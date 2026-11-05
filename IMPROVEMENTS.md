# Codebase Improvement Plan — Sports-Betting-Analyzer

Review date: 2025-11-04
Scope: `backend/` (Python/FastAPI), `frontend/` (Blazor), `mobile/` (MAUI), CI/CD, Docker, repo hygiene.

**Overall assessment:** A large, feature-rich system (many sports, ML pipeline, odds, bet tracking, push notifications) that has grown fast. The core issues are: a giant monolithic entry point with dead/shadowed code, no security boundaries, heavy scratch-file clutter, weak test coverage, loose dependency pinning, and mixed-in build artifacts. None of the issues are structural rewrites — they're tractable cleanups, ordered by priority below.

---

## P0 — Correctness & Security (do these first)

### 1. Two conflicting routes: the real predict endpoint may be dead code
`backend/api/app.py` registers `POST /{sport}/predict/{task}` **twice**:
- line ~324: `make_prediction()` — a NASCAR heuristic stub ("Simple heuristic prediction based on starting position... In production, this would load and use a trained ML model")
- line ~746: `predict()` — the actual model-backed implementation (cache, `SportFactory`, etc.)

FastAPI matches in registration order, so the **stub wins for every sport** and the real implementation is unreachable. Same risk for any other duplicated path across `app.py` and the `*_endpoints.py` routers — audit all 105 `@app.*` routes in `app.py` against the routers and delete the duplicates.

### 2. CORS defaults to `*`
`backend/api/app.py:236` — the default `CORS_ORIGINS` list ends with `*`. Combined with no auth (see below), any website can call the API cross-origin. Make the default an explicit allowlist and fail closed if unset.

### 3. No authentication on a mutable API
Endpoints can train models, **delete models** (`DELETE /{sport}/models/{series}/{task}`), import data, and read datasets — with no bearer/auth layer visible in `app.py`. In production this is open. Minimum: put the API behind an auth token (or reverse proxy) and remove/disable destructive endpoints from development defaults.

### 4. Hardcoded credential defaults in `docker-compose.yml`
- `POSTGRES_PASSWORD: ${DB_PASSWORD:-sportsbetting2024}` (3 places)
- `PGADMIN_PASSWORD: ${PGADMIN_PASSWORD:-admin123}`

Require the env vars (fail if missing) or at minimum move the fallbacks to a documented local-dev-only file. Rotate the `sportsbetting2024` password if it's been used on any real server.

### 5. Files that shouldn't be in git
`git ls-files` shows:
- `.vs/` (Visual Studio state, `CodeChunks.db`, `*.vsidx`, `slnx.sqlite`) — despite `.gitignore` listing `.vs/`; it was committed before being ignored. Remove with `git rm -r --cached .vs` and keep the ignore rule.
- `frontend/sportsbetting.db`, `*-shm`, `*-wal` — live SQLite files tracked in the frontend app directory.
- `crash_log.txt`, `backtest_results.txt`, `dk_test.json`, `nascar_quality.json`, `team_name_mapping.txt`, `cols.txt`, various `data/*.csv` and `.rda` files committed at repo root.
- `google-services.json` at the root — Firebase client config is low-sensitivity, but confirm it's not a server key.

### 6. Shadowed/backup code in the live codebase
- `backend/api/app_backup.py`
- `backend/api/espn_endpoints.py_snippet` (not even a `.py` file)
- `backend/patch_endpoints.py`, `patch_endpoints_v2.py`, `patch_endpoints_v3.py`

Delete. Git history is your backup; these files are a trap for future readers.

---

## P1 — Architecture

### 7. `backend/api/app.py` is a 4,768-line, 105-route monolith
You've already started extracting routers (29 `*_endpoint` modules), but half the surface area is still inline in `app.py`, alongside app setup, numpy JSON encoders, the scheduler startup, etc. Finish the migration:

- Move each route group into a `APIRouter` (sports CRUD, training, predictions, simulation, imports) into `api/routers/`.
- `app.py` should end up <150 lines: middleware, routers, lifespan, health.
- This naturally fixes #1 (route shadowing) and makes the API testable in slices.

### 8. `sys.path` hacks + mixed import styles
`app.py` does `sys.path.insert(...)` and then mixes `import train as train_mod` with `from src.version import ...` with bare imports of `data_loader`, `simulation`, etc. This makes the backend un-installable, breaks IDE tooling, and is order-dependent. Consolidate on the `src.` package style (everything under `backend/src/` or `backend/services/`) and drop the path surgery. Ideally a `pyproject.toml` + `pip install -e .` so imports have one shape.

### 9. Monkeypatch as integration strategy
`src/patch_xgboost.py` silently rewrites `xgb.Booster.load_model` to skip broken `sportsdataverse` legacy models (imported at line 2 of `app.py`). This hides real breakage. Prefer: patch the pin in requirements, vendoring, or a small adapter — and at minimum log once and surface it in `/health` so nobody is surprised when EP models are missing.

### 10. Duplicated per-sport UI (48 pages in `frontend/Components/Pages`)
`NBALiveOdds`, `NCAABLiveOdds`, `CFBLiveOdds`, `MlbLiveOdds`, `CollegeBaseballLiveOdds` (and similar `*PlayerProfiles`, `*Stats` triples) are near-clones differing by sport config. Extract one generic `SportLiveOdds`/`SportProfiles` component parameterized by a `SportConfig` (API paths, columns, labels). Cuts page count roughly in half and eliminates the "fix in one league, forget the other" bug class.

### 11. `PythonMLServiceClient.cs` (1,864 lines)
The API client monolith in `frontend/Services`. Split by domain (PredictionsClient, ModelsClient, DataClient, TrackingClient, PushClient) around a small `IBaseApiClient` with the shared HttpClient, retries, and error mapping. The `shared/SportsBettingAnalyzer.Shared.csproj` project exists but barely seems used — move the common models + API client there so `frontend/` and `mobile/` stop diverging on the same API contract.

### 12. Two parallel CI systems
`.github/workflows/` (4 workflows) and `.gitea/workflows/deploy.yml` define different pipelines. Keep one source of truth (or a shared workflow snippet) so deploy config and CI config can't drift.

---

## P2 — Code quality & maintainability

### 13. Scratch/debug files everywhere
- **70 `.py` files at `backend/` root**: `check_*.py`, `debug_*.py`, `diagnose_*.py`, `inspect_*.py`, `scratch.py`, `scratch2.py`, `dry_run_import.py`, `fix_format.py`...
- ~20 top-level one-shots at repo root (`.ps1` and `.py` route-fixers).

Create `backend/scripts/scratch/` (gitignored) for throwaway work; promote the genuinely reusable ones into `backend/scripts/` (real importers/predictors are already there and are fine); delete the rest.

### 14. Logging discipline
- **1,136 `print()` calls** in the backend. Replace with `logging` (you already have `log_capture.py` infrastructure — route everything through it).
- **20× `except Exception: pass`** and **68 bare `except:`** blocks. At minimum `except Exception:  logger.debug(...)`; ideally catch specific exceptions.
- `logging.basicConfig(level=logging.INFO)` at import time in `app.py` fights uvicorn's logging config.

### 15. Error handling shape
`@app.exception_handler(Exception)` + per-route `try/except HTTPException` everywhere means failures can be swallowed or double-wrapped. Standardize: endpoints raise domain exceptions or `HTTPException`; the global handler maps them; log context (sport, task, model key) in the handler.

### 16. Dependencies
- `requirements.txt` is mostly **unpinned** (`pandas`, `xgboost`, `fastapi`, `requests`...) → non-reproducible builds; Docker image and production can drift. Use `pip-compile`/`uv lock` to generate pinned `requirements.lock`.
- **Flask and FastAPI both listed** — if Flask is legacy, cut it.
- `pytest` is in the main `requirements.txt` — dev tools belong only in `requirements-test.txt` (where it also already is).
- R + Posit packages are installed at runtime-image stage (Dockerfile stage 2 installs `r-base`). Consider whether the serving container truly needs it, or pre-bake a base image. Layer the expensive `R -e install.packages(...)` step before the `COPY requirements.txt` churn so it isn't rebuilt every change.

### 17. No lint/format gate
No ruff/black/mypy config found. Add `ruff` (or black + isort) + a `ruff check --fix` step in `backend-tests.yml`; `.editorconfig` for the C# side. Cheap, high return on a 3,000-file-class repo.

### 18. Tests
Most `test_*.py` files at `backend/` root are one-off manual verifications (`test_dedup_fix.py`, `test_shap_ncaab.py`, etc.). Real pytest suites live only in `backend/tests/` (~6 files, ~1,100 lines — thin for a system this size).
- Port the valuable manual checks into `backend/tests/` with fixtures/mocks (esp. CLV math, bet grader, confidence scoring — pure logic, easy to test).
- C# side has 2 test files for 50+ services; at least add tests for the API client deserialization and `BetAnalysisService` math.
- CI uses `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres  # Placeholder` — if tests import `app.py`, that's fragile. Either add a `postgres` service container in the workflow, or design the test suite to not import the app.

### 19. Data in VCS
`.gitignore` says "*CSV Data files (DO NOT COMMIT*)" yet `data/nascar/cup_enhanced.csv` etc. are tracked (via `!data/*.json` + explicit commits). Decide: data is either (a) git-ignored with a `data/README.md` fetch script (you already have a README there), or (b) a small golden fixture set for tests. Right now it's the messy middle.

### 20. Storage sprawl
Postgres in compose, `frontend/sportsbetting.db` SQLite live files in the frontend project, file-based `fcm_store.py`/`push_store.py`/`notification_store.py` creating schemas over what looks like SQLite. That's four persistence paths. Fine as an evolution state, but document which is authoritative per dataset (a `docs/ARCHITECTURE.md` with a data-flow diagram would stop the next "where is this data?" search), and plan a migration path.

---

## P3 — Nice to have

- **Docs:** README (434 lines) + docs/ plans are decent. Add `docs/ARCHITECTURE.md` (components, data flow, ports) and `CONTRIBUTING.md`; retire `IMPLEMENTATION_CHECKLIST.md` / `working_endpoints.md` into docs once they're current.
- **Versioning:** you have `.version.json`, `src/version.py`, `simple_version.py`, Docker `ARG VERSION/GIT_SHA` — three mechanisms. Pick one (build-time injection only) and delete the rest.
- **`SportFactory`/`base.py`:** good abstraction skeleton, but `nascar.py` is 717 lines vs `nhl.py` 83 — NASCAR is special-cased in ~6 places (enhancer, OCR, AI, odds, live endpoints). If NASCAR stays the flagship, fine — but keep all its specialness in one clearly-named module family.
- **Watchtower** auto-updates in a `production` profile is a footgun for a service with a database; consider explicit deploy + migration steps.
- **Frontend `keys/*.xml`** (SignalR) are committed; ensure they aren't sensitive for your deployment.

---

## Suggested sequencing (roughly 5 work items)

| # | Work item | Effort | Impact |
|---|-----------|--------|--------|
| 1 | Audit + dedupe routes in `app.py` (fixes shadowed `predict` bug), delete `app_backup.py`/`*_snippet`/`patch_endpoints_*` | S | Fixes a live correctness bug |
| 2 | Security pass: CORS fail-closed, no default secrets in compose, remove `.vs/` + SQLite + log/scratch files from git | S | Blocks real exposure |
| 3 | Move scratch files out, delete dead one-shots, add ruff + fix, `print` → logging in `api/` | M | Daily-dev quality |
| 4 | Split `PythonMLServiceClient.cs`, extract generic sport pages, grow pytest suite with CI `postgres` service | L | Long-term velocity |
| 5 | Pin dependencies, single CI system, one versioning mechanism | M | Reproducibility |
