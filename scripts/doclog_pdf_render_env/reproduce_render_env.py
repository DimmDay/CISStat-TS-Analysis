"""DOCLOG-PDF-RENDER-DEPLOY-2 (2026-10-27): динамическая репродукция
ПОЛНОГО сценария тимлида и оракулы операционной видимости среды.

Постановка: «Полностью воспроизведи сценарий прохождения этапа
"Загрузка" и выгрузи "План исследования" в PDF. У меня не работает --
Ошибка сборки формата pdf: render_dependency_unavailable. Проверь e2e
тестом и оракулами.»

Диагноз (аудит класса отказа DOCLOG-PDF-FONT-DEPLOY-1):
  * В PDF-пути ЕДИНСТВЕННЫЙ источник RenderDependencyError --
    _resolve_font() (font_unavailable); e2e полного сценария на дереве
    fe790c5 ЗЕЛЁНЫЙ (см. tests/api/test_doclog_pdf_full_upload_e2e.py)
    => наблюдаемый отказ возможен ТОЛЬКО в среде без allowlist-шрифта:
    работающий контейнер собран ДО фикса DEPLOY-1 (stale-образ), либо
    его пересборка не выполнилась/упала незаметно.
  * Латентные разрывы ТОГО ЖЕ класса, которые сработали бы следующими:
    Pillow не был объявлен в requirements.txt (нужен render_snapshot_png
    и _srgb_icc_bytes PDF/A), pypdf не был объявлен (нужен
    _pdfa_postprocess). В slim-образе их нет; в песочнице есть --
    недоказанная установка (урок F14).

Сценарии протокола (TestClient + Memory, паттерн корпуса DOCLOG;
namespace RUN-RENV*/renv- дизъюнктен; worker вручную run_once):
  S0  /health/ops render_dependencies -- операционная видимость среды
      (facts-only, peek-семантика): шрифт+reportlab+pillow+pypdf+
      pyarrow на месте => среда ПОЛНАЯ.
  S1  ПОЛНЫЙ этап «Загрузка» штатными эндпоинтами (файл -> цель/дата
      -> паспорт -> validate) -> D01 «План исследования» -> POST pdf
      202 queued -> worker -> ready -> байты %PDF-, attachment.
      Вердикт: конвейер ЗЕЛЁНЫЙ на полном сценарии.
  S2  Модель stale-образа (allowlist-шрифты отсутствуют): тот же
      клик -> терминальный failed, error_code=
      render_dependency_unavailable, attempt не растёт (детерминированная);
      повторная постановка -> новый job attempt=2, тот же отказ --
      точный эквивалент наблюдения тимлида.
  S3  /health/ops в модели stale-образа: render_dependencies.pdf_font
      ok=false -- отказ виден операционно ДО первого клика аналитика
      (тимлид может проверить ЖИВОЙ контейнер без shell-доступа).

Продуктовый код не меняется; подмена _PDF_FONT_CANDIDATES -- модель
среды. Протокол: protocols/repro_result.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Песочница экспортирует DATABASE_URL -- корпус Memory-паттерна DOCLOG-4
# требует явного выбора memory-бекендов (CISSTAT_*_BACKEND приоритетен).
os.environ["CISSTAT_DATA_DIR"] = "/tmp/renv-repro-data"
os.environ["CISSTAT_STORAGE_MODE"] = "advisory"
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ["CISSTAT_SESSION_BACKEND"] = "memory"
os.environ["CISSTAT_ARTIFACTS_BACKEND"] = "memory"
os.environ["CISSTAT_DOCUMENTS_BACKEND"] = "memory"
os.environ["CISSTAT_SNAPSHOTS_BACKEND"] = "memory"
os.environ["CISSTAT_IDENTITY_MODE"] = "session_scoped"
os.environ["CISSTAT_DELIVERY_WORKER_ENABLED"] = "0"
os.environ["CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED"] = "0"
os.environ["CISSTAT_AUDIT_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _scenario_csv() -> bytes:
    from datetime import date, timedelta

    start_day = date(2024, 1, 1)
    rows = ["date,value"]
    for index in range(36):
        day = (start_day + timedelta(days=index)).isoformat()
        if index in (4, 17, 30):
            rows.append(f"{day},")
            continue
        rows.append(f"{day},{float(10 + index)}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _reset_stores() -> None:
    from apps.api import artifact_store, document_jobs, doc_profiles
    from apps.api import research_runs, report_snapshot, security_audit
    from apps.api import session_store, telemetry
    from apps.api.admin_logs import reset_support_grant_registry_for_testing
    from apps.api.monitoring import reset_monitoring_registry_for_testing
    from apps.api.routers import documentation as documentation_router

    session_store.reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    doc_profiles.reset_org_profile_service_for_testing()
    reset_support_grant_registry_for_testing()
    reset_monitoring_registry_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    security_audit.reset_audit_for_testing()
    telemetry.reset_telemetry_for_testing()


def _client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    return TestClient(app)


def _pass_upload_stage(client) -> str:
    """Полное прохождение этапа «Загрузка» штатными эндпоинтами."""
    upload = client.post(
        "/v1/internal/upload",
        files={"file": ("renv-plan-scenario.csv", _scenario_csv(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    assert client.post(
        "/v1/session/target-column", json={"column": "value"}
    ).status_code == 200
    assert client.post(
        "/v1/session/date-column", json={"column": "date"}
    ).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.get("/v1/session/dataset/validate").status_code == 200
    trace = client.get("/v1/progress/trace")
    run_id = trace.json()["run_id"]
    assert run_id
    return run_id


def _worker_drain(cycles: int = 6) -> list:
    from apps.api.document_render_worker import DocumentRenderWorker

    worker = DocumentRenderWorker(interval=0, render_timeout=30.0)
    return [worker.run_once() for _ in range(cycles)]


def _s0_health_full(client) -> dict:
    ops = client.get("/health/ops")
    assert ops.status_code == 200, ops.text
    deps = ops.json()["render_dependencies"]
    assert deps["pdf_font"]["ok"] is True
    assert deps["reportlab"]["ok"] is True
    assert deps["pillow"]["ok"] is True
    assert deps["pypdf"]["ok"] is True
    assert deps["pyarrow"]["ok"] is True
    return {"verdict": "environment_complete", "render_dependencies": deps}


def _s1_full_scenario(client) -> dict:
    run_id = _pass_upload_stage(client)
    created = client.post(
        f"/v1/documentation/runs/{run_id}/documents",
        json={"kind": "D01", "refresh": True},
    )
    assert created.status_code in (200, 201), created.text
    document = created.json()["document"]
    assert document["kind_code"] == "D01"
    revision_id = created.json()["revision"]["revision_id"]

    detail = client.get(f"/v1/documentation/revisions/{revision_id}")
    snapshot = detail.json()["snapshot"]
    d01 = snapshot["sections"][0]
    assert d01["code"] == "D01" and d01["title"] == "План исследования"

    post = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "pdf"},
    )
    assert post.status_code == 202, post.text
    job = post.json()["job"]
    job_id = job["job_id"]
    cycles = _worker_drain()
    final = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
    assert final["state"] == "ready", final

    renditions = [
        item
        for item in client.get(
            f"/v1/documentation/revisions/{revision_id}"
        ).json()["revision"]["renditions"]
        if item["format"] == "pdf"
    ]
    content = client.get(
        f"/v1/documentation/renditions/{renditions[0]['rendition_id']}/content"
    )
    assert content.content[:5] == b"%PDF-"
    return {
        "verdict": "pipeline_green",
        "run_id": run_id,
        "document_kind": document["kind_code"],
        "section": {"code": d01["code"], "title": d01["title"],
                    "claims": len(d01["claims"])},
        "post": {"status": 202, "state": "queued"},
        "worker_cycles": cycles,
        "final_job": {"state": final["state"], "attempt": final["attempt"]},
        "content": {
            "status": content.status_code,
            "head": content.content[:5].decode("latin-1"),
            "size": len(content.content),
            "content_disposition": content.headers.get("content-disposition"),
            "content_type": content.headers.get("content-type"),
        },
    }


def _s2_stale_environment_model(client) -> dict:
    """Модель stale-образа: allowlist-шрифты отсутствуют."""
    from apps.api import document_renditions

    original = document_renditions._PDF_FONT_CANDIDATES
    attempts: list[dict] = []
    try:
        document_renditions._PDF_FONT_CANDIDATES = tuple()
        run_id = _pass_upload_stage(client)
        for click in (1, 2):
            created = client.post(
                f"/v1/documentation/runs/{run_id}/documents",
                json={"kind": "D01", "refresh": False},
            )
            assert created.status_code in (200, 201), created.text
            revision_id = created.json()["revision"]["revision_id"]
            post = client.post(
                f"/v1/documentation/revisions/{revision_id}/renditions",
                json={"format": "pdf"},
            )
            assert post.status_code == 202, post.text
            job = post.json()["job"]
            cycles = _worker_drain()
            final = client.get(
                f"/v1/documentation/jobs/{job['job_id']}"
            ).json()["job"]
            attempts.append({
                "click": click,
                "job_id": job["job_id"],
                "post_state": job["state"],
                "post_attempt": job["attempt"],
                "final_state": final["state"],
                "final_attempt": final["attempt"],
                "error_code": final.get("error_code"),
                "worker_cycles": cycles,
            })
            assert final["state"] == "failed"
            assert final["error_code"] == "render_dependency_unavailable"
    finally:
        document_renditions._PDF_FONT_CANDIDATES = original
    return {
        "verdict": "stale_environment_reproduced",
        "attempts": attempts,
        "equivalent_ui_message": (
            "Задание djob-…: Ошибка (failed) (попытка 2) / "
            "Ошибка сборки формата pdf: render_dependency_unavailable"
        ),
    }


def _s3_health_stale_model(client) -> dict:
    """Операционная видимость в модели stale-образа."""
    from apps.api import document_renditions

    original = document_renditions._PDF_FONT_CANDIDATES
    try:
        document_renditions._PDF_FONT_CANDIDATES = tuple()
        ops = client.get("/health/ops")
        assert ops.status_code == 200
        deps = ops.json()["render_dependencies"]
        assert deps["pdf_font"]["ok"] is False
        assert deps["pdf_font"]["name"] is None
        return {
            "verdict": "stale_environment_visible_in_ops",
            "pdf_font": deps["pdf_font"],
        }
    finally:
        document_renditions._PDF_FONT_CANDIDATES = original


def main() -> int:
    _reset_stores()
    protocol: dict = {
        "task": "DOCLOG-PDF-RENDER-DEPLOY-2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": os.popen("git rev-parse --short HEAD").read().strip(),
        "scenario": (
            "Этап «Загрузка» -> D01 «План исследования» -> «Собрать "
            "формат: PDF»; диагноз render_dependency_unavailable"
        ),
    }
    with _client() as client:
        protocol["S0_health_full"] = _s0_health_full(client)
        _reset_stores()
        protocol["S1_full_scenario"] = _s1_full_scenario(client)
        _reset_stores()
        protocol["S2_stale_environment_model"] = _s2_stale_environment_model(client)
        protocol["S3_health_stale_model"] = _s3_health_stale_model(client)

    protocol["conclusion"] = {
        "pipeline_code": (
            "S1: полный сценарий ЗЕЛЁНЫЙ на fe790c5 -- код и конвейер "
            "корректны; отказ format=pdf render_dependency_unavailable "
            "возможен ТОЛЬКО в среде без allowlist-шрифта"
        ),
        "lead_environment": (
            "наблюдаемый отказ == S2: работающий контейнер собран ДО "
            "DOCLOG-PDF-FONT-DEPLOY-1 (stale-образ) -- требуется "
            "пересборка/редеплой; после неё S0-видимость /health/ops "
            "подтверждает среду без shell-доступа"
        ),
        "class_elimination": (
            "Pillow/pypdf объявлены в requirements, исполняемый guard "
            "PDF в Dockerfile, honest-классификация png/pdfa, "
            "операционная видимость /health/ops render_dependencies"
        ),
    }

    out = Path(__file__).resolve().parent / "protocols" / "repro_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(protocol, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
