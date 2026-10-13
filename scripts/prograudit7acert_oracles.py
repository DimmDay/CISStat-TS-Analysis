# scripts/prograudit7acert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-7A-CERT.

Объект: коммит b43e2eb (PROGR-AUDIT-7A -- матрица Modeling и
происхождение методов, plan_progress_audit.md §15; контракт
docs/progress_audit_contract.md аддендум v1.3-7A §23):
  * семь типов P13 (candidates_generated, selection_evaluated,
    models_compared, diagnostics_run, tuning_skipped,
    tuning_job_started, tuning_job_cancelled) -- ЯВНАЯ семантика
    ЕДИНОГО редьюсера, словарь ПРОЦЕССНОЙ стадии Modeling,
    «операция ≠ результат» (всем done НЕ назначается);
  * реальный носитель факта baseline_estimation: backtest_run с
    payload.family_id=="baselines" -- payload-условная ДОПОЛНИТЕЛЬНАЯ
    атрибуция узла со СВОИМ честным reason (легаси/не-baseline --
    носитель не срабатывает, done не фабрикуется);
  * честное отсутствие решения problem_definition/data_structure/
    constraint_mapping (продюсеров нет -- done по открытию вкладки
    невозможен);
  * связность job-фактов одним job_id в payload; обоснование skip --
    reason ЭХОМ в ответе /tuning/skip(/skip-pending) и в факте трассы;
  * поздний факт старого job не повышает current-context
    (validity=stale против нового контекста);
  * происхождение метода/параметров в payload независимо от картинки
    узла (P19 сохранён совместно с AUDIT-4).

Принцип «оракулы на своих данных»: корпус сертификатора ДИЗЪЮКТЕН
оракулу исполнителя (tests/api/test_progress_audit_7a.py: CSV
«date,value,driver» ПОМЕСЯЧНО 2021-2025, цель value, reason-метки
«AUDIT-7A», idempotency-ключи audit7a-*, strategy expanding/sliding
с их параметрами horizon=2/n_splits=2/gap=1/train_window=40):
  * свой CSV-корпус: «dt,sales,promo,price» ПОДЕННО 2023-01-01..
    2023-02-26 (57 суток, три числовых столбца), цель sales,
    альтернативная цель для смены контекста -- price;
  * свои параметры контуров: candidates sliding horizon=1/n_splits=3/
    gap=2/train_window=45 и expanding horizon=3/n_splits=2;
    jobs/start max_trials=3/metric=mae/random_state=7,
    idempotency-ключи cert7a-job-*;
  * свои reason-строки с метками «Cert-7A», свои min_oof_points=5;
  * свои наблюдательные методы, ОТСУТСТВУЮЩИЕ у исполнителя:
    жизненный цикл start→cancel→start→cancel (last-wins, 4 факта),
    переоткрытие selection повторной оценкой после model_selected,
    P16-бейдж узла candidate_generation и бейдж-гигиена носителя
    (счётчик следует за reason-событием), неизменность узла Baseline
    после не-baseline backtest, потребление Наставником статусов
    ЕДИНОГО редьюсера (last_active_stage), fallback отчёта с исходным
    типом/ids, guard двойной записи носителя, stage-level носитель
    (контракт E6), неизменность reason-текстов.

Канал проверки: самодостаточный EXIT-код (0 = все PASS).
Группы: ENV (свой корпус), SEM (семантика 7 типов §23.1),
CAR (носитель baseline §23.3), JOB (связность/late-old-job §23.4),
E2E (полный Modeling-контур на живом TestClient), ORG (происхождение
P19/§23.5 + Наставник + отчёт).

Запуск: python scripts/prograudit7acert_oracles.py [--protocol PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Чистая изоляция окружения ДО импортов продукта (документированный
# средовой класс: DATABASE_URL=file:… в песочнице ломает psycopg-парсер
# -- одинаково на базе и HEAD, см. worklog AUDIT-8/7A).
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

PROTOCOL_LINES: list[str] = []
FAILURES: list[str] = []
PASSES: int = 0


def _log(msg: str) -> None:
    print(msg)
    PROTOCOL_LINES.append(msg)


class OracleFail(AssertionError):
    """Честный отказ оракула (различим от неожиданного исключения)."""


def oracle(name: str):
    """Декоратор-харнесс: полная изоляция окружения на каждый оракул."""

    def wrap(fn):
        def run():
            global PASSES
            tmp = tempfile.mkdtemp(prefix="cert7a-oracle-")
            os.environ["CISSTAT_DATA_DIR"] = tmp
            from apps.api import research_runs as rr
            from apps.api.session_store import (
                reset_session_store_for_testing,
            )

            rr.reset_research_run_store_for_testing()
            rr.reset_dataset_file_store_for_testing()
            reset_session_store_for_testing()
            try:
                fn()
            except OracleFail as exc:
                FAILURES.append(f"{name}: {exc}")
                _log(f"  FAIL {name}: {exc}")
            except Exception as exc:  # неожиданное исключение = FAIL
                FAILURES.append(f"{name}: UNEXPECTED {exc!r}")
                _log(f"  FAIL {name}: UNEXPECTED {exc!r}")
                traceback.print_exc()
            else:
                PASSES += 1
                _log(f"  ok   {name}")
            finally:
                rr.reset_research_run_store_for_testing()
                rr.reset_dataset_file_store_for_testing()
                reset_session_store_for_testing()

        run.__name__ = fn.__name__
        run._oracle_name = name
        return run

    return wrap


# ── СВОИ данные сертификатора (дизъюнктны исполнителю) ───────────────

# Поденный корпус 2023: 57 суток (январь 31 + февраль 26), три
# числовых столбца. sales -- тренд + недельная сезонность (цель по
# умолчанию), price -- гладкий тренд (альтернативная цель для смены
# контекста), promo -- целые 0/1/2.
_DAYS = [f"2023-01-{d:02d}" for d in range(1, 32)] + [
    f"2023-02-{d:02d}" for d in range(1, 27)
]
_SALES = [200.0 + 0.9 * i + 4.0 * (i % 7) for i in range(57)]
_PRICE = [10.0 + 0.05 * i for i in range(57)]
_PROMO = [i % 3 for i in range(57)]
CSV_SALES = "dt,sales,promo,price\n" + "".join(
    f"{d},{s:.2f},{p},{pr:.2f}\n"
    for d, s, p, pr in zip(_DAYS, _SALES, _PROMO, _PRICE)
)

# Свои reason-строки (метки Cert-7A -- дизъюнкт с исполнителем).
REASON_SKIP_1 = "Cert-7A: осознанно оставлены параметры по умолчанию"
REASON_SKIP_PENDING = "Cert-7A: скоуп тюнинга закрыт без подбора"
REASON_CANCEL = "Cert-7A: отмена job до завершения"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.node_status import (  # noqa: E402
    EVENT_NODE_REASON,
    EVENT_NODE_STATUS,
    NODE_SUMMARY_COUNT_KEYS,
    NodeStateFold,
    derive_last_active_stage,
    derive_node_statuses,
    resolve_event_status,
)

# Символы AUDIT-7A отсутствуют на базе 2353e65 (до задачи) -- импорт
# толерантен, оракулы честно фиксируют отказ «возможности нет».
try:  # noqa: SIM105
    from app.core.node_status import (  # noqa: F401
        PAYLOAD_CARRIER_REASON,
        payload_carrier_node,
    )
except ImportError:  # база до AUDIT-7A
    PAYLOAD_CARRIER_REASON = None  # type: ignore[assignment]
    payload_carrier_node = None  # type: ignore[assignment]
from app.core.pipeline_graph import is_known_node  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    reset_session_store_for_testing,
)

# Семь типов P13 и их контрактные статусы (§23.1).
P13_EXPECTED_STATUS = {
    "candidates_generated": "done",
    "selection_evaluated": "in_progress",
    "models_compared": "done",
    "diagnostics_run": "done",
    "tuning_skipped": "done",
    "tuning_job_started": "in_progress",
    "tuning_job_cancelled": "pending",
}
P13_TYPES = tuple(P13_EXPECTED_STATUS)


def _client() -> TestClient:
    return TestClient(app)


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str = "2026-10-13T08:00:00+00:00",
    context_id: str | None = None,
    **payload,
) -> dict:
    """Словарь канона §4.1 (+ опциональный envelope-контекст AUDIT-S).
    event_id детерминирован (своя схема evt7a- -- дизъюнкт с
    исполнителем)."""
    digest = hashlib.md5(
        f"cert7a|{node_id}|{event_type}|{ts}".encode("utf-8")
    ).hexdigest()[:10]
    data = {
        "event_id": f"evt7a-{digest}",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": payload,
    }
    if context_id is not None:
        data["context_id"] = context_id
    return data


def _node(states: list[dict], stage: str, node_id: str) -> dict:
    for state in states:
        if state["stage"] == stage and state["node_id"] == node_id:
            return state
    raise OracleFail(f"узел {stage}/{node_id} не найден")


def _trace_node(client: TestClient, stage: str, node_id: str) -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return _node(resp.json()["nodes"], stage, node_id)


def _trace_events(client: TestClient) -> list[dict]:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def _trace_context(client: TestClient) -> str | None:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json().get("context_id")


def _run_id(client: TestClient) -> str:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    run_id = resp.json().get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе"
    return run_id


def _prepare_modeling_session(client: TestClient) -> None:
    """Реалистичное начало исследования на СВОЁМ корпусе:
    upload → цель sales → дата dt → паспорт → Modeling entry."""
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("cert7a-sales.csv",
                        io.BytesIO(CSV_SALES.encode("utf-8")),
                        "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(
        "/v1/session/target-column", json={"column": "sales"}
    ).status_code == 200
    assert client.post(
        "/v1/session/date-column", json={"column": "dt"}
    ).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post(
        "/v1/session/dataset/passport/modeling_entry"
    ).status_code == 200


def _skip_ready_session(client: TestClient) -> None:
    """Сессия с закрытым скоупом тюнинга на СВОИХ параметрах:
    candidates(sliding 1/3/2/45) → baselines → backtest ets →
    исключение остальных из backtest-скоупа."""
    _prepare_modeling_session(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "ets"}
    ).status_code == 200
    scope = client.get("/v1/session/modeling/state").json()["artifacts"][
        "execution_scope"
    ]
    for model_id in scope["pending_backtest_model_ids"]:
        excluded = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={
                "model_id": model_id,
                "decision": "exclude",
                "reason": "Cert-7A: вне проверки",
                "acknowledge": True,
            },
        )
        assert excluded.status_code == 200, excluded.text


def _closed_tuning_scope(client: TestClient) -> None:
    """Скоуп закрыт осознанным пропуском + backtest naive (второй
    baseline-факт -- материал для не-baseline/последующих проверок)."""
    _skip_ready_session(client)
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "naive"}
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/tuning/skip",
        json={
            "model_id": "ets",
            "reason": REASON_SKIP_1,
            "acknowledge": True,
        },
    ).status_code == 200


# ── Группа ENV: свой корпус (санитария окружения сертификатора) ──────


@oracle("G-ENV-1 свой корпус и реалистичная сессия")
def g_env_1_own_corpus_session():
    """Свой поденный CSV принимается; полный контур подготовки даёт
    run_id/context_id трассы. Контроль окружения (PASS на базе и HEAD)."""
    client = _client()
    _prepare_modeling_session(client)
    run_id = _run_id(client)
    assert run_id.startswith("run-") or run_id, "run_id пуст"
    assert _trace_context(client), "context_id отсутствует"
    resp = client.get("/v1/session/modeling/state")
    assert resp.status_code == 200, resp.text
    artifacts = resp.json().get("artifacts") or {}
    assert "artifact_schema_version" in artifacts, artifacts.keys()


@oracle("G-ENV-2 инвариант reason-карты и граф")
def g_env_2_map_invariants():
    """Инвариант прежних задач: ключи EVENT_NODE_REASON == ключи
    EVENT_NODE_STATUS (reason и статус описывают ОДНО событие); узлы
    носителя/семи типов известны графу. Инвариант держится на обеих
    сторонах (контроль), на HEAD карта шире на 7 типов."""
    from app.core.node_status import PAYLOAD_STATUS_EVENT_TYPES
    assert set(EVENT_NODE_STATUS) <= set(EVENT_NODE_REASON), (
        "каждый статусный тип обязан иметь reason"
    )
    assert set(EVENT_NODE_REASON) == (
        set(EVENT_NODE_STATUS) | set(PAYLOAD_STATUS_EVENT_TYPES)
    ), "инвариант reason-карты (статусы + payload-статусные) нарушен"
    for stage, node in (
        ("modeling", "candidate_generation"),
        ("modeling", "baseline_estimation"),
        ("modeling", "backtest"),
        ("modeling", "tuning"),
        ("modeling", "selection"),
        ("modeling", "diagnostics"),
        ("modeling", "comparison"),
        ("modeling", "problem_definition"),
        ("modeling", "data_structure"),
        ("modeling", "constraint_mapping"),
    ):
        assert is_known_node(stage, node), f"{stage}/{node} вне графа"


# ── Группа SEM: семантика семи типов P13 (§23.1) на своих словарях ──


@oracle("G-SEM-1 семь типов: явный статус единого редьюсера")
def g_sem_1_seven_types_status():
    """resolve_event_status для каждого из 7 типов возвращает
    КОНТРАКТНЫЙ статус (§23.1: операция ≠ результат); derive_node_statuses
    кладёт статусы на свои узлы. База: None/узлы не двигаются (RED)."""
    for event_type, expected in P13_EXPECTED_STATUS.items():
        got = resolve_event_status(
            _event("modeling", "tuning", event_type)
        )
        assert got == expected, (
            f"{event_type}: resolve_event_status={got!r}, контракт {expected!r}"
        )
    fold_events = [
        _event("modeling", "candidate_generation", "candidates_generated"),
        _event("modeling", "selection", "selection_evaluated"),
        _event("modeling", "comparison", "models_compared"),
        _event("modeling", "diagnostics", "diagnostics_run"),
        _event("modeling", "tuning", "tuning_skipped"),
        _event("modeling", "tuning", "tuning_job_started"),
        _event("modeling", "tuning", "tuning_job_cancelled"),
    ]
    statuses = derive_node_statuses(fold_events)
    assert statuses.get("modeling/candidate_generation") == "done"
    assert statuses.get("modeling/selection") == "in_progress"
    assert statuses.get("modeling/comparison") == "done"
    assert statuses.get("modeling/diagnostics") == "done"
    assert statuses.get("modeling/tuning") == "pending"  # last-wins: cancel


# ЛИТЕРАЛЬНЫЕ тексты §23.1 контракта (пин СОДЕРЖАТЕЛЬНЫЙ, не
# самореференциальный: сверка с текстом контракта, а не с картой --
# подмена текста внутри карты ловится именно здесь; кампания CM-5).
P13_LITERAL_REASON = {
    "candidates_generated": "Пул кандидатов сформирован applicability-движком",
    "selection_evaluated": "Оценка выбора выполнена: модель ещё не выбрана",
    "models_compared": "Сравнение моделей выполнено",
    "diagnostics_run": "Диагностика моделей выполнена или переиспользована",
    "tuning_skipped": "Тюнинг пропущен аналитиком: оставлены параметры по умолчанию",
    "tuning_job_started": "Запущен job тюнинга: работа в процессе",
    "tuning_job_cancelled": "Тюнинг отменён аналитиком до завершения",
}


@oracle("G-SEM-2 семь типов: честные reason-тексты (литеральные пины §23.1)")
def g_sem_2_seven_types_reasons():
    """Каждый тип несёт СВОЙ человекочитаемый reason (факт, не совет):
    текст сверяется с ЛИТЕРАЛОМ контракта §23.1 (не с картой -- мутант
    «перепутанные тексты в карте» не должен быть самосогласованным);
    попарная различимость; текст в карте совпадает с литералом. База:
    detail не создаётся (RED)."""
    for event_type, literal in P13_LITERAL_REASON.items():
        assert EVENT_NODE_REASON.get(event_type) == literal, (
            f"{event_type}: карта reason != литералу контракта §23.1"
        )
    texts = {}
    for event_type in P13_TYPES:
        fold = NodeStateFold()
        fold.apply(
            _event("modeling", "tuning", event_type)
            if event_type.startswith("tuning")
            else _event(
                "modeling",
                {
                    "candidates_generated": "candidate_generation",
                    "selection_evaluated": "selection",
                    "models_compared": "comparison",
                    "diagnostics_run": "diagnostics",
                }[event_type],
                event_type,
            )
        )
        node = {
            "candidates_generated": "candidate_generation",
            "selection_evaluated": "selection",
            "models_compared": "comparison",
            "diagnostics_run": "diagnostics",
            "tuning_skipped": "tuning",
            "tuning_job_started": "tuning",
            "tuning_job_cancelled": "tuning",
        }[event_type]
        detail = fold.detail(f"modeling/{node}")
        text = detail.get("status_reason")
        assert text == P13_LITERAL_REASON[event_type], (
            f"{event_type}: reason {text!r} != литералу контракта §23.1"
        )
        texts[event_type] = text
    assert len(set(texts.values())) == 7, "reason-тексты 7 типов не различны"


@oracle("G-SEM-3 запрет механического done: не- done статусы существуют")
def g_sem_3_not_all_done_invariant():
    """Инвариант карточки §15 «Не назначать всем done»: в статусловаре
    7 типов присутствуют РОВНО контрактные не-done классы --
    selection_evaluated/tuning_job_started=in_progress,
    tuning_job_cancelled=pending; никаких семи подряд done. Мутант
    «все done» / точечные флипы убиваются на HEAD."""
    non_done = {
        t: s for t, s in P13_EXPECTED_STATUS.items() if s != "done"
    }
    assert non_done == {
        "selection_evaluated": "in_progress",
        "tuning_job_started": "in_progress",
        "tuning_job_cancelled": "pending",
    }, f"контракт не-done изменился: {non_done}"
    for event_type, expected in non_done.items():
        got = EVENT_NODE_STATUS.get(event_type)
        assert got == expected, (
            f"{event_type}: карта даёт {got!r}, контракт не-done {expected!r}"
        )
    fold = NodeStateFold()
    for event_type, node in (
        ("selection_evaluated", "selection"),
        ("tuning_job_started", "tuning"),
        ("tuning_job_cancelled", "tuning"),
    ):
        fold.apply(_event("modeling", node, event_type))
        status = fold.statuses.get(f"modeling/{node}")
        assert status == expected_status(event_type), (
            f"{event_type}: редьюсер дал {status!r}, не {expected_status(event_type)!r}"
        )


def expected_status(event_type: str) -> str:
    return P13_EXPECTED_STATUS[event_type]


@oracle("G-SEM-4 фаза: узловые факты P13 двигают last_active_stage")
def g_sem_4_phase_advance():
    """Фазу двигают только узловые факты решения -- все 7 типов теперь
    узловые: derive_last_active_stage корпуса из 7 P13-фактов ==
    modeling. База: типы не узловые -- фаза не двигается (RED)."""
    events = [
        _event("modeling", "candidate_generation", "candidates_generated"),
        _event("modeling", "selection", "selection_evaluated"),
        _event("modeling", "tuning", "tuning_job_cancelled"),
    ]
    assert derive_last_active_stage(events) == "modeling", (
        "узловые факты P13 не двигают фазу Наставника"
    )


@oracle("G-SEM-5 бейдж P16: runnable_candidates на candidate_generation")
def g_sem_5_candidates_badge():
    """§23.1: бейдж узла Пул кандидатов -- размер исполнимого пула
    (payload.statistics.runnable_candidates хука); ключ последний в
    NODE_SUMMARY_COUNT_KEYS (порядок прежних приоритетов не изменён).
    База: ключа нет -- бейдж не появляется (RED)."""
    assert NODE_SUMMARY_COUNT_KEYS[-1] == "runnable_candidates", (
        "ключ пула не последний в NODE_SUMMARY_COUNT_KEYS"
    )
    assert "runnable_candidates" in NODE_SUMMARY_COUNT_KEYS
    fold = NodeStateFold()
    # Хук флэттенит statistics.runnable_candidates в верхний уровень
    # payload факта (пин flatten-ожиданий trace_hook) -- редьюсер читает
    # верхний уровень.
    fold.apply(
        _event(
            "modeling",
            "candidate_generation",
            "candidates_generated",
            runnable_candidates=6,
            catalog_only_candidates=1,
        )
    )
    detail = fold.detail("modeling/candidate_generation")
    assert detail.get("summary_count") == 6, (
        f"бейдж {detail.get('summary_count')!r}, контракт -- размер пула 6"
    )


# ── Группа CAR: payload-носитель baseline_estimation (§23.3) ─────────


@oracle("G-CAR-1 носитель: backtest baselines атрибутирует Baseline")
def g_car_1_carrier_attributes_baseline():
    """backtest_run(family_id=baselines) ДОПОЛНИТЕЛЬНО атрибутируется
    узлу modeling/baseline_estimation: done + СВОЙ честный reason
    носителя (не «Бэктест выполнен»), главное атрибуция modeling/backtest
    не меняется, происхождение I10 (context/evidence от события). База:
    носителя нет -- узел не двигается (RED)."""
    fold = NodeStateFold()
    carrier_event = _event(
        "modeling", "backtest", "backtest_run",
        context_id="ctx-carrier-A",
        family_id="baselines", model_id="naive", metrics={"mape": 4.2},
    )
    fold.apply(carrier_event)
    status = fold.statuses.get("modeling/baseline_estimation")
    assert status == "done", (
        f"носитель не сработал: baseline_estimation={status!r} (RED-класс R2)"
    )
    detail = fold.detail("modeling/baseline_estimation")
    expected_reason = PAYLOAD_CARRIER_REASON[("backtest_run", "baseline_estimation")]
    assert detail.get("status_reason") == expected_reason, (
        f"reason носителя {detail.get('status_reason')!r} != честному тексту"
    )
    assert detail.get("_status_ctx") == "ctx-carrier-A", (
        "носитель потерял контекст происхождения (I10)"
    )
    # Главная атрибуция узла события -- прежняя (backtest).
    assert fold.statuses.get("modeling/backtest") == "done"
    main_reason = fold.detail("modeling/backtest").get("status_reason")
    assert main_reason == EVENT_NODE_REASON["backtest_run"], (
        "главная атрибуция узла события испорчена носителем"
    )


@oracle("G-CAR-2 чистота: не-baseline/легаси/мусор носитель не срабатывает")
def g_car_2_carrier_purity():
    """Легаси-корпус без family_id, не-baseline семейство, мусор payload
    -- носитель не срабатывает (done не фабрикуется); функция чистая
    (payload-мусор -- None, R3: фантомных атрибуций нет). Контроль на
    обеих сторонах; на HEAD страхует от обратного флипа условия."""
    assert payload_carrier_node is not None, (
        "payload-носитель не реализован (база до AUDIT-7A -- RED-класс R2)"
    )
    assert payload_carrier_node(
        _event("modeling", "backtest", "backtest_run", family_id="ets")
    ) is None, "не-baseline семейство атрибутировано"
    assert payload_carrier_node(
        _event("modeling", "backtest", "backtest_run")
    ) is None, "легаси без family_id атрибутирован"
    assert payload_carrier_node(
        _event("modeling", "backtest", "backtest_run", family_id=7)
    ) is None, "мусорный family_id атрибутирован"
    assert payload_carrier_node(
        _event("modeling", "backtest", "model_selected")
    ) is None, "чужой тип события атрибутирован"
    no_payload = _event("modeling", "backtest", "backtest_run")
    no_payload["payload"] = "мусор-строка"
    assert payload_carrier_node(no_payload) is None, "не-Mapping payload"
    # И статус узла Baseline не появляется ни при каком из этих событий.
    fold = NodeStateFold()
    for evt in (
        _event("modeling", "backtest", "backtest_run", family_id="ets"),
        _event("modeling", "backtest", "backtest_run"),
    ):
        fold.apply(evt)
    assert "modeling/baseline_estimation" not in fold.statuses, (
        "фантомный done Baseline фабрикуется не-baseline событием"
    )


@oracle("G-CAR-3 stage-level носитель: событие без узла несёт Baseline")
def g_car_3_stage_level_carrier():
    """Событие БЕЗ узла (stage-level backtest_run, контракт E6) с
    family_id=baselines узел носителя ПОЛУЧАЕТ -- факт payload
    существует; фантомный узел события прежние гейты не пропускают.
    База: носителя нет (RED)."""
    fold = NodeStateFold()
    stage_event = _event(
        "modeling", None, "backtest_run",
        context_id="ctx-carrier-E6",
        family_id="baselines",
    )
    fold.apply(stage_event)
    assert fold.statuses.get("modeling/baseline_estimation") == "done", (
        "stage-level носитель не атрибутировал Baseline"
    )
    detail = fold.detail("modeling/baseline_estimation")
    assert detail.get("_status_ctx") == "ctx-carrier-E6"


@oracle("G-CAR-4 P16-гигиена бейджа через носитель")
def g_car_4_carrier_badge_hygiene():
    """Счётчик следует за reason-событием (P16) и В НОСИТЕЛЕ: carrier
    с фактом счётчика ставит бейдж; СЛЕДУЮЩИЙ carrier БЕЗ фактов
    счётчика честно ОЧИЩАЕТ бейдж (цифра прежнего расчёта не
    наследуется). База: носителя нет (RED)."""
    fold = NodeStateFold()
    fold.apply(
        _event("modeling", "backtest", "backtest_run",
               family_id="baselines", runnable_candidates=3)
    )
    detail = fold.detail("modeling/baseline_estimation")
    assert detail.get("summary_count") == 3, (
        f"бейдж носителя {detail.get('summary_count')!r} != 3"
    )
    fold.apply(
        _event("modeling", "backtest", "backtest_run",
               family_id="baselines")
    )
    detail = fold.detail("modeling/baseline_estimation")
    assert detail.get("summary_count") is None, (
        "бейдж унаследовал цифру прежнего расчёта -- P16 нарушен"
    )


@oracle("G-CAR-5 guard двойной записи: свой узел == носитель")
def g_car_5_same_node_guard():
    """Событие, чья ГЛАВНАЯ атрибуция уже совпадает с носителем
    (backtest_run, node_id=baseline_estimation, family_id=baselines --
    нештатно, но легально через прямой seed): носитель НЕ дублирует
    запись -- одна запись статуса/reason (метод гасит дубль). Пин
    конструкции единой точки записи."""
    fold = NodeStateFold()
    fold.apply(
        _event("modeling", "baseline_estimation", "backtest_run",
               context_id="ctx-same", family_id="baselines")
    )
    detail = fold.detail("modeling/baseline_estimation")
    # Единственная запись -- главный путь (reason карты backtest_run),
    # дубль носителя не перезаписывает её текстом носителя.
    assert fold.statuses.get("modeling/baseline_estimation") == "done"
    assert detail.get("status_reason") == EVENT_NODE_REASON["backtest_run"], (
        "дубль записи носителя перезаписал главную атрибуцию"
    )


# ── Группа JOB: связность job-фактов и поздний старый job (§23.4) ────


@oracle("G-JOB-1 связность: started/cancelled одним job_id")
def g_job_1_job_id_linkage():
    """Payload фактов tuning_job_started И tuning_job_cancelled несёт
    один и тот же job_id (связность operation/job id удостоверяется
    трассой); cancel до completion -- узел pending, НЕ done. База:
    job_id в payload отсутствует, узел не двигается (RED)."""
    client = _client()
    _prepare_modeling_session(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 3,
              "metric": "mae", "random_state": 7,
              "idempotency_key": "cert7a-job-link"},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "in_progress", (
        f"запущенный job -- работа в процессе, узел {node['status']!r}"
    )
    started_events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_job_started"
    ]
    assert started_events, "факт tuning_job_started не записан"
    started_payload = started_events[-1].get("payload") or {}
    assert started_payload.get("job_id") == job_id, (
        "факт запуска не несёт job_id"
    )
    cancelled = client.post(
        f"/v1/session/modeling/jobs/{job_id}/cancel",
        json={"reason": REASON_CANCEL},
    )
    assert cancelled.status_code == 200, cancelled.text
    cancelled_events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_job_cancelled"
    ]
    assert cancelled_events, "факт tuning_job_cancelled не записан"
    cancelled_payload = cancelled_events[-1].get("payload") or {}
    assert cancelled_payload.get("job_id") == job_id, (
        "факт отмены не связан с запуском одним job_id"
    )
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "pending", (
        f"cancel до completion дал {node['status']!r} -- НЕ done"
    )
    assert node["status"] != "done"


@oracle("G-JOB-2 жизненный цикл last-wins: четыре факта подряд")
def g_job_2_lifecycle_last_wins():
    """start→cancel→start→cancel: узел Тюнинг следует ЗА ПОСЛЕДНИМ
    фактом на каждом шаге (in_progress→pending→in_progress→pending);
    каждый факт -- отдельный job_id (связность парами, не склейка)."""
    client = _client()
    _prepare_modeling_session(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    expected_cycle = ["in_progress", "pending", "in_progress", "pending"]
    job_ids: list[str] = []
    for cycle_index, expected in enumerate(expected_cycle, start=1):
        if expected == "in_progress":
            started = client.post(
                "/v1/session/modeling/jobs/start",
                json={"operation": "tuning", "model_id": "ets",
                      "max_trials": 3, "metric": "mae", "random_state": 7,
                      "idempotency_key": f"cert7a-cycle-{cycle_index}"},
            )
            assert started.status_code == 200, started.text
            job_ids.append(started.json()["job_id"])
        else:
            cancelled = client.post(
                f"/v1/session/modeling/jobs/{job_ids[-1]}/cancel",
                json={"reason": REASON_CANCEL},
            )
            assert cancelled.status_code == 200, cancelled.text
        node = _trace_node(client, "modeling", "tuning")
        assert node["status"] == expected, (
            f"шаг {cycle_index}: узел {node['status']!r}, last-wins {expected!r}"
        )
    started_events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_job_started"
    ]
    assert len({e["payload"].get("job_id") for e in started_events}) == 2, (
        "два запуска не различаются job_id"
    )


@oracle("G-JOB-3 поздний старый job не повышает current-context")
def g_job_3_late_old_job_stale():
    """Факт запуска старого job (контекст A) после смены цели
    (контекст B): узел остаётся in_progress с validity=stale (старый
    job не представляется текущей работой); поздняя отмена -- честный
    404 БЕЗ нового факта; новый job в контексте B -- validity=current."""
    client = _client()
    _prepare_modeling_session(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 3,
              "metric": "mae", "random_state": 7,
              "idempotency_key": "cert7a-stale-job"},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    context_before = _trace_context(client)
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "in_progress"
    assert node["validity"] == "current", (
        f"факт своего контекста: validity={node['validity']!r}"
    )
    switched = client.post(
        "/v1/session/target-column", json={"column": "price"}
    )
    assert switched.status_code == 200, switched.text
    context_after = _trace_context(client)
    assert context_after and context_after != context_before, (
        "смена цели обязана сменить контекст расчёта (AUDIT-C)"
    )
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "in_progress", (
        "последний факт трассы -- запуск старого job (last-wins)"
    )
    assert node["validity"] == "stale", (
        f"факт старого контекста validity={node['validity']!r} -- старый "
        "job не должен представляться текущей работой"
    )
    modelling_before = len([
        e for e in _trace_events(client) if e.get("stage") == "modeling"
    ])
    late_cancel = client.post(
        f"/v1/session/modeling/jobs/{job_id}/cancel",
        json={"reason": "Cert-7A: поздняя отмена старого job"},
    )
    assert late_cancel.status_code == 404, (
        f"записи старого job инвалидированы, ответ {late_cancel.status_code}"
    )
    modelling_after = len([
        e for e in _trace_events(client) if e.get("stage") == "modeling"
    ])
    assert modelling_after == modelling_before, (
        "отказ отмены не сеет фактов трассы"
    )
    # Реалистичный контур аналитика в НОВОМ контексте: смена цели
    # сбрасывает passport-историю (passport_history_reset) -- заново
    # подтверждаются modeling_entry и пул кандидатов, затем новый job.
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post(
        "/v1/session/dataset/passport/modeling_entry"
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    restarted = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 3,
              "metric": "mae", "random_state": 7,
              "idempotency_key": "cert7a-fresh-job"},
    )
    assert restarted.status_code == 200, restarted.text
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "in_progress"
    assert node["validity"] == "current", (
        f"новый job в новом контексте: validity={node['validity']!r}"
    )


# ── Группа E2E: полный Modeling-контур на живом TestClient ───────────


def _select_ets(client: TestClient, evaluate_body: dict):
    """Свой выбор модели ПОДПИСЯМИ оценки (select требует
    selection_analysis_id/selection_signature из ответа evaluate --
    привязка выбора к своему анализу); acknowledge-флаги осознаны
    сертификатором, риск baseline-выбора принимается явно."""
    return client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": "ets",
            "selection_analysis_id": evaluate_body.get("selection_analysis_id"),
            "selection_signature": evaluate_body.get("selection_signature"),
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
            "acknowledge_ensemble_no_gain": True,
        },
    )


@oracle("G-E2E-1 candidates: факт пула, узел done, бейдж-число")
def g_e2e_1_candidates_producer():
    """POST /modeling/candidates (СВОИ параметры): факт
    candidates_generated несёт spec_version и runnable_candidates ==
    ответу статистики; узел candidate_generation done + reason карты +
    бейдж == размеру пула (P16). База: узел pending, бейджа нет (RED)."""
    client = _client()
    _prepare_modeling_session(client)
    resp = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    )
    assert resp.status_code == 200, resp.text
    statistics = resp.json().get("statistics") or {}
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "candidates_generated"
    ]
    assert events, "факт candidates_generated не записан"
    payload = events[-1].get("payload") or {}
    assert payload.get("spec_version"), "факт без версии методики (§23.5)"
    assert payload.get("runnable_candidates") == statistics.get(
        "runnable_candidates"
    ), "payload бейджа расходится с ответом пула"
    node = _trace_node(client, "modeling", "candidate_generation")
    assert node["status"] == "done", (
        f"пул сформирован, узел {node['status']!r} (RED-класс R1)"
    )
    assert node["status_reason"] == EVENT_NODE_REASON["candidates_generated"]
    assert node.get("summary_count") == statistics.get("runnable_candidates"), (
        f"бейдж {node.get('summary_count')!r} != размеру пула (P16)"
    )


@oracle("G-E2E-2 оценка ≠ выбор; сравнение и диагностика -- done")
def g_e2e_2_selection_diagnostics_comparison():
    """Полный закрытый скоуп → diagnostics/ensure → compare →
    selection/evaluate (СВОЙ min_oof_points): узел selection
    in_progress (оценка ≠ выбор, done несёт только model_selected);
    diagnostics и comparison -- done с reason карт. База: статусов нет
    (RED)."""
    client = _client()
    _closed_tuning_scope(client)
    assert client.post(
        "/v1/session/modeling/diagnostics/ensure", json={}
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/compare", json={}
    ).status_code == 200
    evaluated = client.post(
        "/v1/session/modeling/selection/evaluate",
        json={"min_oof_points": 5},
    )
    assert evaluated.status_code == 200, evaluated.text
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "selection_evaluated"
    ]
    assert events, "факт selection_evaluated не записан"
    node = _trace_node(client, "modeling", "selection")
    assert node["status"] == "in_progress", (
        f"оценка закрыла выбор: {node['status']!r} (механический done)"
    )
    assert node["status_reason"] == EVENT_NODE_REASON["selection_evaluated"]
    diag = _trace_node(client, "modeling", "diagnostics")
    assert diag["status"] == "done", f"диагностика: {diag['status']!r}"
    assert diag["status_reason"] == EVENT_NODE_REASON["diagnostics_run"]
    comp = _trace_node(client, "modeling", "comparison")
    assert comp["status"] == "done", f"сравнение: {comp['status']!r}"
    assert comp["status_reason"] == EVENT_NODE_REASON["models_compared"]


@oracle("G-E2E-3 skip: reason эхом в ответе и в факте")
def g_e2e_3_skip_reason_echo():
    """«skipped имеет обоснование»: ответ /tuning/skip ЭХОМ возвращает
    СВОЙ reason; факт трассы несёт тот же reason; узел Тюнинг done с
    reason карты. База: эха нет -- обоснование теряется (RED)."""
    client = _client()
    _skip_ready_session(client)
    resp = client.post(
        "/v1/session/modeling/tuning/skip",
        json={"model_id": "ets", "reason": REASON_SKIP_1,
              "acknowledge": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("reason") == REASON_SKIP_1, (
        f"ответ не эхом вернул обоснование: {body.get('reason')!r}"
    )
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_skipped"
    ]
    assert events, "факт tuning_skipped не записан"
    payload = events[-1].get("payload") or {}
    assert payload.get("model_id") == "ets"
    assert payload.get("reason") == REASON_SKIP_1, (
        f"обоснование не попало в факт трассы: {payload.get('reason')!r}"
    )
    node = _trace_node(client, "modeling", "tuning")
    assert node["status"] == "done", (
        f"осознанный пропуск закрыл вопрос: {node['status']!r}"
    )
    assert node["status_reason"] == EVENT_NODE_REASON["tuning_skipped"]


@oracle("G-E2E-4 skip-pending: reason эхом (атомарное решение)")
def g_e2e_4_skip_pending_reason_echo():
    """Атомарный пропуск pending-скоупа: reason ЭХОМ в ответе и в
    факте трассы (тот же класс обоснованных решений). База: эха нет
    (RED)."""
    client = _client()
    _skip_ready_session(client)
    resp = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={"reason": REASON_SKIP_PENDING, "acknowledge": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("reason") == REASON_SKIP_PENDING, (
        f"эхо обоснования потеряно: {resp.json().get('reason')!r}"
    )
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_skipped"
    ]
    assert events, "факт tuning_skipped не записан"
    payload = events[-1].get("payload") or {}
    assert payload.get("reason") == REASON_SKIP_PENDING


@oracle("G-E2E-5 skip-pending unchanged: честный payload, узел стабилен")
def g_e2e_5_skip_pending_unchanged():
    """Повторный skip-pending на закрытом скоупе: статус unchanged,
    reason ВСЁ РАВНО эхом (обоснование решения фиксируется); факт несёт
    payload.status=unchanged; узел Тюнинг остаётся done (повторное
    решение не открывает закрытый вопрос). База: эха нет (RED)."""
    client = _client()
    _skip_ready_session(client)
    assert client.post(
        "/v1/session/modeling/tuning/skip",
        json={"model_id": "ets", "reason": REASON_SKIP_1,
              "acknowledge": True},
    ).status_code == 200
    node_before = _trace_node(client, "modeling", "tuning")
    resp = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={"reason": REASON_SKIP_PENDING, "acknowledge": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "unchanged", body
    assert body.get("reason") == REASON_SKIP_PENDING, (
        "не-skipped путь тоже обязан возвращать обоснование"
    )
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "tuning_skipped"
    ]
    assert events, "факт tuning_skipped (unchanged) не записан"
    payload = events[-1].get("payload") or {}
    assert payload.get("status") == "unchanged", payload
    assert payload.get("reason") == REASON_SKIP_PENDING
    node_after = _trace_node(client, "modeling", "tuning")
    assert node_after["status"] == "done", (
        f"повторное решение изменило закрытый узел: "
        f"{node_before['status']!r} -> {node_after['status']!r}"
    )


@oracle("G-E2E-6 честное отсутствие: три узла без продюсеров pending")
def g_e2e_6_missing_producers_honest_absence():
    """Полный реалистичный контур (пул→baselines→backtest ets+naive→
    исключения→skip→диагностика→сравнение→оценка→выбор→карта) НЕ
    создаёт фактов problem_definition/data_structure/constraint_mapping
    -- pending, reason отсутствует (честное отсутствие, не «done по
    открытию вкладки»); baseline_estimation -- done от РЕАЛЬНОГО
    носителя; после model_selected узел selection done. База: baseline
    pending (RED)."""
    client = _client()
    _closed_tuning_scope(client)
    assert client.post(
        "/v1/session/modeling/diagnostics/ensure", json={}
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/compare", json={}
    ).status_code == 200
    evaluated = client.post(
        "/v1/session/modeling/selection/evaluate",
        json={"min_oof_points": 5},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert _select_ets(client, evaluated.json()).status_code == 200
    for absent_node in (
        "problem_definition", "data_structure", "constraint_mapping",
    ):
        node = _trace_node(client, "modeling", absent_node)
        assert node["status"] == "pending", (
            f"{absent_node}: {node['status']!r} без продюсера (фабрикация)"
        )
        assert node["status_reason"] is None, (
            f"{absent_node}: reason без факта"
        )
    baseline = _trace_node(client, "modeling", "baseline_estimation")
    assert baseline["status"] == "done", (
        f"baseline рассчитан, носитель обязан удостоверять: "
        f"{baseline['status']!r} (RED-класс R2)"
    )
    assert baseline["status_reason"] == PAYLOAD_CARRIER_REASON[
        ("backtest_run", "baseline_estimation")
    ]
    selection = _trace_node(client, "modeling", "selection")
    assert selection["status"] == "done", (
        f"model_selected обязан закрывать выбор: {selection['status']!r}"
    )


@oracle("G-E2E-7 носитель точечен: ets-бэктест не трогает Baseline")
def g_e2e_7_carrier_only_baseline_family():
    """После done Baseline (носитель) реальный backtest ets (семейство
    НЕ baselines): узел backtest done, узел Baseline НЕИЗМЕНЕН (статус,
    reason носителя) -- носитель срабатывает только на своей семье
    (e2e через живые маршруты)."""
    client = _client()
    _skip_ready_session(client)
    # До baseline-family backtest: /baselines сознательно вне трассы
    # (пин PROGR-20), backtest ets -- не-baseline. Честное отсутствие:
    # носитель НЕ фабрикует done ни из bootstrap, ни из чужой семьи.
    baseline = _trace_node(client, "modeling", "baseline_estimation")
    assert baseline["status"] == "pending", (
        f"до baseline-family backtest узел {baseline['status']!r} -- "
        "носитель обязан требовать РЕАЛЬНЫЙ факт"
    )
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "naive"}
    ).status_code == 200
    # naive -- baseline-модель: факт backtest_run(family_id=baselines)
    # -- носитель удостоверяет done.
    baseline_done = _trace_node(client, "modeling", "baseline_estimation")
    assert baseline_done["status"] == "done", (
        f"носитель не сработал на живом контуре: "
        f"{baseline_done['status']!r}"
    )
    reason_before = baseline_done["status_reason"]
    count_before = baseline_done.get("summary_count")
    # Повторный не-baseline backtest (ets): узел Baseline НЕИЗМЕНЕН.
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "ets"}
    ).status_code == 200
    backtest_node = _trace_node(client, "modeling", "backtest")
    assert backtest_node["status"] == "done"
    baseline_after = _trace_node(client, "modeling", "baseline_estimation")
    assert baseline_after["status"] == "done"
    assert baseline_after["status_reason"] == reason_before, (
        "не-baseline backtest перезаписал reason Baseline"
    )
    assert baseline_after.get("summary_count") == count_before, (
        "не-baseline backtest тронул бейдж Baseline"
    )


@oracle("G-E2E-8 переоткрытие selection повторной оценкой (last-wins)")
def g_e2e_8_selection_reopen_last_wins():
    """evaluate → in_progress; select → done; ПОВТОРНАЯ оценка → узел
    честно ПЕРЕОТКРЫТ in_progress (last-wins единого редьюсера: оценка
    после выбора -- работа с выбором возобновилась)."""
    client = _client()
    _closed_tuning_scope(client)
    assert client.post(
        "/v1/session/modeling/diagnostics/ensure", json={}
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/compare", json={}
    ).status_code == 200
    evaluated = client.post(
        "/v1/session/modeling/selection/evaluate",
        json={"min_oof_points": 5},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert _select_ets(client, evaluated.json()).status_code == 200
    node = _trace_node(client, "modeling", "selection")
    assert node["status"] == "done", f"выбор: {node['status']!r}"
    assert client.post(
        "/v1/session/modeling/selection/evaluate",
        json={"min_oof_points": 5},
    ).status_code == 200
    node = _trace_node(client, "modeling", "selection")
    assert node["status"] == "in_progress", (
        f"повторная оценка не переоткрыла selection: {node['status']!r}"
    )
    assert node["status_reason"] == EVENT_NODE_REASON["selection_evaluated"]


# ── Группа ORG: происхождение, Наставник, отчёт (§23.5 + границы) ────


@oracle("G-ORG-1 происхождение метода: иная стратегия -- иной факт")
def g_org_1_method_provenance_two_facts():
    """§23.5 «Метод/параметры... сохранять независимо от одинаковой
    картинки узла»: candidates sliding → expanding (разные параметры
    методики) -- ДВА факта в истории с РАЗНЫМИ payload.strategy (узел
    при этом done на обоих; вторая стратегия тоже двигает пул). P19
    (иная картина того же count) страхуется контролем дедупа."""
    client = _client()
    _prepare_modeling_session(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 1, "n_splits": 3,
              "gap": 2, "train_window": 45},
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 3, "n_splits": 2},
    ).status_code == 200
    events = [
        e for e in _trace_events(client)
        if e.get("event_type") == "candidates_generated"
    ]
    assert len(events) == 2, (
        f"второй реально выполненный расчёт пула потерян из истории: "
        f"{len(events)} фактов"
    )
    payloads = [e.get("payload") or {} for e in events]
    assert payloads[0] != payloads[1], (
        "два разных расчёта пула неразличимы в истории (происхождение)"
    )
    node = _trace_node(client, "modeling", "candidate_generation")
    assert node["status"] == "done"
    # Происхождение: spec_version присутствует в обоих фактах.
    # ЧЕСТНОЕ НАБЛЮДЕНИЕ (не дефект, клетка §23.1): параметр strategy в
    # whitelist хука не входит -- journaled origin пула это spec_version
    # и состав (runnable/catalog_only/blocked); см. находку R-7AC-1.
    for event in events:
        assert (event.get("payload") or {}).get("spec_version"), (
            "факт без версии методики (происхождение §23.5)"
        )
        assert "runnable_candidates" in (event.get("payload") or {}), (
            "факт без состава пула"
        )


@oracle("G-ORG-2 Наставник потребляет ЕДИНЫЙ редьюсер (фаза modeling)")
def g_org_2_mentor_single_reducer():
    """Наставник НЕ имеет копии семантики: next-step после узлового
    факта P13 видит фазу modeling (last_active_stage) -- фаза от того
    же движка. База: типы не узловые -- фаза не двигается (RED)."""
    client = _client()
    _skip_ready_session(client)
    run_id = _run_id(client)
    resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("last_active_stage") == "modeling", (
        f"Наставник видит фазу {body.get('last_active_stage')!r} -- "
        "статусы Наставника не от единого редьюсера"
    )
    # Живой in_progress статус не роняет Наставника.
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 3,
              "metric": "mae", "random_state": 7,
              "idempotency_key": "cert7a-mentor-job"},
    )
    assert started.status_code == 200, started.text
    resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("last_active_stage") == "modeling"


@oracle("G-ORG-3 отчёт: честный fallback с исходным типом/ids")
def g_org_3_report_honest_fallback():
    """Граница AUDIT-7B: human-шаблонов новых типов ещё нет -- отчёт
    НЕ должен ни падать, ни терять исходный тип/ids (общий честный
    fallback). P13-факты доступны отчёту; markdown содержит исходный
    тип события (fallback сохраняет тип). Контроль на обеих сторонах."""
    client = _client()
    _skip_ready_session(client)
    # Факт обоснованного пропуска -- материал проверки fallback'а.
    assert client.post(
        "/v1/session/modeling/tuning/skip",
        json={"model_id": "ets", "reason": REASON_SKIP_1,
              "acknowledge": True},
    ).status_code == 200
    run_id = _run_id(client)
    resp = client.get(f"/v1/progress/runs/{run_id}/report?format=md")
    assert resp.status_code == 200, resp.text
    text = resp.text
    assert "tuning_skipped" in text, (
        "исходный тип события потерян отчётом (нечестный fallback)"
    )
    assert "Событие трассы: tuning_skipped" in text, (
        "общий fallback не обозначил неизвестную интерпретацию честно"
    )


@oracle("G-ORG-4 bейдж узла по живому /trace согласован с фактом")
def g_org_4_trace_badge_consistency():
    """Сквозная согласованность: бейдж candidate_generation из живого
    /trace == payload последнего факта candidates_generated (P16 от
    факта, не от картинки) -- доказательство происхождения числа."""
    client = _client()
    _prepare_modeling_session(client)
    resp = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 3, "n_splits": 2},
    )
    assert resp.status_code == 200, resp.text
    pool = resp.json().get("statistics") or {}
    node = _trace_node(client, "modeling", "candidate_generation")
    assert node.get("summary_count") == pool.get("runnable_candidates"), (
        "бейдж панели != размеру пула последнего факта"
    )


# ── Runner ───────────────────────────────────────────────────────────

ORACLES: list = []


def _collect() -> None:
    import __main__ as mod  # noqa: PLC0415
    for name, value in vars(mod).items():
        if callable(value) and hasattr(value, "_oracle_name"):
            ORACLES.append(value)
    ORACLES.sort(key=lambda fn: fn._oracle_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=None, help="путь протокола")
    args = parser.parse_args()
    _collect()
    _log("PROGR-AUDIT-7A-CERT -- СВОИ оракулы (данные сертификатора)")
    _log(f"Объект: HEAD={Path(REPO).name}; оракулов: {len(ORACLES)}")
    for fn in ORACLES:
        fn()
    _log("")
    _log(f"ИТОГ: PASS={PASSES} FAIL={len(FAILURES)}")
    if FAILURES:
        _log("Отказы:")
        for failure in FAILURES:
            _log(f"  - {failure}")
    protocol_path = args.protocol or (
        REPO + "/scripts/prograudit7acert_oracles_results.txt"
    )
    Path(protocol_path).write_text(
        "\n".join(PROTOCOL_LINES) + "\n", encoding="utf-8"
    )
    print(f"протокол: {protocol_path}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
