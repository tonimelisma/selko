# Review Action Contrast, Sizing and Grouping

**Status:** Planned, not started.

**Date:** 2026-08-09

**Scope:** The Accept / Edit / Reject peer action group and every other peer
action group that shares its CSS/roles, on web, iOS and Android; shared design
tokens; brand and UI reference documentation; the three design-token contract
tests; product screenshots. No backend, database, sync or event-lifecycle
changes.

**Supersedes:** product decisions 5, 8 and 11 of
[`cross-platform-review-accessibility.md`](cross-platform-review-accessibility.md).
Everything else in that spec (one column, 720-unit cap, 48-unit targets, visible
labels, `Accept` copy, native dialogs stay native) still stands.

---

## Outcome

The three Review actions become one solid family that is unmistakably a group,
unmistakably three separate controls, and sized to their labels:

- every button has a **solid fill with a maximum-contrast label** — dark fill
  and white label on the light card, bright fill and near-black label on the
  dark card;
- **no button is ever a neutral close to its background**; the weakest
  button-to-card boundary across both themes is 6.81:1, against a 3:1
  requirement;
- **every label clears 7:1 (AAA)** in both themes;
- buttons are **equal to each other and sized to the widest label in the set**,
  never stretched to the container and never long flat bars;
- the row **never stacks** at any width English supports, and labels never
  truncate or wrap; and
- the same contract governs Review cards, Event Detail, and every other peer
  action group.

---

## Problem

Measured from `frontend/src/app.css` and `design/tokens.json` as they stand.

| Shipped today | Label on fill | Button vs card | Verdict |
|---|---:|---:|---|
| Accept — light `#5CA07C` | 6.12:1 | 3.10:1 | AA only |
| Edit — light `#F5EEE6` | 13.01:1 | **1.15:1** | **Fails WCAG 1.4.11** |
| Reject — light `#AD3650` | 6.14:1 | 6.14:1 | AA only |
| Accept — dark `#5FBE90` | 8.37:1 | 7.19:1 | AAA |
| Edit — dark `#241F1B` | 13.91:1 | **1.00:1** | **Invisible** |
| Reject — dark `#EE7189` | 6.30:1 | 5.72:1 | AA only |

Four distinct defects:

1. **Edit has no visible boundary.** In `selko-dark`, `--color-base-200` and
   `--color-surface` are both `#241f1b`, so `.peer-action-secondary`'s fill is
   byte-identical to the card it sits on — 1.00:1. Its border reaches 1.17:1.
   WCAG 1.4.11 requires 3:1. In light mode the fill is 1.15:1 and the border
   1.26:1, so it fails there too.
2. **Accept is a mid-tone carrying a near-black label.** `#12100E` on `#5CA07C`
   clears AA but misses AAA, and the fill itself is only 3.10:1 against the
   white card — barely separated from what it sits on.
3. **Accept and Reject share a luminance** (1.26:1 in dark mode), so the two
   opposite outcomes are separated by hue alone.
4. **Full-width thirds, then a stack.** `grid-template-columns: repeat(3, 1fr)`
   plus `width: 100%` gives a six-character label a ~200 px slab on desktop, and
   `@media (max-width: 520px)` turns the row into three stacked bars — 168 px of
   button on every card — on every phone and small tablet.

Defect 1 is a latent trap beyond this surface: any control that fills itself
with `base-200` while sitting on a `surface` disappears in dark mode. Audit
`.action-tertiary:hover`, `.date-chip` and `.badge-neutral-warm` while here;
fix only what is a peer action in this increment and note the rest.

---

## Product decisions (locked)

1. **One construction per theme, applied to all three actions.** Light theme:
   solid dark fill, white label. Dark theme: solid bright fill, near-black
   label. The rule is chosen for maximum separation from the surface behind the
   button, and it inverts per theme because the surface does.
2. **Peer actions have equal visual weight.** Review is a triage surface where
   rejecting is as routine as accepting, so Accept is not ranked above its
   peers. Only hue separates the three, always backed by an icon and a word.
3. **No peer action uses a fill or border within 3:1 of its own background.**
   This is a hard floor; the values below all clear 6.8:1.
4. **Buttons are sized to the widest label in the group, not to the container.**
   Equal to each other, leading-aligned, never stretched.
5. **The row never stacks into three identical slabs.** Where a single row is
   geometrically impossible, the fallback is Accept full width with Edit and
   Reject sharing the row beneath.
6. **Labels never truncate and never wrap**, at any width or text scale.
7. **Icons scale down before they disappear**, and disappear only below 297
   units of available width. Because peer actions carry equal weight, the icon
   is the colour-blind fallback cue and must survive phone widths.
8. **Semantic hue mapping is unchanged.** Green = accept, warm neutral = edit,
   berry = reject. Rust and coral remain brand-only and never destructive.
9. **This does not restyle** navigation tabs, badges, state tags, static
   statuses, Show more/less, isolated Retry/Undo/Reprocess, or native system
   dialogs.

---

## Standards basis, and the deliberate departures

Followed:

- Apple HIG recommends equal sizing so options read as one coherent set, a
  hit region of at least 44×44 pt, familiar symbols and concise verb labels:
  <https://developer.apple.com/design/human-interface-guidelines/buttons>.
- Material 3 says a button's width should follow its label and warns explicitly
  against stretching that leaves very little content inside a wide container,
  and against truncating or wrapping label text:
  <https://m3.material.io/components/buttons/guidelines>.
- WCAG 2.2: 1.4.3 text contrast, 1.4.11 non-text contrast (3:1 for component
  boundaries), 1.4.1 colour is not the only cue, 1.4.10 reflow at 320 px,
  2.5.8/2.5.5 target size: <https://www.w3.org/TR/WCAG22/>.

**Departed from, deliberately.** Apple recommends distinguishing the preferred
option by style and keeping prominent buttons to one or two per view, and
advises against giving a destructive action the most prominent role. Decision 2
overrides all three for this surface. Two consequences are accepted and must be
recorded rather than rediscovered:

- Accept and Reject sit at **1.30:1 (light)** and **1.41:1 (dark)** as colour
  blocks. Someone with deuteranopia separates them by icon and label, not by
  shape. This is why decision 7 protects the icons.
- **Reject has no confirmation and no undo.** `handleRejectNew` in
  `frontend/src/routes/app/+page.svelte` sets `status='rejected'` directly; the
  only recovery is a reprocess buried in History. Equal prominence raises the
  cost of a mis-tap, which is why the inter-button gap grows from 8 to 12. See
  "Open question" below.

---

## Shared design contract

### Tokens

Add to `design/tokens.json` under `color.light` and `color.dark`. Putting them
inside `color.{mode}` is deliberate: the existing web contract test already
asserts that *every* manifest colour value appears in `app.css`, so these are
covered for free.

```json
"color": {
  "light": {
    "acceptFill": "#276243",
    "editFill":   "#544A40",
    "rejectFill": "#84203A",
    "actionLabel": "#FFFFFF"
  },
  "dark": {
    "acceptFill": "#7FD9A8",
    "editFill":   "#C9BAA8",
    "rejectFill": "#F0899C",
    "actionLabel": "#12100E"
  }
}
```

Add to `control`:

```json
"control": {
  "peerGap": 12,
  "iconCompact": 16
}
```

Measured contrast — every value below is a hard assertion in the contract tests:

| Role | Light fill | Label | Vs card | Vs paper | Dark fill | Label | Vs card | Vs paper |
|---|---|---:|---:|---:|---|---:|---:|---:|
| Accept | `#276243` | 7.21 | 7.21 | 6.76 | `#7FD9A8` | 11.20 | 9.63 | 10.61 |
| Edit | `#544A40` | 8.64 | 8.64 | 8.10 | `#C9BAA8` | 10.01 | 8.60 | 9.48 |
| Reject | `#84203A` | 9.34 | 9.34 | 8.75 | `#F0899C` | 7.92 | 6.81 | 7.50 |

"Vs paper" matters because the Event Detail mobile action bar sits on paper, not
on a card.

### Roles

`secondary` and `destructiveFilled` keep their names on all three platforms so
existing call sites and one test selector keep working; only their colours
change. A new `accept` role replaces the DaisyUI `btn-success` currently used
for Accept, so peer buttons stop inheriting framework colours.

| Role | Container | Label | Use |
|---|---|---|---|
| `accept` | `acceptFill` | `actionLabel` | Accept |
| `secondary` | `editFill` | `actionLabel` | Edit, Cancel, neutral alternative |
| `destructiveFilled` | `rejectFill` | `actionLabel` | Reject, destructive peer choice |
| `primary` | brand coral | `onPrimary` | Isolated CTA (Accept all, Reconnect) |
| `tertiary` | transparent | ink | Isolated low-priority utilities |
| `destructiveOutline` | transparent + error border | error | Standalone destructive only |

`primary`, `tertiary` and `destructiveOutline` are unchanged.

### Layout and the reflow ladder

Breakpoints are derived from Figtree measured in the browser at 14/700, not
guessed: the widest English label, "Accept", is **48.6 px**.

| Tier | Trigger (available width) | Icon | Padding | Gap | Row width |
|---|---|---:|---:|---:|---:|
| 1 | > 352 | 18 | 16 | 12 | 339 px |
| 2 | ≤ 352 | 16 | 10 | 8 | 283 px |
| 3 | ≤ 296 | none | 10 | 8 | 217 px |

Against the widths the row actually gets:

| Viewport | Row has | Tier | Icons | Result |
|---|---:|---:|---|---|
| 720 px card (desktop) | 626 px | 1 | yes | one row |
| 375 px phone | 311 px | 2 | yes | one row |
| 320 px (WCAG reflow floor) | 256 px | 3 | no | one row |

English therefore never stacks at any supported width. A long-locale label
(German "Bearbeiten" is 75.4 px) cannot hold one row at 320 px without
truncating; that is the only case where the 1+2 fallback from decision 5 fires.

**The action row must span the full card width.** Today it is nested beside the
50 px date chip, which costs 62 px — exactly the margin that forces the stack on
a phone.

---

## WS1 — Shared tokens and documentation

Files: `design/tokens.json`, `docs/brand-guide.md`, `docs/ui/02-screen-specs.md`,
`docs/ui/03-patterns-and-components.md`,
`docs/specs/cross-platform-review-accessibility.md`, `docs/specs/README.md`.

1. Add the four colours per theme and the two control values above.
2. `docs/brand-guide.md`: amend semantic rule 4 (peer groups use one solid
   construction, not a mixed treatment) and rule 5 (light-mode filled peer
   actions carry a **white** label, not `#12100E`; `onSuccess` stays only for
   non-peer success surfaces). Add the four new tokens to the palette table.
3. `docs/specs/cross-platform-review-accessibility.md`: mark decisions 5, 8 and
   11 superseded, with a pointer to this file. Do not delete them — the history
   of why equal-fill was chosen is useful.
4. `docs/ui/02-screen-specs.md` and `03-patterns-and-components.md`: replace the
   full-width equal grid with the intrinsic row plus the ladder table.
5. `docs/specs/README.md`: add this spec to "Active plans".

---

## WS2 — Web

Files: `frontend/src/app.css`, `EventCard.svelte`, `ChangeCard.svelte`,
`routes/app/events/[id]/+page.svelte`, `ConfirmModal.svelte`,
`UndoConflictDialog.svelte`, `IntegrationStatus.svelte`,
`ConnectionRecovery.svelte`, plus the tests listed in WS5.

### The container-query trap

`container-type: inline-size` applies inline-size containment, so a size
container's width can no longer be determined by its contents. It therefore
**cannot** be put on the `width: fit-content` group itself — that combination
collapses the group. The query container must be the **parent**; the group is
`fit-content` inside it. This is the same class of problem
`.peer-action-group--intrinsic` already works around for ConnectionRecovery.

### CSS

```css
:root {
  --action-accept: #276243;
  --action-edit:   #544a40;
  --action-reject: #84203a;
  --action-label:  #ffffff;
  --peer-gap: 12px;
  --icon-compact: 16px;
}

[data-theme='selko-dark'] {
  --action-accept: #7fd9a8;
  --action-edit:   #c9baa8;
  --action-reject: #f0899c;
  --action-label:  #12100e;
}

/* The query container is the wrapper, never the fit-content group. */
.peer-action-wrap { container-type: inline-size; }

.peer-action-group {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--peer-gap);
  width: fit-content;
  max-width: 100%;
}
.peer-action-group[data-peer-count='2'] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.peer-action-group[data-peer-count='1'] { grid-template-columns: minmax(0, 1fr); }

/* Dialog actions keep their conventional trailing alignment. */
.peer-action-group--trailing { margin-inline-start: auto; }

.peer-action-group > :is(.btn, a.btn) {
  width: 100%;
  min-width: 0;
  min-height: var(--control-height);
  height: auto !important;
  justify-content: center;
  white-space: nowrap;
}

.peer-action-accept    { background: var(--action-accept) !important; border-color: var(--action-accept) !important; color: var(--action-label) !important; }
.peer-action-secondary { background: var(--action-edit)   !important; border-color: var(--action-edit)   !important; color: var(--action-label) !important; }
.peer-action-destructive { background: var(--action-reject) !important; border-color: var(--action-reject) !important; color: var(--action-label) !important; }

@container (max-width: 352px) {
  .peer-action-group { gap: var(--control-content-gap); }
  .peer-action-group > .btn { padding-inline: var(--compact-horizontal-padding); gap: 6px; }
  .peer-action-group .peer-icon { width: var(--icon-compact); height: var(--icon-compact); }
}
@container (max-width: 296px) {
  .peer-action-group .peer-icon { display: none; }
}
```

Delete `@media (max-width: 520px)` and both single-column overrides.

### Components

1. `EventCard.svelte` / `ChangeCard.svelte`: move the action group out of the
   date-chip column so it spans the full card content width; wrap it in
   `.peer-action-wrap`; replace `btn btn-success` with `btn peer-action-accept`;
   add `class="peer-icon"` to each action `<svg>`.
2. **Replace the Edit pencil icon.** The current path draws the ferrule
   (`m15 5 4 4`) detached from a hairline body, which reads as a pickaxe. Use a
   body wide enough that the ferrule crosses it, and raise all three action
   icons to `stroke-width` 2.2–2.4 so they match a 14/700 label optically:

   ```html
   <path d="M21.17 6.81a1 1 0 0 0-3.98-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.63l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>
   ```

3. `events/[id]/+page.svelte`: both the desktop and mobile action bars get the
   wrapper and the new accept role. The mobile bar sits on paper — verify
   against the "vs paper" column above.
4. `ConfirmModal.svelte`, `UndoConflictDialog.svelte`: add
   `peer-action-group--trailing` so dialog buttons stay trailing-aligned once
   the group is `fit-content`.
5. `IntegrationStatus.svelte`, `ConnectionRecovery.svelte`: verify only. They
   use `btn-primary` plus `peer-action-destructive`; the primary role is
   unchanged, and `--intrinsic` still needs `container-type: normal`.
6. Preserve every existing accessible name, loading, disabled and
   OAuth-recovery behaviour. Edit stays an `<a>`; only its presentation changes.

---

## WS3 — iOS

Files: `ios/Selko/SelkoControls.swift`, `ios/Selko/Assets.xcassets/`,
`Features/Review/Views/EventCardView.swift`, `EventDetailView.swift`,
`ios/SelkoTests/DesignTokenContractTests.swift`.

1. Add colorsets `SelkoActionAccept`, `SelkoActionEdit`, `SelkoActionReject`,
   `SelkoActionLabel` with both appearances. `ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS`
   generates the `Color.selkoActionAccept` accessors — do **not** hand-write
   duplicate `Color` extensions (causes "invalid redeclaration").
2. `SelkoActionRole`: add `case accept`. Point `accept`, `secondary` and
   `destructiveFilled` at the new colours, all with `.selkoActionLabel`
   foreground. Drop the border overlay for these three; keep it for
   `destructiveOutline`.
3. `SelkoMetrics`: add `peerGap = 12`, `iconCompact = 16`.
4. Add `enum SelkoPeerActionTier { case full, compact, labelOnly }` and put the
   resolved tier in the environment. `SelkoActionLabel` reads it to choose icon
   size or omit the image; it already has `lineLimit(1)` and `fixedSize`, which
   satisfies "never truncate, never wrap".
5. `SelkoPeerActionLayout`: today it splits the full available width and stacks
   on overflow. Change to — measure each tier's intrinsic row width in order,
   adopt the first that fits, place buttons **leading-aligned at that width**
   rather than filling the proposal, and fall back to 1+2 (Accept full width,
   Edit and Reject beneath) only when tier 3 does not fit. Remove
   `.frame(maxWidth: .infinity)` from `SelkoPeerActionGroup`.
6. The tier decision must come from the measured proposal and Dynamic Type, not
   a device-name or size-class check.
7. `EventCardView` / `EventDetailView`: switch Accept to `.accept`; no structural
   change otherwise. Keep swipe actions as redundant shortcuts.

---

## WS4 — Android

Files: `ui/theme/Color.kt`, `ui/theme/Theme.kt` (`SelkoTheme.colors`),
`ui/components/SelkoControls.kt`, `ui/screens/review/EventCardContent.kt`,
`EventDetailScreen.kt`, `ReviewQueueScreen.kt`,
`app/src/test/java/net/melisma/selko/ui/theme/DesignTokenContractTest.kt`.

1. `Color.kt`: add `SelkoActionAccept/Edit/Reject/Label` for both themes and
   expose them through `SelkoTheme.colors`.
2. `SelkoControlMetrics`: add `peerGap = 12.dp`, `iconCompact = 16.dp`.
3. `SelkoActionRole`: add `Accept`; repoint `Accept`, `Secondary` and
   `DestructiveFilled` at the new colours via `ButtonDefaults.buttonColors`.
4. `SelkoButton`: accept a tier so the `Icon` size follows it or is omitted; add
   `maxLines = 1` and `overflow = TextOverflow.Clip` — never `Ellipsis`, which
   would violate decision 6.
5. `SelkoPeerActionGroup`: it already measures text with `rememberTextMeasurer`,
   which is the right foundation. Replace the binary fits/stacked decision with
   the three-tier ladder, drop `Modifier.fillMaxWidth()` and `Modifier.weight(1f)`
   in favour of a `Row` of `Modifier.width(widestSlot)` buttons wrapped to
   content, and replace the `Column` stack with the 1+2 fallback.
6. `EventCardContent` / `EventDetailScreen`: switch Accept to the new role;
   give Event Detail equal widths rather than opposite ends.
7. Existing Android tests assert 44 dp in places — check and update rather than
   leaving contradictory assertions.

---

## WS5 — Tests

Two existing tests **pin the behaviour being removed** and must be changed
before the CSS, or the suite fails for the right reason at the wrong time:

- `frontend/src/lib/components/__tests__/DesignTokenContract.test.js` asserts
  `@media (max-width: 520px)` and `grid-template-columns: minmax(0, 1fr)`.
  Replace with assertions for `.peer-action-wrap`, `container-type: inline-size`,
  `width: fit-content`, and both `@container` breakpoints.
- `frontend/src/lib/components/__tests__/EventCard.test.js:76` asserts
  `data-peer-count="3"`; keep the attribute so this survives.

`frontend/src/routes/app/__tests__/page.test.js:379` selects
`button.peer-action-destructive` — this is why the role class names are kept.
No test selects `.btn-success` or `.peer-action-secondary`, so renaming Accept
to `.peer-action-accept` is safe.

Add to all three contract tests:

- every new manifest colour is present in the platform implementation;
- **label vs fill ≥ 7.0** for accept/edit/reject in both themes (AAA, not the
  4.5 currently asserted);
- **fill vs surface ≥ 3.0 and fill vs paper ≥ 3.0** for all three in both
  themes — the assertion that would have caught the 1.00:1 Edit button;
- `peerGap` and `iconCompact` match the manifest.

Add a web component test that the action group is not a descendant of the date
chip column, and a test asserting no button declares `white-space: normal`.

---

## Definition of done

Per `CLAUDE.md`, scoped to what changed — and this changes all three platforms:

- [ ] Worktree + feature branch (`feat/review-action-contrast`) + PR. This is a
      source code increment, so run the step 0 merged-PR review-comment audit.
- [ ] `uv run pytest backend/tests/ -m "not integration"` — not required, no
      backend files change. Skip.
- [ ] Frontend unit tests + `npm run check` + `./scripts/capture-all-screenshots.sh web`
- [ ] iOS tests + `./scripts/capture-all-screenshots.sh ios`
      (`rm -rf ios/TestResults.xcresult` first; scheme is `iOS`)
- [ ] Android tests + `./scripts/capture-all-screenshots.sh android`
      (canonical Android capture is currently blocked by a repeatable Pixel_8
      crash after APK install — if it recurs, record it rather than silently
      skipping)
- [ ] Verify in both themes at 320 px, 375 px, 720 px and 200% browser zoom, and
      at the largest Dynamic Type / Android font scale
- [ ] `./scripts/merge-and-cleanup.sh <pr>` as the final step

This ships to a server (`frontend`), so the final report must end with the
production-deploy question.

---

## Open question, to decide separately

**Should Reject become undoable?** It currently has no confirmation and no undo,
and this spec deliberately gives it equal prominence beside Accept. The
mitigations here are spatial (12 px gap, neutral Edit sitting between the two
opposites) and they reduce mis-taps rather than making one recoverable. An undo
toast on Review, mirroring the existing History undo, would close it properly.
Out of scope for this increment; do not let it be silently dropped.
