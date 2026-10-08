#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ задачи A (spec_progress_target_column.md,
Task PROGR-25-A) -- аудит PROGR-25-A-CERT.

Принципы (прецеденты PROGR-17/18/20/21/24-CERT):
  - данные СВОИ, не пересекающиеся ни с данными разработчика (крошечные
    3-строчные CSV date/value и встроенный sales_demo.csv), ни с датасетом
    прошлой сертификации PROGR-24-CERT (retail_daily.csv, 364 точки);
  - оракулы НЕ копируют ассерты test_progress_progr25a.py /
    test_target_column.py, а атакуют с других углов: почасовой энергетический
    ряд, ловушка-«год» с последующим ФАКТОМ регистрации даты, приманка
    «load_detrended» в самом файле, вырожденный нечисловой фрейм,
    согласованность трёх источников истины (/current, /target-column,
    /trace-носитель), чистота чтений, аддитивность трёх схем.

СВОЙ датасет -- почасовое энергопотребление energy_hourly.csv, 336 точек
(14 суток), колонки: ts (ISO-час) / load (МВт; суточная сезонность, тренд,
выходной провал, шум, seeded). Варианты: v2 + price (2 числовых), v3
year(int)+load (ловушка R4), v4 + load_detrended (приманка-«производная»,
загружена В ФАЙЛЕ; реестр пуст -> имя не решает), v6 region (0 числовых).

Группы:
  A -- юнит-контракты apps/api/target_column_rule.py на своих сценариях (12);
  B -- живой API на своём датасете (20);
  C -- сквозные инварианты/совместимость (6);
  D -- персистентность нового поля (3; D1/D2 -- ожидаемые FAIL, доказательство
       находки F1: target_column_source не сериализуется).

Выход: scripts/progr25acert_oracles.txt; exit 0 == все PASS кроме ровно
{D1,D2} (задокументированный дефект F1). Правила AGENTS.md: только
измерение, без commit/push.
"""
from __future__ import annotations

import io
import json
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
from apps.api.routers.progress import ProgressTraceResponse  # noqa: E402
from apps.api.schemas import (  # noqa: E402
    SessionStateResponse,
    TargetColumnResponse,
)
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    DatasetInfo,
    RedisSessionStore,
    reset_session_store_for_testing,
    session_from_dict,
    session_to_dict,
)
from apps.api.target_column_rule import (  # noqa: E402
    auto_fix_and_seed,
    numeric_columns,
    suggest_target_column,
    target_column_candidates,
)
from apps.api.trace_hook import TRACE_ROUTES  # noqa: E402

OUT = REPO / "scripts" / "progr25acert_oracles.txt"

_lines: list[str] = []
_checks: list[tuple[str, bool]] = []


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def check(label: str, ok: bool) -> bool:
    _checks.append((label, ok))
    emit(f"    [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


# ── свой датасет: почасовая энергия ──────────────────────────────────


def _load_series(n: int = 336, seed: int = 20251008) -> np.ndarray:
    """МВт-потребление: суточная сезонность (день/ночь), недельный
    выходной провал, линейный рост, шум."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    hour = t % 24.0
    dow = (t // 24.0) % 7.0
    load = (
        520.0
        + 0.05 * t
        + 130.0 * np.exp(-0.5 * ((hour - 9) / 2.4) ** 2)
        + 165.0 * np.exp(-0.5 * ((hour - 19) / 2.6) ** 2)
        - 60.0 * np.exp(-0.5 * ((hour - 3) / 3.0) ** 2)
        - 45.0 * (dow >= 5).astype(float)
        + rng.normal(0, 9.0, n)
    )
    return np.round(load, 2)


def _ts_index(n: int = 336) -> list[str]:
    return pd.date_range("2026-09-01", periods=n, freq="h").astype(str).tolist()


def _decoy_detrended(load: np.ndarray) -> np.ndarray:
    """Приманка «load_detrended»: тренд снят ОФФЛАЙН при подготовке файла
    (центрированное окно 24) -- ИСХОДНАЯ колонка с производноподобным
    именем; реестр обязан считать её исходной (канон PROGR-24: не по
    суффиксу). Имя не совпадает с генерируемыми суффиксами платформы."""
    s = pd.Series(load)
    det = s - s.rolling(24, center=True, min_periods=1).mean() + s.mean()
    return np.round(det.to_numpy(), 2)


def energy_frame(version: int = 1) -> pd.DataFrame:
    load = _load_series()
    ts = _ts_index(len(load))
    if version == 1:
        return pd.DataFrame({"ts": ts, "load": load})
    if version == 2:
        price = np.round(3.5 + 0.002 * np.arange(len(load)) + load / 900.0, 3)
        return pd.DataFrame({"ts": ts, "load": load, "price": price})
    if version == 3:
        year = pd.to_datetime(ts).year.to_numpy()
        return pd.DataFrame({"year": year, "load": load})
    if version == 4:
        return pd.DataFrame(
            {"ts": ts, "load": load, "load_detrended": _decoy_detrended(load)}
        )
    # version 6: вырожденный фрейм без числовых кандидатов
    region = np.where(np.arange(len(load)) % 2 == 0, "north", "south")
    return pd.DataFrame({"ts": ts, "region": region})


def csv_of(frame: pd.DataFrame) -> io.BytesIO:
    return io.BytesIO(frame.to_csv(index=False).encode("utf-8"))


def upload(client: TestClient, version: int, name: str = "energy_hourly.csv") -> dict:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (name, csv_of(energy_frame(version)), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def fresh_client() -> TestClient:
    reset_session_store_for_testing()
    return TestClient(app)


def trace_events(client: TestClient) -> list[dict]:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def target_changed(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("event_type") == "target_column_changed"]


def unit_session(frame: pd.DataFrame, **fields) -> AnalysisSession:
    session = AnalysisSession(session_id="cert25a-unit")
    session.dataset = DatasetInfo(
        dataset_id="cert25a", name="energy_hourly.csv",
        rows=len(frame), columns=len(frame.columns), size_label="48 KB",
    )
    session.dataframe = frame
    for key, value in fields.items():
        setattr(session, key, value)
    return session


# ══ Группа A: юнит-контракты правила на своих сценариях ══════════════


def group_a() -> None:
    emit("── A. Юнит-контракты target_column_rule (свои сценарии) ──")

    frame1 = energy_frame(1)
    frame4 = energy_frame(4)

    # A1: numeric_columns -- int/float числовые; строки/timestamps нет.
    # ФАКТ pandas 2.2.3: bool НЕ входит в select_dtypes(include="number") --
    # докстринг модуля ("pandas считает bool числовым") неточен, поведение
    # прежнее (перенос _get_numeric_columns без изменения семантики) --
    # находка F2 акта; для TS-target исключение bool безопаснее.
    probe = pd.DataFrame({
        "b": [True, False, True],
        "i": np.array([1, 2, 3], dtype="int64"),
        "f": [1.5, 2.5, 3.5],
        "s": ["x", "y", "z"],
        "d": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    })
    got = set(numeric_columns(probe))
    check("A1 numeric_columns: int/float числовые; bool/строки/даты нет "
          "(докстрингу о bool -- находка F2)",
          got == {"i", "f"})

    # A2: приманка load_detrended (вне реестра) остаётся кандидатом.
    session = unit_session(frame4)
    cands = target_column_candidates(session)
    check("A2 приманка-исходная load_detrended -- кандидат (не по суффиксу)",
          cands == ["load", "load_detrended"])

    # A3: реестр исключает производную; ghost-запись безвредна.
    session_registry = unit_session(
        frame4, derived_columns={"load_detrended": {"stage": "preprocessing"}}
    )
    check("A3 колонка реестра исключена из кандидатов",
          target_column_candidates(session_registry) == ["load"])
    session_ghost = unit_session(frame1, derived_columns={"ghost_col": {"stage": "x"}})
    check("A3b ghost-запись реестра безвредна",
          target_column_candidates(session_ghost) == ["load"])

    # A4: date_column-факт исключает даже с НЕдатоподобным именем.
    frame_ax = pd.DataFrame(
        {"hour_idx": np.arange(336, dtype="int64"), "load": _load_series()[:336]}
    )
    session_ax = unit_session(frame_ax, date_column="hour_idx")
    check("A4 date_column-факт исключён (имя hour_idx не date-подобное)",
          target_column_candidates(session_ax) == ["load"])

    # A5: рекомендация -- первый кандидат по порядку фрейма; пусто -> None.
    check("A5 suggest = первый кандидат по порядку фрейма",
          suggest_target_column(unit_session(frame4)) == "load"
          and suggest_target_column(unit_session(energy_frame(3))) == "year")
    check("A5b пустой список кандидатов -> recommend None",
          suggest_target_column(unit_session(energy_frame(6))) is None)

    # A6: dataframe=None -- честный пустой список.
    session_none = AnalysisSession(session_id="cert25a-nodf")
    check("A6 dataframe=None -> кандидатов нет без исключений",
          target_column_candidates(session_none) == []
          and suggest_target_column(session_none) is None)

    # A7: авто-фиксация при ровно одном кандидате -- полный состав.
    session_fix = unit_session(frame1)
    fixed = auto_fix_and_seed(session_fix)
    events = [e for e in session_fix.pipeline_trace
              if e.get("event_type") == "target_column_changed"]
    ev = events[0] if events else {}
    check("A7 авто-фиксация возвращает load, source=auto",
          fixed == "load" and session_fix.target_column == "load"
          and session_fix.target_column_source == "auto")
    check("A7b событие: payload ровно {target_column, source: auto}",
          ev.get("payload") == {"target_column": "load", "source": "auto"})
    check("A7c событие: stage=validation, node_id=None, actor=system",
          ev.get("stage") == "validation" and ev.get("node_id") is None
          and ev.get("actor") == "system")
    check("A7d run_id зафиксирован и общий у события",
          ev.get("run_id", "") != ""
          and ev.get("run_id") == session_fix.run_id)

    # A8: два кандидата -- фиксации нет, состояние нетронуто.
    session_amb = unit_session(frame4)
    before = len(session_amb.pipeline_trace)
    check("A8 два кандидата -> None, target/source не тронуты, трасса не росла",
          auto_fix_and_seed(session_amb) is None
          and session_amb.target_column is None
          and session_amb.target_column_source is None
          and len(session_amb.pipeline_trace) == before)

    # A9: ноль кандидатов (единственная числовая -- date-ось).
    only_axis = pd.DataFrame({"hour_idx": np.arange(336, dtype="int64")})
    session_zero = unit_session(only_axis, date_column="hour_idx")
    check("A9 ноль кандидатов -> None (фиксации/события нет)",
          auto_fix_and_seed(session_zero) is None
          and session_zero.pipeline_trace == [])

    # A10: прямой set_target_column (путь restore) не сеет и не ставит.
    session_restore = unit_session(frame1)
    session_restore.set_target_column("load")
    check("A10 restore-путь: set_target_column без события и без source",
          session_restore.target_column == "load"
          and session_restore.target_column_source is None
          and session_restore.pipeline_trace == [])

    # A11: повторный вызов auto_fix_and_seed -- ВТОРОЕ событие
    # (документирующий якорь: защита -- единственная точка вызова
    # upload/demo + set_dataset reset; канон наблюдаемого поведения).
    session_twice = unit_session(frame1)
    auto_fix_and_seed(session_twice)
    auto_fix_and_seed(session_twice)
    twice = [e for e in session_twice.pipeline_trace
             if e.get("event_type") == "target_column_changed"]
    check("A11 повторный вызов сеет второе событие (документирующий якорь)",
          len(twice) == 2 and session_twice.target_column_source == "auto")

    # A12: stage-level событие авто-фиксации не двигает last_active_stage.
    session_stage = unit_session(frame1)
    session_stage.last_active_stage = "upload"
    auto_fix_and_seed(session_stage)
    check("A12 событие stage=validation не двигает last_active_stage",
          session_stage.last_active_stage == "upload")


# ══ Группа B: живой API на своём датасете ════════════════════════════


def group_b() -> None:
    emit("── B. Живой API на своём датасете (energy_hourly) ──")

    # B1-B4: однозначный случай.
    client = fresh_client()
    upload(client, 1)
    current = client.get("/v1/session/current").json()
    check("B1 upload v1 -> /current: target=load, source=auto",
          current["target_column"] == "load"
          and current["target_column_source"] == "auto")

    tc = client.get("/v1/session/target-column").json()
    check("B2 GET /target-column зеркалит и рекомендует load",
          tc["target_column"] == "load" and tc["target_column_source"] == "auto"
          and tc["suggested_column"] == "load"
          and tc["available_columns"] == ["load"])

    events = trace_events(client)
    fixed = target_changed(events)
    upl = [e for e in events if e.get("event_type") == "upload_completed"]
    ev = fixed[0] if fixed else {}
    # ФАКТИЧЕСКАЯ хронология слоя 1: target_column_changed ПЕРЕД
    # upload_completed -- фиксация происходит в точке обработки upload
    # (R3: посев в точке фиксации), upload_completed сеется хуком на
    # ответ маршрута. run_id общий: первая запись слоя 1 фиксирует run_id.
    check("B3 ровно одно событие; хронология фиксация -> upload_completed",
          len(fixed) == 1 and bool(upl)
          and events.index(ev) < events.index(upl[0]))
    check("B3b payload/stage/node_id/actor/run_id события",
          ev.get("payload") == {"target_column": "load", "source": "auto"}
          and ev.get("stage") == "validation" and ev.get("node_id") is None
          and ev.get("actor") == "system"
          and ev.get("run_id", "") != ""
          and ev.get("run_id") == upl[0].get("run_id"))

    trace_top = client.get("/v1/progress/trace").json()
    check("B4 носитель задачи B: /trace target_column/source наверху",
          trace_top["target_column"] == "load"
          and trace_top["target_column_source"] == "auto")

    # B5: неоднозначность v2.
    client2 = fresh_client()
    upload(client2, 2, "energy_hourly_v2.csv")
    cur2 = client2.get("/v1/session/current").json()
    events2 = trace_events(client2)
    top2 = client2.get("/v1/progress/trace").json()
    check("B5 v2 (2 числовых): фиксации/события/носителя нет",
          cur2["target_column"] is None
          and cur2["target_column_source"] is None
          and target_changed(events2) == []
          and top2["target_column"] is None
          and top2["target_column_source"] is None)
    check("B5b рекомендация -- первый кандидат по порядку (load)",
          client2.get("/v1/session/target-column").json()["suggested_column"] == "load")

    # B6: ловушка R4 v3 (year + load).
    client3 = fresh_client()
    upload(client3, 3, "energy_year.csv")
    cur3 = client3.get("/v1/session/current").json()
    check("B6 v3 [year, load]: фиксации нет, событие отсутствует (R4)",
          cur3["target_column"] is None
          and cur3["target_column_source"] is None
          and target_changed(trace_events(client3)) == [])
    check("B6b рекомендация = year (первый кандидат; имя-исключение снято)",
          client3.get("/v1/session/target-column").json()["suggested_column"] == "year")

    # B7: R4 факт-вычет: регистрация year как даты -> рекомендация load,
    # но фиксации НЕТ (правило живёт только в точках загрузки).
    dc = client3.post("/v1/session/date-column", json={"column": "year"})
    tc3 = client3.get("/v1/session/target-column").json()
    check("B7 факт date_column=year -> рекомендация load",
          dc.status_code == 200 and tc3["suggested_column"] == "load")
    check("B7b авто-фиксации вне точек загрузки нет (осознанная граница)",
          tc3["target_column"] is None and tc3["target_column_source"] is None
          and target_changed(trace_events(client3)) == [])

    # B8: приманка v4 в живом API.
    client4 = fresh_client()
    upload(client4, 4, "energy_decoy.csv")
    cur4 = client4.get("/v1/session/current").json()
    check("B8 v4 приманка load_detrended: 2 кандидата, фиксации нет",
          cur4["target_column"] is None
          and cur4["target_column_source"] is None
          and target_changed(trace_events(client4)) == [])
    check("B8b рекомендация load (порядок фрейма; суффикс не решает)",
          client4.get("/v1/session/target-column").json()["suggested_column"] == "load")

    # B9: demo-путь (R2) на встроенном sales_demo.
    client5 = fresh_client()
    demo = client5.post("/v1/session/demo")
    democur = client5.get("/v1/session/current").json()
    check("B9 demo: sales_demo (2 числовых) -- честное «не выбран»",
          demo.status_code == 200 and democur["has_active_dataset"] is True
          and democur["target_column"] is None
          and democur["target_column_source"] is None
          and target_changed(trace_events(client5)) == [])
    check("B9b /trace носитель demo: None/None; ключ source в ответе demo",
          client5.get("/v1/progress/trace").json()["target_column"] is None
          and "target_column_source" in demo.json())

    # B9c: ЖИВОЕ доказательство R2 для одночислового demo: подмена
    # DEMO_DATASET_PATH на СВОЙ одночисловой CSV (monkeypatch -- техника
    # тестирования, код эндпоинта не меняется; встроенный sales_demo
    # двоичен и делает demo-точку необозримой -- гэп, закрываемый здесь).
    import tempfile
    from apps.api.routers import session as session_router

    client5b = fresh_client()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        energy_frame(1).to_csv(tmp.name, index=False)
        single_path = tmp.name
    original_demo_path = session_router.DEMO_DATASET_PATH
    try:
        session_router.DEMO_DATASET_PATH = Path(single_path)
        demo2 = client5b.post("/v1/session/demo")
        cur5b = client5b.get("/v1/session/current").json()
        fixed5b = target_changed(trace_events(client5b))
        top5b = client5b.get("/v1/progress/trace").json()
    finally:
        session_router.DEMO_DATASET_PATH = original_demo_path
        os.unlink(single_path)
    check("B9c demo одночислового CSV (R2): target=load, source=auto",
          demo2.status_code == 200
          and cur5b["target_column"] == "load"
          and cur5b["target_column_source"] == "auto")
    check("B9c событие авто на demo-пути; носитель /trace согласован",
          len(fixed5b) == 1
          and fixed5b[0]["payload"] == {"target_column": "load", "source": "auto"}
          and top5b["target_column"] == "load"
          and top5b["target_column_source"] == "auto")

    # B10: ручной выбор после demo -> user; payload ручного события без source.
    # (Свой client: fresh_client() в B9c сбросил store -- изолируем сценарий.)
    client5 = fresh_client()
    client5.post("/v1/session/demo")
    manual = client5.post("/v1/session/target-column", json={"column": "sales"})
    manual_events = target_changed(trace_events(client5))
    check("B10 demo -> ручной выбор sales: source=user",
          manual.status_code == 200
          and manual.json()["target_column_source"] == "user")
    check("B10b payload ручного события без ключа source (legacy-канал)",
          len(manual_events) == 1
          and "source" not in manual_events[0]["payload"]
          and manual_events[0]["payload"]["target_column"] == "sales")

    # B11: last-wins user поверх auto; порядок событий auto -> manual.
    client6 = fresh_client()
    upload(client6, 1)
    client6.post("/v1/session/target-column", json={"column": "load"})
    events6 = target_changed(trace_events(client6))
    check("B11 ручной поверх авто: source=user, 2 события в порядке auto->manual",
          client6.get("/v1/session/current").json()["target_column_source"] == "user"
          and len(events6) == 2
          and events6[0]["payload"].get("source") == "auto"
          and "source" not in events6[1]["payload"])

    # B12: повторный выбор ТОЙ ЖЕ колонки: паспорт не сбрасывается,
    # source всё равно user (событие/канон set_target_column не менялись).
    client7 = fresh_client()
    upload(client7, 1)
    client7.post("/v1/session/dataset/passport/start")
    again = client7.post("/v1/session/target-column", json={"column": "load"})
    check("B12 re-pick той же колонки: passport_history_reset=False, source=user",
          again.status_code == 200
          and again.json()["passport_history_reset"] is False
          and again.json()["target_column_source"] == "user")

    # B13: convert-types сбрасывает ЦЕЛЬ И ИСТОЧНИК; носитель согласован.
    client8 = fresh_client()
    upload(client8, 1)
    conv = client8.post(
        "/v1/session/dataset/convert-types",
        json={"conversions": [{"column": "load", "target_type": "string"}],
              "invalid_policy": "coerce", "apply": True},
    )
    cur8 = client8.get("/v1/session/current").json()
    top8 = client8.get("/v1/progress/trace").json()
    check("B13 convert load->string: target и source сброшены",
          conv.status_code == 200 and conv.json()["target_column_reset"] is True
          and cur8["target_column"] is None
          and cur8["target_column_source"] is None)
    check("B13b носитель /trace согласован после сброса",
          top8["target_column"] is None
          and top8["target_column_source"] is None)

    # B14: re-upload того же файла -- трасса слоя 1 перезапущена, 1 событие.
    client9 = fresh_client()
    upload(client9, 1)
    upload(client9, 1)
    events9 = target_changed(trace_events(client9))
    check("B14 re-upload: ровно одно событие авто (канон PROGR-3)",
          len(events9) == 1
          and events9[0]["payload"] == {"target_column": "load", "source": "auto"})

    # B15: re-upload чередованием v1 -> v2: сброс без новой фиксации.
    client10 = fresh_client()
    upload(client10, 1)
    upload(client10, 2, "energy_hourly_v2.csv")
    cur10 = client10.get("/v1/session/current").json()
    check("B15 v1(авто) -> v2(2 числовых): честное «не выбран»",
          cur10["target_column"] is None
          and cur10["target_column_source"] is None
          and target_changed(trace_events(client10)) == [])

    # B16: вырожденный фрейм без числовых.
    client11 = fresh_client()
    upload(client11, 6, "energy_regions.csv")
    cur11 = client11.get("/v1/session/current").json()
    tc11 = client11.get("/v1/session/target-column").json()
    check("B16 0 числовых: фиксации нет, suggested=None, available=[]",
          cur11["target_column"] is None
          and cur11["target_column_source"] is None
          and tc11["suggested_column"] is None
          and tc11["available_columns"] == []
          and target_changed(trace_events(client11)) == [])

    # B17: три источника истины согласованы во всех трёх состояниях.
    client12 = fresh_client()
    upload(client12, 1)
    s1 = (client12.get("/v1/session/current").json()["target_column"],
          client12.get("/v1/progress/trace").json()["target_column"],
          client12.get("/v1/session/target-column").json()["target_column"])
    upload(client12, 2, "energy_hourly_v2.csv")
    s2 = (client12.get("/v1/session/current").json()["target_column"],
          client12.get("/v1/progress/trace").json()["target_column"],
          client12.get("/v1/session/target-column").json()["target_column"])
    client12.post("/v1/session/target-column", json={"column": "load"})
    s3 = (client12.get("/v1/session/current").json()["target_column"],
          client12.get("/v1/progress/trace").json()["target_column"],
          client12.get("/v1/session/target-column").json()["target_column"])
    check("B17 /current == /trace == /target-column (auto/None/user)",
          s1 == ("load", "load", "load")
          and s2 == (None, None, None)
          and s3 == ("load", "load", "load"))

    # B18: аддитивность трёх схем.
    check("B18 SessionStateResponse/TargetColumnResponse: source Optional=None",
          "target_column_source" in SessionStateResponse.model_fields
          and SessionStateResponse.model_fields["target_column_source"].default is None
          and "target_column_source" in TargetColumnResponse.model_fields
          and TargetColumnResponse.model_fields["target_column_source"].default is None)
    check("B18b ProgressTraceResponse: target_column/source Optional=None",
          "target_column" in ProgressTraceResponse.model_fields
          and "target_column_source" in ProgressTraceResponse.model_fields
          and ProgressTraceResponse.model_fields["target_column"].default is None
          and ProgressTraceResponse.model_fields["target_column_source"].default is None)

    # B19: канал source в TRACE_ROUTES и фактический payload ручного события.
    spec = next((s for s in TRACE_ROUTES
                 if s.method == "POST"
                 and s.path_template == "/v1/session/target-column"),
                None)
    check("B19 payload_keys target-column-маршрута содержит source",
          spec is not None and "source" in spec.payload_keys
          and "target_column" in spec.payload_keys)

    # B20: чтения чистые -- GET не создаёт событий и не меняет source.
    client13 = fresh_client()
    upload(client13, 1)
    n_before = len(trace_events(client13))
    client13.get("/v1/session/current")
    client13.get("/v1/session/target-column")
    client13.get("/v1/progress/trace")
    check("B20 GET-чтения не создают событий и не меняют состояние",
          len(trace_events(client13)) == n_before
          and client13.get("/v1/session/current").json()["target_column_source"] == "auto")


# ══ Группа C: сквозные инварианты/совместимость ══════════════════════


def group_c() -> None:
    emit("── C. Сквозные инварианты и совместимость ──")

    # C1: legacy-документ без target_column_source читается без ошибок.
    # (dataframe_json в Redis-документе -- JSON-строка, см. _dataframe_to_json.)
    legacy = {
        "session_id": "cert25a-legacy",
        "dataset": {"dataset_id": "d1", "name": "old.csv", "rows": 3,
                    "columns": 2, "size_label": "12 B"},
        "dataframe_json": json.dumps({
            "columns": ["load"],
            "index": [0, 1, 2],
            "data": [[1.0], [2.0], [3.0]],
        }),
        "stages": {"upload": "done"},
        "target_column": "load",
    }
    restored = session_from_dict(legacy)
    check("C1 legacy-документ: target жив, source=None (читается как user)",
          restored.target_column == "load"
          and restored.target_column_source is None)

    # C2: «ровно 7 полей» движка не затронуто -- payload события не поле
    # PipelineNodeState; проверка узла трассы /trace на исходной форме.
    client = fresh_client()
    upload(client, 1)
    nodes = client.get("/v1/progress/trace").json()["nodes"]
    forms = {tuple(sorted(n.keys())) for n in nodes} if nodes else set()
    check("C2 узлы трассы сохраняют исходную форму (аддитивность в /trace)",
          all("payload" not in f for f in forms))

    # C3: derived_columns (PROGR-24) и target_column переживают сериализацию
    # -- изоляция дефекта именно НОВОГО поля (см. D1).
    session = unit_session(energy_frame(1),
                           derived_columns={"x_sma_7": {"stage": "preprocessing"}})
    auto_fix_and_seed(session)
    roundtrip = session_from_dict(session_to_dict(session))
    check("C3 derived_columns и target_column переживают roundtrip",
          roundtrip.derived_columns == session.derived_columns
          and roundtrip.target_column == "load")

    # C4: состояние сессии согласовано с трассой на всём жизненном цикле:
    # auto-событие при source=auto; после ручного -- последнее событие
    # без source, сессия user.
    client2 = fresh_client()
    upload(client2, 1)
    client2.post("/v1/session/target-column", json={"column": "load"})
    evs = target_changed(trace_events(client2))
    check("C4 жизненный цикл: авто (source=auto) -> ручное (без source)",
          len(evs) == 2 and evs[0]["payload"].get("source") == "auto"
          and "source" not in evs[1]["payload"]
          and client2.get("/v1/session/current").json()["target_column_source"] == "user")

    # C5: ручной канал не позволяет зафиксировать НЕчисловую колонку
    # (контакт числовости правила).
    client3 = fresh_client()
    upload(client3, 6, "energy_regions.csv")
    bad = client3.post("/v1/session/target-column", json={"column": "region"})
    cur3 = client3.get("/v1/session/current").json()
    check("C5 ручная фиксация нечисловой отклонена (422/400), цель не установлена",
          bad.status_code in (400, 422) and cur3["target_column"] is None)

    # C6: SESSION_SCHEMA_VERSION не поднята -- аддитивное поле не требует
    # миграции (совместимо с решением по PROGR-24: подъём только при
    # структурных полях); документ v3 читается.
    from apps.api.session_store import SESSION_SCHEMA_VERSION
    check("C6 SESSION_SCHEMA_VERSION == 3 (аддитивность без миграции)",
          SESSION_SCHEMA_VERSION == 3)


# ══ Группа D: персистентность нового поля (находка F1) ═══════════════


def group_d() -> None:
    emit("── D. Персистентность target_column_source (контракт store) ──")

    session = unit_session(energy_frame(1))
    auto_fix_and_seed(session)

    # D1: КОНТРАКТ сериализации: source обязан переживать roundtrip.
    doc = session_to_dict(session)
    rt = session_from_dict(doc)
    ok1 = (rt.target_column_source == "auto" and rt.target_column == "load")
    _checks.append(("D1 source переживает to_dict/from_dict", ok1))
    emit(f"    [{'PASS' if ok1 else 'FAIL'}] D1 source переживает to_dict/from_dict"
         + ("" if ok1 else "  <-- ДЕФЕКТ F1: ключ 'target_column_source' в "
                           "документе отсутствует"))

    # D2: production-путь RedisSessionStore (fakeredis): save -> get.
    import fakeredis
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis())
    store.save(session)
    loaded = store.get(session.session_id)
    ok2 = loaded is not None and loaded.target_column_source == "auto"
    _checks.append(("D2 source переживает Redis save/get", ok2))
    emit(f"    [{'PASS' if ok2 else 'FAIL'}] D2 source переживает Redis save/get"
         + ("" if ok2 else "  <-- ДЕФЕКТ F1: production-путь теряет origin"))

    # D3: контраст -- старые поля в ТОМ ЖЕ документе сохраняются.
    ok3 = (loaded is not None and loaded.target_column == "load"
           and loaded.derived_columns == session.derived_columns
           and loaded.run_id == session.run_id)
    _checks.append(("D3 target/реестр/run_id в том же документе сохранены", ok3))
    emit(f"    [{'PASS' if ok3 else 'FAIL'}] D3 target/реестр/run_id в том же "
         "документе сохранены (изоляция дефекта новым полем)")


# ══ Итог ═════════════════════════════════════════════════════════════

EXPECTED_FAILS = {"D1 source переживает to_dict/from_dict",
                  "D2 source переживает Redis save/get"}


def main() -> int:
    emit("=" * 100)
    emit("ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ PROGR-25-A-CERT -- задача A "
         "(spec_progress_target_column.md §4-A)")
    emit("Свой датасет: energy_hourly.csv (336 часовых точек; ts/load; "
         "варианты v2 price, v3 year, v4 load_detrended, v6 без числовых)")
    emit("=" * 100)
    group_a()
    group_b()
    group_c()
    group_d()
    passed = sum(1 for _, ok in _checks if ok)
    failed = [label for label, ok in _checks if not ok]
    expected_hits = [label for label in failed if label in EXPECTED_FAILS]
    unexpected = [label for label in failed if label not in EXPECTED_FAILS]
    emit("")
    emit("=" * 100)
    emit(f"ИТОГ ОРАКУЛОВ: {passed}/{len(_checks)} PASS "
         f"(expected-FAIL: {expected_hits} "
         "-- доказательства находки F1)")
    if unexpected:
        emit(f"НЕОЖИДАННЫЕ FAIL: {unexpected}")
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"Протокол: {OUT}")
    return 0 if not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main())
