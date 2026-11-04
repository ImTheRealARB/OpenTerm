import { defineConfig } from "@playwright/test";

// PW_PORT lets two worktrees run Playwright side by side (each builds its own dist/ and previews on its own port).
const port = Number(process.env.PW_PORT ?? 4173);

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  workers: 4, // the default (half the cores, 10 here) made 8-9 tests flake per run, on main too; 4 workers: 183 pass in 74 s vs 130 s
  timeout: 20_000,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1600, height: 900 } },
  webServer: {
    // vite build without `npm run build`'s tsc --noEmit: type checking is its own gate, and it costs ~5 s here.
    command: "npx vite build && npm run preview -- --host 127.0.0.1 --port " + port + " --strictPort",
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
