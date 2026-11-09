-- AUTH-16 explicit additive migration, no request-time DDL.
CREATE TABLE auth_demo_admissions (
 admission_id UUID PRIMARY KEY, campaign_id UUID NOT NULL REFERENCES auth_demo_campaigns(campaign_id),
 code_hash TEXT NOT NULL UNIQUE CHECK(code_hash ~ '^[a-f0-9]{64}$'),
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 redeemed_grant_id UUID REFERENCES auth_demo_grants(grant_id), redeemed_at TIMESTAMPTZ,
 CHECK(expires_at>created_at), CHECK((redeemed_at IS NULL)=(redeemed_grant_id IS NULL))
);
CREATE INDEX auth16_admissions_campaign ON auth_demo_admissions(campaign_id);
CREATE TABLE auth_demo_http_usage (
 scope_id UUID PRIMARY KEY REFERENCES auth_budget_scopes(scope_id),
 requests BIGINT NOT NULL DEFAULT 0 CHECK(requests>=0)
);
CREATE TABLE auth_demo_calls (
 call_id UUID PRIMARY KEY, grant_id UUID NOT NULL REFERENCES auth_demo_grants(grant_id),
 entry_id TEXT NOT NULL, key_hash TEXT NOT NULL, body_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('running','done','failed')),
 response JSONB, run_id TEXT, created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(grant_id,entry_id,key_hash)
);
CREATE TABLE auth_demo_cleanup (
 grant_id UUID PRIMARY KEY REFERENCES auth_demo_grants(grant_id),
 cleaned_at TIMESTAMPTZ NOT NULL, runs_deleted INTEGER NOT NULL
);
CREATE TABLE auth_demo_sweep_attempts (
 grant_id UUID PRIMARY KEY REFERENCES auth_demo_grants(grant_id),
 attempted_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE auth_demo_gc (
 kind TEXT NOT NULL CHECK(kind IN ('object','upload','checkpoint','cache','proof')),
 file_key TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','done')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(kind,file_key)
);
CREATE FUNCTION auth16_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['redeemed_at','redeemed_grant_id']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['redeemed_at','redeemed_grant_id']) OR OLD.redeemed_at IS NOT NULL THEN
 RAISE EXCEPTION 'immutable admission history' USING ERRCODE='23514'; END IF; RETURN NEW;
END $$;
CREATE TRIGGER auth16_admission_guard BEFORE UPDATE OR DELETE ON auth_demo_admissions FOR EACH ROW EXECUTE FUNCTION auth16_admission_guard();
