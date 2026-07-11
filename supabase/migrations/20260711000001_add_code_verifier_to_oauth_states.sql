-- Persist PKCE code_verifier across OAuth initiate → callback.
-- google-auth-oauthlib includes a code_challenge in the auth URL; the matching
-- code_verifier must be sent on token exchange. Without this, Google returns
-- (invalid_grant) Missing code verifier.

ALTER TABLE public.oauth_states
    ADD COLUMN IF NOT EXISTS code_verifier TEXT;
