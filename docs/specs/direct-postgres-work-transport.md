# Direct Postgres Work Transport

**Status:** implemented — the direct-pg work transport is complete. The
Aug 6–9 batch's unreachable-code increments (Inc3–Inc5) were finished by the
remediation plan in `direct-pg-completion-and-live-ui-hardening.md` (C1 #279,
C2 #280, C3 #281): the asyncpg session-pooler pool is mandatory at startup,
every trusted-worker coordination call runs over it (no PostgREST twins), and
the LISTEN/NOTIFY WorkListener is live. Inc2's missing semaphore landed in C4
#282, dead code/config was purged in C5 #283.

- **Inc0 (#262) and Inc1 (#263) are real and shipped.** LLM egress metering and
  the payload fixes work.
- **Inc2 (#264) is half-done.** N pollers → 1 claim loop landed; the semaphore
  that was supposed to preserve throughput was never written, so acquisition and
  attachment are now strictly serial and
  `email_acquisition_concurrency` / `email_attachment_concurrency` are read
  nowhere outside `config.py`.
- **Inc3 (#265), Inc4 (#266–#267) and Inc5 (#268) are unreachable dead code.**
  `asyncpg` was never added to `pyproject.toml`; `pg_pool` is never passed to
  `WorkerPool`, `IngestionRuntime` or `EmailIngestionRepository`; the seven
  `*_via_pool` methods have zero callers; `WorkListener.start()` is a stub that
  sets `_connected = True` and returns, and the class is never instantiated.
  **No query has ever run over asyncpg and nothing has ever issued `LISTEN`.**
  The `pg_notify` triggers from `20260809000002` fire into an empty channel.
- **Inc6 (#269) shipped** as a health field plus a test.

The measured egress improvement (929 → 96 MB/day) came entirely from arch A plus
increments 0–1. Every worker database call still crosses PostgREST at ~1,690 B,
so the 373 MB/mailbox/month curve in §1.3 is **unchanged**.

Completion is planned in
[`direct-pg-completion-and-live-ui-hardening.md`](direct-pg-completion-and-live-ui-hardening.md)
(increments C1–C3). Do not start from this document's increment list — start
from that one.

Supersedes the "target shape" section of [`egress-and-work-scheduling.md`](egress-and-work-scheduling.md),
which fixed poll *frequency*. This fixes poll *existence* and per-call *cost*.

**There are no open questions in this document.** Every question raised during
investigation is resolved in §6 with either a measurement or a recorded decision. If you hit
something undecided while implementing, that is a defect in this spec — fix the spec first.

---

## 1. The measured problem

Two platform quota alerts arrived in the same week. They are the **same bytes billed twice**:
a worker→Supabase round trip is outbound bandwidth to Render and egress to Supabase. Both
allowances are **5 GB/month**.

| Platform | Plan | Allowance | State on 2026-08-09 |
|---|---|---|---|
| Supabase (org `vuwnwheqmjulotrwrpyw`, covers prod **and** staging) | Free | 5 GB egress | **6.214 GB (124%)**, cycle 22 Jul – 22 Aug; projects restricted 06 Sep if the next cycle also exceeds |
| Render (team `tea-d5qftkp5pdvs7395ii80`) | Hobby | 5 GB bandwidth | ~5.9 GB month-to-date; overage auto-billed at $15/100 GB |

### 1.1 What the bandwidth graph shows

`bandwidth_usage` for `srv-d5snitkoud1c73adbkl0` (`selko-app-production`), hourly:

```
Aug 1 00:00 – Aug 6 22:00   38.7 MB/h, flat, ±0.5 across 142 consecutive hours
Aug 6 23:00                  8.3 MB/h        ← egress arch A deploys
Aug 7 00:00 – 02:00          ~0              ← restart
Aug 7 03:00 / 06:00          49.7 / 73.8     ← LLM backlog drain (756 calls that day)
Aug 7 07:00 – present         3.9–4.1 MB/h, flat
```

The prior architecture cost **929 MB/day**; the current one costs **96 MB/day**. The six days
before the fix consumed the entire monthly Render allowance on their own.

A flat line with no diurnal shape is the diagnosis: that is a machine talking to itself, and
its amplitude is the poll rate. Nothing about it tracks users.

### 1.2 Why the remaining 96 MB/day is still wrong

Live `GET /health/egress` on `api.selkoapp.com` (process uptime 3,079 s):

```
supabase: 1,234 calls · 2,269,668 bytes   →  ~1,690 bytes per call
```

An empty `claim_approved_event` returns `null`. **Two bytes of information cost 1,690 bytes on
the wire.** The envelope is the payload:

- service-role JWT is 219 characters and is sent **twice** per request (`apikey` **and**
  `Authorization: Bearer`)
- PostgREST request headers + Supabase gateway response headers
- ~99.9% envelope, ~0.1% information

This is a **transport mismatch**. PostgREST-over-HTTPS exists to let untrusted clients reach
Postgres safely through RLS. The backend holds the service-role key and bypasses RLS anyway;
it is paying the full cost of a security model it does not use.

### 1.3 How it scales

| Class | Share of calls | Cost | Scales with |
|---|---|---|---|
| **Fixed chatter** — `claim_approved_event`, `claim_unprocessed_email`, `claim_integration_recovery`, `refresh_waiting_calendar_recoveries`, `claim_email_ingestion_item ×2`, `claim_email_attachment ×2` | 67% | **1.18 GB/month** | nothing — identical at zero users |
| **Per-mailbox** — discovery, heartbeats, folder GET+upsert, `upsert_discovered_email_items`, `complete_email_sync` | 33% | **373 MB/month per mailbox** | linearly with connected mailboxes |

| Mailboxes | Egress/month (idle, before any mail is processed) |
|---|---|
| 2 (today) | 1.9 GB |
| **12** | **~5.0 GB — both allowances exhausted** |
| 50 | 19.8 GB |
| 500 | 187 GB |

**Twelve mailboxes doing nothing exhausts both 5 GB budgets.** For calibration: the entire
production dataset is ~100 MB (32 MB database + 70 MB Storage). The current billing cycle
egressed **55× the whole corpus**.

The cost is `poll_rate × mailboxes`, a quantity with no relationship to value delivered.

### 1.4 A blind spot in our own meter

`selko/services/egress.py` defines four destination constants. `record_egress` is called in
exactly four places — `auth.py` (supabase), `gmail.py` + `attachments.py` (gmail),
`msgraph.py` (graph).

**`LLM = "llm"` is defined and never used.** Every byte shipped to Gemini — email bodies,
PDFs, images up to 6.5 MB — is invisible.

This reconciles the books: the meter reports 2.88 MB/h; Render measures 3.9–4.1 MB/h. The
~30% gap is consistent with LLM payloads, and with the Aug 7 06:00 spike to 73.8 MB on a
756-LLM-call day that the meter barely registered.

**The blind spot is exactly where the largest payloads are, and it is the one that grows
fastest with users.** Increment 0 closes it, because nothing later can be verified without it.

---

## 2. Orientation for the implementer

Read this before touching code. It will save you a day.

### 2.1 The seam already exists

You do **not** need to rewrite 27 call sites. Worker database access is already funnelled
through two narrow places:

| Layer | File | What it owns |
|---|---|---|
| `EmailIngestionRepository` | `backend/selko/services/email_ingestion.py:210` | Every v2 coordination RPC — `claim_due_email_sync`, `heartbeat_email_sync`, `upsert_discovered_email_items`, `complete_email_sync`, `claim_email_ingestion_item`, `claim_email_attachment`, `save_email_with_attachment_descriptors`, and the rest. ~15 methods, each a thin `self.client.rpc(name, args).execute()` |
| Loose service functions | `selko/services/{events,emails,integrations,calendars}.py` | `claim_approved_event`, `claim_unprocessed_email`, `claim_integration_recovery`, `refresh_waiting_calendar_recoveries` |

Increment 4 changes the **inside** of these methods. Callers keep their signatures. This is
why the port is a few days and not a few weeks.

### 2.2 Who starts the workers

`backend/selko/api/app.py:71` — the FastAPI `lifespan`. Guarded by
`config.enable_background_processing`. It constructs `WorkerPool` (line 108) and
`IngestionRuntime` (line 134). Your connection pool and listener are created here, before
either, and closed after both.

### 2.3 What must not change

Web, iOS, Android and every RLS-scoped API route keep using PostgREST with the **user's** JWT.
This spec touches the **trusted-worker path only**. If you find yourself editing
`frontend/`, `ios/`, or `android/`, stop — you are out of scope.

### 2.4 Vocabulary

- **Session mode (port 5432)** — Supavisor keeps one Postgres backend per client connection
  for the connection's whole life. Supports `LISTEN/NOTIFY`, prepared statements, `SET`.
- **Transaction mode (port 6543)** — Supavisor hands a backend to a client only for the
  duration of a transaction. **Breaks `LISTEN/NOTIFY`.** We never use this.
- **`NOTIFY`** — a Postgres message sent on commit to whoever is currently `LISTEN`ing. It is
  a wake-up hint, **not a queue**. Nobody listening means the message is gone.

---

## 3. Target design

**Rule: the backend does not ask whether there is work. It is told.**

1. **One persistent asyncpg connection pool** from the API process to Postgres via the
   **Supavisor session pooler (port 5432)**. One TLS handshake per connection lifetime; no
   JWT per call; no HTTP headers. A claim costs its actual bytes.
2. **One dedicated `LISTEN` connection**, separate from the pool. Triggers `pg_notify` on the
   work tables. The scheduler waits on an `asyncio.Event` fed by the listener.
3. **A slow safety-net poll — kept deliberately.** `NOTIFY` is not durable. Work durability
   stays where it already is (rows + leases + `FOR UPDATE SKIP LOCKED`); the notification is
   only a wake hint. A 5-minute floor poll turns a missed notification into latency, never
   into lost work.
4. **The existing in-process nudge stays**, unchanged, as the fastest path for
   approve / `request_email_sync_now`.

Idle egress becomes TCP keepalives. Steady-state cost becomes proportional to mail actually
processed — `O(work)`, not `O(mailboxes × poll_rate)`.

### 3.1 Why one notification survives a 100-row batch

`upsert_discovered_email_items` inserts up to 100 rows per call. A naive row-level trigger
would fire 100 notifications.

It does not, and you can rely on this: **Postgres collapses duplicate `(channel, payload)`
pairs signalled within the same transaction into a single delivery.** A row-level `AFTER`
trigger emitting a constant payload therefore yields exactly one notification per transaction,
however many rows it touched. This is why §Appendix A uses row-level triggers with `WHEN`
clauses rather than statement-level triggers (which cannot inspect row values).

### 3.2 Alternatives considered and rejected

**Consolidated claim RPC** (one PostgREST call per tick instead of eight). ~80% of the fixed
chatter for ~1 day. Rejected as the destination: every call stays at 1,690 bytes, so the
**373 MB/mailbox/month** curve is untouched — it fixes the constant, not the shape. Also
throwaway once `LISTEN` lands.

**Supabase Realtime Broadcast** as the wake signal. Attractive: `0 / 2,000,000` messages used,
the mechanism is already designed in [`live-ui-updates.md`](live-ui-updates.md), no pooler or
asyncpg needed. Rejected because it only fixes *idle wake-up*. The real work — discovery,
heartbeats, folder upserts, status writes — still crosses PostgREST at 1,690 bytes/call, and
that work is what drives the per-mailbox cost. Broadcast remains correct for the **client**
live-update spec; it is not correct here.

**Pay and move on.** Supabase Pro is $25/mo and lifts egress to 250 GB. Worth doing
*alongside* (see §6, D1) — but at 373 MB/mailbox/month it re-hits the ceiling around 600
mailboxes. It changes the deadline, not the defect.

---

## 4. Platform constraints

Researched 2026-08-09 against the plan tiers actually in use: Supabase **Free**, Render
**Hobby**.

### 4.1 Cleared

| Question | Finding | Source |
|---|---|---|
| Session mode on Free? | Supavisor session mode (**port 5432**) is available on **all plans**, **IPv4-only on every tier** | [Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres) |
| `LISTEN/NOTIFY` through it? | **Yes in session mode.** Explicitly **not** in transaction mode | [Supavisor FAQ](https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI), [supavisor#85](https://github.com/supabase/supavisor/issues/85) |
| Connection limits? | Free/Nano: **60 direct, 200 pooler clients**. We need 2–5 | [Compute and disk](https://supabase.com/docs/guides/platform/compute-and-disk) |
| Render Hobby long-lived outbound TCP? | Allowed. IPv6 unnecessary — the shared pooler is IPv4 | — |
| The reported asyncpg/session-pooler failure? | Reproduces only at **>100 concurrent connections**. We need single digits | [supabase#39227](https://github.com/supabase/supabase/issues/39227) |

### 4.2 Hazards — each has a named mitigation and a test

| # | Hazard | Consequence if missed | Mitigation | Test |
|---|---|---|---|---|
| **H1** | Port **6543** (transaction mode) silently breaks `LISTEN` | System looks healthy, never receives a notification, silently degrades to the safety poll. The entire project delivers nothing and nothing errors | `assert_session_mode_url()` at startup; refuse to boot on any port but 5432 | unit: 6543 URL raises; 5432 passes |
| **H2** | `NOTIFY` is not durable | Work stranded until a human notices | Safety-net poll is **mandatory**. `WORKER_SAFETY_POLL_SECONDS` has a hard floor of 60 s and no "disable" value | integration: kill listener, insert work, assert processed within the floor |
| **H3** | Idle TCP dropped by NAT/LB (~350 s is a common idle timeout); asyncpg sets **no** socket keepalives by default | Listener goes deaf on a socket that still looks open. **Worst failure mode in this design** | TCP keepalives at 60 s (below any known timeout) **plus** an application heartbeat that self-`NOTIFY`s and asserts receipt; reconnect with backoff on miss | integration: drop the connection underneath the listener, assert reconnect and delivery resumes |
| **H4** | `db.*.supabase.co` is **IPv6-only** without the paid IPv4 add-on | Connection refused from Render | Use the pooler hostname only; `assert_session_mode_url()` also rejects a `db.*.supabase.co` host | unit: direct host raises |
| **H5** | The database password is a **new secret**, distinct from `SUPABASE_SERVICE_ROLE_KEY` | Another credential to manage and rotate | Add `SUPABASE_DB_URL` to `.env.example` and all three env files. Never log it; `__repr__` must redact. **Never seed a production URL into staging or development** (environment-separation rule, `CLAUDE.md`) | unit: repr/log redaction |

### 4.3 Accepted and documented

- **Egress is still counted.** Shared-pooler traffic bills as *Shared Pooler Egress* —
  Supabase avoids double-counting Database→Pooler and Pooler→Client, but it is not free. The
  win is volume (~100 B/call vs ~1,690 B/call), not exemption.
  ([Manage Egress usage](https://supabase.com/docs/guides/platform/manage-your-usage/egress))
- **Cross-region.** Render is **Oregon**; production Supabase is **us-east-1** (staging is
  **us-west-2**). ~70 ms RTT. Persistent connections make this cheaper than today. See §6 D4.
- **RLS is bypassed.** A pooler connection as the `postgres` role bypasses RLS — the same
  posture as the service-role key today. No new exposure. State it in the `pg.py` docstring
  so it is not rediscovered as a surprise.

---

## 5. Relationship to the cheaper options

### Prerequisite — do first, it is the same refactor

**Collapse `IngestionRuntime`'s N pollers into 1 claim loop + N executors.**
`email_acquisition_concurrency=2` and `email_attachment_concurrency=2` each spawn a worker
owning its own idle poll loop — visible in the meter as `claim_email_ingestion_item ×2` and
`claim_email_attachment ×2`. `WorkerPool` already got this fix (egress inc 3);
`IngestionRuntime` never did. Concurrency must multiply **executors**, never **pollers**.
This is the exact shape `LISTEN` needs. Increment 2.

### Independent — this work does not cover them

These reduce **payload**, which a cheaper transport does not touch. Two also cut **Gmail/Graph**
egress, which this project never addresses. Increment 1.

- **Folder discovery hourly, not every 5 minutes.** Currently `GET email_folders` →
  `select("*")` of 39 rows → upsert all 39 back, per mailbox, per poll.
  `POST /rest/v1/email_folders` is the priciest operation in the meter at **10.25 KB/call**.
- **Drop `emails.body_html`.** Read once, in memory at ingest, for linked-image extraction
  (`emails.py:359`). Nothing ever reads it back — yet it rides on every claim, re-fetch and
  status update.
- **Kill the double body fetch.** `claim_unprocessed_email` is `RETURNS SETOF public.emails`
  and returns the complete row; `process_email_for_events` then calls
  `fetch_email_with_attachments`, which re-`select("*")`s the same email
  (`event_processing.py:376`).

### Subsumed — do **not** build these

- **`Prefer: return=minimal` on worker writes.** Meaningful only on PostgREST; over asyncpg
  you omit `RETURNING`. (Still applies to client-facing writes that stay on PostgREST —
  currently only `integrations.py:842` uses it.)
- **A consolidated multi-claim RPC.** Throwaway once the scheduler waits on `LISTEN`.
- **Interval-gating the recovery probes.** `LISTEN` removes the probe entirely.

---

## 6. Decisions (formerly open questions)

**D1 — Buy Supabase Pro before starting? Yes, recommended; the plan does not depend on it.**
$25/mo, egress 5 → 250 GB, covers both projects in the org. It removes the 06 Sep restriction
risk so this work is done deliberately rather than against a deadline. *If it is not bought,*
increments 0–2 become time-critical: they must be deployed before the 22 Aug cycle rollover,
since increments 0–2 alone are projected to land the next cycle near 1.2–1.5 GB against the
5 GB cap.

**D2 — Does `selko-app-staging` contribute measurable bandwidth? No. Measured, resolved.**
`bandwidth_usage` for `srv-d5sng4coud1c73ad9op0`, 7–9 Aug: 0.018–0.093 MB/hour, with most
hours reporting no data at all (Render free plan spins the service down). Under 0.5 MB across
three days — noise against prod's 96 MB/day. **Production is the only Render bandwidth
consumer that matters. Do not spend time on staging.**

**D3 — Multi-instance? Out of scope. `numInstances` stays 1.** `LISTEN` is strictly better
than the in-process nudge if that ever changes — every instance receives the notification
rather than only the local one. But claim contention at N>1 has never been exercised, so it
is not claimed as supported. Increment 5 adds one test asserting two concurrent listeners do
not double-process (`FOR UPDATE SKIP LOCKED` already guarantees this; the test records it).
**Do not add instances as part of this work.**

**D4 — Fix the Oregon ↔ us-east-1 split while touching connection setup? No.** Moving a
region means re-provisioning a project and migrating data — vastly larger and riskier than
this work, with a benefit (~70 ms) that persistent connections largely absorb. Recorded here
so it is not silently reconsidered mid-implementation. Revisit only if latency becomes a
user-visible complaint.

**D5 — Purge `scheduled_tasks`? Yes: delete the rows, keep the table.** 2,877 rows of
`email_fetch` (2,074 failed) from an architecture that no longer exists. Verified the table is
reachable only through `workers/photo_fetch.py`, which is parked. The table and
`services/scheduled_tasks.py` **stay** — the photos schema is deliberately retained per
`docs/specs/photo-ingestion-parked` — but the dead rows go. Folded into increment 1 as a
one-off migration. It is not an egress fix; it removes a trap for the next reader of the
schema.

---

## 7. Increments

Each is independently shippable and independently revertable. **0–2 are worth doing even if
3–6 are never started.** Every increment follows the worktree + PR workflow in `CLAUDE.md`.

---

### Increment 0 — Close the LLM metering blind spot

**Goal:** every later measurement becomes trustworthy.

**Files:** `backend/selko/services/llm_provider.py` (the HTTP call path),
`backend/selko/services/egress.py` (no change — `LLM` already exists).

**Change:** at the provider request/response boundary, call
`record_egress(LLM, f"{provider}:{operation}", request_bytes=…, response_bytes=…)`. Use the
serialized request body length and the response body length. Operation names must stay
bounded — use the provider and model family, never a per-request identifier.

**Tests:** unit — a mocked provider call records a non-zero `llm` entry; operation name
contains no identifiers.

**DoD:** `GET /health/egress` shows an `llm` destination under `by_destination`. Backend unit
tests pass.

**Rollback:** revert the PR. Metering only; no behaviour change.

---

### Increment 1 — Payload fixes (independent of transport)

**Goal:** −40–50% of current egress; also reduces Gmail/Graph calls.

**Files:**
- `backend/selko/workers/email_ingestion.py:262` (`_discover_gmail`), `:431`
  (`_discover_outlook`)
- `backend/selko/services/email_folders.py:85` (`upsert_discovered_folders`)
- `backend/selko/services/event_processing.py:355` (`fetch_email_with_attachments`)
- `backend/selko/services/events.py:470` (`process_email_for_events`)
- `backend/selko/config.py`
- new migrations under `supabase/migrations/`

**Changes:**

1. **Folder cadence.** Add `EMAIL_FOLDER_REFRESH_SECONDS` (default `3600`). In both discovery
   paths, skip the folder listing + `upsert_discovered_folders` when
   `email_sync_state.folders_refreshed_at` is newer than the interval. Add that column in a
   migration. A user-initiated folder-settings change must force a refresh — wire it to the
   same nudge path as `request_email_sync_now`.
2. **Pass the claimed row through.** `process_email_for_events` currently takes `email_id` and
   re-fetches. Add an optional `email: dict | None = None` parameter; when supplied, hand it
   to `fetch_email_with_attachments` so it skips its `select("*")` and only fetches
   attachments. `workers/email_process.py` already has the claimed row — pass it.
3. **Drop `body_html`.** Migration: `ALTER TABLE public.emails DROP COLUMN body_html;`. Remove
   the write in `services/emails.py:232`. The in-memory extraction at `emails.py:356–381` is
   unaffected — it reads the parsed payload, not the column. Verify no client reads it
   (already confirmed: no hits in `frontend/`, `ios/`, `android/`).
4. **Purge dead rows** (D5): `DELETE FROM public.scheduled_tasks WHERE task_type =
   'email_fetch';` in its own migration, with the row count recorded in the PR body.

**Tests:** regression test per fix, in the module fixed (`CLAUDE.md` requires this):
folder refresh is skipped inside the interval and forced outside it; `process_email_for_events`
issues no email `select` when handed a row; no code path references `body_html`.

**DoD:** backend unit tests pass. Migrations applied to staging first, row counts recorded.
`GET /health/egress` shows `POST /rest/v1/email_folders` calls/minute dropped ~12×.

**Rollback:** the `body_html` drop is **not** reversible from data. Take a column backup
(`CREATE TABLE emails_body_html_backup AS SELECT id, body_html FROM emails;`) in the same
migration, and drop that backup table in a follow-up only after one clean week.

---

### Increment 2 — `IngestionRuntime`: N pollers → 1 claim loop + N executors

**Goal:** remove the `×2` multipliers. Prerequisite for increment 5.

**Files:** `backend/selko/workers/ingestion_runtime.py:122` (`start`),
`backend/selko/workers/email_ingestion.py` (`acquisition_loop`, `attachment_loop`).

**Change:** mirror what `WorkerPool` already does (`workers/pool.py:232`, `_scheduler_loop`).
Spawn **one** acquisition claim loop and **one** attachment claim loop. Each drains: claim,
dispatch the work to a task behind an `asyncio.Semaphore` sized by the existing
`email_acquisition_concurrency` / `email_attachment_concurrency`, re-claim immediately, and
sleep only when a claim returns empty. Keep the config names — they now mean executor width,
and their docstrings in `config.py:121–125` must be corrected to say so.

**Tests:** unit — with concurrency 4 and 10 available items, assert exactly one claim loop
exists, at most 4 items are in flight, and all 10 complete. Assert idle polling issues one
claim per tick, not N.

**DoD:** backend unit tests pass. `GET /health/egress` shows
`claim_email_ingestion_item` and `claim_email_attachment` at half their prior calls/minute.

**Rollback:** revert the PR; leases make partial processing safe.

---

### Increment 3 — Connection pool, no behaviour change

**Goal:** prove the transport in production on exactly one query.

**Files:** `backend/selko/services/pg.py` (new), `backend/selko/config.py`,
`backend/selko/api/app.py`, `pyproject.toml`, `.env.example`, `.env`, `.env.test`,
`.env.production`, `backend/selko/api/routes/health.py`.

**Add dependency:** `asyncpg` (none of `asyncpg`, `psycopg`, `sqlalchemy` is currently a
dependency — this is genuinely new).

**New config** (`config.py`, all via `getenv` with the defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `SUPABASE_DB_URL` | *(none — required when background processing is on)* | Session-pooler URI |
| `PG_POOL_MIN_SIZE` | `1` | asyncpg pool floor |
| `PG_POOL_MAX_SIZE` | `4` | asyncpg pool ceiling (limit is 200; 4 is ample) |
| `PG_KEEPALIVE_SECONDS` | `60` | TCP keepalive idle (H3) |
| `PG_CONNECT_TIMEOUT_SECONDS` | `10` | fail fast on a bad URL |

**Where to get the URL:** Supabase Dashboard → project → **Connect** → **Session pooler**.
Copy it verbatim. It is a `*.pooler.supabase.com` host on port **5432**. Do **not** use the
"Direct connection" string (`db.*.supabase.co`, IPv6-only — H4) and do **not** use the
"Transaction pooler" string (port 6543 — H1).

**`pg.py` contract:**

```python
def assert_session_mode_url(url: str) -> None:
    """Refuse anything that cannot carry LISTEN/NOTIFY (H1, H4).

    Raises ConfigurationError when the port is not 5432 or the host is a
    direct db.*.supabase.co endpoint. Never includes the password in the
    message.
    """

async def create_pool(config: Config) -> asyncpg.Pool:
    """Session-pooler pool with TCP keepalives and statement cache disabled.

    statement_cache_size=0 is set even though session mode supports prepared
    statements: it costs nothing here and makes a future misconfiguration to
    transaction mode fail loudly rather than intermittently.
    """
```

**Wiring:** in `app.py` `lifespan`, inside the `config.enable_background_processing` branch
(line 96), create the pool **before** `WorkerPool` and `IngestionRuntime`, and close it after
both stop. If `SUPABASE_DB_URL` is unset while background processing is on, **fail startup** —
do not silently fall back to PostgREST.

**Canary:** port exactly one read — `health_dead_letter_counts` in
`ingestion_runtime.health_snapshot()` — to the pool. Everything else stays on PostgREST.

**Tests:** unit — `assert_session_mode_url` accepts 5432, rejects 6543 and `db.*.supabase.co`;
password never appears in the raised message. Integration (local Supabase) — pool connects and
the canary query returns the same shape as the RPC did.

**DoD:** backend unit tests pass. `/health/ingestion` returns identical output to before.
`/health/egress` shows one fewer supabase RPC per health cycle.

**Rollback:** revert the PR. Nothing else depends on the pool yet.

---

### Increment 4 — Port the claim/complete/heartbeat paths

**Goal:** per-call cost 1,690 B → ~100 B.

**Files:** `backend/selko/services/email_ingestion.py` (`EmailIngestionRepository`),
`backend/selko/services/events.py`, `emails.py`, `integrations.py`, `calendars.py`.

**Change:** inside each method, replace `self.client.rpc(name, args).execute()` with
`await pool.fetch("select * from public.<name>($1, $2)", …)`. **The SQL functions do not
change** — they are already `SECURITY DEFINER` and already do the locking. You are changing
only how they are invoked.

Port in this order, one PR per group, verifying `/health/egress` between:

1. `claim_approved_event`, `claim_unprocessed_email`
2. `claim_email_ingestion_item`, `claim_email_attachment`, `complete_item`, `fail_item`
3. `claim_due_email_sync`, `claim_due_email_reconciliation`, `heartbeat_email_sync`,
   `complete_email_sync`
4. `claim_integration_recovery`, `refresh_waiting_calendar_recoveries`
5. `upsert_discovered_email_items`, `save_email_with_attachment_descriptors`

**Async note:** `EmailIngestionRepository` methods are currently synchronous and called from
`asyncio.to_thread(...)` in `email_ingestion.py:172`. Make the ported methods `async` and
remove the `to_thread` wrapper for those paths — asyncpg is natively async and wrapping it in
a thread would be strictly worse. Paths still on PostgREST keep their `to_thread`.

**Tests:** every ported method keeps its existing unit test, with the mock changed from a
Supabase client to an asyncpg pool. Add one integration test per group against local Supabase
asserting the ported call returns the same shape as the RPC.

**DoD:** backend unit + integration tests pass. `/health/egress` `supabase` bytes-per-call
drops from ~1,690 to ~100–200 for the ported operations.

**Rollback:** each group is its own PR; revert individually. Leases make a mid-flight revert
safe.

---

### Increment 5 — `NOTIFY` triggers and the listener

**Goal:** idle egress → keepalives.

**Files:** new migration (Appendix A), `backend/selko/services/pg.py` (`WorkListener`),
`backend/selko/workers/pool.py`, `backend/selko/workers/ingestion_runtime.py`,
`backend/selko/config.py`.

**New config:**

| Variable | Default | Purpose |
|---|---|---|
| `WORKER_SAFETY_POLL_SECONDS` | `300` | Floor poll (H2). Hard-clamped to ≥ 60; there is no disable value |
| `PG_LISTENER_HEARTBEAT_SECONDS` | `120` | Self-`NOTIFY` liveness probe (H3) |

**`WorkListener` contract:**

```python
class WorkListener:
    """Dedicated LISTEN connection feeding asyncio.Events per work type.

    Owns its own connection, NOT a pool member — a pool connection could be
    handed to a query and lose its LISTEN registration.

    Liveness (H3): every PG_LISTENER_HEARTBEAT_SECONDS it emits a self-NOTIFY
    on the 'selko_heartbeat' channel and asserts receipt within 10s. A miss
    means the socket is dead-but-open; the connection is torn down and
    reconnected with exponential backoff (1s, 2s, 4s … capped at 60s).
    Reconnect always re-issues LISTEN before declaring itself healthy.
    """
    def event_for(self, work_type: str) -> asyncio.Event: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> dict:  # {connected, reconnects, last_notification_at}
```

**Scheduler change:** `WorkerPool._scheduler_loop` (`pool.py:232`) currently waits on
`self._nudge_event` with `timeout=self._tick_seconds()`. Change it to wait on *either* the
nudge event *or* the listener's event, with `timeout=WORKER_SAFETY_POLL_SECONDS`. Apply the
same change to the two `IngestionRuntime` claim loops from increment 2. The 5-second tick
floor from R3 is removed — it exists to prevent a busy-wait that no longer exists.

**Observability:** add `listener` to `/health/ingestion` — `{connected, reconnects,
last_notification_at}`. A listener disconnected for more than two heartbeat intervals sets
status `degraded`.

**Tests:**
- integration: insert an approved event, assert the scheduler wakes in <1 s without a tick
- integration (**H2**): stop the listener, insert work, assert it is processed within
  `WORKER_SAFETY_POLL_SECONDS`
- integration (**H3**): terminate the listener's backend server-side
  (`pg_terminate_backend`), assert reconnect and that notifications resume
- integration (**D3**): two listeners, one insert, assert exactly one processes it
- unit: batch of 100 rows in one transaction produces exactly one wake (§3.1)

**DoD:** all above pass. `/health/egress` idle `calls_per_second` drops from ~0.49 to under
0.02. Deploy order: **migration first, code second** — triggers are inert until a listener
exists, so this is safe in both directions.

**Rollback:** revert the code PR; the triggers become inert `pg_notify` calls with no listener
(negligible cost) and the safety poll carries the load. Drop the triggers in a follow-up only
if the approach is abandoned.

---

### Increment 6 — Budget enforcement

**Goal:** stop the regression recurring.

**Files:** `backend/selko/api/routes/health.py`, `backend/tests/`, `CLAUDE.md`.

**Changes:**

1. Add `bytes_per_mailbox_per_day` to the `/health/egress` payload — total supabase bytes
   divided by uptime and by the count of active email integrations.
2. A test asserting the **fixed** (mailbox-independent) idle rate stays under a documented
   ceiling, so a new unconditional poll fails CI rather than a billing cycle.
3. **Replace the architecture rule in `CLAUDE.md`.** Today it reads *"Idle worker loops must
   back off geometrically … a flat idle tick is a standing egress leak."* Geometric backoff
   legitimises the defect. Replace with: **"Idle loops must not exist. Work arrives by
   notification; the safety-net poll is a floor, not a schedule. Any new unconditional
   periodic database call must be justified in the PR body against
   `docs/specs/direct-postgres-work-transport.md`."**

**DoD:** the budget test fails when an unconditional poll is added (verify by adding one
temporarily). `CLAUDE.md` updated.

---

## 8. Verification

Egress claims are credible only when measured. For every increment:

1. **`GET https://api.selkoapp.com/health/egress`** before and after. Counters are
   process-local and reset on deploy — compare at **matched uptime**, not wall-clock.
2. **Render `bandwidth_usage`** at hourly resolution for `srv-d5snitkoud1c73adbkl0`. This is
   the honest external number and it produced §1.1. Expect the flat line to drop and then to
   *stop being flat* — after increment 5 the graph should track mail volume. **That change of
   shape, not the level, is the proof.**
3. **Supabase usage dashboard**, per project, per billing cycle.

**Exit criteria:**

| Metric | Today | Target |
|---|---|---|
| Idle egress, 2 mailboxes | 96 MB/day | **< 10 MB/day** |
| Marginal cost per mailbox | 373 MB/month | **< 20 MB/month** |
| Idle `calls_per_second` | 0.49 | **< 0.02** |
| Bytes per claim call | ~1,690 | **< 200** |

---

## Appendix A — Notification migration

One channel, one constant payload per work type, row-level `AFTER` triggers with `WHEN`
clauses. Duplicate `(channel, payload)` pairs collapse per transaction (§3.1), so a 100-row
batch yields one notification.

```sql
CREATE OR REPLACE FUNCTION public.notify_work_available()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    -- TG_ARGV[0] is the work type, e.g. 'email_pending'. Constant per trigger,
    -- so Postgres collapses duplicates within one transaction.
    PERFORM pg_notify('selko_work', TG_ARGV[0]);
    RETURN NULL;  -- AFTER trigger; return value is ignored
END; $$;

CREATE TRIGGER emails_notify_pending
    AFTER INSERT OR UPDATE OF processing_status ON public.emails
    FOR EACH ROW WHEN (NEW.processing_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('email_pending');

CREATE TRIGGER events_notify_approved
    AFTER INSERT OR UPDATE OF status ON public.events
    FOR EACH ROW WHEN (NEW.status = 'approved')
    EXECUTE FUNCTION public.notify_work_available('event_approved');

CREATE TRIGGER items_notify_pending
    AFTER INSERT OR UPDATE OF acquisition_status ON public.email_ingestion_items
    FOR EACH ROW WHEN (NEW.acquisition_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('item_pending');

CREATE TRIGGER attachments_notify_pending
    AFTER INSERT OR UPDATE OF ingestion_status ON public.attachments
    FOR EACH ROW WHEN (NEW.ingestion_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('attachment_pending');
```

`email_sync_state` is **deliberately excluded**: its due-ness is time-based
(`next_poll_at`), not state-based, so there is no insert or update to hang a trigger on. The
coordinator's due-sync claim is the one loop that legitimately remains time-driven — at the
safety-poll interval, not the current 30 s.

Verify the column names against `docs/database-schema.md` before writing the migration; the
enum values above are taken from `20260801000001_polling_email_ingestion_v2.sql` and
`claim_unprocessed_email`.

## Appendix B — New environment variables

Add to `.env.example`, `.env`, `.env.test`, `.env.production`, and Render env for
`selko-app-production`. `SUPABASE_DB_URL` is a **secret** — treat it like
`SUPABASE_SERVICE_ROLE_KEY`, and never copy a production value into a lower environment.

```
SUPABASE_DB_URL=postgresql://…@…pooler.supabase.com:5432/postgres
PG_POOL_MIN_SIZE=1
PG_POOL_MAX_SIZE=4
PG_KEEPALIVE_SECONDS=60
PG_CONNECT_TIMEOUT_SECONDS=10
PG_LISTENER_HEARTBEAT_SECONDS=120
WORKER_SAFETY_POLL_SECONDS=300
EMAIL_FOLDER_REFRESH_SECONDS=3600
```
