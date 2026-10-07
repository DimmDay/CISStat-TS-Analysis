#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДЕТАЛЬНАЯ ХРОНОЛОГИЯ воспроизводящей конфигурации (2-я фиксация
мастера со стратегией flag) + контроль дефолтной (cap).

Для каждого шага фиксируются ОДНОВРЕМЕННО: карточка «Выбросы» (степпер,
живой IQR-профиль) и узел outliers в /v1/progress/trace (события).
Только измерение, без правок кода.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from fastapi.testclient import TestClient  # noqa: E402

CSV = Path("/home/z/my-project/scripts/repro_data/forecast_monitor_synthetic_n150.csv")


def card(c: TestClient, mark: str) -> dict:
    d = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    print(f"  {mark:58s} КАРТОЧКА: status={d['status']:8s} outliers={d['total_outliers']:3d} "
          f"cols={d['affected_columns']}")
    return d


def trace(c: TestClient, mark: str) -> dict:
    tr = c.get("/v1/progress/trace").json()
    node = {n["node_id"]: n for n in tr.get("nodes", [])}.get("outliers", {})
    print(f"  {mark:58s} TRACE:   status={node.get('status'):8s} "
          f"reason={node.get('status_reason')!r} count={node.get('summary_count')}")
    return node


def events(c: TestClient, mark: str) -> None:
    sid = c.cookies.get(SESSION_COOKIE_NAME)
    ev = get_session_store().get(sid).pipeline_trace
    print(f"  {mark:58s} EVENTS:  " +
          " -> ".join(f"{e['event_type']}({e.get('node_id')})" for e in ev))


def run(label: str, fix2_payload: dict) -> None:
    print("\n" + "=" * 100)
    print(f"ПОТОК: {label}")
    print("=" * 100)
    reset_session_store_for_testing()
    c = TestClient(app)

    print("\n[1] Загрузка + структура:")
    c.post("/v1/internal/upload", files={"file": (CSV.name, io.BytesIO(CSV.read_bytes()), "text/csv")})
    c.post("/v1/session/date-column", json={"column": "date"})
    card(c, "после загрузки:")
    trace(c, "после загрузки:")

    print("\n[2] Пропуски -> interpolate (apply):")
    mp = c.get("/v1/session/dataset/missing-profile").json()
    cols = list(mp.get("affected_columns")
                or [x["column"] for x in mp.get("columns", []) if x.get("missing_count")])
    c.post("/v1/session/dataset/missing-corrections",
           json={"columns": cols, "strategy": "interpolate", "apply": True})
    st = c.get("/v1/session/dataset/missing-profile").json()["status"]
    print(f"  {'':58s} Пропуски: status={st}")

    print("\n[3] Выбросы, ПЕРВАЯ фиксация (мастер по умолчанию cap/iqr 1.5):")
    p1 = card(c, "до первой фиксации:")
    c.post("/v1/session/dataset/outlier-corrections", json={
        "columns": list(p1["affected_columns"]), "strategy": "cap",
        "method": "iqr", "param": 1.5, "apply": True})
    card(c, "после первой фиксации:")
    trace(c, "после первой фиксации:")

    print("\n[4] Стационарность: рекомендация -> добавление колонки:")
    sp = c.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
    method = sp["profile"]["selected_method"]
    r = c.post("/v1/session/dataset/preprocessing/stationarity-transformations",
               json={"column": "value", "method": method, "apply": True,
                     "confirm_non_causal": True}).json()
    print(f"  {'':58s} метод={method} -> колонка {r.get('output_column')} "
          f"(rows {r.get('rows_before')}->{r.get('rows_after')})")
    p2 = card(c, "ПОСЛЕ добавления колонки («опять выбросы»):")
    trace(c, "ПОСЛЕ добавления колонки:")
    events(c, "после добавления колонки:")

    print("\n[5] ВТОРАЯ фиксация (вариация):")
    payload = {"columns": list(p2["affected_columns"]), "apply": True}
    payload.update(fix2_payload)
    resp = c.post("/v1/session/dataset/outlier-corrections", json=payload).json()
    print(f"  {'':58s} ответ мастера: found={resp['total_outliers']} "
          f"changed={resp['total_changed']} still={resp['total_still_outliers']} "
          f"added={resp['added_columns']}")
    print(f"  {'':58s} (UI мастера пишет «Изменения применены, профиль пересчитан» "
          f"безусловно при HTTP 200)")
    fin_card = card(c, "ФИНАЛ (после сообщения мастера):")
    fin_node = trace(c, "ФИНАЛ (после сообщения мастера):")
    events(c, "ФИНАЛ:")
    print(f"\n  >>> КАРТОЧКА={fin_card['status']} (outliers={fin_card['total_outliers']}) "
          f"vs TRACE={fin_node.get('status')} (count={fin_node.get('summary_count')}) "
          f"-> {'РАСХОЖДЕНИЕ ВОСПРОИЗВЕДЕНО' if fin_card['status'] != fin_node.get('status') else 'согласованы'}")
    if fin_card["total_outliers"]:
        for item in fin_card["columns"]:
            if item["outlier_count"]:
                print(f"      остаток: {item['column']}: {item['outlier_count']} @ "
                      f"{item['outlier_examples']} bounds={item['bounds']}")
    print(f"  >>> payload события correction_applied №2:")
    sid = c.cookies.get(SESSION_COOKIE_NAME)
    ev = get_session_store().get(sid).pipeline_trace
    for e in ev[::-1]:
        if e["event_type"] == "correction_applied" and e.get("node_id") == "outliers":
            print("      " + json.dumps(e.get("payload", {}), ensure_ascii=False))
            break


def main() -> int:
    run("ДЕФОЛТ: 2-я фиксация strategy=cap, method=iqr, param=1.5",
        {"strategy": "cap", "method": "iqr", "param": 1.5})
    run("ВОСПРОИЗВОДЯЩАЯ: 2-я фиксация strategy=flag («Добавить флаг выброса»)",
        {"strategy": "flag", "method": "iqr", "param": 1.5})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
