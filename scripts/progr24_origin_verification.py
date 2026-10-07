#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПРОТОКОЛ ВЕРИФИКАЦИИ задачи A спеки spec_status_original_series.md
(Task PROGR-24-ORIGIN-A): реестр происхождения колонок + каноническая
область гейтов качества + derived_summary (вне статуса).

Проверяемые контракты (спека §Реализация п.1-4):
  Р1 единая точка регистрации: хелпер сравнивает колонки до/после apply
     (не угадывает по суффиксу); вызывается во всех apply-эндпоинтах.
  Р2 каноническая область: гейты (пропуски/выбросы/регулярность/валидация)
     считают по canonical_columns(session) -- исходному ряду.
  Р3 derived_summary: профиль по производным колонкам считается отдельно и
     отдаётся вне статуса и вне свёртки.
  Р4 совместимость: старые сессии без реестра = все колонки исходные;
     версия схемы сессии растёт (2 -> 3).
  Р5 петля «+4 выброса от флаг-колонки» (PROGR-22-REPRO) исчезает по
     построению; класс C5 G345 устраняется ПРИЧИНОЙ (спека п.4): «окно
     лжи» закрывается причиной, трассировка PROGR-23 остаётся.

Сценарий: полный поток G345 на детерминированном аналоге
forecast_monitor_synthetic_n150 (тренд + сезон M=12, 4 выброса, 3 пропуска):
загрузка -> пропуски(interpolate) -> выбросы(cap) -> стационарность
(производная колонка) -> [карточка после производных всплесков] ->
частичная фиксация C5 -> финал. Плюс поток флаг-колонки (Р5).

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
    SESSION_SCHEMA_VERSION,
    get_session_store,
    reset_session_store_for_testing,
)
from fastapi.testclient import TestClient  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = REPO / "scripts" / "progr24_origin_verification.txt"

_lines: list[str] = []
_checks: list[tuple[str, bool]] = []


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def check(label: str, ok: bool) -> None:
    _checks.append((label, ok))
    emit(f"    [{'PASS' if ok else 'FAIL'}] {label}")


def g345_frame() -> pd.DataFrame:
    """Детерминированный аналог forecast_monitor_synthetic_n150.csv
    (генератор scripts/dataset_forecast_monitor.py, без шума): тренд +
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


def upload(c: TestClient, frame: pd.DataFrame) -> None:
    r = c.post(
        "/v1/internal/upload",
        files={"file": ("g345.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text


def session_obj(c: TestClient):
    return get_session_store().get(c.cookies.get(SESSION_COOKIE_NAME))


def card(c: TestClient, mark: str) -> dict:
    d = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    derived = d.get("derived_summary")
    emit(
        f"    {mark:58s} КАРТОЧКА: status={d['status']:8s} outliers={d['total_outliers']} "
        f"cols={d['total_numeric_columns']} | derived_summary="
        + (f"cols={derived['total_columns']} spikes={derived['total_outliers']}" if derived else "нет")
    )
    return d


def missing_card(c: TestClient, mark: str) -> dict:
    d = c.get("/v1/session/dataset/missing-profile").json()
    derived = d.get("derived_summary")
    emit(
        f"    {mark:58s} ПРОПУСКИ: status={d['status']:8s} missing={d['total_missing']} "
        f"cols={d['total_columns']} | derived_summary="
        + (f"cols={derived['total_columns']}" if derived else "нет")
    )
    return d


def trace_node(c: TestClient, mark: str) -> dict:
    nodes = {
        n["node_id"]: n
        for n in c.get("/v1/progress/trace").json().get("nodes", [])
        if n.get("stage") == "preprocessing"
    }
    node = nodes["outliers"]
    emit(
        f"    {mark:58s} TRACE outliers: status={node['status']:8s} count={node['summary_count']}"
    )
    return node


def fix_missing_and_outliers(c: TestClient) -> None:
    """Остановки «Пропуски» (interpolate) и «Выбросы» (cap iqr-1.5) --
    честный UI-поток до стационарности (гейт пропусков + зелёная карточка)."""
    missing = c.get("/v1/session/dataset/missing-profile").json()
    cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
    r = c.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": cols, "strategy": "interpolate", "apply": True},
    )
    assert r.status_code == 200, r.text
    card1 = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    r = c.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": card1["affected_columns"], "strategy": "cap",
              "method": "iqr", "param": 1.5, "apply": True},
    )
    assert r.status_code == 200, r.text


def stationarity_apply(c: TestClient) -> dict:
    profile = c.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
    method = profile["profile"].get("selected_method") or "first_difference"
    r = c.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        json={"column": "value", "method": method, "apply": True, "confirm_non_causal": True},
    )
    assert r.status_code == 200, r.text
    return r.json()


def main() -> int:
    reset_session_store_for_testing()
    client = TestClient(app)

    emit("=" * 100)
    emit("ПРОТОКОЛ ВЕРИФИКАЦИИ PROGR-24-ORIGIN-A (spec_status_original_series.md, задача A)")
    emit(f"База: b6d4a03; SESSION_SCHEMA_VERSION = {SESSION_SCHEMA_VERSION} (спека п.3: версия растёт)")
    emit("=" * 100)

    # ── Поток 1: полный G345 ─────────────────────────────────────────
    emit("\n── Поток 1: полный G345 (загрузка -> пропуски -> выбросы -> стационарность) ──")
    upload(client, g345_frame())
    client.post("/v1/session/date-column", json={"column": "date"})
    card0 = card(client, "после загрузки")
    check("Р2: карточка по исходному ряду видит 4 выброса value", card0["total_outliers"] == 4)
    check("Р4: derived_summary отсутствует без производных колонок", card0.get("derived_summary") is None)

    fix_missing_and_outliers(client)
    card1 = card(client, "после пропуски+выбросы (исходный ряд чист)")
    check("Р2: карточка зелёная на чистом исходном ряду", card1["status"] == "done")

    st = stationarity_apply(client)
    derived_col = st["output_column"]
    emit(f"    стационарность apply: output_column={derived_col!r}")
    registry = session_obj(client).derived_columns
    entry = registry.get(derived_col, {})
    emit(f"    реестр derived_columns: {{{derived_col!r}: stage={entry.get('stage')!r}, source={entry.get('source')!r}}}")
    check(
        "Р1: единая точка регистрации записала {stage, source, created_at}",
        entry.get("stage") == "stationarity"
        and bool(entry.get("source"))
        and bool(entry.get("created_at")),
    )

    card2 = card(client, "после стационарности (производная с 4 всплесками)")
    check(
        "Р2/Р3: всплески производной НЕ прибавились к карточке (4, а не 8); карточка зелёная",
        card2["status"] == "done" and card2["total_outliers"] == 0,
    )
    check(
        "Р3: derived_summary честно несёт 4 всплеска производной колонки",
        (card2.get("derived_summary") or {}).get("total_outliers") == 4,
    )
    node2 = trace_node(client, "после стационарности")
    check(
        "Р5 (спека п.4): card == trace на зелёной карточке -- окно лжи закрыто ПРИЧИНОЙ",
        node2["status"] == card2["status"] == "done" and node2["summary_count"] == 0,
    )

    emit("\n    ── Класс C5: частичная фиксация (производная колонка снята с чекбокса) ──")
    apply2 = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
    ).json()
    emit(
        f"    apply2 мастера: found={apply2['total_outliers']} changed={apply2['total_changed']} "
        f"| карточная шкала: status={apply2['status']} after={apply2['total_outliers_after']}"
    )
    check(
        "Р5: класс C5 устранён по причине -- карточная шкала apply: done/0 (было warning/4 навсегда)",
        apply2["status"] == "done" and apply2["total_outliers_after"] == 0,
    )
    check(
        "Р3: derived_summary в ответе apply сохраняет 4 всплеска производной (информационно)",
        (apply2.get("derived_summary") or {}).get("total_outliers") == 4,
    )
    card3 = card(client, "финал G345")
    node3 = trace_node(client, "финал G345")
    check(
        "Р5: финал card == trace (оба зелёные), бейдж 0 -- расхождение G345 невоспроизводимо",
        card3["status"] == node3["status"] == "done" and node3["summary_count"] == 0,
    )

    # ── Поток 2: петля флаг-колонки ──────────────────────────────────
    emit("\n── Поток 2: Р5 -- петля «+4 выброса от флаг-колонки» (PROGR-22-REPRO) ──")
    reset_session_store_for_testing()
    client2 = TestClient(app)
    upload(client2, g345_frame())
    before = client2.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    emit(f"    до flag-apply: карточка outliers={before['total_outliers']} cols={before['total_numeric_columns']}")
    r = client2.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": True},
    )
    assert r.status_code == 200, r.text
    flag_column = r.json()["added_columns"][0]
    emit(f"    flag-apply: добавлена колонка {flag_column!r}")
    after = client2.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    after_cols = [item["column"] for item in after["columns"]]
    check(
        "Р5: флаг-колонка исключена из карточки ПО ПОСТРОЕНИЮ (реестр, не суффикс)",
        flag_column not in after_cols
        and after["total_numeric_columns"] == 1
        and after["total_outliers"] == 4,
    )
    reg = session_obj(client2).derived_columns.get(flag_column, {})
    check(
        "Р1: флаг-колонка зарегистрирована как производная остановки «Выбросы»",
        reg.get("stage") == "outliers",
    )
    check(
        "Р3: деградировавший IQR флаг-колонки виден ТОЛЬКО в derived_summary (4 всплеска)",
        (after.get("derived_summary") or {}).get("total_outliers") == 4,
    )

    # ── Поток 3: совместимость и область валидации ───────────────────
    emit("\n── Поток 3: Р4 совместимость + область «Валидации» ──")
    reset_session_store_for_testing()
    client3 = TestClient(app)
    upload(client3, g345_frame())
    fix_missing_and_outliers(client3)
    stationarity_apply(client3)
    derived_name = session_obj(client3).derived_columns
    derived_col3 = next(iter(derived_name))
    r422 = client3.get("/v1/session/dataset/validate", params={"column": derived_col3})
    emit(f"    GET /validate?column={derived_col3!r} -> {r422.status_code}: {r422.json().get('detail', '')[:90]}")
    check(
        "Р2: явная per-column проверка производной колонки -- честная 422 (методологический guard)",
        r422.status_code == 422,
    )
    r200 = client3.get("/v1/session/dataset/validate", params={"column": "value"})
    check("Р2: явная per-column проверка исходной колонки работает", r200.status_code == 200)
    reg_card = client3.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    check(
        "Р2: «Регулярность» применима по канонической области (дата-ось исходного ряда)",
        reg_card["profile"]["applicable"] is True,
    )
    legacy = {
        "session_id": "legacy-check",
        "dataframe_json": pd.DataFrame({"a": [1.0]}).to_json(orient="split"),
        "stages": {},
    }
    from apps.api.session_store import session_from_dict

    restored = session_from_dict(legacy)
    check(
        "Р4: старая Redis-сессия без реестра читается -- все колонки исходные",
        restored.derived_columns == {},
    )

    emit("\n" + "=" * 100)
    total = len(_checks)
    failed = [label for label, ok in _checks if not ok]
    emit(f"ИТОГ: {total - len(failed)}/{total} контрактов выполнено")
    for label, ok in _checks:
        emit(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    emit("=" * 100)
    emit("Правила AGENTS.md соблюдены: измерение на локальном дереве, commit/push НЕ выполнялись.")

    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"\nПротокол сохранён: {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
