# 01 — Schema: every table, Postgres to SQLite

## Summary

| Table | Columns | Constraints | Indexes | Triggers | Policies | HAND items |
|---|---|---|---|---|---|---|
| `action_history` | 9 | 4 | 4 | 0 | 5 | 0 |
| `attachments` | 17 | 4 | 5 | 1 | 1 | 0 |
| `calendar_entries` | 24 | 5 | 4 | 0 | 1 | 0 |
| `calendar_mirror_state` | 18 | 3 | 2 | 0 | 0 | 0 |
| `calendar_sync_log` | 7 | 4 | 5 | 0 | 2 | 0 |
| `calendar_work_items` | 21 | 9 | 4 | 2 | 1 | 0 |
| `email_calendar_components` | 14 | 6 | 4 | 0 | 0 | 0 |
| `email_folders` | 20 | 7 | 4 | 0 | 2 | 0 |
| `email_ingestion_items` | 21 | 8 | 3 | 1 | 1 | 0 |
| `email_sync_runs` | 16 | 6 | 3 | 0 | 1 | 0 |
| `email_sync_state` | 18 | 4 | 2 | 0 | 2 | 0 |
| `emails` | 45 | 8 | 10 | 3 | 1 | 0 |
| `event_change_proposals` | 12 | 11 | 4 | 2 | 1 | 3 |
| `event_identity_hints` | 12 | 9 | 4 | 0 | 0 | 1 |
| `event_repair_audit` | 8 | 3 | 3 | 0 | 0 | 0 |
| `event_sources` | 8 | 6 | 5 | 2 | 1 | 0 |
| `events` | 17 | 6 | 4 | 5 | 1 | 1 |
| `global_limits` | 7 | 2 | 2 | 1 | 2 | 0 |
| `graph_api_failures` | 19 | 4 | 4 | 0 | 1 | 0 |
| `integration_recoveries` | 24 | 5 | 3 | 0 | 2 | 0 |
| `integrations` | 14 | 3 | 3 | 3 | 1 | 0 |
| `llm_call_log` | 19 | 3 | 5 | 0 | 2 | 1 |
| `oauth_states` | 7 | 2 | 2 | 0 | 1 | 1 |
| `operational_incidents` | 13 | 6 | 2 | 0 | 1 | 0 |
| `photos` | 25 | 4 | 4 | 0 | 5 | 2 |
| `scheduled_tasks` | 12 | 4 | 3 | 0 | 2 | 0 |
| `sender_rules` | 7 | 4 | 6 | 2 | 1 | 0 |
| `usage_quotas` | 11 | 3 | 3 | 1 | 2 | 1 |
| `user_calendar_settings` | 8 | 4 | 1 | 1 | 1 | 0 |
| `users` | 5 | 2 | 1 | 1 | 3 | 0 |
| **30 tables** | 458 | 149 | 109 | 25 | 44 | **13** |

Generated from the live local schema (all migrations applied) by querying `information_schema` and `pg_catalog` read-only. Every table, column, constraint, index, trigger and policy is listed. `HAND` marks the items a person must translate; everything else is mechanical. The draft DDL is the starting point for `backend/selko/db/migrations/0001_initial.sql`; it is not final until every `HAND` item is resolved and the schema-contract successor test passes.

## Codec rules (one implementation, `backend/selko/db/codec.py`)

| Postgres | SQLite storage | Codec |
|---|---|---|
| `uuid` | `TEXT` | `str(uuid.UUID(v))` on write; canonical lowercase; compared as text |
| `timestamptz` | `TEXT` | always UTC, `%Y-%m-%dT%H:%M:%S.%fZ` (6-digit microseconds, `Z`), so text order = time order |
| `date` / `time` | `TEXT` | `YYYY-MM-DD` / `HH:MM:SS` |
| `boolean` | `INTEGER` | 0/1 with `CHECK (col IN (0,1))` |
| `jsonb` / arrays | `TEXT` | `json.dumps(v, separators=(',',':'), sort_keys=True, ensure_ascii=False)`; `CHECK (json_valid(col))` |
| enum types | `TEXT` | `CHECK (col IN (...))`, pinned by the `EXPECTED_CHECK_DOMAINS` successor |
| `integer` / `bigint` | `INTEGER` | int |

## `action_history`

9 columns, 4 constraints, 4 indexes, 0 triggers, 5 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `action_type` | `text` | no |  | `TEXT` | text |
| 4 | `entity_type` | `text` | no |  | `TEXT` | text |
| 5 | `entity_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 6 | `previous_state` | `jsonb` | yes |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 7 | `new_state` | `jsonb` | yes |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 8 | `external_resource_id` | `text` | yes |  | `TEXT` | text |
| 9 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `action_history_action_type_check` | check | `CHECK ((action_type = ANY (ARRAY['create'::text, 'update'::text, 'delete'::text])))` | mechanical |
| `action_history_entity_type_check` | check | `CHECK ((entity_type = ANY (ARRAY['event'::text, 'sender_rule'::text])))` | mechanical |
| `action_history_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `action_history_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `action_history_entity_idx` | `CREATE INDEX action_history_entity_idx ON public.action_history USING btree (entity_type, entity_id)` | mechanical |
| `action_history_pkey` | `CREATE UNIQUE INDEX action_history_pkey ON public.action_history USING btree (id)` | from its constraint |
| `action_history_user_action_type_idx` | `CREATE INDEX action_history_user_action_type_idx ON public.action_history USING btree (user_id, action_type, created_at DESC)` | mechanical |
| `action_history_user_created_idx` | `CREATE INDEX action_history_user_created_idx ON public.action_history USING btree (user_id, created_at DESC)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Deny deletes from action_history` (DELETE, roles {public}): using `false`
- `Deny updates to action_history` (UPDATE, roles {public}): using `false`
- `Service role full access to action_history` (ALL, roles {public}): using `(auth.role() = 'service_role'::text)`; check `(auth.role() = 'service_role'::text)`
- `Users can insert own action history` (INSERT, roles {public}): using ``; check `(auth.uid() = user_id)`
- `Users can view own action history` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE action_history (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    previous_state TEXT CHECK (previous_state IS NULL OR json_valid(previous_state)),
    new_state TEXT CHECK (new_state IS NULL OR json_valid(new_state)),
    external_resource_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT action_history_action_type_check CHECK ((action_type IN ('create', 'update', 'delete'))),
    CONSTRAINT action_history_entity_type_check CHECK ((entity_type IN ('event', 'sender_rule'))),
    CONSTRAINT action_history_pkey PRIMARY KEY (id),
    CONSTRAINT action_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX action_history_entity_idx ON action_history (entity_type, entity_id);
CREATE INDEX action_history_user_action_type_idx ON action_history (user_id, action_type, created_at DESC);
CREATE INDEX action_history_user_created_idx ON action_history (user_id, created_at DESC);
```

## `attachments`

17 columns, 4 constraints, 5 indexes, 1 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `email_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider_attachment_id` | `text` | yes |  | `TEXT` | text |
| 5 | `filename` | `text` | no |  | `TEXT` | text |
| 6 | `mime_type` | `text` | yes |  | `TEXT` | text |
| 7 | `size_bytes` | `bigint` | yes |  | `INTEGER` | int |
| 8 | `storage_path` | `text` | yes |  | `TEXT` | text |
| 9 | `content_hash` | `text` | yes |  | `TEXT` | text |
| 10 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 11 | `ingestion_status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 12 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 13 | `max_attempts` | `integer` | no | `8` | `INTEGER` | int |
| 14 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 15 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 16 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 17 | `ingestion_error_code` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `attachments_email_id_fkey` | foreign key | `FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE` | mechanical |
| `attachments_ingestion_status_check` | check | `CHECK ((ingestion_status = ANY (ARRAY['pending'::text, 'processing'::text, 'stored'::text, 'unsupported'::text, 'retry'::text, 'dead_letter'::text])))` | mechanical |
| `attachments_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `attachments_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `attachments_claim_idx` | `CREATE INDEX attachments_claim_idx ON public.attachments USING btree (ingestion_status, next_retry_at, created_at) WHERE (ingestion_status = ANY (ARRAY['pending'::text, 'retry'::text, 'processing'::text]))` | mechanical |
| `attachments_email_provider_attachment_idx` | `CREATE UNIQUE INDEX attachments_email_provider_attachment_idx ON public.attachments USING btree (email_id, provider_attachment_id) WHERE ((provider_attachment_id IS NOT NULL) AND (provider_attachment_id <> ''::text))` | mechanical |
| `attachments_pkey` | `CREATE UNIQUE INDEX attachments_pkey ON public.attachments USING btree (id)` | from its constraint |
| `idx_attachments_content_hash` | `CREATE INDEX idx_attachments_content_hash ON public.attachments USING btree (user_id, content_hash) WHERE (content_hash IS NOT NULL)` | mechanical |
| `idx_attachments_email` | `CREATE INDEX idx_attachments_email ON public.attachments USING btree (email_id)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `attachments_notify_pending`: `CREATE TRIGGER attachments_notify_pending AFTER INSERT OR UPDATE OF ingestion_status ON public.attachments FOR EACH ROW WHEN ((new.ingestion_status = 'pending'::text)) EXECUTE FUNCTION notify_work_available('attachment_pending')`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own attachments` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE attachments (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    provider_attachment_id TEXT,
    filename TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    storage_path TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ingestion_status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    next_retry_at TEXT,
    locked_by TEXT,
    locked_until TEXT,
    ingestion_error_code TEXT,
    CONSTRAINT attachments_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    CONSTRAINT attachments_ingestion_status_check CHECK ((ingestion_status IN ('pending', 'processing', 'stored', 'unsupported', 'retry', 'dead_letter'))),
    CONSTRAINT attachments_pkey PRIMARY KEY (id),
    CONSTRAINT attachments_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX attachments_claim_idx ON attachments (ingestion_status, next_retry_at, created_at) WHERE (ingestion_status IN ('pending', 'retry', 'processing'));
CREATE UNIQUE INDEX attachments_email_provider_attachment_idx ON attachments (email_id, provider_attachment_id) WHERE ((provider_attachment_id IS NOT NULL) AND (provider_attachment_id <> ''));
CREATE INDEX idx_attachments_content_hash ON attachments (user_id, content_hash) WHERE (content_hash IS NOT NULL);
CREATE INDEX idx_attachments_email ON attachments (email_id);
```

## `calendar_entries`

24 columns, 5 constraints, 4 indexes, 0 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `calendar_id` | `text` | no |  | `TEXT` | text |
| 5 | `provider_event_id` | `text` | no |  | `TEXT` | text |
| 6 | `ical_uid` | `text` | yes |  | `TEXT` | text |
| 7 | `recurring_event_id` | `text` | yes |  | `TEXT` | text |
| 8 | `original_start` | `text` | no | `''::text` | `TEXT` | text |
| 9 | `title` | `text` | yes |  | `TEXT` | text |
| 10 | `location` | `text` | yes |  | `TEXT` | text |
| 11 | `start_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `end_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `all_day` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 14 | `timezone` | `text` | yes |  | `TEXT` | text |
| 15 | `status` | `text` | no | `'confirmed'::text` | `TEXT` | text |
| 16 | `self_response` | `text` | yes |  | `TEXT` | text |
| 17 | `etag` | `text` | yes |  | `TEXT` | text |
| 18 | `sequence` | `integer` | yes |  | `INTEGER` | int |
| 19 | `provider_updated_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 20 | `origin` | `text` | no | `'external'::text` | `TEXT` | text |
| 21 | `deleted_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 22 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 23 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 24 | `join_url` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `calendar_entries_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `calendar_entries_origin_check` | check | `CHECK ((origin = ANY (ARRAY['selko_created'::text, 'external'::text])))` | mechanical |
| `calendar_entries_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `calendar_entries_provider_key` | unique | `UNIQUE (integration_id, calendar_id, provider_event_id)` | mechanical |
| `calendar_entries_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `calendar_entries_pkey` | `CREATE UNIQUE INDEX calendar_entries_pkey ON public.calendar_entries USING btree (id)` | from its constraint |
| `calendar_entries_provider_key` | `CREATE UNIQUE INDEX calendar_entries_provider_key ON public.calendar_entries USING btree (integration_id, calendar_id, provider_event_id)` | from its constraint |
| `calendar_entries_uid_idx` | `CREATE INDEX calendar_entries_uid_idx ON public.calendar_entries USING btree (user_id, ical_uid, original_start) WHERE ((ical_uid IS NOT NULL) AND (deleted_at IS NULL))` | mechanical |
| `calendar_entries_user_start_idx` | `CREATE INDEX calendar_entries_user_start_idx ON public.calendar_entries USING btree (user_id, start_at) WHERE (deleted_at IS NULL)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can view own calendar entries` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE calendar_entries (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    ical_uid TEXT,
    recurring_event_id TEXT,
    original_start TEXT NOT NULL DEFAULT '',
    title TEXT,
    location TEXT,
    start_at TEXT,
    end_at TEXT,
    all_day INTEGER NOT NULL DEFAULT 0 CHECK (all_day IN (0,1)),
    timezone TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    self_response TEXT,
    etag TEXT,
    sequence INTEGER,
    provider_updated_at TEXT,
    origin TEXT NOT NULL DEFAULT 'external',
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    join_url TEXT,
    CONSTRAINT calendar_entries_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT calendar_entries_origin_check CHECK ((origin IN ('selko_created', 'external'))),
    CONSTRAINT calendar_entries_pkey PRIMARY KEY (id),
    CONSTRAINT calendar_entries_provider_key UNIQUE (integration_id, calendar_id, provider_event_id),
    CONSTRAINT calendar_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_entries_uid_idx ON calendar_entries (user_id, ical_uid, original_start) WHERE ((ical_uid IS NOT NULL) AND (deleted_at IS NULL));
CREATE INDEX calendar_entries_user_start_idx ON calendar_entries (user_id, start_at) WHERE (deleted_at IS NULL);
```

## `calendar_mirror_state`

18 columns, 3 constraints, 2 indexes, 0 triggers, 0 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 2 | `calendar_id` | `text` | no |  | `TEXT` | text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `sync_token` | `text` | yes |  | `TEXT` | text |
| 5 | `last_full_resync_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 6 | `window_start` | `timestamp with time zone` | no |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 7 | `window_end` | `timestamp with time zone` | no |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 8 | `next_poll_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 9 | `lease_owner` | `text` | yes |  | `TEXT` | text |
| 10 | `lease_expires_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `lease_generation` | `bigint` | no | `0` | `INTEGER` | int |
| 12 | `last_started_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `last_success_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 14 | `consecutive_failures` | `integer` | no | `0` | `INTEGER` | int |
| 15 | `last_error_code` | `text` | yes |  | `TEXT` | text |
| 16 | `last_error_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 17 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 18 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `calendar_mirror_state_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `calendar_mirror_state_pkey` | primary key | `PRIMARY KEY (integration_id, calendar_id)` | mechanical |
| `calendar_mirror_state_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `calendar_mirror_state_due_idx` | `CREATE INDEX calendar_mirror_state_due_idx ON public.calendar_mirror_state USING btree (next_poll_at, lease_expires_at)` | mechanical |
| `calendar_mirror_state_pkey` | `CREATE UNIQUE INDEX calendar_mirror_state_pkey ON public.calendar_mirror_state USING btree (integration_id, calendar_id)` | from its constraint |

**Draft SQLite DDL**

```sql
CREATE TABLE calendar_mirror_state (
    integration_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    sync_token TEXT,
    last_full_resync_at TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    next_poll_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    lease_owner TEXT,
    lease_expires_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    last_started_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT calendar_mirror_state_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT calendar_mirror_state_pkey PRIMARY KEY (integration_id, calendar_id),
    CONSTRAINT calendar_mirror_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_mirror_state_due_idx ON calendar_mirror_state (next_poll_at, lease_expires_at);
```

## `calendar_sync_log`

7 columns, 4 constraints, 5 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `event_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `google_calendar_event_id` | `text` | no |  | `TEXT` | text |
| 5 | `action` | `text` | no |  | `TEXT` | text |
| 6 | `snapshot_synced` | `jsonb` | no |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 7 | `synced_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `calendar_sync_log_action_check` | check | `CHECK ((action = ANY (ARRAY['created'::text, 'updated'::text, 'deleted'::text])))` | mechanical |
| `calendar_sync_log_event_id_fkey` | foreign key | `FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE` | mechanical |
| `calendar_sync_log_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `calendar_sync_log_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `calendar_sync_log_event_id_idx` | `CREATE INDEX calendar_sync_log_event_id_idx ON public.calendar_sync_log USING btree (event_id)` | mechanical |
| `calendar_sync_log_google_id_idx` | `CREATE INDEX calendar_sync_log_google_id_idx ON public.calendar_sync_log USING btree (google_calendar_event_id)` | mechanical |
| `calendar_sync_log_pkey` | `CREATE UNIQUE INDEX calendar_sync_log_pkey ON public.calendar_sync_log USING btree (id)` | from its constraint |
| `calendar_sync_log_synced_at_idx` | `CREATE INDEX calendar_sync_log_synced_at_idx ON public.calendar_sync_log USING btree (synced_at DESC)` | mechanical |
| `calendar_sync_log_user_id_idx` | `CREATE INDEX calendar_sync_log_user_id_idx ON public.calendar_sync_log USING btree (user_id)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can insert own sync logs` (INSERT, roles {public}): using ``; check `(user_id = auth.uid())`
- `Users can view own sync logs` (SELECT, roles {public}): using `(user_id = auth.uid())`

**Draft SQLite DDL**

```sql
CREATE TABLE calendar_sync_log (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    google_calendar_event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    snapshot_synced TEXT NOT NULL CHECK (snapshot_synced IS NULL OR json_valid(snapshot_synced)),
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT calendar_sync_log_action_check CHECK ((action IN ('created', 'updated', 'deleted'))),
    CONSTRAINT calendar_sync_log_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT calendar_sync_log_pkey PRIMARY KEY (id),
    CONSTRAINT calendar_sync_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_sync_log_event_id_idx ON calendar_sync_log (event_id);
CREATE INDEX calendar_sync_log_google_id_idx ON calendar_sync_log (google_calendar_event_id);
CREATE INDEX calendar_sync_log_synced_at_idx ON calendar_sync_log (synced_at DESC);
CREATE INDEX calendar_sync_log_user_id_idx ON calendar_sync_log (user_id);
```

## `calendar_work_items`

21 columns, 9 constraints, 4 indexes, 2 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `event_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `action` | `text` | no |  | `TEXT` | text |
| 5 | `generation` | `bigint` | no |  | `INTEGER` | int |
| 6 | `status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 7 | `desired_event` | `jsonb` | yes |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 8 | `provider_event_id` | `text` | yes |  | `TEXT` | text |
| 9 | `expected_provider_revision` | `text` | yes |  | `TEXT` | text |
| 10 | `force_overwrite` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 11 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 12 | `max_attempts` | `integer` | no | `3` | `INTEGER` | int |
| 13 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 14 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 15 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 16 | `failure_code` | `text` | yes |  | `TEXT` | text |
| 17 | `failure_detail` | `text` | yes |  | `TEXT` | text |
| 18 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 19 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 20 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 21 | `provider` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `calendar_work_items_action_check` | check | `CHECK ((action = ANY (ARRAY['upsert'::text, 'cancel'::text])))` | mechanical |
| `calendar_work_items_attempts_check` | check | `CHECK ((attempts >= 0))` | mechanical |
| `calendar_work_items_event_id_fkey` | foreign key | `FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE` | mechanical |
| `calendar_work_items_generation_check` | check | `CHECK ((generation > 0))` | mechanical |
| `calendar_work_items_max_attempts_check` | check | `CHECK ((max_attempts > 0))` | mechanical |
| `calendar_work_items_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `calendar_work_items_provider_check` | check | `CHECK ((provider = ANY (ARRAY['google_calendar'::text, 'outlook'::text])))` | mechanical |
| `calendar_work_items_status_check` | check | `CHECK ((status = ANY (ARRAY['pending'::text, 'processing'::text, 'succeeded'::text, 'failed'::text, 'blocked'::text, 'superseded'::text])))` | mechanical |
| `calendar_work_items_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `calendar_work_items_claim_idx` | `CREATE INDEX calendar_work_items_claim_idx ON public.calendar_work_items USING btree (status, next_retry_at, created_at) WHERE (status = ANY (ARRAY['pending'::text, 'processing'::text]))` | mechanical |
| `calendar_work_items_one_active_per_event` | `CREATE UNIQUE INDEX calendar_work_items_one_active_per_event ON public.calendar_work_items USING btree (event_id) WHERE (status = ANY (ARRAY['pending'::text, 'processing'::text]))` | mechanical |
| `calendar_work_items_pkey` | `CREATE UNIQUE INDEX calendar_work_items_pkey ON public.calendar_work_items USING btree (id)` | from its constraint |
| `calendar_work_items_user_idx` | `CREATE INDEX calendar_work_items_user_idx ON public.calendar_work_items USING btree (user_id, created_at DESC)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `calendar_work_items_owner_check`: `CREATE TRIGGER calendar_work_items_owner_check BEFORE INSERT OR UPDATE ON public.calendar_work_items FOR EACH ROW EXECUTE FUNCTION calendar_work_item_owner_check()`
- `trg_calendar_work_items_broadcast`: `CREATE TRIGGER trg_calendar_work_items_broadcast AFTER INSERT OR DELETE OR UPDATE ON public.calendar_work_items FOR EACH ROW EXECUTE FUNCTION trg_calendar_work_items_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can read own calendar work` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE calendar_work_items (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    generation INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    desired_event TEXT CHECK (desired_event IS NULL OR json_valid(desired_event)),
    provider_event_id TEXT,
    expected_provider_revision TEXT,
    force_overwrite INTEGER NOT NULL DEFAULT 0 CHECK (force_overwrite IN (0,1)),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    locked_by TEXT,
    locked_until TEXT,
    next_retry_at TEXT,
    failure_code TEXT,
    failure_detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    provider TEXT,
    CONSTRAINT calendar_work_items_action_check CHECK ((action IN ('upsert', 'cancel'))),
    CONSTRAINT calendar_work_items_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT calendar_work_items_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT calendar_work_items_generation_check CHECK ((generation > 0)),
    CONSTRAINT calendar_work_items_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT calendar_work_items_pkey PRIMARY KEY (id),
    CONSTRAINT calendar_work_items_provider_check CHECK ((provider IN ('google_calendar', 'outlook'))),
    CONSTRAINT calendar_work_items_status_check CHECK ((status IN ('pending', 'processing', 'succeeded', 'failed', 'blocked', 'superseded'))),
    CONSTRAINT calendar_work_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_work_items_claim_idx ON calendar_work_items (status, next_retry_at, created_at) WHERE (status IN ('pending', 'processing'));
CREATE UNIQUE INDEX calendar_work_items_one_active_per_event ON calendar_work_items (event_id) WHERE (status IN ('pending', 'processing'));
CREATE INDEX calendar_work_items_user_idx ON calendar_work_items (user_id, created_at DESC);
```

## `email_calendar_components`

14 columns, 6 constraints, 4 indexes, 0 triggers, 0 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `email_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `component_index` | `integer` | no |  | `INTEGER` | int |
| 5 | `method` | `text` | no |  | `TEXT` | text |
| 6 | `uid_hash` | `text` | yes |  | `TEXT` | text |
| 7 | `recurrence_id` | `text` | yes |  | `TEXT` | text |
| 8 | `recurrence_range` | `text` | yes |  | `TEXT` | text |
| 9 | `sequence` | `integer` | no | `0` | `INTEGER` | int |
| 10 | `dtstamp` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `component_status` | `text` | yes |  | `TEXT` | text |
| 12 | `start_datetime` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `end_datetime` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 14 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `email_calendar_components_component_index_check` | check | `CHECK ((component_index >= 0))` | mechanical |
| `email_calendar_components_email_id_component_index_key` | unique | `UNIQUE (email_id, component_index)` | mechanical |
| `email_calendar_components_email_id_fkey` | foreign key | `FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE` | mechanical |
| `email_calendar_components_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `email_calendar_components_recurrence_range_check` | check | `CHECK (((recurrence_range IS NULL) OR (recurrence_range = 'THISANDFUTURE'::text)))` | mechanical |
| `email_calendar_components_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `email_calendar_components_email_id_component_index_key` | `CREATE UNIQUE INDEX email_calendar_components_email_id_component_index_key ON public.email_calendar_components USING btree (email_id, component_index)` | from its constraint |
| `email_calendar_components_email_idx` | `CREATE INDEX email_calendar_components_email_idx ON public.email_calendar_components USING btree (email_id)` | mechanical |
| `email_calendar_components_pkey` | `CREATE UNIQUE INDEX email_calendar_components_pkey ON public.email_calendar_components USING btree (id)` | from its constraint |
| `email_calendar_components_user_idx` | `CREATE INDEX email_calendar_components_user_idx ON public.email_calendar_components USING btree (user_id)` | mechanical |

**Draft SQLite DDL**

```sql
CREATE TABLE email_calendar_components (
    id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    component_index INTEGER NOT NULL,
    method TEXT NOT NULL,
    uid_hash TEXT,
    recurrence_id TEXT,
    recurrence_range TEXT,
    sequence INTEGER NOT NULL DEFAULT 0,
    dtstamp TEXT,
    component_status TEXT,
    start_datetime TEXT,
    end_datetime TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT email_calendar_components_component_index_check CHECK ((component_index >= 0)),
    CONSTRAINT email_calendar_components_email_id_component_index_key UNIQUE (email_id, component_index),
    CONSTRAINT email_calendar_components_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    CONSTRAINT email_calendar_components_pkey PRIMARY KEY (id),
    CONSTRAINT email_calendar_components_recurrence_range_check CHECK (((recurrence_range IS NULL) OR (recurrence_range = 'THISANDFUTURE'))),
    CONSTRAINT email_calendar_components_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_calendar_components_email_idx ON email_calendar_components (email_id);
CREATE INDEX email_calendar_components_user_idx ON email_calendar_components (user_id);
```

## `email_folders`

20 columns, 7 constraints, 4 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider` | `text` | no |  | `TEXT` | text |
| 5 | `provider_folder_id` | `text` | no |  | `TEXT` | text |
| 6 | `parent_folder_id` | `text` | yes |  | `TEXT` | text |
| 7 | `name` | `text` | no |  | `TEXT` | text |
| 8 | `full_path` | `text` | no |  | `TEXT` | text |
| 9 | `folder_kind` | `text` | no |  | `TEXT` | text |
| 10 | `is_system` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 11 | `system_kind` | `text` | yes |  | `TEXT` | text |
| 12 | `classification_decision` | `text` | no | `'include'::text` | `TEXT` | text |
| 13 | `classification_reason` | `text` | yes |  | `TEXT` | text |
| 14 | `user_override` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 15 | `is_included` | `boolean` | no | `true` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 16 | `sync_cursor` | `text` | yes |  | `TEXT` | text |
| 17 | `discovered_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 18 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 19 | `is_scannable` | `boolean` | no | `true` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 20 | `is_permanently_excluded` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `email_folders_classification_decision_check` | check | `CHECK ((classification_decision = ANY (ARRAY['include'::text, 'exclude'::text, 'uncertain'::text])))` | mechanical |
| `email_folders_folder_kind_check` | check | `CHECK ((folder_kind = ANY (ARRAY['label'::text, 'folder'::text])))` | mechanical |
| `email_folders_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `email_folders_integration_id_provider_folder_id_key` | unique | `UNIQUE (integration_id, provider_folder_id)` | mechanical |
| `email_folders_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `email_folders_provider_check` | check | `CHECK ((provider = ANY (ARRAY['gmail'::text, 'outlook'::text])))` | mechanical |
| `email_folders_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `email_folders_integration_id_provider_folder_id_key` | `CREATE UNIQUE INDEX email_folders_integration_id_provider_folder_id_key ON public.email_folders USING btree (integration_id, provider_folder_id)` | from its constraint |
| `email_folders_pkey` | `CREATE UNIQUE INDEX email_folders_pkey ON public.email_folders USING btree (id)` | from its constraint |
| `idx_email_folders_syncable` | `CREATE INDEX idx_email_folders_syncable ON public.email_folders USING btree (integration_id, is_included, is_scannable)` | mechanical |
| `idx_email_folders_user_provider` | `CREATE INDEX idx_email_folders_user_provider ON public.email_folders USING btree (user_id, provider, full_path)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role full access to email folders` (ALL, roles {service_role}): using `true`; check `true`
- `Users can view own email folders` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE email_folders (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_folder_id TEXT NOT NULL,
    parent_folder_id TEXT,
    name TEXT NOT NULL,
    full_path TEXT NOT NULL,
    folder_kind TEXT NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0,1)),
    system_kind TEXT,
    classification_decision TEXT NOT NULL DEFAULT 'include',
    classification_reason TEXT,
    user_override INTEGER NOT NULL DEFAULT 0 CHECK (user_override IN (0,1)),
    is_included INTEGER NOT NULL DEFAULT 1 CHECK (is_included IN (0,1)),
    sync_cursor TEXT,
    discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_scannable INTEGER NOT NULL DEFAULT 1 CHECK (is_scannable IN (0,1)),
    is_permanently_excluded INTEGER NOT NULL DEFAULT 0 CHECK (is_permanently_excluded IN (0,1)),
    CONSTRAINT email_folders_classification_decision_check CHECK ((classification_decision IN ('include', 'exclude', 'uncertain'))),
    CONSTRAINT email_folders_folder_kind_check CHECK ((folder_kind IN ('label', 'folder'))),
    CONSTRAINT email_folders_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT email_folders_integration_id_provider_folder_id_key UNIQUE (integration_id, provider_folder_id),
    CONSTRAINT email_folders_pkey PRIMARY KEY (id),
    CONSTRAINT email_folders_provider_check CHECK ((provider IN ('gmail', 'outlook'))),
    CONSTRAINT email_folders_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_email_folders_syncable ON email_folders (integration_id, is_included, is_scannable);
CREATE INDEX idx_email_folders_user_provider ON email_folders (user_id, provider, full_path);
```

## `email_ingestion_items`

21 columns, 8 constraints, 3 indexes, 1 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider` | `text` | no |  | `TEXT` | text |
| 5 | `provider_message_id` | `text` | no |  | `TEXT` | text |
| 6 | `provider_folder_ids` | `_text` | no | `'{}'::text[]` | `TEXT` | text[] -> JSON array text, CHECK (json_valid(col)) |
| 7 | `change_kind` | `text` | no | `'upsert'::text` | `TEXT` | text |
| 8 | `first_discovered_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 9 | `last_discovered_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 10 | `acquisition_status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 11 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 12 | `max_attempts` | `integer` | no | `8` | `INTEGER` | int |
| 13 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 14 | `lease_owner` | `text` | yes |  | `TEXT` | text |
| 15 | `lease_expires_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 16 | `last_error_code` | `text` | yes |  | `TEXT` | text |
| 17 | `last_error_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 18 | `email_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 19 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 20 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 21 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `email_ingestion_items_acquisition_status_check` | check | `CHECK ((acquisition_status = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'retry'::text, 'dead_letter'::text, 'removed'::text])))` | mechanical |
| `email_ingestion_items_change_kind_check` | check | `CHECK ((change_kind = ANY (ARRAY['upsert'::text, 'membership_change'::text, 'removed'::text])))` | mechanical |
| `email_ingestion_items_email_id_fkey` | foreign key | `FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL` | mechanical |
| `email_ingestion_items_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `email_ingestion_items_integration_id_provider_message_id_key` | unique | `UNIQUE (integration_id, provider_message_id)` | mechanical |
| `email_ingestion_items_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `email_ingestion_items_provider_check` | check | `CHECK ((provider = ANY (ARRAY['gmail'::text, 'outlook'::text])))` | mechanical |
| `email_ingestion_items_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `email_ingestion_items_claim_idx` | `CREATE INDEX email_ingestion_items_claim_idx ON public.email_ingestion_items USING btree (acquisition_status, next_retry_at, created_at) WHERE (acquisition_status = ANY (ARRAY['pending'::text, 'retry'::text, 'processing'::text]))` | mechanical |
| `email_ingestion_items_integration_id_provider_message_id_key` | `CREATE UNIQUE INDEX email_ingestion_items_integration_id_provider_message_id_key ON public.email_ingestion_items USING btree (integration_id, provider_message_id)` | from its constraint |
| `email_ingestion_items_pkey` | `CREATE UNIQUE INDEX email_ingestion_items_pkey ON public.email_ingestion_items USING btree (id)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `items_notify_pending`: `CREATE TRIGGER items_notify_pending AFTER INSERT OR UPDATE OF acquisition_status ON public.email_ingestion_items FOR EACH ROW WHEN ((new.acquisition_status = 'pending'::text)) EXECUTE FUNCTION notify_work_available('item_pending')`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages ingestion items` (ALL, roles {service_role}): using `true`; check `true`

**Draft SQLite DDL**

```sql
CREATE TABLE email_ingestion_items (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    provider_folder_ids TEXT NOT NULL DEFAULT '[]' CHECK (provider_folder_ids IS NULL OR json_valid(provider_folder_ids)),
    change_kind TEXT NOT NULL DEFAULT 'upsert',
    first_discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    acquisition_status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    next_retry_at TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error_code TEXT,
    last_error_at TEXT,
    email_id TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT email_ingestion_items_acquisition_status_check CHECK ((acquisition_status IN ('pending', 'processing', 'completed', 'retry', 'dead_letter', 'removed'))),
    CONSTRAINT email_ingestion_items_change_kind_check CHECK ((change_kind IN ('upsert', 'membership_change', 'removed'))),
    CONSTRAINT email_ingestion_items_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL,
    CONSTRAINT email_ingestion_items_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT email_ingestion_items_integration_id_provider_message_id_key UNIQUE (integration_id, provider_message_id),
    CONSTRAINT email_ingestion_items_pkey PRIMARY KEY (id),
    CONSTRAINT email_ingestion_items_provider_check CHECK ((provider IN ('gmail', 'outlook'))),
    CONSTRAINT email_ingestion_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_ingestion_items_claim_idx ON email_ingestion_items (acquisition_status, next_retry_at, created_at) WHERE (acquisition_status IN ('pending', 'retry', 'processing'));
```

## `email_sync_runs`

16 columns, 6 constraints, 3 indexes, 0 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider` | `text` | no |  | `TEXT` | text |
| 5 | `run_kind` | `text` | no |  | `TEXT` | text |
| 6 | `status` | `text` | no |  | `TEXT` | text |
| 7 | `started_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 8 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 9 | `folders_attempted` | `integer` | no | `0` | `INTEGER` | int |
| 10 | `folders_completed` | `integer` | no | `0` | `INTEGER` | int |
| 11 | `provider_ids_seen` | `integer` | no | `0` | `INTEGER` | int |
| 12 | `ingestion_items_inserted` | `integer` | no | `0` | `INTEGER` | int |
| 13 | `ingestion_items_existing` | `integer` | no | `0` | `INTEGER` | int |
| 14 | `error_code` | `text` | yes |  | `TEXT` | text |
| 15 | `error_detail` | `text` | yes |  | `TEXT` | text |
| 16 | `lease_generation` | `bigint` | no | `0` | `INTEGER` | int |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `email_sync_runs_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `email_sync_runs_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `email_sync_runs_provider_check` | check | `CHECK ((provider = ANY (ARRAY['gmail'::text, 'outlook'::text])))` | mechanical |
| `email_sync_runs_run_kind_check` | check | `CHECK ((run_kind = ANY (ARRAY['initial'::text, 'incremental'::text, 'daily_reconcile'::text, 'weekly_reconcile'::text, 'manual_repair'::text])))` | mechanical |
| `email_sync_runs_status_check` | check | `CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'failed'::text, 'abandoned'::text])))` | mechanical |
| `email_sync_runs_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `email_sync_runs_integration_started_idx` | `CREATE INDEX email_sync_runs_integration_started_idx ON public.email_sync_runs USING btree (integration_id, started_at DESC)` | mechanical |
| `email_sync_runs_one_running_per_integration` | `CREATE UNIQUE INDEX email_sync_runs_one_running_per_integration ON public.email_sync_runs USING btree (integration_id) WHERE (status = 'running'::text)` | mechanical |
| `email_sync_runs_pkey` | `CREATE UNIQUE INDEX email_sync_runs_pkey ON public.email_sync_runs USING btree (id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages email sync runs` (ALL, roles {service_role}): using `true`; check `true`

**Draft SQLite DDL**

```sql
CREATE TABLE email_sync_runs (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    folders_attempted INTEGER NOT NULL DEFAULT 0,
    folders_completed INTEGER NOT NULL DEFAULT 0,
    provider_ids_seen INTEGER NOT NULL DEFAULT 0,
    ingestion_items_inserted INTEGER NOT NULL DEFAULT 0,
    ingestion_items_existing INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_detail TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT email_sync_runs_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT email_sync_runs_pkey PRIMARY KEY (id),
    CONSTRAINT email_sync_runs_provider_check CHECK ((provider IN ('gmail', 'outlook'))),
    CONSTRAINT email_sync_runs_run_kind_check CHECK ((run_kind IN ('initial', 'incremental', 'daily_reconcile', 'weekly_reconcile', 'manual_repair'))),
    CONSTRAINT email_sync_runs_status_check CHECK ((status IN ('running', 'completed', 'failed', 'abandoned'))),
    CONSTRAINT email_sync_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_sync_runs_integration_started_idx ON email_sync_runs (integration_id, started_at DESC);
CREATE UNIQUE INDEX email_sync_runs_one_running_per_integration ON email_sync_runs (integration_id) WHERE (status = 'running');
```

## `email_sync_state`

18 columns, 4 constraints, 2 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `provider` | `text` | no |  | `TEXT` | text |
| 4 | `initial_watermark_at` | `timestamp with time zone` | no |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 5 | `next_poll_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 6 | `lease_owner` | `text` | yes |  | `TEXT` | text |
| 7 | `lease_expires_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 8 | `last_started_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 9 | `last_discovery_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 10 | `last_success_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `last_reconciled_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `consecutive_failures` | `integer` | no | `0` | `INTEGER` | int |
| 13 | `last_error_code` | `text` | yes |  | `TEXT` | text |
| 14 | `last_error_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 15 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 16 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 17 | `folders_refreshed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 18 | `lease_generation` | `bigint` | no | `0` | `INTEGER` | int |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `email_sync_state_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `email_sync_state_pkey` | primary key | `PRIMARY KEY (integration_id)` | mechanical |
| `email_sync_state_provider_check` | check | `CHECK ((provider = ANY (ARRAY['gmail'::text, 'outlook'::text])))` | mechanical |
| `email_sync_state_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `email_sync_state_due_idx` | `CREATE INDEX email_sync_state_due_idx ON public.email_sync_state USING btree (next_poll_at, last_success_at NULLS FIRST)` | mechanical |
| `email_sync_state_pkey` | `CREATE UNIQUE INDEX email_sync_state_pkey ON public.email_sync_state USING btree (integration_id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages email sync state` (ALL, roles {service_role}): using `true`; check `true`
- `Users can view own email sync health` (SELECT, roles {authenticated}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE email_sync_state (
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    initial_watermark_at TEXT NOT NULL,
    next_poll_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_started_at TEXT,
    last_discovery_at TEXT,
    last_success_at TEXT,
    last_reconciled_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    folders_refreshed_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT email_sync_state_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT email_sync_state_pkey PRIMARY KEY (integration_id),
    CONSTRAINT email_sync_state_provider_check CHECK ((provider IN ('gmail', 'outlook'))),
    CONSTRAINT email_sync_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_sync_state_due_idx ON email_sync_state (next_poll_at, last_success_at NULLS FIRST);
```

## `emails`

45 columns, 8 constraints, 10 indexes, 3 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `integration_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider_message_id` | `text` | no |  | `TEXT` | text |
| 5 | `thread_id` | `text` | yes |  | `TEXT` | text |
| 6 | `subject` | `text` | yes |  | `TEXT` | text |
| 7 | `from_email` | `text` | yes |  | `TEXT` | text |
| 8 | `from_name` | `text` | yes |  | `TEXT` | text |
| 9 | `to_emails` | `_text` | yes |  | `TEXT` | text[] -> JSON array text, CHECK (json_valid(col)) |
| 10 | `date_sent` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `snippet` | `text` | yes |  | `TEXT` | text |
| 12 | `provider_labels` | `_text` | no | `'{}'::text[]` | `TEXT` | text[] -> JSON array text, CHECK (json_valid(col)) |
| 13 | `is_spam` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 14 | `is_trash` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 15 | `is_promotions` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 16 | `is_social` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 17 | `is_updates` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 18 | `is_forums` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 19 | `is_primary` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 20 | `is_important` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 21 | `is_starred` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 22 | `is_unread` | `boolean` | yes | `true` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 23 | `storage_path` | `text` | yes |  | `TEXT` | text |
| 24 | `has_attachments` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 25 | `content_hash` | `text` | yes |  | `TEXT` | text |
| 26 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 27 | `processing_status` | `text` | yes | `'pending'::text` | `TEXT` | text |
| 28 | `processing_error` | `text` | yes |  | `TEXT` | text |
| 29 | `processed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 30 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 31 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 32 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 33 | `max_attempts` | `integer` | no | `3` | `INTEGER` | int |
| 34 | `body_text` | `text` | yes |  | `TEXT` | text |
| 36 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 37 | `dead_letter_reason` | `text` | yes |  | `TEXT` | text |
| 38 | `dead_letter_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 39 | `email_provider` | `text` | no | `'gmail'::text` | `TEXT` | text |
| 40 | `provider_folder_ids` | `_text` | no | `'{}'::text[]` | `TEXT` | text[] -> JSON array text, CHECK (json_valid(col)) |
| 41 | `processing_outcome` | `text` | yes |  | `TEXT` | text |
| 42 | `processing_explanation` | `text` | yes |  | `TEXT` | text |
| 43 | `processing_result` | `jsonb` | yes |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 44 | `email_folder_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 45 | `is_calendar_invite` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 46 | `lock_generation` | `bigint` | no | `0` | `INTEGER` | int |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `emails_email_folder_id_fkey` | foreign key | `FOREIGN KEY (email_folder_id) REFERENCES email_folders(id) ON DELETE SET NULL` | mechanical |
| `emails_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE SET NULL` | mechanical |
| `emails_pending_is_claimable_check` | check | `CHECK (((processing_status <> 'pending'::text) OR ((attempts < max_attempts) AND (locked_by IS NULL) AND (locked_until IS NULL))))` | mechanical |
| `emails_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `emails_processing_outcome_check` | check | `CHECK (((processing_outcome IS NULL) OR (processing_outcome = ANY (ARRAY['no_event'::text, 'event_matched'::text, 'event_created'::text, 'event_updated'::text, 'event_created_and_updated'::text, 'event_cancelled'::text, 'calendar_invite'::text, 'cancellation_unmatched'::text, 'cancellation_ambiguous'::text]))))` | mechanical |
| `emails_processing_status_check` | check | `CHECK ((processing_status = ANY (ARRAY['pending'::text, 'processing'::text, 'processed'::text, 'failed'::text, 'skipped'::text])))` | mechanical |
| `emails_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |
| `emails_user_provider_message_key` | unique | `UNIQUE (user_id, email_provider, provider_message_id)` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `emails_pkey` | `CREATE UNIQUE INDEX emails_pkey ON public.emails USING btree (id)` | from its constraint |
| `emails_user_provider_message_key` | `CREATE UNIQUE INDEX emails_user_provider_message_key ON public.emails USING btree (user_id, email_provider, provider_message_id)` | from its constraint |
| `idx_emails_content_hash` | `CREATE INDEX idx_emails_content_hash ON public.emails USING btree (user_id, content_hash) WHERE (content_hash IS NOT NULL)` | mechanical |
| `idx_emails_date` | `CREATE INDEX idx_emails_date ON public.emails USING btree (date_sent DESC)` | mechanical |
| `idx_emails_history` | `CREATE INDEX idx_emails_history ON public.emails USING btree (user_id, date_sent DESC) WHERE (processing_status = ANY (ARRAY['processed'::text, 'failed'::text]))` | mechanical |
| `idx_emails_pending_processing` | `CREATE INDEX idx_emails_pending_processing ON public.emails USING btree (processing_status, created_at) WHERE (processing_status = 'pending'::text)` | mechanical |
| `idx_emails_processing_status` | `CREATE INDEX idx_emails_processing_status ON public.emails USING btree (processing_status)` | mechanical |
| `idx_emails_provider_message_id` | `CREATE INDEX idx_emails_provider_message_id ON public.emails USING btree (provider_message_id)` | mechanical |
| `idx_emails_user` | `CREATE INDEX idx_emails_user ON public.emails USING btree (user_id)` | mechanical |
| `idx_emails_user_date` | `CREATE INDEX idx_emails_user_date ON public.emails USING btree (user_id, date_sent DESC)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `emails_notify_pending`: `CREATE TRIGGER emails_notify_pending AFTER INSERT OR UPDATE OF processing_status ON public.emails FOR EACH ROW WHEN ((new.processing_status = 'pending'::text)) EXECUTE FUNCTION notify_work_available('email_pending')`
- `parse_provider_labels_trigger`: `CREATE TRIGGER parse_provider_labels_trigger BEFORE INSERT OR UPDATE OF provider_labels ON public.emails FOR EACH ROW EXECUTE FUNCTION parse_provider_labels()`
- `trg_emails_broadcast_upd`: `CREATE TRIGGER trg_emails_broadcast_upd AFTER UPDATE OF processing_status, processing_error ON public.emails FOR EACH ROW EXECUTE FUNCTION trg_emails_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own emails` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE emails (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    integration_id TEXT,
    provider_message_id TEXT NOT NULL,
    thread_id TEXT,
    subject TEXT,
    from_email TEXT,
    from_name TEXT,
    to_emails TEXT CHECK (to_emails IS NULL OR json_valid(to_emails)),
    date_sent TEXT,
    snippet TEXT,
    provider_labels TEXT NOT NULL DEFAULT '[]' CHECK (provider_labels IS NULL OR json_valid(provider_labels)),
    is_spam INTEGER DEFAULT 0 CHECK (is_spam IN (0,1)),
    is_trash INTEGER DEFAULT 0 CHECK (is_trash IN (0,1)),
    is_promotions INTEGER DEFAULT 0 CHECK (is_promotions IN (0,1)),
    is_social INTEGER DEFAULT 0 CHECK (is_social IN (0,1)),
    is_updates INTEGER DEFAULT 0 CHECK (is_updates IN (0,1)),
    is_forums INTEGER DEFAULT 0 CHECK (is_forums IN (0,1)),
    is_primary INTEGER DEFAULT 0 CHECK (is_primary IN (0,1)),
    is_important INTEGER DEFAULT 0 CHECK (is_important IN (0,1)),
    is_starred INTEGER DEFAULT 0 CHECK (is_starred IN (0,1)),
    is_unread INTEGER DEFAULT 1 CHECK (is_unread IN (0,1)),
    storage_path TEXT,
    has_attachments INTEGER DEFAULT 0 CHECK (has_attachments IN (0,1)),
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    processing_status TEXT DEFAULT 'pending',
    processing_error TEXT,
    processed_at TEXT,
    locked_until TEXT,
    locked_by TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    body_text TEXT,
    next_retry_at TEXT,
    dead_letter_reason TEXT,
    dead_letter_at TEXT,
    email_provider TEXT NOT NULL DEFAULT 'gmail',
    provider_folder_ids TEXT NOT NULL DEFAULT '[]' CHECK (provider_folder_ids IS NULL OR json_valid(provider_folder_ids)),
    processing_outcome TEXT,
    processing_explanation TEXT,
    processing_result TEXT CHECK (processing_result IS NULL OR json_valid(processing_result)),
    email_folder_id TEXT,
    is_calendar_invite INTEGER NOT NULL DEFAULT 0 CHECK (is_calendar_invite IN (0,1)),
    lock_generation INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT emails_email_folder_id_fkey FOREIGN KEY (email_folder_id) REFERENCES email_folders(id) ON DELETE SET NULL,
    CONSTRAINT emails_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE SET NULL,
    CONSTRAINT emails_pending_is_claimable_check CHECK (((processing_status <> 'pending') OR ((attempts < max_attempts) AND (locked_by IS NULL) AND (locked_until IS NULL)))),
    CONSTRAINT emails_pkey PRIMARY KEY (id),
    CONSTRAINT emails_processing_outcome_check CHECK (((processing_outcome IS NULL) OR (processing_outcome IN ('no_event', 'event_matched', 'event_created', 'event_updated', 'event_created_and_updated', 'event_cancelled', 'calendar_invite', 'cancellation_unmatched', 'cancellation_ambiguous')))),
    CONSTRAINT emails_processing_status_check CHECK ((processing_status IN ('pending', 'processing', 'processed', 'failed', 'skipped'))),
    CONSTRAINT emails_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT emails_user_provider_message_key UNIQUE (user_id, email_provider, provider_message_id)
) STRICT;
CREATE INDEX idx_emails_content_hash ON emails (user_id, content_hash) WHERE (content_hash IS NOT NULL);
CREATE INDEX idx_emails_date ON emails (date_sent DESC);
CREATE INDEX idx_emails_history ON emails (user_id, date_sent DESC) WHERE (processing_status IN ('processed', 'failed'));
CREATE INDEX idx_emails_pending_processing ON emails (processing_status, created_at) WHERE (processing_status = 'pending');
CREATE INDEX idx_emails_processing_status ON emails (processing_status);
CREATE INDEX idx_emails_provider_message_id ON emails (provider_message_id);
CREATE INDEX idx_emails_user ON emails (user_id);
CREATE INDEX idx_emails_user_date ON emails (user_id, date_sent DESC);
```

## `event_change_proposals`

12 columns, 11 constraints, 4 indexes, 2 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `event_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `source_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 5 | `kind` | `text` | no |  | `TEXT` | text |
| 6 | `status` | `text` | no |  | `TEXT` | text |
| 7 | `change_set` | `jsonb` | no |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 8 | `event_snapshot_before` | `jsonb` | no |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 9 | `resolution_reason` | `text` | yes |  | `TEXT` | text |
| 10 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 11 | `resolved_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `event_change_proposals_change_set_check` | check | `CHECK (((jsonb_typeof(change_set) = 'object'::text) AND (change_set <> '{}'::jsonb)))` | HAND: contains `jsonb_` -- check SQLite equivalent |
| `event_change_proposals_event_id_fkey` | foreign key | `FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE` | mechanical |
| `event_change_proposals_event_snapshot_before_check` | check | `CHECK (((jsonb_typeof(event_snapshot_before) = 'object'::text) AND (event_snapshot_before <> '{}'::jsonb)))` | HAND: contains `jsonb_` -- check SQLite equivalent |
| `event_change_proposals_invariant` | trigger | `TRIGGER DEFERRABLE INITIALLY DEFERRED` | HAND: trigger constraint |
| `event_change_proposals_kind_check` | check | `CHECK ((kind = ANY (ARRAY['material_update'::text, 'cancellation'::text])))` | mechanical |
| `event_change_proposals_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `event_change_proposals_source_id_fkey` | foreign key | `FOREIGN KEY (source_id) REFERENCES event_sources(id) ON DELETE RESTRICT` | mechanical |
| `event_change_proposals_source_id_key` | unique | `UNIQUE (source_id)` | mechanical |
| `event_change_proposals_source_owner_check` | check | `CHECK ((user_id IS NOT NULL))` | mechanical |
| `event_change_proposals_status_check` | check | `CHECK ((status = ANY (ARRAY['pending'::text, 'applied'::text, 'rejected'::text, 'superseded'::text, 'closed_legacy'::text])))` | mechanical |
| `event_change_proposals_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `event_change_proposals_event_created_idx` | `CREATE INDEX event_change_proposals_event_created_idx ON public.event_change_proposals USING btree (event_id, created_at DESC, id DESC)` | mechanical |
| `event_change_proposals_one_pending_per_event` | `CREATE UNIQUE INDEX event_change_proposals_one_pending_per_event ON public.event_change_proposals USING btree (event_id) WHERE (status = 'pending'::text)` | mechanical |
| `event_change_proposals_pkey` | `CREATE UNIQUE INDEX event_change_proposals_pkey ON public.event_change_proposals USING btree (id)` | from its constraint |
| `event_change_proposals_source_id_key` | `CREATE UNIQUE INDEX event_change_proposals_source_id_key ON public.event_change_proposals USING btree (source_id)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `event_change_proposals_invariant`: `CREATE CONSTRAINT TRIGGER event_change_proposals_invariant AFTER INSERT OR DELETE OR UPDATE ON public.event_change_proposals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_event_change_proposal_invariant()`
- `trg_event_change_proposals_broadcast`: `CREATE TRIGGER trg_event_change_proposals_broadcast AFTER INSERT OR DELETE OR UPDATE ON public.event_change_proposals FOR EACH ROW EXECUTE FUNCTION trg_event_change_proposals_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `event_change_proposals_owner_select` (SELECT, roles {authenticated}): using `(user_id = auth.uid())`

**Draft SQLite DDL**

```sql
CREATE TABLE event_change_proposals (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    change_set TEXT NOT NULL CHECK (change_set IS NULL OR json_valid(change_set)),
    event_snapshot_before TEXT NOT NULL CHECK (event_snapshot_before IS NULL OR json_valid(event_snapshot_before)),
    resolution_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT event_change_proposals_change_set_check CHECK (((jsonb_typeof(change_set) = 'object') AND (change_set <> '{}'))),
    CONSTRAINT event_change_proposals_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_change_proposals_event_snapshot_before_check CHECK (((jsonb_typeof(event_snapshot_before) = 'object') AND (event_snapshot_before <> '{}'))),
    CONSTRAINT event_change_proposals_kind_check CHECK ((kind IN ('material_update', 'cancellation'))),
    CONSTRAINT event_change_proposals_pkey PRIMARY KEY (id),
    CONSTRAINT event_change_proposals_source_id_fkey FOREIGN KEY (source_id) REFERENCES event_sources(id) ON DELETE RESTRICT,
    CONSTRAINT event_change_proposals_source_id_key UNIQUE (source_id),
    CONSTRAINT event_change_proposals_source_owner_check CHECK ((user_id IS NOT NULL)),
    CONSTRAINT event_change_proposals_status_check CHECK ((status IN ('pending', 'applied', 'rejected', 'superseded', 'closed_legacy'))),
    CONSTRAINT event_change_proposals_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX event_change_proposals_event_created_idx ON event_change_proposals (event_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX event_change_proposals_one_pending_per_event ON event_change_proposals (event_id) WHERE (status = 'pending');
```

## `event_identity_hints`

12 columns, 9 constraints, 4 indexes, 0 triggers, 0 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `event_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `source_email_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 5 | `kind` | `text` | no |  | `TEXT` | text |
| 6 | `value_hash` | `text` | no |  | `TEXT` | text |
| 7 | `recurrence_id` | `text` | no | `''::text` | `TEXT` | text |
| 8 | `strength` | `text` | no |  | `TEXT` | text |
| 9 | `sequence` | `integer` | no | `0` | `INTEGER` | int |
| 10 | `dtstamp` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 12 | `calendar_entry_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `event_identity_hints_calendar_entry_id_fkey` | foreign key | `FOREIGN KEY (calendar_entry_id) REFERENCES calendar_entries(id) ON DELETE CASCADE` | mechanical |
| `event_identity_hints_event_id_fkey` | foreign key | `FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE` | mechanical |
| `event_identity_hints_event_id_kind_value_hash_recurrence_id_key` | unique | `UNIQUE (event_id, kind, value_hash, recurrence_id)` | mechanical |
| `event_identity_hints_kind_check` | check | `CHECK ((kind = ANY (ARRAY['ical_uid'::text, 'provider_thread'::text, 'join_url'::text, 'management_url'::text])))` | mechanical |
| `event_identity_hints_one_entity` | check | `CHECK ((num_nonnulls(event_id, calendar_entry_id) = 1))` | HAND: contains `num_nonnulls` -- check SQLite equivalent |
| `event_identity_hints_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `event_identity_hints_source_email_id_fkey` | foreign key | `FOREIGN KEY (source_email_id) REFERENCES emails(id) ON DELETE SET NULL` | mechanical |
| `event_identity_hints_strength_check` | check | `CHECK ((strength = ANY (ARRAY['authoritative'::text, 'supporting'::text])))` | mechanical |
| `event_identity_hints_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `event_identity_hints_calendar_entry_key` | `CREATE UNIQUE INDEX event_identity_hints_calendar_entry_key ON public.event_identity_hints USING btree (calendar_entry_id, kind, value_hash, recurrence_id)` | mechanical |
| `event_identity_hints_event_id_kind_value_hash_recurrence_id_key` | `CREATE UNIQUE INDEX event_identity_hints_event_id_kind_value_hash_recurrence_id_key ON public.event_identity_hints USING btree (event_id, kind, value_hash, recurrence_id)` | from its constraint |
| `event_identity_hints_lookup_idx` | `CREATE INDEX event_identity_hints_lookup_idx ON public.event_identity_hints USING btree (user_id, kind, value_hash, recurrence_id)` | mechanical |
| `event_identity_hints_pkey` | `CREATE UNIQUE INDEX event_identity_hints_pkey ON public.event_identity_hints USING btree (id)` | from its constraint |

**Draft SQLite DDL**

```sql
CREATE TABLE event_identity_hints (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_id TEXT,
    source_email_id TEXT,
    kind TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    recurrence_id TEXT NOT NULL DEFAULT '',
    strength TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    dtstamp TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    calendar_entry_id TEXT,
    CONSTRAINT event_identity_hints_calendar_entry_id_fkey FOREIGN KEY (calendar_entry_id) REFERENCES calendar_entries(id) ON DELETE CASCADE,
    CONSTRAINT event_identity_hints_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_identity_hints_event_id_kind_value_hash_recurrence_id_key UNIQUE (event_id, kind, value_hash, recurrence_id),
    CONSTRAINT event_identity_hints_kind_check CHECK ((kind IN ('ical_uid', 'provider_thread', 'join_url', 'management_url'))),
    CONSTRAINT event_identity_hints_one_entity CHECK ((num_nonnulls(event_id, calendar_entry_id) = 1)),
    CONSTRAINT event_identity_hints_pkey PRIMARY KEY (id),
    CONSTRAINT event_identity_hints_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES emails(id) ON DELETE SET NULL,
    CONSTRAINT event_identity_hints_strength_check CHECK ((strength IN ('authoritative', 'supporting'))),
    CONSTRAINT event_identity_hints_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE UNIQUE INDEX event_identity_hints_calendar_entry_key ON event_identity_hints (calendar_entry_id, kind, value_hash, recurrence_id);
CREATE INDEX event_identity_hints_lookup_idx ON event_identity_hints (user_id, kind, value_hash, recurrence_id);
```

## `event_repair_audit`

8 columns, 3 constraints, 3 indexes, 0 triggers, 0 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `event_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `action` | `text` | no |  | `TEXT` | text |
| 5 | `reason` | `text` | no |  | `TEXT` | text |
| 6 | `actor` | `text` | no |  | `TEXT` | text |
| 7 | `pre_change` | `jsonb` | no | `'{}'::jsonb` | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 8 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `event_repair_audit_action_check` | check | `CHECK ((action = ANY (ARRAY['merge_duplicate_group'::text, 'merge_source'::text, 'cancel_event'::text, 'resolve_proposal'::text])))` | mechanical |
| `event_repair_audit_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `event_repair_audit_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `event_repair_audit_event_created_idx` | `CREATE INDEX event_repair_audit_event_created_idx ON public.event_repair_audit USING btree (event_id, created_at DESC)` | mechanical |
| `event_repair_audit_pkey` | `CREATE UNIQUE INDEX event_repair_audit_pkey ON public.event_repair_audit USING btree (id)` | from its constraint |
| `event_repair_audit_user_created_idx` | `CREATE INDEX event_repair_audit_user_created_idx ON public.event_repair_audit USING btree (user_id, created_at DESC)` | mechanical |

**Draft SQLite DDL**

```sql
CREATE TABLE event_repair_audit (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_id TEXT,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    pre_change TEXT NOT NULL DEFAULT '[]' CHECK (pre_change IS NULL OR json_valid(pre_change)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT event_repair_audit_action_check CHECK ((action IN ('merge_duplicate_group', 'merge_source', 'cancel_event', 'resolve_proposal'))),
    CONSTRAINT event_repair_audit_pkey PRIMARY KEY (id),
    CONSTRAINT event_repair_audit_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX event_repair_audit_event_created_idx ON event_repair_audit (event_id, created_at DESC);
CREATE INDEX event_repair_audit_user_created_idx ON event_repair_audit (user_id, created_at DESC);
```

## `event_sources`

8 columns, 6 constraints, 5 indexes, 2 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `event_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `email_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `source_type` | `text` | no | `'new_invitation'::text` | `TEXT` | text |
| 5 | `extracted_data` | `jsonb` | no |  | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 8 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 9 | `source_origin` | `text` | no | `'email'::text` | `TEXT` | text |
| 10 | `google_calendar_source_event_id` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `event_sources_email_id_fkey` | foreign key | `FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE` | mechanical |
| `event_sources_event_id_fkey` | foreign key | `FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE` | mechanical |
| `event_sources_origin_check` | check | `CHECK ((((source_origin = 'email'::text) AND (email_id IS NOT NULL)) OR ((source_origin = 'google_calendar'::text) AND (google_calendar_source_event_id IS NOT NULL)) OR (source_origin = 'google_photos'::text)))` | mechanical |
| `event_sources_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `event_sources_source_origin_check` | check | `CHECK ((source_origin = ANY (ARRAY['email'::text, 'google_calendar'::text, 'google_photos'::text])))` | mechanical |
| `event_sources_source_type_check` | check | `CHECK ((source_type = ANY (ARRAY['new_invitation'::text, 'update'::text, 'cancellation'::text, 'reminder'::text, 'unknown'::text])))` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `event_sources_event_email_unique` | `CREATE UNIQUE INDEX event_sources_event_email_unique ON public.event_sources USING btree (event_id, email_id) WHERE (source_origin = 'email'::text)` | mechanical |
| `event_sources_event_gcal_unique` | `CREATE UNIQUE INDEX event_sources_event_gcal_unique ON public.event_sources USING btree (event_id, google_calendar_source_event_id) WHERE (source_origin = 'google_calendar'::text)` | mechanical |
| `event_sources_pkey` | `CREATE UNIQUE INDEX event_sources_pkey ON public.event_sources USING btree (id)` | from its constraint |
| `idx_event_sources_email` | `CREATE INDEX idx_event_sources_email ON public.event_sources USING btree (email_id)` | mechanical |
| `idx_event_sources_event` | `CREATE INDEX idx_event_sources_event ON public.event_sources USING btree (event_id)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `trg_event_sources_broadcast_ins`: `CREATE TRIGGER trg_event_sources_broadcast_ins AFTER INSERT ON public.event_sources FOR EACH ROW EXECUTE FUNCTION trg_event_sources_broadcast()`
- `trg_event_sources_broadcast_upd`: `CREATE TRIGGER trg_event_sources_broadcast_upd AFTER UPDATE OF source_origin ON public.event_sources FOR EACH ROW EXECUTE FUNCTION trg_event_sources_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `event_sources_owner_select` (SELECT, roles {authenticated}): using `(EXISTS ( SELECT 1
   FROM events
  WHERE ((events.id = event_sources.event_id) AND (events.user_id = auth.uid()))))`

**Draft SQLite DDL**

```sql
CREATE TABLE event_sources (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    email_id TEXT,
    source_type TEXT NOT NULL DEFAULT 'new_invitation',
    extracted_data TEXT NOT NULL CHECK (extracted_data IS NULL OR json_valid(extracted_data)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    source_origin TEXT NOT NULL DEFAULT 'email',
    google_calendar_source_event_id TEXT,
    CONSTRAINT event_sources_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    CONSTRAINT event_sources_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_sources_origin_check CHECK ((((source_origin = 'email') AND (email_id IS NOT NULL)) OR ((source_origin = 'google_calendar') AND (google_calendar_source_event_id IS NOT NULL)) OR (source_origin = 'google_photos'))),
    CONSTRAINT event_sources_pkey PRIMARY KEY (id),
    CONSTRAINT event_sources_source_origin_check CHECK ((source_origin IN ('email', 'google_calendar', 'google_photos'))),
    CONSTRAINT event_sources_source_type_check CHECK ((source_type IN ('new_invitation', 'update', 'cancellation', 'reminder', 'unknown')))
) STRICT;
CREATE UNIQUE INDEX event_sources_event_email_unique ON event_sources (event_id, email_id) WHERE (source_origin = 'email');
CREATE UNIQUE INDEX event_sources_event_gcal_unique ON event_sources (event_id, google_calendar_source_event_id) WHERE (source_origin = 'google_calendar');
CREATE INDEX idx_event_sources_email ON event_sources (email_id);
CREATE INDEX idx_event_sources_event ON event_sources (event_id);
```

## `events`

17 columns, 6 constraints, 4 indexes, 5 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `title` | `text` | no |  | `TEXT` | text |
| 4 | `start_datetime` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 5 | `end_datetime` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 6 | `all_day` | `boolean` | yes | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 7 | `location` | `text` | yes |  | `TEXT` | text |
| 8 | `description` | `text` | yes |  | `TEXT` | text |
| 9 | `source_attribution` | `text` | yes |  | `TEXT` | text |
| 11 | `google_calendar_event_id` | `text` | yes |  | `TEXT` | text |
| 12 | `synced_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 14 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 20 | `importance` | `text` | no | `'action_required'::text` | `TEXT` | text |
| 24 | `recurrence_rule` | `text` | yes |  | `TEXT` | text |
| 26 | `recovery_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 29 | `review_status` | `text` | no | `'pending_review'::text` | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `events_change_proposal_invariant` | trigger | `TRIGGER DEFERRABLE INITIALLY DEFERRED` | HAND: trigger constraint |
| `events_importance_check` | check | `CHECK ((importance = ANY (ARRAY['action_required'::text, 'fyi'::text])))` | mechanical |
| `events_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `events_recovery_id_fkey` | foreign key | `FOREIGN KEY (recovery_id) REFERENCES integration_recoveries(id) ON DELETE SET NULL` | mechanical |
| `events_review_status_check` | check | `CHECK ((review_status = ANY (ARRAY['pending_review'::text, 'active'::text, 'rejected'::text, 'cancelled'::text])))` | mechanical |
| `events_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `events_pkey` | `CREATE UNIQUE INDEX events_pkey ON public.events USING btree (id)` | from its constraint |
| `events_recovery_id_idx` | `CREATE INDEX events_recovery_id_idx ON public.events USING btree (recovery_id) WHERE (recovery_id IS NOT NULL)` | mechanical |
| `idx_events_start_date` | `CREATE INDEX idx_events_start_date ON public.events USING btree (user_id, start_datetime)` | mechanical |
| `idx_events_user_id` | `CREATE INDEX idx_events_user_id ON public.events USING btree (user_id)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `events_change_proposal_invariant`: `CREATE CONSTRAINT TRIGGER events_change_proposal_invariant AFTER INSERT OR UPDATE ON public.events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_event_change_proposal_invariant()`
- `set_events_updated_at`: `CREATE TRIGGER set_events_updated_at BEFORE UPDATE ON public.events FOR EACH ROW EXECUTE FUNCTION set_updated_at()`
- `trg_events_broadcast_del`: `CREATE TRIGGER trg_events_broadcast_del AFTER DELETE ON public.events FOR EACH ROW EXECUTE FUNCTION trg_events_broadcast()`
- `trg_events_broadcast_ins`: `CREATE TRIGGER trg_events_broadcast_ins AFTER INSERT ON public.events FOR EACH ROW EXECUTE FUNCTION trg_events_broadcast()`
- `trg_events_broadcast_upd`: `CREATE TRIGGER trg_events_broadcast_upd AFTER UPDATE OF review_status, title, start_datetime, end_datetime ON public.events FOR EACH ROW EXECUTE FUNCTION trg_events_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own events` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE events (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_datetime TEXT,
    end_datetime TEXT,
    all_day INTEGER DEFAULT 0 CHECK (all_day IN (0,1)),
    location TEXT,
    description TEXT,
    source_attribution TEXT,
    google_calendar_event_id TEXT,
    synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    importance TEXT NOT NULL DEFAULT 'action_required',
    recurrence_rule TEXT,
    recovery_id TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending_review',
    CONSTRAINT events_importance_check CHECK ((importance IN ('action_required', 'fyi'))),
    CONSTRAINT events_pkey PRIMARY KEY (id),
    CONSTRAINT events_recovery_id_fkey FOREIGN KEY (recovery_id) REFERENCES integration_recoveries(id) ON DELETE SET NULL,
    CONSTRAINT events_review_status_check CHECK ((review_status IN ('pending_review', 'active', 'rejected', 'cancelled'))),
    CONSTRAINT events_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX events_recovery_id_idx ON events (recovery_id) WHERE (recovery_id IS NOT NULL);
CREATE INDEX idx_events_start_date ON events (user_id, start_datetime);
CREATE INDEX idx_events_user_id ON events (user_id);
```

## `global_limits`

7 columns, 2 constraints, 2 indexes, 1 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `limit_type` | `text` | no |  | `TEXT` | text |
| 3 | `default_limit` | `integer` | no |  | `INTEGER` | int |
| 4 | `max_allowed` | `integer` | no |  | `INTEGER` | int |
| 5 | `is_active` | `boolean` | no | `true` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 6 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 7 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `global_limits_limit_type_key` | unique | `UNIQUE (limit_type)` | mechanical |
| `global_limits_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `global_limits_limit_type_key` | `CREATE UNIQUE INDEX global_limits_limit_type_key ON public.global_limits USING btree (limit_type)` | from its constraint |
| `global_limits_pkey` | `CREATE UNIQUE INDEX global_limits_pkey ON public.global_limits USING btree (id)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `set_global_limits_updated_at`: `CREATE TRIGGER set_global_limits_updated_at BEFORE UPDATE ON public.global_limits FOR EACH ROW EXECUTE FUNCTION set_updated_at()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Authenticated users can view global limits` (SELECT, roles {authenticated}): using `true`
- `Service role can manage global limits` (ALL, roles {service_role}): using `true`; check `true`

**Draft SQLite DDL**

```sql
CREATE TABLE global_limits (
    id TEXT NOT NULL,
    limit_type TEXT NOT NULL,
    default_limit INTEGER NOT NULL,
    max_allowed INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT global_limits_limit_type_key UNIQUE (limit_type),
    CONSTRAINT global_limits_pkey PRIMARY KEY (id)
) STRICT;

```

## `graph_api_failures`

19 columns, 4 constraints, 4 indexes, 0 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `occurred_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 3 | `environment` | `text` | no |  | `TEXT` | text |
| 4 | `integration_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 5 | `graph_surface` | `text` | no |  | `TEXT` | text |
| 6 | `operation` | `text` | no |  | `TEXT` | text |
| 7 | `http_method` | `text` | no |  | `TEXT` | text |
| 8 | `safe_url_template` | `text` | no |  | `TEXT` | text |
| 9 | `http_status` | `integer` | yes |  | `INTEGER` | int |
| 10 | `graph_error_code` | `text` | yes |  | `TEXT` | text |
| 11 | `request_id` | `text` | yes |  | `TEXT` | text |
| 12 | `client_request_id` | `text` | yes |  | `TEXT` | text |
| 13 | `retry_after_seconds` | `integer` | yes |  | `INTEGER` | int |
| 14 | `failure_class` | `text` | no |  | `TEXT` | text |
| 15 | `response_summary` | `text` | yes |  | `TEXT` | text |
| 16 | `run_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 17 | `attempt` | `integer` | no | `1` | `INTEGER` | int |
| 18 | `will_retry` | `boolean` | no | `false` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 19 | `resolved_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `graph_api_failures_graph_surface_check` | check | `CHECK ((graph_surface = ANY (ARRAY['outlook_mail'::text, 'outlook_calendar'::text, 'onedrive'::text])))` | mechanical |
| `graph_api_failures_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `graph_api_failures_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `graph_api_failures_run_id_fkey` | foreign key | `FOREIGN KEY (run_id) REFERENCES email_sync_runs(id) ON DELETE SET NULL` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `graph_api_failures_class_time_idx` | `CREATE INDEX graph_api_failures_class_time_idx ON public.graph_api_failures USING btree (failure_class, occurred_at DESC)` | mechanical |
| `graph_api_failures_pkey` | `CREATE UNIQUE INDEX graph_api_failures_pkey ON public.graph_api_failures USING btree (id)` | from its constraint |
| `graph_api_failures_surface_time_idx` | `CREATE INDEX graph_api_failures_surface_time_idx ON public.graph_api_failures USING btree (graph_surface, occurred_at DESC)` | mechanical |
| `graph_api_failures_unresolved_idx` | `CREATE INDEX graph_api_failures_unresolved_idx ON public.graph_api_failures USING btree (occurred_at DESC) WHERE (resolved_at IS NULL)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages Graph failures` (ALL, roles {service_role}): using `true`; check `true`

**Draft SQLite DDL**

```sql
CREATE TABLE graph_api_failures (
    id TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    environment TEXT NOT NULL,
    integration_id TEXT,
    graph_surface TEXT NOT NULL,
    operation TEXT NOT NULL,
    http_method TEXT NOT NULL,
    safe_url_template TEXT NOT NULL,
    http_status INTEGER,
    graph_error_code TEXT,
    request_id TEXT,
    client_request_id TEXT,
    retry_after_seconds INTEGER,
    failure_class TEXT NOT NULL,
    response_summary TEXT,
    run_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    will_retry INTEGER NOT NULL DEFAULT 0 CHECK (will_retry IN (0,1)),
    resolved_at TEXT,
    CONSTRAINT graph_api_failures_graph_surface_check CHECK ((graph_surface IN ('outlook_mail', 'outlook_calendar', 'onedrive'))),
    CONSTRAINT graph_api_failures_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT graph_api_failures_pkey PRIMARY KEY (id),
    CONSTRAINT graph_api_failures_run_id_fkey FOREIGN KEY (run_id) REFERENCES email_sync_runs(id) ON DELETE SET NULL
) STRICT;
CREATE INDEX graph_api_failures_class_time_idx ON graph_api_failures (failure_class, occurred_at DESC);
CREATE INDEX graph_api_failures_surface_time_idx ON graph_api_failures (graph_surface, occurred_at DESC);
CREATE INDEX graph_api_failures_unresolved_idx ON graph_api_failures (occurred_at DESC) WHERE (resolved_at IS NULL);
```

## `integration_recoveries`

24 columns, 5 constraints, 3 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `integration_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `provider` | `integration_provider` | no |  | `TEXT` | enum integration_provider -> text, CHECK (col IN ('gmail', 'google_photos', 'google_calendar', 'outlook')) |
| 5 | `reason` | `text` | no |  | `TEXT` | text |
| 6 | `status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 7 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 8 | `max_attempts` | `integer` | no | `5` | `INTEGER` | int |
| 9 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 10 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 11 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `recovery_since` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `checkpoint` | `jsonb` | no | `'{}'::jsonb` | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 14 | `discovered_count` | `integer` | no | `0` | `INTEGER` | int |
| 15 | `requeued_count` | `integer` | no | `0` | `INTEGER` | int |
| 16 | `completed_count` | `integer` | no | `0` | `INTEGER` | int |
| 17 | `remaining_count` | `integer` | no | `0` | `INTEGER` | int |
| 18 | `error_code` | `text` | yes |  | `TEXT` | text |
| 19 | `error_detail` | `text` | yes |  | `TEXT` | text |
| 20 | `requested_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 21 | `started_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 22 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 23 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 24 | `withdrawn_count` | `integer` | no | `0` | `INTEGER` | int |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `integration_recoveries_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `integration_recoveries_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `integration_recoveries_reason_check` | check | `CHECK ((reason = ANY (ARRAY['initial_connection'::text, 'reauthorization'::text])))` | mechanical |
| `integration_recoveries_status_check` | check | `CHECK ((status = ANY (ARRAY['pending'::text, 'processing'::text, 'waiting'::text, 'completed'::text, 'completed_with_errors'::text, 'failed'::text, 'superseded'::text])))` | mechanical |
| `integration_recoveries_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `integration_recoveries_claim_idx` | `CREATE INDEX integration_recoveries_claim_idx ON public.integration_recoveries USING btree (requested_at) WHERE (status = 'pending'::text)` | mechanical |
| `integration_recoveries_one_active_idx` | `CREATE UNIQUE INDEX integration_recoveries_one_active_idx ON public.integration_recoveries USING btree (integration_id) WHERE (status = ANY (ARRAY['pending'::text, 'processing'::text, 'waiting'::text]))` | mechanical |
| `integration_recoveries_pkey` | `CREATE UNIQUE INDEX integration_recoveries_pkey ON public.integration_recoveries USING btree (id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages integration recoveries` (ALL, roles {service_role}): using `true`; check `true`
- `Users can view own integration recoveries` (SELECT, roles {authenticated}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE integration_recoveries (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('gmail', 'google_photos', 'google_calendar', 'outlook')),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_retry_at TEXT,
    locked_by TEXT,
    locked_until TEXT,
    recovery_since TEXT,
    checkpoint TEXT NOT NULL DEFAULT '[]' CHECK (checkpoint IS NULL OR json_valid(checkpoint)),
    discovered_count INTEGER NOT NULL DEFAULT 0,
    requeued_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    remaining_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_detail TEXT,
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    withdrawn_count INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT integration_recoveries_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT integration_recoveries_pkey PRIMARY KEY (id),
    CONSTRAINT integration_recoveries_reason_check CHECK ((reason IN ('initial_connection', 'reauthorization'))),
    CONSTRAINT integration_recoveries_status_check CHECK ((status IN ('pending', 'processing', 'waiting', 'completed', 'completed_with_errors', 'failed', 'superseded'))),
    CONSTRAINT integration_recoveries_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX integration_recoveries_claim_idx ON integration_recoveries (requested_at) WHERE (status = 'pending');
CREATE UNIQUE INDEX integration_recoveries_one_active_idx ON integration_recoveries (integration_id) WHERE (status IN ('pending', 'processing', 'waiting'));
```

## `integrations`

14 columns, 3 constraints, 3 indexes, 3 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `provider` | `integration_provider` | no |  | `TEXT` | enum integration_provider -> text, CHECK (col IN ('gmail', 'google_photos', 'google_calendar', 'outlook')) |
| 4 | `status` | `integration_status` | no | `'active'::integration_status` | `TEXT` | enum integration_status -> text, CHECK (col IN ('active', 'expired', 'revoked', 'error')) |
| 5 | `access_token` | `text` | no |  | `TEXT` | text |
| 6 | `refresh_token` | `text` | yes |  | `TEXT` | text |
| 7 | `token_expiry` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 8 | `provider_email` | `text` | yes |  | `TEXT` | text |
| 9 | `scopes` | `_text` | no | `'{}'::text[]` | `TEXT` | text[] -> JSON array text, CHECK (json_valid(col)) |
| 10 | `sync_cursor` | `text` | yes |  | `TEXT` | text |
| 11 | `last_sync_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 13 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 14 | `last_photo_sync_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `integrations_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `integrations_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |
| `integrations_user_id_provider_key` | unique | `UNIQUE (user_id, provider)` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `idx_integrations_user_status` | `CREATE INDEX idx_integrations_user_status ON public.integrations USING btree (user_id, status)` | mechanical |
| `integrations_pkey` | `CREATE UNIQUE INDEX integrations_pkey ON public.integrations USING btree (id)` | from its constraint |
| `integrations_user_id_provider_key` | `CREATE UNIQUE INDEX integrations_user_id_provider_key ON public.integrations USING btree (user_id, provider)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `integrations_ensure_email_sync_state`: `CREATE TRIGGER integrations_ensure_email_sync_state AFTER INSERT OR UPDATE OF status, provider ON public.integrations FOR EACH ROW EXECUTE FUNCTION ensure_email_sync_state()`
- `set_integrations_updated_at`: `CREATE TRIGGER set_integrations_updated_at BEFORE UPDATE ON public.integrations FOR EACH ROW EXECUTE FUNCTION set_updated_at()`
- `trg_integrations_broadcast_upd`: `CREATE TRIGGER trg_integrations_broadcast_upd AFTER UPDATE OF status ON public.integrations FOR EACH ROW EXECUTE FUNCTION trg_integrations_broadcast()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own integrations` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE integrations (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('gmail', 'google_photos', 'google_calendar', 'outlook')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'revoked', 'error')),
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry TEXT,
    provider_email TEXT,
    scopes TEXT NOT NULL DEFAULT '[]' CHECK (scopes IS NULL OR json_valid(scopes)),
    sync_cursor TEXT,
    last_sync_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_photo_sync_at TEXT,
    CONSTRAINT integrations_pkey PRIMARY KEY (id),
    CONSTRAINT integrations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT integrations_user_id_provider_key UNIQUE (user_id, provider)
) STRICT;
CREATE INDEX idx_integrations_user_status ON integrations (user_id, status);
```

## `llm_call_log`

19 columns, 3 constraints, 5 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `operation_type` | `llm_operation_type` | no |  | `TEXT` | enum llm_operation_type -> text, CHECK (col IN ('extract_events', 'compare_events', 'merge_events', 'propose_event_update', 'classify_email_folder')) |
| 4 | `model` | `text` | no |  | `TEXT` | text |
| 5 | `email_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 6 | `prompt_text` | `text` | no |  | `TEXT` | text |
| 7 | `response_text` | `text` | yes |  | `TEXT` | text |
| 8 | `prompt_tokens` | `integer` | yes |  | `INTEGER` | int |
| 9 | `completion_tokens` | `integer` | yes |  | `INTEGER` | int |
| 10 | `total_tokens` | `integer` | yes |  | `INTEGER` | int |
| 11 | `started_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 12 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `latency_ms` | `integer` | yes |  | `INTEGER` | int |
| 14 | `success` | `boolean` | no | `true` | `INTEGER` | bool -> 0/1, CHECK (col IN (0,1)) |
| 15 | `error_message` | `text` | yes |  | `TEXT` | text |
| 16 | `error_type` | `text` | yes |  | `TEXT` | text |
| 17 | `estimated_cost_usd` | `numeric` | yes |  | `TEXT` | numeric(10,6) -> HAND: decimal text or REAL (see usage) |
| 18 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 19 | `provider` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `llm_call_log_email_id_fkey` | foreign key | `FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL` | mechanical |
| `llm_call_log_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `llm_call_log_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `idx_llm_call_log_email` | `CREATE INDEX idx_llm_call_log_email ON public.llm_call_log USING btree (email_id) WHERE (email_id IS NOT NULL)` | mechanical |
| `idx_llm_call_log_operation` | `CREATE INDEX idx_llm_call_log_operation ON public.llm_call_log USING btree (operation_type)` | mechanical |
| `idx_llm_call_log_success` | `CREATE INDEX idx_llm_call_log_success ON public.llm_call_log USING btree (success) WHERE (success = false)` | mechanical |
| `idx_llm_call_log_user_date` | `CREATE INDEX idx_llm_call_log_user_date ON public.llm_call_log USING btree (user_id, started_at DESC)` | mechanical |
| `llm_call_log_pkey` | `CREATE UNIQUE INDEX llm_call_log_pkey ON public.llm_call_log USING btree (id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role can manage llm call logs` (ALL, roles {service_role}): using `true`; check `true`
- `Users can view own llm calls` (SELECT, roles {authenticated}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE llm_call_log (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('extract_events', 'compare_events', 'merge_events', 'propose_event_update', 'classify_email_folder')),
    model TEXT NOT NULL,
    email_id TEXT,
    prompt_text TEXT NOT NULL,
    response_text TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    latency_ms INTEGER,
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0,1)),
    error_message TEXT,
    error_type TEXT,
    estimated_cost_usd TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    provider TEXT,
    CONSTRAINT llm_call_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL,
    CONSTRAINT llm_call_log_pkey PRIMARY KEY (id),
    CONSTRAINT llm_call_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_llm_call_log_email ON llm_call_log (email_id) WHERE (email_id IS NOT NULL);
CREATE INDEX idx_llm_call_log_operation ON llm_call_log (operation_type);
CREATE INDEX idx_llm_call_log_success ON llm_call_log (success) WHERE (success = false);
CREATE INDEX idx_llm_call_log_user_date ON llm_call_log (user_id, started_at DESC);
```

## `oauth_states`

7 columns, 2 constraints, 2 indexes, 0 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `state` | `text` | no |  | `TEXT` | text |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `provider` | `text` | no |  | `TEXT` | text |
| 4 | `redirect_uri` | `text` | no |  | `TEXT` | text |
| 5 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 6 | `expires_at` | `timestamp with time zone` | no | `(now() + '00:10:00'::interval)` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; HAND: default (now() + '00:10:00'::interval) |
| 7 | `code_verifier` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `oauth_states_pkey` | primary key | `PRIMARY KEY (state)` | mechanical |
| `oauth_states_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `oauth_states_expires_at_idx` | `CREATE INDEX oauth_states_expires_at_idx ON public.oauth_states USING btree (expires_at)` | mechanical |
| `oauth_states_pkey` | `CREATE UNIQUE INDEX oauth_states_pkey ON public.oauth_states USING btree (state)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role full access to oauth_states` (ALL, roles {public}): using `(auth.role() = 'service_role'::text)`; check `(auth.role() = 'service_role'::text)`

**Draft SQLite DDL**

```sql
CREATE TABLE oauth_states (
    state TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at TEXT NOT NULL,
    code_verifier TEXT,
    CONSTRAINT oauth_states_pkey PRIMARY KEY (state),
    CONSTRAINT oauth_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX oauth_states_expires_at_idx ON oauth_states (expires_at);
```

## `operational_incidents`

13 columns, 6 constraints, 2 indexes, 0 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `incident_key` | `text` | no |  | `TEXT` | text |
| 3 | `integration_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 4 | `user_id` | `uuid` | yes |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 5 | `incident_type` | `text` | no |  | `TEXT` | text |
| 6 | `severity` | `text` | no |  | `TEXT` | text |
| 7 | `status` | `text` | no |  | `TEXT` | text |
| 8 | `safe_summary` | `text` | no |  | `TEXT` | text |
| 9 | `first_seen_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 10 | `last_seen_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 11 | `resolved_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `opened_notification_sent_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 13 | `resolved_notification_sent_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `operational_incidents_incident_key_key` | unique | `UNIQUE (incident_key)` | mechanical |
| `operational_incidents_integration_id_fkey` | foreign key | `FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE` | mechanical |
| `operational_incidents_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `operational_incidents_severity_check` | check | `CHECK ((severity = ANY (ARRAY['warning'::text, 'critical'::text])))` | mechanical |
| `operational_incidents_status_check` | check | `CHECK ((status = ANY (ARRAY['open'::text, 'resolved'::text])))` | mechanical |
| `operational_incidents_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `operational_incidents_incident_key_key` | `CREATE UNIQUE INDEX operational_incidents_incident_key_key ON public.operational_incidents USING btree (incident_key)` | from its constraint |
| `operational_incidents_pkey` | `CREATE UNIQUE INDEX operational_incidents_pkey ON public.operational_incidents USING btree (id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role manages operational incidents` (ALL, roles {service_role}): using `true`; check `true`

**Draft SQLite DDL**

```sql
CREATE TABLE operational_incidents (
    id TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    integration_id TEXT,
    user_id TEXT,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at TEXT,
    opened_notification_sent_at TEXT,
    resolved_notification_sent_at TEXT,
    CONSTRAINT operational_incidents_incident_key_key UNIQUE (incident_key),
    CONSTRAINT operational_incidents_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT operational_incidents_pkey PRIMARY KEY (id),
    CONSTRAINT operational_incidents_severity_check CHECK ((severity IN ('warning', 'critical'))),
    CONSTRAINT operational_incidents_status_check CHECK ((status IN ('open', 'resolved'))),
    CONSTRAINT operational_incidents_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;

```

## `photos`

25 columns, 4 constraints, 4 indexes, 0 triggers, 5 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `google_photo_id` | `text` | no |  | `TEXT` | text |
| 4 | `filename` | `text` | yes |  | `TEXT` | text |
| 5 | `description` | `text` | yes |  | `TEXT` | text |
| 6 | `mime_type` | `text` | yes |  | `TEXT` | text |
| 7 | `date_taken` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 8 | `width` | `integer` | yes |  | `INTEGER` | int |
| 9 | `height` | `integer` | yes |  | `INTEGER` | int |
| 10 | `location_latitude` | `numeric` | yes |  | `TEXT` | numeric(None,None) -> HAND: decimal text or REAL (see usage) |
| 11 | `location_longitude` | `numeric` | yes |  | `TEXT` | numeric(None,None) -> HAND: decimal text or REAL (see usage) |
| 12 | `location_display_name` | `text` | yes |  | `TEXT` | text |
| 13 | `storage_path` | `text` | yes |  | `TEXT` | text |
| 14 | `content_hash` | `text` | yes |  | `TEXT` | text |
| 15 | `processing_status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 16 | `processing_error` | `text` | yes |  | `TEXT` | text |
| 17 | `processed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 18 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 19 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 20 | `attempts` | `integer` | no | `0` | `INTEGER` | int |
| 21 | `max_attempts` | `integer` | no | `3` | `INTEGER` | int |
| 22 | `next_retry_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 23 | `dead_letter_reason` | `text` | yes |  | `TEXT` | text |
| 24 | `dead_letter_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 25 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `photos_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `photos_processing_status_check` | check | `CHECK ((processing_status = ANY (ARRAY['pending'::text, 'processing'::text, 'processed'::text, 'failed'::text, 'skipped'::text])))` | mechanical |
| `photos_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |
| `photos_user_id_google_photo_id_key` | unique | `UNIQUE (user_id, google_photo_id)` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `photos_pending_idx` | `CREATE INDEX photos_pending_idx ON public.photos USING btree (processing_status, created_at) WHERE (processing_status = 'pending'::text)` | mechanical |
| `photos_pkey` | `CREATE UNIQUE INDEX photos_pkey ON public.photos USING btree (id)` | from its constraint |
| `photos_user_id_google_photo_id_key` | `CREATE UNIQUE INDEX photos_user_id_google_photo_id_key ON public.photos USING btree (user_id, google_photo_id)` | from its constraint |
| `photos_user_idx` | `CREATE INDEX photos_user_idx ON public.photos USING btree (user_id, created_at DESC)` | mechanical |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role full access to photos` (ALL, roles {public}): using `(auth.role() = 'service_role'::text)`; check `(auth.role() = 'service_role'::text)`
- `Users can delete own photos` (DELETE, roles {public}): using `(auth.uid() = user_id)`
- `Users can insert own photos` (INSERT, roles {public}): using ``; check `(auth.uid() = user_id)`
- `Users can update own photos` (UPDATE, roles {public}): using `(auth.uid() = user_id)`
- `Users can view own photos` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE photos (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    google_photo_id TEXT NOT NULL,
    filename TEXT,
    description TEXT,
    mime_type TEXT,
    date_taken TEXT,
    width INTEGER,
    height INTEGER,
    location_latitude TEXT,
    location_longitude TEXT,
    location_display_name TEXT,
    storage_path TEXT,
    content_hash TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    processed_at TEXT,
    locked_until TEXT,
    locked_by TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_retry_at TEXT,
    dead_letter_reason TEXT,
    dead_letter_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT photos_pkey PRIMARY KEY (id),
    CONSTRAINT photos_processing_status_check CHECK ((processing_status IN ('pending', 'processing', 'processed', 'failed', 'skipped'))),
    CONSTRAINT photos_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT photos_user_id_google_photo_id_key UNIQUE (user_id, google_photo_id)
) STRICT;
CREATE INDEX photos_pending_idx ON photos (processing_status, created_at) WHERE (processing_status = 'pending');
CREATE INDEX photos_user_idx ON photos (user_id, created_at DESC);
```

## `scheduled_tasks`

12 columns, 4 constraints, 3 indexes, 0 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `task_type` | `text` | no |  | `TEXT` | text |
| 4 | `payload` | `jsonb` | no | `'{}'::jsonb` | `TEXT` | json -> canonical JSON text, CHECK (json_valid(col)) |
| 5 | `status` | `text` | no | `'pending'::text` | `TEXT` | text |
| 6 | `scheduled_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 7 | `locked_until` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 8 | `locked_by` | `text` | yes |  | `TEXT` | text |
| 9 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 10 | `started_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 11 | `completed_at` | `timestamp with time zone` | yes |  | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' |
| 12 | `last_error` | `text` | yes |  | `TEXT` | text |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `scheduled_tasks_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `scheduled_tasks_status_check` | check | `CHECK ((status = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'failed'::text])))` | mechanical |
| `scheduled_tasks_task_type_check` | check | `CHECK ((task_type = ANY (ARRAY['photo_fetch'::text, 'email_fetch'::text])))` | mechanical |
| `scheduled_tasks_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `idx_scheduled_tasks_pending` | `CREATE INDEX idx_scheduled_tasks_pending ON public.scheduled_tasks USING btree (status, scheduled_at) WHERE (status = 'pending'::text)` | mechanical |
| `idx_scheduled_tasks_user` | `CREATE INDEX idx_scheduled_tasks_user ON public.scheduled_tasks USING btree (user_id)` | mechanical |
| `scheduled_tasks_pkey` | `CREATE UNIQUE INDEX scheduled_tasks_pkey ON public.scheduled_tasks USING btree (id)` | from its constraint |

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role full access to scheduled tasks` (ALL, roles {public}): using `true`
- `Users can view own scheduled tasks` (SELECT, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE scheduled_tasks (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '[]' CHECK (payload IS NULL OR json_valid(payload)),
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    locked_until TEXT,
    locked_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at TEXT,
    completed_at TEXT,
    last_error TEXT,
    CONSTRAINT scheduled_tasks_pkey PRIMARY KEY (id),
    CONSTRAINT scheduled_tasks_status_check CHECK ((status IN ('pending', 'processing', 'completed', 'failed'))),
    CONSTRAINT scheduled_tasks_task_type_check CHECK ((task_type IN ('photo_fetch', 'email_fetch'))),
    CONSTRAINT scheduled_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_scheduled_tasks_pending ON scheduled_tasks (status, scheduled_at) WHERE (status = 'pending');
CREATE INDEX idx_scheduled_tasks_user ON scheduled_tasks (user_id);
```

## `sender_rules`

7 columns, 4 constraints, 6 indexes, 2 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `sender_domain` | `text` | yes |  | `TEXT` | text |
| 4 | `sender_email` | `text` | yes |  | `TEXT` | text |
| 5 | `action` | `text` | no |  | `TEXT` | text |
| 6 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 7 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `sender_rules_action_check` | check | `CHECK ((action = ANY (ARRAY['auto_approve'::text, 'ignore'::text])))` | mechanical |
| `sender_rules_check` | check | `CHECK (((sender_domain IS NOT NULL) OR (sender_email IS NOT NULL)))` | mechanical |
| `sender_rules_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `sender_rules_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `idx_sender_rules_domain` | `CREATE INDEX idx_sender_rules_domain ON public.sender_rules USING btree (sender_domain)` | mechanical |
| `idx_sender_rules_email` | `CREATE INDEX idx_sender_rules_email ON public.sender_rules USING btree (sender_email)` | mechanical |
| `idx_sender_rules_user` | `CREATE INDEX idx_sender_rules_user ON public.sender_rules USING btree (user_id)` | mechanical |
| `sender_rules_pkey` | `CREATE UNIQUE INDEX sender_rules_pkey ON public.sender_rules USING btree (id)` | from its constraint |
| `sender_rules_user_domain_unique` | `CREATE UNIQUE INDEX sender_rules_user_domain_unique ON public.sender_rules USING btree (user_id, sender_domain) WHERE (sender_domain IS NOT NULL)` | mechanical |
| `sender_rules_user_email_unique` | `CREATE UNIQUE INDEX sender_rules_user_email_unique ON public.sender_rules USING btree (user_id, sender_email) WHERE (sender_email IS NOT NULL)` | mechanical |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `sender_rule_before_delete`: `CREATE TRIGGER sender_rule_before_delete BEFORE DELETE ON public.sender_rules FOR EACH ROW EXECUTE FUNCTION reset_skipped_emails_for_sender_rule()`
- `set_sender_rules_updated_at`: `CREATE TRIGGER set_sender_rules_updated_at BEFORE UPDATE ON public.sender_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own sender_rules` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE sender_rules (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    sender_domain TEXT,
    sender_email TEXT,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT sender_rules_action_check CHECK ((action IN ('auto_approve', 'ignore'))),
    CONSTRAINT sender_rules_check CHECK (((sender_domain IS NOT NULL) OR (sender_email IS NOT NULL))),
    CONSTRAINT sender_rules_pkey PRIMARY KEY (id),
    CONSTRAINT sender_rules_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_sender_rules_domain ON sender_rules (sender_domain);
CREATE INDEX idx_sender_rules_email ON sender_rules (sender_email);
CREATE INDEX idx_sender_rules_user ON sender_rules (user_id);
CREATE UNIQUE INDEX sender_rules_user_domain_unique ON sender_rules (user_id, sender_domain) WHERE (sender_domain IS NOT NULL);
CREATE UNIQUE INDEX sender_rules_user_email_unique ON sender_rules (user_id, sender_email) WHERE (sender_email IS NOT NULL);
```

## `usage_quotas`

11 columns, 3 constraints, 3 indexes, 1 triggers, 2 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` | `TEXT` | uuid -> canonical lowercase 36-char text; generated in Python (uuid4) |
| 2 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 3 | `date` | `date` | no | `CURRENT_DATE` | `TEXT` | date -> 'YYYY-MM-DD'; HAND: default CURRENT_DATE |
| 4 | `llm_calls_count` | `integer` | no | `0` | `INTEGER` | int |
| 5 | `llm_calls_limit` | `integer` | no | `100` | `INTEGER` | int |
| 6 | `email_syncs_count` | `integer` | no | `0` | `INTEGER` | int |
| 7 | `email_syncs_limit` | `integer` | no | `50` | `INTEGER` | int |
| 8 | `calendar_syncs_count` | `integer` | no | `0` | `INTEGER` | int |
| 9 | `calendar_syncs_limit` | `integer` | no | `100` | `INTEGER` | int |
| 10 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 11 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `usage_quotas_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |
| `usage_quotas_user_id_date_key` | unique | `UNIQUE (user_id, date)` | mechanical |
| `usage_quotas_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `idx_usage_quotas_user_date` | `CREATE INDEX idx_usage_quotas_user_date ON public.usage_quotas USING btree (user_id, date)` | mechanical |
| `usage_quotas_pkey` | `CREATE UNIQUE INDEX usage_quotas_pkey ON public.usage_quotas USING btree (id)` | from its constraint |
| `usage_quotas_user_id_date_key` | `CREATE UNIQUE INDEX usage_quotas_user_id_date_key ON public.usage_quotas USING btree (user_id, date)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `set_usage_quotas_updated_at`: `CREATE TRIGGER set_usage_quotas_updated_at BEFORE UPDATE ON public.usage_quotas FOR EACH ROW EXECUTE FUNCTION set_updated_at()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Service role can manage quotas` (ALL, roles {service_role}): using `true`; check `true`
- `Users can view own usage` (SELECT, roles {authenticated}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE usage_quotas (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    llm_calls_count INTEGER NOT NULL DEFAULT 0,
    llm_calls_limit INTEGER NOT NULL DEFAULT 100,
    email_syncs_count INTEGER NOT NULL DEFAULT 0,
    email_syncs_limit INTEGER NOT NULL DEFAULT 50,
    calendar_syncs_count INTEGER NOT NULL DEFAULT 0,
    calendar_syncs_limit INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT usage_quotas_pkey PRIMARY KEY (id),
    CONSTRAINT usage_quotas_user_id_date_key UNIQUE (user_id, date),
    CONSTRAINT usage_quotas_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_usage_quotas_user_date ON usage_quotas (user_id, date);
```

## `user_calendar_settings`

8 columns, 4 constraints, 1 indexes, 1 triggers, 1 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `user_id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 2 | `target_calendar_id` | `text` | yes |  | `TEXT` | text |
| 3 | `default_invitees` | `text` | yes |  | `TEXT` | text |
| 4 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 5 | `timezone` | `text` | no | `'America/New_York'::text` | `TEXT` | text |
| 6 | `all_day_display_mode` | `text` | no | `'all_day'::text` | `TEXT` | text |
| 7 | `all_day_custom_start` | `time without time zone` | yes |  | `TEXT` | time -> 'HH:MM:SS' |
| 8 | `all_day_custom_end` | `time without time zone` | yes |  | `TEXT` | time -> 'HH:MM:SS' |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `user_calendar_settings_all_day_custom_times_check` | check | `CHECK ((((all_day_display_mode = 'custom'::text) AND (all_day_custom_start IS NOT NULL) AND (all_day_custom_end IS NOT NULL) AND (all_day_custom_end > all_day_custom_start)) OR (all_day_display_mode <> 'custom'::text)))` | mechanical |
| `user_calendar_settings_all_day_display_mode_check` | check | `CHECK ((all_day_display_mode = ANY (ARRAY['all_day'::text, 'day_9_to_5'::text, 'morning_8_to_9'::text, 'custom'::text])))` | mechanical |
| `user_calendar_settings_pkey` | primary key | `PRIMARY KEY (user_id)` | mechanical |
| `user_calendar_settings_user_id_fkey` | foreign key | `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `user_calendar_settings_pkey` | `CREATE UNIQUE INDEX user_calendar_settings_pkey ON public.user_calendar_settings USING btree (user_id)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `set_user_calendar_settings_updated_at`: `CREATE TRIGGER set_user_calendar_settings_updated_at BEFORE UPDATE ON public.user_calendar_settings FOR EACH ROW EXECUTE FUNCTION set_updated_at()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can manage own calendar_settings` (ALL, roles {public}): using `(auth.uid() = user_id)`

**Draft SQLite DDL**

```sql
CREATE TABLE user_calendar_settings (
    user_id TEXT NOT NULL,
    target_calendar_id TEXT,
    default_invitees TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    all_day_display_mode TEXT NOT NULL DEFAULT 'all_day',
    all_day_custom_start TEXT,
    all_day_custom_end TEXT,
    CONSTRAINT user_calendar_settings_all_day_custom_times_check CHECK ((((all_day_display_mode = 'custom') AND (all_day_custom_start IS NOT NULL) AND (all_day_custom_end IS NOT NULL) AND (all_day_custom_end > all_day_custom_start)) OR (all_day_display_mode <> 'custom'))),
    CONSTRAINT user_calendar_settings_all_day_display_mode_check CHECK ((all_day_display_mode IN ('all_day', 'day_9_to_5', 'morning_8_to_9', 'custom'))),
    CONSTRAINT user_calendar_settings_pkey PRIMARY KEY (user_id),
    CONSTRAINT user_calendar_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;

```

## `users`

5 columns, 2 constraints, 1 indexes, 1 triggers, 3 RLS policies (RLS on).

| # | Column | Postgres | Null | Default | SQLite | Codec / note |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  | `TEXT` | uuid -> canonical lowercase 36-char text |
| 2 | `email` | `text` | no |  | `TEXT` | text |
| 3 | `display_name` | `text` | yes |  | `TEXT` | text |
| 4 | `created_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |
| 5 | `updated_at` | `timestamp with time zone` | no | `now()` | `TEXT` | timestamptz -> UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ'; now() -> UTC text (Python sets it explicitly on insert) |

**Constraints**

| Name | Kind | Postgres definition | SQLite |
|---|---|---|---|
| `users_id_fkey` | foreign key | `FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE` | auth.users -> accounts(id) |
| `users_pkey` | primary key | `PRIMARY KEY (id)` | mechanical |

**Indexes**

| Name | Postgres definition | SQLite |
|---|---|---|
| `users_pkey` | `CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)` | from its constraint |

**Triggers** (each is replaced as Appendix B says: data-layer code, a SQLite trigger, or the event bus)

- `set_users_updated_at`: `CREATE TRIGGER set_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION set_updated_at()`

**RLS policies** (replaced by the `user_id` scoping every `selko.db` read takes, proven by the cross-user ownership test)

- `Users can insert own profile` (INSERT, roles {public}): using ``; check `(auth.uid() = id)`
- `Users can update own profile` (UPDATE, roles {public}): using `(auth.uid() = id)`
- `Users can view own profile` (SELECT, roles {public}): using `(auth.uid() = id)`

**Draft SQLite DDL**

```sql
CREATE TABLE users (
    id TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT users_id_fkey FOREIGN KEY (id) REFERENCES accounts(id) ON DELETE CASCADE,
    CONSTRAINT users_pkey PRIMARY KEY (id)
) STRICT;

```

## View `email_sync_health`

Becomes a query function in `selko.db` (SQLite views cannot call the Python codecs and this one is read by code, not by clients).

```sql
SELECT s.integration_id,
    s.user_id,
    s.provider,
    s.initial_watermark_at,
    s.next_poll_at,
    s.last_started_at,
    s.last_discovery_at,
    s.last_success_at,
    s.last_reconciled_at,
    s.consecutive_failures,
    s.last_error_code,
    s.last_error_at,
    i.provider_email,
    i.status AS integration_status
   FROM (email_sync_state s
     JOIN integrations i ON ((i.id = s.integration_id)));
```

## Draft DDL validation

Every draft above was executed in SQLite 3.53.1 (in memory, foreign keys on): 27 of 30 tables created.

- `email_sync_state`: **does not parse**: `unsupported use of NULLS FIRST` (HAND)
- `event_change_proposals`: **does not parse**: `no such function: jsonb_typeof` (HAND)
- `event_identity_hints`: **does not parse**: `no such function: num_nonnulls` (HAND)

## Resolution of every HAND item

Each item above that a script could not translate, with its decision. The
`0001_initial.sql` that implements these must create all 30 tables in the
validation harness above (the harness becomes a unit test:
`backend/tests/test_sqlite_schema.py::test_initial_schema_creates_every_table`).

| # | Table / object | Postgres | SQLite decision | Why |
|---|---|---|---|---|
| 1 | `email_sync_state_due_idx` | `(next_poll_at, last_success_at NULLS FIRST)` | `(next_poll_at, last_success_at)` | SQLite rejects `NULLS FIRST` in an index, and already sorts NULLs first in ascending order, so the claim order is unchanged |
| 2 | `event_change_proposals_change_set_check` | `jsonb_typeof(change_set) = 'object' AND change_set <> '{}'` | `CHECK (json_valid(change_set) AND json_type(change_set) = 'object' AND change_set <> '{}')` | `json_type` is SQLite's `jsonb_typeof`; the codec writes canonical JSON, so the empty object is always exactly `{}` |
| 3 | `event_change_proposals_event_snapshot_before_check` | same shape | same translation on `event_snapshot_before` | as above |
| 4 | `event_change_proposals_invariant` | `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` | an explicit check at the end of every proposal transaction in `selko/db/proposals.py` (`_assert_proposal_invariants(conn, event_id)`) | SQLite has no deferred constraint triggers; every writer of proposals is in one module, so the check runs once per transaction, before commit. A unit test asserts no other module writes the table (AST guard, like the event-insert guard) |
| 5 | `events_change_proposal_invariant` | deferred constraint trigger on `events` | the same end-of-transaction check, called by every `selko/db/events.py` writer | as above |
| 6 | `event_identity_hints_one_entity` | `num_nonnulls(event_id, calendar_entry_id) = 1` | `CHECK ((event_id IS NOT NULL) + (calendar_entry_id IS NOT NULL) = 1)` | SQLite booleans are 0/1 integers, so the sum counts non-nulls exactly |
| 7 | `llm_call_log.estimated_cost_usd` | `numeric(10,6)` | `REAL`, same name | report-only (written only by `services/llm_logging.py:162` and `:321`, summed for usage reports); float rounding at the sixth decimal is immaterial, and a rename would ripple for nothing (decision D6) |
| 8 | `oauth_states.expires_at` default | `now() + interval '10 minutes'` | no SQL default; `selko/db/oauth_states.py` sets it explicitly | SQLite defaults can't do date arithmetic in the codec's format; one writer |
| 9 | `photos.location_latitude` | `numeric` | `REAL` | coordinates; no code reads or writes them today (photo ingestion is parked) |
| 10 | `photos.location_longitude` | `numeric` | `REAL` | as above |
| 11 | `usage_quotas.date` default | `CURRENT_DATE` | `DEFAULT (date('now'))` | SQLite's `date('now')` is UTC `YYYY-MM-DD`, the codec's date format; Postgres used the server zone (UTC in Supabase) |
| 12 | `event_change_proposals` table | failed to parse (items 2, 3) | parses once 2 and 3 are applied | verified by the harness |
| 13 | `event_identity_hints` table | failed to parse (item 6) | parses once 6 is applied | verified by the harness |
