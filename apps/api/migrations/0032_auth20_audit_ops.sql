-- AUTH-20 additive audit/operations authority. No request-path DDL.
-- Durable revocation ledger: terminal security transitions are captured at
-- the PostgreSQL level regardless of the code path (fail-closed by design).
-- Retention pruning is the only permitted DELETE; UPDATE is forbidden.

CREATE TABLE auth_ops_ledger (
    entry_id BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL CHECK (table_name IN (
        'auth_password_credentials','auth_sessions','auth_api_keys',
        'auth_worker_services','auth_demo_grants','auth_demo_admissions',
        'auth_reservations','auth_billing_orders')),
    row_id UUID NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('revoked','consumed','settled','released','applied','canceled')),
    row_image JSONB NOT NULL CHECK (jsonb_typeof(row_image)='object'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX auth20_ledger_recent ON auth_ops_ledger(occurred_at);
CREATE INDEX auth20_ledger_row ON auth_ops_ledger(table_name,row_id,entry_id);

-- Append-only integrity: UPDATE forbidden; DELETE is retention-only (sweeper).
CREATE FUNCTION auth20_ledger_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'auth_ops_ledger is append-only' USING ERRCODE='23514'; END IF;
    RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER auth20_ledger_guard BEFORE UPDATE OR DELETE ON auth_ops_ledger
    FOR EACH ROW EXECUTE FUNCTION auth20_ledger_guard();

-- One capture function for all eight guarded tables; terminal transitions only.
CREATE FUNCTION auth20_ops_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_table TEXT := TG_TABLE_NAME;
    v_event TEXT;
    v_row_id UUID;
    v_image JSONB;
BEGIN
    IF v_table='auth_password_credentials' THEN
        IF OLD.status='active' AND NEW.status='revoked' THEN
            v_event:='revoked'; v_row_id:=NEW.credential_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_sessions' THEN
        IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
            v_event:='revoked'; v_row_id:=NEW.session_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_api_keys' THEN
        IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
            v_event:='revoked'; v_row_id:=NEW.key_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_worker_services' THEN
        IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
            v_event:='revoked'; v_row_id:=NEW.service_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_demo_grants' THEN
        IF OLD.status<>'revoked' AND NEW.status='revoked' THEN
            v_event:='revoked'; v_row_id:=NEW.grant_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_demo_admissions' THEN
        IF OLD.redeemed_at IS NULL AND NEW.redeemed_at IS NOT NULL THEN
            v_event:='consumed'; v_row_id:=NEW.admission_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_reservations' THEN
        IF OLD.state NOT IN ('settled','released') AND NEW.state IN ('settled','released') THEN
            v_event:=NEW.state; v_row_id:=NEW.reservation_id; v_image:=to_jsonb(NEW);
        END IF;
    ELSIF v_table='auth_billing_orders' THEN
        IF OLD.state='pending' AND NEW.state IN ('applied','canceled') THEN
            v_event:=NEW.state; v_row_id:=NEW.order_id; v_image:=to_jsonb(NEW);
        END IF;
    END IF;
    IF v_event IS NOT NULL THEN
        INSERT INTO auth_ops_ledger(table_name,row_id,event,row_image)
        VALUES (v_table,v_row_id,v_event,v_image);
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER auth20_capture_password AFTER UPDATE ON auth_password_credentials
    FOR EACH ROW WHEN (OLD.status='active' AND NEW.status='revoked')
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_sessions AFTER UPDATE ON auth_sessions
    FOR EACH ROW WHEN (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL)
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_api_keys AFTER UPDATE ON auth_api_keys
    FOR EACH ROW WHEN (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL)
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_worker_services AFTER UPDATE ON auth_worker_services
    FOR EACH ROW WHEN (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL)
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_demo_grants AFTER UPDATE ON auth_demo_grants
    FOR EACH ROW WHEN (OLD.status <> 'revoked' AND NEW.status='revoked')
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_demo_admissions AFTER UPDATE ON auth_demo_admissions
    FOR EACH ROW WHEN (OLD.redeemed_at IS NULL AND NEW.redeemed_at IS NOT NULL)
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_reservations AFTER UPDATE ON auth_reservations
    FOR EACH ROW WHEN (OLD.state NOT IN ('settled','released') AND NEW.state IN ('settled','released'))
    EXECUTE FUNCTION auth20_ops_capture();
CREATE TRIGGER auth20_capture_billing_orders AFTER UPDATE ON auth_billing_orders
    FOR EACH ROW WHEN (OLD.state='pending' AND NEW.state IN ('applied','canceled'))
    EXECUTE FUNCTION auth20_ops_capture();
