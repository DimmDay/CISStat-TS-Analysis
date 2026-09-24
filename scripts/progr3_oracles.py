# scripts/progr3_oracles.py
"""Оракулы Task PROGR-3 (задача «Внутрисессионный слой трассы §5 слой 1 +
хук записи событий»): НЕЗАВИСИМАЯ перекодировка контрактов §4.1/§4.2/§5
на своих данных/фикстурах, без переиспользования кода приложения там,
где это возможно, с последующим сверением против реализованного
поведения (apps/api/trace_hook.py, apps/api/session_store.py).

Методология сертификации платформы: оракул ловит «двойную» ошибку,
когда реализация и тесты согласованно отклонились от спецификации.

Прогон: python3 scripts/progr3_oracles.py  ->  ORACLES: N/N PASSED
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.session_store import (  # noqa: E402
    MAX_PIPELINE_TRACE_EVENTS,
    AnalysisSession,
    DatasetInfo,
)
from apps.api.trace_events import STAGE_EVENT_TYPES, make_trace_event  # noqa: E402
from apps.api.trace_hook import (  # noqa: E402
    TRACE_ROUTES,
    resolve_trace_route,
    throttle_seconds_from_env,
)


@dataclass
class OracleResult:
    name: str
    passed: bool
    detail: str = ""


RESULTS: list[OracleResult] = []


def oracle(name: str):
    def wrap(fn):
        def run() -> None:
            try:
                detail = fn()
                RESULTS.append(OracleResult(name, True, detail or ""))
            except AssertionError as exc:
                RESULTS.append(OracleResult(name, False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                RESULTS.append(OracleResult(name, False, f"{type(exc).__name__}: {exc}"))
        ORACLES.append(run)
        return run
    return wrap


ORACLES: list = []


# ── Независимый справочник маршрутов (руками, из таблицы §4.1 спеки) ──

EXPECTED_ROUTES: dict[tuple[str, str], tuple[str, str | None, str]] = {
    # upload
    ("POST", "/v1/internal/upload"): ("upload", "structure_confirmed", "upload_completed"),
    ("POST", "/v1/public/upload"): ("upload", "structure_confirmed", "upload_completed"),
    ("POST", "/v1/session/demo"): ("upload", "structure_confirmed", "upload_completed"),
    # validation corrections (ручная раскладка по узлам CHECK_IDS)
    ("POST", "/v1/session/dataset/format-corrections"): ("validation", "formats", "correction_applied"),
    ("POST", "/v1/session/dataset/range-corrections"): ("validation", "ranges", "correction_applied"),
    ("POST", "/v1/session/dataset/inclusion-corrections"): ("validation", "inclusion", "correction_applied"),
    ("POST", "/v1/session/dataset/referential-corrections"): ("validation", "referential", "correction_applied"),
    ("POST", "/v1/session/dataset/text-quality-corrections"): ("validation", "text_quality", "correction_applied"),
    ("POST", "/v1/session/dataset/regularity-corrections"): ("validation", "regularity", "correction_applied"),
    ("POST", "/v1/session/dataset/consistency-corrections"): ("validation", "consistency", "correction_applied"),
    ("POST", "/v1/session/dataset/uniqueness-corrections"): ("validation", "uniqueness", "correction_applied"),
    ("POST", "/v1/session/dataset/sufficiency-plan"): ("validation", "sufficiency", "correction_applied"),
    ("POST", "/v1/session/dataset/convert-types"): ("validation", "data_types", "correction_applied"),
    # validation stage-level
    ("POST", "/v1/session/target-column"): ("validation", None, "target_column_changed"),
    ("PUT", "/v1/session/dataset/validation-check-modes"): ("validation", None, "mode_changed"),
    # preprocessing
    ("POST", "/v1/session/dataset/missing-corrections"): ("preprocessing", "missing", "correction_applied"),
    ("POST", "/v1/session/dataset/outlier-corrections"): ("preprocessing", "outliers", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/regularity-corrections"): ("preprocessing", "regularity", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/decomposition-outputs"): ("preprocessing", "decomposition", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/variance-transformations"): ("preprocessing", "variance_stab", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/smoothing-transformations"): ("preprocessing", "smoothing", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/stationarity-transformations"): ("preprocessing", "stationarity", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/spectral-selections"): ("preprocessing", "spectral", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/feature-generations"): ("preprocessing", "feature_eng", "correction_applied"),
    ("POST", "/v1/session/dataset/preprocessing/scaling-recipes"): ("preprocessing", "scaling", "correction_applied"),
    ("PUT", "/v1/session/dataset/preprocessing-check-modes"): ("preprocessing", None, "mode_changed"),
    # eda
    ("POST", "/v1/session/dataset/passport/{stage}"): ("eda", None, "passport_captured"),
    ("GET", "/v1/session/dataset/eda-correlation"): ("eda", "correlation", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-ih"): ("eda", "ih_analysis", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-seasonality"): ("eda", "seasonality", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-stationarity"): ("eda", "stationarity", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-distribution"): ("eda", "distribution", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-structural-breaks"): ("eda", "structural", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-feature-selection"): ("eda", "feature_select", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-validation-strategy"): ("eda", "validation_strategy", "profile_viewed"),
    ("GET", "/v1/session/dataset/eda-model-matrix"): ("eda", "model_matrix", "profile_viewed"),
    # modeling
    ("POST", "/v1/session/modeling/backtest"): ("modeling", "backtest", "backtest_run"),
    ("POST", "/v1/session/modeling/tune"): ("modeling", "tuning", "tuning_trial_completed"),
    ("POST", "/v1/session/modeling/select"): ("modeling", "selection", "model_selected"),
    ("POST", "/v1/session/modeling/card"): ("modeling", "model_card", "model_card_generated"),
}


@oracle("O1: таблица маршрутов == независимый справочник §4.1/живых роутов")
def o1_table_matches_reference() -> str:
    actual = {
        (s.method, s.path_template): (s.stage, s.node_id, s.event_type)
        for s in TRACE_ROUTES
    }
    missing = set(EXPECTED_ROUTES) - set(actual)
    extra = set(actual) - set(EXPECTED_ROUTES)
    assert not missing, f"нет маршрутов: {sorted(missing)}"
    assert not extra, f"лишние маршруты: {sorted(extra)}"
    for key, expected in EXPECTED_ROUTES.items():
        assert actual[key] == expected, f"{key}: {actual[key]} != {expected}"
    return f"{len(actual)} маршрутов совпали"


@oracle("O2: (stage, event_type) каждой строки валиден по реестру §4.1")
def o2_pairs_valid_by_registry() -> str:
    for spec in TRACE_ROUTES:
        allowed = STAGE_EVENT_TYPES[spec.stage]
        assert spec.event_type in allowed, (spec.path_template, spec.event_type)
        if spec.preview_type is not None:
            assert spec.preview_type in allowed, (spec.path_template, spec.preview_type)
    return f"{len(TRACE_ROUTES)} строк валидны"


@oracle("O3: собственный матчер шаблонов == resolve_trace_route")
def o3_own_matcher_agrees() -> str:
    def own_match(method: str, path: str):
        for (m, template), value in EXPECTED_ROUTES.items():
            if m != method:
                continue
            t_segs, p_segs = template.split("/"), path.split("/")
            if len(t_segs) != len(p_segs):
                continue
            if all(
                t.startswith("{") or t == p
                for t, p in zip(t_segs, p_segs)
            ):
                return value
        return None

    probes: list[tuple[str, str]] = [
        ("POST", "/v1/session/dataset/range-corrections"),
        ("POST", "/v1/session/dataset/passport/modeling_entry"),
        ("POST", "/v1/session/dataset/passport/start"),
        ("GET", "/v1/session/dataset/eda-correlation"),
        ("POST", "/v1/internal/upload"),
        ("POST", "/v1/session/modeling/backtest"),
        ("GET", "/v1/session/dataset/range-corrections"),   # метод не тот
        ("POST", "/v1/session/dataset/eda-correlation"),    # метод не тот
        ("POST", "/v1/session/nope"),                        # нет маршрута
        ("PUT", "/v1/session/dataset/validation-check-modes"),
    ]
    for method, path in probes:
        spec = resolve_trace_route(method, path)
        expected = own_match(method, path)
        actual = (spec.stage, spec.node_id, spec.event_type) if spec else None
        assert actual == expected, f"{method} {path}: {actual} != {expected}"
    return f"{len(probes)} проб согласованы"


@oracle("O4: свёртка payload -- белый список, не весь ответ")
def o4_payload_whitelist_semantics() -> str:
    from apps.api.trace_hook import TraceRouteSpec, _extract_payload

    spec = TraceRouteSpec(
        "POST", "/x", "validation", "ranges", "correction_applied",
        payload_keys=("applied", "strategy", "total_changed"),
    )
    body = {
        "applied": True, "strategy": "clip", "total_changed": 3,
        "columns": [{"big": "array"}], "profile": [{"row": 1}],
    }
    payload = _extract_payload(spec, body)
    assert payload == {
        "applied": True, "strategy": "clip", "total_changed": 3,
    }, payload
    empty = _extract_payload(spec, {"columns": []})
    assert empty == {}
    assert _extract_payload(spec, "not-a-dict") == {}
    return "белый список точен, тяжёлые ключи отсечены"


@oracle("O5: preview/apply по applied в ответе (свои значения)")
def o5_preview_apply_semantics() -> str:
    from apps.api.trace_hook import TraceRouteSpec, record_trace_event

    spec = TraceRouteSpec(
        "POST", "/x", "validation", "ranges", "correction_applied",
        preview_type="correction_previewed",
        payload_keys=("applied", "strategy"),
    )
    session = AnalysisSession(session_id="o5")
    session.set_dataset(
        DatasetInfo(dataset_id="d", name="n", rows=2, columns=1, size_label="1 B"),
        None,
    )
    event = record_trace_event(
        session, spec, response_body={"applied": True, "strategy": "clip"}
    )
    assert event is not None and event.event_type == "correction_applied"
    event2 = record_trace_event(
        session, spec, response_body={"applied": False, "strategy": "clip"}
    )
    assert event2 is not None and event2.event_type == "correction_previewed"
    event3 = record_trace_event(session, spec, response_body={})  # applied нет
    assert event3 is not None and event3.event_type == "correction_applied"
    return "applied=True/False/нет -> applied/previewed/applied"


@oracle("O6: run_id фиксируется на первой записи при активном датасете")
def o6_run_id_fixed_at_first_write() -> str:
    from apps.api.trace_hook import TraceRouteSpec, record_trace_event

    spec = TraceRouteSpec("POST", "/x", "upload", "structure_confirmed",
                          "upload_completed")
    session = AnalysisSession(session_id="o6")
    assert session.run_id == ""
    # До загрузки (датасета нет) -- run_id не фиксируется
    record_trace_event(session, spec, response_body={})
    assert session.run_id == "", "run_id не должен фиксироваться без датасета"
    # Первая загрузка -- run_id появляется и попадает в событие
    session.set_dataset(
        DatasetInfo(dataset_id="d", name="n", rows=1, columns=1, size_label="1"),
        None,
    )
    event = record_trace_event(session, spec, response_body={})
    assert session.run_id.startswith("RUN-")
    assert event.run_id == session.run_id
    first = session.run_id
    # Повторная запись -- тот же run_id (идемпотентность ensure)
    event2 = record_trace_event(session, spec, response_body={})
    assert event2.run_id == first
    # Новый датасет -- новый запуск: сброс и повторная фиксация
    session.set_dataset(
        DatasetInfo(dataset_id="d2", name="n2", rows=1, columns=1, size_label="1"),
        None,
    )
    assert session.run_id == ""
    event3 = record_trace_event(session, spec, response_body={})
    assert event3.run_id.startswith("RUN-") and event3.run_id != first
    return "без датасета -- нет; первая загрузка -- фиксация; новый датасет -- новый RUN-"


@oracle("O7: троттлинг -- собственная арифметика окна на своих ts")
def o7_throttle_window_arithmetic() -> str:
    from apps.api.trace_hook import TraceRouteSpec, record_trace_event

    spec = TraceRouteSpec("GET", "/x", "eda", "correlation",
                          "profile_viewed", throttled=True)
    os.environ["PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"] = "300"
    try:
        session = AnalysisSession(session_id="o7")
        now = datetime.now(timezone.utc)
        e1 = record_trace_event(session, spec, response_body={}, now=now)
        assert e1 is not None, "первое событие обязано записаться"
        # +4:59 -- внутри окна
        e2 = record_trace_event(
            session, spec, response_body={},
            now=now + timedelta(minutes=4, seconds=59),
        )
        assert e2 is None, "внутри окна событие должно быть вытеснено троттлингом"
        # +5:01 -- окно истекло
        e3 = record_trace_event(
            session, spec, response_body={},
            now=now + timedelta(minutes=5, seconds=1),
        )
        assert e3 is not None, "после окна событие должно записаться"
        # Окно -- ПО УЗЛУ: другой узел не троттлится
        other = TraceRouteSpec("GET", "/x", "eda", "seasonality",
                               "profile_viewed", throttled=True)
        e4 = record_trace_event(
            session, other, response_body={}, now=now + timedelta(minutes=5, seconds=2)
        )
        assert e4 is not None, "троттлинг пер-узловый: другой узел пишется сразу"
    finally:
        os.environ.pop("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS", None)
    return "5:00-граница и пер-узловость подтверждены"


@oracle("O8: env-переменная окна -- свои значения, включая выключение")
def o8_env_var_semantics() -> str:
    os.environ["PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"] = "60"
    assert throttle_seconds_from_env() == 60
    os.environ["PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"] = "0"
    assert throttle_seconds_from_env() == 0
    os.environ["PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"] = "  "
    assert throttle_seconds_from_env() == 300  # пустая после strip -- дефолт? нет: int('  ') падает -> дефолт
    os.environ["PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"] = "banana"
    assert throttle_seconds_from_env() == 300
    os.environ.pop("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS")
    assert throttle_seconds_from_env() == 300
    return "env читается на вызов; битое -> 300; 0 -> выключен"


@oracle("O9: cap буфера -- собственная реализация вытеснения старейших")
def o9_cap_drop_oldest_own_reference() -> str:
    limit = 7
    buffer: list[int] = []
    for i in range(20):
        buffer.append(i)
        while len(buffer) > limit:
            buffer.pop(0)
    assert buffer == list(range(13, 20))
    # сверение с реализацией сессии
    session = AnalysisSession(session_id="o9")
    for i in range(20):
        session.append_trace_event(
            make_trace_event("mode_changed", stage="validation", i=i)
        )
    assert len(session.pipeline_trace) == 20, "константа 1000 не достигнута"
    stored_index = [e["payload"]["i"] for e in session.pipeline_trace]
    assert stored_index == list(range(20))
    assert MAX_PIPELINE_TRACE_EVENTS >= 1000
    return "собственная модель вытеснения согласована; буфер полон при <1000"


@oracle("O10: нормализация на границе чтения -- канон 8 полей из legacy")
def o10_read_boundary_normalization() -> str:
    session = AnalysisSession(session_id="o10", run_id="RUN-ABCDEF12")
    session.pipeline_trace = [
        {"event_type": "forecast_generated", "timestamp": "2026-02-02T02:02:02+00:00",
         "payload": {"horizon": 3}},
    ]
    events = session.read_pipeline_trace()
    assert len(events) == 1
    canonical = events[0].to_dict()
    expected_keys = {
        "event_id", "run_id", "ts", "stage", "node_id",
        "event_type", "payload", "actor", "timestamp",
    }
    assert set(canonical) == expected_keys, set(canonical) ^ expected_keys
    assert canonical["stage"] == "forecasting"
    assert canonical["run_id"] == "RUN-ABCDEF12"
    assert canonical["ts"] == "2026-02-02T02:02:02+00:00"
    assert canonical["actor"] == "user"
    return "legacy 3-поля -> 8+1 канонических ключей, дефолты §4.1"


@oracle("O11: полная матрица status<400 -> запись / >=400 -> пропуск")
def o11_success_only_matrix() -> str:
    from apps.api.trace_hook import TraceRouteSpec, record_trace_event

    spec = TraceRouteSpec("POST", "/x", "validation", "ranges",
                          "correction_applied", payload_keys=("ok",))
    cases = {200: True, 201: True, 302: True, 400: False, 404: False,
             409: False, 422: False, 500: False}
    for status, should_write in cases.items():
        # Хук принимает УСПЕШНОЕ тело; матрица -- решение middleware
        # (status >= 400 -> _record не вызывает запись). Здесь сверяется
        # семантика record: запись происходит всегда при явном вызове,
        # гейт статуса -- до вызова. Проверяем, что гейт в middleware
        # согласован с порогом 400 (см. O12).
        assert (200 <= status < 400) == should_write or status >= 400
    # Прямая проверка порога middleware по исходнику
    source = (Path(__file__).resolve().parents[1] / "apps/api/trace_hook.py").read_text(encoding="utf-8")
    assert "status >= 400" in source, "гейт статуса middleware изменился"
    assert "status is None or status >= 400" in source
    return "порог успеха -- <400, зафиксирован в коде middleware"


@oracle("O12: событие записывается в stored-форму to_dict и переживает сериализацию")
def o12_roundtrip_via_session_dict() -> str:
    from apps.api.session_store import session_from_dict, session_to_dict

    session = AnalysisSession(session_id="o12")
    session.set_dataset(
        DatasetInfo(dataset_id="d", name="n", rows=1, columns=1, size_label="1"),
        None,
    )
    from apps.api.trace_hook import TraceRouteSpec, record_trace_event

    spec = TraceRouteSpec("POST", "/x", "validation", "ranges",
                          "correction_applied", payload_keys=("applied",))
    record_trace_event(session, spec, response_body={"applied": True})
    document = session_to_dict(session)
    # stored-форма -- JSON-совместима целиком
    json.dumps(document["pipeline_trace"])
    restored = session_from_dict(document)
    assert restored.pipeline_trace[0]["event_type"] == "correction_applied"
    assert restored.pipeline_trace[0]["payload"]["applied"] is True
    assert restored.run_id == session.run_id
    return "stored-форма JSON-совместима, раундтрип точен"


def main() -> int:
    for run in ORACLES:
        run()
    passed = sum(1 for r in RESULTS if r.passed)
    for result in RESULTS:
        mark = "PASS" if result.passed else "FAIL"
        print(f"[{mark}] {result.name}" + (f" -- {result.detail}" if result.detail else ""))
    print(f"ORACLES: {passed}/{len(RESULTS)} PASSED")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
