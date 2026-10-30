import type Database from "better-sqlite3";
import { readFileSync } from "node:fs";

// Step 05 replaces this ordered list with the published SQL filenames.
export const tableFiles: readonly string[] = [];

export function initializeDatabase(connection: Database.Database): void {
  connection.pragma("foreign_keys = ON");
  connection.transaction(() => {
    for (const filename of tableFiles) {
      connection.exec(readFileSync(new URL(`./tables/${filename}`, import.meta.url), "utf8"));
    }
    if (connection.prepare("PRAGMA foreign_key_check").all().length) throw new Error("Foreign-key validation failed");
  })();
}
