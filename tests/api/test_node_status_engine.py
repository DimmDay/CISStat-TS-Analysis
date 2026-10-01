# tests/api/test_node_status_engine.py
"""Тесты Task PROGR-10 (Расхождение №1): единый движок статусов узлов
из фактов решений -- app/core/node_status.py (spec_progress.md §4.1).

Один движок -- три потребителя (панель §6.2, Наставник §7.1,
admin-аналитика §10); до PROGR-10 движков было два (бэкенд-зеркало в
mentor_rules + фронтенд-порт progress.ts) плюс зеркало forecasting-узла
в run_report. Решение расхождения: живой опрос profile-эндпоинтов
(§3/§4.2 progress_ts_analysis.md) НЕ реализуется -- статус с точностью
до последнего засеянного события (цена принята тимлидом).

Контуры:

  1. EVENT_NODE_STATUS: каноническая карта 12 узловых типов §4.1
     (перенос дословно) и семантика статусов; каждый тип карты реально
     испускается реестром STAGE_EVENT_TYPES (карта не шире фактов).
  2. event_to_dict: публичная нормализация (бывший приватный
     _event_dict) на объекте/dict/мусоре.
  3. resolve_node_id: явный node_id приоритетен; forecasting-вывод из
     типа (контракт PROGR-1); вне правил -- None (N-2).
  4. derive_node_statuses: last-event-wins, N-2, forecasting-вывод,
     фантомы, смешанные представления, коллизия regularity.
  5. derive_stage_states: пусто/порядок §2/тоталы, warning->attention
     при done-большинстве (§12 п.10), running->attention, счётчики =
     деривация.
  6. Владение: копий движка больше нет (mentor_rules/progress.ts/
     run_report) -- расползание ловится тестом, а не код-ревью.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core import node_status
from app.core.node_status import (
    EVENT_NODE_STATUS,
    derive_node_statuses,
    derive_stage_states,
    event_to_dict,
    resolve_node_id,
)
from apps.api.trace_events import STAGE_EVENT_TYPES, make_trace_event

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _ts(seconds: int) -> str:
    """Детерминированный ts-литерал (хронология входа задаётся порядком
    списка, литералы -- для читаемости корпуса)."""
    return f"2026-09-29T10:{seconds // 60:02d}:{seconds % 60:02d}+00:00"


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str = "2026-09-29T10:00:00+00:00",
    **payload,
) -> dict:
    """Словарь канона §4.1 (минимальный корпус движка)."""
    return {
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": payload,
    }


# ── Контур 1: каноническая карта §4.1 ────────────────────────────────


class TestEventNodeStatusMap:
    def test_map_covers_exactly_12_canonical_types(self):
        """Карта -- ровно 12 узловых типов §4.1: перенос из mentor_rules
        дословно, ни потерь, ни пополнений мимо реестра."""
        assert set(EVENT_NODE_STATUS) == {
            "upload_completed",
            "correction_applied",
            "correction_previewed",
            "profile_viewed",
            "backtest_run",
            "tuning_trial_completed",
            "model_selected",
            "model_card_generated",
            "forecast_generated",
            "forecast_compared",
            "forecast_sensitivity_computed",
            "forecast_exported",
        }

    def test_terminal_decision_events_map_to_done(self):
        terminal = [
            event_type
            for event_type, status in EVENT_NODE_STATUS.items()
            if event_type != "correction_previewed"
            and event_type != "profile_viewed"
        ]
        assert len(terminal) == 10
        assert all(EVENT_NODE_STATUS[event_type] == "done" for event_type in terminal)

    def test_correction_previewed_maps_to_warning(self):
        """preview показывается ТОЛЬКО при найденных нарушениях --
        решение ещё не принято: узел warning, не done."""
        assert EVENT_NODE_STATUS["correction_previewed"] == "warning"

    def test_profile_viewed_maps_to_running(self):
        """Просмотр профиля -- узел исследуется: running (принятая цена
        расхождения: без коррекции узел останется running)."""
        assert EVENT_NODE_STATUS["profile_viewed"] == "running"


class TestMapTypesAreReallyEmitted:
    def test_every_mapped_type_registered_in_event_registry(self):
        """Каждая запись карты -- реально испускаемый тип: тип есть в
        реестре хука (STAGE_EVENT_TYPES) на своей стадии -- карта не
        может описывать события, которые трасса никогда не создаст."""
        for event_type in EVENT_NODE_STATUS:
            registered = any(
                event_type in types for types in STAGE_EVENT_TYPES.values()
            )
            assert registered, f"Тип {event_type!r} не в реестре событий"


# ── Контур 2: event_to_dict (публичная нормализация) ─────────────────


class TestEventToDict:
    def test_trace_event_object_normalized_via_to_dict(self):
        event = make_trace_event(
            "correction_applied",
            stage="preprocessing",
            node_id="missing",
            run_id="RUN-AAA00001",
        )
        data = event_to_dict(event)
        assert isinstance(data, dict)
        assert data["event_type"] == "correction_applied"
        assert data["stage"] == "preprocessing"
        assert data["node_id"] == "missing"
        # Канон §4.1: 8 полей + legacy-алиас timestamp (to_dict).
        for key in (
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor", "timestamp",
        ):
            assert key in data

    def test_plain_dict_passes_through(self):
        raw = {"event_type": "backtest_run", "stage": "modeling"}
        assert event_to_dict(raw) is raw  # без копии: события иммутабельны

    def test_garbage_returns_none(self):
        assert event_to_dict(None) is None
        assert event_to_dict(42) is None
        assert event_to_dict("correction_applied") is None
        assert event_to_dict([{"event_type": "backtest_run"}]) is None


# ── Контур 3: resolve_node_id (контракт PROGR-1) ─────────────────────


class TestResolveNodeId:
    def test_explicit_node_id_has_priority(self):
        data = _event("modeling", "backtest", "backtest_run")
        assert resolve_node_id(data) == "backtest"

    def test_forecasting_node_derived_from_event_type(self):
        """Слой 2 хранит forecasting-события с node_id=None (PROGR-1):
        узел выводится из типа -- 4 канонических типа == узлы графа §2."""
        data = _event("forecasting", None, "forecast_generated")
        assert resolve_node_id(data) == "forecast_generated"

    def test_forecasting_unknown_type_stays_none(self):
        """Чужой тип forecasting-события не выдаётся за узел: узлы
        Прогнозирования -- ровно 4 канонических типа события."""
        data = _event("forecasting", None, "unknown_event")
        assert resolve_node_id(data) is None

    def test_non_forecasting_stage_level_event_is_none(self):
        """N-2: события уровня стадии (node_id=None) вне forecasting не
        создают узловых фактов."""
        assert resolve_node_id(_event("eda", None, "passport_captured")) is None
        assert resolve_node_id(_event("validation", None, "run_paused")) is None

    def test_empty_node_id_is_none_not_empty_string(self):
        assert resolve_node_id(_event("preprocessing", "", "correction_applied")) is None
        assert resolve_node_id({"stage": "preprocessing", "event_type": "correction_applied"}) is None


# ── Контур 4: движок derive_node_statuses ────────────────────────────


class TestDeriveNodeStatuses:
    def test_last_event_wins(self):
        """Хронология входа сохраняется: позднее событие перезаписывает
        раннее (previewed -> applied = done; обратный порядок --
        деградация до warning)."""
        applied_first = [
            _event("preprocessing", "missing", "correction_previewed", _ts(10)),
            _event("preprocessing", "missing", "correction_applied", _ts(20)),
        ]
        previewed_last = [
            _event("preprocessing", "missing", "correction_applied", _ts(10)),
            _event("preprocessing", "missing", "correction_previewed", _ts(20)),
        ]
        assert derive_node_statuses(applied_first)["preprocessing/missing"] == "done"
        assert derive_node_statuses(previewed_last)["preprocessing/missing"] == "warning"

    def test_run_level_events_skipped_n2(self):
        """N-2 (PROGR-4): run-level события (node_id=None) не создают
        узловых фактов и не трогают своды стадий."""
        events = [
            _event("preprocessing", None, "run_paused", _ts(5)),
            _event("eda", None, "passport_captured", _ts(4)),
            _event("validation", None, "checkpoint_saved", _ts(3)),
        ]
        assert derive_node_statuses(events) == {}

    def test_forecasting_nodes_derived_from_event_type(self):
        events = [
            _event("forecasting", None, "forecast_generated", _ts(5)),
            _event("forecasting", None, "forecast_exported", _ts(6)),
        ]
        statuses = derive_node_statuses(events)
        assert statuses["forecasting/forecast_generated"] == "done"
        assert statuses["forecasting/forecast_exported"] == "done"

    def test_unknown_nodes_and_types_skipped_no_phantoms(self):
        """Фантомных узлов не возникает: неизвестный узел (is_known_node
        гейт) и неизвестный тип (нет в карте) честно пропускаются."""
        events = [
            _event("preprocessing", "nonexistent", "correction_applied", _ts(5)),
            _event("validation", "formats", "totally_unknown_type", _ts(5)),
            _event("forecasting", None, "unknown_event", _ts(5)),
        ]
        assert derive_node_statuses(events) == {}

    def test_mixed_representations_accepted(self):
        """Слой 1 отдаёт TraceEvent, слой 2 -- stored-словари; движок
        принимает смешанные представления в одном списке (нормализация
        на границе движка, не у каждого потребителя)."""
        events = [
            make_trace_event(
                "correction_applied",
                stage="preprocessing",
                node_id="missing",
                run_id="RUN-AAA00001",
            ),
            _event("modeling", "backtest", "backtest_run", _ts(5)),
        ]
        statuses = derive_node_statuses(events)
        assert statuses["preprocessing/missing"] == "done"
        assert statuses["modeling/backtest"] == "done"

    def test_regularity_collision_between_stages(self):
        """Ключ -- "stage/node_id": regularity Валидации и Предобработки
        -- разные узлы с независимыми статусами (id сознательно
        пересекаются между стадиями)."""
        events = [
            _event("validation", "regularity", "correction_applied", _ts(10)),
            _event("preprocessing", "regularity", "correction_previewed", _ts(20)),
        ]
        statuses = derive_node_statuses(events)
        assert statuses["validation/regularity"] == "done"
        assert statuses["preprocessing/regularity"] == "warning"

    def test_empty_and_garbage_events_yield_empty_map(self):
        assert derive_node_statuses([]) == {}
        assert derive_node_statuses([None, 42, "мусор"]) == {}


# ── Контур 5: derive_stage_states (панельная надстройка) ─────────────


class TestDeriveStageStates:
    def test_empty_statuses_all_stages_not_started_with_honest_totals(self):
        states = derive_stage_states({})
        assert len(states) == 6
        assert all(state["fold"] == "not_started" for state in states)
        assert all(state["done_count"] == 0 for state in states)
        assert all(state["warning_nodes"] == 0 for state in states)
        # Тоталы -- из живого графа, не заглушка.
        from app.core.pipeline_graph import STAGE_NODES

        assert [state["total_nodes"] for state in states] == [
            len(STAGE_NODES[stage]) for stage in (
                "upload", "validation", "preprocessing",
                "eda", "modeling", "forecasting",
            )
        ]

    def test_stages_in_canonical_order_s2(self):
        from app.core.pipeline_graph import STAGES

        states = derive_stage_states({})
        assert [state["stage"] for state in states] == list(STAGES)

    def test_counters_match_derivation(self):
        from app.core.pipeline_graph import STAGE_NODES

        statuses = {
            "upload/structure_confirmed": "done",
            "validation/data_types": "done",
            "validation/formats": "warning",
            "preprocessing/missing": "running",
        }
        states = {state["stage"]: state for state in derive_stage_states(statuses)}
        assert states["upload"]["done_count"] == 1
        assert states["validation"]["done_count"] == 1
        assert states["validation"]["warning_nodes"] == 1
        assert states["validation"]["total_nodes"] == len(STAGE_NODES["validation"])
        assert states["modeling"]["done_count"] == 0

    def test_warning_folds_to_attention_even_with_done_majority(self):
        """§12 п.10: любой единичный warning делает карточку жёлтой --
        заметность проблемы дороже чистоты общей картины (9 done + 1
        warning из 10 -- attention, не passed)."""
        statuses = {
            f"validation/{node_id}": "done"
            for node_id in (
                "data_types", "formats", "ranges", "consistency",
                "uniqueness", "inclusion", "referential",
                "text_quality", "regularity",
            )
        }
        statuses["validation/sufficiency"] = "warning"
        states = {state["stage"]: state for state in derive_stage_states(statuses)}
        assert states["validation"]["fold"] == "attention"
        assert states["validation"]["done_count"] == 9
        assert states["validation"]["warning_nodes"] == 1

    def test_running_folds_to_attention(self):
        """Профиль просмотрен, коррекции не было (принятая цена
        расхождения) -- стадия «в работе» (attention), не «не начато»."""
        statuses = {"eda/descriptive": "running"}
        states = {state["stage"]: state for state in derive_stage_states(statuses)}
        assert states["eda"]["fold"] == "attention"
        assert states["eda"]["warning_nodes"] == 0

    def test_all_done_stage_folds_to_passed(self):
        statuses = {"upload/structure_confirmed": "done"}
        states = {state["stage"]: state for state in derive_stage_states(statuses)}
        assert states["upload"]["fold"] == "passed"


# ── Контур 6: владение (копий движка больше нет) ─────────────────────


class TestEngineOwnership:
    def test_mentor_rules_has_no_engine_copy(self):
        """Бэкенд-дубликат удалён: mentor_rules импортирует публичный API
        движка, а не держит своё зеркало (до PROGR-10 там жили
        derive_node_statuses/_EVENT_STATUS_MAP/_FORECASTING_NODES)."""
        source = (_REPO_ROOT / "app" / "core" / "mentor_rules.py").read_text(
            encoding="utf-8"
        )
        assert "def derive_node_statuses" not in source
        assert "_EVENT_STATUS_MAP" not in source
        assert "_FORECASTING_NODES" not in source
        assert "from app.core.node_status import" in source

    def test_run_report_has_no_forecasting_mirror(self):
        """Третье зеркало (приватный _forecasting_node_of) заменён на
        публичный resolve_node_id единого движка."""
        source = (_REPO_ROOT / "app" / "core" / "run_report.py").read_text(
            encoding="utf-8"
        )
        assert "_forecasting_node_of" not in source
        assert "resolve_node_id" in source

    def test_progress_ts_has_no_frontend_engine(self):
        """Фронтенд рендерит, не вычисляет: порт движка удалён из
        packages/ui/lib/progress.ts -- панель потребляет готовое
        состояние /trace (node_statuses/stages)."""
        source = (_REPO_ROOT / "packages" / "ui" / "lib" / "progress.ts").read_text(
            encoding="utf-8"
        )
        assert "deriveNodeStatuses" not in source
        assert "PROGRESS_EVENT_STATUS" not in source
        assert "foldNodeStatuses" not in source
        assert "collectForecastTraceEvents" not in source
        assert "stageSummary" not in source


# ── Публичный API модуля (реэкспорт для потребителей) ────────────────


def test_public_api_surface():
    """Потребители (панель/Наставник/admin) импортируют ровно этот
    набор: карта, нормализация, вывод узла, движок, свёртка стадий."""
    for name in (
        "EVENT_NODE_STATUS",
        "event_to_dict",
        "resolve_node_id",
        "derive_node_statuses",
        "derive_stage_states",
    ):
        assert hasattr(node_status, name), f"Нет публичного {name}"
