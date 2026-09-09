# tests/unit/test_vecm_adapter.py
"""Task 133 -- VECM: нативный statsmodels-адаптер (family=multivariate).

Постановка docs/modeling_task_list.md::Task 133 (общая нота серии VAR/VECM):
- **Ранг Йохансена определяется ТОЛЬКО на train-fold**: адаптер получает
  train-срез системы; режим "auto" вызывает select_coint_rank на нём,
  полная история недостижима по построению.  Ранг 0 -- честный отказ
  (VECM неприменим), БЕЗ тихого VAR-fallback.
- **Нативный многомерный прогноз с интервалами** -- VECMResults.predict
  (mid/lower/upper при alpha).  НЕ цикл одномерных ARIMA.
- **Fail-closed**: ошибки fit/predict -- ошибки fold'а; никаких
  синтетических демо и Naive-подмен (run_vecm_backtest на одиночном
  synthetic-ряде честно отказывает).
- Bounded params: k_ar_diff (1..12), coint_rank ("auto" | int >= 1),
  deterministic (n/ci/co/li/lo), alpha (0.01/0.05/0.10).
- Детерминизм: OLS-оценка, случайность отсутствует.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

from apps.api.model_impls.vecm import (
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    DETERMINISTIC_OPTIONS,
    PARAM_BOUNDS,
    VECM_ADAPTER_ID,
    VECM_MIN_TRAIN,
    _vecm_fit_predict,
    run_vecm_backtest,
    validate_vecm_params,
)


def _cointegrated(n: int = 150, seed: int = 13) -> np.ndarray:
    """Коинтегрированная пара ранга 1: spread y2-y1 -- стационарный шум."""
    rng = np.random.default_rng(seed)
    y1 = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    y2 = y1 + rng.normal(0.0, 0.5, n)
    return np.column_stack([y1, y2])


def _independent_walks(n: int = 150, seed: int = 21) -> np.ndarray:
    """Две независимые случайные блуждания -- коинтеграции нет."""
    rng = np.random.default_rng(seed)
    return np.column_stack([
        100.0 + np.cumsum(rng.normal(0.0, 1.0, n)),
        50.0 + np.cumsum(rng.normal(0.0, 1.0, n)),
    ])


def _fit(matrix: np.ndarray, horizon: int = 4, **kwargs):
    params = kwargs.pop("params", None)
    return _vecm_fit_predict(
        [float(v) for v in matrix[:, 0]], horizon,
        related_series={
            name: [float(v) for v in matrix[:, position]]
            for position, name in enumerate(("b", "c"), start=1)
            if position < matrix.shape[1]
        },
        params=params, **kwargs,
    )


class TestAdapterLocationConvention:
    """Regression e6f6726-класса ошибок: адаптер живёт в model_impls/."""

    def test_module_docstring_pins_canonical_path(self):
        source = pathlib.Path(
            "apps/api/model_impls/vecm.py",
        ).read_text(encoding="utf-8")
        assert source.splitlines()[0].strip("# ").strip() == \
            "apps/api/model_impls/vecm.py"


class TestParamValidation:
    """Bounded param_space -- fail-closed вне допустимых значений."""

    def test_defaults(self):
        assert validate_vecm_params(None) == DEFAULT_PARAMS == {
            "k_ar_diff": 1, "coint_rank": "auto",
            "deterministic": "ci", "alpha": 0.05,
        }

    def test_adapter_id(self):
        assert VECM_ADAPTER_ID == "statsmodels-vecm"
        assert VECM_MIN_TRAIN == 20  # MIN_SYSTEM_OBSERVATIONS контракта

    def test_k_ar_diff_bounded(self):
        for bad in (0, 13, -1):
            with pytest.raises(ValueError, match="k_ar_diff"):
                validate_vecm_params({"k_ar_diff": bad})
        assert validate_vecm_params({"k_ar_diff": 12})["k_ar_diff"] == 12
        assert PARAM_BOUNDS["k_ar_diff"] == (1, 12)

    def test_k_ar_diff_type_safe(self):
        for bad in (True, 1.5, "3", None):
            with pytest.raises(ValueError, match="k_ar_diff"):
                validate_vecm_params({"k_ar_diff": bad})

    def test_coint_rank_auto_or_positive_int(self):
        assert validate_vecm_params({"coint_rank": "auto"})["coint_rank"] == "auto"
        assert validate_vecm_params({"coint_rank": 1})["coint_rank"] == 1
        for bad in (0, -2, "1", 1.5, True):
            with pytest.raises(ValueError, match="coint_rank"):
                validate_vecm_params({"coint_rank": bad})

    def test_deterministic_options(self):
        assert DETERMINISTIC_OPTIONS == {"n", "ci", "co", "li", "lo"}
        with pytest.raises(ValueError, match="deterministic"):
            validate_vecm_params({"deterministic": "ct"})

    def test_alpha_options(self):
        assert ALPHA_OPTIONS == {0.01, 0.05, 0.10}
        with pytest.raises(ValueError, match="alpha"):
            validate_vecm_params({"alpha": 0.5})

    def test_unknown_keys_ignored(self):
        normalized = validate_vecm_params({"maxlags": 4, "ic": "aic"})
        assert "maxlags" not in normalized and "ic" not in normalized


class TestFailClosedInputs:
    """Системные гейты адаптера: K>=2, finite, длины, история."""

    def test_single_series_rejected(self):
        with pytest.raises(ValueError, match="не менее 2"):
            _vecm_fit_predict([1.0, 2.0, 3.0], 2)

    def test_nan_rejected(self):
        matrix = _cointegrated()
        matrix[7, 0] = np.nan
        with pytest.raises(ValueError, match="NaN/Inf"):
            _fit(matrix)

    def test_length_mismatch_rejected(self):
        matrix = _cointegrated()
        with pytest.raises(ValueError, match="длина"):
            _vecm_fit_predict(
                [float(v) for v in matrix[:-3, 0]], 2,
                related_series={"b": [float(v) for v in matrix[:, 1]]},
            )

    def test_short_history_rejected(self):
        matrix = _cointegrated(n=15)
        with pytest.raises(ValueError, match=f"минимум {VECM_MIN_TRAIN}"):
            _fit(matrix)

    def test_history_insufficient_for_k_ar_diff(self):
        matrix = _cointegrated(n=40)
        with pytest.raises(ValueError, match="короткая"):
            _fit(matrix, params={"k_ar_diff": 12})

    def test_horizon_positive(self):
        with pytest.raises(ValueError, match="horizon"):
            _fit(_cointegrated(), horizon=0)

    def test_fixed_rank_exceeds_k_minus_one(self):
        matrix = _cointegrated()  # K=2 => ранг <= 1
        with pytest.raises(ValueError, match="coint_rank"):
            _fit(matrix, params={"coint_rank": 2})


class TestFoldLocalJohansenRank:
    """Ранг Йохансена -- только на train-срезе, "auto" без fallback."""

    def test_auto_rank_on_cointegrated_system(self):
        payload = _fit(_cointegrated())
        assert payload["coint_rank"] >= 1
        assert payload["rank_selection"]["mode"] == "auto"
        assert payload["rank_selection"]["selected_rank"] == payload["coint_rank"]
        assert payload["rank_selection"]["signif"] == 0.05
        assert payload["rank_selection"]["det_order"] == 0  # deterministic="ci"

    def test_auto_rank_zero_is_honest_error_without_var_fallback(self):
        with pytest.raises(ValueError, match="[Кк]оинтеграци"):
            _fit(_independent_walks())

    def test_fixed_rank_bypasses_rank_test(self):
        payload = _fit(_independent_walks(), params={"coint_rank": 1})
        assert payload["rank_selection"]["mode"] == "fixed"
        assert payload["coint_rank"] == 1

    def test_det_order_follows_deterministic_terms(self):
        payload = _fit(_cointegrated(), params={"deterministic": "n"})
        assert payload["rank_selection"]["det_order"] == -1
        payload = _fit(_cointegrated(), params={"deterministic": "li"})
        assert payload["rank_selection"]["det_order"] == 1


class TestNativeVectorForecast:
    """VECMResults.predict -- нативный векторный прогноз с интервалами."""

    def test_payload_shapes_and_keys(self):
        payload = _fit(_cointegrated(), horizon=5)
        assert payload["forecast"].shape == (5, 2)
        assert payload["lower"].shape == (5, 2)
        assert payload["upper"].shape == (5, 2)
        assert np.isfinite(payload["forecast"]).all()
        assert np.all(payload["lower"] <= payload["forecast"] + 1e-12)
        assert np.all(payload["forecast"] <= payload["upper"] + 1e-12)
        assert payload["series_names"] == ("__target__", "b")
        for key in ("k_ar_diff", "coint_rank", "rank_selection",
                    "deterministic_terms", "alpha", "nobs",
                    "coefficient_matrices", "in_sample_residuals",
                    "deterministic"):
            assert key in payload, key
        assert payload["deterministic"] is True  # OLS-детерминизм реестра

    def test_var_rep_blocks_counted_by_k_ar_diff(self):
        payload = _fit(_cointegrated(), params={"k_ar_diff": 2})
        blocks = payload["coefficient_matrices"]
        assert len(blocks) == 3  # VAR(k_ar_diff+1) в уровнях
        assert all(block.shape == (2, 2) for block in blocks)

    def test_cross_equation_link_is_native(self):
        """Ошибка коррекции: возмущение spread меняет прогноз TARGET-ряда.

        Фиксированный ранг изолирует механизм ECT от чувствительности
        ранг-теста к грубому возмущению хвоста выборки."""
        matrix = _cointegrated()
        base = _fit(matrix, horizon=5, params={"coint_rank": 1})
        perturbed = matrix.copy()
        perturbed[-3:, 1] += 10.0  # сдвиг y2 при неизменном y1
        shifted = _fit(perturbed, horizon=5, params={"coint_rank": 1})
        assert not np.allclose(base["forecast"][:, 0], shifted["forecast"][:, 0])

    def test_alpha_widens_intervals(self):
        wide = _fit(_cointegrated(), params={"alpha": 0.01})
        narrow = _fit(_cointegrated(), params={"alpha": 0.10})
        assert np.all(
            (wide["upper"] - wide["lower"]) >= (narrow["upper"] - narrow["lower"]) - 1e-9
        )

    def test_determinism_bitwise(self):
        first = _fit(_cointegrated())
        second = _fit(_cointegrated(), random_state=7)
        assert np.array_equal(first["forecast"], second["forecast"])
        assert np.array_equal(first["in_sample_residuals"], second["in_sample_residuals"])

    def test_in_sample_residuals_shape(self):
        payload = _fit(_cointegrated(), params={"k_ar_diff": 2})
        resid = payload["in_sample_residuals"]
        assert resid.ndim == 2 and resid.shape[1] == 2
        assert resid.shape[0] == payload["nobs"]


class TestLegacySyntheticEndpoint:
    """Одиночный synthetic-эндпоинт честно отказывает (как VAR Task 132)."""

    def test_run_vecm_backtest_refuses_single_series(self):
        with pytest.raises(ValueError, match="не менее 2"):
            run_vecm_backtest([float(v) for v in np.arange(40.0)], 0.8, 12)
