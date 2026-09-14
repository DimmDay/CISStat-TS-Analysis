# scripts/cert_forecast_oracles.py
# Независимый сертификационный аудит Task FORECAST-1: оракул-тесты
# на СОБСТВЕННЫХ данных аудитора (DGPs не пересекаются с фикстурами коллеги).
# Оракул = свойство с известным точным ответом из теории (точечный прогноз
# baseline-моделей, ширина/симметрия интервалов, покрытие, инверсия цепочки).
from __future__ import annotations

import sys
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

from apps.api.final_fit import build_final_fit  # noqa: E402
from apps.api.forecasting import (  # noqa: E402
    ForecastingError,
    compute_forecast,
    compute_forecast_coverage,
    empirical_step_quantiles,
    forecast_anomaly_flags,
    future_date_labels,
)
from apps.api.forecasting_contract import resolve_forecast_alpha  # noqa: E402
from apps.api.model_execution import (  # noqa: E402
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionResult,
)

RESULTS: list[tuple[str, str, str]] = []


def check(oracle_id: str, description: str, fn) -> None:
    try:
        fn()
        RESULTS.append((oracle_id, "PASS", description))
        print(f"[PASS] {oracle_id}: {description}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((oracle_id, "FAIL", f"{description} :: {type(exc).__name__}: {exc}"))
        print(f"[FAIL] {oracle_id}: {description}")
        traceback.print_exc(limit=3)


# ── Собственные DGPs аудитора (не совпадают с фикстурами коллеги) ──


def dgp_white_noise(n: int = 240, sigma: float = 2.0, seed: int = 77031) -> pd.DataFrame:
    """DGP-B: y = 100 + iid N(0, sigma) -- известная дисперсия дляCoverage-оракула."""
    rng = np.random.default_rng(seed)
    y = 100.0 + rng.normal(0.0, sigma, n)
    return pd.DataFrame({
        "dt": pd.date_range("2021-03-05", periods=n, freq="D").astype(str),
        "y": y,
    })


def dgp_exact_linear(n: int = 150, slope: float = 5.0) -> pd.DataFrame:
    """DGP-C: детерминированная прямая -- drift-оракул точный до 1e-9."""
    t = np.arange(n, dtype=float)
    return pd.DataFrame({
        "dt": pd.date_range("2019-06-01", periods=n, freq="W").astype(str),
        "y": 12.0 + slope * t,
    })


def dgp_pure_seasonal(n: int = 120, period: int = 12) -> pd.DataFrame:
    """DGP-D: чистая синусоида без шума -- seasonal_naive-оракул точный."""
    t = np.arange(n, dtype=float)
    return pd.DataFrame({
        "dt": pd.date_range("2020-01-01", periods=n, freq="MS").astype(str),
        "y": 10.0 * np.sin(2.0 * np.pi * t / period),
    })


def dgp_exp_growth(n: int = 140, seed: int = 99017) -> pd.DataFrame:
    """DGP-A: мультипликативный рост -> log_difference-цепочка, асимметрия."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    y = 50.0 * np.exp(0.012 * t) + rng.normal(0, 0.4, n)
    return pd.DataFrame({
        "dt": pd.date_range("2017-02-01", periods=n, freq="MS").astype(str),
        "y": np.maximum(y, 1.0),
    })


def identity_fit(frame: pd.DataFrame):
    return build_final_fit(
        frame, target_column="y", date_column="dt",
        transformations={}, scaling_recipe={},
    )


def run_forecast(model_id: str, frame: pd.DataFrame, fit, horizon: int,
                 alpha: float = 0.05, oof=None, validated=None,
                 params=None, registry=None, random_state: int = 31337,
                 simulation_trajectories: int = 500):
    return compute_forecast(
        simulation_trajectories=simulation_trajectories,
        model_id=model_id, horizon=horizon,
        alpha_resolution=resolve_forecast_alpha(model_id, alpha, {}),
        final_fit=fit, seasonal_period=12, params=params or {},
        registry=registry or MODEL_EXECUTION_REGISTRY,
        history_values=fit.source_values, history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["dt"]), horizon),
        oof_predictions=oof or [], validated_horizon=validated,
        random_state=random_state,
    )


def make_oof(sigma: float, steps: dict[int, int], seed: int = 55019) -> list[dict]:
    """OOF-набор с известным N(0, sigma) остатком по каждому шагу."""
    rng = np.random.default_rng(seed)
    points: list[dict] = []
    for step, count in steps.items():
        residuals = rng.normal(0.0, sigma, count)
        for fold, residual in enumerate(residuals):
            points.append({
                "fold": fold, "horizon_step": step, "index": fold,
                "label": f"2025-{step:02d}", "actual": 100.0,
                "predicted": 100.0 - residual, "residual": residual,
            })
    return points


# ── O1: naive-оракул точки (точное равенство последнему уровню) ────


def o1_naive_point_oracle() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    computation = run_forecast("naive", frame, fit, horizon=8, oof=make_oof(2.0, {1: 30, 2: 30, 3: 30, 4: 30, 5: 30, 6: 30, 7: 30, 8: 30}))
    last = float(frame["y"].to_numpy()[-1])
    for point in computation.points:
        assert point["value"] == last, (
            f"naive forecast {point['value']} != последний уровень {last}"
        )


# ── O2: mean-оракул точки ─────────────────────────────────────────


def o2_mean_point_oracle() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    computation = run_forecast("mean", frame, fit, horizon=5, oof=make_oof(2.0, {1: 30, 2: 30, 3: 30, 4: 30, 5: 30}))
    expected = float(np.mean(frame["y"].to_numpy()))
    for point in computation.points:
        assert abs(point["value"] - expected) < 1e-9, (
            f"mean forecast {point['value']} != среднее {expected}"
        )


# ── O3: drift-оракул (точная линейная экстраполяция) ──────────────


def o3_drift_point_oracle() -> None:
    frame = dgp_exact_linear(slope=5.0)
    fit = identity_fit(frame)
    computation = run_forecast("drift", frame, fit, horizon=6, oof=make_oof(0.01, {1: 20, 2: 20, 3: 20, 4: 20, 5: 20, 6: 20}))
    values = frame["y"].to_numpy()
    n = len(values)
    slope = (values[-1] - values[0]) / (n - 1)
    for point in computation.points:
        expected = values[-1] + slope * point["step"]
        assert abs(point["value"] - expected) < 1e-8, (
            f"drift шаг {point['step']}: {point['value']} != {expected}"
        )


# ── O4: seasonal_naive-оракул (повтор последнего сезона) ──────────


def o4_seasonal_naive_point_oracle() -> None:
    frame = dgp_pure_seasonal()
    fit = identity_fit(frame)
    horizon = 15
    computation = run_forecast(
        "seasonal_naive", frame, fit, horizon=horizon,
        oof=make_oof(0.01, {s: 15 for s in range(1, 13)}),
    )
    values = frame["y"].to_numpy()
    m = 12
    for point in computation.points:
        expected = values[n - m + (point["step"] - 1) % m] if (n := len(values)) else None
        assert abs(point["value"] - expected) < 1e-8, (
            f"seasonal_naive шаг {point['step']}: {point['value']} != {expected}"
        )


# ── O5:containment-оракул для трёх методов на своих DGPs ──────────


def o5_interval_containment_all_methods() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    oof = make_oof(2.0, {s: 40 for s in range(1, 7)})
    for model_id, params in (("naive", {}), ("arima", {}), ("ets", {"trend": "add", "seasonal": None})):
        computation = run_forecast(model_id, frame, fit, horizon=6, oof=oof, validated=6, params=params)
        for point in computation.points:
            assert point["ci_lower"] < point["value"] < point["ci_upper"], (
                f"{model_id} шаг {point['step']}: границы не охватывают точку"
            )


# ── O6: alpha-монотонность ширины интервала (3 метода) ────────────


def o6_alpha_monotonicity() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    oof = make_oof(2.0, {s: 60 for s in range(1, 5)})
    for model_id, params in (("naive", {}), ("arima", {}), ("ets", {"trend": "add", "seasonal": None})):
        widths: dict[float, float] = {}
        for alpha in (0.01, 0.20, 0.40):
            computation = run_forecast(model_id, frame, fit, horizon=4, alpha=alpha, oof=oof, validated=4, params=params)
            widths[alpha] = float(np.mean([p["ci_upper"] - p["ci_lower"] for p in computation.points]))
        assert widths[0.01] > widths[0.20] > widths[0.40], (
            f"{model_id}: ширина не монотонна по alpha: {widths}"
        )


# ── O6b: симметрия симуляционного интервала на симметричном шуме ──


def o6b_simulation_symmetry() -> None:
    """На белом шуме квантильные границы симуляции обязаны быть симметричны
    относительно точки: |point-lower| ~= |upper-point| (alpha=0.20 -> q0.90/q0.10).
    Ловит подмену квантиля alpha/2 -> alpha (вилка мутанта: 0.84/1.28 сигма).
    3000 траекторий -- шум квантиля при дефолтных 500 ~ ±8-10% на границу."""
    frame = dgp_white_noise(n=300, seed=88121)
    fit = identity_fit(frame)
    computation = run_forecast(
        "ets", frame, fit, horizon=4, alpha=0.20,
        params={"trend": "add", "seasonal": None}, random_state=2026,
        simulation_trajectories=3000,
    )
    for point in computation.points:
        lower_gap = point["value"] - point["ci_lower"]
        upper_gap = point["ci_upper"] - point["value"]
        ratio = lower_gap / upper_gap if upper_gap > 0 else 99.0
        assert 0.90 <= ratio <= 1.10, (
            f"симуляция асимметрична на симметричном DGP: ratio={ratio:.3f}"
        )


# ── O7: MC-оракул покрытия эмпирического интервала ≈ номиналу ─────


def o7_coverage_approximates_nominal() -> None:
    sigma = 2.0
    oof = make_oof(sigma, {1: 400}, seed=61027)
    computation = compute_forecast_coverage(oof, 0.05)
    assert computation is not None
    # Номинал 95%: толеранс +-5 п.п. при 400 точках (SE ~ 1.1 п.п.).
    assert 0.90 <= computation <= 0.995, f"покрытие {computation} далеко от 0.95"


# ── O8: асимметрия интервала в исходной шкале (log_difference) ────


def o8_log_difference_asymmetry() -> None:
    """Экспоненциальный DGP через log_difference + fake-адаптер с симметричным
    transformed-интервалом: в исходной шкале верхний хвост длиннее нижнего."""
    frame = dgp_exp_growth()
    frame["y"] = frame["y"].abs() + 40.0
    transformations = {
        "y_logdiff": {
            "kind": "stationarity", "method": "log_difference",
            "seasonal_period": 12,
            "source_column": "y", "inverse_supported": True,
        },
    }
    fit = build_final_fit(
        frame, target_column="y_logdiff", date_column="dt",
        transformations=transformations, scaling_recipe={},
    )

    class _SymmetricAdapter:
        def execute(self, model_id, request):
            point = [float(request.target[-1])] * int(request.horizon)
            lower = [point[0] - 0.01] * int(request.horizon)
            upper = [point[0] + 0.01] * int(request.horizon)
            return ModelExecutionResult(
                forecast=point, lower_interval=lower, upper_interval=upper,
                metadata={"adapter": "symmetric-fake"},
            )

    computation = run_forecast(
        "lstm", frame, fit, horizon=3, alpha=0.05,
        registry=_SymmetricAdapter(),
    )
    # Точная теория: restore для log_difference -- exp(log(y_T) + cumsum(forecast)),
    # поэтому интервал ±d на КАЖДЫЙ диффен на шаге k аккумулируется в ±d*k:
    # ratio_k = (e^(d*k) - 1) / (1 - e^(-d*k)) -- верхний хвост длиннее.
    d = 0.01
    for i, point in enumerate(computation.points, start=1):
        upper_gap = point["ci_upper"] - point["value"]
        lower_gap = point["value"] - point["ci_lower"]
        ratio = upper_gap / lower_gap if lower_gap > 0 else 0.0
        expected_ratio = (float(np.exp(d * i)) - 1.0) / (1.0 - float(np.exp(-d * i)))
        assert upper_gap > lower_gap, (
            f"шаг {i}: верхний хвост {upper_gap} не длиннее нижнего {lower_gap}"
        )
        assert abs(ratio - expected_ratio) < 0.005, (
            f"шаг {i}: ratio {ratio:.6f} != теоретический {expected_ratio:.6f}"
        )


# ── O9: детерминизм симуляции на своём seed ───────────────────────


def o9_simulation_determinism() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    kwargs = dict(
        model_id="ets", horizon=5, alpha=0.05,
        params={"trend": "add", "seasonal": None}, random_state=60601,
    )
    first = run_forecast(frame=frame, fit=fit, **kwargs)
    second = run_forecast(frame=frame, fit=fit, **kwargs)
    assert [p["ci_lower"] for p in first.points] == [p["ci_lower"] for p in second.points]
    assert [p["ci_upper"] for p in first.points] == [p["ci_upper"] for p in second.points]


# ── O10: warning-оракулы горизонта (analytic vs empirical) ────────


def o10_horizon_warnings_distinction() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    analytic = run_forecast("arima", frame, fit, horizon=9, validated=4)
    assert any("превышает проверенный бэктестом" in w for w in analytic.warnings), (
        "analytic: отсутствует мягкое предупреждение о горизонте"
    )
    empirical = run_forecast(
        "naive", frame, fit, horizon=7, validated=4,
        oof=make_oof(2.0, {1: 25, 2: 25, 3: 25, 4: 25}),
    )
    assert any("консервативная" in w for w in empirical.warnings), (
        "empirical: отсутствует честный warning о консервативной оценке"
    )
    # Шаги 5..7 используют квантиль последнего валидированного шага (4).
    for i in (4, 5, 6):
        assert empirical.points[i]["ci_lower"] == empirical.points[3]["ci_lower"]
        assert empirical.points[i]["ci_upper"] == empirical.points[3]["ci_upper"]


# ── O11: оракул аномальных прогнозных точек ───────────────────────


def o11_anomaly_flags() -> None:
    history = list(np.linspace(200.0, 210.0, 80))
    assert forecast_anomaly_flags(history, [211.0, 260.0]) == [False, True]
    assert forecast_anomaly_flags(history, [211.0, 212.5]) == [False, False]


# ── O12: формула coverage -- ручной подсчёт на малом наборе ───────


def o12_coverage_manual_formula() -> None:
    oof = [
        {"horizon_step": 1, "actual": 10.0, "predicted": 9.0, "residual": 1.0},
        {"horizon_step": 1, "actual": 10.0, "predicted": 11.5, "residual": -1.5},
        {"horizon_step": 1, "actual": 10.0, "predicted": 13.0, "residual": -3.0},
        {"horizon_step": 2, "actual": 10.0, "predicted": 10.4, "residual": -0.4},
    ]
    alpha = 0.5  # квантили 0.25/0.75
    low, high = empirical_step_quantiles(oof, alpha)
    # шаг 1: отсортированные [-3.0, -1.5, 1.0]; numpy linear interpolation:
    # q0.25 -> позиция 0.5 -> -2.25; q0.75 -> позиция 1.5 -> -0.25
    assert abs(low[1] - (-2.25)) < 1e-9, f"q0.25={low[1]}, ожидался -2.25"
    assert abs(high[1] - (-0.25)) < 1e-9, f"q0.75={high[1]}, ожидался -0.25"
    covered = sum(
        1 for p in oof
        if low[int(p["horizon_step"])] <= p["actual"] - p["predicted"] <= high[int(p["horizon_step"])]
    )
    expected = covered / len(oof)
    actual = compute_forecast_coverage(oof, alpha)
    assert actual == expected, f"coverage {actual} != ручной подсчёт {expected}"


# ── O13: эмпирические границы = точка + квантиль СВОЕГО шага ──────


def o13_empirical_bounds_exact_formula() -> None:
    frame = dgp_white_noise()
    fit = identity_fit(frame)
    residuals = {1: [-3.0, -1.0, 0.5, 1.0, 3.0], 2: [-7.0, -2.0, 1.0, 2.0, 6.0]}
    oof = []
    for step, values_ in residuals.items():
        for fold, residual in enumerate(values_):
            oof.append({"fold": fold, "horizon_step": step, "index": fold,
                        "label": f"2025-{step}", "actual": 100.0,
                        "predicted": 100.0 - residual, "residual": residual})
    computation = run_forecast("naive", frame, fit, horizon=2, alpha=0.20, oof=oof, validated=2)
    low, high = empirical_step_quantiles(oof, 0.20)
    last = float(frame["y"].to_numpy()[-1])
    for i, point in enumerate(computation.points, start=1):
        assert point["value"] == last
        assert abs(point["ci_lower"] - (last + low[i])) < 1e-9, (
            f"нижняя граница шага {i} не равна точка+q(alpha/2)"
        )
        assert abs(point["ci_upper"] - (last + high[i])) < 1e-9


# ── O14: паритет-гейт ловит дрейф зеркала (свой fake-реестр) ──────


def o14_parity_gate_catches_registry_drift() -> None:
    """Fake-реестр возвращает точку, расходящуюся с сопряжённым statsmodels-фитом
    на 1% -- паритет-гейт обязан отказать (ForecastingError), а не отдать
    прогноз с несогласованной точкой/границами."""
    frame = dgp_white_noise()
    fit = identity_fit(frame)

    class _DriftedRegistry:
        def execute(self, model_id, request):
            base = np.asarray([float(v) for v in request.target[-1:]] * int(request.horizon))
            return ModelExecutionResult(
                forecast=(base * 1.01).tolist(), metadata={"adapter": "drifted"},
            )

    try:
        run_forecast("arima", frame, fit, horizon=5, registry=_DriftedRegistry())
    except ForecastingError as exc:
        assert "Паритет" in str(exc) or "паритет" in str(exc).lower()
        return
    raise AssertionError("паритет-гейт пропустил расхождение реестра и фита")


# ── O15: future_date_labels -- календарный оракул ─────────────────


def o15_future_date_labels() -> None:
    # ME-сетка: Nov30, Dec31, Jan31, Feb28, Mar31 -> будущее Apr30, May31, Jun30
    monthly = pd.DatetimeIndex(pd.date_range("2024-11-30", periods=5, freq="ME"))
    labels = future_date_labels(monthly, 3)
    expected = [
        pd.Timestamp("2025-04-30").isoformat(),
        pd.Timestamp("2025-05-31").isoformat(),
        pd.Timestamp("2025-06-30").isoformat(),
    ]
    assert labels == expected, f"месячная сетка продолжена неверно: {labels}"
    irregular = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-07"])
    assert future_date_labels(irregular, 3) is None, "нерегулярная сетка обязана дать None"


# ── O16: _param_space_corners -- углы, дедуп, потолок ─────────────


def o16_param_space_corners() -> None:
    from apps.api.routers.forecasting_session import MAX_SENSITIVITY_COMBOS, _param_space_corners

    space = {"trend": ["add", "mul"], "seasonal": ["add"], "damped_trend": [True, False]}
    combos = _param_space_corners(space)
    assert len(combos) == 4, f"2x1x2=4 угла, получено {len(combos)}"
    assert {"trend": "add", "seasonal": "add", "damped_trend": True} in combos
    assert {"trend": "mul", "seasonal": "add", "damped_trend": False} in combos
    big = {f"axis_{i}": ["a", "b", "c"] for i in range(5)}  # 2^5 = 32 > 8
    assert len(_param_space_corners(big)) == MAX_SENSITIVITY_COMBOS


# ── O17: неизвестная/вне-scope модель -- честный отказ ────────────


def o17_non_eligible_model_fails_closed() -> None:
    from apps.api.forecasting_contract import interval_method_for_model

    for model_id in ("var", "garch", "deepar", "unknown_model"):
        try:
            interval_method_for_model(model_id)
        except ValueError:
            continue
        raise AssertionError(f"{model_id}: ожидался fail-closed ValueError")


def main() -> int:
    check("O1", "naive: точка = последний уровень (точное равенство)", o1_naive_point_oracle)
    check("O2", "mean: точка = среднее истории (1e-9)", o2_mean_point_oracle)
    check("O3", "drift: точная линейная экстраполяция на 6 шагов", o3_drift_point_oracle)
    check("O4", "seasonal_naive: точное сезонное повторение", o4_seasonal_naive_point_oracle)
    check("O5", "containment lower<point<upper для 3 методов", o5_interval_containment_all_methods)
    check("O6", "ширина интервала монотонна по alpha (3 метода)", o6_alpha_monotonicity)
    check("O6b", "симметрия симуляции на симметричном шуме (alpha=0.20)", o6b_simulation_symmetry)
    check("O7", "MC-покрытие эмпирического интервала ~= 0.95", o7_coverage_approximates_nominal)
    check("O8", "log_difference: асимметрия границ в исходной шкале", o8_log_difference_asymmetry)
    check("O9", "детерминизм симуляции при фиксированном seed", o9_simulation_determinism)
    check("O10", "разная строгость warning'ов: analytic мягкий / empirical консервативный", o10_horizon_warnings_distinction)
    check("O11", "аномалии: спайк ловится, спокойный прогноз нет", o11_anomaly_flags)
    check("O12", "coverage = ручная формула (квантили numpy)", o12_coverage_manual_formula)
    check("O13", "эмпирические границы = точка + квантиль своего шага", o13_empirical_bounds_exact_formula)
    check("O14", "паритет-гейт ловит дрейф fake-реестра (1%)", o14_parity_gate_catches_registry_drift)
    check("O15", "future_date_labels: продолжение ME-сетки / None для нерегулярной", o15_future_date_labels)
    check("O16", "_param_space_corners: углы 2x1x2, дедуп, потолок 8", o16_param_space_corners)
    check("O17", "var/garch/deepar/unknown -- честный fail-closed", o17_non_eligible_model_fails_closed)

    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    failed = len(RESULTS) - passed
    print(f"\n=== ORACLE SUMMARY: {passed} PASS / {failed} FAIL из {len(RESULTS)} ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
