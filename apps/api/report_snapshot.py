# apps/api/report_snapshot.py
"""
DOCLOG-2 (spec_documentation_logging.md §10, §8.1, §19, AC02/AC03/AC09):
ReportSnapshot и реестр снимков -- замороженный атомарный снимок фактов
исследования до cutoff + dependency manifest.

ПОСТАНОВКА (§19, строка DOCLOG-2): «ReportSnapshot/cutoff, claim refs,
adapters D01-D09, отсутствие пересчётов». Критерий завершения:
concurrent mutation не смешивает версии, current/stale/unknown и gaps
честны. Сборщик (сервис + адаптеры секций) -- в
apps/api/snapshot_builder.py; здесь -- контракт §10.1, cutoff (§10.2),
реестр метаданных (§8.1: тот же Postgres, миграция 0008) и фабрики.

КОНТРАКТ (§10.1): снимок содержит только факты выбранного контекста и
явно обозначенную историческую часть. Отсутствие ref -- unknown, не
current (R07). Применимость на момент cutoff -- часть frozen snapshot.
approval всегда null (согласование D11 -- DOCLOG-6).

SOURCE CUTOFF (§10.2): last_sequence -- реальная позиция durable ledger
(НЕ watermark размера корпуса существующего отчёта, который не
переинтерпретируется); event_count -- отдельное число; ordering_quality
canonical|legacy; для legacy корпуса без надёжного sequence хранится
закреплённый ordered event-id manifest, не синтетический «достоверный
seq».

KNOWLEDGE_VERSION (§10.1/AC03): sha256 артефакта промоушена реестра
знаний -- версия, относительно которой разрешаются methodology-ref
секций; тексты в P0 не встраиваются (rendition -- DOCLOG-5). Новая
версия реестра не меняет сохранённую ревизию: снимок immutable,
пересборка = новый снимок.

ИДЕМПОТЕНТНОСТЬ (§10.3/AC09): UNIQUE(run_id, idempotency_key); тот же
ключ с другим телом -- конфликт 409, не тихий дубль; повтор с тем же
телом возвращает прежний snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from abc import ABC
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apps.api.trace_events import canonical_event_order


REPORT_SNAPSHOT_SCHEMA_VERSION = "doclog.report_snapshot/1"
SNAPSHOT_ID_PATTERN = re.compile(r"^rs-[0-9a-f]{32}$")

# §10.1: template {"id": "research-report", "version": "1.0"}
TEMPLATE_ID = "research-report"
TEMPLATE_VERSION = "1.0"

# Пилотные значения по умолчанию (§22: default private/no sharing).
DEFAULT_LOCALE = "ru-RU"
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_CLASSIFICATION = "private"
DEFAULT_REDACTION_PROFILE = "owner-v1"

VALIDITY_CURRENT = "current"
VALIDITY_STALE = "stale"
VALIDITY_UNKNOWN = "unknown"

# §6 D01-D11: code -> (kind, title, methodology_stage). methodology_stage
# -- ссылка на этап реестра знаний (методология-ref, не текст); D01 --
# форма планирования, отдельного этапа реестра нет (честное None).
# DOCLOG-6: D10 «Рекомендации и ограничения» и D11 «Итоговый отчёт» --
# сквозные документы согласования/публикации (§19 строка DOCLOG-6);
# отдельного этапа реестра знаний у них нет -- честное None.
DOCUMENT_KINDS: dict[str, tuple[str, str, Optional[str]]] = {
    "D01": ("plan", "План исследования", None),
    "D02": ("source_passport", "Паспорт источника", "upload"),
    "D03": ("quality_protocol", "Протокол качества", "validation"),
    "D04": ("transformation_recipe", "Рецепт преобразований", "preprocessing"),
    "D05": ("eda_note", "Аналитическая записка", "eda"),
    "D06": ("experiment_protocol", "Протокол экспериментов", "modeling"),
    "D07": ("model_card", "Карточка модели", "modeling"),
    "D08": ("forecast_release", "Выпуск прогноза", "forecasting"),
    "D09": ("panel_appendix", "Приложение панели", "modeling"),
    "D10": ("recommendations_limits", "Рекомендации и ограничения", None),
    "D11": ("final_report", "Итоговый отчёт", None),
}

_KIND_ALIAS: dict[str, str] = {
    code: code for code in DOCUMENT_KINDS
}
for _code, (_kind, _title, _stage) in DOCUMENT_KINDS.items():
    _KIND_ALIAS[_kind] = _code

REF_KIND_ARTIFACT = "artifact"
REF_KIND_CHECKPOINT = "checkpoint"
REF_KIND_EVENT = "event"

SNAPSHOTS_BACKEND_ENV = "CISSTAT_SNAPSHOTS_BACKEND"

KNOWLEDGE_REGISTRY_PATH = Path(__file__).with_name("knowledge") / "registry_data.json"


# ── Ошибки контура ───────────────────────────────────────────────────


class SnapshotIntegrityError(RuntimeError):
    """Подмена/порча байтов сохранённого снимка (T8/T16): расхождение
    payload_sha256 при чтении -- битые байты не выдаются за валидные."""


class SnapshotIdempotencyConflictError(RuntimeError):
    """§10.3/AC09: тот же idempotency_key с другим телом запроса --
    конфликт без записи (409-семантика)."""


# ── Идентификаторы и вспомогательные ────────────────────────────────


def new_snapshot_id() -> str:
    return "rs-" + uuid.uuid4().hex


def is_valid_snapshot_id(value: Any) -> bool:
    return bool(isinstance(value, str) and SNAPSHOT_ID_PATTERN.match(value))


def resolve_kinds(requested: Any) -> list[str]:
    """Нормализация запрошенных видов: алиасы kind-имён -> коды D01-D11,
    порядок запроса сохраняется, дубликаты схлопываются. Пустой список
    и виды вне D01-D11 -- ValueError (D12 -- задача DOCLOG-8 §19)."""
    if not isinstance(requested, (list, tuple)) or not requested:
        raise ValueError("kinds: требуется непустой список видов D01-D11")
    resolved: list[str] = []
    for item in requested:
        code = _KIND_ALIAS.get(str(item))
        if code is None:
            raise ValueError(
                f"Неизвестный вид документа: {item!r}; "
                f"известные: {sorted(DOCUMENT_KINDS)}"
            )
        if code not in resolved:
            resolved.append(code)
    return resolved


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Knowledge version (AC03) ─────────────────────────────────────────


def knowledge_registry_version() -> Optional[str]:
    """sha256 артефакта промоушена реестра знаний -- «использованная
    версия» (§10.1): база разрешения methodology-ref секций. Файл
    отсутствует -- честное None (нет фабкации версии)."""
    path = KNOWLEDGE_REGISTRY_PATH
    try:
        content = Path(path).read_bytes()
    except OSError:
        return None
    return "sha256:" + hashlib.sha256(content).hexdigest()


# ── SourceCutoff (§10.2) ─────────────────────────────────────────────


@dataclass(frozen=True)
class SourceCutoff:
    """Позиция durable ledger на момент заморозки (§10.2)."""

    last_sequence: int = 0
    event_count: int = 0
    ordering_quality: str = "canonical"
    event_id_manifest: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_sequence": self.last_sequence,
            "event_count": self.event_count,
            "ordering_quality": self.ordering_quality,
            "event_id_manifest": (
                list(self.event_id_manifest)
                if self.event_id_manifest is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SourceCutoff":
        if not isinstance(data, dict):
            return cls()
        manifest = data.get("event_id_manifest")
        return cls(
            last_sequence=int(data.get("last_sequence") or 0),
            event_count=int(data.get("event_count") or 0),
            ordering_quality=(
                str(data.get("ordering_quality") or "canonical")
            ),
            event_id_manifest=(
                [str(item) for item in manifest]
                if isinstance(manifest, list)
                else None
            ),
        )

    def stability_key(self) -> tuple:
        """Ключ сравнения при двойном чтении (AC02): полное состояние
        cutoff, включая manifest (появление sequence-пробела -- тоже
        изменение корпуса)."""
        return (
            self.last_sequence,
            self.event_count,
            self.ordering_quality,
            tuple(self.event_id_manifest or ()),
        )


def _event_to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(event)


def build_source_cutoff(events: list[Any]) -> SourceCutoff:
    """Cutoff по корпусу событий (§10.2): у ВСЕХ событий sequence ->
    canonical (sequence авторитетен); иначе legacy -- закреплённый
    ordered event-id manifest по canonical_event_order (хронологический
    порядок; частичный sequence корпус не переупорядочивает) и честный
    максимум СРЕСТИ известных sequence (без синтетических значений)."""
    normalized = [_event_to_dict(event) for event in events]
    ordered = canonical_event_order(normalized)
    sequences = [
        int(event["sequence"])
        for event in ordered
        if isinstance(event.get("sequence"), int)
        and not isinstance(event.get("sequence"), bool)
    ]
    if len(sequences) == len(ordered):
        # пустой корпус тривиально упорядочен; у ВСЕХ событий sequence
        # -> canonical (sequence авторитетен)
        return SourceCutoff(
            last_sequence=(max(sequences) if sequences else 0),
            event_count=len(ordered),
            ordering_quality="canonical",
            event_id_manifest=None,
        )
    manifest = [str(event.get("event_id") or "") for event in ordered]
    return SourceCutoff(
        last_sequence=(max(sequences) if sequences else 0),
        event_count=len(ordered),
        ordering_quality="legacy",
        event_id_manifest=manifest,
    )


# ── Validity (R07: current/stale/unknown) ────────────────────────────


def artifact_validity(
    artifact_meta: Any,
    target_context: Optional[str],
    target_revision: Optional[int],
) -> str:
    """Применимость артефакта на момент cutoff (R07: «исторически
    выполненное не равно пригодному»; отсутствие context/evidence ref --
    unknown, не current).

    Матрица:
      - metadata отсутствует (context и revision оба None) -> unknown
        (даже для полностью legacy-зеркала: подтвердить применимость
        нечем);
      - context и revision совпадают с целевыми -> current;
      - известные, но другие -- stale.
    """
    if isinstance(artifact_meta, dict):
        ctx = artifact_meta.get("context_id")
        rev = artifact_meta.get("data_revision")
    else:
        ctx = getattr(artifact_meta, "context_id", None)
        rev = getattr(artifact_meta, "data_revision", None)
    if ctx is None and rev is None:
        return VALIDITY_UNKNOWN
    if ctx == target_context and rev == target_revision:
        return VALIDITY_CURRENT
    return VALIDITY_STALE


# ── Модель снимка (§10.1) ────────────────────────────────────────────


@dataclass
class ReportSnapshot:
    """Замороженный снимок фактов исследования (§10.1). Контрактные
    поля (to_dict) -- содержимое снимка; registry-поля
    (payload_sha256/size_bytes/storage_key/idempotency_key/
    request_fingerprint/kinds/created_by) -- метаданные реестра, в
    канонические байты НЕ входят (content-addressed самоссылка
    недопустима)."""

    snapshot_id: str
    research_run_id: str
    context_id: Optional[str] = None
    data_revision: Optional[int] = None
    data_ref: Optional[str] = None
    data_digest: Optional[dict[str, Any]] = None
    source_cutoff: dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=_now_iso)
    template: dict[str, Any] = field(
        default_factory=lambda: {"id": TEMPLATE_ID, "version": TEMPLATE_VERSION}
    )
    knowledge_version: Optional[str] = None
    locale: str = DEFAULT_LOCALE
    display_timezone: str = DEFAULT_TIMEZONE
    classification: str = DEFAULT_CLASSIFICATION
    redaction_profile: str = DEFAULT_REDACTION_PROFILE
    completeness: dict[str, Any] = field(
        default_factory=lambda: {"status": "partial", "missing_refs": []}
    )
    reproducibility: dict[str, Any] = field(
        default_factory=lambda: {"status": "limited", "reasons": []}
    )
    sections: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    approval: Optional[dict[str, Any]] = None
    schema_version: str = REPORT_SNAPSHOT_SCHEMA_VERSION
    # ── registry-метаданные (НЕ в канонических байтах) ──
    payload_sha256: str = ""
    size_bytes: int = 0
    storage_key: str = ""
    kinds: list[str] = field(default_factory=list)
    idempotency_key: str = ""
    request_fingerprint: str = ""
    created_by: Optional[str] = None

    _REGISTRY_FIELDS = (
        "payload_sha256", "size_bytes", "storage_key", "kinds",
        "idempotency_key", "request_fingerprint", "created_by",
    )

    def to_dict(self) -> dict[str, Any]:
        """Контрактные поля §10.1 (без registry-метаданных)."""
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "research_run_id": self.research_run_id,
            "context_id": self.context_id,
            "data_revision": self.data_revision,
            "data_ref": self.data_ref,
            "data_digest": (
                dict(self.data_digest) if self.data_digest is not None else None
            ),
            "source_cutoff": dict(self.source_cutoff),
            "captured_at": self.captured_at,
            "template": dict(self.template),
            "knowledge_version": self.knowledge_version,
            "locale": self.locale,
            "display_timezone": self.display_timezone,
            "classification": self.classification,
            "redaction_profile": self.redaction_profile,
            "completeness": {
                "status": self.completeness.get("status", "partial"),
                "missing_refs": list(self.completeness.get("missing_refs", [])),
            },
            "reproducibility": {
                "status": self.reproducibility.get("status", "limited"),
                "reasons": list(self.reproducibility.get("reasons", [])),
            },
            "sections": [
                {
                    "code": section.get("code"),
                    "kind": section.get("kind"),
                    "title": section.get("title"),
                    "methodology_stage": section.get("methodology_stage"),
                    "claims": [
                        {
                            "text": claim.get("text", ""),
                            "event_refs": list(claim.get("event_refs", [])),
                            "result_refs": list(claim.get("result_refs", [])),
                            "validity": claim.get(
                                "validity", VALIDITY_UNKNOWN
                            ),
                            "evidence_level": claim.get("evidence_level"),
                        }
                        for claim in section.get("claims", [])
                    ],
                }
                for section in self.sections
            ],
            "dependencies": list(self.dependencies),
            "approval": self.approval,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportSnapshot":
        known = {name for name in cls.__dataclass_fields__}
        known -= set(cls._REGISTRY_FIELDS)
        kwargs = {key: value for key, value in data.items() if key in known}
        return cls(**kwargs)

    def copy(self) -> "ReportSnapshot":
        """Копия (контракт store: возвращать копии, не живые объекты)."""
        return replace(
            self,
            data_digest=dict(self.data_digest) if self.data_digest else None,
            source_cutoff=dict(self.source_cutoff),
            template=dict(self.template),
            completeness={
                "status": self.completeness.get("status", "partial"),
                "missing_refs": list(self.completeness.get("missing_refs", [])),
            },
            reproducibility={
                "status": self.reproducibility.get("status", "limited"),
                "reasons": list(self.reproducibility.get("reasons", [])),
            },
            sections=[
                {
                    **section,
                    "claims": [dict(claim) for claim in section.get("claims", [])],
                }
                for section in self.sections
            ],
            dependencies=list(self.dependencies),
            kinds=list(self.kinds),
        )


# ── Реестр метаданных снимков (§8.1: тот же Postgres, новые таблицы) ──


class SnapshotRegistry(ABC):
    """Реестр ReportSnapshot (§9.1 Document/DocumentRevision -- полный
    жизненный цикл документов -- DOCLOG-4/6; здесь -- замороженные
    снимки как факты). Контракт store: возвращать копии, не живые
    объекты; bytes снимка -- в object store (content-addressed),
    метаданные -- здесь; чтение содержимого проверяет payload_sha256
    (T8/T16)."""

    def register_snapshot(
        self, snapshot: ReportSnapshot, dependencies: list[dict[str, Any]]
    ) -> tuple[ReportSnapshot, bool]:  # pragma: no cover - контракт
        raise NotImplementedError

    def get_snapshot_record(self, snapshot_id: str) -> Optional[ReportSnapshot]:  # pragma: no cover
        raise NotImplementedError

    def find_idempotent(self, run_id: str, idempotency_key: str) -> Optional[ReportSnapshot]:  # pragma: no cover
        raise NotImplementedError

    def list_records(self, run_id: str) -> list[ReportSnapshot]:  # pragma: no cover
        raise NotImplementedError

    def list_dependencies(self, snapshot_id: str) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        raise NotImplementedError


class MemorySnapshotRegistry(SnapshotRegistry):
    """Memory-реализация (паритет MemoryResearchRunStore/MemoryArtifactRegistry:
    замок, копии записей, без алиасинга живых объектов)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, ReportSnapshot] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._deps: dict[str, list[dict[str, Any]]] = {}

    def register_snapshot(
        self, snapshot: ReportSnapshot, dependencies: list[dict[str, Any]]
    ) -> tuple[ReportSnapshot, bool]:
        key = (snapshot.research_run_id, snapshot.idempotency_key)
        with self._lock:
            existing_id = self._by_key.get(key)
            if existing_id is not None:
                existing = self._snapshots[existing_id]
                if existing.request_fingerprint != snapshot.request_fingerprint:
                    raise SnapshotIdempotencyConflictError(
                        "Тот же idempotency_key с другим телом запроса -- "
                        "конфликт без записи (AC09)"
                    )
                return existing.copy(), False
            self._snapshots[snapshot.snapshot_id] = snapshot.copy()
            self._by_key[key] = snapshot.snapshot_id
            self._deps[snapshot.snapshot_id] = [
                dict(dep) for dep in dependencies
            ]
            return snapshot.copy(), True

    def get_snapshot_record(self, snapshot_id: str) -> Optional[ReportSnapshot]:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
        return snapshot.copy() if snapshot is not None else None

    def find_idempotent(self, run_id: str, idempotency_key: str) -> Optional[ReportSnapshot]:
        with self._lock:
            snapshot_id = self._by_key.get((run_id, idempotency_key))
            snapshot = (
                self._snapshots.get(snapshot_id) if snapshot_id else None
            )
        return snapshot.copy() if snapshot is not None else None

    def list_records(self, run_id: str) -> list[ReportSnapshot]:
        with self._lock:
            records = [
                snapshot.copy()
                for snapshot in self._snapshots.values()
                if snapshot.research_run_id == run_id
            ]
        records.sort(key=lambda item: (item.captured_at, item.snapshot_id))
        return records

    def list_dependencies(self, snapshot_id: str) -> list[dict[str, Any]]:
        with self._lock:
            deps = self._deps.get(snapshot_id, [])
        return [dict(dep) for dep in deps]

    def readiness_probe(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory"}


class PostgresSnapshotRegistry(SnapshotRegistry):
    """Postgres-реализация (ленивый psycopg -- паритет
    PostgresArtifactRegistry/PostgresResearchRunStore; миграция 0008
    применяется run_migrations на первом коннекте)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresSnapshotRegistry":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresSnapshotRegistry."
            )
        return PostgresSnapshotRegistry(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- паритет остальных durable-контуров

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    _SELECT_COLUMNS = (
        "snapshot_id, run_id, schema_version, kinds, template_id, "
        "template_version, locale, display_timezone, classification, "
        "redaction_profile, knowledge_version, cutoff_last_sequence, "
        "cutoff_event_count, ordering_quality, context_id, data_revision, "
        "data_ref, data_digest_algorithm, data_digest_value, payload_sha256, "
        "size_bytes, storage_key, completeness_status, "
        "completeness_missing_refs, reproducibility_status, "
        "reproducibility_reasons, dependencies, idempotency_key, "
        "request_fingerprint, created_by, created_at"
    )

    _PROBE_CONNECT_TIMEOUT_SECONDS = 3

    @staticmethod
    def _record_from_row(row: tuple) -> ReportSnapshot:
        cutoff = {
            "last_sequence": int(row[11] or 0),
            "event_count": int(row[12] or 0),
            "ordering_quality": str(row[13] or "canonical"),
            "event_id_manifest": None,
        }
        data_digest = None
        if row[17] and row[18]:
            data_digest = {"algorithm": str(row[17]), "value": str(row[18])}
        return ReportSnapshot(
            snapshot_id=str(row[0]),
            research_run_id=str(row[1]),
            schema_version=str(row[2]),
            kinds=list(row[3] or []),
            template={"id": str(row[4]), "version": str(row[5])},
            locale=str(row[6]),
            display_timezone=str(row[7]),
            classification=str(row[8]),
            redaction_profile=str(row[9]),
            knowledge_version=(str(row[10]) if row[10] else None),
            source_cutoff=cutoff,
            context_id=(str(row[14]) if row[14] else None),
            data_revision=(int(row[15]) if row[15] is not None else None),
            data_ref=(str(row[16]) if row[16] else None),
            data_digest=data_digest,
            payload_sha256=str(row[19] or ""),
            size_bytes=int(row[20] or 0),
            storage_key=str(row[21] or ""),
            completeness={
                "status": str(row[22] or "partial"),
                "missing_refs": list(row[23] or []),
            },
            reproducibility={
                "status": str(row[24] or "limited"),
                "reasons": list(row[25] or []),
            },
            dependencies=list(row[26] or []),
            idempotency_key=str(row[27] or ""),
            request_fingerprint=str(row[28] or ""),
            created_by=(str(row[29]) if row[29] else None),
            captured_at=(
                row[30].isoformat() if hasattr(row[30], "isoformat") else str(row[30])
            ),
        )

    def readiness_probe(self) -> dict[str, Any]:
        import psycopg

        from apps.api.storage_diagnostics import safe_error

        try:
            with psycopg.connect(
                self._dsn,
                autocommit=True,
                connect_timeout=self._PROBE_CONNECT_TIMEOUT_SECONDS,
            ) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute("SELECT to_regclass('public.report_snapshots')")
                if cur.fetchone()[0] is None:
                    return {
                        "ok": False,
                        "backend": "postgres",
                        "error": "миграция 0008 не применена",
                    }
            return {"ok": True, "backend": "postgres"}
        except Exception as exc:  # pragma: no cover -- средовой путь
            return {
                "ok": False,
                "backend": "postgres",
                "error": safe_error(exc),
            }

    def register_snapshot(
        self, snapshot: ReportSnapshot, dependencies: list[dict[str, Any]]
    ) -> tuple[ReportSnapshot, bool]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO report_snapshots
                    (snapshot_id, run_id, schema_version, kinds, template_id,
                     template_version, locale, display_timezone,
                     classification, redaction_profile, knowledge_version,
                     cutoff_last_sequence, cutoff_event_count,
                     ordering_quality, context_id, data_revision, data_ref,
                     data_digest_algorithm, data_digest_value,
                     payload_sha256, size_bytes, storage_key,
                     completeness_status, completeness_missing_refs,
                     reproducibility_status, reproducibility_reasons,
                     dependencies, idempotency_key, request_fingerprint,
                     created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, idempotency_key) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.research_run_id,
                    snapshot.schema_version,
                    json.dumps(snapshot.kinds, ensure_ascii=False),
                    snapshot.template.get("id", TEMPLATE_ID),
                    snapshot.template.get("version", TEMPLATE_VERSION),
                    snapshot.locale,
                    snapshot.display_timezone,
                    snapshot.classification,
                    snapshot.redaction_profile,
                    snapshot.knowledge_version,
                    (snapshot.source_cutoff or {}).get("last_sequence", 0),
                    (snapshot.source_cutoff or {}).get("event_count", 0),
                    (snapshot.source_cutoff or {}).get(
                        "ordering_quality", "canonical"
                    ),
                    snapshot.context_id,
                    snapshot.data_revision,
                    snapshot.data_ref,
                    (snapshot.data_digest or {}).get("algorithm"),
                    (snapshot.data_digest or {}).get("value"),
                    snapshot.payload_sha256,
                    snapshot.size_bytes,
                    snapshot.storage_key,
                    snapshot.completeness.get("status", "partial"),
                    json.dumps(
                        snapshot.completeness.get("missing_refs", []),
                        ensure_ascii=False,
                    ),
                    snapshot.reproducibility.get("status", "limited"),
                    json.dumps(
                        snapshot.reproducibility.get("reasons", []),
                        ensure_ascii=False,
                    ),
                    json.dumps(snapshot.dependencies, ensure_ascii=False),
                    snapshot.idempotency_key,
                    snapshot.request_fingerprint,
                    snapshot.created_by,
                    snapshot.captured_at,
                ),
            )
            inserted = cur.rowcount == 1
            if not inserted:
                cur.execute(
                    "SELECT " + self._SELECT_COLUMNS
                    + " FROM report_snapshots "
                    "WHERE run_id = %s AND idempotency_key = %s",
                    (snapshot.research_run_id, snapshot.idempotency_key),
                )
                row = cur.fetchone()
                conn.commit()
                if row is None:  # pragma: no cover -- конфликт-гонка
                    raise SnapshotIdempotencyConflictError(
                        "idempotency_key занят, запись не читается"
                    )
                existing = self._record_from_row(row)
                if existing.request_fingerprint != snapshot.request_fingerprint:
                    raise SnapshotIdempotencyConflictError(
                        "Тот же idempotency_key с другим телом запроса -- "
                        "конфликт без записи (AC09)"
                    )
                return existing, False
            cur.executemany(
                """
                INSERT INTO report_snapshot_dependencies
                    (dep_id, snapshot_id, run_id, ref_kind, ref_id, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id, ref_kind, ref_id) DO NOTHING
                """,
                [
                    (
                        "dep-" + uuid.uuid4().hex,
                        snapshot.snapshot_id,
                        snapshot.research_run_id,
                        str(dep.get("ref_kind", "")),
                        str(dep.get("ref_id", "")),
                        str(dep.get("reason", "")),
                    )
                    for dep in dependencies
                ],
            )
            conn.commit()
        return snapshot.copy(), True

    def get_snapshot_record(self, snapshot_id: str) -> Optional[ReportSnapshot]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT " + self._SELECT_COLUMNS
                + " FROM report_snapshots WHERE snapshot_id = %s",
                (snapshot_id,),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def find_idempotent(self, run_id: str, idempotency_key: str) -> Optional[ReportSnapshot]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT " + self._SELECT_COLUMNS
                + " FROM report_snapshots "
                "WHERE run_id = %s AND idempotency_key = %s",
                (run_id, idempotency_key),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def list_records(self, run_id: str) -> list[ReportSnapshot]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT " + self._SELECT_COLUMNS
                + " FROM report_snapshots WHERE run_id = %s "
                "ORDER BY created_at, snapshot_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def list_dependencies(self, snapshot_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ref_kind, ref_id, reason FROM "
                "report_snapshot_dependencies WHERE snapshot_id = %s "
                "ORDER BY ref_kind, ref_id",
                (snapshot_id,),
            )
            rows = cur.fetchall()
        return [
            {"ref_kind": str(row[0]), "ref_id": str(row[1]), "reason": str(row[2])}
            for row in rows
        ]


# ── Фабрики (паритет get_artifact_registry) ──────────────────────────

_registry: Optional[SnapshotRegistry] = None
_logger = __import__("logging").getLogger(__name__)


def get_snapshot_registry() -> SnapshotRegistry:
    """Выбор backend (симметрично get_artifact_registry):
    CISSTAT_SNAPSHOTS_BACKEND=memory -> Memory; =postgres или DATABASE_URL
    -> Postgres; иначе Memory (auto). Required-режим -- fail-closed
    (тихий Memory fallback запрещён, P21/F14)."""
    global _registry
    if _registry is not None:
        return _registry

    from apps.api.storage_diagnostics import (
        COMPONENT_SNAPSHOTS,
        get_storage_mode,
        record_backend_fallback,
        record_backend_selected,
        safe_error,
    )

    mode = get_storage_mode()
    backend_explicit = os.environ.get(SNAPSHOTS_BACKEND_ENV, "").lower()
    database_url = os.environ.get("DATABASE_URL", "")

    if backend_explicit == "memory":
        _registry = MemorySnapshotRegistry()
        record_backend_selected(COMPONENT_SNAPSHOTS, "memory", "memory")
    elif backend_explicit == "postgres" or database_url:
        record_backend_selected(COMPONENT_SNAPSHOTS, "postgres", "initializing")
        try:
            candidate = PostgresSnapshotRegistry.from_env()
            if mode == "required":
                probe = candidate.readiness_probe()
                if not probe.get("ok"):
                    reason = probe.get("error") or "readiness probe failed"
                    raise RuntimeError(
                        "SnapshotRegistry: Postgres backend required, "
                        f"но недоступен (fail-closed, P21/F14): {reason}"
                    )
            _registry = candidate
            record_backend_selected(COMPONENT_SNAPSHOTS, "postgres", "postgres")
            _logger.info("SnapshotRegistry: Postgres backend selected")
        except Exception as e:
            reason = safe_error(e)
            if mode == "required":
                record_backend_selected(
                    COMPONENT_SNAPSHOTS, "postgres", "unavailable",
                    reason=reason, degraded=True,
                )
                raise RuntimeError(
                    "SnapshotRegistry: Postgres backend required, "
                    f"но инициализация не удалась (fail-closed, P21/F14): "
                    f"{reason}"
                ) from e
            _logger.error(
                "SnapshotRegistry: Postgres init failed (%s), ЯВНАЯ "
                "деградация в Memory (advisory; состояние в /health/ops)",
                reason,
            )
            record_backend_fallback(
                COMPONENT_SNAPSHOTS, "postgres", reason, effective="memory"
            )
            _registry = MemorySnapshotRegistry()
    else:
        _registry = MemorySnapshotRegistry()
        record_backend_selected(COMPONENT_SNAPSHOTS, "auto", "memory")

    return _registry


def peek_snapshot_registry() -> Optional[SnapshotRegistry]:
    """Чтение singleton БЕЗ инициализации (/health/ops не провоцирует
    создание; паритет peek_artifact_registry)."""
    return _registry


def reset_snapshot_registry_for_testing() -> None:
    global _registry
    _registry = None
