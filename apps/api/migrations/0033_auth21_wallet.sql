-- AUTH-21 additive source-aware wallet. No pricing, no payments, no auto-credit:
-- lots exist only where a trusted operator command issued them (design D1/D8).
CREATE TABLE auth_wallets (
 wallet_id UUID PRIMARY KEY,
 account_id UUID NOT NULL UNIQUE REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','locked')),
 locked_reason TEXT CHECK(locked_reason IS NULL OR length(locked_reason)<=256),
 version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
 created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE auth_wallet_lots (
 lot_id UUID PRIMARY KEY,
 wallet_id UUID NOT NULL REFERENCES auth_wallets(wallet_id) ON DELETE RESTRICT,
 account_id UUID NOT NULL REFERENCES auth_accounts(account_id) ON DELETE RESTRICT,
 source TEXT NOT NULL CHECK(source IN ('included','purchased','promotional')),
 issued BIGINT NOT NULL CHECK(issued>0),
 available BIGINT NOT NULL CHECK(available>=0),
 reserved BIGINT NOT NULL DEFAULT 0 CHECK(reserved>=0),
 spent BIGINT NOT NULL DEFAULT 0 CHECK(spent>=0),
 expired BIGINT NOT NULL DEFAULT 0 CHECK(expired>=0),
 refund_pending BIGINT NOT NULL DEFAULT 0 CHECK(refund_pending>=0),
 refunded BIGINT NOT NULL DEFAULT 0 CHECK(refunded>=0),
 expires_at TIMESTAMPTZ,
 origin_cycle UUID REFERENCES auth_billing_cycles(cycle_id) ON DELETE RESTRICT,
 origin_order TEXT CHECK(origin_order IS NULL OR length(origin_order) BETWEEN 1 AND 128),
 origin_ref TEXT CHECK(origin_ref IS NULL OR length(origin_ref) BETWEEN 1 AND 256),
 version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
 created_at TIMESTAMPTZ NOT NULL,
 CHECK(source<>'included' OR expires_at IS NOT NULL),
 CHECK(source<>'purchased' OR expires_at IS NULL),
 CHECK(available::numeric+reserved::numeric+spent::numeric+expired::numeric+refund_pending::numeric+refunded::numeric=issued::numeric)
);
-- Unique credit per explicit basis: one purchased credit per order (E3/E6),
-- one issuance per (cycle, basis): ref='base' or ref='proration:<order>'.
CREATE UNIQUE INDEX auth21_lot_order ON auth_wallet_lots(account_id,origin_order) WHERE origin_order IS NOT NULL;
CREATE UNIQUE INDEX auth21_lot_cycle ON auth_wallet_lots(account_id,origin_cycle,origin_ref) WHERE origin_cycle IS NOT NULL;
-- FEFO physical order (design D3): dying first, then endless, then source rank, then stable id.
CREATE INDEX auth21_wallet_fefo ON auth_wallet_lots(wallet_id,(expires_at IS NULL),expires_at,
 (CASE source WHEN 'included' THEN 0 WHEN 'promotional' THEN 1 ELSE 2 END),lot_id)
 WHERE available>0;
CREATE TABLE auth_wallet_postings (
 posting_id UUID PRIMARY KEY,
 lot_id UUID NOT NULL REFERENCES auth_wallet_lots(lot_id) ON DELETE RESTRICT,
 reservation_id UUID REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 event TEXT NOT NULL CHECK(event IN ('reserve','settle','release','expire','refund_hold','refund_confirmed','refund_failed','adjust')),
 issued_delta BIGINT NOT NULL DEFAULT 0 CHECK(issued_delta=0),
 available_delta BIGINT NOT NULL DEFAULT 0,
 reserved_delta BIGINT NOT NULL DEFAULT 0,
 spent_delta BIGINT NOT NULL DEFAULT 0,
 expired_delta BIGINT NOT NULL DEFAULT 0,
 refund_pending_delta BIGINT NOT NULL DEFAULT 0,
 refunded_delta BIGINT NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL,
 CHECK(available_delta::numeric+reserved_delta::numeric+spent_delta::numeric+expired_delta::numeric+refund_pending_delta::numeric+refunded_delta::numeric=0),
 CHECK(available_delta<>0 OR reserved_delta<>0 OR spent_delta<>0 OR expired_delta<>0 OR refund_pending_delta<>0 OR refunded_delta<>0),
 CHECK(reservation_id IS NOT NULL OR event NOT IN ('reserve','settle','release')),
 -- Exactly one source bucket -> one target bucket per event (design D16).
 CHECK((event='reserve' AND available_delta<0 AND reserved_delta=-available_delta AND spent_delta=0 AND expired_delta=0 AND refund_pending_delta=0 AND refunded_delta=0)
   OR (event='settle' AND reserved_delta<0 AND spent_delta=-reserved_delta AND available_delta=0 AND expired_delta=0 AND refund_pending_delta=0 AND refunded_delta=0)
   OR (event='release' AND reserved_delta<0 AND ((available_delta=-reserved_delta AND expired_delta=0) OR (expired_delta=-reserved_delta AND available_delta=0)) AND spent_delta=0 AND refund_pending_delta=0 AND refunded_delta=0)
   OR (event='expire' AND available_delta<0 AND expired_delta=-available_delta AND reserved_delta=0 AND spent_delta=0 AND refund_pending_delta=0 AND refunded_delta=0)
   OR (event='refund_hold' AND available_delta<0 AND refund_pending_delta=-available_delta AND reserved_delta=0 AND spent_delta=0 AND expired_delta=0 AND refunded_delta=0)
   OR (event='refund_confirmed' AND refund_pending_delta<0 AND refunded_delta=-refund_pending_delta AND available_delta=0 AND reserved_delta=0 AND spent_delta=0 AND expired_delta=0)
   OR (event='refund_failed' AND refund_pending_delta<0 AND available_delta=-refund_pending_delta AND reserved_delta=0 AND spent_delta=0 AND expired_delta=0 AND refunded_delta=0)
   OR event='adjust')
);
CREATE TABLE auth_reservation_lot_allocations (
 reservation_id UUID NOT NULL REFERENCES auth_reservations(reservation_id) ON DELETE RESTRICT,
 lot_id UUID NOT NULL REFERENCES auth_wallet_lots(lot_id) ON DELETE RESTRICT,
 units BIGINT NOT NULL CHECK(units>0),
 PRIMARY KEY(reservation_id,lot_id)
);
CREATE INDEX auth21_lot_alloc ON auth_reservation_lot_allocations(lot_id);
CREATE FUNCTION auth21_wallet_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'wallet retained' USING ERRCODE='23514'; END IF;
 IF (NEW.wallet_id,NEW.account_id) IS DISTINCT FROM (OLD.wallet_id,OLD.account_id)
    OR NEW.version<>OLD.version+1 THEN RAISE EXCEPTION 'immutable wallet binding/CAS' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth21_wallet_guard BEFORE UPDATE OR DELETE ON auth_wallets FOR EACH ROW EXECUTE FUNCTION auth21_wallet_guard();
CREATE FUNCTION auth21_lot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'lot retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.version<>1 OR NEW.available<>NEW.issued OR NEW.reserved<>0 OR NEW.spent<>0 OR NEW.expired<>0 OR NEW.refund_pending<>0 OR NEW.refunded<>0 THEN
   RAISE EXCEPTION 'lot starts from a balanced issue' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.lot_id,NEW.wallet_id,NEW.account_id,NEW.source,NEW.issued,NEW.expires_at,NEW.origin_cycle,NEW.origin_order,NEW.origin_ref) IS DISTINCT FROM
    (OLD.lot_id,OLD.wallet_id,OLD.account_id,OLD.source,OLD.issued,OLD.expires_at,OLD.origin_cycle,OLD.origin_order,OLD.origin_ref)
    OR NEW.version<>OLD.version+1
    OR ((NEW.available,NEW.reserved,NEW.spent,NEW.expired,NEW.refund_pending,NEW.refunded) IS DISTINCT FROM
        (OLD.available,OLD.reserved,OLD.spent,OLD.expired,OLD.refund_pending,OLD.refunded) AND pg_trigger_depth()<2) THEN
  RAISE EXCEPTION 'immutable lot binding/projection' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth21_lot_guard BEFORE INSERT OR UPDATE OR DELETE ON auth_wallet_lots FOR EACH ROW EXECUTE FUNCTION auth21_lot_guard();
CREATE FUNCTION auth21_posting_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'immutable wallet history' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth21_posting_guard BEFORE UPDATE OR DELETE ON auth_wallet_postings FOR EACH ROW EXECUTE FUNCTION auth21_posting_guard();
-- Projection is advanced ONLY by append-only postings, in O(1), never a rescan.
CREATE FUNCTION auth21_lot_projection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE auth_wallet_lots SET
  available=available+NEW.available_delta,reserved=reserved+NEW.reserved_delta,
  spent=spent+NEW.spent_delta,expired=expired+NEW.expired_delta,
  refund_pending=refund_pending+NEW.refund_pending_delta,refunded=refunded+NEW.refunded_delta,
  version=version+1
 WHERE lot_id=NEW.lot_id;
 RETURN NULL;
END $$;
CREATE TRIGGER auth21_posting_projection AFTER INSERT ON auth_wallet_postings FOR EACH ROW EXECUTE FUNCTION auth21_lot_projection();
CREATE FUNCTION auth21_lot_allocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR NEW.reservation_id<>OLD.reservation_id OR NEW.lot_id<>OLD.lot_id OR NEW.units<=OLD.units THEN
  RAISE EXCEPTION 'immutable lot allocation' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth21_lot_allocation_guard BEFORE UPDATE OR DELETE ON auth_reservation_lot_allocations FOR EACH ROW EXECUTE FUNCTION auth21_lot_allocation_guard();
