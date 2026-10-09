#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сертификация PROGR-25-D-CERT: оракулы аудитора на СВОИХ данных.

Объект аудита -- тестовая поставка задачи D (коммит 6873227 поверх a55caed):
сквозной интеграционный сценарий (tests/integration, ПЕРВЫЙ файл директории),
repo-пины находок сертификаций (TM-11/TM-12/TM-15, TB-8) и мутационная
матрица M1-M5. Задача D продовых файлов НЕ меняет (проверено diff-ом
a55caed..6873227: только НОВЫЕ тестовые/скриптовые файлы + worklog9), поэтому
оракулы аудитора независимо проверяют ТЕ ЖЕ контракты D на СВОИХ данных --
полностью независимо от repo-тестов задачи (свои датасеты, свои колонки,
свои строки фронт-оракула).

СВОИ данные (никакого копирования repo-тестов -- иные имена, форма, seed):
  rain_hourly.csv   -- timestamp,rain, 96 часовых точек, seed 20261009
                       (≠ date/value разработчика, ≠ ts/load A-CERT, ≠ t/load D-пина)
  rain_multi.csv    -- timestamp,rain,snow,humidity -- 3 числовых (неоднозначность)
  demo_rain_single  -- date,rain  (подмена DEMO_DATASET_PATH, 3 строки)
  demo_rain_two     -- date,rain,snow
  юнит-фреймы       -- hour_index/snow (дата-факт), rain/pressure_detrended,
                       rain/snow_detrended (реестр решает, не имя)

Группы:
  G (3)  -- детерминизм и спецификация генератора n150 (Ф4: 3 пропуска
            @{45,87,122}, 4 выброса @{25,70,105,130}; проверка ПРОТИВ
            документированной базовой линии, не против кода генератора);
  E (8)  -- сквозной сценарий на rain_hourly: /current → селектор → /trace
            (канон payload, stage/node_id/actor, run_id общий, хронология
            R3 в ОБОИХ слоях) → трёхисточность;
  M (3)  -- Наставник на своих данных: авто-текст без просьбы; просьба при
            неоднозначности + рекомендация не фиксируется; user-ветка
            (BOTH-текст, legacy-payload ручного события);
  D (2)  -- demo-точка правила (подмена DEMO_DAT_PATH СВОИМИ файлами):
            одночисловой фиксирует (auto), двухчисловой -- честно нет;
  C (3)  -- носители/контракты: свежая сессия честно пуста; TRACE_ROUTES
            payload_keys ручного маршрута; схема ProgressTraceResponse;
  U (4)  -- вычеты правила на своих колонках: дата-факт (hour_index),
            реестр (pressure_detrended), производноподобное имя вне реестра.

Протокол: scripts/progr25dcert_oracles.txt. Exit 0 -- все PASS.
Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Изоляция хранилищ ДО импорта app-модулей (паттерн test_progress_progr25c).
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.research_runs import (  # noqa: E402
    get_research_run_store,
    reset_research_run_store_for_testing,
)
from apps.api.routers.progress import ProgressTraceResponse  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    reset_session_store_for_testing,
)
from apps.api.target_column_rule import (  # noqa: E402
    auto_fix_and_seed,
    target_column_candidates,
)
from apps.api.trace_hook import TRACE_ROUTES  # noqa: E402

OUT = Path(os.environ.get(
    "DCERT_PROTOCOL_PATH",
    str(REPO / "scripts" / "progr25dcert_oracles.txt"),
))
_lines: list[str] = []
_failures: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def check(oid: str, label: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    emit(f"  [{mark}] {oid} {label}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(f"{oid}: {label}" + (f" -- {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────────────────────
# СВОИ данные (seeded, воспроизводимые)
# ─────────────────────────────────────────────────────────────────────────────

SEED_CERT = 20261009


def _rain_hourly_df(with_multi: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(SEED_CERT)
    n = 96
    ts = pd.date_range("2025-03-01 00:00", periods=n, freq="h").strftime("%Y-%m-%d %H:%M")
    base = 8.0 + 3.0 * np.sin(2.0 * np.pi * np.arange(n) / 24.0)
    rain = np.round(base + rng.normal(0.0, 0.8, n), 2)
    data = {"timestamp": ts, "rain": rain}
    if with_multi:
        data["snow"] = np.round(rng.normal(1.5, 0.3, n), 2)
        data["humidity"] = np.round(rng.normal(70.0, 5.0, n), 2)
    return pd.DataFrame(data)


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


DEMO_RAIN_SINGLE = (
    "date,rain\n2025-03-01 00:00,4.2\n2025-03-01 01:00,3.9\n2025-03-01 02:00,5.1\n"
)
DEMO_RAIN_TWO = (
    "date,rain,snow\n2025-03-01 00:00,4.2,1.1\n"
    "2025-03-01 01:00,3.9,1.4\n2025-03-01 02:00,5.1,0.9\n"
)

client = TestClient(app)


def _reset() -> None:
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()


def _upload(df: pd.DataFrame, filename: str) -> dict:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, io.BytesIO(_csv_bytes(df)), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _current() -> dict:
    r = client.get("/v1/session/current")
    assert r.status_code == 200, r.text
    return r.json()


def _trace() -> dict:
    r = client.get("/v1/progress/trace")
    assert r.status_code == 200, r.text
    return r.json()


def _selector() -> dict:
    r = client.get("/v1/session/target-column")
    assert r.status_code == 200, r.text
    return r.json()


def _phase_text(run_id: str) -> str:
    r = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert r.status_code == 200, r.text
    return r.json()["phase_text"]


def _of_type(events: list[dict], etype: str) -> list[dict]:
    return [e for e in events if e.get("event_type") == etype]


# ─────────────────────────────────────────────────────────────────────────────
# G: генератор n150 -- детерминизм и спецификация Ф4 (против базовой линии)
# ─────────────────────────────────────────────────────────────────────────────

def group_g() -> None:
    emit("== G: генератор n150 (детерминизм + спецификация Ф4 спеки) ==")
    spec = importlib.util.spec_from_file_location(
        "dfm_dcert", REPO / "scripts" / "dataset_forecast_monitor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    df1, df2 = mod.generate_series(), mod.generate_series()
    b1 = df1.to_csv(index=False).encode()
    b2 = df2.to_csv(index=False).encode()
    check("G1", "детерминизм: два прогона -- идентичные байты CSV",
          hashlib.md5(b1).hexdigest() == hashlib.md5(b2).hexdigest())

    ok_struct = (
        df1.shape == (150, 2)
        and list(df1.columns) == ["date", "value"]
        and sorted(df1.index[df1["value"].isna()].tolist()) == [45, 87, 122]
        and int(df1["date"].isna().sum()) == 0
    )
    check("G2", "структура: (150,2), date/value, пропуски ровно @{45,87,122}, даты целы",
          ok_struct)

    # Базовая линия ДОКУМЕНТИРОВАНА в шапке генератора (спецификация Ф4):
    # value = 120 + 0.55*t + 18*sin(2*pi*(t+2)/12) + шум; выбросы -- 4 точки.
    # Аудитор проверяет ПРОТИВ формулы спеки, не против кода генератора.
    t = np.arange(150, dtype=float)
    baseline = 120.0 + 0.55 * t + 18.0 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    observed = df1["value"].to_numpy(dtype=float)
    dev = np.abs(observed - baseline)
    dev[~np.isfinite(dev)] = -1.0  # NaN-пропуски не участвуют
    top4 = sorted(np.argsort(dev)[-4:].tolist())
    signs = [observed[i] - baseline[i] for i in top4]
    up = sum(1 for s in signs if s > 0)
    check("G3", "выбросы: 4 максимума отклонения ровно @{25,70,105,130}, "
                "3 спайка вверх + 1 провал вниз, значения > 0",
          top4 == [25, 70, 105, 130] and up == 3
          and float(np.nanmin(observed)) > 0,
          f"top4={top4}")


# ─────────────────────────────────────────────────────────────────────────────
# E: сквозной сценарий на СВОИХ данных (rain_hourly)
# ─────────────────────────────────────────────────────────────────────────────

def group_e() -> None:
    emit("")
    emit("== E: сквозной сценарий на rain_hourly (96 часовых точек, rain) ==")
    _reset()
    _upload(_rain_hourly_df(), "rain_hourly.csv")

    cur = _current()
    check("E1", "/current: датасет активен, rain/auto, дата не зарегистрирована",
          cur["has_active_dataset"] is True
          and cur["target_column"] == "rain"
          and cur["target_column_source"] == "auto"
          and cur["date_column"] is None,
          f"{cur.get('target_column')}/{cur.get('target_column_source')}")

    tr = _trace()
    check("E2", "/trace-носитель (шапка B): rain/auto наверху ответа",
          tr["target_column"] == "rain" and tr["target_column_source"] == "auto")

    changed = _of_type(tr["events"], "target_column_changed")
    ok_e3 = (
        len(changed) == 1
        and changed[0]["payload"] == {"target_column": "rain", "source": "auto"}
        and changed[0]["stage"] == "validation"
        and changed[0]["node_id"] is None
        and changed[0]["actor"] == "system"
    )
    check("E3", "ровно одно событие; payload канона A ТОЧНО; stage=validation, "
                "node_id=None, actor=system",
          ok_e3,
          f"payload={changed[0]['payload'] if changed else None}")

    completed = _of_type(tr["events"], "upload_completed")
    ok_e4 = bool(completed) and bool(changed) and changed[0]["run_id"] != "" \
        and changed[0]["run_id"] == completed[0]["run_id"]
    check("E4", "run_id события общий с upload_completed и непуст (§5)", ok_e4)

    types = [e.get("event_type") for e in tr["events"]]
    check("E5", "хронология слоя 1 (канон R3): фиксация раньше upload_completed",
          "target_column_changed" in types and "upload_completed" in types
          and types.index("target_column_changed") < types.index("upload_completed"))

    run_id = tr["run_id"]
    layer2 = [e.to_dict() for e in get_research_run_store().list_events(run_id)]
    l2_changed = _of_type(layer2, "target_column_changed")
    l2_completed = _of_type(layer2, "upload_completed")
    ok_e6 = (
        len(l2_changed) == 1
        and l2_changed[0]["payload"] == {"target_column": "rain", "source": "auto"}
        and bool(l2_completed)
        and layer2.index(l2_changed[0]) < layer2.index(l2_completed[0])
    )
    check("E6", "зеркало слоя 2: ровно одно run-событие канона, "
                "раньше upload_completed (хронология слоя 2)",
          ok_e6,
          f"n_changed={len(l2_changed)}")

    sel = _selector()
    check("E7", "селектор: тот же факт, рекомендация совпадает с фиксацией",
          sel["target_column"] == "rain"
          and sel["target_column_source"] == "auto"
          and sel["suggested_column"] == "rain"
          and "rain" in sel["available_columns"])

    cur2, tr2, sel2 = _current(), _trace(), _selector()
    ok_e8 = (
        cur2["target_column"] == tr2["target_column"] == sel2["target_column"] == "rain"
        and cur2["target_column_source"] == tr2["target_column_source"]
        == sel2["target_column_source"] == "auto"
    )
    check("E8", "трёхисточность после повторных чтений: /current == /trace == "
                "/target-column (rain/auto), идемпотентность",
          ok_e8)


# ─────────────────────────────────────────────────────────────────────────────
# M: Наставник на СВОИХ данных (авто / неоднозначность / user)
# ─────────────────────────────────────────────────────────────────────────────

def group_m() -> None:
    emit("")
    emit("== M: Наставник и reason на своих данных ==")
    # M1: авто-ветка -- текст называет rain, просьбы нет
    _reset()
    _upload(_rain_hourly_df(), "rain_hourly_m1.csv")
    r = client.post("/v1/session/date-column", json={"column": "timestamp"})
    assert r.status_code == 200, r.text
    run_id = _trace()["run_id"]
    text = _phase_text(run_id)
    check("M1", "авто-текст Наставника называет rain, просьбы выбрать нет",
          "выбран автоматически: rain" in text
          and "Подтвердите целевой признак" not in text,
          text[:120])

    # M2: неоднозначность -- честная просьба, рекомендация отображается, не фиксируется
    _reset()
    _upload(_rain_hourly_df(with_multi=True), "rain_multi.csv")
    r = client.post("/v1/session/date-column", json={"column": "timestamp"})
    assert r.status_code == 200, r.text
    tr = _trace()
    text2 = _phase_text(tr["run_id"])
    sel = _selector()
    ok_m2 = (
        "Подтвердите целевой признак" in text2
        and "выбран автоматически" not in text2
        and sel["target_column"] is None
        and sel["suggested_column"] == "rain"
        and _of_type(tr["events"], "target_column_changed") == []
    )
    check("M2", "неоднозначность (rain/snow/humidity): просьба выбрать; "
                "рекомендация rain отображается, НЕ фиксируется; событий нет",
          ok_m2, text2[:120])

    # M3: ручной выбор humidity -- user во всех носителях, BOTH-текст,
    # legacy-payload ручного события (без source)
    r = client.post("/v1/session/target-column", json={"column": "humidity"})
    assert r.status_code == 200, r.text
    resp = r.json()
    tr3 = _trace()
    cur3 = _current()
    sel3 = _selector()
    manual = _of_type(tr3["events"], "target_column_changed")
    text3 = _phase_text(tr3["run_id"])
    ok_m3 = (
        resp["target_column_source"] == "user"
        and cur3["target_column"] == "humidity" and cur3["target_column_source"] == "user"
        and tr3["target_column"] == "humidity" and tr3["target_column_source"] == "user"
        and sel3["target_column"] == "humidity" and sel3["target_column_source"] == "user"
        and len(manual) == 1
        and manual[0]["payload"] == {"target_column": "humidity"}
        and "Подтвердите целевой признак" not in text3
        and "выбран автоматически" not in text3
        and "целевой признак выбран" in text3
    )
    check("M3", "user-ветка: source=user во ВСЕХ трёх носителях; ровно одно "
                "событие с legacy-payload {target_column} без source; BOTH-текст "
                "без просьбы и без «автоматически»",
          ok_m3,
          f"payload={manual[0]['payload'] if manual else None}")


# ─────────────────────────────────────────────────────────────────────────────
# D: demo-точка правила на СВОИХ файлах (подмена DEMO_DATASET_PATH)
# ─────────────────────────────────────────────────────────────────────────────

def group_d() -> None:
    emit("")
    emit("== D: demo-точка правила (свои demo-файлы) ==")
    _reset()
    demo = REPO / "scripts" / "_dcert_demo_single.tmp.csv"
    demo.write_text(DEMO_RAIN_SINGLE, encoding="utf-8")
    try:
        original = "apps.api.routers.session.DEMO_DATASET_PATH"
        import apps.api.routers.session as session_mod
        saved = session_mod.DEMO_DATASET_PATH
        session_mod.DEMO_DATASET_PATH = demo
        try:
            r = client.post("/v1/session/demo")
            assert r.status_code == 200, r.text
            data = r.json()
            changed = _of_type(_trace()["events"], "target_column_changed")
            check("D1", "demo одночисловой (date,rain): фиксация rain/auto "
                        "+ ровно одно событие канона",
                  data["has_active_dataset"] is True
                  and data["target_column"] == "rain"
                  and data["target_column_source"] == "auto"
                  and len(changed) == 1
                  and changed[0]["payload"] == {"target_column": "rain", "source": "auto"},
                  f"{data.get('target_column')}/{data.get('target_column_source')}")
        finally:
            session_mod.DEMO_DATASET_PATH = saved
    finally:
        demo.unlink(missing_ok=True)

    _reset()
    demo2 = REPO / "scripts" / "_dcert_demo_two.tmp.csv"
    demo2.write_text(DEMO_RAIN_TWO, encoding="utf-8")
    try:
        import apps.api.routers.session as session_mod
        saved = session_mod.DEMO_DATASET_PATH
        session_mod.DEMO_DATASET_PATH = demo2
        try:
            r = client.post("/v1/session/demo")
            assert r.status_code == 200, r.text
            data = r.json()
            check("D2", "demo двухчисловой (date,rain,snow): честная "
                        "неоднозначность -- фиксации/события нет (guard R2)",
                  data["target_column"] is None
                  and data["target_column_source"] is None
                  and _of_type(_trace()["events"], "target_column_changed") == [],
                  f"{data.get('target_column')}/{data.get('target_column_source')}")
        finally:
            session_mod.DEMO_DATASET_PATH = saved
    finally:
        demo2.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# C: носители и контракты (свежая сессия, TRACE_ROUTES, схема)
# ─────────────────────────────────────────────────────────────────────────────

def group_c() -> None:
    emit("")
    emit("== C: носители и контракты ==")
    _reset()
    tr = _trace()
    cur = _current()
    check("C1", "свежая сессия: носитель /trace честно пуст (None/None), "
                "/current без признака",
          tr["target_column"] is None and tr["target_column_source"] is None
          and cur["target_column"] is None)

    specs = [s for s in TRACE_ROUTES
             if s.method == "POST" and s.path_template == "/v1/session/target-column"]
    ok_c2 = (
        len(specs) == 1
        and specs[0].event_type == "target_column_changed"
        and {"target_column", "source"} <= set(specs[0].payload_keys)
    )
    check("C2", "TRACE_ROUTES: POST /v1/session/target-column зафиксирован "
                "однократно, event_type=target_column_changed, "
                "payload_keys ⊇ {target_column, source}",
          ok_c2,
          f"n={len(specs)}, keys={specs[0].payload_keys if specs else None}")

    fields = ProgressTraceResponse.model_fields
    check("C3", "ProgressTraceResponse.model_fields ⊇ "
                "{target_column, target_column_source} (носитель шапки B)",
          "target_column" in fields and "target_column_source" in fields)


# ─────────────────────────────────────────────────────────────────────────────
# U: вычеты правила на СВОИХ колонках (юнит)
# ─────────────────────────────────────────────────────────────────────────────

def _unit_session(columns: dict, **fields) -> AnalysisSession:
    s = AnalysisSession(session_id="dcert-unit")
    for k, v in fields.items():
        setattr(s, k, v)
    s.dataframe = pd.DataFrame(columns)
    return s


def group_u() -> None:
    emit("")
    emit("== U: вычеты правила на своих колонках ==")
    # U1: часовая ось ЗАРЕГИСТРИРОВАНА как date_column -- исключается по факту
    s = _unit_session({"hour_index": [1, 2, 3], "snow": [0.4, 0.5, 0.6]},
                      date_column="hour_index")
    ok_u1 = (target_column_candidates(s) == ["snow"]
             and auto_fix_and_seed(s) == "snow"
             and s.target_column == "snow"
             and s.target_column_source == "auto")
    check("U1", "дата-факт: hour_index зарегистрирована -- единственный "
                "кандидат snow, авто-фиксация snow/auto",
          ok_u1)

    # U2: та же пара БЕЗ регистрации -- два кандидата, фиксации нет (guard)
    s2 = _unit_session({"hour_index": [1, 2, 3], "snow": [0.4, 0.5, 0.6]})
    ok_u2 = (target_column_candidates(s2) == ["hour_index", "snow"]
             and auto_fix_and_seed(s2) is None
             and s2.target_column is None
             and s2.target_column_source is None)
    check("U2", "guard: без регистрации даты -- два кандидата, честная "
                "неоднозначность (None/None)",
          ok_u2)

    # U3: реестр решает: pressure_detrended исключается, фиксация rain
    s3 = _unit_session({"rain": [4.0, 5.0, 6.0],
                        "pressure_detrended": [0.1, 0.2, 0.3]})
    before = auto_fix_and_seed(s3)
    s3.derived_columns = {"pressure_detrended": {"stage": "preprocessing"}}
    after = auto_fix_and_seed(s3)
    ok_u3 = (before is None and after == "rain"
             and s3.target_column_source == "auto"
             and s3.pipeline_trace[-1]["payload"]
             == {"target_column": "rain", "source": "auto"})
    check("U3", "реестр решает (канон PROGR-24): pressure_detrended в реестре "
                "исключается -- фиксация rain; payload канона в pipeline_trace",
          ok_u3)

    # U4: производноподобное имя ВНЕ реестра -- полноценный кандидат (guard)
    s4 = _unit_session({"rain": [4.0, 5.0, 6.0],
                        "snow_detrended": [0.1, 0.2, 0.3]})
    ok_u4 = (target_column_candidates(s4) == ["rain", "snow_detrended"]
             and auto_fix_and_seed(s4) is None)
    check("U4", "guard: snow_detrended вне реестра -- кандидат; «не угадываем "
                "по суффиксу» (None)",
          ok_u4)


def main() -> int:
    emit("=" * 78)
    emit("СЕРТИФИКАЦИЯ PROGR-25-D-CERT -- ОРАКУЛЫ НА СВОИХ ДАННЫХ")
    emit("Свои датасеты: rain_hourly/rain_multi (timestamp,rain[,snow,humidity],")
    emit("seed 20261009), demo_rain_single/two; колонки hour_index/snow/")
    emit("pressure_detrended/snow_detrended -- дискриминаторы хардкода имён.")
    emit("=" * 78)
    group_g()
    group_e()
    group_m()
    group_d()
    group_c()
    group_u()
    total = 3 + 8 + 3 + 2 + 3 + 4
    emit("")
    emit("─" * 78)
    emit(f"ИТОГ: {total - len(_failures)}/{total} PASS"
         + (f"; FAIL: {len(_failures)}" if _failures else " -- все оракулы зелёные"))
    for f in _failures:
        emit(f"  !! {f}")
    emit("─" * 78)
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
