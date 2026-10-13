# scripts/prograudit6bcert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-6B-CERT.

Объект: коммит 8b309eb (PROGR-AUDIT-6B -- восстановимая доставка и
операции, plan_progress_audit.md §17; контракт
docs/progress_audit_contract.md аддендум v1.5-6B §25):
  * реестр producers required/advisory (п.1) -- гарантия «durable»
    НЕ распространяется на advisory;
  * durable outbox В транзакции commit'а (п.3/п.4): crash до commit --
    нет ни фактов, ни обязательства; после -- обязательство переживает
    потерю процесса/cache;
  * run-level операции паузы/возобновления/чекпоинта/restore --
    атомарный батч вместо advisory-пары (seam P08/P10 устранён);
  * worker восстановления по operation_id (п.5): дедуп event_id,
    backoff/бюджет, unknown kind -- отказ без изобретения операции;
  * staged cleanup внешних артефактов (п.7): sweep сирот-снимков,
    повтор безопасен;
  * delivery-эндпоинты read-after-write (п.6/п.8): not_executed /
    executed_documentation_pending / committed_projection_pending /
    delivered / failed -- фиктивный rollback не сообщается.

Принцип «оракулы на своих данных»: корпус сертификатора ДИЗЪЮКТЕН
оракулу исполнителя (tests/api/test_progress_audit_6b.py: CSV
«date,value,humidity» n=150 от 2026-02-01, run-идентификаторы
RUN-6B*, отчёты report-6b-*, операции op-*, ключи K-6B-*):
  * свой CSV-корпус: «period,revenue,temp» ПОДЕННО 2025-01-01..
    2025-03-29 (88 суток, два числовых столбца + дата);
  * свои идентификаторы: запуски RUN-C6B-*, отчёты rep-cert6b-*,
    операции op-c6b-*, ключи cert6b-key-*;
  * свои метки отказов «Cert-6B: ...» (last_error), свои параметры
    бюджетов (max_attempts=2/7), свои метки времени для list_due;
  * свои наблюдательные методы, ОТСУТСТВУЮЩИЕ у исполнителя:
    -- полная серия backoff-математики 1..12 с пином кэпа (у
       исполнителя математики backoff нет);
    -- полевая верификация roundtrip DeliveryTask (13 полей,
       включая max_attempts/next_attempt_at/last_error) и изоляция
       глубоких копий (мутация прочитанного payload не портит store),
       first-wins дедуп register;
    -- трёхкейсная семантика bind_idempotency_key (привязка пустого,
       НЕ-перезапись непустого, no-op пустого аргумента);
    -- НОВОЕ направление отказа атомарности: отказ outbox-INSERT В
       транзакции commit'а на ЖИВОМ PostgreSQL (исполнитель инъекцией
       ломал подготовку СОБЫТИЙ -- шов _prepare_stored_event; шов
       обязательства не проверялся) -> полный откат: ноль событий,
       ноль строк outbox, нет receipt, метаданные запуска прежние;
    -- НОВЫЙ fault-timeline restore: commit прошёл, сохранение слоя 1
       (второй save) отказало -> 500, факт и обязательство в ledger,
       worker ДОСТАВЛЯЕТ проекцию в сессию, сохранённую первым save
       («операция записана, проекция ещё не обновилась» -- RED-
       карточка §17 на run-level пути; исполнитель проверял отказ ДО
       commit'а и отказ cache на картах);
    -- CAS-конфликт на уровне store с обязательством в батче:
       CommitConflictError до записи -- ноль событий/обязательств;
    -- дедуп-рекоммит ПОСЛЕ доставки: обязательство НЕ сбрасывается
       в pending, события не задваиваются, backlog честен;
    -- sweep-скоупинг: сирот удалён, ССЫЛАЕМЫЙ снимок выжил, повтор
       no-op, явный run_ids-список сужает периметр;
    -- пин НЕпубличности payload в delivery-эндпоинтах (в ответе нет
       копий событий -- они читаются через /trace);
    -- таблица ПРЕДШЕСТВОВАНИЯ classify_operation (delivered/failed
       старше receipt; defensive-ветка «обязательство без receipt»
       честно committed_projection_pending, не «успех»).

Канал проверки: самодостаточный EXIT-код (0 = все PASS; SKIP живут
отдельно -- живой PG без DSN).

Группы: ENV (реестр/константы), OUT (контракт outbox), ATOM
(атомарность батча), MAP (required-доставка карт), RUN (run-level
операции), SWEEP (staged cleanup), EP (эндпоинты/классификатор),
CTRL (контролы базы -- GREEN и на базе), PG (живой PostgreSQL).

Запуск: python3 scripts/prograudit6bcert_oracles.py [--protocol PATH]
        (CISSTAT_CERT6B_PG=1 -- автоподъём живого pgserver для PG-группы)
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Чистая изоляция окружения ДО импортов продукта (документированный
# средовой класс песочницы: DATABASE_URL=file:… ломает psycopg-парсер).
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

PROTOCOL_LINES: list[str] = []
FAILURES: list[str] = []
PASSES: int = 0
SKIPS: int = 0


def _log(msg: str) -> None:
    print(msg)
    PROTOCOL_LINES.append(msg)


class OracleFail(AssertionError):
    """Честный отказ оракула (различим от неожиданного исключения)."""


def oracle(name: str, *, needs_pg: bool = False):
    """Декоратор-харнесс: полная изоляция окружения на каждый оракул."""

    def wrap(fn):
        def run():
            global PASSES, SKIPS
            tmp = tempfile.mkdtemp(prefix="cert6b-oracle-")
            os.environ["CISSTAT_DATA_DIR"] = tmp
            from apps.api import research_runs as rr
            from apps.api.session_store import (
                reset_session_store_for_testing,
            )

            rr.reset_research_run_store_for_testing()
            rr.reset_dataset_file_store_for_testing()
            reset_session_store_for_testing()
            try:
                if needs_pg:
                    if dox is None:  # capability-check раньше DSN: на базе -- честный FAIL
                        raise OracleFail(
                            "возможность AUDIT-6B отсутствует "
                            "(apps.api.delivery_outbox недоступен -- база 56f431c?)"
                        )
                    dsn = os.environ.get("CISSTAT_TEST_PG_DSN", "")
                    if not dsn:
                        SKIPS += 1
                        _log(f"  SKIP {name} (нет CISSTAT_TEST_PG_DSN)")
                        return
                fn()
            except OracleFail as exc:
                FAILURES.append(f"{name}: {exc}")
                _log(f"  FAIL {name}: {exc}")
            except Exception as exc:  # неожиданное исключение = FAIL
                FAILURES.append(f"{name}: UNEXPECTED {exc!r}")
                _log(f"  FAIL {name}: UNEXPECTED {exc!r}")
                traceback.print_exc()
            else:
                PASSES += 1
                _log(f"  ok   {name}")
            finally:
                rr.reset_research_run_store_for_testing()
                rr.reset_dataset_file_store_for_testing()
                reset_session_store_for_testing()

        run.__name__ = fn.__name__
        run._oracle_name = name
        run._needs_pg = needs_pg
        return run

    return wrap


# ── Символы AUDIT-6B отсутствуют на базе 56f431c (до задачи) ─────────

try:  # noqa: SIM105
    from apps.api import delivery_outbox as dox
except ImportError:  # база до AUDIT-6B
    dox = None  # type: ignore[assignment]


def _require_6b() -> None:
    if dox is None:
        raise OracleFail(
            "возможность AUDIT-6B отсутствует (apps.api.delivery_outbox "
            "недоступен -- база 56f431c?)"
        )


# ── СВОИ данные сертификатора (дизъюнктны исполнителю) ───────────────

# Поденный корпус 2025: 88 суток (январь 31 + февраль 28 + март 29),
# столбцы period/revenue/temp. revenue -- тренд + пилообразная
# недельная компонента; temp -- гладкий синус.
_JAN = [f"2025-01-{d:02d}" for d in range(1, 32)]
_FEB = [f"2025-02-{d:02d}" for d in range(1, 29)]
_MAR = [f"2025-03-{d:02d}" for d in range(1, 30)]
_DAYS = _JAN + _FEB + _MAR
_REVENUE = [500.0 + 2.0 * i + 3.0 * (i % 5) for i in range(88)]
_TEMP = [20.0 + 5.0 * ((i % 12) / 12.0) for i in range(88)]
CSV_CERT6B = "period,revenue,temp\n" + "".join(
    f"{d},{r:.2f},{t:.2f}\n" for d, r, t in zip(_DAYS, _REVENUE, _TEMP)
)

RUN_PREFIX = "RUN-C6B"
REPORT_PREFIX = "rep-cert6b"
CERT_LABEL = "Cert-6B"


def _client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    return TestClient(app)


def _upload_own(client) -> tuple[str, str]:
    """Свой корпус -> запуск: (run_id, context_id) из /progress/trace."""
    import io

    resp = client.post(
        "/v1/internal/upload",
        files={"file": (
            "cert6b_revenue_temp_88d.csv",
            io.BytesIO(CSV_CERT6B.encode()),
            "text/csv",
        )},
    )
    assert resp.status_code == 200, resp.text
    trace = client.get("/v1/progress/trace").json()
    run_id = str(trace.get("run_id") or "")
    context_id = str(trace.get("context_id") or "")
    assert run_id and context_id, (
        "seed Cert-6B: загрузка обязана фиксировать запуск и контекст"
    )
    return run_id, context_id


def _layer1_count(client, event_type: str) -> int:
    """Свой счётчик слоя 1 (по cookie клиента, без хелперов исполнителя)."""
    from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

    session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
    session = get_session_store().get(session_id)
    if session is None:
        return 0
    return sum(
        1
        for item in session.pipeline_trace
        if isinstance(item, dict) and item.get("event_type") == event_type
    )


def _my_run(run_id: str, **kw):
    from apps.api.research_runs import ResearchRun

    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "run_id": run_id,
        "session_id": "sess-cert6b",
        "dataset_fingerprint": "c" * 64,
        "dataset_name": "cert6b_revenue_temp_88d.csv",
        "created_at": now,
        "last_active_at": now,
    }
    defaults.update(kw)
    return ResearchRun(**defaults)


def _events(run_id: str, count: int, event_type: str = "upload_stop_status",
            node_id: str = "structure_confirmed"):
    from apps.api.trace_events import make_trace_event

    return tuple(
        make_trace_event(
            event_type, stage="upload", node_id=node_id, run_id=run_id, idx=i,
        )
        for i in range(count)
    )


def _mirror_task(run_id: str, events, operation_id: str, *,
                 session_id: str = "sess-cert6b", **kw):
    _require_6b()
    return dox.layer1_mirror_task(
        session_id=session_id,
        run_id=run_id,
        events=list(events),
        operation_id=operation_id,
        **kw,
    )


def _task_of(store, operation_id: str):
    _require_6b()
    return store.delivery_outbox.get_task(operation_id)


# ── свои швы отказа (независимая реализация, не хелперы исполнителя) ──


@contextmanager
def _redis_semantics_with_save_fault(nth: int):
    """Redis-семантика слоя 1 с отказом n-го SET (честная симуляция):
    серверный документ -- ОТДЕЛЬНЫЙ снимок на каждый успешный save
    (write-copy: Redis SET сериализует состояние момента), читатели
    получают копии (read-copy), отказ save НЕ меняет серверный документ
    (незавершённые мутации локального объекта не видны следующему
    get()). Ревизионная логика оригинала сохранена (SessionConflict)."""
    from apps.api.session_store import MemorySessionStore, SessionConflictError

    orig_save = MemorySessionStore.save
    orig_get = MemorySessionStore.get
    orig_goc = MemorySessionStore.get_or_create
    state = {"n": 0, "sessions": []}

    def redis_save(self, session):
        state["n"] += 1
        state["sessions"].append(getattr(session, "session_id", ""))
        if state["n"] == nth:
            raise RuntimeError(
                f"{CERT_LABEL}: injected cache save failure #{nth}"
            )
        current = self._sessions.get(session.session_id)
        if (current is not None and current is not session
                and current.storage_revision != session.storage_revision):
            raise SessionConflictError(
                f"Stale session revision {session.storage_revision}; "
                f"current revision is {current.storage_revision}"
            )
        session.touch()
        session.storage_revision += 1
        # Redis-семантика: серверный документ -- снимок момента SET
        self._sessions[session.session_id] = deepcopy(session)

    def redis_get(self, session_id):
        stored = orig_get(self, session_id)
        return deepcopy(stored) if stored is not None else None

    def redis_goc(self, session_id):
        stored = orig_goc(self, session_id)
        return deepcopy(stored) if stored is not None else None

    MemorySessionStore.save = redis_save          # type: ignore[method-assign]
    MemorySessionStore.get = redis_get            # type: ignore[method-assign]
    MemorySessionStore.get_or_create = redis_goc  # type: ignore[method-assign]
    try:
        yield state
    finally:
        MemorySessionStore.save = orig_save           # type: ignore[method-assign]
        MemorySessionStore.get = orig_get             # type: ignore[method-assign]
        MemorySessionStore.get_or_create = orig_goc   # type: ignore[method-assign]


@contextmanager
def _fail_save_on_nth(nth: int):
    """Отказ сохранения слоя 1 на n-м вызове (транзиентный сбой cache)."""
    from apps.api.session_store import MemorySessionStore

    orig = MemorySessionStore.save
    state = {"n": 0, "sessions": []}

    def failing(self, session):
        state["n"] += 1
        state["sessions"].append(getattr(session, "session_id", ""))
        if state["n"] == nth:
            raise RuntimeError(f"{CERT_LABEL}: injected cache save failure #{nth}")
        return orig(self, session)

    MemorySessionStore.save = failing  # type: ignore[method-assign]
    try:
        yield state
    finally:
        MemorySessionStore.save = orig  # type: ignore[method-assign]


@contextmanager
def _patch_attr(obj, name: str, replacement):
    orig = getattr(obj, name)
    setattr(obj, name, replacement)
    try:
        yield
    finally:
        setattr(obj, name, orig)


def _pg_fresh_store():
    """Живой PostgreSQL: чистая схема (DROP SCHEMA CASCADE) + миграции
    0001..0005 -> PostgresResearchRunStore. Тот же контракт
    CISSTAT_TEST_PG_DSN, что у исполнителя/CI."""
    import psycopg

    from apps.api.research_runs import (
        PostgresResearchRunStore,
        run_migrations,
    )

    dsn = os.environ["CISSTAT_TEST_PG_DSN"]
    conn = psycopg.connect(dsn, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    conn.commit()
    run_migrations(conn)
    conn.close()
    return PostgresResearchRunStore(dsn=dsn)


# ══ 1. ENV: реестр producers, константы, математика backoff ══════════


@oracle("O-ENV-1 реестр producers: точные множества, дизъюнктность, "
        "паттерны ключей, обоснования advisory (§25.1)")
def o_env_1_registry():
    _require_6b()
    required = {
        "progress_maps_v2": "report:{run_id}:{report_id}",
        "runs.pause": "event:{run_id}:{event_id}",
        "runs.resume": "event:{run_id}:{event_id}",
        "runs.checkpoint": "event:{run_id}:{event_id}",
        "runs.restore": "event:{run_id}:{event_id}",
    }
    advisory = {
        "trace_hook_mirror",
        "progress_maps_legacy",
        "corrections_dataframe",
        "mentor_observations",
    }
    if dict(dox.REQUIRED_PRODUCERS) != required:
        raise OracleFail(
            f"REQUIRED_PRODUCERS != контракт §25.1: {dox.REQUIRED_PRODUCERS}"
        )
    if set(dox.ADVISORY_PRODUCERS) != advisory:
        raise OracleFail(
            f"ADVISORY_PRODUCERS != контракт §25.1: {set(dox.ADVISORY_PRODUCERS)}"
        )
    overlap = set(dox.REQUIRED_PRODUCERS) & set(dox.ADVISORY_PRODUCERS)
    if overlap:
        raise OracleFail(f"пересечение required/advisory запрещено: {overlap}")
    for producer, justification in dox.ADVISORY_PRODUCERS.items():
        if not isinstance(justification, str) or len(justification) < 10:
            raise OracleFail(
                f"advisory {producer}: обоснование пустое/декоративное"
            )
    for producer, pattern in dox.REQUIRED_PRODUCERS.items():
        if producer == "progress_maps_v2":
            if pattern != "report:{run_id}:{report_id}":
                raise OracleFail(f"{producer}: паттерн ключа {pattern!r}")
        elif not pattern.startswith("event:{run_id}:{event_id}"):
            raise OracleFail(f"{producer}: паттерн ключа {pattern!r}")


@oracle("O-ENV-2 математика backoff: полная серия 1..12, кэп 3600, "
        "defensive attempts=0 (§25.4)")
def o_env_2_backoff_series():
    _require_6b()
    expected = {1: 30, 2: 60, 3: 120, 4: 240, 5: 480, 6: 960, 7: 1920}
    for attempts, seconds in expected.items():
        actual = dox.retry_backoff_seconds(attempts)
        if actual != seconds:
            raise OracleFail(
                f"backoff({attempts}) == {actual}, ожидалось {seconds}"
            )
    for attempts in (8, 12, 20):
        if dox.retry_backoff_seconds(attempts) != 3600:
            raise OracleFail(
                f"backoff({attempts}) не ограничен кэпом 3600"
            )
    if dox.retry_backoff_seconds(0) != 30:
        raise OracleFail("backoff(0) -- defensive-ветка обязана давать базу 30")
    series = [dox.retry_backoff_seconds(a) for a in range(1, 9)]
    if series != sorted(series):
        raise OracleFail(f"серия backoff не монотонна: {series}")


@oracle("O-ENV-3 словарь состояний: 3 состояния outbox, 5 состояний "
        "операции, бюджеты/базы (§25.2/§25.5)")
def o_env_3_vocabulary():
    _require_6b()
    if (dox.STATE_PENDING, dox.STATE_DELIVERED, dox.STATE_FAILED) != (
        "pending", "delivered", "failed",
    ):
        raise OracleFail("состояния outbox != pending/delivered/failed")
    ops = {
        dox.OP_NOT_EXECUTED: "not_executed",
        dox.OP_EXECUTED_DOCUMENTATION_PENDING: "executed_documentation_pending",
        dox.OP_COMMITTED_PROJECTION_PENDING: "committed_projection_pending",
        dox.OP_DELIVERED: "delivered",
        dox.OP_FAILED: "failed",
    }
    for actual, expected in ops.items():
        if actual != expected:
            raise OracleFail(f"состояние операции {actual!r} != {expected!r}")
    if dox.DEFAULT_MAX_ATTEMPTS != 5:
        raise OracleFail(f"DEFAULT_MAX_ATTEMPTS == {dox.DEFAULT_MAX_ATTEMPTS}")
    if (dox.RETRY_BACKOFF_BASE_SECONDS, dox.RETRY_BACKOFF_CAP_SECONDS) != (30, 3600):
        raise OracleFail("база/кэп backoff != 30/3600")
    if set(dox.DELIVERY_KINDS) != {"layer1_mirror"}:
        raise OracleFail(
            f"DELIVERY_KINDS физически не ограничен проекцией: {dox.DELIVERY_KINDS}"
        )


@oracle("O-ENV-4 КОНТРОЛЬ базы: commit событий без обязательства -- "
        "базовый контракт 6A здоров (GREEN и на базе)")
def o_env_4_base_commit_control():
    from apps.api.research_runs import (
        CommitEventBatch,
        MemoryResearchRunStore,
        batch_body_fingerprint,
    )

    store = MemoryResearchRunStore()
    run_id = f"{RUN_PREFIX}-CTRL-COMMIT"
    store.upsert_run(_my_run(run_id))
    events = _events(run_id, 2)
    receipt = store.commit_event_batch(
        CommitEventBatch(
            run=_my_run(run_id),
            events=events,
            idempotency_key="cert6b-key-ctrl-commit",
            body_fingerprint=batch_body_fingerprint(run_id, events),
        )
    )
    assert receipt is not None
    assert receipt.committed_watermark == 2, receipt
    assert len(store.list_events(run_id)) == 2


# ══ 2. OUT: контракт outbox на СВОИХ данных ══════════════════════════


@oracle("O-OUT-1 roundtrip DeliveryTask: 13 полей без искажений "
        "(свои max_attempts=7/next_attempt_at/last_error)")
def o_out_1_roundtrip():
    _require_6b()
    task = dox.DeliveryTask(
        operation_id="op-c6b-rt",
        idempotency_key="cert6b-key-rt",
        run_id=f"{RUN_PREFIX}-RT",
        kind="layer1_mirror",
        payload={"session_id": "sess-cert6b", "events": [{"event_id": "e1"}]},
        state=dox.STATE_PENDING,
        attempts=2,
        max_attempts=7,
        next_attempt_at="2026-10-13T10:00:00+00:00",
        last_error=f"{CERT_LABEL}: прошлая попытка",
        created_at="2026-10-13T09:00:00+00:00",
        updated_at="2026-10-13T09:30:00+00:00",
        delivered_at=None,
    )
    restored = dox.DeliveryTask.from_dict(task.to_dict())
    for field in (
        "operation_id", "idempotency_key", "run_id", "kind", "state",
        "attempts", "max_attempts", "next_attempt_at", "last_error",
        "created_at", "updated_at", "delivered_at",
    ):
        if getattr(restored, field) != getattr(task, field):
            raise OracleFail(
                f"roundtrip потерял поле {field}: "
                f"{getattr(restored, field)!r} != {getattr(task, field)!r}"
            )
    if restored.payload != task.payload:
        raise OracleFail("roundtrip исказил payload")
    # дефолты from_dict не подменяют собственные значения
    if restored.max_attempts != 7:
        raise OracleFail("from_dict подменил max_attempts дефолтом")


@oracle("O-OUT-2 изоляция копий + first-wins дедуп register")
def o_out_2_copy_isolation():
    _require_6b()
    outbox = dox.MemoryDeliveryOutbox()
    task = _mirror_task(
        f"{RUN_PREFIX}-COPY", _events(f"{RUN_PREFIX}-COPY", 1), "op-c6b-copy",
    )
    task.payload["payload_marker"] = "cert6b-v1"
    outbox.register(task)
    # мутация ИСХОДНОГО payload после register не портит store
    task.payload["session_id"] = "sess-hacked"
    stored = outbox.get_task("op-c6b-copy")
    assert stored is not None
    if stored.payload["session_id"] == "sess-hacked":
        raise OracleFail("register не скопировал payload (живая ссылка)")
    # мутация ПРОЧИТАННОГО payload не портит store (контракт копий R1)
    stored.payload["session_id"] = "sess-hacked-2"
    again = outbox.get_task("op-c6b-copy")
    assert again is not None
    if again.payload["session_id"] != "sess-cert6b":
        raise OracleFail("get_task вернул живую ссылку (мутация прочитанного)")
    # first-wins дедуп: повторный register с тем же operation_id -- no-op
    second = _mirror_task(
        f"{RUN_PREFIX}-COPY", _events(f"{RUN_PREFIX}-COPY", 1), "op-c6b-copy",
    )
    second.payload["payload_marker"] = "cert6b-v2"
    outbox.register(second)
    third = outbox.get_task("op-c6b-copy")
    assert third is not None
    if third.payload.get("payload_marker") != "cert6b-v1":
        raise OracleFail("дедуп register НЕ first-wins (перезапись)")
    counts = outbox.backlog()
    if counts[dox.STATE_PENDING] != 1:
        raise OracleFail(f"backlog после дедупа: {counts}")


@oracle("O-OUT-3 bind_idempotency_key: привязка пустого, НЕ-перезапись "
        "непустого, no-op пустого аргумента, иммутабельность (§25.2)")
def o_out_3_bind():
    _require_6b()
    run_id = f"{RUN_PREFIX}-BIND"
    plain = _mirror_task(run_id, _events(run_id, 1), "op-c6b-bind-1")
    bound = dox.bind_idempotency_key(plain, "cert6b-key-bind-1")
    if bound.idempotency_key != "cert6b-key-bind-1":
        raise OracleFail("пустой ключ не привязан")
    if plain.idempotency_key != "":
        raise OracleFail("bind мутировал исходный замороженный task")
    prebound = _mirror_task(run_id, _events(run_id, 1), "op-c6b-bind-2")
    prebound = dox.bind_idempotency_key(prebound, "cert6b-key-original")
    rebound = dox.bind_idempotency_key(prebound, "cert6b-key-other")
    if rebound.idempotency_key != "cert6b-key-original":
        raise OracleFail("bind ПЕРЕЗАПИСАЛ непустой ключ (связь с receipt потеряна)")
    noop = dox.bind_idempotency_key(plain, "")
    if noop.idempotency_key != "":
        raise OracleFail("bind с пустым аргументом не no-op")


@oracle("O-OUT-4 list_due: будущее НЕ due, None первым, state-фильтр, "
        "limit-срез (свои метки времени)")
def o_out_4_list_due():
    _require_6b()
    outbox = dox.MemoryDeliveryOutbox()
    now = datetime.now(timezone.utc)
    run_id = f"{RUN_PREFIX}-DUE"
    t_immediate = _mirror_task(run_id, _events(run_id, 1), "op-c6b-due-now")
    t_past = _mirror_task(run_id, _events(run_id, 1), "op-c6b-due-past")
    t_past = dox.DeliveryTask(**{
        **t_past.to_dict(),
        "next_attempt_at": (now - timedelta(minutes=5)).isoformat(),
    })
    t_future = _mirror_task(run_id, _events(run_id, 1), "op-c6b-due-future")
    t_future = dox.DeliveryTask(**{
        **t_future.to_dict(),
        "next_attempt_at": (now + timedelta(hours=1)).isoformat(),
    })
    for task in (t_immediate, t_past, t_future):
        outbox.register(task)
    due = outbox.list_due(now=now.isoformat(), limit=100)
    due_ids = [task.operation_id for task in due]
    if "op-c6b-due-future" in due_ids:
        raise OracleFail("будущее обязательство попало в due (фильтр времени сломан)")
    if due_ids[:2] != ["op-c6b-due-now", "op-c6b-due-past"]:
        raise OracleFail(f"срочность порядка нарушена: {due_ids}")
    limited = outbox.list_due(now=now.isoformat(), limit=1)
    if [task.operation_id for task in limited] != ["op-c6b-due-now"]:
        raise OracleFail("limit-срез list_due неверен")
    outbox.mark_delivered("op-c6b-due-now", delivered_at=now.isoformat())
    due2 = outbox.list_due(now=now.isoformat(), limit=100)
    if [task.operation_id for task in due2] != ["op-c6b-due-past"]:
        raise OracleFail("delivered попал в due (state-фильтр сломан)")


@oracle("O-OUT-5 clip last_error: граница 500, суффикс, персистенция "
        "через mark_failed (операционный лог без сырых payload)")
def o_out_5_clip():
    _require_6b()
    exact = "a" * 500
    if dox._clip_error(exact) != exact:
        raise OracleFail("ровно 500 символов не должен обрезаться")
    clipped = dox._clip_error("b" * 501)
    if len(clipped) != 500 or not clipped.endswith("..."):
        raise OracleFail(f"clip 501: len={len(clipped)}, tail={clipped[-4:]!r}")
    if dox._clip_error("") != "":
        raise OracleFail("пустая ошибка искажена")
    if dox._clip_error(None) != "":
        raise OracleFail("None-ошибка должна нормализоваться в пустую строку")
    outbox = dox.MemoryDeliveryOutbox()
    run_id = f"{RUN_PREFIX}-CLIP"
    task = _mirror_task(run_id, _events(run_id, 1), "op-c6b-clip")
    outbox.register(task)
    outbox.mark_failed(
        "op-c6b-clip",
        error=f"{CERT_LABEL} сырая причина " + "x" * 600,
        next_attempt_at=datetime.now(timezone.utc).isoformat(),
        at=datetime.now(timezone.utc).isoformat(),
    )
    stored = outbox.get_task("op-c6b-clip")
    assert stored is not None
    if stored.last_error is None or not stored.last_error.startswith(CERT_LABEL):
        raise OracleFail(f"last_error потерял содержимое: {stored.last_error!r}")
    if len(stored.last_error) > 500 or not stored.last_error.endswith("..."):
        raise OracleFail("last_error не обрезан безопасно")


# ══ 3. ATOM: атомарность батча с обязательством ══════════════════════


@oracle("O-ATOM-1 КОНТРОЛЬ базы: дедуп того же тела -- прежний receipt, "
        "одна копия (GREEN и на базе)")
def o_atom_1_base_dedup_control():
    from apps.api.research_runs import (
        CommitEventBatch,
        MemoryResearchRunStore,
        batch_body_fingerprint,
    )

    store = MemoryResearchRunStore()
    run_id = f"{RUN_PREFIX}-CTRL-DEDUP"
    store.upsert_run(_my_run(run_id))
    events = _events(run_id, 1)
    kwargs = dict(
        run=_my_run(run_id),
        events=events,
        idempotency_key="cert6b-key-ctrl-dedup",
        body_fingerprint=batch_body_fingerprint(run_id, events),
    )
    receipt1 = store.commit_event_batch(CommitEventBatch(**kwargs))
    receipt2 = store.commit_event_batch(CommitEventBatch(**kwargs))
    if receipt1.committed_watermark != receipt2.committed_watermark:
        raise OracleFail("дедуп вернул другой watermark")
    if len(store.list_events(run_id)) != 1:
        raise OracleFail("дедуп задвоил события")


@oracle("O-ATOM-2 полный батч: receipt + обязательство + чекпоинт + "
        "события ОДНОЙ транзакцией, привязка ключа, watermark (§25.2/§25.3)")
def o_atom_2_full_batch():
    _require_6b()
    from apps.api.research_runs import (
        CommitEventBatch,
        MemoryResearchRunStore,
        ResearchCheckpoint,
        batch_body_fingerprint,
    )

    store = MemoryResearchRunStore()
    run_id = f"{RUN_PREFIX}-ATOM"
    store.upsert_run(_my_run(run_id))
    events = _events(run_id, 2)
    checkpoint = ResearchCheckpoint(
        checkpoint_id="cp-cert6b-atom",
        run_id=run_id,
        event_id=events[0].event_id,
        label=f"{CERT_LABEL}: точка атомарного батча",
        watermark=0,
    )
    task = _mirror_task(run_id, events, "op-c6b-atom")
    receipt = store.commit_event_batch(
        CommitEventBatch(
            run=_my_run(run_id),
            events=events,
            idempotency_key="cert6b-key-atom",
            body_fingerprint=batch_body_fingerprint(run_id, events),
            checkpoints=(checkpoint,),
            delivery_task=task,
        )
    )
    if receipt.committed_watermark != 2:
        raise OracleFail(f"watermark {receipt.committed_watermark} != 2")
    stored_task = _task_of(store, "op-c6b-atom")
    if stored_task is None:
        raise OracleFail("обязательство не зарегистрировано транзакцией commit'а")
    if stored_task.idempotency_key != "cert6b-key-atom":
        raise OracleFail(
            f"ключ commit'а не привязан: {stored_task.idempotency_key!r}"
        )
    if stored_task.state != dox.STATE_PENDING:
        raise OracleFail(f"состояние обязательства {stored_task.state}")
    if [cp.checkpoint_id for cp in store.list_checkpoints(run_id)] != ["cp-cert6b-atom"]:
        raise OracleFail("чекпоинт не зарегистрирован той же транзакцией")
    if len(store.list_events(run_id)) != 2:
        raise OracleFail("события не зарегистрированы")
    counts = store.delivery_outbox.backlog()
    if counts[dox.STATE_PENDING] != 1:
        raise OracleFail(f"backlog честности: {counts}")


@oracle("O-ATOM-3 дедуп-рекоммит ПОСЛЕ доставки: обязательство не "
        "сбрасывается в pending, события не задваиваются")
def o_atom_3_dedup_after_delivered():
    _require_6b()
    from apps.api.research_runs import (
        CommitEventBatch,
        MemoryResearchRunStore,
        batch_body_fingerprint,
    )

    store = MemoryResearchRunStore()
    run_id = f"{RUN_PREFIX}-DEDUP-DELIV"
    store.upsert_run(_my_run(run_id))
    events = _events(run_id, 1)
    kwargs = dict(
        run=_my_run(run_id),
        events=events,
        idempotency_key="cert6b-key-dedup-deliv",
        body_fingerprint=batch_body_fingerprint(run_id, events),
        delivery_task=_mirror_task(run_id, events, "op-c6b-dedup-deliv"),
    )
    store.commit_event_batch(CommitEventBatch(**kwargs))
    receipt1 = store.get_commit_receipt("cert6b-key-dedup-deliv")
    store.delivery_outbox.mark_delivered(
        "op-c6b-dedup-deliv",
        delivered_at=datetime.now(timezone.utc).isoformat(),
    )
    receipt2 = store.commit_event_batch(CommitEventBatch(**kwargs))
    stored = _task_of(store, "op-c6b-dedup-deliv")
    assert stored is not None
    if stored.state != dox.STATE_DELIVERED:
        raise OracleFail(
            f"дедуп-рекоммит сбросил доставленное обязательство: {stored.state}"
        )
    if len(store.list_events(run_id)) != 1:
        raise OracleFail("дедуп-рекоммит задвоил события")
    if (receipt2 is not receipt1 and (
        receipt2.accepted_event_ids != receipt1.accepted_event_ids
        or receipt2.committed_watermark != receipt1.committed_watermark
    )):
        raise OracleFail("дедуп-рекоммит вернул НЕ прежний receipt")
    counts = store.delivery_outbox.backlog()
    if counts[dox.STATE_DELIVERED] != 1 or counts[dox.STATE_PENDING] != 0:
        raise OracleFail(f"backlog после дедупа недостоверен: {counts}")


# ══ 4. MAP: required-доставка карт на СВОЁМ контуре ══════════════════


def _post_eda_map(client, run_id: str, context_id: str, report_id: str):
    from app.core.pipeline_graph import STAGE_NODES
    from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES

    checks = {
        node_id: list(EDA_CHECK_STATUS_VALUES)[i % len(EDA_CHECK_STATUS_VALUES)]
        for i, node_id in enumerate(STAGE_NODES["eda"])
    }
    return client.post(
        "/v1/progress/eda-checks",
        json={
            "checks": checks,
            "schema_version": 2,
            "run_id": run_id,
            "context_id": context_id,
            "report_id": report_id,
        },
    )


@oracle("O-MAP-1 свой контур: здоровая поставка 200 -> отказ cache: "
        "500 честно называет committed_projection_pending/operation_id/"
        "watermark -> worker доставляет -> повтор дедуплицирован")
def o_map_1_full_contour():
    _require_6b()
    from app.core.pipeline_graph import STAGE_NODES
    from apps.api import research_runs

    client = _client()
    run_id, context_id = _upload_own(client)
    store = research_runs.get_research_run_store()
    n_nodes = len(STAGE_NODES["eda"])

    resp_ok = _post_eda_map(client, run_id, context_id, f"{REPORT_PREFIX}-map-1")
    if resp_ok.status_code != 200:
        raise OracleFail(f"здоровая поставка карты: {resp_ok.status_code} {resp_ok.text}")
    base_count = _layer1_count(client, "eda_check_status")
    if base_count != n_nodes:
        raise OracleFail(f"слой 1 после здоровой поставки: {base_count} != {n_nodes}")

    with _redis_semantics_with_save_fault(1):
        resp_fail = _post_eda_map(client, run_id, context_id, f"{REPORT_PREFIX}-map-2")
    if resp_fail.status_code != 500:
        raise OracleFail(
            f"отказ cache обязан дать 500: {resp_fail.status_code} {resp_fail.text}"
        )
    detail = str(resp_fail.json().get("detail") or "")
    for pin in (
        "committed_projection_pending",
        f"operation_id: {REPORT_PREFIX}-map-2",
        "watermark: ",
    ):
        if pin not in detail:
            raise OracleFail(f"честный 500 без пина {pin!r}: {detail[:200]}")

    receipt = store.get_commit_receipt(f"report:{run_id}:{REPORT_PREFIX}-map-2")
    if receipt is None:
        raise OracleFail("отказ cache отменил committed событие (receipt нет)")
    task = _task_of(store, f"{REPORT_PREFIX}-map-2")
    if task is None or task.state != dox.STATE_PENDING:
        raise OracleFail("обязательство пережило отказ cache неправильно")
    if _layer1_count(client, "eda_check_status") != base_count:
        raise OracleFail("отказ cache всё же долил проекцию в слой 1")

    summary = dox.run_delivery_recovery(store)
    if summary["delivered"] < 1:
        raise OracleFail(f"worker не доставил проекцию: {summary}")
    if _layer1_count(client, "eda_check_status") != base_count + n_nodes:
        raise OracleFail("после worker'а проекция неполна")
    if _task_of(store, f"{REPORT_PREFIX}-map-2").state != dox.STATE_DELIVERED:
        raise OracleFail("worker не закрыл обязательство")

    resp_retry = _post_eda_map(client, run_id, context_id, f"{REPORT_PREFIX}-map-2")
    if resp_retry.status_code != 200 or resp_retry.json().get("deduplicated") is not True:
        raise OracleFail(f"повтор поставки не дедуплицирован: {resp_retry.text[:200]}")
    if _layer1_count(client, "eda_check_status") != base_count + n_nodes:
        raise OracleFail("повтор поставки задвоил проекцию")


@oracle("O-MAP-2 worker дважды: вторая попытка due=0/delivered=0, "
        "копий нет (сводка честна)")
def o_map_2_worker_twice():
    _require_6b()
    from app.core.pipeline_graph import STAGE_NODES
    from apps.api import research_runs

    client = _client()
    run_id, context_id = _upload_own(client)
    store = research_runs.get_research_run_store()
    n_nodes = len(STAGE_NODES["eda"])

    with _redis_semantics_with_save_fault(1):
        resp = _post_eda_map(client, run_id, context_id, f"{REPORT_PREFIX}-twice")
    if resp.status_code != 500:
        raise OracleFail("постановка fault-сценария не воспроизведена")

    first = dox.run_delivery_recovery(store)
    second = dox.run_delivery_recovery(store)
    if first["delivered"] != 1 or first["due"] != 1:
        raise OracleFail(f"первый прогон: {first}")
    if second != {"due": 0, "delivered": 0, "session_absent": 0, "failed": 0}:
        raise OracleFail(f"второй прогон недостоверен: {second}")
    if _layer1_count(client, "eda_check_status") != n_nodes:
        raise OracleFail("двойной worker задвоил копии в слое 1")


# ══ 5. RUN: run-level операции (CAS, пауза/резюме, fault-timeline) ═══


@oracle("O-RUN-1 CAS-конфликт на store-уровне с обязательством в батче: "
        "CommitConflictError ДО записи -- ноль событий/обязательств")
def o_run_1_cas_conflict():
    _require_6b()
    from apps.api.research_runs import (
        CommitEventBatch,
        CommitConflictError,
        MemoryResearchRunStore,
        batch_body_fingerprint,
    )

    store = MemoryResearchRunStore()
    run_id = f"{RUN_PREFIX}-CAS"
    store.upsert_run(_my_run(run_id, context_id="ctx-cert6b-A", status="active"))
    events = _events(run_id, 1)
    task = _mirror_task(run_id, events, "op-c6b-cas")
    try:
        store.commit_event_batch(
            CommitEventBatch(
                run=_my_run(run_id, context_id="ctx-cert6b-A"),
                events=events,
                expected_context_id="ctx-cert6b-STALE",
                idempotency_key="cert6b-key-cas",
                body_fingerprint=batch_body_fingerprint(run_id, events),
                delivery_task=task,
            )
        )
    except CommitConflictError:
        pass
    else:
        raise OracleFail("stale context не отклонён CAS-гейтом")
    if store.list_events(run_id) != []:
        raise OracleFail("CAS-конфликт записал события")
    if _task_of(store, "op-c6b-cas") is not None:
        raise OracleFail("CAS-конфликт зарегистрировал обязательство")
    if store.get_commit_receipt("cert6b-key-cas") is not None:
        raise OracleFail("CAS-конфликт выдал receipt")
    run_meta = [run for run in store.list_runs() if run.run_id == run_id][0]
    if run_meta.status != "active" or run_meta.context_id != "ctx-cert6b-A":
        raise OracleFail("CAS-конфликт сдвинул метаданные запуска")


@oracle("O-RUN-2 пауза/резюме: обязательства event:{{run}}:{{event}} "
        "закрыты синхронным зеркалом, read-after-write с watermark")
def o_run_2_pause_resume():
    _require_6b()
    from apps.api import research_runs

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()

    resp_pause = client.post(f"/v1/progress/runs/{run_id}/pause")
    if resp_pause.status_code != 200:
        raise OracleFail(f"пауза: {resp_pause.status_code} {resp_pause.text}")
    event_id = str(resp_pause.json()["event"]["event_id"])
    task = _task_of(store, event_id)
    if task is None:
        raise OracleFail("run_paused без обязательства доставки (required-путь потерян)")
    if task.idempotency_key != f"event:{run_id}:{event_id}":
        raise OracleFail(f"ключ обязательства: {task.idempotency_key!r}")
    if task.state != dox.STATE_DELIVERED:
        raise OracleFail(f"синхронное зеркало не закрыло обязательство: {task.state}")

    status = client.get(f"/v1/progress/runs/{run_id}/delivery/{event_id}").json()
    if status.get("state") != "delivered":
        raise OracleFail(f"read-after-write: {status}")
    receipt = status.get("receipt") or {}
    if not receipt.get("committed_watermark"):
        raise OracleFail("read-after-write без watermark receipt'а")

    resp_resume = client.post(f"/v1/progress/runs/{run_id}/resume")
    if resp_resume.status_code != 200:
        raise OracleFail(f"резюме: {resp_resume.status_code} {resp_resume.text}")
    listing = client.get(f"/v1/progress/runs/{run_id}/delivery").json()
    counts = listing.get("counts_by_state") or {}
    if counts.get("delivered") != 2:
        raise OracleFail(f"counts_by_state: {counts}")
    if len(listing.get("tasks") or []) != 2:
        raise OracleFail("перечень обязательств неполон")


@oracle("O-RUN-3 fault-timeline restore: commit прошёл, второй save слоя 1 "
        "отказал -> защитный 503 (контур _durable_ops); факт и обязательство "
        "в ledger; worker доставляет проекцию в сессию первого save "
        "(RED-карточка §17 «операция записана, проекция ещё не обновилась»)")
def o_run_3_restore_projection_pending():
    _require_6b()
    from apps.api import research_runs
    from apps.api.session_store import get_session_store

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()

    with _redis_semantics_with_save_fault(2) as fault:
        resp = client.get(f"/v1/progress/runs/{run_id}/restore")
    if resp.status_code != 503:
        raise OracleFail(
            f"отказ второго save обязан дать защитный 503: {resp.status_code} "
            f"{resp.text[:200]}"
        )
    captured = fault["sessions"]
    if len(captured) < 2 or not captured[1]:
        raise OracleFail(f"шов сохранения не наблюдён: {captured}")
    new_session_id = captured[1]

    events = store.list_events(run_id)
    resumed = [e for e in events if e.event_type == "run_resumed"]
    if not resumed:
        raise OracleFail("факт run_resumed не committed (операция потеряна)")
    event_id = resumed[-1].event_id
    task = _task_of(store, event_id)
    if task is None or task.state != dox.STATE_PENDING:
        raise OracleFail("обязательство restore не ждёт worker'а")

    # слой 1 сохранён ПЕРВЫМ save -- без run_resumed (Redis-семантика копий)
    session = get_session_store().get(new_session_id)
    assert session is not None
    before = sum(
        1 for item in session.pipeline_trace
        if isinstance(item, dict) and item.get("event_type") == "run_resumed"
    )
    if before != 0:
        raise OracleFail("слой 1 получил факт мимо обязательства")

    summary = dox.run_delivery_recovery(store)
    if summary["delivered"] != 1 or summary["session_absent"] != 0:
        raise OracleFail(f"worker не восстановил проекцию: {summary}")
    repaired = get_session_store().get(new_session_id)
    assert repaired is not None
    after = sum(
        1 for item in repaired.pipeline_trace
        if isinstance(item, dict) and item.get("event_type") == "run_resumed"
    )
    if after != 1:
        raise OracleFail(f"проекция после worker'а: run_resumed x{after}")
    if _task_of(store, event_id).state != dox.STATE_DELIVERED:
        raise OracleFail("обязательство не закрыто после доставки")


# ══ 6. SWEEP: staged cleanup внешних артефактов ══════════════════════


@oracle("O-SWEEP-1 sweep: сирот удалён, ССЫЛАЕМЫЙ снимок выжил, повтор "
        "no-op (свой сирот через file_store)")
def o_sweep_1_scoped_cleanup():
    """Сирота -- файл без ссылки в ledger; ссылаемый снимок выживает."""
    _require_6b()
    import pandas as pd

    from apps.api import research_runs
    from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()
    file_store = research_runs.get_dataset_file_store()

    events = store.list_events(run_id)
    if not events:
        raise OracleFail("seed: ledger пуст")
    resp_cp = client.post(
        f"/v1/progress/runs/{run_id}/checkpoints",
        json={"event_id": events[0].event_id, "label": f"{CERT_LABEL}: реальная точка"},
    )
    if resp_cp.status_code != 201:
        raise OracleFail(f"чекпоинт: {resp_cp.status_code} {resp_cp.text}")
    real_cp_id = str(resp_cp.json()["checkpoint"]["checkpoint_id"])
    if real_cp_id not in {p.stem for p in file_store.checkpoint_snapshot_files(run_id)}:
        raise OracleFail("снимок реального чекпоинта не записан (staged-артефакт)")

    frame = pd.DataFrame({"period": _DAYS[:5], "revenue": _REVENUE[:5]})
    if not file_store.save_checkpoint_snapshot(run_id, "cp-cert6b-orphan", frame):
        raise OracleFail("сирота-снимок не записан (сценарий невоспроизводим)")

    removed = dox.sweep_orphaned_checkpoints(store, file_store)
    if removed != ["cp-cert6b-orphan"]:
        raise OracleFail(f"sweep удалил не только сирота: {removed}")
    survivors = {p.stem for p in file_store.checkpoint_snapshot_files(run_id)}
    if real_cp_id not in survivors:
        raise OracleFail("sweep удалил ССЫЛАЕМЫЙ снимок (потеря данных)")
    if "cp-cert6b-orphan" in survivors:
        raise OracleFail("sweep не удалил сироту")

    removed_again = dox.sweep_orphaned_checkpoints(store, file_store)
    if removed_again != []:
        raise OracleFail(f"повторный sweep не no-op: {removed_again}")


@oracle("O-SWEEP-2 sweep-скоупинг: явный run_ids сужает периметр "
        "(два запуска -- сироты независимо)")
def o_sweep_2_subset_scoping():
    _require_6b()
    import pandas as pd

    from apps.api import research_runs

    client = _client()
    run_a, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()
    file_store = research_runs.get_dataset_file_store()
    run_b = f"{RUN_PREFIX}-SWEEP-B"
    store.upsert_run(_my_run(run_b))

    frame = pd.DataFrame({"period": _DAYS[:3], "revenue": _REVENUE[:3]})
    assert file_store.save_checkpoint_snapshot(run_a, "cp-cert6b-orphan-a", frame)
    assert file_store.save_checkpoint_snapshot(run_b, "cp-cert6b-orphan-b", frame)

    removed = dox.sweep_orphaned_checkpoints(store, file_store, run_ids=[run_a])
    if removed != ["cp-cert6b-orphan-a"]:
        raise OracleFail(f"скоупинг нарушен: {removed}")
    b_files = {p.stem for p in file_store.checkpoint_snapshot_files(run_b)}
    if "cp-cert6b-orphan-b" not in b_files:
        raise OracleFail("sweep вышел за явный периметр run_ids")
    removed_b = dox.sweep_orphaned_checkpoints(store, file_store, run_ids=[run_b])
    if removed_b != ["cp-cert6b-orphan-b"]:
        raise OracleFail(f"второй скоуп: {removed_b}")


# ══ 7. EP: эндпоинты и классификатор (read-after-write, п.6/п.8) ═════


@oracle("O-EP-1 эндпоинты: неизвестная операция 200 not_executed, "
        "неизвестный запуск 404, исчерпанный бюджет failed + last_error, "
        "payload НЕ публичен, counts_by_state")
def o_ep_1_endpoints():
    _require_6b()
    from apps.api import research_runs

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()

    resp_404 = client.get(f"/v1/progress/runs/{RUN_PREFIX}-NOPE/delivery")
    if resp_404.status_code != 404:
        raise OracleFail(f"неизвестный запуск: {resp_404.status_code} (факт -- 404)")
    resp_unknown = client.get(f"/v1/progress/runs/{run_id}/delivery/op-c6b-unknown")
    if resp_unknown.status_code != 200:
        raise OracleFail(f"неизвестная операция: {resp_unknown.status_code} (честный 200)")
    if resp_unknown.json().get("state") != "not_executed":
        raise OracleFail(f"неизвестная операция: {resp_unknown.json()}")

    task = _mirror_task(run_id, _events(run_id, 1), "op-c6b-budget", max_attempts=2)
    store.delivery_outbox.register(task)
    now = datetime.now(timezone.utc).isoformat()
    store.delivery_outbox.mark_failed(
        "op-c6b-budget", error=f"{CERT_LABEL}: сбой 1",
        next_attempt_at=now, at=now,
    )
    store.delivery_outbox.mark_failed(
        "op-c6b-budget", error=f"{CERT_LABEL}: сбой 2 (бюджет)",
        next_attempt_at=now, at=now,
    )
    stored = _task_of(store, "op-c6b-budget")
    assert stored is not None
    if stored.state != dox.STATE_FAILED:
        raise OracleFail(f"бюджет 5 != 2 попыток не исчерпан: {stored.state}")
    if stored.attempts != 2:
        raise OracleFail(f"attempts: {stored.attempts}")

    body = client.get(f"/v1/progress/runs/{run_id}/delivery/op-c6b-budget").json()
    if body.get("state") != "failed":
        raise OracleFail(f"исчерпанный бюджет виден как {body.get('state')}")
    if CERT_LABEL not in str(body.get("last_error") or ""):
        raise OracleFail("last_error не доезжает до наблюдателя")
    if "payload" in body:
        raise OracleFail("эндпоинт выдал payload (копии событий не публичны)")

    listing = client.get(f"/v1/progress/runs/{run_id}/delivery").json()
    if (listing.get("counts_by_state") or {}).get("failed") != 1:
        raise OracleFail(f"counts_by_state: {listing.get('counts_by_state')}")
    for item in listing.get("tasks") or []:
        if "payload" in item:
            raise OracleFail("list-эндпоинт выдал payload")


@oracle("O-EP-2 таблица предшествования classify_operation: delivered/failed "
        "старше receipt; defensive-ветка честна (6 строк, свои формы)")
def o_ep_2_classifier():
    _require_6b()
    def task(state: str) -> "dox.DeliveryTask":
        return dox.DeliveryTask(
            operation_id=f"op-c6b-cls-{state}",
            idempotency_key="cert6b-key-cls",
            run_id=f"{RUN_PREFIX}-CLS",
            state=state,
        )

    receipt = SimpleNamespace()  # любой непустой receipt (watermark-объект)
    rows = [
        ((receipt, task(dox.STATE_DELIVERED), {}), "delivered",
         "delivered-обязательство с receipt"),
        ((receipt, task(dox.STATE_FAILED), {}), "failed",
         "failed старше receipt (бюджет честнее оптимизма)"),
        ((receipt, task(dox.STATE_PENDING), {}), "committed_projection_pending",
         "pending с receipt -- проекция ждёт"),
        ((None, task(dox.STATE_PENDING), {}), "committed_projection_pending",
         "defensive: обязательство без receipt -- не «успех»"),
        ((None, None, {"mutation_applied": True}), "executed_documentation_pending",
         "мутация исполнена, документирование не зафиксировано"),
        ((None, None, {}), "not_executed", "до хранилища не дошло"),
    ]
    for (rcpt, tsk, kw), expected, why in rows:
        actual = dox.classify_operation(rcpt, tsk, **kw)
        if actual != expected:
            raise OracleFail(f"{why}: {actual} != {expected}")


@oracle("O-REC-1 неизвестный kind: worker отказывает без изобретения "
        "операции (failed, причина названа, попытка учтена, события целы)")
def o_rec_1_unknown_kind():
    _require_6b()
    from apps.api import research_runs

    store = research_runs.get_research_run_store()
    run_id = f"{RUN_PREFIX}-REC"
    store.upsert_run(_my_run(run_id))
    events = _events(run_id, 1)
    task = _mirror_task(
        run_id, events, "op-c6b-rec",
        session_id="sess-cert6b-absent", max_attempts=1,
    )
    task = dox.DeliveryTask(**{
        **task.to_dict(), "kind": "replay_correction_cert6b",
    })
    store.delivery_outbox.register(task)
    before = len(store.list_events(run_id))
    summary = dox.run_delivery_recovery(store)
    if summary["failed"] != 1:
        raise OracleFail(f"неизвестный kind обязан дать failed: {summary}")
    stored = _task_of(store, "op-c6b-rec")
    assert stored is not None
    if stored.state != dox.STATE_FAILED:
        raise OracleFail(f"неизвестный kind закрыт как {stored.state}")
    last_error = str(stored.last_error or "")
    if "kind" not in last_error:
        raise OracleFail(f"last_error не называет причину: {last_error!r}")
    if len(store.list_events(run_id)) != before:
        raise OracleFail("worker изобрёл операцию (события изменились)")
    if stored.attempts != 1:
        raise OracleFail(f"попытка не учтена: {stored.attempts}")


@oracle("O-REC-2 crash между доставкой и закрытием обязательства: тот же "
        "task доставлен дважды -- ровно одна копия в слое 1 (дедуп по "
        "event_id, RED-карточка §17 «worker дважды»)")
def o_rec_2_double_delivery():
    _require_6b()
    from app.core.pipeline_graph import STAGE_NODES
    from apps.api import research_runs
    from apps.api.session_store import get_session_store

    client = _client()
    run_id, context_id = _upload_own(client)
    store = research_runs.get_research_run_store()
    n_nodes = len(STAGE_NODES["eda"])

    with _redis_semantics_with_save_fault(1):
        resp = _post_eda_map(client, run_id, context_id, f"{REPORT_PREFIX}-crash")
    if resp.status_code != 500:
        raise OracleFail("постановка fault-сценария не воспроизведена")
    task = _task_of(store, f"{REPORT_PREFIX}-crash")
    if task is None or task.state != dox.STATE_PENDING:
        raise OracleFail("обязательство не в состоянии ожидания доставки")

    # crash ПОСЛЕ записи событий в слой 1, ДО mark_delivered (шов
    # «доставлено, но обязательство ещё открыто» -- тот же класс, что
    # P08/P10): повторная доставка того же task обязана быть no-op.
    session_id = str(task.payload.get("session_id") or "")
    if not session_id:
        raise OracleFail("payload обязательства без session_id")
    outcome1 = dox.deliver_layer1_mirror(task, get_session_store())
    if outcome1 != "delivered":
        raise OracleFail(f"первая доставка: {outcome1}")
    outcome2 = dox.deliver_layer1_mirror(task, get_session_store())
    if outcome2 != "delivered":
        raise OracleFail(f"повторная доставка: {outcome2}")

    session = get_session_store().get(session_id)
    assert session is not None
    items = [
        item for item in session.pipeline_trace
        if isinstance(item, dict)
        and item.get("event_type") == "eda_check_status"
    ]
    if len(items) != n_nodes:
        raise OracleFail(
            f"двойная доставка дала {len(items)} копий вместо {n_nodes}"
        )
    ids = [item.get("event_id") for item in items]
    if len(ids) != len(set(ids)):
        raise OracleFail("дубликаты event_id в слое 1 после двойной доставки")


# ══ 8. CTRL: контролы базы (GREEN и на базе 56f431c) ═════════════════


@oracle("O-CTRL-1 КОНТРОЛЬ базы: пауза -- 200 и факт в ledger (advisory-путь "
        "базы здоров; обязательство здесь не пинится)")
def o_ctrl_1_pause_base():
    from apps.api import research_runs

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()
    resp = client.post(f"/v1/progress/runs/{run_id}/pause")
    if resp.status_code != 200:
        raise OracleFail(f"пауза: {resp.status_code} {resp.text[:200]}")
    if resp.json().get("status") != "paused":
        raise OracleFail("пауза не переключила статус")
    events = store.list_events(run_id)
    if not [e for e in events if e.event_type == "run_paused"]:
        raise OracleFail("факт run_paused не в ledger")


@oracle("O-CTRL-2 КОНТРОЛЬ базы: чекпоинт -- 201 и staged-снимок на диске "
        "(артефакты существовали до 6B; sweep здесь не пинится)")
def o_ctrl_2_checkpoint_staged_base():
    from apps.api import research_runs

    client = _client()
    run_id, _ctx = _upload_own(client)
    store = research_runs.get_research_run_store()
    file_store = research_runs.get_dataset_file_store()
    events = store.list_events(run_id)
    resp = client.post(
        f"/v1/progress/runs/{run_id}/checkpoints",
        json={"event_id": events[0].event_id, "label": f"{CERT_LABEL}: базовая точка"},
    )
    if resp.status_code != 201:
        raise OracleFail(f"чекпоинт: {resp.status_code} {resp.text[:200]}")
    cp_id = str(resp.json()["checkpoint"]["checkpoint_id"])
    # наблюдение через каталог файлового слоя (checkpoint_snapshot_files --
    # примитив 6B; контрол базы обязан быть base-совместимым)
    snapshots = {p.stem for p in file_store._checkpoints_dir(run_id).glob("*.csv")}
    if cp_id not in snapshots:
        raise OracleFail("staged-снимок отсутствует")


# ══ 9. PG: живой PostgreSQL (fault-tests, план §17 GREEN) ════════════


@oracle("O-PG-1 restart-выживание на живом PG: обязательство + receipt "
        "видимы НОВЫМ экземпляром store (свои ключи/содержимое)", needs_pg=True)
def o_pg_1_restart_survival():
    _require_6b()
    from apps.api.research_runs import (
        CommitEventBatch,
        batch_body_fingerprint,
    )

    store_a = _pg_fresh_store()
    run_id = f"{RUN_PREFIX}-PG-RT"
    store_a.upsert_run(_my_run(run_id))
    events = _events(run_id, 2)
    receipt = store_a.commit_event_batch(
        CommitEventBatch(
            run=_my_run(run_id),
            events=events,
            idempotency_key="cert6b-key-pg-rt",
            body_fingerprint=batch_body_fingerprint(run_id, events),
            delivery_task=_mirror_task(run_id, events, "op-c6b-pg-rt"),
        )
    )
    assert receipt is not None and receipt.committed_watermark == 2

    # новый экземпляр store на ТОМ ЖЕ DSN (без пересоздания схемы --
    # restart выживаемость проверяет существующие данные)
    from apps.api.research_runs import PostgresResearchRunStore

    store_b = PostgresResearchRunStore(dsn=os.environ["CISSTAT_TEST_PG_DSN"])
    task = store_b.delivery_outbox.get_task("op-c6b-pg-rt")
    if task is None:
        raise OracleFail("restart: обязательство потеряно")
    if task.idempotency_key != "cert6b-key-pg-rt":
        raise OracleFail("restart: привязка ключа потеряна")
    if task.state != dox.STATE_PENDING:
        raise OracleFail(f"restart: состояние {task.state}")
    receipt_b = store_b.get_commit_receipt("cert6b-key-pg-rt")
    if receipt_b is None or receipt_b.committed_watermark != 2:
        raise OracleFail("restart: receipt потерян")
    if len(store_b.list_events(run_id)) != 2:
        raise OracleFail("restart: события потеряны")
    counts = store_b.delivery_outbox.backlog()
    if counts[dox.STATE_PENDING] != 1:
        raise OracleFail(f"restart: backlog {counts}")


@oracle("O-PG-2 НОВОЕ направление отказа атомарности на живом PG: отказ "
        "outbox-INSERT В транзакции commit'а -> ПОЛНЫЙ откат (ноль событий, "
        "ноль строк outbox, нет receipt, метаданные прежние)", needs_pg=True)
def o_pg_2_outbox_insert_rollback():
    _require_6b()
    from apps.api import research_runs
    from apps.api.research_runs import (
        CommitEventBatch,
        batch_body_fingerprint,
    )

    store = _pg_fresh_store()
    run_id = f"{RUN_PREFIX}-PG-ROLLBACK"
    store.upsert_run(_my_run(run_id, context_id="ctx-cert6b-pg"))
    events = _events(run_id, 2)

    def _broken_params(_task):
        raise RuntimeError(f"{CERT_LABEL}: injected outbox INSERT failure")

    with _patch_attr(research_runs, "outbox_row_params", _broken_params):
        try:
            store.commit_event_batch(
                CommitEventBatch(
                    run=_my_run(run_id, context_id="ctx-cert6b-pg"),
                    events=events,
                    idempotency_key="cert6b-key-pg-rb",
                    body_fingerprint=batch_body_fingerprint(run_id, events),
                    delivery_task=_mirror_task(run_id, events, "op-c6b-pg-rb"),
                )
            )
        except RuntimeError as exc:
            if CERT_LABEL not in str(exc):
                raise
        else:
            raise OracleFail("отказ outbox-INSERT не прервал commit")

    from apps.api.research_runs import PostgresResearchRunStore

    observer = PostgresResearchRunStore(dsn=os.environ["CISSTAT_TEST_PG_DSN"])
    if observer.list_events(run_id) != []:
        raise OracleFail("откат не убрал события (частичный commit)")
    if observer.delivery_outbox.get_task("op-c6b-pg-rb") is not None:
        raise OracleFail("откат не убрал обязательство")
    if observer.get_commit_receipt("cert6b-key-pg-rb") is not None:
        raise OracleFail("откат не убрал receipt")
    run_meta = [run for run in observer.list_runs() if run.run_id == run_id][0]
    if run_meta.context_id != "ctx-cert6b-pg" or run_meta.status != "active":
        raise OracleFail(f"метаданные запуска искажены: ctx={run_meta.context_id}")
    counts = observer.delivery_outbox.backlog()
    if counts != {dox.STATE_PENDING: 0, dox.STATE_DELIVERED: 0, dox.STATE_FAILED: 0}:
        raise OracleFail(f"outbox не пуст после отката: {counts}")


@oracle("O-PG-3 due-фильтр worker'а на живом PG: будущее не доставляется, "
        "due доставляется; паритет list_due с Memory", needs_pg=True)
def o_pg_3_due_filter_parity():
    _require_6b()
    from apps.api.research_runs import MemoryResearchRunStore, PostgresResearchRunStore

    run_id = f"{RUN_PREFIX}-PG-DUE"
    now = datetime.now(timezone.utc)
    store = _pg_fresh_store()
    store.upsert_run(_my_run(run_id))
    future = _mirror_task(run_id, _events(run_id, 1), "op-c6b-pg-future")
    future = dox.DeliveryTask(**{
        **future.to_dict(),
        "next_attempt_at": (now + timedelta(hours=2)).isoformat(),
    })
    due_task = _mirror_task(run_id, _events(run_id, 1), "op-c6b-pg-due")
    store.delivery_outbox.register(future)
    store.delivery_outbox.register(due_task)

    # паритет list_due ДО recovery (оба хранилища в одинаковой фазе)
    memory = MemoryResearchRunStore()
    memory.delivery_outbox.register(future)
    memory.delivery_outbox.register(due_task)
    mem_due = memory.delivery_outbox.list_due(now=now.isoformat(), limit=100)
    pg_due = store.delivery_outbox.list_due(now=now.isoformat(), limit=100)
    if [t.operation_id for t in mem_due] != [t.operation_id for t in pg_due]:
        raise OracleFail("паритет list_due Memory/Postgres нарушен (I8)")
    if [t.operation_id for t in pg_due] != ["op-c6b-pg-due"]:
        raise OracleFail(f"PG due-выборка: {[t.operation_id for t in pg_due]}")

    summary = dox.run_delivery_recovery(store)
    if summary["due"] != 1:
        raise OracleFail(f"PG due-фильтр: будущая задача попала в прогон: {summary}")
    if summary["delivered"] != 0 or summary["session_absent"] != 1:
        raise OracleFail(f"PG прогон недостоверен: {summary}")
    if _task_of(store, "op-c6b-pg-future").state != dox.STATE_PENDING:
        raise OracleFail("будущая задача не осталась pending")
    if _task_of(store, "op-c6b-pg-due").state != dox.STATE_DELIVERED:
        raise OracleFail("due-задача не закрыта")


# ── Runner ───────────────────────────────────────────────────────────

ORACLES: list = []


def _collect() -> None:
    import __main__ as mod  # noqa: PLC0415
    for name, value in vars(mod).items():
        if callable(value) and hasattr(value, "_oracle_name"):
            ORACLES.append(value)
    ORACLES.sort(key=lambda fn: fn._oracle_name)


def _ensure_pg_dsn() -> None:
    """Автоподъём живого pgserver для PG-группы (свой каталог -- дизъюнкт
    с раннером исполнителя scripts/prograudit6b_pg_runner.sh)."""
    if os.environ.get("CISSTAT_TEST_PG_DSN"):
        return
    if os.environ.get("CISSTAT_CERT6B_PG") == "1":
        import pgserver

        server = pgserver.get_server(
            "/tmp/cisstat6bcert-pg", cleanup_mode="delete"
        )
        os.environ["CISSTAT_TEST_PG_DSN"] = server.get_uri()
        _log(f"pgserver: {server.get_uri()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=None, help="путь протокола")
    args = parser.parse_args()
    _ensure_pg_dsn()
    _collect()
    _log("PROGR-AUDIT-6B-CERT -- СВОИ оракулы (данные сертификатора)")
    _log(f"Объект: {Path(REPO).name}; оракулов: {len(ORACLES)}")
    for fn in ORACLES:
        fn()
    _log("")
    _log(f"ИТОГ: PASS={PASSES} FAIL={len(FAILURES)} SKIP={SKIPS}")
    if FAILURES:
        _log("Отказы:")
        for failure in FAILURES:
            _log(f"  - {failure}")
    protocol_path = args.protocol or (
        REPO + "/scripts/prograudit6bcert_oracles_results.txt"
    )
    Path(protocol_path).write_text(
        "\n".join(PROTOCOL_LINES) + "\n", encoding="utf-8"
    )
    print(f"протокол: {protocol_path}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
