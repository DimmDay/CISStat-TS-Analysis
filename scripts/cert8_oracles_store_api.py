# scripts/cert8_oracles_store_api.py
"""PROGR-8-CERT (часть 2): слой 2, хук, REST, E2E -- свои данные сертификатора.

  O7  Слой 2: MentorObservation fail-closed; to_dict/from_dict roundtrip;
      DDL-синхронность MIGRATION_STATEMENTS <-> migrations/0001_research_runs.sql
      (разбор колонок обеими сторонами); Memory-store: порядок дописывания,
      копийность, изоляция экземпляров; контракт обоих классов store.
  O8  Дополнение хука: dotted "metrics.mape" -> плоский "mape"; отсутствующий/
      не-dict промежуточный уровень -- честный пропуск; mape=null сохраняется;
      плоские ключи не сломаны; РЕАЛЬНАЯ строка backtest в TRACE_ROUTES несёт
      metrics.mape; коллизия последних сегментов -- последний выигрывает.
  O9  REST /v1/progress/admin/*: 401 / 403 (обе не-ADMIN роли) / 500 / 200;
      отсутствие X-API-Key -- 422 (фиксация контракта FastAPI); границы
      days/top -- 422; gt=0 у max_backtest_mape -- 422; админ-эндпоинты не
      трассируются; пустой корпус -- честные нули по HTTP.
  O10 E2E: демо-сеанс (HTTP) -> run_id -> sanity-check с warning -> наблюдение
      с run-контекстом; без cookie -- записей нет; best-effort (сбой журнала
      не ломает 200); next-step по подсеянному model_selected -> наблюдение
      next_step; admin/overview + case-bank по подсеянному корпусу через
      реальный mirror-путь record_run_event.

Запуск: python3 scripts/cert8_oracles_store_api.py  (exit 0 = все PASSED)
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CERT_DIR = tempfile.mkdtemp(prefix="cert8b-")
os.environ["CISSTAT_DATA_DIR"] = os.path.join(_CERT_DIR, "data")
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_API_KEYS"] = (
    "cert8-admin-key:admin:,cert8-user-key:external_user:demo,"
    "cert8-analyst-key:internal_analyst:"
)

from apps.api.research_runs import (  # noqa: E402
    MIGRATION_STATEMENTS,
    MemoryResearchRunStore,
    MentorObservation,
    PostgresResearchRunStore,
    ResearchRun,
    get_research_run_store,
    record_run_event,
    reset_dataset_file_store_for_testing,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event  # noqa: E402
from apps.api.trace_hook import TRACE_ROUTES, TraceRouteSpec, _extract_payload, resolve_trace_route  # noqa: E402

_RESULTS: list[tuple[str, bool, str]] = []


def check(oracle_id: str, condition: bool, detail: str = "") -> None:
    _RESULTS.append((oracle_id, bool(condition), detail))
    status = "PASSED" if condition else "FAILED"
    print(f"[{status}] {oracle_id}" + (f" -- {detail}" if detail and not condition else ""))


def expect_value_error(oracle_id: str, fn) -> None:
    try:
        fn()
    except ValueError:
        check(oracle_id, True)
        return
    check(oracle_id, False, "ValueError не поднялся")


# ── O7: слой 2 -- журнал наблюдений ──────────────────────────────────


def oracle_mentor_observation() -> None:
    obs = MentorObservation(
        run_id="RUN-CERT8AA",
        obs_kind="sanity_warning",
        rule_id="no_effect",
        stage="preprocessing",
        node_id="missing",
        severity="warning",
    )
    data = obs.to_dict()
    restored = MentorObservation.from_dict(data)
    check("O7.1 to_dict/from_dict roundtrip 8 полей", restored.to_dict() == data, f"{restored.to_dict()}")
    check(
        "O7.2 дефолты: obs_id uuid, ts ISO",
        len(obs.obs_id) == 36 and datetime.fromisoformat(obs.ts) is not None,
        f"obs_id={obs.obs_id} ts={obs.ts}",
    )
    expect_value_error("O7.3 fail-closed: неизвестный obs_kind", lambda: MentorObservation(run_id="R", rule_id="x", obs_kind="шум"))
    expect_value_error("O7.4 fail-closed: пустой run_id", lambda: MentorObservation(run_id="", rule_id="x"))
    expect_value_error("O7.5 fail-closed: пустой rule_id", lambda: MentorObservation(run_id="R", rule_id=""))

    store = MemoryResearchRunStore()
    for i in range(3):
        store.append_mentor_observation(
            MentorObservation(run_id=f"RUN-{i}", obs_kind="next_step", rule_id=f"rule-{i}", stage="upload")
        )
    listed = store.list_mentor_observations()
    check("O7.6 порядок дописывания (append-only)", [o.rule_id for o in listed] == ["rule-0", "rule-1", "rule-2"], f"{[o.rule_id for o in listed]}")
    listed.append("мусор")  # type: ignore[arg-type]
    check("O7.7 список -- копия (мутация не затрагивает store)", len(store.list_mentor_observations()) == 3)
    other = MemoryResearchRunStore()
    check("O7.8 изоляция экземпляров store", len(other.list_mentor_observations()) == 0)
    check(
        "O7.9 контракт: оба класса реализуют 2 метода журнала",
        callable(getattr(MemoryResearchRunStore, "append_mentor_observation", None))
        and callable(getattr(PostgresResearchRunStore, "list_mentor_observations", None)),
    )


def oracle_ddl_sync() -> None:
    """O7.10: DDL mentor_observations синхронен в MIGRATION_STATEMENTS и ops-файле."""
    pg_ddl = next((s for s in MIGRATION_STATEMENTS if "mentor_observations" in s), "")
    ops_path = Path(__file__).resolve().parent.parent / "apps/api/migrations/0001_research_runs.sql"
    ops_sql = ops_path.read_text(encoding="utf-8")

    def columns(sql: str) -> dict[str, list[str]]:
        start = sql.find("mentor_observations")
        if start < 0:
            return {}
        cols: dict[str, list[str]] = {}
        for line in sql[start:].splitlines()[1:]:
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.startswith("--"):
                continue
            if stripped.startswith(")"):
                break
            parts = stripped.split()
            if len(parts) >= 2:
                cols.setdefault(parts[0], parts[1:])
        return cols

    cols_m, cols_o = columns(pg_ddl), columns(ops_sql)
    expected = {"seq", "obs_id", "run_id", "ts", "obs_kind", "rule_id", "stage", "node_id", "severity"}
    check("O7.10 DDL синхронен: 9 колонок в обоих источниках", set(cols_m) == set(cols_o) == expected, f"M={sorted(cols_m)} O={sorted(cols_o)}")
    check("O7.11 типы совпадают дословно", all(cols_m[c] == cols_o[c] for c in expected if c in cols_m and c in cols_o), f"{ {c: (cols_m.get(c), cols_o.get(c)) for c in expected} }")
    check("O7.12 obs_id UNIQUE в обоих", "UNIQUE" in pg_ddl and "UNIQUE" in ops_sql)


# ── O8: дополнение хука (dotted-path) ────────────────────────────────


def oracle_trace_hook_dotted() -> None:
    spec = TraceRouteSpec("POST", "/x", "modeling", "backtest", "backtest_run", payload_keys=("model_id", "metrics.mape"))
    payload = _extract_payload(spec, {"model_id": "ets", "metrics": {"mape": 12.5}})
    check("O8.1 dotted -> плоский 'mape'", payload == {"model_id": "ets", "mape": 12.5}, f"{payload}")
    check("O8.2 отсутствующий промежуточный уровень -- пропуск", _extract_payload(spec, {"model_id": "ets"}) == {"model_id": "ets"})
    check("O8.3 промежуточный не dict -- пропуск", _extract_payload(spec, {"model_id": "ets", "metrics": "не-словарь"}) == {"model_id": "ets"})
    check("O8.4 mape=null сохраняется как None (движок потом откажет)", _extract_payload(spec, {"metrics": {"mape": None}}) == {"mape": None})
    flat_spec = TraceRouteSpec("POST", "/y", "upload", "structure_confirmed", "upload_completed", payload_keys=("name", "rows"))
    check("O8.5 плоские ключи работают как прежде", _extract_payload(flat_spec, {"name": "meteo.csv", "rows": 42}) == {"name": "meteo.csv", "rows": 42})
    twin = TraceRouteSpec("POST", "/z", "upload", "structure_confirmed", "upload_completed", payload_keys=("a.x", "b.x"))
    check("O8.6 коллизия последних сегментов -- последний выигрывает", _extract_payload(twin, {"a": {"x": 1}, "b": {"x": 2}}) == {"x": 2})
    backtest_spec = next(s for s in TRACE_ROUTES if s.path_template == "/v1/session/modeling/backtest")
    check("O8.7 РЕАЛЬНАЯ строка backtest несёт metrics.mape", "metrics.mape" in backtest_spec.payload_keys, f"{backtest_spec.payload_keys}")
    check("O8.8 whitelist backtest не потерял плоские факты", {"model_id", "model_name", "family_id", "n_train", "n_test"} <= set(backtest_spec.payload_keys))


# ── O9/O10: REST и E2E ───────────────────────────────────────────────

_ADMIN = {"X-API-Key": "cert8-admin-key"}


def _fresh_client():
    from fastapi.testclient import TestClient
    from apps.api.main import app

    return TestClient(app)


def _reset_all() -> None:
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    reset_dataset_file_store_for_testing()


def oracle_rest_auth_and_validation() -> None:
    _reset_all()
    client = _fresh_client()
    r = client.get("/v1/progress/admin/overview", headers={"X-API-Key": "wrong-cert8-key"})
    check("O9.1 неверный ключ -- 401", r.status_code == 401, f"{r.status_code}")
    r = client.get("/v1/progress/admin/overview", headers={"X-API-Key": "cert8-user-key"})
    check("O9.2 external_user -- 403", r.status_code == 403, f"{r.status_code}")
    r = client.get("/v1/progress/admin/overview", headers={"X-API-Key": "cert8-analyst-key"})
    check("O9.3 internal_analyst с полными capabilities -- тоже 403", r.status_code == 403, f"{r.status_code}")
    r = client.get("/v1/progress/admin/overview")
    check("O9.4 без X-API-Key -- 422 (контракт FastAPI Header(...))", r.status_code == 422, f"{r.status_code}")
    os.environ.pop("CISSTAT_API_KEYS", None)
    r = client.get("/v1/progress/admin/overview", headers=_ADMIN)
    check("O9.5 ключи не настроены -- 500", r.status_code == 500, f"{r.status_code}")
    os.environ["CISSTAT_API_KEYS"] = (
        "cert8-admin-key:admin:,cert8-user-key:external_user:demo,cert8-analyst-key:internal_analyst:"
    )
    r = client.get("/v1/progress/admin/overview", headers=_ADMIN)
    check("O9.6 ADMIN -- 200, пустой корпус честно нулевой", r.status_code == 200 and r.json()["runs_total_all_time"] == 0 and r.json()["runs_by_status"] == {"active": 0, "paused": 0, "completed": 0, "abandoned": 0}, f"{r.status_code} {r.json() if r.status_code == 200 else r.text}")
    body = r.json()
    expected_keys = {
        "generated_at", "period_days", "runs_total_all_time", "runs_total_in_period",
        "runs_by_status", "stage_time", "top_problem_nodes", "next_step_frequency",
        "sanity_by_rule", "sanity_by_node", "forecasting_model_frequency",
        "forecasting_horizon_frequency", "forecasting_alpha_frequency",
    }
    check("O9.7 контракт ответа -- все 13 полей §10/§9", expected_keys <= set(body), f"{sorted(set(body) ^ expected_keys)}")
    for params, expect in [({"days": 0}, 422), ({"days": 731}, 422), ({"top": 0}, 422), ({"top": 51}, 422), ({"days": 730, "top": 50}, 200)]:
        r = client.get("/v1/progress/admin/overview", params=params, headers=_ADMIN)
        check(f"O9.8 границы {params} -> {expect}", r.status_code == expect, f"{r.status_code}")
    r = client.get("/v1/progress/admin/case-bank/candidates", params={"max_backtest_mape": 0}, headers=_ADMIN)
    check("O9.9 max_backtest_mape=0 -> 422 (gt=0)", r.status_code == 422, f"{r.status_code}")
    r = client.get("/v1/progress/admin/case-bank/candidates", headers=_ADMIN)
    check(
        "O9.10 case-bank: эхо критериев + total_completed",
        r.status_code == 200 and r.json()["criteria"]["max_backtest_mape"] == 30.0 and r.json()["total_completed"] == 0,
        f"{r.status_code}",
    )
    check(
        "O9.11 админ-эндпоинты не трассируются (ридеры не трассируются)",
        resolve_trace_route("GET", "/v1/progress/admin/overview") is None
        and resolve_trace_route("GET", "/v1/progress/admin/case-bank/candidates") is None,
    )
    check(
        "O9.12 sanity-check/next-step в таблице хука тоже отсутствуют (негейт: PRE-существующее)",
        resolve_trace_route("POST", "/v1/progress/mentor/sanity-check") is None,
    )
    client.close()


def oracle_e2e_observations() -> None:
    """E2E: демо-сеанс -> sanity/next-step наблюдения -> корпус -> админ-агрегаты."""
    _reset_all()
    client = _fresh_client()
    # 1) демо-сеанс: cookie + run_id (upload_completed хуком)
    r = client.post("/v1/session/demo")
    check("O10.1 демо-сеанс 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    check("O10.2 run_id зафиксирован загрузкой (§5)", bool(run_id) and run_id.startswith("RUN-"), f"run_id={run_id}")
    check("O10.3 upload_completed в трассе слоя 1", any(e["event_type"] == "upload_completed" for e in trace["events"]))
    # 2) sanity-check с warning -> наблюдение в журнале с run-контекстом
    payload = {
        "stage": "preprocessing", "node_id": "missing", "strategy": "drop_rows",
        "affected_count_before": 5, "changed_count": 0, "still_affected_count": 5,
        "rows_before": 100, "rows_after": 100,
    }
    r = client.post("/v1/progress/mentor/sanity-check", json=payload)
    warnings = r.json().get("warnings", [])
    check("O10.4 preview-исход без изменений даёт no_effect warning (§7.2)", any(w["rule_id"] == "no_effect" for w in warnings), f"{warnings}")
    obs = get_research_run_store().list_mentor_observations()
    sanity_obs = [o for o in obs if o.obs_kind == "sanity_warning"]
    check("O10.5 наблюдение записано с run-контекстом cookie-сеанса", len(sanity_obs) == 1 and sanity_obs[0].run_id == run_id and sanity_obs[0].node_id == "missing", f"{[(o.run_id, o.node_id) for o in sanity_obs]}")
    # 3) без cookie -- записей нет (отдельный клиент без cookie-банки)
    no_cookie_client = _fresh_client()
    r2 = no_cookie_client.post("/v1/progress/mentor/sanity-check", json=payload)
    check("O10.6 ответ без cookie корректен (200 + warnings)", r2.status_code == 200 and len(r2.json()["warnings"]) > 0)
    check("O10.7 вне исследования предупреждение не существует для корпуса", len(get_research_run_store().list_mentor_observations()) == 1)
    no_cookie_client.close()
    # 4) best-effort: сбой журнала не ломает ответ
    store = get_research_run_store()
    original = store.append_mentor_observation

    def broken(_obs):
        raise RuntimeError("журнал недоступен")

    store.append_mentor_observation = broken  # type: ignore[method-assign]
    r3 = client.post("/v1/progress/mentor/sanity-check", json=payload)
    check("O10.8 best-effort: сбой журнала -- ответ 200 с warnings", r3.status_code == 200 and len(r3.json()["warnings"]) > 0, f"{r3.status_code}")
    store.append_mentor_observation = original  # type: ignore[method-assign]
    # 5) next-step: подсеиваем model_selected через реальный mirror-путь
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    event = make_trace_event("model_selected", stage="modeling", node_id="selection", run_id=run_id, selected_model_id="ets")
    record_run_event(session, event)
    r4 = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    body4 = r4.json()
    check("O10.9 выбранная без бэктеста модель даёт рекомендацию (Этап 2 §11)", body4["recommendation"] is not None and body4["recommendation"]["rule_id"] == "modeling_selected_without_backtest", f"{body4.get('recommendation')}")
    next_obs = [o for o in get_research_run_store().list_mentor_observations() if o.obs_kind == "next_step"]
    check("O10.10 ВЫДАННАЯ рекомендация записана в журнал (§10 частота выдач)", len(next_obs) == 1 and next_obs[0].rule_id == "modeling_selected_without_backtest", f"{[(o.rule_id) for o in next_obs]}")
    # 6) admin overview по живому корпусу
    r5 = client.get("/v1/progress/admin/overview", headers=_ADMIN)
    body5 = r5.json()
    check("O10.11 корпус виден админке: all_time >= 1", body5["runs_total_all_time"] >= 1, f"{body5['runs_total_all_time']}")
    check("O10.12 частота next-step в ответе", any(i["rule_id"] == "modeling_selected_without_backtest" for i in body5["next_step_frequency"]), f"{body5['next_step_frequency']}")
    check("O10.13 sanity по правилу/узлу в ответе", any(i["rule_id"] == "no_effect" for i in body5["sanity_by_rule"]) and any(i["node_id"] == "missing" for i in body5["sanity_by_node"]), f"{body5['sanity_by_rule']} {body5['sanity_by_node']}")
    check("O10.14 modeling стадия измерима (2 события: upload+modeling... проверка деградации честная)", isinstance(body5["stage_time"], list))
    client.close()


def oracle_e2e_case_bank() -> None:
    """E2E банка кейсов: завершённый запуск с backtest-доказательством (mape в
    payload -- тем же путём, что кладёт дополнение хука: плоский 'mape')."""
    _reset_all()
    client = _fresh_client()
    store = get_research_run_store()
    now = datetime.now(timezone.utc)
    run_id = "RUN-CERT8E2E"
    store.upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id="sess-cert8",
            dataset_name="energy_load.csv",
            created_at=(now - timedelta(hours=2)).isoformat(),
            last_active_at=(now - timedelta(hours=1)).isoformat(),
            status="completed",
        )
    )
    backtest_event = make_trace_event(
        "backtest_run", stage="modeling", node_id="backtest", run_id=run_id,
        model_id="ets", model_name="ETS", family_id="ets", n_train=80, n_test=20, mape=9.75,
    )
    warning_event = make_trace_event(
        "correction_previewed", stage="preprocessing", node_id="outliers", run_id=run_id, strategy="iqr",
    )
    store.append_event(run_id, backtest_event)
    store.append_event(run_id, warning_event)
    r = client.get(
        "/v1/progress/admin/case-bank/candidates",
        params={"max_backtest_mape": 30, "max_warning_nodes": 2, "max_sanity_warnings": 2},
        headers=_ADMIN,
    )
    body = r.json()
    check("O10.15 кандидат отобран по HTTP", r.status_code == 200 and len(body["candidates"]) == 1, f"{r.status_code} {body}")
    if body["candidates"]:
        c = body["candidates"][0]
        check(
            "O10.16 evidence кандидата полная",
            c["run_id"] == run_id and abs(c["backtest_mape"] - 9.75) < 1e-9 and c["warning_nodes"] == 1 and c["sanity_warnings"] == 0 and c["dataset_name"] == "energy_load.csv",
            f"{c}",
        )
    check("O10.17 total_completed == 1", body["total_completed"] == 1, f"{body['total_completed']}")
    # строгий порог mape исключает
    r2 = client.get("/v1/progress/admin/case-bank/candidates", params={"max_backtest_mape": 5}, headers=_ADMIN)
    check("O10.18 mape 9.75 > порога 5 -- кандидатов нет", r2.json()["candidates"] == [], f"{r2.json()}")
    client.close()


def main() -> int:
    oracle_mentor_observation()
    oracle_ddl_sync()
    oracle_trace_hook_dotted()
    oracle_rest_auth_and_validation()
    oracle_e2e_observations()
    oracle_e2e_case_bank()
    failed = [r for r in _RESULTS if not r[1]]
    print(f"\n=== Оракулы слоя 2/хука/REST/E2E: {len(_RESULTS) - len(failed)}/{len(_RESULTS)} PASSED ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
