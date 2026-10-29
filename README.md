# Requirement Compilation Tutorial

Compile a requirement tree into a database, backend APIs, and an interactive frontend through 13 numbered steps (00–12).

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or a local venv + pip
- Node.js 22.12+ and npm
- An OpenAI-compatible API. Step 01 needs a vision-capable model only when the requirements reference images.

Install [uv](https://docs.astral.sh/uv/) (recommended), then from the repository root:

```bash
uv sync
source .venv/bin/activate
cp -n .env.example .env
```

On Windows PowerShell:

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Set the model credentials in `.env`:

```dotenv
MODEL=your-model
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
```

For a separate visual model, set `VISUAL_MODEL`, `VISUAL_API_KEY`, and `VISUAL_BASE_URL`. Unset visual settings fall back to the text-model settings.

Steps 08, 10, and 12 install the generated application's npm dependencies when needed. Steps 10 and 12 also install Playwright Chromium. On Linux, install missing browser system libraries with `npx playwright install-deps chromium` from the generated workspace. On Windows, use `npx.cmd playwright install chromium` for a manual browser-install retry. Building `better-sqlite3` from source on Windows may require Python and MSVC C++ build tools.

## Run the compiler

Prepare `input/requirements.yaml` and any referenced images, then run:

```bash
uv run python run_all.py --input input --output outputs/demo
```

`run_all.py` runs steps **00–03 and 05–12**. It skips step 04, which only prints the schema and obligation relationships. Run that view separately with `uv run python 04_check_db_obligations.py --output outputs/demo`. Step 01's interactive browser is disabled in the pipeline so execution continues without waiting for input.

Run an individual step after its prerequisites are ready. For example:

```bash
uv run python 01_explore_requirement.py --input input --output outputs/demo
```

By default, step 01 analyzes the requirements and images, saves its artifacts, then opens the terminal browser. Use `--browse` to skip analysis and browse only, or `--no-browse` to analyze without opening the browser. Add `--pause` to a numbered step to wait for Enter between display panels. Relative paths resolve from the current working directory.

## Steps and outputs

| Step | Purpose | Main output |
| --- | --- | --- |
| 00 | Initialize the React/Vite frontend, Express/TypeScript backend, and SQLite scaffold | Project files |
| 01 | Read the requirement tree and analyze referenced images | `.arc/requirements.json`, `.arc/visual_analysis.json` |
| 02 | Build the database schema and link fields to requirements | `.arc/db_schema.json` |
| 03 | Infer requirement-level database reads and writes | `.arc/db_obligations.json` |
| 04 | Display the schema and requirement-obligation relationships | Terminal view; no artifact |
| 05 | Generate and validate one SQLite table per schema entity | `backend/src/db/tables/`, database initializer |
| 06 | Decompose backend operations into APIs and allocate DB obligations | `.arc/backend_apis.json` |
| 07 | Add API preconditions and postconditions | `.arc/backend_contracts.json` |
| 08 | Generate API tests, confirm RED, implement APIs, and run regression | `backend/src/`, `backend/tests/`, `.arc/backend_tdd.json` |
| 09 | Design pages, UI elements, and frontend data | `.arc/ui_design.json` |
| 10 | Implement pages against UI existence tests | `frontend/src/`, `.arc/ui_checks.json` |
| 11 | Design triggers, events, and API/data effects | `.arc/ui_interactions.json` |
| 12 | Implement events and verify browser scenarios | `frontend/`, `.arc/frontend_e2e.json` |

## Project layout

```text
00_*.py ... 12_*.py       # Numbered stages
run_all.py               # Non-interactive pipeline
input/                   # Requirements and reference images
infrastructure/
├── stages/               # Database, backend, and frontend logic
├── shared/               # Models, retrieval, agents, and project templates
└── utils/                # CLI, files, paths, processes, and presentation
outputs/demo/
├── .arc/                 # Intermediate designs and reports
├── backend/              # API source, SQL tables, and tests
├── frontend/             # React source and browser tests
├── compiler.log
└── model_calls.jsonl
```

The Python stages validate model proposals before saving artifacts. Implementation stages use TypeScript compilation, backend tests, browser tests, or builds as appropriate. Step 04 is a read-only review; steps 08, 10, and 12 perform implementation TDD.

`compiler.log` records terminal panels and errors. `model_calls.jsonl` records prompts, file contents, image data, and full model/HTTP responses (authentication headers are excluded). Treat both files as sensitive project data.

## Run the generated application

From the generated workspace root:

```bash
cd outputs/demo
npm install
npm run db:init
npm run build
npm start
```

The app is served at `http://localhost:3000` by default. Set `PORT` or `DATABASE_URL` to change the server port or database path. Steps 10 and 12 also build the workspace after their checks pass.

These commands are added to the generated workspace as their corresponding steps run: backend tests after 08, UI tests after 10, and E2E tests after 12.

Run implementation checks with:

```bash
npm run test:backend
npm run test:ui
npm run test:e2e
```

Run the Python protocol and portability tests from the repository root:

```bash
uv run python -m unittest discover -s tests -v
```

On Windows without uv, replace `python` with `\.venv\Scripts\python.exe`. Use `npm.cmd` if the PowerShell `npm.ps1` shim is blocked.
