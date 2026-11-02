import type Database from "better-sqlite3";
import { randomBytes, scryptSync } from "node:crypto";
import { readFileSync } from "node:fs";

// Step 05 fills this dependency-ordered list; row definitions live in seeds/*.sql.
export const seedFiles: readonly string[] = [];

export function seedDatabase(connection: Database.Database): void {
  // SQL can encode predefined credentials without persisting plaintext passwords.
  connection.function("seed_password_hash", (password: unknown) => {
    if (typeof password !== "string") throw new Error("Seed password must be a string");
    const salt = randomBytes(16);
    const digest = scryptSync(password, salt, 64).toString("hex");
    return `scrypt$${salt.toString("hex")}$${digest}`;
  });
  // Permit mutually referencing seed rows; initializeDatabase checks the final state.
  connection.pragma("defer_foreign_keys = ON");
  for (const filename of seedFiles) {
    try {
      connection.exec(readFileSync(new URL(`./seeds/${filename}`, import.meta.url), "utf8"));
    } catch (cause) {
      throw new Error(`Database startup data failed for seeds/${filename}`, { cause });
    }
  }
}
