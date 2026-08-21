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

**Status:** verified locally, not deployed. `ENABLE_BACKGROUND_PROCESSING=false` stays.
**Branch:** `main` at `7ee04d6e` + this commit. No prod deploy until you explicitly approve.

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
- **Hardening 9:** `scripts/drill-lease-recovery.sh` + `test_integration_ingestion_drill.py`
  (gate + Outlook fixture).

Migrations added (11 pending on prod, was 9):
- `20260807000001_fix_recovery_withdrawn_and_complete.sql` (withdrawn_count)
- `20260807000002_explicit_service_role_grants.sql` (explicit 11 grants)

Prod is still at `a50e1e4e` code vs `20260803000002` schema, with BG off — inert mismatch.
Do not flip the flag via Render env alone. Follow the ordered cutover below.

## Ordered cutover (must be migrations first, code second, flag last)

Ordering constraint (migrations first, code second, flag last) carried from the
egress-scheduling and polling-v2 work:

1. **No CI minutes will ever be bought for test gating.** Local verification remains authoritative. The dependency-free production deployment job is the exception because it owns the secret Render hooks; wait only for that job, not unrelated test jobs.
2. **Staging token:** `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (checks both dev and staging, copies working → stale; if both stale, re-auth one side then re-sync). Do not ask to reauth when one side is working.
3. **Staging deploy (local, gated):** `./scripts/assert-schema-code-compat.sh && supabase link --project-ref lxmysergoeaegxlyfzwk && supabase db push` (dry-run then push). Render deploys on main push. `gh workflow run test.yml` to staging is a bonus only — never required.
4. **Staging drills:** `./scripts/drill-lease-recovery.sh` (local Supabase) and staging full-path.
5. **Prod migrations (local, gated):** `./scripts/assert-schema-code-compat.sh && supabase link --project-ref khahcozfbnpykspvatrg && supabase db push --dry-run` (review 11) then `supabase db push`.
6. **Prod code:** after explicit approval and the local production migration gate, run `gh workflow run test.yml -f staging_action=none -f deploy_production=true`. The dependency-free production job owns both secret Render hooks. Do not wait for unrelated test jobs after that deploy job succeeds.
7. **Flag:** set `ENABLE_BACKGROUND_PROCESSING=true` only after steps 5-6 and health below.

## Local DoD (gate, not CI — CI is out of minutes)

Ran 2026-08-07 against `main`:

- `uv run pytest backend/tests/ -m "not integration" -q` → **988 passed, 235 deselected, 7 warnings**
- `npm --prefix frontend run test:unit -- --reporter=json` → **success True, 0 failed, 300 passed** (102 suites)
- `npm --prefix frontend run check` → **0 errors 0 warnings**
- New migrations syntax-checked (no `psql` errors on `supabase db diff` — local instance not running, but SQL parses and grants match the 11 revoke targets).

No integration tests run by default (`-m "not integration"` gate per AGENTS.md); the two integration-only drills are behind `scripts/drill-lease-recovery.sh` and require `supabase start`.

## Health to confirm after flag on (staging then prod)

- `GET /health/ingestion` → `status: ok`, `tasks alive`, `oldest_next_poll_seconds` < 1800, `integrations_due` 0-1, `leases_held` 0-1, `items_dead_letter` 0, `attachments_dead_letter` 0, `open_incidents` 0.
- `GET /health/egress` → after 1h idle, `total_bytes` projects to single-digit MB/month (not 28 GB). Top operations should be `supabase:claim_due_email_sync` etc. at ~1 per tick, not per second.
- Sentry: trigger synthetic error (watchdog `logger.exception` path) and confirm event arrives.
- Data repair: run `20260803000001_revive_misclassified_dead_letters.sql` count against prod and record row count (expect 0-2 pre-fix `parse_invalid` dead letters).
- Watch `items_dead_letter` for 24h — any non-zero is a bug (inc 2 guarantees nothing dead-letters on first failure).
- Toni acceptance (polling v2 step 19): reconcile `toni@melisma.net` Outlook for 30d, confirm discrepancy 456 → 0, Inbox+Archive read included, new mail within SLO over two intervals, synthetic failure opens/resolves one notification (requires Resend config).

## Rollback

`email_fetch.py` was deleted in #234 before v2 ever ran in prod, so rollback is `git revert` of the five v2 PRs plus four migrations. No v2 state is destroyed — tables, leases, discovered identities persist, so a later re-cutover resumes. Verify this claim on staging before prod cutover (currently an assertion, not a tested property per hardening finding 30).

## Historical non-deploy record

The original 2026-08-07 increment intentionally stopped before production. That historical stop is superseded for future deployment mechanics by ordered-cutover step 6 above; production still requires explicit user approval.
