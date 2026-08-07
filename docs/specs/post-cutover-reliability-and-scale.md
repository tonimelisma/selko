# Post-Cutover Reliability and Scale — Rock-Solid Plan

**Status:** Planned, not started. Written 2026-08-06 (evening).
**Scope:** `backend/**`, `supabase/**`, `frontend/src/**` (+ iOS/Android for one increment), `config`, `scripts/`, `docs/`.
**Supersedes / completes:** `ingestion-recovery-hardening.md` findings 30–31 and egress open questions 1–8; `egress-and-work-scheduling.md` increments 3–6 hardening tail; `cutover-verification-20260807.md` operational gate.
**Does not re-litigate:** the leased durable pipeline (`FOR UPDATE SKIP LOCKED` + heartbeat + `save_email_with_attachment_descriptors` + provider-cursor triggers), the structural Gmail/Graph error classifier, or the Outlook well-known-folder resolution. Those are correct and stay.

---

## 0. Why this doc exists

The Aug 3–6 batch closed four P0s (substring dead-letter, silent loop death, descriptor race, red `main`), cut idle egress ~500× (1.5 M → ~3k RPCs/day, ~28 GB/mo → single-digit MB), and added the supervision/observability that makes a cutover diagnosable. It did so incrementally and largely correctly — but incrementally means seams.

Full read-through of `main` at `58fc8cb2` (8 Aug 6 commits + 5 Aug 3–4 hardening commits, 47 files +5107/−403) plus the 11 pending migrations finds **no data-loss bug still live**, but **seven families of soft spots where the fix is partial, untested at the real seam, inconsistent across the two schedulers, or operationally un-provable.** Each soft spot is cheap to misunderstand ("just tighten the loop") and expensive to hit in prod (silent truncation, starved reconcile, missed nudge, unexercised Graph write, HEAD-vs-schema drift).

This plan eliminates the family, not the symptom. Every increment below is A/B-tested against at least one cheaper band-aid and explains why the band-aid loses. Increments are kept small and shelved in dependency order; steps 17–19 of `polling-email-ingestion-v2.md` (staging drills, prod cutover, Toni 456→0 acceptance) remain the gate and are not weakened.

**Research method.** Read-only walk of all touched modules before design: `workers/pool.py`, `workers/email_ingestion.py`, `workers/ingestion_runtime.py`, `services/{gmail,google_errors,email_ingestion,email_sync_health,auth,egress,msgraph,outlook}`, `api/{app,routes/{health,events,integrations}}`, `supabase/migrations/20260801*–07000002`, `frontend/src/lib/components/ConnectionRecovery.svelte`, `config.py`, `scripts/drill-lease-recovery.sh`, `tests/{test_egress,test_ingestion_runtime,test_workers,test_email_ingestion_v2,integration/*}`, and the three predecessor specs. Soft-spot grading used two lenses: *fidelity* (does it do what the plan claimed, at the real seam?) and *first-principles* (would you still do this from blank?).

---

## 1. Inventory — every remaining soft spot, grouped

### 1A. Health lies when busy (`down`/`degraded` undercount)

* `workers/ingestion_runtime.py:289–317` `health_snapshot()` does `select("id,acquisition_status", count="exact")` + Python `sum(... == "dead_letter")` over `items.data`. PostgREST caps a single response at **1000 rows**; `count="exact"` does not help — the body is still truncated. Past ~1k dead letters (or ~1k attachments) the endpoint reports `items_dead_letter == <1000` and `status == "ok"`. Same for `attachments`. Meanwhile `services/email_sync_health.py:133` `_dead_letter_integration_ids` correctly **pages** (`_DEAD_LETTER_PAGE_SIZE=1000`, `_DEAD_LETTER_MAX_PAGES=100`) — the health *evaluator* is safe, the health *endpoint* is not. A monitoring system that under-reports is indistinguishable from a healthy one.

* `health_snapshot()` also does a single `select("next_poll_at,lease_expires_at")` over all `email_sync_state` rows (today <10 rows — fine) but filters in Python; a DB-side `count(*) FILTER (WHERE ...)` would be one RPC instead of shipping every row plus still be accurate at 10k integrations.

**Band-aid:** "just add `.range()` client paging like the evaluator." Loses because it makes `/health/ingestion` N RPCs in series on every health probe. **Real fix:** server-side counted RPCs (one round-trip, no truncation, no Python sum).

### 1B. Gmail batch exception eats failures

* `services/gmail.py:490–510` `get_messages_metadata_batch` builds `BatchHttpRequest`, callback `_on_message` `raise _wrap_http_error(...)` on per-message non-404 `HttpError`. In some `googleapiclient` versions `BatchHttpRequest.execute()` **swallows** per-request callbacks' exceptions and surfaces only the batch-level `HttpError` (or nothing). If swallowed, one 500 in a chunk of 100 silently disappears and the caller records the wrong `change_kind`. `tests/test_email_ingestion_v2.py` coverage for 6a mocks at `get_messages_metadata_batch` level and never exercises the callback error path.

**Band-aid:** "log and ignore per-message transport errors." Loses because a transient 500 must retry that identity, not classify it `removed`. **Real fix:** never `raise` inside the callback; capture per-request outcome into `results` + `per_request_errors`, resolve after `execute()`.

### 1C. Two idle models sharing one deployment

* `workers/pool.py:204` `_scheduler_loop` is **fixed tick + nudge**: drain until empty, then `wait_for(nudge, timeout=_tick_seconds())` where `_tick_seconds()` = `max(worker_idle_max_seconds, idle_sleep_seconds, 5.0)` (~30 s).
* `workers/email_ingestion.py:445` `coordinator_loop` is **tick + nudge** (60 s) — same idea, consistent with the pool.
* `workers/email_ingestion.py:520` `_claim_loop` (`acquisition_loop`, `attachment_loop`) is **geometric backoff** on `stop_event`: `idle_backoff(consecutive_idle)` 1 s → 30 s. Its nudge is **unwired**: `ingestion_runtime.py:87` `nudge()` iterates workers but acquisition loops sleep on `stop_event.wait()`, not on `nudge_event`. After the coordinator discovers N new items, acquisition can still sleep up to 30 s before claiming the first one. Egress is fixed, but **p50 discovery→acquisition latency is needlessly tail-latent**.

* `workers/pool.py:92` `num_workers` doc says "concurrency hint for executor pool" — no executor exists. Processing is `await _process_event_sync` sequentially inside the drain. `num_workers=3` in `config.py:83` is now dead config. Either it fans out or it should be deleted; leaving a 3→1 behavioral change behind the same flag is confusing.

* `pool.py:131` `_tick_seconds()` floor `5.0` and `ingestion_runtime` equivalent are invisible: `WORKER_IDLE_MAX_SECONDS=1` silently becomes 5 s with no warning/log — a deployer debugging latency sees no clue.

**Band-aid:** "leave `_claim_loop` geometric, it's lower egress." Loses because geometric on acquisition buys ≤(30 s − tick) egress while costing user-visible latency on every mail burst. **Real fix:** one idle model everywhere, with nudge wirable to every claim loop.

### 1D. Heartbeat does not cover the long tail of discovery

* `workers/email_ingestion.py:202` `_discover_gmail` calls `list_message_ids` (paginated `q=after:…` loop, up to thousands of pages on a 90-day reconcile) **without** any `require_heartbeat`. `require_heartbeat` is only called **before** `upsert_discovered` per 100-page chunk. A slow `list_message_ids` that spans >`email_lease_seconds` (900 s) will lose its lease while still listing, then `upsert_discovered` fails with lease-lost and the whole pass is discarded — exactly the mid-pass expiry the design set out to avoid, just moved from the upload phase to the listing phase.

* `email_ingestion.py:247` `claim_due_email_reconciliation` predicate requires `next_poll_at > now()` (reconcile only when not due for a normal poll). If an integration is flapping `next_poll_at <= now()` via `fail_sync` backoff, it can starve reconcile forever while normal polls keep failing and retrying. Weekly reconcile is then the only completeness backstop and it is itself capped at 2000.

**Band-aid:** "increase lease to 1800 s." Loses because it papers over one tail — Outlook folder fan-out has the same shape, and a hung provider call could exceed any lease. **Real fix:** heartbeat that actually covers the long call, plus reconcile eligibility that doesn't starve.

### 1E. Observability too local / too easy to miss

* `services/egress.py:63` `EgressMeter` is **process-local, reset on restart**. `/health/egress` against a freshly deployed instance is empty; its `projected_bytes_per_30d` on a 2-minute-old process wildly overestimates. No per-integration or per-run attribution, so a noisy mailbox is indistinguishable from a hot loop without reading log lines.

* `api/app.py:198` Sentry `traces_sample_rate=0.0`, `send_default_pii=False` correct, but watchdog `capture_exception` is swallowed if `sentry_sdk` not installed — no integration test proves the path fires, and no synthetic check is wired to `GET /health/*`.

* `services/email_sync_health.py:172` `evaluate_once` correctly pages dead letters; `workers/ingestion_runtime.py` `health_snapshot` (1A) does not — two places to remember, one of them wrong. Duplication invites skew.

**Band-aid:** "add Grafana." Loses for a single operator — structured log lines (5c) + Sentry + two health endpoints are the right YAGNI weight; just make the two health surfaces agree and have a one-command synthetic.

### 1F. Recovery accounting & UI half-life

* `supabase/migrations/20260807000001` added `withdrawn_count` and retrained both RPCs to include `cancelled`/`rejected` — correct. Existing `waiting` rows created **before** the migration have `withdrawn_count=0` even if they already had withdrawn events; `refresh_waiting_calendar_recoveries` will heal them on next claim, but staged proof of "discovered = completed + remaining + errored + withdrawn closes" is not in the test suite — only a Svelte arithmetic fallback is.

* `_incident` grace for first poll (`services/email_sync_health.py:183`) skips `stale_poll` while `last_started` within `warning_seconds` — correct. But `consecutive_failures >= 3` still fires a `repeated_failures` critical even inside that grace (first poll attempted 3 times rapidly). Harmless today (no first-poll retries that fast) but inconsistent.

* `frontend/src/lib/components/ConnectionRecovery.svelte:63` resilient `setTimeout` chain (7c) keeps `pollTimer` as a single timeout; Svelte remount creates a second timer without clearing the first (`onMount` cleanup only runs on unmount). `justCaughtUp` 4 s transient correctly disappears but `pollTimer` leaks on fast navigation. `live-ui-updates.md` prescribes private `Broadcast` invalidations — the poll is knowingly debt, but debt without an expiry becomes permanent.

### 1G. Cutover atomicity & rollback unproven

* 11 migrations pending on prod (`20260801000001..07000002`) vs prod code pinned at `a50e1e4e` with `ENABLE_BACKGROUND_PROCESSING=false` — inert mismatch today, explosive if the flag is flipped via **Render env var** (which **redeploys HEAD**, not the running commit). The runbook says "migrations first, code second, flag last via `gh workflow run test.yml`" but the dashboard ENV path is still the accidental hot path (it caused the 26-commit jump). No guard prevents it.

* `docs/specs/cutover-verification-20260807.md:65` rollback described as `git revert` of 5 v2 PRs + migrations, "v2 state persists" — **asserted, never tested on staging** (hardening Finding 30). Revert of the dynamic-SQL RPC `save_email_with_attachment_descriptors` while rows already written by it have not been exercised.

* Staging auth still dead (`invalid_grant` since 2026-02-12) + GitHub minutes out + `workflow_dispatch` stuck `queued` — the three gates for staging proof are all red at once, so no drill has run outside local.

* Docs drift: ordered runbook lives in **three** places (`polling-email-ingestion-v2.md` Production cutover runbook, `egress-and-work-scheduling.md` Ordering constraint, `cutover-verification-20260807.md`); only the last carries the local DoD numbers (988/300). The next deployer has to reconcile three docs.

**Band-aid:** "just run `supabase db push` manually and flip the env var." Loses because it recreates the HEAD-ahead-of-schema drift and bypasses the workflow's atomic `db push` + deploy. **Real fix:** make the wrong order impossible and the rollback rehearsed.

### 1H. Drill coverage shape-only

* `scripts/drill-lease-recovery.sh` + `tests/integration/test_integration_ingestion_drill.py:230` — `test_kill_mid_pass` is a `pytest.skip` placeholder; `test_expired_lease_is_claimable` asserts `True` (structural, not behavioral). `test_gate_blocks_llm_until_attachments_terminal` skips unless `supabase start`. The only behavioral proof of the atomic-RPC gate is the earlier `test_integration_email_ingestion_v2.py` count RPC. No single test starts a real runtime, SIGKILLs mid-lease, restarts, and asserts exact-once per `(integration_id, provider_message_id)`.

* Outlook write-path fixture (`test_outlook_acquisition_handles_file_vs_item_attachment`) exercises the descriptor mapping but not the Graph token-refresh mid-pass (`_outlook_token(force_refresh=True)`) nor the `RESYNC_REQUIRED` → re-list path, both of which are the highest-value Graph branches.

---

## 2. Design principles for the real fix

1. **One counted path.** If it matters for an alert, count it server-side in SQL and expose the count once. No Python `sum(...)` over a truncated response, no second paged scan that must be kept in sync.
2. **One idle model.** Fixed tick + edge-triggered nudge everywhere a worker waits. Geometric backoff becomes a floor, not a model. Every claim loop that can be woken in the current process is wirable; `num_workers` means something or disappears.
3. **Heartbeat covers the long call.** Any provider loop that can outlive the lease must heartbeat **around** the call, not merely before the next DB write. Fail-lease is a safety net, not the primary defence.
4. **Exceptions don't propagate through callbacks.** Per-request outcomes are values, not thrown control flow.
5. **Ordering is enforced, not documented.** The deploy workflow, not the runbook, prevents schema-behind-code.
6. **Debt has an expiry.** Every "keep poll for now" increments with a successor PR named.

---

## 3. Increments — the real fix

Every increment is small enough to review in one sitting and ordered so a later one never needs a revert of an earlier one. Size = review size, not calendar days.

```
P0 cutover gate (must land before any prod flag flip)
  ┌─ R1 health: counted RPCs                (fixes 1A, 1E dupe)
  ├─ R2 gmail batch: per-request outcomes    (fixes 1B)
  ├─ R3 unified scheduler + nudge           (fixes 1C)
  ├─ R4 heartbeat + reconcile starve        (fixes 1D)
  └─ R5 enforced cutover + rollback rehearsal (fixes 1G — gate, never silent again)

P1 close-behind (land before Toni 456→0, within one sprint)
  ├─ R6 observability contract + synthetic  (fixes 1E residue)
  ├─ R7 recovery correctness + Realtime seam (fixes 1F)
  └─ R8 real drills (fixes 1H)

P2 hygiene (after Toni, before photo re-intro)
  └─ R9 config & doc consolidation
```

Parallelism: R1, R2, R3 branch independently; R4 depends on R3 (heartbeat hook shared); R5 gates all.

---

### R1 — Health lies → counted health (P0)

**Branch:** `fix/health-counted-degraded` · **Scope:** `supabase/**`, `backend/selko/workers/ingestion_runtime.py`, `backend/selko/api/schemas/common.py`, `backend/selko/api/routes/health.py`, `backend/tests/test_ingestion_runtime.py` · **Size:** small

**Change**

1. New migration `supabase/migrations/<ts>_health_counted_slo.sql` (SECURITY DEFINER, explicit `GRANT TO service_role`):

```sql
CREATE OR REPLACE FUNCTION public.health_dead_letter_counts()
RETURNS TABLE (items_dead_letter integer, attachments_dead_letter integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  SELECT
    (SELECT count(*)::int FROM public.email_ingestion_items
       WHERE acquisition_status = 'dead_letter'),
    (SELECT count(*)::int FROM public.attachments
       WHERE ingestion_status = 'dead_letter');
END; $$;
REVOKE ALL ON FUNCTION public.health_dead_letter_counts() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_dead_letter_counts() TO service_role;

CREATE OR REPLACE FUNCTION public.health_poll_slo(p_warning_seconds integer)
RETURNS TABLE (integrations_due integer, leases_held integer,
               oldest_next_poll_seconds integer, open_incidents integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  SELECT
    (SELECT count(*)::int FROM public.email_sync_state s
       JOIN public.integrations i ON i.id=s.integration_id
       WHERE i.status='active' AND s.next_poll_at <= now()
         AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())),
    (SELECT count(*)::int FROM public.email_sync_state WHERE lease_expires_at > now()),
    (SELECT GREATEST(0, EXTRACT(EPOCH FROM (now() - min(s.next_poll_at)))::int)
       FROM public.email_sync_state s),
    (SELECT count(*)::int FROM public.operational_incidents
       WHERE status='open' AND incident_key LIKE 'email-sync:%');
END; $$;
REVOKE ALL ON FUNCTION public.health_poll_slo(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_poll_slo(integer) TO service_role;
```

2. `workers/ingestion_runtime.py:234` `health_snapshot()` becomes:

```python
def health_snapshot(self) -> dict[str, Any]:
    snap = {"status":"ok","background_processing_enabled":True,
            "instance_id":self.instance_id,"tasks":self.status()["tasks"], …}
    try:
        dead = self.client.rpc("health_dead_letter_counts").execute().data[0]
        slo  = self.client.rpc("health_poll_slo",
               {"p_warning_seconds": self.config.email_health_warning_seconds}
             ).execute().data[0]
        items_pending = self.client.rpc("health_pending_count").execute()  # or keep one more small RPC
        # ... merge, no Python sum() over a truncated response
    except Exception: … return degraded …
    # degraded = dead.items_dead_letter>0 or dead.attachments_dead_letter>0 or slo.open_incidents>0
    #          or slo.oldest_next_poll_seconds > warning
```

Two RPCs (dead-letter + SLO+incidents) — fixed cost regardless of scale. No `select count="exact"` tablescan, no `sum` over truncated `data`.

3. Delete the evaluator's duplicate paging for health (keep the evaluator's paging for **incident creation**, which needs per-integration granularity). Evaluator stays paged; health becomes counted. The duplication is retired.

**Verify**

* `tests/test_ingestion_runtime.py` — seed 1500 items via `upsert_discovered_email_items` mock with 1500 `dead_letter`, assert `health_snapshot()["items_dead_letter"]==1500` (fails before, passes after).
* `supabase db reset` + `EXPLAIN ANALYZE SELECT health_dead_letter_counts()` uses the existing `email_ingestion_items.acquisition_status` index, not a seq scan at 100k.

**Why not client paging?** N sequential `.range()` calls on the hot health probe multiply latency and still race with concurrent inserts; one server-side `count(*) FILTER` is 1 round-trip and transactional. Alternatives considered: materialized view (stale), trigger-maintained counter table (write amplification, out-of-sync risk). Rejected.

---

### R2 — Gmail batch swallow → per-request outcomes (P0)

**Branch:** `fix/gmail-batch-per-request-outcomes` · **Scope:** `backend/selko/services/gmail.py`, `backend/tests/test_gmail.py` (or extend `test_email_ingestion_v2.py`) · **Size:** small

**Change** — `gmail.py:475` `get_messages_metadata_batch`:

```python
def get_messages_metadata_batch(service, message_ids, *, batch_size=100) -> dict[str, dict]:
    results: dict[str, dict] = {}
    per_request_errors: list[BaseException] = []
    def _on_message(request_id, response, exception):
        if exception is None:
            results[request_id] = response
            return
        if isinstance(exception, RefreshError):
            # not per-message recoverable — park for the batch-level raise
            per_request_errors.append(_auth_error(exception, prefix="Gmail credentials expired or revoked"))
            return
        if isinstance(exception, HttpError) and getattr(exception.resp,"status",None)==404:
            results[request_id] = {"id": request_id, "_deleted": True}
            return
        if isinstance(exception, HttpError):
            per_request_errors.append(_wrap_http_error(exception, prefix="Gmail API error batch metadata"))
            return
        per_request_errors.append(GmailError(f"Gmail API error batch metadata: {exception}"))

    for chunk in _chunks(ids, batch_size):
        per_request_errors.clear()
        batch = service.new_batch_http_request()
        for mid in chunk: batch.add(service.users().messages().get(..., format="metadata"), callback=_on_message, request_id=mid)
        batch.execute()   # never raises via callback now
        if any(isinstance(e, GmailAuthError) for e in per_request_errors):
            raise per_request_errors[0]  # auth aborts the whole discover — correct terminal
        if per_request_errors:
            # one transient 5xx in a 100-chunk must retry that identity, not poison the whole chunk
            # caller handles retryable per-code; surface as provider_transient with the first error's detail
            # but keep already-successful results for this chunk
            # -> re-raise a single aggregate that classify_email_error maps to provider_transient
            raise GmailError(f"Gmail batch metadata partial failure ({len(per_request_errors)}/100)", status_code=500)
    return results
```

Plus: in `workers/email_ingestion.py:_discover_gmail` handle the partial-failure raise by re-queueing just that chunk via `provider_transient` backoff (reuse `classify_email_error`), not whole pass — **chunk-level retry, not pass-level** (see R4 heartbeat).

**Verify**

* Unit test with `MagicMock` `service.new_batch_http_request()` whose `execute()` invokes `callback(req_id, None, HttpError(resp=500))` for one id in a chunk of 3 — before: either swallowed or whole-batch swallowed; after: first call returns 2 successes + raise transient; second call for the remaining 1 succeeds.

---

### R3 — Two idle models → one idle model + everywhere-nudge (P0)

**Branch:** `fix/unified-scheduler-nudge` · **Scope:** `backend/selko/workers/{pool,ingestion_runtime,email_ingestion}.py`, `backend/selko/config.py`, `backend/tests/test_{workers,ingestion_runtime}.py`, `backend/selko/api/app.py` · **Size:** medium

**Change**

1. **`WorkerPool.num_workers` stops meaning "pollers"**. Single scheduler drains; concurrency is an **executor semaphore** around the actual I/O, not extra pollers. `pool.py: _scheduler_loop` drains with:

```python
sem = asyncio.Semaphore(max(self.config.worker_calendar_sync_concurrency, 1))
async def _process_one(event): 
    async with sem: await self._process_event_sync(...)
# drain: gather with semaphore rather than sequential await
```

Expose `worker_calendar_sync_concurrency` (default 2) alongside existing `email_{acquisition,attachment}_concurrency`. Legacy `worker_pool_size` kept as alias for one release with a deprecation log, then removed — and `num_workers` constructor param deleted. No behavioral 3→1 behind a silent flag.

2. **Unify waiting.** Add `EmailIngestionWorker._claim_nudge: asyncio.Event` (same loop-bound lifecycle as coordinator nudge). `IngestionRuntime.nudge()` triggers both `coordinator_loop` and each `_claim_loop`. Refactor `_claim_loop`:

```python
async def _claim_loop(self, run_once):
    nudge = self.ensure_claim_nudge()
    consecutive_idle = 0
    while not self.stop_event.is_set():
        if await self._guarded(run_once): 
            consecutive_idle = 0; continue
        consecutive_idle += 1
        wait_s = self.idle_backoff(consecutive_idle)  # floor, not model
        try: await asyncio.wait_for(asyncio.wait([self.stop_event.wait(), nudge.wait()],
                      return_when=asyncio.FIRST_COMPLETED), timeout=wait_s)
        except asyncio.TimeoutError: pass
        if nudge.is_set(): nudge.clear(); consecutive_idle = 0
```

Result: discovery→acquisition p50 goes from up to 30 s → <100 ms (coalesced), idle egress stays tick-limited (coordinator tick dominates), and acquisition burst after a 2000-bound reconcile never waits for backoff.

3. **Make floors visible.** `config.py` dataclass field `worker_idle_max_seconds` / `worker_calendar_sync_concurrency` docstring notes the 5 s floor; `pool.py: _tick_seconds()` logs once at `DEBUG` when clamping `WORKER_IDLE_MAX_SECONDS < 5`.

**Verify**

* `test_scheduler_drains_with_concurrency` — enqueue 5 events, `worker_calendar_sync_concurrency=2`, assert at most 2 `sync_event` calls overlap (via `asyncio.Event` + counter), still drains in ≤ceil(5/2) passes.
* `test_acquisition_nudge_wakes_claim_loop` — `stop_event` not set, `_claim_loop` sleeping on backoff, `runtime.nudge()` resolves within 50 ms (fails before).

**Why not keep geometric forever?** Geometric optimizes steady-state idle while sacrificing the only latency users feel: the mail they just waited for. With Nudge + `DEAD_LETTER_PAGE_SIZE` egress now single digits/month, the last millisecond of backoff costs more in perceived latency than it saves in envelope.

---

### R4 — Heartbeat around the long call + reconcile anti-starve (P0)

**Branch:** `fix/heartbeat-around-discovery` · **Scope:** `backend/selko/workers/email_ingestion.py`, `backend/selko/services/email_ingestion.py`, `supabase/migrations/*_heartbeat_and_reconcile.sql`, `backend/tests/test_email_ingestion_v2.py` · **Size:** medium

**Change**

1. **Heartbeat the listing itself.** Wrap every paginated provider enumeration with a periodic heartbeat: heartbeat **every N provider pages** and **every 60 s wall-clock**, whichever comes first. Implementation: helper `_with_heartbeat(integration_id, worker_id, coro_fn)` that runs the provider call in a thread and heartbeats on a 30 s timer in parallel. Applied to `list_message_ids` loop, Gmail `BatchHttpRequest` chunk loop, and Outlook `fetch_mail_folders` + per-folder `fetch_message_changes`/`fetch_folder_messages` pagination. Loss-of-lease mid-enumeration now fails fast with `LeaseLostError` and is retried at `run_kind` level with `fail_sync(provider_transient)` backoff, not silently lost.

2. **Fix reconciliation starvation.** Change `claim_due_email_reconciliation` predicate: remove `AND s.next_poll_at > now()`. Replace with `AND (s.last_reconciled_at IS NULL OR s.last_reconciled_at <= now() - interval '1 day') AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())` regardless of `next_poll_at`. This is safe because the two claim functions already `SKIP LOCKED` — if normal poll holds the lease, reconcile cannot claim anyway; if normal poll is due but unclaimed, either can win and the other will take the next slot. Weekly vs daily selection unchanged. Add `email_sync_runs.run_kind` filter: `daily_reconcile` capped per existing `email_reconcile_max_identities` with identity-dedup resumable logic (already correct); keep Outlook uncapped but now O(folders) and heartbeat-protected.

3. **Migration note.** No schema change required beyond possibly adding an index on `last_reconciled_at` if `EXPLAIN` shows seq scan at 10k integrations — measure in staging.

**Verify**

* Slow-provider test: mock `list_message_ids` to sleep 1.2× lease (inject `sleep(2)` with `email_lease_seconds=1`), assert `require_heartbeat` actually extends `lease_expires_at` mid-loop and the pass completes (fails before: lost lease / `complete_sync` returns false).
* Starve test: seed one integration with `next_poll_at = now()-10m` looping `fail_sync` backoff and `last_reconciled_at = now()-8 days`, assert `claim_due_email_reconciliation` still claims (fails before).

**Why not just longer lease?** Any finite lease is a deadline; a hung provider page would still exceed it. Periodic heartbeat makes lease liveness independent of provider latency — the right invariant.

---

### R5 — Make the wrong cutover impossible + rehearse the rollback (P0 — gate)

**Branch:** `fix/enforced-cutover-and-rollback` · **Scope:** `supabase/**`, `.github/workflows/test.yml`, `docs/specs/cutover-verification-20260807.md`, `scripts/assert-schema-code-compat.sh` (new), `docs/ci-cd.md` · **Size:** small (operational correctness > code)

**Change**

1. **Workflow-enforced ordering.** Add a step early in `.github/workflows/test.yml` (both `workflow_dispatch` and push paths): `supabase db diff --linked --schema public | grep -q 'No changes'` check that fails the deploy if HEAD migrations are not yet pushed to the linked environment. Never allow code deploy when `migrations_pending > 0`. The workflow remains the only blessed `supabase db push` path — document that manual `supabase db push` is owner-only, idempotent repair, not the deploy path.

2. **Guard the Render env-var footgun.** Add `scripts/assert-schema-code-compat.sh` (checked by CI on `main`): reads `supabase/migrations` max timestamp vs `supabase db remote` max applied timestamp on prod (via `supabase migration list --linked`); fails if pending. Reference it in `cutover-verification-20260807.md` as the pre-flag check.

3. **Rollback rehearsal on staging (Finding 30).** In staging, before any prod cutover: push all 11 migrations + code, insert one `save_email_with_attachment_descriptors` mail with 2 descriptors, `git revert` the 5 PRs that introduced v2 (`4bbe07c5..e9e478c3` squashes) including the four migration reverts, deploy reverted image, assert: v2 tables (`email_sync_state`, `email_ingestion_items`, `operational_incidents`) **still exist** (reverts only drop new RPCs, not tables), discovered identities still present, and a second cutover reclaims leases and resumes. Record commit SHAs + row counts in the checklist. This converts "v2 state persists — asserted" to "v2 state persists — rehearsed."

4. **Single ordered doc.** Keep `cutover-verification-20260807.md` as the **sole** ordered checklist. Replace both `egress-and-work-scheduling.md` "Ordering constraint" and `polling-email-ingestion-v2.md` duplicated cutover section with a one-line pointer: `See cutover-verification-20260807.md — the gate before any flag flip.`

5. **Unblock the three gates.** Top-up doc now tracks them as checkboxes with owners: GitHub minutes top-up (you), `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail` browser auth (you), `workflow_dispatch` re-dispatch (cancel stuck run `31127495914`, re-run on-demand). No code change, but the plan explicitly lists them so CI is not the invisible blocker again.

**Verify**

* Dry-run the guard on staging with one pending migration — workflow correctly refuses to deploy code.
* Staging rollback rehearsal log (counts, SHAs) committed to `cutover-verification` as addendum.

**Why not just "remember not to use ENV"?** ENV is the Render dashboard's primary control; docs don't stop clicks. A CI gate that fails the deploy on schema-behind-code makes the wrong path mechanically impossible.

---

### R6 — Observability contract + one-command synthetic (P1)

**Branch:** `feat/observability-contract` · **Scope:** `backend/selko/services/egress.py`, `backend/selko/api/routes/health.py`, `backend/selko/workers/ingestion_runtime.py`, `scripts/smoke-ingestion.py` (new), `backend/tests/test_egress.py` · **Size:** small

**Change**

1. **One health shape.** After R1, `/health/ingestion` and `EmailSyncHealthEvaluator` share a single `services/ingestion_health.py` helper for `withdrawn/dead-letter/open-incident` semantics (de-dupe the two `withdrawn` forecasts). Evaluator keeps paging for per-integration incident creation; health endpoint stays counted. No second place to keep in sync.

2. **Egress clarity.** `EgressMeter.projected_bytes_per_30d` annotated in OpenAPI description as "naïve projection — valid only on long-lived idle instances" and emitted alongside `uptime_seconds` so a 2-minute snapshot is not quoted. Keep process-local (cheap); per-integration attribution stays out (high cardinality, privacy risk) until a dedicated table is justified.

3. **One-command synthetic.** `scripts/smoke-ingestion.py` (unit-testable): hits `GET /health/ingestion` and `GET /health/egress`, raises watchdog synthetic (inject `raise RuntimeError("synthetic")` behind `SMOKE_SENTRY_DSN` env guard), asserts `tasks.alive==true`, `items_dead_letter==0`, Sentry event arrived (if DSN set). Wired as the "Health to confirm after flag on" check in the cutover doc — replaces manual curl list.

---

### R7 — Recovery accounting & Realtime seam (P1)

**Branch:** `fix/recovery-exact-and-realtime` · **Scope:** `supabase/migrations/*_recovery_exact.sql`, `backend/selko/services/email_sync_health.py`, `frontend/src/lib/components/ConnectionRecovery.svelte`, `frontend/src/lib/services/integrations.js`, `ios/**`, `android/**`, `docs/specs/live-ui-updates.md` · **Size:** medium

**Change**

1. **Make withdrawn exact.** Migration adds `integration_recoveries.superseded_at` / constraint that `completed_count + remaining_count + errored_count + withdrawn_count <= discovered_count` (enforced in RPC, not just app). Backfills `withdrawn_count` for pre-migration `waiting` rows by recounting `cancelled`/`rejected` from `events` once. Test: seed one `pending` recovery, tag 5 events, cancel 2 mid-`waiting`, call `refresh_waiting_calendar_recoveries`, assert `discovered=5, completed=2, errored=0, withdrawn=2, remaining=1` (fails before: remaining undercount).

2. **First-poll grace consistency.** In `email_sync_health.py:193` gate the `consecutive_failures >=3` check with the same `age < warning` guard as `stale_poll` — inside initial grace, failures are not yet "repeated" (a fresh `last_started` with 3 fast retries during bootstrap should not page).

3. **Realtime expiry.** Keep Svelte **resilient poll** (R handler in `loadRecovery` — keep previous on error, exponential backoff 5 s → 60 s) but cap its lifetime: if `docs/specs/live-ui-updates.md` Broadcast is available, the card subscribes to `user:<uid>:selko-changes` filtered `resource=integration_recoveries` and uses poll only as the **reconnect catch-up** (current spec's intended design). If Realtime is not yet shipped, mark the poll with an expiry comment: `// TODO(R7b): replace with Broadcast — see live-ui-updates.md §Decision`.

4. **Cross-platform.** Mirror the resilient handler on iOS (`ConnectionRecoveryView.swift`) + Android (`ConnectionRecoveryContent.kt`) — same "keep previous on error, back off" semantics, same invalidation hint.

---

### R8 — Real drills, not shape (P1)

**Branch:** `test/real-lease-and-gate-drills` · **Scope:** `backend/tests/integration/test_integration_*.py`, `scripts/drill-lease-recovery.sh`, `backend/tests/test_gmail.py` · **Size:** medium (test, but load-bearing)

**Change**

1. **Kill-mid-lease is behavioral.** `scripts/drill-lease-recovery.sh` starts local Supabase, seeds one Gmail integration with `email_lease_seconds=10`, starts a real `IngestionRuntime` in a subprocess with a patched `discover()` that sleeps 8 s after `require_heartbeat` while holding the lease, `kill -9` the subprocess mid-lease, starts a second `IngestionRuntime`, asserts: second process's `claim_due_email_sync` reclaims the expired lease within `lease + 1 s`, `email_ingestion_items` uniqueness `(integration_id, provider_message_id)` holds, every `upsert_discovered` identity appears exactly once. This exercises `FOR UPDATE SKIP LOCKED` reclaim **and** uniqueness — the property all 918 mocks never proved.

2. **Gate regression is real-DB.** `test_integration_ingestion_drill.py: test_gate_blocks_llm_until_attachments_terminal` no longer `pytest.skip`; it seeds one email + 2 `pending` descriptors against real local Supabase via `save_email_with_attachment_descriptors`, then asserts `claim_unprocessed_email` returns nothing, mutates both to `stored`, asserts it now returns the email.

3. **Graph token-refresh mid-pass & RESYNC.** Fixture that patches `get_access_token` to return token A, then on `fetch_message_changes` raise `GraphHttpError(401)`, then on force-refresh return token B and succeed; second fixture raises `RESYNC_REQUIRED` sentinel twice (first delta) and asserts the second pass re-lists rather than persisting the sentinel as cursor (the `410` guard added in 6b).

**Verify** — `supabase start && ./scripts/drill-lease-recovery.sh` green; `uv run pytest -m integration -k "gate"` green locally (CI may not have Supabase — gated behind `integration` marker per `AGENTS.md`).

---

### R9 — Config & doc consolidation (P2)

**Branch:** `chore/config-and-docs-tidy` · **Scope:** `backend/selko/config.py`, `docs/specs/README.md`, `docs/database-schema.md`, `CLAUDE.md`, `backend/selko/workers/pool.py`, `backend/tests/test_workers.py` · **Size:** small

**Change**

1. Delete dead path: `cli_backfill_email_ingestion_v2.py` already gone (8g). Now: delete `dynamic-import hack` compat keep-alive after one release (audit every `patch("…get_credentials")` → `get_gmail_credentials`), remove blanket `GRANT ON ALL FUNCTIONS` preamble note from `20260801000001` history comment (explicit grants now canonical in `supabase/migrations/20260807000002` + R1).

2. Config hygiene: deprecate `WORKER_POOL_SIZE` → `WORKER_CALENDAR_SYNC_CONCURRENCY` with `logger.warning` shim and docs migration note; document floor `5.0` in `Config.worker_idle_max_seconds` docstring + `.env.example`; log once when `WORKER_IDLE_MAX_SECONDS < 5`.

3. Docs as one truth: update `docs/specs/README.md` statuses (Hardening: done with remaining Findings 30–31 → R5; Egress: done with open questions 1–8 → R1–R5; Cutover: single pointer). Fold durable "how it works" (leases, discovery→acquisition, readiness gate) into `docs/database-schema.md` and `docs/gmail-integration.md`. Keep this doc as history once landed.

---

## 4. Alternatives considered (per family)

| Family | Cheaper alternative | Why real fix wins |
|---|---|---|
| 1A health | Client-side `.range()` paging on health probe | N RPCs/ probe, still racy; 1 counted SQL is transactional, 1 RPC, same cost at 1 or 10k rows |
| 1A health | Materialized view `ingestion_health_mv` | Stale by definition; refresh adds write path |
| 1B Gmail | Log-and-ignore per-request 5xx | Must retry that identity, not mark `removed` |
| 1C idle | Keep geometric on acquisition | 30 s tail latency on every mail burst for ≤27 s egress saving |
| 1D heartbeat | Longer lease (1800 s) | Any finite deadline still expires on hung provider |
| 1D reconcile | "Reconcile only when idle" | Starves exactly when completeness matters (flapping) |
| 1E egress | Prometheus right now | No one to watch it; logs+Sentry+two health routes serve one operator |
| 1G cutover | "Remember not to use ENV" | Docs don't stop clicks; CI gate does |
| 1G rollback | "Assert rollback is unnecessary" | Head-ahead-of-schema drift already happened (26 commits); must prove revert preserves tables |
| 1H drills | Shape/mocked Gate test | Transaction-boundary bug by definition invisible to mocks |

---

## 5. Sequencing & DoD

### Dependency graph (not a waterfall — parallel where stated)

```
R1 ─┐
R2 ─┼─→ R5 (cutover gate — last word before any flag flip)
R3 ─┤   ↑
R4 ─┘   │
R6 ─────┤ (needs R1)
R7 ─────┤ (after R3 if it touches nudge)
R8 ─────┤ (after R1,R3,R4 so drills prove them)
R9 ─────┘ (after all — docs that describe them)
```

R1/R2/R3 start parallel in three worktrees. R4 after R3. R5 gates flag forever.

### Per-increment DoD (all scale: only the platform you touched)

* Backend-only: `uv run pytest backend/tests/ -m "not integration" -q` + the increment's targeted `integration` drills where applicable + `supabase db diff` syntax check.
* Frontend in R7: `npm --prefix frontend run test:unit -- --reporter=json` + `npm run check` + `./scripts/capture-all-screenshots.sh web`.
* All: scoped to change — never run iOS/Android for backend-only increments (per `AGENTS.md`).

### Cutover re-gate (replaces the duplicated runbook)

1. Restore GitHub minutes; cancel & re-dispatch stuck `workflow_dispatch` run.
2. You: `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail` (browser).
3. Staging `supabase db push --linked` via workflow (not manual) + staging `gh workflow run test.yml`.
4. Staging `scripts/drill-lease-recovery.sh` + staging reconcile → `items_pending==0` after one tick.
5. Prod `supabase db push` dry-run + reviewed migration list (11 → reviewed, no HEAD surprises).
6. Prod `gh workflow run test.yml` (your approval — never auto).
7. Flag `ENABLE_BACKGROUND_PROCESSING=true` only after R5 gate + `/health/ingestion==ok` + `/health/egress` single-digit MB projection + Sentry synthetic + revival row count + 24 h dead-letter 0 + Toni 456→0 with Inbox/Archive, two-SLO-interval liveness.

Rollback rehearsal (R5) is a prerequisite to step 5, not an afterthought.

---

## 6. Reference — what this plan leaves deliberately untouched

* Polling itself (History cursors + per-folder Graph deltas) — correct for "every included folder after watermark" contract; Push/watch would add HTTPS exposure + renewal for no latency gain at 5 min SLO.
* In-process runtime (async monolith) — ownership is in leases, not topology; `selko.worker_app` standalone stays for drills. Separate service deferred until `/health/ingestion` shows sustained pressure.
* LLM-centric extraction, approval→calendar single-owner, permanently-excluded system trees, user-override folder prefs — all out of scope.

---

## 7. Closing — what "done" looks like

Done is not "8 more PRs landed." Done is: `/health/ingestion` counts from SQL and never under-reports past 1k rows; Gmail batch failures retry the right identity, not the wrong chunk; discovery→acquisition latency is tick-independent and egress is still single-digit MB; a lease held through a slow provider page is heartbeated, not lost; the wrong deploy order fails the workflow instead of silently drifting; the rollback rehearsal log is committed next to the checklist; and two drills that start a real runtime, kill it mid-lease, and assert exact-once prove that the core promise — *a worker dying mid-pass loses nothing and duplicates nothing* — is no longer an assertion but an artifact.
