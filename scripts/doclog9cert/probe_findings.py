# scripts/doclog9cert/probe_findings.py
"""DOCLOG-9-CERT: зонды находок (независимые воспроизводимые пробы).

P1 (F-D9C1): ICC-профиль littlecms несёт wall-clock в заголовке --
pdfa-рендер недетерминирован; repo-тест pdfa-детерминизма флакует
(зависимость от границы секунды).
P2 (F-D9C2): ломучий audit-sink на mandatory-аудите создания профиля --
HTTP 500 (не 503 mandatory_audit_unavailable) И профиль остаётся
созданным (реестр пишется до аудита; AC11 fail-closed по состоянию
нарушен).
P3 (F-D9C4): verify_signature_manifest без ключа БРОСАЕТ исключение --
ветка key_unavailable в _signature_validate недостижима (мёртвый код).
P4 (F-D9C5): анонимный POST /org-profiles -- 422 org_profile_invalid
вместо uniform 404 (в create_org_profile нет ветки OrgProfileNotFound).
P5 (N-D9C1): worm_lock при job.revision_id='' -- холд молча не ставится,
выпуск становится ready (apply_worm_hold -> False игнорируется).
P6 (N-D9C2): validate_conformance=false -- мусорные байты становятся
ready с passed-записью «валидация отключена политикой профиля».

Запуск:  /home/z/.venv/bin/python -m scripts.doclog9cert.probe_findings
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))


def _fresh_env() -> None:
    os.environ.pop("DATABASE_URL", None)
    os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp()
    from apps.api import (artifact_store, doc_profiles, document_jobs,
                          document_render_worker, report_snapshot,
                          research_runs)
    from apps.api import security_audit
    from apps.api.session_store import reset_session_store_for_testing

    for mod in (research_runs, artifact_store, report_snapshot,
                document_jobs, document_render_worker, doc_profiles):
        for attr in dir(mod):
            if attr.startswith("reset_") and attr.endswith("_for_testing"):
                getattr(mod, attr)()
    reset_session_store_for_testing()
    security_audit.reset_audit_for_testing()


def _seeds():
    from scripts.doclog9cert.conftest import (SESSION_A, admin_subject,
                                              delivery, profile_service,
                                              run_worker_once, seed_snapshot,
                                              subject_of)

    return SESSION_A, admin_subject, delivery, profile_service, \
        run_worker_once, seed_snapshot, subject_of


def probe_p1_icc_wallclock() -> dict:
    from apps.api.document_renditions import _srgb_icc_bytes

    icc = _srgb_icc_bytes()
    now = time.gmtime()
    fields = {
        "year": int.from_bytes(icc[24:26], "big"),
        "month": int.from_bytes(icc[26:28], "big"),
        "day": int.from_bytes(icc[28:30], "big"),
        "second": int.from_bytes(icc[34:36], "big"),
    }
    ok = (fields["year"] == now.tm_year and fields["month"] == now.tm_mon
          and fields["day"] == now.tm_mday
          and abs(fields["second"] - now.tm_sec) <= 2)
    return {"probe": "P1", "finding": "F-D9C1", "pass": ok,
            "icc_header_fields": fields}


def probe_p2_broken_sink_create() -> dict:
    from apps.api import security_audit
    from apps.api.main import app

    from scripts.doclog9cert.conftest import BrokenAuditSink

    class _Sink(BrokenAuditSink):
        pass

    _fresh_env()
    os.environ["CISSTAT_API_KEYS"] = (
        "d9cert-pk:admin::subj-d9certprobe0001:tenant-d9cert:"
    )
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as client:
        healthy = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9cert-p2a", "version_no": 1, "format": "pdfa"},
            headers={"X-API-Key": "d9cert-pk"},
        )
        security_audit.set_audit_sink_for_testing(_Sink())
        broken = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9cert-p2b", "version_no": 1, "format": "pdfa"},
            headers={"X-API-Key": "d9cert-pk"},
        )
        security_audit.set_audit_sink_for_testing(None)
        after = client.get(
            "/v1/documentation/org-profiles",
            headers={"X-API-Key": "d9cert-pk"},
        )
    names = [p["name"] for p in after.json().get("profiles", [])]
    persisted = "d9cert-p2b" in names
    return {
        "probe": "P2", "finding": "F-D9C2",
        "healthy_status": healthy.status_code,
        "broken_sink_status": broken.status_code,
        "profile_persisted_despite_failure": persisted,
        "pass": broken.status_code == 500 and persisted,
    }


def probe_p3_verify_without_key_raises() -> dict:
    from apps.api.doc_profiles import (
        SignatureKeyUnavailable,
        sign_content,
        verify_signature_manifest,
    )

    os.environ["CISSTAT_DOC_SIGN_KEY"] = "d9cert-p3"
    manifest = sign_content(b"d9cert-p3-bytes", snapshot_sha256="c" * 64,
                            profile_id="prof-p3")
    os.environ.pop("CISSTAT_DOC_SIGN_KEY", None)
    try:
        verify_signature_manifest(b"d9cert-p3-bytes", manifest)
        raised = False
    except SignatureKeyUnavailable:
        raised = True
    return {"probe": "P3", "finding": "F-D9C4",
            "raises_without_key": raised, "pass": raised}


def probe_p4_anonymous_create_422() -> dict:
    from apps.api.main import app

    _fresh_env()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9cert-p4", "version_no": 1, "format": "pdfa"},
        )
    body = resp.json()
    return {
        "probe": "P4", "finding": "F-D9C5",
        "status": resp.status_code,
        "code": body.get("detail", {}).get("code"),
        "pass": resp.status_code == 422
        and body.get("detail", {}).get("code") == "org_profile_invalid",
    }


def probe_p5_worm_skip_without_revision() -> dict:
    from apps.api.document_lifecycle import DocumentLifecycleService

    _fresh_env()
    SESSION_A, admin_subject, delivery, profile_service, \
        run_worker_once, seed_snapshot, subject_of = _seeds()
    snap = seed_snapshot()
    prof = profile_service().create_profile(
        name="d9cert-p5", version_no=1, format="docx",
        subject=admin_subject(), worm_lock=True,
    )
    svc = delivery()
    job, _ = svc.request_rendition(
        snap, format="docx", org_profile_id=prof.profile_id,
        subject=subject_of(SESSION_A), session_id=SESSION_A,
    )
    run_worker_once()
    done = svc.registry.get_job(job.job_id)
    ret = (DocumentLifecycleService.create_default()
           .registry.get_retention(done.revision_id)
           if done.revision_id else None)
    return {
        "probe": "P5", "finding": "N-D9C1",
        "job_revision_id": done.revision_id,
        "job_state": done.state,
        "retention_present": ret is not None,
        "pass": done.state == "ready" and ret is None,
    }


def probe_p6_conformance_off_garbage_ready() -> dict:
    _fresh_env()
    SESSION_A, admin_subject, delivery, profile_service, \
        run_worker_once, seed_snapshot, subject_of = _seeds()
    from apps.api import document_jobs as dj

    snap = seed_snapshot()
    prof = profile_service().create_profile(
        name="d9cert-p6", version_no=1, format="docx",
        subject=admin_subject(), validate_conformance=False,
    )
    svc = delivery()
    original = dj.render_snapshot_docx
    dj.render_snapshot_docx = lambda *a, **k: b"garbage-not-a-zip"
    try:
        job, _ = svc.request_rendition(
            snap, format="docx", org_profile_id=prof.profile_id,
            subject=subject_of(SESSION_A), session_id=SESSION_A,
        )
        run_worker_once()
    finally:
        dj.render_snapshot_docx = original
    done = svc.registry.get_job(job.job_id)
    records = (profile_service().registry
               .list_validations_by_job(job.job_id))
    return {
        "probe": "P6", "finding": "N-D9C2",
        "job_state": done.state,
        "validation": [
            {"validator": r.validator, "result": r.result,
             "findings": r.findings} for r in records
        ],
        "pass": done.state == "ready"
        and any(r.result == "passed" and r.findings for r in records),
    }


def main() -> None:
    results = [
        probe_p1_icc_wallclock(),
        probe_p2_broken_sink_create(),
        probe_p3_verify_without_key_raises(),
        probe_p4_anonymous_create_422(),
        probe_p5_worm_skip_without_revision(),
        probe_p6_conformance_off_garbage_ready(),
    ]
    payload = {"probes": results,
               "all_reproduced": all(r["pass"] for r in results)}
    (HERE / "protocols" / "probe_findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
