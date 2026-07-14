-- Repair existing databases where 20260713000001 disabled the delete trigger
-- while deduplicating an ignore rule that was replaced by auto_approve.
-- Those emails stayed skipped even though the surviving rule now permits them.

UPDATE public.emails em
SET processing_status = 'pending',
    processing_error = NULL,
    locked_by = NULL,
    locked_until = NULL,
    attempts = 0
WHERE em.processing_status = 'skipped'
  AND em.processing_outcome IS DISTINCT FROM 'calendar_invite'
  AND em.date_sent >= now() - interval '30 days'
  AND (
      EXISTS (
          SELECT 1
          FROM public.sender_rules exact_rule
          WHERE exact_rule.user_id = em.user_id
            AND exact_rule.sender_email = em.from_email
            AND exact_rule.action = 'auto_approve'
      )
      OR (
          EXISTS (
              SELECT 1
              FROM public.sender_rules domain_rule
              WHERE domain_rule.user_id = em.user_id
                AND domain_rule.sender_domain IS NOT NULL
                AND domain_rule.sender_domain = split_part(em.from_email, '@', 2)
                AND domain_rule.action = 'auto_approve'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM public.sender_rules exact_rule
              WHERE exact_rule.user_id = em.user_id
                AND exact_rule.sender_email = em.from_email
          )
      )
  );
