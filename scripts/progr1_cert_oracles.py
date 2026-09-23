# scripts/progr1_cert_oracles.py
# Независимый сертификационный аудит Task PROGR-1: оракул-тесты
# на СОБСТВЕННЫХ данных аудитора (run_id, timestamps, payload-факты и
# legacy-популяция не пересекаются с fixtures tests/api/test_trace_events.py).
# Оракул = свойство с известным точным ответом из spec_progress.md §4.1
# (канон 8 полей, таблица event_type по стадиям, двойная запись ts/timestamp,
# аддитивная миграция 3-польных stored-событий) и аддендума (п.2.1).
# Запуск: python scripts/progr1_cert_oracles.py   (exit 0 == все GREEN)
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from uuid import UUID

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

from apps.api.schemas import ForecastTraceEventSchema  # noqa: E402
from apps.api.trace_events import (  # noqa: E402
    FORECAST_EVENT_TYPES,
    KNOWN_STAGES,
    RUN_LEVEL_EVENT_TYPES,
    STAGE_EVENT_TYPES,
    TraceEvent,
    make_trace_event,
    normalize_trace_event_dict,
)

RESULTS: list[tuple[str, str, str]] = []


def check(oracle_id: str, description: str, fn) -> None:
    try:
        fn()
        RESULTS.append((oracle_id, "PASS", description))
        print(f"[PASS] {oracle_id}: {description}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((oracle_id, "FAIL", f"{description} :: {type(exc).__name__}: {exc}"))
        print(f"[FAIL] {oracle_id}: {description}")
        traceback.print_exc(limit=3)


# ── Собственные данные аудитора (не совпадают с fixtures коллеги) ──

MY_RUN_ID = "RUN-9F3KC7-CERT"
MY_TS_LEGACY = "2026-09-21T07:45:11.123456+00:00"
MY_STAGES_NODES = {
    "validation": "ranges",
    "preprocessing": "missing",
    "eda": "seasonality",
    "modeling": "backtest",
    "forecasting": None,
    "upload": None,
}
MY_PAYLOAD_FACTS = {
    "strategy": "lin_interp_time",
    "total_changed": 7,
    "rows_removed": 0,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── A. Канонические поля §4.1 ─────────────────────────────────────


def a1_eight_fields_exact_values() -> None:
    ev = make_trace_event(
        "correction_applied",
        stage="preprocessing",
        node_id="missing",
        run_id=MY_RUN_ID,
        actor="user",
        **MY_PAYLOAD_FACTS,
    )
    assert ev.event_type == "correction_applied"
    assert ev.stage == "preprocessing"
    assert ev.node_id == "missing"
    assert ev.run_id == MY_RUN_ID
    assert ev.actor == "user"
    assert ev.payload == MY_PAYLOAD_FACTS
    assert isinstance(ev.event_id, str) and ev.event_id
    assert isinstance(ev.ts, str) and ev.ts
    # Полей ровно восемь (канон §4.1), девятое имя -- только legacy-алиас.
    canon = {"event_id", "run_id", "ts", "stage", "node_id", "event_type", "payload", "actor"}
    have = {f for f in vars(ev) if not f.startswith("_")}
    assert have == canon, f"поля датакласса != канона: {have}"


def a2_event_id_is_uuid() -> None:
    ev = make_trace_event("forecast_generated", horizon=6)
    UUID(ev.event_id)  # ValueError, если не uuid
    assert len(ev.event_id) == 36 and ev.event_id.count("-") == 4


def a3_ts_is_server_utc_iso() -> None:
    before = _utc_now()
    ev = make_trace_event("forecast_generated")
    after = _utc_now()
    parsed = datetime.fromisoformat(ev.ts)
    assert parsed.tzinfo is not None, "ts обязан быть timezone-aware (сервер, UTC)"
    assert parsed.utcoffset().total_seconds() == 0, "ts обязан быть UTC"
    assert before <= parsed <= after, "ts обязан генерироваться сервером в момент фабрики"


def a4_node_id_none_for_stage_level() -> None:
    ev = make_trace_event("checkpoint_saved", stage="eda")
    assert ev.node_id is None


def a5_actor_default_user() -> None:
    ev = make_trace_event("forecast_generated")
    assert ev.actor == "user"  # §4.1: "user" -- единственный вариант сейчас


def a6_frozen_dataclass() -> None:
    import dataclasses

    ev = make_trace_event("forecast_generated")
    assert dataclasses.is_dataclass(ev)
    try:
        ev.event_type = "forecast_exported"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("датакласс обязан быть frozen (иммутабельная трасса)")


def a7_default_payload_not_shared() -> None:
    a = make_trace_event("forecast_generated")
    b = make_trace_event("forecast_compared")
    a.payload["leak"] = 1
    assert "leak" not in b.payload and b.payload == {}


def a8_legacy_alias_property() -> None:
    ev = make_trace_event("forecast_exported", fmt="csv")
    assert ev.timestamp == ev.ts


def a9_defaults_sweep() -> None:
    # Дефолты фабрики/датакласса -- контракт совместимости 4 call-site
    ev = make_trace_event("forecast_generated")
    assert ev.run_id == "" and isinstance(ev.run_id, str)
    assert ev.stage == "forecasting" and ev.node_id is None
    assert ev.actor == "user" and ev.payload == {}


# ── B. Реестр event_type по стадиям (таблица §4.1) ────────────────

# Независимая кодировка таблицы §4.1 spec_progress.md (строка upload --
# из §6.1: перенос addLogEntry успешной загрузки в TraceEvent).
SPEC_TABLE: dict[str, set[str]] = {
    "upload": {"upload_completed"},
    "validation": {"mode_changed", "correction_previewed", "correction_applied", "target_column_changed"},
    "preprocessing": {"mode_changed", "correction_previewed", "correction_applied", "target_column_changed"},
    "eda": {"profile_viewed", "passport_captured"},
    "modeling": {"backtest_run", "tuning_trial_completed", "model_selected", "model_card_generated"},
    "forecasting": {"forecast_generated", "forecast_compared", "forecast_sensitivity_computed", "forecast_exported"},
}
SPEC_RUN_LEVEL = {"run_paused", "run_resumed", "checkpoint_saved"}
SPEC_STAGES = ("upload", "validation", "preprocessing", "eda", "modeling", "forecasting")


def b1_registry_matches_spec_table_exactly() -> None:
    assert set(STAGE_EVENT_TYPES) == set(SPEC_STAGES), "набор стадий реестра != §2"
    for stage, types in SPEC_TABLE.items():
        assert STAGE_EVENT_TYPES[stage] == types, (
            f"реестр[{stage!r}] расходится с таблицей §4.1: "
            f"{STAGE_EVENT_TYPES[stage] ^ types}"
        )
    # run-level НЕ растворены в стадиях -- реестр отражает таблицу дословно
    for stage in SPEC_STAGES:
        assert not (STAGE_EVENT_TYPES[stage] & SPEC_RUN_LEVEL), (
            f"run-level типы вплавлены в стадию {stage!r} -- это не таблица §4.1"
        )


def b2_run_level_valid_on_any_stage() -> None:
    for stage in SPEC_STAGES:
        for et in SPEC_RUN_LEVEL:
            ev = make_trace_event(et, stage=stage, run_id=MY_RUN_ID)
            assert ev.stage == stage and ev.event_type == et and ev.run_id == MY_RUN_ID


def b3_unknown_event_type_fails_closed() -> None:
    for stage in SPEC_STAGES:
        try:
            make_trace_event("forecast_generated_typo", stage=stage)
        except ValueError:
            continue
        raise AssertionError(f"неизвестный тип не отклонён на стадии {stage!r}")


def b4_valid_type_on_wrong_stage_fails_closed() -> None:
    all_types = set().union(*SPEC_TABLE.values())
    for stage in SPEC_STAGES:
        foreign = sorted(all_types - SPEC_TABLE[stage] - SPEC_RUN_LEVEL)
        assert foreign, f"нет чужого типа для стадии {stage!r}"
        probe = foreign[0]
        try:
            make_trace_event(probe, stage=stage)
        except ValueError:
            continue
        raise AssertionError(f"чужой тип {probe!r} принят на стадии {stage!r}")


def b5_unknown_stage_fails_closed() -> None:
    for bad in ("bogus", "", "UPLOAD", "forecasting2"):
        try:
            make_trace_event("run_paused", stage=bad)
        except ValueError:
            continue
        raise AssertionError(f"неизвестная стадия {bad!r} не отклонена")


def b6_known_stages_equal_spec_stages() -> None:
    assert KNOWN_STAGES == SPEC_STAGES == tuple(SPEC_TABLE)


def b7_exhaustive_positive_sweep() -> None:
    # Каждая (stage, event_type)-пара реестра + run-level -- фабрика success,
    # поля совпадают, node_id по MY_STAGES_NODES.
    for stage, types in SPEC_TABLE.items():
        for et in sorted(types):
            node = MY_STAGES_NODES[stage]
            ev = make_trace_event(et, stage=stage, node_id=node, run_id=MY_RUN_ID)
            assert (ev.stage, ev.event_type, ev.node_id) == (stage, et, node)
    assert RUN_LEVEL_EVENT_TYPES == SPEC_RUN_LEVEL
    assert FORECAST_EVENT_TYPES == SPEC_TABLE["forecasting"]


# ── C. to_dict(): 8 канонических ключей + legacy-алиас ────────────

CANON_KEYS = {"event_id", "run_id", "ts", "stage", "node_id", "event_type", "payload", "actor"}


def c1_dict_keys_nine_with_alias() -> None:
    d = make_trace_event("forecast_generated", h=6).to_dict()
    assert set(d) == CANON_KEYS | {"timestamp"}, f"ключи to_dict: {sorted(d)}"


def c2_alias_equals_ts_in_dict() -> None:
    d = make_trace_event("forecast_compared").to_dict()
    assert d["timestamp"] == d["ts"]
    # Порядок и типы: payload -- dict, node_id -- None по умолчанию
    assert isinstance(d["payload"], dict) and d["node_id"] is None


def c3_json_roundtrip() -> None:
    d = make_trace_event(
        "correction_applied", stage="validation", node_id="ranges",
        run_id=MY_RUN_ID, **MY_PAYLOAD_FACTS,
    ).to_dict()
    assert json.loads(json.dumps(d)) == d


def c4_pydantic_http_contract_intact() -> None:
    # Двойная запись: ForecastTraceEventSchema требует timestamp (обязательное),
    # лишние канонические ключи фильтруются -- HTTP-контракт не меняется.
    for stage, types in SPEC_TABLE.items():
        for et in sorted(types):
            d = make_trace_event(et, stage=stage, run_id=MY_RUN_ID).to_dict()
            schema = ForecastTraceEventSchema(**d)
            dump = schema.model_dump()
            assert set(dump) == {"event_type", "timestamp", "payload"}
            assert dump["timestamp"] == d["ts"] and dump["event_type"] == et
    # Фронтенд-интерфейс ForecastTraceEvent (packages/ui/lib/forecasting.ts)
    # читает event_type/timestamp/payload -- все три присутствуют.
    d = make_trace_event("forecast_generated").to_dict()
    assert {"event_type", "timestamp", "payload"} <= set(d)


def c5_flat_payload_independence() -> None:
    ev = make_trace_event("forecast_generated", horizon=6, alpha=0.05)
    d = ev.to_dict()
    d["payload"]["horizon"] = 999
    assert ev.payload["horizon"] == 6, "to_dict обязан копировать payload верхнего уровня"
    d2 = ev.to_dict()
    ev.payload["alpha"] = 0.5
    assert d2["payload"]["alpha"] == 0.05, "событие не должно мутировать ранее отданный словарь"


def c5b_nested_payload_sharing_characterization() -> None:
    # ХАРАКТЕРИЗАЦИЯ (см. акт сертификации, замечание R1): копия payload в
    # to_dict() поверхностная -- вложенные структуры разделяются с событием.
    ev = make_trace_event("correction_applied", stage="validation", nested={"a": 1})
    d = ev.to_dict()
    d["payload"]["nested"]["a"] = 999
    assert ev.payload["nested"]["a"] == 999, "ожидаемое (документируемое) поведение: вложенные структуры разделяются"


# ── D. Нормализация legacy 3-польных stored-событий ───────────────

CANON_OUT_KEYS = {"event_id", "run_id", "ts", "stage", "node_id", "event_type", "payload", "actor"}


def d1_legacy_three_fields_to_canonical() -> None:
    raw = {
        "event_type": "forecast_generated",
        "timestamp": MY_TS_LEGACY,
        "payload": {"horizon": 12, "model_card_id": "mc-cert-77"},
    }
    out = normalize_trace_event_dict(raw)
    assert set(out) == CANON_OUT_KEYS, f"ключи нормы: {sorted(out)}"
    assert out["ts"] == MY_TS_LEGACY and "timestamp" not in out
    assert out["stage"] == "forecasting" and out["node_id"] is None
    assert out["actor"] == "user" and out["run_id"] == ""
    assert out["payload"] == {"horizon": 12, "model_card_id": "mc-cert-77"}
    UUID(out["event_id"])


def d2_run_id_attach_and_priority() -> None:
    legacy = {"event_type": "forecast_compared", "timestamp": MY_TS_LEGACY}
    out = normalize_trace_event_dict(legacy, run_id=MY_RUN_ID)
    assert out["run_id"] == MY_RUN_ID
    # run_id самого события приоритетнее параметра границы чтения
    own = {"event_type": "forecast_compared", "timestamp": MY_TS_LEGACY, "run_id": "RUN-LEGACY-001"}
    out2 = normalize_trace_event_dict(own, run_id=MY_RUN_ID)
    assert out2["run_id"] == "RUN-LEGACY-001"


def d3_normalization_idempotent() -> None:
    legacy = {"event_type": "forecast_exported", "timestamp": MY_TS_LEGACY, "payload": {"fmt": "png"}}
    once = normalize_trace_event_dict(legacy)
    twice = normalize_trace_event_dict(once)
    assert once == twice
    canon = make_trace_event("forecast_generated", stage="forecasting", run_id=MY_RUN_ID).to_dict()
    c1 = normalize_trace_event_dict(canon)
    assert normalize_trace_event_dict(c1) == c1


def d4_input_not_mutated_and_flat_payload_isolated() -> None:
    raw = {
        "event_type": "forecast_sensitivity_computed",
        "timestamp": MY_TS_LEGACY,
        "payload": {"varied_axes": ["horizon"], "n_combos": 3},
    }
    snapshot = json.dumps(raw, sort_keys=True)
    out = normalize_trace_event_dict(raw)
    assert json.dumps(raw, sort_keys=True) == snapshot, "вход мутирован нормализацией"
    # Плоский уровень payload изолирован в ОБЕ стороны (верхняя копия dict())
    out["payload"]["n_combos"] = 999
    assert raw["payload"]["n_combos"] == 3, "payload выхода разделяется с входом"
    raw["payload"]["n_combos"] = 7
    out2 = normalize_trace_event_dict(raw)
    assert out2["payload"]["n_combos"] == 7  # честная нормализация текущего значения
    out2["payload"]["n_combos"] = 999
    assert raw["payload"]["n_combos"] == 7


def d4b_nested_payload_shared_with_input_characterization() -> None:
    # ХАРАКТЕРИЗАЦИЯ (см. акт сертификации, замечание R1b): копия payload в
    # нормализации поверхностная -- ВЛОЖЕННЫЕ структуры разделяются между
    # stored-входом и нормализованным выходом (та же мелкая копия, что и R1
    # в to_dict). Мутация вложенного списка на входе видна на выходе.
    raw = {"event_type": "forecast_compared", "timestamp": MY_TS_LEGACY,
           "payload": {"forecast_ids": ["f-1"]}}
    out = normalize_trace_event_dict(raw)
    raw["payload"]["forecast_ids"].append("f-2")
    assert out["payload"]["forecast_ids"] == ["f-1", "f-2"], (
        "ожидаемое (документируемое) поведение: вложенные структуры разделяются"
    )


def d5_canonical_passthrough() -> None:
    full = {
        "event_id": "e" * 32,
        "run_id": MY_RUN_ID,
        "ts": MY_TS_LEGACY,
        "stage": "validation",
        "node_id": "ranges",
        "event_type": "correction_applied",
        "payload": dict(MY_PAYLOAD_FACTS),
        "actor": "user",
    }
    assert normalize_trace_event_dict(full) == full


def d6_partial_canonical_defaults() -> None:
    out = normalize_trace_event_dict({"event_type": "run_paused", "ts": MY_TS_LEGACY})
    assert out["stage"] == "forecasting" and out["node_id"] is None
    assert out["actor"] == "user" and out["run_id"] == "" and out["event_id"]
    # канонический частичный словарь БЕЗ legacy-алиаса хранит явную стадию
    out2 = normalize_trace_event_dict({"event_type": "mode_changed", "ts": MY_TS_LEGACY, "stage": "validation"})
    assert out2["stage"] == "validation"


def d6b_legacy_alias_with_explicit_stage_characterization() -> None:
    # ХАРАКТЕРИЗАЦИЯ (см. акт сертификации, замечание R2): dict с legacy-алиасом
    # timestamp, но БЕЗ ts и С явной стадией -- стадия принудительно forecasting.
    raw = {"event_type": "correction_applied", "timestamp": MY_TS_LEGACY, "stage": "validation"}
    out = normalize_trace_event_dict(raw)
    assert out["stage"] == "forecasting", "ожидаемое (документируемое) поведение: явная стадия игнорируется при legacy-маркере"


def d7_unknown_stage_fails_closed_on_read() -> None:
    for bad_stage in ("bogus", "UPLOAD"):
        try:
            normalize_trace_event_dict({"event_type": "run_paused", "ts": MY_TS_LEGACY, "stage": bad_stage})
        except ValueError:
            continue
        raise AssertionError(f"стадия {bad_stage!r} не отклонена на границе чтения")


def d7b_event_type_not_validated_on_read_characterization() -> None:
    # ХАРАКТЕРИЗАЦИЯ (см. акт сертификации, замечание R3): normalize/from_dict
    # НЕ проверяют event_type по реестру -- stored-событие с опечаткой типа
    # проходит границу чтения. Fail-closed живёт только в фабрике.
    out = normalize_trace_event_dict({"event_type": "totally_unknown_type", "ts": MY_TS_LEGACY})
    assert out["event_type"] == "totally_unknown_type"


def d8_from_dict_roundtrip_all_stages() -> None:
    for stage, types in SPEC_TABLE.items():
        for et in sorted(types):
            node = MY_STAGES_NODES[stage]
            ev = make_trace_event(et, stage=stage, node_id=node, run_id=MY_RUN_ID, fact=1)
            assert TraceEvent.from_dict(ev.to_dict()) == ev
    for stage in SPEC_STAGES:
        for et in sorted(SPEC_RUN_LEVEL):
            ev = make_trace_event(et, stage=stage, run_id=MY_RUN_ID, comment="cert")
            assert TraceEvent.from_dict(ev.to_dict()) == ev


def d9_from_dict_legacy_exact() -> None:
    ev = TraceEvent.from_dict(
        {"event_type": "forecast_exported", "timestamp": MY_TS_LEGACY, "payload": {"format": "pdf"}},
        run_id=MY_RUN_ID,
    )
    assert ev.ts == MY_TS_LEGACY and ev.stage == "forecasting"
    assert ev.payload == {"format": "pdf"} and ev.run_id == MY_RUN_ID
    assert ev.event_type == "forecast_exported" and ev.actor == "user"


def d10_mixed_corpus_dual_write_invariant() -> None:
    # Смешанный корпус: legacy-популяция (4 события моего прогнозного прогона)
    # + канонические события. После нормализации и повторной сериализации
    # КАЖДОЕ событие несёт двойную запись ts==timestamp -- потребители
    # legacy-ключа (pydantic-схема, фронтенд) не видят разницы поколений.
    corpus: list[dict] = [
        {"event_type": "forecast_generated", "timestamp": "2026-09-21T07:45:11+00:00",
         "payload": {"horizon": 6, "alpha": 0.05}},
        {"event_type": "forecast_compared", "timestamp": "2026-09-21T07:46:30+00:00",
         "payload": {"forecast_ids": ["f-1", "f-2"]}},
        {"event_type": "forecast_sensitivity_computed", "timestamp": "2026-09-21T07:47:02+00:00",
         "payload": {"n_combos": 8}},
        {"event_type": "forecast_exported", "timestamp": "2026-09-21T07:48:45+00:00",
         "payload": {"format": "csv"}},
    ]
    canon_a = make_trace_event("run_paused", stage="modeling", run_id=MY_RUN_ID).to_dict()
    canon_b = make_trace_event("profile_viewed", stage="eda", node_id="seasonality").to_dict()
    normalized = [normalize_trace_event_dict(r, run_id=MY_RUN_ID) for r in corpus] + [canon_a, canon_b]
    for d in normalized:
        assert d["ts"] == d.get("timestamp") or "timestamp" not in d
        # через from_dict -> to_dict: алиас восстанавливается для ВСЕХ поколений
        redicted = TraceEvent.from_dict(d).to_dict()
        assert redicted["timestamp"] == redicted["ts"]
        ForecastTraceEventSchema(**redicted)  # HTTP-контракт цел для всего корпуса


# ── E. Обратная совместимость 4 вызовов Прогнозирования ───────────


def e1_call_sites_signature_compat() -> None:
    # Ровно сигнатуры 4 call-site routers/forecasting_session.py (мои значения):
    ev1 = make_trace_event(
        "forecast_generated", model_card_id="mc-77", forecast_id="f-77",
        model_id="ets", horizon=10, alpha=0.1, ci_method="analytic",
    )
    assert ev1.stage == "forecasting" and ev1.payload["model_id"] == "ets"
    ev2 = make_trace_event("forecast_exported", forecast_id="f-77", format="xlsx")
    assert ev2.payload["format"] == "xlsx"
    ev3 = make_trace_event("forecast_compared", forecast_ids=["f-1", "f-2"], model_card_ids=["mc-1"])
    assert ev3.payload["forecast_ids"] == ["f-1", "f-2"]
    ev4 = make_trace_event("forecast_sensitivity_computed", forecast_id="f-1", varied_axes=["horizon"], n_combos=4)
    assert ev4.payload["varied_axes"] == ["horizon"]
    for ev in (ev1, ev2, ev3, ev4):
        ForecastTraceEventSchema(**ev.to_dict())


def e2_payload_facts_not_raw_series() -> None:
    # §4.1: payload хранит факты решения, не сырые данные ряда.
    # Прогоняю большие числа как значения фактов -- контракт не ограничивает
    # размер, но сериализуемость и отсутствие DataFrame обязательны.
    big_fact = {"n_observations": 50000, "total_changed": 1234}
    ev = make_trace_event("correction_applied", stage="preprocessing", node_id="outliers", **big_fact)
    ev2 = make_trace_event("mode_changed", stage="validation", new_mode="auto")
    assert ev2.stage == "validation"
    d = ev.to_dict()
    assert json.dumps(d)  # сериализуемо
    import pandas as pd

    try:
        json.dumps(make_trace_event("forecast_generated", frame=pd.DataFrame({"x": [1]})).to_dict())
    except TypeError:
        pass  # DataFrame в payload невозможен по построению -- и не нужен
    else:
        raise AssertionError("DataFrame неожиданно сериализуем -- проверка утратила смысл")


def main() -> int:
    groups = [
        ("A1", "канон: 8 полей датакласса с точными значениями (мои данные)", a1_eight_fields_exact_values),
        ("A2", "event_id -- валидный UUID", a2_event_id_is_uuid),
        ("A3", "ts -- серверный ISO UTC, в границах момента фабрики", a3_ts_is_server_utc_iso),
        ("A4", "node_id=None для событий уровня стадии", a4_node_id_none_for_stage_level),
        ("A5", "actor по умолчанию 'user' (единственный вариант §4.1)", a5_actor_default_user),
        ("A6", "датакласс frozen -- иммутабельная трасса", a6_frozen_dataclass),
        ("A7", "дефолтный payload не разделяется между событиями", a7_default_payload_not_shared),
        ("A8", "legacy-алиас timestamp == ts", a8_legacy_alias_property),
        ("A9", "сweep дефолтов фабрики (run_id/stage/node_id/actor/payload)", a9_defaults_sweep),
        ("B1", "реестр == таблице §4.1 дословно, run-level не вплавлены", b1_registry_matches_spec_table_exactly),
        ("B2", "run-level типы валидны на любой из 6 стадий", b2_run_level_valid_on_any_stage),
        ("B3", "fail-closed: неизвестный event_type на всех стадиях", b3_unknown_event_type_fails_closed),
        ("B4", "fail-closed: валидный тип на чужой стадии", b4_valid_type_on_wrong_stage_fails_closed),
        ("B5", "fail-closed: неизвестная стадия (включая регистр/пустую)", b5_unknown_stage_fails_closed),
        ("B6", "KNOWN_STAGES == STAGES §2 == стадиям реестра", b6_known_stages_equal_spec_stages),
        ("B7", "исчерпывающий позитивный обход всего реестра", b7_exhaustive_positive_sweep),
        ("C1", "to_dict: ровно 9 ключей (8 канон + timestamp)", c1_dict_keys_nine_with_alias),
        ("C2", "to_dict: алиас == ts, типы полей", c2_alias_equals_ts_in_dict),
        ("C3", "to_dict: JSON-сериализуемость туда-обратно", c3_json_roundtrip),
        ("C4", "pydantic-контракт цел для всего реестра (двойная запись)", c4_pydantic_http_contract_intact),
        ("C5", "to_dict: плоский payload изолирован в обе стороны", c5_flat_payload_independence),
        ("C5b", "характеристика R1: вложенный payload разделяется (мелкая копия)", c5b_nested_payload_sharing_characterization),
        ("D1", "legacy 3 поля -> канон 8 полей (мои timestamps)", d1_legacy_three_fields_to_canonical),
        ("D2", "run_id: прикрепление при отсутствии, приоритет своего", d2_run_id_attach_and_priority),
        ("D3", "нормализация идемпотентна (legacy и канон)", d3_normalization_idempotent),
        ("D4", "вход не мутируется; плоский payload изолирован в обе стороны", d4_input_not_mutated_and_flat_payload_isolated),
        ("D4b", "характеристика R1b: вложенный payload нормы разделяется с входом", d4b_nested_payload_shared_with_input_characterization),
        ("D5", "канонический словарь -- pass-through без изменений", d5_canonical_passthrough),
        ("D6", "частичный канон: дефолты без выдуманных данных", d6_partial_canonical_defaults),
        ("D6b", "характеристика R2: legacy-алиас + явная stage -> forecasting", d6b_legacy_alias_with_explicit_stage_characterization),
        ("D7", "fail-closed чтения: неизвестная стадия отклоняется", d7_unknown_stage_fails_closed_on_read),
        ("D7b", "характеристика R3: event_type не валидируется на чтении", d7b_event_type_not_validated_on_read_characterization),
        ("D8", "from_dict(to_dict(e)) == e для всего реестра + run-level", d8_from_dict_roundtrip_all_stages),
        ("D9", "from_dict legacy: точное восстановление полей", d9_from_dict_legacy_exact),
        ("D10", "смешанный корпус: инвариант двойной записи для всех поколений", d10_mixed_corpus_dual_write_invariant),
        ("E1", "сигнатуры 4 call-site Прогнозирования совместимы + pydantic", e1_call_sites_signature_compat),
        ("E2", "payload -- факты решения, JSON-сериализуемые (§4.1)", e2_payload_facts_not_raw_series),
    ]
    for oid, desc, fn in groups:
        check(oid, desc, fn)

    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    failed = len(RESULTS) - passed
    print(f"\n=== ORACLE SUMMARY: {passed} PASS / {failed} FAIL из {len(RESULTS)} ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
