# tests/api/test_doclog_pdf_full_upload_e2e.py
"""DOCLOG-PDF-RENDER-DEPLOY-2 (2026-10-27): E2E-оракул ПОЛНОГО
сценария тимлида на дереве fe790c5:

  этап «Загрузка» (штатные HTTP-эндпоинты: файл -> цель/дата ->
  паспорт -> validate) -> документ D01 «План исследования» ->
  «Собрать формат: PDF» (202 queued) -> worker -> ready -> байты PDF.

Отличие от scripts/doclog_pdf_repro/reproduce_pdf_failure.py
(DOCLOG-PDF-FONT-DEPLOY-1): там снимок сидировался SnapshotService
напрямую; здесь ПРОХОЖДЕНИЕ этапа «Загрузка» целиком через реальные
эндпоинты (TestClient, паттерн test_doclog_recheck_fix.py) -- то есть
полная цепочка прод, включая трассу upload_completed и durable-события
запуска, из которых сборщик D01 берёт claims.

Ожидаемый вердикт на дереве с зависимостями рендера: конвейер ЗЕЛЁНЫЙ
(ready, %PDF-, attachment) -- наблюдаемый у тимлида
render_dependency_unavailable на format=pdf возможен ТОЛЬКО в среде
без allowlist-шрифта (stale-образ до DEPLOY-1); runtime-видимость
состояния среды даёт /health/ops render_dependencies.

Namespace дизъюнктен: RUN-RENV*, renv-*.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.session_store import SESSION_COOKIE_NAME


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Изолированный TestClient: memory-бекенды, свой каталог данных
    (паттерн корпуса DOCLOG, tests/api/test_doclog_recheck_fix.py)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "renv-e2e-data"))
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SNAPSHOTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_API_KEYS", "renv-e2e-key")
    for name in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    from apps.api import artifact_store, document_jobs, doc_profiles
    from apps.api import research_runs, report_snapshot, session_store
    from apps.api import security_audit
    from apps.api.admin_logs import reset_support_grant_registry_for_testing
    from apps.api.main import app
    from apps.api.monitoring import reset_monitoring_registry_for_testing

    session_store.reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    doc_profiles.reset_org_profile_service_for_testing()
    reset_support_grant_registry_for_testing()
    reset_monitoring_registry_for_testing()
    monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "memory")
    security_audit.reset_audit_for_testing()

    with TestClient(app) as test_client:
        yield test_client


def _scenario_csv() -> bytes:
    """Детерминированный ряд n=36 (date/value) -- тот же класс входа,
    что у сценария DOCLOG-E2E-RECHECK (гейт паспорта >= 30 точек)."""
    from datetime import date, timedelta

    start_day = date(2024, 1, 1)
    rows = ["date,value"]
    for index in range(36):
        day = (start_day + timedelta(days=index)).isoformat()
        if index in (4, 17, 30):  # 3 пропуска
            rows.append(f"{day},")
            continue
        rows.append(f"{day},{float(10 + index)}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _pass_upload_stage(client: TestClient) -> str:
    """ПОЛНОЕ прохождение этапа «Загрузка» штатными эндпоинтами:
    файл -> авто/ручная фиксация цели и временной колонки -> паспорт
    start -> validate -> run_id (как в проде: durable-события запуска
    пишутся TraceHookMiddleware, включая upload_completed)."""
    upload = client.post(
        "/v1/internal/upload",
        files={"file": ("renv-plan-scenario.csv", _scenario_csv(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["rows"] == 36 and body["columns"] == 2
    assert body["error"] is None

    target = client.post("/v1/session/target-column", json={"column": "value"})
    assert target.status_code == 200, target.text
    date_column = client.post("/v1/session/date-column", json={"column": "date"})
    assert date_column.status_code == 200, date_column.text

    passport = client.post("/v1/session/dataset/passport/start")
    assert passport.status_code == 200, passport.text
    validated = client.get("/v1/session/dataset/validate")
    assert validated.status_code == 200, validated.text

    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    run_id = trace.json()["run_id"]
    assert run_id, "run_id не зафиксирован после этапа «Загрузка»"
    return run_id


def _worker_drain(cycles: int = 6) -> list:
    """Ручной прогон worker'а рендера (CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED=0)."""
    from apps.api.document_render_worker import DocumentRenderWorker

    worker = DocumentRenderWorker(interval=0, render_timeout=30.0)
    return [worker.run_once() for _ in range(cycles)]


class TestFullUploadStageToPdf:
    def test_upload_stage_plan_document_pdf_ready(self, client):
        """«Загрузка» -> D01 «План исследования» -> PDF -> ready."""
        run_id = _pass_upload_stage(client)

        # -- документ D01 «План исследования» (клик в разделе «Документы») --
        created = client.post(
            f"/v1/documentation/runs/{run_id}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert created.status_code in (200, 201), created.text
        document = created.json()["document"]
        assert document["kind_code"] == "D01"
        revision_id = created.json()["revision"]["revision_id"]

        detail = client.get(f"/v1/documentation/revisions/{revision_id}")
        assert detail.status_code == 200, detail.text
        snapshot = detail.json()["snapshot"]
        section_codes = [s["code"] for s in snapshot["sections"]]
        assert section_codes == ["D01"], section_codes
        d01 = snapshot["sections"][0]
        assert d01["title"] == "План исследования"
        assert d01["claims"], "D01 без claims -- пустой план недопустим"

        # -- «Собрать формат: PDF» (тяжёлый формат -> 202 queued) --
        post = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "pdf"},
        )
        assert post.status_code == 202, post.text
        job = post.json()["job"]
        assert job["state"] == "queued"
        job_id = job["job_id"]

        cycles = _worker_drain()

        final = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        assert final["state"] == "ready", (
            f"job не дошёл до ready: {final} (worker cycles: {cycles})"
        )
        assert "error_code" not in final or not final.get("error_code")

        # -- байты выдачи: настоящий PDF, attachment (DOCLOG-DL-FIX-1) --
        renditions = [
            item
            for item in client.get(
                f"/v1/documentation/revisions/{revision_id}"
            ).json()["revision"]["renditions"]
            if item["format"] == "pdf"
        ]
        assert renditions and renditions[0]["state"] == "ready"
        content = client.get(
            f"/v1/documentation/renditions/{renditions[0]['rendition_id']}/content"
        )
        assert content.status_code == 200, content.text
        assert content.content[:5] == b"%PDF-"
        assert len(content.content) > 1000, "PDF подозрительно мал"
        assert "attachment" in content.headers.get("content-disposition", "")

    def test_health_ops_reports_render_environment(self, client):
        """После прохождения «Загрузки» операционная диагностика живой
        среды показывает: allowlist-шрифт и python-зависимости рендера
        НА МЕСТЕ (на stale-контейнере этот тест-оракул честно сказал бы
        pdf_font ok=False -- наблюдаемый отказ стал бы видим до
        первого клика «Собрать формат»)."""
        _pass_upload_stage(client)
        ops = client.get("/health/ops")
        assert ops.status_code == 200, ops.text
        deps = ops.json()["render_dependencies"]
        assert deps["pdf_font"]["ok"] is True
        assert deps["pdf_font"]["name"] == "DejaVuSans"
        assert deps["reportlab"]["ok"] is True
        assert deps["pillow"]["ok"] is True
        assert deps["pypdf"]["ok"] is True
        assert deps["pyarrow"]["ok"] is True
