# tests/api/test_mentor_rules.py
"""Тесты Task PROGR-6 (plan_progress.md): Наставник v1 -- правило-движок
(spec_progress.md §7) без LLM, с порогами в rules/mentor.yaml (§12 п.7).

Контуры:

  1. Конфигурация порогов: rules/mentor.yaml читается fail-closed на
     импорте (паттерн EDA-JSON §12 п.2); канонические стартовые значения
     §7.2/§12 п.7 (0.2 / 0.3 / 10 минут / 3 стратегии) живут в YAML,
     а не в коде -- движок читает конфиг на ВЫЗОВЕ (патч singleton
     проверяет, что порог из конфига, а не хардкод).
  2. §7.2 sanity-правила (on_correction_result): no_effect /
     over_aggressive / excessive_data_loss -- полный список сработавших,
     правила независимы; нормализованный CorrectionOutcomeSummary
     (переупаковка preview-ответа любого Мастера).
  3. §7.2 thrashing (on_demand_with_history -- третий вид триггера):
     окно 10 минут, >=3 разных стратегий correction_previewed без
     correction_applied; применяется к истории trace_events запуска.
  4. §7.1 «Следующий шаг» (on_demand): ОДНА рекомендация за раз --
     первое сработавшее правило в сортировке по (priority, rule_id);
     каноническое правило regularity_before_decomposition; базовые
     правила Моделирования (Этап 2 §11) и Прогнозирования
     (forecast_not_compared_before_export).
  5. derive_node_statuses: С PROGR-10 (Расхождение №1) движок живёт в
     app/core/node_status.py -- тесты переехали в
     tests/api/test_node_status_engine.py (единый движок трёх
     потребителей); здесь -- только правила Наставника.
  6. REST: GET /v1/progress/runs/{run_id}/mentor/next-step (слой 2:
     404 неизвестный запуск, 503 -- долговременный слой недоступен,
     N-4 -- в ответе нет семантики управления панелью);
     POST /v1/progress/mentor/sanity-check -- чистое вычисление над
     телом запроса (без долговременного слоя; fail-closed 422 на
     неизвестную пару (stage, node_id) -- паттерн make_node_state).
  7. §8 контракт рендера текстов (PROGR-12, Расхождение №3):
     MentorTextRenderer -- Protocol, зафиксированный В КОДЕ (раньше --
     только упоминание в докстринге); дефолт FormatMentorTextRenderer
     (.format() шаблона, без сети); evaluate_* рендерят ЧЕРЕЗ renderer
     ПОСЛЕ вычисления факта (renderer не вызывается, если правило не
     сработало -- LLM никогда не решает); подключение LLM позже =
     добавление реализации Protocol, не ввод интерфейса; fail-closed
     валидация шаблонов на импорте расширена на ВСЕ триггеры.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import mentor_rules
from app.core.mentor_rules import (
    CorrectionOutcomeSummary,
    FormatMentorTextRenderer,
    MentorRule,
    MentorTextRenderer,
    TRIGGER_ON_CORRECTION_RESULT,
    evaluate_history_warnings,
    evaluate_next_step,
    evaluate_sanity,
    load_mentor_config,
    phase_text,
)
from apps.api.trace_events import make_trace_event


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных, чистые синглтоны."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outcome(**overrides) -> CorrectionOutcomeSummary:
    """Базовый preview-исход: стратегия что-то изменила, без потерь."""
    base = dict(
        stage="preprocessing",
        node_id="missing",
        strategy="median_mode",
        method=None,
        affected_count_before=10,
        changed_count=8,
        still_affected_count=2,
        rows_before=100,
        rows_after=100,
        stats_before=None,
        stats_after=None,
    )
    base.update(overrides)
    return CorrectionOutcomeSummary(**base)


def _ts(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _preview_event(strategy: str, ts: str, node_id: str = "missing") -> dict:
    return {
        "event_id": f"e-{strategy}-{ts}",
        "run_id": "RUN-AAA00001",
        "ts": ts,
        "stage": "preprocessing",
        "node_id": node_id,
        "event_type": "correction_previewed",
        "payload": {"strategy": strategy},
        "actor": "user",
    }


# ── Контур 1: конфигурация порогов (§12 п.7) ─────────────────────────


class TestMentorConfig:
    def test_canonical_thresholds_live_in_yaml_not_code(self):
        """Канонические стартовые значения §7.2/§12 п.7 -- в rules/mentor.yaml."""
        config = load_mentor_config()
        assert config["sanity"]["over_aggressive"]["std_collapse_factor"] == 0.2
        assert config["sanity"]["excessive_data_loss"]["max_removed_share"] == 0.3
        assert config["history"]["thrashing"]["window_minutes"] == 10
        assert config["history"]["thrashing"]["distinct_strategies"] == 3

    def test_missing_file_is_import_error_fail_closed(self, tmp_path: Path):
        with pytest.raises(ImportError):
            load_mentor_config(tmp_path / "no_such_mentor.yaml")

    def test_broken_yaml_is_import_error_fail_closed(self, tmp_path: Path):
        broken = tmp_path / "mentor.yaml"
        broken.write_text("sanity: [unclosed", encoding="utf-8")
        with pytest.raises(ImportError):
            load_mentor_config(broken)

    def test_engine_reads_config_at_call_time_not_hardcode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Порог over_aggressive читается из конфига на вызове: сдвиг порога
        в конфиге меняет поведение правила без правки кода (§12 п.7)."""
        custom = tmp_path / "mentor.yaml"
        config = load_mentor_config()
        config["sanity"]["over_aggressive"]["std_collapse_factor"] = 0.9
        custom.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(
            mentor_rules, "MENTOR_CONFIG", load_mentor_config(custom)
        )
        outcome = _outcome(
            stats_before={"mean": 10.0, "std": 5.0},
            stats_after={"mean": 10.0, "std": 2.0},  # падение в 2.5 раза: <0.9, но не <0.2
        )
        warnings = evaluate_sanity(outcome)
        assert any(w.rule_id == "over_aggressive" for w in warnings)


# ── Контур 2: sanity-правила §7.2 (on_correction_result) ─────────────


class TestSanityRules:
    def test_no_effect_fires_when_nothing_changed(self):
        outcome = _outcome(changed_count=0, still_affected_count=10)
        warnings = evaluate_sanity(outcome)
        rule_ids = [w.rule_id for w in warnings]
        assert "no_effect" in rule_ids
        warning = next(w for w in warnings if w.rule_id == "no_effect")
        assert warning.severity == "warning"
        assert warning.suggested_action

    def test_no_effect_silent_when_affected_zero(self):
        """Нечего исправлять -- не ошибка выбора метода."""
        outcome = _outcome(affected_count_before=0, changed_count=0)
        assert all(w.rule_id != "no_effect" for w in evaluate_sanity(outcome))

    def test_no_effect_silent_when_strategy_worked(self):
        assert all(w.rule_id != "no_effect" for w in evaluate_sanity(_outcome()))

    def test_over_aggressive_fires_on_std_collapse(self):
        outcome = _outcome(
            stats_before={"mean": 10.0, "std": 5.0},
            stats_after={"mean": 10.0, "std": 0.5},  # 0.5 < 5.0 * 0.2
        )
        warnings = evaluate_sanity(outcome)
        warning = next(w for w in warnings if w.rule_id == "over_aggressive")
        assert warning.severity == "warning"
        assert "5 раз" in warning.message  # каноническая формулировка §7.2

    def test_over_aggressive_boundary_not_fired(self):
        """Ровно на границе (std_after == std_before * 0.2) -- тишина."""
        outcome = _outcome(
            stats_before={"mean": 10.0, "std": 5.0},
            stats_after={"mean": 10.0, "std": 1.0},
        )
        assert all(w.rule_id != "over_aggressive" for w in evaluate_sanity(outcome))

    def test_over_aggressive_silent_without_stats(self):
        assert all(
            w.rule_id != "over_aggressive"
            for w in evaluate_sanity(_outcome(stats_before=None, stats_after=None))
        )

    def test_excessive_data_loss_fires_above_share(self):
        outcome = _outcome(
            strategy="drop_rows", rows_before=100, rows_after=60  # 40% > 30%
        )
        warnings = evaluate_sanity(outcome)
        warning = next(w for w in warnings if w.rule_id == "excessive_data_loss")
        assert "40%" in warning.message  # доля посчитана, не захардкожена

    def test_excessive_data_loss_boundary_not_fired(self):
        """Ровно 30% (граница included) -- тишина: правило строгое >."""
        outcome = _outcome(strategy="drop_rows", rows_before=100, rows_after=70)
        assert all(
            w.rule_id != "excessive_data_loss" for w in evaluate_sanity(outcome)
        )

    def test_excessive_data_loss_only_for_drop_rows(self):
        outcome = _outcome(strategy="median_mode", rows_before=100, rows_after=60)
        assert all(
            w.rule_id != "excessive_data_loss" for w in evaluate_sanity(outcome)
        )

    def test_excessive_data_loss_guard_zero_rows(self):
        outcome = _outcome(strategy="drop_rows", rows_before=0, rows_after=0)
        assert all(
            w.rule_id != "excessive_data_loss" for w in evaluate_sanity(outcome)
        )

    def test_returns_full_list_not_first_match(self):
        """§7.2: в отличие от §7.1 возвращается ВЕСЬ список -- проблемы
        независимы и не взаимоисключающи."""
        outcome = _outcome(
            strategy="drop_rows",
            changed_count=0,
            rows_before=100,
            rows_after=40,  # 60% потерь
        )
        rule_ids = {w.rule_id for w in evaluate_sanity(outcome)}
        assert {"no_effect", "excessive_data_loss"} <= rule_ids


# ── Контур 3: thrashing (on_demand_with_history) ─────────────────────


class TestThrashingHistoryRule:
    def test_fires_three_distinct_strategies_without_apply(self):
        events = [
            _preview_event("median_mode", _ts(9)),
            _preview_event("mean_mode", _ts(8)),
            _preview_event("drop_rows", _ts(7)),
        ]
        warnings = evaluate_history_warnings(events)
        assert len(warnings) == 1
        assert warnings[0].rule_id == "thrashing_detected"
        # «Как решать», не «куда идти»: подсказки-действия нет (§7.2);
        # deep-link отсутствует и в самом правиле реестра.
        assert warnings[0].suggested_action is None
        thrashing_rule = mentor_rules.HISTORY_RULES[0]
        assert thrashing_rule.recommended_action is None
        assert "чекпоинтом" in warnings[0].message

    def test_silent_with_fewer_strategies(self):
        events = [
            _preview_event("median_mode", _ts(9)),
            _preview_event("median_mode", _ts(8)),
            _preview_event("mean_mode", _ts(7)),
        ]
        assert evaluate_history_warnings(events) == []

    def test_applied_event_cancels_warning(self):
        events = [
            _preview_event("median_mode", _ts(9)),
            _preview_event("mean_mode", _ts(8)),
            _preview_event("drop_rows", _ts(7)),
            {
                "event_id": "e-apply",
                "ts": _ts(6),
                "stage": "preprocessing",
                "node_id": "missing",
                "event_type": "correction_applied",
                "payload": {"strategy": "median_mode"},
                "actor": "user",
            },
        ]
        assert evaluate_history_warnings(events) == []

    def test_events_outside_window_ignored(self):
        events = [
            _preview_event("median_mode", _ts(30)),
            _preview_event("mean_mode", _ts(40)),
            _preview_event("drop_rows", _ts(50)),
        ]
        assert evaluate_history_warnings(events) == []

    def test_naive_timestamp_treated_as_utc(self):
        events = [
            _preview_event("median_mode", _ts(9)),
            _preview_event("mean_mode", _ts(8)),
            {
                "event_id": "e-3",
                "ts": (datetime.now() - timedelta(minutes=7)).isoformat(),  # naive
                "stage": "preprocessing",
                "node_id": "missing",
                "event_type": "correction_previewed",
                "payload": {"strategy": "drop_rows"},
                "actor": "user",
            },
        ]
        assert len(evaluate_history_warnings(events)) == 1

    def test_unreadable_ts_does_not_crash(self):
        events = [
            _preview_event("median_mode", _ts(9)),
            _preview_event("mean_mode", _ts(8)),
            {
                "event_id": "e-bad",
                "ts": "not-a-timestamp",
                "stage": "preprocessing",
                "node_id": "missing",
                "event_type": "correction_previewed",
                "payload": {"strategy": "drop_rows"},
                "actor": "user",
            },
        ]
        # Битое ts -- деградация (событие вне окна), не 500.
        assert isinstance(evaluate_history_warnings(events), list)

    def test_trace_event_objects_accepted(self):
        """Слой 2 хранит TraceEvent -- движок принимает и объекты, и dict."""
        fresh = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        events = [
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-AAA00001", strategy="median_mode", ts=fresh,
            ),
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-AAA00001", strategy="mean_mode", ts=fresh,
            ),
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-AAA00001", strategy="flag", ts=fresh,
            ),
        ]
        assert len(evaluate_history_warnings(events)) == 1


# ── Контур 4: «Следующий шаг» §7.1 (on_demand) ───────────────────────


class TestNextStepRules:
    def test_canonical_regularity_before_decomposition(self):
        """Дословно правило-пример §7.1: regularity=warning, декомпозиция
        ещё не решена -- рекомендация сначала исправить регулярность."""
        statuses = {"preprocessing/regularity": "warning"}
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "regularity_before_decomposition"
        assert recommendation.recommended_action == "preprocessing.regularity"
        assert "STL-декомпозиция" in recommendation.message

    def test_decomposition_done_silences_regularity_rule(self):
        statuses = {
            "preprocessing/regularity": "warning",
            "preprocessing/decomposition": "done",
        }
        recommendation = evaluate_next_step(statuses)
        assert recommendation is None or (
            recommendation.rule_id != "regularity_before_decomposition"
        )

    def test_single_recommendation_first_by_priority(self):
        """§7.1: Наставник даёт ОДНУ рекомендацию -- первое сработавшее
        правило по (priority, rule_id), не весь список."""
        statuses = {
            "preprocessing/regularity": "warning",   # priority 10
            "preprocessing/missing": "warning",      # priority 30
            "preprocessing/outliers": "warning",     # priority 30
        }
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "regularity_before_decomposition"

    def test_tie_broken_by_rule_id(self):
        """Одинаковый priority -- детерминизм по rule_id (missing < outliers)."""
        statuses = {
            "preprocessing/missing": "warning",
            "preprocessing/outliers": "warning",
        }
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "preprocessing_missing_attention"

    def test_modeling_selected_without_backtest(self):
        statuses = {"modeling/selection": "done"}
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "modeling_selected_without_backtest"
        assert recommendation.recommended_action == "modeling.backtest"

    def test_modeling_candidates_without_selection(self):
        statuses = {"modeling/backtest": "done"}
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "modeling_candidates_without_selection"
        assert recommendation.recommended_action == "modeling.selection"

    def test_forecast_not_compared_before_export(self):
        """Правило §7.1 для Прогнозирования (категория C §11 -- правило
        включено сразу, данные появляются по мере работы Прогнозирования)."""
        statuses = {"forecasting/forecast_generated": "done"}
        recommendation = evaluate_next_step(statuses)
        assert recommendation is not None
        assert recommendation.rule_id == "forecast_not_compared_before_export"
        assert recommendation.recommended_action == "forecasting.compare"

    def test_no_match_returns_none(self):
        assert evaluate_next_step({}) is None
        assert evaluate_next_step({"preprocessing/missing": "done"}) is None

    def test_all_on_demand_rules_have_meta(self):
        for rule in mentor_rules.NEXT_STEP_RULES:
            assert rule.trigger == "on_demand"
            assert rule.explanation_template
            assert isinstance(rule.priority, int)


# ── Контур 5: derive_node_statuses -- переехал в PROGR-10 ────────────
# Тесты движка статусов живут в tests/api/test_node_status_engine.py
# (Расхождение №1: единый движок app/core/node_status.py для панели,
# Наставника и admin-аналитики; копий быть не должно -- см. там же
# контур «владение").


# ── Контур 6: REST-эндпоинты Наставника ──────────────────────────────


def _seed_run(store, run_id: str = "RUN-AAA00001") -> None:
    from apps.api import research_runs

    store.upsert_run(
        research_runs.ResearchRun(
            run_id=run_id,
            session_id="seed-session",
            dataset_fingerprint="f" * 64,
            dataset_name="seed.csv",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
        )
    )


def _seed_event(store, run_id: str, event) -> None:
    store.append_event(run_id, event)


class TestMentorNextStepEndpoint:
    def test_404_unknown_run(self, client: TestClient):
        response = client.get("/v1/progress/runs/RUN-NOPE0000/mentor/next-step")
        assert response.status_code == 404

    def test_recommendation_from_layer2_trace(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(
            store,
            "RUN-AAA00001",
            make_trace_event(
                "upload_completed", stage="upload",
                node_id="structure_confirmed", run_id="RUN-AAA00001",
            ),
        )
        _seed_event(
            store,
            "RUN-AAA00001",
            make_trace_event(
                "correction_previewed", stage="preprocessing",
                node_id="regularity", run_id="RUN-AAA00001", strategy="resample",
            ),
        )
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "RUN-AAA00001"
        assert data["recommendation"]["rule_id"] == "regularity_before_decomposition"
        assert data["recommendation"]["recommended_action"] == "preprocessing.regularity"
        assert data["phase_text"]
        assert data["summary"]["stage"] == "preprocessing"
        assert data["summary"]["total_nodes"] > 0
        # N-4: в ответе нет семантики закрытия/навигации панели.
        assert "close" not in data and "panel" not in data

    def test_history_warning_thrashing_in_response(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        for strategy in ("median_mode", "mean_mode", "drop_rows"):
            _seed_event(
                store,
                "RUN-AAA00001",
                make_trace_event(
                    "correction_previewed", stage="preprocessing",
                    node_id="missing", run_id="RUN-AAA00001", strategy=strategy,
                ),
            )
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        rule_ids = [w["rule_id"] for w in response.json()["history_warnings"]]
        assert "thrashing_detected" in rule_ids

    def test_no_recommendation_still_valid_response(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] is None
        assert data["history_warnings"] == []


class TestSanityCheckEndpoint:
    def test_url_is_run_independent(self, client: TestClient):
        """§7.2: sanity-check НЕ run-scoped -- чистое вычисление над
        preview-ответом Мастера, построенным клиентом."""
        response = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing",
                "node_id": "missing",
                "strategy": "median_mode",
                "affected_count_before": 10,
                "changed_count": 0,
                "still_affected_count": 10,
                "rows_before": 0,
                "rows_after": 0,
            },
        )
        assert response.status_code == 200
        rule_ids = [w["rule_id"] for w in response.json()["warnings"]]
        assert rule_ids == ["no_effect"]

    def test_unknown_node_fail_closed_422(self, client: TestClient):
        response = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing",
                "node_id": "phantom_node",
                "strategy": "median_mode",
                "affected_count_before": 1,
                "changed_count": 1,
                "still_affected_count": 0,
                "rows_before": 10,
                "rows_after": 10,
            },
        )
        assert response.status_code == 422

    def test_unknown_stage_fail_closed_422(self, client: TestClient):
        response = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "not_a_stage",
                "node_id": "missing",
                "strategy": "median_mode",
            },
        )
        assert response.status_code == 422

    def test_multiple_warnings_full_list(self, client: TestClient):
        response = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing",
                "node_id": "missing",
                "strategy": "drop_rows",
                "affected_count_before": 50,
                "changed_count": 0,
                "still_affected_count": 50,
                "rows_before": 100,
                "rows_after": 30,
            },
        )
        assert response.status_code == 200
        rule_ids = {w["rule_id"] for w in response.json()["warnings"]}
        assert {"no_effect", "excessive_data_loss"} <= rule_ids

    def test_clean_outcome_empty_warnings(self, client: TestClient):
        response = client.post(
            "/v1/progress/mentor/sanity-check",
            json={
                "stage": "preprocessing",
                "node_id": "outliers",
                "strategy": "winsorize",
                "method": "iqr",
                "affected_count_before": 5,
                "changed_count": 5,
                "still_affected_count": 0,
                "rows_before": 100,
                "rows_after": 100,
            },
        )
        assert response.status_code == 200
        assert response.json()["warnings"] == []


# ── Контур 7: §8 -- контракт рендера текстов (MentorTextRenderer) ────


class _RecordingRenderer:
    """Stub-реализация Protocol §8: фиксирует вызовы render(rule,
    context), возвращает фиксированный текст -- проверяет, что сообщения
    ДОХОДЯТ до потребителя именно через renderer, а не мимо него."""

    def __init__(self, text: str = "РЕНДЕР-СТАБ") -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    def render(self, rule: MentorRule, context: dict) -> str:  # type: ignore[override]
        self.calls.append((rule.rule_id, dict(context)))
        return self.text


class TestMentorTextRendererContract:
    # -- сам контракт (Protocol в коде, не на бумаге) --

    def test_protocol_runtime_checkable_and_default_conforms(self):
        """Дефолтная реализация структурно удовлетворяет Protocol §8."""
        assert isinstance(
            mentor_rules.DEFAULT_TEXT_RENDERER, MentorTextRenderer
        )

    def test_duck_typed_renderer_satisfies_protocol_structurally(self):
        """Protocol СТРУКТУРНЫЙ: любая реализация render(rule, context)
        -> str годится -- подключение LLM позже = добавление реализации
        (LLMMentorTextRenderer), НЕ ввод интерфейса (Расхождение №3)."""

        class _LLMStub:  # номинально НЕ наследник -- только по форме
            def render(self, rule: MentorRule, context: dict) -> str:
                return "llm"

        assert isinstance(_LLMStub(), MentorTextRenderer)

    # -- семантика дефолтной реализации (спека §8: «просто .format()
    #    шаблона, без сети/модели») --

    def _probe_rule(self, template: str) -> MentorRule:
        return MentorRule(
            rule_id="probe",
            stage="preprocessing",
            trigger=TRIGGER_ON_CORRECTION_RESULT,
            priority=99,
            explanation_template=template,
        )

    def test_default_renderer_formats_template_with_context(self):
        text = mentor_rules.DEFAULT_TEXT_RENDERER.render(
            self._probe_rule("Доля {removed_share:.0%} строк; в {times} раз."),
            {"removed_share": 0.4, "times": 5},
        )
        assert text == "Доля 40% строк; в 5 раз."

    def test_default_renderer_static_template_ignores_extra_context(self):
        """Статичный шаблон + богатый контекст (агрегированные факты для
        будущего LLM) -- лишние ключи .format() игнорирует."""
        text = mentor_rules.DEFAULT_TEXT_RENDERER.render(
            self._probe_rule("Статичный текст."), {"anything": 1}
        )
        assert text == "Статичный текст."

    def test_default_renderer_missing_param_is_strict_key_error(self):
        """Строгий .format(): пропущенный параметр шаблона -- KeyError
        (ловится тестами на пары шаблон/контекст), не тихая деградация."""
        with pytest.raises(KeyError):
            mentor_rules.DEFAULT_TEXT_RENDERER.render(
                self._probe_rule("Нужен {times}."), {}
            )

    # -- evaluate_* рендерят ЧЕРЕЗ renderer (§7.1 и §7.2 одинаково) --

    def test_next_step_message_rendered_through_protocol(self):
        """§7.1: сообщение рекомендации -- результат renderer.render;
        контекст несёт агрегированные факты (статусы узлов), виденные
        правилом."""
        renderer = _RecordingRenderer()
        statuses = {"preprocessing/regularity": "warning"}
        recommendation = evaluate_next_step(statuses, renderer=renderer)
        assert recommendation is not None
        assert recommendation.message == "РЕНДЕР-СТАБ"
        assert [c[0] for c in renderer.calls] == [
            "regularity_before_decomposition"
        ]
        assert renderer.calls[0][1]["statuses"] == statuses

    def test_sanity_message_rendered_through_protocol(self):
        """§7.2: message -- от renderer; severity/suggested_action -- из
        факта правила (renderer НЕ решает, есть ли ошибка); контекст
        несёт параметры шаблона ({times}/{removed_share})."""
        renderer = _RecordingRenderer()
        outcome = _outcome(
            strategy="drop_rows",
            affected_count_before=50,
            changed_count=0,
            still_affected_count=50,
            rows_before=100,
            rows_after=30,
            stats_before={"mean": 10.0, "std": 5.0},
            stats_after={"mean": 10.0, "std": 0.5},
        )
        warnings = evaluate_sanity(outcome, renderer=renderer)
        assert {w.rule_id for w in warnings} == {
            "no_effect",
            "over_aggressive",
            "excessive_data_loss",
        }
        assert all(w.message == "РЕНДЕР-СТАБ" for w in warnings)
        by_rule = {c[0]: c[1] for c in renderer.calls}
        assert by_rule["over_aggressive"]["times"] == 5
        assert abs(by_rule["excessive_data_loss"]["removed_share"] - 0.7) < 1e-9
        severity_by_rule = {w.rule_id: w.severity for w in warnings}
        assert severity_by_rule == {
            "no_effect": "warning",
            "over_aggressive": "warning",
            "excessive_data_loss": "warning",
        }
        assert all(w.suggested_action for w in warnings)

    def test_history_message_rendered_through_protocol(self):
        """on_demand_with_history: thrashing тоже рендерится через
        Protocol (§8: «применимо одинаково и к §7.2»)."""
        renderer = _RecordingRenderer()
        fresh = _ts(1)
        events = [
            make_trace_event(
                "correction_previewed", stage="preprocessing", node_id="missing",
                run_id="RUN-AAA00001", strategy=strategy, ts=fresh,
            )
            for strategy in ("median_mode", "mean_mode", "flag")
        ]
        warnings = evaluate_history_warnings(events, renderer=renderer)
        assert len(warnings) == 1
        assert warnings[0].message == "РЕНДЕР-СТАБ"
        assert warnings[0].severity == "info"
        assert [c[0] for c in renderer.calls] == ["thrashing_detected"]
        assert renderer.calls[0][1]["strategies"] == [
            "median_mode",
            "mean_mode",
            "flag",
        ]

    def test_renderer_not_called_when_no_rule_fires(self):
        """Порядок «сначала правило, потом текст» (спека education §4.2):
        renderer не вызывается, если НИ ОДНО правило не сработало --
        LLM никогда не решает, есть ли ошибка (регресс-тест границы)."""
        renderer = _RecordingRenderer()
        assert evaluate_next_step({}, renderer=renderer) is None
        assert evaluate_sanity(_outcome(), renderer=renderer) == []
        assert evaluate_history_warnings([], renderer=renderer) == []
        assert renderer.calls == []

    def test_default_rendering_matches_legacy_texts_byte_for_byte(self):
        """Дефолтный рендер даёт те же тексты, что инлайн-производство
        до рефактора: формулировки §7.2/§7.1 не изменились (совместимость
        с UI и сертификационными оракулами PROGR-6)."""
        warnings = evaluate_sanity(
            _outcome(
                stats_before={"mean": 10.0, "std": 5.0},
                stats_after={"mean": 10.0, "std": 0.5},
            )
        )
        over = next(w for w in warnings if w.rule_id == "over_aggressive")
        assert "в 5 раз" in over.message
        loss = evaluate_sanity(
            _outcome(
                strategy="drop_rows",
                affected_count_before=50,
                changed_count=0,
                rows_before=100,
                rows_after=30,
            )
        )
        excessive = next(w for w in loss if w.rule_id == "excessive_data_loss")
        assert "70%" in excessive.message
        recommendation = evaluate_next_step({"preprocessing/regularity": "warning"})
        assert recommendation is not None
        assert "STL-декомпозиция" in recommendation.message

    def test_rendered_messages_leave_no_leftover_placeholders(self):
        """Все сработавшие правила всех триггеров: в отрендеренных
        сообщениях не остаётся подстановок {name} -- пары
        шаблон/контекст согласованы (страховка строгого .format())."""
        import re

        leftover = re.compile(r"\{[a-zA-Z_][a-zA-Z_0-9]*")
        scenarios: list[list] = [
            [
                w.message
                for w in evaluate_sanity(
                    _outcome(
                        strategy="drop_rows",
                        affected_count_before=50,
                        changed_count=0,
                        rows_before=100,
                        rows_after=30,
                        stats_before={"mean": 10.0, "std": 5.0},
                        stats_after={"mean": 10.0, "std": 0.5},
                    )
                )
            ],
            [
                w.message
                for w in evaluate_history_warnings(
                    [
                        make_trace_event(
                            "correction_previewed",
                            stage="preprocessing",
                            node_id="missing",
                            run_id="RUN-AAA00001",
                            strategy=strategy,
                            ts=_ts(1),
                        )
                        for strategy in ("median_mode", "mean_mode", "flag")
                    ]
                )
            ],
            [
                r.message
                for r in (
                    evaluate_next_step({"preprocessing/regularity": "warning"}),
                    evaluate_next_step({"preprocessing/missing": "warning"}),
                    evaluate_next_step({"modeling/selection": "done"}),
                    evaluate_next_step({"forecasting/forecast_generated": "done"}),
                )
                if r is not None
            ],
        ]
        messages = [m for group in scenarios for m in group]
        assert messages, "ожидались сработавшие правила"
        for message in messages:
            assert leftover.search(message) is None, message

    # -- fail-closed: шаблоны валидируются на импорте (§8 => все триггеры) --

    def test_broken_template_placeholder_is_import_error_fail_closed(self):
        """Битая подстановка в шаблоне (опечатка) -- ImportError на
        импорте реестра, не ValueError в рантайме (паттерн TRACE_ROUTES)."""
        broken = self._probe_rule("Битый шаблон {times")
        with pytest.raises(ImportError):
            mentor_rules.validate_explanation_template(broken)

    def test_every_registry_rule_has_renderable_template(self):
        """§8: рендер применим одинаково к §7.1 и §7.2 => шаблон обязателен
        для ВСЕХ триггеров (fail-closed ослабленное исключение для
        on_correction_result снято)."""
        for rule in (
            *mentor_rules.NEXT_STEP_RULES,
            *mentor_rules.SANITY_RULES,
            *mentor_rules.HISTORY_RULES,
        ):
            assert rule.explanation_template, rule.rule_id
            mentor_rules.validate_explanation_template(rule)  # не бросает

    def test_conditions_of_correction_rules_return_pre_render_fact(self):
        """Условия §7.2/истории возвращают факт срабатывания (контекст
        рендера), а не готовый текст: текст -- зона ответственности
        renderer (§8), факт -- зона правила."""
        fact = mentor_rules.rule_no_effect(
            _outcome(affected_count_before=5, changed_count=0)
        )
        assert fact is not None
        assert fact.severity == "warning"
        assert fact.suggested_action
        assert isinstance(fact.context, dict)
        assert mentor_rules.rule_no_effect(_outcome()) is None


# ── PROGR-15-B: текст фазы «Загрузки» -- из фактов решения, не статический шаблон ──
#
# Дефект (расследование PROGR-15-REPRO, причина Г-2, подтверждена
# тимлидом): PHASE_TEXT_TEMPLATES["upload"] -- жёсткая строка
# «подтвердите структуру данных и целевой признак», phase_text(stage)
# фактов не читает -- в сценарии тимлида Наставник требовал подтвердить
# УЖЕ подтверждённую структуру: факт upload/structure=done лежит в той
# же трассе, а summary того же ответа next-step показывает structure=done
# (JSON противоречит сам себе в одном payload).
#
# Контракт: phase_text(stage, statuses=None, events=None). Вызовы
# по-старому (без аргументов) -- дословно прежний шаблон; для upload
# текст ветвится по фактам решения: узел upload/structure -- из статусов
# единого движка (те же, что читает summary ответа), выбор целевого
# признака -- событие target_column_changed с НЕПУСТЫМ payload-колонкой
# (та же семантика, что у метаданных запуска research_runs: пустой --
# сброс, не выбор). Остальные стадии не обусловливаются: их описательные
# шаблоны фактам не противоречат. Фронт-контракт не меняется:
# phase_text в ответе next-step -- по-прежнему строка.


def _target_changed_event(run_id: str = "RUN-AAA00001", column: str = "value"):
    return make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id=run_id, target_column=column,
    )


class TestPhaseTextUploadFacts:
    def test_legacy_call_is_verbatim_static_template(self):
        """Обратная совместимость: вызов по-старому -- прежний текст."""
        assert phase_text("upload") == mentor_rules.PHASE_TEXT_TEMPLATES["upload"]
        assert phase_text("upload", None) == mentor_rules.PHASE_TEXT_TEMPLATES["upload"]

    def test_structure_done_silences_structure_request(self):
        text = phase_text("upload", {"upload/structure": "done"})
        assert "подтвердите структуру" not in text.lower()
        assert "подтверждена" in text

    def test_structure_not_done_keeps_requesting_structure(self):
        text = phase_text("upload", {"upload/structure": "warning"})
        assert "подтвердите структуру" in text.lower()

    def test_structure_done_without_target_fact_requests_target_only(self):
        text = phase_text("upload", {"upload/structure": "done"}, [])
        assert "подтвердите структуру" not in text.lower()
        assert "подтвердите" in text.lower()  # просьба осталась -- про цель
        assert "целевой признак" in text

    def test_target_fact_silences_all_requests_when_structure_done(self):
        text = phase_text("upload", {"upload/structure": "done"}, [_target_changed_event()])
        assert "подтвердите" not in text.lower()
        assert "подтверждена" in text

    def test_target_fact_without_structure_requests_structure_only(self):
        text = phase_text("upload", {}, [_target_changed_event()])
        assert "подтвердите структуру" in text.lower()
        assert "подтвердите целевой" not in text.lower()

    def test_empty_target_payload_is_reset_not_choice(self):
        """Семантика метаданных запуска (research_runs): пустой
        target_column в payload -- сброс выбора, фактом не является."""
        empty = _target_changed_event(run_id="RUN-BBB00002", column="")
        text = phase_text("upload", {"upload/structure": "done"}, [empty])
        assert "подтвердите" in text.lower()

    def test_junk_events_are_skipped_not_crash(self):
        """Мусор вместо событий -- пропуск (event_to_dict), не 500."""
        text = phase_text("upload", {"upload/structure": "done"}, ["мусор", 42, None])
        assert "подтверждена" in text

    def test_other_stages_condition_on_facts_not_static(self):
        """МИГРАЦИЯ КОНТРАКТА (PROGR-19, spec_progress_v1.1.md §3,
        категория C): в PROGR-15-B остальные стадии игнорировали
        статусы/события -- это признано дефектом (статический шаблон
        противоречил summary того же ответа next-step). Теперь каждая
        стадия обусловлена СВОИМИ фактами (реестр правил), а без фактов
        (пустые статусы/события) -- прежний статический шаблон.
        Чужие факты (upload-статусы) текст не меняют."""
        for stage in ("validation", "preprocessing", "eda", "modeling", "forecasting"):
            no_facts = phase_text(stage, {}, [])
            assert no_facts == phase_text(stage), stage
            own = {
                "validation": _fact_statuses(stage, done_ids=("data_types",)),
                "preprocessing": _fact_statuses(stage, done_ids=("missing",)),
                "eda": _fact_statuses(stage, done_ids=("correlation",)),
                "modeling": _fact_statuses(stage, done_ids=("backtest",)),
                "forecasting": _fact_statuses(stage, done_ids=("forecast_generated",)),
            }[stage]
            with_facts = phase_text(stage, own, [])
            assert with_facts != no_facts, stage
            # чужие (upload) статусы этой стадии не касаются
            alien = _fact_statuses("upload", done_ids=("structure",))
            assert phase_text(stage, alien) == no_facts, stage

    def test_unknown_stage_fallback_unchanged(self):
        assert phase_text("no-such-stage", {"upload/structure": "done"}) == phase_text("no-such-stage")


class TestMentorNextStepPhaseFacts:
    """PROGR-15-B, контур REST: phase_text ответа next-step обусловлен
    теми же фактами трассы запуска, что и summary того же ответа
    (structure=done в summary при просьбе «подтвердите структуру» в
    phase_text -- самопротиворечие одного JSON, закрыто)."""

    def test_structure_stop_fact_done_silences_request(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(
            store, "RUN-AAA00001",
            make_trace_event(
                "upload_stop_status", stage="upload", node_id="structure",
                run_id="RUN-AAA00001", status="done",
            ),
        )
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        data = response.json()
        assert data["last_active_stage"] == "upload"
        assert data["summary"]["stage"] == "upload"
        assert "подтвердите структуру" not in data["phase_text"].lower()

    def test_structure_confirmed_fact_silences_request(self, client: TestClient):
        """Второй источник того же факта: POST /date-column ->
        structure_confirmed (PROGR-13-A3), узел structure."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(
            store, "RUN-AAA00001",
            make_trace_event(
                "structure_confirmed", stage="upload", node_id="structure",
                run_id="RUN-AAA00001",
            ),
        )
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert "подтвердите структуру" not in data["phase_text"].lower()

    def test_target_fact_with_structure_silences_all_requests(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(
            store, "RUN-AAA00001",
            make_trace_event(
                "upload_stop_status", stage="upload", node_id="structure",
                run_id="RUN-AAA00001", status="done",
            ),
        )
        _seed_event(store, "RUN-AAA00001", _target_changed_event())
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert "подтвердите" not in data["phase_text"].lower()
        assert "подтверждена" in data["phase_text"]

    def test_run_without_facts_keeps_static_text(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["phase_text"] == mentor_rules.PHASE_TEXT_TEMPLATES["upload"]


# ── PROGR-19 (spec_progress_v1.1.md §3, категория C): текст фазы -- из декларативного реестра правил для ВСЕХ 6 стадий ──
#
# Корень (v1.1 §3): PROGR-15-B сделал phase_text факт-обусловленным
# только для upload (ручное if/elif); остальные пять стадий получали
# статический шаблон, противоречащий summary того же ответа next-step
# (то же «самопротиворечие одного JSON», не найденное вживую, потому
# что PROGR-15-REPRO тестировал именно Загрузку). Решение v1.1: не
# тиражировать if/elif пятью копиями, а обобщить контракт --
# декларативная таблица STAGE_PHASE_TEXT_RULES, первое совпавшее
# правило -- текст, ни одно -- статический PHASE_TEXT_TEMPLATES[stage]
# (обратная совместимость вызова без аргументов -- дословно). Условия
# читают уже посчитанный stage_node_summary (ноль нового I/O);
# upload-логика переносится в реестр как частный случай, не второй
# механизм. Минимальный набор v1.1 -- хотя бы один факт-обусловленный
# вариант на каждую стадию.

_PHASE_RULE_STAGES = ("validation", "preprocessing", "eda", "modeling", "forecasting")


def _fact_statuses(stage: str, done_ids, warn_ids=()) -> dict[str, str]:
    """Статусы узлов стадии из фактов (тот же вид, что у движка)."""
    from app.core.pipeline_graph import STAGE_NODES

    out: dict[str, str] = {}
    for node_id in STAGE_NODES[stage]:
        if node_id in done_ids:
            out[f"{stage}/{node_id}"] = "done"
        elif node_id in warn_ids:
            out[f"{stage}/{node_id}"] = "warning"
    return out


def _fact_event(stage: str, node_id: str, status: str = "done", run_id: str = "RUN-AAA00001"):
    """Узловой факт стадии как событие трассы: payload-статусы для
    проверочных стадий, карта EVENT_NODE_STATUS -- для процессных
    (modeling/forecasting), тот же вид, что сеют модули."""
    if stage == "upload":
        return make_trace_event(
            "upload_stop_status", stage=stage, node_id=node_id,
            run_id=run_id, status=status,
        )
    if stage == "modeling":
        event_type = {
            "backtest": "backtest_run",
            "tuning": "tuning_trial_completed",
            "selection": "model_selected",
            "model_card": "model_card_generated",
        }[node_id]
        return make_trace_event(
            event_type, stage=stage, node_id=node_id, run_id=run_id,
        )
    if stage == "forecasting":
        # id узла == тип события (§2: узлы Прогнозирования -- 4 типа
        # события ForecastRun).
        return make_trace_event(
            node_id, stage=stage, node_id=node_id, run_id=run_id,
        )
    return make_trace_event(
        f"{stage}_check_status", stage=stage, node_id=node_id,
        run_id=run_id, status=status,
    )


class TestStagePhaseTextRulesRegistry:
    def test_registry_covers_all_six_stages_in_graph_order(self):
        """Ключи реестра -- ровно стадии графа, в каноническом порядке
        (паттерн инварианта STAGE_NODES: рассинхрон невозможен тихо)."""
        from app.core.pipeline_graph import STAGES

        assert tuple(mentor_rules.STAGE_PHASE_TEXT_RULES.keys()) == STAGES

    def test_every_stage_has_at_least_one_rule(self):
        """Критерий приёмки v1.1: каждая стадия получает хотя бы один
        факт-обусловленный вариант (сейчас -- только upload)."""
        for stage in _PHASE_RULE_STAGES:
            assert mentor_rules.STAGE_PHASE_TEXT_RULES[stage], stage

    def test_rules_are_condition_plus_template(self):
        for stage, rules in mentor_rules.STAGE_PHASE_TEXT_RULES.items():
            for rule in rules:
                assert callable(rule.condition), stage
                assert isinstance(rule.template, str) and rule.template, stage

    def test_templates_render_from_summary_fields(self):
        """Шаблоны рендерятся из полей сводки стадии (те же, что уже в
        ответе next-step); поле nodes (список) в текст не подставляется."""
        stub = {
            "stage": "x", "total_nodes": 10, "done_count": 3,
            "warning_nodes": 1, "nodes": [{"node_id": "n", "status": "done"}],
        }
        for stage, rules in mentor_rules.STAGE_PHASE_TEXT_RULES.items():
            for rule in rules:
                text = rule.template.format(**stub)
                assert text.strip(), stage

    def test_validator_rejects_template_outside_summary_fields(self, monkeypatch):
        """Гейт полей шаблона -- несущая защита (мутант M-8): снятие гейта
        пропустило бы подстановку списка nodes (repr словарей) в
        человекочитаемый текст панели; валидатор обязан ловить это на
        импорте, а не рантайм ответа next-step."""
        bad = mentor_rules.PhaseTextRule(mentor_rules._some_done, "узлы: {nodes}")
        monkeypatch.setattr(
            mentor_rules, "STAGE_PHASE_TEXT_RULES",
            {**mentor_rules.STAGE_PHASE_TEXT_RULES, "validation": (bad,)},
        )
        with pytest.raises(ImportError):
            mentor_rules._validate_stage_phase_text_rules()

    def test_validator_rejects_signature_drift(self, monkeypatch):
        """Дрейф сигнатуры условий (condition без events) -- ImportError
        на импорте, не TypeError в рантайме ответа next-step."""
        broken = mentor_rules.PhaseTextRule(lambda summary: True, "текст")
        monkeypatch.setattr(
            mentor_rules, "STAGE_PHASE_TEXT_RULES",
            {**mentor_rules.STAGE_PHASE_TEXT_RULES, "eda": (broken,)},
        )
        with pytest.raises(ImportError):
            mentor_rules._validate_stage_phase_text_rules()

    def test_legacy_call_is_verbatim_static_for_all_six_stages(self):
        """Обратная совместимость дословно (то же требование, что
        PROGR-15-B): вызов без аргументов -- прежний статический шаблон."""
        for stage in mentor_rules.STAGE_PHASE_TEXT_RULES:
            assert phase_text(stage) == mentor_rules.PHASE_TEXT_TEMPLATES[stage], stage
            assert phase_text(stage, None) == mentor_rules.PHASE_TEXT_TEMPLATES[stage], stage


class TestPhaseTextFactsAllStages:
    def test_validation_done_with_problems(self):
        statuses = _fact_statuses(
            "validation", done_ids=("data_types", "formats", "ranges"),
            warn_ids=("consistency",),
        )
        text = phase_text("validation", statuses)
        assert "3 из 10" in text
        assert "найдены проблемы" in text

    def test_validation_done_without_problems(self):
        statuses = _fact_statuses("validation", done_ids=("data_types", "formats"))
        text = phase_text("validation", statuses)
        assert "2 из 10" in text
        assert "найдены проблемы" not in text

    def test_validation_without_facts_keeps_static_template(self):
        text = phase_text("validation", {})
        assert text == mentor_rules.PHASE_TEXT_TEMPLATES["validation"]

    def test_preprocessing_done_count(self):
        statuses = _fact_statuses(
            "preprocessing", done_ids=("missing", "outliers", "regularity", "smoothing"),
        )
        text = phase_text("preprocessing", statuses)
        assert "4 из 10" in text
        assert "обработано" in text

    def test_preprocessing_without_facts_keeps_static_template(self):
        assert phase_text("preprocessing", {}) == mentor_rules.PHASE_TEXT_TEMPLATES["preprocessing"]

    def test_eda_viewed_count(self):
        """Семантика EDA (решение тимлида PROGR-18): done -- «аналитик
        открыл и просмотрел результат», формулировка -- про ПРОСМОТР."""
        statuses = _fact_statuses("eda", done_ids=("correlation", "seasonality", "stationarity"))
        text = phase_text("eda", statuses)
        assert "3 из 10" in text
        assert "просмотрено" in text

    def test_eda_without_facts_keeps_static_template(self):
        assert phase_text("eda", {}) == mentor_rules.PHASE_TEXT_TEMPLATES["eda"]

    def test_modeling_backtest_ran(self):
        statuses = _fact_statuses("modeling", done_ids=("backtest", "selection"))
        text = phase_text("modeling", statuses)
        assert "бэктест" in text.lower()
        assert "2 из 11" in text

    def test_modeling_facts_without_backtest(self):
        statuses = _fact_statuses("modeling", done_ids=("selection",))
        text = phase_text("modeling", statuses)
        assert "не запускался" in text
        assert "бэктест" not in text.lower() or "backtest не запускался" in text

    def test_modeling_without_facts_keeps_static_template(self):
        assert phase_text("modeling", {}) == mentor_rules.PHASE_TEXT_TEMPLATES["modeling"]

    def test_forecasting_generated(self):
        statuses = _fact_statuses("forecasting", done_ids=("forecast_generated", "forecast_compared"))
        text = phase_text("forecasting", statuses)
        assert "прогноз построен" in text  # статический «построение» -- не дискриминатор
        assert "2 из 4" in text

    def test_forecasting_facts_without_generated(self):
        statuses = _fact_statuses("forecasting", done_ids=("forecast_compared",))
        text = phase_text("forecasting", statuses)
        assert "не строился" in text

    def test_forecasting_without_facts_keeps_static_template(self):
        assert phase_text("forecasting", {}) == mentor_rules.PHASE_TEXT_TEMPLATES["forecasting"]

    def test_first_matched_rule_wins(self):
        """Порядок приоритета: правило с проблемами впереди счётчика --
        при done>0 и warning>0 побеждает ПЕРВОЕ правило реестра."""
        statuses = _fact_statuses(
            "validation", done_ids=("data_types",), warn_ids=("ranges",),
        )
        text = phase_text("validation", statuses)
        assert "найдены проблемы" in text

    def test_upload_rules_behave_as_before_transfer(self):
        """Перенос upload-логики в реестр -- тот же контракт частного
        случая (TestPhaseTextUploadFacts покрывает подробно; здесь --
        привязка реестра к прежним текстам)."""
        assert phase_text("upload", {"upload/structure": "done"}) == (
            "Исследование на этапе «Загрузка»: структура данных подтверждена. "
            "Подтвердите целевой признак, чтобы пошли проверки качества."
        )
        assert phase_text(
            "upload", {"upload/structure": "done"}, [_target_changed_event()],
        ) == mentor_rules._UPLOAD_STRUCTURE_DONE_BOTH

    def test_cross_stage_facts_do_not_leak(self):
        """Статусы чужой стадии не меняют текст этой (сводка стадии
        читает только свои узлы; upload-правила -- только свои события)."""
        alien = _fact_statuses("validation", done_ids=("data_types", "formats"))
        assert phase_text("upload", alien) == mentor_rules.PHASE_TEXT_TEMPLATES["upload"]
        assert phase_text("eda", alien) == mentor_rules.PHASE_TEXT_TEMPLATES["eda"]

    def test_junk_events_do_not_crash_any_stage(self):
        """Мусор вместо событий -- пропуск (event_to_dict), не 500, для
        всех стадий и правил реестра."""
        for stage in mentor_rules.STAGE_PHASE_TEXT_RULES:
            text = phase_text(stage, {}, ["мусор", 42, None, {"event_type": 7}])
            assert text == mentor_rules.PHASE_TEXT_TEMPLATES[stage], stage

    def test_unknown_stage_fallback_unchanged(self):
        assert phase_text("no-such-stage", {"validation/data_types": "done"}) == phase_text("no-such-stage")


class TestMentorNextStepPhaseFactsAllStages:
    """PROGR-19, контур REST: phase_text ответа next-step обусловлен
    фактами трассы для всех стадий (не только upload); сводка summary
    того же ответа и текст фазы перестают противоречить друг другу."""

    def test_validation_check_facts_condition_phase_text(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(store, "RUN-AAA00001", _fact_event("validation", "data_types", "done"))
        _seed_event(store, "RUN-AAA00001", _fact_event("validation", "ranges", "warning"))
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["last_active_stage"] == "validation"
        assert data["summary"]["stage"] == "validation"
        assert "1 из 10" in data["phase_text"]
        assert "найдены проблемы" in data["phase_text"]

    def test_eda_viewed_facts_condition_phase_text(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(store, "RUN-AAA00001", _fact_event("eda", "correlation", "done"))
        _seed_event(store, "RUN-AAA00001", _fact_event("eda", "seasonality", "done"))
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["last_active_stage"] == "eda"
        assert "2 из 10" in data["phase_text"]
        assert "просмотрено" in data["phase_text"]

    def test_modeling_backtest_fact_conditions_phase_text(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(store, "RUN-AAA00001", _fact_event("modeling", "backtest"))
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["last_active_stage"] == "modeling"
        assert "бэктест" in data["phase_text"].lower()
        assert "1 из 11" in data["phase_text"]

    def test_forecasting_generated_fact_conditions_phase_text(self, client: TestClient):
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        _seed_event(store, "RUN-AAA00001", _fact_event("forecasting", "forecast_generated"))
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["last_active_stage"] == "forecasting"
        assert "прогноз построен" in data["phase_text"]

    def test_run_without_facts_keeps_static_text(self, client: TestClient):
        """Регресс: пустая трасса -- статические шаблоны на любой
        стадии (фаза без фактов не превращается в утверждение)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_run(store)
        data = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step").json()
        assert data["phase_text"] == mentor_rules.PHASE_TEXT_TEMPLATES["upload"]


# ── PROGR-24-ORIGIN-C: правило Наставника derived_spikes ─────────────
#
# spec_status_original_series.md, задача C: всплески на производных
# колонках (разности стационарности, сглаживание, флаги) -- не выбросы
# исходного ряда; гейты качества применяются один раз к каноническому
# ряду (задача A), а аналитику нужен СОВЕТ по терминологии §3.2 (не
# факт!) -- только по запросу, severity=info, с двумя методологически
# чистыми путями: (а) residual-based обнаружение на исходном ряду
# (остаток STL-декомпозиции в мастере «Выбросов»), (б) EDA «Структурные
# сдвиги» + интервенционная dummy-переменная (Box–Tiao). В трассу совет
# не попадает (разведение §3.2 дословно).
#
# Триггер on_demand_with_session -- четвёртый вид: правило требует
# фактов СЕССИИ (derived-область), а не одного preview-ответа и не
# истории трассы; данные приносит роутер (правила -- чистые функции,
# хранилища в движок не импортируются). Носитель факта -- та же
# каноническая функция профиля производных, что питает derived_summary
# задачи A (пересказ уже посчитанного, шкала карточки iqr-1.5). Канал
# показа -- history_warnings ответа next-step (панель Наставника --
# «по запросу»; контракт ответа не меняется, фронтенд рендерит как
# есть). В журнал наблюдений совет НЕ пишется (консистентно с
# history-предупреждениями; частота открытий панели не телеметрия
# решений).


def _derived_facts(total_outliers: int) -> dict[str, Any]:
    return {
        "total_outliers": total_outliers,
        "total_columns": 1,
        "total_numeric_columns": 1,
        "affected_columns": ["value_detrended"],
    }


class TestDerivedSpikesSessionAdvice:
    def test_fires_on_derived_spikes_with_info_severity(self):
        fact = mentor_rules.rule_derived_spikes(_derived_facts(4))
        assert fact is not None
        assert fact.severity == "info", "совет по терминологии, не тревога"
        assert fact.suggested_action is None, "«как решать», а не «куда идти»"
        assert fact.context["total_outliers"] == 4

    def test_silent_on_zero_spikes(self):
        assert mentor_rules.rule_derived_spikes(_derived_facts(0)) is None

    def test_silent_on_garbage_facts(self):
        """Мусор/чужие типы -- пропуск (деградация «совета нет»), не 500."""
        for facts in (None, {}, {"total_outliers": "4"},
                      {"total_outliers": True}, {"total_outliers": -3},
                      {"total_outliers": 2.5}, {"total_outliers": None}):
            assert mentor_rules.rule_derived_spikes(facts) is None, facts

    def test_rule_registered_in_session_advice_registry(self):
        rule = {r.rule_id: r for r in mentor_rules.SESSION_ADVICE_RULES}
        assert "derived_spikes" in rule
        derived = rule["derived_spikes"]
        assert derived.trigger == mentor_rules.TRIGGER_ON_DEMAND_WITH_SESSION
        assert derived.stage == "preprocessing"
        assert derived.recommended_action is None

    def test_new_trigger_is_known(self):
        assert mentor_rules.TRIGGER_ON_DEMAND_WITH_SESSION in mentor_rules.KNOWN_TRIGGERS

    def test_template_carries_both_spec_paths(self):
        """Два пути спеки дословно в шаблоне: (а) STL-остаток на исходном
        ряду в мастере «Выбросов», (б) EDA «Структурные сдвиги» +
        интервенционная dummy Box–Tiao."""
        template = next(
            r.explanation_template
            for r in mentor_rules.SESSION_ADVICE_RULES
            if r.rule_id == "derived_spikes"
        )
        assert "STL" in template
        assert "«Выбросы»" in template
        assert "«Структурные сдвиги»" in template
        assert "Box–Tiao" in template
        assert "{total_outliers}" in template

    def test_evaluate_session_advice_none_facts_empty_list(self):
        assert mentor_rules.evaluate_session_advice(None) == []

    def test_evaluate_session_advice_renders_message_with_count(self):
        warnings = mentor_rules.evaluate_session_advice(_derived_facts(4))
        assert len(warnings) == 1
        assert warnings[0].rule_id == "derived_spikes"
        assert warnings[0].severity == "info"
        assert "4" in warnings[0].message

    def test_evaluate_session_advice_renderer_called_only_when_fired(self):
        """§8: renderer не вызывается, если правило не сработало."""
        calls: list[tuple[str, dict]] = []

        class _Spy:
            def render(self, rule, context):
                calls.append((rule.rule_id, dict(context)))
                return "рендер"

        assert mentor_rules.evaluate_session_advice(_derived_facts(0), renderer=_Spy()) == []
        assert calls == []
        assert mentor_rules.evaluate_session_advice(_derived_facts(2), renderer=_Spy())[0].message == "рендер"
        assert calls and calls[0][0] == "derived_spikes"

    def test_session_advice_rules_covered_by_import_validation(self):
        """Fail-closed самопроверка импорта покрывает четвёртый реестр
        (шаблон обязателен для ВСЕХ триггеров)."""
        for rule in mentor_rules.SESSION_ADVICE_RULES:
            assert rule.explanation_template
            mentor_rules.validate_explanation_template(rule)  # не бросает


# ── e2e: derived_spikes в ответе next-step ────────────────────────────

def _g345_like_frame() -> Any:
    """Детерминированный кадр класса C5 (тренд + сезон M=12, 4 выброса,
    3 пропуска): после стационарности производная колонка несёт всплески
    на позициях скачков -- тот же сценарий PROGR-22-REPRO."""
    import numpy as np
    import pandas as pd

    t = np.arange(150, dtype=float)
    value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    value[25] += 110
    value[70] += 105
    value[105] += 95
    value[130] -= 135
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )
    frame.loc[[45, 87, 122], "value"] = np.nan
    return frame


def _clean_frame() -> Any:
    """Ряд без выбросов и пропусков: плавный тренд + мягкая сезонность --
    первая разность гладкая и ограниченная (без скачков), IQR-заборы
    никого не флагают: производная есть, всплесков нет. (Строго
    константный ряд не годится: вырожденная нулевая дисперсия даёт NaN
    в статистиках профиля стационарности -- платформа честно не может
    посчитать acf константы.)"""
    import numpy as np
    import pandas as pd

    t = np.arange(150, dtype=float)
    value = 100 + 0.5 * t + 5 * np.sin(2.0 * np.pi * t / 12.0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )


def _upload_frame(client_: TestClient, frame: Any) -> None:
    import io

    response = client_.post(
        "/v1/internal/upload",
        files={"file": ("frame.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _stationarity_apply(client_: TestClient, column: str = "value") -> None:
    """Честный UI-поток: остановка «Пропуски» (гейт стационарности),
    затем preview → apply стационарности (кнопка disabled без preview)."""
    missing = client_.get("/v1/session/dataset/missing-profile").json()
    cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
    if cols:
        response = client_.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        assert response.status_code == 200, response.text
    profile = client_.get(
        f"/v1/session/dataset/preprocessing/stationarity-profile?column={column}"
    ).json()
    method = profile["profile"].get("selected_method") or "first_difference"
    response = client_.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        json={"column": column, "method": method, "apply": True, "confirm_non_causal": True},
    )
    assert response.status_code == 200, response.text


def _seed_run_with_session(client_: TestClient, run_id: str = "RUN-AAA00001") -> None:
    """Запуск слоя 2, связанный с РЕАЛЬНОЙ cookie-сессией клиента
    (run.session_id -- последний известный, research_runs)."""
    from apps.api import research_runs
    from apps.api.session_store import SESSION_COOKIE_NAME

    session_id = client_.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    research_runs.get_research_run_store().upsert_run(
        research_runs.ResearchRun(
            run_id=run_id,
            session_id=session_id,
            dataset_fingerprint="f" * 64,
            dataset_name="frame.csv",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
        )
    )


class TestMentorDerivedSpikesEndpoint:
    def test_derived_spikes_warning_in_next_step_response(self, client: TestClient):
        """Полный поток: загрузка → стационарность (производная колонка со
        всплесками) → next-step содержит совет derived_spikes (info), и
        число всплесков в совете -- то же, что derived_summary профиля
        (та же каноническая функция, шкала карточки)."""
        _upload_frame(client, _g345_like_frame())
        _stationarity_apply(client)
        _seed_run_with_session(client)

        profile = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
        derived_total = (profile.get("derived_summary") or {}).get("total_outliers")
        assert derived_total and derived_total > 0, "в производной колонке должны быть всплески"

        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        warnings = {
            w["rule_id"]: w for w in response.json()["history_warnings"]
        }
        assert "derived_spikes" in warnings
        advice = warnings["derived_spikes"]
        assert advice["severity"] == "info"
        assert advice["suggested_action"] is None
        assert str(derived_total) in advice["message"], advice["message"]

    def test_silent_without_derived_columns(self, client: TestClient):
        """Датасет без применений -- производных нет, совета нет
        (Наставник не объясняет то, чего нет)."""
        _upload_frame(client, _g345_like_frame())
        _seed_run_with_session(client)
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        rule_ids = [w["rule_id"] for w in response.json()["history_warnings"]]
        assert "derived_spikes" not in rule_ids

    def test_silent_when_derived_columns_have_no_spikes(self, client: TestClient):
        """Производные есть, всплесков нет (константная разность
        линейного тренда) -- совет не срабатывает: ноль нового шума."""
        _upload_frame(client, _clean_frame())
        _stationarity_apply(client)
        _seed_run_with_session(client)
        from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session is not None and session.derived_columns, "производная должна быть зарегистрирована"
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        rule_ids = [w["rule_id"] for w in response.json()["history_warnings"]]
        assert "derived_spikes" not in rule_ids

    def test_silent_when_session_of_run_is_gone(self, client: TestClient):
        """run.session_id указывает на несуществующую сессию (истёкшая
        cookie, другой слой) -- best-effort деградация: ответ валиден,
        совета нет, НЕ 500."""
        from apps.api import research_runs

        _upload_frame(client, _g345_like_frame())
        _stationarity_apply(client)
        store = research_runs.get_research_run_store()
        store.upsert_run(
            research_runs.ResearchRun(
                run_id="RUN-AAA00001",
                session_id="ghost-session",
                dataset_fingerprint="f" * 64,
                dataset_name="frame.csv",
                created_at=_now_iso(),
                last_active_at=_now_iso(),
            )
        )
        response = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert response.status_code == 200
        rule_ids = [w["rule_id"] for w in response.json()["history_warnings"]]
        assert "derived_spikes" not in rule_ids


class TestDerivedSpikesFactsScope:
    def test_facts_scoped_to_derived_area_only(self):
        """Носитель факта -- ПРОИЗВОДНАЯ область (задача A): всплески
        канонического ряда НЕ должны попадать в facts (иначе Наставник
        советовал бы терминологию производных про обычные выбросы
        исходного ряда). Каноническая колонка со всплесками + чистая
        производная -- факты молчат (total_outliers == 0)."""
        import numpy as np
        import pandas as pd

        from apps.api.column_origin import register_derived_columns
        from apps.api.routers.progress import _derived_spikes_facts
        from apps.api.session_store import (
            AnalysisSession,
            DatasetInfo,
            get_session_store,
        )

        t = np.arange(150, dtype=float)
        value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
        value[[25, 70, 105, 130]] += [110, 105, 95, -135]  # всплески КАНОНА
        clean = 5 * np.sin(2.0 * np.pi * t / 12.0)  # гладкая производная
        df = pd.DataFrame({"value": np.round(value, 2), "clean": np.round(clean, 2)})

        session = AnalysisSession(session_id="scope-probe")
        session.set_dataset(
            DatasetInfo(
                dataset_id="d1",
                name="frame.csv",
                rows=len(df),
                columns=2,
                size_label="1 КБ",
                dataset_fingerprint="f" * 64,
            ),
            df,
        )
        register_derived_columns(
            session, before_columns=["value"], stage="stationarity", source="probe"
        )
        get_session_store().save(session)

        from apps.api import research_runs

        run = research_runs.ResearchRun(
            run_id="RUN-SCOPE001", session_id="scope-probe"
        )
        facts = _derived_spikes_facts(run)
        assert facts is not None, "производная область есть -- факты обязаны прийти"
        assert facts["total_outliers"] == 0, (
            "всплески канонического ряда не должны попадать в совет "
            "о производных (скоуп задачи A)"
        )
