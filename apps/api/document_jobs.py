# apps/api/document_jobs.py
"""
DOCLOG-4 (spec_documentation_logging.md §9.1 адаптеры, §10.3, §11 ось
генерации, §12.2, §15, §17, §19 строка DOCLOG-4, §20 AC05/AC06/AC09):
слой документов поверх снимков DOCLOG-2 и MVP выдачи с job states.

ПОСТАНОВКА (§19, строка DOCLOG-4): «Раздел документов, stage entry
points, HTML/MD/JSON/JSONL/существующие таблицы, job states». Зависимость
2+3 выполнена. Критерий завершения: read/preview не меняют science state.

СЛОЙ ДОКУМЕНТОВ -- АДАПТЕР, НЕ НОВЫЙ ИСТОЧНИК ИСТИНЫ (§19: «reader
появляется раньше writer»; полное Document/DocumentRevision реестр с
текстами аналитика -- DOCLOG-6):
  document          -- (run_id, kind_code), find-or-create (§9.1:
                       «Document: logical document, без перезаписи
                       старых revisions»);
  document_revision -- НЕПЕРЕПИСЫВАЕМАЯ ссылка на существующий frozen
                       ReportSnapshot (UNIQUE(snapshot_id), 1:1) с
                       монотонным version_no; пересборка = НОВАЯ версия
                       (наследуется от идемпотентности сборщика);
  document_rendition-- готовый формат (§9.1 «Rendition: несколько
                       форматов одной ревизии»);
  document_job      -- задание генерации (§11: queued -> rendering ->
                       ready; failed/cancelled -- терминальные состояния
                       ПОПЫТКИ с возможностью нового retry).

IDЕМПОТЕНТНОСТЬ (§10.3/AC09): UNIQUE(snapshot_id, format,
redaction_profile) на rendition; повторный запрос ТОГО ЖЕ формата
возвращает существующую ready rendition и ПРЕЖНИЙ job -- БЕЗ нового
задания и БЕЗ повторного рендера («Повторный клик не запускает научный
расчёт и не создаёт дубли», §12.2).

АВТОРИЗАЦИЯ (R09/§15/T15): каждый метод сервиса резолвит ресурс -> run
и проходит решающую таблицу DOCLOG-0 (identity.authorize_run_access).
Знание document_id/revision_id/job_id/rendition_id НЕ является правом.
N3-ГЕЙТ (акт DOCLOG-2-FIX): dependency manifest выдаётся ТОЛЬКО через
авторизованный путь (get_revision возвращает snapshot.to_dict() ПОСЛЕ
решающей таблицы); прямой ungated доступ к dependency_refs в контуре
исключён.

НАУКА НЕ ТРОГАЕТСЯ (AC05): рендеры -- чистые функции от снимка
(document_renditions); сервис не пишет в run/ledger/артефакты; байты
rendition идут в общий object store как ДОКУМЕНТНЫЙ слой (префикс
content path documents/) -- научные артефакты не перезаписываются.

АУДИТ ВЫДАЧИ (§14.1) -- в роутере (routers/documentation.py): тройка
download_requested/response_stream_started/response_stream_finished
РАЗЛИЧАЕТСЯ; protected_document_viewed на preview; классы standard
(AC11-инвариант: сбой аудита не ломает выдачу).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# H29 (AUDIT-6C паритет): операционные логи выбора backend (без DSN --
# причины проходят safe_error до логов).
logger = logging.getLogger(__name__)

from apps.api.report_snapshot import (
    DEFAULT_REDACTION_PROFILE,
    DOCUMENT_KINDS,
    ReportSnapshot,
)
# Рендеры P0 -- чистые функции (§7/R06): импортируются в namespace
# МОДУЛЯ (dispatch через globals() -- оракулы подменяют точки входа
# document_jobs.render_snapshot_* для негативных сценариев рендера).
from apps.api.document_renditions import (
    HEAVY_RENDITION_FORMATS,
    RENDITION_FORMATS,
    render_snapshot_csv,
    render_snapshot_html,
    render_snapshot_json,
    render_snapshot_jsonl,
)
from apps.api.document_renditions import (
    render_snapshot_markdown as render_snapshot_md,
)
# DOCLOG-5: тяжёлые рендеры (§7 P1) -- те же чистые функции, но
# выполняются асинхронным worker'ом (§18); dispatch -- тот же
# globals()-механизм (render_snapshot_{fmt}), негативные оракулы
# подменяют те же точки входа. Evidence ZIP алиасится в
# render_snapshot_zip под общий диспетчер-паттерн.
from apps.api.document_renditions import (
    render_evidence_zip,
    render_snapshot_parquet,
    render_snapshot_pdf,
    render_snapshot_png,
    render_snapshot_svg,
    render_snapshot_xlsx,
)
from apps.api.document_renditions import (
    render_evidence_zip as render_snapshot_zip,
)
# DOCLOG-9 (§7 P2): рендеры профилей организации -- те же чистые
# функции от (снимок, профиль); профиль применяется ТОЛЬКО к этим
# форматам (docx/pdfa), обязательный параметр выпуска.
from apps.api.document_renditions import (
    render_snapshot_docx,
    render_snapshot_pdfa,
)

DOCUMENTS_BACKEND_ENV = "CISSTAT_DOCUMENTS_BACKEND"

# DOCLOG-7 (§14.2): колонки безопасной проекции доставки (list_delivery_summary).
_DELIVERY_SUMMARY_COLUMNS = (
    "job_id", "run_id", "tenant_id", "snapshot_id", "format",
    "redaction_profile", "state", "error_code", "attempt",
    "created_at", "updated_at", "revision_id", "rendition_id",
    "document_id", "kind_code",
)

# §11: состояния оси генерации.
JOB_QUEUED = "queued"
JOB_RENDERING = "rendering"
JOB_READY = "ready"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_STATES = frozenset({JOB_QUEUED, JOB_RENDERING, JOB_READY, JOB_FAILED, JOB_CANCELLED})

RENDITION_READY = "ready"
RENDITION_FAILED = "failed"
# DOCLOG-6 (§16.1): tombstone retention-очистки -- запись/хэши сохранены,
# байтов нет (честный 410 на чтение).
RENDITION_PURGED = "purged"

# DOCLOG-5 (§18/§11): пределы рендер-контура. MAX_JOB_ATTEMPTS --
# ограничение ПОПЫТОК рендера одной цели (snapshot, format, profile);
# после исчерпания -- честный 429 retry_limit_exceeded, очередь не
# крутится вечно. MAX_OPEN_JOBS_PER_TENANT -- backpressure постановки
# (§18: per-tenant quota); превышение -- 429 quota_exceeded.
MAX_JOB_ATTEMPTS = 5
MAX_OPEN_JOBS_PER_TENANT = 10


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def new_document_id() -> str:
    return _new_id("doc-")


def new_revision_id() -> str:
    return _new_id("drev-")


def new_rendition_id() -> str:
    return _new_id("drend-")


def new_job_id() -> str:
    return _new_id("djob-")


def new_print_revision_id() -> str:
    """PGV-02: id печатной ревизии (document_print_revisions, миграция
    0016) -- отдельный префикс от snapshot-ревизий (drev-)."""
    return _new_id("dprint-")


def is_valid_document_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"doc-[0-9a-f]{32}", value))


def is_valid_revision_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"drev-[0-9a-f]{32}", value))


def is_valid_rendition_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"drend-[0-9a-f]{32}", value))


def is_valid_job_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"djob-[0-9a-f]{32}", value))


# ── Ошибки контура ───────────────────────────────────────────────────


class DocumentAccessDenied(RuntimeError):
    """R09/T15: ресурс не существует ЛИБО не принадлежит субъекту --
    HTTP-слой отвечает uniform 404 (существование не дисклоужается)."""


class UnsupportedFormatError(ValueError):
    """§17: 400 unsupported_format (тяжёлые форматы -- DOCLOG-5)."""


class DocumentIntegrityError(RuntimeError):
    """T8-дух: расхождение content_sha256 при чтении готового файла --
    битые байты не выдаются за валидные."""


class DocumentRetryLimitExceeded(RuntimeError):
    """§18 retries: исчерпан MAX_JOB_ATTEMPTS попыток рендера цели
    (snapshot, format, profile) -- честный 429 retry_limit_exceeded."""


class DocumentQuotaExceeded(RuntimeError):
    """§18 backpressure: tenant-очередь открытых jobs переполнена --
    честный 429 quota_exceeded (не тихое переполнение очереди)."""


class RenditionPurgedError(RuntimeError):
    """DOCLOG-6 (§16.1/§17): байты rendition удалены retention-sweep'ом
    (tombstone state="purged") -- чтение владельцу 410 purged_artifact
    («410 -- известный разрешённому владельцу purged artifact»)."""


class PrintBasisInvalid(ValueError):
    """PGV-02-FIX (находка F-P2C1, docs/cert_pgv02_2026-10-28.md §7):
    basis-артефакт печатной ревизии отсутствует в реестре либо
    принадлежит другому run -- ревизия не создаётся (§10.2 «revision с
    frozen refs/pins»: refs обязаны быть допустимыми; §5/§11 object
    authorization: артефакт чужого run -- недопустимый basis)."""


class PrintRevisionConflictError(RuntimeError):
    """PGV-02-FIX (находка F-P2C6, класс F-D2C1): нарушены
    UNIQUE-ограничения DDL 0016 -- UNIQUE(document_id, version_no) либо
    UNIQUE(document_id, basis_fingerprint). Postgres отклонил бы вставку
    IntegrityError; Memory-реестр обязан давать эквивалентный конфликт,
    а не молчаливый дубликат (паритет Memory/Postgres -- урок F-D2C1)."""


# ── Записи ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DocumentRecord:
    document_id: str
    run_id: str
    kind_code: str
    current_revision_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "run_id": self.run_id,
            "kind_code": self.kind_code,
            "current_revision_id": self.current_revision_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class DocumentRevisionRecord:
    revision_id: str
    document_id: str
    snapshot_id: str
    run_id: str
    version_no: int
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "document_id": self.document_id,
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "version_no": self.version_no,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class DocumentPrintRevisionRecord:
    """PGV-02 (spec_passport_graphics_visual.md §10.2): ревизия печатного
    документа V01/P01/P02. Basis -- frozen print inputs (артефакты
    visual_print_snapshot / паспорта / сравнение), НЕ report snapshot:
    document_revisions.snapshot_id NOT NULL сохраняется для legacy
    читателей D01-D12 (критерий PGV-02). snapshot_id допускает NULL как
    опциональный паспортный anchor. Идемпотентность -- по
    basis_fingerprint (UNIQUE(document_id, basis_fingerprint)): повтор с
    тем же basis не плодит версии (§11 идемпотентность по digest)."""

    print_revision_id: str
    document_id: str
    run_id: str
    print_kind: str
    basis_kind: str
    basis_artifact_ids: list[str] = field(default_factory=list)
    snapshot_id: Optional[str] = None
    profile_id: str = "figure-landscape"
    manifest_artifact_id: Optional[str] = None
    basis_fingerprint: str = ""
    version_no: int = 0
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "print_revision_id": self.print_revision_id,
            "document_id": self.document_id,
            "run_id": self.run_id,
            "print_kind": self.print_kind,
            "basis_kind": self.basis_kind,
            "basis_artifact_ids": list(self.basis_artifact_ids),
            "snapshot_id": self.snapshot_id,
            "profile_id": self.profile_id,
            "manifest_artifact_id": self.manifest_artifact_id,
            "basis_fingerprint": self.basis_fingerprint,
            "version_no": self.version_no,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentPrintRevisionRecord":
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(
            **{key: value for key, value in data.items() if key in known}
        )

    def copy(self) -> "DocumentPrintRevisionRecord":
        return DocumentPrintRevisionRecord(
            **{k: (list(v) if k == "basis_artifact_ids" else v)
               for k, v in self.to_dict().items()}
        )


@dataclass
class DocumentRenditionRecord:
    rendition_id: str
    revision_id: str
    snapshot_id: str
    run_id: str
    format: str
    redaction_profile: str = DEFAULT_REDACTION_PROFILE
    state: str = RENDITION_READY
    media_type: str = ""
    size_bytes: int = 0
    content_sha256: str = ""
    storage_key: str = ""
    job_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    # DOCLOG-5 (критерий завершения §19): все rendition одной ревизии
    # несут ОДИН snapshot hash из registry-метаданных снимка.
    snapshot_payload_sha256: str = ""
    # DOCLOG-9 (§19 строка DOCLOG-9): организационный профиль выпуска
    # (фиксируется в metadata; '' -- безпрофильный legacy-выпуск).
    org_profile_id: str = ""
    # Байты -- только в Memory-реестре (dev/тесты); durable-слой хранит
    # их в object store (content-addressed), как DOCLOG-1/2.
    content_bytes: Optional[bytes] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rendition_id": self.rendition_id,
            "revision_id": self.revision_id,
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "format": self.format,
            "redaction_profile": self.redaction_profile,
            "state": self.state,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "content_sha256": self.content_sha256,
            "storage_key": self.storage_key,
            "job_id": self.job_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "snapshot_payload_sha256": self.snapshot_payload_sha256,
            "org_profile_id": self.org_profile_id,
        }


@dataclass
class DocumentJobRecord:
    job_id: str
    run_id: str
    snapshot_id: str
    format: str
    redaction_profile: str = DEFAULT_REDACTION_PROFILE
    revision_id: Optional[str] = None
    rendition_id: Optional[str] = None
    state: str = JOB_QUEUED
    error_code: Optional[str] = None
    attempt: int = 0
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    # DOCLOG-5 (§11/§18): lease-поля worker'а и tenant для per-tenant
    # concurrency. claimed_at/lease_expires_at ставятся воркером при
    # захвате job'а; просроченный lease -- честный реклейм (AC08).
    tenant_id: Optional[str] = None
    claimed_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    # DOCLOG-9 (§19): организационный профиль выпуска -- resolve на
    # постановке И повторная policy-проверка на момент исполнения
    # (retire между постановкой и рендером -- честный failed).
    org_profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "format": self.format,
            "redaction_profile": self.redaction_profile,
            "revision_id": self.revision_id,
            "rendition_id": self.rendition_id,
            "state": self.state,
            "error_code": self.error_code,
            "attempt": self.attempt,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tenant_id": self.tenant_id,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
            "org_profile_id": self.org_profile_id,
        }


# ── Реестр (ABC + Memory + Postgres, паритет фабрик DOCLOG-1/2) ─────


class DocumentRegistry(ABC):
    """Metadata-реестр слоя документов (§8.1: тот же Postgres)."""

    def register_document(
        self, document: DocumentRecord
    ) -> DocumentRecord:  # pragma: no cover - контракт
        raise NotImplementedError

    def find_document_by_kind(
        self, run_id: str, kind_code: str
    ) -> Optional[DocumentRecord]:  # pragma: no cover
        raise NotImplementedError

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:  # pragma: no cover
        raise NotImplementedError

    def register_revision(
        self, revision: DocumentRevisionRecord
    ) -> DocumentRevisionRecord:  # pragma: no cover
        raise NotImplementedError

    def get_revision(
        self, revision_id: str
    ) -> Optional[DocumentRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    def find_revision_by_snapshot(
        self, document_id: str, snapshot_id: str
    ) -> Optional[DocumentRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_revisions(self, document_id: str) -> list[DocumentRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    # -- PGV-02: печатные ревизии (document_print_revisions, 0016) --

    def register_print_revision(
        self, revision: DocumentPrintRevisionRecord
    ) -> DocumentPrintRevisionRecord:  # pragma: no cover
        raise NotImplementedError

    def get_print_revision(
        self, print_revision_id: str
    ) -> Optional[DocumentPrintRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    def find_print_revision_by_fingerprint(
        self, document_id: str, basis_fingerprint: str
    ) -> Optional[DocumentPrintRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_print_revisions(
        self, document_id: str
    ) -> list[DocumentPrintRevisionRecord]:  # pragma: no cover
        raise NotImplementedError

    def register_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:  # pragma: no cover
        raise NotImplementedError

    def update_rendition(self, rendition: DocumentRenditionRecord) -> DocumentRenditionRecord:  # pragma: no cover
        raise NotImplementedError

    def get_rendition(
        self, rendition_id: str
    ) -> Optional[DocumentRenditionRecord]:  # pragma: no cover
        raise NotImplementedError

    def find_rendition(
        self, snapshot_id: str, fmt: str, redaction_profile: str
    ) -> Optional[DocumentRenditionRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_renditions(self, snapshot_id: str) -> list[DocumentRenditionRecord]:  # pragma: no cover
        raise NotImplementedError

    def register_job(self, job: DocumentJobRecord) -> DocumentJobRecord:  # pragma: no cover
        raise NotImplementedError

    def update_job(self, job: DocumentJobRecord) -> DocumentJobRecord:  # pragma: no cover
        raise NotImplementedError

    def get_job(self, job_id: str) -> Optional[DocumentJobRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_jobs(self, run_id: str) -> list[DocumentJobRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_open_jobs(self, limit: int = 100) -> list[DocumentJobRecord]:  # pragma: no cover
        """DOCLOG-5 (§11/§18): открытые (queued/rendering) jobs всего
        контура в порядке FIFO -- очередь воркера + backpressure."""
        raise NotImplementedError

    def list_delivery_summary(
        self,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        state: Optional[str] = None,
        format_filter: Optional[str] = None,
        run_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:  # pragma: no cover - контракт
        """DOCLOG-7 (§14.2 вкладка «Доставка и документы»): безопасные
        metadata доставки (jobs + rendition/document цепочка) для админ-
        журналов. БЕЗ content_bytes/payload -- только состояния. Порядок
        (created_at DESC, job_id DESC). Структурный паритет Memory/
        Postgres обязателен (урок F-D2C1)."""
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        raise NotImplementedError


class MemoryDocumentRegistry(DocumentRegistry):
    """Memory-реестр (dev/тесты/auto). Байты rendition -- в records."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._documents: dict[str, DocumentRecord] = {}
        self._revisions: dict[str, DocumentRevisionRecord] = {}
        self._print_revisions: dict[str, DocumentPrintRevisionRecord] = {}
        self._renditions: dict[str, DocumentRenditionRecord] = {}
        self._jobs: dict[str, DocumentJobRecord] = {}

    def register_document(self, document: DocumentRecord) -> DocumentRecord:
        with self._lock:
            self._documents[document.document_id] = document
            return document

    def find_document_by_kind(
        self, run_id: str, kind_code: str
    ) -> Optional[DocumentRecord]:
        with self._lock:
            for document in self._documents.values():
                if document.run_id == run_id and document.kind_code == kind_code:
                    return document
            return None

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        with self._lock:
            return self._documents.get(document_id)

    def register_revision(
        self, revision: DocumentRevisionRecord
    ) -> DocumentRevisionRecord:
        with self._lock:
            self._revisions[revision.revision_id] = revision
            document = self._documents.get(revision.document_id)
            if document is not None:
                document.current_revision_id = revision.revision_id
            return revision

    def get_revision(self, revision_id: str) -> Optional[DocumentRevisionRecord]:
        with self._lock:
            return self._revisions.get(revision_id)

    def find_revision_by_snapshot(
        self, document_id: str, snapshot_id: str
    ) -> Optional[DocumentRevisionRecord]:
        with self._lock:
            for revision in self._revisions.values():
                if (
                    revision.document_id == document_id
                    and revision.snapshot_id == snapshot_id
                ):
                    return revision
            return None

    def list_revisions(self, document_id: str) -> list[DocumentRevisionRecord]:
        with self._lock:
            revisions = [
                revision
                for revision in self._revisions.values()
                if revision.document_id == document_id
            ]
        return sorted(revisions, key=lambda item: (item.version_no, item.revision_id))

    # -- PGV-02: печатные ревизии (паритет Postgres, урок F-D2C1) --

    def register_print_revision(
        self, revision: DocumentPrintRevisionRecord
    ) -> DocumentPrintRevisionRecord:
        with self._lock:
            # PGV-02-FIX (F-P2C6): паритет UNIQUE-ограничений DDL 0016 --
            # Memory не маскирует конфликты молчаливым дубликатом (урок
            # F-D2C1). Проверка ДО мутации указателя документа.
            for existing in self._print_revisions.values():
                if existing.document_id != revision.document_id:
                    continue
                if existing.version_no == revision.version_no:
                    raise PrintRevisionConflictError(
                        "UNIQUE(document_id, version_no) нарушен: документ "
                        f"{revision.document_id!r} уже несёт версию "
                        f"{revision.version_no} ({existing.print_revision_id!r})"
                    )
                if existing.basis_fingerprint == revision.basis_fingerprint:
                    raise PrintRevisionConflictError(
                        "UNIQUE(document_id, basis_fingerprint) нарушен: "
                        f"документ {revision.document_id!r} уже несёт этот "
                        f"basis ({existing.print_revision_id!r})"
                    )
            self._print_revisions[revision.print_revision_id] = revision.copy()
            document = self._documents.get(revision.document_id)
            if document is not None:
                document.current_revision_id = revision.print_revision_id
            return revision.copy()

    def get_print_revision(
        self, print_revision_id: str
    ) -> Optional[DocumentPrintRevisionRecord]:
        with self._lock:
            revision = self._print_revisions.get(print_revision_id)
            return revision.copy() if revision else None

    def find_print_revision_by_fingerprint(
        self, document_id: str, basis_fingerprint: str
    ) -> Optional[DocumentPrintRevisionRecord]:
        with self._lock:
            for revision in self._print_revisions.values():
                if (
                    revision.document_id == document_id
                    and revision.basis_fingerprint == basis_fingerprint
                ):
                    return revision.copy()
            return None

    def list_print_revisions(
        self, document_id: str
    ) -> list[DocumentPrintRevisionRecord]:
        with self._lock:
            revisions = [
                revision
                for revision in self._print_revisions.values()
                if revision.document_id == document_id
            ]
        return sorted(
            [r.copy() for r in revisions],
            key=lambda item: (item.version_no, item.print_revision_id),
        )

    def register_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:
        with self._lock:
            self._renditions[rendition.rendition_id] = rendition
            return rendition

    def update_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:
        with self._lock:
            self._renditions[rendition.rendition_id] = rendition
            return rendition

    def get_rendition(self, rendition_id: str) -> Optional[DocumentRenditionRecord]:
        with self._lock:
            return self._renditions.get(rendition_id)

    def find_rendition(
        self, snapshot_id: str, fmt: str, redaction_profile: str
    ) -> Optional[DocumentRenditionRecord]:
        with self._lock:
            for rendition in self._renditions.values():
                if (
                    rendition.snapshot_id == snapshot_id
                    and rendition.format == fmt
                    and rendition.redaction_profile == redaction_profile
                ):
                    return rendition
            return None

    def list_renditions(self, snapshot_id: str) -> list[DocumentRenditionRecord]:
        with self._lock:
            renditions = [
                rendition
                for rendition in self._renditions.values()
                if rendition.snapshot_id == snapshot_id
            ]
        return sorted(renditions, key=lambda item: (item.created_at, item.rendition_id))

    def register_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        with self._lock:
            self._jobs[job.job_id] = job
            return job

    def update_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        job.updated_at = _now_iso()
        with self._lock:
            self._jobs[job.job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[DocumentJobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, run_id: str) -> list[DocumentJobRecord]:
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.run_id == run_id]
        return sorted(jobs, key=lambda item: (item.created_at, item.job_id))

    def list_open_jobs(self, limit: int = 100) -> list[DocumentJobRecord]:
        with self._lock:
            open_states = (JOB_QUEUED, JOB_RENDERING)
            jobs = [
                job
                for job in self._jobs.values()
                if job.state in open_states
            ]
        jobs.sort(key=lambda item: (item.created_at, item.job_id))
        return jobs[:limit]

    def list_delivery_summary(
        self,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        state: Optional[str] = None,
        format_filter: Optional[str] = None,
        run_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """DOCLOG-7 (§14.2): безопасные metadata доставки. Memory:
        join jobs -> renditions -> revisions -> documents по словарям;
        БЕЗ content_bytes (repr=False поле не попадает в dict-проекцию)."""
        with self._lock:
            jobs = list(self._jobs.values())
        rows: list[dict[str, Any]] = []
        for job in jobs:
            if state is not None and job.state != state:
                continue
            if format_filter is not None and job.format != format_filter:
                continue
            if run_id is not None and job.run_id != run_id:
                continue
            if tenant_id is not None and job.tenant_id != tenant_id:
                continue
            if from_ts is not None and job.created_at < from_ts:
                continue
            if to_ts is not None and job.created_at >= to_ts:
                continue
            rendition = (
                self._renditions.get(job.rendition_id)
                if job.rendition_id
                else None
            )
            revision_id = (
                job.revision_id
                or (rendition.revision_id if rendition else None)
            )
            revision = (
                self._revisions.get(revision_id) if revision_id else None
            )
            document = (
                self._documents.get(revision.document_id)
                if revision is not None
                else None
            )
            rows.append(
                {
                    "job_id": job.job_id,
                    "run_id": job.run_id,
                    "tenant_id": job.tenant_id,
                    "snapshot_id": job.snapshot_id,
                    "format": job.format,
                    "redaction_profile": job.redaction_profile,
                    "state": job.state,
                    "error_code": job.error_code,
                    "attempt": job.attempt,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "revision_id": revision_id,
                    "rendition_id": job.rendition_id,
                    "document_id": (
                        document.document_id if document is not None else None
                    ),
                    "kind_code": (
                        document.kind_code if document is not None else None
                    ),
                }
            )
        rows.sort(
            key=lambda item: (str(item["created_at"]), item["job_id"]),
            reverse=True,
        )
        return rows

    def readiness_probe(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory"}


class PostgresDocumentRegistry(DocumentRegistry):
    """Durable-реестр (миграция 0010; ленивый psycopg -- паритет
    фабрик DOCLOG-1/2). Байты rendition -- в object store."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._migrated = False

    @classmethod
    def from_env(cls) -> "PostgresDocumentRegistry":
        # H29 (DOCLOG-H29-UIHONEST-AUDITVIEW, 2026-10-27): паттерн
        # PostgresArtifactRegistry/PostgresSnapshotRegistry -- DSN читается
        # здесь, отсутствие DATABASE_URL -- явный RuntimeError. Прежний
        # вариант импортировал несуществующий research_runs.database_dsn
        # (ImportError на каждом durable-обращении -- durable-путь
        # документов фактически не работал).
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresDocumentRegistry."
            )
        return cls(dsn)

    def _connect(self):
        import psycopg

        conn = psycopg.connect(self._dsn)
        if not self._migrated:
            from apps.api.research_runs import run_migrations

            run_migrations(conn)
            self._migrated = True
        return conn

    def readiness_probe(self) -> dict[str, Any]:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return {"ok": True, "backend": "postgres"}
        except Exception:  # pragma: no cover -- probe не бросает
            return {"ok": False, "backend": "postgres"}

    # -- documents --

    def register_document(self, document: DocumentRecord) -> DocumentRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (document_id, run_id, kind_code, "
                "current_revision_id, created_by, created_at) VALUES "
                "(%s, %s, %s, %s, %s, %s) ON CONFLICT (document_id) DO NOTHING",
                (
                    document.document_id,
                    document.run_id,
                    document.kind_code,
                    document.current_revision_id,
                    document.created_by,
                    document.created_at,
                ),
            )
        return document

    def find_document_by_kind(
        self, run_id: str, kind_code: str
    ) -> Optional[DocumentRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT document_id, run_id, kind_code, "
                "current_revision_id, created_by, created_at FROM documents "
                "WHERE run_id = %s AND kind_code = %s",
                (run_id, kind_code),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return DocumentRecord(
            document_id=str(row[0]),
            run_id=str(row[1]),
            kind_code=str(row[2]),
            current_revision_id=row[3],
            created_by=row[4],
            created_at=row[5].isoformat() if row[5] else _now_iso(),
        )

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT document_id, run_id, kind_code, "
                "current_revision_id, created_by, created_at FROM documents "
                "WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return DocumentRecord(
            document_id=str(row[0]),
            run_id=str(row[1]),
            kind_code=str(row[2]),
            current_revision_id=row[3],
            created_by=row[4],
            created_at=row[5].isoformat() if row[5] else _now_iso(),
        )

    # -- revisions --

    def register_revision(
        self, revision: DocumentRevisionRecord
    ) -> DocumentRevisionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_revisions (revision_id, document_id, "
                "snapshot_id, run_id, version_no, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    revision.revision_id,
                    revision.document_id,
                    revision.snapshot_id,
                    revision.run_id,
                    revision.version_no,
                    revision.created_by,
                    revision.created_at,
                ),
            )
            cur.execute(
                "UPDATE documents SET current_revision_id = %s "
                "WHERE document_id = %s",
                (revision.revision_id, revision.document_id),
            )
        return revision

    _REVISION_SELECT = (
        "SELECT revision_id, document_id, snapshot_id, run_id, version_no, "
        "created_by, created_at FROM document_revisions"
    )

    @staticmethod
    def _revision_from_row(row: tuple) -> DocumentRevisionRecord:
        return DocumentRevisionRecord(
            revision_id=str(row[0]),
            document_id=str(row[1]),
            snapshot_id=str(row[2]),
            run_id=str(row[3]),
            version_no=int(row[4]),
            created_by=row[5],
            created_at=row[6].isoformat() if row[6] else _now_iso(),
        )

    def get_revision(self, revision_id: str) -> Optional[DocumentRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._REVISION_SELECT + " WHERE revision_id = %s",
                (revision_id,),
            )
            row = cur.fetchone()
        return self._revision_from_row(row) if row is not None else None

    def find_revision_by_snapshot(
        self, document_id: str, snapshot_id: str
    ) -> Optional[DocumentRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._REVISION_SELECT
                + " WHERE document_id = %s AND snapshot_id = %s",
                (document_id, snapshot_id),
            )
            row = cur.fetchone()
        return self._revision_from_row(row) if row is not None else None

    def list_revisions(self, document_id: str) -> list[DocumentRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._REVISION_SELECT
                + " WHERE document_id = %s ORDER BY version_no, revision_id",
                (document_id,),
            )
            rows = cur.fetchall()
        return [self._revision_from_row(row) for row in rows]

    # -- PGV-02: печатные ревизии (document_print_revisions, 0016) --

    def register_print_revision(
        self, revision: DocumentPrintRevisionRecord
    ) -> DocumentPrintRevisionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_print_revisions (print_revision_id, "
                "document_id, run_id, print_kind, basis_kind, "
                "basis_artifact_ids, snapshot_id, profile_id, "
                "manifest_artifact_id, basis_fingerprint, version_no, "
                "created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    revision.print_revision_id,
                    revision.document_id,
                    revision.run_id,
                    revision.print_kind,
                    revision.basis_kind,
                    json.dumps(revision.basis_artifact_ids),
                    revision.snapshot_id,
                    revision.profile_id,
                    revision.manifest_artifact_id,
                    revision.basis_fingerprint,
                    revision.version_no,
                    revision.created_by,
                    revision.created_at,
                ),
            )
            cur.execute(
                "UPDATE documents SET current_revision_id = %s "
                "WHERE document_id = %s",
                (revision.print_revision_id, revision.document_id),
            )
        return revision.copy()

    _PRINT_REVISION_SELECT = (
        "SELECT print_revision_id, document_id, run_id, print_kind, "
        "basis_kind, basis_artifact_ids, snapshot_id, profile_id, "
        "manifest_artifact_id, basis_fingerprint, version_no, created_by, "
        "created_at FROM document_print_revisions"
    )

    @staticmethod
    def _print_revision_from_row(row: tuple) -> DocumentPrintRevisionRecord:
        return DocumentPrintRevisionRecord(
            print_revision_id=str(row[0]),
            document_id=str(row[1]),
            run_id=str(row[2]),
            print_kind=str(row[3]),
            basis_kind=str(row[4]),
            basis_artifact_ids=list(row[5] or []),
            snapshot_id=(str(row[6]) if row[6] else None),
            profile_id=str(row[7] or "figure-landscape"),
            manifest_artifact_id=(str(row[8]) if row[8] else None),
            basis_fingerprint=str(row[9] or ""),
            version_no=int(row[10]),
            created_by=row[11],
            created_at=row[12].isoformat() if row[12] else _now_iso(),
        )

    def get_print_revision(
        self, print_revision_id: str
    ) -> Optional[DocumentPrintRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._PRINT_REVISION_SELECT + " WHERE print_revision_id = %s",
                (print_revision_id,),
            )
            row = cur.fetchone()
        return self._print_revision_from_row(row) if row is not None else None

    def find_print_revision_by_fingerprint(
        self, document_id: str, basis_fingerprint: str
    ) -> Optional[DocumentPrintRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._PRINT_REVISION_SELECT
                + " WHERE document_id = %s AND basis_fingerprint = %s",
                (document_id, basis_fingerprint),
            )
            row = cur.fetchone()
        return self._print_revision_from_row(row) if row is not None else None

    def list_print_revisions(
        self, document_id: str
    ) -> list[DocumentPrintRevisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._PRINT_REVISION_SELECT
                + " WHERE document_id = %s ORDER BY version_no, print_revision_id",
                (document_id,),
            )
            rows = cur.fetchall()
        return [self._print_revision_from_row(row) for row in rows]

    # -- renditions --

    _RENDITION_SELECT = (
        "SELECT rendition_id, revision_id, snapshot_id, run_id, format, "
        "redaction_profile, state, media_type, size_bytes, content_sha256, "
        "storage_key, job_id, created_by, created_at, "
        "snapshot_payload_sha256, org_profile_id FROM document_renditions"
    )

    @staticmethod
    def _rendition_from_row(row: tuple) -> DocumentRenditionRecord:
        return DocumentRenditionRecord(
            rendition_id=str(row[0]),
            revision_id=str(row[1]),
            snapshot_id=str(row[2]),
            run_id=str(row[3]),
            format=str(row[4]),
            redaction_profile=str(row[5]),
            state=str(row[6]),
            media_type=str(row[7] or ""),
            size_bytes=int(row[8] or 0),
            content_sha256=str(row[9] or ""),
            storage_key=str(row[10] or ""),
            job_id=row[11],
            created_by=row[12],
            created_at=row[13].isoformat() if row[13] else _now_iso(),
            snapshot_payload_sha256=str(row[14] or ""),
            org_profile_id=str(row[15] or ""),
        )

    def register_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_renditions (rendition_id, revision_id, "
                "snapshot_id, run_id, format, redaction_profile, state, "
                "media_type, size_bytes, content_sha256, storage_key, job_id, "
                "created_by, created_at, snapshot_payload_sha256, org_profile_id) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (snapshot_id, format, redaction_profile) "
                "DO UPDATE SET state = EXCLUDED.state, media_type = "
                "EXCLUDED.media_type, size_bytes = EXCLUDED.size_bytes, "
                "content_sha256 = EXCLUDED.content_sha256, storage_key = "
                "EXCLUDED.storage_key, job_id = EXCLUDED.job_id, "
                "snapshot_payload_sha256 = EXCLUDED.snapshot_payload_sha256, "
                "org_profile_id = EXCLUDED.org_profile_id",
                (
                    rendition.rendition_id,
                    rendition.revision_id,
                    rendition.snapshot_id,
                    rendition.run_id,
                    rendition.format,
                    rendition.redaction_profile,
                    rendition.state,
                    rendition.media_type,
                    rendition.size_bytes,
                    rendition.content_sha256,
                    rendition.storage_key,
                    rendition.job_id,
                    rendition.created_by,
                    rendition.created_at,
                    rendition.snapshot_payload_sha256,
                    rendition.org_profile_id,
                ),
            )
        return rendition

    def update_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE document_renditions SET state = %s, media_type = %s, "
                "size_bytes = %s, content_sha256 = %s, storage_key = %s, "
                "job_id = %s, snapshot_payload_sha256 = %s "
                "WHERE rendition_id = %s",
                (
                    rendition.state,
                    rendition.media_type,
                    rendition.size_bytes,
                    rendition.content_sha256,
                    rendition.storage_key,
                    rendition.job_id,
                    rendition.snapshot_payload_sha256,
                    rendition.rendition_id,
                ),
            )
        return rendition

    def get_rendition(self, rendition_id: str) -> Optional[DocumentRenditionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._RENDITION_SELECT + " WHERE rendition_id = %s",
                (rendition_id,),
            )
            row = cur.fetchone()
        return self._rendition_from_row(row) if row is not None else None

    def find_rendition(
        self, snapshot_id: str, fmt: str, redaction_profile: str
    ) -> Optional[DocumentRenditionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._RENDITION_SELECT
                + " WHERE snapshot_id = %s AND format = %s "
                "AND redaction_profile = %s",
                (snapshot_id, fmt, redaction_profile),
            )
            row = cur.fetchone()
        return self._rendition_from_row(row) if row is not None else None

    def list_renditions(self, snapshot_id: str) -> list[DocumentRenditionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._RENDITION_SELECT
                + " WHERE snapshot_id = %s ORDER BY created_at, rendition_id",
                (snapshot_id,),
            )
            rows = cur.fetchall()
        return [self._rendition_from_row(row) for row in rows]

    # -- jobs --

    _JOB_SELECT = (
        "SELECT job_id, run_id, snapshot_id, format, redaction_profile, "
        "revision_id, rendition_id, state, error_code, attempt, created_by, "
        "created_at, updated_at, tenant_id, claimed_at, lease_expires_at, "
        "org_profile_id FROM document_jobs"
    )

    @staticmethod
    def _job_from_row(row: tuple) -> DocumentJobRecord:
        return DocumentJobRecord(
            job_id=str(row[0]),
            run_id=str(row[1]),
            snapshot_id=str(row[2]),
            format=str(row[3]),
            redaction_profile=str(row[4]),
            revision_id=row[5],
            rendition_id=row[6],
            state=str(row[7]),
            error_code=row[8],
            attempt=int(row[9] or 0),
            created_by=row[10],
            created_at=row[11].isoformat() if row[11] else _now_iso(),
            updated_at=row[12].isoformat() if row[12] else _now_iso(),
            tenant_id=row[13],
            claimed_at=row[14].isoformat() if row[14] else None,
            lease_expires_at=row[15].isoformat() if row[15] else None,
            org_profile_id=str(row[16] or ""),
        )

    def register_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_jobs (job_id, run_id, snapshot_id, "
                "format, redaction_profile, revision_id, rendition_id, state, "
                "error_code, attempt, created_by, created_at, updated_at, "
                "tenant_id, claimed_at, lease_expires_at, org_profile_id) VALUES (%s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    job.job_id,
                    job.run_id,
                    job.snapshot_id,
                    job.format,
                    job.redaction_profile,
                    job.revision_id,
                    job.rendition_id,
                    job.state,
                    job.error_code,
                    job.attempt,
                    job.created_by,
                    job.created_at,
                    job.updated_at,
                    job.tenant_id,
                    job.claimed_at,
                    job.lease_expires_at,
                    job.org_profile_id,
                ),
            )
        return job

    def update_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        job.updated_at = _now_iso()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE document_jobs SET state = %s, error_code = %s, "
                "attempt = %s, rendition_id = %s, updated_at = %s, "
                "claimed_at = %s, lease_expires_at = %s WHERE job_id = %s",
                (
                    job.state,
                    job.error_code,
                    job.attempt,
                    job.rendition_id,
                    job.updated_at,
                    job.claimed_at,
                    job.lease_expires_at,
                    job.job_id,
                ),
            )
        return job

    def get_job(self, job_id: str) -> Optional[DocumentJobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._JOB_SELECT + " WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
        return self._job_from_row(row) if row is not None else None

    def list_jobs(self, run_id: str) -> list[DocumentJobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._JOB_SELECT + " WHERE run_id = %s ORDER BY created_at, job_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_open_jobs(self, limit: int = 100) -> list[DocumentJobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._JOB_SELECT
                + " WHERE state IN ('queued', 'rendering') "
                "ORDER BY created_at, job_id LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_delivery_summary(
        self,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        state: Optional[str] = None,
        format_filter: Optional[str] = None,
        run_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """DOCLOG-7 (§14.2): SQL-join jobs -> renditions -> revisions ->
        documents; whitelist-колонки, БЕЗ content/payload."""
        sql = (
            "SELECT j.job_id, j.run_id, j.tenant_id, j.snapshot_id,"
            " j.format, j.redaction_profile, j.state, j.error_code,"
            " j.attempt, j.created_at, j.updated_at, j.revision_id,"
            " j.rendition_id, rev.document_id, d.kind_code"
            " FROM document_jobs j"
            " LEFT JOIN document_renditions r"
            " ON r.rendition_id = j.rendition_id"
            " LEFT JOIN document_revisions rev"
            " ON rev.revision_id = COALESCE(j.revision_id, r.revision_id)"
            " LEFT JOIN documents d ON d.document_id = rev.document_id"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if state is not None:
            clauses.append("j.state = %s")
            params.append(state)
        if format_filter is not None:
            clauses.append("j.format = %s")
            params.append(format_filter)
        if run_id is not None:
            clauses.append("j.run_id = %s")
            params.append(run_id)
        if tenant_id is not None:
            clauses.append("j.tenant_id = %s")
            params.append(tenant_id)
        if from_ts is not None:
            clauses.append("j.created_at >= %s")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("j.created_at < %s")
            params.append(to_ts)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY j.created_at DESC, j.job_id DESC"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            record = dict(zip(_DELIVERY_SUMMARY_COLUMNS, row))
            for key, value in list(record.items()):
                if isinstance(value, datetime):
                    record[key] = value.isoformat()
            result.append(record)
        return result


# ── Фабрики (паритет get_artifact_registry / get_snapshot_registry) ──


_registry: Optional[DocumentRegistry] = None
_registry_lock = threading.Lock()


def get_document_registry() -> DocumentRegistry:
    """Фабрика реестра документов -- КОНТРАКТ AUDIT-6C (план §18 п.1;
    P21/F14 -- CISSTAT_STORAGE_MODE). H29 (Task DOCLOG-H29-UIHONEST-
    AUDITVIEW, 2026-10-27): единственный компонент durable-контура, не
    доведённый до паритета runs/session/artifacts/snapshots -- тихий
    выбор backend без диагностики; устранён (класс S4/S5 «исследование
    недоступно после рестарта free-тира» больше не прячется).

    ВЫБОР БЭКЕНДА (паритет get_research_run_store):
      - CISSTAT_DOCUMENTS_BACKEND=memory -> Memory (ВЫБРАННЫЙ backend,
        приоритет над DATABASE_URL; observable как configured=memory);
      - =postgres или DATABASE_URL задан -> Postgres;
      - иначе -> Memory (configured=auto).

    РЕЖИМЫ ХРАНЕНИЯ:

      - ``required``: неверная конфигурация/отсутствующий драйвер/
        недоступная БД (readiness-проба на выборе) -- fail-closed
        RuntimeError, ТИХИЙ Memory fallback ЗАПРЕЩЁН;
      - ``advisory`` (default, dev): fallback в Memory допустим, но НЕ
        тихий: configured/effective/degraded + безопасная причина
        (record_backend_fallback), состояние видно в /health/ops.

    Readiness-проба -- ТОЛЬКО в required (advisory сохраняет
    сертифицированный ленивый контракт: конструирование Postgres
    не открывает соединение; недоступность БД видна через readiness
    /health/ops, а не на выборе фабрики).
    """
    global _registry
    with _registry_lock:
        if _registry is not None:
            return _registry

        from apps.api.storage_diagnostics import (
            COMPONENT_DOCUMENTS,
            get_storage_mode,
            record_backend_fallback,
            record_backend_selected,
            safe_error,
        )

        mode = get_storage_mode()
        backend_explicit = (
            os.environ.get(DOCUMENTS_BACKEND_ENV) or ""
        ).strip().lower()
        dsn = (os.environ.get("DATABASE_URL") or "").strip()

        # Опечатка в конфигурации -- fail fast (паритет get_storage_mode:
        # в required-окружении тихое «неизвестное = auto» скрыло бы
        # fail-closed контракт).
        if backend_explicit not in ("", "auto", "memory", "postgres"):
            raise RuntimeError(
                f"{DOCUMENTS_BACKEND_ENV}={backend_explicit!r} не "
                "поддерживается; доступно: memory | postgres"
            )

        if backend_explicit == "memory":
            _registry = MemoryDocumentRegistry()
            record_backend_selected(COMPONENT_DOCUMENTS, "memory", "memory")
        elif backend_explicit == "postgres" or dsn:
            # Выбор фиксируется ДО попытки (паритет runs/session): отказ
            # инициализации виден в snapshot как configured=postgres.
            record_backend_selected(COMPONENT_DOCUMENTS, "postgres", "initializing")
            try:
                candidate = PostgresDocumentRegistry.from_env()
                if mode == "required":
                    # P21/F14 fail-closed: соединение поднимается заранее
                    # -- неверная конфигурация/драйвер/миграция/БД видны
                    # немедленно, а не на первом запросе «Документов».
                    probe = candidate.readiness_probe()
                    if not probe.get("ok"):
                        reason = probe.get("error") or "readiness probe failed"
                        raise RuntimeError(
                            "DocumentRegistry: Postgres backend required, "
                            f"но недоступен (fail-closed, P21/F14): {reason}"
                        )
                _registry = candidate
                record_backend_selected(COMPONENT_DOCUMENTS, "postgres", "postgres")
                logger.info("DocumentRegistry: Postgres backend selected")
            except Exception as e:
                reason = safe_error(e)
                if mode == "required":
                    # Тихий Memory fallback в required запрещён (план
                    # §18 п.1): ошибка останавливает запуск/запрос, а не
                    # подменяет долговечность памятью процесса.
                    record_backend_selected(
                        COMPONENT_DOCUMENTS, "postgres", "unavailable",
                        reason=reason, degraded=True,
                    )
                    raise RuntimeError(
                        "DocumentRegistry: Postgres backend required, "
                        f"но инициализация не удалась (fail-closed, P21/F14): "
                        f"{reason}"
                    ) from e
                logger.error(
                    "DocumentRegistry: Postgres init failed (%s), ЯВНАЯ "
                    "деградация в Memory (advisory mode; состояние в "
                    "/health/ops)", reason,
                )
                record_backend_fallback(
                    COMPONENT_DOCUMENTS, "postgres", reason, effective="memory"
                )
                _registry = MemoryDocumentRegistry()
        else:
            _registry = MemoryDocumentRegistry()
            record_backend_selected(COMPONENT_DOCUMENTS, "auto", "memory")
        return _registry


def peek_document_registry() -> Optional[DocumentRegistry]:
    """Факты /health/ops БЕЗ провокации фабрики (паритет peek-контракта)."""
    return _registry


def reset_document_registry_for_testing() -> None:
    global _registry
    with _registry_lock:
        _registry = None


# ── Сервис выдачи ────────────────────────────────────────────────────


class DocumentDeliveryService:
    """MVP выдачи поверх frozen снимков (§12.2 действия, §17 контракты).

    Авторизация -- ПЕРВЫЙ шаг каждого метода; отказ --
    DocumentAccessDenied (HTTP: uniform 404). Рендеры -- чистые функции
    (document_renditions.render_for_format); байты -- в общий object
    store (content-addressed, докyментный слой); science state не
    меняется (AC05)."""

    def __init__(self, registry: DocumentRegistry, objects: Any) -> None:
        self.registry = registry
        self.objects = objects

    @classmethod
    def create_default(cls) -> "DocumentDeliveryService":
        from apps.api.artifact_store import get_artifact_object_store

        return cls(get_document_registry(), get_artifact_object_store())

    # -- авторизация (одна объектная, R09) --

    def _authorized_run(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        action: str = "read",
    ) -> Any:
        from apps.api.identity import authorize_run_access
        from apps.api.research_runs import get_research_run_store

        run = get_research_run_store().get_run(run_id)
        if run is None:
            raise DocumentAccessDenied("Запуск недоступен")
        decision = authorize_run_access(
            run, subject, session_id=session_id, action=action
        )
        if not decision.allowed:
            raise DocumentAccessDenied("Запуск недоступен")
        return run

    def _snapshot_for_revision(
        self, revision: DocumentRevisionRecord, subject: Any, *, session_id: str
    ) -> ReportSnapshot:
        from apps.api.snapshot_builder import SnapshotService

        self._authorized_run(
            revision.run_id, subject, session_id=session_id, action="read"
        )
        snapshot = SnapshotService.create_default().get_snapshot(
            revision.snapshot_id, subject, session_id=session_id
        )
        return snapshot

    # -- документы и версии (§9.1 адаптер) --

    def ensure_document_revision(
        self,
        snapshot: ReportSnapshot,
        subject: Any,
        *,
        session_id: str = "",
        kind_code: Optional[str] = None,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord, bool]:
        """find-or-create document=(run, kind) + append-only revision
        (UNIQUE(snapshot_id)). Возвращает (document, revision, created)."""
        run_id = snapshot.research_run_id
        self._authorized_run(run_id, subject, session_id=session_id, action="write")
        code = kind_code or (snapshot.kinds[0] if snapshot.kinds else None)
        if code is None:
            raise UnsupportedFormatError("Снимок без kinds не образует документ")
        created = False
        document = self.registry.find_document_by_kind(run_id, code)
        if document is None:
            document = self.registry.register_document(
                DocumentRecord(
                    document_id=new_document_id(),
                    run_id=run_id,
                    kind_code=code,
                    created_by=getattr(subject, "subject_id", None),
                )
            )
            created = True
        existing = self.registry.find_revision_by_snapshot(
            document.document_id, snapshot.snapshot_id
        )
        if existing is not None:
            # Тот же снимок уже выдан ЭТОМУ виду документа: версия НЕ
            # дублируется (§12.2 «повторный клик не создаёт дубли»);
            # multi-kind снимок честно входит в КАЖДЫЙ свой документ --
            # UNIQUE(document_id, snapshot_id).
            return document, existing, False
        revisions = self.registry.list_revisions(document.document_id)
        version_no = (revisions[-1].version_no + 1) if revisions else 1
        revision = self.registry.register_revision(
            DocumentRevisionRecord(
                revision_id=new_revision_id(),
                document_id=document.document_id,
                snapshot_id=snapshot.snapshot_id,
                run_id=run_id,
                version_no=version_no,
                created_by=getattr(subject, "subject_id", None),
            )
        )
        return document, revision, True

    # -- PGV-02: печатные документы/ревизии (V01/P01/P02, §10.2) --

    def ensure_print_document_revision(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        print_kind: str,
        basis_kind: str,
        basis_artifact_ids: Optional[list[str]] = None,
        snapshot_id: Optional[str] = None,
        profile_id: str = "figure-landscape",
        manifest_artifact_id: Optional[str] = None,
    ) -> tuple[DocumentRecord, DocumentPrintRevisionRecord, bool]:
        """Find-or-create печатный документ (run, print_kind) + ревизия с
        frozen basis из durable print inputs (§10.2: «Создаётся revision
        с frozen refs/pins без capture и перерасчёта»). Идемпотентность
        -- по basis_fingerprint (UNIQUE(document_id, basis_fingerprint)):
        тот же basis -- та же ревизия (§12.2 «повторный клик не создаёт
        дубли»); иной basis/profile/manifest -- новая версия (§11
        идемпотентность по телу: manifest_artifact_id входит в
        fingerprint -- PGV-02-FIX F-P2C3, аргумент не отбрасывается).
        D01-D12 -- через снапшот-поток (ensure_document_revision),
        печатные типы -- только здесь (каталог pgv.document_catalog/2
        различает семейства). Basis-артефакты пинятся с причиной (§16).

        PGV-02-FIX: (F-P2C1) basis-артефакты проходят гейт существования
        и run-принадлежности ДО создания документа/ревизии -- ревизия не
        создаётся по dangling/чужим объектам; (F-P2C5-класс) пин basis
        ставится ДО регистрации ревизии -- отказ пина оставляет durable
        слой без частичного состояния, отказ регистрации -- unpin-
        компенсация поставленных пинов (AC08-дух)."""
        from apps.api.artifact_store import (
            canonical_json_bytes,
            get_artifact_registry,
        )
        from apps.api.report_snapshot import is_print_document_kind

        if not is_print_document_kind(print_kind):
            raise UnsupportedFormatError(
                f"ensure_print_document_revision: {print_kind!r} -- не "
                "печатный тип (V01/P01/P02); D01-D12 идут через "
                "снапшот-поток"
        )
        self._authorized_run(run_id, subject, session_id=session_id, action="write")
        basis_ids = list(basis_artifact_ids or [])
        self._validate_print_basis(run_id, basis_ids)
        # Идемпотентный ключ тела (§11): действие + basis digest
        # (включая manifest -- F-P2C3).
        fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "print_kind": print_kind,
                    "basis_kind": basis_kind,
                    "basis_artifact_ids": basis_ids,
                    "snapshot_id": snapshot_id,
                    "profile_id": profile_id,
                    "manifest_artifact_id": manifest_artifact_id,
                }
            )
        ).hexdigest()
        document = self.registry.find_document_by_kind(run_id, print_kind)
        if document is not None:
            existing = self.registry.find_print_revision_by_fingerprint(
                document.document_id, fingerprint
            )
            if existing is not None:
                return document, existing, False
        if document is None:
            document = self.registry.register_document(
                DocumentRecord(
                    document_id=new_document_id(),
                    run_id=run_id,
                    kind_code=print_kind,
                    created_by=getattr(subject, "subject_id", None),
                )
            )
        revisions = self.registry.list_print_revisions(document.document_id)
        version_no = (revisions[-1].version_no + 1) if revisions else 1
        revision_id = new_print_revision_id()
        created_by = getattr(subject, "subject_id", None)
        # §16 + F-P2C5-класс: пин basis ДО регистрации ревизии (id
        # прегенерирован); unpin-компенсация -- только пины, поставленные
        # ЭТОЙ операцией (pin_ref идемпотентен: чужие пины не снимаем).
        artifact_registry = get_artifact_registry()
        pre_pinned = {
            pin.ref_id
            for pin in artifact_registry.list_pins(run_id, ref_kind="artifact")
        }
        pinned_now: list[str] = []
        try:
            for artifact_id in basis_ids:
                self.registry_pin_artifact(
                    run_id,
                    artifact_id,
                    reason=f"print_revision:{revision_id}",
                    created_by=created_by,
                )
                pinned_now.append(artifact_id)
            revision = self.registry.register_print_revision(
                DocumentPrintRevisionRecord(
                    print_revision_id=revision_id,
                    document_id=document.document_id,
                    run_id=run_id,
                    print_kind=print_kind,
                    basis_kind=basis_kind,
                    basis_artifact_ids=basis_ids,
                    snapshot_id=snapshot_id,
                    profile_id=profile_id,
                    manifest_artifact_id=manifest_artifact_id,
                    basis_fingerprint=fingerprint,
                    version_no=version_no,
                    created_by=created_by,
                )
            )
        except Exception:
            for artifact_id in pinned_now:
                if artifact_id in pre_pinned:
                    continue  # пин существовал до операции -- не наш
                try:
                    artifact_registry.unpin_ref(run_id, "artifact", artifact_id)
                except Exception as unpin_exc:  # pragma: no cover
                    logger.warning(
                        "ensure_print_document_revision: unpin-компенсация "
                        "не удалась для %s: %s",
                        artifact_id,
                        unpin_exc,
                    )
            raise
        return document, revision, True

    def _validate_print_basis(self, run_id: str, basis_ids: list[str]) -> None:
        """PGV-02-FIX (F-P2C1): гейт существования и run-принадлежности
        basis-артефактов (§10.2 «revision с frozen refs/pins»: refs
        обязаны быть допустимыми; §5/§11 object authorization). Отказ ДО
        создания документа/ревизии/пинов -- ничего не регистрируется."""
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        for artifact_id in basis_ids:
            artifact = registry.get_artifact(artifact_id)
            if artifact is None:
                raise PrintBasisInvalid(
                    f"ensure_print_document_revision: basis-артефакт "
                    f"{artifact_id!r} отсутствует в реестре (§10.2: frozen "
                    "refs печатной ревизии обязаны быть допустимыми)"
                )
            if artifact.run_id != run_id:
                raise PrintBasisInvalid(
                    f"ensure_print_document_revision: basis-артефакт "
                    f"{artifact_id!r} принадлежит другому run (§5/§11: "
                    "object authorization -- артефакт чужого run не "
                    "является допустимым basis)"
                )

    def registry_pin_artifact(
        self, run_id: str, artifact_id: str, *, reason: str, created_by: Optional[str]
    ) -> None:
        """Pin артефакта через артефактный реестр (pin_ref -- контракт
        ArtifactRegistry); отказ pin -- честный сбой ревизии."""
        from apps.api.artifact_store import get_artifact_registry

        get_artifact_registry().pin_ref(
            run_id, "artifact", artifact_id, reason=reason, created_by=created_by
        )

    def list_print_documents(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        print_kind: Optional[str] = None,
    ) -> list[tuple[DocumentRecord, list[DocumentPrintRevisionRecord]]]:
        """Печатные документы запуска с ревизиями (субстрат PGV-15:
        фильтры «Визуализации»/«Паспорта свойств»). Легаси list_documents
        (D01-D12, snapshot-ревизии) НЕ задействован -- ответ legacy API
        сохраняет прежнюю форму (критерий PGV-02)."""
        from apps.api.report_snapshot import PRINT_DOCUMENT_KINDS, is_print_document_kind

        if print_kind is not None:
            if not is_print_document_kind(print_kind):
                raise UnsupportedFormatError(
                    f"list_print_documents: {print_kind!r} -- не печатный тип"
                )
            codes: list[str] = [print_kind]
        else:
            codes = list(PRINT_DOCUMENT_KINDS)
        self._authorized_run(run_id, subject, session_id=session_id, action="read")
        documents = []
        for code in codes:
            document = self.registry.find_document_by_kind(run_id, code)
            if document is not None:
                documents.append(document)
        result = []
        for document in documents:
            result.append(
                (document, self.registry.list_print_revisions(document.document_id))
            )
        return result

    def list_documents(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        kind: Optional[str] = None,
    ) -> list[tuple[DocumentRecord, list[DocumentRevisionRecord]]]:
        """Список документов запуска с версиями (§17 GET /runs/{id}/
        documents; kind-фильтр §12.1 «отфильтрованный список»)."""
        self._authorized_run(run_id, subject, session_id=session_id, action="read")
        # D01-D09 -- ограниченный каталог (§6): скан по кодам дешевле
        # и честнее произвольного list_documents по run (паритет
        # Memory/Postgres-реестров).
        documents = []
        for code in DOCUMENT_KINDS:
            if kind is not None and code != kind:
                continue
            document = self.registry.find_document_by_kind(run_id, code)
            if document is not None:
                documents.append(document)
        result: list[tuple[DocumentRecord, list[DocumentRevisionRecord]]] = []
        for document in documents:
            result.append(
                (document, self.registry.list_revisions(document.document_id))
            )
        return result

    def get_document_with_revisions(
        self, document_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[DocumentRecord, list[DocumentRevisionRecord]]:
        if not is_valid_document_id(document_id):
            raise DocumentAccessDenied("Документ недоступен")
        document = self.registry.get_document(document_id)
        if document is None:
            raise DocumentAccessDenied("Документ недоступен")
        self._authorized_run(
            document.run_id, subject, session_id=session_id, action="read"
        )
        return document, self.registry.list_revisions(document.document_id)

    def get_revision(
        self, revision_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[DocumentRevisionRecord, DocumentRecord, ReportSnapshot]:
        """Авторизованное чтение версии: revision + document + ПОЛНЫЙ
        snapshot (включая dependencies -- N3-гейт: только здесь, после
        решающей таблицы; знание revision_id НЕ право)."""
        if not is_valid_revision_id(revision_id):
            raise DocumentAccessDenied("Документ недоступен")
        revision = self.registry.get_revision(revision_id)
        if revision is None:
            raise DocumentAccessDenied("Документ недоступен")
        document = self.registry.get_document(revision.document_id)
        if document is None:
            raise DocumentAccessDenied("Документ недоступен")
        snapshot = self._snapshot_for_revision(
            revision, subject, session_id=session_id
        )
        return revision, document, snapshot

    # -- renditions/jobs (§10.3/§11/§17, AC09) --

    def request_rendition(
        self,
        snapshot: ReportSnapshot,
        *,
        format: str,
        subject: Any,
        session_id: str = "",
        redaction_profile: str = DEFAULT_REDACTION_PROFILE,
        revision_id: Optional[str] = None,
        org_profile_id: str = "",
    ) -> tuple[DocumentJobRecord, Optional[DocumentRenditionRecord]]:
        """§10.3/§11/§17/§18, AC08/AC09: P0-форматы рендерятся
        синхронно (пин DOCLOG-4), тяжёлые (HEAVY_RENDITION_FORMATS §7
        P1) -- ТОЛЬКО через очередь (job queued; рендер выполняет
        document_render_worker; §18: «тяжёлый PDF не создаётся
        синхронно»). Идемпотентность (AC09): ready-цель возвращает
        прежний job/rendition; АКТИВНАЯ (queued/rendering) -- тот же
        job без нового задания; исчерпанные попытки -- честный
        DocumentRetryLimitExceeded; переполненная tenant-очередь --
        DocumentQuotaExceeded (§18 backpressure).

        DOCLOG-9 (§19 строка DOCLOG-9): организационный профиль --
        часть формы выпуска. Форматы docx/pdfa ТРЕБУЮТ профиль
        (безымянный выпуск PDF/A запрещён -- «выбранный профиль
        подтверждён валидатором и policy, не названием файла»);
        профиль применим ТОЛЬКО к форматам своего каталога; профиль
        resolve'ится ДО постановки (существует + ACTIVE + формат);
        готовая/активная цель с ДРУГИМ профилем -- честный 409
        org_profile_mismatch (одна визуальная форма на цель, §11)."""
        from apps.api.artifact_store import artifact_content_sha256

        run_id = snapshot.research_run_id
        self._authorized_run(run_id, subject, session_id=session_id, action="write")
        spec = RENDITION_FORMATS.get(format)
        if spec is None:
            raise UnsupportedFormatError(
                f"Формат {format!r} не входит в каталог P0+P1 (§7)"
            )
        # ── DOCLOG-9: организационный профиль выпуска ──────────────
        profile_service = None
        if org_profile_id or format in ("docx", "pdfa"):
            from apps.api import doc_profiles as _dp

            profile_service = _dp.org_profile_service()
            if format not in _dp.PROFILE_FORMATS:
                raise _dp.OrgProfileFormatMismatch(
                    f"Организационный профиль применим только к форматам "
                    f"{sorted(_dp.PROFILE_FORMATS)}; запрошен {format!r}"
                )
            if not org_profile_id:
                raise _dp.OrgProfileRequired(
                    f"Формат {format!r} требует организационный профиль "
                    "(§19: выбранный профиль подтверждён валидатором и "
                    "organisational policy, не названием файла)"
                )
            profile_service.resolve_profile(
                org_profile_id, fmt=format, subject=subject
            )  # NotFound/Retired/FormatMismatch -- честные ошибки сервисного слоя
        existing = self.registry.find_rendition(
            snapshot.snapshot_id, format, redaction_profile
        )
        if (
            existing is not None
            and existing.state == RENDITION_READY
            and existing.job_id
            and self.registry.get_job(existing.job_id) is not None
        ):
            # DOCLOG-9 (§11/AC09): одна визуальная форма на цель --
            # готовая цель с ДРУГИМ профилем: честный 409, не вторая
            # версия и не тихий возврат чужой формы.
            if org_profile_id and existing.org_profile_id != org_profile_id:
                from apps.api.doc_profiles import OrgProfileMismatchError

                raise OrgProfileMismatchError(
                    "Rendition этой цели уже выпущена с другим "
                    f"профилем ({existing.org_profile_id!r}); профиль -- "
                    "часть формы выпуска (§11): создайте новую ревизию"
                )
            # AC09/§12.2: повторный клик -- прежний job/rendition, БЕЗ
            # нового задания и БЕЗ повторного рендера.
            job = self.registry.get_job(existing.job_id)
            return job, existing

        prior_jobs = [
            job
            for job in self.registry.list_jobs(run_id)
            if job.snapshot_id == snapshot.snapshot_id
            and job.format == format
            and job.redaction_profile == redaction_profile
        ]
        # AC09 (worker-режим): активное задание цели -- возврат ТОГО ЖЕ
        # job (двойной клик / гонка polling'а не плодят очередь версий).
        active = next(
            (
                job
                for job in prior_jobs
                if job.state in (JOB_QUEUED, JOB_RENDERING)
            ),
            None,
        )
        if active is not None:
            # DOCLOG-9: активное задание той же цели с другим профилем
            # -- та же честная политика mismatch.
            if org_profile_id and active.org_profile_id != org_profile_id:
                from apps.api.doc_profiles import OrgProfileMismatchError

                raise OrgProfileMismatchError(
                    "Активное задание этой цели выпущено с другим "
                    f"профилем ({active.org_profile_id!r}); профиль -- "
                    "часть формы выпуска (§11)"
                )
            return active, None
        # §18 retries: попытки рендера цели ограничены (MAX_JOB_ATTEMPTS)
        # -- честный отказ вместо вечной очереди.
        if len(prior_jobs) >= MAX_JOB_ATTEMPTS:
            raise DocumentRetryLimitExceeded(
                "retry_limit_exceeded: исчерпаны попытки рендера "
                f"({len(prior_jobs)}/{MAX_JOB_ATTEMPTS}) для "
                f"{format!r}; перечитайте версию или обратитесь в "
                "поддержку"
            )
        # §18 backpressure: per-tenant квота ОТКРЫТЫХ jobs (вся очередь
        # контура, не только этот run).
        tenant_id = getattr(subject, "tenant_id", None) or None
        open_jobs = self.registry.list_open_jobs()
        tenant_open = [
            job for job in open_jobs if (job.tenant_id or None) == tenant_id
        ]
        if len(tenant_open) >= MAX_OPEN_JOBS_PER_TENANT:
            raise DocumentQuotaExceeded(
                "quota_exceeded: очередь открытых заданий tenant "
                f"{tenant_id or 'default'} переполнена "
                f"({len(tenant_open)}/{MAX_OPEN_JOBS_PER_TENANT}); "
                "повторите позднее"
            )
        attempt = len(prior_jobs) + 1
        job = self.registry.register_job(
            DocumentJobRecord(
                job_id=new_job_id(),
                run_id=run_id,
                snapshot_id=snapshot.snapshot_id,
                format=format,
                redaction_profile=redaction_profile,
                revision_id=revision_id
                or (existing.revision_id if existing is not None else None),
                state=JOB_QUEUED,
                attempt=attempt,
                created_by=getattr(subject, "subject_id", None),
                tenant_id=tenant_id,
                org_profile_id=org_profile_id,
            )
        )
        if format in HEAVY_RENDITION_FORMATS:
            # §18: тяжёлый рендер -- асинхронный; 202 queued, rendition
            # появится после stage+commit worker'ом (AC08: никаких
            # broken ready refs по построению).
            return job, None
        job = self.registry.update_job(
            replace_dataclass(job, state=JOB_RENDERING)
        )
        try:
            content = _render_snapshot_by_format(snapshot, format)
        except UnsupportedFormatError:
            job = self.fail_render(job, "unsupported_format")
            raise
        except Exception:
            job = self.fail_render(job, "render_failed")
            return job, None
        job, rendition = self.complete_render(job, spec, content, snapshot)
        return job, rendition

    # -- финализация рендера (общий код AC08 для sync-пути и worker'а) --

    def complete_render(
        self,
        job: DocumentJobRecord,
        spec: Any,
        content: bytes,
        snapshot: ReportSnapshot,
    ) -> tuple[DocumentJobRecord, Optional[DocumentRenditionRecord]]:
        """Готовность ТОЛЬКО в порядке AC08: (DOCLOG-9: resolve профиля
        и ВАЛИДАТОР ДО stage -- failed-валидация не даёт ни байтов в
        object store) stage байтов -> commit в object store ->
        register/update rendition (с ЕДИНЫМ snapshot hash -- критерий
        завершения §19) -> job ready. Crash на любом шаге оставляет job
        в явном состоянии без broken ready refs. DOCLOG-9 (§19):
        профиль подтверждается ВАЛИДАТОРОМ, не названием файла --
        passed/failed записи пишутся ДОЛЖНЫ (доказательство); подпись/
        якорь/WORM применяются только к passed-выпуску."""
        from apps.api.artifact_store import artifact_content_sha256

        # F-D5C1 CAS-гейт (DOCLOG-E2E-RECHECK-1-FIX, акт §9.5 «проверить
        # прежнюю race отмены»): complete_render получает СВЕЖУЮ запись
        # задания из реестра, а не снимок воркера. Отменённое задание
        # завершением НЕ перезаписывается: cancel -- решение аналитика,
        # его исход не переписывается (паритет духа frozen §6).
        fresh = self.registry.get_job(job.job_id)
        if fresh is not None and fresh.state != job.state:
            job = fresh
        if job.state == JOB_CANCELLED:
            return job, None

        # ── DOCLOG-9: организационный профиль выпуска ───────────────
        profile = None
        profile_service = None
        passed_validation = None
        signature_manifest: Optional[dict[str, Any]] = None
        if job.org_profile_id:
            from apps.api import doc_profiles as _dp

            profile_service = _dp.org_profile_service()
            profile = profile_service.registry.get_profile(job.org_profile_id)
            if (
                profile is None
                or profile.status != _dp.PROFILE_ACTIVE
                or profile.format != job.format
            ):
                # Policy-проверка на момент ИСПОЛНЕНИЯ (retire между
                # постановкой и рендером -- честный terminal failed).
                return self.fail_render(job, "org_profile_unavailable"), None
            validation = profile_service.validate_output(
                content, job.format, profile
            )
            if validation.result != "passed":
                # «Профиль подтверждён валидатором»: failed -- честный
                # отказ выпуска (запись пишется с rendition_id="" --
                # ready-файла нет, AC08 по построению).
                profile_service.record_validation(
                    profile,
                    validation=validation,
                    fmt=job.format,
                    rendition_id="",
                    job_id=job.job_id,
                    run_id=job.run_id,
                    subject=None,
                )
                return (
                    self.fail_render(job, "profile_validation_failed"),
                    None,
                )
            passed_validation = validation
            if profile.sign_contents:
                try:
                    signature_manifest = _dp.sign_content(
                        content,
                        snapshot_sha256=snapshot.payload_sha256 or "",
                        profile_id=profile.profile_id,
                        profile_version_no=profile.version_no,
                        media_type=spec.media_type,
                        signed_by=job.created_by,
                    )
                except _dp.SignatureKeyUnavailable:
                    # Честный отказ (AC12-дух): тихая неподписанная
                    # ready запрещена.
                    return (
                        self.fail_render(job, "sign_key_unavailable"),
                        None,
                    )

        existing = self.registry.find_rendition(
            job.snapshot_id, job.format, job.redaction_profile
        )
        rendition_id = (
            existing.rendition_id if existing is not None else new_rendition_id()
        )
        staged = self.objects.stage_bytes(content, spec.media_type)
        storage_key = self.objects.commit_staged(staged)
        rendition = DocumentRenditionRecord(
            rendition_id=rendition_id,
            revision_id=(
                existing.revision_id
                if existing is not None
                else (job.revision_id or "")
            ),
            snapshot_id=job.snapshot_id,
            run_id=job.run_id,
            format=job.format,
            redaction_profile=job.redaction_profile,
            state=RENDITION_READY,
            media_type=spec.media_type,
            size_bytes=len(content),
            content_sha256=artifact_content_sha256(content),
            storage_key=storage_key,
            job_id=job.job_id,
            created_by=job.created_by,
            snapshot_payload_sha256=snapshot.payload_sha256 or "",
            org_profile_id=job.org_profile_id,
            content_bytes=(
                content
                if isinstance(self.registry, MemoryDocumentRegistry)
                else None
            ),
        )
        if existing is not None:
            rendition = self.registry.update_rendition(rendition)
        else:
            rendition = self.registry.register_rendition(rendition)
        if profile_service is not None and profile is not None:
            # ── DOCLOG-9: доказательства подтверждённого выпуска ──
            # (passed-валидация -- та же проверка, что до stage; запись
            # с rendition_id -- доказательство подтверждения).
            profile_service.record_validation(
                profile,
                validation=passed_validation,
                fmt=job.format,
                rendition_id=rendition.rendition_id,
                job_id=job.job_id,
                run_id=job.run_id,
                subject=None,
            )
            if signature_manifest is not None:
                profile_service.record_signature(
                    profile,
                    manifest=signature_manifest,
                    fmt=job.format,
                    rendition_id=rendition.rendition_id,
                    job_id=job.job_id,
                    run_id=job.run_id,
                    subject=None,
                )
            if profile.anchor_registry:
                profile_service.record_anchor(
                    profile,
                    content_sha256=rendition.content_sha256,
                    rendition_id=rendition.rendition_id,
                    subject=None,
                )
            if profile.worm_lock:
                revision = (
                    self.registry.get_revision(job.revision_id)
                    if job.revision_id
                    else None
                )
                document_id = (
                    str(revision.document_id) if revision is not None else ""
                )
                profile_service.apply_worm_hold(
                    profile,
                    document_id=document_id,
                    run_id=job.run_id,
                    subject=None,
                )
        # F-D5C1 CAS-гейт #2 (DOCLOG-E2E-RECHECK-1-FIX): ПЕРЕД финальной
        # готовностью -- повторная сверка с реестром. Гонка «cancel в
        # rendering -> завершение воркера»: отмена побеждает, готовые
        # байты не выдаются (rendition помечается failed -- паритет
        # fail_render «готовые байты НЕ выдаются»), job остаётся
        # cancelled.
        fresh_before_commit = self.registry.get_job(job.job_id)
        if (
            fresh_before_commit is not None
            and fresh_before_commit.state == JOB_CANCELLED
        ):
            self.registry.update_rendition(
                replace_dataclass(
                    rendition, state=RENDITION_FAILED, job_id=job.job_id
                )
            )
            return fresh_before_commit, None
        job = self.registry.update_job(
            replace_dataclass(
                job, state=JOB_READY, rendition_id=rendition.rendition_id
            )
        )
        return job, rendition

    def fail_render(
        self, job: DocumentJobRecord, error_code: str
    ) -> DocumentJobRecord:
        """Честная неудача попытки: job failed + error_code; существующая
        failed rendition (если была) помечается failed с этим job --
        готовые байты НЕ выдаются (AC08/§10.3)."""
        job = self.registry.update_job(
            replace_dataclass(job, state=JOB_FAILED, error_code=error_code)
        )
        existing = self.registry.find_rendition(
            job.snapshot_id, job.format, job.redaction_profile
        )
        if existing is not None:
            self.registry.update_rendition(
                replace_dataclass(
                    existing, state=RENDITION_FAILED, job_id=job.job_id
                )
            )
        return job

    def get_job(
        self, job_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[DocumentJobRecord, Optional[DocumentRenditionRecord]]:
        if not is_valid_job_id(job_id):
            raise DocumentAccessDenied("Задание недоступно")
        job = self.registry.get_job(job_id)
        if job is None:
            raise DocumentAccessDenied("Задание недоступно")
        self._authorized_run(job.run_id, subject, session_id=session_id, action="read")
        rendition = (
            self.registry.get_rendition(job.rendition_id)
            if job.rendition_id
            else None
        )
        return job, rendition

    def list_jobs(
        self, run_id: str, subject: Any, *, session_id: str = ""
    ) -> list[DocumentJobRecord]:
        self._authorized_run(run_id, subject, session_id=session_id, action="read")
        return self.registry.list_jobs(run_id)

    def cancel_job(
        self, job_id: str, subject: Any, *, session_id: str = ""
    ) -> DocumentJobRecord:
        """§17: cancel идемпотентен; научные результаты остаются. Ready/
        failed/cancelled -- no-op (результат/итог попытки не переписывается)."""
        job, _rendition = self.get_job(
            job_id, subject, session_id=session_id
        )
        if job.state in (JOB_QUEUED, JOB_RENDERING):
            job = self.registry.update_job(
                replace_dataclass(job, state=JOB_CANCELLED)
            )
        return job

    def read_rendition_content(
        self, rendition: DocumentRenditionRecord, subject: Any, *, session_id: str = ""
    ) -> bytes:
        """Байты готового файла: авторизация -> integrity (content_sha256)
        -> байты. Читает ТОЛЬКО документный слой; наука не трогается."""
        self._authorized_run(
            rendition.run_id, subject, session_id=session_id, action="read"
        )
        if rendition.state == RENDITION_PURGED:
            raise RenditionPurgedError(
                "Файл удалён политикой хранения (§16.1); соберите формат "
                "заново"
            )
        if rendition.state != RENDITION_READY or not rendition.storage_key:
            raise DocumentAccessDenied("Файл недоступен")
        if isinstance(self.registry, MemoryDocumentRegistry) and rendition.content_bytes is not None:
            content = rendition.content_bytes
        else:
            content = self.objects.read_bytes(rendition.storage_key)
        from apps.api.artifact_store import artifact_content_sha256

        if artifact_content_sha256(content) != rendition.content_sha256:
            raise DocumentIntegrityError(
                "Байты rendition не совпадают с content_sha256 (T8-дух)"
            )
        return content


def replace_dataclass(record: Any, **changes: Any) -> Any:
    """Иммутабельная замена полей записи (dataclasses.replace по духу,
    без зависимости от конкретного класса)."""
    from dataclasses import replace

    return replace(record, **changes)


def _render_snapshot_by_format(
    snapshot: ReportSnapshot, fmt: str, profile: Any = None
) -> bytes:
    """Диспетчер чистого рендера (document_renditions): lookup по
    globals() МОДУЛЯ -- негативные оракулы подменяют
    document_jobs.render_snapshot_* (job failed), при этом рендеры
    остаются чистыми функциями от снимка (AC05). DOCLOG-9: профиль
    организации -- второй аргумент рендеров docx/pdfa (f(снимок,
    профиль)); профиль не входит в identity идемпотентности (AC09),
    но входит в байты (R06 -- оформление профиля)."""
    func = globals().get(f"render_snapshot_{fmt}")
    if func is None or not callable(func):
        raise UnsupportedFormatError(
            f"Формат {fmt!r} не входит в каталог P0 (§7)"
        )
    result = func(snapshot, profile) if fmt in ("docx", "pdfa") else func(snapshot)
    if isinstance(result, bytes):
        return result
    return str(result).encode("utf-8")
