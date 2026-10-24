# scripts/doclog9cert/test_d9cert_oracle_unit.py
"""DOCLOG-9-CERT: unit-оракулы на СВОИХ данных (u01–u32).

Поверхность: каталоги профилей, права §15 (scopes vs роль), валидаторы
conformance («не названием файла»), detached-подпись (HMAC, НЕ юр. ЭП),
чистые рендеры docx/pdfa (R06/AC03/AC05), §19-доказательства
(validation-record даже при passed), якорь/WORM, аудит-классы §8/§14.1,
паритет реестра, ПИН дефектов F-D9C1/F-D9C2 (честная фиксация
фактического поведения; трактовка -- в акте docs/cert_doclog9).
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import replace

import pytest

from scripts.doclog9cert.conftest import (
    RUN_A,
    SESSION_A,
    SESSION_B,
    SESSION_C,
    admin_subject,
    audit_count,
    audit_records,
    delivery,
    make_profile,
    policy_subject,
    profile_service,
    render_with_profile,
    seed_document_revision,
    seed_snapshot,
    subject_of,
)


# ══════════════════════════════════════════════════════════════════════
# Каталоги и модель (§19/§16)
# ══════════════════════════════════════════════════════════════════════


def test_u01_profile_catalogs_frozen():
    from apps.api import doc_profiles as dp

    assert dp.PROFILE_FORMATS == frozenset({"docx", "pdfa"})
    assert dp.PROFILE_ACTIVE == "active" and dp.PROFILE_RETIRED == "retired"
    assert dp.VALIDATOR_BY_FORMAT == {
        "pdfa": "pdfa-structural/1",
        "docx": "docx-structural/1",
    }
    assert dp.KNOWN_VALIDATORS == frozenset(
        {"pdfa-structural/1", "docx-structural/1", "signature/1"}
    )
    assert dp.SIGN_KEY_ENV == "CISSTAT_DOC_SIGN_KEY"
    assert dp.SIGNATURE_ALGORITHM == "HMAC-SHA256"
    assert dp.WORM_REASON_PREFIX == "org_profile_worm"


def test_u02_schema_version_and_disclaimer():
    from apps.api import doc_profiles as dp

    assert dp.PROFILE_SCHEMA_VERSION == "doclog.org_profile/1"
    import os

    os.environ["CISSTAT_DOC_SIGN_KEY"] = "d9cert-k1"
    try:
        manifest = dp.sign_content(
            b"d9cert-bytes", snapshot_sha256="a" * 64, profile_id="prof-x"
        )
    finally:
        os.environ.pop("CISSTAT_DOC_SIGN_KEY", None)
    assert manifest["disclaimer"] == "not_a_legal_signature"
    assert manifest["content_sha256"] == hashlib.sha256(b"d9cert-bytes").hexdigest()
    assert manifest["algorithm"] == "HMAC-SHA256"


def test_u03_create_name_validation_and_strip():
    svc = profile_service()
    subject = admin_subject()
    with pytest.raises(dp_err()):
        svc.create_profile(name="   ", version_no=1, format="pdfa", subject=subject)
    with pytest.raises(dp_err()):
        svc.create_profile(name="", version_no=1, format="pdfa", subject=subject)
    made = svc.create_profile(
        name="  d9cert-strip  ", version_no=1, format="docx", subject=subject
    )
    assert made.name == "d9cert-strip"
    assert made.profile_id.startswith("prof-")


def dp_err():
    from apps.api.doc_profiles import OrgProfileError

    return OrgProfileError


def test_u04_version_no_catalog():
    """version_no -- положительное целое; ПИН F-D9C2-кандидат: bool
    проходит isinstance(int) и принимается (Memory-путь; JSON-ответ
    «version_no»: true; durable INTEGER-колонка рассинхронизирована --
    трактовка в акте)."""
    svc = profile_service()
    subject = admin_subject()
    for bad in (0, -1, "2", 1.5, None):
        with pytest.raises(dp_err()):
            svc.create_profile(
                name=f"d9cert-vn-{type(bad).__name__}",
                version_no=bad,
                format="pdfa",
                subject=subject,
            )
    pinned = svc.create_profile(
        name="d9cert-bool-version", version_no=True, format="pdfa",
        subject=subject,
    )
    assert pinned.version_no == True  # noqa: E712 -- честный ПИН дефекта


def test_u05_format_catalog_case_sensitive_at_service():
    """Сервис НЕ нормализует регистр (нормализация -- обязанность
    роутера, пин в API-оракуле a09); чужой формат -- FormatMismatch."""
    svc = profile_service()
    subject = admin_subject()
    from apps.api.doc_profiles import OrgProfileFormatMismatch

    with pytest.raises(OrgProfileFormatMismatch):
        svc.create_profile(name="d9cert-fmt", version_no=1, format="pdf",
                           subject=subject)
    with pytest.raises(OrgProfileFormatMismatch):
        svc.create_profile(name="d9cert-fmt2", version_no=1, format="PDFA",
                           subject=subject)


def test_u06_policy_admin_gate_scopes_vs_role():
    """§15: право через scopes; аноним -- NotFound (uniform), без права
    -- AccessDenied; роль admin и scope policy.admin -- оба пути."""
    from apps.api.doc_profiles import (
        OrgProfileAccessDenied,
        OrgProfileNotFound,
    )

    svc = profile_service()
    from apps.api.identity import SubjectRef

    with pytest.raises(OrgProfileNotFound):
        svc.create_profile(name="d9cert-anon", version_no=1, format="pdfa",
                           subject=None)
    anon_ref = SubjectRef.anonymous()
    assert anon_ref.is_anonymous
    with pytest.raises(OrgProfileNotFound):
        svc.list_profiles(anon_ref)
    with pytest.raises(OrgProfileNotFound):
        svc.list_profiles(subject_of(""))  # пустая сессия -- anonymous
    writer = subject_of(SESSION_B, role="external_user",
                        scopes=frozenset({"documentation.write"}))
    with pytest.raises(OrgProfileAccessDenied):
        svc.create_profile(name="d9cert-w", version_no=1, format="pdfa",
                           subject=writer)
    by_role = svc.create_profile(name="d9cert-role", version_no=1,
                                 format="pdfa", subject=admin_subject())
    assert by_role.status == "active"
    by_scope = svc.create_profile(name="d9cert-scope", version_no=1,
                                  format="docx", subject=policy_subject())
    assert by_scope.created_by == policy_subject().subject_id
    listed = svc.list_profiles(writer)
    names = [p.name for p in listed]
    assert "d9cert-role" in names and "d9cert-scope" in names


def test_u07_create_audit_mandatory_fail_closed():
    """§14.1/AC11: org_profile_created -- mandatory; недоступный sink
    прерывает запись аудита. ПИН ПОРЯДКА (см. F-D9C2 в акте): реестр
    пишется ДО аудита -- профиль остаётся созданным при сбойном sink
    (защищённое действие выполнено, только ответ об ошибке); здесь
    фиксируем факт both-сторон: сбой sink виден И профиль существует."""
    from apps.api import security_audit
    from apps.api.doc_profiles import OrgProfileError

    from scripts.doclog9cert.conftest import BrokenAuditSink

    svc = profile_service()
    security_audit.set_audit_sink_for_testing(BrokenAuditSink())
    with pytest.raises(Exception) as excinfo:
        svc.create_profile(name="d9cert-fc", version_no=1, format="pdfa",
                           subject=admin_subject())
    assert "org_profile_created" in str(excinfo.value)
    assert "AC11 fail-closed" in str(excinfo.value)
    security_audit.set_audit_sink_for_testing(None)
    # Фактическое состояние: профиль СОЗДАН (порядок write→audit, ПИН).
    dup = svc.registry.find_duplicate("d9cert-fc", 1)
    assert dup is not None  # ПИН F-D9C2: действие выполнено до отказа


def test_u08_retire_flow_idempotent_and_immutable():
    svc = profile_service()
    subject = admin_subject()
    profile = svc.create_profile(name="d9cert-retire", version_no=1,
                                 format="docx", subject=subject,
                                 footer_text="d9cert-футер")
    retired = svc.retire_profile(profile.profile_id, subject)
    assert retired.status == "retired"
    assert retired.retired_by == subject.subject_id
    assert retired.retired_at
    # Иммутабельность содержимого: retire -- статусная запись.
    for field in ("name", "version_no", "format", "language", "title_prefix",
                  "footer_text", "organization", "created_by", "created_at"):
        assert getattr(retired, field) == getattr(profile, field), field
    assert audit_count("org_profile_created") == 1
    assert audit_count("org_profile_retired") == 1
    # Идемпотентность: повторный retire -- БЕЗ второй audit-записи.
    again = svc.retire_profile(profile.profile_id, subject)
    assert again.status == "retired"
    assert audit_count("org_profile_retired") == 1
    # Атрибуция и ресурс в audit-записи.
    rec = [r for r in audit_records() if r.get("action") == "org_profile_retired"][0]
    assert rec.get("resource_kind") == "document_profile"
    assert rec.get("resource_id") == profile.profile_id


def test_u09_resolve_profile_policy_gates():
    from apps.api.doc_profiles import (
        OrgProfileFormatMismatch,
        OrgProfileNotFound,
        OrgProfileRetired,
    )

    svc = profile_service()
    subject = admin_subject()
    pdfa_profile = svc.create_profile(name="d9cert-res-p", version_no=1,
                                      format="pdfa", subject=subject)
    with pytest.raises(OrgProfileNotFound):
        svc.resolve_profile("prof-missing", fmt="pdfa", subject=subject)
    with pytest.raises(OrgProfileFormatMismatch):
        svc.resolve_profile(pdfa_profile.profile_id, fmt="docx",
                            subject=subject)
    resolved = svc.resolve_profile(pdfa_profile.profile_id, fmt="pdfa",
                                   subject=subject)
    assert resolved.profile_id == pdfa_profile.profile_id
    svc.retire_profile(pdfa_profile.profile_id, subject)
    with pytest.raises(OrgProfileRetired):
        svc.resolve_profile(pdfa_profile.profile_id, fmt="pdfa",
                            subject=subject)


# ══════════════════════════════════════════════════════════════════════
# Валидаторы conformance: подтверждение ВАЛИДАТОРОМ, не названием (§19)
# ══════════════════════════════════════════════════════════════════════


def _pdfa_with_removed_marker(marker: bytes) -> bytes:
    from apps.api.document_renditions import render_snapshot_pdfa

    class Snap:
        pass

    snap = seed_snapshot()
    content = render_snapshot_pdfa(snap)
    assert marker in content
    return content.replace(marker, b"REMOVED-MARKER")


def test_u10_pdfa_validator_own_render_passes_and_marker_catalog():
    """Собственный pdfa-рендер -- passed; КАЖДЫЙ маркер по отдельности
    даёт СВОЙ finding (валидатор подтверждает байты, не название)."""
    from apps.api.doc_profiles import _pdfa_structural_validate
    from apps.api.document_renditions import render_snapshot_pdfa

    snap = seed_snapshot()
    good = render_snapshot_pdfa(snap)
    result = _pdfa_structural_validate(good)
    assert result.result == "passed"
    assert result.validator == "pdfa-structural/1"

    non_pdf = b"PK-03-04 not a pdf"
    r0 = _pdfa_structural_validate(non_pdf)
    assert r0.result == "failed" and any(
        f.startswith("pdf_header_missing") for f in r0.findings
    )
    cases = {
        b"GTS_PDFA1": "outputintent_missing",
        b"DestOutputProfile": "icc_missing",
        b"FontFile2": "fonts_missing",
    }
    for marker, code in cases.items():
        broken = _pdfa_with_removed_marker(marker)
        res = _pdfa_structural_validate(broken)
        assert res.result == "failed", marker
        assert any(f.startswith(code) for f in res.findings), (marker, res.findings)
    # XMP-идентификация: оба pdfaid-поля.
    import re

    no_part = re.sub(rb"pdfaid:part[^>]*>\s*1\s*<", b"pdfaid:part>9<", good)
    r1 = _pdfa_structural_validate(no_part)
    assert any(f.startswith("pdfaid_missing") for f in r1.findings)
    no_conf = re.sub(
        rb"pdfaid:conformance[^>]*>\s*B\s*<", b"pdfaid:conformance>Q<",
        good, flags=re.IGNORECASE,
    )
    r2 = _pdfa_structural_validate(no_conf)
    assert any(f.startswith("pdfa_conformance_missing") for f in r2.findings)
    # Запрещённые включения.
    for marker, code in (
        (b"/Encrypt", "encrypt_present"),
        (b"/JavaScript", "javascript_present"),
        (b"/S /URI", "external_uri_present"),
    ):
        injected = good + b"\n" + marker + b"\n"
        res = _pdfa_structural_validate(injected)
        assert res.result == "failed", marker
        assert any(f.startswith(code) for f in res.findings), (marker, res.findings)


def test_u11_pdfa_validator_fails_plain_pdf():
    """§7 P2/§20: обычный PDF НЕ проходит pdfa-валидатор (не
    переименованный PDF)."""
    from apps.api.doc_profiles import _pdfa_structural_validate
    from apps.api.document_renditions import render_snapshot_pdf

    snap = seed_snapshot()
    plain = render_snapshot_pdf(snap)
    res = _pdfa_structural_validate(plain)
    assert res.result == "failed"
    assert any(f.startswith("pdfaid_missing") for f in res.findings)


def test_u12_docx_validator_members_external_rels_xml():
    from apps.api.doc_profiles import _docx_structural_validate
    from apps.api.document_renditions import render_snapshot_docx

    snap = seed_snapshot()
    good = render_snapshot_docx(snap)
    res = _docx_structural_validate(good)
    assert res.result == "passed"
    assert res.validator == "docx-structural/1"

    # Не ZIP.
    r0 = _docx_structural_validate(b"not a zip at all")
    assert r0.result == "failed"
    assert any(f.startswith("zip_invalid") for f in r0.findings)

    # Без обязательного члена.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("docProps/core.xml", "<cp/>")
    r1 = _docx_structural_validate(buf.getvalue())
    assert any("member_missing" in f and "word/document.xml" in f
               for f in r1.findings)

    # Внешняя связь (AC16).
    src = zipfile.ZipFile(io.BytesIO(good))
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as out:
        for name in src.namelist():
            data = src.read(name)
            if name == "_rels/.rels":
                data = data.replace(
                    b"</Relationships>",
                    b'<Relationship Id="rEvil" Target="http://evil.example/x" '
                    b'TargetMode="External"/></Relationships>',
                )
            out.writestr(name, data)
    r2 = _docx_structural_validate(buf2.getvalue())
    assert r2.result == "failed"
    assert any(f.startswith("external_relationship") for f in r2.findings)

    # Невалидный XML.
    buf3 = io.BytesIO()
    with zipfile.ZipFile(buf3, "w") as out:
        for name in src.namelist():
            data = src.read(name)
            if name == "word/document.xml":
                data = b"<w:document><unclosed>"
            out.writestr(name, data)
    r3 = _docx_structural_validate(buf3.getvalue())
    assert any(f.startswith("xml_invalid") for f in r3.findings)


def test_u13_signature_roundtrip_tamper_binding_and_order():
    """Detached-подпись: roundtrip; порча байтов -- mac_mismatch
    (двухканальная привязка метаданных+байтов); порядок ключей
    манифеста не влияет на MAC."""
    import os

    from apps.api.doc_profiles import (
        SignatureKeyUnavailable,
        sign_content,
        verify_signature_manifest,
    )

    os.environ["CISSTAT_DOC_SIGN_KEY"] = "d9cert-sig-key"
    try:
        payload = b"d9cert-doc-bytes-1.2.3"
        manifest = sign_content(payload, snapshot_sha256="b" * 64,
                                profile_id="prof-sig", profile_version_no=2)
        assert verify_signature_manifest(payload, manifest).result == "passed"
        tampered = payload[:-1] + bytes([payload[-1] ^ 0x01])
        res = verify_signature_manifest(tampered, manifest)
        assert res.result == "failed"
        assert any(f.startswith("mac_mismatch") for f in res.findings)
        # Тело метаданных то же, байты другие -> mismatch (привязка).
        res2 = verify_signature_manifest(b"other-bytes", manifest)
        assert res2.result == "failed"
        # MAC инвариантен к порядку ключей манифеста.
        reordered = dict(reversed(list(manifest.items())))
        assert verify_signature_manifest(payload, reordered).result == "passed"
        # MAC отсутствует.
        no_mac = {k: v for k, v in manifest.items() if k != "mac"}
        res3 = verify_signature_manifest(payload, no_mac)
        assert any(f.startswith("mac_missing") for f in res3.findings)
        # Пустой/неч словарь.
        res4 = verify_signature_manifest(payload, None)
        assert res4.result == "failed"
    finally:
        os.environ.pop("CISSTAT_DOC_SIGN_KEY", None)
    # Без ключа: sign -- честное исключение; verify -- ТОЖЕ исключение
    # (ПИН F-D9C4, акт §5: ветка key_unavailable в _signature_validate
    # недостижима -- _canonical_manifest вызывает _sign_key() раньше
    # проверки ключа; грациозный failed key_unavailable -- мёртвый код;
    # при потере/ротации ключа verify-signature поднимает исключение,
    # HTTP-поведение -- см. a25). После FIX -- инвертировать на failed.
    with pytest.raises(SignatureKeyUnavailable):
        sign_content(payload, snapshot_sha256="b" * 64, profile_id="prof-sig")
    with pytest.raises(SignatureKeyUnavailable):
        verify_signature_manifest(payload, manifest)


def test_u14_validate_output_dispatcher_and_policy_switch():
    from apps.api.doc_profiles import (
        OrgProfileFormatMismatch,
        OrganizationalDocumentProfile,
        validate_profile_output,
    )
    from apps.api.document_renditions import render_snapshot_docx

    snap = seed_snapshot()
    docx_bytes = render_snapshot_docx(snap)
    pdfa_profile = OrganizationalDocumentProfile(
        profile_id="prof-d", name="d9cert-d", version_no=1, format="pdfa"
    )
    docx_profile = OrganizationalDocumentProfile(
        profile_id="prof-d", name="d9cert-d", version_no=1, format="docx"
    )
    assert validate_profile_output(docx_bytes, "docx", docx_profile).result == "passed"
    # Диспетчер выбирает валидатор по ЗАПРОШЕННОМУ формату (fmt),
    # profile.format диспетчеризацию не меняет; docx-байты под
    # pdfa-валидатором (fmt="pdfa") -- честный failed (pdf_header_missing).
    assert validate_profile_output(
        docx_bytes, "pdfa", pdfa_profile
    ).result == "failed"
    assert validate_profile_output(
        docx_bytes, "pdfa", docx_profile
    ).result == "failed"
    with pytest.raises(OrgProfileFormatMismatch):
        validate_profile_output(docx_bytes, "html", docx_profile)
    # Сервисный переключатель политики: validate_conformance=False.
    svc = profile_service()
    off = OrganizationalDocumentProfile(
        profile_id="prof-off", name="d9cert-off", version_no=1, format="docx",
        validate_conformance=False,
    )
    res = svc.validate_output(b"garbage-not-zip", "docx", off)
    assert res.result == "passed"
    assert any("validate_conformance=false" in f for f in res.findings)


# ══════════════════════════════════════════════════════════════════════
# Чистые рендеры docx/pdfa: f(снимок, профиль), AC03/AC05/AC16
# ══════════════════════════════════════════════════════════════════════


def _docx_document_xml(content: bytes) -> str:
    zf = zipfile.ZipFile(io.BytesIO(content))
    return zf.read("word/document.xml").decode("utf-8")


def test_u15_docx_render_deterministic_members_and_decoration():
    from apps.api.document_renditions import render_snapshot_docx

    snap = seed_snapshot()
    profile = make_profile(
        fmt="docx", title_prefix="d9cert · гриф",
        footer_text="d9cert-футер-строка",
        organization="Организация d9cert",
    )
    a = render_snapshot_docx(snap, profile)
    b = render_snapshot_docx(snap, profile)
    assert a == b  # AC03: детерминизм docx
    zf = zipfile.ZipFile(io.BytesIO(a))
    for member in ("[Content_Types].xml", "_rels/.rels", "word/document.xml",
                   "word/styles.xml", "docProps/core.xml"):
        assert member in zf.namelist(), member
    doc = _docx_document_xml(a)
    assert 'TargetMode="External"' not in doc
    assert "d9cert · гриф" in doc            # title_prefix в байтах
    assert "d9cert-футер-строка" in doc      # footer в байтах
    assert "Организация d9cert" in doc       # организация в байтах
    assert "Автоматически сгенерировано" in doc  # обязательная пометка §12.2
    assert snap.snapshot_id in doc and snap.research_run_id in doc


def test_u16_docx_render_escapes_untrusted_text():
    """AC16: недоверенный текст (утверждения/названия) экранирован."""
    from apps.api.document_renditions import render_snapshot_docx

    snap = seed_snapshot()
    snap = replace(
        snap,
        sections=[{
            "title": "Секция <script>alert(1)</script>",
            "code": "S1",
            "claims": [{
                "text": "Утверждение <img src=x onerror=alert(2)> & «кавычки»",
                "validity": "confirmed",
                "evidence_level": "",
                "event_refs": [],
                "result_refs": [],
            }],
        }],
    )
    content = render_snapshot_docx(snap)
    doc = _docx_document_xml(content)
    assert "<script>" not in doc
    assert "<img" not in doc
    assert "&lt;script&gt;" in doc
    assert "&amp;" in doc


def test_u17_pdfa_render_markers_no_forbidden_content_decoration():
    from apps.api.document_renditions import render_snapshot_pdfa

    snap = seed_snapshot()
    profile = make_profile(fmt="pdfa", footer_text="d9cert-футер-pdfа")
    content = render_snapshot_pdfa(snap, profile)
    assert content.startswith(b"%PDF-")
    assert b"pdfaid:part" in content
    assert b"pdfaid:conformance" in content
    assert b"GTS_PDFA1" in content
    assert b"DestOutputProfile" in content
    assert b"FontFile2" in content          # встроенный шрифт базового PDF
    assert b"/Encrypt" not in content
    assert b"/JavaScript" not in content
    assert b"/S /URI" not in content
    assert "d9cert-футер-pdfа".encode("utf-8") in content  # оформление в XMP
    assert b"acsp" in content               # ICC-профиль встроен


def test_u18_pdfa_cross_second_nondeterminism_pin_f_d9c1():
    """ПИН ДЕФЕКТА F-D9C1 (акт, §5): pdfa-рендер НЕ байт-детерминирован
    через границу секунды -- littlecms кладёт wall-clock в ICC-заголовок
    (байты 24:36 профиля). Oracle фиксирует фактическое поведение;
    после DOCLOG-9-FIX инвертировать (рендер обязан стать
    детерминированным). Область поражения ограничена: длины равны,
    расхождения -- единичные байты (поле секунд), docx не затронут."""
    from apps.api.document_renditions import render_snapshot_docx

    snap = seed_snapshot()
    a = render_with_clock(snap)
    time.sleep(1.25)
    b = render_with_clock(snap)
    if a == b:
        # Граница секунды не пересечена (маловероятно, но честно) --
        # оракул не врёт: повторяем до пересечения (максимум 3 попытки).
        for _ in range(3):
            time.sleep(1.25)
            a2 = render_with_clock(snap)
            if a2 != b:
                a = a2
                break
    assert a != b  # ПИН F-D9C1: байты различаются
    diffs = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    assert len(a) == len(b)
    assert len(diffs) <= 4           # поражение ограничено полем секунд
    assert diffs[-1] - diffs[0] <= 2
    assert render_snapshot_docx(snap) == render_snapshot_docx(snap)  # docx чист


def render_with_clock(snap):
    from apps.api.document_renditions import render_snapshot_pdfa

    return render_snapshot_pdfa(snap)


def test_u19_srgb_icc_header_carries_wallclock_pin_f_d9c1():
    """ПИН механизма F-D9C1: ICC-профиль littlecms содержит время
    создания в заголовке (байты 24:36 = UTC-поля год/месяц/день/час/
    минута/секунда) -- детерминизм байтов выпуска нарушен на уровне
    генератора профиля."""
    from apps.api.document_renditions import _srgb_icc_bytes

    icc = _srgb_icc_bytes()
    assert len(icc) >= 128 and icc[36:40] == b"acsp"
    year = int.from_bytes(icc[24:26], "big")
    month = int.from_bytes(icc[26:28], "big")
    day = int.from_bytes(icc[28:30], "big")
    second = int.from_bytes(icc[34:36], "big")
    now = time.gmtime()
    assert year == now.tm_year and month == now.tm_mon and day == now.tm_mday
    assert abs(second - now.tm_sec) <= 2  # поле секунд = wall-clock


def test_u20_pdfa_diff_confined_to_icc_timestamp_f_d9c1_scope():
    """Область поражения F-D9C1 (акт §5): ВСЕ расхождения между двумя
    рендерами одного (снимок, профиль) лежат в поле времени
    ICC-заголовка (байты [start+24, start+36) каждого встроенного
    профиля, сигнатура acsp). Оракул не флакует: если граница секунды
    не пересечена, байты равны (тривиальный pass); если пересечена --
    расхождения обязаны быть в ICC-штампе и нигде больше."""
    from apps.api.document_renditions import render_snapshot_pdfa

    snap = seed_snapshot()
    a = render_snapshot_pdfa(snap)
    b = render_snapshot_pdfa(snap)
    if a == b:
        return  # граница не пересечена -- инвариант тривиально выполнен
    assert len(a) == len(b)
    diffs = [i for i in range(len(a)) if a[i] != b[i]]
    windows = _icc_timestamp_windows(a)
    assert windows, "ICC-профиль не найден в байтах выпуска"
    for idx in diffs:
        assert any(lo <= idx < hi for lo, hi in windows), (
            f"расхождение {idx} вне поля времени ICC: {diffs}"
        )


def test_u33_pdfa_outputintent_structural_catalog():
    """Структурная (не текстуальная) проверка PDF/A-каталога: pypdf
    читает корень -- ровно один OutputIntent, S=/GTS_PDFA1,
    DestOutputProfile привязан; XMP-поток закреплён за /Metadata."""
    import pypdf

    from apps.api.document_renditions import render_snapshot_pdfa

    snap = seed_snapshot()
    content = render_snapshot_pdfa(snap)
    reader = pypdf.PdfReader(io.BytesIO(content))
    root = reader.trailer["/Root"]
    intents = root["/OutputIntents"]
    assert len(intents) == 1
    intent = intents[0].get_object()
    assert intent["/S"] == "/GTS_PDFA1"
    assert "/DestOutputProfile" in intent
    icc_ref = intent.raw_get("/DestOutputProfile")
    assert icc_ref is not None  # ссылка на поток ICC, не литерал
    metadata = root["/Metadata"].get_object()
    xmp = metadata.get_data()
    assert b"pdfaid:part" in xmp and b"pdfaid:conformance" in xmp


def _icc_timestamp_windows(content: bytes) -> list[tuple[int, int]]:
    """Окна полей времени ICC-заголовков в байтах PDF (профиль ищется
    по сигнатуре acsp с проверкой поля размера 588)."""
    windows: list[tuple[int, int]] = []
    pos = 0
    while True:
        idx = content.find(b"acsp", pos)
        if idx < 36:
            break
        start = idx - 36
        size = int.from_bytes(content[start:start + 4], "big")
        if size == 588 and start >= 0:
            windows.append((start + 24, start + 36))
        pos = idx + 4
    return windows


# ══════════════════════════════════════════════════════════════════════
# §19-доказательства через полный цикл (сервис+worker)
# ══════════════════════════════════════════════════════════════════════


def test_u21_docx_end_to_end_ready_with_proof_records():
    from apps.api.document_jobs import JOB_READY

    snap = seed_snapshot()
    profile = make_profile(fmt="docx")
    job, rendition = render_with_profile(snap, "docx", profile)
    assert job.state == JOB_READY, job.error_code
    assert rendition is not None and rendition.state == "ready"
    assert rendition.org_profile_id == profile.profile_id
    validations = profile_service().registry.list_validations(
        rendition.rendition_id
    )
    # §19: запись валидации пишется ДАЖЕ при passed (доказательство).
    assert len(validations) == 1
    rec = validations[0]
    assert rec.result == "passed"
    assert rec.validator == "docx-structural/1"
    assert rec.rendition_id == rendition.rendition_id
    assert rec.job_id == job.job_id
    assert rec.run_id == snap.research_run_id
    assert rec.profile_id == profile.profile_id
    assert rec.profile_version_no == profile.version_no
    assert audit_count("rendition_validated") == 1  # standard-класс


def test_u22_failed_validation_honest_terminal_no_ready_bytes(monkeypatch):
    """AC08 по построению: failed-валидация -- terminal failed
    profile_validation_failed; ready-файла нет; запись с
    rendition_id="" (findings сохранены)."""
    from apps.api import document_jobs
    from apps.api.document_jobs import JOB_FAILED
    from apps.api.document_renditions import render_snapshot_pdf

    snap = seed_snapshot()
    profile = make_profile(fmt="pdfa")
    # Честная подмена: под именем pdfa -- ОБЫЧНЫЙ PDF (не названием).
    monkeypatch.setattr(
        document_jobs, "render_snapshot_pdfa",
        lambda *a, **kw: render_snapshot_pdf(snap),
    )
    job, rendition = render_with_profile(snap, "pdfa", profile)
    assert job.state == JOB_FAILED
    assert job.error_code == "profile_validation_failed"
    assert not job.rendition_id
    assert rendition is None
    failed_records = profile_service().registry.list_validations_by_job(
        job.job_id
    )
    assert len(failed_records) == 1
    rec = failed_records[0]
    assert rec.result == "failed" and rec.rendition_id == ""
    assert rec.validator == "pdfa-structural/1" and rec.findings
    assert rendition is None and audit_count("rendition_validated") == 1


def test_u23_sign_flow_manifest_persisted_and_verifiable():
    import os

    os.environ["CISSTAT_DOC_SIGN_KEY"] = "d9cert-sign-secret-7777"
    try:
        snap = seed_snapshot()
        profile = make_profile(fmt="docx", sign_contents=True)
        job, rendition = render_with_profile(snap, "docx", profile)
        from apps.api.document_jobs import JOB_READY

        assert job.state == JOB_READY, job.error_code
        validations = profile_service().registry.list_validations(
            rendition.rendition_id
        )
        sig = [v for v in validations if v.validator == "signature/1"]
        assert len(sig) == 1
        manifest = sig[0].signature_manifest
        assert manifest and manifest["algorithm"] == "HMAC-SHA256"
        assert manifest["content_sha256"] == rendition.content_sha256
        assert manifest["profile_id"] == profile.profile_id
        # Независимая верификация сохранённых байтов.
        from apps.api.doc_profiles import verify_signature_manifest

        stored = delivery().registry.get_rendition(rendition.rendition_id)
        assert verify_signature_manifest(
            stored.content_bytes, dict(manifest)
        ).result == "passed"
    finally:
        os.environ.pop("CISSTAT_DOC_SIGN_KEY", None)


def test_u24_sign_without_key_is_honest_failed():
    import os

    os.environ.pop("CISSTAT_DOC_SIGN_KEY", None)
    snap = seed_snapshot()
    profile = make_profile(fmt="docx", sign_contents=True)
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_FAILED

    assert job.state == JOB_FAILED
    assert job.error_code == "sign_key_unavailable"
    assert rendition is None  # тихая неподписанная ready запрещена


def test_u25_anchor_append_only_bound_to_bytes():
    snap = seed_snapshot()
    profile = make_profile(fmt="docx", anchor_registry=True)
    job, rendition = render_with_profile(snap, "docx", profile)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    anchors = profile_service().registry.list_anchors(rendition.rendition_id)
    assert len(anchors) == 1
    assert anchors[0].content_sha256 == rendition.content_sha256
    assert anchors[0].profile_id == profile.profile_id
    assert anchors[0].anchor_id.startswith("anchor-")
    assert audit_count("rendition_anchored") == 1


def test_u26_worm_hold_on_document_with_reason():
    from apps.api.document_lifecycle import DocumentLifecycleService

    snap = seed_snapshot()
    _document, revision = seed_document_revision(snap)
    profile = make_profile(fmt="docx", worm_lock=True)
    job, rendition = render_with_profile(
        snap, "docx", profile, revision_id=revision.revision_id
    )
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY, job.error_code
    stored = delivery().registry.get_revision(job.revision_id)
    assert stored is not None
    retention = DocumentLifecycleService.create_default().registry.get_retention(
        stored.document_id
    )
    assert retention is not None and retention.hold is True
    assert retention.hold_reason == f"org_profile_worm:{profile.profile_id}"
    # Идемпотентный повтор (upsert, hold не снимается).
    profile_service().apply_worm_hold(
        profile, document_id=stored.document_id,
        run_id=snap.research_run_id, subject=admin_subject(),
    )
    again = DocumentLifecycleService.create_default().registry.get_retention(
        stored.document_id
    )
    assert again.hold is True


def test_u27_profile_mismatch_same_target_both_phases():
    """AC09/§11: одна визуальная форма на цель. Готовая цель с другим
    профилем -- OrgProfileMismatchError; АКТИВНОЕ задание с другим
    профилем -- тоже mismatch."""
    from apps.api.doc_profiles import OrgProfileMismatchError
    from apps.api.document_jobs import JOB_READY

    snap = seed_snapshot()
    profile_a = make_profile(name="d9cert-ma", fmt="docx", version_no=1)
    profile_b = make_profile(name="d9cert-mb", fmt="docx", version_no=1)
    job, rendition = render_with_profile(snap, "docx", profile_a)
    assert job.state == JOB_READY
    service = delivery()
    with pytest.raises(OrgProfileMismatchError):
        service.request_rendition(
            snap, format="docx", org_profile_id=profile_b.profile_id,
            subject=subject_of(SESSION_A), session_id=SESSION_A,
        )
    # Активная фаза: новое задание (другой снимок) ставится в очередь,
    # затем повторный заказ с другим профилем до исполнения worker'а.
    snap2 = seed_snapshot()
    queued, _r = service.request_rendition(
        snap2, format="docx", org_profile_id=profile_a.profile_id,
        subject=subject_of(SESSION_A), session_id=SESSION_A,
    )
    assert queued.state in ("queued", "rendering")
    with pytest.raises(OrgProfileMismatchError):
        service.request_rendition(
            snap2, format="docx", org_profile_id=profile_b.profile_id,
            subject=subject_of(SESSION_A), session_id=SESSION_A,
        )
    # Тот же профиль -- идемпотентно: тот же job, БЕЗ нового задания.
    same, _r2 = service.request_rendition(
        snap2, format="docx", org_profile_id=profile_a.profile_id,
        subject=subject_of(SESSION_A), session_id=SESSION_A,
    )
    assert same.job_id == queued.job_id


def test_u28_request_gates_catalog():
    """Каталог гейтов заказа: docx/pdfa БЕЗ профиля -- OrgProfileRequired;
    профиль на P0-формат -- FormatMismatch; неизвестный -- NotFound;
    retired -- Retired; чужой формат профиля -- FormatMismatch."""
    from apps.api.doc_profiles import (
        OrgProfileFormatMismatch,
        OrgProfileNotFound,
        OrgProfileRequired,
        OrgProfileRetired,
    )

    snap = seed_snapshot()
    service = delivery()
    subject = subject_of(SESSION_A)
    with pytest.raises(OrgProfileRequired):
        service.request_rendition(snap, format="docx", subject=subject,
                                  session_id=SESSION_A)
    with pytest.raises(OrgProfileRequired):
        service.request_rendition(snap, format="pdfa", subject=subject,
                                  session_id=SESSION_A)
    profile = make_profile(fmt="pdfa")
    with pytest.raises(OrgProfileFormatMismatch):
        service.request_rendition(
            snap, format="md", org_profile_id=profile.profile_id,
            subject=subject, session_id=SESSION_A,
        )
    with pytest.raises(OrgProfileNotFound):
        service.request_rendition(
            snap, format="pdfa", org_profile_id="prof-nope",
            subject=subject, session_id=SESSION_A,
        )
    profile_service().retire_profile(profile.profile_id, admin_subject())
    with pytest.raises(OrgProfileRetired):
        service.request_rendition(
            snap, format="pdfa", org_profile_id=profile.profile_id,
            subject=subject, session_id=SESSION_A,
        )
    docx_profile = make_profile(name="d9cert-fmt-x", fmt="docx", version_no=1)
    with pytest.raises(OrgProfileFormatMismatch):
        service.request_rendition(
            snap, format="pdfa", org_profile_id=docx_profile.profile_id,
            subject=subject, session_id=SESSION_A,
        )


def test_u29_worker_rechecks_policy_at_execution_time():
    """Retire между постановкой и исполнением -- честный terminal failed
    org_profile_unavailable (не тихий рендер по старому профилю)."""
    from apps.api.document_jobs import JOB_FAILED

    snap = seed_snapshot()
    profile = make_profile(fmt="docx")
    service = delivery()
    job, _r = service.request_rendition(
        snap, format="docx", org_profile_id=profile.profile_id,
        subject=subject_of(SESSION_A), session_id=SESSION_A,
    )
    profile_service().retire_profile(profile.profile_id, admin_subject())
    from scripts.doclog9cert.conftest import run_worker_once

    run_worker_once()
    done = service.registry.get_job(job.job_id)
    assert done.state == JOB_FAILED
    assert done.error_code == "org_profile_unavailable"


def test_u30_legacy_profileless_rendition_mismatch():
    """Безпрофильный legacy-выпуск (org_profile_id='') не может быть
    перекрыт профильным запросом той же цели -- mismatch (профиль --
    часть формы)."""
    from apps.api.doc_profiles import OrgProfileMismatchError
    from apps.api.document_jobs import JOB_READY

    snap = seed_snapshot()
    service = delivery()
    job, _r = service.request_rendition(
        snap, format="md", subject=subject_of(SESSION_A),
        session_id=SESSION_A,
    )
    assert job.state == JOB_READY  # P0 синхронно
    profile = make_profile(name="d9cert-legacy", fmt="pdfa")
    # md вне PROFILE_FORMATS: профиль применим только к docx/pdfa --
    # для md-цели профильный заказ невозможен в принципе (FormatMismatch),
    # что и есть честная граница «одна визуальная форма на цель».
    from apps.api.doc_profiles import OrgProfileFormatMismatch

    with pytest.raises(OrgProfileFormatMismatch):
        service.request_rendition(
            snap, format="md", org_profile_id=profile.profile_id,
            subject=subject_of(SESSION_A), session_id=SESSION_A,
        )


# ══════════════════════════════════════════════════════════════════════
# Реестр: паритет/порядок/изоляция
# ══════════════════════════════════════════════════════════════════════


def test_u31_memory_registry_order_filter_and_probe():
    svc = profile_service()
    subject = admin_subject()
    svc.create_profile(name="d9cert-b", version_no=2, format="pdfa",
                       subject=subject)
    svc.create_profile(name="d9cert-b", version_no=1, format="docx",
                       subject=subject)
    svc.create_profile(name="d9cert-a", version_no=1, format="pdfa",
                       subject=subject)
    names = [(p.name, p.version_no) for p in svc.registry.list_profiles()]
    assert names == sorted(names)
    docx_only = svc.registry.list_profiles("docx")
    assert all(p.format == "docx" for p in docx_only)
    assert len(docx_only) == 1
    probe = svc.registry.readiness_probe()
    assert probe["backend"] == "memory" and probe["profiles"] == 3
    dup = svc.registry.find_duplicate("d9cert-b", 1)
    assert dup is not None and dup.format == "docx"
    assert svc.registry.find_duplicate("d9cert-b", 9) is None


def test_u32_validation_record_version_binding():
    """Запись валидации привязывает ВЕРСИЮ профиля (не только id):
    новая версия того же имени -- свои записи."""
    svc = profile_service()
    subject = admin_subject()
    p1 = svc.create_profile(name="d9cert-vb", version_no=1, format="docx",
                            subject=subject)
    p2 = svc.create_profile(name="d9cert-vb", version_no=2, format="docx",
                            subject=subject)
    assert p1.profile_id != p2.profile_id
    snap = seed_snapshot()
    job, rendition = render_with_profile(snap, "docx", p2)
    from apps.api.document_jobs import JOB_READY

    assert job.state == JOB_READY
    records = svc.registry.list_validations(rendition.rendition_id)
    assert all(r.profile_id == p2.profile_id for r in records)
    assert all(r.profile_version_no == 2 for r in records)
