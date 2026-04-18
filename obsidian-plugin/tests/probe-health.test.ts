/**
 * Tests for MnemeClient.probeHealth — the response-shape detector that
 * prevents the plugin from trusting a non-mneme service squatting on our
 * port. Verifies:
 *   - "mneme-warm" vs "mneme" vs "other" vs "down" return codes
 *   - 4 KB body-size cap (anti-OOM against malicious local service)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { MnemeClient } from "../src/mneme-client";

function mockFetch(response: Response | Error) {
  if (response instanceof Error) {
    globalThis.fetch = vi.fn().mockRejectedValue(response);
  } else {
    globalThis.fetch = vi.fn().mockResolvedValue(response);
  }
}

function makeResponse(
  body: unknown,
  opts: { ok?: boolean; status?: number } = {},
): Response {
  const bodyStr = typeof body === "string" ? body : JSON.stringify(body);
  return new Response(bodyStr, {
    status: opts.status ?? 200,
    statusText: opts.ok === false ? "Error" : "OK",
  });
}

describe("probeHealth", () => {
  let client: MnemeClient;

  beforeEach(() => {
    client = new MnemeClient("mneme");
  });

  it("returns 'mneme-warm' when model is loaded", async () => {
    mockFetch(makeResponse({ status: "ok", model_loaded: true }));
    const result = await client.probeHealth(8765);
    expect(result).toBe("mneme-warm");
  });

  it("returns 'mneme' when response shape matches but model not loaded", async () => {
    mockFetch(makeResponse({ status: "ok", model_loaded: false }));
    const result = await client.probeHealth(8765);
    expect(result).toBe("mneme");
  });

  it("returns 'other' when response shape is wrong (port-squatting)", async () => {
    mockFetch(makeResponse({ foo: "bar" }));
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' when status is not 'ok'", async () => {
    mockFetch(makeResponse({ status: "error", model_loaded: true }));
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' on non-2xx responses", async () => {
    mockFetch(makeResponse({}, { ok: false, status: 500 }));
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'down' on network error", async () => {
    mockFetch(new TypeError("fetch failed"));
    const result = await client.probeHealth(8765);
    expect(result).toBe("down");
  });

  it("returns 'other' on invalid JSON body", async () => {
    mockFetch(makeResponse("not-json-at-all"));
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("returns 'other' when body exceeds 4 KB cap", async () => {
    // 8 KB of padding + valid shape — body-cap must reject before JSON parse
    const huge = "A".repeat(8 * 1024);
    const body = JSON.stringify({ status: "ok", model_loaded: true, pad: huge });
    mockFetch(makeResponse(body));
    const result = await client.probeHealth(8765);
    expect(result).toBe("other");
  });

  it("isHttpServerHealthy wraps probeHealth ('mneme' / 'mneme-warm' → true)", async () => {
    mockFetch(makeResponse({ status: "ok", model_loaded: true }));
    expect(await client.isHttpServerHealthy(8765)).toBe(true);

    mockFetch(makeResponse({ status: "ok", model_loaded: false }));
    expect(await client.isHttpServerHealthy(8765)).toBe(true);

    mockFetch(makeResponse({ foo: "bar" }));
    expect(await client.isHttpServerHealthy(8765)).toBe(false);

    mockFetch(new TypeError("down"));
    expect(await client.isHttpServerHealthy(8765)).toBe(false);
  });
});
