# 0005. The web app is the only client

- Status: accepted
- Date: 2026-11-28

## Context and problem

Selko had native iOS and Android apps, a CLI and an MCP connector, each reading data its own
way. Every client multiplied the API surface and the verification lanes. Requirements:
[SEL-500..511](../requirements/web.md).

## Decision drivers

- One client to test and screenshot.
- No client may read the database directly.

## Considered options

### A responsive SvelteKit web app served by the same process (chosen)

- Good: one build, one origin, one verification lane.
- Bad: no offline or native-device features.
- Failure modes: a broken web build breaks every user at once, so the frontend and image lanes gate merges.

### Keep the native apps

- Good: native features.
- Bad: three clients to maintain and verify.
- Failure modes: clients silently diverge from the API.

## Decision

The web app is Selko's only client. It talks only to the API through
`frontend/src/lib/api/client.js` (Bearer token in memory, one shared refresh on 401); there is no
database client in the browser. There is no CLI and no MCP connector. The native apps are
removed from the tree (git history keeps them): nothing builds, tests or ships them.

## Consequences

Mobile capture, push notifications and on-device inference are out of scope; ideas for them go
to issues.

## Confirmation

`frontend/src/lib/__tests__/no-supabase.test.js` (SEL-511), `client.test.js` (SEL-500..502).

## Retirement proof

A product decision to ship a second client, with its own lane.

## Reversal plan

Rebuild a native client against the client API in `docs/design/client-api.md`.
