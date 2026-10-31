-- AUTH-02. Standalone auth migration; applied transactionally by
-- authentication.migrations, never by the scientific research_runs writer.
-- No credentials, sessions or legacy ownership are inferred/imported here.
CREATE TABLE auth_identities (
    subject_id UUID PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'person' CHECK (kind IN ('person','service')),
    platform_role TEXT NOT NULL DEFAULT 'external_user'
        CHECK (platform_role IN ('external_user','internal_analyst','admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
    subject_version BIGINT NOT NULL DEFAULT 1 CHECK (subject_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE auth_external_identities (
    issuer TEXT COLLATE "C" NOT NULL CHECK (length(issuer) BETWEEN 1 AND 2048 AND btrim(issuer) <> ''),
    external_subject TEXT COLLATE "C" NOT NULL CHECK (length(external_subject) BETWEEN 1 AND 255 AND btrim(external_subject) <> ''),
    subject_id UUID NOT NULL REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
    email TEXT CHECK (email IS NULL OR length(email) BETWEEN 1 AND 320),
    email_verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (issuer,external_subject),
    CHECK (NOT email_verified OR email IS NOT NULL)
);
CREATE INDEX auth_external_identity_subject ON auth_external_identities(subject_id);
CREATE TABLE auth_accounts (
    account_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL UNIQUE,
    account_type TEXT NOT NULL DEFAULT 'mono' CHECK (account_type IN ('mono','multi')),
    plan TEXT NOT NULL DEFAULT 'demo' CHECK (plan IN ('demo','starter','professional','enterprise','internal')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
    seats INTEGER NOT NULL DEFAULT 1 CHECK (seats > 0),
    entitlement_version BIGINT NOT NULL DEFAULT 1 CHECK (entitlement_version > 0),
    plan_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (account_type <> 'mono' OR seats = 1)
);
CREATE TABLE auth_memberships (
    account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
    subject_id UUID NOT NULL REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
    account_role TEXT NOT NULL CHECK (account_role IN ('owner','member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id,subject_id)
);
CREATE INDEX auth_membership_subject ON auth_memberships(subject_id,account_id);

CREATE FUNCTION auth02_identity_update() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.subject_id IS DISTINCT FROM OLD.subject_id THEN
        RAISE EXCEPTION 'immutable subject' USING ERRCODE='23514',CONSTRAINT='auth02_subject_immutable';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.subject_version <> OLD.subject_version + 1 THEN
        RAISE EXCEPTION 'subject version must advance' USING ERRCODE='23514',CONSTRAINT='auth02_subject_version';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth02_identity_update BEFORE UPDATE ON auth_identities
FOR EACH ROW EXECUTE FUNCTION auth02_identity_update();

CREATE FUNCTION auth02_external_update() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF (NEW.issuer,NEW.external_subject,NEW.subject_id) IS DISTINCT FROM
       (OLD.issuer,OLD.external_subject,OLD.subject_id) THEN
        RAISE EXCEPTION 'immutable external binding' USING ERRCODE='23514',CONSTRAINT='auth02_external_immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth02_external_update BEFORE UPDATE ON auth_external_identities
FOR EACH ROW EXECUTE FUNCTION auth02_external_update();

CREATE FUNCTION auth02_account_update() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF (NEW.account_id,NEW.tenant_id) IS DISTINCT FROM (OLD.account_id,OLD.tenant_id) THEN
        RAISE EXCEPTION 'immutable account tenant' USING ERRCODE='23514',CONSTRAINT='auth02_account_immutable';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.entitlement_version <> OLD.entitlement_version + 1 THEN
        RAISE EXCEPTION 'entitlement version must advance' USING ERRCODE='23514',CONSTRAINT='auth02_entitlement_version';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth02_account_update BEFORE UPDATE ON auth_accounts
FOR EACH ROW EXECUTE FUNCTION auth02_account_update();

CREATE FUNCTION auth02_membership_write() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE affected UUID;
BEGIN
    IF TG_OP='UPDATE' AND (NEW.account_id,NEW.subject_id) IS DISTINCT FROM (OLD.account_id,OLD.subject_id) THEN
        RAISE EXCEPTION 'immutable membership keys' USING ERRCODE='23514',CONSTRAINT='auth02_member_immutable';
    END IF;
    IF TG_OP='DELETE' THEN affected=OLD.account_id; ELSE affected=NEW.account_id; END IF;
    -- A real parent write serializes all membership mutations, including raw SQL.
    -- Under repeatable read a concurrent stale writer aborts instead of write skew.
    UPDATE auth_accounts SET entitlement_version=entitlement_version+1,updated_at=now()
        WHERE account_id=affected;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER auth02_membership_write BEFORE INSERT OR UPDATE OR DELETE ON auth_memberships
FOR EACH ROW EXECUTE FUNCTION auth02_membership_write();

CREATE FUNCTION auth02_membership_invariant() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE aid UUID; a auth_accounts%ROWTYPE; members BIGINT; owners BIGINT;
BEGIN
    IF TG_OP='DELETE' THEN aid=OLD.account_id; ELSE aid=NEW.account_id; END IF;
    SELECT * INTO a FROM auth_accounts WHERE account_id=aid FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT count(*), count(*) FILTER (WHERE account_role='owner') INTO members,owners
        FROM auth_memberships WHERE account_id=aid AND status='active';
    IF owners < 1 OR members > a.seats OR (a.account_type='mono' AND members <> 1) THEN
        RAISE EXCEPTION 'account membership invariant' USING ERRCODE='23514',CONSTRAINT='auth02_membership_invariant';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER auth02_account_membership_check
AFTER INSERT OR UPDATE ON auth_accounts DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION auth02_membership_invariant();
CREATE CONSTRAINT TRIGGER auth02_member_account_check
AFTER INSERT OR UPDATE OR DELETE ON auth_memberships DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION auth02_membership_invariant();
