# Calendar Identity and Cancellation

**Status:** C1 implemented in this increment; C2–C3 remain planned.

**Written:** 2026-08-12.

**Replaces:** the R3 and R4 increments of
[`review-queue-integrity.md`](review-queue-integrity.md), which shipped DDL with
no behaviour (`stub-rollback-and-gate-repair.md` D-R3.1, D-R4.1) and were
dropped by G1.

**Depends on:** [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md)
P1–P3 merged and verified in production. Identity matching adds rungs above the
existing candidate comparison and writes hints alongside events, so it needs the
single fenced commit path to exist first — otherwise it adds a second writer to
the race P2 is closing.

**Normative requirements:** `review-queue-integrity.md` §7 (identity), §8
(cancellation) and §3 decisions 9–11 are the requirement text for this plan.
They are correct and are **not** restated here. This file specifies how they are
built so that each increment is wired end-to-end, which is the only thing R3
and R4 got wrong.

---

## 1. Why R3 and R4 failed, and what changes

R3 created `email_calendar_components` and `event_identity_hints` and stopped.
R4 added three columns and a status value and stopped. Neither table was ever
written to; neither column was ever set. The gate passed because empty tables
and unset columns behave perfectly.

The structural change here is a rule, enforced by G4's reachability guard and
by each increment's acceptance criterion:

> **A schema object and the code that fills it land in the same increment.**
> A migration that creates a table whose only writer is a future PR does not
> merge.

That is why this plan has three increments rather than R3's and R4's two, and
why each one is a vertical slice — parser, canonicalizer, table, matcher,
test — instead of a horizontal layer.

---

## 2. Increments

### C1 — Parse calendar components and write them

**Branch:** `feat/calendar-component-parsing`

One increment containing **all** of:

1. **Migration** — recreate `email_calendar_components` exactly as
   `review-queue-integrity.md` §7.1 specifies (RLS enabled in the same
   migration, service-role only, `UNIQUE (email_id, component_index)`).
2. **`save_email_with_attachment_descriptors` gains `p_calendar_components`
   again**, restoring the four-argument form G1.2 reverted — but with D-R3.2
   fixed. The write must be **non-destructive when the caller supplies
   nothing**:

   ```sql
   -- R3 shipped an unconditional DELETE, so any later re-save of the email
   -- (reconciliation upsert, delta re-fetch, Outlook folder move) silently
   -- erased previously parsed components. Only replace when the caller
   -- actually parsed something.
   IF jsonb_array_length(COALESCE(p_calendar_components, '[]'::jsonb)) > 0 THEN
       DELETE FROM public.email_calendar_components WHERE email_id = v_email_id;
       INSERT INTO public.email_calendar_components (...) SELECT ...;
   END IF;
   ```

   Exactly one callable overload when the increment lands.
3. **Gmail parsing** — `services/gmail.py`: every `text/calendar` part,
   including inline. Preserve per-VEVENT `METHOD`, `UID`, `RECURRENCE-ID` and
   `RANGE`, `SEQUENCE`, `DTSTAMP`, `STATUS`, `DTSTART`, `DTEND`. A malformed
   component logs safe telemetry and falls back to invite classification
   without failing acquisition.
4. **Outlook parsing** — `services/outlook.py`: preserve `meetingMessageType`,
   especially `meetingCancelled`; map `iCalUId` and dates from the associated
   event; when list/delta lacks navigation data, issue the documented bounded
   `GET`, meter its egress through `services/egress.py`, and obey Graph
   retries. A missing associated event becomes a structured cancellation
   without UID.
5. **Wiring** — `workers/email_ingestion.py::acquire_item()` passes the parsed
   components into the atomic save. This is the step R3 omitted.

**Tests**

- Unit, per provider, from anonymized fixtures: inline Gmail `text/calendar`,
  Gmail attachment `.ics`, multi-VEVENT, malformed VEVENT, Outlook
  `meetingCancelled`, Outlook missing associated event.
- Integration, real Postgres: acquire a Gmail fixture with an inline `CANCEL`
  and assert the `email_calendar_components` rows exist with the right
  `method`, `uid_hash` and `sequence`.
- Integration: **re-save the same email with `[]` and assert the components
  survive.** This is D-R3.2's regression test.

**Acceptance:** `SELECT count(*) FROM email_calendar_components` is non-zero
after the integration suite. A table this increment creates and does not fill
is the failure being corrected — do not merge it empty.

---

### C2 — Identity hints and the matching ladder

**Branch:** `feat/event-identity-matching`
**Depends on:** C1.

1. **Migration** — recreate `event_identity_hints` per §7.2, RLS in the same
   migration, service-role only, lookup index on
   `(user_id, kind, value_hash, recurrence_id)`.
2. **`backend/selko/services/event_identity.py`** — the canonicalizer §7.2
   specifies: `ical_uid` (authoritative, with recurrence identity),
   `provider_thread`, `join_url`, `management_url` (all supporting). Log kind
   and match presence only — never a raw value and never a hash.
3. **The ladder** — implement §7.3 inside the resolution half of
   `save_extracted_events()`, ahead of the existing local-day LLM comparison,
   which stays as rung 4.
4. **Hint attachment** — new validated hints are written in the **same
   transaction** as the event, i.e. inside `commit_email_extraction`
   (`parallel-extraction-fenced-commit.md` P1.1). Extend that RPC's decision
   payload with a `hints` array. Do not add a second writer.

   A hint that participates in matching must also participate in the
   fingerprint fence, or C2 reopens the race P2 closed: when the ladder matches
   on a hint rather than on the local-day band, extend the decision's window to
   cover the hint lookup, or record explicitly why the hint's candidate set
   cannot change concurrently. Do not leave this to the implementer's judgement
   — decide it in the C2 PR description and test it.

**Tests** — the four cases in §7.4, as deterministic tests where the outcome is
structural and as anonymized evals where it is a model judgement:

| Case | Kind | Must assert |
|---|---|---|
| Two worded confirmations, one slot | eval | one event, two sources |
| Original → reschedule sharing a management URL | eval | update, not create |
| Two distinct meetings sharing a permanent room | **deterministic** | two events; one supporting hint never merges |
| Stale `SEQUENCE`; equal `SEQUENCE`, later `DTSTAMP` | **deterministic** | stale is an audited no-op |

Hand-write expected output. Run individual fixtures first per
`backend/tests/eval/README.md`. If the compare or propose prompt changes, run
the full default-model all-operation suite before and after and save both
reports per `docs/evals-process.md`.

**Acceptance:** the permanent-room negative case passes without a model call —
it must be impossible for one supporting hint to merge, by construction rather
than by prompt quality.

---

### C3 — Automatic cancellation

**Branch:** `feat/automatic-event-cancellation`
**Depends on:** C2.

`events.calendar_sync_action`, `events.calendar_work_generation` and the
`cancel_queued` status value already exist — G1 kept them, and
`20260814000002`'s `claim_calendar_work` already selects
`status IN ('approved','cancel_queued')` and increments the generation. C3
supplies the behaviour that was missing.

1. **Classification** — §8.1's three classes. Structured authoritative and
   unstructured strong auto-apply; ambiguous and unmatched never create or
   mutate, and finish the email with `cancellation_ambiguous` /
   `cancellation_unmatched` and a safe History reason.
2. **Routing** — stop pre-skipping `CANCEL` in `process_email_for_events()`.
   `REQUEST`, `REPLY`, `COUNTER` and `DECLINECOUNTER` stay skipped (§3, note
   under decision 11).
3. **Local Review transitions** — §8.2's table. **Preserve the original
   title**; terminal status plus History already communicate cancellation.
4. **Worker-owned calendar cancellation** — §8.3. The worker branches on
   `calendar_sync_action`. Complete/fail/defer/park all carry id, owner and
   generation; zero rows updated means stale ownership and must not overwrite a
   newer cancellation. Success sets `cancelled`; retries preserve the action so
   recovery never turns a cancel back into an upsert.
5. **Delete the inline path** — `apply_pending_change()` must stop calling
   `calendars.cancel_calendar_event()`. §2.3 identified this: it writes Google
   Calendar inline, outside the single-owner worker. Once no caller remains,
   delete the function. Do not deprecate it.
6. **Surfaces** — `cancel_queued` in OAuth recovery sets, History labels, API
   schemas, and the web/iOS/Android History views. Review still queries only
   `pending_review` / `pending_change`.

**Tests** — the twelve cases in §8.4, plus:

- `test_apply_pending_change_never_calls_google` — asserts the inline path is
  gone, guarding the §3 decision 11 invariant against reintroduction.
- Frontend unit tests for the History label, on every platform whose History
  view changed, plus screenshots for those platforms only.

**Acceptance:** a pending cancellation is auto-dispositioned out of Review with
no user action, and `grep -rn "cancel_calendar_event" backend/` returns nothing
outside its own deleted history.

---

## 3. Verification

Before each merge: `./scripts/verify.sh backend` (plus
`./scripts/verify.sh frontend` and web screenshots for C3's History change).
After each merge: `./scripts/verify.sh staging`.

Staging fault drills — `review-queue-integrity.md` §11 drills 7 and 8, which
only C3 can execute:

7. Race a calendar upsert against a cancellation; cancellation wins and the
   stale upsert completion cannot reset it.
8. Fail OAuth on a queued cancel; reconnect resumes the cancel, not an upsert.

### First seven production days

- no cancellation creates a New card;
- no known matched pending cancellation remains in Review;
- zero false merges from a single supporting hint;
- egress unchanged except for the bounded, metered Graph associated-event
  fetches from C1.

---

## 4. Rollback

| Increment | Rollback |
|---|---|
| C1 | Revert code and migration together. The four-arg RPC and its only caller must move as one — never leave a deployed caller with a missing signature. Components are additive; retain the table until the revert is verified. |
| C2 | Hints are additive and ignorable by rolled-back code. Revert the ladder; keep the table until verified. |
| C3 | **Stop new classification but retain queued cancellations.** Drain or park them before rolling back. Never coerce `cancel_queued` to `approved`/`upsert` — that recreates a cancelled event on the user's real calendar. |

---

## 5. Definition of done

- [ ] C1–C3 merged, locally verified, staging-verified, drills 7 and 8 run.
- [ ] Every table this plan creates is written to by code in the same
      increment, proven by a non-zero row count after the integration suite.
- [ ] Gmail inline and attachment `text/calendar`, and Outlook
      `meetingMessageType`, all reach `email_calendar_components`.
- [ ] Re-saving an email without components does not delete them (D-R3.2).
- [ ] No weak hint alone merges or cancels; the permanent-room negative case is
      deterministic, not prompt-dependent.
- [ ] Hints are written inside `commit_email_extraction`, not by a second
      writer.
- [ ] Cancellation never creates; ambiguous and unmatched are audited outcomes.
- [ ] Calendar writes are worker-owned; `cancel_calendar_event()` is deleted.
- [ ] `cancel_queued` handled in recovery, History, and API schemas on every
      platform.
- [ ] `docs/database-schema.md`, `docs/gmail-integration.md`,
      `docs/microsoft-graph-failure-ledger.md` and `CLAUDE.md` updated.
- [ ] `review-queue-integrity.md` R3 and R4 marked **superseded by this file**.
