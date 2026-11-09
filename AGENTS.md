AGENTS.md

Instructions for AI coding agents working in this repo. Read this fully before making changes.

0. **Where to pick up from (session handoff)**

The 2026-07-20 session (mobile UX polish + `PythonMLServiceClient` split) left a full handoff in **`docs/SESSION_HANDOFF.md` — read it first if you continue that work.** Quick state:

- Merged into master: all five chunks — mobile error boundary (PR #66), CSS consolidation (PR #64), theme unification (PR #63), bottom-nav polish (PR #65), ML client split (PR #67). C# test suite on master now includes their new tests.
- C# test suite on master: **80 passing** in `tests/SportsBettingAnalyzer.Tests` (30 baseline + tests added by the five merged feature branches).
- Python tests live in `backend/tests` (168 passing); run with the repo venv (`venv\Scripts\activate` on this Windows box) — plain `python` lacks pytest.
- Two traps that bit that session (details in the handoff):
  1. MAUI **silently drops `*.razor.css` unless it is in `wwwroot`** — put new mobile styles in `mobile/wwwroot/css/app.css`, not beside the `.razor` file.
  2. A `Directory` type in the shared project shadows `System.IO.Directory` in the test project — `CS0722`/`CS0117` on `Directory.Exists`/`Combine`; `global::` does not help; use `DirectoryInfo`/`File.Exists` and `dir.FullName + "/rel"` paths.
- Before branching, `git fetch origin master` and fast-forward local `master` — it falls behind while PRs merge (this is why PR #65 conflicted).

1. What this project is

Sports-Betting-Analyzer is a multi-part app for predicting sports outcomes (NASCAR, NFL, NBA, and some NCAAB) and tracking bets.

ML service (Python, FastAPI): trains models, serves predictions, loads and updates datasets. Default port 8000. Swagger at /docs.
.NET Blazor app (SportsBettingAnalyzer): the UI/backend that calls the ML service over HTTP through PythonMLServiceClient.
Other top-level folders: backend/, frontend/, mobile/, shared/, db/, models/, data/, scripts/, tests/, docs/, mllearning/.
CI: .gitea/workflows/ and .github/workflows/. Default branch is master.
Container setup: docker-compose.yml at repo root.

The README's project-structure tree is out of date (it still says mllearning/ is the root). Do not trust it. Run ls and look at the real layout before editing.

2. How you must work (read this twice)

You are a local model with a limited context window. Work in small, verified steps.

Look before you edit. Use ls, grep -rn, and open only the specific file or line range you need. Never open huge files whole (CSV, parquet, JSON dumps, logs, UpgradeLog.htm, .html scrapes). Use head, wc -l, or sed -n 'START,ENDp'.
One task at a time. Finish and verify one change before starting the next.
State a short plan first (3-6 lines): which files you will touch and why.
Make the smallest change that solves the problem. No drive-by refactors, no renaming, no reformatting untouched code.
Never guess. If a function, column name, route, or config key is not visible in the code you read, search for it. If you still cannot find it, say so and ask.
Verify after every change (see section 5). Report the actual command output, not what you expect it to say.
If a command fails twice with the same error, stop. Explain what you tried and ask for direction. Do not loop.
Show diffs, not whole files, when reporting your work.
3. Setup and run commands

Python (ML service):

bash
python -m venv venv
# Windows: venv\Scripts\activate    Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
python scripts/setup_data.py                   # download datasets (needs Kaggle creds)
python scripts/setup_data.py --sport nba       # one sport only
python scripts/setup_data.py --verify-only     # check files without downloading
python scripts/verify_data.py                  # validate datasets
python -m uvicorn api.app:app --reload --port 8000

Confirm the actual location of requirements.txt and api/app.py with ls/find first, since folders have moved over time.

Docker: docker-compose.yml at the root. Check it before assuming service names or ports.

.NET: solution file is SportsBettingAnalyzer_All.slnx. Use dotnet build and dotnet test against it (or the specific project) once you have confirmed the project paths.

Environment variables used by the Blazor app to reach the ML service:

PYTHON_ML_BASE_URL=http://localhost:8000
PYTHON_ML_TIMEOUT=300
PYTHON_ML_HEALTH_CHECK_INTERVAL=30

Log level: LOG_LEVEL=DEBUG.

4. Code conventions

Python

Python 3.9+ compatible. Do not use syntax newer than that unless you confirm the runtime version.
Sport-specific logic lives in per-sport modules (nascar, nfl, nba). Keep sport logic there, not in api/app.py.
API routes follow the pattern /{sport}/... (schema, data, train, predict, models, entities, simulate, upcoming). Match existing route naming. If you add or change a route, also check the .NET client that calls it.
Trained models are saved as joblib files under models/{sport}/{series}/, with metrics in {task}_metrics.json. Do not rename these paths without updating loaders and the .NET client.
Use pandas idioms already present in the file you edit. Do not load the full 300 MB NBA PlayerStatistics.csv into context or print it; use nrows, usecols, or chunking when inspecting.
Prefer logging over print in service code.

C# / .NET

Match the existing style in the file you edit (naming, async patterns, DI).
Calls to the ML service go through PythonMLServiceClient. Keep request/response models in sync with the FastAPI endpoints.

General

Keep functions small and typed where the file already uses types.
Add or update a test when you fix a bug or add behavior, if a test location exists in tests/.
5. Verifying your work

Before saying a task is done, run what applies:

bash
python -m pytest tests/ -q                # Python tests (confirm the real test path)
python scripts/verify_data.py             # if you touched data loading or schemas
python -c "import api.app"                # quick import sanity check for the API
dotnet build SportsBettingAnalyzer_All.slnx   # if you touched C#

If the repo has a root-level test_*.py file relevant to your change (for example test_models.py, test_versioning.py), run that too.

For API changes, start the service and hit the endpoint:

bash
curl http://localhost:8000/health

If you cannot run something (missing data, missing credentials, no network), say exactly what you could not run and why. Do not claim success.

6. Do not touch / handle with care
Secrets and credentials: never print, copy, log, or commit kaggle.json, API keys, tokens, .env files, or the contents of google-services.json. Never paste credentials into commits or messages.
Large data and models: data/ CSVs and trained model files are not meant for Git. Do not add them to commits. Respect .gitignore and .dockerignore.
Betting data and databases: do not run destructive SQL (DELETE, DROP, TRUNCATE, mass UPDATE) against any real database. deduplicate_bets.sql and db/ scripts modify real data: read them, explain what they will do, and wait for approval before running.
Generated/IDE files: ignore .vs/, *.pyproj.user, UpgradeLog.htm, crash_log.txt, sports-db_logs.txt, tmp/, and scraped .html files. Do not edit or "clean" them unless asked.
Root-level scripts (check_*.py, debug_*.py, fix_shared_routes*.py/.ps1, route_checker.*, apply_import_logic.py, dry_run_import.py): these are one-off utilities. Read before running. Do not delete or consolidate them unless asked.
CI workflows: do not change .gitea/workflows/ or .github/workflows/ unless the task is about CI.
Never force-push, rewrite history, or switch branches without being told to.
7. Git workflow
Default branch is master. Work on a feature branch if asked to commit.
Commit messages: short imperative subject (under 72 chars), optional body explaining why. Example: Fix NBA feature loader dropping rookies.
One logical change per commit.
Do not commit unless asked. When asked, show git status and git diff --stat first.
8. Domain rules for sports modeling
Avoid data leakage. Train on past games only. Respect the train/test season split (train_start_season, test_start_season). Never use features that would not be known before the game starts.
Do not inflate results. Report real metrics from real runs. Never fabricate accuracy, ROI, or backtest numbers. backtest_results.txt is historical output, not a spec.
Team and driver names are messy. Use the existing name-mapping logic (team_name_mapping.txt, check_names.py) rather than ad hoc string fixes.
Odds and bets are money-related. Treat bet-tracking, odds ingestion, and payout calculations as high-risk. Add tests, and call out any change that alters stored bet records.
This tool provides analysis, not guarantees. Do not add copy or output that promises winning bets.
9. When you are unsure

Ask a single, specific question instead of making assumptions. Good: "PlayerStatistics.csv is missing locally. Should I download it with setup_data.py --sport nba or use a small sample?" Bad: guessing a path and continuing.

10. Final report format

When you finish a task, reply with:

What changed: files and a one-line reason each.
How you verified: commands run and their real results.
Not verified / risks: anything you could not run or are unsure about.
Next step (optional): one suggested follow-up.