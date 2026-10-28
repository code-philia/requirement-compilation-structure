import { readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = fileURLToPath(new URL("../../", import.meta.url));
function discover(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? discover(path) : path.endsWith(".test.ts") ? [path] : [];
  });
}
const files = discover(join(root, "backend/tests")).sort();
if (!files.length) throw new Error("No API tests found; run step 08 first.");
const result = spawnSync(process.execPath, ["--import", "tsx", "--test", "--test-reporter=tap", ...files], { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
