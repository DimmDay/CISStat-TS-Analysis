-- AUTH-19: external (OIDC / personal email trial) sessions and one-time
-- entry states. Additive only; 0019–0030 checksums stay immutable.
--
-- AUTH-15 already made credential_id nullable for demo sessions and locked
-- the (credential_id, demo_grant_id) pair with auth15_session_family. AUTH-19
-- adds a third session kind: a verified external identity has NEITHER a
-- password credential NOR a demo grant. The family check is honestly
-- extended here (the 0027 checksum itself stays untouched).
ALTER TABLE auth_sessions ALTER COLUMN credential_version DROP NOT NULL;
ALTER TABLE auth_sessions DROP CONSTRAINT auth15_session_family;
ALTER TABLE auth_sessions ADD CONSTRAINT auth15_session_family CHECK (
    (credential_id IS NOT NULL AND demo_grant_id IS NULL)      -- password (AUTH-04)
    OR (credential_id IS NULL AND demo_grant_id IS NOT NULL)   -- demo (AUTH-15)
    OR (credential_id IS NULL AND demo_grant_id IS NULL)       -- external (AUTH-19)
);

-- One-time email entry challenge: magic-link token and OTP both keyed-hash,
-- finite attempts, honest delivery state; consume is a POST command only.
CREATE TABLE auth_email_challenges (
    challenge_id UUID PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('trial_login','email_bind')),
    email TEXT COLLATE "C" NOT NULL CHECK (length(email) BETWEEN 6 AND 320 AND position('@' IN email) > 1),
    token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    code_hash TEXT NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    subject_id UUID REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK (length(origin) BETWEEN 1 AND 512),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    delivered_at TIMESTAMPTZ,
    delivery_code TEXT NOT NULL DEFAULT 'pending' CHECK (delivery_code IN ('pending','sent','failed')),
    consumed_at TIMESTAMPTZ,
    CHECK (issued_at < expires_at),
    CHECK ((purpose='email_bind') = (subject_id IS NOT NULL))
);
CREATE INDEX auth_email_challenge_email ON auth_email_challenges(email,expires_at);
CREATE INDEX auth_email_challenge_email_code ON auth_email_challenges(email,code_hash) WHERE consumed_at IS NULL;

-- One-time OIDC authorization states and post-authentication account
-- selection tokens. state_hash only; nonce/PKCE verifier never leave the DB.
CREATE TABLE auth_login_states (
    state_id UUID PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('oidc_login','oidc_link','oidc_select','email_select')),
    state_hash TEXT NOT NULL UNIQUE CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    nonce TEXT,
    pkce_verifier TEXT,
    subject_id UUID REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK (length(origin) BETWEEN 1 AND 512),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CHECK (issued_at < expires_at),
    CHECK ((nonce IS NOT NULL AND pkce_verifier IS NOT NULL) = (purpose IN ('oidc_login','oidc_link'))),
    CHECK ((subject_id IS NOT NULL) = (purpose <> 'oidc_login'))
);
CREATE INDEX auth_login_state_subject ON auth_login_states(subject_id,expires_at);

-- A consumed challenge/state cannot be resurrected or rewritten.
CREATE FUNCTION auth19_email_challenge_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['attempts','delivered_at','delivery_code','consumed_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['attempts','delivered_at','delivery_code','consumed_at']) OR
    NEW.attempts<OLD.attempts OR
    (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at) OR
    (OLD.delivery_code='sent' AND NEW.delivery_code<>'sent') THEN
  RAISE EXCEPTION 'immutable email challenge' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth19_email_challenge_guard BEFORE UPDATE ON auth_email_challenges
FOR EACH ROW EXECUTE FUNCTION auth19_email_challenge_guard();
CREATE FUNCTION auth19_login_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['consumed_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['consumed_at']) OR
    (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at) THEN
  RAISE EXCEPTION 'immutable login state' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth19_login_state_guard BEFORE UPDATE ON auth_login_states
FOR EACH ROW EXECUTE FUNCTION auth19_login_state_guard();
