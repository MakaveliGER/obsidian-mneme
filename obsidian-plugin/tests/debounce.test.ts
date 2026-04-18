/**
 * Tests for MnemeClient.scheduleConfigUpdate — the debounce wrapper that
 * prevents spawning a Python subprocess per keystroke in the plugin
 * settings pane.
 *
 * Uses vitest's fake timers to verify the coalescing behavior without
 * sleeping for 400ms per assertion.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MnemeClient } from "../src/mneme-client";

describe("scheduleConfigUpdate debouncing", () => {
  let client: MnemeClient;
  let updateConfigSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    client = new MnemeClient("mneme");
    // Stub the real CLI-spawning updateConfig so fired calls don't spawn.
    updateConfigSpy = vi
      .spyOn(client, "updateConfig")
      .mockResolvedValue({ updated_key: "x", old_value: "a", new_value: "b" });
  });

  afterEach(() => {
    vi.useRealTimers();
    updateConfigSpy.mockRestore();
  });

  it("fires a single updateConfig after the debounce window for a key", async () => {
    client.scheduleConfigUpdate("search.top_k", "10");
    expect(updateConfigSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(399);
    expect(updateConfigSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    // Timer fired; the async handler is queued — flush microtasks.
    await vi.runAllTimersAsync();

    expect(updateConfigSpy).toHaveBeenCalledTimes(1);
    expect(updateConfigSpy).toHaveBeenCalledWith("search.top_k", "10");
  });

  it("coalesces rapid calls for the same key into a single fire with the last value", async () => {
    client.scheduleConfigUpdate("search.top_k", "1");
    client.scheduleConfigUpdate("search.top_k", "2");
    client.scheduleConfigUpdate("search.top_k", "3");
    client.scheduleConfigUpdate("search.top_k", "4");
    client.scheduleConfigUpdate("search.top_k", "5");

    expect(updateConfigSpy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(500);
    await vi.runAllTimersAsync();

    expect(updateConfigSpy).toHaveBeenCalledTimes(1);
    expect(updateConfigSpy).toHaveBeenCalledWith("search.top_k", "5");
  });

  it("fires each key independently (different keys don't coalesce each other)", async () => {
    client.scheduleConfigUpdate("search.top_k", "10");
    client.scheduleConfigUpdate("embedding.batch_size", "32");
    client.scheduleConfigUpdate("chunking.max_tokens", "1000");

    vi.advanceTimersByTime(500);
    await vi.runAllTimersAsync();

    expect(updateConfigSpy).toHaveBeenCalledTimes(3);
    const keys = updateConfigSpy.mock.calls.map((c) => c[0]).sort();
    expect(keys).toEqual([
      "chunking.max_tokens",
      "embedding.batch_size",
      "search.top_k",
    ]);
  });

  it("custom delay is respected", async () => {
    client.scheduleConfigUpdate("search.top_k", "10", 100);

    vi.advanceTimersByTime(99);
    expect(updateConfigSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    await vi.runAllTimersAsync();
    expect(updateConfigSpy).toHaveBeenCalledTimes(1);
  });

  it("does not crash when updateConfig rejects — errors are swallowed", async () => {
    updateConfigSpy.mockRejectedValueOnce(new Error("disk full"));

    client.scheduleConfigUpdate("search.top_k", "10");
    vi.advanceTimersByTime(500);
    // Should not throw even though the rejected promise fires. Vitest
    // captures unhandled rejections; the point is the plugin UI thread
    // doesn't get a popup per keystroke on sustained failures.
    await vi.runAllTimersAsync();

    expect(updateConfigSpy).toHaveBeenCalledTimes(1);
  });
});
