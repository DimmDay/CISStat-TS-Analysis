# tests/api/test_pgv11_visual_exports.py
"""Задача PGV-11 (spec_passport_graphics_visual.md §13, строка PGV-11):
Export EDA/IH/tasks -- «Скачать PNG» на render sites остановок EDA
(16 pgv-03 view) и задач (tasks.causes.fold_importance).

Критерий завершения (§13): «Полные читаемые карты/матрицы, стабильная
scale, unavailable не фабрикуется».

Дизайн поставки (продолжение PGV-10-архитектуры, без новых HTTP
роутов -- те же GET visual-sources / POST visuals):
  • скоуп: 16 eda.* view адаптеров pgv-03/eda_* + 1 tasks view
    pgv-03/tasks_xai; паспорта (pgv-04/13) и demo -- честный отказ;
  • печатные формы: адаптеры PGV-03 срезают экранную форму; PGV-11
    АДДИТИВНО достраивает канонические формы печати ({columns, rows},
    {row_headings, column_headings, cells}, ih-матрица) из ТЕХ ЖЕ
    frozen данных (экранная форма не меняется -- паритет PGV-10);
  • AC01: scatter/histogram/kde -- отдельные view со своей sampling
    и СВОИМИ осями (не другой subplot);
  • AC02: IH-матрица печатается html_table-секцией ПОЛНОСТЬЮ -- bins
    строк/колонок, проценты, сумма строки (знаменатель долей),
    честная пометка о цветовой шкале 0..100 % и об абсолютном n
    (SVG-only сериализация не подходит, spec §2);
  • стабильная scale: heatmap домен -- из ФАКТИЧЕСКИХ ячеек frozen
    данных, детерминированный (две сборки -- один домен);
  • unavailable не фабрикуется: нет frozen результата -- 409
    source_unavailable; not_computed задачи -- freeze не создаётся;
  • tasks view: ref modeling_artifact_ref -- из frozen card
    (честный отказ без него, refs не фабрикуются).

Оракулы на СВОИХ данных: корпус дизъюнктен repo и PGV-02/03/08/09/10
(RUN-PGV11xxxx, pgv11-*); изоляция -- паттерн test_pgv10.
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
    research_runs.reset_dataset_file_store_for_testing()
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


# ── Сид-хелперы на СВОИХ данных (корпус pgv11) ─────────────────────────

RUN_ID = "RUN-PGV11A01"
SESSION_ID = "pgv11-seed-session"
CONTEXT_ID = "ctx-pgv11-1"
DATA_REVISION = 3


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
        dataset_fingerprint="pgv11" * 6,
        dataset_name="pgv11-eda-tasks-exports-seed",
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
        dataset_id="pgv11-ds",
        name="pgv11-seed",
        rows=96,
        columns=3,
        size_label="5 KB",
        dataset_fingerprint="pgv11" * 6,
    )
    session.data_revision = DATA_REVISION
    session.set_date_column("date")
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


# ── Честные RAW-ответы остановок (зеркала реальных форм роутеров) ──────

_IH_RESULT = {
    "feature": "lag_1",
    "kind": "lag",
    "dtype": "float64",
    "n_observations": 96,
    "r": 0.6,
    "r_adjusted": 0.5,
    "mi": 0.3,
    "h_x": 2.0,
    "h_y": 2.1,
    "n_bins_x": 4,
    "n_bins_y": 4,
    "permutation_baseline": 0.1,
    "p_value": 0.01,
    "q_value": 0.02,
    "significant": True,
    "error": None,
}

HONEST_RESPONSES: dict[str, dict] = {
    "eda.descriptive.stats": {
        "columns": [
            {
                "name": "Оборот",
                "non_null_count": 94,
                "stats": {
                    "mean": 10.5, "median": 10.0, "std": 2.0, "q1": 9.0,
                    "q3": 12.0, "iqr": 3.0, "skewness": 0.2, "kurtosis": -0.1,
                },
            }
        ],
    },
    "eda.descriptive.distribution.scatter": {
        "scatter": [{"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 3.0}],
        "scatter_sampled": False,
    },
    "eda.descriptive.distribution.histogram": {
        "histogram": [{"bin": 0, "count": 3}, {"bin": 1, "count": 5}],
    },
    "eda.descriptive.distribution.kde": {
        "kde": [{"x": 1.0, "density": 0.4}],
    },
    "eda.correlation.acf_pacf": {
        "acf": [
            {"lag": 0, "value": 1.0, "confidence_lower": -0.2, "confidence_upper": 0.2},
            {"lag": 1, "value": 0.5, "confidence_lower": -0.2, "confidence_upper": 0.2},
        ],
        "pacf": [
            {"lag": 1, "value": 0.4, "confidence_lower": -0.2, "confidence_upper": 0.2},
        ],
        "max_lag": 12,
        "order_source": "time_column",
        "applicable": True,
        "reason": None,
    },
    "eda.ih.metrics_table": {
        "results": [_IH_RESULT],
        "target_entropy": 2.1,
        "applicable": True,
        "reason": None,
    },
    "eda.ih.conditional_map": {
        "column": "value",
        "n_observations": 96,
        "conditional_feature": "lag_1",
        "conditional_x_bins": ["[0, 5)", "[5, 10)"],
        "conditional_y_bins": ["низкий", "высокий"],
        "conditional_matrix": [
            {"x_bin": "[0, 5)", "values": [60.0, 40.0]},
            {"x_bin": "[5, 10)", "values": [30.0, 70.0]},
        ],
        "applicable": True,
        "reason": None,
    },
    "eda.ih.results": {
        "results": [_IH_RESULT],
        "synergies": [
            {
                "pair": "lag_1 × lag_2",
                "feature_1": "lag_1",
                "feature_2": "lag_2",
                "r_1": 0.6,
                "r_2": 0.4,
                "r_combined": 0.7,
                "incremental_gain": 0.1,
                "interaction_delta": 0.02,
            }
        ],
        "recommendations": ["lag_1 -- главный фактор"],
        "applicable": True,
        "reason": None,
    },
    "eda.seasonality.spectrum": {
        "fft": [{"frequency": 0.1, "power": 5.0}],
        "periodogram": [{"frequency": 0.25, "power": 8.0}],
        "dominant_period": 4.0,
        "dominant_strength": 0.6,
        "spectral_entropy": 0.4,
        "candidates": [
            {
                "rank": 1,
                "period": 4.0,
                "period_rounded": 4,
                "frequency": 0.25,
                "amplitude": 2.0,
                "power": 8.0,
                "power_share": 0.5,
            }
        ],
        "applicable": True,
        "reason": None,
    },
    "eda.stationarity.tests": {
        "tests": [
            {
                "id": "adf_level",
                "label": "ADF (уровень)",
                "null_hypothesis": "unit root",
                "alternative_hypothesis": "stationary",
                "available": True,
                "statistic": -3.5,
                "p_value": 0.008,
                "lags": 2,
                "reject_null": True,
            }
        ],
        "consensus": "stationary",
        "recommendation": "ряд стационарен",
        "applicable": True,
        "reason": None,
    },
    "eda.distribution.tests": {
        "tests": [
            {
                "id": "shapiro",
                "label": "Shapiro–Wilk",
                "available": True,
                "statistic": 0.98,
                "p_value": 0.4,
                "adjusted_p_value": 0.4,
                "reject_normality": False,
                "n_used": 96,
            }
        ],
        "summary": {
            "mean": 10.5, "median": 10.0, "std": 2.0,
            "skewness": 0.2, "excess_kurtosis": -0.1,
        },
        "applicable": True,
        "reason": None,
    },
    "eda.structural.breakpoints": {
        "series": [
            {"index": 0, "label": "2025-01-01", "value": 1.0, "fitted": 1.0, "segment_id": 0},
        ],
        "cusum": [{"index": 0, "value": 0.0}],
        "segments": [
            {
                "id": 0,
                "start_index": 0,
                "end_index": 47,
                "start_label": "2025-01-01",
                "end_label": "2025-02-17",
                "n_observations": 48,
                "mean": 1.0,
                "std": 0.5,
                "slope": 0.01,
            },
            {
                "id": 1,
                "start_index": 48,
                "end_index": 95,
                "start_label": "2025-02-18",
                "end_label": "2025-04-05",
                "n_observations": 48,
                "mean": 2.0,
                "std": 0.4,
                "slope": -0.01,
            },
        ],
        "break_count": 1,
        "applicable": True,
        "reason": None,
    },
    "eda.feature_select.scores": {
        "features": [
            {
                "name": "lag_1",
                "n_observations": 96,
                "pearson": 0.6,
                "spearman": 0.55,
                "vif": 1.2,
                "vif_infinite": False,
                "max_abs_predictor_correlation": 0.4,
                "granger_available": True,
                "best_granger_lag": 1,
                "granger_p_value": 0.02,
                "granger_adjusted_p_value": 0.03,
                "granger_significant": True,
                "decision": "keep",
                "decision_reason": "сильная связь",
            }
        ],
        "applicable": True,
        "reason": None,
    },
    "eda.feature_select.matrix": {
        "correlation_matrix": [
            {"row": "lag_1", "column": "lag_1", "pearson": 1.0, "spearman": 1.0},
            {"row": "lag_1", "column": "lag_2", "pearson": 0.4, "spearman": 0.35},
            {"row": "lag_2", "column": "lag_1", "pearson": 0.4, "spearman": 0.35},
            {"row": "lag_2", "column": "lag_2", "pearson": 1.0, "spearman": 1.0},
        ],
        "applicable": True,
        "reason": None,
    },
    "eda.validation_strategy.windows": {
        "folds": [
            {
                "fold": 1,
                "train_start": 0,
                "train_end": 47,
                "train_size": 48,
                "gap_start": None,
                "gap_end": None,
                "gap_size": 0,
                "test_start": 48,
                "test_end": 59,
                "test_size": 12,
                "train_start_label": "2025-01-01",
                "train_end_label": "2025-02-17",
                "test_start_label": "2025-02-18",
                "test_end_label": "2025-03-01",
            }
        ],
        "strategy": "sliding",
        "horizon": 12,
        "gap": 0,
        "applicable": True,
        "reason": None,
    },
    "eda.model_matrix.applicability": {
        "families": [
            {"family_id": "arima", "family_name": "ARIMA", "model_count": 1},
        ],
        "models": [
            {
                "model_id": "arima",
                "model_name": "ARIMA",
                "family_id": "arima",
                "family_name": "ARIMA",
                "compatibility": "candidate",
                "platform_status": "ready",
                "min_observations": 24,
                "supports_exogenous": False,
                "libraries": ["statsmodels"],
                "training_time": "fast",
                "criteria": [],
                "blocking_reasons": [],
                "cautions": [],
            }
        ],
        "summary": {
            "total_models": 1, "candidates": 1, "conditional": 0,
            "blocked": 0, "ready": 1, "catalog_only": 0,
        },
        "applicable": True,
        "reason": None,
    },
    "tasks.causes.fold_importance": {
        "method": {
            "method_id": "fold_importance",
            "kind": "mdi",
            "title": "Fold-важность",
            "status": "available",
            "reason": None,
            "factors": [
                {
                    "feature_name": "lag_1",
                    "mean_share": 0.42,
                    "n_folds": 3,
                    "fold_values": [],
                },
                {
                    "feature_name": "lag_2",
                    "mean_share": 0.18,
                    "n_folds": 3,
                    "fold_values": [],
                },
            ],
            "provenance": {
                "backtest_run_id": "bt-pgv11-1",
                "plan_id": "plan-pgv11-1",
                "n_folds": 3,
            },
        },
        "card": {
            "card_id": "card-pgv11-1",
            "model_id": "random_forest",
            "selection_kind": "single",
            "created_at": "2026-10-31T08:00:00Z",
        },
    },
}


def _slice_of(view_id: str) -> dict:
    """Канонический срез адаптера PGV-03/11 из честного RAW-ответа
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
    return spec.units(HONEST_RESPONSES[view_id])


def _freeze_slice(
    view_id: str,
    *,
    result_ref: str | None = None,
    data_override: dict | None = None,
    drop_print_forms: bool = False,
):
    """Freeze visual_result из канонического среза адаптера (форма
    wiring'а). drop_print_forms -- честная имитация СТАРОГО frozen
    артефакта без печатных форм (снапшот собирается, но мост честно
    откажется рендерить секции без контента)."""
    from apps.api.visual_artifacts import freeze_visual_result

    data = data_override if data_override is not None else _slice_of(view_id)
    if drop_print_forms:
        data = {
            key: value
            for key, value in data.items()
            if key not in ("columns", "rows", "row_headings", "column_headings",
                           "cells", "ih_input", "caption")
        }
    _seed_run()
    _seed_session_object()

    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION
    from apps.api.visual_producers import adapter_spec

    # паритет build_visual_result_payload: payload.kind -- первичный
    # kind спеки адаптера (mixed-сайты несут первичный, не "mixed")
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
            "method": "pgv11_seed",
            "parameters": {"selected_column": "value"},
        },
        "units": _units_of(view_id),
        "sampling": _sampling_of(view_id),
        "warnings": [],
        "execution": {
            "execution_ref": f"exec-pgv11-{view_id}",
            "result_ref": result_ref or f"vr-pgv11-{view_id.replace('.', '-')}",
            "computed_at": "2026-10-31T08:30:00Z",
            "computed_at_reason": None,
        },
    }
    return freeze_visual_result(
        RUN_ID,
        _owner_subject(),
        payload=payload,
        session_id=SESSION_ID,
    )


def _build_snapshot(view_id: str, *, screen_svg: str | None = None, **kwargs):
    from apps.api.visual_exports import build_visual_print_snapshot

    data_override = kwargs.pop("data_override", None)
    drop_print_forms = kwargs.pop("drop_print_forms", False)
    result_ref = kwargs.pop("result_ref", None)
    artifact = _freeze_slice(
        view_id,
        data_override=data_override,
        drop_print_forms=drop_print_forms,
        result_ref=result_ref,
    )
    result_payload = _payload_of(artifact)
    return (
        build_visual_print_snapshot(
            RUN_ID,
            site_view_id=view_id,
            result_artifact=artifact,
            result_payload=result_payload,
            screen_svg=screen_svg,
            date_column=kwargs.pop("date_column", "date"),
            render_requested_at="2026-10-31T09:05:00Z",
            **kwargs,
        ),
        artifact,
    )


SCREEN_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='400'>"
    "<rect width='800' height='400' fill='white'/></svg>"
)


# ══════════════════════════════════════════════════════════════════════
# 1. Скоуп экспорта (§13 PGV-11: Eda*/TasksCauses)
# ══════════════════════════════════════════════════════════════════════


class TestExportScope:
    def test_pgv11_scope_is_eda_and_tasks_pgv03_views(self):
        """Скоуп PGV-11 -- 16 pgv-03 view остановки EDA + tasks.causes.
        fold_importance (spec §13 «Eda*/TasksCauses»); паспорта
        (pgv-04/13) и demo -- вне."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import pgv11_export_view_ids

        expected = sorted(
            site["view_id"]
            for site in load_visual_registry()["sites"]
            if site["module_id"] in ("eda", "tasks")
            and str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        )
        assert list(pgv11_export_view_ids()) == expected
        assert len(expected) == 17, "санити: 16 eda + 1 tasks"
        assert "eda.passport.panel" not in expected
        assert "eda.passport.comparison" not in expected
        assert "tasks.causes.fold_importance" in expected

    def test_pgv11_scope_disjoint_with_pgv10(self):
        """Скоупы PGV-10/PGV-11 дизъюнктны; объединение -- 55 view."""
        from apps.api.visual_exports import (
            export_view_ids,
            pgv10_export_view_ids,
            pgv11_export_view_ids,
        )

        pgv10 = set(pgv10_export_view_ids())
        pgv11 = set(pgv11_export_view_ids())
        assert not (pgv10 & pgv11)
        assert len(pgv10) == 38 and len(pgv11) == 17
        assert list(export_view_ids()) == sorted(pgv10 | pgv11)
        assert len(export_view_ids()) == 55

    def test_every_pgv11_view_is_wired_with_print_forms(self):
        """Все 17 view скоупа -- wired адаптеры с канонической печатной
        формой в срезе (недобора нет -- gap закрыт, не замалчиван)."""
        from apps.api.visual_exports import pgv11_export_view_ids
        from apps.api.visual_producers import (
            UNWIRED_PGV03_VIEWS,
            adapter_spec,
            resolve_producer_view,
        )

        assert not (set(pgv11_export_view_ids()) & UNWIRED_PGV03_VIEWS)
        for view_id in pgv11_export_view_ids():
            resolve_producer_view(view_id)
            spec = adapter_spec(view_id)
            data = spec.extract(HONEST_RESPONSES[view_id])
            site_kind = spec.renderer_kind
            if site_kind == "html_heatmap":
                assert isinstance(data.get("row_headings"), list), view_id
                assert isinstance(data.get("cells"), list), view_id
            elif site_kind == "recharts_svg":
                # chart-сайт: печатная геометрия -- frozen screen_svg;
                # data несёт экранную форму (достаточно)
                assert data, view_id
            elif site_kind == "html_table" and view_id != "eda.ih.conditional_map":
                assert isinstance(data.get("columns"), list), view_id
                assert isinstance(data.get("rows"), list), view_id
            # conditional_map -- ih-матрица: полная каноническая форма
            # матрицы (AC02) проверяется в TestPrintForms

    def test_out_of_scope_views_still_refuse_with_task_hint(self):
        """Паспорта (PGV-04/13), demo, modeling/forecasting (PGV-12) --
        честный отказ экспорта с именем добирающей задачи; EDA/tasks
        скоупа PGV-11 -- РАЗРЕШАЮТСЯ (пин скоупа)."""
        import pytest

        from apps.api.visual_exports import (
            VisualExportOutOfScope,
            resolve_export_view,
        )

        for view_id, task in (
            ("eda.passport.panel", "PGV-04"),
            ("eda.passport.comparison", "PGV-13"),
            ("navigator.upload.chart.series", "static demo"),
            ("modeling.backtest.comparison", "PGV-12"),
            ("forecasting.forecast.chart", "PGV-12"),
        ):
            with pytest.raises(VisualExportOutOfScope) as excinfo:
                resolve_export_view(view_id)
            assert task in str(excinfo.value)

        from apps.api.visual_exports import pgv11_export_view_ids

        for view_id in pgv11_export_view_ids():
            assert resolve_export_view(view_id)["view_id"] == view_id

    def test_pgv11_print_specs_complete(self):
        """Печатные спецификации полны: титул у всех 17; оси у всех
        chart-сайтов (AC01 -- свой график, не другой subplot);
        композиции mixed-сайтов -- >=2 секций разных kinds."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import (
            CHART_AXES,
            VIEW_TITLES,
            mixed_sections_for,
            pgv11_export_view_ids,
        )

        kinds = {
            site["view_id"]: site["renderer_kind"]
            for site in load_visual_registry()["sites"]
        }
        for view_id in pgv11_export_view_ids():
            assert view_id in VIEW_TITLES, view_id
            sections = mixed_sections_for(view_id, kinds[view_id])
            assert sections, view_id
            has_chart = any(
                s["renderer_kind"] == "recharts_svg" for s in sections
            )
            if has_chart:
                assert view_id in CHART_AXES, view_id
                axes = CHART_AXES[view_id]
                assert len(axes) == 2
                for axis in axes:
                    assert axis["name"]
                    unit = axis["units"]
                    assert unit["value"] or unit["reason"], view_id
            if kinds[view_id] == "mixed":
                assert len(sections) >= 2, view_id
                assert len({s["renderer_kind"] for s in sections}) >= 2, view_id


# ══════════════════════════════════════════════════════════════════════
# 2. Печатные формы адаптеров (аддитивные; экранная форма не меняется)
# ══════════════════════════════════════════════════════════════════════


class TestPrintForms:
    def test_table_views_carry_columns_rows_from_frozen_data(self):
        """Табличные сайты: {columns, rows} -- каноническая форма моста;
        экранная форма сохранена (аддитивно)."""
        for view_id in ("eda.descriptive.stats", "eda.ih.metrics_table"):
            data = _slice_of(view_id)
            assert data["columns"] and data["rows"], view_id
            row = data["rows"][0]
            assert all(name in row for name in data["columns"]), view_id

    def test_ih_conditional_map_full_matrix_form(self):
        """AC02: срез conditional_map несёт полную IH-матрицу -- bins
        строк/колонок, проценты, знаменатель (сумма строки), n
        наблюдений; печатается таблицей (SVG-only не подходит, §2)."""
        data = _slice_of("eda.ih.conditional_map")
        ih = data["ih_input"]
        assert ih["x_bins"] == ["[0, 5)", "[5, 10)"]
        assert ih["y_bins"] == ["низкий", "высокий"]
        assert ih["n_observations"] == 96
        assert ih["feature_label"] == "lag_1"
        assert ih["target_label"] == "value"
        row = ih["rows"][0]
        assert row["x_bin"] == "[0, 5)"
        assert row["values"] == [60.0, 40.0]
        assert row["row_sum"] == 100.0, "знаменатель долей строки"
        assert ih["row_totals"] is None, (
            "абсолютный n строки не сохранён -- честная причина, не фабрикация"
        )
        assert ih["denominator_note"], "честная пометка о знаменателе"
        # экранная форма сохранена (аддитивность)
        assert data["matrix"][0]["values"] == [60.0, 40.0]

    def test_heatmap_matrix_unfolded_from_pairs(self):
        """feature_select.matrix: пары {row, column, value} развёрнуты в
        каноническую форму html_heatmap {row_headings, column_headings,
        cells} из ТЕХ ЖЕ frozen данных (одна шкала, row headers, §7)."""
        data = _slice_of("eda.feature_select.matrix")
        assert data["row_headings"] == ["lag_1", "lag_2"]
        assert data["column_headings"] == ["lag_1", "lag_2"]
        assert data["cells"] == [[1.0, 0.4], [0.4, 1.0]]
        assert isinstance(data["cell_texts"], list)

    def test_mixed_views_carry_table_form_alongside_screen_form(self):
        """Mixed-сайты: экранная форма (series/tests/folds...) сохранена,
        печатная {columns, rows} достроена из того же ответа (§6:
        producer несёт print input)."""
        cases = {
            "eda.correlation.acf_pacf": "acf",
            "eda.ih.results": "results",
            "eda.seasonality.spectrum": "fft",
            "eda.stationarity.tests": "tests",
            "eda.distribution.tests": "tests",
            "eda.structural.breakpoints": "segments",
            "eda.validation_strategy.windows": "folds",
            "eda.model_matrix.applicability": "models",
            "tasks.causes.fold_importance": "method",
        }
        for view_id, screen_key in cases.items():
            data = _slice_of(view_id)
            assert screen_key in data, view_id
            assert data.get("columns") and data.get("rows"), view_id

    def test_tasks_causes_carries_modeling_artifact_ref(self):
        """tasks view: modeling_artifact_ref -- из frozen card (обязательный
        ref реестра PGV-00), без фабрикации."""
        data = _slice_of("tasks.causes.fold_importance")
        assert data["modeling_artifact_ref"] == "card-pgv11-1"

    def test_tasks_not_computed_is_not_frozen_by_design(self):
        """not_computed не фабрикуется: wiring freeze только при
        available (договор поставки -- пин формы ответа)."""
        response = {
            "method": {
                "method_id": "fold_importance",
                "status": "not_computed",
                "reason": "нет привязанных fold-записей",
                "factors": [],
            },
            "card": {"card_id": "card-x"},
        }
        from apps.api.visual_producers import adapter_spec

        data = adapter_spec("tasks.causes.fold_importance").extract(response)
        assert data["method"]["status"] == "not_computed"
        assert data["method"]["factors"] == []
        # печатная форма честно пуста (без выдуманных строк)
        assert data["rows"] == []

    def test_honest_forms_are_canonicalizable(self):
        """Все 17 срезов канонизируются (гейт persist PGV-02)."""
        from apps.api.artifact_store import canonical_json_bytes
        from apps.api.visual_exports import pgv11_export_view_ids

        for view_id in pgv11_export_view_ids():
            canonical_json_bytes(_slice_of(view_id))


# ══════════════════════════════════════════════════════════════════════
# 3. Сборка VisualPrintSnapshot/1 (PGV-01-контракт)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotBuilder:
    def test_every_view_snapshot_passes_pgv01_validation(self):
        """Снапшот КАЖДОГО view скоупа валиден по PGV-01 (состав секций,
        заголовки таблиц, шкала heatmap, оси графиков)."""
        from apps.api.print_schema import validate_print_snapshot
        from apps.api.visual_exports import pgv11_export_view_ids

        for view_id in pgv11_export_view_ids():
            needs_svg = mixed_has_chart(view_id)
            snapshot, _artifact = _build_snapshot(
                view_id, screen_svg=SCREEN_SVG if needs_svg else None
            )
            violations = validate_print_snapshot(snapshot)
            assert not violations, f"{view_id}: {violations}"

    def test_ac01_distribution_views_are_separate_oracles(self):
        """AC01: scatter/histogram/kde -- РАЗНЫЕ view: разные title/оси
        и свой sampling; один view не подменяет другой subplot."""
        from apps.api.visual_exports import VIEW_TITLES

        snapshots = {}
        for view_id in (
            "eda.descriptive.distribution.scatter",
            "eda.descriptive.distribution.histogram",
            "eda.descriptive.distribution.kde",
        ):
            snapshot, _ = _build_snapshot(view_id, screen_svg=SCREEN_SVG)
            snapshots[view_id] = snapshot
            assert snapshot["display"]["title"] == VIEW_TITLES[view_id]
            chart = snapshot["display"]["sections"][0]
            names = [axis["name"] for axis in chart["axes"]]
            assert len(names) == 2
        # у scatter обе оси -- значение; у histogram Y -- число наблюдений
        scatter_axes = snapshots["eda.descriptive.distribution.scatter"]["display"]["sections"][0]["axes"]
        hist_axes = snapshots["eda.descriptive.distribution.histogram"]["display"]["sections"][0]["axes"]
        assert scatter_axes[0]["name"] != hist_axes[1]["name"]
        assert "Число наблюдений" in hist_axes[1]["name"]

    def test_ac02_conditional_map_prints_full_matrix(self):
        """AC02: печатная секция conditional_map -- html_table с
        замороженными динамическими заголовками (bins строк/колонок),
        полный состав матрицы в контенте, caption с честной шкалой."""
        snapshot, _ = _build_snapshot("eda.ih.conditional_map")
        section = snapshot["display"]["sections"][0]
        assert section["renderer_kind"] == "html_table"
        headings = section["table_headings"]
        assert headings["row"] == ["Интервал «lag_1» \\ «value»"]
        assert headings["column"] == ["низкий", "высокий", "Сумма строки, %"]

    def test_stable_heatmap_scale_from_frozen_cells(self):
        """Стабильная scale: домен тепловой карты -- из ФАКТИЧЕСКИХ
        ячеек frozen данных; две сборки -- один домен (детерминизм)."""
        first, _ = _build_snapshot("eda.feature_select.matrix")
        second, _ = _build_snapshot("eda.feature_select.matrix")
        scale_a = first["display"]["sections"][0]["heatmap_scale"]
        scale_b = second["display"]["sections"][0]["heatmap_scale"]
        assert scale_a["domain"] == [0.4, 1.0], "мин/макс фактических ячеек"
        assert scale_a == scale_b

    def test_mixed_snapshot_sections_from_one_frozen_data(self):
        """Mixed-сайт: секции снапшота -- >=2 разных kinds из ОДНОГО
        frozen результата; table-секции несут заголовки печати."""
        snapshot, _ = _build_snapshot("eda.stationarity.tests", screen_svg=SCREEN_SVG)
        sections = snapshot["display"]["sections"]
        assert len(sections) >= 2
        kinds = [s["renderer_kind"] for s in sections]
        assert "recharts_svg" in kinds and "html_table" in kinds
        table = next(s for s in sections if s["renderer_kind"] == "html_table")
        assert table["table_headings"]["row"] and table["table_headings"]["column"]

    def test_tasks_view_refs_carry_modeling_artifact_ref(self):
        """tasks view: refs снапшота несут modeling_artifact_ref из
        frozen card; без него -- честный отказ (refs не фабрикуются)."""
        snapshot, _ = _build_snapshot(
            "tasks.causes.fold_importance", screen_svg=SCREEN_SVG
        )
        assert snapshot["refs"]["modeling_artifact_ref"] == "card-pgv11-1"

        import pytest

        from apps.api.visual_exports import VisualSourceUnavailable

        without_ref = {
            key: value
            for key, value in _slice_of("tasks.causes.fold_importance").items()
            if key != "modeling_artifact_ref"
        }
        with pytest.raises(VisualSourceUnavailable):
            _build_snapshot(
                "tasks.causes.fold_importance",
                data_override=without_ref,
                result_ref="vr-pgv11-tasks-noref",
                screen_svg=SCREEN_SVG,
            )

    def test_chart_view_without_screen_svg_is_honest_preflight(self):
        """§3.6: график не фабрикуется -- chart-секция без frozen
        screen_svg -- preflight-отказ ДО постановки job'а."""
        import pytest

        from apps.api.visual_exports import PrintScreenSvgRequired

        with pytest.raises(PrintScreenSvgRequired):
            _build_snapshot("eda.descriptive.distribution.scatter")

    def test_sampling_transferred_honestly(self):
        """AC08: sampling frozen результата переносится в снапшот
        (detail_level=sampling при неполном показе)."""
        snapshot, _ = _build_snapshot(
            "eda.descriptive.distribution.scatter", screen_svg=SCREEN_SVG
        )
        assert snapshot["sampling"]["mode"] == "full"
        assert snapshot["display"]["detail_level"] == "expanded"

        from apps.api.visual_producers import adapter_spec

        sampled = dict(HONEST_RESPONSES["eda.descriptive.distribution.scatter"])
        sampled["scatter_sampled"] = True
        spec = adapter_spec("eda.descriptive.distribution.scatter")
        sampling = spec.sampling(sampled, sampled.get("sampling"))
        assert sampling["mode"] in ("downsampled", "windowed", "truncated", "aggregated")

    def test_missing_frozen_headings_are_honest_rejection(self):
        """AC02-гейт: ih_input без bins -- заголовки печати не выводятся,
        честный отказ (заголовки не фабрикуются)."""
        import pytest

        from apps.api.visual_exports import VisualExportError

        broken = dict(_slice_of("eda.ih.conditional_map"))
        broken["ih_input"] = {**broken["ih_input"], "y_bins": []}
        with pytest.raises(VisualExportError):
            _build_snapshot(
                "eda.ih.conditional_map",
                data_override=broken,
                result_ref="vr-pgv11-ih-nobins",
            )


def mixed_has_chart(view_id: str) -> bool:
    from apps.api.print_schema import load_visual_registry
    from apps.api.visual_exports import mixed_sections_for

    site = next(
        s for s in load_visual_registry()["sites"] if s["view_id"] == view_id
    )
    return any(
        s["renderer_kind"] == "recharts_svg"
        for s in mixed_sections_for(view_id, site["renderer_kind"])
    )


# ══════════════════════════════════════════════════════════════════════
# 4. Мост контента: секции из frozen data (render payload/1)
# ══════════════════════════════════════════════════════════════════════


class TestRenderPayloadBridge:
    def _bridge(self, view_id: str):
        from apps.api.print_render_payload import (
            build_render_payload,
            section_content_from_visual_result,
        )

        snapshot, artifact = _build_snapshot(
            view_id, screen_svg=SCREEN_SVG if mixed_has_chart(view_id) else None
        )
        result = _payload_of(artifact)
        content = section_content_from_visual_result(snapshot, result)
        payload = build_render_payload(snapshot, content, request_id="pgv11:bridge")
        return snapshot, content, payload

    def test_conditional_map_table_content_is_full_matrix(self):
        """AC02: контент таблицы -- ВСЕ строки/колонки матрицы, проценты,
        сумма строки; заголовки -- замороженные динамические."""
        _snapshot, content, payload = self._bridge("eda.ih.conditional_map")
        section = payload["sections"][0]
        assert section["kind"] == "html_table"
        rows = section["rows"]
        assert len(rows) == 2, "все интервалы фактора"
        assert rows[0][0] == "[0, 5)", "row header -- бин фактора"
        assert rows[0][1] == "60.0" and rows[0][2] == "40.0"
        assert rows[0][3] == "100.0", "знаменатель долей строки"
        assert section["headings"]["column"][-1] == "Сумма строки, %"
        assert section.get("caption"), "честная пометка о шкале/знаменателе"

    def test_heatmap_content_with_stable_domain(self):
        _snapshot, content, payload = self._bridge("eda.feature_select.matrix")
        section = payload["sections"][0]
        assert section["kind"] == "html_heatmap"
        assert section["row_headings"] == ["lag_1", "lag_2"]
        assert section["cells"] == [[1.0, 0.4], [0.4, 1.0]]

    def test_mixed_content_chart_plus_table(self):
        _snapshot, content, payload = self._bridge("eda.stationarity.tests")
        kinds = [s["kind"] for s in payload["sections"]]
        assert kinds[0] == "recharts_svg"
        assert content["chart"]["svg_xml"] == SCREEN_SVG
        table = next(s for s in payload["sections"] if s["kind"] == "html_table")
        assert table["rows"], "таблица тестов из frozen data"

    def test_old_artifact_without_print_forms_is_honest_incomplete(self):
        """unavailable не фабрикуется: старый frozen артефакт без
        печатных форм -- missing_section_content (§3.6), не подмена."""
        import pytest

        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            section_content_from_visual_result,
        )

        view_id = "eda.ih.metrics_table"
        artifact = _freeze_slice(
            view_id, drop_print_forms=True, result_ref="vr-pgv11-metrics-old"
        )
        result = _payload_of(artifact)
        snapshot, _ = _build_snapshot(view_id)
        with pytest.raises(PrintRenderPayloadIncomplete):
            section_content_from_visual_result(snapshot, result)


# ══════════════════════════════════════════════════════════════════════
# 5. HTTP-контракт экспорта (те же роуты -- без новых surface)
# ══════════════════════════════════════════════════════════════════════


def _client_get_json(path: str, cookies: dict | None = None) -> dict:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        test_client.cookies.update(cookies or {"cisstat_session_id": SESSION_ID})
        response = test_client.get(path)
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {}
        return {"status": response.status_code, "data": payload}


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


class TestVisualExportHttp:
    def test_post_visuals_202_for_every_scope_view(self):
        """AC03 (API-уровень): каждый view скоупа принимает «Скачать
        PNG» -- 202 + status_url; job доводится до ready штатным
        worker'ом с fake-renderer'ом (контейнер PGV-08 недоступен в
        среде -- граница PGV-08; полный путь job'а проверен, очередь
        освобождается -- квота tenant не переполняется)."""
        from apps.api import document_jobs, document_render_worker
        from apps.api.visual_exports import pgv11_export_view_ids

        class _FakeClient:
            def render_page(self, payload, *, timeout_s=None):
                assert payload["sections"], "render payload без секций"
                return b"\x89PNG\r\n\x1a\n" + b"0" * 64

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service,
            png_renderer=_FakeClient(),
        )

        for view_id in pgv11_export_view_ids():
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

    def test_post_visuals_passport_view_422_with_task_hint(self):
        _seed_run()
        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "eda.passport.panel"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "view_out_of_scope"
        assert "PGV-04" in body["data"]["message"]

    def test_post_visuals_foreign_run_uniform_404(self):
        """AC18: чужой run -- uniform 404 (знание run_id не право)."""
        _seed_run()
        _freeze_slice("eda.ih.metrics_table")
        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "eda.ih.metrics_table"},
            cookies={"cisstat_session_id": "pgv11-foreign-cookie"},
        )
        assert body["status"] == 404
        assert body["data"]["code"] == "not_found"

    def test_post_visuals_without_frozen_result_409(self):
        """unavailable не фабрикуется: view не открывался -- 409
        source_unavailable, пересчёт науки запрещён."""
        _seed_run()
        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "eda.seasonality.spectrum"},
        )
        assert body["status"] == 409
        assert body["data"]["code"] == "source_unavailable"

    def test_post_visuals_chart_without_svg_422(self):
        _seed_run()
        _freeze_slice("eda.descriptive.distribution.histogram")
        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "eda.descriptive.distribution.histogram"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "screen_svg_required"

    def test_post_visuals_cas_conflict_409(self):
        """AC07: смена контекста при freeze -- 409 context_changed
        (табличный view: без screen_svg-preflight, CAS доходит до
        freeze снапшота)."""
        _seed_run()
        _freeze_slice("eda.descriptive.stats")
        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "eda.descriptive.stats",
             "expected_context_id": "ctx-old"},
        )
        assert body["status"] == 409
        assert body["data"]["code"] == "context_changed"


# ══════════════════════════════════════════════════════════════════════
# 6. GET visual-sources: 55 источников, честные состояния
# ══════════════════════════════════════════════════════════════════════


class TestVisualSourcesList:
    def test_visual_sources_lists_combined_scope(self):
        _seed_run()
        _freeze_slice("eda.ih.metrics_table")
        body = _client_get_json(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources"
        )
        assert body["status"] == 200
        sources = body["data"]["sources"]
        ids = [s["view_id"] for s in sources]
        assert len(ids) == 55, "38 PGV-10 + 17 PGV-11"
        ih = next(s for s in sources if s["view_id"] == "eda.ih.metrics_table")
        assert ih["export_ready"] is True
        assert ih["latest_result"]["result_ref"]
        empty = next(s for s in sources if s["view_id"] == "eda.ih.results")
        assert empty["export_ready"] is False
        assert empty["unavailable_reason"], "честная причина, не фабрикация"

    def test_visual_sources_foreign_run_uniform_404(self):
        _seed_run()
        body = _client_get_json(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources",
            cookies={"cisstat_session_id": "pgv11-foreign-cookie"},
        )
        assert body["status"] == 404
