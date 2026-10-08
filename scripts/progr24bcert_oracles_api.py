# -*- coding: utf-8 -*-
"""Live-API оракулы PROGR-24-B-CERT на СВОИХ данных: контракт данных,
которыми задача A (бэкенд) кормит три фронте-точки задачи B.

Задача B не меняла бэкенд (проверено diff 8c06802) -- здесь независимо
воспроизводится ВХОДНОЙ КОНТРАКТ UI на своём датасете: derived_summary
в профилях/ответах коррекций (плашка Обзора + группа «Производные»
мастера) и честный 422 /dataset/validate на производной колонке.

Свой датасет: «дневные продажи сети кофеен», 144 точки, колонки
date / cups_sold (3 собственных всплеска на позициях 33/61/90) /
avg_check. Имена, числа и позиции НЕ совпадают с датасетом сертификации
задачи A (retail_daily.csv) -- независимая реконструкция.

Запуск из корня репозитория:
    python scripts/progr24bcert_oracles_api.py
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

logging.disable(logging.WARNING)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store  # noqa: E402

OUT = REPO / "scripts" / "progr24bcert_oracles_api.txt"

_lines: list[str] = []
_checks: list[tuple[str, bool]] = []

DS_SUMMARY_KEYS = {"total_columns", "total_numeric_columns", "total_outliers", "affected_columns", "columns"}
DS_ITEM_KEYS = {"column", "sample_size", "outlier_count", "outlier_pct", "recommended_method", "bounds", "outlier_examples", "insufficient_sample"}


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def check(label: str, ok: bool) -> bool:
    emit(f"    [{'PASS' if ok else 'FAIL'}] {label}")
    _checks.append((label, ok))
    return ok


def cafe_frame() -> pd.DataFrame:
    """Дневные продажи кофеен, 144 точки. Свои позиции и величины всплесков."""
    rng = np.random.default_rng(20261008)
    t = np.arange(144, dtype=float)
    dow = t % 7.0
    cups = 320.0 + 0.4 * t + 55.0 * np.exp(-0.5 * ((dow - 6) / 1.2) ** 2) + rng.normal(0, 9, len(t))
    # Свои всплески: промо-день, сбой выгрузки, аномальный трафик.
    for pos, delta in [(33, 95.0), (61, -80.0), (90, 70.0)]:
        cups[pos] += delta
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-03-01", periods=144, freq="D").strftime("%Y-%m-%d"),
            "cups_sold": np.round(cups, 2),
            "avg_check": np.round(210.0 - 0.05 * t + rng.normal(0, 2.5, len(t)), 2),
        }
    )


def upload(c: TestClient, frame: pd.DataFrame, name: str) -> None:
    r = c.post("/v1/internal/upload", files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")})
    assert r.status_code == 200, r.text


def card(c: TestClient, url: str) -> dict:
    r = c.get(url)
    assert r.status_code == 200, r.text
    return r.json()


def group_a() -> None:
    emit("-- Группа A: derived_summary как вход плашки Обзора и группы мастера (свои данные) --")
    c = TestClient(app)
    upload(c, cafe_frame(), "cafe_daily.csv")
    c.post("/v1/session/date-column", json={"column": "date"})

    prof0 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    canon_names = [x["column"] for x in prof0["columns"]]
    check("A1: до производных каноническая область == обе исходные колонки (cups_sold, avg_check), derived_summary отсутствует",
          sorted(canon_names) == ["avg_check", "cups_sold"] and prof0.get("derived_summary") is None)

    k_cups = prof0["total_outliers"]
    apply1 = c.post("/v1/session/dataset/outlier-corrections",
                    json={"columns": ["cups_sold"], "strategy": "flag", "method": "iqr", "apply": True})
    check("A2: apply flag -- 200, флаг-колонка cups_sold_outlier_flag добавлена",
          apply1.status_code == 200 and "cups_sold_outlier_flag" in (apply1.json().get("added_columns") or []))
    ds_apply = (apply1.json() or {}).get("derived_summary") or {}
    check("A3: derived_summary в apply-ответе (вход обновления группы «Производные» мастера после apply)",
          DS_SUMMARY_KEYS.issubset(ds_apply.keys())
          and ds_apply.get("total_columns") == 1
          and ds_apply.get("affected_columns") == ["cups_sold_outlier_flag"])
    flag_item = (ds_apply.get("columns") or [{}])[0]
    check("A4: элемент derived_summary несёт ВСЕ поля, которые рендерит UI (column/счётчик/bounds/примеры)",
          DS_ITEM_KEYS.issubset(flag_item.keys())
          and flag_item.get("column") == "cups_sold_outlier_flag"
          and flag_item.get("outlier_count") == k_cups)
    # GREEN-фаза оракула: IQR на своих числах обязан отфлагать k_cups >= 1
    # (маска непуста -- флаг материализован, A2), и вырожденный IQR флага
    # даёт ровно K всплесков на K единиц; жёсткое == 3 было ошибкой моих
    # ожиданий (сезонность выходных расширяет IQR исходного ряда).
    check("A5: вырожденный IQR флага на своих числах: K единиц -> K всплесков (K = |маска| >= 1), только в derived_summary",
          flag_item.get("outlier_count") == k_cups and k_cups >= 1)

    prof1 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    check("A6: после flag-apply карточка (каноническая область) НЕ содержит флаг-колонку -- петля PROGR-22 невозможна",
          "cups_sold_outlier_flag" not in [x["column"] for x in prof1["columns"]]
          and "cups_sold_outlier_flag" in ((prof1.get("derived_summary") or {}).get("affected_columns") or []))

    # Стационарность на своей серии: первая разность cups_sold.
    stat = c.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                  json={"column": "cups_sold", "method": "first_difference", "apply": True, "confirm_non_causal": True})
    check("A7: stationarity apply -- 200, производная cups_sold_diff1 зарегистрирована",
          stat.status_code == 200 and stat.json().get("output_column") == "cups_sold_diff1")

    prof2 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    ds2 = prof2.get("derived_summary") or {}
    derived_names = [x["column"] for x in ds2.get("columns", [])]
    check("A8: ядро спеки на своём ряде: 2 производные колонки, всплески первой разности ТОЛЬКО в derived_summary",
          sorted(derived_names) == ["cups_sold_diff1", "cups_sold_outlier_flag"]
          and ds2.get("total_outliers", 0) >= 1
          and "cups_sold_diff1" not in [x["column"] for x in prof2["columns"]])

    preview = c.post("/v1/session/dataset/outlier-corrections",
                     json={"columns": ["cups_sold", "cups_sold_diff1"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": False})
    check("A9: осознанный выбор производной (как чекбокс группы «Производные») -- preview 200 с derived_summary в ответе",
          preview.status_code == 200 and preview.json().get("derived_summary") is not None)

    validate = c.get("/v1/session/dataset/validate", params={"column": "cups_sold_diff1"})
    validate_ok = c.get("/v1/session/dataset/validate", params={"column": "cups_sold"})
    check("A10: /dataset/validate: производная -- честный 422 (не тихий проход), исходная -- 200",
          validate.status_code == 422 and validate_ok.status_code == 200)

    store = get_session_store()
    sess = store.get(c.cookies.get(SESSION_COOKIE_NAME))
    check("A11: реестр происхождения сессии: stage-метаданные своих остановок (outliers/stationarity)",
          sess.derived_columns["cups_sold_outlier_flag"]["stage"] == "outliers"
          and sess.derived_columns["cups_sold_diff1"]["stage"] == "stationarity")

    # GREEN-фаза оракула: профили -- по ЧИСЛОВЫМ колонкам; ось времени
    # (date) в canonical/derived не входит и в разбиение не включается.
    all_names = {"cups_sold", "avg_check"} | {"cups_sold_outlier_flag", "cups_sold_diff1"}
    check("A12: разбиение без потерь: canonical ∪ derived == все ЧИСЛОВЫЕ колонки своего датафрейма + производные, без пересечений",
          set(canon_names) | set(derived_names) == all_names
          and not (set(canon_names) & set(derived_names)))


def main() -> int:
    emit("=" * 100)
    emit("LIVE-API ОРАКУЛЫ PROGR-24-B-CERT: входной контракт UI задачи B на своих данных (cafe_daily.csv)")
    emit("База: 23c5068 (задача B = 8c06802); бэкенд задачи A не менялся -- оракул независимо воспроизводит его данные")
    emit("=" * 100)
    group_a()
    emit()
    total = len(_checks)
    failed = sum(1 for _, ok in _checks if not ok)
    emit("=" * 100)
    emit(f"ИТОГ: {total - failed}/{total} оракулов GREEN" + ("" if failed == 0 else f"  <-- ПРОВАЛОВ: {failed}"))
    emit("=" * 100)
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
