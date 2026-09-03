"""Единый hand-off Validation → Preprocessing → EDA → Modeling.

Модуль не повторяет аналитические алгоритмы: финальные свойства берутся из
канонического паспорта, совместимость моделей — из EDA model matrix, схема
folds — из EDA validation strategy, а правила кандидатов — из modeling.yaml.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from app.core.passport import prepare_passport_series, series_fingerprint
from apps.api.eda_model_matrix import build_eda_model_matrix
from apps.api.eda_validation_strategy import build_eda_validation_strategy
from apps.api.session_store import AnalysisSession, MODELING_STAGE_IDS


def _trace(group: str, source_id: str, label: str, endpoint: str,
           inputs: list[str], stages: list[str]) -> dict[str, Any]:
    return {
        "group": group, "source_id": source_id, "label": label,
        "source_endpoint": endpoint, "modeling_inputs": inputs,
        "modeling_stages": stages,
    }


TRACEABILITY_CATALOG: tuple[dict[str, Any], ...] = (
    _trace("validation", "data_types", "Типы данных", "/dataset/validate", ["numeric_target", "typed_features"], ["data_structure", "constraint_mapping"]),
    _trace("validation", "formats", "Форматы и шаблоны", "/dataset/format-profile", ["parse_contract", "categorical_contract"], ["data_structure"]),
    _trace("validation", "ranges", "Диапазоны значений", "/dataset/range-profile", ["domain_bounds", "target_support"], ["constraint_mapping"]),
    _trace("validation", "consistency", "Логика и хронология", "/dataset/consistency-profile", ["logical_constraints", "temporal_order"], ["constraint_mapping"]),
    _trace("validation", "uniqueness", "Уникальность", "/dataset/uniqueness-profile", ["series_identity", "panel_keys"], ["data_structure"]),
    _trace("validation", "inclusion", "Допустимый набор", "/dataset/inclusion-profile", ["categorical_levels", "encoding_scope"], ["constraint_mapping"]),
    _trace("validation", "referential", "Ссылочная целостность", "/dataset/referential-profile", ["exogenous_alignment", "join_integrity"], ["data_structure"]),
    _trace("validation", "text_quality", "Целостность текста", "/dataset/text-quality-profile", ["feature_names", "category_quality"], ["constraint_mapping"]),
    _trace("validation", "regularity", "Равномерность временного шага", "/dataset/regularity-profile", ["frequency", "is_regular"], ["data_structure", "backtest"]),
    _trace("validation", "sufficiency", "Достаточность наблюдений", "/dataset/sufficiency-profile", ["history_budget", "model_minimums"], ["candidate_generation", "backtest"]),
    _trace("preprocessing", "missing", "Пропуски", "/dataset/missing-profile", ["finite_target", "missing_policy"], ["constraint_mapping", "backtest"]),
    _trace("preprocessing", "outliers", "Выбросы", "/dataset/outlier-profile", ["robustness_need", "loss_sensitivity"], ["constraint_mapping", "comparison"]),
    _trace("preprocessing", "regularity", "Регулярность ряда", "/dataset/preprocessing/regularity-profile", ["frequency", "regular_grid"], ["data_structure", "backtest"]),
    _trace("preprocessing", "decomposition", "Декомпозиция ряда", "/dataset/preprocessing/decomposition-profile", ["trend_strength", "seasonal_periods", "residual_structure"], ["candidate_generation", "diagnostics"]),
    _trace("preprocessing", "variance_stab", "Стабилизация дисперсии", "/dataset/preprocessing/variance-profile", ["target_transform", "inverse_transform"], ["constraint_mapping", "model_card"]),
    _trace("preprocessing", "smoothing", "Сглаживание ряда", "/dataset/preprocessing/smoothing-profile", ["causality", "modeling_safe"], ["constraint_mapping", "model_card"]),
    _trace("preprocessing", "stationarity", "Стационарность ряда", "/dataset/preprocessing/stationarity-profile", ["integration_order", "inverse_boundaries"], ["candidate_generation", "diagnostics"]),
    _trace("preprocessing", "spectral", "Спектральный анализ", "/dataset/preprocessing/spectral-profile", ["seasonal_periods", "spectral_evidence"], ["candidate_generation", "tuning"]),
    _trace("preprocessing", "feature_eng", "Генерация признаков", "/dataset/preprocessing/feature-generation-profile", ["feature_catalog", "lookback", "forecast_availability"], ["data_structure", "tuning"]),
    _trace("preprocessing", "scaling", "Масштабирование", "/dataset/preprocessing/scaling-profile", ["fold_safe_scaler", "target_inverse"], ["backtest", "model_card"]),
    _trace("eda", "descriptive", "Описательные статистики", "/dataset/stats", ["scale", "dispersion", "shape"], ["constraint_mapping"]),
    _trace("eda", "correlation", "Корреляция (ACF/PACF)", "/dataset/eda-correlation", ["lag_structure", "ar_ma_orders"], ["candidate_generation", "tuning"]),
    _trace("eda", "ih_analysis", "IH-анализ", "/dataset/eda-ih", ["nonlinear_signal", "interaction_candidates"], ["candidate_generation", "tuning"]),
    _trace("eda", "seasonality", "Сезонность и периодичность", "/dataset/eda-seasonality", ["seasonal_periods", "seasonal_strength"], ["candidate_generation", "tuning"]),
    _trace("eda", "stationarity", "Верификация стационарности", "/dataset/eda-stationarity", ["stationarity_consensus", "break_adjustment"], ["candidate_generation", "diagnostics"]),
    _trace("eda", "distribution", "Распределение", "/dataset/eda-distribution", ["loss_choice", "interval_assumptions"], ["constraint_mapping", "diagnostics"]),
    _trace("eda", "structural", "Структурные сдвиги", "/dataset/eda-structural-breaks", ["training_window", "regime_risk"], ["backtest", "selection"]),
    _trace("eda", "feature_select", "Отбор признаков", "/dataset/eda-feature-selection", ["feature_shortlist", "vif", "granger"], ["candidate_generation", "tuning"]),
    _trace("eda", "validation_strategy", "Стратегия валидации", "/dataset/eda-validation-strategy", ["folds", "horizon", "gap"], ["backtest", "tuning", "comparison"]),
    _trace("eda", "model_matrix", "Матрица моделей", "/dataset/eda-model-matrix", ["runnable_shortlist", "criteria_matrix"], ["candidate_generation", "selection"]),
)


def build_traceability_summary(nodes: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("done", "warning", "skipped", "pending")
    summary = {"total": len(nodes), **{status: 0 for status in statuses}, "blocking": 0}
    for node in nodes:
        status = str(node.get("status", "pending"))
        if status in summary:
            summary[status] += 1
        if node.get("blocking"):
            summary["blocking"] += 1
    return summary


def _frequency_alias(value: Any) -> str:
    raw = str(value or "").upper()
    if raw.startswith(("B", "C", "D")):
        return "D"
    if raw.startswith("W"):
        return "W"
    if raw.startswith(("M", "BM", "SM")):
        return "M"
    if raw.startswith(("Q", "BQ")):
        return "Q"
    if raw.startswith(("Y", "A")):
        return "Y"
    return raw or "other"


def _iqr_outlier_ratio(values: pd.Series) -> float:
    if len(values) < 4:
        return 0.0
    q1, q3 = np.quantile(values.to_numpy(dtype=float), [0.25, 0.75])
    iqr = q3 - q1
    if iqr <= np.finfo(float).eps:
        return 0.0
    count = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum())
    return count / len(values)


def _validation_statuses(session: AnalysisSession) -> dict[str, tuple[str, str]]:
    try:
        from validation.engine import validate_dataframe
        from validation.rule_resolver import resolve_validation_rules

        rules, sources = resolve_validation_rules(
            session.dataframe,
            template_id=session.validation_template_id,
            session_overrides=session.validation_rule_overrides,
            type_schema=session.type_schema,
        )
        result = validate_dataframe(session.dataframe, rules, target_column=session.target_column)
        output: dict[str, tuple[str, str]] = {}
        for source_id in (item["source_id"] for item in TRACEABILITY_CATALOG if item["group"] == "validation"):
            mode = session.validation_check_modes.get(source_id, "auto")
            if mode == "disabled":
                output[source_id] = ("skipped", "Проверка отключена аналитиком.")
                continue
            item = result.get("checks", {}).get(source_id, {})
            raw_status = item.get("status", "pending")
            status = "warning" if raw_status == "warning" else ("pending" if raw_status == "pending" else "done")
            count = item.get("count")
            evidence = f"Источник правил: {sources.get(source_id, 'not_applicable')}; нарушений: {count if count is not None else '—'}."
            output[source_id] = (status, evidence)
        return output
    except Exception as exc:  # traceability must explain an unavailable source
        return {
            item["source_id"]: ("pending", f"Текущий результат не получен: {exc}")
            for item in TRACEABILITY_CATALOG if item["group"] == "validation"
        }


def _preprocessing_statuses(session: AnalysisSession, passport: dict[str, Any], values: pd.Series) -> dict[str, tuple[str, str]]:
    modes = session.preprocessing_check_modes
    kinds = [str(item.get("kind", "")) for item in session.preprocessing_transformations.values()]
    methods = [str(item.get("method", "")) for item in session.preprocessing_transformations.values()]
    periods = session.preprocessing_spectral_selection.get("periods", [])
    generated = session.preprocessing_feature_generation.get("output_columns", [])
    scaling = session.preprocessing_scaling_recipe
    regular = bool(passport.get("freq", {}).get("is_regular"))
    stationary = bool(passport.get("stationarity", {}).get("is_stationary"))
    outliers = _iqr_outlier_ratio(values)
    statuses = {
        "missing": ("done", "Целевой ряд содержит только конечные значения."),
        "outliers": ("warning" if outliers else "done", f"IQR-доля выбросов финальной цели: {outliers:.2%}."),
        "regularity": ("done" if regular else "warning", f"Финальная частота: {passport.get('freq', {}).get('value', '—')}."),
        "decomposition": ("done", f"STL/сезонность: {passport.get('seasonality', {}).get('strength', 'N/A')}"),
        "variance_stab": ("done" if any(method in {"box_cox", "yeo_johnson", "log", "log1p", "sqrt"} for method in methods) else "skipped", "Сохранена обратимая power-трансформация." if methods else "Power-трансформация не применялась."),
        "smoothing": ("done" if "smoothing" in kinds else "skipped", "Сглаженный выход сохранён." if "smoothing" in kinds else "Опциональное сглаживание не применялось."),
        "stationarity": ("done" if stationary or "stationarity" in kinds else "warning", "Финальный ряд стационарен или сохранено дифференцирование." if stationary or "stationarity" in kinds else "Финальная проверка не подтвердила стационарность."),
        "spectral": ("done", f"Подтверждённые периоды: {periods or passport.get('seasonal_periods', {}).get('periods', [])}."),
        "feature_eng": ("done" if generated else "skipped", f"Создано признаков: {len(generated)}." if generated else "Target-derived X не материализованы."),
        "scaling": ("done" if scaling else "skipped", f"Fold-safe рецепт: {scaling.get('method')}." if scaling else "Масштабирование не требуется выбранным моделям либо не настроено."),
    }
    for source_id, mode in modes.items():
        if source_id in statuses and mode == "disabled":
            statuses[source_id] = ("skipped", "Остановка отключена аналитиком.")
    return statuses


def _eda_statuses(passport: dict[str, Any], n_exogenous: int, matrix: dict[str, Any], validation: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        "descriptive": ("done", f"n={passport.get('basic_stats', {}).get('n', '—')}; mean={passport.get('basic_stats', {}).get('mean', '—')}."),
        "correlation": ("done" if passport.get("autocorrelation", {}).get("applicable", True) else "warning", f"Ljung–Box p={passport.get('autocorrelation', {}).get('value', 'N/A')}."),
        "ih_analysis": ("pending" if n_exogenous else "skipped", "Нелинейные связи требуют сохранённого результата IH." if n_exogenous else "Нет X-кандидатов для IH."),
        "seasonality": ("done", f"Сила сезонности: {passport.get('seasonality', {}).get('strength', 'N/A')}."),
        "stationarity": ("done" if passport.get("stationarity", {}).get("is_stationary") else "warning", f"ADF p={passport.get('stationarity', {}).get('value', 'N/A')}."),
        "distribution": ("done", f"Jarque–Bera p={passport.get('normality', {}).get('value', 'N/A')}."),
        "structural": ("pending", "Результат структурных сдвигов не входит в паспорт; подтвердите окно обучения в Моделировании."),
        "feature_select": ("pending" if n_exogenous else "skipped", "Shortlist X должен быть подтверждён EDA." if n_exogenous else "Нет экзогенных X для отбора."),
        "validation_strategy": ("done" if validation.get("applicable") else "warning", validation.get("recommendation") or validation.get("reason") or "Стратегия построена."),
        "model_matrix": ("done" if matrix.get("applicable") else "warning", matrix.get("recommendation") or matrix.get("reason") or "Матрица построена."),
    }


def build_modeling_context(session: AnalysisSession, *, horizon: int = 12,
                           strategy: str = "expanding", n_splits: int = 5,
                           gap: int = 0, train_window: int = 60) -> dict[str, Any]:
    if session.dataframe is None or not session.target_column or not session.date_column:
        raise ValueError("Для Моделирования нужны dataset, target_column и date_column")
    checkpoint = session.latest_passport_checkpoint("modeling_entry")
    if checkpoint is None:
        raise ValueError("Сначала подтвердите checkpoint modeling_entry на вкладке EDA")
    series = prepare_passport_series(session.dataframe, session.target_column, session.date_column)
    fingerprint = series_fingerprint(series)
    if fingerprint != checkpoint.fingerprint:
        raise ValueError("Checkpoint modeling_entry устарел: ряд изменился после подтверждения EDA")
    snapshot = session.passport_snapshot(checkpoint.snapshot_id)
    if snapshot is None:
        raise ValueError("Снимок checkpoint modeling_entry недоступен")
    passport = deepcopy(snapshot.passport)

    validation = build_eda_validation_strategy(
        session.dataframe, session.target_column, strategy=strategy,
        horizon=horizon, n_splits=n_splits, gap=gap, train_window=train_window,
    )
    # Stable adapter for Modeling consumers: EDA exposes requested/effective
    # splits, while the modeling contract consumes the actually usable count.
    validation["n_splits"] = validation.get("effective_splits", n_splits)
    matrix = build_eda_model_matrix(
        session.dataframe, session.target_column, task="forecast", horizon=horizon,
        validation_strategy=strategy, n_splits=n_splits, gap=gap,
        train_window=train_window,
    )
    matrix_profile = matrix.get("profile", {})
    numeric_columns = [str(column) for column in session.dataframe.select_dtypes(include="number").columns]
    n_exogenous = int(matrix_profile.get("n_exogenous", max(0, len(numeric_columns) - 1)))
    values = pd.Series(series.to_numpy(dtype=float))
    seasonal_periods = list(dict.fromkeys(
        list(session.preprocessing_spectral_selection.get("periods", []))
        + list(matrix_profile.get("seasonal_periods", []))
        + list(passport.get("seasonal_periods", {}).get("periods", []))
    ))
    profile = {
        "n_observations": len(series), "n_series": 1, "n_exogenous": n_exogenous,
        "is_regular": bool(passport.get("freq", {}).get("is_regular")),
        "frequency": _frequency_alias(passport.get("freq", {}).get("value")),
        "has_seasonality": bool(passport.get("seasonality", {}).get("is_seasonal")),
        "seasonal_periods": [int(item) for item in seasonal_periods if int(item) > 1],
        "is_stationary_or_diffable": bool(passport.get("stationarity", {}).get("is_stationary")) or any(
            item.get("kind") == "stationarity" for item in session.preprocessing_transformations.values()
        ),
        "is_cointegrated": False,
        "has_negative_values": bool((values < 0).any()),
        "has_volatility_clustering": False,
        "domain": "other", "missing_ratio": 0.0,
        "outlier_ratio": round(_iqr_outlier_ratio(values), 8),
        "has_holidays": False, "gpu_available": False,
        "feature_engineering_applied": bool(session.preprocessing_feature_generation),
    }

    status_maps = {
        "validation": _validation_statuses(session),
        "preprocessing": _preprocessing_statuses(session, passport, values),
        "eda": _eda_statuses(passport, n_exogenous, matrix, validation),
    }
    nodes = []
    hard_blocking_ids = {("validation", "data_types"), ("preprocessing", "missing")}
    for definition in TRACEABILITY_CATALOG:
        status, evidence = status_maps[definition["group"]][definition["source_id"]]
        node = {**deepcopy(definition), "status": status, "evidence": evidence}
        source_key = (definition["group"], definition["source_id"])
        node["blocking"] = source_key in hard_blocking_ids and status in {"warning", "pending"}
        if source_key == ("validation", "sufficiency"):
            # Общая validation-норма может быть строже конкретного horizon.
            # Блокируем только если выбранная временная схема действительно не помещается.
            node["blocking"] = not bool(validation.get("applicable"))
        elif source_key in {("validation", "regularity"), ("preprocessing", "regularity")}:
            # Нерегулярность — ограничение применимости моделей, а не универсальный запрет.
            node["blocking"] = not bool(matrix.get("applicable"))
        nodes.append(node)

    traceability_summary = build_traceability_summary(nodes)
    ready = (
        traceability_summary["blocking"] == 0
        and bool(validation.get("applicable"))
        and bool(matrix.get("applicable"))
        and bool(matrix.get("runnable_shortlist"))
    )
    return {
        "ready": ready, "data_source": "session", "fingerprint": fingerprint,
        "checkpoint": {
            "checkpoint_id": checkpoint.checkpoint_id, "snapshot_id": checkpoint.snapshot_id,
            "stage": checkpoint.stage, "source_stage": checkpoint.source_stage,
            "confirmed_at": checkpoint.confirmed_at,
        },
        "profile": profile, "passport": passport,
        "validation_strategy": validation,
        "model_matrix": matrix,
        "runnable_shortlist": matrix.get("runnable_shortlist", []),
        "traceability": {"nodes": nodes, "summary": traceability_summary},
    }
