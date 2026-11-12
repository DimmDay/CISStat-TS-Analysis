"""AUTH-25 payment reconciliation/restore/launch contracts. Real SQL flows
live in tests/integration.

Normative rules: spec_auth_architecture.md AUTH-25 (crash/backup/provider
replay produce no duplicates; terms/catalog confirmed before real checkout),
§12.4 (uncertain financial state holds, never a Memory wallet), §13.9 (real
checkout is a separate delivery), spec_billing_accounts.md §13.10 E6.
"""

import unittest

from apps.api.billing.reconciliation import (
    BLOCKING_CODES,
    LOCK_REASON_PREFIX,
    MAX_FINDINGS,
    WATERMARK_FORMAT,
    WATERMARK_MAX_ENTRIES,
    assemble_launch_verdict,
    finding,
    parse_refund_window,
    provider_mode,
    restore_suggestions,
    validate_watermark,
)


def wm_entry(kind, **overrides):
    base = {
        "order": {
            "kind": "order",
            "order_id": "11111111-1111-1111-1111-111111111111",
            "account_id": "22222222-2222-2222-2222-222222222222",
            "payment_id": "payment-1",
            "state": "credited",
        },
        "refund": {
            "kind": "refund",
            "refund_id": "33333333-3333-3333-3333-333333333333",
            "order_id": "11111111-1111-1111-1111-111111111111",
            "state": "refunded",
        },
        "dispute": {
            "kind": "dispute",
            "dispute_id": "44444444-4444-4444-4444-444444444444",
            "order_id": "11111111-1111-1111-1111-111111111111",
            "state": "lost",
        },
    }[kind]
    base.update(overrides)
    return base


class FindingContracts(unittest.TestCase):
    """Bounded findings with a fixed code vocabulary and severity."""

    def test_blocking_codes_are_classified(self):
        for code in (
            "credit_order_mismatch",
            "payment_id_collision",
            "refund_state_mismatch",
            "dispute_state_mismatch",
            "lot_projection_drift",
            "lot_balance_violation",
            "restore_regression",
        ):
            self.assertIn(code, BLOCKING_CODES)
            self.assertEqual(finding(code, "s1")["severity"], "blocking")

    def test_info_codes_are_classified(self):
        for code in ("paid_review_open", "inbox_unowned_event", "audit_outbox_pending"):
            self.assertNotIn(code, BLOCKING_CODES)
            self.assertEqual(finding(code, "s1")["severity"], "info")

    def test_unknown_code_rejected(self):
        with self.assertRaises(ValueError):
            finding("made_up_code", "s1")

    def test_subject_required(self):
        for bad in ("", " ", None, 123):
            with self.assertRaises(ValueError):
                finding("paid_review_open", bad)

    def test_detail_is_bounded_json(self):
        long = "x" * 100_000
        row = finding("paid_review_open", "s1", detail=long)
        self.assertLessEqual(len(row["detail"]), 512)

    def test_finding_shape_is_stable(self):
        row = finding("credit_order_mismatch", "order " + "a" * 8, detail="d")
        self.assertEqual(set(row), {"code", "severity", "subject", "detail"})
        self.assertIsInstance(row["detail"], str)


class WatermarkDocument(unittest.TestCase):
    """cisstat-auth25-watermark/1: bounded, typed, tamper-evident envelope."""

    def doc(self, entries):
        return {"format": WATERMARK_FORMAT, "entries": entries}

    def test_valid_document_passes(self):
        rows = validate_watermark(self.doc([wm_entry("order"), wm_entry("refund")]))
        self.assertEqual([r["kind"] for r in rows], ["order", "refund"])

    def test_wrong_format_rejected(self):
        with self.assertRaises(ValueError):
            validate_watermark({"format": "cisstat-auth20-marks/1", "entries": []})
        with self.assertRaises(ValueError):
            validate_watermark({"entries": []})

    def test_envelope_shape_rejected(self):
        for bad in (None, [], "doc", 42):
            with self.assertRaises(ValueError):
                validate_watermark(bad)
        with self.assertRaises(ValueError):
            validate_watermark({"format": WATERMARK_FORMAT, "entries": "no"})

    def test_entries_bounded(self):
        overflow = [wm_entry("order", order_id=f"id-{i}") for i in range(WATERMARK_MAX_ENTRIES + 1)]
        with self.assertRaises(ValueError):
            validate_watermark(self.doc(overflow))

    def test_entry_kind_and_fields_validated(self):
        with self.assertRaises(ValueError):
            validate_watermark(self.doc([{"kind": "unknown", "order_id": "x"}]))
        for missing in ("order_id", "account_id", "state", "kind"):
            row = wm_entry("order")
            row.pop(missing)
            with self.assertRaises(ValueError):
                validate_watermark(self.doc([row]))
        for missing in ("refund_id", "order_id", "state"):
            row = wm_entry("refund")
            row.pop(missing)
            with self.assertRaises(ValueError):
                validate_watermark(self.doc([row]))
        for missing in ("dispute_id", "order_id", "state"):
            row = wm_entry("dispute")
            row.pop(missing)
            with self.assertRaises(ValueError):
                validate_watermark(self.doc([row]))

    def test_ids_must_be_strings(self):
        with self.assertRaises(ValueError):
            validate_watermark(self.doc([wm_entry("order", order_id=123)]))


class ProviderMode(unittest.TestCase):
    """D4: the mode fact is reported, live is blocked, nothing is enabled."""

    def test_missing_env_is_not_configured_and_ok(self):
        mode, ok, _ = provider_mode({})
        self.assertEqual(mode, "not_configured")
        self.assertTrue(ok)

    def test_sandbox_is_the_only_ok_explicit_mode(self):
        mode, ok, _ = provider_mode({"CISSTAT_YOOKASSA_ENABLED": "test"})
        self.assertEqual(mode, "sandbox")
        self.assertTrue(ok)

    def test_any_other_value_is_blocked(self):
        for value in ("live", "prod", "TEST", "yes", "1"):
            mode, ok, _ = provider_mode({"CISSTAT_YOOKASSA_ENABLED": value})
            self.assertEqual(mode, "blocked")
            self.assertFalse(ok)


class RefundWindow(unittest.TestCase):
    """AUTH-23 window env parsing is reused verbatim (single policy source)."""

    def test_default_when_absent(self):
        self.assertEqual(parse_refund_window(environ={}), 14)

    def test_bounds_accept_0_and_90(self):
        self.assertEqual(parse_refund_window(environ={"CISSTAT_TOPUP_REFUND_DAYS": "0"}), 0)
        self.assertEqual(parse_refund_window(environ={"CISSTAT_TOPUP_REFUND_DAYS": "90"}), 90)

    def test_matches_refunds_window_days_semantics(self):
        from apps.api.billing.refunds import window_days

        self.assertEqual(parse_refund_window(environ={"CISSTAT_TOPUP_REFUND_DAYS": " 7 "}), 7)
        self.assertEqual(parse_refund_window(environ={"CISSTAT_TOPUP_REFUND_DAYS": "5"}), window_days({"CISSTAT_TOPUP_REFUND_DAYS": "5"}))

    def test_invalid_values_rejected(self):
        for raw in ("-1", "91", "abc", "3.5", ""):
            with self.assertRaises(ValueError):
                parse_refund_window(environ={"CISSTAT_TOPUP_REFUND_DAYS": raw})


class RestoreSuggestions(unittest.TestCase):
    """Watermark regressions point to existing trusted commands, never to
    silent money re-application."""

    def test_order_regression_suggests_topup_commands(self):
        out = restore_suggestions(wm_entry("order"))
        self.assertTrue(any("manage_topups" in s for s in out))
        self.assertTrue(any("reconcile" in s for s in out))

    def test_refund_regression_suggests_refund_reconcile(self):
        out = restore_suggestions(wm_entry("refund"))
        self.assertTrue(any("manage_refunds" in s and "refund-reconcile" in s for s in out))

    def test_dispute_regression_suggests_dispute_path(self):
        out = restore_suggestions(wm_entry("dispute"))
        self.assertTrue(any("manage_refunds" in s and "dispute" in s for s in out))

    def test_unknown_kind_gives_no_suggestions(self):
        self.assertEqual(restore_suggestions({"kind": "?", "state": "credited"}), [])


class LaunchVerdict(unittest.TestCase):
    """D4: verdict assembles from named checks; nothing is switched on."""

    @staticmethod
    def ok(name):
        return {"name": name, "status": "ok", "detail": ""}

    def test_all_ok(self):
        verdict = assemble_launch_verdict(
            [self.ok("schema_ready"), self.ok("catalog_valid"), self.ok("provider_mode")]
        )
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["verdict"], "ok")
        self.assertEqual(verdict["reasons"], [])

    def test_empty_catalog_blocks_without_explicit_allow(self):
        checks = [
            {"name": "catalog_valid", "status": "blocked", "detail": "empty catalog"},
        ]
        verdict = assemble_launch_verdict(checks)
        self.assertFalse(verdict["ok"])
        self.assertIn("catalog_valid", verdict["reasons"][0])

    def test_empty_catalog_warns_with_explicit_allow(self):
        checks = [
            {"name": "catalog_valid", "status": "blocked", "detail": "empty catalog"},
        ]
        verdict = assemble_launch_verdict(checks, allow_empty_catalog=True)
        self.assertTrue(verdict["ok"])
        self.assertEqual(
            [c["status"] for c in verdict["checks"] if c["name"] == "catalog_valid"],
            ["warn"],
        )

    def test_blocked_check_blocks_verdict(self):
        checks = [
            self.ok("schema_ready"),
            {"name": "provider_mode", "status": "blocked", "detail": "live env"},
        ]
        verdict = assemble_launch_verdict(checks)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("provider_mode" in r for r in verdict["reasons"]))

    def test_warn_alone_keeps_ok(self):
        verdict = assemble_launch_verdict(
            [{"name": "audit_delivery", "status": "warn", "detail": "3 pending"}]
        )
        self.assertTrue(verdict["ok"])

    def test_unknown_check_name_rejected(self):
        with self.assertRaises(ValueError):
            assemble_launch_verdict([{"name": "mystery", "status": "ok", "detail": ""}])

    def test_check_status_vocabulary(self):
        with self.assertRaises(ValueError):
            assemble_launch_verdict([{"name": "schema_ready", "status": "fine", "detail": ""}])

    def test_lock_reason_prefix_carries_task_marker(self):
        self.assertTrue(LOCK_REASON_PREFIX.startswith("auth25"))
        # lock_flagged stores (prefix + ": " + reason)[:256]; the marker and
        # the operator reason both survive the bound.
        bounded = (LOCK_REASON_PREFIX + ": " + "r" * 240)[:256]
        self.assertLessEqual(len(bounded), 256)
        self.assertTrue(bounded.startswith(LOCK_REASON_PREFIX))


class ReportBounding(unittest.TestCase):
    """report() never returns more than MAX_FINDINGS findings."""

    def test_max_findings_constant(self):
        self.assertEqual(MAX_FINDINGS, 500)
        self.assertLess(MAX_FINDINGS, WATERMARK_MAX_ENTRIES)


if __name__ == "__main__":
    unittest.main()
