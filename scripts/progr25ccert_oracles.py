#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ задачи C (spec_progress_target_column.md,
PROGR-25-C) -- аудит PROGR-25-C-CERT.

Принципы (прецеденты PROGR-25-A-CERT / PROGR-25-B-CERT):
  - данные СВОИ, не пересекаются ни с данными разработчика (date/value,
    sales/profit), ни с датасетом сертификации A (ts/load/price/temp):
    pressure_hourly.csv (ts/pressure, 96 точек, seeded) и
    pressure_demand.csv (ts/pressure/demand); юнит-колонки
    pressure/demand/air_temp; ловит хардкод «value» в любом звене;
  - оракулы НЕ копируют ассерты test_progress_progr25c.py /
    TestPhaseTextUploadOrigin / TestProgr25CStageLevelReasonOrigin,
    а атакуют с других углов: ПОЛНОЕ равенство шаблона (не substring),
    цепочки last-wins из 2+ событий, dict-событие с payload=None
    (деградация без падения), факт подстановки из payload при смене
    колонок, честная просьба о структуре при auto-факте, сброс,
    трёхисточность (/current ↔ слой 1 ↔ слой 2), идемпотентность чтений.

Группы (22 именованных):
  M (7) -- Наставник end-to-end на живом API, свои датасеты
           (M4 включает last-wins user→auto через API: reason слоя 1
           + зеркало нового run по канону R3);
  R (2) -- reason узла (validation, sufficiency) через /trace;
  U (8) -- юнит-оракулы phase_text / derive_pipeline_node_states
           (U7 -- пин документированной границы (3) PROGR-25-C:
           унаследованная семантика last-non-empty при сброс-событии);
  S (5) -- статические/структурные пины (реестр, whitelist, зеркало).

Классификация для RED-репро (pre-registered):
  KILLER -- обязан падать на коде ДО задачи C (4cd8534);
  GUARD  -- обязан оставаться зелёным на коде ДО задачи C (честный RED,
            при мутациях становятся убийцами).

Выход: scripts/progr25ccert_oracles.txt; exit 0 == все PASS.
Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

logging.disable(logging.WARNING)
os.environ.setdefault("CISSTAT_RUNS_BACKEND", "memory")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import mentor_rules  # noqa: E402
from app.core.mentor_rules import phase_text  # noqa: E402
from app.core.node_status import derive_pipeline_node_states  # noqa: E402
from apps.api import research_runs  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event  # noqa: E402

OUT = REPO / "scripts" / "progr25ccert_oracles.txt"

# Точный авто-текст спеки §4-C (имя колонки -- факт из payload события).
AUTO_TEXT = (
    "Исследование на этапе «Загрузка»: исследуемый признак выбран "
    "автоматически: {col} -- проверки качества ждут на этапе «Валидация»."
)

_lines: list[str] = []
_checks: list[tuple[str, bool]] = []

# Pre-registered RED-классификация (см. docstring; акт §4).
EXPECTED_RED: dict[str, str] = {
    "M1": "kill", "M2": "kill", "M3": "kill", "M4": "kill",
    "M5": "guard", "M6": "kill", "M7": "kill",
    "R1": "kill", "R2": "guard",
    "U1": "kill", "U2a": "guard", "U2b": "kill", "U3": "kill",
    "U4": "kill", "U5": "guard", "U6": "kill", "U7": "kill",
    "S1": "kill", "S2": "kill", "S3": "kill", "S4": "kill", "S5": "kill",
}


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def check(label: str, ok: bool, note: str = "") -> None:
    _checks.append((label, bool(ok)))
    emit(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {note}" if note else ""))


def _csv_one() -> bytes:
    """СВОЙ датасет v1: pressure_hourly.csv, 96 часовых точек,
    колонки ts (ISO) / pressure (гПа; суточный цикл + шум, seeded).
    Единственная числовая -- кандидаты ровно один."""
    rng = np.random.default_rng(20261009)
    n = 96
    ts = pd.date_range("2026-09-01 00:00", periods=n, freq="h")
    base = 1013.0 + 0.8 * np.sin(np.arange(n) * 2 * np.pi / 24) + rng.normal(0, 0.3, n)
    df = pd.DataFrame(
        {"ts": ts.strftime("%Y-%m-%dT%H:%M:%S"), "pressure": np.round(base, 2)}
    )
    return df.to_csv(index=False).encode("utf-8")


def _csv_two() -> bytes:
    """СВОЙ датасет v2: pressure_demand.csv -- ДВЕ числовые
    (pressure, demand): честная неоднозначность."""
    rng = np.random.default_rng(20261010)
    n = 96
    ts = pd.date_range("2026-09-01 00:00", periods=n, freq="h")
    pressure = 1013.0 + 0.8 * np.sin(np.arange(n) * 2 * np.pi / 24) + rng.normal(0, 0.3, n)
    demand = 40.0 + 12.0 * np.sin(np.arange(n) * 2 * np.pi / 24) + rng.normal(0, 1.5, n)
    df = pd.DataFrame(
        {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "pressure": np.round(pressure, 2),
            "demand": np.round(demand, 2),
        }
    )
    return df.to_csv(index=False).encode("utf-8")


client = TestClient(app)


def _fresh_stores() -> None:
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


def _upload(name: str, blob: bytes) -> None:
    resp = client.post(
        "/v1/internal/upload", files={"file": (name, io.BytesIO(blob), "text/csv")}
    )
    assert resp.status_code == 200, resp.text


def _confirm_structure(column: str = "ts") -> None:
    resp = client.post("/v1/session/date-column", json={"column": column})
    assert resp.status_code == 200, resp.text


def _run_id() -> str:
    data = client.get("/v1/progress/trace").json()
    run_id = data.get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _mentor_text() -> str:
    resp = client.get(f"/v1/progress/runs/{_run_id()}/mentor/next-step")
    assert resp.status_code == 200, resp.text
    return resp.json()["phase_text"]


def _layer2_events(run_id: str) -> list[dict]:
    store = research_runs.get_research_run_store()
    return [e.to_dict() for e in store.list_events(run_id)]


def _sufficiency_reason() -> str | None:
    data = client.get("/v1/progress/trace").json()
    nodes = [
        n for n in data.get("nodes", [])
        if n.get("stage") == "validation" and n.get("node_id") == "sufficiency"
    ]
    assert nodes, "узел validation/sufficiency отсутствует в /trace"
    return nodes[0].get("status_reason")


# ══ Группа M: Наставник end-to-end на живом API ═══════════════════════


def phase_m() -> None:
    emit("── Группа M: Наставник end-to-end (живой API, свои датасеты)")
    # Фаза 1: свой однозначный датасет
    _fresh_stores()
    _upload("pressure_hourly.csv", _csv_one())
    _confirm_structure("ts")

    text = _mentor_text()
    check("M1", text == AUTO_TEXT.format(col="pressure"),
          "фаза upload, полное равенство авто-текста с колонкой pressure; "
          f"last_active_stage==upload (событие stage=validation фазу не двигает); "
          f"фактический текст: {text[:90]!r}")

    events = _layer2_events(_run_id())
    fixed = [e for e in events if e["event_type"] == "target_column_changed"]
    types = [e["event_type"] for e in events]
    ok_m2 = (
        len(fixed) == 1
        and fixed[0]["payload"] == {"target_column": "pressure", "source": "auto"}
        and fixed[0]["stage"] == "validation"
        and fixed[0]["node_id"] is None
        and "upload_completed" in types
        and types.index("target_column_changed") < types.index("upload_completed")
    )
    check("M2", ok_m2, "зеркало слоя 2: ровно одно событие, payload канона A, "
                       "хронология R3 (фиксация раньше upload_completed)")

    run = research_runs.get_research_run_store().get_run(_run_id())
    check("M3", run is not None and run.target_column == "pressure",
          "run.target_column заполнен из payload (restore-хилинг)")

    current = client.get("/v1/session/current").json()
    trace = client.get("/v1/progress/trace").json()
    ok_m6 = (
        current.get("target_column") == "pressure"
        and current.get("target_column_source") == "auto"
        and trace.get("target_column") == "pressure"
        and trace.get("target_column_source") == "auto"
        and len(fixed) == 1
        and fixed[0]["payload"]["target_column"] == "pressure"
    )
    check("M6", ok_m6, "трёхисточность: /current ↔ /trace (слой 1) ↔ слой 2 "
                       "сходятся на pressure/auto")

    text2 = _mentor_text()
    _ = client.get("/v1/progress/trace").json()
    events2 = _layer2_events(_run_id())
    fixed2 = [e for e in events2 if e["event_type"] == "target_column_changed"]
    check("M7", text2 == AUTO_TEXT.format(col="pressure") and len(fixed2) == 1,
          "идемпотентность чтений: повторные next-step//trace не плодят "
          "событий зеркала и меняют текст")

    # Фаза 2: свой неоднозначный датасет + last-wins user→auto через API
    # (канон R3: каждый upload -- НОВЫЙ run; сквозной last-wins user→auto
    # наблюдаем в слое 1 через reason, а авто-текст Наставника нового run --
    # после честного повторного подтверждения структуры)
    _fresh_stores()
    _upload("pressure_demand.csv", _csv_two())
    _confirm_structure("ts")
    text_req = _mentor_text()
    honest_request = (
        "Подтвердите целевой признак" in text_req and "автоматически" not in text_req
    )
    resp = client.post("/v1/session/target-column", json={"column": "demand"})
    manual_ok = resp.status_code == 200 and resp.json().get("target_column_source") == "user"
    text_user = _mentor_text()
    _upload("pressure_hourly.csv", _csv_one())  # re-upload: единственная числовая → auto ПОСЛЕ user
    reason_auto = _sufficiency_reason()  # слой 1: user(demand) → auto(pressure), last-wins
    run2 = _run_id()
    events3 = _layer2_events(run2)
    fixed3 = [e for e in events3 if e["event_type"] == "target_column_changed"]
    chronology_ok = (
        len(fixed3) == 1
        and fixed3[0]["payload"].get("source") == "auto"
        and fixed3[0]["payload"].get("target_column") == "pressure"
        and "upload_completed" in [e["event_type"] for e in events3]
        and [e["event_type"] for e in events3].index("target_column_changed")
        < [e["event_type"] for e in events3].index("upload_completed")
    )
    _confirm_structure("ts")  # новый датасет -- структура честно pending, подтверждаем заново
    text_auto = _mentor_text()
    ok_m4 = (
        honest_request
        and manual_ok
        and "структура данных подтверждена, целевой признак выбран" in text_user
        and "автоматически" not in text_user
        and reason_auto == "Целевой признак: pressure (авто)"
        and chronology_ok
        and text_auto == AUTO_TEXT.format(col="pressure")
    )
    check("M4", ok_m4, "last-wins через живой API: честная просьба при двух "
                       "числовых → user demand → re-upload v1 → новый run: auto-зеркало "
                       "раньше upload_completed (R3), reason слоя 1 -- «(авто)» "
                       "(user→auto), после переподтверждения структуры -- авто-текст")

    # Фаза 3: demo-guard на свежих хранилищах
    _fresh_stores()
    resp = client.post("/v1/session/demo")
    demo_ok = resp.status_code == 200
    no_target = client.get("/v1/session/current").json().get("target_column") is None
    events4 = _layer2_events(_run_id())
    no_mirror = not [e for e in events4 if e["event_type"] == "target_column_changed"]
    text_demo = _mentor_text()
    check("M5", demo_ok and no_target and no_mirror
          and "подтвердите" in text_demo.lower() and "автоматически" not in text_demo.lower(),
          "demo-guard: встроенный sales_demo.csv (две числовые) -- фиксации/зеркала "
          "нет ни в одном слое, Наставник честно просит")


# ══ Группа R: reason узла через /trace ════════════════════════════════


def phase_r() -> None:
    emit("── Группа R: reason (validation, sufficiency) через /trace")
    # R1/R2 исполняются в фазах M (свои датасеты); здесь -- повторное
    # чтение на фазе 1 не нужно, поэтому отдельные мини-фазы:
    _fresh_stores()
    _upload("pressure_hourly.csv", _csv_one())
    reason = _sufficiency_reason()
    node = next(
        n for n in client.get("/v1/progress/trace").json()["nodes"]
        if n["stage"] == "validation" and n["node_id"] == "sufficiency"
    )
    check("R1", reason == "Целевой признак: pressure (авто)" and node["status"] == "pending",
          f"auto → пометка, статус узла не тронут (N-2); факт: {reason!r}")

    _fresh_stores()
    _upload("pressure_demand.csv", _csv_two())
    resp = client.post("/v1/session/target-column", json={"column": "pressure"})
    assert resp.status_code == 200, resp.text
    reason_user = _sufficiency_reason()
    check("R2", reason_user == "Целевой признак: pressure",
          f"user → прежний текст без пометки (регресс PROGR-21); факт: {reason_user!r}")


# ══ Группа U: юнит-оракулы с других углов ═════════════════════════════

_STRUCT_DONE = {"upload/structure": "done"}


def _ev(run_id: str, column: str, source: str, seconds: int) -> dict:
    """Канонический dict события §4.1 (минимальный корпус движка, паттерн
    test_node_status_engine._event): свои run_id/колонки/хронология."""
    return {
        "ts": f"2026-10-09T10:{seconds // 60:02d}:{seconds % 60:02d}+00:00",
        "stage": "validation",
        "node_id": None,
        "event_type": "target_column_changed",
        "payload": {"target_column": column, "source": source},
    }


def _engine_reason(events: list[dict]) -> str | None:
    node = next(
        s for s in derive_pipeline_node_states(events)
        if s["stage"] == "validation" and s["node_id"] == "sufficiency"
    )
    return node["status_reason"]


def phase_u() -> None:
    emit("── Группа U: юнит-оракулы phase_text / движка reason")
    t1 = phase_text("upload", _STRUCT_DONE, [_ev("RUN-CERTC001", "air_temp", "auto", 1)])
    t2 = phase_text("upload", _STRUCT_DONE, [_ev("RUN-CERTC001", "demand", "auto", 2)])
    check("U1", t1 == AUTO_TEXT.format(col="air_temp")
          and t2 == AUTO_TEXT.format(col="demand") and t1 != t2,
          "точное равенство шаблона; факт берётся из payload -- тот же "
          "шаблон, разные колонки, разные тексты (ловит хардкод value)")

    t_end_user = phase_text(
        "upload", _STRUCT_DONE,
        [_ev("RUN-CERTC002", "pressure", "auto", 1), _ev("RUN-CERTC002", "demand", "user", 2)],
    )
    check("U2a", "структура данных подтверждена, целевой признак выбран" in t_end_user
          and "автоматически" not in t_end_user,
          "guard: цепочка auto→user -- прежний BOTH-текст")

    t_end_auto = phase_text(
        "upload", _STRUCT_DONE,
        [_ev("RUN-CERTC003", "demand", "user", 1), _ev("RUN-CERTC003", "pressure", "auto", 2)],
    )
    check("U2b", t_end_auto == AUTO_TEXT.format(col="pressure"),
          "цепочка user→auto -- авто-текст с колонкой pressure")

    junk = ["мусор", 42, None, {}, [1, 2]]
    t_junk = phase_text(
        "upload", _STRUCT_DONE,
        junk + [_ev("RUN-CERTC004", "pressure", "auto", 3)],
    )
    check("U3", t_junk == AUTO_TEXT.format(col="pressure"),
          "мусор-толерантность: строка/число/None/пустой dict/список -- "
          "деградация «событие мимо фактов», правило живо")

    dead_payload = {
        "ts": "2026-10-09T10:00:00+00:00", "stage": "validation",
        "node_id": None, "event_type": "target_column_changed", "payload": None,
    }
    t_dead_left = phase_text("upload", _STRUCT_DONE, [dead_payload, _ev("RUN-CERTC005", "pressure", "auto", 4)])
    t_dead_right = phase_text("upload", _STRUCT_DONE, [_ev("RUN-CERTC005", "pressure", "auto", 4), dead_payload])
    check("U4", t_dead_left == AUTO_TEXT.format(col="pressure")
          and t_dead_right == AUTO_TEXT.format(col="pressure"),
          "dict-событие с payload=None -- пропуск без падения, в любом "
          "порядке относительно реального факта")

    t_struct_pending = phase_text("upload", {}, [_ev("RUN-CERTC006", "pressure", "auto", 5)])
    check("U5", "подтвердите структуру" in t_struct_pending.lower()
          and "подтвердите целевой" not in t_struct_pending.lower()
          and "автоматически" not in t_struct_pending.lower(),
          "guard: auto-факт при структуре pending НЕ даёт авто-текста -- "
          "честная просьба о структуре (правило требует структуру)")

    t_fact = phase_text("upload", _STRUCT_DONE, [_ev("RUN-CERTC007", "air_temp", "auto", 6)])
    check("U6", "air_temp" in t_fact and "pressure" not in t_fact
          and "target_column" not in t_fact,
          "факт подстановки из payload, не из сводки (сводка без "
          "target_column); имя в тексте -- имя из события")

    reason_reset = _engine_reason(
        [
            _ev("RUN-CERTC008", "pressure", "auto", 1),
            {"ts": "2026-10-09T10:00:01+00:00", "stage": "validation",
             "node_id": None, "event_type": "target_column_changed",
             "payload": {"target_column": ""}},
        ]
    )
    t_reset = phase_text("upload", _STRUCT_DONE,
                         [_ev("RUN-CERTC008", "pressure", "auto", 1),
                          {"ts": "2026-10-09T10:00:01+00:00", "stage": "validation",
                           "node_id": None, "event_type": "target_column_changed",
                           "payload": {"target_column": ""}}])
    check("U7", reason_reset is None
          and t_reset == AUTO_TEXT.format(col="pressure"),
          "граница (3) PROGR-25-C, пин унаследованной семантики last-non-empty: "
          "reason сброс-событием снимается (PROGR-21), текст Наставника держится "
          "на последнем НЕПУСТОМ выборе (auto) -- через API пустой target "
          "недостижим (POST 422); пин защищает семантику от тихой смены")


# ══ Группа S: статические/структурные пины ════════════════════════════


def phase_s() -> None:
    emit("── Группа S: статические/структурные пины")
    auto_cond = getattr(mentor_rules, "_upload_structure_and_target_auto", None)
    both_cond = getattr(mentor_rules, "_upload_structure_and_target_done", None)
    rules = mentor_rules.STAGE_PHASE_TEXT_RULES.get("upload", ())
    conds = [r.condition for r in rules]
    ok_s1 = (
        auto_cond is not None
        and both_cond is not None
        and conds
        and conds[0] is auto_cond
        and auto_cond in conds
        and both_cond in conds
        and conds.index(auto_cond) < conds.index(both_cond)
        and "выбран автоматически" in rules[conds.index(auto_cond)].template
        and "{target_column}" in rules[conds.index(auto_cond)].template
    )
    check("S1", ok_s1, "реестр upload: правило auto ПЕРВЫМ и ПЕРЕД общим "
                       "both-правилом; шаблон называет факт {target_column}")

    fields = getattr(mentor_rules, "_PHASE_TEMPLATE_FIELDS", frozenset())
    check("S2", "target_column" in fields and "nodes" not in fields,
          "whitelist шаблонов: факт разрешён, nodes запрещён (канон PROGR-19)")

    src = (REPO / "apps" / "api" / "target_column_rule.py").read_text(encoding="utf-8")
    i_append = src.find("session.append_trace_event(event)")
    i_mirror = src.find("record_run_event(session, event)")
    check("S3", i_append != -1 and i_mirror != -1 and i_mirror > i_append,
          "зеркало слоя 2: record_run_event вызывается после посева слоя 1 "
          "в auto_fix_and_seed")

    ns_src = (REPO / "app" / "core" / "node_status.py").read_text(encoding="utf-8")
    check("S4", 'mark = " (авто)" if source == "auto" else ""' in ns_src,
          "гейт честности reason: пометка только по факту source==auto")

    check("S5", getattr(mentor_rules, "_TARGET_SOURCE_AUTO", None) == "auto",
          "литерал канона A в app/core (листовой модуль, без импорта из api)")


# ══ Итог ══════════════════════════════════════════════════════════════


def main() -> int:
    emit("=" * 100)
    emit("ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ PROGR-25-C-CERT -- задача C "
         "(spec_progress_target_column.md §4-C)")
    emit("Свои данные: pressure_hourly.csv / pressure_demand.csv (96 точек, "
         "seeded), юнит-колонки pressure/demand/air_temp")
    emit("=" * 100)
    phase_m()
    phase_r()
    phase_u()
    phase_s()
    passed = sum(1 for _, ok in _checks if ok)
    failed = [label for label, ok in _checks if not ok]
    emit("")
    emit("=" * 100)
    emit(f"ИТОГ ОРАКУЛОВ: {passed}/{len(_checks)} PASS")
    if failed:
        emit(f"FAIL: {failed}")
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"Протокол: {OUT}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
