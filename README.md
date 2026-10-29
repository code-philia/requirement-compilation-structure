# Requirement Compilation Tutorial

Compile a requirement tree into a database, backend APIs, and an interactive frontend through 13 independently executable teaching steps.

## Environment setup

Requires Python 3.11+, Node.js 22.12+, and npm. Building `better-sqlite3` from source may also require Python, make, and a C++ compiler.

Recommended: use [uv](https://docs.astral.sh/uv/). From the repository root (the directory containing `pyproject.toml`):

```bash
uv sync
cp -n .env.example .env
uv run playwright install chromium
```

On Windows PowerShell:

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run playwright install chromium
```

Configure `.env`:

```env
OPENAI_API_KEY=fill-this-in
MODEL=deepseek-flash
OPENAI_BASE_URL=https://api.arc-bench.com/v1
```

## Compile the complete application

From the compiler directory, run the complete 00–12 pipeline without teaching pauses or interactive requirement browsing:

```bash
uv run main.py input/requirements.yaml -o output/demo --port 3000
```

`requirement_path` is the positional YAML document path. Images are resolved relative to that document, so other filenames and directories are supported. A directory argument selects its `requirements.yaml` file. `-o` / `--output-dir` specifies the generated application directory (`--ouput-dir` is also accepted). `--port` defaults to 3000 and sets the backend startup default in newly created templates; the application's `PORT` environment variable still takes precedence. Initialization preserves existing files, including an existing server's configured default.

`main.py` parses these arguments and creates `Compiler`. `compiler.py` stores the requirement path, input directory, output directory, `.arc` directory and port, and calls stage behaviors directly in `Compiler.pipeline()`. English stage comments identify every step, including the database obligation review in stage 04. The pipeline stops at the first failure and returns a nonzero CLI exit code; it never launches the numbered entry scripts or enters their argument parsers.

Stage behaviors now live in importable modules under `infrastructure/stages/` and `infrastructure/shared/project/workflow.py`. The numbered scripts remain thin CLI wrappers for individual lessons and may be removed without affecting the main pipeline. Existing stage artifacts and the workspace's shared compiler/model logs retain their current formats.

The new positional `requirement_path`, `-o` / `--output-dir` and `--port` options belong only to `main.py`. Numbered teaching scripts keep their original arguments, defaults and execution flow, including `--input`, `--output`, `--pause` and their existing stage-specific options; their commands below are unchanged.

## Start the lab
```bash
# Step 1: Explore Requirement (Syntax) Tree
uv run 01_explore_requirement.py --pause --output output/demo

# Step 2: Building DB Schema
uv run 02_build_db_schema.py --pause --output output/demo

# Step 3: Obligation Generation & Enforcement 
uv run 03_infer_db_obligations.py --pause --output output/demo

# Step 4: Result display
uv run 04_check_db_obligations.py --pause --output output/demo

# Step 5: Implement DB
uv run 05_implement_db.py --pause --output output/demo

# Step 6: Decompose Backend API
uv run 06_decompose_backend_apis.py --pause --output output/demo

# Step 7: Contract Inference
uv run 07_infer_api_contracts.py --pause --output output/demo

# Step 8: Implement Backend
uv run 08_implement_backend_tdd.py --pause --output output/demo

# Step 9: UI/Data Design
uv run 09_design_ui.py --pause --output output/demo

# Step 10: Implement UI
uv run 10_implement_ui.py --pause --output output/demo

# Step 11: Interaction Design
uv run 11_design_ui_interactions.py --pause --output output/demo

# Step 12: E2E TDD
uv run 12_implement_frontend_tdd.py --pause --output output/demo
```

## Start the built website
```bash
cd output/demo
npm install
npm run db:init
npm run build
npm start
```
