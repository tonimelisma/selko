-- Selko's SQLite schema, version 1.
--
-- Written from the live Postgres schema after its 120 migrations
-- (docs/specs/sqlite-single-process/01-schema.md shows the mapping, column by
-- column). Conventions, enforced by selko.db.codec:
--   ids         TEXT, canonical lowercase UUID, generated in Python
--   timestamps  TEXT, UTC, YYYY-MM-DDTHH:MM:SS.ffffffZ (text order = time order)
--   booleans    INTEGER 0/1
--   json/arrays TEXT holding canonical JSON
-- Every table is STRICT. Row ownership, which Postgres enforced with RLS, is
-- enforced by selko.db: every read a client can reach takes a user_id.

-- Accounts replace Supabase Auth's auth.users. Ids are carried over unchanged,
-- so every user_id in every table keeps pointing at the same person
-- (docs/specs/sqlite-single-process/03-api-auth-web.md §B).
CREATE TABLE accounts (
    id TEXT NOT NULL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,                  -- trimmed and lowercased by the data layer
    password_hash TEXT NOT NULL,                 -- bcrypt; GoTrue's $2a$10$ hashes carried verbatim
    email_confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_sign_in_at TEXT,
    disabled_at TEXT
) STRICT;

-- One row per signed-in device. The access token's `sid`.
CREATE TABLE auth_sessions (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    refreshed_at TEXT NOT NULL,
    user_agent TEXT,                             -- first 200 characters; no IP is stored
    revoked_at TEXT,
    revoked_reason TEXT CHECK (revoked_reason IN ('logout', 'logout_global', 'reuse_detected', 'expired', 'password_changed', 'account_deleted'))
) STRICT;
CREATE INDEX auth_sessions_user_active ON auth_sessions (user_id) WHERE revoked_at IS NULL;

-- Refresh tokens: 32 random bytes, stored only as their SHA-256, rotated on
-- every use. A token reused within 10 s of its rotation is a concurrent
-- refresh; later, it is a stolen token and the session is revoked.
CREATE TABLE auth_refresh_tokens (
    id TEXT NOT NULL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auth_sessions(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    parent_id TEXT REFERENCES auth_refresh_tokens(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    rotated_at TEXT
) STRICT;

CREATE TABLE action_history (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    previous_state TEXT CHECK (previous_state IS NULL OR json_valid(previous_state)),
    new_state TEXT CHECK (new_state IS NULL OR json_valid(new_state)),
    external_resource_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT action_history_action_type_check CHECK ((action_type IN ('create', 'update', 'delete'))),
    CONSTRAINT action_history_entity_type_check CHECK ((entity_type IN ('event', 'sender_rule'))),
    CONSTRAINT action_history_pkey PRIMARY KEY (id),
    CONSTRAINT action_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX action_history_entity_idx ON action_history (entity_type, entity_id);
CREATE INDEX action_history_user_action_type_idx ON action_history (user_id, action_type, created_at DESC);
CREATE INDEX action_history_user_created_idx ON action_history (user_id, created_at DESC);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    join_url TEXT,
    CONSTRAINT calendar_entries_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT calendar_entries_origin_check CHECK ((origin IN ('selko_created', 'external'))),
    CONSTRAINT calendar_entries_pkey PRIMARY KEY (id),
    CONSTRAINT calendar_entries_provider_key UNIQUE (integration_id, calendar_id, provider_event_id),
    CONSTRAINT calendar_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_entries_uid_idx ON calendar_entries (user_id, ical_uid, original_start) WHERE ((ical_uid IS NOT NULL) AND (deleted_at IS NULL));
CREATE INDEX calendar_entries_user_start_idx ON calendar_entries (user_id, start_at) WHERE (deleted_at IS NULL);

CREATE TABLE calendar_mirror_state (
    integration_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    sync_token TEXT,
    last_full_resync_at TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    next_poll_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    lease_owner TEXT,
    lease_expires_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    last_started_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT calendar_mirror_state_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT calendar_mirror_state_pkey PRIMARY KEY (integration_id, calendar_id),
    CONSTRAINT calendar_mirror_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_mirror_state_due_idx ON calendar_mirror_state (next_poll_at, lease_expires_at);

CREATE TABLE calendar_sync_log (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    google_calendar_event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    snapshot_synced TEXT NOT NULL CHECK (snapshot_synced IS NULL OR json_valid(snapshot_synced)),
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT calendar_sync_log_action_check CHECK ((action IN ('created', 'updated', 'deleted', 'cancelled'))),
    CONSTRAINT calendar_sync_log_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT calendar_sync_log_pkey PRIMARY KEY (id),
    CONSTRAINT calendar_sync_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX calendar_sync_log_event_id_idx ON calendar_sync_log (event_id);
CREATE INDEX calendar_sync_log_google_id_idx ON calendar_sync_log (google_calendar_event_id);
CREATE INDEX calendar_sync_log_synced_at_idx ON calendar_sync_log (synced_at DESC);
CREATE INDEX calendar_sync_log_user_id_idx ON calendar_sync_log (user_id);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT email_calendar_components_component_index_check CHECK ((component_index >= 0)),
    CONSTRAINT email_calendar_components_email_id_component_index_key UNIQUE (email_id, component_index),
    CONSTRAINT email_calendar_components_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    CONSTRAINT email_calendar_components_pkey PRIMARY KEY (id),
    CONSTRAINT email_calendar_components_recurrence_range_check CHECK (((recurrence_range IS NULL) OR (recurrence_range = 'THISANDFUTURE'))),
    CONSTRAINT email_calendar_components_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_calendar_components_email_idx ON email_calendar_components (email_id);
CREATE INDEX email_calendar_components_user_idx ON email_calendar_components (user_id);

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
    discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE email_ingestion_items (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    provider_folder_ids TEXT NOT NULL DEFAULT '[]' CHECK (provider_folder_ids IS NULL OR json_valid(provider_folder_ids)),
    change_kind TEXT NOT NULL DEFAULT 'upsert',
    first_discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    last_discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE email_sync_runs (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE email_sync_state (
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    initial_watermark_at TEXT NOT NULL,
    next_poll_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_started_at TEXT,
    last_discovery_at TEXT,
    last_success_at TEXT,
    last_reconciled_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    folders_refreshed_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT email_sync_state_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES integrations(id) ON DELETE CASCADE,
    CONSTRAINT email_sync_state_pkey PRIMARY KEY (integration_id),
    CONSTRAINT email_sync_state_provider_check CHECK ((provider IN ('gmail', 'outlook'))),
    CONSTRAINT email_sync_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX email_sync_state_due_idx ON email_sync_state (next_poll_at, last_success_at);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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
-- The expired-lease step of claim_unprocessed_email (02-data-layer.md §2.1).
CREATE INDEX idx_emails_processing_locked_until ON emails (processing_status, locked_until);
CREATE INDEX idx_emails_provider_message_id ON emails (provider_message_id);
CREATE INDEX idx_emails_user ON emails (user_id);
CREATE INDEX idx_emails_user_date ON emails (user_id, date_sent DESC);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    resolved_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT event_change_proposals_change_set_check CHECK (json_valid(change_set) AND json_type(change_set) = 'object' AND change_set <> '{}'),
    CONSTRAINT event_change_proposals_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_change_proposals_event_snapshot_before_check CHECK (json_valid(event_snapshot_before) AND json_type(event_snapshot_before) = 'object' AND event_snapshot_before <> '{}'),
    CONSTRAINT event_change_proposals_kind_check CHECK ((kind IN ('material_update', 'cancellation'))),
    CONSTRAINT event_change_proposals_pkey PRIMARY KEY (id),
    CONSTRAINT event_change_proposals_source_id_fkey FOREIGN KEY (source_id) REFERENCES event_sources(id),
    CONSTRAINT event_change_proposals_source_id_key UNIQUE (source_id),
    CONSTRAINT event_change_proposals_source_owner_check CHECK ((user_id IS NOT NULL)),
    CONSTRAINT event_change_proposals_status_check CHECK ((status IN ('pending', 'applied', 'rejected', 'superseded', 'closed_legacy'))),
    CONSTRAINT event_change_proposals_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX event_change_proposals_event_created_idx ON event_change_proposals (event_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX event_change_proposals_one_pending_per_event ON event_change_proposals (event_id) WHERE (status = 'pending');

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    calendar_entry_id TEXT,
    CONSTRAINT event_identity_hints_calendar_entry_id_fkey FOREIGN KEY (calendar_entry_id) REFERENCES calendar_entries(id) ON DELETE CASCADE,
    CONSTRAINT event_identity_hints_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_identity_hints_event_id_kind_value_hash_recurrence_id_key UNIQUE (event_id, kind, value_hash, recurrence_id),
    CONSTRAINT event_identity_hints_kind_check CHECK ((kind IN ('ical_uid', 'provider_thread', 'join_url', 'management_url'))),
    CONSTRAINT event_identity_hints_one_entity CHECK (((event_id IS NOT NULL) + (calendar_entry_id IS NOT NULL)) = 1),
    CONSTRAINT event_identity_hints_pkey PRIMARY KEY (id),
    CONSTRAINT event_identity_hints_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES emails(id) ON DELETE SET NULL,
    CONSTRAINT event_identity_hints_strength_check CHECK ((strength IN ('authoritative', 'supporting'))),
    CONSTRAINT event_identity_hints_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE UNIQUE INDEX event_identity_hints_calendar_entry_key ON event_identity_hints (calendar_entry_id, kind, value_hash, recurrence_id);
CREATE INDEX event_identity_hints_lookup_idx ON event_identity_hints (user_id, kind, value_hash, recurrence_id);

CREATE TABLE event_repair_audit (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_id TEXT,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    pre_change TEXT NOT NULL DEFAULT '[]' CHECK (pre_change IS NULL OR json_valid(pre_change)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT event_repair_audit_action_check CHECK ((action IN ('merge_duplicate_group', 'merge_source', 'cancel_event', 'resolve_proposal'))),
    CONSTRAINT event_repair_audit_pkey PRIMARY KEY (id),
    CONSTRAINT event_repair_audit_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX event_repair_audit_event_created_idx ON event_repair_audit (event_id, created_at DESC);
CREATE INDEX event_repair_audit_user_created_idx ON event_repair_audit (user_id, created_at DESC);

CREATE TABLE event_sources (
    id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    email_id TEXT,
    source_type TEXT NOT NULL DEFAULT 'new_invitation',
    extracted_data TEXT NOT NULL CHECK (extracted_data IS NULL OR json_valid(extracted_data)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    source_origin TEXT NOT NULL DEFAULT 'email',
    google_calendar_source_event_id TEXT,
    CONSTRAINT event_sources_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    CONSTRAINT event_sources_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT event_sources_origin_check CHECK ((((source_origin = 'email') AND (email_id IS NOT NULL)) OR ((source_origin = 'google_calendar') AND (google_calendar_source_event_id IS NOT NULL)))),
    CONSTRAINT event_sources_pkey PRIMARY KEY (id),
    CONSTRAINT event_sources_source_origin_check CHECK ((source_origin IN ('email', 'google_calendar'))),
    CONSTRAINT event_sources_source_type_check CHECK ((source_type IN ('new_invitation', 'update', 'cancellation', 'reminder', 'unknown')))
) STRICT;
CREATE UNIQUE INDEX event_sources_event_email_unique ON event_sources (event_id, email_id) WHERE (source_origin = 'email');
CREATE UNIQUE INDEX event_sources_event_gcal_unique ON event_sources (event_id, google_calendar_source_event_id) WHERE (source_origin = 'google_calendar');
CREATE INDEX idx_event_sources_email ON event_sources (email_id);
CREATE INDEX idx_event_sources_event ON event_sources (event_id);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE global_limits (
    id TEXT NOT NULL,
    limit_type TEXT NOT NULL,
    default_limit INTEGER NOT NULL,
    max_allowed INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT global_limits_limit_type_key UNIQUE (limit_type),
    CONSTRAINT global_limits_pkey PRIMARY KEY (id)
) STRICT;

CREATE TABLE graph_api_failures (
    id TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE integration_recoveries (
    id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('gmail', 'google_calendar', 'outlook')),
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
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE integrations (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('gmail', 'google_calendar', 'outlook')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'revoked', 'error')),
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry TEXT,
    provider_email TEXT,
    scopes TEXT NOT NULL DEFAULT '[]' CHECK (scopes IS NULL OR json_valid(scopes)),
    sync_cursor TEXT,
    last_sync_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT integrations_pkey PRIMARY KEY (id),
    CONSTRAINT integrations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT integrations_user_id_provider_key UNIQUE (user_id, provider)
) STRICT;
CREATE INDEX idx_integrations_user_status ON integrations (user_id, status);

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
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    completed_at TEXT,
    latency_ms INTEGER,
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0,1)),
    error_message TEXT,
    error_type TEXT,
    estimated_cost_usd REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    provider TEXT,
    CONSTRAINT llm_call_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL,
    CONSTRAINT llm_call_log_pkey PRIMARY KEY (id),
    CONSTRAINT llm_call_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_llm_call_log_email ON llm_call_log (email_id) WHERE (email_id IS NOT NULL);
CREATE INDEX idx_llm_call_log_operation ON llm_call_log (operation_type);
CREATE INDEX idx_llm_call_log_success ON llm_call_log (success) WHERE (success = false);
CREATE INDEX idx_llm_call_log_user_date ON llm_call_log (user_id, started_at DESC);

CREATE TABLE oauth_states (
    state TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    expires_at TEXT NOT NULL,
    code_verifier TEXT,
    CONSTRAINT oauth_states_pkey PRIMARY KEY (state),
    CONSTRAINT oauth_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX oauth_states_expires_at_idx ON oauth_states (expires_at);

CREATE TABLE operational_incidents (
    id TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    integration_id TEXT,
    user_id TEXT,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE sender_rules (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    sender_domain TEXT,
    sender_email TEXT,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
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

CREATE TABLE usage_quotas (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL DEFAULT (date('now')),
    llm_calls_count INTEGER NOT NULL DEFAULT 0,
    llm_calls_limit INTEGER NOT NULL DEFAULT 100,
    email_syncs_count INTEGER NOT NULL DEFAULT 0,
    email_syncs_limit INTEGER NOT NULL DEFAULT 50,
    calendar_syncs_count INTEGER NOT NULL DEFAULT 0,
    calendar_syncs_limit INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT usage_quotas_pkey PRIMARY KEY (id),
    CONSTRAINT usage_quotas_user_id_date_key UNIQUE (user_id, date),
    CONSTRAINT usage_quotas_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;
CREATE INDEX idx_usage_quotas_user_date ON usage_quotas (user_id, date);

CREATE TABLE user_calendar_settings (
    user_id TEXT NOT NULL,
    target_calendar_id TEXT,
    default_invitees TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    all_day_display_mode TEXT NOT NULL DEFAULT 'all_day',
    all_day_custom_start TEXT,
    all_day_custom_end TEXT,
    CONSTRAINT user_calendar_settings_all_day_custom_times_check CHECK ((((all_day_display_mode = 'custom') AND (all_day_custom_start IS NOT NULL) AND (all_day_custom_end IS NOT NULL) AND (all_day_custom_end > all_day_custom_start)) OR (all_day_display_mode <> 'custom'))),
    CONSTRAINT user_calendar_settings_all_day_display_mode_check CHECK ((all_day_display_mode IN ('all_day', 'day_9_to_5', 'morning_8_to_9', 'custom'))),
    CONSTRAINT user_calendar_settings_pkey PRIMARY KEY (user_id),
    CONSTRAINT user_calendar_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) STRICT;

CREATE TABLE users (
    id TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CONSTRAINT users_id_fkey FOREIGN KEY (id) REFERENCES accounts(id) ON DELETE CASCADE,
    CONSTRAINT users_pkey PRIMARY KEY (id)
) STRICT;

-- ===========================================================================
-- Triggers: one per Postgres trigger (docs/specs/sqlite-single-process/
-- 02-data-layer.md §2.13-2.15). They call functions that only the data
-- layer's writer connection registers:
--   selko_now()                     the transaction's timestamp (Postgres now())
--   selko_ts(offset_seconds)        that timestamp plus an offset
--   selko_emit_live(user, resource, operation)   a live hint, sent after commit
--   selko_emit_work(work_type)      a worker wake-up, sent after commit
--   selko_touch_event(event_id)     an event whose proposal invariant is checked before commit
-- A write from any other connection fails with "no such function": nothing
-- can change these tables behind the data layer's back.
-- ===========================================================================

-- updated_at: Postgres's BEFORE UPDATE trigger always set now(); so does this.
CREATE TRIGGER set_events_updated_at AFTER UPDATE ON events FOR EACH ROW
BEGIN UPDATE events SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_global_limits_updated_at AFTER UPDATE ON global_limits FOR EACH ROW
BEGIN UPDATE global_limits SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_integrations_updated_at AFTER UPDATE ON integrations FOR EACH ROW
BEGIN UPDATE integrations SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_sender_rules_updated_at AFTER UPDATE ON sender_rules FOR EACH ROW
BEGIN UPDATE sender_rules SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_usage_quotas_updated_at AFTER UPDATE ON usage_quotas FOR EACH ROW
BEGIN UPDATE usage_quotas SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_user_calendar_settings_updated_at AFTER UPDATE ON user_calendar_settings FOR EACH ROW
BEGIN UPDATE user_calendar_settings SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;
CREATE TRIGGER set_users_updated_at AFTER UPDATE ON users FOR EACH ROW
BEGIN UPDATE users SET updated_at = selko_now() WHERE rowid = NEW.rowid; END;

-- Gmail labels -> the boolean label columns (Postgres: BEFORE INSERT OR UPDATE OF provider_labels).
CREATE TRIGGER parse_provider_labels_insert AFTER INSERT ON emails FOR EACH ROW
BEGIN
    UPDATE emails SET
        is_spam       = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'SPAM'),
        is_trash      = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'TRASH'),
        is_promotions = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_PROMOTIONS'),
        is_social     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_SOCIAL'),
        is_updates    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_UPDATES'),
        is_forums     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_FORUMS'),
        is_primary    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_PERSONAL'),
        is_important  = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'IMPORTANT'),
        is_starred    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'STARRED'),
        is_unread     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'UNREAD')
    WHERE rowid = NEW.rowid;
END;
CREATE TRIGGER parse_provider_labels_update AFTER UPDATE OF provider_labels ON emails FOR EACH ROW
BEGIN
    UPDATE emails SET
        is_spam       = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'SPAM'),
        is_trash      = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'TRASH'),
        is_promotions = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_PROMOTIONS'),
        is_social     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_SOCIAL'),
        is_updates    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_UPDATES'),
        is_forums     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_FORUMS'),
        is_primary    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'CATEGORY_PERSONAL'),
        is_important  = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'IMPORTANT'),
        is_starred    = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'STARRED'),
        is_unread     = EXISTS (SELECT 1 FROM json_each(NEW.provider_labels) WHERE value = 'UNREAD')
    WHERE rowid = NEW.rowid;
END;

-- A calendar work item belongs to its event's owner.
CREATE TRIGGER calendar_work_items_owner_check_insert BEFORE INSERT ON calendar_work_items FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM events WHERE id = NEW.event_id AND user_id = NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'calendar work item owner does not match event owner'); END;
CREATE TRIGGER calendar_work_items_owner_check_update BEFORE UPDATE ON calendar_work_items FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM events WHERE id = NEW.event_id AND user_id = NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'calendar work item owner does not match event owner'); END;

-- An active Gmail/Outlook integration has a sync state; reconnecting resumes promptly.
CREATE TRIGGER integrations_ensure_email_sync_state_insert AFTER INSERT ON integrations FOR EACH ROW
WHEN NEW.provider IN ('gmail', 'outlook') AND NEW.status = 'active'
BEGIN
    INSERT INTO email_sync_state (integration_id, user_id, provider, initial_watermark_at, next_poll_at, created_at, updated_at)
    VALUES (NEW.id, NEW.user_id, NEW.provider, selko_ts(-14 * 86400), selko_now(), selko_now(), selko_now())
    ON CONFLICT (integration_id) DO UPDATE SET
        next_poll_at = CASE
            WHEN email_sync_state.lease_expires_at IS NULL OR email_sync_state.lease_expires_at <= selko_now()
            THEN selko_now() ELSE email_sync_state.next_poll_at END,
        consecutive_failures = 0,
        last_error_code = NULL,
        updated_at = selko_now();
END;
CREATE TRIGGER integrations_ensure_email_sync_state_update AFTER UPDATE OF status, provider ON integrations FOR EACH ROW
WHEN NEW.provider IN ('gmail', 'outlook') AND NEW.status = 'active'
BEGIN
    INSERT INTO email_sync_state (integration_id, user_id, provider, initial_watermark_at, next_poll_at, created_at, updated_at)
    VALUES (NEW.id, NEW.user_id, NEW.provider, selko_ts(-14 * 86400), selko_now(), selko_now(), selko_now())
    ON CONFLICT (integration_id) DO UPDATE SET
        next_poll_at = CASE
            WHEN email_sync_state.lease_expires_at IS NULL OR email_sync_state.lease_expires_at <= selko_now()
            THEN selko_now() ELSE email_sync_state.next_poll_at END,
        consecutive_failures = 0,
        last_error_code = NULL,
        updated_at = selko_now();
END;

-- Worker wake-ups (Postgres: pg_notify('selko_work', ...), delivered on commit).
CREATE TRIGGER emails_notify_pending_insert AFTER INSERT ON emails FOR EACH ROW
WHEN NEW.processing_status = 'pending' BEGIN SELECT selko_emit_work('email_pending'); END;
CREATE TRIGGER emails_notify_pending_update AFTER UPDATE OF processing_status ON emails FOR EACH ROW
WHEN NEW.processing_status = 'pending' BEGIN SELECT selko_emit_work('email_pending'); END;
CREATE TRIGGER items_notify_pending_insert AFTER INSERT ON email_ingestion_items FOR EACH ROW
WHEN NEW.acquisition_status = 'pending' BEGIN SELECT selko_emit_work('item_pending'); END;
CREATE TRIGGER items_notify_pending_update AFTER UPDATE OF acquisition_status ON email_ingestion_items FOR EACH ROW
WHEN NEW.acquisition_status = 'pending' BEGIN SELECT selko_emit_work('item_pending'); END;
CREATE TRIGGER attachments_notify_pending_insert AFTER INSERT ON attachments FOR EACH ROW
WHEN NEW.ingestion_status = 'pending' BEGIN SELECT selko_emit_work('attachment_pending'); END;
CREATE TRIGGER attachments_notify_pending_update AFTER UPDATE OF ingestion_status ON attachments FOR EACH ROW
WHEN NEW.ingestion_status = 'pending' BEGIN SELECT selko_emit_work('attachment_pending'); END;

-- Live hints for the web app (Postgres: realtime.send, one per user and resource per transaction).
CREATE TRIGGER trg_events_broadcast_ins AFTER INSERT ON events FOR EACH ROW
BEGIN SELECT selko_emit_live(NEW.user_id, 'events', 'INSERT'); END;
CREATE TRIGGER trg_events_broadcast_del AFTER DELETE ON events FOR EACH ROW
BEGIN SELECT selko_emit_live(OLD.user_id, 'events', 'DELETE'); END;
CREATE TRIGGER trg_events_broadcast_upd AFTER UPDATE OF review_status, title, start_datetime, end_datetime ON events FOR EACH ROW
WHEN NEW.review_status IS NOT OLD.review_status OR NEW.title IS NOT OLD.title
  OR NEW.start_datetime IS NOT OLD.start_datetime OR NEW.end_datetime IS NOT OLD.end_datetime
BEGIN SELECT selko_emit_live(NEW.user_id, 'events', 'UPDATE'); END;
CREATE TRIGGER trg_emails_broadcast_upd AFTER UPDATE OF processing_status, processing_error ON emails FOR EACH ROW
WHEN NEW.processing_status IS NOT OLD.processing_status OR NEW.processing_error IS NOT OLD.processing_error
BEGIN SELECT selko_emit_live(NEW.user_id, 'emails', 'UPDATE'); END;
CREATE TRIGGER trg_event_sources_broadcast_ins AFTER INSERT ON event_sources FOR EACH ROW
BEGIN SELECT selko_emit_live((SELECT user_id FROM events WHERE id = NEW.event_id), 'event_sources', 'INSERT'); END;
CREATE TRIGGER trg_event_sources_broadcast_upd AFTER UPDATE OF source_origin ON event_sources FOR EACH ROW
BEGIN SELECT selko_emit_live((SELECT user_id FROM events WHERE id = NEW.event_id), 'event_sources', 'UPDATE'); END;
CREATE TRIGGER trg_integrations_broadcast_upd AFTER UPDATE OF status ON integrations FOR EACH ROW
WHEN NEW.status IS NOT OLD.status
BEGIN SELECT selko_emit_live(NEW.user_id, 'integrations', 'UPDATE'); END;
CREATE TRIGGER trg_calendar_work_items_broadcast_ins AFTER INSERT ON calendar_work_items FOR EACH ROW
BEGIN SELECT selko_emit_live(NEW.user_id, 'calendar_work_items', 'INSERT'); END;
CREATE TRIGGER trg_calendar_work_items_broadcast_upd AFTER UPDATE ON calendar_work_items FOR EACH ROW
BEGIN SELECT selko_emit_live(NEW.user_id, 'calendar_work_items', 'UPDATE'); END;
CREATE TRIGGER trg_calendar_work_items_broadcast_del AFTER DELETE ON calendar_work_items FOR EACH ROW
BEGIN SELECT selko_emit_live(OLD.user_id, 'calendar_work_items', 'DELETE'); END;
CREATE TRIGGER trg_event_change_proposals_broadcast_ins AFTER INSERT ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_emit_live(NEW.user_id, 'event_change_proposals', 'INSERT'); END;
CREATE TRIGGER trg_event_change_proposals_broadcast_upd AFTER UPDATE ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_emit_live(NEW.user_id, 'event_change_proposals', 'UPDATE'); END;
CREATE TRIGGER trg_event_change_proposals_broadcast_del AFTER DELETE ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_emit_live(OLD.user_id, 'event_change_proposals', 'DELETE'); END;

-- Proposal invariant (Postgres: deferred constraint triggers): record the
-- touched events; the transaction checks them just before COMMIT.
CREATE TRIGGER events_change_proposal_invariant_ins AFTER INSERT ON events FOR EACH ROW
BEGIN SELECT selko_touch_event(NEW.id); END;
CREATE TRIGGER events_change_proposal_invariant_upd AFTER UPDATE ON events FOR EACH ROW
BEGIN SELECT selko_touch_event(NEW.id); END;
CREATE TRIGGER event_change_proposals_invariant_ins AFTER INSERT ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_touch_event(NEW.event_id); END;
CREATE TRIGGER event_change_proposals_invariant_upd AFTER UPDATE ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_touch_event(NEW.event_id); SELECT selko_touch_event(OLD.event_id); END;
CREATE TRIGGER event_change_proposals_invariant_del AFTER DELETE ON event_change_proposals FOR EACH ROW
BEGIN SELECT selko_touch_event(OLD.event_id); END;

-- Quota limits (Postgres migration 20260127000003 seeded these). Without them
-- every quota check fails, and the quota service fails open: no enforcement.
-- On an imported database the rows arrive with the data instead.
INSERT INTO global_limits (id, limit_type, default_limit, max_allowed, is_active, created_at, updated_at) VALUES
    ('00000000-0000-4000-8000-000000000001', 'llm_calls_daily', 100, 1000, 1, strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z', strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    ('00000000-0000-4000-8000-000000000002', 'email_syncs_daily', 50, 500, 1, strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z', strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    ('00000000-0000-4000-8000-000000000003', 'calendar_syncs_daily', 100, 1000, 1, strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z', strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
ON CONFLICT (limit_type) DO NOTHING;
