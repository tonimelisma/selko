---
paths:
  - "frontend/**"
---

# Web conventions

- SvelteKit 2 with Svelte 5 runes syntax.
- DaisyUI semantic colours only; never raw Tailwind colours (`text-blue-500` and the like).
- Themes `selko-light` and `selko-dark` live in `frontend/src/app.css` (Tailwind v4
  `@plugin "daisyui/theme"`); there is no Tailwind config file.
- `svelte-check` runs strict: add JSDoc type annotations where needed.
- `design/tokens.json` is the control contract: use the semantic control primitives; static
  statuses are plain icon and text, NEW is neutral, Included/Excluded is a labelled switch, and
  every touch target is at least 44 px (the tokens set 48).
- The web app talks only to the API, through `frontend/src/lib/api/client.js`; no database client
  in the browser, the access token in memory only.
- Unit tests stub `fetch`; the backend route tests prove the response shape.
- After a UI change, run `./scripts/capture-all-screenshots.sh web` and review the screenshots
  (at most 2000 px a side, never `fullPage: true`). Details: `docs/design/screenshots.md`,
  `docs/design/ui-patterns.md`, `docs/design/brand.md`.
