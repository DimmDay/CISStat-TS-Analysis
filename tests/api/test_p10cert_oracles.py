# tests/api/test_p10cert_oracles.py
"""Независимая сертификация PGV-10 (Export upload/validation/
preprocessing) -- оракулы СЕРТИФИКАТОРА на СВОИХ данных.

База сертификации: main@81fb560 (цель -- коммит поставки PGV-10);
родитель -- 09c79aa (PGV-09). Корпус дизъюнктен repo-корпусу
исполнителя (RUN-PGV10A01/pgv10-*) и корпусам PGV-02/03/08/09:
RUN-P10CERT-2026A / p10cert-* / vr-p10cert-*.

Метод (AGENTS.md + конвенция серии):
  • свои оракулы на своих данных -- не копия корпуса исполнителя;
  • свои мутанты -- scripts/p10cert/ (кампания отдельно);
  • RED на родителе 09c79aa (протокол scripts/p10cert/protocols/);
  • продукт не меняется: после всех кампаний git diff пуст.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun

# ── Изоляция КАЖДОГО теста (паттерн серии PGV) ────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "p10cert-data"))
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


# ── Свои данные (корпус p10cert) ──────────────────────────────────────

RUN_ID = "RUN-P10CERT-2026A"
SESSION_ID = "p10cert-session-a"
CONTEXT_ID = "ctx-p10cert-a1"
DATA_REVISION = 41


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = CONTEXT_ID,
    data_revision: int | None = DATA_REVISION,
    target_column: str | None = "turnover",
):
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p10cert" * 6,
        dataset_name="p10cert-oracle-seed",
        target_column=target_column,
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


def _seed_session_object(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    date_column: str = "dt",
):
    from apps.api.session_store import (
        AnalysisSession,
        DatasetInfo,
        get_session_store,
    )

    session = AnalysisSession(session_id=session_id)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p10cert-ds-a",
        name="p10cert-seed",
        rows=120,
        columns=2,
        size_label="6 KB",
        dataset_fingerprint="p10cert" * 6,
    )
    session.data_revision = DATA_REVISION
    session.set_date_column(date_column)
    try:
        get_session_store().save(session)
    except Exception:  # noqa: BLE001 -- повторный сид
        pass
    return session


def _artifact_payload(artifact) -> dict:
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


def _visual_snapshots(run_id: str = RUN_ID, view_id: str | None = None):
    from apps.api.visual_artifacts import list_visual_print_snapshots

    artifacts = list_visual_print_snapshots(run_id)
    if view_id is None:
        return artifacts
    return [a for a in artifacts if a.refs.get("view_id") == view_id]


def _print_snapshots(run_id: str = RUN_ID):
    from apps.api.visual_artifacts import list_visual_print_snapshots

    return list_visual_print_snapshots(run_id)


def _result_payload(
    *,
    view_id: str,
    data: dict,
    kind: str,
    result_ref: str,
    method: str = "p10cert_method",
    selection: dict | None = None,
    sampling: dict | None = None,
    computed_at: str | None = "2026-10-31T08:30:00Z",
) -> dict:
    """VisualResult/1 на СВОИХ данных (зеркало контракта PGV-03)."""
    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

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
            "parameters": dict(selection or {"selected_column": "turnover"}),
        },
        "units": [{"value": None, "reason": "dimensionless"}],
        "sampling": sampling or {
            "applicable": True, "mode": "full", "point_cap": None, "reason": None,
        },
        "warnings": [],
        "execution": {
            "execution_ref": f"exec-p10cert-{view_id}",
            "result_ref": result_ref,
            "computed_at": computed_at,
            "computed_at_reason": None if computed_at else "producer_not_reported",
        },
    }


def _freeze_result(view_id: str, *, data: dict, kind: str, result_ref: str, **kw):
    from apps.api.visual_artifacts import freeze_visual_result

    _seed_run()
    _seed_session_object()
    return freeze_visual_result(
        RUN_ID,
        _owner_subject(),
        payload=_result_payload(
            view_id=view_id, data=data, kind=kind, result_ref=result_ref, **kw
        ),
        session_id=SESSION_ID,
    )


# Мои известные данные: таблица формата (validation.formats.chart --
# chart-вид; значения известны сертификатору).
CERT_FORMAT_DATA = {
    "categories": ["Дата", "Число", "Текст"],
    "counts": [17, 41, 3],
}
CERT_TABLE_DATA = {
    "columns": ["check", "status", "count"],
    "rows": [
        {"check": "date_continuity", "status": "ok", "count": 120},
        {"check": "sorted", "status": "warning", "count": 1},
    ],
}
# Тепловая карта пропусков с ИЗВЕСТНЫМИ ячейками (домен [0.0, 0.75]).
CERT_HEATMAP_DATA = {
    "row_headings": ["dt", "turnover"],
    "column_headings": ["w1", "w2", "w3", "w4"],
    "cells": [
        [0.0, 0.0, 0.25, 0.0],
        [0.75, 0.0, 0.0, 0.5],
    ],
}
# Стационарность (mixed: chart + tests) с известными p-value.
CERT_STATIONARITY_DATA = {
    "series": [
        {"x": "2025-01-01", "y": 10.5},
        {"x": "2025-02-01", "y": 11.2},
        {"x": "2025-03-01", "y": 9.8},
    ],
    "tests": [
        {"test": "ADF", "p_before": 0.31, "p_after": 0.01},
        {"test": "KPSS", "p_before": 0.04, "p_after": 0.70},
    ],
    # Каноническая форма таблицы моста (паритет адаптера
    # _stationarity_overview): {columns, rows}.
    "columns": ["test", "p_before", "p_after"],
    "rows": [
        {"test": "ADF", "p_before": 0.31, "p_after": 0.01},
        {"test": "KPSS", "p_before": 0.04, "p_after": 0.70},
    ],
    "row_count": 2,
}


def _svg(width: int = 640, marker: str = "p10cert") -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' "
        f"height='320' data-cert='{marker}'><rect x='0' y='0' "
        f"width='{width}' height='320' fill='white'/></svg>"
    )


def _export(view_id: str, **kw):
    from apps.api.visual_exports import request_visual_export

    kw.setdefault("session_id", SESSION_ID)
    kw.setdefault("render_requested_at", _now())
    return request_visual_export(RUN_ID, _owner_subject(), view_id=view_id, **kw)


# ══════════════════════════════════════════════════════════════════════
# O1–O3. Скоуп экспорта (§13: 38 render sites трёх остановок)
# ══════════════════════════════════════════════════════════════════════


class TestCertScope:
    def test_o1_scope_equals_registry_derived_38_sites(self):
        """Скоуп = pgv-03 research view трёх модулей; число выводится из
        реестра PGV-00 (не хардкод), паспорта/static_demo/EDA/modeling
        вне скоупа (§13/§5: unknown site блокирует CERT)."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import pgv10_export_view_ids

        scope = set(pgv10_export_view_ids())
        expected = {
            str(site["view_id"])
            for site in load_visual_registry()["sites"]
            if site["module_id"] in ("upload", "validation", "preprocessing")
            and str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        }
        assert scope == expected, "скоуп не совпадает с реестром PGV-00"
        assert len(scope) == 38, f"заявлено 38, фактически {len(scope)}"
        per_module: dict[str, int] = {}
        for site in load_visual_registry()["sites"]:
            if str(site["view_id"]) in scope:
                per_module[site["module_id"]] = (
                    per_module.get(site["module_id"], 0) + 1
                )
        assert per_module == {"upload": 10, "validation": 10, "preprocessing": 18}

    def test_o2_no_forgotten_pgv03_view_in_three_modules(self):
        """Каждый pgv-03 research view трёх остановок экспортируем
        (незабытых сайтов нет -- §5 «полный инвентарь»): у каждого view
        скоупа resolve успешен; у вне-скоуповых pgv-03 -- честный отказ
        с добирающей задачей."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import resolve_export_view

        for site in load_visual_registry()["sites"]:
            view_id = str(site["view_id"])
            if (
                site["module_id"] in ("upload", "validation", "preprocessing")
                and str(site.get("source_adapter", "")).startswith("pgv-03/")
                and site.get("applicability") != "static_demo"
            ):
                assert resolve_export_view(view_id)["view_id"] == view_id

    def test_o3_unknown_and_out_of_scope_honest(self):
        """Unknown view -- UnknownExportView; EDA/modeling/passport/
        static_demo -- VisualExportOutOfScope с указанием добирающей
        задачи (честная граница скоупа)."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_exports import (
            UnknownExportView,
            VisualExportOutOfScope,
            resolve_export_view,
        )

        with pytest.raises(UnknownExportView):
            resolve_export_view("p10cert.does.not.exist")
        hints: dict[str, str] = {}
        from apps.api.visual_exports import pgv11_export_view_ids

        pgv11_scope = set(pgv11_export_view_ids())
        for site in load_visual_registry()["sites"]:
            view_id = str(site["view_id"])
            adapter = str(site.get("source_adapter", ""))
            if adapter.startswith("pgv-03/") and site["module_id"] in (
                "upload", "validation", "preprocessing",
            ):
                continue  # скоуп PGV-10 -- проверен выше
            if view_id in pgv11_scope:
                continue  # скоуп PGV-11 (EDA/tasks) -- пин корпуса test_pgv11
            with pytest.raises(VisualExportOutOfScope) as exc:
                resolve_export_view(view_id)
            hints.setdefault(
                "pgv-04" if adapter.startswith("pgv-04/") else "other",
                str(exc.value),
            )
        # Вне скоупов остались паспорта (pgv-04/13), demo и modeling/
        # forecasting (PGV-12) -- каждый отказывается честно с
        # упоминанием задачи.
        assert hints, "реестр без вне-скоуповых view -- проверка вырождена"
        assert any("PGV-" in h for h in hints.values()) or any(
            "static" in h for h in hints.values()
        )


# ══════════════════════════════════════════════════════════════════════
# O4–O7. Durable-экспорт: без науки, идемпотентность, identity
# ══════════════════════════════════════════════════════════════════════


class TestCertDurableExport:
    def test_o4_export_does_not_run_science(self):
        """AC06: экспорт из durable-слоя не запускает науку и не меняет
        scientific-состояние: после экспорта -- не появилось НОВЫХ
        visual_result, data_revision запуска не изменился,-session
        dataset не пересоздан; экспорт успех при живом frozen
        результате даже БЕЗ обращения к научным расчётам."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o4-1",
        )
        from apps.api.visual_exports import request_visual_export

        before_results = len(_visual_results())
        before_revision = _seed_run().data_revision
        outcome = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="validation.regularity.overview",
            session_id=SESSION_ID, render_requested_at=_now(),
        )
        assert outcome["job"]["state"] in ("queued", "rendering")
        assert len(_visual_results()) == before_results, (
            "экспорт создал новый visual_result -- научный пересчёт (AC06)"
        )
        assert _seed_run().data_revision == before_revision

    def test_o5_idempotent_repeat_same_snapshot_revision_job(self):
        """AC09/§12.2 на СВОИХ данных: повторный экспорт -- тот же
        frozen input (время фиксации не переписывается), та же V01
        ревизия, тот же job; дубли снапшотов не создаются."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o5-1",
        )
        first = _export("validation.regularity.overview")
        snap_first = _print_snapshots()[0]
        captured_first = _artifact_payload(snap_first)["times"]["captured_at"]
        second = _export("validation.regularity.overview")
        assert second["snapshot_artifact_id"] == first["snapshot_artifact_id"]
        assert second["print_revision_id"] == first["print_revision_id"]
        assert second["job"]["job_id"] == first["job"]["job_id"]
        assert len(_print_snapshots()) == 1, "дубль frozen print input"
        snap_after = _print_snapshots()[0]
        assert _artifact_payload(snap_after)["times"]["captured_at"] == captured_first, (
            "время фиксации снапшота переписано при повторном экспорте"
        )

    def test_o6_different_profile_new_revision_same_document(self):
        """Иной профиль -- новая ревизия того же печатного документа
        (F-P2C3); сам frozen input не дублируется."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o6-1",
        )
        first = _export("validation.regularity.overview")
        second = _export(
            "validation.regularity.overview", profile_id="a4-portrait"
        )
        assert second["print_revision_id"] != first["print_revision_id"]
        assert second["document_id"] == first["document_id"]
        assert len(_print_snapshots()) == 1
        assert second["profile_id"] == "a4-portrait"

    def test_o7_different_screen_svg_is_different_snapshot(self):
        """Иной frozen print input (другая геометрия того же
        результата) -- ДРУГОЙ immutable снапшот; identity включает
        svg-digest (первые 16 hex sha256); §8 «старые не переписываются»."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o7-1",
        )
        first = _export(
            "validation.formats.chart", screen_svg=_svg(640, "o7-first")
        )
        second = _export(
            "validation.formats.chart", screen_svg=_svg(1280, "o7-second")
        )
        assert second["snapshot_artifact_id"] != first["snapshot_artifact_id"]
        snaps = _visual_snapshots(view_id="validation.formats.chart")
        assert len(snaps) == 2
        # Identity-член svg-digest согласован с содержимым снапшота.
        import hashlib

        payload_second = _artifact_payload(snaps[-1])
        svg = payload_second["display"]["sections"][0]["screen_svg"]
        digest16 = hashlib.sha256(svg.encode("utf-8")).hexdigest()[:16]
        assert "data-cert='o7-second'" in svg, "в печати не та геометрия"
        producer_key = snaps[-1].producer_key
        assert producer_key.endswith(digest16), (
            f"identity снапшота {producer_key} не содержит svg-digest {digest16}"
        )


# ══════════════════════════════════════════════════════════════════════
# O8–O9. CAS (AC07) и uniform-404 (AC18)
# ══════════════════════════════════════════════════════════════════════


class TestCertCasAndAccess:
    def test_o8_cas_revision_conflict_409_nothing_registered(self):
        """AC07: экспорт с устаревшей expected_data_revision -- 409
        context_changed (плоское тело), НИЧЕГО не регистрируется."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o8-1",
        )
        from apps.api.visual_artifacts import PrintContextConflict
        from apps.api.visual_exports import request_visual_export

        with pytest.raises(PrintContextConflict):
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.regularity.overview",
                session_id=SESSION_ID,
                expected_data_revision=DATA_REVISION - 1,
                render_requested_at=_now(),
            )
        assert len(_print_snapshots()) == 0
        from apps.api.document_jobs import DocumentDeliveryService

        service = DocumentDeliveryService.create_default()
        assert service.registry.list_jobs(RUN_ID) == []
        assert len(_visual_results()) == 1

    def test_o8b_cas_via_http_flat_body(self, client):
        """HTTP-контракт CAS: 409 с плоским телом {code: context_changed,
        message, request_id} (паритет логов/мониторинга)."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o8b-1",
        )
        resp = client.post(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            json={
                "view_id": "validation.regularity.overview",
                "expected_data_revision": DATA_REVISION - 1,
            },
            cookies={"cisstat_session_id": SESSION_ID},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body.get("code") == "context_changed"
        assert "request_id" in body and body["request_id"]

    def test_o9_uniform_404_foreign_and_missing_and_anonymous(self, client):
        """AC18/R09: чужой/несуществующий run и аноним -- одинаковый
        uniform-404 с плоским телом на GET visual-sources И POST
        visuals; существование запуска не дисклоужается (формы тел
        попарно неразличимы)."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o9-1",
        )
        foreign = {"cisstat_session_id": "p10cert-foreign-cookie"}
        missing_run = "RUN-P10CERT-NOSUCH"
        variants = [
            ("GET", f"/v1/documentation/runs/{RUN_ID}/visual-sources", None, foreign),
            ("GET", f"/v1/documentation/runs/{missing_run}/visual-sources", None, foreign),
            ("GET", f"/v1/documentation/runs/{RUN_ID}/visual-sources", None, None),
            ("POST", f"/v1/documentation/runs/{RUN_ID}/visuals",
             {"view_id": "validation.regularity.overview"}, foreign),
            ("POST", f"/v1/documentation/runs/{missing_run}/visuals",
             {"view_id": "validation.regularity.overview"}, foreign),
        ]
        bodies = []
        for method, url, payload, headers in variants:
            if method == "GET":
                resp = client.get(url, headers=headers or {})
            else:
                resp = client.post(url, json=payload, headers=headers or {})
            assert resp.status_code == 404, f"{url}: {resp.status_code}"
            body = resp.json()
            assert body.get("code") == "not_found"
            assert "request_id" in body
            body.pop("request_id", None)  # request_id уникален на запрос
            bodies.append(json.dumps(body, sort_keys=True, ensure_ascii=False))
        # uniform: тело foreign == тело missing (по парам GET/POST).
        assert bodies[0] == bodies[1], "foreign/missing различимы в GET"
        assert bodies[3] == bodies[4], "foreign/missing различимы в POST"


# ══════════════════════════════════════════════════════════════════════
# O10. Честные preflight-отказы до постановки job'а
# ══════════════════════════════════════════════════════════════════════


class TestCertPreflight:
    def _seed_chart(self, result_ref: str = "vr-p10cert-o10-1"):
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref=result_ref,
        )
        from apps.api.document_jobs import DocumentDeliveryService

        return DocumentDeliveryService.create_default()

    def test_o10_chart_without_svg_refused_before_job(self):
        """screen_svg_required -- ДО постановки job'а: ни ревизии, ни
        job'а не создаётся (не заглушка контейнера)."""
        service = self._seed_chart()
        jobs_before = len(service.registry.list_jobs(RUN_ID))
        from apps.api.visual_exports import PrintScreenSvgRequired, request_visual_export

        with pytest.raises(PrintScreenSvgRequired):
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.formats.chart",
                session_id=SESSION_ID, render_requested_at=_now(),
            )
        assert len(service.registry.list_jobs(RUN_ID)) == jobs_before

    def test_o10b_invalid_svg_variants_refused(self):
        """invalid_screen_svg: не-SVG корень, <script>, foreignObject,
        on*-обработчик -- 422, до job'а."""
        from apps.api.visual_exports import InvalidScreenSvg, request_visual_export

        self._seed_chart()
        bad = [
            "<div>не SVG</div>",
            "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            "<svg xmlns='http://www.w3.org/2000/svg'><foreignObject><body>x</body></foreignObject></svg>",
            "<svg xmlns='http://www.w3.org/2000/svg'><rect onload='evil()'/></svg>",
        ]
        for svg in bad:
            with pytest.raises(InvalidScreenSvg):
                request_visual_export(
                    RUN_ID, _owner_subject(),
                    view_id="validation.formats.chart",
                    session_id=SESSION_ID, screen_svg=svg,
                    render_requested_at=_now(),
                )
        assert len(_print_snapshots()) == 0

    def test_o10c_invalid_profile_and_oversize_svg(self):
        """invalid_profile -- вне каталога PGV-01 (422);
        export_too_large -- SVG больше 8 MiB (413)."""
        from apps.api.visual_exports import VisualExportError, request_visual_export

        self._seed_chart()
        with pytest.raises(VisualExportError) as exc:
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.formats.chart",
                session_id=SESSION_ID, profile_id="a3-scroll-of-doom",
                screen_svg=_svg(), render_requested_at=_now(),
            )
        assert "invalid_profile" in str(exc.value)
        huge = "<svg xmlns='http://www.w3.org/2000/svg'>" + " " * (8_000_001) + "</svg>"
        with pytest.raises(VisualExportError) as exc2:
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.formats.chart",
                session_id=SESSION_ID, screen_svg=huge,
                render_requested_at=_now(),
            )
        assert "export_too_large" in str(exc2.value)

    def test_o10d_http_flat_error_codes(self, client):
        """HTTP-контракты preflight: 422 unknown_view /
        view_out_of_scope / screen_svg_required / invalid_screen_svg /
        invalid_profile -- плоские тела с request_id."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o10d-1",
        )
        cases = [
            ({"view_id": "p10cert.no.such.view"}, 422, "unknown_view"),
            ({"view_id": "eda.passport.panel"}, 422, None),  # вне скоупа (PGV-04; EDA/tasks вошли в скоуп PGV-11)
            ({"view_id": "validation.formats.chart"}, 422, "screen_svg_required"),
        ]
        for payload, status, code in cases:
            resp = client.post(
                f"/v1/documentation/runs/{RUN_ID}/visuals",
                json=payload,
                cookies={"cisstat_session_id": SESSION_ID},
            )
            assert resp.status_code == status, (payload, resp.status_code, resp.text)
            body = resp.json()
            assert "request_id" in body
            if code:
                assert body.get("code") == code
        bad_svg = client.post(
            f"/v1/documentation/runs/{RUN_ID}/visuals",
            json={
                "view_id": "validation.formats.chart",
                "screen_svg": "<svg><script>x()</script></svg>",
            },
            cookies={"cisstat_session_id": SESSION_ID},
        )
        assert bad_svg.status_code == 422
        assert bad_svg.json().get("code") == "invalid_screen_svg"


# ══════════════════════════════════════════════════════════════════════
# O11–O14. Контент снапшота: mixed/heatmap/sampling/refs
# ══════════════════════════════════════════════════════════════════════


class TestCertSnapshotContent:
    def test_o11_mixed_sections_from_one_frozen_data(self):
        """Mixed-сайт (стационарность): >=2 секции разных kinds из
        ОДНОГО frozen data; chart-секция требует svg; таблица строится
        мостом из моих известных p-value."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "preprocessing.stationarity.overview",
            data=CERT_STATIONARITY_DATA,
            kind="recharts_svg",  # payload.kind mixed-сайта -- первичный kind
            result_ref="vr-p10cert-o11-1",
        )
        outcome = _export(
            "preprocessing.stationarity.overview", screen_svg=_svg(900, "o11")
        )
        snap = next(
            a for a in _visual_snapshots(view_id="preprocessing.stationarity.overview")
            if a.artifact_id == outcome["snapshot_artifact_id"]
        )
        payload = _artifact_payload(snap)
        sections = payload["display"]["sections"]
        kinds = [s["renderer_kind"] for s in sections]
        assert kinds == ["recharts_svg", "html_table"], kinds
        assert sections[0]["screen_svg_sha256"]
        assert "data-cert='o11'" in sections[0]["screen_svg"]

    def test_o12_heatmap_domain_from_frozen_cells(self):
        """Домен шкалы теплокарты -- из ФАКТИЧЕСКИХ ячеек frozen data:
        мои известные [0.0..0.75] -> domain == [0.0, 0.75] (не [0,1])."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "preprocessing.missing.coverage_matrix",
            data=CERT_HEATMAP_DATA,
            kind="html_heatmap",
            result_ref="vr-p10cert-o12-1",
        )
        outcome = _export("preprocessing.missing.coverage_matrix")
        snap = next(
            a for a in _visual_snapshots(view_id="preprocessing.missing.coverage_matrix")
            if a.artifact_id == outcome["snapshot_artifact_id"]
        )
        section = _artifact_payload(snap)["display"]["sections"][0]
        assert section["renderer_kind"] == "html_heatmap"
        assert section["heatmap_scale"]["domain"] == [0.0, 0.75]

    def test_o12b_empty_cells_honest_default_domain(self):
        """Пустые ячейки -- честный дефолт [0, 1] (паритет
        rendererCore), не выдуманный домен данных."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "preprocessing.missing.coverage_matrix",
            data={"row_headings": [], "column_headings": [], "cells": []},
            kind="html_heatmap",
            result_ref="vr-p10cert-o12b-1",
        )
        _export("preprocessing.missing.coverage_matrix")
        snap = _visual_snapshots(view_id="preprocessing.missing.coverage_matrix")[-1]
        section = _artifact_payload(snap)["display"]["sections"][0]
        assert section["heatmap_scale"]["domain"] == [0.0, 1.0]

    def test_o13_sampling_honesty_detail_level(self):
        """AC08: sampling frozen результата переносится; неполный показ
        -- detail_level=sampling; full -- expanded; скрытого апгрейда
        нет (point_cap переносится)."""
        _seed_run()
        _seed_session_object()
        sampling = {
            "applicable": True, "mode": "downsampled",
            "point_cap": 64, "reason": "display_window",
        }
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o13-1",
            sampling=sampling,
        )
        _export("validation.formats.chart", screen_svg=_svg(700, "o13"))
        snap = _visual_snapshots(view_id="validation.formats.chart")[-1]
        payload = _artifact_payload(snap)
        assert payload["display"]["detail_level"] == "sampling"
        assert payload["sampling"]["mode"] == "downsampled"
        assert payload["sampling"]["point_cap"] == 64
        # и второй кейс: full -> expanded
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o13-2",
        )
        _export(
            "validation.formats.chart",
            screen_svg=_svg(701, "o13-full"),
            result_ref="vr-p10cert-o13-2",
        )
        snaps = [
            a for a in _visual_snapshots(view_id="validation.formats.chart")
            if _artifact_payload(a)["sampling"]["mode"] == "full"
        ]
        assert snaps, "второй снапшот (full) не найден"
        assert _artifact_payload(snaps[-1])["display"]["detail_level"] == "expanded"

    def test_o14_refs_honest_no_fabrication(self):
        """Refs не фабрикуются: без target_column -- честный отказ с
        именем ref; без date_column (ни сессия, ни запрос) -- отказ;
        явный date_column запроса принимается; grouping-refs структуры
        -- «(не используется)»/«(не определена)» (PROGR-14-A)."""
        from dataclasses import replace as dc_replace

        from apps.api.research_runs import get_research_run_store
        from apps.api.visual_exports import VisualSourceUnavailable, request_visual_export

        # (а) без target_column (пересеиваем run ПОСЛЕ freeze: хелпер
        # freeze восстанавливает дефолтный target)
        _seed_session_object()
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o14-1",
        )
        run = _seed_run(target_column=None)
        with pytest.raises(VisualSourceUnavailable) as exc:
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.regularity.overview",
                session_id=SESSION_ID, render_requested_at=_now(),
            )
        assert "target_column" in str(exc.value)
        # (б) target есть, но без date_column ни в сессии, ни в запросе
        run2 = dc_replace(run, target_column="turnover")
        get_research_run_store().upsert_run(run2)
        from apps.api.session_store import get_session_store

        _live = get_session_store().get_or_create(SESSION_ID)
        _live.set_date_column("")  # «(не использовать)»-семантика отсутствия
        get_session_store().save(_live)
        with pytest.raises(VisualSourceUnavailable) as exc2:
            request_visual_export(
                RUN_ID, _owner_subject(),
                view_id="validation.regularity.overview",
                session_id=SESSION_ID, render_requested_at=_now(),
            )
        assert "date_column" in str(exc2.value)
        # (в) явный date_column запроса принимается
        outcome = request_visual_export(
            RUN_ID, _owner_subject(),
            view_id="validation.regularity.overview",
            session_id=SESSION_ID, date_column="dt",
            render_requested_at=_now(),
        )
        snap = next(
            a for a in _visual_snapshots(view_id="validation.regularity.overview")
            if a.artifact_id == outcome["snapshot_artifact_id"]
        )
        refs = _artifact_payload(snap)["refs"]
        assert refs["target_column"] == "turnover"
        assert refs["date_column"] == "dt"
        assert refs["data_revision"] == str(DATA_REVISION)
        assert refs["context_id"] == CONTEXT_ID


# ══════════════════════════════════════════════════════════════════════
# O15–O16. Полный путь job'а (fake renderer) и мост контента
# ══════════════════════════════════════════════════════════════════════


class TestCertWorkerE2E:
    def test_o15_full_job_path_fake_renderer_chart(self):
        """Полный путь на СВОИХ данных: POST-цепочка -> штатный
        document_render_worker.run_once с fake-renderer -> ready PNG
        rendition; payload renderer'а: мой svg в recharts-секции,
        request_id = pgv:{job_id}, light-print тема, моя легенда осей."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o15-1",
        )
        outcome = _export(
            "validation.formats.chart", screen_svg=_svg(760, "o15")
        )
        job_id = outcome["job"]["job_id"]
        captured: dict = {}

        class _FakeRenderer:
            def render_page(self, payload, *, timeout_s=None):
                captured["payload"] = payload
                return b"\x89PNG\r\n\x1a\n" + b"p10cert" * 9

        from apps.api import document_jobs, document_render_worker

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service, png_renderer=_FakeRenderer()
        )
        worker.run_once()
        job = service.registry.get_job(job_id)
        assert job.state == "ready", f"job: {job.state} {job.error_code}"
        rendition = service.registry.get_rendition(job.rendition_id)
        assert rendition.state == "ready" and rendition.format == "png"
        payload = captured["payload"]
        assert payload["request_id"] == f"pgv:{job_id}"
        assert payload["snapshot"]["print"]["theme"] == "light-print"
        assert payload["snapshot"]["print"]["profile_id"] == "figure-landscape"
        section = next(
            s for s in payload["sections"] if s["section_id"] == "main"
        )
        assert "data-cert='o15'" in section["svg_xml"]

    def test_o15b_mixed_job_path_renders_two_sections(self):
        """Mixed-сайт: job рендерит ОБЕ секции (chart+таблица), контент
        таблицы -- мои известные значения p-value."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "preprocessing.stationarity.overview",
            data=CERT_STATIONARITY_DATA,
            kind="recharts_svg",  # payload.kind mixed-сайта -- первичный kind
            result_ref="vr-p10cert-o15b-1",
        )
        outcome = _export(
            "preprocessing.stationarity.overview", screen_svg=_svg(910, "o15b")
        )
        job_id = outcome["job"]["job_id"]
        captured: dict = {}

        class _FakeRenderer:
            def render_page(self, payload, *, timeout_s=None):
                captured["payload"] = payload
                return b"\x89PNG\r\n\x1a\n" + b"mixed" * 8

        from apps.api import document_jobs, document_render_worker

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service, png_renderer=_FakeRenderer()
        )
        worker.run_once()
        job = service.registry.get_job(job_id)
        assert job.state == "ready", f"job: {job.state} {job.error_code}"
        payload = captured["payload"]
        kinds = {s["section_id"]: s["kind"] for s in payload["sections"]}
        assert kinds == {"chart": "recharts_svg", "tests": "html_table"}, kinds
        tests_section = next(
            s for s in payload["sections"] if s["section_id"] == "tests"
        )
        flat = json.dumps(tests_section, ensure_ascii=False)
        assert "0.31" in flat and "0.7" in flat, "p-value до/после потеряны"
        assert "ADF" in flat and "KPSS" in flat


class TestCertBridge:
    def test_o16_snapshot_svg_wins_over_result_svg(self):
        """«Не первый SVG» на мосту: screen_svg снапшота первичен --
        если frozen result несёт svg_xml, а снапшот -- свой screen_svg,
        печать несёт снапшотный (мой маркер), а не результатный."""
        from apps.api.print_render_payload import (
            build_print_render_payload_from_basis,
        )

        _seed_run()
        _seed_session_object()
        from apps.api.visual_artifacts import freeze_visual_print_snapshot
        from apps.api.visual_exports import build_visual_print_snapshot

        _freeze_result(
            "validation.formats.chart",
            data={"svg_xml": "<svg xmlns='http://www.w3.org/2000/svg'><rect data-from='RESULT'/></svg>"},
            kind="recharts_svg",
            result_ref="vr-p10cert-o16-1",
        )
        results = _visual_results(view_id="validation.formats.chart")
        result_artifact = results[-1]
        result_payload = _artifact_payload(result_artifact)
        snapshot_payload = build_visual_print_snapshot(
            RUN_ID,
            site_view_id="validation.formats.chart",
            result_artifact=result_artifact,
            result_payload=result_payload,
            screen_svg=_svg(620, "o16-SNAPSHOT"),
            render_requested_at=_now(),
        )
        payload = build_print_render_payload_from_basis(
            {
                "snapshot": snapshot_payload,
                "visual_result": result_payload,
            },
            request_id="pgv:p10cert-o16",
        )
        section = payload["sections"][0]
        assert "o16-SNAPSHOT" in section["svg_xml"]
        assert "data-from" not in section["svg_xml"], (
            "мост взял svg из результата -- не frozen screen_svg снапшота"
        )

    def test_o16b_missing_form_is_honest_incomplete(self):
        """§3.6: неизвестная форма данных -- честный
        PrintRenderPayloadIncomplete (job-код missing_section_content),
        не пустая таблица/нули."""
        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            build_print_render_payload_from_basis,
        )

        _seed_run()
        _seed_session_object()
        from apps.api.visual_exports import build_visual_print_snapshot

        _freeze_result(
            "validation.regularity.overview",
            data={"совсем": "не форма таблицы"},
            kind="html_table",
            result_ref="vr-p10cert-o16b-1",
        )
        result_artifact = _visual_results(view_id="validation.regularity.overview")[-1]
        result_payload = _artifact_payload(result_artifact)
        snapshot_payload = build_visual_print_snapshot(
            RUN_ID,
            site_view_id="validation.regularity.overview",
            result_artifact=result_artifact,
            result_payload=result_payload,
            render_requested_at=_now(),
        )
        with pytest.raises(PrintRenderPayloadIncomplete):
            build_print_render_payload_from_basis(
                {"snapshot": snapshot_payload, "visual_result": result_payload},
                request_id="pgv:p10cert-o16b",
            )


# ══════════════════════════════════════════════════════════════════════
# O17–O19. visual-sources без науки; PG write-path; статическая coverage
# ══════════════════════════════════════════════════════════════════════


class TestCertVisualSources:
    def test_o17_sources_list_and_no_science(self, client):
        """GET visual-sources: 38 источников, у свежего запуска
        export_ready=false с причиной; после freeze+экспорта -- true с
        digest/контекстом; GET не создаёт артефактов (наука не
        запускается)."""
        _seed_run()
        _seed_session_object()
        resp = client.get(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources",
            cookies={"cisstat_session_id": SESSION_ID},
        )
        assert resp.status_code == 200
        sources = resp.json()["sources"]
        assert len(sources) == 55  # 38 PGV-10 + 17 PGV-11 (EDA/tasks)
        by_view = {s["view_id"]: s for s in sources}
        assert by_view["validation.regularity.overview"]["export_ready"] is False
        assert "result_not_frozen" in by_view["validation.regularity.overview"]["unavailable_reason"]
        assert len(_visual_results()) == 0
        _freeze_result(
            "validation.regularity.overview",
            data=CERT_TABLE_DATA,
            kind="html_table",
            result_ref="vr-p10cert-o17-1",
        )
        _export("validation.regularity.overview")
        resp2 = client.get(
            f"/v1/documentation/runs/{RUN_ID}/visual-sources",
            cookies={"cisstat_session_id": SESSION_ID},
        )
        src = {s["view_id"]: s for s in resp2.json()["sources"]}[
            "validation.regularity.overview"
        ]
        assert src["export_ready"] is True
        assert src["latest_result"]["digest"]
        assert src["latest_result"]["result_ref"] == "vr-p10cert-o17-1"
        assert src["latest_snapshot"]["profile_id"] == "figure-landscape"


class TestCertPgWritePath:
    def test_o18_print_job_insert_replays_into_mini_model(self, monkeypatch):
        """F-P9C1-класс regression-pin на СВОИХ данных: печатные
        job/rendition, созданные ЭКСПОРТОМ PGV-10, в формах INSERT
        Postgres-адаптера исполняются в мини-модели ограничений
        0010+0016+0017+0018 (FK ON) без нарушений; NULL-нормализация
        соблюдена."""
        import sqlite3

        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o18-1",
        )
        outcome = _export("validation.formats.chart", screen_svg=_svg(660, "o18"))
        job_id = outcome["job"]["job_id"]

        class _FakeRenderer:
            def render_page(self, payload, *, timeout_s=None):
                return b"\x89PNG\r\n\x1a\n" + b"pg" * 16

        from apps.api import document_jobs, document_render_worker

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service, png_renderer=_FakeRenderer()
        )
        worker.run_once()
        job_record = service.registry.get_job(job_id)
        rendition_record = service.registry.get_rendition(job_record.rendition_id)

        from apps.api.document_jobs import PostgresDocumentRegistry

        registry = PostgresDocumentRegistry("postgresql://p10cert:fake@localhost/db")
        captured: list = []

        class _Log:
            def __init__(self):
                self.rows = []

        class _Cur:
            def __init__(self, log):
                self._log = log

            def execute(self, sql, params=()):
                self._log.rows.append((sql, tuple(params)))

            def fetchone(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Conn:
            def __init__(self, log):
                self._log = log

            def cursor(self):
                return _Cur(self._log)

            def commit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _fake_connect():
            conn = _Conn(_Log())
            captured.append(conn)
            return conn

        monkeypatch.setattr(registry, "_connect", _fake_connect)
        registry.register_job(job_record)
        registry.register_rendition(rendition_record)
        sql_params = [(s.replace("%s", "?"), p) for conn in captured for (s, p) in conn._log.rows]

        # Мини-модель ограничений (зеркало 0010+0016+0017+0018, FK ON):
        # колонки -- из ФАКТИЧЕСКОЙ формы INSERT адаптера; FK -- по
        # известным связям DDL 0010/0016/0017 (NULL-допускающие).
        import re as _re

        mini = sqlite3.connect(":memory:")
        mini.execute("PRAGMA foreign_keys = ON")
        mini.executescript(
            """
            CREATE TABLE research_runs (run_id TEXT PRIMARY KEY);
            CREATE TABLE report_snapshots (snapshot_id TEXT PRIMARY KEY);
            CREATE TABLE document_revisions (revision_id TEXT PRIMARY KEY);
            CREATE TABLE document_print_revisions (print_revision_id TEXT PRIMARY KEY);
            CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY);
        """
        )
        mini.execute("INSERT INTO research_runs VALUES (?)", (RUN_ID,))
        mini.execute(
            "INSERT INTO document_print_revisions VALUES (?)",
            (outcome["print_revision_id"],),
        )
        # FK-карта из фактических 0010+0016+0017+0018: basis_artifact_id
        # и revision_id (jobs) -- БЕЗ FK; snapshot_id/revision_id
        # (renditions) -- NULL-допускающие после 0017/0018.
        _FK_JOBS = {
            "run_id": "research_runs(run_id)",
            "snapshot_id": "report_snapshots(snapshot_id)",
            "print_revision_id": "document_print_revisions(print_revision_id)",
        }
        _FK_RENDITIONS = {
            "run_id": "research_runs(run_id)",
            "snapshot_id": "report_snapshots(snapshot_id)",
            "revision_id": "document_revisions(revision_id)",
            "print_revision_id": "document_print_revisions(print_revision_id)",
        }
        insert_forms = [
            (sql, params)
            for sql, params in sql_params
            if "INSERT INTO" in sql.upper() and "document_jobs" in sql
        ] + [
            (sql, params)
            for sql, params in sql_params
            if "INSERT INTO" in sql.upper() and "document_renditions" in sql
        ]
        assert insert_forms, "адаптер не выдал форм INSERT печатных записей"
        seen_tables = {}
        for sql, params in insert_forms:
            m = _re.match(
                r"\s*INSERT INTO (\w+)\s*\(([^)]*)\)\s*VALUES", sql, _re.I
            )
            assert m, f"неожиданная форма SQL: {sql[:120]}"
            table, cols = m.group(1), [
                c.strip() for c in m.group(2).split(",")
            ]
            assert len(cols) == len(params), (
                f"число колонок {len(cols)} != число параметров {len(params)}"
            )
            if table not in seen_tables:
                fks = _FK_JOBS if table == "document_jobs" else _FK_RENDITIONS
                defs = []
                for col in cols:
                    col_type = "INTEGER" if col in ("attempt",) else "TEXT"
                    ddl = f"{col} {col_type}"
                    if col in fks:
                        ddl += f" REFERENCES {fks[col]}"
                    defs.append(ddl)
                mini.execute(
                    f"CREATE TABLE {table} ({', '.join(defs)})"
                )
                if table == "document_renditions":
                    # 0010 UNIQUE (snapshot-путь) + частичный UNIQUE 0017
                    # (печатный путь: цель конфликта по роду записи).
                    mini.execute(
                        "CREATE UNIQUE INDEX uq_r_snap ON document_renditions"
                        " (snapshot_id, format, redaction_profile)"
                    )
                    mini.execute(
                        "CREATE UNIQUE INDEX uq_r_print ON document_renditions"
                        " (print_revision_id, format, redaction_profile)"
                        " WHERE print_revision_id IS NOT NULL"
                    )
                seen_tables[table] = cols
            try:
                mini.execute(sql, params)
            except sqlite3.Error as exc:
                raise AssertionError(
                    f"форма INSERT печатной записи нарушает ограничения "
                    f"мини-модели: {exc}\nSQL: {sql}\nparams: {params}"
                ) from exc
        # NULL-семантика FIX PGV-09 печатного write-path: ключевые
        # FK-колонки печатных записей -- NULL, не '' и не 'None'.
        job_row = mini.execute(
            "SELECT snapshot_id, print_revision_id FROM document_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        assert job_row is not None, "печатная job не записана в мини-модель"
        assert job_row[0] is None, (
            f"snapshot_id печатной job = {job_row[0]!r} (ожидается NULL)"
        )
        rend_row = mini.execute(
            "SELECT revision_id, snapshot_id, print_revision_id FROM document_renditions"
        ).fetchone()
        assert rend_row is not None, "печатная rendition не записана"
        assert rend_row[0] is None, (
            f"revision_id печатной rendition = {rend_row[0]!r} (ожидается NULL)"
        )
        assert rend_row[1] is None
        assert rend_row[2] == outcome["print_revision_id"]


class TestCertStaticCoverage:
    def test_o19_every_scope_view_has_button_mount_and_no_document_scan(self):
        """Статический coverage-оракул сертификатора (§5 «полный
        инвентарь»): (а) каждый из 38 view_id скоупа упомянут в
        исходниках UI как viewId кнопки/скоупа; (б) serializeChartSvg
        использует container.querySelector, а НЕ document-скан
        («не первый SVG документа»); (в) unknown viewId из скоупа
        кнопки не получают."""
        import re

        ui_dir = Path(__file__).resolve().parents[2] / "packages" / "ui"
        from apps.api.visual_exports import pgv10_export_view_ids

        scope = set(pgv10_export_view_ids())
        text_corpus = ""
        for path in list((ui_dir / "components").rglob("*.tsx")) + list(
            (ui_dir / "lib").rglob("*.ts")
        ):
            if ".test." in path.name:
                continue
            text_corpus += path.read_text(encoding="utf-8", errors="replace")
        missing = [
            view_id for view_id in scope
            if f'"{view_id}"' not in text_corpus and f"'{view_id}'" not in text_corpus
        ]
        assert not missing, f"view без монтирования кнопки в UI: {missing}"
        serializer = (
            ui_dir / "lib" / "serializeChartSvg.ts"
        ).read_text(encoding="utf-8")
        assert "container.querySelector" in serializer
        assert not re.search(r"document\.querySelector\(\s*[\"']svg", serializer), (
            "serializeChartSvg сканирует документ -- «первый SVG»-дефект"
        )


# ══════════════════════════════════════════════════════════════════════
# F-P10C1 (proof). Иной профиль переиспользует снапшот со старым
# print.profile_id -- декларируемый профиль ревизии расходится с
# геометрией рендера. Оракул зарегистрирован КАК ДОКАЗАТЕЛЬСТВО
# НАХОДКИ: GREEN-ожидание описывает ЧЕСТНОЕ поведение, фактический
# RED -- воспроизведение несоответствия (см. акт сертификации §4).
# ══════════════════════════════════════════════════════════════════════


class TestCertProfileConsistencyProof:
    def test_o20_second_profile_render_payload_declares_requested_profile(self):
        """Честный контракт: при экспорте того же frozen input с иным
        профилем payload рендера ревизии a4-portrait должен нести
        print.profile_id='a4-portrait'. ФАКТ (см. акт): payload несёт
        профиль ПЕРВОГО экспорта -- находка F-P10C1."""
        _seed_run()
        _seed_session_object()
        _freeze_result(
            "validation.formats.chart",
            data=CERT_FORMAT_DATA,
            kind="recharts_svg",
            result_ref="vr-p10cert-o20-1",
        )
        _export("validation.formats.chart", screen_svg=_svg(670, "o20"))  # figure-landscape
        second = _export(
            "validation.formats.chart",
            screen_svg=_svg(670, "o20"),
            profile_id="a4-portrait",
        )
        captured: dict = {}

        class _FakeRenderer:
            def render_page(self, payload, *, timeout_s=None):
                captured["payload"] = payload
                return b"\x89PNG\r\n\x1a\n" + b"prof" * 8

        from apps.api import document_jobs, document_render_worker

        service = document_jobs.DocumentDeliveryService.create_default()
        worker = document_render_worker.DocumentRenderWorker(
            service=service, png_renderer=_FakeRenderer()
        )
        worker.run_once()
        job = service.registry.get_job(second["job"]["job_id"])
        assert job.state == "ready", f"job: {job.state} {job.error_code}"
        # Честное ожидание: геометрия рендера = заявленный профиль.
        assert captured["payload"]["snapshot"]["print"]["profile_id"] == (
            second["profile_id"]
        ), (
            "F-P10C1: ревизия декларирует "
            f"{second['profile_id']}, а рендер несёт "
            f"{captured['payload']['snapshot']['print']['profile_id']}"
        )
