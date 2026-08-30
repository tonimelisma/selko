-- I2 of docs/specs/event-identity-reach.md: mirror the user's calendar.
--
-- Selko could only see a calendar entry when an email happened to match it
-- inside a one-local-day window capped at 50 results. Nothing was retained
-- between calls, so "does the user already have this?" had no index to consult
-- and fell through to an LLM text comparison -- which is why invites the user
-- had already accepted kept reappearing in the review queue as New.
--
-- These tables are a projection, never a source of truth. The user's decisions
-- stay in events.review_status and event_change_proposals; delivery stays with
-- calendar_work_items. Nothing here writes to the provider.

CREATE TABLE public.calendar_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    calendar_id text NOT NULL,
    provider_event_id text NOT NULL,

    -- Identity. ical_uid is the same UID the invite carried, which is what
    -- makes "the user already has this" a lookup instead of a guess.
    ical_uid text,
    recurring_event_id text,
    original_start text NOT NULL DEFAULT '',

    -- Shape, for the matcher and the review UI. Stored in the clear, exactly as
    -- events.title and emails.subject already are; RLS scopes both to the owner.
    title text,
    location text,
    start_at timestamptz,
    end_at timestamptz,
    all_day boolean NOT NULL DEFAULT false,
    timezone text,

    -- Provider state, for drift detection.
    status text NOT NULL DEFAULT 'confirmed',
    self_response text,
    etag text,
    sequence integer,
    provider_updated_at timestamptz,

    -- 'selko_created' entries carry our private extendedProperty; everything
    -- else the user made or accepted elsewhere.
    origin text NOT NULL DEFAULT 'external' CHECK (origin IN ('selko_created', 'external')),

    -- Tombstone rather than delete: a vanished entry is itself the signal that
    -- the user removed something, and undo still needs the history.
    deleted_at timestamptz,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT calendar_entries_provider_key UNIQUE (integration_id, calendar_id, provider_event_id)
);

ALTER TABLE public.calendar_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own calendar entries"
    ON public.calendar_entries FOR SELECT
    USING (auth.uid() = user_id);

CREATE INDEX calendar_entries_user_start_idx
    ON public.calendar_entries (user_id, start_at)
    WHERE deleted_at IS NULL;
-- The lookup identity matching performs: "is this UID already on the calendar?"
CREATE INDEX calendar_entries_uid_idx
    ON public.calendar_entries (user_id, ical_uid, original_start)
    WHERE ical_uid IS NOT NULL AND deleted_at IS NULL;

COMMENT ON TABLE public.calendar_entries IS
    'I2: read-only projection of the user''s calendar. Never a source of truth; decisions live in events.review_status and delivery in calendar_work_items.';

-- One row per calendar being mirrored. The lease/generation columns copy the
-- shape email_sync_state already proves, so a crashed sync recovers on the next
-- claim rather than on a restart.
CREATE TABLE public.calendar_mirror_state (
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    calendar_id text NOT NULL,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Incremental cursor. A steady state transfers only what changed, which is
    -- what keeps this inside the egress rule: work arrives by change, and the
    -- poll below is a floor rather than a schedule.
    sync_token text,
    last_full_resync_at timestamptz,

    -- The rolling window actually mirrored. All history is unbounded and
    -- pointless: matching only asks about events near an extracted date.
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,

    next_poll_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    lease_generation bigint NOT NULL DEFAULT 0,
    last_started_at timestamptz,
    last_success_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (integration_id, calendar_id)
);

ALTER TABLE public.calendar_mirror_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.calendar_mirror_state FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.calendar_mirror_state TO service_role;

-- No partial predicate here: now() is not IMMUTABLE and Postgres rejects it in
-- an index predicate. Both columns are indexed so the claim query can filter on
-- lease expiry at scan time instead.
CREATE INDEX calendar_mirror_state_due_idx
    ON public.calendar_mirror_state (next_poll_at, lease_expires_at);

COMMENT ON TABLE public.calendar_mirror_state IS
    'I2: per-calendar sync cursor and lease. sync_token drives incremental reads; a 410 GONE clears it and forces one full resync.';
