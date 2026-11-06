import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const isWindows = process.platform === "win32";
const python = join("..", ".venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python");
const port = process.env.E2E_PORT ?? "8765";
const dataDir = join(tmpdir(), `dataforge-e2e-${Date.now()}`);

/**
 * Runs against the production build served by FastAPI, so the real security headers apply.
 * It uses an installed browser (Microsoft Edge by default); set E2E_CHANNEL=chrome to change it.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  outputDir: join(tmpdir(), "dataforge-e2e-results"),
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.E2E_CHANNEL ?? "msedge",
    viewport: { width: 1440, height: 900 },
    trace: "off",
  },
  webServer: {
    command: `"${python}" -m alembic upgrade head && "${python}" -m uvicorn app.main:app --port ${port}`,
    cwd: "../backend",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      ENVIRONMENT: "test",
      DATA_DIR: dataDir,
      DATABASE_URL: "",
      AI_PROVIDER: "demo",
      CORS_ORIGINS: `http://127.0.0.1:${port}`,
      RATE_LIMIT_AUTH_PER_MINUTE: "1000",
      RATE_LIMIT_AI_PER_MINUTE: "1000",
      RATE_LIMIT_UPLOAD_PER_MINUTE: "1000",
    },
  },
});
