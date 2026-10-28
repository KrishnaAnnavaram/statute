import { defineConfig } from "@playwright/test";

// End-to-end tests run the real Python read API over the repository's committed
// output/ (read-only) and the built UI. Build first: npm run build.
const PORT = 8799;
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "off" },
  webServer: {
    command: `python -m statute_console --port ${PORT}`,
    cwd: "../server",
    url: `http://127.0.0.1:${PORT}/api/v1/stages`,
    reuseExistingServer: false,
    env: { PYTHONDONTWRITEBYTECODE: "1" },
    timeout: 30_000,
  },
});
