# tests/api/test_trace_events.py
# Task PROGR-1 (2026-09-23) -- сведение канонического TraceEvent
# (spec_progress.md §4.1) с реализацией apps/api/trace_events.py
# (spec_forecasting2.md §10.4). TDD RED: контракт 8 канонических полей,
# реестр типов событий по стадиям, нормализация legacy-событий.
"""Контракт канонического события трассы «Прогресса».

Канон (spec_progress.md §4.1): event_id / run_id / ts / stage / node_id /
event_type / payload / actor. Реализованный ранее (spec_forecasting2.md
§10.4) 3-польный формат -- совместимое подмножество, мигрируемое
аддитивно: legacy-алиас `timestamp` сохраняется в to_dict() (pydantic
ForecastTraceEventSchema требует его как обязательное поле), а нормализация
старых stored-событий выполняется normalize_trace_event_dict().
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from apps.api.trace_events import (
    FORECAST_EVENT_TYPES,
    KNOWN_STAGES,
    RUN_LEVEL_EVENT_TYPES,
    STAGE_EVENT_TYPES,
    TraceEvent,
    make_trace_event,
    normalize_trace_event_dict,
)


# ── Канонические поля §4.1 ────────────────────────────────────────

class TestCanonicalFields:
    def test_make_trace_event_has_all_eight_canonical_fields(self):
        event = make_trace_event("forecast_generated", horizon=6, alpha=0.05)
        assert event.event_type == "forecast_generated"
        assert event.payload == {"horizon": 6, "alpha": 0.05}
        # event_id -- непустая uuid-строка
        assert isinstance(event.event_id, str) and len(event.event_id) >= 32
        # ts -- ISO-8601, парсится datetime.fromisoformat
        assert isinstance(event.ts, str)
        datetime.fromisoformat(event.ts)
        # stage -- по умолчанию forecasting (совместимость с 4 текущими вызовами)
        assert event.stage == "forecasting"
        # node_id -- None для событий уровня стадии/этапа
        assert event.node_id is None
        # run_id -- по умолчанию "" (привязка к research_runs -- задача PROGR-3)
        assert event.run_id == ""
        # actor -- единственный вариант на сейчас
        assert event.actor == "user"

    def test_explicit_stage_node_id_run_id_actor(self):
        event = make_trace_event(
            "correction_applied",
            stage="preprocessing",
            node_id="missing",
            run_id="run-123",
            actor="user",
            strategy="median",
        )
        assert event.stage == "preprocessing"
        assert event.node_id == "missing"
        assert event.run_id == "run-123"
        assert event.actor == "user"
        assert event.payload == {"strategy": "median"}

    def test_event_ids_unique(self):
        a = make_trace_event("forecast_generated")
        b = make_trace_event("forecast_generated")
        assert a.event_id != b.event_id

    def test_timestamp_legacy_alias_points_to_ts(self):
        event = make_trace_event("forecast_generated")
        assert event.timestamp == event.ts


# ── to_dict(): 8 канонических ключей + legacy-алиас ──────────────

class TestToDict:
    def test_to_dict_contains_canonical_and_legacy_keys(self):
        raw = make_trace_event(
            "forecast_exported", format="csv",
            stage="forecasting", run_id="run-9", node_id=None,
        ).to_dict()
        expected = {
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor", "timestamp",
        }
        assert set(raw.keys()) == expected
        assert raw["timestamp"] == raw["ts"]
        assert raw["event_type"] == "forecast_exported"
        assert raw["payload"] == {"format": "csv"}
        assert raw["stage"] == "forecasting"
        assert raw["run_id"] == "run-9"

    def test_to_dict_payload_is_deep_copied(self):
        event = make_trace_event("forecast_generated", horizon=3)
        raw = event.to_dict()
        raw["payload"]["horizon"] = 999
        assert event.payload["horizon"] == 3

    def test_to_dict_json_serializable(self):
        raw = make_trace_event("forecast_compared", forecast_ids=["a", "b"]).to_dict()
        assert json.loads(json.dumps(raw)) == raw


# ── Fail-closed реестр типов событий по стадиям (§4.1 таблица) ──

class TestStageEventRegistry:
    def test_known_stages_match_six_pipeline_stages(self):
        assert KNOWN_STAGES == (
            "upload", "validation", "preprocessing", "eda",
            "modeling", "forecasting",
        )

    def test_forecasting_registry_is_existing_forecast_event_types(self):
        assert STAGE_EVENT_TYPES["forecasting"] == set(FORECAST_EVENT_TYPES)
        assert FORECAST_EVENT_TYPES == {
            "forecast_generated", "forecast_compared",
            "forecast_sensitivity_computed", "forecast_exported",
        }

    def test_registry_per_spec_table(self):
        # PROGR-13-B2: паспорт -- сквозной факт, точка задаёт стадию
        # события (TRACE_ROUTES маппит start->upload,
        # validation->validation, exit->eda, modeling_entry->modeling);
        # реестр расширен типом на upload/validation/modeling (паттерн
        # «сторонние этапы -- расширением реестра, не обходом гейта»).
        # PROGR-13-A3/A4: Загрузка + structure_confirmed (подтверждение
        # структуры аналитиком, POST /date-column) и upload_stop_status
        # (отчёт фактов остановок модулем, статус -- в payload).
        assert STAGE_EVENT_TYPES["upload"] == {
            "upload_completed", "passport_captured",
            "structure_confirmed", "upload_stop_status",
        }
        assert STAGE_EVENT_TYPES["validation"] == {
            "mode_changed", "correction_previewed",
            "correction_applied", "target_column_changed",
            "passport_captured",
        }
        assert STAGE_EVENT_TYPES["preprocessing"] == {
            "mode_changed", "correction_previewed",
            "correction_applied", "target_column_changed",
        }
        assert STAGE_EVENT_TYPES["eda"] == {"profile_viewed", "passport_captured"}
        assert STAGE_EVENT_TYPES["modeling"] == {
            "backtest_run", "tuning_trial_completed",
            "model_selected", "model_card_generated",
            "passport_captured",
        }

    def test_run_level_events_valid_on_any_stage(self):
        for stage in KNOWN_STAGES:
            for event_type in RUN_LEVEL_EVENT_TYPES:
                event = make_trace_event(event_type, stage=stage)
                assert event.stage == stage
        assert RUN_LEVEL_EVENT_TYPES == {"run_paused", "run_resumed", "checkpoint_saved"}

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError, match="Неизвестный тип события трассы"):
            make_trace_event("forecast_generated_typo")

    def test_known_type_with_wrong_stage_raises(self):
        # mode_changed не существует на стадии modeling -- опечатка
        # stage при вызове не должна молча попасть в трассу.
        with pytest.raises(ValueError, match="Неизвестный тип события трассы"):
            make_trace_event("mode_changed", stage="modeling")

    def test_unknown_stage_raises(self):
        with pytest.raises(ValueError, match="Неизвестная стадия"):
            make_trace_event("run_paused", stage="bogus")


# ── Нормализация legacy-событий (stored-формат 3 полей) ──────────

class TestNormalizeLegacy:
    def test_legacy_three_field_dict_becomes_canonical(self):
        raw = {
            "event_type": "forecast_generated",
            "timestamp": "2026-09-01T10:00:00+00:00",
            "payload": {"horizon": 6},
        }
        out = normalize_trace_event_dict(raw)
        assert set(out.keys()) == {
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor",
        }
        assert out["ts"] == "2026-09-01T10:00:00+00:00"
        assert "timestamp" not in out  # канон без legacy-алиаса
        assert out["stage"] == "forecasting"
        assert out["node_id"] is None
        assert out["actor"] == "user"
        assert out["run_id"] == ""
        assert out["payload"] == {"horizon": 6}
        assert len(out["event_id"]) >= 32

    def test_run_id_can_be_attached_during_normalization(self):
        raw = {"event_type": "forecast_generated", "timestamp": "t-not-iso-but-preserved"}
        out = normalize_trace_event_dict(raw, run_id="RUN-8F2A91")
        assert out["run_id"] == "RUN-8F2A91"
        assert out["ts"] == "t-not-iso-but-preserved"  # переносятся как есть

    def test_canonical_dict_passes_through_and_missing_defaults_filled(self):
        raw = {
            "event_id": "e" * 32,
            "run_id": "run-1",
            "ts": "2026-09-01T10:00:00+00:00",
            "stage": "validation",
            "node_id": "ranges",
            "event_type": "correction_applied",
            "payload": {"total_changed": 2},
            "actor": "user",
        }
        out = normalize_trace_event_dict(raw)
        assert out == raw

    def test_partial_canonical_dict_defaults_filled(self):
        out = normalize_trace_event_dict({"event_type": "run_paused", "ts": "2026-09-01T00:00:00+00:00"})
        # Дефолт стадии -- "forecasting": единственная реальная legacy-
        # популяция stored-событий (3-польный формат §7 forecasting2) весь
        # этапа Прогнозирования; дефолт не изобретает ложных данных.
        assert out["stage"] == "forecasting"
        assert out["node_id"] is None
        assert out["actor"] == "user"
        assert out["run_id"] == ""
        assert out["event_id"]

    def test_input_dict_not_mutated(self):
        raw = {"event_type": "forecast_generated", "timestamp": "t", "payload": {"a": 1}}
        snapshot = json.dumps(raw)
        normalize_trace_event_dict(raw)
        assert json.dumps(raw) == snapshot

    def test_from_dict_roundtrip_with_canonical_to_dict(self):
        event = make_trace_event(
            "checkpoint_saved", stage="eda",
            node_id="seasonality", run_id="run-7", comment="перед спектром",
        )
        restored = TraceEvent.from_dict(event.to_dict())
        assert restored == event  # dataclass-равенство: все 8 полей

    def test_from_dict_legacy_format(self):
        event = TraceEvent.from_dict({
            "event_type": "forecast_exported",
            "timestamp": "2026-09-01T11:00:00+00:00",
            "payload": {"format": "png"},
        })
        assert event.ts == "2026-09-01T11:00:00+00:00"
        assert event.stage == "forecasting"
        assert event.payload == {"format": "png"}


# ── Обратная совместимость существующих вызовов ───────────────────

class TestBackwardCompat:
    def test_existing_forecasting_call_sites_signature_unchanged(self):
        # Ровно так вызывают 4 текущих call-site forecasting_session.py:
        # make_trace_event(event_type, **payload) -- без stage/run_id.
        event = make_trace_event(
            "forecast_generated",
            model_card_id="mc-1", forecast_id="f-1",
            horizon=12, alpha=0.05, ci_method="normal",
        )
        assert event.stage == "forecasting"
        assert event.payload["model_card_id"] == "mc-1"

    def test_frozen_dataclass_still_frozen(self):
        event = make_trace_event("forecast_generated")
        with pytest.raises(Exception):
            event.event_type = "forecast_exported"  # type: ignore[misc]

    def test_default_factory_payload_not_shared(self):
        a = make_trace_event("forecast_generated")
        b = make_trace_event("forecast_generated")
        a.payload["x"] = 1
        assert b.payload == {}
