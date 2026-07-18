# Selko Brand Guide

The definitive visual reference for Selko. The machine-readable source of truth
is [`design/tokens.json`](../design/tokens.json); platform tests must fail when
an implementation drifts from it. The detailed build specification is
[`docs/specs/warmth-design-system.md`](specs/warmth-design-system.md).

## Personality

Calm, warm, rounded, and quietly capable. Selko should feel like a clear desk:
soft paper surfaces, confident coral actions, restrained metadata, and enough
space for decisions to feel easy.

## Tagline

**“Make life easy.”**

Use this in marketing and brand contexts. Product screens should use task-focused
supporting copy instead of repeating the tagline.

## Warmth palette

| Token | Light | Dark | Usage |
|---|---|---|---|
| paper | `#FBF7F2` | `#1A1613` | Page background |
| surface | `#FFFFFF` | `#241F1B` | Cards, sheets, nav bars |
| subtle | `#F5EEE6` | `#2C2621` | Secondary controls, chips |
| ink | `#2B2622` | `#F2ECE4` | Primary text |
| body | `#4A423B` | `#D8CFC5` | Body text |
| muted | `#746A61` | `#A99E92` | Secondary text |
| faint | `#786E65` | `#9A8F84` | Metadata and placeholders |
| border | `#EDE4DA` | `#322B25` | Card and navigation hairlines |
| divider | `#F2EAE1` | `#322B25` | Internal separators |
| primary | `#E86F52` | `#F0805C` | Coral actions and active navigation |
| rust | `#B4553A` | `#F0805C` | Brand-deep text: overlines, section labels, links. Never destructive. |
| link | `#C9603F` | `#F0805C` | Links |
| amber | `#F0A85C` | `#F0B45C` | Secondary accent |
| success | `#5CA07C` | `#5FBE90` | Accept and connected states |
| changed | `#C97A2E` | `#F0B45C` | Changed / caution state |
| berry (error) | `#AD3650` | `#EE7189` | Errors, failed syncs, destructive actions (reject, ignore, disconnect, logout) |
| info | `#6E655C` | `#B8AC9F` | Quiet informational UI (warm slate; Selko has no loud "info" semantics) |

Dark mode uses borders in place of shadows. Filled dark-mode buttons use dark
ink labels on bright Warmth fills where the contrast requires it.

### Semantic color rules

1. **One hue per meaning.** Coral family = brand, green = positive, amber/ochre
   = caution/changed, berry = danger, warm gray = informational. Rust is a
   darker *text* shade of coral for overlines and labels — it is not a
   semantic color.
2. **Destructive actions always use berry (`error`),** never rust or coral.
   Rust ≈ coral in dark mode, so styling danger with rust collapses it into
   the brand color at night.
3. **Dark mode adjusts lightness, never hue.** Each token has a light/dark
   pair within its own hue family; do not remap one hue onto another.
4. **Destructive controls are ghost/outline by default.** The only filled
   berry button is the confirm button inside a confirmation dialog, so brand
   CTAs (filled coral) and danger stay distinguishable by shape alone.
5. **Filled action content is semantic.** Light coral uses ink `#2B2622`, green
   uses `#12100E`, and berry uses white. Small successful status text uses
   `#3F7D5F`; warning text uses `#9A5C1D`.
6. **NEW is neutral, not successful.** NEW uses `#F5EEE6`/`#6E655C`; CHANGED
   uses `#FDF1E7`/`#9A5C1D`.

## Typography

Figtree is bundled/self-hosted on every platform. Use the available weights
400, 500, 600, 700, and 800. Titles are compact and confident; metadata is
smaller, quieter, and never competes with the decision.

| Style | Size | Weight | Usage |
|---|---:|---:|---|
| Display | 40 | 800 | Marketing only |
| H1 | 30 | 800 | Desktop page titles |
| Screen title | 23–26 | 700–800 | Native screen titles |
| Title | 15–16 | 700 | Card headings and event titles |
| Body | 15 | 400 | Descriptions |
| Caption | 12–13 | 500 | Metadata |
| Overline | 11 | 700 | Uppercase section labels |

## Shape, spacing, and elevation

- Navigation rows and contained icon tiles: 12px radius.
- Buttons, inputs, selects, switch hit containers, and dialogs: 14px radius.
- Cards and sheets on every platform: 20px radius.
- State tags and removable chips only: full pill radius.
- Use the 4px spacing grid. Standard controls are at least 44px/pt/dp high,
  with 16px horizontal padding, 8px content gaps, 20px icons, and 14/700 labels.
  Inputs are 46px high. Every icon-only action has a 44×44 target.
- Light cards use a soft brown-tinted shadow; dark cards use a 1px border and no
  shadow.
- Buttons are sentence case. The interface has no emoji or decorative noise.

## Logo mark

The mark is a coral rounded calendar tile with three small rounded blocks: two
on top and one wide bar below. Use the vector/drawn platform component, never a
bitmap. On coral backgrounds the blocks use paper; on dark backgrounds they use
ink.

## Navigation and screens

- iOS and Android use a surface bottom tab bar with Review, History, and
  Settings. Each screen starts with a title, subtitle, and account avatar.
- Mobile web uses a sticky logo/avatar header and pill tabs below it. There is
  no bottom bar.
- Desktop web uses a fixed 236px sidebar with the logo, navigation, and a footer
  account block with icon logout. Content remains on paper with a max width near
  1120px.
- Log out belongs at the foot of Settings on native surfaces and in the desktop
  sidebar footer; it is not a primary header action.

## Voice and terminology

Brief, direct, and calm. Use “Sign in”, “Sign up”, “Accept”, “Reject”, “Undo”,
and “Log out”. Status vocabulary is Connected, Included, Excluded, Synced,
Failed, Rejected, Cancelled, NEW, and CHANGED. Empty states use a short heading plus one sentence. Errors state
what happened without an apology or exclamation mark.
