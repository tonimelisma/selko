# Shared UI Patterns & Components

Shared conventions for the Selko web app. The cross-platform tokens live in
[`docs/brand-guide.md`](../brand-guide.md); the complete implementation brief is
[`docs/specs/warmth-design-system.md`](../specs/warmth-design-system.md).

**Tech stack:** SvelteKit 2 + Svelte 5 + Tailwind/DaisyUI 5.

## Responsive strategy

Use mobile-first styles. Mobile is 320–767px, tablet is 768–1023px, and desktop
is 1024px and above (`lg:`). App content sits on `paper`; cards and sheets sit
on `surface`.

## Navigation shells

The shared `/app/*` layout renders the responsive shell through `Navbar.svelte`:

- Mobile and tablet: sticky logo/avatar header followed by pill tabs for Review,
  History, and Settings. There is no bottom navigation.
- Desktop: fixed 236px surface sidebar with logo, icon-and-label navigation,
  active subtle row, and a footer account block with square logout control.
- Event Detail is a drill-down from Review, not a fourth navigation item.

Keep `aria-current`, route links, and the existing logout handler intact. The
shell must remain usable without JavaScript-dependent duplicated navigation in
the accessibility tree.

## Page layout and headers

Desktop app content uses a paper background, 26–30px gutters, and a max width
near 1120px. The Review reading axis is a centered 720px maximum with 16px
minimum side gutters. `PageHeader` provides a 30px/800 Figtree title, a muted subtitle,
and an optional actions slot. Review places Accept all and overflow actions in
the header on desktop; mobile places the same actions in a full-width bottom
bar at the end of the list.

## Component anatomy

### Buttons and inputs

- Primary: coral fill with ink label, brand shadow
  in light mode.
- Secondary: subtle fill with ink label.
- Destructive outline: transparent with a berry border and label for standalone
  destructive utilities.
- Tertiary: borderless text action with a visible hover/focus surface.
- Peer Accept/Edit/Reject: one solid construction per theme (light: dark fill/white label, dark: bright fill/near-black label; acceptFill #276243/#7FD9A8, editFill #544A40/#C9BAA8, rejectFill #84203A/#F0899C, actionLabel #FFFFFF/#12100E), hue only separates the three (green/warm/berry).
- Inputs: 46px tall, 14px radius, paper fill and warm border; focus uses coral
  border and a restrained coral ring.

Use semantic DaisyUI classes and Warmth utilities such as `bg-surface`,
`shadow-card`, `shadow-popover`, and `shadow-brand`; do not use raw Tailwind
color names.

### State tags and chips

State tags are pill-shaped, uppercase, and use the
Warmth NEW, CHANGED, or neutral palettes. NEW is neutral, never green. Static
statuses are plain icon-and-text indicators and never capsules. Category chips
use a dot and label on subtle. Sender chips contain a separate 48px remove
affordance. Included/Excluded is always a labeled switch.

All custom controls expose hover, pressed, visible keyboard focus, loading, and
disabled states. Disabled controls have no brand shadow or action-colored glow.

### EventCard

An event card has a date chip, state tag, title, faint metadata, and a peer action group: three controls sharing one solid construction per theme, sized intrinsically to the widest label (equal to each other, leading-aligned, `width: fit-content`), never stretched, with `peerGap` 12 (8 when ≤352). The group reflows via 3-tier ladder (full → compact 16px icon/10px pad → label-only) and never stacks into three slabs; fallback 1+2 only for long locales. Changed events show the old value struck through in disabled text and the new value in ink.

### Peer action groups

Adjacent custom choices for the same item use one solid visual family per theme and intrinsically-sized equal controls (`width: fit-content`, leading-aligned). Review cards use Accept → Edit → Reject; Event Detail uses Reject → Accept. Each target is at least 48px high, has a visible label and icon (icon scales to `iconCompact` 16 ≤352, hidden ≤296, never truncates/wraps), and exposes an event-specific accessible name beginning with that visible label. Row spans full card width (not beside date chip). Native dialogs, menus, pickers, swipe actions, and navigation retain their platform-owned presentation.

### SenderHeader and sender rules

Sender groups are surface cards with 20px radius. The header contains a
deterministic two-initial avatar tile, sender name, event count, and a chevron
control. Expanding the control reveals an inline rounded menu with Auto-accept
events, bulk actions, a divider, and Ignore this sender. Rules use removable
chips under Auto-accepted senders and Auto-ignored senders.

### Empty, loading, and error states

Empty states center a 60px subtle tile with a success check, a short heading,
and one calm sentence. Full-page loading uses the Warmth spinner. Inline errors
use `alert-error`; OAuth start and callback failures stay persistently visible
beside the relevant reconnect control after the redirect.

### Confirmation and destructive actions

Accept and Reject are immediate and reversible from History. Disconnecting an
account uses `ConfirmModal`. Log out is a ghost-destructive control at the foot
of Settings or in the desktop sidebar footer.

## Accessibility

Every icon-only control has an accessible label. Preserve the route's active
state with `aria-current`, retain stable identifiers used by unit and screenshot
tests, and keep visible focus states on keyboard navigation.
