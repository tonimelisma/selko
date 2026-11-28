GOVERNS: scripts/capture-all-screenshots.sh scripts/capture-web-screenshots.sh scripts/seed_screenshot_data.py frontend/tests/e2e/screenshots.spec.ts docs/screenshots/**

# Screenshot Capture Guide

Screenshots of the web app live in `docs/screenshots/` and are used for
documentation and visual verification. The web app is Selko's only client.

---

## How to Capture Screenshots

**There is ONE command:**

```bash
./scripts/capture-all-screenshots.sh web    # 24 web screenshots via Playwright
```

It seeds the screenshot data, starts the local API if it is not running (and
stops only what it started), runs the Playwright capture and keeps every image
under 2000 px.

> **Do NOT** manually seed data, run `capture-web-screenshots.sh` directly, or
> use MCP tools for screenshot capture. Those are internals of the script.

**No prerequisite service.** The script builds the web app (same origin, as in
the image), seeds a throwaway SQLite data directory (`.verify/screenshot-data`)
with `scripts/seed_screenshot_data.py`, starts the API on port 8000 serving the
built app, points Playwright at it (`SELKO_E2E_BASE_URL`), and stops the API
when done. Port 8000 must be free. The run raises the sign-in rate limits for
its own API only (24 sign-ins from one address in a minute). The API log is
`.verify/screenshot-api.log`.

---

## Appendix: Debugging Reference

> **You should NOT need this section for normal screenshot capture.**

### Screenshot User Credentials
- Email: `screenshots@selko.local`
- Password: `screenshotpass123`

### Web (Playwright)

The Playwright test (`frontend/tests/e2e/screenshots.spec.ts`) captures 24
screenshots: six screens at desktop and mobile sizes, each in light and dark
appearance. It starts its own dev server.

- Never use `fullPage: true` — produces oversized images
- Desktop and mobile viewports are both safe (under 2000px)

### Manual MCP Capture (Last Resort Fallback)

Only if the script is broken and you need screenshots urgently: Playwright MCP
— `browser_navigate`, `browser_take_screenshot`, `browser_resize`.

---

## Complete Screenshot Checklist

Every standard screen is captured in both light and dark appearances. Append
`-light` or `-dark` immediately before `.png`; for example,
`web-history-desktop-light.png` and `web-history-desktop-dark.png`.

| Screenshot | Filename | Viewport |
|-----------|----------|----------|
| Login (desktop) | `web-login-desktop-{light,dark}.png` | 1280x800 |
| Register (desktop) | `web-register-desktop-{light,dark}.png` | 1280x800 |
| Review queue (desktop) | `web-review-queue-desktop-{light,dark}.png` | 1280x800 |
| Event detail (desktop) | `web-event-detail-desktop-{light,dark}.png` | 1280x800 |
| History (desktop) | `web-history-desktop-{light,dark}.png` | 1280x800 |
| Settings (desktop) | `web-settings-desktop-{light,dark}.png` | 1280x800 |
| Login (mobile) | `web-login-mobile-{light,dark}.png` | 390x844 |
| Register (mobile) | `web-register-mobile-{light,dark}.png` | 390x844 |
| Review queue (mobile) | `web-review-queue-mobile-{light,dark}.png` | 390x844 |
| Event detail (mobile) | `web-event-detail-mobile-{light,dark}.png` | 390x844 |
| History (mobile) | `web-history-mobile-{light,dark}.png` | 390x844 |
| Settings (mobile) | `web-settings-mobile-{light,dark}.png` | 390x844 |

The matrix contains 24 screenshots.

---

## Troubleshooting

### Web form has stale credentials
Clear fields before screenshotting: use `browser_run_code` to fill empty
strings, or navigate to the page fresh.

### Screenshots too large for Claude API
Both dimensions must be ≤ 2000px. The capture keeps them under that; for an
image from elsewhere, resize it (`sips --resampleHeight 1920` on macOS,
ImageMagick's `convert -resize x1920` on Linux).
