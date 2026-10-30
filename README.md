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

## Start the lab
```bash
# Step 0: Initialize the project
uv run 00_project_initialization.py --pause --output output/demo

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

# Step 6: Design complete Backend APIs (I/O, R/W, P/Q)
uv run 06_design_backend_apis.py --pause --output output/demo

# Step 7: Display Backend APIs (read-only)
uv run 07_check_backend_apis.py --pause --output output/demo

# Step 8: Implement Backend
uv run 08_implement_backend_tdd.py --pause --output output/demo

# Step 9: UI/Data Design
uv run 09_design_ui.py --pause --output output/demo

# Step 10: Implement UI
uv run 10_implement_ui.py --pause --output output/demo

# Step 11: Trigger Design
uv run 11_design_frontend_triggers.py --pause --output output/demo

# Step 12: Trigger E2E TDD
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