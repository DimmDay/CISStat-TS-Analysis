-- AUTH-15 additive forum authority. Explicit apply only.
CREATE TABLE auth_demo_campaigns (
 campaign_id UUID PRIMARY KEY, alias TEXT COLLATE "C" NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','scheduled','active','paused','revoked')),
 policy JSONB NOT NULL CHECK(jsonb_typeof(policy)='object'),
 policy_version BIGINT NOT NULL DEFAULT 1 CHECK(policy_version>0),
 password_hash TEXT NOT NULL CHECK(password_hash LIKE '$argon2id$%'),
 credential_version BIGINT NOT NULL DEFAULT 1 CHECK(credential_version>0),
 issued_grants BIGINT NOT NULL DEFAULT 0 CHECK(issued_grants>=0),
 sponsor_id UUID NOT NULL UNIQUE REFERENCES auth_budget_scopes(scope_id),
 created_at TIMESTAMPTZ NOT NULL, activated_at TIMESTAMPTZ
);
CREATE TABLE auth_demo_grants (
 grant_id UUID PRIMARY KEY REFERENCES auth_budget_scopes(scope_id),
 campaign_id UUID NOT NULL REFERENCES auth_demo_campaigns(campaign_id),
 subject_id UUID NOT NULL UNIQUE REFERENCES auth_identities(subject_id),
 account_id UUID NOT NULL UNIQUE REFERENCES auth_accounts(account_id),
 resume_hash TEXT NOT NULL UNIQUE CHECK(resume_hash ~ '^[a-f0-9]{64}$'),
 issued_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL CHECK(expires_at>issued_at),
 policy_version BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked')),
 UNIQUE(grant_id,subject_id,account_id),
 FOREIGN KEY(account_id,subject_id) REFERENCES auth_memberships(account_id,subject_id)
);
CREATE INDEX auth15_campaign_grants ON auth_demo_grants(campaign_id,expires_at);
ALTER TABLE auth_sessions ALTER COLUMN credential_id DROP NOT NULL;
ALTER TABLE auth_sessions ADD COLUMN demo_grant_id UUID;
ALTER TABLE auth_sessions ADD CONSTRAINT auth15_session_family CHECK ((credential_id IS NULL)=(demo_grant_id IS NOT NULL));
ALTER TABLE auth_sessions ADD CONSTRAINT auth15_session_grant FOREIGN KEY(demo_grant_id,subject_id,account_id)
 REFERENCES auth_demo_grants(grant_id,subject_id,account_id);
CREATE FUNCTION auth15_grant_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') OR OLD.status='revoked' THEN
  RAISE EXCEPTION 'immutable demo binding and expiry' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth15_grant_guard BEFORE UPDATE OR DELETE ON auth_demo_grants FOR EACH ROW EXECUTE FUNCTION auth15_grant_guard();
CREATE FUNCTION auth15_campaign_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR NEW.campaign_id<>OLD.campaign_id OR NEW.alias<>OLD.alias OR NEW.sponsor_id<>OLD.sponsor_id
 OR NEW.created_at<>OLD.created_at OR NEW.issued_grants<OLD.issued_grants OR NEW.credential_version<OLD.credential_version
 OR NEW.policy_version<OLD.policy_version OR OLD.status='revoked'
 OR (OLD.activated_at IS NOT NULL AND (NEW.activated_at IS DISTINCT FROM OLD.activated_at
 OR NEW.policy->>'starts_at' IS DISTINCT FROM OLD.policy->>'starts_at' OR NEW.policy->>'ends_at' IS DISTINCT FROM OLD.policy->>'ends_at')) THEN
  RAISE EXCEPTION 'immutable demo campaign boundary' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth15_campaign_guard BEFORE UPDATE OR DELETE ON auth_demo_campaigns FOR EACH ROW EXECUTE FUNCTION auth15_campaign_guard();
