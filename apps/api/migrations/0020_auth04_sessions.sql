-- AUTH-04 owned schema; explicit migration, no DDL on request/import.
CREATE TABLE auth_password_credentials (
 credential_id UUID PRIMARY KEY,
 subject_id UUID NOT NULL UNIQUE REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
 login TEXT COLLATE "C" NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9][a-z0-9_.@+\-]{2,127}$'),
 password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
 version BIGINT NOT NULL DEFAULT 1 CHECK (version>0),
 status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
 scopes JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(scopes)='array'),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(credential_id,subject_id)
);
CREATE TABLE auth_subject_security (
 subject_id UUID PRIMARY KEY REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
 session_epoch BIGINT NOT NULL DEFAULT 1 CHECK (session_epoch>0)
);
CREATE TABLE auth_sessions (
 session_id UUID PRIMARY KEY,
 family_id UUID NOT NULL,
 token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
 subject_id UUID NOT NULL REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 credential_id UUID NOT NULL REFERENCES auth_password_credentials(credential_id) ON DELETE RESTRICT,
 credential_version BIGINT NOT NULL CHECK (credential_version>0),
 subject_version BIGINT NOT NULL CHECK (subject_version>0),
 session_epoch BIGINT NOT NULL CHECK (session_epoch>0),
 scopes JSONB NOT NULL CHECK (jsonb_typeof(scopes)='array'),
 origin TEXT NOT NULL,
 auth_time TIMESTAMPTZ NOT NULL,
 issued_at TIMESTAMPTZ NOT NULL,
 last_seen_at TIMESTAMPTZ NOT NULL,
 idle_expires_at TIMESTAMPTZ NOT NULL,
 absolute_expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 FOREIGN KEY(credential_id,subject_id) REFERENCES auth_password_credentials(credential_id,subject_id) ON DELETE RESTRICT,
 FOREIGN KEY(account_id,subject_id) REFERENCES auth_memberships(account_id,subject_id) ON DELETE RESTRICT,
 CHECK (auth_time<=issued_at AND issued_at<=last_seen_at),
 CHECK (issued_at<absolute_expires_at AND last_seen_at<=absolute_expires_at),
 CHECK (idle_expires_at<=absolute_expires_at AND issued_at<idle_expires_at)
);
CREATE INDEX auth_sessions_subject ON auth_sessions(subject_id,issued_at,session_id);
CREATE INDEX auth_sessions_family ON auth_sessions(subject_id,family_id);
CREATE TABLE auth_login_limits (
 bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL CHECK(attempts>0),
 resets_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX auth_login_limits_expiry ON auth_login_limits(resets_at);
-- Durable delivery obligation for the EXISTING security_audit record schema.
CREATE TABLE auth_audit_outbox (
 audit_id TEXT PRIMARY KEY, payload JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), delivered_at TIMESTAMPTZ
);
CREATE INDEX auth_audit_pending ON auth_audit_outbox(created_at) WHERE delivered_at IS NULL;

CREATE FUNCTION auth04_password_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.subject_id<>OLD.subject_id OR NEW.credential_id<>OLD.credential_id OR NEW.login<>OLD.login THEN
  RAISE EXCEPTION 'immutable credential binding' USING ERRCODE='23514';
 END IF;
 IF NEW.password_hash<>OLD.password_hash OR NEW.status<>OLD.status OR NEW.scopes<>OLD.scopes THEN
  NEW.version:=GREATEST(NEW.version,OLD.version+1);
 END IF;
 IF NEW.version<OLD.version THEN RAISE EXCEPTION 'version regression' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth04_password_version BEFORE UPDATE ON auth_password_credentials
 FOR EACH ROW EXECUTE FUNCTION auth04_password_version();
CREATE FUNCTION auth04_session_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['last_seen_at','idle_expires_at','revoked_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['last_seen_at','idle_expires_at','revoked_at']) OR
    NEW.last_seen_at<OLD.last_seen_at OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
  RAISE EXCEPTION 'immutable or revoked session' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth04_session_immutable BEFORE UPDATE ON auth_sessions
 FOR EACH ROW EXECUTE FUNCTION auth04_session_immutable();
