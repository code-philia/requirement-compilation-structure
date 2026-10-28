import { cpSync } from "node:fs";

// SQL stays in separate files and is copied beside the compiled DB modules.
cpSync(new URL("../src/db/tables/", import.meta.url), new URL("../dist/db/tables/", import.meta.url), { recursive: true });
