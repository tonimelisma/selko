"""Lint: an .accessibilityIdentifier on a container erases its children.

Applied to a container, that modifier does not name the container -- it
overwrites the identifier of every accessibility element inside it. This shipped
three times:

  * SettingsView stamped "connectedAccountsSection" onto all three provider rows
    and their buttons.
  * SettingsView stamped "emailFoldersSection" onto every folder toggle.
  * EventCardView stamped "eventCardContainer" onto the event title and all
    three card actions -- a real VoiceOver defect, since Accept/Edit/Reject then
    shared one identifier instead of naming their event. It also erased
    "eventTitle", which left a UI test skipping every assertion it claimed to
    make behind `guard ... else { return }`.

Each instance was found by hand, days apart, after a test failed for reasons
that looked unrelated. An import-graph-style check finds the whole class at once.

This lives in the backend suite because that is the one gate that always runs;
a rule enforced only where someone remembers to look is not enforced.
"""

from __future__ import annotations

import re
from pathlib import Path

IOS_ROOT = Path(__file__).resolve().parent.parent.parent / "ios" / "Selko"

# Modifiers that mark a view as a single leaf element. Applying an identifier to
# a container is correct when the container is *also* collapsed into one element,
# because then there are no children left to clobber.
SAFE_MARKERS = (
    # Collapses the subtree into one element deliberately -- there are no child
    # identifiers left to clobber, so naming it is correct.
    ".accessibilityElement(children: .ignore)",
    ".accessibilityElement(children: .combine)",
    # Keeps children as separate elements and names the container itself. This
    # is the fix for a container that legitimately wants an identifier while its
    # buttons keep theirs.
    ".accessibilityElement(children: .contain)",
)

IDENTIFIER = re.compile(r"^\s*\.accessibilityIdentifier\(")
CONTAINER_CLOSE = re.compile(r"^(\s*)\}\s*$")
# Only *layout* containers hold multiple accessibility elements. A Button or a
# Toggle already is one element, so naming it is correct and must not be flagged.
CONTAINER_OPEN = re.compile(
    r"^\s*(?:\w+\s*=\s*)?(VStack|HStack|ZStack|LazyVStack|LazyHStack|Section|Form|List|Group|ScrollView)\b"
)


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(IOS_ROOT.rglob("*.swift")):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if not IDENTIFIER.match(line):
                continue
            # Walk back over other modifiers to the line the chain hangs off.
            probe = index - 1
            while probe >= 0 and lines[probe].lstrip().startswith("."):
                probe -= 1
            if probe < 0:
                continue
            close = CONTAINER_CLOSE.match(lines[probe])
            if not close:
                continue
            # Find what opened this block: the line at the same indentation.
            indent = close.group(1)
            opener = None
            for back in range(probe - 1, -1, -1):
                candidate = lines[back]
                if candidate.strip() and candidate.startswith(indent) and not candidate[len(indent) : len(indent) + 1].isspace():
                    opener = candidate
                    break
            if opener is None or not CONTAINER_OPEN.match(opener):
                continue
            window = "\n".join(lines[max(0, index - 6) : index + 2])
            if any(marker in window for marker in SAFE_MARKERS):
                continue
            rel = path.relative_to(IOS_ROOT.parent.parent)
            found.append(f"{rel}:{index + 1}: {line.strip()}")
    return found


KNOWN: set[str] = set()


def test_the_known_offender_list_does_not_rot():
    """Every allowlisted site must still be a real match.

    A stale entry would silently widen the lint. The list is empty now -- all
    eight original sites were fixed with .accessibilityElement(children:
    .contain), which names the container while leaving its children their own
    identifiers -- so this guards against an entry being added and then
    forgotten rather than fixed.
    """
    current = {offender.split(": ", 1)[0] for offender in _offenders()}
    stale = KNOWN - current
    assert not stale, (
        "These sites are allowlisted but no longer match the lint. If they were "
        "fixed, delete them from KNOWN:\n" + "\n".join(sorted(stale))
    )


def test_no_new_accessibility_identifier_on_an_uncollapsed_container():
    offenders = [o for o in _offenders() if o.split(": ", 1)[0] not in KNOWN]
    assert not offenders, (
        "An .accessibilityIdentifier applied to a container overwrites the "
        "identifier of every element inside it, erasing the identity of the "
        "controls a screen reader and the UI tests depend on.\n\n"
        "Move it to the leaf it is meant to name, or collapse the container "
        "with .accessibilityElement(children: .ignore/.combine) so it really "
        "is one element.\n\n" + "\n".join(offenders)
    )
