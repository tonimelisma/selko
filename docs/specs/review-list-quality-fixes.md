# Review List Quality Fixes

**Status:** Implemented
**Date:** 2026-07-13
**Scope:** backend (`backend/selko/services`, `backend/selko/workers`), Supabase migrations, web frontend, one production cleanup script.

This spec fixes the cluster of review-list problems found in the 2026-07-12/13
production investigation: self-sent emails producing events, calendar invites
surfacing as suggestions, broken dedup for evening events, duplicate suggestion
rows, zero-length events, cosmetic "title updated" changesets, wholesale
description replacement, missing dates on all-day cards, and sender-ignore not
clearing the whole review pile.

---

## Product decisions (locked in — do not re-litigate during implementation)

1. **Ignoring a sender is retroactive and atomic.** Creating an `ignore` rule
   must simultaneously reject that sender's events in the New lane AND discard
   their proposals in the Changes lane, server-side, in one call. Not a
   client-side loop over one lane.
2. **Calendar invitation emails never become Selko suggestions.** If a mailbox
   Selko reads receives a calendar invite (Google/Outlook meeting request,
   update, RSVP, or cancellation), the email client and its calendar already
   handle it. Selko skips it entirely. There is no "mirror work invites"
   feature. Plain "add to calendar" `.ics` files (RFC 5545 `METHOD:PUBLISH` or
   no METHOD) are NOT invites and stay supported.
3. **Suppress junk at the source.** Nearly-identical changesets must not be
   generated in the first place — fix the prompt/schema of the single
   generating LLM call plus deterministic code gates. Do NOT add new LLM
   verification passes that try to catch bad output afterwards.

---

## Background evidence (production, 2026-07-13)

Read-only queries against production Supabase found, for the primary user's
Outlook-connected account:

- **26 events** pending (`pending_review` = 20, `pending_change` = 6).
- **84 Outlook emails ingested from Sent Items and Deleted Items.** Their
  `provider_folder_ids` point to two folder IDs (base64 suffixes `AgEJAAAA`,
  `AgEKAAAA`) that no longer exist in `email_folders`. They were ingested in a
  single batch at 2026-07-13 01:14–01:15 UTC — the PR #183 initial scan, which
  ran before the #184/#185 well-known-folder hardening. Current code correctly
  excludes those folders; the leftover emails/events were never cleaned up.
  ~11 of the 26 pending items exist only because of this incident (all events
  attributed to the user's own sent mail, plus a colleague's meeting invite
  that was sitting in Deleted Items).
- **The whole mailbox was re-ingested when message IDs switched format**
  (legacy mutable `AQMk…` rows from Jul 12, immutable `AAk…` rows from Jul 13).
  Same messages, different `provider_message_id` → reprocessed → duplicate
  events (e.g. two identical application-deadline rows extracted twice from
  one newsletter).
- **Dedup is blind to evening events.** `find_matching_event` takes the
  event's *local* date but queries a *UTC* day window. `llm_call_log` shows the
  second deadline-event processing compared against unrelated events on the
  previous UTC date — the existing duplicate at `2026-07-28T03:00:00Z`
  (= Jul 27 8pm PDT) was never a candidate.
- **Out-of-order processing + literal title diffs.** An interview reminder
  email (sent Jul 12) created the event; the *older* original invite (sent
  Jul 9) was processed later and proposed retitling it to nearly the same
  string.
- **Enrichment replaces instead of appending.** An email inviting the user to
  run an advocacy table at a community bike fest proposed replacing the
  existing fest event's title and description wholesale instead of appending a
  note about the table.

---

## WS1 — Retroactive sender ignore (Supabase RPC + web)

### Problem

`handleIgnoreSender` in `frontend/src/routes/app/+page.svelte` (~line 241)
inserts a `sender_rules` row, then loops over **only the events of the group
card the button was clicked on** (one lane). If the same sender has events in
the other lane, they stay. The loop is also non-atomic and client-only.

### Fix

**New migration** `supabase/migrations/<timestamp>_ignore_sender_retroactive.sql`:

```sql
CREATE OR REPLACE FUNCTION public.ignore_sender_and_reject_pending(
    p_sender_email text DEFAULT NULL,
    p_sender_domain text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_user_id uuid := auth.uid();
    v_rejected_new integer := 0;
    v_discarded_changes integer := 0;
    v_event record;
    v_source record;
    v_snapshot jsonb;
    v_has_invitation boolean;
    v_restore_status text;
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'not authenticated';
    END IF;
    IF p_sender_email IS NULL AND p_sender_domain IS NULL THEN
        RAISE EXCEPTION 'sender_email or sender_domain required';
    END IF;

    -- 1. Upsert the ignore rule (unique per (user_id, sender_email) /
    --    (user_id, sender_domain) partial indexes already exist).
    IF p_sender_email IS NOT NULL THEN
        INSERT INTO public.sender_rules (user_id, sender_email, action)
        VALUES (v_user_id, p_sender_email, 'ignore')
        ON CONFLICT (user_id, sender_email) WHERE sender_email IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    ELSE
        INSERT INTO public.sender_rules (user_id, sender_domain, action)
        VALUES (v_user_id, p_sender_domain, 'ignore')
        ON CONFLICT (user_id, sender_domain) WHERE sender_domain IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    END IF;

    -- 2. New lane: reject pending_review events that have a non-undone email
    --    source from this sender.
    WITH matching AS (
        SELECT DISTINCT es.event_id
        FROM public.event_sources es
        JOIN public.emails em ON em.id = es.email_id
        WHERE es.is_undone = false
          AND em.user_id = v_user_id
          AND (
                (p_sender_email IS NOT NULL AND em.from_email = p_sender_email)
             OR (p_sender_domain IS NOT NULL
                 AND em.from_email LIKE '%@' || p_sender_domain)
          )
    )
    UPDATE public.events ev
    SET status = 'rejected', updated_at = now()
    FROM matching m
    WHERE ev.id = m.event_id
      AND ev.user_id = v_user_id
      AND ev.status = 'pending_review';
    GET DIAGNOSTICS v_rejected_new = ROW_COUNT;

    -- 3. Changes lane: for each pending_change event whose ACTIVE proposal
    --    (latest non-undone update/cancellation source) came from this sender,
    --    discard the proposal. Mirrors selko.services.events.reject_pending_change.
    FOR v_event IN
        SELECT ev.*
        FROM public.events ev
        WHERE ev.user_id = v_user_id AND ev.status = 'pending_change'
    LOOP
        SELECT es.* INTO v_source
        FROM public.event_sources es
        LEFT JOIN public.emails em ON em.id = es.email_id
        WHERE es.event_id = v_event.id
          AND es.source_type IN ('update', 'cancellation')
          AND es.is_undone = false
        ORDER BY es.created_at DESC
        LIMIT 1;

        IF v_source.id IS NULL THEN CONTINUE; END IF;

        -- Active proposal must be from the ignored sender. The proposal may be
        -- represented by a google_calendar sibling row; check the email sibling.
        IF NOT EXISTS (
            SELECT 1 FROM public.event_sources es2
            JOIN public.emails em2 ON em2.id = es2.email_id
            WHERE es2.event_id = v_event.id
              AND es2.is_undone = false
              AND es2.source_type IN ('update', 'cancellation')
              AND (
                    (p_sender_email IS NOT NULL AND em2.from_email = p_sender_email)
                 OR (p_sender_domain IS NOT NULL
                     AND em2.from_email LIKE '%@' || p_sender_domain)
              )
        ) THEN
            CONTINUE;
        END IF;

        -- Mark ALL active update/cancellation sources undone (email + gcal sibling).
        UPDATE public.event_sources
        SET is_undone = true
        WHERE event_id = v_event.id
          AND source_type IN ('update', 'cancellation')
          AND is_undone = false;

        SELECT EXISTS (
            SELECT 1 FROM public.event_sources
            WHERE event_id = v_event.id AND source_type = 'new_invitation'
        ) INTO v_has_invitation;

        -- GCal-adopt row that only exists to carry this proposal: delete it.
        IF v_event.google_calendar_event_id IS NOT NULL
           AND v_event.synced_at IS NULL
           AND NOT v_has_invitation THEN
            DELETE FROM public.events WHERE id = v_event.id;
            v_discarded_changes := v_discarded_changes + 1;
            CONTINUE;
        END IF;

        -- Restore snapshot fields + status.
        v_snapshot := v_source.event_snapshot_before;
        v_restore_status := CASE
            WHEN v_snapshot ? 'status' AND (v_snapshot->>'status') IN
                 ('pending_review','approved','synced','sync_failed','rejected','cancelled')
                THEN v_snapshot->>'status'
            WHEN v_event.google_calendar_event_id IS NOT NULL THEN 'synced'
            ELSE 'approved'
        END;

        UPDATE public.events SET
            status = v_restore_status,
            title = COALESCE(v_snapshot->>'title', title),
            start_datetime = COALESCE((v_snapshot->>'start_datetime')::timestamptz, start_datetime),
            end_datetime = CASE WHEN v_snapshot ? 'end_datetime'
                THEN (v_snapshot->>'end_datetime')::timestamptz ELSE end_datetime END,
            all_day = COALESCE((v_snapshot->>'all_day')::boolean, all_day),
            location = CASE WHEN v_snapshot ? 'location'
                THEN v_snapshot->>'location' ELSE location END,
            description = CASE WHEN v_snapshot ? 'description'
                THEN v_snapshot->>'description' ELSE description END,
            importance = COALESCE(v_snapshot->>'importance', importance),
            updated_at = now()
        WHERE id = v_event.id;
        v_discarded_changes := v_discarded_changes + 1;
    END LOOP;

    RETURN jsonb_build_object(
        'rejected_new', v_rejected_new,
        'discarded_changes', v_discarded_changes
    );
END;
$$;

GRANT EXECUTE ON FUNCTION public.ignore_sender_and_reject_pending(text, text)
    TO authenticated;
```

> Check the actual unique-index names/definitions in
> `20260126000004_create_sender_rules.sql` before writing the `ON CONFLICT`
> clauses — match the existing partial indexes exactly, or use
> `ON CONFLICT DO NOTHING` + a follow-up `UPDATE` if they aren't plain
> unique constraints.

**Web** (`frontend/src/lib/services/sender-rules.js`): add

```js
export async function ignoreSenderRetroactive(senderEmail) {
	try {
		const { data, error } = await supabase.rpc('ignore_sender_and_reject_pending', {
			p_sender_email: senderEmail
		});
		if (error) throw error;
		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
```

**Web** (`frontend/src/routes/app/+page.svelte`): rewrite `handleIgnoreSender`:

- Guard: if `senderEmail` does not contain `@` (pseudo senders
  `google_photos` / `google_calendar` / unknown from
  `frontend/src/lib/event-sender.js`), show an error and return — the ignore
  action only applies to email senders.
- Call `ignoreSenderRetroactive(senderEmail)`; on success call `loadEvents()`
  to refetch (this clears BOTH lanes), then show the existing
  `home.senderIgnored` notification. Delete the per-event rejection loop.
- Leave `handleAutoApproveSender` unchanged (out of scope).

### Not in scope

- Symmetric behavior on rule deletion already exists for emails
  (`sender_rule_before_delete` trigger reprocesses skipped emails); rejected
  events are intentionally NOT resurrected on un-ignore — reprocessing
  recreates suggestions from the emails.
- iOS/Android: they don't have the ignore-from-review action today; when they
  gain it they must call this RPC, never a client-side loop.

### Tests (DoD: backend unit + frontend unit + `npm run check` + web screenshots)

- Frontend: update `frontend/src/routes/app/__tests__/page.test.js` — mock
  `supabase.rpc`, assert: rpc called with sender email; events refetched;
  pseudo-sender guard does not call rpc.
- Backend: none of the Python services change; add a migration-presence test
  only if the repo has a pattern for it (it doesn't — skip).
- Manual (local Supabase): seed one sender with a `pending_review` event and a
  `pending_change` event; call the RPC as the user; verify both disappear, the
  changes-lane event's snapshot fields are restored, and the rule row exists.

---

## WS2 — One-off production cleanup script

### Problem

The #183 deploy-window scan left production data that keeps polluting the
review list: 84 emails from Sent Items/Deleted Items (plus their events), and
duplicate pending events from the mutable→immutable message-ID re-ingestion.

### Fix

New script `scripts/cleanup_review_incident_20260713.py`, modeled on the other
`cli/` tools (loads config via `ENVIRONMENT` env var, uses the service-role
Supabase client). **Dry-run by default; only writes with `--apply`.**

For every user with an Outlook integration:

1. **Orphan-folder emails.** Build the set of known
   `email_folders.provider_folder_id` for the user (`provider = 'outlook'`).
   An email is *orphaned* when `email_provider = 'outlook'`,
   `provider_folder_ids` is non-empty, and **every** entry is missing from the
   known set. (These are the Sent Items / Deleted Items ingests; the folder
   rows were deleted by the #184/#185 reconcile.)
2. **Reject their pending events.** For each orphaned email, walk its
   non-undone `event_sources`:
   - Event `status = 'pending_review'` and **all** of its non-undone email
     sources are orphaned emails → `status = 'rejected'`.
   - Event `status = 'pending_change'` and the active proposal's email source
     is an orphaned email → call
     `selko.services.events.reject_pending_change(client, event_id)` (reuse the
     Python logic; do not reimplement).
3. **Neutralize the emails.** Set `processing_status = 'skipped'` and
   `processing_explanation = 'Ingested from an excluded folder (Sent/Deleted Items) during the 2026-07-13 migration window'`
   on all orphaned emails so nothing reprocesses them.
4. **Duplicate pending events** (catches the duplicate-deadline pair, whose
   source emails are both Inbox rows): group the user's `pending_review`
   events by
   `(title, start_datetime)`; where a group has >1 row, keep the oldest
   `created_at` and set the rest to `rejected`.
5. Print a per-user summary table (counts per step) in both modes.

### Explicitly out of scope

- Deleting the stale mutable-ID (`AQMk…`) email rows. They're `processed`
  History noise, not review noise, and deleting them risks breaking
  `event_sources` references. Revisit only if History pagination suffers.
- Touching `integrations.sync_cursor` (legacy Inbox delta link) — the reliable
  path ignores it.

### Tests

Backend unit test for the pure decision helpers (extract "is orphaned" and
"group duplicates" into module-level functions and test them with plain
dicts). Run the script against local Supabase seed data before production.
Run with `ENVIRONMENT=production` only after review of the dry-run output.

---

## WS3 — Dedup correctness (stops NEW duplicates)

All in `backend/selko/services/events.py` unless noted.

### 3a. Local-day candidate window queried as UTC (the duplicate-deadline bug)

`find_matching_event` (~line 497): `start_date` is derived from a local-offset
ISO string (e.g. `2026-07-27T20:00:00-07:00` → `.date()` = Jul 27) but the
query window is `f"{start_date}T00:00:00Z"`–`T23:59:59Z` (UTC). Stored events
are UTC; any event between 5pm and midnight Pacific lives on the *next* UTC
date and is never a candidate — for the Selko-events query AND the Google
Calendar read-back, which both use these bounds.

Replace the window computation:

```python
from selko.services.civil_time import ensure_aware, resolve_zone

start_aware = ensure_aware(start_dt, user_timezone)
if start_aware is None:
    return None
local_day = start_aware.astimezone(resolve_zone(user_timezone)).replace(
    hour=0, minute=0, second=0, microsecond=0
)
time_min = local_day.astimezone(timezone.utc).isoformat()
time_max = (local_day + timedelta(days=1)).astimezone(timezone.utc).isoformat()
```

Use `.gte("start_datetime", time_min).lt("start_datetime", time_max)` (note
`lt`, not `lte`) and pass the same `time_min`/`time_max` to
`calendars.fetch_calendar_events_for_date_range`.

### 3b. Reuse the Selko row already linked to a matched GCal event (duplicate change-card bug)

When `compare_events` matches a Google Calendar candidate,
`save_extracted_events` unconditionally calls `create_pending_change_from_gcal`,
inserting a **new** Selko row per email even when a Selko row already tracks
that calendar event. In `find_matching_event`, after the LLM returns a
`gcal:`-prefixed match, first look for an existing linked row:

```python
existing = supabase_client.table("events").select("*").eq(
    "user_id", user_id
).eq("google_calendar_event_id", gcal_id).not_.in_(
    "status", ["rejected", "cancelled"]
).order("created_at").limit(1).execute()
if existing.data:
    row = existing.data[0]
    return EventMatch(match_id=row["id"], baseline={... same fields as the
        local-candidate baseline dict at the bottom of find_matching_event ...})
```

Only fall through to the GCal-baseline `EventMatch` when no linked row exists.
(`propose_local_change` already marks prior active proposals undone, so a
second email replaces the first proposal instead of stacking a second card.)

### 3c. Null-start events bypass everything

Events with `start_datetime = NULL` skip dedup (early `return None`), can't
sync, and render blank/“All Day” cards. In `save_extracted_events`, before the
past-event cutoff check: if `event_data.get("start_datetime")` is falsy, log
and `continue` (do not create the event). The extraction prompt already forbids
date-less events; this is the code gate for when the model disobeys.

### Tests (backend unit, `backend/tests/`)

- Window: with `user_timezone="America/Los_Angeles"` and an extracted start of
  `2026-07-27T20:00:00-07:00`, assert the events query bounds are
  `2026-07-27T07:00:00+00:00` / `2026-07-28T07:00:00+00:00` (MagicMock the
  Supabase chain and inspect call args).
- GCal reuse: mock an existing row with `google_calendar_event_id = X`; assert
  the returned `EventMatch.match_id` is the row's UUID, not `gcal:X`.
- Null start: assert no insert happens and the event is skipped.
- Regression note: this is a bug fix — tests are mandatory per DoD.

---

## WS4 — Update-proposal discipline (cosmetic titles / append-only enrichment / recency)

Per product decision 3, everything here is either a change to the **one
generating LLM call** (`propose_event_update` in
`backend/selko/services/event_processing.py`) or a **deterministic code gate**
(`backend/selko/services/event_diff.py`). No new LLM calls.

### 4a. Process emails oldest-first

Bulk scans ingest newest-first, so older emails "update" events created from
newer ones. New migration re-creating `claim_unprocessed_email` (copy the full
function body from `20260712000003_reliable_email_ingestion_and_history.sql`,
change only the ordering):

```sql
    ORDER BY date_sent ASC NULLS LAST, created_at ASC
```

### 4b. Give the propose call recency context and hard rules

`propose_event_update` gains two keyword args:
`email_date_sent: Optional[str]` and `baseline_info_date: Optional[str]`.

Caller (`save_extracted_events` in `services/events.py`): pass the processing
email's `date_sent` (fetch it once alongside the email metadata — it's already
in `fetch_email_with_attachments` metadata) and, for local matches, the newest
`emails.date_sent` across the matched event's non-undone sources (one extra
query: `event_sources` joined to `emails`, order by `emails.date_sent` desc,
limit 1). For GCal-baseline matches pass `None`.

Prompt additions (after the extracted-fields block):

```
**This email was sent:** {email_date_sent}
**The event's current information is from an email sent:** {baseline_info_date}
```

New rules appended to the numbered rule list:

```
10. If this email is OLDER than the event's current information, it must NOT
    change title, start/end, all_day, or location. At most kind=enrichment
    with a description addition. When it adds nothing new → kind=noop.
11. Do NOT propose a title change when both titles describe the same
    real-world event. Rewording, reordering, or adding a role/subtitle
    qualifier (e.g. "- Advocacy Table", "(Recruiter)") is NOT a title change.
    Only propose title when the organizer renamed or materially changed the
    event itself.
12. Description changes must use mode="append" with ONLY the new information
    as a short paragraph — never restate the existing description. Use
    mode="replace" only for organizer-issued corrections or cancellations.
```

Schema: in the `propose_schema` `changes.items.properties`, add
`"mode": {"type": "string", "enum": ["append", "replace"]}`.

### 4c. Append-mode description merging (code)

- `event_diff.FieldChange`: add `mode: Optional[Literal["append", "replace"]] = None`.
- New helper in `event_diff.py`:

```python
def resolve_description_append(
    change_set: EventChangeSet, baseline: dict[str, Any]
) -> EventChangeSet:
    """Materialize mode=append description changes into full after-values."""
    for change in change_set.changes:
        if change.field == "description" and change.mode == "append":
            base = (baseline.get("description") or "").strip()
            addition = (str(change.after or "")).strip()
            if addition and addition not in base:
                change.after = f"{base}\n\n{addition}" if base else addition
            else:
                change.after = base or change.after
            change.mode = None
    return change_set
```

- Call it in `save_extracted_events` immediately after
  `propose_event_update` returns (before `gate_change_set` has already run
  inside propose — so call it on the gated set, before
  `proposed_fields_from_change_set`). The persisted `change_set` then contains
  the final after-value, so ChangeCard's before/after display and
  `apply_pending_change` need no changes.
- In `propose_event_update`, plumb `mode=item.get("mode")` into the
  `FieldChange(...)` construction.

### 4d. Deterministic cosmetic-title gate (code, not LLM)

In `gate_change_set` (`event_diff.py`), drop `title` changes whose before/after
are token-similar:

```python
import re

def _title_tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(value or "").casefold()) if t}

def _titles_cosmetically_equal(before: Any, after: Any) -> bool:
    a, b = _title_tokens(before), _title_tokens(after)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5
```

In the gating loop: `if field == "title" and _titles_cosmetically_equal(before, after): continue`.

Calibration (intended outcomes; token sets are casefolded alphanumerics):
- "Interview with Acme - Screening Call with Jane Doe" →
  "Acme Screening Call with Jane Doe (Recruiter)": ∩=6, ∪=8 →
  Jaccard 0.75 → dropped ✓ (the real-world case behind this rule)
- "Community Bike Fest 2026" → "Community Bike Fest 2026 - Advocacy Table":
  ∩=4, ∪=6 → 0.67 → dropped ✓ (a participation role is not a rename —
  decision 3/7)
- "Camping: Pine Ridge — Site 046" → "Pine Ridge Camping Trip":
  ∩=3, ∪=6 → 0.50 → dropped at the ≥ 0.5 threshold ✓ (a vaguer proposal
  title must not replace a confirmed reservation title; rule 10 blocks the
  rest of that changeset anyway since the proposing email is older)
- "Spring Gala" → "Emergency Board Meeting": ∩=0 → 0.0 → kept ✓
  (genuine rename)

### Tests (backend unit)

- `gate_change_set` drops the recruiter-title pair from the calibration table;
  keeps a genuinely different title ("Spring Gala" → "Emergency Board
  Meeting").
- `resolve_description_append` appends to a non-empty baseline, replaces
  nothing, dedupes an already-present addition.
- `propose_event_update` prompt contains both date lines when provided
  (mock the gateway, inspect `contents`).
- Claim-order migration: no Python test; verify on local Supabase that two
  pending emails claim oldest-`date_sent`-first.
- Update the eval fixtures in `backend/tests/eval/` only if they assert on the
  propose prompt text (check `grep -r "proposing updates" backend/tests`).

---

## WS5 — All-day, dates, and duration correctness

### 5a. All-day cards show no date (web)

[`frontend/src/lib/components/EventCard.svelte`](../../frontend/src/lib/components/EventCard.svelte)
line 12 returns the bare "All Day" string. Replace `formattedDateTime` logic:

```js
if (event.all_day) {
	if (!event.start_datetime) return $_('events.allDay');
	const start = new Date(event.start_datetime);
	const opts = { weekday: 'short', month: 'short', day: 'numeric' };
	let label = start.toLocaleDateString(undefined, opts);
	if (event.end_datetime) {
		// end is stored as the last moment of the final day; subtract a minute
		// so an exclusive-style end doesn't spill into the next day
		const end = new Date(new Date(event.end_datetime).getTime() - 60000);
		if (end.toDateString() !== start.toDateString() && end > start) {
			label += ` – ${end.toLocaleDateString(undefined, opts)}`;
		}
	}
	return `${label}, ${$_('events.allDay')}`;
}
```

Extract this whole `formattedDateTime` body into a shared helper
`frontend/src/lib/format-event-datetime.js` and use it from `EventCard.svelte`
and the event detail page (`frontend/src/routes/app/events/[id]/+page.svelte`
— audit it for the same all-day early-return and replace). Add unit tests in
`frontend/src/lib/__tests__/`.

### 5b. ICS parser drops the all-day flag (backend)

[`backend/selko/services/ics_parser.py`](../../backend/selko/services/ics_parser.py)
`_vevent_to_calendar_event` computes `is_all_day` (line ~132) but never passes
it. Add `all_day=is_all_day` to the `CalendarEvent(...)` construction. Note:
for all-day VEVENTs, `DTEND` is an *exclusive* date per RFC 5545 — keep the
raw value (the sync-side fix in 5c handles exclusivity).

### 5c. All-day Google Calendar payload is wrong (backend)

[`backend/selko/services/calendars.py`](../../backend/selko/services/calendars.py)
lines ~249–259 (create) and ~543–555 (update):

- `end.date` is set to the **start** date → multi-day all-day events (Kids
  Club Closed, Aug 12–14) collapse to one day, and Google's all-day `end.date`
  must be the *exclusive* next day anyway.
- The date is derived by `start_dt.split("T")[0]` on the stored UTC timestamp
  → wrong day for timezones east of UTC.

Fix both call sites with a shared helper (put it in `civil_time.py`):

```python
def gcal_all_day_fields(
    start_value: Any, end_value: Any, user_timezone: Optional[str] = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Local start date + exclusive local end date for GCal all-day events."""
    start_civil = to_civil_iso(start_value, user_timezone)
    start_date = date.fromisoformat(start_civil[:10])
    if end_value:
        end_civil = to_civil_iso(end_value, user_timezone)
        end_date = date.fromisoformat(end_civil[:10])
        # stored ends are "last moment of final day" (e.g. 23:59:59); an end at
        # exactly midnight already points at the exclusive next day
        if end_civil[11:19] != "00:00:00":
            end_date += timedelta(days=1)
        end_date = max(end_date, start_date + timedelta(days=1))
    else:
        end_date = start_date + timedelta(days=1)
    return {"date": start_date.isoformat()}, {"date": end_date.isoformat()}
```

Worked examples (America/Los_Angeles): a 3-day closure stored
`2026-08-12T07:00:00Z` / `2026-08-15T06:59:59Z` → `start.date=2026-08-12`,
`end.date=2026-08-15` (renders Aug 12–14 ✓). Single-day with `end=None` →
start+1 ✓. Helsinki user, local midnight stored `…T21:00:00Z` previous UTC day
→ civil conversion returns the correct local date ✓.

### 5d. Zero-length timed events get a default duration (backend)

Deadlines extract as `end == start` (e.g. an application deadline at 8:00pm)
or with no end, and sync as
zero-length slivers (`calendars.py` line ~274 sets `end = start`). In
`normalize_event_data` (`services/events.py`), after computing the storage
ISOs: if not all-day and start is set and (end is missing or `end <= start`),
set `end = start + 1 hour` (parse with `datetime.fromisoformat`, add
`timedelta(hours=1)`, re-serialize with `.isoformat()`). This covers both
create and update-proposal paths because propose after-values run through
`to_storage_iso` in `save_extracted_events` — add the same guard there when
both datetime fields end up in `proposed_fields`.

### Tests

- Frontend: `format-event-datetime` unit tests — timed, all-day single-day,
  all-day multi-day, null start.
- Backend: ICS all-day VEVENT → `all_day=True`; `gcal_all_day_fields` cases
  above (including Helsinki); min-duration guard (no end / end==start /
  end>start untouched / all-day untouched).
- Screenshots: web only (`./scripts/capture-all-screenshots.sh web`) — the
  review list card layout changes.

---

## WS6 — Calendar-invite suppression (filter at ingestion)

### Problem

Invitation emails (Google Calendar "Invitation: …" / "Updated invitation: …"
mails, Outlook meeting requests) become review suggestions. Per product
decision 2 they must be skipped: the email client / its calendar already owns
them.

**Design: filter at ingestion.** Invites are detected in the fetch workers and
stored pre-skipped, so they never enter the pending queue, are never claimed
by the process worker, and never reach an LLM. A thin process-time guard
remains only as a backstop (see step 5) — it is not the primary mechanism.

> **Implementation status:** PR #190 shipped the backstop layer — the
> migration (`20260713000002_calendar_invite_suppression.sql`), the Outlook
> `@odata.type` flag in `parse_outlook_message`, `detect_invite_method` in
> `ics_parser.py`, the process-time skip in `process_email_for_events`, and
> the History outcome label. With #190, invites never reach an LLM, but they
> still enter the pending queue and are claimed before being skipped, and
> Gmail detection happens only at process time. **Remaining work:** steps 2
> and 3 below (Gmail parse-time detection; store pre-skipped in both fetch
> paths), plus aligning the shipped backstop to mark emails `skipped` rather
> than `processed` (step 5).

### Detection signals (structural only — no subject-line heuristics)

1. **Outlook:** Graph returns meeting mails as `eventMessage` subtypes. In
   `parse_outlook_message` (`backend/selko/services/outlook.py`), set a new
   field: `result["is_calendar_invite"] = "eventmessage" in str(msg.get("@odata.type", "")).lower()`.
   (`get_full_message` / the reliable path fetch full payloads, so
   `@odata.type` is present for meeting messages.)
2. **Gmail:** invites carry a `text/calendar` MIME part whose RFC 5545
   `METHOD` distinguishes real invite machinery (REQUEST/REPLY/CANCEL/…)
   from shareable calendar files (PUBLISH / no METHOD). Both signals are
   available at fetch time in the full message payload:
   - the part's `Content-Type` header usually includes a `method=REQUEST`
     parameter, and
   - the part body is usually inline (`body.data`, base64url) and contains a
     `METHOD:` line.

### Changes

1. **Migration** *(shipped in PR #190)*: add
   `is_calendar_invite boolean NOT NULL DEFAULT false` to `emails`; extend
   `emails_processing_outcome_check` to include `'calendar_invite'`.
2. **Gmail ingest detection** *(remaining)* — in `parse_gmail_message`
   (`backend/selko/services/emails.py`), walk the payload parts recursively
   (reuse the traversal pattern of `_extract_body_from_payload`). For a part
   with `mimeType == "text/calendar"`, resolve its METHOD:
   - from the part's `Content-Type` header value (`method=X` parameter,
     case-insensitive); else
   - if the part has inline `body.data`, base64url-decode it and match
     `^METHOD:(\S+)` (multiline, case-insensitive); else
   - leave undetermined (attachment-only body) — the backstop in step 5
     covers it.
   Set `result["is_calendar_invite"] = method in INVITE_METHODS` where

   ```python
   INVITE_METHODS = {"REQUEST", "REPLY", "CANCEL", "COUNTER", "DECLINECOUNTER"}
   ```

   (define the set once in `ics_parser.py` and import it).
3. **Store pre-skipped** *(remaining)* — when `parsed.get("is_calendar_invite")`
   is true (the Outlook parser already sets the flag as of PR #190; Gmail gets
   it from step 2), the parser also sets, in the same parsed dict:

   ```python
   parsed["processing_status"] = "skipped"
   parsed["processing_outcome"] = "calendar_invite"
   parsed["processing_explanation"] = (
       "Calendar invitation — already handled by your email client and calendar."
   )
   parsed["processed_at"] = datetime.now(timezone.utc).isoformat()
   ```

   Put this in a small shared helper (e.g. `mark_parsed_as_calendar_invite(parsed)`
   in `services/emails.py`) called from both the Gmail and Outlook parse
   paths. Because `save_emails` upserts the parsed dict as-is, these keys flow
   into the insert; `claim_unprocessed_email` only claims `'pending'` rows, so
   the email is never processed. **Do NOT add these keys for non-invite
   emails** — on upsert-conflict re-saves (folder moves), absent columns keep
   their existing values, and including `processing_status` unconditionally
   would clobber already-processed rows.
4. **`ics_parser.py` backstop helper** *(shipped in PR #190)* for stored
   `.ics` attachments:

```python
def detect_invite_method(attachments: list[dict[str, Any]]) -> Optional[str]:
    """Return the uppercased METHOD of the first parseable .ics, or None."""
    for att in _filter_ics_attachments(attachments):
        try:
            cal = icalendar.Calendar.from_ical(att["data"])
        except Exception:
            continue
        method = cal.get("METHOD")
        if method:
            return str(method).strip().upper()
    return None
```

5. **Process-time backstop** *(shipped in PR #190, one alignment remaining)* —
   in `process_email_for_events` (`services/events.py`), after sender-rule
   checks, before ICS/LLM extraction. As shipped it marks the email
   `"processed"`; change it to `"skipped"` so the queue-state matches the
   ingest-time marking and the sender-ignore path:

```python
invite_method = ics_parser.detect_invite_method(attachments)
if email_metadata.get("is_calendar_invite") or invite_method in ics_parser.INVITE_METHODS:
    result = {"num_events": 0, "num_new": 0, "num_updated": 0}
    mark_email_status(
        supabase_client, email_id, "skipped",
        outcome="calendar_invite",
        explanation="Calendar invitation — already handled by your email client and calendar.",
        result=result,
    )
    return result
```

   `fetch_email_with_attachments` must include `is_calendar_invite` in the
   returned metadata dict. This backstop exists for exactly three cases —
   it should almost never fire:
   - the `reprocess_email` RPC (`20260712000005_…`) resets any email to
     `pending`, including ingest-skipped invites a user reprocesses from
     History;
   - Gmail messages whose `text/calendar` METHOD was undeterminable at fetch
     time (attachment-only body) but is readable from the stored attachment;
   - emails ingested before this workstream ships.

   `METHOD:PUBLISH` or a missing METHOD falls through to today's behavior at
   both layers (`parse_ics_attachments` still creates events from plain
   "add to calendar" files).
6. **History UI** *(shipped in PR #190)*:
   `frontend/src/routes/app/history/+page.svelte` outcome map: `calendar_invite`
   renders via `history.emailCalendarInvite`. Invites appear in History as
   skipped-with-reason, never as gaps — do not silently drop invite emails at
   fetch time; the row is the audit trail and the recovery path if detection
   ever misfires.
7. The existing RSVP noop rule in the propose prompt stays as belt-and-braces
   (RSVPs that slip through still gate to noop).

### Interaction with existing events

If an invite email would have *updated* an existing Selko event (organizer
moved the meeting), we now skip it. Accepted trade-off: for invite-managed
meetings the calendar itself is the source of truth, and Selko's GCal
read-back (WS3) sees the moved event. Do not special-case this.

### Tests (backend unit + frontend unit)

PR #190 already covers `detect_invite_method`, the Outlook flag, the
process-time skip, and the History label. The remaining ingestion work needs:

- `parse_gmail_message`: `text/calendar` part with `method=REQUEST` in
  Content-Type → flag true + skip fields set; METHOD only in inline body
  data → flag true; `method=PUBLISH` → flag false, no skip fields; no
  calendar part → flag false; calendar part with attachment-only body →
  flag false (backstop case).
- `parse_outlook_message`: payload with
  `"@odata.type": "#microsoft.graph.eventMessageRequest"` → flag true + skip
  fields set; plain message → false, and the parsed dict contains NO
  `processing_status` key.
- `detect_invite_method`: REQUEST → "REQUEST"; PUBLISH → falls through and
  `process_email_for_events` still extracts; no METHOD → None; malformed ics →
  None.
- Ingest short-circuit: an invite-flagged parsed dict saved via `save_emails`
  produces a row with `processing_status='skipped'` /
  `outcome='calendar_invite'` (assert on the upsert payload with a mocked
  client) — i.e. it can never be claimed, and no LLM gateway is constructed.
- Backstop: email row flagged `is_calendar_invite` but status `pending`
  (reprocess path) → `process_email_for_events` skips with outcome
  `calendar_invite`, gateway never called.
- History page test: outcome renders the new label.

---

## Rollout order and PR mapping

Each row is one worktree + PR per `CLAUDE.md`. Local, change-scoped tests are
the merge gate.

| # | Branch | Contents | Status |
|---|--------|----------|--------|
| 1 | `fix/dedup-local-day-window` | WS3 (a+b+c) + regression tests | **Implemented — PR #187** |
| 2 | `feat/retroactive-sender-ignore` | WS1 migration + web | **Implemented — PR #188** |
| 3 | `fix/all-day-dates-and-duration` | WS5 (a–d) | **Implemented — PR #189** |
| 4 | `feat/calendar-invite-suppression` | WS6 backstop layer | **Implemented — PR #190** |
| 5 | `feat/invite-filter-at-ingestion` | WS6 remaining: Gmail parse-time detection, store pre-skipped, backstop `skipped` alignment | **Implemented — PR #192** |
| 6 | `feat/update-proposal-discipline` | WS4 (a–d) | **Implemented — PR #194** |
| 7 | `chore/cleanup-review-incident` | WS2 script | **Implemented — PR #196** (script only; **not yet run against staging/production** — needs explicit approval before `--apply`) |

Post-merge automated review comments landed on PRs #188–#194 after they were
squash-merged; every real finding (a dedupe-trigger requeue bug, a GCal
all-day date shift, a multi-attachment invite-detection gap, the calendar-
invite backstop's `skipped` status being overwritten by the worker pool, and
two gaps in the update-proposal discipline gates) was fixed and merged in
follow-up PR #197, with a reply on each original PR. See CLAUDE.md's
"Check for unaddressed PR review comments" step.

Before running WS2 against production, verify the affected user's review
list first: the ~11 incident-sourced items, the duplicate deadline event,
and the second duplicate-appointment change card should be gone once
`--apply` runs.

Deployment note: rows 1–6 (and PR #197) all touch `backend`/`supabase`/
`frontend`, so each shipped a final production-deploy question per
`CLAUDE.md`; the actual production deploy still requires the user's
explicit approval, as does running WS2's script against staging/production
data.

## Documentation follow-ups

- [x] Folded "how invites are handled" into `docs/gmail-integration.md` as a
  Selko-specific appendix (the rest of that doc is generic Gmail API
  research, not Selko implementation docs, and has no separate Outlook
  file).
- [x] Updated `docs/database-schema.md`: `emails.is_calendar_invite`, the
  `calendar_invite` outcome, the `ignore_sender_and_reject_pending` RPC,
  `claim_unprocessed_email`'s oldest-`date_sent`-first ordering, and the
  `sender_rules` trigger's equivalent-rule guard.
- [x] Marked this spec **Implemented**.
