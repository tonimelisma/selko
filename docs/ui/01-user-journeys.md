# User Journeys

This document defines the user journeys for Selko's web application. For screen-by-screen specs, see `docs/ui/02-screen-specs.md`. For shared patterns, see `docs/ui/03-patterns-and-components.md`.

---

## Screens

| Screen | Route | Description |
|--------|-------|-------------|
| Review Queue | `/app` | Home screen. Event review list. Replaced by integration setup when not connected. |
| Event Detail | `/app/events/[id]` | Edit/review a single event. Click-through from queue, not a nav tab. |
| Activity History | `/app/history` | Timeline of all actions (user + automatic). Undo from here. |
| Settings | `/app/settings` | Integration management, account, calendar config, timezone. |

---

## Journey 1: New User (First-Time Setup)

**Goal:** Go from zero to seeing the first extracted calendar events.

```
Register → Login → Review Queue shows integration setup (not connected)
  → Click "Connect Google Account" → OAuth flow (Gmail + Calendar scopes)
  → Google grants permissions → redirected back
  → If multiple calendars: pick default. If one: auto-selected.
  → First sync runs → emails fetched → AI processes → events appear in queue
```

### Step-by-step

1. **Register** (`/register`): User creates account with email + password. Sees confirmation message.
2. **Login** (`/login`): User logs in. Redirected to Review Queue.
3. **Review Queue — Integration Setup** (`/app`): No integrations connected. The entire queue area is replaced by an integration setup screen:

   ```
   ┌──────────────────────────────────────────────────┐
   │  Welcome to Selko!                                │
   │                                                    │
   │  Connect your Google account to get started.      │
   │  Selko will read your emails and create           │
   │  calendar events automatically.                   │
   │                                                    │
   │  [Connect Google Account]                         │
   └──────────────────────────────────────────────────┘
   ```

4. **OAuth Flow**: User clicks Connect → redirected to Google consent screen → grants Gmail and Calendar permissions → redirected back to `/app`.
5. **Calendar Selection**: If the Google account has multiple calendars, a dropdown appears to pick the default target calendar. If only one calendar exists, it's auto-selected.
6. **First Sync**: Backend automatically triggers email sync. Queue shows a syncing indicator. After processing completes, events appear in the Review Queue.
7. **First Review**: User sees pending events grouped by sender. Taps "Edit" on an event → Event Detail → reviews/edits → approves → event syncs to Google Calendar.

### Partial OAuth Scopes

The user may grant only some scopes (e.g., Gmail but not Calendar). In this case:
- The integration setup screen remains, showing which services are authorized and which still need authorization.
- Per-service status is visible: "Gmail: authorized", "Google Calendar: not authorized [Authorize]".
- The "Authorize" button triggers a scoped OAuth request for just the missing permission.
- Both Gmail and Calendar must be authorized before the Review Queue appears.

---

## Journey 2: Returning User (Daily Use)

**Goal:** Review and approve new events extracted from recent emails.

```
Login → Review Queue shows pending events
  → Browse events grouped by sender → email → events
  → Approve individual events, or approve all from a sender/email
  → Tap "Edit" on events needing changes → Event Detail → edit → approve
  → Check Activity History for recent actions
  → Undo if needed
```

### Step-by-step

1. **Login** → **Review Queue** (`/app`): Shows pending events in hierarchical list.
2. **Review Queue**: User sees events grouped by sender → email → events:
   - **Sender group** (e.g., "school@district.edu") — [Approve All] button
     - **Email** ("Party Invitation", Oct 1) — [Approve All] button
       - **Event**: "Birthday Party" — Oct 5, 2:00 PM — [Approve] [Edit] [Reject]
       - **Event**: "RSVP Reminder" — Oct 3 — [Approve] [Edit] [Reject]
3. **Quick Approve**: For straightforward events, user clicks "Approve" directly. Event animates out of the list. No toast, no modal.
4. **Group Approve**: User clicks "Approve All" on a sender header or email header. All events in that group are approved at once. The group animates out.
5. **Edit Before Approve**: User clicks "Edit" → Event Detail screen. Edits are auto-saved. User approves or rejects. Returns to queue.
6. **Reject**: User clicks "Reject". Event animates out. No confirmation modal.
7. **Activity History** (`/app/history`): User checks recent actions. Sees "Birthday Party approved and synced." Clicks "Undo" → event removed from Google Calendar and returned to Review Queue (reverted to AI-extracted original, not user-edited version).

### Key Behaviors

- All approve/reject actions are immediate. No confirmation modals. No toasts.
- Events animate out of the queue (slide out if smooth animation is achievable, otherwise just disappear).
- Everything goes to Activity History where the user can undo.
- UPDATE events (time changes, cancellations from follow-up emails) are applied automatically — they never appear in the Review Queue. They appear in Activity History where the user can undo them.

---

## Journey 3: Error Recovery

**Goal:** Handle integration failures, sync errors, and network issues gracefully.

### Scenario A: Token Expiry / Integration Failure

```
User logs in → Review Queue is replaced by integration setup screen
  → Shows which service lost authorization
  → "Gmail: authorized" / "Google Calendar: expired [Reconnect]"
  → User clicks Reconnect → OAuth flow → back to queue
```

- The integration setup screen takes over the entire Review Queue whenever integrations are not fully working.
- Same screen whether it's initial setup, token expiry, or revoked access.
- Existing events remain in the database. When reconnected, everything continues as before.

### Scenario B: Calendar Sync Failure

```
User approves event → sync fails
  → Event shows error badge in Activity History
  → [Retry] button on the entry
  → User taps Retry → sync succeeds
```

- Sync failures appear in Activity History with a retry action.
- The event has already left the Review Queue (it was approved).

### Scenario C: OAuth Flow Failure

```
User clicks Connect → Google OAuth → denies or error
  → Redirected back to app → error toast shown
  → Integration setup screen still showing, user can try again
```

- OAuth errors are shown as a toast notification — the one case where toasts are used.
- Same toast behavior whether the OAuth was initiated from the Review Queue setup screen or from Settings (for adding a second account).

### Scenario D: Network Loss

```
User is reviewing events → network drops
  → Actions (approve/reject) show inline error
  → Automatic retry when network returns
  → No data loss — nothing committed until network confirms
```

- Read-only data already loaded remains visible.
- Failed actions retry automatically.
- No offline queue or local persistence.

---

## Review Queue State Diagram

The Review Queue at `/app` has two top-level states: integration setup or event queue.

```
                    ┌──────────────────┐
                    │   User logs in   │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ Check integrations│
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │                              │
     ┌────────▼───────────┐       ┌─────────▼──────────┐
     │ INTEGRATION SETUP   │       │ QUEUE               │
     │                     │       │                      │
     │ Shown when:         │       │ Shown when both      │
     │ - No account linked │       │ Gmail + Calendar     │
     │ - Gmail not authed  │       │ are authorized       │
     │ - Calendar not authed│      │                      │
     │ - Token expired     │       │                      │
     │ - Token revoked     │       │                      │
     │                     │       │                      │
     │ Shows connect/      │       │  ┌────────────────┐  │
     │ reconnect/authorize │       │  │ Has pending     │  │
     │ actions per service │       │  │ events?         │  │
     └─────────────────────┘       │  └───────┬────────┘  │
                                   │     ┌────┴────┐      │
                                   │     │         │      │
                                   │     ▼         ▼      │
                                   │  ┌─────┐  ┌──────┐  │
                                   │  │EMPTY│  │EVENTS│  │
                                   │  │"All │  │List  │  │
                                   │  │caught│  │with  │  │
                                   │  │up!" │  │groups│  │
                                   │  └─────┘  └──────┘  │
                                   └──────────────────────┘
```

### Data Checks

```javascript
import { fetchIntegrations } from '$lib/services/integrations'
import { fetchPendingEvents } from '$lib/services/events'

// 1. Check integration status
const { data: integrations } = await fetchIntegrations()
const gmail = integrations?.find(i => i.provider === 'gmail')
const gcal = integrations?.find(i => i.provider === 'google_calendar')

const gmailOk = gmail?.status === 'active'
const gcalOk = gcal?.status === 'active'

// 2. If both OK, show queue. Otherwise, show integration setup.
if (gmailOk && gcalOk) {
  const { data: pendingEvents } = await fetchPendingEvents()
  // Show queue (or "All caught up" if empty)
} else {
  // Show integration setup screen with per-service status
}
```

---

## Navigation Between Screens

```
Review Queue (/app) ──────── Event Detail (/app/events/[id])
    │                              │
    │   "Edit" on event card       │   "← Back" returns to queue
    │                              │
    ├── Activity History (/app/history)
    │       Undo → event returns to queue
    │
    └── Settings (/app/settings)
            Integration management
            Calendar & timezone config
```

- **Review Queue** is the home screen. All navigation starts here.
- **Event Detail** is only reachable from the Review Queue (via "Edit" on an event card).
- **Activity History** is reachable from the bottom tabs / navbar.
- **Settings** is reachable from the bottom tabs / navbar. Contains integration management.
