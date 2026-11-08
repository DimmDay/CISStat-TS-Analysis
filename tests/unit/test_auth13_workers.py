"""AUTH-13 execution contracts and real bounded process stop oracles."""

import unittest, time
from apps.api.workers.process import run_bounded, WorkStopped, WorkFailed


def add(a, b):
    return a + b


def hang():
    while True:
        time.sleep(0.05)


def child_secrets():
    import os

    return {
        key: os.environ.get(key)
        for key in ("DATABASE_URL", "CISSTAT_WORKER_KEY", "CISSTAT_AUTH_CSRF_KEY")
    }


def crash():
    import os

    os._exit(7)


def invalid_trial():
    raise ValueError("invalid trial")


class WorkerUnitTests(unittest.TestCase):
    def test_worker_service_key_is_redacted_in_operational_errors(self):
        from apps.api.storage_diagnostics import safe_error

        secret = "cwk_" + "x" * 43
        self.assertNotIn(secret, safe_error(RuntimeError("credential " + secret)))

    def test_child_never_inherits_authority_secrets(self):
        from unittest.mock import patch

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "secret-db",
                "CISSTAT_WORKER_KEY": "secret-worker",
                "CISSTAT_AUTH_CSRF_KEY": "secret-csrf",
            },
        ):
            value, proof = run_bounded(child_secrets, timeout=5)
        self.assertEqual(value, dict.fromkeys(value))
        self.assertTrue(proof.stopped)

    def test_crash_has_positive_exit_evidence(self):
        with self.assertRaises(WorkStopped) as error:
            run_bounded(crash, timeout=5)
        self.assertEqual(error.exception.code, "worker_process_crash")
        self.assertEqual(error.exception.proof.exit_code, 7)
        self.assertTrue(error.exception.proof.stopped)

    def test_authority_revoke_stops_work_within_bound(self):
        def reject():
            raise RuntimeError("revoked")

        start = time.monotonic()
        with self.assertRaises(WorkStopped) as error:
            run_bounded(hang, timeout=5, checkpoint=reject)
        self.assertEqual(error.exception.code, "worker_authority_lost")
        self.assertTrue(error.exception.proof.stopped)
        self.assertLess(time.monotonic() - start, 4)

    def test_joined_domain_failure_is_not_unknown_execution(self):
        with self.assertRaises(WorkFailed) as error:
            run_bounded(invalid_trial, timeout=15)
        self.assertIsInstance(error.exception.error, ValueError)
        self.assertTrue(error.exception.proof.stopped)

    def test_unknown_stop_does_not_reuse_not_started_proof(self):
        from unittest.mock import Mock, patch
        from types import SimpleNamespace
        from datetime import UTC, datetime, timedelta
        from apps.api.workers.execution import Execution
        from apps.api.workers.process import StopProof

        auth = Mock()
        auth.seal_stop.side_effect = [
            {"outcome": "not_started"},
            RuntimeError("stop not proved"),
        ]
        claim = SimpleNamespace(
            deadline=datetime.now(UTC) + timedelta(seconds=10),
            lease_until=datetime.now(UTC) + timedelta(seconds=10),
            worker_id="one",
            fence=1,
        )
        work = Execution(auth, claim)
        with patch(
            "apps.api.workers.execution.run_bounded",
            side_effect=WorkStopped(
                "worker_stop_unknown", StopProof(False, 123, None, "unknown")
            ),
        ):
            with self.assertRaises(RuntimeError):
                work.run(add, 1, 2)
        work.abort()
        auth.stopped.assert_not_called()
        auth.uncertain.assert_called_once_with("one", expected_fence=1)

    def test_pure_result_is_returned_only_after_join(self):
        result, proof = run_bounded(add, (2, 3), timeout=5)
        self.assertEqual(result, 5)
        self.assertTrue(proof.stopped)

    def test_timeout_stops_process_before_return(self):
        start = time.monotonic()
        with self.assertRaises(WorkStopped) as e:
            run_bounded(hang, (), timeout=0.3)
        self.assertTrue(e.exception.proof.stopped)
        self.assertLess(time.monotonic() - start, 4)
