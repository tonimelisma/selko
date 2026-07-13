CREATE OR REPLACE FUNCTION public.reprocess_email(
    p_user_id uuid,
    p_email_id uuid
)
RETURNS SETOF public.emails
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF auth.uid() IS DISTINCT FROM p_user_id AND auth.role() <> 'service_role' THEN
        RAISE EXCEPTION 'Cannot reprocess another user''s email';
    END IF;

    RETURN QUERY
    UPDATE public.emails
    SET processing_status = 'pending',
        processing_error = NULL,
        processing_outcome = NULL,
        processing_explanation = NULL,
        processing_result = NULL,
        processed_at = NULL,
        locked_by = NULL,
        locked_until = NULL,
        next_retry_at = NULL,
        dead_letter_reason = NULL,
        dead_letter_at = NULL,
        attempts = 0
    WHERE id = p_email_id
      AND user_id = p_user_id
      AND processing_status NOT IN ('pending', 'processing')
    RETURNING public.emails.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.reprocess_email(uuid, uuid) TO authenticated, service_role;
