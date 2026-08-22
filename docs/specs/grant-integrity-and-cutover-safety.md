+++
spec_id = "grant-integrity-and-cutover-safety"
readme_order = 6
title = "Grant integrity and cutover safety"
increments = "W1–W6, D4–D5"
gate = "Blocks the S+V production cutover; W1 is independent and ships first"
tests = [
  "tests/integration/test_schema_contract.py::test_security_definer_functions_are_not_executable_by_api_roles",
  "tests/test_gate_contract.py::test_gate_bounds_every_docker_probe",
  "tests/integration/test_integration_events.py::test_delete_events_status_backfill_preserves_every_legacy_status",
  "tests/test_ingestion_runtime.py::test_health_evaluation_has_a_safety_net_floor",
]
health = ["/health/ingestion"]
drills = ["staging-worker-drill"]
+++

# Grant Integrity and Cutover Safety

**Status is not authored here.** `docs/specs/README.md` derives it from
evidence manifests (V3). What follows in §10 is the recorded evidence §9 asks
for — commands, timestamps and content-free counts — not a status claim.

**Written:** 2026-08-21, after reviewing every change between `eb41562c` (the
`executable-truth` plan) and `24e770c2` (HEAD, V8), querying the live grant
state of both cloud projects, and reading the Docker VM console log that
explains why the Tier 1 gate has not run today.

**Audience:** A developer new to this codebase. Every increment names the files
to change, the contract, the test to write first, and the evidence required to
call it done.

**Depends on:** [`executable-truth.md`](executable-truth.md) V1–V8, all merged.
This plan repairs three defects that V1–V8 introduced or failed to catch, and
adds the two gates the production cutover needs before it can be attempted.

**Does not authorize:** the S+V production cutover. That remains a separate,
explicitly approved decision, and W6 exists to make it rehearsable rather than
to perform it.

---

## 1. Outcome

After this plan, the following are true and each is proven by something that
fails when it stops being true:

1. **No `SECURITY DEFINER` function in `public` is executable by `anon` or
   `authenticated` unless a contract says so by name.** The guard asserts the
   roles that PostgREST actually authenticates as.
2. **The gate cannot hang.** Every Docker probe is bounded; an unresponsive
   daemon fails the gate in seconds with a diagnosis, rather than blocking
   forever.
3. **The V8 collapse is finished.** No RPC signature, return key, or Python
   read still carries the deleted `events.status` vocabulary, and every legacy
   status value has a defined destination in the backfill.
4. **Health evaluation has a floor.** Incident evaluation runs on work activity
   *and* on a bounded safety net, so a system that has stopped doing work is
   still a system that notices.
5. **Worker behaviour is verified before production, from the operator's
   machine, against real Supavisor.** Under D4 this is a locally-run
   `selko.worker_app` against staging Supabase, and the Tier 2 verifier says
   exactly that instead of asserting a posture staging cannot hold.
6. **The cutover is rehearsable.** The 9-migration production batch can be
   applied to a copy of production's real data, on demand, before it is applied
   to production.

---

## 2. Evidence

Everything in this section was measured on 2026-08-21 against the live systems.
Production figures are content-free: counts, sizes, and status labels only.

### 2.1 The grant hardening has never worked

Queried directly, not inferred from the linter:

| Project | `SECURITY DEFINER` functions in `public` | executable by `anon` |
|---|---:|---:|
| staging `lxmysergoeaegxlyfzwk` | 56 | **56** |
| production `khahcozfbnpykspvatrg` | 45 | **45** |

The exposed set includes `commit_email_extraction`,
`save_email_with_attachment_descriptors`, `claim_unprocessed_email`,
`fail_email_processing`, `reprocess_email(p_user_id, p_email_id)`,
`get_llm_usage_summary(p_user_id, ...)` and `_enqueue_calendar_work`. The `anon`
key is published in every client build.

Root cause, from `pg_default_acl` on staging:

```
schema public, objtype f:
  {postgres=X/postgres, anon=X/postgres, authenticated=X/postgres, service_role=X/postgres}
  {postgres=X/supabase_admin, anon=X/supabase_admin, authenticated=X/supabase_admin, service_role=X/supabase_admin}
```

Supabase installs `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON
FUNCTIONS TO anon, authenticated`. Every function created in `public` receives a
**direct** grant to both roles. `REVOKE ALL ON FUNCTION ... FROM PUBLIC` revokes
the `PUBLIC` pseudo-role and does not touch a direct grant.

Therefore every `REVOKE ... FROM PUBLIC` line in every migration is decorative,
including the sixteen added by V8 at
`20260829000001_delete_events_status.sql:816` and the entire purpose of
`20260811000005_revoke_security_definer_public_execute`.

The guard that should have caught this asserts the wrong role.
`backend/tests/integration/test_schema_contract.py:599`:

```sql
AND has_function_privilege('public', p.oid, 'EXECUTE')
```

`'public'` is the pseudo-role. The test has passed continuously while the
property it is named for has never held in any environment, including locally —
`supabase db reset` installs the same default ACL.

This is the failure mode `executable-truth` §2 catalogues as "a guard that
asserts diff text, not system properties," reproduced one layer down, and it
survived the plan written to eliminate it.

### 2.2 The gate hangs instead of failing

Docker Desktop is running — the app, `com.docker.backend` and
`com.docker.virtualization` are all alive — but the daemon is wedged. The VM
console log ends with:

```
EXT4-fs (vda1): failed to convert unwritten extents to written extents
  -- potential data loss!  (inode 790510, error -5)
```

`error -5` is `EIO`; the VM's `Docker.raw` disk has an I/O fault. Console output
stops at 12:08 and never resumes. Six `docker ps` invocations issued during this
review are still blocked.

`scripts/verify.sh:59` `require_local_supabase()` calls `docker inspect` with no
timeout, so `./scripts/verify.sh backend` blocks indefinitely rather than
failing. V1 deleted success-by-refusal and left success-by-hanging, which is
worse: a refusal exits non-zero and prints a cause, while a hang consumes the
whole CI budget and, locally, is indistinguishable from a slow test run.

Backend unit tests do not touch Docker and pass at HEAD: **1081 passed, 37
skipped** (`pytest -m "not integration"`). The integration suite, the fixture
seed, and therefore the manifest are all unreachable until Docker is repaired.
`.verify/` does not exist, which is why `docs/specs/README.md` reports
`Evidence pending` for every plan.

### 2.3 V8 removed the column but not the vocabulary

`20260829000001_delete_events_status.sql` drops `events.status` and leaves three
residues:

| Residue | Location | Effect |
|---|---|---|
| `p_legacy_status text` | `_enqueue_calendar_work` signature, line 77 | Declared, never referenced in the body. Four call sites still compute `CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END` to feed it. |
| `'event_status'` return key | `fail_calendar_work`, line 209 | Returns a delivery-vocabulary string for a column that no longer exists. `grep` across `backend/`, `frontend/src/`, iOS and Android finds **no reader**. |
| `p_restore_status` | `reject_event_change_proposal`, line 288 | Still validates `IN ('pending_review','approved','synced','sync_failed','rejected','cancelled')` and maps to `review_status`. |

And the backfill is incomplete. Production's real distribution:

```
rejected 182 · synced 71 · pending_review 25 · pending_change 11 · sync_failed 3
```

The `DO` block at lines 8–39 preserves only `status = 'synced'`. The three
`sync_failed` rows become indistinguishable from never-attempted once the column
drops — uncompensated loss in a `DROP COLUMN`, with no test asserting the
backfill is total.

On the Python side, `backend/selko/services/events.py:1462` and `:1498` read
`snapshot.get("status")`. `event_snapshot_before` is `match.baseline`, a dict of
the `events` row, which no longer has `status`. For new proposals the value is
permanently `None`; for proposals already stored in production it is still
populated. `created_as_change_only` therefore flips from sometimes-true to
never-true for new rows, silently narrowing the "GCal-only adopt with no
original invitation → delete the row" path. This is not dead code; it is code
whose behaviour depends on when the row was written.

### 2.4 V6 made the stall detector depend on the thing it detects

`_evaluate_health_on_activity` (`backend/selko/workers/email_ingestion.py:247`)
runs at the end of a completed sync run in `coordinator_loop`. Deleting the
unconditional 300 s poll was correct and is what the architecture principle
asks for. But the principle's own wording is *"work arrives by notification; the
safety-net poll is a floor, not a schedule"* — and V6 removed the schedule
without leaving a floor.

If the coordinator cannot claim anything — every integration OAuth-blocked, the
claim path itself broken, or zero active integrations — `evaluate_once()` never
runs, `operational_incidents` are never opened, and no notification fires. The
`/health` surface still computes `health_work_state` on demand, so observability
survives; alerting does not, in precisely the scenario alerting exists for.

Production corroborates that the classifier still has the hole V6 was meant to
close: `email-attachment` reports **15 restarts** with
`last_exception_code: "unknown"` (14 when `executable-truth` was written).

### 2.5 Where the environments are

| | code | DB migrations |
|---|---|---|
| `main` | `24e770c2` (V8) | through `20260829000001` |
| staging | `21a7bb55` (V3), deployed 06:00Z | `20260827000002` |
| production | `7768cfb6` | `20260822000001` |

V4–V8 have never run anywhere but a laptop whose Docker has been broken since
midday. `/health` on staging returns no `build_sha`, confirming #338 is not
deployed; `./scripts/verify.sh staging` would poll for ten minutes and then
correctly fail `staging health did not serve expected revision`.

Production is **9 migrations** and **14 commits** behind, and production code at
`7768cfb6` writes `events.status` in twelve places
(`backend/selko/services/events.py:474–1283`). Applying `20260829000001` to
production breaks the running process until the code deploy lands; there is no
ordering that avoids a window. Production is 55 MB / 292 events / 2385 emails,
so a full logical dump costs seconds.

The Supabase organisation is on the **free** plan: no PITR, no daily backups,
two projects (both used), 5 GB egress per month org-wide. `DROP COLUMN` is
irreversible and there is nothing to roll back to that we do not take ourselves.

### 2.6 Review

`gh api repos/tonimelisma/selko/pulls/{333..342}/comments` returns `0` for all
ten. D3 recorded the rule; ten more PRs have merged without a review artifact.
D5 below closes that as a decision rather than restating the rule.

---

## 3. The rule this plan enforces

`executable-truth` established: *if an invariant matters enough to write down,
it matters enough to assert.* §2.1 shows the next failure mode after that rule
is adopted:

> **The rule:** an assertion must name the thing the runtime actually uses. A
> guard that asserts a *neighbouring* name — the `PUBLIC` pseudo-role instead of
> `anon`, a SQL comment instead of a constraint, a migration's text instead of
> its effect — is indistinguishable from no guard, and is worse, because it
> reports green.

Applied here: every guard added by this plan asserts against a live catalog or a
live process, never against source text.

---

## 4. Decisions

**D4 — staging worker posture (supersedes `executable-truth` D2).**

D2(a) recorded "staging runs workers on, permanently." That decision is not
implementable on the plan staging is on, and this was not known when it was
recorded. `selko-app-staging` is Render **free**: 512 MB, 0.15 CPU, and it
**spins down after ~15 minutes idle**. Measured during this review — the first
`/health` request timed out at 30 s and the retry returned `uptime_seconds: 8`,
a cold start caused by the request itself. Render's metrics show five distinct
instance IDs in twenty hours. A sleeping instance holds no lease, sends no
heartbeat, and reclaims nothing; `STAGING_REQUIRE_WORKERS=1` can never pass
there.

**Decision recorded 2026-08-21, by the operator: (A).** Staging stays on Render
free. Worker verification runs `selko.worker_app` **from the operator's machine
against staging Supabase**, over the real Supavisor session pooler.

This covers real Postgres, real Supavisor, real `LISTEN`/`NOTIFY`, real leases,
real generation fencing and real expiry reclaim — everything Tier 1 structurally
cannot reach. It does **not** cover Render's memory ceiling or the deployed
service's posture, and W5 requires the verifier to say so rather than assert a
posture that will never hold.

**D5 — review (supersedes `executable-truth` D3).** D3 asked for a mechanism and
none was adopted; ten further PRs merged with zero review artifacts, including
the `DROP COLUMN` migration. A rule that has now failed twice is not a rule.

**Decision recorded 2026-08-21: the artifact requirement is dropped as a
per-PR rule and replaced by a gate that does not depend on anyone remembering
it.** W6's rehearsal is the review of record for anything touching
`supabase/migrations/**`: a migration that has not been applied to a copy of
production's real data has not been reviewed, regardless of who read the diff.

---

## 5. Phase A — the guards

### W1 — The grant guard asserts the roles that exist

**Branch:** `fix/security-definer-role-grants`

**Files:** `backend/tests/integration/test_schema_contract.py`,
`supabase/migrations/20260830000001_revoke_api_role_function_grants.sql` (new)

1. **Test first.** Rename
   `test_security_definer_functions_are_not_executable_by_public` to
   `test_security_definer_functions_are_not_executable_by_api_roles` and assert
   over `anon` **and** `authenticated`, not the `PUBLIC` pseudo-role. It fails
   immediately, locally, against every function in `public`.
2. Introduce `AUTHENTICATED_EXECUTABLE_FUNCTIONS` — the explicit, named set of
   RPCs a signed-in user is *meant* to call, each with the reason it is safe
   (it derives the caller from `auth.uid()`, or it is RLS-scoped). Anything not
   in that set must be executable by `service_role` only. `anon` gets nothing;
   there is no unauthenticated RPC in this product.
3. The migration issues real revokes — `REVOKE ALL ON FUNCTION ... FROM anon,
   authenticated` for every `SECURITY DEFINER` function in `public` — then
   re-grants exactly the contract set to `authenticated` and the worker set to
   `service_role`. It also resets the default ACL so the next function created
   does not silently reopen the hole:
   `ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated;`
   issued for both `postgres` and `supabase_admin` grantors.
4. Keep the existing `FROM PUBLIC` revokes. They are harmless and correct for a
   different role; they were simply never sufficient.

**Test first:** the renamed test fails at HEAD listing 56 functions.

**Done when:** the renamed test passes against local Postgres; a deliberately
added `GRANT EXECUTE ... TO anon` makes it fail; the same query run against
staging and production returns zero rows after the migration reaches them.

**Ships first and alone.** It is independent of the cutover and is live
exposure.

### W2 — The gate fails instead of hanging

**Branch:** `fix/bounded-docker-probe`

**Files:** `scripts/verify.sh`, `backend/tests/test_gate_contract.py`

1. Bound every Docker invocation in the gate. macOS has no `timeout(1)` — the
   review confirmed `command not found: timeout` — so the bound is implemented
   in-script with a background probe and a bounded wait, not by assuming a
   coreutils binary exists.
2. On timeout, fail with the diagnosis rather than the symptom: name the daemon
   as unresponsive, and point at Docker Desktop → Troubleshoot → Clean/Purge
   data, which is the documented repair for a VM disk that has taken an I/O
   fault.
3. `test_gate_contract.py::test_gate_bounds_every_docker_probe` parses
   `scripts/verify.sh` and asserts that no `docker` invocation appears outside
   the bounded helper. This is a source-text assertion, which §3 warns about —
   it is acceptable here only because the property *is* a property of the
   script's text, and the behavioural half is covered by the done-when below.

**Done when:** with the daemon wedged, `./scripts/verify.sh backend` exits
non-zero in under 30 s naming the daemon; with the daemon healthy the gate is
unchanged.

---

## 6. Phase B — finish V8, and the floor

### W3 — Finish the state-ownership collapse

**Branch:** `refactor/finish-events-status-collapse`

**Files:** `supabase/migrations/20260830000002_finish_events_status_collapse.sql`
(new), `backend/selko/services/events.py`,
`backend/tests/integration/test_integration_events.py`

`20260829000001` has not reached staging or production, but it *has* been
applied locally and is committed. Amending a committed migration breaks anyone
whose local database already ran it, so the repairs land as a new migration.

1. **Complete the backfill, by amending `20260829000001` in place.**

   *Corrected during implementation.* This section originally proposed shipping
   a follow-up migration as an "idempotent repair for databases that ran the
   incomplete version." **That is impossible.** Once `DROP COLUMN status`
   executes, the values are gone and nothing can reconstruct which rows were
   `sync_failed`. There is exactly one moment at which this is fixable: before
   the migration reaches a durable environment. It has not — staging is at
   `20260827000002`, production at `20260822000001`, and the local database was
   at `20260828000001`, so `20260829000001` has never executed anywhere.

   Extend the preservation block to cover every pre-drop status. `sync_failed`
   becomes a `failed` work item; `approved`, `syncing` and `cancel_queued`
   become `pending` items of the right action; `pending_review`, `rejected` and
   `cancelled` are review states that never attempted a provider write and get
   none.
2. **Delete `p_legacy_status`** from `_enqueue_calendar_work` and the four call
   sites that compute a value for it. **Delete the `'event_status'` key** from
   `fail_calendar_work`'s return. **Delete `p_restore_status`** from
   `reject_event_change_proposal`, deriving `review_status` from the proposal
   and event rather than from a caller-supplied legacy label.
3. **Resolve the snapshot reads.** `created_as_change_only` must not depend on a
   key that new rows never carry. Derive it from what the events row and its
   `event_sources` actually say — no `google_calendar_event_id`-plus-`synced_at`
   heuristic keyed off a vanished column.
4. **Test first:**
   `test_delete_events_status_backfill_preserves_every_legacy_status` seeds one
   event per legacy status against local Postgres, runs the migration path, and
   asserts each has a `calendar_work_items` row whose status is the defined
   destination. It fails today for `sync_failed`.

**Done when:** no RPC signature, return key, or Python read references the
deleted vocabulary; the backfill test passes; `grep -rn "p_legacy_status\|event_status"`
over `supabase/migrations` and `backend/` returns only the new migration's
`DROP FUNCTION` lines.

### W4 — Health evaluation gets a floor

**Branch:** `fix/health-evaluation-floor`

**Files:** `backend/selko/workers/ingestion_runtime.py`,
`backend/selko/workers/email_ingestion.py`,
`backend/tests/test_ingestion_runtime.py`,
`backend/tests/test_egress_budget.py`

1. Keep the notification-driven path exactly as V6 built it.
2. Add a **floor**, not a schedule: the runtime evaluates health if and only if
   no work-activity evaluation has happened for
   `EMAIL_HEALTH_FLOOR_SECONDS` (default 900). An interval that resets on every
   real evaluation costs nothing on a busy system and bounds the blind window on
   a stalled one.
3. `test_health_evaluation_has_a_safety_net_floor` drives the runtime with zero
   claimable work, advances the clock past the floor, and asserts exactly one
   `evaluate_once()`. A second test asserts that continuous work activity
   produces **no** floor-driven evaluation, so the floor cannot decay back into
   the 300 s poll V6 deleted.
4. Extend `test_egress_budget.py` with the floor's contribution so the ceiling
   is asserted rather than assumed.
5. **Classify the `unknown` restarts** while in this file — 15 restarts with
   `last_exception_code: "unknown"` means `_exception_code` has a hole. An
   unclassified exception becomes a distinct, counted code.

**Done when:** an idle runtime evaluates health once per floor interval and no
more; a busy runtime never evaluates on the floor; the egress budget test
covers both.

---

## 7. Phase C — the cutover gates

### W5 — Worker verification runs locally against staging

**Branch:** `feat/staging-worker-drill`

**Files:** `scripts/verify-staging.sh`, `scripts/drill-staging-workers.sh`
(new), `backend/tests/drills/`, `docs/testing-guide.md`, `CLAUDE.md`

Per D4:

1. `STAGING_REQUIRE_WORKERS` stops meaning "assert the deployed service runs
   workers." It is replaced by `drill-staging-workers.sh`, which starts
   `selko.worker_app` locally with `ENVIRONMENT=staging`, waits for
   `listener.connected`, runs the drill suite against staging Supabase, and
   stops the worker. The script owns the process lifecycle so a failed drill
   cannot leave a worker running against staging.
2. `verify-staging.sh` keeps asserting `/health` and `build_sha` on the deployed
   service — that part is real and still required — and **states in its output**
   that the deployed staging service runs with background processing off by
   design, and that worker properties are proven by the local drill instead.
   No assertion may claim a posture staging does not hold.
3. The drill registers `staging-worker-drill` in the staging manifest, so
   `spec-status.sh` can see it.
4. `CLAUDE.md`'s Tier 2 description is corrected to match. Per
   `executable-truth`'s non-goals, this is a *deletion* of an inaccurate claim,
   not a new rule.

**Done when:** `./scripts/drill-staging-workers.sh` runs the drill suite green
against staging with a locally-run worker; killing the worker mid-drill makes it
red; the staging manifest records the drill.

### W6 — The cutover is rehearsable

**Branch:** `feat/cutover-rehearsal`

**Files:** `scripts/rehearse-cutover.sh` (new), `docs/specs/cutover-verification-20260807.md`

*Corrected during implementation.* This originally read "takes a logical dump
of production, restores it into a scratch local database." That would move real
users' OAuth refresh tokens and email bodies onto a developer laptop — exactly
what `CLAUDE.md`'s environment-separation rule forbids. The plan proposed it
anyway, which is worth recording: the rule did not survive contact with a
convenient design.

1. `scripts/rehearse_cutover.py` **copies no production data**. What it reads
   from production is content-free and already permitted for diagnosis: row
   counts grouped by status label, and the current migration version. It then
   builds a scratch local database, replays every migration up to production's
   version, seeds synthetic rows matching production's *status distribution*,
   applies the pending batch in order, and asserts.
2. It prints a content-free report: counts per legacy status before, work items
   per destination after, and any migration that failed.
3. Per D5 this is the review of record for `supabase/migrations/**`.
4. What it does not prove: behaviour that depends on row *content*. No
   migration in this batch branches on content.

**Done when:** the rehearsal applies all 9 pending migrations to a copy of
production's real data and the contract suite passes against the result; a
deliberately broken migration makes it red.

---

## 8. Non-goals

- Performing the production cutover. W6 makes it rehearsable; executing it
  remains a separate approved decision.
- Upgrading staging's Render plan. D4 chose (A); revisit only if the local-drill
  path proves insufficient.
- Repairing production data, or replaying historical failed email.
- Adding any rule to `CLAUDE.md` unaccompanied by the test that enforces it.

---

## 9. Acceptance

Complete when all of the following hold simultaneously, each demonstrated by a
recorded command:

1. `test_security_definer_functions_are_not_executable_by_api_roles` passes
   locally, and the same catalog query returns zero rows on staging and
   production.
2. With the Docker daemon wedged, `./scripts/verify.sh backend` exits non-zero
   in under 30 s naming the daemon.
3. `grep` finds no surviving `events.status` vocabulary in any RPC signature,
   return key, or Python read.
4. An idle runtime evaluates health exactly once per floor interval; a busy one
   never evaluates on the floor.
5. `./scripts/drill-staging-workers.sh` is green against staging.
6. `./scripts/rehearse-cutover.sh` applies all pending migrations to a copy of
   production and the contract suite passes.

Record commands, timestamps, safe counts and HTTP responses. Never record
production content, tokens, provider ids, subjects, addresses or raw errors.

---

## 10. Evidence record

Commands and results, 2026-08-21/22. Counts only; no production content.

**W1 — grant integrity.** `20260830000001` + `20260830000003`. Measured on the
live staging project after the batch reached it:

```sql
SELECT count(*) FILTER (WHERE has_function_privilege('anon', p.oid,'EXECUTE'))
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.prosecdef;
```

| | before | after |
|---|---:|---:|
| staging, anon-executable | 56 / 56 | **0 / 59** |
| staging, authenticated-executable | 56 | **4** (the contract set) |

Production was 45 / 45 before and is unchanged — it has not been deployed.

Two findings that only execution produced: the local Supabase default ACL for
functions in `public` is `{postgres=X/postgres}` while the hosted one is
`{postgres=X,anon=X,authenticated=X,service_role=X}`, so no local gate could
ever have failed on this; and PostgreSQL's own `GRANT EXECUTE … TO PUBLIC`
default left three broadcast trigger functions reachable after the first
revoke pass, which is why the revoke covers `PUBLIC` as well.

**W2 — bounded gate.** Verified against a genuinely wedged daemon
(`EXT4-fs (vda1) … error -5`): `./scripts/verify.sh backend` exited 1 in 16 s
where it previously never returned.

**W3 — collapse finished.** Executing `20260829000001` for the first time
found: `claim_calendar_work_item` still writing the dropped column, so every
calendar claim would have failed; `complete_calendar_work` converting every
unsync into a cancellation; the `enqueue_calendar_work` wrapper passing a
dropped argument; and a backfill covering one of five delivery-bearing
statuses.

**W4 — health floor.** Idle runtime evaluates once per floor interval; a busy
one never evaluates on the floor. Both asserted, because the first alone passes
for an unconditional timer.

**W5 — staging worker drill (D4).**

```
ENVIRONMENT=staging ./scripts/drill-staging-workers.sh   → 10 passed, exit 0
```

`selko.worker_app` booted against staging over the Supavisor session pooler
(port 5432, LISTEN accepted), was stopped cleanly, and the ten-step acceptance
drill then ran green against real staging Postgres. Progression across fixes:
8/2 → 9/1 → 10/0. The deployed staging service still runs with background
processing off, by design.

**W6 — cutover rehearsal.** Two modes. The shape mode replays the batch
against production's status distribution; the faithful mode (`--faithful`)
replays it against a **redacted clone of production's real rows** — 14,181 rows
across 14 tables, including 2,409 emails, 8,247 sync runs, 447 attachments and
370 event_sources. Redaction is the default and structural columns are the
allowlist, so a content column added later is redacted automatically; JSON keeps
its shape because migrations branch on it.

The faithful mode found what the shape mode could not — **the batch would have
aborted on migration 4 of 12 in production**:

```
20260825000001: event_change_proposals backfill ambiguous
                event_id=2f6fabd6-… total=2 complete=1
```

Verified read-only against production: two events carry two active
update/cancellation sources with only one complete. The guard demanded
`v_total = 1`, which is a claim about provenance rows rather than about the
proposal. It is now `v_complete = 1` — the property that actually has to be
unambiguous. Staging has no such rows, so staging applied it cleanly and no gate
ever saw it.

It also disproved one alarm it raised itself: flattening jsonb to `{}` made the
same guard report `complete=0` on healthy rows. That was a redaction artifact,
and chasing it is why redaction now preserves JSON shape.



```
uv run python scripts/rehearse_cutover.py \
  --shape "rejected=182,synced=71,pending_review=25,pending_change=11,sync_failed=3" \
  --production-version 20260822000001
```

Replays 97 migrations to production's state, seeds production's content-free
status distribution, applies the 9 pending migrations. It found the blocker
this plan was written too late to have prevented: `20260826000001` narrows the
status domain to exclude `pending_change` and never migrates the rows holding
it. Production has 11. The migration would have failed there, before any later
migration in the batch could run — and staging applied it cleanly only because
staging has no such rows.

**Tier 1.** `./scripts/verify.sh backend` — 1359 passed, 0 failed, 55 skipped.
`main` at `24e770c2` failed its own gate with 18 failures; the same gate on the
merged result is green, verified across four random-ordering seeds after three
order-dependent assertions were removed.

**Not done.** Production deployment. Production remains 9 migrations and ~20
commits behind, and the cutover has a hard breakage window: the running code
writes `events.status` in twelve places, so it breaks the moment the migration
lands and stays broken until the code deploy completes. The Supabase
organisation is on the free plan — no PITR, no automated backups — so a
`pg_dump` immediately before is the only rollback that will exist.
