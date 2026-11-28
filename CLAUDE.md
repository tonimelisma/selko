# CLAUDE.md

## What this is

Selko reads a user's email (Gmail, Outlook), extracts calendar events with a multimodal LLM, lets
the user review them in a web app, and writes approved events to Google Calendar or Outlook
Calendar. It ships as one signed container image (`ghcr.io/tonimelisma/selko`): one Python 3.14
process (FastAPI, in-process workers, the built SvelteKit 2 web app) over one SQLite file.
Production is `https://api.selkoapp.com`. Backend tooling is `uv`; the web app is npm (Node ≥ 22.12).
Architecture: [docs/architecture.md](docs/architecture.md). The software is proprietary (see
`LICENSE`).

## Working style

- When it is clear what is wanted, do it. Ask only for what only the user can do, or for a real
  product choice nobody has made yet.
- Don't end a turn with a summary announcing the next step, an offer to continue, or a list of
  decisions that block nothing: take the next step.
- Stop only when nothing can move forward without the user, or when what blocks you is
  deliberately protected (a permission, a ruleset, a secret). Then say exactly what is needed.
- Still confirm destructive or irreversible actions outside the normal flow (deleting data,
  rewriting history, changing settings); the normal flow (branch, commit, PR, merge, release) is
  not one of them.
- Live tests clean up everything they create in their own teardown, even when they fail, and
  confirm the removal.

## Product invariants

- One process over one SQLite file; all state in `SELKO_DATA_DIR`; the root filesystem is never
  written. ([ADR 0001](docs/adr/0001-one-process-one-sqlite-file.md))
- One owner per data directory: the server holds a `flock` on `.selko.lock`; a second owner
  refuses to start. ([ADR 0002](docs/adr/0002-one-owner-per-data-directory.md))
- One writer connection, a pool of four WAL readers; never a transaction across LLM or provider
  I/O. ([ADR 0003](docs/adr/0003-one-writer-many-readers.md))
- Nothing reaches a hosted database: no supabase, postgrest, asyncpg or psycopg anywhere.
  ([ADR 0004](docs/adr/0004-no-hosted-database.md))
- The web app is the only client and talks only to the API; the native apps were removed (git
  history keeps them). ([ADR 0005](docs/adr/0005-web-app-is-the-only-client.md))
- Selko's own sign-in: bcrypt, short-lived HS256 access tokens in memory, a rotating HttpOnly
  refresh cookie. ([ADR 0006](docs/adr/0006-own-sign-in.md))
- Attachments are files under the data directory, owner-only.
  ([ADR 0007](docs/adr/0007-attachments-are-files.md))
- Work arrives by signal, not by polling; the safety-net poll is a floor, not a schedule.
  ([ADR 0008](docs/adr/0008-work-arrives-by-signal.md))
- Production extraction runs one Anthropic model (`claude-haiku-5-5`) with
  `LLM_FALLBACK_PROVIDER=none` kept explicit; every provider that can receive email content is
  named on `/privacy`, so changing either is a policy change.
  ([ADR 0009](docs/adr/0009-llm-centric-extraction-one-model.md))
- Every extraction decision states its intent; declined events are terminal, except that a
  `booking_confirmed` email reopens a rejected event into New.
  ([ADR 0010](docs/adr/0010-explicit-extraction-intent-and-declined-terminal.md))
- Events are written only by the fenced extraction commit; extraction stays parallel.
  ([ADR 0011](docs/adr/0011-parallel-extraction-fenced-commit.md))
- One state owner per concern; background workers are the only calendar writers.
  ([ADR 0012](docs/adr/0012-one-state-owner-per-concern.md))
- API keys are read from Azure Key Vault by the process at startup; nothing is pushed, rendered
  or kept in `.env`. ([ADR 0013](docs/adr/0013-keys-from-key-vault-at-startup.md))
- A merge to main releases to production through a signed image the server follows.
  ([ADR 0014](docs/adr/0014-merge-to-main-releases-a-signed-image.md))
- Health signals must be able to return to green, and health includes what the API answers.
  ([ADR 0015](docs/adr/0015-health-signals-return-to-green.md))
- Every read and write of a user-owned table takes the owner; another user's row is a 404.
  ([ADR 0016](docs/adr/0016-ownership-by-user-id-in-the-data-layer.md))
- Email is the only input; photo-library ingestion is not re-proposed.
  ([ADR 0017](docs/adr/0017-email-is-the-only-input.md))

Backend and web conventions that follow from these: `.claude/rules/backend.md`,
`.claude/rules/frontend.md`.

## Engineering philosophy

- No compatibility shims. When a structure is wrong, replace it and migrate its callers in the
  same change.
- The smallest correct design. Simplicity first; measure before optimizing, never optimize on a
  hunch.
- One owner per fact, per mutation and per side effect. Two places that know the same thing will
  disagree.
- Abstractions only at real boundaries (a process, a network, a storage format, a platform), not
  in anticipation.
- Don't guess and don't fabricate: an unknown API, path, value or result is looked up, measured or
  reported as unknown.
- You own the repository. Nothing is "pre-existing" or someone else's problem, and red CI is never
  waived: it is fixed first.
- Comments and docs describe current behavior and why it is that way, never its history.
- Never trust a signal that cannot fail. Before trusting a gate, ask: if this were broken right
  now, would this check go red? If an invariant matters enough to write down, it matters enough to
  assert.
- End to end first: complete a full journey before expanding scope. Add complexity only when a
  measured need exists.

## Engineering practices

- Test first. A change in behavior starts with a test that fails without it.
- Every bug, CI failure and review finding gets a regression test, seen failing before the fix;
  quote its red output in the PR.
- The instrumentation flywheel, every increment:
  - Never guess a bug's cause. If the logs and metrics can't explain it, add the instrumentation
    first, so this occurrence or the next one is diagnosable, then fix.
  - Never guess at performance: measure, keep a baseline, optimize, and report before and after.
  - Even when nothing is blocked, review the instrumentation on every path you touched: add what
    was missing, remove what is noise.
- Tests are hermetic: temporary directories and fixtures, never the developer's real data, config
  or accounts.
- Every database test runs on a real SQLite file with every migration applied
  (`backend/tests/sqlite_fixtures.py`). Mock providers (Gmail, Graph, Google Calendar, LLMs), never
  the database. SQL that has never been executed has not been tested: a migration is done when a
  test exercised the trigger or column it adds.
- A route no test calls has not been tested: test the route, not only the service under it.
- An increment is not implemented until its call sites are wired. Code behind a flag or an
  injected dependency gets a test asserting the dependency reaches the call. Unreachable modules
  fail `backend/tests/test_reachability.py`.
- The guards that keep the suite honest: `backend/tests/db/test_ownership.py` (every user-owned
  data function takes `user_id`), `backend/tests/test_reachability.py`,
  `backend/tests/test_no_hosted_database.py`, `backend/tests/test_single_data_layer.py` (events
  written only by the fenced commit), `backend/tests/test_sqlite_schema.py` with
  `backend/tests/schema_domains.py` (CHECK domains pinned: never narrow one without checking its
  writers), `backend/tests/db/test_imported_fixture.py` (every migration applies to the imported
  database), `backend/tests/test_startup_footprint.py`, `backend/tests/test_logging.py` (ids, never
  email content), `backend/tests/db/test_health.py`.
- Production LLM failures also become anonymized regression eval fixtures under
  `backend/tests/eval/fixtures/` with hand-written expected output. Run that fixture before
  shipping; if the prompt changes, run the broader suite `docs/design/evals.md` requires.
- Configuration is part of the change. A new required environment variable is set in every
  environment that runs the code (`.env.example`, `scripts/cloud-setup.sh`, the image check's env
  file) in the same PR, and production's env file needs it too: tell the maintainer. A correct
  diff plus a missing value is an outage.
- Verify by risk dimension, not only by file path: a config value is checked in the target
  environment; a migration on a populated table runs on a production-shaped copy; a long-running
  path is watched after release ([research](docs/research/2026-08-22-production-breakage-root-causes.md)).
- Environment separation: never move production credentials or data into development. Never copy
  production's `selko.db` or attachments anywhere but the server that runs production. Reading
  production state for diagnosis (health endpoints, counts) is fine; print no tokens and copy
  nothing. The repository is public: never put user data in a workflow artifact.
- Every action in `.github/workflows/` is pinned to a commit SHA with a `# vX.Y.Z` comment, and
  tools in `run:` to an exact version.
- Long-running commands: stop every process you start as soon as its consumer finishes, never
  start one that shares a resource (port 8000, the local database) while another holds it, and
  never kill a process you did not start. `scripts/verify-lanes.py` holds a per-lane lock and
  reports `BUSY` instead of running twice. A lane that needs a service declares it under
  `[[lanes.X.requires]]` in `scripts/lanes.toml`, so it fails closed with a remedy.
- No formatter is configured; match the surrounding style.

### Verification lanes

Lanes are declared in `scripts/lanes.toml` and run by `scripts/verify-lanes.py`, which fingerprints
each lane's inputs by content and reuses a lane that already passed for exactly those inputs. Read
the printed table (status, duration, executed or reused), not your memory of what ran. Every
execution is recorded in the lane ledger (`.verify/ledger/<run id>.jsonl`, tracked).
**A lane that cannot run is red, never skipped**: the image lane is red without Docker.

| Lane | Gate | What it proves |
|---|---|---|
| `backend` | prod | `./scripts/verify.sh backend`: unit + integration suites over SQLite |
| `frontend` | prod | `./scripts/verify.sh frontend`: web unit tests and `svelte-check` |
| `image` | prod | `./scripts/image-lane.sh`: the image under the server's limits (read-only root, no capabilities, 400 MB, `/data` the only volume), health and production invariants, sign-up/sign-in/refresh, review + live update, attachment download, the imported database |
| `prod-health` | observe | `./scripts/check-production-health.sh`: the health invariants against running production; blocks nothing |

`observe` is deliberately not a merge gate: it measures the currently deployed production, so
blocking on it would deadlock a fix for a degraded production.

| You changed | Must pass before merge |
|---|---|
| `backend/**` | `./scripts/verify.sh backend` |
| `backend/selko/db/migrations/**` | the backend lane (every database test applies every migration to a fresh file), plus a run on a production-shaped copy when it touches a populated table |
| `frontend/src/**` | `./scripts/verify.sh frontend` and `./scripts/capture-all-screenshots.sh web`, reviewed |
| `Dockerfile`, `.dockerignore`, `scripts/build-image.sh`, `scripts/image-*.sh`, the imported fixture | `./scripts/image-lane.sh` (its inputs include `backend/selko/**` and `frontend/src/**` too) |
| docs, `*.md`, `.env*`, other scripts, `.claude/` | `script/process-check` |

Only what you edited counts: a backend-only change runs no web tests or screenshots. CI runs the
same lanes; the scoped lanes passing in the session plus a green `CI gate` is the merge decision.

## Commands

```sh
script/verify                                   # backend + frontend lanes and script/process-check; run before every push
./scripts/verify-lanes.py --gate prod           # every prod lane, cached by input content
./scripts/verify-lanes.py --gate observe        # measure running production
./scripts/verify-report.py                      # what each lane costs and has caught
./scripts/verify.sh backend                     # backend suite
./scripts/verify.sh frontend                    # web unit tests + svelte-check
./scripts/image-lane.sh                         # the image lane (needs Docker)
SELKO_KEYVAULT_AUTH=off uv run pytest backend/tests/<file>::<test> -q   # one backend test
npm --prefix frontend run test:unit             # web unit tests
npm --prefix frontend run check                 # svelte-check
./scripts/capture-all-screenshots.sh web        # web screenshots after a UI change
./scripts/check-production-health.sh [<url>]    # health invariants (default production)
uv run uvicorn selko.api.app:app --port 8000    # local server over SELKO_DATA_DIR
uv run python -m selko.admin migrate | delete-account <uuid> | seed-demo <email>
uv run python -m backend.tests.eval.run_eval --fixture <category/name>   # LLM evals (needs the vault keys)
script/process-check                            # requirements, Validates tags and doc links agree
script/stage start | pre-merge <PR> | post-merge <PR>
```

Cloud sessions: the SessionStart hook `scripts/cloud-setup.sh` installs uv + Python, the web app's
npm dependencies and Docker, and writes a local `.env` (a random `SELKO_JWT_SECRET`,
`SELKO_DATA_DIR=data`, local `ALLOWED_ORIGINS`, labelled placeholders for OAuth clients).
`scripts/cloud-setup.sh --status` says what is ready. The backend needs no database service.

## Configuration

Key settings: `SELKO_DATA_DIR`, `SELKO_JWT_SECRET` (at least 32 bytes) and
`SELKO_JWT_SECRET_PREVIOUS` during a rotation, `ALLOWED_ORIGINS`, `API_PUBLIC_URL`,
`FRONTEND_URL`, `ENABLE_BACKGROUND_PROCESSING`, `GIT_COMMIT_SHA` (set by the image build, published
by `/health`). `.env` is local development; `.env.example` is the template.

LLM provider keys and the Google and Microsoft OAuth clients come from Azure Key Vault, read by
`backend/selko/keyvault.py` at startup ([ADR 0013](docs/adr/0013-keys-from-key-vault-at-startup.md)):
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (the legacy cloud-session name
`MELISMA_SECRETS_CLIENT_SECRET` is still accepted as the secret), `SELKO_KEYVAULT_URL` (LLM provider
keys), `SELKO_KEYVAULT_HOSTS_URL` (OAuth clients), `SELKO_KEYVAULT_AUTH=off|gce`. A variable already
set always wins; a key that cannot be read is absent, so what needs it fails rather than passes.
Until the server's env file provides them, the production image carries the four non-secret values
from build arguments (repository Actions variables). The specific vaults, tenant and app
registrations live in the maintainer's secrets and server repositories; values are never handled
here. A key set by hand in a cloud environment goes in `SELKO_ANTHROPIC_API_KEY`, because Claude
Code removes `ANTHROPIC_API_KEY` from the shells it starts.

Cloud sessions' GitHub access: `gh api` REST works; GraphQL, tag pushes, ref deletion, releases and
repository settings are refused.

## Where docs live

- `docs/index.md` maps every doc. Requirements live in `docs/requirements/<area>.md`: stable
  `SEL-NNN` IDs, one EARS sentence each, current behavior only, each `[verified]` by a test tagged
  `Validates: <ID>` (`# Validates:` in Python, `// Validates:` in JS) or `unverified: <why>`.
  Future work lives in GitHub issues, not in docs.
- `docs/architecture.md` says how the code is built and why; `docs/adr/NNNN-title.md` records each
  decision (superseded, never deleted); `docs/lessons.md` holds rules learned and open problems,
  and is pruned when they are resolved.
- `docs/design/<module>.md` describes one module and starts with `GOVERNS: <paths>`: change those
  paths, update that doc. Dated research and measurements go to `docs/research/YYYY-MM-DD-title.md`.
  `docs/deploy-log/` is history from before the release health job; nothing new is written there.
- Update the docs and this file in the same PR as the code they describe.

Where to read first:

| Topic | Document |
|---|---|
| Storage, transactions, migrations | `docs/design/data-layer.md`, `docs/design/database-schema.md` |
| Sign-in and sessions | `docs/design/auth.md` |
| The API the web app uses, `/live` | `docs/design/client-api.md`, `docs/design/api.md` |
| Extraction, identity, review, calendar delivery | `docs/design/event-lifecycle.md` |
| Background workers and mail polling | `docs/design/workers.md` |
| OAuth connect and reconnect recovery | `docs/design/integrations.md` |
| Microsoft Graph behavior | `docs/design/microsoft-graph.md` (read before changing Graph retry, cursor or auth; add an entry after a production Graph failure) |
| LLM providers and prompts | `docs/design/llm.md`, `docs/design/evals.md`, `backend/tests/eval/README.md` |
| CI, the image and release | `docs/design/ci-cd.md` |
| Tests | `docs/design/testing.md`, `docs/design/ui-testing.md` |
| Web UI | `docs/design/user-journeys.md`, `docs/design/screens.md`, `docs/design/ui-patterns.md`, `docs/design/brand.md`, `docs/design/screenshots.md` |

## Increment lifecycle

1. **Start**: `script/stage start`. Anything red on main or in the last scheduled run, and any
   unanswered review comment on recent PRs, is fixed before new work. Read the open issues.
2. **Ready**: write the Definition of Ready in the PR body: the problem, requirement IDs or
   issue, acceptance criteria, what is out of scope.
3. **Test first**, then implement with the instrumentation flywheel.
4. **Verify** with the one verify command; it must be green before pushing.
5. **Docs** (requirements, architecture, ADRs, lessons, this file) in the same PR.
6. **Land**: PR, wait for `CI gate`, squash-merge, which releases (see Git, CI and PRs).
7. **Report**: after the merge, one PR comment with the Definition of Done checklist and the final
   increment report (below).

A plan that spans several increments lives in a GitHub tracking issue with a checklist, never in
a file. Never committed: per-PR report or readiness files, session state or resume files, ledgers
of merged PRs. That information belongs in the PR and its comments.

## Git, CI and PRs

- One branch per increment, cut from a fresh `origin/main`, named `feat/`, `fix/`, `docs/`,
  `chore/`, `refactor/` or `perf/` plus a short topic. Never reuse a branch after its PR merged;
  never name a branch for the tool that wrote it.
- Every change lands through a PR whose body fills `.github/pull_request_template.md`. CI checks
  the body, and that a PR titled `fix...` changes a test.
- `CI gate` is the one required check: a job that needs every other job. Wait for it
  (`script/stage pre-merge <PR>`), and fix every failure; never bypass it.
- Squash-merge as soon as `CI gate` is green, without asking: in a cloud session with
  `gh api -X PUT repos/<owner>/<repo>/pulls/<N>/merge -f merge_method=squash -f sha=<head sha>`
  (`script/stage post-merge <PR>` does this); locally with `gh pr merge --auto --squash`.
- Merging to main releases; nobody tags or publishes by hand.
- The cloud sessions' GitHub proxy refuses tag pushes, branch deletion and GraphQL: use the REST
  API (`gh api`), and leave branch deletion to GitHub's delete-on-merge and the branch-cleanup
  workflow.
- Commit messages: an imperative subject saying what changed; the body says why.
- **Merging to main deploys to production automatically.** One-off production data operations (a
  data cutover, anything that deletes or rewrites production data) need an explicit yes from the
  maintainer.
- CI, workflow `CI` (`.github/workflows/ci.yml`): runs on PRs (including `edited`), pushes to main,
  a weekly schedule and dispatch. Jobs: `changes` (path filters; scheduled and dispatched runs run
  everything), `backend` (pytest over SQLite), `frontend-unit` (unit tests with coverage),
  `frontend-build` (build, `svelte-check`), `image` (builds the image and runs
  `scripts/image-lane.sh`, then checks the image resolves its Key Vault settings; on a push to main
  whose diff touches the image's inputs it pushes `ghcr.io/tonimelisma/selko:<sha>` unsigned),
  `process` (`script/process-check`, `script/pr-check`), and `CI gate` (needs all, the one required
  check, always reports).
- Release, workflow `Image` (`.github/workflows/image.yml`): runs on `workflow_run` of CI completing
  successfully for a push to main. Its `release` job cosign-signs (keyless) the pushed `:<sha>`
  digest and moves `:main`; the signing identity is `.github/workflows/image.yml@refs/heads/main`,
  which the server verifies, so never rename the file or move the signing job. The server follows
  `:main` within minutes. The `health` job then polls `https://api.selkoapp.com/health` for up to
  15 minutes until it answers with that commit and runs `scripts/check-production-health.sh`; on
  failure it opens an issue labelled `deploy-failure`. A `deploy-failure` issue is fixed first, like
  red CI. Nobody writes deploy-log entries.
- After a merge, check main: `gh api "repos/tonimelisma/selko/actions/runs?branch=main&per_page=3"
  --jq '.workflow_runs[] | [.id,.name,.event,.conclusion] | @tsv'`. A CI job may never imply
  coverage it does not have: if it cannot run part of its verification, it says so in its output.

## Privacy review

Before every commit, read your own staged diff (`git diff --cached`) and remove anything private
about the maintainer, their family or their computers: people's names, addresses, personal email
addresses and accounts, hostnames, home-directory paths, IP addresses, tenant, client or vault
IDs, real personal documents or photos. Use neutral stand-ins in tests and examples. There is no
list of private terms to check against: judge the diff.

## Definition of Done

An increment is done when every line holds; the final report marks each ✅ or ❌ with evidence:

- [ ] Start stage clean: main CI, the last scheduled run and recent review comments were green or
      fixed first.
- [ ] Tests first; the regression test's red output before the fix is quoted.
- [ ] The verify command is green, and CI is green on the final commit.
- [ ] Traceability and doc checks (`script/process-check`, `script/pr-check`) are green.
- [ ] Docs and CLAUDE.md are updated in the same PR.
- [ ] Instrumentation reviewed on touched paths: what was added, what removed, or why it is
      adequate.
- [ ] Privacy review done on every commit's staged diff.
- [ ] Every review thread is answered or resolved.
- [ ] Merged; main CI green; the release it produced is linked.
- [ ] Clean up: only main and open PRs' branches remain on the remote; the working tree is clean.

### Final increment report

One PR comment after the merge, with these parts:

1. **Done / not done**: what the increment delivered, and anything left out.
2. **Definition of Ready**: as written, and whether it held.
3. **Requirements, ADRs and docs**: IDs added, changed or retired; ADRs; docs touched.
4. **Design decisions**: each with the alternatives considered and why they lost.
5. **Verification evidence**: commands, CI run links and durations, release link.
6. **Regression test**: name and red output before the fix (or "no bug fixed").
7. **Diagnosis**: for a bug, the root cause and how it was established.
8. **Instrumentation**: added, removed, and gaps still open.
9. **Performance**: before and after numbers, or "not touched".
10. **Privacy review**: done on every commit; anything removed.
11. **Smells**: what looked wrong but was out of scope.
12. **Follow-ups**: each filed as an issue, linked.
13. **Definition of Done**: the checklist above, each line ✅ or ❌ with evidence.
