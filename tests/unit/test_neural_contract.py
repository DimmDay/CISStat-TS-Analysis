# tests/unit/test_neural_contract.py
"""Task 137 -- Neural Runtime Contract: контракт-тесты нейро-runtime (каркас Tasks 138-142).

Постановка docs/modeling_task_list.md::Task 137 -- унификация пяти нейро-моделей
(LSTM/GRU, N-BEATS, N-HiTS, TFT, DeepAR) на NeuralForecast вместо смеси
Darts/GluonTS/PyTorch Forecasting.  Контракт -- инфраструктурный уровень
(прецедент: volatility_contract.py Task 134, multivariate_contract.py Task 131),
НЕЗАВИСИМЫЙ от HTTP/session-кода; torch/neuralforecast на уровне модуля НЕ
импортируются (ленивая загрузка -- уровень neural_runtime).

Поверхности контракта (по пунктам постановки):
1. Единый long-format unique_id/ds/y -- to_long_format/validate_long_format.
2. Historic/future/static exogenous-контракт -- build_exogenous_plan
   (явная классификация БЕЗ скрытого угадывания) + validate_future_exogenous_frame.
3. CPU/GPU worker capabilities -- neural_worker_capabilities/resolve_neural_device
   (gpu=required без GPU-сигнала -- честный отказ, без тихого CPU-понижения).
4. Checkpoints вне Redis JSON -- NeuralCheckpointStore (filesystem-бэкенд,
   JSON-safe pointer, sha256 анти-тампер, размерный потолок).
5. Early stopping, seed, max epochs/steps -- NeuralTrainingConfig (bounded, XOR-бюджет).
6. Probabilistic losses и quantiles -- interval_levels_for_alpha/resolve_probabilistic_loss.
7. Продолжение job после рестарта -- restore_resume_state по pointer из job-записи.
"""
from __future__ import annotations

import json
import random as py_random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apps.api.neural_contract import (
    CHECKPOINT_MAX_BYTES,
    DEFAULT_NEURAL_QUANTILE_LEVELS,
    NEURAL_CONTRACT_VERSION,
    NEURAL_PROBABILISTIC_LOSSES,
    NEURAL_RUNTIME,
    NeuralCheckpointStore,
    NeuralContractError,
    NeuralExogenousPlan,
    NeuralIntervalPlan,
    NeuralRuntimeUnavailableError,
    NeuralTrainingConfig,
    build_exogenous_plan,
    build_static_frame,
    checkpoint_pointer_is_json_safe,
    checkpoint_policy,
    fold_seed,
    interval_levels_for_alpha,
    neural_cohort_contract,
    neural_worker_capabilities,
    resolve_neural_device,
    resolve_probabilistic_loss,
    restore_resume_state,
    to_long_format,
    validate_future_exogenous_frame,
    validate_long_format,
)


# ── Фикстуры ──────────────────────────────────────────────────────────────

def _univariate_frame(n: int = 64) -> pd.DataFrame:
    """Регулярная дневная сетка + детерминированный сигнал."""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    values = 10 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.1
    return pd.DataFrame({"ts": idx, "value": values})


def _panel_frame(n_per_series: int = 48, n_series: int = 3) -> pd.DataFrame:
    """Гenuine-панель: несколько сущностей на общей сетке."""
    rng = np.random.default_rng(23)
    idx = pd.date_range("2024-03-01", periods=n_per_series, freq="D")
    frames = []
    for i in range(n_series):
        values = 5 + i * 2 + rng.standard_normal(n_per_series) * 0.2
        frames.append(
            pd.DataFrame({"ts": idx, "entity": f"obj_{i}", "value": values})
        )
    return pd.concat(frames, ignore_index=True)


# ── 1. Long-format unique_id / ds / y ─────────────────────────────────────

class TestLongFormatContract:
    def test_univariate_to_long_format_shape_and_columns(self):
        long = to_long_format(_univariate_frame(), value_column="value", time_column="ts")
        assert list(long.columns) == ["unique_id", "ds", "y"]
        assert len(long) == 64
        assert long["unique_id"].nunique() == 1
        assert pd.api.types.is_datetime64_any_dtype(long["ds"])
        assert pd.api.types.is_float_dtype(long["y"])

    def test_panel_to_long_format_preserves_series_ids(self):
        long = to_long_format(
            _panel_frame(), value_column="value", time_column="ts",
            series_column="entity",
        )
        assert list(long.columns) == ["unique_id", "ds", "y"]
        assert long["unique_id"].nunique() == 3
        assert sorted(long["unique_id"].unique()) == ["obj_0", "obj_1", "obj_2"]
        # каждая серия -- регулярный срез без пересечений по (unique_id, ds)
        assert not long.duplicated(["unique_id", "ds"]).any()

    def test_long_format_sorted_by_unique_id_then_ds(self):
        frame = _panel_frame()
        long = to_long_format(
            frame, value_column="value", time_column="ts", series_column="entity",
        )
        expected = long.sort_values(["unique_id", "ds"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(long, expected)

    def test_keep_columns_carries_numeric_exog(self):
        frame = _univariate_frame()
        frame["temp"] = np.linspace(1.0, 2.0, len(frame))
        long = to_long_format(
            frame, value_column="value", time_column="ts",
            keep_columns=("temp",),
        )
        assert list(long.columns) == ["unique_id", "ds", "y", "temp"]
        np.testing.assert_allclose(long["temp"].to_numpy(), frame["temp"].to_numpy())

    def test_fail_closed_on_nan_values(self):
        frame = _univariate_frame()
        frame.loc[3, "value"] = np.nan
        with pytest.raises(NeuralContractError, match="NaN|конечн"):
            to_long_format(frame, value_column="value", time_column="ts")

    def test_fail_closed_on_infinite_values(self):
        frame = _univariate_frame()
        frame.loc[5, "value"] = np.inf
        with pytest.raises(NeuralContractError):
            to_long_format(frame, value_column="value", time_column="ts")

    def test_fail_closed_on_missing_value_column(self):
        with pytest.raises(NeuralContractError, match="nope"):
            to_long_format(_univariate_frame(), value_column="nope", time_column="ts")

    def test_fail_closed_on_duplicate_timestamps(self):
        frame = _univariate_frame()
        frame.loc[7, "ts"] = frame.loc[6, "ts"]
        with pytest.raises(NeuralContractError, match="повтор|дублик"):
            to_long_format(frame, value_column="value", time_column="ts")

    def test_validate_long_format_reports_series_count(self):
        long = to_long_format(
            _panel_frame(), value_column="value", time_column="ts",
            series_column="entity",
        )
        info = validate_long_format(long)
        assert info["n_series"] == 3
        assert info["n_observations"] == 144
        assert info["frequency"]  # регулярная сетка обнаружена

    def test_validate_long_format_fail_closed_on_gaps(self):
        long = to_long_format(_univariate_frame(), value_column="value", time_column="ts")
        broken = long.drop(index=10).reset_index(drop=True)
        with pytest.raises(NeuralContractError, match="нерегулярн|сетк"):
            validate_long_format(broken)


# ── 2. Historic / future / static exogenous contract ─────────────────────

class TestExogenousContract:
    def _long_with_exog(self):
        frame = _univariate_frame()
        n = len(frame)
        frame["price_promo"] = (np.arange(n) % 7 == 0).astype(float)      # известна в будущее
        frame["market_index"] = np.sin(np.arange(n) / 5.0)               # только прошлое
        frame["region_code"] = 42.0                                       # статика
        return to_long_format(
            frame, value_column="value", time_column="ts",
            keep_columns=("price_promo", "market_index", "region_code"),
        )

    def test_plan_classifies_declared_columns_explicitly(self):
        long = self._long_with_exog()
        plan = build_exogenous_plan(
            long, futr=("price_promo",), hist=("market_index",), stat=("region_code",),
        )
        assert isinstance(plan, NeuralExogenousPlan)
        assert plan.futr_exog_list == ("price_promo",)
        assert plan.hist_exog_list == ("market_index",)
        assert plan.stat_exog_list == ("region_code",)

    def test_plan_signature_is_stable_and_bound_to_columns(self):
        long = self._long_with_exog()
        plan_a = build_exogenous_plan(long, futr=("price_promo",))
        plan_b = build_exogenous_plan(long, futr=("price_promo",))
        plan_c = build_exogenous_plan(long, futr=())
        assert plan_a.signature == plan_b.signature
        assert plan_a.signature != plan_c.signature
        assert len(plan_a.signature) == 64  # sha256 hex

    def test_fail_closed_on_unknown_column(self):
        long = self._long_with_exog()
        with pytest.raises(NeuralContractError, match="nope"):
            build_exogenous_plan(long, futr=("nope",))

    def test_fail_closed_on_nan_in_declared_exog(self):
        long = self._long_with_exog()
        long.loc[2, "market_index"] = np.nan
        with pytest.raises(NeuralContractError, match="market_index"):
            build_exogenous_plan(long, hist=("market_index",))

    def test_fail_closed_on_non_constant_static_column(self):
        long = self._long_with_exog()
        long.loc[4, "region_code"] = 7.0
        with pytest.raises(NeuralContractError, match="region_code|стат"):
            build_exogenous_plan(long, stat=("region_code",))

    def test_fail_closed_on_column_declared_twice(self):
        long = self._long_with_exog()
        with pytest.raises(NeuralContractError, match="price_promo|дважды|пересек"):
            build_exogenous_plan(
                long, futr=("price_promo",), hist=("price_promo",),
            )

    def test_future_frame_requires_full_coverage(self):
        long = self._long_with_exog()
        plan = build_exogenous_plan(long, futr=("price_promo",))
        horizon = 7
        future = pd.DataFrame({
            "unique_id": ["series_0"] * horizon,
            "ds": pd.date_range("2024-03-05", periods=horizon, freq="D"),
            "price_promo": np.zeros(horizon),
        })
        validate_future_exogenous_frame(plan, future, n_series=1, horizon=horizon)

    def test_future_frame_fail_closed_on_short_coverage(self):
        long = self._long_with_exog()
        plan = build_exogenous_plan(long, futr=("price_promo",))
        horizon = 7
        short = pd.DataFrame({
            "unique_id": ["series_0"] * (horizon - 2),
            "ds": pd.date_range("2024-03-05", periods=horizon - 2, freq="D"),
            "price_promo": np.zeros(horizon - 2),
        })
        with pytest.raises(NeuralContractError, match="горизонт|покрыт"):
            validate_future_exogenous_frame(plan, short, n_series=1, horizon=horizon)

    def test_future_frame_fail_closed_when_futr_declared_but_frame_missing(self):
        long = self._long_with_exog()
        plan = build_exogenous_plan(long, futr=("price_promo",))
        with pytest.raises(NeuralContractError, match="futr|future"):
            validate_future_exogenous_frame(plan, None, n_series=1, horizon=7)

    def test_future_frame_not_required_without_futr(self):
        long = self._long_with_exog()
        plan = build_exogenous_plan(long, hist=("market_index",))
        validate_future_exogenous_frame(plan, None, n_series=1, horizon=7)

    def test_static_frame_one_row_per_series(self):
        long = to_long_format(
            _panel_frame().assign(region="eu"), value_column="value",
            time_column="ts", series_column="entity", keep_columns=("region",),
        )
        plan = build_exogenous_plan(long, stat=("region",))
        static = build_static_frame(long, plan)
        assert len(static) == long["unique_id"].nunique()
        assert "unique_id" in static.columns and "region" in static.columns


# ── 5. NeuralTrainingConfig: seed, early stopping, max steps ─────────────

class TestTrainingConfig:
    def test_config_with_max_steps(self):
        config = NeuralTrainingConfig(seed=42, max_steps=100)
        assert config.max_steps == 100

    def test_fail_closed_on_missing_budget(self):
        # NeuralForecast 3.x: max_epochs deprecated (fail-closed в BaseModel);
        # единый бюджет унифицированного runtime -- max_steps.
        with pytest.raises(NeuralContractError, match="max_steps"):
            NeuralTrainingConfig(seed=1)

    def test_fail_closed_on_seed_out_of_bounds(self):
        with pytest.raises(NeuralContractError, match="seed"):
            NeuralTrainingConfig(seed=-1, max_steps=10)
        with pytest.raises(NeuralContractError, match="seed"):
            NeuralTrainingConfig(seed=2**31, max_steps=10)

    def test_fail_closed_on_steps_out_of_bounds(self):
        with pytest.raises(NeuralContractError, match="max_steps"):
            NeuralTrainingConfig(seed=1, max_steps=0)
        with pytest.raises(NeuralContractError, match="max_steps"):
            NeuralTrainingConfig(seed=1, max_steps=10**6)

    def test_fail_closed_on_patience_without_val_size(self):
        with pytest.raises(NeuralContractError, match="val_size"):
            NeuralTrainingConfig(seed=1, max_steps=50, early_stopping_patience=3)

    def test_early_stopping_disabled_with_zero_patience(self):
        config = NeuralTrainingConfig(seed=1, max_steps=50, early_stopping_patience=0)
        assert config.early_stopping_enabled is False

    def test_early_stopping_enabled_with_val_size(self):
        config = NeuralTrainingConfig(
            seed=1, max_steps=50, early_stopping_patience=3, val_size=10,
        )
        assert config.early_stopping_enabled is True

    def test_fail_closed_on_negative_val_size(self):
        with pytest.raises(NeuralContractError, match="val_size"):
            NeuralTrainingConfig(seed=1, max_steps=50, val_size=-5)

    def test_fail_closed_on_bad_batch_size(self):
        with pytest.raises(NeuralContractError, match="batch_size"):
            NeuralTrainingConfig(seed=1, max_steps=50, batch_size=0)

    def test_fold_seed_is_deterministic_and_bounded(self):
        a = fold_seed(42, fold_index=0, step=0)
        b = fold_seed(42, fold_index=0, step=0)
        c = fold_seed(42, fold_index=1, step=0)
        d = fold_seed(43, fold_index=0, step=0)
        assert a == b
        assert a != c and a != d
        assert 0 <= a < 2**31


# ── 6. Probabilistic losses и quantiles ──────────────────────────────────

class TestProbabilisticContract:
    def test_default_quantile_levels_symmetric(self):
        assert DEFAULT_NEURAL_QUANTILE_LEVELS == (10.0, 50.0, 90.0)

    def test_interval_levels_for_alpha(self):
        plan = interval_levels_for_alpha(0.2)
        assert isinstance(plan, NeuralIntervalPlan)
        assert plan.levels == (10.0, 50.0, 90.0)
        assert plan.median_level == 50.0
        assert plan.method == "neural_quantile_outputs"

    def test_interval_levels_alpha_005(self):
        plan = interval_levels_for_alpha(0.05)
        assert plan.levels == (2.5, 50.0, 97.5)

    def test_fail_closed_on_alpha_out_of_range(self):
        with pytest.raises(NeuralContractError, match="alpha"):
            interval_levels_for_alpha(0.0)
        with pytest.raises(NeuralContractError, match="alpha"):
            interval_levels_for_alpha(1.0)
        with pytest.raises(NeuralContractError, match="alpha"):
            interval_levels_for_alpha(-0.1)

    def test_resolve_allowed_point_loss(self):
        assert resolve_probabilistic_loss("mae") == "mae"
        assert resolve_probabilistic_loss("mse") == "mse"

    def test_resolve_probabilistic_loss_requires_levels(self):
        for loss in NEURAL_PROBABILISTIC_LOSSES:
            resolved = resolve_probabilistic_loss(loss, levels=(10.0, 50.0, 90.0))
            assert resolved == loss
            with pytest.raises(NeuralContractError, match="quantile|уровн"):
                resolve_probabilistic_loss(loss)

    def test_fail_closed_on_unknown_loss(self):
        with pytest.raises(NeuralContractError, match="loss"):
            resolve_probabilistic_loss("cosine")


# ── 3. CPU/GPU worker capabilities ───────────────────────────────────────

class TestWorkerCapabilities:
    def test_capabilities_report_cpu_by_default(self, monkeypatch):
        monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
        caps = neural_worker_capabilities()
        assert caps["gpu_available"] is False
        assert caps["device"] == "cpu"
        assert caps["dependency_group"] == "neural"
        assert "neuralforecast" in caps["packages"]

    def test_capabilities_report_gpu_signal(self, monkeypatch):
        monkeypatch.setenv("CISSTAT_GPU_AVAILABLE", "1")
        caps = neural_worker_capabilities()
        assert caps["gpu_available"] is True
        assert caps["device"] == "cuda"

    def test_gpu_required_without_signal_fails_closed(self, monkeypatch):
        monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
        with pytest.raises(NeuralRuntimeUnavailableError):
            resolve_neural_device(requires_gpu=True)

    def test_gpu_optional_downgrades_to_cpu_honestly(self, monkeypatch):
        monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
        assert resolve_neural_device(requires_gpu=False) == "cpu"

    def test_gpu_required_with_signal_resolves_cuda(self, monkeypatch):
        monkeypatch.setenv("CISSTAT_GPU_AVAILABLE", "yes")
        assert resolve_neural_device(requires_gpu=True) == "cuda"


# ── 4+7. Checkpoints вне Redis JSON + продолжение job после рестарта ─────

class TestCheckpointStore:
    def _store(self, tmp_path: Path) -> NeuralCheckpointStore:
        return NeuralCheckpointStore(root=tmp_path / "ckpt")

    def test_save_creates_files_and_json_safe_pointer(self, tmp_path):
        store = self._store(tmp_path)
        pointer = store.save_checkpoint(
            "job-abc-1", b"\x00\x01binary-payload", metadata={"epoch": 3, "step": 42},
        )
        assert pointer["backend"] == "filesystem"
        assert pointer["checkpoint_id"] == "job-abc-1"
        assert pointer["bytes"] == len(b"\x00\x01binary-payload")
        assert pointer["contract_version"] == NEURAL_CONTRACT_VERSION
        assert pointer["metadata"]["epoch"] == 3
        assert checkpoint_pointer_is_json_safe(pointer)
        assert store.has_checkpoint("job-abc-1")

    def test_pointer_is_json_serializable_for_redis(self, tmp_path):
        store = self._store(tmp_path)
        pointer = store.save_checkpoint("job-json", b"payload", metadata={"k": "v"})
        encoded = json.dumps(pointer)  # как RedisSessionStore.save
        decoded = json.loads(encoded)
        assert decoded["sha256"] == pointer["sha256"]

    def test_load_roundtrip_verifies_sha256(self, tmp_path):
        store = self._store(tmp_path)
        payload = b"torch-ckpt-bytes"
        pointer = store.save_checkpoint("job-load", payload)
        loaded, manifest = store.load_checkpoint("job-load", pointer)
        assert loaded == payload
        assert manifest["sha256"] == pointer["sha256"]

    def test_load_fail_closed_on_tampered_sha(self, tmp_path):
        store = self._store(tmp_path)
        pointer = store.save_checkpoint("job-tamper", b"payload")
        tampered = dict(pointer, sha256="0" * 64)
        with pytest.raises(NeuralContractError, match="sha256|целостн"):
            store.load_checkpoint("job-tamper", tampered)

    def test_load_fail_closed_on_contract_version_mismatch(self, tmp_path):
        store = self._store(tmp_path)
        pointer = store.save_checkpoint("job-ver", b"payload")
        stale = dict(pointer, contract_version="neural-contract-v0")
        with pytest.raises(NeuralContractError, match="contract_version"):
            store.load_checkpoint("job-ver", stale)

    def test_save_fail_closed_on_oversized_payload(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "apps.api.neural_contract.CHECKPOINT_MAX_BYTES", 16,
        )
        store = self._store(tmp_path)
        with pytest.raises(NeuralContractError, match="превышает|MAX_BYTES"):
            store.save_checkpoint("job-big", b"x" * 17)

    def test_save_fail_closed_on_empty_payload(self, tmp_path):
        store = self._store(tmp_path)
        with pytest.raises(NeuralContractError, match="пуст"):
            store.save_checkpoint("job-empty", b"")

    @pytest.mark.parametrize("bad_id", ["../escape", "", "a/b", "a\nb", " x"])
    def test_save_fail_closed_on_unsafe_job_id(self, tmp_path, bad_id):
        store = self._store(tmp_path)
        with pytest.raises(NeuralContractError, match="job_id"):
            store.save_checkpoint(bad_id, b"payload")

    def test_delete_removes_checkpoint(self, tmp_path):
        store = self._store(tmp_path)
        store.save_checkpoint("job-del", b"payload")
        store.delete_checkpoint("job-del")
        assert not store.has_checkpoint("job-del")

    def test_restore_resume_state_after_restart(self, tmp_path):
        store = self._store(tmp_path)
        pointer = store.save_checkpoint(
            "job-resume", b"state",
            metadata={"epoch": 7, "next_step": 2, "optimizer_step": 140},
        )
        state = restore_resume_state("job-resume", pointer)
        assert state.checkpoint_path == pointer["path"]
        assert state.contract_version == NEURAL_CONTRACT_VERSION
        assert state.metadata["epoch"] == 7
        assert state.metadata["next_step"] == 2

    def test_restore_fail_closed_on_missing_file(self, tmp_path):
        pointer = {
            "backend": "filesystem",
            "checkpoint_id": "job-gone",
            "path": str(tmp_path / "missing.ckpt"),
            "bytes": 6,
            "sha256": "a" * 64,
            "contract_version": NEURAL_CONTRACT_VERSION,
            "metadata": {},
        }
        with pytest.raises(NeuralContractError, match="отсутств|найден"):
            restore_resume_state("job-gone", pointer)

    def test_checkpoint_policy_declares_out_of_redis_storage(self):
        policy = checkpoint_policy()
        assert policy["backend"] == "filesystem"
        assert policy["stored_in_redis_json"] is False
        assert policy["max_bytes"] == CHECKPOINT_MAX_BYTES
        assert policy["contract_version"] == NEURAL_CONTRACT_VERSION


# ── Cohort contract: декларация нейро-cohort для движка ──────────────────

class TestNeuralCohortContract:
    def _fixtures(self):
        long = to_long_format(
            _univariate_frame(), value_column="value", time_column="ts",
        )
        exogenous = build_exogenous_plan(long)
        interval = interval_levels_for_alpha(0.2)
        config = NeuralTrainingConfig(seed=7, max_steps=100)
        return long, exogenous, interval, config


    def test_univariate_cohort_declaration(self, monkeypatch):
        monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
        _, exogenous, interval, config = self._fixtures()
        cohort = neural_cohort_contract(
            fingerprint="fp-137",
            n_series=1,
            exogenous=exogenous,
            interval=interval,
            loss="mae",
            config=config,
        )
        assert cohort["objective"] == "level_forecast"
        assert cohort["dependency_group"] == "neural"
        assert cohort["runtime"] == NEURAL_RUNTIME
        assert cohort["input_kind"] == "univariate"
        assert cohort["fingerprint"] == "fp-137"
        assert cohort["interval"]["method"] == "neural_quantile_outputs"
        assert cohort["checkpoint_policy"]["backend"] == "filesystem"
        assert cohort["device"] == "cpu"

    def test_panel_cohort_for_multi_series(self):
        _, exogenous, interval, config = self._fixtures()
        cohort = neural_cohort_contract(
            fingerprint="fp-panel",
            n_series=5,
            min_series=5,
            exogenous=exogenous,
            interval=interval,
            loss="quantile",
            config=config,
        )
        assert cohort["input_kind"] == "panel"
        assert cohort["panel"] is True

    def test_fail_closed_below_declared_min_series(self):
        _, exogenous, interval, config = self._fixtures()
        with pytest.raises(NeuralContractError, match="панел|min_series"):
            neural_cohort_contract(
                fingerprint="fp-deepar",
                n_series=1,
                min_series=5,
                exogenous=exogenous,
                interval=interval,
                loss="mae",
                config=config,
            )

    def test_fail_closed_on_single_series_declared_panel(self):
        """Честность DeepAR: числовые колонки одного объекта -- НЕ панель."""
        _, exogenous, interval, config = self._fixtures()
        with pytest.raises(NeuralContractError):
            neural_cohort_contract(
                fingerprint="fp-fake-panel",
                n_series=1,
                min_series=5,
                exogenous=exogenous,
                interval=interval,
                loss="mae",
                config=config,
                input_kind="panel",
            )

    def test_cohort_binds_training_config_and_loss(self):
        _, exogenous, interval, config = self._fixtures()
        cohort = neural_cohort_contract(
            fingerprint="fp-bind",
            n_series=1,
            exogenous=exogenous,
            interval=interval,
            loss="mae",
            config=config,
        )
        assert cohort["training"]["seed"] == 7
        assert cohort["training"]["max_steps"] == 100
        assert cohort["loss"] == "mae"
        assert cohort["feature_contract"]["signature"] == exogenous.signature
