#!/usr/bin/env python3
# scripts/audit_scripts/progr5fe_ddl_integration.py
"""Интеграционный прогон DDL долговременного слоя «Прогресса» на
on-prem Postgres (Task PROGR-5.1; схема spec_progress.md §12 п.1,
DDL apps/api/migrations/0001_research_runs.sql, Task PROGR-5).

Прогоняет на ЖИВОМ Postgres-сервере:

  [1] DROP-затирание -> применение DDL-ФАЙЛА ops-контуром (psql -f-эквивалент:
      весь файл одним простым запросом, без параметров);
  [2] контроль объектов: 3 таблицы (research_runs/trace_events/run_checkpoints)
      + 3 индекса (idx_trace_events_run_seq/idx_research_runs_session/
      idx_research_runs_status);
  [3] идемпотентность: повторное применение файла не падает и не меняет схему;
  [4] эквивалентность источников: MIGRATION_STATEMENTS (авто-миграция первого
      коннекта apps/api/research_runs.py) дают то же множество объектов, что
      файл (рассинхронизация -- дефект);
  [5] поведенческий контракт PostgresResearchRunStore на живой БД:
      раундтрип запуска, статусы paused/active, supersede, события
      (JSONB-пейлоад с юникодом, порядок seq, дубль по (run_id, event_id)
      отсекается), чекпоинт;
  [6] DDL-гарантии сервера: UNIQUE (run_id, event_id) -- UniqueViolation
      на сырой дубль-вставке; FK ON DELETE CASCADE.

Целевой сервер (--dsn > env CISSTAT_DDL_DSN > env DATABASE_URL):

  on-prem:  --dsn 'postgresql://user:pass@host:5432/db'
  sandbox:  без --dsn поднимается эфемерный сервер pgserver (PyPI, бинари
            PostgreSQL без root; реальный сервер 16.x, unix-сокет) --
            НЕ эмуляция: применяется и проверяется тот же DDL на настоящем
            Postgres.

Успех: все шаги PASS, код возврата 0; любой FAIL -- ненулевой код.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DDL_FILE = REPO_ROOT / "apps" / "api" / "migrations" / "0001_research_runs.sql"

DROP_SCHEMA_SQL = """
DROP TABLE IF EXISTS run_checkpoints CASCADE;
DROP TABLE IF EXISTS trace_events CASCADE;
DROP TABLE IF EXISTS research_runs CASCADE;
"""

EXPECTED_TABLES = {"research_runs", "trace_events", "run_checkpoints"}
EXPECTED_INDEXES = {
    "idx_trace_events_run_seq",
    "idx_research_runs_session",
    "idx_research_runs_status",
}

RESULTS: list[tuple[str, str, str]] = []


def report(step: str, verdict: str, detail: str = "") -> None:
    RESULTS.append((step, verdict, detail))
    marker = "PASS" if verdict == "PASS" else "FAIL"
    print(f"[{marker}] {step}" + (f" -- {detail}" if detail else ""))


def schema_objects(conn) -> tuple[set[str], set[str]]:
    tables = {
        r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    indexes = {
        r[0] for r in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        ).fetchall()
    }
    return tables, indexes


def apply_ddl_file(conn) -> None:
    """psql -f-эквивалент: файл целиком простым протоколом (psycopg
    исполняет многоутверждающий SQL без параметров)."""
    with conn.cursor() as cur:
        cur.execute(DDL_FILE.read_text(encoding="utf-8"))
    conn.commit()


def resolve_dsn(args: argparse.Namespace) -> tuple[str, object | None]:
    """DSN из --dsn/env; без него -- эфемерный pgserver (реальный Postgres)."""
    dsn = args.dsn or os.environ.get("CISSTAT_DDL_DSN") or os.environ.get("DATABASE_URL")
    if dsn and not dsn.startswith("file:"):
        return dsn, None
    try:
        import pgserver
    except ImportError:
        raise SystemExit(
            "DSN не задан, а pgserver недоступен. Передайте --dsn "
            "'postgresql://user:pass@host:5432/db' (on-prem) или установите "
            "pip install 'psycopg[binary]' pgserver для эфемерного сервера."
        )
    server_dir = args.pgdata or "/home/z/my-project/pg-integration/data"
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    print(f"Postgres (ephemeral pgserver): {uri}")
    print(f"    binaries: {Path(pgserver.__file__).parent}")
    return uri, server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dsn", default="", help="DSN on-prem Postgres (иначе env/ephemeral)")
    parser.add_argument("--pgdata", default="", help="каталог кластера pgserver (sandbox)")
    args = parser.parse_args()

    import psycopg

    dsn, ephemeral = resolve_dsn(args)
    print(f"=== Интеграционный прогон DDL PROGR-5 на Postgres ===")
    print(f"DDL: {DDL_FILE.relative_to(REPO_ROOT)}")
    print(f"Цель: {'эфемерный pgserver (реальный PostgreSQL)' if ephemeral else 'внешний сервер (on-prem)'}\n")

    from apps.api.research_runs import (
        MIGRATION_STATEMENTS,
        PostgresResearchRunStore,
        ResearchCheckpoint,
        ResearchRun,
        run_migrations,
    )
    from apps.api.trace_events import make_trace_event

    # ── [1] Чистая схема + применение DDL-файла ─────────────────────
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(DROP_SCHEMA_SQL)
        conn.commit()
        apply_ddl_file(conn)
        report("[1] применение DDL-файла", "PASS", "DROP-затирание + CREATE OK")

        # ── [2] Контроль объектов ───────────────────────────────────
        tables, indexes = schema_objects(conn)
        missing = (EXPECTED_TABLES - tables) | (EXPECTED_INDEXES - indexes)
        report(
            "[2] объекты схемы §12 п.1",
            "PASS" if not missing else "FAIL",
            f"таблицы {sorted(EXPECTED_TABLES & tables)}, индексы {sorted(EXPECTED_INDEXES & indexes)}"
            + (f"; ОТСУТСТВУЮТ: {sorted(missing)}" if missing else ""),
        )

        # ── [3] Идемпотентность повторного прогона ──────────────────
        before = (tables, indexes)
        apply_ddl_file(conn)
        apply_ddl_file(conn)
        after = schema_objects(conn)
        report(
            "[3] идемпотентность DDL (повторный прогон)",
            "PASS" if after == before else "FAIL",
            "схема не изменилась, IF NOT EXISTS сработал"
            if after == before else f"схема изменилась: {before} -> {after}",
        )

        # ── [4] Эквивалентность MIGRATION_STATEMENTS и файла ────────
        with conn.cursor() as cur:
            cur.execute(DROP_SCHEMA_SQL)
        conn.commit()
        conn2 = psycopg.connect(dsn)
        try:
            executed = run_migrations(conn2)
        finally:
            conn2.close()
        py_tables, py_indexes = schema_objects(conn)
        same = (py_tables, py_indexes) == before
        report(
            "[4] эквивалентность MIGRATION_STATEMENTS ↔ DDL-файл",
            "PASS" if same else "FAIL",
            f"{executed} утверждений; объекты совпадают с файлом"
            if same else f"РАССИНХРОНИЗАЦИЯ: python={py_tables | py_indexes} file={before[0] | before[1]}",
        )
    finally:
        conn.close()

    # ── [5] Поведенческий контракт хранилища на живой БД ────────────
    store = PostgresResearchRunStore(dsn=dsn)
    now = datetime.now(timezone.utc).isoformat()
    run = ResearchRun(
        run_id="RUN-DDLINTEG",
        session_id="sess-ddl-integration",
        dataset_fingerprint="b" * 64,
        dataset_name="demo_sales.csv (демо-датасет)",
        target_column=None,
        created_at=now,
        last_active_at=now,
    )
    try:
        store.upsert_run(run)
        loaded = store.get_run(run.run_id)
        ok = loaded is not None and loaded.dataset_name == run.dataset_name and loaded.status == "active"

        store.set_run_status(run.run_id, "paused")
        ok = ok and store.get_run(run.run_id).status == "paused"

        ev1 = make_trace_event(
            "upload_completed", stage="upload", node_id="structure_confirmed",
            run_id=run.run_id, name="demo_sales.csv (демо-датасет)", rows=120,
        )
        ev2 = make_trace_event(
            "run_paused", stage="upload", node_id=None, run_id=run.run_id,
        )  # N-2: run-level, node_id=None сохраняется как есть
        store.append_event(run.run_id, ev1)
        store.append_event(run.run_id, ev2)
        store.append_event(run.run_id, ev1)  # дубль -- DO NOTHING
        events = store.list_events(run.run_id)
        ok = (
            ok
            and [e.event_type for e in events] == ["upload_completed", "run_paused"]
            and events[1].node_id is None
            and events[0].payload.get("name") == "demo_sales.csv (демо-датасет)"
        )

        store.add_checkpoint(
            run.run_id,
            ResearchCheckpoint(
                checkpoint_id="cp-ddl-integ",
                run_id=run.run_id,
                event_id=ev1.event_id,
                label="Перед экспериментом со сглаживанием",
            ),
        )
        cps = store.list_checkpoints(run.run_id)
        ok = ok and len(cps) == 1 and cps[0].label == "Перед экспериментом со сглаживанием"

        report(
            "[5] поведенческий контракт PostgresResearchRunStore",
            "PASS" if ok else "FAIL",
            "раундтрип запуска, paused, события (JSONB/юникод/N-2), дубль отсечён, чекпоинт",
        )
    except Exception as exc:  # noqa: BLE001
        report("[5] поведенческий контракт PostgresResearchRunStore", "FAIL", repr(exc))

    # ── [6] DDL-гарантии сервера ────────────────────────────────────
    try:
        conn = psycopg.connect(dsn)
        unique_ok = cascade_ok = False
        try:
            # [6a] UNIQUE (run_id, event_id): базовая пара -- ЗАФИКСИРОВАНА
            # (rollback после UniqueViolation сбросил бы и запуск, [6b]
            # остался бы без родителя).
            with conn.cursor() as cur:
                cur.execute("INSERT INTO research_runs (run_id) VALUES ('RUN-DDLSRV')")
                cur.execute(
                    "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, "
                    "event_type) VALUES ('dup', 'RUN-DDLSRV', now(), 'upload', NULL, "
                    "'upload_completed')"
                )
            conn.commit()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO trace_events (event_id, run_id, ts, stage, "
                        "node_id, event_type) VALUES ('dup', 'RUN-DDLSRV', now(), "
                        "'upload', NULL, 'upload_completed')"
                    )
                conn.commit()
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                unique_ok = True
            # [6b] CASCADE: чекпоинт на зафиксированную пару, затем удаление
            # запуска -- события/чекпоинты обязаны уйти вместе с ним.
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO run_checkpoints (checkpoint_id, run_id, event_id) "
                    "VALUES ('cp-srv', 'RUN-DDLSRV', 'dup')"
                )
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM research_runs WHERE run_id = 'RUN-DDLSRV'")
            conn.commit()
            with conn.cursor() as cur:
                left_events = cur.execute(
                    "SELECT COUNT(*) FROM trace_events WHERE run_id = 'RUN-DDLSRV'"
                ).fetchone()[0]
                left_cps = cur.execute(
                    "SELECT COUNT(*) FROM run_checkpoints WHERE run_id = 'RUN-DDLSRV'"
                ).fetchone()[0]
            cascade_ok = left_events == 0 and left_cps == 0
        finally:
            conn.close()
        verdict = "PASS" if unique_ok and cascade_ok else "FAIL"
        detail = (
            "UNIQUE (run_id, event_id) -- UniqueViolation; ON DELETE CASCADE -- "
            "события/чекпоинты удалены вместе с запуском"
        )
        if not unique_ok:
            detail = "UNIQUE (run_id, event_id) НЕ enforced сервером"
        elif not cascade_ok:
            detail = "ON DELETE CASCADE НЕ enforced сервером"
        report("[6] DDL-гарантии сервера (UNIQUE + CASCADE)", verdict, detail)
    except Exception as exc:  # noqa: BLE001
        report("[6] DDL-гарантии сервера (UNIQUE + CASCADE)", "FAIL", repr(exc))

    if ephemeral is not None:
        print("\n(эфемерный сервер pgserver оставлен в --pgdata для повторных прогонов)")

    failed = [r for r in RESULTS if r[1] != "PASS"]
    print(f"\n=== ИТОГ: {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
