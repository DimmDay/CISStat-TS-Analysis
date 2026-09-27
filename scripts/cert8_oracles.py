# scripts/cert8_oracles.py
"""PROGR-8-CERT: независимые оракул-тесты на СОБСТВЕННЫХ данных сертификатора.

Задача сертификации (plan_progress.md PROGR-8, spec_progress.md §10 + §9):
  Admin-панель мониторинга + офлайн-потребители (категория D).

Принцип независимости: корпус/сценарии НЕ копируются из коллегиальных
tests/api/test_admin_analytics.py / test_admin_progress_api.py -- свои
запуски, свои моменты времени (детерминированная инъекция now), свои
payload, свои граничные случаи. Часть оракулов дублирует контракт
коллегиальных тестов сознательно (перекрёстная проверка), часть добавляет
НОВЫЕ углы:

  O1  §10 запуски за период: включительность обеих границ окна; будущий
      created_at вне периода; нечитаемый created_at -- all-time;
      by_status только по запускам периода.
  O2  §10 время по стадиям: точная арифметика mean/median на своих
      числах; стадия из 1 события не измерима; нечитаемые ts --
      деградация; сортировка mean desc / тай-брейк stage asc.
  O3  §10 топ problem-узлов: счёт ПО ЗАПУСКАМ (не по событиям); последнее
      событие решает (previewed -> applied = done, не считается);
      фантомы исключены; топ-Limit с детерминированными тай-брейками.
  O4  §7.1/§7.2 частоты: next_step по (rule_id, stage); sanity по правилу
      И по узлу -- две проекции одного журнала; наблюдение без node_id
      не атрибутируется узлу; чужой obs_kind игнорируется.
  O5  §9 предпочтения Прогнозирования: model_id/horizon/alpha из payload
      forecast_generated; числовые значения строкуются (30 -> "30");
      пустые/отсутствующие -- честный пропуск; события чужих типов и
      запусков-призраков не считаются.
  O6  §9 банк кейсов: последний backtest_run финален (два бэктеста);
      без mape/нечитаемый mape -- нет доказательства; пороговые границы
      (== включительно); строковый mape; сортировка mape asc + run_id;
      sanity чужих запусков не текут; NaN mape -- ФИКСАЦИЯ фактического
      поведения (находка F-1).
  O7  Слой 2: MentorObservation fail-closed (3 ValueError-оракула);
      to_dict/from_dict roundtrip; DDL-синхронность MIGRATION_STATEMENTS
      и ops-файла migrations/0001_research_runs.sql; Memory-store:
      порядок дописывания, копийность списка, изоляция между store.
  O8  Хук (дополнение PROGR-8): dotted "metrics.mape" -> плоский "mape";
      отсутствующий/не-dict промежуточный уровень -- пропуск; mape=null
      сохраняется как null (движок потом честно откажет); плоские ключи
      не сломаны; реальная строка таблицы backtest несёт metrics.mape.
  O9  REST /v1/progress/admin/*: 401/403(2 роли)/500/200; отсутствие
      X-API-Key -- 422 (фиксация фактического контракта FastAPI);
      границы days/top и gt=0 mape -- 422; админ-эндпоинты не
      трассируются; пустой корпус -- честные нули по HTTP.
  O10 E2E на своих данных: демо-сеанс (HTTP) -> run_id -> sanity-check
      с warning -> наблюдение в журнале; next-step с подсеянным
      model_selected -> наблюдение next_step; best-effort (сбой журнала
      не ломает 200); admin/overview по подсеянному корпусу; case-bank
      по завершённому запуску с реальным mirror-путём record_run_event.

Запуск: python3 scripts/cert8_oracles.py  (exit 0 = все оракулы PASSED)
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Изоляция среды ДО импорта приложения: память вместо Postgres-зеркала,
# свои каталоги данных (сертификация не должна трогать общие сессии).
_CERT_DIR = tempfile.mkdtemp(prefix="cert8-")
os.environ["CISSTAT_DATA_DIR"] = os.path.join(_CERT_DIR, "data")
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("CISSTAT_API_KEYS", "cert8-admin:admin:")

from app.core.admin_analytics import (  # noqa: E402
    build_admin_overview,
    select_case_bank_candidates,
)
from apps.api.research_runs import (  # noqa: E402
    MIGRATION_STATEMENTS,
    MemoryResearchRunStore,
    MentorObservation,
    ResearchRun,
    get_research_run_store,
    record_run_event,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event  # noqa: E402
from apps.api.trace_hook import (  # noqa: E402
    TRACE_ROUTES,
    TraceRouteSpec,
    _extract_payload,
    resolve_trace_route,
)

# ── Свои данные сертификатора (не коллегиальные) ─────────────────────

BASE = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
MY_RUN = "RUN-CERT8AA"
MY_RUN2 = "RUN-CERT8BB"
MY_RUN3 = "RUN-CERT8CC"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def ev(
    event_type: str,
    stage: str,
    node_id: str | None,
    run_id: str,
    ts: datetime | None,
    **payload,
) -> dict:
    """Событие в канонической 8-польной форме (§4.1) -- вход движка."""
    return {
        "event_id": f"E-{run_id}-{event_type}-{node_id}-{ts}",
        "run_id": run_id,
        "ts": iso(ts) if ts else None,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload),
        "actor": "user",
    }


_RESULTS: list[tuple[str, bool, str]] = []


def check(oracle_id: str, condition: bool, detail: str = "") -> None:
    _RESULTS.append((oracle_id, bool(condition), detail))
    status = "PASSED" if condition else "FAILED"
    print(f"[{status}] {oracle_id}" + (f" -- {detail}" if detail and not condition else ""))


# ── O1: §10 запуски за период ────────────────────────────────────────


def oracle_runs_by_status() -> None:
    from app.core.admin_analytics import _runs_by_status

    runs = [
        # ровно на левой границе окна (period_days=7) -- ВКЛЮЧИТЕЛЬНО
        {"run_id": "R1", "status": "active", "created_at": iso(BASE - timedelta(days=7))},
        # ровно на правой границе (now) -- ВКЛЮЧИТЕЛЬНО
        {"run_id": "R2", "status": "completed", "created_at": iso(BASE)},
        # на секунду раньше окна -- вне периода, но в all-time
        {"run_id": "R3", "status": "completed", "created_at": iso(BASE - timedelta(days=7, seconds=1))},
        # будущий created_at -- вне периода (период -- накопленное прошлое)
        {"run_id": "R4", "status": "paused", "created_at": iso(BASE + timedelta(days=1))},
        # нечитаемый created_at -- all-time, вне периода (не угадываем)
        {"run_id": "R5", "status": "abandoned", "created_at": "не-дата"},
        {"run_id": "R6", "status": "active", "created_at": None},
    ]
    total, in_period, by_status = _runs_by_status(runs, now=BASE, period_days=7)
    check("O1.1 all-time == числу запусков", total == 6, f"total={total}")
    check("O1.2 in_period == 2 (обе границы включены)", in_period == 2, f"in_period={in_period}")
    check(
        "O1.3 by_status только по периоду",
        by_status == {"active": 1, "paused": 0, "completed": 1, "abandoned": 0},
        f"by_status={by_status}",
    )
    # канонические ключи присутствуют всегда (стабильный контракт)
    _, _, empty_status = _runs_by_status([], now=BASE, period_days=7)
    check(
        "O1.4 пустой корпус: 4 канонических ключа с нулями",
        empty_status == {"active": 0, "paused": 0, "completed": 0, "abandoned": 0},
        f"{empty_status}",
    )


# ── O2: §10 время по стадиям ─────────────────────────────────────────


def oracle_stage_time() -> None:
    events = {
        MY_RUN: [
            # preprocessing: события 10 и 30 мин назад -> span 20
            ev("correction_previewed", "preprocessing", "missing", MY_RUN, BASE - timedelta(minutes=30)),
            ev("correction_applied", "preprocessing", "missing", MY_RUN, BASE - timedelta(minutes=10)),
            # validation: 1 читаемое + 1 нечитаемое -> НЕ измерима (>=2 читаемых)
            ev("mode_changed", "validation", None, MY_RUN, BASE - timedelta(minutes=25)),
            ev("correction_applied", "validation", "formats", MY_RUN, None),
            # upload: единственное событие -> не измерима
            ev("upload_completed", "upload", "structure_confirmed", MY_RUN, BASE - timedelta(minutes=40)),
        ],
        MY_RUN2: [
            # preprocessing: 5 и 15 мин -> span 10; агрегат по трём запускам
            ev("correction_previewed", "preprocessing", "outliers", MY_RUN2, BASE - timedelta(minutes=15)),
            ev("correction_applied", "preprocessing", "outliers", MY_RUN2, BASE - timedelta(minutes=5)),
        ],
        MY_RUN3: [
            # третье span 7 мин -- асимметрия mean != median (анти-мутант M4)
            ev("correction_previewed", "preprocessing", "missing", MY_RUN3, BASE - timedelta(minutes=10)),
            ev("correction_applied", "preprocessing", "missing", MY_RUN3, BASE - timedelta(minutes=3)),
        ],
    }
    runs = [{"run_id": MY_RUN}, {"run_id": MY_RUN2}, {"run_id": MY_RUN3}]
    stats = build_admin_overview(runs, events, [], now=BASE, period_days=30).stage_time
    pre = next((s for s in stats if s.stage == "preprocessing"), None)
    check("O2.1 стадии с <2 читаемыми событиями отсутствуют (validation/upload)", all(s.stage != "validation" for s in stats) and all(s.stage != "upload" for s in stats), f"{[(s.stage) for s in stats]}")
    check("O2.2 preprocessing агрегирован по 3 запускам", pre is not None and pre.runs_with_stage == 3, f"{pre}")
    check("O2.3 mean == (20+10+7)/3 == 12.333...", pre is not None and abs(pre.mean_minutes - 37.0 / 3.0) < 1e-9, f"mean={pre.mean_minutes if pre else None}")
    check("O2.4 median == median(20,10,7) == 10.0 (mean != median)", pre is not None and abs(pre.median_minutes - 10.0) < 1e-9, f"median={pre.median_minutes if pre else None}")
    # сортировка mean desc; тай-брейк -- stage asc
    runs3 = [{"run_id": "RX"}, {"run_id": "RY"}]
    events3 = {
        "RX": [
            ev("correction_previewed", "eda", "correlation", "RX", BASE - timedelta(minutes=60)),
            ev("correction_applied", "eda", "correlation", "RX", BASE - timedelta(minutes=10)),  # span 50
        ],
        "RY": [
            ev("correction_previewed", "modeling", "backtest", "RY", BASE - timedelta(minutes=40)),
            ev("correction_applied", "modeling", "backtest", "RY", BASE - timedelta(minutes=0)),  # span 40
        ],
    }
    stats3 = build_admin_overview(runs3, events3, [], now=BASE, period_days=30).stage_time
    check(
        "O2.5 сортировка mean desc (50 перед 40)",
        len(stats3) == 2 and stats3[0].stage == "eda" and stats3[1].stage == "modeling",
        f"{[(s.stage, s.mean_minutes) for s in stats3]}",
    )
    # нечитаемые ts среди >=2 событий: только читаемые образуют span
    events_bad = {
        "RZ": [
            ev("correction_previewed", "preprocessing", "missing", "RZ", None),
            ev("correction_applied", "preprocessing", "missing", "RZ", BASE - timedelta(minutes=10)),
            ev("correction_previewed", "preprocessing", "outliers", "RZ", BASE - timedelta(minutes=2)),
        ],
    }
    stats_bad = build_admin_overview([{"run_id": "RZ"}], events_bad, [], now=BASE, period_days=30).stage_time
    pre_bad = next((s for s in stats_bad if s.stage == "preprocessing"), None)
    check(
        "O2.6 нечитаемый ts пропущен, span по 2 читаемым == 8 мин",
        pre_bad is not None and abs(pre_bad.mean_minutes - 8.0) < 1e-9,
        f"{pre_bad}",
    )


# ── O3: §10 топ problem-узлов ────────────────────────────────────────


def oracle_top_problem_nodes() -> None:
    events = {
        MY_RUN: [
            # один и тот же узел warning ДВАЖДЫ в одном запуске == 1 запуск
            ev("correction_previewed", "preprocessing", "missing", MY_RUN, BASE - timedelta(minutes=30), strategy="a"),
            ev("correction_previewed", "preprocessing", "missing", MY_RUN, BASE - timedelta(minutes=20), strategy="b"),
            # previewed -> applied: последнее событие решает -> done
            ev("correction_previewed", "preprocessing", "outliers", MY_RUN, BASE - timedelta(minutes=25)),
            ev("correction_applied", "preprocessing", "outliers", MY_RUN, BASE - timedelta(minutes=15)),
            # фантомный узел (вне графа) -- не должен появиться
            ev("correction_previewed", "preprocessing", "нет_такого_узла", MY_RUN, BASE - timedelta(minutes=12)),
            # неизвестный event_type -- статуса не создаёт
            ev("что-то_иное", "validation", "formats", MY_RUN, BASE - timedelta(minutes=11)),
        ],
        MY_RUN2: [
            ev("correction_previewed", "preprocessing", "missing", MY_RUN2, BASE - timedelta(minutes=10)),
            # второй запуск: validation/formats warning (неизвестный тип выше -- не считается)
            ev("correction_previewed", "validation", "formats", MY_RUN2, BASE - timedelta(minutes=9)),
        ],
    }
    runs = [{"run_id": MY_RUN}, {"run_id": MY_RUN2}]
    top = build_admin_overview(runs, events, [], now=BASE, period_days=30).top_problem_nodes
    keys = [(item.stage, item.node_id, item.status, item.count) for item in top]
    check(
        "O3.1 счёт по запускам: preprocessing/missing warning == 2",
        ("preprocessing", "missing", "warning", 2) in keys,
        f"{keys}",
    )
    check(
        "O3.2 last-event-wins: outliers applied -> не в problem-топе",
        ("preprocessing", "outliers", "warning", 1) not in keys,
        f"{keys}",
    )
    check("O3.3 фантомный узел исключён", all(item.node_id != "нет_такого_узла" for item in top), f"{keys}")
    check(
        "O3.4 неизвестный event_type не создаёт статуса",
        ("validation", "formats", "warning", 1) in keys and all(item.status != "что-то_иное" for item in top),
        f"{keys}",
    )
    # top_limit: 3 problem-узла, лимит 2 -- первые 2 по (count desc, stage, node)
    events_more = {
        "RA": [ev("correction_previewed", "eda", "seasonality", "RA", BASE - timedelta(minutes=5))],
        "RB": [ev("correction_previewed", "eda", "distribution", "RB", BASE - timedelta(minutes=5))],
        "RC": [ev("correction_previewed", "eda", "structural", "RC", BASE - timedelta(minutes=5))],
    }
    top2 = build_admin_overview(
        [{"run_id": "RA"}, {"run_id": "RB"}, {"run_id": "RC"}],
        events_more, [], now=BASE, period_days=30, top_limit=2,
    ).top_problem_nodes
    check(
        "O3.5 top_limit=2 обрезает и тай-брейк stage/node asc",
        [(i.node_id) for i in top2] == ["distribution", "seasonality"],
        f"{[i.node_id for i in top2]}",
    )


# ── O4: §7.1/§7.2 частоты из журнала наблюдений ──────────────────────


def oracle_mentor_frequencies() -> None:
    obs = [
        {"run_id": MY_RUN, "obs_kind": "next_step", "rule_id": "regularity_before_decomposition", "stage": "preprocessing", "node_id": None, "severity": ""},
        {"run_id": MY_RUN, "obs_kind": "next_step", "rule_id": "regularity_before_decomposition", "stage": "preprocessing", "node_id": None, "severity": ""},
        {"run_id": MY_RUN2, "obs_kind": "next_step", "rule_id": "modeling_selected_without_backtest", "stage": "modeling", "node_id": None, "severity": ""},
        # sanity: по правилу 2, по узлу 1 (второй -- без node_id)
        {"run_id": MY_RUN, "obs_kind": "sanity_warning", "rule_id": "no_effect", "stage": "preprocessing", "node_id": "missing", "severity": "warning"},
        {"run_id": MY_RUN, "obs_kind": "sanity_warning", "rule_id": "no_effect", "stage": "preprocessing", "node_id": None, "severity": "warning"},
        {"run_id": MY_RUN2, "obs_kind": "sanity_warning", "rule_id": "over_aggressive", "stage": "preprocessing", "node_id": "outliers", "severity": "warning"},
        # чужой obs_kind -- игнорируется обеими проекциями
        {"run_id": MY_RUN, "obs_kind": "какой-то_шум", "rule_id": "no_effect", "stage": "preprocessing", "node_id": "missing", "severity": "warning"},
    ]
    overview = build_admin_overview([{"run_id": MY_RUN}, {"run_id": MY_RUN2}], {}, obs, now=BASE, period_days=30)
    ns = [(i.rule_id, i.count) for i in overview.next_step_frequency]
    check(
        "O4.1 next_step ТОЧНО [(regularity,2), (modeling,1)] -- sanity/шум не смешаны",
        ns == [("regularity_before_decomposition", 2), ("modeling_selected_without_backtest", 1)],
        f"{ns}",
    )
    sbr = [(i.rule_id, i.count) for i in overview.sanity_by_rule]
    check(
        "O4.2 sanity по правилу ТОЧНО [(no_effect,2), (over_aggressive,1)]",
        sbr == [("no_effect", 2), ("over_aggressive", 1)],
        f"{sbr}",
    )
    sbn = [(i.stage, i.node_id, i.count) for i in overview.sanity_by_node]
    check(
        "O4.3 sanity по узлу: наблюдение без node_id не атрибутируется",
        ("preprocessing", "missing", 1) in sbn and ("preprocessing", "outliers", 1) in sbn and len(sbn) == 2,
        f"{sbn}",
    )
    check("O4.4 шум не попал ни в одну проекцию", all(i.rule_id != "какой-то_шум" for i in overview.sanity_by_rule) and all(i.node_id != "какой-то_шум" for i in overview.sanity_by_node))


# ── O5: §9 предпочтения Прогнозирования ──────────────────────────────


def oracle_forecast_frequencies() -> None:
    events = {
        MY_RUN: [
            ev("forecast_generated", "forecasting", None, MY_RUN, BASE - timedelta(minutes=20), model_id="naive_ts", horizon=30, alpha=0.95),
            ev("forecast_generated", "forecasting", None, MY_RUN, BASE - timedelta(minutes=10), model_id="naive_ts", horizon=30, alpha=0.8),
            ev("forecast_compared", "forecasting", None, MY_RUN, BASE - timedelta(minutes=5), model_id="ets"),  # чужой тип -- не считается
        ],
        MY_RUN2: [
            ev("forecast_generated", "forecasting", None, MY_RUN2, BASE - timedelta(minutes=8), model_id="ets", horizon=7),  # без alpha
            ev("forecast_generated", "forecasting", None, MY_RUN2, BASE - timedelta(minutes=7), model_id="", horizon=None),  # пустые -- пропуск
        ],
        "RUN-GHOST": [
            ev("forecast_generated", "forecasting", None, "RUN-GHOST", BASE - timedelta(minutes=1), model_id="призрак", horizon=1, alpha=0.5),
        ],
    }
    runs = [{"run_id": MY_RUN}, {"run_id": MY_RUN2}]
    overview = build_admin_overview(runs, events, [], now=BASE, period_days=30)
    models = [(i.value, i.count) for i in overview.forecasting_model_frequency]
    check("O5.1 модели ТОЧНО [(naive_ts,2), (ets,1)] -- пустые не считаются", models == [("naive_ts", 2), ("ets", 1)], f"{models}")
    check("O5.2 события-призраки (не из runs) не считаются", all(v != "призрак" for v, _ in models), f"{models}")
    horizons = [(i.value, i.count) for i in overview.forecasting_horizon_frequency]
    check("O5.3 горизонты ТОЧНО [('30',2), ('7',1)]", horizons == [("30", 2), ("7", 1)], f"{horizons}")
    alphas = [(i.value, i.count) for i in overview.forecasting_alpha_frequency]
    check("O5.4 alpha ТОЧНО [('0.8',1), ('0.95',1)]", alphas == [("0.8", 1), ("0.95", 1)], f"{alphas}")


# ── O6: §9 банк кейсов ───────────────────────────────────────────────


def oracle_case_bank() -> None:
    def completed_run(run_id: str, backtests: list[dict], status: str = "completed") -> tuple[dict, list[dict]]:
        run = {"run_id": run_id, "status": status, "dataset_name": "meteo_2024.csv", "created_at": iso(BASE - timedelta(days=1))}
        events = [
            ev(bt["type"], "modeling", "backtest", run_id, BASE - timedelta(minutes=bt["ago"]), mape=bt.get("mape"), model_id="ets")
            for bt in backtests
        ]
        return run, events

    # (а) чистый кандидат
    run, events = completed_run(MY_RUN, [{"type": "backtest_run", "ago": 60, "mape": 12.5}])
    # (б) два бэктеста: последний финален (плохой 40 -> хороший 8): кандидат
    run2, events2 = completed_run(MY_RUN2, [
        {"type": "backtest_run", "ago": 120, "mape": 40.0},
        {"type": "backtest_run", "ago": 30, "mape": 8.0},
    ])
    # (в) обратный порядок: последний плохой (50) -> НЕ кандидат
    run3, events3 = completed_run(MY_RUN3, [
        {"type": "backtest_run", "ago": 120, "mape": 5.0},
        {"type": "backtest_run", "ago": 30, "mape": 50.0},
    ])
    # (г) не-completed -- не кандидат
    run4, events4 = completed_run("RUN-CERT8DD", [{"type": "backtest_run", "ago": 60, "mape": 1.0}], status="active")
    # (д) бэктест без mape -- нет доказательства
    run5, events5 = completed_run("RUN-CERT8EE", [{"type": "backtest_run", "ago": 60}])
    # (е) нечитаемый mape
    run6, events6 = completed_run("RUN-CERT8FF", [{"type": "backtest_run", "ago": 60, "mape": "абс"}])
    runs = [run, run2, run3, run4, run5, run6]
    all_events = {MY_RUN: events, MY_RUN2: events2, MY_RUN3: events3, "RUN-CERT8DD": events4, "RUN-CERT8EE": events5, "RUN-CERT8FF": events6}
    obs = [{"run_id": MY_RUN, "obs_kind": "sanity_warning", "rule_id": "no_effect", "stage": "preprocessing", "node_id": "missing", "severity": "warning"}]
    candidates = select_case_bank_candidates(runs, all_events, obs, max_backtest_mape=30.0, max_warning_nodes=2, max_sanity_warnings=2)
    ids = [c.run_id for c in candidates]
    check("O6.1 чистый кандидат отобран", MY_RUN in ids, f"{ids}")
    check("O6.2 последний backtest финален: 40->8 кандидат, 5->50 нет", MY_RUN2 in ids and MY_RUN3 not in ids, f"{ids}")
    check("O6.3 не-completed исключён", "RUN-CERT8DD" not in ids, f"{ids}")
    check("O6.4 без mape и с нечитаемым mape -- нет доказательства, исключены", "RUN-CERT8EE" not in ids and "RUN-CERT8FF" not in ids, f"{ids}")
    cand_a = next(c for c in candidates if c.run_id == MY_RUN)
    check("O6.5 evidence заполнена фактом корпуса", abs(cand_a.backtest_mape - 12.5) < 1e-9 and cand_a.sanity_warnings == 1 and cand_a.dataset_name == "meteo_2024.csv", f"{cand_a}")
    # строковый mape -- доказательство (JSON-значение движку скармливается как есть)
    run7, events7 = completed_run("RUN-CERT8GG", [{"type": "backtest_run", "ago": 60, "mape": "17.25"}])
    cand7 = select_case_bank_candidates([run7], {"RUN-CERT8GG": events7}, [], max_backtest_mape=30.0)
    check("O6.6 строковый числовой mape принимается движком", len(cand7) == 1 and abs(cand7[0].backtest_mape - 17.25) < 1e-9, f"{cand7}")
    # границы порогов: == включительно по всем трём критериям
    cand_edge = select_case_bank_candidates(
        [run], {MY_RUN: events}, obs, max_backtest_mape=12.5, max_warning_nodes=0, max_sanity_warnings=1
    )
    check("O6.7 границы == включительны (mape/warnings/sanity)", len(cand_edge) == 1, f"{cand_edge}")
    cand_strict = select_case_bank_candidates([run], {MY_RUN: events}, obs + [dict(obs[0])], max_sanity_warnings=1)
    check("O6.8 sanity 2 > порога 1 -- исключён", len(cand_strict) == 0, f"{cand_strict}")
    # warning-узлы считаются финальными статусами
    run_warn, events_warn = completed_run("RUN-CERT8HH", [{"type": "backtest_run", "ago": 60, "mape": 10.0}])
    events_warn = events_warn + [
        ev("correction_previewed", "preprocessing", "missing", "RUN-CERT8HH", BASE - timedelta(minutes=50)),
        ev("correction_previewed", "preprocessing", "outliers", "RUN-CERT8HH", BASE - timedelta(minutes=49)),
        ev("correction_previewed", "preprocessing", "smoothing", "RUN-CERT8HH", BASE - timedelta(minutes=48)),
    ]
    cand_warn = select_case_bank_candidates([run_warn], {"RUN-CERT8HH": events_warn}, [], max_warning_nodes=2)
    cand_ok = select_case_bank_candidates([run_warn], {"RUN-CERT8HH": events_warn}, [], max_warning_nodes=3)
    check("O6.9 3 warning-узла: порог 2 отсекает, 3 пропускает", len(cand_warn) == 0 and len(cand_ok) == 1, f"warn={len(cand_warn)} ok={len(cand_ok)}")
    # сортировка: mape asc, тай-брейк run_id
    r_a, e_a = completed_run("RUN-B", [{"type": "backtest_run", "ago": 60, "mape": 10.0}])
    r_b, e_b = completed_run("RUN-A", [{"type": "backtest_run", "ago": 60, "mape": 10.0}])
    r_c, e_c = completed_run("RUN-C", [{"type": "backtest_run", "ago": 60, "mape": 2.0}])
    sorted_c = select_case_bank_candidates([r_a, r_b, r_c], {"RUN-A": e_b, "RUN-B": e_a, "RUN-C": e_c}, [])
    check("O6.10 сортировка mape asc + run_id тай-брейк", [c.run_id for c in sorted_c] == ["RUN-C", "RUN-A", "RUN-B"], f"{[c.run_id for c in sorted_c]}")
    # sanity чужих запусков не текут
    leaked = select_case_bank_candidates([r_a], {"RUN-B": e_a}, [
        {"run_id": "ДРУГОЙ", "obs_kind": "sanity_warning", "rule_id": "no_effect", "stage": "preprocessing", "node_id": "missing", "severity": "warning"}
    ] * 5, max_sanity_warnings=2)
    check("O6.11 sanity чужих run_id не атрибутируются", len(leaked) == 1 and leaked[0].sanity_warnings == 0, f"{leaked}")
    # NaN mape: фиксация фактического поведения (находка F-1)
    r_nan, e_nan = completed_run("RUN-NAN", [{"type": "backtest_run", "ago": 60, "mape": float("nan")}])
    cand_nan = select_case_bank_candidates([r_nan], {"RUN-NAN": e_nan}, [])
    check(
        "O6.12 НАХОДКА F-1: NaN mape проходит порог (float('nan') > x == False)",
        len(cand_nan) == 1,
        f"candidates={cand_nan}",
    )


def main() -> int:
    oracle_runs_by_status()
    oracle_stage_time()
    oracle_top_problem_nodes()
    oracle_mentor_frequencies()
    oracle_forecast_frequencies()
    oracle_case_bank()
    failed = [r for r in _RESULTS if not r[1]]
    print(f"\n=== Оракулы движка: {_RESULTS and ''}{len(_RESULTS) - len(failed)}/{len(_RESULTS)} PASSED ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
