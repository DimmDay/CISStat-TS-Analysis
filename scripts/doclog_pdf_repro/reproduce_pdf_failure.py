"""DOCLOG-PDF-FAIL-1 (2026-10-27): динамическая репродукция отказа
«Собрать формат: PDF» в worker-контуре раздела «Документы».

Постановка тимлида: исправление скачивания реализовано (9390ab5), но
кроме формата pdf. Сценарий: «Собрать формат:» -> PDF -> worker
задумывается, ставит в очередь -> «Задание djob-…: Ошибка (failed)
(попытка 2)». Воспроизвести, найти причины, устранить.

Гипотеза (проверяется S1/S2): PDF/PNG-рендер требует TTF-шрифт из
allowlist (_PDF_FONT_CANDIDATES: DejaVu/Liberation). Деплой-образ
python:3.12-slim (apps/api/Dockerfile, render.yaml runtime: docker)
НЕ содержит системных шрифтов -> _resolve_font() честно падает
RenderDependencyError -> worker: render_dependency_unavailable
(детерминированная, терминальная) -> «Ошибка (failed)». Повторный клик
пользователя = ВТОРАЯ попытка (attempt = len(prior_jobs)+1) -- отсюда
«(попытка 2)» в UI.

S1 (baseline, шрифты в ФС есть): полный поток POST pdf -> 202 queued ->
worker run_once() -> ready, непустые байты PDF (%PDF-). Доказывает:
код рендера корректен, конвейер работоспособен.

S2 (симуляция деплой-образа: allowlist-шрифты ОТСУТСТВУЮТ): тот же
поток -> job терминально failed, error_code=render_dependency_unavailable,
attempt не растёт (детерминированная -- очередь не крутится); затем
повторная постановка (клик «собрать ещё раз») -> НОВЫЙ job с attempt=2 ->
тот же отказ -- точный эквивалент наблюдаемого «Ошибка (failed)
(попытка 2)».

Read-only исследование продукта (продуктовый код не меняется); подмена
_PDF_FONT_CANDIDATES -- модель среды, а не патч кода. TestClient +
Memory-бекенды (паттерн корпуса DOCLOG-4/5), namespace RUN-DPF*/dpf-
дизъюнктен. Протокол: protocols/repro_result.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Песочница экспортирует DATABASE_URL -- корпус Memory-паттерна DOCLOG-4
# требует явного выбора memory-бекендов (CISSTAT_*_BACKEND приоритетен).
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ["CISSTAT_SESSIONS_BACKEND"] = "memory"
os.environ["CISSTAT_ARTIFACTS_BACKEND"] = "memory"
os.environ["CISSTAT_DOCUMENTS_BACKEND"] = "memory"
os.environ["CISSTAT_SNAPSHOTS_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)  # песочница; Memory-паттерн DOCLOG-4
# Worker управляется ВРУЧНУЮ (run_once) -- детерминизм сценария.
os.environ["CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED"] = "0"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RUN_ID = "RUN-DPF00001"
SESSION_ID = "dpf-seed-session"


def _reset_stores() -> None:
    from apps.api import artifact_store, report_snapshot
    from apps.api import document_jobs
    from apps.api.routers import documentation as documentation_router
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


def _seed_snapshot():
    from apps.api import research_runs
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun
    from apps.api.session_store import AnalysisSession, get_session_store
    from apps.api.snapshot_builder import SnapshotService
    from apps.api.trace_events import TraceEvent

    now = datetime.now(timezone.utc).isoformat()
    session = AnalysisSession(session_id=SESSION_ID)
    session.owner_subject = SubjectRef.from_session(SESSION_ID).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    get_session_store().save(session)

    run = ResearchRun(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        dataset_fingerprint="dpf" * 10 + "d",
        dataset_name="doclog-pdf-repro",
        target_column="value",
        target_column_source="user",
        created_at=now,
        last_active_at=now,
        status="active",
        context_id="ctx-dpf-1",
        data_revision=2,
        owner_subject=SubjectRef.from_session(SESSION_ID).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    research_runs.get_research_run_store().upsert_run(run)
    research_runs.get_research_run_store().append_event(
        RUN_ID,
        TraceEvent(
            event_type="upload_completed",
            payload={"dataset": "doclog-pdf-repro"},
            run_id=RUN_ID,
            stage="upload",
            schema_version=2,
            evidence_level="server_result",
        ),
    )
    subject = SubjectRef.from_session(SESSION_ID)
    snapshot, _created = SnapshotService.create_default().build_snapshot(
        RUN_ID, subject, session_id=SESSION_ID, kinds=["D02"]
    )
    return snapshot


def _poll_terminal(client, job_id: str, cycles: int = 30) -> dict:
    state = None
    job = {}
    for _ in range(cycles):
        job = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        state = job["state"]
        if state in ("ready", "failed", "cancelled"):
            break
    return job


def _run_pdf_flow(client) -> dict:
    """Клик «Собрать формат: PDF» -> постановка -> worker -> итог."""
    resp = client.post(
        f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
    )
    assert resp.status_code in (200, 201), resp.text
    doc = resp.json()["document"]
    rev_id = doc["current_revision_id"]

    post = client.post(
        f"/v1/documentation/revisions/{rev_id}/renditions",
        json={"format": "pdf"},
    )
    body = post.json()
    if post.status_code == 429:
        return {"post_status": 429, "body": body}
    assert post.status_code == 202, post.text
    job = body["job"]
    job_id = job["job_id"]

    from apps.api.document_render_worker import DocumentRenderWorker

    worker = DocumentRenderWorker(interval=0, render_timeout=30.0)
    cycles = [worker.run_once() for _ in range(6)]
    final = _poll_terminal(client, job_id)

    rendition = None
    rev = client.get(f"/v1/documentation/revisions/{rev_id}").json()
    for item in rev["revision"]["renditions"]:
        if item["format"] == "pdf":
            rendition = item
    content_head = None
    if rendition is not None and rendition.get("state") == "ready":
        c = client.get(
            f"/v1/documentation/renditions/{rendition['rendition_id']}/content"
        )
        content_head = {
            "status": c.status_code,
            "content_type": c.headers.get("content-type"),
            "content_disposition": c.headers.get("content-disposition"),
            "head": c.content[:8].decode("latin-1"),
            "size": len(c.content),
        }
    return {
        "revision_id": rev_id,
        "post_status": post.status_code,
        "post_job_state": job["state"],
        "post_job_attempt": job["attempt"],
        "worker_cycles": cycles,
        "final_job": final,
        "rendition_state": (rendition or {}).get("state"),
        "content": content_head,
    }


def main() -> int:
    from fastapi.testclient import TestClient

    results: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
    }

    # ── S1: baseline -- шрифты в ФС есть (локальная/dev-среда) ───────
    import apps.api.document_renditions as renditions

    font_probe = {
        path: os.path.isfile(path) for path, _n, _b in renditions._PDF_FONT_CANDIDATES
    }
    results["font_probe"] = font_probe

    _reset_stores()
    _seed_snapshot()
    from apps.api.main import app

    with TestClient(app) as client:
        client.cookies.set("cisstat_session_id", SESSION_ID)
        results["S1_baseline_fonts_present"] = _run_pdf_flow(client)

    # ── S2: симуляция деплой-образа python:3.12-slim (шрифтов нет) ──
    original_candidates = renditions._PDF_FONT_CANDIDATES
    renditions._PDF_FONT_CANDIDATES = tuple()  # модель slim-образа
    try:
        _reset_stores()
        _seed_snapshot()
        with TestClient(app) as client:
            client.cookies.set("cisstat_session_id", SESSION_ID)
            first = _run_pdf_flow(client)
            # Повторный клик пользователя после неудачи: та же цель
            # (snapshot, format, profile) -> НОВЫЙ job, attempt=2.
            second = _run_pdf_flow(client)
            # Третий клик: attempt=3 -- пользователь будет «щёлкать» дальше.
            third = _run_pdf_flow(client)
        results["S2_deploy_image_no_fonts"] = {
            "first_click": first,
            "second_click": second,
            "third_click": third,
        }
    finally:
        renditions._PDF_FONT_CANDIDATES = original_candidates

    out = Path(__file__).parent / "protocols" / "repro_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def brief(tag: str, data: dict) -> str:
        fin = data.get("final_job", {})
        return (
            f"{tag}: POST={data.get('post_status')} "
            f"state={fin.get('state')} attempt={fin.get('attempt')} "
            f"error_code={fin.get('error_code')}"
        )

    print("font_probe:", json.dumps(font_probe))
    print(brief("S1 baseline (fonts present)", results["S1_baseline_fonts_present"]))
    s2 = results["S2_deploy_image_no_fonts"]
    print(brief("S2 no-fonts click#1", s2["first_click"]))
    print(brief("S2 no-fonts click#2", s2["second_click"]))
    print(brief("S2 no-fonts click#3", s2["third_click"]))
    print("protocol:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
