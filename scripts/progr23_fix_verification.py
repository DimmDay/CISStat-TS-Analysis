#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПРОТОКОЛ ВЕРИФИКАЦИИ ФИКСОВ G345 (Task PROGR-23) -- тот же сценарий,
что в scripts/progr_h345_cap_iqr.py (закреплённые (iqr, cap)), но на
ИСПРАВЛЕННОМ коде: проверка закрытия расхождения «жёлтая карточка /
зелёный Прогресс» и «окна лжи».

Проверяемые контракты:
  Ф1 трассировка GET-пересчётов: после stationarity-apply (производная
     колонка с выбросами) живой пересчёт карточки сеет
     outliers_profile_status -- Прогресс показывает warning в окне
     «выбросы появились -> следующая коррекция» (раньше: done);
  Ф2 семантика last-wins: apply несёт честный исход в КАРТОЧНОЙ шкале
     (status/total_outliers_after) -- класс C5 (снятый чекбокс колонки
     с выбросами) оставляет узел warning, бейдж = карточному числу;
  Ф3 честный баннер: носители фактов в ответе apply (проверка текста --
     фронт-тесты PreprocessingOutliersPipeline.test.tsx).

Датасет: детерминированный генератор scripts/dataset_forecast_monitor.py
(forecast_monitor_synthetic_n150: тренд+сезон, 4 выброса, 3 пропуска).

Правила AGENTS.md: только измерение, без commit/push.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from fastapi.testclient import TestClient  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = REPO / "scripts" / "progr23_fix_verification.txt"


def generate_series() -> pd.DataFrame:
    """Детерминированный аналог forecast_monitor_synthetic_n150.csv
    (формула генератора scripts/dataset_forecast_monitor.py, без шума;
    тот же кадр, что в tests/api/test_progress_progr23.py): тренд +
    сезон M=12, 4 выброса, 3 пропуска."""
    t = np.arange(150, dtype=float)
    value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    value[25] += 110
    value[70] += 105
    value[105] += 95
    value[130] -= 135
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )
    frame.loc[[45, 87, 122], "value"] = np.nan
    return frame

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def card(c: TestClient, mark: str) -> dict:
    d = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    emit(f"    {mark:52s} КАРТОЧКА(iqr): status={d['status']:8s} outliers={d['total_outliers']}")
    return d


def trace_node(c: TestClient, mark: str) -> dict:
    tr = c.get("/v1/progress/trace").json()
    node = {n["node_id"]: n for n in tr.get("nodes", []) if n.get("stage") == "preprocessing"}.get("outliers", {})
    emit(f"    {mark:52s} TRACE: status={node.get('status'):8s} count={node.get('summary_count')} "
         f"reason={str(node.get('status_reason'))[:44]!r}")
    return node


def fix2(c: TestClient, name: str, payload: dict) -> dict:
    emit("\n" + "=" * 100)
    emit(f"ПОТОК: {name} (закреплённые (iqr, cap), 2-я фиксация)")
    emit("=" * 100)

    reset_session_store_for_testing()
    c.cookies.clear()
    emit("\n  [1-3] Загрузка -> дата -> пропуски(interpolate) -> выбросы №1 (cap/iqr1.5):")
    csv = generate_series().to_csv(index=False)
    assert c.post("/v1/internal/upload", files={
        "file": ("forecast_monitor_synthetic_n150.csv", io.BytesIO(csv.encode()), "text/csv")}).status_code == 200
    c.post("/v1/session/date-column", json={"column": "date"})
    mp = c.get("/v1/session/dataset/missing-profile").json()
    cols = [x["column"] for x in mp["columns"] if x.get("missing_count")]
    c.post("/v1/session/dataset/missing-corrections", json={"columns": cols, "strategy": "interpolate", "apply": True})
    p1 = card(c, "до 1-й фиксации:")
    c.post("/v1/session/dataset/outlier-corrections",
           json={"columns": p1["affected_columns"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True})
    card(c, "после 1-й фиксации:")
    trace_node(c, "после 1-й фиксации:")

    emit("\n  [4] Стационарность: рекомендация -> apply (производная колонка):")
    sp = c.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
    method = sp["profile"]["selected_method"]
    st = c.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                json={"column": "value", "method": method, "apply": True, "confirm_non_causal": True})
    assert st.status_code == 200, st.text
    emit(f"    {'':52s} метод={method} -> {st.json().get('output_column')}")

    emit("\n  [5] «Окно лжи» (Г5): карточка видит выбросы, что видит Прогресс?")
    p2 = card(c, "ПОСЛЕ добавления колонки (живой пересчёт):")
    node_mid = trace_node(c, "ПОСЛЕ добавления колонки:")
    window_honest = p2["status"] == node_mid.get("status")
    emit(f"    {'':52s} >>> ОКНО Лжи {'ЗАКРЫТО (card == trace)' if window_honest else 'ЕЩЁ ЕСТЬ (card != trace)'}")

    emit("\n  [6] 2-я фиксация (preview -> apply):")
    base = {"columns": list(p2["affected_columns"]), "strategy": "cap", "method": "iqr", "param": 1.5}
    base.update(payload)
    c.post("/v1/session/dataset/outlier-corrections", json={**base, "apply": False})
    trace_node(c, "после preview №2 (correction_previewed):")
    ap = c.post("/v1/session/dataset/outlier-corrections", json={**base, "apply": True})
    assert ap.status_code == 200, ap.text
    body = ap.json()
    emit(f"    {'ОТВЕТ МАСТЕРА (apply):':52s} found={body['total_outliers']} changed={body['total_changed']} "
         f"still={body['total_still_outliers']} КАРТОЧНАЯ шкала: status={body['status']} "
         f"outliers_after={body['total_outliers_after']}")

    fin = card(c, "ФИНАЛ:")
    node_fin = trace_node(c, "ФИНАЛ:")
    consistent = fin["status"] == node_fin.get("status")
    emit(f"    {'':52s} >>> ФИНАЛ: card={fin['status']} vs trace={node_fin.get('status')} -> "
         f"{'СОГЛАСОВАНЫ' if consistent else 'РАСХОЖДЕНИЕ'}")
    return {"name": name, "window_honest": window_honest, "final_consistent": consistent,
            "card": fin["status"], "trace": node_fin.get("status"),
            "apply_status": body["status"], "apply_after": body["total_outliers_after"]}


def main() -> int:
    c = TestClient(app)
    results = [
        fix2(c, "C0 контроль: k=1.5, все предзаполненные колонки", {}),
        fix2(c, "C5 класс: частичный выбор (производная колонка снята)", {"columns": ["value"]}),
    ]
    emit("\n" + "=" * 100)
    emit("СВОДКА (исправленный код)")
    emit("=" * 100)
    ok = True
    for r in results:
        emit(f"  {r['name'][:66]:66s} окно: {'закрыто' if r['window_honest'] else 'ЕСТЬ'}; "
             f"финал: card={r['card']} trace={r['trace']} "
             f"({'СОГЛАСОВАНЫ' if r['final_consistent'] else 'РАСХОЖДЕНИЕ'}); "
             f"apply отчитал карточную шкалу: status={r['apply_status']} after={r['apply_after']}")
        ok = ok and r["window_honest"] and r["final_consistent"]
    emit("\nВЕРДИКТ: " + ("все расхождения G345 закрыты на уровне API (Ф1+Ф2); честный баннер (Ф3) -- "
                          "фронт-тесты packages/ui/components/PreprocessingOutliersPipeline.test.tsx."
                          if ok else "ЕСТЬ НЕЗАКРЫТЫЕ РАСХОЖДЕНИЯ -- см. протокол выше."))
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"\nПротокол сохранён: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
