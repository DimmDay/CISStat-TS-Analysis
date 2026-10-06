# scripts/progr17cert_oracles.py
# Независимый сертификационный аудит Task PROGR-17: оракул-тесты на
# СОБСТВЕННЫХ данных аудитора. Датасет, карта статусов, run_id и порядок
# отчётов НЕ пересекаются с fixtures tests/api/test_progress_progr17.py
# (у коллеги -- месячный monitor CSV 150 строк, колонка "value", без
# пропусков/выбросов; у аудитора -- НЕДЕЛЬНЫЙ ряд продаж 120 строк,
# колонки dt/sales/promo/store, 7 инжектированных пропусков и один
# экстремальный выброс).
#
# Оракулы проверяют: (A) дата-специфичные отпечатки СВОЕГО датасета на
# реальных profile-эндпоинтах, (B) вывод статусов модуля по документиро-
# ванной семантике TsAnalysisPreprocessing.tsx (профиль осел -> status,
# 404 -> skipped) и полноту снапшота, (C) контракт
# POST /v1/progress/preprocessing-checks end-to-end на этих данных
# (панель == модулю, all-or-nothing, last-wins, 400, посев run_id),
# (D) потребители: отчёт §5.4 (метки реестра для ВСЕХ 10 остановок) и
# фаза Наставника B1.
#
# Запуск: python scripts/progr17cert_oracles.py   (exit 0 == все GREEN)
from __future__ import annotations

import io
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

from app.core.pipeline_graph import CHECK_STATUS_VALUES, STAGE_NODES  # noqa: E402
from app.core.node_status import derive_last_active_stage  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

CHECK_IDS = list(STAGE_NODES["preprocessing"])

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


# ── Собственный датасет аудитора (недельный, 120 точек) ──

def build_my_csv() -> str:
    import pandas as pd

    idx = pd.date_range("2015-01-07", periods=120, freq="7D")
    sales = [
        100 + 0.5 * i + 20 * math.sin(2 * math.pi * i / 52) + (i % 7) * 0.1
        for i in range(120)
    ]
    sales[60] *= 10.0  # экстремальный выброс (10x) -- отпечаток «Выбросов»
    promo = [5.0 + (i % 4) for i in range(120)]
    for j in (9, 23, 41, 55, 78, 96, 111):
        promo[j] = None  # ровно 7 пропусков -- отпечаток «Пропусков»
    frame = pd.DataFrame(
        {
            "dt": idx.strftime("%Y-%m-%d"),
            "sales": [round(v, 3) for v in sales],
            "promo": promo,
            "store": [f"S{i % 3}" for i in range(120)],
        }
    )
    return frame.to_csv(index=False)


MY_CSV = build_my_csv()

client = TestClient(app)
_fresh = None  # второй клиент без cookie -- для оракула 400


def upload_my_dataset() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "cert17_weekly_sales_n120.csv",
            io.BytesIO(MY_CSV.encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def get_json(path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def derive_module_snapshot(feature: str) -> dict[str, str]:
    """Семантика модуля (TsAnalysisPreprocessing.tsx): профиль осел ->
    его status; 404 -> skipped. Ровно то, что степпер показывает."""
    base = "/v1/session/dataset"
    urls = {
        "missing": f"{base}/missing-profile",
        "outliers": f"{base}/outlier-profile?method=iqr",
        "regularity": f"{base}/preprocessing/regularity-profile",
        "decomposition": f"{base}/preprocessing/decomposition-profile?column={feature}",
        "variance_stab": f"{base}/preprocessing/variance-profile?column={feature}",
        "smoothing": f"{base}/preprocessing/smoothing-profile?column={feature}",
        "stationarity": f"{base}/preprocessing/stationarity-profile?column={feature}",
        "spectral": f"{base}/preprocessing/spectral-profile?column={feature}",
        "feature_eng": f"{base}/preprocessing/feature-generation-profile?column={feature}",
        "scaling": f"{base}/preprocessing/scaling-profile?column={feature}",
    }
    assert set(urls) == set(CHECK_IDS)
    snapshot: dict[str, str] = {}
    for check_id, url in urls.items():
        response = client.get(url)
        if response.status_code == 404:
            snapshot[check_id] = "skipped"
            continue
        assert response.status_code == 200, (url, response.text)
        status = response.json().get("status")
        assert isinstance(status, str), (url, status)
        snapshot[check_id] = status
    return snapshot


# ── A: отпечатки СВОЕГО датасета на реальных профилях ──

def oracle_a1_missing_fingerprint() -> None:
    profile = get_json("/v1/session/dataset/missing-profile")
    assert profile["total_missing"] == 7, profile["total_missing"]
    assert profile["status"] in CHECK_STATUS_VALUES


def oracle_a2_outlier_fingerprint() -> None:
    profile = get_json("/v1/session/dataset/outlier-profile?method=iqr")
    assert profile["total_outliers"] >= 1, profile["total_outliers"]
    assert profile["status"] in CHECK_STATUS_VALUES


def oracle_a3_regularity_fingerprint() -> None:
    profile = get_json("/v1/session/dataset/preprocessing/regularity-profile")
    assert profile["profile"]["total_violations"] == 0, profile["profile"]
    assert profile["status"] in CHECK_STATUS_VALUES


# ── B: вывод статусов модуля -- полнота снапшота ──

def oracle_b1_snapshot_full_and_settled() -> None:
    target = get_json("/v1/session/target-column")
    assert target["has_dataset"] is True
    feature = target["suggested_column"]
    assert feature, "useTargetColumn авто-фиксирует рекомендацию при числовых колонках"
    snapshot = derive_module_snapshot(feature)
    assert set(snapshot) == set(CHECK_IDS)
    for check_id, status in snapshot.items():
        assert status in ("done", "warning", "skipped", "error"), (check_id, status)
        assert status not in ("running", "pending"), (check_id, status)


# ── C: контракт POST /v1/progress/preprocessing-checks end-to-end ──

def oracle_c1_post_contract() -> None:
    target = get_json("/v1/session/target-column")
    snapshot = derive_module_snapshot(target["suggested_column"])
    reported = client.post(
        "/v1/progress/preprocessing-checks", json={"checks": snapshot}
    )
    assert reported.status_code == 200, reported.text
    body = reported.json()
    assert body["reported"] == 10
    assert body["run_id"].startswith("RUN-")
    oracle_c1_post_contract.snapshot = snapshot  # type: ignore[attr-defined]
    oracle_c1_post_contract.run_id = body["run_id"]  # type: ignore[attr-defined]


def oracle_c2_layer1_events() -> None:
    snapshot = oracle_c1_post_contract.snapshot  # type: ignore[attr-defined]
    run_id = oracle_c1_post_contract.run_id  # type: ignore[attr-defined]
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    events = [
        e for e in session.pipeline_trace
        if e["event_type"] == "preprocessing_check_status"
    ]
    assert len(events) == 10
    by_node = {e["node_id"]: e for e in events}
    for check_id, status in snapshot.items():
        event = by_node[check_id]
        assert event["payload"]["status"] == status, (check_id, status)
        assert event["stage"] == "preprocessing"
        assert event["run_id"] == run_id
        assert event["ts"] and event["event_id"]


def oracle_c3_layer2_mirror() -> None:
    from apps.api.research_runs import get_research_run_store

    run_id = oracle_c1_post_contract.run_id  # type: ignore[attr-defined]
    stored = get_research_run_store().list_events(run_id)
    mirror = [
        e for e in stored if e.event_type == "preprocessing_check_status"
    ]
    assert len(mirror) == 10


def oracle_c4_panel_equals_module() -> None:
    snapshot = oracle_c1_post_contract.snapshot  # type: ignore[attr-defined]
    trace = get_json("/v1/progress/trace")
    for check_id, status in snapshot.items():
        assert trace["node_statuses"].get(f"preprocessing/{check_id}") == status, (
            check_id, status, trace["node_statuses"].get(f"preprocessing/{check_id}")
        )


def oracle_c5_stage_fold_consistent() -> None:
    trace = get_json("/v1/progress/trace")
    stage = next(s for s in trace["stages"] if s["stage"] == "preprocessing")
    assert stage["total_nodes"] == 10
    assert stage["done_count"] + stage["warning_nodes"] <= 10
    if stage["warning_nodes"] > 0:
        assert stage["fold"] == "attention", stage  # §12 п.10
    else:
        assert stage["fold"] in ("done", "idle"), stage


def oracle_c6_last_wins() -> None:
    snapshot = dict(oracle_c1_post_contract.snapshot)  # type: ignore[attr-defined]
    flip = next(c for c, s in snapshot.items() if s != "done")
    snapshot[flip] = "done"
    reported = client.post(
        "/v1/progress/preprocessing-checks", json={"checks": snapshot}
    )
    assert reported.status_code == 200, reported.text
    trace = get_json("/v1/progress/trace")
    assert trace["node_statuses"].get(f"preprocessing/{flip}") == "done"
    oracle_c1_post_contract.snapshot = snapshot  # type: ignore[attr-defined]


def oracle_c7_fail_closed_all_or_nothing() -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    before = sum(
        1 for e in session.pipeline_trace
        if e["event_type"] == "preprocessing_check_status"
    )
    good = dict(oracle_c1_post_contract.snapshot)  # type: ignore[attr-defined]
    bad_payloads = [
        {**good, "phantom_stop": "done"},
        {**good, "missing": "exploded"},
        {"missing": "done"},
        {},
    ]
    for checks_map in bad_payloads:
        response = client.post(
            "/v1/progress/preprocessing-checks", json={"checks": checks_map}
        )
        assert response.status_code == 422, (checks_map, response.status_code)
    after = sum(
        1 for e in session.pipeline_trace
        if e["event_type"] == "preprocessing_check_status"
    )
    assert before == after, (before, after)


def oracle_c8_400_without_dataset() -> None:
    global _fresh
    _fresh = TestClient(app)  # без cookie -- новая сессия без датасета
    response = _fresh.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": {c: "done" for c in CHECK_IDS}},
    )
    assert response.status_code == 400, response.status_code


def oracle_c9_run_id_seeded() -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    session.run_id = ""
    get_session_store().save(session)
    reported = client.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": dict(oracle_c1_post_contract.snapshot)},  # type: ignore[attr-defined]
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["run_id"].startswith("RUN-")


# ── D: потребители -- отчёт §5.4 и фаза Наставника ──

def oracle_d1_report_labels_all_ten() -> None:
    from app.core.run_report import build_report_model, render_markdown

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    events = [
        e for e in session.pipeline_trace
        if e["event_type"] == "preprocessing_check_status"
    ]
    assert len(events) >= 10
    run_meta = {
        "run_id": session.run_id, "dataset_name": "cert17_weekly_sales_n120.csv",
        "status": "active",
        "created_at": events[0]["ts"], "last_active_at": events[-1]["ts"],
    }
    md = render_markdown(build_report_model(run_meta, events))
    reported_nodes = {e["node_id"] for e in events}
    assert reported_nodes == set(CHECK_IDS)
    for event in events:
        raw_id = event["node_id"]
        assert f"отчитан модулем «Предобработка»" in md, raw_id
        # метка не сырой id: строка факта содержит «<»метку«» != node_id
        lines = [ln for ln in md.splitlines() if f"«{raw_id}»" in ln]
        assert not lines, f"сырой id {raw_id} просочился в отчёт"
        assert f"отчитан модулем «Предобработка»" in md
    assert "Событие трассы" not in md, "фоллбек-строка вместо факта"


def oracle_d2_mentor_phase_preprocessing() -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    stage = derive_last_active_stage(session.pipeline_trace)
    assert stage == "preprocessing", stage


def main() -> int:
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()

    upload_my_dataset()
    target = get_json("/v1/session/target-column")
    feature = target["suggested_column"]
    print(f"       -- suggested_column (активный признак, как в useTargetColumn): {feature!r}")

    check("A1", "отпечаток «Пропусков» СВОЕГО датасета: total_missing == 7 (инжектировано ровно 7)",
          oracle_a1_missing_fingerprint)
    check("A2", "отпечаток «Выбросов»: total_outliers >= 1 (инжектирован 10x-выброс)",
          oracle_a2_outlier_fingerprint)
    check("A3", "отпечаток «Регулярности»: total_violations == 0 (недельная сетка без нарушений)",
          oracle_a3_regularity_fingerprint)
    check("B1", "снапшот модуля ПОЛНЫЙ (10/10 реестра) и ОСЕВШИЙ (ни running, ни pending)",
          oracle_b1_snapshot_full_and_settled)

    check("C1", "POST /v1/progress/preprocessing-checks: 200, reported == 10, run_id RUN-*",
          oracle_c1_post_contract)
    check("C2", "слой 1: 10 событий preprocessing_check_status, payload.status == снапшоту, stage/run_id корректны",
          oracle_c2_layer1_events)
    check("C3", "слой 2 (зеркало research_runs): 10 событий",
          oracle_c3_layer2_mirror)
    check("C4", "панель == модулю: node_statuses[preprocessing/*] == снапшот (все 10)",
          oracle_c4_panel_equals_module)
    check("C5", "свёртка стадии согласована снапшоту: warning -> attention (§12 п.10)",
          oracle_c5_stage_fold_consistent)
    check("C6", "last-wins: повторный отчёт меняет статус узла на панели",
          oracle_c6_last_wins)
    check("C7", "fail-closed на СВОИХ данных: фантом/мусор/партиал/пусто -- 422 x4, ноль записей",
          oracle_c7_fail_closed_all_or_nothing)
    check("C8", "без датасета -- 400 (факты этапов без исследования не существуют)",
          oracle_c8_400_without_dataset)
    check("C9", "посев run_id на первом отчёте (запуск мог произойти мимо хука)",
          oracle_c9_run_id_seeded)
    check("D1", "отчёт §5.4: строки фактов для ВСЕХ 10 остановок, метки реестра, без сырых id и фоллбеков",
          oracle_d1_report_labels_all_ten)
    check("D2", "фаза Наставника (B1): стадия последнего узлового факта == preprocessing",
          oracle_d2_mentor_phase_preprocessing)

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
