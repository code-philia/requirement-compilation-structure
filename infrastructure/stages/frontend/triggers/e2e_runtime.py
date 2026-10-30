"""Step 12 test infrastructure: real application servers and isolated SQLite data.

Compiler-owned Playwright, Vite, Node-runner, and fixture source strings are written
by prepare_e2e(). Each browser run owns temporary database files; test cases reset
their data. Business handlers and scenario assertions are generated separately."""

import json

from infrastructure.utils.files import save_text

CONFIG = "frontend/playwright.e2e.config.ts"
FIXTURE = "frontend/tests/e2e/support/context.ts"
RUNNER = "frontend/scripts/test-e2e.mjs"
VITE_CONFIG = "frontend/vite.e2e.config.ts"

CONFIG_SOURCE = '''import { defineConfig } from "@playwright/test";
const frontendPort = process.env.ARC_E2E_FRONTEND_PORT;
const backendPort = process.env.ARC_E2E_BACKEND_PORT;
const database = process.env.ARC_E2E_DB_FILE;
if (!frontendPort || !backendPort || !database) throw new Error("Use npm run test:e2e or the step 12 runner");
export default defineConfig({
  testDir: "./tests/e2e", outputDir: "./test-results/e2e", workers: 1,
  fullyParallel: false, retries: 0, forbidOnly: true,
  timeout: 30000, expect: { timeout: 5000 }, reporter: "json",
  use: { baseURL: `http://127.0.0.1:${frontendPort}`, browserName: "chromium", headless: true,
    trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: "node --import tsx ../backend/src/server.ts",
      url: `http://127.0.0.1:${backendPort}/api/health`, reuseExistingServer: false, timeout: 600000,
      ...(process.platform === "win32" ? {} : { gracefulShutdown: { signal: "SIGTERM" as const, timeout: 3000 } }),
      env: { PORT: backendPort, DATABASE_URL: database } },
    { command: `node ../node_modules/vite/bin/vite.js --config vite.e2e.config.ts --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: `http://127.0.0.1:${frontendPort}`, reuseExistingServer: false, timeout: 600000,
      ...(process.platform === "win32" ? {} : { gracefulShutdown: { signal: "SIGTERM" as const, timeout: 3000 } }),
      env: { ARC_BACKEND_URL: `http://127.0.0.1:${backendPort}` } },
  ],
});
'''

RUNNER_SOURCE = '''// Every invocation owns a new database; no production database is reset.
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";
import { spawn, spawnSync } from "node:child_process";
const root = fileURLToPath(new URL("../../", import.meta.url));
async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}
const directory = mkdtempSync(join(process.env.ARC_E2E_TEMP_ROOT ?? tmpdir(), "arc-e2e-"));
try {
  const backend = await freePort();
  let frontend = await freePort();
  while (frontend === backend) frontend = await freePort();
  const child = spawn(process.execPath, ["node_modules/@playwright/test/cli.js", "test",
    "--config", "frontend/playwright.e2e.config.ts", ...process.argv.slice(2)], {
    cwd: root, stdio: "inherit", env: { ...process.env, ARC_E2E_BACKEND_PORT: String(backend),
      ARC_E2E_FRONTEND_PORT: String(frontend), ARC_E2E_DB_FILE: join(directory, "app.db") },
  });
  const forward = signal => {
    if (process.platform === "win32" && child.pid)
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    else child.kill(signal);
  };
  process.on("SIGINT", forward); process.on("SIGTERM", forward);
  try {
    process.exitCode = await new Promise((resolve, reject) => { child.once("error", reject); child.once("close", code => resolve(code ?? 1)); });
  } finally { process.off("SIGINT", forward); process.off("SIGTERM", forward); }
} finally { rmSync(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 }); }
'''

FIXTURE_SOURCE = '''// Compiler-owned Given/observation fixture. When actions go through the browser.
import { test as base, expect } from "@playwright/test";
import type Database from "better-sqlite3";
import { basename, dirname } from "node:path";
import { createDatabaseClient } from "../../../../backend/src/db/client.js";
import { initializeDatabase } from "../../../../backend/src/db/initialize.js";
export { fixturePasswordHash } from "../../../../backend/tests/support/context.js";
export const test = base.extend<{ database: Database.Database; applicationErrors: void }>({
  database: [async ({}, use) => {
    const path = process.env.ARC_E2E_DB_FILE;
    if (!path || basename(path) !== "app.db" || !basename(dirname(path)).startsWith("arc-e2e-"))
      throw new Error("E2E fixtures require the runner-owned temporary database");
    const connection = createDatabaseClient(path);
    try {
      initializeDatabase(connection);
      connection.pragma("foreign_keys = OFF");
      connection.transaction(() => {
        const tables = connection.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all() as { name: string }[];
        for (const table of tables) connection.exec(`DELETE FROM "${table.name.replaceAll('"', '""')}"`);
      })();
      connection.pragma("foreign_keys = ON");
      await use(connection);
    } finally { connection.close(); }
  }, { auto: true }],
  applicationErrors: [async ({ page, database }, use) => {
    void database;
    const errors: string[] = [];
    page.on("pageerror", error => errors.push("E2E_RUNTIME_ERROR: " + error.message));
    page.on("requestfailed", request => {
      if (new URL(request.url()).pathname.startsWith("/api/")) errors.push("E2E_NETWORK_ERROR: " + request.url());
    });
    await use();
    if (errors.length) throw new Error(errors.join("\\n"));
  }, { auto: true }],
});
export { expect };
'''


def prepare_e2e(output, backend):
    """Write E2E configuration, real-server launchers, isolated database fixtures, and the npm test command."""
    sources = {CONFIG: CONFIG_SOURCE, RUNNER: RUNNER_SOURCE,
        VITE_CONFIG: 'import { defineConfig, mergeConfig } from "vite";\nimport base from "./vite.config";\nexport default mergeConfig(base, defineConfig({ server: { proxy: { "/api": process.env.ARC_BACKEND_URL! } } }));\n',
        FIXTURE: FIXTURE_SOURCE}
    for relative, source in sources.items():
        save_text(output / relative, source)
    path = output / "package.json"
    package = json.loads(path.read_text(encoding="utf-8-sig"))
    package.setdefault("scripts", {})["test:e2e"] = "node frontend/scripts/test-e2e.mjs"
    save_text(path, json.dumps(package, indent=2) + "\n")
