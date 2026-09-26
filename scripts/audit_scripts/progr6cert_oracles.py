# scripts/audit_scripts/progr6cert_oracles.py
"""Оракулные тесты независимой сертификации Task PROGR-6 (2026-09-26).

Методология PROGR-1-CERT/PROGR-2/PROGR-3-CERT/OUTL-1-CERT: оракул --
независимая проверка реализованного поведения на СВОИХ данных (не
копирование assert-ов коллеги):

  OR-1  Целостность реестров: узлы всех on_demand-правил существуют в
        графе пайплайна (детектор «мёртвых правил»: фантомная пара
        (stage, node) отфильтрована is_known_node -- правило молчит
        вечно); типы событий _EVENT_STATUS_MAP реально испускаются
        (TRACE_ROUTES хука + FORECAST_EVENT_TYPES + run-level);
        реестры правил совпадают со спецификацией §7.1/§7.2.
  OR-2  Независимая реимплементация трёх sanity-правил §7.2 (чистая
        математика спецификации) на 500 рандомизированных preview-исходах
        (fixed seed) + детерминированные границы (ровно 0.2/0.3,
        std_after=0, нулевые строки, рост строк).
  OR-3  Независимая реимплементация окна «метаний» на 300 рандомизированных
        потоках событий (fixed seed): границы окна, apply-снятие,
        наивный ts, битый ts, TraceEvent-объекты, дубли стратегий.
        Плюс документирующие семантику случаи (cross-node, apply вне окна).
  OR-4  Зеркало derive_node_statuses: фикстура 12 событий -- ожидаемый
        словарь статусов; ТОТ ЖЕ ожидаемый словарь зашит в
        packages/ui/lib/progr6cert_oracles.test.ts (кросс-слойная
        сверка бэкенд/фронтенд на идентичной фикстуре).
  OR-5  Живая проба API (TestClient): 404/200/422 контракты, ОДНА
        рекомендация §7.1, thrashing в ответе, sanity-check с реальной
        формой preview-ответа Мастера (поля схем DatasetXCorrectionResponse),
        границы «ровно 30%» / «ровно 5x» через API.
  OR-6  Конфиг порогов §12 п.7: канонические значения; fail-closed
        матрица (нет файла / битый YAML / нет ключа / строка / bool);
        документирование дегенеративных числовых порогов (находка N-3).

Прогон: python scripts/audit_scripts/progr6cert_oracles.py
Успех:  ORACLES: 6/6 PASSED (exit 0); иначе -- перечень упавших, exit 1.
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Изоляция среды ДО импорта apps.api (паттерн коллеги: DATABASE_URL в CI
# может быть занят инфраструктурой -- N-8 PROGR-5-CERT).
_tmp = tempfile.mkdtemp(prefix="progr6cert-oracle-")
import os  # noqa: E402

os.environ["CISSTAT_DATA_DIR"] = str(Path(_tmp) / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)

from app.core import mentor_rules  # noqa: E402
from app.core.pipeline_graph import STAGE_NODES  # noqa: E402
from app.core.mentor_rules import (  # noqa: E402
    CorrectionOutcomeSummary,
    evaluate_history_warnings,
    evaluate_next_step,
    evaluate_sanity,
    load_mentor_config,
)
from apps.api import research_runs  # noqa: E402
from apps.api.trace_events import (  # noqa: E402
    FORECAST_EVENT_TYPES,
    make_trace_event,
)

SEED = 260926
_FAIL: list[str] = []


def check(case: str, cond: bool, detail: str = "") -> None:
    if not cond:
        _FAIL.append(f"{case}: {detail}")


# ── OR-1: целостность реестров (детектор мёртвых правил) ─────────────

# Пары (stage, node), читаемые условиями on_demand-правил (по исходнику
# условий _*_before_*/attention/without_*). Если пары нет в графе --
# derive_node_statuses никогда не выдаст такой ключ (is_known_node) и
# правило мёртвое.
RULE_NODE_REFS: dict[str, list[tuple[str, str]]] = {
    "regularity_before_decomposition": [
        ("preprocessing", "regularity"),
        ("preprocessing", "decomposition"),
    ],
    "forecast_not_compared_before_export": [
        ("forecasting", "forecast_generated"),
        ("forecasting", "forecast_compared"),
    ],
    "preprocessing_stationarity_before_modeling": [
        ("preprocessing", "stationarity"),
    ],
    "modeling_selected_without_backtest": [
        ("modeling", "selection"),
        ("modeling", "backtest"),
    ],
    "modeling_candidates_without_selection": [
        ("modeling", "backtest"),
        ("modeling", "selection"),
    ],
    "preprocessing_missing_attention": [("preprocessing", "missing")],
    "preprocessing_outliers_attention": [("preprocessing", "outliers")],
    "validation_sufficiency_attention": [("validation", "sufficiency")],
}


def or1_registry_integrity() -> None:
    check(
        "OR-1 набор on_demand-правил",
        {r.rule_id for r in mentor_rules.NEXT_STEP_RULES} == set(RULE_NODE_REFS),
        "реестр правил §7.1 разошёлся с таблицей ссылок оракула",
    )
    for rule in mentor_rules.NEXT_STEP_RULES:
        for stage, node in RULE_NODE_REFS.get(rule.rule_id, []):
            check(
                f"OR-1 узел {stage}/{node} правила {rule.rule_id}",
                stage in STAGE_NODES and node in STAGE_NODES[stage],
                "пара отсутствует в графе -- правило мёртвое",
            )
    # Каждая _EVENT_STATUS_MAP-запись -- реально испускаемый тип.
    emitted: set[str] = set(FORECAST_EVENT_TYPES)
    hook_src = (ROOT / "apps/api/trace_hook.py").read_text(encoding="utf-8")
    for token in {
        "upload_completed", "correction_applied", "correction_previewed",
        "profile_viewed", "backtest_run", "tuning_trial_completed",
        "model_selected", "model_card_generated", "mode_changed",
        "target_column_changed", "passport_captured",
        "run_paused", "run_resumed", "checkpoint_saved",
    }:
        if f'"{token}"' in hook_src:
            emitted.add(token)
    for event_type in mentor_rules._EVENT_STATUS_MAP:
        check(
            f"OR-1 событие {event_type} испускается платформой",
            event_type in emitted,
            "тип не найден ни в TRACE_ROUTES, ни в FORECAST_EVENT_TYPES",
        )
    # Реестры §7.2 и history -- дословно спецификации.
    check(
        "OR-1 SANITY_RULES",
        {r.rule_id for r in mentor_rules.SANITY_RULES}
        == {"no_effect", "over_aggressive", "excessive_data_loss"},
        "состав sanity-правил не §7.2",
    )
    check(
        "OR-1 HISTORY_RULES",
        {r.rule_id for r in mentor_rules.HISTORY_RULES} == {"thrashing_detected"},
        "history-реестр не §7.2",
    )
    check(
        "OR-1 триггеры",
        {r.trigger for r in mentor_rules.SANITY_RULES} == {"on_correction_result"}
        and {r.trigger for r in mentor_rules.HISTORY_RULES} == {"on_demand_with_history"}
        and {r.trigger for r in mentor_rules.NEXT_STEP_RULES} == {"on_demand"},
        "триггер-семейства перепутаны",
    )
    # thrashing: recommended_action осознанно None («как решать»).
    check(
        "OR-1 thrashing без deep-link",
        mentor_rules.HISTORY_RULES[0].recommended_action is None,
        "у «метаний» появился deep-link",
    )


# ── OR-2: независимая реимплементация sanity-правил §7.2 ─────────────

def ref_no_effect(o: CorrectionOutcomeSummary) -> bool:
    """§7.2 дословно: было что исправлять, но не изменилось ничего."""
    return o.affected_count_before > 0 and o.changed_count == 0


def ref_over_aggressive(o: CorrectionOutcomeSummary) -> bool:
    """§7.2: std схлопнулся ниже factor=0.2 от исходного."""
    if not (o.stats_before and o.stats_after):
        return False
    sb = o.stats_before.get("std")
    sa = o.stats_after.get("std")
    return bool(sb) and sa is not None and sa < sb * 0.2


def ref_excessive(o: CorrectionOutcomeSummary) -> bool:
    """§7.2: drop_rows удаляет долю > 0.3 (доля как (b-a)/b)."""
    if o.rows_before == 0:
        return False
    share = (o.rows_before - o.rows_after) / o.rows_before
    return o.strategy == "drop_rows" and share > 0.3


REFS = {
    "no_effect": ref_no_effect,
    "over_aggressive": ref_over_aggressive,
    "excessive_data_loss": ref_excessive,
}


def random_outcome(rng: random.Random) -> CorrectionOutcomeSummary:
    strategy = rng.choice(
        ["drop_rows", "median_mode", "mean_mode", "flag", "cap", "winsorize"]
    )
    affected = rng.choice([0, 1, 3, 10, 25, 60])
    if rng.random() < 0.15:
        changed = affected  # всё изменилось
    else:
        changed = rng.choice([0, affected, max(0, affected - rng.randint(0, 5))])
    rows_before = rng.choice([0, 1, 10, 70, 100, 240, 1000])
    if rng.random() < 0.2 and rows_before > 0:
        rows_after = rng.randint(0, rows_before)  # вплоть до полных потерь
    else:
        rows_after = rows_before
    if rng.random() < 0.25:
        stats_before = None
        stats_after = None
    else:
        std = rng.choice([0.0, 0.5, 2.0, 4.2, 5.0, 10.0])
        stats_before = {"mean": 10.0, "std": std, "median": 9.0}
        ratio = rng.choice([0.0, 0.05, 0.2, 0.199, 0.21, 0.5, 1.0, 1.4])
        stats_after = {"mean": 10.0, "std": std * ratio, "median": 9.0}
    return CorrectionOutcomeSummary(
        stage="preprocessing",
        node_id=rng.choice(["missing", "outliers", "regularity"]),
        strategy=strategy,
        method=None if rng.random() < 0.5 else rng.choice(["iqr", "zscore"]),
        affected_count_before=affected,
        changed_count=changed,
        still_affected_count=max(0, affected - changed),
        rows_before=rows_before,
        rows_after=rows_after,
        stats_before=stats_before,
        stats_after=stats_after,
    )


def or2_sanity_randomized() -> None:
    rng = random.Random(SEED)
    mismatches = 0
    for i in range(500):
        outcome = random_outcome(rng)
        got = {w.rule_id for w in evaluate_sanity(outcome)}
        want = {rid for rid, ref in REFS.items() if ref(outcome)}
        if got != want:
            mismatches += 1
            check(
                f"OR-2 рандом #{i}",
                False,
                f"исход={outcome!r} движок={sorted(got)} оракул={sorted(want)}",
            )
            if mismatches >= 3:
                break
    # Детерминированные границы на своих данных.
    exact_over = CorrectionOutcomeSummary(
        stage="preprocessing", node_id="missing", strategy="median_mode",
        affected_count_before=4, changed_count=4, still_affected_count=0,
        rows_before=99, rows_after=99,
        stats_before={"std": 7.3}, stats_after={"std": 7.3 * 0.2},  # ровно граница
    )
    check("OR-2 граница 0.2 -- тишина", not ref_over_aggressive(exact_over)
          and all(w.rule_id != "over_aggressive" for w in evaluate_sanity(exact_over)),
          "движок/оракул расходятся на точной границе 0.2")
    zero_std_after = CorrectionOutcomeSummary(
        stage="preprocessing", node_id="outliers", strategy="cap",
        affected_count_before=9, changed_count=9, still_affected_count=0,
        rows_before=50, rows_after=50,
        stats_before={"std": 4.0}, stats_after={"std": 0.0},
    )
    check("OR-2 std_after=0 срабатывает",
          ref_over_aggressive(zero_std_after)
          and any(w.rule_id == "over_aggressive" for w in evaluate_sanity(zero_std_after)),
          "переглаживание до нулевой дисперсии не поймано")
    growth = CorrectionOutcomeSummary(
        stage="preprocessing", node_id="regularity", strategy="drop_rows",
        affected_count_before=5, changed_count=5, still_affected_count=0,
        rows_before=100, rows_after=150,  # строки ДОБАВИЛИСЬ (fictitious_zero)
    )
    check("OR-2 рост строк -- тишина",
          not ref_excessive(growth)
          and all(w.rule_id != "excessive_data_loss" for w in evaluate_sanity(growth)),
          "отрицательная доля потерь триггерит правило")


# ── OR-3: независимая реимплементация окна «метаний» ─────────────────

def _ref_parse_ts(raw):
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ref_thrashing(events, *, now, window_minutes=10.0, need=3) -> bool:
    """Каноническая лямбда §7.2: >= need разных стратегий preview в окне,
    ни одного correction_applied в окне."""
    ws = now - timedelta(minutes=window_minutes)
    strategies: list[str] = []
    has_apply = False
    for event in events:
        d = event.to_dict() if hasattr(event, "to_dict") else event
        if not isinstance(d, dict):
            continue
        ts = _ref_parse_ts(d.get("ts"))
        if d.get("event_type") == "correction_applied":
            if ts is not None and ts >= ws:
                has_apply = True
            continue
        if d.get("event_type") != "correction_previewed":
            continue
        if ts is None or ts < ws:
            continue
        s = (d.get("payload") or {}).get("strategy")
        if isinstance(s, str) and s and s not in strategies:
            strategies.append(s)
    return len(strategies) >= need and not has_apply


def random_stream(rng: random.Random, now: datetime) -> list:
    pool = ["median_mode", "mean_mode", "drop_rows", "flag", "cap", "interpolate"]
    events: list = []
    for _ in range(rng.randint(0, 12)):
        kind = rng.random()
        minutes = rng.choice([0, 3, 5, 9.999, 10, 10.001, 12, 25, 60])
        ts = (now - timedelta(minutes=minutes)).isoformat()
        if kind < 0.6:
            payload = {"strategy": rng.choice(pool)}
            if rng.random() < 0.15:
                payload = {}  # preview без стратегии -- не считается
            events.append(
                {
                    "ts": ts if rng.random() < 0.8 else ts[:-6],  # 20% naive
                    "stage": "preprocessing",
                    "node_id": rng.choice(["missing", "outliers", "regularity"]),
                    "event_type": "correction_previewed",
                    "payload": payload,
                }
            )
        elif kind < 0.8:
            events.append(
                {
                    "ts": ts,
                    "stage": "preprocessing",
                    "node_id": "missing",
                    "event_type": "correction_applied",
                    "payload": {"strategy": rng.choice(pool)},
                }
            )
        else:
            events.append(
                {
                    "ts": rng.choice(["not-a-timestamp", ""]),
                    "stage": "preprocessing",
                    "node_id": "missing",
                    "event_type": "correction_previewed",
                    "payload": {"strategy": rng.choice(pool)},
                }
            )
    if rng.random() < 0.2:
        fresh = (now - timedelta(minutes=1)).isoformat()
        events.append(
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-CERT0001", strategy=rng.choice(pool), ts=fresh,
            )
        )
    return events


def or3_thrashing_randomized() -> None:
    rng = random.Random(SEED + 1)
    now = datetime.now(timezone.utc)
    mismatches = 0
    for i in range(300):
        stream = random_stream(rng, now)
        got = rule_thrashing_call(stream, now)
        want = ref_thrashing(stream, now=now)
        if got != want:
            mismatches += 1
            check(f"OR-3 поток #{i}", False, "движок и оракул разошлись")
            if mismatches >= 3:
                break
    # Семантика-документация (мои данные, другие стратегии -- cap/ffill/sort):
    def ev(strategy: str, node: str, minutes: float) -> dict:
        return {
            "ts": (now - timedelta(minutes=minutes)).isoformat(),
            "stage": "preprocessing",
            "node_id": node,
            "event_type": "correction_previewed",
            "payload": {"strategy": strategy},
        }

    cross_node = [ev("cap", "missing", 9), ev("ffill", "outliers", 8), ev("sort", "regularity", 7)]
    check(
        "OR-3 cross-node: 3 стратегии на 3 узлах -> срабатывает (канон-лямбда §7.2)",
        rule_thrashing_call(cross_node, now) and ref_thrashing(cross_node, now=now),
        "семантика cross-node изменилась",
    )
    apply_outside = cross_node + [
        {
            "ts": (now - timedelta(minutes=25)).isoformat(),
            "stage": "preprocessing", "node_id": "missing",
            "event_type": "correction_applied", "payload": {"strategy": "cap"},
        }
    ]
    check(
        "OR-3 apply вне окна не снимает предупреждение",
        rule_thrashing_call(apply_outside, now),
        "apply вне окна ошибочно снимает",
    )
    apply_exact = cross_node + [
        {
            "ts": (now - timedelta(minutes=10)).isoformat(),  # ровно window_start
            "stage": "preprocessing", "node_id": "missing",
            "event_type": "correction_applied", "payload": {"strategy": "cap"},
        }
    ]
    check(
        "OR-3 apply ровно на границе окна снимает (>=)",
        not rule_thrashing_call(apply_exact, now),
        "граница apply инвертирована",
    )
    preview_boundary = [
        ev("cap", "missing", 9),
        ev("ffill", "missing", 8),
        ev("sort", "missing", 10.0),  # ровно window_start -- тоже в окне
    ]
    check(
        "OR-3 preview ровно на границе окна учитывается (не < ws)",
        rule_thrashing_call(preview_boundary, now),
        "preview на границе окна потерян",
    )


def rule_thrashing_call(stream: list, now: datetime):
    """Движок с фиксированным now; результат нормализуется к bool
    (движок отдаёт SanityWarning | None, оракул -- bool)."""
    return mentor_rules.rule_thrashing(stream, now=now) is not None


# ── OR-4: зеркало derive_node_statuses (кросс-слойная фикстура) ──────

# Фикстура И ожидание дублированы в packages/ui/lib/progr6cert_oracles.test.ts;
# расхождение зеркал ловится любой из двух сторон.
MIRROR_FIXTURE: list[dict] = [
    {"ts": "2026-09-26T10:00:00+00:00", "stage": "upload",
     "node_id": "structure_confirmed", "event_type": "upload_completed", "payload": {}},
    {"ts": "2026-09-26T10:05:00+00:00", "stage": "preprocessing",
     "node_id": "missing", "event_type": "correction_previewed", "payload": {}},
    {"ts": "2026-09-26T10:09:00+00:00", "stage": "preprocessing",
     "node_id": "missing", "event_type": "correction_applied", "payload": {}},
    {"ts": "2026-09-26T10:12:00+00:00", "stage": "eda",
     "node_id": "descriptive", "event_type": "profile_viewed", "payload": {}},
    {"ts": "2026-09-26T10:14:00+00:00", "stage": "preprocessing",
     "node_id": None, "event_type": "run_paused", "payload": {}},
    {"ts": "2026-09-26T10:15:00+00:00", "stage": "forecasting",
     "node_id": None, "event_type": "forecast_generated", "payload": {}},
    {"ts": "2026-09-26T10:16:00+00:00", "stage": "preprocessing",
     "node_id": "phantom", "event_type": "correction_applied", "payload": {}},
    {"ts": "2026-09-26T10:17:00+00:00", "stage": "validation",
     "node_id": "sufficiency", "event_type": "unknown_future_type", "payload": {}},
    {"ts": "2026-09-26T10:18:00+00:00", "stage": "modeling",
     "node_id": "backtest", "event_type": "backtest_run", "payload": {}},
    {"ts": "2026-09-26T10:19:00+00:00", "stage": "modeling",
     "node_id": "selection", "event_type": "model_selected", "payload": {}},
    {"ts": "2026-09-26T10:20:00+00:00", "stage": "forecasting",
     "node_id": None, "event_type": "forecast_exported", "payload": {}},
    {"ts": "2026-09-26T10:21:00+00:00", "stage": "preprocessing",
     "node_id": "outliers", "event_type": "correction_previewed", "payload": {}},
]

# Ожидание ПО СЛЕДНЕМУ событию узла (позднее перезаписывает раннее).
MIRROR_EXPECTED: dict[str, str] = {
    "upload/structure_confirmed": "done",
    "preprocessing/missing": "done",        # previewed -> applied
    "eda/descriptive": "running",
    "forecasting/forecast_generated": "done",     # узел из типа (node_id=None)
    "forecasting/forecast_exported": "done",      # узел из типа (node_id=None)
    "modeling/backtest": "done",
    "modeling/selection": "done",
    "preprocessing/outliers": "warning",
    # phantom/unknown_future_type/run_paused -- честно пропущены.
}


def or4_derive_mirror() -> None:
    got = mentor_rules.derive_node_statuses(MIRROR_FIXTURE)
    check("OR-4 бэкенд-зеркало", got == MIRROR_EXPECTED,
          f"got={got!r} want={MIRROR_EXPECTED!r}")


# ── OR-5: живая проба API (TestClient, слой 2 + sanity-check) ────────

def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _seed_run(store, run_id: str) -> None:
    store.upsert_run(
        research_runs.ResearchRun(
            run_id=run_id,
            session_id="cert-session",
            dataset_fingerprint="c" * 64,
            dataset_name="cert_progr6.csv",
            created_at=_iso(60),
            last_active_at=_iso(1),
        )
    )


def or5_api_live_probe() -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as client:
        # 404 неизвестный запуск -- без рекомендаций по чужому run_id.
        r404 = client.get("/v1/progress/runs/RUN-NOTHERE0/mentor/next-step")
        check("OR-5 404 неизвестный запуск", r404.status_code == 404,
              f"status={r404.status_code}")

        store = research_runs.get_research_run_store()
        _seed_run(store, "RUN-CERT0001")
        # Мои события: upload -> preview regularity (не решена) ->
        # 3 preview-стратегии на missing 8..6 минут назад -> «мечется».
        store.append_event(
            "RUN-CERT0001",
            make_trace_event("upload_completed", stage="upload",
                             node_id="structure_confirmed", run_id="RUN-CERT0001"),
        )
        store.append_event(
            "RUN-CERT0001",
            make_trace_event("correction_previewed", stage="preprocessing",
                             node_id="regularity", run_id="RUN-CERT0001",
                             strategy="asfreq", ts=_iso(9)),
        )
        for strategy, minutes in (("drop_rows", 8), ("fictitious_zero", 7), ("ffill", 6)):
            store.append_event(
                "RUN-CERT0001",
                make_trace_event("correction_previewed", stage="preprocessing",
                                 node_id="missing", run_id="RUN-CERT0001",
                                 strategy=strategy, ts=_iso(minutes)),
            )
        r = client.get("/v1/progress/runs/RUN-CERT0001/mentor/next-step")
        check("OR-5 next-step 200", r.status_code == 200, f"status={r.status_code}")
        data = r.json()
        check(
            "OR-5 рекомендация regularity_before_decomposition (§7.1)",
            data["recommendation"] is not None
            and data["recommendation"]["rule_id"] == "regularity_before_decomposition"
            and data["recommendation"]["recommended_action"] == "preprocessing.regularity",
            f"recommendation={data.get('recommendation')!r}",
        )
        check(
            "OR-5 ОДНА рекомендация (инвариант §7.1)",
            data["recommendation"] is not None,
            "ответ без единственной рекомендации",
        )
        check(
            "OR-5 phase_text + summary в ответе",
            bool(data["phase_text"]) and data["summary"]["stage"] == "preprocessing"
            and data["summary"]["total_nodes"] == len(STAGE_NODES["preprocessing"]),
            "сводка стадии не пересказывает граф",
        )
        warn_ids = [w["rule_id"] for w in data["history_warnings"]]
        check(
            "OR-5 thrashing в history_warnings (панель, не инлайн)",
            "thrashing_detected" in warn_ids,
            f"history_warnings={warn_ids!r}",
        )

        # sanity-check с реальной формой preview-ответа Мастера пропусков
        # (поля DatasetMissingCorrectionResponse; статистики -- «худшая»
        # колонка worstStdStats: std 4.2 -> 0.7, падение в 6 раз > 5).
        master_like = {
            "stage": "preprocessing",
            "node_id": "missing",
            "strategy": "median_mode",
            "method": None,
            "affected_count_before": 13,
            "changed_count": 0,
            "still_affected_count": 13,
            "rows_before": 240,
            "rows_after": 240,
            "stats_before": {"mean": 51.3, "std": 4.2, "median": 50.9},
            "stats_after": {"mean": 51.3, "std": 0.7, "median": 50.9},
        }
        r2 = client.post("/v1/progress/mentor/sanity-check", json=master_like)
        check("OR-5 sanity-check 200", r2.status_code == 200, f"status={r2.status_code}")
        ids2 = [w["rule_id"] for w in r2.json()["warnings"]]
        check(
            "OR-5 no_effect + over_aggressive одновременно (весь список)",
            "no_effect" in ids2 and "over_aggressive" in ids2,
            f"warnings={ids2!r}",
        )
        severities = {w["rule_id"]: w["severity"] for w in r2.json()["warnings"]}
        check(
            "OR-5 severity warning у обоих",
            severities.get("no_effect") == "warning"
            and severities.get("over_aggressive") == "warning",
            f"severities={severities!r}",
        )

        # drop_rows 40% потерь через API + границы «ровно 30%» -- тишина.
        r3 = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing", "node_id": "missing",
                "strategy": "drop_rows", "affected_count_before": 80,
                "changed_count": 80, "still_affected_count": 0,
                "rows_before": 200, "rows_after": 120,
            },
        )
        check(
            "OR-5 drop_rows 40% -> excessive_data_loss",
            any(w["rule_id"] == "excessive_data_loss" for w in r3.json()["warnings"]),
            f"warnings={r3.json()['warnings']!r}",
        )
        r4 = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing", "node_id": "missing",
                "strategy": "drop_rows", "affected_count_before": 60,
                "changed_count": 60, "still_affected_count": 0,
                "rows_before": 200, "rows_after": 140,  # ровно 30%
            },
        )
        check(
            "OR-5 ровно 30% -- тишина (граница >)",
            r4.json()["warnings"] == [],
            f"warnings={r4.json()['warnings']!r}",
        )
        # fail-closed 422 на фантомный узел/стадию.
        r5 = client.post(
            "/v1/progress/mentor/sanity-check",
            json={"stage": "preprocessing", "node_id": "no_such_node"},
        )
        r6 = client.post(
            "/v1/progress/mentor/sanity-check",
            json={"stage": "astral_plane", "node_id": "missing"},
        )
        check("OR-5 422 фантомный узел", r5.status_code == 422,
              f"status={r5.status_code}")
        check("OR-5 422 неизвестная стадия", r6.status_code == 422,
              f"status={r6.status_code}")


# ── OR-6: конфиг порогов §12 п.7 (fail-closed матрица) ───────────────

def or6_config() -> None:
    import yaml as _yaml

    config = load_mentor_config()
    check(
        "OR-6 канонические стартовые значения",
        config["sanity"]["over_aggressive"]["std_collapse_factor"] == 0.2
        and config["sanity"]["excessive_data_loss"]["max_removed_share"] == 0.3
        and config["history"]["thrashing"]["window_minutes"] == 10
        and config["history"]["thrashing"]["distinct_strategies"] == 3,
        "значения разошлись с §7.2/§12 п.7",
    )
    tmp = Path(tempfile.mkdtemp(prefix="progr6cert-cfg-"))
    base = json.dumps(config, ensure_ascii=False)

    def write(name: str, text: str) -> Path:
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    no_keys = json.loads(base)
    del no_keys["sanity"]["excessive_data_loss"]
    matrix = {
        "нет файла": tmp / "absent.yaml",
        "битый YAML": write("broken.yaml", "sanity: [unclosed"),
        "нет секции": write("no_section.yaml", json.dumps(no_keys)),
        "строковый порог": write(
            "str.yaml",
            json.dumps({**config, "history": {"thrashing": {"window_minutes": "ten",
                                                            "distinct_strategies": 3}}}),
        ),
        "bool-порог": write(
            "bool.yaml",
            json.dumps({**config, "sanity": {"over_aggressive": {"std_collapse_factor": True},
                                             "excessive_data_loss": {"max_removed_share": 0.3}}}),
        ),
    }
    for case, path in matrix.items():
        try:
            load_mentor_config(path)
            check(f"OR-6 fail-closed: {case}", False, "ImportError не поднят")
        except ImportError:
            pass
        except Exception as exc:  # битый YAML может дать свой класс ошибки
            check(f"OR-6 fail-closed: {case}", False,
                  f"неожиданный {type(exc).__name__}: {exc}")

    # N-3 (документирование): числовые, но дегенеративные пороги проходят
    # загрузчик и меняют семантику -- distinct_strategies=1 тревожит с
    # первой же попытки. Не блокирует сертификацию: значения калибруются
    # ops-ом (§12 п.7), загрузчик гарантирует только «число, не хардкод».
    degenerate = write(
        "degenerate.yaml",
        _yaml.safe_dump({**config, "history": {"thrashing": {"window_minutes": 10,
                                                             "distinct_strategies": 1}}}),
    )
    patched = load_mentor_config(degenerate)
    original_config = mentor_rules.MENTOR_CONFIG
    try:
        mentor_rules.MENTOR_CONFIG = patched
        fired_on_first = mentor_rules.rule_thrashing(
            [{"ts": _iso(1), "stage": "preprocessing", "node_id": "missing",
              "event_type": "correction_previewed", "payload": {"strategy": "cap"}}],
        )
        check("OR-6 N-3: distinct_strategies=1 тревожит на первой попытке",
              fired_on_first is not None,
              "дегенеративный порог не применился -- семантика другая")
    finally:
        mentor_rules.MENTOR_CONFIG = original_config


# ── Точка входа ───────────────────────────────────────────────────────

def main() -> int:
    stages = [
        ("OR-1 реестры", or1_registry_integrity),
        ("OR-2 sanity §7.2 (500 рандом + границы)", or2_sanity_randomized),
        ("OR-3 thrashing (300 потоков + границы)", or3_thrashing_randomized),
        ("OR-4 зеркало derive_node_statuses", or4_derive_mirror),
        ("OR-5 живая проба API", or5_api_live_probe),
        ("OR-6 конфиг §12 п.7", or6_config),
    ]
    for name, fn in stages:
        try:
            fn()
            print(f"[RUN ] {name}")
        except Exception:
            _FAIL.append(f"{name}: НЕОЖИДАННОЕ ИСКЛЮЧЕНИЕ\n{traceback.format_exc()}")
    if _FAIL:
        print(f"ORACLES: FAILED ({len(_FAIL)} расхождений)")
        for failure in _FAIL:
            print(f"  - {failure}")
        return 1
    print(f"ORACLES: {len(stages)}/{len(stages)} PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
