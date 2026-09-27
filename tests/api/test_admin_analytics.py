# tests/api/test_admin_analytics.py
"""Тесты Task PROGR-8 (plan_progress.md): движок агрегатов Admin-панели
(spec_progress.md §10) и офлайн-потребителей (§9, категория D).

Движок -- app/core/admin_analytics.py, ЧИСТЫЙ модуль без HTTP (паттерн
run_report.py PROGR-7): принимает словари канонических форм
(ResearchRun.to_dict / TraceEvent.to_dict / MentorObservation.to_dict),
возвращает модели агрегатов.

Контур тестов -- СОБСТВЕННЫЕ данные (не копии коллегиальных фикстур):

  1. Запуски по статусам за период (§10 «за период») + all-time;
     нечитаемый created_at -- в all-time, вне периода (честность).
  2. Распределение времени по стадиям (§10 «где застревают»):
     span first->last ts стадии внутри запуска; стадия измерима при
     >= 2 читаемых событиях; нечитаемые ts пропускаются; сортировка
     по убыванию среднего.
  3. Топ узлов warning/error (§10): статусы выводятся
     derive_node_statuses (зеркало PROGR-6); фантомных узлов нет.
  4. Частота правил §7.1 (наблюдения next_step) и §7.2 по правилу
     и по узлу (наблюдения sanity_warning) -- §10 дословно;
     наблюдение без node_id учитывается по правилу, но не по узлу.
  5. Прогнозирование (§9: spec_forecasting2 §9.3 п.5): частоты
     model_id/horizon/alpha из payload forecast_generated.
  6. Банк кейсов (§9): алгоритмическая эвристика -- completed +
     финальный бэктест-скор + малое число warning-узлов + малое число
     sanity-предупреждений; «последний backtest_run -- финальный»;
     без доказательства скора кандидат не отбирается (no fabricated
     evidence); сортировка по mape asc.
  7. Пустой корпус -- честные нули (приёмка плана: «не гейтится
     кодом»); агрегаты детерминированы (инъекция now).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.admin_analytics import (
    AdminOverviewModel,
    build_admin_overview,
    select_case_bank_candidates,
)

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: float = 0.0, minutes: float = 0.0) -> str:
    """Момент «days_ago суток назад + minutes минут» (minutes сдвигает
    ВПЕРЁД относительно базовой точки)."""
    return (NOW - timedelta(days=days_ago) + timedelta(minutes=minutes)).isoformat()


def _run(
    run_id: str,
    *,
    status: str = "active",
    created_days_ago: float = 5.0,
    dataset_name: str = "prices.csv",
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "session_id": "sess-" + run_id.lower(),
        "dataset_fingerprint": "fp-" + run_id.lower(),
        "dataset_name": dataset_name,
        "target_column": "Price",
        "created_at": created_at
        if created_at is not None
        else _iso(created_days_ago),
        "last_active_at": _iso(max(created_days_ago - 1.0, 0.0)),
        "status": status,
    }


def _event(
    event_type: str,
    *,
    run_id: str,
    stage: str = "upload",
    node_id: str | None = "structure_confirmed",
    ts: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"ev-{run_id}-{event_type}-{len(str(payload or {}))}",
        "run_id": run_id,
        "ts": ts or _iso(5.0),
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": "user",
        "timestamp": ts or _iso(5.0),
    }


def _observation(
    obs_kind: str,
    rule_id: str,
    *,
    run_id: str = "RUN-A",
    stage: str = "preprocessing",
    node_id: str | None = "missing",
    severity: str = "warning",
    ts: str | None = None,
) -> dict[str, Any]:
    return {
        "obs_id": f"obs-{obs_kind}-{rule_id}-{node_id}-{len(ts or '')}",
        "run_id": run_id,
        "ts": ts or _iso(1.0),
        "obs_kind": obs_kind,
        "rule_id": rule_id,
        "stage": stage,
        "node_id": node_id,
        "severity": severity,
    }


# ── 1. Запуски по статусам за период ─────────────────────────────────


class TestRunsByStatus:
    def test_counts_statuses_within_period_only(self):
        runs = [
            _run("RUN-A", status="completed", created_days_ago=5),
            _run("RUN-B", status="active", created_days_ago=10),
            _run("RUN-C", status="paused", created_days_ago=40),   # вне 30 дней
            _run("RUN-D", status="abandoned", created_days_ago=1),
        ]
        model = build_admin_overview(
            runs, {}, [], now=NOW, period_days=30
        )
        assert model.runs_total_in_period == 3
        assert model.runs_by_status["completed"] == 1
        assert model.runs_by_status["active"] == 1
        assert model.runs_by_status["paused"] == 0  # вне периода
        assert model.runs_by_status["abandoned"] == 1
        assert model.runs_total_all_time == 4
        assert model.period_days == 30

    def test_unparseable_created_at_counts_all_time_only(self):
        runs = [
            _run("RUN-A", status="active", created_at=""),
            _run("RUN-B", status="active", created_at="не-дата"),
            _run("RUN-C", status="completed", created_days_ago=2),
        ]
        model = build_admin_overview(runs, {}, [], now=NOW, period_days=30)
        assert model.runs_total_all_time == 3
        assert model.runs_total_in_period == 1
        assert model.runs_by_status["active"] == 0
        assert model.runs_by_status["completed"] == 1

    def test_period_window_boundary_inclusive(self):
        # Запуск ровно на границе окна (now - 30 дней) -- ВНУТРИ периода.
        runs = [_run("RUN-A", status="active", created_at=_iso(30.0))]
        model = build_admin_overview(runs, {}, [], now=NOW, period_days=30)
        assert model.runs_total_in_period == 1


# ── 2. Время по стадиям ──────────────────────────────────────────────


class TestStageTime:
    def test_span_first_to_last_per_run_and_stage(self):
        events = [
            # RUN-A: upload -- два события с разницей 10 мин;
            # preprocessing -- два события с разницей 40 мин.
            _event("upload_completed", run_id="RUN-A", ts=_iso(5.0)),
            _event(
                "mode_changed", run_id="RUN-A", stage="upload",
                node_id=None, ts=_iso(5.0, minutes=10),
            ),
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0),
            ),
            _event(
                "correction_applied", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0, minutes=40),
            ),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        by_stage = {item.stage: item for item in model.stage_time}
        assert by_stage["upload"].runs_with_stage == 1
        assert by_stage["upload"].mean_minutes == pytest.approx(10.0)
        assert by_stage["preprocessing"].mean_minutes == pytest.approx(40.0)
        assert by_stage["preprocessing"].median_minutes == pytest.approx(40.0)

    def test_aggregates_mean_and_median_across_runs(self):
        events_a = [
            _event("upload_completed", run_id="RUN-A", ts=_iso(5.0)),
            _event(
                "mode_changed", run_id="RUN-A", stage="upload",
                node_id=None, ts=_iso(5.0, minutes=10),
            ),
        ]
        events_b = [
            _event("upload_completed", run_id="RUN-B", ts=_iso(2.0)),
            _event(
                "mode_changed", run_id="RUN-B", stage="upload",
                node_id=None, ts=_iso(2.0, minutes=30),
            ),
        ]
        runs = [_run("RUN-A", status="completed"), _run("RUN-B", status="active")]
        model = build_admin_overview(
            runs, {"RUN-A": events_a, "RUN-B": events_b}, [], now=NOW
        )
        upload = next(item for item in model.stage_time if item.stage == "upload")
        assert upload.runs_with_stage == 2
        assert upload.mean_minutes == pytest.approx(20.0)
        assert upload.median_minutes == pytest.approx(20.0)

    def test_stage_with_single_event_is_not_measurable(self):
        events = [
            _event("upload_completed", run_id="RUN-A", ts=_iso(5.0)),
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0),
            ),
            _event(
                "correction_applied", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0),  # тот же ts: span 0
            ),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        # Upload -- 1 событие: span неизмерим, стадии нет в распределении;
        # preprocessing -- 2 события с span 0: измерима, время 0.
        stages = {item.stage for item in model.stage_time}
        assert "upload" not in stages
        prep = next(item for item in model.stage_time if item.stage == "preprocessing")
        assert prep.mean_minutes == 0.0

    def test_unreadable_ts_skipped_degradation(self):
        events = [
            _event("upload_completed", run_id="RUN-A", ts=_iso(5.0)),
            _event(
                "mode_changed", run_id="RUN-A", stage="upload",
                node_id=None, ts="битый-ts",
            ),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        # Нечитаемое событие пропущено: остался один читаемый -- неизмеримо.
        assert model.stage_time == []

    def test_sorted_by_mean_descending(self):
        events_a = [
            _event("upload_completed", run_id="RUN-A", ts=_iso(5.0)),
            _event(
                "mode_changed", run_id="RUN-A", stage="upload",
                node_id=None, ts=_iso(4.0),
            ),  # span 1440 мин
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(3.0),
            ),
            _event(
                "correction_applied", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(3.0, minutes=30),
            ),  # span 30 мин
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events_a}, [], now=NOW
        )
        assert [item.stage for item in model.stage_time] == [
            "upload", "preprocessing",
        ]


# ── 3. Топ проблемных узлов ──────────────────────────────────────────


class TestTopProblemNodes:
    def test_counts_warning_nodes_across_runs(self):
        events_a = [
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0),
            ),
        ]
        events_b = [
            _event(
                "correction_previewed", run_id="RUN-B", stage="preprocessing",
                node_id="missing", ts=_iso(2.0),
            ),
        ]
        runs = [_run("RUN-A"), _run("RUN-B")]
        model = build_admin_overview(
            runs, {"RUN-A": events_a, "RUN-B": events_b}, [], now=NOW
        )
        assert len(model.top_problem_nodes) == 1
        node = model.top_problem_nodes[0]
        assert (node.stage, node.node_id, node.status, node.count) == (
            "preprocessing", "missing", "warning", 2,
        )

    def test_done_nodes_not_counted_and_fantoms_skipped(self):
        events = [
            # previewed -> applied: финальный статус done -- не проблема.
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0),
            ),
            _event(
                "correction_applied", run_id="RUN-A", stage="preprocessing",
                node_id="missing", ts=_iso(4.0 - 1.0 / 1440.0),
            ),
            # Фантомный узел (нет в графе §2) -- честно пропущен.
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id="unknown_node", ts=_iso(4.0),
            ),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        assert model.top_problem_nodes == []

    def test_top_limit_applied(self):
        events = [
            _event(
                "correction_previewed", run_id="RUN-A", stage="preprocessing",
                node_id=node, ts=_iso(4.0),
            )
            for node in ("missing", "outliers", "regularity")
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [],
            now=NOW, top_limit=2,
        )
        assert len(model.top_problem_nodes) == 2


# ── 4. Частоты правил Наставника (§7.1/§7.2 -> §10) ──────────────────


class TestMentorFrequencies:
    def test_next_step_frequency_from_observations(self):
        observations = [
            _observation("next_step", "preprocessing_missing_attention",
                         node_id=None, severity=""),
            _observation("next_step", "preprocessing_missing_attention",
                         node_id=None, severity="", ts=_iso(2.0)),
            _observation("next_step", "forecast_not_compared_before_export",
                         run_id="RUN-B", stage="forecasting",
                         node_id=None, severity=""),
        ]
        model = build_admin_overview([_run("RUN-A")], {}, observations, now=NOW)
        assert [item.rule_id for item in model.next_step_frequency] == [
            "preprocessing_missing_attention",
            "forecast_not_compared_before_export",
        ]
        assert model.next_step_frequency[0].count == 2
        assert model.next_step_frequency[0].stage == "preprocessing"

    def test_sanity_by_rule_and_by_node(self):
        observations = [
            _observation("sanity_warning", "no_effect",
                         stage="preprocessing", node_id="missing"),
            _observation("sanity_warning", "no_effect",
                         stage="preprocessing", node_id="outliers"),
            _observation("sanity_warning", "over_aggressive",
                         stage="preprocessing", node_id="smoothing"),
            _observation("sanity_warning", "excessive_data_loss",
                         stage="preprocessing", node_id=None),
        ]
        model = build_admin_overview([_run("RUN-A")], {}, observations, now=NOW)
        by_rule = {item.rule_id: item.count for item in model.sanity_by_rule}
        assert by_rule == {
            "no_effect": 2,
            "over_aggressive": 1,
            "excessive_data_loss": 1,
        }
        by_node = {(item.stage, item.node_id): item.count
                   for item in model.sanity_by_node}
        assert by_node == {
            ("preprocessing", "missing"): 1,
            ("preprocessing", "outliers"): 1,
            ("preprocessing", "smoothing"): 1,
            # Наблюдение без node_id не атрибутируется узлу честно.
        }

    def test_unknown_observation_kind_ignored(self):
        observations = [_observation("telemetry", "whatever")]
        model = build_admin_overview([_run("RUN-A")], {}, observations, now=NOW)
        assert model.next_step_frequency == []
        assert model.sanity_by_rule == []
        assert model.sanity_by_node == []


# ── 5. Прогнозирование: предпочтения (§9, spec_forecasting2 §9.3 п.5) ─


class TestForecastingPreferences:
    def test_model_horizon_alpha_frequencies(self):
        events = [
            _event("forecast_generated", run_id="RUN-A", stage="forecasting",
                   node_id=None, ts=_iso(3.0),
                   payload={"model_id": "naive", "horizon": 7, "alpha": 0.1}),
            _event("forecast_generated", run_id="RUN-A", stage="forecasting",
                   node_id=None, ts=_iso(2.0),
                   payload={"model_id": "ets", "horizon": 7, "alpha": 0.05}),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        assert {item.value: item.count
                for item in model.forecasting_model_frequency} == {
            "naive": 1, "ets": 1,
        }
        assert model.forecasting_horizon_frequency[0].value == "7"
        assert model.forecasting_horizon_frequency[0].count == 2
        assert [item.value for item in model.forecasting_alpha_frequency] == [
            "0.05", "0.1",
        ]

    def test_missing_payload_values_skipped(self):
        events = [
            _event("forecast_generated", run_id="RUN-A", stage="forecasting",
                   node_id=None, payload={"forecast_id": "F1"}),
        ]
        model = build_admin_overview(
            [_run("RUN-A", status="completed")], {"RUN-A": events}, [], now=NOW
        )
        assert model.forecasting_model_frequency == []
        assert model.forecasting_horizon_frequency == []
        assert model.forecasting_alpha_frequency == []


# ── 6. Банк кейсов (§9, алгоритмическая эвристика) ───────────────────


class TestCaseBankCandidates:
    def _run_with_backtest(
        self,
        run_id: str,
        mape: float | None,
        *,
        status: str = "completed",
        extra_events: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payload = {"model_id": "ets", "n_train": 100, "n_test": 20}
        if mape is not None:
            payload["metrics"] = {"mape": mape}
        # Паттерн хука: dotted "metrics.mape" попадает в payload плоским
        # ключом "mape" (корпус хранит факты плоскими ключами §4.1).
        stored = dict(payload)
        if mape is not None:
            stored["mape"] = mape
        events = [
            _event("backtest_run", run_id=run_id, stage="modeling",
                   node_id="backtest", ts=_iso(2.0), payload=stored),
            *(extra_events or []),
        ]
        return _run(run_id, status=status), events

    def test_clean_completed_run_is_candidate(self):
        run, events = self._run_with_backtest("RUN-A", 12.5)
        model = select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_backtest_mape=30.0,
        )
        assert len(model) == 1
        candidate = model[0]
        assert candidate.run_id == "RUN-A"
        assert candidate.backtest_mape == pytest.approx(12.5)
        assert candidate.warning_nodes == 0
        assert candidate.sanity_warnings == 0
        assert candidate.status == "completed"

    def test_mape_above_threshold_excluded(self):
        run, events = self._run_with_backtest("RUN-A", 45.0)
        assert select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_backtest_mape=30.0,
        ) == []

    def test_without_score_evidence_excluded(self):
        # Финальный бэктест без mape в payload -- нет доказательства
        # качества: кандидат не отбирается (no fabricated evidence).
        run, events = self._run_with_backtest("RUN-A", None)
        assert select_case_bank_candidates([run], {"RUN-A": events}, []) == []

    def test_last_backtest_is_final(self):
        # Два бэктеста: финальный -- ПОСЛЕДНИЙ; его скор и оценивается.
        run = _run("RUN-A", status="completed")
        events = [
            _event("backtest_run", run_id="RUN-A", stage="modeling",
                   node_id="backtest", ts=_iso(3.0),
                   payload={"model_id": "naive", "mape": 5.0}),
            _event("backtest_run", run_id="RUN-A", stage="modeling",
                   node_id="backtest", ts=_iso(2.0),
                   payload={"model_id": "ets", "mape": 25.0}),
        ]
        candidates = select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_backtest_mape=10.0,
        )
        # Финальный mape 25 > 10 -- исключён, несмотря на ранний 5.0.
        assert candidates == []

    def test_not_completed_excluded(self):
        run, events = self._run_with_backtest("RUN-A", 12.5, status="active")
        assert select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_backtest_mape=30.0,
        ) == []

    def test_too_many_warning_nodes_excluded(self):
        run, events = self._run_with_backtest(
            "RUN-A", 12.5,
            extra_events=[
                _event("correction_previewed", run_id="RUN-A",
                       stage="preprocessing", node_id=node, ts=_iso(3.0))
                for node in ("missing", "outliers", "regularity")
            ],
        )
        assert select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_warning_nodes=2,
        ) == []

    def test_boundary_warning_nodes_included(self):
        run, events = self._run_with_backtest(
            "RUN-A", 12.5,
            extra_events=[
                _event("correction_previewed", run_id="RUN-A",
                       stage="preprocessing", node_id="missing", ts=_iso(3.0)),
            ],
        )
        candidates = select_case_bank_candidates(
            [run], {"RUN-A": events}, [], max_warning_nodes=1,
        )
        assert len(candidates) == 1
        assert candidates[0].warning_nodes == 1

    def test_too_many_sanity_warnings_excluded(self):
        run, events = self._run_with_backtest("RUN-A", 12.5)
        observations = [
            _observation("sanity_warning", "no_effect", run_id="RUN-A",
                         node_id="missing", ts=_iso(3.0)),
            _observation("sanity_warning", "over_aggressive", run_id="RUN-A",
                         node_id="missing", ts=_iso(2.5)),
            _observation("sanity_warning", "excessive_data_loss",
                         run_id="RUN-A", node_id="missing", ts=_iso(2.0)),
        ]
        assert select_case_bank_candidates(
            [run], {"RUN-A": events}, observations, max_sanity_warnings=2,
        ) == []

    def test_sorted_by_mape_ascending(self):
        run_a, events_a = self._run_with_backtest("RUN-B", 20.0)
        run_b, events_b = self._run_with_backtest("RUN-A", 10.0)
        candidates = select_case_bank_candidates(
            [run_a, run_b], {"RUN-B": events_a, "RUN-A": events_b}, [],
            max_backtest_mape=30.0,
        )
        assert [item.run_id for item in candidates] == ["RUN-A", "RUN-B"]

    def test_unparseable_mape_is_not_evidence(self):
        run = _run("RUN-A", status="completed")
        events = [
            _event("backtest_run", run_id="RUN-A", stage="modeling",
                   node_id="backtest", ts=_iso(2.0),
                   payload={"model_id": "ets", "mape": "не-число"}),
        ]
        assert select_case_bank_candidates([run], {"RUN-A": events}, []) == []


# ── 7. Пустой корпус и контракт модели ───────────────────────────────


class TestEmptyCorpusAndContract:
    def test_empty_corpus_honest_zeros(self):
        model = build_admin_overview([], {}, [], now=NOW)
        assert isinstance(model, AdminOverviewModel)
        assert model.runs_total_all_time == 0
        assert model.runs_total_in_period == 0
        assert model.runs_by_status == {
            "active": 0, "paused": 0, "completed": 0, "abandoned": 0,
        }
        assert model.stage_time == []
        assert model.top_problem_nodes == []
        assert model.next_step_frequency == []
        assert model.sanity_by_rule == []
        assert model.sanity_by_node == []
        assert model.forecasting_model_frequency == []
        assert model.forecasting_horizon_frequency == []
        assert model.forecasting_alpha_frequency == []
        assert model.generated_at == NOW.isoformat()

    def test_events_of_unknown_runs_ignored(self):
        # События без запуска в runs не агрегируются по узлам (корпус
        # задаётся списком запусков) -- честная деградация, не падение.
        events = {
            "RUN-GHOST": [
                _event("correction_previewed", run_id="RUN-GHOST",
                       stage="preprocessing", node_id="missing", ts=_iso(1.0)),
            ],
        }
        model = build_admin_overview([], events, [], now=NOW)
        assert model.top_problem_nodes == []
