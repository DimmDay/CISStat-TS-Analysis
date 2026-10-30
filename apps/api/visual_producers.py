# apps/api/visual_producers.py
"""
Task PGV-03 (spec_passport_graphics_visual.md §6/§13, строка PGV-03):
producer-адаптеры -- фиксация print-input (VisualResult/1) в момент
фиксации РЕАЛЬНОГО ответа научной остановки.

ПОСТАНОВКА (§13): «Producer adapters; точки изменения --
upload/validation/preprocessing/EDA/modeling/forecast/tasks; критерий --
freeze сохранённого реального response, CAS версии, export не
пересчитывает science».

КЛЮЧЕВЫЕ РЕШЕНИЯ (§6 -- «Producer adapter фиксирует print input при
фиксации результата либо первом explicit export ещё доступного
проверенного результата»):

1. ОДИН СЛОЙ АДАПТЕРОВ (сквозная практика «одна точка интеграции»).
   Реестр PGV-00 -- источник истины: view с source_adapter pgv-03/*
   либо имеет адаптер этой поставки (wired: 48 view во всех семи
   остановках), либо входит в честный недобор UNWIRED_PGV03_VIEWS
   (добирается PGV-10/11/12 -- gap виден, не замалчивается, §3.6).
   navigator/static_demo -- НЕ результат исследования (§1/§2);
   passport.panel/comparison -- PGV-04/PGV-13; legacy_png -- PGV-12:
   адаптеров нет, resolve честно отказывает.

2. RESULT_REF -- ДЕТЕРМИНИРОВАННЫЙ ТОКЕН РЕЗУЛЬТАТА (§6 «Response
   содержит result_ref/context/version token»): vr-<sha256> от
   (params, response). Те же данные и params -- тот же ref
   (идемпотентность §11); zoom/окно/новая ревизия данных -- другой ref
   (AC08: sampling/aggregation/zoom различаются явно, скрытого detail
   upgrade нет).

3. КЭШ СОХРАНЁННЫХ ОТВЕТОВ (субстрат lazy transfer). «Для lazy GET
   результат переносится из фактического response в durable слой
   идемпотентно» (§6): фиксированный ответ сохраняется (LRU,
   process-local) с контекстом момента (run/session/context/revision/
   computed_at); снимок изолируется ГЛУБОКОЙ копией (PGV-03-FIX,
   F-P3C3) -- пост-мутация источника не меняет сохранённое; первый
   explicit export (PGV-13) морозит СОХРАНЁННЫЙ ответ по ref --
   renderer не вызывает GET для повторной науки (§6), экспорт не
   запускает научный расчёт (§3.1, AC06).

4. PAYLOAD ПО ЗЕРКАЛУ PGV-01. VisualResult/1 собирается из фактического
   ответа: payload.data -- срез ответа (серия/таблица/матрица/карточки),
   digest == sha256(data) (не выдумывается), units -- value XOR явная
   null-причина (legacy_unknown для сырых рядов; dimensionless для
   counts/статистик), sampling -- из РЕАЛЬНЫХ полей ответа
   (scatter_sampled/sampling_method/original_count, params.zoom),
   parameters.origin -- trusted (producer_freeze / producer_first_export),
   execution.computed_at -- от обработчика (None -> честная причина
   producer_not_reported, время вызова не подставляется).

5. FREEZE И CAS (PGV-AC07). freeze_visual_from_response -- producer_
   freeze: фиксация текущего durable-состояния (сессия и запуск
   согласованы в момент ответа); явные expected_* проверяются против
   run (расхождение -> PrintContextConflict -> 409 context_changed,
   НИЧЕГО не зарегистрировано). freeze_saved_visual -- producer_first_
   export: CAS ВСЕГДА сверяет контекст сохранённого ответа с текущим
   состоянием запуска (смена данных между показом и export -> 409;
   клиент выбирает обновление или уже сохранённую версию). «ВСЕГДА»
   ENFORCED (PGV-03-FIX, F-P3C1): сверка возможна только при ПОЛНОМ
   снимке контекста момента; деградировавший снимок не даёт
   доказательства неизменности durable-состояния -- fail-closed, НЕ
   тихий пропуск сверки (класс F-P2C2, прецедент PGV-02-FIX): пустой
   снимок (оба измерения неизвестны) -- VisualSourceUnavailable,
   частичный -- PrintContextConflict (409); НИЧЕГО не регистрируется.

6. ЧЕСТНЫЕ ГРАНИЦЫ. unknown view -- UnknownVisualView; вне скоупа
   (demo/passport/comparison/legacy/unwired) -- VisualViewOutOfScope с
   указанием добирающей задачи; вытесненный из кэша ref --
   VisualSourceUnavailable (§11 source_unavailable), пересчёта науки
   НЕТ; неканонический payload -- честный отказ гейта PGV-02 (ничего
   не регистрируется).

ИНВАРИАНТ: модуль ТОЛЬКО переносит уже вычисленный результат в durable
слой; никакой науки здесь нет (§3.1). Best-effort-обёртка для
обработчиков -- notify_visual_result в promotion_integration (сбой --
durable-receipt, научная операция и HTTP-ответ не ломаются, прецедент
C03/notify_validation_result).
"""

from __future__ import annotations

import copy
import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

# source_adapter сайтов реестра PGV-00, относящихся к этой задаче
PRODUCER_SOURCE_ADAPTER_PREFIX = "pgv-03/"

TRUSTED_ORIGIN_FREEZE = "producer_freeze"
TRUSTED_ORIGIN_FIRST_EXPORT = "producer_first_export"

# ── Ошибки (роутеры PGV-13 маппят: 422/409) ──────────────────────────


class VisualProducerError(RuntimeError):
    """Базовая ошибка слоя producer-адаптеров (честная, без дисклоужения)."""


class UnknownVisualView(VisualProducerError):
    """view_id вне реестра PGV-00 -- неизвестный сайт (§5: unknown site
    блокирует CERT; честный отказ, не молчаливый успех)."""


class VisualViewOutOfScope(VisualProducerError):
    """view вне скоупа PGV-03: navigator/static_demo (не результат
    исследования, §1/§2), passport.panel/comparison (PGV-04/PGV-13),
    legacy_png (PGV-12) либо pgv-03 view без адаптера этой поставки
    (честный недобор -- добирается PGV-10/11/12)."""


class VisualSourceUnavailable(VisualProducerError):
    """Сохранённый ответ для result_ref недоступен (вытеснен LRU/нет в
    этом процессе) -- §11 source_unavailable; пересчёт науки запрещён."""


# ── Резолв сайтов реестра PGV-00 ─────────────────────────────────────


@lru_cache(maxsize=1)
def _registry_sites_by_view() -> dict[str, dict[str, Any]]:
    from apps.api.print_schema import load_visual_registry

    return {
        str(site.get("view_id")): site
        for site in load_visual_registry()["sites"]
        if site.get("view_id")
    }


@lru_cache(maxsize=1)
def producer_view_ids() -> tuple[str, ...]:
    """Все view реестра PGV-00 с source_adapter pgv-03/* И research-
    applicability (68 сайтов -- upload/validation/preprocessing/EDA/
    modeling/forecasting/tasks). navigator/static_demo -- отдельная
    честная категория (static_demo_view_ids): «статическое демо
    маркируется и не становится результатом исследования» (spec §1)."""
    return tuple(
        sorted(
            view_id
            for view_id, site in _registry_sites_by_view().items()
            if str(site.get("source_adapter", "")).startswith(
                PRODUCER_SOURCE_ADAPTER_PREFIX
            )
            and site.get("applicability") != "static_demo"
        )
    )


@lru_cache(maxsize=1)
def static_demo_view_ids() -> tuple[str, ...]:
    """pgv-03/navigator_demo сайты: статические демо-превью Навигатора.
    Не результаты исследования (spec §1/§2) -- freeze запрещён честным
    отказом скоупа; экспорт таких сайтов -- отдельное решение PGV-00
    (пометка demo), вне durable-контура результатов."""
    return tuple(
        sorted(
            view_id
            for view_id, site in _registry_sites_by_view().items()
            if str(site.get("source_adapter", "")).startswith(
                PRODUCER_SOURCE_ADAPTER_PREFIX
            )
            and site.get("applicability") == "static_demo"
        )
    )


def _site_for(view_id: str) -> Optional[dict[str, Any]]:
    site = _registry_sites_by_view().get(view_id)
    if site is None:
        return None
    if not str(site.get("source_adapter", "")).startswith(
        PRODUCER_SOURCE_ADAPTER_PREFIX
    ) or site.get("applicability") == "static_demo":
        # Сайт реестра вне research-скоупа PGV-03: demo (navigator --
        # «не становится результатом исследования», §1), passport
        # (PGV-04), comparison (PGV-13), legacy_png (PGV-12).
        adapter = str(site.get("source_adapter", "") or "unknown")
        if site.get("applicability") == "static_demo":
            task = "static demo -- не результат исследования (spec §1)"
        elif adapter.startswith("pgv-04/"):
            task = "PGV-04"
        elif adapter.startswith("pgv-13/"):
            task = "PGV-13"
        elif adapter.startswith("pgv-12/"):
            task = "PGV-12"
        else:
            task = "PGV-00"
        raise VisualViewOutOfScope(
            f"view {view_id!r} вне скоупа PGV-03 (source_adapter={adapter!r}; "
            f"добирающая задача: {task})"
        )
    return site


def resolve_producer_view(view_id: str) -> dict[str, Any]:
    """Сайт реестра для pgv-03 view; UnknownVisualView / честный
    VisualViewOutOfScope (demo/passport/comparison/legacy/unwired)."""
    site = _site_for(view_id)
    if site is None:
        raise UnknownVisualView(
            f"view {view_id!r} вне реестра PGV-00 (unknown site -- §5)"
        )
    if view_id in UNWIRED_PGV03_VIEWS:
        raise VisualViewOutOfScope(
            f"view {view_id!r} заявлен в реестре, но адаптер не входит в "
            f"поставку PGV-03 (честный недобор -- добирается PGV-10/11/12)"
        )
    return site


# ── Честный недобор (PGV-10/11/12): заявлены в реестре, не в поставке ─

UNWIRED_PGV03_VIEWS: frozenset[str] = frozenset(
    {
        # ── Моделирование -> PGV-12 ──
        "modeling.workflow.overview",
        "modeling.traceability.cards",
        "modeling.panel.metrics",
        "modeling.diagnostics.residuals",
        # ── Прогнозирование -> PGV-12 ──
        "forecasting.forecast.comparison",
        "forecasting.forecast.sensitivity",
        "forecasting.accuracy.metrics",
        "forecasting.monitoring.d12",
    }
)
# PGV-10: 12 недобранных view «Предобработки» добраны адаптерами ниже
# (честный недобор PGV-03 сужен; EDA/tasks -- PGV-11, modeling/forecast
# -- PGV-12, паспорта -- PGV-04/13).


def unwired_view_ids() -> tuple[str, ...]:
    return tuple(sorted(UNWIRED_PGV03_VIEWS))


# ── Units-политики (value XOR явная причина; spec §6) ────────────────


def _units_value(value: str) -> list[dict[str, Any]]:
    return [{"value": value, "reason": None}]


def _units_unknown(_response: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    # Единицы сырого ряда не извлекаются из ответа -- честная null-причина
    # (spec §6: «Не выдумывать единицы и timestamps»).
    return [{"value": None, "reason": "legacy_unknown"}]


UNITS_DIMENSIONLESS = ("dimensionless",)
UNITS_PERCENT = ("percent",)

# ── Sampling-политики (из РЕАЛЬНЫХ полей ответа; AC05/AC08) ──────────

_ZOOM_KEYS = ("start", "end")


def _is_zoom(params: Optional[Mapping[str, Any]]) -> bool:
    if not params:
        return False
    return any(params.get(key) is not None for key in _ZOOM_KEYS)


def _series_sampling(
    response: Mapping[str, Any],
    *,
    sampled_key: str,
    count_of: Callable[[Mapping[str, Any]], int],
    params: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """sampling сериальных видов: zoom -> windowed; LTTB/даунсэмпл ->
    downsampled + point_cap (реальные поля ответа); иначе full."""
    if _is_zoom(params):
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": count_of(response),
            "reason": None,
        }
    if response.get(sampled_key) is True:
        return {
            "applicable": True,
            "mode": "downsampled",
            "point_cap": count_of(response),
            "reason": None,
        }
    return {"applicable": True, "mode": "full", "point_cap": None, "reason": None}


def _full_sampling(
    response: Mapping[str, Any],
    *,
    zoom_cap_of: Optional[Callable[[Mapping[str, Any]], int]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Полный результат (таблицы/карточки/матрицы): все строки включены.
    Для windowed-вычислений (гистограмма по zoom-диапазону) -- честный
    windowed с фактическим потолком точек окна."""
    if zoom_cap_of is not None and _is_zoom(params):
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": zoom_cap_of(response),
            "reason": None,
        }
    return {"applicable": True, "mode": "full", "point_cap": None, "reason": None}


# ── Экстракторы срезов ответа (payload.data -- честный срез) ─────────


def _validation_check_data(
    response: Mapping[str, Any], check_id: str
) -> dict[str, Any]:
    checks = response.get("checks")
    check = checks.get(check_id) if isinstance(checks, dict) else None
    if not isinstance(check, dict):
        check = {}
    return {
        "check_id": check_id,
        "status": check.get("status"),
        "count": check.get("count"),
        "scope": check.get("scope"),
        "rule_source": check.get("rule_source"),
        "mode": check.get("mode"),
        "error": check.get("error"),
        "items": check.get("items") or [],
    }


def _stats_table_data(response: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for column in response.get("columns") or []:
        stats = column.get("stats") or {}
        rows.append(
            {
                "name": column.get("name"),
                "non_null_count": column.get("non_null_count"),
                "mean": stats.get("mean"),
                "median": stats.get("median"),
                "std": stats.get("std"),
                "q1": stats.get("q1"),
                "q3": stats.get("q3"),
                "iqr": stats.get("iqr"),
                "skewness": stats.get("skewness"),
                "kurtosis": stats.get("kurtosis"),
            }
        )
    return {
        "columns": [
            "name", "non_null_count", "mean", "median", "std",
            "q1", "q3", "iqr", "skewness", "kurtosis",
        ],
        "rows": rows,
        "row_count": len(rows),
    }


def _columns_info_table(response: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "name": column.get("name"),
            "dtype": column.get("dtype"),
            "type_icon": column.get("type_icon"),
            "non_null": column.get("non_null"),
            "nulls": column.get("nulls"),
            "unique": column.get("unique"),
        }
        for column in response.get("columns_info") or []
    ]
    return {
        "columns": ["name", "dtype", "type_icon", "non_null", "nulls", "unique"],
        "rows": rows,
        "row_count": len(rows),
    }


def _preview_table(response: Mapping[str, Any]) -> dict[str, Any]:
    preview = response.get("preview") or {}
    return {
        "tables": [
            {"id": "head", "rows": preview.get("head") or []},
            {"id": "tail", "rows": preview.get("tail") or []},
        ]
    }


def _quality_cards(response: Mapping[str, Any]) -> dict[str, Any]:
    quality = response.get("quality") or {}
    return {
        "cards": [
            {"label": key, "value": quality.get(key)}
            for key in (
                "cols_with_missing", "cols_with_outliers",
                "rows_total", "duplicates",
            )
        ]
    }


def _structure_table(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "columns": ["field", "selected", "detail"],
        "rows": [
            {"field": "date_col", "selected": response.get("date_col"), "detail": None},
            {"field": "entity_col", "selected": response.get("entity_col"), "detail": None},
            {"field": "frequency", "selected": response.get("frequency"), "detail": None},
        ],
        "row_count": 3,
    }


def _decomposition_cards(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cards": [
            {"label": "trend_pct", "value": response.get("trend_pct")},
            {"label": "seasonal_pct", "value": response.get("seasonal_pct")},
            {"label": "cyclical_pct", "value": response.get("cyclical_pct")},
            {"label": "resid_pct", "value": response.get("resid_pct")},
        ],
        "applicable": response.get("applicable"),
        "reason": response.get("reason"),
    }


def _missing_profile_table(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "summary": {
            "total_rows": response.get("total_rows"),
            "total_columns": response.get("total_columns"),
            "total_missing": response.get("total_missing"),
            "missing_rate_pct": response.get("missing_rate_pct"),
            "rows_with_missing": response.get("rows_with_missing"),
            "rows_with_missing_pct": response.get("rows_with_missing_pct"),
            "empty_rows": response.get("empty_rows"),
        },
        "columns": response.get("columns") or [],
        "row_histogram": response.get("row_histogram") or [],
    }


def _outlier_profile_table(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "summary": {
            "total_rows": response.get("total_rows"),
            "total_numeric_columns": response.get("total_numeric_columns"),
            "total_outliers": response.get("total_outliers"),
            "outlier_rate_pct": response.get("outlier_rate_pct"),
            "affected_columns": response.get("affected_columns"),
        },
        "columns": response.get("columns") or [],
    }


def _smoothing_profile(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = response.get("profile") or {}
    return {
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
        "selected_method": profile.get("selected_method"),
        "selected_parameters": profile.get("selected_parameters"),
        "needs_smoothing": profile.get("needs_smoothing"),
        "diagnostics_before": profile.get("diagnostics_before"),
        "diagnostics_after": profile.get("diagnostics_after"),
        "points": profile.get("points") or [],
    }


# ── Экстракторы добора PGV-10 (обёрнутые ответы {mode,status,profile}) ─


def _profile_of(response: Mapping[str, Any]) -> Mapping[str, Any]:
    """Обёртка остановок Предобработки {mode, status, profile}: срез
    берётся из фактического profile; плоский ответ (без обёртки) --
    как есть (честные формы обоих видов)."""
    profile = response.get("profile")
    return profile if isinstance(profile, dict) else response


def _preprocessing_regularity_table(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Регулярность»: профиль временной оси -> таблица
    поле/значение (зеркало RegularityProfileOut, apps/api/schemas.py)."""
    profile = _profile_of(response)
    rows = [
        {"field": "date_column", "selected": profile.get("date_column")},
        {"field": "entity_column", "selected": profile.get("entity_column")},
        {
            "field": "frequency",
            "selected": profile.get("detected_frequency")
            or profile.get("target_frequency"),
        },
        {"field": "is_sorted", "selected": profile.get("is_sorted")},
        {"field": "sort_violations", "selected": profile.get("sort_violations")},
        {"field": "invalid_date_count", "selected": profile.get("invalid_date_count")},
        {"field": "duplicate_count", "selected": profile.get("duplicate_count")},
        {"field": "gap_count", "selected": profile.get("gap_count")},
        {
            "field": "missing_period_count",
            "selected": profile.get("missing_period_count"),
        },
        {"field": "total_violations", "selected": profile.get("total_violations")},
    ]
    return {
        "applicable": profile.get("applicable"),
        "reason": profile.get("applicability_message"),
        "columns": ["field", "selected"],
        "rows": rows,
        "row_count": len(rows),
    }


def _regularity_gap_map(response: Mapping[str, Any]) -> dict[str, Any]:
    """Таймлайн событий (validation/regularity.py::regularity_timeline):
    события разрывов/дублей/сортировки -- chart-форма (events) И табличная
    (columns/rows) для второй секции mixed-сайта."""
    events = response.get("events") or []
    rows = [
        {
            "date": event.get("date"),
            "kind": event.get("kind"),
            "group": event.get("group"),
        }
        for event in events
        if isinstance(event, dict)
    ]
    return {
        "events": events,
        "truncated": response.get("truncated"),
        "date_column": response.get("date_column"),
        "entity_column": response.get("entity_column"),
        "min_date": response.get("min_date"),
        "max_date": response.get("max_date"),
        "columns": ["date", "kind", "group"],
        "rows": rows,
        "row_count": len(rows),
    }


def _preprocessing_decomposition_series(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Декомпозиция ряда» (build_preprocessing_decomposition):
    STL-компоненты вдоль временной оси."""
    profile = _profile_of(response)
    return {
        "series": profile.get("points") or [],
        "method": profile.get("method"),
        "period": profile.get("period"),
        "n_points": profile.get("n_points"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _variance_series(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = _profile_of(response)
    return {
        "series": profile.get("points") or [],
        "selected_method": profile.get("selected_method"),
        "lambda_value": profile.get("lambda_value"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _variance_rolling(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = _profile_of(response)
    return {
        "series": profile.get("points") or [],
        "selected_method": profile.get("selected_method"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _variance_methods(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = _profile_of(response)
    return {
        "candidates": profile.get("candidates") or [],
        "selected_method": profile.get("selected_method"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _variance_distribution(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = _profile_of(response)
    return {
        "bins": profile.get("histogram") or [],
        "selected_method": profile.get("selected_method"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _variance_diagnostics(response: Mapping[str, Any]) -> dict[str, Any]:
    profile = _profile_of(response)
    before = profile.get("diagnostics_before") or {}
    after = profile.get("diagnostics_after") or {}
    return {
        "cards": [
            {"label": "corr(mean, σ)", "value": after.get("mean_std_correlation")},
            {"label": "Brown–Forsythe p", "value": after.get("levene_pvalue")},
            {
                "label": "block_variance_ratio",
                "value": after.get("block_variance_ratio"),
            },
            {"label": "ARCH-LM p", "value": after.get("arch_lm_pvalue")},
        ],
        "diagnostics_before": before,
        "diagnostics_after": after,
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
    }


def _stationarity_overview(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Стационарность»: ряд до/после (chart) И сравнение
    тестов (таблица) из ОДНОГО фактического ответа (mixed-сайт)."""
    profile = _profile_of(response)
    tests = profile.get("tests") or []
    rows = [
        {
            "test": test.get("test") or test.get("label"),
            "p_before": test.get("before_p_value"),
            "p_after": test.get("after_p_value"),
        }
        for test in tests
        if isinstance(test, dict)
    ]
    return {
        "series": profile.get("points") or [],
        "tests": tests,
        "selected_method": profile.get("selected_method"),
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
        "columns": ["test", "p_before", "p_after"],
        "rows": rows,
        "row_count": len(rows),
    }


def _spectral_periodogram(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Спектральный анализ»: Welch-PSD (chart) И частотные
    диапазоны (таблица) из ОДНОГО ответа."""
    profile = _profile_of(response)
    bands = profile.get("bands") or []
    rows = [
        {
            "band": band.get("label"),
            "power_share": band.get("power_share"),
        }
        for band in bands
        if isinstance(band, dict)
    ]
    return {
        "series": profile.get("welch") or [],
        "bands": bands,
        "candidates": profile.get("candidates") or [],
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
        "columns": ["band", "power_share"],
        "rows": rows,
        "row_count": len(rows),
    }


def _feature_eng_overview(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Генерация признаков»: превью (chart) И каталог
    признаков (таблица) из ОДНОГО ответа."""
    profile = _profile_of(response)
    catalog = profile.get("catalog") or []
    rows = [
        {
            "name": item.get("name"),
            "family": item.get("family"),
            "coverage": item.get("coverage"),
        }
        for item in catalog
        if isinstance(item, dict)
    ]
    return {
        "series": profile.get("preview_points") or [],
        "catalog": catalog,
        "lag_correlations": profile.get("lag_correlations") or [],
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
        "columns": ["name", "family", "coverage"],
        "rows": rows,
        "row_count": len(rows),
    }


def _scaling_overview(response: Mapping[str, Any]) -> dict[str, Any]:
    """Остановка «Масштабирование»: превью (chart) И сравнение
    масштабов (таблица) из ОДНОГО ответа."""
    profile = _profile_of(response)
    ranges = profile.get("range_points") or []
    rows = [
        {
            "column": item.get("column"),
            "log_scale_before": item.get("log_scale_before"),
            "log_scale_after": item.get("log_scale_after"),
        }
        for item in ranges
        if isinstance(item, dict)
    ]
    return {
        "series": profile.get("preview_points") or [],
        "recommended_method": profile.get("recommended_method"),
        "range_points": ranges,
        "applicable": profile.get("applicable"),
        "reason": profile.get("reason"),
        "columns": ["column", "log_scale_before", "log_scale_after"],
        "rows": rows,
        "row_count": len(rows),
    }


def _missing_coverage_heatmap(response: Mapping[str, Any]) -> dict[str, Any]:
    """Теплокарта покрытия (PGV-03: {columns, bins,...}) -- PGV-10
    аддитивно разворачивает фактические bins (MissingMatrixBinOut:
    missing_share по колонкам) в каноническую форму html_heatmap
    {row_headings, column_headings, cells}: печатная секция строится из
    ТЕХ ЖЕ замороженных данных, без пересчёта (§6)."""
    columns = [str(c) for c in response.get("columns") or []]
    bins = response.get("bins") or []
    row_headings: list[str] = []
    cells: list[list[Any]] = []
    for bin_record in bins:
        if not isinstance(bin_record, dict):
            continue
        row_headings.append(
            f"Строки {bin_record.get('row_start')}–{bin_record.get('row_end')}"
        )
        share = bin_record.get("missing_share") or {}
        cells.append([share.get(column) for column in columns])
    return {
        "columns": columns,
        "bins": bins,
        "rows_per_bin": response.get("rows_per_bin"),
        "total_rows": response.get("total_rows"),
        "row_headings": row_headings,
        "column_headings": columns,
        "cells": cells,
    }


def _outlier_series_profile_mixed(response: Mapping[str, Any]) -> dict[str, Any]:
    """Ряд с границами метода (PGV-03 chart-форма) + PGV-10 аддитивно:
    границы колонок -- табличная форма второй секции mixed-сайта
    (ОДИН фактический ответ, без пересчёта, §6)."""
    bounds = response.get("bounds") or {}
    rows = []
    if isinstance(bounds, dict):
        for column, bound in bounds.items():
            bound_rec = bound if isinstance(bound, dict) else {}
            rows.append(
                {
                    "column": column,
                    "lower": bound_rec.get("lower"),
                    "upper": bound_rec.get("upper"),
                }
            )
    return {
        "series": response.get("points") or [],
        "bounds": bounds,
        "columns": ["column", "lower", "upper"],
        "rows": rows,
        "row_count": len(rows),
    }


def _detail_level_sampling(
    response: Mapping[str, Any], params: Optional[Mapping[str, Any]]
) -> dict[str, Any]:
    """detail_level=compact -- потолок ТОЧЕК ОТОБРАЖЕНИЯ при полном
    расчёте (Task 97.3): честный truncated с фактическим cap (AC08:
    скрытого detail upgrade нет); иначе full."""
    profile = _profile_of(response)
    points = profile.get("points") or []
    total = profile.get("n_points") or profile.get("n_observations")
    if (
        (params or {}).get("detail_level") == "compact"
        and isinstance(total, int)
        and len(points) < total
    ):
        return {
            "applicable": True,
            "mode": "truncated",
            "point_cap": len(points),
            "reason": None,
        }
    return {"applicable": True, "mode": "full", "point_cap": None, "reason": None}


def _forecast_chart(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "points": response.get("points") or [],
        "history": response.get("history") or {},
        "horizon": response.get("horizon"),
        "alpha": response.get("alpha"),
        "alpha_effective": response.get("alpha_effective"),
        "ci_method": response.get("ci_method"),
    }


def _panel_forecast_chart(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "panel": response.get("panel") or {},
        "entities": response.get("entities") or [],
        "horizon": response.get("horizon"),
    }


def _panel_forecast_table(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entities": response.get("entities") or [],
        "variables": response.get("variables") or [],
        "panel": response.get("panel") or {},
    }


def _backtest_comparison_data(
    backtests: Mapping[str, Any],
) -> dict[str, Any]:
    """Срез session.modeling_artifacts['backtests'] для вида сравнения:
    метрики и per-fold метрики каждой модели (реальные записи)."""
    models = []
    for model_id, entry in (backtests or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        models.append(
            {
                "model_id": model_id,
                "model_name": entry.get("model_name"),
                "status": entry.get("status"),
                "strategy": entry.get("strategy"),
                "metrics": entry.get("metrics") or {},
                "fold_metrics": [
                    {
                        "fold": fold.get("fold"),
                        "status": fold.get("status"),
                        "metrics": fold.get("metrics") or {},
                    }
                    for fold in (
                        entry.get("folds") or []
                        if isinstance(entry.get("folds"), list)
                        else []
                    )
                    if isinstance(fold, dict)
                ],
            }
        )
    return {"models": models, "model_count": len(models)}


def _backtest_oof_data(backtests: Mapping[str, Any]) -> dict[str, Any]:
    """OOF-ряды бэктестов (predictions fold'ов) -- реальные записи."""
    models = []
    for model_id, entry in (backtests or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        oof = entry.get("oof") if isinstance(entry.get("oof"), list) else []
        predictions = [
            point
            for fold in (
                entry.get("folds") or []
                if isinstance(entry.get("folds"), list)
                else []
            )
            if isinstance(fold, dict)
            for point in (fold.get("predictions") or [])
            if isinstance(point, dict)
        ]
        models.append(
            {
                "model_id": model_id,
                "model_name": entry.get("model_name"),
                "oof": oof,
                "fold_predictions": predictions,
            }
        )
    return {"models": models, "model_count": len(models)}


def _tasks_causes_data(response: Mapping[str, Any]) -> dict[str, Any]:
    """Срез ответа /tasks/causes: fold-важность (реальный метод ответа).
    not_computed НЕ фабрикуется: данные вида -- только available-метод
    (адаптер вызывает freeze только при available, см. wiring)."""
    return {"method": response.get("method") or {}, "card": response.get("card") or {}}


def _ih_results_data(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "results": response.get("results") or [],
        "synergies": response.get("synergies") or [],
        "recommendations": response.get("recommendations") or [],
    }


def _timeseries_data(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "series": response.get("points") or [],
        "was_resorted": response.get("was_resorted"),
        "column": response.get("column"),
        "date_column": response.get("date_column"),
    }


def _range_count(response: Mapping[str, Any]) -> int:
    return int(response.get("non_null_count") or 0)


def _series_count(response: Mapping[str, Any]) -> int:
    return len(response.get("scatter") or [])


def _points_count(response: Mapping[str, Any]) -> int:
    return len(response.get("points") or [])


def _series_count_for_eda_rolling(response: Mapping[str, Any]) -> int:
    return len(response.get("rolling") or [])


def _breaks_series_count(response: Mapping[str, Any]) -> int:
    return len(response.get("series") or [])


def _smoothing_points_count(response: Mapping[str, Any]) -> int:
    profile = response.get("profile") or {}
    return len(profile.get("points") or [])


def _forecast_points_count(response: Mapping[str, Any]) -> int:
    return len(response.get("points") or [])


def _feature_scores_count(response: Mapping[str, Any]) -> int:
    return len(response.get("features") or [])


def _folds_count(response: Mapping[str, Any]) -> int:
    return len(response.get("folds") or [])


def _windowed_histogram_sampling(
    response: Mapping[str, Any], params: Optional[Mapping[str, Any]]
) -> dict[str, Any]:
    """Гистограмма/KDE: расчёт по ПОЛНОМУ столбцу (chart_data.py) --
    честный full; на zoom-диапазоне -- windowed с фактическим числом
    точек окна (скрытого detail upgrade нет, AC08)."""
    if _is_zoom(params):
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": _range_count(response),
            "reason": None,
        }
    return {"applicable": True, "mode": "full", "point_cap": None, "reason": None}


def _units_table(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Таблицы строк/столбцов датасета: значения -- сырые данные ряда
    (units неизвестны из ответа -- legacy_unknown), счётчики --
    dimensionless. Две честные декларации вместо одной выдуманной."""
    return [
        {"value": None, "reason": "legacy_unknown"},
        {"value": "dimensionless", "reason": None},
    ]


# Алиас для таблиц upload (сырые значения + счётчики).
_UNITS_DIMENSIONLESS_TABLE = _units_table


# ── Спецификации адаптеров (48 wired view) ────────────────────────────


@dataclass(frozen=True)
class VisualAdapterSpec:
    """Декларация адаптера: срез ответа -> payload.data + units +
    sampling. Все функции чистые (никакой науки, только срез)."""

    view_id: str
    module_id: str
    renderer_kind: str  # payload.kind (mixed -> первичный kind)
    method: str
    extract: Callable[[Mapping[str, Any]], Any]
    units: Callable[[Mapping[str, Any]], list[dict[str, Any]]]
    sampling: Callable[
        [Mapping[str, Any], Optional[Mapping[str, Any]]], dict[str, Any]
    ]
    selection_keys: tuple[str, ...] = ()


def _spec(
    view_id: str,
    renderer_kind: str,
    method: str,
    extract: Callable[[Mapping[str, Any]], Any],
    units: list[dict[str, Any]] | Callable[[Mapping[str, Any]], list[dict[str, Any]]],
    sampling: Callable[
        [Mapping[str, Any], Optional[Mapping[str, Any]]], dict[str, Any]
    ]
    | dict[str, Any],
    selection_keys: tuple[str, ...] = (),
) -> VisualAdapterSpec:
    module_id = view_id.split(".", 1)[0]
    units_fn: Callable[[Mapping[str, Any]], list[dict[str, Any]]]
    if callable(units):
        units_fn = units
    else:
        units_fn = lambda _response: list(units)  # noqa: E731
    sampling_fn: Callable[
        [Mapping[str, Any], Optional[Mapping[str, Any]]], dict[str, Any]
    ]
    if callable(sampling):
        sampling_fn = sampling
    else:
        sampling_fn = lambda _response, _params: dict(sampling)  # noqa: E731
    return VisualAdapterSpec(
        view_id=view_id,
        module_id=module_id,
        renderer_kind=renderer_kind,
        method=method,
        extract=extract,
        units=units_fn,
        sampling=sampling_fn,
        selection_keys=selection_keys,
    )


_FULL = {
    "applicable": True, "mode": "full", "point_cap": None, "reason": None,
}
_DIMENSIONLESS = [{"value": "dimensionless", "reason": None}]
_PERCENT = [{"value": "percent", "reason": None}]

DISTRIBUTION_SELECTION = ("selected_column", "sampling", "bins")

ADAPTER_SPECS: dict[str, VisualAdapterSpec] = {
    # ── Upload (10) ──────────────────────────────────────────────────
    "upload.overview.preview": _spec(
        "upload.overview.preview", "html_table", "dataset_preview",
        _preview_table, _UNITS_DIMENSIONLESS_TABLE, dict(_FULL),
        selection_keys=("preview_rows", "selected_column"),
    ),
    "upload.overview.tech_table": _spec(
        "upload.overview.tech_table", "html_table", "dataset_columns_info",
        _columns_info_table, _UNITS_DIMENSIONLESS_TABLE, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "upload.quality.teaser": _spec(
        "upload.quality.teaser", "html_cards", "quality_teaser",
        _quality_cards, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "upload.chart.series": _spec(
        "upload.chart.series", "recharts_svg", "timeseries_points",
        _timeseries_data, _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="sampled", count_of=_points_count, params=p
        ),
        selection_keys=("selected_column", "window", "zoom"),
    ),
    "upload.chart.decomposition_shares": _spec(
        "upload.chart.decomposition_shares", "html_cards",
        "decomposition_shares", _decomposition_cards, _PERCENT, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "upload.chart.decomposition_series": _spec(
        "upload.chart.decomposition_series", "recharts_svg",
        "decomposition_series",
        lambda r: {"series": r.get("points") or [], "method": r.get("method")},
        _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="sampled", count_of=_points_count, params=p
        ),
        selection_keys=("selected_column",),
    ),
    "upload.distribution.scatter": _spec(
        "upload.distribution.scatter", "recharts_svg", "distribution_scatter",
        lambda r: {"series": r.get("scatter") or []},
        _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="scatter_sampled", count_of=_series_count, params=p
        ),
        selection_keys=("selected_column", "sampling"),
    ),
    "upload.distribution.histogram": _spec(
        "upload.distribution.histogram", "recharts_svg",
        "distribution_histogram",
        lambda r: {"bins": r.get("histogram") or []},
        _DIMENSIONLESS, _windowed_histogram_sampling,
        selection_keys=("selected_column", "sampling", "bins"),
    ),
    "upload.distribution.kde": _spec(
        "upload.distribution.kde", "recharts_svg", "distribution_kde",
        lambda r: {"curve": r.get("kde") or []},
        _units_unknown, _windowed_histogram_sampling,
        selection_keys=("selected_column", "sampling"),
    ),
    "upload.structure.schema": _spec(
        "upload.structure.schema", "html_table", "structure_detection",
        _structure_table, _UNITS_DIMENSIONLESS_TABLE, dict(_FULL),
        selection_keys=("detection_confidence",),
    ),
    # ── Validation (10) ──────────────────────────────────────────────
    "validation.data_types.matrix": _spec(
        "validation.data_types.matrix", "html_table", "validation_data_types",
        lambda r: _validation_check_data(r, "data_types"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.formats.chart": _spec(
        "validation.formats.chart", "recharts_svg", "validation_formats",
        lambda r: {
            "series": [
                {"x": item.get("label"), "y": item.get("count")}
                for item in _validation_check_data(r, "formats").get("items")
            ],
            "summary": {
                key: _validation_check_data(r, "formats").get(key)
                for key in ("status", "count", "scope")
            },
        },
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.ranges.overview": _spec(
        "validation.ranges.overview", "html_table", "validation_ranges",
        lambda r: _validation_check_data(r, "ranges"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.consistency.overview": _spec(
        "validation.consistency.overview", "html_table",
        "validation_consistency",
        lambda r: _validation_check_data(r, "consistency"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.uniqueness.overview": _spec(
        "validation.uniqueness.overview", "html_table",
        "validation_uniqueness",
        lambda r: _validation_check_data(r, "uniqueness"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.inclusion.overview": _spec(
        "validation.inclusion.overview", "html_table",
        "validation_inclusion",
        lambda r: _validation_check_data(r, "inclusion"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.referential.overview": _spec(
        "validation.referential.overview", "html_table",
        "validation_referential",
        lambda r: _validation_check_data(r, "referential"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.text_quality.overview": _spec(
        "validation.text_quality.overview", "html_table",
        "validation_text_quality",
        lambda r: _validation_check_data(r, "text_quality"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.regularity.overview": _spec(
        "validation.regularity.overview", "html_table",
        "validation_regularity",
        lambda r: _validation_check_data(r, "regularity"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    "validation.sufficiency.overview": _spec(
        "validation.sufficiency.overview", "html_table",
        "validation_sufficiency",
        lambda r: _validation_check_data(r, "sufficiency"),
        _DIMENSIONLESS, dict(_FULL),
    ),
    # ── Preprocessing (6) ────────────────────────────────────────────
    "preprocessing.missing.overview": _spec(
        "preprocessing.missing.overview", "html_table", "missing_profile",
        _missing_profile_table, _PERCENT, dict(_FULL),
        selection_keys=("selected_column", "denominators"),
    ),
    "preprocessing.missing.coverage_matrix": _spec(
        "preprocessing.missing.coverage_matrix", "html_heatmap",
        "missing_coverage_matrix",
        _missing_coverage_heatmap, _PERCENT, dict(_FULL),
        selection_keys=("bins", "row_window"),
    ),
    "preprocessing.missing.correlation": _spec(
        "preprocessing.missing.correlation", "html_table",
        "missing_correlation",
        lambda r: {
            "columns": r.get("columns") or [],
            "matrix": r.get("matrix") or [],
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column", "indicator_column"),
    ),
    "preprocessing.outliers.overview": _spec(
        "preprocessing.outliers.overview", "html_table", "outlier_profile",
        _outlier_profile_table, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("method", "strategy", "denominators"),
    ),
    "preprocessing.outliers.series_profile": _spec(
        "preprocessing.outliers.series_profile", "recharts_svg",
        "outlier_series_profile",
        _outlier_series_profile_mixed,
        _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="sampled", count_of=_points_count, params=p
        ),
        selection_keys=("method", "strategy", "selected_column"),
    ),
    "preprocessing.smoothing.overview": _spec(
        "preprocessing.smoothing.overview", "recharts_svg",
        "smoothing_profile", _smoothing_profile, _units_unknown,
        lambda r, p: _full_sampling(
            r, zoom_cap_of=_smoothing_points_count, params=p
        ),
        selection_keys=("method", "window", "selected_column"),
    ),
    # ── Preprocessing добор PGV-10 (12 view; недобор PGV-03 сужен) ────
    "preprocessing.regularity.overview": _spec(
        "preprocessing.regularity.overview", "html_table",
        "preprocessing_regularity_profile",
        _preprocessing_regularity_table, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "preprocessing.regularity.gap_map": _spec(
        "preprocessing.regularity.gap_map", "recharts_svg",
        "preprocessing_regularity_timeline",
        _regularity_gap_map, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("group",),
    ),
    "preprocessing.decomposition.overview": _spec(
        "preprocessing.decomposition.overview", "recharts_svg",
        "preprocessing_decomposition",
        _preprocessing_decomposition_series, _units_unknown,
        _detail_level_sampling,
        selection_keys=("selected_column", "period", "robust", "detail_level"),
    ),
    "preprocessing.variance_stab.series": _spec(
        "preprocessing.variance_stab.series", "recharts_svg",
        "variance_series",
        _variance_series, _units_unknown, dict(_FULL),
        selection_keys=("selected_column", "selected_method", "lambda_value"),
    ),
    "preprocessing.variance_stab.rolling": _spec(
        "preprocessing.variance_stab.rolling", "recharts_svg",
        "variance_rolling",
        _variance_rolling, _units_unknown, dict(_FULL),
        selection_keys=("selected_column", "selected_method"),
    ),
    "preprocessing.variance_stab.methods": _spec(
        "preprocessing.variance_stab.methods", "recharts_svg",
        "variance_methods",
        _variance_methods, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "preprocessing.variance_stab.distribution": _spec(
        "preprocessing.variance_stab.distribution", "recharts_svg",
        "variance_distribution",
        _variance_distribution, _units_unknown, dict(_FULL),
        selection_keys=("selected_column", "selected_method", "bins"),
    ),
    "preprocessing.variance_stab.diagnostics": _spec(
        "preprocessing.variance_stab.diagnostics", "html_cards",
        "variance_diagnostics",
        _variance_diagnostics, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "preprocessing.stationarity.overview": _spec(
        "preprocessing.stationarity.overview", "recharts_svg",
        "stationarity_profile",
        _stationarity_overview, _units_table, dict(_FULL),
        selection_keys=("selected_column", "alpha"),
    ),
    "preprocessing.spectral.periodogram": _spec(
        "preprocessing.spectral.periodogram", "recharts_svg",
        "spectral_periodogram",
        _spectral_periodogram, _units_table, dict(_FULL),
        selection_keys=("selected_column", "detail_level"),
    ),
    "preprocessing.feature_eng.overview": _spec(
        "preprocessing.feature_eng.overview", "recharts_svg",
        "feature_engineering_overview",
        _feature_eng_overview, _units_table, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    "preprocessing.scaling.overview": _spec(
        "preprocessing.scaling.overview", "recharts_svg",
        "scaling_overview",
        _scaling_overview, _units_table, dict(_FULL),
        selection_keys=("selected_column",),
    ),
    # ── EDA (16) ─────────────────────────────────────────────────────
    "eda.descriptive.stats": _spec(
        "eda.descriptive.stats", "html_table", "descriptive_stats",
        _stats_table_data, _UNITS_DIMENSIONLESS_TABLE, dict(_FULL),
        selection_keys=("selected_column", "comparison_stage"),
    ),
    "eda.descriptive.distribution.scatter": _spec(
        "eda.descriptive.distribution.scatter", "recharts_svg",
        "eda_distribution_scatter",
        lambda r: {"series": r.get("scatter") or []},
        _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="scatter_sampled", count_of=_series_count, params=p
        ),
        selection_keys=("selected_column", "sampling"),
    ),
    "eda.descriptive.distribution.histogram": _spec(
        "eda.descriptive.distribution.histogram", "recharts_svg",
        "eda_distribution_histogram",
        lambda r: {"bins": r.get("histogram") or []},
        _DIMENSIONLESS, _windowed_histogram_sampling,
        selection_keys=("selected_column", "bins", "sampling"),
    ),
    "eda.descriptive.distribution.kde": _spec(
        "eda.descriptive.distribution.kde", "recharts_svg",
        "eda_distribution_kde",
        lambda r: {"curve": r.get("kde") or []},
        _units_unknown, _windowed_histogram_sampling,
        selection_keys=("selected_column", "sampling"),
    ),
    "eda.correlation.acf_pacf": _spec(
        "eda.correlation.acf_pacf", "recharts_svg", "acf_pacf",
        lambda r: {
            "acf": r.get("acf") or [],
            "pacf": r.get("pacf") or [],
            "max_lag": r.get("max_lag"),
            "order_source": r.get("order_source"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        # ось лагов -- время в единицах ряда (units неизвестны);
        # коэффициенты корреляции -- dimensionless. Две честные
        # декларации вместо одной выдуманной.
        _units_table, dict(_FULL),
        selection_keys=("lags", "selected_column"),
    ),
    "eda.ih.metrics_table": _spec(
        "eda.ih.metrics_table", "html_table", "ih_metrics",
        lambda r: {
            "results": r.get("results") or [],
            "target_entropy": r.get("target_entropy"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("factor_column", "bins"),
    ),
    "eda.ih.conditional_map": _spec(
        "eda.ih.conditional_map", "html_table", "ih_conditional_map",
        lambda r: {
            "matrix": r.get("conditional_matrix") or [],
            "x_bins": r.get("conditional_x_bins"),
            "y_bins": r.get("conditional_y_bins"),
            "conditional_feature": r.get("conditional_feature"),
            "applicable": r.get("applicable"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("factor_column", "bins"),
    ),
    "eda.ih.results": _spec(
        "eda.ih.results", "html_table", "ih_results", _ih_results_data,
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("factor_column",),
    ),
    "eda.seasonality.spectrum": _spec(
        "eda.seasonality.spectrum", "recharts_svg", "seasonality_spectrum",
        lambda r: {
            "fft": r.get("fft") or [],
            "periodogram": r.get("periodogram") or [],
            "dominant_period": r.get("dominant_period"),
            "dominant_strength": r.get("dominant_strength"),
            "spectral_entropy": r.get("spectral_entropy"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("window", "selected_column"),
    ),
    "eda.stationarity.tests": _spec(
        "eda.stationarity.tests", "html_table", "stationarity_tests",
        lambda r: {
            "tests": r.get("tests") or [],
            "consensus": r.get("consensus"),
            "recommendation": r.get("recommendation"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("test", "selected_column"),
    ),
    "eda.distribution.tests": _spec(
        "eda.distribution.tests", "html_table", "distribution_tests",
        lambda r: {
            "tests": r.get("tests") or [],
            "summary": {
                key: r.get(key)
                for key in ("mean", "median", "std", "skewness", "excess_kurtosis")
            },
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("selected_column", "bins"),
    ),
    "eda.structural.breakpoints": _spec(
        "eda.structural.breakpoints", "recharts_svg", "structural_breaks",
        lambda r: {
            "series": r.get("series") or [],
            "cusum": r.get("cusum") or [],
            "segments": r.get("segments") or [],
            "break_count": r.get("break_count"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _units_unknown, lambda r, p: _series_sampling(
            r, sampled_key="series_sampled", count_of=_breaks_series_count, params=p
        ),
        selection_keys=("method", "selected_column"),
    ),
    "eda.feature_select.scores": _spec(
        "eda.feature_select.scores", "recharts_svg", "feature_scores",
        lambda r: {
            "features": r.get("features") or [],
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("method", "selected_column"),
    ),
    "eda.feature_select.matrix": _spec(
        "eda.feature_select.matrix", "html_heatmap", "feature_matrix",
        lambda r: {
            "matrix": r.get("correlation_matrix") or [],
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("method", "selected_column"),
    ),
    "eda.validation_strategy.windows": _spec(
        "eda.validation_strategy.windows", "recharts_svg",
        "validation_strategy_windows",
        lambda r: {
            "folds": r.get("folds") or [],
            "strategy": r.get("strategy"),
            "horizon": r.get("horizon"),
            "gap": r.get("gap"),
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("strategy", "horizon", "gap"),
    ),
    "eda.model_matrix.applicability": _spec(
        "eda.model_matrix.applicability", "html_table", "model_matrix",
        lambda r: {
            "families": r.get("families") or [],
            "models": r.get("models") or [],
            "summary": r.get("summary") or {},
            "applicable": r.get("applicable"),
            "reason": r.get("reason"),
        },
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("family_filter",),
    ),
    # ── Modeling (2) ─────────────────────────────────────────────────
    "modeling.backtest.comparison": _spec(
        "modeling.backtest.comparison", "recharts_svg", "backtest_comparison",
        lambda r: _backtest_comparison_data(r.get("backtests") or {}),
        _DIMENSIONLESS, dict(_FULL),
        selection_keys=("metric", "models", "folds"),
    ),
    "modeling.backtest.oof": _spec(
        "modeling.backtest.oof", "recharts_svg", "backtest_oof",
        lambda r: _backtest_oof_data(r.get("backtests") or {}),
        _units_unknown, dict(_FULL),
        selection_keys=("fold", "window"),
    ),
    # ── Forecasting (3) ──────────────────────────────────────────────
    "forecasting.forecast.chart": _spec(
        "forecasting.forecast.chart", "recharts_svg", "forecast_chart",
        _forecast_chart, _units_unknown, lambda r, p: _full_sampling(
            r, zoom_cap_of=_forecast_points_count, params=p
        ),
        selection_keys=("origin", "horizon", "alpha", "intervals", "history_window"),
    ),
    "forecasting.forecast.panel_chart": _spec(
        "forecasting.forecast.panel_chart", "recharts_svg",
        "panel_forecast_chart", _panel_forecast_chart, _units_unknown,
        dict(_FULL),
        selection_keys=("entity", "origin", "horizon"),
    ),
    "forecasting.forecast.panel_table": _spec(
        "forecasting.forecast.panel_table", "html_table",
        "panel_forecast_table", _panel_forecast_table, _DIMENSIONLESS,
        dict(_FULL),
        selection_keys=("entity",),
    ),
    # ── Tasks (1) ────────────────────────────────────────────────────
    "tasks.causes.fold_importance": _spec(
        "tasks.causes.fold_importance", "recharts_svg", "xai_fold_importance",
        _tasks_causes_data, _DIMENSIONLESS, dict(_FULL),
        selection_keys=("method",),
    ),
}


def wired_view_ids() -> tuple[str, ...]:
    """View с адаптерами этой поставки (48; во всех семи остановках)."""
    return tuple(sorted(ADAPTER_SPECS))


def adapter_specs() -> dict[str, VisualAdapterSpec]:
    """Словарь спецификаций (копия -- защита от мутаций извне)."""
    return dict(ADAPTER_SPECS)


def adapter_spec(view_id: str) -> VisualAdapterSpec:
    spec = ADAPTER_SPECS.get(view_id)
    if spec is None:
        # resolve даёт честную ошибку скоупа (unknown/demo/unwired)
        resolve_producer_view(view_id)
        raise UnknownVisualView(f"адаптер не зарегистрирован: {view_id!r}")
    return spec


# ── result_ref: детерминированный токен результата (§6) ──────────────


def visual_result_ref(
    params: Optional[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> str:
    """vr-<sha256[:32]> от (params, response): те же данные и selection
    -- тот же ref (идемпотентность §11); zoom/новая ревизия данных --
    другой ref (AC08/§8: новый immutable артефакт)."""
    from apps.api.artifact_store import canonical_json_bytes

    body = canonical_json_bytes(
        {"params": dict(params or {}), "response": response}
    )
    return "vr-" + hashlib.sha256(body).hexdigest()[:32]


# ── Кэш сохранённых ответов (субстрат lazy transfer, §6) ─────────────


@dataclass(frozen=True)
class SavedVisualResponse:
    """Фактический ответ научной остановки, сохранённый в момент выдачи
    (контекст момента: run/session/context/revision/computed_at),
    изолированный глубокой копией от источника (PGV-03-FIX, F-P3C3).
    computed_at -- время фиксации: от производителя; None -- честно «не
    сообщено», подстановка wall-clock запрещена (PGV-03-FIX, F-P3C2);
    для прямых вызовов кэша без времени -- момент сохранения."""

    run_id: str
    session_id: str
    result_ref: str
    response: dict[str, Any]
    params: dict[str, Any]
    context_id: Optional[str]
    data_revision: Optional[int]
    computed_at: Optional[str]
    view_ids: tuple[str, ...] = ()


VISUAL_RESPONSE_CACHE_MAX_ENTRIES = 256
_VISUAL_RESPONSE_CACHE: "OrderedDict[str, SavedVisualResponse]" = OrderedDict()

# Сентинел дефолта computed_at: «время не передано -- кэш-запись хранит
# момент сохранения». ЯВНЫЙ None означает противоположное -- «производитель
# время НЕ сообщил» -- и хранится как None без подстановки wall-clock
# (PGV-03-FIX, F-P3C2: wiring-канал обязан передавать время как есть).
_SAVE_MOMENT: Any = object()


def reset_visual_response_cache_for_testing() -> None:
    _VISUAL_RESPONSE_CACHE.clear()


def save_visual_response(
    session: Any,
    *,
    response: Mapping[str, Any],
    params: Optional[Mapping[str, Any]] = None,
    view_ids: tuple[str, ...] = (),
    computed_at: Any = _SAVE_MOMENT,
) -> Optional[str]:
    """Сохранить фактический ответ (LRU, process-local) и вернуть его
    result_ref. Честные пропуски: нет датасета/run -- трассы ещё нет,
    документировать нечего (§6 lazy transfer требует run для freeze);
    неканоничное содержимое/неизолируемый снимок -- тоже честный пропуск.
    Не бросает на состоянии сессии -- return None.

    Время фиксации (PGV-03-FIX, F-P3C2): аргумент не передан (default
    _SAVE_MOMENT -- прямые вызовы кэша) -- запись хранит момент
    сохранения; computed_at=None -- производитель время НЕ сообщил --
    запись хранит None БЕЗ подстановки wall-clock (контракт
    build_visual_result_payload: None -> честная причина
    producer_not_reported, время вызова не подставляется); строка --
    время производителя. Wiring-канал notify_visual_result передаёт
    аргумент как есть -- кэш-запись и payload несут одно время."""
    run_id = str(getattr(session, "run_id", "") or "")
    if not run_id:
        return None
    if getattr(session, "dataset", None) is None:
        return None
    try:
        # F-P3C3 (PGV-03-FIX): глубокая копия снимка -- «фактический
        # ответ, сохранённый в момент выдачи» защищён от пост-мутаций
        # источника: вложенные структуры не разделяются с вызывателем.
        response_snapshot = copy.deepcopy(dict(response))
        params_snapshot = copy.deepcopy(dict(params or {}))
        # ref считается по снимку: сохранённое и его токен согласованы.
        ref = visual_result_ref(params_snapshot, response_snapshot)
    except Exception:
        # Неканоничный ответ/неизолируемый снимок -- честный пропуск кэша
        # (freeze ответит отказом гейта; повторная попытка не нужна).
        return None
    if computed_at is _SAVE_MOMENT:
        # Прямой вызов кэша без времени: момент сохранения -- лучшее
        # известное время фиксации (докстринг SavedVisualResponse).
        entry_computed_at: Any = _now_iso()
    else:
        # None -- производитель время не сообщил (честно, без
        # подстановки); строка -- время производителя (as-is).
        entry_computed_at = computed_at
    entry = SavedVisualResponse(
        run_id=run_id,
        session_id=str(getattr(session, "session_id", "") or ""),
        result_ref=ref,
        response=response_snapshot,
        params=params_snapshot,
        context_id=_session_context_id(session),
        data_revision=_session_data_revision(session),
        computed_at=entry_computed_at,
        view_ids=tuple(view_ids),
    )
    _VISUAL_RESPONSE_CACHE.pop(ref, None)
    _VISUAL_RESPONSE_CACHE[ref] = entry
    while len(_VISUAL_RESPONSE_CACHE) > VISUAL_RESPONSE_CACHE_MAX_ENTRIES:
        _VISUAL_RESPONSE_CACHE.popitem(last=False)
    return ref


def get_saved_visual_response(
    run_id: str, result_ref: str
) -> Optional[SavedVisualResponse]:
    """Сохранённый ответ по ref (LRU-hit двигает запись в конец)."""
    entry = _VISUAL_RESPONSE_CACHE.get(result_ref)
    if entry is None or entry.run_id != run_id:
        return None
    _VISUAL_RESPONSE_CACHE.move_to_end(result_ref)
    return entry


def _session_context_id(session: Any) -> Optional[str]:
    try:
        return session.current_context_id()
    except Exception:  # pragma: no cover -- честная деградация
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _session_data_revision(session: Any) -> Optional[int]:
    revision = getattr(session, "data_revision", None)
    if isinstance(revision, bool) or not isinstance(revision, int):
        return None
    return revision


# ── Сборка payload VisualResult/1 (зеркало правил PGV-01) ────────────

PRINT_RESULT_SCHEMA_VERSION_LOCAL = "pgv.visual_result/1"


def build_visual_result_payload(
    view_id: str,
    response: Mapping[str, Any],
    *,
    result_ref: str,
    computed_at: Optional[str],
    params: Optional[Mapping[str, Any]] = None,
    origin: str = TRUSTED_ORIGIN_FREEZE,
    warnings: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """VisualResult/1 из фактического ответа (spec §6): нормализованный
    срез результата + digest + честные units/sampling + trusted
    parameters + execution (result_ref/computed_at). Никакой науки."""
    if origin not in (TRUSTED_ORIGIN_FREEZE, TRUSTED_ORIGIN_FIRST_EXPORT):
        raise VisualProducerError(
            f"origin {origin!r} не является trusted (PGV-01: "
            "producer_freeze/producer_first_export)"
        )
    site = resolve_producer_view(view_id)
    spec = adapter_spec(view_id)
    data = spec.extract(response)
    from apps.api.artifact_store import (
        SerializationError,
        artifact_content_sha256,
        canonical_json_bytes,
    )

    try:
        digest = artifact_content_sha256(canonical_json_bytes(data))
    except SerializationError as exc:
        # Неканоничный срез (NaN/Infinity): честный отказ -- «gap, не
        # готовая картинка» (§8); время вызова не подставляется.
        raise VisualProducerError(
            f"Срез результата {view_id} неканоничен (честный отказ): {exc}"
        ) from exc
    trusted_params = {
        key: (params or {}).get(key)
        for key in spec.selection_keys
        if (params or {}).get(key) is not None
    }
    sampling = spec.sampling(response, params)
    return {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION_LOCAL,
        "view_id": view_id,
        "payload": {
            "kind": spec.renderer_kind,
            "series_cap": sampling.get("point_cap"),
            "digest": digest,
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": origin,
            "method": spec.method,
            "parameters": trusted_params,
        },
        "units": spec.units(response),
        "sampling": sampling,
        "warnings": list(warnings or []),
        "execution": {
            "execution_ref": f"producer:{site.get('source_adapter', 'pgv-03')}",
            "result_ref": result_ref,
            "computed_at": computed_at,
            "computed_at_reason": (
                None if computed_at else "producer_not_reported"
            ),
        },
    }


# ── Freeze-оркестрация (поверх PGV-02 durable-слоя) ──────────────────


def freeze_visual_from_response(
    run_id: str,
    subject: Any,
    *,
    view_id: str,
    response: Mapping[str, Any],
    session_id: str = "",
    params: Optional[Mapping[str, Any]] = None,
    computed_at: Optional[str] = None,
    origin: str = TRUSTED_ORIGIN_FREEZE,
    expected_context_id: Optional[str] = None,
    expected_data_revision: Optional[int] = None,
    created_by: Optional[str] = None,
    warnings: Optional[list[Any]] = None,
) -> Any:
    """Freeze VisualResult из фактического ответа (producer_freeze /
    producer_first_export): сборка payload -> freeze_visual_result
    (PGV-02) с CAS по явным expected_* (AC07: расхождение -> 409
    context_changed, ничего не регистрируется)."""
    payload = build_visual_result_payload(
        view_id,
        response,
        result_ref=visual_result_ref(params, response),
        computed_at=computed_at,
        params=params,
        origin=origin,
        warnings=warnings,
    )
    from apps.api.visual_artifacts import freeze_visual_result

    return freeze_visual_result(
        run_id,
        subject,
        payload=payload,
        session_id=session_id,
        expected_context_id=expected_context_id,
        expected_data_revision=expected_data_revision,
        created_by=created_by,
    )


def freeze_saved_visual(
    run_id: str,
    subject: Any,
    *,
    view_id: str,
    result_ref: str,
    session_id: str = "",
    created_by: Optional[str] = None,
) -> Any:
    """Первый explicit export (producer_first_export; §6): freeze
    СОХРАНЁННОГО ответа по result_ref БЕЗ пересчёта науки (AC06 --
    renderer не вызывает GET для повторной науки). CAS ВСЕГДА сверяет
    контекст сохранённого ответа с текущим durable-состоянием запуска
    (AC07: смена данных между показом и export -> 409 context_changed;
    клиент выбирает обновление или уже сохранённую версию).

    PGV-03-FIX (F-P3C1) -- «ВСЕГДА» enforced: сверка возможна только
    при ПОЛНОМ снимке контекста момента ответа. Деградировавший снимок
    не даёт доказательства неизменности durable-состояния -- fail-closed,
    НЕ тихий пропуск сверки (класс F-P2C2, прецедент PGV-02-FIX):
    пустой снимок (context_id и data_revision неизвестны) -- честный
    VisualSourceUnavailable; частичный снимок -- PrintContextConflict
    (409 context_changed); НИЧЕГО не регистрируется."""
    # Сначала честный резолв вида (unknown/out-of-scope -- до кэша,
    # чтобы семантика ошибок не зависела от состояния кэша).
    resolve_producer_view(view_id)
    saved = get_saved_visual_response(run_id, result_ref)
    if saved is None:
        raise VisualSourceUnavailable(
            "Сохранённый ответ для result_ref недоступен (вытеснен из "
            "кэша либо ответ другого запуска) -- source_unavailable; "
            "повторный экспорт после обновления представления "
            "(пересчёт науки не выполняется)"
        )
    # CAS ВСЕГДА (PGV-03-FIX, F-P3C1): полный снимок -- сверку обоих
    # измерений выполняет PGV-02 (expected_* ниже); деградировавший --
    # fail-closed отказ: экспорт «мимо сверки» невозможен.
    if saved.context_id is None and saved.data_revision is None:
        raise VisualSourceUnavailable(
            "Сохранённый ответ не несёт контекста момента (context_id и "
            "data_revision неизвестны) -- безопасный экспорт невозможен, "
            "сверять нечем (source_unavailable); обновите представление "
            "(новый ответ -> новый полный снимок)"
        )
    if saved.context_id is None or saved.data_revision is None:
        from apps.api.visual_artifacts import PrintContextConflict

        raise PrintContextConflict(
            "freeze_saved_visual: снимок контекста сохранённого ответа "
            f"неполон (context_id={saved.context_id!r}, "
            f"data_revision={saved.data_revision!r}) -- сверка «CAS "
            "ВСЕГДА» невозможна честно -- 409 context_changed: обновите "
            "представление или выберите сохранённую версию"
        )
    return freeze_visual_from_response(
        run_id,
        subject,
        view_id=view_id,
        response=saved.response,
        session_id=session_id,
        params=saved.params,
        computed_at=saved.computed_at,
        origin=TRUSTED_ORIGIN_FIRST_EXPORT,
        # CAS: ожидание = контекст МОМЕНТА ОТВЕТА (то, что видел клиент)
        expected_context_id=saved.context_id,
        expected_data_revision=saved.data_revision,
        created_by=created_by,
    )


def list_run_visual_results_count(run_id: str, view_id: str) -> int:
    """Число visual_result запуска по view (для счётчиков sweep; без
    SessionStore/Redis)."""
    try:
        from apps.api.visual_artifacts import list_visual_results

        return len(list_visual_results(run_id, view_id=view_id))
    except Exception:  # pragma: no cover -- счётчик не критичен
        return 0
