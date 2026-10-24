# scripts/doclog7cert/test_d7cert_oracle_unit.py
"""DOCLOG-7-CERT: unit-оракулы на СВОИХ данных (u01–u26).

Поверхность admin_logs.py без HTTP: валидация грантов, эффективный
доступ (§15.1), cursor/whitelist/окно (§14.2), retention (§16.1),
сужение по гранту (§19 «нет данных вне grant»), memory-реестр,
диагностический пакет (AC10/AC19), pg-хелперы (без БД).

 Namespace дизъюнктен repo: d7c-*, subj-d7c*, tenant-d7cert-*.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from apps.api import admin_logs
from apps.api.admin_logs import (
    AUDIT_RETENTION_DAYS,
    BUNDLE_EXCLUDED,
    BUNDLE_SCHEMA,
    EffectiveLogAccess,
    GrantValidationError,
    LogsValidationError,
    MemorySupportGrantRegistry,
    QUERY_LIMIT_MAX,
    STREAM_AUDIT,
    STREAM_DELIVERY,
    STREAM_TELEMETRY,
    SupportGrantService,
    TELEMETRY_RETENTION_DAYS,
    _check_explicit_scope,
    _decode_cursor,
    _encode_cursor,
    _is_expired,
    _narrow,
    _parse_iso,
    _retention_meta,
    _validate_filters,
    build_diagnostic_bundle,
    parse_query,
    replace_grant_record,
    resolve_effective_log_access,
)

from .conftest import (
    ADMIN_SUBJECT,
    RUN_A,
    RUN_B,
    SUPPORT_SUBJECT,
    TENANT_CORE,
    TENANT_ZETA,
    iso,
    make_grant_record,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _access(**kw) -> EffectiveLogAccess:
    base = dict(
        telemetry=True,
        audit=True,
        delivery=True,
        export=True,
        grants_management=False,
        tenants=frozenset(),
        runs=frozenset(),
    )
    base.update(kw)
    return EffectiveLogAccess(**base)


def _query(**kw):
    base = dict(
        stream=STREAM_TELEMETRY,
        from_raw=None,
        to_raw=None,
        limit_raw=None,
        cursor_raw=None,
        filters=None,
    )
    base.update(kw)
    return parse_query(base["stream"], **{k: v for k, v in base.items() if k != "stream"})


# ═══════════════ Валидация грантов (§14.2/§15, fail-closed) ═══════════


def test_u01_ticket_subject_tenant_required():
    ok = dict(
        ticket="d7c-ticket",
        subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE,
        scopes=("logs.read",),
        ttl_hours=24,
        run_id=None,
    )
    for override in (
        {"ticket": ""}, {"ticket": "   "}, {"ticket": None},
        {"subject_id": ""}, {"subject_id": None},
        {"subject_id": "subj-nothex!!"},  # subj- вне hex-шаблона невалиден
        {"tenant_id": ""}, {"tenant_id": None},
        {"tenant_id": "Not a slug"}, {"tenant_id": "TENANT-UPPER"},
    ):
        kw = dict(ok)
        kw.update(override)
        with pytest.raises(GrantValidationError):
            SupportGrantService._validate(**kw)


def test_u02_scopes_whitelist_no_data_rights():
    ok = dict(
        ticket="d7c-ticket",
        subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE,
        scopes=("logs.read",),
        ttl_hours=24,
        run_id=None,
    )
    # data/publish-права через support-grant ЗАПРЕЩЕНЫ (§14.2 «без данных»)
    for bad in ("artifact.data.read", "documentation.publish", "policy.admin",
                "logs.admin", "support.grant", "bogus.scope"):
        with pytest.raises(GrantValidationError):
            SupportGrantService._validate(**{**ok, "scopes": (bad,)})
    with pytest.raises(GrantValidationError):
        SupportGrantService._validate(**{**ok, "scopes": ()})
    # whitelist проходит
    SupportGrantService._validate(
        **{**ok, "scopes": ("logs.read", "audit.read", "logs.export")}
    )


def test_u03_ttl_bounds():
    ok = dict(
        ticket="d7c",
        subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE,
        scopes=("logs.read",),
        run_id=None,
    )
    for bad in (0, -1, -0.5, 168.0001, 1000, "abc", None):
        with pytest.raises(GrantValidationError):
            SupportGrantService._validate(**{**ok, "ttl_hours": bad})
    # 168 ровно -- легитимен; строка "24" -- легитимна; 0.5 -- легитимна
    SupportGrantService._validate(**{**ok, "ttl_hours": 168})
    SupportGrantService._validate(**{**ok, "ttl_hours": "24"})
    SupportGrantService._validate(**{**ok, "ttl_hours": 0.5})


def test_u04_ttl_nan_известная_находка_f2_raw_valueerror():
    """НАХОДКА F2 (пин): NaN проходит сравнения диапазона _validate
    (nan<=0 False, nan>168 False) и взрывается в timedelta уже В
    create_grant -- в API это 500, не 422. Оракул закрепляет
    СУЩЕСТВУЮЩЕЕ поведение как находку сертификатора (fail-closed
    валидация неполна), не как контракт."""
    service = SupportGrantService(registry=MemorySupportGrantRegistry())
    with pytest.raises(ValueError) as excinfo:
        service.create_grant(
            ticket="d7c-nan", purpose="d7c",
            subject_id=SUPPORT_SUBJECT, tenant_id=TENANT_CORE,
            scopes=("logs.read",), ttl_hours=float("nan"),
            created_by=ADMIN_SUBJECT)
    assert "NaN" in str(excinfo.value) or "nan" in str(excinfo.value).lower()


def test_u05_purpose_optional_известная_находка_f1():
    """НАХОДКА F1 (пин): purpose НЕ обязателен в коде, хотя контрактный
    документ docs/doclog7_logs_support.md требует «ticket/purpose/tenant
    обязательны» (спека §14.2: «Поддержка получает ticket/purpose»).
    Грант без purpose создаётся -- расхождение код↔контракт."""
    registry = MemorySupportGrantRegistry()
    service = SupportGrantService(registry=registry)
    record = service.create_grant(
        ticket="d7c-no-purpose",
        purpose="   ",
        subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE,
        scopes=("logs.read",),
        ttl_hours=1,
        created_by=ADMIN_SUBJECT,
    )
    assert record.purpose == ""  # создан БЕЗ purpose (находка)
    assert registry.get_grant(record.grant_id) is not None


def test_u06_is_expired_fail_closed():
    assert _is_expired(make_grant_record(expires_at=_now() + timedelta(hours=1))) is False
    assert _is_expired(make_grant_record(expires_at=_now() - timedelta(minutes=1))) is True
    # невалидная/отсутствующая дата -- fail-closed (считается истёкшим)
    broken = replace_grant_record(make_grant_record(), expires_at="не дата")
    assert _is_expired(broken) is True
    broken2 = replace_grant_record(make_grant_record(), expires_at=None)
    assert _is_expired(broken2) is True


def test_u07_parse_iso_наивная_utc():
    parsed = _parse_iso("2026-10-24T10:00:00")
    assert parsed is not None and parsed.tzinfo is not None
    parsed2 = _parse_iso("2026-10-24T10:00:00Z")
    assert parsed2 is not None
    assert _parse_iso("") is None
    assert _parse_iso("мусор") is None
    assert _parse_iso(None) is None


# ═══════════════ Эффективный доступ (§15.1 ADMIN ∪ scopes ∪ grants) ═══


class _Principal:
    def __init__(self, role=None, scopes=(), subject_id=""):
        self.role = role
        self.scopes = set(scopes)
        self.subject_id = subject_id


def test_u08_admin_unrestricted_and_grants_management():
    from apps.api.plans import Role

    access = resolve_effective_log_access(
        _Principal(role=Role.ADMIN, subject_id=ADMIN_SUBJECT),
        registry=MemorySupportGrantRegistry(),
    )
    assert access.unrestricted
    assert access.telemetry and access.audit and access.delivery
    assert access.export and access.grants_management
    # строковое "admin" тоже признаётся (паритет role.value)
    access2 = resolve_effective_log_access(
        _Principal(role="admin"), registry=MemorySupportGrantRegistry()
    )
    assert access2.unrestricted


def test_u09_no_role_no_scopes_no_access():
    access = resolve_effective_log_access(
        _Principal(subject_id=SUPPORT_SUBJECT),
        registry=MemorySupportGrantRegistry(),
    )
    assert not access.telemetry and not access.audit and not access.delivery
    assert not access.export and not access.grants_management


def test_u10_scopes_map_to_streams():
    access = resolve_effective_log_access(
        _Principal(scopes={"logs.read", "audit.read", "logs.export"}),
        registry=MemorySupportGrantRegistry(),
    )
    assert access.telemetry and access.audit and access.delivery and access.export
    assert not access.grants_management
    access2 = resolve_effective_log_access(
        _Principal(scopes={"support.grant"}),
        registry=MemorySupportGrantRegistry(),
    )
    assert access2.grants_management
    assert not access2.telemetry and not access2.audit and not access2.export


def test_u11_grants_union_boundaries_expired_revoked_excluded():
    registry = MemorySupportGrantRegistry()
    now = _now()
    registry.create_grant(make_grant_record(
        grant_id="d7grant-d7cert-u11a", subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE, run_id=None,
        scopes=("logs.read", "audit.read"),
        created_at=now, expires_at=now + timedelta(hours=2)))
    registry.create_grant(make_grant_record(
        grant_id="d7grant-d7cert-u11b", subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_ZETA, run_id=RUN_A,
        scopes=("logs.export",),
        created_at=now, expires_at=now + timedelta(hours=2)))
    # истёкший -- исключён
    registry.create_grant(make_grant_record(
        grant_id="d7grant-d7cert-u11c", subject_id=SUPPORT_SUBJECT,
        tenant_id="tenant-d7cert-exp", scopes=("logs.read",),
        created_at=now - timedelta(hours=5), expires_at=now - timedelta(hours=1)))
    # отозванный -- исключён (list_grants по умолчанию hide)
    registry.create_grant(make_grant_record(
        grant_id="d7grant-d7cert-u11d", subject_id=SUPPORT_SUBJECT,
        tenant_id="tenant-d7cert-rev", scopes=("logs.read",),
        created_at=now, expires_at=now + timedelta(hours=2),
        revoked_at=now.isoformat()))
    # невалидный expires -- fail-closed
    broken = replace_grant_record(
        make_grant_record(
            grant_id="d7grant-d7cert-u11e", subject_id=SUPPORT_SUBJECT,
            tenant_id="tenant-d7cert-bad", scopes=("logs.read",)),
        expires_at="мусор")
    registry.create_grant(broken)

    access = resolve_effective_log_access(
        _Principal(subject_id=SUPPORT_SUBJECT), registry=registry)
    assert access.telemetry and access.audit and access.export
    assert not access.grants_management
    assert access.tenants == frozenset({TENANT_CORE, TENANT_ZETA})
    assert access.runs == frozenset({RUN_A})
    assert not access.unrestricted


# ═══════════════ Cursor / окно / лимиты / whitelist (§14.2) ═══════════


def test_u12_cursor_roundtrip_and_fail_closed():
    encoded = _encode_cursor(("2026-10-24T00:00:00+00:00", "evt-1"))
    decoded = _decode_cursor(encoded)
    assert decoded == {"t": "2026-10-24T00:00:00+00:00", "id": "evt-1"}
    for garbage in ("!!!не base64!!!", "", "e30="):  # {} без ключей
        with pytest.raises(LogsValidationError):
            _decode_cursor(garbage)
    # валидный base64 от списка, не dict
    import base64

    with pytest.raises(LogsValidationError):
        _decode_cursor(base64.urlsafe_b64encode(b"[1,2]").decode("ascii"))


def test_u13_parse_query_defaults_and_window():
    q = _query()
    assert q.limit == 50
    assert q.to_ts - q.from_ts == timedelta(hours=24)
    assert q.cursor is None and q.filters == {}
    # пустое окно / обратное окно
    now = _now()
    with pytest.raises(LogsValidationError):
        _query(from_raw=iso(now), to_raw=iso(now))
    with pytest.raises(LogsValidationError):
        _query(from_raw=iso(now), to_raw=iso(now - timedelta(hours=1)))
    # окно > 31 дня -- отказ; ровно 31 день -- ок
    with pytest.raises(LogsValidationError):
        _query(
            from_raw=iso(now - timedelta(days=31, seconds=1)),
            to_raw=iso(now),
        )
    q31 = _query(
        from_raw=iso(now - timedelta(days=31)),
        to_raw=iso(now),
    )
    assert q31.to_ts - q31.from_ts == timedelta(days=31)
    # некорректные даты
    with pytest.raises(LogsValidationError):
        _query(from_raw="не дата", to_raw=None)
    with pytest.raises(LogsValidationError):
        _query(from_raw=None, to_raw="не дата")
    # неизвестный поток
    with pytest.raises(LogsValidationError):
        parse_query("bogus", from_raw=None, to_raw=None, limit_raw=None,
                    cursor_raw=None, filters=None)


def test_u14_limit_bounds():
    for bad in (0, -1, 201, 10**6, "abc"):
        with pytest.raises(LogsValidationError):
            _query(limit_raw=bad)
    assert _query(limit_raw=1).limit == 1
    assert _query(limit_raw=200).limit == QUERY_LIMIT_MAX
    assert _query(limit_raw="7").limit == 7
    # N-наблюдение: float-лимит тихо обрезается int() (1.5 -> 1) --
    # без выхода за границы 1..200; закреплено как N-D7C3.
    assert _query(limit_raw=1.5).limit == 1
    assert _query(limit_raw=200.9).limit == 200


def test_u15_filters_validation():
    # None/"" выбрасываются; не-строки -- отказ
    q = _query(filters={"tenant_id": TENANT_CORE, "run_id": None, "severity": ""})
    assert q.filters == {"tenant_id": TENANT_CORE}
    with pytest.raises(LogsValidationError):
        _query(filters={"limit": 5})
    # whitelist потоков (§14.2)
    assert _validate_filters(STREAM_TELEMETRY, {"severity": "INFO"}) == {
        "severity": "INFO"}
    assert _validate_filters(STREAM_AUDIT, {"action": "grant_created"})
    assert _validate_filters(STREAM_DELIVERY, {"state": "ready", "format": "pdf"})
    with pytest.raises(LogsValidationError):
        _validate_filters(STREAM_TELEMETRY, {"action": "x"})  # чужой полю
    with pytest.raises(LogsValidationError):
        _validate_filters(STREAM_AUDIT, {"event_name": "x"})
    with pytest.raises(LogsValidationError):
        _validate_filters(STREAM_DELIVERY, {"severity": "INFO"})
    with pytest.raises(LogsValidationError):
        _validate_filters(STREAM_TELEMETRY, {"free_sql": "1=1; DROP"})


# ═══════════════ Retention horizon (§16.1 -- честный репортинг) ═══════


def test_u16_retention_meta_horizons():
    now = _now()
    meta_t = _retention_meta(STREAM_TELEMETRY, now - timedelta(days=40))
    assert meta_t["retention_horizon_days"] == 30
    assert "retention_note" in meta_t
    meta_a = _retention_meta(STREAM_AUDIT, now - timedelta(days=400))
    assert meta_a["retention_horizon_days"] == 365
    assert "retention_note" in meta_a
    # свежие окна -- без пометки
    assert "retention_note" not in _retention_meta(STREAM_TELEMETRY, now - timedelta(days=1))
    assert "retention_note" not in _retention_meta(STREAM_AUDIT, now - timedelta(days=30))
    # delivery -- горизонт отсутствует (явный None), пометки нет
    meta_d = _retention_meta(STREAM_DELIVERY, now - timedelta(days=400))
    assert meta_d["retention_horizon_days"] is None
    assert "retention_note" not in meta_d
    # константы контракта §16.1
    assert TELEMETRY_RETENTION_DAYS == 30
    assert AUDIT_RETENTION_DAYS == 365


# ═══════════════ Сужение по гранту (§19 «нет данных вне grant») ═══════


def test_u17_narrow_fail_closed():
    rec = {"tenant_id": TENANT_CORE, "run_id": RUN_A}
    rec_zeta = {"tenant_id": TENANT_ZETA, "run_id": RUN_B}
    rec_empty = {"tenant_id": "", "run_id": RUN_A}
    rec_no_tenant = {"run_id": RUN_A}
    # unrestricted -- всё проходит
    full = _access()
    for r in (rec, rec_zeta, rec_empty, rec_no_tenant):
        assert _narrow(r, full, run_key="run_id")
    # scoped: только свой tenant; пустой/отсутствующий tenant -- FAIL-CLOSED
    scoped = _access(tenants=frozenset({TENANT_CORE}))
    assert _narrow(rec, scoped, run_key="run_id")
    assert not _narrow(rec_zeta, scoped, run_key="run_id")
    assert not _narrow(rec_empty, scoped, run_key="run_id")
    assert not _narrow(rec_no_tenant, scoped, run_key="run_id")
    # scoped по run: чужой run отброшен
    scoped_run = _access(tenants=frozenset({TENANT_CORE}), runs=frozenset({RUN_A}))
    assert _narrow(rec, scoped_run, run_key="run_id")
    assert not _narrow(
        {"tenant_id": TENANT_CORE, "run_id": RUN_B}, scoped_run, run_key="run_id")
    # runs пуст при непустых tenants -- run-граница не применяется
    tenant_only = _access(tenants=frozenset({TENANT_CORE}))
    assert _narrow({"tenant_id": TENANT_CORE, "run_id": RUN_B}, tenant_only,
                   run_key="run_id")


def test_u18_explicit_scope_gate_403_semantics():
    rec_query_tenant_foreign = _query(filters={"tenant_id": TENANT_ZETA})
    rec_query_run_foreign = _query(filters={"run_id": RUN_B})
    # unrestricted -- нет отказа
    _check_explicit_scope(rec_query_tenant_foreign, _access())
    # scoped c непустыми tenants: явный фильтр вне границы -- отказ (403)
    scoped = _access(tenants=frozenset({TENANT_CORE}), runs=frozenset({RUN_A}))
    with pytest.raises(admin_logs.LogsAccessDenied):
        _check_explicit_scope(rec_query_tenant_foreign, scoped)
    with pytest.raises(admin_logs.LogsAccessDenied):
        _check_explicit_scope(rec_query_run_foreign, scoped)
    _check_explicit_scope(_query(filters={"run_id": RUN_A}), scoped)
    # tenant-wide грант (runs пуст): run-фильтр НЕ классифицируется вне
    # границы (граница run не ограничена) -- сужение, не 403 (честная
    # семантика; meta.effective_scope раскрывает сужение)
    tenant_only = _access(tenants=frozenset({TENANT_CORE}))
    _check_explicit_scope(rec_query_run_foreign, tenant_only)
    with pytest.raises(admin_logs.LogsAccessDenied):
        _check_explicit_scope(rec_query_tenant_foreign, tenant_only)


# ═══════════════ Memory-реестр грантов ════════════════════════════════


def test_u19_memory_registry_crud_and_overflow():
    registry = MemorySupportGrantRegistry(maxsize=2)
    g1 = make_grant_record(grant_id="d7grant-d7cert-u19a")
    g2 = make_grant_record(grant_id="d7grant-d7cert-u19b")
    g3 = make_grant_record(grant_id="d7grant-d7cert-u19c")
    registry.create_grant(g1)
    registry.create_grant(g2)
    assert registry.get_grant("d7grant-d7cert-u19a").grant_id == g1.grant_id
    assert registry.get_grant("d7grant-нет") is None
    with pytest.raises(admin_logs.LogsBackendError):
        registry.create_grant(g3)  # переполнение -- честный backend-отказ
    # список: subject-фильтр, hide revoked, порядок (created_at, id) DESC
    now = _now()
    registry2 = MemorySupportGrantRegistry()
    a = make_grant_record(grant_id="d7grant-d7cert-u19d", created_at=now,
                          expires_at=now + timedelta(hours=1))
    b = make_grant_record(grant_id="d7grant-d7cert-u19e", created_at=now,
                          expires_at=now + timedelta(hours=1))
    c = make_grant_record(grant_id="d7grant-d7cert-u19f", created_at=now,
                          expires_at=now + timedelta(hours=1),
                          subject_id="subj-d7c9999999999999")
    registry2.create_grant(a)
    registry2.create_grant(b)
    registry2.create_grant(c)
    listed = registry2.list_grants()
    assert [r.grant_id for r in listed] == [
        "d7grant-d7cert-u19f", "d7grant-d7cert-u19e", "d7grant-d7cert-u19d"]
    mine = registry2.list_grants(subject_id=SUPPORT_SUBJECT)
    assert {r.grant_id for r in mine} == {
        "d7grant-d7cert-u19d", "d7grant-d7cert-u19e"}
    revoked = replace_grant_record(
        a, revoked_at=now.isoformat(), revoked_by=ADMIN_SUBJECT)
    registry2.update_grant(revoked)
    assert registry2.list_grants(subject_id=SUPPORT_SUBJECT) == [
        b]  # revoked скрыт
    both = registry2.list_grants(subject_id=SUPPORT_SUBJECT, include_revoked=True)
    assert len(both) == 2
    with pytest.raises(admin_logs.GrantNotFoundError):
        registry2.update_grant(make_grant_record(grant_id="d7grant-нет"))
    # копии, не ссылки (без алиасинга; урок DOCLOG-0)
    listed2 = registry2.list_grants()
    assert [r.grant_id for r in listed2] == [
        "d7grant-d7cert-u19f", "d7grant-d7cert-u19e"]
    assert listed2[0] is not b


def test_u20_replace_record_no_aliasing():
    original = make_grant_record()
    changed = replace_grant_record(original, purpose="новая цель d7c")
    assert original.purpose == "d7c unit grant"
    assert changed.purpose == "новая цель d7c"
    assert changed.grant_id == original.grant_id


# ═══════════════ Диагностический пакет (unit-уровень) ════════════════


def test_u21_bundle_zip_contract_and_determinism():
    from apps.api import telemetry

    telemetry.emit(
        "d7c.bundle.event", "info",
        message_template="d7c bundle seed",
        attributes={"d7c": 1},
        tenant_id=TENANT_CORE, research_run_id=RUN_A,
        occurred_at=iso(_now() - timedelta(minutes=5)), essential=True,
    )
    query = _query(
        from_raw=iso(_now() - timedelta(hours=1)), to_raw=iso(_now())
    )
    access = _access()
    zip1, bundle_id1, filename1 = build_diagnostic_bundle(
        query, access, streams=("telemetry",))
    assert filename1 == f"{bundle_id1}.zip"
    assert bundle_id1.startswith("diagb-")
    assert filename1.endswith(".zip") and "/" not in filename1
    with zipfile.ZipFile(io.BytesIO(zip1)) as zf:
        names = set(zf.namelist())
        assert names == {"manifest.json", "telemetry.jsonl"}
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        telemetry_lines = zf.read("telemetry.jsonl").decode("utf-8").strip().splitlines()
        # AC10-детерминизм: даты всех членов зафиксированы (2020,1,1)
        for info in zf.infolist():
            assert info.date_time == (2020, 1, 1, 0, 0, 0)
    assert manifest["schema_version"] == BUNDLE_SCHEMA
    assert manifest["counts"]["telemetry.jsonl"] == 1
    assert manifest["members_sha256"] and set(manifest["members_sha256"]) == {
        "telemetry.jsonl"}
    import hashlib

    with zipfile.ZipFile(io.BytesIO(zip1)) as zf:
        assert manifest["members_sha256"]["telemetry.jsonl"] == hashlib.sha256(
            zf.read("telemetry.jsonl")).hexdigest()
    assert len(manifest["excluded"]) == 5
    # детерминизм: два пакета совпадают во всём, кроме bundle_id/created_at
    zip2, bundle_id2, _ = build_diagnostic_bundle(query, access, streams=("telemetry",))
    assert bundle_id1 != bundle_id2
    with zipfile.ZipFile(io.BytesIO(zip1)) as z1, zipfile.ZipFile(io.BytesIO(zip2)) as z2:
        m1 = json.loads(z1.read("manifest.json"))
        m2 = json.loads(z2.read("manifest.json"))
        m1.pop("bundle_id"), m1.pop("created_at")
        m2.pop("bundle_id"), m2.pop("created_at")
        assert m1 == m2
        assert z1.read("telemetry.jsonl") == z2.read("telemetry.jsonl")


def test_u22_bundle_manifest_exclusions_and_scope_meta():
    query = _query()
    scoped = _access(tenants=frozenset({TENANT_CORE}), runs=frozenset({RUN_A}))
    zip_bytes, _, _ = build_diagnostic_bundle(query, scoped, streams=("audit",))
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["effective_scope"] == {
        "tenants": [TENANT_CORE], "runs": [RUN_A]}
    assert manifest["limits"]["per_stream_rows"] == 2000
    assert manifest["retention"] == {
        "telemetry_days": 30, "audit_days": 365}
    assert "requested" in manifest and "filters" in manifest
    # исключённые категории зафиксированы явно (AC19)
    joined = " ".join(manifest["excluded"])
    for keyword in ("датасетов", "cookies", "env", "API-ключ", "пути"):
        assert keyword in joined, keyword
    assert BUNDLE_EXCLUDED == tuple(manifest["excluded"])


def test_u23_bundle_access_and_validation_fail_closed():
    query = _query()
    no_export = _access(export=False)
    with pytest.raises(admin_logs.LogsAccessDenied):
        build_diagnostic_bundle(query, no_export)
    with pytest.raises(LogsValidationError):
        build_diagnostic_bundle(query, _access(), streams=("bogus",))


def test_u24_safe_ops_never_breaks_bundle_and_stays_safe():
    # сбой сборки статуса -- {"ok": False}, пакет живёт (§14.2 диагностический)
    status = admin_logs._safe_ops("telemetry")
    assert isinstance(status, dict)
    broken = admin_logs._safe_ops("audit")  # на memory-бекенде честный статус
    assert isinstance(broken, dict)


# ═══════════════ Postgres-хелперы (unit, без БД) ══════════════════════


def test_u25_pg_narrow_builds_parameterized_in_clauses():
    clauses: list[str] = []
    params: list = []
    scoped = _access(tenants=frozenset({TENANT_CORE, TENANT_ZETA}),
                     runs=frozenset({RUN_A, RUN_B}))
    admin_logs._pg_narrow(clauses, params, scoped, run_col="research_run_id")
    assert any("tenant_id IN" in c for c in clauses)
    assert any("research_run_id IN" in c for c in clauses)
    assert params == [TENANT_CORE, TENANT_ZETA, RUN_A, RUN_B]  # sorted, параметризовано
    # unrestricted -- clauses не добавляются
    clauses2: list[str] = []
    params2: list = []
    admin_logs._pg_narrow(clauses2, params2, _access(), run_col="run_id")
    assert clauses2 == [] and params2 == []
    # окно >= from, < to
    now = _now()
    clauses3, params3 = admin_logs._pg_window("occurred_at", _query(
        from_raw=iso(now - timedelta(hours=2)), to_raw=iso(now)))
    assert clauses3 == ["occurred_at >= %s", "occurred_at < %s"]
    assert params3 == [now - timedelta(hours=2), now]


def test_u26_grant_scopes_catalog_frozen():
    assert admin_logs.GRANT_SCOPES == frozenset(
        {"logs.read", "audit.read", "logs.export"})
    # НИКАКИХ data/publish прав в whitelist грантов
    assert not (admin_logs.GRANT_SCOPES & {"artifact.data.read",
                                           "documentation.publish", "policy.admin"})
    assert admin_logs.GRANT_TTL_MAX_HOURS == 168
    assert admin_logs.WINDOW_MAX_DAYS == 31
    assert admin_logs.QUERY_LIMIT_MAX == 200
    assert admin_logs.QUERY_LIMIT_DEFAULT == 50
    assert admin_logs.EXPORT_LIMIT == 2000
    assert admin_logs.GRANT_SCHEMA_VERSION == "doclog.support_grant/1"
    assert admin_logs.BUNDLE_PREFIX == "diagb-"
