# tests/api/test_progress_audit_6b.py
"""Acceptance-тесты задачи AUDIT-6B (plan_progress_audit.md §17):
восстановимая доставка и операции контура «Прогресс».

Контракт (docs/progress_audit_contract.md, аддендум v1.5-6B §25; план §17
п.1–п.8; spec_progress_audit.md §8.3):

  R1 (п.1).  Реестр producers: required -- ЯВНЫЙ перечень мигрированных
             путей (v2-карты, run-level операции паузы/возобновления/
             чекпоинта/restore); advisory -- остальной сервис (хук-зеркало
             после ответа P22, легаси-карты, мутации DataFrame коррекций,
             наблюдения Наставника). Гарантия «durable» не распространяется
             на advisory (риск/граница карточки).
  R2 (п.2).  Простой UI report: ledger фиксируется ДО durable receipt;
             Redis (слой 1) -- восстанавливаемая проекция. Отказ cache НЕ
             отменяет committed событие; обязательство доставки переживает
             отказ cache, worker восстанавливает проекцию из факта.
  R3 (п.3).  Артефакты (снимки чекпоинтов): snapshot готовится ДО
             commit'а; ссылка+операционное состояние+событие --
             ОДНОЙ транзакцией (расширение commit_event_batch:
             checkpoints + delivery_task).
  R4 (п.4).  Outbox/обязательство живёт в ТОМ ЖЕ устойчивом хранилище,
             что ledger (миграция 0005 progress_delivery_outbox; Memory --
             тот же контракт), а не в памяти процесса и не в «недоказанном
             Redis». Crash ДО commit -- нет ни событий, ни обязательства
             (атомарность); crash ПОСЛЕ -- обязательство есть, worker
             доставляет.
  R5 (п.5).  Retry доставляет факт/проекцию по operation_id: worker
             идемпотентен (двойной прогон -- одна копия факта в слое 1),
             математические операции повторно НЕ запускает (виды задач
             ограничены проекцией layer1_mirror).
  R6 (п.6).  Состояния различаются честно: not_executed /
             executed_documentation_pending / committed_projection_pending /
             delivered / failed. Фиктивный rollback не сообщается.
  R7 (п.7).  Контролируемое восстановление: повторный запуск recovery
             безопасен; для внешних артефактов -- sweep staged cleanup
             (DB-транзакция не делает файловую запись атомарной: упавший
             commit оставляет staged-файл, sweep его удаляет).
  R8 (п.8).  Read-after-write: delivery-эндпоинт возвращает состояние
             операции (receipt + watermark) либо честное ожидающее;
             advisory-путь после ответа остаётся честно best-effort.

Живой Postgres (Донастройка_2 п.1, план §17 GREEN: «Fault tests с
настоящими тестовыми PostgreSQL/устойчивым хранилищем обязательны»):
DSN из CISSTAT_TEST_PG_DSN (тот же паттерн, что AUDIT-6A); без DSN живая
половина паритета честно skip.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.pipeline_graph import CHECK_STATUS_VALUES, STAGE_NODES
from apps.api.main import app
from apps.api.research_runs import (
    CommitEventBatch,
    MemoryResearchRunStore,
    PostgresResearchRunStore,
    ResearchCheckpoint,
    ResearchRun,
    batch_body_fingerprint,
    reset_dataset_file_store_for_testing,
)
from apps.api.session_store import (
    AnalysisSession,
    MemorySessionStore,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event

client = TestClient(app)

PG_DSN = os.environ.get("CISSTAT_TEST_PG_DSN", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── хранилища: parity-параметризация (I8) ────────────────────────────


@pytest.fixture()
def memory_store() -> MemoryResearchRunStore:
    return MemoryResearchRunStore()


@pytest.fixture()
def pg_store() -> PostgresResearchRunStore:
    """Живой Postgres: чистая схема на каждый тест (включая outbox 0005).
    Без CISSTAT_TEST_PG_DSN -- честный skip живой половины паритета."""
    if not PG_DSN:
        pytest.skip("CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен")
    try:
        import psycopg
    except ImportError:  # pragma: no cover - среда без драйвера
        pytest.skip("psycopg не установлен")
    conn = psycopg.connect(PG_DSN, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(
            "DROP TABLE IF EXISTS progress_delivery_outbox CASCADE;"
            "DROP TABLE IF EXISTS run_commit_receipts CASCADE;"
            "DROP TABLE IF EXISTS run_checkpoints CASCADE;"
            "DROP TABLE IF EXISTS trace_events CASCADE;"
            "DROP TABLE IF EXISTS research_runs CASCADE;"
            "DROP TABLE IF EXISTS mentor_observations CASCADE;"
        )
    conn.commit()
    from apps.api.research_runs import run_migrations

    run_migrations(conn)
    conn.close()
    return PostgresResearchRunStore(dsn=PG_DSN)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    """Parity-параметризация (I8): одни и те же контрактные тесты outbox
    на обоих хранилищах."""
    if request.param == "memory":
        return request.getfixturevalue("memory_store")
    return request.getfixturevalue("pg_store")


@pytest.fixture(autouse=True)
def _api_stores(monkeypatch, tmp_path):
    """REST-тесты (client) -- изолированные Memory-хранилища + tmp-каталог
    файлового слоя (снимки чекпоинтов)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path))
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    reset_dataset_file_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    reset_dataset_file_store_for_testing()


# ── швы отказа (паттерн AUDIT-6A) ────────────────────────────────────


def _inject_failure_on_nth(store_obj, monkeypatch, nth: int = 1) -> None:
    """Одноразовый отказ шва подготовки события (транзиентный сбой
    хранилища, прецедент P08/P10)."""
    cls = type(store_obj)
    original = cls._prepare_stored_event
    calls = {"n": 0}

    def failing(self, event, seq):
        calls["n"] += 1
        if calls["n"] == nth:
            raise RuntimeError("injected mid-batch failure")
        return original(self, event, seq)

    monkeypatch.setattr(cls, "_prepare_stored_event", failing)


def _inject_cache_save_failure(monkeypatch, times: int = 1) -> None:
    """Одноразовый отказ сохранения слоя 1 (cache) -- «Отказ cache не
    отменяет committed событие» (п.2). Redis-семантика имитируется
    честно: get() возвращает КОПИЮ документа (мутации не проходят по
    ссылке), save с отказом не меняет хранимый документ."""
    from copy import deepcopy

    original = MemorySessionStore.save
    state = {"left": times}

    def failing_save(self, session):
        if state["left"] > 0:
            state["left"] -= 1
            raise RuntimeError("injected cache failure")
        return original(self, session)

    monkeypatch.setattr(MemorySessionStore, "save", failing_save)

    original_get_or_create = MemorySessionStore.get_or_create

    def copy_get_or_create(self, session_id):
        stored = original_get_or_create(self, session_id)
        # Redis-семантика: читатель работает с копией документа;
        # несохранённые мутации не видны следующему get().
        return deepcopy(stored) if stored is not None else None

    original_get = MemorySessionStore.get

    def copy_get(self, session_id):
        stored = original_get(self, session_id)
        return deepcopy(stored) if stored is not None else None

    monkeypatch.setattr(MemorySessionStore, "get", copy_get)
    monkeypatch.setattr(MemorySessionStore, "get_or_create", copy_get_or_create)


# ── REST-хелперы (паттерн AUDIT-2A) ──────────────────────────────────

ENDPOINT_MAPS: dict[str, dict[str, Any]] = {
    "/eda-checks": {
        "key": "checks",
        "registry": STAGE_NODES["eda"],
        "statuses": None,  # заполняется из EDA_CHECK_STATUS_VALUES
    },
}


def _monitor_csv() -> str:
    import pandas as pd

    idx = [datetime(2026, 2, 1) + timedelta(days=i) for i in range(150)]
    frame = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in idx],
            "value": [120.0 + i for i in range(150)],
            "humidity": [40.0 + (i % 7) * 0.5 for i in range(150)],
        }
    )
    return frame.to_csv(index=False)


def _upload() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "forecast_monitor_synthetic_n150.csv",
            io.BytesIO(_monitor_csv().encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def _seed() -> tuple[str, str]:
    _upload()
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    context_id = trace.get("context_id") or ""
    assert run_id and context_id, "seed: загрузка должна фиксировать запуск и контекст"
    return run_id, context_id


def _demo_run() -> ResearchRun:
    client.post("/v1/session/demo")
    from apps.api import research_runs

    return research_runs.get_research_run_store().list_runs()[0]


def _task_of(store_obj, operation_id: str):
    return store_obj.delivery_outbox.get_task(operation_id)


# ── store-хелперы (уровень commit_event_batch) ───────────────────────


def _simple_run(run_id: str, **kwargs: Any) -> ResearchRun:
    defaults: dict[str, Any] = {
        "run_id": run_id,
        "session_id": "sess-6b",
        "dataset_fingerprint": "b" * 64,
        "dataset_name": "six_b.csv",
        "created_at": _now_iso(),
        "last_active_at": _now_iso(),
    }
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _simple_events(run_id: str, count: int) -> tuple:
    return tuple(
        make_trace_event(
            "upload_stop_status", stage="upload",
            node_id="structure_confirmed", run_id=run_id, idx=i,
        )
        for i in range(count)
    )


def _mirror_task(run_id: str, events, operation_id: str, *,
                 session_id: str = "sess-6b", **kwargs: Any):
    from apps.api import delivery_outbox

    return delivery_outbox.layer1_mirror_task(
        session_id=session_id,
        run_id=run_id,
        events=list(events),
        operation_id=operation_id,
        **kwargs,
    )


# ══ 1. Реестр producers (п.1) ════════════════════════════════════════


class TestProducerRegistry:
    """П.1: гарантия действует только для ЯВНО мигрированных required-
    путей; advisory -- честно перечислен."""

    def test_required_producers_enumerated(self):
        from apps.api import delivery_outbox

        required = delivery_outbox.REQUIRED_PRODUCERS
        assert set(required) == {
            "progress_maps_v2",
            "runs.pause",
            "runs.resume",
            "runs.checkpoint",
            "runs.restore",
        }
        # Каждый required несёт содержательный паттерн ключа
        # идемпотентности (basis повтора по operation_id).
        for producer, key_pattern in required.items():
            assert key_pattern, producer
            assert "{" in key_pattern and "}" in key_pattern, producer

    def test_advisory_producers_enumerated(self):
        from apps.api import delivery_outbox

        advisory = delivery_outbox.ADVISORY_PRODUCERS
        # Хук-зеркало после ответа (P09/P22) -- advisory по п.8;
        # легаси-карты -- compatibility mode; мутации DataFrame коррекций
        # -- unmigrated (граница карточки: «Не обещать гарантированное
        # документирование для unmigrated handlers»).
        assert "trace_hook_mirror" in advisory
        assert "progress_maps_legacy" in advisory
        assert "corrections_dataframe" in advisory
        # Пересечения запрещены: путь либо required, либо advisory.
        assert not set(advisory) & set(delivery_outbox.REQUIRED_PRODUCERS)

    def test_delivery_kinds_bounded_to_projection(self):
        """П.5: retry доставляет факт/проекцию и НЕ повторяет научную
        операцию -- реестр видов задач ограничен проекционными kind'ами."""
        from apps.api import delivery_outbox

        assert set(delivery_outbox.DELIVERY_KINDS) == {"layer1_mirror"}


# ══ 2. Outbox-контракт хранилищ (п.4, I8) ════════════════════════════


class TestOutboxContract:
    @pytest.fixture(autouse=True)
    def _runs_for_outbox(self, store):
        """FK-паритет живого Postgres: outbox ссылается на существующие
        запуски (регистрация через commit всегда идёт вместе с run той
        же транзакцией; standalone-регистрация тестов -- на тех же
        запусках)."""
        store.upsert_run(_simple_run("RUN-6B01"))
        store.upsert_run(_simple_run("RUN-6B02"))
        yield

    def _task(self, run_id: str, operation_id: str, **kwargs: Any) -> Any:
        from apps.api import delivery_outbox

        return delivery_outbox.layer1_mirror_task(
            session_id="sess-1",
            run_id=run_id,
            events=[
                make_trace_event(
                    "run_paused", stage="upload", node_id=None,
                    run_id=run_id, op=operation_id,
                )
            ],
            operation_id=operation_id,
            **kwargs,
        )

    def test_store_exposes_outbox(self, store):
        """П.4: outbox живёт в том же устойчивом хранилище, что ledger --
        store предоставляет его как часть своего контракта."""
        assert store.delivery_outbox is not None

    def test_register_and_get_roundtrip(self, store):
        from apps.api import delivery_outbox

        outbox = store.delivery_outbox
        task = self._task("RUN-6B01", "op-1")
        outbox.register(task)
        loaded = outbox.get_task("op-1")
        assert loaded is not None
        assert loaded.operation_id == "op-1"
        assert loaded.run_id == "RUN-6B01"
        assert loaded.kind == "layer1_mirror"
        assert loaded.state == delivery_outbox.STATE_PENDING
        assert loaded.idempotency_key == task.idempotency_key
        # Глубокие копии: мутация прочитанного payload не портит stored.
        loaded.payload["events"].clear()
        assert outbox.get_task("op-1").payload["events"]

    def test_get_task_unknown_none(self, store):
        assert store.delivery_outbox.get_task("no-such-op") is None

    def test_list_due_ordering_and_filters(self, store):
        from apps.api import delivery_outbox

        outbox = store.delivery_outbox
        outbox.register(self._task("RUN-6B01", "op-now"))
        future = self._task(
            "RUN-6B01", "op-future",
            next_attempt_at="2099-01-01T00:00:00+00:00",
        )
        outbox.register(future)
        earlier = self._task(
            "RUN-6B01", "op-earlier",
            next_attempt_at="2000-01-01T00:00:00+00:00",
        )
        outbox.register(earlier)
        delivered = self._task("RUN-6B01", "op-done")
        outbox.register(delivered)
        outbox.mark_delivered("op-done", delivered_at=_now_iso())

        due = outbox.list_due(now="2026-01-01T00:00:00+00:00", limit=10)
        ids = [task.operation_id for task in due]
        # Только pending к сроку; будущий и доставленный не идут.
        assert "op-earlier" in ids and "op-now" in ids
        assert "op-future" not in ids and "op-done" not in ids
        # Порядок срочности: немедленные (без next_attempt_at) -- первыми,
        # затем по возрастанию next_attempt_at.
        assert ids.index("op-now") < ids.index("op-earlier")

    def test_mark_failed_increments_and_expires_to_failed(self, store):
        from apps.api import delivery_outbox

        outbox = store.delivery_outbox
        task = self._task("RUN-6B01", "op-x", max_attempts=2)
        outbox.register(task)
        assert outbox.mark_failed(
            "op-x", error="boom", next_attempt_at=_now_iso(), at=_now_iso(),
        )
        assert outbox.get_task("op-x").state == delivery_outbox.STATE_PENDING
        assert outbox.get_task("op-x").attempts == 1
        assert outbox.get_task("op-x").last_error == "boom"
        assert outbox.mark_failed(
            "op-x", error="boom-2", next_attempt_at=_now_iso(), at=_now_iso(),
        )
        expired = outbox.get_task("op-x")
        assert expired.state == delivery_outbox.STATE_FAILED
        assert expired.attempts == 2
        # Исчерпанный не доставляется повторно автоматом.
        assert outbox.list_due(now=_now_iso(), limit=10) == []

    def test_backlog_counts_by_state(self, store):
        from apps.api import delivery_outbox

        outbox = store.delivery_outbox
        outbox.register(self._task("RUN-6B01", "op-a"))
        outbox.register(self._task("RUN-6B01", "op-b"))
        outbox.mark_delivered("op-b", delivered_at=_now_iso())
        outbox.register(self._task("RUN-6B01", "op-c", max_attempts=1))
        outbox.mark_failed("op-c", error="x", next_attempt_at=_now_iso(), at=_now_iso())
        backlog = outbox.backlog()
        assert backlog[delivery_outbox.STATE_PENDING] == 1
        assert backlog[delivery_outbox.STATE_DELIVERED] == 1
        assert backlog[delivery_outbox.STATE_FAILED] == 1

    def test_list_by_run_scoped(self, store):
        outbox = store.delivery_outbox
        outbox.register(self._task("RUN-6B01", "op-a"))
        outbox.register(self._task("RUN-6B02", "op-b"))
        ids = {task.operation_id for task in outbox.list_by_run("RUN-6B01")}
        assert ids == {"op-a"}

    def test_mark_missing_task_is_safe(self, store):
        outbox = store.delivery_outbox
        assert outbox.mark_delivered("ghost", delivered_at=_now_iso()) is False
        assert outbox.mark_failed(
            "ghost", error="x", next_attempt_at=_now_iso(), at=_now_iso(),
        ) is False


# ══ 3. Атомарное обязательство (п.3/п.4; crash до/после commit) ══════


class TestAtomicObligation:
    """Обязательство доставки регистрируется В ТОЙ ЖЕ транзакции, что
    события: crash ДО commit -- нет ни фактов, ни обязательства; после --
    есть и то и другое. Дедуп commit не дублирует обязательство."""

    def test_mid_batch_failure_leaves_no_obligation(self, store, monkeypatch):
        run_id = "RUN-6BAT01"
        store.upsert_run(_simple_run(run_id))
        events = _simple_events(run_id, 3)
        task = _mirror_task(run_id, events, operation_id="op-atomic")
        _inject_failure_on_nth(store, monkeypatch, nth=2)
        with pytest.raises(RuntimeError, match="injected"):
            store.commit_event_batch(
                CommitEventBatch(
                    run=_simple_run(run_id),
                    events=events,
                    idempotency_key="K-6B-atomic",
                    body_fingerprint=batch_body_fingerprint(run_id, events),
                    delivery_task=task,
                )
            )
        # Crash ДО commit: ноль событий, прежние метаданные...
        assert store.list_events(run_id) == []
        assert store.get_commit_receipt("K-6B-atomic") is None
        # ...и НЕТ обязательства (оно не переживает несостоявшийся commit).
        assert _task_of(store, "op-atomic") is None

    def test_commit_registers_obligation_atomically(self, store):
        from apps.api import delivery_outbox

        run_id = "RUN-6BAT02"
        events = _simple_events(run_id, 2)
        task = _mirror_task(run_id, events, operation_id="op-ok")
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=_simple_run(run_id),
                events=events,
                idempotency_key="K-6B-ok",
                body_fingerprint=batch_body_fingerprint(run_id, events),
                delivery_task=task,
            )
        )
        loaded = _task_of(store, "op-ok")
        assert loaded is not None
        assert loaded.state == delivery_outbox.STATE_PENDING
        # Связь обязательства с receipt -- по ключу идемпотентности.
        assert loaded.idempotency_key == "K-6B-ok"
        assert receipt.idempotency_key == "K-6B-ok"

    def test_dedup_commit_does_not_duplicate_obligation(self, store):
        from apps.api import delivery_outbox

        run_id = "RUN-6BAT03"
        events = _simple_events(run_id, 1)
        batch_kwargs = dict(
            run=_simple_run(run_id),
            events=events,
            idempotency_key="K-6B-dedup",
            body_fingerprint=batch_body_fingerprint(run_id, events),
            delivery_task=_mirror_task(run_id, events, operation_id="op-dedup"),
        )
        store.commit_event_batch(CommitEventBatch(**batch_kwargs))
        store.commit_event_batch(CommitEventBatch(**batch_kwargs))
        outbox = store.delivery_outbox
        # Обязательство одно (повтор доставки не порождает новое).
        assert outbox.get_task("op-dedup") is not None
        assert outbox.backlog()[delivery_outbox.STATE_PENDING] == 1
        # Второй commit вернул прежний receipt: события не задвоены.
        assert len(store.list_events(run_id)) == 1

    def test_checkpoints_register_in_batch_transaction(self, store):
        """П.3: ссылка на артефакт + операционное состояние + событие --
        одна транзакция: расширение батча чекпоинтами."""
        run_id = "RUN-6BAT04"
        event = make_trace_event(
            "checkpoint_saved", stage="upload", node_id=None, run_id=run_id
        )
        checkpoint = ResearchCheckpoint(
            checkpoint_id="cp-6b-1", run_id=run_id, event_id="anchor-1",
            label="cp", watermark=0,
        )
        store.commit_event_batch(
            CommitEventBatch(
                run=_simple_run(run_id),
                events=(event,),
                checkpoints=(checkpoint,),
                idempotency_key=f"event:{run_id}:{event.event_id}",
                body_fingerprint=batch_body_fingerprint(run_id, (event,)),
            )
        )
        listed = store.list_checkpoints(run_id)
        assert [cp.checkpoint_id for cp in listed] == ["cp-6b-1"]
        assert store.list_events(run_id)[-1].event_type == "checkpoint_saved"

    def test_checkpoint_batch_failure_registers_nothing(self, store, monkeypatch):
        run_id = "RUN-6BAT05"
        store.upsert_run(_simple_run(run_id))
        event = make_trace_event(
            "checkpoint_saved", stage="upload", node_id=None, run_id=run_id
        )
        checkpoint = ResearchCheckpoint(
            checkpoint_id="cp-6b-2", run_id=run_id, event_id="anchor-1",
            label="cp", watermark=0,
        )
        _inject_failure_on_nth(store, monkeypatch, nth=1)
        with pytest.raises(RuntimeError, match="injected"):
            store.commit_event_batch(
                CommitEventBatch(
                    run=_simple_run(run_id),
                    events=(event,),
                    checkpoints=(checkpoint,),
                    idempotency_key=f"event:{run_id}:{event.event_id}",
                    body_fingerprint=batch_body_fingerprint(run_id, (event,)),
                )
            )
        # Ни чекпоинта, ни события -- атомарность регистрации артефакта.
        assert store.list_checkpoints(run_id) == []
        assert store.list_events(run_id) == []


# ══ 4. Required-доставка карты: cache отказал, ledger держит (п.2) ═══


class TestMapDeliveryRecovery:
    def _post_map(self, run_id: str, context_id: str, report_id: str):
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

    def _layer1_event_count(self, run_id: str, event_type: str) -> int:
        from apps.api.session_store import SESSION_COOKIE_NAME

        session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
        session = get_session_store().get(session_id)
        if session is None:
            return 0
        return sum(
            1
            for item in session.pipeline_trace
            if item.get("event_type") == event_type
        )

    def test_cache_failure_keeps_committed_event_and_worker_recovers(
        self, monkeypatch
    ):
        """П.2: отчёт фиксируется ledger'ом ДО durable receipt; отказ
        cache НЕ отменяет committed событие; worker восстанавливает
        проекцию слоя 1 из факта."""
        from apps.api import delivery_outbox, research_runs

        run_id, context_id = _seed()
        run_store = research_runs.get_research_run_store()
        ledger_before = len(run_store.list_events(run_id))

        _inject_cache_save_failure(monkeypatch, times=1)
        resp = self._post_map(run_id, context_id, "report-6b-cache")
        assert resp.status_code == 500, resp.text
        detail = resp.json()["detail"]
        # Честная ошибка: committed/projection_pending, а не фиктивный
        # rollback (п.6): ответ называет состояние, operation_id и позицию.
        assert "committed_projection_pending" in detail
        assert "report-6b-cache" in detail

        # Событие committed: ledger держит карту, receipt существует.
        receipt = run_store.get_commit_receipt(f"report:{run_id}:report-6b-cache")
        assert receipt is not None
        events = run_store.list_events(run_id)
        assert len(events) == ledger_before + len(STAGE_NODES["eda"])
        watermark = receipt.committed_watermark
        assert watermark >= len(STAGE_NODES["eda"])

        # Обязательство переживает отказ cache: pending, тот же operation_id.
        task = _task_of(run_store, "report-6b-cache")
        assert task is not None
        assert task.state == delivery_outbox.STATE_PENDING

        # Слой 1 не получил карту (cache отказал).
        assert (
            self._layer1_event_count(run_id, "eda_check_status") == 0
        )

        # Worker доставляет проекцию из факта.
        summary = delivery_outbox.run_delivery_recovery(run_store)
        assert summary["delivered"] >= 1
        assert (
            self._layer1_event_count(run_id, "eda_check_status")
            == len(STAGE_NODES["eda"])
        )
        assert _task_of(run_store, "report-6b-cache").state == (
            delivery_outbox.STATE_DELIVERED
        )

        # Повтор поставки того же тела -- прежний receipt, ноль новых
        # фактов (R5: retry по operation_id не повторяет операцию).
        resp2 = self._post_map(run_id, context_id, "report-6b-cache")
        assert resp2.status_code == 200
        assert resp2.json()["deduplicated"] is True
        assert len(run_store.list_events(run_id)) == ledger_before + len(
            STAGE_NODES["eda"]
        )
        assert (
            self._layer1_event_count(run_id, "eda_check_status")
            == len(STAGE_NODES["eda"])
        )

    def test_worker_twice_is_idempotent(self, monkeypatch):
        """R5: двойной прогон worker -- одна копия факта в слое 1
        («worker дважды» RED-карточки)."""
        from apps.api import delivery_outbox, research_runs

        run_id, context_id = _seed()
        run_store = research_runs.get_research_run_store()
        _inject_cache_save_failure(monkeypatch, times=1)
        assert self._post_map(run_id, context_id, "report-6b-twice").status_code == 500

        first = delivery_outbox.run_delivery_recovery(run_store)
        second = delivery_outbox.run_delivery_recovery(run_store)
        assert first["delivered"] >= 1
        # Второй прогон: доставлять нечего, копий нет.
        assert second["delivered"] == 0
        assert (
            self._layer1_event_count(run_id, "eda_check_status")
            == len(STAGE_NODES["eda"])
        )

    def test_worker_does_not_run_scientific_operations(self):
        """П.5: виды задач ограничены проекцией -- worker физически не
        имеет вида «повторить коррекцию»; неизвестный kind -- отказ, а не
        изобретение операции."""
        from apps.api import delivery_outbox, research_runs

        run_store = research_runs.get_research_run_store()
        run_id = "RUN-6BWK01"
        run_store.upsert_run(_simple_run(run_id))
        event = make_trace_event(
            "run_paused", stage="upload", node_id=None, run_id=run_id
        )
        from apps.api import delivery_outbox

        task = delivery_outbox.DeliveryTask(
            operation_id="op-wrong-kind",
            idempotency_key="",
            run_id=run_id,
            kind="replay_correction",
            payload={"session_id": "sess-6b", "events": [event.to_dict()]},
            max_attempts=1,
        )
        run_store.delivery_outbox.register(task)
        summary = delivery_outbox.run_delivery_recovery(run_store)
        # Неизвестный kind -- failed (попытка учтена), операция не
        # изобретается: событий больше не стало.
        assert summary["failed"] >= 1
        assert run_store.list_events(run_id) == []
        assert _task_of(run_store, "op-wrong-kind").state == (
            delivery_outbox.STATE_FAILED
        )


# ══ 5. Run-level операции: атомарность + обязательство (P08/P10) ═════


class TestRunLevelOpsRequired:
    """Миграция pause/resume/checkpoint/restore из advisory-пары
    (set_run_status/upsert_run + append_event) в атомарный батч:
    seam между двумя записями устранён (P08/P10 fault timeline)."""

    def test_pause_atomic_and_required_delivery(self):
        """Успешная пауза: статус+событие одной операцией; обязательство
        доставки в слой 1 зарегистрировано и доставлено синхронно."""
        from apps.api import delivery_outbox, research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        ledger_before = len(run_store.list_events(run.run_id))
        resp = client.post(f"/v1/progress/runs/{run.run_id}/pause")
        assert resp.status_code == 200, resp.text
        event_id = resp.json()["event"]["event_id"]

        # Статус и событие -- одной транзакцией (обе записи есть).
        assert run_store.get_run(run.run_id).status == "paused"
        events = run_store.list_events(run.run_id)
        assert len(events) == ledger_before + 1
        assert events[-1].event_type == "run_paused"

        # Required-путь: обязательство существовало и доставлено
        # синхронно (cache жив).
        task = _task_of(run_store, event_id)
        assert task is not None
        assert task.state == delivery_outbox.STATE_DELIVERED
        assert task.idempotency_key == f"event:{run.run_id}:{event_id}"

    def test_pause_mid_batch_failure_is_honest_not_executed(self, monkeypatch):
        """P10-seam устранён: отказ в середине фиксации оставляет
        статус И событие прежними; 503 без заявления rollback."""
        from apps.api import research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        _inject_failure_on_nth(run_store, monkeypatch, nth=1)
        resp = client.post(f"/v1/progress/runs/{run.run_id}/pause")
        assert resp.status_code == 503, resp.text
        # Ни статуса, ни события: seam'а между двумя записями больше нет.
        assert run_store.get_run(run.run_id).status == "active"
        assert all(
            event.event_type != "run_paused"
            for event in run_store.list_events(run.run_id)
        )

    def test_resume_required_delivery(self):
        from apps.api import delivery_outbox, research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        client.post(f"/v1/progress/runs/{run.run_id}/pause")
        resp = client.post(f"/v1/progress/runs/{run.run_id}/resume")
        assert resp.status_code == 200, resp.text
        event_id = resp.json()["event"]["event_id"]
        assert run_store.get_run(run.run_id).status == "active"
        task = _task_of(run_store, event_id)
        assert task is not None
        assert task.state == delivery_outbox.STATE_DELIVERED

    def test_restore_atomic_with_delivery_task(self):
        """Restore: run-метаданные (новый контекст raw-входа) + run_resumed
        -- одной транзакцией; обязательство доставки выполнено."""
        from apps.api import delivery_outbox, research_runs
        from apps.api.session_store import SESSION_COOKIE_NAME

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        resp = client.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "raw"
        updated = run_store.get_run(run.run_id)
        assert updated.status == "active"
        resumed_events = [
            event
            for event in run_store.list_events(run.run_id)
            if event.event_type == "run_resumed" and event.payload.get("restored")
        ]
        assert resumed_events, "restore обязан записать run_resumed (restored=true)"
        resumed = resumed_events[-1]
        task = _task_of(run_store, resumed.event_id)
        assert task is not None
        assert task.state == delivery_outbox.STATE_DELIVERED
        # Слой 1 НОВОЙ сессии содержит факт (синхронное зеркало).
        new_session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert new_session is not None
        assert any(
            item.get("event_type") == "run_resumed"
            for item in new_session.pipeline_trace
        )

    def test_restore_mid_batch_failure_keeps_previous_metadata(self, monkeypatch):
        """P10-seam restore устранён: отказ в середине фиксации не
        сдвигает контекст/статус запуска и не оставляет событие."""
        from apps.api import research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        context_before = run_store.get_run(run.run_id).context_id
        _inject_failure_on_nth(run_store, monkeypatch, nth=1)
        resp = client.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 503, resp.text
        updated = run_store.get_run(run.run_id)
        assert updated.context_id == context_before
        assert all(
            not (event.event_type == "run_resumed" and event.payload.get("restored"))
            for event in run_store.list_events(run.run_id)
        )


# ══ 6. Артефакты чекпоинта: staged + sweep (п.3/п.7) ═════════════════


class TestCheckpointStagedArtifact:
    def _anchor_event_id(self, run_id: str) -> str:
        from apps.api import research_runs

        return research_runs.get_research_run_store().list_events(run_id)[0].event_id

    def _snapshot_files(self, run_id: str) -> list:
        from apps.api.research_runs import get_dataset_file_store

        return get_dataset_file_store().checkpoint_snapshot_files(run_id)

    def test_checkpoint_success_registers_artifact_atomically(self):
        """Успех: staged-снимок на диске + ссылка + событие -- одной
        транзакцией; обязательство доставки исполнено."""
        from apps.api import delivery_outbox, research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        payload = {
            "event_id": self._anchor_event_id(run.run_id),
            "label": "cp-6b-ok",
        }
        resp = client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints", json=payload
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        checkpoints = run_store.list_checkpoints(run.run_id)
        assert [cp.checkpoint_id for cp in checkpoints] == [
            body["checkpoint"]["checkpoint_id"]
        ]
        assert any(
            event.event_type == "checkpoint_saved"
            for event in run_store.list_events(run.run_id)
        )
        # Артефакт подготовлен до фиксации и существует после неё.
        files = self._snapshot_files(run.run_id)
        assert len(files) == 1
        saved = [
            event
            for event in run_store.list_events(run.run_id)
            if event.event_type == "checkpoint_saved"
        ][-1]
        task = _task_of(run_store, saved.event_id)
        assert task is not None
        assert task.state == delivery_outbox.STATE_DELIVERED

    def test_commit_failure_leaves_staged_file_and_sweep_cleans(self, monkeypatch):
        """П.7: DB-транзакция НЕ делает файловую запись атомарной --
        упавший commit оставляет staged-файл; sweep staged cleanup
        удаляет осиротевший снимок, повторный sweep -- no-op."""
        from apps.api import research_runs
        from apps.api.research_runs import get_dataset_file_store

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        _inject_failure_on_nth(run_store, monkeypatch, nth=1)
        resp = client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={
                "event_id": self._anchor_event_id(run.run_id),
                "label": "cp-6b-fail",
            },
        )
        assert resp.status_code == 503, resp.text
        # Ничего не зарегистрировано...
        assert run_store.list_checkpoints(run.run_id) == []
        assert all(
            event.event_type != "checkpoint_saved"
            for event in run_store.list_events(run.run_id)
        )
        # ...но staged-файл остался (честная граница файловой записи).
        files = self._snapshot_files(run.run_id)
        assert len(files) == 1

        # Sweep staged cleanup (п.7) -- операция контура доставки над
        # примитивами файлового слоя.
        from apps.api.delivery_outbox import sweep_orphaned_checkpoints

        removed = sweep_orphaned_checkpoints(
            run_store, get_dataset_file_store(), run_ids=[run.run_id]
        )
        assert len(removed) == 1
        assert self._snapshot_files(run.run_id) == []
        # Повторный запуск -- no-op (п.7: повторный recovery безопасен).
        assert sweep_orphaned_checkpoints(
            run_store, get_dataset_file_store(), run_ids=[run.run_id]
        ) == []


# ══ 7. Delivery-эндпоинт: состояния и watermark (п.6/п.8) ════════════


class TestDeliveryEndpoint:
    def test_unknown_operation_is_not_executed(self):
        from apps.api import delivery_outbox

        run = _demo_run()
        resp = client.get(
            f"/v1/progress/runs/{run.run_id}/delivery/no-such-op"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["state"] == delivery_outbox.OP_NOT_EXECUTED
        assert data["receipt"] is None

    def test_unknown_run_404(self):
        resp = client.get("/v1/progress/runs/RUN-DEAD000/delivery/whatever")
        assert resp.status_code == 404

    def test_states_pending_delivered_and_receipt_watermark(self, monkeypatch):
        """П.8: read-after-write -- либо состояние с receipt/watermark,
        либо честное ожидающее; watermark достижим в /trace."""
        from apps.api import delivery_outbox, research_runs

        run_id, context_id = _seed()
        run_store = research_runs.get_research_run_store()
        _inject_cache_save_failure(monkeypatch, times=1)
        from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES

        checks = {
            node_id: list(EDA_CHECK_STATUS_VALUES)[i % len(EDA_CHECK_STATUS_VALUES)]
            for i, node_id in enumerate(STAGE_NODES["eda"])
        }
        assert client.post(
            "/v1/progress/eda-checks",
            json={
                "checks": checks,
                "schema_version": 2,
                "run_id": run_id,
                "context_id": context_id,
                "report_id": "report-6b-state",
            },
        ).status_code == 500

        # Pending-обязательство: committed, проекция ожидает.
        resp = client.get(
            f"/v1/progress/runs/{run_id}/delivery/report-6b-state"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == delivery_outbox.OP_COMMITTED_PROJECTION_PENDING
        assert data["receipt"] is not None
        watermark = data["receipt"]["committed_watermark"]
        assert watermark >= len(STAGE_NODES["eda"])

        # Read-your-write по watermark: ledger держит позицию.
        trace = client.get("/v1/progress/trace").json()
        assert trace["events_total"] >= watermark

        # Worker доставил -- состояние delivered, receipt прежний.
        delivery_outbox.run_delivery_recovery(run_store)
        resp2 = client.get(
            f"/v1/progress/runs/{run_id}/delivery/report-6b-state"
        )
        data2 = resp2.json()
        assert data2["state"] == delivery_outbox.OP_DELIVERED
        assert data2["delivery_state"] == delivery_outbox.STATE_DELIVERED
        assert data2["receipt"]["committed_watermark"] == watermark

    def test_failed_state_visible(self, monkeypatch):
        """R6: исчерпанный бюджет попыток -- честный failed, а не тихое
        исчезновение обязательства."""
        from apps.api import delivery_outbox, research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        event = make_trace_event(
            "run_paused", stage="upload", node_id=None, run_id=run.run_id
        )
        task = _mirror_task(
            run.run_id, (event,), operation_id="op-fail-visible", max_attempts=1
        )
        run_store.delivery_outbox.register(task)
        run_store.delivery_outbox.mark_failed(
            "op-fail-visible", error="cache down",
            next_attempt_at=_now_iso(), at=_now_iso(),
        )
        resp = client.get(
            f"/v1/progress/runs/{run.run_id}/delivery/op-fail-visible"
        )
        data = resp.json()
        assert data["state"] == delivery_outbox.OP_FAILED
        assert data["last_error"] == "cache down"
        assert data["attempts"] == 1

    def test_delivery_list_per_run(self, monkeypatch):
        from apps.api import delivery_outbox, research_runs

        run = _demo_run()
        run_store = research_runs.get_research_run_store()
        event = make_trace_event(
            "run_paused", stage="upload", node_id=None, run_id=run.run_id
        )
        run_store.delivery_outbox.register(
            _mirror_task(run.run_id, (event,), operation_id="op-list-1")
        )
        resp = client.get(f"/v1/progress/runs/{run.run_id}/delivery")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run.run_id
        ids = {task["operation_id"] for task in data["tasks"]}
        assert "op-list-1" in ids
        assert data["counts_by_state"][delivery_outbox.STATE_PENDING] >= 1


# ══ 8. Классификатор состояний (п.6) ═════════════════════════════════


class TestOperationClassifier:
    def _receipt(self, watermark: int = 3):
        from apps.api.research_runs import CommitReceipt

        return CommitReceipt(
            idempotency_key="event:R:op", run_id="R", context_id=None,
            accepted_event_ids=("e1",), committed_watermark=watermark,
        )

    def _task(self, state: str):
        from apps.api import delivery_outbox

        return delivery_outbox.DeliveryTask(
            operation_id="op", idempotency_key="event:R:op", run_id="R",
            kind="layer1_mirror", payload={}, state=state,
        )

    def test_not_executed(self):
        from apps.api import delivery_outbox

        assert delivery_outbox.classify_operation(None, None) == (
            delivery_outbox.OP_NOT_EXECUTED
        )

    def test_committed_projection_pending(self):
        from apps.api import delivery_outbox

        assert delivery_outbox.classify_operation(
            self._receipt(), self._task(delivery_outbox.STATE_PENDING)
        ) == delivery_outbox.OP_COMMITTED_PROJECTION_PENDING
        # Обязательство без receipt (защитная ветка) -- не «успех».
        assert delivery_outbox.classify_operation(
            None, self._task(delivery_outbox.STATE_PENDING)
        ) == delivery_outbox.OP_COMMITTED_PROJECTION_PENDING

    def test_delivered(self):
        from apps.api import delivery_outbox

        assert delivery_outbox.classify_operation(
            self._receipt(), self._task(delivery_outbox.STATE_DELIVERED)
        ) == delivery_outbox.OP_DELIVERED

    def test_failed(self):
        from apps.api import delivery_outbox

        assert delivery_outbox.classify_operation(
            self._receipt(), self._task(delivery_outbox.STATE_FAILED)
        ) == delivery_outbox.OP_FAILED

    def test_executed_documentation_pending(self):
        """Мутация научных данных исполнена, документирование не
        зафиксировано -- честное состояние, не «rollback» (п.6)."""
        from apps.api import delivery_outbox

        assert delivery_outbox.classify_operation(
            None, None, mutation_applied=True
        ) == delivery_outbox.OP_EXECUTED_DOCUMENTATION_PENDING


# ══ 9. Живой Postgres: restart-выживание (план §17 GREEN) ════════════


class TestPostgresRestartSurvival:
    @pytest.mark.skipif(
        not PG_DSN, reason="CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен"
    )
    def test_receipt_and_obligation_survive_store_restart(self):
        """«Устойчивый тестовый restart не теряет принятые required-факты»:
        обязательство и receipt читаются НОВЫМ экземпляром store (новые
        соединения), worker нового экземпляра доставляет проекцию."""
        from apps.api import delivery_outbox

        pg = PostgresResearchRunStore(dsn=PG_DSN)
        run_id = f"RUN-6BRST-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
        events = _simple_events(run_id, 2)
        task = _mirror_task(
            run_id, events, operation_id="op-restart", session_id="sess-6b-rst"
        )
        pg.commit_event_batch(
            CommitEventBatch(
                run=_simple_run(run_id),
                events=events,
                idempotency_key="K-6B-restart",
                body_fingerprint=batch_body_fingerprint(run_id, events),
                delivery_task=task,
            )
        )

        # Restart: НОВЫЙ экземпляр store (новые соединения).
        fresh = PostgresResearchRunStore(dsn=PG_DSN)
        assert fresh.get_commit_receipt("K-6B-restart") is not None
        assert len(fresh.list_events(run_id)) == 2
        loaded = _task_of(fresh, "op-restart")
        assert loaded is not None
        assert loaded.state == delivery_outbox.STATE_PENDING

        # Worker нового экземпляра доставляет проекцию в cache.
        session_store = MemorySessionStore()
        session = AnalysisSession(session_id="sess-6b-rst")
        session.run_id = run_id
        session_store.save(session)
        summary = delivery_outbox.run_delivery_recovery(
            fresh, session_store=session_store
        )
        assert summary["delivered"] == 1
        restored = session_store.get("sess-6b-rst")
        assert sum(
            1
            for item in restored.pipeline_trace
            if item.get("event_type") == "upload_stop_status"
        ) == 2
        assert _task_of(fresh, "op-restart").state == (
            delivery_outbox.STATE_DELIVERED
        )

    @pytest.mark.skipif(
        not PG_DSN, reason="CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен"
    )
    def test_mid_batch_failure_on_live_pg_leaves_no_obligation(self, monkeypatch):
        """План §17 RED: «crash до ledger commit» на настоящем PostgreSQL
        -- rollback атомарен, обязательства нет."""
        pg = PostgresResearchRunStore(dsn=PG_DSN)
        run_id = f"RUN-6BRBF-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
        pg.upsert_run(_simple_run(run_id))
        events = _simple_events(run_id, 3)
        _inject_failure_on_nth(pg, monkeypatch, nth=2)
        with pytest.raises(RuntimeError, match="injected"):
            pg.commit_event_batch(
                CommitEventBatch(
                    run=_simple_run(run_id),
                    events=events,
                    idempotency_key="K-6B-rbf",
                    body_fingerprint=batch_body_fingerprint(run_id, events),
                    delivery_task=_mirror_task(run_id, events, operation_id="op-rbf"),
                )
            )
        assert pg.list_events(run_id) == []
        assert pg.get_commit_receipt("K-6B-rbf") is None
        assert _task_of(pg, "op-rbf") is None
