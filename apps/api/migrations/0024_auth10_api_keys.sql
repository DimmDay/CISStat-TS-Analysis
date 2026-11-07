-- AUTH-10 explicit auth authority migration, no ENV token import/backfill.
CREATE TABLE auth_api_keys (
    key_id UUID PRIMARY KEY,
    family_id UUID NOT NULL,
    token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    subject_id UUID NOT NULL REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
    account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
    subject_version BIGINT NOT NULL CHECK(subject_version>0),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
    scopes TEXT[] NOT NULL CHECK(cardinality(scopes) BETWEEN 1 AND 4
        AND scopes <@ ARRAY['api.read','api.write','api.compute','api.database']::text[]
        AND array_position(scopes,NULL) IS NULL),
    version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL CHECK(expires_at>created_at),
    revoked_at TIMESTAMPTZ CHECK(revoked_at IS NULL OR revoked_at>=created_at),
    replaced_by UUID REFERENCES auth_api_keys(key_id) DEFERRABLE INITIALLY DEFERRED,
    CHECK(replaced_by IS NULL OR (revoked_at IS NOT NULL AND replaced_by<>key_id))
);
CREATE UNIQUE INDEX auth10_active_family ON auth_api_keys(family_id) WHERE revoked_at IS NULL;
CREATE INDEX auth10_owner ON auth_api_keys(account_id,subject_id,created_at DESC);

CREATE FUNCTION auth10_key_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'key history retained' USING ERRCODE='23514';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'terminal key revocation' USING ERRCODE='23514';
    END IF;
    IF (to_jsonb(NEW)-ARRAY['revoked_at','replaced_by','version']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['revoked_at','replaced_by','version']) OR
       (NEW IS DISTINCT FROM OLD AND (NEW.revoked_at IS NULL OR NEW.version<>OLD.version+1)) THEN
        RAISE EXCEPTION 'immutable key authority' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth10_key_guard BEFORE UPDATE OR DELETE ON auth_api_keys
FOR EACH ROW EXECUTE FUNCTION auth10_key_guard();

CREATE FUNCTION auth10_identity_keys() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.subject_version<>OLD.subject_version THEN
        UPDATE auth_api_keys SET revoked_at=GREATEST(clock_timestamp(),created_at),version=version+1
        WHERE subject_id=NEW.subject_id AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth10_identity_keys AFTER UPDATE ON auth_identities
FOR EACH ROW EXECUTE FUNCTION auth10_identity_keys();

CREATE FUNCTION auth10_account_keys() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.status<>'active' OR NEW.plan='demo' OR
       (NEW.plan_expires_at IS NOT NULL AND NEW.plan_expires_at<=clock_timestamp()) OR
       (OLD.plan_expires_at IS NOT NULL AND OLD.plan_expires_at<=clock_timestamp()
        AND NEW.plan_expires_at IS DISTINCT FROM OLD.plan_expires_at) THEN
        UPDATE auth_api_keys SET revoked_at=GREATEST(clock_timestamp(),created_at),version=version+1
        WHERE account_id=NEW.account_id AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth10_account_keys AFTER UPDATE ON auth_accounts
FOR EACH ROW EXECUTE FUNCTION auth10_account_keys();

CREATE FUNCTION auth10_membership_keys() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        UPDATE auth_api_keys SET revoked_at=GREATEST(clock_timestamp(),created_at),version=version+1
        WHERE account_id=OLD.account_id AND subject_id=OLD.subject_id AND revoked_at IS NULL;
        RETURN OLD;
    END IF;
    IF NEW.status<>'active' THEN
        UPDATE auth_api_keys SET revoked_at=GREATEST(clock_timestamp(),created_at),version=version+1
        WHERE account_id=NEW.account_id AND subject_id=NEW.subject_id AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth10_membership_keys AFTER UPDATE OR DELETE ON auth_memberships
FOR EACH ROW EXECUTE FUNCTION auth10_membership_keys();
