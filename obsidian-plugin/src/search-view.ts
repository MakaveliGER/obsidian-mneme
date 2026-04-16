import { ItemView, WorkspaceLeaf } from "obsidian";
import type MnemePlugin from "./main";
import type { SearchResult } from "./types";

export const SEARCH_VIEW_TYPE = "mneme-search-view";

export class MnemeSearchView extends ItemView {
  private plugin: MnemePlugin;
  private activeTab: string = "search";
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private leafChangeRef: ReturnType<typeof this.app.workspace.on> | null = null;

  constructor(leaf: WorkspaceLeaf, plugin: MnemePlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return SEARCH_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "Mneme Search";
  }

  getIcon(): string {
    return "mneme";
  }

  async onOpen(): Promise<void> {
    this.leafChangeRef = this.app.workspace.on("active-leaf-change", () => {
      if (this.activeTab === "similar") {
        this.renderSimilarTab();
      }
    });
    this.registerEvent(this.leafChangeRef);
    this.render();
  }

  async onClose(): Promise<void> {
    this.leafChangeRef = null;
  }

  /** Switch active tab programmatically (called from main.ts) */
  setActiveTab(tab: string): void {
    this.activeTab = tab;
    this.render();
  }

  private render(): void {
    const { containerEl } = this;
    containerEl.empty();

    const container = containerEl.createDiv({ cls: "mneme-search-container" });

    // Tab bar
    const tabs = container.createDiv({ cls: "mneme-tabs" });

    const searchTab = tabs.createEl("button", {
      cls: `mneme-tab ${this.activeTab === "search" ? "active" : ""}`,
      text: "Suche",
    });
    searchTab.addEventListener("click", () => {
      this.activeTab = "search";
      this.render();
    });

    const similarTab = tabs.createEl("button", {
      cls: `mneme-tab ${this.activeTab === "similar" ? "active" : ""}`,
      text: "Ähnliche Notizen",
    });
    similarTab.addEventListener("click", () => {
      this.activeTab = "similar";
      this.render();
    });

    // Content area
    if (this.activeTab === "search") {
      this.renderSearchTab(container);
    } else {
      this.renderSimilarTab(container);
    }
  }

  private renderSearchTab(parent?: HTMLElement): void {
    const container = parent ?? this.containerEl.querySelector(".mneme-search-container") as HTMLElement;
    if (!container) return;

    // Remove existing content below tabs (keep tabs)
    if (!parent) {
      const tabs = container.querySelector(".mneme-tabs");
      container.empty();
      if (tabs) container.appendChild(tabs);
    }

    // Search input row
    const inputRow = container.createDiv({ cls: "mneme-search-input-row" });
    const input = inputRow.createEl("input", {
      cls: "mneme-search-input",
      attr: { type: "text", placeholder: "Vault durchsuchen..." },
    });
    const btn = inputRow.createEl("button", {
      cls: "mneme-search-btn",
      text: "Suchen",
    });

    // Results area
    const resultsEl = container.createDiv({ cls: "mneme-results" });
    resultsEl.createDiv({ cls: "mneme-empty", text: "Suchbegriff eingeben..." });

    const doSearch = async () => {
      const query = input.value.trim();
      if (!query) {
        resultsEl.empty();
        resultsEl.createDiv({ cls: "mneme-empty", text: "Suchbegriff eingeben..." });
        return;
      }

      resultsEl.empty();
      resultsEl.createDiv({ cls: "mneme-loading", text: "Suche läuft..." });

      try {
        const results = await this.plugin.client.search(query, this.plugin.settings.searchTopK);
        resultsEl.empty();

        if (results.length === 0) {
          resultsEl.createDiv({ cls: "mneme-empty", text: "Keine Ergebnisse" });
          return;
        }

        this.renderResults(resultsEl, results);
      } catch (err: unknown) {
        resultsEl.empty();
        const msg = err instanceof Error ? err.message : "Unbekannter Fehler";
        resultsEl.createDiv({ cls: "mneme-empty", text: `Fehler: ${msg}` });
      }
    };

    // Debounced search on input
    input.addEventListener("input", () => {
      if (this.debounceTimer) clearTimeout(this.debounceTimer);
      this.debounceTimer = setTimeout(doSearch, 300);
    });

    // Immediate search on button click
    btn.addEventListener("click", () => {
      if (this.debounceTimer) clearTimeout(this.debounceTimer);
      doSearch();
    });

    // Search on Enter
    input.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        if (this.debounceTimer) clearTimeout(this.debounceTimer);
        doSearch();
      }
    });

    // Focus input
    input.focus();
  }

  private async renderSimilarTab(parent?: HTMLElement): Promise<void> {
    const container = parent ?? this.containerEl.querySelector(".mneme-search-container") as HTMLElement;
    if (!container) return;

    // Remove existing content below tabs (keep tabs)
    if (!parent) {
      const tabs = container.querySelector(".mneme-tabs");
      container.empty();
      if (tabs) container.appendChild(tabs);
    }

    const resultsEl = container.createDiv({ cls: "mneme-results" });

    const activeFile = this.app.workspace.getActiveFile();
    if (!activeFile) {
      resultsEl.createDiv({ cls: "mneme-empty", text: "Keine aktive Notiz" });
      return;
    }

    const noteTitle = activeFile.basename;
    resultsEl.createDiv({ cls: "mneme-loading", text: "Suche läuft..." });

    try {
      const results = await this.plugin.client.search(noteTitle, this.plugin.settings.searchTopK);
      resultsEl.empty();

      // Filter out the active note itself
      const filtered = results.filter((r) => r.path !== activeFile.path);

      if (filtered.length === 0) {
        resultsEl.createDiv({ cls: "mneme-empty", text: "Keine Ergebnisse" });
        return;
      }

      this.renderResults(resultsEl, filtered);
    } catch (err: unknown) {
      resultsEl.empty();
      const msg = err instanceof Error ? err.message : "Unbekannter Fehler";
      resultsEl.createDiv({ cls: "mneme-empty", text: `Fehler: ${msg}` });
    }
  }

  private renderResults(container: HTMLElement, results: SearchResult[]): void {
    for (const result of results) {
      const item = container.createDiv({ cls: "mneme-result-item" });

      // Header row: title + score badge
      const header = item.createDiv({ cls: "mneme-result-header" });
      header.createSpan({ cls: "mneme-result-title", text: result.title || result.path });

      const scoreClass =
        result.score >= 0.75
          ? "mneme-score-high"
          : result.score >= 0.5
            ? "mneme-score-mid"
            : "mneme-score-low";
      header.createSpan({
        cls: `mneme-result-score ${scoreClass}`,
        text: result.score.toFixed(2),
      });

      // Path
      item.createDiv({ cls: "mneme-result-path", text: result.path });

      // Content preview (2 lines handled by CSS -webkit-line-clamp)
      if (result.content) {
        item.createDiv({ cls: "mneme-result-preview", text: result.content });
      }

      // Click to open note
      item.addEventListener("click", () => {
        this.app.workspace.openLinkText(result.path, "");
      });
    }
  }
}
