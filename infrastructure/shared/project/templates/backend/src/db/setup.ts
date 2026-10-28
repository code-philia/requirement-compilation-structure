import { createDatabaseClient } from "./client.js";
import { initializeDatabase } from "./initialize.js";

const connection = createDatabaseClient();
try {
  initializeDatabase(connection);
  console.log("Database tables initialized.");
} finally {
  connection.close();
}
