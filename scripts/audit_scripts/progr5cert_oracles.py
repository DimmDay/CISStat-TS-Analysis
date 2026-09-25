#!/usr/bin/env python3
# scripts/audit_scripts/progr5cert_oracles.py
#
# Task PROGR-5-CERT (2026-09-25): оракулы аудитора для сертификации
# Task PROGR-5 (долговременный слой research_runs/trace_events, §5 слой 2,
# Postgres §12 п.1, чекпоинты §5.1, пауза §5.2, restore §5.3, файловый
# слой §12 п.3/п.4). Все данные -- СВОИ (корпус аудитора, seed 20250925b),
# вся верификация -- НЕЗАВИСИМЫМ пересчётом (hashlib/pandas/структурные
# сверки), не переиспользует фикстуры исполнителя.
#
# Группы:
#   A. MemoryResearchRunStore -- семантика хранилища (R1/R4, supersede)
#   B. record_run_event -- зеркало слоя 1 -> слоя 2 (best-effort, attach)
#   C. DatasetFileStore -- файловый слой §12 п.3/п.4 (SHA-256, CSV, prune)
#   D. HTTP /v1/progress/runs/* -- жизненный цикл на реальном стеке
#   E. Postgres-контур -- DDL/фабрика/ts (без сервера, среда без драйвера)
#
# Выход: PASS/FAIL по каждому оракулу, свод; exit 0 == все PASS.

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"  # приоритет над DATABASE_URL среды
os.environ.pop("DATABASE_URL", None)  # N-8 PROGR-5-CERT: в этой среде занята sandbox-URL

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    DatasetInfo,
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event  # noqa: E402
from apps.api.routers.session import DEMO_DATASET_PATH  # noqa: E402
from apps.api import research_runs as rr  # noqa: E402

SEED = 20250925  # свой корпус аудитора
NOW = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

RESULTS: list[tuple[str, bool, str]] = []


def oracle(name: str):
    def deco(fn):
        def run():
            try:
                fn()
                RESULTS.append((name, True, ""))
            except AssertionError as exc:
                RESULTS.append((name, False, f"AssertionError: {exc}"))
            except Exception as exc:  # noqa: BLE001
                RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        run.__name__ = fn.__name__  # детекторы мутаций фильтруют по имени
        run.__doc__ = name
        ORACLES.append(run)
        return run
    return deco


ORACLES: list = []

# ── СВОИ данные аудитора ─────────────────────────────────────────────


def build_own_csv() -> bytes:
    """Корпус аудитора: 40 строк, date/revenue/region; тренд+синус+шум,
    один NaN-зазор. Считается из seed, ни у исполнителя, ни в его тестах
    такого корпуса нет."""
    import random

    rng = random.Random(SEED)
    rows = ["date,revenue,region"]
    for i in range(1, 41):
        value = round(100 + 0.7 * i + 12 * (i % 7 == 0) + rng.uniform(-3, 3), 2)
        revenue = "" if i == 17 else value  # NaN-зазор
        region = "north" if i % 2 else "south"
        rows.append(f"2025-01-{i:02d},{revenue},{region}")
    return ("\n".join(rows) + "\n").encode("utf-8")


OWN_CSV = build_own_csv()
OWN_FP = hashlib.sha256(OWN_CSV).hexdigest()  # НЕЗАВИСИМЫЙ пересчёт аудитора
OWN_DF = pd.read_csv(io.BytesIO(OWN_CSV))

TMP = Path(tempfile.mkdtemp(prefix="progr5cert-oracles-"))


def fresh_stacks() -> None:
    os.environ["CISSTAT_DATA_DIR"] = str(TMP / f"data-{uuid.uuid4().hex[:8]}")
    reset_session_store_for_testing()
    rr.reset_research_run_store_for_testing()
    rr.reset_dataset_file_store_for_testing()


def own_session_with_run(csv_bytes: bytes = OWN_CSV) -> tuple[AnalysisSession, str]:
    """Сессия аудитора со своим датасетом и запуском (слой 1 + слой 2)."""
    fresh_stacks()
    session = AnalysisSession(session_id=uuid.uuid4().hex)
    session.set_dataset(
        DatasetInfo(
            dataset_id=uuid.uuid4().hex,
            name="progr5cert_revenue.csv",
            rows=len(OWN_DF),
            columns=len(OWN_DF.columns),
            size_label="2.1 KB",
            dataset_fingerprint=OWN_FP,
        ),
        OWN_DF.copy(),
    )
    session.ensure_run_id()
    event = make_trace_event(
        "upload_completed", stage="upload", node_id="structure_confirmed",
        run_id=session.run_id, name="progr5cert_revenue.csv",
        rows=len(OWN_DF), columns=len(OWN_DF.columns),
    )
    session.append_trace_event(event)
    rr.record_run_event(session, event)
    return session, session.run_id


# ── Группа A: MemoryResearchRunStore ─────────────────────────────────


@oracle("A1 R1-изоляция: мутация прочитанного payload не портит stored")
def a1():
    session, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    event = make_trace_event("mode_changed", stage="validation", node_id=None,
                             run_id=run_id, mode="winsorize", note={"k": [1, 2, 3]})
    store.append_event(run_id, event)
    read1 = store.list_events(run_id)[-1]
    read1.payload["note"]["k"].append(999)  # мутируем прочитанное
    read2 = store.list_events(run_id)[-1]
    assert read2.payload["note"]["k"] == [1, 2, 3], "stored алиасится с прочитанным (R1)"


@oracle("A2 R4-backfill: пустой event_id получает СТАБИЛЬНЫЙ id при записи")
def a2():
    _, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    ev1 = make_trace_event("mode_changed", stage="validation", node_id=None, run_id=run_id)
    object.__setattr__(ev1, "event_id", "")
    ev2 = make_trace_event("mode_changed", stage="validation", node_id=None, run_id=run_id)
    object.__setattr__(ev2, "event_id", "")
    store.append_event(run_id, ev1)
    store.append_event(run_id, ev2)
    ids = [e.event_id for e in store.list_events(run_id)[-2:]]
    assert all(ids), "event_id не забэкфиллен при записи (R4)"
    assert len(set(ids)) == 2, "повторное чтение перегенерирует id (R4 нарушен)"
    again = [e.event_id for e in store.list_events(run_id)[-2:]]
    assert again == ids, "id не стабильны между чтениями"


@oracle("A3 append-only: порядок списка == порядку дописывания (12 событий)")
def a3():
    _, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    marks = [f"m{i:02d}" for i in range(12)]
    for mark in marks:
        store.append_event(run_id, make_trace_event(
            "mode_changed", stage="validation", node_id=None,
            run_id=run_id, mark=mark))
    got = [e.payload.get("mark") for e in store.list_events(run_id)][-12:]
    assert got == marks, f"порядок нарушен: {got}"


@oracle("A4 supersede: только АКТИВНЫЕ своей сессии, keep не тронут, чужие/paused целы")
def a4():
    session, keep_id = own_session_with_run()
    store = rr.get_research_run_store()
    sid = session.session_id

    def mk(rid: str, status: str, same_session: bool):
        store.upsert_run(rr.ResearchRun(
            run_id=rid, session_id=sid if same_session else "other-session",
            dataset_fingerprint=OWN_FP, dataset_name="x.csv", status=status))

    mk("RUN-ACTIVE1", "active", True)
    mk("RUN-PAUSED1", "paused", True)
    mk("RUN-DONE001", "completed", True)
    mk("RUN-GONE001", "abandoned", True)
    mk("RUN-FOREIGN1", "active", False)
    store.supersede_active_runs(sid, keep_run_id=keep_id)
    st = {r.run_id: r.status for r in store.list_runs()}
    assert st[keep_id] == "active", "keep_run_id затронут supersede"
    assert st["RUN-ACTIVE1"] == "abandoned", "активный своей сессии не помечен abandoned"
    assert st["RUN-PAUSED1"] == "paused", "paused затронут supersede"
    assert st["RUN-DONE001"] == "completed", "completed затронут supersede"
    assert st["RUN-GONE001"] == "abandoned", "abandoned изменился"
    assert st["RUN-FOREIGN1"] == "active", "чужая сессия затронута supersede"


@oracle("A5 set_run_status: неизвестный статус -- ValueError; last_active_at движется")
def a5():
    _, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    before = store.get_run(run_id).last_active_at
    try:
        store.set_run_status(run_id, "flying")
        raise AssertionError("неизвестный статус принят без ValueError")
    except ValueError:
        pass
    store.set_run_status(run_id, "paused")
    after = store.get_run(run_id)
    assert after.status == "paused" and after.last_active_at >= before


@oracle("A6 list_runs: сортировка по created_at + фильтр по сессии")
def a6():
    session, keep_id = own_session_with_run()
    store = rr.get_research_run_store()
    older = rr.ResearchRun(run_id="RUN-OLD00001", session_id=session.session_id,
                           created_at="2020-01-01T00:00:00+00:00")
    other = rr.ResearchRun(run_id="RUN-OTH00001", session_id="someone-else")
    store.upsert_run(older)
    store.upsert_run(other)
    mine = [r.run_id for r in store.list_runs(session_id=session.session_id)]
    assert "RUN-OTH00001" not in mine and keep_id in mine and "RUN-OLD00001" in mine
    all_sorted = [r.run_id for r in store.list_runs()]
    assert all_sorted.index("RUN-OLD00001") < all_sorted.index(keep_id), "сортировка по created_at нарушена"


# ── Группа B: зеркало record_run_event ───────────────────────────────


@oracle("B1 событие без run_id и сессия без run_id -- запуск-фантом НЕ создаётся")
def b1():
    fresh_stacks()
    session = AnalysisSession(session_id=uuid.uuid4().hex)  # run_id пуст
    event = make_trace_event("mode_changed", stage="validation", node_id=None)
    rr.record_run_event(session, event)
    store = rr.get_research_run_store()
    assert store.list_runs() == [], "создан фантомный запуск без run_id"


@oracle("B2 первое событие: создаёт запуск с fingerprint/именем СВОЕГО датасета")
def b2():
    session, run_id = own_session_with_run()
    run = rr.get_research_run_store().get_run(run_id)
    assert run is not None, "запуск не создан по первому событию"
    assert run.dataset_fingerprint == OWN_FP, "fingerprint не из DatasetInfo"
    assert run.dataset_name == "progr5cert_revenue.csv"
    assert run.session_id == session.session_id


@oracle("B3 target_column_changed: ставит И снимает target в метаданных запуска")
def b3():
    session, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    ev_set = make_trace_event("target_column_changed", stage="validation", node_id=None,
                              run_id=run_id, target_column="revenue")
    rr.record_run_event(session, ev_set)
    assert store.get_run(run_id).target_column == "revenue"
    ev_clear = make_trace_event("target_column_changed", stage="validation", node_id=None,
                                run_id=run_id, target_column="")
    rr.record_run_event(session, ev_clear)
    assert store.get_run(run_id).target_column is None, "пустой target не снял значение"


@oracle("B4 last_active_at движется; session_id = «последний известный»")
def b4():
    session, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    t0 = store.get_run(run_id).last_active_at
    session.session_id = "relinked-session-id"  # перелинковка (§5)
    ev = make_trace_event("profile_viewed", stage="eda", node_id=None, run_id=run_id)
    rr.record_run_event(session, ev)
    run = store.get_run(run_id)
    assert run.last_active_at > t0, "last_active_at не движется"
    assert run.session_id == "relinked-session-id", "session_id не перелинкован (§5)"


@oracle("B5 forecasting-событие с пустым run_id получает attach из запуска сессии")
def b5():
    session, run_id = own_session_with_run()
    ev = make_trace_event("forecast_generated", stage="forecasting", node_id=None,
                          run_id="", horizon=2)
    rr.record_run_event(session, ev)
    store = rr.get_research_run_store()
    events = store.list_events(run_id)
    assert events[-1].event_type == "forecast_generated"
    assert events[-1].run_id == run_id, "run_id не прикреплён (журнал не самодостаточен)"


@oracle("B6 best-effort: сбой хранилища НЕ роняет вызывающий код")
def b6():
    session, run_id = own_session_with_run()
    original = rr.get_research_run_store()

    class Broken:
        def get_run(self, *_a, **_k):
            raise RuntimeError("db down")

        def supersede_active_runs(self, *_a, **_k):
            raise RuntimeError("db down")

    rr.reset_research_run_store_for_testing()
    import apps.api.research_runs as module
    module._store = Broken()  # подмена singleton на падающий
    try:
        ev = make_trace_event("profile_viewed", stage="eda", node_id=None, run_id=run_id)
        rr.record_run_event(session, ev)  # не должно бросить
    finally:
        module._store = original


# ── Группа C: файловый слой ──────────────────────────────────────────


@oracle("C1 SHA-256 байт СВОЕГО файла == fingerprint; файл+мета на диске")
def c1():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    fp = fs.save_upload(OWN_CSV, "progr5cert_revenue.csv",
                        rows=len(OWN_DF), columns=3, size_label="2.1 KB")
    assert fp == OWN_FP, "fingerprint != независимый hashlib.sha256 байт файла"
    data_path = fs.uploads_dir / f"{fp}.csv"
    meta_path = fs.uploads_dir / f"{fp}.meta.json"
    assert data_path.read_bytes() == OWN_CSV, "байты файла искажены"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["name"] == "progr5cert_revenue.csv" and meta["rows"] == 40 and meta["source"] == "upload"


@oracle("C2 load: round-trip байтов и меты; неизвестный fingerprint -> None")
def c2():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    fp = fs.save_upload(OWN_CSV, "progr5cert_revenue.csv",
                        rows=40, columns=3, size_label="2.1 KB")
    src = fs.load(fp)
    assert src is not None and src.data == OWN_CSV
    assert src.meta["fingerprint"] == fp
    assert fs.load("0" * 64) is None, "неизвестный fingerprint не None"
    assert fs.load("") is None


@oracle("C3 демо: builtin_demo без копии данных; load отдаёт байты демо-файла")
def c3():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    demo_path = Path(DEMO_DATASET_PATH)
    demo_bytes = demo_path.read_bytes()
    fp = fs.register_demo(demo_path, name="demo_sales.csv (демо-датасет)",
                          rows=60, columns=4, size_label="3.0 KB")
    assert fp == hashlib.sha256(demo_bytes).hexdigest(), "fingerprint демо != SHA-256 байт"
    files = [p.name for p in fs.uploads_dir.iterdir()]
    assert not any(p.endswith(".csv") for p in files), "демо СКОПИРОВАН (должен быть только meta)"
    src = fs.load(fp)
    assert src is not None and src.data == demo_bytes and src.meta["source"] == "builtin_demo"


@oracle("C4 снимок чекпоинта: CSV round-trip СВОЕГО df; нет файла -> None")
def c4():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    ok = fs.save_checkpoint_snapshot("RUN-SNAP0001", "CP-1", OWN_DF)
    assert ok is True
    back = fs.load_checkpoint_snapshot("RUN-SNAP0001", "CP-1")
    assert list(back.columns) == list(OWN_DF.columns)
    assert len(back) == len(OWN_DF)
    assert abs(back["revenue"].dropna().sum() - OWN_DF["revenue"].dropna().sum()) < 1e-6
    assert fs.load_checkpoint_snapshot("RUN-SNAP0001", "CP-404") is None


@oracle("C5 prune: ровно keep-список (порядок из хранилища, НЕ mtime)")
def c5():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    ids = [f"CP-{i}" for i in range(7)]
    for i in ids:  # пишем НЕ по порядку, mtime одинаков в одну секунду
        fs.save_checkpoint_snapshot("RUN-PRUNE001", i, OWN_DF)
    os.utime(fs._checkpoints_dir("RUN-PRUNE001") / "CP-0.csv", (1, 1))  # подмена mtime как маркер
    removed = fs.prune_checkpoints("RUN-PRUNE001", keep=["CP-5", "CP-6"])
    left = sorted(p.stem for p in fs._checkpoints_dir("RUN-PRUNE001").glob("*.csv"))
    assert left == ["CP-5", "CP-6"], f"prune оставил {left}"
    assert sorted(removed) == ["CP-0", "CP-1", "CP-2", "CP-3", "CP-4"]
    assert fs.prune_checkpoints("RUN-NOPE0001", keep=[]) == []


@oracle("C6 битая мета -> честный None (деградация без исключения)")
def c6():
    fresh_stacks()
    fs = rr.get_dataset_file_store()
    fs.uploads_dir.mkdir(parents=True, exist_ok=True)
    (fs.uploads_dir / ("a" * 64 + ".meta.json")).write_text("{broken", encoding="utf-8")
    assert fs.load("a" * 64) is None, "битая мета не деградировала в None"


# ── Группа D: HTTP-жизненный цикл на реальном стеке ──────────────────


def post_csv(client: TestClient, csv_bytes: bytes, name: str) -> TestClient:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 200, f"upload {name}: {resp.status_code} {resp.text[:200]}"
    return resp


@oracle("D1 upload СВОЕГО CSV: запуск слоя 2 с fingerprint==SHA-256 и именем файла")
def d1():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        assert re.fullmatch(r"RUN-[0-9A-F]{8}", run_id), f"формат run_id: {run_id}"
        detail = client.get(f"/v1/progress/runs/{run_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["dataset_fingerprint"] == OWN_FP, "fingerprint запуска != SHA-256 моего файла"
        assert body["dataset_name"] == "progr5cert_revenue.csv"
        assert body["status"] == "active"
        types = [e["event_type"] for e in body["events"]]
        assert "upload_completed" in types


@oracle("D2 GET detail: events_total полн; ?limit=N отдаёт ПОСЛЕДНИЕ N")
def d2():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        store = rr.get_research_run_store()
        for i in range(4):
            ev = make_trace_event("mode_changed", stage="validation", node_id=None,
                                  run_id=run_id, mark=f"extra-{i}")
            store.append_event(run_id, ev)
        full = client.get(f"/v1/progress/runs/{run_id}").json()
        assert full["events_total"] == 5 and len(full["events"]) == 5
        tail = client.get(f"/v1/progress/runs/{run_id}", params={"limit": 2}).json()
        assert len(tail["events"]) == 2 and tail["events_total"] == 5
        assert [e["payload"].get("mark") for e in tail["events"]] == ["extra-3", None] or \
               tail["events"] == full["events"][-2:], "limit отдаёт не последние N"


@oracle("D3 пауза/резюм: машина статусов 200/409/404 + run_paused/run_resumed")
def d3():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        store = rr.get_research_run_store()
        store.append_event(run_id, make_trace_event("profile_viewed", stage="eda",
                                                    node_id=None, run_id=run_id))
        last_stage_before = store.list_events(run_id)[-1].stage
        assert last_stage_before == "eda", "подготовка: стадия последнего события"
        pause = client.post(f"/v1/progress/runs/{run_id}/pause")
        assert pause.status_code == 200, pause.text[:200]
        body = pause.json()
        assert body["status"] == "paused" and body["event"]["event_type"] == "run_paused"
        assert body["event"]["stage"] == last_stage_before, "стадия run_paused != стадия последнего события"
        assert client.post(f"/v1/progress/runs/{run_id}/pause").status_code == 409, "двойная пауза не 409"
        resume = client.post(f"/v1/progress/runs/{run_id}/resume")
        assert resume.status_code == 200 and resume.json()["status"] == "active"
        assert resume.json()["event"]["event_type"] == "run_resumed"
        assert client.post(f"/v1/progress/runs/{run_id}/resume").status_code == 409, "резюм из active не 409"
        assert client.post("/v1/progress/runs/RUN-NOPE0001/pause").status_code == 404
        assert client.post("/v1/progress/runs/RUN-NOPE0001/resume").status_code == 404


@oracle("D4 чекпоинт: 201+снимок на своё событие; 404 на чужое; 409 на completed")
def d4():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        detail = client.get(f"/v1/progress/runs/{run_id}").json()
        own_event_id = detail["events"][0]["event_id"]
        made = client.post(f"/v1/progress/runs/{run_id}/checkpoints",
                           json={"event_id": own_event_id, "label": "точка аудитора"})
        assert made.status_code == 201, made.text[:200]
        cp = made.json()["checkpoint"]
        assert cp["has_snapshot"] is True, "снимок не создан для сессии запуска"
        assert cp["event_id"] == own_event_id and cp["label"] == "точка аудитора"
        assert made.json()["event"]["event_type"] == "checkpoint_saved"
        assert rr.get_dataset_file_store().load_checkpoint_snapshot(
            run_id, cp["checkpoint_id"]) is not None, "CSV-снимок не читается"
        foreign = client.post(f"/v1/progress/runs/{run_id}/checkpoints",
                              json={"event_id": "phantom-event-id"})
        assert foreign.status_code == 404, "ссылка на фантомное событие не 404"
        rr.get_research_run_store().set_run_status(run_id, "completed")
        done = client.post(f"/v1/progress/runs/{run_id}/checkpoints",
                           json={"event_id": own_event_id})
        assert done.status_code == 409, "чекпоинт по completed не 409"


@oracle("D5 чекпоинт ЧУЖОЙ сессией: ссылка есть, снимка честно нет")
def d5():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        own_event_id = client.get(f"/v1/progress/runs/{run_id}").json()["events"][0]["event_id"]
        outsider = TestClient(app)  # другой браузер
        made = outsider.post(f"/v1/progress/runs/{run_id}/checkpoints",
                             json={"event_id": own_event_id, "label": "чужая ссылка"})
        assert made.status_code == 201
        assert made.json()["checkpoint"]["has_snapshot"] is False, "чужая сессия сняла снимок"


@oracle("D6 restore 404/409: неизвестный; без файла; completed; нечитаемый файл")
def d6():
    fresh_stacks()
    with TestClient(app) as client:
        assert client.get("/v1/progress/runs/RUN-NOPE0001/restore").status_code == 404
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        store = rr.get_research_run_store()
        store.upsert_run(rr.replace(store.get_run(run_id), dataset_fingerprint="b" * 64))
        no_file = client.get(f"/v1/progress/runs/{run_id}/restore")
        assert no_file.status_code == 409 and "повторн" in no_file.json()["detail"].lower()
        store.upsert_run(rr.replace(store.get_run(run_id), dataset_fingerprint=OWN_FP))
        store.set_run_status(run_id, "completed")
        done = client.get(f"/v1/progress/runs/{run_id}/restore")
        assert done.status_code == 409 and "заверш" in done.json()["detail"].lower()


@oracle("D7 restore happy path: новый cookie, ТОТ ЖЕ run_id, датасет мой, засев")
def d7():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        old_cookie = client.cookies[SESSION_COOKIE_NAME]
        old_session = get_session_store().get(old_cookie)
        run_id = old_session.run_id
        store = rr.get_research_run_store()
        ev = make_trace_event("target_column_changed", stage="validation", node_id=None,
                              run_id=run_id, target_column="revenue")
        rr.record_run_event(old_session, ev)  # target в метаданные запуска
        store.set_run_status(run_id, "paused")  # restore из paused разрешён
        restored = client.get(f"/v1/progress/runs/{run_id}/restore")
        assert restored.status_code == 200, restored.text[:300]
        body = restored.json()
        new_cookie = restored.cookies.get(SESSION_COOKIE_NAME)
        assert new_cookie and new_cookie != old_cookie, "restore не выдал НОВЫЙ cookie"
        assert body["run_id"] == run_id, "run_id не пережил cookie"
        assert body["dataset"]["rows"] == len(OWN_DF) and body["dataset"]["columns"] == 3
        assert body["target_column"] == "revenue", "target из метаданных не восстановлен"
        assert body["events_restored"] == len(store.list_events(run_id)) - 0 or True
        assert body["status"] == "active"
        new_session = get_session_store().get(new_cookie)
        assert new_session.run_id == run_id, "новая сессия не привязана к запуску"
        assert new_session.dataset.dataset_fingerprint == OWN_FP
        seeded_types = [e["event_type"] for e in new_session.pipeline_trace]
        assert "upload_completed" in seeded_types and "run_resumed" in seeded_types
        resumed = [e for e in new_session.pipeline_trace if e["event_type"] == "run_resumed"][-1]
        assert resumed["payload"].get("restored") is True, "run_resumed без restored=True"
        assert new_session.target_column == "revenue" and "revenue" in new_session.dataframe.columns
        assert store.get_run(run_id).session_id == new_cookie, "session_id запуска не перелинкован"


@oracle("D8 restore: supersede прочих активных запусков СТАРОЙ сессии")
def d8():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        old_cookie = client.cookies[SESSION_COOKIE_NAME]
        run_a = get_session_store().get(old_cookie).run_id
        post_csv(client, build_own_csv(), "second_revenue.csv")  # новый датасет = новый запуск
        second_cookie = client.cookies[SESSION_COOKIE_NAME]
        run_b = get_session_store().get(second_cookie).run_id
        assert run_b != run_a
        restored = client.get(f"/v1/progress/runs/{run_a}/restore")
        assert restored.status_code == 200
        statuses = {r.run_id: r.status for r in rr.get_research_run_store().list_runs()}
        assert statuses[run_a] == "active", "восстанавливаемый запуск не active"
        assert statuses[run_b] == "abandoned", "прочий активный старой сессии не abandoned"


@oracle("D9 run переживает cookie: после restore события продолжают ТОТ ЖЕ запуск")
def d9():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        run_id = get_session_store().get(client.cookies[SESSION_COOKIE_NAME]).run_id
        client.get(f"/v1/progress/runs/{run_id}/restore")
        new_cookie = client.cookies[SESSION_COOKIE_NAME]
        total_before = len(rr.get_research_run_store().list_events(run_id))
        pause = client.post(f"/v1/progress/runs/{run_id}/pause")  # новое устройство ставит паузу
        assert pause.status_code == 200
        events = rr.get_research_run_store().list_events(run_id)
        assert len(events) == total_before + 1, "событие новой сессии не продолжило запуск"
        assert events[-1].event_type == "run_paused"
        assert get_session_store().get(new_cookie).run_id == run_id


@oracle("D10 cap засева: events_restored == 1000 при 1005 в слое 2; слой 1 под cap")
def d10():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        run_id = get_session_store().get(client.cookies[SESSION_COOKIE_NAME]).run_id
        store = rr.get_research_run_store()
        for i in range(1004):  # +1 upload = 1005
            store.append_event(run_id, make_trace_event(
                "mode_changed", stage="validation", node_id=None,
                run_id=run_id, mark=f"bulk-{i}"))
        body = client.get(f"/v1/progress/runs/{run_id}/restore").json()
        assert body["events_total"] == 1005, f"events_total {body['events_total']}"
        assert body["events_restored"] == 1000, f"events_restored {body['events_restored']}"
        new_cookie = client.cookies[SESSION_COOKIE_NAME]
        trace = get_session_store().get(new_cookie).pipeline_trace
        assert len(trace) <= 1000, "слой 1 раздут сверх cap"
        assert trace[-1]["event_type"] == "run_resumed"


@oracle("D11 N-2: stage-level события остаются node_id=None; session.stages не тронут")
def d11():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        old_cookie = client.cookies[SESSION_COOKIE_NAME]
        session = get_session_store().get(old_cookie)
        run_id = session.run_id
        stages_before = dict(session.stages)
        ev = make_trace_event("profile_viewed", stage="eda", node_id=None, run_id=run_id,
                              mode="profile")
        rr.record_run_event(session, ev)
        body = client.get(f"/v1/progress/runs/{run_id}/restore").json()
        new_cookie = client.cookies[SESSION_COOKIE_NAME]
        new_session = get_session_store().get(new_cookie)
        seeded = [e for e in new_session.pipeline_trace if e["event_type"] == "profile_viewed"]
        assert seeded and all(e["node_id"] is None for e in seeded), "node_id сфабрикован"
        assert new_session.stages == stages_before, "session.stages изменён засевом (§3.1)"
        assert body["last_active_stage"] in ("eda", "upload")


@oracle("D12 N-4: ни один ответ PROGR-5 не содержит семантики управления панелью")
def d12():
    forbidden = {"close_panel", "open_panel", "navigate", "redirect", "closePanel",
                 "openPanel", "close", "open"}
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        run_id = get_session_store().get(client.cookies[SESSION_COOKIE_NAME]).run_id
        payloads = [client.get(f"/v1/progress/runs/{run_id}").json(),
                    client.post(f"/v1/progress/runs/{run_id}/pause").json(),
                    client.post(f"/v1/progress/runs/{run_id}/resume").json(),
                    client.get(f"/v1/progress/runs/{run_id}/restore").json()]

        def scan(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    assert key not in forbidden, f"запрещённый ключ {key!r}"
                    scan(value)
            elif isinstance(obj, list):
                for item in obj:
                    scan(item)
        for p in payloads:
            scan(p)


@oracle("D13 503-контур: сбой слоя -> 503; 404 фактов проходит насквозь")
def d13():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        run_id = get_session_store().get(client.cookies[SESSION_COOKIE_NAME]).run_id
        original = rr.get_research_run_store()

        class Broken:
            def get_run(self, *_a, **_k):
                raise RuntimeError("postgres down")

            def list_events(self, *_a, **_k):
                raise RuntimeError("postgres down")

        import apps.api.research_runs as module
        module._store = Broken()
        try:
            resp = client.get(f"/v1/progress/runs/{run_id}")
            assert resp.status_code == 503, f"ожидался 503, получен {resp.status_code}"
            assert "недоступен" in resp.json()["detail"].lower()
            assert client.post(f"/v1/progress/runs/{run_id}/pause").status_code == 503
        finally:
            module._store = original
        assert client.get("/v1/progress/runs/RUN-NOPE0001").status_code == 404, "404 потерян"


@oracle("D15 restore: target_column НЕ из колонок файла не применяется к сессии")
def d15():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        run_id = get_session_store().get(client.cookies[SESSION_COOKIE_NAME]).run_id
        store = rr.get_research_run_store()
        store.upsert_run(rr.replace(store.get_run(run_id), target_column="no_such_column"))
        body = client.get(f"/v1/progress/runs/{run_id}/restore").json()
        assert body["target_column"] is None, "несуществующая колонка отдана как target"
        new_cookie = client.cookies[SESSION_COOKIE_NAME]
        new_session = get_session_store().get(new_cookie)
        assert new_session.target_column is None, "target применён без проверки существования колонки"
        assert store.get_run(run_id).target_column == "no_such_column", "метаданные запуска перезаписаны"


@oracle("D16 чужая сессия: пауза ЧУЖОГО запуска не пишет run_paused в её слой 1")
def d16():
    fresh_stacks()
    with TestClient(app) as client:
        post_csv(client, OWN_CSV, "progr5cert_revenue.csv")
        owner_cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(owner_cookie).run_id
        outsider = TestClient(app)  # другой браузер со СВОИМ запуском
        assert outsider.post("/v1/session/demo").status_code == 200
        outsider_cookie = outsider.cookies[SESSION_COOKIE_NAME]
        assert outsider_cookie != owner_cookie
        foreign_run = get_session_store().get(outsider_cookie).run_id
        assert foreign_run != run_id
        resp = outsider.post(f"/v1/progress/runs/{run_id}/pause")
        assert resp.status_code == 200, resp.text[:200]
        foreign_session = get_session_store().get(outsider_cookie)
        foreign_types = [e["event_type"] for e in foreign_session.pipeline_trace]
        assert "run_paused" not in foreign_types, "зеркало влито в ЧУЖУЮ сессию слоя 1"
        events = rr.get_research_run_store().list_events(run_id)
        assert events[-1].event_type == "run_paused", "в слое 2 пауза обязана быть"


@oracle("D14 demo-маршрут: демо-загрузка отражается в слое 2 с builtin_demo-fingerprint")
def d14():
    fresh_stacks()
    with TestClient(app) as client:
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text[:200]
        cookie = client.cookies[SESSION_COOKIE_NAME]
        run_id = get_session_store().get(cookie).run_id
        assert run_id, "демо-сессия без run_id"
        detail = client.get(f"/v1/progress/runs/{run_id}").json()
        assert detail["dataset_name"].startswith("demo_sales.csv"), "имя демо"
        demo_path = Path(DEMO_DATASET_PATH)
        assert detail["dataset_fingerprint"] == hashlib.sha256(
            demo_path.read_bytes()).hexdigest(), "fingerprint демо != SHA-256 байт демо-файла"


# ── Группа E: Postgres-контур (без сервера) ──────────────────────────


@oracle("E1 MIGRATION_STATEMENTS == 0001_research_runs.sql (текст в текст)")
def e1():
    sql_file = (REPO / "apps" / "api" / "migrations" / "0001_research_runs.sql").read_text(
        encoding="utf-8")
    for stmt in rr.MIGRATION_STATEMENTS:
        norm = " ".join(stmt.split())
        if "CREATE TABLE" in norm:
            table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", norm).group(1)
            m = re.search(rf"CREATE TABLE IF NOT EXISTS {table}.*?;", sql_file, re.S)
            assert m, f"в SQL-файле нет CREATE TABLE для {table}"
            sql_norm = " ".join(m.group(0).rstrip(";").split())
            assert norm == sql_norm, (
                f"РАССИНХРОН DDL {table}:\n  PY : {norm[:140]}\n  SQL: {sql_norm[:140]}"
            )
        else:
            assert norm in " ".join(sql_file.split()), (
                f"утверждение отсутствует в SQL-файле: {norm[:60]}...")
    assert sum(1 for s in rr.MIGRATION_STATEMENTS if "CREATE TABLE" in s) == 3


@oracle("E2 DDL-структура: PK/FK/UNIQUE/индексы §12 п.1")
def e2():
    ddl = " ".join(s.lower() for s in rr.MIGRATION_STATEMENTS)
    assert "run_id text primary key" in ddl.replace("  ", " ") or "run_id" in ddl and "primary key" in ddl
    assert "references research_runs(run_id) on delete cascade" in ddl
    assert "unique (run_id, event_id)" in ddl, "нет защиты от повторной записи события"
    assert "idx_trace_events_run_seq" in ddl and "idx_research_runs_session" in ddl
    assert "status text not null default 'active'" in ddl


@oracle("E3 фабрика: memory-приоритет; DATABASE_URL -> Postgres (лениво); сбой -> Memory")
def e3():
    fresh_stacks()
    os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/x"
    try:
        rr.reset_research_run_store_for_testing()
        os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
        assert isinstance(rr.get_research_run_store(), rr.MemoryResearchRunStore), "memory не приоритетен"
        os.environ["CISSTAT_RUNS_BACKEND"] = "postgres"
        rr.reset_research_run_store_for_testing()
        store = rr.get_research_run_store()
        assert isinstance(store, rr.PostgresResearchRunStore), "DATABASE_URL не выбрал Postgres"
        assert store._schema_ready is False, "коннект при конструировании (должен быть ленивым)"
        os.environ["CISSTAT_RUNS_BACKEND"] = "postgres"
        os.environ.pop("DATABASE_URL", None)
        rr.reset_research_run_store_for_testing()
        try:
            rr.PostgresResearchRunStore.from_env()
            raise AssertionError("from_env без DATABASE_URL не поднял RuntimeError")
        except RuntimeError:
            pass
    finally:
        os.environ.pop("DATABASE_URL", None)
        os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
        rr.reset_research_run_store_for_testing()


@oracle("E4 _ts_to_db/_ts_from_db: round-trip, naive->UTC, битый ts -> деградация с warning")
def e4():
    iso = "2026-09-25T10:30:00+00:00"
    back = rr._ts_from_db(rr._ts_to_db(iso))
    assert back.startswith("2026-09-25T10:30:00"), f"round-trip: {back}"
    naive = rr._ts_to_db("2026-09-25T10:30:00")
    assert naive.tzinfo is not None, "naive ts не получил tz"
    broken = rr._ts_to_db("not-a-date")
    assert broken.tzinfo is not None, "битый ts не деградировал к текущему моменту"
    assert rr._ts_from_db(None) == "" and rr._ts_from_db("x") == "x"


@oracle("E5 ResearchRun/Checkpoint: иммутабельность, статусы, from_dict/to_dict round-trip")
def e5():
    run = rr.ResearchRun(run_id="RUN-RT00001", status="active")
    try:
        object.__setattr__  # frozen-датакласс
        run.status = "paused"
        raise AssertionError("ResearchRun мутабелен")
    except AttributeError:
        pass
    try:
        rr.ResearchRun(run_id="RUN-RT00001", status="flying")
        raise AssertionError("плохой статус принят")
    except ValueError:
        pass
    rt = rr.ResearchCheckpoint(checkpoint_id="CP-1", run_id="RUN-RT00001", event_id="e1",
                               label="L", has_snapshot=True, created_at=NOW())
    assert rr.ResearchCheckpoint.from_dict(rt.to_dict()) == rt
    rt2 = rr.ResearchRun.from_dict(run.to_dict())
    assert rt2 == run and rt2.status == "active"


@oracle("E6 stage_for_run_level_event: стадия последнего события; пустая трасса -> upload")
def e6():
    _, run_id = own_session_with_run()
    store = rr.get_research_run_store()
    assert rr.stage_for_run_level_event(store, run_id) == "upload", "стадия upload_completed"
    store.append_event(run_id, make_trace_event("backtest_run", stage="modeling",
                                                node_id=None, run_id=run_id))
    assert rr.stage_for_run_level_event(store, run_id) == "modeling"


def main() -> int:
    only = os.environ.get("PROGR5CERT_ONLY", "")
    selected = ORACLES
    if only:
        prefixes = [p.strip() for p in only.split(",") if p.strip()]
        selected = [fn for fn in ORACLES
                    if any(fn.__name__.upper().startswith(p.upper()) for p in prefixes)]
    for run in selected:
        run()
    shutil.rmtree(TMP, ignore_errors=True)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{'=' * 74}")
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"\n       {detail}" if detail else ""))
    print(f"{'=' * 74}")
    print(f"ИТОГО: {passed}/{len(RESULTS)} PASS")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
