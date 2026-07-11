-- Keep the enum change isolated because Supabase wraps migrations in transactions.
ALTER TYPE public.integration_provider ADD VALUE IF NOT EXISTS 'outlook';
