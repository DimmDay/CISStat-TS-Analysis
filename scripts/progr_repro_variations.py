#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МАТРИЦА ВАРИАЦИЙ: какие настройки Мастера исправления выбросов дают
наблюдаемое тимлидом расхождение «карточка 'Выбросы' жёлтая, Прогресс
зелёный» после сообщения «Изменения применены, профиль пересчитан».

Каждая вариация -- ПОЛНЫЙ сценарий с нуля (своя сессия):
  upload -> date-column -> пропуски(interpolate) -> выбросы №1 (cap/iqr)
  -> станционарность (метод) -> выбросы №2 (ВАРИАЦИЯ) -> КАРТОЧКА vs TRACE.

Только измерение; никаких правок кода (read-only исследование).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    get_session_store,
    reset_session_store_for_testing,
)
from fastapi.testclient import TestClient  # noqa: E402

CSV = Path("/home/z/my-project/scripts/repro_data/forecast_monitor_synthetic_n150.csv")


def run_flow(name: str, fix2: dict, stationarity_method: str | None = "recommended") -> dict:
    """Полный сценарий; fix2 -- payload второй фиксации выбросов."""
    reset_session_store_for_testing()
    client = TestClient(app)
    result: dict = {"name": name}

    r = client.post("/v1/internal/upload", files={
        "file": (CSV.name, io.BytesIO(CSV.read_bytes()), "text/csv")})
    assert r.status_code == 200, r.text
    client.post("/v1/session/date-column", json={"column": "date"})

    # Пропуски -> interpolate
    mp = client.get("/v1/session/dataset/missing-profile").json()
    cols = list(mp.get("affected_columns")
                or [c["column"] for c in mp.get("columns", []) if c.get("missing_count")])
    if cols:
        client.post("/v1/session/dataset/missing-corrections",
                    json={"columns": cols, "strategy": "interpolate", "apply": True})

    # Выбросы №1: cap + iqr (мастер по умолчанию)
    p1 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    result["out1_found"] = p1["total_outliers"]
    if p1["total_outliers"] > 0:
        client.post("/v1/session/dataset/outlier-corrections", json={
            "columns": list(p1["affected_columns"]), "strategy": "cap",
            "method": "iqr", "param": 1.5, "apply": True})
    p1b = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    result["card_after_fix1"] = p1b["status"]

    # Стационарность: рекомендация или форсированный метод
    sp = client.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
    method = (sp.get("profile", {}).get("selected_method") if stationarity_method == "recommended"
              else stationarity_method)
    result["stationarity_method"] = method
    if method and method != "none":
        r = client.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                        json={"column": "value", "method": method, "apply": True,
                              "confirm_non_causal": True})
        assert r.status_code == 200, f"{method}: {r.text}"
        result["added_column"] = r.json().get("output_column")

    # Выбросы появились повторно?
    p2 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    result["reappeared"] = p2["total_outliers"]
    result["reappeared_cols"] = list(p2["affected_columns"])
    result["card_before_fix2"] = p2["status"]
    tr_mid = client.get("/v1/progress/trace").json()
    mid = {n["node_id"]: n for n in tr_mid.get("nodes", [])}.get("outliers", {})
    result["trace_before_fix2"] = mid.get("status")

    # Выбросы №2 (вариация)
    if p2["total_outliers"] > 0 or fix2.get("force_apply"):
        payload = {"columns": list(p2["affected_columns"]) or ["value_detrended"],
                   "apply": True}
        payload.update(fix2)
        r = client.post("/v1/session/dataset/outlier-corrections", json=payload)
        assert r.status_code == 200, f"{name}: {r.text}"
        resp = r.json()
        result["fix2_still_by_method"] = resp["total_still_outliers"]
        result["fix2_method"] = resp["method"]
        result["fix2_added_cols"] = resp["added_columns"]

    # ФИНАЛ: карточка vs trace
    p3 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    result["card_final"] = p3["status"]
    result["card_final_outliers"] = p3["total_outliers"]
    result["card_final_cols"] = list(p3["affected_columns"])
    tr = client.get("/v1/progress/trace").json()
    node = {n["node_id"]: n for n in tr.get("nodes", [])}.get("outliers", {})
    result["trace_final"] = node.get("status")
    result["DIVERGENCE"] = result["card_final"] != result["trace_final"]
    return result


def main() -> int:
    rows = []

    # V0: поток по умолчанию дважды (базлайн -- уже известен: зелёный/зелёный)
    rows.append(run_flow(
        "V0 base: 2-я фиксация cap/iqr 1.5 (мастер по умолчанию)",
        {"strategy": "cap", "method": "iqr", "param": 1.5}))

    # V1: стационарность = first_difference (аналитик выбрал разности),
    #     2-я фиксация cap/iqr
    rows.append(run_flow(
        "V1 стационарность=first_difference, 2-я фиксация cap/iqr",
        {"strategy": "cap", "method": "iqr", "param": 1.5},
        stationarity_method="first_difference"))

    # V2: 2-я фиксация strategy=flag («Добавить флаг выброса»)
    rows.append(run_flow(
        "V2 2-я фиксация strategy=flag (iqr)",
        {"strategy": "flag", "method": "iqr", "param": 1.5}))

    # V3: 2-я фиксация method=percentile (1/99) + cap
    rows.append(run_flow(
        "V3 2-я фиксация method=percentile(1/99) + cap",
        {"strategy": "cap", "method": "percentile", "param": [1, 99]}))

    # V4: 2-я фиксация method=zscore (3.0) + cap
    rows.append(run_flow(
        "V4 2-я фиксация method=zscore(3.0) + cap",
        {"strategy": "cap", "method": "zscore", "param": 3.0}))

    # V5: 2-я фиксация use_residual=True (STL-остаток) + cap, одна колонка
    reset_session_store_for_testing()
    client = TestClient(app)
    client.post("/v1/internal/upload", files={
        "file": (CSV.name, io.BytesIO(CSV.read_bytes()), "text/csv")})
    client.post("/v1/session/date-column", json={"column": "date"})
    mp = client.get("/v1/session/dataset/missing-profile").json()
    client.post("/v1/session/dataset/missing-corrections", json={
        "columns": list(mp.get("affected_columns")
                        or [c["column"] for c in mp.get("columns", []) if c.get("missing_count")]),
        "strategy": "interpolate", "apply": True})
    p1 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": list(p1["affected_columns"]), "strategy": "cap",
        "method": "iqr", "param": 1.5, "apply": True})
    client.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                json={"column": "value", "method": "linear_detrend", "apply": True,
                      "confirm_non_causal": True})
    p2 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    residual_col = list(p2["affected_columns"])[0]
    r = client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": [residual_col], "strategy": "cap", "method": "iqr",
        "param": 1.5, "use_residual": True, "date_column": "date", "apply": True})
    v5: dict = {"name": f"V5 2-я фиксация use_residual(STL) + cap по '{residual_col}'"}
    if r.status_code == 200:
        resp = r.json()
        v5["fix2_still_by_method"] = resp["total_still_outliers"]
    else:
        v5["fix2_http"] = r.status_code
        v5["fix2_error"] = r.json().get("detail", "")[:120]
    p3 = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    v5["card_final"] = p3["status"]
    v5["card_final_outliers"] = p3["total_outliers"]
    v5["card_final_cols"] = list(p3["affected_columns"])
    tr = client.get("/v1/progress/trace").json()
    node = {n["node_id"]: n for n in tr.get("nodes", [])}.get("outliers", {})
    v5["trace_final"] = node.get("status")
    v5["DIVERGENCE"] = v5["card_final"] != v5["trace_final"]
    rows.append(v5)

    # V6: 2-я фиксация drop_rows
    rows.append(run_flow(
        "V6 2-я фиксация strategy=drop_rows (iqr)",
        {"strategy": "drop_rows", "method": "iqr", "param": 1.5}))

    # V7: 2-я фиксация strategy=median
    rows.append(run_flow(
        "V7 2-я фиксация strategy=median (iqr)",
        {"strategy": "median", "method": "iqr", "param": 1.5}))

    # ── Таблица ──
    print("=" * 110)
    print(f"{'вариация':52s} | {'карточка ДО 2-й':15s} | {'trace ДО':9s} | "
          f"{'карточка ФИНАЛ':15s} | {'выбросов':8s} | {'trace ФИНАЛ':11s} | РАСХОЖДЕНИЕ")
    print("-" * 110)
    for row in rows:
        print(f"{row['name'][:52]:52s} | {str(row.get('card_before_fix2')):15s} | "
              f"{str(row.get('trace_before_fix2')):9s} | {str(row.get('card_final')):15s} | "
              f"{str(row.get('card_final_outliers')):8s} | {str(row.get('trace_final')):11s} | "
              f"{'>>> ДА <<<' if row.get('DIVERGENCE') else 'нет'}")
        if row.get("card_final_cols"):
            print(f"{'    остаются выбросы в:':52s} | {row['card_final_cols']}")
        if row.get("fix2_still_by_method") is not None:
            print(f"{'    still_outliers (по методу мастера):':52s} | {row['fix2_still_by_method']}")
        if row.get("fix2_error"):
            print(f"{'    ошибка мастера:':52s} | {row['fix2_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
