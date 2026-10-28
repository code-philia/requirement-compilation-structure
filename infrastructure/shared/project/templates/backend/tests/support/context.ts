import type { TestContext } from "node:test";
import { scryptSync } from "node:crypto";
import { createDatabaseClient } from "../../src/db/client.js";
import { initializeDatabase } from "../../src/db/initialize.js";
import type { ApiRequest } from "../../src/api/types.js";

export function createTestDatabase(context: TestContext) {
  const connection = createDatabaseClient(":memory:");
  initializeDatabase(connection);
  context.after(() => connection.close());
  return connection;
}

export function request(values: Partial<ApiRequest> = {}): ApiRequest {
  return { params: {}, query: {}, body: {}, headers: {}, ...values };
}

// Fixture encoding policy for credential APIs. Fixture setup is not API behavior.
// Production may use a stronger compatible format; these existing records must
// remain verifiable. No test relies on an exact random hash or generated UUID.
export function fixturePasswordHash(password: string): string {
  const salt = "00112233445566778899aabbccddeeff";
  const digest = scryptSync(password, Buffer.from(salt, "hex"), 64).toString("hex");
  return `scrypt$${salt}$${digest}`;
}
