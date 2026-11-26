# 05 — Data conversion, import tool, cutover, rollback, risks (Q7)

> **Done and removed.** The cutover ran on 2026-11-25 (T+0 22:00 UTC,
> `docs/deploy-log/2026-11-25-35f62d57.md`). The importer (`selko_import/`, the
> `importer` Dockerfile target) was deleted from the tree afterwards; the signed
> `ghcr.io/tonimelisma/selko-import:35f62d57` remains in the registry, and the
> database it made from the Postgres fixture is kept as
> `backend/tests/fixtures/imported_from_postgres.sql`. The rest of this file is
> the historical record of how it worked.

Part of the plan for `docs/specs/sqlite-single-process.md`. This file covers
increment Q7 (cutover) and the import tool it needs. The source schema was
read from the repository and the local stack on 2026-11-25 (all 120 Postgres
migrations applied, PostgreSQL 17.6). Anything that can only be measured in
production is marked **UNKNOWN:** with the way to find it out.

**Reconciled with the code on 2026-11-25 (after #425).** Where the plan and
the code differ, this file now describes the code; a planned feature the code
does not have is marked **Not built**. The code: `selko_import/` (`core.py`,
`attachments.py`, `__main__.py`), the importer image
`ghcr.io/tonimelisma/selko-import:<sha>` (Dockerfile target `importer`), and
`selko/db/datalock.py`.

The target host is called **the server**: it pulls the signed image and
verifies it. Nothing in this file describes how it is reached or what else
runs on it. That belongs to the server's own (private) runbook, because this
repository is public.

Owners: **operator** = Toni; **agent** = a Claude session. "On the server"
means whoever holds the server's access, using its own (private) procedure.

---

## A. Data conversion, table by table

### A.1 Conversion rules (one codec, used by the importer and by `selko/db/`)

The live public schema has **30 base tables** (27 carried: `oauth_states`,
`photos` and `scheduled_tasks` are not) and 1 view (`email_sync_health`,
which is recreated by `0001_initial.sql` and carries no data). Their 440 columns
use 13 Postgres types. Each type has exactly one conversion:

| Code | Postgres | SQLite (STRICT) | Value written | Source-side checksum cell (SQL on Postgres) | Target-side cell (SQL on SQLite) |
|---|---|---|---|---|---|
| U | `uuid` | `TEXT` | canonical lowercase 36-char form, `str(uuid.UUID)` | `col::text` | `col` |
| T | `timestamptz` | `TEXT` | UTC, **fixed 27 chars**: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (always 6 fractional digits, always `Z`), i.e. `dt.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.%fZ')` | `to_char(col AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')` | `col` |
| D | `date` | `TEXT` | `YYYY-MM-DD` | `to_char(col, 'YYYY-MM-DD')` | `col` |
| H | `time without time zone` | `TEXT` | `HH:MM:SS` (Q0.6 asserts no fractional seconds exist) | `col::text` | `col` |
| X | `text`, `varchar` | `TEXT` | verbatim | `col` | `col` |
| I | `integer`, `bigint` | `INTEGER` | verbatim (64-bit fits both) | `col::text` | `CAST(col AS TEXT)` |
| B | `boolean` | `INTEGER` + `CHECK (col IN (0,1))` | `1`/`0`; NULL stays NULL | `CASE WHEN col THEN '1' ELSE '0' END` | `CAST(col AS TEXT)` |
| J | `jsonb` | `TEXT` + `CHECK (json_valid(col))` | **Postgres's own `jsonb::text` rendering, verbatim** (already normalised: keys de-duplicated and ordered, numbers as written, e.g. `{"a": [1, 2.50], "b": 1}`) | `col::text` | `col` |
| A | `text[]` (5 columns) | `TEXT` + `CHECK (json_valid(col) AND json_type(col) = 'array')` | `to_json(col)::text`, e.g. `["a","b c","é"]` (Q0.6 asserts every array is 1-dimensional) | `to_json(col)::text` | `col` |
| E | enum (`integration_provider`, `integration_status`, `llm_operation_type`) | `TEXT` + `CHECK (col IN (…labels…))` | label text | `col::text` | `col` |
| M | `numeric(10,6)` (only `llm_call_log.estimated_cost_usd`) | `REAL`, same name (decision D6) | `float(value)` | `round(col, 6)::text` | `f"{v:.6f}"` in Python |

The only unconstrained `numeric` columns were `photos.location_latitude/longitude`
(code R). `photos` is no longer carried (§A.3), so no carried column uses R.

There are no `bytea`, `interval`, `inet`, generated or identity columns in
`public`. The 52 CHECK constraints are all validated (`pg_constraint.convalidated`
is true for every one), so every carried row already satisfies the CHECKs that
`0001_initial.sql` ports.

Decisions this table fixes:

- **Timestamps have a fixed width** so that text comparison equals time
  comparison. Leases, `next_retry_at` and `locked_until` are compared in SQL
  this way. `selko/db/` must write the same format everywhere, and **no
  SQLite `DEFAULT` may produce a timestamp**: SQLite's `strftime('%f')`
  gives milliseconds, which would mix two widths in one column. See risk E-2.
- **JSON is carried as Postgres renders it**, not re-serialised by Python.
  This is lossless by construction: no float re-parsing and no key
  reordering. SQLite's JSON functions read it as is.
- **Arrays are carried through the same SQL expression** that the checksum
  uses, so text equality proves the conversion.
- **What is independent and what is not.** The export selects every column
  through the same `CONVERT` expression the checksum uses (`core.py`), so the
  text written and the text hashed on the source side come from one
  expression. The target side reads the stored values back from SQLite and
  hashes them in Python (`_sqlite_cell`, `row_hash`). A mismatch therefore
  catches anything lost or changed between Postgres and the SQLite file
  (truncation, type coercion, a dropped row, a constraint rewriting a value),
  but not a wrong choice in `CONVERT` itself; the per-type expressions above
  are what the code uses.

### A.2 Verification per table (the same formula on both sides)

For every carried table, in a fixed column order (`ordinal_position`):

```
cell(v)  = 'N'                                   if v IS NULL
         = 'S' || length(v) || ':' || v          otherwise   (v = the cell text of A.1; length in characters)
row(r)   = cell(c1) || cell(c2) || … || cell(cn)
h(r)     = first 15 hex digits of sha256(utf8(row(r)))  as an unsigned 60-bit integer
C1(table) = ( count(*),  sum(h) mod 2^64,  bit_xor(h) )
```

This is order-independent (sum and xor). The length prefix makes the
encoding unambiguous: no separator can be forged by content.

Postgres side: a single SQL statement per table, run in the export snapshot
(§B.3). Example (`global_limits`):

```sql
SELECT count(*) AS n, (sum(h::numeric) % 18446744073709551616)::text AS s, bit_xor(h) AS x FROM (
 SELECT ('x'||substr(encode(sha256(convert_to(
   CASE WHEN id IS NULL THEN 'N' ELSE 'S'||length(id::text)||':'||id::text END ||
   CASE WHEN limit_type IS NULL THEN 'N' ELSE 'S'||length(limit_type)||':'||limit_type END ||
   CASE WHEN default_limit IS NULL THEN 'N' ELSE 'S'||length(default_limit::text)||':'||default_limit::text END ||
   CASE WHEN max_allowed IS NULL THEN 'N' ELSE 'S'||length(max_allowed::text)||':'||max_allowed::text END ||
   CASE WHEN is_active IS NULL THEN 'N' ELSE 'S1:'||CASE WHEN is_active THEN '1' ELSE '0' END END ||
   CASE WHEN created_at IS NULL THEN 'N' ELSE 'S27:'||to_char(created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END ||
   CASE WHEN updated_at IS NULL THEN 'N' ELSE 'S27:'||to_char(updated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END
 ,'UTF8')),'hex'),1,15))::bit(60)::bigint AS h FROM public.global_limits) t;
```

SQLite side: every row is read back from the loaded file, each cell rendered
by `_sqlite_cell` (integers as decimal text, `M` as `%.6f`, text verbatim),
and `row_hash`/`fold` computed in Python with the same encoding.
`test_both_sides_hash_identically` asserts the Python hash equals Postgres's
for the same cells.

The importer generates the per-table statement from its **pinned column
map** (§B.2), never from `information_schema` at run time. Schema drift
therefore fails closed (exit 3) instead of being checked against itself.

**C2** (a tolerance check for `photos.location_*`): **not built** and no
longer needed, since `photos` is not carried.

**Structural checks after the load** (`_structural_checks`), all of which must
pass: `PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` returns 0
rows; every T column matches the 27-character form
(`YYYY-MM-DDTHH:MM:SS.ffffffZ`). **Not built:** a `user_version` comparison,
a trigger/index set comparison, and an invariant re-check (the schema is the
image's own migration chain, applied by the same code, so these would compare
it with itself).

### A.3 Per-table conversion

Each table below lists every live column with its Postgres type, its SQLite
type, the conversion code from A.1, and its nullability. Defaults are **not**
applied by the import: every value is carried explicitly, including the ones
a default produced. The order below is alphabetical. The load order is in §B.5.

#### `action_history` (9 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `action_type` | text | TEXT | X | NOT NULL |
| `entity_type` | text | TEXT | X | NOT NULL |
| `entity_id` | uuid | TEXT | U | NOT NULL |
| `previous_state` | jsonb | TEXT | J | yes |
| `new_state` | jsonb | TEXT | J | yes |
| `external_resource_id` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** No module in `backend/selko/` reads or writes it today (grep, 2026-11-25), but it is the only record of earlier undo history and is small. `previous_state`/`new_state` hold prior row content (JSON). Verification: C1 over all 9 columns.

#### `attachments` (17 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `email_id` | uuid | TEXT | U | NOT NULL |
| `provider_attachment_id` | text | TEXT | X | yes |
| `filename` | text | TEXT | X | NOT NULL |
| `mime_type` | text | TEXT | X | yes |
| `size_bytes` | bigint | INTEGER | I | yes |
| `storage_path` | text | TEXT | X | yes |
| `content_hash` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `ingestion_status` | text | TEXT | X | NOT NULL |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `locked_by` | text | TEXT | X | yes |
| `locked_until` | timestamptz | TEXT | T | yes |
| `ingestion_error_code` | text | TEXT | X | yes |

**Carry all rows.** `storage_path` is carried verbatim and is the file's path relative to `/data/attachments/` (§A.4); `content_hash` is the SHA-256 hex of the object bytes (`services/attachments.py:57`) and is what the object copy is verified against. Rows in `processing` with a lease are carried unchanged; the new process expires every lease at startup (spec §4.3). Verification: C1 over all 17 columns, plus the object check of §A.4.

#### `calendar_entries` (24 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `calendar_id` | text | TEXT | X | NOT NULL |
| `provider_event_id` | text | TEXT | X | NOT NULL |
| `ical_uid` | text | TEXT | X | yes |
| `recurring_event_id` | text | TEXT | X | yes |
| `original_start` | text | TEXT | X | NOT NULL |
| `title` | text | TEXT | X | yes |
| `location` | text | TEXT | X | yes |
| `start_at` | timestamptz | TEXT | T | yes |
| `end_at` | timestamptz | TEXT | T | yes |
| `all_day` | boolean | INTEGER | B | NOT NULL |
| `timezone` | text | TEXT | X | yes |
| `status` | text | TEXT | X | NOT NULL |
| `self_response` | text | TEXT | X | yes |
| `etag` | text | TEXT | X | yes |
| `sequence` | integer | INTEGER | I | yes |
| `provider_updated_at` | timestamptz | TEXT | T | yes |
| `origin` | text | TEXT | X | NOT NULL |
| `deleted_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `join_url` | text | TEXT | X | yes |

**Carry all rows.** The mirror of the users' own provider calendars. It could be rebuilt by a full mirror resync, but it is not dropped: `event_identity_hints.calendar_entry_id` references it with `ON DELETE CASCADE`, so dropping it would also drop identity hints, and dedup read-back needs it on the first calendar write after cutover. `original_start` is already `text` (default `''`) and is carried verbatim. Personal data (titles, locations of the user's calendar). Verification: C1 over all 23 columns.

#### `calendar_mirror_state` (18 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `calendar_id` | text | TEXT | X | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `sync_token` | text | TEXT | X | yes |
| `last_full_resync_at` | timestamptz | TEXT | T | yes |
| `window_start` | timestamptz | TEXT | T | NOT NULL |
| `window_end` | timestamptz | TEXT | T | NOT NULL |
| `next_poll_at` | timestamptz | TEXT | T | NOT NULL |
| `lease_owner` | text | TEXT | X | yes |
| `lease_expires_at` | timestamptz | TEXT | T | yes |
| `lease_generation` | bigint | INTEGER | I | NOT NULL |
| `last_started_at` | timestamptz | TEXT | T | yes |
| `last_success_at` | timestamptz | TEXT | T | yes |
| `consecutive_failures` | integer | INTEGER | I | NOT NULL |
| `last_error_code` | text | TEXT | X | yes |
| `last_error_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** `sync_token` is the provider calendar delta cursor; carrying it is what makes the first mirror poll after cutover incremental instead of a full window resync. Lease columns carried, expired at startup. Composite PK `(integration_id, calendar_id)`. Verification: C1 over all 17 columns.

#### `calendar_sync_log` (7 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `google_calendar_event_id` | text | TEXT | X | NOT NULL |
| `action` | text | TEXT | X | NOT NULL |
| `snapshot_synced` | jsonb | TEXT | J | NOT NULL |
| `synced_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** Read by `services/calendars.py:1096` (`snapshot_synced, action, synced_at`) for the undo divergence check; dropping it would make every undo of an earlier write refuse or misjudge divergence. Verification: C1 over all 7 columns.

#### `calendar_work_items` (21 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `action` | text | TEXT | X | NOT NULL |
| `generation` | bigint | INTEGER | I | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `desired_event` | jsonb | TEXT | J | yes |
| `provider_event_id` | text | TEXT | X | yes |
| `expected_provider_revision` | text | TEXT | X | yes |
| `force_overwrite` | boolean | INTEGER | B | NOT NULL |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `locked_by` | text | TEXT | X | yes |
| `locked_until` | timestamptz | TEXT | T | yes |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `failure_code` | text | TEXT | X | yes |
| `failure_detail` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `completed_at` | timestamptz | TEXT | T | yes |
| `provider` | text | TEXT | X | yes |

**Carry all rows.** The single owner of calendar delivery state. Rows in `processing` at the freeze are counted by Q0.8 at the freeze (their provider write may or may not have happened; see risk E-9). `desired_event` is JSON. Verification: C1 over all 21 columns.

#### `email_calendar_components` (14 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `email_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `component_index` | integer | INTEGER | I | NOT NULL |
| `method` | text | TEXT | X | NOT NULL |
| `uid_hash` | text | TEXT | X | yes |
| `recurrence_id` | text | TEXT | X | yes |
| `recurrence_range` | text | TEXT | X | yes |
| `sequence` | integer | INTEGER | I | NOT NULL |
| `dtstamp` | timestamptz | TEXT | T | yes |
| `component_status` | text | TEXT | X | yes |
| `start_datetime` | timestamptz | TEXT | T | yes |
| `end_datetime` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** Parsed iCalendar parts; `uid_hash` is a hash, content-free. Verification: C1 over all 14 columns.

#### `email_folders` (20 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `provider` | text | TEXT | X | NOT NULL |
| `provider_folder_id` | text | TEXT | X | NOT NULL |
| `parent_folder_id` | text | TEXT | X | yes |
| `name` | text | TEXT | X | NOT NULL |
| `full_path` | text | TEXT | X | NOT NULL |
| `folder_kind` | text | TEXT | X | NOT NULL |
| `is_system` | boolean | INTEGER | B | NOT NULL |
| `system_kind` | text | TEXT | X | yes |
| `classification_decision` | text | TEXT | X | NOT NULL |
| `classification_reason` | text | TEXT | X | yes |
| `user_override` | boolean | INTEGER | B | NOT NULL |
| `is_included` | boolean | INTEGER | B | NOT NULL |
| `sync_cursor` | text | TEXT | X | yes |
| `discovered_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `is_scannable` | boolean | INTEGER | B | NOT NULL |
| `is_permanently_excluded` | boolean | INTEGER | B | NOT NULL |

**Carry all rows.** `sync_cursor` is the Outlook per-folder delta link (an opaque URL carrying a provider state token). Treat it as sensitive: never printed, only hashed into C1. Verification: C1 over all 20 columns.

#### `email_ingestion_items` (21 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | text | TEXT | X | NOT NULL |
| `provider_message_id` | text | TEXT | X | NOT NULL |
| `provider_folder_ids` | text[] | TEXT | A | NOT NULL |
| `change_kind` | text | TEXT | X | NOT NULL |
| `first_discovered_at` | timestamptz | TEXT | T | NOT NULL |
| `last_discovered_at` | timestamptz | TEXT | T | NOT NULL |
| `acquisition_status` | text | TEXT | X | NOT NULL |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `lease_owner` | text | TEXT | X | yes |
| `lease_expires_at` | timestamptz | TEXT | T | yes |
| `last_error_code` | text | TEXT | X | yes |
| `last_error_at` | timestamptz | TEXT | T | yes |
| `email_id` | uuid | TEXT | U | yes |
| `completed_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** Unique `(integration_id, provider_message_id)` is what makes re-discovery after cutover a no-op instead of a duplicate. `provider_folder_ids` is `text[]` → JSON array. Verification: C1 over all 21 columns.

#### `email_sync_runs` (16 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | text | TEXT | X | NOT NULL |
| `run_kind` | text | TEXT | X | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `started_at` | timestamptz | TEXT | T | NOT NULL |
| `completed_at` | timestamptz | TEXT | T | yes |
| `folders_attempted` | integer | INTEGER | I | NOT NULL |
| `folders_completed` | integer | INTEGER | I | NOT NULL |
| `provider_ids_seen` | integer | INTEGER | I | NOT NULL |
| `ingestion_items_inserted` | integer | INTEGER | I | NOT NULL |
| `ingestion_items_existing` | integer | INTEGER | I | NOT NULL |
| `error_code` | text | TEXT | X | yes |
| `error_detail` | text | TEXT | X | yes |
| `lease_generation` | bigint | INTEGER | I | NOT NULL |

**Carry all rows.** A row left `running` by the freeze is carried as `running`; the partial unique index `email_sync_runs_one_running_per_integration` means no new run can start for that integration until startup recovery marks it `abandoned` (`selko.db.startup.reset_leases_at_startup` does, before the workers start; risk E-12). Verification: C1 over all 16 columns.

#### `email_sync_state` (18 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | text | TEXT | X | NOT NULL |
| `initial_watermark_at` | timestamptz | TEXT | T | NOT NULL |
| `next_poll_at` | timestamptz | TEXT | T | NOT NULL |
| `lease_owner` | text | TEXT | X | yes |
| `lease_expires_at` | timestamptz | TEXT | T | yes |
| `last_started_at` | timestamptz | TEXT | T | yes |
| `last_discovery_at` | timestamptz | TEXT | T | yes |
| `last_success_at` | timestamptz | TEXT | T | yes |
| `last_reconciled_at` | timestamptz | TEXT | T | yes |
| `consecutive_failures` | integer | INTEGER | I | NOT NULL |
| `last_error_code` | text | TEXT | X | yes |
| `last_error_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `folders_refreshed_at` | timestamptz | TEXT | T | yes |
| `lease_generation` | bigint | INTEGER | I | NOT NULL |

**Carry all rows.** PK `integration_id`. The Postgres trigger `integrations_ensure_email_sync_state` creates these rows; its SQLite port must not fire during the load or it would insert rows that then collide with the imported ones (§B.6). Verification: C1 over all 18 columns.

#### `emails` (45 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | yes |
| `provider_message_id` | text | TEXT | X | NOT NULL |
| `thread_id` | text | TEXT | X | yes |
| `subject` | text | TEXT | X | yes |
| `from_email` | text | TEXT | X | yes |
| `from_name` | text | TEXT | X | yes |
| `to_emails` | text[] | TEXT | A | yes |
| `date_sent` | timestamptz | TEXT | T | yes |
| `snippet` | text | TEXT | X | yes |
| `provider_labels` | text[] | TEXT | A | NOT NULL |
| `is_spam` | boolean | INTEGER | B | yes |
| `is_trash` | boolean | INTEGER | B | yes |
| `is_promotions` | boolean | INTEGER | B | yes |
| `is_social` | boolean | INTEGER | B | yes |
| `is_updates` | boolean | INTEGER | B | yes |
| `is_forums` | boolean | INTEGER | B | yes |
| `is_primary` | boolean | INTEGER | B | yes |
| `is_important` | boolean | INTEGER | B | yes |
| `is_starred` | boolean | INTEGER | B | yes |
| `is_unread` | boolean | INTEGER | B | yes |
| `storage_path` | text | TEXT | X | yes |
| `has_attachments` | boolean | INTEGER | B | yes |
| `content_hash` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `processing_status` | text | TEXT | X | yes |
| `processing_error` | text | TEXT | X | yes |
| `processed_at` | timestamptz | TEXT | T | yes |
| `locked_until` | timestamptz | TEXT | T | yes |
| `locked_by` | text | TEXT | X | yes |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `body_text` | text | TEXT | X | yes |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `dead_letter_reason` | text | TEXT | X | yes |
| `dead_letter_at` | timestamptz | TEXT | T | yes |
| `email_provider` | text | TEXT | X | NOT NULL |
| `provider_folder_ids` | text[] | TEXT | A | NOT NULL |
| `processing_outcome` | text | TEXT | X | yes |
| `processing_explanation` | text | TEXT | X | yes |
| `processing_result` | jsonb | TEXT | J | yes |
| `email_folder_id` | uuid | TEXT | U | yes |
| `is_calendar_invite` | boolean | INTEGER | B | NOT NULL |
| `lock_generation` | bigint | INTEGER | I | NOT NULL |

**Carry all rows.** Largest content: `body_text`, `snippet`, `subject` (Q0.3 measures uncompressed bytes). `to_emails`, `provider_labels`, `provider_folder_ids` are `text[]` → JSON arrays; `processing_result` is JSON. The ten nullable `is_*` booleans are carried with their NULLs (no defaulting: Q0.6 counts them). The Postgres `parse_provider_labels_trigger` recomputes the `is_*` flags from `provider_labels` on INSERT; its SQLite port must not fire during the load, or the carried flags would be silently recomputed (§B.6). `storage_path`: no code path writes it (only `attachments.storage_path` is used, `services/attachments.py`); Q0.4 counts non-NULL values and the importer carries them verbatim as text without copying any object for them. Verification: C1 over all 44 columns.

#### `event_change_proposals` (12 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `source_id` | uuid | TEXT | U | NOT NULL |
| `kind` | text | TEXT | X | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `change_set` | jsonb | TEXT | J | NOT NULL |
| `event_snapshot_before` | jsonb | TEXT | J | NOT NULL |
| `resolution_reason` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `resolved_at` | timestamptz | TEXT | T | yes |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** `change_set` and `event_snapshot_before` must be non-empty JSON objects (Postgres CHECKs); the SQLite CHECK is `json_type(col) = 'object' AND col <> '{}'`, which holds for the carried text because Postgres renders an empty object as exactly `{}`. FK `source_id → event_sources ON DELETE RESTRICT`. Verification: C1 over all 12 columns.

#### `event_identity_hints` (12 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | yes |
| `source_email_id` | uuid | TEXT | U | yes |
| `kind` | text | TEXT | X | NOT NULL |
| `value_hash` | text | TEXT | X | NOT NULL |
| `recurrence_id` | text | TEXT | X | NOT NULL |
| `strength` | text | TEXT | X | NOT NULL |
| `sequence` | integer | INTEGER | I | NOT NULL |
| `dtstamp` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `calendar_entry_id` | uuid | TEXT | U | yes |

**Carry all rows.** `value_hash` is a hash; CHECK `num_nonnulls(event_id, calendar_entry_id) = 1` ports as `(event_id IS NULL) + (calendar_entry_id IS NULL) = 1`. Verification: C1 over all 12 columns.

#### `event_repair_audit` (8 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | yes |
| `action` | text | TEXT | X | NOT NULL |
| `reason` | text | TEXT | X | NOT NULL |
| `actor` | text | TEXT | X | NOT NULL |
| `pre_change` | jsonb | TEXT | J | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** Service-only audit of production repairs (`scripts/repair_review_queue_integrity.py`); `pre_change` holds prior row content. Verification: C1 over all 8 columns.

#### `event_sources` (8 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `event_id` | uuid | TEXT | U | NOT NULL |
| `email_id` | uuid | TEXT | U | yes |
| `source_type` | text | TEXT | X | NOT NULL |
| `extracted_data` | jsonb | TEXT | J | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `source_origin` | text | TEXT | X | NOT NULL |
| `google_calendar_source_event_id` | text | TEXT | X | yes |

**Carry all rows.** `extracted_data` is the LLM extraction (JSON, personal data). Verification: C1 over all 8 columns.

#### `events` (17 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `title` | text | TEXT | X | NOT NULL |
| `start_datetime` | timestamptz | TEXT | T | yes |
| `end_datetime` | timestamptz | TEXT | T | yes |
| `all_day` | boolean | INTEGER | B | yes |
| `location` | text | TEXT | X | yes |
| `description` | text | TEXT | X | yes |
| `source_attribution` | text | TEXT | X | yes |
| `google_calendar_event_id` | text | TEXT | X | yes |
| `synced_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `importance` | text | TEXT | X | NOT NULL |
| `recurrence_rule` | text | TEXT | X | yes |
| `recovery_id` | uuid | TEXT | U | yes |
| `review_status` | text | TEXT | X | NOT NULL |

**Carry all rows.** `google_calendar_event_id` holds bare Google ids and qualified `outlook:<graph id>` ids; carried verbatim (CLAUDE.md, two calendar providers). `review_status` CHECK carried. Verification: C1 over all 17 columns.

#### `global_limits` (7 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `limit_type` | text | TEXT | X | NOT NULL |
| `default_limit` | integer | INTEGER | I | NOT NULL |
| `max_allowed` | integer | INTEGER | I | NOT NULL |
| `is_active` | boolean | INTEGER | B | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows** (configuration; 3 rows locally). Verification: C1 over all 7 columns. This table was used to validate the checksum formula on 2026-11-25 (§A.2).

#### `graph_api_failures` (19 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `occurred_at` | timestamptz | TEXT | T | NOT NULL |
| `environment` | text | TEXT | X | NOT NULL |
| `integration_id` | uuid | TEXT | U | yes |
| `graph_surface` | text | TEXT | X | NOT NULL |
| `operation` | text | TEXT | X | NOT NULL |
| `http_method` | text | TEXT | X | NOT NULL |
| `safe_url_template` | text | TEXT | X | NOT NULL |
| `http_status` | integer | INTEGER | I | yes |
| `graph_error_code` | text | TEXT | X | yes |
| `request_id` | text | TEXT | X | yes |
| `client_request_id` | text | TEXT | X | yes |
| `retry_after_seconds` | integer | INTEGER | I | yes |
| `failure_class` | text | TEXT | X | NOT NULL |
| `response_summary` | text | TEXT | X | yes |
| `run_id` | uuid | TEXT | U | yes |
| `attempt` | integer | INTEGER | I | NOT NULL |
| `will_retry` | boolean | INTEGER | B | NOT NULL |
| `resolved_at` | timestamptz | TEXT | T | yes |

**Carry all rows.** The Microsoft Graph failure ledger (`docs/microsoft-graph-failure-ledger.md`), content-free by design (`safe_url_template`, `response_summary`). Small. Verification: C1 over all 19 columns.

#### `integration_recoveries` (24 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `integration_id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | enum integration_provider | TEXT | E | NOT NULL |
| `reason` | text | TEXT | X | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `locked_by` | text | TEXT | X | yes |
| `locked_until` | timestamptz | TEXT | T | yes |
| `recovery_since` | timestamptz | TEXT | T | yes |
| `checkpoint` | jsonb | TEXT | J | NOT NULL |
| `discovered_count` | integer | INTEGER | I | NOT NULL |
| `requeued_count` | integer | INTEGER | I | NOT NULL |
| `completed_count` | integer | INTEGER | I | NOT NULL |
| `remaining_count` | integer | INTEGER | I | NOT NULL |
| `error_code` | text | TEXT | X | yes |
| `error_detail` | text | TEXT | X | yes |
| `requested_at` | timestamptz | TEXT | T | NOT NULL |
| `started_at` | timestamptz | TEXT | T | yes |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `completed_at` | timestamptz | TEXT | T | yes |
| `withdrawn_count` | integer | INTEGER | I | NOT NULL |

**Carry all rows.** `provider` is enum `integration_provider` → TEXT + CHECK `IN ('gmail','google_calendar','outlook')` (`google_photos` was dropped with the feature; a source row with it makes the import refuse, exit 3). `checkpoint` is JSON. Verification: C1 over all 24 columns.

#### `integrations` (14 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | enum integration_provider | TEXT | E | NOT NULL |
| `status` | enum integration_status | TEXT | E | NOT NULL |
| `access_token` | text | TEXT | X | NOT NULL |
| `refresh_token` | text | TEXT | X | yes |
| `token_expiry` | timestamptz | TEXT | T | yes |
| `provider_email` | text | TEXT | X | yes |
| `scopes` | text[] | TEXT | A | NOT NULL |
| `sync_cursor` | text | TEXT | X | yes |
| `last_sync_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `last_photo_sync_at` | timestamptz | — (not carried) | — | yes |

**Carry all rows, 13 of 14 columns.** `last_photo_sync_at` belonged to the
removed Google Photos ingestion and is not carried; the import refuses
(exit 3) if any row has it set, or has provider `google_photos`, so nothing is
silently dropped. **Holds secrets.** `access_token` (NOT NULL) and `refresh_token` are OAuth tokens stored **in plaintext** today: no migration uses `pgcrypto`, `pgp_sym_*` or Vault (grep of `supabase/migrations`, 2026-11-25; `vault.secrets` has 0 rows locally), and `services/integrations.py` writes them through the save RPC as `p_access_token`/`p_refresh_token` and reads them back as `row["access_token"]` with no decryption. So there is no encryption key to carry: the values are copied as TEXT byte for byte. They are hashed into C1 like any column and **never printed**: the importer's error messages for this table name the column only, never the value or the row id (§B.8). `scopes` is `text[]` → JSON array. `sync_cursor` is the Gmail `historyId` (decimal text). `provider`/`status` are enums → TEXT + CHECK. On the server the tokens sit in plaintext in `selko.db`, its WAL, every `backups/pre-NNNN.db` copy and every disk snapshot (risk E-5). Verification: C1 over the 13 carried columns.

#### `llm_call_log` (19 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `operation_type` | enum llm_operation_type | TEXT | E | NOT NULL |
| `model` | text | TEXT | X | NOT NULL |
| `email_id` | uuid | TEXT | U | yes |
| `prompt_text` | text | TEXT | X | NOT NULL |
| `response_text` | text | TEXT | X | yes |
| `prompt_tokens` | integer | INTEGER | I | yes |
| `completion_tokens` | integer | INTEGER | I | yes |
| `total_tokens` | integer | INTEGER | I | yes |
| `started_at` | timestamptz | TEXT | T | NOT NULL |
| `completed_at` | timestamptz | TEXT | T | yes |
| `latency_ms` | integer | INTEGER | I | yes |
| `success` | boolean | INTEGER | B | NOT NULL |
| `error_message` | text | TEXT | X | yes |
| `error_type` | text | TEXT | X | yes |
| `estimated_cost_usd` | numeric(10,6) | REAL | M | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `provider` | text | TEXT | X | yes |

**Carry all rows (default).** Write-only today (`services/llm_logging.py:168`, no reader in `backend/selko/`), but `prompt_text`/`response_text` are the evidence for the DoD rule that production LLM failures become eval fixtures. It holds whole email bodies and is probably the largest table (Q0.3). **Decision rule:** if Q0 shows it above 50% of the uncompressed total, the owner chooses before dry run #1 between carrying all rows and carrying rows with `created_at >= now() - 90 days`. The choice is written into this spec and passed as `--llm-log-since=<ISO>`; source counts and checksums then use the same `WHERE`. `operation_type` is enum `llm_operation_type` → TEXT + CHECK. `estimated_cost_usd numeric(10,6)` → **REAL** under the same name (decision D6). Verification: C1 over all 19 columns, the cost cell rounded to 6 decimals on both sides.

#### `oauth_states` (7 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `state` | text | TEXT | X | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `provider` | text | TEXT | X | NOT NULL |
| `redirect_uri` | text | TEXT | X | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `expires_at` | timestamptz | TEXT | T | NOT NULL |
| `code_verifier` | text | TEXT | X | yes |

**Skip every row.** These are CSRF/PKCE states for in-progress provider connections. `expires_at` defaults to `created_at + 10 minutes`, and `code_verifier` is a PKCE secret. Once the API is suspended (C-5), no flow can complete on the old stack. A flow started before the freeze and finished after the switch reaches the new process with a state it lacks and is refused, so the user clicks Connect again. Not carrying a short-lived secret is also data minimisation. Verification: target count 0; the source count is reported as `skipped`.

#### `operational_incidents` (13 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `incident_key` | text | TEXT | X | NOT NULL |
| `integration_id` | uuid | TEXT | U | yes |
| `user_id` | uuid | TEXT | U | yes |
| `incident_type` | text | TEXT | X | NOT NULL |
| `severity` | text | TEXT | X | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `safe_summary` | text | TEXT | X | NOT NULL |
| `first_seen_at` | timestamptz | TEXT | T | NOT NULL |
| `last_seen_at` | timestamptz | TEXT | T | NOT NULL |
| `resolved_at` | timestamptz | TEXT | T | yes |
| `opened_notification_sent_at` | timestamptz | TEXT | T | yes |
| `resolved_notification_sent_at` | timestamptz | TEXT | T | yes |

**Carry all rows.** `incident_key` (unique) dedupes notifications. Dropping the open incidents would make the new process send a fresh "opened" notification for each one. Verification: C1 over all 13 columns.

#### `photos` and `scheduled_tasks`: not carried

Google Photos ingestion and the scheduled-task queue were removed (#425); the
SQLite schema has neither table. The pinned column map still lists them (they
are the source's), so the drift check is unchanged. Before writing anything,
the import counts their rows, and every other trace of the feature
(`google_photos` integrations, integration recoveries and event sources,
`integrations.last_photo_sync_at`), and **refuses with exit 3** if any count
is non-zero, naming the counts. Remove that data at the source first, or keep
the old deployment.

#### `sender_rules` (7 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `sender_domain` | text | TEXT | X | yes |
| `sender_email` | text | TEXT | X | yes |
| `action` | text | TEXT | X | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** At least one of `sender_domain`/`sender_email` is non-NULL (CHECK). Verification: C1 over all 7 columns.

#### `usage_quotas` (11 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `date` | date | TEXT | D | NOT NULL |
| `llm_calls_count` | integer | INTEGER | I | NOT NULL |
| `llm_calls_limit` | integer | INTEGER | I | NOT NULL |
| `email_syncs_count` | integer | INTEGER | I | NOT NULL |
| `email_syncs_limit` | integer | INTEGER | I | NOT NULL |
| `calendar_syncs_count` | integer | INTEGER | I | NOT NULL |
| `calendar_syncs_limit` | integer | INTEGER | I | NOT NULL |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** The current day's counters gate LLM calls, so they must carry. Older days could be dropped but are tiny. `date` → `YYYY-MM-DD`. Verification: C1 over all 11 columns.

#### `user_calendar_settings` (8 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `user_id` | uuid | TEXT | U | NOT NULL |
| `target_calendar_id` | text | TEXT | X | yes |
| `default_invitees` | text | TEXT | X | yes |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |
| `timezone` | text | TEXT | X | NOT NULL |
| `all_day_display_mode` | text | TEXT | X | NOT NULL |
| `all_day_custom_start` | time | TEXT | H | yes |
| `all_day_custom_end` | time | TEXT | H | yes |

**Carry all rows.** PK `user_id`. `all_day_custom_start/end` are `time` → `HH:MM:SS` (Q0.6 asserts no fractional seconds; if any exist the format is `HH:MM:SS.ffffff` for that column and the cell expression stays `col::text`). The CHECK `all_day_custom_end > all_day_custom_start` stays valid in SQLite as a text comparison, because the fixed-width format sorts like the time. Verification: C1 over all 8 columns.

#### `users` (5 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `email` | text | TEXT | X | NOT NULL |
| `display_name` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `updated_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows.** Today `users.id → auth.users(id) ON DELETE CASCADE`; in SQLite it becomes `users.id → accounts(id) ON DELETE CASCADE`, so `accounts` loads first (§A.3). Q0.5 checks that `users.email` equals the account email. Verification: C1 over all 5 columns.

#### `auth.users` → `accounts`

Carried (`ACCOUNT_SOURCE` in `core.py`), for every `auth.users` row with
`deleted_at IS NULL` and a non-empty `encrypted_password`:

| auth.users column | `accounts` column | Conversion |
|---|---|---|
| `id` | `id` | U |
| `email` | `email` | `lower(email)` (NOT NULL UNIQUE in `accounts`) |
| `encrypted_password` | `password_hash` | verbatim bcrypt `$2a$10$…`; Python `bcrypt` verifies it unchanged |
| `email_confirmed_at` | `email_confirmed_at` | T |
| `created_at` | `created_at` | T |
| `coalesce(updated_at, created_at)` | `updated_at` | T |
| `last_sign_in_at` | `last_sign_in_at` | T |

Not carried: everything else in `auth.users` (`banned_until`, `phone`,
`raw_user_meta_data`, `is_anonymous`, `is_sso_user`, …) and all GoTrue
session, refresh-token, identity and MFA tables. **Every web user signs in
again after cutover**; old sessions are not carried.

A `public.users` row whose account is not carried (deleted, or no password,
e.g. an OAuth-only sign-in) has no `accounts` row to reference; the
foreign-key check after the load then fails and the import exits 5 with
nothing written. **UNKNOWN:** whether production has such users; Q0.5 counts
them. **Not built:** a C1 checksum for `accounts` (the count is reported) and
preflight checks for anonymous/SSO users, NULL emails or phones.

#### `storage.objects` (bucket `attachments`) → `<data dir>/attachments/`

`storage.objects` is not turned into a table. Each object becomes one file
(`selko_import/attachments.py`):

| Source | Target |
|---|---|
| `storage.objects.name` (= `attachments.storage_path`, `"{user_id}/{uuid12}_{safe_filename}"`) | file `<data dir>/attachments/<name>`, mode 0600 |
| object bytes, via the Storage API (§B.7) | written to `<name>.copying`, fsynced, then renamed |
| `metadata->>'size'` | checked against the file's length |
| `attachments.content_hash` (when set) | checked against the file's SHA-256 |

The path is carried **verbatim**, so `attachments.storage_path` is unchanged
and the server resolves files through that column. A name that is absolute,
contains `..`, `.` or an empty segment, or resolves outside the attachments
directory stops the copy (exit 6).

- **Objects with no `attachments` row** are copied anyway and counted
  ("without a row"), except files of the removed photo ingestion
  (`{user_id}/photos/...` with no row), which are counted and not copied.
- **Rows whose object is missing at the source** are counted ("rows whose
  object the source lacks"); the row is carried unchanged by the database
  import. This count does not fail the copy.
- An object that is missing when fetched (404, or Storage's 400 `not_found`)
  or whose bytes do not match its size/hash is counted, not kept, and makes
  the run exit 6. Re-running retries it.

**Not built:** moving local files whose source object disappeared into an
`attachments.removed/` folder, a per-run error file with ids, and a check of
the first path segment against the row's `user_id`.

---

## B. The import tool: `python -m selko_import`

### B.1 Where it lives and how it runs

- Package **`selko_import/`** (top level, beside `backend/selko/`, never
  inside it): `backend/tests/test_no_hosted_database.py` fails if anything
  under `selko` imports a Postgres driver, and the importer is the one place
  that needs one (`asyncpg`, a dependency of the workspace root only).
- It ships as its own image, `ghcr.io/tonimelisma/selko-import:<sha>`
  (Dockerfile target `importer`: the `selko` package plus `selko_import` and
  `asyncpg`), built, checked and signed with the app image by `image.yml`, so
  the app image never carries a Postgres driver. Use the importer image of
  **the same commit** as the app image that will serve the file: the importer
  applies `selko`'s own migration chain, so the file it writes is the schema
  that app expects.
- It runs **on the server**, as uid 10001, with a read-only root, no
  capabilities, the data directory mounted and the secret files mounted
  read-only. Never in Actions: the repository is public and a log or artifact
  would expose user data. The image lane runs it exactly this way against the
  fixture (`scripts/image-lane.sh`).

### B.2 Commands and inputs

```
python -m selko_import database    --source-url-file F --target <data dir>/selko.db
python -m selko_import attachments --source-url-file F --storage-url https://<ref>.supabase.co \
                                   --storage-key-file F --data-dir <data dir>
```

| Input | How | Never |
|---|---|---|
| source URL | a file (`--source-url-file`): the session-pooler connection string of the production database. It carries the password | on a command line, in an environment variable, in a log |
| storage key | a file (`--storage-key-file`): a Supabase secret API key created only for the import (§B.7) | printed, logged, kept after the cutover |
| storage URL | `--storage-url`, not a secret | — |
| pinned column map | `selko_import/columns.json`: the source's tables and columns with their conversion codes | read from `information_schema` at run time |

The operator copies the values into files on the server himself, from the
Supabase dashboard; no agent sees them. On open the importer sets
`SET TIME ZONE 'UTC'` for its own session. **Not built:** file-permission
checks on the secret files, `server_encoding` and timeout settings.

### B.3 Source reads

- Drift check first: the live `public` table and column lists must equal the
  pinned map exactly, or exit 3. Then the removed-feature check (§A.3), exit 3.
- **One snapshot for the whole import.** The drift check, the removed-feature
  check, the accounts and every table's rows *and* source checksum are read in
  a single `REPEATABLE READ READ ONLY` transaction, through asyncpg cursors
  (500 rows per fetch and per batch), every column through its `CONVERT`
  expression. The copy is therefore exactly the source as of that
  transaction's start, and a write committed while the import runs is neither
  copied nor counted: a rehearsal against the live deployment verifies as
  cleanly as the real run. (Rehearsal 2 failed with exit 5 on
  `email_sync_state` before this: each table had its own transaction and the
  checksum ran outside it, so a live worker's write landed in between.)
- The freeze (§C.3) is still what makes the copy *complete*: with the old
  workers stopped, nothing written after the snapshot is lost, and no OAuth
  refresh token rotates after it is copied. **Not built:** the write
  fingerprint (Q0.7) taken by the tool; take it by hand at the freeze.
- `attachments` reads its object list and row count in one snapshot too.

### B.4 Memory

Rows move in batches of 500, one SQLite transaction per table. Attachments
stream to disk in 64 KiB chunks, one at a time. **Not built:** byte-bounded
batches, adaptive prefetch and peak-RSS reporting. Give the production run
the same 400 MB limit as the app and watch it.

### B.5 Writing: fresh file, new schema, atomic rename

1. Refuse (exit 2) if the target file exists. Refuse (exit 4) if another
   process holds the data directory's lock (`<data dir>/.selko.lock`,
   `flock`): the server and the importer take it for as long as they run, so
   the importer never writes while a server runs. Operator commands
   (`selko.admin`) do not take it.
2. Create `<target>.importing` (deleting any leftover), apply the migration
   chain with `selko.db.migrate`, drop every trigger (their SQL is kept), set
   `foreign_keys = OFF`, and delete rows the migrations seed
   (`global_limits`), which come from the source instead.
3. Load `accounts`, then every carried table in alphabetical order. A CHECK,
   NOT NULL or UNIQUE failure stops the import (exit 5) with nothing written.
4. Recreate the triggers verbatim, set `foreign_keys = ON`, run the
   structural checks (§A.2) including `foreign_key_check`.
5. On success `os.replace(<target>.importing, <target>)`: the rename is the
   only step that makes the result visible, and it is atomic. On any failure
   the scratch file and its WAL/SHM are deleted and the target is never
   touched.

**Not built:** dropping and rebuilding non-PK indexes, fsyncing the
directory, a free-space check, and chowning (the importer runs as the
server's uid, so the file is already its).

### B.6 Why triggers are dropped during the load

The SQLite triggers that recompute `emails.is_*` flags, insert
`email_sync_state` rows, set `updated_at` and check ownership would change
carried values or insert extra rows. The import is a **pure copy**. All state
repair is left to the server's startup recovery
(`selko.db.startup.reset_leases_at_startup`: leases released, `running` sync
runs marked `abandoned`), which already exists for crashes. A copy that
changes nothing can then be checked by checksum.

### B.7 Attachment copy

- Object list: `storage.objects WHERE bucket_id = 'attachments'` (name,
  `metadata->>'size'`), joined to `public.attachments` on `storage_path` for
  `content_hash` and to tell orphans and photo files apart.
- Bytes: `GET {storage url}/storage/v1/object/authenticated/attachments/{name}`
  with `Authorization: Bearer <key>` and `apikey: <key>`, streamed, 60 s read
  timeout, 4 attempts with backoff on 5xx/429/connection errors. A 404 (or
  Storage's 400 `not_found`) counts as missing at the source; any other 4xx
  is exit 7.
- **Credential.** Storage has no read-only key. Use a **dedicated secret API
  key** (Supabase dashboard → Project Settings → API Keys → Secret keys →
  "Create new secret key", named `cutover-import`), deleted after the
  cutover. **UNKNOWN:** whether the project has the new API-key system; if it
  only has the legacy `service_role` key, that key is the credential and is
  rotated when the project is deleted.
- **Restartable.** A file already present with the right size (and SHA-256
  when `content_hash` is set) is skipped, so the copy runs early, while
  production is live, and again after the freeze for the delta.

### B.8 Output: counts only

stdout/stderr carry table names, counts, byte totals and exit reasons. No
cell values, ids, emails, object names, paths, URLs or keys: an import
failure names the table (and SQLite's constraint message), the attachment
copy prints one counts line. `test_import_attachments.py` asserts the key,
the source URL, an object name and a user id appear in no output. **Not
built:** a per-row error file and a JSON report file.

### B.9 Acceptance

`database` exits 0 only if: every carried table's checksum triple (count,
sum, xor) is equal on both sides; `integrity_check` is `ok`;
`foreign_key_check` returns nothing; and every T column has the 27-character
form. It prints one line per table and a total.

`attachments` exits 0 only if no object was missing at the source and none
mismatched its size/hash. It prints: objects, copied (bytes), already in
place, missing at source, not matching, without a row, rows whose object the
source lacks, photo files not copied.

### B.10 Exit codes

| Exit | `database` | `attachments` |
|---|---|---|
| 0 | imported and verified; `selko.db` is in place | every object copied and verified |
| 2 | usage, or the target already exists | usage |
| 3 | source schema differs from the pinned map, or the source holds data of the removed Google Photos feature | — |
| 4 | the data directory is in use (its lock is held) | the data directory is in use |
| 5 | a source row violates the target schema, or verification failed; nothing written | — |
| 6 | — | some objects missing at the source or not matching, or an object name outside the directory; re-runnable |
| 7 | — | the Storage API refused the key or the request, or kept failing |

**Not built:** `--dry-run`, `--verify-only`, `--measure`, `--delta-since`,
`--llm-log-since`, `--attachments-only` (the separate `attachments` command
replaces it), exit 8 and exit 9. A dry run is an import into a throwaway
directory (§C.2).

### B.11 Tests

- `backend/tests/integration/test_import_from_postgres.py` and
  `test_import_attachments.py` run against a throwaway Postgres container
  holding `selko_import/fixture/` (the frozen pre-move schema with synthetic
  rows), with a local stand-in for the Storage API. They cover the happy
  path, a corrupted cell (exit 5, nothing written), schema drift (exit 3), a
  row the target refuses (exit 5), each removed-feature refusal (exit 3), a
  re-run that copies nothing, a missing or corrupt object (exit 6), a refused
  key (exit 7), a path outside the directory, and counts-only output. They
  need Docker (or `SELKO_IMPORT_TEST_POSTGRES_URL`) and never skip.
- The image lane (`scripts/image-lane.sh`, also in `image.yml`) imports the
  fixture with the importer image, then boots the app image on the result
  and signs in with the carried password.
- **Not built:** a separate CI lane named `import-from-postgres`, and an
  edge-value fixture beyond `selko_import/fixture/`.

---

## C. Cutover runbook

### C.0 Q0 measurements: the exact read-only SQL

These are read-only queries for sizing and preconditions. **How they run:**
the operator runs them in the Supabase dashboard's SQL editor (or any
read-only session) and records **counts and sizes only**. The planned
`measure-production` Actions operation and the importer's `--measure` mode
were **not built** (`ops.yml` is gone, and an Actions log is public).

**Q0.1 Size per table** (on-disk, compressed):
```sql
SELECT c.relname,
       pg_total_relation_size(c.oid)                       AS total_bytes,
       pg_relation_size(c.oid)                             AS heap_bytes,
       COALESCE(pg_total_relation_size(c.reltoastrelid),0) AS toast_bytes,
       pg_indexes_size(c.oid)                              AS index_bytes
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY total_bytes DESC;
SELECT pg_database_size(current_database()) AS database_bytes;
```

**Q0.2 Exact row count per table** (one statement covering all 30 tables):
```sql
SELECT table_name,
       (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM public.%I', table_name), false, true, '')))[1]::text::bigint AS n
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1;
```

**Q0.3 Uncompressed size of the large values.** SQLite does not compress,
and TOAST does, so this, not Q0.1, sizes `selko.db`:
```sql
SELECT 'emails.body_text' AS col, count(body_text), sum(octet_length(body_text)), max(octet_length(body_text)) FROM public.emails
UNION ALL SELECT 'emails.snippet', count(snippet), sum(octet_length(snippet)), max(octet_length(snippet)) FROM public.emails
UNION ALL SELECT 'emails.processing_result', count(processing_result), sum(octet_length(processing_result::text)), max(octet_length(processing_result::text)) FROM public.emails
UNION ALL SELECT 'llm_call_log.prompt_text', count(prompt_text), sum(octet_length(prompt_text)), max(octet_length(prompt_text)) FROM public.llm_call_log
UNION ALL SELECT 'llm_call_log.response_text', count(response_text), sum(octet_length(response_text)), max(octet_length(response_text)) FROM public.llm_call_log
UNION ALL SELECT 'event_sources.extracted_data', count(*), sum(octet_length(extracted_data::text)), max(octet_length(extracted_data::text)) FROM public.event_sources
UNION ALL SELECT 'calendar_work_items.desired_event', count(desired_event), sum(octet_length(desired_event::text)), max(octet_length(desired_event::text)) FROM public.calendar_work_items
UNION ALL SELECT 'event_change_proposals.json', count(*), sum(octet_length(change_set::text) + octet_length(event_snapshot_before::text)), max(octet_length(change_set::text) + octet_length(event_snapshot_before::text)) FROM public.event_change_proposals
UNION ALL SELECT 'calendar_sync_log.snapshot_synced', count(*), sum(octet_length(snapshot_synced::text)), max(octet_length(snapshot_synced::text)) FROM public.calendar_sync_log;
SELECT min(created_at), max(created_at), count(*) FILTER (WHERE created_at < now() - interval '90 days') AS older_than_90d FROM public.llm_call_log;
```

**Q0.4 Attachments:**
```sql
SELECT count(*) AS objects, sum((metadata->>'size')::bigint) AS bytes, max((metadata->>'size')::bigint) AS max_bytes
FROM storage.objects WHERE bucket_id = 'attachments';
SELECT bucket_id, count(*) FROM storage.objects GROUP BY 1;                                  -- expect only 'attachments'
SELECT count(*) AS rows, count(storage_path) AS with_path, count(DISTINCT storage_path) AS distinct_paths,
       sum(size_bytes) FILTER (WHERE storage_path IS NOT NULL) AS row_bytes,
       count(*) FILTER (WHERE ingestion_status = 'stored' AND storage_path IS NULL) AS stored_without_path,
       count(*) FILTER (WHERE storage_path IS NOT NULL AND content_hash IS NULL) AS path_without_hash
FROM public.attachments;
SELECT count(*) AS orphan_objects, coalesce(sum((o.metadata->>'size')::bigint),0) AS orphan_bytes
FROM storage.objects o WHERE o.bucket_id = 'attachments'
  AND NOT EXISTS (SELECT 1 FROM public.attachments a WHERE a.storage_path = o.name);
SELECT count(*) AS rows_missing_object FROM public.attachments a
WHERE a.storage_path IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM storage.objects o WHERE o.bucket_id = 'attachments' AND o.name = a.storage_path);
SELECT count(*) FILTER (WHERE name !~ '^[0-9a-f-]{36}/[A-Za-z0-9._-]+$') AS bad_names FROM storage.objects WHERE bucket_id = 'attachments';
SELECT count(storage_path) AS email_paths FROM public.emails;
```

**Q0.5 Users and sign-in:**
```sql
SELECT count(*) AS users,
       count(*) FILTER (WHERE is_anonymous) AS anonymous,
       count(*) FILTER (WHERE is_sso_user) AS sso,
       count(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted,
       count(*) FILTER (WHERE banned_until > now()) AS banned,
       count(*) FILTER (WHERE email IS NULL) AS no_email,
       count(*) FILTER (WHERE email <> lower(email)) AS mixed_case_email,
       count(*) FILTER (WHERE phone IS NOT NULL) AS with_phone,
       count(*) FILTER (WHERE email_confirmed_at IS NULL) AS unconfirmed,
       count(*) FILTER (WHERE coalesce(encrypted_password,'') = '') AS no_password,
       count(*) FILTER (WHERE encrypted_password <> '' AND encrypted_password !~ '^\$2[aby]\$') AS non_bcrypt,
       count(*) FILTER (WHERE last_sign_in_at > now() - interval '30 days') AS active_30d
FROM auth.users;
SELECT provider, count(*) FROM auth.identities GROUP BY 1;                                   -- expect only 'email'
SELECT (SELECT count(*) FROM auth.users a WHERE NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = a.id)) AS auth_without_profile,
       (SELECT count(*) FROM public.users u JOIN auth.users a ON a.id = u.id WHERE u.email IS DISTINCT FROM a.email) AS email_mismatch;
```
Whether sign-up needs email confirmation is not in SQL. It is the Auth
config, read by the agent from the cloud session through the Management API
(network secret for `api.supabase.com`). **Filter with jq: the full response
contains SMTP and provider secrets.**
```bash
curl -fsS https://api.supabase.com/v1/projects/khahcozfbnpykspvatrg/config/auth \
  | jq '{mailer_autoconfirm, disable_signup, jwt_exp, refresh_token_rotation_enabled, security_refresh_token_reuse_interval, password_min_length, site_url}'
```

**Q0.6 Domain preconditions** (each count must be 0, except the `null_*`
counts and the scale, which are recorded):
```sql
-- infinity timestamps, per timestamptz column
SELECT c.table_name||'.'||c.column_name AS col,
       (xpath('/row/n/text()', query_to_xml(format(
         'SELECT count(*) AS n FROM public.%I WHERE %I IN (''infinity''::timestamptz, ''-infinity''::timestamptz) OR extract(year FROM %I) NOT BETWEEN 1 AND 9999',
         c.table_name, c.column_name, c.column_name), false, true, '')))[1]::text::bigint AS bad
FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.data_type = 'timestamp with time zone';
SELECT count(*) FILTER (WHERE array_ndims(to_emails) > 1) + count(*) FILTER (WHERE array_ndims(provider_labels) > 1)
     + count(*) FILTER (WHERE array_ndims(provider_folder_ids) > 1) AS multidim FROM public.emails;
SELECT count(*) FILTER (WHERE array_position(to_emails, NULL) IS NOT NULL) AS null_elements FROM public.emails;
SELECT count(*) FILTER (WHERE all_day_custom_start::text LIKE '%.%' OR all_day_custom_end::text LIKE '%.%') AS fractional_time FROM public.user_calendar_settings;
SELECT count(*) AS photo_rows FROM public.photos;  -- must be 0, or the import refuses (exit 3)
SELECT count(*) AS scheduled_task_rows FROM public.scheduled_tasks;  -- must be 0
SELECT count(*) FILTER (WHERE is_spam IS NULL) AS null_is_spam, count(*) FILTER (WHERE is_unread IS NULL) AS null_is_unread,
       count(*) FILTER (WHERE has_attachments IS NULL) AS null_has_attachments, count(*) FILTER (WHERE processing_status IS NULL) AS null_status
FROM public.emails;
SHOW server_encoding;   -- expect UTF8
```

**Q0.7 Write fingerprint** (used at the freeze; content-free):
```sql
SELECT sum(n_tup_ins + n_tup_upd + n_tup_del) AS fingerprint
FROM pg_stat_all_tables WHERE schemaname IN ('public', 'auth', 'storage');
SELECT greatest((SELECT max(updated_at) FROM public.events), (SELECT max(created_at) FROM public.emails),
                (SELECT max(updated_at) FROM public.calendar_work_items), (SELECT max(updated_at) FROM public.email_sync_state),
                (SELECT max(updated_at) FROM public.integrations), (SELECT max(created_at) FROM auth.users)) AS last_write_at;
```
Statistics are flushed asynchronously, so the two readings are taken at
least 3 minutes apart. **UNKNOWN:** whether the read-only role can see
`n_tup_*` for `auth` and `storage`. Find out in dry run #1: if the values
come back NULL, the fingerprint is computed over `public` only and the
`last_write_at` line carries the auth check.

**Q0.8 In flight** (at the freeze):
```sql
SELECT 'emails' AS t, count(*) FROM public.emails WHERE processing_status = 'processing'
UNION ALL SELECT 'attachments', count(*) FROM public.attachments WHERE ingestion_status = 'processing'
UNION ALL SELECT 'email_ingestion_items', count(*) FROM public.email_ingestion_items WHERE acquisition_status = 'processing'
UNION ALL SELECT 'calendar_work_items', count(*) FROM public.calendar_work_items WHERE status = 'processing'
UNION ALL SELECT 'calendar_work_items_pending', count(*) FROM public.calendar_work_items WHERE status = 'pending'
UNION ALL SELECT 'email_sync_runs', count(*) FROM public.email_sync_runs WHERE status = 'running'
UNION ALL SELECT 'integration_recoveries', count(*) FROM public.integration_recoveries WHERE status IN ('pending','processing','waiting')
UNION ALL SELECT 'oauth_states_live', count(*) FROM public.oauth_states WHERE expires_at > now();
```

Also measured, outside SQL. **UNKNOWN until checked:** the Supabase plan
(dashboard → Organization → Billing; a free-plan project is paused after a
week of inactivity, see §D.4); whether Render `autoDeploy` is off for both
services (P-2); and the server's free disk and memory (P-11).

### C.1 Health invariants

`scripts/check-production-health.sh <url>` asserts, through
`scripts/assert-health.sh`, four surfaces: `root` and `egress` on `/health`
and `/health/egress`, and `work-state` and `ingestion`, both read from
`/health/ingestion` (there is no `/health/work-state` route).

| Surface | Old stack (Render + Supabase) | New process (this repository's `assert-health.sh`) |
|---|---|---|
| `root` | 40-char `build_sha`, `server_errors_per_hour == 0` | unchanged |
| `work-state` | `items_dead_letter`, `attachments_dead_letter`, `stale_processing_emails`, `unclaimable_pending` all 0 | unchanged (same counters, computed by `selko.db.health`) |
| `ingestion` | status ok, background on, every task alive, `listener.connected` | status ok, background on, every task alive, `listener.kind == "in_process"` and `bound` |
| `egress` | `transport == "asyncpg"` | `transport == "sqlite"` |

The script on `main` holds the new rules, so it is red against the old stack
by construction. For observations of the old stack use its own assertions:
`git show 7207aac5:scripts/assert-health.sh`. **Not built:** a
`database.engine`/`schema_version` field in `/health`.

Note for the server's updater: `/health` reports `degraded` whenever there
are dead letters, so an update during such a period rolls back.

### C.2 Prerequisites

| # | Owner | Step | Done when |
|---|---|---|---|
| P-1 | agent | Record the last Postgres build: `curl -fsS https://api.selkoapp.com/health \| jq -r .build_sha` into the deploy log as `LAST_PG_SHA` (7207aac5 at the time of writing) | recorded |
| P-2 | operator | Render never builds `main` again (it is SQLite code now): Render dashboard → each service → Settings → Auto-Deploy → **No**; Deploy Hook → **Regenerate** | both services off |
| P-3 | operator | Q0 numbers recorded, counts only (§C.0); in particular Q0.5 (users without a carried account) and the photos/scheduled-task counts, which must be 0 | recorded |
| P-4 | operator | OAuth consoles: the hostname does not change, so nothing is edited. Check Google (*Authorized redirect URIs* has `https://api.selkoapp.com/integrations/google/callback`) and Microsoft Entra (*Redirect URIs* has `https://api.selkoapp.com/integrations/microsoft/callback`; client secret valid past T+30d) | both present |
| P-5 | operator | Notify users ahead of the change (the privacy policy promises notice): date, window, "you will need to sign in again" | sent |
| P-6 | agent | The privacy policy names the providers Selko uses (done: Google Cloud hosting, no Supabase or Render) | in the released image |
| P-7 | operator | The server's env file, copied by the operator from the Render dashboard into the server himself (no agent sees it): `ENVIRONMENT=production`, `API_PUBLIC_URL=https://api.selkoapp.com`, `FRONTEND_URL=https://selkoapp.com`, `ALLOWED_ORIGINS=https://selkoapp.com,https://www.selkoapp.com,https://api.selkoapp.com`, `ENABLE_BACKGROUND_PROCESSING=true` (on from the first start, owner decision), the OAuth clients, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_THINKING`, `LLM_FALLBACK_PROVIDER=none`, the LLM key, optional Sentry/notification settings, and `SELKO_JWT_SECRET` generated on the server (`openssl rand -hex 32`) | key list confirmed by name |
| P-8 | operator | Import inputs in files on the server: the session-pooler URL and the `cutover-import` storage key (§B.7) | files present |
| P-9 | on the server | Rehearsal: run `database` into a throwaway directory, boot the app image on it with background processing **off** (it would otherwise poll mailboxes and write calendars beside production), sign in, compare counts, delete the directory (it holds real user data) | exit 0, sign-in works, directory deleted |
| P-10 | operator | Lower the DNS TTL of `selkoapp.com`, `www` and `api` to 1 min (Cloudflare → DNS) a day ahead | TTL ≤ 60 s |
| P-11 | on the server | Capacity: free disk ≥ 4 × the Q0.3 uncompressed total + 1.2 × the Q0.4 attachment bytes + 2 GiB; NTP synchronised | both true |
| P-12 | operator | **Release in place**: the commit to run is on `main` and its `release` job is green, so `:main` and both images of that commit are signed. Use the importer image of the same commit | `:main` = that commit |
| P-13 | on the server | Warm attachment copy while production is live: `attachments …` (re-runnable) | exit 0, or exit 6 with the missing count recorded as pre-existing loss |
| P-14 | operator | Go/no-go at the lowest-traffic hour | go |

### C.3 The window (T0 = start of freeze)

**Hard limit: if C-9 (DNS live) has not been reached by T0+90 min, roll back
(§D, R1).**

| # | Owner | Step | Expected |
|---|---|---|---|
| C-1 | agent | Baseline: old-stack health with its own assertions (§C.1) | OK, `build_sha = LAST_PG_SHA` |
| C-2 | operator | **Freeze:** suspend the Render services (dashboard → service → Suspend). This stops every writer; DNS stragglers later get an error, never a write | `/health` on the old host stops answering 200 |
| C-3 | operator | Write fingerprint Q0.7 twice, at least 3 min apart (§C.0) | identical; if not, something still writes: find it or roll back (R1) |
| C-4 | on the server | Final attachment delta: `attachments …` | exit 0 |
| C-5 | on the server | **Import:** `database --source-url-file … --target <data dir>/selko.db` | exit 0, every table's checksum matches |
| C-6 | on the server | Protect the starting point: a manual disk snapshot | snapshot listed |
| C-7 | on the server | **Start Selko** (background processing on). It migrates at startup and takes the data directory's lock | `/health` ok with the released `build_sha`; `/health/ingestion` every task alive, `listener.bound` |
| C-8 | operator | **Switch DNS** (Cloudflare → DNS, DNS only as today): `selkoapp.com`, `www.selkoapp.com` and `api.selkoapp.com` → the server; all three are served by the same container. Write the old targets into the deploy log first | saved |
| C-9 | agent | Propagation and TLS: the three names resolve to the server and answer over TLS; `curl -fsS https://api.selkoapp.com/health \| jq -r .build_sha` is the released SHA | done |
| C-10 | agent | `./scripts/check-production-health.sh` | all four surfaces OK within 10 min (every integration is overdue after the window, so the first polls are immediate) |
| C-11 | operator | Sign in with the existing password; Review, History, Settings; download one attachment; reconnect Google (and Outlook if connected) to prove the OAuth round trip; with Review open run "Check email now" and see it update without a reload | all work |
| C-12 | agent | **Deploy log** `docs/deploy-log/<date>-<sha>.md`: T+0 (the server session hands over the SHA, the cutover time and the health output), then T+15m inside the turn, T+24h next day | rows filled |
| C-13 | operator | Close the import credentials: delete the `cutover-import` key in Supabase; delete the secret files on the server | done |

**Expected downtime:** from C-2 to C-9, the import duration (measured in the
rehearsal) plus about 20 min. No email is lost: the provider cursors
(`integrations.sync_cursor`, `email_folders.sync_cursor`,
`calendar_mirror_state.sync_token`) are carried, so the first polls pick up
everything that arrived during the window. Web users sign in once more.

---

## D. Rollback

Background processing is on from the first start, so **the new server writes
from the moment it starts (C-7)**: it polls mailboxes, extracts events and may
write calendars, and from C-9 users write too. Rolling back after C-7 loses
those writes.

### D.1 Decision criteria

| Trigger | Action |
|---|---|
| The import exits non-zero, or C-3 fingerprints differ and the writer is not found within 10 min | **R1** at once; diagnose afterwards |
| C-7 to C-10: health red, sign-in fails, counts wrong, TLS not issued within 10 min of propagation | R2 |
| A cross-user data exposure or visibly wrong data at any time | **Stop the Selko container immediately**, then decide R2 within 1 h |
| After T+24h | No rollback, fix forward, except for a data-integrity breach |

### D.2 R1: before Selko started (nothing written on SQLite)

Lossless. Postgres is exactly as it was at the freeze.

1. On the server: move the imported files aside for diagnosis (they hold user
   data; delete within 7 days).
2. Operator: resume the Render services (dashboard → Resume). **Never** use a
   deploy hook or "Deploy latest commit": `main` is SQLite code. Confirm
   `/health` answers `build_sha = LAST_PG_SHA`.
3. Deploy log: verdict "rolled back", with the reason.

### D.3 R2: after Selko started (SQLite has accepted writes)

**This loses data; there is no carry-back.** What happens to each kind of
write made on SQLite:

| Written on SQLite | On the old stack after R2 |
|---|---|
| New emails and their extracted events | Not lost: the old stack resumes from its own cursors, frozen at the freeze, and re-extracts them (LLM cost again) |
| Calendar events written by the new server | They exist in the provider calendar; the old stack's mirror sees them and dedup should adopt them. **Residual risk: duplicates**; check the affected users' calendars |
| User decisions, sender rules, calendar settings | **Lost**; the events come back in the review lanes |
| OAuth reconnects, new sign-ups | Lost; old refresh tokens normally still work, new users sign up again |
| Account deletion requests | Must be repeated on the old stack |

1. On the server: stop Selko **first**, so nothing writes while DNS drains.
   Keep `selko.db` and take a snapshot.
2. Operator: DNS back to the values in the deploy log; resume Render (R1
   step 2).
3. Operator: re-apply decisions by hand, check calendars for duplicates,
   email affected users. **Not built:** a `--delta-since` report listing what
   was written after the cutover; the operator compares by hand.
4. Deploy log: verdict "rolled back".

### D.4 Retention of the old stack

Render stays suspended and Supabase untouched (no migrations, no Auth or
Storage changes) for about a week of stable running. **UNKNOWN:** the
Supabase plan; a free-plan project pauses after a week of inactivity (it can
be restored from the dashboard). Then, on the owner's say-so: delete the
Render services and the Supabase project (that deletion is how user data
held there is deleted, inside the privacy policy's 30 days), remove the
remaining Actions secrets for Supabase and Render, and delete `selko_import`
from this repository.

---

## E. Risk register

L = likelihood and I = impact, each rated H, M or L.

| # | Risk | L | I | Detection | Mitigation |
|---|---|---|---|---|---|
| E-1 | **Data shape surprise.** A production value the SQLite schema refuses: a NOT NULL that Postgres allows, an enum label missing from a CHECK, an array with NULL elements, a multi-dimensional array, `infinity` | M | M (the import fails in the window: R1, a wasted window) | Q0.6 ahead of time; the rehearsal (P-9) runs the real import | `0001_initial.sql` was written from the live schema with the CHECKs and nullability ported one for one; the rehearsal against production; a refused row is exit 5 with nothing written |
| E-2 | **Timestamp format or precision drift.** A `selko/db/` path or a SQLite `DEFAULT` writes milliseconds or `+00:00`, so text comparison of leases and `next_retry_at` misorders silently | M | H (silent, in lease and retry logic) | the import's 27-character check over every T column (§A.2) | one codec; `tx.now` is the one timestamp source; defaults padded to microseconds. **Not built:** a per-column CHECK on the format and a startup re-check |
| E-3 | **Timezone loss.** A `timestamptz` read with a non-UTC session zone, or `time`/`date` columns treated as UTC instants | L | M | C1: the source side uses `AT TIME ZONE 'UTC'` independently of the codec, so any shift is a mismatch | `SET TIME ZONE 'UTC'` on the source session; asyncpg returns aware datetimes; `date`/`time` carried as text, never converted |
| E-4 | **Numeric conversion.** `estimated_cost_usd` losing precision in REAL | L | L | C1 (both sides rounded to 6 decimals, the column's scale) | the name and unit are unchanged; the photo coordinates are no longer carried |
| E-5 | **OAuth tokens exposed.** They are plaintext in `integrations`. During the import they could leak through output; after it they sit unencrypted in `selko.db`, its WAL, every `backups/pre-NNNN.db` and the disk snapshots | M | H (anyone who can read those files has every user's mailbox) | the counts-only output test (§B.8) | output carries counts only; files 0600; rehearsal copies deleted the same day. **Not built:** application-level encryption of `access_token`/`refresh_token` with a key from the env file (owner's call) |
| E-6 | **OAuth redirect mismatch.** `API_PUBLIC_URL` mistyped in the env file (`http://`, a trailing `/`), so Google/Microsoft refuse with `redirect_uri_mismatch` and every reconnect fails | M | M (existing tokens keep working; only connect/reconnect breaks) | C-11 reconnect round trip; `_validate_redirect_uri` only allows `api.selkoapp.com`, `localhost`, `127.0.0.1` | the hostname is unchanged, so the consoles need no edit (P-4 only checks them); P-7 gives the exact value; C-11 is mandatory before T+0 is written |
| E-7 | **Provider cursor discontinuity.** A Gmail `historyId` too old (Gmail answers 404 and a full resync is needed), or an Outlook delta link expired (`syncStateNotFound`/410) after the window, causing a slow catch-up or missed messages | L (the window is about an hour) | M | `graph_api_failures` rows, `email_sync_state.last_error_code`, `/health/ingestion` `items_stalled_seconds` | cursors carried verbatim; `services/gmail.py`, `services/outlook.py` and `services/msgraph.py` already handle these responses with a resync (both have handling for them; behaviour per `docs/microsoft-graph-failure-ledger.md`); keep the window short; T+15m checks every integration's `last_success_at` |
| E-8 | **Split brain: both stacks running.** Render resumed or rebuilt by mistake while the server runs, so two processes poll the same mailboxes and write the same calendars from different databases | L–M | H | Render dashboard (suspended); duplicate events reported | P-2 (auto-deploy off, hooks regenerated); rollback always stops the server's Selko **before** resuming Render (§D); on the server, one process per data directory (`.selko.lock`) |
| E-9 | **Calendar write in flight at the freeze.** A work item cancelled after the provider accepted the write but before completion was recorded. The new process retries it, possibly creating a duplicate or reapplying an update | M (if the freeze lands during delivery) | M | Q0.8 at the freeze records `calendar_work_items` in `processing`; after C-10 the operator checks those users' calendars | the freeze waits up to 5 min for processing = 0; dedup read-back against the mirror (`services/calendars.py:317`) before a create; the window at the lowest-traffic hour |
| E-10 | **Duplicate ingestion after cutover.** Emails re-discovered from carried cursors are inserted again | L | M | `emails` count stable for known messages; the unique index violations are visible as errors | the unique keys `emails (user_id, email_provider, provider_message_id)` and `email_ingestion_items (integration_id, provider_message_id)` are ported, so re-discovery is an upsert, not a duplicate |
| E-11 | **Attachment volume or size.** Total bytes unknown (Q0.4); a 50 MiB object over a slow link; Storage throttling; the final delta too slow for the window | M | M | Q0.4; the warm copy durations (P-13); the `attachments` counts line | warm copies before the freeze; restartable per object; the delta at the freeze is only what arrived since the warm copy |
| E-12 | **Startup recovery incomplete.** A `running` row in `email_sync_runs` blocks every new run for its integration; a leased row of a forgotten table stays leased | M | H (ingestion silently stops for some users) | `ingestion` surface `items_stalled_seconds`; T+15m per-integration checks | `selko.db.startup.reset_leases_at_startup` releases every lease and marks `running` runs `abandoned` before the workers start; the image lane boots on an imported database |
| E-13 | **Server memory.** The import, or Selko over 400 MB once running (the history includes an OOM at ~2 MB/min, #191) | M | M | `docker stats` at T+0/T+15m/T+24h; OOM-kill count | the import runs while the server is stopped (the lock enforces it); 500-row batches; the server has a 400 MB limit |
| E-14 | **Server disk.** `selko.db` larger than expected because TOAST compression is lost, plus rehearsal copies, `backups/pre-NNNN.db`, WAL and attachments | M | H (a full disk stops writes) | Q0.3 sizes; P-11; `df` at every deploy-log window | the P-11 rule; rehearsal outputs deleted |
| E-15 | **Clock.** Server clock skew breaks lease expiry, retry timing, JWT `exp`/`iat`, OAuth token-expiry checks and Gmail/Graph request signing | L | M | `timedatectl` at P-11; JWT failures in Sentry | NTP synchronised (P-11); leases and timestamps always taken from one clock (the server's) |
| E-16 | **Backup gap.** No snapshot between the import and the first nightly snapshot | M | H | the snapshot list at T+0 and T+24h | a manual snapshot at C-6; a first restore test within 7 days (restore a snapshot to a scratch disk, run `PRAGMA integrity_check`) |
| E-17 | **TLS issuance delay.** Certificates for the real names can only be issued once DNS points at the server, so there are minutes of TLS errors; repeated failures hit the CA's rate limits | M | M | C-9 | low TTL; the server's own runbook may pre-issue with DNS-01 (not in this repository) |
| E-18 | **DNS stragglers.** Resolvers or clients that cache past the TTL keep reaching Render for minutes to hours | M | L | Render request metrics (the dashboard) after C-9 | Render is **suspended**, so stragglers see an error, never a write to the old database |
| E-19 | **Write freeze leaks.** A writer is missed (a dashboard edit, a Render worker still running), so rows changed after a table's export are silently lost | L | H | the Q0.7 fingerprint taken twice at C-3 | Render suspended at C-2; the fingerprint must be equal or the window aborts. The importer does not re-check the source after the load (§B.3) |
| E-20 | **The source connection lacks a privilege** (`auth.users`, `storage.objects`, `pg_stat_all_tables`) or the pooler times out a long export | M | M | the rehearsal (P-9) | the session pooler with the `postgres` user; the rehearsal measures the duration |
| E-21 | **`main` is SQLite code while production still runs Postgres code** (until the cutover). Any Render rebuild of `main`, or a hotfix branched from `main`, takes production down | M | H | P-1/P-2 | Render never builds `main` (P-2); a hotfix before the cutover branches from `LAST_PG_SHA` |
| E-22 | **Privacy-policy promise broken.** Processors change without the notice the policy promises | L | M | P-5/P-6 | notice ahead (P-5); the policy already names Google Cloud and no longer Supabase or Render. **UNKNOWN:** whether the Google OAuth app's verification for restricted Gmail scopes must report a change of hosting (Google Cloud Console → OAuth consent screen) |
| E-23 | **Notification noise at startup.** Every integration looks overdue when the new process starts; the incident evaluator may send `stale_poll` "opened" emails and then "resolved" ones | H | L | the operator's inbox | expected; noted in the deploy log; carried `operational_incidents` prevent duplicates for incidents already open |
| E-24 | **Sessions.** Every web user is signed out | H (certain) | L | — | P-5 notice; existing passwords keep working (bcrypt carried) |
| E-25 | **Import and server from different commits.** The schema the importer writes differs from what the server expects | L | M | the server migrates at startup and refuses a ledger it does not know | use the importer image of the same commit as the app (P-12); the importer applies the server's own migration chain. **Not built:** a `schema_version` field in `/health` |

