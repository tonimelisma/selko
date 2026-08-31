-- Keep the join URL of a mirrored calendar entry.
--
-- `hints_from_calendar_event` already derives a `join_url` hint from Google's
-- `hangoutLink` and `conferenceData.entryPoints[].uri`. The mirror never fed it
-- one: hints are written from a row reloaded out of `calendar_entries`, and
-- that row carried only the iCalUID. So mirrored entries were indexed by UID
-- alone, while events extracted from email carry only `join_url` hints -- two
-- sets of hints that can never intersect.
--
-- Measured consequence: four Snowflake interviews sat in the New lane holding
-- `join_url` hints while the identical calendar entries, holding the same Zoom
-- links, sat on an imported calendar carrying only `ical_uid` hints. Nothing
-- could connect them.
--
-- Nullable with no backfill: entries acquire the value on their next sync.
ALTER TABLE calendar_entries ADD COLUMN IF NOT EXISTS join_url text;

COMMENT ON COLUMN calendar_entries.join_url IS
  'Conferencing URL from hangoutLink or conferenceData.entryPoints, kept so the '
  'entry can be indexed by the same join_url hint an email-extracted event carries.';
