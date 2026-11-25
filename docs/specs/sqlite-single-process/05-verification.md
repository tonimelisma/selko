# 06 — Verification, tests, CI, tooling and documentation through the migration

Part of the migration plan for `docs/specs/sqlite-single-process.md` (Q0–Q8).
Written 2026-11-25 from a read-only pass over the tree at
`/home/user/selko`. Nothing was run: no test suite, lane, API or database. All
counts were taken with `grep`/`wc` over the files and are stated with the
pattern used where a count could be read two ways.

Conventions used throughout:

- **Fates:** **U** unchanged · **R** rewritten against the new layer (the phase
  and what changes are named) · **X** replaced by a named new test · **D**
  deleted (with why it is safe).
- **Phase tags** refer to the overview's increments: Q1 client data through the
  API, Q2 `/live`, Q3 ownership without RLS, Q4 image/signing/startup
  migrations/image lane, Q5 own auth, Q6 SQLite data layer, Q7 cutover, Q8
  retire.
- Paths in tests are given relative to `backend/` where pytest node ids use
  them (`tests/...`), otherwise from the repository root.
- New SQLite-layer tests live under `backend/tests/db/` (new directory). The
  schema appendix (`01-schema.md`) names
  `backend/tests/test_sqlite_schema.py::test_initial_schema_creates_every_table`;
  this section adopts that node as written and puts the rest of the
  schema-contract successor beside it (§A.7).

---

## 0. Findings that change the plan (read first)

These were found while inventorying. Each one is a "signal that cannot fail"
today and must be fixed **before** the migration relies on it, because the
migration moves or deletes the code these signals are supposed to watch.

1. **`backend/tests/test_workers.py` defines five test classes twice.**
   `TestSingleTransportWiring`, `TestProcessIntegrationRecovery`,
   `TestServiceClientReuse`, `TestEmailProcessWorker` and
   `TestCalendarSyncWorker` are defined at lines 279/331/474/515/604 and again
   at 861/886/1029/1070/1159. Python binds the module attribute to the second
   definition, so pytest collects only lines 861–1370. Tests that exist **only
   in the first copy never run**:
   `TestSingleTransportWiring::test_event_writes_go_through_commit_rpc`
   (line ~300; the module-level copy at line 1382 does run) and
   `TestCalendarSyncWorker::test_worker_cancels_calendar_event_with_fenced_completion`
   (line 686, "Cancellation uses provider delete and never the upsert path").
   The named guards `test_worker_pool_claims_over_the_pool` and
   `test_no_worker_module_retains_a_postgrest_fallback` run from their second
   copies (866, 875). Fix in the first source increment (Q1): delete lines
   279–860 after moving the cancellation test into the live class, and add
   `tests/test_test_hygiene.py::test_no_test_module_redefines_a_class_or_function`
   (AST over `backend/tests/**/*.py`: no duplicate top-level `ClassDef`/
   `FunctionDef` names, no duplicate method names inside a class).
2. **The AST/regex guards walk a cwd-relative path.**
   `test_no_worker_module_retains_a_postgrest_fallback` (`Path("backend/selko")`),
   `test_no_compat_shims_in_workers` (`Path("backend/selko/workers")`) and both
   copies of `test_event_writes_go_through_commit_rpc` pass vacuously when
   pytest runs with cwd `backend/` (rglob finds nothing). `verify.sh` and
   `test.yml` run from the root, so they work today by convention only. Every
   successor guard in this plan resolves its root from `__file__` and asserts
   the scanned file set is non-empty.
3. **The schema contract will not see the four enum types after Q6.**
   `test_check_constraint_domains_are_pinned`
   (`tests/integration/test_schema_contract.py:967`) reads only CHECKs shaped
   `ANY (ARRAY[...])`, and `test_status_literals_in_python_are_permitted`
   (line 996) special-cases `integrations.status` as an enum. In SQLite the 4
   enum types become `CHECK (col IN (...))` (spec §4.2), so the pinned dict
   gains four entries in Q6; the special case is deleted.
4. **The e2e suite cannot pass in a cloud session as written.**
   `frontend/tests/e2e/auth.setup.ts` signs in as `test@selko.local` /
   `testpass123`; `scripts/cloud-setup.sh:275-276` writes
   `TEST_USER_PASSWORD=$(openssl rand -hex 16)`. No lane runs e2e
   (`scripts/lanes.toml` frontend lane = vitest + svelte-check). The image lane
   (B10) runs a subset of e2e against the container and must take the
   credentials from the environment.
5. **Stale references:** `frontend/src/lib/live-updates.js:3` links `docs/specs/live-ui-updates.md`,
   which does not exist. Two spec front-matter test ids do not exist:
   `tests/integration/test_integration_recovery.py::TestClaimIntegrationRecovery::test_reclaims_expired_recovery`
   (`oauth-reconnect-catch-up.md`) and
   `tests/test_repair_review_queue_integrity.py::test_apply_requires_manifest_and_confirmed_user`
   (`parallel-extraction-fenced-commit.md`).
6. **Count reconciliation with spec §2.** The spec's "126 files" / "45 files"
   count every `.py` file; test modules are **119**: 70 in `backend/tests/`,
   5 in `backend/tests/unit/`, 1 in `backend/tests/drills/`, 43 in
   `backend/tests/integration/`. `def test_` definitions: 1,302 outside
   `integration/`, 346 inside (parametrization expands these to the spec's
   1,727 / 368 collected). Frontend: 37 vitest files (354 `it(`/`test(`
   calls), 9 Playwright specs/setup + 1 fixture.
7. **Q6 cannot ship to today's production.** Q6 code talks only to SQLite, so
   once Q6 merges, `main` cannot run on Render + hosted Supabase. The overview
   says "every phase until Q7 ships to today's production". **UNKNOWN:**
   whether Q6 merges to `main` before Q7 or is held until the cutover — decide
   in the overview; find out by asking the overview author/owner. This section
   assumes Q6 merges and production is **frozen** at the Q5 SHA from the Q6
   merge to the Q7 cutover; §C makes `deploy-production` refuse in that window
   rather than deploy an app that cannot reach its database.

---

## A. Test inventory

Dependency tags: **SB** stubs the supabase-py client (MagicMock `.table()`/
`.rpc()` chains, `mock_supabase_client`, FastAPI `dependency_overrides` of
`get_authenticated_client`/`get_service_role_client`) · **PG** asyncpg pool or
its double (`fake_pg_pool` from `backend/tests/conftest.py:64`) · **LS** local
Supabase over HTTP (PostgREST/GoTrue/Storage via `authenticated_client`,
`admin_client`, `temp_user`) · **PGSQL** executes or reads Postgres-specific
SQL (`pg_pool` against `localhost:54322`, catalog queries, migration files) ·
**SC** schema contract · **GM** real Gmail (marker `gmail`/`development`
with seeded tokens) · **ST** staging-marked (needs staging credentials; never
runs while staging is paused) · **PURE** no database at all · **REPO**
inspects repository files/scripts/workflows.

### A.1 Backend tests outside `integration/` (76 files)

| # | File | Tests (`def test_`) | Depends on | Fate | Phase and what changes |
|---|---|---|---|---|---|
| 1 | `test_acquisition_executor_bound.py` | 5 | PURE (AsyncMock `worker.repository.claim_item/fail_item`, lines 74–116) | **U** | Q6 keeps the `EmailIngestionRepository` method names (`claim_item`, `fail_item`); if the SQLite repository renames them, the patch targets change mechanically |
| 2 | `test_api_routes.py` | 54 | SB (`dependency_overrides`, `mock_client`) | **R** | Q1 adds cases for the ~20 new read/write endpoints; Q5 `TestAuth*` (`test_invalid_token_returns_401` line 356 etc.) verify own JWTs instead of `client.auth.get_user` (`api/deps.py:80`); Q6 overrides a temp-SQLite `db` dependency instead of `mock_client`; health tests 115–319 assert the new `transport`/`database` fields |
| 3 | `test_attachment_type_rejected.py` | 8 | SB (fake `StorageApiError`, line 34) | **R** | Q6: the bucket MIME allowlist disappears; the invariant ("a type that cannot be stored is terminal `unsupported`, one attempt, never dead-letter") is re-asserted against the worker's accept-set before the disk write |
| 4 | `test_attachments.py` | 26 | patches `upload_to_storage`, `get_current_user_id`, `save_attachment_metadata` | **R** | Q6: `upload_to_storage` → atomic file write under `attachments/<user_id>/<attachment_id>`; `get_current_user_id` patch → explicit `user_id` argument |
| 5 | `test_auth.py` | 3 | SB (`get_service_client`, httpx HTTP/2, egress hook) | **X** (Q6) | All three test the supabase service client; replaced by `tests/test_no_supabase_or_asyncpg.py` (B9) and the remaining egress destinations in `test_egress.py`. Safe: there is no database host to meter |
| 6 | `test_automatic_cancellation_migration.py` | 1 | PGSQL (reads `supabase/migrations/20260813000004_automatic_cancellation.sql`) | **D** (Q6) | Pins legacy `events.status` values inside a historical migration; `events.status` no longer exists (`20260829000001`), and `0001_initial.sql` is written from the live schema. Successor of the live rule: `test_events_has_exactly_one_state_owner` (A.3 #19) |
| 7 | `test_backfill_calendar_components.py` | 7 | SB (table mocks for `scripts/backfill_calendar_components.py`) | **D** (Q6, conditional) | Deleted with the one-off I5 ICS backfill script once the backfill is recorded as run on production. **UNKNOWN:** whether it ran — find out in `docs/specs/event-identity-reach.md` I5 status and the deploy logs. If it has not run, run it before Q7 (it targets Postgres) and delete both in Q6 |
| 8 | `test_calendar_components.py` | 4 | 1 test PGSQL (reads `20260819000001_calendar_components.sql`), 3 PURE | **R** (Q6) | `test_c1_migration_secures_components_and_preserves_on_empty_resave` deleted; its behaviour ("an empty component payload never erases an earlier parse") moves to `tests/db/test_email_writes.py::test_empty_component_payload_preserves_earlier_parse`; the 3 parser tests U |
| 9 | `test_calendar_identity_match.py` | 7 | PURE | **U** | — |
| 10 | `test_calendar_mirror.py` | 23 | SB (1 `table.return_value`, PostgREST row cap) | **R** (Q6) | The mirror write path uses `selko.db.calendar_entries`; the PostgREST row-cap paging test is deleted (no row cap) |
| 11 | `test_calendar_policy.py` | 16 | SB (`events_table`/`sources_table` mocks, line 192) | **R** (Q6) | The skip-budget test `TestCreateEventSourceMaterializedSplit::test_create_event_stores_source_in_extracted_data` is deleted with its `skip_budget.toml` entry; the rest U |
| 12 | `test_calendars.py` | 40 | SB + PG (14 `fake_pg_pool`, 54 `mock_client`) | **R** (Q6) | Calendar settings and work-item calls through a temp SQLite db; the 2 `TestRemovedInlineCancellation` skip-budget tests deleted |
| 13 | `test_civil_time.py` | 5 | PURE | **U** | — |
| 14 | `test_cleanup_review_incident.py` | 14 | REPO (imports `scripts/cleanup_review_incident_20260713.py`; PostgREST row-cap test line 29) | **D** (Q6) | Deleted with the 2026-07-13 incident script, which can only run against PostgREST; the incident is closed |
| 15 | `test_config.py` | 46 | SB config fields (47 `SUPABASE` mentions), ST env names | **R** | Q5 adds the JWT secret (required at startup; missing ⇒ refuse); Q6 adds the data directory, removes `supabase_*`/`SUPABASE_DB_URL` fields; Q8 drops `.env.test`/staging resolution |
| 16 | `test_declined_event_terminality.py` | 7 | SB (`fake_commit(client, ...)`, line 43) | **R** (Q6) | `fake_commit` signature becomes the `selko.db` commit function's; assertions unchanged |
| 17 | `test_egress.py` | 11 | REPO + `SUPABASE` destination constant | **R** (Q6) | `SUPABASE` destination removed from `selko/services/egress.py:38`; the AST test at line 66 keeps checking Graph operations |
| 18 | `test_egress_budget.py` | 3 | PURE (patches worker) | **R** (Q6) | "health database call budget" now counts local SQLite calls; the budget (one evaluation per floor interval) is unchanged |
| 19 | `test_email_body.py` | 17 | PURE | **U** | — |
| 20 | `test_email_images.py` | 26 | PURE | **U** | — |
| 21 | `test_email_ingestion_v2.py` | 53 | PG (69 `fake_pg_pool`), SB | **R** (Q6) | Repository runs against a temp SQLite file; `test_dead_letter_scan_pages_past_the_postgrest_row_cap` (line 390) becomes a plain >1,000-row count test; `test_no_acquisition_failure_is_terminal_on_first_attempt` U in intent |
| 22 | `test_emails.py` | 28 | SB in save tests, PURE parse tests | **R** (Q6) | `save_emails` through `selko.db`; parsers U |
| 23 | `test_error_responses.py` | 10 | PURE | **U** | — |
| 24 | `test_eval.py` | 30 | PURE | **U** | — |
| 25 | `test_eval_identity.py` | 20 | PURE | **U** | — |
| 26 | `test_event_diff.py` | 28 | PURE | **U** | — |
| 27 | `test_event_identity.py` | 8 | 1 test PGSQL (`20260820000001_identity_hints_and_fence.sql`, line 51), rest PURE | **R** (Q6) | Migration-text test deleted; the hint fence is proven by `test_integration_identity_mirror_fence.py`/`test_integration_event_identity.py` successors on SQLite |
| 28 | `test_event_processing.py` | 37 | Config fixtures with `supabase_url` | **R** (Q8) | Fixture config drops Supabase fields |
| 29 | `test_events.py` | 37 | SB (79 `mock_client`, 31 `table.return_value`) | **R** (Q6) | Temp SQLite; 5 skip-budget tests (`TestGenerateSourceAttribution::test_skips_undone_sources`, `TestUpdateEventResync::*`, `TestRedoEmailContribution::*`, `TestCreateEventFromGCalMatch::*`) deleted with their budget entries |
| 30 | `test_events_refactor.py` | 50 | SB (101 `mock_client`) | **R** (Q6) | `save_extracted_events`/`process_email_for_events` against a temp db; the stubbed `_commit_email_extraction` becomes the real function (this is the class of stub #332 hid behind) |
| 31 | `test_extraction_decision_intent.py` | 3 | REPO (AST over `backend/selko/services/events.py`) | **U** | Stays valid while decision dicts are built in `services/events.py`. If Q6 moves that code, update `EVENTS` (line ~19) in the same PR and assert the file exists |
| 32 | `test_fenced_event_commit.py` | 1 | SB (`client.rpc` returning `{"fenced": True}`) | **R** (Q6) | Calls `selko.db` commit with a stale generation against a real temp db |
| 33 | `test_format_conversion.py` | 40 | PURE | **U** | — |
| 34 | `test_gate_contract.py` | 11 | REPO (`verify.sh`, `verify-staging.sh`, manifest writer, workflows) | **R** (Q4, Q6, Q8) | See §A.7 "gate contract" |
| 35 | `test_gmail.py` | 10 | SB (`mock_supabase_client.table()...maybe_single()`, line 89) | **R** (Q6) | `get_oauth_credentials` reads `integrations` from a temp db |
| 36 | `test_health_endpoints.py` | 5 | PG (`test_transport_probe_*`, lines 55, 80) | **R** (Q6) | Transport probe tests become SQLite probe tests: a db that cannot answer reports unavailable; the probe is time-bounded |
| 37 | `test_ics_parser.py` | 23 | PURE | **U** | — |
| 38 | `test_ingestion_runtime.py` | 27 | PG + SB (`build_notifier`, lifespan wiring) | **R** (Q2, Q6) | Q2: lifespan also starts the `/live` fan-out; Q6: lifespan opens the SQLite writer, resets leases (B5) and wires the event bus instead of `WorkListener`; `test_no_apscheduler_remains_in_the_api_module` (line 256) U |
| 39 | `test_integrations.py` | 34 | SB + PG (42 supabase mentions, `postgrest.APIError`) | **R** (Q6) | Temp db; `APIError` handling replaced by `sqlite3.IntegrityError` classification |
| 40 | `test_late_calendar_match.py` | 9 | SB (`_FakeClient`, line ~11) | **R** (Q6) | The hand-written PostgREST fake is deleted; real temp db |
| 41 | `test_llm_gateway.py` | 22 | PURE (logging and quota services are mocks) | **U** | — |
| 42 | `test_llm_gateway_fallback.py` | 11 | PURE | **U** | — |
| 43 | `test_llm_provider.py` | 89 | PURE | **U** | — |
| 44 | `test_memory_monitor.py` | 10 | PURE | **U** | — |
| 45 | `test_ops.py` | 14 | REPO (`scripts/ops.py` ↔ `ops.yml`) | **R** (Q6, Q7, Q8) | Tracks each operation's removal/rewrite (§C.7); `test_production_jobs_never_run_concurrently` and `test_every_action_is_pinned_by_full_sha` U |
| 46 | `test_outlook.py` | 11 | SB (`client.table()...maybe_single()`, line 171) | **R** (Q6) | `get_access_token` reads from temp db |
| 47 | `test_outlook_calendar.py` | 39 | PG + SB (`patch.object(pool_module …)`) | **R** (Q6) | Pool double → temp db; adapter tests U |
| 48 | `test_packaging.py` | 1 | REPO | **U** | — |
| 49 | `test_pg.py` | 13 | PG (session-mode URL guard, keepalives, `WorkListener`) | **X** (Q6) | Deleted with `selko/services/pg.py`. Successors: `tests/db/test_connection.py` (WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000` asserted on every opened connection) and `tests/db/test_event_bus.py` (B6) for `test_listener_sets_event_for_payload`/`test_heartbeat_payload_does_not_set_work_events` |
| 50 | `test_photos.py` | 28 | SB + PG (62 supabase mentions) | **R** (Q6) | Ported with the photo functions (spec §4.3: one Python function per current function). If the owner instead deletes parked photo ingestion (a product decision not yet made), this file is D with the code and `photos`/`scheduled_tasks.task_type='photo_fetch'` leave `EXPECTED_CHECK_DOMAINS` |
| 51 | `test_propose_event_update.py` | 5 | PURE | **U** | — |
| 52 | `test_prune_eval_results.py` | 2 | REPO | **U** | — |
| 53 | `test_reachability.py` | 1 | REPO (AST import graph) | **R** (Q6) | §A.7 |
| 54 | `test_reliability.py` | 21 | PG (6 `fake_pg_pool`) | **R** (Q6) | Dead-letter/backoff via temp db; circuit breaker tests U |
| 55 | `test_reliable_email_history.py` | 11 | SB + PG (`client.rpc`, `table.return_value`) | **R** (Q6) | `set_folder_preference` (today RPC `set_email_folder_preference`) against temp db |
| 56 | `test_repair_review_queue_integrity.py` | 7 | REPO + PGSQL (line 27 reads `20260818000001_repair_event_cancellation.sql`) | **R** (Q6/Q7) | Migration-text test deleted; the tool's fail-closed rules (manifest, confirmed user, dry-run default) re-tested against the SQLite version of the tool that runs on the server (§C.7) |
| 57 | `test_resolution_metrics.py` | 1 | PURE | **U** | — |
| 58 | `test_retry_utils.py` | 8 | PURE | **U** | — |
| 59 | `test_scheduled_tasks.py` | 25 | SB + PG (70 `mock_client`, 16 `fake_pg_pool`) | **R** (Q6) | Temp db (or D with the photo decision, row 50) |
| 60 | `test_scripts.py` | 16 | REPO (`assert-schema-code-compat.sh`, `check-migration-order.sh`) | **R** (Q6, Q8) | Q6 adds the SQLite chain cases to `TestCheckMigrationOrder`; Q8 deletes `TestFindMissingVersions`/`TestAssertSchemaCodeCompat*` with `assert-schema-code-compat.sh` |
| 61 | `test_security.py` | 13 | SB (`.rpc` quota mocks) | **R** (Q6) | Quota calls through `selko.db.quotas` |
| 62 | `test_seed_test_tokens.py` | 10 | SB + ST (dev↔staging copy) | **D** (Q8) | Deleted with `scripts/seed_test_tokens.py` when the staging project is deleted; until then U. The production-refusal guard it pins is moot when no tool copies tokens between databases |
| 63 | `test_selko_managed_updates.py` | 8 | SB (`client.table.return_value.select`, line 119) | **R** (Q6) | `_is_from_users_calendar` against temp db |
| 64 | `test_sender_rule_migrations.py` | 3 | PGSQL (reads `20260713000001_ignore_sender_retroactive.sql`) | **X** (Q6) | Replaced by `tests/db/test_sender_rules.py::test_deleting_an_ignore_rule_resets_its_skipped_emails` and `::test_ignore_rule_never_touches_calendar_invites` (behaviour of `sender_rule_before_delete`/`reset_skipped_emails_for_sender_rule`, executed) |
| 65 | `test_spec_status.py` | 4 | REPO | **U** | Each increment updates spec front matter (§D.5); the test itself is unchanged |
| 66 | `test_staging_verifier.py` | 2 | REPO (`verify.sh staging`, `verify-staging.sh`) | **D** (Q6) | Deleted with `verify-staging.sh` and the `staging` mode of `verify.sh`: no staging environment can run the SQLite build. Successor gate: the image lane (B10) |
| 67 | `test_state_ownership_s5.py` | 4 | REPO (AST over calendar worker/helpers) | **R** (Q6) | Functions take a `db` handle instead of `pg_pool`; the "typed lease is dispatched with every write" assertions unchanged |
| 68 | `test_thread_identity_rung.py` | 5 | PURE | **U** | — |
| 69 | `test_verify_lanes.py` | 10 | REPO (runner) | **U** | `test_the_repository_lanes_declare_only_inputs_that_exist` (line 256) is what forces each lanes.toml edit in §C.1 to land in the same PR as the files it names |
| 70 | `test_workers.py` | 58 | PG + SB (218 mocks, 65 pool refs) | **R** (Q1 hygiene, Q6) | Q1: delete the shadowed duplicate block (§0.1). Q6: pool double → temp db; guards per §A.7 |
| 71 | `unit/test_calendar_drift.py` | 10 | PURE (Google event mocks) | **U** | — |
| 72 | `unit/test_civil_time.py` | 10 | PURE | **U** | — |
| 73 | `unit/test_quota_service.py` | 19 | SB (13 `.rpc.`) | **R** (Q6) | `QuotaService` over `selko.db.quotas` |
| 74 | `unit/test_timezone.py` | 17 | SB (`get_user_timezone(mock_client, …)`) | **R** (Q6) | Temp db with `user_calendar_settings` row |
| 75 | `unit/test_undo_history_event.py` | 7 | SB (8 `.rpc.`, 32 `mock_client`) | **R** (Q6) | Real proposal/undo functions against temp db; Google client still mocked |
| 76 | `drills/test_acceptance_drill.py` | 10 | ST + PGSQL (composes integration tests, `drill` marker, staging) | **X** (Q6) | The drill exists because staging was the only real-Postgres-with-pooler target. Once the test engine is the production engine, the ten composed tests run in Tier 1 every time. Deleted with `drills/conftest.py`; spec front matter `drills = [...]` entries re-pointed (§D.5) |

Totals for A.1: **U 26 · R 41 · X 4 · D 5** (76 files).

### A.2 Backend integration tests (`backend/tests/integration/`, 43 files)

All use `integration/conftest.py` fixtures: `pg_pool` (asyncpg to
`localhost:54322`, line 102), `authenticated_client`, `admin_client`,
`temp_user` (GoTrue admin, line 188), `temp_user_client`. "Temp SQLite" below
means the Q6 replacement conftest: one file per test (`tmp_path`), every
migration in `backend/selko/db/migrations/` applied by the real runner, users
created through `selko.db.accounts` (Q5 shape), no Docker.

| # | File | Tests | Depends on | Fate | Phase and what changes |
|---|---|---|---|---|---|
| 1 | `test_broadcast_fanout.py` | 2 | PGSQL (`realtime.send` triggers) | **X** | Q2: replaced by `tests/integration/test_live_invalidations.py::test_bulk_update_emits_one_invalidation_per_resource` (pg_notify feed, Postgres); Q6: by `tests/db/test_event_bus.py::test_one_invalidation_per_resource_per_transaction` |
| 2 | `test_integration_api.py` | 36 | LS (JWT from GoTrue) | **R** | Q1 data endpoints added (the docstring's "data endpoints removed" stops being true); Q5 tokens from `/auth/token`; Q6 temp SQLite. CORS tests 397–508 U; `test_apply_change_*` (577, 595) U in intent |
| 3 | `test_integration_attachment_mime_contract.py` | 5 | PGSQL (`storage.buckets.allowed_mime_types` vs worker accept-set) | **X** (Q6) | Two allowlists become one. Replaced by `tests/db/test_attachment_store.py::test_every_type_the_worker_accepts_is_stored` (parametrized over the accept-set, writes and reads back each) and `::test_the_store_refuses_a_type_outside_the_accept_set` (keeps "the matcher itself can fail") |
| 4 | `test_integration_attachments.py` | 11 | LS (Storage), GM (`test_gmail_attachment_full_pipeline`), ST (`test_upload_and_retrieve_staging`) | **R** (Q6) | Storage → disk; `test_user_sees_only_own_attachments` moves into the ownership matrix (B1); staging test deleted; GM test keeps the `gmail` marker |
| 5 | `test_integration_auth.py` | 8 | LS (GoTrue sign-in), ST | **X** (Q5) | Replaced by `tests/integration/test_auth_api.py` (B8); staging tests deleted |
| 6 | `test_integration_automatic_cancellation.py` | 2 | LS + PG | **R** (Q6) | Claim/complete cancellation via `selko.db.calendar_work` on temp SQLite. Node `TestAutomaticCancellation::test_stale_upsert_completion_cannot_reset_cancellation` is named in `calendar-identity-and-cancellation.md` front matter: keep the node id |
| 7 | `test_integration_calendar_components.py` | 1 | LS | **R** (Q6) | — |
| 8 | `test_integration_calendar_recovery_worker.py` | 7 | LS + PG | **R** (Q6) | — |
| 9 | `test_integration_calendar_work_items.py` | 4 | LS + PG | **R** (Q6) | Keep node `test_enqueue_claim_complete_is_item_fenced` (state-ownership spec front matter) |
| 10 | `test_integration_calendars.py` | 11 | LS (1 `skip`) | **R** (Q6) | — |
| 11 | `test_integration_data_api_grants.py` | 4 | LS (PostgREST grants per role, `postgrest.APIError`) | **X** | Q3: replaced on Postgres by `tests/integration/test_api_roles_have_no_privileges.py` (anon and authenticated hold no table/function privilege once no client uses PostgREST, §B.1a); Q6: deleted, no database roles exist. Owner-reachability of the profile is in the ownership matrix |
| 12 | `test_integration_e2e.py` | 4 | LS + GM + ST | **R** (Q6) | `test_user_data_cascade_delete` (135) keeps proving `ON DELETE CASCADE` with `foreign_keys=ON`; staging test deleted; GM tests keep marker |
| 13 | `test_integration_email_ingestion_v2.py` | 11 | LS (60 supabase refs) | **R** (Q6) | Every claim/heartbeat/complete/fail test executes the Python functions; `test_only_one_worker_owns_an_integration_and_expired_leases_return` keeps lease expiry within a run (startup reset is additional, B5) |
| 14 | `test_integration_email_state_machine.py` | 15 | LS | **R** (Q6) | Node `TestDurableEmailStateMachine::test_expired_processing_email_is_reclaimed_without_restart` kept (state-ownership front matter). `test_pending_email_cannot_equal_max_attempts` (150) becomes a SQLite CHECK test; `test_one_running_run_per_integration_is_a_database_invariant` (402) a partial unique index test |
| 15 | `test_integration_emails.py` | 14 | LS + ST; `test_gmail_labels_trigger*` (161–224) exercise `parse_provider_labels_trigger` | **R** (Q6) | Label parsing trigger → Python in the email writer (or SQLite trigger, per 01-schema); the three label tests executed against temp db; `test_rls_user_isolation` → ownership matrix; staging tests deleted |
| 16 | `test_integration_event_change_proposals.py` | 2 | LS | **R** (Q6) | Proposal invariants (01-schema HAND 4/5: end-of-transaction `_assert_proposal_invariants`) |
| 17 | `test_integration_event_identity.py` | 2 | PG | **R** (Q6) | Keep node `test_hint_lookup_is_part_of_the_commit_fence` |
| 18 | `test_integration_event_processing.py` | 10 | LS + `llm` | **R** (Q6) | DB fetch path via temp db; LLM tests keep the `llm` marker |
| 19 | `test_integration_events.py` | 17 | LS + PG + PGSQL | **R** (Q6) | `test_delete_events_status_backfill_preserves_every_legacy_status` (713) **deleted** (Postgres migration history; named in `grant-integrity-and-cutover-safety.md` front matter, which is updated); `test_events_has_exactly_one_state_owner` (760) R against `sqlite_master`; `test_no_rpc_signature_carries_the_deleted_delivery_vocabulary` (777) R as an `inspect.signature` scan of every `selko.db` function |
| 20 | `test_integration_extraction_intent.py` | 12 | PG (103 pool refs) | **R** (Q6) | Critical: every test executes `commit_email_extraction` itself — must stay true for the Python port |
| 21 | `test_integration_fenced_event_commit.py` | 8 | PG | **R** (Q6) | Keep nodes `test_python_and_sql_fingerprints_agree` (now: the commit-time fingerprint and the decision-time fingerprint are computed by the same function over rows read inside the writer transaction; the test must still be able to fail by mutating a row between the two) and `test_stale_fingerprint_returns_conflict_and_mutates_nothing` |
| 22 | `test_integration_gmail.py` | 10 | GM + ST | **R** (Q6) | Credentials read from temp db seeded with the dev token; staging half deleted (§C.3 on the token source) |
| 23 | `test_integration_grant_posture.py` | 2 | ST (`staging_pg_pool`) | **D** (Q3) | Staging-only, has not run since staging was paused. Superseded on Postgres by §B.1a (local, runs every Tier 1) and made moot at Q7 (no roles) |
| 24 | `test_integration_graph_ledger.py` | 1 | LS | **R** (Q6) | — |
| 25 | `test_integration_hint_upsert.py` | 2 | LS | **R** (Q6) | Still meaningful: SQLite also requires an upsert's conflict target to repeat a partial index's `WHERE`. `test_hint_upsert_can_infer_its_conflict_target` must execute the real upsert |
| 26 | `test_integration_identity_hint_coverage.py` | 2 | LS | **R** (Q6) | Keep node `test_ordinary_email_yields_a_provider_thread_hint` |
| 27 | `test_integration_identity_mirror_fence.py` | 2 | LS | **R** (Q6) | — |
| 28 | `test_integration_ingestion_drill.py` | 5 | LS | **R** (Q6) | `test_expired_lease_is_claimable` kept; add crash variant in B5 |
| 29 | `test_integration_ingestion_stall_signal.py` | 5 | PG (`health_work_state`) | **R** (Q6) | `health_work_state` as a Python function; `test_it_returns_to_green_when_the_backlog_drains` (194) is the "can return to green" proof — keep |
| 30 | `test_integration_late_calendar_match.py` | 2 | LS | **R** (Q6) | — |
| 31 | `test_integration_oauth.py` | 13 | LS + ST | **R** (Q6) | The four `test_authenticated_session_*` tests (201–253) about column grants on token columns are replaced by `tests/test_client_payloads.py::test_no_client_endpoint_serializes_a_token_column` (every response model of every client route is checked against the token column names `access_token`, `refresh_token`, …); staging test deleted |
| 32 | `test_integration_outlook_calendar.py` | 8 | LS + PG | **R** (Q6) | — |
| 33 | `test_integration_recovery.py` | 8 | LS + PG | **R** (Q6) | Keep node `TestCompleteIntegrationReauthorization::test_upserts_credentials_and_creates_calendar_recovery`; `test_user_can_read_own_recovery_but_not_write_it` → ownership matrix (`GET` recoveries) + route inventory (no write route) |
| 34 | `test_integration_revive_mime_dead_letters.py` | 5 | PGSQL (executes `20261019000002`) | **D** (Q6) | A one-shot data repair already applied in production; the import (Q7) carries its result, and the SQLite chain never contains it |
| 35 | `test_integration_rls_security.py` | 8 | LS + ST | **X** | Q3: replaced by the ownership matrix (B1) while still on Postgres — both run through Q5 because PostgREST stays publicly reachable until Q7; Q6: deleted (needs PostgREST) |
| 36 | `test_integration_seed_fixtures.py` | 1 | LS (`list_users` via GoTrue admin) | **R** (Q5, Q6) | Q5 lists `accounts`; Q6 reads the temp data dir the seed wrote |
| 37 | `test_integration_users.py` | 10 | LS (GoTrue admin), ST | **X** (Q5) | Replaced by `tests/integration/test_accounts.py` (create/list/get/delete, duplicate email refused, `users` profile row created with the account — successor of `handle_new_user`); staging tests deleted |
| 38 | `test_integration_work_listener.py` | 5 | PGSQL (LISTEN/NOTIFY) | **X** (Q6) | Replaced by `tests/db/test_event_bus.py` (B6). `test_durability_missed_notification_costs_latency_never_work` → `::test_missed_wakeup_costs_latency_not_work`; `test_d3_two_listeners_one_notification_one_claim` → B4 concurrency |
| 39 | `test_integration_worker_pool_port.py` | 13 | PG (`SELECT * FROM public.fn($1,…)` forms, jsonb casts) | **X** (Q6) | Replaced by `tests/db/test_db_functions_contract.py`: one test per ported function, generated coverage check (§A.7 "schema contract", item c) |
| 40 | `test_integration_workers.py` | 18 | LS + PG | **R** (Q6) | `test_concurrent_workers_no_duplicate_*` (197, 417) and `test_multiple_workers_get_different_*` (678, 708) become asyncio-concurrency tests over the single writer (B4) |
| 41 | `test_llm_logging.py` | 13 | LS | **R** (Q6) | `test_user_cannot_view_other_user_logs` → ownership matrix if a client route exposes logs; otherwise route inventory proves no client route does |
| 42 | `test_rate_limiting.py` | 16 | LS | **R** (Q6) | Quota tables/functions in `selko.db`; `test_quota_rpcs_are_denied_to_a_signed_in_user` (112) → route inventory: no client route mutates `usage_quotas`/`global_limits`; slowapi header tests U |
| 43 | `test_schema_contract.py` | 11 | SC + PGSQL (catalog queries) | **X** (Q1 partial, Q6) | §A.7 |

Totals for A.2: **U 0 · R 32 · X 9 · D 2** (43 files).

### A.3 Frontend unit tests (37 files)

13 files mention `supabase` (spec §2 count matches): `Navbar`,
`services/integrations`, `services/events`, `services/emails`,
`live-updates`, `email-history`, `errors`, `services`, `backend-api`,
`app/layout`, `app/settings/page`, `login/page`, `privacy/page`.

| File (under `frontend/src/`) | Depends on | Fate | Phase and what changes |
|---|---|---|---|
| `lib/components/__tests__/{EventCard,DispositionedCard,ChangeCard,ErrorAlert,EmptyState,LoadingSpinner,IntegrationStatus,DesignTokenContract,LabeledSwitch,ConnectionRecovery,StatusBadge,SenderRulesPanel,SenderHeader}.test.js` (13) | props/mocked services | **U** | Field names of API DTOs are kept identical to today's row shapes in Q1 so these stay unchanged; any renamed field is a Q1 change to the component and its test together |
| `lib/components/__tests__/Navbar.test.js` | mocks `$lib/stores.js` because `stores.js → supabase.js` needs env (line 23) | **R** (Q5) | Mock goes when `stores.js` no longer imports `supabase.js` |
| `lib/services/__tests__/integrations.test.js`, `events.test.js`, `emails.test.js` | stub supabase client | **R** (Q1) | Stub the API `fetch` client instead (assert method, path, body, and error envelope `{error, detail}`) |
| `lib/__tests__/services.test.js` | 12 `.from`/`.rpc`/`storage` stubs (attachments signed URL, calendar settings upsert, sender rules, event sources) | **R** (Q1) | Attachment download through the API (`GET /attachments/{id}`), `getAttachmentUrl` signed-URL tests (lines 100–130) replaced by an authenticated download test |
| `lib/__tests__/email-history.test.js` | stub `.select` with embedded relations | **R** (Q1) | API pagination contract |
| `lib/__tests__/live-updates.test.js` | stub Realtime channel (22 refs) | **R** (Q2) | Streaming-fetch SSE client: reconnect backoff keeps `rejoinAttempts` at module scope (F1.1), catch-up refetch on reconnect, token refresh restarts the stream, payload-only invalidation |
| `lib/__tests__/errors.test.js` | `SupabaseError`/`parseSupabaseError` | **R** (Q1, finished Q5) | `ApiError` parsing the API envelope; Supabase/PostgREST/GoTrue code mapping deleted when the last caller goes (Q5) |
| `lib/__tests__/backend-api.test.js` | token from the Supabase session | **R** (Q5) | Token from own auth store; 401 → one refresh-and-retry, never a loop |
| `routes/app/__tests__/layout.test.js` | supabase auth + live updates | **R** (Q2, Q5) | — |
| `routes/app/settings/__tests__/page.test.js` | 2 supabase refs | **R** (Q1) | — |
| `routes/login/__tests__/page.test.js` | mocks `$lib/supabase.js` (line 14) | **R** (Q5) | Mocks own auth (`POST /auth/token`) |
| `routes/privacy/__tests__/page.test.js` | `names every service provider…` asserts `Supabase:` and `Render:` (line 27) | **R** (Q7, Q8) | §D.4 |
| `lib/__tests__/{calendar-providers,translate-only-flip,safe-redirect,event-sender,review-queue-order,format-event-datetime,google-connection,format-change-value}.test.js` (8) | PURE | **U** | — |
| `routes/app/history/__tests__/page.test.js`, `routes/app/__tests__/page.test.js`, `routes/app/events/[id]/__tests__/page.test.js` (3) | `vi.mock('$lib/services/...')`, `$lib/api/backend.js` | **U** | Service module signatures are kept in Q1; only the implementations behind them change |

Totals for A.3: **U 24 · R 13 · X 0 · D 0** (37 files).

### A.4 Frontend e2e (`frontend/tests/e2e/`, 10 files)

`auth.setup.ts`, `auth.spec.ts`, `event-detail.spec.ts`, `history.spec.ts`,
`navigation.spec.ts`, `responsiveness.spec.ts`, `review-queue.spec.ts`,
`screenshots.spec.ts`, `settings.spec.ts`, `fixtures/auth.ts`. They drive the
UI only (no supabase calls; `storageState` only). Depend on: Vite dev server
(`playwright.config.ts` `baseURL: http://localhost:5173`, `webServer: npm run
dev`), the API on :8000, seeded local Supabase. **Fate: U (10)** in content;
the harness changes: Q4 `playwright.config.ts` takes `BASE_URL` and skips
`webServer` when it is set, so the image lane can point it at the container;
Q4 `auth.setup.ts` reads `E2E_EMAIL`/`E2E_PASSWORD` (§0.4); Q5 the saved
`storageState` holds Selko's own session instead of the `sb-*` key (no test
edit, the setup re-runs). `screenshots.spec.ts` runs through
`scripts/capture-web-screenshots.sh` (`npx playwright test screenshots
--project=screenshots`).

### A.5 Counts by fate

| Group | Files | U | R | X | D |
|---|---|---|---|---|---|
| Backend outside `integration/` (A.1) | 76 | 26 | 41 | 4 | 5 |
| Backend `integration/` (A.2) | 43 | 0 | 32 | 9 | 2 |
| Frontend unit (A.3) | 37 | 24 | 13 | 0 | 0 |
| Frontend e2e (A.4) | 10 | 10 | 0 | 0 | 0 |
| **All** | **166** | **60** | **86** | **13** | **7** |

Non-test files that change with them: `backend/tests/conftest.py`
(`mock_supabase_client`, `fake_pg_pool` deleted in Q6; `tmp_db` fixture
added), `backend/tests/integration/conftest.py` (rewritten in Q6),
`backend/tests/drills/conftest.py` (deleted Q6), `backend/tests/skip_budget.toml`
(54 entries; the S5 characterization entries deleted with their tests in Q6 —
the manifest writer fails on an unlisted skip, so the budget and the tests
must change in the same PR), pytest markers in `backend/pyproject.toml`
(`development`, `staging`, `drill`, `production` lose meaning; §C.3).

### A.6 How a rewritten test is accepted

A rewrite is accepted only when it is shown able to fail. For every R/X file
in Q6 the PR records, in its body, one mutation per file that turned the test
red (e.g. "removed the `lock_generation` comparison in
`selko/db/emails.py::fail_email_processing` → 3 tests red"). This is the
direct application of "if this were broken right now, would this check
actually go red?" to the largest single rewrite in the project's history.

### A.7 Guards CLAUDE.md names, and each one's successor

| Guard today | What it protects | Successor (name, phase) | Notes so nothing is lost silently |
|---|---|---|---|
| `tests/test_reachability.py::test_every_worker_and_service_module_is_reachable` (line 97; `RUNTIME_ROOTS` line 10 includes `selko.worker_app`; scans `selko.services.`/`selko.workers.`) | no module without callers | Same test, **R in Q6**: `RUNTIME_ROOTS = {"selko.api", "selko.api.app", "selko.__main__"}` (the single-process entrypoint; `selko.worker_app` is deleted — it existed for staging drills); scanned prefixes add `selko.db.` and `selko.auth.` | `DELIBERATELY_UNREACHABLE` keeps the photo entries or loses them with the photo decision. Add `test_scanned_prefixes_exist` (each prefix matches ≥1 module) so a renamed package can't make the guard vacuous |
| `tests/test_workers.py::TestSingleTransportWiring::test_no_worker_module_retains_a_postgrest_fallback` (live copy line 875; regex `_via_pool\|if .*pg_pool is not None`) | one implementation per operation | **X in Q6** by `tests/test_no_supabase_or_asyncpg.py` (B9) **plus** `tests/test_single_data_layer.py::test_no_module_outside_selko_db_executes_sql` (AST: `execute`/`executemany`/`executescript` calls and `sqlite3` imports occur only under `backend/selko/db/`) and `::test_no_db_function_has_a_twin` (no two functions in `selko.db` whose names differ only by a `_via_*`/`_legacy`/`_v2` suffix) | Spec Q6 names the first successor; the second keeps the rule's intent ("one data layer"), which a non-importability test alone does not |
| `tests/test_workers.py::test_no_compat_shims_in_workers` (line 1371) | delete, don't deprecate | **U**, root resolved from `__file__`, scope widened to `backend/selko/` (the Q6 port is exactly where "kept for compat" would appear) | §0.2 |
| `tests/test_workers.py::TestSingleTransportWiring::test_worker_pool_claims_over_the_pool` (live copy line 866) | an injected dependency actually reaches the call | **R in Q6**: `test_worker_pool_claims_through_the_db_layer` — builds the real `WorkerPool` over a temp db holding one approved event, runs `_process_any_work`, asserts the work item moved to `processing` with the worker's id (a row change, not a recorded SQL string) | Strictly stronger: today it asserts a SQL string was recorded by a fake |
| `tests/test_workers.py::test_event_writes_go_through_commit_rpc` (line 1382) and the shadowed copy | no direct `events` inserts outside the fenced commit | **R in Q6**: `tests/test_single_data_layer.py::test_events_are_written_only_by_the_commit_function` — AST over `backend/selko/` for SQL string literals matching `INSERT\s+INTO\s+events\b` / `UPDATE\s+events\b` and calls to `selko.db.events` writers; allowlist = the functions in `selko/db/events.py` that implement `commit_email_extraction` and the named review transitions, each with a reason | The old check looks for `.table("events").insert(`, which no Q6 code contains — left as is it would pass forever. 01-schema HAND 4/5 adds the same AST guard for `event_change_proposals` |
| `tests/test_extraction_decision_intent.py` (AST guard over `save_extracted_events` decisions) | every decision states `intent` | **U** (§A.1 #31) + `commit_email_extraction` in Python keeps raising on a missing `intent`/`fields.review_status`; `tests/db/test_commit_email_extraction.py::test_decision_without_intent_raises` | — |
| `tests/test_state_ownership_s5.py` (4 AST guards) | calendar writes carry the claimed lease | **R in Q6** | — |
| `tests/integration/test_schema_contract.py` (11 tests) | live schema matches what the code assumes | Split, item by item: **(a)** `test_check_constraint_domains_are_pinned` (967) → `backend/tests/test_sqlite_schema.py::test_check_constraint_domains_are_pinned` (parses `sqlite_master.sql` of the applied chain; `EXPECTED_CHECK_DOMAINS` moves to `backend/tests/schema_domains.py`, gains the 4 former enum columns, Q6); **(b)** `test_status_literals_in_python_are_permitted` (996) → U logic, imports the moved dict, enum special case deleted (Q6); **(c)** `test_every_security_definer_function_has_a_contract` (448) → `tests/db/test_db_functions_contract.py::test_every_db_function_has_an_executing_contract` (enumerates public functions of `selko.db.*` modules and requires an entry in `FUNCTION_CONTRACTS` that executes it against a populated temp db and checks the returned shape; an un-contracted function fails by name) (Q6); **(d)** `test_every_public_table_has_rls_enabled` (617) → `test_sqlite_schema.py::test_every_user_owned_table_has_a_non_null_user_id` + B1 ownership matrix (Q3/Q6); **(e)** `test_security_definer_functions_are_not_executable_by_api_roles` (634) and **(f)** `test_default_function_privileges_do_not_grant_api_roles` (682) → kept on Postgres through Q5 (production still has roles), replaced in Q3 by §B.1a, **D in Q6** (no roles); **(g)** `test_live_triggers_for_every_triggered_table` (718) → `test_sqlite_schema.py::test_every_trigger_fires` (each SQLite trigger in `sqlite_master` has a test that fires it) plus `TRIGGER_ONLY_FUNCTIONS` (line 35) mapped to where each now lives (broadcast triggers → event bus B6; `notify_work_available` → bus; `handle_new_user` → accounts; `ensure_email_sync_state` → integration writer; owner/invariant checks → SQLite triggers or `_assert_*` functions) — the mapping is a dict the test asserts is total; **(h)** `test_pending_proposal_requires_active_review_status` (890), **(i)** `test_reject_event_change_proposal_is_one_atomic_transition` (918), **(j)** `test_event_delivery_state_has_no_legacy_status_column` (604) → R on SQLite (Q6); **(k)** `test_frontend_select_columns_exist_in_the_live_schema` (1177) → **D in Q1** (spec: "has nothing left to check") replaced by B9's frontend half (`no-postgrest.test.js`) and `tests/test_client_payloads.py::test_every_client_route_declares_a_response_model` (every non-public route has `response_model`, so DTO fields are a typed contract the frontend can be checked against) | `AUTHENTICATED_EXECUTABLE_FUNCTIONS` (line 57) disappears with (e) in Q6; its four functions become API routes covered by B1 |
| `tests/test_gate_contract.py` (11 tests) | the gate cannot turn missing evidence into green | **R**: `test_gate_has_no_success_by_refusal_or_ignored_failure` (21) iterates `(VERIFY, VERIFY_IMAGE)` from Q6 (`VERIFY_STAGING` deleted); `test_gate_bounds_every_docker_probe` (108), `test_bounded_docker_probe_fails_fast_when_the_daemon_hangs` (138), `test_bounded_docker_probe_passes_through_a_healthy_daemon` (162) follow `bounded_docker` from `verify.sh` into `scripts/verify-image.sh` in Q6 (verify.sh no longer touches Docker; the image lane does); `test_missing_gmail_token_requires_explicit_degradation_flag` (29) stays as long as any real-Gmail coverage is attempted (§C.3); manifest tests (36, 272, 321) U; `test_no_workflow_step_has_env_entries_stranded_inside_its_script` (200) U; add `test_image_lane_fails_closed_without_docker` (Q4) | Node `test_gate_bounds_every_docker_probe` is named in `grant-integrity-and-cutover-safety.md` front matter: the node id is kept by keeping the test name |
| `tests/test_ops.py` (14) | dispatch client ↔ workflow cannot drift | **R** at every ops change (§C.7) | — |
| `tests/test_verify_lanes.py` (10) | the caching runner cannot cache a failure or ignore a missing input | **U** | — |
| `tests/integration/test_integration_rls_security.py`, `test_integration_data_api_grants.py`, `test_integration_grant_posture.py` | cross-tenant isolation; no API-role privilege | B1 (Q3) + §B.1a (Q3) | Both old and new run Q3–Q5 |
| `test_ingestion_runtime.py::test_health_evaluation_has_a_safety_net_floor` (774) | the floor exists | **U** (named in grant-integrity front matter) | — |
| `scripts/assert-health.sh` (no test today) | production invariants | New `tests/test_assert_health.py` (Q2): for each surface, a green fixture passes, each invariant violated alone fails, and a payload missing the field fails (proves every `has(...)`). Extended at Q6/Q7 (§C.9) | Today nothing proves `assert-health.sh` can go red except production |

---

## B. New tests the migration needs

### B.1 Cross-user ownership matrix (Q3; moved to SQLite in Q6)

File: `backend/tests/integration/test_ownership_matrix.py` in Q3 (needs local
Supabase: two `temp_user`s), moved to `backend/tests/test_ownership_matrix.py`
on a temp db in Q6.

- **Route enumeration:** iterate `create_app().routes`; for every `APIRoute`,
  walk `route.dependant` recursively and mark the route *authenticated* if
  `get_current_user` appears. `PUBLIC_ROUTES` is an explicit set of
  `(method, path)` with a reason each (`/health*`, the OAuth callbacks,
  `POST /auth/signup`, `POST /auth/token`, static web). Every authenticated
  route must have an entry in `OWNERSHIP_CASES: dict[tuple[str, str], Case]`.
  `test_every_authenticated_route_has_an_ownership_case` fails naming the
  route — **this is how a new route without coverage goes red.**
  `test_no_case_names_a_route_that_does_not_exist` fails on a stale entry.
  `test_public_routes_take_no_user_input_ids` asserts no public route has an
  `{…_id}` path parameter other than OAuth `state`.
- **Each case** builds user A's resource through application write paths
  (the screenshot seed's helpers), then:
  1. as A: expect 2xx and the resource (proves the 404 below is not vacuous);
  2. as B with A's ids (path, query and body ids): expect **404** with the
     standard error envelope, never 403 and never 200 (no existence leak);
  3. for mutating routes: A's rows are byte-identical before/after B's call
     (snapshot via `selko.db` read helpers in Q6; via service-role client in
     Q3);
  4. list routes: B's response contains none of A's ids, and A's contains
     them.
- **SSE:** `GET /live` as B receives no invalidation for A's writes (B7).
- **Static complement (Q6):** `tests/test_single_data_layer.py::test_every_db_query_function_takes_user_id`
  — AST over `selko/db/*.py`: every public function that reads or writes a
  user-owned table (tables with a `user_id` column, read from the applied
  schema) has a `user_id` parameter used in a `WHERE`. Cross-user worker
  functions (`claim_*`, `unlock_expired_*`, `health_work_state`, lease reset)
  are listed in `CROSS_USER_FUNCTIONS` with a reason and must not be imported
  by any module under `selko/api/routes/` (AST import check). This is the
  RLS replacement the spec §4.3 calls "enforced by a test".

### B.1a API roles hold nothing (Q3, Postgres only)

Once Q1 and Q2 are in production, no client calls PostgREST, Realtime or
Storage, so the anon and authenticated roles need no privilege at all.
Q3 ships a migration revoking every table, sequence and function privilege
from `anon` and `authenticated` in `public` (and Storage object policies),
and `backend/tests/integration/test_api_roles_have_no_privileges.py`:
`test_anon_and_authenticated_hold_no_privilege_in_public` (catalog query over
`information_schema.role_table_grants`, `routine_privileges`),
`test_postgrest_answers_401_or_empty_for_a_signed_in_user` (one real PostgREST
call per table with a GoTrue token). This closes the exposure for the Q3–Q7
window, which the ownership matrix cannot (it tests the API, not PostgREST).
It needs `rehearse-cutover` before deploy (it is a migration on production)
and is deleted in Q6. **Precondition:** GoTrue (Q5) still signs users in;
GoTrue uses its own `supabase_auth_admin` role, which the revoke does not
touch — the test asserts sign-in still works.

### B.2 Migration runner (Q4)

`backend/tests/db/test_migrations.py` (the runner is built in Q4 per spec;
in Q4 it runs against throwaway SQLite files only, since production is still
Postgres):

- `test_fresh_database_applies_every_migration_and_records_hashes` —
  `PRAGMA user_version` equals the number of files; `schema_migrations` has
  one row per file with its SHA-256.
- `test_pending_migration_writes_a_vacuum_into_copy_first` — a database at
  version N with migration N+1 pending: `/data/pre-<sha>.db` exists before
  N+1's first statement (the test migration records `sqlite_master` of the
  copy via a hook), `PRAGMA integrity_check` on the copy is `ok`, and per-table
  checksums of the copy equal the pre-state.
- `test_no_copy_when_nothing_is_pending`.
- `test_failed_migration_rolls_back_and_the_process_exits` — chain of three
  where #2 raises mid-file: `user_version` stays 1, no object from #2 exists,
  no `schema_migrations` row for #2, `python -m selko serve --data-dir <tmp>`
  in a subprocess exits non-zero and never binds its port (probe the port).
- `test_an_applied_migration_that_was_edited_is_refused` — hash mismatch ⇒
  refuse to start with a message naming the file.
- `test_a_database_newer_than_the_code_is_refused` — `user_version` greater
  than the chain ⇒ refuse (this is the rollback-after-migration case); the
  message names the `pre-<sha>.db` to restore.
- `test_restoring_the_pre_copy_lets_the_previous_image_start` — apply N+1,
  restore `pre-<sha>.db`, start code at N: starts, data equals pre-state.
- `test_the_copy_failing_aborts_before_any_migration` — copy target not
  writable (directory `chmod 0500`) ⇒ no migration applied, exit non-zero.
- `test_table_rebuild_migration_keeps_foreign_keys_valid` — a migration using
  SQLite's 12-step rebuild (`PRAGMA foreign_keys` cannot change inside a
  transaction): runner sets it outside, runs `PRAGMA foreign_key_check` before
  commit, and refuses on any violation.
- `test_pre_copies_are_retained_two_deep` — the third migration deploy deletes
  the oldest copy (disk on a 30 GB VM; §C.9 asserts free space).
- `test_health_publishes_the_schema_version` — `/health` includes
  `schema.version` and `schema.head_file`.

### B.3 Import tool verification (Q7; lane `import`, needs local Supabase)

`backend/tests/integration/test_import_from_postgres.py`:

- **Seed:** a local Postgres populated through application write paths
  (`scripts/seed_screenshot_data.py seed` plus the `ContractContext` builder
  from today's `test_schema_contract.py`, which creates a row in every
  table), plus targeted edge rows: NULL in every nullable column; non-ASCII
  text; nested and empty `jsonb`; empty and non-empty arrays (5 columns);
  `timestamptz` with non-UTC offsets and microseconds; `date` and `time`; the
  3 `numeric` columns at their extremes; every enum value; attachment objects
  in local Storage including a zero-byte one; an `auth.users` row per account
  with a GoTrue-made bcrypt hash.
- `test_every_table_is_seeded` — fails if any of the 30 tables (read from
  `information_schema`) has zero rows, so a new table cannot escape the round
  trip.
- `test_row_counts_match_per_table`.
- `test_per_table_checksums_match` — canonical row form (UUID lowercase,
  timestamps UTC ISO 8601 with fixed microsecond precision, JSON with sorted
  keys, arrays as JSON) hashed in primary-key order. The **Postgres side is
  computed in SQL** (`string_agg(... ORDER BY id)`, `to_char(... AT TIME ZONE
  'UTC')`, `jsonb` canonical text) by a query separate from the importer's
  reader, so one codec bug cannot cancel itself out on both sides.
- `test_attachments_match` — count, total bytes, and SHA-256 of each file
  equals the `content_hash` column and the Storage object.
- `test_imported_database_serves_the_same_api_answers` — for the seeded user,
  every Q1 `GET` endpoint's JSON from the Postgres-backed app equals the
  SQLite-backed app's (strongest end-to-end check; ordering normalised).
- `test_existing_password_signs_in_after_import` — `POST /auth/token` with the
  seed password against the imported file.
- `test_checksum_mismatch_fails_the_import` — corrupt one imported row and
  rerun the comparison: non-zero exit naming table and key (the checker can
  fail).
- `test_import_refuses_a_non_empty_target` and
  `test_import_refuses_an_unknown_source_column` (schema drift between
  production and the importer is a stop, not a skip).
- `test_import_is_deterministic` — two imports into fresh files give equal
  checksums.
- `test_imported_file_passes_the_schema_contract` — runs B.2/§A.7 schema
  tests against the imported file, `PRAGMA integrity_check` and
  `foreign_key_check` clean.

Run on the server before the real cutover as a dry run (§E Q7).

### B.4 Single writer and claim concurrency (Q6)

`backend/tests/db/test_writer_concurrency.py`:

- `test_concurrent_claimers_never_share_a_row[<claim function>]` —
  parametrized over every claim function (the 11 former `SKIP LOCKED`
  functions plus the advisory-locked two; the list is taken from
  `selko.db.CLAIM_FUNCTIONS`, and `test_claim_function_list_is_complete`
  compares it with every `selko.db` function whose name starts with `claim_`).
  Seed 20 claimable rows, `asyncio.gather` 50 claim calls (each through
  `asyncio.to_thread`), assert 20 distinct ids, 30 empty results, each row's
  `lock_generation` incremented exactly once. Repeat under 5
  `pytest-randomly` seeds.
- `test_stale_generation_completion_is_a_noop` and
  `test_stale_generation_failure_is_a_noop` — fencing kept (spec §4.3).
- `test_readers_see_committed_state_during_a_long_write` — WAL readers are not
  blocked and never see uncommitted rows.
- `test_external_write_lock_times_out_classified` — a second connection holds
  `BEGIN IMMEDIATE`; the writer waits ~`busy_timeout` and raises a classified
  `DatabaseBusy`, never hangs.
- `test_the_event_loop_never_blocks_on_a_write` — inject a 500 ms sleep in the
  writer thread; a ticker coroutine's lag stays under 50 ms.
- `test_a_failing_function_rolls_back_all_its_writes`.

### B.5 Startup lease reset (Q6)

`backend/tests/db/test_startup_recovery.py`:

- `test_startup_expires_every_lease_before_any_task_starts` — seed
  `processing`/leased rows with future `lock_expires_at` in every leased table;
  start the lifespan with tasks patched to snapshot the db on their first
  call; every lease is expired, rows are claimable, `email_sync_runs.status =
  'running'` became `'abandoned'`, generations advanced (a zombie completion
  would be fenced).
- `test_reset_covers_every_leased_table` — leased tables are derived from the
  applied schema (columns named `locked_by`/`lock_expires_at`/`lease_*`);
  the set handled by the reset must equal it, so a new leased table without
  reset fails.
- `test_killed_process_recovers_its_work` — subprocess `selko serve` claims a
  row, `SIGKILL`, restart, the row completes once (no duplicate side effect
  recorded by the fake provider).

### B.6 Event bus publishes after commit (Q6)

`backend/tests/db/test_event_bus.py`:

- `test_publish_happens_only_after_commit` — at callback time a separate read
  connection already sees the row.
- `test_rolled_back_transaction_publishes_nothing`.
- `test_one_invalidation_per_resource_per_transaction` — 50-row update in one
  transaction ⇒ one hint per `(user, resource)` (successor of
  `test_broadcast_fanout.py::test_bulk_update_emits_one_broadcast_per_resource`);
  `test_distinct_transactions_publish_distinctly`.
- `test_work_wakeup_sets_the_event_for_its_work_type` and
  `test_non_work_publications_wake_nothing` (successors of `test_pg.py`
  listener tests).
- `test_missed_wakeup_costs_latency_not_work` — drop the publication; the
  safety-net floor still claims the row within one floor interval.
- `test_a_slow_subscriber_never_blocks_the_writer` — bounded per-subscriber
  queue; overflow replaces queued hints with one `resync` hint.
- `test_every_former_broadcast_trigger_has_a_publisher` — the 6
  `trg_*_broadcast` and `notify_work_available` names (frozen from today's
  `TRIGGER_ONLY_FUNCTIONS`) map to the writer functions that publish for those
  tables; the test executes each writer and asserts a publication.

### B.7 SSE `/live` (Q2 on `pg_notify`, Q6 on the bus)

`backend/tests/test_live_endpoint.py` (Q2 version in `integration/` because
it needs Postgres `LISTEN`):

- `test_live_requires_a_token` (401 without, 401 with an expired one).
- `test_live_streams_own_invalidations` — write as A, receive
  `{resource, operation, entity_id, occurred_at}` within 2 s; key set exact
  (content-free payload).
- `test_live_never_streams_another_users_changes`.
- `test_live_sends_heartbeats` — comment line at the configured interval so
  proxies keep the stream.
- `test_live_closes_when_the_access_token_expires` (client reconnects with a
  refreshed token; frontend test covers that side).
- `test_disconnect_releases_the_subscriber` — subscriber count returns to 0
  (memory: one process, 400 MB limit).
- `test_fifty_streams_receive_one_write` — no loop stall (ticker lag < 50 ms).
- Q2 only: `test_live_resumes_after_the_listener_reconnects` (kill the
  `LISTEN` socket as `test_integration_work_listener.py::test_h3_dead_socket_reconnects_and_still_delivers` does).

Frontend: `live-updates.test.js` rewrite (A.3). Production check at T+0 of
the Q2 deploy and of Q7: `curl -N -H "Authorization: Bearer …"
https://api.selkoapp.com/live` receives a heartbeat through the proxy within
one interval (Render in Q2, Caddy in Q7: proxy buffering is invisible to
every local test).

### B.8 Auth (Q5)

`backend/tests/integration/test_auth_api.py` (on Postgres `accounts` in Q5,
temp db in Q6) and `backend/tests/test_auth_tokens.py` (pure):

- `test_gotrue_made_bcrypt_hash_verifies` — committed fixture
  `backend/tests/fixtures/auth/gotrue_bcrypt.json` holding a `$2a$10$` hash
  that **GoTrue itself produced** for a throwaway password (made once in Q5
  on local Supabase via the admin API, read from `auth.users.encrypted_password`,
  user deleted; the password is not a secret). Plus the live variant
  `test_hash_copied_from_auth_users_verifies` (creates a local GoTrue user in
  the Q5 suite, runs the `accounts` fill, signs in through `/auth/token`).
  Wrong password fails; `$2b$` accepted.
- `test_accounts_fill_matches_auth_users` — the Q5 migration/fill: counts,
  ids and hashes equal; `id` equals `auth.users.id` so every FK survives.
- `test_password_grant_issues_access_and_refresh` — HS256, `exp - iat = 3600`,
  `sub` = account id.
- `test_wrong_password_and_unknown_email_answer_the_same` — same status and
  body; unknown email still runs a dummy bcrypt compare.
- `test_email_is_matched_case_insensitively`.
- `test_refresh_rotates` — R1 → (A2, R2); R1 is no longer valid after the
  window.
- `test_refresh_reuse_within_10_seconds_is_tolerated` (returns the same
  successor, GoTrue's reuse interval) and
  `test_refresh_reuse_after_the_window_revokes_the_family` (R1 after 10 s ⇒
  401 and R2 is revoked too). Time injected, no sleeps.
- `test_refresh_tokens_are_stored_hashed` — the stored column never equals the
  token.
- `test_logout_revokes_the_refresh_family`.
- `test_rejected_access_tokens` — parametrized: wrong secret, `alg: none`,
  expired, tampered `sub`, a Supabase-issued token (users sign in again after
  Q5) ⇒ 401 each.
- `test_token_endpoint_is_rate_limited` — slowapi 429 after the configured
  burst.
- `test_signup_refuses_a_duplicate_email` and, if Q0 finds confirmation
  required, `test_signup_sends_confirmation_and_blocks_sign_in_until_confirmed`
  (Resend faked at the HTTP boundary).
- `test_missing_jwt_secret_refuses_startup` (configuration is part of the
  change).
- `GET /auth/user` is in the ownership matrix.

### B.9 supabase and asyncpg are not importable from selko (Q6) / clients do not call PostgREST (Q1, Q5)

- `backend/tests/test_no_supabase_or_asyncpg.py::test_selko_imports_no_database_client`
  — a subprocess imports every module under `selko` (walk from `__file__`,
  assert ≥ 1 module found) and asserts none of `supabase`, `postgrest`,
  `gotrue`, `supabase_auth`, `realtime`, `storage3`, `asyncpg`, `psycopg` is in
  `sys.modules`; `::test_no_source_imports_them` (AST); and
  `::test_lockfile_has_no_database_client` (parses `uv.lock` /
  `backend/pyproject.toml`: those distributions absent). The image lane runs
  `python -c "import supabase"` in the container and requires
  `ModuleNotFoundError`. **Exception until Q8:** the import tool needs a
  Postgres driver in Q7; it lives in `selko/tools/import_from_postgres.py`
  imported only by the `selko import-from-postgres` subcommand, and
  `test_selko_imports_no_database_client` excludes exactly that module path,
  with the exclusion deleted in Q8 with the tool.
- `frontend/src/lib/__tests__/no-postgrest.test.js` (Q1): globs
  `src/**/*.{js,svelte}` (excluding tests) and fails on
  `/supabase\s*\.\s*(from|rpc|storage|channel)\s*\(/` and on any import of
  `$lib/supabase.js` outside the auth modules still allowed until Q5;
  a self-test feeds the matcher a fixture string containing
  `supabase.from('events')` and `Array.from(x)` and requires exactly one hit
  (the matcher can fail and does not false-positive on `Array.from`).
- `frontend/src/lib/__tests__/no-supabase.test.js` (Q5): no `@supabase/`
  import anywhere and `@supabase/supabase-js` absent from
  `frontend/package.json`.

### B.10 Production-image lane (Q4)

Script `scripts/verify-image.sh`; lane `image` (gate `prod`); the same script
runs in CI before the image is signed (§C.6).

1. `docker build --build-arg BUILD_SHA=$(git rev-parse HEAD)` of the
   repository `Dockerfile` (bounded docker probes as in today's `verify.sh`).
2. `docker run --read-only --memory=400m --cap-drop=ALL --user <non-root>
   -v <fresh volume>:/data -p 127.0.0.1:<free port>:8000` with a test
   secrets file (throwaway JWT secret, LLM placeholder). Free port, never
   8000 (CLAUDE.md "never start a command that shares a resource").
3. `/health` serves `build_sha == HEAD` within 60 s; pipe `/health`,
   `/health/ingestion`, `/health/egress` through `scripts/assert-health.sh`
   (root, work-state; ingestion with background processing on and no
   integrations).
4. Static web: `GET /` and `GET /app/settings` return the SPA `index.html`;
   a hashed asset under `/_app/immutable/` returns 200; `GET /health` and an
   unknown `/events/<uuid>/sync` return JSON, never `index.html`
   (SPA fallback must not shadow the API).
5. Sign-in: create an account (`docker exec … selko create-account` reading
   the password from stdin), `POST /auth/token`, `GET /auth/user`, one client
   `GET`, `/live` heartbeat; then Playwright `auth.setup.ts`, `auth.spec.ts`,
   `review-queue.spec.ts` with `BASE_URL` pointing at the container and
   `E2E_EMAIL`/`E2E_PASSWORD`.
6. Upgrade path: stop, replace `/data` with the committed fixture database at
   the schema version of `origin/main`'s head
   (`backend/tests/fixtures/db/main-head.db`, regenerated by a script when a
   migration merges), start: migrations apply, `pre-<sha>.db` exists, smoke
   repeats. (From Q6; in Q4 the chain is empty-but-real.)
7. Crash: `docker kill -s KILL` during a claim, restart, the row completes
   (B.5 in the real image).
8. Posture: `docker exec id -u` ≠ 0; a write to `/` fails; `docker inspect`
   `OOMKilled == false`; peak RSS from `docker stats` recorded in the run
   record; `python -c "import supabase"` fails (from Q6).
9. Teardown in a `trap`: remove container and volume, and confirm the
   removal (`docker ps -a`, `docker volume ls` filtered by the run's label).

Q4–Q5: production still runs Postgres, so steps 2–5 need a database: the
lane `requires` local Supabase healthy (`supabase_db_selko` and
`supabase_kong_selko` health, as `verify.sh:require_local_supabase` checks)
and passes the local URLs to the container on the host network. From Q6 the
lane has no external dependency besides Docker.

### B.11 Crash-consistent copy (Q6)

`backend/tests/db/test_snapshot_restore.py::test_a_copy_taken_mid_write_opens_cleanly`
— a writer commits continuously; copy `selko.db`, `-wal`, `-shm` at an
arbitrary instant (what a disk snapshot captures); open the copy:
`integrity_check` ok, every transaction committed before the copy instant is
present, nothing partial. This is the evidence behind spec §4.6 "a snapshot
restores like a power cut".

### B.12 Attachments on disk (Q6)

`backend/tests/db/test_attachment_store.py`: `test_write_is_atomic` (crash
between write and rename leaves no visible partial file),
`test_startup_removes_orphan_temp_files`, `test_row_and_file_agree` (a
startup/health check counts rows whose file is missing:
`attachments_missing_files`, asserted zero in work-state from Q7, §C.9),
`test_paths_never_escape_the_user_directory` (ids with `..`/`/` refused),
plus the two accept-set tests in A.2 #3.

### B.13 Assert-health can go red (Q2)

`backend/tests/test_assert_health.py` as described in §A.7 last row.

---

## C. Gates and lanes

Principle kept throughout: **a lane that cannot run is red.** Every step that
disappears is replaced by a step that can fail, in the same PR.

### C.1 `scripts/lanes.toml`

Today: `backend` (prod; `./scripts/verify.sh backend`; inputs include
`supabase/migrations/**/*.sql`, `supabase/config.toml`,
`scripts/seed_test_tokens.py`, `.github/workflows/*.yml`, `scripts/ops.py`),
`schema-compat` (prod; `ops.py dispatch schema-compat target=production
when=pre-deploy`), `migration-order` (prod; `check-migration-order.sh`),
`prod-health` (observe), `frontend` (prod). No mobile lanes.

| Phase | Change |
|---|---|
| Q1–Q3 | none |
| Q4 | add `[lanes.image]`: `gate = "prod"`, `command = "./scripts/verify-image.sh"`, inputs `Dockerfile`, `.dockerignore`, `backend/**/*.py`, `backend/pyproject.toml`, `pyproject.toml`, `uv.lock`, `frontend/src/**`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/svelte.config.js`, `frontend/vite.config.js`, `frontend/tests/e2e/**`, `scripts/verify-image.sh`; `[[lanes.image.requires]]` "docker" (`docker info`, remedy `scripts/cloud-setup.sh` starts dockerd) and, Q4–Q5 only, "local-supabase" (same health probe as `verify.sh`) |
| Q5 | none (the `schema-compat` input list is unchanged; the accounts migration goes through `supabase/migrations`) |
| Q6 | `backend`: description "unit + integration on temp SQLite"; inputs add `backend/selko/db/migrations/**/*.sql` and `backend/tests/fixtures/db/**`, drop `supabase/migrations/**/*.sql` and `supabase/config.toml` (no backend test reads them any more); `image`: drop the local-supabase requirement; `schema-compat`: command becomes `./scripts/check-schema-compat.sh` (§C.8) with inputs `backend/selko/db/migrations/**/*.sql`, `scripts/check-schema-compat.sh`; `migration-order`: inputs add the SQLite chain |
| Q7 | add `[lanes.import]` (`gate = "prod"`, `./scripts/verify.sh import`, requires local Supabase) for the cutover PRs only |
| Q8 | delete `import`; `backend` drops `scripts/seed_test_tokens.py`; `migration-order` drops `supabase/migrations/**/*.sql` — **in the PR that deletes `supabase/`**, because `test_the_repository_lanes_declare_only_inputs_that_exist` (and the runner's own "pattern matched nothing ⇒ red") fail on a pattern with no files |

Final: `backend`, `frontend`, `migration-order`, `schema-compat` (local
script), `image` — all `prod`; `prod-health` — `observe`.

### C.2 `scripts/verify-lanes.py`

Unchanged in every phase (fingerprints, ledger, per-lane locks, `requires`,
"input pattern that matches nothing is red"). The image lane holds Docker, so
it must not run concurrently with screenshot capture that holds port 8000 —
it uses a free port and its own lock, so no change is needed. CLAUDE.md's
`--gate mobile` is removed in the Q1 docs (§0.5).

### C.3 `scripts/verify.sh`

Today `verify_backend` (line 166): `check-migration-order.sh main`,
`require_local_supabase` (docker health of `supabase_db_selko`/
`supabase_kong_selko` with `bounded_docker`), `supabase db reset`,
`prepare_local_integration_fixtures` (GoTrue `create_user`; Gmail token copy
staging→development via `seed_test_tokens.py`, or the explicit
`--accept-stale-gmail-token` degradation), schema hash from `supabase
migration list --local`, unit run, integration run (`-m "not staging"`),
screenshot seed, fixture test; writes `.verify/backend-<sha>.json`.

| Phase | Change |
|---|---|
| Q1–Q4 | none |
| Q5 | `prepare_local_integration_fixtures` creates the test user through the new accounts path (the Q5 app no longer calls GoTrue admin) |
| Q6 | `verify_backend` becomes: `check-migration-order.sh main`; `uv run python -m selko.db.migrate --check` (chain hashes, numbering); schema hash = SHA-256 of `sqlite_master.sql` (sorted) of a fresh db with the chain applied; unit run; integration run on temp SQLite (no Docker, no `supabase`); screenshot seed into `SELKO_DATA_DIR=$(mktemp -d)` and the fixture test against that directory; directory removed in the EXIT trap. `require_local_supabase`, `bounded_docker` and `fail_unresponsive_daemon` move to `scripts/verify-image.sh`. `staging` mode deleted. Gmail token: see below |
| Q7 | add `import` mode (B.3), needs local Supabase, fails closed like today's `require_local_supabase` |
| Q8 | delete `import` mode |

**Real-Gmail coverage after staging is gone.** Today the token comes from a
dev↔staging copy and is routinely missing (CLAUDE.md records the degradation
while staging is paused). With no staging, nothing can supply a live Gmail
refresh token to a session: the proxy's network secrets inject headers, and a
Google refresh grant carries the token in the POST body. This is a decision
only Toni can make (a burner Gmail account and where its token lives). Until
then the `gmail`-marked tests keep running only under the explicit
degradation flag, which `write-verification-manifest.py` records — never a
silent skip. The image lane does not need Gmail.

### C.4 `.githooks/pre-commit`

Today: backend changes = `backend/*.py|scripts/seed_test_tokens.py`; trusts
`.verify/backend-<sha>.json` with `"status": "passed"` and nothing newer,
else the pytest cache; frontend = `frontend/test-results.json`; eval-result
ceiling.

| Phase | Change |
|---|---|
| Q6 | case list adds `backend/selko/db/migrations/*.sql` (a migration-only commit is not checked today, because the hook only matches `*.py`); the freshness `find` adds `-name '*.sql'` under `backend/selko/db/migrations` |
| Q8 | drop `scripts/seed_test_tokens.py` from the case list and the `find` |

The message text ("`./scripts/verify.sh backend` … collects staging-marked
tests") is updated in Q6 when the staging marker goes.

### C.5 `scripts/cloud-setup.sh`

Today: uv + Python 3.14, Supabase CLI (pinned), jq/lsof, Node ≥ 22.12,
frontend npm deps, Chrome for Playwright, `core.hooksPath`, `dockerd`,
`supabase start -x <excludes>` detached, `.env`/`frontend/.env` with local
Supabase demo keys and a random test password; `--db`, `--status`.

| Phase | Change |
|---|---|
| Q4 | `--status` reports Docker readiness for the image lane (it already starts dockerd) |
| Q5 | `.env` gets a throwaway `SELKO_JWT_SECRET` (`openssl rand -hex 32`) |
| Q6 | `.env` gets `SELKO_DATA_DIR=$PWD/.verify/data`; `frontend/.env` drops `VITE_SUPABASE_*` (Q5 already stopped reading them) |
| Q8 | delete `ensure_supabase_cli`, `supabase_healthy`, `start_supabase`, the Supabase-status part of `write_env_files`, `SUPABASE_EXCLUDES`, `--db`; `--status` reports uv, Node, `node_modules`, Docker, Chrome. Keep `ensure_docker` (image lane). Update CLAUDE.md "Cloud sessions" timings (no more image pulls for Supabase) |

### C.6 `.github/workflows/test.yml` and `frontend-tests.yml`

`test.yml` today: `changes` (paths-filter `backend`, `supabase`),
`unit-tests` (`pytest -m "not integration" -n auto`), `deploy-staging`
(reports "paused" unless staging is active; then `supabase link`, `db push`,
Render hook, `verify-staging.sh`).

| Phase | Change |
|---|---|
| Q4 | new job `image`: on PR — build, `scripts/verify-image.sh` (with local Supabase via `scripts/cloud-setup.sh --db` while Q4–Q5 need it); on push to `main` — same, then push `ghcr.io/tonimelisma/selko:<sha>` and `cosign sign` the **digest** keylessly, only if verify-image passed (`permissions: packages: write, id-token: write`). Actions pinned by full SHA (`test_every_action_is_pinned_by_full_sha` covers `ops.yml`; extend it to all workflows) |
| Q6 | `unit-tests` runs the whole backend suite, integration included, minus `gmail`/`llm` markers (no Docker needed now); `deploy-staging` deleted (no staging can run the SQLite build); paths-filter `supabase` output dropped from job conditions |
| Q8 | remove the `supabase` filter |

`frontend-tests.yml`: the build step writes `VITE_SUPABASE_URL`/
`VITE_SUPABASE_ANON_KEY` placeholders — removed in Q5. Otherwise unchanged.

### C.7 `.github/workflows/ops.yml` and `scripts/ops.py`

`test_ops.py` keeps both files in step; every row below edits `SCHEMAS`
(`scripts/ops.py:102`) and `ops.yml` (`repository_dispatch.types`,
`workflow_dispatch.inputs.operation.options`, the job) in one PR.

| Operation | Today | Q1–Q5 | Q6 | Q7 | Q8 / final |
|---|---|---|---|---|---|
| `schema-compat` | `supabase link`, `db push --dry-run` (pre) or `assert-schema-code-compat.sh --linked` (post) against production | unchanged; required for Q1–Q3/Q5 migrations | lane switches to the local script (§C.8); op kept only for a Postgres emergency fix while production is frozen | unused | deleted with `assert-schema-code-compat.sh` |
| `deploy-production` | SHA = main's tip; `db push` dry run + apply; R5; Render hooks App+Web; wait for `build_sha`; `check-production-health.sh` | unchanged | add a first step that refuses when `backend/selko/db/migrations/` exists in the checked-out SHA and the cutover marker is absent: "main is SQLite-only; production is frozen at the Q5 SHA until the cutover" (red, not a silent no-op) | rewritten: SHA = main's tip; verify the CI `image` check-run for the SHA succeeded (`commits/<sha>/check-runs`); `cosign verify` the digest with identity = `test.yml` on `refs/heads/main` of this repository; move `:latest` to the digest (`docker buildx imagetools create`); wait until `api.selkoapp.com/health` serves the SHA (the server's updater pulls every 5 minutes; keep 30 × 30 s); `check-production-health.sh`; assert `/health` `schema.version` equals the repository head. Secrets used: none beyond `GITHUB_TOKEN` | same; Supabase/Render steps and secrets gone |
| `rehearse-cutover` | local Supabase on the runner + production read-only URL; `rehearse_cutover.py [--faithful]` | **required** before deploying Q3's revoke migration and Q5's `accounts` fill (migrations on populated production) | unused | replaced by the **server-side** import dry run (§E Q7): never in Actions, because the repository and its artifacts are public | deleted with `rehearse_cutover.py`; successor is the server-side `selko migrate --rehearse` (VACUUM INTO a scratch copy, apply pending migrations, run the invariant checks, delete the copy) run through the server's access path before approving a migration that touches a populated table |
| `repair-review-queue` | dry run / apply against production Postgres; reverse-operation artifact (7 days) | unchanged | unchanged (production is still Postgres) | replaced by `selko repair-review-queue` inside the image, run on the server; the reverse-operation file stays on the server's volume (no public artifact) | deleted from ops |
| `staging-tier2` | red while staging is paused | unchanged (red, disclosed) | deleted with `verify-staging.sh`, `drill-staging-workers.sh`, `_drill_lease_probe.py` | — | — |

Server-side operations (the import, rehearsals, repairs) run on the server by
its operator; deploying the image to the server is outside this repository:
the server pulls the signed image and verifies its signer identity.

### C.8 Schema-compat after Q6

`scripts/check-schema-compat.sh` (VM; `api.selkoapp.com` is reachable from the
cloud VM): read `/health` → `schema.version` and `schema.head_file`; compare
with `backend/selko/db/migrations/`; print the files a deploy would apply;
**red** when `/health` does not publish `schema.version` (silence is not
success — this makes it red from the Q6 merge until the Q7 cutover, which is
correct: there is no SQLite production to be compatible with), when production
is ahead of the tree (drift), or when an already-applied file's hash (also
published) differs from the tree. Tests in `test_scripts.py`
(`TestCheckSchemaCompat`, fed recorded `/health` payloads, including a missing
field).

### C.9 `check-production-health.sh` / `assert-health.sh`

Today: root (`build_sha` 40 chars, status ok|degraded,
`server_errors_per_hour == 0`), work-state (4 counters zero), ingestion
(`status ok`, background on, tasks alive, `.listener.connected == true`,
`has("items_stalled_seconds")`, ≤ 1800), egress (`.transport == "asyncpg"`,
`assert-health.sh:105`).

| Phase | Change |
|---|---|
| Q2 | `tests/test_assert_health.py` (B.13). Ingestion unchanged (the pg listener now also feeds `/live`) |
| Q6 (merged with the health payload change) | every payload publishes `storage_engine` (`"postgres"` on the Q5 build is absent, so the script treats absent as `postgres` **only** for the egress/ingestion branch selection, never as a pass); `sqlite` builds: egress `.transport == "sqlite"`; ingestion `.event_bus.running == true` replaces `.listener.connected`; root additionally requires `schema.version` integer > 0. Each engine is held to its own strict filter; the postgres branch is deleted in Q8. This keeps `prod-health` green against the frozen Q5 production between Q6 and Q7 instead of red for days |
| Q7 | work-state adds `attachments_missing_files == 0` (B.12); new surface `storage` on `/health`: `storage.free_bytes >= <threshold>` and `storage.pre_copies <= 2`. **UNKNOWN:** the threshold — set it from Q0's database and attachment sizes (spec Q0 measures them) as max(2 GB, 3 × (db + largest pre-copy)); until Q0 the surface is not added. `check-production-health.sh` adds `check storage /health` |
| Q8 | postgres branch deleted |

Every new invariant answers "what makes it go back to green": free space
returns when copies are pruned (automatic, B.2) or the disk grows (operator);
missing files return to zero only by repair — that is intended, a missing
attachment is lost data.

### C.10 `docs/deploy-log/TEMPLATE.md`

| Phase | Change |
|---|---|
| Q4 | "Shipped" adds **Image digest** and **cosign verified (identity)** (filled with "n/a — Render build" until Q7) |
| Q7 | "Schema version" becomes before → after (`/health` `schema.version`); "Migrations applied" lists SQLite files; add **Pre-migration copy** (path, size) and **Rollback target** (previous digest + `pre-<sha>.db`); "Rehearsal" points to the server-side `selko migrate --rehearse` output; "Deploy run" unchanged; the Observation table adds columns **db + WAL size**, **free disk**, **container restarts / OOMKilled**. The cutover entry also records the import's per-table counts and checksum verdict (counts only; the repository is public) |
| Q8 | remove the `rehearse-cutover` wording |

The Stop hook `.claude/hooks/require-deploy-observation.sh` is unchanged.

### C.11 Other scripts touched

| Script | Fate |
|---|---|
| `scripts/assert-schema-code-compat.sh`, `scripts/supabase-project-status.sh` | D at Q8 |
| `scripts/check-migration-order.sh` | R at Q6: also checks `backend/selko/db/migrations/` (four-digit prefix, strictly increasing, no gap, a file present on `main` may not change content), and refuses any **new** file under `supabase/migrations/` after the Q6 merge except an emergency fix explicitly named in the PR; Q8 drops the Postgres half |
| `scripts/verify-staging.sh`, `scripts/drill-staging-workers.sh`, `scripts/_drill_lease_probe.py` | D at Q6 |
| `scripts/rehearse_cutover.py` | D at Q8 (needed through Q5) |
| `scripts/repair_review_queue_integrity.py` | R at Q7 into `selko repair-review-queue` (same flags and fail-closed rules), D from `scripts/` |
| `scripts/seed_test_tokens.py` | D at Q8 |
| `scripts/seed_screenshot_data.py` | R at Q5 (accounts) and Q6 (writes through `selko.db` into `SELKO_DATA_DIR`) |
| `scripts/capture-all-screenshots.sh` / `with-api.sh` | R at Q6: no "Supabase is running" precondition; start `selko serve --data-dir` (the existing "is it really Selko on :8000" check stays) |
| `scripts/smoke-ingestion.py` | U; used by the image lane |
| `scripts/write-verification-manifest.py` | U (schema hash input changes in verify.sh) |
| `scripts/backfill_calendar_components.py`, `scripts/cleanup_review_incident_20260713.py` | D at Q6 (§A.1 #7, #14) |
| new: `scripts/verify-image.sh` (Q4), `scripts/check-schema-compat.sh` (Q6) | — |

### C.12 Tier 1 and Tier 2, honestly

**Tier 1** after Q6 is the same command and gets stronger: the integration
suite runs on the production engine, on every CI push too (§C.6), with no
Docker and no local-vs-hosted gap. The class of failure CLAUDE.md lists under
Tier 2 ("Local Supabase has no Supavisor…", session pooler, LISTEN/NOTIFY
survival, grant drift between local and hosted ACLs) stops existing because
those components stop existing.

**Tier 2 today** cannot run: staging is paused, `staging-tier2` is red, and
every deploy carries an operator waiver. **After Q6 there is no hosted
staging at all.** The substitute gate has three parts and is named "Tier 2"
in CLAUDE.md from Q6:

1. **The image lane on the tree** (pre-merge, `verify-lanes.py --gate prod`).
2. **The same script on the exact artifact** in CI before signing, and
   `deploy-production` refuses a SHA whose `image` check-run did not pass —
   so "signed" implies "booted, migrated from main's schema, signed in,
   survived SIGKILL, under 400 MB".
3. **Server-side rehearsal** for migrations on populated tables
   (`selko migrate --rehearse` against a `VACUUM INTO` copy of production on
   the server) — the successor of `rehearse-cutover --faithful`.

What none of these covers, stated in CLAUDE.md and in every deploy log:
live OAuth with Google and Microsoft (token refresh mid-pass, #235 class),
real Gmail/Graph/Calendar responses and egress, the reverse proxy and DNS in
front of the process (SSE buffering, TLS), memory over hours on an e2-micro
shared with other services, and production data shapes for code paths that
are not migrations. Those are observable only after deploy: T+0/T+15m/T+24h
windows in the deploy log, with RSS and free disk recorded. The waiver
language ("an explicit user instruction to deploy … after the Tier 2 gap has
been disclosed is an operator waiver") is deleted in Q6, because the gap it
waives no longer exists in that form; the remaining gaps are permanent and
are covered by observation, not by a waiver.

---

## D. Documentation

### D.1 `CLAUDE.md` (by heading)

| Heading (line) | Change | When |
|---|---|---|
| MANDATORY: The verification process (43) | remove `--gate mobile` (step 1) | Q1 (docs fix) |
| Checking that production is actually healthy (66) | `ingestion` row: "pg listener connected" → "event bus running"; `egress` row: asyncpg → sqlite; add `storage` row; delete the `selko.onrender.com` staging paragraph | Q6 (ingestion/egress), Q7 (storage), Q8 (staging paragraph) |
| Long-running commands (96) | "the local database" → the local data directory; add Docker/image lane as a shared resource | Q4, Q6 |
| Never trust a signal that cannot fail (119) | add the duplicate-class finding (§0.1) as a fourth example | Q1 |
| MANDATORY: Worktree Workflow (154) | box: drop `cli/` (does not exist), `supabase/` → `backend/selko/db/migrations/` is source code | Q1 (cli), Q6 (migrations), Q8 (supabase) |
| Cloud sessions (198) | setup paragraph (Supabase CLI, `supabase start`, measured timings), "Where each lane and task runs" table rows backend/migration-order/schema-compat/production deploy/cutover rehearsal/review-queue repair/Tier 2/Supabase Management API/Render API, `gh` notes unchanged; add rows: image lane (VM, Docker), server operations (import, repair, rehearse) via the server access path | Q4 (image row), Q6 (backend/Tier 2 rows), Q7 (deploy/server ops), Q8 (Supabase/Render rows and setup text) |
| Owner setup (283) | network secrets for `api.supabase.com`/`api.render.com`, Actions secrets list (`SUPABASE_*`, `PRODUCTION_SUPABASE_*`, `RENDER_*`, `STAGING_*`), allowed-hosts list | Q8 (after the 14 days) |
| Definition of Done / 0 (329, 333) | unchanged | — |
| MANDATORY: Verification tiers (349) | Tier 1: temp SQLite, no Docker; Tier 2: §C.12; delete the three "Tier 1 cannot reach" bullets and the waiver paragraph | Q6 |
| 1. Scope your change (386) | table rows `backend/**, cli/**` (drop cli), `supabase/**` → `backend/selko/db/migrations/**` (Tier 2 = image lane), iOS/Android rows (legacy); bullets: RLS-in-same-migration → "every new user-owned table has `user_id NOT NULL` and an ownership-matrix case"; reachability bullet: new roots; CHECK bullet: new location of `EXPECTED_CHECK_DOMAINS`; "SQL that has never been executed" → "a `selko.db` function or trigger that has never been executed"; "A client query string is schema" → delete, replace with "an API response model is the client contract" (`test_every_client_route_declares_a_response_model`) | Q1 (query-string bullet, iOS/Android), Q3 (ownership bullet), Q6 (rest) |
| 1a. Pick verification by risk dimension (450) | "Migration touching a populated table" row → server-side `selko migrate --rehearse` | Q7 |
| 1b. Run the lanes (480) | gate list (no mobile), add `image` | Q1, Q4 |
| 2. Ship it (515) | deploy command semantics (signed digest, `:latest`), what the job checks | Q7 |
| CI Ownership (527) | `deploy-staging` history paragraph; "Google OAuth expired: `cli.cli_seed_tokens`" (stale) | Q6, Q8 |
| Essential Commands (581) | `supabase start`/`db reset` → `selko serve --data-dir`; `uv run python -m selko.api` (crashes, spec §6) fixed with the Q4 entrypoint; xcodebuild row removed | Q1 (xcodebuild), Q4, Q8 |
| Screenshot Updates (624) | "Shared code (Supabase schema, seed data)" row | Q6 |
| Architecture Principles (639) | "Direct Supabase Access" → "Clients call the API only" (Q1); "Two transports, no fallback" → "One data layer, one writer" with the B9 and `test_single_data_layer.py` guard names (Q6); RPC names in ingestion/calendar component/identity/review/durable polling/work state/single-owner sync/two providers/repair bullets become `selko.db` function names; `FOR UPDATE SKIP LOCKED`, advisory locks, `pg_notify`, `selko.worker_app` → single writer, startup reset, event bus (Q6); egress bullet drops the Supabase hook (Q6); Reconnect recovery "RLS-readable by the owner" → API route (Q1); MCP bullet deleted (stale now, Q1); "LLM-Centric" privacy sentence unchanged | Q1, Q2, Q6 |
| Environment & Config (696) | `.env.test`, `.env.production`, "Supabase Instances" line | Q8 |
| MANDATORY: Environment separation (710) | `cli_seed_tokens` rules → "production data never leaves the server; the import runs on the server" | Q7 (new rule), Q8 (old text removed) |
| Reference Index (731) | `supabase-frontend-queries.md` → `api-client-endpoints.md` (Q1); add this spec; MCP row (stale, Q1); historical specs (cutover-verification-20260807, foundation-integrity, grant-integrity…) marked superseded where their gates no longer exist (Q8) | Q1, Q8 |

### D.2 `PRD_ARCH.md`, `README.md`, `legacy/README.md`

- `PRD_ARCH.md`: Part 2 §1.2–1.3 (infrastructure), Part 3 §0 status, §1
  System Overview diagram, §3.1 "Direct Supabase Access (No Proxy Layers)" →
  "API is the only door" (Q1), §4.1 component overview (Render service
  subgraph line 463) and §5 stack table (Supabase/Render rows line 516),
  §5.2 "Why Supabase" and §5.3 "Why Render" → "Why SQLite" and "Why one VM"
  (Q7), §6 add the rejected alternative "keep Postgres" with the measured
  reasons from the spec §3, §7 Deployment Strategy (Render config, line 554)
  → image + pull (Q7), §8 Security Model (RLS → API ownership, Q3; auth Q5).
- `README.md`: "Product status" (Realtime Broadcast line 101, Q2),
  "Architecture" + diagram (lines 104–131, Q1 and Q7), "Stack" (Q7),
  "Local development" prerequisites/setup (`supabase start`, lines 139–151,
  Q8 — until then both Postgres and SQLite instructions are true at
  different points, so Q6 rewrites it to SQLite and keeps one line for the
  import lane's Supabase), "Testing" (Q6).
- `legacy/README.md`: add that the native apps stopped working at the Q7
  cutover (Q7).

### D.3 `docs/*.md`

| Doc | Change | When |
|---|---|---|
| `database-schema.md` (700 lines; Supabase Storage §603, Data API grants §684, Migrations §692) | Q5: `accounts`, refresh-token tables; Q6: rewritten from `0001_initial.sql` (TEXT/ISO types, JSON CHECKs, STRICT), "Supabase Storage" → attachments directory, RLS/grants → ownership in the API, migrations → startup runner with pre-copy | Q5, Q6 |
| `supabase-frontend-queries.md` (730) | replaced by `docs/api-client-endpoints.md` (every client endpoint, request/response models, error envelope, pagination); live section Q2; auth Q5. Old file deleted in Q1 | Q1, Q2, Q5 |
| `job-queue.md` (292) | Q2: `pg_notify` now also feeds `/live`; Q6: claims under the single writer, leases kept, startup reset, event bus, testing section (no `supabase start`) | Q2, Q6 |
| `api-workflow.md` (297) | Q1: §"Data Queries (Direct Supabase)" (291) and steps 4/6 ("via Supabase direct") → API calls; Q5: Step 1 sign-in via `/auth/*`; Q6: local start without Supabase | Q1, Q5, Q6 |
| `testing-guide.md` (198) | markers table (integration no longer needs Supabase; `development`/`staging`/`drill`/`production` retired), "Development (Local Supabase)" and "Staging (Cloud Supabase)" sections, bounded-docker note → image lane | Q6, Q8 |
| `ci-cd.md` (244) | environments table (9–11), pipeline diagram (deploy-staging 39, deploy-production 53–56), jobs/ops tables (80–88), "Render does not deploy on push" (138), Render health check config (202) → the server's updater health check, Render log search (228) → server logs | Q4 (image job), Q6 (staging), Q7 (deploy), Q8 |
| `gmail-integration.md` | `reprocess_email` RPC and `claim_unprocessed_email` wording (lines 385–387) → `selko.db` functions | Q6 |
| `llm-integration.md` | no Supabase/Postgres/table references found (grep `supabase\|postgres\|rpc\|llm_call_log\|usage_quotas`); re-grep in Q6 and change nothing if still none | Q6 (check only) |
| `microsoft-graph-failure-ledger.md` | ledger writer is a `selko.db` function; Supabase/PostgREST mentions | Q6 |
| `parallel-agents.md` | env-file copy steps naming Supabase | Q8 |
| `screenshot-guide.md`, `ui-testing-guide.md` | `supabase start` prerequisites → `selko serve --data-dir`; e2e `BASE_URL`/`E2E_*` | Q4, Q6 |
| `deploy-log/README.md` | unchanged text; TEMPLATE per §C.10 | Q4, Q7 |
| `backlog.md` | Supabase mention reviewed | Q8 |

### D.4 Privacy policy (`frontend/src/routes/privacy/+page.svelte`, lines 99–112)

The processor list must be true for every day, so it changes when data
moves, not when code merges:

- **Q5 (conditional):** if Q0 finds sign-up requires email confirmation and
  signup sends mail through Resend (the API uses Resend today only for
  operator notifications, `selko/services/email_sync_health.py:59`), add
  "Resend: sign-up confirmation email" before the Q5 deploy.
- **Q7 (before the import runs):** add the new hosting provider. If the
  server is the GCP VM (§C.7 inference), "Google Cloud: hosting for the Selko
  web app, server and database". **UNKNOWN:** whether the domain's DNS or
  traffic passes through another provider (e.g. Cloudflare) after the switch
  — find out from the DNS configuration chosen for the Q7 switch; if traffic
  is proxied, that provider is listed too. Remove "Render" once Render no
  longer serves traffic (end of Q7).
- **Q8:** remove "Supabase" only when the Supabase project is deleted (it
  holds user data for the 14-day way back).
- Test: `routes/privacy/__tests__/page.test.js::names every service provider
  that handles user data` (line 24, list at line 27) changes in the same PR
  each time; `names no AI provider besides Anthropic` U. CLAUDE.md
  "LLM-Centric AI" already says a provider change is a policy change; the
  same sentence is extended to hosting providers in Q7.

### D.5 Spec front matter (`docs/specs/*.md`, checked by `tests/test_spec_status.py`)

- `sqlite-single-process.md`: each increment adds its proving node ids to
  `tests`, its health surfaces to `health` (`/health` schema, `/live`,
  `storage`), and drills (`image-lane-crash-drill`) — otherwise the
  generated status table cannot show the increment done.
- Front matter naming tests that Q6 deletes or renames must change in the
  same PR: `grant-integrity-and-cutover-safety.md`
  (`test_security_definer_functions_are_not_executable_by_api_roles`,
  `test_delete_events_status_backfill_preserves_every_legacy_status`,
  drill `staging-worker-drill`), `state-ownership-and-deterministic-recovery.md`
  (drill `state-ownership-acceptance-drill`), `executable-truth.md`,
  `foundation-integrity.md`, `cutover-verification-20260807.md`,
  `oauth-reconnect-catch-up.md` (drills). Mark those specs superseded where
  their gate no longer exists rather than leaving references to deleted
  nodes. Fix the two already-missing ids (§0.5) in Q1.

---

## E. Checklist per increment

"Green to start" is what must hold before the increment's branch is cut;
"green to finish" is what must hold before the PR merges (and, for server
increments, before the deploy log is closed). `--gate prod` always means
`./scripts/verify-lanes.py --gate prod` and the printed table is reported.

### Q1 — Client data through the API

Start: `--gate prod` green on `main`; `check-production-health.sh` green;
the §0.1 duplicate-class fix and `test_test_hygiene.py` merged (separate small
PR first, so later rewrites start from a suite that runs what it shows).

Finish:
1. New endpoints have route tests in `test_api_routes.py` and integration
   tests in `test_integration_api.py`; every new route has
   `response_model` (`test_every_client_route_declares_a_response_model`).
2. `no-postgrest.test.js` green and its self-test proves it can fail.
3. Frontend service tests rewritten (A.3 Q1 rows); `npm run check` green;
   web screenshots captured (`capture-all-screenshots.sh web`).
4. `test_frontend_select_columns_exist_in_the_live_schema` deleted in the same
   PR as the last `.from(` (spec Q1 done-when).
5. Docs: `api-client-endpoints.md` replaces `supabase-frontend-queries.md`;
   CLAUDE.md stale items (§0.5) fixed; spec front matter ids fixed.
6. Deploy (owner's yes per SHA) and deploy log T+0/T+15m; T+24h next day,
   including "History/Review load without 4xx/5xx" (`server_errors_per_hour`
   0).

### Q2 — Live updates through the API

Start: Q1 deployed and its T+24h row filled.
Finish: B.7 tests green (Postgres `LISTEN` version);
`test_live_invalidations.py` replaces `test_broadcast_fanout.py` in the PR that
drops the `realtime.send` triggers (`rehearse-cutover` before that deploy);
`live-updates.test.js` rewritten; `test_assert_health.py` (B.13) added;
T+0 includes the `/live` heartbeat through Render's proxy; spec done-when
"Realtime unused in production for 7 days" recorded in the deploy log at
T+7d (Realtime usage read from the Supabase Management API by count only).

### Q3 — Ownership without RLS

Start: Q2 deployed.
Finish: B.1 ownership matrix green with every authenticated route covered;
`test_every_authenticated_route_has_an_ownership_case` shown red by adding a
throwaway route in a scratch commit (recorded in the PR body, not merged);
B.1a revoke migration + `test_api_roles_have_no_privileges.py` green locally;
`rehearse-cutover --faithful` run for the revoke and its run URL in the deploy
log; `schema-compat` green; `test_integration_grant_posture.py` deleted;
`test_integration_rls_security.py` and `test_integration_data_api_grants.py`
still green (they remain until Q6); deploy; T+0 includes one real PostgREST
call with a production user token answering empty/401 (count only in the
log).

### Q4 — Image, signing, startup migrations, image lane

Start: Q3 deployed. Docker available in the VM (`cloud-setup.sh --status`).
Finish: B.2 migration-runner tests green; `verify-image.sh` and lane `image`
green locally (with local Supabase), including the e2e subset with
`E2E_*` credentials; `test_gate_contract.py::test_image_lane_fails_closed_without_docker`
green; CI `image` job green on the PR and, after merge, the digest for
`main`'s tip is pushed and `cosign verify` passes from the VM; `/health`
publishes `schema` (from the image's own runner); TEMPLATE gains the image
fields; the Essential Commands entrypoint fixed (spec §6); docs (§D Q4 rows).
Production deploy as today (Render). **UNKNOWN:** whether Render runs the
image from Q4 (one build path) or keeps building from source until Q7 (two
build paths, the image proven only by the lane) — decide in the overview; if
Render keeps building from source, the deploy log records "image not
deployed" until Q7.

### Q5 — Own auth on today's database

Start: Q4 deployed; Q0's answer on email confirmation recorded in the spec.
Finish: B.8 tests green; `accounts` fill rehearsed with `rehearse-cutover
--faithful` (count and hash-format checks, no content in the log);
`test_integration_auth.py`/`test_integration_users.py` replaced;
`login`, `backend-api`, `Navbar`, `layout` frontend tests rewritten;
`no-supabase.test.js` green (frontend has no Supabase dependency);
`frontend-tests.yml` drops `VITE_SUPABASE_*`; privacy policy (Resend if
applicable) before deploy; deploy; T+0 signs in with an existing password
through the web app (spec done-when) and confirms GoTrue receives no
sign-ins after T+0 (count from the Management API at T+24h).

### Q6 — The SQLite data layer

Start: Q5 deployed and its T+24h filled; the decision of §0.7 taken
(production frozen at the Q5 SHA until Q7, or Q6 held); the photo decision
taken (port or delete); the 01-schema HAND items resolved.
Finish:
1. Full backend suite green on temp SQLite via `verify.sh backend` (no
   Docker): every A.1/A.2 R/X row done; skip budget shrunk in the same PR;
   each rewritten file has a recorded mutation that turned it red (A.6).
2. Successor guards green: B9, `test_single_data_layer.py` (three tests),
   `test_reachability.py` with new roots, `test_events_are_written_only_by_the_commit_function`,
   `test_sqlite_schema.py` (domains incl. the 4 former enums, triggers,
   user_id), `test_db_functions_contract.py` coverage, B4, B5, B6, B11,
   B12.
3. `image` lane green without local Supabase, including the upgrade path and
   SIGKILL step; CI runs the whole suite.
4. `check-migration-order.sh` handles both chains; `check-schema-compat.sh`
   in place and red against production (expected, stated in the PR);
   `assert-health.sh` engine dispatch with tests; `prod-health` still green
   against the frozen production.
5. `deploy-production` refuses SQLite SHAs before the cutover (test in
   `test_ops.py` or a workflow-structure test asserting the step exists).
6. Deleted: `verify-staging.sh`, drills, staging-tier2 op, `deploy-staging`
   job, `selko/services/pg.py`, `selko.worker_app`, the Postgres-only tests
   in A.1/A.2 marked D at Q6.
7. Docs per §D (Q6 rows); spec front matter updated.

### Q7 — Cutover (owner's explicit yes)

Start: Q6 merged; `--gate prod` green (including `import`); B.3 green against
local Postgres; the server (§C.7) has Selko's image identity in its updater
and a `/data` volume; privacy policy PR with the hosting provider merged and
deployed **to Render** before any user data is imported; disk headroom
checked against Q0 sizes.
Finish (in order, each recorded in the cutover deploy log):
1. Dry run on the server: `selko import-from-postgres --dry-run` from the
   production read-only URL into a scratch file; counts and checksums match;
   scratch file deleted and its deletion confirmed.
2. Writes stopped on Render (background processing off, write routes
   refusing); `check-production-health.sh` against Render shows no claimed
   work in flight.
3. Real import on the server; counts and checksum verdict match; attachment
   bytes and hashes match.
4. Start the process from the signed image; `check-production-health.sh
   https://<server origin>` green before DNS moves.
5. DNS switch for `selkoapp.com` and `api.selkoapp.com`; `deploy-production`
   (rewritten) for the cutover SHA, which waits for `build_sha` at
   `api.selkoapp.com` and runs the health check — T+0.
6. `/live` heartbeat through the proxy, sign-in with an existing password,
   one Gmail and one Outlook poll observed, one calendar write observed —
   T+0/T+15m rows.
7. T+24h: RSS within 400 MB without restarts, free disk, no OOMKilled,
   `server_errors_per_hour` 0, `prod-health` green on the sqlite branch.
8. `check-schema-compat.sh` turns green.

### Q8 — Retire (14 days untouched after Q7)

Start: Q7 T+24h filled; 14 days without using the way back; owner's yes to
delete the Supabase project and Render services.
Finish: Supabase project and Render services deleted (owner action, Toni
only); privacy policy drops Supabase in the same day's deploy; `supabase/`,
the Postgres half of `check-migration-order.sh`, `assert-schema-code-compat.sh`,
`supabase-project-status.sh`, `rehearse_cutover.py`, `seed_test_tokens.py`,
`import` lane and tool (and its B9 exclusion), the `schema-compat`/
`rehearse-cutover`/`repair-review-queue` ops removed — lanes.toml patterns
removed in the same PR as the files (`test_the_repository_lanes_declare_only_inputs_that_exist`);
`cloud-setup.sh` without Supabase; assert-health postgres branch deleted;
Actions secrets and network secrets listed for deletion in the report (Toni
only); CLAUDE.md/README/docs per §D Q8 rows; `--gate prod` green; CI on
`main` green.
