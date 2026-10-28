# Requirement Compilation Tutorial

Compile a requirement tree into a database, backend APIs, and an interactive frontend through 13 independently executable teaching steps.

## Environment setup

Requires Python 3.11+, Node.js 22.12+, and npm. Building `better-sqlite3` from source may also require Python, make, and a C++ compiler.

Run commands from the `compiler` project root:

```bash
cd compiler
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

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
    │   ├── agent/           # Shared prompts, edit tools, bounded loop and file index
    │   └── project/         # Stack templates, dependencies and entrypoint resolution
    └── utils/               # CLI, artifact loading/writing, console views and logging
```

Start reading with a numbered script, then follow its explicit imports. `stages` defines compilation meaning and validation; `shared` provides reusable execution services; `utils` contains small helpers independent of stage logic. Some orchestration and prompts remain in the numbered scripts.

In frontend packages, `design.py` defines and validates representations, `synthesis.py` handles model proposals and correction feedback, `implementation.py` coordinates TDD, `runtime.py` generates application wiring, and `testing.py` provides fixed check commands. Interaction `e2e_runtime.py` generates the real-server browser-test harness.

Design stages retrieve existing definitions, request a structured model proposal, validate it, and publish accepted artifacts. Page retrieval returns the corresponding UI/data subtree for reuse. Obligation propagation in step 04 uses deterministic rules.

Steps 08, 10, and 12 share `shared/agent/loop.py`: the compiler supplies selected file contents and a shallow project tree; the model returns scoped edits or requests fixed checks; the stage accepts the result only after its checks pass. `protocol.py` contains the common prompts and tool schemas. `FileIndex` records requirement/file and module/file associations and model-selected entrypoints in `.arc/file_index.json`. API tests and E2E implementations proceed requirement by requirement; UI implementation proceeds page by page after all UI/data design is complete.

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
| 02: DB Schema Synthesis | `python 02_build_db_schema.py --output outputs/demo` | `db_schema.json`: entities, fields, constraints, and references discovered with schema RAG. |
| 03: Dataflow Obligation Inference | `python 03_infer_db_obligations.py --output outputs/demo` | `db_obligations.json`: requirement/step read and write sets. |
| 04: Obligation Checking and Propagation | `python 04_check_db_obligations.py --output outputs/demo` | `db_obligations_checked.json`: bottom-up completion and unresolved downward-allocation TODOs. |
| 05: DB Implementation | `python 05_implement_db.py --output outputs/demo` | One SQL file per table in `backend/src/db/tables/` and an ordered database initializer. |
| 06: Backend API Decomposition | `python 06_decompose_backend_apis.py --output outputs/demo` | `backend_apis.json`: reusable API Primitives with checked obligation-union coverage; at most three proposals per requirement. |
| 07: Contract Inference | `python 07_infer_api_contracts.py --output outputs/demo` | `backend_contracts.json`: signatures, request/response schemas, preconditions, and postconditions. |
| 08: Backend TDD | `python 08_implement_backend_tdd.py --output outputs/demo` | Key API tests, API implementations, `backend_tdd.json`, and file-index updates. |
| 09: UI/Data Design | `python 09_design_ui.py --input input --output outputs/demo` | `ui_design.json`: pages, UI subtrees, frontend data, and display fixtures for all requirements. |
| 10: UI Existence TDD | `python 10_implement_ui.py --input input --output outputs/demo` | Playwright component-presence tests, React pages, `ui_checks.json`, and file-index updates; business events remain empty. |
| 11: Interaction Design | `python 11_design_ui_interactions.py --input input --output outputs/demo` | `ui_interactions.json`: triggers/events, obligation coverage, typed data mappings, and event contracts. |
| 12: Interaction E2E TDD | `python 12_implement_frontend_tdd.py --input input --output outputs/demo` | Browser scenarios, event implementations, `frontend_e2e.json`, file-index updates, and a complete application build. |

Use `python <script>.py --help` for stage-specific options, including retrieval size, test budgets, and agent turn limits. Step 00 exposes `--stack` as the extension point for other technology stacks.

Generated files are organized as follows:

```text
outputs/demo/
├── .arc/                    # Intermediate designs, reports, and file_index.json
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

Expected result: tables are initialized in `backend/data/app.db`, the frontend and backend build into their `dist/` directories, and the application is served at `http://localhost:3000`. Set `PORT` or `DATABASE_URL` to override the port or database path. Steps 10 and 12 also build the workspace after their checks pass.

Rerun tests from the generated workspace after the corresponding implementation step:

| Command | Expected output |
| --- | --- |
| `npm run test:backend` | Key API contract tests against isolated in-memory databases. |
| `npm run test:ui` | Playwright verifies component presence and display fixtures; business events are disabled during these checks. |
| `npm run test:e2e` | Playwright runs real frontend/backend scenarios with a temporary SQLite database, then cleans up its servers and database. |
