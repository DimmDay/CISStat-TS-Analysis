# apps/api/document_lifecycle.py
"""
DOCLOG-6 (spec_documentation_logging.md §11, §14.1, §15, §16, §17,
§19 строка DOCLOG-6, §20 AC04-дух/AC05/AC06/AC07/AC11/AC17/AC18):
согласование и архив -- ось СОДЕРЖАНИЯ жизненного цикла документов.

ПОСТАНОВКА (§19): «D10/D11, approvals/retract/supersede, независимая
от checkpoints retention, backup/restore». Критерии завершения:
«approval bound hash, разделение прав, deletion/hold и restore drill».

КОНТУР -- APPEND-ONLY ПОВЕРХ АДАПТЕРА DOCLOG-4 (§11): ревизия остаётся
непереписываемой ссылкой на frozen-снимок; lifecycle-записи
(approval_requested/approved/rejected/published/retracted/superseded)
НЕ переписываются и НЕ удаляются, состояние ревизии ВЫЧИСЛЯЕТСЯ из
упорядоченных записей (последняя определяет состояние):
  draft -> ready_for_review -> approved | rejected;
  approved -> published; published -> retracted | superseded.

APPROVAL BOUND HASH (AC07): ApprovalRecord хранит ТОЧНЫЙ revision_id,
registry payload_sha256 снимка и approval_manifest (rendition_id,
format, content_sha256 всех ready-renditions на момент утверждения).
Publish ПЕРЕПРОВЕРЯЕТ хэши: расхождение/утрата -- честный 409
approval_not_applicable («старое approval не переносится на новый
hash»). Publish пинирует snapshot (ref_kind=snapshot, reason=
document:{id}:published:{version_no}) -- deletion-защита независимо
от checkpoint keeper'а (§16/AC04-дух).

РАЗДЕЛЕНИЕ ПРАВ (§15/D5): lifecycle_rights(subject) -- ADMIN-роль
(§15.1 полный каталог) | явные scopes документации у API-ключа |
cookie-суррогат в пилотных режимах (session_scoped/dev_single_user --
честная непрерывность с DOCLOG-4; в режиме scoped права НЕ
фантазируются). Отказ в правах у владельца -- 403 insufficient_scope;
чужое/нет -- uniform 404 (без изменений, R09).

POLICY (D6): CISSTAT_DOCLOG_APPROVAL_POLICY = single (дефолт пилота) |
two_person (утверждающий != создатель ревизии и != запросивший
согласование). Незнакомое значение -- fail-closed к single + warning
(прецедент identity-mode). Нарушение -- 422 self_approval_forbidden.

MANDATORY AUDIT (§14.1/AC11): approve/publish/retract --
record_mandatory fail-closed ДО действия (сбой аудита -> операция не
выполняется, состояние не меняется). Retention/archive/drill --
record_standard.

RETENTION (§16.1/D8) -- НЕЗАВИСИМАЯ от checkpoint keeper'а: hold
приоритетен; published/approved/retracted/superseded документы не
очищаются («опубликованные -- до явного окончания archival policy»);
draft-документ: готовые renditions старше
CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS (30) -- purge: байты из object
store удаляются, rendition.state="purged" (tombstone честен: запись и
хэши сохранены, байтов нет), чтение -- 410 purged_artifact владельцу
(§17 «410 -- известный разрешённому владельцу purged artifact»).

ARCHIVE/RESTORE DRILL (§16/AC18/D9): bundle = metadata.jsonl (все
сущности контура) + objects/{sha256} (байты снимков/renditions) +
manifest.json (sha256 каждого члена КРОМЕ самого манифеста -- §13.3).
Drill проверяет члены + ссылочную целостность + bound-hash согласований;
missing/mismatched ЯВНО перечисляются (не маскируются); duration_ms
drill замерен (RPO/RTO не декларируются).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("cisstat.document_lifecycle")

# ── Состояния ревизии (§11 ось содержания) ───────────────────────────

STATE_DRAFT = "draft"
STATE_READY_FOR_REVIEW = "ready_for_review"
STATE_APPROVED = "approved"
STATE_PUBLISHED = "published"
STATE_REJECTED = "rejected"
STATE_RETRACTED = "retracted"
STATE_SUPERSEDED = "superseded"

# ── Lifecycle-события (append-only) ──────────────────────────────────

EVENT_REQUEST = "approval_requested"
EVENT_APPROVED = "approved"
EVENT_REJECTED = "rejected"
EVENT_PUBLISHED = "published"
EVENT_RETRACTED = "retracted"
EVENT_SUPERSEDED = "superseded"

LIFECYCLE_EVENTS = frozenset(
    {EVENT_REQUEST, EVENT_APPROVED, EVENT_REJECTED, EVENT_PUBLISHED,
     EVENT_RETRACTED, EVENT_SUPERSEDED}
)

# Состояния, защищающие документ от retention-очистки (§16.1).
_PROTECTED_STATES = frozenset(
    {STATE_APPROVED, STATE_PUBLISHED, STATE_RETRACTED, STATE_SUPERSEDED}
)

APPROVAL_POLICY_ENV = "CISSTAT_DOCLOG_APPROVAL_POLICY"
POLICY_SINGLE = "single"
POLICY_TWO_PERSON = "two_person"
APPROVAL_POLICY_VERSION = "doclog6-approval-policy-v1"

RETENTION_DRAFT_DAYS_ENV = "CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS"
DEFAULT_RETENTION_DRAFT_DAYS = 30  # §16.1 «Невостребованные draft renditions»

ARCHIVE_BUNDLE_PREFIX = "d6arch-"

RENDITION_PURGED = "purged"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def new_approval_id() -> str:
    return _new_id("dapp-")


def new_lifecycle_id() -> str:
    return _new_id("dlc-")


# ── Ошибки контура (HTTP-маппинг -- routers/documentation.py) ────────


class LifecycleAccessDenied(RuntimeError):
    """R09/T15: ресурс не существует ЛИБО не принадлежит субъекту --
    HTTP-слой отвечает uniform 404."""


class InsufficientScopeError(RuntimeError):
    """§15/D5: субъект авторизован на ресурсе (владелец), но права на
    действие НЕТ (scope/policy) -- честный 403 insufficient_scope."""


class InvalidTransitionError(ValueError):
    """§11/D3: незаконный переход состояния -- 422 invalid_transition."""


class SelfApprovalForbiddenError(RuntimeError):
    """§11/D6: two_person policy запрещает самоутверждение -- 422."""


class ApprovalHashMismatchError(ValueError):
    """AC07: expected_snapshot_sha256 не совпал с текущим -- 409."""


class ApprovalNotApplicableError(RuntimeError):
    """§11/AC07: хэши снимка/renditions изменились после согласования
    (либо согласование не верифицируемо) -- publish отказывает, 409."""


class PublishRequiresApprovalError(RuntimeError):
    """§11: публикация без согласования -- 422."""


class PublishBlockedGapsError(RuntimeError):
    """§11: обязательные разделы/полнота -- publish заблокирован, 422."""


class DiffAcrossDocumentsError(ValueError):
    """§17: diff применим только к ревизиям одного документа -- 422."""


# ── Policy и права (D6/D5) ───────────────────────────────────────────


def approval_policy() -> str:
    """Активная policy согласования; незнакомое значение -- fail-closed
    к single (дефолт пилота) + warning (прецедент identity-mode)."""
    raw = (os.environ.get(APPROVAL_POLICY_ENV) or "").strip().lower()
    if not raw:
        return POLICY_SINGLE
    if raw not in (POLICY_SINGLE, POLICY_TWO_PERSON):
        logger.warning(
            "Approval policy: незнакомый %s=%r -- fail-closed к %s",
            APPROVAL_POLICY_ENV, raw, POLICY_SINGLE,
        )
        return POLICY_SINGLE
    return raw


def retention_draft_days() -> int:
    """§16.1: срок невостребованных draft renditions (дней; дефолт 30).
    Некорректное значение -- честный дефолт (без отрицательных сроков)."""
    raw = (os.environ.get(RETENTION_DRAFT_DAYS_ENV) or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_RETENTION_DRAFT_DAYS
    except ValueError:
        return DEFAULT_RETENTION_DRAFT_DAYS
    return value if value >= 0 else DEFAULT_RETENTION_DRAFT_DAYS


@dataclass(frozen=True)
class LifecycleRights:
    """Разделение прав §15/D5. basis -- честная причина выдачи."""

    can_request: bool = False
    can_approve: bool = False
    can_publish: bool = False
    can_retention: bool = False
    basis: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_request": self.can_request,
            "can_approve": self.can_approve,
            "can_publish": self.can_publish,
            "can_retention": self.can_retention,
            "basis": self.basis,
        }


_SCOPE_APPROVE = "documentation.approve"
_SCOPE_PUBLISH = "documentation.publish"
_SCOPE_WRITE = "documentation.write"
_SCOPE_POLICY_ADMIN = "policy.admin"

_PILOT_MODES = frozenset({"session_scoped", "dev_single_user"})


def lifecycle_rights(subject: Any) -> LifecycleRights:
    """Разделение прав (§15/D5). ADMIN -- полный каталог (§15.1);
    API-ключ -- по явным scopes; cookie-суррогат -- пилотная
    непрерывность с DOCLOG-4 ТОЛЬКО в режимах session_scoped/
    dev_single_user (в режиме scoped права не фантазируются)."""
    if subject is None or getattr(subject, "is_anonymous", True):
        return LifecycleRights()
    role = (getattr(subject, "role", None) or "")
    if role == "admin":
        return LifecycleRights(True, True, True, True, "admin_full_catalog")
    via = getattr(subject, "via", "")
    scopes = frozenset(getattr(subject, "scopes", ()) or ())
    if via == "api_key":
        mode = _identity_mode()
        if mode == "scoped" and not scopes:
            return LifecycleRights(basis="scoped_mode_no_pilot_rights")
        return LifecycleRights(
            can_request=_SCOPE_WRITE in scopes,
            can_approve=_SCOPE_APPROVE in scopes,
            can_publish=_SCOPE_PUBLISH in scopes,
            can_retention=_SCOPE_POLICY_ADMIN in scopes,
            basis="scope",
        )
    if via == "session_surrogate" and _identity_mode() in _PILOT_MODES:
        # Пилотная непрерывность (D5): run-уровень решающей таблицы
        # DOCLOG-0 всё равно гейтит владение на каждом методе.
        return LifecycleRights(True, True, True, True, "session_owner_pilot")
    return LifecycleRights(basis="scoped_mode_no_pilot_rights")


def _identity_mode() -> str:
    try:
        from apps.api.identity import get_identity_mode

        return get_identity_mode()
    except Exception:  # pragma: no cover -- mode не роняет права
        return "session_scoped"


# ── Записи ───────────────────────────────────────────────────────────


@dataclass
class ApprovalRecord:
    """§9.1 Approval: approval_id, точный document_revision_id И
    snapshot hash, actor, policy/version, решение/время/основание."""

    approval_id: str
    revision_id: str
    document_id: str
    run_id: str
    decision: str  # approve | reject
    actor_subject: str = ""
    actor_via: str = ""
    tenant_id: Optional[str] = None
    policy: str = POLICY_SINGLE
    policy_version: str = APPROVAL_POLICY_VERSION
    reason: str = ""
    snapshot_payload_sha256: str = ""
    approval_manifest: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "revision_id": self.revision_id,
            "document_id": self.document_id,
            "run_id": self.run_id,
            "decision": self.decision,
            "actor_subject": self.actor_subject,
            "actor_via": self.actor_via,
            "tenant_id": self.tenant_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "reason": self.reason,
            "snapshot_payload_sha256": self.snapshot_payload_sha256,
            "approval_manifest": [dict(item) for item in self.approval_manifest],
            "created_at": self.created_at,
        }


@dataclass
class LifecycleRecord:
    """Append-only запись жизненного цикла (§11)."""

    record_id: str
    document_id: str
    revision_id: str
    run_id: str
    event: str
    actor_subject: Optional[str] = None
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "run_id": self.run_id,
            "event": self.event,
            "actor_subject": self.actor_subject,
            "reason": self.reason,
            "details": dict(self.details),
            "created_at": self.created_at,
        }


@dataclass
class RetentionRecord:
    """§16.1: hold/приоритет очистки на документе."""

    document_id: str
    run_id: str
    hold: bool = False
    hold_reason: str = ""
    updated_by: Optional[str] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "run_id": self.run_id,
            "hold": self.hold,
            "hold_reason": self.hold_reason,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


# ── Реестр (ABC + Memory + Postgres, паритет фабрик DOCLOG-4) ────────


class DocumentLifecycleRegistry(ABC):
    """Metadata-реестр согласования/архива (§8.1: тот же Postgres;
    миграция 0012)."""

    def append_approval(self, approval: ApprovalRecord) -> ApprovalRecord:  # pragma: no cover
        raise NotImplementedError

    def list_approvals(self, revision_id: str) -> list[ApprovalRecord]:  # pragma: no cover
        raise NotImplementedError

    def latest_approval(self, revision_id: str) -> Optional[ApprovalRecord]:  # pragma: no cover
        raise NotImplementedError

    def append_lifecycle(self, record: LifecycleRecord) -> LifecycleRecord:  # pragma: no cover
        raise NotImplementedError

    def list_lifecycle(self, revision_id: str) -> list[LifecycleRecord]:  # pragma: no cover
        raise NotImplementedError

    def get_retention(self, document_id: str) -> Optional[RetentionRecord]:  # pragma: no cover
        raise NotImplementedError

    def upsert_retention(self, record: RetentionRecord) -> RetentionRecord:  # pragma: no cover
        raise NotImplementedError

    def list_retention(self, run_id: str) -> list[RetentionRecord]:  # pragma: no cover
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        raise NotImplementedError


class MemoryDocumentLifecycleRegistry(DocumentLifecycleRegistry):
    """Memory-реестр (dev/тесты/auto)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._approvals: dict[str, ApprovalRecord] = {}
        self._lifecycle: dict[str, LifecycleRecord] = {}
        self._retention: dict[str, RetentionRecord] = {}

    def append_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self._approvals[approval.approval_id] = approval
            return approval

    def list_approvals(self, revision_id: str) -> list[ApprovalRecord]:
        with self._lock:
            approvals = [
                approval
                for approval in self._approvals.values()
                if approval.revision_id == revision_id
            ]
        return sorted(approvals, key=lambda item: (item.created_at, item.approval_id))

    def latest_approval(self, revision_id: str) -> Optional[ApprovalRecord]:
        approvals = self.list_approvals(revision_id)
        return approvals[-1] if approvals else None

    def append_lifecycle(self, record: LifecycleRecord) -> LifecycleRecord:
        with self._lock:
            self._lifecycle[record.record_id] = record
            return record

    def list_lifecycle(self, revision_id: str) -> list[LifecycleRecord]:
        with self._lock:
            records = [
                record
                for record in self._lifecycle.values()
                if record.revision_id == revision_id
            ]
        return sorted(records, key=lambda item: (item.created_at, item.record_id))

    def get_retention(self, document_id: str) -> Optional[RetentionRecord]:
        with self._lock:
            record = self._retention.get(document_id)
            return RetentionRecord(**record.to_dict()) if record else None

    def upsert_retention(self, record: RetentionRecord) -> RetentionRecord:
        with self._lock:
            self._retention[record.document_id] = record
            return record

    def list_retention(self, run_id: str) -> list[RetentionRecord]:
        with self._lock:
            records = [
                record
                for record in self._retention.values()
                if record.run_id == run_id
            ]
        return sorted(records, key=lambda item: item.document_id)

    def readiness_probe(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory"}


class PostgresDocumentLifecycleRegistry(DocumentLifecycleRegistry):
    """Durable-реестр (миграция 0012; ленивый psycopg -- паритет
    фабрик DOCLOG-4/5)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._migrated = False

    @classmethod
    def from_env(cls) -> "PostgresDocumentLifecycleRegistry":
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

    def append_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_approvals (approval_id, revision_id, "
                "document_id, run_id, decision, actor_subject, actor_via, "
                "tenant_id, policy, policy_version, reason, "
                "snapshot_payload_sha256, approval_manifest, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (approval_id) DO NOTHING",
                (
                    approval.approval_id,
                    approval.revision_id,
                    approval.document_id,
                    approval.run_id,
                    approval.decision,
                    approval.actor_subject,
                    approval.actor_via,
                    approval.tenant_id,
                    approval.policy,
                    approval.policy_version,
                    approval.reason,
                    approval.snapshot_payload_sha256,
                    psycopg.types.json.Jsonb(approval.approval_manifest),
                    approval.created_at,
                ),
            )
        return approval

    def list_approvals(self, revision_id: str) -> list[ApprovalRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT approval_id, revision_id, document_id, run_id, "
                "decision, actor_subject, actor_via, tenant_id, policy, "
                "policy_version, reason, snapshot_payload_sha256, "
                "approval_manifest, created_at FROM document_approvals "
                "WHERE revision_id = %s ORDER BY created_at, approval_id",
                (revision_id,),
            )
            rows = cur.fetchall()
        return [self._approval_from_row(row) for row in rows]

    def latest_approval(self, revision_id: str) -> Optional[ApprovalRecord]:
        approvals = self.list_approvals(revision_id)
        return approvals[-1] if approvals else None

    @staticmethod
    def _approval_from_row(row: tuple) -> ApprovalRecord:
        import json as _json

        return ApprovalRecord(
            approval_id=str(row[0]),
            revision_id=str(row[1]),
            document_id=str(row[2]),
            run_id=str(row[3]),
            decision=str(row[4]),
            actor_subject=row[5] or "",
            actor_via=row[6] or "",
            tenant_id=row[7],
            policy=row[8] or POLICY_SINGLE,
            policy_version=row[9] or APPROVAL_POLICY_VERSION,
            reason=row[10] or "",
            snapshot_payload_sha256=row[11] or "",
            approval_manifest=(
                row[12]
                if isinstance(row[12], list)
                else (_json.loads(row[12]) if row[12] else [])
            ),
            created_at=row[13].isoformat() if row[13] else _now_iso(),
        )

    def append_lifecycle(self, record: LifecycleRecord) -> LifecycleRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_lifecycle (record_id, document_id, "
                "revision_id, run_id, event, actor_subject, reason, details, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (record_id) DO NOTHING",
                (
                    record.record_id,
                    record.document_id,
                    record.revision_id,
                    record.run_id,
                    record.event,
                    record.actor_subject,
                    record.reason,
                    psycopg.types.json.Jsonb(record.details),
                    record.created_at,
                ),
            )
        return record

    def list_lifecycle(self, revision_id: str) -> list[LifecycleRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT record_id, document_id, revision_id, run_id, event, "
                "actor_subject, reason, details, created_at FROM "
                "document_lifecycle WHERE revision_id = %s "
                "ORDER BY created_at, record_id",
                (revision_id,),
            )
            rows = cur.fetchall()
        return [self._lifecycle_from_row(row) for row in rows]

    @staticmethod
    def _lifecycle_from_row(row: tuple) -> LifecycleRecord:
        import json as _json

        return LifecycleRecord(
            record_id=str(row[0]),
            document_id=str(row[1]),
            revision_id=str(row[2]),
            run_id=str(row[3]),
            event=str(row[4]),
            actor_subject=row[5],
            reason=row[6] or "",
            details=(
                row[7]
                if isinstance(row[7], dict)
                else (_json.loads(row[7]) if row[7] else {})
            ),
            created_at=row[8].isoformat() if row[8] else _now_iso(),
        )

    def get_retention(self, document_id: str) -> Optional[RetentionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT document_id, run_id, hold, hold_reason, updated_by, "
                "updated_at FROM document_retention WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return RetentionRecord(
            document_id=str(row[0]),
            run_id=str(row[1]),
            hold=bool(row[2]),
            hold_reason=row[3] or "",
            updated_by=row[4],
            updated_at=row[5].isoformat() if row[5] else _now_iso(),
        )

    def upsert_retention(self, record: RetentionRecord) -> RetentionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_retention (document_id, run_id, hold, "
                "hold_reason, updated_by, updated_at) VALUES "
                "(%s, %s, %s, %s, %s, %s) ON CONFLICT (document_id) DO "
                "UPDATE SET hold = EXCLUDED.hold, hold_reason = "
                "EXCLUDED.hold_reason, updated_by = EXCLUDED.updated_by, "
                "updated_at = EXCLUDED.updated_at",
                (
                    record.document_id,
                    record.run_id,
                    record.hold,
                    record.hold_reason,
                    record.updated_by,
                    record.updated_at,
                ),
            )
        return record

    def list_retention(self, run_id: str) -> list[RetentionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT document_id, run_id, hold, hold_reason, updated_by, "
                "updated_at FROM document_retention WHERE run_id = %s "
                "ORDER BY document_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [
            RetentionRecord(
                document_id=str(row[0]),
                run_id=str(row[1]),
                hold=bool(row[2]),
                hold_reason=row[3] or "",
                updated_by=row[4],
                updated_at=row[5].isoformat() if row[5] else _now_iso(),
            )
            for row in rows
        ]


_LIFECYCLE_REGISTRY: Optional[DocumentLifecycleRegistry] = None
_LIFECYCLE_REGISTRY_LOCK = threading.Lock()
LIFECYCLE_BACKEND_ENV = "CISSTAT_DOCUMENTS_BACKEND"


def get_document_lifecycle_registry() -> DocumentLifecycleRegistry:
    """Фабрика реестра (паритет get_document_registry: тот же
    CISSTAT_DOCUMENTS_BACKEND/DATABASE_URL -- тот же Postgres §8.1)."""
    global _LIFECYCLE_REGISTRY
    with _LIFECYCLE_REGISTRY_LOCK:
        if _LIFECYCLE_REGISTRY is None:
            backend = (os.environ.get(LIFECYCLE_BACKEND_ENV) or "").strip().lower()
            dsn = (os.environ.get("DATABASE_URL") or "").strip()
            if backend == "memory" or (not backend and not dsn):
                _LIFECYCLE_REGISTRY = MemoryDocumentLifecycleRegistry()
            elif backend in ("", "auto", "postgres") and dsn:
                _LIFECYCLE_REGISTRY = PostgresDocumentLifecycleRegistry(dsn)
            elif backend in ("", "auto"):
                _LIFECYCLE_REGISTRY = MemoryDocumentLifecycleRegistry()
            else:
                raise RuntimeError(
                    f"{LIFECYCLE_BACKEND_ENV}={backend!r} не поддерживается; "
                    "доступно: memory | postgres"
                )
        return _LIFECYCLE_REGISTRY


def peek_document_lifecycle_registry() -> Optional[DocumentLifecycleRegistry]:
    return _LIFECYCLE_REGISTRY


def reset_document_lifecycle_registry_for_testing() -> None:
    global _LIFECYCLE_REGISTRY
    with _LIFECYCLE_REGISTRY_LOCK:
        _LIFECYCLE_REGISTRY = None


# ── Сервис согласования/архива ───────────────────────────────────────


class DocumentLifecycleService:
    """Ось содержания поверх адаптера DOCLOG-4 (§11/§16/§17).

    Авторизация -- ПЕРВЫЙ шаг каждого метода: резолв ревизии/документа
    через DocumentDeliveryService.get_revision (решающая таблица
    DOCLOG-0), затем -- разделение прав D5. Согласование НЕ меняет
    снимок/науку (AC05): только lifecycle-записи и retention/pins."""

    def __init__(self, registry: DocumentLifecycleRegistry, delivery: Any) -> None:
        self.registry = registry
        self.delivery = delivery

    @classmethod
    def create_default(cls) -> "DocumentLifecycleService":
        return cls(get_document_lifecycle_registry(), _delivery_service())

    # -- базовые резолвы (авторизация через delivery, R09) --

    def _resolve_revision(
        self, revision_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[Any, Any, Any]:
        from apps.api.document_jobs import DocumentAccessDenied

        try:
            return self.delivery.get_revision(
                revision_id, subject, session_id=session_id
            )
        except DocumentAccessDenied as exc:
            raise LifecycleAccessDenied(str(exc)) from None

    def _resolve_document(
        self, document_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[Any, list[Any]]:
        from apps.api.document_jobs import DocumentAccessDenied

        try:
            return self.delivery.get_document_with_revisions(
                document_id, subject, session_id=session_id
            )
        except DocumentAccessDenied as exc:
            raise LifecycleAccessDenied(str(exc)) from None

    def _resolve_run(self, run_id: str, subject: Any, *, session_id: str = "", action: str = "read") -> Any:
        from apps.api.document_jobs import DocumentAccessDenied

        try:
            return self.delivery._authorized_run(
                run_id, subject, session_id=session_id, action=action
            )
        except DocumentAccessDenied as exc:
            raise LifecycleAccessDenied(str(exc)) from None

    # -- состояние ревизии (вычисляется из append-only записей) --

    def revision_state(self, revision_id: str) -> str:
        records = self.registry.list_lifecycle(revision_id)
        state = STATE_DRAFT
        for record in records:
            if record.event == EVENT_REQUEST:
                state = STATE_READY_FOR_REVIEW
            elif record.event == EVENT_APPROVED:
                state = STATE_APPROVED
            elif record.event == EVENT_REJECTED:
                state = STATE_REJECTED
            elif record.event == EVENT_PUBLISHED:
                state = STATE_PUBLISHED
            elif record.event == EVENT_RETRACTED:
                state = STATE_RETRACTED
            elif record.event == EVENT_SUPERSEDED:
                state = STATE_SUPERSEDED
        return state

    def _latest_approval_record(self, revision_id: str) -> Optional[ApprovalRecord]:
        approvals = [
            approval
            for approval in self.registry.list_approvals(revision_id)
            if approval.decision == "approve"
        ]
        return approvals[-1] if approvals else None

    # -- запрос согласования --

    def request_approval(
        self, revision_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[Any, str]:
        revision, _document, _snapshot = self._resolve_revision(
            revision_id, subject, session_id=session_id
        )
        rights = lifecycle_rights(subject)
        if not rights.can_request:
            raise InsufficientScopeError(
                "documentation.write требуется для запроса согласования"
            )
        state = self.revision_state(revision_id)
        if state != STATE_DRAFT:
            raise InvalidTransitionError(
                f"Запрос согласования возможен только из draft (текущее: {state})"
            )
        self.registry.append_lifecycle(
            LifecycleRecord(
                record_id=new_lifecycle_id(),
                document_id=revision.document_id,
                revision_id=revision.revision_id,
                run_id=revision.run_id,
                event=EVENT_REQUEST,
                actor_subject=getattr(subject, "subject_id", None),
                reason="",
                details={"basis": rights.basis},
            )
        )
        return revision, STATE_READY_FOR_REVIEW

    # -- решение согласующего (approve/reject) --

    def decide_approval(
        self,
        revision_id: str,
        subject: Any,
        *,
        session_id: str = "",
        decision: str,
        reason: str = "",
        expected_snapshot_sha256: Optional[str] = None,
    ) -> tuple[Any, ApprovalRecord, str]:
        # Порядок fail-closed (R09): СНАЧАЛА резолв ресурса/права,
        # ТОЛЬКО затем валидация тела (незнакомое решение чужому тоже
        # отвечает uniform 404, существование не дисклоужается).
        revision, document, _snapshot = self._resolve_revision(
            revision_id, subject, session_id=session_id
        )
        if decision not in ("approve", "reject"):
            raise InvalidTransitionError(
                "decision обязан быть approve | reject"
            )
        rights = lifecycle_rights(subject)
        if not rights.can_approve:
            raise InsufficientScopeError(
                "documentation.approve требуется для решения согласования"
            )
        state = self.revision_state(revision_id)
        if state != STATE_READY_FOR_REVIEW:
            raise InvalidTransitionError(
                f"Решение согласующего возможно только из ready_for_review "
                f"(текущее: {state})"
            )
        if approval_policy() == POLICY_TWO_PERSON:
            requester = self._approval_requester(revision_id)
            if (
                subject.subject_id == getattr(revision, "created_by", None)
                or (requester is not None and subject.subject_id == requester)
            ):
                raise SelfApprovalForbiddenError(
                    "two_person policy: утверждающий не может быть "
                    "создателем ревизии или запросившим согласование"
                )
        snapshot_record = self._snapshot_record(revision.snapshot_id)
        if snapshot_record is None:
            raise ApprovalNotApplicableError(
                "Снимок ревизии недоступен в реестре -- согласование "
                "невозможно верифицировать (fail-closed)"
            )
        current_hash = str(getattr(snapshot_record, "payload_sha256", "") or "")
        if expected_snapshot_sha256 is not None and (
            expected_snapshot_sha256 != current_hash
        ):
            raise ApprovalHashMismatchError(
                "expected_snapshot_sha256 не совпадает с текущим снимком"
            )
        manifest = [
            {
                "rendition_id": rendition.rendition_id,
                "format": rendition.format,
                "content_sha256": rendition.content_sha256,
            }
            for rendition in self.delivery.registry.list_renditions(
                revision.snapshot_id
            )
            if rendition.state == "ready"
        ]
        self._mandatory_audit(
            "document_approved",
            "allowed" if decision == "approve" else "denied",
            subject=subject,
            revision=revision,
            snapshot_record=snapshot_record,
            details={"decision": decision, "reason": reason[:512]},
        )
        approval = ApprovalRecord(
            approval_id=new_approval_id(),
            revision_id=revision.revision_id,
            document_id=document.document_id,
            run_id=revision.run_id,
            decision=decision,
            actor_subject=getattr(subject, "subject_id", None) or "",
            actor_via=getattr(subject, "via", "") or "",
            tenant_id=getattr(subject, "tenant_id", None),
            policy=approval_policy(),
            policy_version=APPROVAL_POLICY_VERSION,
            reason=reason,
            snapshot_payload_sha256=current_hash,
            approval_manifest=manifest,
        )
        self.registry.append_approval(approval)
        self.registry.append_lifecycle(
            LifecycleRecord(
                record_id=new_lifecycle_id(),
                document_id=document.document_id,
                revision_id=revision.revision_id,
                run_id=revision.run_id,
                event=EVENT_APPROVED if decision == "approve" else EVENT_REJECTED,
                actor_subject=getattr(subject, "subject_id", None),
                reason=reason,
                details={"approval_id": approval.approval_id},
            )
        )
        new_state = self.revision_state(revision_id)
        return revision, approval, new_state

    def _approval_requester(self, revision_id: str) -> Optional[str]:
        for record in self.registry.list_lifecycle(revision_id):
            if record.event == EVENT_REQUEST:
                return record.actor_subject
        return None

    def _snapshot_record(self, snapshot_id: str) -> Any:
        from apps.api.report_snapshot import peek_snapshot_registry

        registry = peek_snapshot_registry()
        if registry is None:
            return None
        return registry.get_snapshot_record(snapshot_id)

    def _mandatory_audit(
        self,
        action: str,
        decision: str,
        *,
        subject: Any,
        revision: Any,
        snapshot_record: Any,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """§14.1/AC11: approve/publish/retract -- обязательный audit,
        fail-closed ДО действия (MandatoryAuditFailure -- операция не
        выполняется)."""
        from apps.api.security_audit import record_mandatory

        record_mandatory(
            action,
            decision,
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="document_revision",
            resource_id=str(revision.revision_id),
            resource_version=str(getattr(revision, "version_no", "") or ""),
            policy_basis=(
                "DOCLOG-6 approval bound hash; policy="
                f"{approval_policy()}:{APPROVAL_POLICY_VERSION}"
            ),
            run_id=str(revision.run_id),
            details={
                **(details or {}),
                "snapshot_payload_sha256": str(
                    getattr(snapshot_record, "payload_sha256", "") or ""
                ),
            },
        )

    # -- публикация (§11: publication manifest / bound hashes) --

    def publish(
        self, revision_id: str, subject: Any, *, session_id: str = ""
    ) -> tuple[Any, LifecycleRecord, str]:
        revision, document, snapshot = self._resolve_revision(
            revision_id, subject, session_id=session_id
        )
        rights = lifecycle_rights(subject)
        if not rights.can_publish:
            raise InsufficientScopeError(
                "documentation.publish требуется для публикации"
            )
        state = self.revision_state(revision_id)
        if state in (STATE_DRAFT, STATE_READY_FOR_REVIEW):
            raise PublishRequiresApprovalError(
                "Публикация требует согласования этой ревизии (§11)"
            )
        if state != STATE_APPROVED:
            raise InvalidTransitionError(
                f"Публикация возможна только из approved (текущее: {state})"
            )
        approval = self._latest_approval_record(revision_id)
        if approval is None:
            raise PublishRequiresApprovalError(
                "Согласование этой ревизии не найдено"
            )
        # AC07: bound-hash верификация ПЕРЕД публикацией.
        snapshot_record = self._snapshot_record(revision.snapshot_id)
        if snapshot_record is None:
            raise ApprovalNotApplicableError(
                "Снимок ревизии недоступен в реестре -- publish отклонён"
            )
        current_hash = str(getattr(snapshot_record, "payload_sha256", "") or "")
        if current_hash != approval.snapshot_payload_sha256:
            raise ApprovalNotApplicableError(
                "Хэш снимка изменился после согласования -- старое "
                "approval не переносится (AC07); создайте новую ревизию"
            )
        renditions_by_id = {
            rendition.rendition_id: rendition
            for rendition in self.delivery.registry.list_renditions(
                revision.snapshot_id
            )
        }
        for bound in approval.approval_manifest:
            rendition = renditions_by_id.get(str(bound.get("rendition_id")))
            if (
                rendition is None
                or str(rendition.content_sha256)
                != str(bound.get("content_sha256"))
            ):
                raise ApprovalNotApplicableError(
                    "Утверждённая визуальная форма изменилась/утрачена "
                    "(AC07); соберите формат заново и согласуйте ревизию"
                )
        # §11: публикация требует обязательных разделов и допустимой
        # полноты; policy v1 -- для итогового D11 gaps блокируют.
        sections = getattr(snapshot, "sections", []) or []
        if not sections:
            raise PublishBlockedGapsError(
                "Снимок без обязательных разделов -- публикация "
                "заблокирована (§11)"
            )
        kind_code = getattr(document, "kind_code", "")
        completeness_status = ""
        completeness = getattr(snapshot, "completeness", None)
        if isinstance(completeness, dict):
            completeness_status = str(completeness.get("status", ""))
        if kind_code == "D11" and completeness_status != "complete":
            raise PublishBlockedGapsError(
                "Итоговый отчёт D11 с незакрытыми gaps не публикуется "
                "(policy v1, §11); partial допустим для D01-D10"
            )
        # Supersede: предыдущая published ревизия того же документа --
        # append-only запись superseded (байты не переписываются).
        supersedes = self._published_revision_of_document(document.document_id)
        self._mandatory_audit(
            "document_published",
            "allowed",
            subject=subject,
            revision=revision,
            snapshot_record=snapshot_record,
            details={
                "approval_id": approval.approval_id,
                "supersedes_revision_id": supersedes.revision_id if supersedes else None,
            },
        )
        record = self.registry.append_lifecycle(
            LifecycleRecord(
                record_id=new_lifecycle_id(),
                document_id=document.document_id,
                revision_id=revision.revision_id,
                run_id=revision.run_id,
                event=EVENT_PUBLISHED,
                actor_subject=getattr(subject, "subject_id", None),
                reason="",
                details={
                    "approval_id": approval.approval_id,
                    "snapshot_payload_sha256": current_hash,
                    "supersedes_revision_id": (
                        supersedes.revision_id if supersedes else None
                    ),
                },
            )
        )
        if supersedes is not None:
            self.registry.append_lifecycle(
                LifecycleRecord(
                    record_id=new_lifecycle_id(),
                    document_id=document.document_id,
                    revision_id=supersedes.revision_id,
                    run_id=revision.run_id,
                    event=EVENT_SUPERSEDED,
                    actor_subject=getattr(subject, "subject_id", None),
                    reason="",
                    details={"superseded_by": revision.revision_id},
                )
            )
        # §16/AC04-дух: publish пинирует снимок независимо от
        # checkpoint keeper'а (best-effort -- как _pin_dependencies).
        self._pin_published_snapshot(revision, document, subject)
        return revision, record, self.revision_state(revision_id)

    def _published_revision_of_document(self, document_id: str) -> Optional[Any]:
        for revision in self.delivery.registry.list_revisions(document_id):
            if self.revision_state(revision.revision_id) == STATE_PUBLISHED:
                return revision
        return None

    def _pin_published_snapshot(
        self, revision: Any, document: Any, subject: Any
    ) -> None:
        try:
            from apps.api.artifact_store import get_artifact_registry

            get_artifact_registry().pin_ref(
                revision.run_id,
                "snapshot",
                revision.snapshot_id,
                reason=(
                    f"document:{document.document_id}:published:"
                    f"{revision.version_no}"
                ),
                created_by=getattr(subject, "subject_id", None),
            )
        except Exception as exc:  # pragma: no cover -- пин не роняет publish
            logger.warning(
                "Publish pin failed: run=%s revision=%s -- %s",
                revision.run_id, revision.revision_id, exc,
            )

    # -- отзыв (§11: append-only решение с причиной) --

    def retract(
        self,
        revision_id: str,
        subject: Any,
        *,
        session_id: str = "",
        reason: str = "",
    ) -> tuple[Any, str]:
        revision, _document, _snapshot = self._resolve_revision(
            revision_id, subject, session_id=session_id
        )
        rights = lifecycle_rights(subject)
        if not rights.can_publish:
            raise InsufficientScopeError(
                "documentation.publish требуется для отзыва"
            )
        state = self.revision_state(revision_id)
        if state != STATE_PUBLISHED:
            raise InvalidTransitionError(
                f"Отзыв возможен только из published (текущее: {state})"
            )
        snapshot_record = self._snapshot_record(revision.snapshot_id)
        self._mandatory_audit(
            "document_revoked",
            "allowed",
            subject=subject,
            revision=revision,
            snapshot_record=snapshot_record,
            details={"reason": (reason or "")[:512]},
        )
        self.registry.append_lifecycle(
            LifecycleRecord(
                record_id=new_lifecycle_id(),
                document_id=revision.document_id,
                revision_id=revision.revision_id,
                run_id=revision.run_id,
                event=EVENT_RETRACTED,
                actor_subject=getattr(subject, "subject_id", None),
                reason=reason,
                details={},
            )
        )
        return revision, self.revision_state(revision_id)

    def list_lifecycle(
        self, revision_id: str, subject: Any, *, session_id: str = ""
    ) -> list[LifecycleRecord]:
        self._resolve_revision(revision_id, subject, session_id=session_id)
        return self.registry.list_lifecycle(revision_id)

    # -- retention (§16.1/D8) --

    def set_retention(
        self,
        document_id: str,
        subject: Any,
        *,
        session_id: str = "",
        action: str,
        reason: str = "",
    ) -> RetentionRecord:
        # Порядок fail-closed (R09): резолв/права до валидации тела.
        document, _revisions = self._resolve_document(
            document_id, subject, session_id=session_id
        )
        if action not in ("hold", "release"):
            raise InvalidTransitionError("action обязан быть hold | release")
        rights = lifecycle_rights(subject)
        if not rights.can_retention:
            raise InsufficientScopeError(
                "policy.admin/admin требуется для смены retention"
            )
        hold = action == "hold"
        record = RetentionRecord(
            document_id=document.document_id,
            run_id=document.run_id,
            hold=hold,
            hold_reason=reason if hold else "",
            updated_by=getattr(subject, "subject_id", None),
        )
        record = self.registry.upsert_retention(record)
        from apps.api.security_audit import record_standard

        record_standard(
            "retention_policy_changed",
            "allowed",
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="document",
            resource_id=str(document.document_id),
            policy_basis=f"DOCLOG-6 retention; basis={rights.basis}",
            run_id=str(document.run_id),
            details={"action": action, "reason": (reason or "")[:512]},
        )
        return record

    def sweep_retention(
        self, run_id: str, subject: Any, *, session_id: str = ""
    ) -> dict[str, Any]:
        """§16.1: purge невостребованных draft renditions; hold
        приоритетен; published/approved/retracted/superseded не
        очищаются; научный слой и pinned-зависимости не трогаются."""
        self._resolve_run(run_id, subject, session_id=session_id, action="write")
        rights = lifecycle_rights(subject)
        if not rights.can_retention:
            raise InsufficientScopeError(
                "policy.admin/admin требуется для запуска retention sweep"
            )
        cutoff = datetime.now(timezone.utc) - timedelta_days(retention_draft_days())
        report: dict[str, Any] = {
            "scanned_documents": 0,
            "skipped_hold_documents": 0,
            "kept_published_documents": 0,
            "purged_renditions": 0,
            "draft_days": retention_draft_days(),
        }
        from apps.api.report_snapshot import DOCUMENT_KINDS
        from apps.api.document_jobs import MemoryDocumentRegistry

        registry = self.delivery.registry
        for kind_code in DOCUMENT_KINDS:
            document = registry.find_document_by_kind(run_id, kind_code)
            if document is None:
                continue
            report["scanned_documents"] += 1
            retention = self.registry.get_retention(document.document_id)
            if retention is not None and retention.hold:
                report["skipped_hold_documents"] += 1
                continue
            revisions = registry.list_revisions(document.document_id)
            states = {
                self.revision_state(revision.revision_id)
                for revision in revisions
            }
            if states & _PROTECTED_STATES:
                report["kept_published_documents"] += 1
                continue
            for revision in revisions:
                for rendition in registry.list_renditions(revision.snapshot_id):
                    if rendition.state != "ready":
                        continue
                    created = _parse_iso(rendition.created_at)
                    if created is None or created > cutoff:
                        continue
                    self._purge_rendition(registry, rendition)
                    report["purged_renditions"] += 1
        from apps.api.security_audit import record_standard

        record_standard(
            "cleanup_started",
            "allowed",
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="run",
            resource_id=str(run_id),
            policy_basis=f"DOCLOG-6 retention sweep; basis={rights.basis}",
            run_id=str(run_id),
            details={key: report[key] for key in sorted(report)},
        )
        return report

    def _purge_rendition(self, registry: Any, rendition: Any) -> None:
        """Purge = честный tombstone: байты удалены, запись/хэши
        сохранены, state="purged" (§16.1/§17 410)."""
        storage_key = str(rendition.storage_key or "")
        if storage_key:
            try:
                path = self.delivery.objects.path_for_key(storage_key)
                path.unlink(missing_ok=True)
            except Exception as exc:  # pragma: no cover -- unlink не роняет
                logger.warning(
                    "Retention purge: unlink failed key=%s -- %s",
                    storage_key, exc,
                )
        updated = replace_record(rendition, state=RENDITION_PURGED, content_bytes=None)
        registry.update_rendition(updated)

    # -- archive / restore drill (§16/AC18/D9) --

    def build_archive_bundle(
        self, run_id: str, subject: Any, *, session_id: str = ""
    ) -> dict[str, Any]:
        self._resolve_run(run_id, subject, session_id=session_id, action="write")
        rights = lifecycle_rights(subject)
        if not rights.can_retention:
            raise InsufficientScopeError(
                "policy.admin/admin требуется для создания архивного пакета"
            )
        base = _data_root()
        bundle_id = ARCHIVE_BUNDLE_PREFIX + uuid.uuid4().hex
        bundle_dir = base / "archive" / run_id / bundle_id
        objects_dir = bundle_dir / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)

        members: list[dict[str, Any]] = []
        entity_lines: list[dict[str, Any]] = []

        documents = []
        from apps.api.report_snapshot import DOCUMENT_KINDS

        registry = self.delivery.registry
        for kind_code in DOCUMENT_KINDS:
            document = registry.find_document_by_kind(run_id, kind_code)
            if document is not None:
                documents.append(document)
        for document in documents:
            entity_lines.append({"entity": "document", **document.to_dict()})
            for revision in registry.list_revisions(document.document_id):
                entity_lines.append({"entity": "revision", **revision.to_dict()})
                for rendition in registry.list_renditions(revision.snapshot_id):
                    entity_lines.append({"entity": "rendition", **rendition.to_dict()})
                for approval in self.registry.list_approvals(revision.revision_id):
                    entity_lines.append({"entity": "approval", **approval.to_dict()})
                for record in self.registry.list_lifecycle(revision.revision_id):
                    entity_lines.append({"entity": "lifecycle", **record.to_dict()})
            retention = self.registry.get_retention(document.document_id)
            if retention is not None:
                entity_lines.append({"entity": "retention", **retention.to_dict()})

        snapshot_registry = _snapshot_registry()
        copied_keys: set[str] = set()

        def _copy_object(storage_key: str) -> None:
            if not storage_key or storage_key in copied_keys:
                return
            copied_keys.add(storage_key)
            try:
                payload = self.delivery.objects.read_bytes(storage_key)
            except Exception as exc:  # pragma: no cover -- честно фиксируется
                logger.warning(
                    "Archive: объект %s недоступен -- %s", storage_key, exc
                )
                return
            target = objects_dir / storage_key.replace("/", "_")
            target.write_bytes(payload)

        if snapshot_registry is not None:
            for snapshot in snapshot_registry.list_records(run_id):
                entity_lines.append(
                    {
                        "entity": "snapshot",
                        "snapshot_id": snapshot.snapshot_id,
                        "research_run_id": snapshot.research_run_id,
                        "payload_sha256": snapshot.payload_sha256,
                        "storage_key": snapshot.storage_key,
                        "captured_at": snapshot.captured_at,
                        "kinds": list(snapshot.kinds),
                        "context_id": snapshot.context_id,
                        "data_revision": snapshot.data_revision,
                    }
                )
                _copy_object(str(snapshot.storage_key or ""))
        # Байты ready-renditions (после snapshot-копирования: renditions
        # собраны в entity_lines выше).
        for line in entity_lines:
            if line.get("entity") == "rendition" and line.get("state") == "ready":
                _copy_object(str(line.get("storage_key") or ""))
        from apps.api.artifact_store import get_artifact_registry

        for pin in get_artifact_registry().list_pins(run_id):
            entity_lines.append(
                {
                    "entity": "pin",
                    "ref_kind": pin.ref_kind,
                    "ref_id": pin.ref_id,
                    "reason": pin.reason,
                    "created_at": getattr(pin, "created_at", None),
                }
            )

        metadata_bytes = (
            "\n".join(
                canonical_json_line(line) for line in entity_lines
            ).encode("utf-8")
            + b"\n"
            if entity_lines
            else b""
        )
        (bundle_dir / "metadata.jsonl").write_bytes(metadata_bytes)
        members.append(_member(bundle_dir, "metadata.jsonl"))

        for path in sorted(objects_dir.iterdir()):
            members.append(_member(bundle_dir, f"objects/{path.name}"))

        manifest_payload = {
            "bundle_id": bundle_id,
            "run_id": run_id,
            "created_at": _now_iso(),
            "member_count": len(members),
            "members": members,
            # §13.3: manifest не содержит собственного hash (циклическое
            # определение запрещено).
        }
        manifest_bytes = canonical_json_bytes(manifest_payload)
        (bundle_dir / "manifest.json").write_bytes(manifest_bytes)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        from apps.api.security_audit import record_standard

        record_standard(
            "archive_bundle_created",
            "allowed",
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="run",
            resource_id=str(run_id),
            policy_basis=f"DOCLOG-6 archive; basis={rights.basis}",
            run_id=str(run_id),
            details={
                "bundle_id": bundle_id,
                "member_count": len(members),
                "manifest_sha256": manifest_sha256,
            },
        )
        return {
            "bundle_id": bundle_id,
            "run_id": run_id,
            "member_count": len(members),
            "manifest_sha256": manifest_sha256,
            "created_at": manifest_payload["created_at"],
        }

    def verify_archive_bundle(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        bundle_id: str = "",
    ) -> dict[str, Any]:
        self._resolve_run(run_id, subject, session_id=session_id, action="read")
        if not bundle_id or "/" in bundle_id or ".." in bundle_id or not bundle_id.startswith(ARCHIVE_BUNDLE_PREFIX):
            raise LifecycleAccessDenied("Архивный пакет недоступен")
        started = time.monotonic()
        bundle_dir = _data_root() / "archive" / run_id / bundle_id
        manifest_path = bundle_dir / "manifest.json"
        missing: list[str] = []
        mismatched: list[str] = []
        ref_errors: list[str] = []
        checked_refs = 0
        manifest: dict[str, Any] | None = None
        if manifest_path.exists():
            try:
                manifest = json_loads(manifest_path.read_bytes())
            except Exception:
                mismatched.append("manifest.json")
                manifest = None
        else:
            missing.append("manifest.json")
        entities: list[dict[str, Any]] = []
        if manifest is not None:
            for member in manifest.get("members", []):
                path = str(member.get("path", ""))
                target = bundle_dir / path
                if not target.exists():
                    missing.append(path)
                    continue
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if digest != str(member.get("sha256")):
                    mismatched.append(path)
                    continue
            metadata_path = bundle_dir / "metadata.jsonl"
            if metadata_path.exists():
                for line in metadata_path.read_bytes().splitlines():
                    if not line.strip():
                        continue
                    try:
                        entities.append(json_loads(line))
                    except Exception:
                        mismatched.append("metadata.jsonl:line")
        if manifest is None and not missing:
            missing.append("manifest.json")

        # Ссылочная целостность (AC18: refs/checksums/approval).
        by_entity: dict[str, list[dict[str, Any]]] = {}
        for entity in entities:
            by_entity.setdefault(str(entity.get("entity")), []).append(entity)
        document_ids = {
            str(item.get("document_id"))
            for item in by_entity.get("document", [])
        }
        revision_ids = {
            str(item.get("revision_id"))
            for item in by_entity.get("revision", [])
        }
        snapshot_hashes = {
            str(item.get("snapshot_id")): str(item.get("payload_sha256") or "")
            for item in by_entity.get("snapshot", [])
        }
        member_paths = {
            str(member.get("path"))
            for member in (manifest or {}).get("members", [])
        }
        for revision in by_entity.get("revision", []):
            checked_refs += 1
            if str(revision.get("document_id")) not in document_ids:
                ref_errors.append(
                    f"revision:{revision.get('revision_id')}:document_missing"
                )
        for rendition in by_entity.get("rendition", []):
            checked_refs += 1
            if str(rendition.get("revision_id")) not in revision_ids:
                ref_errors.append(
                    f"rendition:{rendition.get('rendition_id')}:revision_missing"
                )
            if str(rendition.get("state")) == "ready":
                key = str(rendition.get("storage_key") or "")
                object_path = f"objects/{key.replace('/', '_')}"
                if key and object_path not in member_paths:
                    missing.append(object_path)
        for approval in by_entity.get("approval", []):
            checked_refs += 1
            if str(approval.get("revision_id")) not in revision_ids:
                ref_errors.append(
                    f"approval:{approval.get('approval_id')}:revision_missing"
                )
            snapshot_id = None
            for revision in by_entity.get("revision", []):
                if str(revision.get("revision_id")) == str(approval.get("revision_id")):
                    snapshot_id = str(revision.get("snapshot_id"))
                    break
            if snapshot_id is not None:
                bound = str(approval.get("snapshot_payload_sha256") or "")
                actual = snapshot_hashes.get(snapshot_id, "")
                if bound and actual and bound != actual:
                    ref_errors.append(
                        f"approval:{approval.get('approval_id')}:hash_mismatch"
                    )
        for snapshot in by_entity.get("snapshot", []):
            checked_refs += 1
            key = str(snapshot.get("storage_key") or "")
            object_path = f"objects/{key.replace('/', '_')}"
            if key and object_path not in member_paths:
                missing.append(object_path)

        duration_ms = int((time.monotonic() - started) * 1000)
        ok = not missing and not mismatched and not ref_errors
        from apps.api.security_audit import record_standard

        record_standard(
            "restore_started",
            "allowed",
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="run",
            resource_id=str(run_id),
            policy_basis="DOCLOG-6 restore drill",
            run_id=str(run_id),
            details={"bundle_id": bundle_id},
        )
        record_standard(
            "integrity_verified" if ok else "integrity_failed",
            "allowed" if ok else "denied",
            actor_subject=getattr(subject, "subject_id", "") or "",
            actor_via=getattr(subject, "via", "") or "anonymous",
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="archive_bundle",
            resource_id=str(bundle_id),
            policy_basis="DOCLOG-6 restore drill (AC18)",
            run_id=str(run_id),
            details={
                "missing": len(missing),
                "mismatched": len(mismatched),
                "ref_errors": len(ref_errors),
            },
        )
        return {
            "bundle_id": bundle_id,
            "run_id": run_id,
            "ok": ok,
            "checked_refs": checked_refs,
            "missing": missing,
            "mismatched": mismatched,
            "ref_errors": ref_errors,
            "duration_ms": duration_ms,
        }

    # -- diff ревизий (§17; по замороженным данным) --

    def diff_revisions(
        self,
        revision_id: str,
        subject: Any,
        *,
        session_id: str = "",
        against_revision_id: str = "",
    ) -> dict[str, Any]:
        """§17 Diff ревизий по замороженным снимкам, без пересчётов.

        Направление (F-D6C1, DOCLOG-6-CERT-FIX): diff(rev,
        against=prev) = изменения ОТ against К rev --
        claims.added = появившиеся в rev, claims.removed =
        существовавшие в against; metadata/validity_changed
        from = значение against, to = значение rev."""
        revision, document, snapshot = self._resolve_revision(
            revision_id, subject, session_id=session_id
        )
        against, document_b, snapshot_b = self._resolve_revision(
            against_revision_id, subject, session_id=session_id
        )
        if document.document_id != document_b.document_id:
            raise DiffAcrossDocumentsError(
                "Diff применим только к ревизиям одного документа"
            )
        a = snapshot.to_dict() if snapshot is not None else {}
        b = snapshot_b.to_dict() if snapshot_b is not None else {}
        metadata_fields = (
            "context_id",
            "data_revision",
            "data_ref",
            "data_digest",
            "captured_at",
            "knowledge_version",
            "classification",
            "redaction_profile",
        )
        metadata_diff: dict[str, dict[str, Any]] = {}
        for field_name in metadata_fields:
            if a.get(field_name) != b.get(field_name):
                metadata_diff[field_name] = {
                    "from": b.get(field_name),
                    "to": a.get(field_name),
                }
        for cutoff_field in ("last_sequence", "event_count"):
            a_value = (a.get("source_cutoff") or {}).get(cutoff_field)
            b_value = (b.get("source_cutoff") or {}).get(cutoff_field)
            if a_value != b_value:
                metadata_diff[f"source_cutoff.{cutoff_field}"] = {
                    "from": b_value,
                    "to": a_value,
                }
        for completeness_field in ("completeness.status", "reproducibility.status"):
            section_name, field_name = completeness_field.split(".")
            a_value = (a.get(section_name) or {}).get(field_name)
            b_value = (b.get(section_name) or {}).get(field_name)
            if a_value != b_value:
                metadata_diff[completeness_field] = {
                    "from": b_value,
                    "to": a_value,
                }
        a_claims = _flatten_claims(a)
        b_claims = _flatten_claims(b)
        # Направление diff (F-D6C1, DOCLOG-6-CERT-FIX): diff(rev,
        # against=prev) читается как изменения ОТ against К rev.
        # added = утверждения, появившиеся в rev относительно against;
        # removed = существовавшие в against и отсутствующие в rev --
        # естественному чтению подписей панели doclog6-diff
        # («Добавлено утверждений» / «Убрано утверждений»).
        added = [claim for text, claim in a_claims.items() if text not in b_claims]
        removed = [claim for text, claim in b_claims.items() if text not in a_claims]
        validity_changed = [
            {
                "text": text,
                "from": b_claims[text]["validity"],
                "to": claim["validity"],
            }
            for text, claim in a_claims.items()
            if text in b_claims and claim["validity"] != b_claims[text]["validity"]
        ]
        return {
            "revision_id": revision.revision_id,
            "against_revision_id": against.revision_id,
            "metadata": metadata_diff,
            "claims": {
                "added": added,
                "removed": removed,
                "validity_changed": validity_changed,
            },
            "recalculated": False,
        }


# ── Вспомогательные ──────────────────────────────────────────────────


def _delivery_service() -> Any:
    from apps.api.document_jobs import DocumentDeliveryService

    return DocumentDeliveryService.create_default()


def _snapshot_registry() -> Any:
    from apps.api.report_snapshot import peek_snapshot_registry

    return peek_snapshot_registry()


def _data_root() -> Path:
    env_root = os.environ.get("CISSTAT_DATA_DIR", "")
    base = Path(env_root) if env_root else Path(__file__).resolve().parents[2] / "data"
    return base


def _member(bundle_dir: Path, relative: str) -> dict[str, Any]:
    data = (bundle_dir / relative).read_bytes()
    return {
        "path": relative,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def canonical_json_bytes(payload: Any) -> bytes:
    from apps.api.artifact_store import canonical_json_bytes as _fn

    return _fn(payload)


def canonical_json_line(payload: dict[str, Any]) -> str:
    from apps.api.artifact_store import canonical_json_bytes as _fn

    return _fn(payload).decode("utf-8")


def json_loads(data: bytes) -> Any:
    import json

    return json.loads(data.decode("utf-8"))


def timedelta_days(days: int) -> Any:
    from datetime import timedelta

    return timedelta(days=days)


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def replace_record(record: Any, **changes: Any) -> Any:
    from apps.api.document_jobs import replace_dataclass

    return replace_dataclass(record, **changes)


def _flatten_claims(snapshot_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
    flat: dict[str, dict[str, Any]] = {}
    for section in snapshot_dict.get("sections", []) or []:
        code = str(section.get("code", ""))
        for claim in section.get("claims", []) or []:
            text = f"{code}:{claim.get('text', '')}"
            flat[text] = {
                "code": code,
                "text": claim.get("text", ""),
                "validity": claim.get("validity"),
            }
    return flat
