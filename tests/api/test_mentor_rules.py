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
