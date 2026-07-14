# Warmth Design System — Implementation Plan

**Status:** Proposed (not yet implemented)
**Source of truth:** Claude Design project — [Selko Design System](https://claude.ai/design/p/4efc1206-c41f-4d40-9f06-d52391b09388?file=Selko+Design+System.dc.html)
**Scope:** Replace the current "Selko Blue" (#5B63D3 + Inter) visual identity with the
"Warmth" system (coral #E86F52, warm paper/cream surfaces, Figtree, soft large radii)
across **desktop web, mobile web, iOS, and Android**. No backend or schema changes.

This is a restyle + navigation-shell change. All existing behavior (queries, view
models, routing, i18n, RPCs) stays as-is. Only presentation code changes.

---

## 1. Design overview

The design doc contains four turn sections; use them as the reference mocks:

| Mock | What it shows |
|------|---------------|
| 2a / 2b | Native Review screen, light & dark |
| 3a | Full token + component library (brand, color, type, shape, components) |
| 4a | Native History screen |
| 4b | Native Settings screen |
| 4c | Mobile web Review (top header + pill tabs, no bottom bar) |
| 4d | Desktop web Review (left sidebar shell, 2-column card masonry) |

Key identity points:

- **Logo mark:** a coral rounded square "calendar tile" containing three small
  rounded blocks (two on top — right one at 55% opacity — one wide bar at
  bottom at 85% opacity). Renders on light, dark, and coral backgrounds by
  swapping the block color (paper on coral, ink-colored blocks on dark). Build
  it as a vector/drawn component per platform, not a bitmap.
- **Tagline in-product:** "Make life easy." (chip in brand card — marketing use
  only; do not add to app screens).
- **Personality:** calm, warm, rounded. Cards float on a warm paper background
  with soft brown-tinted shadows in light mode; dark mode uses hairline borders
  instead of shadows.

---

## 2. Design tokens (all platforms)

Values in the mocks are px on a 378-pt phone frame — treat px = pt = dp 1:1.
Round fractional mock sizes (13.5, 12.5) to the nearest token where noted.

### 2.1 Color — light mode

| Token | Hex | Usage |
|-------|-----|-------|
| `paper` | `#FBF7F2` | Page/screen background |
| `surface` | `#FFFFFF` | Cards, sheets, nav bars |
| `subtle` | `#F5EEE6` | Secondary buttons, icon-button bg, date chips, chips |
| `ink` | `#2B2622` | Primary text |
| `body` | `#4A423B` | Body text, ghost-button label |
| `muted` | `#8A7F74` | Secondary text, inactive icons |
| `faint` | `#9A8F84` | Meta text, placeholders |
| `disabled` | `#B7ABA0` | Strikethrough old values, disabled |
| `border` | `#EDE4DA` | Card/nav hairlines |
| `divider` | `#F2EAE1` | Row separators inside cards |
| `border-strong` | `#E7DBCF` | Ghost-button outlines, toggle-off track |
| `primary` | `#E86F52` | Coral — primary buttons, active nav, brand |
| `primary-deep` | `#B4553A` | Rust — overline labels, destructive text, reject |
| `primary-link` | `#C9603F` | Links on light |
| `accent` | `#F0A85C` | Amber — secondary avatar color |
| `success` | `#5CA07C` | Accept buttons, connected dots |
| `changed` | `#C97A2E` | Ochre — CHANGED state |
| `badge-new-bg` / `-fg` | `#EAF3EE` / `#3F7D5F` | NEW badge |
| `badge-changed-bg` / `-fg` | `#FDF1E7` / `#C97A2E` | CHANGED badge |
| `badge-neutral-bg` / `-fg` | `#F5EEE6` / `#8A7F74` | TASK/neutral badge |
| `menu-border` | `#F3DED4` | Inline sender-menu border |

### 2.2 Color — dark mode

| Token | Hex | Usage |
|-------|-----|-------|
| `paper` | `#1A1613` | Page background |
| `surface` | `#241F1B` | Cards (with 1px `border` outline, no shadow) |
| `subtle` | `#2C2621` | Elevated chips, icon buttons, date chips |
| `ink` | `#F2ECE4` | Primary text |
| `muted` | `#A99E92` | Secondary text, inactive icons |
| `faint` | `#8E8378` | Meta text |
| `disabled` | `#6E655B` | Strikethrough old values |
| `border` | `#322B25` | Card outlines, dividers |
| `border-strong` | `#3A332C` | Inline menu border |
| `primary` | `#F0805C` | Coral (brightened) — buttons, active nav |
| `on-primary` | `#1A1613` | Text/icon on coral (dark mode buttons are dark-on-bright) |
| `accent` | `#F0B45C` | Amber |
| `success` | `#5FBE90` | Accept buttons — content color `#12100E` |
| `changed` | `#F0B45C` | CHANGED fg; badge bg `rgba(240,180,92,0.16)` |

Light mode keeps white/near-white content on filled buttons; **dark mode inverts
to dark ink on bright fills** (see mock 2b: Accept-all is `#F0805C` with `#1A1613`
text, Accept is `#5FBE90` with `#12100E` text).

### 2.3 Typography

Font: **Figtree** (Google Fonts, SIL OFL, weights 400–800) on **all platforms**,
bundled/self-hosted per platform (see §4.1, §5.2, §6.1).

| Style | Size / weight / tracking | Usage |
|-------|--------------------------|-------|
| Display | 40 / 800 / -3% | Marketing only |
| H1 | 30 / 800 / -2.5% | Desktop page titles |
| H2 / screen title | 23 / 700 / -2% | Native screen titles use 26/800 per mocks — acceptable range 23–26 |
| Title | 16 / 700 | Card headings, event titles (15 in dense lists is fine) |
| Body | 15 / 400 | Descriptions |
| Caption | 12.5 / 500 | Meta lines (round to 12 or 13 where the platform needs integers) |
| Overline | 11 / 700 / +8% / UPPERCASE | Section labels — colored `primary-deep` (light) / `primary` (dark) |

Button labels: 13–14.5 / 700.

### 2.4 Shape

| Token | Radius | Usage |
|-------|--------|-------|
| `sm` | 8 | — (rare) |
| `md` | 14 | Buttons (44–48 h), inputs, connect buttons |
| `lg` | 20 | Cards on web (22 on native card lists), empty states |
| `pill` | 999 | Badges, chips, toggles, pill tabs |

Component-specific (from mocks, keep): small action buttons 36 h / r11,
icon buttons 32–40 sq / r10–12, date chip r13, avatar tile r12–13, inline
sender menu r15, nav items (sidebar) r12.

### 2.5 Spacing & elevation

- 4-pt base scale: 4 / 8 / 12 / 16 / 24 / 32. Card internal padding 14–16;
  screen gutters 15–16 (native), 30 (desktop content area).
- Elevation (light mode only):
  - `card`: `0 2px 12px -6px rgba(80,60,45,0.28)`
  - `popover`: `0 12px 28px -14px rgba(80,60,45,0.40)`
  - `brand` (coral CTAs): `0 10px 20px -8px rgba(232,111,82,0.60)`
- Dark mode: **no shadows** — 1px `border` outlines on cards instead.

### 2.6 Component anatomy (shared across platforms)

Build these to match section 05 of mock 3a:

1. **Buttons** — Primary (coral fill, white/on-primary label, brand shadow),
   Secondary (`subtle` fill, ink label), Ghost (transparent, 1.5px
   `border-strong` outline, `body` label), Accept (success fill + check icon),
   square icon buttons (edit ✎ / reject ✕ on `subtle`).
2. **Inputs** — 46 h, r14, `paper` bg + 1.5px `border` at rest; focus = white bg,
   1.5px coral border, 3px ring `rgba(232,111,82,0.14)`.
3. **Toggle** — 44×26 pill; on = coral track/white thumb, off = `border-strong`
   track. (Native platforms may use the platform switch tinted coral.)
4. **Badges** — NEW / CHANGED / neutral pill badges (10–11 / 700, pill), coral
   count badge.
5. **Chips** — category chip (dot + label on `subtle`), removable sender chip
   (label + circular ✕ affordance on `border-strong`).
6. **Date chip** — 48–50 w column: month (10/700, coral, tracked caps) over
   day (19–20/800 ink), `subtle` bg, r13. Amber variant for CHANGED senders.
7. **Avatar tile** — rounded-square (r12–13) with 1–2 initials, white text,
   bg deterministically picked from [coral, amber, success] by sender-name hash.
   User account avatar is a coral **circle** with initials.
8. **Event card row** — date chip · (badge line) · title · meta line ·
   action row [Accept (flex) · edit 36sq · reject 36sq]. CHANGED rows show
   `old (strikethrough, disabled color) → new (600 weight, ink)`.
9. **Sender group card** — surface card r20–22; header row = avatar tile,
   name (15/700) + count line (12, faint), chevron icon-button; event rows
   separated by `divider`; header menu (chevron tap) expands **inline** panel
   (r15, `menu-border` outline): "Auto-accept events" + toggle, divider,
   "Ignore this sender" in `primary-deep`.
10. **Empty state** — centered 60sq r20 `subtle` tile with success check,
    "All caught up" (18/800), one-line explainer (14, muted).
11. **Accept-all bar** — full-width coral CTA (46–48 h, r14–15, brand shadow)
    plus 48sq `subtle` "⋯" overflow button (native/mobile web); on desktop it
    lives in the page header (44 h, r14).

---

## 3. Navigation shells

| Surface | Shell |
|---------|-------|
| Native iOS/Android | Bottom tab bar, 3 tabs: Review · History · Settings. Active = coral icon+label, inactive = `faint`. White/`surface` bar, top hairline `border`. Screen header = large title (26/800) + subtitle (13.5, muted) + 40sq coral circle avatar right. **Logout moves to the foot of Settings** (ghost destructive button) — remove it from any nav/header if present. |
| Mobile web (<1024px) | Top header: logo mark + wordmark left, coral avatar circle right. Below: pill-tab row (Review / History / Settings), active pill = coral fill white label; hairline under the row. No bottom bar. |
| Desktop web (≥1024px) | Fixed left sidebar 236px, `surface` bg, right hairline: logo+wordmark top; nav list (icon + label, r12 rows, active = `subtle` bg + `primary-deep` text); footer pinned bottom = avatar, name/email, square logout icon-button. Content area on `paper`, 26–30px padding, max-width ~1120 with 2-column masonry for sender cards. |

Tab icons (stroke style, 1.6–1.8 weight): Review = 3-line list; History =
clock; Settings = two sliders. Reproduce the inline SVGs from the design doc.

---

## 4. Web implementation (SvelteKit + Tailwind 4 + DaisyUI 5)

All web work in a worktree, e.g. branch `feat/warmth-web`, worktree
`selko-feat-warmth-web`.

### 4.1 Theme + font (`frontend/src/app.css`)

1. Replace `@fontsource-variable/inter` with `@fontsource-variable/figtree`
   (`npm i @fontsource-variable/figtree`, remove the Inter dep) and update the
   `html { font-family }` rule. Keep the self-hosting approach (Safari content
   blockers — see comment in file).
2. Rewrite both DaisyUI theme blocks (`selko-light`, `selko-dark`):

   ```css
   @plugin "daisyui/theme" {
     name: 'selko-light';
     default: true;
     color-scheme: light;
     --color-primary: #E86F52;          /* coral */
     --color-primary-content: #FFFFFF;
     --color-secondary: #B4553A;        /* rust — overlines, destructive text */
     --color-secondary-content: #FFFFFF;
     --color-accent: #F0A85C;           /* amber */
     --color-accent-content: #FFFFFF;
     --color-neutral: #8A7F74;          /* muted */
     --color-neutral-content: #FFFFFF;
     --color-base-100: #FBF7F2;         /* paper — page bg */
     --color-base-200: #F5EEE6;         /* subtle */
     --color-base-300: #EDE4DA;         /* border */
     --color-base-content: #2B2622;     /* ink */
     --color-info: #C9603F;
     --color-info-content: #FFFFFF;
     --color-success: #5CA07C;
     --color-success-content: #FFFFFF;
     --color-warning: #C97A2E;
     --color-warning-content: #FFFFFF;
     --color-error: #B4553A;
     --color-error-content: #FFFFFF;
     --radius-selector: 999px;  /* toggles, badges */
     --radius-field: 14px;      /* buttons, inputs */
     --radius-box: 20px;        /* cards, modals */
   }
   ```

   `selko-dark` equivalents: primary `#F0805C` (content `#1A1613`), base-100
   `#1A1613`, base-200 `#241F1B`, base-300 `#322B25`, base-content `#F2ECE4`,
   neutral `#A99E92`, success `#5FBE90` (content `#12100E`), warning/accent
   `#F0B45C` (content `#1A1613`), error `#F0805C` (content `#1A1613`), same radii.
3. Cards use `bg-white` in light mode which DaisyUI can't express with base
   tokens alone (base-100 is now paper, not white). Add two custom utility
   variables in `app.css` under each theme: `--color-surface`
   (`#FFFFFF` / `#241F1B`) and register a `bg-surface` utility via Tailwind
   `@theme` / `@utility`, or simply keep cards on `bg-base-100`… **Decision:
   add `--color-surface` + `@utility bg-surface`** so page (`bg-base-100`) and
   card (`bg-surface`) differ, matching the mock. Also add the three shadow
   utilities (`shadow-card`, `shadow-popover`, `shadow-brand`) with the values
   from §2.5, applied light-mode only (wrap in `[data-theme='selko-light'] &`
   or use color-mix on a shadow-color variable).

### 4.2 App shell (`frontend/src/routes/app/+layout.svelte`, `Navbar.svelte`)

Replace the single top `Navbar.svelte` with a responsive shell per §3:

- New `frontend/src/lib/components/AppShell.svelte` (or refactor Navbar):
  - `lg:` breakpoint and up → render `SidebarNav.svelte` (fixed 236px column,
    logo, nav links from the same `navLinks` derived list, footer user block
    with logout icon-button) + `<main>` on paper with 2xl max width.
  - Below `lg` → sticky header (logo + avatar) + pill tab row.
- New `frontend/src/lib/components/LogoMark.svelte` — the calendar-tile mark as
  inline SVG/divs, prop `size`, prop `variant: 'light'|'dark'|'onBrand'`.
- Avatar: coral circle with user initials derived from the session email
  (first two chars of local part, uppercased) — small helper in `$lib`.
- Keep `aria-current`, i18n keys (`nav.*`), and the logout handler exactly as
  today; update `Navbar.test.js` (or add `AppShell.test.js`) for both layouts.

### 4.3 Screens & components (all under `frontend/src/lib/components/` and `frontend/src/routes/app/`)

Restyle in place — do not rename data props:

| File | Changes |
|------|---------|
| `EventCard.svelte` | New row anatomy: date chip, NEW/CHANGED badge, title 15/700, meta 12.5 faint, action row (Accept success button + ✎ + ✕ icon buttons). CHANGED diff line with strikethrough → new. |
| `SenderHeader.svelte` | Avatar tile (initials + hash color), name + count, chevron icon-button; expanded inline menu = auto-accept toggle + "Ignore this sender". |
| `SenderRulesPanel.svelte` | Removable chips (§2.6.5) under "Auto-accepted senders" / "Auto-ignored senders" overline labels. |
| `StatusBadge.svelte` | Map statuses to the new badge palette (§2.1). |
| `EmptyState.svelte` | §2.6.10 anatomy. |
| `PageHeader.svelte` | Desktop: H1 30/800 + subtitle; actions slot right (Accept all + ⋯). |
| `ConfirmModal.svelte`, `ErrorAlert.svelte`, `LoadingSpinner.svelte`, `IntegrationStatus.svelte` | Recolor to theme tokens only. |
| `routes/app/+page.svelte` (Review) | Desktop: 2-col `columns-2` masonry of sender cards + header CTA. Mobile: single column + full-width Accept-all bar at list end. |
| `routes/app/history/+page.svelte` | Two overline-labeled sections: "Dispositioned" (icon tile ✓ green / ✕ rust, status word, NEW/CHANGED pill, title, source · time, ghost **Undo** button) and "Emails processed" (subject, sender · account · time, outcome dot line — green "n events added" / neutral "No event found" / rust "Failed — reason", ghost **Reprocess** where applicable). Match mock 4a. |
| `routes/app/settings/+page.svelte` | Match mock 4b top-to-bottom: "Connect an account" (two ghost cards Google / Microsoft), "Connected accounts" cards (provider tile, email, status dot line, Disconnect ghost-destructive / Reconnect coral; nested "Folders scanned" rows with Scanned coral pill-button vs Excluded ghost + rationale caption), "Target calendar" radio card, sender chips sections, ghost-destructive **Log out** at the foot. |
| `routes/login`, `routes/register` | Recolor to tokens; coral primary CTA; paper bg; centered surface card r20. |

Rules: **DaisyUI semantic classes only** (no raw Tailwind palette colors);
`svelte-check` is strict — keep JSDoc types.

### 4.4 Web DoD

- `cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json`
- `npm run check`
- `./scripts/capture-all-screenshots.sh web` and visually review (light+dark,
  desktop+mobile widths).

Suggested split: **PR 1** tokens + font + shell; **PR 2** Review/History/
Settings/auth screens. Each ≤ ~500 lines of diff where practical.

---

## 5. iOS implementation (SwiftUI)

Branch `feat/warmth-ios`, worktree `selko-feat-warmth-ios`.

### 5.1 Colors — asset catalog only

Add color sets to `ios/Selko/Assets.xcassets` (each with Any/Dark appearance).
They auto-generate `Color.<name>` extensions — **do not** write manual
`Color` extensions (invalid-redeclaration risk, see `CLAUDE.md`):

| Color set | Light | Dark |
|-----------|-------|------|
| `AccentColor` (update) | `#E86F52` | `#F0805C` |
| `SelkoPaper` | `#FBF7F2` | `#1A1613` |
| `SelkoSurface` | `#FFFFFF` | `#241F1B` |
| `SelkoSubtle` | `#F5EEE6` | `#2C2621` |
| `SelkoInk` | `#2B2622` | `#F2ECE4` |
| `SelkoMuted` | `#8A7F74` | `#A99E92` |
| `SelkoFaint` | `#9A8F84` | `#8E8378` |
| `SelkoBorder` | `#EDE4DA` | `#322B25` |
| `SelkoDivider` | `#F2EAE1` | `#322B25` |
| `SelkoOnPrimary` | `#FFFFFF` | `#1A1613` |
| `SelkoSuccess` (update) | `#5CA07C` | `#5FBE90` |
| `SelkoOnSuccess` | `#FFFFFF` | `#12100E` |
| `SelkoWarning` (update) | `#C97A2E` | `#F0B45C` |
| `SelkoError` (update) | `#B4553A` | `#F0805C` |
| `SelkoRust` | `#B4553A` | `#F0805C` |
| `SelkoBadgeNewBg` / `Fg` | `#EAF3EE` / `#3F7D5F` | `rgba(95,190,144,0.16)` / `#5FBE90` |
| `SelkoBadgeChangedBg` / `Fg` | `#FDF1E7` / `#C97A2E` | `rgba(240,180,92,0.16)` / `#F0B45C` |

Update the doc comment in `ios/Selko/BrandColors.swift` to describe the new
palette (or fold constants there if any non-catalog values are needed, e.g.
shadow colors).

### 5.2 Typography & shape

- **Bundle Figtree** (SIL OFL — free to embed):
  1. Download the static TTFs and add them under `ios/Selko/Fonts/`
     (`Figtree-Regular.ttf`, `-Medium`, `-SemiBold`, `-Bold`, `-ExtraBold`).
     The synced root group should pick them up as resources; verify in
     Build Phases → Copy Bundle Resources after adding.
  2. Declare them in `ios/Selko/Info.plist` under `UIAppFonts` (one array
     entry per file).
  3. Add `ios/Selko/SelkoTypography.swift` (new file — auto-discovered, no
     pbxproj edit) exposing the §2.3 scale as static `Font`s. **Always use
     `Font.custom(_:size:relativeTo:)`** so Dynamic Type scaling keeps
     working, e.g. screen title
     `Font.custom("Figtree-ExtraBold", size: 26, relativeTo: .largeTitle)`,
     title `Font.custom("Figtree-Bold", size: 15, relativeTo: .body)`,
     overline `Font.custom("Figtree-Bold", size: 11, relativeTo: .caption)`
     + `.kerning(0.9)` + uppercase.
  4. Sanity-check the PostScript names at runtime once
     (`UIFont.familyNames` dump in a debug build, or just verify rendering in
     screenshots) — a typo in the custom-font name silently falls back to
     the system font.
- Radii/shadows: add `SelkoShape` constants (card 22, button 14, smallButton 11,
  chip pill). Light-mode card shadow
  `.shadow(color: Color(red:0.31,green:0.24,blue:0.18).opacity(0.28), radius: 6, y: 2)`
  — gate on `colorScheme == .light`; dark mode uses
  `.overlay(RoundedRectangle...stroke(Color.selkoBorder))`.

### 5.3 Views

| File | Changes |
|------|---------|
| `Navigation/MainTabView.swift` | 3 tabs Review/History/Settings, coral tint, surface bar. Header pattern (large title + subtitle + avatar circle) per screen. |
| `Features/Review/Views/ReviewQueueView.swift`, `SenderGroupView.swift`, `EventCardView.swift` | Sender card + event row anatomy (§2.6.8–9), Accept-all bar pinned under list, empty state (§2.6.10). |
| `Features/Review/Views/EventDetailView.swift`, `IntegrationSetupView.swift` | Recolor; inputs per §2.6.2. |
| `Features/History/Views/HistoryView.swift` | Mock 4a: Dispositioned + Emails processed sections, Undo/Reprocess buttons. |
| `Features/Settings/Views/SettingsView.swift`, `SenderRulesView.swift` | Mock 4b: connect buttons, account cards + folder rows, target-calendar radio list, sender chips, Log out ghost-destructive at foot. |
| `Features/Auth/Views/LoginView.swift`, `RegisterView.swift` | Paper bg, surface card, coral CTA, logo mark. |
| New `Core/…/SelkoLogoMark.swift` (SwiftUI shape-drawn) | §1 logo. |

Pure SwiftUI; no UIKit imports.

### 5.4 iOS DoD

- `rm -rf ios/TestResults.xcresult` then
  `xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult`
- `./scripts/capture-all-screenshots.sh ios` and review light/dark.

---

## 6. Android implementation (Jetpack Compose + Material3)

Branch `feat/warmth-android`, worktree `selko-feat-warmth-android`.

### 6.1 Fonts

Download Figtree static weights → `android/app/src/main/res/font/` as
`figtree_regular.ttf`, `figtree_medium.ttf`, `figtree_semibold.ttf`,
`figtree_bold.ttf`, `figtree_extrabold.ttf` (lowercase+underscores rule).
Remove the `inter_*.ttf` files once nothing references them.

### 6.2 Theme files (`ui/theme/`)

- `Color.kt` — replace the palette wholesale with §2.1/§2.2 (keep the
  `Selko*`/`Selko*Dark` naming convention so call sites keep compiling where
  names match; add new tokens: `SelkoPaper`, `SelkoSubtle`, `SelkoRust`,
  badge colors, etc.).
- `Theme.kt` — Material3 mapping (`dynamicColor = false` stays):
  - light: `primary=#E86F52`, `onPrimary=#FFFFFF`, `primaryContainer=#F5EEE6`,
    `secondary=#B4553A`, `tertiary=#F0A85C`, `background=#FBF7F2`,
    `onBackground=#2B2622`, `surface=#FFFFFF`, `surfaceVariant=#F5EEE6`,
    `onSurfaceVariant=#8A7F74`, `outline=#E7DBCF`, `outlineVariant=#F2EAE1`,
    `error=#B4553A`.
  - dark: `primary=#F0805C`, `onPrimary=#1A1613`, `background=#1A1613`,
    `surface=#241F1B`, `surfaceVariant=#2C2621`, `onSurface=#F2ECE4`,
    `onSurfaceVariant=#A99E92`, `outline=#3A332C`, `outlineVariant=#322B25`,
    `error=#F0805C`, `onError=#1A1613`.
  - Success/accept isn't a Material3 slot — keep the existing extended-color
    pattern (`SelkoSuccess*`) updated to `#5CA07C`/`#5FBE90` (+ on-colors).
- `Type.kt` — Figtree `FontFamily`; text styles per §2.3
  (`headlineMedium` 26/ExtraBold −0.02em screen titles, `titleMedium` 15–16/Bold,
  `bodyMedium` 15/Normal, `labelSmall` 11/Bold caps +0.08em, etc.).
- Add `Shape.kt` if missing: `small=8`, `medium=14`, `large=20` (cards 22 via
  explicit `RoundedCornerShape(22.dp)` where needed).

### 6.3 Screens & components

| File | Changes |
|------|---------|
| `ui/components/SelkoBottomNavigation.kt` | 3 items, coral selected / faint unselected, surface container, top hairline. |
| `ui/navigation/MainScaffold.kt` | Screen header (large title + subtitle + coral avatar circle). |
| `ui/screens/review/*` (`ReviewQueueScreen`, `EventCardContent`, `EventDetailScreen`, `IntegrationSetupContent`) | Sender cards, event rows, Accept-all bar, empty state per §2.6 / mock 2a-b. |
| `ui/screens/history/HistoryScreen.kt` | Mock 4a sections + Undo/Reprocess. |
| `ui/screens/settings/SettingsScreen.kt` | Mock 4b layout, Log out at foot. |
| `ui/screens/auth/*` | Paper bg, surface card, coral CTA, logo mark composable (new `ui/components/SelkoLogoMark.kt`). |

Card elevation: light `shadowElevation` small (2–3.dp) with default ambient
color, or `Modifier.shadow` w/ spot color `#503C2D`; dark = `border` stroke,
zero elevation. Material3 only; icons beyond basics need
`material-icons-extended` (or draw the three nav icons as vector drawables from
the design's SVG paths — preferred, they're tiny).

### 6.4 Android DoD

- `cd android && ./gradlew testDebugUnitTest`
- `./scripts/capture-all-screenshots.sh android` and review light/dark.

---

## 7. Docs & follow-through

- Rewrite `docs/brand-guide.md` for the Warmth system (palette tables above,
  Figtree typography on all platforms, shape, logo construction, per-platform
  notes). Direct-to-main docs edit, ideally merged alongside the
  first web PR so the guide never contradicts shipped UI.
- Update `docs/ui/03-patterns-and-components.md` component anatomy references.
- After all platforms land, run `./scripts/capture-all-screenshots.sh` once for
  a full refresh if shared seed data changed (it shouldn't).
- Mark this spec **Implemented** and fold durable content into the brand guide.

## 8. Suggested increment order

1. **Web PR 1** — tokens, Figtree, AppShell/Sidebar/pill-tabs, LogoMark (+ brand-guide doc update on main).
2. **Web PR 2** — Review, History, Settings, auth screens + component restyles.
3. **iOS PR** — asset colors, typography/shape helpers, all views.
4. **Android PR** — fonts, theme files, all screens.

Platforms 3 and 4 are independent of each other and of web PR 2; they can run
as parallel worktrees. Each PR follows the scoped DoD (`CLAUDE.md`): local
platform tests are the gate, `./scripts/merge-and-cleanup.sh <pr>` to land.

## 9. Acceptance checklist (per platform)

- [ ] Light and dark both match mocks 2a/2b (Review), 4a (History), 4b (Settings).
- [ ] Dark mode uses borders, not shadows; filled buttons are dark-ink-on-bright.
- [ ] No remaining `#5B63D3`/Selko-Blue or Inter references (`grep -ri '5B63D3\|8B91D6\|inter' <platform dir>`).
- [ ] Overlines use rust (light) / coral (dark) — never coral text on white body copy (contrast).
- [ ] Navigation: bottom tabs (native) / pill tabs (mobile web) / sidebar (desktop) with logout placement per §3.
- [ ] Unit tests updated where markup/classes are asserted; bug-free `npm run check` on web.
- [ ] Screenshots captured via `./scripts/capture-all-screenshots.sh <platform>` and reviewed.
