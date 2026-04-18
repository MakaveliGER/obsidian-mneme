/**
 * Tests for MnemeClient.probeHealth — the response-shape detector that
 * prevents the plugin from trusting a non-mneme service squatting on our
 * port. Verifies:
 *   - "mneme-warm" vs "mneme" vs "other" vs "down" return codes
 *   - 4 KB body-size cap (anti-OOM against malicious local service)
 *
 * Mocks Obsidian's `requestUrl` rather than `fetch` because MnemeClient
 * uses the Node-level Obsidian API to bypass Electron-renderer CORS.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { MnemeClient } from "../src/mneme-client";
import * as obsidian from "obsidian";

type ProbeResponse = {
  status: number;
  text: string;
  json: unknown;
  arrayBuffer: ArrayBuffer;
  headers: Record<string, string>;
};

function mockRequestUrl(body: unknown, opts: { status?: number } = {}): void {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  let json: unknown;
  try {
    json = typeof body === "string" ? JSON.parse(body) : body;
  } catch {
    json = null;
  }
  const response: ProbeResponse = {
    status: opts.status ?? 200,
    text,
    json,
    arrayBuffer: new ArrayBuffer(0),
    headers: {},
  };
  vi.spyOn(obsidian, "requestUrl").mockResolvedValue(response);
}

function mockRequestUrlReject(err: Error): void {
  vi.spyOn(obsidian, "requestUrl").mockRejectedValue(err);
}

describe("probeHealth", () => {
  let client: MnemeClient;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new MnemeClient("mneme");
  });

  it("returns 'mneme-warm' when model is loaded", async () => {
    mockRequestUrl({ status: "ok", model_loaded: true });
    const result = await client.probeHealth(8765);
    expect(result).toBe("mneme-warm");
  });

  it("returns 'mneme' when response shape matches but model not loaded", async () => {
    mockRequestUrl({ status: "ok", model_loaded: false });
    const result = await client.probeHealth(8765);
    expect(result).toBe("mneme");
  });

  it("returns 'other' when response shape is wrong (port-squatting)", async () => {
    mockRequestUrl({ foo: "bar" });
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' when status is not 'ok'", async () => {
    mockRequestUrl({ status: "error", model_loaded: true });
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' on non-2xx responses", async () => {
    mockRequestUrl({}, { status: 500 });
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'down' on network error", async () => {
    mockRequestUrlReject(new TypeError("request failed"));
    const result = await client.probeHealth(8765);
    expect(result).toBe("down");
  });

  it("returns 'other' on invalid JSON body", async () => {
    mockRequestUrl("not-json-at-all");
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' when body exceeds 4 KB cap", async () => {
    const huge = "A".repeat(8 * 1024);
    const body = { status: "ok", model_loaded: true, pad: huge };
    mockRequestUrl(body);
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("isHttpServerHealthy wraps probeHealth ('mneme' / 'mneme-warm' → true)", async () => {
    mockRequestUrl({ status: "ok", model_loaded: true });
    expect(await client.isHttpServerHealthy(8765)).toBe(true);

    mockRequestUrl({ status: "ok", model_loaded: false });
    expect(await client.isHttpServerHealthy(8765)).toBe(true);

    mockRequestUrl({ foo: "bar" });
    expect(await client.isHttpServerHealthy(8765)).toBe(false);

    mockRequestUrlReject(new TypeError("down"));
    expect(await client.isHttpServerHealthy(8765)).toBe(false);
  });
});
