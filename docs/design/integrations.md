GOVERNS: backend/selko/services/integrations.py backend/selko/api/routes/integrations.py backend/selko/db/integrations.py backend/selko/db/recovery.py backend/selko/services/calendars.py

# Integrations and reconnect recovery

Google (Gmail + Calendar in one consent) and Microsoft (mail and calendar in one consent).
Requirements: [accounts](../requirements/accounts.md) (connect, scopes),
[calendar](../requirements/calendar.md) (recovery).

## Reconnect contract

- The OAuth callback's latency is independent of any backlog.
- Saving the new credentials and creating the recovery generation is one transaction
  (`selko.db.recovery.complete_integration_reauthorization`); at most one active recovery per
  integration, and a newer reauthorization supersedes the older one.
- Calendar recovery requeues only that user's work with `failure_code` `oauth_required` or
  `oauth_scope_required`, in bounded batches through the normal workers. Mail resumes from the
  provider cursors (the `integrations_ensure_email_sync_state_*` triggers) with no recovery record.
- User-auth failures never open a global provider circuit breaker.
- The web app distinguishes Connected from Catching up (`GET /integrations/recovery`, owner-scoped;
  the ConnectionRecovery card).
- Everything is auditable without tokens or content.

## Scopes

Gmail `gmail.readonly`; Google Calendar `calendar` and `calendar.events`; Microsoft `Mail.Read`,
`User.Read` and, for calendar, `Calendars.ReadWrite`. An Outlook refresh requests only the scopes
the stored grant holds; asking for more fails the refresh and would expire mail too.
