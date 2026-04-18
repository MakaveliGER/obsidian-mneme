import { Plugin, WorkspaceLeaf, Notice, addIcon } from "obsidian";
import { MnemeClient } from "./mneme-client";
import { MnemeSettingsTab } from "./settings";
import { MnemeSearchView, SEARCH_VIEW_TYPE } from "./search-view";
import { MnemeStatusBar } from "./status-bar";
import { MnemeHealthModal } from "./health-modal";
import type { MnemeSettings } from "./types";
import { DEFAULT_SETTINGS } from "./types";

/** Custom Mneme icon — Muse silhouette SVG.
 *
 * Fill is hardcoded to the brand gold (#C9A84C) matching the banner
 * wordmark — this is a brand asset, intentionally theme-agnostic.
 * The explicit `fill` attribute on the <g> overrides Obsidian's
 * default `currentColor` inheritance on the wrapper <svg>. */
const MNEME_ICON_SVG = `<g fill="#C9A84C" transform="translate(0,100) scale(0.039,-0.039)"><path d="M1709 2137 c-24 -13 -54 -38 -66 -56 l-22 -33 6 51 c7 60 -4 65 -60 27 -34 -24 -36 -24 -79 -8 -65 24 -258 28 -338 8 -164 -42 -314 -184 -345 -323 -5 -24 -12 -33 -26 -33 -26 0 -89 -33 -111 -57 -65 -71 -84 -239 -40 -338 41 -89 101 -136 176 -137 36 -1 44 -6 69 -40 30 -42 78 -68 125 -68 l29 0 -12 -54 c-21 -92 -37 -129 -76 -188 -22 -31 -39 -61 -39 -67 0 -6 -19 -15 -42 -21 -32 -9 -58 -28 -101 -72 -112 -117 -131 -157 -64 -137 17 5 69 10 113 10 92 0 152 -17 292 -82 232 -109 398 -138 560 -97 27 7 42 16 42 26 0 46 -184 263 -210 247 -5 -3 -10 -2 -10 2 0 23 71 218 82 225 7 5 50 6 95 2 52 -4 94 -2 117 6 46 15 70 58 62 110 -4 27 -2 41 9 50 8 7 15 25 15 41 0 15 5 31 11 35 7 4 9 20 6 40 -5 32 -4 34 33 44 23 6 41 18 45 29 3 11 -11 61 -35 119 -26 64 -40 116 -40 144 0 24 -5 70 -10 101 -10 52 -9 59 12 87 48 66 16 190 -61 236 -16 10 -32 26 -34 36 -4 14 -15 18 -47 18 l-42 0 29 28 c35 32 66 88 58 102 -9 15 -28 12 -76 -13z"/></g>`;

export default class MnemePlugin extends Plugin {
  settings: MnemeSettings = DEFAULT_SETTINGS;
  client: MnemeClient = new MnemeClient();
  statusBar: MnemeStatusBar | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();

    // Register custom icon
    addIcon("mneme", MNEME_ICON_SVG);

    // Update client path from settings
    this.client.setPath(this.settings.mnemePath);

    // Register search view
    this.registerView(SEARCH_VIEW_TYPE, (leaf: WorkspaceLeaf) => {
      return new MnemeSearchView(leaf, this);
    });

    // Ribbon icon — opens search panel
    this.addRibbonIcon("mneme", "Mneme — Vault Search", () => {
      this.activateSearchView();
    });

    // Status bar
    this.statusBar = new MnemeStatusBar(this.addStatusBarItem(), this);
    this.statusBar.startPolling();

    // Settings tab
    this.addSettingTab(new MnemeSettingsTab(this.app, this));

    // Commands
    this.addCommand({
      id: "mneme-search",
      name: "Search vault",
      callback: () => this.activateSearchView(),
    });

    this.addCommand({
      id: "mneme-reindex",
      name: "Reindex vault",
      callback: () => this.runReindex(),
    });

    this.addCommand({
      id: "mneme-similar",
      name: "Show similar notes",
      callback: () => this.activateSearchView("similar"),
    });

    this.addCommand({
      id: "mneme-health",
      name: "Vault health check",
      callback: () => this.showHealthReport(),
    });

    // Server lifecycle: auto-start + reindex on startup
    this.app.workspace.onLayoutReady(() => {
      this.onStartup();
    });
  }

  onunload(): void {
    this.statusBar?.stopPolling();
    this.onShutdown();
  }

  /** Called when Obsidian layout is ready — start HTTP server + optional reindex */
  private async onStartup(): Promise<void> {
    // Auto-start HTTP server (if enabled and not already running)
    if (this.settings.autoStartServer) {
      const status = await this.client.startHttpServer(
        this.settings.serverPort,
        this.settings.keepServerRunningAfterClose,
      );
      if (status === "already-running") {
        new Notice(
          `Mneme: Server läuft bereits auf Port ${this.settings.serverPort}`,
          3000,
        );
      } else if (status === "started") {
        new Notice(
          `Mneme: HTTP-Server gestartet (Port ${this.settings.serverPort})`,
          3000,
        );
      } else if (status === "blocked") {
        new Notice(
          "Mneme: Pfad-Sicherheitsprüfung fehlgeschlagen. Der konfigurierte Pfad endet nicht auf 'mneme' oder 'mneme.exe'. Bearbeite die Einstellungen.",
          12000,
        );
        return;
      } else {
        new Notice(
          "Mneme: Server konnte nicht gestartet werden. Prüfe den Pfad in den Settings.",
          8000,
        );
        return;
      }

      // Wait until the model is actually loaded (eager-init completes).
      // Running reindex before model_loaded=true would block on the cold
      // import path and is confusing — skip instead if it doesn't warm up.
      const warm = await this.client.waitUntilWarm(
        this.settings.serverPort,
        60000,
      );
      if (!warm) {
        new Notice(
          "Mneme: Server-Warmup dauert ungewöhnlich lang. Reindex wird übersprungen — nächster Start sollte schneller sein (warme Caches).",
          8000,
        );
        return;
      }

      // Enable the HTTP fast-path for search/similar/stats/etc. Plugin
      // UI queries now go via fetch() → ~10ms round-trip instead of
      // spawning a fresh Python process per call (2-3s cold).
      this.client.setHttpPort(this.settings.serverPort);
      new Notice(
        `Mneme: HTTP-Fast-Path aktiv (Port ${this.settings.serverPort})`,
        3000,
      );
    } else {
      // autoStartServer disabled — every search will spawn a CLI subprocess
      // (2-3s cold per call + model reload). Visible notice so the user
      // knows why their queries are slow.
      new Notice(
        "Mneme: Auto-Start ist deaktiviert. Suchen laufen über CLI-Fallback und sind entsprechend langsam. Aktivier Auto-Start in den Settings für bessere Performance.",
        8000,
      );
    }

    // Reindex on start (catches offline changes + sync) — only after warmup.
    if (this.settings.reindexOnStart) {
      try {
        const result = await this.client.reindex(false);
        if (result.indexed > 0 || result.deleted > 0) {
          new Notice(
            `Mneme: Sync abgeschlossen — ${result.indexed} aktualisiert, ${result.deleted} gelöscht (${result.duration_seconds.toFixed(1)}s)`,
            5000,
          );
        }
        this.statusBar?.refresh();
      } catch {
        // Silent — server might have died between warmup and reindex
      }
    }
  }

  /** Called when Obsidian closes — optional reindex, keep server running by default */
  private async onShutdown(): Promise<void> {
    // Reindex on close
    if (this.settings.reindexOnClose) {
      try {
        await this.client.reindex(false);
      } catch {
        // Silent — we're shutting down
      }
    }

    // Disable the HTTP fast-path so any late calls that slip past unload
    // don't keep firing requests at a server that may be gone.
    this.client.setHttpPort(null);

    // Only stop the server if the user opted into the non-persistent mode.
    // The default is to keep it running so Claudian (and the next Obsidian
    // session) find it already warm — cold-start cost is paid once per boot.
    if (!this.settings.keepServerRunningAfterClose) {
      this.client.stopServer();
    }
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    this.client.setPath(this.settings.mnemePath);
  }

  /** Open or focus the search sidebar */
  async activateSearchView(tab?: string): Promise<void> {
    const existing =
      this.app.workspace.getLeavesOfType(SEARCH_VIEW_TYPE);

    if (existing.length > 0) {
      this.app.workspace.revealLeaf(existing[0]);
      if (tab) {
        const view = existing[0].view as MnemeSearchView;
        view.setActiveTab(tab);
      }
      return;
    }

    const leaf = this.app.workspace.getRightLeaf(false);
    if (leaf) {
      await leaf.setViewState({ type: SEARCH_VIEW_TYPE, active: true });
      this.app.workspace.revealLeaf(leaf);
      if (tab) {
        const view = leaf.view as MnemeSearchView;
        view.setActiveTab(tab);
      }
    }
  }

  /** Run reindex with progress notification */
  async runReindex(full: boolean = false): Promise<void> {
    const notice = new (await import("obsidian")).Notice(
      "Mneme: Reindex gestartet...",
      0
    );
    try {
      const result = await this.client.reindex(full);
      notice.hide();
      new (await import("obsidian")).Notice(
        `Mneme: Reindex abgeschlossen — ${result.indexed} indexiert, ${result.skipped} übersprungen, ${result.deleted} gelöscht (${result.duration_seconds.toFixed(1)}s)`,
        8000
      );
      this.statusBar?.refresh();
    } catch (err: unknown) {
      notice.hide();
      const msg =
        err instanceof Error ? err.message : "Unbekannter Fehler";
      new (await import("obsidian")).Notice(
        `Mneme: Reindex fehlgeschlagen — ${msg}`,
        10000
      );
    }
  }

  /** Show vault health report modal */
  async showHealthReport(): Promise<void> {
    const modal = new MnemeHealthModal(this.app, this);
    modal.open();
  }
}
