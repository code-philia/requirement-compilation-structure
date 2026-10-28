import express from "express";
import type Database from "better-sqlite3";
import { registerApis } from "./api/register.js";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function createApp(connection?: Database.Database) {
  const app = express();
  app.use(express.json());
  app.get("/api/health", (_request, response) => response.json({ status: "ok" }));
  if (connection) registerApis(app, connection);
  // Later backend passes add business routes before this API fallback.
  app.use("/api", (_request, response) => response.status(404).json({ error: "Unknown API route" }));
  const frontend = fileURLToPath(new URL("../../frontend/dist/", import.meta.url));
  if (existsSync(frontend)) {
    app.use(express.static(frontend));
    app.get("/{*path}", (_request, response) => response.sendFile(`${frontend}/index.html`));
  }
  return app;
}
