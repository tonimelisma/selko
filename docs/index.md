# Docs

A map of the docs: one line per doc, saying what question it answers.

- [Architecture](architecture.md): how Selko is built: components, data, flows, security, failure handling, and why.
- [Lessons](lessons.md): rules learned the hard way, and problems still open.

## Requirements

What Selko does today, as EARS sentences with `SEL-NNN` IDs, each verified by tagged tests or marked `unverified:`.

- [Email ingestion (SEL-001..099)](requirements/ingestion.md)
- [Event extraction (SEL-100..199)](requirements/extraction.md)
- [Review (SEL-200..299)](requirements/review.md)
- [Calendar delivery (SEL-300..399)](requirements/calendar.md)
- [Accounts, ownership and integrations (SEL-400..499)](requirements/accounts.md)
- [Web app (SEL-500..599)](requirements/web.md)
- [Platform and operations (SEL-600..699)](requirements/operations.md)
- [Privacy and secrets (SEL-700..799)](requirements/privacy.md)

## Design

One doc per module; each starts with `GOVERNS:` naming the paths it describes.

- [api](design/api.md): walk through the API journey with curl.
- [auth](design/auth.md): tokens, cookies, abuse resistance.
- [brand](design/brand.md): colours, type, voice.
- [ci-cd](design/ci-cd.md): CI, the image, release and production health.
- [client-api](design/client-api.md): the routes the web app uses, and `/live`.
- [data-layer](design/data-layer.md): connections, transactions, ownership, migrations.
- [database-schema](design/database-schema.md): tables and columns.
- [evals](design/evals.md): running and interpreting LLM evals.
- [event-lifecycle](design/event-lifecycle.md): state owners, extraction, identity, review, calendar delivery.
- [integrations](design/integrations.md): OAuth connect, scopes, reconnect recovery.
- [llm](design/llm.md): model registry and extraction prompts.
- [microsoft-graph](design/microsoft-graph.md): Graph failure ledger.
- [screens](design/screens.md): screen-by-screen web specs.
- [screenshots](design/screenshots.md): capturing web screenshots.
- [testing](design/testing.md): test commands, layout and guards.
- [ui-patterns](design/ui-patterns.md): shared UI patterns and the review queue rules.
- [ui-testing](design/ui-testing.md): unit, e2e and visual UI testing.
- [user-journeys](design/user-journeys.md): the web app user journeys.
- [workers](design/workers.md): background workers, durable polling, claim functions.

## Decisions

- [docs/adr/](adr/): one ADR per decision (MADR, with Confirmation, Retirement proof and Reversal plan); superseded ones stay.
  - [0001. One process over one SQLite file](adr/0001-one-process-one-sqlite-file.md)
  - [0002. One owner per data directory](adr/0002-one-owner-per-data-directory.md)
  - [0003. One writer connection, a small pool of WAL readers](adr/0003-one-writer-many-readers.md)
  - [0004. No hosted database](adr/0004-no-hosted-database.md)
  - [0005. The web app is the only client](adr/0005-web-app-is-the-only-client.md)
  - [0006. Selko's own sign-in](adr/0006-own-sign-in.md)
  - [0007. Attachments are files in the data directory](adr/0007-attachments-are-files.md)
  - [0008. Work arrives by signal, not by polling](adr/0008-work-arrives-by-signal.md)
  - [0009. LLM-centric extraction; production runs one Anthropic model with no fallback](adr/0009-llm-centric-extraction-one-model.md)
  - [0010. Explicit extraction intent; declined events are terminal](adr/0010-explicit-extraction-intent-and-declined-terminal.md)
  - [0011. Parallel extraction with a fenced commit](adr/0011-parallel-extraction-fenced-commit.md)
  - [0012. One state owner per concern; workers are the only provider writers](adr/0012-one-state-owner-per-concern.md)
  - [0013. API keys are read from Azure Key Vault by the app at startup](adr/0013-keys-from-key-vault-at-startup.md)
  - [0014. A merge to main releases to production through a signed image](adr/0014-merge-to-main-releases-a-signed-image.md)
  - [0015. Health signals must be able to return to green, and measure what the API answers](adr/0015-health-signals-return-to-green.md)
  - [0016. Ownership is the user_id argument of every data-layer function](adr/0016-ownership-by-user-id-in-the-data-layer.md)
  - [0017. Email is the only input](adr/0017-email-is-the-only-input.md)

## Research

- [2026-01-21-gmail-synchronization](research/2026-01-21-gmail-synchronization.md)
- [Gemini setup for email analysis (2026-02-15)](research/2026-02-15-gemini-email-analysis-setup.md)
- [Production breakage by root cause (2026-08-22)](research/2026-08-22-production-breakage-root-causes.md)

## History

- [deploy-log/](deploy-log/): observations of past deploys, kept as history; no new entries are written (the release `health` job replaced them).
- [screenshots/](screenshots/): current web screenshots.
- LLM eval reports: `backend/tests/eval/reports/`.
