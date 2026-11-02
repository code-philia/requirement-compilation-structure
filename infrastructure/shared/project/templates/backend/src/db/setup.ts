import { createDatabaseClient } from "./client.js";
import { initializeDatabase } from "./initialize.js";

const connection = createDatabaseClient();
try {
  initializeDatabase(connection);
  console.log("Database tables and required startup data initialized.");
} finally {
  connection.close();
}
