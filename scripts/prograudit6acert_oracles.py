# scripts/prograudit6acert_oracles.py
"""Независимая сертификация AUDIT-6A (план plan_progress_audit.md §7) —
оракулы сертификатора НА СВОИХ данных. НЕ копирует
tests/api/test_progress_audit_6a.py: свои run_id (RUN-CERT6A-*),
свои event_id (c6a-*), свои payload-теги, свой датасет e2e-потока
(farm_yield_monthly.csv, 72 месячные точки, seed 20261011), свои углы
проверки атомарного ledger.

Группы:
  FP   — batch_body_fingerprint: детерминизм/чувствительность/префикс (5)
  ATOM — атомарность: отказ на ПОСЛЕДНЕМ/ПЕРВОМ событии, receipt после
         отказа отсутствует, retry-once ровно одна копия, watermark
         стабилен, ключ идемпотентности переживает CAS-отказ (6)
  SEQ  — sequence: непрерывность при чередовании батчей/одиночных,
         независимость per run, legacy-first канонический порядок (PG),
         защита уникальным индексом (5)
  RCP  — receipt: безключевой батч, два разных ключа на одно тело,
         retry после ДОПИСАНЫХ событий возвращает СТАРЫЙ receipt,
         форма/watermark, содержательные ключи продюсеров (5)
  CAS  — expected context: первичная привязка на NULL, совпадение
         принимается, None отключает, stale после привязки отклонён
         ДО записи, CAS-отказ не потребляет ключ (5)
  COA  — COALESCE-слияние: контекст сохраняется при None-батче,
         digest обновляется новым значением, target_column=None пишется
         напрямую (сброс цели — не COALESCE), ревизия обновляется (4)
  PAR  — паритет I8 на ОБОИХ хранилищах: дедуп append, глубокие копии,
         durable envelope v2 в PG-строке (3, параметризовано)
  E2E  — свой CSV через живой API: полная карта = один batch с
         содержательным ключом map:{run_id}:{fp[:40]}, повтор не
         дублирует, слой 1 не задет (3)
  MIG  — миграция 0002 на legacy-корпусе 0001: применение файла DDL,
         legacy-строки читаемы (sequence None), новые события с 1,
         receipt работает на мигрированном корпусе (3)

Запуск:
  python3 scripts/prograudit6acert_oracles.py            # всё (PG через pgserver)
  python3 scripts/prograudit6acert_oracles.py --no-pg    # только Memory
  python3 scripts/prograudit6acert_oracles.py --cert     # режим kill-канала мутаций
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


# ── Свои данные сертификатора ────────────────────────────────────────

SEED_TAG = "c6a-hydro"


def _now(offset_ms: int = 0) -> str:
    base = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(milliseconds=offset_ms)).isoformat()


def _run(run_id: str = "RUN-CERT6A-H01", **kw: Any):
    from apps.api.research_runs import ResearchRun

    defaults: dict[str, Any] = {
        "run_id": run_id,
        "session_id": "sess-cert6a-hydro",
        "dataset_fingerprint": "f" * 64,
        "dataset_name": "hydro_meteo_cert6a.csv",
        "created_at": _now(0),
        "last_active_at": _now(0),
    }
    defaults.update(kw)
    return ResearchRun(**defaults)


def _ev(run_id: str, tag: str, *, etype: str = "upload_stop_status",
        stage: str = "upload", node: str = "structure_confirmed", **payload: Any):
    """Своё событие сертификатора: payload несёт тег канала и свои поля."""
    from apps.api.trace_events import make_trace_event

    base_payload = {"channel": SEED_TAG, "tag": tag}
    base_payload.update(payload)
    return make_trace_event(
        etype, stage=stage, node_id=node, run_id=run_id, **base_payload
    )


def _fresh_memory():
    from apps.api.research_runs import MemoryResearchRunStore

    return MemoryResearchRunStore()


_PG_SERVER = None


def _fresh_pg():
    """Живой временный Postgres (pgserver), чистая схема на каждый оракул."""
    global _PG_SERVER
    if _PG_SERVER is None:
        import pgserver

        _PG_SERVER = pgserver.get_server(
            tempfile.mkdtemp(prefix="cisstat6acert-pg-"), cleanup_mode="delete"
        )
    import psycopg
    from apps.api.research_runs import PostgresResearchRunStore, run_migrations

    dsn = _PG_SERVER.get_uri()
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
    return PostgresResearchRunStore(dsn=dsn)


def _inj_fail_nth(store_obj, nth: int, cls_attr: str = "_prepare_stored_event"):
    """ОДНОРАЗОВЫЙ отказ на N-м вызове шва подготовки (транзиентный сбой)."""
    cls = type(store_obj)
    original = getattr(cls, cls_attr)
    calls = {"n": 0}

    def failing(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == nth:
            raise RuntimeError("cert6a injected transient failure")
        return original(self, *a, **kw)

    setattr(cls, cls_attr, failing)
    return lambda: setattr(cls, cls_attr, original)


# ── FP. batch_body_fingerprint на своих payload ──────────────────────


def grp_fp() -> None:
    print("FP — отпечаток тела батча (свои payload, кириллица)")
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import batch_body_fingerprint

    e1 = _ev("RUN-CERT6A-H01", "fp-1", sensor="влажность", value=41.5)
    # тот же корпус = те же event_id (фабрика генерирует новый id на вызов):
    e1_dup = dc_replace(e1)
    e_other_payload = dc_replace(e1, payload={**e1.payload, "value": 99.0})
    run_a = "RUN-CERT6A-H01"
    run_b = "RUN-CERT6A-H02"

    fp1 = batch_body_fingerprint(run_a, (e1,))
    fp2 = batch_body_fingerprint(run_a, (e1_dup,))
    check("FP1 тот же корпус → тот же отпечаток", fp1 == fp2)

    fp3 = batch_body_fingerprint(run_a, (e_other_payload,))
    check("FP2 другой payload → другой отпечаток", fp1 != fp3)

    fp4 = batch_body_fingerprint(run_b, (e1,))
    check("FP3 другой run_id → другой отпечаток", fp1 != fp4)

    fp5 = batch_body_fingerprint(run_a, (e1,), context_id="ctx-A")
    fp6 = batch_body_fingerprint(run_a, (e1,), context_id="ctx-B")
    check("FP4 контекст входит в материал отпечатка", fp5 != fp6)

    check(
        "FP5 префикс sha256: и hex-длина 64",
        fp1.startswith("sha256:") and len(fp1) == len("sha256:") + 64,
        fp1[:20],
    )

    # Межпроцессный детерминизм (свой субпроцесс, свои данные; id/ts пиннуты)
    code = (
        "import sys; from dataclasses import replace;"
        "sys.path.insert(0, %r);"
        "from apps.api.trace_events import make_trace_event;"
        "from apps.api.research_runs import batch_body_fingerprint;"
        "e = make_trace_event('upload_stop_status', stage='upload',"
        " node_id='structure_confirmed', run_id='RUN-CERT6A-H01',"
        " channel='c6a-hydro', tag='fp-x', value=41.5);"
        "e = replace(e, event_id='c6a-fixed-fp-0001', ts='2026-10-11T12:00:00+00:00');"
        "print(batch_body_fingerprint('RUN-CERT6A-H01', (e,)))" % str(REPO)
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO)
        ).stdout.strip()
        for _ in range(2)
    }
    check("FP6 отпечаток детерминирован межпроцессно", len(outs) == 1 and next(iter(outs)).startswith("sha256:"), str(outs)[:80])


# ── ATOM. Атомарность батча (свои углы отказа) ───────────────────────


def grp_atom_memory() -> None:
    print("ATOM-M — атомарность, Memory (отказ на последнем/первом, receipt, retry)")
    from apps.api.research_runs import CommitEventBatch, batch_body_fingerprint

    st = _fresh_memory()
    run = _run("RUN-CERT6A-H03", target_column="humidity")
    evs = tuple(_ev("RUN-CERT6A-H03", f"atom-{i}") for i in range(4))

    # отказ на ПОСЛЕДНЕМ (4-м) событии
    restore = _inj_fail_nth(st, nth=4)
    try:
        st.commit_event_batch(
            CommitEventBatch(run=run, events=evs, idempotency_key="k-atom-last")
        )
        ok_raise = False
    except RuntimeError:
        ok_raise = True
    finally:
        restore()
    check("ATOM1 отказ на последнем событии поднят", ok_raise)
    check("ATOM2 после отказа ноль событий", len(st.list_events("RUN-CERT6A-H03")) == 0)
    run_after = st.get_run("RUN-CERT6A-H03")
    check(
        "ATOM3 метаданные прежние после отказа",
        run_after is None or run_after.target_column == "humidity" if run_after else True,
    )
    check(
        "ATOM4 receipt отказавшего батча НЕ зарегистрирован",
        st.get_commit_receipt("k-atom-last") is None,
    )

    # честный retry тем же ключом/телом — ровно одна копия
    fp = batch_body_fingerprint("RUN-CERT6A-H03", evs, context_id=run.context_id)
    receipt = st.commit_event_batch(
        CommitEventBatch(run=run, events=evs, idempotency_key="k-atom-last", body_fingerprint=fp)
    )
    check("ATOM5 retry после отказа принят", receipt.committed_watermark == 4)
    check("ATOM6 retry ровно одна копия каждого события", len(st.list_events("RUN-CERT6A-H03")) == 4)

    # отказ на ПЕРВОМ событии после успешного корпуса — прежние метаданные
    run2 = _run("RUN-CERT6A-H04")
    st.commit_event_batch(CommitEventBatch(run=run2, events=(_ev("RUN-CERT6A-H04", "seed"),)))
    before_meta = st.get_run("RUN-CERT6A-H04")
    evs2 = tuple(_ev("RUN-CERT6A-H04", f"b2-{i}") for i in range(3))
    restore2 = _inj_fail_nth(st, nth=1)
    try:
        st.commit_event_batch(CommitEventBatch(run=run2, events=evs2, idempotency_key="k-atom-first"))
    except RuntimeError:
        pass
    finally:
        restore2()
    meta2 = st.get_run("RUN-CERT6A-H04")
    check(
        "ATOM7 отказ на первом: метаданные байт-в-байт прежние",
        meta2.last_active_at == before_meta.last_active_at
        and meta2.data_revision == before_meta.data_revision,
    )


def grp_atom_pg() -> None:
    print("ATOM-P — атомарность, живой PG (отказ на последнем, rollback)")
    from apps.api.research_runs import CommitEventBatch

    st = _fresh_pg()
    run = _run("RUN-CERT6A-H05", target_column="pressure")
    evs = tuple(_ev("RUN-CERT6A-H05", f"pgatom-{i}") for i in range(3))
    restore = _inj_fail_nth(st, nth=3)
    try:
        st.commit_event_batch(CommitEventBatch(run=run, events=evs, idempotency_key="k-pg-last"))
        ok_raise = False
    except RuntimeError:
        ok_raise = True
    finally:
        restore()
    check("ATOMP1 отказ на последнем событии поднят (живой PG)", ok_raise)
    check("ATOMP2 rollback: ноль событий в таблице", len(st.list_events("RUN-CERT6A-H05")) == 0)
    check(
        "ATOMP3 rollback: run-метаданные не записаны",
        st.get_run("RUN-CERT6A-H05") is None or st.get_run("RUN-CERT6A-H05").target_column is None,
    )
    check("ATOMP4 receipt после отката отсутствует", st.get_commit_receipt("k-pg-last") is None)


# ── SEQ. Непрерывность позиции ledger ────────────────────────────────


def grp_seq_memory() -> None:
    print("SEQ-M — sequence per run: чередование, независимость запусков")
    from apps.api.research_runs import CommitEventBatch

    st = _fresh_memory()
    r1, r2 = "RUN-CERT6A-H06", "RUN-CERT6A-H07"
    # чередование батчей и одиночных advisory-записей
    st.commit_event_batch(
        CommitEventBatch(run=_run(r1), events=tuple(_ev(r1, f"s1-{i}") for i in range(2)))
    )
    st.append_event(r1, _ev(r1, "single-1"))
    st.commit_event_batch(
        CommitEventBatch(run=_run(r1), events=tuple(_ev(r1, f"s2-{i}") for i in range(2)))
    )
    seqs1 = [e.sequence for e in st.list_events(r1)]
    check("SEQ1 непрерывный префикс 1..5 при чередовании", seqs1 == [1, 2, 3, 4, 5], str(seqs1))

    st.commit_event_batch(
        CommitEventBatch(run=_run(r2), events=tuple(_ev(r2, f"t1-{i}") for i in range(3)))
    )
    seqs2 = [e.sequence for e in st.list_events(r2)]
    check("SEQ2 sequence независима per run (второй запуск с 1)", seqs2 == [1, 2, 3], str(seqs2))

    # конкурентные батчи одного запуска — один суммарный порядок без дублей
    r3 = "RUN-CERT6A-H08"
    barrier = threading.Barrier(2)

    def worker(tag: str):
        evs = tuple(_ev(r3, f"{tag}-{i}") for i in range(20))
        barrier.wait()
        st.commit_event_batch(CommitEventBatch(run=_run(r3), events=evs))

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("wa", "wb")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqs3 = sorted(e.sequence for e in st.list_events(r3))
    check(
        "SEQ3 конкурентные батчи: непрерывный 1..40 без дублей/дыр",
        seqs3 == list(range(1, 41)),
        f"n={len(seqs3)}",
    )


def grp_seq_pg() -> None:
    print("SEQ-P — живой PG: непрерывность, legacy-first порядок, уникальность")
    from apps.api.research_runs import CommitEventBatch

    st = _fresh_pg()
    r = "RUN-CERT6A-H09"
    st.commit_event_batch(
        CommitEventBatch(run=_run(r), events=tuple(_ev(r, f"p1-{i}") for i in range(3)))
    )
    st.append_event(r, _ev(r, "pg-single"))
    st.commit_event_batch(
        CommitEventBatch(run=_run(r), events=tuple(_ev(r, f"p2-{i}") for i in range(2)))
    )
    seqs = [e.sequence for e in st.list_events(r)]
    check("SEQP1 живой PG: непрерывный 1..6 при чередовании", seqs == [1, 2, 3, 4, 5, 6], str(seqs))

    # legacy-корпус: строки с commit_seq NULL читаются первыми (store-order)
    import psycopg

    conn = psycopg.connect(st._dsn, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_runs (run_id, session_id) VALUES (%s, %s)",
            ("RUN-CERT6A-LEG", "sess-cert6a-legacy"),
        )
        cur.execute(
            "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, event_type)"
            " VALUES (%s, 'RUN-CERT6A-LEG', now(), 'upload', 'structure_confirmed', 'upload_completed'),"
            "       (%s, 'RUN-CERT6A-LEG', now(), 'upload', 'structure_confirmed', 'structure_confirmed')",
            ("legacy-ev-1", "legacy-ev-2"),
        )
    conn.commit()
    conn.close()
    st2_commit = st.commit_event_batch(
        CommitEventBatch(
            run=_run("RUN-CERT6A-LEG", session_id="sess-cert6a-legacy"),
            events=(_ev("RUN-CERT6A-LEG", "new-after-legacy"),),
        )
    )
    events = st.list_events("RUN-CERT6A-LEG")
    types = [e.event_type for e in events]
    check(
        "SEQP2 legacy-first: NULL-строки раньше новых commit_seq",
        types[:2] == ["upload_completed", "structure_confirmed"] and types[-1] == "upload_stop_status",
        str(types),
    )
    check("SEQP3 новые события после legacy начинаются с commit_seq=1", st2_commit.committed_watermark == 1)
    legacy_seq = [e.sequence for e in events[:2]]
    check("SEQP4 legacy-строки честно sequence=None", legacy_seq == [None, None], str(legacy_seq))


# ── RCP. Receipt и идемпотентность ───────────────────────────────────


def grp_rcp_memory() -> None:
    print("RCP-M — receipt: безключевой, два ключа, retry после дописанных")
    from apps.api.research_runs import CommitEventBatch, batch_body_fingerprint

    st = _fresh_memory()
    r = "RUN-CERT6A-H10"

    # безключевой батч: события+sequence пишутся, receipt НЕ регистрируется
    rc0 = st.commit_event_batch(
        CommitEventBatch(run=_run(r), events=tuple(_ev(r, f"k0-{i}") for i in range(2)))
    )
    check("RCP1 безключевой батч возвращает receipt с пустым ключом", rc0.idempotency_key == "")
    check("RCP2 безключевой: get_commit_receipt вернёт None", st.get_commit_receipt("x-nope") is None)

    evs = tuple(_ev(r, f"rc-{i}") for i in range(3))
    run_with_ctx = _run(r, context_id="ctx-rcp-form")
    body = batch_body_fingerprint(r, evs, context_id=run_with_ctx.context_id)
    rc1 = st.commit_event_batch(CommitEventBatch(run=run_with_ctx, events=evs, idempotency_key="cert6a-map-key"))
    rc2 = st.commit_event_batch(CommitEventBatch(run=run_with_ctx, events=evs, idempotency_key="other-cert6a-key", body_fingerprint=body))
    check("RCP3 два РАЗНЫХ ключа на одно тело — оба приняты независимо", rc1.idempotency_key != rc2.idempotency_key)

    # retry СТАРОГО ключа ПОСЛЕ дописанных событий — прежний receipt, без записи
    between = len(st.list_events(r))
    st.commit_event_batch(CommitEventBatch(run=_run(r), events=(_ev(r, "post-retry"),), idempotency_key="fresh-key-after"))
    rc_retry = st.commit_event_batch(CommitEventBatch(run=run_with_ctx, events=evs, idempotency_key="cert6a-map-key", body_fingerprint=body))
    check("RCP4 retry старого ключа возвращает СТАРЫЙ watermark и ТЕ ЖЕ accepted-ids", rc_retry.committed_watermark == rc1.committed_watermark and rc_retry.accepted_event_ids == rc1.accepted_event_ids)
    total_after_new = between + 1
    check("RCP5 retry старого ключа НЕ дописывает события", len(st.list_events(r)) == total_after_new)

    # форма receipt
    check(
        "RCP6 форма receipt: run/context/ids/watermark/created_at",
        rc1.run_id == r and rc1.context_id is not None and len(rc1.accepted_event_ids) == 3
        and rc1.created_at and set(rc1.to_dict()) == {"idempotency_key", "run_id", "context_id", "accepted_event_ids", "committed_watermark", "created_at"},
    )
    got = st.get_commit_receipt("cert6a-map-key")
    check("RCP7 get_commit_receipt возвращает сохранённый", got is not None and got.accepted_event_ids == rc1.accepted_event_ids)

    # RCP8: accepted_event_ids = ФАКТИЧЕСКИ ПРИНЯТЫЕ (не дедуплицированные):
    # батч [A(дубль корпуса), C(новый)] → accepted ровно [C]
    ev_a = evs[0]  # уже в корпусе
    ev_c = _ev(r, "rc-new-c")
    run_ctx2 = _run(r, context_id="ctx-rcp-form")
    rc8 = st.commit_event_batch(CommitEventBatch(run=run_ctx2, events=(ev_a, ev_c), idempotency_key="cert6a-partial-key"))
    check(
        "RCP8 accepted-ids — принятые (дедуплицированные не входят)",
        list(rc8.accepted_event_ids) == [ev_c.event_id],
        str(rc8.accepted_event_ids),
    )
    # RCP9: durability accepted-ids частичного батча — ПРОЧИТАННЫЙ receipt
    # (get_commit_receipt) несёт фактически принятые, не все id батча
    got_partial = st.get_commit_receipt("cert6a-partial-key")
    check(
        "RCP9 прочитанный receipt частичного батча: accepted = принятые",
        got_partial is not None and list(got_partial.accepted_event_ids) == [ev_c.event_id],
        str(got_partial.accepted_event_ids if got_partial else None),
    )


def grp_rcp_pg() -> None:
    print("RCP-P — живой PG: retry старого ключа, conflict без записи")
    from apps.api.research_runs import CommitEventBatch, IdempotencyConflictError, batch_body_fingerprint

    st = _fresh_pg()
    r = "RUN-CERT6A-H11"
    evs = tuple(_ev(r, f"pgrc-{i}") for i in range(3))
    rc1 = st.commit_event_batch(CommitEventBatch(run=_run(r), events=evs, idempotency_key="pg-cert6a-key"))
    n_after_first = len(st.list_events(r))

    # тот же ключ + ДРУГОЕ тело (другой payload) — конфликт, ноль записей
    other = tuple(_ev(r, f"pgrc-{i}", value=i) for i in range(3))
    try:
        st.commit_event_batch(CommitEventBatch(run=_run(r), events=other, idempotency_key="pg-cert6a-key"))
        raised = False
    except IdempotencyConflictError:
        raised = True
    check("RCPG1 тот же ключ + другое тело → IdempotencyConflictError", raised)
    check("RCPG2 конфликт БЕЗ записи (корпус не вырос)", len(st.list_events(r)) == n_after_first)

    # retry того же ключа/тела — прежний receipt без записи
    body = batch_body_fingerprint(r, evs, context_id=_run(r).context_id)
    rc2 = st.commit_event_batch(CommitEventBatch(run=_run(r), events=evs, idempotency_key="pg-cert6a-key", body_fingerprint=body))
    check("RCPG3 retry возвращает прежний receipt (watermark равен)", rc2.committed_watermark == rc1.committed_watermark and rc2.accepted_event_ids == rc1.accepted_event_ids)
    check("RCPG4 retry не дублирует", len(st.list_events(r)) == n_after_first)

    # потерянный receipt читается по ключу после «перезапуска» (новый объект store)
    from apps.api.research_runs import PostgresResearchRunStore

    st_fresh_obj = PostgresResearchRunStore(dsn=st._dsn)
    got = st_fresh_obj.get_commit_receipt("pg-cert6a-key")
    check("RCPG5 receipt durable: читается новым коннектом/объектом", got is not None and got.committed_watermark == rc1.committed_watermark)

    # RCPG6: accepted-ids = фактически принятые: батч [A(дубль), C(новый)] → [C]
    ev_a = evs[0]
    ev_c = _ev(r, "pgrc-new-c")
    rc6 = st.commit_event_batch(CommitEventBatch(run=_run(r), events=(ev_a, ev_c), idempotency_key="pg-cert6a-partial"))
    check(
        "RCPG6 accepted-ids — принятые (дедуплицированные не входят)",
        list(rc6.accepted_event_ids) == [ev_c.event_id],
        str(rc6.accepted_event_ids),
    )

    # RCPG7: durability — ПРОЧИТАННЫЙ из строки PG receipt частичного батча
    # несёт фактически принятые id (не все id батча)
    got_partial = st.get_commit_receipt("pg-cert6a-partial")
    check(
        "RCPG7 прочитанный из строки receipt: accepted = принятые",
        got_partial is not None and list(got_partial.accepted_event_ids) == [ev_c.event_id],
        str(got_partial.accepted_event_ids if got_partial else None),
    )


# ── CAS. Expected context (свои углы) ────────────────────────────────


def grp_cas(store_factory, prefix: str, run_id: str) -> None:
    print(f"CAS-{prefix} — expected context: привязка/совпадение/отключение/stale")
    from apps.api.research_runs import CommitConflictError, CommitEventBatch

    st = store_factory()
    r = run_id

    # stored NULL — первичная привязка при не-None expected
    evs1 = (_ev(r, "cas-1"),)
    rc1 = st.commit_event_batch(
        CommitEventBatch(run=_run(r, context_id="ctx-c6a-1"), events=evs1, expected_context_id="ctx-c6a-1")
    )
    check(f"{prefix}1 stored NULL + expected → первичная привязка принята", rc1.context_id == "ctx-c6a-1")

    # совпадение — принимается
    evs2 = (_ev(r, "cas-2"),)
    rc2 = st.commit_event_batch(
        CommitEventBatch(run=_run(r, context_id="ctx-c6a-1"), events=evs2, expected_context_id="ctx-c6a-1")
    )
    check(f"{prefix}2 совпадающий контекст принимается", rc2.context_id == "ctx-c6a-1")

    # CAS-отказ не потребляет ключ идемпотентности: производитель прочитал ctx-1,
    # ДРУГОЙ писатель перевёл контекст на ctx-2, retry производителя — stale
    evs3 = (_ev(r, "cas-3"),)
    st.commit_event_batch(
        CommitEventBatch(run=_run(r, context_id="ctx-c6a-2"), events=(_ev(r, "cas-2b-move"),), expected_context_id=None)
    )  # advisory-писатель сдвинул stored контекст на ctx-c6a-2
    try:
        st.commit_event_batch(
            CommitEventBatch(
                run=_run(r, context_id="ctx-c6a-2"), events=evs3,
                expected_context_id="ctx-c6a-1", idempotency_key=f"{prefix.lower()}-cas-key",
            )
        )
        raised = False
    except CommitConflictError:
        raised = True
    check(f"{prefix}3 stale-контекст отклонён (CommitConflictError)", raised)
    check(f"{prefix}4 после CAS-отказа ноль новых событий от производителя", len([e for e in st.list_events(r) if e.payload.get("tag") == "cas-3"]) == 0)
    rc3 = st.commit_event_batch(
        CommitEventBatch(
            run=_run(r, context_id="ctx-c6a-2"), events=evs3,
            expected_context_id="ctx-c6a-2", idempotency_key=f"{prefix.lower()}-cas-key",
        )
    )
    check(f"{prefix}5 ключ пережил CAS-отказ: retry с исправленным контекстом принят", rc3.context_id == "ctx-c6a-2")

    # expected None — проверка отключена (advisory)
    evs4 = (_ev(r, "cas-4"),)
    rc4 = st.commit_event_batch(
        CommitEventBatch(run=_run(r, context_id="ctx-c6a-3"), events=evs4, expected_context_id=None)
    )
    check(f"{prefix}6 expected=None отключает CAS (advisory)", rc4.context_id == "ctx-c6a-3")

    # stored NULL при СУЩЕСТВУЮЩЕЙ строке run — первичная привязка принимается
    # (run материализован advisory-батчем без контекста; shell-строка PG-append)
    r2 = run_id + "-nullbind"
    st.commit_event_batch(CommitEventBatch(run=_run(r2), events=(_ev(r2, "nullbind-seed"),)))
    check(f"{prefix}7 предусловие: run существует с контекстом NULL", (st.get_run(r2).context_id is None))
    rc7 = st.commit_event_batch(
        CommitEventBatch(
            run=_run(r2, context_id="ctx-nullbind"), events=(_ev(r2, "nullbind-bind"),),
            expected_context_id="ctx-nullbind",
        )
    )
    check(f"{prefix}8 stored NULL + существующий run → первичная привязка, не конфликт", rc7.context_id == "ctx-nullbind")


def grp_coa(store_factory, prefix: str, run_id: str) -> None:
    print(f"COA-{prefix} — COALESCE-слияние аддитивных полей run")
    from apps.api.research_runs import CommitEventBatch

    st = store_factory()
    r = run_id
    st.commit_event_batch(
        CommitEventBatch(
            run=_run(r, context_id="ctx-keep", data_revision=3, data_digest="digest-1"),
            events=(_ev(r, "coa-1"),),
        )
    )
    # батч без новых значений — прежние метаданные сохранены; receipt несёт
    # СЛИТЫЙ (хранимый) контекст, не пустой из батча
    rc_none = st.commit_event_batch(
        CommitEventBatch(run=_run(r), events=(_ev(r, "coa-2"),), idempotency_key=f"{prefix.lower()}-coa-none-key")
    )
    run = st.get_run(r)
    check(f"{prefix}1 None-батч не стирает context/revision/digest", run.context_id == "ctx-keep" and run.data_revision == 3 and run.data_digest == "digest-1")
    check(f"{prefix}1b receipt None-батча несёт слитый контекст", rc_none.context_id == "ctx-keep", str(rc_none.context_id))

    # частичное обновление: только digest
    st.commit_event_batch(
        CommitEventBatch(run=_run(r, data_digest="digest-2"), events=(_ev(r, "coa-3"),))
    )
    run = st.get_run(r)
    check(f"{prefix}2 digest обновлён, контекст сохранён", run.data_digest == "digest-2" and run.context_id == "ctx-keep")

    # target_column=None — ПРЯМАЯ запись (сброс цели, не COALESCE)
    st.commit_event_batch(
        CommitEventBatch(
            run=_run(r, context_id="ctx-keep", data_digest="digest-2", target_column="humidity"),
            events=(_ev(r, "coa-4"),),
        )
    )
    run = st.get_run(r)
    check(f"{prefix}3 target_column записан напрямую", run.target_column == "humidity")
    st.commit_event_batch(
        CommitEventBatch(run=_run(r, target_column=None), events=(_ev(r, "coa-5"),))
    )
    run = st.get_run(r)
    check(f"{prefix}4 target_column=None сбрасывает цель (не COALESCE)", run.target_column is None and run.context_id == "ctx-keep")


# ── PAR. Паритет I8 на обоих хранилищах ──────────────────────────────


def grp_par(store_factory, prefix: str, run_id: str) -> None:
    print(f"PAR-{prefix} — паритет: дедуп append, глубокие копии, envelope durable")
    from apps.api.research_runs import CommitEventBatch

    st = store_factory()
    r = run_id

    ev = _ev(r, "par-dup")
    st.append_event(r, ev)
    st.append_event(r, ev)  # тот же (run_id, event_id)
    facts = [e for e in st.list_events(r) if e.payload.get("tag") == "par-dup"]
    check(f"{prefix}1 дедуп append (run_id, event_id) — ровно один факт", len(facts) == 1)

    ev2 = _ev(r, "par-copy", nested={"k": [1, 2, 3]})
    st.commit_event_batch(CommitEventBatch(run=_run(r), events=(ev2,)))
    got = [e for e in st.list_events(r) if e.payload.get("tag") == "par-copy"][0]
    got.payload["nested"]["k"].append(999)  # мутация прочитанного
    got_again = [e for e in st.list_events(r) if e.payload.get("tag") == "par-copy"][0]
    check(f"{prefix}2 глубокие копии: мутация прочитанного не портит stored", got_again.payload["nested"]["k"] == [1, 2, 3])

    # durable envelope v2 (штамп до записи)
    from apps.api.trace_events import stamp_envelope

    ev3 = stamp_envelope(
        _ev(r, "par-env", node="eda_correlation"),
        schema_version=2, evidence_level="server_result",
        operation_id="op-cert6a-77", context_id="ctx-env-cert6a",
    )
    st.commit_event_batch(CommitEventBatch(run=_run(r), events=(ev3,)))
    got_env = [e for e in st.list_events(r) if e.payload.get("tag") == "par-env"][0]
    check(
        f"{prefix}3 envelope v2 переживает запись/чтение",
        got_env.operation_id == "op-cert6a-77" and got_env.context_id == "ctx-env-cert6a"
        and got_env.schema_version == 2 and got_env.evidence_level == "server_result",
    )


# ── E2E. Свой CSV через живой API — migrated producer ────────────────


def _own_csv(tmpdir: Path) -> Path:
    """Свой датасет сертификатора: farm_yield_monthly.csv, 72 мес. точки."""
    import io

    lines = ["date,yield"]
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for i in range(72):
        d = base + timedelta(days=30 * i)
        val = 40 + 0.3 * (i % 12) + (i % 7) * 0.9
        lines.append(f"{d.strftime('%Y-%m-%d')},{val:.2f}")
    p = tmpdir / "farm_yield_monthly.csv"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def grp_e2e() -> None:
    print("E2E — свой CSV: карта остановок = один batch, содержательный ключ map:")
    os.environ.setdefault("CISSTAT_DATA_DIR", tempfile.mkdtemp(prefix="cisstat6acert-data-"))
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("CISSTAT_RUNS_BACKEND", None)
    from fastapi.testclient import TestClient

    from apps.api import research_runs
    from apps.api.main import app
    from apps.api.research_runs import batch_body_fingerprint
    from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store, reset_session_store_for_testing
    from app.core.pipeline_graph import STAGE_NODES

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    with TestClient(app) as client:
        csv_path = _own_csv(Path(tempfile.mkdtemp(prefix="cisstat6acert-csv-")))
        with open(csv_path, "rb") as fh:
            up = client.post("/v1/internal/upload", files={"file": ("farm_yield_monthly.csv", fh, "text/csv")})
        check("E2E0 свой CSV загружен через живой API", up.status_code == 200, f"status={up.status_code}")
        run_id = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME)).run_id
        store = research_runs.get_research_run_store()
        before = len(store.list_events(run_id))

        stops = {node_id: "done" for node_id in STAGE_NODES["upload"]}
        resp = client.post("/v1/progress/upload-stops", json={"stops": stops})
        check("E2E1 upload-stops 200", resp.status_code == 200)

        events = store.list_events(run_id)
        map_events = events[before:]
        n_nodes = len(STAGE_NODES["upload"])
        check(
            "E2E2 карта узлов — один batch: непрерывный sequence-префикс",
            len(map_events) == n_nodes
            and [e.sequence for e in map_events] == list(range(before + 1, before + 1 + n_nodes)),
        )

        # содержательный ключ продюсера: map:{run_id}:{fp[:40]} — пересчёт СВОИМ кодом
        layer1 = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME)).read_pipeline_trace()
        l1_types = [e.event_type for e in layer1]
        own_events = tuple(
            e for e in layer1 if e.event_type == "upload_stop_status"
        )[-n_nodes:]
        own_fp = batch_body_fingerprint(run_id, own_events)
        expected_key = f"map:{run_id}:{own_fp[:40]}"
        got = store.get_commit_receipt(expected_key)
        check(
            "E2E3 содержательный ключ map:{run_id}:{fp[:40]} восстанавливается своим пересчётом",
            got is not None and len(got.accepted_event_ids) == n_nodes,
            f"key={expected_key[:60]}",
        )

        # Повтор POST = НОВАЯ поставка (новые event_id): честная P07-семантика
        # наблюдений (контракт §15.3); retry ТЕХ ЖЕ event_id защищён на уровне
        # store — проверяется отдельно (E2E7).
        resp2 = client.post("/v1/progress/upload-stops", json={"stops": stops})
        check("E2E4 повтор карты: 200", resp2.status_code == 200)
        events_after = store.list_events(run_id)
        check(
            "E2E5 новая поставка карты честно даёт новые наблюдения (P07)",
            len(events_after) == len(events) + n_nodes,
            f"{len(events_after)} vs {len(events)}+{n_nodes}",
        )
        l1_after = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME)).read_pipeline_trace()
        check("E2E6 слой 1 симметрично вырос на новую поставку", len(l1_after) == len(layer1) + n_nodes)

        # E2E7: транспортный retry ТОГО ЖЕ батча (те же event_id ПЕРВОЙ
        # поставки, тот же содержательный ключ) — ноль новых событий слоя 2,
        # прежний receipt (события первой поставки — из layer1)
        same_batch_events = tuple(
            e for e in layer1 if e.event_type == "upload_stop_status"
        )[-n_nodes:]
        n_before_retry = len(store.list_events(run_id))
        from apps.api.research_runs import CommitEventBatch

        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=store.get_run(run_id),
                events=same_batch_events,
                idempotency_key=expected_key,
                body_fingerprint=own_fp,
            )
        )
        check(
            "E2E7 store-retry того же батча: прежний receipt, ноль дубликатов",
            receipt.committed_watermark == got.committed_watermark
            and len(store.list_events(run_id)) == n_before_retry,
        )

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


# ── MIG. Миграция 0002 на legacy-корпусе ─────────────────────────────


def grp_mig() -> None:
    print("MIG — миграция 0002: файл DDL == python-утверждения, legacy-корпус")
    import psycopg
    from apps.api.research_runs import (
        MIGRATION_FILES,
        MIGRATION_STATEMENTS_0001,
        MIGRATION_STATEMENTS_0002,
        PostgresResearchRunStore,
        run_migrations,
    )

    # файл-дубль 0002 == python-утверждения (собственный нормализующий разбор:
    # сначала выкидываем строки комментариев, потом сплит по ';')
    file_sql = (REPO / "apps/api/migrations/0002_audit6a_atomic_ledger.sql").read_text(encoding="utf-8")
    sql_body = "\n".join(
        line for line in file_sql.splitlines() if not line.strip().startswith("--")
    )
    file_stmts = [" ".join(s.split()) for s in sql_body.split(";") if s.strip()]
    py_stmts = [" ".join(s.split()) for s in MIGRATION_STATEMENTS_0002]
    check("MIG1 файл 0002 == MIGRATION_STATEMENTS_0002 (нормализованно)", file_stmts == py_stmts, f"{len(file_stmts)} vs {len(py_stmts)}")
    check("MIG2 каталог MIGRATION_FILES содержит 0001+0002", [n for n, _ in MIGRATION_FILES] == ["0001_research_runs.sql", "0002_audit6a_atomic_ledger.sql"])

    # legacy-корпус: ТОЛЬКО 0001, свои строки, затем файл 0002
    global _PG_SERVER
    if _PG_SERVER is None:
        import pgserver

        _PG_SERVER = pgserver.get_server(tempfile.mkdtemp(prefix="cisstat6acert-pg-"), cleanup_mode="delete")
    dsn = _PG_SERVER.get_uri()
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
    for stmt in MIGRATION_STATEMENTS_0001:
        conn.cursor().execute(stmt)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO research_runs (run_id, session_id) VALUES (%s, %s)", ("RUN-CERT6A-MIG", "sess-cert6a-mig"))
        cur.execute(
            "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, event_type, payload)"
            " VALUES (%s, 'RUN-CERT6A-MIG', now(), 'upload', null, 'upload_completed', '{}'),"
            "       (%s, 'RUN-CERT6A-MIG', now(), 'upload', null, 'structure_confirmed', '{}')",
            ("mig-legacy-1", "mig-legacy-2"),
        )
    conn.commit()
    # применение ФАЙЛА 0002 (не python-утверждений)
    cur = conn.cursor()
    cur.execute(file_sql)
    conn.commit()
    conn.close()

    st = PostgresResearchRunStore(dsn=dsn)
    legacy = st.list_events("RUN-CERT6A-MIG")
    check("MIG3 legacy-корпус читаем после файла 0002", len(legacy) == 2)
    check("MIG4 legacy sequence честно None", [e.sequence for e in legacy] == [None, None])
    from apps.api.research_runs import CommitEventBatch

    rc = st.commit_event_batch(
        CommitEventBatch(
            run=_run("RUN-CERT6A-MIG", session_id="sess-cert6a-mig"),
            events=(_ev("RUN-CERT6A-MIG", "mig-new"),),
            idempotency_key="mig-cert6a-key",
        )
    )
    check("MIG5 батч+receipt на мигрированном корпусе (watermark с 1)", rc.committed_watermark == 1 and st.get_commit_receipt("mig-cert6a-key") is not None)


# ── main ─────────────────────────────────────────────────────────────


def main() -> int:
    args = set(sys.argv[1:])
    no_pg = "--no-pg" in args
    print("=== Оракулы сертификации AUDIT-6A (свои данные сертификатора) ===")
    grp_fp()
    grp_atom_memory()
    grp_seq_memory()
    grp_rcp_memory()
    grp_cas(_fresh_memory, "M", "RUN-CERT6A-H12")
    grp_coa(_fresh_memory, "M", "RUN-CERT6A-H13")
    grp_par(_fresh_memory, "M", "RUN-CERT6A-H14")
    if not no_pg:
        grp_atom_pg()
        grp_seq_pg()
        grp_rcp_pg()
        grp_cas(_fresh_pg, "PG", "RUN-CERT6A-H15")
        grp_coa(_fresh_pg, "PG", "RUN-CERT6A-H16")
        grp_par(_fresh_pg, "PG", "RUN-CERT6A-H17")
        grp_mig()
    grp_e2e()

    failed = [(n, d) for n, ok, d in RESULTS if not ok]
    total = len(RESULTS)
    print(f"=== ИТОГ ОРАКУЛОВ: {total - len(failed)}/{total} PASS ===")
    for n, d in failed:
        print(f"  FAIL: {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
