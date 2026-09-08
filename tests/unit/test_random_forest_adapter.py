"""Task 127 -- unit-тесты Random Forest адаптера (recursive supervised ML).

Проверяются:
- каузальность supervised-матрицы: признак в точке p использует только y<p;
- warm-up дроп и симметричная выравненность known-колонок (future_known/static);
- рекурсивный прогноз через RecursiveFeatureState: шаг h+1 строится из
  прогнозов модели, замкнутая форма авторегрессии воспроизводится точно;
- аддитивный peek/push-контракт RecursiveFeatureState (Task 127: runtime-
  потребитель рекурсивного контракта Task 126);
- детерминированность при фиксированном random_state;
- prediction intervals по деревьям: lower <= point <= upper;
- feature importance привязан к точной fold-матрице (bind_feature_importance);
- регрессорный канал future_known/static: симметрия, fail-closed валидация;
- bounded params: выход за границы -- ошибка fold'а, не тихая деградация.
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
from apps.api.model_impls.random_forest import (
    DEFAULT_N_LAGS,
    PARAM_BOUNDS,
    rf_feature_specs,
    supervised_matrix,
    validate_rf_params,
    _rf_fit_predict,
)


def _y(n: int = 40) -> list[float]:
    return [
        50.0 + 0.7 * t + 5.0 * math.sin(2.0 * math.pi * t / 8.0)
        for t in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Feature-спеки адаптера
# ══════════════════════════════════════════════════════════════════════════════

class TestRfFeatureSpecs:
    def test_specs_cover_lags_rolling_and_difference(self):
        specs = rf_feature_specs(n_lags=3)
        assert set(specs) == {
            "rf_lag_1", "rf_lag_2", "rf_lag_3",
            "rf_roll_mean", "rf_roll_std", "rf_diff_1",
        }
        assert specs["rf_lag_2"].kind == KIND_LAG
        assert specs["rf_lag_2"].role == ROLE_HISTORIC
        assert int(specs["rf_lag_2"].lookback) == 2
        assert specs["rf_roll_mean"].kind == KIND_ROLLING
        assert int(specs["rf_roll_mean"].lookback) == 3
        assert str(specs["rf_roll_mean"].params["statistic"]) == "mean"
        assert specs["rf_diff_1"].kind == KIND_DIFFERENCE
        assert int(specs["rf_diff_1"].lookback) == 2

    def test_max_lookback_is_n_lags(self):
        specs = rf_feature_specs(n_lags=5)
        assert max(int(spec.lookback) for spec in specs.values()) == 5

    def test_n_lags_is_bounded(self):
        assert 1 <= int(PARAM_BOUNDS["n_lags"][0]) <= int(PARAM_BOUNDS["n_lags"][1]) <= 32
        assert DEFAULT_N_LAGS <= PARAM_BOUNDS["n_lags"][1]


# ══════════════════════════════════════════════════════════════════════════════
# Supervised-матрица: каузальность и warm-up
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisedMatrix:
    def test_rows_are_causal_and_warmup_is_dropped(self):
        y = [10.0, 12.0, 14.0, 18.0, 20.0, 25.0, 30.0, 28.0, 31.0, 35.0, 38.0, 41.0]
        specs = rf_feature_specs(n_lags=3)
        columns, rows, target, warmup = supervised_matrix(y, known={}, specs=specs)
        assert warmup == 3
        assert columns == [
            "rf_lag_1", "rf_lag_2", "rf_lag_3", "rf_roll_mean", "rf_roll_std", "rf_diff_1",
        ]
        assert len(rows) == len(y) - warmup == len(target)
        # Первая usable-строка -- target в позиции 3 (y=18), признаки только из y<3.
        assert target[0] == pytest.approx(18.0)
        lag_1, lag_2, lag_3 = rows[0][0], rows[0][1], rows[0][2]
        assert (lag_1, lag_2, lag_3) == (14.0, 12.0, 10.0)
        assert rows[0][3] == pytest.approx((10.0 + 12.0 + 14.0) / 3)
        # ddof=0 -- та же семантика, что и у FoldFeatureMatrixBuilder/RecursiveFeatureState.
        window = [10.0, 12.0, 14.0]
        mean = sum(window) / 3
        variance = sum((value - mean) ** 2 for value in window) / 3
        assert rows[0][4] == pytest.approx(math.sqrt(variance))
        assert rows[0][5] == pytest.approx(14.0 - 12.0)

    def test_known_columns_are_aligned_after_warmup(self):
        y = _y(20)
        known = {"driver": [float(index) * 2 for index in range(len(y))]}
        specs = rf_feature_specs(n_lags=2)
        columns, rows, target, warmup = supervised_matrix(
            y, known=known, specs=specs,
        )
        assert columns[-1] == "driver"
        assert warmup == 2
        assert len(rows) == len(y) - warmup
        # Known-колонка обрезается на тот же warm-up, что и lag-признаки.
        assert rows[0][-1] == pytest.approx(known["driver"][warmup])
        assert rows[-1][-1] == pytest.approx(known["driver"][-1])

    def test_known_columns_are_sorted_deterministically(self):
        y = _y(16)
        known = {
            "zeta": [1.0] * len(y),
            "alpha": [2.0] * len(y),
            "mid": [3.0] * len(y),
        }
        specs = rf_feature_specs(n_lags=2)
        columns, _rows, _target, _warmup = supervised_matrix(
            y, known=known, specs=specs,
        )
        known_part = columns[len(specs):]
        assert known_part == ["alpha", "mid", "zeta"]

    def test_insufficient_history_fails_closed(self):
        y = [1.0, 2.0, 3.0]
        specs = rf_feature_specs(n_lags=2)
        with pytest.raises(ValueError, match="истор"):
            supervised_matrix(y, known={}, specs=specs)


# ══════════════════════════════════════════════════════════════════════════════
# RecursiveFeatureState peek/push: runtime-контракт рекурсии
# ══════════════════════════════════════════════════════════════════════════════

class TestRecursivePeekPush:
    @staticmethod
    def _state(history: list[float]) -> RecursiveFeatureState:
        specs = rf_feature_specs(n_lags=3)
        return RecursiveFeatureState(
            history=history, columns=list(specs), specs=specs,
        )

    def test_peek_row_does_not_mutate_history(self):
        state = self._state([1.0, 2.0, 3.0, 4.0])
        before = state.history()
        row = state.peek_row()
        assert row[0] == 4.0  # rf_lag_1
        assert state.history() == before

    def test_push_appends_exactly_once(self):
        state = self._state([1.0, 2.0, 3.0, 4.0])
        state.push(5.0)
        assert state.history() == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert state.peek_row()[0] == 5.0

    def test_next_row_equals_peek_then_push(self):
        state_a = self._state([1.0, 2.0, 3.0, 4.0])
        state_b = self._state([1.0, 2.0, 3.0, 4.0])
        composed = state_a.peek_row()
        state_a.push(9.0)
        via_next = state_b.next_row(prediction=9.0)
        assert composed == via_next
        assert state_a.history() == state_b.history()

    def test_recursive_loop_reproduces_closed_form(self):
        """Полный рекурсивный цикл: peek -> predict -> push, без off-by-one."""
        y_train = [16.0 * (0.5 ** t) for t in range(12)]
        state = self._state(y_train)
        history_pushes: list[float] = []
        # Идеальная авторегрессия y_t = 0.5*y_{t-1}: "модель" для теста.
        for _step in range(4):
            row = state.peek_row()
            prediction = 0.5 * row[0]
            state.push(prediction)
            history_pushes.append(prediction)
        assert state.history()[:len(y_train)] == y_train
        assert state.history()[len(y_train):] == history_pushes


# ══════════════════════════════════════════════════════════════════════════════
# Bounded params (fail-closed)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateRfParams:
    def test_defaults_are_valid_and_normalized(self):
        params = validate_rf_params({})
        assert params["n_estimators"] == 200
        assert params["max_depth"] is None
        assert params["min_samples_leaf"] == 1
        assert params["n_lags"] == DEFAULT_N_LAGS

    def test_valid_params_pass_through(self):
        params = validate_rf_params({
            "n_estimators": 50, "max_depth": 6,
            "min_samples_leaf": 3, "n_lags": 3,
        })
        assert params == {
            "n_estimators": 50, "max_depth": 6,
            "min_samples_leaf": 3, "n_lags": 3,
        }

    @pytest.mark.parametrize("override", [
        {"n_estimators": 5}, {"n_estimators": 1001},
        {"max_depth": 0}, {"max_depth": 65},
        {"min_samples_leaf": 0}, {"min_samples_leaf": 101},
        {"n_lags": 0}, {"n_lags": 33},
        {"n_estimators": 50.5}, {"n_lags": "many"},
    ])
    def test_out_of_bounds_params_fail_closed(self, override):
        with pytest.raises(ValueError):
            validate_rf_params(override)

    def test_unknown_params_are_ignored(self):
        # Соглашение платформы: адаптеры игнорируют чужие ключи
        # (в params всегда приходит tbats_seasonal_periods и т.п.).
        params = validate_rf_params({"tbats_seasonal_periods": [7, 365], "n_lags": 2})
        assert params["n_lags"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# _rf_fit_predict: рекурсия, детерминизм, интервалы, importance
# ══════════════════════════════════════════════════════════════════════════════

class TestRfFitPredictHappyPath:
    def test_forecast_is_deterministic_for_fixed_seed(self):
        y = _y(48)
        first = _rf_fit_predict(y, 6, params={"n_estimators": 50, "n_lags": 3}, random_state=42)
        second = _rf_fit_predict(y, 6, params={"n_estimators": 50, "n_lags": 3}, random_state=42)
        assert first["forecast"] == second["forecast"]
        assert first["lower"] == second["lower"]
        assert first["upper"] == second["upper"]
        assert first["feature_importance_lineage"]["matrix_hash"] == (
            second["feature_importance_lineage"]["matrix_hash"]
        )

    def test_different_seed_changes_the_forecast(self):
        y = _y(48)
        first = _rf_fit_predict(y, 6, params={"n_estimators": 50, "n_lags": 3}, random_state=42)
        second = _rf_fit_predict(y, 6, params={"n_estimators": 50, "n_lags": 3}, random_state=7)
        assert first["forecast"] != second["forecast"]

    def test_forecast_shape_and_intervals_contain_point(self):
        y = _y(48)
        payload = _rf_fit_predict(y, 5, params={"n_estimators": 60, "n_lags": 3}, random_state=42)
        assert len(payload["forecast"]) == len(payload["lower"]) == len(payload["upper"]) == 5
        for point, lower, upper in zip(
            payload["forecast"], payload["lower"], payload["upper"], strict=True,
        ):
            assert math.isfinite(point)
            assert lower <= point <= upper

    def test_recursive_period_two_continuation_is_exact(self):
        """Рекурсия доказывается рядом с периодом 2 (y_t = y_{t-2}).

        Значения ряда совпадают с тренировочными feature-строками, поэтому
        деревья предсказывают ТОЧНО (чистые листья), и замкнутая форма
        [1, 2, 1] проверяется с машинной точностью.  Одновременно тест
        детерминированно ловит stale-history/off-by-one баги рекурсии:
        шаг 2 даёт 2 только если шаг 1 ПОЛОЖИЛ свой прогноз в историю
        (без push шаг 2 построил бы строку от y_T=2 и предсказал 1).
        """
        y = [1.0, 2.0] * 6  # хвост [..., 1, 2]
        payload = _rf_fit_predict(
            y, 3,
            params={"n_estimators": 30, "max_depth": None, "min_samples_leaf": 1, "n_lags": 2},
            random_state=42,
        )
        assert payload["forecast"] == pytest.approx([1.0, 2.0, 1.0], abs=1e-12)

    def test_forecast_stays_within_training_target_range(self):
        """Честное свойство RF: деревья не экстраполируют за пределы train.

        Геометрически затухающий ряд уходит ниже минимального train-значения;
        рекурсивный прогноз обязан остаться в диапазоне тренировочных таргетов
        (средние листьев) -- это ловит как уход рекурсии в бесконечность,
        так и случайную утечку фактов теста.
        """
        y = [16.0 * (0.5 ** t) for t in range(20)]
        payload = _rf_fit_predict(
            y, 4,
            params={"n_estimators": 30, "max_depth": None, "min_samples_leaf": 1, "n_lags": 2},
            random_state=42,
        )
        assert min(payload["forecast"]) >= min(y) - 1e-12
        assert max(payload["forecast"]) <= max(y) + 1e-12

    def test_known_regressor_channel_reaches_the_model(self):
        """future_known-регрессор доходит до fit/predict: A/B-дивергенция.

        y = driver (детерминированная псевдослучайная последовательность):
        лаги y не несут информации о БУДУЩЕМ driver, поэтому две прогонки с
        одинаковым train, но разными future_features обязаны давать разные
        прогнозы.  Если адаптер теряет канал -- прогнозы совпадают байт в
        байт, тест краснеет.  Точные значения прогнозов здесь не проверяются
        сознательно: деревья piecewise-constant, и точный лист для новой
        строки зависит от порядка сплитов -- это свойство RF, а не бага.
        """
        driver = [((7 * t) % 13) * 10.0 / 13 for t in range(40)]
        y = list(driver)  # y_t = driver_t -- только регрессор объясняет target
        run = lambda future: _rf_fit_predict(
            y, 3,
            train_features={"driver": driver}, future_features={"driver": future},
            params={"n_estimators": 60, "max_depth": None, "min_samples_leaf": 1, "n_lags": 1},
            random_state=42,
        )["forecast"]
        forecast_a = run([driver[0], driver[7], driver[11]])
        forecast_b = run([driver[5], driver[3], driver[9]])
        assert forecast_a != forecast_b
        # И без канала -- третий результат: канал влияет на прогноз.
        bare = _rf_fit_predict(
            y, 3,
            params={"n_estimators": 60, "max_depth": None, "min_samples_leaf": 1, "n_lags": 1},
            random_state=42,
        )["forecast"]
        assert bare != forecast_a

    def test_feature_importance_is_bound_to_exact_matrix(self):
        y = _y(48)
        train_features = {"driver": [float(index) for index in range(len(y))]}
        future_features = {"driver": [48.0, 49.0, 50.0]}
        payload = _rf_fit_predict(
            y, 3,
            train_features=train_features, future_features=future_features,
            params={"n_estimators": 40, "n_lags": 3}, random_state=42,
        )
        lineage = payload["feature_importance_lineage"]
        records = payload["feature_importances"]
        assert lineage["adapter_id"] == "sklearn-random-forest"
        assert len(lineage["matrix_hash"]) == 64
        assert set(lineage["columns"]) == set(lineage["future_known_columns"]) | {
            "rf_lag_1", "rf_lag_2", "rf_lag_3", "rf_roll_mean", "rf_roll_std", "rf_diff_1",
        }
        names = {record["feature_name"] for record in records}
        assert names == set(lineage["columns"])
        total = sum(record["importance"] for record in records)
        assert total == pytest.approx(1.0, abs=1e-9)
        # Oracle-защита Task 126: важность валидируется против колонок
        # ТОЧНОЙ матрицы, на которой она посчитана.
        bound = bind_feature_importance(lineage, records)
        assert bound["matrix_hash"] == lineage["matrix_hash"]
        with pytest.raises(Exception, match="не входит в колонки"):
            bind_feature_importance(lineage, [{"feature_name": "oracle_column", "importance": 1.0}])


# ══════════════════════════════════════════════════════════════════════════════
# _rf_fit_predict: fail-closed контракт
# ══════════════════════════════════════════════════════════════════════════════

class TestRfFitPredictFailClosed:
    def test_nan_target_rejected(self):
        with pytest.raises(ValueError, match="NaN/Inf"):
            _rf_fit_predict([1.0, math.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                             9.0, 10.0, 11.0, 12.0], 2,
                            params={"n_lags": 2}, random_state=42)

    def test_future_without_train_regressors_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="симметрично"):
            _rf_fit_predict(y, 2, future_features={"x": [1.0, 2.0]},
                            params={"n_lags": 2}, random_state=42)

    def test_train_without_future_regressors_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="horizon"):
            _rf_fit_predict(y, 2, train_features={"x": [1.0] * len(y)},
                            params={"n_lags": 2}, random_state=42)

    def test_regressor_key_mismatch_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="расходятся"):
            _rf_fit_predict(
                y, 2,
                train_features={"x": [1.0] * len(y)}, future_features={"y": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_regressor_length_mismatch_rejected(self):
        y = _y(24)
        with pytest.raises(ValueError, match="не равна"):
            _rf_fit_predict(
                y, 2,
                train_features={"x": [1.0] * (len(y) - 1)}, future_features={"x": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_nan_regressor_rejected(self):
        y = _y(24)
        train = [1.0] * len(y)
        train[5] = math.nan
        with pytest.raises(ValueError, match="NaN/Inf"):
            _rf_fit_predict(
                y, 2,
                train_features={"x": train}, future_features={"x": [1.0, 2.0]},
                params={"n_lags": 2}, random_state=42,
            )

    def test_insufficient_train_history_rejected(self):
        y = _y(9)  # n_lags=4 -> usable = 9-4 = 5 < 8
        with pytest.raises(ValueError, match="истор"):
            _rf_fit_predict(y, 2, params={"n_lags": 4}, random_state=42)
