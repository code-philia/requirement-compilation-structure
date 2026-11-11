"""Single-response SQL implementation through native edit_file calls."""

import json

from infrastructure.shared.agent.agent import BaseAgent
from infrastructure.shared.models.text import reasoning_arguments
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.model_io import record_tool_execution


SQL_INSTRUCTIONS = """Implement the current entity using data definition language (DDL).
Choose SQL syntax and physical types appropriate to the supplied technology stack.
Use edit_file/create for a missing output_path under backend/src/db/tables.
For existing SQL, use exact local edit_file/replace edits and preserve unrelated
definitions. This task owns one fixed SQL path. All required definitions and
referenced SQL are supplied. Use the exact output_path.

Define the table while preserving canonical entity and field names. Quote identifiers
according to the target database dialect. Implement supplied primary keys, nullability,
uniqueness, foreign-key references and database-enforceable value constraints.
Map logical field types to appropriate physical types for the target database.
Use explicit NOT NULL when nullable=false. Follow the target database's key-generation
capabilities and supplied schema evidence; application code supplies other generated
values. Do not invent defaults, normalization, cascades or uniqueness.

Use CHECK or other supported DDL constraints where appropriate. Respect the target
database's restrictions on constraint expressions, including JSON validation.
Describe application-only rules such as password hashing in comments instead of
inventing database checks. Keep rules that cannot be enforced by supported DDL in
application code.

This task defines one table, without extra tables, data mutations or application
startup code. Referenced tables provide target definitions and available SQL; a
missing implementation means that table has not been generated yet. Handle foreign
keys, self-references and cyclic dependencies according to the supplied dependency
plan and target database capabilities. The compiler owns ordered initialization.
Keep repeated initialization safe and preserve existing data, using conditional
table creation where supported.
"""

SEED_INSTRUCTIONS = '''Review the current requirement and incrementally maintain its prerequisite database rows.
Each table has one insertion file: backend/src/db/seeds/ENTITY.sql. The compiler has
created these files and a dependency-ordered seed.ts loader. Edit only the insertion
SQL files; do not put records or INSERT statements in seed.ts or the table DDL files.
The insertion-file mapping identifies the current tables. The canonical table list
names the available tables; their DDL is in backend/src/db/tables/ENTITY.sql.
All canonical table and insertion SQL contents are supplied.
Only canonical database table/insertion files are readable; other application files and
requirements are outside this task. The password helper contract is specified below;
there is no need to inspect the seed loader or other infrastructure.

Identify data that must EXIST BEFORE this requirement's When actions:
- System/domain data users cannot create through the application, such as train services,
  reference catalogues, built-in roles or already stocked books.
- Existing users, books, shelves and other domain records stated in Given or explicit
  seed/prerequisite sections. Include these even when another requirement implements
  their creation: login must be testable with a pre-existing account independently of
  registration, and reading/editing content must not depend on its creation workflow.
- Include the related parent rows and association rows needed to make these records valid.
Preserve exact names, credentials, contents, relationships and initial status supplied by
requirements. For omitted mandatory fields, choose minimal valid deterministic values.
Do not discard prerequisites merely because they occur in a scenario rather than a
sentence saying "system startup". Use the supplied complete requirement and its scenarios.
If a generic reference such as "an existing verified account" does not identify concrete
records, do not invent a separate account, password or object. The defining leaf requirement
will supply those records during this pass. Fill omitted mandatory fields only for records
whose identity is actually established by this requirement.

Do not pre-execute the current When/Then. A record created by this scenario's operation
must remain absent until that operation. Do not fabricate authenticated sessions, personal
history, favorites or drafts that the requirement explicitly establishes through login
or other UI actions. Browser/session state is not a database seed prerequisite.
Different scenarios may need different preconditions. Seed their distinct prerequisite
objects with the exact specified identities; scenario-specific absence, counts or mutable
states can still be arranged by isolated test fixtures. If constraints prevent coexistence,
keep the shared baseline valid and leave conflicting scenario variations to test setup.
Return no tool calls when no prerequisite rows need adding or correcting.

Inspect the supplied existing insertion SQL, then use edit_file/append for missing
rows or edit_file/replace for a small unique exact span when correction is necessary. Preserve ALL earlier requirements' records and comments; never replace a whole
file or rebuild it for only the current requirement. Mark related statements with the
requirement ID. A table's insertion file inserts only into that table; put its parents
and associations in their own files. SELECT subqueries may resolve existing foreign keys.
Use stable identifiers/business keys and SQLite INSERT ... SELECT ... WHERE NOT EXISTS,
or a targeted ON CONFLICT ... DO NOTHING. Avoid INSERT OR IGNORE, which hides invalid data.
Repeated startup must not duplicate records, overwrite user edits or reset credentials.
Do not DELETE, DROP, REPLACE, change table definitions, disable constraints or suppress errors.
The loader executes these files in table-dependency order inside the initialization
transaction; foreign-key checks are deferred until all seed files have executed.

For password-hash columns, use the SQL function seed_password_hash('required password').
It returns scrypt$saltHex$digestHex using a 16-byte salt and a 64-byte digest, compatible
with the documented test credential format. Never store a plaintext password in a hash
column or invent a digest. The password function is called by SQL only for missing rows.
Escape SQL literals correctly; use 0/1 booleans and valid JSON text when required.
The compiler performs real initialization/build checks after this pass.
'''


class DatabaseImplementationAgent(BaseAgent):
    def __init__(self, kind: str, model_name: str | None = None) -> None:
        if kind not in {"table", "seed"}:
            raise ValueError("Database task kind must be table or seed")
        super().__init__(model_name=model_name, json_mode=False)
        self.kind = kind

    def build_system_prompt(self) -> str:
        instructions = SQL_INSTRUCTIONS if self.kind == "table" else SEED_INSTRUCTIONS
        return instructions + """
Use native edit_file function calls, not serialized tool calls in response text.
The input supplies technology stack, directory structure and complete relevant files.
Return all required writes in ONE response. No read/search or repair loop is available.
Table edits must target only output_path. Use operation=create for a missing file,
append/prepend for boundary insertions, or replace with a unique exact old_content
span copied from the supplied file. Never replace an entire existing file.
Seed tasks preserve all earlier requirements while appending or locally correcting INSERTs.
The compiler owns TypeScript loaders and executes initialization after all SQL is saved.
"""

    def build_user_prompt(self, input: dict) -> str:
        paragraphs = [
            "Please implement the current database table." if self.kind == "table" else
                "Please identify and implement prerequisite database rows for the current requirement.",
            "Technology stack:\n" + input["technology_stack"],
        ]
        if self.kind == "table":
            name = input["entity_name"]
            paragraphs.append(f"Current entity: {name}\nRequired SQL path: {input['output_path']}\n"
                "Complete entity definition:\n" + format_schema({name: input["entity"]}))
            references = []
            for name, record in input["referenced_tables"].items():
                references.append(format_schema({name: record["schema"]}))
                implementation = record["implementation"]
                if implementation is None:
                    references.append("SQL is not generated yet. Use the supplied definition for forward references.")
                else:
                    references.append(f"Referenced SQL file: {implementation['path']}\n"
                        + implementation["content"])
            paragraphs.append("Referenced tables and available implementations:\n" +
                ("\n\n".join(references) or "(none)"))
        else:
            requirement = input["requirement"]
            paragraphs.append(f"Current requirement: {requirement['id']} — {requirement['name']}\n"
                f"Description:\n{requirement['description']}")
            steps = []
            previous_scenario = None
            for step in requirement["steps"]:
                scenario = step["scenario"]
                if scenario["id"] != previous_scenario:
                    steps.append(f"Scenario {scenario['id']}: {scenario['name']}")
                    previous_scenario = scenario["id"]
                steps.append(f"Step {step['id']}")
                for key in ("Given", "When", "Then"):
                    steps.append(f"{key}: {step[key]}")
                if step.get("references"):
                    steps.append("References: " + ", ".join(step["references"]))
            paragraphs.append("Requirement scenarios and Given/When/Then steps:\n" +
                ("\n".join(steps) or "(none)"))
            paragraphs.append("Related entities and their prerequisite dependencies:\n" +
                (format_schema(input["entities"]) or "(none)"))
            paragraphs.append("Canonical table names in dependency order:\n" +
                (" → ".join(input["table_names"]) or "(none)"))
            paths = []
            for name, path in input["insert_files"].items():
                paths.append(f"- {name}: {path}")
            paragraphs.append("Insertion-file mapping for this requirement:\n" +
                ("\n".join(paths) or "(none)"))
        scope = input["directory_structure"]
        paragraphs.append("Project scope (paths relative to the generated project root):\n" +
            "\n".join(scope["directories"]))
        paragraphs.append("Existing files in this scope:\n" +
            ("\n".join(scope["existing_files"]) or "(none)"))
        paragraphs.append("Only these files may be edited:\n" +
            ("\n".join(scope["writable_files"]) or "(none)"))
        for path, record in input["files"].items():
            access = "editable" if record["writable"] else "reference only"
            content = record["content"]
            if content is None:
                content = "(file does not exist)" if not record["exists"] else "(content not supplied)"
            paragraphs.append(f"File: {path} ({access})\n{content}")
        paragraphs.append("Return native edit_file calls using the supplied paths and exact existing text. "
            "Preserve earlier requirements. The compiler handles SQL loading and initialization.")
        return "\n\n".join(paragraphs)

    def run(self, input: dict, files) -> dict:
        task = {**input, "technology_stack": "React + Express + SQLite (better-sqlite3)",
            "directory_structure": files.describe(), "files": files.snapshot()}
        messages = [{"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": self.build_user_prompt(task)}]
        self.messages = messages
        response = self.model._request(model=self.model.name, messages=messages,
            tools=files.definitions(["edit_file"]), tool_choice="required" if self.kind == "table" else "auto",
            **reasoning_arguments(self.model.name, self.model.reasoning))
        if not response.choices:
            raise ValueError("Database agent returned no choices")
        choice = response.choices[0]
        message = choice.message
        messages.append(message.model_dump(exclude_none=True))
        if choice.finish_reason == "length":
            raise ValueError("Database SQL response was truncated")
        if getattr(message, "refusal", None):
            raise ValueError(f"Database model refused the task: {message.refusal}")
        calls = message.tool_calls or []
        if self.kind == "table" and not calls:
            raise ValueError("A table task must generate SQL through edit_file")
        for call in calls:
            if call.function.name != "edit_file":
                raise ValueError(f"Unsupported database tool: {call.function.name}")
            arguments = json.loads(call.function.arguments)
            if "tool" in arguments:
                raise ValueError("Native tool arguments must not contain a tool field")
            if self.kind == "table" and arguments.get("path") != input["output_path"]:
                raise ValueError("Table SQL must use the exact output_path")
        if not calls:
            return {"status": "GENERATED", "files": []}
        try:
            results = files.execute(calls)
        except (ValueError, OSError) as error:
            for call in calls:
                result = {"error": str(error), "status": "BATCH_ROLLED_BACK"}
                messages.append({"role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)})
                record_tool_execution(call.model_dump(exclude_none=True), result, logger=self.logger)
            raise
        messages.extend(results)
        for call, result in zip(calls, results):
            record_tool_execution(call.model_dump(exclude_none=True), json.loads(result["content"]), logger=self.logger)
        if self.kind == "table" and not files.resolve_path(input["output_path"]).is_file():
            raise ValueError("Table SQL output was not created")
        return {"status": "GENERATED", "files": sorted(files.changed_paths)}
