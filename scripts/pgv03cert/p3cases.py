# scripts/pgv03cert/p3cases.py
#
# PGV-03-CERT — СОБСТВЕННЫЕ данные сертификатора (оракулы на своих данных).
#
# Namespace: p3cert-* (дизъюнктен с repo-сюитой tests/api/
# test_pgv03_producer_adapters.py и корпусами p0cert-*/p1cert-*/p2cert-*).
# Ни один оракул здесь не импортирует repo-фикстуры/билдеры: ответы
# научных остановок транскрибированы НЕЗАВИСИМО по формам реальных
# обработчиков (FastAPI-модели ответов), ожидания units/sampling/data --
# моя собственная транскрипция контракта честности spec §6 («не выдумывать
# единицы», sampling из реальных полей, AC05/AC08) и докстрингов модуля.
#
# Ожидания прегистрированы: если реализация расходится с транскрипцией --
# детерминированный RED (либо дефект оракула -- тогда он честно
# исправляется ДО кампании с записью в акте, либо находка).

from __future__ import annotations

import hashlib
import json
from typing import Any

VISUAL_RESULT_VERSION = "pgv.visual_result/1"

# ── Свои ответы научных остановок (независимая транскрипция форм) ────


def timeseries_response(*, sampled: bool = False, n_points: int = 5) -> dict[str, Any]:
    """GET /dataset/timeseries: ряд + флаги LTTB-прореживания."""
    return {
        "points": [{"x": i, "y": float(i * 2)} for i in range(n_points)],
        "sampled": sampled,
        "column": "value",
        "date_column": "date",
        "was_resorted": False,
    }


def scatter_response(*, sampled: bool = True, n_points: int = 4) -> dict[str, Any]:
    """GET /dataset/distribution: scatter + scatter_sampled."""
    return {
        "column": "value",
        "non_null_count": 500,
        "scatter": [{"x": i, "y": float(i)} for i in range(n_points)],
        "scatter_sampled": sampled,
        "scatter_sampling_method": "lttb" if sampled else None,
        "scatter_original_count": 500,
        "histogram": [],
        "kde": None,
    }


def histogram_response(*, non_null: int = 123, n_bins: int = 3) -> dict[str, Any]:
    return {
        "column": "value",
        "non_null_count": non_null,
        "scatter": [],
        "scatter_sampled": False,
        "scatter_sampling_method": None,
        "scatter_original_count": non_null,
        "histogram": [{"bin_start": i, "bin_end": i + 1, "count": i * 10} for i in range(n_bins)],
        "kde": None,
    }


def preview_response() -> dict[str, Any]:
    return {
        "preview": {
            "head": [{"date": "2026-01-01", "value": 1.0}],
            "tail": [{"date": "2026-01-02", "value": 2.0}],
        },
        "rows_total": 2,
        "columns_total": 2,
    }


def columns_info_response() -> dict[str, Any]:
    return {
        "columns_info": [
            {"name": "date", "dtype": "object", "type_icon": "📅", "non_null": 2, "nulls": 0, "unique": 2},
            {"name": "value", "dtype": "float64", "type_icon": "#", "non_null": 2, "nulls": 0, "unique": 2},
        ],
        "rows_total": 2,
        "columns_total": 2,
    }


def quality_response() -> dict[str, Any]:
    return {
        "quality": {
            "cols_with_missing": 1,
            "cols_with_outliers": 0,
            "rows_total": 100,
            "duplicates": 2,
        }
    }


def validation_checks_response() -> dict[str, Any]:
    return {
        "checks": {
            "data_types": {
                "status": "pass",
                "count": 1,
                "scope": "column",
                "rule_source": "dtype",
                "mode": "strict",
                "error": None,
                "items": [{"column": "value", "ok": True}],
            }
        }
    }


def stats_response() -> dict[str, Any]:
    return {
        "columns": [
            {
                "name": "value",
                "non_null_count": 10,
                "stats": {
                    "mean": 1.5, "median": 1.5, "std": 0.7,
                    "q1": 1.0, "q3": 2.0, "iqr": 1.0,
                    "skewness": 0.0, "kurtosis": -1.2,
                },
            }
        ]
    }


def acf_response() -> dict[str, Any]:
    return {
        "acf": [{"lag": 0, "value": 1.0}, {"lag": 1, "value": 0.5}],
        "pacf": [{"lag": 0, "value": 1.0}],
        "max_lag": 10,
        "order_source": "min(10, n//2)",
        "applicable": True,
        "reason": None,
    }


def missing_profile_response() -> dict[str, Any]:
    return {
        "total_rows": 100,
        "total_columns": 4,
        "total_missing": 5,
        "missing_rate_pct": 1.25,
        "rows_with_missing": 3,
        "rows_with_missing_pct": 3.0,
        "empty_rows": 0,
        "columns": [{"column": "a", "missing": 5, "rate_pct": 5.0}],
        "row_histogram": [{"bin": "0", "rows": 97}],
    }


def backtests_response() -> dict[str, Any]:
    return {
        "backtests": {
            "arima": {
                "model_name": "ARIMA",
                "status": "done",
                "strategy": "expanding",
                "metrics": {"mae": 1.1, "rmse": 1.4},
                "folds": [
                    {
                        "fold": 1,
                        "status": "done",
                        "metrics": {"mae": 1.2},
                        "predictions": [{"x": 1, "y": 2.0}],
                    }
                ],
                "oof": [{"x": 1, "y": 2.0}],
            }
        }
    }


def smoothing_response(*, n_points: int = 6) -> dict[str, Any]:
    """GET /preprocessing/smoothing: профиль сглаживания с точками."""
    return {
        "profile": {
            "applicable": True,
            "reason": None,
            "selected_method": "moving_average",
            "selected_parameters": {"window": 3},
            "needs_smoothing": True,
            "diagnostics_before": {"adf_p": 0.4},
            "diagnostics_after": {"adf_p": 0.02},
            "points": [{"x": i, "y": float(i)} for i in range(n_points)],
        }
    }


def forecast_response(*, n_points: int = 5) -> dict[str, Any]:
    """POST /forecast: прогнозная диаграмма."""
    return {
        "points": [{"x": i, "y": float(i)} for i in range(n_points)],
        "history": {"series": []},
        "horizon": 12,
        "alpha": 0.3,
        "alpha_effective": 0.3,
        "ci_method": "normal",
    }


# ── Канонические bytes/хэш (собственная реализация, не импорт repo) ──


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: Any) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


# ── Прегистрированные ожидания units/sampling/data ──────────────────
# Формат: словарь ожидаемых фрагментов payload VisualResult/1.
# units -- ПОЛНЫЙ список; sampling -- ПОЛНЫЙ словарь; data -- ключи среза.

RAW_SERIES_UNITS = [{"value": None, "reason": "legacy_unknown"}]
TWO_DECL_UNITS = [{"value": None, "reason": "legacy_unknown"}, {"value": "dimensionless", "reason": None}]
DIMENSIONLESS_UNITS = [{"value": "dimensionless", "reason": None}]
PERCENT_UNITS = [{"value": "percent", "reason": None}]

FULL_SAMPLING = {"applicable": True, "mode": "full", "point_cap": None, "reason": None}


def downsampled_sampling(cap: int) -> dict[str, Any]:
    return {"applicable": True, "mode": "downsampled", "point_cap": cap, "reason": None}


def windowed_sampling(cap: int) -> dict[str, Any]:
    return {"applicable": True, "mode": "windowed", "point_cap": cap, "reason": None}


# ── Реестр unit-кейсов: id → описание ────────────────────────────────
# Каждый кейс: view_id, response, params, computed_at, ожидания payload.

def unit_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(
        cid: str,
        view_id: str,
        response: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        computed_at: str | None = None,
        units: list[dict[str, Any]],
        sampling: dict[str, Any],
        data_keys: set[str] | frozenset[str],
        data_eq: Any = None,
        trusted_params: dict[str, Any],
        method: str,
        kind: str,
    ) -> None:
        cases.append(
            {
                "id": cid,
                "view_id": view_id,
                "response": response,
                "params": params,
                "computed_at": computed_at,
                "expected_units": units,
                "expected_sampling": sampling,
                "expected_data_keys": data_keys,
                "expected_data_eq": data_eq,
                "expected_trusted_params": trusted_params,
                "expected_method": method,
                "expected_kind": kind,
            }
        )

    # ── Сериальные виды: raw ряд -- legacy_unknown; sampled → downsampled ─
    add(
        "U01", "upload.chart.series", timeseries_response(),
        units=RAW_SERIES_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"series", "was_resorted", "column", "date_column"}),
        trusted_params={}, method="timeseries_points", kind="recharts_svg",
    )
    add(
        "U02", "upload.chart.series", timeseries_response(sampled=True, n_points=7),
        units=RAW_SERIES_UNITS, sampling=downsampled_sampling(7),
        data_keys=frozenset({"series", "was_resorted", "column", "date_column"}),
        trusted_params={}, method="timeseries_points", kind="recharts_svg",
    )
    add(
        "U03", "upload.chart.series", timeseries_response(n_points=9),
        params={"selected_column": "value", "start": 2, "end": 5},
        units=RAW_SERIES_UNITS, sampling=windowed_sampling(9),
        data_keys=frozenset({"series", "was_resorted", "column", "date_column"}),
        # zoom -- не в selection_keys вида: в trusted-параметры не попадает,
        # но sampling переводит в windowed (честный след окна, AC08).
        trusted_params={"selected_column": "value"},
        method="timeseries_points", kind="recharts_svg",
    )
    add(
        "U04", "upload.distribution.scatter", scatter_response(sampled=True),
        units=RAW_SERIES_UNITS, sampling=downsampled_sampling(4),
        data_keys=frozenset({"series"}),
        trusted_params={}, method="distribution_scatter", kind="recharts_svg",
    )
    add(
        "U05", "upload.distribution.scatter", scatter_response(sampled=False),
        params={"selected_column": "v", "sampling": "lttb"},
        units=RAW_SERIES_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"series"}),
        trusted_params={"selected_column": "v", "sampling": "lttb"},
        method="distribution_scatter", kind="recharts_svg",
    )
    # ── Гистограмма: dimensionless; zoom → windowed cap=non_null_count ──
    add(
        "U06", "upload.distribution.histogram", histogram_response(),
        units=DIMENSIONLESS_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"bins"}),
        trusted_params={}, method="distribution_histogram", kind="recharts_svg",
    )
    add(
        "U07", "upload.distribution.histogram", histogram_response(non_null=55, n_bins=4),
        params={"selected_column": "value", "start": 0, "end": 55},
        units=DIMENSIONLESS_UNITS, sampling=windowed_sampling(55),
        data_keys=frozenset({"bins"}),
        trusted_params={"selected_column": "value"},
        method="distribution_histogram", kind="recharts_svg",
    )
    # ── Таблицы: две декларации (сырые значения + счётчики) ─────────────
    add(
        "U08", "upload.overview.preview", preview_response(),
        units=TWO_DECL_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"tables"}),
        trusted_params={}, method="dataset_preview", kind="html_table",
    )
    add(
        "U09", "upload.overview.tech_table", columns_info_response(),
        units=TWO_DECL_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"columns", "rows", "row_count"}),
        trusted_params={}, method="dataset_columns_info", kind="html_table",
    )
    add(
        "U10", "eda.descriptive.stats", stats_response(),
        units=TWO_DECL_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"columns", "rows", "row_count"}),
        trusted_params={}, method="descriptive_stats", kind="html_table",
    )
    # ── Карточки/валидация/percent/ACF ──────────────────────────────────
    add(
        "U11", "upload.quality.teaser", quality_response(),
        units=DIMENSIONLESS_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"cards"}),
        trusted_params={}, method="quality_teaser", kind="html_cards",
    )
    add(
        "U12", "validation.data_types.matrix", validation_checks_response(),
        units=DIMENSIONLESS_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"check_id", "status", "count", "scope", "rule_source", "mode", "error", "items"}),
        data_eq={
            "check_id": "data_types",
            "status": "pass",
            "count": 1,
            "scope": "column",
            "rule_source": "dtype",
            "mode": "strict",
            "error": None,
            "items": [{"column": "value", "ok": True}],
        },
        trusted_params={}, method="validation_data_types", kind="html_table",
    )
    add(
        "U13", "preprocessing.missing.overview", missing_profile_response(),
        units=PERCENT_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"summary", "columns", "row_histogram"}),
        trusted_params={}, method="missing_profile", kind="html_table",
    )
    add(
        "U14", "eda.correlation.acf_pacf", acf_response(),
        units=TWO_DECL_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"acf", "pacf", "max_lag", "order_source", "applicable", "reason"}),
        trusted_params={}, method="acf_pacf", kind="recharts_svg",
    )
    # ── Backtests-срез (sweep-канал) ────────────────────────────────────
    add(
        "U15", "modeling.backtest.comparison", backtests_response(),
        units=DIMENSIONLESS_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({"models", "model_count"}),
        data_eq=None,
        trusted_params={}, method="backtest_comparison", kind="recharts_svg",
    )
    # ── Windowed через zoom_cap_of (усиление после M09 SURVIVED) ────────
    add(
        "U16", "preprocessing.smoothing.overview", smoothing_response(),
        params={"method": "moving_average", "start": 0, "end": 6},
        units=RAW_SERIES_UNITS, sampling=windowed_sampling(6),
        data_keys=frozenset({
            "applicable", "reason", "selected_method", "selected_parameters",
            "needs_smoothing", "diagnostics_before", "diagnostics_after", "points",
        }),
        trusted_params={"method": "moving_average"},
        method="smoothing_profile", kind="recharts_svg",
    )
    add(
        "U17", "preprocessing.smoothing.overview", smoothing_response(),
        units=RAW_SERIES_UNITS, sampling=FULL_SAMPLING,
        data_keys=frozenset({
            "applicable", "reason", "selected_method", "selected_parameters",
            "needs_smoothing", "diagnostics_before", "diagnostics_after", "points",
        }),
        trusted_params={}, method="smoothing_profile", kind="recharts_svg",
    )
    add(
        "U18", "forecasting.forecast.chart", forecast_response(),
        params={"origin": 0, "horizon": 12, "start": 0, "end": 5},
        units=RAW_SERIES_UNITS, sampling=windowed_sampling(5),
        data_keys=frozenset({"points", "history", "horizon", "alpha", "alpha_effective", "ci_method"}),
        # origin=0 -- валидное значение (не None): входит в trusted;
        # start/end вне selection_keys вида -- в параметрах не видны.
        trusted_params={"origin": 0, "horizon": 12},
        method="forecast_chart", kind="recharts_svg",
    )
    return cases


# ── Ожидания честности execution/origin (сквозные для всех кейсов) ───

EXECUTION_CONTRACT = {
    # computed_at=None → честная причина, время вызова НЕ подставляется
    # (докстринг build_visual_result_payload, док поставки §3.3).
    "none_computed_at_reason": "producer_not_reported",
    "provided_computed_at_reason": None,
}

ORIGIN_REFUSED = "client_request"  # не trusted → VisualProducerError
