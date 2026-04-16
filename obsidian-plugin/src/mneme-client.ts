import { exec, spawn, ChildProcess } from "child_process";
import { promisify } from "util";
import type {
  SearchResult,
  VaultStats,
  ReindexResult,
  HealthReport,
  MnemeConfig,
} from "./types";

const execAsync = promisify(exec);

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

  /** Start the Mneme MCP server as a background process */
  startServer(): boolean {
    if (this.serverProcess && !this.serverProcess.killed) {
      return true; // already running
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

  /** Stop the Mneme server process */
  stopServer(): void {
    if (this.serverProcess && !this.serverProcess.killed) {
      this.serverProcess.kill();
      this.serverProcess = null;
    }
  }

  /** Check if server process is running */
  isServerRunning(): boolean {
    return this.serverProcess !== null && !this.serverProcess.killed;
  }

  /** Run a mneme CLI command and return parsed JSON output */
  private async run(
    args: string,
    timeoutMs: number = 30000
  ): Promise<unknown> {
    const cmd = `${this.mnemePath} ${args}`;
    try {
      const { stdout } = await execAsync(cmd, {
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

  /** Run a command that returns plain text (not JSON) */
  private async runText(
    args: string,
    timeoutMs: number = 30000
  ): Promise<string> {
    const cmd = `${this.mnemePath} ${args}`;
    try {
      const { stdout } = await execAsync(cmd, {
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
    const tkArg = topK ? ` --top-k ${topK}` : "";
    const escaped = query.replace(/"/g, '\\"');
    const result = (await this.run(
      `search "${escaped}"${tkArg} --json`
    )) as { results?: SearchResult[] };
    return result.results || [];
  }

  /** Get vault statistics */
  async getStatus(): Promise<VaultStats> {
    return (await this.run("status --json")) as VaultStats;
  }

  /** Reindex the vault */
  async reindex(full: boolean = false): Promise<ReindexResult> {
    const fullArg = full ? " --full" : "";
    return (await this.run(
      `reindex${fullArg} --json`,
      300000
    )) as ReindexResult;
  }

  /** Run vault health check */
  async healthCheck(): Promise<HealthReport> {
    return (await this.run("health --json", 120000)) as HealthReport;
  }

  /** Get current config */
  async getConfig(): Promise<MnemeConfig> {
    return (await this.run("get-config --json")) as MnemeConfig;
  }

  /** Update a config value */
  async updateConfig(key: string, value: string): Promise<void> {
    await this.runText(`update-config "${key}" "${value}"`);
  }

  /** Set auto-search mode */
  async setAutoSearchMode(mode: "off" | "smart" | "always"): Promise<string> {
    return await this.runText(`auto-search ${mode}`);
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
