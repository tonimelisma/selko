+++
spec_id = "event-identity-reach"
readme_order = 12
title = "Event identity reach: invites, reschedules, and the user's existing calendar"
increments = "I1–I5"
gate = "I1–I5 implemented; backfill not yet applied to production"
tests = [
  "tests/test_calendar_identity_match.py::test_matching_uid_proves_the_user_already_has_the_event",
  "tests/test_calendar_identity_match.py::test_a_shared_join_url_alone_never_merges_two_events",
  "tests/test_calendar_mirror.py::test_the_runtime_actually_runs_the_mirror",
  "tests/test_thread_identity_rung.py::test_a_thread_matches_its_event_across_a_date_change",
  "tests/test_thread_identity_rung.py::test_a_shared_thread_does_not_merge_different_events",
  "tests/integration/test_integration_identity_hint_coverage.py::test_ordinary_email_yields_a_provider_thread_hint",
]
health = []
drills = []
+++

# Event identity reach

**Status:** I1–I5 implemented and merged. The backfill script (I5) has been
dry-run against production, which reports 19 candidate attachments, but has not
been applied.

One defect found while building I4 is worth recording separately, because it
invalidates the measurement in §1: `_load_identity_context` selected a
`body_html` column that no longer exists. PostgREST rejects the whole select for
an unknown column and the failure was swallowed by a debug-level `except`, so
`provider` and `thread_id` were empty for every email and **no `provider_thread`
hint had ever been written**. The 14 hints counted below were the `join_url`
ones, derived from event text rather than from that query. Hint coverage should
therefore improve on its own now that the select works, independently of the
backfill.

**Written:** 2026-08-30, from production data rather than from design intent.

## 1. What production actually looks like

Measured on production 2026-08-30, not estimated:

| Measure | Value |
|---|---|
| Emails | 2698 |
| Events | 364 |
| `email_calendar_components` | 6 |
| `event_identity_hints` | 14 |
| Hints by kind | `join_url` 14, `ical_uid` **0**, `provider_thread` **0** |

Component capture works. Every ICS-bearing email ingested after the capture
feature reached production on 2026-08-22 produced a component (6 of 6 on
2026-08-28); the 18 that produced none all predate that deploy and were never
backfilled. There is no parsing defect.

The consequence is nonetheless severe: **about 4% of events carry any identity
hint, and not one carries an iCalendar UID.** Identity today rests almost
entirely on video-call join URLs.

### The cases that motivated this

*One email, five events.* A single confirmation email
("Virtual Zoom Interview Confirmation", 2026-08-28 20:58) produced five events
across two days -- one at 9/04 22:30 and four on 9/09 at 17:00, 18:00, 21:30 and
23:00. Extraction was **correct**: these are five distinct interview slots. They
appeared in the review queue as New even though the user had already accepted
the corresponding ICS invites, which were sitting in their Google Calendar.

*Same event, two emails.* 2026-09-18 carries both "Ice Cream Social & Costume
Swap" and "Ice Cream Social & PTA Meeting", 30 minutes apart, both accepted,
both now in the calendar. One real event, two entries.

*Similar but distinct.* The same day holds "Swedish: Beginner 1A",
"Swedish: Intermediate 1A" and "Swedish: Advanced". These must never merge.
Any fix that collapses the Ice Cream Social pair must leave these alone.

## 2. Why the current design cannot resolve them

`find_matching_event` builds candidates as:

```python
local_day = start.astimezone(user_tz).replace(hour=0, ...)
.gte("start_datetime", local_day).lt("start_datetime", local_day + 1 day)
```

Three properties follow, and they explain every symptom above.

**R1. Identity hints are never derived from the user's calendar.** Hints are
computed from incoming email and stored against Selko's own events. Google
Calendar entries are fetched as candidates but compared only by title, time and
an LLM judgement. `iCalUID` -- returned by the Google Calendar API on every
event, and equal to the UID in the invite the user accepted -- **appears nowhere
in the codebase**. An event that exists only in the user's calendar can
therefore never be matched by identity, only guessed at by text.

**R2. The candidate window is one local day.** An event rescheduled to another
date is outside its own candidate window, so it cannot be compared against its
earlier self. Only a hint escapes this, because the hint lookup uses an explicit
1970–2100 read set. With no `ical_uid` hints in production, no reschedule across
days can currently be recognised as an update.

**R3. Same-day dedup ends in an LLM text comparison**, which declines when two
emails describe one event with different emphasis, and which must keep declining
for the class-level case. Text alone cannot separate these two situations
reliably; a durable non-text signal is required.

## 3. Requirements

**I1 — Match the user's calendar by identity. _Implemented._** Identity hints
are extracted from Google Calendar entries (`iCalUID` plus `originalStartTime`
for a recurring occurrence, and the video join URL from `hangoutLink` or
`conferenceData`) and compared against the incoming event's hints before the LLM
rung runs. An authoritative UID match resolves immediately.

A shared join URL never merges on its own: sessions in one interview loop
routinely share a meeting link, and collapsing five real events into one is
worse than the duplicate this prevents. `match_by_identity` accepts only
`strength == "authoritative"`, and a test asserts that removing the guard breaks
the loop case.

**I2 — Identity lookup must not be bounded by the candidate window.** Hint
matching already uses a time-independent read set; the calendar-derived hints of
I1 must use it too, so a reschedule is recognised regardless of its new date.

**I3 — Give text-only mail a date-independent hint.** Where no UID exists,
derive a hint from provider thread plus normalised organiser, so a follow-up
message about a known event can reach its earlier self across a date change.
This hint is *supporting*, never authoritative on its own (§4, rung 4).

**I4 — Backfill.** 18 ICS-bearing emails predate component capture. Re-parse
them so their UIDs enter the hint table, or accept permanently that events
before 2026-08-22 have no authoritative identity and record that decision.

**I5 — Never merge on a shared prefix.** Distinct sessions of one series
(different times, different levels) must survive every rule above. This is a
constraint on I1–I3, not a separate feature.

## 4. The resolution ladder, as it must become

Rungs are tried in order; the first that resolves wins.

| # | Rung | Signal | Authority |
|---|---|---|---|
| 1 | Authoritative UID | `ical_uid` (+ `recurrence_id`), from email **or from the user's calendar** | Decides alone. `SEQUENCE`/`DTSTAMP` order revisions |
| 2 | Exact duplicate | Same join URL **and** same start instant | Decides alone |
| 3 | Provider thread | Same thread + same organiser + overlapping window | Decides alone for *updates*, never for creates |
| 4 | Two-signal correlation | Any two of: join URL, organiser, normalised title, same start | Decides |
| 5 | LLM local-day comparison | Text | Last resort, same-day only |

Today only rungs 2, 4 and 5 can fire, because rung 1 has no data and rung 3 does
not exist.

## 4a. What the code does today (read 2026-08-30, not assumed)

| Fact | Where | Consequence |
|---|---|---|
| Calendar reads are `timeMin`/`timeMax`, `singleEvents=True`, **`maxResults=50`**, no `syncToken` | `calendars.fetch_calendar_events_for_date_range` | A busy day truncates silently; nothing is retained between calls |
| No table mirrors the calendar. `calendar_sync_log` records *our own writes*; `user_calendar_settings` holds settings | schema | "Do I already know this?" has no index to consult |
| Hints are keyed to `event_id`, unique on `(event_id, kind, value_hash, recurrence_id)`, looked up by `(user_id, kind, value_hash, recurrence_id)` | `event_identity_hints` | Only Selko-created events can be found by identity |
| `commit_email_extraction` re-checks a window fingerprint **and** a hint fingerprint over `events` before writing | `20260830000002` | Any new matching source must join the fence, or a concurrent writer can invalidate the decision |
| A calendar match already **adopts** the entry: creates an event carrying `google_calendar_event_id` with `source_origin: google_calendar` | `events.py` ~705–755 | Adoption exists; only *discovery* is missing |
| `_calendar_service_for_user` resolves credentials by provider and `target_calendar_id or "primary"` | `calendars.py:1131` | With two `google_calendar` integration rows, which calendar is read is not deterministic |
| Divergence is detected per event by a live GET at undo time | `assert_calendar_not_diverged` | External edits are invisible until someone undoes something |

The adoption path is the important one: Selko already knows how to take a
calendar entry as the baseline for an event. What is missing is that it only
ever sees an entry when an email happens to match it inside a one-day window.

## 4b. Plan

Five increments. Each is shippable, wired to call sites, and testable on its own;
none is a refactor without behaviour.

### Two questions that turned out not to be open

An earlier draft of this plan raised "what may we store about events the user
did not send us" and "which calendar is authoritative" as decisions blocking I2.
Both dissolve on inspection, and are recorded here so they are not raised again.

**What is stored.** `emails` already holds `subject`, `snippet`, `body_text` and
`from_email`; `events` already holds `title`, `description` and `location`. Every
one of those tables has RLS enabled and is scoped to the owning user. Mirroring a
calendar entry's title, times and location is the same posture, not an
escalation. The *content-free* rule in this codebase governs two specific
things — identity hints, whose values are hashed, and health and diagnostic
telemetry, which carry counts, rates and status labels only. It has never
governed user data at rest. Mirrored entries therefore store the field set the
matcher and the review UI need, under RLS, and the hints derived from them stay
hashed exactly as email-derived hints already are.

**Which calendar.** The one the user connected. Authority is not something this
system chooses: an integration row belongs to a user, carries its own
credentials, and `user_calendar_settings.target_calendar_id` names the calendar
within it. If the user connects a different calendar, that is simply a different
target and the mirror follows it. The two `google_calendar` rows in production
that prompted the question belong to **two different users**, which is the
system working correctly.

The one genuine parameter is **how much calendar to mirror**. All history is
unbounded and pointless; matching only ever asks about events near an extracted
date. Mirror a rolling window — a few months back, a year forward — and let the
window, not the row count, bound cost. That is an engineering choice inside I2,
not a precondition for it.

### I2 — Mirror the calendar, incrementally

`calendar_entries`: `user_id, integration_id, calendar_id, provider_event_id,
ical_uid, recurring_event_id, original_start, start_at, end_at, all_day,
timezone, status, self_response, etag, provider_updated_at, sequence, origin
(selko_created|external), deleted_at`. Unique on
`(integration_id, calendar_id, provider_event_id)`. **RLS in the same
migration**, owner-readable, service-writable.

`calendar_mirror_state`, one row per `(integration_id, calendar_id)`, copying
the shape `email_sync_state` already proves: `sync_token, last_full_resync_at,
next_poll_at, lease_owner, lease_expires_at, lease_generation,
consecutive_failures, last_error_code`.

Sync uses `events.list(syncToken=…)`, so a steady state transfers only changes —
this matters because the egress rule forbids unconditional periodic reads. A
`410 GONE` clears the token and forces one full resync. Deletions become
tombstones (`deleted_at`), never row deletes, so drift and undo stay answerable.

The loop is a task in `IngestionRuntime` using the existing claim → heartbeat →
complete/fail fencing, which also satisfies the reachability test.

### I3 — Let identity reach the mirror

Add `calendar_entry_id uuid` to `event_identity_hints`, nullable, with
`CHECK (num_nonnulls(event_id, calendar_entry_id) = 1)` so a hint names exactly
one entity. The existing lookup index already covers
`(user_id, kind, value_hash, recurrence_id)` and needs no change.

Populate hints on every mirror upsert via the existing
`hints_from_calendar_event`. Extend `_load_identity_candidates` to return
calendar entries beside events.

**Extend the fence.** `commit_email_extraction`'s hint fingerprint currently
covers `events` reached through hints; it must also cover `calendar_entries`
reached through hints, or a concurrent mirror sync can invalidate a decision
between match and commit. This is the step most likely to be skipped and the one
that would reintroduce the race P2 closed.

I1 (shipped) already compares calendar identity inline at match time. I3
replaces that with the index, so the answer no longer depends on the entry
falling inside a 50-result day window.

### I4 — A hint that survives a date change

Text-only mail carries no UID. Derive `provider_thread` (already implemented in
`event_identity`) plus a normalised organiser, and add rung 3: same thread and
organiser with an overlapping window **decides for updates only, never for
creates**. That asymmetry is deliberate — a thread is strong evidence that two
messages concern one event, and weak evidence that a new event exists.

This is what closes S4 and S5 for mail without an invite; I1 only closes them
when an ICS is present.

### I5 — Backfill and drift

Re-parse the 18 ICS-bearing emails that predate component capture so their UIDs
enter the index, or record the decision not to. Then use the mirror for what it
uniquely enables: noticing that the user moved or deleted an event themselves,
which today is invisible until an undo triggers `assert_calendar_not_diverged`.

### Verification each increment owes

| Increment | Beyond the lanes |
|---|---|
| I2 | New tables → RLS in the same migration. New loop → watch RSS and `/health/egress` over hours; a mirror that re-reads everything is the exact shape of the #191 OOM and the 942 MB egress bill. Assert the rolling window actually bounds the row count, or it does not bound anything |
| I3 | Migration touches a populated table → `rehearse_cutover.py --faithful`. Fence change → the conflict test must fail without it |
| I4 | Evals: S4/S5 fixtures alongside the three already committed |
| I5 | Backfill is a production data mutation → dry run, manifest, reverse artifact |

## 5. Scenarios that must be covered

Each row is a required test. "New" means a new event is created; "Update" means
the existing event receives a change proposal; "Ignore" means provenance is
recorded and nothing is proposed.

| # | Scenario | Expected |
|---|---|---|
| S1 | ICS invite arrives, event unknown | New, hint `ical_uid` written |
| S2 | Same ICS re-delivered (same UID, same `SEQUENCE`) | Ignore |
| S3 | ICS revision (same UID, higher `SEQUENCE`) | Update |
| S4 | **Text email updates an earlier ICS event** (same thread/organiser, no UID in the text) | Update via rung 3 — *not* a new event |
| S5 | **Text email reschedules to another date** | Update, matched by UID or thread, never by window |
| S6 | Event already in the user's calendar from an invite accepted elsewhere; email describes it | Ignore — must not appear as New (rung 1 via `iCalUID`) |
| S7 | One email describes several distinct sessions | Several New events; never collapsed |
| S8 | Two emails describe one event with different titles | Update/merge into one |
| S9 | Series with several levels on one day | Separate events; never merged |
| S10 | ICS `METHOD:CANCEL` for a known UID | Cancellation proposal |
| S11 | Text email cancels an ICS-created event | Cancellation via rung 3 |
| S12 | Recurring invite, single occurrence changed (`RECURRENCE-ID`) | Update that occurrence only |
| S13 | Same UID, different user | Never matches across users |
| S14 | Declined event, later email about it | Provenance only; never revived (`review-queue-integrity` §8.2) |
| S15 | ICS present but malformed | Component ignored, extraction still proceeds |

S4, S5 and S6 are the user-reported failures. S7 and S9 are the regressions any
fix must not cause.

## 6. Evals

Anonymized from production, in `backend/tests/eval/fixtures/compare/`:

- `interview_loop_distinct_slots_20.json` — S7: sessions at 17:00/18:00/21:30/23:00 must not merge
- `same_event_two_agenda_titles_21.json` — S8: one event, two agenda titles, 30 minutes apart
- `same_series_different_level_22.json` — S9: Beginner/Intermediate/Advanced must stay separate

These cover the LLM rung. Rungs 1–4 are deterministic and belong in integration
tests against real Postgres, not in evals.

## 7. Non-goals

Importing the user's whole calendar into `events`. I1 needs identity comparison
at match time, not a mirror of the calendar, and a mirror would raise ownership
questions that `calendar_work_items` already answers for the write direction.
