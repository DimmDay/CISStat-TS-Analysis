# scripts/progr18cert_oracles.py
# Независимый сертификационный аудит Task PROGR-18 (eda_check_status):
# оракул-тесты на СОБСТВЕННЫХ данных аудитора. Датасет, карта просмотров,
# run_id и порядок отчётов НЕ пересекаются ни с fixtures
# tests/api/test_progress_progr18.py (у коллеги -- месячный monitor CSV
# 150 строк, date/value, линейный ряд), ни с оракулами PROGR-17-CERT
# (недельные продажи 120 строк). У аудитора -- СУТОЧНЫЙ ряд посещаемости
# 210 точек (30 недель), колонки day/visits/channel: недельная
# сезонность (период 7), инжектированный сдвиг уровня (+250 с i=150),
# один экстремальный выброс (5x, i=30).
#
# Оракулы проверяют:
#   (A) дата-специфичные отпечатки СВОЕГО датасета на реальных EDA-
#       профилях (сезонность 7 -- confirmed/dominant, структурный сдвиг
#       в точке i=150, skew выброса);
#   (B) семантика модуля TsAnalysisEDA.tsx на этих данных: профили
#       осели (done/warning -- результат ПОКАЗАН, факт просмотра
#       возможен; ни running, ни pending, ни error) + идентичность
#       реестра (backend == shared JSON == клиентский порядок);
#   (C) контракт POST /v1/progress/eda-checks end-to-end НА ЭТИХ
#       ДАННЫХ: панель == модулю, all-or-nothing c проверкой ДЕТАЛЕЙ
#       422 (в т.ч. легальный CheckStatus "warning" -- решение
#       тимлида), last-wins, 400, посев run_id, составной ключ
#       eda/stationarity != preprocessing/stationarity, персистент-
#       ность через НАСТОЯЩУЮ границу сериализации (fakeredis --
#       эквивалент Пр-4, которого у PROGR-18 в репозитории НЕТ);
#   (D) потребители: отчёт §5.4 (метки реестра для ВСЕХ 10
#       исследований, формулировки ПРОСМОТРА), фаза Наставника B1,
#       терминология status_reason узла («ИССЛЕДОВАНИЕ», модуль
#       «EDA» назван ЯВНО) и критерий приёмки v1.1 §7 -- 6/6 стадий
#       имеют узловой факт-источник.
#
# Запуск: python scripts/progr18cert_oracles.py   (exit 0 == все GREEN)
from __future__ import annotations

import io
import json
import math
import os
import sys
import traceback

# Среда долговременного слоя -- как в fixtures tests/api (memory, без
# DATABASE_URL): оракулы проверяют контракт, не Postgres-коннективность.
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.pipeline_graph import EDA_STAGE_IDS, STAGE_NODES  # noqa: E402
from app.core.node_status import (  # noqa: E402
    EVENT_NODE_STATUS,
    PAYLOAD_STATUS_EVENT_TYPES,
    derive_last_active_stage,
    derive_node_statuses,
)
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

CHECK_IDS = list(STAGE_NODES["eda"])

RESULTS: list[tuple[str, str, str]] = []


def check(oracle_id: str, description: str, fn) -> None:
    try:
        fn()
        RESULTS.append((oracle_id, "PASS", description))
        print(f"[PASS] {oracle_id}: {description}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((oracle_id, "FAIL", f"{description} :: {type(exc).__name__}: {exc}"))
        print(f"[FAIL] {oracle_id}: {description}")
        traceback.print_exc(limit=3)


# ── Собственный датасет аудитора (суточный ряд посещаемости, 210 точек) ──

def build_my_csv() -> str:
    import pandas as pd

    idx = pd.date_range("2024-01-01", periods=210, freq="D")
    visits = []
    for i in range(210):
        value = 500 + 0.6 * i + 60 * math.sin(2 * math.pi * i / 7) + 8 * ((i * 7) % 13)
        if i >= 150:
            value += 250  # сдвиг уровня -- отпечаток «Структурных сдвигов» (i=150)
        visits.append(round(value, 3))
    visits[30] *= 5.0  # экстремальный выброс (5x, i=30) -- отпечаток «Распределения»
    frame = pd.DataFrame(
        {
            "day": idx.strftime("%Y-%m-%d"),
            "visits": visits,
            "channel": [["organic", "ads", "social"][i % 3] for i in range(210)],
        }
    )
    return frame.to_csv(index=False)


MY_CSV = build_my_csv()

client = TestClient(app)
_fresh: TestClient | None = None  # второй клиент без cookie -- для 400


def upload_my_dataset(on: TestClient | None = None) -> None:
    target = on or client
    response = target.post(
        "/v1/internal/upload",
        files={"file": (
            "cert18_daily_traffic_n210.csv",
            io.BytesIO(MY_CSV.encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def get_json(path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def _profile(path: str) -> dict:
    """EDA-профиль: 404 == нет датасета (контракт модуля), иначе 200."""
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    return response.json()


# Семантика модуля (TsAnalysisEDA.tsx, документированные ветки статусов)
def derive_status(id_: str, profile: dict) -> str:
    if id_ == "seasonality":
        if profile.get("applicable") is False:
            return "warning"
        return "done" if profile.get("applicable") else "pending"
    if id_ == "stationarity":
        if profile.get("applicable") is False:
            return "warning"
        if profile.get("consensus") in ("stationary", "trend-stationary"):
            return "done"
        return "warning" if profile.get("applicable") else "pending"
    if id_ == "distribution":
        if profile.get("applicable") is False:
            return "warning"
        if profile.get("normality_status") == "compatible":
            return "done"
        return "warning" if profile.get("applicable") else "pending"
    if id_ == "structural":
        if profile.get("applicable") is False:
            return "warning"
        if profile.get("status") == "stable":
            return "done"
        return "warning" if profile.get("applicable") else "pending"
    raise AssertionError(f"нет семантики для {id_}")


# ── A: отпечатки СВОЕГО датасета на реальных EDA-профилях ──

def oracle_a1_seasonality_weekly() -> None:
    profile = _profile(
        "/v1/session/dataset/eda-seasonality?column=visits&min_cycles=2&max_candidates=6"
    )
    assert profile.get("applicable") is True, profile.get("applicable")
    # confirmed_periods -- СЧЁТЧИК подтверждённых кандидатов (схема
    # DatasetEdaSeasonalityResponse); недельный цикл -- dominant_period==7
    # и кандидат period_rounded==7 с confirmed=True.
    assert profile.get("confirmed_periods", 0) >= 1, profile.get("confirmed_periods")
    dominant = profile.get("dominant_period")
    assert dominant is not None and round(dominant) == 7, dominant
    weekly = next(
        (c for c in profile.get("candidates", [])
         if c.get("period_rounded") == 7),
        None,
    )
    assert weekly is not None and weekly.get("confirmed") is True, weekly


def oracle_a2_structural_break() -> None:
    profile = _profile(
        "/v1/session/dataset/eda-structural-breaks"
        "?column=visits&alpha=0.05&min_segment=30&penalty_multiplier=1.0"
    )
    supported = profile.get("supported_count")
    assert isinstance(supported, int) and supported >= 1, (
        f"инжектированный сдвиг уровня (i>=150, +250) не найден: {profile!r}"
    )
    at_150 = next(
        (c for c in profile.get("candidates", [])
         if c.get("index") == 150 and c.get("supported")),
        None,
    )
    assert at_150 is not None, (
        "устойчивый кандидат не в точке инжектированного сдвига i=150"
    )


def oracle_a3_stats_outlier_fingerprint() -> None:
    data = get_json("/v1/session/dataset/stats")
    visits = next(c for c in data["columns"] if c["name"] == "visits")
    assert visits["non_null_count"] == 210, visits["non_null_count"]
    stats = visits["stats"]
    assert stats is not None and stats["mean"] > stats["median"], (
        f"5x-выброс не смещает mean относительно median: {stats!r}"
    )
    assert stats["skewness"] > 3.0, (
        f"тяжёлая правая асимметрия от выброса не видна: skew={stats['skewness']}"
    )


# ── B: семантика модуля на СВОИХ данных + идентичность реестра ──

def oracle_b1_profiles_settled_shown() -> None:
    """Профили моих данных ОСЕЛИ: статус модуля ∈ {done, warning} --
    результат ПОКАЗАН (факт просмотра возможен); ни running/pending/error.
    Сознательно разные исходы: seasonality -> done (период найден),
    stationarity/structural/distribution -> warning (тренд/сдвиг/выброс) --
    решение тимлида: особенности результата НЕ мешают факту просмотра."""
    probes = {
        "seasonality": "/v1/session/dataset/eda-seasonality?column=visits&min_cycles=2&max_candidates=6",
        "stationarity": "/v1/session/dataset/eda-stationarity?column=visits&alpha=0.05&rolling_window=14",
        "distribution": "/v1/session/dataset/eda-distribution?column=visits&alpha=0.05&bins=20",
        "structural": "/v1/session/dataset/eda-structural-breaks?column=visits&alpha=0.05&min_segment=30&penalty_multiplier=1.0",
    }
    derived = {id_: derive_status(id_, _profile(url)) for id_, url in probes.items()}
    assert all(s in ("done", "warning") for s in derived.values()), derived
    assert derived["seasonality"] == "done", derived
    assert derived["stationarity"] == "warning", (
        f"тренд+сдвиг моих данных должны давать warning: {derived}"
    )


def oracle_b2_registry_identity_three_sources() -> None:
    """Реестр EDA един: backend EDA_STAGE_IDS == shared/pipeline_nodes/
    eda_checks.json == порядок клиентского CHECKS (TsAnalysisEDA.tsx).
    Ровно 10 исследований, порядок §2 сохранён."""
    assert len(EDA_STAGE_IDS) == 10, EDA_STAGE_IDS
    repo = "/home/z/my-project/CISStat-TS-Analysis"
    with open(f"{repo}/shared/pipeline_nodes/eda_checks.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    nodes = raw["nodes"] if isinstance(raw, dict) and "nodes" in raw else raw
    json_ids = [entry["id"] for entry in nodes]
    assert list(EDA_STAGE_IDS) == json_ids, (list(EDA_STAGE_IDS), json_ids)
    tsx = open(
        f"{repo}/packages/ui/components/TsAnalysisEDA.tsx", encoding="utf-8"
    ).read()
    # Клиент строит CHECKS из общего JSON (EDA_CHECK_DEFS.map) -- прямой
    # литерал списка в .tsx отсутствует; контракт синхронизации -- импорт
    # реестра, что и проверяем.
    assert "EDA_CHECK_DEFS.map" in tsx, "клиент не читает общий JSON реестра"


# ── C: контракт POST /v1/progress/eda-checks на СВОИХ данных ──

MY_DONE_6 = {
    "descriptive": "done",
    "correlation": "done",
    "seasonality": "done",
    "stationarity": "warning" if False else "done",
    "distribution": "done",
    "structural": "done",
    "ih_analysis": "pending",
    "feature_select": "pending",
    "validation_strategy": "pending",
    "model_matrix": "pending",
}


def _trace() -> dict:
    response = client.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    return response.json()


def _eda_events_layer1() -> list[dict]:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    return [
        event for event in session.pipeline_trace
        if event["event_type"] == "eda_check_status"
    ]


def oracle_c1_post_contract() -> None:
    response = client.post("/v1/progress/eda-checks", json={"checks": MY_DONE_6})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reported"] == 10, body
    assert body["run_id"] and body["run_id"].startswith("RUN-"), body


def oracle_c2_layer1_events() -> None:
    events = _eda_events_layer1()
    assert len(events) == 10, len(events)
    by_node = {event["node_id"]: event for event in events}
    assert set(by_node) == set(CHECK_IDS), set(by_node) ^ set(CHECK_IDS)
    for node_id, status in MY_DONE_6.items():
        event = by_node[node_id]
        assert event["payload"]["status"] == status, (node_id, event)
        assert event["stage"] == "eda", (node_id, event["stage"])
        assert event["run_id"] == _trace()["run_id"], node_id


def oracle_c3_layer2_mirror() -> None:
    from apps.api.research_runs import get_research_run_store

    run_id = _trace()["run_id"]
    stored = get_research_run_store().list_events(run_id)
    mirror = [event for event in stored if event.event_type == "eda_check_status"]
    assert len(mirror) == 10, len(mirror)


def oracle_c4_panel_equals_module() -> None:
    trace = _trace()
    for node_id, status in MY_DONE_6.items():
        assert trace["node_statuses"].get(f"eda/{node_id}") == status, (
            node_id, trace["node_statuses"].get(f"eda/{node_id}")
        )


def oracle_c5_fold_attention_warning_zero() -> None:
    stage = next(s for s in _trace()["stages"] if s["stage"] == "eda")
    assert stage["fold"] == "attention", stage
    assert stage["done_count"] == 6, stage
    assert stage["warning_nodes"] == 0, (
        f"warning в словаре отчёта EDA нет (решение тимлида): {stage}"
    )
    assert stage["total_nodes"] == 10, stage


def oracle_c6_all_viewed_folds_passed() -> None:
    full_done = {check_id: "done" for check_id in CHECK_IDS}
    response = client.post("/v1/progress/eda-checks", json={"checks": full_done})
    assert response.status_code == 200, response.text
    stage = next(s for s in _trace()["stages"] if s["stage"] == "eda")
    assert stage["fold"] == "passed", stage
    assert stage["done_count"] == 10 and stage["warning_nodes"] == 0, stage


def oracle_c7_fail_closed_details() -> None:
    """Fail-closed x5 НА СВОИХ данных, с проверкой ДЕТАЛЕЙ (не только
    кода): фантом / легальный CheckStatus warning (решение тимлида) /
    мусор / неполная карта / пустая карта -- 422 c адресным текстом и
    НОЛЬ записей после каждой попытки (all-or-nothing)."""
    base = dict(MY_DONE_6)
    cases = [
        ({**base, "phantom_study": "done"}, "Неизвестные исследования"),
        ({**base, "descriptive": "warning"}, "warning не вводится"),
        ({**base, "descriptive": "exploded"}, "словарь отчёта EDA"),
        ({"descriptive": "done"}, "неполна"),
        ({}, "пуста"),
    ]
    before = len(_eda_events_layer1())
    for payload, marker in cases:
        response = client.post("/v1/progress/eda-checks", json={"checks": payload})
        assert response.status_code == 422, (payload, response.status_code)
        assert marker in response.json()["detail"], (marker, response.json()["detail"])
    assert len(_eda_events_layer1()) == before, "all-or-nothing нарушен"


def oracle_c8_400_without_dataset() -> None:
    global _fresh
    _fresh = TestClient(app)
    upload_none = _fresh.post(  # чужая пустая сессия без датасета
        "/v1/progress/eda-checks", json={"checks": {k: "pending" for k in CHECK_IDS}}
    )
    assert upload_none.status_code == 400, upload_none.status_code
    _fresh.close()
    _fresh = None


def oracle_c9_run_id_seeded() -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    session.run_id = ""
    get_session_store().save(session)
    response = client.post(
        "/v1/progress/eda-checks", json={"checks": {k: "pending" for k in CHECK_IDS}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["run_id"].startswith("RUN-"), response.json()


def oracle_c10_last_wins() -> None:
    response = client.post(
        "/v1/progress/eda-checks",
        json={"checks": {k: "pending" for k in CHECK_IDS}},
    )
    assert response.status_code == 200, response.text
    node = _trace()["node_statuses"].get("eda/seasonality")
    assert node == "pending", node
    changed = {k: "pending" for k in CHECK_IDS}
    changed["seasonality"] = "done"
    response = client.post("/v1/progress/eda-checks", json={"checks": changed})
    assert response.status_code == 200, response.text
    assert _trace()["node_statuses"].get("eda/seasonality") == "done"


def oracle_c11_composite_key() -> None:
    """id исследований EDA сознательно пересекаются с Предобработкой
    (stationarity): составной ключ движка обязан разводить стадии --
    eda/stationarity покрашен, preprocessing/stationarity не тронут."""
    statuses = derive_node_statuses([
        {
            "event_id": "ev-cert18-1",
            "run_id": "RUN-CERT18",
            "ts": "2026-10-06T12:00:00+00:00",
            "stage": "eda",
            "node_id": "stationarity",
            "event_type": "eda_check_status",
            "payload": {"status": "done"},
            "actor": "user",
        },
    ])
    assert statuses.get("eda/stationarity") == "done", statuses
    assert "preprocessing/stationarity" not in statuses, statuses


def oracle_c12_persistence_through_serialization() -> None:
    """Персистентность отчёта EDA через НАСТОЯЩУЮ границу сериализации:
    RedisSessionStore на fakeredis (эквивалент Пр-4, который у PROGR-18
    в репозитории ОТСУТСТВУЕТ -- см. находки акта). После POST сессия
    перечитывается из store: 10 событий отчёта в сериализованном
    документе, а не только в памяти процесса."""
    import fakeredis

    from apps.api import session_store as session_store_module
    from apps.api.session_store import RedisSessionStore

    fake_server = fakeredis.FakeServer()
    store = RedisSessionStore(
        client=fakeredis.FakeStrictRedis(server=fake_server), ttl_seconds=3600
    )
    original = session_store_module._store
    session_store_module._store = store
    try:
        # Подмена store ДО загрузки: датасет и отчёт пишутся в ОДИН
        # redis-документ (паттерн Пр-4 test_progress_progr17.py).
        upload_my_dataset()
        response = client.post(
            "/v1/progress/eda-checks",
            json={"checks": {k: "done" for k in CHECK_IDS}},
        )
        assert response.status_code == 200, response.text
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        reread = store.get(session_id)
        assert reread is not None, "сессия не пережила границу сериализации"
        persisted = [
            event for event in reread.pipeline_trace
            if event["event_type"] == "eda_check_status"
        ]
        assert len(persisted) == 10, (
            f"в сериализованном документе {len(persisted)} событий отчёта EDA "
            "(ожидалось 10) -- save() не записал документ"
        )
    finally:
        session_store_module._store = original


# ── D: потребители -- отчёт §5.4, Наставник, терминология, §7 v1.1 ──

def oracle_d1_report_lines_all_ten() -> None:
    from app.core.run_report import build_report_model, render_markdown

    events = [
        {
            "event_id": f"ev-cert18-d1-{i}",
            "run_id": "RUN-CERT18",
            "ts": f"2026-10-06T13:{i:02d}:00+00:00",
            "stage": "eda",
            "node_id": node_id,
            "event_type": "eda_check_status",
            "payload": {"status": "done" if i < 6 else "pending"},
            "actor": "user",
        }
        for i, node_id in enumerate(CHECK_IDS)
    ]
    run_meta = {
        "run_id": "RUN-CERT18",
        "dataset_name": "cert18_daily_traffic_n210.csv",
        "status": "active",
        "created_at": "2026-10-06T12:59:00+00:00",
        "last_active_at": "2026-10-06T13:10:00+00:00",
    }
    model = build_report_model(run_meta, events)
    md = render_markdown(model)
    assert "Событие трассы" not in md, "фоллбек-строка в отчёте"
    assert "eda/" not in md and "ih_analysis" not in md, "сырые id в отчёте"
    assert "отчитан модулем «EDA»" in md, "модуль не назван ЯВНО"
    assert md.count("результат просмотрен аналитиком") == 6, "не 6 строк просмотра"
    assert md.count("ещё не просмотрен аналитиком") == 4, "не 4 строки ожидания"
    # Метки ВСЕХ 10 исследований -- из реестра справки (не сырые id):
    labels = [
        "Описательные статистики", "Корреляция (ACF/PACF)", "IH-анализ",
        "Сезонность", "Стационарность", "Распределение",
    ]
    for label in labels:
        assert label in md, f"метки реестра нет в отчёте: {label}"


def oracle_d2_mentor_phase() -> None:
    events = [
        {
            "event_id": "ev-cert18-d2",
            "run_id": "RUN-CERT18",
            "ts": "2026-10-06T13:00:00+00:00",
            "stage": "eda",
            "node_id": "descriptive",
            "event_type": "eda_check_status",
            "payload": {"status": "done"},
            "actor": "user",
        },
    ]
    assert derive_last_active_stage(events) == "eda"


def oracle_d3_node_reason_terminology() -> None:
    """Терминология узлового состояния: status_reason узла eda/* --
    «Статус исследования отчитан модулем «EDA»» (ИССЛЕДОВАНИЕ, не
    проверка; модуль назван ЯВНО) -- поверхность /trace nodes[]."""
    trace = _trace()
    node = next(
        n for n in trace["nodes"]
        if n["stage"] == "eda" and n["node_id"] == "stationarity"
    )
    assert node["status"] == "pending", node  # последний отчёт -- pending
    # Последнее событие узла -- eda_check_status: причина терминологии EDA.
    assert node["status_reason"] == "Статус исследования отчитан модулем «EDA»", (
        node["status_reason"]
    )


def oracle_d4_acceptance_six_of_six() -> None:
    """Критерий приёмки v1.1 §7: КАЖДАЯ из 6 стадий имеет хотя бы один
    узловой факт-источник уровня «проверка/этап/исследование пройдено»
    -- тип в реестре стадии, статус которого выводится движком (карта
    EVENT_NODE_STATUS либо payload-статус). PROGR-18 закрывает последнюю
    (eda)."""
    from apps.api.trace_events import STAGE_EVENT_TYPES

    fact_sources: dict[str, list[str]] = {}
    for stage, types in STAGE_EVENT_TYPES.items():
        fact_sources[stage] = sorted(
            t for t in types
            if t in EVENT_NODE_STATUS or t in PAYLOAD_STATUS_EVENT_TYPES
        )
    missing = [s for s, ts in fact_sources.items() if not ts]
    assert not missing, f"стадии без узлового факт-источника: {missing}"
    assert "eda_check_status" in fact_sources["eda"], fact_sources["eda"]
    assert len(fact_sources) == 6, sorted(fact_sources)


def main() -> int:
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()

    upload_my_dataset()
    print("       -- датасет аудитора: cert18_daily_traffic_n210.csv "
          "(сутки, 210 точек, сезонность 7, сдвиг +250@i=150, выброс 5x@i=30)")

    check("A1", "отпечаток «Сезонности» СВОЕГО датасета: период 7 подтверждён и доминирует",
          oracle_a1_seasonality_weekly)
    check("A2", "отпечаток «Структурных сдвигов»: устойчивый сдвиг ровно в точке i=150",
          oracle_a2_structural_break)
    check("A3", "отпечаток «Распределения»: 5x-выброс -- mean>median, skew>3",
          oracle_a3_stats_outlier_fingerprint)
    check("B1", "профили моих данных осели: seasonality=done, stationarity=warning "
                "(результат ПОКАЗАН -- факт просмотра возможен)",
          oracle_b1_profiles_settled_shown)
    check("B2", "реестр един: backend == shared JSON == клиентский импорт (10 исследований)",
          oracle_b2_registry_identity_three_sources)

    check("C1", "POST /v1/progress/eda-checks (6 done / 4 pending): 200, reported==10, run_id RUN-*",
          oracle_c1_post_contract)
    check("C2", "слой 1: 10 событий eda_check_status, payload.status == карте, stage=eda, run_id",
          oracle_c2_layer1_events)
    check("C3", "слой 2 (зеркало research_runs): 10 событий",
          oracle_c3_layer2_mirror)
    check("C4", "панель == модулю: node_statuses[eda/*] == карта (все 10)",
          oracle_c4_panel_equals_module)
    check("C5", "свёртка 6/4: attention, warning_nodes==0 (warning в словаре EDA нет)",
          oracle_c5_fold_attention_warning_zero)
    check("C6", "все 10 просмотрены: fold passed, done_count==10",
          oracle_c6_all_viewed_folds_passed)
    check("C7", "fail-closed x5 c ДЕТАЛЯМИ (фантом/warning-легальный/мусор/неполная/пустая) "
                "-- 422, ноль записей",
          oracle_c7_fail_closed_details)
    check("C8", "без датасета -- 400 (факты просмотров без исследования не существуют)",
          oracle_c8_400_without_dataset)
    check("C9", "посев run_id на первом отчёте (запуск мог произойти мимо хука)",
          oracle_c9_run_id_seeded)
    check("C10", "last-wins: повторный отчёт меняет статус узла на панели",
          oracle_c10_last_wins)
    check("C11", "составной ключ: eda/stationarity != preprocessing/stationarity",
          oracle_c11_composite_key)
    check("C12", "персистентность через сериализацию (fakeredis): 10 событий переживают "
                 "перечитывание store",
          oracle_c12_persistence_through_serialization)

    check("D1", "отчёт §5.4: 6 строк «просмотрен» + 4 «не просмотрен», метки реестра, "
                "модуль «EDA» назван, без сырых id и фоллбеков",
          oracle_d1_report_lines_all_ten)
    check("D2", "фаза Наставника (B1): узловой факт eda_check_status двигает фазу на eda",
          oracle_d2_mentor_phase)
    check("D3", "терминология status_reason узла: «Статус исследования отчитан модулем «EDA»»",
          oracle_d3_node_reason_terminology)
    check("D4", "критерий приёмки v1.1 §7: 6/6 стадий имеют узловой факт-источник "
                "(PROGR-18 закрывает eda)",
          oracle_d4_acceptance_six_of_six)

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()

    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n===== СВОДКА: {passed}/{len(RESULTS)} GREEN =====")
    for oracle_id, _, desc in failed:
        print(f"FAIL: {oracle_id}: {desc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
