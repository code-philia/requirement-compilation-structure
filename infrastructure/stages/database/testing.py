"""Execute the application's SQLite initialization and compiled server startup."""

import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from infrastructure.utils.processes import capture_process, npm_command


PROBE_SOURCE = r'''
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createServer } from "node:net";
import { scryptSync, timingSafeEqual } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
const plan = JSON.parse(readFileSync(process.argv[2], "utf8"));
const Database = createRequire(join(process.cwd(), "package.json"))("better-sqlite3");
const quote = name => '"' + name.replaceAll('"', '""') + '"';
const affinity = value => {const type=value.toUpperCase();return type.includes('INT')?'INTEGER':/CHAR|CLOB|TEXT/.test(type)?'TEXT':!type||type.includes('BLOB')?'BLOB':/REAL|FLOA|DOUB/.test(type)?'REAL':'NUMERIC';};
let phase = "setup", server;
const completed = [];
const canonicalJson = value => JSON.stringify(normalizeJson(value));
function normalizeJson(value) {
  if(Array.isArray(value)) return value.map(normalizeJson);
  if(value && typeof value==='object') return Object.fromEntries(Object.keys(value).sort().map(key=>[key,normalizeJson(value[key])]));
  return value;
}
function inspect(filename, marker = false) {
  if (!existsSync(filename)) throw new Error("Initialization did not create DATABASE_URL: " + filename);
  const db = new Database(filename);
  try {
    for (const [table, fields] of Object.entries(plan.tables)) {
      const columns = db.prepare(`PRAGMA table_info(${quote(table)})`).all().map(row => row.name);
      if (!columns.length) throw new Error("Missing table: " + table);
      for (const field of fields) if (!columns.includes(field)) throw new Error("Missing column: " + table + "." + field);
      const info=db.prepare(`PRAGMA table_info(${quote(table)})`).all();
      const unique=db.prepare(`PRAGMA index_list(${quote(table)})`).all().filter(index=>index.unique)
        .map(index=>db.prepare(`PRAGMA index_info(${quote(index.name)})`).all().map(column=>column.name).sort().join('|'));
      const refs=db.prepare(`PRAGMA foreign_key_list(${quote(table)})`).all();
      const design=plan.schema[table];
      for(const [name,field] of Object.entries(design.fields)) {
        const actual=info.find(column=>column.name===name);
        if(field.sqlite_type&&affinity(actual.type)!==affinity(field.sqlite_type))throw new Error(`Storage affinity mismatch: ${table}.${name}`);
        const nonnull=Boolean(actual.notnull)||(actual.pk>0&&actual.type.toUpperCase()==='INTEGER');
        if(!field.nullable&&!nonnull)throw new Error(`Required field allows null: ${table}.${name}`);
        if(field.primary_key&&!actual.pk)throw new Error(`Missing primary key: ${table}.${name}`);
        if(field.unique&&!field.primary_key&&!unique.includes(name))throw new Error(`Missing unique constraint: ${table}.${name}`);
        if(field.references) {
          const [target,key]=field.references.split('.');
          const matches=refs.some(ref=>{
            if(ref.from!==name||ref.table!==target)return false;
            if(ref.to===key)return true;
            if(ref.to!=null)return false;
            const primary=db.prepare(`PRAGMA table_info(${quote(target)})`).all().filter(column=>column.pk);
            return primary.length===1&&primary[0].name===key;
          });
          if(!matches)throw new Error(`Missing foreign key: ${table}.${name}`);
        }
      }
      for(const group of design.unique_constraints??[])if(!unique.includes([...group].sort().join('|')))throw new Error(`Missing composite unique: ${table}.${group.join(',')}`);
    }
    if (db.prepare("PRAGMA foreign_key_check").all().length) throw new Error("Foreign-key validation failed");
    for (const record of plan.validation_data ?? []) {
      const entries=Object.entries(record.locator);
      const row=db.prepare(`SELECT * FROM ${quote(record.entity)} WHERE ${entries.map(([key])=>quote(key)+'=?').join(' AND ')}`).get(...entries.map(([,value])=>value));
      if(record.lifecycle!=="SEED") {
        if(row)throw new Error("Non-SEED validation record was preloaded: "+record.id);
      } else {
        if(!row)throw new Error("Missing source SEED record: "+record.id);
        for(const [key,value] of Object.entries(record.fields)) {
          const json=plan.schema[record.entity].fields[key]?.type==='json';
          const matches=json&&row[key]!=null&&value!=null
            ? canonicalJson(JSON.parse(row[key]))===canonicalJson(JSON.parse(value)) : row[key]===value;
          if(!matches)throw new Error("Source SEED value mismatch: "+record.id+"."+key);
        }
        for(const [key,password] of Object.entries(record.password_hashes??{})) {
          const [algorithm,salt,digest,...extra]=String(row[key]??'').split('$');
          if(algorithm!=='scrypt'||!/^[0-9a-f]{32}$/i.test(salt??'')||!/^[0-9a-f]{128}$/i.test(digest??'')||extra.length)
            throw new Error('Invalid source credential hash: '+record.id+'.'+key);
          const expected=Buffer.from(digest,'hex');
          if(!timingSafeEqual(scryptSync(password,Buffer.from(salt,'hex'),64),expected))
            throw new Error('Source credential mismatch: '+record.id+'.'+key);
        }
      }
    }
    if (marker && db.prepare('SELECT value FROM "__arc_startup_probe"').get()?.value !== "preserve")
      throw new Error("Initialization changed existing data");
  } finally { db.close(); }
}
function seedMarker(filename) {
  const db = new Database(filename);
  try { db.exec('CREATE TABLE "__arc_startup_probe" (value TEXT); INSERT INTO "__arc_startup_probe" VALUES (\'preserve\');'); }
  finally { db.close(); }
}
function setup(command, filename, marker = false) {
  const result = spawnSync(command[0], command.slice(1), { cwd: process.cwd(),
    env: { ...process.env, DATABASE_URL: filename }, encoding: "utf8", timeout: 60000 });
  if (result.error || result.status !== 0)
    throw new Error([result.error?.message, result.stdout, result.stderr].filter(Boolean).join("\n"));
  inspect(filename, marker);
  completed.push(phase);
}
async function stopServer() {
  if (!server) return;
  const child = server;
  server = undefined;
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  for (let i = 0; i < 30 && child.exitCode === null && child.signalCode === null; i++) await delay(100);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await new Promise(resolve => child.once("exit", resolve));
  }
}
async function startup(filename, marker = false) {
  let output = "", spawnError;
  const listener = createServer();
  await new Promise((resolve, reject) => { listener.once("error", reject); listener.listen(0, "127.0.0.1", resolve); });
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  server = spawn(process.execPath, ["backend/dist/server.js"], {
    cwd: process.cwd(), env: { ...process.env, DATABASE_URL: filename, PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const child = server;
  child.stdout.on("data", data => { output = (output + data).slice(-24000); });
  child.stderr.on("data", data => { output = (output + data).slice(-24000); });
  child.on("error", error => { spawnError = error; });
  try {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) throw new Error("Server exited before readiness:\n" + output);
      if (port) {
        const response = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(1000) }).catch(() => null);
        if (response?.ok) {
          inspect(filename, marker);
          completed.push(phase);
          return;
        }
      }
      await delay(100);
    }
    throw new Error("Server did not become ready:\n" + output);
  } finally { await stopServer(); }
}
try {
  const database = join(plan.directory, "setup.db");
  phase = "fresh initialization"; setup(plan.setup, database);
  seedMarker(database);
  phase = "repeated initialization"; setup(plan.setup, database, true);
  const first = Object.keys(plan.tables)[0];
  if (first) {
    const db = new Database(database);
    try { db.pragma("foreign_keys = OFF"); db.exec(`DROP TABLE ${quote(first)}`); }
    finally { db.close(); }
    phase = "missing-table recovery"; setup(plan.setup, database, true);
  }
  phase = "compiled initialization"; setup([process.execPath, "backend/dist/db/setup.js"], database, true);
  const startupDatabase = join(plan.directory, "startup.db");
  phase = "fresh server startup"; await startup(startupDatabase);
  seedMarker(startupDatabase);
  phase = "server restart"; await startup(startupDatabase, true);
  phase = "output database initialization"; setup(plan.setup, plan.database);
  console.log(JSON.stringify({ status: "GREEN", completed, database_path: plan.database }));
} catch (error) {
  console.error(JSON.stringify({ phase, completed, error: error.stack ?? String(error) }));
  process.exitCode = 1;
} finally { await stopServer(); }
'''


class DatabaseChecks:
    """Probe disposable databases before initializing the output's persistent database."""

    def __init__(self, output, schema):
        self.output = Path(output).resolve()
        self.schema = schema
        self.node = shutil.which("node")
        if not self.node:
            raise ValueError("Node.js is required for database initialization checks")

    def run(self):
        try:
            # The implementation agent must not bypass acceptance via tsconfig.noCheck
            # or a replacement npm build script. Run the compiler-owned check first.
            typed = capture_process([self.node, "node_modules/typescript/bin/tsc", "--noEmit",
                "--noCheck", "false", "--strict", "true", "-p", "backend/tsconfig.json"],
                cwd=self.output, timeout=600)
            if typed["returncode"]:
                return {**typed, "phase": "backend typecheck"}
            build = capture_process([*npm_command(), "run", "build", "--workspace", "@arc/backend"],
                cwd=self.output, timeout=600)
            if build["returncode"]:
                return {**build, "phase": "backend build"}
            with TemporaryDirectory(prefix="arc-db-check-") as temporary:
                plan = {"directory": temporary, "database": str(self.output / "backend/data/app.db"),
                    "tables": {name: list(entity["fields"]) for name, entity in self.schema["entities"].items()},
                    "schema":self.schema["entities"],
                    "validation_data": [],  # SQL-first flow does not require a seed-binding manifest.
                    "setup": [*npm_command(), "run", "db:init", "--workspace", "@arc/backend"]}
                runner = Path(temporary) / "check-database.mjs"
                arguments = Path(temporary) / "plan.json"
                runner.write_text(PROBE_SOURCE, encoding="utf-8")
                arguments.write_text(json.dumps(plan), encoding="utf-8")
                result = capture_process([self.node, str(runner), str(arguments)],
                    cwd=self.output, timeout=600)
            for stream in ("stderr", "stdout"):
                for line in result.get(stream, "").splitlines():
                    try:
                        detail = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(detail, dict):
                        result.update({key: detail[key] for key in ("phase", "completed", "error", "status", "database_path") if key in detail})
            return result
        except subprocess.TimeoutExpired as error:
            return {"returncode": 1, "phase": "database initialization", "output": str(error), "error": "Database checks timed out"}
