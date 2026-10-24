# scripts/doclog9cert/test_d9cert_oracle_api.py
"""DOCLOG-9-CERT: API-оракулы (a01–a26) на СВОИХ ключах/сессиях.

Uniform-404 решающей таблицы DOCLOG-0, контракт-тела §17, права §15
(X-API-Key: роль admin / scope policy.admin / без права / чужой tenant),
сквозной выпуск docx/pdfa с профилем через HTTP+worker, honest-отказы
(422/404/409/503), audit-классы, 410 purged, гигиена ошибок (сентинел).
"""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from scripts.doclog9cert.conftest import (
    ADMIN_KEY,
    D9C_SENTINEL,
    OTHER_KEY,
    POLICY_KEY,
    RUN_A,
    SESSION_A,
    SESSION_B,
    SIGN_KEY_VALUE,
    WRITER_KEY,
    admin_subject,
    audit_count,
    cookie,
    delivery,
    make_profile,
    profile_service,
    render_with_profile,
    seed_document_revision,
    seed_snapshot,
)


def _headers(key: str) -> dict:
    return {"X-API-Key": key}


def _create_profile(client: TestClient, key: str, **payload) -> dict:
    resp = client.post(
        "/v1/documentation/org-profiles", json=payload, headers=_headers(key)
    )
    return resp


# ══════════════════════════════════════════════════════════════════════
# Uniform 404 и права
# ══════════════════════════════════════════════════════════════════════


def _request(client: TestClient, method: str, path: str, payload=None):
    if method == "get":
        return client.get(path)
    return client.post(path, json=payload)


def test_a01_anonymous_uniform_404_all_routes(client: TestClient):
    """Аноним не дисклоужает контур: uniform 404 на list/retire/
    validations/verify-signature. ПИН ДЕФЕКТА F-D9C5 (акт §5): POST
    create для анонима отвечает 422 org_profile_invalid («Контур
    профилей недоступен») вместо uniform 404 -- в create_org_profile
    НЕТ ветки OrgProfileNotFound (падает в общий OrgProfileError → 422);
    решающая таблица DOCLOG-0 нарушена для одного маршрута. После FIX
    -- инвертировать POST-строку на 404."""
    paths = [
        ("get", "/v1/documentation/org-profiles", None, 404),
        ("post", "/v1/documentation/org-profiles", {"name": "x", "version_no": 1,
                                                    "format": "pdfa"}, 422),
        ("post", "/v1/documentation/org-profiles/prof-x/retire", None, 404),
        ("get", "/v1/documentation/renditions/rend-x/validations", None, 404),
        ("post", "/v1/documentation/renditions/rend-x/verify-signature", None, 404),
    ]
    for method, path, payload, expected in paths:
        resp = _request(client, method, path, payload)
        assert resp.status_code == expected, (method, path, resp.status_code)
        assert "d9cert-SENTINEL" not in resp.text
    anon_create = client.post(
        "/v1/documentation/org-profiles",
        json={"name": "x", "version_no": 1, "format": "pdfa"},
    )
    assert anon_create.json()["detail"]["code"] == "org_profile_invalid"
    assert "Контур профилей" in anon_create.json()["detail"]["message"]


def test_a02_authenticated_foreign_list_ok_rendition_404(client: TestClient):
    """Чтение списка профилей -- аутентификация (чужой ключ получает
    список -- контракт §15); записи валидации ЧУЖОГО rendition --
    uniform 404 (T7/T15: знание id не право)."""
    profile = make_profile(fmt="docx")
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    client.headers.update(_headers(OTHER_KEY))
    listed = client.get("/v1/documentation/org-profiles")
    assert listed.status_code == 200
    resp = client.get(
        f"/v1/documentation/renditions/{rendition.rendition_id}/validations"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "rendition_not_found"


def test_a03_create_contract_201():
    """201-контракт создания: schema/prefix/defaults/created_by==subject;
    audit org_profile_created ровно 1."""
    from apps.api.identity import subject_pseudonym

    snap = seed_snapshot()
    client = TestClient(__import__("apps.api.main", fromlist=["app"]).app)
    with client as c:
        resp = _create_profile(
            c, ADMIN_KEY, name="d9cert-contract", version_no=3, format="pdfa",
            title_prefix="гриф", footer_text="футер",
            organization="орг",
        )
    assert resp.status_code == 201, resp.text
    profile = resp.json()["profile"]
    assert profile["schema_version"] == "doclog.org_profile/1"
    assert profile["profile_id"].startswith("prof-")
    assert profile["status"] == "active"
    assert profile["version_no"] == 3
    assert profile["language"] == "ru"
    assert profile["validate_conformance"] is True
    assert profile["sign_contents"] is False
    assert profile["anchor_registry"] is False
    assert profile["worm_lock"] is False
    assert profile["retired_at"] is None
    assert profile["created_by"] == "subj-d9certadm00000001"
    assert audit_count("org_profile_created") == 1


def test_a04_writer_without_scope_403_code_catalog(client: TestClient):
    resp = _create_profile(
        client, WRITER_KEY, name="d9cert-w403", version_no=1, format="pdfa"
    )
    assert resp.status_code == 403
    body = resp.json()["detail"]
    assert body["code"] == "insufficient_scope"
    assert "policy.admin" in body["message"]


def test_a05_scope_based_policy_admin_201(client: TestClient):
    """§15 дословно: право policy.admin через scopes создаёт профиль
    БЕЗ роли admin."""
    resp = _create_profile(
        client, POLICY_KEY, name="d9cert-scope201", version_no=1,
        format="docx",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["profile"]["created_by"] == "subj-d9certpol0000002"


def test_a06_validation_catalog_422(client: TestClient):
    """422-каталог: пустое имя / version_no<=0 / version_no не-число /
    чужой формат -- с РАЗНЫМИ кодами; тело плоское в detail."""
    cases = [
        ({"name": "   ", "version_no": 1, "format": "pdfa"},
         "org_profile_invalid"),
        ({"name": "d9cert-bad", "version_no": 0, "format": "pdfa"},
         "org_profile_invalid"),
        ({"name": "d9cert-bad", "version_no": "2", "format": "pdfa"},
         "org_profile_invalid"),
        ({"name": "d9cert-bad", "version_no": 1, "format": "doc"},
         "org_profile_format_mismatch"),
    ]
    for payload, code in cases:
        resp = _create_profile(client, ADMIN_KEY, **payload)
        assert resp.status_code == 422, (payload, resp.status_code)
        assert resp.json()["detail"]["code"] == code, payload
        assert D9C_SENTINEL not in resp.text


def test_a07_duplicate_409_and_versions_allowed(client: TestClient):
    payload = {"name": "d9cert-dup", "version_no": 1, "format": "pdfa"}
    first = _create_profile(client, ADMIN_KEY, **payload)
    assert first.status_code == 201
    second = _create_profile(client, ADMIN_KEY, **payload)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "org_profile_duplicate"
    next_version = _create_profile(
        client, ADMIN_KEY, name="d9cert-dup", version_no=2, format="pdfa"
    )
    assert next_version.status_code == 201
    other_name = _create_profile(
        client, ADMIN_KEY, name="d9cert-dup2", version_no=1, format="pdfa"
    )
    assert other_name.status_code == 201


def test_a08_http_bool_version_no_pin_f_d9c2(client: TestClient):
    """ПИН ДЕФЕКТА F-D9C2 (акт §5): JSON true проходит isinstance(int)
    и создаёт профиль с version_no=true (ответ-тело «version_no»: true);
    durable INTEGER-контур рассинхронизирован. После FIX -- инвертировать
    (ожидать 422)."""
    resp = _create_profile(
        client, ADMIN_KEY, name="d9cert-boolhttp", version_no=True,
        format="pdfa",
    )
    assert resp.status_code == 201  # ПИН: принимается
    assert resp.json()["profile"]["version_no"] is True


def test_a09_router_normalizes_format_filter_and_list_contract(
    client: TestClient,
):
    """Роутер нормализует format (POST «PDFA » и GET ?format=PDF —
    сервис регистронезависим на HTTP-границе); список сортирован и
    содержит и retired (честный листинг)."""
    made = _create_profile(
        client, ADMIN_KEY, name="d9cert-norm", version_no=1, format="PDFA"
    )
    assert made.status_code == 201, made.text
    assert made.json()["profile"]["format"] == "pdfa"
    profile_service().retire_profile(
        made.json()["profile"]["profile_id"], admin_subject()
    )
    listed = client.get("/v1/documentation/org-profiles",
                        params={"format": "PDF"},
                        headers=_headers(ADMIN_KEY))
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 0  # "PDF" -> "pdf" -- не формат каталога
    listed2 = client.get("/v1/documentation/org-profiles",
                         params={"format": "PDFA"},
                         headers=_headers(ADMIN_KEY))
    assert listed2.status_code == 200
    names = [p["name"] for p in listed2.json()["profiles"]]
    assert "d9cert-norm" in names  # retired тоже честно в списке
    statuses = {p["name"]: p["status"] for p in listed2.json()["profiles"]}
    assert statuses["d9cert-norm"] == "retired"


def test_a10_retire_route_flow_and_audit(client: TestClient):
    created = _create_profile(
        client, ADMIN_KEY, name="d9cert-ret", version_no=1, format="docx"
    )
    pid = created.json()["profile"]["profile_id"]
    resp = client.post(
        f"/v1/documentation/org-profiles/{pid}/retire",
        headers=_headers(ADMIN_KEY),
    )
    assert resp.status_code == 200
    body = resp.json()["profile"]
    assert body["status"] == "retired" and body["retired_at"]
    assert audit_count("org_profile_retired") == 1
    again = client.post(
        f"/v1/documentation/org-profiles/{pid}/retire",
        headers=_headers(ADMIN_KEY),
    )
    assert again.status_code == 200
    assert audit_count("org_profile_retired") == 1  # идемпотентно
    unknown = client.post(
        "/v1/documentation/org-profiles/prof-nope/retire",
        headers=_headers(ADMIN_KEY),
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "org_profile_not_found"
    denied = client.post(
        f"/v1/documentation/org-profiles/{pid}/retire",
        headers=_headers(WRITER_KEY),
    )
    assert denied.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Заказ рендера с профилем через HTTP
# ══════════════════════════════════════════════════════════════════════


def _seed_revision_via_http(client: TestClient) -> tuple[str, str]:
    snap = seed_snapshot()
    cookie(client, SESSION_A)
    docs = client.post(
        f"/v1/documentation/runs/{snap.research_run_id}/documents",
        json={"kind": "D01"},
    )
    assert docs.status_code == 201, docs.text
    revision_id = docs.json()["revision"]["revision_id"]
    return snap.snapshot_id, revision_id


def test_a11_docx_without_profile_422(client: TestClient):
    _snapshot_id, revision_id = _seed_revision_via_http(client)
    resp = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "docx"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "org_profile_invalid"
    # pdfa без профиля -- тот же честный отказ (безымянный выпуск запрещён)
    resp2 = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "pdfa"},
    )
    assert resp2.status_code == 422


def test_a12_profile_gates_http_catalog(client: TestClient):
    _snapshot_id, revision_id = _seed_revision_via_http(client)
    # профиль на P0-формат
    pdfa_profile = make_profile(name="d9cert-gate-p", fmt="pdfa", version_no=1)
    resp = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "md", "org_profile_id": pdfa_profile.profile_id},
    )
    assert resp.status_code == 422
    # неизвестный профиль
    resp2 = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "docx", "org_profile_id": "prof-nope"},
    )
    assert resp2.status_code == 404
    assert resp2.json()["detail"]["code"] == "org_profile_not_found"
    # retired профиль
    profile_service().retire_profile(pdfa_profile.profile_id, admin_subject())
    resp3 = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "pdfa", "org_profile_id": pdfa_profile.profile_id},
    )
    assert resp3.status_code == 409
    assert resp3.json()["detail"]["code"] == "org_profile_retired"


def test_a13_docx_end_to_end_ready_validations_download(client: TestClient):
    from scripts.doclog9cert.conftest import run_worker_once

    _snapshot_id, revision_id = _seed_revision_via_http(client)
    created = _create_profile(
        client, POLICY_KEY, name="d9cert-e2e", version_no=1, format="docx",
        footer_text="d9cert-http-футер",
    )
    pid = created.json()["profile"]["profile_id"]
    resp = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "docx", "org_profile_id": pid},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job"]["job_id"]
    assert resp.json()["job"]["org_profile_id"] == pid  # профиль в job metadata
    run_worker_once()
    status = client.get(f"/v1/documentation/jobs/{job_id}")
    job_body = status.json()["job"]
    assert job_body["state"] == "ready", job_body.get("error_code")
    rendition_id = job_body["rendition_id"]
    validations = client.get(
        f"/v1/documentation/renditions/{rendition_id}/validations"
    )
    assert validations.status_code == 200
    records = validations.json()["validations"]
    assert validations.json()["count"] == len(records) >= 1
    assert any(
        r["validator"] == "docx-structural/1" and r["result"] == "passed"
        for r in records
    )
    assert all(r["profile_id"] == pid for r in records)
    # Байты скачиваются и являются валидным OOXML с оформлением профиля.
    content = client.get(
        f"/v1/documentation/renditions/{rendition_id}/content"
    )
    assert content.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(content.content))
    doc = zf.read("word/document.xml").decode("utf-8")
    assert "d9cert-http-футер" in doc


def test_a14_mismatch_409_http(client: TestClient):
    from scripts.doclog9cert.conftest import run_worker_once

    _snapshot_id, revision_id = _seed_revision_via_http(client)
    pa = _create_profile(client, ADMIN_KEY, name="d9cert-mha",
                         version_no=1, format="docx").json()["profile"]
    pb = _create_profile(client, ADMIN_KEY, name="d9cert-mhb",
                         version_no=1, format="docx").json()["profile"]
    first = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "docx", "org_profile_id": pa["profile_id"]},
    )
    assert first.status_code == 202
    run_worker_once()
    second = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "docx", "org_profile_id": pb["profile_id"]},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "org_profile_mismatch"


def test_a15_failed_validation_via_http_no_ready(client: TestClient,
                                                 monkeypatch):
    """Ключевой критерий §19 через HTTP: «pdfa» с байтами обычного PDF --
    job failed profile_validation_failed; validations по rendition
    недоступны (rendition не существует -- честная граница, см.
    F-D9C3 в акте); failed-запись доказательства живёт в реестре по job."""
    from apps.api import document_jobs
    from apps.api.document_renditions import render_snapshot_pdf
    from scripts.doclog9cert.conftest import run_worker_once

    _snapshot_id, revision_id = _seed_revision_via_http(client)
    created = _create_profile(
        client, ADMIN_KEY, name="d9cert-fv", version_no=1, format="pdfa"
    )
    pid = created.json()["profile"]["profile_id"]
    snap = seed_snapshot()
    monkeypatch.setattr(
        document_jobs, "render_snapshot_pdfa",
        lambda *a, **kw: render_snapshot_pdf(snap),
    )
    resp = client.post(
        f"/v1/documentation/revisions/{revision_id}/renditions",
        json={"format": "pdfa", "org_profile_id": pid},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job"]["job_id"]
    run_worker_once()
    job_body = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
    assert job_body["state"] == "failed"
    assert job_body["error_code"] == "profile_validation_failed"
    # Ready-файла нет; validations по несуществующему rendition -- 404.
    assert not job_body.get("rendition_id")
    missing = client.get(
        "/v1/documentation/renditions/rend-absent/validations"
    )
    assert missing.status_code == 404
    # Но доказательство в durable-реестре есть (по job).
    records = profile_service().registry.list_validations_by_job(job_id)
    assert len(records) == 1 and records[0].result == "failed"
    assert records[0].rendition_id == "" and records[0].findings


# ══════════════════════════════════════════════════════════════════════
# Подпись: verify-signature маршрут
# ══════════════════════════════════════════════════════════════════════


def _signed_rendition(client: TestClient, monkeypatch, *,
                      with_key: bool = True):
    from scripts.doclog9cert.conftest import run_worker_once

    if with_key:
        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_VALUE)
    else:
        monkeypatch.delenv("CISSTAT_DOC_SIGN_KEY", raising=False)
    profile = make_profile(fmt="docx", sign_contents=True)
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", profile)
    return job, rendition


def test_a16_verify_signature_passed_tampered_not_signed(
    client: TestClient, monkeypatch
):
    monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_VALUE)
    profile = make_profile(fmt="docx", sign_contents=True)
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    cookie(client, SESSION_A)
    resp = client.post(
        f"/v1/documentation/renditions/{rendition.rendition_id}/verify-signature"
    )
    assert resp.status_code == 200
    verification = resp.json()["verification"]
    assert verification["result"] == "passed"
    assert verification["validator"] == "signature/1"
    # Порча МАНИФЕСТА (метаданных) в append-only реестре: новая запись с
    # подменённым content_sha256 -> mac_mismatch при неизменных байтах
    # (двухканальная привязка: метаданные тоже под MAC'ом).
    from apps.api.doc_profiles import ProfileValidationRecord

    registry = delivery().registry
    stored = registry.get_rendition(rendition.rendition_id)
    original = [
        v for v in profile_service().registry.list_validations(
            rendition.rendition_id)
        if v.validator == "signature/1"
    ][-1]
    tampered_manifest = dict(original.signature_manifest or {})
    tampered_manifest["content_sha256"] = "f" * 64
    profile_service().registry.append_validation(
        ProfileValidationRecord(
            validation_id="val-d9cert-tampered",
            rendition_id=rendition.rendition_id,
            job_id=original.job_id,
            run_id=original.run_id,
            profile_id=original.profile_id,
            profile_version_no=original.profile_version_no,
            format=original.format,
            validator="signature/1",
            result="passed",
            findings=[],
            signature_manifest=tampered_manifest,
        )
    )
    resp2 = client.post(
        f"/v1/documentation/renditions/{rendition.rendition_id}/verify-signature"
    )
    assert resp2.status_code == 200
    verification2 = resp2.json()["verification"]
    assert verification2["result"] == "failed"
    assert any(f.startswith("mac_mismatch") for f in verification2["findings"])
    assert stored.content_bytes  # байты не менялись -- порча только в метаданных
    # Несуществующий rendition -- uniform 404.
    resp3 = client.post(
        "/v1/documentation/renditions/rend-absent/verify-signature"
    )
    assert resp3.status_code == 404


def test_a17_verify_signature_not_signed(client: TestClient):
    profile = make_profile(fmt="docx", sign_contents=False)
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    cookie(client, SESSION_A)
    resp = client.post(
        f"/v1/documentation/renditions/{rendition.rendition_id}/verify-signature"
    )
    assert resp.status_code == 200
    body = resp.json()["verification"]
    assert body["result"] == "not_signed"
    assert body["validator"] == "signature/1"


def test_a18_verify_signature_purged_410(client: TestClient, monkeypatch):
    """Подписанный выпуск (без WORM) удаляется draft-retention --
    verify-signature честный 410 purged_artifact."""
    monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "30")
    monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_VALUE)
    from apps.api.document_jobs import JOB_READY, replace_dataclass

    snap = seed_snapshot()
    profile = make_profile(fmt="docx", sign_contents=True)  # БЕЗ worm_lock
    _document, revision = seed_document_revision(snap)
    job, rendition = render_with_profile(
        snap, "docx", profile, revision_id=revision.revision_id
    )
    assert job.state == JOB_READY, job.error_code
    # Состаривание и sweep (паритет repo-паттерна DOCLOG-6).
    from datetime import datetime, timedelta, timezone

    registry = delivery().registry
    stored = registry.get_rendition(rendition.rendition_id)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    registry.update_rendition(replace_dataclass(stored, created_at=old))
    cookie(client, SESSION_A)
    sweep = client.post(
        f"/v1/documentation/runs/{snap.research_run_id}/retention/sweep"
    )
    assert sweep.status_code == 200
    purged = registry.get_rendition(rendition.rendition_id)
    assert purged.state == "purged"
    resp = client.post(
        f"/v1/documentation/renditions/{rendition.rendition_id}/verify-signature"
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "purged_artifact"


def test_a19_worm_blocks_retention_purge(client: TestClient, monkeypatch):
    """WORM-профиль: draft-retention НЕ удаляет выпуск (hold на
    документе); report честен."""
    monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "30")
    from apps.api.document_jobs import JOB_READY, replace_dataclass
    from datetime import datetime, timedelta, timezone

    snap = seed_snapshot()
    profile = make_profile(fmt="docx", worm_lock=True)
    _document, revision = seed_document_revision(snap)
    job, rendition = render_with_profile(
        snap, "docx", profile, revision_id=revision.revision_id
    )
    assert job.state == JOB_READY, job.error_code
    registry = delivery().registry
    stored = registry.get_rendition(rendition.rendition_id)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    registry.update_rendition(replace_dataclass(stored, created_at=old))
    cookie(client, SESSION_A)
    sweep = client.post(
        f"/v1/documentation/runs/{snap.research_run_id}/retention/sweep"
    )
    assert sweep.status_code == 200
    report = sweep.json()["report"]
    assert report.get("purged_renditions", 0) == 0
    after = registry.get_rendition(rendition.rendition_id)
    assert after.state == "ready"  # hold защитил выпуск


def test_a20_mandatory_audit_broken_sink_http(client: TestClient):
    """Fail-closed через HTTP: ломучий sink на mandatory-аудите создания
    профиля. ПИН F-D9C2 (акт §5): операция прерывается (500, маппинг
    503 mandatory_audit_unavailable ОТСУТСТВУЕТ в routers/doc_profiles.py
    -- паритет documentation.py:306 нарушен) и профиль ОСТАЁТСЯ
    созданным (реестр пишется до аудита). После FIX -- ожидать 503 и
    отсутствие профиля."""
    from apps.api import security_audit
    from apps.api.main import app

    from scripts.doclog9cert.conftest import BrokenAuditSink

    security_audit.set_audit_sink_for_testing(BrokenAuditSink())
    try:
        with TestClient(app, raise_server_exceptions=False) as raw_client:
            resp = raw_client.post(
                "/v1/documentation/org-profiles",
                json={"name": "d9cert-fc-http", "version_no": 1,
                      "format": "pdfa"},
                headers=_headers(ADMIN_KEY),
            )
            assert resp.status_code == 500  # ПИН: не 503 mandatory_audit_unavailable
            assert D9C_SENTINEL not in resp.text
    finally:
        security_audit.set_audit_sink_for_testing(None)
    dup = profile_service().registry.find_duplicate("d9cert-fc-http", 1)
    assert dup is not None  # ПИН: защищённое действие выполнено


def test_a21_standard_audit_broken_sink_does_not_break_rendition(
    client: TestClient, monkeypatch
):
    """§8/AC11: rendition_validated/anchored -- standard: ломучий sink
    НЕ ломает выпуск (запись пропущена, выпуск ready)."""
    from apps.api import security_audit
    from scripts.doclog9cert.conftest import run_worker_once

    class BrokenStandardSink(security_audit.MemoryAuditSink):
        def append(self, record):
            if record.get("action") in ("rendition_validated",
                                        "rendition_anchored"):
                raise RuntimeError("standard sink down")
            return super().append(record)

    profile = make_profile(fmt="docx", anchor_registry=True)
    snap = seed_snapshot()
    security_audit.set_audit_sink_for_testing(BrokenStandardSink())
    try:
        job, rendition = render_with_profile(snap, "docx", profile)
        from apps.api.document_jobs import JOB_READY

        assert job.state == JOB_READY, job.error_code  # выпуск НЕ сломан
    finally:
        security_audit.set_audit_sink_for_testing(None)
    # Доказательства в реестре профилей не зависят от audit-sink.
    records = profile_service().registry.list_validations(
        rendition.rendition_id
    )
    assert records and records[0].result == "passed"


def test_a22_error_hygiene_no_sentinel_no_traceback(client: TestClient):
    """Гигиена §17: ошибочные ответы без сентинела/traceback/postgres://."""
    probes = [
        ("get", "/v1/documentation/org-profiles", None),
        ("post", "/v1/documentation/org-profiles",
         {"name": "d9cert-h", "version_no": 0, "format": "pdfa"}),
        ("post", "/v1/documentation/org-profiles/prof-x/retire", None),
        ("get", "/v1/documentation/renditions/rend-x/validations", None),
        ("post", "/v1/documentation/renditions/rend-x/verify-signature", None),
    ]
    for method, path, payload in probes:
        resp = _request(client, method, path, payload)
        text = resp.text
        assert D9C_SENTINEL not in text
        assert "Traceback" not in text
        assert "postgres://" not in text


def test_a23_worker_rendition_metadata_roundtrip(client: TestClient):
    """Метаданные org_profile_id переживают реестровый roundtrip
    (get_rendition/registry list) и попадают в HTTP-выдачу jobs."""
    from scripts.doclog9cert.conftest import run_worker_once

    profile = make_profile(fmt="pdfa")
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "pdfa", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    cookie(client, SESSION_A)
    body = client.get(f"/v1/documentation/jobs/{job.job_id}").json()["job"]
    assert body["org_profile_id"] == profile.profile_id
    listed = delivery().registry.list_renditions(snap.snapshot_id)
    assert any(r.org_profile_id == profile.profile_id for r in listed)


def test_a24_anon_and_foreign_key_uniform_on_rendition_routes(
    client: TestClient,
):
    """Матрица доступа renditions-маршрутов: аноним и чужой ключ --
    404; свой ключ/cookie -- 200 (read)."""
    profile = make_profile(fmt="docx")
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    anon = client.get(
        f"/v1/documentation/renditions/{rendition.rendition_id}/validations"
    )
    assert anon.status_code == 404
    foreign = client.get(
        f"/v1/documentation/renditions/{rendition.rendition_id}/validations",
        headers=_headers(OTHER_KEY),
    )
    assert foreign.status_code == 404
    cookie(client, SESSION_A)
    own = client.get(
        f"/v1/documentation/renditions/{rendition.rendition_id}/validations"
    )
    assert own.status_code == 200
