import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: resolve(import.meta.dirname, "ui"),
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
});
