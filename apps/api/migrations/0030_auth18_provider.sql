-- Additive subscription provider authority. No destructive migration or existing ledger reset.
CREATE TABLE auth_billing_cycles (
 cycle_id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES auth_accounts,
 starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL CHECK(ends_at>starts_at),
 config jsonb NOT NULL, seats integer NOT NULL CHECK(seats BETWEEN 1 AND 1000),
 adjustment_numerator numeric(40,0) NOT NULL DEFAULT 0,
 version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 UNIQUE(account_id)
);
CREATE TABLE auth_billing_quotes (
 quote_id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES auth_accounts,
 request_id uuid NOT NULL REFERENCES auth_seat_requests,
 owner_id uuid NOT NULL REFERENCES auth_identities(subject_id),
 cycle_id uuid NOT NULL REFERENCES auth_billing_cycles,
 snapshot jsonb NOT NULL, digest text NOT NULL CHECK(length(digest)=64),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL CHECK(expires_at>created_at)
);
CREATE TABLE auth_billing_orders (
 order_id uuid PRIMARY KEY, quote_id uuid NOT NULL UNIQUE REFERENCES auth_billing_quotes,
 account_id uuid NOT NULL REFERENCES auth_accounts,
 request_id uuid NOT NULL UNIQUE REFERENCES auth_seat_requests,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','applied','canceled','review_required','paid_review')),
 payment_id text UNIQUE, candidate_id text, checkout_url text,
 first_attempt_at timestamptz, next_attempt_at timestamptz NOT NULL,
 lease_until timestamptz, last_observed_at timestamptz, fence bigint NOT NULL DEFAULT 0, attempts integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL, paid_at timestamptz,
 CHECK(payment_id IS NULL OR payment_id ~ '^[A-Za-z0-9_-]{1,64}$')
);
CREATE INDEX auth18_due ON auth_billing_orders(next_attempt_at) WHERE state='pending';
CREATE TABLE auth_provider_inbox (
 order_id uuid NOT NULL REFERENCES auth_billing_orders,
 payment_id text NOT NULL CHECK(payment_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 event text NOT NULL CHECK(event IN ('payment.succeeded','payment.canceled','payment.waiting_for_capture')),
 received_at timestamptz NOT NULL,
 PRIMARY KEY(payment_id,event)
);
CREATE TABLE auth_billing_adjustments (
 order_id uuid PRIMARY KEY REFERENCES auth_billing_orders,
 cycle_id uuid NOT NULL REFERENCES auth_billing_cycles,
 delta_numerator numeric(40,0) NOT NULL,
 duration_us bigint NOT NULL CHECK(duration_us>0),
 included_entitlement bigint NOT NULL CHECK(included_entitlement>=0),
 created_at timestamptz NOT NULL
);
CREATE FUNCTION auth18_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable billing history'; END $$;
CREATE TRIGGER auth18_quote_guard BEFORE UPDATE OR DELETE ON auth_billing_quotes FOR EACH ROW EXECUTE FUNCTION auth18_immutable();
CREATE TRIGGER auth18_adjustment_guard BEFORE UPDATE OR DELETE ON auth_billing_adjustments FOR EACH ROW EXECUTE FUNCTION auth18_immutable();
CREATE FUNCTION auth18_order_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable billing order'; END IF;
 IF (NEW.order_id,NEW.quote_id,NEW.account_id,NEW.request_id,NEW.created_at) IS DISTINCT FROM
    (OLD.order_id,OLD.quote_id,OLD.account_id,OLD.request_id,OLD.created_at)
 OR (OLD.payment_id IS NOT NULL AND NEW.payment_id IS DISTINCT FROM OLD.payment_id)
 OR (OLD.first_attempt_at IS NOT NULL AND NEW.first_attempt_at IS DISTINCT FROM OLD.first_attempt_at)
 OR (OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at)
 OR (OLD.state IN ('applied','paid_review') AND NEW.state IS DISTINCT FROM OLD.state)
 THEN RAISE EXCEPTION 'immutable billing order binding'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth18_order_guard BEFORE UPDATE OR DELETE ON auth_billing_orders FOR EACH ROW EXECUTE FUNCTION auth18_order_guard_fn();
CREATE FUNCTION auth18_cycle_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable billing cycle'; END IF;
 IF (NEW.cycle_id,NEW.account_id,NEW.starts_at,NEW.ends_at,NEW.config) IS DISTINCT FROM
    (OLD.cycle_id,OLD.account_id,OLD.starts_at,OLD.ends_at,OLD.config)
 OR NEW.version<>OLD.version+1 THEN RAISE EXCEPTION 'immutable cycle terms/CAS'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth18_cycle_guard BEFORE UPDATE OR DELETE ON auth_billing_cycles FOR EACH ROW EXECUTE FUNCTION auth18_cycle_guard_fn();
CREATE TRIGGER auth18_inbox_guard BEFORE UPDATE OR DELETE ON auth_provider_inbox FOR EACH ROW EXECUTE FUNCTION auth18_immutable();
