-- AUTH-12 additive authority. No commercial credit/pricing or legacy usage invented.
CREATE TABLE auth_budget_scopes (
 scope_id UUID PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('sponsor','campaign','account','grant')),
 parent_id UUID REFERENCES auth_budget_scopes(scope_id) ON DELETE RESTRICT,
 account_id UUID REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','closed')),
 starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ,
 version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
 CHECK(ends_at IS NULL OR ends_at>starts_at), CHECK(scope_id IS DISTINCT FROM parent_id),
 CHECK((kind IN ('account','grant'))=(account_id IS NOT NULL)),
 CHECK(kind<>'account' OR scope_id=account_id),
 CHECK(kind NOT IN ('campaign','grant') OR ends_at IS NOT NULL)
);
CREATE UNIQUE INDEX auth12_account_scope ON auth_budget_scopes(account_id) WHERE kind='account';
CREATE UNIQUE INDEX auth12_grant_scope ON auth_budget_scopes(account_id) WHERE kind='grant';
CREATE TABLE auth_resource_budgets (
 budget_id UUID PRIMARY KEY, scope_id UUID NOT NULL REFERENCES auth_budget_scopes(scope_id) ON DELETE RESTRICT,
 metric TEXT NOT NULL CHECK(metric IN ('cu','api','analysis','concurrency')),
 period TEXT NOT NULL CHECK(period='lifetime' OR period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
 limit_units BIGINT CHECK(limit_units>=0), reserved BIGINT NOT NULL DEFAULT 0 CHECK(reserved>=0),
 spent BIGINT NOT NULL DEFAULT 0 CHECK(spent>=0), version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
 CHECK(metric NOT IN ('cu','concurrency') OR limit_units IS NOT NULL),
 CHECK(reserved::numeric+spent::numeric<=9223372036854775807),
 CHECK(metric IN ('api','analysis') OR reserved::numeric+spent::numeric<=limit_units),
 UNIQUE(scope_id,metric,period)
);
CREATE TABLE auth_reservations (
 reservation_id UUID PRIMARY KEY, account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 subject_id UUID NOT NULL REFERENCES auth_identities(subject_id) ON DELETE RESTRICT,
 tenant_id UUID NOT NULL, canonical_operation TEXT NOT NULL,
 key_digest TEXT NOT NULL CHECK(key_digest ~ '^[a-f0-9]{64}$'),
 payload_digest TEXT NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 admission JSONB NOT NULL CHECK(jsonb_typeof(admission)='object'),
 quote_version TEXT NOT NULL, held_cu BIGINT NOT NULL CHECK(held_cu>=0),
 actual_cu BIGINT CHECK(actual_cu>=0 AND actual_cu<=held_cu),
 state TEXT NOT NULL CHECK(state IN ('pending','running','settled','released')),
 version BIGINT NOT NULL DEFAULT 1 CHECK(version>0), created_at TIMESTAMPTZ NOT NULL,
 deadline TIMESTAMPTZ NOT NULL, lease_until TIMESTAMPTZ,
 result_ref TEXT CHECK(length(result_ref)<=160), CHECK(deadline>created_at),
 CHECK((state='settled')=(actual_cu IS NOT NULL)),
 UNIQUE(account_id,subject_id,canonical_operation,key_digest)
);
CREATE TABLE auth_reservation_allocations (
 reservation_id UUID NOT NULL REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 budget_id UUID NOT NULL REFERENCES auth_resource_budgets(budget_id) ON DELETE RESTRICT,
 units BIGINT NOT NULL CHECK(units>0), metric TEXT NOT NULL CHECK(metric IN ('cu','api','analysis','concurrency')),
 PRIMARY KEY(reservation_id,budget_id)
);
CREATE TABLE auth_usage_postings (
 reservation_id UUID NOT NULL REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 event_no BIGINT NOT NULL CHECK(event_no>0), budget_id UUID NOT NULL REFERENCES auth_resource_budgets(budget_id) ON DELETE RESTRICT,
 available_delta BIGINT NOT NULL, reserved_delta BIGINT NOT NULL, spent_delta BIGINT NOT NULL,
 CHECK(available_delta::numeric+reserved_delta::numeric+spent_delta::numeric=0),
 CHECK(available_delta<>0 OR reserved_delta<>0 OR spent_delta<>0),
 PRIMARY KEY(reservation_id,event_no,budget_id)
);
CREATE TABLE auth_analysis_claims (
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT, run_id TEXT NOT NULL,
 reservation_id UUID NOT NULL REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 PRIMARY KEY(account_id,run_id)
);
-- Durable job intent is committed with reserve; actual queue delivery/worker adapters AUTH-13.
CREATE TABLE auth_job_outbox (
 reservation_id UUID PRIMARY KEY REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'), created_at TIMESTAMPTZ NOT NULL,
 delivered_at TIMESTAMPTZ
);
CREATE FUNCTION auth12_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'immutable budget history' USING ERRCODE='23514'; END $$;
CREATE TRIGGER auth12_postings_immutable BEFORE UPDATE OR DELETE ON auth_usage_postings FOR EACH ROW EXECUTE FUNCTION auth12_immutable();
CREATE TRIGGER auth12_claims_immutable BEFORE UPDATE OR DELETE ON auth_analysis_claims FOR EACH ROW EXECUTE FUNCTION auth12_immutable();
CREATE FUNCTION auth12_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p auth_budget_scopes%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'scope retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(OLD)-ARRAY['status','version']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['status','version'])
     OR NEW.version<>OLD.version+1 OR OLD.status='closed' THEN
   RAISE EXCEPTION 'immutable scope binding' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.parent_id IS NOT NULL THEN
  SELECT * INTO p FROM auth_budget_scopes WHERE scope_id=NEW.parent_id;
 END IF;
 IF NOT COALESCE(((NEW.kind='sponsor' AND NEW.parent_id IS NULL) OR
         (NEW.kind='campaign' AND p.kind='sponsor') OR
         (NEW.kind='account' AND (NEW.parent_id IS NULL OR p.kind IN ('sponsor','campaign'))) OR
         (NEW.kind='grant' AND p.kind='account' AND p.account_id=NEW.account_id)),FALSE) THEN
  RAISE EXCEPTION 'invalid budget hierarchy' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth12_scope_guard BEFORE INSERT OR UPDATE OR DELETE ON auth_budget_scopes FOR EACH ROW EXECUTE FUNCTION auth12_scope_guard();
-- Projection is advanced ONLY by append-only postings, in O(1), never a history rescan.
CREATE FUNCTION auth12_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'budget retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.reserved<>0 OR NEW.spent<>0 OR NEW.version<>1 THEN
   RAISE EXCEPTION 'budget starts without fabricated usage' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.budget_id,NEW.scope_id,NEW.metric,NEW.period) IS DISTINCT FROM (OLD.budget_id,OLD.scope_id,OLD.metric,OLD.period)
    OR NEW.version<>OLD.version+1 OR
    ((NEW.reserved,NEW.spent) IS DISTINCT FROM (OLD.reserved,OLD.spent) AND pg_trigger_depth()<2) THEN
  RAISE EXCEPTION 'budget version/binding/projection' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth12_budget_guard BEFORE INSERT OR UPDATE OR DELETE ON auth_resource_budgets FOR EACH ROW EXECUTE FUNCTION auth12_budget_guard();
CREATE FUNCTION auth12_projection_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 UPDATE auth_resource_budgets SET reserved=reserved+NEW.reserved_delta,spent=spent+NEW.spent_delta,version=version+1
 WHERE budget_id=NEW.budget_id;
 RETURN NULL;
END $$;
CREATE TRIGGER auth12_posting_projection AFTER INSERT ON auth_usage_postings FOR EACH ROW EXECUTE FUNCTION auth12_projection_guard();
CREATE INDEX auth12_postings_budget ON auth_usage_postings(budget_id,reservation_id,event_no);
CREATE FUNCTION auth12_reservation_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'reservation retained' USING ERRCODE='23514'; END IF;
 IF OLD.state IN ('settled','released') OR NEW.version<>OLD.version+1 OR
  (to_jsonb(OLD)-ARRAY['state','version','held_cu','actual_cu','lease_until','result_ref']) IS DISTINCT FROM
  (to_jsonb(NEW)-ARRAY['state','version','held_cu','actual_cu','lease_until','result_ref']) OR
  NOT ((OLD.state='pending' AND NEW.state IN ('running','released')) OR
       (OLD.state='running' AND NEW.state IN ('running','settled'))) OR NEW.held_cu<OLD.held_cu THEN
  RAISE EXCEPTION 'reservation state/version/binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth12_reservation_guard BEFORE UPDATE OR DELETE ON auth_reservations FOR EACH ROW EXECUTE FUNCTION auth12_reservation_guard();
CREATE FUNCTION auth12_allocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR NEW.reservation_id<>OLD.reservation_id OR NEW.budget_id<>OLD.budget_id OR
    NEW.metric<>'cu' OR NEW.metric<>OLD.metric OR NEW.units<=OLD.units THEN
  RAISE EXCEPTION 'immutable allocation' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth12_allocation_guard BEFORE UPDATE OR DELETE ON auth_reservation_allocations FOR EACH ROW EXECUTE FUNCTION auth12_allocation_guard();
CREATE FUNCTION auth12_outbox_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(OLD)-'delivered_at') IS DISTINCT FROM (to_jsonb(NEW)-'delivered_at') OR OLD.delivered_at IS NOT NULL THEN
  RAISE EXCEPTION 'immutable job intent' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth12_outbox_guard BEFORE UPDATE OR DELETE ON auth_job_outbox FOR EACH ROW EXECUTE FUNCTION auth12_outbox_guard();
