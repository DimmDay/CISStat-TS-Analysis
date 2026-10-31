# tests/api/test_pgv10_visual_exports.py
"""Задача PGV-10 (spec_passport_graphics_visual.md §10.1/§11/§13,
строка PGV-10): Export upload/validation/preprocessing -- «Скачать
PNG» на всех render sites трёх остановок.

Критерий завершения (§13): «Верный PNG каждого view, before/after/
sampling, не первый SVG».

Дизайн поставки:
  • producer-слой: 12 недобранных preprocessing view добираются
    адаптерами PGV-03-паттерна (UNWIRED_PGV03_VIEWS сужается честно);
  • экспорт-слой apps/api/visual_exports.py: GET visual-sources
    (доступные frozen inputs БЕЗ запуска науки, §11) и POST visuals
    (freeze durable visual_result -> VisualPrintSnapshot/1 -> V01
    revision -> PNG job через PGV-09);
  • frozen экранный SVG (§4.1 passthrough, rendererCore PGV-08):
    клиент сериализует СВОЙ chart-узел (не «первый SVG документа»);
    снапшот несёт screen_svg в секции, identity снапшота включает
    его digest (иной frozen print input -- другая ревизия, AC08);
  • мост контента: секции собираются ПО СВОЕМУ renderer_kind из
    frozen data (mixed-сайты -- несколько секций); отсутствие формы
    -- честный missing_section_content (§3.6, не подменяется).

Оракулы на СВОИХ данных: корпус дизъюнктен repo и PGV-02/03/08/09
(RUN-PGV10xxxx, pgv10-*); изоляция -- паттерн test_pgv09. Контейнер
PGV-08 в среде сессии недоступен (унаследованная граница): полный
путь до job'а -- через штатный document_render_worker.run_once с
инъекцией fake-renderer'а (паттерн класса D PGV-09); контент моста --
чистые функции.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun

# ── Изоляция КАЖДОГО теста (паттерн test_pgv09_jobs_renderer_integration) ──


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


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы на СВОИХ данных (корпус pgv10) ────────────────────────

RUN_ID = "RUN-PGV10A01"
SESSION_ID = "pgv10-seed-session"
CONTEXT_ID = "ctx-pgv10-1"
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
        dataset_fingerprint="pgv10" * 6,
        dataset_name="pgv10-visual-exports-seed",
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
    """AnalysisSession с датасетом/контекстом, СОХРАНЁННАЯ в store
    (экспорт читает date_column структуры из сессии запуска)."""
    from apps.api.session_store import (
        AnalysisSession,
        DatasetInfo,
        get_session_store,
    )

    session = AnalysisSession(session_id=SESSION_ID)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="pgv10-ds",
        name="pgv10-seed",
        rows=96,
        columns=2,
        size_label="4 KB",
        dataset_fingerprint="pgv10" * 6,
    )
    session.data_revision = DATA_REVISION
    session.set_date_column("date")
    try:
        get_session_store().save(session)
    except Exception:  # noqa: BLE001 -- повторный сид в одном тесте
        pass
    return session


def _sync_run_to_session(session) -> None:
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(session.run_id)
    assert run is not None, "run не посеян"
    get_research_run_store().upsert_run(
        dc_replace(
            run,
            context_id=session.current_context_id(),
            data_revision=session.data_revision,
        )
    )


def _payload_of(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    return json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


def _visual_results(run_id: str = RUN_ID, view_id: str | None = None):
    from apps.api.visual_artifacts import list_visual_results

    artifacts = list_visual_results(run_id)
    if view_id is None:
        return artifacts
    return [a for a in artifacts if a.refs.get("view_id") == view_id]


TABLE_DATA = {
    "columns": ["name", "dtype", "non_null", "nulls"],
    "rows": [
        {"name": "Дата", "dtype": "datetime64", "non_null": 96, "nulls": 0},
        {"name": "Оборот", "dtype": "float64", "non_null": 94, "nulls": 2},
    ],
}


def _frozen_visual_result(
    view_id: str = "upload.overview.tech_table",
    *,
    data: dict | None = None,
    kind: str = "html_table",
    result_ref: str = "vr-pgv10-table-0001",
    method: str = "tech_info",
    selection: dict | None = None,
    units: list | None = None,
    sampling: dict | None = None,
    computed_at: str | None = "2026-10-30T09:00:00Z",
) -> dict:
    """VisualResult/1 (зеркало правил PGV-01; форма адаптеров PGV-03)."""
    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    data = data if data is not None else TABLE_DATA
    return {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": view_id,
        "payload": {
            "kind": kind,
            "series_cap": (sampling or {}).get("point_cap"),
            "digest": artifact_content_sha256(canonical_json_bytes(data)),
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": "producer_freeze",
            "method": method,
            "parameters": dict(selection or {"selected_column": "Оборот"}),
        },
        "units": units if units is not None else [{"value": None, "reason": "dimensionless"}],
        "sampling": sampling or {
            "applicable": True, "mode": "full", "point_cap": None, "reason": None,
        },
        "warnings": [],
        "execution": {
            "execution_ref": f"exec-pgv10-{view_id}",
            "result_ref": result_ref,
            "computed_at": computed_at,
            "computed_at_reason": None if computed_at else "producer_not_reported",
        },
    }


def _freeze_visual_result(view_id: str = "upload.overview.tech_table", **kwargs):
    from apps.api.visual_artifacts import freeze_visual_result

    _seed_run()
    _seed_session_object()
    return freeze_visual_result(
        RUN_ID,
        _owner_subject(),
        payload=_frozen_visual_result(view_id, **kwargs),
        session_id=SESSION_ID,
    )


# ══════════════════════════════════════════════════════════════════════
# 1. Скоуп экспорта (spec §13 PGV-10: upload/validation/preprocessing)
# ══════════════════════════════════════════════════════════════════════


class TestExportScope:
    def test_pgv10_scope_is_pgv03_research_views_of_three_modules(self):
        """Скоуп PGV-10 -- pgv-03 research view модулей
        upload/validation/preprocessing (spec §13: «Все render sites
        этих stops»); navigator/demo, паспорта (pgv-04/13), EDA/
        modeling/forecasting/tasks (PGV-11/12) -- вне скоупа."""
        from apps.api.visual_exports import pgv10_export_view_ids

        from apps.api.print_schema import load_visual_registry

        expected = sorted(
            site["view_id"]
            for site in load_visual_registry()["sites"]
            if site["module_id"] in ("upload", "validation", "preprocessing")
            and str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        )
        assert list(pgv10_export_view_ids()) == expected
        assert len(expected) == 38, "санити: 10 upload + 10 validation + 18 preprocessing"
        assert "upload.passport.panel" not in expected
        assert "upload.passport.comparison" not in expected

    def test_every_pgv10_view_is_wired_after_this_task(self):
        """12 недобранных preprocessing view добраны: UNWIRED_PGV03_VIEWS
        не содержит ни одного view скоупа PGV-10 (честный недобор
        PGV-03 сужен поставкой, gap закрыт -- не замалчиван)."""
        from apps.api.visual_exports import pgv10_export_view_ids
        from apps.api.visual_producers import (
            UNWIRED_PGV03_VIEWS,
            adapter_spec,
            resolve_producer_view,
        )

        unwired_in_scope = set(pgv10_export_view_ids()) & UNWIRED_PGV03_VIEWS
        assert unwired_in_scope == set(), (
            f"адаптеры не добраны: {sorted(unwired_in_scope)}"
        )
        for view_id in pgv10_export_view_ids():
            site = resolve_producer_view(view_id)
            spec = adapter_spec(view_id)
            assert spec.module_id == site["module_id"]

    def test_out_of_scope_views_refuse_export_with_hint(self):
        """passport/comparison (PGV-13/04), demo, modeling/forecast --
        честный отказ экспорта с именем добирающей задачи. (EDA/tasks
        вошли в скоуп поставкой PGV-11 -- их отказ убран честным
        сужением списка, скоуп пинится корпусом test_pgv11.)"""
        import pytest

        from apps.api.visual_exports import (
            VisualExportOutOfScope,
            resolve_export_view,
        )

        for view_id, task in (
            ("upload.passport.panel", "PGV-04"),
            ("upload.passport.comparison", "PGV-13"),
            ("navigator.upload.chart.series", "static demo"),
            ("modeling.backtest.comparison", "PGV-12"),
            ("forecasting.forecast.chart", "PGV-12"),
        ):
            with pytest.raises(VisualExportOutOfScope) as excinfo:
                resolve_export_view(view_id)
            assert task in str(excinfo.value)

    def test_unknown_view_is_honest_rejection(self):
        import pytest

        from apps.api.visual_exports import UnknownExportView, resolve_export_view

        with pytest.raises(UnknownExportView):
            resolve_export_view("upload.chart.nonexistent")

    def test_mixed_view_compositions_declared_for_all_mixed_in_scope(self):
        """Каждый mixed-сайт скоупа имеет декларацию печатной композиции
        (>=2 секции разных kinds -- правила PGV-01); не-mixed -- ровно
        одна секция своего kind (validate_print_snapshotPGV-01)."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import mixed_sections_for

        for site in load_visual_registry()["sites"]:
            if site["view_id"] not in pgv10_scope():
                continue
            sections = mixed_sections_for(site["view_id"], site["renderer_kind"])
            kinds = [section["renderer_kind"] for section in sections]
            if site["renderer_kind"] == "mixed":
                assert len(sections) >= 2
                assert len(set(kinds)) >= 2
            else:
                assert kinds == [site["renderer_kind"]]


def pgv10_scope():
    from apps.api.visual_exports import pgv10_export_view_ids

    return set(pgv10_export_view_ids())


# ══════════════════════════════════════════════════════════════════════
# 2. Адаптеры добора (срезы РЕАЛЬНЫХ форм ответов, зеркала builders)
# ══════════════════════════════════════════════════════════════════════


class TestDoborAdapters:
    """12 добранных адаптеров: срезы из фактических форм ответов
    строителей (validation/regularity.py, preprocessing_* builders);
    units/sampling честны, никакой науки."""

    def test_regularity_overview_table_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.regularity.overview")
        response = {
            "mode": "auto",
            "status": "done",
            "status_reason": None,
            "profile": {
                "applicable": True, "reason": None,
                "date_column": "date", "entity_column": None,
                "frequency": "D", "total_points": 96,
                "total_violations": 3, "gaps": 2, "duplicates": 1,
                "sort_violations": 0,
            },
        }
        data = spec.extract(response)
        assert data["columns"] and data["rows"]
        assert data["rows"][0]["field"] == "date_column"

    def test_regularity_gap_map_mixed_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.regularity.gap_map")
        response = {
            "date_column": "date", "entity_column": None,
            "min_date": "2025-01-01T00:00:00", "max_date": "2025-04-01T00:00:00",
            "events": [
                {"date": "2025-02-01T00:00:00", "kind": "gap", "group": "—"},
                {"date": "2025-03-01T00:00:00", "kind": "duplicate", "group": "—"},
            ],
            "truncated": False,
        }
        data = spec.extract(response)
        assert data["events"] == response["events"]
        assert data["columns"] and len(data["rows"]) == 2

    def test_decomposition_overview_series_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.decomposition.overview")
        response = {
            "applicable": True, "reason": None,
            "column": "value", "period": 12, "method": "STL",
            "points": [
                {"x": "2025-01-01", "observed": 1.0, "trend": 1.1,
                 "seasonal": 0.2, "resid": -0.3},
            ],
            "warnings": [],
        }
        data = spec.extract(response)
        assert data["series"] == response["points"]
        assert data["method"] == "STL"

    def test_variance_views_slices(self):
        from apps.api.visual_producers import adapter_spec

        response = {
            "column": "value", "applicable": True, "reason": None,
            "n_observations": 96, "missing_count": 0,
            "selected_method": "box_cox", "lambda_value": 0.15,
            "needs_stabilization": True,
            "diagnostics_before": {"stability_score": 41.0, "arch_lm_lag": 2},
            "diagnostics_after": {"stability_score": 78.0, "arch_lm_lag": 2},
            "candidates": [
                {"method": "box_cox", "label": "Box–Cox", "available": True,
                 "reason": None, "lambda_value": 0.15, "stability_score": 78.0},
            ],
            "points": [
                {"x": "2025-01-01", "original": 10.0, "transformed": 2.1,
                 "rolling_std_before": 1.2, "rolling_std_after": 0.4},
            ],
            "histogram": [
                {"bin": 0, "original_x": 1.0, "original_density": 0.2,
                 "transformed_x": 0.1, "transformed_density": 0.5},
            ],
            "warnings": [], "recommendation": "рекомендация",
        }
        series = adapter_spec("preprocessing.variance_stab.series").extract(response)
        assert series["series"] == response["points"]
        assert series["selected_method"] == "box_cox"
        rolling = adapter_spec("preprocessing.variance_stab.rolling").extract(response)
        assert rolling["series"] == response["points"]
        methods = adapter_spec("preprocessing.variance_stab.methods").extract(response)
        assert methods["candidates"] == response["candidates"]
        distribution = adapter_spec(
            "preprocessing.variance_stab.distribution"
        ).extract(response)
        assert distribution["bins"] == response["histogram"]
        diagnostics = adapter_spec(
            "preprocessing.variance_stab.diagnostics"
        ).extract(response)
        assert diagnostics["cards"][0]["label"]
        assert diagnostics["diagnostics_before"] == response["diagnostics_before"]

    def test_stationarity_overview_mixed_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.stationarity.overview")
        response = {
            "column": "value", "applicable": True, "reason": None,
            "selected_method": "diff", "needs_transformation": True,
            "tests": [
                {"test": "ADF(c)", "before_p_value": 0.4, "after_p_value": 0.01},
            ],
            "points": [{"x": "2025-01-01", "original": 1.0, "transformed": 0.1}],
        }
        data = spec.extract(response)
        assert data["series"] == response["points"]
        assert data["tests"] == response["tests"]
        # mixed: данные несут ОБЕ формы (chart + table)
        assert data["columns"] and data["rows"]

    def test_spectral_periodogram_mixed_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.spectral.periodogram")
        response = {
            "column": "value", "applicable": True, "reason": None,
            "welch": [{"frequency": 0.08, "power": 3.2, "period": 12.5}],
            "bands": [{"label": "сезонные", "power_share": 0.6}],
            "candidates": [{"period": 12.5, "strength": 0.7}],
        }
        data = spec.extract(response)
        assert data["series"] == response["welch"]
        assert data["columns"] and data["rows"]

    def test_feature_eng_overview_mixed_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.feature_eng.overview")
        response = {
            "column": "value", "applicable": True, "reason": None,
            "preview_points": [{"x": "2025-01-01", "target": 1.0, "lag": 0.9}],
            "catalog": [{"name": "lag_1", "family": "lag", "coverage": 1.0}],
            "lag_correlations": [{"lag": 1, "correlation": 0.8, "selected": True}],
        }
        data = spec.extract(response)
        assert data["series"] == response["preview_points"]
        assert data["columns"] and data["rows"]

    def test_scaling_overview_mixed_slice(self):
        from apps.api.visual_producers import adapter_spec

        spec = adapter_spec("preprocessing.scaling.overview")
        response = {
            "target_column": "value", "applicable": True, "reason": None,
            "recommended_method": "robust_scaler",
            "preview_points": [{"x": "2025-01-01", "original": 10.0, "scaled": 0.5}],
            "range_points": [{"column": "value", "log_scale_before": 1.2,
                              "log_scale_after": 0.1}],
            "methods": [{"method": "robust_scaler", "label": "Robust"}],
        }
        data = spec.extract(response)
        assert data["series"] == response["preview_points"]
        assert data["columns"] and data["rows"]

    def test_new_adapter_payloads_pass_pgv01_gate(self):
        """Payload каждого добранного view проходит валидационный гейт
        PGV-01 (units/sampling/trusted) -- паритет 48 wired адаптеров."""
        from apps.api.print_schema import validate_visual_result

        from apps.api.visual_exports import pgv10_export_view_ids
        from apps.api.visual_producers import (
            adapter_spec,
            build_visual_result_payload,
        )

        for view_id in sorted(pgv10_scope()):
            spec = adapter_spec(view_id)
            payload = build_visual_result_payload(
                view_id,
                _honest_response_for(view_id),
                result_ref="vr-pgv10-gate",
                computed_at="2026-10-30T09:00:00Z",
            )
            violations = validate_visual_result(payload)
            assert not violations, f"{view_id}: {violations}"


def _honest_response_for(view_id: str) -> dict:
    """Минимальные ЧЕСТНЫЕ формы ответов строителей для гейт-оракула
    (зеркала реальных builders; не выдуманные поля -- срезы берутся из
    этих форм адаптерами)."""
    series_point = {"x": "2025-01-01", "original": 1.0, "transformed": 0.5}
    if view_id == "preprocessing.regularity.overview":
        return {"profile": {"applicable": True, "date_column": "date",
                            "frequency": "D", "total_violations": 0}}
    if view_id == "preprocessing.regularity.gap_map":
        return {"events": [], "truncated": False}
    if view_id == "preprocessing.decomposition.overview":
        return {"applicable": True, "points": [
            {"x": "2025-01-01", "observed": 1.0, "trend": 1.0,
             "seasonal": 0.0, "resid": 0.0}], "method": "STL"}
    if view_id.startswith("preprocessing.variance_stab."):
        return {
            "selected_method": "box_cox", "lambda_value": 0.1,
            "diagnostics_before": {"stability_score": 10.0},
            "diagnostics_after": {"stability_score": 80.0},
            "candidates": [], "points": [series_point], "histogram": [],
        }
    if view_id == "preprocessing.stationarity.overview":
        return {"selected_method": "diff", "tests": [], "points": [series_point]}
    if view_id == "preprocessing.spectral.periodogram":
        return {"welch": [{"frequency": 0.1, "power": 1.0, "period": 10.0}],
                "bands": [{"label": "высокие", "power_share": 0.3}]}
    if view_id == "preprocessing.feature_eng.overview":
        return {"preview_points": [dict(series_point, target=1.0)],
                "catalog": [{"name": "lag_1", "family": "lag", "coverage": 0.9}]}
    if view_id == "preprocessing.scaling.overview":
        return {"recommended_method": "robust_scaler",
                "preview_points": [dict(series_point, scaled=0.5)],
                "range_points": [{"column": "value", "log_scale_before": 1.0,
                                  "log_scale_after": 0.1}]}
    # Остальные view скоупа (wired PGV-03): честные формы из их адаптеров.
    if view_id == "upload.overview.preview":
        return {"preview": {"head": [["a", "1"]], "tail": [["b", "2"]]}}
    if view_id == "upload.overview.tech_table":
        return {"columns_info": [{"name": "value", "dtype": "float64",
                                  "type_icon": "#", "non_null": 9,
                                  "nulls": 0, "unique": 9}]}
    if view_id == "upload.quality.teaser":
        return {"quality": {"cols_with_missing": 0, "cols_with_outliers": 0,
                            "rows_total": 9, "duplicates": 0}}
    if view_id == "upload.chart.series":
        return {"points": [{"x": "2025-01-01", "y": 1.0}], "sampled": False}
    if view_id == "upload.chart.decomposition_shares":
        return {"trend_pct": 60.0, "seasonal_pct": 30.0, "cyclical_pct": None,
                "resid_pct": 10.0, "applicable": True, "reason": None}
    if view_id == "upload.chart.decomposition_series":
        return {"points": [{"x": "2025-01-01", "trend": 1.0, "seasonal": 0.0,
                            "resid": 0.0}], "method": "STL", "sampled": False}
    if view_id == "upload.distribution.scatter":
        return {"scatter": [{"x": 1.0, "y": 2.0}], "scatter_sampled": False}
    if view_id == "upload.distribution.histogram":
        return {"histogram": [{"bin": 0, "count": 3}]}
    if view_id == "upload.distribution.kde":
        return {"kde": [{"x": 1.0, "density": 0.4}]}
    if view_id == "upload.structure.schema":
        return {"date_col": "date", "entity_col": None, "frequency": "MS"}
    if view_id == "validation.formats.chart":
        return {"checks": {"formats": {"status": "passed", "count": 0,
                                       "scope": "dataset", "items": []}}}
    if view_id == "validation.data_types.matrix":
        return {"checks": {"data_types": {"status": "passed", "count": 0,
                                          "scope": "dataset", "rule_source": "default",
                                          "mode": "auto", "error": None,
                                          "items": []}}}
    if view_id.startswith("validation.") and view_id.endswith(".overview"):
        check_id = view_id.removeprefix("validation.").removesuffix(".overview")
        return {"checks": {check_id: {"status": "passed", "count": 0,
                                      "scope": "dataset", "rule_source": "default",
                                      "mode": "auto", "error": None,
                                      "items": []}}}
    if view_id == "preprocessing.missing.overview":
        return {"total_rows": 9, "total_columns": 2, "total_missing": 0,
                "missing_rate_pct": 0.0, "rows_with_missing": 0,
                "rows_with_missing_pct": 0.0, "empty_rows": 0,
                "columns": [], "row_histogram": []}
    if view_id == "preprocessing.missing.coverage_matrix":
        return {"columns": ["value"], "bins": ["1–9"],
                "rows_per_bin": 9, "total_rows": 9}
    if view_id == "preprocessing.missing.correlation":
        return {"columns": ["value"], "matrix": [[1.0]]}
    if view_id == "preprocessing.outliers.overview":
        return {"total_rows": 9, "total_numeric_columns": 1,
                "total_outliers": 0, "outlier_rate_pct": 0.0,
                "affected_columns": 0, "columns": []}
    if view_id == "preprocessing.outliers.series_profile":
        return {"points": [{"x": "2025-01-01", "y": 1.0}],
                "bounds": {"value": {"lower": -1.0, "upper": 1.0}},
                "sampled": False}
    if view_id == "preprocessing.smoothing.overview":
        return {"profile": {"applicable": True, "reason": None,
                            "selected_method": "moving_average",
                            "selected_parameters": {"window": 3},
                            "needs_smoothing": False,
                            "diagnostics_before": {}, "diagnostics_after": {},
                            "points": [{"x": "2025-01-01", "original": 1.0,
                                        "smoothed": 1.0}]}}
    raise AssertionError(f"нет честной формы для {view_id}")


# ══════════════════════════════════════════════════════════════════════
# 3. Сборка VisualPrintSnapshot/1 (PGV-01-контракт; screen_svg -- §4.1)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotBuilder:
    def _build(self, view_id="upload.overview.tech_table", **kwargs):
        from apps.api.visual_exports import build_visual_print_snapshot

        _seed_run()
        artifact = _freeze_visual_result(view_id, **kwargs.pop("freeze_kwargs", {}))
        result_payload = _payload_of(artifact)
        return build_visual_print_snapshot(
            RUN_ID,
            site_view_id=view_id,
            result_artifact=artifact,
            result_payload=result_payload,
            profile_id=kwargs.pop("profile_id", "figure-landscape"),
            screen_svg=kwargs.pop("screen_svg", None),
            expected_context_id=kwargs.pop("expected_context_id", CONTEXT_ID),
            expected_data_revision=kwargs.pop(
                "expected_data_revision", DATA_REVISION
            ),
            date_column=kwargs.pop("date_column", "date"),
            render_requested_at="2026-10-30T09:05:00Z",
        ), artifact

    def test_snapshot_passes_pgv01_validation_table_view(self):
        from apps.api.print_schema import validate_print_snapshot

        snapshot, _artifact = self._build()
        violations = validate_print_snapshot(snapshot)
        assert not violations, f"{violations}"

    def test_snapshot_research_refs_and_expected_context(self):
        snapshot, _artifact = self._build()
        assert snapshot["scope"] == "research"
        assert snapshot["refs"]["context_id"] == CONTEXT_ID
        assert str(snapshot["refs"]["data_revision"]) == str(DATA_REVISION)
        assert snapshot["expected_context"]["context_id"] == CONTEXT_ID

    def test_snapshot_display_sections_table_headings(self):
        snapshot, _artifact = self._build("upload.overview.tech_table")
        sections = snapshot["display"]["sections"]
        assert len(sections) == 1
        assert sections[0]["renderer_kind"] == "html_table"
        assert sections[0]["table_headings"]["row"]
        assert sections[0]["table_headings"]["column"]

    def test_chart_view_requires_screen_svg_honest(self):
        """recharts_svg-секция без frozen геометрии -- честный отказ
        сборки (§3.6: график не фабрикуется; renderer без svg дал бы
        заглушку -- preflight ловит ДО постановки job'а)."""
        import pytest

        from apps.api.visual_exports import PrintScreenSvgRequired

        with pytest.raises(PrintScreenSvgRequired):
            self._build("upload.chart.series")

    def test_chart_snapshot_with_screen_svg_passes_validation(self):
        from apps.api.print_schema import validate_print_snapshot

        svg = "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'></svg>"
        snapshot, _artifact = self._build(
            "upload.chart.series",
            freeze_kwargs={"data": {"series": [{"x": "2025-01-01", "y": 1.0}]},
                           "kind": "recharts_svg",
                           "sampling": {"applicable": True, "mode": "full",
                                        "point_cap": None, "reason": None}},
            screen_svg=svg,
        )
        violations = validate_print_snapshot(snapshot)
        assert not violations, f"{violations}"
        section = snapshot["display"]["sections"][0]
        assert section["screen_svg"] == svg
        assert section["screen_svg_sha256"] == hashlib.sha256(svg.encode()).hexdigest()

    def test_mixed_view_composition_sections(self):
        from apps.api.print_schema import validate_print_snapshot

        svg = "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'></svg>"
        snapshot, _artifact = self._build(
            "preprocessing.stationarity.overview",
            freeze_kwargs={
                "data": {
                    "series": [{"x": "2025-01-01", "original": 1.0,
                                "transformed": 0.5}],
                    "tests": [{"test": "ADF(c)", "before_p_value": 0.4,
                               "after_p_value": 0.01}],
                    "columns": ["test", "p до", "p после"],
                    "rows": [{"test": "ADF(c)", "p до": 0.4, "p после": 0.01}],
                },
                "kind": "recharts_svg",
                "units": [{"value": None, "reason": "legacy_unknown"}],
            },
            screen_svg=svg,
        )
        violations = validate_print_snapshot(snapshot)
        assert not violations, f"{violations}"
        kinds = [s["renderer_kind"] for s in snapshot["display"]["sections"]]
        assert kinds == ["recharts_svg", "html_table"]

    def test_heatmap_scale_domain_from_frozen_data(self):
        from apps.api.print_schema import validate_print_snapshot

        snapshot, _artifact = self._build(
            "preprocessing.missing.coverage_matrix",
            freeze_kwargs={
                "data": {
                    "columns": ["value"],
                    "bins": [],
                    "row_headings": ["Строки 1–5", "Строки 6–9"],
                    "column_headings": ["value"],
                    "cells": [[12.5], [87.5]],
                },
                "kind": "html_heatmap",
                "units": [{"value": "percent", "reason": None}],
            },
        )
        violations = validate_print_snapshot(snapshot)
        assert not violations, f"{violations}"
        scale = snapshot["display"]["sections"][0]["heatmap_scale"]
        assert scale["domain"] == [12.5, 87.5]

    def test_sampling_metadata_carried_from_result(self):
        """before/after/sampling: sampling frozen результата переносится
        в снапшот (AC08: скрытого detail upgrade нет)."""
        snapshot, _artifact = self._build(
            "upload.chart.series",
            freeze_kwargs={
                "data": {"series": [{"x": "2025-01-01", "y": 1.0}]},
                "kind": "recharts_svg",
                "sampling": {"applicable": True, "mode": "downsampled",
                             "point_cap": 600, "reason": None},
            },
            screen_svg="<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        )
        assert snapshot["sampling"]["mode"] == "downsampled"
        assert snapshot["sampling"]["point_cap"] == 600
        assert snapshot["display"]["detail_level"] == "sampling"

    def test_selection_values_are_allowlisted_by_construction(self):
        """§6 «allowlisted display selection»: снапшот несёт ТОЛЬКО ключи
        view_params реестра (вне-allowlist ключи frozen результата не
        переносятся в печать -- нарушение selection_not_allowlisted
        невозможно по построению)."""
        from apps.api.print_schema import validate_print_snapshot

        snapshot, _artifact = self._build(
            "upload.chart.series",
            freeze_kwargs={
                "data": {"series": [{"x": "2025-01-01", "y": 1.0}]},
                "kind": "recharts_svg",
                "selection": {"hacker_key": "x", "window": "full"},
            },
            screen_svg="<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        )
        assert "hacker_key" not in snapshot["selection"]["values"]
        assert "hacker_key" not in snapshot["method"]["parameters"]
        assert snapshot["selection"]["values"].get("window") == "full"
        codes = {v.code for v in validate_print_snapshot(snapshot)}
        assert "selection_not_allowlisted" not in codes


# ══════════════════════════════════════════════════════════════════════
# 4. Сервис экспорта: freeze -> snapshot -> V01 -> job (без науки)
# ══════════════════════════════════════════════════════════════════════


class TestRequestVisualExport:
    def test_export_from_durable_result_full_chain(self):
        """durable visual_result -> snapshot -> V01 revision -> queued
        PNG job (§10.2/§11); science не трогается (AC06)."""
        _seed_run()
        _freeze_visual_result()
        from apps.api.visual_exports import request_visual_export

        outcome = request_visual_export(
            RUN_ID,
            _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID,
            render_requested_at=_now(),
        )
        assert outcome["view_id"] == "upload.overview.tech_table"
        assert outcome["job"]["state"] in ("queued", "rendering")
        assert outcome["status_url"].startswith("/v1/documentation/jobs/")
        assert outcome["print_kind"] == "V01"
        assert outcome["snapshot_artifact_id"]
        assert outcome["result_artifact_id"]

    def test_export_job_renders_via_worker_with_fake_renderer(self):
        """Полный путь: queued job -> штатный document_render_worker
        run_once с fake-renderer'ом -> PNG rendition ready (контейнер
        PGV-08 недоступен в среде -- граница PGV-08; контракт жизни
        job'а проверен)."""
        _seed_run()
        _freeze_visual_result()
        from apps.api import document_jobs, document_render_worker
        from apps.api.visual_exports import request_visual_export

        outcome = request_visual_export(
            RUN_ID,
            _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID,
            render_requested_at=_now(),
        )
        job_id = outcome["job"]["job_id"]

        captured: dict = {}

        class _FakeClient:
            def render_page(self, payload, *, timeout_s=None):  # signature parity
                captured["request_id"] = payload["request_id"]
                captured["sections"] = payload["sections"]
                return b"\x89PNG\r\n\x1a\n" + b"0" * 64

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service,
            png_renderer=_FakeClient(),
        )
        worker.run_once()
        job = service.registry.get_job(job_id)
        assert job.state == "ready", f"job: {job.state} {job.error_code}"
        rendition = service.registry.get_rendition(job.rendition_id)
        assert rendition is not None and rendition.state == "ready"
        assert rendition.format == "png"
        assert captured["sections"][0]["kind"] == "html_table"

    def test_export_without_frozen_result_is_source_unavailable(self):
        import pytest

        _seed_run()
        from apps.api.visual_exports import (
            VisualSourceUnavailable,
            request_visual_export,
        )

        with pytest.raises(VisualSourceUnavailable):
            request_visual_export(
                RUN_ID,
                _owner_subject(),
                view_id="upload.overview.tech_table",
                session_id=SESSION_ID,
                render_requested_at=_now(),
            )

    def test_export_cas_context_change_conflicts(self):
        """Смена контекста между показом и экспортом -> 409
        context_changed, НИЧЕГО не регистрируется (PGV-AC07)."""
        import pytest

        _seed_run()
        _freeze_visual_result()
        from apps.api.visual_artifacts import PrintContextConflict
        from apps.api.visual_exports import request_visual_export

        with pytest.raises(PrintContextConflict):
            request_visual_export(
                RUN_ID,
                _owner_subject(),
                view_id="upload.overview.tech_table",
                session_id=SESSION_ID,
                expected_context_id="ctx-old",
                render_requested_at=_now(),
            )

    def test_export_idempotent_same_frozen_input_same_revision(self):
        """Повторный экспорт того же frozen input -- та же ревизия
        (§12.2 «повторный клик не создаёт дубли»); job -- прежний
        (AC09)."""
        _seed_run()
        _freeze_visual_result()
        from apps.api.visual_exports import request_visual_export

        first = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID, render_requested_at=_now(),
        )
        second = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID, render_requested_at=_now(),
        )
        assert second["print_revision_id"] == first["print_revision_id"]
        assert second["job"]["job_id"] == first["job"]["job_id"]

    def test_export_different_profile_creates_new_revision(self):
        """Иной профиль -- иная ревизия того же печатного документа
        (basis_fingerprint включает profile -- F-P2C3)."""
        _seed_run()
        _freeze_visual_result()
        from apps.api.visual_exports import request_visual_export

        first = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID, render_requested_at=_now(),
        )
        second = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID, profile_id="a4-portrait",
            render_requested_at=_now(),
        )
        assert second["print_revision_id"] != first["print_revision_id"]
        assert second["document_id"] == first["document_id"]

    def test_export_different_screen_svg_new_snapshot(self):
        """Иной frozen print input (другой screen_svg того же
        результата) -- НОВЫЙ immutable снапшот (§8 «старые snapshots
        не переписываются»; identity включает svg digest)."""
        _seed_run()
        _freeze_visual_result(
            "upload.chart.series",
            data={"series": [{"x": "2025-01-01", "y": 1.0}]},
            kind="recharts_svg",
            result_ref="vr-pgv10-chart-1",
        )
        from apps.api.visual_artifacts import list_visual_print_snapshots
        from apps.api.visual_exports import request_visual_export

        first = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.chart.series",
            session_id=SESSION_ID,
            screen_svg="<svg xmlns='http://www.w3.org/2000/svg' width='800'></svg>",
            render_requested_at=_now(),
        )
        second = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.chart.series",
            session_id=SESSION_ID,
            screen_svg="<svg xmlns='http://www.w3.org/2000/svg' width='1200'></svg>",
            render_requested_at=_now(),
        )
        assert second["snapshot_artifact_id"] != first["snapshot_artifact_id"]
        assert len(list_visual_print_snapshots(RUN_ID, view_id="upload.chart.series")) == 2

    def test_export_with_explicit_result_ref(self):
        _seed_run()
        _freeze_visual_result(result_ref="vr-explicit-1")
        _freeze_visual_result(result_ref="vr-explicit-2")
        from apps.api.visual_exports import request_visual_export

        outcome = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="upload.overview.tech_table",
            session_id=SESSION_ID,
            result_ref="vr-explicit-1",
            render_requested_at=_now(),
        )
        artifact = _payload_of(
            next(a for a in _visual_results()
                 if a.artifact_id == outcome["result_artifact_id"])
        )
        assert artifact["execution"]["result_ref"] == "vr-explicit-1"

    def test_foreign_run_is_uniform_denial(self):
        import pytest

        _seed_run()
        _freeze_visual_result()
        from apps.api.visual_exports import VisualExportAccessDenied
        from apps.api.visual_exports import request_visual_export

        with pytest.raises(VisualExportAccessDenied):
            request_visual_export(
                RUN_ID,
                SubjectRef.from_session("pgv10-foreign-cookie"),
                view_id="upload.overview.tech_table",
                session_id="pgv10-foreign-cookie",
                render_requested_at=_now(),
            )


# ══════════════════════════════════════════════════════════════════════
# 5. HTTP-маршруты §11 (visual-sources / visuals)
# ══════════════════════════════════════════════════════════════════════


class TestVisualExportHttp:
    def test_visual_sources_lists_scope_without_science(self):
        """GET visual-sources: объединённый скоуп 38 PGV-10 + 17 PGV-11
        = 55 view, frozen-факты, БЕЗ запуска науки (§11 «без запуска
        науки»; расширение списка -- поставка PGV-11)."""
        _seed_run()
        _freeze_visual_result()
        from tests.api.test_pgv10_visual_exports import _client_get_json

        body = _client_get_json(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources"
        )
        assert body["status"] == 200
        data = body["data"]
        assert data["run_id"] == RUN_ID
        ids = [source["view_id"] for source in data["sources"]]
        assert len(ids) == 55, "38 PGV-10 + 17 PGV-11 (EDA/tasks)"
        assert "upload.overview.tech_table" in ids
        source = next(s for s in data["sources"]
                      if s["view_id"] == "upload.overview.tech_table")
        assert source["export_ready"] is True
        assert source["latest_result"]["result_ref"]
        empty = next(s for s in data["sources"]
                     if s["view_id"] == "preprocessing.scaling.overview")
        assert empty["export_ready"] is False
        assert empty["latest_result"] is None

    def test_visual_sources_foreign_run_uniform_404(self):
        from tests.api.test_pgv10_visual_exports import _client_get_json

        body = _client_get_json(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources",
            cookies={"cisstat_session_id": "pgv10-foreign-cookie"},
        )
        assert body["status"] == 404

    def test_post_visuals_returns_202_and_status_url(self):
        _seed_run()
        _freeze_visual_result()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.overview.tech_table"},
        )
        assert body["status"] == 202
        assert body["data"]["job"]["state"] in ("queued", "rendering")
        assert body["data"]["status_url"].startswith("/v1/documentation/jobs/")

    def test_post_visuals_unknown_view_422(self):
        _seed_run()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.chart.nonexistent"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "unknown_view"

    def test_post_visuals_out_of_scope_422_with_task_hint(self):
        _seed_run()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.passport.panel"},
        )
        assert body["status"] == 422
        assert "PGV-04" in body["data"]["message"]

    def test_post_visuals_chart_without_svg_422(self):
        _seed_run()
        _freeze_visual_result(
            "upload.chart.series",
            data={"series": [{"x": "2025-01-01", "y": 1.0}]},
            kind="recharts_svg",
            result_ref="vr-pgv10-chart-2",
        )
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.chart.series"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "screen_svg_required"

    def test_post_visuals_invalid_screen_svg_422(self):
        _seed_run()
        _freeze_visual_result(
            "upload.chart.series",
            data={"series": [{"x": "2025-01-01", "y": 1.0}]},
            kind="recharts_svg",
            result_ref="vr-pgv10-chart-3",
        )
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.chart.series",
             "screen_svg": "<script>alert(1)</script>"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "invalid_screen_svg"

    def test_post_visuals_invalid_profile_422(self):
        _seed_run()
        _freeze_visual_result()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.overview.tech_table", "profile_id": "wallpaper"},
        )
        assert body["status"] == 422
        assert body["data"]["code"] == "invalid_profile"

    def test_post_visuals_cas_conflict_409(self):
        _seed_run()
        _freeze_visual_result()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.overview.tech_table",
             "expected_context_id": "ctx-old"},
        )
        assert body["status"] == 409
        assert body["data"]["code"] == "context_changed"

    def test_post_visuals_source_unavailable_409(self):
        _seed_run()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.overview.tech_table"},
        )
        assert body["status"] == 409
        assert body["data"]["code"] == "source_unavailable"

    def test_post_visuals_foreign_run_404(self):
        _seed_run()
        from tests.api.test_pgv10_visual_exports import _client_post_json

        body = _client_post_json(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            {"view_id": "upload.overview.tech_table"},
            cookies={"cisstat_session_id": "pgv10-foreign-cookie"},
        )
        assert body["status"] == 404


# ══════════════════════════════════════════════════════════════════════
# 6. Мост контента: секции по своему renderer_kind из frozen data
# ══════════════════════════════════════════════════════════════════════


class TestRenderPayloadBridge:
    def test_mixed_sections_built_from_same_frozen_data(self):
        """mixed-сайт: chart-секция из screen_svg снапшота, table-секция
        из {columns, rows} frozen data -- обе секции получают контент
        (§6: producer несёт print input; паритет render_payload/1)."""
        from apps.api.print_render_payload import (
            build_render_payload,
            section_content_from_visual_result,
        )

        svg = "<svg xmlns='http://www.w3.org/2000/svg' width='800'></svg>"
        snapshot = {
            "schema_version": "pgv.visual_print_snapshot/1",
            "display": {
                "sections": [
                    {"section_id": "chart", "renderer_kind": "recharts_svg",
                     "screen_svg": svg},
                    {"section_id": "table", "renderer_kind": "html_table",
                     "table_headings": {"row": ["Тест", "p до", "p после"],
                                        "column": ["Значение"]}},
                ]
            },
        }
        result = {
            "payload": {
                "kind": "recharts_svg",
                "data": {
                    "series": [{"x": "2025-01-01", "original": 1.0}],
                    "columns": ["test", "p до", "p после"],
                    "rows": [{"test": "ADF(c)", "p до": 0.4, "p после": 0.01}],
                },
            }
        }
        content = section_content_from_visual_result(snapshot, result)
        assert content["chart"]["svg_xml"] == svg
        assert content["table"]["rows"][0][0] == "ADF(c)"
        payload = build_render_payload(
            snapshot, content, request_id="pgv:job-bridge"
        )
        kinds = [s["kind"] for s in payload["sections"]]
        assert kinds == ["recharts_svg", "html_table"]

    def test_screen_svg_from_snapshot_wins_over_data(self):
        from apps.api.print_render_payload import section_content_from_visual_result

        snapshot = {
            "schema_version": "pgv.visual_print_snapshot/1",
            "display": {
                "sections": [
                    {"section_id": "s", "renderer_kind": "recharts_svg",
                     "screen_svg": "<svg id='frozen'></svg>"},
                ]
            },
        }
        result = {"payload": {"kind": "recharts_svg",
                              "data": {"svg_xml": "<svg id='legacy'></svg>"}}}
        content = section_content_from_visual_result(snapshot, result)
        assert content["s"]["svg_xml"] == "<svg id='frozen'></svg>"

    def test_missing_form_is_honest_incomplete(self):
        import pytest

        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            section_content_from_visual_result,
        )

        snapshot = {
            "schema_version": "pgv.visual_print_snapshot/1",
            "display": {
                "sections": [
                    {"section_id": "t", "renderer_kind": "html_table",
                     "table_headings": {"row": ["A"], "column": ["B"]}},
                ]
            },
        }
        result = {"payload": {"kind": "html_table", "data": {"series": []}}}
        with pytest.raises(PrintRenderPayloadIncomplete):
            section_content_from_visual_result(snapshot, result)


# ══════════════════════════════════════════════════════════════════════
# 7. HTTP-хелперы (TestClient с честными статусами)
# ══════════════════════════════════════════════════════════════════════


def _client_get_json(path: str, cookies: dict | None = None) -> dict:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        # cookies задаются на экземпляре (per-request cookies в
        # TestClient устарели и передаются ненадёжно).
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
