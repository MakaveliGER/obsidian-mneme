import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    // Node environment — we're testing MnemeClient which uses child_process,
    // not DOM. Components that touch Obsidian APIs stay out of vitest scope.
    environment: "node",
    globals: false,
    include: ["tests/**/*.test.ts"],
    // Give child_process / network-timeout tests some headroom.
    testTimeout: 5000,
  },
  resolve: {
    alias: {
      // Stub the `obsidian` runtime — vitest runs outside Obsidian. Tests
      // that need real plugin behaviour go into Obsidian itself, not here.
      // Use fileURLToPath for a proper OS path (Windows-safe: no URL-encoded
      // spaces, no /D:/ prefix that Vite can't resolve).
      obsidian: fileURLToPath(new URL("./tests/stubs/obsidian.ts", import.meta.url)),
    },
  },
});
