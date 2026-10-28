# Requirement Compilation Tutorial

Compile a requirement tree into a database, backend APIs, and an interactive frontend through 13 independently executable teaching steps.

## Environment setup

Requires Python 3.11+, Node.js 22.12+, and npm. Building `better-sqlite3` from source may also require Python, make, and a C++ compiler.

Linux/macOS setup (start from the directory containing `compiler`):

```bash
cd compiler
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

Windows PowerShell setup (Python 3.11+ and Node/npm must be on PATH):

```powershell
cd compiler
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Activation is optional. On Windows, replace `python` in the commands below with `.\.venv\Scripts\python.exe`. This avoids PowerShell activation-policy differences. For example:

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
    │   └── project/         # Stack templates, dependencies and fixed implementation paths
    └── utils/               # CLI, portable I/O/paths/processes, console views and logging
```

Start reading with a numbered script, then follow its explicit imports. `stages` defines compilation meaning and validation; `shared` provides reusable execution services; `utils` contains small helpers independent of stage logic. Some orchestration and prompts remain in the numbered scripts.

In frontend packages, `design.py` defines and validates representations, `synthesis.py` handles model proposals and correction feedback, `implementation.py` coordinates TDD, `runtime.py` generates application wiring, and `testing.py` provides fixed check commands. Interaction `e2e_runtime.py` generates the real-server browser-test harness.

Design stages retrieve existing definitions, request a structured model proposal, validate it, and publish accepted artifacts. Page retrieval returns the corresponding UI/data subtree for reuse. Obligation propagation in step 04 uses deterministic rules.

Steps 08, 10, and 12 share `shared/agent/loop.py`. Each model request contains only `task`, `files`, and the latest `feedback`. Every file has its current `content` (null before creation) and a `writable` flag. Source and test contents appear only in this map. Backend implementation sees existing backend sources; frontend implementation sees existing frontend sources. Tests and compiler-owned runtime files are read-only.

The model returns one JSON object:

```json
{"edits": [{"path": "the/supplied/writable/path.ts", "content": "complete final file contents"}]}
```

Creation and replacement use the same format. Only explicitly supplied writable paths are accepted; each may occur once per batch. Arbitrary helper files, file deletion/moves, patch operations, shell tools and model-selected entrypoints are not supported. The compiler validates the whole batch before writing and restores original bytes on a write failure. Valid edits remain on disk after a failed acceptance check; the next request supplies refreshed files and the latest error. Every edit response, including an empty list, automatically runs fixed acceptance checks. An existing passing implementation is reused without an implementation-model call.

Implementation paths are derived from semantic IDs by `shared/project/entrypoints.py`. Filenames use a readable normalized prefix plus a stable ID hash to distinguish case-only IDs and avoid Windows reserved filenames. The exact path is supplied in the task; models do not calculate it.

| Module | Directory | Fixed export |
| --- | --- | --- |
| Backend API | `backend/src/handlers/` | `handle` |
| UI page | `frontend/src/pages/` | `Page` |
| UI event | `frontend/src/events/` | `handle` |

Routing, test bindings, page registration and event registration import these convention files directly. No file association index is created or read. API tests and E2E implementations proceed requirement by requirement; UI implementation proceeds page by page after all UI/data design is complete. Step 12 may also repair explicitly supplied page files while retaining their presentation boundary and existing regression tests.

This protocol replaces the earlier file tools and `.arc/file_index.json`. Use a fresh output directory for the first run after this change, or regenerate steps 08, 10 and 12 and their downstream prerequisites in a clean workspace. Old model-selected paths are not migrated or inferred from an existing index.

## Execute the compiler

Prepare `input/requirements.yaml` and its referenced images. Use the same input and output directories throughout a run. Relative paths resolve from the directory where the command is invoked.

Run all steps sequentially:

```bash
python run_all.py --input input --output outputs/demo
```

Expected result: steps 00-12 complete in order without pauses, producing an application under `outputs/demo/`. Execution stops immediately if a step fails.

Each step can also run independently after its prerequisites have completed. Add `--pause` to a numbered script to wait for Enter between teaching panels. JSON filenames below are relative to `outputs/demo/.arc/`.

| Step | Command | Expected output |
| --- | --- | --- |
| 00: Project Initialization | `python 00_project_initialization.py --output outputs/demo` | React/Vite/Tailwind frontend, Express/TypeScript backend, and SQLite connection scaffold; existing files are preserved. |
| 01: Explore Requirement Tree | `python 01_explore_requirement.py --input input --output outputs/demo` | `requirements.json` and `visual_analysis.json`. |
| 02: DB Schema Synthesis | `python 02_build_db_schema.py --output outputs/demo` | `db_schema.json`: entities, fields, constraints, references, and requirement-to-field relations discovered with schema RAG. |
| 03: Dataflow Obligation Inference | `python 03_infer_db_obligations.py --output outputs/demo` | `db_obligations.json`: requirement/step read and write sets inferred from each requirement's related schema fields, with coverage checked during inference. |
| 04: Schema/Obligation ER View | `python 04_check_db_obligations.py --output outputs/demo` | Read-only console view of the complete schema graph and requirement/obligation relations; no checked artifact is written. |
| 05: DB Implementation | `python 05_implement_db.py --output outputs/demo` | One SQL file per table in `backend/src/db/tables/` and an ordered database initializer. |
| 06: Backend API Decomposition | `python 06_decompose_backend_apis.py --output outputs/demo` | `backend_apis.json`: reusable APIs, R/W obligations, HTTP signatures, and request/response schemas; validates coverage and interface uniqueness. |
| 07: Contract Inference | `python 07_infer_api_contracts.py --output outputs/demo` | `backend_contracts.json`: adds preconditions and postconditions to the fixed step 06 APIs; preserves signatures, I/O schemas, and R/W. |
| 08: Backend TDD | `python 08_implement_backend_tdd.py --output outputs/demo` | Key API tests, API implementations, `backend_tdd.json`. |
| 09: UI/Data Design | `python 09_design_ui.py --input input --output outputs/demo` | `ui_design.json`: pages, UI subtrees, frontend data, and display fixtures for all requirements. |
| 10: UI Existence TDD | `python 10_implement_ui.py --input input --output outputs/demo` | Playwright component-presence tests, React pages, `ui_checks.json`; business events are disabled. |
| 11: Interaction Design | `python 11_design_ui_interactions.py --input input --output outputs/demo` | `ui_interactions.json`: triggers/events, obligation coverage, ordered actions, derived DB coverage, and semantic P/Q. |
| 12: Interaction E2E TDD | `python 12_implement_frontend_tdd.py --input input --output outputs/demo` | Browser scenarios, event implementations, `frontend_e2e.json`, and a complete application build. |

Step 07 returns only `{"contract":{"precondition":[...],"postcondition":[...]}}`. Each precondition contains `id`, `description`, and `error_status`; each postcondition contains `id`, `description`, and `status`. Conditions describe business semantics without request/response field pointers. Rejection statuses must be declared, every response status needs a postcondition, and step 06 interfaces and database obligations remain fixed. Each shared API is inferred once using all its owning requirements. Previously inferred complete contracts remain available in step 07 to coordinate session/cookie conventions.

Step 08 supplies the selected API, a single `all_requirement_uses` list with structured steps, and the full entity definitions in `db_schema`. It does not repeat the current requirement, schema ownership mappings, or the global contract registry. Source and frozen test contents remain in the shared `files` map. Literal test titles use readable scenario names and P/Q IDs; database effects, including forbidden writes, are checked through assertions rather than `R:`/`W:` title labels. `--max-tests` is one direct per-API limit (default 5), with no branch/precondition-derived budget. A case may cover several conditions or response branches. Canonical tests are generated before implementation, frozen, and required to fail by assertion against temporary 501 test bindings before the implementation can be accepted as GREEN.

The simplified backend P/Q schema replaces the earlier pointer-bearing records. Regenerate step 07 and its consumers (08–12) for an existing run; old records are rejected rather than silently converted. P/Q title IDs provide traceability, not proof of business behavior.

Use `python <script>.py --help` for stage-specific options, including retrieval size, test budgets, and agent turn limits. Step 00 exposes `--stack` as the extension point for other technology stacks.

Interaction events declare only frontend `write` permissions. Event DB obligations are derived from called APIs; input-only or navigation-only events have empty DB sets. Step-to-trigger bindings provide behavioral traceability, without requiring a step's DB effects to be covered by that requirement's events: a scenario may include another page's lifecycle behavior. Direct API allocation and requirement-level API coverage remain checked; cross-page outcomes are verified by step 12 E2E tests.

Steps 09–12 use one frontend representation and the shared file-edit protocol:

- Step 09 returns `pages`, `elements`, `bindings`, `requirement_ui`, and `step_ui`. Each changed ID carries a complete replacement record; omitted IDs stay unchanged. There are no recursive prop/fixture patches or explanation fields. Page route/root and existing element type/parent stay fixed. Accepted data references, props and fixture states must be retained.
- Every frontend variable is defined once in `bindings` as `{dtype, constraints, initial, source}`. Element `data` is a list of variable names; visibility can reference the same table. Variables are global to the UI host, without owner/ancestor inference. `ui_design.json` has only pages, elements, bindings, requirements and steps.
- Step 10 loads only requirements, visual evidence and UI/data design. Page tasks receive visual evidence once, with runtime types and frozen tests in `files`. The report stores a fingerprint of the full design, so changes to styles or other untested metadata still require rerunning presentation checks. Steps 11/12 share the exact baseline validation. Steps 10/12 share the presentation boundary scan, so page repairs cannot silently introduce ordinary business handlers or hooks.
- Step 11 receives complete existing interactions and directly allocated APIs; it has no event/API ranking or `--top-k` option. It first designs each leaf's trigger bindings and ordered actions, then infers one semantic P/Q per shared event. Images and concatenated step text are absent from behavior-model requests.

A trigger is `{source, event, action}`. An event is `{description, write, actions}`. Each action has `{id, kind, description}`, plus `api` for API calls or `page` for navigation. Kinds are `local`, `api`, and `navigate`. Action descriptions specify request values, transformations and response branches; action IDs distinguish repeated calls. DB effects and runtime API/navigation permissions are derived from declared calls and destinations. Only the event declares frontend writes. Input/change wiring, source types, IDs, direct API allocation and requirement-level DB coverage remain checked.

Requirements with no UI skip frontend interaction work; their APIs remain covered by backend TDD.

Event contract inference returns `{"contract":{"precondition":["..."],"postcondition":["..."]}}`. P may be empty; Q must describe observable results. There are no typed request/update expressions, action contracts, guard fields or cross-layer Q mappings. Static validation checks structure and effects; real browser scenarios verify the described business behavior.

Step 12 supplies each scenario event/trigger/contract once and includes reachable navigation pages and their lifecycle events, including native href destinations. `target_event_ids` selects implementations needed for the scenario. A dependency event can be implemented before its owning requirement is processed; its ownership remains unchanged, and its owner still gets its own scenario suite. Tests trace STEP IDs, without mandatory EVENT title tags. They use real servers and isolated SQLite fixtures, asserting visible results and persistence/forbidden writes. Existing frontend runtime failures enter implementation repair instead of forcing test regeneration; startup, browser, fixture, backend and network failures are not accepted as behavioral RED. Frozen tests, UI regression and the final build remain required. The runtime ignores late updates/navigation from a handler after a different navigation has superseded it.

These frontend schemas replace the earlier descriptor/owner and typed-contract formats. For existing projects, regenerate steps 09–12 and their source/tests in a fresh output workspace; there is no dual-format reader or automatic migration. Steps 00–08 retain their current protocols.

Generated files are organized as follows:

```text
outputs/demo/
├── .arc/                    # Intermediate designs and reports
├── backend/                 # API source, per-table SQL, and contract tests
├── frontend/                # React source and Playwright UI/E2E tests
├── package.json             # Generated workspace commands
└── compiler.log             # Timestamped console output and errors from each step
```

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
python -m unittest discover -s tests -v
```

On Windows, use `.\.venv\Scripts\python.exe` for that command. See [Windows compatibility review](WINDOWS_COMPATIBILITY.md) for the per-step audit, fixes, and validation limits.
