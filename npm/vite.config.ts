import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root: resolve(import.meta.dirname, "ui"),
  build: {
    outDir: resolve(import.meta.dirname, "../src/taxsentry/web/static"),
    emptyOutDir: true,
    sourcemap: true,
  },
});
