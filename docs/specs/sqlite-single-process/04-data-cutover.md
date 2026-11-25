# 05 — Data conversion, import tool, cutover, rollback, risks (Q7)

Part of the plan for `docs/specs/sqlite-single-process.md`. This file covers
increment Q7 (cutover) and the import tool it needs. Everything here was read
from the repository and the local stack on 2026-11-25: the local database
with all 120 migrations applied, PostgreSQL 17.6. Anything that can only be
measured in production is marked **UNKNOWN:** with the way to find it out.

The target host is called **the VM**. TLS is terminated by **its reverse
proxy**. Nothing in this file describes how the VM is reached or what else
runs on it. That belongs to the VM's own (private) runbook, because this
repository is public.

Owners: **operator** = Toni; **agent** = a Claude session. "On the VM" means
whoever holds the VM's access, using the VM's own access procedure.

---

## A. Data conversion, table by table

### A.1 Conversion rules (one codec, used by the importer and by `selko/db/`)

The live public schema has **30 base tables** and 1 view (`email_sync_health`,
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
| M | `numeric(10,6)` (only `llm_call_log.estimated_cost_usd`) | `REAL`, same name (decision D6) | `float(value)` | `round(col, 6)::text` | `printf('%.6f', col)` |
| R | unconstrained `numeric` (only `photos.location_latitude/longitude`) | `REAL` | `float(Decimal)` | excluded from C1, checked by C2 | excluded from C1 |

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
- **Every other value goes through Python** (asyncpg's native types, then the
  codec), while the Postgres side of the checksum is computed by Postgres
  itself with `to_char`. These are two independent implementations, so a
  codec bug shows up as a checksum mismatch instead of being hashed the same
  on both sides.

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

SQLite side: the same row expression in SQL, with `cell()` and `h60()`
registered as deterministic Python functions on the connection
(`create_function`), and sum/xor taken in Python. On 2026-11-25 both sides
were computed for local `global_limits`: Postgres
`3 | 1455107210497170496 | 855236598025236146`, and SQLite (loaded through
the codec) the same three numbers.

The importer generates the per-table statement from its **pinned column
map** (§B.2), never from `information_schema` at run time. Schema drift
therefore fails closed (exit 3) instead of being checked against itself.

**C2** (only `photos.location_*`): merge both sides by `id` ordered with
`COLLATE "C"` (Postgres) and BINARY (SQLite). Requirement: `|a − b| ≤ 1e-9`
and NULL ↔ NULL.

**Structural checks after the load**, all of which must pass:
`PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` returns 0 rows;
`PRAGMA user_version` = the head of the image's migration chain; the set of
triggers and indexes in `sqlite_master` (name + SQL) is identical to a fresh
`0001…` database; every T column matches
`^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$`; and `selko.db.invariants` (the
Python port of the six invariant triggers, Q6) reports 0 violations.

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

**Carry all rows.** The single owner of calendar delivery state. Rows in `processing` at the freeze are counted in step C-6 (their provider write may or may not have happened; see risk E-9). `desired_event` is JSON. Verification: C1 over all 21 columns.

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

**Carry all rows.** A row left `running` by the freeze is carried as `running`; the partial unique index `email_sync_runs_one_running_per_integration` means no new run can start for that integration until startup recovery marks it `abandoned` (a Q6 requirement this plan depends on; risk E-12). Verification: C1 over all 16 columns.

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

**Carry all rows.** `provider` is enum `integration_provider` → TEXT + CHECK `IN ('gmail','google_photos','google_calendar','outlook')`. `checkpoint` is JSON. Verification: C1 over all 24 columns.

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
| `last_photo_sync_at` | timestamptz | TEXT | T | yes |

**Carry all rows. Holds secrets.** `access_token` (NOT NULL) and `refresh_token` are OAuth tokens stored **in plaintext** today: no migration uses `pgcrypto`, `pgp_sym_*` or Vault (grep of `supabase/migrations`, 2026-11-25; `vault.secrets` has 0 rows locally), and `services/integrations.py` writes them through the save RPC as `p_access_token`/`p_refresh_token` and reads them back as `row["access_token"]` with no decryption. So there is no encryption key to carry: the values are copied as TEXT byte for byte. They are hashed into C1 like any column and **never printed**: the importer's error messages for this table name the column only, never the value or the row id (§B.8). `scopes` is `text[]` → JSON array. `sync_cursor` is the Gmail `historyId` (decimal text). `provider`/`status` are enums → TEXT + CHECK. On the VM the tokens sit in plaintext in `selko.db`, its WAL, every `pre-<sha>.db` copy and every disk snapshot (risk E-5). Verification: C1 over all 14 columns.

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

#### `photos` (25 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `google_photo_id` | text | TEXT | X | NOT NULL |
| `filename` | text | TEXT | X | yes |
| `description` | text | TEXT | X | yes |
| `mime_type` | text | TEXT | X | yes |
| `date_taken` | timestamptz | TEXT | T | yes |
| `width` | integer | INTEGER | I | yes |
| `height` | integer | INTEGER | I | yes |
| `location_latitude` | numeric | REAL | R | yes |
| `location_longitude` | numeric | REAL | R | yes |
| `location_display_name` | text | TEXT | X | yes |
| `storage_path` | text | TEXT | X | yes |
| `content_hash` | text | TEXT | X | yes |
| `processing_status` | text | TEXT | X | NOT NULL |
| `processing_error` | text | TEXT | X | yes |
| `processed_at` | timestamptz | TEXT | T | yes |
| `locked_until` | timestamptz | TEXT | T | yes |
| `locked_by` | text | TEXT | X | yes |
| `attempts` | integer | INTEGER | I | NOT NULL |
| `max_attempts` | integer | INTEGER | I | NOT NULL |
| `next_retry_at` | timestamptz | TEXT | T | yes |
| `dead_letter_reason` | text | TEXT | X | yes |
| `dead_letter_at` | timestamptz | TEXT | T | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |

**Carry all rows** (Google Photos ingestion is parked; Q0.2 should count 0). `location_latitude`/`location_longitude` are unconstrained `numeric` → REAL. They are excluded from C1 and checked by C2 instead (|pg::float8 − sqlite| ≤ 1e-9 per row, merged by `id`); Q0.6 records their maximum scale. Verification: C1 over the other 23 columns, plus C2.

#### `scheduled_tasks` (12 columns)

| Column | Postgres | SQLite | Conv. | Null |
|---|---|---|---|---|
| `id` | uuid | TEXT | U | NOT NULL |
| `user_id` | uuid | TEXT | U | NOT NULL |
| `task_type` | text | TEXT | X | NOT NULL |
| `payload` | jsonb | TEXT | J | NOT NULL |
| `status` | text | TEXT | X | NOT NULL |
| `scheduled_at` | timestamptz | TEXT | T | NOT NULL |
| `locked_until` | timestamptz | TEXT | T | yes |
| `locked_by` | text | TEXT | X | yes |
| `created_at` | timestamptz | TEXT | T | NOT NULL |
| `started_at` | timestamptz | TEXT | T | yes |
| `completed_at` | timestamptz | TEXT | T | yes |
| `last_error` | text | TEXT | X | yes |

**Carry all rows.** CHECK `task_type IN ('photo_fetch','email_fetch')`. CLAUDE.md says no `email_fetch` task exists any more, so expect historical rows only. Verification: C1 over all 12 columns.

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

Selko needs these columns. All of them exist in local `auth.users`
(GoTrue schema, checked 2026-11-25):

| auth.users column | Postgres | `accounts` column | SQLite | Conv. | Null |
|---|---|---|---|---|---|
| `id` | uuid | `id` | TEXT PK | U | NOT NULL |
| `email` | varchar | `email` | TEXT UNIQUE | X | yes in GoTrue; NOT NULL in `accounts` (Q0.5 must count 0 NULL emails) |
| `encrypted_password` | varchar | `password_hash` | TEXT | X, verbatim bcrypt `$2a$10$…` (spec §2: Python `bcrypt` verifies it) | yes |
| `created_at` | timestamptz | `created_at` | TEXT | T | NOT NULL in `accounts` (Q0.5 counts NULLs; the importer fails on one) |
| `updated_at` | timestamptz | `updated_at` | TEXT | T | yes |
| `email_confirmed_at` | timestamptz | `email_confirmed_at` | TEXT | T | yes |
| `last_sign_in_at` | timestamptz | `last_sign_in_at` | TEXT | T | yes |
| `banned_until` | timestamptz | `banned_until` | TEXT | T | yes |
| `deleted_at` | timestamptz | `deleted_at` | TEXT | T | yes |
| `is_anonymous` | boolean | — (checked, not carried) | — | — | Q0.5: must be 0 rows with `true`, else stop |
| `is_sso_user` | boolean | — (checked, not carried) | — | — | Q0.5: must be 0 rows with `true`, else stop |

Not carried: `confirmed_at` (a generated column in GoTrue, derived from
`email_confirmed_at`), `phone` (Q0.5 must count 0 non-NULL), `raw_user_meta_data`
(the display name lives in `public.users.display_name`), `aud`, `role`, and
all GoTrue session, refresh-token, identity and MFA tables. **Every web user
signs in again after cutover** (spec §4.8); old sessions are not carried.

Rows skipped: none. A row with `deleted_at` or a future `banned_until` is
carried as is, and the new sign-in refuses it, exactly as GoTrue does today.

**If Q5 has already created `public.accounts` on Postgres** (the spec says Q5
fills it from `auth.users` and moves sign-in to it), then **`public.accounts`
is the source** and `auth.users` is only cross-checked. The check: every
`public.users.id` has an `accounts` row, and every `auth.users` row created
before the Q5 switch has an `accounts` row with an identical `password_hash`
or a later `updated_at`. **UNKNOWN:** the exact `public.accounts` and
refresh-token columns until Q5 is written. Q5 must pin them, and the
importer's column map takes them from Q5's migration. Refresh tokens are
**not carried** in either case.

Verification: C1 over the 9 carried columns (source side computed on the
same 9 columns), plus `count(accounts) = count(source)` and
`count(users) ≤ count(accounts)` with every `users.id` present.

#### `storage.objects` (bucket `attachments`) → `/data/attachments/`

`storage.buckets` holds exactly one bucket, `attachments` (private, 50 MiB
file limit, a MIME allowlist). `storage.objects` is **not** turned into a
table. Each object becomes one file:

| Source | Target |
|---|---|
| `storage.objects.name` (= `attachments.storage_path`, written as `"{user_id}/{unique_id}_{safe_filename}"` by `services/attachments.py:197`) | file `/data/attachments/<name>`, mode 0600, directories 0700, owned by the container user |
| object bytes, via the Storage API (§B.7) | file content, written to `<name>.part`, fsynced, then renamed |
| `metadata->>'size'` | checked against the file's length |
| `metadata->>'mimetype'` | not carried (`attachments.mime_type` already has it) |

The path is carried **verbatim** instead of being renamed to
`<user_id>/<attachment_id>` (spec §4.1). That keeps `attachments.storage_path`
unchanged, so its C1 checksum still proves the mapping. New writes may use
the §4.1 layout. `selko/db/` must resolve files through the `storage_path`
column and never derive a path from the id (a Q6 requirement). Every name
must match `^[0-9a-f-]{36}/[A-Za-z0-9._-]+$`, and its first segment must
equal the referencing row's `user_id`. Otherwise the importer stops with
exit 5 (no path traversal, no cross-user file).

Rows skipped:
- **Orphan objects** (an object no `attachments` row references) are **not
  copied**, and their count and bytes are reported. Nothing could ever read
  them.
- **Rows whose object is missing at the source** carry over unchanged (the
  row is still true history). They are counted, and their ids are written
  to the 0600 error file.

Verification (§B.9): every `attachments` row with a non-NULL `storage_path`
has a file. For rows with `content_hash`, the file's SHA-256 equals it; for
the rest, the file's length equals `metadata->>'size'`. Totals of count and
bytes match the source minus orphans.

---

## B. The import tool: `selko import-from-postgres`

### B.1 Where it lives and why there

- Package **`selko_import/`** (top level, beside `selko/`, not inside it),
  console script `selko` → subcommand `import-from-postgres`. It is installed
  in the production image from a uv dependency group `import` that carries
  `asyncpg` (already a dependency today) and `httpx` (already one).
- Why not under `selko/`: Q6's done-criterion is a test that `supabase` and
  `asyncpg` are **not importable from `selko`**. The importer is the one
  place that still needs a Postgres driver. Keeping it as a sibling package
  lets that test stay strict, and it is deleted in Q8.
- It imports `selko.db.codec` (the A.1 codec), `selko.db.migrations` (the
  same chain the server runs at startup) and `selko.db.invariants`. So the
  file it writes is, by construction, the schema the server expects.
- It runs **on the VM, in the signed image, pinned by digest**, never in
  Actions: this repository is public, and a workflow artifact or log would
  expose user data (spec §5, Q7).

### B.2 Inputs

| Input | How | Never |
|---|---|---|
| `SOURCE_DATABASE_URL` | key in a **secrets file** (`--secrets PATH`, default `/run/secrets/import.env`), `KEY=value` lines. The value is the session-pooler URL of the production **read-only role** (the same role whose URL is the Actions secret `PRODUCTION_SUPABASE_READONLY_DB_URL`; the operator copies it from the Supabase dashboard, since Actions secrets cannot be read back) | on a command line, in an environment variable, in a log |
| `SOURCE_SUPABASE_URL` | same file: `https://khahcozfbnpykspvatrg.supabase.co` | — |
| `SOURCE_STORAGE_KEY` | same file: a Supabase **secret API key created only for the import** (§B.7) | printed, logged, kept after T+1h |
| `--target DIR` | the data volume, default `/data` | — |
| pinned column map | `selko_import/columns.py`: for every table, the ordered `(column, pg_type, code)` list from §A.3, plus the skip and filter rules | read from `information_schema` at run time |

The file must be mode 0600 and owned by the running uid, or the importer
exits 2 before reading it. It is mounted read-only into the container
(`-v <file>:/run/secrets/import.env:ro`). On open the importer checks
`SHOW server_encoding` = `UTF8` and `SHOW TimeZone`. It sets
`SET TIME ZONE 'UTC'`, `SET statement_timeout = 0` and
`SET idle_in_transaction_session_timeout = 0` for its own session only.

### B.3 Source reads: one consistent snapshot, read only

- One connection, one transaction:
  `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`. Every table is
  exported, and its source C1 computed, inside this snapshot, so the export
  is a single point in time even if a writer were still alive. The fingerprint
  check (§C, C-7) separately proves there is none.
- Preflight in the snapshot. Each of these exits 3 or 4 on failure:
  `has_table_privilege(<t>, 'SELECT')` for the 30 tables, `auth.users`
  (or `public.accounts`) and `storage.objects`; the live column list of
  every table equals the pinned map (names, order and `udt_name`); no
  `infinity`/`-infinity` timestamps; no multi-dimensional arrays; no
  fractional `time` values. Q0.6 measures the same conditions ahead of time.
- Per table: `DECLARE … CURSOR FOR SELECT <cols> FROM public.<t> [WHERE <filter>]`
  through asyncpg's `connection.cursor(query, prefetch=200)`. J columns are
  selected as `col::text` and A columns as `to_json(col)::text`. No
  `ORDER BY` is needed: the load is order-independent, and FKs are satisfied
  by the table order (§B.5).

### B.4 Memory bound (~1 GB-RAM VM)

- The container runs with `--memory 384m` while the Selko server is **not**
  running (they never run together; §B.10).
- Rows are batched by **whichever limit comes first: 500 rows or 16 MiB of
  cell bytes**. The asyncpg prefetch is 200 rows. One SQLite transaction is
  committed per batch. SQLite runs with `PRAGMA cache_size = -16384` (16 MiB),
  `journal_mode = OFF` and `synchronous = OFF` while loading. That is safe
  because the file is a scratch file which a failed run deletes. After
  verification the file is switched to `journal_mode = WAL` and
  `synchronous = NORMAL` (spec §4.1).
- Expected peak: Python + asyncpg + one 16 MiB batch decoded twice, plus the
  prefetch of the largest rows. Q0.3's `max(octet_length(body_text))` and
  `max(octet_length(prompt_text))` size the prefetch: if 200 × that maximum
  exceeds 64 MiB, the importer lowers the prefetch for that table to
  `floor(64 MiB / max)`, with a minimum of 1. Peak RSS (`ru_maxrss`) goes
  into the report. Acceptance: below 300 MiB in the dry run.
- Attachment downloads stream in 1 MiB chunks to disk. At most 4 run at
  once. Nothing is held in memory.

### B.5 Writing: fresh file, new schema, FK on, atomic rename

1. Refuse (exit 8) if `DIR/selko.db` exists (unless the mode is
   `--dry-run`), if free space in `DIR` is below the requirement of §C P-12,
   or if another process holds `DIR/.selko.lock`. The server holds an
   exclusive `flock` on that file for its lifetime (a Q6 requirement), so
   the importer can never write while a server runs, and two servers can
   never share the file. The importer itself takes `DIR/.import.lock`.
2. Create `DIR/selko.db.importing` (after deleting any leftover). Apply the
   image's migration chain with the server's own code, then save and drop
   **every trigger and every non-PK index** (their `sqlite_master.sql` is
   kept in memory). Set `PRAGMA foreign_keys = ON`.
3. Load the tables in FK order:
   `accounts` → `users` → `global_limits` → `integrations` → `email_folders`
   → `email_sync_state` → `email_sync_runs` → `integration_recoveries` →
   `emails` → `attachments` → `email_calendar_components` →
   `email_ingestion_items` → `events` → `event_sources` →
   `event_change_proposals` → `calendar_entries` → `calendar_mirror_state`
   → `event_identity_hints` → `calendar_work_items` → `calendar_sync_log` →
   `action_history` → `sender_rules` → `user_calendar_settings` →
   `usage_quotas` → `scheduled_tasks` → `llm_call_log` →
   `operational_incidents` → `graph_api_failures` → `event_repair_audit` →
   `photos`. (`oauth_states` is skipped.) There is no cycle among the 56
   foreign keys, so no deferral is needed. A CHECK or FK failure is exit 5.
4. Recreate the saved indexes, then the saved triggers, verbatim. A unique
   index that fails to build is exit 5.
5. Verify (§B.9). On success: `PRAGMA journal_mode = WAL`,
   `PRAGMA wal_checkpoint(TRUNCATE)`, fsync the file and `DIR`, then
   `os.rename(selko.db.importing, selko.db)` and fsync `DIR` again. The
   rename is the only step that makes the result visible, and it is atomic.
   The file and the attachment tree are chowned to the server's uid, mode 0600.
6. On any failure: delete `selko.db.importing` and the WAL/SHM files, keep
   the report, and exit non-zero. `selko.db` is never touched.

### B.6 Why triggers are dropped during the load

The SQLite ports of `parse_provider_labels_trigger` (which recomputes the
`emails.is_*` flags), `integrations_ensure_email_sync_state` (which inserts
`email_sync_state` rows), the `updated_at` triggers (which would overwrite the
carried `updated_at`) and the owner-check triggers would change carried
values or insert extra rows. The import is a **pure copy**. All state repair
(lease expiry, abandoning `running` sync runs) is left to the server's
startup recovery, which already has to exist for crashes. A copy that
changes nothing can then be checked by checksum.

### B.7 Attachment copy

- Object list: from `storage.objects WHERE bucket_id = 'attachments'` in the
  same read-only snapshot (name, `metadata->>'size'`), joined to
  `public.attachments` on `storage_path` to tag orphans and fetch
  `content_hash`.
- Bytes: `GET {SOURCE_SUPABASE_URL}/storage/v1/object/authenticated/attachments/{name}`.
  The URL-encoded `name` uses headers `Authorization: Bearer <key>` and
  `apikey: <key>`, with httpx streaming, a 60 s read timeout and 3 retries
  with backoff on 5xx/429/connection errors. A 404 counts as
  "missing at source". Any other 4xx is exit 7.
- **Credential.** Storage has no read-only key. Reading private objects needs
  the service role. Use a **dedicated secret API key**
  (Supabase dashboard → Project Settings → API Keys → Secret keys → "Create
  new secret key", named `cutover-import`), so it can be deleted after the
  import without touching the key Render uses. That keeps rollback intact.
  **UNKNOWN:** whether project `khahcozfbnpykspvatrg` has moved to the new
  API-key system (publishable/secret keys). Find out in the dashboard under
  API Keys. If it only has the legacy JWT `service_role` key, that key is
  the credential: it cannot be revoked separately, so it is rotated at Q8
  when the project is deleted, and kept only in the 0600 secrets file until then.
- **Restartable and incremental.** A file that already exists with the
  right length (and SHA-256 when `content_hash` is set) is skipped. The copy
  is therefore safe to run early (`--attachments-only`, at T-1d and T-1h)
  and then again for only the delta at the freeze. Local files that no
  longer correspond to a source object are moved to
  `DIR/attachments.removed/` and counted, never silently deleted.
- At the final run every local file is re-hashed (a local disk read), so a
  file copied early and changed at the source afterwards is caught.

### B.8 Progress and logs: counts only

- stdout/stderr carry **only** table names, column names, counts, byte
  totals, durations and exit reasons, in lines like
  `table=emails rows=12000/45210 bytes=310MiB elapsed=41s`.
- Never written to stdout/stderr: cell values, ids, emails, file names,
  storage paths or URLs with tokens. Every exception is caught at the
  table boundary and re-raised as `ImportError(table, column, row_ordinal,
  error_class)`, and the original message is **not** printed (SQLite and
  asyncpg messages can contain values). A test feeds a canary token value
  through a failing row and asserts it appears in no output.
- Detail that the operator needs (the ids of failing rows, missing objects,
  orphans) goes to `DIR/import-errors-<utc>.jsonl`, mode 0600, which the
  operator deletes after reading.

### B.9 Verification report and acceptance thresholds

The report is written to `DIR/import-report-<utc>.json` (0600) and printed
as a counts-only table:

```
table                    source   target  skipped  C1      C2
emails                    45210    45210        0  match   -
oauth_states                  2        0        2  -       -
...
structural: integrity_check=ok fk_violations=0 user_version=<n> triggers=match indexes=match ts_format_violations=0 invariant_violations=0
snapshot: fingerprint_before=<n> fingerprint_after=<n> source_c1_recheck=match
attachments: source_objects=<n> referenced=<n> copied=<n> already_present=<n> orphans_skipped=<n> missing_at_source=<n> hash_mismatch=0 bytes=<n>
resources: peak_rss_mib=<n> duration_s=<n> db_bytes=<n> attachments_bytes=<n>
```

**Acceptance. A single miss fails the import, with exit 6 or 7:**

| Check | Threshold |
|---|---|
| Row count per carried table | target = source (with the same `WHERE` for filtered tables), **0 tolerance** |
| C1 per table | all three components equal, **0 tolerance** |
| C2 (`photos.location_*`) | every pair within 1e-9; NULL ↔ NULL |
| Skipped rows | only `oauth_states` (all), plus `llm_call_log` older than `--llm-log-since` if the owner chose that; nothing else |
| `integrity_check` / `foreign_key_check` | `ok` / 0 rows |
| Triggers and indexes | identical to a fresh migration-chain database |
| Timestamp format | 0 violations of the A.2 regex in every T column |
| Invariants (`selko.db.invariants`) | 0 violations |
| Source re-check | source C1 recomputed in a **second, new** snapshot after the load equals the first, and the write fingerprint (Q0.7) is unchanged. This proves nothing wrote during the export |
| Attachments | `hash_mismatch = 0`; `missing_at_source` ≤ the count recorded by dry run #2 (pre-existing loss is listed, never new loss); every referenced object present locally |
| Peak RSS | < 300 MiB |
| Duration (final run) | ≤ 20 min. If dry run #2 takes longer, the window plan in §C is redone before the go/no-go |

### B.10 Modes and exit codes

```
selko import-from-postgres --secrets FILE --target DIR [mode] [options]
  (no mode)            full import + verification + atomic rename
  --dry-run            full import + verification into DIR/dryrun-<utc>/, never renamed to selko.db
  --attachments-only   copy/refresh attachment files only (restartable; safe while production runs)
  --measure[=SET]      read-only Q0 queries, counts and sizes only (SET: all|sizes|users|domains|fingerprint|inflight)
  --verify-only        recompute target C1 and structural checks against an existing report (no source needed)
  --delta-since=ISO    rollback aid (§D): per-table counts of target rows created/updated after ISO; ids to the 0600 file
  options: --llm-log-since=ISO  --batch-rows=500  --batch-bytes=16MiB  --download-concurrency=4
```

| Exit | Meaning |
|---|---|
| 0 | success: all thresholds met (in full mode, `selko.db` is in place) |
| 2 | usage, or a secrets file missing, unreadable or wrongly permissioned |
| 3 | source schema drift: live columns ≠ pinned map, or a domain precondition failed (infinity, ndims, fractional time, anonymous/SSO users, NULL email) |
| 4 | source unreachable, or a SELECT privilege missing |
| 5 | conversion or constraint failure while loading (CHECK, FK, unique, invalid storage path) |
| 6 | verification mismatch (counts, C1, C2, structure, invariants, source re-check) |
| 7 | attachment copy failure (non-404 4xx, hash mismatch, new missing objects) |
| 8 | target refused: `selko.db` exists, not enough disk, or the lock is held by a server or another import |
| 9 | interrupted (SIGINT/SIGTERM): the scratch file is deleted, attachment files stay (restartable) |

### B.11 Dry runs and tests

- **CI lane `import-from-postgres`** (added to `scripts/lanes.toml` in Q7,
  removed in Q8). Against local Supabase seeded by
  `scripts/seed_screenshot_data.py`, plus an edge-value fixture: NULL in
  every nullable column, 1970 and 2099 timestamps, timestamps with exactly
  `.000000` microseconds, non-BMP Unicode in text, arrays holding quotes,
  backslashes and the empty array, JSON with `2.50` and nested arrays, the
  maximum `numeric(10,6)`, one `processing` row of each leased table, one
  `running` sync run, one orphan object and one missing object. The lane
  runs `--dry-run` and requires exit 0. Then it deliberately corrupts one
  target cell and requires `--verify-only` to exit 6. **A check that is
  never shown to fail is decoration.**
- **Dry run #1 (T-7d) and #2 (T-1d) against production,** on the VM,
  read-only, with `--dry-run`. Afterwards, the server image is started
  against the dry-run file with `ENABLE_BACKGROUND_PROCESSING=false`, behind
  the temporary hostname (§C P-9). The operator signs in with their
  existing password and compares the review-queue counts. Then the dry-run
  directory is deleted (it holds real user data). Workers must stay off for
  this boot, or the dry-run copy would poll mailboxes and write calendars
  in parallel with production.

---

## C. Cutover runbook

### C.0 Q0 measurements: the exact read-only SQL

Q0 runs early, before Q1 starts. At that point no import image exists yet,
so it runs as a new content-free `ops.yml` operation `measure-production`.
That operation has the same posture as `rehearse-cutover`: the
`PRODUCTION_SUPABASE_READONLY_DB_URL` secret, a `READ ONLY` transaction,
and output piped through `scripts/ops.py redact`. Counts and sizes only. The
Actions log is public, so the user count becomes public: **the owner decides
whether that is acceptable.** If it is not, only Q0.5 runs later on the VM,
through `--measure=users`. From Q7 on, every query below also runs on the VM
through `--measure`. Every statement was run against the local stack on
2026-11-25.

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
SELECT (SELECT count(storage_path) FROM public.emails) AS email_paths, (SELECT count(storage_path) FROM public.photos) AS photo_paths;
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
SELECT max(scale(location_latitude)), max(scale(location_longitude)), count(location_latitude) FROM public.photos;
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
services (P-2); and the VM's free disk and memory (P-12).

### C.1 Health invariants: which hold, which change

`scripts/check-production-health.sh` and `scripts/assert-health.sh` must
work against **both** stacks during the window. A Q7 change makes
`assert-health.sh` pick its rules by the engine that `/health` publishes:
the Q6 server adds `"database": {"engine": "sqlite", "schema_version": N}`,
and the old stack has no such field.

| Surface | Old stack (Render + Supabase) | New process | Why |
|---|---|---|---|
| `root` | 40-char `build_sha`, status ok/degraded, `server_errors_per_hour == 0` | **unchanged**, plus `.database.engine == "sqlite"` and `.database.schema_version` equal to the image's head | release identity, and 5xx still matter |
| `work-state` | `items_dead_letter`, `attachments_dead_letter`, `stale_processing_emails`, `unclaimable_pending` all 0 | **unchanged** (same counters, now computed by `selko/db/`) | lost or stuck work is never acceptable |
| `ingestion` | status ok, background on, every task alive, `listener.connected`, `items_stalled_seconds ≤ 1800` | **`listener.connected` removed** (there is no pg listener; an in-process bus that always reports connected would be a signal that cannot fail); the rest unchanged | — |
| `egress` | `transport == "asyncpg"` | **`transport == "sqlite"`** and no `supabase` destination in the byte counters | proves the old transport is gone, not merely idle |

While workers are off (steps C-11 to C-15), `ingestion` is expected to fail
and is recorded as such. Only `root` and `work-state` gate those steps.

### C.2 Prerequisites (T-14d to T-1h)

| # | When | Owner | Step | Exact command or action | Done when |
|---|---|---|---|---|---|
| P-1 | before Q6 merges | agent | Record the last Postgres build | `curl -fsS https://api.selkoapp.com/health \| jq -r .build_sha` → written into this spec as `LAST_PG_SHA` | recorded |
| P-2 | before Q6 merges | agent, then operator | Render must never build `main` again: after Q6, `main` is SQLite code and would crash on Render | agent: `curl -fsS 'https://api.render.com/v1/services?limit=50' \| jq -r '.[].service \| [.id,.name,.type,.autoDeploy,.suspended] \| @tsv'` (the cloud session's network secret supplies the key). Operator: in Render dashboard → each service → Settings → Auto-Deploy → **No**; then Settings → Deploy Hook → **Regenerate** (invalidates the hook URL that `ops.yml` still holds) | both services `autoDeploy` = `no`; ids recorded as `API_ID`, `WEB_ID` |
| P-3 | T-14d | agent | Q0 numbers recorded in the spec | §C.0 (`measure-production`, then on the VM `--measure=all`) | numbers in spec |
| P-4 | T-14d | agent | Auth config read | Q0.5 curl | `mailer_autoconfirm` recorded |
| P-5 | T-14d | operator | OAuth consoles hold the callbacks the new process uses. **The hostname does not change** (`api_public_url` builds them; `services/integrations.py:686-690`), so normally nothing is edited | Google Cloud Console → APIs & Services → Credentials → the OAuth client whose id is `GOOGLE_CLIENT_ID` → *Authorized redirect URIs* contains `https://api.selkoapp.com/integrations/google/callback`. Microsoft Entra → App registrations → the app `MICROSOFT_CLIENT_ID` → Authentication → Web → *Redirect URIs* contains `https://api.selkoapp.com/integrations/microsoft/callback`; Certificates & secrets → client-secret expiry later than T+30d | both present, secret valid |
| P-6 | T-7d | operator | Notify users. The privacy policy (`frontend/src/routes/privacy/+page.svelte`, "Changes") promises notice *before* a change in how data is handled | email to every account: date and window, "you will need to sign in again", "the iOS/Android apps stop working" | sent |
| P-7 | T-7d | agent | Privacy policy and its test in the cutover SHA: remove **Supabase** and **Render** from "Who else handles your data", add the VM's hosting provider (the operator gives the name; once published it is public by design) and **Sentry**, which receives error reports today but is not listed; bump `lastUpdated`; update `frontend/src/routes/privacy/__tests__/page.test.js` (it asserts `'Supabase:'` and `'Render:'`) | PR merged into the image that will be approved | page and test updated |
| P-8 | T-7d | operator | Secrets file for the server on the VM (outside `/data`, mode 0600). Values are copied from Render dashboard → API service → Environment; **an agent never reads them** | keys: `ENVIRONMENT=production`, `API_PUBLIC_URL=https://api.selkoapp.com`, `FRONTEND_URL=https://selkoapp.com`, `ALLOWED_ORIGINS=https://selkoapp.com,https://www.selkoapp.com,https://cutover.selkoapp.com` (the last one until C-27), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_FALLBACK_PROVIDER=none` (CLAUDE.md: must stay explicit), the provider's API key, `SENTRY_DSN`, `OPERATIONAL_NOTIFICATION_SENDER/RECIPIENT/API_KEY/WEBHOOK_URL` (those set on Render), the new JWT secret (generated on the VM straight into the file: `python3 -c 'import secrets;print("AUTH_JWT_SECRET="+secrets.token_urlsafe(48))' >> FILE`; the variable name comes from Q5), and **`ENABLE_BACKGROUND_PROCESSING=false`** | operator confirms the key list against Render's (names only) |
| P-9 | T-3d | operator | Temporary hostname `cutover.selkoapp.com` → the VM (Cloudflare dashboard → DNS → Add record, **DNS only**); the reverse proxy routes it to Selko. **Do not look it up before creating it**: the zone's negative TTL is 1800 s (SOA, 2026-11-25) | record exists; `curl -sI https://cutover.selkoapp.com` gets a TLS handshake | — |
| P-10 | T-7d, T-1d | operator (secrets), agent or operator (run) | Dry runs #1 and #2 (§B.11). Import secrets file `import.env` (0600, outside `/data`): `SOURCE_DATABASE_URL`, `SOURCE_SUPABASE_URL=https://khahcozfbnpykspvatrg.supabase.co`, `SOURCE_STORAGE_KEY` (the `cutover-import` key, §B.7) | `cosign verify <image>@sha256:<digest> --certificate-oidc-issuer https://token.actions.githubusercontent.com --certificate-identity-regexp '^https://github.com/tonimelisma/selko/\.github/workflows/<Q4 image workflow>\.yml@refs/heads/main$'`, then `docker run --rm --memory 384m --read-only --tmpfs /tmp -v <data volume>:/data -v <dir>/import.env:/run/secrets/import.env:ro <image>@sha256:<digest> selko import-from-postgres --target /data --dry-run` | exit 0, every §B.9 threshold met, boot test passed, `/data/dryrun-*` deleted |
| P-11 | T-24h | operator | Lower the TTL (currently **300 s** for `selkoapp.com` A, `www` CNAME and `api` CNAME; read from public DNS 2026-11-25; all DNS-only, Cloudflare) | Cloudflare → DNS → each of the 3 records → TTL **1 min** | `curl -s 'https://dns.google/resolve?name=api.selkoapp.com&type=CNAME' \| jq '.Answer[0].TTL'` ≤ 60 (after 300 s have passed) |
| P-12 | T-1d | on the VM | Capacity and clock | free disk on the data volume ≥ 4 × (Q0.3 uncompressed total + Q0.1 index bytes) + 1.2 × Q0.4 bytes + 2 GiB; free memory with Selko not running ≥ 400 MiB; `timedatectl show -p NTPSynchronized --value` = `yes` | all three true |
| P-13 | T-1d | agent | Image approved and pinned: the owner's yes for the SHA, the same digest for import and serve; the VM's own image updater **does not** start or update Selko until C-11 | per the VM's runbook | digest recorded in deploy log |
| P-14 | T-1h | on the VM | Warm attachment copy | `… selko import-from-postgres --target /data --attachments-only` (also at T-1d) | exit 0 |
| P-15 | T-1h | operator | Go/no-go | P-1 … P-14 done; dry run #2 green; window at the lowest-traffic hour (the operator picks it; `/health` `requests_per_hour` gives a guide) | go |

### C.3 The window (T0 = start of freeze)

Times are targets. **Hard limit: if C-17 (DNS live) has not been reached by
T0+90 min, roll back (§D, stage R1/R2).**

| # | Target time | Owner | Step | Exact command or action | Expected |
|---|---|---|---|---|---|
| C-1 | T0-5 | agent | Baseline into the deploy log | `./scripts/check-production-health.sh` (old rules); `curl -fsS https://api.selkoapp.com/health \| jq '{build_sha, status, requests}'` | all OK, `build_sha = LAST_PG_SHA` |
| C-2 | T0-5 | on the VM | In-flight baseline | `--measure=inflight` (Q0.8) | `calendar_work_items` processing = 0 (if not, wait up to 5 min and re-measure; then proceed and record the number) |
| C-3 | T0 | agent | **Freeze: suspend the API on Render.** Suspension sends SIGTERM, and the lifespan stops ingestion first, then the worker pool (`api/app.py`), so in-flight tasks are cancelled and their leases stay behind (they are expired at the new process's startup). Suspension, rather than only switching workers off, also stops every user write, and every DNS straggler later gets a 503 instead of writing to the old database | `curl -fsS -X POST https://api.render.com/v1/services/$API_ID/suspend -o /dev/null -w '%{http_code}\n'` | `202`; within 2 min `curl -s -o /dev/null -w '%{http_code}' https://api.selkoapp.com/health` ≠ 200 |
| C-4 | T0+1 | agent | Confirm the service state | `curl -fsS https://api.render.com/v1/services/$API_ID \| jq -r .suspended` | `suspended` |
| C-5 | T0+2 | on the VM | Write fingerprint #1 | `--measure=fingerprint` (Q0.7) | record |
| C-6 | T0+2 | on the VM | In-flight at freeze | `--measure=inflight` | record every number in the deploy log (counts only) |
| C-7 | T0+5 | on the VM | Write fingerprint #2, at least 3 min after #1 | `--measure=fingerprint` | **identical to #1**. If not: something still writes. Find it (Render worker? a dashboard session?) or roll back (R1) |
| C-8 | T0+5 | on the VM | Final attachment delta | `--attachments-only` | exit 0 |
| C-9 | T0+7 | on the VM | **Import** | `docker run --rm --memory 384m --read-only --tmpfs /tmp -v <data volume>:/data -v <dir>/import.env:/run/secrets/import.env:ro <image>@sha256:<digest> selko import-from-postgres --target /data` | exit 0, §B.9 all green; duration ≈ dry run #2 |
| C-10 | T0+7+D | operator | Protect the starting point | on the VM `sqlite3 /data/selko.db "VACUUM INTO '/data/cutover-pristine.db'"` (or the same from Python inside the image), then a **manual disk snapshot** in the cloud console | snapshot listed |
| C-11 | +2 min | on the VM | **Start Selko, workers off** (`ENABLE_BACKGROUND_PROCESSING=false` from P-8), 400 MB memory limit, with the image's own start command | `curl -fsS https://cutover.selkoapp.com/health \| jq '{build_sha, database}'` | approved SHA, `engine: sqlite`, schema version = head |
| C-12 | +1 | agent | Health on the temporary name | `./scripts/check-production-health.sh https://cutover.selkoapp.com` | `root`, `work-state`, `egress` OK; `ingestion` FAIL (workers off): expected, recorded |
| C-13 | +1 | agent | Nothing has written yet | `selko import-from-postgres --verify-only --target /data` | exit 0: C1 matches the import report for every table (run before anyone signs in; from C-14 on, `accounts.last_sign_in_at` and the refresh-token table differ by design) |
| C-14 | +5 | operator | Sign in at `https://cutover.selkoapp.com` with the existing password; open Review, History, Settings; download one attachment | — | sign-in works; the New/Changes lane counts equal the counts the operator noted before T0 |
| C-15 | +1 | operator | **Switch DNS** (Cloudflare → DNS): `selkoapp.com` A → the VM's address (plus AAAA if the VM has IPv6; none exists today); `www` and `api` CNAME → `selkoapp.com` (or A → the VM). Proxy status **DNS only**, as today. Write the old targets into the deploy log first: `api` → `selko-production.onrender.com`, `www` → `selko-web.onrender.com`, apex → the A records shown in Render dashboard → web service → Settings → Custom Domains | — | saved |
| C-16 | +1 … +5 | agent | Propagation | `for h in selkoapp.com www.selkoapp.com api.selkoapp.com; do curl -s "https://dns.google/resolve?name=$h&type=A" \| jq -r '.Answer[-1].data'; curl -s -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$h&type=A" \| jq -r '.Answer[-1].data'; done` | all six answers are the VM's address (the agent compares against the value the operator gave, without writing it anywhere public) |
| C-17 | +1 … +3 | agent | TLS on the real names (the reverse proxy issues certificates once DNS resolves to it) | `for h in selkoapp.com www.selkoapp.com api.selkoapp.com; do curl -sS -o /dev/null -w "$h %{http_code} %{ssl_verify_result}\n" https://$h/; done; curl -fsS https://api.selkoapp.com/health \| jq -r .build_sha` | `200 0` ×3 (`www` may answer `301` to the apex, whatever Render does today: check with `curl -sI https://www.selkoapp.com` at C-1); approved SHA |
| C-18 | +2 | agent | Health on production | `./scripts/check-production-health.sh` | `root`, `work-state`, `egress` OK; `ingestion` FAIL (workers off) |
| C-19 | +1 | operator | **Workers on: the point after which rollback loses data** (§D) | edit the secrets file: `ENABLE_BACKGROUND_PROCESSING=true`; restart Selko | restarted |
| C-20 | +1 … +10 | agent | Ingestion moves. The poll interval is 300 s (`email_poll_interval_seconds`), and every integration is overdue after the window, so the first poll is immediate | `./scripts/check-production-health.sh`; `curl -fsS https://api.selkoapp.com/health/ingestion \| jq '{status, background_processing_enabled, items_stalled_seconds, tasks: [.tasks[] \| {name, alive}]}'` | all four surfaces OK within 10 min |
| C-21 | +5 | operator | OAuth round trip (writes only the operator's own tokens; leaves nothing behind) | web → Settings → Google → Reconnect, finish the consent; the same for Outlook if connected | returns to Settings with the account connected; no `redirect_uri_mismatch` |
| C-22 | +2 | operator | Live updates | with the Review page open, run "Check email now" from Settings | the page updates without a reload |
| C-23 | +2 | agent | Sentry (synthetic project, as today) | `SMOKE_SENTRY_DSN=… uv run python scripts/smoke-ingestion.py --base-url https://api.selkoapp.com --check-sentry`; operator: Sentry → production project → no new issue since T0 | exit 0 |
| C-24 | +5 | agent | **Deploy log T+0**: `docs/deploy-log/<date>-<sha>.md` from `TEMPLATE.md`. "Shipped": code SHA, image digest, `schema_version`, "Migrations applied: the SQLite chain at import", config: the full key list of P-8 (names only). "Pre-deploy evidence": the dry-run #2 report (counts only), C-7 fingerprints, C-6 in-flight counts, the import duration. "Affected table row counts": the §B.9 table. T+0 row: the check output, RSS (`docker stats --no-stream` on the VM), dead letters, task restarts, **measured downtime** (C-3 → C-17) | commit, PR, merge (docs only; the Stop hook requires the T+0/T+15m rows) | — |
| C-25 | T+15m | agent | Deploy log T+15m: wait inside the turn (Monitor with an until-loop, per CLAUDE.md), then `./scripts/check-production-health.sh`; check `email_sync_state.last_success_at` advanced for every active integration (via `/health/ingestion`, or `--measure` with counts of integrations whose `last_success_at` < T+0); the `calendar_work_items` pending count falling; `server_errors_per_hour` = 0; RSS below 400 MB; `/data` usage | row filled | — |
| C-26 | T+1h | operator | Close the import credentials | Supabase → API Keys → delete `cutover-import`; on the VM `shred -u <dir>/import.env`; delete `/data/import-errors-*.jsonl`; a second manual disk snapshot | done |
| C-27 | T+24h | agent, operator | Deploy log T+24h: RSS trend (the history has a ~2 MB/min leak, #191), `/health/egress` (no `supabase` bytes), WAL size (`ls -l /data/selko.db-wal` < 64 MiB, so checkpoints run), the first nightly snapshot exists, zero dead letters, Sentry quiet, no duplicate calendar events reported. Operator: TTL back to Auto; delete the `cutover.selkoapp.com` record; agent: remove it from `ALLOWED_ORIGINS` | row filled; "Which gate should have caught it" answered | — |

**Expected downtime.** API unavailable from C-3 to C-17: about **35 min
plus the import duration D** that dry run #2 measures. At the expected
size (under 1 GB), D should be well under 20 min, but **UNKNOWN until dry run
#1**. Email processing is paused from C-3 to C-20, about 10 min longer. No
email is lost: the provider cursors (`integrations.sync_cursor` for the
Gmail historyId, `email_folders.sync_cursor` for Outlook delta, and
`calendar_mirror_state.sync_token`) are carried, so the first polls pick up
everything that arrived during the window. Web users sign in once more.

---

## D. Rollback

### D.1 Decision criteria and time limits

| Trigger | Action |
|---|---|
| Any §B.9 threshold missed, or the import exits non-zero, during the window | **R1** at once. Diagnosis is not done inside the window; the import report is kept for afterwards |
| C-7 fingerprints differ and the writer is not found within 10 min | R1 |
| C-11 to C-18: health red, sign-in fails, counts differ in C-14, or TLS fails to issue within 10 min of propagation | R2 |
| T0+90 min passes without C-17 | R1, or R2 if DNS has already moved |
| After C-19: a cross-user data exposure, or data visibly wrong (missing events, wrong owner) | **Stop the Selko process immediately** (stop the exposure first), then decide R3 within 1 h |
| After C-19: ingestion or calendar delivery not working and not fixable within 2 h | R3 |
| After **T+24h** | **No rollback, fix forward**, except for a data-integrity breach. By then the writes that R3 would lose are a day's worth |

### D.2 R1: before DNS moves (nothing was served from SQLite)

Lossless. Postgres is exactly as it was at the freeze.

1. On the VM: stop Selko if C-11 started it. Move `/data/selko.db*`,
   `cutover-pristine.db` and the report into `/data/aborted-<utc>/` (0700),
   for diagnosis. Delete that directory within 7 days: it holds user data.
2. Agent: `curl -fsS -X POST https://api.render.com/v1/services/$API_ID/resume -o /dev/null -w '%{http_code}\n'` → `202`.
3. Agent: poll `curl -fsS https://api.selkoapp.com/health | jq -r .build_sha`
   until it equals `LAST_PG_SHA` (Render restarts the existing deploy, not a
   new build of `main`). Then run `./scripts/check-production-health.sh`
   (old rules): all OK. The workers start themselves: `ENABLE_BACKGROUND_PROCESSING`
   was never changed on Render. Expired leases are reclaimed by
   `claim_unprocessed_email` and the other claim paths.
4. Deploy log: verdict "rolled back", with the reason.

Time: 5–10 min. The Render resume does not rebuild. **Never** use a deploy
hook or "Deploy latest commit" for rollback. If a rebuild is ever needed, it
is `POST /v1/services/$API_ID/deploys` with `{"commitId": "<LAST_PG_SHA>"}`.

### D.3 R2: DNS moved, workers off, no user writes on SQLite

Effectively lossless. The only writes on SQLite are sign-ins (the operator's
own, plus any user who arrived between C-17 and the decision), and those are
not carried back. Users sign in again on the old stack.

1. Operator: revert the three DNS records to the values written in the
   deploy log at C-15 (TTL is still 60 s).
2. On the VM: stop Selko **before** the Render resume, so no user can write
   to SQLite while DNS drains. Move the files aside, as in R1.
3. Agent: resume Render and verify, as in R1 steps 2–3. Render's custom-domain
   certificates are still valid: they last about 90 days, and Render renews
   them once DNS points back.
4. Agent: confirm with `selko import-from-postgres --verify-only` on the
   moved file that nothing but `accounts`/refresh tokens changed. If other
   tables changed, treat it as R3.

Time: 10–15 min, plus DNS drain (60 s TTL; stragglers get the stopped
VM, i.e. an error, never a write).

### D.4 R3: after C-19 (SQLite has accepted writes)

**This loses data. There is no automated carry-back, and building one is
not planned.** It would need a reverse converter plus fencing against the
old schema, for at most a day of writes by a handful of users. What happens
to each kind of write:

| Written on SQLite after C-19 | On the old stack after R3 |
|---|---|
| New emails and their extracted events | **Not lost**: the old stack resumes from its own cursors, frozen at C-3, and re-discovers and re-extracts them. That costs the LLM calls again |
| Calendar events written to Google/Outlook by SQLite | They **exist in the provider calendar**. The old stack's mirror (`calendar_mirror_state.sync_token`, frozen at C-3) sees them, and dedup read-back should adopt them instead of creating a duplicate. **Residual risk: duplicates**; the operator checks the calendars of every user with writes in the delta report |
| User decisions (approve/reject, change accepted/rejected), sender rules, calendar settings | **Lost**. The events come back in the New/Changes lanes. The operator re-applies them by hand from the delta report |
| OAuth reconnects | Lost on the old stack. Google and Microsoft leave the older refresh tokens valid (a new consent does not revoke them), so the old stack's tokens normally still work. A revoked or expired one shows up as a reconnect prompt |
| New sign-ups | **Lost**. Those users are emailed to sign up again |
| Account deletion requests | Must be repeated on the old stack (the privacy policy promises deletion within 30 days) |

Procedure:

1. On the VM: stop Selko (this stops writes). Keep `/data/selko.db` in place
   and take a disk snapshot.
2. On the VM: `selko import-from-postgres --delta-since=<C-19 time> --target /data`.
   It prints per-table counts of rows created or updated after C-19 (from
   `created_at`/`updated_at`/`resolved_at`/`completed_at`) and writes the
   per-user list of event ids, sender rules and settings to a 0600 file
   for the operator. Tables without such a column (`email_folders`
   classification changes, for example) are listed as "cannot be
   enumerated". That is an honest gap.
3. Operator: DNS back (R2 step 1). Agent: resume Render (R1 steps 2–3).
4. Operator: re-apply the decisions from the delta file in the web app, check
   the affected users' calendars for duplicates, and email affected users.
5. Deploy log: verdict "rolled back", with the delta counts and what was
   re-applied.

Time: 20–30 min, plus manual re-application.

### D.5 The 14-day retention of the old stack

| Day | Owner | Action |
|---|---|---|
| T+0 | agent | Render API service **suspended** (C-3); Render web service still up (it serves the old static app to DNS stragglers, which then fail on the suspended API) |
| T+1d | agent | Suspend the Render web service too: `POST /v1/services/$WEB_ID/suspend`. **UNKNOWN:** whether a suspended paid Render service is billed. Check Render dashboard → Billing |
| T+0 … T+14d | — | Supabase project left **running and untouched**: no migrations, no Auth or Storage changes. **UNKNOWN:** the plan. On the free plan a project is paused after about a week without activity; a paused project can be restored from the dashboard in minutes, so rollback is still possible but slower. Check dashboard → Billing, or `./scripts/supabase-project-status.sh khahcozfbnpykspvatrg` |
| T+0 … T+14d | on the VM | `cutover-pristine.db` kept (0600) for comparison and as a second way back; deleted at T+14d |
| T+14d (Q8) | operator | With the owner's yes: delete the Render services and their custom domains; delete the Supabase project (that deletion is how user data held there is deleted, inside the policy's 30 days); remove the Actions secrets `SUPABASE_ACCESS_TOKEN`, `PRODUCTION_SUPABASE_*`, `STAGING_SUPABASE_*`, `RENDER_DEPLOY_HOOK_*`; remove the `api.supabase.com`/`api.render.com` network secrets from the cloud environment; delete `cutover-pristine.db` |

The way back **narrows every day**: R3 loses more the later it happens, which
is why D.1 ends rollback at T+24h. Between T+1d and T+14d the old stack is
a disaster-recovery copy as of the freeze, not a live alternative.

---

## E. Risk register

L = likelihood and I = impact, each rated H, M or L.

| # | Risk | L | I | Detection | Mitigation |
|---|---|---|---|---|---|
| E-1 | **Data shape surprise.** A production value the SQLite schema refuses: a NOT NULL that Postgres allows, an enum label missing from a CHECK, an array with NULL elements, a multi-dimensional array, `infinity` | M | M (the import fails in the window: R1, a wasted window) | Q0.6 at T-14d; the dry-run preflight (exit 3) and load (exit 5) at T-7d and T-1d | `0001_initial.sql` is written from the live schema with the CHECKs and nullability ported one for one; two dry runs against production; the CI lane's edge-value fixture |
| E-2 | **Timestamp format or precision drift.** The importer writes `….ffffffZ`, but a `selko/db/` path or a SQLite `DEFAULT` writes milliseconds or `+00:00`. Text comparison of leases and `next_retry_at` then misorders silently (`…00.5Z` > `…00.123456Z`), so work is retried early or never | M | H (silent, in lease and retry logic) | the §A.2 regex check runs in the import **and** at server startup over every T column (Q6), plus a test that inserts through every write path and checks the format | one codec; no timestamp `DEFAULT`s in SQLite; a CHECK on every T column: `CHECK (col IS NULL OR (length(col) = 27 AND substr(col,27) = 'Z'))` |
| E-3 | **Timezone loss.** A `timestamptz` read with a non-UTC session zone, or `time`/`date` columns treated as UTC instants | L | M | C1: the source side uses `AT TIME ZONE 'UTC'` independently of the codec, so any shift is a mismatch | `SET TIME ZONE 'UTC'` on the source session; asyncpg returns aware datetimes; `date`/`time` carried as text, never converted |
| E-4 | **Numeric conversion.** `estimated_cost_usd` or the latitude/longitude losing precision in REAL | L | L | C1 for cost (both sides rounded to 6 decimals, the column's scale); C2 for coordinates; Q0.6 records the scale | the name and unit are unchanged; photos are parked (expected 0 rows) |
| E-5 | **OAuth tokens exposed.** They are plaintext in `integrations` today (no encryption anywhere in `services/` or the migrations). During the import they could leak through an exception message or log line. After it they sit unencrypted in `selko.db`, the WAL, `pre-<sha>.db`, `cutover-pristine.db`, the snapshots, and in the dry-run copies if not deleted | M | H (anyone who can read those files has every user's mailbox) | the canary-token test (§B.8); a post-run grep of the import logs for the token prefixes `ya29.` and `1//` and Microsoft's `EwB`/`M.` forms (count only); `ls -l` modes 0600 | errors carry table/column/ordinal only; files 0600 under a dedicated uid; dry-run outputs deleted the same day; **follow-up increment (not in Q7):** application-level encryption of `access_token`/`refresh_token` with a key from the secrets file, so a copied database file alone is not enough |
| E-6 | **OAuth redirect mismatch.** `API_PUBLIC_URL` mistyped in the secrets file (`http://`, a trailing `/`, the temporary hostname), so Google/Microsoft refuse with `redirect_uri_mismatch` and every reconnect fails | M | M (existing tokens keep working; only connect/reconnect breaks) | C-21 reconnect round trip; `_validate_redirect_uri` only allows `api.selkoapp.com`, `localhost`, `127.0.0.1` | the hostname is unchanged, so the consoles need no edit (P-5 only checks them); P-8 gives the exact value; C-21 is mandatory before T+0 is written |
| E-7 | **Provider cursor discontinuity.** A Gmail `historyId` too old (Gmail answers 404 and a full resync is needed), or an Outlook delta link expired (`syncStateNotFound`/410) after the window, causing a slow catch-up or missed messages | L (the window is about an hour) | M | `graph_api_failures` rows, `email_sync_state.last_error_code`, `/health/ingestion` `items_stalled_seconds` | cursors carried verbatim; `services/gmail.py`, `services/outlook.py` and `services/msgraph.py` already handle these responses with a resync (both have handling for them; behaviour per `docs/microsoft-graph-failure-ledger.md`); keep the window short; T+15m checks every integration's `last_success_at` |
| E-8 | **Split brain: both stacks running.** Render resumed or rebuilt by mistake (a stale deploy hook, Render auto-deploy of `main`, someone pressing Resume) while the VM runs, so two processes poll the same mailboxes and write the same calendars from different databases. Duplicate events and diverging state | L–M | H | Render API `suspended` checked at C-4 and daily until Q8; Sentry and `/health` of both; duplicate events reported | P-2 (auto-deploy off, hooks regenerated); `ops.yml` `deploy-production` no longer calls Render after Q4; rollback always stops the VM process **before** resuming Render (§D) |
| E-9 | **Calendar write in flight at the freeze.** A work item cancelled after the provider accepted the write but before completion was recorded. The new process retries it, possibly creating a duplicate or reapplying an update | M (if the freeze lands during delivery) | M | C-2/C-6 record `calendar_work_items` in `processing`; after C-20 the operator checks those users' calendars | the freeze waits up to 5 min for processing = 0 (C-2); dedup read-back against the mirror (`services/calendars.py:317`) before a create; the window at the lowest-traffic hour |
| E-10 | **Duplicate ingestion after cutover.** Emails re-discovered from carried cursors are inserted again | L | M | `emails` count stable for known messages; the unique index violations are visible as errors | the unique keys `emails (user_id, email_provider, provider_message_id)` and `email_ingestion_items (integration_id, provider_message_id)` are ported, so re-discovery is an upsert, not a duplicate |
| E-11 | **Attachment volume or size.** Total bytes unknown (Q0.4); a 50 MiB object over a slow link; Storage throttling; the final delta too slow for the window | M | M | Q0.4; the warm copy durations at T-1d/T-1h; §B.9 attachment counters | warm copies before the freeze; restartable per object; 4-way concurrency; the delta at the freeze is only what arrived since T-1h |
| E-12 | **Startup recovery incomplete.** A `running` row in `email_sync_runs` blocks every new run for its integration (partial unique index). Processing rows of a table the recovery forgets stay leased forever | M | H (ingestion silently stops for some users; this is the "loop alive, claiming nothing" failure seen before) | `ingestion` surface `items_stalled_seconds`; T+15m `last_success_at` per integration | a Q6 test that builds a database from the CI lane's import (with one leased row in every leased table and one `running` run), starts the server, and requires every lease expired and the run `abandoned` before the first claim |
| E-13 | **VM memory.** Import plus the VM's other services, or Selko over 400 MB once running (the history includes an OOM at ~2 MB/min, #191) | M | M | the import report `peak_rss_mib`; `docker stats` at T+0/T+15m/T+24h; the OOM-kill count | the import runs with `--memory 384m` while the server is stopped; byte-bounded batches; the server has a 400 MB limit, so it is killed and restarted inside its own limit |
| E-14 | **VM disk.** `selko.db` larger than expected because TOAST compression is lost (body text, LLM prompts), plus dry-run copies, `pre-<sha>.db`, `cutover-pristine.db`, WAL and attachments | M | H (a full disk stops writes; SQLite returns `SQLITE_FULL`) | Q0.3 uncompressed sizes; the P-12 threshold; `df` at every deploy-log window | the P-12 rule (4× the uncompressed size + 1.2× attachments + 2 GiB); dry-run outputs deleted; `--llm-log-since` if the owner chooses it; WAL checkpoint after the import |
| E-15 | **Clock.** VM clock skew breaks lease expiry, retry timing, JWT `exp`/`iat`, OAuth token-expiry checks and Gmail/Graph request signing | L | M | `timedatectl` at P-12; JWT failures in Sentry | NTP synchronised (P-12); leases and timestamps always taken from one clock (the server's) |
| E-16 | **Backup gap.** No snapshot exists between the import and the first nightly snapshot, so a disk failure that night loses everything since the import | M | H | the snapshot list at T+0 and T+24h | a manual snapshot at C-10 and C-26; `cutover-pristine.db`; a first **restore test** within 7 days (restore a snapshot to a scratch disk, run `PRAGMA integrity_check` and `--verify-only`) |
| E-17 | **TLS issuance delay.** The reverse proxy can only get certificates for the real names after DNS points at it, so there are minutes of TLS errors. Repeated failures hit the CA's rate limits (5 failed validations per hostname per hour) | M | M | C-17 `ssl_verify_result` | the temporary hostname proves issuance works at T-3d; low TTL; if the reverse proxy supports DNS-01, pre-issue (configured in the VM's own repository, not here) |
| E-18 | **DNS stragglers.** Resolvers or clients that cache past the TTL keep reaching Render for minutes to hours | M | L | Render request metrics (the dashboard) after C-17 | the API is **suspended**, so stragglers see an error, never a write to the old database |
| E-19 | **Write freeze leaks.** Some writer is missed: a client still talking to GoTrue/PostgREST directly (if Q1/Q5 are incomplete), a dashboard edit, the staging `worker_app` pointed at production by mistake | L | H (rows changed after the export are silently lost) | C-5/C-7 fingerprint, and the §B.9 source re-check in a second snapshot | Q1 and Q5 are prerequisites (no client calls PostgREST or GoTrue); the fingerprint must be equal or the window aborts |
| E-20 | **Read-only role lacks a privilege** (`auth.users`, `storage.objects`, `pg_stat_all_tables`) or the pooler refuses a long transaction (idle or statement timeout) | M | M | dry run #1 preflight (exit 4) and its duration | the session sets `statement_timeout = 0` and `idle_in_transaction_session_timeout = 0`; the operator grants the missing SELECTs to the read-only role before dry run #2; the session pooler is used, because the direct database host is IPv6-only on Supabase |
| E-21 | **`main` is SQLite code while production still runs Postgres code** (between the Q6 merge and Q7). Any Render rebuild of `main`, or a hotfix branched from `main`, takes production down | M | H | P-1/P-2 | Render builds only by `commitId = LAST_PG_SHA`; a hotfix in that period branches from `LAST_PG_SHA`; keep Q6-merge → Q7 short (days) |
| E-22 | **Privacy-policy promise broken.** Processors change without the notice the policy promises, or the policy page still names Supabase/Render after the cutover | L | M (trust and compliance; Google's restricted-scope review reads the policy) | P-6/P-7 checklist; the privacy test asserts the new list | notice at T-7d; the policy change ships in the cutover image, so it goes live at the same moment. **UNKNOWN:** whether the Google OAuth app is verified for restricted Gmail scopes and must report a change of hosting; see Google Cloud Console → OAuth consent screen → Publishing status |
| E-23 | **Notification noise at startup.** Every integration looks overdue when the new process starts; the incident evaluator may send `stale_poll` "opened" emails and then "resolved" ones | H | L | the operator's inbox | expected; noted in the deploy log; carried `operational_incidents` prevent duplicates for incidents already open |
| E-24 | **Sessions and legacy clients.** Every web user is signed out; the iOS/Android apps stop working (spec §4.8) | H (certain) | L | — | P-6 notice; existing passwords keep working (bcrypt carried) |
| E-25 | **Import and server from different images.** The schema version written by the importer differs from what the server expects; the server re-migrates, or refuses to start | L | M | `/health` `database.schema_version` = the image head at C-11 | one digest for both (P-13); the importer applies the server's own migration chain |

