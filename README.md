# Requirement Compiler

Compile `requirements.yaml` and reference images into a React + Express + SQLite application through seven stages (00–06). Backend construction designs APIs/modules and generates its own tests. Frontend construction designs and implements each requirement first, then accepts it using existing `input/tests/<requirement-ID>.spec.ts` files. It does not generate or edit frontend tests. Requirements without matching tests complete implementation and pass normally. Intermediate artifacts are saved under `.arc/`; see [frontend construction](infrastructure/stages/frontend/build.md).

## Environment

Install [Python 3.11+](https://www.python.org/downloads/), [Node.js 22.12+ with npm](https://nodejs.org/en/download), and [uv](https://docs.astral.sh/uv/getting-started/installation/). Ensure `node`, `npm`, and `uv` are available in your terminal; reopen it after installation.

Run from the repository root using your platform's shell.

**Windows (PowerShell)**

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run playwright install chromium
```

**macOS / Linux (bash or zsh)**

```bash
uv sync
if [ ! -f .env ]; then cp .env.example .env; fi
uv run playwright install chromium
```

On supported Debian/Ubuntu Linux systems, use `uv run playwright install --with-deps chromium` instead to also install browser system dependencies; this may require sudo.

If npm needs to compile native dependencies such as `better-sqlite3`, install the platform's build tools:

| Platform | Build tools |
| --- | --- |
| Windows | Visual Studio Build Tools with **Desktop development with C++**, plus Python available to npm. |
| macOS | Xcode Command Line Tools: `xcode-select --install`. |
| Linux | Python, make, and a C++ compiler; on Debian/Ubuntu: `sudo apt-get install python3 build-essential`. |

Set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `MODEL` in `.env`. Use a model that accepts image input.

## Run

The input directory must contain `requirements.yaml` and its referenced images. The examples use `input/` and write the generated application to `outputs/demo/`. The commands below work in PowerShell, bash, and zsh.

### Full pipeline

```bash
uv run main.py input --output-dir outputs/demo
```

Add `--model-log` to display and save detailed model input/output, or `--port 33000` to change the backend port (default: 3000). Token usage and model latency are always shown.

### Stages and debugging

The same seven named stages run in this order; stage numbers are no longer used:

| Stage | Responsibility |
| --- | --- |
| `project_initialization` | Create the application scaffold. |
| `read_requirements` | Import requirements and analyze referenced images. |
| `build_db_schema` | Read complete model.mmd content and design the logical schema in one native agent loop. |
| `implement_db` | One native agent loop implements dependency-ordered schema batches, reads original root data and writes INSERTs. |
| `correct_db` | Review every requirement node in batches of five, using only concatenated name, description.text and scenarios; directly repair schema/DDL/INSERT code as needed. |
| `build_backend` | Design APIs and reusable modules, generate tests and implement each requirement in one agent context. |
| `build_frontend` | Design pages/components/interactions, implement and accept using the supplied requirement tests. |

```bash
# Initialize, then run a single stage (repeat with the names above in order).
uv run main.py input --output-dir outputs/demo --stage project_initialization
uv run main.py input --output-dir outputs/demo --stage read_requirements
uv run main.py input --output-dir outputs/demo --stage build_db_schema
uv run main.py input --output-dir outputs/demo --stage implement_db
uv run main.py input --output-dir outputs/demo --stage correct_db
uv run main.py input --output-dir outputs/demo --stage build_backend
uv run main.py input --output-dir outputs/demo --stage build_frontend

# Restore the preceding completed checkpoint, then run this stage and all later stages.
uv run main.py input --output-dir outputs/demo --from-stage implement_db
```

`--stage` restores the preceding successful Git checkpoint before running only the selected stage.
`--from-stage` restores the same checkpoint and continues to the end. These commands operate
on the output application's Git repository; uncommitted output changes must be saved first.
Historical numbered names and equivalent completed Git checkpoints remain supported.
New logs, reports and repair commands use the names above. Use `uv run main.py --help`
to list the stages. Add `--pause` or `--model-log` as needed.

For structured authorization/BPMN inputs, see [backend evidence contracts](infrastructure/stages/backend/README.md).

### Start the generated application

```bash
cd outputs/demo
npm run db:init
npm run build
npm start
```

Open `http://localhost:3000` (or the port you selected).

## Playground

After the environment setup above, build the React interface from the repository root:

```bash
npm --prefix playground install
npm --prefix playground run build
```

Start the local server:

```bash
uv run playground/server.py --port 0
```

Open the URL printed in the terminal. `--port 0` selects an available port; use `--port 45741` for a fixed port. The console loads model settings from the root `.env` file. Input and output paths are relative to the repository root; historical runs are listed from directories under `outputs/` containing `.arc/`.

Rebuild after changing the frontend. Press `Ctrl+C` to stop the server.

## Code map and extension points

![Compiler code map](assets/compiler-code-map.svg)

Numbered scripts orchestrate each pass. Domain logic lives in `infrastructure/stages/`; shared agent and project services live in `infrastructure/shared/`.

### Module guide

| Module | Entry | Purpose |
| --- | --- | --- |
| Pipeline | [main.py](main.py), [compiler.py](infrastructure/compiler.py) | Configuration, pass order, and reports. |
| Requirements · 00–01 | [requirements/](infrastructure/stages/requirements/), [project/](infrastructure/shared/project/) | Requirement tree and project initialization. |
| Database · 02–05 | [database/](infrastructure/stages/database/) | Schema, obligations, DDL, and seed data. |
| Backend · 06–08 | [backend/](infrastructure/stages/backend/) | API contracts, HTTP tests, and implementation. |
| Frontend · 09–12 | [ui/](infrastructure/stages/frontend/ui/), [triggers/](infrastructure/stages/frontend/triggers/) | UI design, interactions, and browser acceptance. |
| Agent loops | [proposals.py](infrastructure/shared/agent/proposals.py), [loop.py](infrastructure/shared/agent/loop.py) | Model requests, file edits, checks, and repair. |
| Runtime services | [project/](infrastructure/shared/project/), [presentation/](infrastructure/utils/presentation/) | Templates, Git checkpoints, logs, and execution evidence. |

### Extension points

| Area | Current entry | Possible extension |
| --- | --- | --- |
| Memory | [conventions.py](infrastructure/shared/agent/conventions.py) stores shared decisions; task loops retain retrieved evidence. | Store validated repair lessons and retrieve only those relevant to the current task. |
| RAG | [rag/](infrastructure/shared/rag/) provides BM25; [discovery.py](infrastructure/shared/agent/discovery.py) provides lexical search and exact reads. | Add embeddings, hybrid retrieval, or reranking to the relevant retrieval path. |
| Tools | [tools/](infrastructure/shared/agent/tools/) registers and executes `read_file` and `edit_file`. | Add tool schemas, executors, permissions, and observation handling in `loop.py`, including external service adapters. |
| Skills | No loader is implemented. | Select task-relevant `SKILL.md` guidance when assembling prompts, using the existing tools and permissions. |
| Models | [text.py](infrastructure/shared/models/text.py), [vision.py](infrastructure/shared/models/vision.py). | Add providers or select models by task. |
| Acceptance | Domain `testing.py` and runtime modules. | Support other application stacks or execution environments. |

Keep each task focused on one requirement. Retrieve shared knowledge on demand, preserve canonical contracts, and use executable checks to accept changes.
