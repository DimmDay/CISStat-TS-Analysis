"""AUTH-13 worker-credential bootstrap: unit-контракт без БД (OPS-DIAG-1).

Дефект: compose прокидывает CISSTAT_WORKER_KEY (по умолчанию пуст), но
строка в auth_worker_services никогда не создаётся -- verify() отвечает
503 worker_service_unavailable на каждом цикле document_render_worker и
на каждом admit(). Проверяются: формат ключа, разрешение ключа из env,
короткие замыкания без БД (disabled/missing/invalid), чистое отображение
строки в состояние, отсутствие утечек секрета/дайджеста в результате,
startup_check (никогда не бросает) и legibility ошибок воркера
(last_error_code + дедупликация warning-лога одинаковых повторов).
"""

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.workers import bootstrap
from apps.api.workers.services import KEY


class GenerateKeyTests(unittest.TestCase):
    def test_generated_key_matches_services_format(self):
        for _ in range(20):
            self.assertRegex(bootstrap.generate_key(), KEY)

    def test_generated_keys_are_unique(self):
        self.assertEqual(len({bootstrap.generate_key() for _ in range(50)}), 50)


class ResolveKeyTests(unittest.TestCase):
    def test_explicit_key_wins_over_env(self):
        env_key, explicit = bootstrap.generate_key(), bootstrap.generate_key()
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: env_key}):
            self.assertEqual(bootstrap._resolve_key(explicit), explicit)

    def test_env_value_is_stripped(self):
        key = bootstrap.generate_key()
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: "  " + key + "\t"}):
            self.assertEqual(bootstrap._resolve_key(None), key)

    def test_empty_env_resolves_to_empty(self):
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: "   "}):
            self.assertEqual(bootstrap._resolve_key(None), "")


class EnsureShortCircuitTests(unittest.TestCase):
    """Ветви без БД: ни один из них не создаёт store-подключений."""

    def test_disabled_when_auth13_context_off_and_store_not_given(self):
        with patch.dict(
            os.environ, {bootstrap.ENV_WORKER_KEY: bootstrap.generate_key()}
        ):
            with patch("apps.api.workers.bridge.enabled", return_value=False):
                out = bootstrap.ensure_service_credential()
        self.assertEqual(out["state"], "disabled")
        self.assertTrue(out["key_configured"])

    def test_missing_when_env_key_empty(self):
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: ""}):
            with patch("apps.api.workers.bridge.enabled", return_value=True):
                with patch(
                    "apps.api.authentication.storage.PostgresAccessStore.from_env",
                    side_effect=AssertionError("store must not be touched"),
                ):
                    out = bootstrap.ensure_service_credential()
        self.assertEqual(out["state"], "missing")
        self.assertFalse(out["key_configured"])
        self.assertIn("manage_workers.py", out["remediation"])

    def test_invalid_when_key_format_wrong(self):
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: "cwk_too_short"}):
            with patch("apps.api.workers.bridge.enabled", return_value=True):
                with patch(
                    "apps.api.authentication.storage.PostgresAccessStore.from_env",
                    side_effect=AssertionError("store must not be touched"),
                ):
                    out = bootstrap.ensure_service_credential()
        self.assertEqual(out["state"], "invalid")
        self.assertTrue(out["key_configured"])
        self.assertIn("cwk_", out["remediation"])


class EvaluateTests(unittest.TestCase):
    NOW = datetime.now(UTC)

    def test_absent_row(self):
        self.assertEqual(bootstrap._evaluate(None, self.NOW), "absent")

    def test_revoked_wins_over_expiry(self):
        row = {
            "revoked_at": self.NOW - timedelta(days=1),
            "expires_at": self.NOW + timedelta(days=1),
        }
        self.assertEqual(bootstrap._evaluate(row, self.NOW), "revoked")

    def test_expired_including_boundary(self):
        self.assertEqual(
            bootstrap._evaluate(
                {"revoked_at": None, "expires_at": self.NOW}, self.NOW
            ),
            "expired",
        )

    def test_present(self):
        self.assertEqual(
            bootstrap._evaluate(
                {"revoked_at": None, "expires_at": self.NOW + timedelta(seconds=1)},
                self.NOW,
            ),
            "present",
        )


class OutcomeLeakTests(unittest.TestCase):
    def test_outcome_never_contains_secret_or_digest(self):
        key = bootstrap.generate_key()
        digest_hex = sha256(("cisstat.worker/1\0" + key).encode()).hexdigest()
        row = {
            "service_id": "11111111-1111-1111-1111-111111111111",
            "kinds": ["delivery", "modeling", "render"],
            "created_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC) + timedelta(days=365),
            "revoked_at": None,
        }
        blob = json.dumps(
            [
                bootstrap._outcome("registered", row, days=365, key_configured=True),
                bootstrap._outcome("present", row),
                bootstrap._outcome("revoked", {**row, "revoked_at": datetime.now(UTC)}),
                bootstrap._outcome("missing"),
                bootstrap._outcome("invalid", key_configured=True),
                bootstrap._outcome("disabled", key_configured=True),
            ],
            default=str,
        )
        self.assertNotIn(key, blob)
        self.assertNotIn(digest_hex, blob)
        self.assertNotIn("key_hash", blob)


class StartupCheckTests(unittest.TestCase):
    def setUp(self):
        bootstrap.reset_for_testing()
        self.addCleanup(bootstrap.reset_for_testing)

    def test_records_outcome_for_health_ops(self):
        with patch.object(
            bootstrap,
            "ensure_service_credential",
            return_value={"state": "registered", "key_configured": True},
        ):
            out = bootstrap.startup_check()
        self.assertEqual(out["state"], "registered")
        self.assertEqual(bootstrap.last_status()["state"], "registered")

    def test_never_raises_and_records_safe_error(self):
        with patch.object(
            bootstrap,
            "ensure_service_credential",
            side_effect=RuntimeError("boom-boom"),
        ):
            out = bootstrap.startup_check()
        self.assertEqual(out["state"], "error")
        self.assertIn("boom-boom", out["detail"])
        self.assertEqual(bootstrap.last_status()["state"], "error")

    def test_peek_before_lifespan_is_not_checked(self):
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: ""}):
            status = bootstrap.last_status()
        self.assertEqual(status["state"], "not_checked")
        self.assertFalse(status["key_configured"])

    def test_reset_for_testing_clears_cache(self):
        bootstrap.record_status({"state": "registered"})
        bootstrap.reset_for_testing()
        self.assertEqual(bootstrap.last_status()["state"], "not_checked")


class WorkerErrorLegibilityTests(unittest.TestCase):
    """OPS-DIAG-1: 887+ одинаковых warning'ов подряд затемняют журнал;
    consecutive_errors остаётся честным, лог дедуплицируется."""

    @staticmethod
    def _worker():
        from apps.api.document_render_worker import DocumentRenderWorker

        return DocumentRenderWorker(interval=1)

    @staticmethod
    def _error(code="worker_service_unavailable"):
        return HTTPException(
            status_code=503,
            detail={"code": code, "message": "сбой", "request_id": ""},
        )

    def test_error_code_extracted_and_log_deduplicated(self):
        from apps.api.document_render_worker import ERROR_LOG_DEDUP_CYCLES

        worker = self._worker()
        with patch("apps.api.document_render_worker.logger") as lg:
            for _ in range(ERROR_LOG_DEDUP_CYCLES * 2):
                worker._record_error(self._error())
        status = worker.status()
        self.assertEqual(
            status["consecutive_errors"], ERROR_LOG_DEDUP_CYCLES * 2
        )
        self.assertEqual(status["last_error_code"], "worker_service_unavailable")
        self.assertEqual(lg.warning.call_count, 3)  # первый + каждые N циклов

    def test_new_reason_logs_immediately_and_updates_code(self):
        worker = self._worker()
        with patch("apps.api.document_render_worker.logger") as lg:
            worker._record_error(self._error("worker_service_unavailable"))
            worker._record_error(self._error("auth_authority_unavailable"))
        self.assertEqual(lg.warning.call_count, 2)
        self.assertEqual(
            worker.status()["last_error_code"], "auth_authority_unavailable"
        )

    def test_success_resets_counters_and_dedup(self):
        worker = self._worker()
        with patch("apps.api.document_render_worker.logger"):
            worker._record_error(self._error())
        worker._mark_success("2026-11-09T12:00:00+00:00", {"claimed": 0})
        status = worker.status()
        self.assertEqual(status["consecutive_errors"], 0)
        self.assertIsNone(status["last_error"])
        self.assertIsNone(status["last_error_code"])
        with patch("apps.api.document_render_worker.logger") as lg:
            worker._record_error(self._error())
        self.assertEqual(lg.warning.call_count, 1)  # снова «первый»
        self.assertEqual(worker.status()["consecutive_errors"], 1)

    def test_non_http_exception_has_no_code(self):
        worker = self._worker()
        with patch("apps.api.document_render_worker.logger"):
            worker._record_error(RuntimeError("plain failure"))
        self.assertIsNone(worker.status()["last_error_code"])

    def test_singleton_off_status_includes_last_error_code(self):
        from apps.api import document_render_worker as drw

        with patch.object(drw, "_worker", None):
            status = drw.document_render_worker_status()
        self.assertIn("last_error_code", status)
        self.assertIsNone(status["last_error_code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
