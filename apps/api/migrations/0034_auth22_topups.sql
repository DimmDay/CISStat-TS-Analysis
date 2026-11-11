-- AUTH-22 additive top-up checkout/credit. No auto-credit: packages exist only
-- where a trusted operator command provisioned them (design D1); credit is
-- bound to a confirmed server payment and the AUTH-21 wallet unique basis.
CREATE TABLE auth_topup_packages (
 package_id UUID PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 128),
 units BIGINT NOT NULL CHECK(units BETWEEN 1 AND 1000000000000),
 price_minor BIGINT NOT NULL CHECK(price_minor BETWEEN 1 AND 10000000000),
 currency TEXT NOT NULL CHECK(currency='RUB'),
 price_version TEXT NOT NULL CHECK(length(price_version) BETWEEN 1 AND 128),
 terms_version TEXT NOT NULL CHECK(length(terms_version) BETWEEN 1 AND 128),
 enabled BOOLEAN NOT NULL DEFAULT true,
 created_at TIMESTAMPTZ NOT NULL
);
-- Immutable price history: only an explicit enable->disable flip is allowed.
CREATE FUNCTION auth22_package_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'package retained' USING ERRCODE='23514'; END IF;
 IF (NEW.package_id,NEW.title,NEW.units,NEW.price_minor,NEW.currency,
     NEW.price_version,NEW.terms_version,NEW.created_at) IS DISTINCT FROM
    (OLD.package_id,OLD.title,OLD.units,OLD.price_minor,OLD.currency,
     OLD.price_version,OLD.terms_version,OLD.created_at)
 OR (OLD.enabled AND NOT NEW.enabled) IS NOT TRUE
 THEN RAISE EXCEPTION 'immutable package price history' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth22_package_guard BEFORE UPDATE OR DELETE ON auth_topup_packages FOR EACH ROW EXECUTE FUNCTION auth22_package_guard();

CREATE TABLE auth_topup_quotes (
 quote_id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES auth_accounts,
 owner_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 package_id UUID NOT NULL REFERENCES auth_topup_packages,
 snapshot JSONB NOT NULL,
 digest TEXT NOT NULL CHECK(length(digest)=64),
 created_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL CHECK(expires_at>created_at)
);
CREATE INDEX auth22_quote_rate ON auth_topup_quotes(account_id,created_at);
CREATE FUNCTION auth22_quote_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable top-up quote' USING ERRCODE='23514'; END $$;
CREATE TRIGGER auth22_quote_guard BEFORE UPDATE OR DELETE ON auth_topup_quotes FOR EACH ROW EXECUTE FUNCTION auth22_quote_guard();

CREATE TABLE auth_topup_orders (
 order_id UUID PRIMARY KEY,
 quote_id UUID NOT NULL UNIQUE REFERENCES auth_topup_quotes,
 account_id UUID NOT NULL REFERENCES auth_accounts,
 units BIGINT NOT NULL CHECK(units>0),
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','credited','canceled','review_required','paid_review')),
 payment_id TEXT UNIQUE CHECK(payment_id IS NULL OR payment_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 candidate_id TEXT CHECK(candidate_id IS NULL OR candidate_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 checkout_url TEXT,
 first_attempt_at TIMESTAMPTZ, next_attempt_at TIMESTAMPTZ NOT NULL,
 lease_until TIMESTAMPTZ, last_observed_at TIMESTAMPTZ,
 fence BIGINT NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL, paid_at TIMESTAMPTZ, credited_at TIMESTAMPTZ
);
CREATE INDEX auth22_due ON auth_topup_orders(next_attempt_at) WHERE state='pending';
CREATE FUNCTION auth22_order_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable top-up order' USING ERRCODE='23514'; END IF;
 IF (NEW.order_id,NEW.quote_id,NEW.account_id,NEW.units,NEW.created_at) IS DISTINCT FROM
    (OLD.order_id,OLD.quote_id,OLD.account_id,OLD.units,OLD.created_at)
 OR (OLD.payment_id IS NOT NULL AND NEW.payment_id IS DISTINCT FROM OLD.payment_id)
 OR (OLD.first_attempt_at IS NOT NULL AND NEW.first_attempt_at IS DISTINCT FROM OLD.first_attempt_at)
 OR (OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at)
 OR (OLD.credited_at IS NOT NULL AND NEW.credited_at IS DISTINCT FROM OLD.credited_at)
 -- Out-of-order provider events never reopen a decided top-up (13.4.5).
 -- paid_review -> credited is the single audited operator resolution (design D5).
 OR (OLD.state = 'credited' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.state = 'canceled' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.state = 'paid_review' AND NEW.state NOT IN ('paid_review','credited'))
 THEN RAISE EXCEPTION 'immutable top-up order binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth22_order_guard BEFORE UPDATE OR DELETE ON auth_topup_orders FOR EACH ROW EXECUTE FUNCTION auth22_order_guard_fn();

CREATE TABLE auth_topup_inbox (
 order_id UUID NOT NULL REFERENCES auth_topup_orders,
 payment_id TEXT NOT NULL CHECK(payment_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 event TEXT NOT NULL CHECK(event IN ('payment.succeeded','payment.canceled','payment.waiting_for_capture')),
 received_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(payment_id,event)
);
CREATE TRIGGER auth22_inbox_guard BEFORE UPDATE OR DELETE ON auth_topup_inbox FOR EACH ROW EXECUTE FUNCTION auth22_quote_guard();
