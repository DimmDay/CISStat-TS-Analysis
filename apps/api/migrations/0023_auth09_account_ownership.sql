-- AUTH-09 additive ownership, no automatic legacy backfill.
-- statement
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS owner_account_id UUID;
-- statement
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS ownership_version BIGINT NOT NULL DEFAULT 0;
-- statement
CREATE INDEX IF NOT EXISTS idx_research_runs_account ON research_runs(owner_account_id);
-- statement
CREATE TABLE IF NOT EXISTS run_ownership_migrations (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id),
    owner_account_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    previous_owner_subject TEXT,
    previous_tenant_id TEXT,
    previous_session_hash TEXT NOT NULL,
    evidence TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
-- statement
CREATE OR REPLACE FUNCTION auth09_run_owner_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF OLD.owner_account_id IS NOT NULL THEN
        IF (NEW.owner_account_id,NEW.tenant_id,NEW.owner_subject,NEW.ownership,NEW.ownership_version)
            IS DISTINCT FROM
           (OLD.owner_account_id,OLD.tenant_id,OLD.owner_subject,OLD.ownership,OLD.ownership_version) THEN
            RAISE EXCEPTION 'immutable Account ownership' USING ERRCODE='23514';
        END IF;
    ELSIF NEW.owner_account_id IS NOT NULL THEN
        IF NEW.owner_subject IS DISTINCT FROM OLD.owner_subject OR
           NOT EXISTS (SELECT 1 FROM run_ownership_migrations m WHERE m.run_id=OLD.run_id
             AND m.owner_account_id=NEW.owner_account_id AND m.tenant_id::text=NEW.tenant_id
             AND m.previous_owner_subject IS NOT DISTINCT FROM OLD.owner_subject
             AND m.previous_tenant_id IS NOT DISTINCT FROM OLD.tenant_id) THEN
            RAISE EXCEPTION 'explicit ownership migration required' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
-- statement
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='auth09_run_owner_guard'
                  AND tgrelid='research_runs'::regclass) THEN
        CREATE TRIGGER auth09_run_owner_guard BEFORE UPDATE ON research_runs
        FOR EACH ROW EXECUTE FUNCTION auth09_run_owner_guard();
    END IF;
END $$;
-- statement
CREATE OR REPLACE FUNCTION auth09_receipt_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'immutable ownership receipt' USING ERRCODE='23514';
END $$;
-- statement
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='auth09_receipt_guard'
                  AND tgrelid='run_ownership_migrations'::regclass) THEN
        CREATE TRIGGER auth09_receipt_guard BEFORE UPDATE OR DELETE ON run_ownership_migrations
        FOR EACH ROW EXECUTE FUNCTION auth09_receipt_guard();
    END IF;
END $$;
-- statement
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='auth09_account_binding'
                  AND conrelid='research_runs'::regclass) THEN
        ALTER TABLE research_runs ADD CONSTRAINT auth09_account_binding CHECK (
            (owner_account_id IS NULL AND ownership_version=0) OR
            (owner_account_id IS NOT NULL AND ownership_version=1
             AND ownership IS NOT DISTINCT FROM 'bound' AND tenant_id IS NOT NULL)
        );
    END IF;
END $$;
