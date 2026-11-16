-- One finite pilot pool. No modification of previous receipts, usage or purchased lots.
CREATE TABLE auth_personal_demo_pool (
 pool_id uuid PRIMARY KEY, sponsor_id uuid NOT NULL UNIQUE REFERENCES auth_budget_scopes,
 signup_ends_at timestamptz NOT NULL, max_trials integer NOT NULL CHECK(max_trials BETWEEN 1 AND 10000),
 days integer NOT NULL CHECK(days BETWEEN 1 AND 30), micro_cu bigint NOT NULL CHECK(micro_cu BETWEEN 1 AND 1000000000000),
 analyses integer NOT NULL CHECK(analyses BETWEEN 1 AND 100), status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused'))
);
CREATE TABLE auth_personal_trials (
 subject_id uuid PRIMARY KEY REFERENCES auth_identities,
 account_id uuid NOT NULL UNIQUE REFERENCES auth_accounts,
 email_hash text NOT NULL UNIQUE CHECK(length(email_hash)=64),
 pool_id uuid NOT NULL REFERENCES auth_personal_demo_pool,
 lot_id uuid NOT NULL UNIQUE REFERENCES auth_wallet_lots,
 issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL CHECK(expires_at>issued_at)
);
CREATE FUNCTION personal_pool_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') THEN
 RAISE EXCEPTION 'immutable personal pool policy' USING ERRCODE='23514'; END IF; RETURN NEW;
END $$;
CREATE TRIGGER personal_pool_guard BEFORE UPDATE OR DELETE ON auth_personal_demo_pool FOR EACH ROW EXECUTE FUNCTION personal_pool_guard_fn();
CREATE TRIGGER personal_trials_guard BEFORE UPDATE OR DELETE ON auth_personal_trials FOR EACH ROW EXECUTE FUNCTION auth12_immutable();
DO $$ DECLARE
 pid uuid := '00000000-0000-4000-8000-000000000036';
 sid uuid := '00000000-0000-4000-8000-000000000136';
 cutoff timestamptz := clock_timestamp()+interval '30 days';
 period_start timestamptz := date_trunc('month',clock_timestamp());
BEGIN
 INSERT INTO auth_budget_scopes(scope_id,kind,starts_at,ends_at) VALUES(sid,'sponsor',date_trunc('day',clock_timestamp()),cutoff+interval '14 days');
 INSERT INTO auth_personal_demo_pool(pool_id,sponsor_id,signup_ends_at,max_trials,days,micro_cu,analyses) VALUES(pid,sid,cutoff,100,14,100000000,10);
 INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units) VALUES
 (gen_random_uuid(),sid,'cu','lifetime',10000000000),
 (gen_random_uuid(),sid,'analysis','lifetime',1000),
 (gen_random_uuid(),sid,'concurrency','lifetime',2);
 WHILE period_start < cutoff+interval '14 days' LOOP
 INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units)
 VALUES(gen_random_uuid(),sid,'api',to_char(period_start AT TIME ZONE 'UTC','YYYY-MM'),100000);
 period_start := period_start+interval '1 month';
 END LOOP;
END $$;
