"""Многокритериальный скрининг признаков для временного ряда."""
from __future__ import annotations

from inspect import signature
from typing import Any, Iterable
import warnings

import numpy as np
import pandas as pd

from app.eda.correlation import find_significant_correlations


MIN_FEATURE_SELECTION_OBSERVATIONS = 30
HIGH_PAIR_CORRELATION = 0.85


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _empty_result(df: pd.DataFrame, target: str, reason: str, alpha: float,
                  max_lag: int, correlation_threshold: float,
                  vif_threshold: float, difference_order: int) -> dict[str, Any]:
    numeric_target = pd.to_numeric(df[target], errors="coerce") if target in df else pd.Series(dtype=float)
    finite_count = int(np.isfinite(numeric_target.to_numpy(dtype=float)).sum()) if len(numeric_target) else 0
    return {
        "column": target, "applicable": False, "reason": reason,
        "n_observations": finite_count, "min_observations": MIN_FEATURE_SELECTION_OBSERVATIONS,
        "numeric_candidates": 0, "analyzed_features": 0, "alpha": float(alpha),
        "requested_max_lag": int(max_lag), "max_lag": 0,
        "correlation_threshold": float(correlation_threshold), "vif_threshold": float(vif_threshold),
        "difference_order": int(difference_order), "granger_n_observations": max(0, finite_count - difference_order),
        "granger_available": False, "granger_reason": reason, "correlation_matrix": [],
        "features": [], "granger": [], "high_correlation_pairs": [], "excluded_features": [],
        "kept_features": [], "review_features": [], "low_signal_features": [],
        "recommendation": reason, "recommendations": [], "warnings": [],
    }


def _vif_values(frame: pd.DataFrame, columns: list[str]) -> dict[str, tuple[float | None, bool]]:
    if len(columns) == 1:
        return {columns[0]: (1.0, False)}
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    matrix = frame[columns].to_numpy(dtype=float)
    standardized = (matrix - matrix.mean(axis=0)) / matrix.std(axis=0, ddof=0)
    supports_standardize = "standardize" in signature(variance_inflation_factor).parameters
    result: dict[str, tuple[float | None, bool]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for index, name in enumerate(columns):
            try:
                value = float(variance_inflation_factor(standardized, index, standardize=False)) if supports_standardize else float(variance_inflation_factor(standardized, index))
            except (ValueError, FloatingPointError, np.linalg.LinAlgError, ZeroDivisionError):
                value = float("inf")
            infinite = not np.isfinite(value) or value >= 1e12
            result[name] = (None if infinite else value, infinite)
    return result


def _granger_tests(frame: pd.DataFrame, target: str, candidates: list[str],
                   max_lag: int, alpha: float) -> tuple[list[dict[str, Any]], set[str]]:
    from statsmodels.stats.multitest import multipletests
    from statsmodels.tsa.stattools import grangercausalitytests

    raw: list[dict[str, Any]] = []
    failed: set[str] = set()
    supports_verbose = "verbose" in signature(grangercausalitytests).parameters
    for feature in candidates:
        kwargs: dict[str, Any] = {"maxlag": max_lag, "addconst": True}
        if supports_verbose:
            kwargs["verbose"] = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = grangercausalitytests(frame[[target, feature]].to_numpy(dtype=float), **kwargs)
            for lag in range(1, max_lag + 1):
                statistic, p_value = map(_finite, result[lag][0]["ssr_ftest"][:2])
                if statistic is None or p_value is None:
                    raise ValueError("non-finite Granger result")
                raw.append({"feature": feature, "lag": lag, "f_statistic": statistic, "p_value": p_value})
        except (ValueError, FloatingPointError, np.linalg.LinAlgError, ZeroDivisionError):
            failed.add(feature)
    if not raw:
        return [], failed
    rejected, adjusted, _, _ = multipletests([item["p_value"] for item in raw], alpha=alpha, method="fdr_bh")
    return [{**item, "adjusted_p_value": float(adjusted[i]), "significant": bool(rejected[i])} for i, item in enumerate(raw)], failed


def analyze_feature_selection(
    df: pd.DataFrame, target: str, alpha: float = 0.05, max_lag: int = 3,
    correlation_threshold: float = 0.3, vif_threshold: float = 5.0,
    difference_order: int = 0, *, excluded_columns: Iterable[str] = (),
    granger_enabled: bool = True, granger_disabled_reason: str | None = None,
) -> dict[str, Any]:
    """Строит read-only профиль кандидатов относительно выбранной цели."""
    if not 0 < alpha < 1 or max_lag < 1 or not 0 < correlation_threshold <= 1 or vif_threshold < 1 or difference_order not in (0, 1):
        raise ValueError("Некорректные параметры отбора признаков")
    if target not in df.columns:
        return _empty_result(df, target, f"Целевая колонка «{target}» отсутствует.", alpha, max_lag, correlation_threshold, vif_threshold, difference_order)
    target_values = pd.to_numeric(df[target], errors="coerce").replace([np.inf, -np.inf], np.nan)
    if target_values.isna().any():
        return _empty_result(df, target, "В целевом ряду есть пропуски или бесконечные значения. Сначала завершите предобработку.", alpha, max_lag, correlation_threshold, vif_threshold, difference_order)
    if len(target_values) < MIN_FEATURE_SELECTION_OBSERVATIONS:
        return _empty_result(df, target, f"Недостаточно наблюдений: нужно не менее {MIN_FEATURE_SELECTION_OBSERVATIONS}.", alpha, max_lag, correlation_threshold, vif_threshold, difference_order)
    if float(np.ptp(target_values.to_numpy(dtype=float))) <= np.finfo(float).eps:
        return _empty_result(df, target, "Целевой ряд константный.", alpha, max_lag, correlation_threshold, vif_threshold, difference_order)

    excluded_set = {str(name) for name in excluded_columns}
    numeric_candidates = [str(name) for name in df.select_dtypes(include="number").columns if str(name) != target and str(name) not in excluded_set]
    excluded_features: list[dict[str, str]] = []
    candidates: list[str] = []
    work = pd.DataFrame({target: target_values.astype(float).reset_index(drop=True)})
    for name in numeric_candidates:
        values = pd.to_numeric(df[name], errors="coerce").replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
        if values.isna().any():
            excluded_features.append({"name": name, "reason": "Исключён: есть пропуски или бесконечные значения."})
        elif float(np.ptp(values.to_numpy(dtype=float))) <= np.finfo(float).eps:
            excluded_features.append({"name": name, "reason": "Исключён как константный признак."})
        else:
            candidates.append(name)
            work[name] = values.astype(float)
    if not candidates:
        result = _empty_result(df, target, "Нужен хотя бы один корректный числовой предиктор.", alpha, max_lag, correlation_threshold, vif_threshold, difference_order)
        result.update(numeric_candidates=len(numeric_candidates), excluded_features=excluded_features)
        return result

    all_columns = [target, *candidates]
    pearson_matrix = work[all_columns].corr(method="pearson")
    spearman_matrix = work[all_columns].corr(method="spearman")
    matrix = [{"row": row, "column": col, "pearson": float(pearson_matrix.loc[row, col]), "spearman": float(spearman_matrix.loc[row, col])} for row in all_columns for col in all_columns]
    high_pairs = []
    for item in find_significant_correlations(work, candidates, threshold=HIGH_PAIR_CORRELATION):
        names = str(item["pair"]).split(" ↔ ", 1)
        if len(names) == 2:
            high_pairs.append({"first": names[0], "second": names[1], "correlation": float(item["val"])})

    vif = _vif_values(work, candidates)
    granger_frame = work[all_columns].diff().iloc[1:].reset_index(drop=True) if difference_order == 1 else work[all_columns]
    granger_n = len(granger_frame)
    actual_max_lag = min(max_lag, max(1, (granger_n - 5) // 3))
    granger, failed = _granger_tests(granger_frame, target, candidates, actual_max_lag, alpha) if granger_enabled else ([], set())
    by_feature = {name: [item for item in granger if item["feature"] == name] for name in candidates}
    features: list[dict[str, Any]] = []
    for name in candidates:
        tests = by_feature[name]
        best = min(tests, key=lambda item: item["adjusted_p_value"]) if tests else None
        pearson, spearman = float(pearson_matrix.loc[target, name]), float(spearman_matrix.loc[target, name])
        signal = max(abs(pearson), abs(spearman)) >= correlation_threshold or bool(best and best["significant"])
        vif_value, vif_infinite = vif[name]
        collinear = vif_infinite or bool(vif_value is not None and vif_value >= vif_threshold)
        decision = "keep" if signal and not collinear else "review" if signal else "low_signal"
        reasons = {"keep": "Есть сигнал без превышения VIF; подтвердите временной валидацией.", "review": "Есть сигнал, но мультиколлинеарность требует проверки.", "low_signal": "Устойчивый сигнал не найден; исключение допустимо только после временной валидации."}
        others = [abs(float(pearson_matrix.loc[name, other])) for other in candidates if other != name]
        features.append({"name": name, "n_observations": len(work), "pearson": pearson, "spearman": spearman,
                         "vif": vif_value, "vif_infinite": vif_infinite, "max_abs_predictor_correlation": max(others) if others else 0.0,
                         "granger_available": bool(tests) and name not in failed, "best_granger_lag": int(best["lag"]) if best else None,
                         "granger_p_value": float(best["p_value"]) if best else None, "granger_adjusted_p_value": float(best["adjusted_p_value"]) if best else None,
                         "granger_significant": bool(best["significant"]) if best else False, "decision": decision, "decision_reason": reasons[decision]})
    order = {"keep": 0, "review": 1, "low_signal": 2}
    features.sort(key=lambda item: (order[item["decision"]], -max(abs(item["pearson"]), abs(item["spearman"])), item["name"]))
    kept = [x["name"] for x in features if x["decision"] == "keep"]
    review = [x["name"] for x in features if x["decision"] == "review"]
    low = [x["name"] for x in features if x["decision"] == "low_signal"]
    recommendation = f"Предварительно сохранить: {len(kept)}; проверить: {len(review)}; слабый сигнал: {len(low)}."
    warnings_out = ["Granger показывает опережающую предсказательность, а не доказанную причинность.", "VIF не является универсальной командой удалить признак."]
    if difference_order == 1:
        warnings_out.append("Granger рассчитан на первых разностях; коинтеграция не оценивается.")
    if not granger_enabled and granger_disabled_reason:
        warnings_out.append(granger_disabled_reason)
    if failed:
        warnings_out.append("Granger не удалось оценить для: " + ", ".join(sorted(failed)) + ".")
    return {"column": target, "applicable": True, "reason": None, "n_observations": len(work),
            "min_observations": MIN_FEATURE_SELECTION_OBSERVATIONS, "numeric_candidates": len(numeric_candidates),
            "analyzed_features": len(features), "alpha": float(alpha), "requested_max_lag": int(max_lag), "max_lag": actual_max_lag,
            "correlation_threshold": float(correlation_threshold), "vif_threshold": float(vif_threshold), "difference_order": int(difference_order),
            "granger_n_observations": granger_n, "granger_available": bool(granger_enabled), "granger_reason": granger_disabled_reason,
            "correlation_matrix": matrix, "features": features, "granger": granger, "high_correlation_pairs": high_pairs,
            "excluded_features": excluded_features, "kept_features": kept, "review_features": review, "low_signal_features": low,
            "recommendation": recommendation, "recommendations": [recommendation, "Подтвердите shortlist expanding-window валидацией."],
            "warnings": list(dict.fromkeys(warnings_out))}
