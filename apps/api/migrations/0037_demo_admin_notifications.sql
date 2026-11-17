-- Separate delivery state; no login proofs, tokens, cookies or arbitrary payloads.
CREATE TABLE auth_demo_admin_notifications (
 notification_id uuid PRIMARY KEY REFERENCES auth_personal_trials(subject_id),
 user_email text NOT NULL CHECK(length(user_email) BETWEEN 6 AND 320),
 issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL CHECK(expires_at>issued_at),
 micro_cu bigint NOT NULL CHECK(micro_cu>0), analyses integer NOT NULL CHECK(analyses>0),
 concurrency integer NOT NULL CHECK(concurrency>0), max_rows integer NOT NULL CHECK(max_rows>0),
 recipient text,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 claim_id uuid, lease_until timestamptz, sent_at timestamptz,
 last_error_code text CHECK(last_error_code IS NULL OR last_error_code='smtp_unavailable'),
 CHECK((status='sending' AND claim_id IS NOT NULL AND lease_until IS NOT NULL) OR
       (status<>'sending' AND claim_id IS NULL AND lease_until IS NULL)),
 CHECK((status='sent')=(sent_at IS NOT NULL))
);
CREATE INDEX demo_admin_delivery_due ON auth_demo_admin_notifications(next_attempt_at) WHERE status<>'sent';
CREATE FUNCTION demo_admin_notice_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR
 (to_jsonb(NEW)-ARRAY['recipient','status','attempts','next_attempt_at','claim_id','lease_until','sent_at','last_error_code'])
 IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['recipient','status','attempts','next_attempt_at','claim_id','lease_until','sent_at','last_error_code'])
 OR (OLD.recipient IS NOT NULL AND NEW.recipient IS DISTINCT FROM OLD.recipient) THEN
 RAISE EXCEPTION 'immutable admin notice content' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER demo_admin_notice_guard BEFORE UPDATE OR DELETE ON auth_demo_admin_notifications
 FOR EACH ROW EXECUTE FUNCTION demo_admin_notice_guard_fn();
