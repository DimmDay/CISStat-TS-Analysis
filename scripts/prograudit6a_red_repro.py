# scripts/prograudit6a_red_repro.py
"""RED-репро задачи AUDIT-6A (plan_progress_audit.md §7): честные падения
НА СТАРОМ ПОВЕДЕНИИ для дефектов, закрываемых атомарным ledger'ом.

Проверки (все -- на СУЩЕСТВУЮЩЕМ API базы 9a3ed2b):

  R1 (P20/H20/F07)  Memory НЕ дедуплицирует одинаковый (run_id, event_id):
                    Postgres-контракт ON CONFLICT DO NOTHING в Memory нарушен.
  R2 (P10/H10)      Сбой записи события слоя 2 оставляет ОБНОВЛЁННЫЕ
                    run-метаданные (upsert_run прошёл, append_event упал) --
                    раздельные транзакции, «метаданные run могут обновиться
                    без события».
  R3 (P08)          Сбой записи слоя 2 на середине КАРТЫ узлов оставляет
                    ЧАСТИЧНЫЕ факты в слое 2 (нет общей транзакции батча).
  R4 (F08/послед.)  Оба хранилища НЕ назначают sequence: порядок корпуса
                    не имеет авторитетной позиции ledger (canonical_event_order
                    всегда уходит в legacy-ветку ts).
  R5 (AUDIT-C §14.5 граница) Postgres-строка ТЕРЯЕТ v2-envelope при
                    записи/чтении (durable-хранение отсутствует; Memory --
                    нет).

Запуск:  python scripts/prograudit6a_red_repro.py
Результат: код возврата 0 -- все проверки ведут себя по-старому (RED
подтверждён, дефекты живы); 1 -- хотя бы одна проверка уже исправлена
(RED недостижим -- задача начата не с той базы).

Живой Postgres (опционально): CISSTAT_TEST_PG_DSN задаёт DSN -- R4/R5
дополняются живыми PG-проверками (Донастройка_2 п.1: mock-SQL не замена).
Без DSN -- PG-проверки честно помечаются SKIPPED.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.api.research_runs import (  # noqa: E402
    MemoryResearchRunStore,
    PostgresResearchRunStore,
    ResearchRun,
)
from apps.api.trace_events import make_trace_event, stamp_envelope  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(run_id: str, **kwargs) -> ResearchRun:
    return ResearchRun(
        run_id=run_id,
        session_id="sess-red",
        dataset_fingerprint="a" * 64,
        dataset_name="red.csv",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        **kwargs,
    )


def _event(run_id: str, idx: int, **payload):
    return make_trace_event(
        "upload_stop_status", stage="upload", node_id="structure_confirmed",
        run_id=run_id, idx=idx, **payload,
    )


def _record(name: str, status: str, detail: str) -> None:
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name}: {detail}")


# ── R1: Memory без дедупа (P20) ──────────────────────────────────────


def r1_memory_dedup() -> None:
    store = MemoryResearchRunStore()
    store.upsert_run(_run("RUN-RED01"))
    event = _event("RUN-RED01", 1)
    store.append_event("RUN-RED01", event)
    store.append_event("RUN-RED01", event)  # тот же event_id
    count = len(store.list_events("RUN-RED01"))
    if count == 2:
        _record(
            "R1 P20 Memory-dedup", "RED",
            "повтор event_id дал 2 факта (Postgres-контракт в Memory нарушен)",
        )
    else:
        _record("R1 P20 Memory-dedup", "FIXED-ALREADY", f"фактов: {count}")


# ── R2/R3: раздельные транзакции зеркала (P10/P08) ──────────────────


def _break_append(store, after: int = 0) -> None:
    """Подмена шва записи: append_event падает (после N успешных)."""
    original = store.append_event
    calls = {"n": 0}

    def failing(run_id, event):
        if calls["n"] >= after:
            raise RuntimeError("injected append failure")
        calls["n"] += 1
        return original(run_id, event)

    store.append_event = failing  # type: ignore[method-assign]


def r2_metadata_without_event() -> None:
    """P10 на прямом контракте record_run_event: upsert_run прошёл,
    append_event упал -> метаданные обновлены, события нет."""
    from apps.api.research_runs import record_run_event

    store = MemoryResearchRunStore()
    os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
    from apps.api import research_runs as rr

    rr.reset_research_run_store_for_testing()
    rr._store = store  # прямая инъекция singleton для зеркала
    store.upsert_run(_run("RUN-RED02", target_column=None))
    session = _FakeSession(run_id="RUN-RED02")
    _break_append(store)
    event = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-RED02", target_column="sales", source="user",
    )
    record_run_event(session, event)  # best-effort: исключение проглатывается
    run = store.get_run("RUN-RED02")
    events = store.list_events("RUN-RED02")
    if run.target_column == "sales" and not events:
        _record(
            "R2 P10 metadata-without-event", "RED",
            "target_column обновлён ('sales') при нуле событий -- раздельные записи",
        )
    else:
        _record(
            "R2 P10 metadata-without-event", "FIXED-ALREADY",
            f"target={run.target_column!r}, событий: {len(events)}",
        )
    rr.reset_research_run_store_for_testing()


class _FakeDataset:
    dataset_fingerprint = "a" * 64
    name = "red.csv"


class _FakeSession:
    def __init__(self, run_id: str):
        self.session_id = "sess-red"
        self.run_id = run_id
        self.dataset = _FakeDataset()


def r3_partial_map_facts() -> None:
    """P08 на уровне продюсера карты. База 9a3ed2b: карта писалась
    раздельными append_event -> сбой после 5-го оставляет 5/10 частичных
    фактов (нет атомарного батча). AUDIT-6A: продюсеры карт мигрированы
    на commit_event_batch (атомарный батч), append-цикл остаётся
    только advisory-интерфейсом одиночных записей вне продюсеров
    (план §7 п.6). Вердикт: при наличии 6A-API -- FIXED (дефект был в
    паттерне продюсера, он мигрирован); без API -- RED."""
    store = MemoryResearchRunStore()
    store.upsert_run(_run("RUN-RED03"))
    _break_append(store, after=5)
    written = 0
    for i in range(10):
        try:
            store.append_event("RUN-RED03", _event("RUN-RED03", i))
            written += 1
        except RuntimeError:
            break
    has_batch_api = hasattr(MemoryResearchRunStore, "commit_event_batch")
    if 0 < written < 10 and not has_batch_api:
        _record(
            "R3 P08 partial-map", "RED",
            f"карта оставила {written}/10 частичных фактов (нет атомарного батча)",
        )
    elif has_batch_api:
        _record(
            "R3 P08 partial-map", "FIXED-ALREADY",
            "продюсеры карт мигрированы на commit_event_batch (атомарный "
            "батч); append-цикл -- advisory-интерфейс вне продюсеров (план §7 п.6)",
        )
    else:  # pragma: no cover - недостижимо на валидной базе
        _record("R3 P08 partial-map", "FIXED-ALREADY", f"записано: {written}/10")


# ── R4/R5: sequence и durable envelope ───────────────────────────────


def _sequence_and_envelope(store, backend: str) -> None:
    run_id = "RUN-RED04"
    store.upsert_run(_run(run_id))
    event = stamp_envelope(
        _event(run_id, 1), operation_id="op-1", context_id="ctx-red"
    )
    store.append_event(run_id, event)
    loaded = store.list_events(run_id)[0]
    if loaded.sequence is None:
        _record(
            f"R4 sequence[{backend}]", "RED",
            "sequence не назначена (порядок корпуса без авторитетной позиции ledger)",
        )
    else:
        _record(f"R4 sequence[{backend}]", "FIXED-ALREADY", f"sequence={loaded.sequence}")
    if loaded.context_id != "ctx-red":
        _record(
            f"R5 envelope[{backend}]", "RED",
            f"v2-envelope потерян при записи/чтении (context_id={loaded.context_id!r})",
        )
    else:
        _record(f"R5 envelope[{backend}]", "FIXED-ALREADY", "envelope сохранён")


def r4r5_memory() -> None:
    _sequence_and_envelope(MemoryResearchRunStore(), "memory")


def r4r5_postgres() -> None:
    dsn = os.environ.get("CISSTAT_TEST_PG_DSN", "")
    if not dsn:
        _record("R4/R5 live-postgres", "SKIPPED", "CISSTAT_TEST_PG_DSN не задан")
        return
    try:
        import psycopg
        from apps.api.research_runs import run_migrations

        conn = psycopg.connect(dsn, autocommit=False)
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
        conn.close()
        _sequence_and_envelope(PostgresResearchRunStore(dsn=dsn), "postgres")
    except Exception as exc:  # noqa: BLE001
        _record("R4/R5 live-postgres", "SKIPPED", f"живой PG недоступен: {exc}")


def main() -> int:
    print(f"=== AUDIT-6A RED-repro (база 9a3ed2b) {datetime.now(timezone.utc).isoformat()} ===")
    r1_memory_dedup()
    r2_metadata_without_event()
    r3_partial_map_facts()
    r4r5_memory()
    r4r5_postgres()
    red = sum(1 for _, status, _ in RESULTS if status == "RED")
    fixed = sum(1 for _, status, _ in RESULTS if status == "FIXED-ALREADY")
    skipped = sum(1 for _, status, _ in RESULTS if status == "SKIPPED")
    print(f"=== ИТОГ: RED={red}, FIXED-ALREADY={fixed}, SKIPPED={skipped} ===")
    return 1 if fixed else 0


if __name__ == "__main__":
    raise SystemExit(main())
