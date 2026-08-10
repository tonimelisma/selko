-- C5.6: D5 — purge the dead 'email_fetch' scheduled task rows.
--
-- 'email_fetch' scheduled tasks are residue of an architecture that no
-- longer exists (durable polling replaced it in #234). The table and
-- services/scheduled_tasks.py stay for the parked photo path; the rows go.
DELETE FROM public.scheduled_tasks WHERE task_type = 'email_fetch';
