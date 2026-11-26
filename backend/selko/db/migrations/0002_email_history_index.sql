-- Email history (E7) counted and ordered a user's emails by reading every row,
-- and processing_outcome sits after body_text in the row, so each history page
-- read every email body of the user: 46 ms to count and 112 ms to order a page
-- on a 400 MB database, churning the page cache on every request. Covering the
-- filter and the order in one index makes both index-only (3.6 ms and 41 ms).
CREATE INDEX idx_emails_history_order ON emails (user_id, processing_status, processing_outcome, date_sent, id);
