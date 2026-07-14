-- Repair emails that the 20260713000001 sender-rule dedupe may have requeued
-- before 20260713000004 installed the equivalent-rule guard. An email still
-- matching an active ignore rule must not remain pending.

UPDATE public.emails em
SET processing_status = 'skipped',
    processing_error = NULL,
    locked_by = NULL,
    locked_until = NULL
WHERE em.processing_status = 'pending'
  AND EXISTS (
      SELECT 1
      FROM public.sender_rules sr
      WHERE sr.user_id = em.user_id
        AND sr.action = 'ignore'
        AND (
              (sr.sender_email IS NOT NULL AND em.from_email = sr.sender_email)
           OR (sr.sender_domain IS NOT NULL
               AND em.from_email LIKE '%@' || sr.sender_domain
               AND NOT EXISTS (
                   SELECT 1
                   FROM public.sender_rules exact_rule
                   WHERE exact_rule.user_id = em.user_id
                     AND exact_rule.sender_email = em.from_email
                     AND exact_rule.action <> 'ignore'
               ))
        )
  );
