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
near 1120px. `PageHeader` provides a 30px/800 Figtree title, a muted subtitle,
and an optional actions slot. Review places Accept all and overflow actions in
the header on desktop; mobile places the same actions in a full-width bottom
bar at the end of the list.

## Component anatomy

### Buttons and inputs

- Primary: coral fill, white/light-mode or dark-ink/dark-mode label, brand shadow
  in light mode.
- Secondary: subtle fill with ink label.
- Ghost: transparent with a strong warm border.
- Accept: success fill with a check icon.
- Reject/destructive: rust/error outline or fill as appropriate.
- Inputs: 46px tall, 14px radius, paper fill and warm border; focus uses coral
  border and a restrained coral ring.

Use semantic DaisyUI classes and Warmth utilities such as `bg-surface`,
`shadow-card`, `shadow-popover`, and `shadow-brand`; do not use raw Tailwind
color names.

### Badges and chips

Badges are pill-shaped, uppercase where they represent a state, and use the
Warmth NEW, CHANGED, or neutral palettes. Category chips use a dot and label on
subtle. Sender chips contain a circular remove affordance.

### EventCard

An event card has a date chip, state badge, title, faint metadata, and an action
row: flexible Accept, square edit, and square Reject. Changed events show the
old value struck through in disabled text and the new value in ink.

### SenderHeader and sender rules

Sender groups are surface cards with 20px radius. The header contains a
deterministic two-initial avatar tile, sender name, event count, and a chevron
control. Expanding the control reveals an inline rounded menu with Auto-accept
events, bulk actions, a divider, and Ignore this sender. Rules use removable
chips under Auto-accepted senders and Auto-ignored senders.

### Empty, loading, and error states

Empty states center a 60px subtle tile with a success check, a short heading,
and one calm sentence. Full-page loading uses the Warmth spinner. Inline errors
use `alert-error`; OAuth failures may use a persistent toast because the user
needs to see the redirect result.

### Confirmation and destructive actions

Approve and Reject are immediate and reversible from History. Disconnecting an
account uses `ConfirmModal`. Log out is a ghost-destructive control at the foot
of Settings or in the desktop sidebar footer.

## Accessibility

Every icon-only control has an accessible label. Preserve the route's active
state with `aria-current`, retain stable identifiers used by unit and screenshot
tests, and keep visible focus states on keyboard navigation.
