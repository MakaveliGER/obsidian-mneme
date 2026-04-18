import { execFile, spawn, ChildProcess } from "child_process";
import { promisify } from "util";
import type {
  SearchResult,
  VaultStats,
  ReindexResult,
  HealthReport,
  MnemeConfig,
} from "./types";

const execFileAsync = promisify(execFile);

/**
 * Client for communicating with the Mneme Python backend via CLI.
 * All operations are async and return parsed JSON responses.
 * Can also manage the MCP server process lifecycle.
 */
export class MnemeClient {
  private serverProcess: ChildProcess | null = null;

  constructor(private mnemePath: string = "mneme") {}

  setPath(path: string): void {
    this.mnemePath = path;
  }

  /** Ping the HTTP server's /health endpoint. Returns true if it responds. */
  async isHttpServerHealthy(port: number = 8765): Promise<boolean> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const response = await fetch(`http://127.0.0.1:${port}/health`, {
        method: "GET",
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      return response.ok;
    } catch {
      return false;
    }
  }

  /** Start the Mneme HTTP server as a detached background process.
   *
   * Returns "already-running" if an HTTP server is already responding on
   * the configured port (Obsidian-restart case), "started" if we spawned
   * a new one, "failed" on error.
   *
   * The process is detached + unref'd so it survives Obsidian close — this
   * preserves the cold-start cost across sessions and means Claudian finds
   * the server warm even if Obsidian is closed.
   */
  async startHttpServer(
    port: number = 8765,
    detached: boolean = true
  ): Promise<"started" | "already-running" | "failed"> {
    if (await this.isHttpServerHealthy(port)) {
      return "already-running";
    }
    try {
      const child = spawn(
        this.mnemePath,
        ["serve", "--transport", "streamable-http", "--port", String(port)],
        {
          stdio: "ignore",
          detached,
          windowsHide: true,
          env: { ...process.env, PYTHONIOENCODING: "utf-8" },
        }
      );

      child.on("error", () => {
        this.serverProcess = null;
      });

      if (detached) {
        // Decouple from parent — Obsidian can exit while the server keeps
        // running. We deliberately do NOT keep a reference here.
        child.unref();
        this.serverProcess = null;
      } else {
        this.serverProcess = child;
        child.on("exit", () => {
          this.serverProcess = null;
        });
      }
      return "started";
    } catch {
      this.serverProcess = null;
      return "failed";
    }
  }

  /** Legacy stdio-spawn — kept for tests / backward compat, not used in v0.3+ */
  startServer(): boolean {
    if (this.serverProcess && !this.serverProcess.killed) {
      return true;
    }
    try {
      this.serverProcess = spawn(this.mnemePath, ["serve"], {
        stdio: "ignore",
        detached: false,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });
      this.serverProcess.on("error", () => {
        this.serverProcess = null;
      });
      this.serverProcess.on("exit", () => {
        this.serverProcess = null;
      });
      return true;
    } catch {
      this.serverProcess = null;
      return false;
    }
  }

  /** Stop the Mneme server process we spawned (only works if NOT detached) */
  stopServer(): void {
    if (this.serverProcess && !this.serverProcess.killed) {
      this.serverProcess.kill();
      this.serverProcess = null;
    }
  }

  /** Check if our tracked server process is running (in-process ref only) */
  isServerRunning(): boolean {
    return this.serverProcess !== null && !this.serverProcess.killed;
  }

  /** Run a mneme CLI command with argument array and return parsed JSON output */
  private async runArgs(
    args: string[],
    timeoutMs: number = 30000
  ): Promise<unknown> {
    try {
      const { stdout } = await execFileAsync(this.mnemePath, args, {
        timeout: timeoutMs,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });
      return JSON.parse(stdout.trim());
    } catch (err: unknown) {
      const error = err as {
        code?: string;
        stderr?: string;
        message?: string;
      };
      if (error.code === "ENOENT") {
        throw new Error(
          `Mneme nicht gefunden: "${this.mnemePath}". Bitte installiere Mneme (pip install mneme) oder setze den korrekten Pfad in den Settings.`
        );
      }
      const stderr = error.stderr || error.message || "Unknown error";
      throw new Error(`Mneme Fehler: ${stderr}`);
    }
  }

  /** Run a command with argument array that returns plain text (not JSON) */
  private async runArgsText(
    args: string[],
    timeoutMs: number = 30000
  ): Promise<string> {
    try {
      const { stdout } = await execFileAsync(this.mnemePath, args, {
        timeout: timeoutMs,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });
      return stdout.trim();
    } catch (err: unknown) {
      const error = err as {
        code?: string;
        stderr?: string;
        message?: string;
      };
      if (error.code === "ENOENT") {
        throw new Error(
          `Mneme nicht gefunden: "${this.mnemePath}".`
        );
      }
      throw new Error(`Mneme Fehler: ${error.stderr || error.message}`);
    }
  }

  /** Search the vault */
  async search(query: string, topK?: number): Promise<SearchResult[]> {
    const args = ["search", query, "--json"];
    if (topK) args.push("--top-k", String(topK));
    const result = (await this.runArgs(args)) as { results?: SearchResult[] };
    return result.results || [];
  }

  /** Find semantically similar notes via average chunk embedding */
  async similar(path: string, topK?: number): Promise<SearchResult[]> {
    const args = ["similar", path, "--json"];
    if (topK) args.push("--top-k", String(topK));
    const result = (await this.runArgs(args)) as { results?: SearchResult[] };
    return result.results || [];
  }

  /** Get vault statistics */
  async getStatus(): Promise<VaultStats> {
    return (await this.runArgs(["status", "--json"])) as VaultStats;
  }

  /** Reindex the vault */
  async reindex(full: boolean = false): Promise<ReindexResult> {
    const args = ["reindex", "--json"];
    if (full) args.push("--full");
    return (await this.runArgs(args, 300000)) as ReindexResult;
  }

  /** Run vault health check */
  async healthCheck(): Promise<HealthReport> {
    return (await this.runArgs(["health", "--json"], 120000)) as HealthReport;
  }

  /** Get current config */
  async getConfig(): Promise<MnemeConfig> {
    return (await this.runArgs(["get-config", "--json"])) as MnemeConfig;
  }

  /** Update a config value */
  async updateConfig(key: string, value: string): Promise<void> {
    await this.runArgsText(["update-config", key, value]);
  }

  /** Set auto-search mode */
  async setAutoSearchMode(mode: "off" | "smart" | "always"): Promise<string> {
    return await this.runArgsText(["auto-search", mode]);
  }

  /** Check if mneme is reachable */
  async ping(): Promise<boolean> {
    try {
      await this.getStatus();
      return true;
    } catch {
      return false;
    }
  }
}
