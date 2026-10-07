#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""REPRODUCTION: сценарий тимлида на демо-датасете
forecast_monitor_synthetic_n150.csv (FC-MON-2, 3 пропуска + 4 выброса).

Сценарий:
  Загрузка -> Валидация -> Предобработка: чинит Пропуски, Выбросы ->
  остановка «Стационарность ряда»: добавляет колонку по рекомендации ->
  выбросы появляются повторно -> повторно чинит выбросы (мастер,
  «Изменения применены, профиль пересчитан») ->
  ФАКТ: остановка «Выбросы» (степпер) vs узел «outliers» в /v1/progress/trace.

Скрипт только ВОСПРОИЗВОДИТ и ИЗМЕРЯЕТ (read-only относительно репо):
никаких правок кода, никаких fix. Все обращения к API -- штатные
эндпоинты платформы, тот же TestClient-паттерн, что в tests/api.
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

STEPS: list[str] = []


def step(label: str) -> None:
    STEPS.append(label)
    print(f"\n=== ШАГ {len(STEPS)}: {label}")


def card(client: TestClient, label: str = "") -> dict:
    """Состояние КАРТОЧКИ остановки «Выбросы» (степпер Предобработки):
    GET /dataset/outlier-profile?method=iqr -- тот же запрос, что в
    TsAnalysisPreprocessing.tsx строка 289."""
    r = client.get("/v1/session/dataset/outlier-profile?method=iqr")
    r.raise_for_status()
    data = r.json()
    print(f"  [КАРТОЧКА Выбросы]{label} status={data['status']!r} "
          f"total_outliers={data['total_outliers']} "
          f"numeric_cols={data['total_numeric_columns']} "
          f"affected={data['affected_columns']}")
    for item in data["columns"]:
        if item["outlier_count"]:
            print(f"      - {item['column']}: {item['outlier_count']} шт @ "
                  f"{item['outlier_examples']} (bounds={item['bounds']})")
    return data


def trace(client: TestClient, label: str = "", nodes=("outliers", "stationarity", "missing")) -> dict:
    """Состояние узлов в «Прогрессе»: GET /v1/progress/trace."""
    r = client.get("/v1/progress/trace")
    r.raise_for_status()
    data = r.json()
    by_id = {n["node_id"]: n for n in data.get("nodes", [])}
    for node_id in nodes:
        n = by_id.get(node_id)
        if n:
            print(f"  [TRACE {node_id}]{label} status={n.get('status')!r} "
                  f"reason={n.get('status_reason')!r} count={n.get('summary_count')}")
    return data


def events(client: TestClient, label: str = "") -> list[dict]:
    sid = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(sid)
    ev = session.pipeline_trace
    print(f"  [СОБЫТИЯ]{label} всего={len(ev)}: "
          + " -> ".join(f"{e['event_type']}({e.get('node_id')})" for e in ev))
    return ev


def main() -> int:
    reset_session_store_for_testing()
    client = TestClient(app)

    # ── ШАГ 1. Загрузка демо-датасета ──────────────────────────────
    step("Загрузка: POST /v1/internal/upload forecast_monitor_synthetic_n150.csv")
    csv_bytes = CSV.read_bytes()
    df0 = pd.read_csv(io.BytesIO(csv_bytes))
    print(f"  датасет: rows={len(df0)}, cols={list(df0.columns)}, "
          f"NaN в value={int(df0['value'].isna().sum())}")
    r = client.post(
        "/v1/internal/upload",
        files={"file": (CSV.name, io.BytesIO(csv_bytes), "text/csv")},
    )
    print(f"  HTTP {r.status_code}: {r.json()}")
    assert r.status_code == 200, r.text
    events(client)

    # ── ШАГ 2. Валидация: подтверждение структуры ──────────────────
    step("Валидация: POST /v1/session/date-column (подтверждение 'date')")
    r = client.post("/v1/session/date-column", json={"column": "date"})
    print(f"  HTTP {r.status_code}: date_column={r.json().get('date_column')}")
    assert r.status_code == 200, r.text
    events(client)

    # ── ШАГ 3. Предобработка, остановка «Пропуски» ─────────────────
    step("Предобработка/Пропуски: профиль -> интерполяция (apply)")
    r = client.get("/v1/session/dataset/missing-profile")
    mp = r.json()
    print(f"  [КАРТОЧКА Пропуски] status={mp['status']!r} "
          f"total_missing={mp.get('total_missing')} "
          f"affected={mp.get('affected_columns')}")
    cols = mp.get("affected_columns") or [c["column"] for c in mp["columns"] if c.get("missing_count")]
    r = client.post("/v1/session/dataset/missing-corrections", json={
        "columns": cols, "strategy": "interpolate", "apply": True,
    })
    print(f"  HTTP {r.status_code}: applied={r.json().get('applied')} "
          f"total_missing={r.json().get('total_missing', 'n/a')}")
    assert r.status_code == 200, r.text
    r = client.get("/v1/session/dataset/missing-profile")
    print(f"  [КАРТОЧКА Пропуски после] status={r.json()['status']!r} "
          f"total_missing={r.json().get('total_missing')}")
    events(client)

    # ── ШАГ 4. Предобработка, остановка «Выбросы» (ПЕРВОЕ исправление)
    step("Предобработка/Выбросы: профиль -> preview -> apply (cap, iqr 1.5)")
    before = card(client, " ДО первого исправления")
    assert before["total_outliers"] > 0, "в демо-датасете должны быть выбросы"
    affected1 = list(before["affected_columns"])
    r = client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": affected1, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": False,
    })
    pv = r.json()
    print(f"  preview: HTTP {r.status_code} found={pv['total_outliers']} "
          f"changed={pv['total_changed']} still={pv['total_still_outliers']}")
    r = client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": affected1, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": True,
    })
    ap = r.json()
    print(f"  apply: HTTP {r.status_code} applied={ap['applied']} "
          f"found={ap['total_outliers']} changed={ap['total_changed']} "
          f"still={ap['total_still_outliers']} rows_removed={ap['rows_removed']} "
          f"added_cols={ap['added_columns']}")
    after1 = card(client, " ПОСЛЕ первого исправления (мастер бы написал «профиль пересчитан»)")
    trace(client, " после первого исправления")
    events(client)

    # ── ШАГ 5. Остановка «Стационарность ряда»: рекомендация ───────
    step("Предобработка/Стационарность: GET stationarity-profile (рекомендация)")
    r = client.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value")
    sp = r.json()
    prof = sp.get("profile", {})
    print(f"  HTTP {r.status_code}: card_status={sp.get('status')!r} "
          f"consensus_before={prof.get('consensus_before')} "
          f"selected_method={prof.get('selected_method')} "
          f"needs_transformation={prof.get('needs_transformation')}")
    rec = prof.get("recommendation")
    print(f"  recommendation={rec!r}")
    method = prof.get("selected_method") or "first_difference"
    assert method and method != "none", f"метод не определён: {method!r}"

    # ── ШАГ 6. Стационарность: добавление колонки (apply) ──────────
    step(f"Предобработка/Стационарность: POST stationarity-transformations "
         f"(method={method}, apply=true) -- «добавляет колонки по рекомендации»")
    r = client.post("/v1/session/dataset/preprocessing/stationarity-transformations", json={
        "column": "value", "method": method, "apply": True,
        "confirm_non_causal": True,
    })
    print(f"  HTTP {r.status_code}: {json.dumps(r.json(), ensure_ascii=False)[:400]}")
    assert r.status_code == 200, r.text
    st_resp = r.json()
    print(f"  output_column={st_resp.get('output_column')} "
          f"lost_observations={st_resp.get('lost_observations')}")
    trace(client, " после добавления колонки")
    events(client)

    # ── ШАГ 7. «Опять появляются выбросы» ──────────────────────────
    step("Возврат на остановку «Выбросы»: профиль ПОСЛЕ добавления колонки")
    reappeared = card(client, " ПОСЛЕ добавления колонки стационарности")
    affected2 = list(reappeared["affected_columns"])
    assert reappeared["total_outliers"] > 0, "ожидалось повторное появление выбросов"

    # ── ШАГ 8. Повторное исправление выбросов ──────────────────────
    step(f"Повторное исправление: preview -> apply (cap, iqr 1.5, "
         f"columns={affected2}) -- мастер пишет «Изменения применены, профиль пересчитан»")
    r = client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": affected2, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": False,
    })
    pv2 = r.json()
    print(f"  preview: HTTP {r.status_code} found={pv2['total_outliers']} "
          f"changed={pv2['total_changed']} still={pv2['total_still_outliers']}")
    for c in pv2["columns"]:
        print(f"      - {c['column']}: found={c['outlier_count']} "
              f"changed={c['changed_count']} still={c['still_outliers']}")
    r = client.post("/v1/session/dataset/outlier-corrections", json={
        "columns": affected2, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": True,
    })
    ap2 = r.json()
    print(f"  apply: HTTP {r.status_code} applied={ap2['applied']} "
          f"found={ap2['total_outliers']} changed={ap2['total_changed']} "
          f"still={ap2['total_still_outliers']} rows_removed={ap2['rows_removed']}")
    for c in ap2["columns"]:
        print(f"      - {c['column']}: found={c['outlier_count']} "
              f"changed={c['changed_count']} still={c['still_outliers']}")

    # ── ШАГ 9. РАЗВОДКА: карточка vs Прогресс (ГЛАВНЫЙ ФАКТ) ───────
    step("РАЗВОДКА после повторного исправления: КАРТОЧКА vs ПРОГРЕСС")
    final_card = card(client, " ФИНАЛ (степпер Предобработки)")
    tr = trace(client, " ФИНАЛ")
    events(client, " ФИНАЛ")

    # Полный трейс-дамп узла outliers
    by_id = {n["node_id"]: n for n in tr.get("nodes", [])}
    if "outliers" in by_id:
        print("\n  [TRACE узел outliers ПОЛНОСТЬЮ]:")
        print("  " + json.dumps(by_id["outliers"], ensure_ascii=False, indent=2).replace("\n", "\n  "))

    # ── Вердикт воспроизведения ────────────────────────────────────
    card_status = final_card["status"]
    trace_status = by_id.get("outliers", {}).get("status")
    print("\n" + "=" * 72)
    print("ИТОГ ВОСПРОИЗВЕДЕНИЯ (поток по умолчанию: cap + iqr 1.5):")
    print(f"  КАРТОЧКА «Выбросы» (живой профиль IQR): status={card_status!r} "
          f"total_outliers={final_card['total_outliers']}")
    print(f"  TRACE «outliers» (события correction_applied): status={trace_status!r}")
    if card_status != trace_status:
        print("  >>> РАСХОЖДЕНИЕ ВОСПРОИЗВЕДЕНО: карточка != trace")
    else:
        print("  >>> расхождения НЕТ в потоке по умолчанию -- "
              "нужны вариации (flag/drop_rows/метод) -- см. следующие пробы")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
