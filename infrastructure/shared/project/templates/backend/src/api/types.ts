import type Database from "better-sqlite3";

export interface ApiRequest {
  params: Record<string, string>;
  query: Record<string, unknown>;
  body: Record<string, unknown>;
  headers: Record<string, string | undefined>;
}

export interface ApiResponse {
  status: number;
  body: unknown;
  headers?: Record<string, string | string[]>;
}

export type ApiHandler = (request: ApiRequest, connection: Database.Database) => Promise<ApiResponse>;
