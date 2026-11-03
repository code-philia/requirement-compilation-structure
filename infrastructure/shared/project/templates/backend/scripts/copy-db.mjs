import { cpSync } from "node:fs";

// SQL stays in separate files and is copied beside the compiled DB modules.
for (const directory of ["tables", "seeds"]) {
  cpSync(new URL(`../src/db/${directory}/`, import.meta.url), new URL(`../dist/db/${directory}/`, import.meta.url), { recursive: true });
}
