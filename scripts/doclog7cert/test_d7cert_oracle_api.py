# scripts/doclog7cert/test_d7cert_oracle_api.py
"""DOCLOG-7-CERT: API-оракулы на СВОИХ данных (a01–a34).

Полный HTTP-контур /v1/logs на собственных ключах/tenant'ах/данных:
аутентификация (401), единый отказ (403 + authz_denied в audit),
саможурналирование (ровно одна запись, без рекурсии), чтение трёх
потоков по whitelist-фильтрам, гранты (жизненный цикл, mandatory
fail-closed AC11), диагностический пакет (AC10-сентинелы, download
тройка, AC05-tripwire), retention-horizon (§16.1), uniform-ошибки.

Зафиксированные наблюдения сертификатора (см. docs/cert_doclog7):
- N-D7C4: query-параметры вне collect-каталога роутера тихо
  игнорируются (200, без фильтрации) -- whitelist применён на уровне
  collect-списка, а не 422;
- F4: члены пакета <stream>.jsonl при >1 записи склеены без
  newline-разделителя (to_jsonl без \\n + "".join) -- не валидный
  JSONL для независимого получателя (пин a34).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from .conftest import (
    ADMIN_KEY,
    ADMIN_SUBJECT,
    MGR_KEY,
    MGR_SUBJECT,
    RO_KEY,
    RO_SUBJECT,
    RUN_A,
    RUN_B,
    SCOPED_KEY,
    SCOPED_SUBJECT,
    SECRET_SENTINEL,
    SUPPORT_KEY,
    SUPPORT_SUBJECT,
    TENANT_CORE,
    TENANT_OTHER,
    TENANT_ZETA,
    ZETA_KEY,
    audit_count,
    create_grant_via_api,
    iso,
    seed_audit,
    seed_delivery,
    seed_delivery_chain,
    seed_telemetry,
)
from apps.api import admin_logs, security_audit


_LOG_ROUTES = (
    "/v1/logs/access",
    "/v1/logs/telemetry",
    "/v1/logs/audit",
    "/v1/logs/delivery",
)


def _decode_concatenated_jsonl(raw: bytes) -> list[dict]:
    """Разбор склеенного члена пакета (фактический формат F4): объекты
    идут подряд без newline-разделителя."""
    decoder = json.JSONDecoder()
    text = raw.decode("utf-8")
    records: list[dict] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " \n\r\t":
            index += 1
        if index >= len(text):
            break
        value, end = decoder.raw_decode(text, index)
        records.append(value)
        index = end
    return records


# ═══════════════ 1. Аутентификация/отказ (§15, uniform) ═══════════════


def test_a01_401_missing_and_unknown_key(client: TestClient):
    for route in _LOG_ROUTES:
        response = client.get(route)  # без ключа
        assert response.status_code == 401, route
    response = client.get("/v1/logs/telemetry",
                          headers={"X-API-Key": "d7c-unknown-key-9999"})
    assert response.status_code == 401
    # 401 сам журналируется как authn_denied (псевдоним, не ключ)
    assert audit_count("authn_denied") >= 1


def test_a02_403_uniform_body_and_authz_denied_audited(client: TestClient):
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    before = audit_count("authz_denied")
    for route in _LOG_ROUTES[1:]:
        response = client.get(route)
        assert response.status_code == 403, route
        body = response.json()
        assert body["code"] == "logs_access_denied"
        assert body["message"]
        assert body["request_id"]
    response = client.post("/v1/logs/export", json={})
    assert response.status_code == 403
    assert response.json()["code"] == "logs_access_denied"
    response = client.get("/v1/logs/grants")
    assert response.status_code == 403
    # каждый отказ сам в durable audit (§14.2 «все действия учитываются»)
    # телеметрия/аудит/доставка + экспорт + гранты = ровно 5 отказов
    after = audit_count("authz_denied")
    assert after >= before + 5
    record = next(
        r for r in security_audit.audit_records()
        if r.get("action") == "authz_denied"
    )
    assert record["resource_kind"] == "admin_logs"
    # значение ключа НЕ дисклоужено (AC10)
    assert ADMIN_KEY.encode() not in json.dumps(
        security_audit.audit_records()).encode()


def test_a03_access_summary_honest_and_not_audited(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    before = audit_count("audit_log_accessed")
    response = client.get("/v1/logs/access")
    assert response.status_code == 200
    body = response.json()
    assert body["principal"]["subject_id"] == ADMIN_SUBJECT
    assert body["access"] == {
        "telemetry": True, "audit": True, "delivery": True,
        "export": True, "grants_management": True,
        "scope": "unrestricted",
    }
    # GET /access -- мета-доступ, не журналируется (решение зафиксировано)
    assert audit_count("audit_log_accessed") == before
    # scoped ключ реестра без logs.export -- честный флаг
    client.headers.update({"X-API-Key": RO_KEY})
    body2 = client.get("/v1/logs/access").json()
    assert body2["access"]["telemetry"] is True
    assert body2["access"]["export"] is False
    assert body2["access"]["grants_management"] is False


# ═══════════════ 2. Чтение telemetry (свои данные) ════════════════════


def test_a04_admin_reads_own_seeded_records_and_meta(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=3)
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["stream"] == "telemetry"
    assert body["meta"]["count"] == 3
    assert body["meta"]["order"] == "occurred_at DESC, id DESC"
    assert body["meta"]["effective_scope"] == "unrestricted"
    assert body["meta"]["limit"] == 50
    assert body["meta"]["retention_horizon_days"] == 30
    assert body["next_cursor"] is None
    assert len(body["records"]) == 3
    names = [r["event_name"] for r in body["records"]]
    assert names == ["d7c.seed.event"] * 3
    # порядок DESC по (occurred_at, event_id)
    stamps = [r["occurred_at"] for r in body["records"]]
    assert stamps == sorted(stamps, reverse=True)
    # свои данные честны (кириллица, атрибуты)
    assert body["records"][0]["attributes"]["component"] == "d7c-seed-2"


def test_a05_self_journaling_exactly_one_no_recursion(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    assert audit_count("audit_log_accessed", "telemetry") == 0
    client.get("/v1/logs/telemetry")
    assert audit_count("audit_log_accessed", "telemetry") == 1
    client.get("/v1/logs/telemetry")
    assert audit_count("audit_log_accessed", "telemetry") == 2
    # чтение audit-потока тоже добавляет ровно одну (без рекурсии)
    client.get("/v1/logs/audit")
    assert audit_count("audit_log_accessed", "audit") == 1
    client.get("/v1/logs/audit")
    assert audit_count("audit_log_accessed", "audit") == 2


def test_a06_self_journaling_failure_does_not_break_read(client: TestClient):
    """AC11-инвариант: сбой standard-audit НЕ ломает чтение потока."""
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=1)

    class _Failing:
        def append(self, record):
            raise RuntimeError("d7c audit outage")

        def readiness_probe(self):
            return {"ok": False}

    security_audit.set_audit_sink_for_testing(_Failing())
    try:
        response = client.get("/v1/logs/telemetry",
                              params={"event_name": "d7c.seed.event"})
        assert response.status_code == 200  # чтение НЕ сломано
        assert response.json()["meta"]["count"] == 1
    finally:
        security_audit.reset_audit_for_testing()


def test_a07_telemetry_filters_whitelist_exact(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=2, severity="info", outcome="success")
    seed_telemetry(count=1, event_name="d7c.seed.error", severity="error",
                   outcome="failure", request_id="req-d7c-err")
    # severity нормализована в каноническую форму (INFO/ERROR)
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event",
                                  "severity": "INFO"})
    assert response.status_code == 200
    assert response.json()["meta"]["count"] == 2
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.error",
                                  "severity": "ERROR"})
    assert response.json()["meta"]["count"] == 1
    assert response.json()["records"][0]["outcome"] == "failure"
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.error"})
    assert response.json()["meta"]["count"] == 1
    response = client.get("/v1/logs/telemetry",
                          params={"request_id": "req-d7c-err"})
    assert response.json()["meta"]["count"] == 1
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event",
                                  "outcome": "success"})
    assert response.json()["meta"]["count"] == 2
    # комбинированный фильтр
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.error",
                                  "severity": "ERROR", "outcome": "failure"})
    assert response.json()["meta"]["count"] == 1
    # НАХОДКА F5 (пин фактического поведения): run_id/tenant_id
    # whitelist-фильтры НЕ применяются на memory-бекенде (только в
    # PG-пути) -- список НЕ сужается; паритет Memory/Postgres нарушен
    # (урок F-D2C1). Утечки нет (narrowing по гранту отдельный), но
    # контракт фильтра не выполнен на дефолтном бекенде.
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event",
                                  "run_id": RUN_B})
    assert response.json()["meta"]["count"] == 2  # F5: фильтр проигнорирован
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event",
                                  "tenant_id": TENANT_ZETA})
    assert response.json()["meta"]["count"] == 2  # F5: фильтр проигнорирован
    # N-D7C4 (пин фактического поведения): параметр вне collect-каталога
    # роутера тихо игнорируется -- 200 и БЕЗ фильтрации (whitelist
    # применяется составом collect-списка, а не 422)
    total = client.get("/v1/logs/telemetry",
                       params={"event_name": "d7c.seed.event"}).json()["meta"]["count"]
    response = client.get("/v1/logs/telemetry",
                          params={"free_text": "1=1; DROP TABLE"})
    assert response.status_code == 200
    assert response.json()["meta"]["count"] >= total
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event",
                                  "action": "grant_created"})
    assert response.status_code == 200  # audit-поле на telemetry проигнорировано


def test_a08_window_validation_and_honest_default(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=1)
    params = {"event_name": "d7c.seed.event"}
    response = client.get("/v1/logs/telemetry", params=params)
    assert response.json()["meta"]["count"] == 1  # сид от T0 = now-2h
    old = datetime.now(timezone.utc) - timedelta(hours=40)
    seed_telemetry(count=1, start=old, event_name="d7c.seed.old")
    response = client.get("/v1/logs/telemetry", params=params)
    assert response.json()["meta"]["count"] == 1  # старый невидим (честно)
    # явное окно видит старый
    window = {"event_name": "d7c.seed.old",
              "from": iso(old - timedelta(hours=1)),
              "to": iso(old + timedelta(hours=1))}
    response = client.get("/v1/logs/telemetry", params=window)
    assert response.json()["meta"]["count"] == 1
    # окно > 31 дня -- 422; from >= to -- 422
    now = datetime.now(timezone.utc)
    response = client.get("/v1/logs/telemetry", params={
        "from": iso(now - timedelta(days=32)), "to": iso(now)})
    assert response.status_code == 422
    response = client.get("/v1/logs/telemetry", params={
        "from": iso(now), "to": iso(now)})
    assert response.status_code == 422
    # некорректная дата -- 422
    response = client.get("/v1/logs/telemetry", params={"from": "не-дата"})
    assert response.status_code == 422


def test_a09_limit_and_cursor_pagination_no_loss_no_dup(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=5, message_prefix="страница d7c")
    # лимит 201 -- 422; 0 -- 422; "abc" -- 422
    for bad in ("201", "0", "-3", "abc"):
        response = client.get("/v1/logs/telemetry", params={"limit": bad})
        assert response.status_code == 422, bad
    # постраничный обход: 5 записей по 2 -- без потерь и дублей
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while pages < 10:
        params = {"limit": "2", "event_name": "d7c.seed.event"}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/v1/logs/telemetry", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(r["event_id"] for r in body["records"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5
    # мусорный cursor -- 422 (fail-closed)
    response = client.get("/v1/logs/telemetry", params={"cursor": "!!!"})
    assert response.status_code == 422
    response = client.get("/v1/logs/telemetry", params={"cursor": "e30"})
    assert response.status_code == 422  # "{}" -- без ключей t/id
    # курсор за пределами выборки -- честная пустая страница
    import base64

    far = base64.urlsafe_b64encode(json.dumps(
        {"t": "1970-01-01T00:00:00+00:00", "id": "x"},
    ).encode()).decode()
    response = client.get("/v1/logs/telemetry", params={"cursor": far})
    assert response.status_code == 200
    assert response.json()["records"] == []


def test_a10_retention_note_honest_reporting(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    # telemetry: окно, начинающееся старше 30 дней -- retention_note
    now = datetime.now(timezone.utc)
    response = client.get("/v1/logs/telemetry", params={
        "from": iso(now - timedelta(days=30, hours=1)), "to": iso(now)})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["retention_horizon_days"] == 30
    assert "retention_note" in meta
    # audit: окно старше 365 дней -- note + horizon 365
    response = client.get("/v1/logs/audit", params={
        "from": iso(now - timedelta(days=400)),
        "to": iso(now - timedelta(days=380))})
    meta = response.json()["meta"]
    assert meta["retention_horizon_days"] == 365
    assert "retention_note" in meta
    # delivery: горизонт отсутствует (явный None), пометки нет
    response = client.get("/v1/logs/delivery")
    meta = response.json()["meta"]
    assert meta["retention_horizon_days"] is None
    assert "retention_note" not in meta


# ═══════════════ 3. Эффективный доступ: scopes/grants narrowing ═══════


def test_a11_registry_scoped_key_reads_and_meta(client: TestClient):
    client.headers.update({"X-API-Key": SCOPED_KEY})
    seed_telemetry(count=1)
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event"})
    assert response.status_code == 200
    assert response.json()["meta"]["count"] == 1
    # audit.read тоже есть
    response = client.get("/v1/logs/audit")
    assert response.status_code == 200
    # N-наблюдение сертификатора (N-D7C2): скоуп реестра БЕЗ гранта
    # не несёт tenant-границы (boundary дают только grants); meta честно
    # показывает "unrestricted" -- поведение закреплено как наблюдение.
    assert response.json()["meta"]["effective_scope"] == "unrestricted"


def test_a12_grant_narrows_to_tenant_and_meta_reveals(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                         tenant_id=TENANT_CORE, scopes=["logs.read"])
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    seed_telemetry(count=2)  # CORE
    seed_telemetry(count=1, tenant_id=TENANT_ZETA, run_id=RUN_B,
                   event_name="d7c.seed.zeta")
    response = client.get("/v1/logs/telemetry",
                          params={"event_name": "d7c.seed.event"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 2  # zeta-запись НЕ выдана (§19)
    assert all(r["tenant_id"] == TENANT_CORE for r in body["records"])
    assert body["meta"]["effective_scope"] == {
        "tenants": [TENANT_CORE], "runs": []}
    # запись без tenant в скоуп-режиме -- fail-closed (не выдаётся)
    seed_telemetry(count=1, tenant_id=None, event_name="d7c.seed.blank")
    body = client.get("/v1/logs/telemetry",
                      params={"event_name": "d7c.seed.event"}).json()
    assert body["meta"]["count"] == 2


def test_a13_explicit_filter_outside_grant_403_not_empty_list(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                         tenant_id=TENANT_CORE, run_id=RUN_A,
                         scopes=["logs.read"])
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    # явный tenant вне границы -- 403 (не пустой список)
    response = client.get("/v1/logs/telemetry",
                          params={"tenant_id": TENANT_ZETA})
    assert response.status_code == 403
    assert response.json()["code"] == "logs_access_denied"
    # явный run вне границы -- 403
    response = client.get("/v1/logs/telemetry", params={"run_id": RUN_B})
    assert response.status_code == 403
    # внутри границы -- 200
    response = client.get("/v1/logs/telemetry", params={
        "tenant_id": TENANT_CORE, "run_id": RUN_A})
    assert response.status_code == 200
    # tenant-wide грант: run вне границы НЕ классифицируется (граница
    # run открыта) -- сужение с честной meta (N-D7C1)
    client.headers.update({"X-API-Key": ADMIN_KEY})
    create_grant_via_api(client, subject_id=SCOPED_SUBJECT,
                         tenant_id=TENANT_CORE, run_id=None,
                         scopes=["logs.read"], ticket="d7c-ticket-wide")
    client.headers.update({"X-API-Key": SCOPED_KEY})
    response = client.get("/v1/logs/telemetry", params={"run_id": RUN_B})
    assert response.status_code == 200  # сужение, не 403 (N-D7C1)
    assert response.json()["meta"]["effective_scope"] == {
        "tenants": [TENANT_CORE], "runs": []}


def test_a14_grant_grants_access_only_within_boundary(client: TestClient):
    # до гранта -- 403
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    assert client.get("/v1/logs/telemetry").status_code == 403
    # admin выдаёт грант -- доступ появляется
    client.headers.update({"X-API-Key": ADMIN_KEY})
    grant = create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                                 tenant_id=TENANT_CORE, scopes=["logs.read"])
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    response = client.get("/v1/logs/telemetry")
    assert response.status_code == 200
    # отзыв -- доступ исчезает (append-only revocation)
    client.headers.update({"X-API-Key": ADMIN_KEY})
    revoke = client.post(f"/v1/logs/grants/{grant['grant_id']}/revoke",
                         json={"reason": "d7c работа завершена"})
    assert revoke.status_code == 200
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    assert client.get("/v1/logs/telemetry").status_code == 403
    # knowledge of run_id не есть право (AC06-дух): чужой tenant+run
    client.headers.update({"X-API-Key": ZETA_KEY})
    assert client.get("/v1/logs/telemetry").status_code == 403


def test_a15_expired_grant_fail_closed(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    from apps.api.admin_logs import (
        get_support_grant_registry,
        replace_grant_record,
    )

    grant = create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                                 tenant_id=TENANT_CORE, scopes=["logs.read"])
    registry = get_support_grant_registry()
    record = registry.get_grant(grant["grant_id"])
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    registry.update_grant(replace_grant_record(record, expires_at=iso(past)))
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    assert client.get("/v1/logs/telemetry").status_code == 403  # истёк -- отказ


# ═══════════════ 4. Поток audit (свои данные) ═════════════════════════


def test_a16_audit_stream_filters_and_self_visibility(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_audit(action="run_access_allowed", decision="allowed")
    seed_audit(action="authz_denied", decision="denied",
               tenant_id=TENANT_ZETA, run_id=RUN_B)
    response = client.get("/v1/logs/audit", params={"decision": "denied"})
    assert response.status_code == 200
    records = [r for r in response.json()["records"]
               if r.get("resource_kind") == "research_run"]
    assert len(records) == 1
    assert records[0]["action"] == "authz_denied"
    assert records[0]["tenant_id"] == TENANT_ZETA
    response = client.get("/v1/logs/audit",
                          params={"action": "run_access_allowed"})
    actions = {r["action"] for r in response.json()["records"]}
    assert actions == {"run_access_allowed"}
    # самодоступность: audit-чтение видно следующему audit-чтению
    response = client.get("/v1/logs/audit")
    actions = {r["action"] for r in response.json()["records"]}
    assert "audit_log_accessed" in actions
    assert "run_access_allowed" in actions
    # N-D7C4: severity -- не audit-поле, параметр тихо проигнорирован
    response = client.get("/v1/logs/audit", params={"severity": "INFO"})
    assert response.status_code == 200


# ═══════════════ 5. Поток delivery (metadata only) ════════════════════


_DELIVERY_KEYS = {
    "job_id", "run_id", "tenant_id", "snapshot_id", "format",
    "redaction_profile", "state", "error_code", "attempt",
    "created_at", "updated_at", "revision_id", "rendition_id",
    "document_id", "kind_code",
}


def test_a17_delivery_metadata_only_no_content_bytes(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    chain = seed_delivery_chain()
    seed_delivery(state="failed")
    response = client.get("/v1/logs/delivery")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 2
    row = next(r for r in body["records"] if r["job_id"] == chain["job_id"])
    assert set(row.keys()) == _DELIVERY_KEYS  # ровно whitelist-проекция
    assert row["state"] == "ready"
    assert row["format"] == "pdf"
    assert row["kind_code"] == "D02"  # join до документа честен
    assert row["document_id"] == chain["document_id"]
    assert row["revision_id"] == chain["revision_id"]
    assert row["rendition_id"] == chain["rendition_id"]
    # НИКАКИХ контентных байтов в потоке (§14.2 дословно)
    assert "content_bytes" not in json.dumps(body)
    assert "payload" not in json.dumps(body)
    failed = next(r for r in body["records"] if r["state"] == "failed")
    assert failed["error_code"] == "render_error"
    assert failed["attempt"] == 2


def test_a18_delivery_filters(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_delivery(state="ready", format_="pdf")
    seed_delivery(state="failed", format_="pdf")
    response = client.get("/v1/logs/delivery", params={"state": "failed"})
    assert response.json()["meta"]["count"] == 1
    response = client.get("/v1/logs/delivery", params={"format": "pdf"})
    assert response.json()["meta"]["count"] == 2
    response = client.get("/v1/logs/delivery", params={"run_id": RUN_B})
    assert response.json()["meta"]["count"] == 0
    # N-D7C4: severity -- не delivery-поле, тихо проигнорировано
    response = client.get("/v1/logs/delivery", params={"severity": "INFO"})
    assert response.status_code == 200
    assert response.json()["meta"]["count"] == 2


# ═══════════════ 6. Гранты: жизненный цикл и AC11 ═════════════════════


def test_a19_grant_lifecycle_api_fields_and_dedup(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    before_created = audit_count("grant_created")
    grant = create_grant_via_api(
        client, subject_id=SUPPORT_SUBJECT, tenant_id=TENANT_CORE,
        run_id=RUN_A, scopes=["logs.read", "logs.read", "logs.export"],
        ttl_hours=24)
    assert grant["schema_version"] == "doclog.support_grant/1"
    assert grant["grant_id"].startswith("d7grant-")
    assert grant["scopes"] == ["logs.read", "logs.export"]  # дедуп сохранён
    assert grant["ticket"] == "d7c-ticket-42"
    assert grant["subject_id"] == SUPPORT_SUBJECT
    assert grant["tenant_id"] == TENANT_CORE
    assert grant["run_id"] == RUN_A
    assert grant["created_by"] == ADMIN_SUBJECT
    created = datetime.fromisoformat(grant["created_at"])
    expires = datetime.fromisoformat(grant["expires_at"])
    assert (expires - created) == timedelta(hours=24)
    assert grant["revoked_at"] is None
    # mandatory audit grant_created записан
    assert audit_count("grant_created") == before_created + 1
    record = next(r for r in security_audit.audit_records()
                  if r.get("action") == "grant_created")
    assert record["decision"] == "allowed"
    assert record["actor_subject"] == ADMIN_SUBJECT  # не значение ключа
    assert record["resource_kind"] == "support_grant"
    assert record["resource_id"] == grant["grant_id"]
    assert record["policy_basis"] == "ticket:d7c-ticket-42"
    assert record["details"]["grantee_subject"] == SUPPORT_SUBJECT
    assert record["details"]["ttl_hours"] == 24.0
    # список грантов (админ)
    client.headers.update({"X-API-Key": ADMIN_KEY})
    listed = client.get("/v1/logs/grants").json()["grants"]
    assert any(g["grant_id"] == grant["grant_id"] for g in listed)


def test_a20_grant_validation_422_catalog(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    ok = {
        "ticket": "d7c",
        "subject_id": SUPPORT_SUBJECT,
        "tenant_id": TENANT_CORE,
        "scopes": ["logs.read"],
        "ttl_hours": 24,
    }
    bad_bodies = [
        {**ok, "ticket": ""},
        {**ok, "subject_id": ""},
        {**ok, "subject_id": "subj-подделка!"},
        {**ok, "tenant_id": ""},
        {**ok, "tenant_id": "НЕ СЛАГ"},
        {**ok, "scopes": []},
        {**ok, "scopes": ["artifact.data.read"]},   # данные НЕ грантуются
        {**ok, "scopes": ["documentation.publish"]},
        {**ok, "scopes": ["logs.admin"]},
        {**ok, "ttl_hours": 0},
        {**ok, "ttl_hours": 169},
        {**ok, "ttl_hours": "бесконечность"},
    ]
    for body in bad_bodies:
        response = client.post("/v1/logs/grants", json=body)
        assert response.status_code == 422, body
        assert response.json()["code"] == "logs_validation_error"
    # НАХОДКА F2 (пин): NaN TTL -- 500 (unhandled ValueError), не 422
    nan_body = json.dumps({**ok, "ttl_hours": float("nan")})  # литерал NaN
    from apps.api.main import app as _app

    with TestClient(_app, raise_server_exceptions=False) as raw_client:
        raw_client.headers.update({"X-API-Key": ADMIN_KEY})
        response = raw_client.post(
            "/v1/logs/grants", content=nan_body,
            headers={"content-type": "application/json"})
        assert response.status_code == 500  # закреплено как находка F2


def test_a21_grant_create_mandatory_fail_closed(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    from apps.api import security_audit as sa

    class _Failing(sa.AuditSink):
        def append(self, record):
            raise RuntimeError("d7c audit outage")

        def readiness_probe(self):
            return {"ok": False, "backend": "memory"}

    security_audit.set_audit_sink_for_testing(_Failing())
    try:
        response = client.post("/v1/logs/grants", json={
            "ticket": "d7c-fail", "purpose": "d7c",
            "subject_id": SUPPORT_SUBJECT, "tenant_id": TENANT_CORE,
            "scopes": ["logs.read"], "ttl_hours": 1})
        assert response.status_code == 503
        assert response.json()["code"] == "audit_unavailable"
        # a-оракул: реестр ПУСТ -- грант не создан (fail-closed §14.1)
        from apps.api.admin_logs import SupportGrantService

        assert SupportGrantService().registry.list_grants() == []
    finally:
        security_audit.reset_audit_for_testing()
    # восстановление: тот же запрос после починки -- 201
    response = client.post("/v1/logs/grants", json={
        "ticket": "d7c-fail", "purpose": "d7c",
        "subject_id": SUPPORT_SUBJECT, "tenant_id": TENANT_CORE,
        "scopes": ["logs.read"], "ttl_hours": 1})
    assert response.status_code == 201


def test_a22_grant_revoke_mandatory_fail_closed_and_idempotent(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    grant = create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                                 tenant_id=TENANT_CORE, scopes=["logs.read"])
    # ломаем sink -- отзыв отклонён, состояние НЕ изменилось
    from apps.api import security_audit as sa

    class _Failing(sa.AuditSink):
        def append(self, record):
            raise RuntimeError("d7c audit outage")

        def readiness_probe(self):
            return {"ok": False, "backend": "memory"}

    security_audit.set_audit_sink_for_testing(_Failing())
    try:
        response = client.post(
            f"/v1/logs/grants/{grant['grant_id']}/revoke",
            json={"reason": "d7c"})
        assert response.status_code == 503
        assert response.json()["code"] == "audit_unavailable"
        from apps.api.admin_logs import SupportGrantService

        record = SupportGrantService().registry.get_grant(grant["grant_id"])
        assert record.revoked_at is None  # отзыв НЕ произошёл
    finally:
        security_audit.reset_audit_for_testing()
    # починка -- отзыв выполняется
    response = client.post(f"/v1/logs/grants/{grant['grant_id']}/revoke",
                           json={"reason": "d7c работа завершена"})
    assert response.status_code == 200
    body = response.json()
    assert body["revoked_at"] is not None
    assert body["revoked_by"] == ADMIN_SUBJECT
    assert body["revoke_reason"] == "d7c работа завершена"
    # идемпотентный повторный отзыв: 200, БЕЗ второй grant_revoked записи
    before = audit_count("grant_revoked")
    assert before == 1
    response2 = client.post(f"/v1/logs/grants/{grant['grant_id']}/revoke",
                            json={"reason": "повтор d7c"})
    assert response2.status_code == 200
    assert audit_count("grant_revoked") == before  # ровно одна запись
    # неизвестный грант -- uniform 404
    response3 = client.post("/v1/logs/grants/d7grant-нет/revoke", json={})
    assert response3.status_code == 404
    assert response3.json()["code"] == "grant_not_found"
    assert response3.json()["request_id"]


def test_a23_grants_listing_include_revoked(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    grant = create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                                 tenant_id=TENANT_CORE, scopes=["logs.read"])
    client.post(f"/v1/logs/grants/{grant['grant_id']}/revoke", json={})
    listed = client.get("/v1/logs/grants").json()["grants"]
    assert all(g["grant_id"] != grant["grant_id"] for g in listed)
    listed_all = client.get(
        "/v1/logs/grants", params={"include_revoked": "true"},
    ).json()["grants"]
    assert any(g["grant_id"] == grant["grant_id"] and g["revoked_at"]
               for g in listed_all)


def test_a24_grant_management_requires_scope_not_admin_role_only(client: TestClient):
    # НЕ-админ с support.grant-скоупом -- менеджмент доступен (§15 каталог)
    client.headers.update({"X-API-Key": MGR_KEY})
    response = client.post("/v1/logs/grants", json={
        "ticket": "d7c-mgr", "purpose": "поддержка d7c",
        "subject_id": SCOPED_SUBJECT, "tenant_id": TENANT_CORE,
        "scopes": ["audit.read"], "ttl_hours": 2})
    assert response.status_code == 201
    # при этом потоки ему НЕ открыты (нет logs.read/audit.read)
    assert client.get("/v1/logs/telemetry").status_code == 403
    assert client.get("/v1/logs/audit").status_code == 403


# ═══════════════ 7. Диагностический пакет (AC10/AC19) ════════════════


def _export_bundle(client: TestClient, **body) -> dict:
    response = client.post("/v1/logs/export", json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    return {"bytes": response.content, "disposition": disposition}


def test_a25_bundle_ac10_sentinels_absent(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=1)
    seed_audit()
    seed_delivery()
    bundle = _export_bundle(client)
    raw = bundle["bytes"]
    # AC10: ключ/env/DSN/cookie НИКОГДА не в байтах пакета
    assert ADMIN_KEY.encode() not in raw
    assert SUPPORT_KEY.encode() not in raw
    assert SCOPED_KEY.encode() not in raw
    assert SECRET_SENTINEL.encode() not in raw
    assert b"postgres://" not in raw
    assert b"DATABASE_URL" not in raw
    filename = bundle["disposition"].split("filename=")[1].strip('"')
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert set(zf.namelist()) == {
            "manifest.json", "telemetry.jsonl", "audit.jsonl", "delivery.jsonl"}
        manifest = json.loads(zf.read("manifest.json"))
        for name in ("telemetry.jsonl", "audit.jsonl", "delivery.jsonl"):
            for record in _decode_concatenated_jsonl(zf.read(name)):
                assert not any(
                    key in record for key in ("content_bytes", "payload"))
    assert manifest["schema_version"] == "doclog.diagbundle/1"
    assert manifest["bundle_id"] == filename[:-4]
    assert len(manifest["excluded"]) == 5
    assert manifest["counts"]["telemetry.jsonl"] >= 1
    # N-D7C5 (пин): обязательная самозапись экспорта (audit_log_accessed,
    # resource_id=diagnostic_bundle) НЕ попадает в собственный пакет:
    # to-граница окна фиксируется в parse_query ДО записи mandatory-
    # записи в роутере. Учёт состоялся в durable-журнале (виден
    # последующим чтениям/экспортам -- см. a26) -- «все действия
    # учитываются» выполняется, но пакет самозаписи не содержит.
    assert manifest["counts"]["audit.jsonl"] == 1  # только свой сид
    assert manifest["counts"]["delivery.jsonl"] == 1
    assert manifest["effective_scope"] == "unrestricted"
    # manifest не несёт значений DSN/env (имена флагов вида
    # "dsn_configured"/"environment" допустимы -- safe-подмножество)
    manifest_text = json.dumps(manifest)
    assert "postgres://" not in manifest_text
    assert "DATABASE_URL" not in manifest_text
    assert SECRET_SENTINEL not in manifest_text


def test_a26_bundle_self_audit_and_download_triple(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    before_acc = audit_count("audit_log_accessed", "diagnostic_bundle")
    before_dl = audit_count("download_requested")
    before_start = audit_count("response_stream_started")
    before_fin = audit_count("response_stream_finished")
    _export_bundle(client)
    assert audit_count("audit_log_accessed", "diagnostic_bundle") == before_acc + 1
    assert audit_count("download_requested") == before_dl + 1
    assert audit_count("response_stream_started") == before_start + 1
    assert audit_count("response_stream_finished") == before_fin + 1
    # НИКАКОЙ рекурсии: ровно одна обязательная запись на экспорт
    _export_bundle(client)
    assert audit_count("audit_log_accessed", "diagnostic_bundle") == before_acc + 2


def test_a27_bundle_requires_export_scope_finding_f3_pinned(client: TestClient):
    """AC11/§15: экспорт требует logs.export. НАХОДКА F3 (пин): при 403
    mandatory-запись audit_log_accessed decision=allowed УЖЕ написана
    (audit утверждает разрешённое раскрытие, которого не было)."""
    client.headers.update({"X-API-Key": RO_KEY})  # только logs.read
    before = audit_count("audit_log_accessed", "diagnostic_bundle")
    response = client.post("/v1/logs/export", json={})
    assert response.status_code == 403
    after = audit_count("audit_log_accessed", "diagnostic_bundle")
    assert after == before + 1  # находка F3: запись «allowed» при отказе
    record = [r for r in security_audit.audit_records()
              if r.get("resource_id") == "diagnostic_bundle"][-1]
    assert record["decision"] == "allowed"  # факт находки


def test_a28_bundle_validation_and_stream_subset(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=1)
    response = client.post("/v1/logs/export", json={"streams": ["bogus"]})
    assert response.status_code == 422
    response = client.post("/v1/logs/export", json={
        "from": iso(datetime.now(timezone.utc) - timedelta(days=40)),
        "to": iso(datetime.now(timezone.utc))})
    assert response.status_code == 422  # окно > 31 дня
    # подмножество потоков -- только запрошенные члены
    bundle = _export_bundle(client, streams=["telemetry"])
    with zipfile.ZipFile(io.BytesIO(bundle["bytes"])) as zf:
        assert set(zf.namelist()) == {"manifest.json", "telemetry.jsonl"}
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["requested"]["streams"] == ["telemetry"]


def test_a29_bundle_grant_narrowed_bundle_honest(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    """Пакет по гранту: только записи границы, effective_scope честен.
    Грант без audit.read -- пакет собирается ТОЛЬКО из разрешённых
    потоков (явный streams), попытка всего каталога -- 403 (§19)."""
    create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                         tenant_id=TENANT_CORE,
                         scopes=["logs.read", "logs.export"],
                         ticket="d7c-ticket-bundle")
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    seed_telemetry(count=2)
    seed_telemetry(count=1, tenant_id=TENANT_ZETA, run_id=RUN_B,
                   event_name="d7c.seed.zeta")
    # весь каталог (audit без права) -- 403, а не частичный пакет
    response = client.post("/v1/logs/export", json={})
    assert response.status_code == 403
    # только разрешённый поток -- честный суженный пакет
    bundle = _export_bundle(client, streams=["telemetry"])
    with zipfile.ZipFile(io.BytesIO(bundle["bytes"])) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        telemetry_records = _decode_concatenated_jsonl(zf.read("telemetry.jsonl"))
    assert manifest["effective_scope"] == {"tenants": [TENANT_CORE], "runs": []}
    assert manifest["counts"]["telemetry.jsonl"] == 2  # zeta НЕ в пакете
    assert all(r.get("tenant_id") == TENANT_CORE for r in telemetry_records)


# ═══════════════ 8. Uniform-ошибки и tripwire ═════════════════════════


def test_a30_backend_503_uniform(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    monkeypatch.setenv("CISSTAT_TELEMETRY_BACKEND", "postgres")
    try:
        response = client.get("/v1/logs/telemetry")  # DATABASE_URL удалён
        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "logs_backend_unavailable"
        assert body["request_id"]
    finally:
        monkeypatch.delenv("CISSTAT_TELEMETRY_BACKEND", raising=False)


def test_a31_ac05_tripwire_reads_do_not_mutate_delivery_state(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    chain = seed_delivery_chain()
    from apps.api.document_jobs import get_document_registry

    registry = get_document_registry()

    def snapshot_state() -> dict:
        rows = registry.list_delivery_summary()
        return {r["job_id"]: (r["state"], r["attempt"]) for r in rows}

    before = snapshot_state()
    client.get("/v1/logs/telemetry")
    client.get("/v1/logs/audit")
    client.get("/v1/logs/delivery")
    _export_bundle(client)
    assert snapshot_state() == before  # чтение журналов не меняет delivery
    # job остался ready, никаких ретраев/переходов
    assert before[chain["job_id"]][0] == "ready"


def test_a32_export_empty_body_all_streams_default_window(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    response = client.post("/v1/logs/export")  # тело отсутствует
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert set(zf.namelist()) == {
            "manifest.json", "telemetry.jsonl", "audit.jsonl", "delivery.jsonl"}


def test_a33_run_scoped_grant_narrows_runs(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    create_grant_via_api(client, subject_id=SUPPORT_SUBJECT,
                         tenant_id=TENANT_CORE, run_id=RUN_A,
                         scopes=["logs.read"], ticket="d7c-ticket-run")
    client.headers.update({"X-API-Key": SUPPORT_KEY})
    seed_telemetry(count=1, run_id=RUN_A)
    seed_telemetry(count=1, run_id=RUN_B, event_name="d7c.seed.runb")
    body = client.get("/v1/logs/telemetry",
                      params={"event_name": "d7c.seed.event"}).json()
    assert body["meta"]["count"] == 1
    assert body["records"][0]["research_run_id"] == RUN_A
    assert body["meta"]["effective_scope"] == {
        "tenants": [TENANT_CORE], "runs": [RUN_A]}


def test_a34_bundle_jsonl_concatenation_finding_f4_pinned(client: TestClient):
    """НАХОДКА F4 (пин): члены пакета <stream>.jsonl при >1 записи
    склеены БЕЗ newline-разделителя (to_jsonl не добавляет \\n, join
    через \"\"), поэтому разбор по строкам (JSONL-контракт) даёт ОДНУ
    строку с несколькими объектами -- независимый получатель (AC19)
    стандартным JSONL-ридером пакет не прочитает."""
    client.headers.update({"X-API-Key": ADMIN_KEY})
    seed_telemetry(count=2)
    bundle = _export_bundle(client, streams=["telemetry"])
    with zipfile.ZipFile(io.BytesIO(bundle["bytes"])) as zf:
        raw = zf.read("telemetry.jsonl")
    assert bundle["disposition"]  # пакет выдан
    lines = raw.decode("utf-8").splitlines()
    decoded = _decode_concatenated_jsonl(raw)
    assert len(decoded) >= 2  # свои сиды + worker-события старта
    # факт находки: N>=2 записей -> 1 строка (нет newline-разделителя)
    assert len(lines) == 1
    with pytest.raises(json.JSONDecodeError):
        json.loads(lines[0])  # Extra data -- не валидный JSON Lines


def test_a35_export_mandatory_fail_closed(client: TestClient):
    """AC11: экспорт журналов -- раскрытие; невозможность зафиксировать
    обязательную запись -- отказ ДО построения пакета (503), пакет не
    выдаётся."""
    client.headers.update({"X-API-Key": ADMIN_KEY})
    from apps.api import security_audit as sa

    class _Failing(sa.AuditSink):
        def append(self, record):
            raise RuntimeError("d7c audit outage")

        def readiness_probe(self):
            return {"ok": False, "backend": "memory"}

    security_audit.set_audit_sink_for_testing(_Failing())
    try:
        response = client.post("/v1/logs/export", json={})
        assert response.status_code == 503
        assert response.json()["code"] == "audit_unavailable"
        # пакет НЕ выдан при отказе обязательного audit
        assert response.headers.get("content-type") != "application/zip"
    finally:
        security_audit.reset_audit_for_testing()
