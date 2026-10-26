# apps/api/doc_profiles.py
"""
DOCLOG-9 (spec_documentation_logging.md §7 P2, §11, §15, §16, §19 строка
DOCLOG-9, §20 AC03/AC05/AC08/AC09/AC12/AC16): профили организации --
версионированные организационные политики выпуска визуальной формы
документа.

Критерий §19 -- «выбранный профиль подтверждён валидатором и
organisational policy, НЕ названием файла» -- реализован буквально:

1. Валидатор conformance проверяет БАЙТЫ выпуска (pdfa-structural/1,
   docx-structural/1); запись валидации пишется ДАЖЕ при passed
   (доказательство подтверждения); failed -- честный failed-выпуск
   (document_jobs переводит job в terminal failed
   profile_validation_failed, ready-файла нет -- AC08 по построению).
2. Организационная политика: профиль применяется только если он
   существует, ACTIVE и соответствует формату рендера; управление
   профилями -- право policy.admin (§15: reviewer/policy -- permission
   sets через scopes, не новые роли); аноним не дисклоужит контур
   (uniform 404, решающая таблица DOCLOG-0).

Профиль -- организационная сущность tenant-уровня: НЕ научное данное
run'а (таблица doc_profiles БЕЗ FK на research_runs -- паритет грантов
DOCLOG-7: переживает run намеренно). Рендер -- чистая функция от
(снимок, профиль) (R06/AC03/AC05): оформление профиля входит в байты,
профиль версионирован (UNIQUE(name, version_no)) и иммутабелен
(retire -- статусная запись, не правка).

Гарантии профиля:
  validate_conformance -- структурный валидатор (по умолчанию TRUE);
  sign_contents       -- detached HMAC-SHA256-манифест содержимого.
        Это НЕ юридическая электронная подпись (§7: PDF «не электронная
        подпись»); алгоритм и состав манифеста фиксируются в самой
        записи; ключ CISSTAT_DOC_SIGN_KEY; отсутствие ключа -- честный
        отказ (SignatureKeyUnavailable), не тихая неподписанная ready.
  anchor_registry     -- append-only якорь (doc_anchor_records,
        INSERT-only API; локальный срез внешнего anchoring §16).
  worm_lock           -- логический WORM: retention hold DOCLOG-6 на
        документе с причиной org_profile_worm:<profile_id>; физический
        object-lock -- организационный выбор инфраструктуры (§8.1).

PDF/A (§7 P2): отдельная запись каталога, НЕ переименование pdf.
Рендер создаёт XMP-идентификацию (pdfaid:part=1, conformance=B),
OutputIntent GTS_PDFA1 с программно сгенерированным sRGB ICC-профилем
(Pillow/littlecms; отсутствие -- честный RenderDependencyError),
встроенные шрифты, без Encrypt/JavaScript/внешних URI. Валидатор
проверяет маркеры conformance; внешний veraPDF -- следующий срез.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import zipfile
from dataclasses import dataclass, field, replace as _replace
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

PROFILE_FORMATS = frozenset({"docx", "pdfa"})
PROFILE_ACTIVE = "active"
PROFILE_RETIRED = "retired"
PROFILE_SCHEMA_VERSION = "doclog.org_profile/1"

PDFA_VALIDATOR = "pdfa-structural/1"
DOCX_VALIDATOR = "docx-structural/1"
SIGNATURE_VALIDATOR = "signature/1"
SIGN_KEY_ENV = "CISSTAT_DOC_SIGN_KEY"
SIGNATURE_ALGORITHM = "HMAC-SHA256"

KNOWN_VALIDATORS = frozenset({PDFA_VALIDATOR, DOCX_VALIDATOR, SIGNATURE_VALIDATOR})

VALIDATOR_BY_FORMAT = {"pdfa": PDFA_VALIDATOR, "docx": DOCX_VALIDATOR}

WORM_REASON_PREFIX = "org_profile_worm"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex}"


# ── Исключения (HTTP-маппинг §17 в routers) ──────────────────────────


class OrgProfileError(RuntimeError):
    """Базовая ошибка контура профилей."""


class OrgProfileAccessDenied(OrgProfileError):
    """Нет права policy.admin (403)."""


class OrgProfileNotFound(OrgProfileError):
    """Профиль не существует (404 uniform)."""


class OrgProfileRetired(OrgProfileError):
    """Профиль выведен из действия (409)."""


class OrgProfileFormatMismatch(OrgProfileError):
    """Профиль не соответствует формату рендера / формат вне профиля
    каталога (422)."""


class OrgProfileDuplicate(OrgProfileError):
    """Дубль (name, version_no) (409)."""


class OrgProfileRequired(OrgProfileError):
    """Формат docx/pdfa требует организационный профиль (422)."""


class OrgProfileMismatchError(OrgProfileError):
    """Готовая rendition цели выпущена с ДРУГИМ профилем (409):
    одна визуальная форма на цель (§11/AC09)."""


class OrgProfileUnavailable(OrgProfileError):
    """Профиль недоступен/retired на момент исполнения рендера
    (worker: terminal failed org_profile_unavailable)."""


class SignatureKeyUnavailable(OrgProfileError):
    """Ключ подписи не задан -- честный отказ (AC12-дух)."""


# ── Модель ───────────────────────────────────────────────────────────


@dataclass
class OrganizationalDocumentProfile:
    """Версионированная организационная политика выпуска (§19)."""

    profile_id: str
    name: str
    version_no: int
    format: str
    status: str = PROFILE_ACTIVE
    language: str = "ru"
    title_prefix: str = ""
    footer_text: str = ""
    organization: str = ""
    validate_conformance: bool = True
    sign_contents: bool = False
    anchor_registry: bool = False
    worm_lock: bool = False
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    retired_by: Optional[str] = None
    retired_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": self.name,
            "version_no": self.version_no,
            "format": self.format,
            "status": self.status,
            "language": self.language,
            "title_prefix": self.title_prefix,
            "footer_text": self.footer_text,
            "organization": self.organization,
            "validate_conformance": self.validate_conformance,
            "sign_contents": self.sign_contents,
            "anchor_registry": self.anchor_registry,
            "worm_lock": self.worm_lock,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "retired_by": self.retired_by,
            "retired_at": self.retired_at,
        }


@dataclass
class ValidationResult:
    """Результат валидатора/подписи (findings -- человекочитаемы)."""

    validator: str
    result: str  # passed | failed
    findings: list[str] = field(default_factory=list)
    signature_manifest: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "result": self.result,
            "findings": list(self.findings),
            "signature_manifest": self.signature_manifest,
        }


@dataclass
class ProfileValidationRecord:
    """Дurable-запись валидации rendition (миграция 0015)."""

    validation_id: str
    rendition_id: str
    job_id: str
    run_id: str
    profile_id: str
    profile_version_no: int
    format: str
    validator: str
    result: str
    findings: list[str] = field(default_factory=list)
    signature_manifest: Optional[dict[str, Any]] = None
    checked_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "rendition_id": self.rendition_id,
            "job_id": self.job_id,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "profile_version_no": self.profile_version_no,
            "format": self.format,
            "validator": self.validator,
            "result": self.result,
            "findings": list(self.findings),
            "signature_manifest": self.signature_manifest,
            "checked_at": self.checked_at,
        }


@dataclass
class DocumentAnchorRecord:
    """Append-only якорь (INSERT-only; локальный срез §16)."""

    anchor_id: str
    rendition_id: str
    content_sha256: str
    profile_id: str
    anchored_by: Optional[str] = None
    anchored_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "rendition_id": self.rendition_id,
            "content_sha256": self.content_sha256,
            "profile_id": self.profile_id,
            "anchored_by": self.anchored_by,
            "anchored_at": self.anchored_at,
        }


# ── Валидаторы conformance («не названием файла») ────────────────────

_PDFA_XMP_PART_RE = re.compile(rb"pdfaid:part[^>]*>\s*1\s*<")
_PDFA_XMP_CONF_RE = re.compile(rb"pdfaid:conformance[^>]*>\s*B\s*<", re.IGNORECASE)


def _pdfa_structural_validate(content: bytes) -> ValidationResult:
    """Структурные маркеры PDF/A-1b. Внешний veraPDF -- следующий срез
    (честная граница docs/doclog9_profiles.md)."""
    findings: list[str] = []
    if not content.startswith(b"%PDF-"):
        findings.append("pdf_header_missing: байты не начинаются с %PDF-")
        return ValidationResult(PDFA_VALIDATOR, "failed", findings)
    if not _PDFA_XMP_PART_RE.search(content):
        findings.append("pdfaid_missing: XMP-идентификация pdfaid:part=1 отсутствует")
    if not _PDFA_XMP_CONF_RE.search(content):
        findings.append(
            "pdfa_conformance_missing: pdfaid:conformance=B отсутствует"
        )
    if b"GTS_PDFA1" not in content:
        findings.append("outputintent_missing: GTS_PDFA1 OutputIntent отсутствует")
    if b"DestOutputProfile" not in content:
        findings.append(
            "icc_missing: DestOutputProfile (sRGB ICC) не привязан"
        )
    if b"FontFile2" not in content:
        findings.append("fonts_missing: встроенные шрифты (FontFile2) отсутствуют")
    if b"/Encrypt" in content:
        findings.append("encrypt_present: шифрование запрещено PDF/A")
    if b"/JavaScript" in content or b"/JS" in content:
        findings.append("javascript_present: скрипты запрещены PDF/A")
    if b"/S /URI" in content:
        findings.append("external_uri_present: внешние URI-экшены запрещены")
    if findings:
        return ValidationResult(PDFA_VALIDATOR, "failed", findings)
    return ValidationResult(PDFA_VALIDATOR, "passed", ["все маркеры PDF/A-1b на месте"])


_DOCX_REQUIRED_MEMBERS = (
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/styles.xml",
    "docProps/core.xml",
)


def _docx_structural_validate(content: bytes) -> ValidationResult:
    """Структура OOXML: обязательные члены, валидный XML, без внешних
    связей TARGETMODE="External"."""
    findings: list[str] = []
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile:
        return ValidationResult(
            DOCX_VALIDATOR, "failed", ["zip_invalid: байты не ZIP/OOXML"]
        )
    names = set(zf.namelist())
    for member in _DOCX_REQUIRED_MEMBERS:
        if member not in names:
            findings.append(f"member_missing: {member} отсутствует")
    for rels in (n for n in names if n.endswith(".rels")):
        data = zf.read(rels)
        if b'TargetMode="External"' in data:
            findings.append(
                f"external_relationship: {rels} содержит внешнюю связь"
            )
    import xml.etree.ElementTree as ET

    for member in ("[Content_Types].xml", "word/document.xml", "docProps/core.xml"):
        if member in names:
            try:
                ET.fromstring(zf.read(member))
            except ET.ParseError as exc:
                findings.append(f"xml_invalid: {member} не парсится ({exc.__class__.__name__})")
    if findings:
        return ValidationResult(DOCX_VALIDATOR, "failed", findings)
    return ValidationResult(
        DOCX_VALIDATOR, "passed", ["OOXML-структура валидна, внешних связей нет"]
    )


def _signature_validate(
    content: bytes, manifest: Optional[dict[str, Any]]
) -> ValidationResult:
    """Верификация detached-подписи (manifest должен быть в записи)."""
    if not manifest or not isinstance(manifest, dict):
        return ValidationResult(
            SIGNATURE_VALIDATOR, "failed", ["manifest_missing: манифест подписи отсутствует"]
        )
    expected = _canonical_manifest(content, manifest)
    mac = manifest.get("mac", "")
    if not isinstance(mac, str) or not mac:
        return ValidationResult(
            SIGNATURE_VALIDATOR, "failed", ["mac_missing: MAC отсутствует в манифесте"]
        )
    key = _sign_key_or_none()
    if key is None:
        return ValidationResult(
            SIGNATURE_VALIDATOR, "failed", ["key_unavailable: ключ подписи не задан"]
        )
    if hmac.compare_digest(mac, expected):
        return ValidationResult(
            SIGNATURE_VALIDATOR,
            "passed",
            [f"algorithm={manifest.get('algorithm')}"],
            signature_manifest=manifest,
        )
    return ValidationResult(
        SIGNATURE_VALIDATOR, "failed", ["mac_mismatch: подпись не совпадает с байтами"]
    )


# ── Подпись содержимого (HMAC, НЕ юридическая ЭП) ────────────────────


def _sign_key_or_none() -> Optional[bytes]:
    value = os.environ.get(SIGN_KEY_ENV, "").strip()
    return value.encode("utf-8") if value else None


def _canonical_manifest(content: bytes, manifest: dict[str, Any]) -> str:
    """MAC от канонического JSON манифеста БЕЗ поля mac + байтов
    содержимого (двухканальная привязка: метаданные и байты)."""
    base = {k: v for k, v in manifest.items() if k != "mac"}
    canonical = json.dumps(base, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    digest_input = canonical.encode("utf-8") + b"\x00" + content
    return hmac.new(_sign_key() , digest_input, hashlib.sha256).hexdigest()


def _sign_key() -> bytes:
    key = _sign_key_or_none()
    if key is None:
        raise SignatureKeyUnavailable(
            f"{SIGN_KEY_ENV} не задан -- подпись содержимого невозможна; "
            "тихая неподписанная выдача запрещена (AC12-дух)"
        )
    return key


def sign_content(
    content: bytes,
    *,
    snapshot_sha256: str,
    profile_id: str,
    profile_version_no: int = 0,
    media_type: str = "",
    signed_by: Optional[str] = None,
) -> dict[str, Any]:
    """Detached HMAC-манифест. Пометка: НЕ юридическая электронная
    подпись (§7); фиксирует совпадение байтов+метаданных на момент
    подписания и верифицируется независимо."""
    manifest: dict[str, Any] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "snapshot_payload_sha256": snapshot_sha256,
        "media_type": media_type,
        "profile_id": profile_id,
        "profile_version_no": profile_version_no,
        "signed_by": signed_by,
        "disclaimer": "not_a_legal_signature",
    }
    manifest["mac"] = _canonical_manifest(content, manifest)
    return manifest


def verify_signature_manifest(
    content: bytes, manifest: dict[str, Any]
) -> ValidationResult:
    """Независимая верификация манифеста против байтов."""
    return _signature_validate(content, manifest)


def validate_profile_output(
    content: bytes, fmt: str, profile: Optional[OrganizationalDocumentProfile]
) -> ValidationResult:
    """Диспетчер структурного валидатора conformance («профиль
    подтверждён валидатором, не названием файла»)."""
    if fmt == "pdfa":
        return _pdfa_structural_validate(content)
    if fmt == "docx":
        return _docx_structural_validate(content)
    raise OrgProfileFormatMismatch(
        f"Профильная валидация не определена для формата {fmt!r}"
    )


# ── Реестры (ABC + Memory + Postgres; паритет DOCLOG-8) ─────────────


class OrgProfileRegistryError(RuntimeError):
    pass


class OrgProfileRegistry:
    """Реестр профилей/валидаций/якорей (ABC)."""

    def create_profile(self, profile: OrganizationalDocumentProfile) -> OrganizationalDocumentProfile:  # pragma: no cover - контракт
        raise NotImplementedError

    def get_profile(self, profile_id: str) -> Optional[OrganizationalDocumentProfile]:  # pragma: no cover
        raise NotImplementedError

    def find_duplicate(self, name: str, version_no: int) -> Optional[OrganizationalDocumentProfile]:  # pragma: no cover
        raise NotImplementedError

    def list_profiles(self, fmt: Optional[str] = None) -> list[OrganizationalDocumentProfile]:  # pragma: no cover
        raise NotImplementedError

    def update_status(
        self, profile_id: str, status: str, actor: Optional[str]
    ) -> Optional[OrganizationalDocumentProfile]:  # pragma: no cover
        raise NotImplementedError

    def append_validation(self, record: ProfileValidationRecord) -> ProfileValidationRecord:  # pragma: no cover
        raise NotImplementedError

    def list_validations(self, rendition_id: str) -> list[ProfileValidationRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_validations_by_job(self, job_id: str) -> list[ProfileValidationRecord]:  # pragma: no cover
        raise NotImplementedError

    def append_anchor(self, record: DocumentAnchorRecord) -> DocumentAnchorRecord:  # pragma: no cover
        raise NotImplementedError

    def list_anchors(self, rendition_id: str) -> list[DocumentAnchorRecord]:  # pragma: no cover
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        raise NotImplementedError


class MemoryOrgProfileRegistry(OrgProfileRegistry):
    """In-memory реестр (dev/тесты; содержимое -- только в памяти)."""

    def __init__(self) -> None:
        self._profiles: dict[str, OrganizationalDocumentProfile] = {}
        self._validations: list[ProfileValidationRecord] = []
        self._anchors: list[DocumentAnchorRecord] = []
        self._lock = threading.Lock()

    def create_profile(
        self, profile: OrganizationalDocumentProfile
    ) -> OrganizationalDocumentProfile:
        with self._lock:
            self._profiles[profile.profile_id] = profile
        return profile

    def get_profile(
        self, profile_id: str
    ) -> Optional[OrganizationalDocumentProfile]:
        return self._profiles.get(profile_id)

    def find_duplicate(
        self, name: str, version_no: int
    ) -> Optional[OrganizationalDocumentProfile]:
        for profile in self._profiles.values():
            if profile.name == name and profile.version_no == version_no:
                return profile
        return None

    def list_profiles(
        self, fmt: Optional[str] = None
    ) -> list[OrganizationalDocumentProfile]:
        profiles = list(self._profiles.values())
        if fmt:
            profiles = [p for p in profiles if p.format == fmt]
        return sorted(profiles, key=lambda p: (p.name, p.version_no))

    def update_status(
        self, profile_id: str, status: str, actor: Optional[str]
    ) -> Optional[OrganizationalDocumentProfile]:
        profile = self._profiles.get(profile_id)
        if profile is None:
            return None
        updated = _replace(
            profile,
            status=status,
            retired_by=actor if status == PROFILE_RETIRED else profile.retired_by,
            retired_at=_now_iso() if status == PROFILE_RETIRED else profile.retired_at,
        )
        self._profiles[profile_id] = updated
        return updated

    def append_validation(
        self, record: ProfileValidationRecord
    ) -> ProfileValidationRecord:
        with self._lock:
            self._validations.append(record)
        return record

    def list_validations(self, rendition_id: str) -> list[ProfileValidationRecord]:
        return [
            r for r in self._validations if r.rendition_id == rendition_id
        ]

    def list_validations_by_job(self, job_id: str) -> list[ProfileValidationRecord]:
        return [r for r in self._validations if r.job_id == job_id]

    def append_anchor(self, record: DocumentAnchorRecord) -> DocumentAnchorRecord:
        with self._lock:
            self._anchors.append(record)
        return record

    def list_anchors(self, rendition_id: str) -> list[DocumentAnchorRecord]:
        return [r for r in self._anchors if r.rendition_id == rendition_id]

    def readiness_probe(self) -> dict[str, Any]:
        return {
            "backend": "memory",
            "profiles": len(self._profiles),
            "validations": len(self._validations),
            "anchors": len(self._anchors),
        }


class PostgresOrgProfileRegistry(OrgProfileRegistry):
    """Durable-реестр (миграция 0015 на первом коннекте; ленивый
    psycopg -- паритет durable-контуров DOCLOG-1/2/4/6/7/8)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresOrgProfileRegistry":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresOrgProfileRegistry."
            )
        return PostgresOrgProfileRegistry(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- паритет durable-контуров

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    def create_profile(
        self, profile: OrganizationalDocumentProfile
    ) -> OrganizationalDocumentProfile:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc_profiles (profile_id, schema_version, name, "
                "version_no, format, status, language, title_prefix, "
                "footer_text, organization, validate_conformance, "
                "sign_contents, anchor_registry, worm_lock, created_by, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s)",
                (
                    profile.profile_id, PROFILE_SCHEMA_VERSION, profile.name,
                    profile.version_no, profile.format, profile.status,
                    profile.language, profile.title_prefix,
                    profile.footer_text, profile.organization,
                    profile.validate_conformance, profile.sign_contents,
                    profile.anchor_registry, profile.worm_lock,
                    profile.created_by, profile.created_at,
                ),
            )
        return profile

    def get_profile(
        self, profile_id: str
    ) -> Optional[OrganizationalDocumentProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_id, name, version_no, format, status, "
                "language, title_prefix, footer_text, organization, "
                "validate_conformance, sign_contents, anchor_registry, "
                "worm_lock, created_by, created_at::text, retired_by, "
                "retired_at::text FROM doc_profiles WHERE profile_id = %s",
                (profile_id,),
            ).fetchone()
        return self._row_to_profile(row) if row else None

    def find_duplicate(
        self, name: str, version_no: int
    ) -> Optional[OrganizationalDocumentProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_id, name, version_no, format, status, "
                "language, title_prefix, footer_text, organization, "
                "validate_conformance, sign_contents, anchor_registry, "
                "worm_lock, created_by, created_at::text, retired_by, "
                "retired_at::text FROM doc_profiles WHERE name = %s AND "
                "version_no = %s",
                (name, version_no),
            ).fetchone()
        return self._row_to_profile(row) if row else None

    def list_profiles(
        self, fmt: Optional[str] = None
    ) -> list[OrganizationalDocumentProfile]:
        query = (
            "SELECT profile_id, name, version_no, format, status, "
            "language, title_prefix, footer_text, organization, "
            "validate_conformance, sign_contents, anchor_registry, "
            "worm_lock, created_by, created_at::text, retired_by, "
            "retired_at::text FROM doc_profiles"
        )
        params: tuple[str, ...] = ()
        if fmt:
            query += " WHERE format = %s"
            params = (fmt,)
        query += " ORDER BY name, version_no"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def update_status(
        self, profile_id: str, status: str, actor: Optional[str]
    ) -> Optional[OrganizationalDocumentProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE doc_profiles SET status = %s, retired_by = %s, "
                "retired_at = CASE WHEN %s = 'retired' THEN now() ELSE "
                "retired_at END WHERE profile_id = %s RETURNING "
                "profile_id",
                (status, actor, status, profile_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_profile(profile_id)

    def append_validation(
        self, record: ProfileValidationRecord
    ) -> ProfileValidationRecord:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc_rendition_validations (validation_id, "
                "rendition_id, job_id, run_id, profile_id, "
                "profile_version_no, format, validator, result, findings, "
                "signature_manifest, checked_at) VALUES (%s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    record.validation_id, record.rendition_id, record.job_id,
                    record.run_id, record.profile_id,
                    record.profile_version_no, record.format,
                    record.validator, record.result,
                    json.dumps(record.findings, ensure_ascii=False),
                    json.dumps(record.signature_manifest, ensure_ascii=False)
                    if record.signature_manifest is not None else None,
                    record.checked_at,
                ),
            )
        return record

    def list_validations(self, rendition_id: str) -> list[ProfileValidationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT validation_id, rendition_id, job_id, run_id, "
                "profile_id, profile_version_no, format, validator, "
                "result, findings, signature_manifest, checked_at::text "
                "FROM doc_rendition_validations WHERE rendition_id = %s "
                "ORDER BY checked_at, validation_id",
                (rendition_id,),
            ).fetchall()
        return [self._row_to_validation(row) for row in rows]

    def list_validations_by_job(self, job_id: str) -> list[ProfileValidationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT validation_id, rendition_id, job_id, run_id, "
                "profile_id, profile_version_no, format, validator, "
                "result, findings, signature_manifest, checked_at::text "
                "FROM doc_rendition_validations WHERE job_id = %s "
                "ORDER BY checked_at, validation_id",
                (job_id,),
            ).fetchall()
        return [self._row_to_validation(row) for row in rows]

    def append_anchor(self, record: DocumentAnchorRecord) -> DocumentAnchorRecord:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc_anchor_records (anchor_id, rendition_id, "
                "content_sha256, profile_id, anchored_by, anchored_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    record.anchor_id, record.rendition_id,
                    record.content_sha256, record.profile_id,
                    record.anchored_by, record.anchored_at,
                ),
            )
        return record

    def list_anchors(self, rendition_id: str) -> list[DocumentAnchorRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT anchor_id, rendition_id, content_sha256, "
                "profile_id, anchored_by, anchored_at::text FROM "
                "doc_anchor_records WHERE rendition_id = %s ORDER BY "
                "anchored_at, anchor_id",
                (rendition_id,),
            ).fetchall()
        return [
            DocumentAnchorRecord(
                anchor_id=row[0], rendition_id=row[1],
                content_sha256=row[2], profile_id=row[3],
                anchored_by=row[4], anchored_at=row[5],
            )
            for row in rows
        ]

    def readiness_probe(self) -> dict[str, Any]:
        return {"backend": "postgres"}

    @staticmethod
    def _row_to_profile(row: Any) -> OrganizationalDocumentProfile:
        return OrganizationalDocumentProfile(
            profile_id=row[0], name=row[1], version_no=int(row[2]),
            format=row[3], status=row[4], language=row[5],
            title_prefix=row[6], footer_text=row[7], organization=row[8],
            validate_conformance=bool(row[9]), sign_contents=bool(row[10]),
            anchor_registry=bool(row[11]), worm_lock=bool(row[12]),
            created_by=row[13], created_at=row[14], retired_by=row[15],
            retired_at=row[16],
        )

    @staticmethod
    def _row_to_validation(row: Any) -> ProfileValidationRecord:
        return ProfileValidationRecord(
            validation_id=row[0], rendition_id=row[1], job_id=row[2],
            run_id=row[3], profile_id=row[4],
            profile_version_no=int(row[5]), format=row[6],
            validator=row[7], result=row[8],
            findings=list(row[9] or []),
            signature_manifest=row[10] if isinstance(row[10], dict) else None,
            checked_at=row[11],
        )


_ORG_PROFILE_REGISTRY: Optional[OrgProfileRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def _registry_from_env() -> OrgProfileRegistry:
    if os.environ.get("CISSTAT_DOC_PROFILES_BACKEND", "").strip().lower() == "postgres":
        return PostgresOrgProfileRegistry.from_env()
    if os.environ.get("DATABASE_URL"):
        return PostgresOrgProfileRegistry.from_env()
    return MemoryOrgProfileRegistry()


def get_org_profile_registry() -> OrgProfileRegistry:
    global _ORG_PROFILE_REGISTRY
    if _ORG_PROFILE_REGISTRY is None:
        with _REGISTRY_LOCK:
            if _ORG_PROFILE_REGISTRY is None:
                _ORG_PROFILE_REGISTRY = _registry_from_env()
    return _ORG_PROFILE_REGISTRY


def reset_org_profile_registry_for_testing() -> None:
    global _ORG_PROFILE_REGISTRY
    with _REGISTRY_LOCK:
        _ORG_PROFILE_REGISTRY = None
    # Сервис связан с реестром (singleton): сброс реестра без сброса
    # сервиса оставлял бы прежний Memory-реестр между тестами.
    reset_org_profile_service_for_testing()


# ── Сервис ───────────────────────────────────────────────────────────


class OrgProfileService:
    """Управление профилями организации и применение профилей к
    выпускам (создание/retire -- policy.admin, §15)."""

    def __init__(self, registry: OrgProfileRegistry) -> None:
        self.registry = registry

    @staticmethod
    def create_default() -> "OrgProfileService":
        return OrgProfileService(get_org_profile_registry())

    # -- права --

    @staticmethod
    def _require_policy_admin(subject: Any) -> None:
        """§15: policy.admin -- permission set через scopes; роль ADMIN
        даёт полный каталог (§15.1); cookie-суррогат права не фантазирует."""
        if subject is None or getattr(subject, "is_anonymous", True):
            raise OrgProfileNotFound("Контур профилей недоступен")
        role = (getattr(subject, "role", None) or "")
        if role == "admin":
            return
        scopes = getattr(subject, "scopes", None) or frozenset()
        if "policy.admin" not in scopes:
            raise OrgProfileAccessDenied(
                "Управление профилями организации требует policy.admin (§15)"
            )

    # -- управление --

    def create_profile(
        self,
        *,
        name: str,
        version_no: int,
        format: str,
        subject: Any,
        language: str = "ru",
        title_prefix: str = "",
        footer_text: str = "",
        organization: str = "",
        validate_conformance: bool = True,
        sign_contents: bool = False,
        anchor_registry: bool = False,
        worm_lock: bool = False,
    ) -> OrganizationalDocumentProfile:
        self._require_policy_admin(subject)
        name = str(name).strip()
        if not name:
            raise OrgProfileError("Имя профиля обязательно")
        if not isinstance(version_no, int) or version_no < 1:
            raise OrgProfileError("version_no -- положительное целое")
        if format not in PROFILE_FORMATS:
            raise OrgProfileFormatMismatch(
                f"Формат профиля {format!r} вне каталога DOCLOG-9 "
                f"(допустимо: {sorted(PROFILE_FORMATS)})"
            )
        duplicate = self.registry.find_duplicate(name, version_no)
        if duplicate is not None:
            raise OrgProfileDuplicate(
                f"Профиль {name!r} версии {version_no} уже существует"
            )
        profile = OrganizationalDocumentProfile(
            profile_id=_new_id("prof"),
            name=name,
            version_no=version_no,
            format=format,
            language=language or "ru",
            title_prefix=str(title_prefix or ""),
            footer_text=str(footer_text or ""),
            organization=str(organization or ""),
            validate_conformance=bool(validate_conformance),
            sign_contents=bool(sign_contents),
            anchor_registry=bool(anchor_registry),
            worm_lock=bool(worm_lock),
            created_by=getattr(subject, "subject_id", None),
        )
        # C08 (DOCLOG-E2E-RECHECK-1-FIX; подтверждение F-D9C2): mandatory-
        # аудит ВЫПОЛНЯЕТСЯ ДО защищённой записи (R09-паттерн
        # document_lifecycle: «record_mandatory fail-closed ДО действия»).
        # Прежний порядок create → audit при ломучем sink оставлял
        # незарегистрированную защищённую запись (профиль создан, аудит
        # упал, ретрай -- 409 duplicate). Аудит записи создаёт
        # profile_id ДО записи в реестр -- resource_id корректен.
        self._audit(
            "org_profile_created",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no,
                     "format": profile.format},
        )
        return self.registry.create_profile(profile)

    def retire_profile(
        self, profile_id: str, subject: Any
    ) -> OrganizationalDocumentProfile:
        self._require_policy_admin(subject)
        profile = self.registry.get_profile(profile_id)
        if profile is None:
            raise OrgProfileNotFound("Профиль не найден")
        if profile.status == PROFILE_RETIRED:
            return profile  # идемпотентно (паритет cancel_job §17)
        # C08 (DOCLOG-E2E-RECHECK-1-FIX): тот же порядок fail-closed, что
        # и для create -- mandatory-аудит ДО смены статуса (retire --
        # защищённая запись того же класса «смена шаблона/policy»).
        self._audit(
            "org_profile_retired",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no},
        )
        updated = self.registry.update_status(
            profile_id, PROFILE_RETIRED, getattr(subject, "subject_id", None)
        )
        assert updated is not None
        return updated

    def list_profiles(
        self, subject: Any, *, fmt: Optional[str] = None
    ) -> list[OrganizationalDocumentProfile]:
        if subject is None or getattr(subject, "is_anonymous", True):
            raise OrgProfileNotFound("Контур профилей недоступен")
        return self.registry.list_profiles(fmt)

    # -- применение --

    def resolve_profile(
        self, profile_id: str, *, fmt: str, subject: Any
    ) -> OrganizationalDocumentProfile:
        """Policy-подтверждение: существует + ACTIVE + формат совпадает."""
        profile = self.registry.get_profile(profile_id)
        if profile is None:
            raise OrgProfileNotFound("Профиль не найден")
        if profile.format != fmt:
            raise OrgProfileFormatMismatch(
                f"Профиль {profile.name} v{profile.version_no} для формата "
                f"{profile.format!r}, запрошен рендер {fmt!r}"
            )
        if profile.status != PROFILE_ACTIVE:
            raise OrgProfileRetired(
                f"Профиль {profile.name} v{profile.version_no} выведен из "
                "действия -- выпуск по нему невозможен"
            )
        return profile

    def validate_output(
        self, content: bytes, fmt: str, profile: OrganizationalDocumentProfile
    ) -> ValidationResult:
        if profile.validate_conformance:
            return validate_profile_output(content, fmt, profile)
        return ValidationResult(
            VALIDATOR_BY_FORMAT[fmt],
            "passed",
            ["validate_conformance=false: валидация отключена политикой профиля"],
        )

    def record_validation(
        self,
        profile: OrganizationalDocumentProfile,
        *,
        validation: ValidationResult,
        fmt: str,
        rendition_id: str,
        job_id: str,
        run_id: str,
        subject: Any,
    ) -> ProfileValidationRecord:
        """Durable-запись валидации (пишется ДАЖЕ при passed --
        доказательство «подтверждён валидатором», §19); audit
        rendition_validated -- standard (сбой не ломает выпуск)."""
        record = ProfileValidationRecord(
            validation_id=_new_id("val"),
            rendition_id=rendition_id,
            job_id=job_id,
            run_id=run_id,
            profile_id=profile.profile_id,
            profile_version_no=profile.version_no,
            format=fmt,
            validator=validation.validator,
            result=validation.result,
            findings=list(validation.findings),
            signature_manifest=validation.signature_manifest,
        )
        self.registry.append_validation(record)
        self._audit(
            "rendition_validated",
            subject=subject,
            profile=profile,
            details={
                "rendition_id": rendition_id,
                "validator": validation.validator,
                "result": validation.result,
            },
            requirement="standard",
        )
        return record

    def record_signature(
        self,
        profile: OrganizationalDocumentProfile,
        *,
        manifest: dict[str, Any],
        fmt: str,
        rendition_id: str,
        job_id: str,
        run_id: str,
        subject: Any,
    ) -> ProfileValidationRecord:
        """Запись detached-подписи (validator=signature/1; манифест
        хранится в записи -- верификация независима)."""
        return self.record_validation(
            profile,
            validation=ValidationResult(
                SIGNATURE_VALIDATOR,
                "passed",
                [f"algorithm={SIGNATURE_ALGORITHM}"],
                signature_manifest=manifest,
            ),
            fmt=fmt,
            rendition_id=rendition_id,
            job_id=job_id,
            run_id=run_id,
            subject=subject,
        )

    def record_anchor(
        self,
        profile: OrganizationalDocumentProfile,
        *,
        content_sha256: str,
        rendition_id: str,
        subject: Any,
    ) -> DocumentAnchorRecord:
        """Append-only якорь + audit rendition_anchored (standard)."""
        record = self.registry.append_anchor(
            DocumentAnchorRecord(
                anchor_id=_new_id("anchor"),
                rendition_id=rendition_id,
                content_sha256=content_sha256,
                profile_id=profile.profile_id,
                anchored_by=getattr(subject, "subject_id", None),
            )
        )
        self._audit(
            "rendition_anchored",
            subject=subject,
            profile=profile,
            details={"rendition_id": rendition_id},
            requirement="standard",
        )
        return record

    def apply_worm_hold(
        self,
        profile: OrganizationalDocumentProfile,
        *,
        document_id: str,
        run_id: str,
        subject: Any,
    ) -> bool:
        """Логический WORM (§16): retention hold DOCLOG-6 на документе
        (идемпотентно: upsert обновляет причину/время, hold не снимается)."""
        if not document_id:
            return False
        from apps.api.document_lifecycle import (
            DocumentLifecycleService, RetentionRecord,
        )

        lifecycle = DocumentLifecycleService.create_default()
        lifecycle.registry.upsert_retention(
            RetentionRecord(
                document_id=document_id,
                run_id=run_id,
                hold=True,
                hold_reason=f"{WORM_REASON_PREFIX}:{profile.profile_id}",
                updated_by=getattr(subject, "subject_id", None),
            )
        )
        return True

    def _audit(
        self,
        action: str,
        *,
        subject: Any,
        profile: OrganizationalDocumentProfile,
        details: dict[str, Any],
        requirement: str = "mandatory",
    ) -> None:
        """§14.1/AC11: создание/retire профиля (класс «смена шаблона/
        policy») -- обязательный аудит fail-closed (record_mandatory);
        валидация/якорь -- standard durable (сбой виден, но не ломает
        выпуск)."""
        from apps.api.security_audit import record_mandatory, record_standard

        record = (
            record_mandatory if requirement == "mandatory" else record_standard
        )
        record(
            action,
            "allowed",
            actor_subject=str(getattr(subject, "subject_id", "") or ""),
            actor_via=str(getattr(subject, "via", "") or "anonymous"),
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="document_profile",
            resource_id=profile.profile_id,
            resource_version=str(profile.version_no),
            policy_basis="DOCLOG-9 organizational policy; policy.admin",
            details={
                **details,
                "profile_name": profile.name,
                "profile_format": profile.format,
            },
        )


_ORG_PROFILE_SERVICE: Optional[OrgProfileService] = None


def org_profile_service() -> OrgProfileService:
    global _ORG_PROFILE_SERVICE
    if _ORG_PROFILE_SERVICE is None:
        _ORG_PROFILE_SERVICE = OrgProfileService.create_default()
    return _ORG_PROFILE_SERVICE


def reset_org_profile_service_for_testing() -> None:
    global _ORG_PROFILE_SERVICE
    _ORG_PROFILE_SERVICE = None
