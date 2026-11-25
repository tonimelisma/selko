# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MANDATORY: Bash Command Rules

- **Always `cd` to the worktree/project directory first** in a separate Bash call, then run commands with relative paths. Do NOT use absolute paths to files/directories.
- **Never use `cd` as part of a command** (e.g., `cd foo && make`). Change directory in a separate Bash call first.
- **Never chain unrelated commands with `&&`.** Run each command as a separate Bash tool call.
- All three rules are required — violating them breaks Claude Code's permission system.

---

## MANDATORY: Working with Toni

Toni's standing rules for every project. They live in his `~/.claude/CLAUDE.md`
too, but that file never reaches a cloud session, so they are repeated here.

- **When it is already clear what Toni wants, do it.** Never ask whether to do
  it, how to do it, or which piece to do first, and never end a turn with a
  go-ahead question or a "Yes, do it" button. Ask only for what only Toni can
  do (his accounts, devices, approvals) or a real product choice he has not
  made yet.
- **Never end a turn while any item Toni asked for can still move forward
  without him.** When one item is blocked (the Mac locked, something only he
  can do), go on to the next unblocked one; stop only when every item is done
  or truly blocked, and list just the Toni-only steps at the end.
- **Merge without asking.** Once the scoped lanes for a change pass, open the
  PR and squash-merge it yourself; never stop to ask whether to merge. This
  does not extend to production deploys, which still need an explicit yes.
- **Live tests may write to Toni's real apps; every test removes what it made**
  in its own teardown, even when it fails, and confirms the removal. Never
  leave test data behind.

---

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails; photo-library ingestion is parked) to manage schedules, to-do lists, and digital filing systems. See `PRD_ARCH.md` for complete product requirements and architecture.

---

## MANDATORY: The verification process

This is the whole loop. Do not invent a different one per task.

1. **Run the lanes. Never hand-roll verification.**
   `./scripts/verify-lanes.py --gate prod` before any production deploy.
   Lanes cache on input content, so a re-run
   after a fix executes only what changed.
2. **Read the printed table, not your memory of what you ran.** It states each
   lane's status, duration, and whether it executed or was reused.
3. **Red or BLOCKED means stop.** Fix, re-run, repeat. A lane that cannot run
   is red — never "probably fine".
4. **Report the table plus a recommendation.** Never ask "should I deploy?"
   with no evidence attached.
5. **After deploying, fill in `docs/deploy-log/<date>-<sha>.md`.** T+0 and T+15m
   before you report done; T+24h next day. **Enforced:** the Stop hook
   `.claude/hooks/require-deploy-observation.sh` refuses to end a turn while a
   log dated today or yesterday has a blank T+0/T+15m row or is uncommitted.
   Wait for T+15m *inside* the turn (Monitor with an until-loop). Never end the
   turn on a background sleep and say "waiting": nothing comes back to fill the
   row, which is how three logs shipped with it blank. A window that passed
   unobserved is written as `missed`, never left empty.

| Lane | Gate | What it proves |
|---|---|---|
| `backend` | prod | `./scripts/verify.sh backend`: unit + integration suites; every database test gets a fresh SQLite file with every migration applied |
| `frontend` | prod | `./scripts/verify.sh frontend`: web unit tests and `svelte-check` |
| `image` | prod | `./scripts/image-lane.sh`: builds the image and runs it the way the server does — read-only root, no capabilities, 400 MB, `/data` the only volume — then checks health and the production invariants, sign-up/sign-in/refresh, review + live update, attachment download, and a database imported from a Postgres fixture |
| `prod-health` | observe | `./scripts/check-production-health.sh`: the invariants below against running production |

### Checking that production is actually healthy

```bash
./scripts/check-production-health.sh          # production (api.selkoapp.com)
./scripts/check-production-health.sh <url>    # any deployment
```

It runs the invariants in `scripts/assert-health.sh` — the standard list:

| Surface | Must hold |
|---|---|
| `work-state` | `items_dead_letter`, `attachments_dead_letter`, `stale_processing_emails`, `unclaimable_pending` are **all zero**, whatever the worker posture. `failed_emails` is *not* asserted — terminal failures are permanent history, and requiring them to be zero made this check unsatisfiable forever after the first one |
| `ingestion` | status ok, background processing on, every task alive, the in-process work listener bound (`listener.kind == "in_process"`, `bound`) |
| `root` | publishes a 40-character build SHA (which build answered), and `requests.server_errors_per_hour` is **zero** — a deployment answering 5xx is not healthy, whatever its queues look like |
| `egress` | worker transport is `sqlite` |

The image lane runs the same script against the container it starts, so the
image is held to production's rules before it ships. **A check that never runs
against the environment that matters is not a check**, and one that cannot
return to green is ignored just as fast as one that cannot go red.

**Production is `https://api.selkoapp.com`.** Until the cutover to the signed
image, it still runs the previous (hosted-Postgres) build, whose listener and
transport fields differ: this branch's `check-production-health.sh` is red
against it by construction. For that deployment's deploy-log observations use
its own assertions: `git show 7207aac5:scripts/assert-health.sh`.

### Long-running commands: one at a time, stop what you start

These rules exist because all three were broken in one session: a `uvicorn`
left running for 1h47m, two `xcodebuild` runs driving the same simulator
simultaneously, and an exit code read from `echo` instead of the command.

- **A background task is finished when the harness reports it exited** — not
  when its output looks complete. Some tools print their results and then stay
  alive for minutes.
- **Never start a command that shares a resource** (port 8000, the local
  database) **while another holds it.** Check with
  `ps -eo pid,etime,command`. `verify-lanes.py` enforces this
  with a per-lane lock and reports `BUSY` rather than running anyway.
- **Stop every process you start**, in the same session, as soon as its
  consumer finishes. Never kill a process you did not start — it may be the
  operator's.
- **Never end a command with `; echo "exit=$?"`.** That reports `echo`'s status.
  Let the command's own exit code propagate.
- **Prefer a declared precondition over a hand-started dependency.** If a lane
  needs a service, declare it in `scripts/lanes.toml` under `[[lanes.X.requires]]`
  so it fails closed with a remedy instead of passing only on the machine where
  someone happened to start it.

### Never trust a signal that cannot fail

Every serious defect in this codebase came from a green signal that meant less
than it looked like. A `/health` probe satisfied by *any* server on the port. A
UI test whose assertions sat behind `guard ... else { return }`. An initializer
parameter accepted and discarded. Before trusting a gate, ask: **if this were
broken right now, would this check actually go red?** If not, it is decoration.

---

## MANDATORY: Discovery Before Implementation

Every non-trivial task starts with read-only research and discovery in the main
repository. Diagnose or reproduce the issue, identify the likely root cause,
and form a concrete increment plan before creating a branch/worktree, editing
files, claiming review comments, or making other implementation writes.

- **Worktree creation marks the start of an implementation increment.** Do not
  create one merely to investigate.
- A request to **fix, implement, or change** something authorizes proceeding
  once the issue and increment plan are sufficiently understood; a ceremonial
  approval pause is not required.
- If the user primarily asks questions, requests investigation/discovery, or
  raises several uncertain symptoms, present the findings and proposed
  increment first, then wait for them to choose whether to implement it.
- Simple, low-risk changes with an obvious cause may proceed after a brief
  confirmation in the existing code. Use judgment; the goal is understanding
  before mutation, not process for its own sake.
- Run the late-review audit in Definition of Done step 0 only when a **source
  code increment** actually begins, not during discovery or a docs/config-only
  increment. Never claim or absorb PR review comments into a docs/config-only
  increment; leave them unclaimed for the next source code increment.

---

## MANDATORY: Worktree Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Source code (backend/, frontend/src/)                                 │
│    → MUST use a feature branch + PR                                    │
│      cloud session: in its own clone (no worktree)                     │
│      Mac: in a worktree                                                │
│                                                                         │
│  Config files (.env, docs/, CLAUDE.md, scripts/)                       │
│    → Mac: CAN edit directly in main repo                               │
│      cloud session: session branch + PR like everything else           │
└─────────────────────────────────────────────────────────────────────────┘
```

**Why:** Multiple AI agents work simultaneously. Each cloud session has a
private clone; on the Mac, worktrees isolate each task. PRs ensure CI runs
before merging. The worktree steps below apply to the Mac only — a cloud
session follows "Cloud sessions" instead.

### Naming

| Type | Branch | Worktree |
|------|--------|----------|
| Feature | `feat/add-login` | `selko-feat-add-login` |
| Bugfix | `fix/api-timeout` | `selko-fix-api-timeout` |

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

### Setup & Usage

See `docs/parallel-agents.md` for the full pre-work checklist (sync, create worktree, copy env files, install deps).

> **CRITICAL (Mac):** After setup, your working directory MUST be the worktree (`~/Development/selko-<type>-<task>/`). All commands run from there. If a Bash command is rejected, you're probably in the wrong directory — verify with `pwd`.

### Enforcement

A Claude Code hook **blocks source code edits** in the main repo. You'll see:
```
BLOCKED: Cannot edit source code in the main repository.
```

---

## Cloud sessions (claude.ai/code)

A cloud session (`CLAUDE_CODE_REMOTE=true`) runs in an Ubuntu 24.04 x86_64 VM
with a throwaway clone of this repo. **This is the default way to work**: nothing
in Selko needs the Mac. Everything above still applies, with these differences.

**Setup is automatic.** The SessionStart hook `scripts/cloud-setup.sh` (a no-op
anywhere else) installs uv + Python 3.14, the frontend's npm deps (Node ≥ 22.12;
older Node silently skips rolldown's native binding), points Playwright at the
preinstalled Chrome (`$CHROME_PATH`), sets `core.hooksPath=.githooks`, starts
`dockerd` (the image lane only), and writes a local `.env`: a random
`SELKO_JWT_SECRET`, `SELKO_DATA_DIR=data`, local `ALLOWED_ORIGINS` and labelled
non-functional placeholders for the OAuth client IDs and for any LLM key the
environment does not provide. The backend needs no database service.
`scripts/cloud-setup.sh --status` says what is ready; full log:
`.verify/cloud-setup.log`.

**Worktrees: not used.** The clone is already private to the session. Work on
a feature branch (`git switch -c <type>/<task>`); the edit-guard hook blocks
source edits only while the clone is on `main`. The harness usually checks out
its own session branch (`branch/<name>`, same commit as `main`), so the guard
allows edits from the start; push to that branch. `merge-and-cleanup.sh` moves
the clone onto the merged `main` instead of removing a worktree.

**Where each lane and task runs: all on the VM.**

| Lane / task | Command |
|---|---|
| backend | `./scripts/verify.sh backend` |
| frontend | `./scripts/verify.sh frontend` |
| image | `./scripts/image-lane.sh` (Docker; builds through the session proxy with `scripts/build-image.sh`) |
| web screenshots | `./scripts/capture-all-screenshots.sh web` |
| prod-health, deploy-log windows | `./scripts/check-production-health.sh` |
| LLM evals / real-model tests | `uv run python -m backend.tests.eval.run_eval --fixture <category/name>` (or `--all --all-operations`, per `docs/evals-process.md`); `uv run pytest backend/tests/<file> --run-llm`. Needs the provider keys (Owner setup) |

**LLM keys are the one credential kept as environment variables** (owner
decision), in the dedicated personal "selko" cloud environment. setup never
copies one into a file: `.env` gets a placeholder only for a key the
environment does *not* provide, and a placeholder left from an earlier session
is dropped once the key appears. **Claude Code removes `ANTHROPIC_API_KEY` from
the shells it starts**, so that key is stored as `SELKO_ANTHROPIC_API_KEY` and
mapped back by reference in `CLAUDE_ENV_FILE`.

**GitHub from the VM.** `gh api` REST works (pulls, merges, check-runs,
issues, Actions runs and job logs); GraphQL is refused, so `gh pr
create/list/view/merge` fail — use `gh api repos/tonimelisma/selko/pulls …`.
Pushing tags, deleting refs, releases, repository settings and Actions
secrets/variables are refused too. Merged branches are deleted by GitHub
("Automatically delete head branches").

### Owner setup (Toni only)

Values are never handled by an agent.

**Cloud environment "selko"** (claude.ai → environment settings; personal),
*environment variables* — the LLM keys config.py reads, only those you use:
`SELKO_ANTHROPIC_API_KEY` (the Anthropic key; see above), `GEMINI_API_KEY`,
`OPENAI_API_KEY`, `XAI_API_KEY`, `META_MODEL_API_KEY` (or `META_API_KEY` /
`MODEL_API_KEY`), `MOONSHOT_API_KEY`, `ZAI_API_KEY` (or `ZHIPU_API_KEY`),
`DEEPSEEK_API_KEY`, `ALIBABA_API_KEY`, `MINIMAX_API_KEY`, `TINKER_API_KEY`;
plus `SMOKE_SENTRY_DSN` (a DSN for the synthetic, not production's).

**Image signing needs no secret.** `image.yml` pushes with the workflow's
`GITHUB_TOKEN` and signs keylessly with cosign through GitHub's OIDC token.

**Production's settings** (its env file: `SELKO_JWT_SECRET`, OAuth clients, LLM
keys, `ALLOWED_ORIGINS`, …) live with the server that runs the image, outside
this repository.

---

## Definition of Done

**The DoD scales to what you changed. Run only what your change actually touches — nothing more.** A backend-only change never runs web tests or screenshots.

### 0. Check for unaddressed PR review comments (source code increments only)

Review comments often land **after** a PR has already been squash-merged (async reviewers, bots, ultrareview). At the start of each work increment:

**Skip this entire step for docs/config-only increments.** Do not inspect,
claim, or fix unrelated PR comments while doing documentation or configuration
work. Run it only when the current increment will edit source code.

1. `gh api "repos/tonimelisma/selko/pulls?state=closed&per_page=10" --jq '.[] | select(.merged_at) | [.number,.title] | @tsv'` — the last merged PRs (REST: `gh pr list` needs GraphQL).
2. For each, check for review comments that haven't been addressed yet (`gh api repos/tonimelisma/selko/pulls/<number>/comments` and `gh api repos/tonimelisma/selko/issues/<number>/comments`). Skip comments already marked fixed/claimed by a prior increment.
3. **Claim** any unclaimed, unaddressed comment by posting a reply that you'll fix it, so parallel agents don't duplicate the work.
4. **Fix it** as part of the current increment (same worktree/branch as whatever else you're doing, or its own small PR if unrelated to the current task).
5. **Close the loop** — post a follow-up comment on the original PR explaining how it was fixed (link the commit/PR that fixed it).

This keeps stale review feedback from silently rotting once a PR is merged and out of sight.

## MANDATORY: Verification tiers

CI is not a tier. It runs on every push and PR (the repo is public, so
hosted-runner minutes cost nothing) and is never left red, but the gate is the
lanes, not a green tick.

**Tier 1 — in the session, before the PR merges.** `./scripts/verify.sh backend`
(unit + integration over SQLite; no service), plus the `frontend` and `image`
lanes when their inputs changed. This is the merge gate.

**There is no staging tier any more.** What staging used to stand for — the
shape that actually runs — is now the image lane: the exact image, under the
server's limits, with the production health invariants asserted against it. CI
runs the same check on `main` before it pushes and signs the image.

What no local lane can reach stays real: production data shape, elapsed time
(memory growth, token expiry) and configuration on the server. Those are
observed after deploy, in the deploy log (see "Pick verification by risk
dimension").

### 1. Scope your change

| You changed | Required before merge |
|-------------|-----------------------|
| `backend/**` | `./scripts/verify.sh backend` |
| `backend/selko/db/migrations/**` | `./scripts/verify.sh backend` — every database test applies every migration to a fresh file, so this is what proves the migration executes; plus a run on a production-shaped copy when it touches a populated table |
| `frontend/src/**` | `./scripts/verify.sh frontend` + **web** screenshots |
| `Dockerfile`, `.dockerignore`, `scripts/build-image.sh`, `scripts/image-*.sh`, `selko_import/**` | `./scripts/image-lane.sh` (its inputs include `backend/selko/**` and `frontend/src/**` too; `verify-lanes.py` runs it when any changed) |
| `legacy/**` (the unmaintained iOS and Android apps) | Nothing: don't change them (`legacy/README.md`) |
| `docs/`, `*.md`, `.env*`, other `scripts/`, `.claude/`, config only | Nothing to test — commit & push |

- **Only what you edited counts.** Editing `backend/` requires no web tests or screenshots.
- **Bug fixes MUST include a regression test** in the module you fixed.
- **Production LLM failures MUST also become anonymized regression eval fixtures**
  under `backend/tests/eval/fixtures/`, with hand-written expected output. Run the
  specific fixture before shipping; if the prompt changes, run the broader eval
  suite required by `docs/evals-process.md` to check for regressions.
- **Screenshots** only for the platform whose UI you changed (see "Screenshot Updates"). Skip for backend/docs/config.
- **Every read and write of a user-owned table takes the owner.** There is no
  row-level security: ownership is the `user_id` argument of every public
  `selko.db` function that touches a user-owned table, and
  `backend/tests/db/test_ownership.py` fails on one that lacks it (worker-wide
  functions are allowlisted by name with a reason). A route answers another
  user's row with 404, never 403.
- **An increment is not implemented until its call sites are wired.** Do not
  mark a spec increment done, and do not write "next PR wires the call sites",
  when the new code has no callers. Direct-pg increments 3–5 shipped this way:
  `asyncpg` was never installed, `pg_pool` was never passed to any worker, and
  `WorkListener.start()` was a stub that reported healthy — all with a green
  test suite. If you add a code path behind a flag or an injected dependency,
  add a test that asserts the dependency actually reaches the call.
- **Unreachable code fails the build.** A new module under `backend/selko/`
  must be transitively importable from `selko.api`, `selko.worker_app` or
  `selko.admin` (`backend/tests/test_reachability.py`). The call-site rule
  above was stated three times and broken three times; mocks cannot notice a
  module nobody imports, an import graph can.
- **Nothing reaches a hosted database.** `backend/tests/test_no_hosted_database.py`
  fails if any module under `backend/selko` imports supabase, postgrest,
  asyncpg or psycopg. `selko_import` (outside the package, never in the image) is
  the one reader of the old Postgres database.
- **Never narrow a CHECK constraint without checking its writers.** Enumerated
  text domains are pinned in `backend/tests/schema_domains.py`
  (`EXPECTED_CHECK_DOMAINS`, asserted by `test_sqlite_schema.py`).
- **Events are written only by the fenced commit.** Any SQL that writes `events`
  outside `selko.db.events` (and its listed exceptions) fails
  `backend/tests/test_single_data_layer.py`.
- **SQL that has never been executed has not been tested.** A migration is not
  done because it applies cleanly. It is done when a test has exercised the
  trigger it creates or the column it adds, against a real file. Two Postgres
  migrations once applied cleanly, passed the mocked suite, and broke every
  UPDATE on their first real call. Every database test here runs on a real
  migrated SQLite file, so mock the provider, never the database.
- **A client request is schema, not text.** The web app reads through the
  client API (`backend/selko/api/routes/client.py`); its routes are tested over
  a real database (`backend/tests/db/test_client_routes.py`), and the frontend
  unit tests stub `fetch`. A field a page reads that no route test returns is
  untested — add it to the route test.
- **Configuration is part of the change.** If your increment adds a required
  environment variable, it is not done until that variable is set in every
  environment that runs the code (`.env.example`, `cloud-setup.sh`, the image
  check's env file, and production's env file — tell Toni). A correct diff plus
  a missing value is an outage.

### 1a. Pick verification by risk dimension, not just by file path

File paths decide *which lane runs*. They do not decide whether the change is
dangerous. Eight weeks of production-breaking commits, classified:

| Root cause | Examples | Local tests catch it? |
|---|---|---|
| Config / environment | #218 prod env overrides, #217 workers off by default, #151 auth redirect URLs | **No** — invisible in a diff and locally |
| Production data shape | #351 rehearsal vs real rows, #196 review incident | **No** — the local DB is empty or seeded |
| Elapsed time / runtime | #191 OOM (~2 MB/min), #235 Outlook token refresh mid-pass | **No** — needs hours of running |
| Observability gaps | #215 surface prod integration failures | **No** — you cannot test what is never reported |
| Tests hiding bugs | #232 "the production bugs it was hiding" | The tests *were* the problem |

Only the last row is code logic. Our verification is dense on the axis that
rarely breaks and thin on the three that do, which is why "lots of tests" and
"production broke again" are both true at once. Adding unit tests does not move
these numbers. Match the dimension instead:

| Dimension your change touches | Required beyond the lanes |
|---|---|
| A one-line config or env var | Verify the value **in the target environment**. A correct diff plus a missing value is an outage; `.env.example` proves nothing |
| Migration touching a populated table | Run it on a copy of a production-shaped database (`selko_import` output, or the fixture in `selko_import/fixture/`). A migration that applies cleanly to an empty file has not been tested |
| Worker, loop, or long-running path | Watch RSS and `/health/egress` over hours, recorded in the deploy log. A laptop has no memory ceiling and no token expiry |
| New user-owned table | Its `selko.db` functions take `user_id` (`backend/tests/db/test_ownership.py` fails otherwise) |
| New code path behind a flag or injected dependency | A test asserting the dependency actually reaches the call site |
| Pure logic, no schema/config change | The lanes are sufficient |

**A 500-line refactor with no schema or config change is usually safer than a
one-line `.env` edit.** Scope verification to that reality.

### 1b. Run the lanes, don't hand-roll the verification

```bash
./scripts/verify-lanes.py --gate prod     # blocks a production deploy
./scripts/verify-lanes.py --gate observe  # measures running production; blocks nothing
./scripts/verify-report.py                # what each lane costs and has caught
```

**`observe` is deliberately not a deploy gate.** It measures the *currently
deployed* production, so blocking a deploy on it deadlocks: a degraded
production makes the gate red, and the change that would heal it can never
ship. Run it after deploying — `docs/deploy-log/TEMPLATE.md` calls it at each
observation window.

Lanes are declared in `scripts/lanes.toml`. The runner fingerprints each lane's
declared inputs by **content**, so a lane that already passed for exactly those
inputs is reused rather than re-run: fix one lane, run again, and only that lane
executes. Results are keyed by fingerprint, so reverting an edit restores the
cached result instead of forcing a re-run.

Every lane execution appends to `.verify/ledger.jsonl` (duration, outcome,
executed-or-reused) and each run writes `.verify/runs/<id>.json`. That history is
what makes verification improvable: `verify-report.py` shows which lanes have
ever caught a real failure and what each costs, so a lane that has never fired
across many runs can be demoted on evidence rather than kept on faith.

**A lane that cannot run is RED, never skipped.** The image lane is red when
Docker is unavailable. Silence is not success.

**Production is the image** (backend + web app in one process), and the lanes
above are the only ones. The native iOS and Android apps are unmaintained
(`legacy/README.md`): no lane, CI job, hook or setup step builds or tests them.

### 2. Ship it

- [ ] Source code → feature branch (cloud: the session's clone; Mac: a worktree). Config/docs on the Mac may go to `main` directly; a cloud session uses its branch + PR.
- [ ] The scoped lanes above pass in the session — **the lanes are the gate, not CI**
- [ ] Commit (conventional format), push, open the PR over REST: `gh api repos/tonimelisma/selko/pulls -f head=<branch> -f base=main -f title=… -f body=…` (`gh pr create` needs GraphQL, which the cloud proxy refuses)
- [ ] `./scripts/merge-and-cleanup.sh <pr_number>` — squash-merges over REST and cleans up: GitHub deletes the remote branch itself, the script deletes the local branch, moves the clone to the merged `main` (cloud) or fast-forwards `main` and removes the worktree (Mac). **Does not wait on CI.**
- [ ] **Check CI on `main` and fix forward if it ran and failed** — the `actions/runs?branch=main` query under "CI Ownership". On `main`, `image.yml` is what publishes `ghcr.io/tonimelisma/selko:<sha>`: a red image job means nothing new ships.
- [ ] If your change ships (`backend`/`frontend`/image), **report the `--gate prod` lane table and state a recommendation**. A bare "Should I deploy this to production?" with no evidence attached asks the operator to adjudicate a question the lane table already answers.
- [ ] **Production deploys.** A merge to `main` publishes a signed image; the server that runs production pulls and verifies it (cosign identity: `image.yml` on `refs/heads/main`). Deployment itself lives outside this repository. **Never change what production runs without Toni's explicit yes for that SHA.** The first cutover from the previous hosted-Postgres build imports its data once, on the server, with the signed importer image `ghcr.io/tonimelisma/selko-import:<sha>` (`database` copies and checksums every table; `attachments` copies every Storage object and verifies its size and SHA-256; secrets are read from files, never a command line; database exit 3 = schema drift, 5 = verification failed, nothing written; attachments exit 6 = missing or mismatched objects, re-runnable) — `docs/specs/sqlite-single-process/04-data-cutover.md`.
- [ ] **After any production deploy, open a `docs/deploy-log/<date>-<sha>.md` entry from `TEMPLATE.md` and fill the T+0 and T+15m rows before reporting done.** The T+24h row is filled the next day. Config, real-data and elapsed-time failures are only observable here — a deploy is not finished when it is applied, it is finished when it has been watched. Always fill in "which gate should have caught it"; that is what turns an incident into a permanent gate improvement instead of folklore.

See `docs/parallel-agents.md` for the full workflow. See `docs/ci-cd.md` for CI architecture details.

### CI Ownership — never a gate, but never ignored

**CI runs on every push and PR, and it is never a merge gate.** The gate is the
lanes in the session. Workflows: `test.yml` (the whole backend suite),
`frontend-tests.yml` (web unit tests, `svelte-check`, build), `image.yml`
(build, image check, and on `main` push + cosign sign).

**A red CI is never left red.** A status nobody reads is worse than no status.

**MANDATORY — after every merge to `main`, check CI and fix forward.**

```bash
gh api "repos/tonimelisma/selko/actions/runs?branch=main&per_page=3" \
  --jq '.workflow_runs[] | [.id,.name,.event,.conclusion] | @tsv'
```

If it failed:
1. **Diagnose** — `gh api repos/tonimelisma/selko/actions/runs/<id>/jobs --jq '.jobs[] | [.id,.name,.conclusion] | @tsv'`,
   then `gh api repos/tonimelisma/selko/actions/jobs/<job id>/logs | tail -80`
2. **Code issue** — follow-up PR.

**A CI job may never imply coverage it does not have.** If a job cannot run part
of its verification, it says so in its own output rather than passing quietly.
A green tick that reads as more than it is has caused more damage here than a
red one.

### Worktree Cleanup Rules

`merge-and-cleanup.sh` cleans up for you. For any manual removal the safety rule stands:

**NEVER force-remove a worktree (`--force`) without first inspecting uncommitted work.**
1. `cd` to the worktree, run `git status`
2. Uncommitted/untracked files? **Review them manually** — they may hold real work or artifacts
3. Use `git worktree remove` (no `--force`). If it refuses, that's the safety mechanism — inspect first
4. `git worktree remove --force` destroys uncommitted work with no recovery — treat it like `rm -rf`

---

## Essential Commands

| Command | Purpose |
|---------|---------|
| `./scripts/verify.sh backend` | Backend tests (unit + integration over SQLite) |
| `npm run test:unit -- --reporter=json --outputFile=test-results.json` | Frontend tests (from `frontend/`) |
| `uv run uvicorn selko.api.app:app --port 8000` | Local API over `SELKO_DATA_DIR` (migrates at startup; serves `SELKO_WEB_DIR` when set) |
| `uv run python -m selko.admin migrate \| delete-account <uuid> \| seed-demo <email>` | Operator commands (also inside the image) |
| `./scripts/build-image.sh [tag]` | Build the image locally |

See `docs/testing-guide.md` for the full test guide.

---

## Platform Preferences

**The web app is Selko's only client.** There is no CLI and no MCP connector
(both removed 2026-11-25). The native apps in `legacy/ios/` and
`legacy/android/` are unmaintained (owner decision, 2026-11-25): never edit,
build or test them, and don't read them as a description of how Selko works.

### Web — SvelteKit + DaisyUI
- SvelteKit 2 with Svelte 5 (runes syntax)
- DaisyUI semantic colors only — never use raw Tailwind colors (`text-blue-500` etc.)
- Custom themes `selko-light` and `selko-dark` in `frontend/src/app.css` (Tailwind v4 `@plugin "daisyui/theme"`; there is no `tailwind.config.js`)
- `svelte-check` CI is strict about types — use JSDoc annotations where needed
- `design/tokens.json` is the canonical control contract. Use
  semantic control primitives; static statuses are plain icon/text, NEW is
  neutral, Included/Excluded is a labeled switch, and all targets are ≥44.

---

## UI Testing & Visual Verification

**Standard workflow:** Use `./scripts/capture-all-screenshots.sh web` to capture screenshots, then review them for visual correctness. The script handles seeding, building, and capturing automatically.

**MCP tools** (Playwright) are for **manual debugging only** — e.g., clicking a new button, testing a specific interaction, or investigating a visual bug that screenshots alone can't diagnose. Do NOT use MCP tools or `/verify-*` slash commands as a standard verification step.

**Key warnings:** Screenshots must be **≤ 2000 px** in both dimensions (resize with `sips --resampleHeight 1920`). Never use `fullPage: true` in Playwright.

**Full details:** `docs/ui-testing-guide.md`

---

## Screenshot Updates (DoD)

**When to update:** Only when UI-visible code changed. Skip for backend-only, docs, or config changes.

**One command — do NOT manually seed data, run individual scripts, or use MCP tools:**

| Changed files | Command |
|---------------|---------|
| `frontend/src/` | `./scripts/capture-all-screenshots.sh web` |
| Shared code (schema, seed data) affecting the UI | `./scripts/capture-all-screenshots.sh web` |

The script handles seeding, starting the API, capturing and resizing. See `docs/screenshot-guide.md` for details.

---

## Architecture Principles

- **One process, one file.** The image runs one uvicorn worker that serves the
  built web app, the API and the background workers on one port. All state is
  in `SELKO_DATA_DIR` (`/data` in the image): `selko.db` and `attachments/`.
  Settings come from an env file. The root filesystem is never written.
- **One writer, many readers.** `selko.db.Database` keeps one writer connection
  behind a lock with `BEGIN IMMEDIATE`, and reader connections in WAL mode
  (`query_only`). Every write is a `db.write()` transaction; `tx.now` is one
  strictly increasing UTC timestamp per transaction; timestamps are stored as
  fixed-width `YYYY-MM-DDTHH:MM:SS.ffffffZ` text. Tables are `STRICT`; JSON
  columns are `CHECK (json_valid(...))`. Migrations live in
  `backend/selko/db/migrations/` and apply at startup (`selko.db.migrate`, with
  a hash-checked ledger and a `VACUUM INTO` backup before each).
- **Typed errors, not driver errors.** `selko.db.errors` translates SQLite
  failures into `NotFound`, `NotOwned`, `InvalidArgument`, `UniqueViolation`,
  `CheckViolation`, `ForeignKeyViolation`, `NotNullViolation`, `DbBusy` and the
  proposal-state errors; services and routes catch those.
- **An operation has exactly one implementation.** Services keep their old
  parameter names (`client`, `supabase_client`, `pg_pool`) but the value is the
  `Database`. Never write a second path for the same operation; the guards in
  `backend/tests/test_workers.py` (`test_no_compat_shims_in_workers`) and
  `test_single_data_layer.py` enforce it.
- **Work arrives by signal, not by polling.** A committed write that creates
  work calls `tx.emit_work(...)`; `selko.db.bus.WorkSignals` wakes the waiting
  worker after commit (it replaced Postgres `LISTEN/NOTIFY`). Changes a user
  should see call `tx.emit_live(user, resource)`; the in-process `Bus` fans them
  out to `GET /live`, a Server-Sent Events stream (Bearer token, 25 s heartbeat,
  re-auth at expiry, at most 5 streams per user). The safety-net poll is a
  floor, not a schedule.
- **Own sign-in.** `selko.services.accounts`: bcrypt passwords (imported GoTrue
  `$2a$10$` hashes verify unchanged), HS256 access tokens signed with
  `SELKO_JWT_SECRET` (`SELKO_JWT_SECRET_PREVIOUS` verifies during a rotation),
  and a rotating refresh token in the `selko_refresh` cookie (HttpOnly,
  SameSite=Strict, Path=/auth; only its SHA-256 is stored; reusing a rotated
  token revokes the session). Cookie endpoints check `Origin`. Password
  sign-ins are rate-limited per address separately from refreshes.
- **The web app talks only to the API.** There is no database client in the
  browser: `frontend/src/lib/api/client.js` sends the Bearer token and does one
  shared refresh on 401; the access token lives in memory only.
- **Attachments are files.** Stored under `<SELKO_DATA_DIR>/attachments/` as
  `{user_id}/{uuid12}_{filename}` (written to a temp file, fsynced, renamed;
  paths outside the directory are refused), served owner-only by
  `GET /attachments/{id}/content`.
- **Reliable email ingestion:** Gmail uses paginated initial scans plus History cursors; Outlook resolves immutable well-known folder IDs before traversing and uses one delta cursor per included folder. Eligible provider folders are scannable but hidden from Settings, permanent/hidden trees are excluded, and folder preferences go through `selko.db.email_sync.set_email_folder_preference`. Email outcomes/reprocessing are exposed through the paginated History workflow.
- **Calendar component capture:** Email acquisition parses every inline/attachment Gmail `text/calendar` part and Outlook meeting metadata into `email_calendar_components` through the single atomic `selko.db.emails.save_email_with_attachment_descriptors`. Empty component payloads never erase an earlier parse.
- **Calendar identity matching:** `event_identity.py` canonicalizes content-free UID, provider-thread, join, and management hints. The resolution ladder applies authoritative UID/revision matching, exact join/time duplicates, and only two-signal supporting correlation before the local-day LLM fallback. Hints are written only by the fenced `selko.db.events.commit_email_extraction`, whose hint lookup set is fingerprinted together with the local-day band (producer and commit share `hint_fingerprint`).
- **Event review integrity:** `event_change_proposals` is the authoritative owner of update/cancellation review state; `event_sources` retains provenance only. Pending proposals require `events.review_status='active'`; event `status` never represents the Changes lane. Apply, reject, reopen, and repair transitions go through `selko.db.proposals`, and review clients fail closed when proposal details are unavailable. **Every extraction decision states an explicit `intent`** (`no_change`/`apply`/`review`/`record_only`) and, except for `record_only`, an explicit `fields.review_status`; `commit_email_extraction` raises rather than defaulting either. It used to derive auto-apply from `review_status='active'` — the same value a pending proposal requires — so an unstated decision silently applied the change and wrote to the user's calendar. Delivery follows `review_status`, never `intent`. **Updates to an approved event Selko created apply automatically** (`intent="apply"`, calendar upsert, an applied proposal kept for History/undo); only an event adopted from the user's own calendar (`event_sources.source_origin='google_calendar'`) — or a change the model reads as a cancellation — waits in the Changes lane. An unknown provenance fails closed to review. A **declined event (`rejected`/`cancelled`) is terminal**: later emails still record provenance and identity hints, which is what keeps the match working and prevents a duplicate in the New lane, but never revive it (`docs/specs/review-queue-integrity.md` §8.2). **One exception:** an email the extractor flags `booking_confirmed` (ticket receipt, completed registration, accepted RSVP) reopens a `rejected` event into the New lane — never to the calendar — because buying tickets reverses the user's own decision. A school-play receipt was swallowed this way. `cancelled` (the organizer's word) stays terminal. `_enqueue_calendar_work` no longer promotes review status and refuses an upsert for a declined event.
- **Durable email polling:** the only email ingestion path. `IngestionRuntime` starts inside the FastAPI process (one process: web app, API and workers) whenever `ENABLE_BACKGROUND_PROCESSING` is on, and owns leased provider discovery, durable identity acquisition, independent attachment retries, reconciliation, and safe health notifications. Single ownership comes from leases written under the single writer (lease expiry plus a generation fence), not process topology. There is no APScheduler and no `email_fetch` task — the coordinator owns its own cadence. New integrations become pollable via the `integrations_ensure_email_sync_state_*` triggers; `request_email_sync_now` asks for a prompt poll. `selko.worker_app` runs the identical task set standalone.
- **Durable email work state:** a `pending` email is invariant-guaranteed claimable (`emails_pending_is_claimable_check`: `attempts < max_attempts`, no owner, no unexpired lock). `claim_unprocessed_email` opportunistically reclaims one expired `processing` lease per call before claiming fresh work, so a crashed worker's row recovers on the next claim, never on a restart or a periodic sweep. `fail_email_processing` is the single fenced retry-or-terminate transition; a stale `(worker_id, lock_generation)` is a no-op. Provider discovery leases (`email_sync_state`/`email_sync_runs`) are generation-fenced end to end via claim → heartbeat → complete/fail, and at most one `running` run exists per integration by a partial unique index. `selko.db.health.health_work_state` is the single counted health query behind both `/health` and `/health/ingestion`; it reports `unclaimable_pending` (actionable, degrades the rollup) separately from `failed_emails` (terminal history, never degrades it) — merging them made `degraded` permanent after the first exhausted retry; see `docs/specs/state-ownership-and-deterministic-recovery.md` S1–S5 for the implemented current model.
- **Single-owner calendar sync:** Approval and proposal application enqueue `calendar_work_items`; the item owns action, generation, attempts, lease, error, and provider-write fencing. `events.review_status` owns the user decision — queueing calendar work never writes it, so each caller states the decision itself before enqueueing — while API and clients derive delivery state from the latest non-superseded work item. Automatic cancellation enqueues an item with `action='cancel'`. Background workers are the sole Google Calendar writers for both upserts and cancellations. Explicit `/events/{id}/sync` requests idempotently observe or requeue worker-owned work.
- **Two calendar providers, one code path:** events are written to Google Calendar *or* Outlook Calendar. `selko/services/calendar_providers.py` holds both adapters, and both speak Google Calendar's event shape, so the writer, mirror, dedup read-back and undo divergence checks never branch on provider. **Provider identity lives in the ids:** Google ids stay bare, Outlook ids are stored qualified as `outlook:<graph id>` — in `user_calendar_settings.target_calendar_id`, `events.google_calendar_event_id` (historical name, kept so imported rows and the code keep one vocabulary) and `calendar_entries.provider_event_id`. Routing (`selko.db.calendar_work.calendar_write_provider`): an event already in a calendar stays there, otherwise the target calendar's provider, otherwise Google if connected. The claim stamps `calendar_work_items.provider`, only claims items whose provider is writable, and takes the providers whose circuit is closed (`BREAKER_KEYS`: `google_calendar`, `outlook_calendar`). One Microsoft consent covers mail and calendar (`Calendars.ReadWrite`); **a mail-only Outlook grant is not a writable calendar**, and its refresh must request only the scopes it holds (`outlook.refresh_scopes`) — asking for more fails the refresh and would expire mail too. Never mark the Outlook integration expired from a calendar failure: that row also carries mail.
- **Measure what the API answers, not only what the workers are doing.** Every
  health invariant here was internal — dead letters, worker liveness, listener,
  transport — so `POST /events/{id}/apply-change` could return 500 to *every*
  request for eight days with all of them green. `request_metrics` counts
  responses by outcome and `/health` publishes `requests.server_errors_per_hour`,
  which `assert-health.sh` requires to be zero.
- **A route no test calls has not been tested.** The service function under
  `apply-change` was well covered; the route itself had no test, so
  `applied["status"]` was never executed and survived the deletion of
  `events.status` in the removal of `events.status`. This is the HTTP twin of the SQL rule
  in the Definition of Done: coverage of the layer underneath proves nothing about the layer users
  actually reach.
- **An unhandled exception must still return a CORS-bearing response.**
  Starlette's `ServerErrorMiddleware` sits outside `CORSMiddleware`, so a bare
  crash produces a 500 the browser refuses to read — the client reports a
  network failure ("Load failed" in Safari) and the real error is invisible.
  `app.py` registers a catch-all handler so a 500 arrives as a readable 500.
- **Health signals must be able to return to green.** A gauge that can never
  read zero is ignored exactly as fast as one that can never go red, and this
  codebase has shipped both. `unclaimable_emails` counted permanent terminal
  failures alongside actionable stuck rows, so one failed email pinned
  production to `degraded` forever (fixed by splitting
  `unclaimable_pending` from `failed_emails`). The incident evaluator raised a
  *critical* `stale_poll` against integrations that are deliberately not polled,
  so an expired OAuth token did the same for 18 days. Before adding a health
  signal, ask what makes it go back to green, and whether that is something the
  system does on its own.
- **Reconnect recovery:** Google Calendar reauthorization atomically creates a durable `integration_recoveries` generation (`selko.db.recovery.complete_integration_reauthorization`) that requeues OAuth-blocked calendar work items; email resumes from provider cursors via the `integrations_ensure_email_sync_state_*` triggers with no recovery record. Auth failures are classified on `calendar_work_items.failure_code` (`oauth_required`/`oauth_scope_required`) and never trip the global provider circuit breaker. The ConnectionRecovery card on the web shows catch-up progress (`GET /integrations/recovery`, owner-scoped).
- **Outbound traffic is metered:** `selko.services.egress` attributes every outbound byte to a destination (`gmail`/`graph`/`llm`) and a bounded operation template, exposed at `/health/egress` and logged every `EGRESS_LOG_INTERVAL_SECONDS`. The database is a local file, so it has no egress; `/health/egress` reports the worker transport as `sqlite`. This exists because a platform bandwidth alert reports a total with no attribution, which cannot tell constant polling apart from real provider downloads. Idle loops must not exist. Work arrives by notification; the safety-net poll is a floor, not a schedule. Any new unconditional periodic call must be justified in the PR body against the two rules above: work arrives by notification, and the safety-net poll is a floor rather than a schedule.
- **Fenced-resolution health:** `/health` exposes content-free, process-local resolution conflicts-per-hour, retry histogram, fenced-write count, conflict-exhaustion count, and pending-email age gauges. Event extraction writes are committed only through `commit_email_extraction`; any other SQL that writes `events` fails `backend/tests/test_single_data_layer.py`. Google Photos ingestion remains parked.
- **End-to-End First:** Complete full journeys before expanding scope. First journey: Email → Calendar Event.
- **LLM-Centric AI:** All intelligence uses multimodal LLMs (multi-provider registry; production runs `claude-haiku-5-5` only, `LLM_FALLBACK_PROVIDER=none`; an unset fallback is auto-filled, so `none` must stay explicit). Every provider that can receive email content is named in the public privacy policy at `/privacy`, so changing either is a policy change.
- **YAGNI:** Add complexity only when measured need exists.

**Details:** `PRD_ARCH.md`, `docs/specs/sqlite-single-process/`

---

## Self-Maintenance Rule

**This CLAUDE.md is the single source of truth for all AI agents.** After major changes (new tables, endpoints, routes, docs, env vars, or architectural shifts), update this file. Keep it concise — link to detailed docs rather than duplicating content. Every linked doc must exist; remove stale links.

---

## Environment & Config

| File | Purpose |
|------|---------|
| `.env` | Local development (`ENVIRONMENT=development`) |
| `.env.production` | Production values on a machine that runs production locally, optional; the image reads its env file through the process environment |
| `.env.example` | Template for setup |

Key settings: `SELKO_DATA_DIR` (database and attachments), `SELKO_JWT_SECRET`
(≥ 32 bytes; `openssl rand -hex 32`) and `SELKO_JWT_SECRET_PREVIOUS` during a
rotation, `ALLOWED_ORIGINS` (cookie endpoints refuse any other `Origin`),
`API_PUBLIC_URL`, `FRONTEND_URL`, `ENABLE_BACKGROUND_PROCESSING`,
`GIT_COMMIT_SHA` (set by the image build; published by `/health`).
Microsoft Outlook OAuth uses `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`
from a Microsoft Entra app registration.

### MANDATORY: Environment separation

**Never move production credentials or data into development.** Production
holds real users' OAuth refresh tokens and mail; a development machine is a
lower-trust environment. Never copy production's `selko.db`, its attachments or
an import of its old database anywhere but the server that runs production.
Reading production state for diagnosis is fine (health endpoints, counts).
Print no tokens and copy nothing.

---

## Reference Index

| Topic | Document | When to Read |
|-------|----------|--------------|
| **SQLite single process** | `docs/specs/sqlite-single-process/` | **Read first** for anything about storage, auth, the client API, `/live`, the image or the data cutover. Schema (01), data layer (02), API/auth/web (03), cutover (04), verification (05) |
| **Worktree workflow** | `docs/parallel-agents.md` | Before any source code task |
| **Testing** | `docs/testing-guide.md` | Before running tests |
| **Database schema** | `docs/database-schema.md` | When working with data |
| **API workflow** | `docs/api-workflow.md` | When working with Python API |
| **CI/CD** | `docs/ci-cd.md` | When troubleshooting CI or the image |
| **Job queue** | `docs/job-queue.md` | When working with background jobs |
| **Gmail integration** | `docs/gmail-integration.md` | When working with email sync |
| **Microsoft Graph failure ledger** | `docs/microsoft-graph-failure-ledger.md` | Before changing Graph request/retry/resync behavior or after any production Graph failure |
| **OAuth reconnect catch-up** | `docs/specs/oauth-reconnect-catch-up.md` | When implementing automatic email/calendar recovery after OAuth reauthorization |
| **Deploy log** | `docs/deploy-log/` | Before and after every production deploy. Records what shipped, T+0/T+15m/T+24h observations, and **which gate should have caught** anything that broke |
| **Executable truth** | `docs/specs/executable-truth.md` | Before trusting any gate or spec status (historical record; the Postgres mechanics it names are gone, the rules stand) |
| **Parallel extraction, fenced commit** | `docs/specs/parallel-extraction-fenced-commit.md` | Before touching worker concurrency, `save_extracted_events`, or how extracted events are persisted |
| **Calendar identity and cancellation** | `docs/specs/calendar-identity-and-cancellation.md` | Before touching iCalendar parsing, event identity/dedup, or cancellation |
| **Review queue integrity** | `docs/specs/review-queue-integrity.md` | Normative requirements for web Review (§5), identity (§7), cancellation (§8). **§6's fenced-lane mechanism is superseded** — see parallel-extraction-fenced-commit |
| **Event identity reach** | `docs/specs/event-identity-reach.md` | Before touching dedup, invite handling, or why an event the user already has appears as New |
| **LLM integration** | `docs/llm-integration.md` | When working with LLM features |
| **Architecture** | `PRD_ARCH.md` | For product requirements and architecture |
| **UI user journeys** | `docs/ui/01-user-journeys.md` | When planning frontend work or understanding user flows |
| **Screen specifications** | `docs/ui/02-screen-specs.md` | When implementing any web screen |
| **UI patterns & components** | `docs/ui/03-patterns-and-components.md` | Before building any UI component, to follow conventions |
| **Brand guide** | `docs/brand-guide.md` | When implementing any UI, choosing colors, fonts, or terminology |
| **UI testing** | `docs/ui-testing-guide.md` | When writing E2E tests or using MCP visual verification |
| **Screenshot capture** | `docs/screenshot-guide.md` | When capturing web screenshots |
| **LLM eval system** | `backend/tests/eval/README.md` | When working with LLM evaluation or benchmarking |
| **Evals process** | `docs/evals-process.md` | When running evals, interpreting results, or iterating on prompts |
| **Implementation specs** | `docs/specs/` | When planning or implementing a new feature (see `docs/specs/README.md`) |

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
