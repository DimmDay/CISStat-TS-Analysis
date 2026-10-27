"""DOCLOG-DL-REPRO-1 (2026-10-27): динамическая репродукция поведения
«Собрать формат:» -> «Скачать MD/HTML/JSON» в разделе «Документы».

Постановка тимлида: после этапа «Загрузка» открыт раздел «Документы»,
строка «Собрать формат:»; клик по «Скачать MARKDOWN» даёт НЕ файл .md в
загрузки, а страницу в ТОЙ ЖЕ вкладке; HTML ожидается новой вкладкой;
JSON тоже не скачивается. Прокомментировать поведение сервиса.

Метод: штатный TestClient + Memory-сторы (паттерн корпуса DOCLOG-4),
сессия-владелец (cookie), run bound, frozen-снимок D02 через штатный
сборщик DOCLOG-2, черновик документа + renditions md/html/json (P0,
синхронно). Затем -- точная печать ТОГО, что получает браузер на
GET /renditions/{id}/content (status/Content-Type/Content-Disposition/
nosniff/Cache-Control + первые байты тела) и, для сравнения,
GET /revisions/{id}/preview (панель «Предпросмотр» UI).

Read-only исследование: продуктовый код не меняется; namespace
(RUN-DLR*, dlr-*) дизъюнктен repo и сертификаторам.
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RUN_ID = "RUN-DLR00001"
SESSION_ID = "dlr-seed-session"


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
        dataset_fingerprint="dlr" * 10 + "d",
        dataset_name="doclog-dl-repro",
        target_column="value",
        target_column_source="user",
        created_at=now,
        last_active_at=now,
        status="active",
        context_id="ctx-dlr-1",
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
            payload={"dataset": "doclog-dl-repro"},
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


def main() -> int:
    from fastapi.testclient import TestClient

    _reset_stores()
    _seed_snapshot()

    from apps.api.main import app

    with TestClient(app) as client:
        client.cookies.set("cisstat_session_id", SESSION_ID)

        # Пользовательский путь: черновик D02 -> ревизия -> renditions.
        resp = client.post(f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"})
        assert resp.status_code in (200, 201), resp.text
        doc = resp.json()["document"]
        rev_id = doc["current_revision_id"]

        results: dict[str, dict] = {"scenario": {
            "base": "b0ef60e (main) + DOCLOG-DL-FIX-1 (attachment)",
            "run_id": RUN_ID,
            "session_id": SESSION_ID,
            "document_kind": "D02",
            "revision_id": rev_id,
        }}

        for fmt in ("md", "html", "json", "csv", "jsonl", "zip"):
            r = client.post(
                f"/v1/documentation/revisions/{rev_id}/renditions", json={"format": fmt}
            )
            if r.status_code != 202:
                results[fmt] = {"post_status": r.status_code, "body": r.json()}
                continue
            job = r.json()["job"]
            job_id = job["job_id"]
            state = job["state"]
            for _ in range(50):
                if state in ("ready", "failed", "cancelled"):
                    break
                state = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]["state"]
            rend = client.get(f"/v1/documentation/revisions/{rev_id}").json()["revision"]["renditions"]
            if not any(x["format"] == fmt for x in rend):
                results[fmt] = {
                    "post_status": 202,
                    "job_state": state,
                    "renditions_seen": [x["format"] for x in rend],
                }
                continue
            rendition = next(x for x in rend if x["format"] == fmt)
            c = client.get(f"/v1/documentation/renditions/{rendition['rendition_id']}/content")
            body_head = c.content[:90].decode("utf-8", "replace").replace("\n", "\\n")
            results[fmt] = {
                "post_status": 202,
                "job_state": state,
                "content_status": c.status_code,
                "content_type": c.headers.get("content-type"),
                "content_disposition": c.headers.get("content-disposition"),
                "x_content_type_options": c.headers.get("x-content-type-options"),
                "cache_control": c.headers.get("cache-control"),
                "body_head": body_head,
                "size_bytes": rendition["size_bytes"],
            }

        pv = client.get(f"/v1/documentation/revisions/{rev_id}/preview")
        results["preview_endpoint"] = {
            "status": pv.status_code,
            "content_type": pv.headers.get("content-type"),
            "content_disposition": pv.headers.get("content-disposition"),
        }

    out = REPO / "scripts/doclog_dl_repro/protocols/repro_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
