# tests/api/test_progress_audit_7a.py
"""
PROGR-AUDIT-7A: матрица Modeling и происхождение методов
(plan_progress_audit.md §15; spec_progress_audit.md F09/F13, P13/P19;
контракт docs/progress_audit_contract.md аддендум v1.3-7A §23).

Задача на фундаменте AUDIT-4 → AUDIT-6A (план §3: предшественники
закрыты). Состав карточки §15:

  1. Семь типов P13 (candidates_generated, selection_evaluated,
     models_compared, diagnostics_run, tuning_skipped,
     tuning_job_started, tuning_job_cancelled) получают ЯВНУЮ семантику
     проекции ЕДИНОГО редьюсера: узел + статус словаря ПРОЦЕССНОЙ
     стадии Modeling (pending/in_progress/done, §3 pipeline_graph) +
     честный reason. Всем done НЕ назначается: оценка выбора -- не
     выбор (in_progress), запуск job -- не завершение (in_progress),
     отмена job -- не результат (pending).
  2. Для problem_definition/data_structure/constraint_mapping
     устанавливается честное ОТСУТСТВИЕ продюсера (нет носителя факта
     -- узлы не получают done; «не создавать done по открытию
     вкладки»); для baseline_estimation -- РЕАЛЬНЫЙ носитель:
     backtest_run с payload.family_id=="baselines" (та же семантика,
     что уже утверждает session.modeling_pipeline -- has_baseline ==
     backtest family_id=baselines), payload-условная атрибуция узла.
  3. Job started/cancelled связываются ОДНИМ job id в payload фактов
     (до задачи связность отсутствовала -- job_id не попадал в трассу);
     skipped имеет обоснование: reason эхом в ответе /tuning/skip и
     /tuning/skip-pending и в payload факта трассы.
  4. Поздний факт старого job не повышает current-context: факты
     started/cancelled несут контекст сеяния; против нового контекста
     запуска validity=stale (механизм AUDIT-5B), current определяется
     фактами нового контекста.
  5. P19 (совместно с AUDIT-4): иной метод при той же картинке --
     другой факт (DEDUPE_PARAM_KEYS -- параметров результата в dedupe);
     фокус-рефетч того же результата не журналируется новым методом.

RED-сценарии карточки §15: P13/P19; cancel до completion; skipped с
причиной; результат старого job; иной метод при том же count;
отсутствующий producer не даёт вымышленного done.

Границы (план §15 + пины PROGR-20): jobs/{id}/step, /baselines,
/tuning/start, /tuning/step СОЗНАТЕЛЬНО не трассируются (механические
единицы работы/вне таблицы приоритетов -- test_progr20_conscious_
exclusions_stay_untraced); завершение job-контура фактом трассы не
является (артефактная система несёт result_ref/tuning_id); готовность
production-моделей и контракты BacktestPlan/EDA-fold не меняются;
human report-шаблоны новых типов -- AUDIT-7B (план §16), в отчёте
действует честный общий fallback с исходным типом/ids.
"""
from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from app.core.node_status import (
    EVENT_NODE_REASON,
    EVENT_NODE_STATUS,
    NodeStateFold,
    derive_last_active_stage,
    derive_node_statuses,
    derive_pipeline_node_states,
    resolve_event_status,
)
from app.core.pipeline_graph import is_known_node
from apps.api.main import app
from apps.api.session_store import (
    reset_session_store_for_testing,
)


# ── Изоляция e2e (паттерн test_progress_audit_8) ─────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


client = TestClient(app)

CSV_MODELING = (
    "date,value,driver\n"
    + "".join(
        f"{year}-{month:02d}-01,"
        f"{100 + 0.4 * index + 7 * (index % 3)},{30 + 0.2 * index}\n"
        for year in (2021, 2022, 2023, 2024, 2025)
        for index, month in enumerate(range(1, 13), start=1)
    )
)


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str = "2026-10-13T10:00:00+00:00",
    context_id: str | None = None,
    **payload,
) -> dict:
    """Словарь канона §4.1 (+ опциональный envelope-контекст AUDIT-S).
    event_id -- детерминированный (реальный корпус хука всегда несёт
    identity; происхождение I10 ссылается на него)."""
    digest = hashlib.md5(
        f"{node_id}|{event_type}|{ts}".encode("utf-8")
    ).hexdigest()[:10]
    data = {
        "event_id": f"evt-{digest}",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": payload,
    }
    if context_id is not None:
        data["context_id"] = context_id
    return data


def _node(
    states: list[dict], stage: str, node_id: str
) -> dict:
    for state in states:
        if state["stage"] == stage and state["node_id"] == node_id:
            return state
    raise AssertionError(f"узел {stage}/{node_id} не найден")


def _trace_node(stage: str, node_id: str) -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    for state in resp.json()["nodes"]:
        if state["stage"] == stage and state["node_id"] == node_id:
            return state
    raise AssertionError(f"узел {stage}/{node_id} не найден в /trace")


def _trace_events() -> list[dict]:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def _trace_context_id() -> str | None:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json().get("context_id")


def _prepare_modeling_session() -> None:
    """Реалистичное начало исследования (паттерн test_modeling_workflow):
    upload → цель → дата → паспорт → Modeling entry."""
    file = io.BytesIO(CSV_MODELING.encode("utf-8"))
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", file, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(
        "/v1/session/target-column", json={"column": "value"}
    ).status_code == 200
    assert client.post(
        "/v1/session/date-column", json={"column": "date"}
    ).status_code == 200
    assert client.post(
        "/v1/session/dataset/passport/start"
    ).status_code == 200
    assert client.post(
        "/v1/session/dataset/passport/modeling_entry"
    ).status_code == 200


# ── Контур A: семантика редьюсера для семи типов P13 (план §15) ──────


class TestP13ReducerSemantics:
    def test_p13_seven_types_have_explicit_status_semantics(self):
        """P13/кариочка §15: каждый из семи типов -- ЯВНАЯ семантика
        статуса ЕДИНОГО редьюсера (до задачи: None -- «событие есть,
        его последствия нигде не определены», F09). Словарь ПРОЦЕССНОЙ
        стадии Modeling: pending/in_progress/done; всем done НЕ
        назначается -- оценка/запуск не результат, отмена не успех."""
        expected = {
            "candidates_generated": "done",
            "selection_evaluated": "in_progress",
            "models_compared": "done",
            "diagnostics_run": "done",
            "tuning_skipped": "done",
            "tuning_job_started": "in_progress",
            "tuning_job_cancelled": "pending",
        }
        for event_type, status in expected.items():
            resolved = resolve_event_status(
                _event("modeling", "tuning", event_type)
            )
            assert resolved == status, (
                f"{event_type}: ожидался статус {status!r} словаря "
                f"процессной стадии, получен {resolved!r}"
            )

    def test_p13_nodes_and_reasons_are_facts(self):
        """Каждый тип атрибутируется СВОЕМУ узлу графа с честным
        reason-фактом (не советом): пул сформирован, оценка без выбора,
        сравнение выполнено, диагностика, пропуск с обоснованием,
        запуск job, отмена до завершения."""
        expectations = {
            "candidates_generated": ("candidate_generation", "done"),
            "selection_evaluated": ("selection", "in_progress"),
            "models_compared": ("comparison", "done"),
            "diagnostics_run": ("diagnostics", "done"),
            "tuning_skipped": ("tuning", "done"),
            "tuning_job_started": ("tuning", "in_progress"),
            "tuning_job_cancelled": ("tuning", "pending"),
        }
        for event_type, (node_id, status) in expectations.items():
            assert is_known_node("modeling", node_id), event_type
            statuses = derive_node_statuses(
                [_event("modeling", node_id, event_type)]
            )
            assert statuses[f"modeling/{node_id}"] == status, event_type
            reason = EVENT_NODE_REASON[event_type]
            assert reason and reason.strip(), event_type

    def test_job_lifecycle_last_wins_on_tuning_node(self):
        """Жизненный цикл job -- last-wins ЕДИНОГО редьюсера: запуск
        (in_progress) → отмена (pending, работа остановлена) →
        осознанный пропуск (done, defaults оставлены). Ни один переход
        не «застревает»: каждое событие имеет определённое
        последствие."""
        corpus = [
            _event("modeling", "tuning", "tuning_job_started", ts="...T10:00:01+00:00"),
            _event("modeling", "tuning", "tuning_job_cancelled", ts="...T10:00:02+00:00"),
        ]
        statuses = derive_node_statuses(corpus)
        assert statuses["modeling/tuning"] == "pending"
        corpus.append(
            _event("modeling", "tuning", "tuning_skipped", ts="...T10:00:03+00:00")
        )
        statuses = derive_node_statuses(corpus)
        assert statuses["modeling/tuning"] == "done"

    def test_cancel_before_completion_is_never_done(self):
        """RED-карточка §15 «cancel до completion»: started → cancelled
        -- узел тюнинга НЕ done (результата нет); причина -- честный
        текст отмены рядом со статусом."""
        corpus = [
            _event("modeling", "tuning", "tuning_job_started"),
            _event("modeling", "tuning", "tuning_job_cancelled"),
        ]
        states = derive_pipeline_node_states(corpus)
        node = _node(states, "modeling", "tuning")
        assert node["status"] != "done"
        assert node["status"] == "pending"
        assert node["status_reason"] == EVENT_NODE_REASON["tuning_job_cancelled"]

    def test_evaluation_is_in_progress_and_does_not_close_selection(self):
        """Оценка выбора (рекомендация + ансамбль) -- НЕ зафиксированный
        выбор: selection in_progress; done узла несёт только
        model_selected (канон §4.1). Наставник видит «выбор не
        зафиксирован» через статус, правило
        modeling_candidates_without_selection живёт."""
        corpus = [
            _event("modeling", "selection", "selection_evaluated"),
        ]
        states = derive_pipeline_node_states(corpus)
        node = _node(states, "modeling", "selection")
        assert node["status"] == "in_progress"
        corpus.append(_event("modeling", "selection", "model_selected"))
        states = derive_pipeline_node_states(corpus)
        assert _node(states, "modeling", "selection")["status"] == "done"

    def test_p13_types_advance_phase_to_modeling(self):
        """Фаза (Наставник): узловые факты решения двигают фазу на
        modeling -- каждый из семи типов делает это (гейт
        derive_last_active_stage -- resolve_event_status)."""
        nodes = {
            "candidates_generated": "candidate_generation",
            "selection_evaluated": "selection",
            "models_compared": "comparison",
            "diagnostics_run": "diagnostics",
            "tuning_skipped": "tuning",
            "tuning_job_started": "tuning",
            "tuning_job_cancelled": "tuning",
        }
        for event_type, node_id in nodes.items():
            stage = derive_last_active_stage(
                [_event("modeling", node_id, event_type)]
            )
            assert stage == "modeling", event_type

    def test_p13_registered_types_control(self):
        """Контроль (GREEN на базе, PROGR-20): все семь типов в реестре
        стадии modeling -- карта не шире фактов (инвариант
        test_every_mapped_type_registered_in_event_registry).
        Членство в EVENT_NODE_STATUS/EVENT_NODE_REASON -- предмет RED
        (до задачи типов там нет)."""
        from apps.api.trace_events import STAGE_EVENT_TYPES

        for event_type in (
            "candidates_generated", "selection_evaluated",
            "models_compared", "diagnostics_run", "tuning_skipped",
            "tuning_job_started", "tuning_job_cancelled",
        ):
            assert event_type in STAGE_EVENT_TYPES["modeling"], event_type


# ── Контур B: payload-носитель baseline_estimation (план §15) ────────


class TestBaselineCarrier:
    def test_backtest_run_baseline_family_attributes_baseline_node(self):
        """Реальный носитель факта baseline-оценки: backtest_run с
        payload.family_id=="baselines" -- тот же факт, что утверждает
        session.modeling_pipeline (has_baseline). Узел Baseline --
        done с собственным честным reason; узел Бэктест -- прежний done
        (главная атрибуция не дублируется)."""
        corpus = [
            _event(
                "modeling", "backtest", "backtest_run",
                model_id="naive", family_id="baselines",
            ),
        ]
        states = derive_pipeline_node_states(corpus)
        backtest = _node(states, "modeling", "backtest")
        baseline = _node(states, "modeling", "baseline_estimation")
        assert backtest["status"] == "done"
        assert baseline["status"] == "done"
        assert baseline["status_reason"]
        assert baseline["status_reason"] != backtest["status_reason"]

    def test_backtest_run_non_baseline_does_not_touch_baseline_node(self):
        """Отрицательный контроль: backtest НЕ-baseline семейства
        (family_id=arima) узел Baseline НЕ трогает -- атрибуция
        payload-условная, фантомных done нет."""
        corpus = [
            _event(
                "modeling", "backtest", "backtest_run",
                model_id="arima", family_id="arima",
            ),
        ]
        states = derive_pipeline_node_states(corpus)
        assert _node(states, "modeling", "backtest")["status"] == "done"
        baseline = _node(states, "modeling", "baseline_estimation")
        assert baseline["status"] == "pending"
        assert baseline["status_reason"] is None

    def test_backtest_run_legacy_without_family_id_honest_absence(self):
        """Легаси-корпус без family_id в payload: носитель не
        срабатывает, узел Baseline остаётся pending -- происхождение не
        выдумывается (честное отсутствие)."""
        corpus = [_event("modeling", "backtest", "backtest_run")]
        states = derive_pipeline_node_states(corpus)
        baseline = _node(states, "modeling", "baseline_estimation")
        assert baseline["status"] == "pending"

    def test_carrier_fact_keeps_provenance_and_validity(self):
        """Факт-носитель несёт происхождение I10 (source/reason ссылки)
        и применимость PR-4: факт контекста A против контекста запуска B
        -- validity=stale (старый baseline не удостоверяет новые
        данные)."""
        corpus = [
            _event(
                "modeling", "backtest", "backtest_run",
                context_id="ctx-A", family_id="baselines",
            ),
        ]
        fold = NodeStateFold()
        for item in corpus:
            fold.apply(item)
        states = fold.node_states_with_evidence(run_context_id="ctx-B")
        baseline = _node(states, "modeling", "baseline_estimation")
        assert baseline["status"] == "done"
        assert baseline["validity"] == "stale"
        assert baseline["source_event_id"]
        assert baseline["reason_source_event_id"]


# ── Контур C: e2e продюсеры (полное API-окружение) ───────────────────


class TestModelingProducersE2E:
    def test_candidates_event_carries_pool_facts_and_marks_node_done(self):
        """POST /modeling/candidates: факт candidates_generated несёт
        факты пула (spec_version -- версия методики, statistics --
        состав), узел Пул кандидатов -- done (до задачи: событие без
        последствий, узел pending -- F09/P13)."""
        _prepare_modeling_session()
        resp = client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
        )
        assert resp.status_code == 200, resp.text
        statistics = resp.json().get("statistics") or {}
        events = [
            e for e in _trace_events()
            if e.get("event_type") == "candidates_generated"
        ]
        assert events, "факт candidates_generated не записан"
        payload = events[-1].get("payload") or {}
        assert payload.get("spec_version")
        assert payload.get("runnable_candidates") == statistics.get(
            "runnable_candidates"
        )
        node = _trace_node("modeling", "candidate_generation")
        assert node["status"] == "done"
        assert node["status_reason"] == EVENT_NODE_REASON["candidates_generated"]

    def test_selection_evaluation_leaves_selection_open(self):
        """POST /modeling/selection/evaluate: факт оценки не закрывает
        выбор -- узел selection НЕ done (done несёт только
        model_selected)."""
        self._closed_tuning_scope()
        assert client.post(
            "/v1/session/modeling/diagnostics/ensure", json={}
        ).status_code == 200
        assert client.post(
            "/v1/session/modeling/compare", json={}
        ).status_code == 200
        resp = client.post(
            "/v1/session/modeling/selection/evaluate",
            json={"min_oof_points": 4},
        )
        assert resp.status_code == 200, resp.text
        events = [
            e for e in _trace_events()
            if e.get("event_type") == "selection_evaluated"
        ]
        assert events, "факт selection_evaluated не записан"
        node = _trace_node("modeling", "selection")
        assert node["status"] == "in_progress"
        assert node["status_reason"] == EVENT_NODE_REASON["selection_evaluated"]

    def _skip_ready_session(self) -> None:
        """Сессия, готовая к осознанному пропуску тюнинга (паттерн
        test_one_defaults_decision_atomically_closes_the_complete_
        tuning_scope): candidates → baselines → backtest ets →
        исключение остальных из backtest scope."""
        _prepare_modeling_session()
        assert client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
        ).status_code == 200
        assert client.post("/v1/session/modeling/baselines").status_code == 200
        assert client.post(
            "/v1/session/modeling/backtest", json={"model_id": "ets"}
        ).status_code == 200
        scope = client.get("/v1/session/modeling/state").json()[
            "artifacts"
        ]["execution_scope"]
        for model_id in scope["pending_backtest_model_ids"]:
            excluded = client.post(
                "/v1/session/modeling/backtest/exclude",
                json={
                    "model_id": model_id, "decision": "exclude",
                    "reason": "Не входит в проверку AUDIT-7A",
                    "acknowledge": True,
                },
            )
            assert excluded.status_code == 200, excluded.text

    def test_skip_reason_is_echoed_and_journaled(self):
        """RED-карточка §15 «skipped с причиной»: осознанный пропуск
        несёт обоснование -- ответ /tuning/skip ЭХОМ возвращает reason
        (до задачи: обоснование терялось -- в факте трассы только
        model_id), факт трассы содержит reason, узел Тюнинг -- done с
        честным reason."""
        self._skip_ready_session()
        resp = client.post(
            "/v1/session/modeling/tuning/skip",
            json={
                "model_id": "ets",
                "reason": "Оставить параметры по умолчанию (AUDIT-7A)",
                "acknowledge": True,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("reason") == "Оставить параметры по умолчанию (AUDIT-7A)", (
            "ответ пропуска не эхом возвращает обоснование -- факту трассы "
            "нечем обосновать решение"
        )
        events = [
            e for e in _trace_events()
            if e.get("event_type") == "tuning_skipped"
        ]
        assert events, "факт tuning_skipped не записан"
        payload = events[-1].get("payload") or {}
        assert payload.get("model_id") == "ets"
        assert payload.get("reason") == "Оставить параметры по умолчанию (AUDIT-7A)"
        node = _trace_node("modeling", "tuning")
        assert node["status"] == "done"
        assert node["status_reason"] == EVENT_NODE_REASON["tuning_skipped"]

    def test_skip_pending_reason_is_echoed(self):
        """Атомарный пропуск всего pending-скоупа: reason эхом в ответе
        и в факте трассы (тот же класс обоснованного решения)."""
        self._skip_ready_session()
        resp = client.post(
            "/v1/session/modeling/tuning/skip-pending",
            json={
                "reason": "Осознанно оставлены defaults (AUDIT-7A)",
                "acknowledge": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("reason") == "Осознанно оставлены defaults (AUDIT-7A)"
        events = [
            e for e in _trace_events()
            if e.get("event_type") == "tuning_skipped"
        ]
        assert events
        payload = events[-1].get("payload") or {}
        assert payload.get("reason") == "Осознанно оставлены defaults (AUDIT-7A)"

    def test_job_start_and_cancel_are_linked_by_job_id(self):
        """Job started/cancelled связываются ОДНИМ job id: payload
        обоих фактов несёт job_id (до задачи связность отсутствовала --
        событие запуска не отличить от события отмены другого job);
        cancel до completion -- узел НЕ done."""
        _prepare_modeling_session()
        assert client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "sliding", "horizon": 2, "n_splits": 2,
                  "gap": 1, "train_window": 40},
        ).status_code == 200
        started = client.post(
            "/v1/session/modeling/jobs/start",
            json={"operation": "tuning", "model_id": "ets", "max_trials": 2,
                  "metric": "rmse", "random_state": 42,
                  "idempotency_key": "audit7a-job"},
        )
        assert started.status_code == 200, started.text
        job_id = started.json()["job_id"]
        node = _trace_node("modeling", "tuning")
        assert node["status"] == "in_progress", (
            "запущенный job -- работа в процессе, не результат"
        )
        cancelled = client.post(
            f"/v1/session/modeling/jobs/{job_id}/cancel",
            json={"reason": "Отмена до завершения (AUDIT-7A)"},
        )
        assert cancelled.status_code == 200, cancelled.text
        started_events = [
            e for e in _trace_events()
            if e.get("event_type") == "tuning_job_started"
        ]
        cancelled_events = [
            e for e in _trace_events()
            if e.get("event_type") == "tuning_job_cancelled"
        ]
        assert started_events and cancelled_events
        started_payload = started_events[-1].get("payload") or {}
        cancelled_payload = cancelled_events[-1].get("payload") or {}
        assert started_payload.get("job_id") == job_id, (
            "факт запуска не несёт job_id -- связность operation/job "
            "не удостоверяется трассой"
        )
        assert cancelled_payload.get("job_id") == job_id, (
            "факт отмены не несёт job_id -- не связан с запуском"
        )
        node = _trace_node("modeling", "tuning")
        assert node["status"] != "done"
        assert node["status"] == "pending"

    def test_late_old_job_facts_do_not_raise_current_context(self):
        """RED-карточка §15 «результат старого job»: факт запуска
        старого job (контекст A) после смены цели (контекст B) --
        validity=stale против текущего контекста запуска; ни один
        старый факт не представляется текущей работой. Завершение
        job-контура фактом трассы не является (пин PROGR-20 --
        «результат старого job» не может выдать себя за текущий);
        поздняя отмена после смены цели честно отказывает 404 (записи
        job инвалидированы вместе с контекстом) и НЕ пишет нового
        факта -- current-context не повышается."""
        _prepare_modeling_session()
        assert client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "sliding", "horizon": 2, "n_splits": 2,
                  "gap": 1, "train_window": 40},
        ).status_code == 200
        started = client.post(
            "/v1/session/modeling/jobs/start",
            json={"operation": "tuning", "model_id": "ets", "max_trials": 2,
                  "metric": "rmse", "random_state": 42,
                  "idempotency_key": "audit7a-stale-job"},
        )
        assert started.status_code == 200, started.text
        job_id = started.json()["job_id"]
        context_before = _trace_context_id()
        node = _trace_node("modeling", "tuning")
        assert node["status"] == "in_progress", (
            "запущенный job -- работа в процессе, не результат"
        )
        assert node["validity"] == "current"
        # Смена цели -- новый контекст расчёта (AUDIT-C); записи job
        # инвалидированы вместе с моделирующими артефактами контекста A.
        switched = client.post(
            "/v1/session/target-column", json={"column": "driver"}
        )
        assert switched.status_code == 200, switched.text
        context_after = _trace_context_id()
        assert context_after and context_after != context_before, (
            "смена цели обязана сменить контекст расчёта (AUDIT-C)"
        )
        node = _trace_node("modeling", "tuning")
        assert node["status"] == "in_progress", (
            "последний факт трассы -- запуск старого job (last-wins)"
        )
        assert node["validity"] == "stale", (
            "факт старого контекста не должен представляться текущей "
            "работой: старый job не повышает current-context"
        )
        # Поздняя отмена старого job: записи инвалидированы -- честный
        # отказ, НОВОГО ФАКТА в трассе нет (current не трогается).
        modelling_events_before = len([
            e for e in _trace_events() if e.get("stage") == "modeling"
        ])
        cancelled = client.post(
            f"/v1/session/modeling/jobs/{job_id}/cancel",
            json={"reason": "Поздняя отмена старого job"},
        )
        assert cancelled.status_code == 404, (
            "записи старого job инвалидированы сменой контекста -- "
            "отмена не может выдать себя за действующую операцию"
        )
        modelling_events_after = len([
            e for e in _trace_events() if e.get("stage") == "modeling"
        ])
        assert modelling_events_after == modelling_events_before, (
            "отказ отмены не сеет фактов трассы"
        )
        statuses = [
            e.get("event_type") for e in _trace_events()
            if e.get("stage") == "modeling"
        ]
        assert "tuning_job_cancelled" not in statuses
        assert "tuning_trial_completed" not in statuses
        node = _trace_node("modeling", "tuning")
        assert node["status"] != "done"

    def test_missing_producers_never_fabricate_done(self):
        """RED-карточка §15 «отсутствующий producer не даёт
        вымышленного done»: полный реалистичный контур Modeling (пул →
        бэктест → тюнинг → диагностика → сравнение → оценка → выбор →
        карта) НЕ создаёт фактов для problem_definition/
        data_structure/constraint_mapping -- честное отсутствие решения
        (узлы pending, reason нет); «done по открытию вкладки»
        невозможен: носителей факта нет. baseline_estimation получает
        done от РЕАЛЬНОГО носителя (backtest baselines)."""
        self._closed_tuning_scope()
        assert client.post(
            "/v1/session/modeling/diagnostics/ensure", json={}
        ).status_code == 200
        assert client.post(
            "/v1/session/modeling/compare", json={}
        ).status_code == 200
        assert client.post(
            "/v1/session/modeling/selection/evaluate",
            json={"min_oof_points": 4},
        ).status_code == 200
        for absent_node in (
            "problem_definition", "data_structure", "constraint_mapping",
        ):
            node = _trace_node("modeling", absent_node)
            assert node["status"] == "pending", absent_node
            assert node["status_reason"] is None, absent_node
        baseline = _trace_node("modeling", "baseline_estimation")
        assert baseline["status"] == "done", (
            "baseline рассчитан (/modeling/baselines) -- реальный "
            "носитель backtest_run(family_id=baselines) обязан его "
            "удостоверять"
        )

    def _closed_tuning_scope(self) -> None:
        """Закрытый осознанным пропуском тюнинг-скоуп (сравнение требует
        полного scope): candidates → baselines → backtest ets и
        baseline-модели → исключение остальных → skip ets с
        обоснованием. Backtest НАИВНОЙ baseline-модели -- реальный
        трассируемый факт backtest_run(family_id=baselines) (носитель
        узла Baseline; /modeling/baselines сознательно вне таблицы
        трассы -- пин PROGR-20)."""
        self._skip_ready_session()
        assert client.post(
            "/v1/session/modeling/backtest", json={"model_id": "naive"}
        ).status_code == 200
        resp = client.post(
            "/v1/session/modeling/tuning/skip",
            json={
                "model_id": "ets",
                "reason": "Оставить параметры по умолчанию (AUDIT-7A)",
                "acknowledge": True,
            },
        )
        assert resp.status_code == 200, resp.text

    def test_p19_method_change_same_count_is_new_fact_control(self):
        """Контроль (совместно с AUDIT-4, GREEN на базе): параметры
        результата (method/mode) в ключе дедупа -- иной метод при той же
        status/count-картине создаёт факт; рефетч того же результата не
        журналируется (DEDUPE_PARAM_KEYS)."""
        from apps.api.trace_hook import DEDUPE_PARAM_KEYS

        assert DEDUPE_PARAM_KEYS == ("method", "mode")
        _prepare_modeling_session()
        first = client.get("/v1/session/dataset/outlier-profile?method=iqr")
        assert first.status_code == 200, first.text
        second = client.get("/v1/session/dataset/outlier-profile?method=zscore")
        assert second.status_code == 200, second.text
        methods = [
            e.get("payload", {}).get("method")
            for e in _trace_events()
            if e.get("event_type") == "outliers_profile_status"
        ]
        assert methods == ["iqr", "zscore"], (
            "иной метод при той же картинке подавлен дедупом -- история "
            "выполненных методов потеряна (P19/F13)"
        )
        third = client.get("/v1/session/dataset/outlier-profile?method=zscore")
        assert third.status_code == 200, third.text
        methods = [
            e.get("payload", {}).get("method")
            for e in _trace_events()
            if e.get("event_type") == "outliers_profile_status"
        ]
        assert methods == ["iqr", "zscore"], (
            "фокус-рефетч того же результата не должен журналироваться "
            "новым методом"
        )
