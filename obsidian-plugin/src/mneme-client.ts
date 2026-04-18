import { execFile, spawn, ChildProcess } from "child_process";
import { promisify } from "util";
import { requestUrl } from "obsidian";
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
  private configUpdateTimers = new Map<string, ReturnType<typeof setTimeout>>();
  // HTTP fast-path: when set, search/similar/stats/reindex route through
  // the warm HTTP server instead of spawning a Python process per call.
  // Set by startHttpServer() once the server is confirmed running.
  private httpPort: number | null = null;

  constructor(private mnemePath: string = "mneme") {}

  setPath(path: string): void {
    this.mnemePath = path;
  }

  /** Enable the HTTP fast-path. Subsequent search/similar/stats calls
   * will try the REST endpoints first and fall back to CLI on error. */
  setHttpPort(port: number | null): void {
    this.httpPort = port;
  }

  /** Lazy discovery: if httpPort isn't set yet (onStartup didn't complete
   * or hasn't run), probe the default server port and latch it. Called
   * before every HTTP-capable method so the plugin self-heals even when
   * the startup sequence missed its window.
   *
   * This eliminates the class of bug where the initial setHttpPort() in
   * onStartup failed silently (waitUntilWarm timeout, race with Obsidian
   * layout-ready, etc.) and every subsequent search/similar call fell
   * through to the slow CLI subprocess — a subprocess that also deadlocks
   * on the SQLite write-lock when the server is already running.
   *
   * The default port matches DEFAULT_SETTINGS.serverPort (8765). Users who
   * changed it either went through onStartup successfully (then httpPort
   * is already set) or manually set up the server at 8765 anyway. */
  private async ensureHttpPort(): Promise<void> {
    if (this.httpPort !== null) return;
    const state = await this.probeHealth(8765);
    if (state === "mneme-warm" || state === "mneme") {
      this.httpPort = 8765;
      // eslint-disable-next-line no-console
      console.info("[Mneme] HTTP server discovered on port 8765 via lazy probe");
    }
  }

  /** Internal: call a REST endpoint on the warm HTTP server via Obsidian's
   * `requestUrl()` API.
   *
   * **Why not browser `fetch()`:** Obsidian's renderer runs with origin
   * `app://obsidian.md`. Any POST with `Content-Type: application/json` to
   * `http://127.0.0.1:8765` is a cross-origin non-simple request — the
   * browser issues a CORS OPTIONS preflight first. Our Starlette/FastMCP
   * server doesn't handle OPTIONS on the `/api/v1/*` routes, so the
   * preflight fails, `fetch()` throws a TypeError, and the entire HTTP
   * fast-path collapses silently into the CLI fallback. The CLI then
   * deadlocks on the SQLite write-lock held by the running server.
   *
   * `requestUrl()` is Obsidian's Node-level HTTP helper. It bypasses the
   * browser CORS stack entirely and talks straight to the server — which
   * is exactly what we want for a plugin contacting its own sidecar on
   * loopback.
   *
   * Returns parsed JSON on 2xx, throws `http-error: <status>` on non-2xx,
   * `http-down: <msg>` on transport failure so callers can fall back. */
  private async restCall(
    path: string,
    method: "GET" | "POST",
    body?: unknown,
    _timeoutMs: number = 30000,
  ): Promise<unknown> {
    if (this.httpPort === null) {
      throw new Error("http-down: no port configured");
    }
    try {
      const response = await requestUrl({
        url: `http://127.0.0.1:${this.httpPort}${path}`,
        method,
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        throw: false,
      });
      if (response.status < 200 || response.status >= 300) {
        throw new Error(`http-error: ${response.status}`);
      }
      // Parse manually from .text rather than trusting requestUrl's .json
      // getter — accessing .json throws on malformed bodies in some
      // Obsidian builds, and we'd rather surface a clean http-down.
      try {
        return JSON.parse(response.text);
      } catch {
        throw new Error("http-down: invalid JSON in response");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.startsWith("http-")) throw err;
      throw new Error(`http-down: ${msg}`);
    }
  }

  /** Debounced config update. Multiple calls with the same key within
   * `delayMs` collapse into a single CLI invocation with the latest value.
   * Avoids spawning `mneme update-config` on every keystroke of a text input.
   */
  scheduleConfigUpdate(key: string, value: string, delayMs: number = 400): void {
    const existing = this.configUpdateTimers.get(key);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(async () => {
      this.configUpdateTimers.delete(key);
      try {
        await this.updateConfig(key, value);
      } catch (err) {
        // Silent — settings pane shouldn't spam notifications on every
        // failed config update. Log to console for debugging.
        // eslint-disable-next-line no-console
        console.warn(`[Mneme] debounced updateConfig(${key}) failed:`, err);
      }
    }, delayMs);
    this.configUpdateTimers.set(key, timer);
  }

  /** Ping the HTTP server's /health endpoint.
   *
   * Returns one of:
   *   - "mneme"       — it's our server (has `model_loaded` field)
   *   - "mneme-warm"  — it's our server AND model is loaded
   *   - "other"       — something else is answering on that port (don't trust)
   *   - "down"        — no response
   *
   * Verifying the response shape (not just 2xx) prevents collision with some
   * other local service squatting on our port.
   */
  async probeHealth(port: number = 8765): Promise<"mneme-warm" | "mneme" | "other" | "down"> {
    try {
      // Same rationale as restCall(): use Obsidian's Node-level requestUrl
      // to bypass Electron renderer CORS. Even this GET without a custom
      // Content-Type header can fail in some Obsidian builds when the
      // response arrives without CORS headers.
      const response = await requestUrl({
        url: `http://127.0.0.1:${port}/health`,
        method: "GET",
        throw: false,
      });
      if (response.status < 200 || response.status >= 300) {
        return "other";
      }
      // Body-size cap: a squatting local service could stream junk and OOM
      // the plugin renderer. Real /health is ~40 bytes; 4 KB leaves room
      // for future fields. requestUrl returns the full body as a string
      // already, so this is a cheap length check.
      if (response.text.length > 4096) {
        return "other";
      }
      let body: Record<string, unknown>;
      try {
        body = JSON.parse(response.text) as Record<string, unknown>;
      } catch {
        return "other";
      }
      if (body && body.status === "ok" && "model_loaded" in body) {
        return body.model_loaded === true ? "mneme-warm" : "mneme";
      }
      return "other";
    } catch {
      return "down";
    }
  }

  /** Legacy boolean probe — true if *any* 2xx response. Kept for callers that
   * don't care about the distinction. Prefer probeHealth() for new code. */
  async isHttpServerHealthy(port: number = 8765): Promise<boolean> {
    const state = await this.probeHealth(port);
    return state === "mneme" || state === "mneme-warm";
  }

  /** Wait until the HTTP server reports model_loaded:true, or give up after
   * timeoutMs. Returns true if warm, false on timeout / error. */
  async waitUntilWarm(
    port: number = 8765,
    timeoutMs: number = 30000,
  ): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const state = await this.probeHealth(port);
      if (state === "mneme-warm") {
        return true;
      }
      if (state === "other") {
        return false; // port is squatted — don't wait
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    return false;
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
  ): Promise<"started" | "already-running" | "failed" | "blocked"> {
    // mnemePath safety check: data.json lives inside the vault for many users
    // and can be tampered with via vault-sync. Defense-in-depth against an
    // attacker-controlled data.json pointing us at an arbitrary executable:
    //
    //   1. Exact-match "mneme" (PATH resolution) — fine.
    //   2. Otherwise the path must be absolute AND the basename exactly
    //      "mneme" or "mneme.exe". Reject:
    //      - UNC paths (\\server\share\...) — attacker-controlled remote exe
    //      - Relative paths — traversal surface, ambiguous cwd
    //      - Basenames that merely start with "mneme" (mneme-wrapper.exe etc)
    //
    // This is not a true security boundary — anyone who can write to
    // data.json can likely also replace the venv's mneme.exe directly —
    // but it blocks the "trivially malicious vault template" class of attack.
    const path = this.mnemePath.trim();
    if (path !== "mneme") {
      // Reject UNC
      if (path.startsWith("\\\\") || path.startsWith("//")) {
        return "blocked";
      }
      // Reject relative paths — must be absolute on Windows (drive-letter
      // or forward-slashed) or POSIX (/…)
      const isAbsoluteWin = /^[A-Za-z]:[\\/]/.test(path);
      const isAbsolutePosix = path.startsWith("/");
      if (!isAbsoluteWin && !isAbsolutePosix) {
        return "blocked";
      }
      // Reject traversal sequences
      if (path.includes("\\..\\") || path.includes("/../") ||
          path.endsWith("\\..") || path.endsWith("/..")) {
        return "blocked";
      }
      // Require basename === "mneme" or "mneme.exe" (case-insensitive)
      const basename = path.split(/[\\/]/).pop()?.toLowerCase() ?? "";
      if (basename !== "mneme" && basename !== "mneme.exe") {
        return "blocked";
      }
    }

    if (await this.isHttpServerHealthy(port)) {
      return "already-running";
    }
    try {
      const child = spawn(
        this.mnemePath,
        // Explicit --host 127.0.0.1 so an attacker-controlled config.toml
        // (with server.host = "0.0.0.0") can't force a non-loopback bind
        // via plugin-spawned processes. Server-side guard still validates.
        ["serve", "--transport", "streamable-http",
         "--host", "127.0.0.1", "--port", String(port)],
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

  /** Silence noisy library output that the CLI's heavy imports produce —
   * tqdm progress bars, HuggingFace Hub network spinners, transformers
   * deprecation warnings, ROCm UserWarnings. Without this, the fallback
   * spawn path pollutes stderr with 2-3 KB of weights-loading bars that
   * then get surfaced to the user as "Mneme Fehler" when parsing fails or
   * the process exits non-zero. Applied on every CLI spawn. */
  private cliEnv(): NodeJS.ProcessEnv {
    return {
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      TQDM_DISABLE: "1",
      HF_HUB_DISABLE_PROGRESS_BARS: "1",
      TRANSFORMERS_VERBOSITY: "error",
      PYTHONWARNINGS: "ignore",
    };
  }

  /** Strip tqdm progress bars and deprecation / user warnings from stderr
   * before surfacing it as an error message. Keeps the last few meaningful
   * lines so the user sees the actual failure reason, not "Loading
   * weights: 0%|" × 40. */
  private sanitizeStderr(stderr: string): string {
    if (!stderr) return "";
    const cleaned = stderr
      .split(/\r\n|\r|\n/)
      // tqdm bars: "28%|...| 109/391 [00:00<?, ?it/s]"
      .filter((l) => !/\d+%\|.*\|.*\d+\/\d+.*\[/.test(l))
      // Python warning lines — module path + line + WarningClass
      .filter((l) => !/\.py:\d+:\s+(User|Deprecation|Future)Warning/.test(l))
      // Bare `warnings.warn(...)` continuation lines
      .filter((l) => !/^\s*warnings\.warn\(/.test(l))
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (cleaned.length === 0) {
      // Everything was noise — give the raw tail so the user has *something*.
      return stderr.slice(-400).trim();
    }
    // Last 3 meaningful lines — usually the actual traceback / error.
    return cleaned.slice(-3).join("\n");
  }

  /** Run a mneme CLI command with argument array and return parsed JSON output */
  private async runArgs(
    args: string[],
    timeoutMs: number = 30000
  ): Promise<unknown> {
    try {
      const { stdout } = await execFileAsync(this.mnemePath, args, {
        timeout: timeoutMs,
        env: this.cliEnv(),
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
          `Mneme nicht gefunden: "${this.mnemePath}". Bitte installiere Mneme (pip install obsidian-mneme) oder setze den korrekten Pfad in den Settings.`
        );
      }
      const stderr = this.sanitizeStderr(error.stderr || error.message || "Unknown error");
      throw new Error(`Mneme Fehler: ${stderr || "Unknown error"}`);
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
        env: this.cliEnv(),
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
      const stderr = this.sanitizeStderr(error.stderr || error.message || "");
      throw new Error(`Mneme Fehler: ${stderr || "Unknown error"}`);
    }
  }

  /** Search the vault.
   *
   * Tries the warm HTTP server first (~10ms round-trip) and falls back to
   * the CLI subprocess (cold start ~15s first call, 2-3s thereafter) only
   * if the HTTP path is unreachable. The fallback keeps the plugin
   * functional if the user disabled autoStartServer or the server crashed
   * between calls. Timeout bumped to 120s for the CLI path because BGE-M3
   * cold-load + search can easily exceed 30s on first invocation.
   */
  async search(query: string, topK?: number): Promise<SearchResult[]> {
    await this.ensureHttpPort();
    if (this.httpPort !== null) {
      try {
        const r = (await this.restCall("/api/v1/search", "POST", {
          query, top_k: topK ?? 10,
        })) as { results?: SearchResult[] };
        return r.results || [];
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[Mneme] HTTP search failed, falling back to CLI:", err);
      }
    } else {
      // eslint-disable-next-line no-console
      console.warn("[Mneme] No HTTP server reachable on port 8765 — using CLI fallback. Start `mneme serve --transport streamable-http` or enable Auto-Start in plugin settings.");
    }
    const args = ["search", query, "--json"];
    if (topK) args.push("--top-k", String(topK));
    const result = (await this.runArgs(args, 120000)) as { results?: SearchResult[] };
    return result.results || [];
  }

  /** Find semantically similar notes via average chunk embedding */
  async similar(path: string, topK?: number): Promise<SearchResult[]> {
    await this.ensureHttpPort();
    if (this.httpPort !== null) {
      try {
        const r = (await this.restCall("/api/v1/similar", "POST", {
          path, top_k: topK ?? 5,
        })) as { results?: SearchResult[] };
        return r.results || [];
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[Mneme] HTTP similar failed, falling back to CLI:", err);
      }
    }
    const args = ["similar", path, "--json"];
    if (topK) args.push("--top-k", String(topK));
    const result = (await this.runArgs(args, 120000)) as { results?: SearchResult[] };
    return result.results || [];
  }

  /** Get vault statistics */
  async getStatus(): Promise<VaultStats> {
    await this.ensureHttpPort();
    if (this.httpPort !== null) {
      try {
        return (await this.restCall("/api/v1/stats", "GET")) as VaultStats;
      } catch {
        // fall through to CLI
      }
    }
    return (await this.runArgs(["status", "--json"])) as VaultStats;
  }

  /** Reindex the vault */
  async reindex(full: boolean = false): Promise<ReindexResult> {
    await this.ensureHttpPort();
    if (this.httpPort !== null) {
      try {
        return (await this.restCall(
          "/api/v1/reindex",
          "POST",
          { full },
          300000,
        )) as ReindexResult;
      } catch {
        // fall through to CLI
      }
    }
    const args = ["reindex", "--json"];
    if (full) args.push("--full");
    return (await this.runArgs(args, 300000)) as ReindexResult;
  }

  /** Run vault health check */
  async healthCheck(): Promise<HealthReport> {
    await this.ensureHttpPort();
    if (this.httpPort !== null) {
      try {
        return (await this.restCall(
          "/api/v1/vault-health",
          "POST",
          {},
          120000,
        )) as HealthReport;
      } catch {
        // fall through to CLI
      }
    }
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
