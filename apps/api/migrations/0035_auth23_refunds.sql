-- AUTH-23 additive refund/dispute workflow. No auto-anything: a refund exists
-- only where an OWNER requested it for a credited whole unused purchased lot
-- (spec_billing_accounts.md §13.7), disputes are opened by trusted commands.
-- Wallet bucket movements reuse the 0033 posting events (0033 stays byte-identical).
CREATE TABLE auth_refund_orders (
 refund_id UUID PRIMARY KEY,
 order_id UUID NOT NULL UNIQUE REFERENCES auth_topup_orders,
 account_id UUID NOT NULL REFERENCES auth_accounts,
 lot_id UUID NOT NULL REFERENCES auth_wallet_lots(lot_id) ON DELETE RESTRICT,
 owner_id UUID NOT NULL REFERENCES auth_identities(subject_id),
 units BIGINT NOT NULL CHECK(units>0),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL CHECK(currency='RUB'),
 terms_version TEXT NOT NULL CHECK(length(terms_version) BETWEEN 1 AND 128),
 window_days INTEGER NOT NULL CHECK(window_days BETWEEN 0 AND 90),
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','refunded','failed','review_required')),
 provider_refund_id TEXT UNIQUE CHECK(provider_refund_id IS NULL OR provider_refund_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 first_attempt_at TIMESTAMPTZ, next_attempt_at TIMESTAMPTZ NOT NULL,
 lease_until TIMESTAMPTZ, fence BIGINT NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL, decided_at TIMESTAMPTZ
);
CREATE INDEX auth23_refund_due ON auth_refund_orders(next_attempt_at) WHERE state='pending';
CREATE FUNCTION auth23_refund_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable refund order' USING ERRCODE='23514'; END IF;
 IF (NEW.refund_id,NEW.order_id,NEW.account_id,NEW.lot_id,NEW.owner_id,NEW.units,NEW.amount_minor,
     NEW.currency,NEW.terms_version,NEW.window_days,NEW.created_at) IS DISTINCT FROM
    (OLD.refund_id,OLD.order_id,OLD.account_id,OLD.lot_id,OLD.owner_id,OLD.units,OLD.amount_minor,
     OLD.currency,OLD.terms_version,OLD.window_days,OLD.created_at)
 OR (OLD.provider_refund_id IS NOT NULL AND NEW.provider_refund_id IS DISTINCT FROM OLD.provider_refund_id)
 OR (OLD.first_attempt_at IS NOT NULL AND NEW.first_attempt_at IS DISTINCT FROM OLD.first_attempt_at)
 OR (OLD.decided_at IS NOT NULL AND NEW.decided_at IS DISTINCT FROM OLD.decided_at)
 -- Unknown provider outcomes never unlock a hold by themselves (13.7.3).
 OR (OLD.state='refunded' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.state='failed' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.state='review_required' AND NEW.state NOT IN ('review_required','pending'))
 THEN RAISE EXCEPTION 'immutable refund order binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth23_refund_guard BEFORE UPDATE OR DELETE ON auth_refund_orders FOR EACH ROW EXECUTE FUNCTION auth23_refund_guard_fn();

CREATE TABLE auth_disputes (
 dispute_id UUID PRIMARY KEY,
 order_id UUID NOT NULL UNIQUE REFERENCES auth_topup_orders,
 account_id UUID NOT NULL REFERENCES auth_accounts,
 lot_id UUID NOT NULL REFERENCES auth_wallet_lots(lot_id) ON DELETE RESTRICT,
 payment_id TEXT CHECK(payment_id IS NULL OR payment_id ~ '^[A-Za-z0-9_-]{1,64}$'),
 spent_units BIGINT NOT NULL CHECK(spent_units>=0),
 disputed_units BIGINT NOT NULL CHECK(disputed_units>0),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL CHECK(currency='RUB'),
 wallet_was_locked BOOLEAN NOT NULL DEFAULT false,
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','lost','won')),
 opened_reason TEXT NOT NULL CHECK(length(opened_reason) BETWEEN 1 AND 256),
 resolution_reason TEXT CHECK(resolution_reason IS NULL OR length(resolution_reason) BETWEEN 1 AND 256),
 created_at TIMESTAMPTZ NOT NULL, resolved_at TIMESTAMPTZ
);
CREATE FUNCTION auth23_dispute_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable dispute record' USING ERRCODE='23514'; END IF;
 IF (NEW.dispute_id,NEW.order_id,NEW.account_id,NEW.lot_id,NEW.payment_id,NEW.spent_units,
     NEW.disputed_units,NEW.amount_minor,NEW.currency,NEW.wallet_was_locked,NEW.opened_reason,
     NEW.created_at) IS DISTINCT FROM
    (OLD.dispute_id,OLD.order_id,OLD.account_id,OLD.lot_id,OLD.payment_id,OLD.spent_units,
     OLD.disputed_units,OLD.amount_minor,OLD.currency,OLD.wallet_was_locked,OLD.opened_reason,
     OLD.created_at)
 OR (OLD.state='open' AND NEW.state NOT IN ('open','lost','won'))
 OR (OLD.state='lost' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.state='won' AND NEW.state IS DISTINCT FROM OLD.state)
 OR (OLD.resolved_at IS NOT NULL AND NEW.resolved_at IS DISTINCT FROM OLD.resolved_at)
 THEN RAISE EXCEPTION 'immutable dispute binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth23_dispute_guard BEFORE UPDATE OR DELETE ON auth_disputes FOR EACH ROW EXECUTE FUNCTION auth23_dispute_guard_fn();
