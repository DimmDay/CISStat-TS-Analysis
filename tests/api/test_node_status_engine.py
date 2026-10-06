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
    derive_pipeline_node_states,
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
    def test_map_covers_exactly_13_canonical_types(self):
        """Карта -- ровно 13 узловых типов §4.1 (PROGR-13-A3:
        + structure_confirmed -- факт подтверждения структуры аналитиком;
        отчёты остановок upload_stop_status -- ОТДЕЛЬНЫЙ реестр
        payload-статусов PAYLOAD_STATUS_EVENT_TYPES, статус из payload,
        карте «тип -> один статус» не подвластен)."""
        assert set(EVENT_NODE_STATUS) == {
            "upload_completed",
            "structure_confirmed",
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

    def test_payload_status_registry_is_upload_stop_report(self):
        """PROGR-13-A4 + PROGR-16-A: payload-статусные типы -- отчёты
        остановок «Загрузки» и проверок «Валидации» (клиентские снапшоты
        §7.2); статус валидируется CHECK_STATUS_VALUES в
        resolve_event_status."""
        from app.core.node_status import PAYLOAD_STATUS_EVENT_TYPES

        assert PAYLOAD_STATUS_EVENT_TYPES == frozenset(
            {"upload_stop_status", "validation_check_status"}
        )

    def test_terminal_decision_events_map_to_done(self):
        terminal = [
            event_type
            for event_type, status in EVENT_NODE_STATUS.items()
            if event_type != "correction_previewed"
            and event_type != "profile_viewed"
        ]
        assert len(terminal) == 11
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
            "upload/structure": "done",
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
        from app.core.pipeline_graph import STAGE_NODES

        statuses = {
            f"upload/{node_id}": "done" for node_id in STAGE_NODES["upload"]
        }
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


# ── Контур 7: полное состояние узла §3 (PROGR-11) ────────────────────
#
# РАСХОЖДЕНИЕ (постановка PROGR-11): поля §3 mode/summary_count/
# status_reason объявлены в PipelineNodeState (pipeline_graph.py), но в
# рендер панели попадает только статус, выведенный из событий; бейджи-
# числа и mode до UI не доезжают. Решение -- канонический движок
# дополняется чистой функцией derive_pipeline_node_states: ВСЕ узлы
# графа в порядке §2 с полным набором полей §3; статус -- тот же
# канонический derive_node_statuses (вторая реализации статуса
# запрещена), остальные поля -- из ТЕХ ЖЕ засеянных фактов решений
# (trace_events) + эффективные check-modes сессии (Валидация/
# Предобработка -- то же состояние, что показывают степперы;
# опроса profile-эндпоинтов по-прежнему нет).


class TestPipelineNodeStates:
    def test_reason_map_covers_exactly_the_status_map(self):
        """Шаблоны status_reason -- ровно для тех же узловых типов, что
        и карта статусов ПЛЮС payload-статусные типы (PROGR-13-A4:
        upload_stop_status -- тоже узловой факт решения, причина общая):
        reason и статус всегда описывают ОДНО и то же последнее событие
        узла (рассинхрон невозможен по построению)."""
        from app.core.node_status import PAYLOAD_STATUS_EVENT_TYPES

        assert set(node_status.EVENT_NODE_REASON) == (
            set(EVENT_NODE_STATUS) | set(PAYLOAD_STATUS_EVENT_TYPES)
        )

    def test_empty_events_return_all_graph_nodes_in_s2_order(self):
        """Пустая трасса -- ВСЕ 50 узлов графа в каноническом порядке §2,
        честные «не начато» (pending) без выдуманных фактов."""
        from app.core.pipeline_graph import STAGES, STAGE_NODES

        states = derive_pipeline_node_states([])
        assert [s["stage"] for s in states] == [
            stage for stage in STAGES for _ in STAGE_NODES[stage]
        ]
        assert [s["node_id"] for s in states] == [
            node_id for stage in STAGES for node_id in STAGE_NODES[stage]
        ]
        assert all(s["status"] == "pending" for s in states)
        assert all(s["status_reason"] is None for s in states)
        assert all(s["last_touched_at"] is None for s in states)
        assert all(s["summary_count"] is None for s in states)

    def test_node_dict_carries_exactly_the_s3_fields(self):
        """Контракт §3: ровно 7 полей PipelineNodeState -- ничего лишнего
        (зеркало датакласса, не новая модель)."""
        states = derive_pipeline_node_states([])
        assert all(
            set(s) == {
                "stage", "node_id", "status", "status_reason",
                "mode", "last_touched_at", "summary_count",
            }
            for s in states
        )

    def test_correction_facts_fill_reason_count_and_ts(self):
        """correction_applied -- факт решения: статус done (канонический
        движок), reason по шаблону, summary_count из payload
        (total_missing -- то же число, что в правом бейдже узла, §3),
        last_touched_at -- ts события."""
        events = [
            _event(
                "preprocessing", "missing", "correction_applied",
                ts="2026-09-29T10:05:00+00:00",
                applied=True, strategy="mean", total_missing=12,
            ),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        node = by_key[("preprocessing", "missing")]
        assert node["status"] == "done"
        assert node["status_reason"] == node_status.EVENT_NODE_REASON["correction_applied"]
        assert node["summary_count"] == 12
        assert node["last_touched_at"] == "2026-09-29T10:05:00+00:00"

    def test_count_key_priority_problem_counts_first(self):
        """Приоритет ключей бейджа: проблемные счётчики (total_missing/
        total_outliers/total_violations/total_invalid) старше
        результатов коррекции (rows_removed/total_changed)."""
        events = [
            _event(
                "validation", "consistency", "correction_applied",
                total_changed=7, total_violations=3,
            ),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        assert by_key[("validation", "consistency")]["summary_count"] == 3

    def test_last_event_wins_for_reason_count_and_ts(self):
        """Хронология: позднее событие перезаписывает раннее
        (previewed -> applied = done + причина applied); счётчик -- от
        последнего события с числом, не от первого."""
        events = [
            _event(
                "preprocessing", "outliers", "correction_previewed",
                ts="2026-09-29T10:01:00+00:00", total_outliers=5,
            ),
            _event(
                "preprocessing", "outliers", "correction_applied",
                ts="2026-09-29T10:02:00+00:00", total_outliers=0, rows_removed=2,
            ),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        node = by_key[("preprocessing", "outliers")]
        assert node["status"] == "done"
        assert node["status_reason"] == node_status.EVENT_NODE_REASON["correction_applied"]
        # total_outliers (проблемный счётчик) старше rows_removed даже
        # внутри одного payload.
        assert node["summary_count"] == 0
        assert node["last_touched_at"] == "2026-09-29T10:02:00+00:00"

    def test_profile_viewed_reason_and_running(self):
        """Просмотренный без коррекции узел -- running (принятая цена
        расхождения №1) с честной причиной."""
        events = [
            _event("eda", "correlation", "profile_viewed",
                   ts="2026-09-29T10:03:00+00:00"),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        node = by_key[("eda", "correlation")]
        assert node["status"] == "running"
        assert node["status_reason"] == node_status.EVENT_NODE_REASON["profile_viewed"]
        assert node["summary_count"] is None  # profile_viewed чисел не несёт
        assert node["last_touched_at"] == "2026-09-29T10:03:00+00:00"

    def test_upload_completed_has_no_summary_count(self):
        """payload upload_completed (name/rows/columns/size_label) не
        содержит ключей бейджа -- summary_count честно None, бейдж
        не выдумывается. PROGR-13-A3: факт чтения файла -- узел overview
        (подтверждение структуры -- отдельное событие)."""
        events = [
            _event("upload", "overview", "upload_completed",
                   rows=120, columns=7),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        node = by_key[("upload", "overview")]
        assert node["status"] == "done"
        assert node["summary_count"] is None
        assert node["last_touched_at"] is not None

    def test_mode_effective_for_validation_and_preprocessing_only(self):
        """mode (§3: auto/enabled/disabled) -- только Валидация/
        Предобработка; отсутствующее значение -- эффективное «auto»
        (тот же контракт, что у степперов), остальные стадии -- None."""
        check_modes = {"validation": {"formats": "disabled"}}
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states([], check_modes)
        }
        assert by_key[("validation", "formats")]["mode"] == "disabled"
        assert by_key[("validation", "data_types")]["mode"] == "auto"
        assert by_key[("preprocessing", "missing")]["mode"] == "auto"
        assert by_key[("upload", "structure")]["mode"] is None
        assert by_key[("eda", "correlation")]["mode"] is None
        assert by_key[("modeling", "backtest")]["mode"] is None
        assert by_key[("forecasting", "forecast_generated")]["mode"] is None

    def test_mode_invalid_value_failsafe_to_auto(self):
        """Битое значение mode в хранилище -- fail-safe «auto» (тот же
        контракт, что _effective_*_check_modes степперов), не мусор в UI."""
        check_modes = {"preprocessing": {"missing": "turbo"}}
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states([], check_modes)
        }
        assert by_key[("preprocessing", "missing")]["mode"] == "auto"

    def test_mode_none_when_check_modes_not_provided(self):
        """check_modes не передан -- mode None (движок не выдумывает
        данные, которых нет); роутер всегда передаёт сессионные словари."""
        states = derive_pipeline_node_states([])
        assert all(s["mode"] is None for s in states)

    def test_stage_level_and_phantom_events_do_not_touch_details(self):
        """N-2: события без узла (mode_changed/target_column_changed) и
        фантомные пары вне графа не создают деталей; mode_changed -- 
        событие уровня стадии, mode узлов приходит из состояния сессии."""
        events = [
            _event("validation", None, "mode_changed", modes={"formats": "disabled"}),
            _event("validation", "phantom", "correction_applied", total_missing=1),
            _event("nowhere", "missing", "correction_applied"),
        ]
        states = derive_pipeline_node_states(events)
        assert all(s["last_touched_at"] is None for s in states)
        assert all(s["summary_count"] is None for s in states)
        assert all(s["status"] == "pending" for s in states)

    def test_non_integer_counts_are_skipped_failsafe(self):
        """Мусор в счётчике (строка/bool/отрицательное) -- не бейдж:
        ключ пропускается, других ключей payload это не касается."""
        events = [
            _event(
                "preprocessing", "missing", "correction_applied",
                total_missing="много", total_changed=True, rows_removed=-1,
                total_outliers=4,
            ),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        assert by_key[("preprocessing", "missing")]["summary_count"] == 4

    def test_last_touched_at_skips_unreadable_ts(self):
        """Нечитаемый ts события не затирает последний валидный
        last_touched_at (fail-safe хронологии)."""
        events = [
            _event("eda", "seasonality", "profile_viewed",
                   ts="2026-09-29T10:07:00+00:00"),
            _event("eda", "seasonality", "profile_viewed", ts=""),
        ]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        assert by_key[("eda", "seasonality")]["last_touched_at"] == (
            "2026-09-29T10:07:00+00:00"
        )

    def test_trace_event_objects_and_dicts_mixed(self):
        """Смешанные представления легальны (слой 1 -- TraceEvent,
        слой 2 -- stored-словари), как в derive_node_statuses."""
        obj = make_trace_event(
            "correction_applied", stage="preprocessing",
            node_id="missing", run_id="RUN-AAA00002",
        )
        events = [_event("preprocessing", "missing", "correction_previewed"), obj]
        by_key = {
            (s["stage"], s["node_id"]): s
            for s in derive_pipeline_node_states(events)
        }
        node = by_key[("preprocessing", "missing")]
        assert node["status"] == "done"
        assert node["status_reason"] == node_status.EVENT_NODE_REASON["correction_applied"]

    def test_status_matches_canonical_engine_everywhere(self):
        """Статусы полного состояния == канонический derive_node_statuses
        на тех же событиях (вторая реализация статуса запрещена)."""
        from app.core.pipeline_graph import STAGES, STAGE_NODES

        events = [
            _event("validation", "formats", "correction_previewed"),
            _event("preprocessing", "missing", "correction_applied"),
            _event("eda", "correlation", "profile_viewed"),
            _event("forecasting", None, "forecast_generated"),
        ]
        statuses = derive_node_statuses(events)
        states = derive_pipeline_node_states(events)
        for state in states:
            expected = statuses.get(f"{state['stage']}/{state['node_id']}", "pending")
            assert state["status"] == expected
        # И полнота: все узлы графа присутствуют.
        assert len(states) == sum(len(nodes) for nodes in STAGE_NODES.values())
        assert {(s["stage"], s["node_id"]) for s in states} == {
            (stage, node_id)
            for stage in STAGES
            for node_id in STAGE_NODES[stage]
        }


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
        "derive_pipeline_node_states",
    ):
        assert hasattr(node_status, name), f"Нет публичного {name}"
