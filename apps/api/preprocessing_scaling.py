"""API-адаптер остановки «Предобработка → Масштабирование»."""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np
import pandas as pd

from app.data.detectors import score_all_columns_as_date, smart_to_datetime
from app.preprocessing.scaling import SCALING_METHODS, fit_transform_scaling


DATE_CONFIDENCE_THRESHOLD = 0.7
SCALING_PREVIEW_POINTS = 240
SCALING_MATRIX_COLUMNS = 12


def _optional(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(result, 6) if np.isfinite(result) else None


def _signature(df: pd.DataFrame, columns: Sequence[str]) -> str:
    selected = list(columns)
    digest = hashlib.sha256()
    digest.update("\x1f".join(selected).encode("utf-8"))
    digest.update("\x1f".join(str(df[column].dtype) for column in selected).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(df[selected], index=True).to_numpy().tobytes())
    return digest.hexdigest()


def _date_like_columns(df: pd.DataFrame) -> set[str]:
    return {
        str(item["name"]) for item in score_all_columns_as_date(df)
        if float(item["score"]) >= DATE_CONFIDENCE_THRESHOLD
    }


def _outlier_pct(values: np.ndarray, q1: float, q3: float) -> float:
    iqr = q3 - q1
    if iqr <= 0:
        return 0.0
    mask = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
    return round(float(np.mean(mask) * 100), 4)


def _column_profiles(
    df: pd.DataFrame, target_column: str, generated: set[str],
) -> list[dict[str, Any]]:
    date_like = _date_like_columns(df)
    profiles: list[dict[str, Any]] = []
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_bool_dtype(series) or not pd.api.types.is_numeric_dtype(series):
            continue
        numeric = pd.to_numeric(series, errors="coerce")
        finite = numeric.replace([np.inf, -np.inf], np.nan)
        valid = finite.dropna().to_numpy(dtype=float)
        missing_count = int(finite.isna().sum())
        unique_count = int(finite.nunique(dropna=True))
        binary = unique_count <= 2 and set(finite.dropna().unique()).issubset({0, 1})
        constant = unique_count <= 1
        exclusion_reason: str | None = None
        if column in date_like:
            exclusion_reason = "временная/идентификационная ось"
        elif missing_count:
            exclusion_reason = f"пропуски или infinite: {missing_count}"
        elif constant:
            exclusion_reason = "константная колонка"
        eligible = exclusion_reason is None
        role = "target" if column == target_column else "generated" if column in generated else "source"
        if len(valid):
            q1, median, q3 = np.quantile(valid, [0.25, 0.5, 0.75])
            std = float(np.std(valid, ddof=0))
            iqr = float(q3 - q1)
            scale = std if std > 1e-12 else iqr if iqr > 1e-12 else float(np.ptp(valid))
            skewness = float(pd.Series(valid).skew()) if len(valid) >= 3 else 0.0
            values = {
                "minimum": _optional(np.min(valid)), "maximum": _optional(np.max(valid)),
                "mean": _optional(np.mean(valid)), "std": _optional(std),
                "median": _optional(median), "q1": _optional(q1), "q3": _optional(q3),
                "iqr": _optional(iqr), "outlier_pct": _outlier_pct(valid, float(q1), float(q3)),
                "skewness": _optional(skewness), "scale": _optional(scale),
            }
        else:
            values = {key: None for key in (
                "minimum", "maximum", "mean", "std", "median", "q1", "q3",
                "iqr", "outlier_pct", "skewness", "scale",
            )}
        already_bounded = bool(
            role == "generated" and values["minimum"] is not None and values["maximum"] is not None
            and float(values["minimum"]) >= -1.000001 and float(values["maximum"]) <= 1.000001
        )
        recommended = bool(
            eligible and not binary and not already_bounded and column != target_column
        )
        profiles.append({
            "name": str(column), "role": role, "dtype": str(series.dtype),
            "missing_count": missing_count, "unique_count": unique_count,
            "binary": binary, "constant": constant, "eligible": eligible,
            "recommended": recommended, "exclusion_reason": exclusion_reason,
            **values,
        })
    return profiles


def _labels(df: pd.DataFrame) -> list[str]:
    candidates = [
        item for item in score_all_columns_as_date(df)
        if float(item["score"]) >= DATE_CONFIDENCE_THRESHOLD
    ]
    if candidates:
        parsed = smart_to_datetime(df[str(candidates[0]["name"])])
        if not parsed.isna().any():
            return [pd.Timestamp(value).isoformat() for value in parsed]
    return [str(index + 1) for index in range(len(df))]


def _indices(size: int) -> np.ndarray:
    if size <= SCALING_PREVIEW_POINTS:
        return np.arange(size, dtype=int)
    return np.unique(np.linspace(0, size - 1, SCALING_PREVIEW_POINTS, dtype=int))


def _summary(values: np.ndarray) -> dict[str, float | None]:
    q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75])
    return {
        "minimum": _optional(np.min(values)), "maximum": _optional(np.max(values)),
        "mean": _optional(np.mean(values)), "std": _optional(np.std(values, ddof=0)),
        "median": _optional(median), "q1": _optional(q1), "q3": _optional(q3),
        "iqr": _optional(q3 - q1),
    }


def _max_correlation_delta(before: np.ndarray, after: np.ndarray) -> float:
    if before.shape[1] < 2:
        return 0.0
    corr_before = np.corrcoef(before, rowvar=False)
    corr_after = np.corrcoef(after, rowvar=False)
    delta = np.abs(corr_after - corr_before)
    return round(float(np.nanmax(delta)), 6)


METHOD_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "standard": {"label": "StandardScaler", "linear": True, "centers": "mean", "scales": "std", "outlier_robust": False, "bounded": False, "preserves_zero": False, "note": "Нулевая средняя и единичная дисперсия; чувствителен к выбросам."},
    "minmax": {"label": "MinMaxScaler", "linear": True, "centers": "minimum", "scales": "range", "outlier_robust": False, "bounded": True, "preserves_zero": False, "note": "Обучающий диапазон [0, 1]; будущие значения могут выйти за него."},
    "robust": {"label": "RobustScaler", "linear": True, "centers": "median", "scales": "IQR", "outlier_robust": True, "bounded": False, "preserves_zero": False, "note": "Медиана/IQR уменьшают влияние выбросов, но не удаляют их."},
    "maxabs": {"label": "MaxAbsScaler", "linear": True, "centers": "none", "scales": "max(abs)", "outlier_robust": False, "bounded": True, "preserves_zero": True, "note": "Не центрирует и сохраняет нули; полезен для разреженных признаков."},
    "quantile": {"label": "QuantileTransformer", "linear": False, "centers": "rank", "scales": "ECDF", "outlier_robust": True, "bounded": False, "preserves_zero": False, "note": "Нелинейно меняет распределение и может искажать корреляции/расстояния."},
}


def _method_comparison(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    if not columns:
        return [{**description, "method": method, "max_correlation_delta": 0.0} for method, description in METHOD_DESCRIPTIONS.items()]
    matrix = df[columns].to_numpy(dtype=float)
    result = []
    for method, description in METHOD_DESCRIPTIONS.items():
        transformed, _ = fit_transform_scaling(
            df, columns, method, n_quantiles=min(100, max(10, len(df))),
        )
        result.append({
            "method": method, **description,
            "max_correlation_delta": _max_correlation_delta(matrix, transformed.to_numpy()),
        })
    return result


def _visual_payloads(
    df: pd.DataFrame, columns: list[str], method: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not columns:
        return [], [], [], [], []
    transformed, _ = fit_transform_scaling(
        df, columns, method, n_quantiles=min(100, max(10, len(df))),
    )
    focus = columns[0]
    labels = _labels(df)
    preview = [{
        "x": labels[index], "original": _optional(df.iloc[index][focus]),
        "scaled": _optional(transformed.iloc[index][focus]),
    } for index in _indices(len(df))]

    ranges = []
    boxes = []
    for column in columns[:SCALING_MATRIX_COLUMNS]:
        before = df[column].to_numpy(dtype=float)
        after = transformed[column].to_numpy(dtype=float)
        scale_before = float(np.std(before, ddof=0))
        scale_after = float(np.std(after, ddof=0))
        ranges.append({
            "column": column, "scale_before": _optional(scale_before),
            "scale_after": _optional(scale_after),
            "log_scale_before": _optional(np.log10(max(scale_before, 1e-12))),
            "log_scale_after": _optional(np.log10(max(scale_after, 1e-12))),
        })
        for stage, values in (("before", before), ("after", after)):
            boxes.append({"column": column, "stage": stage, **_summary(values)})

    before = df[focus].to_numpy(dtype=float)
    after = transformed[focus].to_numpy(dtype=float)
    before_density, before_edges = np.histogram(before, bins=min(24, max(8, int(np.sqrt(len(before))))), density=True)
    after_density, after_edges = np.histogram(after, bins=len(before_density), density=True)
    distributions = [{
        "x_before": _optional((before_edges[i] + before_edges[i + 1]) / 2),
        "density_before": _optional(before_density[i]),
        "x_after": _optional((after_edges[i] + after_edges[i + 1]) / 2),
        "density_after": _optional(after_density[i]),
    } for i in range(len(before_density))]

    correlations = []
    matrix_columns = columns[:8]
    if len(matrix_columns) >= 2:
        before_corr = df[matrix_columns].corr()
        after_corr = transformed[matrix_columns].corr()
        for left_index, left in enumerate(matrix_columns):
            for right in matrix_columns[left_index + 1:]:
                before_value = float(before_corr.loc[left, right])
                after_value = float(after_corr.loc[left, right])
                correlations.append({
                    "x": left, "y": right, "before": _optional(before_value),
                    "after": _optional(after_value), "delta": _optional(after_value - before_value),
                })
    return preview, ranges, distributions, boxes, correlations


def build_scaling_profile(
    df: pd.DataFrame,
    target_column: str,
    *,
    feature_generation: dict[str, Any] | None = None,
    saved_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Диагностировать матрицу X и предложить fold-safe scaler-рецепт."""
    if target_column not in df.columns:
        raise ValueError(f"Колонка '{target_column}' отсутствует в датасете")
    generated_names = {
        str(name) for name in (feature_generation or {}).get("feature_names", [])
        if str(name) in df.columns
    }
    columns = _column_profiles(df, target_column, generated_names)
    eligible = [item for item in columns if item["eligible"]]
    suggested = [str(item["name"]) for item in columns if item["recommended"]]
    if not suggested:
        suggested = [str(item["name"]) for item in columns if item["eligible"] and item["name"] == target_column]

    scales = [float(item["scale"]) for item in columns if item["name"] in suggested and item["scale"] and float(item["scale"]) > 0]
    scale_ratio = max(scales) / min(scales) if len(scales) >= 2 else 1.0
    suggested_profiles = [item for item in columns if item["name"] in suggested]
    robust_signal = any(
        float(item.get("outlier_pct") or 0) > 1.0 or abs(float(item.get("skewness") or 0)) > 2.0
        for item in suggested_profiles
    )
    recommended_method = "robust" if robust_signal else "standard"
    warnings: list[str] = []
    if any(item["name"] == target_column for item in suggested_profiles):
        warnings.append("Target включён только потому, что непрерывные X отсутствуют; прогнозы потребуют inverse transform, обученный на train.")
    if any(item["binary"] for item in columns):
        warnings.append("Бинарные индикаторы не включены в Auto-набор: их шкала уже интерпретируема как 0/1.")
    if generated_names:
        warnings.append("Непрерывные признаки из остановки «Генерация признаков» доступны для прямого hand-off в рецепт.")

    saved = saved_recipe or {}
    configured = False
    current_saved: dict[str, Any] | None = None
    if saved:
        saved_columns = [str(name) for name in saved.get("columns", [])]
        same_shape = (
            saved.get("kind") == "scaling_recipe"
            and saved.get("target_column") == target_column
            and int(saved.get("configured_on_n", -1)) == len(df)
            and saved_columns
            and all(name in df.columns for name in saved_columns)
        )
        if same_shape and saved.get("source_signature") == _signature(df, saved_columns):
            configured = True
            current_saved = dict(saved)
        else:
            warnings.append("Сохранённый рецепт устарел после изменения строк, значений или состава колонок; подтвердите его заново.")

    applicable = bool(eligible)
    reason = None if applicable else "Нет непрерывных числовых колонок без пропусков и констант"
    preview, ranges, distributions, boxes, correlations = _visual_payloads(
        df, suggested, recommended_method,
    ) if applicable and suggested else ([], [], [], [], [])
    methods = _method_comparison(df, suggested) if applicable else []
    if configured:
        recommendation = "Fold-safe рецепт сохранён. Моделирование должно fit scaler заново на train каждого временного fold."
    elif robust_signal:
        recommendation = "Выбросы/асимметрия выражены: начните с RobustScaler, затем сравните модели временным backtest."
    else:
        recommendation = "Для признаков разных масштабов начните со StandardScaler; окончательный выбор зависит от модели и backtest."
    return {
        "target_column": target_column, "applicable": applicable, "reason": reason,
        "n_observations": len(df), "numeric_count": len(columns),
        "eligible_count": len(eligible), "suggested_columns": suggested,
        "recommended_method": recommended_method, "configured": configured,
        "saved_recipe": current_saved, "focus_column": suggested[0] if suggested else None,
        "scale_ratio": round(float(scale_ratio), 6),
        "orders_of_magnitude": round(float(np.log10(scale_ratio)), 6) if scale_ratio > 0 else 0.0,
        "columns": columns, "preview_points": preview, "range_points": ranges,
        "distribution_points": distributions, "box_points": boxes,
        "correlation_points": correlations, "methods": methods,
        "warnings": warnings, "recommendation": recommendation,
        "methodology_note": (
            "Scaling не является свойством ряда и не улучшает модель автоматически. Полный-history preview диагностический; "
            "сохраняется только рецепт, а fit/fit_transform выполняется на train каждого временного fold и transform — на validation/test. "
            "Affine scalers сохраняют Pearson-корреляции; QuantileTransformer нелинеен и может менять расстояния и корреляции."
        ),
    }


def preview_scaling_recipe(
    df: pd.DataFrame,
    target_column: str,
    *,
    columns: Sequence[str],
    method: str,
    feature_range: Sequence[float] = (0.0, 1.0),
    quantile_range: Sequence[float] = (25.0, 75.0),
    output_distribution: str = "normal",
    n_quantiles: int = 1000,
    confirm_nonlinear: bool = False,
) -> dict[str, Any]:
    """Проверить конфигурацию и сформировать рецепт без мутации DataFrame."""
    if target_column not in df.columns:
        raise ValueError(f"Колонка '{target_column}' отсутствует в датасете")
    if method not in SCALING_METHODS:
        raise ValueError(f"Неподдерживаемый метод масштабирования: {method}")
    if method == "quantile" and not confirm_nonlinear:
        raise ValueError("QuantileTransformer нелинеен; требуется отдельное подтверждение нелинейного преобразования")
    selected = [str(column) for column in columns]
    transformed, preview_metadata = fit_transform_scaling(
        df, selected, method, feature_range=feature_range,
        quantile_range=quantile_range, output_distribution=output_distribution,  # type: ignore[arg-type]
        n_quantiles=n_quantiles,
    )
    metrics = []
    for column in selected:
        before = _summary(df[column].to_numpy(dtype=float))
        after = _summary(transformed[column].to_numpy(dtype=float))
        correlation = float(np.corrcoef(df[column].to_numpy(dtype=float), transformed[column].to_numpy(dtype=float))[0, 1])
        metrics.append({
            "column": column,
            **{f"{key}_before": value for key, value in before.items()},
            **{f"{key}_after": value for key, value in after.items()},
            "original_scaled_correlation": _optional(correlation),
        })
    parameters = dict(preview_metadata["parameters"])  # type: ignore[arg-type]
    recipe = {
        "kind": "scaling_recipe", "target_column": target_column,
        "columns": selected, "method": method, "parameters": parameters,
        "fit_policy": "per_train_fold", "modeling_safe": True,
        "materializes_columns": False, "configured_on_n": len(df),
        "source_signature": _signature(df, selected),
        "target_included": target_column in selected,
        "inverse_transform_required_for_target": target_column in selected,
        "nonlinear": method == "quantile",
    }
    warnings = [
        "Preview обучен на полной истории только для визуальной диагностики и не должен использоваться в backtest."
    ]
    if target_column in selected:
        warnings.append("Target включён в рецепт: после прогноза требуется inverse_transform параметрами соответствующего train-fold.")
    if method == "quantile":
        warnings.append("QuantileTransformer нелинейно меняет корреляции/расстояния и насыщает значения вне обучающего диапазона.")
    preview_metadata = {
        **preview_metadata,
        "fit_scope": "full_history_diagnostic",
        "modeling_safe": False,
        "applied_to_dataframe": False,
    }
    return {
        "target_column": target_column, "columns": selected, "method": method,
        "metrics": metrics, "warnings": warnings, "recipe": recipe,
        "preview_metadata": preview_metadata,
    }

