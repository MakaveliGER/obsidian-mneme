/**
 * Tests for the mnemePath RCE guard in MnemeClient.startHttpServer.
 *
 * Threat model: data.json can be tampered with via vault-sync. A malicious
 * vault template could set `mnemePath` to an attacker-controlled binary and
 * hijack `spawn(mnemePath, …)` on plugin startup. The guard allows only:
 *   - exact "mneme" (PATH resolution)
 *   - absolute path with basename exactly "mneme" or "mneme.exe"
 * and rejects UNC paths, relative paths, and traversal sequences.
 *
 * We verify the guard by setting mnemePath, stubbing the port-probe to
 * return "down", and asserting the "blocked" return code. No actual spawn
 * happens — the guard runs before spawn is reached.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { MnemeClient } from "../src/mneme-client";

// Stub global fetch so probeHealth returns "down" — forces startHttpServer
// past the "already-running" short-circuit and into the guard.
beforeEach(() => {
  globalThis.fetch = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
});

describe("mnemePath RCE guard", () => {
  it("allows the bare 'mneme' (PATH resolution)", async () => {
    const client = new MnemeClient("mneme");
    // We can't prevent spawn without stubbing child_process too; but the
    // guard returning non-"blocked" is the claim under test.
    const result = await client.startHttpServer(18765, false);
    expect(result).not.toBe("blocked");
  });

  it("allows an absolute Windows path with correct basename", async () => {
    const client = new MnemeClient("D:\\venv\\Scripts\\mneme.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).not.toBe("blocked");
  });

  it("allows an absolute POSIX path with correct basename", async () => {
    const client = new MnemeClient("/usr/local/bin/mneme");
    const result = await client.startHttpServer(18765, false);
    expect(result).not.toBe("blocked");
  });

  it("blocks UNC paths", async () => {
    const client = new MnemeClient("\\\\attacker\\share\\mneme.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks forward-slash UNC (//)", async () => {
    const client = new MnemeClient("//attacker/share/mneme.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks relative paths", async () => {
    const client = new MnemeClient("mneme.exe");  // bare filename, no dir
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks relative paths with subdirs", async () => {
    const client = new MnemeClient("bin/mneme.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks traversal sequences", async () => {
    const client = new MnemeClient("C:\\venv\\..\\..\\evil\\mneme.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks POSIX traversal", async () => {
    const client = new MnemeClient("/opt/../tmp/mneme");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks wrong basename (not mneme/mneme.exe)", async () => {
    const client = new MnemeClient("C:\\evil\\payload.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("blocks basenames that merely start with mneme", async () => {
    const client = new MnemeClient("C:\\evil\\mneme-wrapper.exe");
    const result = await client.startHttpServer(18765, false);
    expect(result).toBe("blocked");
  });

  it("basename check is case-insensitive", async () => {
    const client = new MnemeClient("C:\\venv\\MNEME.EXE");
    const result = await client.startHttpServer(18765, false);
    // Uppercase is fine — Windows paths are case-insensitive.
    expect(result).not.toBe("blocked");
  });
});
