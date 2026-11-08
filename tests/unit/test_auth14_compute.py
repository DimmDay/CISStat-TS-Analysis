"""Independent AUTH-14 fixed-point pricing and bounded work oracles."""

import unittest
from apps.api.billing.compute_units import (
    Coefficient,
    Workload,
    quote_work,
    charge_units,
)
from apps.api.billing.compute_meter import meter_scope, tick, WorkLimitExceeded


class PricingTests(unittest.TestCase):
    def coefficient(self, **changes):
        return Coefficient.model_validate(
            dict(
                key="tuning:ets",
                base_micro_cu="0.125",
                exponent="1",
                max_rows=1000,
                max_columns=4,
                max_units=64,
                max_horizon=24,
                max_period=12,
                wall_ms=30000,
                memory_mb=512,
                **changes,
            )
        )

    def work(self, **changes):
        data = dict(
            key="tuning:ets",
            rows=3,
            columns=1,
            units=2,
            horizon=1,
            seasonal_period=1,
            grid_points=1,
        )
        data.update(changes)
        return Workload.model_validate(data)

    def test_rounding_once_per_billable_unit_is_integer(self):
        q = quote_work(self.work(), self.coefficient(), profile_hash="a" * 64)
        self.assertEqual((q.unit_micro_cu, q.reserved_micro_cu), (1, 2))
        self.assertEqual(charge_units(q, 1), 1)

    def test_extra_work_cannot_exceed_quote(self):
        q = quote_work(self.work(), self.coefficient(), profile_hash="a" * 64)
        with self.assertRaises(ValueError):
            charge_units(q, 3)

    def test_dimensions_cannot_extrapolate(self):
        for change in (
            {"rows": 1001},
            {"columns": 5},
            {"units": 65},
            {"horizon": 25},
            {"seasonal_period": 13},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                quote_work(
                    self.work(**change), self.coefficient(), profile_hash="a" * 64
                )

    def test_integer_dimensions_reject_bool_float_negative(self):
        for n in (True, 1.0, -1, 0):
            with self.subTest(n=n), self.assertRaises(ValueError):
                self.work(rows=n)

    def test_coefficient_rejects_nonfinite_and_overflow(self):
        for n in ("NaN", "Infinity", "-1"):
            data = self.coefficient().model_dump()
            data["base_micro_cu"] = n
            with self.assertRaises(ValueError):
                Coefficient.model_validate(data)
        data = self.coefficient().model_dump()
        data["base_micro_cu"] = str(2**63)
        with self.assertRaises(ValueError):
            quote_work(
                self.work(), Coefficient.model_validate(data), profile_hash="a" * 64
            )

    def test_meter_denies_before_extra_work(self):
        with meter_scope("tuning:ets", 2) as meter:
            tick("tuning:ets")
            tick("tuning:ets")
            with self.assertRaises(WorkLimitExceeded):
                tick("tuning:ets")
            self.assertEqual(meter.units, 2)

    def test_foreign_kernel_cannot_consume_a_different_quote(self):
        with meter_scope("tuning:ets", 2) as meter:
            with self.assertRaises(WorkLimitExceeded):
                tick("pelt")
            self.assertEqual(meter.units, 0)


class ProcessMeterTests(unittest.TestCase):
    def test_actual_killed_work_retains_attempt_count(self):
        from apps.api.workers.process import run_bounded, WorkStopped

        with self.assertRaises(WorkStopped) as error:
            run_bounded(tick_hang, timeout=3, work_key="tuning:ets", work_limit=2)
        self.assertEqual(error.exception.proof.usage["units"], 1)
        self.assertTrue(error.exception.proof.stopped)

    def test_missing_profile_is_distinct_from_bad_configured_profile(self):
        import os, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from apps.api.billing.compute_profile import load_profile

        with patch.dict(
            os.environ, {"CISSTAT_CU_PROFILE": "", "CISSTAT_CU_PROFILE_SHA256": ""}
        ):
            self.assertIsNone(load_profile())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("{}")
            with patch.dict(
                os.environ,
                {
                    "CISSTAT_CU_PROFILE": str(path),
                    "CISSTAT_CU_PROFILE_SHA256": "a" * 64,
                },
            ):
                with self.assertRaises(ValueError):
                    load_profile()


def tick_hang():
    import time

    tick("tuning:ets")
    while True:
        time.sleep(0.05)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        from apps.api.billing.compute_profile import machine
        from unittest.mock import patch

        self.environment = {**machine(), "memory_limit_bytes": 4 * 1024**3}
        mocked = patch(
            "apps.api.billing.compute_benchmark.machine", return_value=self.environment
        )
        mocked.start()
        self.addCleanup(mocked.stop)

    def report(self):
        from apps.api.billing.compute_profile import kernel_digest

        samples = []
        for rows in (100, 200, 400):
            for seed in (1, 2, 3):
                work = Workload(
                    key="tuning:ets", rows=rows, columns=1, units=2, folds=2
                )
                samples.append(
                    {
                        "case": {
                            "key": "tuning:ets",
                            "seed": seed,
                            "holdout": seed == 3,
                        },
                        "status": "ok",
                        "work": work.model_dump(),
                        "usage": {"key": "tuning:ets", "units": 2},
                        "metrics": {
                            "cpu_ns": rows * 8000,
                            "parent_wall_ns": 100000000,
                            "rss_peak_bytes": 1000000,
                        },
                        "result": {"successful_trials": 1},
                    }
                )
        return {
            "schema_version": "auth14.benchmark/1",
            "environment": self.environment,
            "kernels": kernel_digest(),
            "requested_keys": ["tuning:ets"],
            "samples": samples,
            "timeout_seconds": 10,
            "memory_mb": 128,
            "reserve_memory_mb": 0,
            "load_test": {"concurrency": 1, "samples": [samples[-1]]},
        }

    def test_training_envelope_covers_independent_holdout(self):
        from apps.api.billing.compute_benchmark import calibrate

        profile, checks = calibrate(self.report())
        self.assertEqual(profile.max_concurrency, 1)
        self.assertTrue(
            all(
                c["quoted_attempted_micro_cu"] >= c["measured_cpu_microseconds"]
                for c in checks
            )
        )

    def test_underestimated_holdout_is_rejected_without_refitting(self):
        from apps.api.billing.compute_benchmark import calibrate

        report = self.report()
        report["samples"][-1]["metrics"]["cpu_ns"] *= 100
        with self.assertRaisesRegex(ValueError, "holdout"):
            calibrate(report)

    def test_leaked_seed_and_missing_measurement_reject_profile(self):
        from apps.api.billing.compute_benchmark import calibrate

        report = self.report()
        report["samples"][-1]["case"]["seed"] = 1
        with self.assertRaisesRegex(ValueError, "leaked"):
            calibrate(report)
        report = self.report()
        report["samples"][0]["metrics"]["rss_peak_bytes"] = 0
        with self.assertRaises(ValueError):
            calibrate(report)


def orphan_native_process():
    import subprocess, sys

    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]).pid


class ProcessTreeTests(unittest.TestCase):
    @unittest.skipUnless(
        __import__("sys").platform == "linux", "Linux process-group oracle"
    )
    def test_joined_parent_does_not_leave_native_descendant_running(self):
        from apps.api.workers.process import run_bounded, _linux_group

        child, proof = run_bounded(orphan_native_process, timeout=10)
        self.assertGreater(child, 0)
        self.assertTrue(proof.stopped)
        self.assertEqual(_linux_group(proof.pid)[1], [])


def delayed_marker(path):
    import time
    from pathlib import Path

    time.sleep(0.55)
    Path(path).write_text("deadline escaped")
    while True:
        time.sleep(0.05)


class DeadlineTests(unittest.TestCase):
    def test_authority_io_cannot_extend_physical_runtime(self):
        import tempfile, time
        from pathlib import Path
        from apps.api.workers.process import run_bounded, WorkStopped

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "escaped"
            with self.assertRaises(WorkStopped) as error:
                run_bounded(
                    delayed_marker,
                    (str(marker),),
                    timeout=0.3,
                    checkpoint=lambda: time.sleep(1.5),
                )
            self.assertFalse(
                marker.exists(),
                "blocked authority pulse extended physical compute deadline",
            )
            self.assertEqual(error.exception.code, "worker_timeout")


class WorkloadBoundaryTests(unittest.TestCase):
    def test_generated_features_are_part_of_actual_work_volume(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from apps.api.billing.compute_runtime import tuning_work

        plan = SimpleNamespace(
            folds=[1, 2],
            horizon=4,
            gap=0,
            n_observations=80,
            feature_columns={},
            feature_plan=SimpleNamespace(features=[1, 2]),
        )
        module = SimpleNamespace(
            prepare_tuning_grid=lambda *a, **k: SimpleNamespace(selected=[{}])
        )
        with patch.dict(sys.modules, {"apps.api.modeling_tuning": module}):
            work = tuning_work(
                dict(model_id="ets", plan=plan, param_space={}, metric="mae")
            )
        self.assertEqual(work.columns, 3)

    def test_inline_reserves_all_trials_while_async_phase_meters_one(self):
        from types import SimpleNamespace
        from datetime import datetime, UTC, timedelta
        from unittest.mock import patch
        from apps.api.workers.execution import Execution
        from apps.api.workers.process import StopProof

        claim = SimpleNamespace(
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            lease_until=datetime.now(UTC) + timedelta(seconds=30),
        )
        authority = SimpleNamespace(seal_stop=lambda *a, **k: {}, pulse=lambda c: None)
        for phased, expected in ((False, 4), (True, 2)):
            execution = Execution(authority, claim)
            execution.compute_descriptor = {
                "compute_work": {"key": "tuning:ets", "units": 4}
            }
            if phased:
                execution.model_job = ("model_jobs", "example")
            with (
                patch(
                    "apps.api.workers.execution.run_bounded",
                    return_value=(1, StopProof(True, 1, 0, "completed")),
                ) as bounded,
                patch("apps.api.workers.spool.save"),
            ):
                execution.run(lambda **k: 1, plan=SimpleNamespace(folds=[1, 2]))
            self.assertEqual(bounded.call_args.kwargs["work_limit"], expected)
