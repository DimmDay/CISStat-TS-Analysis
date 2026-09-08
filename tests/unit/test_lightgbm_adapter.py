"""Task 129 -- unit-тесты LightGBM адаптера (recursive supervised ML).

Проверяются:
- переиспользование общего рекурсивного ядра Task 127 (_supervised_recursion):
  каузальность supervised-матрицы, warm-up, выравненность known-колонок;
- bounded params LightGBM (n_estimators/num_leaves/learning_rate/
  min_data_in_leaf/lambda_l2/feature_fraction/n_lags) -- fail-closed;
- детерминизм (fixed seed) и отсутствие скрытой стохастичности при полном
  сэмплировании (разные seed -- одинаковый прогноз), при feature_fraction<1
  seed реально влияет на прогноз (проводка random_state до бустера);
- prediction intervals через quantile regression (objective="quantile",
  alpha=0.1/0.9): lower <= point <= upper, честная ширина на шумных данных;
- период-2 закрытая форма [1,2,1] с машинной точностью (детерминированно
  ловит stale-history/off-by-one рекурсии);
- feature importance (gain) НОРМАЛИЗОВАН адаптером: нативный
  booster.feature_importance("gain") возвращает сырые суммы гейнов --
  контракт платформы требует сумму 1.0; привязка к ТОЧНОЙ fold-матрице
  (bind_feature_importance, oracle-отрицательный контроль);
- регрессорный канал future_known/static: A/B-дивергенция + fail-closed.
"""
from __future__ import annotations

import math

import pytest

from apps.api.feature_plan import (
    KIND_DIFFERENCE,
    KIND_LAG,
    KIND_ROLLING,
    ROLE_HISTORIC,
    RecursiveFeatureState,
    bind_feature_importance,
)
from apps.api.model_impls._supervised_recursion import (
    MIN_USABLE_ROWS,
    supervised_matrix,
)
from apps.api.model_impls.lightgbm import (
    DEFAULT_N_LAGS,
    PARAM_BOUNDS,
    lgb_feature_specs,
    validate_lgb_params,
    _lgb_fit_predict,
)


def _y(n: int = 40) -> list[float]:
    return [
        50.0 + 0.7 * t + 5.0 * math.sin(2.0 * math.pi * t / 8.0)
        for t in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Feature-спеки и общее ядро
# ══════════════════════════════════════════════════════════════════════════════

class TestLgbFeatureSpecs:
    def test_specs_cover_lags_rolling_and_difference_with_prefix(self):
        specs = lgb_feature_specs(n_lags=3)
        assert set(specs) == {
            "lgb_lag_1", "lgb_lag_2", "lgb_lag_3",
            "lgb_roll_mean", "lgb_roll_std", "lgb_diff_1",
        }
        assert specs["lgb_lag_2"].kind == KIND_LAG
        assert specs["lgb_lag_2"].role == ROLE_HISTORIC
        assert int(specs["lgb_lag_2"].lookback) == 2
        assert specs["lgb_roll_mean"].kind == KIND_ROLLING
        assert int(specs["lgb_roll_mean"].lookback) == 3
        assert str(specs["lgb_roll_mean"].params["statistic"]) == "mean"
        assert specs["lgb_diff_1"].kind == KIND_DIFFERENCE
        assert int(specs["lgb_diff_1"].lookback) == 2

    def test_shared_core_matrix_is_causal_with_warmup(self):
        y = [10.0, 12.0, 14.0, 18.0, 20.0, 25.0, 30.0, 28.0, 31.0, 35.0, 38.0, 41.0]
        columns, rows, target, warmup = supervised_matrix(
            y, known={}, specs=lgb_feature_specs(n_lags=3),
        )
        assert warmup == 3
        assert len(rows) == len(y) - warmup == len(target)
        assert (rows[0][0], rows[0][1], rows[0][2]) == (14.0, 12.0, 10.0)
        assert rows[0][3] == pytest.approx((10.0 + 12.0 + 14.0) / 3)
        assert target[0] == pytest.approx(18.0)

    def test_known_columns_are_aligned_and_sorted(self):
        y = _y(20)
        known = {
            "zeta": [1.0] * len(y),
            "alpha": [2.0] * len(y),
        }
        columns, rows, _target, warmup = supervised_matrix(
            y, known=known, specs=lgb_feature_specs(n_lags=2),
        )
        assert columns[len(lgb_feature_specs(2)):] == ["alpha", "zeta"]
        assert rows[0][-1] == pytest.approx(known["zeta"][warmup])

    def test_min_usable_rows_is_shared_across_ml_family(self):
        assert MIN_USABLE_ROWS == 8

    def test_insufficient_history_fails_closed(self):
        with pytest.raises(ValueError, match="истор"):
            supervised_matrix(
                [1.0, 2.0, 3.0], known={}, specs=lgb_feature_specs(n_lags=2),
            )


# ══════════════════════════════════════════════════════════════════════════════
# Bounded params (fail-closed)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateLgbParams:
    def test_defaults_are_valid_and_normalized(self):
        params = validate_lgb_params({})
        assert params["n_estimators"] == 200
        assert params["num_leaves"] == 31
        assert params["learning_rate"] == pytest.approx(0.1)
        assert params["min_data_in_leaf"] == 20
        assert params["lambda_l2"] == pytest.approx(0.0)
        assert params["feature_fraction"] == pytest.approx(1.0)
        assert params["n_lags"] == DEFAULT_N_LAGS

    def test_valid_params_pass_through(self):
        params = validate_lgb_params({
            "n_estimators": 50, "num_leaves": 15, "learning_rate": 0.3,
            "min_data_in_leaf": 5, "lambda_l2": 0.5, "feature_fraction": 0.8,
            "n_lags": 3,
        })
        assert params["n_estimators"] == 50
        assert params["num_leaves"] == 15
        assert params["learning_rate"] == pytest.approx(0.3)
        assert params["min_data_in_leaf"] == 5
        assert params["lambda_l2"] == pytest.approx(0.5)
        assert params["feature_fraction"] == pytest.approx(0.8)
        assert params["n_lags"] == 3

    @pytest.mark.parametrize("override", [
        {"n_estimators": 5}, {"n_estimators": 1001},
        {"num_leaves": 1}, {"num_leaves": 257},
        {"learning_rate": 0.0005}, {"learning_rate": 1.5},
        {"min_data_in_leaf": 0}, {"min_data_in_leaf": 101},
        {"lambda_l2": -0.1}, {"lambda_l2": 1001.0},
        {"feature_fraction": 0.05}, {"feature_fraction": 1.01},
        {"n_lags": 0}, {"n_lags": 33},
        {"n_estimators": 50.5}, {"n_lags": "many"}, {"learning_rate": "fast"},
        {"num_leaves": True}, {"feature_fraction": False},
    ])
    def test_out_of_bounds_params_fail_closed(self, override):
        with pytest.raises(ValueError):
            validate_lgb_params(override)

    def test_unknown_params_are_ignored(self):
        params = validate_lgb_params({
            "tbats_seasonal_periods": [7, 365], "n_lags": 2,
            "changepoint_prior_scale": 0.5, "max_depth": 6,
        })
        assert params["n_lags"] == 2

    def test_bounds_are_within_shared_n_lags_contract(self):
        assert PARAM_BOUNDS["n_lags"] == (1, 32)


# ══════════════════════════════════════════════════════════════════════════════
# _lgb_fit_predict: рекурсия, детерминизм, интервалы, importance
# ══════════════════════════════════════════════════════════════════════════════

class TestLgbFitPredictHappyPath:
    def test_forecast_is_deterministic_for_fixed_seed(self):
        y = _y(48)
        first = _lgb_fit_predict(y, 6, params={"n_estimators": 40, "n_lags": 3}, random_state=42)
        second = _lgb_fit_predict(y, 6, params={"n_estimators": 40, "n_lags": 3}, random_state=42)
        assert first["forecast"] == second["forecast"]
        assert first["lower"] == second["lower"]
        assert first["upper"] == second["upper"]
        assert first["feature_importance_lineage"]["matrix_hash"] == (
            second["feature_importance_lineage"]["matrix_hash"]
        )

    def test_full_sampling_has_no_hidden_stochasticity(self):
        """feature_fraction=1.0, bagging выключен: бустер детерминирован
        независимо от seed.  Честное доказательство отсутствия скрытой
        случайности; при feature_fraction<1 seed реально доходит до бустера
        (следующий тест).
        """
        y = _y(48)
        by_seed = [
            _lgb_fit_predict(y, 4, params={"n_estimators": 30, "n_lags": 2}, random_state=seed)
            for seed in (42, 7, 2026)
        ]
        assert by_seed[0]["forecast"] == by_seed[1]["forecast"] == by_seed[2]["forecast"]

    def test_seed_reaches_the_booster_when_sampling_is_stochastic(self):
        y = _y(48)
        first = _lgb_fit_predict(
            y, 4,
            params={"n_estimators": 40, "n_lags": 2, "feature_fraction": 0.6},
            random_state=42,
        )
        second = _lgb_fit_predict(
            y, 4,
            params={"n_estimators": 40, "n_lags": 2, "feature_fraction": 0.6},
            random_state=7,
        )
        assert first["forecast"] != second["forecast"]

    def test_forecast_shape_and_intervals_contain_point(self):
        y = _y(48)
        payload = _lgb_fit_predict(y, 5, params={"n_estimators": 40, "n_lags": 3}, random_state=42)
        assert len(payload["forecast"]) == len(payload["lower"]) == len(payload["upper"]) == 5
        for point, lower, upper in zip(
            payload["forecast"], payload["lower"], payload["upper"], strict=True,
        ):
            assert math.isfinite(point)
            assert lower <= point <= upper
        # Quantile-регрессия на шумных данных даёт нетривиальную ширину
        # хотя бы на одном шаге (иначе интервалы вырождаются в точку).
        assert any(lower < upper for lower, upper in zip(payload["lower"], payload["upper"]))

    def test_recursive_period_two_continuation_is_exact(self):
        """Период-2 (y_t = y_{t-2}): замкнутая форма [1,2,1] с машинной точностью.

        Детерминированно ловит stale-history/off-by-one рекурсии: шаг 2 даёт 2
        только если шаг 1 положил свой прогноз в историю (peek -> predict ->
        push).  learning_rate=1.0 + min_data_in_leaf=1: первый бустинг-раунд
        (с boost_from_average) достигает нулевых остатков на чистых листьях.
        """
        y = [1.0, 2.0] * 6
        payload = _lgb_fit_predict(
            y, 3,
            params={
                "n_estimators": 30, "num_leaves": 8, "learning_rate": 1.0,
                "min_data_in_leaf": 1, "lambda_l2": 0.0, "n_lags": 2,
            },
            random_state=42,
        )
        assert payload["forecast"] == pytest.approx([1.0, 2.0, 1.0], abs=1e-9)

    def test_forecast_stays_within_training_target_range(self):
        """Честное свойство бустинга: деревья не экстраполируют за пределы train."""
        y = [16.0 * (0.5 ** t) for t in range(20)]
        payload = _lgb_fit_predict(
            y, 4,
            params={"n_estimators": 30, "num_leaves": 8, "learning_rate": 0.5, "n_lags": 2},
            random_state=42,
        )
        assert min(payload["forecast"]) >= min(y) - 1e-9
        assert max(payload["forecast"]) <= max(y) + 1e-9

    def test_known_regressor_channel_reaches_the_model(self):
        """future_known-регрессор доходит до fit/predict: A/B-дивергенция.

        y = driver + детерминированный джиттер (циклы 13 и 7 взаимно просты,
        поэтому y_t невосстановим из y_{t-1}): лаги почти не несут информации
        о БУДУЩЕМ, driver -- единственный информативный признак, поэтому
        разные future_features обязаны давать разные прогнозы.  Потеря
        канала -- побайтовое совпадение.  (Замечание: на чистом y =
        driver со взаимно-однозначным 13-циклом лаг-признаки объясняют
        таргет целиком и leaf-wise бустинг не доходит до
        данных, а не канала.)
        """
        driver = [((7 * t) % 13) * 10.0 / 13 for t in range(40)]
        eps = [0.3 * ((3 * t) % 7) / 7.0 for t in range(40)]
        y = [d + e for d, e in zip(driver, eps)]
        # min_data_in_leaf=1: конфигурация обязана дать дереву ёмкость
        # расщепляться по значениям регрессора.
        run = lambda future: _lgb_fit_predict(
            y, 3,
            train_features={"driver": driver}, future_features={"driver": future},
            params={"n_estimators": 40, "num_leaves": 15, "min_data_in_leaf": 1, "n_lags": 1},
            random_state=42,
        )["forecast"]
        forecast_a = run([driver[0], driver[7], driver[11]])
        forecast_b = run([driver[5], driver[3], driver[9]])
        assert forecast_a != forecast_b
        bare = _lgb_fit_predict(
            y, 3,
            params={"n_estimators": 40, "num_leaves": 15, "min_data_in_leaf": 1, "n_lags": 1},
            random_state=42,
        )["forecast"]
        assert bare != forecast_a

    def test_feature_importance_is_normalized_and_bound_to_exact_matrix(self):
        y = _y(48)
        train_features = {"driver": [float(index) for index in range(len(y))]}
        future_features = {"driver": [48.0, 49.0, 50.0]}
        payload = _lgb_fit_predict(
            y, 3,
            train_features=train_features, future_features=future_features,
            params={"n_estimators": 40, "n_lags": 3}, random_state=42,
        )
        lineage = payload["feature_importance_lineage"]
        records = payload["feature_importances"]
        assert lineage["adapter_id"] == "lightgbm-native"
        assert len(lineage["matrix_hash"]) == 64
        assert set(lineage["columns"]) == set(lineage["future_known_columns"]) | {
            "lgb_lag_1", "lgb_lag_2", "lgb_lag_3",
            "lgb_roll_mean", "lgb_roll_std", "lgb_diff_1",
        }
        names = {record["feature_name"] for record in records}
        assert names == set(lineage["columns"])
        total = sum(record["importance"] for record in records)
        # Нативный feature_importance("gain") LightGBM возвращает СЫРЫЕ суммы
        # гейнов -- адаптер обязан нормализовать к сумме 1.0 (контракт
        # платформы, отличие от XGBoost с его нормализованным
        # feature_importances_).
        assert total == pytest.approx(1.0, abs=1e-9)
        assert all(record["importance"] >= 0.0 for record in records)
        bound = bind_feature_importance(lineage, records)
        assert bound["matrix_hash"] == lineage["matrix_hash"]
        with pytest.raises(Exception, match="не входит в колонки"):
            bind_feature_importance(
                lineage, [{"feature_name": "oracle_column", "importance": 1.0}],
            )


# ══════════════════════════════════════════════════════════════════════════════
# _lgb_fit_predict: fail-closed контракт
# ══════════════════════════════════════════════════════════════════════════════

class TestLgbFitPredictFailClosed:
    def test_nan_target_rejected(self):
        with pytest.raises(ValueError, match="NaN/Inf"):
            _lgb_fit_predict([1.0, math.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                              9.0, 10.0, 11.0, 12.0], 2,
                             params={"n_lags": 2}, random_state=42)

    def test_future_without_train_regressors_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="симметрично"):
            _lgb_fit_predict(y, 2, future_features={"x": [1.0, 2.0]},
                             params={"n_lags": 2}, random_state=42)

    def test_train_without_future_regressors_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="horizon"):
            _lgb_fit_predict(y, 2, train_features={"x": [1.0] * len(y)},
                             params={"n_lags": 2}, random_state=42)

    def test_regressor_key_mismatch_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="расходятся"):
            _lgb_fit_predict(
                y, 2,
                train_features={"x": [1.0] * len(y)}, future_features={"y": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_regressor_length_mismatch_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="не равна"):
            _lgb_fit_predict(
                y, 2,
                train_features={"x": [1.0] * (len(y) - 1)}, future_features={"x": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_nan_regressor_rejected(self):
        y = _y(24)
        train = [1.0] * len(y)
        train[5] = math.nan
        with pytest.raises(ValueError, match="NaN/Inf"):
            _lgb_fit_predict(
                y, 2,
                train_features={"x": train}, future_features={"x": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_insufficient_train_history_rejected(self):
        y = _y(9)  # n_lags=4 -> usable = 9-4 = 5 < 8
        with pytest.raises(ValueError, match="истор"):
            _lgb_fit_predict(y, 2, params={"n_lags": 4}, random_state=42)

    def test_zero_horizon_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="horizon"):
            _lgb_fit_predict(y, 0, params={"n_lags": 2}, random_state=42)
