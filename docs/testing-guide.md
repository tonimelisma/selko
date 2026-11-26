# Testing Guide

## Test Commands

### Backend (Python/pytest)

```bash
# The Tier 1 gate: unit + integration, writes .verify/backend-<sha>.json and
# fails if any skip is not budgeted (backend/tests/skip_budget.toml)
./scripts/verify.sh backend

# Everything, ad hoc
uv run pytest backend/tests/

# Unit tests only
uv run pytest backend/tests/ -m "not integration"

# Tests that call a real LLM (costs money; needs provider keys)
uv run pytest backend/tests/<file> --run-llm
```

No service is needed. The backend runs on one SQLite file, and every test that
touches the database gets its own: the `db` and `factory` fixtures in
`backend/tests/sqlite_fixtures.py` create a fresh file in `tmp_path` with every
migration in `backend/selko/db/migrations/` applied, and `factory` inserts
minimal valid rows (`factory.user()`, `factory.event(user)`, …).

```python
def test_something(db, factory):
    user = factory.user()
    event = factory.event(user, review_status="pending_review")
    ...
```

No test needs Docker or a database service. The database the one-time
importer made from the Postgres fixture is kept as
`backend/tests/fixtures/imported_from_postgres.sql`;
`backend/tests/db/test_imported_fixture.py` migrates it and signs in its
account, so every migration must still apply to an imported database.

Route tests run the real app (`create_app()`) over that database with a real
access token from `selko.services.accounts`. Streaming routes (`/live`) are
tested against a real uvicorn server, because `TestClient` buffers bodies.
Mock providers (Gmail, Graph, Google Calendar, LLMs), never the database.

### Frontend (Vitest)

```bash
# Run tests with JSON output (required for pre-commit hook)
cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json
```

The frontend unit tests stub `fetch`. A field a page reads must also be
returned by a backend route test (`backend/tests/db/test_client_routes.py`),
or nothing proves the API sends it.

### The image

```bash
./scripts/image-lane.sh            # build, then check
./scripts/image-lane.sh <image>    # check an existing image
```

`scripts/image-check.sh` runs the image with a read-only root, no capabilities,
a 400 MB limit and `/data` as the only volume, and checks `/health`, the
production health invariants, sign-up/sign-in/refresh, review with a live
update, attachment download, and the database imported from the Postgres
fixture (`backend/tests/fixtures/imported_from_postgres.sql`).

The native iOS and Android apps are unmaintained and have no tests to run
(`legacy/README.md`).

## Test Markers

| Marker | Description | Requirements |
|--------|-------------|--------------|
| `integration` | Tests under `backend/tests/integration/` | None (SQLite) |
| `llm` / `--run-llm` | Tests requiring real LLM API calls | Provider keys |

## Test Architecture

| Test Type | Database | LLM | Providers | Cost |
|-----------|----------|-----|-----------|------|
| Unit | A fresh SQLite file where needed | Mocked | Mocked | $0 |
| Integration | A fresh SQLite file | Mocked | Mocked | $0 |
| Integration (real LLM) | A fresh SQLite file | **Real** | Mocked | $$$ |
| Image | The image's own `/data` volume | None | None | $0 |

## When to Use `--run-llm`

Use `--run-llm` when changing LLM prompts or response schemas, or debugging
LLM-specific behavior. Not for database, API or business-logic changes. Prompt
changes also run the evals (`docs/evals-process.md`).

## Guards that keep the suite honest

| Test | Fails when |
|------|-----------|
| `test_reachability.py` | a module under `backend/selko/` is not importable from a runtime entry point |
| `test_no_hosted_database.py` | any module imports supabase, postgrest, asyncpg or psycopg |
| `db/test_ownership.py` | a public `selko.db` function touching a user-owned table takes no `user_id` |
| `test_single_data_layer.py` | SQL outside the commit path writes `events` |
| `test_sqlite_schema.py` | a CHECK domain differs from `schema_domains.py::EXPECTED_CHECK_DOMAINS` |
| `test_gate_contract.py` | the gate can pass by refusal or needs a service |

> **Never modify a test to skip when something is missing.** A skip outside
> `skip_budget.toml` fails the gate, and every skip is listed in the manifest.

## Pre-Commit Hook

A git pre-commit hook blocks commits unless tests have been run for changed
modules. `scripts/cloud-setup.sh` sets `core.hooksPath=.githooks`; on another
machine run `git config core.hooksPath .githooks`.

| Module | Evidence the hook accepts |
|--------|---------------------------|
| backend | a passing `.verify/backend-<sha>.json` from `verify.sh backend` with nothing newer, else the pytest cache with no failures |
| frontend | `frontend/test-results.json` |

**Never bypass the hook with `--no-verify`.**

## UI & E2E Testing

For full details, see `docs/ui-testing-guide.md`.

| Platform | Command | What It Tests |
|----------|---------|---------------|
| Web screenshots | `./scripts/capture-all-screenshots.sh web` | The 24-shot light/dark matrix over seeded data |
| Web E2E | `cd frontend && npm run test:e2e -- --project=chromium` | User journeys in a browser |

The Playwright MCP server is for **manual debugging only**.

## Continuous Integration

CI runs on every push and PR and is never the gate: `test.yml` (the whole
backend suite), `frontend-tests.yml`, `image.yml`. The gate is the lanes, run in
the session (`./scripts/verify-lanes.py --gate prod`). See `docs/ci-cd.md`.
