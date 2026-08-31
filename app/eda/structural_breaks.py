"""Комплементарная диагностика структурных сдвигов временного ряда.

CUSUM отвечает на глобальный вопрос о стабильности параметров линейного
тренда, PELT локализует несколько изменений уровня/наклона, а Chow описывает
локальный выигрыш разбиения в уже найденных точках. Последний расчёт является
послевыборочной диагностикой, а не независимым подтверждающим тестом.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


MIN_STRUCTURAL_OBSERVATIONS = 60
MAX_STRUCTURAL_BREAKS = 10
MAX_PELT_GRID_POINTS = 250
SENSITIVITY_MULTIPLIERS = (0.75, 1.0, 2.0, 3.0, 5.0)


def _base_result(
    series: pd.Series,
    reason: str,
    alpha: float,
    min_segment: int,
    penalty_multiplier: float,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    return {
        "applicable": False,
        "reason": reason,
        "n_observations": int(len(numeric) - missing_count),
        "missing_count": missing_count,
        "min_observations": MIN_STRUCTURAL_OBSERVATIONS,
        "alpha": float(alpha),
        "requested_min_segment": int(min_segment),
        "min_segment": int(min_segment),
        "requested_penalty_multiplier": float(penalty_multiplier),
        "penalty_multiplier": float(penalty_multiplier),
        "penalty_value": None,
        "max_breaks": MAX_STRUCTURAL_BREAKS,
        "jump": 1,
        "model": "piecewise_linear",
        "status": "not_applicable",
        "break_count": 0,
        "supported_count": 0,
        "cusum": {
            "statistic": None,
            "p_value": None,
            "reject_stability": None,
            "critical_values": {},
        },
        "candidates": [],
        "segments": [],
        "fitted": [],
        "cusum_path": [],
        "sensitivity": [],
        "recommendation": reason,
        "recommendations": [],
        "warnings": [],
    }


def structural_breaks_not_applicable(
    series: pd.Series,
    reason: str,
    alpha: float = 0.05,
    min_segment: int = 20,
    penalty_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Возвращает единый контракт для отказа адаптера временной оси."""
    return _base_result(series, reason, alpha, min_segment, penalty_multiplier)


def _ols(values: np.ndarray, start: int, end: int) -> tuple[np.ndarray, float]:
    index = np.arange(start, end, dtype=float)
    design = np.column_stack((np.ones(end - start), index))
    coefficients, _, _, _ = np.linalg.lstsq(design, values[start:end], rcond=None)
    residuals = values[start:end] - design @ coefficients
    return coefficients, float(np.dot(residuals, residuals))


def _holm_adjust(items: list[dict[str, Any]], alpha: float) -> None:
    ranked = sorted(enumerate(items), key=lambda pair: float(pair[1]["p_value"]))
    running_max = 0.0
    count = len(ranked)
    for rank, (index, item) in enumerate(ranked):
        adjusted = min(1.0, (count - rank) * float(item["p_value"]))
        running_max = max(running_max, adjusted)
        items[index]["adjusted_p_value"] = float(running_max)
        items[index]["chow_reject_stability"] = bool(running_max < alpha)


def _cusum(values: np.ndarray, alpha: float) -> tuple[dict[str, Any], list[dict[str, float]]]:
    from statsmodels.stats.diagnostic import breaks_cusumolsresid

    coefficients, _ = _ols(values, 0, len(values))
    design = np.column_stack((np.ones(len(values)), np.arange(len(values), dtype=float)))
    residuals = values - design @ coefficients
    statistic, p_value, critical = breaks_cusumolsresid(residuals, ddof=2)
    critical_values = {
        f"{int(level)}%": float(value)
        for level, value in critical
    }
    critical_5 = critical_values.get("5%", 1.36)
    denominator = float(np.sqrt(np.dot(residuals, residuals)))
    path = np.cumsum(residuals) / denominator if denominator > 0 else np.zeros(len(values))
    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "reject_stability": bool(p_value < alpha),
        "critical_values": critical_values,
    }, [
        {
            "index": int(index),
            "value": float(value),
            "upper": float(critical_5),
            "lower": float(-critical_5),
        }
        for index, value in enumerate(path)
    ]


def _pelt_breaks(
    signal: np.ndarray,
    min_segment: int,
    jump: int,
    penalty: float,
) -> list[int]:
    import ruptures as rpt

    algorithm = rpt.Pelt(model="linear", min_size=min_segment, jump=jump).fit(signal)
    return [int(index) for index in algorithm.predict(pen=penalty) if index < len(signal)]


def _candidate_metrics(
    values: np.ndarray,
    boundaries: list[int],
    global_std: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for position, breakpoint in enumerate(boundaries[1:-1], start=1):
        start = boundaries[position - 1]
        end = boundaries[position + 1]
        left_coefficients, left_rss = _ols(values, start, breakpoint)
        right_coefficients, right_rss = _ols(values, breakpoint, end)
        _, pooled_rss = _ols(values, start, end)
        split_rss = left_rss + right_rss
        numerator = max(0.0, pooled_rss - split_rss) / 2.0
        denominator_df = end - start - 4
        denominator = split_rss / denominator_df if denominator_df > 0 else np.nan
        statistic = float(numerator / denominator) if denominator > 0 else 0.0
        p_value = float(stats.f.sf(statistic, 2, denominator_df)) if denominator_df > 0 else 1.0
        left_level = float(left_coefficients[0] + left_coefficients[1] * breakpoint)
        right_level = float(right_coefficients[0] + right_coefficients[1] * breakpoint)
        candidates.append({
            "rank": 0,
            "index": int(breakpoint),
            "level_change": float(right_level - left_level),
            "standardized_level_change": float((right_level - left_level) / global_std),
            "slope_before": float(left_coefficients[1]),
            "slope_after": float(right_coefficients[1]),
            "slope_change": float(right_coefficients[1] - left_coefficients[1]),
            "rss_gain": float(max(0.0, pooled_rss - split_rss) / max(pooled_rss, np.finfo(float).eps)),
            "chow_statistic": statistic,
            "p_value": p_value,
            "adjusted_p_value": None,
            "chow_reject_stability": None,
            "stability_support": 0.0,
            "supported": False,
        })
    order = sorted(range(len(candidates)), key=lambda index: candidates[index]["rss_gain"], reverse=True)
    for rank, index in enumerate(order, start=1):
        candidates[index]["rank"] = rank
    return candidates


def _segments_and_fitted(
    values: np.ndarray,
    boundaries: list[int],
) -> tuple[list[dict[str, Any]], list[float]]:
    segments: list[dict[str, Any]] = []
    fitted = np.empty(len(values), dtype=float)
    for segment_id, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:]), start=1):
        coefficients, _ = _ols(values, start, end)
        index = np.arange(start, end, dtype=float)
        fitted[start:end] = coefficients[0] + coefficients[1] * index
        segment_values = values[start:end]
        segments.append({
            "id": segment_id,
            "start_index": int(start),
            "end_index": int(end - 1),
            "n_observations": int(end - start),
            "mean": float(np.mean(segment_values)),
            "std": float(np.std(segment_values, ddof=1)),
            "slope": float(coefficients[1]),
        })
    return segments, fitted.tolist()


def analyze_structural_breaks(
    series: pd.Series,
    alpha: float = 0.05,
    min_segment: int = 20,
    penalty_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Ищет изменения уровня и линейного тренда без изменения исходного ряда."""
    if not 0 < alpha < 1:
        raise ValueError("Уровень значимости alpha должен быть между 0 и 1")
    if min_segment < 5:
        raise ValueError("Минимальная длина сегмента должна быть не меньше 5")
    if penalty_multiplier <= 0:
        raise ValueError("Множитель штрафа PELT должен быть положительным")

    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    if missing_count:
        return _base_result(
            numeric,
            "В ряду есть пропуски или бесконечные значения. Сначала завершите предобработку; удаление точек изменило бы положение сдвигов.",
            alpha,
            min_segment,
            penalty_multiplier,
        )
    if len(numeric) < MIN_STRUCTURAL_OBSERVATIONS:
        return _base_result(
            numeric,
            f"Недостаточно наблюдений: нужно не менее {MIN_STRUCTURAL_OBSERVATIONS}, доступно {len(numeric)}.",
            alpha,
            min_segment,
            penalty_multiplier,
        )
    if 2 * min_segment > len(numeric):
        return _base_result(
            numeric,
            "Выбранная минимальная длина не позволяет сформировать два полных сегмента.",
            alpha,
            min_segment,
            penalty_multiplier,
        )
    if float(numeric.max() - numeric.min()) == 0.0:
        return _base_result(
            numeric,
            "Ряд константный: изменения уровня и наклона не определяются.",
            alpha,
            min_segment,
            penalty_multiplier,
        )

    try:
        import ruptures  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        return _base_result(
            numeric,
            "PELT недоступен: серверная зависимость ruptures не установлена.",
            alpha,
            min_segment,
            penalty_multiplier,
        )

    values = numeric.to_numpy(dtype=float)
    n = len(values)
    _, global_rss = _ols(values, 0, n)
    numerical_rss_floor = (
        np.finfo(float).eps
        * n
        * max(float(np.var(values)), 1.0)
        * 100.0
    )
    if global_rss <= numerical_rss_floor:
        return _base_result(
            numeric,
            "Ряд практически точно описывается одной линейной функцией: остаточная дисперсия слишком мала для устойчивых CUSUM и Chow-расчётов.",
            alpha,
            min_segment,
            penalty_multiplier,
        )
    residual_variance = max(global_rss / max(1, n - 2), np.finfo(float).eps)
    base_penalty = 2.0 * residual_variance * np.log(n)
    normalized_time = np.linspace(-1.0, 1.0, n)
    signal = np.column_stack((values, np.ones(n), normalized_time))
    jump = max(1, int(np.ceil(n / MAX_PELT_GRID_POINTS)))

    effective_multiplier = float(penalty_multiplier)
    breaks: list[int] = []
    for _ in range(10):
        breaks = _pelt_breaks(
            signal,
            min_segment,
            jump,
            float(base_penalty * effective_multiplier),
        )
        if len(breaks) <= MAX_STRUCTURAL_BREAKS:
            break
        effective_multiplier *= 1.5

    sensitivity_multipliers = sorted(set((
        *SENSITIVITY_MULTIPLIERS,
        float(penalty_multiplier),
        float(effective_multiplier),
    )))
    sensitivity: list[dict[str, Any]] = []
    sensitivity_breaks: dict[float, list[int]] = {}
    for multiplier in sensitivity_multipliers:
        detected = _pelt_breaks(
            signal,
            min_segment,
            jump,
            float(base_penalty * multiplier),
        )
        sensitivity_breaks[multiplier] = detected
        sensitivity.extend({"penalty_multiplier": float(multiplier), "index": int(index)} for index in detected)

    cusum, cusum_path = _cusum(values, alpha)
    boundaries = [0, *breaks, n]
    candidates = _candidate_metrics(values, boundaries, float(np.std(values, ddof=1)))
    if candidates:
        _holm_adjust(candidates, alpha)
    tolerance = max(jump, min_segment // 5)
    for candidate in candidates:
        support_count = sum(
            any(abs(index - candidate["index"]) <= tolerance for index in detected)
            for detected in sensitivity_breaks.values()
        )
        candidate["stability_support"] = float(support_count / len(sensitivity_multipliers))
        candidate["supported"] = bool(
            candidate["chow_reject_stability"]
            and candidate["stability_support"] >= 0.6
            and cusum["reject_stability"]
        )

    segments, fitted = _segments_and_fitted(values, boundaries)
    supported_count = sum(item["supported"] for item in candidates)
    if supported_count:
        status = "breaks_detected"
        strongest = min(
            (item for item in candidates if item["supported"]),
            key=lambda item: item["rank"],
        )
        recommendation = (
            f"Обнаружено устойчивых кандидатов: {supported_count}. Наиболее выраженный — наблюдение {strongest['index']}. "
            "Сравните обучение на последнем режиме с моделью, допускающей изменение параметров."
        )
    elif breaks:
        status = "candidates_only"
        recommendation = (
            "PELT нашёл кандидатов, но согласование CUSUM, локальной Chow-диагностики и чувствительности недостаточно. "
            "Не делите обучающую выборку автоматически."
        )
    elif cusum["reject_stability"]:
        status = "global_instability"
        recommendation = (
            "CUSUM указывает на общую нестабильность, но PELT не локализовал устойчивую точку при выбранном штрафе. "
            "Проверьте чувствительность, сезонность и нелинейную динамику."
        )
    else:
        status = "stable"
        recommendation = (
            "CUSUM не отвергает стабильность линейного тренда, а PELT не выделяет режимы при выбранных параметрах. "
            "Это отсутствие обнаруженного сигнала, а не доказательство неизменности процесса."
        )

    warnings_out = [
        "Локальная Chow-диагностика рассчитана после выбора точек PELT на тех же данных; её p-значения послевыборочные и не являются независимым подтверждением.",
        "CUSUM и Chow предполагают корректную линейную спецификацию и устойчивые ошибки. При автокорреляции или сезонности интерпретируйте p-значения как диагностические.",
        "PELT ищет изменения уровня и линейного наклона. Сдвиги только дисперсии требуют отдельной диагностики волатильности.",
    ]
    if jump > 1:
        warnings_out.append(
            f"Для ограничения времени вычисления PELT проверяет кандидатов с шагом {jump} наблюдений; точность локализации соответствует этому шагу."
        )
    if effective_multiplier != float(penalty_multiplier):
        warnings_out.append(
            f"Чтобы ограничить число точек значением {MAX_STRUCTURAL_BREAKS}, множитель штрафа автоматически повышен до {effective_multiplier:.3g}."
        )

    return {
        "applicable": True,
        "reason": None,
        "n_observations": n,
        "missing_count": 0,
        "min_observations": MIN_STRUCTURAL_OBSERVATIONS,
        "alpha": float(alpha),
        "requested_min_segment": int(min_segment),
        "min_segment": int(min_segment),
        "requested_penalty_multiplier": float(penalty_multiplier),
        "penalty_multiplier": effective_multiplier,
        "penalty_value": float(base_penalty * effective_multiplier),
        "max_breaks": MAX_STRUCTURAL_BREAKS,
        "jump": jump,
        "model": "piecewise_linear",
        "status": status,
        "break_count": len(candidates),
        "supported_count": int(supported_count),
        "cusum": cusum,
        "candidates": candidates,
        "segments": segments,
        "fitted": fitted,
        "cusum_path": cusum_path,
        "sensitivity": sensitivity,
        "recommendation": recommendation,
        "recommendations": [
            recommendation,
            "Сопоставьте найденные даты с изменениями методологии, политики, рынка или источника данных.",
            "Проверьте устойчивость результата на временных срезах и на остатках модели после удаления сезонности.",
        ],
        "warnings": warnings_out,
    }
