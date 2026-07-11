# Shared UI Patterns & Components

Conventions and reusable components for the Selko web app. All frontend work should follow these patterns for consistency.

**Tech stack:** SvelteKit 2 + Svelte 5, TailwindCSS 3.4, DaisyUI 5.

---

## Responsive Strategy

**Mobile-first.** Write base styles for mobile (320px+), then add `md:` for tablet (768px+) and `lg:` for desktop (1024px+).

### Breakpoints

| Name | Range | TailwindCSS Prefix |
|------|-------|-------------------|
| Mobile | 320–767px | (default, no prefix) |
| Tablet | 768–1023px | `md:` |
| Desktop | 1024px+ | `lg:` |

### Page Container

Every `/app/*` page wraps content in:

```html
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
  <!-- page content -->
</div>
```

---

## Navigation

### Sticky top app bar (all breakpoints)

One sticky top navbar for mobile and desktop — brand, primary links, and Log out. No bottom tab bar (DaisyUI 5 removed `btm-nav`; a top bar also avoids fighting Safari’s bottom chrome).

```html
<nav class="navbar sticky top-0 z-50 bg-base-200 min-h-12" aria-label="Main navigation">
  <div class="flex-none">
    <a href="/app" class="btn btn-ghost btn-sm text-lg font-bold">Selko</a>
  </div>
  <div class="flex-1"></div>
  <div class="flex-none flex items-center gap-0.5 sm:gap-2">
    <ul class="menu menu-horizontal menu-sm p-0">
      <li><a href="/app">Review</a></li>
      <li><a href="/app/history">History</a></li>
      <li><a href="/app/settings">Settings</a></li>
    </ul>
    <button class="btn btn-ghost btn-sm">Log out</button>
  </div>
</nav>
```

### Design Decisions

- **3 destinations** (Review, History, Settings). Event Detail is a drill-down from Review, not its own nav item.
- **No hamburger / bottom dock.** All screens reachable from the sticky top bar.
- Active link highlighted via DaisyUI's `active` class.
- **No pending count badge** on nav items.
- **Page title**: navbar always shows "Selko"; current section is the active link.
- **Logout**: ghost button in the top bar on all breakpoints (also available via Settings account section).
- **Event Detail**: sticky top bar stays visible; mobile save actions use a fixed bar at `bottom-0`.

---

## App Shell / Layout Component

The shared layout wraps all `/app/*` routes. Implemented in `/app/+layout.svelte`.

### Structure

```html
<!-- /app/+layout.svelte -->
<div class="min-h-screen flex flex-col overflow-x-hidden">
  <Navbar />
  <main id="main-content" class="flex-1">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <slot />
    </div>
  </main>
</div>
```

Key points:
- No bottom-nav padding (`pb-20` removed)
- `flex-1` on main fills available height
- On Event Detail mobile, the fixed action bar sits at the bottom of the viewport

---

## Loading States

### Full Page Loading

Used when the entire page is loading (initial data fetch).

```html
<div class="flex justify-center items-center min-h-[50vh]">
  <span class="loading loading-spinner loading-lg"></span>
</div>
```

### Skeleton Placeholders

Used for cards and sections loading independently. Simple gray boxes matching the expected layout shape.

```html
<div class="space-y-4">
  <div class="skeleton h-24 w-full rounded-lg"></div>
  <div class="skeleton h-24 w-full rounded-lg"></div>
  <div class="skeleton h-24 w-full rounded-lg"></div>
</div>
```

No need for detailed skeleton shapes (lines, circles). Plain gray rectangles matching card dimensions are sufficient.

### Button Loading

Used when an action is in progress (e.g., approving with sync).

```html
<button class="btn btn-primary" disabled>
  <span class="loading loading-spinner loading-sm"></span>
</button>
```

Matches the existing pattern in the Login screen.

---

## Empty States

Standardized pattern for screens with no data to show.

```html
<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
  <h3 class="text-lg font-semibold mb-2">All caught up!</h3>
  <p class="text-base-content/70 max-w-md">
    When new emails are processed, extracted events will appear here for your review.
  </p>
</div>
```

Each screen defines its own heading and description text.

---

## Error States

### Inline Error

Used when a page or section fails to load.

```html
<div class="alert alert-error">
  <svg><!-- error icon --></svg>
  <span>Failed to load events. Retrying...</span>
</div>
```

Errors retry automatically. No manual "Retry" button needed for data loading.

### OAuth Error Toast

The **one case** where toasts are used. OAuth errors happen via redirect and need to work regardless of which page the user lands on.

```html
<div class="toast toast-end">
  <div class="alert alert-error">
    <span>Failed to connect Google account. Please try again.</span>
    <button class="btn btn-sm btn-ghost" on:click={dismiss}>✕</button>
  </div>
</div>
```

This toast is persistent (not auto-dismiss) since the user needs to see it and take action.

### Form Validation

```html
<div class="form-control">
  <label class="label" for="title">
    <span class="label-text">Title</span>
  </label>
  <input type="text" id="title" class="input input-bordered" class:input-error={errors.title} />
  {#if errors.title}
    <span class="text-error text-sm mt-1">{errors.title}</span>
  {/if}
</div>
```

---

## Confirmation Patterns

### No Confirmation for Approve/Reject

Approve and reject actions happen immediately. No modals, no toasts. Events animate out of the queue. Everything goes to Activity History where the user can undo.

### Confirmation for Destructive Settings Actions

Disconnecting a Google account uses a `ConfirmModal`:

```html
<dialog class="modal" bind:this={confirmModal}>
  <div class="modal-box">
    <h3 class="text-lg font-bold">Disconnect Google account?</h3>
    <p class="py-4 text-base-content/70">
      Your existing data will be preserved. You can reconnect later to resume syncing.
    </p>
    <div class="modal-action">
      <button class="btn" on:click={cancel}>Cancel</button>
      <button class="btn btn-error" on:click={confirm}>Disconnect</button>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop">
    <button>close</button>
  </form>
</dialog>
```

---

## Reusable Components

Components to build and share across screens. Each is a Svelte component file in `frontend/src/lib/components/`.

### `AppShell`

Wraps all `/app/*` routes. Provides sticky top navbar (brand + nav + logout).

**Used by:** `/app/+layout.svelte`

**Props:** None (reads route from `$page`)

### `SenderHeader`

Group header for a sender in the Review Queue. Shows sender name, email, and a three-dot overflow menu with group actions.

**Used by:** Review Queue

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `senderName` | `string` | Sender display name |
| `senderEmail` | `string` | Sender email address |
| `eventCount` | `number` | Number of events in this group |

**Events dispatched:** `approveAll`, `rejectAll`

**Three-dot menu items:**
- "Approve all" — approves all events from this sender
- "Reject all" — rejects all events from this sender (destructive)
- "Ignore sender" — disabled (future feature)

### `EventCard`

Card for a single extracted event with inline actions and expandable description.

**Used by:** Review Queue

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `event` | `CalendarEvent` | The event object |

**Events dispatched:** `approve`, `reject`, `edit`

**Behavior:**
- Shows title, date/time (or "All Day"), location, description (truncated)
- Action buttons: Accept (green/success), Edit (primary), Reject (red/error)
- Web: text-label buttons. Android: `OutlinedCard` container with `FilledTonalButton`s (Accept/Reject icon-only, Edit icon + text)
- On approve/reject: dispatches event, parent handles animation and removal

### `IntegrationStatus`

Shows per-service OAuth status within a connected Google account. Used in Settings and in the integration setup screen on the Review Queue.

**Used by:** Settings (Connected Accounts section), Review Queue (integration setup state)

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `integrations` | `Integration[]` | All integration records for the user |
| `setupMode` | `boolean` | True when shown on Review Queue setup (changes layout/CTA) |

**Events dispatched:** `connect`, `disconnect`, `authorize`

### `StatusBadge`

Maps status strings to DaisyUI badge colors.

**Used by:** EventCard, IntegrationStatus, Activity History

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `status` | `string` | The status string |
| `type` | `'event' \| 'integration'` | Which status map to use |

**Status-to-badge mapping:**

| Event Status | Badge Class | Label |
|-------------|-------------|-------|
| `pending_review` | `badge badge-warning` | Pending |
| `approved` | `badge badge-info` | Approved |
| `syncing` | `badge badge-info` | Syncing |
| `synced` | `badge badge-success` | Synced |
| `sync_failed` | `badge badge-error` | Failed |
| `rejected` | `badge badge-ghost` | Rejected |
| `cancelled` | `badge badge-ghost` | Cancelled |

| Integration Status | Badge Class | Label |
|-------------------|-------------|-------|
| `active` | `badge badge-success` | Authorized |
| `expired` | `badge badge-error` | Expired |
| `revoked` | `badge badge-error` | Revoked |
| `error` | `badge badge-error` | Error |
| (not connected) | `badge badge-ghost` | Not Connected |

### `PageHeader`

Page heading with optional back link and action slot. Used on Event Detail for the back arrow and action buttons.

**Used by:** Event Detail

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `title` | `string` | Page title (e.g., "Edit Event") |
| `backHref` | `string \| null` | Back link URL (shows ← arrow if set) |

**Slots:** `actions` — right-aligned action buttons

```html
<PageHeader title="Edit Event" backHref="/app">
  <svelte:fragment slot="actions">
    <button class="btn btn-ghost">Reject</button>
    <button class="btn btn-primary">Approve</button>
  </svelte:fragment>
</PageHeader>
```

### `EmptyState`

Generic empty state with customizable content.

**Used by:** Review Queue (all caught up), Activity History (no activity)

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `heading` | `string` | Main heading text |
| `description` | `string` | Description text |

### `ConfirmModal`

Confirmation dialog for destructive Settings actions.

**Used by:** Settings (disconnect integration)

**Props:**
| Prop | Type | Description |
|------|------|-------------|
| `open` | `boolean` | Whether the modal is visible |
| `title` | `string` | Modal heading |
| `description` | `string` | Explanation text |
| `confirmText` | `string` | Confirm button text (default: "Confirm") |
| `confirmClass` | `string` | Confirm button class (default: "btn-error") |

**Events dispatched:** `confirm`, `cancel`

---

## Action Button Styling

Consistent button styling for event actions across all platforms and screens.

### Color Mapping

| Action | Color | Rationale |
|--------|-------|-----------|
| **Accept/Approve** | Green (success) | Confirmatory — positive outcome |
| **Reject** | Red (error) | Destructive — removal action |
| **Edit** | Primary (purple) | Neutral modification — brand color |

### Platform Styles

| Platform | Accept | Edit | Reject |
|----------|--------|------|--------|
| **Web** | `btn btn-success` (filled green) | `btn btn-outline btn-primary` (outlined) | `btn btn-outline btn-error` (outlined red) |
| **iOS** | `.borderedProminent` + `.tint(.selkoSuccess)` | `.bordered` | `.bordered` + `role: .destructive` |
| **Android** | `FilledTonalButton` green, icon-only | `FilledTonalButton` primary, icon + text | `FilledTonalButton` error, icon-only |

Web and iOS action buttons show **text labels**. Android Accept/Reject use icon-only (platform convention for compact action buttons).

### Other Button Patterns

| Button | Web | iOS | Android |
|--------|-----|-----|---------|
| **Disconnect** | `btn btn-outline btn-error btn-sm` | `.bordered` + `.tint(.red)` | `OutlinedButton` with error color |
| **Log out** | `btn btn-error` | `.borderedProminent` + `.tint(.red)` | `Button` with error color |
| **Undo** | `btn btn-outline btn-sm` | `.bordered` | `OutlinedButton` |
| **Retry** | `btn btn-outline btn-warning btn-sm` | `.bordered` + `.tint(.orange)` | `OutlinedButton` with warning color |

## Android Review Queue Component

**Chosen:** `ElevatedCard` — M3 recommends cards for content with multiple data types and multiple actions. ElevatedCard uses shadow-based separation for a softer visual hierarchy.

**Not suitable:** `ListItem` — M3 says lists are for "homogeneous content that doesn't have many actions"; 3-line max is too constrained.

Each event card wraps in `SwipeToDismissBox` (swipe right = approve, swipe left = reject). Cards are grouped under sender headers in a `LazyColumn`.

---

## Color & Theme

> **Full brand specification:** See `docs/brand-guide.md` for the complete color palette, typography, and visual rules across all platforms.

### DaisyUI Semantic Colors Only

Use DaisyUI's semantic color classes exclusively. **Never use raw Tailwind colors** (no `text-blue-500`, `bg-red-100`, etc.). Custom `selko-light` and `selko-dark` themes are defined in `tailwind.config.js` with the brand color palette. DaisyUI handles light/dark theme switching automatically based on the user's system preference.

**Correct:**
```html
<button class="btn btn-primary">Approve</button>
<span class="text-base-content/70">Secondary text</span>
<div class="bg-base-200">Background section</div>
<div class="alert alert-error">Error message</div>
```

**Incorrect:**
```html
<button class="bg-blue-500 text-white">Approve</button>
<span class="text-gray-500">Secondary text</span>
```

### Text Hierarchy

| Purpose | Class |
|---------|-------|
| Primary text | `text-base-content` |
| Secondary text | `text-base-content/70` |
| Muted/disabled | `text-base-content/50` |

### Background Hierarchy

| Purpose | Class |
|---------|-------|
| Page background | `bg-base-100` |
| Section/card background | `bg-base-200` |
| Active/hover states | `bg-base-300` |

---

## Form Conventions

All forms follow this pattern for consistency with existing Login/Register screens.

### Input Fields

```html
<div class="form-control w-full">
  <label class="label" for="title">
    <span class="label-text">Title</span>
  </label>
  <input
    type="text"
    id="title"
    class="input input-bordered w-full"
    bind:value={title}
  />
  {#if errors.title}
    <span class="text-error text-sm mt-1">{errors.title}</span>
  {/if}
</div>
```

### Select Dropdowns

```html
<div class="form-control w-full">
  <label class="label" for="calendar">
    <span class="label-text">Default Calendar</span>
  </label>
  <select id="calendar" class="select select-bordered w-full" bind:value={calendarId}>
    {#each calendars as cal}
      <option value={cal.id}>{cal.name}</option>
    {/each}
  </select>
</div>
```

### Textareas

```html
<div class="form-control w-full">
  <label class="label" for="description">
    <span class="label-text">Description</span>
  </label>
  <textarea
    id="description"
    class="textarea textarea-bordered w-full"
    rows="3"
    bind:value={description}
  ></textarea>
</div>
```

### Checkboxes

```html
<div class="form-control">
  <label class="label cursor-pointer justify-start gap-3">
    <input type="checkbox" class="checkbox" bind:checked={allDay} />
    <span class="label-text">All day</span>
  </label>
</div>
```

### Submit Buttons

```html
<button class="btn btn-primary w-full md:w-auto" disabled={submitting}>
  {#if submitting}
    <span class="loading loading-spinner loading-sm"></span>
  {/if}
  Save Changes
</button>
```

---

## Accessibility

- **Labels**: every input has a `<label>` with matching `for`/`id`, or the input is wrapped in the label.
- **Button text**: all buttons have descriptive text. Icon-only buttons (mobile action buttons) must have `aria-label`.
- **Color not sole indicator**: status badges include text labels alongside color.
- **Focus management**: after modal open, focus moves to modal. After close, focus returns to the trigger.
- **Keyboard**: modals close on `Escape`. All interactive elements focusable and keyboard-operable.
- **Semantic HTML**: use `<nav>`, `<main>`, `<header>`, `<button>`, `<a>` appropriately. No `<div on:click>`.
- **Alt text**: images and icons used for communication have `alt` or `aria-label`.
- **Touch targets**: 44×44px minimum on mobile.
- **Dark/light mode**: handled automatically by DaisyUI based on system preference. No manual toggle needed.
