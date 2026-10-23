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

import os
import re
import threading
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.report_snapshot import (
    DEFAULT_REDACTION_PROFILE,
    DOCUMENT_KINDS,
    ReportSnapshot,
)
# Рендеры P0 -- чистые функции (§7/R06): импортируются в namespace
# МОДУЛЯ (dispatch через globals() -- оракулы подменяют точки входа
# document_jobs.render_snapshot_* для негативных сценариев рендера).
from apps.api.document_renditions import (
    RENDITION_FORMATS,
    render_snapshot_csv,
    render_snapshot_html,
    render_snapshot_json,
    render_snapshot_jsonl,
)
from apps.api.document_renditions import (
    render_snapshot_markdown as render_snapshot_md,
)

DOCUMENTS_BACKEND_ENV = "CISSTAT_DOCUMENTS_BACKEND"

# §11: состояния оси генерации.
JOB_QUEUED = "queued"
JOB_RENDERING = "rendering"
JOB_READY = "ready"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_STATES = frozenset({JOB_QUEUED, JOB_RENDERING, JOB_READY, JOB_FAILED, JOB_CANCELLED})

RENDITION_READY = "ready"
RENDITION_FAILED = "failed"


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

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        raise NotImplementedError


class MemoryDocumentRegistry(DocumentRegistry):
    """Memory-реестр (dev/тесты/auto). Байты rendition -- в records."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._documents: dict[str, DocumentRecord] = {}
        self._revisions: dict[str, DocumentRevisionRecord] = {}
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
        from apps.api.research_runs import database_dsn

        return cls(database_dsn())

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

    # -- renditions --

    _RENDITION_SELECT = (
        "SELECT rendition_id, revision_id, snapshot_id, run_id, format, "
        "redaction_profile, state, media_type, size_bytes, content_sha256, "
        "storage_key, job_id, created_by, created_at FROM document_renditions"
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
        )

    def register_rendition(
        self, rendition: DocumentRenditionRecord
    ) -> DocumentRenditionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_renditions (rendition_id, revision_id, "
                "snapshot_id, run_id, format, redaction_profile, state, "
                "media_type, size_bytes, content_sha256, storage_key, job_id, "
                "created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (snapshot_id, format, redaction_profile) "
                "DO UPDATE SET state = EXCLUDED.state, media_type = "
                "EXCLUDED.media_type, size_bytes = EXCLUDED.size_bytes, "
                "content_sha256 = EXCLUDED.content_sha256, storage_key = "
                "EXCLUDED.storage_key, job_id = EXCLUDED.job_id",
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
                "job_id = %s WHERE rendition_id = %s",
                (
                    rendition.state,
                    rendition.media_type,
                    rendition.size_bytes,
                    rendition.content_sha256,
                    rendition.storage_key,
                    rendition.job_id,
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
        "created_at, updated_at FROM document_jobs"
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
        )

    def register_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_jobs (job_id, run_id, snapshot_id, "
                "format, redaction_profile, revision_id, rendition_id, state, "
                "error_code, attempt, created_by, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                ),
            )
        return job

    def update_job(self, job: DocumentJobRecord) -> DocumentJobRecord:
        job.updated_at = _now_iso()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE document_jobs SET state = %s, error_code = %s, "
                "attempt = %s, rendition_id = %s, updated_at = %s "
                "WHERE job_id = %s",
                (
                    job.state,
                    job.error_code,
                    job.attempt,
                    job.rendition_id,
                    job.updated_at,
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


# ── Фабрики (паритет get_artifact_registry / get_snapshot_registry) ──


_registry: Optional[DocumentRegistry] = None
_registry_lock = threading.Lock()


def get_document_registry() -> DocumentRegistry:
    """Фабрика реестра документов. CISSTAT_DOCUMENTS_BACKEND:
    memory | postgres | (auto -- DATABASE_URL ? postgres : memory)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            backend = (os.environ.get(DOCUMENTS_BACKEND_ENV) or "").strip().lower()
            dsn = (os.environ.get("DATABASE_URL") or "").strip()
            if backend == "memory" or (not backend and not dsn):
                _registry = MemoryDocumentRegistry()
            elif backend in ("", "auto", "postgres") and dsn:
                _registry = PostgresDocumentRegistry(dsn)
            elif backend in ("", "auto"):
                _registry = MemoryDocumentRegistry()
            else:
                raise RuntimeError(
                    f"{DOCUMENTS_BACKEND_ENV}={backend!r} не поддерживается; "
                    "доступно: memory | postgres"
                )
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
    ) -> tuple[DocumentJobRecord, Optional[DocumentRenditionRecord]]:
        from apps.api.artifact_store import artifact_content_sha256

        run_id = snapshot.research_run_id
        self._authorized_run(run_id, subject, session_id=session_id, action="write")
        spec = RENDITION_FORMATS.get(format)
        if spec is None:
            raise UnsupportedFormatError(
                f"Формат {format!r} не входит в каталог P0 (§7)"
            )
        existing = self.registry.find_rendition(
            snapshot.snapshot_id, format, redaction_profile
        )
        if (
            existing is not None
            and existing.state == RENDITION_READY
            and existing.job_id
            and self.registry.get_job(existing.job_id) is not None
        ):
            # AC09/§12.2: повторный клик -- прежний job/rendition, БЕЗ
            # нового задания и БЕЗ повторного рендера.
            job = self.registry.get_job(existing.job_id)
            return job, existing

        attempt = len(
            [
                job
                for job in self.registry.list_jobs(run_id)
                if job.snapshot_id == snapshot.snapshot_id
                and job.format == format
                and job.redaction_profile == redaction_profile
            ]
        ) + 1
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
            )
        )
        job = self.registry.update_job(
            replace_dataclass(job, state=JOB_RENDERING)
        )
        try:
            content = _render_snapshot_by_format(snapshot, format)
        except UnsupportedFormatError:
            job = self.registry.update_job(
                replace_dataclass(job, state=JOB_FAILED, error_code="unsupported_format")
            )
            raise
        except Exception:
            job = self.registry.update_job(
                replace_dataclass(job, state=JOB_FAILED, error_code="render_failed")
            )
            if existing is not None:
                self.registry.update_rendition(
                    replace_dataclass(
                        existing, state=RENDITION_FAILED, job_id=job.job_id
                    )
                )
            return job, None

        staged = self.objects.stage_bytes(content, spec.media_type)
        storage_key = self.objects.commit_staged(staged)
        rendition = DocumentRenditionRecord(
            rendition_id=(
                existing.rendition_id if existing is not None else new_rendition_id()
            ),
            revision_id=(
                revision_id
                or (existing.revision_id if existing is not None else "")
            ),
            snapshot_id=snapshot.snapshot_id,
            run_id=run_id,
            format=format,
            redaction_profile=redaction_profile,
            state=RENDITION_READY,
            media_type=spec.media_type,
            size_bytes=len(content),
            content_sha256=artifact_content_sha256(content),
            storage_key=storage_key,
            job_id=job.job_id,
            created_by=getattr(subject, "subject_id", None),
            content_bytes=content if isinstance(self.registry, MemoryDocumentRegistry) else None,
        )
        if existing is not None:
            rendition = self.registry.update_rendition(rendition)
        else:
            rendition = self.registry.register_rendition(rendition)
        job = self.registry.update_job(
            replace_dataclass(
                job, state=JOB_READY, rendition_id=rendition.rendition_id
            )
        )
        return job, rendition

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


def _render_snapshot_by_format(snapshot: ReportSnapshot, fmt: str) -> bytes:
    """Диспетчер чистого рендера (document_renditions): lookup по
    globals() МОДУЛЯ -- негативные оракулы подменяют
    document_jobs.render_snapshot_* (job failed), при этом рендеры
    остаются чистыми функциями от снимка (AC05)."""
    func = globals().get(f"render_snapshot_{fmt}")
    if func is None or not callable(func):
        raise UnsupportedFormatError(
            f"Формат {fmt!r} не входит в каталог P0 (§7)"
        )
    result = func(snapshot)
    if isinstance(result, bytes):
        return result
    return str(result).encode("utf-8")
