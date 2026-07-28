# User Journeys

This document defines the user journeys for Selko's web application. For screen-by-screen specs, see `docs/ui/02-screen-specs.md`. For shared patterns, see `docs/ui/03-patterns-and-components.md`.

---

## Screens

| Screen | Route | Description |
|--------|-------|-------------|
| Review Queue | `/app` | Home screen. Two lanes: **New** (add to calendar) and **Changes** (field diffs for existing events). First-run setup is full-screen; returning-user connection failures are shown in context. |
| Event Detail | `/app/events/[id]` | Edit/review a single event. Click-through from queue, not a nav tab. |
| Activity History | `/app/history` | Timeline of approvals and applied changes (with field diffs). Undo returns items to New or Changes. |
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

The user may grant only some scopes (e.g., Gmail but not Calendar). First-run
onboarding remains until at least one integration record exists. After that,
the Review Queue stays visible and shows a provider-specific recovery card.
Missing Calendar access disables Accept/Approve actions but leaves Edit and
Reject available.

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
7. **Activity History** (`/app/history`): User checks recent actions. Sees "Birthday Party approved and synced." Clicks "Undo" → event removed from Google Calendar and returned to Review Queue (reverted to AI-extracted original, not user-edited version). If the user had edited the event in Google Calendar after Selko synced it, Undo blocks until they confirm **Force Undo**.

### Key Behaviors

- All approve/reject actions are immediate. No confirmation modals. No toasts.
- Events animate out of the queue (slide out if smooth animation is achievable, otherwise just disappear).
- Everything goes to Activity History where the user can undo.
- UPDATE events (time changes, cancellations from follow-up emails) appear in the **Changes** lane with a field-level diff. Approve applies the change and syncs; Reject discards it. No-op rediscoveries (e.g. RSVP replies that restate an existing event) are skipped silently.
- Activity History distinguishes **New** vs **Changes**, shows what changed for updates, and Undo returns the item to the matching Review lane.

---

## Journey 3: Error Recovery

**Goal:** Handle integration failures, sync errors, and network issues gracefully.

### Scenario A: Token Expiry / Integration Failure

```
User logs in → Review Queue remains visible with a recovery card
  → Shows which service lost authorization and what is paused
  → "Google Calendar expired [Reconnect Google Calendar]"
  → User clicks Reconnect → OAuth flow → back to queue
```

- Only a user with zero integration records sees full first-run onboarding.
- Any active email provider (Gmail or Outlook) keeps ingestion available.
- With no active email provider, new ingestion pauses; existing suggestions and History remain readable.
- With Calendar unavailable, review, edit, and reject remain available; Accept/Approve and auto-approve are disabled until reconnection.
- An expired optional email provider is nonblocking when another email provider is active.

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
  → Redirected back to app → persistent inline error shown
  → Existing context remains visible and user can try again
```

- OAuth start and callback errors use a persistent inline alert next to the
  relevant connection control. They are never conveyed only by a transient
  toast.

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

The Review Queue at `/app` uses full-screen setup only for first run. Returning
users always retain the queue and receive capability-specific recovery.

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
     │ Shown only when:    │       │ Shown to returning   │
     │ - No integration    │       │ users, with recovery │
     │   records exist     │       │ card when needed     │
     │                     │       │                      │
     │ Shows connect/      │       │  ┌────────────────┐  │
     │ connect/reconnect   │       │  │ Has pending     │  │
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
const emailOk = integrations?.some(
  i => ['gmail', 'outlook'].includes(i.provider) && i.status === 'active'
)
const gcal = integrations?.find(i => i.provider === 'google_calendar')

const gcalOk = gcal?.status === 'active'

// 2. Full-screen onboarding is reserved for a true first run.
if (integrations.length === 0) showFirstRunSetup()

// 3. Returning users always load the queue.
const { data: pendingEvents } = await fetchPendingEvents()
if (!emailOk) showRecovery('email') // New ingestion is paused.
if (!gcalOk) showRecovery('calendar') // Disable accept/approve only.
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
- **Activity History** is reachable from the sticky top navbar.
- **Settings** is reachable from the sticky top navbar. Contains integration management.
