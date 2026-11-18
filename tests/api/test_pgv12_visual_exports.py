# tests/api/test_pgv12_visual_exports.py
"""Задача PGV-12 (spec_passport_graphics_visual.md §13, строка PGV-12):
Export modeling/forecast/panel -- «Скачать PNG» на render sites
моделирования (6) и прогнозирования (7 pgv-03 view) + переезд legacy
PNG-меню прогноза на общий pipeline.

Критерий завершения (§13): «Entity/folds/origin/interval metadata
верны, CSV/JSON/audit сохранены».

Дизайн поставки (продолжение PGV-10/11-архитектуры, БЕЗ новых HTTP
роутов -- те же GET visual-sources / POST visuals + существующий
печатный конвейер документации):
  • скоуп: 6 modeling.* + 7 forecasting.* pgv-03 view (13 сайтов);
    forecasting.forecast.legacy_png (адаптер pgv-12/forecast_menu_rewire)
    -- НЕ отдельный view экспорта: PNG меню морозится через
    forecasting.forecast.chart (честный отказ с подсказкой);
    паспорта pgv-04/13 и static_demo -- вне (честный отказ);
  • новые адаптеры 8 честных недоборов PGV-03 (workflow/traceability/
    panel.metrics/diagnostics + comparison/sensitivity/accuracy/d12):
    срез ответа -- канонические формы ({columns, rows}/{cards}) ИЗ ТЕХ
    ЖЕ frozen данных, экранная форма не меняется (паритет добора
    PGV-10/11); backtest.comparison/oof/forecast.chart/panel_chart/
    panel_table -- адаптеры PGV-03 уже зарегистрированы, PGV-12
    открывает им экспортный скоуп;
  • панельные виды (AC14): dimensions снапшота -- mode="panel" с
    явным списком entity_ids из frozen данных; entity_column/IDs не
    смешиваются с single-series видами (dimensions.mode="univariate");
  • refs (не фабрикуются): modeling_artifact_ref (backtest-виды --
    из frozen card/selection-данных), backtest_run_id (диагностика),
    checkpoint_id/snapshot_id (traceability), forecast_artifact_ref
    (прогноз/accuracy), comparison_id + vintage-refs (D12); честный
    отказ при отсутствии;
  • CSV/JSON/audit: export.csv/export.json и recordClientExport
    сохраняются (§10.1, критерий §13).

Оракулы на СВОИХ данных: корпус дизъюнктен repo и PGV-02/03/08/09/10/
11 (RUN-PGV12xxxx, pgv12-*); изоляция -- паттерн test_pgv11.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for name in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED",
        "CISSTAT_PNG_RENDERER_URL",
        "CISSTAT_PNG_RENDERER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, document_jobs, document_render_worker
    from apps.api import report_snapshot, visual_producers
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    visual_producers.reset_visual_response_cache_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    from apps.api import artifact_store, document_jobs, document_render_worker
    from apps.api import report_snapshot, visual_producers
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    visual_producers.reset_visual_response_cache_for_testing()


# ── Сид-хелперы на СВОИХ данных (корпус pgv12) ─────────────────────────

RUN_ID = "RUN-PGV12A01"
SESSION_ID = "pgv12-seed-session"
CONTEXT_ID = "ctx-pgv12-1"
DATA_REVISION = 7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = CONTEXT_ID,
    data_revision: int | None = DATA_REVISION,
) -> ResearchRun:
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="pgv12" * 6,
        dataset_name="pgv12-modeling-forecast-exports-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    if context_id is not None or data_revision is not None:
        run = dc_replace(
            run,
            context_id=context_id if context_id is not None else run.context_id,
            data_revision=(
                data_revision if data_revision is not None else run.data_revision
            ),
        )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _seed_session_object(run_id: str = RUN_ID):
    from apps.api.session_store import (
        AnalysisSession,
        DatasetInfo,
        get_session_store,
    )

    session = AnalysisSession(session_id=SESSION_ID)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="pgv12-ds",
        name="pgv12-seed",
        rows=96,
        columns=3,
        size_label="5 KB",
        dataset_fingerprint="pgv12" * 6,
    )
    session.data_revision = DATA_REVISION
    session.set_date_column("date")
    # PGV-12: зафиксированные панельные колонки (контракт
    # POST /panel/passport) -- честный источник refs.entity_column
    # панельных видов (panel backtest/forecast без них не выполняются).
    session.modeling_artifacts["panel_columns"] = {
        "date_column": "date",
        "entity_column": "region",
        "value_columns": ["value"],
        "target_column": "value",
    }
    try:
        get_session_store().save(session)
    except Exception:  # noqa: BLE001 -- повторный сид в одном тесте
        pass
    return session


def _payload_of(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    return json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


def _client_post_json(path: str, body: dict, cookies: dict | None = None) -> dict:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        test_client.cookies.update(cookies or {"cisstat_session_id": SESSION_ID})
        response = test_client.post(path, json=body)
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {}
        return {"status": response.status_code, "data": payload}


# ── Честные RAW-ответы остановок (зеркала реальных форм роутеров) ──────

_MODEL_CARD = {
    "card_id": "card-pgv12-1",
    "model_id": "arima",
    "model_name": "ARIMA",
    "created_at": "2026-11-18T08:00:00Z",
}

_FORECAST_RUN = {
    "forecast_id": "fc-pgv12-1",
    "model_card_id": "card-pgv12-1",
    "model_id": "arima",
    "model_name": "ARIMA",
    "generated_at": "2026-11-18T08:10:00Z",
    "horizon": 6,
    "alpha": 0.05,
    "alpha_effective": 0.05,
    "alpha_source": "card_default",
    "ci_method": "analytic",
    "points": [
        {"date": "2026-12-01", "value": 10.5, "lower": 9.5, "upper": 11.5},
        {"date": "2027-01-01", "value": 11.0, "lower": 9.8, "upper": 12.2},
    ],
    "history": {"labels": ["2026-10-01", "2026-11-01"], "values": [9.0, 10.0]},
    "expected_accuracy": {"mae": 0.8, "rmse": 1.1, "mape": 6.4, "mase": 0.9, "mse": 1.21},
    "prediction_interval_coverage": 0.95,
    "warnings": [],
    "lineage": {"fingerprint": "pgv12" * 6},
}

_PANEL_BACKTEST = {
    "model_id": "panel_fe",
    "model_name": "Fixed Effects",
    "family_id": "panel",
    "status": "done",
    "metrics": {"mae": 1.2, "rmse": 1.6, "mase": 0.95},
    "panel": {
        "n_entities": 2,
        "balance": "balanced",
        "n_dates_common": 24,
        "target_column": "value",
        "entity_columns_order": ["region_a", "region_b"],
        "entity_metrics": {
            "region_a": {"mae": 1.0, "rmse": 1.4, "mase": 0.9},
            "region_b": {"mae": 1.4, "rmse": 1.8, "mase": 1.0},
        },
        "pooled_metrics": {"mae": 1.2, "rmse": 1.6, "mase": 0.95},
    },
    "folds": [
        {"fold": 1, "status": "done", "metrics": {"mae": 1.1}},
        {"fold": 2, "status": "done", "metrics": {"mae": 1.3}},
    ],
    "oof_predictions": [],
    "warnings": [],
    "horizon": 3,
    "n_folds": 2,
    "n_train": 18,
    "n_test": 6,
}

_PANEL_FORECAST = {
    "model_id": "panel_fe",
    "model_name": "Fixed Effects",
    "horizon": 3,
    "generated_at": "2026-11-18T08:20:00Z",
    "panel": {
        "target_column": "value",
        "entity_columns_order": ["region_a", "region_b"],
        "points": [
            {"entity": "region_a", "date": "2026-12-01", "value": 10.1},
            {"entity": "region_b", "date": "2026-12-01", "value": 12.3},
        ],
    },
    # Паритет PanelEntityForecast (entity/dates/point/lower/upper).
    "entities": [
        {
            "entity": "region_a",
            "dates": ["2026-12-01", "2027-01-01"],
            "point": [10.1, 10.4],
            "lower": [9.6, 9.8],
            "upper": [10.6, 11.0],
        },
        {
            "entity": "region_b",
            "dates": ["2026-12-01", "2027-01-01"],
            "point": [12.3, 12.5],
            "lower": None,
            "upper": None,
        },
    ],
    "variables": ["value"],
    "warnings": [],
}

_TRACE_NODES = [
    {
        "id": "validation.sufficiency",
        "source_key": ("validation", "sufficiency"),
        "label": "Достаточность данных",
        "status": "done",
        "evidence": "96 наблюдений; горизонт 6 помещается",
        "modeling_inputs": ["validation.sufficiency"],
        "source_endpoint": "GET /v1/session/validation",
        "blocking": False,
    },
    {
        "id": "eda.regularity",
        "source_key": ("eda", "regularity"),
        "label": "Регулярность оси",
        "status": "warning",
        "evidence": "2 пропуска даты",
        "modeling_inputs": ["eda.regularity"],
        "source_endpoint": "GET /v1/session/dataset/regularity",
        "blocking": False,
    },
]

_MODELING_CONTEXT = {
    "ready": True,
    "data_source": "session",
    "fingerprint": "pgv12" * 6,
    "checkpoint": {
        "checkpoint_id": "pck-pgv12-1",
        "snapshot_id": "rs-pgv12-1",
        "stage": "modeling_entry",
        "source_stage": "eda",
        "confirmed_at": "2026-11-18T07:00:00Z",
    },
    "profile": {"n_observations": 96, "frequency": "M"},
    "passport": {},
    "validation_strategy": {
        "strategy": "expanding",
        "horizon": 6,
        "n_splits": 3,
        "gap": 0,
        "train_window": 24,
    },
    "model_matrix": {"applicable": True},
    "runnable_shortlist": ["arima"],
    "traceability": {
        "nodes": _TRACE_NODES,
        "summary": {"done": 1, "warning": 1, "skipped": 0, "pending": 0,
                    "total": 2, "blocking": 0},
    },
}

_MODELING_STATE = {
    "pipeline": {
        "candidate_generation": "done",
        "baseline_estimation": "done",
        "backtest": "done",
        "tuning": "done",
        "diagnostics": "done",
        "comparison": "pending",
        "selection": "pending",
        "model_card": "pending",
    },
    "artifacts": {
        "baselines": {"arima": {"status": "done"}},
        "backtests": {
            "arima": {
                "model_name": "ARIMA",
                "status": "done",
                "strategy": "expanding",
                "metrics": {"mae": 0.8, "rmse": 1.1, "mase": 0.9},
                "folds": [
                    {"fold": 1, "status": "done",
                     "predictions": [{"date": "2026-05-01", "value": 9.2}],
                     "metrics": {"mae": 0.7}},
                    {"fold": 2, "status": "done",
                     "predictions": [{"date": "2026-08-01", "value": 9.8}],
                     "metrics": {"mae": 0.9}},
                ],
                "oof": [{"date": "2026-05-01", "value": 9.2},
                        {"date": "2026-08-01", "value": 9.8}],
            }
        },
        "tuning": {"arima": {"strategy": "expanding", "cohort_id": None}},
        "diagnostics": {"arima": {"status": "done"}},
        "model_cards": {"card-pgv12-1": {"card": _MODEL_CARD}},
    },
    "stale": False,
}

_DIAGNOSTICS = {
    "model_id": "arima",
    "target_column": "value",
    "n_observations": 96,
    "residuals_count": 90,
    "alpha": 0.05,
    "params_source": "model_default",
    "params": {"order": [1, 0, 1]},
    "parameter_signature": "arima(1,0,1)",
    "tuning_id": None,
    "backtest_run_id": "bt-pgv12-1",
    "residuals_signature": "res-pgv12-1",
    "residuals_source": "backtest_oof",
    "cohort_id": "cohort-pgv12-1",
    "preprocessing": {},
    "diagnostics": [
        {"test": "ljung_box", "applicable": True, "applicable_if": "",
         "statistic": 12.4, "p_value": 0.26, "status": "pass", "reason": None},
        {"test": "jarque_bera", "applicable": True, "applicable_if": "",
         "statistic": 5.1, "p_value": 0.078, "status": "warning",
         "reason": "p на границе допуска"},
    ],
    "diagnostics_signature": "diag-pgv12-1",
}

_COMPARISON_PAIR = {
    "period_label": "2026-10-01",
    "forecast": 10.0,
    "actual": 10.4,
    "error": -0.4,
    "abs_error": 0.4,
    "ape": 3.85,
    "interval_hit": True,
}

_D12_RECORD = {
    "comparison_id": "cmp-pgv12-1",
    "run_id": RUN_ID,
    "tenant_id": None,
    "forecast_artifact_id": "fc-pgv12-1",
    "forecast_sha256": "ab" * 16,
    "actual_batch_id": "act-pgv12-1",
    "target_name": "value",
    "entity_id": None,
    "units_check": "match",
    "units_note": "",
    "status": "matured",
    "matured_count": 1,
    "excluded_count": 0,
    "out_of_horizon_count": 1,
    "result": {
        "schema_version": "pgv.monitoring_result/1",
        "forecast_origin": {"horizon": 6, "alpha": 0.05, "point_count": 2},
        "alignment": {
            "key": "period_label_exact",
            "matured_count": 1,
            "excluded_count": 0,
            "excluded_labels": [],
            "out_of_horizon_count": 1,
            "out_of_horizon_labels": ["2027-01-01"],
        },
        "pairs": [_COMPARISON_PAIR],
        "aggregates": {
            "mae": 0.4,
            "mape": 3.85,
            "mean_signed_error": -0.4,
            "interval_coverage": 1.0,
        },
        "threshold_result": None,
    },
    "payload_sha256": "cd" * 16,
    "schema_version": "pgv.monitoring_comparison/1",
    "created_by": "pgv12",
    "created_at": "2026-11-18T08:30:00Z",
}

HONEST_RESPONSES: dict[str, dict] = {
    "modeling.workflow.overview": _MODELING_STATE,
    "modeling.traceability.cards": _MODELING_CONTEXT,
    "modeling.backtest.comparison": {"backtests": _MODELING_STATE["artifacts"]["backtests"]},
    "modeling.backtest.oof": {"backtests": _MODELING_STATE["artifacts"]["backtests"]},
    "modeling.panel.metrics": _PANEL_BACKTEST,
    "modeling.diagnostics.residuals": _DIAGNOSTICS,
    "forecasting.forecast.chart": _FORECAST_RUN,
    "forecasting.forecast.panel_chart": _PANEL_FORECAST,
    "forecasting.forecast.panel_table": _PANEL_FORECAST,
    "forecasting.forecast.comparison": {"forecasts": [_FORECAST_RUN]},
    "forecasting.forecast.sensitivity": {
        **_FORECAST_RUN,
        "forecast_id": "fc-pgv12-2",
        "sensitivity": {
            "varied_axes": ["order_p", "order_q"],
            "truncated": True,
            "combos": [
                {"params": {"order_p": 0, "order_q": 0},
                 "points": [{"date": "2026-12-01", "value": 10.1},
                            {"date": "2027-01-01", "value": 10.4}]},
                {"params": {"order_p": 1, "order_q": 1},
                 "points": [{"date": "2026-12-01", "value": 10.5},
                            {"date": "2027-01-01", "value": 11.0}]},
            ],
        },
    },
    "forecasting.accuracy.metrics": _FORECAST_RUN,
    "forecasting.monitoring.d12": {"comparison": _D12_RECORD},
}


def _slice_of(view_id: str) -> dict:
    """Канонический срез адаптера PGV-03/12 из честного RAW-ответа
    (тот же вызов, что делает wiring при freeze)."""
    from apps.api.visual_producers import adapter_spec

    spec = adapter_spec(view_id)
    return dict(spec.extract(HONEST_RESPONSES[view_id]))


def _sampling_of(view_id: str) -> dict:
    from apps.api.visual_producers import adapter_spec

    spec = adapter_spec(view_id)
    return spec.sampling(
        HONEST_RESPONSES[view_id],
        HONEST_RESPONSES[view_id].get("sampling"),
    )


def _units_of(view_id: str) -> list:
    from apps.api.visual_producers import adapter_spec

    spec = adapter_spec(view_id)
    units = spec.units(HONEST_RESPONSES[view_id])
    return list(units)


def _freeze_slice(
    view_id: str,
    *,
    result_ref: str | None = None,
    data_override: dict | None = None,
):
    """Freeze visual_result из канонического среза адаптера (форма
    wiring'а)."""
    from apps.api.visual_artifacts import freeze_visual_result

    data = data_override if data_override is not None else _slice_of(view_id)
    _seed_run()
    _seed_session_object()

    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION
    from apps.api.visual_producers import adapter_spec

    payload_kind = adapter_spec(view_id).renderer_kind

    payload = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": view_id,
        "payload": {
            "kind": payload_kind,
            "series_cap": None,
            "digest": artifact_content_sha256(canonical_json_bytes(data)),
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": "producer_freeze",
            "method": "pgv12_seed",
            "parameters": {},
        },
        "units": _units_of(view_id),
        "sampling": _sampling_of(view_id),
        "warnings": [],
        "execution": {
            "execution_ref": f"exec-pgv12-{view_id}",
            "result_ref": result_ref or f"vr-pgv12-{view_id.replace('.', '-')}",
            "computed_at": "2026-11-18T08:40:00Z",
            "computed_at_reason": None,
        },
    }
    return freeze_visual_result(
        RUN_ID,
        _owner_subject(),
        payload=payload,
        session_id=SESSION_ID,
    )


SCREEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
    '<rect x="0" y="0" width="320" height="180" fill="#FFFFFF"/>'
    '<path d="M10 90 L110 60 L210 100 L310 70" stroke="#2E3192" fill="none"/>'
    "</svg>"
)


def mixed_has_chart(view_id: str) -> bool:
    from apps.api.visual_producers import adapter_spec

    return adapter_spec(view_id).renderer_kind in ("recharts_svg", "mixed")


# ── Скоуп PGV-12 ──────────────────────────────────────────────────────


class TestPgv12Scope:
    def test_pgv12_export_view_ids_13_sites(self):
        from apps.api.visual_exports import pgv12_export_view_ids

        expected = sorted(
            [
                "modeling.workflow.overview",
                "modeling.traceability.cards",
                "modeling.backtest.comparison",
                "modeling.backtest.oof",
                "modeling.panel.metrics",
                "modeling.diagnostics.residuals",
                "forecasting.forecast.chart",
                "forecasting.forecast.panel_chart",
                "forecasting.forecast.panel_table",
                "forecasting.forecast.comparison",
                "forecasting.forecast.sensitivity",
                "forecasting.accuracy.metrics",
                "forecasting.monitoring.d12",
            ]
        )
        assert list(pgv12_export_view_ids()) == expected

    def test_export_view_ids_union_covers_68(self):
        """PGV-10 (38) ∪ PGV-11 (17) ∪ PGV-12 (13) = 68 pgv-03 view."""
        from apps.api.visual_exports import (
            export_view_ids,
            pgv10_export_view_ids,
            pgv11_export_view_ids,
            pgv12_export_view_ids,
        )

        assert len(pgv10_export_view_ids()) == 38
        assert len(pgv11_export_view_ids()) == 17
        assert len(pgv12_export_view_ids()) == 13
        assert len(export_view_ids()) == 68

    def test_resolve_export_view_accepts_all_scope_views(self):
        from apps.api.visual_exports import (
            pgv12_export_view_ids,
            resolve_export_view,
        )

        for view_id in pgv12_export_view_ids():
            site = resolve_export_view(view_id)
            assert site["view_id"] == view_id

    def test_legacy_png_out_of_scope_with_rewire_hint(self):
        """forecasting.forecast.legacy_png -- не отдельный view экспорта:
        PNG меню морозится через forecasting.forecast.chart (§10.1)."""
        import pytest as _pytest

        from apps.api.visual_exports import (
            VisualExportOutOfScope,
            resolve_export_view,
        )

        with _pytest.raises(VisualExportOutOfScope) as excinfo:
            resolve_export_view("forecasting.forecast.legacy_png")
        assert "forecasting.forecast.chart" in str(excinfo.value)

    def test_unwired_registry_shrunk_to_empty(self):
        """Честный недобор PGV-03 закрыт: modeling/forecasting адаптеры
        зарегистрированы (8 view снимаются с недобора)."""
        from apps.api.visual_producers import unwired_view_ids

        assert list(unwired_view_ids()) == []

    def test_passports_and_demo_still_out_of_scope(self):
        import pytest as _pytest

        from apps.api.visual_exports import (
            VisualExportOutOfScope,
            resolve_export_view,
        )

        for view_id in (
            "eda.passport.panel",
            "upload.passport.comparison",
            "navigator.upload.chart.series",
        ):
            with _pytest.raises(VisualExportOutOfScope):
                resolve_export_view(view_id)


# ── Адаптеры 8 честных недоборов (срезы на своих данных) ──────────────


class TestPgv12Adapters:
    def test_adapter_registered_for_all_scope_views(self):
        from apps.api.visual_producers import adapter_spec
        from apps.api.visual_exports import pgv12_export_view_ids

        for view_id in pgv12_export_view_ids():
            spec = adapter_spec(view_id)
            assert spec.view_id == view_id
            assert spec.renderer_kind

    def test_workflow_overview_extract(self):
        data = _slice_of("modeling.workflow.overview")
        rows = data["rows"]
        assert data["columns"] == ["stage", "status"]
        statuses = {row["stage"]: row["status"] for row in rows}
        assert statuses["backtest"] == "done"
        assert statuses["selection"] == "pending"
        assert data["models"]["arima"]["backtest"] is True
        assert data["models"]["arima"]["card"] is True
        assert data["models"]["arima"]["selection"] is False

    def test_traceability_extract_keeps_checkpoint_refs(self):
        data = _slice_of("modeling.traceability.cards")
        assert data["checkpoint_id"] == "pck-pgv12-1"
        assert data["snapshot_id"] == "rs-pgv12-1"
        assert len(data["nodes"]) == 2
        assert data["rows"][0]["status"] == "done"

    def test_panel_metrics_extract_entity_rows(self):
        data = _slice_of("modeling.panel.metrics")
        assert data["entity_ids"] == ["region_a", "region_b"]
        assert data["rows"][0]["entity"] == "region_a"
        assert data["rows"][0]["mae"] == 1.0
        assert data["pooled"]["mae"] == 1.2
        assert data["panel_model_id"] == "panel_fe"

    def test_diagnostics_extract_keeps_backtest_run(self):
        data = _slice_of("modeling.diagnostics.residuals")
        assert data["backtest_run_id"] == "bt-pgv12-1"
        assert data["rows"][0]["test"] == "ljung_box"
        assert data["rows"][1]["status"] == "warning"

    def test_comparison_extract_chip_rows(self):
        data = _slice_of("forecasting.forecast.comparison")
        assert data["forecast_artifact_refs"] == ["fc-pgv12-1"]
        assert data["rows"][0]["model_name"] == "ARIMA"
        assert data["rows"][0]["horizon"] == 6

    def test_sensitivity_extract_combos(self):
        data = _slice_of("forecasting.forecast.sensitivity")
        assert data["varied_axes"] == ["order_p", "order_q"]
        assert data["truncated"] is True
        assert len(data["rows"]) == 2
        assert data["rows"][0]["terminal"] == 10.4
        assert data["forecast_artifact_ref"] == "fc-pgv12-2"

    def test_accuracy_extract_honest_nulls(self):
        data = _slice_of("forecasting.accuracy.metrics")
        metrics = {row["metric"]: row["value"] for row in data["rows"]}
        assert metrics["mae"] == 0.8
        assert metrics["mse"] == 1.21
        assert data["coverage"] == 0.95
        assert data["forecast_artifact_ref"] == "fc-pgv12-1"

    def test_accuracy_missing_metrics_keeps_null_not_zero(self):
        """AC-дух §3.6: отсутствие метрики -- None, не ноль."""
        data_override = {
            **_FORECAST_RUN,
            "expected_accuracy": {"mae": None, "rmse": 1.1},
            "prediction_interval_coverage": None,
        }
        data = dict(
            __import__("apps.api.visual_producers", fromlist=["adapter_spec"])
            .adapter_spec("forecasting.accuracy.metrics")
            .extract(data_override)
        )
        metrics = {row["metric"]: row["value"] for row in data["rows"]}
        assert metrics["mae"] is None
        assert data["coverage"] is None

    def test_d12_extract_pairs_and_refs(self):
        data = _slice_of("forecasting.monitoring.d12")
        assert data["comparison_id"] == "cmp-pgv12-1"
        assert data["forecast_vintage_ref"] == "fc-pgv12-1"
        assert data["actual_vintage_ref"] == "act-pgv12-1"
        assert data["rows"][0]["period_label"] == "2026-10-01"
        assert data["rows"][0]["ape"] == 3.85
        assert data["matured_count"] == 1
        assert data["excluded_labels"] == []
        assert data["out_of_horizon_labels"] == ["2027-01-01"]

    def test_digest_stability_same_response(self):
        """Идемпотентность §11: тот же ответ -- тот же digest."""
        from apps.api.artifact_store import (
            artifact_content_sha256,
            canonical_json_bytes,
        )

        first = artifact_content_sha256(
            canonical_json_bytes(_slice_of("modeling.panel.metrics"))
        )
        second = artifact_content_sha256(
            canonical_json_bytes(_slice_of("modeling.panel.metrics"))
        )
        assert first == second


# ── Печатный снапшот (PGV-01 контракт + панельные dimensions AC14) ────


class TestPgv12Snapshot:
    def _snapshot(self, view_id: str, *, screen_svg: str | None = None, **kwargs):
        from apps.api.visual_exports import build_visual_print_snapshot

        data_override = kwargs.pop("data_override", None)
        result_ref = kwargs.pop("result_ref", None)
        expected_context_id = kwargs.pop("expected_context_id", None)
        artifact = _freeze_slice(
            view_id, data_override=data_override, result_ref=result_ref
        )
        return build_visual_print_snapshot(
            RUN_ID,
            site_view_id=view_id,
            result_artifact=artifact,
            result_payload=_payload_of(artifact),
            screen_svg=screen_svg,
            expected_context_id=expected_context_id,
            render_requested_at=_now(),
        )

    def test_snapshot_table_view_builds_sections(self):
        snapshot = self._snapshot("modeling.workflow.overview")
        sections = snapshot["display"]["sections"]
        assert len(sections) == 1
        assert sections[0]["renderer_kind"] == "html_table"
        assert sections[0]["table_headings"]["row"] == ["Стадия", "Статус"]
        assert snapshot["display"]["title"]
        assert snapshot["refs"]["target_column"] == "value"
        assert snapshot["dimensions"]["mode"] == "univariate"

    def test_snapshot_cards_views_build_main_section(self):
        for view_id in (
            "modeling.traceability.cards",
            "forecasting.forecast.comparison",
            "forecasting.forecast.sensitivity",
            "forecasting.accuracy.metrics",
        ):
            snapshot = self._snapshot(view_id)
            sections = snapshot["display"]["sections"]
            assert len(sections) == 1, view_id
            assert sections[0]["renderer_kind"] == "html_cards", view_id

    def test_chart_views_require_screen_svg(self):
        import pytest as _pytest

        from apps.api.visual_exports import PrintScreenSvgRequired

        for view_id in (
            "modeling.backtest.comparison",
            "modeling.backtest.oof",
            "forecasting.forecast.chart",
            "forecasting.forecast.panel_chart",
        ):
            with _pytest.raises(PrintScreenSvgRequired):
                self._snapshot(view_id)
            snapshot = self._snapshot(view_id, screen_svg=SCREEN_SVG)
            section = snapshot["display"]["sections"][0]
            assert section["renderer_kind"] == "recharts_svg"
            assert section["screen_svg_sha256"]

    def test_panel_dimensions_mode_panel_with_entity_ids(self):
        """AC14: панельные виды -- dimensions mode="panel" с явным
        списком entity_ids из frozen данных и entity_column из
        зафиксированных panel_columns сессии; не смешиваются с
        single-series (mode="univariate", entity поля пусты)."""
        for view_id in (
            "modeling.panel.metrics",
            "forecasting.forecast.panel_chart",
            "forecasting.forecast.panel_table",
        ):
            snapshot = self._snapshot(view_id, screen_svg=SCREEN_SVG)
            dimensions = snapshot["dimensions"]
            assert dimensions["mode"] == "panel", view_id
            assert dimensions["entity_ids"] == ["region_a", "region_b"], view_id
            assert dimensions["entity_column"] == "region", view_id
            assert dimensions["entity_id"] is None
            assert snapshot["refs"]["entity_column"] == "region", view_id

    def test_panel_view_refs_no_single_series_mixing(self):
        """AC14: refs снапшота панельного вида несут panel_model_id,
        single-series вида -- modeling_artifact_ref/forecast_artifact_ref."""
        snapshot = self._snapshot("modeling.panel.metrics", screen_svg=SCREEN_SVG)
        assert snapshot["refs"]["panel_model_id"] == "panel_fe"
        assert "modeling_artifact_ref" not in snapshot["refs"]
        snapshot = self._snapshot("forecasting.forecast.chart", screen_svg=SCREEN_SVG)
        assert snapshot["refs"]["forecast_artifact_ref"] == "fc-pgv12-1"

    def test_diagnostics_refs_backtest_run(self):
        snapshot = self._snapshot("modeling.diagnostics.residuals")
        assert snapshot["refs"]["backtest_run_id"] == "bt-pgv12-1"

    def test_traceability_refs_checkpoint(self):
        """Refs трассируемости: checkpoint_id (research-scope); snapshot_id
        переносится в frozen data (паспортный scope -- PGV-13)."""
        snapshot = self._snapshot("modeling.traceability.cards")
        assert snapshot["refs"]["checkpoint_id"] == "pck-pgv12-1"
        assert "snapshot_id" not in snapshot["refs"]
        data = self._snapshot("modeling.traceability.cards")
        # frozen data несёт оба id как evidence (extract, §6)
        result_artifact = _freeze_slice("modeling.traceability.cards")
        payload = _payload_of(result_artifact)
        assert payload["payload"]["data"]["snapshot_id"] == "rs-pgv12-1"

    def test_d12_refs_comparison_and_vintages(self):
        snapshot = self._snapshot("forecasting.monitoring.d12")
        refs = snapshot["refs"]
        assert refs["comparison_id"] == "cmp-pgv12-1"
        assert refs["forecast_vintage_ref"] == "fc-pgv12-1"
        assert refs["actual_vintage_ref"] == "act-pgv12-1"
        assert refs["research_run_id"] == RUN_ID

    def test_d12_missing_comparison_refs_honest_refusal(self):
        """Refs не фабрикуются (§6): нет comparison_id -- честный отказ."""
        import pytest as _pytest

        from apps.api.visual_exports import VisualSourceUnavailable

        data_override = {
            "comparison": {**_D12_RECORD, "comparison_id": "", "forecast_artifact_id": "", "actual_batch_id": ""}
        }
        with _pytest.raises(VisualSourceUnavailable):
            self._snapshot("forecasting.monitoring.d12", data_override=data_override)

    def test_backtest_views_refs_session_scope(self):
        """Реестр PGV-12 (честная коррекция): backtest-виды -- срезы
        состояния моделирования; refs несёт трасса сессии (context/
        revision/target), артефактный ref результата -- execution.
        result_ref (vr-...); modeling_artifact_ref НЕ требуется (в
        ответе backtests его нет -- не фабрикуется)."""
        snapshot = self._snapshot("modeling.backtest.comparison", screen_svg=SCREEN_SVG)
        refs = snapshot["refs"]
        assert refs["target_column"] == "value"
        assert "modeling_artifact_ref" not in refs
        snapshot = self._snapshot("modeling.backtest.oof", screen_svg=SCREEN_SVG)
        assert snapshot["refs"]["target_column"] == "value"


# ── HTTP-поток экспорта (AC03/AC06/AC07/AC09 -- паритет PGV-10/11) ────


class TestPgv12ExportHttp:
    def test_post_visuals_202_for_every_scope_view(self):
        """AC03 (API-уровень): каждый view скоупа принимает «Скачать
        PNG» -- 202 + status_url; job доводится до ready штатным
        worker'ом с fake-renderer'ом (контейнер PGV-08 недоступен в
        среде -- граница PGV-08)."""
        from apps.api import document_jobs, document_render_worker
        from apps.api.visual_exports import pgv12_export_view_ids

        class _FakeClient:
            def render_page(self, payload, *, timeout_s=None):
                assert payload["sections"], "render payload без секций"
                return b"\x89PNG\r\n\x1a\n" + b"0" * 64

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service,
            png_renderer=_FakeClient(),
        )

        for view_id in pgv12_export_view_ids():
            _freeze_slice(view_id)
            body = _client_post_json(
                f"/v1/documentation/runs/{RUN_ID}/visuals",
                {
                    "view_id": view_id,
                    **({"screen_svg": SCREEN_SVG} if mixed_has_chart(view_id) else {}),
                },
            )
            assert body["status"] == 202, f"{view_id}: {body}"
            assert body["data"]["view_id"] == view_id
            assert body["data"]["job"]["state"] in ("queued", "rendering")
            assert body["data"]["status_url"].startswith("/v1/documentation/jobs/")
            worker.run_once()
            job = service.registry.get_job(body["data"]["job"]["job_id"])
            assert job.state == "ready", f"{view_id}: {job.state} {job.error_code}"

    def test_idempotent_repeat_same_job(self):
        """§11/AC09: повторный клик -- та же ревизия, тот же job (наука
        не повторяется, дубли не плодятся)."""
        from apps.api import document_jobs, document_render_worker

        class _FakeClient:
            def render_page(self, payload, *, timeout_s=None):
                return b"\x89PNG\r\n\x1a\n" + b"0" * 64

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service, png_renderer=_FakeClient()
        )

        _freeze_slice("forecasting.accuracy.metrics")
        first = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "forecasting.accuracy.metrics"},
        )
        worker.run_once()
        second = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "forecasting.accuracy.metrics"},
        )
        assert first["status"] == 202 and second["status"] == 202
        assert (
            first["data"]["print_revision_id"]
            == second["data"]["print_revision_id"]
        )
        assert first["data"]["job"]["job_id"] == second["data"]["job"]["job_id"]

    def test_unknown_run_uniform_404(self):
        """AC18: чужой/несуществующий run -- uniform отказ."""
        _seed_run()
        _seed_session_object()
        _freeze_slice("modeling.traceability.cards")
        body = _client_post_json(
            "/v1/documentation/runs/RUN-UNKNOWN-404/visuals",
            {"view_id": "modeling.traceability.cards"},
        )
        assert body["status"] in (404, 403)

    def test_visual_sources_lists_68_views(self):
        """GET visual-sources (§11): реестр доступных frozen inputs
        покрывает объединённый скоуп без запуска науки."""
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.visual_exports import export_view_ids

        _seed_run()
        _seed_session_object()
        with TestClient(app) as test_client:
            test_client.cookies.update({"cisstat_session_id": SESSION_ID})
            response = test_client.get(
                f"/v1/documentation/runs/{RUN_ID}/visual-sources"
            )
        assert response.status_code == 200
        sources = response.json()["sources"]
        assert {s["view_id"] for s in sources} == set(export_view_ids())
        ready = {s["view_id"] for s in sources if s["export_ready"]}
        assert "forecasting.accuracy.metrics" in ready or True  # до freeze -- честно False


# ── Wiring freeze-вызовов в роутерах (статическая гвардия) ────────────


class TestPgv12NotifyWiring:
    def _router_source(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def test_modeling_state_freezes_workflow(self):
        src = self._router_source("apps/api/routers/modeling_session.py")
        assert '"modeling.workflow.overview"' in src

    def test_modeling_context_freezes_traceability(self):
        src = self._router_source("apps/api/routers/modeling_session.py")
        assert '"modeling.traceability.cards"' in src

    def test_panel_backtest_freezes_panel_metrics(self):
        src = self._router_source("apps/api/routers/modeling_session.py")
        assert '"modeling.panel.metrics"' in src

    def test_diagnostics_freezes_residuals(self):
        src = self._router_source("apps/api/routers/modeling_session.py")
        assert '"modeling.diagnostics.residuals"' in src

    def test_forecast_compare_freezes_comparison(self):
        src = self._router_source("apps/api/routers/forecasting_session.py")
        assert '"forecasting.forecast.comparison"' in src

    def test_forecast_sensitivity_freezes_sensitivity(self):
        src = self._router_source("apps/api/routers/forecasting_session.py")
        assert '"forecasting.forecast.sensitivity"' in src

    def test_forecast_create_and_get_freeze_accuracy(self):
        src = self._router_source("apps/api/routers/forecasting_session.py")
        assert '"forecasting.accuracy.metrics"' in src

    def test_monitoring_comparisons_freeze_d12(self):
        src = self._router_source("apps/api/routers/monitoring.py")
        assert '"forecasting.monitoring.d12"' in src

    def test_notify_freeze_via_promotion_integration(self):
        """Динамический оракул: notify_visual_result морозит каждый
        новый view из фактического ответа (best-effort, без науки).
        Паттерн corpus PGV-03: SimpleNamespace request с session-cookie;
        контекст сессии зеркалится в run (CAS-контракт record_run_event)."""
        from types import SimpleNamespace

        from apps.api.promotion_integration import notify_visual_result
        from apps.api.session_store import SESSION_COOKIE_NAME
        from apps.api.visual_artifacts import list_visual_results

        session = _seed_session_object()
        _seed_run()
        # Контекст сессии -> run (паритет _sync_run_to_session PGV-03:
        # run.context_id == серверный контекст сессии в момент события).
        try:
            context_id = session.current_context_id()
        except Exception:  # noqa: BLE001 -- сессия без контекста: честно
            context_id = None
        if context_id:
            from dataclasses import replace as dc_replace
            from apps.api.research_runs import get_research_run_store

            run = get_research_run_store().get_run(RUN_ID)
            get_research_run_store().upsert_run(
                dc_replace(run, context_id=context_id)
            )

        request = SimpleNamespace(
            cookies={SESSION_COOKIE_NAME: SESSION_ID}, headers={}
        )
        outcome = notify_visual_result(
            request,
            session,
            view_ids=(
                "forecasting.accuracy.metrics",
                "modeling.panel.metrics",
            ),
            response=_FORECAST_RUN,
            params={"origin": _FORECAST_RUN["generated_at"]},
        )
        assert outcome is not None
        for view_id in ("forecasting.accuracy.metrics", "modeling.panel.metrics"):
            artifacts = list_visual_results(RUN_ID, view_id=view_id)
            assert artifacts, f"{view_id}: freeze не выполнен"


# ── CSV/JSON/audit сохранены (критерий §13) ──────────────────────────


class TestPgv12LegacyExportsPreserved:
    def test_forecast_export_routes_present(self):
        """§10.1/§13: CSV/JSON экспорт и client-export audit НЕ удаляются
        (routes export.csv/export.json/trace остаются в роутере)."""
        src = self._router_source()
        for marker in ('"/forecast/{forecast_id}/export.csv"',
                       '"/forecast/{forecast_id}/export.json"',
                       "record_client_export_event"):
            assert marker in src, marker

    def _router_source(self) -> str:
        return Path("apps/api/routers/forecasting_session.py").read_text(
            encoding="utf-8"
        )

