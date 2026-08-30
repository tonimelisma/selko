+++
spec_id = "event-identity-reach"
readme_order = 12
title = "Event identity reach: invites, reschedules, and the user's existing calendar"
increments = "I1–I5"
gate = "not started"
tests = []
health = []
drills = []
+++

# Event identity reach

**Status:** requirements only. No increment implemented.

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

**I1 — Match the user's calendar by identity.** Extract identity hints from
Google Calendar entries (`iCalUID`, and the join URL in `conferenceData` or
`hangoutLink`) and admit them to the same resolution ladder as email-derived
hints. An event whose UID or join URL already exists in the user's calendar is
**already known** and must not be proposed as New.

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
