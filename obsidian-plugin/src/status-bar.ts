import type MnemePlugin from "./main";

export class MnemeStatusBar {
  private statusBarEl: HTMLElement;
  private plugin: MnemePlugin;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private dotEl: HTMLElement | null = null;
  private textEl: HTMLElement | null = null;

  constructor(statusBarEl: HTMLElement, plugin: MnemePlugin) {
    this.statusBarEl = statusBarEl;
    this.plugin = plugin;

    // Build DOM
    this.statusBarEl.addClass("mneme-status");

    this.dotEl = this.statusBarEl.createSpan({ cls: "mneme-status-dot offline" });
    this.textEl = this.statusBarEl.createSpan({ text: "Mneme..." });

    // Click to refresh
    this.statusBarEl.addEventListener("click", () => {
      this.refresh();
    });
  }

  startPolling(): void {
    // Initial check
    this.refresh();

    // Poll every 30 seconds
    this.intervalId = setInterval(() => {
      this.refresh();
    }, 30000);
  }

  stopPolling(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  async refresh(): Promise<void> {
    try {
      const stats = await this.plugin.client.getStatus();

      if (this.dotEl) {
        this.dotEl.removeClass("offline");
        this.dotEl.addClass("online");
      }

      if (this.textEl) {
        this.textEl.textContent = `${stats.total_notes} Notes | ${stats.total_chunks} Chunks`;
      }
    } catch {
      if (this.dotEl) {
        this.dotEl.removeClass("online");
        this.dotEl.addClass("offline");
      }

      if (this.textEl) {
        this.textEl.textContent = "Mneme offline";
      }
    }
  }
}
