+++
spec_id = "cutover-verification-20260807"
readme_order = 8
title = "Cutover verification"
increments = "Ordered checklist"
gate = "Executed through F7–F8, never directly"
tests = []
health = ["/health", "/health/ingestion", "/health/egress"]
drills = ["production-cutover-rehearsal"]
+++

# Cutover Verification — Egress + Hardening Batch (Inc 10)

**Status is not authored here** — `docs/specs/README.md` derives it from
evidence manifests. The Local DoD figures below are a dated record of one
2026-08-07 run, kept for history; they are not a current claim.

**Production still runs `7768cfb6` with 12 migrations pending.** No prod
deploy until explicitly approved.

This is the operational checklist consolidated from the ingestion-hardening
(#241–#247), egress-scheduling and polling-v2 (#231–#235) cutover runbooks, all
of which are now shipped. **This file is the single ordered gate** before the
flag is ever flipped.

## What was built (locally verified, not yet in prod)

- **Egress 1-5 (arch A):** photo polls deleted, duplicate email claim removed,
  single scheduler + drain-then-sleep (WorkerPool 30s tick, Ingestion coordinator
  60s tick), in-process nudge for `POST /events/{id}/sync`, `apply-change`, and
  `request_email_sync_now`. Idle egress: 1.5M/day → ~3k/day (measured via
  `/health/egress` hook; envelope now irrelevant). Next tick catches missed nudge.
- **Hardening 7:** `withdrawn_count` for cancelled/rejected, grace for new
  integration first poll, resilient ConnectionRecovery poll, live-ui debt noted.
- **Hardening 8:** `__import__` hack removed, `get_gmail_credentials` rename,
  explicit grants migration, Outlook failure logging, reconciliation ledger, token init.
- **Hardening 9:** `backend/tests/drills/test_acceptance_drill.py` via `scripts/drill-staging-workers.sh`
  (gate + Outlook fixture).

Migrations added by that batch (the pending set has since grown to **12** —
run `supabase db push --dry-run` for the current list rather than trusting
a count written here):
- `20260807000001_fix_recovery_withdrawn_and_complete.sql` (withdrawn_count)
- `20260807000002_explicit_service_role_grants.sql` (explicit 11 grants)

As of 2026-08-22 production runs code `7768cfb6` against schema
`20260822000001`, with background processing ON in the Render service
environment (the checked-in `.env.production` says `false`; Render is
authoritative and they disagree). Do not flip flags via Render env alone.
Follow the ordered cutover below.

## Extraction decision intent — migration and code must land together

`20260831000001_extraction_decision_intent.sql` makes
`commit_email_extraction` require an explicit `intent` on every decision, and
`save_extracted_events` supplies one. **They are a matched pair**, and the
ordering rule below (migrations first, code second) is what makes the pair
safe: the new function refuses a decision the *old* code would send, so between
the migration and the code deploy, email extraction fails closed rather than
auto-applying. That is the intended failure direction — a stalled extraction is
recoverable, a silent write to a user's Google Calendar is not — but it does
mean the gap should be short, and `ENABLE_BACKGROUND_PROCESSING` should stay
off across it if the gap will not be short.

Production currently runs code `7768cfb6` (an ancestor of #332) against schema
`20260822000001`, so production has **never** run the defective combination:
its Changes lane still works. Staging, at `20260827000002`, is also pre-S3.
Nothing needs repairing in either environment — this batch must simply not ship
the defect.

## Ordered cutover (must be migrations first, code second, flag last)

Ordering constraint (migrations first, code second, flag last) carried from the
egress-scheduling and polling-v2 work:

1. **No CI minutes will ever be bought for test gating.** Local verification remains authoritative. The dependency-free production deployment job is the exception because it owns the secret Render hooks; wait only for that job, not unrelated test jobs.
2. **Staging token:** `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (checks both dev and staging, copies working → stale; if both stale, re-auth one side then re-sync). Do not ask to reauth when one side is working.
3. **Staging deploy (local, gated):** `./scripts/assert-schema-code-compat.sh && supabase link --project-ref lxmysergoeaegxlyfzwk && supabase db push` (dry-run then push). Render deploys on main push. `gh workflow run test.yml` to staging is a bonus only — never required.
4. **Staging drills:** `ENVIRONMENT=staging ./scripts/drill-staging-workers.sh` — starts `selko.worker_app` against staging over the Supavisor session pooler, drains it, then runs the ten-step acceptance drill. (`drill-lease-recovery.sh` is deleted: it ran its delegate with `|| true` and echoed `PASSED` regardless.)
4b. **Faithful cutover rehearsal (required, and re-run on the day):** `uv run python scripts/rehearse_cutover.py --production-url <read-only> --faithful`. Replays every pending migration against a redacted clone of production's real rows. Production data changes; a rehearsal from last week is evidence about last week.
5. **Prod migrations (local, gated):** `./scripts/assert-schema-code-compat.sh && supabase link --project-ref khahcozfbnpykspvatrg && supabase db push --dry-run` (review every pending migration; the count has grown past the 12 recorded here) then `supabase db push`. Take the `pg_dump` from the Rollback section FIRST — it is the only restore point that will exist.
6. **Prod code:** after explicit approval and the local production migration gate, run `gh workflow run test.yml -f staging_action=none -f deploy_production=true`. The dependency-free production job owns both secret Render hooks. Do not wait for unrelated test jobs after that deploy job succeeds.
7. **Flag:** set `ENABLE_BACKGROUND_PROCESSING=true` only after steps 5-6 and health below.

## Local DoD (gate, not CI — CI is out of minutes)

Ran 2026-08-07 against `main`:

- `uv run pytest backend/tests/ -m "not integration" -q` → **988 passed, 235 deselected, 7 warnings**
- `npm --prefix frontend run test:unit -- --reporter=json` → **success True, 0 failed, 300 passed** (102 suites)
- `npm --prefix frontend run check` → **0 errors 0 warnings**
- New migrations syntax-checked (no `psql` errors on `supabase db diff` — local instance not running, but SQL parses and grants match the 11 revoke targets).

Superseded: `./scripts/verify.sh backend` is now the Tier 1 gate and runs the integration suite against local Postgres. The drills live in `backend/tests/drills/` behind the `drill` marker and run against staging via `./scripts/drill-staging-workers.sh`.

## Health to confirm after flag on (staging then prod)

- `GET /health/ingestion` → `status: ok`, `tasks alive`, `oldest_next_poll_seconds` < 1800, `integrations_due` 0-1, `leases_held` 0-1, `items_dead_letter` 0, `attachments_dead_letter` 0, `open_incidents` 0.
- `GET /health/egress` → after 1h idle, `total_bytes` projects to single-digit MB/month (not 28 GB). Top operations should be `supabase:claim_due_email_sync` etc. at ~1 per tick, not per second.
- Sentry: trigger synthetic error (watchdog `logger.exception` path) and confirm event arrives.
- Data repair: run `20260803000001_revive_misclassified_dead_letters.sql` count against prod and record row count (expect 0-2 pre-fix `parse_invalid` dead letters).
- Watch `items_dead_letter` for 24h — any non-zero is a bug (inc 2 guarantees nothing dead-letters on first failure).
- Toni acceptance (polling v2 step 19): reconcile `toni@melisma.net` Outlook for 30d, confirm discrepancy 456 → 0, Inbox+Archive read included, new mail within SLO over two intervals, synthetic failure opens/resolves one notification (requires Resend config).

## Rollback

**There is no code rollback for this batch. `git revert` does not restore a
dropped column.**

The previous text here said rollback was *"`git revert` of the five v2 PRs plus
four migrations"*, and flagged itself as *"an assertion, not a tested
property"*. It was written for the polling-v2 batch, where nothing was
destroyed. It is wrong for this one, and it is wrong in the most dangerous
possible way: a stale rollback plan is read under pressure, at the exact moment
nobody has time to check whether it still applies.

The pending batch is **12 migrations** ending in `20260829000001`, which runs
`ALTER TABLE public.events DROP COLUMN status`. Once that commits, the values
are gone. No later migration and no revert can reconstruct which rows were
`sync_failed` — that is precisely why the backfill in that migration had to be
completed before it reached any durable environment.

Compounding it: the Supabase organisation is on the **free plan**. No PITR, no
automated backups. There is no restore point you did not take yourself.

**The only rollback is a dump taken immediately before the cutover:**

```bash
pg_dump "$PRODUCTION_DB_URL" --format=custom --file=pre-cutover-$(date +%Y%m%dT%H%M%SZ).dump
```

Production is ~55 MB / 295 events / 2409 emails, so this takes seconds. Take it,
verify it is non-empty, and keep it until the cutover has been healthy for at
least 24 hours.

**Restoring is a full-database operation, not a selective one.** Anything
written between the dump and the restore is lost, so the decision to roll back
is also a decision to discard that window.

### Forward is usually the better direction

Every defect this batch has produced was fixed forward, and the machinery to do
that safely now exists:

- `./scripts/rehearse_cutover.py --production-url <ro> --faithful` replays the
  whole batch against a redacted clone of production's real rows. It found two
  blockers a synthetic rehearsal could not: the `pending_change` CHECK domain,
  and the `event_change_proposals` backfill guard refusing two real events.
- `./scripts/verify.sh backend` is the Tier 1 gate.
- `./scripts/drill-staging-workers.sh` proves worker behaviour against staging.

Run the faithful rehearsal again immediately before the cutover. Production is a
live system; its data changes, and a rehearsal from yesterday is evidence about
yesterday's rows.

## Historical non-deploy record

The original 2026-08-07 increment intentionally stopped before production. That historical stop is superseded for future deployment mechanics by ordered-cutover step 6 above; production still requires explicit user approval.
