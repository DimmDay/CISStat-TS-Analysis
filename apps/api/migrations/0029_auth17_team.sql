-- AUTH-17; existing AUTH-02 membership/capacity/last OWNER constraints remain.
CREATE TABLE auth_team_commands (
 command_id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id),
 subject_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 operation TEXT NOT NULL, key_hash TEXT NOT NULL, body_hash TEXT NOT NULL,
 response JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(account_id,subject_id,operation,key_hash)
);
CREATE TABLE auth_invitations (
 invitation_id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id),
 inviter_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 target_subject_id UUID REFERENCES auth_identities(subject_id),
 email TEXT,
 token_hash TEXT NOT NULL UNIQUE CHECK(token_hash ~ '^[a-f0-9]{64}$'),
 created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 consumed_at TIMESTAMPTZ, consumed_by UUID REFERENCES auth_identities(subject_id),
 revoked_at TIMESTAMPTZ,
 CHECK(target_subject_id IS NOT NULL OR email IS NOT NULL),
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '7 days'),
 CHECK((consumed_at IS NULL)=(consumed_by IS NULL)),
 CHECK(consumed_at IS NULL OR revoked_at IS NULL),
 CHECK(consumed_by IS NULL OR target_subject_id IS NULL OR consumed_by=target_subject_id)
);
CREATE INDEX auth17_invites_account ON auth_invitations(account_id,created_at DESC);
CREATE TABLE auth_seat_requests (
 request_id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id),
 requested_by UUID NOT NULL REFERENCES auth_identities(subject_id),
 seats INTEGER NOT NULL CHECK(seats BETWEEN 1 AND 1000),
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','applied','rejected')),
 created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 confirmation_ref TEXT UNIQUE CHECK(length(confirmation_ref) BETWEEN 1 AND 128),
 completed_at TIMESTAMPTZ,
 CHECK(expires_at>created_at),
 CHECK((state='pending')=(completed_at IS NULL)),
 CHECK((state='applied')=(confirmation_ref IS NOT NULL))
);
CREATE UNIQUE INDEX auth17_one_pending_capacity ON auth_seat_requests(account_id) WHERE state='pending';
CREATE FUNCTION auth17_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'team command history retained' USING ERRCODE='23514'; END $$;
CREATE TRIGGER auth17_commands_guard BEFORE UPDATE OR DELETE ON auth_team_commands FOR EACH ROW EXECUTE FUNCTION auth17_history_guard();
CREATE FUNCTION auth17_invitation_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['consumed_at','consumed_by','revoked_at']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['consumed_at','consumed_by','revoked_at']) OR OLD.consumed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN
 RAISE EXCEPTION 'immutable invitation binding or terminal history' USING ERRCODE='23514'; END IF; RETURN NEW;
 END $$;
CREATE TRIGGER auth17_invitation_guard BEFORE UPDATE OR DELETE ON auth_invitations FOR EACH ROW EXECUTE FUNCTION auth17_invitation_guard();
CREATE FUNCTION auth17_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR OLD.state<>'pending' OR NEW.state='pending' OR
 (to_jsonb(NEW)-ARRAY['state','confirmation_ref','completed_at']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['state','confirmation_ref','completed_at']) THEN
 RAISE EXCEPTION 'immutable capacity intent' USING ERRCODE='23514'; END IF; RETURN NEW;
 END $$;
CREATE TRIGGER auth17_request_guard BEFORE UPDATE OR DELETE ON auth_seat_requests FOR EACH ROW EXECUTE FUNCTION auth17_request_guard();
