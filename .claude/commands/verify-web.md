# Visual Verification: Web Frontend

Verify the Selko web frontend visually using the Playwright MCP server tools (NOT Bash-based Playwright CLI).

## Prerequisites

- Frontend dev server running: `cd frontend && npm run dev` (localhost:5173)
- Local Supabase running: `supabase start`

## Steps

### 1. Navigate to the app

Use `browser_navigate` to go to `http://localhost:5173`.

### 2. Screenshot at 3 viewports

For each page, capture screenshots at:
- **Mobile:** 375x812 (iPhone 13)
- **Tablet:** 768x1024 (iPad)
- **Desktop:** 1280x800

Use `browser_resize` to change viewport, then `browser_screenshot` to capture.

### 3. Authentication

For pages under `/app/*`, log in first:
1. Navigate to `http://localhost:5173/login`
2. Use `browser_type` to enter `test@selko.local` in the email field
3. Use `browser_type` to enter `testpass123` in the password field
4. Use `browser_click` to click the sign-in button
5. Wait for redirect to `/app`

### 4. Pages to verify

1. **Login** (`/login`) — unauthenticated
2. **Register** (`/register`) — unauthenticated
3. **Review Queue** (`/app`) — authenticated
4. **Activity History** (`/app/history`) — authenticated
5. **Settings** (`/app/settings`) — authenticated

### 5. What to check

For each screenshot, analyze:
- **Layout:** Elements properly positioned, no overflow, correct spacing
- **Navigation:** Desktop shows top navbar with links; mobile/tablet shows bottom tab bar
- **Responsiveness:** Content reflows correctly between breakpoints
- **DaisyUI theming:** Semantic colors used (base-100, base-200, primary, etc.)
- **Empty states:** Proper messaging when no data
- **Loading states:** Skeleton placeholders or spinners as appropriate

### 6. Accessibility tree

Use `browser_snapshot` on each page to get the accessibility tree. Check:
- All interactive elements have labels
- Headings follow hierarchy (h1 > h2 > h3)
- Form inputs have associated labels
- Buttons have descriptive text or aria-labels

### 7. Report

For each page + viewport, report:
- **PASS** — looks correct
- **ISSUE** — describe the problem with a suggestion

Format:
```
## [Page Name] - [Viewport]
Status: PASS / ISSUE
Notes: [description]
```
