#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ задачи C (spec_status_original_series.md,
Task PROGR-24-ORIGIN-C: правило Наставника derived_spikes + фиксация решения
«производные колонки вне контура статусов» в spec_progress.md §3.2).

Принципы сертификации (прецеденты PROGR-17/18/20/21/24-CERT):
  - данные СВОИ, не пересекающиеся с данными разработчика (g345-подобный
    кадр, n150, позиции [25,70,105,130]) и с оракулами прошлых сертификаций
    (retail_daily, 364 точки, позиции [25,70,105,130]);
  - оракулы НЕ копируют ассерты test_mentor_rules.py, а перекрывают их
    другими углами атаки: decoy-колонка исходной области с
    «производноподобным» именем И реальными всплесками (совет обязан
    молчать -- скоуп задаётся РЕЕСТРОМ задачи A, не суффиксом имени);
    ДВЕ производные колонки (гладкая + всплесковая) -- проверка
    пер-колоночной агрегации по производной области; независимый
    IQR-пересчёт СВОИМ кодом; порядок слияния history→session; журнал
    наблюдений и трасса не получают от совета НИЧЕГО; контракт ответа
    не растёт; спецификация §3.2 несёт решение дословно.

СВОЙ датасет -- energy_monthly.csv, 240 точек (20 лет, месяц):
date / consumption / temperature / consumption_diff (ПРИМАНКА -- исходная
колонка с «производноподобным» именем, загружена из ФАЙЛА, со СВОИМИ
всплесками на позициях [50,120,180]; реестр обязан считать её ИСХОДНОЙ --
совет derived_spikes по ней НЕ срабатывает). consumption: тренд + годовая
сезонность + 4 всплеска на позициях [33,78,141,199] (±90/80/75/-110) --
позиции и форма не совпадают ни с данными разработчика, ни с retail-оракулом
задачи A. temperature -- гладкий независимый предиктор.

Группы:
  A -- движок app/core/mentor_rules.py на своих фактах (9);
  B -- живой API + роутер на своём потоке (10);
  C -- фиксация решения в spec_progress.md §3.2 + периметр коммита (4).

Правила AGENTS.md: только измерение, без commit/push.
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Тихий протокол: шум FastAPI/multipart/psycopg не относится к предмету аудита.
logging.disable(logging.WARNING)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ── Канонические модули платформы (носители проверяемого поведения) ──
from app.core import mentor_rules  # noqa: E402
from app.preprocessing.outliers import (  # noqa: E402
    outliers_summary,
    profile_outliers,
)
from apps.api import research_runs  # noqa: E402
from apps.api.column_origin import (  # noqa: E402
    derived_columns_in_frame,
    register_derived_columns,
    scope_frame,
)
from apps.api.main import app  # noqa: E402
from apps.api.routers.progress import _derived_spikes_facts  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    DatasetInfo,
    get_session_store,
)
from apps.api.trace_events import make_trace_event  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []  # (група, имя, статус)


def check(group: str, name: str, fn) -> None:
    """Один оракул: PASS/FAIL с телом исключения в протоколе."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((group, name, f"FAIL: {type(exc).__name__}: {exc}"))
    else:
        RESULTS.append((group, name, "PASS"))


# ── СВОИ данные ──────────────────────────────────────────────────────

SPIKES_CANON = {33: 120.0, 78: 110.0, 141: 95.0, 199: -135.0}
SPIKES_DECOY = {50: 40.0, 120: -50.0, 180: 35.0}
N = 240


def energy_frame() -> pd.DataFrame:
    """Основной кадр: consumption со всплесками, temperature гладкая,
    consumption_diff -- ПРИМАНКА (исходная колонка со всплесками)."""
    t = np.arange(N, dtype=float)
    cons = 500.0 + 0.9 * t + 12.0 * np.sin(2.0 * np.pi * (t + 3.0) / 12.0)
    for pos, amp in SPIKES_CANON.items():
        cons[pos] += amp
    temp = 15.0 + 12.0 * np.sin(2.0 * np.pi * t / 12.0)
    decoy = 6.0 * np.sin(2.0 * np.pi * t / 7.0)
    for pos, amp in SPIKES_DECOY.items():
        decoy[pos] += amp
    dates = pd.date_range("2005-01-01", periods=N, freq="MS")
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "consumption": np.round(cons, 2),
            "temperature": np.round(temp, 2),
            "consumption_diff": np.round(decoy, 2),
        }
    )


def smooth_frame() -> pd.DataFrame:
    """Кадр без всплесков: плавный тренд + мягкая сезонность; первая
    разность ограничена (производная есть, всплесков нет)."""
    t = np.arange(N, dtype=float)
    value = 200.0 + 0.4 * t + 8.0 * np.sin(2.0 * np.pi * t / 12.0)
    dates = pd.date_range("2010-01-01", periods=N, freq="MS")
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )


def my_iqr_count(values: np.ndarray | pd.Series) -> int:
    """НЕЗАВИСИМАЯ реализация IQR-профиля (шкала карточки: 1.5*IQR,
    строгое неравенство, NaN не флагаются) -- семантика по докстрингу
    app/preprocessing/outliers.py, код мой (не вызов платформенного)."""
    s = pd.Series(values).dropna()
    if len(s) < 20:  # _MIN_SAMPLE_SIZE платформы
        return 0
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    return int(((s < lo) | (s > hi)).sum())


def facts_of(total: int) -> dict:
    return {
        "total_outliers": total,
        "total_columns": 1,
        "total_numeric_columns": 1,
        "affected_columns": ["probe"],
    }


# ── Группа A: движок (mentor_rules) на своих фактах ─────────────────


def a1_fires_strict_int() -> None:
    """Срабатывание на строгом int > 0 (своё значение 7): severity=info,
    suggested_action=None, контекст несёт РОВНО факт."""
    fact = mentor_rules.rule_derived_spikes(facts_of(7))
    assert fact is not None, "int>0 обязан сжечь правило"
    assert fact.severity == "info"
    assert fact.suggested_action is None
    assert fact.context == {"total_outliers": 7}


def a2_silence_matrix_extended() -> None:
    """Расширенная матрица тишины -- классы, которых НЕТ в тестах
    разработчика: float 7.0 (целочисленное значение, но не int),
    np.int64(7), float 0.0, пустая строка, dict-значение, отсутствующий
    ключ, огромный int 10**18 (presence-проверка без верхней границы --
    ОБЯЗАН сработать)."""
    for garbage in (
        {"total_outliers": 7.0},
        {"total_outliers": np.int64(7)},
        {"total_outliers": 0.0},
        {"total_outliers": ""},
        {"total_outliers": {"a": 1}},
        {},
        None,
    ):
        assert mentor_rules.rule_derived_spikes(garbage) is None, garbage
    big = mentor_rules.rule_derived_spikes({"total_outliers": 10**18})
    assert big is not None and big.context["total_outliers"] == 10**18


def a3_bool_trap() -> None:
    """Ловушка истинности: True -- truthy и isinstance(True, int)==True,
    но bool обязан быть отсечён (правило не срабатывает на флаге)."""
    assert mentor_rules.rule_derived_spikes({"total_outliers": True}) is None
    assert mentor_rules.rule_derived_spikes({"total_outliers": False}) is None


def a4_registry_shape() -> None:
    """Реестр SESSION_ADVICE_RULES: ровно одно правило derived_spikes,
    поля реестра соответствуют спеке (stage/trigger/priority/action)."""
    rules = mentor_rules.SESSION_ADVICE_RULES
    assert len(rules) == 1, f"реестр сессионных советов: {len(rules)} правил"
    rule = rules[0]
    assert rule.rule_id == "derived_spikes"
    assert rule.stage == "preprocessing"
    assert rule.trigger == mentor_rules.TRIGGER_ON_DEMAND_WITH_SESSION
    assert rule.recommended_action is None, "без deep-link (два пути)"
    assert rule.condition is not None
    assert isinstance(rule.priority, int)


def a5_known_triggers_exact() -> None:
    """KNOWN_TRIGGERS -- ровно 4 триггера, новый -- четвёртый вид."""
    assert mentor_rules.KNOWN_TRIGGERS == frozenset(
        {
            mentor_rules.TRIGGER_ON_DEMAND,
            mentor_rules.TRIGGER_ON_CORRECTION_RESULT,
            mentor_rules.TRIGGER_ON_DEMAND_WITH_HISTORY,
            mentor_rules.TRIGGER_ON_DEMAND_WITH_SESSION,
        }
    )


def a6_template_shape_and_format() -> None:
    """Шаблон: оба пути спеки + ровно одинарная подстановка (двойные
    фигурные скобки сломали бы .format); render даёт число в тексте."""
    rule = mentor_rules.SESSION_ADVICE_RULES[0]
    tpl = rule.explanation_template
    assert "STL" in tpl and "«Выбросы»" in tpl, "путь (а)"
    assert "«Структурные сдвиги»" in tpl and "Box–Tiao" in tpl, "путь (б)"
    assert tpl.count("{total_outliers}") == 1, "ровно одинарная подстановка"
    mentor_rules.validate_explanation_template(rule)  # не бросает
    text = mentor_rules.DEFAULT_TEXT_RENDERER.render(rule, {"total_outliers": 7})
    assert "7" in text and "{" not in text, "подстановка честная, без остатка"


def a7_determinism_and_no_input_mutation() -> None:
    """Детерминизм (два вызова -- одинаковый результат) и чистота:
    входной mapping не мутируется."""
    facts = facts_of(5)
    snapshot = dict(facts)
    w1 = mentor_rules.evaluate_session_advice(facts)
    w2 = mentor_rules.evaluate_session_advice(facts)
    assert len(w1) == len(w2) == 1
    assert w1[0].message == w2[0].message
    assert w1[0].rule_id == w2[0].rule_id == "derived_spikes"
    assert facts == snapshot, "вход не мутируется"


def a8_renderer_protocol_spy() -> None:
    """§8 через СВОЙ шпион: renderer вызывается РОВНО ОДИН раз при
    срабатывании (rule, context), ноль раз при тишине; message -- вывод
    renderer, а не шаблон (текст собирается движком ЧЕРЕЗ Protocol)."""
    calls: list[tuple[str, dict]] = []

    class Spy:
        def render(self, rule, context):
            calls.append((rule.rule_id, dict(context)))
            return "СОВЕТ-СТАБ"

    fired = mentor_rules.evaluate_session_advice(facts_of(3), renderer=Spy())
    assert len(fired) == 1 and fired[0].message == "СОВЕТ-СТАБ"
    assert calls == [("derived_spikes", {"total_outliers": 3})]
    calls.clear()
    silent = mentor_rules.evaluate_session_advice(facts_of(0), renderer=Spy())
    assert silent == [] and calls == []


def a9_no_trace_sideeffects_from_engine() -> None:
    """Совет -- не факт: движок не пишет трассу. Поведенчески -- вызов
    evaluate_session_advice не меняет хранилище запуска (список событий
    пуст до/после); структурно -- модуль mentor_rules не импортирует
    хранилища/хук трассы (канон «правила -- чистые функции»)."""
    store = research_runs.get_research_run_store()
    store.upsert_run(
        research_runs.ResearchRun(
            run_id="CERT-A9", session_id=None, dataset_fingerprint="a" * 64,
            dataset_name="a.csv", created_at=_now(), last_active_at=_now(),
        )
    )
    before = store.list_events("CERT-A9")
    mentor_rules.evaluate_session_advice(facts_of(9))
    assert store.list_events("CERT-A9") == before
    src = Path(mentor_rules.__file__).read_text(encoding="utf-8")
    import_lines = [
        ln.strip() for ln in src.splitlines()
        if ln.strip().startswith(("import ", "from "))
    ]
    for banned in ("session_store", "research_runs", "trace_hook", "routers"):
        assert not any(ln.startswith((f"import {banned}", f"from {banned}")) for ln in import_lines), (
            f"движок импортирует {banned} -- не чистая функция"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Группа B: живой API + роутер на своём потоке ─────────────────────


def _upload(c: TestClient, frame: pd.DataFrame, name: str) -> None:
    r = c.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text


def _stationarity(c: TestClient, column: str) -> str:
    """Честный UI-поток стационарности: profile → selected_method →
    preview→apply (apply=true; без preview кнопка disabled). Возвращает
    имя добавленной производной колонки (разность списков колонок)."""
    prof = c.get(
        f"/v1/session/dataset/preprocessing/stationarity-profile?column={column}"
    ).json()
    method = prof["profile"].get("selected_method") or "first_difference"
    r = c.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        json={"column": column, "method": method, "apply": True, "confirm_non_causal": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    out_col = body.get("output_column")
    assert out_col, f"apply без output_column: {list(body)}"
    return str(out_col)


def _seed_run_for_cookie(c: TestClient, run_id: str) -> None:
    """Запуск слоя 2, связанный с РЕАЛЬНОЙ cookie-сессией клиента."""
    from apps.api.session_store import SESSION_COOKIE_NAME

    session_id = c.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "нет cookie сессии"
    research_runs.get_research_run_store().upsert_run(
        research_runs.ResearchRun(
            run_id=run_id, session_id=session_id,
            dataset_fingerprint="b" * 64, dataset_name="energy_monthly.csv",
            created_at=_now(), last_active_at=_now(),
        )
    )


def _warnings_map(c: TestClient, run_id: str) -> tuple[dict, dict]:
    r = c.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert r.status_code == 200, r.text
    data = r.json()
    return data, {w["rule_id"]: w for w in data["history_warnings"]}


def b1_fires_and_triple_agreement() -> None:
    """ПОЛНЫЙ честный поток: загрузка energy_monthly → стационарность →
    совет derived_spikes (info) в next-step; ТРОЙНОЕ согласие числа:
    текст совета == derived_summary GET-профиля == МОЯ независимая
    IQR-агрегация по per-колоночным фактам derived_summary."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    derived = _stationarity(c, "consumption")
    _seed_run_for_cookie(c, "RUN-CERT-B1")

    profile = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    ds = profile.get("derived_summary") or {}
    assert ds.get("total_outliers", 0) > 0, "производная обязана нести всплески"
    per_column_sum = sum(col["outlier_count"] for col in ds.get("columns", []))
    assert per_column_sum == ds["total_outliers"], "агрегат == сумме колонок"

    data, wmap = _warnings_map(c, "RUN-CERT-B1")
    assert "derived_spikes" in wmap, "совет обязан появиться"
    advice = wmap["derived_spikes"]
    assert advice["severity"] == "info"
    assert advice["suggested_action"] is None
    assert str(ds["total_outliers"]) in advice["message"], advice["message"]
    assert f"всплесков: {ds['total_outliers']}" in advice["message"]
    assert derived, "имя производной получено"


def b2_decoy_original_named_derived() -> None:
    """ПРИМАНКА скоупа: consumption_diff -- ИСХОДНАЯ колонка с
    «производноподобным» именем и РЕАЛЬНЫМИ всплесками -- НЕ даёт
    совета (реестр пуст); каноническая карточка при этом честно жёлтая
    по исходной области. Скоуп задаётся реестром задачи A, не суффиксом."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    _seed_run_for_cookie(c, "RUN-CERT-B2")
    card = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    affected = {x["column"] for x in card["columns"] if x["outlier_count"] > 0}
    assert card["total_outliers"] == len(SPIKES_DECOY), "приманка должна флагаться в карточке"
    assert "consumption_diff" in affected, "всплески приманки -- в исходной области"
    assert card.get("derived_summary") is None or (
        card["derived_summary"].get("total_outliers", 0) == 0
    ), "производных нет"
    _, wmap = _warnings_map(c, "RUN-CERT-B2")
    assert "derived_spikes" not in wmap, "совет по приманке -- УТЕЧКА скоупа"


def b3_silent_clean_flow() -> None:
    """Гладкий ряд: производная ЕСТЬ (реестр зарегистрирован), всплесков
    НЕТ -- совета нет; derived_summary == 0."""
    c = TestClient(app)
    _upload(c, smooth_frame(), "smooth.csv")
    _stationarity(c, "value")
    _seed_run_for_cookie(c, "RUN-CERT-B3")
    profile = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    ds = profile.get("derived_summary") or {}
    assert ds.get("total_outliers", 0) == 0
    _, wmap = _warnings_map(c, "RUN-CERT-B3")
    assert "derived_spikes" not in wmap


def b4_best_effort_degradation() -> None:
    """Best-effort через живой API: run.session_id → несуществующая
    сессия -- 200, совета нет; run без session_id вовсе -- 200, совета
    нет (два своих варианта деградации, не 500)."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    _stationarity(c, "consumption")
    store = research_runs.get_research_run_store()
    for run_id, sid in (("RUN-CERT-B4G", "ghost-cert-session"), ("RUN-CERT-B4N", "")):
        store.upsert_run(
            research_runs.ResearchRun(
                run_id=run_id, session_id=sid, dataset_fingerprint="c" * 64,
                dataset_name="x.csv", created_at=_now(), last_active_at=_now(),
            )
        )
        data, wmap = _warnings_map(c, run_id)
        assert "derived_spikes" not in wmap, run_id
        assert "phase_text" in data and "recommendation" in data, "ядро ответа живо"


def b5_facts_projection_invariants() -> None:
    """Проекция фактов (прямой вызов _derived_spikes_facts): состав
    ключей, total_columns == len(производных), affected_columns ⊆
    производных, total_outliers == МОЙ независимый IQR-пересчёт по
    производной области."""
    df = energy_frame()
    session = AnalysisSession(session_id="cert-b5")
    session.set_dataset(
        DatasetInfo(
            dataset_id="d-b5", name="energy_monthly.csv", rows=len(df),
            columns=len(df.columns), size_label="2 КБ", dataset_fingerprint="d" * 64,
        ),
        df,
    )
    before = list(session.dataframe.columns)
    # производные: детренд + нормированная колонка + МЯГКИЙ выброс
    # (вне 1.5-забора, внутри 3.0-забора -- различитель шкалы карточки:
    # подмена param=3.0 в носителе факта обязана быть поймана);
    # добавляю их В КАДР СЕССИИ (реестр сравнивает списки колонок кадра)
    t = np.arange(len(session.dataframe), dtype=float)
    session.dataframe["cons_detrended"] = np.round(
        session.dataframe["consumption"] - (500.0 + 0.9 * t), 2
    )
    session.dataframe["temp_scaled"] = np.round(session.dataframe["temperature"] * 0.1, 2)
    mild = np.round(5.0 * np.sin(2.0 * np.pi * t / 12.0), 2)
    mild[100] += 15.0  # 1.5-забор ≈ ±11.8 -> 15 вне; 3.0-забор ≈ ±20.7 -> 15 внутри (различитель шкал)
    session.dataframe["d_mild"] = mild
    register_derived_columns(
        session, before_columns=before, stage="stationarity", source="cert"
    )
    get_session_store().save(session)
    run = research_runs.ResearchRun(run_id="RUN-CERT-B5", session_id="cert-b5")
    facts = _derived_spikes_facts(run)
    assert facts is not None
    assert set(facts) == {
        "total_outliers", "total_columns", "total_numeric_columns", "affected_columns",
    }
    derived_names = derived_columns_in_frame(session)
    assert set(derived_names) == {"cons_detrended", "temp_scaled", "d_mild"}
    assert facts["total_columns"] == 3
    assert facts["total_numeric_columns"] == 3
    assert set(facts["affected_columns"]) <= set(derived_names)
    assert "d_mild" in facts["affected_columns"], "мягкий выброс обязаны считать по 1.5"
    scoped = scope_frame(session.dataframe, derived_names)
    mine = sum(my_iqr_count(scoped[col]) for col in derived_names)
    assert mine == 5, f"калибровка своих данных сломалась: mine={mine}"
    assert facts["total_outliers"] == mine, (
        f"факты {facts['total_outliers']} != мой пересчёт {mine}"
    )


def b6_two_derived_per_column_aggregation() -> None:
    """ОСТРЫЙ скоуп-оракул: ДВЕ производные (гладкая + всплесковая) и
    всплески канона -- факты считают ТОЛЬКО всплесковую производную;
    affected_columns == [всплесковая]; канонические и приманочные
    всплески не просачиваются."""
    df = energy_frame()
    session = AnalysisSession(session_id="cert-b6")
    session.set_dataset(
        DatasetInfo(
            dataset_id="d-b6", name="frame.csv", rows=len(df),
            columns=3, size_label="2 КБ", dataset_fingerprint="e" * 64,
        ),
        df.copy(),
    )
    # производные добавляю В КАДР СЕССИИ ПОСЛЕ set_dataset (реестр
    # сравнивает списки колонок кадра до/после)
    t = np.arange(len(session.dataframe), dtype=float)
    before = list(session.dataframe.columns)
    session.dataframe["d_smooth"] = np.round(5.0 * np.sin(2.0 * np.pi * t / 12.0), 2)
    d_spiky = np.round(5.0 * np.sin(2.0 * np.pi * t / 12.0), 2)
    for pos, amp in ((70, 60.0), (150, -70.0), (210, 55.0)):
        d_spiky[pos] += amp
    session.dataframe["d_spiky"] = d_spiky
    register_derived_columns(
        session, before_columns=before, stage="stationarity", source="cert"
    )
    get_session_store().save(session)
    facts = _derived_spikes_facts(
        research_runs.ResearchRun(run_id="RUN-CERT-B6", session_id="cert-b6")
    )
    assert facts is not None
    mine = my_iqr_count(session.dataframe["d_spiky"])
    assert facts["total_outliers"] == mine == 3, facts
    assert facts["affected_columns"] == ["d_spiky"], facts
    assert facts["total_columns"] == 2


def b7_merge_order_history_then_session() -> None:
    """Детерминированный порядок слияния: history_warnings ==
    [*evaluate_history_warnings, *session advice]. Сею СВОИ 3 preview
    события с разными стратегиями (thrashing) поверх потока с
    производными всплесками -- в ответе thrashing_detected СТРОГО РАНЬШЕ
    derived_spikes, оба присутствуют (слияние, не замещение)."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    _stationarity(c, "consumption")
    _seed_run_for_cookie(c, "RUN-CERT-B7")
    store = research_runs.get_research_run_store()
    for i, strategy in enumerate(("median_mode", "mean_mode", "flag")):
        store.append_event(
            "RUN-CERT-B7",
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-CERT-B7", actor="cert",
                strategy=strategy, ts=_now(),
            ),
        )
        assert i >= 0
    data, wmap = _warnings_map(c, "RUN-CERT-B7")
    ids = [w["rule_id"] for w in data["history_warnings"]]
    assert "thrashing_detected" in ids and "derived_spikes" in ids, ids
    assert ids.index("thrashing_detected") < ids.index("derived_spikes"), ids


def b8_no_trace_events_from_advice() -> None:
    """Совет не пишет трассу: число событий слоя 2 до/после next-step
    (с сработавшим советом) -- НЕИЗМЕННО; ни одного события с
    event_type, производным от совета."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    _stationarity(c, "consumption")
    _seed_run_for_cookie(c, "RUN-CERT-B8")
    store = research_runs.get_research_run_store()
    _, wmap = _warnings_map(c, "RUN-CERT-B8")
    assert "derived_spikes" in wmap, "совет должен быть в этом потоке"
    before = len(store.list_events("RUN-CERT-B8"))
    _warnings_map(c, "RUN-CERT-B8")
    _warnings_map(c, "RUN-CERT-B8")
    assert len(store.list_events("RUN-CERT-B8")) == before, "совет сеет события"


def b9_observations_journal_silent_for_advice() -> None:
    """Журнал наблюдений (§10) от совета НЕ растёт: до/после next-step
    с советом -- ни одного MentorObservation c rule_id=derived_spikes;
    прирост (если рекомендация выдана) -- только obs_kind=next_step."""
    c = TestClient(app)
    _upload(c, energy_frame(), "energy_monthly.csv")
    _stationarity(c, "consumption")
    _seed_run_for_cookie(c, "RUN-CERT-B9")
    store = research_runs.get_research_run_store()
    obs_before = store.list_mentor_observations()
    _, wmap = _warnings_map(c, "RUN-CERT-B9")
    assert "derived_spikes" in wmap
    obs_after = store.list_mentor_observations()
    assert not any(
        o.rule_id == "derived_spikes" for o in obs_after
    ), "совет попал в журнал наблюдений"
    new = [o for o in obs_after if o not in obs_before]
    assert all(o.obs_kind == "next_step" for o in new), new


def b10_contract_shape_and_core_stability() -> None:
    """Контракт ответа не растёт: множество top-level ключей next-step
    одинаково в потоках С советом и БЕЗ; элемент history_warnings имеет
    ровно 4 поля; ядро (statuses/stages/phase_text) стабильно между
    вызовами; совет идемпотентен (3 вызова -- одинаковый текст)."""
    c1 = TestClient(app)
    _upload(c1, energy_frame(), "energy_monthly.csv")
    _stationarity(c1, "consumption")
    _seed_run_for_cookie(c1, "RUN-CERT-B10A")
    c2 = TestClient(app)
    _upload(c2, smooth_frame(), "smooth.csv")
    _stationarity(c2, "value")
    _seed_run_for_cookie(c2, "RUN-CERT-B10B")

    d1, w1 = _warnings_map(c1, "RUN-CERT-B10A")
    d2, w2 = _warnings_map(c2, "RUN-CERT-B10B")
    assert set(d1) == set(d2), "контракт ответа вырос"
    assert "derived_spikes" in w1 and "derived_spikes" not in w2
    for w in (w1["derived_spikes"], *d2["history_warnings"]):
        assert set(w) == {"rule_id", "severity", "message", "suggested_action"}
    msg1 = w1["derived_spikes"]["message"]
    core_keys = (
        "run_id", "run_status", "last_active_stage", "phase_text",
        "summary", "recommendation", "history_warnings",
    )
    for k in core_keys:
        assert k in d1 and k in d2, k
    for _ in range(2):
        d1b, w1b = _warnings_map(c1, "RUN-CERT-B10A")
        assert w1b["derived_spikes"]["message"] == msg1, "совет неидемпотентен"
        assert d1b["phase_text"] == d1["phase_text"], "фаза поплыла"
        assert d1b["summary"] == d1["summary"], "свод поплыл"
        assert d1b["recommendation"] == d1["recommendation"], "рекомендация поплыла"


# ── Группа C: фиксация решения в spec_progress.md §3.2 + периметр ────


def _spec_text() -> str:
    return (REPO / "spec_progress.md").read_text(encoding="utf-8")


def c1_spec_paragraph_exists_in_32() -> None:
    """Абзац PROGR-24-ORIGIN-C присутствует ВНУТРИ §3.2 (между заголовком
    §3.2 и следующим разделом «## 4») и несёт ключевые узлы решения."""
    text = _spec_text()
    start = text.index("### 3.2")
    end = text.index("## 4.", start)
    section = text[start:end]
    assert "PROGR-24-ORIGIN-C" in section, "абзац задачи C не в §3.2"
    for marker in (
        "вне контура статусов",
        "on_demand_with_session",
        "derived_spikes",
        "Box–Tiao",
        "«Структурные сдвиги»",
        "derived_summary",
        "iqr-1.5",
    ):
        assert marker in section, f"в §3.2 нет узла: {marker}"


def c2_spec_decision_recorded_as_final() -> None:
    """Решение записано ЯВНО и финально: «фиксируется явно», «не вводится»
    (новый статус), совет в трассу не попадает, наблюдения не пишутся."""
    text = _spec_text()
    start = text.index("PROGR-24-ORIGIN-C")
    end = text.index("## 4.", start)
    section = text[start:end]
    assert "фиксируется явно" in section
    assert "не вводится" in section, "новый статус не введён -- записано?"
    assert "в трассу не попадает" in section
    assert "не пишется" in section, "журнал наблюдений молчит -- записано?"
    assert "DAG" in section, "однонаправленность пайплайна -- записано?"


def c3_commit_perimeter_exact() -> None:
    """Периметр коммита d2d9732 -- ровно 7 файлов задачи C: НИ одного
    .ts/.tsx (фронт не менялся), НИ одного trace-файла (трасса не менялась),
    НИ одного rules/*.yaml (порог не вводился)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "23c5068..d2d9732"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    expected = {
        "app/core/mentor_rules.py",
        "apps/api/routers/progress.py",
        "spec_progress.md",
        "tests/api/test_mentor_rules.py",
        "worklog/worklog9.md",
        "scripts/progr24c_mutation_check.sh",
        "scripts/progr24c_mutation_results.txt",
    }
    assert set(out) == expected, f"периметр коммита неожиданный: {sorted(set(out) ^ expected)}"
    assert not any(f.endswith((".ts", ".tsx")) for f in out)
    assert not any(f.startswith("rules/") for f in out)
    assert "apps/api/trace_hook.py" not in out and "app/core/node_status.py" not in out


def c4_no_threshold_yaml_and_no_loader_change() -> None:
    """rules/mentor.yaml не содержит derived-порога (presence-проверка
    без калибруемой константы -- канон rule_no_effect); в рабочем дереве
    файл не менялся относительно родителя."""
    yml = (REPO / "rules" / "mentor.yaml").read_text(encoding="utf-8")
    assert "derived" not in yml.lower(), "derived-порог просочился в YAML"
    out = subprocess.run(
        ["git", "diff", "--name-only", "23c5068..d2d9732", "--", "rules/"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert out == [], "rules/ менялся в коммите задачи C"


# ── Runner ───────────────────────────────────────────────────────────

def main() -> int:
    oracles = [
        ("A", "A1 strict int>0 fires (own value 7)", a1_fires_strict_int),
        ("A", "A2 extended silence matrix (7.0/np.int64/0.0/str/dict/missing/10**18)", a2_silence_matrix_extended),
        ("A", "A3 bool truthiness trap", a3_bool_trap),
        ("A", "A4 registry shape (1 rule, fields)", a4_registry_shape),
        ("A", "A5 KNOWN_TRIGGERS exact 4", a5_known_triggers_exact),
        ("A", "A6 template both paths + single placeholder + format", a6_template_shape_and_format),
        ("A", "A7 determinism + input not mutated", a7_determinism_and_no_input_mutation),
        ("A", "A8 renderer Protocol spy (§8)", a8_renderer_protocol_spy),
        ("A", "A9 engine purity: no store/trace side-effects", a9_no_trace_sideeffects_from_engine),
        ("B", "B1 full flow fires + triple number agreement", b1_fires_and_triple_agreement),
        ("B", "B2 decoy original 'consumption_diff' silent", b2_decoy_original_named_derived),
        ("B", "B3 clean flow: derived w/o spikes silent", b3_silent_clean_flow),
        ("B", "B4 best-effort: ghost/no session -> 200, no advice", b4_best_effort_degradation),
        ("B", "B5 facts projection + independent IQR recomposition", b5_facts_projection_invariants),
        ("B", "B6 two derived: per-column aggregation sharp scope", b6_two_derived_per_column_aggregation),
        ("B", "B7 merge order: history then session advice", b7_merge_order_history_then_session),
        ("B", "B8 no trace events from advice", b8_no_trace_events_from_advice),
        ("B", "B9 observations journal silent for advice", b9_observations_journal_silent_for_advice),
        ("B", "B10 contract not grown + core stability + idempotence", b10_contract_shape_and_core_stability),
        ("C", "C1 spec §3.2 paragraph with decision nodes", c1_spec_paragraph_exists_in_32),
        ("C", "C2 decision recorded as final", c2_spec_decision_recorded_as_final),
        ("C", "C3 commit perimeter exactly 7 files", c3_commit_perimeter_exact),
        ("C", "C4 no threshold in rules/mentor.yaml", c4_no_threshold_yaml_and_no_loader_change),
    ]
    for group, name, fn in oracles:
        check(group, name, fn)

    print("=" * 78)
    print("ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ PROGR-24-ORIGIN-C (свои данные)")
    print("=" * 78)
    fails = 0
    current = ""
    for group, name, status in RESULTS:
        if group != current:
            print(f"--- Группа {group} ---")
            current = group
        mark = "PASS" if status == "PASS" else "!!"
        print(f"[{mark}] {name}" + ("" if status == "PASS" else f"  -> {status}"))
        if status != "PASS":
            fails += 1
    total = len(RESULTS)
    print("=" * 78)
    print(f"ИТОГ: {total - fails}/{total} PASS, {fails} FAIL")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
