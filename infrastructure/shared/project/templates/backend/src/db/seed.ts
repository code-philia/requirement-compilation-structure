import type Database from "better-sqlite3";

// Step 05 maintains only the startup data explicitly required by the requirements.
// This runs after table creation, inside the database initialization transaction.
export function seedDatabase(_connection: Database.Database): void {}
