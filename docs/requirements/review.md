# Requirements: Event review lifecycle

How an extracted event moves through the New and Changes lanes into History: approve, reject and
edit; `event_change_proposals` and its apply, reject and reopen transitions in `selko.db.proposals`;
how updates are routed by provenance; declined-event terminality; and undo.

## Lanes and reads

- **SEL-200** When the user opens the review queue (`GET /events/review`), Selko shall return the
  user's not-yet-ended events that are `pending_review` (New) or `active` with a pending change
  proposal (Changes), soonest start first, at most `limit` (default 200, 1 to 500) rows, with the
  full count in `X-Total-Count`. [verified]
- **SEL-201** When the user opens History (`GET /events/activity`), Selko shall return the user's
  `active`, `rejected` and `cancelled` events, most recently updated first, with `total`, `offset`
  and `limit`. [verified]
- **SEL-202** Selko shall report an event's status as `pending_review`, `rejected` or `cancelled`
  directly from `events.review_status`, whatever calendar work exists. [verified]
- **SEL-203** If a user names another user's event in any event route (get, edit, accept, reject,
  apply-change, reject-change, undo), then Selko shall answer 404 and change nothing. [verified]
- **SEL-204** When History lists an event, Selko shall leave out its pending proposals.
  unverified: `events_with_relations(exclude_pending_proposals=True)` is not asserted by any test;
  checked by reading `db/client.py`.

## New lane decisions

- **SEL-206** When the user accepts an event (`POST /events/{id}/accept`), Selko shall set
  `review_status` to `active` and queue a calendar `upsert` work item carrying the event's title,
  times, all_day, location, description, importance and source attribution. [verified]
- **SEL-207** When the user rejects an event (`POST /events/{id}/reject`), Selko shall set
  `review_status` to `rejected` and queue no calendar work. [verified]
- **SEL-208** If a review decision is anything but `active` or `rejected`, or the caller is not
  authenticated or does not own the event, then Selko shall refuse it and leave the event as it
  was. [verified]
- **SEL-209** When the user accepts an event they had rejected, Selko shall make it `active` and
  queue its calendar upsert. [verified]
- **SEL-210** When the user edits an event (`PATCH /events/{id}`), Selko shall accept only `title`
  (1-500 characters, trimmed, not blank), `start_datetime`/`end_datetime` (ISO 8601 with an
  offset), `all_day`, `location` (up to 1000) and `description` (up to 20000), answering 422 for
  any other field or an empty body, and return the whole updated event. [verified]

## Change proposals

- **SEL-212** Selko shall keep update and cancellation review state in `event_change_proposals`,
  and shall refuse at commit any transaction that leaves a `pending` proposal on an event whose
  `review_status` is not `active`. [verified]
- **SEL-213** Selko shall allow at most one `pending` proposal per event, and when a new change is
  held for review shall mark the previous pending proposal `superseded`
  (`superseded_by_newer_proposal`) without touching resolved ones. [verified]
- **SEL-214** When the user applies a change (`POST /events/{id}/apply-change`), Selko shall write
  the proposal's values to the event, mark the proposal `applied` with reason `user_applied`, queue
  a calendar upsert, and answer `{"event_id": …, "status": "active"}`. [verified]
- **SEL-215** When a cancellation proposal is applied, Selko shall keep the event `active` and queue
  a `cancel` work item if it has a provider event, and otherwise make it `cancelled` with no
  calendar work. [verified]
- **SEL-216** When the user rejects a change (`POST /events/{id}/reject-change`), Selko shall
  restore the proposal's snapshot values, mark the proposal `rejected` with reason
  `user_rejected`, keep the event `active`, and queue no calendar work. [verified]
- **SEL-217** When rejecting a change deletes an event adopted from the user's calendar, Selko shall
  delete it only if it carries a provider event id and was never synced by Selko, removing all its
  proposals and sources, and shall refuse the delete for any other event. [verified]
- **SEL-218** If the event has no pending proposal, then apply-change and reject-change shall
  answer 400, and the data layer shall raise `ProposalStateError` for a proposal that is not the
  owner's pending one and `NotOwned` for another user's event. [verified]
- **SEL-219** If a transition is given an expected proposal hash that no longer matches the stored
  proposal, then Selko shall raise `StaleProposal` and change nothing. [verified]
- **SEL-220** If an apply asks for a review status other than `active`/`cancelled` or a calendar
  action other than `upsert`/`cancel`, or a reject gives a reason other than `user_rejected` or
  `repair_operator`, then Selko shall refuse it and roll back. [verified]

## Routing of updates

- **SEL-222** When an email updates an approved event that Selko created (no `google_calendar`
  source), Selko shall apply the change at once, queue a calendar upsert, and keep an `applied`
  proposal for History and undo. [verified]
- **SEL-223** When an email updates an event adopted from the user's own calendar
  (`source_origin='google_calendar'`), Selko shall leave the event's values unchanged, create a
  `pending` proposal in the Changes lane and queue no calendar work. [verified]
- **SEL-224** When the model reads an update to a Selko-created event as a cancellation, Selko
  shall hold it in the Changes lane instead of applying it. [verified]
- **SEL-225** If the event's provenance cannot be read, then Selko shall treat it as adopted from
  the user's calendar and hold the change for review. [verified]
- **SEL-226** When an email updates an event still in the New lane, Selko shall write the new
  values to it, keep it `pending_review`, queue no calendar work and skip the provenance lookup.
  [verified]
- **SEL-227** When an email materially changes an event that exists only in the user's live
  calendar, Selko shall adopt it as an `active` event bound to that provider event id and hold the
  change as a `pending` proposal. [verified]
- **SEL-228** While the sender has an `auto_approve` rule, Selko shall apply a material change to an
  event adopted from the calendar directly and queue its calendar upsert.
  unverified: no test combines an auto-approve rule with a calendar match; checked by reading the
  `auto_apply and match.is_gcal` branch of `save_extracted_events`.

## Declined events

- **SEL-230** When a later email matches a `rejected` or `cancelled` event (and confirms no booking
  for a rejected one), Selko shall record only its source and identity hints, with no proposal, no
  field change, no calendar work, no update-proposal LLM call and no new event. [verified]
- **SEL-231** When an organizer cancellation matches a `rejected` or `cancelled` event, Selko shall
  record it with intent `record_only` and queue no calendar cancel. [verified]
- **SEL-232** When an email confirming a booking matches a `rejected` event, Selko shall move it to
  `pending_review` (New) with an `applied` `material_update` proposal recording
  `rejected`→`pending_review`, change no other field and queue no calendar work. [verified]
- **SEL-233** When an email confirming a booking matches a `cancelled` event, Selko shall keep it
  `cancelled` and record only provenance. [verified]
- **SEL-234** If anything asks to queue a calendar upsert for a `rejected` or `cancelled` event, then
  Selko shall refuse it, and queueing calendar work shall never change an event's `review_status`.
  [verified]

## Undo and history

- **SEL-236** When the user undoes an applied change (`POST /events/{id}/undo`), Selko shall reopen
  the latest applied proposal to `pending`, restore the event to its snapshot as `active`, and,
  when the provider event still exists, queue an upsert of the restored values with the provider's
  current revision. [verified]
- **SEL-237** When the user undoes the approval or rejection of a New event, Selko shall return it
  to `pending_review` and, when Selko had written it to the calendar, queue a `cancel` of the
  provider event with its current revision. [verified]
- **SEL-238** If the provider event was edited in the calendar after Selko's last write and the
  undo is not forced, then Selko shall answer 409 `CALENDAR_DIVERGED` with the changed fields,
  differences and event link, and queue nothing; a forced undo shall queue the work with
  `force_overwrite`. [verified]
- **SEL-239** If the provider event no longer exists when an applied change is undone, then Selko
  shall restore the snapshot locally and queue no calendar work. [verified]
- **SEL-240** When the user re-applies a reopened proposal, Selko shall mark it `applied` again.
  [verified]
- **SEL-241** If a reopen names a proposal that is not `applied`, or another user's event, then
  Selko shall refuse it. [verified]
- **SEL-242** If an undo of a calendar-synced event has no user id, or names another user's event,
  then Selko shall raise `EventsError` and change nothing. [verified]
