# Cross-Platform Review Layout and Action Accessibility

**Status:** Planned

**Date:** 2026-07-31

**Scope:** Web and mobile web, iOS, Android, shared design tokens, UI reference
documentation, automated accessibility coverage, and product screenshots. No
backend, database, sync, or event-lifecycle changes.

## Outcome

Review is a calm, linear decision surface on every platform:

- sender groups always appear in one vertical column;
- the column remains readable instead of stretching across a wide window;
- Accept, Edit, and Reject are visibly labeled peer actions rather than one
  large labeled action beside ambiguous icon-only controls;
- peer actions use the same filled treatment and equal visual weight while
  retaining semantic color, icon, role, and accessible name;
- controls remain usable at large text sizes, browser zoom, narrow widths,
  tablet widths, foldable widths, and with keyboard, VoiceOver, or TalkBack;
- all button and action targets meet a shared 48 px/pt/dp minimum; and
- the same contract governs Review cards and the pending-event action bar on
  Event Detail across web, iOS, and Android.

This plan supersedes the two-column desktop Review masonry and the mixed
filled/outline Review-action treatment in the implemented Warmth spec.

## Product decisions (locked)

1. **Review is always one column.** New and Changes remain separate vertical
   sections, and sender groups inside each section never form a responsive
   grid or masonry layout.
2. **The Review column is bounded and centered.** Its maximum width is 720
   px on web, 720 pt on iOS, and 720 dp on Android. Below that width, it fills
   the available space with the platform's standard 16-unit side gutters.
3. **The width cap covers the whole Review reading axis.** The Review header,
   recovery card, section headings/counts, sender groups, empty state, and
   Accept-all action align to the same centered column. The surrounding app
   shell and navigation continue to use the full window.
4. **Event Detail is not forced into the Review-column layout.** Its editor can
   retain platform-appropriate adaptive layouts, including the existing iPad
   source/form split. Its pending-event action bar must follow the action-group
   contract below.
5. **Peer actions use one surface treatment.** When adjacent controls represent
   choices for the same item or pending decision, every control in the group is
   filled. Do not mix filled, outline, ghost, or bare-icon treatments in one
   peer group.
6. **Semantic meaning remains redundant.** Accept uses success green plus a
   check and label; Edit uses a neutral/subtle fill plus a pencil and label;
   Reject uses error berry plus an X and label. Color is never the only cue.
7. **Peer actions have equal width.** The normal Review-card row is three equal
   buttons: Accept, Edit, Reject. Event Detail is two equal buttons: Reject,
   Accept. Width equality applies within a group, not across unrelated actions.
8. **All peer actions have visible labels and icons.** Icon-only Accept, Edit,
   or Reject controls are not allowed on Review or Event Detail at any width.
9. **Use `Accept` consistently in visible product copy.** Internal services may
   continue to call the state transition `approve`; visible Review and Event
   Detail actions say `Accept`, not a mixture of Accept and Approve.
10. **The universal minimum button/action target is 48 px/pt/dp.** This
    replaces the current shared 44-unit action token. A platform may render a
    smaller glyph, but the laid-out hit region and spacing must remain at least
    48 units.
11. **Labels reflow; they never disappear or truncate.** At large Dynamic Type,
    large Android font scale, 200% web text/zoom, localization expansion, or a
    narrow container, the action group stacks vertically with full-width
    buttons. Do not fall back to icon-only buttons.
12. **Native system dialogs stay native.** SwiftUI alerts and confirmation
    dialogs, Material date/time pickers, and operating-system menus retain
    their platform roles and presentation. The same-treatment rule applies to
    custom in-content peer action groups, custom bottom bars, and custom web
    dialogs; it does not restyle system-owned controls.
13. **Selected navigation is not a peer action group.** Tabs, segmented
    navigation, switches, menus, and selected/unselected states must continue
    to distinguish the current state.
14. **The entire card is not a substitute for Edit.** A visible Edit control
    must activate detail navigation. Optional row/title navigation may remain
    only if it does not create nested interactive semantics or duplicate focus
    stops.

## Standards basis

- Apple Human Interface Guidelines recommend at least a 44×44 pt hit region,
  clear button purpose, familiar symbols, concise action labels, and avoiding
  confusing size differences between adjacent buttons:
  <https://developer.apple.com/design/human-interface-guidelines/buttons>.
- Apple layout guidance recommends restricting readable content width instead
  of spreading text through the full window:
  <https://developer.apple.com/design/human-interface-guidelines/layout>.
- Android recommends at least 48×48 dp for interactive Compose components:
  <https://developer.android.com/develop/ui/compose/accessibility/api-defaults>.
- WCAG 2.2 requires accessible names to contain visible labels, forbids using
  color as the only cue, requires text to resize without loss, and defines
  target-size criteria:
  <https://www.w3.org/TR/WCAG22/>.

The 48-unit contract intentionally exceeds Apple's and WCAG's minimums so one
cross-platform token meets Android guidance and provides more forgiving touch,
pointer, switch-control, and motor-access targets everywhere.

## Current-state findings

### Shared contract and documentation

- `design/tokens.json` defines `control.minimumTarget` as 44 and has no Review
  maximum-width token.
- `docs/brand-guide.md` says destructive actions are outline by default and
  reserves filled berry for confirmation dialogs. That conflicts with the new
  peer-group rule and needs a narrow exception: destructive actions inside a
  filled peer decision group use a filled error role; standalone destructive
  actions can remain outline/ghost.
- `docs/specs/warmth-design-system.md` explicitly specifies two-column desktop
  Review masonry and Accept plus icon-only Edit/Reject.
- `docs/ui/02-screen-specs.md` describes a full-width one-column list but still
  specifies outlined Edit/Reject and mobile text labels that the current UI
  does not render.
- `docs/ui/03-patterns-and-components.md` preserves the flexible Accept plus
  square icon-button anatomy and mixed destructive treatment.

### Web and mobile web

- `frontend/src/routes/app/+page.svelte` applies `lg:grid-cols-2` independently
  to both New and Changes sender-group collections.
- The authenticated app shell allows roughly 1120 px of content, so merely
  deleting the two grid classes would make cards uncomfortably wide.
- `EventCard.svelte` and `ChangeCard.svelte` render a flexible filled Accept,
  a square neutral Edit, and a square error-colored Reject. The checked-in
  screenshots make Edit and Reject read as outlined icon controls.
- Event Detail renders an outlined Reject beside a filled Accept on desktop and
  mobile.
- `ConfirmModal.svelte`, `UndoConflictDialog.svelte`, and inactive integration
  actions also contain mixed custom action groups. They must be classified and
  brought under the same filled-peer rule when the controls are true adjacent
  choices. Tertiary error-recovery utilities that already share a treatment do
  not need gratuitous restyling.
- Card action accessible names are generic across repeated cards. They need the
  event title as context while preserving the visible action word at the start.

### iOS

- `ReviewQueueView` uses one `List`, but does not explicitly bound the Review
  reading axis on iPad, landscape, or resizable environments.
- `EventCardView` renders labeled filled Accept, icon-only secondary Edit, and
  icon-only outlined Reject.
- `ReviewQueueView` wraps the card in a `NavigationLink` while the card itself
  contains Buttons. Its Edit closure is intentionally empty because the outer
  link owns navigation. This creates nested/competing interactive semantics and
  prevents Edit from being a real standalone labeled action.
- `EventDetailView` renders equal-width controls but mixes outlined Reject and
  filled Approve, and uses inconsistent visible copy.
- `SelkoMetrics.minimumTarget` is 44 and `SelkoActionRole` only provides
  `destructiveOutline`, not a filled destructive peer role.
- Native alerts, confirmation dialogs, swipe actions, and menus already use
  platform roles and should remain system-owned.

### Android

- `ReviewQueueScreen` uses one `LazyColumn`, but it fills the entire available
  width and has no tablet/foldable maximum.
- `EventCardContent` renders a weighted labeled Accept plus bare Edit and Reject
  `SelkoIconButton`s.
- `EventDetailScreen` mixes `DestructiveOutline` Reject and filled Success
  Accept, and distributes them to opposite ends instead of giving them equal
  widths.
- `SelkoControlMetrics.minimumTarget` is 44 dp even though Android guidance is
  48 dp. `SelkoActionRole` lacks a filled destructive role.
- Existing Android tests explicitly assert 44 dp and must be updated rather
  than left as contradictory documentation.
- Material pickers and `AlertDialog` controls remain native. Custom recovery
  and settings action rows need classification under the peer-group rule.

## Shared design contract

### Tokens

Update `design/tokens.json`:

```json
{
  "layout": {
    "reviewMaxWidth": 720,
    "screenGutter": 16
  },
  "control": {
    "minimumTarget": 48,
    "inputHeight": 46,
    "horizontalPadding": 16,
    "compactHorizontalPadding": 10,
    "contentGap": 8,
    "icon": 20
  }
}
```

Do not silently raise `inputHeight` as part of this increment. Inputs are a
separate control audit; their interactive wrapper can still provide a 48-unit
hit region where necessary. This increment changes button/action targets.

Mirror the token values through:

- web custom properties in `frontend/src/app.css`;
- `SelkoMetrics` in `ios/Selko/SelkoControls.swift`; and
- `SelkoControlMetrics` in
  `android/app/src/main/java/net/melisma/selko/ui/components/SelkoControls.kt`.

Extend the existing web, iOS, and Android design-token contract tests so both
`minimumTarget` and `reviewMaxWidth` must match the manifest.

### Peer action roles

Expose the same conceptual roles on all three clients:

| Role | Container | Content | Use |
|---|---|---|---|
| `success` | success fill | on-success | Accept |
| `secondary` | subtle/neutral fill | ink/on-surface | Edit, Cancel, neutral alternative |
| `destructiveFilled` | error fill | on-error | Reject or destructive peer choice |
| `primary` | brand fill | on-primary | Isolated primary CTA such as Accept all |
| `tertiary` | transparent/pressed subtle | ink | Isolated low-priority utilities only |
| `destructiveOutline` | transparent/error border | error | Standalone destructive action only |

Add a filled destructive role to the shared web utility vocabulary, SwiftUI
`SelkoActionRole`, and Compose `SelkoActionRole`. Do not repurpose the brand
coral/rust token for destructive actions.

Every custom role must preserve hover/press, keyboard focus, disabled, loading,
high-contrast, light-mode, and dark-mode states. Disabled buttons retain their
label and icon, remove decorative shadow/glow, and remain distinguishable from
enabled controls without relying only on opacity.

### Peer action group behavior

Create a small platform-local `PeerActionGroup`/layout primitive rather than
duplicating width and reflow rules at every call site. It owns layout, not
business behavior.

Normal mode:

```text
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ ✓  Accept    │  │ ✎  Edit      │  │ ×  Reject    │
└──────────────┘  └──────────────┘  └──────────────┘
```

Constrained or enlarged-text mode:

```text
┌──────────────────────────────────────────────────┐
│ ✓  Accept                                        │
├──────────────────────────────────────────────────┤
│ ✎  Edit                                          │
├──────────────────────────────────────────────────┤
│ ×  Reject                                        │
└──────────────────────────────────────────────────┘
```

Requirements:

- one row when every button can display its icon and complete label;
- equal widths and equal minimum heights in the row;
- 8-unit gap between buttons;
- full-width vertical stack when any label would truncate or the platform's
  accessibility text setting makes the row unsuitable;
- natural height growth; no fixed-height clipping;
- logical source/focus order Accept → Edit → Reject on cards and Reject →
  Accept on Event Detail;
- automatic right-to-left mirroring without changing semantic traversal order;
- no horizontal scrolling; and
- loading state remains inside the activated button without blanking or
  disabling unrelated actions unless the existing mutation rules require it.

The reflow decision must be based on available measured space and text scale,
not an English-only screen-width assumption.

### Labels and accessible names

Visible labels are short verbs: `Accept`, `Edit`, and `Reject`.

Repeated card actions need unique names in the accessibility tree:

```text
Accept Parent-Teacher Conference
Edit Parent-Teacher Conference
Reject Parent-Teacher Conference
```

The visible label must be the leading substring of the accessible name for
speech-control compatibility. Decorative button icons are hidden from
assistive technology when the button label already supplies the name.

Do not put the entire card into one combined accessibility element if doing so
hides the three actions. Announce card content first, then the actions in visual
order. Preserve disabled-state explanation for Accept when Google Calendar
needs reconnection.

## Implementation workstreams

### WS1 — Shared tokens and documentation

Files:

- `design/tokens.json`
- `docs/brand-guide.md`
- `docs/ui/02-screen-specs.md`
- `docs/ui/03-patterns-and-components.md`
- `docs/specs/warmth-design-system.md`
- `frontend/src/app.css`
- `ios/Selko/SelkoControls.swift`
- `android/app/src/main/java/net/melisma/selko/ui/components/SelkoControls.kt`
- all three design-token contract tests

Steps:

1. Add `layout.reviewMaxWidth`, `layout.screenGutter`, and the 48-unit control
   target to the canonical manifest.
2. Add `destructiveFilled` without removing existing standalone roles.
3. Add the local peer-group layout primitive on each platform.
4. Update durable docs to distinguish peer decision groups from standalone
   destructive controls and native system dialogs.
5. Mark this spec Implemented only after every platform has shipped.

### WS2 — Web and mobile web

Primary files:

- `frontend/src/routes/app/+page.svelte`
- `frontend/src/lib/components/EventCard.svelte`
- `frontend/src/lib/components/ChangeCard.svelte`
- `frontend/src/routes/app/events/[id]/+page.svelte`
- `frontend/src/lib/components/ConfirmModal.svelte`
- `frontend/src/lib/components/UndoConflictDialog.svelte`
- `frontend/src/lib/components/IntegrationStatus.svelte`
- `frontend/src/lib/components/ConnectionRecovery.svelte`
- relevant component and route tests
- `frontend/tests/e2e/screenshots.spec.ts` or its seeded fixture path

Steps:

1. Wrap the complete populated Review surface in a centered
   `width: 100%; max-width: 720px` container. Do not cap the desktop sidebar or
   global paper background.
2. Remove both `lg:grid-cols-2` declarations. Give New and Changes a semantic
   single-column sender-group list class used by regression tests.
3. Refactor new and changed cards to the same peer-action component/layout.
   Render visible icon-plus-text labels for all three actions.
4. Give all three actions equal width. Reflow to a full-width vertical stack
   when zoom, localization, or container width would truncate a label.
5. Keep links semantically correct: Edit remains navigation, but receives the
   same filled button presentation and focus treatment as its button peers.
6. Make accessible names event-specific and label-first. Preserve current
   loading, disabled, OAuth-recovery, and click behavior.
7. Convert desktop and mobile Event Detail to equal-width filled Reject/Accept
   groups and standardize visible copy to Accept.
8. Audit custom adjacent decision rows:
   - custom confirmation cancel/confirm choices use filled secondary plus
     filled semantic confirmation;
   - undo-conflict choices use filled secondary navigation/cancel plus filled
     destructive Force undo;
   - inactive integration Disconnect/Reconnect peers use filled destructive
     plus filled primary;
   - recovery provider choices use the same filled family;
   - sender bulk actions and inline error utilities that already share one
     treatment remain consistent, without elevating them unnecessarily.
9. Do not restyle navigation tabs, badges, static statuses, Show more/less,
   isolated Retry/Undo/Reprocess, or modal backdrops as peer decisions.

### WS3 — iOS

Primary files:

- `ios/Selko/Features/Review/Views/ReviewQueueView.swift`
- `ios/Selko/Features/Review/Views/EventCardView.swift`
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Navigation/MainTabView.swift`
- `ios/Selko/Features/Review/Views/ConnectionRecoveryView.swift`
- `ios/Selko/SelkoControls.swift`
- Review, Event Detail, token-contract, UI, and screenshot tests

Steps:

1. Center the Review list and all Review states in a container capped at 720
   pt while retaining 16 pt gutters on compact widths. Verify iPad portrait,
   landscape, split view, and iPhone landscape.
2. Implement the peer group with `ViewThatFits` or an equivalent measured
   layout: equal-width `HStack` first, full-width `VStack` fallback. The stack
   must respond to Dynamic Type rather than a device-name check.
3. Replace icon-only Edit/Reject with `Label("Edit", systemImage: "pencil")`
   and `Label("Reject", systemImage: "xmark")`; keep labeled Accept.
4. Use filled success, secondary, and destructive roles and a 48 pt minimum.
5. Remove Buttons from inside the card's `NavigationLink`. Pass an explicit
   `onEdit(UUID)` navigation closure from `MainTabView`/Review navigation state
   so the visible Edit button performs navigation. Remove the misleading
   card-wide “Double tap to view details” hint unless a separate, nonnested
   card navigation target remains.
6. Preserve swipe actions as redundant expert shortcuts with native roles and
   labels; they do not replace the visible controls.
7. Change Event Detail's visible `Approve` label to `Accept`, use equal-width
   filled Reject/Accept actions, and let the group stack at accessibility text
   sizes.
8. Keep SwiftUI alerts, confirmation dialogs, menus, and swipe-action styling
   native. Recovery provider buttons are custom and should use consistent
   filled roles without first-item/remaining-item surface mismatch.

### WS4 — Android

Primary files:

- `android/app/src/main/java/net/melisma/selko/ui/components/SelkoControls.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventCardContent.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ConnectionRecoveryContent.kt`
- relevant unit, Compose UI, accessibility, and screenshot tests

Steps:

1. Center the Review `LazyColumn` in a parent that fills the window; apply
   `widthIn(max = 720.dp)` before filling the constrained width. Preserve 16 dp
   phone gutters and account for display cutouts/fold hinges through normal
   window insets.
2. Raise `SelkoControlMetrics.minimumTarget` to 48 dp and use
   `minimumInteractiveComponentSize()`/`sizeIn` where custom layouts could
   otherwise overlap expanded touch regions.
3. Add a filled destructive `SelkoButton` role with semantic content colors.
4. Replace Edit and Reject `SelkoIconButton`s on cards with labeled
   `SelkoButton`s. Use a measured adaptive group: equal-weight Row when labels
   fit and full-width Column when font scale or available width requires it.
5. Give each action event-specific semantics without duplicating icon content
   descriptions inside the button.
6. Convert Event Detail's bottom bar to equal-weight filled Reject/Accept
   controls with adaptive vertical fallback.
7. Preserve swipe actions as labeled redundant shortcuts.
8. Keep Material date/time picker and `AlertDialog` button presentation native.
   Audit custom recovery/settings rows and convert only genuine peer choices to
   the shared filled-role family.
9. Rename tests that encode “44 dp” and assert the new 48 dp laid-out bounds,
   not merely an expanded invisible touch region.

## Testing plan

### Shared contract tests

- `frontend/src/lib/components/__tests__/DesignTokenContract.test.js` checks
  web CSS against `minimumTarget = 48` and `reviewMaxWidth = 720`.
- `ios/SelkoTests/DesignTokenContractTests.swift` checks `SelkoMetrics` against
  both manifest values.
- `android/app/src/test/.../DesignTokenContractTest.kt` checks Compose metrics
  against both manifest values and removes the hard-coded 44 expectation.

### Web unit and component tests

- Render at least two sender groups in the same Review lane and assert their
  list uses the single-column semantic class with no responsive two-column
  utility.
- Assert the Review content wrapper has the 720 px maximum-width contract.
- For new and changed cards, assert Accept, Edit, and Reject all have visible
  text, icons hidden from the accessibility tree, the common peer-action class,
  and label-first event-specific accessible names.
- Assert disabled Accept retains its visible label and recovery explanation.
- Assert Event Detail uses two peer actions with the same filled family on both
  desktop and mobile render branches.
- Test the constrained/large-text vertical layout without relying only on a
  screenshot.
- Cover custom modal/integration peer groups changed by the audit.

### iOS tests

- Add view inspection/UI assertions for visible Accept, Edit, and Reject labels,
  48 pt minimum frames, accessible names containing the event title, and
  working Edit navigation.
- Verify the card no longer contains nested button/link semantics.
- Verify compact text uses an equal-width row and accessibility Dynamic Type
  uses a full-width stack without truncation.
- Verify Event Detail exposes Reject and Accept in deterministic focus order.
- Preserve existing ViewModel behavior tests; this increment must not alter
  approval/rejection business calls.

### Android tests

- Update `HistoryScreenTest` and token tests from 44 to 48 dp.
- Compose UI tests assert displayed Accept/Edit/Reject text, event-specific
  semantics, equal row widths when space permits, 48 dp bounds, and vertical
  fallback at high font scale/narrow constraints.
- Event Detail tests assert filled destructive/success roles and equal widths.
- Enable Compose accessibility checks where supported and fail on undersized or
  unlabeled actionable nodes.
- Preserve ViewModel/repository tests; no mutation behavior changes.

### Accessibility scenarios

Required targeted checks:

| Surface | Scenarios |
|---|---|
| Web | 320, 390, 768, 1280, and ultrawide viewport; keyboard-only; 200% zoom/text; light/dark; visible focus; Safari VoiceOver spot check |
| iOS | iPhone portrait/landscape; iPad portrait/landscape/split view; default and accessibility Dynamic Type; light/dark; VoiceOver rotor/focus order |
| Android | compact phone; tablet/foldable width; font scale 1.0 and 2.0; light/dark; TalkBack traversal; accessibility scanner/checks |

For every scenario confirm:

- exactly one Review column;
- the column never exceeds 720 units;
- labels do not truncate, overlap, or disappear;
- actions reflow without horizontal scrolling;
- touch/focus targets do not overlap;
- action meaning survives grayscale/color-vision loss because icon and text
  remain present;
- disabled and loading states are announced; and
- focus order matches visual order.

## Screenshot plan

Update the UI seed/capture fixture so one Review section contains at least two
sender groups. A screenshot with only one group cannot prove the single-column
contract.

Capture and review all platforms because shared tokens and all UI targets
change:

```bash
./scripts/capture-all-screenshots.sh
```

Required evidence:

- web desktop light/dark with two same-lane sender groups stacked;
- web mobile light/dark with visible three-button labels;
- iOS Review and Event Detail light/dark;
- Android Review and Event Detail light/dark; and
- targeted large-text screenshots or test attachments for each platform's
  vertical fallback, even if they are not part of the canonical docs gallery.

All checked-in screenshots must remain at or below 2000 px in each dimension.

## Delivery sequence

Implement as one atomic cross-platform source increment in a dedicated
worktree, for example:

```text
branch:   fix/cross-platform-review-accessibility
worktree: selko-fix-cross-platform-review-accessibility
```

The contract, shared tokens, and all three platform implementations should land
together. Landing the 48-unit token or filled-peer rule on only one platform
would create a knowingly inconsistent shared design system.

Suggested internal order:

1. Shared tokens, roles, contract tests, and durable documentation.
2. Web/mobile web layout and actions.
3. iOS layout, navigation semantics, and actions.
4. Android layout, 48 dp targets, and actions.
5. Cross-platform accessibility scenarios and screenshot fixture.
6. All scoped tests, all-platform screenshots, visual review, PR, squash merge,
   and cleanup.

## Validation commands

Run from the implementation worktree. Follow `docs/testing-guide.md` and the
repository rule that each Bash working-directory change is a separate call.

Web:

```bash
cd frontend
npm run test:unit -- --reporter=json --outputFile=test-results.json
npm run check
```

iOS:

```bash
xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult
```

Remove an existing `ios/TestResults.xcresult` safely before rerunning, as
documented in `CLAUDE.md`.

Android:

```bash
cd android
./gradlew testDebugUnitTest
```

Screenshots:

```bash
./scripts/capture-all-screenshots.sh
```

## Acceptance criteria

- [ ] Web New and Changes sender groups never use multiple columns.
- [ ] Web, iOS, and Android Review content is centered and capped at 720 units.
- [ ] Mobile widths retain 16-unit gutters and no horizontal scroll.
- [ ] Review cards visibly show icon-plus-text Accept, Edit, and Reject on every
      platform.
- [ ] Card peer actions use equal widths and filled success/neutral/error roles.
- [ ] Event Detail uses equal-width filled Reject and Accept actions everywhere.
- [ ] Visible product copy consistently says Accept.
- [ ] Every custom action target is at least 48 px/pt/dp.
- [ ] Labels remain complete at 200% web text/zoom, iOS accessibility Dynamic
      Type, Android 2.0 font scale, and localization expansion.
- [ ] Constrained action groups stack instead of truncating or becoming icons.
- [ ] Accessible names start with the visible label and include event context.
- [ ] Icons are not the sole names and do not create duplicate announcements.
- [ ] iOS Edit navigation no longer relies on Buttons nested inside a
      `NavigationLink`.
- [ ] Color is not the only semantic cue.
- [ ] Native dialogs, menus, pickers, and navigation retain platform behavior.
- [ ] Shared token-contract tests pass with 48 and 720.
- [ ] Web unit tests and `npm run check` pass.
- [ ] iOS tests pass on iPhone 17 Pro.
- [ ] Android unit and Compose UI accessibility tests pass.
- [ ] All-platform screenshots are captured and visually reviewed in light and
      dark mode, including multiple same-lane sender groups.
- [ ] Durable UI docs no longer prescribe two-column Review or icon-only peer
      actions.

## Non-goals

- Changing event approval, rejection, editing, sync, or undo behavior.
- Introducing a backend endpoint or database migration.
- Converting Event Detail into a single-column editor on tablets.
- Replacing native confirmation dialogs, swipe actions, menus, or date/time
  pickers with custom components.
- Redesigning navigation tabs or selected-state styling.
- Raising every input field from 46 to 48 in this increment.
- Adding a desktop list-detail pane or showing two Review columns at any width.
