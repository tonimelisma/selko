-- Migration: Create sender_rules table
-- Automation rules for auto-approve or ignore by sender
--
-- Important: 'ignore' means "skip this sender's email data contribution"
-- It does NOT reject the entire event. An event can have contributions from 
-- multiple senders (e.g., PTA, Principal, Teacher all emailing about the same 
-- school event). Ignoring PTA only skips PTA's emails; Principal and Teacher 
-- emails still contribute.

CREATE TABLE public.sender_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Match criteria (sender_email takes precedence over sender_domain)
    sender_domain text,  -- e.g., "school.edu" matches *@school.edu
    sender_email text,   -- e.g., "newsletter@school.edu" for specific sender

    -- Action to take
    -- auto_approve: automatically approve new events from this sender
    -- ignore: skip this sender's emails when extracting/updating events
    action text NOT NULL CHECK (action IN ('auto_approve', 'ignore')),

    created_at timestamptz DEFAULT now() NOT NULL,

    -- Either domain or email must be set
    CHECK (sender_domain IS NOT NULL OR sender_email IS NOT NULL)
);

ALTER TABLE public.sender_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own sender_rules"
    ON public.sender_rules FOR ALL
    USING (auth.uid() = user_id);

-- Indexes
CREATE INDEX idx_sender_rules_user ON public.sender_rules(user_id);
CREATE INDEX idx_sender_rules_domain ON public.sender_rules(sender_domain);
CREATE INDEX idx_sender_rules_email ON public.sender_rules(sender_email);
