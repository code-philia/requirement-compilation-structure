# Requirement Compiler

Compile `requirements.yaml` and reference images into a React + Express + SQLite application through 13 passes: requirements, database schema and obligations, backend APIs and tests, UI, and frontend triggers with end-to-end tests. Intermediate artifacts are saved under the output directory's `.arc/` folder.

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

### Step by step

Run these commands in order. They call the same 13 passes with the same default settings as `main.py`. Step 01 uses `--no-browse` to match the non-interactive pipeline.

```bash
uv run 00_project_initialization.py --input input --output outputs/demo
uv run 01_explore_requirement.py --input input --output outputs/demo --no-browse
uv run 02_build_db_schema.py --input input --output outputs/demo
uv run 03_infer_db_obligations.py --input input --output outputs/demo
uv run 04_check_db_obligations.py --input input --output outputs/demo
uv run 05_implement_db.py --input input --output outputs/demo
uv run 06_design_backend_apis.py --input input --output outputs/demo
uv run 07_check_backend_apis.py --input input --output outputs/demo
uv run 08_implement_backend_tdd.py --input input --output outputs/demo
uv run 09_design_ui.py --input input --output outputs/demo
uv run 10_implement_ui.py --input input --output outputs/demo
uv run 11_design_frontend_triggers.py --input input --output outputs/demo
uv run 12_implement_frontend_tdd.py --input input --output outputs/demo
```

For individual steps, add `--pause` for teaching pauses or `--debug-model-io` for detailed model I/O. Set a custom backend port with `--port` in step 00.

### Start the generated application

```bash
cd outputs/demo
npm run db:init
npm run build
npm start
```

Open `http://localhost:3000` (or the port you selected).

### Local context and independent acceptance

Models receive the current task, selected dependencies and latest failure evidence.
Completed requirements and full source inventories are not appended to every prompt.
The optional `context_request` response discovers candidate IDs or reads exact artifacts
and files; ordinary changes still use `edits`. There is no artificial query-count,
character-count or exact-ID batch-size cap. `ARC_CONTEXT_MAX_CHARS` is no longer used.
Query results still replace prior results, and candidate searches remain paginated to
keep local inputs understandable. Repeated identical evidence prompts the model to read
exact IDs or produce its stage output; a stalled search enters normal task repair.
Provider context/output limits still apply. Automatic decomposition of one oversized
task is not implemented.

Step 06 owns `.arc/shared_conventions.json`. It records concise shared decisions and
compiler-maintained relevance associations. Implementation tasks read related conventions;
changes belong to API design. Obligation records require explicit read/write arrays and
step entries. Step 11 checks declared requirement/step calls against DB obligations;
these checks do not prove actual code semantics.

Step 12 ends with independent acceptance generated per original `requirements.yaml`
leaf. Its model sees original scenarios, selected UI/API interfaces, schema and fixture
utilities, but no application source or process tests. Tests are stored under
`frontend/tests/e2e/acceptance/` and are read-only to application repair. Failed tests may
be corrected by a separate requirement-grounded test-review call; its completion gate
checks compilation, not behavioral success. The real browser verdict remains authoritative.
An unresolved failure produces `COMPLETED_WITH_FAILURES` and does not prevent other
requirements from being attempted. See `.arc/independent_acceptance.json` and the final
stage verification report. Generated tests are still fallible; this separation reduces
shared blind spots, not a proof of complete requirement correctness.

Changes to existing generated tests are recorded with before/after content, diagnosis and
actual feedback in `.arc/test_repairs.jsonl`. No source-text policy scans are introduced.

### Complete the pipeline after local failures

Design tasks (02/03/05/06/09/11), like implementation tasks, attempt their remaining
requirements/entities after a local proposal fails. Per-task results are saved in
`.arc/stage_tasks/<stage>.json`; accepted artifacts remain usable. Failed obligations
stay missing rather than being fabricated as empty R/W records.

The compiler attempts all 13 passes even when a pass raises an ordinary exception.
A downstream pass lacking prerequisites is reported as failed, while independent passes
can still run. `.arc/compilation.json` finishes with `COMPLETED_WITH_FAILURES` when any
pass remains unsuccessful. This does not declare an incomplete application correct.
Ctrl+C still interrupts immediately; a workspace that cannot be written cannot reliably
save a completion report.

Per-task proposal/edit attempts (normally 10) and actual tool/model timeouts remain finite
so a broken task does not hang the entire run. Independent acceptance now uses the same
max-turns value as other stage 12 tasks, without an extra three-turn cap. Test-count values
are generation hints, not hard acceptance gates. The public CLI retains its established
zero exit code on completed partial runs; read the structured report for acceptance status.
