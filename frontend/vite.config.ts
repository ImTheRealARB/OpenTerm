import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  preview: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    reportCompressedSize: true,
    // Vite lists every lazy chunk's JS dependencies (hashed file names, which do not compress) inside the entry file
    // so it can fetch them in parallel. Keep only the CSS entries: the JS imports still load (the browser follows the
    // import graph, and idle preload warms the chunks anyway) but the startup file is ~2 KB gzip smaller.
    modulePreload: { resolveDependencies: (_file, deps) => deps.filter((d) => d.endsWith(".css")) },
  },
  test: { include: ["src/**/*.test.ts"], environment: "node", pool: "threads" }, // threads start faster than forks here
});
