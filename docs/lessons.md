# Lessons

Rules learned the hard way that are not obvious from the code, and problems still open. When a
rule moves into a test, an ADR or `CLAUDE.md`, or a problem is solved, its entry is deleted here.

## Rules learned

- **Never trust a signal that cannot fail.** Every serious defect came from a green signal that
  meant less than it looked: a `/health` probe satisfied by any server on the port, UI assertions
  behind `guard … else { return }`, an initializer parameter accepted and discarded. Ask: if this
  were broken now, would this check go red?
- **If an invariant matters enough to write down, it matters enough to assert;** otherwise delete
  the sentence. An assertion must name the thing the runtime actually uses, never a neighbouring
  name or a migration's text.
- **An increment is not done because its PR merged.** It is done when something that would fail if
  it were absent passes. Name each increment's state individually; "#306–#312 delivered R2–R5"
  sounded true and was false.
- **SQL never executed is not tested.** Two migrations once applied cleanly, passed a mocked suite
  and broke every UPDATE on first real call. Mock providers, never the database.
- **A route no test calls has not been tested.** `apply-change` returned 500 to every request for
  eight days while the service under it was well covered.
- **An unhandled exception must still return a CORS-bearing response.** Starlette's
  `ServerErrorMiddleware` sits outside `CORSMiddleware`; a bare crash reads in the browser as a
  network failure ("Load failed"). `app.py` registers a catch-all handler.
- **Call sites are part of the increment.** Code behind a flag or injected dependency shipped three
  times with no caller and a green suite; `test_reachability.py` now fails on unreachable modules.
- **A schema object and the code that fills it land together.** Dormant tables are still in the
  schema (`action_history`, `event_repair_audit`: #455, #456).
- **A dry run cannot catch a write-path defect.** A backfill's dry run was green and its first real
  insert failed on a column it never fetched. Rehearse writes against a copy.
- **Never swallow a data-access failure at debug level.** A broken select hidden that way meant no
  `provider_thread` hint was ever written.
- **Rows that leave the data layer must be JSON-safe there**; `json.dumps(default=str)` hides the
  leak ([Graph ledger](design/microsoft-graph.md)).
- **Roll stubs out instead of finishing them in place,** and fix a flaky test's isolation instead
  of marking it expected-to-fail.
- **Configuration is invisible in a diff.** Most production breaks were config, data shape or
  elapsed time, not logic ([research](research/2026-08-22-production-breakage-root-causes.md)).

## Open problems

- Defects found while writing the requirements (UID hash case, run counters, invite skip,
  folder classification, privacy-policy defaults): #457.
- Postgres-era leftovers weaken guards (reachability exemption, `client` and `pg_pool` names, code
  comments citing deleted specs): #456.
- No storage or schema-version surface on `/health`, and no restore test on record: #452.
