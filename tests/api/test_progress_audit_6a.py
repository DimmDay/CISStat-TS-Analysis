# tests/api/test_progress_audit_6a.py
"""Acceptance-тесты задачи AUDIT-6A (plan_progress_audit.md §7): атомарный
ledger «Прогресса» и одинаковые store-контракты.

Контракт (docs/progress_audit_contract.md, редакция v0.5-6A; план §7):

  * `commit_event_batch` -- ЕДИНАЯ транзакция хранилища: CAS-проверка
    expected context (контекст запуска, прочитанный продюсером), обновление
    run-метаданных, запись батча событий, регистрация idempotency key и
    receipt. Падение на середине батча оставляет НОЛЬ событий и ПРЕЖНИЕ
    метаданные (P08/P10 -- F05);
  * sequence назначается транзакционно с сериализацией по run: два
    конкурентных батча получают непрерывный префикс 1..N без дублей и
    дыр (BIGSERIAL сам по себе committed-order не удостоверяет);
  * receipt: idempotency key, run/context, принятые event ids, committed
    watermark. Повтор того же ключа/тела возвращает ПРЕЖНИЙ receipt
    (retry после потерянного ответа не дублирует); тот же ключ с другим
    телом -- конфликт БЕЗ записи;
  * stale context отклоняется ДО первой записи (CAS по контексту запуска);
  * parity (I8/P20/F07): Memory реализует тот же контракт дедупа,
    порядка, глубоких копий и batch-отказа, что Postgres; оба проходят
    ОДНИ и те же контрактные тесты;
  * durable envelope слоя 2 (граница AUDIT-C §14.5): v2-envelope события
    переживает запись/чтение в Postgres-строке (миграция 0002, `0001`
    не переписывается; legacy-корпус читается, sequence честно None).

Границы (план §7 «Граница»): Redis и изменение DataFrame в транзакцию НЕ
входят; P09 и контур доставки (outbox/повторы) -- AUDIT-6B, здесь не
объявляются устранёнными; advisory-продюсеры (pause/resume/checkpoint/
restore) остаются до своей миграции.

Postgres-контракт выполняется на ЖИВОМ временном Postgres (Донастройка_2
п.1: «живые contract-тесты обязательны; mock-SQL не замена»): DSN берётся
из CISSTAT_TEST_PG_DSN (тот же паттерн, что test_research_runs_postgres.py);
без DSN живая половина паритета честно skip (приёмка остаётся открытой).
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import (
    CommitConflictError,
    CommitEventBatch,
    CommitReceipt,
    IdempotencyConflictError,
    MemoryResearchRunStore,
    PostgresResearchRunStore,
    ResearchRun,
    batch_body_fingerprint,
)
from apps.api.trace_events import make_trace_event, stamp_envelope

from app.core.pipeline_graph import STAGE_NODES

PG_DSN = os.environ.get("CISSTAT_TEST_PG_DSN", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(run_id: str = "RUN-6ATEST01", **kwargs: Any) -> ResearchRun:
    defaults: dict[str, Any] = {
        "run_id": run_id,
        "session_id": "sess-6a",
        "dataset_fingerprint": "a" * 64,
        "dataset_name": "six_a.csv",
        "created_at": _now_iso(),
        "last_active_at": _now_iso(),
    }
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _events(run_id: str, count: int, *, tag: str = "b") -> tuple:
    return tuple(
        make_trace_event(
            "upload_stop_status",
            stage="upload",
            node_id="structure_confirmed",
            run_id=run_id,
            batch=tag,
            idx=i,
        )
        for i in range(count)
    )


# ── Хранилища: parity-параметризация (I8) ────────────────────────────


@pytest.fixture()
def memory_store() -> MemoryResearchRunStore:
    return MemoryResearchRunStore()


@pytest.fixture()
def pg_store() -> PostgresResearchRunStore:
    """Живой Postgres (Донастройка_2 п.1): чистая схема на каждый тест.
    Без CISSTAT_TEST_PG_DSN -- честный skip (приёмка живого PG остаётся
    открытой, план §7: «Если live PostgreSQL недоступен, соответствующая
    приёмка остаётся открытой»)."""
    if not PG_DSN:
        pytest.skip("CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен")
    try:
        import psycopg
    except ImportError:  # pragma: no cover - среда без драйвера
        pytest.skip("psycopg не установлен")
    conn = psycopg.connect(PG_DSN, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(
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
    """Parity-параметризация (I8): ОДНИ и те же контрактные тесты на
    обоих хранилищах. Живой PG резолвится ТОЛЬКО для postgres-параметра
    (memory-прогон не зависит от наличия DSN); без DSN -- честный skip
    живой половины паритета."""
    if request.param == "memory":
        return request.getfixturevalue("memory_store")
    return request.getfixturevalue("pg_store")


# ── Инъекция отказа на середине батча (шов записи) ───────────────────


def _inject_failure_on_nth(store_obj, monkeypatch, nth: int = 2) -> None:
    """Подмена шва подготовки события: ОДНОРАЗОВЫЙ отказ на N-м вызове
    (транзиентный сбой хранилища -- прецедент «процессной подмены save
    на исключение» H08). Последующие вызовы (в т.ч. честный retry)
    проходят -- ровно сценарий плана §7 «retry после потерянного
    receipt не дублирует»."""
    cls = type(store_obj)
    original = cls._prepare_stored_event
    calls = {"n": 0}

    def failing(self, event, seq):
        calls["n"] += 1
        if calls["n"] == nth:
            raise RuntimeError("injected mid-batch failure")
        return original(self, event, seq)

    monkeypatch.setattr(cls, "_prepare_stored_event", failing)


# ── 1. Атомарность батча (P08/P10, F05) ──────────────────────────────


class TestBatchAtomicity:
    def test_mid_batch_failure_leaves_zero_events_and_previous_metadata(
        self, store, monkeypatch
    ):
        """RED-критерий плана §7: падение на середине batch оставляет
        ноль событий и прежние метаданные (все-или-ничего, F05)."""
        store.upsert_run(_run(target_column=None, context_id="ctx-old"))
        events = _events("RUN-6ATEST01", 3)
        _inject_failure_on_nth(store, monkeypatch, nth=2)
        with pytest.raises(RuntimeError, match="injected"):
            store.commit_event_batch(
                CommitEventBatch(
                    run=_run(target_column="sales", context_id="ctx-new"),
                    events=events,
                    idempotency_key="K-atomic",
                    body_fingerprint=batch_body_fingerprint(
                        "RUN-6ATEST01", events, context_id="ctx-new"
                    ),
                )
            )
        # Ноль событий: журнал не содержит ЧАСТИЧНОГО батча.
        assert store.list_events("RUN-6ATEST01") == []
        # Прежние метаданные: ни target, ни контекст не сдвинулись.
        run = store.get_run("RUN-6ATEST01")
        assert run.target_column is None
        assert run.context_id == "ctx-old"
        # Вода́ забора не двинулась: повторный честный батч стартует с 1.
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=_run(target_column="sales", context_id="ctx-new"),
                events=events,
                idempotency_key="K-atomic",
                body_fingerprint=batch_body_fingerprint(
                    "RUN-6ATEST01", events, context_id="ctx-new"
                ),
            )
        )
        assert receipt.committed_watermark == 3
        assert [event.sequence for event in store.list_events("RUN-6ATEST01")] == [1, 2, 3]

    def test_run_and_events_commit_in_one_operation(self, store):
        """Run-метаданные и события фиксируются ОДНОЙ операцией: после
        commit ни одного раздельного upsert/append не осталось (план §7
        п.1: «проверка expected context, обновление run, запись событий,
        регистрация key и receipt в одной DB-транзакции»)."""
        store.commit_event_batch(
            CommitEventBatch(
                run=_run(target_column="sales", context_id="ctx-1"),
                events=_events("RUN-6ATEST01", 2),
            )
        )
        run = store.get_run("RUN-6ATEST01")
        assert run.target_column == "sales"
        assert run.context_id == "ctx-1"
        assert len(store.list_events("RUN-6ATEST01")) == 2


# ── 2. Порядок: sequence с сериализацией по run (F08/P12-основа) ─────


class TestSequenceAssignment:
    def test_sequence_stamped_by_store(self, store):
        """Sequence -- авторитетная позиция ledger, назначается store
        при фиксации (контракт §3.3 -- УТВЕРЖДЕНО-AUDIT-0); до 6A оба
        хранилища sequence не ставили."""
        store.commit_event_batch(
            CommitEventBatch(run=_run(), events=_events("RUN-6ATEST01", 2))
        )
        store.append_event(
            "RUN-6ATEST01",
            make_trace_event(
                "upload_stop_status", stage="upload",
                node_id="structure_confirmed", run_id="RUN-6ATEST01", idx=99,
            ),
        )
        events = store.list_events("RUN-6ATEST01")
        assert [event.sequence for event in events] == [1, 2, 3]

    def test_two_concurrent_batches_have_one_order(self, store):
        """RED-критерий плана §7: два конкурентных батча имеют один
        порядок -- непрерывный префикс 1..N без дублей и дыр
        (сериализация по run, BIGSERIAL-довод плана)."""
        run = _run()
        if isinstance(store, MemoryResearchRunStore):
            store1 = store2 = store
        else:
            store1 = PostgresResearchRunStore(dsn=PG_DSN)
            store2 = PostgresResearchRunStore(dsn=PG_DSN)

        def commit(tag: str):
            events = _events(run.run_id, 5, tag=tag)
            return store1.commit_event_batch(
                CommitEventBatch(
                    run=run,
                    events=events,
                    idempotency_key=f"conc-{tag}",
                    body_fingerprint=batch_body_fingerprint(run.run_id, events),
                )
            ), tag

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(commit, "A"), pool.submit(commit, "B")]
            results = [future.result() for future in futures]  # бросок = падение теста

        events = store.list_events(run.run_id)
        assert len(events) == 10
        sequences = sorted(event.sequence for event in events)
        assert sequences == list(range(1, 11))
        # Вода́м обеих поставок -- разные позиции, 10 -- максимум.
        watermarks = sorted(r.committed_watermark for r, _ in results)
        assert len(set(watermarks)) == 2
        assert watermarks[-1] == 10
        # Оба батча фиксируются (ни один не потерян, ни один не задублирован).
        assert sum(len(r.accepted_event_ids) for r, _ in results) == 10

    def test_batch_internal_and_corpus_dedup_keeps_order(self, store):
        """Дедуп внутри батча (первый occurrence) и против корпуса:
        повтор не переупорядочивает и не сдвигает sequence принятых."""
        first = _events("RUN-6ATEST01", 1)
        first_event = first[0]
        store.commit_event_batch(
            CommitEventBatch(run=_run(), events=first, idempotency_key="K1",
                             body_fingerprint=batch_body_fingerprint("RUN-6ATEST01", first))
        )
        dup_pair = (first_event,)  # тот же event_id, что уже в корпусе
        new_pair = _events("RUN-6ATEST01", 2, tag="c")
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=_run(),
                events=new_pair + dup_pair + new_pair[:1],  # дубль в батче + дубль корпуса
            )
        )
        # Приняты только ДВА новых (два occurrence повтора отброшены).
        assert len(receipt.accepted_event_ids) == 2
        assert receipt.committed_watermark == 3
        events = store.list_events("RUN-6ATEST01")
        assert len(events) == 3
        assert [event.sequence for event in events] == [1, 2, 3]


# ── 3. Идемпотентность: receipt (план §7 п.4) ────────────────────────


class TestReceiptIdempotency:
    def test_retry_after_lost_receipt_returns_same_receipt(self, store):
        """RED-критерий плана §7: retry после потерянного receipt не
        дублирует -- тот же ключ/тело возвращает прежний receipt."""
        events = _events("RUN-6ATEST01", 3)
        batch = CommitEventBatch(
            run=_run(),
            events=events,
            idempotency_key="op-7f3e",
            body_fingerprint=batch_body_fingerprint("RUN-6ATEST01", events),
        )
        first = store.commit_event_batch(batch)
        second = store.commit_event_batch(batch)  # ответ потерян, повтор
        assert second == first
        assert len(store.list_events("RUN-6ATEST01")) == 3
        assert first.committed_watermark == 3
        assert len(first.accepted_event_ids) == 3

    def test_same_key_different_body_conflicts_without_write(self, store):
        """Тот же ключ с другим телом -- конфликт БЕЗ записи (план §7
        п.4: «тот же ключ с другим телом -- конфликт без записи»)."""
        events = _events("RUN-6ATEST01", 2)
        store.commit_event_batch(
            CommitEventBatch(run=_run(), events=events, idempotency_key="op-7f3e",
                             body_fingerprint=batch_body_fingerprint("RUN-6ATEST01", events))
        )
        other = _events("RUN-6ATEST01", 1, tag="other")
        with pytest.raises(IdempotencyConflictError):
            store.commit_event_batch(
                CommitEventBatch(run=_run(), events=other, idempotency_key="op-7f3e",
                                 body_fingerprint=batch_body_fingerprint("RUN-6ATEST01", other))
            )
        assert len(store.list_events("RUN-6ATEST01")) == 2

    def test_receipt_shape_and_read_api(self, store):
        """Receipt содержит operation/report_id (ключ), run/context,
        принятые event ids, committed watermark (план §7 п.4) и читается
        отдельным API (получение потерянного receipt)."""
        events = _events("RUN-6ATEST01", 2)
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=_run(context_id="ctx-1"),
                events=events,
                idempotency_key="op-report-1",
                body_fingerprint=batch_body_fingerprint("RUN-6ATEST01", events),
            )
        )
        assert isinstance(receipt, CommitReceipt)
        assert receipt.idempotency_key == "op-report-1"
        assert receipt.run_id == "RUN-6ATEST01"
        assert receipt.context_id == "ctx-1"
        assert receipt.accepted_event_ids == tuple(event.event_id for event in events)
        assert receipt.committed_watermark == 2
        assert receipt.created_at
        loaded = store.get_commit_receipt("op-report-1")
        assert loaded == receipt
        assert store.get_commit_receipt("missing-key") is None

    def test_keyless_batch_still_atomic_and_sequenced(self, store):
        """Батч без ключа (advisory-путь) атомарен и упорядочен; повтор
        того же тела без ключа не дублирует (дедуп по event_id)."""
        events = _events("RUN-6ATEST01", 2)
        first = store.commit_event_batch(CommitEventBatch(run=_run(), events=events))
        assert first.idempotency_key == ""
        second = store.commit_event_batch(CommitEventBatch(run=_run(), events=events))
        assert second.accepted_event_ids == ()
        assert second.committed_watermark == first.committed_watermark
        assert len(store.list_events("RUN-6ATEST01")) == 2


# ── 4. CAS-контекст: stale отклонён до commit (I3, план §7) ──────────


class TestExpectedContext:
    def test_stale_context_rejected_before_commit(self, store):
        """RED-критерий плана §7: stale context отклонён ДО commit --
        ни события, ни метаданные не меняются."""
        store.upsert_run(_run(context_id="ctx-current", target_column=None))
        events = _events("RUN-6ATEST01", 2)
        with pytest.raises(CommitConflictError):
            store.commit_event_batch(
                CommitEventBatch(
                    run=_run(context_id="ctx-new", target_column="sales"),
                    events=events,
                    expected_context_id="ctx-stale",  # продюсер читал старое
                )
            )
        assert store.list_events("RUN-6ATEST01") == []
        run = store.get_run("RUN-6ATEST01")
        assert run.target_column is None
        assert run.context_id == "ctx-current"

    def test_expected_context_move_forward_is_accepted(self, store):
        """Легитимный сдвиг контекста (коррекция): CAS по прочитанному
        контексту проходит, метаданные получают НОВЫЙ контекст."""
        store.upsert_run(_run(context_id="ctx-old"))
        store.commit_event_batch(
            CommitEventBatch(
                run=_run(context_id="ctx-new"),
                events=_events("RUN-6ATEST01", 1),
                expected_context_id="ctx-old",
            )
        )
        assert store.get_run("RUN-6ATEST01").context_id == "ctx-new"
        assert len(store.list_events("RUN-6ATEST01")) == 1

    def test_first_stamp_on_null_context_accepted(self, store):
        """Первичная привязка: stored context NULL -- CAS проходит
        (нечего сравнивать), контекст фиксируется."""
        store.commit_event_batch(
            CommitEventBatch(
                run=_run(context_id="ctx-first"),
                events=_events("RUN-6ATEST01", 1),
                expected_context_id=None,
            )
        )
        assert store.get_run("RUN-6ATEST01").context_id == "ctx-first"

    def test_additive_run_fields_merge_not_erase(self, store):
        """Аддитивные run-метаданные (context/data_revision/data_digest,
        граница AUDIT-C §14.5) сливаются, а не стираются: батч без новых
        значений сохраняет прежние (COALESCE-семантика upsert)."""
        store.upsert_run(_run(context_id="ctx-keep", data_revision=3, data_digest="df1-x"))
        store.commit_event_batch(
            CommitEventBatch(
                run=_run(context_id=None, data_revision=None, data_digest=None),
                events=_events("RUN-6ATEST01", 1),
            )
        )
        run = store.get_run("RUN-6ATEST01")
        assert run.context_id == "ctx-keep"
        assert run.data_revision == 3
        assert run.data_digest == "df1-x"


# ── 5. Parity хранилищ (I8, P20, F07) ────────────────────────────────


class TestStoreParity:
    def test_memory_dedup_same_event_id_as_postgres(self, memory_store):
        """P20/H20/F07: Memory дедуплицирует одинаковый (run_id, event_id)
        -- тот же контракт, что Postgres ON CONFLICT DO NOTHING. До 6A
        Memory хранил дубли."""
        run = _run()
        memory_store.upsert_run(run)
        event = _events(run.run_id, 1)[0]
        memory_store.append_event(run.run_id, event)
        memory_store.append_event(run.run_id, event)
        assert len(memory_store.list_events(run.run_id)) == 1

    def test_memory_append_event_deep_copy_and_sequence(self, memory_store):
        """R1 (глубокие копии) сохраняется на новом контракте + sequence
        назначается и одиночному append."""
        run = _run()
        memory_store.upsert_run(run)
        event = _events(run.run_id, 1)[0]
        memory_store.append_event(run.run_id, event)
        event.payload["injected"] = True  # мутация источника не портит stored
        stored = memory_store.list_events(run.run_id)[0]
        assert "injected" not in stored.payload
        assert stored.sequence == 1

    def test_envelope_v2_durable_roundtrip(self, store):
        """Durable envelope слоя 2 (граница AUDIT-C §14.5): v2-событие
        переживает запись/чтение ОБОИХ хранилищ. До миграции 0002
        Postgres-строка теряла envelope (Memory -- нет): parity нарушен."""
        event = stamp_envelope(
            make_trace_event(
                "run_paused", stage="upload", node_id=None,
                run_id="RUN-6ATEST01",
            ),
            operation_id="op-1",
            causation_id="req-1",
            context_id="ctx-env",
        )
        store.commit_event_batch(
            CommitEventBatch(run=_run(), events=(event,))
        )
        loaded = store.list_events("RUN-6ATEST01")[0]
        assert loaded.schema_version == 2
        assert loaded.evidence_level == "operational"
        assert loaded.operation_id == "op-1"
        assert loaded.causation_id == "req-1"
        assert loaded.context_id == "ctx-env"
        # Дедуп по id -- envelope выжившей копии не теряется (пин §12.5).
        store.append_event("RUN-6ATEST01", event)
        again = store.list_events("RUN-6ATEST01")
        assert len(again) == 1
        assert again[0].context_id == "ctx-env"

    def test_identical_contract_same_assertions_both_stores(self, store):
        """Одинаковые контрактные тесты проходят Memory и Postgres:
        эта параметризованная функция и есть паритет (I8); смысловой
        минимум -- раундтрип батча с метаданными и чтение в канон.дикт."""
        events = _events("RUN-6ATEST01", 2)
        store.commit_event_batch(
            CommitEventBatch(run=_run(target_column="t", context_id="ctx-p"),
                             events=events)
        )
        loaded = store.list_events("RUN-6ATEST01")
        assert [e.to_dict()["event_id"] for e in loaded] == [e.event_id for e in events]
        assert [e.to_dict()["sequence"] for e in loaded] == [1, 2]
        run = store.get_run("RUN-6ATEST01")
        assert run.to_dict()["target_column"] == "t"
        assert run.to_dict()["context_id"] == "ctx-p"


# ── 6. Зеркало продюсеров: migrated vs advisory ──────────────────────


class TestMirrorProducers:
    @pytest.fixture(autouse=True)
    def _isolated_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
        from apps.api import research_runs
        from apps.api.session_store import reset_session_store_for_testing

        reset_session_store_for_testing()
        research_runs.reset_research_run_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()
        yield
        reset_session_store_for_testing()
        research_runs.reset_research_run_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()

    @pytest.fixture()
    def client(self) -> TestClient:
        with TestClient(app) as test_client:
            yield test_client

    def _run_id(self, client: TestClient) -> str:
        from apps.api.session_store import get_session_store, SESSION_COOKIE_NAME

        return get_session_store().get(
            client.cookies.get(SESSION_COOKIE_NAME)
        ).run_id

    def test_full_node_map_is_one_batch(self, client: TestClient):
        """Полная карта остановок -- ОДИН batch, не N независимых commit
        (план §7 п.2): события карты получают непрерывный sequence
        следующим префиксом ledger, run-метаданные обновлены той же
        операцией."""
        from apps.api import research_runs

        demo = client.post("/v1/session/demo")
        assert demo.status_code == 200
        run_id = self._run_id(client)
        store = research_runs.get_research_run_store()
        before = len(store.list_events(run_id))

        stops = {node_id: "done" for node_id in STAGE_NODES["upload"]}
        resp = client.post("/v1/progress/upload-stops", json={"stops": stops})
        assert resp.status_code == 200

        events = store.list_events(run_id)
        map_events = events[before:]
        assert len(map_events) == len(STAGE_NODES["upload"])
        # Один непрерывный префикс ledger (монотонный, без дыр).
        assert [e.sequence for e in map_events] == list(
            range(before + 1, before + 1 + len(map_events))
        )
        run = store.get_run(run_id)
        assert run.context_id  # run-метаданные той же операцией

    def test_map_mid_batch_failure_leaves_layer2_untouched(
        self, client: TestClient, monkeypatch
    ):
        """P08 по исправленному контракту на уровне продюсера: падение
        записи слоя 2 на середине карты оставляет слой 2 без ЧАСТИЧНЫХ
        фактов карты; слой 1 события содержит (в дополнение, §5); ответ
        честен (advisory-зеркало не ломает эндпоинт)."""
        from apps.api import research_runs

        client.post("/v1/session/demo")
        run_id = self._run_id(client)
        store = research_runs.get_research_run_store()
        before = len(store.list_events(run_id))
        before_run = store.get_run(run_id)

        _inject_failure_on_nth(store, monkeypatch, nth=1)
        stops = {node_id: "done" for node_id in STAGE_NODES["upload"]}
        resp = client.post("/v1/progress/upload-stops", json={"stops": stops})
        assert resp.status_code == 200  # advisory: сбой зеркала не ломает

        assert len(store.list_events(run_id)) == before  # ноль частичных фактов
        after_run = store.get_run(run_id)
        assert after_run.last_active_at == before_run.last_active_at

        # Слой 1 -- факты есть (в дополнение, не вместо).
        from apps.api.session_store import get_session_store, SESSION_COOKIE_NAME

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        layer1_types = [e.event_type for e in session.read_pipeline_trace()]
        assert layer1_types.count("upload_stop_status") == len(STAGE_NODES["upload"])

    def test_target_metadata_atomic_with_event_on_mirror_failure(
        self, client: TestClient, monkeypatch
    ):
        """P10 по исправленному контракту: сбой записи события не
        оставляет обновлённые run-метаданные -- «метаданные run могут
        обновиться без события» устранено атомарностью commit."""
        from apps.api import research_runs

        client.post("/v1/session/demo")
        run_id = self._run_id(client)
        store = research_runs.get_research_run_store()
        _inject_failure_on_nth(store, monkeypatch, nth=1)

        resp = client.post("/v1/session/target-column", json={"column": "sales"})
        assert resp.status_code == 200
        run = store.get_run(run_id)
        assert run.target_column is None  # метаданные НЕ обновлены без события
        types = [e.event_type for e in store.list_events(run_id)]
        assert "target_column_changed" not in types

    def test_map_retry_same_events_does_not_duplicate(self, client: TestClient):
        """Повтор ОДНОГО И ТОГО ЖЕ батча (та же поставка, тот же ключ
        содержимого) не дублирует факты карты; НОВАЯ поставка (новые
        event_id) честно даёт новые события (P07-семантика наблюдений
        сохранена до AUDIT-2A)."""
        from apps.api import research_runs

        client.post("/v1/session/demo")
        run_id = self._run_id(client)
        store = research_runs.get_research_run_store()
        before = len(store.list_events(run_id))

        stops = {node_id: "done" for node_id in STAGE_NODES["upload"]}
        assert client.post(
            "/v1/progress/upload-stops", json={"stops": stops}
        ).status_code == 200
        after_first = len(store.list_events(run_id))
        assert after_first == before + len(STAGE_NODES["upload"])

        # Прямой повтор ТОГО ЖЕ батча (тот же event_id) -- дедуп.
        store.commit_event_batch(
            CommitEventBatch(
                run=store.get_run(run_id),
                events=tuple(store.list_events(run_id)[before:]),
            )
        )
        assert len(store.list_events(run_id)) == after_first

        # Новая поставка карты -- новые наблюдения (P07 не сломан).
        assert client.post(
            "/v1/progress/upload-stops", json={"stops": stops}
        ).status_code == 200
        assert len(store.list_events(run_id)) == after_first + len(STAGE_NODES["upload"])


# ── 7. Миграция 0002: аддитивность к старому корпусу (план §7) ───────


@pytest.mark.skipif(
    not PG_DSN, reason="CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен"
)
class TestMigration0002OnLegacyCorpus:
    def test_migration_applicable_to_old_corpus_and_legacy_rows_readable(self):
        """Миграция применима к старому корпусу: 0001-схема с legacy-
        строками (v1-события без envelope/sequence) → 0002 аддитивно →
        старые строки читаемы (sequence честно None, канон-порядок
        legacy-first), новые события получают sequence с 1."""
        import psycopg
        from apps.api.research_runs import run_migrations

        conn = psycopg.connect(PG_DSN, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(
                "DROP TABLE IF EXISTS run_commit_receipts CASCADE;"
                "DROP TABLE IF EXISTS run_checkpoints CASCADE;"
                "DROP TABLE IF EXISTS trace_events CASCADE;"
                "DROP TABLE IF EXISTS research_runs CASCADE;"
                "DROP TABLE IF EXISTS mentor_observations CASCADE;"
            )
        conn.commit()
        # Старый корпус: ТОЛЬКО 0001 (ops-файл), без 0002.
        legacy_sql = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "apps" / "api" / "migrations" / "0001_research_runs.sql"
        )
        with conn.cursor() as cur:
            cur.execute(legacy_sql.read_text(encoding="utf-8"))
            cur.execute(
                "INSERT INTO research_runs (run_id, session_id, dataset_name) "
                "VALUES ('RUN-LEGACY6A', 'sess-old', 'old.csv')"
            )
            cur.execute(
                "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, "
                "event_type, payload, actor) VALUES ('legacy-ev-1', 'RUN-LEGACY6A', "
                "now(), 'upload', NULL, 'upload_completed', '{}'::jsonb, 'system')"
            )
        conn.commit()
        run_migrations(conn)  # 0001 (idempotent) + 0002 (аддитивно)
        conn.close()

        store = PostgresResearchRunStore(dsn=PG_DSN)
        legacy = store.list_events("RUN-LEGACY6A")
        assert [e.event_id for e in legacy] == ["legacy-ev-1"]
        assert legacy[0].sequence is None  # честное отсутствие (§3.7)

        # Новое событие -- sequence с 1 (NULLы корпуса не считаются).
        store.append_event(
            "RUN-LEGACY6A",
            make_trace_event(
                "upload_stop_status", stage="upload",
                node_id="structure_confirmed", run_id="RUN-LEGACY6A",
            ),
        )
        events = store.list_events("RUN-LEGACY6A")
        assert [e.sequence for e in events] == [None, 1]  # legacy-first порядок
        assert [e.event_id for e in events] == ["legacy-ev-1", events[1].event_id]

    def test_ddl_files_0001_and_0002_match_python_statements(self):
        """Эквивалентность источников DDL (паттерн PROGR-5.1): объекты
        файлов 0001+0002 == объекты MIGRATION_STATEMENTS (рассинхронизация
        -- находка)."""
        import psycopg
        from pathlib import Path
        from apps.api.research_runs import MIGRATION_STATEMENTS, run_migrations

        migrations_dir = (
            Path(__file__).resolve().parents[2] / "apps" / "api" / "migrations"
        )
        sql = "".join(
            (migrations_dir / name).read_text(encoding="utf-8")
            for name in ("0001_research_runs.sql", "0002_audit6a_atomic_ledger.sql")
        )
        assert "run_commit_receipts" in sql

        conn = psycopg.connect(PG_DSN, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(
                "DROP TABLE IF EXISTS run_commit_receipts CASCADE;"
                "DROP TABLE IF EXISTS run_checkpoints CASCADE;"
                "DROP TABLE IF EXISTS trace_events CASCADE;"
                "DROP TABLE IF EXISTS research_runs CASCADE;"
                "DROP TABLE IF EXISTS mentor_observations CASCADE;"
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        files_objects = self._schema_objects(conn)

        with conn.cursor() as cur:
            cur.execute(
                "DROP TABLE IF EXISTS run_commit_receipts CASCADE;"
                "DROP TABLE IF EXISTS run_checkpoints CASCADE;"
                "DROP TABLE IF EXISTS trace_events CASCADE;"
                "DROP TABLE IF EXISTS research_runs CASCADE;"
                "DROP TABLE IF EXISTS mentor_observations CASCADE;"
            )
        conn.commit()
        run_migrations(conn)
        py_objects = self._schema_objects(conn)
        conn.close()
        assert py_objects == files_objects

    @staticmethod
    def _schema_objects(conn) -> tuple[set[str], set[str]]:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            ).fetchall()
        }
        return tables, indexes
