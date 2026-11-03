// Each invocation owns its backend process, port and temporary database.
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const root = fileURLToPath(new URL("../../", import.meta.url));
function discover(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? discover(path) : path.endsWith(".test.ts") ? [path] : [];
  });
}
async function freePort() {
  const listener = createServer();
  await new Promise((resolve, reject) => {
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", resolve);
  });
  const port = listener.address().port;
  await new Promise((resolve, reject) => listener.close(error => error ? reject(error) : resolve()));
  return port;
}
async function stop(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise(resolve => child.once("exit", resolve));
  child.kill("SIGTERM");
  await Promise.race([exited, delay(3000, undefined, { ref: false })]);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await exited;
  }
}

let backend, tests, directory, interrupted = false;
let backendOutput = "", backendError;
let phase = "runner";
const interrupt = () => {
  interrupted = true;
  void stop(tests);
  void stop(backend);
};
process.on("SIGINT", interrupt);
process.on("SIGTERM", interrupt);
try {
  const requested = process.argv.slice(2);
  const files = requested.length ? requested.map(path => resolve(root, path))
    : discover(join(root, "backend/tests")).sort();
  if (!files.length) throw new Error("No API tests found; run step 08 first.");
  directory = mkdtempSync(join(tmpdir(), "arc-api-"));
  const port = await freePort();
  const baseURL = `http://127.0.0.1:${port}`;
  const database = join(directory, "app.db");
  const env = { ...process.env, PORT: String(port), DATABASE_URL: database,
    ARC_API_BASE_URL: baseURL, ARC_API_DB_FILE: database };
  phase = "startup";
  backend = spawn(process.execPath, ["--import", "tsx", "backend/src/server.ts"], {
    cwd: root, env, stdio: ["ignore", "pipe", "pipe"],
  });
  const record = data => { backendOutput = (backendOutput + data).slice(-12000); };
  backend.stdout.on("data", record);
  backend.stderr.on("data", record);
  backend.on("error", error => { backendError = error; });
  let ready = false;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (interrupted) throw new Error("Backend HTTP checks interrupted");
    if (backendError) throw backendError;
    if (backend.exitCode !== null || backend.signalCode !== null)
      throw new Error("Backend exited before readiness");
    const response = await fetch(`${baseURL}/api/health`, {
      signal: AbortSignal.timeout(1000),
    }).catch(() => null);
    if (response?.ok) { await response.arrayBuffer(); ready = true; break; }
    if (response) await response.arrayBuffer();
    await delay(100);
  }
  if (!ready) throw new Error("Backend did not become ready within 30 seconds");
  phase = "tests";
  tests = spawn(process.execPath, ["--import", "tsx", "--test", "--test-concurrency=1",
    "--test-reporter=tap", ...files], { cwd: root, env, stdio: "inherit" });
  const code = await new Promise((resolve, reject) => {
    tests.once("error", reject);
    tests.once("close", code => resolve(code ?? 1));
  });
  if (interrupted) throw new Error("Backend HTTP checks interrupted");
  if (backend.exitCode !== null || backend.signalCode !== null)
    throw new Error("Backend exited during HTTP tests");
  process.exitCode = code;
  if (code && backendOutput) console.error("BACKEND_LOG:\n" + backendOutput);
} catch (error) {
  const tag = phase === "startup" ? "BACKEND_STARTUP_ERROR"
    : phase === "tests" ? "BACKEND_RUNTIME_ERROR" : "BACKEND_RUNNER_ERROR";
  console.error(`${tag}: ${error.stack ?? String(error)}\n${backendOutput}`);
  process.exitCode = 1;
} finally {
  await stop(tests);
  await stop(backend);
  process.off("SIGINT", interrupt);
  process.off("SIGTERM", interrupt);
  if (directory) rmSync(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}
