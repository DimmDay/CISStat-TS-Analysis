# tests/unit/test_varx_exogenous.py
"""Task 133 -- VARX: exogenous-канал векторных моделей.

Постановка (worklog3.md «Границы Task 132», замечание сертификации 131):
- VAR (supports_exogenous: true в rules/modeling.yaml) принимает
  future-known экзогенные регрессоры: statsmodels VAR(exog=...) +
  forecast_interval(..., exog_future=...);
- адаптер fail-closed: числовой/finite exog, длины train==nobs и
  future==horizon, обе части одновременно, одинаковые ключи;
- движок (run_vector_backtest_plan) принимает ПОЛНУЮ историю exog-колонок,
  выровненную с системой, и режет её per-fold: train_features=[:n_train],
  future_features=[n_train:n_train+execution_horizon];
- VECM (supports_exogenous: false) exog НЕ принимает: warning движка +
  fail-closed гейт реестра;
- cohort-контракт честно декларирует exogenous-канал
  (multivariate_cohort_contract), дефолт -- бит-в-бит прежний;
- vecm_stability: устойчивость VECM = ровно coint_rank единичных корней
  companion-матрицы уровневого VAR-представления.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_vector_backtest_plan,
)
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls.var import _var_fit_predict
from apps.api.multivariate_contract import (
    MultivariateContractError,
    build_endogenous_system,
    multivariate_cohort_contract,
    vecm_stability,
)


def _system_with_informative_x(n: int = 120, seed: int = 5):
    """Система [y, z] + future-known экзогенный x, входящий в уравнение y."""
    rng = np.random.default_rng(seed)
    x = 3.0 + rng.normal(0.0, 1.0, n)
    z = np.zeros(n)
    for t in range(1, n):
        z[t] = 0.4 * z[t - 1] + rng.normal(0.0, 0.5)
    y = 0.8 * x + 0.3 * z + rng.normal(0.0, 0.15, n)
    matrix = np.column_stack([y, z])
    return matrix, x


def _var_payload(matrix, x_train, x_future=None, horizon=4, **kwargs):
    return _var_fit_predict(
        [float(v) for v in matrix[:, 0]], horizon,
        related_series={"z": [float(v) for v in matrix[:, 1]]},
        exog={"x": [float(v) for v in x_train]},
        exog_future=None if x_future is None else
        {"x": [float(v) for v in x_future]},
        **kwargs,
    )


class TestVarxAdapter:
    """VARX на уровне адаптера: нативный exog-канал statsmodels."""

    def test_exog_known_future_beats_zero_future(self):
        """Знание будущего x даёт существенно лучший прогноз y, чем нули."""
        matrix, x = _system_with_informative_x()
        horizon = 8
        n_train = len(matrix) - horizon
        true_future = _var_payload(
            matrix[:n_train], x[:n_train], x[n_train:], horizon=horizon,
        )
        zero_future = _var_payload(
            matrix[:n_train], x[:n_train],
            np.zeros(horizon), horizon=horizon,
        )
        actual = matrix[n_train:, 0]
        mae_true = float(np.abs(true_future["forecast"][:, 0] - actual).mean())
        mae_zero = float(np.abs(zero_future["forecast"][:, 0] - actual).mean())
        assert mae_true < mae_zero * 0.5

    def test_exog_metadata_block(self):
        matrix, x = _system_with_informative_x()
        payload = _var_payload(matrix[:-4], x[:-4], x[-4:], horizon=4)
        assert payload["exogenous"] == {"names": ("x",), "n_exog": 1}

    def test_exog_changes_forecast(self):
        matrix, x = _system_with_informative_x()
        horizon, n_train = 4, len(matrix) - 4
        with_x = _var_payload(matrix[:n_train], x[:n_train], x[n_train:], horizon)
        without = _var_fit_predict(
            [float(v) for v in matrix[:n_train, 0]], horizon,
            related_series={"z": [float(v) for v in matrix[:n_train, 1]]},
        )
        assert not np.allclose(with_x["forecast"], without["forecast"])

    def test_future_exog_required_together_with_train(self):
        matrix, x = _system_with_informative_x()
        with pytest.raises(ValueError, match="exog"):
            _var_payload(matrix[:-4], x[:-4], None, horizon=4)

    def test_train_exog_required_together_with_future(self):
        matrix, x = _system_with_informative_x()
        with pytest.raises(ValueError, match="exog"):
            _var_fit_predict(
                [float(v) for v in matrix[:-4, 0]], 4,
                related_series={"z": [float(v) for v in matrix[:-4, 1]]},
                exog_future={"x": [float(v) for v in x[-4:]]},
            )

    def test_wrong_train_length_rejected(self):
        matrix, x = _system_with_informative_x()
        with pytest.raises(ValueError, match="длина"):
            _var_payload(matrix[:-4], x[:-6], x[-4:], horizon=4)

    def test_wrong_future_length_rejected(self):
        matrix, x = _system_with_informative_x()
        with pytest.raises(ValueError, match="будущего"):
            _var_payload(matrix[:-4], x[:-4], x[-6:], horizon=4)

    def test_nan_in_future_exog_rejected(self):
        """Fail-closed: импутация известного будущего запрещена."""
        matrix, x = _system_with_informative_x()
        broken = list(map(float, x[-4:]))
        broken[1] = float("nan")
        with pytest.raises(ValueError, match="NaN/Inf"):
            _var_payload(matrix[:-4], x[:-4], broken, horizon=4)

    def test_key_sets_must_match(self):
        matrix, x = _system_with_informative_x()
        with pytest.raises(ValueError, match="должны совпадать"):
            _var_fit_predict(
                [float(v) for v in matrix[:-4, 0]], 4,
                related_series={"z": [float(v) for v in matrix[:-4, 1]]},
                exog={"x": [float(v) for v in x[:-4]],
                      "w": [float(v) for v in x[:-4]]},
                exog_future={"x": [float(v) for v in x[-4:]]},
            )

    def test_no_exog_is_bit_for_bit_legacy(self):
        """Отсутствие exog -- прежний контракт VAR (Task 132) без изменений."""
        matrix, x = _system_with_informative_x()
        legacy = _var_fit_predict(
            [float(v) for v in matrix[:-4, 0]], 4,
            related_series={"z": [float(v) for v in matrix[:-4, 1]]},
            params={"maxlags": 2, "ic": None},
        )
        explicit_none = _var_fit_predict(
            [float(v) for v in matrix[:-4, 0]], 4,
            related_series={"z": [float(v) for v in matrix[:-4, 1]]},
            exog=None, exog_future=None,
            params={"maxlags": 2, "ic": None},
        )
        assert np.array_equal(legacy["forecast"], explicit_none["forecast"])


class TestEngineExogenousChannel:
    """Движок: полная история exog, per-fold срезы, честные отказы."""

    def _plan_for(self, matrix, labels):
        system = build_endogenous_system(
            {"y": [float(v) for v in matrix[:, 0]],
             "z": [float(v) for v in matrix[:, 1]]},
            timestamps=labels,
        )
        from app.core.passport import series_fingerprint

        fingerprints = {
            name: series_fingerprint(pd.Series(
                [float(v) for v in matrix[:, position]], index=labels,
            ))
            for position, name in enumerate(("y", "z"))
        }
        contract = multivariate_cohort_contract(
            system, series_fingerprints=fingerprints,
        )
        folds = []
        n = len(matrix)
        horizon, n_splits = 4, 2
        train_end = n - n_splits * horizon - 1
        for index in range(n_splits):
            start_test = train_end + 1 + horizon * index
            folds.append({
                "fold": index + 1, "train_start": 0,
                "train_end": train_end + horizon * index,
                "gap_size": 0, "test_start": start_test,
                "test_end": start_test + horizon - 1,
            })
        plan = build_backtest_plan(
            {"strategy": "expanding", "horizon": horizon,
             "n_splits": n_splits, "gap": 0, "folds": folds},
            n_observations=n, fingerprint="fp-varx", target_column="y",
            seasonal_period=1, objective="multivariate",
            series_fingerprints=fingerprints,
            cohort_contract_override=contract,
        )
        return system, plan

    def test_var_consumes_exogenous_in_engine(self):
        matrix, x = _system_with_informative_x()
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=len(matrix))]
        system, plan = self._plan_for(matrix, labels)
        base = dict(model_id="var", model_name="VAR", family_id="multivariate",
                    system=system, plan=plan, seasonal_period=1,
                    params={"maxlags": 2, "ic": None})
        without = base_run = None
        without = run_engine(base)
        with_run = run_engine({**base, "exogenous": {"x": [float(v) for v in x]}})
        predicted_without = [point["predicted"]
                             for point in without["oof_predictions"]
                             if point["series"] == "y"]
        predicted_with = [point["predicted"]
                          for point in with_run["oof_predictions"]
                          if point["series"] == "y"]
        assert predicted_with != predicted_without
        assert not any(
            "не примен" in warning for warning in with_run["warnings"]
        )

    def test_exogenous_length_mismatch_rejected(self):
        matrix, x = _system_with_informative_x()
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=len(matrix))]
        system, plan = self._plan_for(matrix, labels)
        with pytest.raises(BacktestExecutionError, match="длина"):
            run_vector_backtest_plan(
                model_id="var", model_name="VAR", family_id="multivariate",
                system=system, plan=plan, seasonal_period=1,
                exogenous={"x": [float(v) for v in x[:-2]]},
            )

    def test_exogenous_name_collision_with_system_rejected(self):
        matrix, x = _system_with_informative_x()
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=len(matrix))]
        system, plan = self._plan_for(matrix, labels)
        with pytest.raises(BacktestExecutionError, match="endogenous"):
            run_vector_backtest_plan(
                model_id="var", model_name="VAR", family_id="multivariate",
                system=system, plan=plan, seasonal_period=1,
                exogenous={"y": [float(v) for v in x]},
            )

    def test_non_numeric_exogenous_rejected(self):
        matrix, x = _system_with_informative_x()
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=len(matrix))]
        system, plan = self._plan_for(matrix, labels)
        with pytest.raises(BacktestExecutionError, match="числов"):
            run_vector_backtest_plan(
                model_id="var", model_name="VAR", family_id="multivariate",
                system=system, plan=plan, seasonal_period=1,
                exogenous={"x": ["a"] * len(matrix)},
            )

    def test_vecm_skips_exogenous_with_honest_warning(self):
        matrix, x = _system_with_informative_x()
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=len(matrix))]
        system, plan = self._plan_for(matrix, labels)
        base = dict(model_id="vecm", model_name="VECM", family_id="multivariate",
                    system=system, plan=plan, seasonal_period=1,
                    params={"coint_rank": 1})
        plain = run_engine(base)
        skipped = run_engine({**base, "exogenous": {"x": [float(v) for v in x]}})
        assert any("не примен" in warning and "x" in warning
                   for warning in skipped["warnings"])
        assert skipped["metrics"] == plain["metrics"]


def run_engine(request_kwargs: dict) -> dict:
    from apps.api.backtesting import run_vector_backtest_plan

    return run_vector_backtest_plan(**request_kwargs)


class TestRegistryVarxGates:
    """Реестр: VAR принимает future_features, VECM -- fail-closed."""

    def _request(self, model_id):
        matrix, x = _system_with_informative_x()
        n_train = len(matrix) - 4
        return ModelExecutionRequest(
            target=[float(v) for v in matrix[:n_train, 0]], horizon=4,
            objective="multivariate", seasonal_period=1, params={},
            related_series={"z": [float(v) for v in matrix[:n_train, 1]]},
            train_features={"x": [float(v) for v in x[:n_train]]},
            future_features={"x": [float(v) for v in x[n_train:]]},
        )

    def test_var_definition_declares_future_features(self):
        definition = MODEL_EXECUTION_REGISTRY.require("var")
        assert definition.supports_future_features is True
        assert definition.requires_train_features is False

    def test_vecm_definition_rejects_exogenous(self):
        definition = MODEL_EXECUTION_REGISTRY.require("vecm")
        assert definition.supports_future_features is False
        with pytest.raises(ModelExecutionContractError, match="future_features"):
            MODEL_EXECUTION_REGISTRY.execute("vecm", self._request("vecm"))

    def test_varx_registry_execution_roundtrip(self):
        result = MODEL_EXECUTION_REGISTRY.execute("var", self._request("var"))
        assert result.metadata["exogenous"]["n_exog"] == 1
        assert len(result.forecast) == 4


class TestCohortContractExogenous:
    """Честная декларация exogenous-канала в cohort-контракте."""

    def _system(self):
        matrix, _ = _system_with_informative_x()
        return build_endogenous_system(
            {"y": [float(v) for v in matrix[:, 0]],
             "z": [float(v) for v in matrix[:, 1]]},
            timestamps=[
                stamp.strftime("%Y-%m-%d")
                for stamp in pd.date_range("2020-01-01", periods=len(matrix))
            ],
        )

    def test_default_contract_is_bit_for_bit_legacy(self):
        contract = multivariate_cohort_contract(
            self._system(), series_fingerprints={"y": "fp-y", "z": "fp-z"},
        )
        assert contract["feature_contract"] == {
            "historic": [], "future_known": [], "static": [], "policy": "none",
        }

    def test_exogenous_declared_honestly(self):
        contract = multivariate_cohort_contract(
            self._system(), series_fingerprints={"y": "fp-y", "z": "fp-z"},
            exogenous_future_known=("x",), exogenous_static=("flag",),
        )
        assert contract["feature_contract"] == {
            "historic": [], "future_known": ["x"], "static": ["flag"],
            "policy": "varx_future_known",
        }
        assert contract["objective"] == "multivariate"

    def test_exogenous_names_validated(self):
        with pytest.raises(MultivariateContractError):
            multivariate_cohort_contract(
                self._system(), series_fingerprints={"y": "fp-y", "z": "fp-z"},
                exogenous_future_known=("y",),  # коллизия с endogenous
            )
        with pytest.raises(MultivariateContractError):
            multivariate_cohort_contract(
                self._system(), series_fingerprints={"y": "fp-y", "z": "fp-z"},
                exogenous_future_known=("x", "x"),
            )


class TestVecmStability:
    """Устойчивость VECM: ровно coint_rank единичных корней companion."""

    def test_identity_blocks_two_unit_roots(self):
        blocks = [np.eye(2)]
        report = vecm_stability(blocks, coint_rank=2)
        assert report["n_unit_roots"] == 2
        assert report["is_stable"] is True
        assert abs(report["max_modulus"] - 1.0) <= 1e-8

    def test_rank_mismatch_is_unstable(self):
        blocks = [np.eye(2)]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["is_stable"] is False

    def test_stationary_companion_rank_zero(self):
        blocks = [np.diag([0.5, 0.3])]
        report = vecm_stability(blocks, coint_rank=0)
        assert report["n_unit_roots"] == 0
        assert report["is_stable"] is True
        assert abs(report["max_modulus"] - 0.5) <= 1e-12

    def test_mixed_spectrum_rank_one(self):
        blocks = [np.diag([1.0, 0.5])]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["is_stable"] is True
        report = vecm_stability(blocks, coint_rank=0)
        assert report["is_stable"] is False
