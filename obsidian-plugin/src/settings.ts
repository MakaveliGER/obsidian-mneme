import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type MnemePlugin from "./main";

export class MnemeSettingsTab extends PluginSettingTab {
  plugin: MnemePlugin;

  constructor(app: App, plugin: MnemePlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    // ── Header with branding ──────────────────────
    const header = containerEl.createDiv({ cls: "mneme-settings-header" });
    header.createEl("div", {
      text: "Mneme",
      cls: "mneme-settings-title",
    });
    header.createEl("div", {
      text: "Semantische Vault-Suche",
      cls: "mneme-settings-subtitle",
    });

    // ── Basic Settings ────────────────────────────
    this.addSectionTitle(containerEl, "Grundeinstellungen");

    new Setting(containerEl)
      .setName("Mneme Pfad")
      .setDesc(
        "Pfad zur mneme CLI. Standard: 'mneme' (wenn im PATH). Für isolierte Venvs: voller Pfad zur Binary (z.B. 'D:\\…\\.venv\\Scripts\\mneme.exe')."
      )
      .addText((text) =>
        text
          .setPlaceholder("mneme")
          .setValue(this.plugin.settings.mnemePath)
          .onChange(async (value) => {
            // Plugin-side setting only — there is no mneme_path field in
            // the backend config (the backend doesn't need to know where
            // its own CLI binary lives). Earlier versions called
            // `mneme update-config mneme_path` here which silently errored
            // on every keystroke.
            this.plugin.settings.mnemePath = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Auto-Search Modus")
      .setDesc(
        "Nur relevant wenn Mneme über Claude Code / Claudian als MCP-Server genutzt wird. Steuert, ob Claude proaktiv im Vault sucht."
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption(
            "off",
            "Off — Claude sucht nur wenn explizit das 'search' Tool aufgerufen wird"
          )
          .addOption(
            "smart",
            "Smart — CLAUDE.md-Hinweis empfiehlt Suche bei Wissensfragen (empfohlen)"
          )
          .addOption(
            "always",
            "Always — PreToolUse-Hook injiziert bei jedem Read-Tool-Call vorher Vault-Kontext"
          )
          .setValue(this.plugin.settings.autoSearchMode)
          .onChange(async (value: string) => {
            this.plugin.settings.autoSearchMode = value as
              | "off"
              | "smart"
              | "always";
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "auto_search.mode",
              value
            );
          })
      );

    this.addSliderSetting(containerEl, {
      name: "Search Top-K",
      desc: "Anzahl Suchergebnisse pro Abfrage. Höher = mehr Kontext, aber langsamer und mehr Rauschen.",
      min: 1,
      max: 50,
      step: 1,
      value: this.plugin.settings.searchTopK,
      onChange: async (value) => {
        this.plugin.settings.searchTopK = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("search.top_k", String(value));
      },
    });

    new Setting(containerEl)
      .setName("Embedding Device")
      .setDesc(
        "GPU-Beschleunigung: auto erkennt GPU automatisch."
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption("auto", "Auto (GPU-Erkennung)")
          .addOption("cpu", "CPU")
          .addOption("cuda", "CUDA / ROCm GPU")
          .setValue(this.plugin.settings.embeddingDevice)
          .onChange(async (value: string) => {
            this.plugin.settings.embeddingDevice = value as
              | "auto"
              | "cpu"
              | "cuda";
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "embedding.device",
              value
            );
          })
      );

    new Setting(containerEl)
      .setName("Embedding dtype")
      .setDesc(
        "Datentyp: float16 optimal für GPU (AMD), bfloat16 für CPU."
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption("float16", "float16")
          .addOption("bfloat16", "bfloat16")
          .addOption("float32", "float32")
          .setValue(this.plugin.settings.embeddingDtype)
          .onChange(async (value: string) => {
            this.plugin.settings.embeddingDtype = value as
              | "float16"
              | "bfloat16"
              | "float32";
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "embedding.dtype",
              value
            );
          })
      );

    // ── Advanced Toggle ───────────────────────────
    const advancedToggle = containerEl.createDiv({
      cls: "mneme-advanced-toggle",
    });
    advancedToggle.textContent = this.plugin.settings.showAdvanced
      ? "▼ Erweiterte Einstellungen"
      : "▶ Erweiterte Einstellungen";

    const advancedContainer = containerEl.createDiv();
    advancedContainer.style.display = this.plugin.settings.showAdvanced
      ? "block"
      : "none";

    advancedToggle.addEventListener("click", async () => {
      this.plugin.settings.showAdvanced =
        !this.plugin.settings.showAdvanced;
      await this.plugin.saveSettings();
      advancedToggle.textContent = this.plugin.settings.showAdvanced
        ? "▼ Erweiterte Einstellungen"
        : "▶ Erweiterte Einstellungen";
      advancedContainer.style.display = this.plugin.settings.showAdvanced
        ? "block"
        : "none";
    });

    // ── Advanced Settings ─────────────────────────
    this.addSectionTitle(advancedContainer, "Embedding");

    new Setting(advancedContainer)
      .setName("Embedding Model")
      .setDesc(
        "BGE-M3 empfohlen (multilingual, MIT-Lizenz)."
      )
      .addText((text) =>
        text
          .setPlaceholder("BAAI/bge-m3")
          .setValue(this.plugin.settings.embeddingModel)
          .onChange(async (value) => {
            this.plugin.settings.embeddingModel = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "embedding.model",
              value
            );
          })
      );

    this.addSliderSetting(advancedContainer, {
      name: "Batch Size",
      desc: "Embedding-Batch-Größe. Höher = schneller auf GPU (braucht mehr VRAM), niedriger = weniger Memory. 32 optimal für BGE-M3.",
      min: 8,
      max: 512,
      step: 8,
      value: this.plugin.settings.embeddingBatchSize,
      onChange: async (value) => {
        this.plugin.settings.embeddingBatchSize = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("embedding.batch_size", String(value));
      },
    });

    this.addSectionTitle(advancedContainer, "Chunking");

    this.addSliderSetting(advancedContainer, {
      name: "Chunk Max Tokens",
      desc: "Maximale Chunk-Größe in Tokens. Größere Chunks = mehr Kontext, weniger Precision.",
      min: 200,
      max: 2000,
      step: 50,
      value: this.plugin.settings.chunkMaxTokens,
      onChange: async (value) => {
        this.plugin.settings.chunkMaxTokens = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("chunking.max_tokens", String(value));
      },
    });

    this.addSliderSetting(advancedContainer, {
      name: "Chunk Overlap",
      desc: "Überlappung zwischen Chunks in Tokens. Verhindert Informationsverlust an Chunk-Grenzen.",
      min: 0,
      max: 500,
      step: 10,
      value: this.plugin.settings.chunkOverlapTokens,
      onChange: async (value) => {
        this.plugin.settings.chunkOverlapTokens = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("chunking.overlap_tokens", String(value));
      },
    });

    this.addSectionTitle(advancedContainer, "Suche");

    this.addSliderSetting(advancedContainer, {
      name: "Vector Weight",
      desc: "Gewichtung der Vektorsuche (0.0-1.0). Höher = mehr Semantik.",
      min: 0,
      max: 1,
      step: 0.05,
      value: this.plugin.settings.vectorWeight,
      format: (v) => v.toFixed(2),
      onChange: async (value) => {
        this.plugin.settings.vectorWeight = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("search.vector_weight", String(value));
      },
    });

    this.addSliderSetting(advancedContainer, {
      name: "BM25 Weight",
      desc: "Gewichtung der Keyword-Suche (0.0-1.0). Höher = mehr exakte Matches.",
      min: 0,
      max: 1,
      step: 0.05,
      value: this.plugin.settings.bm25Weight,
      format: (v) => v.toFixed(2),
      onChange: async (value) => {
        this.plugin.settings.bm25Weight = value;
        await this.plugin.saveSettings();
        await this.plugin.client.updateConfig("search.bm25_weight", String(value));
      },
    });

    this.addSectionTitle(advancedContainer, "Reranking");

    advancedContainer.createEl("p", {
      text: "⚠ Erst ab ~500 Notizen sinnvoll. Bei kleineren Vaults wurde ein Relevanz-Verlust von -7.6 % gemessen (Hit@1 gegen BM25+Vector).",
      cls: "setting-item-description mneme-warning-text",
    });

    new Setting(advancedContainer)
      .setName("Reranking aktivieren")
      .setDesc(
        "CrossEncoder-Reranking (BGE-reranker-v2-m3) ordnet Top-N Treffer per Query-Dokument-Matching neu. Langsamer, bei großen Vaults genauer."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.rerankingEnabled)
          .onChange(async (value) => {
            this.plugin.settings.rerankingEnabled = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "reranking.enabled",
              String(value)
            );
            // Re-render to show/hide threshold slider
            this.display();
          })
      );

    if (this.plugin.settings.rerankingEnabled) {
      this.addSliderSetting(advancedContainer, {
        name: "Reranking Threshold",
        desc: "Mindest-Score für Reranking-Ergebnisse (0.0-1.0). Höher = strenger filtern.",
        min: 0,
        max: 1,
        step: 0.05,
        value: this.plugin.settings.rerankingThreshold,
        format: (v) => v.toFixed(2),
        onChange: async (value) => {
          this.plugin.settings.rerankingThreshold = value;
          await this.plugin.saveSettings();
          await this.plugin.client.updateConfig("reranking.threshold", String(value));
        },
      });
    }

    this.addSectionTitle(advancedContainer, "GARS-Scoring");

    advancedContainer.createEl("p", {
      text: "⚠ Erst ab ~500 Notizen sinnvoll. Bei kleineren Vaults wurde ein Relevanz-Verlust von -21 % gemessen (Hit@1 gegen BM25+Vector).",
      cls: "setting-item-description mneme-warning-text",
    });

    new Setting(advancedContainer)
      .setName("GARS aktivieren")
      .setDesc(
        "Graph-Aware Ranking Score: multipliziert Suchtreffer mit der Wikilink-Zentralität. Gut vernetzte Notizen ranken höher."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.garsEnabled)
          .onChange(async (value) => {
            this.plugin.settings.garsEnabled = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "scoring.gars_enabled",
              String(value)
            );
            this.display();
          })
      );

    if (this.plugin.settings.garsEnabled) {
      this.addSliderSetting(advancedContainer, {
        name: "Graph Weight",
        desc: "Gewichtung der Graph-Vernetzung im GARS-Score (0.0-1.0). Höher = vernetzte Notizen stärker bevorzugen.",
        min: 0,
        max: 1,
        step: 0.05,
        value: this.plugin.settings.graphWeight,
        format: (v) => v.toFixed(2),
        onChange: async (value) => {
          this.plugin.settings.graphWeight = value;
          await this.plugin.saveSettings();
          await this.plugin.client.updateConfig("scoring.graph_weight", String(value));
        },
      });
    }

    this.addSectionTitle(advancedContainer, "Auto-Search");

    new Setting(advancedContainer)
      .setName("Hook Matchers")
      .setDesc(
        "Komma-getrennte Tool-Namen für Always-Modus (z.B. Read, Bash, WebFetch)."
      )
      .addText((text) =>
        text
          .setPlaceholder("Read")
          .setValue(this.plugin.settings.hookMatchers.join(", "))
          .onChange(async (value) => {
            this.plugin.settings.hookMatchers = value
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s.length > 0);
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "auto_search.hook_matchers",
              this.plugin.settings.hookMatchers.join(",")
            );
          })
      );

    this.addSectionTitle(advancedContainer, "Health");

    advancedContainer.createEl("p", {
      text: "Health-Check prüft den Vault auf verwaiste Notizen (ohne eingehende Links), schwache Verlinkung (<2 Links), veraltete Notizen (>180 Tage nicht geändert) und nahezu-Duplikate. Die Exclude-Patterns betreffen NUR diese Analyse — nicht den Such-Index.",
      cls: "setting-item-description",
    });

    new Setting(advancedContainer)
      .setName("Health Exclude Patterns")
      .setDesc(
        "Komma-getrennte Glob-Muster die im Health-Report ignoriert werden. Beispiele: '04 Ressourcen/**/Newsletter/**' (externe Inhalte), '05 Daily Notes/**' (Journal)."
      )
      .addText((text) =>
        text
          .setPlaceholder("templates/**, 05 Daily Notes/**")
          .setValue(
            this.plugin.settings.healthExcludePatterns.join(", ")
          )
          .onChange(async (value) => {
            this.plugin.settings.healthExcludePatterns = value
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s.length > 0);
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "health.exclude_patterns",
              this.plugin.settings.healthExcludePatterns.join(",")
            );
          })
      );

    // ── Server & Sync ──────────────────────────────
    this.addSectionTitle(containerEl, "Server & Synchronisation");

    new Setting(containerEl)
      .setName("Server automatisch starten")
      .setDesc(
        "Startet einen Mneme-Server beim Öffnen von Obsidian für Live-File-Monitoring (Watchdog). Lädt ~5 GB RAM für das Embedding-Modell. Nur aktivieren, wenn du Dateiänderungen während Obsidian-Sessions live indexiert haben willst. MCP-Clients (Claude Code / Claudian) starten ihren eigenen Server — dieser hier wäre parallel und redundant. Default: Aus."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.autoStartServer)
          .onChange(async (value) => {
            this.plugin.settings.autoStartServer = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Reindex bei Start")
      .setDesc(
        "Synchronisiert den Index beim Öffnen von Obsidian. Wichtig wenn Notizen extern geändert wurden (z.B. über Obsidian Sync, Mobile, oder einen anderen Rechner)."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.reindexOnStart)
          .onChange(async (value) => {
            this.plugin.settings.reindexOnStart = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Reindex beim Schließen")
      .setDesc(
        "Stellt sicher, dass alle Änderungen vor dem Beenden indexiert sind. Nützlich wenn andere Geräte denselben Index nutzen."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.reindexOnClose)
          .onChange(async (value) => {
            this.plugin.settings.reindexOnClose = value;
            await this.plugin.saveSettings();
          })
      );

    containerEl.createEl("p", {
      text: "ℹ️ Der Watchdog erfasst automatisch alle Dateiänderungen während Obsidian läuft. Ein manueller Reindex ist nur nötig wenn Notizen außerhalb von Obsidian geändert wurden.",
      cls: "setting-item-description",
    });

    // ── Action Buttons ────────────────────────────
    this.addSectionTitle(containerEl, "Aktionen");

    new Setting(containerEl)
      .setName("Reindex starten")
      .setDesc(
        "Indexiert alle Vault-Notizen neu. Geänderte Dateien werden automatisch erkannt."
      )
      .addButton((button) =>
        button
          .setButtonText("Reindex starten")
          .setCta()
          .onClick(async () => {
            await this.plugin.runReindex();
          })
      );

    new Setting(containerEl)
      .setName("Vault Health Check")
      .setDesc(
        "Prüft den Vault auf verwaiste Notizen, schwache Verlinkung und Duplikate."
      )
      .addButton((button) =>
        button
          .setButtonText("Health Check")
          .onClick(async () => {
            await this.plugin.showHealthReport();
          })
      );
  }

  /** Add a styled section title */
  private addSectionTitle(
    containerEl: HTMLElement,
    title: string
  ): void {
    containerEl.createEl("div", {
      text: title,
      cls: "mneme-settings-section-title",
    });
  }

  /** Add a slider setting with a persistent numeric value display next to it. */
  private addSliderSetting(
    container: HTMLElement,
    opts: {
      name: string;
      desc: string;
      min: number;
      max: number;
      step: number;
      value: number;
      format?: (v: number) => string;
      onChange: (v: number) => Promise<void>;
    }
  ): void {
    const fmt = opts.format ?? ((v: number) => String(v));
    let displayEl: HTMLElement;

    const setting = new Setting(container)
      .setName(opts.name)
      .setDesc(opts.desc)
      .addSlider((slider) => {
        slider
          .setLimits(opts.min, opts.max, opts.step)
          .setValue(opts.value)
          .setDynamicTooltip()
          .onChange(async (value) => {
            if (displayEl) displayEl.textContent = fmt(value);
            await opts.onChange(value);
          });
      });

    displayEl = setting.controlEl.createSpan({
      cls: "mneme-slider-value",
      text: fmt(opts.value),
    });
  }
}
