# apps/api/delivery_outbox.py
"""
Восстановимая доставка и операции «Прогресса» (AUDIT-6B,
plan_progress_audit.md §17; контракт docs/progress_audit_contract.md
аддендум v1.5-6B §25; spec_progress_audit.md §8.3).

ЧЕТЫРЕ опоры контура:

1. **Реестр producers (п.1).** Гарантия «операция документирована»
   действует ТОЛЬКО для явно мигрированных required-путей
   (REQUIRED_PRODUCERS): строгие v2-карты статусов и run-level
   операции паузы/возобновления/чекпоинта/restore. Остальной сервис
   перечислен в ADVISORY_PRODUCERS: хук-зеркало после ответа (P09/P22 --
   честно best-effort, п.8), легаси-карты (compatibility mode),
   мутации DataFrame коррекций (unmigrated -- гарантия НЕ заявляется),
   наблюдения Наставника. Пустое слово «durable» на весь сервис не
   распространяется (риск/граница карточки §17).

2. **Durable outbox (п.4).** Обязательство доставки проекции живёт в
   ТОМ ЖЕ устойчивом хранилище, что ledger: Postgres -- таблица
   progress_delivery_outbox (миграция 0005, регистрация В транзакции
   commit_event_batch), Memory -- тот же контракт (паритет I8).
   Обычная очередь в памяти процесса и «недоказанная долговечность
   Redis» недостаточны. Crash ДО commit -- нет ни фактов, ни
   обязательства (атомарность); crash ПОСЛЕ -- обязательство остаётся
   и обрабатывается worker'ом.

3. **Worker (п.5/п.7).** run_delivery_recovery доставляет факты/
   проекции по operation_id (виды задач ограничены проекцией:
   DELIVERY_KINDS = {layer1_mirror} -- математические операции
   повторно НЕ запускаются). Повторный запуск безопасен (дедуп по
   event_id в слое 1). sweep_orphaned_checkpoints -- контролируемый
   staged cleanup внешних артефактов: DB-транзакция НЕ делает
   файловую запись атомарной, упавший commit оставляет staged-файл.

4. **Состояния (п.6/п.8).** Классификатор classify_operation различает
   not_executed / executed_documentation_pending /
   committed_projection_pending / delivered / failed -- без фиктивного
   rollback. Delivery-эндпоинты progress.py возвращают состояние
   операции с receipt и watermark (read-after-write); advisory-путь
   после ответа остаётся честно best-effort.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# ── Реестр producers (п.1: явный перечень гарантий) ──────────────────

# Required: «операция документирована» -- durable receipt + outbox-
# обязательство + восстановимая доставка. Паттерн ключа -- basis
# повтора по operation_id (п.5).
REQUIRED_PRODUCERS: dict[str, str] = {
    # Строгие v2-карты (AUDIT-2A): report:{run_id}:{report_id}.
    "progress_maps_v2": "report:{run_id}:{report_id}",
    # Run-level операции (мигрированы AUDIT-6B из advisory-пары
    # set_run_status/upsert_run + append_event в атомарный батч):
    # event:{run_id}:{event_id}.
    "runs.pause": "event:{run_id}:{event_id}",
    "runs.resume": "event:{run_id}:{event_id}",
    "runs.checkpoint": "event:{run_id}:{event_id}",
    "runs.restore": "event:{run_id}:{event_id}",
}

# Advisory: навигационная телеметрия и unmigrated-пути -- best-effort
# с ЧЕСТНЫМ состоянием (спека §8.3; контракт §3.6). Гарантия
# документирования на них НЕ распространяется.
ADVISORY_PRODUCERS: dict[str, str] = {
    # Зеркало хука после ответа (P09/P22): ответ уходит клиенту ДО
    # записи факта; loss совместим с HTTP 200 -- п.8 карточки §17.
    "trace_hook_mirror": (
        "after-response single-event mirror -- best-effort (P09/P22); "
        "advisory по п.8"
    ),
    # Легаси-карты без v2-конверта (compatibility mode, контракт §19.5):
    # слой 1 первичен, зеркало слоя 2 -- best-effort батч AUDIT-6A.
    "progress_maps_legacy": (
        "legacy map path (compatibility mode) -- best-effort зеркало"
    ),
    # Мутации научных данных коррекций (unmigrated): факт документируется
    # через хук; при отказе слоя 2 состояние операции --
    # executed_documentation_pending (DataFrame уже изменён, фиктивный
    # rollback не сообщается, п.6). Миграция -- отдельное решение.
    "corrections_dataframe": (
        "session.py corrections -- документирование best-effort через хук; "
        "при отказе слоя 2 -- executed_documentation_pending"
    ),
    # Телеметрия Наставника (частота вызовов, не уникальные решения).
    "mentor_observations": "наблюдения Наставника -- телеметрия best-effort",
}

# Виды задач доставки (п.5: retry доставляет факт/проекцию, НЕ запускает
# повторно математическую операцию -- реестр физически ограничен
# проекционными kind'ами).
DELIVERY_KINDS: frozenset[str] = frozenset({"layer1_mirror"})

# ── Состояния ────────────────────────────────────────────────────────

# Состояние обязательства в outbox.
STATE_PENDING = "pending"
STATE_DELIVERED = "delivered"
STATE_FAILED = "failed"

# Состояние операции для вызывающего (п.6: честная таксономия ошибок).
OP_NOT_EXECUTED = "not_executed"                        # до хранилища не дошло
OP_EXECUTED_DOCUMENTATION_PENDING = (                    # исполнено, не задокументировано
    "executed_documentation_pending"
)
OP_COMMITTED_PROJECTION_PENDING = (                      # ledger committed, проекция ждёт
    "committed_projection_pending"
)
OP_DELIVERED = "delivered"                               # committed + проекция доставлена
OP_FAILED = "failed"                                     # бюджет попыток исчерпан

# Бюджет попыток доставки по умолчанию и база экспоненциального
# backoff'а worker'а (30s * 2**(attempts-1), кэп 1 час).
DEFAULT_MAX_ATTEMPTS = 5
RETRY_BACKOFF_BASE_SECONDS = 30
RETRY_BACKOFF_CAP_SECONDS = 3600

# Безопасный размер last_error (operational log без сырых payload'ов).
_LAST_ERROR_MAX = 500


def retry_backoff_seconds(attempts: int) -> int:
    """Экспоненциальный backoff после attempts-й неудачи (1 -> 30s)."""
    seconds = RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1))
    return min(seconds, RETRY_BACKOFF_CAP_SECONDS)


# ── Задача доставки ──────────────────────────────────────────────────


@dataclass(frozen=True)
class DeliveryTask:
    """Обязательство доставки проекции (п.4): регистрируется В транзакции
    commit'а фактов и переживает потерю процесса/cache. Payload содержит
    ТОЛЬКО уже committed факты (повтор доставки не повторяет научную
    операцию, п.5)."""

    operation_id: str                     # report_id либо event_id продюсера
    idempotency_key: str                  # ключ commit'а (связь с receipt)
    run_id: str
    kind: str = "layer1_mirror"
    payload: dict[str, Any] = field(default_factory=dict)
    state: str = STATE_PENDING
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    next_attempt_at: Optional[str] = None  # None -- к доставке немедленно
    last_error: Optional[str] = None
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())
    delivered_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "idempotency_key": self.idempotency_key,
            "run_id": self.run_id,
            "kind": self.kind,
            "payload": self.payload,
            "state": self.state,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "next_attempt_at": self.next_attempt_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "delivered_at": self.delivered_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DeliveryTask":
        return cls(
            operation_id=str(raw.get("operation_id") or ""),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            run_id=str(raw.get("run_id") or ""),
            kind=str(raw.get("kind") or "layer1_mirror"),
            payload=dict(raw.get("payload") or {}),
            state=str(raw.get("state") or STATE_PENDING),
            attempts=int(raw.get("attempts") or 0),
            max_attempts=int(raw.get("max_attempts") or DEFAULT_MAX_ATTEMPTS),
            next_attempt_at=(
                str(raw["next_attempt_at"])
                if raw.get("next_attempt_at")
                else None
            ),
            last_error=(
                str(raw["last_error"]) if raw.get("last_error") else None
            ),
            created_at=str(raw.get("created_at") or _now_iso()),
            updated_at=str(raw.get("updated_at") or _now_iso()),
            delivered_at=(
                str(raw["delivered_at"]) if raw.get("delivered_at") else None
            ),
        )


def layer1_mirror_task(
    *,
    session_id: str,
    run_id: str,
    events: Iterable[Any],
    operation_id: str,
    idempotency_key: str = "",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    next_attempt_at: Optional[str] = None,
) -> DeliveryTask:
    """Обязательство «доставить committed события в слой 1 сессии»
    (восстанавливаемая проекция Redis, п.2). Payload -- to_dict() формы
    уже committed событий; delivery по operation_id (п.5)."""
    payload = {
        "session_id": str(session_id),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in events
        ],
    }
    return DeliveryTask(
        operation_id=str(operation_id),
        idempotency_key=str(idempotency_key),
        run_id=str(run_id),
        kind="layer1_mirror",
        payload=payload,
        max_attempts=max_attempts,
        next_attempt_at=next_attempt_at,
    )


def bind_idempotency_key(task: DeliveryTask, idempotency_key: str) -> DeliveryTask:
    """Связывает обязательство с ключом commit'а (вызывается store'ом при
    регистрации в транзакции, если продюсер не передал ключ): delivery-
    эндпоинт находит receipt обязательства по этой связи (п.8)."""
    if task.idempotency_key or not idempotency_key:
        return task
    return replace(task, idempotency_key=str(idempotency_key))


def classify_operation(
    receipt: Any,
    task: Any,
    *,
    mutation_applied: bool = False,
) -> str:
    """Честное состояние операции (п.6). receipt -- CommitReceipt либо
    None; task -- DeliveryTask либо None; mutation_applied -- научная
    мутация уже применена вне ledger (класс коррекций: фиктивный
    rollback не сообщается)."""
    if task is not None and task.state == STATE_DELIVERED:
        return OP_DELIVERED
    if task is not None and task.state == STATE_FAILED:
        # Исчерпанный бюджет -- честный failed независимо от receipt:
        # тихое исчезновение обязательства запрещено (п.6).
        return OP_FAILED
    if receipt is not None:
        return OP_COMMITTED_PROJECTION_PENDING
    if task is not None:
        # Защитная ветка: обязательство без receipt по построению
        # невозможно (регистрация -- в транзакции commit'а); честно
        # сообщаем ожидающее, а не «успех».
        return OP_COMMITTED_PROJECTION_PENDING
    if mutation_applied:
        return OP_EXECUTED_DOCUMENTATION_PENDING
    return OP_NOT_EXECUTED


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_error(error: str) -> str:
    text = str(error or "")
    if len(text) > _LAST_ERROR_MAX:
        return text[: _LAST_ERROR_MAX - 3] + "..."
    return text


# ── Postgres: общие SQL-константы (таблица 0005) ─────────────────────

OUTBOX_TABLE = "progress_delivery_outbox"

OUTBOX_INSERT_SQL = f"""
INSERT INTO {OUTBOX_TABLE}
    (operation_id, idempotency_key, run_id, kind, payload, state,
     attempts, max_attempts, next_attempt_at, last_error,
     created_at, updated_at, delivered_at)
VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (operation_id) DO NOTHING
"""

_OUTBOX_SELECT_COLUMNS = (
    "operation_id, idempotency_key, run_id, kind, payload, state, "
    "attempts, max_attempts, next_attempt_at, last_error, "
    "created_at, updated_at, delivered_at"
)


def outbox_row_params(task: DeliveryTask) -> tuple[Any, ...]:
    """Параметры INSERT (используются И inline-регистрацией commit'а в
    research_runs.py -- та же транзакция, И standalone-регистрацией)."""

    def _ts(value: Optional[str]) -> Any:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    return (
        task.operation_id,
        task.idempotency_key,
        task.run_id,
        task.kind,
        json.dumps(task.payload, ensure_ascii=False, sort_keys=True, default=str),
        task.state,
        task.attempts,
        task.max_attempts,
        _ts(task.next_attempt_at),
        task.last_error,
        _ts(task.created_at),
        _ts(task.updated_at),
        _ts(task.delivered_at),
    )


def _outbox_task_from_row(row: tuple[Any, ...]) -> DeliveryTask:
    def _iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    payload = row[4]
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}
    return DeliveryTask(
        operation_id=str(row[0]),
        idempotency_key=str(row[1] or ""),
        run_id=str(row[2] or ""),
        kind=str(row[3] or "layer1_mirror"),
        payload=dict(payload or {}),
        state=str(row[5] or STATE_PENDING),
        attempts=int(row[6] or 0),
        max_attempts=int(row[7] or DEFAULT_MAX_ATTEMPTS),
        next_attempt_at=_iso(row[8]),
        last_error=row[9] if row[9] is None else str(row[9]),
        created_at=_iso(row[10]) or _now_iso(),
        updated_at=_iso(row[11]) or _now_iso(),
        delivered_at=_iso(row[12]),
    )


# ── Контракт outbox ──────────────────────────────────────────────────


class DeliveryOutbox:
    """Контракт обязательств доставки (паритет Memory/Postgres, I8).

    register() вызывается ВНУТРИ транзакции commit'а фактов (для
    Postgres -- на том же соединении; Memory -- под тем же замком
    store'а): обязательство атомарно фактам. mark_* -- операции
    worker'а/эндпоинтов (свои транзакции)."""

    def register(self, task: DeliveryTask) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_task(self, operation_id: str) -> Optional[DeliveryTask]:  # pragma: no cover
        raise NotImplementedError

    def list_due(self, now: str, limit: int = 100) -> list[DeliveryTask]:  # pragma: no cover
        raise NotImplementedError

    def list_by_run(self, run_id: str) -> list[DeliveryTask]:  # pragma: no cover
        raise NotImplementedError

    def mark_delivered(self, operation_id: str, *, delivered_at: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def mark_failed(
        self,
        operation_id: str,
        *,
        error: str,
        next_attempt_at: str,
        at: str,
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    def backlog(self) -> dict[str, int]:  # pragma: no cover
        raise NotImplementedError


class MemoryDeliveryOutbox(DeliveryOutbox):
    """Memory-реализация (паритет Postgres: дедуп по operation_id,
    глубокие копии, тот же контракт list_due/mark_*/backlog)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, DeliveryTask] = {}

    def register(self, task: DeliveryTask) -> None:
        with self._lock:
            if task.operation_id in self._tasks:
                return  # дедуп: обязательство уже зарегистрировано
            self._tasks[task.operation_id] = replace(
                task, payload=json.loads(json.dumps(task.payload, default=str))
            )

    def get_task(self, operation_id: str) -> Optional[DeliveryTask]:
        with self._lock:
            task = self._tasks.get(operation_id)
        if task is None:
            return None
        return replace(task, payload=json.loads(json.dumps(task.payload)))

    def list_due(self, now: str, limit: int = 100) -> list[DeliveryTask]:
        with self._lock:
            tasks = [replace(t, payload=json.loads(json.dumps(t.payload)))
                     for t in self._tasks.values()]
        due = [
            task
            for task in tasks
            if task.state == STATE_PENDING
            and (task.next_attempt_at is None or task.next_attempt_at <= now)
        ]
        due.sort(key=lambda t: (t.next_attempt_at or "", t.operation_id))
        return due[: max(0, limit)]

    def list_by_run(self, run_id: str) -> list[DeliveryTask]:
        with self._lock:
            tasks = [replace(t, payload=json.loads(json.dumps(t.payload)))
                     for t in self._tasks.values()]
        matched = [task for task in tasks if task.run_id == run_id]
        matched.sort(key=lambda t: (t.created_at, t.operation_id))
        return matched

    def mark_delivered(self, operation_id: str, *, delivered_at: str) -> bool:
        with self._lock:
            task = self._tasks.get(operation_id)
            if task is None:
                return False
            self._tasks[operation_id] = replace(
                task, state=STATE_DELIVERED,
                delivered_at=delivered_at, updated_at=delivered_at,
            )
            return True

    def mark_failed(
        self,
        operation_id: str,
        *,
        error: str,
        next_attempt_at: str,
        at: str,
    ) -> bool:
        with self._lock:
            task = self._tasks.get(operation_id)
            if task is None:
                return False
            attempts = task.attempts + 1
            state = (
                STATE_FAILED
                if attempts >= task.max_attempts
                else STATE_PENDING
            )
            self._tasks[operation_id] = replace(
                task,
                state=state,
                attempts=attempts,
                last_error=_clip_error(error),
                next_attempt_at=(
                    next_attempt_at if state == STATE_PENDING else task.next_attempt_at
                ),
                updated_at=at,
            )
            return True

    def backlog(self) -> dict[str, int]:
        with self._lock:
            tasks = list(self._tasks.values())
        counts = {STATE_PENDING: 0, STATE_DELIVERED: 0, STATE_FAILED: 0}
        for task in tasks:
            counts[task.state] = counts.get(task.state, 0) + 1
        return counts


class PostgresDeliveryOutbox(DeliveryOutbox):
    """Postgres-реализация (таблица progress_delivery_outbox, миграция
    0005). Регистрация В транзакции commit'а выполняется
    research_runs.commit_event_batch на ТОМ ЖЕ соединении
    (register_with); собственные операции -- на своих соединениях."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    # -- регистрация внутри чужой транзакции (commit_event_batch в
    #    research_runs.py использует OUTBOX_INSERT_SQL +
    #    outbox_row_params на ТОМ ЖЕ соединении) --

    # -- собственные операции (worker / эндпоинты) --

    def register(self, task: DeliveryTask) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(OUTBOX_INSERT_SQL, outbox_row_params(task))
            conn.commit()

    def get_task(self, operation_id: str) -> Optional[DeliveryTask]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_OUTBOX_SELECT_COLUMNS} FROM {OUTBOX_TABLE} "
                "WHERE operation_id = %s",
                (operation_id,),
            )
            row = cur.fetchone()
        return _outbox_task_from_row(row) if row is not None else None

    def list_due(self, now: str, limit: int = 100) -> list[DeliveryTask]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_OUTBOX_SELECT_COLUMNS} FROM {OUTBOX_TABLE} "
                "WHERE state = %s "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= %s) "
                "ORDER BY next_attempt_at NULLS FIRST, operation_id LIMIT %s",
                (STATE_PENDING, _ts_to_db(now), limit),
            )
            rows = cur.fetchall()
        return [_outbox_task_from_row(row) for row in rows]

    def list_by_run(self, run_id: str) -> list[DeliveryTask]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_OUTBOX_SELECT_COLUMNS} FROM {OUTBOX_TABLE} "
                "WHERE run_id = %s ORDER BY created_at, operation_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [_outbox_task_from_row(row) for row in rows]

    def mark_delivered(self, operation_id: str, *, delivered_at: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {OUTBOX_TABLE} SET state = %s, delivered_at = %s, "
                "updated_at = %s WHERE operation_id = %s",
                (STATE_DELIVERED, _ts_to_db(delivered_at),
                 _ts_to_db(delivered_at), operation_id),
            )
            updated = cur.rowcount
            conn.commit()
        return updated > 0

    def mark_failed(
        self,
        operation_id: str,
        *,
        error: str,
        next_attempt_at: str,
        at: str,
    ) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT state, attempts, max_attempts FROM {OUTBOX_TABLE} "
                "WHERE operation_id = %s FOR UPDATE",
                (operation_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return False
            attempts = int(row[1] or 0) + 1
            max_attempts = int(row[2] or DEFAULT_MAX_ATTEMPTS)
            state = (
                STATE_FAILED if attempts >= max_attempts else STATE_PENDING
            )
            cur.execute(
                f"UPDATE {OUTBOX_TABLE} SET state = %s, attempts = %s, "
                "last_error = %s, "
                "next_attempt_at = CASE WHEN %s = %s THEN next_attempt_at "
                "ELSE %s END, updated_at = %s WHERE operation_id = %s",
                (
                    state, attempts, _clip_error(error),
                    state, STATE_FAILED, _ts_to_db(next_attempt_at),
                    _ts_to_db(at), operation_id,
                ),
            )
            conn.commit()
        return True

    def backlog(self) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT state, COUNT(*) FROM {OUTBOX_TABLE} GROUP BY state"
            )
            rows = cur.fetchall()
        counts = {STATE_PENDING: 0, STATE_DELIVERED: 0, STATE_FAILED: 0}
        for state, count in rows:
            counts[str(state)] = int(count or 0)
        return counts


def _ts_to_db(value: str) -> Any:
    """ISO-строка -> datetime для psycopg (тот же контракт, что
    research_runs._ts_to_db; локальная копия -- разрыв цикла импорта:
    research_runs импортирует этот модуль)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ── Worker восстановления (п.5/п.7) ──────────────────────────────────


def deliver_layer1_mirror(task: DeliveryTask, session_store: Any) -> str:
    """Доставка committed событий в слой 1 сессии (восстанавливаемая
    проекция, п.2). Идемпотентна по event_id («worker дважды» -- одна
    копия). Сессия отсутствует (cache потерян) -- "session_absent":
    факт остаётся в ledger (он авторитетен), полная реконструкция
    cache -- путь restore_run (полный ledger сеет слой 1, §5.3)."""
    payload = task.payload or {}
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        raise ValueError(f"layer1_mirror {task.operation_id}: session_id пуст")
    session = session_store.get(session_id)
    if session is None:
        return "session_absent"
    existing_ids = {
        item.get("event_id")
        for item in session.pipeline_trace
        if isinstance(item, dict)
    }
    appended = 0
    for raw in payload.get("events") or []:
        event_id = raw.get("event_id")
        if not event_id or event_id in existing_ids:
            continue  # дедуп: факт уже в навигационном слое
        from apps.api.trace_events import TraceEvent

        session.append_trace_event(TraceEvent.from_dict(raw))
        existing_ids.add(event_id)
        appended += 1
    if appended:
        session_store.save(session)
    return "delivered"


def run_delivery_recovery(
    run_store: Any,
    *,
    session_store: Any = None,
    now: Optional[datetime] = None,
    limit: int = 100,
) -> dict[str, int]:
    """Один проход восстановления доставки (п.5/п.7): доставляет due-
    обязательства по operation_id, честно учитывает попытки (backoff,
    бюджет). Повторный запуск безопасен. Возвращает сводку прогонa:
    due/delivered/session_absent/failed -- operational-сводка для логов
    (связь с фактом -- operation_id в каждой записи, не сырые payload'ы)."""
    if session_store is None:
        from apps.api.session_store import get_session_store

        session_store = get_session_store()
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = moment.isoformat()
    due = run_store.delivery_outbox.list_due(now=now_iso, limit=limit)
    summary = {"due": len(due), "delivered": 0, "session_absent": 0, "failed": 0}
    for task in due:
        try:
            if task.kind == "layer1_mirror":
                outcome = deliver_layer1_mirror(task, session_store)
            else:
                # Реестр видов ограничен проекцией (п.5): неизвестный
                # kind -- отказ, операция не изобретается.
                raise ValueError(f"неизвестный kind доставки: {task.kind!r}")
        except Exception as exc:
            next_at = (
                moment + timedelta(seconds=retry_backoff_seconds(task.attempts + 1))
            ).isoformat()
            run_store.delivery_outbox.mark_failed(
                task.operation_id, error=str(exc),
                next_attempt_at=next_at, at=now_iso,
            )
            summary["failed"] += 1
            logger.warning(
                "Delivery outbox: задача %s (%s) не доставлена -- попытка %s/%s",
                task.operation_id, task.kind,
                task.attempts + 1, task.max_attempts, exc_info=True,
            )
            continue
        run_store.delivery_outbox.mark_delivered(
            task.operation_id, delivered_at=now_iso
        )
        if outcome == "session_absent":
            summary["session_absent"] += 1
            logger.info(
                "Delivery outbox: задача %s -- сессия отсутствует в cache; "
                "факт остаётся в ledger, реконструкция слоя 1 -- restore_run",
                task.operation_id,
            )
        else:
            summary["delivered"] += 1
    return summary


def sweep_orphaned_checkpoints(
    run_store: Any,
    file_store: Any,
    *,
    run_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """Staged cleanup внешних артефактов (п.7): DB-транзакция НЕ делает
    файловую запись атомарной -- упавший commit чекпоинта оставляет
    снимок без ссылки. Sweep удаляет файлы, на которые не ссылается ни
    один чекпоинт ledger'а. Повторный запуск безопасен (no-op)."""
    ids = list(run_ids) if run_ids is not None else [
        run.run_id for run in run_store.list_runs()
    ]
    removed: list[str] = []
    for run_id in ids:
        referenced = {
            checkpoint.checkpoint_id
            for checkpoint in run_store.list_checkpoints(run_id)
        }
        for path in file_store.checkpoint_snapshot_files(run_id):
            if path.stem not in referenced:
                if file_store.remove_checkpoint_snapshot(run_id, path.stem):
                    removed.append(path.stem)
                    logger.warning(
                        "Delivery outbox: staged cleanup -- снимок %s/%s "
                        "без ссылки в ledger удалён",
                        run_id, path.stem,
                    )
    return removed
