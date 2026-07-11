# Specs

Implementation specifications for planned or in-progress features.

## What belongs here

- **Specs / implementation plans** — a detailed, step-by-step design for a feature
  that hasn't been built yet (or is being built). Written to be handed to a developer
  who then implements it. Concrete: file paths, function signatures, SQL, edge cases.

## What does NOT belong here

- **Reference docs** (how a shipped feature works today) go in `docs/` — e.g.
  `docs/gmail-integration.md`, `docs/database-schema.md`.
- **Product requirements / architecture** live in the root `PRD_ARCH.md`.

## Lifecycle

1. Write the spec here and get it reviewed.
2. Implement it (following the worktree + PR workflow in `CLAUDE.md`).
3. Once shipped, fold the durable "how it works" parts into the relevant `docs/`
   reference file and update `docs/database-schema.md` / `CLAUDE.md` as needed.
   The spec can then be marked **Implemented** (keep it for history) rather than
   duplicating reference docs.

## Naming

`docs/specs/<feature-slug>.md` — e.g. `outlook-email-support.md`.
