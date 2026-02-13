# Selko Brand Guide

The definitive design specification for all Selko platforms. Every UI decision references this document.

---

## Personality

Minimalist, premium, calm. Think Apple, Stripe, Linear. No visual noise. Every element earns its place.

---

## Tagline

**"Clear your mind."**

References Finnish origin (selko = clear). States the value proposition.

---

## Color Palette

### Selko Blue (Primary)

| Token | Hex | Usage |
|-------|-----|-------|
| primary | `#5B63D3` | Buttons, links, active states (light mode) |
| primary-dark | `#8B91D6` | Primary color in dark mode |
| on-primary | `#FFFFFF` | Text on primary backgrounds |
| primary-hover | `#4A51B8` | Button hover state |
| primary-pressed | `#3C429A` | Button pressed state |
| primary-tint | `#EDEDF9` | Light tinted backgrounds |

### Neutral Grays

Cool-toned with subtle blue undertone.

| Token | Hex | Light usage | Dark usage |
|-------|-----|-------------|------------|
| gray-0 | `#FFFFFF` | Page bg (base-100) | — |
| gray-50 | `#F8F9FB` | Subtle bg | — |
| gray-100 | `#F1F2F6` | Section bg (base-200) | — |
| gray-200 | `#E2E4EB` | Borders (base-300) | — |
| gray-300 | `#C8CBD6` | Disabled elements | — |
| gray-400 | `#9BA0B3` | Placeholder text | Secondary text |
| gray-500 | `#6E7489` | Secondary text | — |
| gray-700 | `#353845` | — | Borders |
| gray-800 | `#24272F` | — | Section bg (base-200) |
| gray-900 | `#1A1C23` | Primary text | Page bg (base-100) |
| gray-950 | `#111318` | — | Deep bg |

### Semantic Colors

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| success | `#2D8659` | `#3DA873` | Approved, synced, connected |
| error | `#C4384B` | `#E05566` | Rejected, failed, destructive |
| warning | `#B8860B` | `#D4A017` | Pending review |
| info | `#5B63D3` | `#8B91D6` | Informational (same as primary) |

---

## Action Color Mapping

Semantic colors for interactive actions, consistent across all platforms.

| Action | Color | Token | Rationale |
|--------|-------|-------|-----------|
| **Accept/Approve** | Green | `success` | Confirmatory — positive outcome |
| **Reject** | Red | `error` | Destructive — removal action |
| **Edit** | Purple | `primary` | Neutral modification — brand color |
| **Disconnect** | Red (outlined) | `error` | Destructive settings action |
| **Log out** | Red (filled) | `error` | Destructive account action |
| **Undo** | Default (outlined) | — | Neutral reversal |
| **Retry** | Orange (outlined) | `warning` | Recovery action |

See `docs/ui/03-patterns-and-components.md` for per-platform button style details.

---

## Typography

### Font Families

| Platform | Font | Notes |
|----------|------|-------|
| Web | Inter | Load from Google Fonts. Weights: 400, 500, 600 only. |
| iOS | SF Pro (system) | Do NOT use Inter on iOS. Use system font. |
| Android | Inter | Bundle as custom font resource. Weights: 400, 500, 600. |

### Type Scale

| Scale | Size | Weight | Line height | Letter spacing |
|-------|------|--------|-------------|----------------|
| display | 36px | 600 | 1.2 | -0.02em |
| h1 | 28px | 600 | 1.3 | -0.015em |
| h2 | 22px | 600 | 1.35 | -0.01em |
| h3 | 18px | 500 | 1.4 | -0.005em |
| body | 15px | 400 | 1.55 | 0 |
| small | 13px | 400 | 1.5 | 0.005em |
| caption | 11px | 500 | 1.45 | 0.02em |

---

## Visual Rules

### Border Radius

2px everywhere. Buttons, inputs, cards, badges, modals.

### Shadows

Almost never. Only exception: login card gets `0 1px 3px rgba(0,0,0,0.06)`.

### Borders

1px solid. `gray-200` in light mode, `gray-700` in dark mode.

### Spacing

4px base grid. All spacing values are multiples of 4px.

---

## Dark Mode

Follows system preference (`prefers-color-scheme`). No manual toggle.

---

## Terminology

All platforms use identical terminology:

| Context | Term |
|---------|------|
| Button (auth) | "Sign in" / "Sign up" |
| Link (auth) | "Log in" / "Sign up" |
| Menu action | "Log out" |
| Event actions (card buttons) | "Accept" / "Reject" |
| Event actions (detail / group) | "Approve" / "Reject" |
| Button casing | Sentence case (not Title Case) |

---

## Brand Voice

- Brief. Direct. Calm.
- No exclamation marks in UI.
- No emoji in UI.
- Sentence case for all buttons and labels.
- Empty states: short heading + one sentence description.
- Errors: state what happened, no apology.

---

## Platform Mapping

### Web (DaisyUI)

Custom `selko-light` and `selko-dark` themes in `tailwind.config.js`. Map brand tokens to DaisyUI semantic colors:

| DaisyUI token | Light value | Dark value |
|---------------|-------------|------------|
| primary | `#5B63D3` | `#8B91D6` |
| primary-content | `#FFFFFF` | `#FFFFFF` |
| base-100 | `#FFFFFF` | `#1A1C23` |
| base-200 | `#F1F2F6` | `#24272F` |
| base-300 | `#E2E4EB` | `#353845` |
| base-content | `#1A1C23` | `#E2E4EB` |
| success | `#2D8659` | `#3DA873` |
| error | `#C4384B` | `#E05566` |
| warning | `#B8860B` | `#D4A017` |
| info | `#5B63D3` | `#8B91D6` |
| neutral | `#6E7489` | `#9BA0B3` |
| neutral-content | `#FFFFFF` | `#1A1C23` |
| --rounded-box | 2px | 2px |
| --rounded-btn | 2px | 2px |
| --rounded-badge | 2px | 2px |
| --tab-radius | 0px | 0px |

### iOS (SwiftUI)

- AccentColor in asset catalog: `#5B63D3` (light), `#8B91D6` (dark)
- System font (SF Pro) — do not override
- Semantic colors via `BrandColors.swift` extension

### Android (Jetpack Compose)

- Custom Material3 color schemes with `dynamicColor = false`
- Inter font bundled as resource
- Full color scheme override for both light and dark themes
