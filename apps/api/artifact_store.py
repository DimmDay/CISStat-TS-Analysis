# apps/api/artifact_store.py
"""
DOCLOG-1 (spec_documentation_logging.md §9.1, §9.3, §10.2, §16, §19):
устойчивые артефакты -- Metadata/ObjectStore/schema/digests/staging/pins.

ПОСТАНОВКА (§19, строка DOCLOG-1): «Metadata/ObjectStore/schema/digests/
staging/pins; адаптеры паспортов, OOF, cards, forecasts». Критерий
завершения: результаты доступны после TTL-сессии, pin выдерживает
checkpoint-pruning, panel types сохраняются. Адаптеры -- в
apps/api/artifact_promotion.py; здесь -- инфраструктура.

ПРОБЛЕМА (факты спеки): сессия и её буфер не могут быть единственным
архивом исследования (F01: Redis TTL 30 дней, трасса слоя 1 -- 1000
событий); keeper «последних пяти» чекпоинтов может удалить снимок, на
который ссылается документ (F10/H07); прогноз связан с cookie-сессией
(F04/H02).

DIGEST-СХЕМЫ (§9.3 -- ТРИ типа, НЕ взаимозаменяемы):
  - payload_sha256 (artifact_content_sha256) -- SHA-256 канонических
    байт артефакта; проверяется при каждом чтении (T8: подмена/порча
    не выдаются за валидные байты);
  - data_digest {"algorithm": "cisstat-data-v1", "value": ...} --
    версионированная семантика нормализации ДАННЫХ (kind=data_frame);
    канонизация зафиксирована записью algorithm/version;
  - source_bytes_sha256 -- точные байты исходного файла; переносится
    ССЫЛКОЙ (существующий dataset fingerprint), не пересчитывается.

CANON-СЕРИАЛИЗАЦИЯ: json.dumps(..., ensure_ascii=False, sort_keys=True,
separators=(",",":"), allow_nan=False). NaN/Infinity НЕ маскируются:
SerializationError -- отказ вместо молчаливой правки (AC12-дух: не
ноль и не pass).

OBJECT STORE (§10.2 п.6, AC08): content-addressed локальный адаптер.
  {root}/artifacts/objects/{sha256[:2]}/{sha256}  -- commit
  {root}/artifacts/staging/{staging_id}           -- stage до коммита
Протокол: stage_bytes -> commit_staged (ПЕРЕЧИТЫВАЕТ staging, сверяет
sha256+size -- расхождение fail-closed, staged удаляется; os.replace
в objects) -> регистрация метаданных. Crash-матрица: до коммита --
осиротевший staging (sweep с grace period); объект до реестра --
безвредный content-object (mark-and-sweep GC -- DOCLOG-6); метаданные
появляются ТОЛЬКО после валидного объекта. Чтение всегда проверяет
sha256: ArtifactIntegrityError вместо тихих битых байтов. Storage key
производит ТОЛЬКО сервер из хэша -- traversal (T9) невозможен по
построению.

РЕЕСТР (§8.1: «существующий Postgres для ledger и новых metadata
tables»): ArtifactRegistry ABC + Memory + Postgres (ленивый psycopg,
run_migrations на первом коннекте -- тот же паттерн, что runs).
Идемпотентность промоушена: UNIQUE(run_id, producer_key) (AC09);
тот же ключ с другим контентом -- ArtifactConflictError без записи.
FK run_id CASCADE -- паритет ledger (артефакты живут вместе с
запуском; publish-политика DOCLOG-6).

PINS (§16): pin защищает зависимости независимо от keeper «последних
пяти» checkpoint (AC04/T11); metadata хранит ПРИЧИНУ ссылки
(reason=artifact_id у авто-пинов); UNIQUE(run_id, ref_kind, ref_id) --
идемпотентны. ref_kind=checkpoint защищает файл снимка;
unpin -- отдельное действие, последующий prune удаляет незащищённое.

THREAT MODEL (продолжение реестра DOCLOG-0; полный -- docs/
doclog1_durable_artifacts.md): T7 знание artifact_id не право
(авторизация в artifact_promotion поверх этой инфраструктуры);
T8 подмена байтов -- проверка sha256 при чтении; T9 traversal --
серверные ключи из хэша; T10 секреты -- научные полезные нагрузки
только, source-ссылками; T11 prune -- pin-интеграция в progress.py;
T12 канонизация -- allow_nan=False + algorithm/version.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

ARTIFACT_SCHEMA_VERSION = "doclog.artifact/1"
DATA_DIGEST_ALGORITHM = "cisstat-data-v1"

# DOCLOG-E2E-RECHECK-1-FIX (C03, producer integration): каталог
# расширен артефактами научного протокола, которые продюсеры
# (capture/check/apply) продвигают в durable-слой в момент фиксации
# результата:
#   * validation_result -- полный результат GET /dataset/validate
#     (правила/пороги/знаменатели, D03-основа);
#   * correction_recipe -- рецепт фактически применённой коррекции
#     (стратегия/метод/параметры/масштаб изменений, D04-основа).
# data_frame (версия данных) существовал ранее (checkpoint-путь);
# промоушен версии данных при коррекциях использует тот же kind.
ARTIFACT_KINDS: tuple[str, ...] = (
    "passport",
    "oof_backtest",
    "model_card",
    "forecast",
    "data_frame",
    "validation_result",
    "correction_recipe",
)

ARTIFACT_ID_PATTERN = re.compile(r"^art-[0-9a-f]{32}$")

REF_KIND_CHECKPOINT = "checkpoint"
REF_KIND_ARTIFACT = "artifact"

OBJECTS_DIR = "objects"
STAGING_DIR = "staging"


# ── Digest-схемы (§9.3) ──────────────────────────────────────────────


class SerializationError(ValueError):
    """Каноническая сериализация невозможна (NaN/Infinity/небезопасный
    тип). Отказ вместо молчаливой правки полезной нагрузки."""


def canonical_json_bytes(payload: Any) -> bytes:
    """Канонические байты JSON-полезной нагрузки: UTF-8, сортировка
    ключей, компактные разделители, БЕЗ NaN/Infinity (отказ, не
    маскировка -- T12/AC12-дух)."""
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SerializationError(
            f"Каноническая сериализация невозможна (честный отказ, "
            f"без маскировки NaN/Infinity): {type(exc).__name__}"
        ) from exc
    return text.encode("utf-8")


def artifact_content_sha256(content: bytes) -> str:
    """artifact_content_sha256: хэш ТОЧНЫХ байт сохранённого артефакта."""
    return hashlib.sha256(content).hexdigest()


def data_digest(content: bytes) -> dict[str, Any]:
    """data_digest: версионированная семантика нормализации данных.
    algorithm/version обязательны (§9.3: «запись algorithm/version
    обязательна»); НЕ взаимозаменяем с artifact_content_sha256 --
    совпадение значения при CSV-каноне не отменяет разных смыслов."""
    return {
        "algorithm": DATA_DIGEST_ALGORITHM,
        "value": hashlib.sha256(content).hexdigest(),
    }


def is_valid_source_ref(value: Any) -> bool:
    """source_bytes_sha256 -- непустая hex-ссылка на существующий
    fingerprint файла; вычисление НЕ здесь (адаптер переносит)."""
    return bool(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value or "")
    )


def new_artifact_id() -> str:
    return "art-" + uuid.uuid4().hex


def is_valid_artifact_id(value: Any) -> bool:
    return bool(isinstance(value, str) and ARTIFACT_ID_PATTERN.match(value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Модель метаданных (§9.1 ResultArtifact) ──────────────────────────


@dataclass
class ResultArtifact:
    """Устойчивый результат: байты в object store, метаданные в реестре.

    context_id/data_revision -- момент создания (честное отсутствие
    None); input_kind/panel -- панельная семантика (AC13: per-entity
    структура и pooled weighting/scale переносятся КАК ЕСТЬ);
    dependencies -- refs, защищаемые pins; created_by -- псевдоним
    субъекта DOCLOG-0, НЕ ключ/cookie (T4)."""

    artifact_id: str
    run_id: str
    kind: str
    producer_key: str
    media_type: str = "application/json"
    size_bytes: int = 0
    payload_sha256: str = ""
    data_digest: Optional[dict[str, Any]] = None
    source_bytes_sha256: Optional[str] = None
    storage_key: str = ""
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    context_id: Optional[str] = None
    data_revision: Optional[int] = None
    input_kind: Optional[str] = None
    panel: Optional[dict[str, Any]] = None
    dependencies: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "producer_key": self.producer_key,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "payload_sha256": self.payload_sha256,
            "data_digest": self.data_digest,
            "source_bytes_sha256": self.source_bytes_sha256,
            "storage_key": self.storage_key,
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "data_revision": self.data_revision,
            "input_kind": self.input_kind,
            "panel": self.panel,
            "dependencies": list(self.dependencies),
            "refs": dict(self.refs),
            "created_by": self.created_by,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResultArtifact":
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(
            **{key: value for key, value in data.items() if key in known}
        )

    def copy(self) -> "ResultArtifact":
        """Копия записи (R1 контракта store: реализации возвращают
        копии, не живые объекты)."""
        return replace(
            self,
            dependencies=list(self.dependencies),
            refs=dict(self.refs),
            data_digest=dict(self.data_digest) if self.data_digest else None,
            panel=dict(self.panel) if self.panel else None,
        )


@dataclass
class ArtifactPin:
    """Причина защиты зависимости (§16: «metadata graph хранит причины
    ссылок»). UNIQUE(run_id, ref_kind, ref_id) -- идемпотентен."""

    pin_id: str
    run_id: str
    ref_kind: str
    ref_id: str
    reason: str = ""
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "run_id": self.run_id,
            "ref_kind": self.ref_kind,
            "ref_id": self.ref_id,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


# ── Исключения контура ───────────────────────────────────────────────


class StagingVerificationError(RuntimeError):
    """commit_staged: байты staging расходятся с зафиксированными
    sha256/size (порча/гонка) -- fail-closed, метаданные не пишутся."""


class ArtifactIntegrityError(RuntimeError):
    """Чтение: байты объекта расходятся с content-addressed ключом
    (подмена/порча) -- битые байты НЕ выдаются за валидные (T8)."""


class ArtifactConflictError(RuntimeError):
    """Тот же producer_key с ДРУГИМ контентом (AC09: конфликт без
    записи; повтор с тем же контентом возвращает прежний артефакт)."""


# ── Object store (§10.2 п.6) ─────────────────────────────────────────


@dataclass
class StagedObject:
    staging_id: str
    path: Path
    sha256: str
    size_bytes: int
    media_type: str


class ArtifactObjectStore:
    """Content-addressed локальный адаптер (dev/standalone; §8.1:
    «абстракция ArtifactStore с локальным адаптером для dev и устойчивым
    private object storage для production» -- распределённый backend
    реализует тот же интерфейс)."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @staticmethod
    def default_root() -> Path:
        """{CISSTAT_DATA_DIR | <repo>/data}/artifacts -- паритет
        DatasetFileStore.default_root()."""
        env_root = os.environ.get("CISSTAT_DATA_DIR", "")
        base = Path(env_root) if env_root else Path(__file__).resolve().parents[2] / "data"
        return base / "artifacts"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def _objects_dir(self) -> Path:
        return self._root / OBJECTS_DIR

    @property
    def _staging_dir(self) -> Path:
        return self._root / STAGING_DIR

    def stage_bytes(self, payload: bytes, media_type: str) -> StagedObject:
        """1. staging: запись байтов, фиксация sha256/size. Имя файла --
        серверный uuid (T9: имён клиента в раскладке нет)."""
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("Payload обязан быть bytes")
        if not media_type:
            raise ValueError("media_type обязателен")
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        staging_id = uuid.uuid4().hex
        path = self._staging_dir / staging_id
        path.write_bytes(bytes(payload))
        return StagedObject(
            staging_id=staging_id,
            path=path,
            sha256=hashlib.sha256(bytes(payload)).hexdigest(),
            size_bytes=len(payload),
            media_type=media_type,
        )

    def commit_staged(self, staged: StagedObject) -> str:
        """2. verify + commit: ПЕРЕЧИТЫВАЕТ staging, сверяет sha256/size
        (расхождение -- fail-closed: staged удаляется, объект не
        появляется); os.replace -- атомарная постановка в objects.
        Возвращает серверный storage_key из хэша."""
        data = staged.path.read_bytes()
        if (
            hashlib.sha256(data).hexdigest() != staged.sha256
            or len(data) != staged.size_bytes
        ):
            staged.path.unlink(missing_ok=True)
            raise StagingVerificationError(
                "Staging расходится с зафиксированными sha256/size -- "
                "commit отменён (fail-closed, AC08)"
            )
        key = f"{staged.sha256[:2]}/{staged.sha256}"
        object_path = self._objects_dir / key
        if not object_path.exists():
            object_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = object_path.with_name(
                f".tmp-{staged.staging_id}"
            )
            tmp_path.write_bytes(data)
            os.replace(tmp_path, object_path)
        staged.path.unlink(missing_ok=True)
        return key

    def path_for_key(self, key: str) -> Path:
        return self._objects_dir / key

    def read_bytes(self, key: str) -> bytes:
        """3. read: проверка целостности по content-addressed ключу --
        расхождение хэша означает порчу/подмену (T8), байты не выдаются."""
        path = self.path_for_key(key)
        data = path.read_bytes()
        expected = key.rsplit("/", 1)[-1]
        if hashlib.sha256(data).hexdigest() != expected:
            raise ArtifactIntegrityError(
                "Байты объекта расходятся с content-key -- чтение "
                "отклонено (T8, целостность)"
            )
        return data

    def sweep_orphan_staging(self, grace_seconds: float = 86400) -> list[str]:
        """GC staging (§10.2: «GC удаляет orphan staging только после
        grace period»): удаляет staged-файлы старше grace (осиротевшие
        при crash до commit). Commit-объекты не трогаются."""
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        removed: list[str] = []
        for path in self._staging_dir.iterdir():
            if not path.is_file():
                continue
            try:
                age = now - path.stat().st_mtime
            except OSError:  # pragma: no cover -- гонка sweep
                continue
            if age >= grace_seconds:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        if removed:
            logger.info(
                "Artifacts: sweep удалил %d осиротевших staging-файлов", len(removed)
            )
        return removed


# ── Реестр метаданных ────────────────────────────────────────────────


class ArtifactRegistry:
    """Контракт реестра (паттерн ResearchRunStore: копии записей R1,
    идемпотентность AC09)."""

    def register_artifact(
        self, artifact: ResultArtifact
    ) -> tuple[ResultArtifact, bool]:  # pragma: no cover - контракт
        """Регистрация; (existing, False) при повторе того же контента,
        ArtifactConflictError при другом контенте того же producer_key."""
        raise NotImplementedError

    def get_artifact(self, artifact_id: str) -> Optional[ResultArtifact]:  # pragma: no cover
        raise NotImplementedError

    def list_artifacts(
        self, run_id: str, kind: Optional[str] = None
    ) -> list[ResultArtifact]:  # pragma: no cover
        raise NotImplementedError

    def pin_ref(
        self,
        run_id: str,
        ref_kind: str,
        ref_id: str,
        *,
        reason: str = "",
        created_by: Optional[str] = None,
    ) -> ArtifactPin:  # pragma: no cover
        raise NotImplementedError

    def unpin_ref(self, run_id: str, ref_kind: str, ref_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def list_pins(
        self, run_id: str, ref_kind: Optional[str] = None
    ) -> list[ArtifactPin]:  # pragma: no cover
        raise NotImplementedError

    def pinned_checkpoint_ids(self, run_id: str) -> set[str]:
        """Защищённые checkpoint-id (ref_kind=checkpoint) -- basis
        keep-списка prune (AC04/T11)."""
        return {
            pin.ref_id
            for pin in self.list_pins(run_id, ref_kind=REF_KIND_CHECKPOINT)
        }


class MemoryArtifactRegistry(ArtifactRegistry):
    """In-process реестр (dev/тесты; паритет MemoryResearchRunStore:
    замок, копии записей)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._artifacts: dict[str, ResultArtifact] = {}
        # ключ (run_id, ref_kind, ref_id) -> pin (UNIQUE-семантика)
        self._pins: dict[tuple[str, str, str], ArtifactPin] = {}

    def register_artifact(
        self, artifact: ResultArtifact
    ) -> tuple[ResultArtifact, bool]:
        if not is_valid_artifact_id(artifact.artifact_id):
            raise ValueError(
                f"Некорректный artifact_id: {artifact.artifact_id!r}"
            )
        if artifact.kind not in ARTIFACT_KINDS:
            raise ValueError(f"Неизвестный kind артефакта: {artifact.kind!r}")
        with self._lock:
            existing = next(
                (
                    item
                    for item in self._artifacts.values()
                    if item.run_id == artifact.run_id
                    and item.producer_key == artifact.producer_key
                ),
                None,
            )
            if existing is not None:
                if existing.payload_sha256 != artifact.payload_sha256:
                    raise ArtifactConflictError(
                        "Тот же producer_key с другим контентом -- "
                        "конфликт без записи (AC09)"
                    )
                return existing.copy(), False
            self._artifacts[artifact.artifact_id] = artifact.copy()
            return artifact.copy(), True

    def get_artifact(self, artifact_id: str) -> Optional[ResultArtifact]:
        with self._lock:
            artifact = self._artifacts.get(artifact_id)
            return artifact.copy() if artifact else None

    def list_artifacts(
        self, run_id: str, kind: Optional[str] = None
    ) -> list[ResultArtifact]:
        with self._lock:
            items = [
                item
                for item in self._artifacts.values()
                if item.run_id == run_id and (kind is None or item.kind == kind)
            ]
            return [item.copy() for item in items]

    def pin_ref(
        self,
        run_id: str,
        ref_kind: str,
        ref_id: str,
        *,
        reason: str = "",
        created_by: Optional[str] = None,
    ) -> ArtifactPin:
        key = (run_id, ref_kind, ref_id)
        with self._lock:
            existing = self._pins.get(key)
            if existing is not None:
                return existing
            pin = ArtifactPin(
                pin_id=uuid.uuid4().hex,
                run_id=run_id,
                ref_kind=ref_kind,
                ref_id=ref_id,
                reason=reason,
                created_by=created_by,
            )
            self._pins[key] = pin
            return pin

    def unpin_ref(self, run_id: str, ref_kind: str, ref_id: str) -> bool:
        with self._lock:
            return self._pins.pop((run_id, ref_kind, ref_id), None) is not None

    def list_pins(
        self, run_id: str, ref_kind: Optional[str] = None
    ) -> list[ArtifactPin]:
        with self._lock:
            return [
                pin
                for (pin_run, pin_kind, _), pin in self._pins.items()
                if pin_run == run_id and (ref_kind is None or pin_kind == ref_kind)
            ]


class PostgresArtifactRegistry(ArtifactRegistry):
    """Postgres-реализация (§8.1: тот же Postgres, новые metadata
    tables; ленивый psycopg -- тот же паттерн, что PostgresResearchRunStore;
    миграция 0007 применяется run_migrations на первом коннекте)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresArtifactRegistry":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresArtifactRegistry."
            )
        return PostgresArtifactRegistry(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- паритет PostgresResearchRunStore

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    @staticmethod
    def _artifact_from_row(row: tuple) -> ResultArtifact:
        data_digest = None
        if row[8] and row[9]:
            data_digest = {"algorithm": str(row[8]), "value": str(row[9])}
        return ResultArtifact(
            artifact_id=str(row[0]),
            run_id=str(row[1]),
            kind=str(row[2]),
            schema_version=str(row[3]),
            producer_key=str(row[4]),
            media_type=str(row[5]),
            size_bytes=int(row[6]),
            payload_sha256=str(row[7]),
            data_digest=data_digest,
            source_bytes_sha256=(str(row[10]) if row[10] else None),
            storage_key=str(row[11]),
            context_id=(str(row[12]) if row[12] else None),
            data_revision=(int(row[13]) if row[13] is not None else None),
            input_kind=(str(row[14]) if row[14] else None),
            panel=row[15],
            dependencies=list(row[16] or []),
            refs=dict(row[17] or {}),
            created_by=(str(row[18]) if row[18] else None),
            created_at=(
                row[19].isoformat() if hasattr(row[19], "isoformat") else str(row[19])
            ),
        )

    _SELECT_COLUMNS = (
        "artifact_id, run_id, kind, schema_version, producer_key, media_type, "
        "size_bytes, payload_sha256, data_digest_algorithm, data_digest_value, "
        "source_bytes_sha256, storage_key, context_id, data_revision, "
        "input_kind, panel, dependencies, refs, created_by, created_at"
    )

    _PROBE_CONNECT_TIMEOUT_SECONDS = 3

    def readiness_probe(self) -> dict[str, Any]:
        """Дешёвая проба готовности (паритет PostgresResearchRunStore):
        SELECT 1 + наличие таблицы артефактов (недокатанная миграция --
        честный ok=False). Без side-эффектов; причина -- safe_error."""
        import psycopg

        from apps.api.storage_diagnostics import safe_error

        try:
            with psycopg.connect(
                self._dsn,
                autocommit=True,
                connect_timeout=self._PROBE_CONNECT_TIMEOUT_SECONDS,
            ) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute(
                    "SELECT to_regclass('public.research_artifacts')"
                )
                if cur.fetchone()[0] is None:
                    return {
                        "ok": False,
                        "backend": "postgres",
                        "error": "миграция 0007 не применена",
                    }
            return {"ok": True, "backend": "postgres"}
        except Exception as exc:  # pragma: no cover -- средовой путь
            return {
                "ok": False,
                "backend": "postgres",
                "error": safe_error(exc),
            }

    def register_artifact(
        self, artifact: ResultArtifact
    ) -> tuple[ResultArtifact, bool]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_artifacts
                    (artifact_id, run_id, kind, schema_version, producer_key,
                     media_type, size_bytes, payload_sha256,
                     data_digest_algorithm, data_digest_value,
                     source_bytes_sha256, storage_key, context_id,
                     data_revision, input_kind, panel, dependencies, refs,
                     created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, producer_key) DO NOTHING
                """,
                (
                    artifact.artifact_id,
                    artifact.run_id,
                    artifact.kind,
                    artifact.schema_version,
                    artifact.producer_key,
                    artifact.media_type,
                    artifact.size_bytes,
                    artifact.payload_sha256,
                    (artifact.data_digest or {}).get("algorithm"),
                    (artifact.data_digest or {}).get("value"),
                    artifact.source_bytes_sha256,
                    artifact.storage_key,
                    artifact.context_id,
                    artifact.data_revision,
                    artifact.input_kind,
                    json.dumps(artifact.panel, ensure_ascii=False)
                    if artifact.panel is not None
                    else None,
                    json.dumps(artifact.dependencies, ensure_ascii=False),
                    json.dumps(artifact.refs, ensure_ascii=False),
                    artifact.created_by,
                    artifact.created_at,
                ),
            )
            inserted = cur.rowcount == 1
            if not inserted:
                cur.execute(
                    "SELECT " + self._SELECT_COLUMNS
                    + " FROM research_artifacts WHERE run_id = %s AND producer_key = %s",
                    (artifact.run_id, artifact.producer_key),
                )
                row = cur.fetchone()
                conn.commit()
                if row is None:  # pragma: no cover -- конфликт-гонка
                    raise ArtifactConflictError(
                        "producer_key занят, запись не читается"
                    )
                existing = self._artifact_from_row(row)
                if existing.payload_sha256 != artifact.payload_sha256:
                    raise ArtifactConflictError(
                        "Тот же producer_key с другим контентом -- "
                        "конфликт без записи (AC09)"
                    )
                return existing, False
            conn.commit()
        return artifact.copy(), True

    def get_artifact(self, artifact_id: str) -> Optional[ResultArtifact]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT " + self._SELECT_COLUMNS
                + " FROM research_artifacts WHERE artifact_id = %s",
                (artifact_id,),
            )
            row = cur.fetchone()
        return self._artifact_from_row(row) if row else None

    def list_artifacts(
        self, run_id: str, kind: Optional[str] = None
    ) -> list[ResultArtifact]:
        query = (
            "SELECT " + self._SELECT_COLUMNS
            + " FROM research_artifacts WHERE run_id = %s"
        )
        params: list[Any] = [run_id]
        if kind is not None:
            query += " AND kind = %s"
            params.append(kind)
        query += " ORDER BY created_at, artifact_id"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def pin_ref(
        self,
        run_id: str,
        ref_kind: str,
        ref_id: str,
        *,
        reason: str = "",
        created_by: Optional[str] = None,
    ) -> ArtifactPin:
        pin_id = uuid.uuid4().hex
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_artifact_pins
                    (pin_id, run_id, ref_kind, ref_id, reason, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, ref_kind, ref_id) DO NOTHING
                """,
                (pin_id, run_id, ref_kind, ref_id, reason, created_by),
            )
            inserted = cur.rowcount == 1
            if not inserted:
                cur.execute(
                    "SELECT pin_id, run_id, ref_kind, ref_id, reason, "
                    "created_by, created_at FROM research_artifact_pins "
                    "WHERE run_id = %s AND ref_kind = %s AND ref_id = %s",
                    (run_id, ref_kind, ref_id),
                )
                row = cur.fetchone()
                conn.commit()
                return ArtifactPin(
                    pin_id=str(row[0]),
                    run_id=str(row[1]),
                    ref_kind=str(row[2]),
                    ref_id=str(row[3]),
                    reason=str(row[4] or ""),
                    created_by=(str(row[5]) if row[5] else None),
                    created_at=(
                        row[6].isoformat()
                        if hasattr(row[6], "isoformat") else str(row[6])
                    ),
                )
            conn.commit()
        return ArtifactPin(
            pin_id=pin_id,
            run_id=run_id,
            ref_kind=ref_kind,
            ref_id=ref_id,
            reason=reason,
            created_by=created_by,
        )

    def unpin_ref(self, run_id: str, ref_kind: str, ref_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM research_artifact_pins "
                "WHERE run_id = %s AND ref_kind = %s AND ref_id = %s",
                (run_id, ref_kind, ref_id),
            )
            deleted = cur.rowcount == 1
            conn.commit()
        return deleted

    def list_pins(
        self, run_id: str, ref_kind: Optional[str] = None
    ) -> list[ArtifactPin]:
        query = (
            "SELECT pin_id, run_id, ref_kind, ref_id, reason, created_by, "
            "created_at FROM research_artifact_pins WHERE run_id = %s"
        )
        params: list[Any] = [run_id]
        if ref_kind is not None:
            query += " AND ref_kind = %s"
            params.append(ref_kind)
        query += " ORDER BY created_at, pin_id"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
        return [
            ArtifactPin(
                pin_id=str(row[0]),
                run_id=str(row[1]),
                ref_kind=str(row[2]),
                ref_id=str(row[3]),
                reason=str(row[4] or ""),
                created_by=(str(row[5]) if row[5] else None),
                created_at=(
                    row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6])
                ),
            )
            for row in rows
        ]


# ── Фабрики (паритет get_research_run_store) ─────────────────────────

_registry: Optional[ArtifactRegistry] = None
_object_store: Optional[ArtifactObjectStore] = None

ARTIFACTS_BACKEND_ENV = "CISSTAT_ARTIFACTS_BACKEND"


def get_artifact_registry() -> ArtifactRegistry:
    """Выбор backend (симметрично get_research_run_store):
    CISSTAT_ARTIFACTS_BACKEND=memory -> Memory; =postgres или DATABASE_URL
    -> Postgres; иначе Memory (auto). Required-режим -- fail-closed
    (тихий Memory fallback запрещён, P21/F14); advisory -- ЯВНАЯ
    деградация с фиксацией в /health/ops."""
    global _registry
    if _registry is not None:
        return _registry

    from apps.api.storage_diagnostics import (
        COMPONENT_ARTIFACTS,
        get_storage_mode,
        record_backend_fallback,
        record_backend_selected,
        safe_error,
    )

    mode = get_storage_mode()
    backend_explicit = os.environ.get(ARTIFACTS_BACKEND_ENV, "").lower()
    database_url = os.environ.get("DATABASE_URL", "")

    if backend_explicit == "memory":
        _registry = MemoryArtifactRegistry()
        record_backend_selected(COMPONENT_ARTIFACTS, "memory", "memory")
    elif backend_explicit == "postgres" or database_url:
        record_backend_selected(COMPONENT_ARTIFACTS, "postgres", "initializing")
        try:
            candidate = PostgresArtifactRegistry.from_env()
            if mode == "required":
                probe = candidate.readiness_probe()
                if not probe.get("ok"):
                    reason = probe.get("error") or "readiness probe failed"
                    raise RuntimeError(
                        "ArtifactRegistry: Postgres backend required, "
                        f"но недоступен (fail-closed, P21/F14): {reason}"
                    )
            _registry = candidate
            record_backend_selected(COMPONENT_ARTIFACTS, "postgres", "postgres")
            logger.info("ArtifactRegistry: Postgres backend selected")
        except Exception as e:
            reason = safe_error(e)
            if mode == "required":
                record_backend_selected(
                    COMPONENT_ARTIFACTS, "postgres", "unavailable",
                    reason=reason, degraded=True,
                )
                raise RuntimeError(
                    "ArtifactRegistry: Postgres backend required, "
                    f"но инициализация не удалась (fail-closed, P21/F14): "
                    f"{reason}"
                ) from e
            logger.error(
                "ArtifactRegistry: Postgres init failed (%s), ЯВНАЯ "
                "деградация в Memory (advisory; состояние в /health/ops)",
                reason,
            )
            record_backend_fallback(
                COMPONENT_ARTIFACTS, "postgres", reason, effective="memory"
            )
            _registry = MemoryArtifactRegistry()
    else:
        _registry = MemoryArtifactRegistry()
        record_backend_selected(COMPONENT_ARTIFACTS, "auto", "memory")

    return _registry


def peek_artifact_registry() -> Optional[ArtifactRegistry]:
    """Чтение singleton БЕЗ инициализации (/health/ops не провоцирует
    создание; паритет peek_research_run_store)."""
    return _registry


def reset_artifact_registry_for_testing() -> None:
    global _registry
    _registry = None


def get_artifact_object_store() -> ArtifactObjectStore:
    """Singleton файлового слоя (root может задаваться env -- тесты
    переопределяют CISSTAT_DATA_DIR; паритет get_dataset_file_store)."""
    global _object_store
    if _object_store is None:
        _object_store = ArtifactObjectStore(ArtifactObjectStore.default_root())
    return _object_store


def reset_artifact_object_store_for_testing() -> None:
    global _object_store
    _object_store = None
