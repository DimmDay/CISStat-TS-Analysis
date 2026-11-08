-- Additive worker capability/attempt authority; 0025 bytes retained.
CREATE TABLE auth_worker_services (
 service_id UUID PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE CHECK(key_hash ~ '^[0-9a-f]{64}$'),
 kinds TEXT[] NOT NULL CHECK(cardinality(kinds)>0 AND kinds<@ARRAY['modeling','render','delivery']::text[]),
 created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL CHECK(expires_at>created_at),
 revoked_at TIMESTAMPTZ
);
CREATE TABLE auth_worker_jobs (
 worker_id UUID PRIMARY KEY, reservation_id UUID UNIQUE REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('modeling','render','delivery')), external_id TEXT NOT NULL,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 tenant_id UUID NOT NULL, subject_id UUID REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
 delegation JSONB NOT NULL, descriptor JSONB NOT NULL, input_digest TEXT NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
 run_id TEXT NOT NULL, session_id TEXT, context_id TEXT,
 state TEXT NOT NULL CHECK(state IN ('queued','running','uncertain','completed','failed','cancelled')),
 fence BIGINT NOT NULL DEFAULT 1 CHECK(fence>0), attempt_fence BIGINT, accrued_cu BIGINT NOT NULL DEFAULT 0 CHECK(accrued_cu>=0), phase BIGINT NOT NULL DEFAULT 0 CHECK(phase>=0),
 service_id UUID REFERENCES auth_worker_services(service_id) ON DELETE RESTRICT,
 lease_until TIMESTAMPTZ, deadline TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 stop_proof JSONB, result_digest TEXT, error_code TEXT,
 CHECK(kind='delivery' OR reservation_id IS NOT NULL),
 UNIQUE(kind,external_id), CHECK(deadline>created_at)
);
CREATE INDEX auth13_pending ON auth_worker_jobs(state,lease_until,deadline);
CREATE FUNCTION auth13_service_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR
    (to_jsonb(OLD)-'revoked_at') IS DISTINCT FROM (to_jsonb(NEW)-'revoked_at') THEN
  RAISE EXCEPTION 'immutable worker service credential' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth13_service_guard BEFORE UPDATE OR DELETE ON auth_worker_services FOR EACH ROW EXECUTE FUNCTION auth13_service_guard();
CREATE FUNCTION auth13_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR OLD.state IN ('completed','failed','cancelled') OR NEW.fence<>OLD.fence+1 OR
    (to_jsonb(OLD)-ARRAY['state','fence','phase','service_id','lease_until','stop_proof','result_digest','error_code','attempt_fence','accrued_cu']) IS DISTINCT FROM
    (to_jsonb(NEW)-ARRAY['state','fence','phase','service_id','lease_until','stop_proof','result_digest','error_code','attempt_fence','accrued_cu']) OR
    NEW.phase<OLD.phase OR NEW.phase>OLD.phase+1 OR NEW.accrued_cu<OLD.accrued_cu OR
    NOT ((OLD.state='queued' AND NEW.state IN ('running','cancelled','failed')) OR
         (OLD.state='running' AND NEW.state IN ('queued','running','uncertain','completed','failed','cancelled')) OR
         (OLD.state='uncertain' AND NEW.state IN ('uncertain','failed','cancelled'))) THEN
  RAISE EXCEPTION 'worker state/fence/binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth13_job_guard BEFORE UPDATE OR DELETE ON auth_worker_jobs FOR EACH ROW EXECUTE FUNCTION auth13_job_guard();
