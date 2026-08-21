+++
spec_id = "executable-truth"
readme_order = 5
title = "Executable truth"
increments = "V1–V8, D1–D3"
gate = "Gates plan 4's outstanding evidence — start before any further S-plan claim"
tests = [
  "tests/test_spec_status.py::test_generated_status_table_is_current",
  "tests/test_spec_status.py::test_hand_editing_a_status_cell_fails",
]
health = ["/health", "/health/egress"]
drills = ["executable-truth-acceptance-drill"]
+++

# Executable Truth

**Status:** Planned. Nothing implemented. No increment below has started.

**Written:** 2026-08-21, after reviewing every change between `12fafa8c`
(the last plan committed to the repo) and `890f12d4` (HEAD), running all four
local gates, and reading the live staging and production health surfaces.

**Audience:** A developer new to this codebase. Every increment names the files
to change, the contract, the test to write first, and the evidence required to
call it done. If implementation reveals an undecided transition, stop and amend
this plan; do not invent a compatibility path in code.

**Depends on:** [`state-ownership-and-deterministic-recovery.md`](state-ownership-and-deterministic-recovery.md)
S1–S5, which are merged. This plan finishes what S5 left half-done and repairs
the gates that let S1–S5 merge unexecuted.

**Does not authorize:** a production deploy, a production data repair, or a
replay of historical failed email. Production currently runs `7768cfb6`
(deployed 2026-08-14T03:28Z) and has **none** of S1–S5. Deploying that batch is
a separate, explicitly approved decision that comes *after* this plan.

---

## 1. Outcome

After this plan, the following are true and each is proven by something that
fails when it stops being true:

1. **No gate can report success without evidence.** A gate either passes, fails,
   or refuses and exits non-zero. "Continue with reduced coverage" is never a
   default; it is an explicit, recorded operator decision.
2. **A plan's status is derived, not authored.** `docs/specs/README.md` status
   cells are generated from evidence manifests. A human cannot type
   "verification passed" into a spec.
3. **Staging runs the code production runs**, identifies the revision it is
   serving, and is asserted after the deploy reaches live — not after the
   webhook returns 202.
4. **Every invariant worth writing down is executed.** The ten-step acceptance
   drill is a test suite, not prose. No script prints `PASSED` on a path it did
   not run.
5. **Every outbound byte is attributed to a caller.** No destination reports
   `operation="unknown"`. Any unconditional periodic database call is either
   deleted or justified in a file that a test reads.
6. **Fencing is a type, not a branch.** It is not possible to write a call that
   completes calendar work without an owner and a generation.
7. **Event state has one owner.** `events.status` no longer carries delivery
   vocabulary in parallel with `calendar_work_items.status`.

---

## 2. Evidence

Everything in this section was measured on 2026-08-21, not inferred. Production
figures are content-free: counts, byte totals, rates, timestamps, and status
labels only. No subjects, addresses, tokens, provider ids, or bodies.

### 2.1 How the S1–S5 batch actually shipped

| Finding | Evidence |
|---|---|
| The local real-Postgres gate refused for the whole batch | `verify.sh` gated on `supabase status -o json` exiting 0. That output is TTY-sensitive and returns non-zero in a redirected shell when optional services are stopped, so the gate printed "Local Supabase is not running" and exited 1 while Postgres was healthy. Repaired in #334 by probing `docker inspect` container health. |
| Two runtime SQL defects merged behind that refusal | `20260823000002_fix_health_work_state_ambiguous_status.sql` (ambiguous `status`) and `20260827000002_fix_durable_claim_output_shadowing.sql` (`RETURNS TABLE` OUT-parameter shadowing in `claim_due_email_sync` and `claim_due_email_reconciliation`). Both apply cleanly, pass every mocked test, and fail on first real call. The second is a repeat of a failure mode already recorded in the project's own notes. |
| Zero review | `gh api repos/tonimelisma/selko/pulls/{327,329,330,331,332,333,334}/comments` returns `0` for all seven. No bot, no reviewer, no ultrareview. |
| The staging health gate went red, and the docs said it passed | Run `32357060237`, 2026-08-20T10:04:28Z: `ERROR: staging API health status is not ok`. `00ed562e docs: reconcile remaining plan statuses` was committed at 10:22Z asserting staging verification passed. |
| The screenshot fixture path is dead | `scripts/seed_screenshot_data.py:269` sets `review_status` on exactly one of ~13 event dicts. PostgREST builds one column list for a bulk insert, so every row omitting the key sends explicit `NULL`, and S5's `NOT NULL` rejects the batch. `./scripts/capture-all-screenshots.sh` therefore cannot run on any platform. This is why no screenshots have been refreshed since 2026-08-13 despite #331/#332 changing UI on web, iOS, and Android. |
| Three iOS UI tests fail for the same reason | `ScreenshotCaptureTests` (light + dark) and `SettingsUITests.testSettingsShowsConnectedAccountsSection` fail at login because `screenshots@selko.local` does not exist. `verify.sh backend` runs `supabase db reset` and re-seeds only `TEST_USER_EMAIL`, so running the backend gate destroys the fixtures the UI gates need. `iOSTests.xctest` (unit) passes. |
| The durability drill proves nothing and prints `PASSED` | `backend/tests/integration/test_integration_ingestion_drill.py:144` skips with *"Use scripts/drill-lease-recovery.sh for the live kill-mid-pass drill"*. `scripts/drill-lease-recovery.sh` runs that same test with `|| true` and then unconditionally echoes `Drill 9a PASSED`. The test skipped in the 2026-08-21 gate run. The delegation is circular; nothing executes. |
| The S5 guard test asserts diff text, not system properties | `backend/tests/test_state_ownership_s5.py` asserts substrings of a migration file, including the SQL **comment** `"Preserve those rows as terminal work"` and whitespace-sensitive `"status IN (\n    'pending_review', 'approved'"`. It passes whether or not the system holds the property. |

Current gate state, run 2026-08-21 against HEAD:

| Gate | Result |
|---|---|
| `./scripts/verify.sh backend` | pass — unit green; integration **259 passed, 21 skipped**, seed 10741 |
| `./scripts/verify.sh frontend` | pass |
| `./gradlew testDebugUnitTest` | pass |
| `xcodebuild test -scheme iOS` | `iOSTests` pass, `iOSUITests` **3 of 21 fail** (fixture cause above) |

The backend gate is genuinely green now that #334 repaired the detection. The
21 skips are unbudgeted: nobody has declared which of them are acceptable.

### 2.2 What the environments are actually doing

**Staging** (`https://selko.onrender.com`, checked 2026-08-21):

```
/health           → {"status":"ok", ...}
/health/ingestion → {"background_processing_enabled": false, "tasks": [], "listener": null}
/health/egress    → {"transport": "none"}
./scripts/assert-staging-health.sh ingestion  → exit 1
```

Staging runs with background processing **off**. Every durable-worker property
S1–S5 exists to deliver — leases, expiry reclaim, generation fencing,
worker-owned calendar delivery — has never executed on staging. The green
`Integration Tests (Staging)` job on the #334 push is real but narrower than it
reads: it runs pytest against staging *Supabase*, proving the SQL works on real
Postgres. It never touches the deployed service. `deploy-staging` fires the
Render deploy hook and exits — no wait, no health assertion, and the service
publishes no revision identifier, so no assertion could prove which build
answered anyway.

**Production** (`https://api.selkoapp.com`, service `srv-d5snitkoud1c73adbkl0`,
build `7768cfb6`, up 607,511 s ≈ 7.03 days, checked 2026-08-21):

Workers are on and healthy — `background_processing_enabled: true`, all four
tasks alive, `listener.connected: true`, `transport: asyncpg`. Note that the
repo's `.env.production` says `ENABLE_BACKGROUND_PROCESSING=false`; the Render
service environment is authoritative and disagrees. That divergence is itself a
finding: the checked-in env files do not describe the deployed environments.

Egress over those 7.03 days: **220,947,100 bytes**, projected **942 MB/30 d**,
`bytes_per_mailbox_per_day: 4,522,275`.

| destination | operation | calls | calls/min | bytes |
|---|---|---:|---:|---:|
| graph | **unknown** | 14,527 | 1.43 | 147,083,786 |
| supabase | `GET /rest/v1/integrations` | 6,206 | 0.61 | 10,797,947 |
| supabase | `GET /rest/v1/email_sync_state` | 5,940 | 0.59 | 10,604,040 |
| supabase | `GET /rest/v1/email_folders` | 4,248 | 0.42 | 7,454,353 |
| supabase | `GET /rest/v1/attachments` | 2,240 | 0.22 | 3,802,449 |
| supabase | `GET /rest/v1/operational_incidents` | 2,026 | 0.20 | — |
| supabase | `GET /rest/v1/email_ingestion_items` | 2,019 | 0.20 | 3,398,011 |

Three things follow, each verified in code:

1. **67% of all production egress is unattributed.** `backend/selko/services/msgraph.py:112`
   declares `operation: str = "unknown"` as a default parameter. Its only caller,
   `backend/selko/services/outlook.py:224`, passes neither `operation` nor
   `client`, `config`, `integration_id`, or `run_id`. The comment above
   `record_egress` — *"`operation` is already a bounded template"* — is false at
   the only call site. The stated purpose of the egress module, per `CLAUDE.md`,
   is that a bandwidth total with no attribution cannot distinguish constant
   polling from real provider downloads. For the largest destination, it does not.

2. **The Microsoft Graph failure ledger is dead.** `record_graph_failure`
   (`msgraph.py:72`) begins `if client is None: return`. The single caller never
   passes `client`, so `graph_api_failures` is never written. There is no other
   writer and no reader anywhere in `backend/`, `cli/`, or the frontend. The
   table has a schema-contract entry and a dedicated document
   (`docs/microsoft-graph-failure-ledger.md`) referenced from `CLAUDE.md` as
   required reading "after any production Graph failure" — recording nothing.

3. **An unconditional idle loop is running.** `EmailSyncHealthEvaluator.run()`
   (`backend/selko/services/email_sync_health.py:293`) loops every
   `email_health_interval_seconds` (default 300) and calls `evaluate_once()`
   regardless of whether anything changed. Each cycle issues at least four
   PostgREST queries over the service role, including
   `client.table("email_sync_state").select("*")` — a full-table scan — plus
   dead-letter scans of `email_ingestion_items` and `attachments` and a read of
   `operational_incidents`. 607,511 s / 300 s = **2,025 cycles**, which matches
   the observed `operational_incidents` (2,026) and `email_ingestion_items`
   (2,019) counts. Throughout, `integrations_due: 0`, `items_pending: 0`,
   `leases_held: 0` — there was no work. Measured envelope cost is
   10,797,947 / 6,206 = **1,740 B/call**, matching the ~1,690 B figure `CLAUDE.md`
   cites as the reason worker coordination must not use PostgREST. This module
   was **not** touched by S1–S5 and is unchanged at HEAD.

   The exact caller mix behind the `integrations` and `email_sync_state` rates
   is not yet fully attributed; V6 attributes every remaining periodic call to a
   named caller before deciding what to delete. Do not guess it now.

4. **A production task is crash-looping unclassified.** `/health/ingestion`
   reports the `email-attachment` task with `restarts: 14` and
   `last_exception_code: "unknown"` over 7 days. The other three tasks report 0.

### 2.3 Defects that survived the increments meant to remove them

| Defect | Location | Why it survived |
|---|---|---|
| Unfenced calendar completion paths | `backend/selko/workers/pool.py:537` computes `fenced_claim = "calendar_work_item_generation" in event`, then branches. `claim_approved_event_for_sync` (`services/events.py:1745`) **always** sets that key and `pool.py` is the only caller of the four completion helpers, so every `else` branch is dead. | The rule against dual implementations is enforced by `test_workers.py` guards that look for PostgREST fallbacks, not for this shape. |
| An unfenced resolver | `_resolve_calendar_work_item` (`services/events.py:1801`) resolves a `processing` item **without checking `locked_by`** when `worker_id`/`generation` are `None`. | Unreachable today, but it is live API surface: any future caller omitting the fence can complete another worker's in-flight item. |
| A compatibility field S5 forbade | `services/events.py` sets `event["calendar_work_generation"]` with the comment *"Keep the legacy event-view field available to older worker callers"*. There are no older callers. | §11 of the S-plan lists "keeping compatibility fields after S5" as a global non-goal. |
| Dead RPC parameters and a dead SQL branch | `undo_event_and_enqueue_calendar_work` takes `p_change_source_id` and `p_restore_fields`; the single caller (`services/events.py:1596`) always passes `NULL` and `{}`, and the function still branches on `IF p_change_source_id IS NOT NULL`. | #333 was specifically "remove dead calendar attempt arguments" and did not reach these. |
| Two parallel event state machines | `events.status` and `events.review_status` are both `NOT NULL`, both default `'pending_review'`. The post-S5 CHECK keeps the full delivery vocabulary on `status`: `'approved','cancel_queued','syncing','synced','sync_failed'`. The S5 RPCs hand-write both (`SET status = 'rejected', review_status = 'rejected'`; elsewhere `review_status` is derived from `v_fields->>'status'`). | S5 dropped the *columns* it listed and left the *column it was written to collapse*. |
| Live-update wiring with no server half | #331 added `event_change_proposals` and `calendar_work_items` to the realtime allowlist on all three clients, and both web pages subscribe to `calendar_work_items`. The database has broadcast triggers only on `events`, `event_sources`, `emails`, `integrations`. Nothing emits those two resources. | Not a break today, because work-item changes usually also touch `events` and fire that trigger incidentally — which is exactly the dependency V8 removes. |
| History pagination returns duplicates | `fetchActivityEvents` (`frontend/src/lib/services/events.js`) queries `review_status in ('active','rejected','cancelled')` with `count: 'exact'` and `.range()`, then drops Changes-lane rows **client-side**. `history/+page.svelte:174` advances `offset += result.data.length` using the post-filter length, so the next page re-fetches rows already shown and appends them without dedupe. `hasMore = events.length < totalCount` compares a filtered length against an unfiltered exact count. | No test exercises a second page containing a filtered row. |

---

## 3. The rule this plan enforces

Every failure in §2 is the same failure: **a claim that outran its evidence.**

The repository has responded to this class of failure before by writing more
rules. `CLAUDE.md` now narrates its own history of broken rules — "the call-site
rule above was stated three times and broken three times." That is conclusive
evidence that prose does not hold. This plan does not add a rule that asks
anyone to remember anything.

> **The rule:** if an invariant matters enough to write down, it matters enough
> to assert. If it is not worth asserting, delete the sentence.

Applied consistently this means: every paragraph of `CLAUDE.md` that narrates a
past incident becomes a test whose docstring carries the incident, and the
paragraph is deleted. `CLAUDE.md` shrinks to decisions and conventions;
enforcement lives in the suite. A short document that is entirely load-bearing
beats a long one that is skimmed.

---

## 4. Decisions required before implementation

These change the work materially. Each blocks exactly one increment. Do not
start the blocked increment until the decision is recorded here.

**D1 — `events.status` (blocks V8).** Two coherent end-states:

- **(a) Delete it.** `review_status` owns the decision, `calendar_work_items`
  owns delivery, clients render the delivery badge from the work item. This is
  what the S-plan committed to. Requires client changes on all three platforms
  and a migration that drops the column.
- **(b) Keep it as a declared projection.** Trigger-maintained, never
  hand-written by an RPC, with a schema-contract test asserting it always equals
  `f(review_status, latest calendar_work_items.status)`.

*Recommendation: (a).* Option (b) reintroduces a denormalization that must be
defended forever, and today's hand-written dual-write is precisely the
"two mutable sources of truth" shape that produced the orphaned Changes card
that started the S-plan.

**D2 — staging worker posture (blocks V4).** Staging currently runs workers off
on a free Render instance. Either:

- **(a)** Staging runs workers on, permanently, and Tier 2 means what
  `CLAUDE.md` says it means. If the free instance cannot hold that, this costs
  money and that is the price of having a staging tier.
- **(b)** Staging cannot run workers, and every Tier-2 claim in `CLAUDE.md` and
  in the specs is rewritten to say what staging actually proves (schema and RPC
  behaviour on real Postgres) and what it does not.

*Recommendation: (a).* Option (b) is honest but leaves the durable-worker
machinery with no pre-production execution anywhere.

**D3 — review (blocks V1's definition of done).** Seven PRs merged with zero
review artifacts. `/code-review ultra` exists but is user-triggered and billed,
so it cannot be made mechanical from inside the repo. The rule to adopt: **a PR
that touches `supabase/migrations/**` or any fencing path does not merge without
a review artifact linked in the PR body.** Confirm the mechanism you will
actually use, or this becomes another unenforceable sentence.

---

## 5. Phase A — gates that cannot lie

No Phase B increment may start before the Phase A increment it depends on has
merged. Fixing a Phase B defect before its gate exists reproduces the exact
failure this plan is about: a fix nobody can prove.

### V1 — The gate emits evidence and cannot succeed by refusal

**Branch:** `refactor/gate-evidence-manifest`

**Files:** `scripts/verify.sh`, `scripts/verify-staging.sh`,
`backend/tests/test_gate_contract.py` (new), `docs/testing-guide.md`

1. `verify.sh` writes a machine-readable manifest to
   `.verify/backend-<sha>.json` containing: git SHA, dirty-tree flag, local
   schema hash (`supabase migration list --local` digest), pytest seed, counts
   of passed/failed/skipped, and **every skipped node id with its reason**.
2. Introduce a **skip budget**: `backend/tests/skip_budget.toml` names each test
   permitted to skip and the precondition that permits it (no LLM key, no real
   Gmail token, no real Google Calendar). A skip outside the budget fails the
   gate. Today's 21 skips are triaged into the budget in this increment; any
   that cannot be justified are fixed or deleted, not budgeted.
3. **Delete every success-by-refusal path.** The current
   `SELKO_SKIP_REAL_GMAIL=1` branch prints `WARN: ... Gate continues.` and exits
   0. Replace it: the gate exits non-zero, and the operator opts in explicitly
   with `./scripts/verify.sh backend --accept-stale-gmail-token`, which is
   recorded in the manifest as an accepted degradation.
4. `test_gate_contract.py` asserts, by parsing `scripts/verify.sh`, that no
   command in the gate is followed by `|| true`, and that every `exit 0` is
   reachable only after the manifest is written.

**Test first:** a test that fails today because `verify.sh` contains a path that
exits 0 without running the integration suite.

**Done when:** a deliberately broken migration makes the gate exit non-zero; a
missing Gmail token makes the gate exit non-zero without the new flag; the
manifest exists and lists all 21 skips against the budget.

### V2 — Fixtures are gate-owned and built through the real write path

**Branch:** `fix/seed-through-rpcs`

**Files:** `scripts/seed_screenshot_data.py`, `scripts/verify.sh`,
`backend/tests/integration/test_integration_seed_fixtures.py` (new)

The seed script broke because it is 532 lines of literal payloads inserted
directly into eight tables — `integrations`, `email_folders`, `emails`,
`events`, `event_sources`, `event_change_proposals`, `calendar_work_items`,
`user_calendar_settings` — duplicating by hand every invariant the RPC layer
owns. It will drift again on the next schema change. Two changes:

1. **Build seed rows through the same RPCs the application uses**
   (`commit_email_extraction` and the proposal/work-item RPCs) rather than raw
   table inserts, per the architecture principle that an operation has exactly
   one implementation. Where a raw insert is genuinely required, construct rows
   from a single factory so every row carries every key — which also removes the
   PostgREST bulk-insert `NULL` trap permanently rather than patching one column.
2. **`verify.sh backend` seeds the screenshot fixtures as part of the reset and
   asserts the seed succeeds.** It takes seconds and makes a broken seed a red
   gate instead of a red UI suite three platforms away. It also leaves the
   database in the state the iOS and Android UI suites require, removing the
   trap where running the backend gate breaks the mobile gates.

**Test first:** `test_integration_seed_fixtures.py` runs the seed against local
Postgres and asserts the expected row counts per lane. It fails today.

**Done when:** the gate seeds successfully; `./scripts/capture-all-screenshots.sh`
runs on all three platforms; the three iOS UI tests pass.

### V3 — Spec status is derived, never authored

**Branch:** `feat/derived-spec-status`

**Files:** `scripts/spec-status.sh` (new), `docs/specs/README.md`,
`backend/tests/test_spec_status.py` (new), each spec's front matter

1. Each spec declares machine-checkable acceptance criteria in a front-matter
   block: test node ids, health assertions, drill names.
2. `scripts/spec-status.sh` reads the evidence manifests from V1/V4 and
   **generates** the status table in `docs/specs/README.md`.
3. `test_spec_status.py` fails if the committed table differs from the generated
   one.

This makes commits like `docs: reconcile plan statuses` impossible — there is
nothing left to reconcile by hand. It also retires the three status claims that
are currently wrong in `state-ownership-and-deterministic-recovery.md:9` and
`README.md` row 4: that the local real-Postgres gate is unavailable (it passes),
that staging verification passed (the health-asserting run failed), and the
implied completeness of a batch whose staging worker gate has never run.

**Done when:** editing a status cell by hand fails the suite.

### V4 — Staging is real *(blocked on D2)*

**Branch:** `feat/staging-release-identity`

**Files:** `backend/selko/api/routes/health.py`,
`backend/selko/api/schemas/common.py`, `.github/workflows/test.yml`,
`scripts/verify-staging.sh`, `backend/tests/drills/` (new)

1. **Release identity.** `/health` returns the git SHA the process was built
   from (Render exposes `RENDER_GIT_COMMIT`). You cannot verify a deployment you
   cannot identify; today no staging assertion can prove which build answered.
2. **The deploy waits for the revision it deployed.** After firing the deploy
   hook, poll `/health` until the reported SHA equals the pushed SHA, with a
   bounded timeout, then run the root, ingestion, and egress assertions. Today
   the workflow fires the hook, prints "builds will complete asynchronously,"
   and exits.

   **Where this lives matters.** `CLAUDE.md` is explicit that CI may never run
   and must never be a gate; both verification tiers run from the operator's
   machine. So the wait-and-assert logic is implemented **once**, in
   `scripts/verify-staging.sh`, and `deploy-staging` in `test.yml` *invokes that
   same script*. One implementation, two invocation sites — the same rule the
   architecture applies to everything else. Do not write the polling loop inline
   in the workflow; a gate that only exists in CI is a gate that does not exist.

   Observed for accuracy: CI did in fact run for this batch — `Unit Tests`,
   `Android Unit Tests`, `Deploy to Staging`, and `Integration Tests (Staging)`
   all executed. That does not change the policy; it means CI is currently a
   free second opinion, and the script must stay runnable without it.
3. **Workers on** (per D2(a)), so the ingestion assertion
   (`background_processing_enabled`, all tasks alive, `listener.connected`) and
   the egress assertion (`transport == "asyncpg"`) can pass at all. They fail
   today.
4. **Drills become code.** Port the ten steps of the S-plan's §12 acceptance
   drill into `backend/tests/drills/` behind a `drill` marker, each asserting
   its invariant against staging: kill after claim → lease expires → next
   generation reclaims without restart; old-generation completion is fenced;
   concurrent same-day updates yield one event and one proposal; supersede;
   apply queues exactly one upsert and only the worker writes; undo queues
   compensation with no provider write in the request; divergence blocks and
   forced override is recorded; discovery crash abandons the prior run; health
   degrades and recovers during each fault; the ten zero-count queries.
5. **Delete `scripts/drill-lease-recovery.sh`.** Replace it with the drill
   marker. Its `|| true` plus unconditional `Drill 9a PASSED` is the single
   clearest instance of the failure this plan exists to end, and the test it
   delegates to delegates straight back to it.

**Done when:** the drill suite runs green against staging; a deliberately
introduced fence violation makes it red; `assert-staging-health.sh ingestion`
exits 0.

---

## 6. Phase B — the truths the gates were hiding

### V5 — Attribute every outbound byte, and revive the Graph ledger

**Branch:** `fix/graph-egress-attribution`

**Files:** `backend/selko/services/msgraph.py`,
`backend/selko/services/outlook.py`, `backend/tests/test_egress.py`,
`backend/tests/integration/test_integration_graph_ledger.py` (new)

1. **Remove the `operation: str = "unknown"` default.** Make `operation` a
   required keyword argument of `request_json`. An unattributed Graph call then
   fails to construct rather than reporting `unknown` for 147 MB.
2. Pass a bounded operation template from every `outlook.py` call site, plus
   `client`, `config`, `integration_id`, and `run_id` — which is also what
   revives the ledger.
3. **Guard test:** assert that no `record_egress` call site can pass a
   non-literal or defaulted operation, and that `egress_snapshot()` never
   contains the string `unknown`.
4. **Integration test:** force a Graph failure against a stub and assert a row
   lands in `graph_api_failures` with the redacted template. This test fails
   today for every possible input, because `record_graph_failure` returns early
   on `client is None` at its only call site.

**Done when:** `/health/egress` on staging shows named Graph operations, and a
forced failure writes a ledger row.

### V6 — Delete the idle loop, attribute what remains

**Branch:** `refactor/notification-driven-health`

**Files:** `backend/selko/services/email_sync_health.py`,
`backend/selko/workers/ingestion_runtime.py`,
`backend/tests/test_egress_budget.py` (new)

1. **Attribute every periodic call to a named caller first.** V6 begins with
   measurement, not surgery: instrument each periodic caller so
   `/health/egress` can be read as "this many calls per cycle from this loop."
   The 300 s health evaluator is proven (2,025 cycles vs 2,026
   `operational_incidents` reads); the `integrations` and `email_sync_state`
   rates are not yet fully attributed and must not be guessed at.
2. **Then delete or justify.** `evaluate_once()` currently performs
   `select("*")` full scans and dead-letter sweeps on a fixed 300 s schedule
   with zero pending work. Per the architecture principle, work arrives by
   notification and the safety-net poll is a floor, not a schedule. Drive
   incident evaluation from the same notification path the workers use, and move
   whatever must remain periodic onto asyncpg, where a service-role call does
   not pay ~1,740 B of PostgREST envelope.
3. **An egress budget test.** Assert a ceiling on calls-per-idle-hour in the
   integration suite: start the runtime with no work, wait one interval, assert
   the call count. A new unconditional periodic call then fails the suite
   instead of requiring someone to justify it in a PR body nobody reads.
4. **Classify the `email-attachment` restarts.** 14 restarts in 7 days with
   `last_exception_code: "unknown"` means the classifier has a hole. An
   unclassified exception should be a distinct, counted code, not `unknown`.

**Done when:** an idle production-shaped runtime issues an asserted, bounded
number of database calls per hour, and no periodic caller is anonymous.

### V7 — Fencing becomes a type

**Branch:** `refactor/work-item-lease-type`

**Files:** `backend/selko/services/events.py`, `backend/selko/workers/pool.py`,
`backend/tests/test_workers.py`

Do not delete the dead `else` branches. Delete the *possibility* of them:

1. Introduce a `WorkItemLease` value object carrying `(item_id, worker_id,
   generation)`, returned by `claim_approved_event_for_sync` and accepted as the
   **only** completion argument by `complete_event_sync`,
   `complete_event_cancellation`, `fail_event_sync`, and
   `defer_event_sync_for_quota`. No optional `worker_id`/`generation`, no
   overloads.
2. `_resolve_calendar_work_item` loses its unfenced branch entirely; with a
   `WorkItemLease` there is no way to call it without an owner.
3. Remove `event["calendar_work_generation"]` and the "older worker callers"
   comment; remove `p_change_source_id` and `p_restore_fields` from
   `undo_event_and_enqueue_calendar_work` and the `IF p_change_source_id IS NOT
   NULL` branch they feed.
4. Replace the string-matching guards in `backend/tests/test_state_ownership_s5.py`
   with property assertions. A guard that asserts a SQL comment is present
   passes whether or not the system holds the property.

**Done when:** an unfenced completion call does not type-check, and the S5 guard
file contains no assertion about the text of a migration.

### V8 — Finish the state-ownership collapse *(blocked on D1)*

**Branch:** `refactor/single-event-state-owner`

**Files:** migration, `backend/selko/services/events.py`,
`frontend/src/lib/services/events.js`, `frontend/src/routes/app/history/+page.svelte`,
iOS `CalendarEvent.swift`, Android `CalendarEvent.kt`,
`supabase/migrations/` broadcast triggers

1. Per D1, either drop `events.status` and render delivery from
   `calendar_work_items`, or convert it to a declared trigger-maintained
   projection with a contract test. Either way, no RPC hand-writes both columns.
2. **Add broadcast triggers for `event_change_proposals` and
   `calendar_work_items`.** The clients have subscribed to both since #331 and
   nothing emits them; today that is masked by the incidental `events` update
   that D1(a) removes. Ship the server half in the same increment as the change
   that removes the accident.
3. **Fix History pagination at the source.** Exclude Changes-lane events in the
   query — a `not.in` on events with a pending proposal, or a view — so `count`
   and `range` describe the same set. Client-side filtering after a ranged
   query cannot be made correct. Add a test that loads two pages where the first
   contains a filtered row and asserts no duplicate ids.
4. Remove the dead legacy fallback `(!event?.review_status && event?.status ===
   'pending_review')` in `isNewReviewEvent`: `review_status` is `NOT NULL` and
   `EVENT_RELATIONS` selects `*`, so the branch is unreachable.
5. Reconsider the `calendar_work_items` embed in `EVENT_RELATIONS`. It pulls 18
   columns including the full `desired_event` JSON into every Review and History
   row, and nothing renders from it. Under D1(a) it becomes load-bearing; under
   D1(b) it should be trimmed to the columns actually displayed.
6. Update the stale docstring at `backend/selko/api/routes/events.py:363`, which
   still says undo "reverts Google Calendar" in the request.

**Done when:** one column owns the user's decision, one table owns delivery, a
second History page contains no duplicates, and every client subscription has a
server emitter.

---

## 7. Non-goals

- Deploying S1–S5 to production. That is a separate, approved decision after
  this plan; production is currently seven days and six migrations behind.
- Replaying historical failed email or repairing production data.
- Adding a second worker service or transport.
- Adding any rule to `CLAUDE.md` that is not accompanied by the test that
  enforces it. V1–V8 each *remove* prose in favour of an assertion.
- A generic periodic sweeper of any kind.

---

## 8. Acceptance

This plan is complete when all of the following hold simultaneously, and each is
demonstrated by a command whose output is recorded:

1. `./scripts/verify.sh backend` produces a manifest, and every skip in it is in
   the budget.
2. `./scripts/capture-all-screenshots.sh` completes on web, iOS, and Android,
   and all four gates are green including `iOSUITests`.
3. `docs/specs/README.md` is generated; editing a status cell by hand fails the
   suite.
4. `STAGING_REQUIRE_WORKERS=1 ./scripts/verify.sh staging` exits 0 against a
   staging service whose reported SHA equals the pushed SHA.
5. The §12 drill suite passes against staging, and a deliberately introduced
   fence violation makes it fail.
6. `/health/egress` on staging reports zero `unknown` operations, and an idle
   runtime stays under the asserted call budget.
7. An unfenced calendar completion does not type-check.
8. `events` has one state owner, and a second History page contains no
   duplicate ids.

Record commands, timestamps, safe counts, and HTTP responses. Never record
production content, tokens, provider ids, subjects, addresses, or raw errors.
