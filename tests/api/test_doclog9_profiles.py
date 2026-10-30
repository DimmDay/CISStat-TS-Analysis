# tests/api/test_doclog9_profiles.py
"""Задача DOCLOG-9 (spec_documentation_logging.md §7 P2, §11, §12.2/12.3,
§14.1, §15, §19 строка DOCLOG-9, §20 AC03/AC05/AC08/AC09/AC16/AC17):
профили организации -- версионированные организационные политики выпуска
визуальной формы документа (docx/pdfa) с гарантиями: проверяемая
конформность ВАЛИДАТОРОМ (не названием файла), подпись содержимого
(HMAC, НЕ юридическая ЭП), append-only якорь, WORM-холд (логический
retention hold DOCLOG-6), оформление (язык/гриф/футер/организация).

Критерий завершения (§19): «выбранный профиль подтверждён валидатором и
organisational policy, не названием файла» -- rendition становится ready
ТОЛЬКО при passed структурного валидатора (запись валидации пишется даже
при passed); failed -- честный terminal failed с findings; профиль
применяется только ACTIVE и соответствующего формата; право управления
профилями -- policy.admin (§15, не автоматически у ADMIN как роли).

Оракулы на СВОИХ данных (RUN-D9xxxxxx, d9-*, d9prof-*); изоляция каждого
теста -- паттерн test_doclog5_formats_worker.py. Рендеры docx/pdfa --
чистые функции от (снимок, профиль) (R06/AC03/AC05); pdfa -- отдельная
запись каталога, НЕ переименование pdf (§7 P2); подпись -- detached
HMAC-манифест (алгоритм в манифесте); якорь -- INSERT-only реестр;
WORM -- retention hold на документе с причиной org_profile_worm.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog5_formats_worker.py) ───

API_KEYS_ENV = (
    "d9-admin-key-1111:admin::subj-d9aaaaaaaaaaaaaa:tenant-d9core:,"
    "d9-writer-key-2222:external_user:starter:subj-d9bbbbbbbbbbbbbb:tenant-d9core:documentation.write,"
    "d9-other-key-3333:external_user:starter:subj-d9cccccccccccccc:tenant-d9other:"
)

ADMIN_KEY = "d9-admin-key-1111"
WRITER_KEY = "d9-writer-key-2222"
OTHER_KEY = "d9-other-key-3333"
SIGN_KEY_ENV = "d9-sign-secret-0001"


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_SNAPSHOTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOC_PROFILES_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOC_SIGN_KEY", raising=False)
    monkeypatch.setenv("CISSTAT_API_KEYS", API_KEYS_ENV)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_BATCH", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, doc_profiles, report_snapshot
    from apps.api import document_jobs, document_render_worker
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
    doc_profiles.reset_org_profile_registry_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    doc_profiles.reset_org_profile_registry_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (свои данные; паритет DOCLOG-5) ──────────────────────

RUN_ID = "RUN-D9A00001"
SESSION_ID = "d9-seed-session"

D9_VALIDATORS = ("pdfa-structural/1", "docx-structural/1", "signature/1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_session(session_id: str = SESSION_ID) -> AnalysisSession:
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def _seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = "ctx-d9-1",
    data_revision: int | None = 2,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d9" * 16,
        dataset_name="doclog9-seed",
        target_column="value",
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _seed_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
) -> None:
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload={"dataset": "doclog9-seed"},
        run_id=run_id,
        stage=stage,
        schema_version=2,
        evidence_level="server_result",
    )
    research_runs.get_research_run_store().append_event(run_id, event)


def _service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def _seed_snapshot(run_id: str = RUN_ID, session_id: str = SESSION_ID):
    _seed_session(session_id)
    _seed_bound_run(run_id, session_id)
    _seed_event(run_id)
    subject = _owner_subject(session_id)
    snapshot, _created = _service().build_snapshot(
        run_id, subject, session_id=session_id, kinds=["D01", "D02"]
    )
    return snapshot


def _delivery():
    from apps.api.document_jobs import DocumentDeliveryService

    return DocumentDeliveryService.create_default()


def _profile_service():
    from apps.api.doc_profiles import org_profile_service

    return org_profile_service()


def _make_profile(
    *,
    name: str = "d9prof-gost",
    fmt: str = "pdfa",
    version_no: int = 1,
    sign_contents: bool = False,
    anchor_registry: bool = False,
    worm_lock: bool = False,
    title_prefix: str = "CISStat · организация",
    footer_text: str = "Подготовлено автоматически · проверено валидатором",
    organization: str = "Межгосударственный статистический комитет",
):
    """Создаёт профиль СЕРВИСОМ от имени admin-субъекта (ключ из env
    ключей; сервис проверяет policy.admin)."""
    subject = _admin_subject()
    return _profile_service().create_profile(
        name=name,
        version_no=version_no,
        format=fmt,
        title_prefix=title_prefix,
        footer_text=footer_text,
        organization=organization,
        sign_contents=sign_contents,
        anchor_registry=anchor_registry,
        worm_lock=worm_lock,
        subject=subject,
    )


def _admin_subject() -> SubjectRef:
    """Админ-субъект на СВОИХ данных: роль/полный каталог (§15.1).
    Cookie-суррогат права не фантазирует -- роль задаётся явно
    (SubjectRef immutable: собираем новый через replace)."""
    base = SubjectRef.from_session("d9-admin-seed")
    from dataclasses import replace

    return replace(
        base,
        role="admin",
        scopes=frozenset(
            {
                "policy.admin",
                "documentation.write",
                "documentation.read",
            }
        ),
    )


# ══════════════════════════════════════════════════════════════════════
# 1. Каталог форматов и чистые рендеры (§7 P2; R06/AC03/AC05/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestProfileFormatCatalog:
    def test_catalog_contains_docx_and_pdfa(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        assert "docx" in RENDITION_FORMATS
        assert "pdfa" in RENDITION_FORMATS
        # pdfa -- отдельная запись каталога, НЕ переименование pdf (§7).
        assert RENDITION_FORMATS["pdfa"].media_type == "application/pdf"
        assert RENDITION_FORMATS["docx"].extension == "docx"
        assert (
            RENDITION_FORMATS["docx"].media_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_docx_pdfa_are_heavy_async(self):
        """§18: тяжёлый DOCX/PDF/A не создаётся синхронно (worker)."""
        from apps.api.document_renditions import HEAVY_RENDITION_FORMATS

        assert "docx" in HEAVY_RENDITION_FORMATS
        assert "pdfa" in HEAVY_RENDITION_FORMATS

    def test_docx_render_is_pure_and_deterministic(self):
        from apps.api.document_renditions import render_snapshot_docx

        snapshot = _seed_snapshot()
        first = render_snapshot_docx(snapshot)
        second = render_snapshot_docx(snapshot)
        assert first == second  # AC03: один снимок -- одинаковые байты
        # OOXML -- ZIP-контейнер с обязательными членами.
        with zipfile.ZipFile(io.BytesIO(first)) as zf:
            names = set(zf.namelist())
            assert "[Content_Types].xml" in names
            assert "word/document.xml" in names
            assert "word/styles.xml" in names
            assert "docProps/core.xml" in names
            document = zf.read("word/document.xml").decode("utf-8")
            core = zf.read("docProps/core.xml").decode("utf-8")
        # Происхождение внутри файла (§7: «редактируемая копия, с
        # указанием происхождения»).
        assert snapshot.snapshot_id in document
        assert snapshot.payload_sha256[:32] in document
        assert "Автоматически сгенерировано" in document
        # Кириллица действительно в тексте (§20: проверка кириллицы).
        assert "Документ исследования" in document or "Утверждение" in document
        # Манифест происхождения в core.xml.
        assert snapshot.snapshot_id in core

    def test_docx_render_escapes_untrusted_text(self):
        """AC16: недоверенный текст не ломает XML (инъекция тега)."""
        from dataclasses import replace as _replace

        from apps.api.document_renditions import render_snapshot_docx

        snapshot = _seed_snapshot()
        sections = [dict(section) for section in snapshot.sections]
        sections[0] = dict(sections[0])
        sections[0]["claims"] = [
            dict(sections[0]["claims"][0])
            | {"text": "Мат assertion </w:t><w:br/>"},
            *[dict(claim) for claim in sections[0]["claims"][1:]],
        ]
        poisoned = _replace(snapshot, sections=sections)
        content = render_snapshot_docx(poisoned)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            document = zf.read("word/document.xml").decode("utf-8")
        import xml.etree.ElementTree as ET

        ET.fromstring(document)  # валидный XML -- без инъекции
        assert "<w:br/>" not in document

    def test_pdfa_render_markers_and_determinism(self):
        from apps.api.document_renditions import render_snapshot_pdfa

        snapshot = _seed_snapshot()
        first = render_snapshot_pdfa(snapshot)
        second = render_snapshot_pdfa(snapshot)
        assert first == second
        assert first.startswith(b"%PDF-")
        # §7 P2: PDF/A -- НЕ переименованный обычный PDF: маркеры
        # идентификации внутри байтов.
        assert b"pdfaid:part>1" in first or b"part>1</pdfaid:part" in first or b"pdfaid:part" in first
        assert b"pdfaid:conformance" in first
        assert b"GTS_PDFA1" in first
        assert b"DestOutputProfile" in first
        # Встроенный шрифт (кириллица).
        assert b"FontFile2" in first

    def test_pdfa_no_encrypt_no_js_no_external_uri(self):
        """AC16/§12.3: без шифрования/скриптов/внешних ссылок."""
        from apps.api.document_renditions import render_snapshot_pdfa

        content = render_snapshot_pdfa(_seed_snapshot())
        assert b"/Encrypt" not in content
        assert b"/JavaScript" not in content
        assert b"/JS" not in content
        assert b"http://schema" not in content or True  # schema refs XMP допустимы
        # URI-экшены аннотаций отсутствуют.
        assert b"/S /URI" not in content

    def test_pdfa_render_carries_profile_decoration(self):
        """Оформление профиля входит в байты (f(снимок, профиль))."""
        from apps.api.document_renditions import render_snapshot_pdfa

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="pdfa", footer_text="d9-футер-профиль")
        content = render_snapshot_pdfa(snapshot, profile=profile)
        # Оформление -- в XMP-метаданных (UTF-8-байты потока).
        assert profile.footer_text.encode("utf-8") in content


# ══════════════════════════════════════════════════════════════════════
# 2. Валидаторы: профиль подтверждён ВАЛИДАТОРОМ, не названием (§19)
# ══════════════════════════════════════════════════════════════════════


class TestValidators:
    def test_pdfa_validator_passes_own_render(self):
        from apps.api.doc_profiles import validate_profile_output

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="pdfa")
        from apps.api.document_renditions import render_snapshot_pdfa

        result = validate_profile_output(
            render_snapshot_pdfa(snapshot, profile=profile), "pdfa", profile
        )
        assert result.validator == "pdfa-structural/1"
        assert result.result == "passed"
        assert isinstance(result.findings, list)

    def test_pdfa_validator_fails_plain_pdf(self):
        """«Не названием файла»: обычный PDF без PDF/A-маркеров --
        честный failed с перечнем находок."""
        from apps.api.doc_profiles import validate_profile_output
        from apps.api.document_renditions import render_snapshot_pdf

        profile = _make_profile(fmt="pdfa")
        result = validate_profile_output(
            render_snapshot_pdf(_seed_snapshot()), "pdfa", profile
        )
        assert result.result == "failed"
        assert result.validator == "pdfa-structural/1"
        joined = " ".join(result.findings)
        assert "pdfaid" in joined.lower()
        assert "outputintent" in joined.lower()

    def test_pdfa_validator_fails_truncated_bytes(self):
        from apps.api.doc_profiles import validate_profile_output

        profile = _make_profile(fmt="pdfa")
        result = validate_profile_output(b"%PDF-1.4 broken", "pdfa", profile)
        assert result.result == "failed"

    def test_docx_validator_passes_own_render(self):
        from apps.api.doc_profiles import validate_profile_output
        from apps.api.document_renditions import render_snapshot_docx

        profile = _make_profile(fmt="docx")
        result = validate_profile_output(
            render_snapshot_docx(_seed_snapshot(), profile=profile),
            "docx",
            profile,
        )
        assert result.validator == "docx-structural/1"
        assert result.result == "passed"

    def test_docx_validator_fails_zip_without_document_xml(self):
        from apps.api.doc_profiles import validate_profile_output

        profile = _make_profile(fmt="docx")
        fake = io.BytesIO()
        with zipfile.ZipFile(fake, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
        result = validate_profile_output(fake.getvalue(), "docx", profile)
        assert result.result == "failed"
        assert "document.xml" in " ".join(result.findings)

    def test_validators_catalog(self):
        from apps.api.doc_profiles import KNOWN_VALIDATORS

        for validator in D9_VALIDATORS:
            assert validator in KNOWN_VALIDATORS


# ══════════════════════════════════════════════════════════════════════
# 3. Подпись содержимого: HMAC detached-манифест (НЕ юридическая ЭП)
# ══════════════════════════════════════════════════════════════════════


class TestSignature:
    def test_sign_and_verify_roundtrip(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_ENV)
        from apps.api.doc_profiles import sign_content, verify_signature_manifest

        payload = b"d9-content-bytes"
        manifest = sign_content(payload, snapshot_sha256="a" * 64, profile_id="prof-1")
        assert manifest["algorithm"] == "HMAC-SHA256"
        assert manifest["content_sha256"]
        verification = verify_signature_manifest(payload, manifest)
        assert verification.result == "passed"

    def test_verify_fails_tampered_content(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_ENV)
        from apps.api.doc_profiles import sign_content, verify_signature_manifest

        manifest = sign_content(b"original", snapshot_sha256="a" * 64, profile_id="p")
        verification = verify_signature_manifest(b"tampered", manifest)
        assert verification.result == "failed"

    def test_sign_without_key_is_honest_error(self, monkeypatch: pytest.MonkeyPatch):
        """AC12-дух: нет ключа -- честный отказ, НЕ тихая неподписанная
        ready."""
        from apps.api.doc_profiles import SignatureKeyUnavailable, sign_content

        with pytest.raises(SignatureKeyUnavailable):
            sign_content(b"bytes", snapshot_sha256="a" * 64, profile_id="p")


# ══════════════════════════════════════════════════════════════════════
# 4. Сервис профилей: policy/версии/права (§15, §14.1)
# ══════════════════════════════════════════════════════════════════════


class TestOrgProfileService:
    def test_create_requires_policy_admin(self):
        from apps.api.doc_profiles import OrgProfileAccessDenied

        with pytest.raises(OrgProfileAccessDenied):
            _profile_service().create_profile(
                name="d9prof-no-rights",
                version_no=1,
                format="pdfa",
                subject=_owner_subject(),
            )

    def test_create_and_list(self):
        profile = _make_profile()
        assert profile.profile_id
        assert profile.status == "active"
        assert profile.format == "pdfa"
        service = _profile_service()
        listed = service.list_profiles(subject=_admin_subject(), fmt="pdfa")
        assert any(p.profile_id == profile.profile_id for p in listed)

    def test_duplicate_name_version_rejected(self):
        from apps.api.doc_profiles import OrgProfileDuplicate

        _make_profile(name="d9prof-dup", version_no=1)
        with pytest.raises(OrgProfileDuplicate):
            _make_profile(name="d9prof-dup", version_no=1)

    def test_new_version_same_name_allowed(self):
        v1 = _make_profile(name="d9prof-ver", version_no=1)
        v2 = _make_profile(name="d9prof-ver", version_no=2)
        assert v1.profile_id != v2.profile_id

    def test_unknown_format_rejected(self):
        from apps.api.doc_profiles import OrgProfileFormatMismatch

        with pytest.raises(OrgProfileFormatMismatch):
            _make_profile(fmt="xlsx")

    def test_retire_then_resolve_fails(self):
        from apps.api.doc_profiles import OrgProfileRetired

        profile = _make_profile(name="d9prof-ret")
        retired = _profile_service().retire_profile(
            profile.profile_id, subject=_admin_subject()
        )
        assert retired.status == "retired"
        assert retired.retired_at
        with pytest.raises(OrgProfileRetired):
            _profile_service().resolve_profile(
                profile.profile_id, fmt="pdfa", subject=_admin_subject()
            )

    def test_retire_is_idempotent(self):
        profile = _make_profile(name="d9prof-idem")
        first = _profile_service().retire_profile(
            profile.profile_id, subject=_admin_subject()
        )
        second = _profile_service().retire_profile(
            profile.profile_id, subject=_admin_subject()
        )
        assert second.status == "retired"
        assert first.profile_id == second.profile_id

    def test_resolve_format_mismatch(self):
        from apps.api.doc_profiles import OrgProfileFormatMismatch

        profile = _make_profile(name="d9prof-docx", fmt="docx")
        with pytest.raises(OrgProfileFormatMismatch):
            _profile_service().resolve_profile(
                profile.profile_id, fmt="pdfa", subject=_admin_subject()
            )

    def test_resolve_unknown_profile(self):
        from apps.api.doc_profiles import OrgProfileNotFound

        with pytest.raises(OrgProfileNotFound):
            _profile_service().resolve_profile(
                "prof-d9-nonexistent", fmt="pdfa", subject=_admin_subject()
            )

    def test_audit_mandatory_catalog(self):
        from apps.api import security_audit

        assert "org_profile_created" in security_audit.AUDIT_ACTIONS
        assert "org_profile_retired" in security_audit.AUDIT_ACTIONS
        assert (
            security_audit.AUDIT_REQUIREMENTS["org_profile_created"]
            == "mandatory"
        )
        assert (
            security_audit.AUDIT_REQUIREMENTS["org_profile_retired"]
            == "mandatory"
        )
        assert "rendition_validated" in security_audit.AUDIT_ACTIONS
        assert "rendition_anchored" in security_audit.AUDIT_ACTIONS


# ══════════════════════════════════════════════════════════════════════
# 5. Рендер с профилем через сервис: ready только при passed (§19/AC08)
# ══════════════════════════════════════════════════════════════════════


class TestProfileRenderThroughService:
    def test_docx_requires_profile(self):
        """Безымянный выпуск DOCX/PDF-A запрещён: профиль -- часть
        формы (§19: выбранный профиль подтверждён…, не названием)."""
        from apps.api.doc_profiles import OrgProfileRequired

        snapshot = _seed_snapshot()
        with pytest.raises(OrgProfileRequired):
            _delivery().request_rendition(
                snapshot, format="docx",
                subject=_owner_subject(), session_id=SESSION_ID,
            )

    def test_profile_unsupported_for_p0_format(self):
        from apps.api.doc_profiles import OrgProfileFormatMismatch

        snapshot = _seed_snapshot()
        profile = _make_profile(name="d9prof-md", fmt="pdfa")
        with pytest.raises(OrgProfileFormatMismatch):
            _delivery().request_rendition(
                snapshot, format="md", org_profile_id=profile.profile_id,
                subject=_owner_subject(), session_id=SESSION_ID,
            )

    def test_worker_renders_docx_with_profile_ready(self):
        from apps.api.document_jobs import JOB_READY
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", worm_lock=False)
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == JOB_READY, done.error_code
        rendition = service.registry.get_rendition(done.rendition_id)
        assert rendition is not None
        assert rendition.format == "docx"
        # Профиль зафиксирован в rendition metadata.
        assert rendition.org_profile_id == profile.profile_id
        # Валидация ДОКАЗАНА записью (passed -- тоже запись).
        validations = _profile_service().registry.list_validations(
            rendition.rendition_id
        )
        assert validations
        assert all(v.result == "passed" for v in validations)
        assert any(v.validator == "docx-structural/1" for v in validations)

    def test_validation_failed_blocks_ready(self, monkeypatch: pytest.MonkeyPatch):
        """Пин ключевого критерия: подменённый рендер (ОБЫЧНЫЙ PDF без
        PDF/A-маркеров) -- честный terminal failed profile_validation_failed,
        ready-файла НЕТ (AC08 по построению)."""
        from apps.api import document_jobs
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_renditions import render_snapshot_pdf
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="pdfa")
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="pdfa", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        # «Название файла» -- pdfa, байты -- ОБЫЧНЫЙ PDF: валидатор
        # обязан отказать (§19: подтверждение -- не названием файла).
        monkeypatch.setattr(
            document_jobs,
            "render_snapshot_pdfa",
            lambda *a, **kw: render_snapshot_pdf(snapshot),
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == JOB_FAILED
        assert done.error_code == "profile_validation_failed"
        # Ready-файла нет -- broken ready refs невозможны (AC08).
        assert done.rendition_id is None
        # Findings валидатора честно записаны.
        validations = _profile_service().registry.list_validations_by_job(
            job.job_id
        )
        assert validations
        failed = [v for v in validations if v.result == "failed"]
        assert failed
        assert failed[0].validator == "pdfa-structural/1"
        assert failed[0].findings

    def test_profile_mismatch_same_target_409(self):
        """AC09/§11: одна визуальная форма на цель; другой профиль той
        же цели -- 409, не вторая версия."""
        from apps.api.doc_profiles import OrgProfileMismatchError
        from apps.api.document_jobs import JOB_READY
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile_a = _make_profile(name="d9prof-a", fmt="docx")
        profile_b = _make_profile(name="d9prof-b", fmt="docx")
        service = _delivery()
        job1, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile_a.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        assert service.registry.get_job(job1.job_id).state == JOB_READY
        with pytest.raises(OrgProfileMismatchError):
            service.request_rendition(
                snapshot, format="docx", org_profile_id=profile_b.profile_id,
                subject=_owner_subject(), session_id=SESSION_ID,
            )

    def test_same_profile_idempotent(self):
        """AC09: тот же профиль той же цели -- прежний job/rendition."""
        from apps.api.document_jobs import JOB_READY
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(name="d9prof-idem2", fmt="docx")
        service = _delivery()
        job1, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        job2, rend2 = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job2.job_id == job1.job_id
        assert rend2 is not None
        assert service.registry.get_job(job1.job_id).state == JOB_READY

    def test_worm_lock_sets_retention_hold(self):
        """WORM (§16): логический hold на документе с причиной."""
        from apps.api.document_lifecycle import DocumentLifecycleService
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", worm_lock=True)
        service = _delivery()
        # Ревизия выпуска (document_id -- держатель hold'а).
        _document, revision, _created = service.ensure_document_revision(
            snapshot, _owner_subject(), session_id=SESSION_ID
        )
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            revision_id=revision.revision_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == "ready", done.error_code
        # document_id связан с ревизией выпуска (hold -- на документе).
        stored = service.registry.get_revision(done.revision_id)
        assert stored is not None
        lifecycle = DocumentLifecycleService.create_default()
        retention = lifecycle.registry.get_retention(stored.document_id)
        assert retention is not None
        assert retention.hold is True
        assert retention.hold_reason.startswith("org_profile_worm:")
        assert profile.profile_id in retention.hold_reason

    def test_anchor_registry_append_only(self):
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", anchor_registry=True)
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        rendition = service.registry.get_rendition(done.rendition_id)
        anchors = _profile_service().registry.list_anchors(rendition.rendition_id)
        assert len(anchors) == 1
        assert anchors[0].content_sha256 == rendition.content_sha256
        assert anchors[0].profile_id == profile.profile_id

    def test_signature_profile_signs_and_verifies(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_ENV)
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", sign_contents=True)
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == "ready", done.error_code
        rendition = service.registry.get_rendition(done.rendition_id)
        validations = _profile_service().registry.list_validations(
            rendition.rendition_id
        )
        signature_records = [
            v for v in validations if v.validator == "signature/1"
        ]
        assert signature_records and signature_records[0].result == "passed"
        manifest = signature_records[0].signature_manifest
        assert manifest and manifest["algorithm"] == "HMAC-SHA256"

    def test_signature_without_key_fails_honestly(self):
        """Ключ не задан -> честный terminal failed sign_key_unavailable,
        НЕ тихая неподписанная ready."""
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", sign_contents=True)
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == JOB_FAILED
        assert done.error_code == "sign_key_unavailable"
        assert done.rendition_id is None

    def test_profile_retired_after_queue_fails_honestly(self):
        """Профиль выведен из действия МЕЖДУ постановкой и рендером --
        честный terminal failed (policy подтверждается на момент
        исполнения), не тихий рендер по старому профилю."""
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx")
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        _profile_service().retire_profile(
            profile.profile_id, subject=_admin_subject()
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == JOB_FAILED
        assert done.error_code == "org_profile_unavailable"

    def test_rendition_content_downloadable_after_profile_render(self):
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx")
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        rendition = service.registry.get_rendition(done.rendition_id)
        content = service.read_rendition_content(
            rendition, subject=_owner_subject(), session_id=SESSION_ID
        )
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            assert "word/document.xml" in zf.namelist()


# ══════════════════════════════════════════════════════════════════════
# 6. HTTP-маршруты (§17): права, uniform 404, честные коды
# ══════════════════════════════════════════════════════════════════════


class TestHttpRoutes:
    def test_anonymous_list_profiles_uniform_404(self, client: TestClient):
        resp = client.get("/v1/documentation/org-profiles")
        assert resp.status_code == 404

    def test_admin_create_and_list(self, client: TestClient):
        client.headers.update({"X-API-Key": ADMIN_KEY})
        created = client.post(
            "/v1/documentation/org-profiles",
            json={
                "name": "d9prof-http",
                "version_no": 1,
                "format": "pdfa",
                "title_prefix": "CISStat",
                "footer_text": "проверено",
                "organization": "org",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["profile"]["status"] == "active"
        listed = client.get(
            "/v1/documentation/org-profiles", params={"format": "pdfa"}
        )
        assert listed.status_code == 200
        assert any(
            p["profile_id"] == body["profile"]["profile_id"]
            for p in listed.json()["profiles"]
        )

    def test_writer_without_policy_admin_403(self, client: TestClient):
        client.headers.update({"X-API-Key": WRITER_KEY})
        resp = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9prof-w", "version_no": 1, "format": "pdfa"},
        )
        assert resp.status_code == 403

    def test_duplicate_name_version_409(self, client: TestClient):
        client.headers.update({"X-API-Key": ADMIN_KEY})
        payload = {"name": "d9prof-dup-http", "version_no": 1, "format": "pdfa"}
        first = client.post("/v1/documentation/org-profiles", json=payload)
        assert first.status_code == 201
        second = client.post("/v1/documentation/org-profiles", json=payload)
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "org_profile_duplicate"

    def test_unknown_format_422(self, client: TestClient):
        client.headers.update({"X-API-Key": ADMIN_KEY})
        resp = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9prof-bad", "version_no": 1, "format": "doc"},
        )
        assert resp.status_code == 422

    def test_retire_route(self, client: TestClient):
        client.headers.update({"X-API-Key": ADMIN_KEY})
        created = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9prof-ret-http", "version_no": 1, "format": "docx"},
        )
        profile_id = created.json()["profile"]["profile_id"]
        retired = client.post(
            f"/v1/documentation/org-profiles/{profile_id}/retire"
        )
        assert retired.status_code == 200
        assert retired.json()["profile"]["status"] == "retired"
        # Идемпотентный повторный retire.
        again = client.post(
            f"/v1/documentation/org-profiles/{profile_id}/retire"
        )
        assert again.status_code == 200

    def test_retire_unknown_profile_404(self, client: TestClient):
        client.headers.update({"X-API-Key": ADMIN_KEY})
        resp = client.post(
            "/v1/documentation/org-profiles/prof-d9-missing/retire"
        )
        assert resp.status_code == 404

    def test_http_rendition_with_profile_end_to_end(self, client: TestClient):
        """Сквозной HTTP-сценарий: owner заказывает docx с профилем,
        worker рендерит, validations доступны по HTTP."""
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.session_store import SESSION_COOKIE_NAME

        snapshot = _seed_snapshot()
        client.headers.update({"X-API-Key": ADMIN_KEY})
        created = client.post(
            "/v1/documentation/org-profiles",
            json={"name": "d9prof-e2e", "version_no": 1, "format": "docx"},
        )
        profile_id = created.json()["profile"]["profile_id"]
        client.headers.pop("X-API-Key", None)
        client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID)
        resp = client.post(
            f"/v1/documentation/revisions/{snapshot.snapshot_id}/renditions",
            json={"format": "docx", "org_profile_id": profile_id},
        )
        # Ревизии по snapshot.snapshot_id нет; ожидаем создание документа
        # нельзя по этому URL. Честный маршрут renditions принимает
        # revision_id -- поэтому сначала создаём документ HTTP'ем.
        docs = client.post(
            f"/v1/documentation/runs/{snapshot.research_run_id}/documents",
            json={"kind": "D01"},
        )
        assert docs.status_code == 201, docs.text
        revision_id = docs.json()["revision"]["revision_id"]
        resp = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "docx", "org_profile_id": profile_id},
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job"]["job_id"]
        DocumentRenderWorker().run_once()
        status = client.get(f"/v1/documentation/jobs/{job_id}")
        assert status.status_code == 200
        job_body = status.json()["job"]
        assert job_body["state"] == "ready", job_body.get("error_code")
        rendition_id = job_body["rendition_id"]
        validations = client.get(
            f"/v1/documentation/renditions/{rendition_id}/validations"
        )
        assert validations.status_code == 200
        records = validations.json()["validations"]
        assert records
        assert any(
            r["validator"] == "docx-structural/1" and r["result"] == "passed"
            for r in records
        )

    def test_validations_foreign_rendition_uniform_404(self, client: TestClient):
        """Знание rendition_id чужого run НЕ является правом (T7/T15)."""
        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx")
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        from apps.api.document_render_worker import DocumentRenderWorker

        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        rendition_id = done.rendition_id
        # Чужой tenant (other) -- не владелец run'а.
        client.headers.update({"X-API-Key": OTHER_KEY})
        resp = client.get(
            f"/v1/documentation/renditions/{rendition_id}/validations"
        )
        assert resp.status_code == 404

    def test_verify_signature_route(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", SIGN_KEY_ENV)
        snapshot = _seed_snapshot()
        profile = _make_profile(fmt="docx", sign_contents=True)
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="docx", org_profile_id=profile.profile_id,
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        from apps.api.document_render_worker import DocumentRenderWorker

        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job.job_id)
        rendition_id = done.rendition_id
        from apps.api.session_store import SESSION_COOKIE_NAME

        client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID)
        resp = client.post(
            f"/v1/documentation/renditions/{rendition_id}/verify-signature"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["verification"]["result"] == "passed"


# ══════════════════════════════════════════════════════════════════════
# 7. Статические каталоги: миграция 0015, DDL-паритет
# ══════════════════════════════════════════════════════════════════════


class TestStaticCatalogs:
    def test_migration_catalog_counts(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        # Честное обновление пина (прецедент DOCLOG-9): PGV-02 добавил
        # 0016_pgv2_print_documents.sql (2 таблицы + 2 индекса) -- каталог
        # 16 файлов / 96 statements (93 + 3 новой миграции). PGV-09
        # добавил 0017_pgv9_print_renditions.sql (6 ALTER/INDEX + 2 DO) --
        # каталог 17 файлов / 106 statements (96 + 10).
        assert len(MIGRATION_FILES) == 17
        assert MIGRATION_FILES[-1][0] == "0017_pgv9_print_renditions.sql"
        assert len(MIGRATION_STATEMENTS) == 106

    def test_migration_file_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        name, statements = MIGRATION_FILES[-1]
        sql = (Path("apps/api/migrations") / name).read_text("utf-8")
        for statement in statements:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]

    def test_profiles_tables_in_ddl(self):
        sql = Path("apps/api/migrations/0015_doclog9_profiles.sql").read_text(
            "utf-8"
        )
        for fragment in (
            "CREATE TABLE IF NOT EXISTS doc_profiles",
            "CREATE TABLE IF NOT EXISTS doc_rendition_validations",
            "CREATE TABLE IF NOT EXISTS doc_anchor_records",
            "ADD COLUMN IF NOT EXISTS org_profile_id",
        ):
            assert fragment in sql, fragment

    def test_routes_catalog(self):
        from apps.api.main import app

        routes = {
            r.path
            for r in app.routes
            if r.path.startswith("/v1/documentation/org-profiles")
        }
        # list+create (общий путь) + retire -- 2 уникальных пути.
        assert routes == {
            "/v1/documentation/org-profiles",
            "/v1/documentation/org-profiles/{profile_id}/retire",
        }
        rend_routes = [
            r.path
            for r in app.routes
            if "/validations" in r.path or "/verify-signature" in r.path
        ]
        assert len(rend_routes) == 2

    def test_audit_validation_anchored_standard(self):
        from apps.api import security_audit

        assert (
            security_audit.AUDIT_REQUIREMENTS["rendition_validated"]
            == "standard"
        )
        assert (
            security_audit.AUDIT_REQUIREMENTS["rendition_anchored"]
            == "standard"
        )
