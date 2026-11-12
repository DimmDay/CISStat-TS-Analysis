"""Native PostgreSQL AUTH-25 reconciliation/restore/launch oracles.

Acceptance (spec_auth_architecture.md AUTH-25): crash/backup/provider replay
produce no duplicates; terms/catalog confirmed before real checkout. E6: a
restart/backup/reconcile never duplicates a top-up credit, settlement or
refund. Holds of pending refunds/disputes are legitimate states, never
findings. No simulated SQL, no real merchant/network (inherited AUTH-23
fixture with MockTransport)."""

import json
import os
import stat
import tempfile
import unittest
from uuid import UUID, uuid4

from apps.api.billing.reconciliation import (
    WATERMARK_FORMAT,
    FinancialReconciliationService,
)
from apps.api.billing.refund_contract import RefundRequest
from apps.api.billing.topup_contract import TopupOrder, TopupQuote
from apps.api.billing.wallet import _posting
from tests.integration import test_auth23_refunds as previous
from tests.integration.test_auth04_sessions import ORIGIN

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class ReconciliationSQLTests(previous.RefundSQLTests):
    """AUTH-23 fixture (wallet + topup + refund/dispute saga) + the
    reconciliation service under test."""

    def setUp(self):
        super().setUp()
        self.rec = FinancialReconciliationService(self.store, clock=lambda: self.now)

    def report(self):
        return self.rec.report()

    def blocking(self, rep, code):
        return [f for f in rep["findings"] if f["code"] == code]

    def orphan_credit(self, account_id=None, *, ref=None):
        """DBA/restore-artifact simulation: a purchased lot whose origin_order
        is not a credited order (insert starts balanced, as 0033 requires)."""
        aid = UUID(str(account_id or self.account.account_id))
        with self.store.transaction() as tx:
            w = tx.connection.execute(
                "SELECT wallet_id FROM auth_wallets WHERE account_id=%s", (aid,)
            ).fetchone()
            lot_id = uuid4()
            tx.connection.execute(
                "INSERT INTO auth_wallet_lots(lot_id,wallet_id,account_id,source,issued,"
                "available,expires_at,origin_order,version,created_at) "
                "VALUES (%s,%s,%s,'purchased',1000,1000,NULL,%s,1,%s)",
                (
                    lot_id,
                    w["wallet_id"],
                    aid,
                    ref or ("orphan-" + uuid4().hex[:16]),
                    self.now,
                ),
            )
            return lot_id

    def credit_order_without_lot(self):
        """Pending quote/order flipped to credited by hand: no lot exists."""
        q = self.topups.quote(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package)),
        )
        o = self.topups.confirm(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(
                TopupOrder, quote_id=UUID(q["quote_id"]), quote_digest=q["digest"]
            ),
        )
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_topup_orders SET state='credited',credited_at=%s "
                "WHERE order_id=%s",
                (self.now, UUID(o["order_id"])),
            )
        return o

    def refund_refunded(self):
        """Honest saga path down to a provider-confirmed refund (AUTH-23)."""
        o = self.credited_order()
        r = self.request_refund(o)
        self.assertTrue(self.refunds.step())  # create refund (Idempotence-Key)
        self.refund_status = "succeeded"
        self.due(minutes=2)
        self.assertTrue(self.refunds.step())  # GET-confirmed proof -> refunded
        row = self.refund_row(r["refund_id"])
        self.assertEqual(row["state"], "refunded")
        return o, r

    def revert_lot_buckets(self, lot_id, *, units):
        """Restore-artifact simulation through the sanctioned adjust posting:
        refunded CU return to available while the refund row stays terminal."""
        with self.store.transaction() as tx:
            _posting(
                tx.connection,
                lot_id,
                "adjust",
                available_delta=units,
                refunded_delta=-units,
            )

    def other_wallet(self):
        """A second personal account wallet that must never be flagged."""
        self.wallet.create_wallet(self.other_account.account_id, reason="native AUTH25 second wallet")
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT wallet_id, status FROM auth_wallets WHERE account_id=%s",
                (self.other_account.account_id,),
            ).fetchone()

    def wallet_status(self, account_id):
        with self.store.transaction(readonly=True) as tx:
            row = tx.connection.execute(
                "SELECT status FROM auth_wallets WHERE account_id=%s",
                (UUID(str(account_id)),),
            ).fetchone()
            return row["status"] if row else None


class CleanAndLegitimateStates(ReconciliationSQLTests):
    def test_honest_saga_reports_clean(self):
        self.credited_order()
        rep = self.report()
        self.assertTrue(rep["ok"], rep["findings"])
        self.assertEqual(rep["accounts_with_blockers"], [])
        self.assertEqual(rep["counts"]["blocking"], 0)

    def test_pending_refund_hold_is_not_a_finding(self):
        o = self.credited_order()
        self.request_refund(o)
        rep = self.report()
        self.assertTrue(rep["ok"], rep["findings"])

    def test_open_dispute_lock_is_not_a_finding(self):
        o = self.credited_order()
        self.spend_part(30_000_000, 30_000_000)
        self.refunds.dispute_open(o["order_id"], reason="native AUTH25 chargeback")
        rep = self.report()
        self.assertTrue(rep["ok"], rep["findings"])

    def test_paid_review_is_info_not_blocking(self):
        self.credited_order()
        # A second order parked in paid_review (money captured, credit held):
        q = self.topups.quote(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package)),
        )
        o2 = self.topups.confirm(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(TopupOrder, quote_id=UUID(q["quote_id"]), quote_digest=q["digest"]),
        )
        row = self.wallet_row()
        self.wallet.set_status(
            row["wallet_id"],
            expected_version=row["version"],
            status="locked",
            reason="native AUTH25 paid_review hold",
        )
        # The mock echoes one payment id per test; the credited order already
        # bound it, so the second saga must carry a fresh provider payment id.
        self.payment_id = "payment-25"
        self.status = "succeeded"
        self.assertTrue(self.topups.step())
        self.assertEqual(self.order_row(o2["order_id"])["state"], "paid_review")
        row = self.wallet_row()
        self.wallet.set_status(
            row["wallet_id"],
            expected_version=row["version"],
            status="active",
            reason="native AUTH25 unlock",
        )
        rep = self.report()
        self.assertTrue(rep["ok"], rep["findings"])
        self.assertTrue(
            any(f["code"] == "paid_review_open" for f in rep["findings"]),
            rep["findings"],
        )


class DuplicatePrevention(ReconciliationSQLTests):
    def test_provider_replay_cannot_bind_one_payment_twice(self):
        o = self.credited_order()
        q = self.topups.quote(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package)),
        )
        o2 = self.topups.confirm(
            self.token, ORIGIN, self.account.account_id,
            self.tbody(TopupOrder, quote_id=UUID(q["quote_id"]), quote_digest=q["digest"]),
        )
        with self.assertRaises(Exception) as ctx:
            with self.store.transaction() as tx:
                tx.connection.execute(
                    "UPDATE auth_topup_orders SET payment_id=%s WHERE order_id=%s",
                    (self.payment_id, UUID(o2["order_id"])),
                )
        self.assertIn("constraint", str(ctx.exception).lower())

    def test_saga_restart_after_credit_does_not_duplicate_lot(self):
        o = self.credited_order()
        self.assertFalse(self.topups.step())
        with self.store.transaction(readonly=True) as tx:
            n = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_wallet_lots WHERE account_id=%s "
                "AND source='purchased' AND origin_order=%s",
                (self.account.account_id, str(o["order_id"])),
            ).fetchone()["n"]
        self.assertEqual(n, 1)
        rep = self.report()
        self.assertTrue(rep["ok"], rep["findings"])

    def test_report_flags_credit_order_mismatch(self):
        self.credited_order()
        self.credit_order_without_lot()
        rep = self.report()
        self.assertFalse(rep["ok"])
        self.assertEqual(len(self.blocking(rep, "credit_order_mismatch")), 1)
        self.assertIn(str(self.account.account_id), rep["accounts_with_blockers"])

    def test_report_flags_orphan_credit(self):
        self.credited_order()
        self.orphan_credit()
        rep = self.report()
        self.assertFalse(rep["ok"])
        self.assertEqual(len(self.blocking(rep, "credit_order_mismatch")), 1)


class RestoreArtifacts(ReconciliationSQLTests):
    def test_refund_terminal_state_vs_buckets_regression(self):
        o, r = self.refund_refunded()
        lot = self.lot()
        self.revert_lot_buckets(lot["lot_id"], units=int(r["units"]))
        rep = self.report()
        self.assertFalse(rep["ok"])
        found = self.blocking(rep, "refund_state_mismatch")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["subject"], str(r["refund_id"]))

    def test_dispute_open_requires_locked_wallet(self):
        o = self.credited_order()
        self.spend_part(30_000_000, 30_000_000)
        d = self.refunds.dispute_open(o["order_id"], reason="native AUTH25 chargeback")
        row = self.wallet_row()
        self.wallet.set_status(
            row["wallet_id"],
            expected_version=row["version"],
            status="active",
            reason="native AUTH25 manual unlock",
        )
        rep = self.report()
        self.assertFalse(rep["ok"])
        self.assertEqual(len(self.blocking(rep, "dispute_state_mismatch")), 1)

    def test_projection_drift_detected_on_guard_disabled_artifact(self):
        """A DBA/restore artifact that bypasses the lot guard (trigger
        disabled) moves buckets without postings. The realistic artifact is
        a phantom expiry: available fans out to expired with no postings.
        The bucket-vs-issued CHECK still holds (the sum does not change), so
        exactly the projection drift is reported."""
        self.credited_order()
        lot = self.lot()
        with self.raw() as conn:
            conn.autocommit = True
            conn.execute(
                "ALTER TABLE auth_wallet_lots DISABLE TRIGGER auth21_lot_guard"
            )
            try:
                conn.execute(
                    "UPDATE auth_wallet_lots SET available=available-500,"
                    "expired=expired+500 WHERE lot_id=%s",
                    (lot["lot_id"],),
                )
            finally:
                conn.execute(
                    "ALTER TABLE auth_wallet_lots ENABLE TRIGGER auth21_lot_guard"
                )
        rep = self.report()
        self.assertFalse(rep["ok"])
        self.assertEqual(len(self.blocking(rep, "lot_projection_drift")), 1)
        self.assertEqual(len(self.blocking(rep, "lot_balance_violation")), 0)


class WatermarkRestore(ReconciliationSQLTests):
    def test_export_atomic_0600_and_typed(self):
        self.credited_order()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watermark.json")
            out = self.rec.export_watermark(path)
            self.assertEqual(out["format"], WATERMARK_FORMAT)
            self.assertGreaterEqual(out["entries"], 1)
            st = os.stat(path)
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
            doc = json.loads(open(path, encoding="utf-8").read())
            self.assertEqual(doc["format"], WATERMARK_FORMAT)
            kinds = {e["kind"] for e in doc["entries"]}
            self.assertIn("order", kinds)

    def test_reconcile_watermark_finds_regression_without_repair(self):
        o, r = self.refund_refunded()
        lot = self.lot()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watermark.json")
            self.rec.export_watermark(path)
            # A backup restore reverted the lot buckets; the refund row and
            # the watermark survived outside pgdata.
            self.revert_lot_buckets(lot["lot_id"], units=int(r["units"]))
            doc = json.loads(open(path, encoding="utf-8").read())
            before = self.lot()
            out = self.rec.reconcile_watermark(doc, reason="restore drill")
            self.assertFalse(out["ok"])
            self.assertEqual(
                [g["kind"] for g in out["regressions"]], ["refund"]
            )
            self.assertEqual(out["regressions"][0]["id"], str(r["refund_id"]))
            self.assertTrue(
                any("manage_refunds" in s for s in out["suggestions"][str(r["refund_id"])])
            )
            # No money moved: the operator decides with trusted commands.
            after = self.lot()
            self.assertEqual(int(after["available"]), int(before["available"]))
            self.assertEqual(int(after["refunded"]), int(before["refunded"]))
            # Idempotent second run: same facts, no new artifacts.
            again = self.rec.reconcile_watermark(doc, reason="restore drill 2")
            self.assertEqual(again["regressions"], out["regressions"])

    def test_reconcile_watermark_clean_passes(self):
        self.credited_order()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watermark.json")
            self.rec.export_watermark(path)
            doc = json.loads(open(path, encoding="utf-8").read())
            out = self.rec.reconcile_watermark(doc, reason="restore drill")
            self.assertTrue(out["ok"])
            self.assertEqual(out["regressions"], [])

    def test_reconcile_watermark_audits_the_run(self):
        self.credited_order()
        with self.store.transaction(readonly=True) as tx:
            before = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_audit_outbox"
            ).fetchone()["n"]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watermark.json")
            self.rec.export_watermark(path)
            doc = json.loads(open(path, encoding="utf-8").read())
            self.rec.reconcile_watermark(doc, reason="restore drill")
        with self.store.transaction(readonly=True) as tx:
            after = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_audit_outbox"
            ).fetchone()["n"]
        self.assertGreater(after, before)


class Quarantine(ReconciliationSQLTests):
    def test_lock_flagged_locks_only_offenders(self):
        self.other_wallet()
        self.orphan_credit()
        out = self.rec.lock_flagged(reason="uncertain restore state")
        self.assertEqual(len(out["locked"]), 1)
        self.assertIn(str(self.account.account_id), [w["account_id"] for w in out["locked"]])
        row = self.wallet_row()
        self.assertEqual(row["status"], "locked")
        self.assertEqual(self.wallet_status(self.other_account.account_id), "active")
        # The prefixed reason carries the task marker and stays bounded.
        with self.store.transaction(readonly=True) as tx:
            reason = tx.connection.execute(
                "SELECT locked_reason FROM auth_wallets WHERE account_id=%s",
                (self.account.account_id,),
            ).fetchone()["locked_reason"]
        self.assertIn("auth25", reason)
        self.assertIn("uncertain restore state", reason)
        self.assertLessEqual(len(reason), 256)

    def test_lock_flagged_clean_report_locks_nothing(self):
        self.other_wallet()
        self.credited_order()
        out = self.rec.lock_flagged(reason="no doubts")
        self.assertEqual(out["locked"], [])
        self.assertEqual(self.wallet_row()["status"], "active")
        self.assertEqual(self.wallet_status(self.other_account.account_id), "active")


class LaunchGate(ReconciliationSQLTests):
    SANDBOX = {"CISSTAT_YOOKASSA_ENABLED": "test"}

    def test_launch_check_ok_with_catalog_and_sandbox(self):
        verdict = self.rec.launch_check(environ=self.SANDBOX)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        names = {c["name"] for c in verdict["checks"]}
        self.assertEqual(
            names,
            {
                "schema_ready",
                "catalog_valid",
                "refund_window",
                "provider_mode",
                "reconciliation_clean",
                "audit_delivery",
            },
        )

    def test_empty_catalog_blocks_and_warns_with_allow(self):
        self.topups.disable_package(self.package, reason="native AUTH25 close")
        verdict = self.rec.launch_check(environ=self.SANDBOX)
        self.assertFalse(verdict["ok"])
        verdict = self.rec.launch_check(environ=self.SANDBOX, allow_empty_catalog=True)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        row = [c for c in verdict["checks"] if c["name"] == "catalog_valid"][0]
        self.assertEqual(row["status"], "warn")

    def test_blocker_and_live_env_block_the_gate(self):
        self.orphan_credit()
        verdict = self.rec.launch_check(environ=self.SANDBOX)
        self.assertFalse(verdict["ok"])
        verdict = self.rec.launch_check(
            environ={"CISSTAT_YOOKASSA_ENABLED": "live"}, allow_empty_catalog=True
        )
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("provider_mode" in r for r in verdict["reasons"]))

    def test_report_shape_is_json_safe(self):
        self.credited_order()
        rep = self.report()
        self.assertIn("generated_at", rep)
        self.assertIn("checked", rep)
        json.dumps(rep, default=str)


if __name__ == "__main__":
    unittest.main()
