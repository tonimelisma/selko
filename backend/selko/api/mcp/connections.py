"""Whether the user's mail and calendar connections are working, for Claude.

This mirrors the web app's connection banner (``frontend/src/lib/calendar-providers.js``
``recoveryPlan`` and ``google-connection.js``): one entry per *sign-in*, because
one Google consent covers Gmail and Google Calendar and one Microsoft consent
covers Outlook mail and calendar. A user fixes a sign-in, not a row.

It goes further than the banner in two places the banner cannot see cheaply:

- a mailbox whose integration says ``active`` but whose poller keeps failing
  or has not succeeded for hours (``email_sync_health``), and
- accepted events parked because the calendar sign-in lapsed or lacks a scope
  (``calendar_work_items`` blocked with ``oauth_required`` /
  ``oauth_scope_required``), which is the user-visible cost of a lapse.

Every problem returns to green on its own once the user signs in again, or the
next poll succeeds: nothing here counts history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

SignIn = Literal["google", "outlook"]
SIGN_INS: tuple[SignIn, ...] = ("google", "outlook")

# Integration statuses the user must fix by signing in again.
LAPSED = frozenset({"expired", "revoked", "error"})
OAUTH_BLOCKED_CODES = ("oauth_required", "oauth_scope_required")
AUTH_ERROR_CODES = frozenset({"provider_auth_expired"})

# A mailbox polled every few minutes that has failed this many times in a row,
# or has not succeeded for this long, is not "fine" whatever its status says.
FAILING_POLLS = 3
STALE_AFTER = timedelta(hours=6)

_LABEL: dict[SignIn, str] = {"google": "Google", "outlook": "Microsoft Outlook"}
_MAIL: dict[SignIn, str] = {"google": "Gmail", "outlook": "Outlook mail"}
_CALENDAR: dict[SignIn, str] = {"google": "Google Calendar", "outlook": "Outlook Calendar"}


def reconnect_url(frontend_url: str, sign_in: SignIn) -> str:
    """A link that never expires: Selko Settings starts this sign-in on open.

    Scheduled digests are read hours after they run, longer than an OAuth
    state lives, so the durable link goes through the signed-in web app.
    ``reconnect_account`` hands out the direct provider link for live chats.
    """
    return f"{frontend_url.rstrip('/')}/app/settings?reconnect={sign_in}"


def outlook_has_calendar_scope(row: dict[str, Any] | None) -> bool:
    if not row or row.get("provider") != "outlook":
        return False
    return any(
        isinstance(scope, str) and scope.lower().endswith("calendars.readwrite")
        for scope in row.get("scopes") or []
    )


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Problem:
    sign_in: SignIn | None
    action: Literal["reconnect", "connect", "wait"]
    message: str

    def as_dict(self, frontend_url: str) -> dict[str, Any]:
        item: dict[str, Any] = {"problem": self.message, "action": self.action}
        if self.sign_in is not None:
            item["sign_in"] = self.sign_in
            if self.action != "wait":
                item["reconnect_url"] = reconnect_url(frontend_url, self.sign_in)
        elif self.action == "connect":
            item["connect_urls"] = {s: reconnect_url(frontend_url, s) for s in SIGN_INS}
        return item


def _mail_poll_problem(
    sign_in: SignIn, account: str | None, health: dict[str, Any] | None, now: datetime
) -> Problem | None:
    """A mailbox Selko is supposed to be reading but is not managing to."""
    if not health:
        return None
    who = account or _MAIL[sign_in]
    failures = int(health.get("consecutive_failures") or 0)
    code = health.get("last_error_code")
    if failures >= FAILING_POLLS:
        if code in AUTH_ERROR_CODES:
            return Problem(
                sign_in, "reconnect",
                f"{_LABEL[sign_in]} is refusing Selko's sign-in for {who}, so new email "
                "is not being read. Sign in again to fix it.",
            )
        return Problem(
            sign_in, "wait",
            f"Selko's last {failures} attempts to check {who} failed"
            f"{f' ({code})' if code else ''}. It keeps retrying on its own; no action "
            "is needed unless this persists.",
        )
    last_success = _parse(health.get("last_success_at"))
    # Not initial_watermark_at: that is the scan's lookback point, weeks before
    # the mailbox was connected, so it would flag every fresh connection.
    reference = last_success or _parse(health.get("last_started_at"))
    overdue = _parse(health.get("next_poll_at"))
    stale = (reference is not None and now - reference > STALE_AFTER) or (
        reference is None and overdue is not None and now - overdue > STALE_AFTER
    )
    if stale:
        since = (
            f"since {last_success.isoformat(timespec='minutes')}" if last_success
            else "since it was connected"
        )
        return Problem(
            sign_in, "wait",
            f"Selko has not finished a check of {who} {since}. It keeps retrying on "
            "its own; try check_email_now, and reconnect if this persists.",
        )
    return None


def assess_connections(
    integrations: Iterable[dict[str, Any]],
    sync_health: Iterable[dict[str, Any]],
    blocked_calendar_work: Iterable[dict[str, Any]],
    recoveries: Iterable[dict[str, Any]],
    *,
    frontend_url: str,
    now: datetime,
) -> dict[str, Any]:
    """The verdict on every sign-in, and what (if anything) the user must do.

    ``integrations``: rows with provider, status, provider_email, scopes, id.
    ``sync_health``: ``email_sync_health`` rows (integration_id keyed).
    ``blocked_calendar_work``: ``calendar_work_items`` rows blocked on OAuth,
    with ``provider`` and ``failure_code``.
    ``recoveries``: active ``integration_recoveries`` rows (catch-up progress).
    """
    rows = [r for r in integrations if r.get("provider") != "google_photos"]
    by_provider = {r.get("provider"): r for r in rows}
    gmail = by_provider.get("gmail")
    gcal = by_provider.get("google_calendar")
    outlook = by_provider.get("outlook")
    health = {h.get("integration_id"): h for h in sync_health}
    blocked: dict[SignIn, int] = {"google": 0, "outlook": 0}
    for item in blocked_calendar_work:
        # Stamped at first claim; NULL means never claimed, so Google by routing default.
        blocked["outlook" if item.get("provider") == "outlook" else "google"] += 1

    def active(row: dict[str, Any] | None) -> bool:
        return bool(row) and row.get("status") == "active"

    google_calendar_writable = active(gcal)
    outlook_calendar_writable = active(outlook) and outlook_has_calendar_scope(outlook)
    calendar_writable = google_calendar_writable or outlook_calendar_writable
    mail_active = active(gmail) or active(outlook)

    problems: list[Problem] = []
    connections: list[dict[str, Any]] = []
    lapsed = False

    # ---------------------------------------------------------------- Google
    if gmail or gcal:
        account = next((r.get("provider_email") for r in (gmail, gcal) if r and r.get("provider_email")), None)
        mail_lost = bool(gmail) and not active(gmail)
        # A lapsed Google Calendar is not worth a prompt while Outlook Calendar works.
        calendar_lost = bool(gcal) and not active(gcal) and not outlook_calendar_writable
        if mail_lost or calendar_lost:
            lapsed = True
            lost = " and ".join(
                part for part, gone in ((_MAIL["google"], mail_lost), (_CALENDAR["google"], calendar_lost)) if gone
            )
            problems.append(Problem(
                "google", "reconnect",
                f"The Google sign-in for {account or 'your account'} has lapsed, so Selko "
                f"cannot use {lost}. Sign in to Google again to fix it.",
            ))
        elif gmail and not gcal and not calendar_writable:
            problems.append(Problem(
                "google", "reconnect",
                "Google Calendar access was not granted, so accepted events cannot be "
                "added to a calendar. Sign in to Google again and allow Calendar.",
            ))
        if active(gmail):
            poll = _mail_poll_problem("google", account, health.get(gmail.get("id")), now)
            if poll:
                problems.append(poll)
        if blocked["google"] and not (mail_lost or calendar_lost):
            problems.append(Problem(
                "google", "reconnect",
                f"{blocked['google']} accepted event(s) are waiting to reach Google Calendar "
                "because Google needs you to sign in again.",
            ))
        connections.append({
            "sign_in": "google",
            "account": account,
            "state": _state(gmail, gcal),
            "mail": _product(gmail, health),
            "calendar": _product(gcal, health, writable=google_calendar_writable),
            "events_waiting_on_sign_in": blocked["google"],
        })

    # --------------------------------------------------------------- Outlook
    if outlook:
        account = outlook.get("provider_email")
        has_calendar_scope = outlook_has_calendar_scope(outlook)
        if not active(outlook):
            lapsed = True
            lost = (
                "Outlook mail and Outlook Calendar"
                if has_calendar_scope and not google_calendar_writable
                else "Outlook mail"
            )
            problems.append(Problem(
                "outlook", "reconnect",
                f"The Microsoft sign-in for {account or 'your account'} has lapsed, so Selko "
                f"cannot use {lost}. Sign in to Microsoft again to fix it.",
            ))
        else:
            if not has_calendar_scope and not calendar_writable:
                problems.append(Problem(
                    "outlook", "reconnect",
                    "Outlook is connected for mail only, so accepted events cannot be added "
                    "to a calendar. Sign in to Microsoft again to allow Outlook Calendar.",
                ))
            poll = _mail_poll_problem("outlook", account, health.get(outlook.get("id")), now)
            if poll:
                problems.append(poll)
            if blocked["outlook"]:
                problems.append(Problem(
                    "outlook", "reconnect",
                    f"{blocked['outlook']} accepted event(s) are waiting to reach Outlook "
                    "Calendar because Microsoft needs you to sign in again.",
                ))
        connections.append({
            "sign_in": "outlook",
            "account": account,
            "state": "connected" if active(outlook) else "needs_reconnect",
            "mail": _product(outlook, health),
            "calendar": {
                "connected": has_calendar_scope,
                "writable": outlook_calendar_writable,
            },
            "events_waiting_on_sign_in": blocked["outlook"],
        })

    # ------------------------------------------------------------ nothing yet
    # A lapsed sign-in already says what to do; "connect a mailbox" beside it
    # would offer a second, wrong answer to the same problem.
    if not mail_active and not lapsed:
        problems.append(Problem(
            None, "connect",
            "No mailbox is connected, so Selko is not finding any events. Connect Gmail "
            "or Outlook.",
        ))

    catching_up = [
        {
            "provider": r.get("provider"),
            "status": r.get("status"),
            "remaining": r.get("remaining_count"),
            "done": r.get("completed_count"),
        }
        for r in recoveries
    ]
    result: dict[str, Any] = {
        "all_good": not problems,
        "connections": connections,
        "needs_attention": [p.as_dict(frontend_url) for p in problems],
    }
    if catching_up:
        result["catching_up"] = catching_up
    return result


def _state(gmail: dict[str, Any] | None, gcal: dict[str, Any] | None) -> str:
    rows = [r for r in (gmail, gcal) if r]
    if any(r.get("status") != "active" for r in rows):
        return "needs_reconnect"
    return "connected" if gmail and gcal else "partial"


def _product(
    row: dict[str, Any] | None,
    health: dict[str, dict[str, Any]],
    *,
    writable: bool | None = None,
) -> dict[str, Any]:
    if not row:
        out: dict[str, Any] = {"connected": False}
        if writable is not None:
            out["writable"] = False
        return out
    out = {"connected": True, "status": row.get("status")}
    if writable is not None:
        out["writable"] = writable
    poll = health.get(row.get("id"))
    if poll:
        out["last_checked"] = poll.get("last_success_at")
        if poll.get("consecutive_failures"):
            out["consecutive_failures"] = poll.get("consecutive_failures")
    return out


def attention_summary(assessment: dict[str, Any]) -> dict[str, Any] | None:
    """The compact block attached to every other tool's result.

    Only problems the user can act on: a ``wait`` problem fixes itself, and
    repeating it on every call would teach Claude to ignore the field.
    """
    actionable = [p for p in assessment.get("needs_attention", []) if p.get("action") != "wait"]
    if not actionable:
        return None
    return {
        "message": (
            "Some Selko connections need the user to sign in again. Each item has a "
            "link that fixes it; reconnect_account returns a direct sign-in link."
        ),
        "items": actionable,
    }
