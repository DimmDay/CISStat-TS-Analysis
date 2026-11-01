-- AUTH-05: additions only; historical 0019/0020 checksums stay immutable.
ALTER TABLE auth_subject_security ADD COLUMN enrollment_allowed BOOLEAN NOT NULL DEFAULT false;
CREATE TABLE auth_mfa_factors (
 factor_id UUID PRIMARY KEY, subject_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 key_id TEXT NOT NULL, secret_cipher TEXT NOT NULL, last_step BIGINT NOT NULL DEFAULT -1,
 created_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
 UNIQUE(factor_id,subject_id)
);
CREATE UNIQUE INDEX auth_mfa_one_active ON auth_mfa_factors(subject_id) WHERE revoked_at IS NULL;
CREATE TABLE auth_session_mfa (
 session_id UUID PRIMARY KEY REFERENCES auth_sessions(session_id),
 factor_id UUID NOT NULL REFERENCES auth_mfa_factors(factor_id), verified_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE auth_challenges (
 challenge_id UUID PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 subject_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 account_id UUID NOT NULL, credential_id UUID NOT NULL,
 credential_version BIGINT NOT NULL CHECK(credential_version>0),
 subject_version BIGINT NOT NULL CHECK(subject_version>0), session_epoch BIGINT NOT NULL CHECK(session_epoch>0),
 purpose TEXT NOT NULL CHECK(purpose IN ('login','recovery','enroll_start','enroll','step_up','proof')),
 target TEXT NOT NULL DEFAULT '', session_id UUID REFERENCES auth_sessions(session_id),
 factor_id UUID NOT NULL, key_id TEXT, secret_cipher TEXT,
 origin TEXT NOT NULL, auth_time TIMESTAMPTZ NOT NULL, issued_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL, attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 consumed_at TIMESTAMPTZ, CHECK(issued_at<expires_at),
 CHECK((purpose IN ('step_up','proof'))=(session_id IS NOT NULL)),
 CHECK((purpose='enroll')=(secret_cipher IS NOT NULL AND key_id IS NOT NULL)),
 FOREIGN KEY(account_id,subject_id) REFERENCES auth_memberships(account_id,subject_id),
 FOREIGN KEY(credential_id,subject_id) REFERENCES auth_password_credentials(credential_id,subject_id)
);
CREATE INDEX auth_challenge_subject ON auth_challenges(subject_id,expires_at);
CREATE TABLE auth_recovery_codes (
 code_id UUID PRIMARY KEY, subject_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 factor_id UUID NOT NULL, code_hash TEXT NOT NULL UNIQUE CHECK(code_hash ~ '^[0-9a-f]{64}$'),
 created_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
 FOREIGN KEY(factor_id,subject_id) REFERENCES auth_mfa_factors(factor_id,subject_id)
);
CREATE TABLE auth_bootstrap (
 slot INTEGER PRIMARY KEY CHECK(slot=1), token_hash TEXT NOT NULL CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 issued_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
 CHECK(issued_at<expires_at)
);
-- A consumed challenge/code cannot be resurrected; bindings are immutable.
CREATE FUNCTION auth05_challenge_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['attempts','consumed_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['attempts','consumed_at']) OR NEW.attempts<OLD.attempts OR
    (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at) THEN
  RAISE EXCEPTION 'immutable MFA challenge' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth05_challenge_guard BEFORE UPDATE ON auth_challenges FOR EACH ROW EXECUTE FUNCTION auth05_challenge_guard();
CREATE FUNCTION auth05_recovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-'consumed_at') IS DISTINCT FROM (to_jsonb(OLD)-'consumed_at') OR
    (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at) THEN
  RAISE EXCEPTION 'immutable recovery code' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth05_recovery_guard BEFORE UPDATE ON auth_recovery_codes FOR EACH ROW EXECUTE FUNCTION auth05_recovery_guard();
CREATE FUNCTION auth05_factor_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['last_step','revoked_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['last_step','revoked_at']) OR NEW.last_step<OLD.last_step OR
    (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
  RAISE EXCEPTION 'immutable or replayed MFA factor' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth05_factor_guard BEFORE UPDATE ON auth_mfa_factors FOR EACH ROW EXECUTE FUNCTION auth05_factor_guard();
CREATE TRIGGER auth05_bootstrap_guard BEFORE UPDATE ON auth_bootstrap FOR EACH ROW EXECUTE FUNCTION auth05_recovery_guard();
CREATE FUNCTION auth05_session_mfa_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'immutable MFA session evidence' USING ERRCODE='23514';
END $$;
CREATE TRIGGER auth05_session_mfa_guard BEFORE UPDATE ON auth_session_mfa FOR EACH ROW EXECUTE FUNCTION auth05_session_mfa_guard();
