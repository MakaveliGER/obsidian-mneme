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
        "Pfad zur mneme CLI. Standard: 'mneme' (wenn im PATH)."
      )
      .addText((text) =>
        text
          .setPlaceholder("mneme")
          .setValue(this.plugin.settings.mnemePath)
          .onChange(async (value) => {
            this.plugin.settings.mnemePath = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "mneme_path",
              value
            );
          })
      );

    new Setting(containerEl)
      .setName("Auto-Search Modus")
      .setDesc(
        "Steuert, wann Mneme automatisch sucht."
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption("off", "Off — Nur bei explizitem Aufruf")
          .addOption(
            "smart",
            "Smart — Claude sucht proaktiv bei Wissensfragen (empfohlen)"
          )
          .addOption(
            "always",
            "Always — Automatische Suche bei jedem File-Read"
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

    new Setting(containerEl)
      .setName("Search Top-K")
      .setDesc("Anzahl der Suchergebnisse pro Abfrage.")
      .addSlider((slider) =>
        slider
          .setLimits(1, 50, 1)
          .setValue(this.plugin.settings.searchTopK)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.searchTopK = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "search.top_k",
              String(value)
            );
          })
      );

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

    new Setting(advancedContainer)
      .setName("Batch Size")
      .setDesc(
        "Batch-Größe für Embedding-Berechnung. 32 optimal für BGE-M3."
      )
      .addSlider((slider) =>
        slider
          .setLimits(8, 512, 8)
          .setValue(this.plugin.settings.embeddingBatchSize)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.embeddingBatchSize = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "embedding.batch_size",
              String(value)
            );
          })
      );

    this.addSectionTitle(advancedContainer, "Chunking");

    new Setting(advancedContainer)
      .setName("Chunk Max Tokens")
      .setDesc(
        "Maximale Chunk-Größe in Tokens. Größere Chunks = mehr Kontext, weniger Precision."
      )
      .addSlider((slider) =>
        slider
          .setLimits(200, 2000, 50)
          .setValue(this.plugin.settings.chunkMaxTokens)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.chunkMaxTokens = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "chunking.max_tokens",
              String(value)
            );
          })
      );

    new Setting(advancedContainer)
      .setName("Chunk Overlap")
      .setDesc(
        "Überlappung zwischen Chunks in Tokens. Verhindert Informationsverlust an Chunk-Grenzen."
      )
      .addSlider((slider) =>
        slider
          .setLimits(0, 500, 10)
          .setValue(this.plugin.settings.chunkOverlapTokens)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.chunkOverlapTokens = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "chunking.overlap_tokens",
              String(value)
            );
          })
      );

    this.addSectionTitle(advancedContainer, "Suche");

    new Setting(advancedContainer)
      .setName("Vector Weight")
      .setDesc(
        "Gewichtung der Vektorsuche (0.0-1.0). Höher = mehr Semantik."
      )
      .addSlider((slider) =>
        slider
          .setLimits(0, 1, 0.05)
          .setValue(this.plugin.settings.vectorWeight)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.vectorWeight = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "search.vector_weight",
              String(value)
            );
          })
      );

    new Setting(advancedContainer)
      .setName("BM25 Weight")
      .setDesc(
        "Gewichtung der Keyword-Suche (0.0-1.0). Höher = mehr exakte Matches."
      )
      .addSlider((slider) =>
        slider
          .setLimits(0, 1, 0.05)
          .setValue(this.plugin.settings.bm25Weight)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.bm25Weight = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "search.bm25_weight",
              String(value)
            );
          })
      );

    this.addSectionTitle(advancedContainer, "Reranking");

    new Setting(advancedContainer)
      .setName("Reranking aktivieren")
      .setDesc(
        "CrossEncoder Reranking für präzisere Ergebnisse. Langsamer, aber genauer."
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
      new Setting(advancedContainer)
        .setName("Reranking Threshold")
        .setDesc(
          "Mindest-Score für Reranking-Ergebnisse (0.0-1.0)."
        )
        .addSlider((slider) =>
          slider
            .setLimits(0, 1, 0.05)
            .setValue(this.plugin.settings.rerankingThreshold)
            .setDynamicTooltip()
            .onChange(async (value) => {
              this.plugin.settings.rerankingThreshold = value;
              await this.plugin.saveSettings();
              await this.plugin.client.updateConfig(
                "reranking.threshold",
                String(value)
              );
            })
        );
    }

    this.addSectionTitle(advancedContainer, "GARS-Scoring");

    new Setting(advancedContainer)
      .setName("GARS aktivieren")
      .setDesc(
        "Graph-Aware Scoring: Berücksichtigt Wikilink-Vernetzung. Gut vernetzte Notizen werden bevorzugt."
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
      new Setting(advancedContainer)
        .setName("Graph Weight")
        .setDesc(
          "Gewichtung der Graph-Vernetzung im GARS-Score (0.0-1.0)."
        )
        .addSlider((slider) =>
          slider
            .setLimits(0, 1, 0.05)
            .setValue(this.plugin.settings.graphWeight)
            .setDynamicTooltip()
            .onChange(async (value) => {
              this.plugin.settings.graphWeight = value;
              await this.plugin.saveSettings();
              await this.plugin.client.updateConfig(
                "scoring.graph_weight",
                String(value)
              );
            })
        );
    }

    this.addSectionTitle(advancedContainer, "Query Expansion");

    new Setting(advancedContainer)
      .setName("Query Expansion")
      .setDesc(
        "Passt Suchgewichte automatisch an den Query-Typ an: kurze Begriffe → mehr Keyword-Suche, lange Sätze → mehr Semantik. Bringt erst ab ~500 Notizen messbaren Vorteil."
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.queryExpansion ?? false)
          .onChange(async (value) => {
            this.plugin.settings.queryExpansion = value;
            await this.plugin.saveSettings();
            await this.plugin.client.updateConfig(
              "search.query_expansion",
              String(value)
            );
          })
      );

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

    new Setting(advancedContainer)
      .setName("Health Exclude Patterns")
      .setDesc(
        "Komma-getrennte Ordner-Muster die bei Health-Checks ignoriert werden (z.B. templates/**, .trash/**)."
      )
      .addText((text) =>
        text
          .setPlaceholder("templates/**, .trash/**")
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
        "Startet den Mneme-Server beim Öffnen von Obsidian. Der Server überwacht Dateiänderungen automatisch im Hintergrund (Watchdog)."
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
}
