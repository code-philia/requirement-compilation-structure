# Requirement Compilation Tutorial

Compile a requirement tree into a database, backend APIs, and an interactive frontend through 13 independently executable teaching steps.

## Environment setup

Requires Python 3.11+, Node.js 22.12+, and npm. Building `better-sqlite3` from source may also require Python, make, and a C++ compiler.

Recommended: use [uv](https://docs.astral.sh/uv/). From the repository root (the directory containing `pyproject.toml`):

```bash
uv sync
cp -n .env.example .env
```

On Windows PowerShell:

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

Fallback without uv. Windows PowerShell setup (Python 3.11+ and Node/npm must be on PATH):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Activation is optional. With uv, prefix commands with `uv run` (e.g. `uv run python 01_explore_requirement.py ...`). With plain venv on Windows, replace `python` in the commands below with `.\.venv\Scripts\python.exe`. This avoids PowerShell activation-policy differences. For example:

```powershell
.\.venv\Scripts\python.exe run_all.py --input input --output "outputs/demo"
```

Generated source uses UTF-8/LF; UTF-8 inputs may include a BOM. Keep workspace-relative paths and TypeScript imports in forward-slash form with exact filename case. Native absolute CLI paths may use Windows separators and should be quoted when they contain spaces. Native npm dependencies must be installed on each OS; do not copy Linux `node_modules` to Windows. A source build of `better-sqlite3` on Windows requires the appropriate MSVC C++ build tools as well as Python.

Configure `.env`:

```dotenv
MODEL=your-model
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
```

Step 01 needs an image-capable model. To use separate visual-model settings, set `VISUAL_MODEL`, `VISUAL_API_KEY`, and `VISUAL_BASE_URL`; omitted settings fall back to their text-model equivalents.

TDD steps 08, 10, and 12 install the generated application's npm dependencies automatically. Steps 10 and 12 also install Playwright Chromium. If Chromium reports missing operating-system libraries, run this from the generated application directory:

```bash
npx playwright install-deps chromium
```

The OS-library installation command above is for supported Linux environments. Windows browser installation is handled by steps 10/12; use `npx.cmd playwright install chromium` for a manual retry from the generated workspace.

## Project architecture

```text
compiler/
├── 00_*.py ... 12_*.py       # Independent teaching steps
├── run_all.py               # Sequential execution without pauses
├── input/                   # requirements.yaml and reference images
└── infrastructure/
    ├── stages/              # Core compilation representations and stage logic
    │   ├── requirements/    # Requirement tree, step ownership, and traversal
    │   ├── database/        # Schema, obligations, SQL ordering and validation
    │   ├── backend/         # API decomposition, contracts, registration and checks
    │   └── frontend/
    │       ├── ui/          # UI/data design and component-existence TDD
    │       └── interactions/ # Trigger/event design and interaction E2E TDD
    ├── shared/              # Capabilities reused across stages
    │   ├── models/          # Text and image model clients
    │   ├── rag/             # BM25 retrieval for schemas, APIs, pages and events
    │   ├── agent/           # Shared JSON edits, scoped files and bounded repair loop
    │   └── project/         # Stack templates, dependencies and selected source entrypoints
    └── utils/               # CLI, portable I/O/paths/processes, console views and logging
```

Start reading with a numbered script, then follow its explicit imports. `stages` defines compilation meaning and validation; `shared` provides reusable execution services; `utils` contains small helpers independent of stage logic. Some orchestration and prompts remain in the numbered scripts.

Open [CODE_MAP.html](CODE_MAP.html) directly in a browser for the per-step core file call paths, module responsibilities, key symbols and suggested modification points.

In frontend packages, `design.py` defines and validates representations, `synthesis.py` handles model proposals and correction feedback, `implementation.py` coordinates TDD, `runtime.py` generates application wiring, and `testing.py` provides fixed check commands. Interaction `e2e_runtime.py` generates the real-server browser-test harness.

Design stages retrieve existing definitions, request a structured model proposal, validate it, and publish accepted artifacts. Page retrieval returns the corresponding UI/data subtree for reuse. Obligation propagation in step 04 uses deterministic rules.

Steps 08, 10, and 12 share `shared/agent/loop.py`. Each model request contains only `task`, `files`, and the latest `feedback`. The `files` map supplies current file contents and a `writable` flag; null content means a supplied file does not exist yet. Tests are writable during their generation stage and read-only during implementation. Compiler-owned runtime files are references.

The file-edit interface is a JSON response, not a callable tool. Creation and replacement use the same shape:

```json
{"edits": [{"path": "backend/src/greetings/hello.ts", "content": "export const greeting = 'Hello';\n"}]}
```

For a new target, `task.new_file` supplies its identity, kind and destination directory. The model chooses the filename and subdirectories; that path does not need to appear in `files`. The first edit creates that target, and any additional edits may update supplied writable files. Each call creates only its designated target. The compiler remembers the chosen path in `.arc/implementation_paths.json` and maintains imports/registrations. The model returns no entrypoint or file-index fields.

For existing files, the model chooses from `files` entries with `writable=true` and returns each changed file's **complete final content**, preserving unrelated code. The same shape creates a supplied writable file whose content is null. Unchanged files may be omitted. Paths are relative to the output workspace; use forward slashes and exact filename case. Source contents must be JSON strings with escaped newlines, quotes and backslashes. Patches, file deletion/moves, unrequested helper files and shell tools are not supported. A later edit for the same path wins.

The compiler validates a batch before writing and restores original bytes on write failure. Valid edits remain after failed acceptance checks. On retry, task path hints and `files` are refreshed. Once creation succeeds, `task.new_file` disappears and the chosen file is supplied as writable: repair that file at the same path. An empty edit list runs acceptance checks only when no new target is awaiting creation; a new target must first be created. Existing passing implementations can be reused without another implementation-model call.

| Module | Model-selected path under | Required export |
| --- | --- | --- |
| Backend API | `backend/src/` | `handle` |
| UI page | `frontend/src/` | `Page` |
| UI event | `frontend/src/` | `handle` |
| Backend test | `backend/tests/` (`.test.ts`) | Node test suite |
| E2E test | `frontend/tests/e2e/` (`.spec.ts`) | Playwright test suite |

Routing, test bindings, page registration and event registration import the selected files directly. Existing convention files from earlier outputs are still recognized; models do not need to recreate them. The old `.arc/file_index.json` protocol is not used. API tests and E2E implementations proceed requirement by requirement; UI implementation proceeds page by page after UI/data design. Step 12 may also repair supplied writable page files while preserving the UI existence-test regressions.

## Execute the compiler

Prepare `input/requirements.yaml` and its referenced images. Use the same input and output directories throughout a run. Relative paths resolve from the directory where the command is invoked.

Run all steps sequentially:

```bash
uv run python run_all.py --input input --output outputs/demo
```

(`python run_all.py ...` also works inside an activated venv.) Expected result: steps 00-12 complete in order without pauses, producing an application under `outputs/demo/`. Execution stops immediately if a step fails.

Each step can also run independently after its prerequisites have completed. Add `--pause` to a numbered script to wait for Enter between teaching panels. JSON filenames below are relative to `outputs/demo/.arc/`.

| Step | Command | Expected output |
| --- | --- | --- |
| 00: Project Initialization | `python 00_project_initialization.py --output outputs/demo` | React/Vite/Tailwind frontend, Express/TypeScript backend, and SQLite connection scaffold; existing files are preserved. |
| 01: Explore Requirement Tree | `python 01_explore_requirement.py --input input --output outputs/demo` | `requirements.json` and `visual_analysis.json`. |
| 02: DB Schema Synthesis | `python 02_build_db_schema.py --output outputs/demo` | `db_schema.json`: entities, fields, constraints, references, and requirement-to-field relations discovered with schema RAG. |
| 03: Dataflow Obligation Inference | `python 03_infer_db_obligations.py --output outputs/demo` | `db_obligations.json`: requirement/step read and write sets inferred from each requirement's related schema fields, with coverage checked during inference. |
| 04: Schema/Obligation ER View | `python 04_check_db_obligations.py --output outputs/demo` | Read-only console view of the complete schema graph and requirement/obligation relations; no checked artifact is written. |
| 05: DB Implementation | `python 05_implement_db.py --output outputs/demo` | One SQL file per table in `backend/src/db/tables/` and an ordered database initializer. |
| 06: Backend API Decomposition | `python 06_decompose_backend_apis.py --output outputs/demo` | `backend_apis.json`: reusable APIs, R/W obligations, HTTP signatures, and request/response schemas; checks DB-field obligation coverage. |
| 07: Contract Inference | `python 07_infer_api_contracts.py --output outputs/demo` | `backend_contracts.json`: adds preconditions and postconditions to the fixed step 06 APIs; preserves signatures, I/O schemas, and R/W. |
| 08: Backend TDD | `python 08_implement_backend_tdd.py --output outputs/demo` | Key API tests, API implementations, `backend_tdd.json`. |
| 09: UI/Data Design | `python 09_design_ui.py --input input --output outputs/demo` | `ui_design.json`: pages, UI subtrees, frontend data, and display fixtures for all requirements. |
| 10: UI Existence TDD | `python 10_implement_ui.py --input input --output outputs/demo` | Playwright component-presence tests, React pages, `ui_checks.json`; business events are disabled. |
| 11: Interaction Design | `python 11_design_ui_interactions.py --input input --output outputs/demo` | `ui_interactions.json`: triggers/events, obligation coverage, ordered actions, derived DB coverage, and semantic P/Q. |
| 12: Interaction E2E TDD | `python 12_implement_frontend_tdd.py --input input --output outputs/demo` | Browser scenarios, event implementations, `frontend_e2e.json`, and a complete application build. |

The compiler uses two design acceptance rules: necessary JSON structure and DB-field obligations. Actual compilation, tests and builds remain acceptance gates for implementation stages.

| Boundary | Retained check |
| --- | --- |
| Requirement → backend APIs | The allocated APIs' read and write field unions equal the requirement's DB obligations, checked separately. |
| API decomposition → API contracts | API and requirement DB effects remain linked; P/Q may add semantic descriptions without extra coverage rules. |
| Frontend events → backend APIs | API references resolve and called API effects derive from their declared DB read/write fields. |
| Requirement → frontend calls | The direct frontend events' called API field unions equal the requirement's DB obligations. No exact API-ID allocation rule is imposed when equivalent field effects are used. |

JSON checks require the containers and basic value types used by Python; additional metadata is allowed. There are no design gates for route uniqueness, primary/foreign-key policies, supported UI types, mode/data relationships, variable initial-value types, page ownership, retrieval scope, unchanged IDs/props, fixture budgets, P/Q status coverage, or semantic completeness. SQL is saved from the model response without SQLite metadata comparison. Ordinary input bindings and application state are left to the design and implementation models; a button associated with submitting state does not create an enforced input/change obligation.

Steps 08/10/12 still run real TypeScript compilation, Node/Playwright tests and the relevant build. There are no compiler source scans, mandatory P/Q/STEP/EVENT title tags, test-count gates, test-file hash monitors or prerequisite report fingerprint checks. Test budgets remain prompt guidance. Tests and compiler-owned files retain their existing read-only file permissions. Runtime handlers are not restricted by additional frontend-state/API/navigation effect allowlists; actual execution and test assertions determine behavior.

File agents return only `{"edits":[{"path":"relative/path.ts","content":"complete file contents"}]}`. For a new API, page, event, backend test or E2E test, `task.new_file` identifies the target and destination source/test directory; the model chooses the filename and subdirectories. Its first edit creates that target's file, and subsequent edits may update supplied writable files. The compiler remembers the chosen path in `.arc/implementation_paths.json`, generates imports/registrations, and supplies the file as writable on later repairs and resumed runs. No model-generated file index or entrypoint response is required. Existing files at earlier convention paths remain supported. Multiple new events are created one target per call so the first edit is unambiguous; the complete scenario and regression tests must pass before the requirement is accepted. Compiler-generated scaffolding, SQL table destinations and UI existence-test locations retain their compiler-owned paths.

Step 07 returns `{"contract":{"precondition":[...],"postcondition":[...]}}`. P records have `id/description/error_status`; Q records have `id/description/status`. Step 08 receives one `all_requirement_uses` list and full `schema.entities` definitions. Step 09 returns complete records for pages/elements/bindings and requirement/step UI associations. Variables are defined in bindings and referenced by name from elements. Step 11 designs trigger/event records, then string-list event P/Q; it has no image input or interaction RAG. Step 12 supplies unified scenario context, including reachable page lifecycle behavior, and uses real isolated-database E2E tests.

Requirements without UI skip frontend interaction coverage; their backend API obligations remain checked. Step bindings are traceability metadata and do not impose DB containment. Missing files, invalid JSON, unavailable dependencies, file-access errors and real execution failures are still reported as operational errors; they are not additional design policies.

Use `python <script>.py --help` for retrieval, turn limits and prompt-guidance budgets. Existing outputs with the current JSON format can resume from a failed design stage; no UI-specific repair or automatic artifact rewrite is required for this validation-policy change.

Generated files are organized as follows:

```text
outputs/demo/
├── .arc/                    # Intermediate designs and reports
├── backend/                 # API source, per-table SQL, and contract tests
├── frontend/                # React source and Playwright UI/E2E tests
├── package.json             # Generated workspace commands
├── compiler.log             # Stage progress, full display panels, subprocess output and errors
└── model_calls.jsonl         # Complete model SDK requests/responses and actual HTTP bodies
```

The console shows the current stage number/name, requirement or implementation activity, bounded content previews, and elapsed time. Model inputs are summarized by message size, payload sections and file counts. Model returns show readable JSON or file paths and source excerpts. Long previews explicitly indicate truncation. While a model call is pending, a waiting message appears immediately and repeats every 10 seconds. Interactive terminals highlight activity headings; set `NO_COLOR` to disable color.

Both logs append across resumed runs. `compiler.log` keeps full display-panel content even when the console truncates it. `model_calls.jsonl` records untruncated SDK arguments (including system instructions, payloads, file contents, feedback and image data), complete SDK response envelopes, and the actual HTTP request/response bodies. HTTP attempts include SDK retries and the legacy token-parameter fallback. Records have timestamps, stage/activity and a call ID; raw response content is saved before JSON parsing or repair, including invalid or truncated JSON. Authentication headers are not logged. These changes take effect on subsequent calls; earlier logs cannot recover omitted model I/O.

## Build and deploy the generated application

Run from the generated workspace root:

```bash
cd outputs/demo
npm install
npm run db:init
npm run build
npm start
```

On Windows PowerShell, use the explicit npm launcher if the `npm.ps1` shim is blocked:

```powershell
cd outputs/demo
npm.cmd install
npm.cmd run db:init
npm.cmd run build
npm.cmd start
```

The Python compiler resolves npm's JavaScript CLI directly and does not depend on PowerShell script execution.

Expected result: tables are initialized in `backend/data/app.db`, the frontend and backend build into their `dist/` directories, and the application is served at `http://localhost:3000`. Set `PORT` or `DATABASE_URL` to override the port or database path. Steps 10 and 12 also build the workspace after their checks pass.

Rerun tests from the generated workspace after the corresponding implementation step:

| Command | Expected output |
| --- | --- |
| `npm run test:backend` | Key API contract tests against isolated in-memory databases. |
| `npm run test:ui` | Playwright verifies component presence and display fixtures; business events are disabled during these checks. |
| `npm run test:e2e` | Playwright runs real frontend/backend scenarios with a temporary SQLite database, then cleans up its servers and database. |


Compiler protocol and portability checks can be run without model calls:

```bash
uv run python -m unittest discover -s tests -v
```

Without uv, run `python -m unittest discover -s tests -v` in the venv. On Windows without uv, use `.\.venv\Scripts\python.exe` for that command. See [Windows compatibility review](WINDOWS_COMPATIBILITY.md) for the per-step audit, fixes, and validation limits.
