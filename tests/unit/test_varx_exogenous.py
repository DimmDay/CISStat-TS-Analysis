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
- vecm_stability: устойчивость VECM = ровно K - coint_rank единичных
  корней companion-матрицы уровневого VAR-представления (спектральная
  теорема Granger-представления; пересертификация Task 133, audit M6).
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


def _vecm_cointegrated_k3(n: int = 300, seed: int = 13) -> np.ndarray:
    """Коинтегрированная система K=3 ранга 1 (учебный DGP Lütkepohl гл. 6).

    y1 -- случайное блуждание (общий стохастический тренд), y2 = y1 +
    стационарный шум (одна коинтеграционная связь), y3 -- независимое
    блуждание (второй общий тренд).  Итого: K - r = 2 единичных корня,
    r = 1.  Спектр companion уровневого VAR: {1, 1, |lambda|<1}.
    """
    rng = np.random.default_rng(seed)
    y1 = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    y3 = 50.0 + np.cumsum(rng.normal(0.0, 1.2, n))
    y2 = y1 + rng.normal(0.0, 0.5, n)
    return np.column_stack([y1, y2, y3])


class TestVecmStability:
    """Устойчивость VECM: ровно K - coint_rank единичных корней companion.

    Спектральная теорема (Granger-представление; Johansen 1995,
    Lütkepohl 2005, гл. 6): уровневое VAR-представление VECM ранга r
    несёт K - r общих стохастических трендов => РОВНО K - r единичных
    корней; остальные r обязаны лежать строго внутри единичного круга.
    Единичные корни -- не дефект, а суть механизма коррекции ошибок;
    их число равно K - r, а НЕ самому рангу.  Прежняя семантика
    («ровно coint_rank») совпадала с теорией только на K=2, r=1.
    """

    def test_identity_blocks_full_rank_is_unstable(self):
        # eye(2): спектр {1, 1} -- 2 единичных корня.  Ранг r=K=2
        # (стационарные уровни) требует 0 единичных корней => комбинация
        # внутренне противоречива, модель НЕ устойчива.
        blocks = [np.eye(2)]
        report = vecm_stability(blocks, coint_rank=2)
        assert report["n_unit_roots"] == 2
        assert report["expected_unit_roots"] == 0
        assert report["is_stable"] is False
        assert abs(report["max_modulus"] - 1.0) <= 1e-8

    def test_rank_mismatch_is_unstable(self):
        # K=2, r=1: требуется ровно 1 единичный корень; eye(2) даёт 2.
        blocks = [np.eye(2)]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["expected_unit_roots"] == 1
        assert report["n_unit_roots"] == 2
        assert report["is_stable"] is False

    def test_stationary_companion_full_rank_stable(self):
        # diag(0.5, 0.3): стационарный companion <=> r=K=2, 0 единичных
        # корней.  Тот же companion с заявленным r=0 противоречив
        # (потребовал бы K-0=2 общих трендов).
        blocks = [np.diag([0.5, 0.3])]
        report = vecm_stability(blocks, coint_rank=2)
        assert report["n_unit_roots"] == 0
        assert report["expected_unit_roots"] == 0
        assert report["is_stable"] is True
        assert abs(report["max_modulus"] - 0.5) <= 1e-12
        report = vecm_stability(blocks, coint_rank=0)
        assert report["expected_unit_roots"] == 2
        assert report["is_stable"] is False

    def test_mixed_spectrum_rank_one(self):
        # K=2, r=1: спектр {1.0, 0.5} -- ровно 1 единичный корень, 0.5
        # строго внутри => устойчиво; при r=0 требуется 2 корня => нет.
        blocks = [np.diag([1.0, 0.5])]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["expected_unit_roots"] == 1
        assert report["is_stable"] is True
        report = vecm_stability(blocks, coint_rank=0)
        assert report["is_stable"] is False

    def test_three_series_rank_one_requires_two_unit_roots(self):
        # Ключевой K=3-случай (audit M6): K=3, r=1 => K-r=2 единичных
        # корня.  Диагональный спектр {1, 1, 0.5} -- устойчивая VECM;
        # прежняя семантика («ровно r») давала ложную тревогу.
        blocks = [np.diag([1.0, 1.0, 0.5])]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["n_series"] == 3
        assert report["expected_unit_roots"] == 2
        assert report["n_unit_roots"] == 2
        assert report["is_stable"] is True

    def test_three_series_extra_unit_root_is_unstable(self):
        # K=3, r=1, спектр {1, 1, 1}: лишний единичный корень --
        # пропущенный общий тренд, misspecification => нестабильно.
        blocks = [np.diag([1.0, 1.0, 1.0])]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["n_unit_roots"] == 3
        assert report["expected_unit_roots"] == 2
        assert report["is_stable"] is False

    def test_rank_above_dimension_fails_closed(self):
        with pytest.raises(MultivariateContractError, match="размерност"):
            vecm_stability([np.eye(2)], coint_rank=3)

    def test_statsmodels_vecm_oracle_k3_rank1(self):
        """Oracle-привязка (пересертификация Task 133): реальный фит
        statsmodels VECM на коинтегрированной системе K=3, r=1.

        Спектр companion var_rep обязан иметь ровно K-r=2 единичных
        корня и стабильную неранговую часть; rank-тест Йохансена на той
        же матрице подтверждает r=1.  Прежняя семантика («ровно
        coint_rank=1») на этом оракуле давала is_stable=False (audit C6).
        """
        from statsmodels.tsa.vector_ar.vecm import select_coint_rank

        from apps.api.model_impls.vecm import _vecm_fit_predict

        matrix = _vecm_cointegrated_k3()
        rank_oracle = select_coint_rank(
            matrix, det_order=0, k_ar_diff=1, method="trace", signif=0.05,
        )
        assert int(rank_oracle.rank) == 1
        payload = _vecm_fit_predict(
            [float(v) for v in matrix[:, 0]], 4,
            related_series={
                "b": [float(v) for v in matrix[:, 1]],
                "c": [float(v) for v in matrix[:, 2]],
            },
            params={"k_ar_diff": 1, "coint_rank": 1},
        )
        blocks = payload["coefficient_matrices"]
        report = vecm_stability(blocks, coint_rank=1)
        assert report["n_series"] == 3
        assert report["n_unit_roots"] == 3 - 1
        assert report["expected_unit_roots"] == 2
        assert report["is_stable"] is True
        # Регрессионный якорь против возврата к инвертированной семантике:
        # число единичных корней НЕ равно рангу (2 != 1).
        assert report["n_unit_roots"] != report["coint_rank"]
        # Неранговая часть спектра строго внутри единичного круга
        # (включая сдвиговые нули companion-блока порядка k_ar_diff+1).
        inside = [m for m in report["eigenvalue_moduli"]
                  if abs(m - 1.0) > 1e-8]
        assert all(m < 1.0 for m in inside)
        assert len(inside) == 3 * (len(blocks) - 1) + 1


class TestVecmEngineWhiteNoise:
    """Движок: белый шум VECM учитывает фактический порядок модели.

    Прежде движок брал metadata["lag_order"], которого у VECM нет =>
    nlags=3 и fitted_var_order=0 при любом k_ar_diff: df Portmanteau
    завышен (K^2*nlags вместо K^2*(nlags-p) - K*r), а окно могло быть
    меньше порядка модели (audit Task 133, замечание 1).
    """

    def _run_vecm(self, k_ar_diff: int) -> dict:
        n = 160
        rng = np.random.default_rng(13)
        y1 = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
        y2 = y1 + rng.normal(0.0, 0.5, n)
        matrix = np.column_stack([y1, y2])
        labels = [stamp.strftime("%Y-%m-%d")
                  for stamp in pd.date_range("2020-01-01", periods=n)]
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
        horizon, n_splits = 4, 2
        folds = []
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
            n_observations=n, fingerprint="fp-vecm-wn",
            target_column="y", seasonal_period=1,
            objective="multivariate", series_fingerprints=fingerprints,
            cohort_contract_override=contract,
        )
        return run_vector_backtest_plan(
            model_id="vecm", model_name="VECM", family_id="multivariate",
            system=system, plan=plan, seasonal_period=1,
            params={"k_ar_diff": k_ar_diff, "coint_rank": 1},
        )

    def test_white_noise_window_and_df_respect_model_order(self):
        result = self._run_vecm(3)
        k, r, p = 2, 1, 3  # K=2 серии, ранг 1, k_ar_diff=3
        for fold in result["folds"]:
            diagnostics = fold["multivariate_diagnostics"]
            assert diagnostics["vecm"]["k_ar_diff"] == p
            wn = diagnostics["white_noise"]
            assert wn["available"] is True
            # Уровневый порядок k_ar_diff+1=4; окно строго выше него
            # (прежде окно было всегда 3 -- меньше порядка).
            model_order = p + 1
            expected_nlags = max(model_order + 1, min(8, model_order + 3))
            assert wn["joint"]["nlags"] == expected_nlags
            assert expected_nlags > model_order
            # df несёт поправку ранга: K^2*(nlags - p) - K*r (паритет
            # statsmodels VECMResults.test_whiteness).
            assert wn["joint"]["fitted_var_order"] == p
            assert wn["joint"]["rank_adjustment"] == k * r
            assert wn["joint"]["df"] == k * k * (expected_nlags - p) - k * r

    def test_vecm_white_noise_rank_adjustment_shrinks_df(self):
        # Прежнее поведение: порядок 0, без ранговой поправки => при том же
        # окне df = K^2*nlags.  Поправка K*r честно съедает степени свободы
        # под restricted-параметры ранга, а окно растёт вместе с порядком
        # модели (прежде окно всегда было 3 -- меньше порядка при k_ar_diff>=3).
        result = self._run_vecm(3)
        k, r, p = 2, 1, 3
        fold = result["folds"][0]
        wn = fold["multivariate_diagnostics"]["white_noise"]
        nlags = wn["joint"]["nlags"]
        assert nlags > p + 1  # окно выше уровневого порядка k_ar_diff+1=4
        assert wn["joint"]["df"] == k * k * (nlags - p) - k * r
        assert wn["joint"]["df"] < k * k * nlags  # прежний df при том же окне
