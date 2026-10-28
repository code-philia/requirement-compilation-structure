import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const defaultDatabase = fileURLToPath(new URL("../../data/app.db", import.meta.url));

export function createDatabaseClient(filename = process.env.DATABASE_URL ?? defaultDatabase): Database.Database {
  if (!filename.trim()) throw new Error("DATABASE_URL must not be empty");
  if (filename !== ":memory:") mkdirSync(dirname(resolve(filename)), { recursive: true });
  const connection = new Database(filename);
  connection.pragma("foreign_keys = ON");
  return connection;
}
