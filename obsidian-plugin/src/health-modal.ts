import { App, Modal } from "obsidian";
import type MnemePlugin from "./main";
import type { HealthReport } from "./types";

export class MnemeHealthModal extends Modal {
  private plugin: MnemePlugin;

  constructor(app: App, plugin: MnemePlugin) {
    super(app);
    this.plugin = plugin;
  }

  async onOpen(): Promise<void> {
    const { contentEl } = this;
    contentEl.addClass("mneme-health-modal");
    contentEl.createEl("p", { text: "Lade Health Report..." });

    try {
      const report = await this.plugin.client.healthCheck();
      contentEl.empty();
      this.renderReport(contentEl, report);
    } catch (err: unknown) {
      contentEl.empty();
      const msg = err instanceof Error ? err.message : "Unbekannter Fehler";
      contentEl.createEl("p", {
        text: `Fehler: ${msg}`,
        cls: "mneme-empty",
      });
    }
  }

  private renderReport(el: HTMLElement, report: HealthReport): void {
    const sections: Array<{
      title: string;
      items: Array<{ path: string; label: string }>;
    }> = [];

    if (report.orphan_pages) {
      sections.push({
        title: "Orphan Pages",
        items: report.orphan_pages.map((n) => ({
          path: n.path,
          label: n.title || n.path,
        })),
      });
    }

    if (report.weakly_linked) {
      sections.push({
        title: "Weakly Linked",
        items: report.weakly_linked.map((n) => ({
          path: n.path,
          label: `${n.title || n.path} (${n.suggestions.length} Vorschläge)`,
        })),
      });
    }

    if (report.stale_notes) {
      sections.push({
        title: "Stale Notes",
        items: report.stale_notes.map((n) => ({
          path: n.path,
          label: `${n.title || n.path} (${n.days_stale} Tage)`,
        })),
      });
    }

    if (report.near_duplicates) {
      sections.push({
        title: "Near Duplicates",
        items: report.near_duplicates.map((n) => ({
          path: n.path_a,
          label: `${n.path_a} ↔ ${n.path_b} (${(n.similarity * 100).toFixed(0)}%)`,
        })),
      });
    }

    for (const section of sections) {
      const sectionEl = el.createDiv({ cls: "mneme-health-section" });

      const headerEl = sectionEl.createDiv({ cls: "mneme-health-header" });
      headerEl.createSpan({ text: section.title });
      headerEl.createSpan({
        text: `${section.items.length}`,
        cls: "mneme-health-count",
      });

      const itemsEl = sectionEl.createDiv({ cls: "mneme-health-items" });

      // Start collapsed
      itemsEl.style.display = "none";

      headerEl.addEventListener("click", () => {
        itemsEl.style.display =
          itemsEl.style.display === "none" ? "block" : "none";
      });

      for (const item of section.items) {
        const itemEl = itemsEl.createDiv({
          cls: "mneme-health-item",
          text: item.label,
        });
        itemEl.addEventListener("click", () => {
          this.app.workspace.openLinkText(item.path, "");
          this.close();
        });
      }
    }

    // Copy button
    const btnEl = el.createEl("button", {
      text: "Bericht kopieren",
      cls: "mneme-search-btn",
    });
    btnEl.style.marginTop = "16px";
    btnEl.addEventListener("click", () => {
      const markdown = this.reportToMarkdown(report, sections);
      navigator.clipboard.writeText(markdown);
      btnEl.textContent = "Kopiert!";
      setTimeout(() => {
        btnEl.textContent = "Bericht kopieren";
      }, 2000);
    });
  }

  private reportToMarkdown(
    _report: HealthReport,
    sections: Array<{
      title: string;
      items: Array<{ path: string; label: string }>;
    }>
  ): string {
    const lines: string[] = ["# Mneme Health Report", ""];

    for (const section of sections) {
      lines.push(`## ${section.title} (${section.items.length})`);
      for (const item of section.items) {
        lines.push(`- [[${item.path}]] — ${item.label}`);
      }
      lines.push("");
    }

    return lines.join("\n");
  }

  onClose(): void {
    this.contentEl.empty();
  }
}
