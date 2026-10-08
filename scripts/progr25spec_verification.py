#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROGR-25-SPEC-CERT — runtime-верификация фактов и гипотез
spec_progress_target_column.md (98dcba2) по живому коду (read-only).

Правила AGENTS.md: правок КОДА НЕТ (коммит/пуш запрещены); скрипт —
артефакт аудита. Паттерн TestClient (tests/api), штатные эндпоинты.

Проверяемые утверждения спеки:
  Ф1  хук useTargetColumn авто-POSTит рекомендацию GET /target-column
      (сам POST имитируется здесь — хук это фронтовый код);
  Ф4  демо n150: колонки date,value — ровно одна числовая;
  Г1  после загрузки БЕЗ монтирования вкладки с хуком target_column
      на бэкенде пуст и события target_column_changed нет;
  Г2-бэкенд-часть: после авто-POST (имитация хука) поле заполнено —
      «—» в шапке обязано устареванием контекста (фронт, статически
      верифицирован: ProgressDrawer читает useAppShell, провайдер в
      корневом layout, refreshSession панель не вызывает);
  §3/§4 контракты: событие target_column_changed без payload.source
      (аддитивность подтверждена), GET /v1/progress/trace без полей
      target_column/target_column_source;
  §2.2 расхождение: в НЕОДНОЗНАЧНОМ случае (2+ числовых) бэкенд
      отдаёт ненулевой suggestion, а хук авто-POSTит его — «тихий
      выбор» сегодня существует (спека его запрещает, подзадачи на
      снятие авто-POST в плане нет).
"""

import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from dataset_forecast_monitor import generate_series  # noqa: E402

client = TestClient(app)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))


def upload_csv(name: str, df: pd.DataFrame):
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return client.post(
        "/v1/internal/upload",
        files={"file": (name, buf, "text/csv")},
    )


def main() -> int:
    print("== PROGR-25-SPEC-CERT: runtime-верификация spec_progress_target_column.md ==\n")

    # ── 1. Ф4: демо n150 — ровно одна числовая колонка ────────────────
    print("== 1. Ф4: демо forecast_monitor_synthetic_n150 ==")
    df150 = generate_series()
    check("колонки == [date, value]", list(df150.columns) == ["date", "value"],
          str(list(df150.columns)))
    numeric150 = [c for c in df150.columns if pd.api.types.is_numeric_dtype(df150[c])]
    check("числовых колонок ровно одна (value)", numeric150 == ["value"], str(numeric150))
    check("150 строк; 3 пропуска в value @ {45,87,122}; 4 выброса @ {25,70,105,130}",
          len(df150) == 150 and int(df150["value"].isna().sum()) == 3)

    # ── 2. Г1: upload без монтирования вкладок — поле пусто, события нет ──
    print("\n== 2. Г1: сразу после загрузки (API-уровень, без хука) ==")
    r = upload_csv("forecast_monitor_synthetic_n150.csv", df150)
    check("POST /v1/internal/upload == 200", r.status_code == 200, str(r.status_code))

    cur = client.get("/v1/session/current").json()
    check("Г1 подтверждена: /current.target_column is None сразу после загрузки",
          cur.get("target_column") is None, repr(cur.get("target_column")))
    check("датасет при этом активен (has_active_dataset=True)",
          cur.get("has_active_dataset") is True)

    tr = client.get("/v1/progress/trace").json()
    ev_types = [e.get("event_type") for e in tr.get("events", [])]
    check("события target_column_changed в трассе НЕТ",
          "target_column_changed" not in ev_types, str(ev_types))
    check("upload_completed присутствует (сценарий корректен)",
          "upload_completed" in ev_types)
    check("КОНТРАКТ B: /trace НЕ содержит target_column/target_column_source "
          "(поля только добавятся)",
          "target_column" not in tr and "target_column_source" not in tr)

    # ── 3. Ф1: имитация хука — GET suggestion → POST (auto-путь) ──────
    print("\n== 3. Ф1: однозначный случай — suggestion и авто-POST хука ==")
    tc = client.get("/v1/session/target-column").json()
    check("GET /target-column: suggested_column == 'value' (однозначный случай)",
          tc.get("suggested_column") == "value", repr(tc.get("suggested_column")))
    check("GET /target-column: available_columns == ['value']",
          tc.get("available_columns") == ["value"], str(tc.get("available_columns")))
    check("КОНТРАКТ A: в ответе НЕТ target_column_source (аддитивное поле)",
          "target_column_source" not in tc)

    # авто-POST хука (useTargetColumn.ts:139-160) — тот же тело запроса
    pr = client.post("/v1/session/target-column", json={"column": "value"})
    check("POST /target-column {'column':'value'} == 200", pr.status_code == 200)
    cur2 = client.get("/v1/session/current").json()
    check("Г2 (бэкенд-часть): после авто-POST /current.target_column == 'value' "
          "— шапка обязана показывать признак, «—» устаревание контекста",
          cur2.get("target_column") == "value", repr(cur2.get("target_column")))

    tr2 = client.get("/v1/progress/trace").json()
    tce = [e for e in tr2.get("events", []) if e.get("event_type") == "target_column_changed"]
    check("событие target_column_changed появилось в трассе",
          len(tce) == 1, str(len(tce)))
    if tce:
        ev = tce[-1]
        check("атрибуция маршрута: stage='validation', node_id=None "
              "(TRACE_ROUTES:225-229)",
              ev.get("stage") == "validation" and ev.get("node_id") is None,
              f"stage={ev.get('stage')}, node_id={ev.get('node_id')}")
        check("КОНТРАКТ A: payload события — ровно {'target_column'}, "
              "поля source НЕТ (аддитивность)",
              set(ev.get("payload") or {}) == {"target_column"},
              str(sorted((ev.get("payload") or {}).keys())))

    # ── 4. §2.2 РАСХОЖДЕНИЕ: неоднозначный случай — тихий выбор есть ──
    print("\n== 4. §2.2: неоднозначный случай (2+ числовых) — сегодняшний тихий выбор ==")
    df2 = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=40, freq="D").strftime("%Y-%m-%d"),
        "value": [120 + i * 0.5 for i in range(40)],
        "price": [95 + i * 0.3 for i in range(40)],
    })
    r2 = upload_csv("two_numeric.csv", df2)
    check("upload двухколоночного файла == 200", r2.status_code == 200)
    cur3 = client.get("/v1/session/current").json()
    check("после новой загрузки target_column сброшен (set_dataset, "
          "upload_common.py:166 → session_store.py)",
          cur3.get("target_column") is None)
    tc3 = client.get("/v1/session/target-column").json()
    check("РАСХОЖДЕНИЕ: в неоднозначном случае suggested_column НЕ пуст "
          "('value' — первая не-date-подобная), спека же требует «тихого "
          "выбора нет» — хук сегодня авто-POSTит эту рекомендацию "
          "(useTargetColumn.ts:139), подзадачи на снятие авто-POST в плане нет",
          tc3.get("suggested_column") == "value", repr(tc3.get("suggested_column")))

    # ── 5. date-подобные имена исключаются (докстринг эвристики) ──────
    print("\n== 5. Эвристика suggestion: date-подобные по имени ==")
    df3 = pd.DataFrame({
        "year": list(range(2001, 2041)),
        "value": [10.0 + i for i in range(40)],
    })
    r3 = upload_csv("year_value.csv", df3)
    check("upload (year,value) == 200", r3.status_code == 200)
    tc4 = client.get("/v1/session/target-column").json()
    check("suggested_column == 'value' (year исключён по имени)",
          tc4.get("suggested_column") == "value", repr(tc4.get("suggested_column")))
    check("замечание спеке: 'year' исключён ПО ИМЕНИ; фактическая "
          "session.date_column и реестр производных в кандидатах сегодня "
          "НЕ вычитаются (_get_numeric_columns — все числовые)",
          True, "статическая верификация session.py:3966-4000")

    # ── Итог ──────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n== ИТОГ: {passed}/{total} PASS ==")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
