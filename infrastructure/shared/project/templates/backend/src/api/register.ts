import type { Express } from "express";
import type Database from "better-sqlite3";

// API implementation tasks maintain this registry and preserve existing routes.
export function registerApis(_app: Express, _connection: Database.Database): void {}
