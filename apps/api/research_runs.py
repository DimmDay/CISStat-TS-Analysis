# apps/api/research_runs.py
"""Долговременный слой трассы «Прогресса» (spec_progress.md §5 слой 2,
Task PROGR-5): research_runs/trace_events + чекпоинты/пауза/restore.

ПРОБЛЕМА (§5): SessionStore -- TTL 30 дней по cookie браузера. Он
закрывает цели «онлайн-ориентация» и паузу В ПРЕДЕЛАХ одного браузера
(слой 1, AnalysisSession.pipeline_trace -- Task PROGR-3), но не годится
для отчёта пользователю (цель 2), техподдержки по голосом-произносимому
run_id (цель 3) и корпуса трасс по ВСЕМ пользователям (цель 5, админ §10).

РЕШЕНИЕ -- второй слой, В ДОПОЛНЕНИЕ к внутрисессионному буферу (§5
дословно: «Именно сюда пишет middleware из §4.2 -- в дополнение к
внутрисессионному буферу, не вместо него»):

  research_runs: run_id (PK, показывается пользователю, "RUN-XXXXXXXX"),
                 session_id (последний известный), dataset_fingerprint,
                 dataset_name, target_column, created_at, last_active_at,
                 status (active/paused/completed/abandoned);
  trace_events:  append-only журнал, run_id -- внешний ключ;
  run_checkpoints: именованные ссылки на события трассы (§5.1, паттерн
                 PassportCheckpoint -- «ссылка на снимок, а не копия»).

run_id переживает cookie: новая сессия (другое устройство, истёкший
cookie) продолжает ТОТ ЖЕ запуск через restore (§5.3) -- это приёмка
плана (plan_progress.md, «run_id переживает cookie»).

ХРАНИЛИЩА (паттерн SessionStore, КОНТРАКТ по алиасингу тот же):
  - MemoryResearchRunStore -- default dev/tests: in-memory dict,
    записи ГЛУБОКО копируются на границе записи и чтения (R1
    сертификации PROGR-1-CERT);
  - PostgresResearchRunStore -- production (§12 п.1: реляционная модель
    под SQL-агрегации админа; TraceEvent -- фиксированная схема, не
    эволюционирующий документ; Redis остаётся кэшем с TTL). Коннект
    ленивый (на первой операции), DDL -- идемпотентная миграция
    MIGRATION_STATEMENTS (дубль для ops: apps/api/migrations/
    0001_research_runs.sql).

ВЫБОР ПО ENV (симметрично get_session_store):
  - CISSTAT_RUNS_BACKEND=memory -> Memory (приоритетнее DATABASE_URL);
  - CISSTAT_RUNS_BACKEND=postgres или DATABASE_URL задан -> Postgres;
  - иначе -> Memory.
Сбой недоступного Postgres на операции НЕ роняет трассируемый эндпоинт:
зеркало -- best-effort (см. record_run_event); читающие эндпоинты
/ v1/progress/runs/* отвечают 503 (долговременный слой для них
первичен, деградировать на Memory там нельзя -- это была бы ложь).

ЗАПИСЬ: зеркало record_run_event() вызывается из TraceHookMiddleware
(PROGR-3) на каждом событии слоя 1 И из _append_event Прогнозирования
(унификация, обещанная PROGR-3: forecasting-события живут в
ForecastRun.trace, слой 2 -- их единственная долговременная копия).

ФАЙЛОВЫЙ СЛОВЬ (DatasetFileStore, §12 п.3/п.4): data/uploads/ на
локальном диске по dataset_fingerprint (файл + мета-sidecar) -- делает
restore полным, а не «только метаданные»; снимки чекпоинтов --
последние 5 на run_id. Отклонение от рекомендации §12 п.4: формат CSV
(pandas native), а не Parquet -- pyarrow в среде недоступен; замена
формата изолирована в save/load_checkpoint_snapshot.

FINGERPRINT: dataset_fingerprint = SHA-256 байт исходного файла,
вычисляется при загрузке. Отступление от формулировки §12 п.3 «пере-
используется, не изобретается новый хэш»: существующий series_fingerprint
(app/core/passport.py) определён для ряда с датой и значением (target),
которого в момент загрузки ещё нет; file-хэш -- единственный честный
ключ файла в этот момент. Сверка когорт Моделирования продолжает
использовать series_fingerprint, никакой подмены нет.

N-2 (находка PROGR-4): stage-level события (node_id=None) не создают
узловых фактов НИГДЕ в этом модуле -- restore засевает трассу «как
есть», свод стадий остаётся честным по узлам; факт target_column
фиксируется в метаданных запуска из payload target_column_changed, а
не в статусах узлов.

N-4 (находка PROGR-4): ответы эндпоинтов этого слоя не содержат
команд управления панелью (открыть/закрыть/перейти) -- панель «Прогресс»
и deep-link узлов живут во фронтенде (PROGR-4), бэкенд отдаёт только
факты.

PROGR-8 (spec_progress.md §10 + §9) добавляет в долговременный слой
ЖУРНАЛ НАБЛЮДЕНИЙ НАСТАВНИКА (append-only, таблица
mentor_observations): частота срабатывания правил «Следующий шаг»
(§7.1) и sanity-предупреждений (§7.2) по правилу/узлу НИГДЕ не
персистилась -- sanity-check чистое вычисление над телом запроса,
next-step вычисление над трассой; а агрегатам §10 нужен корпус.
Почему НЕ trace_events: трасса -- канон §4.1, события РЕШЕНИЙ
аналитика; служебные события телеметрии Наставника не имеют ни
шаблона в отчёте §5.4 (неизвестный тип стал бы «строкой аудита»), ни
узлового факта -- это было бы загрязнение пользовательских артефактов.
Журнал -- независимый append-only поток (без FK на research_runs:
телеметрия переживает удаление запуска; агрегаты частот корпусные).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from apps.api.trace_events import TraceEvent, mark_honest_time

logger = logging.getLogger(__name__)

# ── Модель данных ────────────────────────────────────────────────────

# Статусы запуска (§5): пауза -- явная фиксация (§5.2), abandoned --
# брошенные (аналитик начал новое исследование в той же сессии),
# completed -- завершённое исследование (restore для него закрыт, §5.3).
RUN_STATUSES = ("active", "paused", "completed", "abandoned")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchRun:
    """Запуск исследования (§5): постоянный идентификатор, переживающий
    cookie-сессию. Иммутабельная запись -- обновления через replace()
    + upsert_run (тот же стиль, что замороженные TraceEvent)."""

    run_id: str
    session_id: str = ""
    dataset_fingerprint: str = ""
    dataset_name: str = ""
    target_column: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    last_active_at: str = field(default_factory=_now_iso)
    status: str = "active"

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError(
                f"Неизвестный статус запуска: {self.status!r}; "
                f"известные: {list(RUN_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "dataset_name": self.dataset_name,
            "target_column": self.target_column,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ResearchRun":
        return cls(
            run_id=str(raw["run_id"]),
            session_id=str(raw.get("session_id") or ""),
            dataset_fingerprint=str(raw.get("dataset_fingerprint") or ""),
            dataset_name=str(raw.get("dataset_name") or ""),
            target_column=raw.get("target_column"),
            created_at=str(raw.get("created_at") or _now_iso()),
            last_active_at=str(raw.get("last_active_at") or _now_iso()),
            status=str(raw.get("status") or "active"),
        )


@dataclass(frozen=True)
class ResearchCheckpoint:
    """Контрольная точка (§5.1) -- именованная ссылка на конкретное
    событие trace_events + человекочитаемый комментарий. Не копия
    события (паттерн PassportCheckpoint: «ссылка на снимок, а не копия
    данных»); создаётся ЯВНО (кнопка «Сохранить точку»), не автоматически --
    иначе чекпоинты обесцениваются количеством (§5.1)."""

    checkpoint_id: str
    run_id: str
    event_id: str
    label: str = ""
    has_snapshot: bool = False
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "label": self.label,
            "has_snapshot": self.has_snapshot,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ResearchCheckpoint":
        return cls(
            checkpoint_id=str(raw["checkpoint_id"]),
            run_id=str(raw["run_id"]),
            event_id=str(raw["event_id"]),
            label=str(raw.get("label") or ""),
            has_snapshot=bool(raw.get("has_snapshot") or False),
            created_at=str(raw.get("created_at") or _now_iso()),
        )


@dataclass(frozen=True)
class DatasetSource:
    """Найденный в файловом слое исходный датасет: байты + мета-sidecar."""

    data: bytes
    meta: dict[str, Any]


# Виды наблюдений журнала Наставника (PROGR-8, §10):
#   sanity_warning -- сработавшее предупреждение §7.2 (одно наблюдение
#                    на КАЖДОЕ сработавшее правило, их список §7.2);
#   next_step     -- ВЫДАННАЯ рекомендация §7.1 (частота выдач --
#                    «какие рекомендации даются чаще всего», §10 дословно).
MENTOR_OBSERVATION_KINDS = ("sanity_warning", "next_step")


@dataclass(frozen=True)
class MentorObservation:
    """Наблюдение журнала Наставника (PROGR-8): факт СРАБАТЫВАНИЯ
    правила, без текстов сообщений (они рендерятся движком правил --
    журнал несёт только идентификацию для агрегатов §10).

    Fail-closed (паттерн ResearchRun.__post_init__): неизвестный вид,
    пустые run_id/rule_id -- ValueError на конструировании, опечатка
    не должна молча исчезнуть из журнала.
    """

    obs_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    ts: str = field(default_factory=_now_iso)
    obs_kind: str = "sanity_warning"
    rule_id: str = ""
    stage: str = ""
    node_id: Optional[str] = None
    severity: str = ""

    def __post_init__(self) -> None:
        if self.obs_kind not in MENTOR_OBSERVATION_KINDS:
            raise ValueError(
                f"Неизвестный вид наблюдения: {self.obs_kind!r}; "
                f"известные: {list(MENTOR_OBSERVATION_KINDS)}"
            )
        if not self.run_id:
            raise ValueError("Наблюдение журнала требует run_id (§5: событие без исследования не существует)")
        if not self.rule_id:
            raise ValueError("Наблюдение журнала требует rule_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "obs_id": self.obs_id,
            "run_id": self.run_id,
            "ts": self.ts,
            "obs_kind": self.obs_kind,
            "rule_id": self.rule_id,
            "stage": self.stage,
            "node_id": self.node_id,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MentorObservation":
        return cls(
            obs_id=str(raw.get("obs_id") or uuid.uuid4()),
            run_id=str(raw.get("run_id") or ""),
            ts=str(raw.get("ts") or _now_iso()),
            obs_kind=str(raw.get("obs_kind") or "sanity_warning"),
            rule_id=str(raw.get("rule_id") or ""),
            stage=str(raw.get("stage") or ""),
            node_id=raw.get("node_id"),
            severity=str(raw.get("severity") or ""),
        )


# ── Миграция схемы (план: «миграции схемы») ──────────────────────────

# Идемпотентный DDL (§12 п.1): research_runs -- PK run_id; trace_events --
# append-only (seq BIGSERIAL -- порядок дописывания, уникальность
# (run_id, event_id) страхует повторную запись); run_checkpoints --
# ссылки на события. Postgres-специфичные типы (TIMESTAMPTZ/JSONB/BIGSERIAL).
MIGRATION_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL DEFAULT '',
        dataset_fingerprint TEXT NOT NULL DEFAULT '',
        dataset_name TEXT NOT NULL DEFAULT '',
        target_column TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        status TEXT NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_events (
        seq BIGSERIAL PRIMARY KEY,
        event_id TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        ts TIMESTAMPTZ NOT NULL,
        stage TEXT NOT NULL,
        node_id TEXT,
        event_type TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        actor TEXT NOT NULL DEFAULT 'user',
        UNIQUE (run_id, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_checkpoints (
        checkpoint_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        event_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        has_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_events_run_seq ON trace_events (run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_session ON research_runs (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs (status)",
    # PROGR-8 (§10): журнал наблюдений Наставника. БЕЗ FK на research_runs:
    # телеметрия переживает удаление запуска, агрегаты частот корпусные.
    """
    CREATE TABLE IF NOT EXISTS mentor_observations (
        seq BIGSERIAL PRIMARY KEY,
        obs_id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        obs_kind TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT '',
        node_id TEXT,
        severity TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mentor_observations_run ON mentor_observations (run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_mentor_observations_rule ON mentor_observations (obs_kind, rule_id)",
)


def run_migrations(conn: Any) -> int:
    """Прогоняет MIGRATION_STATEMENTS через открытое psycopg-соединение.
    Возвращает число выполненных утверждений (для логов старта)."""
    cursor = conn.cursor()
    executed = 0
    for statement in MIGRATION_STATEMENTS:
        cursor.execute(statement)
        executed += 1
    conn.commit()
    return executed


# ── Контракт хранилища ───────────────────────────────────────────────


class ResearchRunStore:
    """Контракт долговременного слоя (паттерн SessionStore ABC).

    Все реализации обязаны:
      * возвращать КОПИИ записей (не живые объекты) -- R1;
      * хранить события в порядке дописывания (append-only, §5);
      * не валидировать (stage, event_type) повторно -- гейт
        make_trace_event (§4.1) уже отработал у источника; на границе
        чтения события восстанавливаются через TraceEvent.from_dict
        (нормализация legacy -- решения R2/R3 PROGR-3-CERT).
    """

    def upsert_run(self, run: ResearchRun) -> None:  # pragma: no cover - контракт
        raise NotImplementedError

    def get_run(self, run_id: str) -> Optional[ResearchRun]:  # pragma: no cover
        raise NotImplementedError

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:  # pragma: no cover
        raise NotImplementedError

    def set_run_status(self, run_id: str, status: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def append_event(self, run_id: str, event: TraceEvent) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_events(self, run_id: str) -> list[TraceEvent]:  # pragma: no cover
        raise NotImplementedError

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:  # pragma: no cover
        raise NotImplementedError

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:  # pragma: no cover
        raise NotImplementedError

    # -- журнал наблюдений Наставника (PROGR-8, §10) --

    def append_mentor_observation(self, obs: MentorObservation) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_mentor_observations(self) -> list[MentorObservation]:  # pragma: no cover
        """Весь журнал (по всем запускам): агрегаты §10 -- корпусные,
        объёмы одной платформы (§12 п.1) приемлемы для полного чтения
        (тот же паттерн «журнал целиком», что R-1 отчёта PROGR-7)."""
        raise NotImplementedError


def _ts_to_db(value: str) -> datetime:
    """ISO-строка канона §4.1 -> datetime для TIMESTAMPTZ. Битое значение
    -- текущий момент с warning (деградация, не потеря события)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("Research runs: нечитаемый ts %r -- подставлен текущий момент", value)
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ts_from_db(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class MemoryResearchRunStore(ResearchRunStore):
    """In-memory реализация (default dev/tests). Глубокие копии payload
    на записи и чтении -- тот же контракт изоляции, что R1 слоя 1."""

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}
        self._events: dict[str, list[TraceEvent]] = {}
        self._checkpoints: dict[str, list[ResearchCheckpoint]] = {}
        self._observations: list[MentorObservation] = []
        self._lock = threading.Lock()

    def upsert_run(self, run: ResearchRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:
        with self._lock:
            runs = list(self._runs.values())
        if session_id is not None:
            runs = [run for run in runs if run.session_id == session_id]
        return sorted(runs, key=lambda run: run.created_at)

    def set_run_status(self, run_id: str, status: str) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"Неизвестный статус запуска: {status!r}")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            self._runs[run_id] = replace(run, status=status, last_active_at=_now_iso())

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:
        with self._lock:
            for run_id, run in self._runs.items():
                if (
                    run.session_id == session_id
                    and run.run_id != keep_run_id
                    and run.status == "active"
                ):
                    self._runs[run_id] = replace(
                        run, status="abandoned", last_active_at=_now_iso()
                    )

    def append_event(self, run_id: str, event: TraceEvent) -> None:
        if not event.event_id:
            # R4 (PROGR-3-CERT): backfill id при записи -- повторное чтение
            # не перегенерирует идентификатор.
            event = replace(event, event_id=str(uuid.uuid4()))
        # AUDIT-S (F16/P23): честная маркировка времени на границе записи.
        # Memory сохраняет raw ts КАК ЕСТЬ -- нечитаемое время маркируется
        # degraded (никакой подмены); idempotent, валидные события не
        # трогает.
        event = mark_honest_time(event, substituted=False)
        # R1: payload копируется ГЛУБОКО -- stored не разделяет вложенные
        # структуры с источником.
        event = replace(event, payload=deepcopy(event.payload))
        with self._lock:
            self._events.setdefault(run_id, []).append(event)

    def list_events(self, run_id: str) -> list[TraceEvent]:
        with self._lock:
            stored = list(self._events.get(run_id, ()))
        # Чтение тоже копирует (контракт «возвращать копии, не живые
        # объекты»): мутации прочитанного payload не портят stored.
        return [replace(event, payload=deepcopy(event.payload)) for event in stored]

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:
        with self._lock:
            for event in self._events.get(run_id, ()):
                if event.event_id == event_id:
                    return event
        return None

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:
        with self._lock:
            self._checkpoints.setdefault(run_id, []).append(checkpoint)

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:
        with self._lock:
            return list(self._checkpoints.get(run_id, ()))

    # -- журнал наблюдений Наставника (PROGR-8, §10) --

    def append_mentor_observation(self, obs: MentorObservation) -> None:
        # MentorObservation заморожена и не содержит вложенных мутабельных
        # структур -- хранится как есть (контракт копий R1 касается
        # payload-словарей, которых здесь нет).
        with self._lock:
            self._observations.append(obs)

    def list_mentor_observations(self) -> list[MentorObservation]:
        with self._lock:
            # Порядок дописывания (append-only), как у trace_events.
            return list(self._observations)


class PostgresResearchRunStore(ResearchRunStore):
    """Postgres-реализация (§12 п.1, production). Ленивый коннект: только
    psycopg.connect() на каждой операции (объёмы одной платформы -- не
    интернет-масштаб, §12 п.1; пул коннектов -- зрелая оптимизация).
    Проверка существования таблиц -- один раз на процесс (ensure_schema).

    Драйвер psycopg (v3) импортируется лениво -- как redis в
    RedisSessionStore.from_env; среда без драйвера просто не выбирает
    этот бэкенд (нет DATABASE_URL), импорт модуля не падает.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresResearchRunStore":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresResearchRunStore. "
                "Set it to your Postgres connection string."
            )
        return PostgresResearchRunStore(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- см. докстринг класса

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    executed = run_migrations(conn)
                    logger.info(
                        "Research runs: схема Postgres готова (%d утверждений)", executed
                    )
                    self._schema_ready = True
        return conn

    # -- runs --

    def upsert_run(self, run: ResearchRun) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_runs
                    (run_id, session_id, dataset_fingerprint, dataset_name,
                     target_column, created_at, last_active_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    dataset_fingerprint = EXCLUDED.dataset_fingerprint,
                    dataset_name = EXCLUDED.dataset_name,
                    target_column = EXCLUDED.target_column,
                    created_at = EXCLUDED.created_at,
                    last_active_at = EXCLUDED.last_active_at,
                    status = EXCLUDED.status
                """,
                (
                    run.run_id, run.session_id, run.dataset_fingerprint,
                    run.dataset_name, run.target_column,
                    _ts_to_db(run.created_at), _ts_to_db(run.last_active_at),
                    run.status,
                ),
            )
            conn.commit()

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, session_id, dataset_fingerprint, dataset_name, "
                "target_column, created_at, last_active_at, status "
                "FROM research_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:
        query = (
            "SELECT run_id, session_id, dataset_fingerprint, dataset_name, "
            "target_column, created_at, last_active_at, status FROM research_runs"
        )
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = %s"
            params = (session_id,)
        query += " ORDER BY created_at"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [self._run_from_row(row) for row in rows]

    def set_run_status(self, run_id: str, status: str) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"Неизвестный статус запуска: {status!r}")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE research_runs SET status = %s, last_active_at = %s "
                "WHERE run_id = %s",
                (status, _ts_to_db(_now_iso()), run_id),
            )
            conn.commit()

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE research_runs SET status = 'abandoned', "
                "last_active_at = %s WHERE session_id = %s AND run_id <> %s "
                "AND status = 'active'",
                (_ts_to_db(_now_iso()), session_id, keep_run_id),
            )
            conn.commit()

    @staticmethod
    def _run_from_row(row: tuple[Any, ...]) -> ResearchRun:
        return ResearchRun(
            run_id=str(row[0]),
            session_id=str(row[1] or ""),
            dataset_fingerprint=str(row[2] or ""),
            dataset_name=str(row[3] or ""),
            target_column=row[4],
            created_at=_ts_from_db(row[5]),
            last_active_at=_ts_from_db(row[6]),
            status=str(row[7] or "active"),
        )

    # -- события --

    def append_event(self, run_id: str, event: TraceEvent) -> None:
        # AUDIT-S (F16/P23): Postgres ЗАМЕНЯЕТ нечитаемый ts значением
        # «записано сейчас» (_ts_to_db строит значение TIMESTAMPTZ-строки)
        # -- замена честно маркируется substituted ДО записи (raw_ts
        # сохранён в envelope; durable-хранение маркировки в строке --
        # миграция AUDIT-6A). Idempotent, валидные события не трогает.
        event = mark_honest_time(event, substituted=True)
        event_id = event.event_id or str(uuid.uuid4())
        payload = json.dumps(event.payload, default=str, ensure_ascii=False)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trace_events
                    (event_id, run_id, ts, stage, node_id, event_type, payload, actor)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (run_id, event_id) DO NOTHING
                """,
                (
                    event_id, run_id, _ts_to_db(event.ts), event.stage,
                    event.node_id, event.event_type, payload, event.actor,
                ),
            )
            conn.commit()

    def list_events(self, run_id: str) -> list[TraceEvent]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, run_id, ts, stage, node_id, event_type, "
                "payload::text, actor FROM trace_events WHERE run_id = %s "
                "ORDER BY seq",
                (run_id,),
            )
            rows = cur.fetchall()
        return [
            TraceEvent(
                event_id=str(row[0]),
                run_id=str(row[1]),
                ts=_ts_from_db(row[2]),
                stage=str(row[3]),
                node_id=row[4],
                event_type=str(row[5]),
                payload=json.loads(row[6] or "{}"),
                actor=str(row[7] or "user"),
            )
            for row in rows
        ]

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:
        events = [event for event in self.list_events(run_id) if event.event_id == event_id]
        return events[0] if events else None

    # -- чекпоинты --

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO run_checkpoints
                    (checkpoint_id, run_id, event_id, label, has_snapshot, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (checkpoint_id) DO NOTHING
                """,
                (
                    checkpoint.checkpoint_id, run_id, checkpoint.event_id,
                    checkpoint.label, checkpoint.has_snapshot,
                    _ts_to_db(checkpoint.created_at),
                ),
            )
            conn.commit()

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT checkpoint_id, run_id, event_id, label, has_snapshot, "
                "created_at FROM run_checkpoints WHERE run_id = %s ORDER BY created_at, checkpoint_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [
            ResearchCheckpoint(
                checkpoint_id=str(row[0]),
                run_id=str(row[1]),
                event_id=str(row[2]),
                label=str(row[3] or ""),
                has_snapshot=bool(row[4]),
                created_at=_ts_from_db(row[5]),
            )
            for row in rows
        ]

    # -- журнал наблюдений Наставника (PROGR-8, §10) --

    def append_mentor_observation(self, obs: MentorObservation) -> None:
        obs_id = obs.obs_id or str(uuid.uuid4())
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mentor_observations
                    (obs_id, run_id, ts, obs_kind, rule_id, stage, node_id, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (obs_id) DO NOTHING
                """,
                (
                    obs_id, obs.run_id, _ts_to_db(obs.ts), obs.obs_kind,
                    obs.rule_id, obs.stage, obs.node_id, obs.severity,
                ),
            )
            conn.commit()

    def list_mentor_observations(self) -> list[MentorObservation]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT obs_id, run_id, ts, obs_kind, rule_id, stage, "
                "node_id, severity FROM mentor_observations ORDER BY seq",
            )
            rows = cur.fetchall()
        return [
            MentorObservation(
                obs_id=str(row[0]),
                run_id=str(row[1]),
                ts=_ts_from_db(row[2]),
                obs_kind=str(row[3]),
                rule_id=str(row[4]),
                stage=str(row[5] or ""),
                node_id=row[6],
                severity=str(row[7] or ""),
            )
            for row in rows
        ]


# ── Фабрика + синглтон (паттерн get_session_store) ───────────────────

_store: Optional[ResearchRunStore] = None


def get_research_run_store() -> ResearchRunStore:
    """Возвращает singleton хранилища запусков.

    ВЫБОР БЭКЕНДА (симметрично get_session_store):
      - CISSTAT_RUNS_BACKEND=memory -> Memory (приоритет над DATABASE_URL);
      - CISSTAT_RUNS_BACKEND=postgres или DATABASE_URL задан -> Postgres
        (ленивый коннект; сбой конструктора -> деградация в Memory с
        error-логом, тот же философия, что у Redis-фолбэка SessionStore);
      - иначе -> Memory.
    """
    global _store
    if _store is not None:
        return _store

    backend_explicit = os.environ.get("CISSTAT_RUNS_BACKEND", "").lower()
    database_url = os.environ.get("DATABASE_URL", "")

    if backend_explicit == "memory":
        _store = MemoryResearchRunStore()
    elif backend_explicit == "postgres" or database_url:
        try:
            _store = PostgresResearchRunStore.from_env()
            logger.info("ResearchRunStore: Postgres backend selected")
        except Exception as e:
            logger.error(
                "ResearchRunStore: Postgres init failed (%s), falling back to Memory", e
            )
            _store = MemoryResearchRunStore()
    else:
        _store = MemoryResearchRunStore()

    return _store


def reset_research_run_store_for_testing() -> None:
    """Сброс singleton. ТОЛЬКО для тестов (паттерн session_store)."""
    global _store
    _store = None


# ── Зеркало слоя 1 -> слой 2 (§5: «в дополнение, не вместо») ─────────


def record_run_event(session: Any, event: TraceEvent) -> None:
    """Отражает событие трассы в долговременный слой. Best-effort: любой
    сбой -- warning и возврат (трасса вспомогательна по отношению к
    основной операции, §4.2; успешный ответ эндпоинта не ломается).

    События без run_id пропускаются честно: запуск существует только
    вместе с исследованием (§5 -- run_id по факту первой загрузки).
    Для Прогнозирования (ForecastRun.trace, run_id в событии пуст --
    исторический контракт PROGR-1) run_id берётся из сессии.
    """
    try:
        run_id = event.run_id or getattr(session, "run_id", "") or ""
        if not run_id:
            return
        # §4.1: событие слоя 2 несёт run_id канонически; у forecasting-
        # событий (ForecastRun.trace) поле пустое исторически -- attach
        # из запуска, чтобы журнал был самодостаточным.
        if not event.run_id:
            event = replace(event, run_id=run_id)
        store = get_research_run_store()
        dataset = getattr(session, "dataset", None)
        existing = store.get_run(run_id)
        if existing is None:
            # Новый запуск: предыдущие АКТИВНЫЕ запуски этой сессии --
            # abandoned (новый датасет = новое исследование, §3.1/§5.2).
            store.supersede_active_runs(session.session_id, keep_run_id=run_id)
            run = ResearchRun(
                run_id=run_id,
                session_id=session.session_id,
                dataset_fingerprint=getattr(dataset, "dataset_fingerprint", "") or "",
                dataset_name=getattr(dataset, "name", "") or "",
            )
        else:
            # session_id -- «последний известный» (§5): запускается
            # перелинковка при restore/продолжении на новом устройстве.
            run = replace(existing, session_id=session.session_id)
        if event.event_type == "target_column_changed":
            raw_target = event.payload.get("target_column")
            run = replace(run, target_column=str(raw_target) if raw_target else None)
        run = replace(run, last_active_at=_now_iso())
        store.upsert_run(run)
        store.append_event(run_id, event)
    except Exception:
        logger.warning(
            "Research runs: событие %s не отражено в долговременном слое",
            getattr(event, "event_type", "?"),
            exc_info=True,
        )


# ── Файловый слой (§12 п.3 uploads + §12 п.4 снимки чекпоинтов) ──────


class DatasetFileStore:
    """Каталог данных на локальном диске (§12 п.3: «локальный диск дёшев
    и уже персистентен по умолчанию»):

      {root}/uploads/{fingerprint}{ext}       -- байты исходного файла
      {root}/uploads/{fingerprint}.meta.json  -- мета (имя/размерность)
      {root}/checkpoints/{run_id}/{checkpoint_id}.csv -- снимки (§12 п.4)

    Корень: env CISSTAT_DATA_DIR, иначе <репозиторий>/data. Все операции
    создают каталоги по требованию; отсутствие файла -- честный None
    (restore отвечает 409 «повторная загрузка», §5.3).
    """

    UPLOADS_DIR = "uploads"
    CHECKPOINTS_DIR = "checkpoints"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @staticmethod
    def default_root() -> Path:
        env_root = os.environ.get("CISSTAT_DATA_DIR", "")
        if env_root:
            return Path(env_root)
        # <репозиторий>/data (apps/api/research_runs.py -> parents[2]).
        return Path(__file__).resolve().parents[2] / "data"

    @property
    def uploads_dir(self) -> Path:
        return self._root / self.UPLOADS_DIR

    def _checkpoints_dir(self, run_id: str) -> Path:
        return self._root / self.CHECKPOINTS_DIR / run_id

    def _ext_of(self, filename: str) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in {".csv", ".xlsx", ".xls", ".tsv", ".json"}:
            return suffix
        return ".csv"

    def save_upload(
        self,
        contents: bytes,
        filename: str,
        *,
        rows: int,
        columns: int,
        size_label: str,
    ) -> str:
        """Сохраняет байты под SHA-256 fingerprint (+ мета-sidecar).
        Возвращает fingerprint. Best-effort у вызывающего: сбой диска не
        должен ронять загрузку (restore ответит 409 честно)."""
        fingerprint = hashlib.sha256(contents).hexdigest()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        data_path = self.uploads_dir / f"{fingerprint}{self._ext_of(filename)}"
        data_path.write_bytes(contents)
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "name": filename,
                    "rows": rows,
                    "columns": columns,
                    "size_label": size_label,
                    "source": "upload",
                    "saved_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return fingerprint

    def register_demo(
        self,
        demo_path: Path,
        *,
        name: str,
        rows: int,
        columns: int,
        size_label: str,
    ) -> str:
        """Демо-датасет не копируется (файл встроен в приложение и
        доступен на сервере -- §5.3): в мете источник builtin_demo.
        Fingerprint -- SHA-256 байт демо-файла (та же формула, что у
        upload: один и тот же файл = один и тот же запуск при restore)."""
        contents = Path(demo_path).read_bytes()
        fingerprint = hashlib.sha256(contents).hexdigest()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "name": name,
                    "rows": rows,
                    "columns": columns,
                    "size_label": size_label,
                    "source": "builtin_demo",
                    "demo_path": str(demo_path),
                    "saved_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return fingerprint

    def load(self, fingerprint: str) -> Optional[DatasetSource]:
        """Байты исходного датасета по fingerprint; None -- файла нет
        (честная деградация restore до «повторной загрузки», §5.3)."""
        if not fingerprint:
            return None
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Dataset files: нечитаемая мета %s", meta_path.name)
            return None
        if meta.get("source") == "builtin_demo":
            demo_path = Path(meta.get("demo_path") or "")
            if not demo_path.exists():
                return None
            return DatasetSource(data=demo_path.read_bytes(), meta=meta)
        matches = [
            path
            for path in self.uploads_dir.glob(f"{fingerprint}.*")
            if not path.name.endswith(".meta.json")
        ]
        if not matches:
            return None
        return DatasetSource(data=matches[0].read_bytes(), meta=meta)

    def save_checkpoint_snapshot(
        self, run_id: str, checkpoint_id: str, dataframe: Optional[pd.DataFrame]
    ) -> bool:
        """Снимок данных чекпоинта (§12 п.4). CSV (pandas native) вместо
        рекомендованного Parquet: pyarrow в среде недоступен; отклонение
        изолировано здесь -- замена на to_parquet/read_parquet не меняет
        вызывателей. Без DataFrame -- False (снимка нет, ссылка есть)."""
        if dataframe is None:
            return False
        directory = self._checkpoints_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{checkpoint_id}.csv"
        dataframe.to_csv(path, index=False)
        return True

    def load_checkpoint_snapshot(self, run_id: str, checkpoint_id: str) -> Optional[pd.DataFrame]:
        path = self._checkpoints_dir(run_id) / f"{checkpoint_id}.csv"
        if not path.exists():
            return None
        try:
            return pd.read_csv(path)
        except (OSError, ValueError):
            logger.warning(
                "Dataset files: нечитаемый снимок чекпоинта %s", path, exc_info=True
            )
            return None

    def prune_checkpoints(self, run_id: str, keep: Iterable[str]) -> list[str]:
        """Оставляет снимки перечисленных чекпоинтов (§12 п.4: последние 5
        на run_id -- порядок определяется хранилищем запусков, не mtime).
        Возвращает удалённые id (для логов/тестов)."""
        keep_set = set(keep)
        directory = self._checkpoints_dir(run_id)
        if not directory.exists():
            return []
        removed: list[str] = []
        for path in directory.glob("*.csv"):
            checkpoint_id = path.stem
            if checkpoint_id not in keep_set:
                path.unlink(missing_ok=True)
                removed.append(checkpoint_id)
        return removed


_file_store: Optional[DatasetFileStore] = None


def get_dataset_file_store() -> DatasetFileStore:
    """Singleton файлового слоя (корень может задаваться env, поэтому
    создание через фабрику -- тесты переопределяют CISSTAT_DATA_DIR)."""
    global _file_store
    if _file_store is None:
        _file_store = DatasetFileStore(DatasetFileStore.default_root())
    return _file_store


def reset_dataset_file_store_for_testing() -> None:
    global _file_store
    _file_store = None


def stage_for_run_level_event(store: ResearchRunStore, run_id: str) -> str:
    """Стадия для run-level события (run_paused/run_resumed/
    checkpoint_saved -- валидны на ЛЮБОЙ стадии, §4.1): стадия последнего
    ФАКТА РЕШЕНИЯ запуска, при пустой трассе / только stage-level
    событиях -- 'upload' (происхождение запуска).

    PROGR-13-C (осознанная граница PROGR-13-B): прежняя версия брала
    хвост трассы (events[-1].stage) -- stage-level события
    (target_column_changed сеется авто-POST хука useTargetColumn на
    вкладке «Загрузка» со stage="validation", passport_captured,
    mode_changed, run_*) уводили штамп run-события на стадию, куда
    аналитик не заходил: «Пауза» после загрузки попадала в корпус
    слоя 2 как пауза НА ВАЛИДАЦИИ (тот же корень, что у дефекта 2
    Наставника, исправленного derive_last_active_stage в B1). Вывод
    -- единый движок (derive_last_decision_stage, гейт по ТИПУ факта
    через resolve_event_status -- единственную точку решения «узловой
    ли это факт», PROGR-13-A4; certified контракт E6 PROGR-5-CERT
    сохранён: backtest_run без узла -> "modeling").

    Импорт движка ЛЕНИВЫЙ (внутри функции): верхнеуровневый
    import app.core.node_status здесь создаёт цикл
    research_runs -> node_status -> pipeline_graph ->
    routers.session -> research_runs (подтверждён эмпирически в
    задаче; прецедент разрыва цикла ленивым импортом в модуле --
    modeling_session.py, forecasting_session.py). На момент вызова
    (обработка запроса) все модули графа уже загружены."""
    from app.core.node_status import derive_last_decision_stage

    return derive_last_decision_stage(store.list_events(run_id))
