# Foundation Integrity — make the repo's claims verifiable, then deploy

**Status:** Partially implemented (updated 2026-08-10). F1–F3, F5, and F9
are merged in PRs #287–#291. F6 has a preserved migration-order guard in draft
PR #292 but still needs authoritative staging/production migration state. F7
has a fail-closed staging verifier in draft PR #293 but its staging execution,
worker drill, and 24-hour soak remain pending. F4 schema-contract tests are not
implemented yet because the required local database reset/fixture proof has not
run. F8 production cutover remains blocked on F7 and explicit operator approval.
**Written:** 2026-08-10, after reviewing the C1–C9 batch (#279–#286 + `0654d4fe`).
**Audience:** a developer new to this codebase. Every increment names the file,
the line, the failing test to write first, and the exact command that proves it
is done. If you hit something undecided while implementing, that is a defect in
this spec — stop and fix the spec first.

**Supersedes nothing.** It completes
[`direct-pg-completion-and-live-ui-hardening.md`](direct-pg-completion-and-live-ui-hardening.md)
and unblocks [`cutover-verification-20260807.md`](cutover-verification-20260807.md).

---

## 1. The honest diagnosis

The C1–C9 batch is good work. The spec behind it is the best document in this
repository: it opens by telling you not to trust the older specs, it lists
exactly what was claimed versus what was actually running, and it deletes rather
than deprecates. It found and fixed genuine, serious defects.

It should not have needed to exist.

Every defect it repaired shares a single cause, and that cause is still present
today:

> **Nothing in the development loop executes the system.**

The Definition of Done gate for backend work is
`uv run pytest backend/tests/ -m "not integration"`. That runs 1,033 tests
against `MagicMock`. It never opens a Postgres connection, never executes a
migration, never fires a trigger, never opens the asyncpg pool. CI cannot
substitute for it — the project has a standing policy never to fund Actions
minutes, and PR CI runs the same `-m "not integration"` selection anyway
(`.github/workflows/test.yml:75`). Staging cannot substitute for it either:
`.env.test` sets `ENABLE_BACKGROUND_PROCESSING=false`, so staging has never run
a worker.

The failure signature this produces is consistent and documented in the repo's
own history:

| Defect | How it shipped green |
|---|---|
| Direct-pg Inc3–5 shipped as unreachable code (`asyncpg` never installed, `pg_pool` never passed, `WorkListener.start()` a stub) | mocks don't notice a dependency that is never injected |
| `20260809000001` inserted into `attachments (file_name, file_size)` — columns that have never existed | the SQL was never executed |
| `20260809000003` referenced `NEW.sync_status` on `public.events` — a column that has never existed; **every** `UPDATE` on events raised | the trigger was never fired |
| `scripts/assert-schema-code-compat.sh`, the gate written to catch exactly this, does not work (§2, D2) | the gate was never run against a drifted database |
| Web realtime rejoin backoff never grows (§2, D1) | the test asserts a rejoin is *scheduled*, not that the delay increases |

There are 26 integration test files under `backend/tests/integration/`,
including three written by this very batch specifically to catch these bugs
(`test_integration_work_listener.py`, `test_integration_worker_pool_port.py`,
`test_broadcast_fanout.py`). **None of them runs in any gate** — not local DoD,
not PR CI. CI runs integration tests only on push to `main`, only against
staging, and only those marked `staging`.

So the tests that would have prevented the batch were written by the batch and
are still unreachable.

### 1.1 The second problem: the deployment gap

Production is at code `a50e1e4e` with schema `20260803000002`
(`cutover-verification-20260807.md:28`). Since then:

- **96 commits**
- **21 migrations**

None deployed. Every day this grows, and every increment adds to a cutover that
has already been deferred three times across three specs. A 21-migration
cutover into a system whose worker path has never run outside a laptop is not a
deploy, it is an experiment.

There is also a contradiction in the repo's own record: `.env.production:31`
says `ENABLE_BACKGROUND_PROCESSING=true`, while
`cutover-verification-20260807.md:3` states the flag must stay `false` until
cutover. One of those is wrong and a reader cannot tell which.

### 1.2 What this means

The problem is not care, effort, or skill — the specs demonstrate all three. The
problem is that **the repo's claims about itself are checked by reading, not by
running.** Reading scales badly: it already leaked three times inside the batch
that was auditing for exactly this class of defect.

---

## 2. Defects found reviewing the C1–C9 batch

These are the concrete findings from the review. Each has an increment below.
None of them is a regression from a previously working state; all are defects
introduced or left in place by the Aug 9–10 work.

### D1 — Web realtime rejoin retries forever at a fixed 1 s (high)

`frontend/src/lib/live-updates.js:158`

```js
let rejoinAttempts = 0;              // declared INSIDE start()
channel.subscribe((status) => {
    ...
    const delay = Math.min(1000 * 2 ** rejoinAttempts, 60000);
    rejoinAttempts += 1;
    setTimeout(() => { stop().then(() => start(uid)); }, delay);   // ← new start(), new closure
});
```

The rejoin path calls `start(uid)` again, which re-declares `rejoinAttempts = 0`.
The exponential backoff therefore never advances past the first step: every
retry waits exactly 1 000 ms, forever.

A private channel that fails authorization does not self-heal, which is the
precise case the C6 comment says this code exists for. In that case the browser
opens one Realtime connection per second indefinitely. For a project whose
architecture principle is *"Outbound traffic is metered… idle loops must not
exist"*, this is a permanent 1 Hz idle loop against Supabase Realtime.

iOS and Android do **not** have this bug — both keep `rejoinAttempts` in a
long-lived loop scope (`LiveUpdateService.swift:67`, inside `while !Task.isCancelled`;
`LiveUpdateRepository.kt:71`, inside the status-collection loop). Web is the
outlier, so this is also a cross-platform parity break.

Related, same file: the terminal-status handler cannot distinguish a deliberate
`stop()` (sign-out, layout teardown) from a server drop. `stop()` sets
`userId = null` at line 194, and the handler reads `const uid = userId` — so
whether a signed-out user's channel gets resurrected depends on callback timing.

**Existing test gives false confidence:** `live-updates.test.js:64` asserts only
that a rejoin is scheduled.

### D2 — The R5 schema gate still cannot fail (high)

`scripts/assert-schema-code-compat.sh:36`

```bash
REMOTE_VERSIONS=$(echo "$REMOTE_RAW" | grep -oE '[0-9]{14}' | sort -u)
```

`$REMOTE_RAW` is the whole output of `supabase migration list --linked`, which
contains **both** a local and a remote column per row. A migration present
locally but missing remotely still prints its version in the local column, so
the grep captures it into `REMOTE_VERSIONS`, `comm -23` finds nothing missing,
and the gate exits 0.

Verified against the real CLI output on this machine (the CLI emits JSON here):

```
$ printf '{"migrations":[{"local":"20260811000004","remote":"","time":"..."}]}' | grep -oE '[0-9]{14}'
20260811000004
```

A migration that exists only locally is reported as applied remotely. The commit
message for C8 is *"make schema/code compat gate real — versions, not counts"*;
the count→version change is correct, but the gate is still incapable of
returning non-zero for the condition it exists to detect. This is the gate that
guards the production cutover.

### D3 — The listener connection has neither TCP keepalives nor a command timeout (medium)

`backend/selko/services/pg.py:162-169`

The module docstring promises *"H3: TCP keepalives at 60s plus app heartbeat."*
The keepalive hook `_enable_tcp_keepalives()` is passed to `create_pool()` via
`init=` (line 104) — but `WorkListener._connect()` calls `asyncpg.connect()`
directly and passes neither the keepalive hook nor `command_timeout`.

The listener is the one connection in the system that sits idle for minutes at a
time and therefore needs keepalives most; pool connections are the ones that
churn. Consequences:

1. No `SO_KEEPALIVE` — a NAT or load balancer can silently drop the socket, and
   the OS never notices.
2. No `command_timeout` — in `_heartbeat_loop`, `await self._conn.execute("SELECT pg_notify(...)")`
   (line 192) on a dead-but-open socket can block indefinitely. It never reaches
   the `wait_for(..., timeout=10.0)` on line 196 that is supposed to detect the
   dead socket. The detector is behind the hang it is meant to detect.

Secondary: when `_connect()` fails inside the reconnect handler (line 219), the
loop returns to the top and sleeps the full `interval` (default 120 s) before
retrying, and `backoff` is not reset on the success path of a reconnect.

### D4 — Three of the four executor paths block the shared drain loop (medium)

C4's stated rule is *"acquire before claim"*, and it also introduced a
**non-blocking** acquire on the LLM path with this rationale
(`workers/pool.py:346`):

> *"non-blocking acquire so a full executor pool does not stall the other work types"*

That rationale is correct and is applied to exactly one of the four paths:

| Path | File:line | Acquire |
|---|---|---|
| LLM email extraction | `workers/pool.py:351` | `wait_for(acquire(), timeout=0.01)` — non-blocking ✅ |
| Calendar sync | `workers/pool.py:321` | `await acquire()` — **blocking** |
| Email acquisition | `workers/email_ingestion.py:644` | `await acquire()` — **blocking** |
| Attachment fetch | `workers/email_ingestion.py:737` | `await acquire()` — **blocking** |

Calendar sync runs *first* in `_process_any_work` and defaults to concurrency 2
(`config.py:487`). `_process_any_work` is awaited serially by `_scheduler_loop`,
so while both calendar slots are busy the scheduler is parked on line 321 and
claims **no** emails and **no** recoveries. A calendar sync is a network call to
Google; if one hangs, the entire worker pool stops processing email, and the
symptom (no email processed) points nowhere near the cause (calendar).

No test covers this: `grep -rn "calendar_semaphore\|_llm_semaphore" backend/tests/`
returns nothing.

### D5 — Migration `20260811000001` is numbered before migrations that already precede it (medium)

C5 (#283, merged 04:59) added `20260811000002/3/4`.
C7 (#285, merged 23:26, **18 hours later**) added `20260811000001`.

On a fresh `supabase db reset` this is harmless: 000001 applies first, and its
`CREATE OR REPLACE` of `broadcast_user_ui_change` plus the narrowed
`trg_events_broadcast_upd` trigger coexist correctly with 000002's replacement
of `trg_events_broadcast`. Locally all four are applied.

It is **not** harmless on any environment that received C5 before C7 existed.
`supabase db push` orders by version; a newly-arrived migration with a version
lower than the highest already-applied one is out of order. Because staging and
production are both far behind, this has not bitten yet — which is exactly why
it must be resolved *before* the cutover rather than discovered during it.

### D7 — Deploying `main` today would fail to start the API (critical)

`backend/selko/config.py:522`, `backend/selko/api/app.py:114`, `.env.test`, `.env.production`

C1 correctly made the direct-pg pool mandatory — there is no fallback, and
`app.py:114` calls `create_pool(config)` unguarded inside the
`enable_background_processing` branch. `assert_session_mode_url` raises
`ConfigurationError("SUPABASE_DB_URL is required when background processing is
enabled")` when the URL is absent, and nothing catches it. That is the correct
design.

The problem is the configuration:

| File | `ENABLE_BACKGROUND_PROCESSING` | `SUPABASE_DB_URL` |
|---|---|---|
| `.env` (local) | — | `postgresql://…@localhost:54322/postgres` |
| `.env.test` (staging) | `false` | **absent** |
| `.env.production` | **`true`** | **absent** |

`config.py:137` defaults `supabase_db_url` to `None` and `config.py:522` reads it
from the environment only. `.github/workflows/test.yml` never supplies it either.
Staging is saved only by having the flag off.

**Production has the flag on and no URL.** Unless the Render production service
carries a `SUPABASE_DB_URL` that exists nowhere in the repository, deploying
`main` to production hard-fails at startup.

This defect is the argument for §3 Tier 2 in one example. The C1 diff is
correct. Every unit test passes. Local execution passes, because `.env` has the
URL. A reviewer reading the PR sees nothing wrong, because nothing *in the diff*
is wrong — what is missing is a value in an environment no test has ever run
against. Only deploying to a real environment surfaces it.

### D8 — Local Postgres cannot test the session pooler, by construction (structural)

`backend/selko/services/pg.py:48-50`

```python
if host in ("localhost", "127.0.0.1", "::1"):
    if port not in (5432, 54322):
```

Port 54322 is local Supabase's **direct** Postgres. Local Supabase has no
Supavisor. So every hypothesis the direct-pg transport rests on — H1 (LISTEN/NOTIFY
survives session mode), H3 (dead-socket detection through the pooler's idle
timeouts), H4 (the pooler host resolves over IPv4) — is untestable on a
developer machine no matter how rigorous the local suite becomes.

This is not a defect to fix. It is a permanent boundary that dictates where the
verification tiers must sit, and the reason staging has to be part of the loop
rather than a final step.

### D6 — Repo hygiene: 161 MB / 13 008 tracked eval result files (low, but growing)

`backend/tests/eval/results/` is deliberately tracked
(`backend/tests/eval/results/.gitignore`: *"Results are tracked in git for
debugging and regression analysis"*). That decision is defensible; its current
execution is not. Results accumulate one file per
(operation, model, thinking, fixture, prompt_hash) and nothing ever prunes
superseded prompt hashes. Every clone pays 161 MB and 13 008 inodes.

---

## 3. The to-be state: three verification tiers, none of them CI

The project already made the decisive call once: **deploys moved off CI onto the
developer's machine** (`supabase db push` run locally, `merge-and-cleanup.sh`
never waiting on CI). That call was right, and the same reasoning applies to
verification. CI is not a tier here. It is a bonus that may never fire.

The tiers exist because each catches a class the one below it **cannot** catch —
not "is less likely to", *cannot*. D8 is the proof for Tier 2: local Supabase has
no Supavisor, so the pooler hypotheses are unreachable locally by construction.
D7 is the proof in the other direction: a missing environment value is invisible
to every local test and every code review, because nothing in the diff is wrong.

### Tier 1 — Local execution gate. Every increment, before the PR merges.

`./scripts/verify.sh backend` starts local Supabase, applies every migration,
and runs unit **and** integration tests against real Postgres with a real
asyncpg pool.

Catches, and catches nothing else can afford to wait on: broken SQL
(`20260809000001`, `20260809000003`), missing RLS (#277), unwired call sites
(direct-pg Inc3–5), trigger errors, schema drift. Fast, free, deterministic,
offline. Of the eight defects in §2, Tier 1 catches four.

### Tier 2 — Staging verification. Every increment, right after merge.

`./scripts/verify.sh staging` pushes migrations, deploys, waits for health, and
runs the `staging`-marked suite against the deployed system — **from the
developer's machine, not from CI**.

Catches what Tier 1 structurally cannot:

| Class | Why local cannot reach it | Evidence |
|---|---|---|
| Missing/wrong environment configuration | the value is absent from an env no local test loads | **D7 — prod would fail to start today** |
| Supavisor session-mode LISTEN/NOTIFY (H1) | local is direct Postgres on 54322; no Supavisor exists | **D8** |
| Pooler host resolution, IPv4/IPv6 (H4) | localhost is exempted from the check | `pg.py:44-50` |
| Dead-socket detection through real idle timeouts (H3) | no NAT or LB in front of localhost | D3, and the drill it blocks |
| Render memory ceiling / OOM | 512 MB limit does not exist locally | the ~2 MB/min leak that OOM-killed prod every ~3 h |
| **Real egress numbers** | localhost transfers are not metered by anyone | the 1 690 B → ~100 B claim justifying the entire direct-pg batch **has never been measured** |
| Realtime private-channel authorization | real JWTs, real expiry, real `setAuth` rotation | D1 and the whole of C6 |
| OAuth token refresh at real expiry | tokens do not expire in a fixture | the recurring `invalid_grant` class |

Thirteen integration files already carry `@pytest.mark.staging`. **They have
never run**, because the only thing that runs them is the
`integration-tests-staging` CI job, which requires the `deploy-staging` job,
which requires Actions minutes that will never be bought. The suite exists; the
trigger is dead. Tier 2 is mostly a matter of moving the trigger to where it
will actually fire.

Note the same is true of the deploy itself: `test.yml:167-192` fires the Render
deploy hooks, and only on a push to `main` in a workflow that does not run. So
**staging has almost certainly never received the last 96 commits either.**
Verify this in F7 step 1 rather than assuming it.

### Tier 3 — Production. Small, deliberate, gated deltas.

After the one-time cutover, the delta between `main` and production is one
increment, not 96 commits. Tier 2 having passed is the precondition for Tier 3.

### What this replaces

| Today | To-be |
|---|---|
| PR gate: mocked tests only | PR gate: Tier 1, real Postgres |
| Post-merge safety net: CI, which never runs | Post-merge safety net: Tier 2, on staging, run by the developer |
| Staging: flag off, never deployed, never tested | Staging: same code and flags as prod, verified every increment |
| Production: 96 commits behind | Production: one increment behind |

### Explicitly out of scope

- **Buying CI minutes.** The policy stands. This plan deliberately puts every
  tier on the developer's machine, where it always fires.
- **New paid Render services.** Tier 2 uses the staging services that already
  exist. No per-branch preview environments — that is why Tier 2 sits
  *after* merge, not before it.
- New product features. Nothing here changes user-visible behaviour except D1.
- Re-litigating the asyncpg transport decision. It is correct and settled.

### The honest cost of Tier 2 being post-merge

Without paid preview environments, staging cannot gate a PR — it can only catch
a defect once the code is on `main`. That is a real weakness and this plan does
not pretend otherwise. It is mitigated, not solved, by:

- Tier 1 being strong enough that anything catchable locally never reaches Tier 2.
- Tier 2 running **immediately** after merge, not batched. A red staging run is
  the top-priority next increment, ahead of new work.
- Fix-forward, matching the project's existing stated posture for CI failures.

For an unusually risky increment (a migration touching a hot table, a change to
the pooler or listener), promote the branch to staging manually *before*
merging. The mechanics are identical — `verify.sh staging` from the branch.

---

## 4. Increments

Each is one PR. Each names the failing test to write **first**. Order matters:
F1 builds confidence with small, self-contained fixes; F2–F4 build the gate;
F5–F6 use it; F7–F8 deploy behind it.

Per `CLAUDE.md`: source code changes need a worktree + feature branch + PR.
Branch names are given. Run the scoped DoD tests before every PR.

---

### F0 — Land the WIP and correct the record ✅ done in this increment

Docs/config only, committed directly to `main`.

- `.claude/launch.json` — untracked dev-server config for the Browser preview
  tooling. Committed.
- `backend/tests/eval/results/extract/gemini_gemini-3.5-flash-lite_low/**` —
  **346 result files for prompt contract hash `0f5dea9702f7`, which is the
  current hash** (verified: `get_prompt_hash("extract")` → `0f5dea9702f7`).
  Zero files with that hash were tracked. This is a complete eval baseline for
  the current prompt — 346 real LLM API calls — that has been sitting untracked
  since 2026-08-07. Committed, so the next eval run does not re-spend them.
- This document, and the `docs/specs/README.md` status corrections.

---

### F1 — Fix the three self-contained defects

**Branch:** `fix/live-update-backoff-and-schema-gate`
**Scope:** `frontend/src/lib/**`, `scripts/**`, `backend/selko/services/pg.py`
**DoD:** frontend unit tests + `npm run check` + web screenshots (D1 touches
`frontend/src/`); backend unit tests (D3).

#### F1.1 — D1: make the web rejoin backoff actually back off

Move the retry state out of `start()` so it survives a rejoin, and add an
explicit "closing on purpose" flag so a deliberate `stop()` does not schedule a
rejoin.

In `frontend/src/lib/live-updates.js`, alongside the other module-level state
(near line 20):

```js
let rejoinAttempts = 0;
let intentionalStop = false;
```

Delete the `let rejoinAttempts = 0;` on line 158. In `stop()`, set
`intentionalStop = true` before `removeChannel` and reset `rejoinAttempts = 0`.
In `start()`, set `intentionalStop = false` after `await stop()`. In the
terminal-status branch, return early when `intentionalStop` is true.

**Write these tests first, in `frontend/src/lib/__tests__/live-updates.test.js`,
and watch them fail:**

1. `it('grows the rejoin delay across consecutive failures')` — drive
   `CHANNEL_ERROR` three times with fake timers; assert the scheduled delays are
   1000, 2000, 4000. Against today's code all three are 1000.
2. `it('caps the rejoin delay at 60s')` — seven consecutive failures; assert the
   seventh delay is 60000.
3. `it('resets the delay after a successful SUBSCRIBED')` — fail twice, then
   `SUBSCRIBED`, then fail; assert the delay is back to 1000.
4. `it('does not rejoin after a deliberate stop')` — call `stop()`, let the
   status callback fire `CLOSED`, advance timers; assert `supabase.channel` was
   not called again.

Do **not** change iOS or Android — both are already correct. Add a one-line
comment in each pointing at the shared invariant so the next person does not
"fix" them into web's shape.

#### F1.2 — D2: make the schema gate capable of failing

The gate must parse the *remote* column only. The CLI supports
`--output-format json`, which removes the parsing ambiguity entirely.

Replace `scripts/assert-schema-code-compat.sh:29-38` with a JSON-based read:
request `supabase migration list --linked --output-format json`, and extract
only entries whose `remote` field is a non-empty 14-digit version. Use `jq` if
present; fail loudly with an actionable message if it is not — per the script's
own rule, *"a gate that exits 0 when it cannot verify is not a gate."*

**Write this test first — `scripts/tests/test_assert_schema_compat.sh`, or a
pytest in `backend/tests/test_scripts.py`, whichever you prefer, but it must
exist:** factor the parsing into a function that takes the CLI output as stdin
so it can be tested without a live project, then assert:

1. Every migration present in both columns → exit 0.
2. One migration present locally, `"remote": ""` → **exit 1**, and the missing
   version is printed. *This test fails against today's script.*
3. Malformed / empty CLI output → exit 1, not exit 0.

#### F1.3 — D3: give the listener connection keepalives and a timeout

In `backend/selko/services/pg.py`, refactor `_enable_tcp_keepalives(idle)` so
its inner `_init` coroutine can be applied to a bare connection as well as
through the pool's `init=`. In `WorkListener._connect()` (line 162), pass
`command_timeout` from config and invoke the keepalive setup on the new
connection immediately after `asyncpg.connect()` returns.

Also, in `_heartbeat_loop`, reset `backoff = 1.0` after a *successful*
`_connect()` in the reconnect branch, and shorten the post-failure wait so a
failed reconnect retries on the backoff schedule rather than after a full
`interval`.

**Write these tests first, in `backend/tests/test_pg.py`:**

1. `test_listener_connection_sets_socket_keepalive` — patch `asyncpg.connect` to
   return a fake connection exposing a mock socket; assert
   `setsockopt(SOL_SOCKET, SO_KEEPALIVE, 1)` was called. Fails today.
2. `test_listener_connection_sets_command_timeout` — assert `asyncpg.connect`
   received a non-`None` `command_timeout`. Fails today.
3. `test_heartbeat_backoff_resets_after_successful_reconnect`.

#### F1.4 — D7: the missing `SUPABASE_DB_URL` (do this first — it is deploy-blocking)

`.env.test` and `.env.production` have no `SUPABASE_DB_URL`, and
`.env.production` has `ENABLE_BACKGROUND_PROCESSING=true`. As written, deploying
`main` to production fails at startup.

**Step 1 — establish the fact.** The Render service may carry the variable even
though the repo does not. Check the staging and production Render services'
environment for `SUPABASE_DB_URL` before changing anything, and record the
answer in the PR body. Do **not** copy any production value into `.env.test` or
into any local file — per `CLAUDE.md`, production credentials never move to a
lower-trust environment. You only need to know *whether* the key is set.

**Step 2 — supply the value in the right place.** The connection string carries
a database password, so it belongs in the Render service environment, never in a
committed file. In `.env.test` and `.env.production`, add a commented marker so
the next reader knows the variable is required and where it lives:

```
# SUPABASE_DB_URL is set in the Render service environment, not here (contains
# the database password). Must be the Supavisor SESSION pooler on port 5432 —
# port 6543 is transaction mode and cannot carry LISTEN/NOTIFY (pg.py H1).
```

Set the real value on the staging Render service now; production waits for F8.

**Step 3 — make the failure legible instead of fatal-at-startup-with-a-traceback.**
Keep it fatal — that part is correct, there is no fallback — but add the check to
config load so the message names the environment and the fix. **Test first, in
`backend/tests/test_config.py`:** assert that
`enable_background_processing=True` with `supabase_db_url=None` raises with a
message containing both `SUPABASE_DB_URL` and `ENABLE_BACKGROUND_PROCESSING`.

**Step 4 — resolve the contradiction in §1.1.** `.env.production:31` says
`true`; `cutover-verification-20260807.md:3` says it must stay `false` until
cutover. Set `.env.production` to `false` and add a comment pointing at F8 as
the increment that flips it. The flag must be turned on deliberately, as the
last step of a cutover, not inherited from a file.

---

### F2 — Make the integration suite run locally, and report honestly what it finds

**Branch:** `test/local-integration-suite`
**Scope:** `backend/tests/integration/**`, `backend/tests/conftest.py`, `scripts/**`
**DoD:** backend unit tests, plus the new suite's own output pasted into the PR body.

This increment is **discovery plus repair**, and it is the one most likely to
surprise you. The 26 integration files have not been run as a suite in a gate.
Some will fail for real reasons; some will fail because they assume staging.
Both outcomes are useful and must be reported, not hidden.

**Step 1 — get a clean database.**

```bash
supabase start
```

```bash
supabase db reset
```

`db reset` applies all 79 migrations in order. If it errors, that is finding
number one and it outranks everything else in this increment.

**Step 2 — run the suite and record the result verbatim.**

```bash
uv run pytest backend/tests/integration/ -m "not staging" -v --tb=short
```

Paste the complete summary line into the PR body. Do not fix anything yet.

**Step 3 — triage every failure into exactly one bucket** and write the table
into the PR body:

| Bucket | Meaning | Action |
|---|---|---|
| **Real defect** | the system is wrong | fix it in this PR, or split it out and link the issue |
| **Stale test** | tests behaviour that was deliberately removed | delete the test, name the commit that removed the behaviour |
| **Staging-only** | needs real Google/Microsoft credentials or the staging project | add the `staging` marker so it is correctly excluded |
| **Environment** | needs `supabase start`, a seeded user, or an env var | fix `conftest.py` so it works from a clean checkout |

**Step 4 — deliver `scripts/verify.sh`.**

```
Usage: ./scripts/verify.sh [backend|frontend|all]
```

For `backend`: assert Supabase is running (fail with the exact `supabase start`
command if not), run `supabase db reset`, then unit tests, then
`pytest backend/tests/integration/ -m "not staging"`. Exit non-zero on any
failure. No mode exits 0 without running something.

**Definition of done:** `./scripts/verify.sh backend` exits 0 on a clean
checkout, and every one of the 26 files is either passing or explicitly marked
`staging` with a one-line reason.

---

### F3 — Promote the execution gate into the Definition of Done

**Branch:** `docs/execution-gate-dod`
**Scope:** `CLAUDE.md`, `docs/testing-guide.md`, `docs/ci-cd.md`
**DoD:** docs only — nothing to test.

Do this *after* F2 goes green, never before. A gate that is red on arrival gets
routed around, and then you have a worse problem than no gate.

`CLAUDE.md` is the single source of truth for every agent working this repo, so
it is where the tier model has to land or it will not be followed. Apply these
four edits exactly.

#### Edit 1 — replace the two backend rows of the "Scope your change" table

Before:

| You changed | Required before merge |
|-------------|-----------------------|
| `backend/**`, `cli/**` | Backend unit tests (`uv run pytest backend/tests/ -m "not integration"`) |
| `supabase/**` (schema/migrations) | Backend unit tests (also deploys to staging on merge) |

After:

| You changed | Required before merge (Tier 1) | Required after merge (Tier 2) |
|-------------|-------------------------------|-------------------------------|
| `backend/**`, `cli/**` | `./scripts/verify.sh backend` — unit **+** integration against local Supabase | `./scripts/verify.sh staging` |
| `supabase/**` (schema/migrations) | `./scripts/verify.sh backend` — the integration run is what proves the migration executes | `./scripts/verify.sh staging` — **required**, migrations must reach staging before prod |

Note the parenthetical *"(also deploys to staging on merge)"* in the old row is
false and must go: that deploy is triggered by the `deploy-staging` CI job,
which needs Actions minutes that will never be bought.

#### Edit 2 — add a new §"Verification tiers" immediately before "Definition of Done"

```markdown
## MANDATORY: Verification tiers

CI is not a tier. It may never run. Both tiers below run from your machine.

**Tier 1 — local, before the PR merges.** `./scripts/verify.sh backend`.
Real Postgres via `supabase start`, all migrations applied, unit + integration
tests. This is the merge gate.

**Tier 2 — staging, immediately after the PR merges.** `./scripts/verify.sh staging`.
Real Supavisor pooler, real Render, real OAuth, real Realtime, real egress.

Tier 2 is not optional and not deferrable, because Tier 1 *cannot* reach what
Tier 2 covers:

- Local Supabase has **no Supavisor**. `.env` points at port 54322, direct
  Postgres. Every session-pooler property — LISTEN/NOTIFY survival, host
  resolution, idle-timeout behaviour — is unreachable locally by construction.
- A missing environment variable is invisible locally and invisible in a diff.
  `SUPABASE_DB_URL` was absent from `.env.test` and `.env.production` while
  `ENABLE_BACKGROUND_PROCESSING=true`; every test passed and the deploy would
  have hard-failed at startup.
- Egress, memory ceilings and token expiry do not exist on a laptop.

**A red Tier 2 run is the top-priority next increment**, ahead of new feature
work. Fix forward. Never let a second increment merge on top of a red staging.
```

#### Edit 3 — add to the Definition of Done prose

As a peer of the existing *"an increment is not implemented until its call sites
are wired"* rule:

```markdown
- **SQL that has never been executed has not been tested.** A migration is not
  done because it applies cleanly. It is done when a test has called the
  function it defines or fired the trigger it creates, against a real database.
  `20260809000001` (inserted into `attachments` columns that have never existed)
  and `20260809000003` (referenced `NEW.sync_status` on `events`, breaking every
  UPDATE) both applied cleanly, passed the full mocked suite, and were broken on
  their first real call.
- **Configuration is part of the change.** If your increment adds a required
  environment variable, it is not done until that variable is set in every
  environment that runs the code. A correct diff plus a missing value is an
  outage. Verify on staging (Tier 2), not by reading `.env.example`.
```

#### Edit 4 — correct the "CI Ownership" section

It currently reads *"Local, change-scoped tests are the only gate."* That
remains true but is now incomplete — it is the pre-merge gate, and staging is
the post-merge one. Rewrite the opening to:

```markdown
**We will never top up GitHub Actions minutes. Never trust CI to run.**

Verification is two tiers, both run from your machine: Tier 1 (local, pre-merge)
and Tier 2 (staging, post-merge). See "Verification tiers" above. CI is a bonus.
If it runs and fails, fix forward; if it never runs, that is expected.

The `deploy-staging` and `integration-tests-staging` jobs in `test.yml` require
Actions minutes and therefore do not run. `./scripts/verify.sh staging` is what
actually deploys and verifies staging. Do not read those jobs as a live path.
```

Finally, update `docs/ci-cd.md` and `docs/testing-guide.md` to match, and state
plainly what is true there: PR CI runs mocked tests only and may not run at all.

---

### F4 — Schema contract tests (the class-killer)

**Branch:** `test/schema-contract`
**Scope:** `backend/tests/integration/test_schema_contract.py` (new)
**DoD:** `./scripts/verify.sh backend`

This is the highest-value increment in the plan. It makes the two Aug 9 defects
structurally unrepeatable.

**Test 1 — every `SECURITY DEFINER` function is callable.**
Enumerate `pg_proc` for `prosecdef = true` in schema `public`. For each, either
invoke it with a realistic argument set from a small fixture registry, or fail
with `f"{name} has no contract test — add one to CONTRACT_FIXTURES"`. Opting out
must be an explicit, reviewable line of code, never silence.

This catches `save_email_with_attachment_descriptors` inserting into
`attachments (file_name, file_size)` the moment it is called.

**Test 2 — every trigger fires without raising.**
Enumerate `information_schema.triggers` for schema `public`. For each triggering
table, insert a minimal valid row, update every column named in the trigger's
`UPDATE OF` list (or one arbitrary column if unrestricted), and delete it.
Assert no exception.

This catches `NEW.sync_status` on the first `UPDATE` — the exact production
break C5 had to repair by hand.

**Test 3 — every table has RLS enabled.**
Query `pg_class.relrowsecurity` for every table in `public`. Assert all true,
with an explicit allow-list constant for any deliberate exception (expected:
empty). `CLAUDE.md` already carries this rule in prose because
`emails_body_html_backup` reached production with RLS off (#277). Prose did not
stop it; this test does.

**Test 4 — no orphaned function grants.** For each `SECURITY DEFINER` function,
assert `EXECUTE` is not granted to `PUBLIC`. `broadcast_user_ui_change` gets this
right (`20260811000001`); assert it for all of them.

**Prove the tests work before trusting them.** For each of tests 1–3, check out
the broken migration, confirm the test fails, then return to `main`:

```bash
git stash && git checkout 26154f3f~1 -- supabase/migrations/20260809000003_live_ui_broadcast.sql
```

Record in the PR body: *"test 2 fails against `20260809000003` with
`record "new" has no field "sync_status"`"*. A contract test that has never
failed is not yet a test.

---

### F5 — D4: stop the executor paths from blocking the shared loop

**Branch:** `fix/executor-head-of-line-blocking`
**Scope:** `backend/selko/workers/pool.py`, `backend/selko/workers/email_ingestion.py`
**DoD:** `./scripts/verify.sh backend`

Apply the LLM path's non-blocking acquire to the other three. Extract the
pattern so the rule lives in one place rather than being restated four times:

```python
async def _try_acquire(sem: asyncio.Semaphore, timeout: float = 0.01) -> bool:
    """Acquire without parking the shared drain loop. Returns False when full.

    Every executor path acquires before claiming (so a claimed row never waits
    in a queue holding its lease) and acquires without blocking (so a saturated
    executor pool for one work type cannot stall the others).
    """
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
```

Use it at `pool.py:321`, `email_ingestion.py:644`, and `email_ingestion.py:737`,
and refactor `pool.py:351` to call it too.

> **Note on `asyncio.wait_for` + `Semaphore.acquire`:** cancelling a granted
> `acquire()` leaked a permit in older CPython. This project runs 3.14
> (`.venv/lib/python3.14`), where the leak is fixed. State this in the
> docstring so nobody re-derives it, and cover it with test 3 below.

**Write these tests first, in `backend/tests/test_workers.py`:**

1. `test_saturated_calendar_executor_does_not_block_email_claims` — fill the
   calendar semaphore, call `_process_any_work`, assert `claim_pending_email`
   was still called. **Fails today** — the call parks on line 321.
2. `test_saturated_acquisition_executor_does_not_block_attachments` — the
   equivalent for `email_ingestion.py`.
3. `test_semaphore_permits_are_not_leaked_by_timeout` — hammer `_try_acquire` on
   a full semaphore 1 000 times, then release everything, then assert the
   semaphore grants exactly `N` permits.
4. `test_claim_never_precedes_acquire` — for all four paths, assert the claim
   function is not called when the semaphore is full. This is C4's rule; nothing
   currently asserts it.

---

### F6 — D5: resolve the migration ordering hazard before it reaches a server

**Branch:** `fix/migration-ordering-guard`
**Scope:** `supabase/migrations/**`, `scripts/**`
**DoD:** `./scripts/verify.sh backend` + `supabase db reset` clean

**Step 1 — establish the fact, do not assume it.** Neither staging nor
production has received any 2026-08 migration according to
`cutover-verification-20260807.md:28`, but that document is three days old.
Confirm before acting:

```bash
supabase link --project-ref lxmysergoeaegxlyfzwk
```

```bash
supabase migration list --linked
```

Repeat for production (`khahcozfbnpykspvatrg`). **Read-only** — do not push.
Record both outputs in the PR body.

**Step 2 — act on what you found.**

- *If neither remote has `20260811000002`* (expected): renumber C7's migration
  from `20260811000001` to `20260811000005` so file order matches authorship
  order. Then `supabase db reset` and confirm the end state is identical — the
  `broadcast_user_ui_change` body from C7 and the `trg_events_broadcast` body
  from C5 must both survive. Assert this with a contract test from F4 rather
  than by reading the SQL.
- *If a remote already applied `20260811000002`*: **do not renumber.** Leave the
  file and add a `docs/` note explaining the out-of-order version, because
  renumbering an applied migration is far more dangerous than the ordering
  itself.

**Step 3 — prevent recurrence.** Add `scripts/check-migration-order.sh`: assert
that the newest migration version in the working tree is greater than every
version already on `main`. Wire it into `scripts/verify.sh`. Write the test that
proves it rejects a lower-numbered new file.

---

### F7 — Build Tier 2: staging becomes a verified environment, every increment

**Branch:** `feat/staging-verification-loop` (for `verify.sh`), plus operational steps.
**Requires:** F1–F6 merged and `./scripts/verify.sh backend` green.
**This is the increment that makes staging part of the process rather than a
final ceremony.** It has two halves: build the tool, then use it.

#### F7a — `./scripts/verify.sh staging`

One command, run from a developer machine, that takes `main` to a verified
staging deployment. It must be safe to re-run and must never touch production.

**Hard safety requirements** — assert these first, and abort before doing
anything if any fails:

1. The linked project ref is `lxmysergoeaegxlyfzwk` (staging). If it is
   `khahcozfbnpykspvatrg`, **abort immediately** — this script must be
   incapable of touching production.
2. `ENVIRONMENT=staging`.
3. Never print a token, password, or connection string. Existence checks only.

**Steps:**

1. **Token freshness** — the recurring `invalid_grant` class. Do not ask anyone
   to re-auth first; the sync script handles the common case:
   ```bash
   uv run python -m cli.cli_seed_tokens --sync --provider gmail
   ```
2. **Schema gate, then migrations** — the gate is real now because of F1.2:
   ```bash
   ./scripts/assert-schema-code-compat.sh --linked
   ```
   On the first run expect this to **fail**, listing the pending migrations.
   That is the gate working. Then `supabase db push --dry-run`, review, push.
3. **Deploy code** — POST the staging Render deploy hook directly. Do **not**
   rely on the `deploy-staging` CI job; it does not run.
4. **Wait for health** — poll `GET /health` until ready or a timeout, then
   `GET /health/ingestion` and `GET /health/egress`. A deploy that boots but
   reports unhealthy is a failure, not a pass. This step alone catches D7.
5. **Run the staging suite:**
   ```bash
   uv run pytest backend/tests/integration/ -m "staging" -v --tb=short -n auto
   ```
   Thirteen files carry this marker and none has ever run. **Expect failures on
   the first execution** and triage them with the same four-bucket table as F2.
6. **Report egress** — print the `/health/egress` delta for the run. This is the
   first real measurement of the 1 690 B → ~100 B claim that justified the
   entire direct-pg batch. Record the number in the PR body. If it does not
   match the claim, that is a finding, and a valuable one.

#### F7b — Turn the workers on in staging

Only after F7a exits 0.

1. Set `SUPABASE_DB_URL` on the staging Render service to the **session pooler**
   host on **port 5432** (F1.4). Port 6543 is transaction mode and cannot carry
   LISTEN/NOTIFY — `assert_session_mode_url` will reject it, which is the check
   working.
2. Set `ENABLE_BACKGROUND_PROCESSING=true` on staging. The worker path — the
   subject of the last three specs — has never run outside a laptop.
3. **Confirm the pooler hypotheses (D8), which nothing local can:**
   - `WorkListener` establishes `LISTEN selko_work` through Supavisor and
     receives a NOTIFY end to end (H1).
   - The pooler host resolves and connects (H4).
   - The H3 dead-socket drill: terminate the listener backend via
     `pg_stat_activity.application_name = 'selko-worker'` and assert the
     listener reconnects. **D3 must be fixed first** or this drill hangs instead
     of failing.
4. `./scripts/drill-lease-recovery.sh`.
5. **Soak 24 h** against the health criteria in
   `cutover-verification-20260807.md:54-61`. Watch RSS for the ~2 MB/min leak
   signature — another thing only a real 512 MB instance shows.
6. **Rehearse the rollback.** `cutover-verification-20260807.md:65` calls it
   *"an assertion, not a tested property"*, and it has carried that caveat since
   hardening finding 30. Execute it on staging: revert, confirm the system runs,
   re-apply. A rollback plan that has never been run is not a rollback plan.

**Definition of done:** `./scripts/verify.sh staging` exits 0 from a clean
checkout; staging has processed real email through the worker path for 24 h with
`items_dead_letter = 0`; the H1/H3/H4 pooler properties are confirmed on real
infrastructure; the rollback has been performed and undone at least once; and
the measured egress figure is recorded.

---

### F8 — Production cutover

**Requires:** F7 complete, including the 24 h soak and the rehearsed rollback.
**Requires explicit approval from Toni before any production step.**

Follow the ordered cutover in
[`cutover-verification-20260807.md`](cutover-verification-20260807.md) §"Ordered
cutover" exactly — migrations first, code second, flag last. Two amendments
from this plan:

- Step 3's gate now actually works (F1.2). If it passes without listing pending
  migrations, something is wrong — investigate before proceeding.
- Before flipping the flag, reconcile the `.env.production` contradiction
  identified in §1.1 so the repo and the running system agree.

---

### F9 — Eval artifact retention

**Branch:** `chore/eval-results-retention`
**Scope:** `backend/tests/eval/**`, `scripts/**`
**DoD:** backend unit tests

161 MB and 13 008 files, growing without bound. Keeping results in git is a
reasonable choice — the alternative is re-spending hundreds of LLM calls to
compare against a baseline. The unbounded part is not.

Add `scripts/prune-eval-results.sh`: for each
(operation, model, thinking, fixture), keep results for the *current* prompt
contract hash plus the *N* most recent superseded hashes (default N=1), delete
the rest. Report bytes and files reclaimed; support `--dry-run`; default to
dry-run so an accidental invocation deletes nothing.

Document in `backend/tests/eval/README.md` when to run it, and record the
before/after file count and size in the PR body.

---

## 5. Sequencing and expected effort

```
F0 ✅ ──▶ F1 ──▶ F2 ──▶ F3 ──▶ F4 ──▶ F5 ──▶ F6 ──▶ F7 ──▶ F8
                                                      │
                                              F9 (any time)
```

| # | Increment | Tier | Size | Blocks |
|---|---|---|---|---|
| F0 | Land WIP, correct the record | — | done | — |
| F1 | Defects D1–D3 **+ D7 (deploy-blocking)** | — | S | F7 |
| F2 | Integration suite runs locally | 1 | **L — unknown until run** | F3, F4 |
| F3 | Both tiers into `CLAUDE.md` + DoD | 1+2 | S | — |
| F4 | Schema contract tests | 1 | M | — |
| F5 | Executor head-of-line blocking (D4) | 1 | M | — |
| F6 | Migration ordering (D5) | 1 | S | F7 |
| F7 | **Build Tier 2: `verify.sh staging`, workers on, 24 h soak** | 2 | **L** | F8 |
| F8 | Production cutover | 3 | M, needs approval | — |
| F9 | Eval retention (D6) | — | S | — |

**Do F1.4 (D7) first, out of order if you like.** It is a config change, it is
deploy-blocking, and until it is done no deploy of `main` can succeed.

**Two increments have genuinely unknown size, for the same reason** — both run
suites that have never run:

- **F2**: 26 integration files, never run as a suite.
- **F7**: 13 `staging`-marked files, never run *at all* (their only trigger is a
  CI job that needs minutes that will never be bought).

Scope both from their first execution, not from reading. If either turns out to
be large, split it: land the tooling plus a passing subset first, then work the
remainder file by file. Do not let either become a branch that lives for a week.

**F2 is the one to watch.** Everything else is scoped from code that has been
read. F2 is scoped from code that has never been run as a suite, so its size is
genuinely unknown until step 2 of that increment completes. If it turns out to be
very large, split it: get `verify.sh` and a passing subset landed first, then
work the remainder file by file. Do not let F2 become a branch that lives for a
week.

## 6. How you will know this worked

Not "the tests pass" — the tests passed for every defect in §1. These:

1. Checking out `26154f3f~1`'s copy of `20260809000003` makes the suite go red.
   *(Today it stays green — that is the whole problem.)*
2. Removing a migration from the remote and running the schema gate exits 1.
3. `./scripts/verify.sh backend` opens a real Postgres connection — verifiable
   in `pg_stat_activity` while it runs.
4. **Unsetting `SUPABASE_DB_URL` on the staging Render service makes
   `./scripts/verify.sh staging` go red at the health check.** That is D7
   becoming detectable rather than latent.
5. **`LISTEN selko_work` is confirmed working through Supavisor on real
   infrastructure**, and the egress claim behind the whole direct-pg batch has a
   measured number attached to it instead of an estimate.
6. Production and `main` are within one increment of each other, and staging is
   never more than one increment behind `main`.
7. A new developer can clone, run one command, and see the system actually run.
