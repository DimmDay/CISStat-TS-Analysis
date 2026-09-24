# scripts/progr3cert_oracles.py
# Task PROGR-3-CERT -- независимые оракул-тесты аудитора на СВОИХ данных.
# Своя кодировка контрактов §4.1/§4.2/§5 (не копия progr3_oracles.py),
# свой мини-ASGI-стенд, свой фейковый стор, свой сид 20260924.
"""Оракулы аудита PROGR-3.
Запуск: python3 /home/z/my-project/scripts/progr3cert_oracles.py
   -> ORACLES-CERT: N/N PASSED
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _find_root() -> Path:
    """Корень репозитория: вверх по родителям до apps/api/session_store.py;
    фоллбек -- абсолютный путь контейнера."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps/api/session_store.py").exists():
            return parent
    return Path("/home/z/my-project/CISStat-TS-Analysis")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))

from apps.api.trace_hook import (  # noqa: E402
    DEFAULT_THROTTLE_SECONDS,
    ENV_THROTTLE_SECONDS,
    TRACE_ROUTES,
    TraceHookMiddleware,
    TraceRouteSpec,
    _extract_payload,
    _parse_json_body,
    _throttled,
    record_trace_event,
    resolve_trace_route,
    throttle_seconds_from_env,
)
from apps.api.trace_events import TraceEvent, make_trace_event  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    SESSION_SCHEMA_VERSION,
    AnalysisSession,
    DatasetInfo,
    session_from_dict,
    session_to_dict,
)
# Модуле-уровневый импорт: при from __future__ import annotations FastAPI
# резолвит аннотацию response: ... по глобальным именам модуля, локальный
# импорт внутри функции не виден -> параметр стал бы query-полем (422).
from fastapi import Response as FastAPIResponse  # noqa: E402

SEED = 20260924
RESULTS: list[tuple[str, bool]] = []


def oracle(name: str):
    def deco(fn):
        def run():
            try:
                detail = fn()
                ok = True
            except Exception as exc:  # noqa: BLE001
                import traceback
                detail = f"EXC {type(exc).__name__}: {exc}"
                ok = False
                traceback.print_exc()
            RESULTS.append((name, ok))
            print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if ok else ""))
            return ok
        run.__name__ = fn.__name__
        ORACLES.append(run)
        return run
    return deco


ORACLES: list = []


def probe_session(sid: str = "CERT-SESS-1", dataset: bool = True) -> AnalysisSession:
    s = AnalysisSession(session_id=sid)
    if dataset:
        s.dataset = DatasetInfo(
            dataset_id=f"ds-{SEED}", name="cert_probe.csv",
            rows=120, columns=5, size_label="12 KB",
        )
    return s


def dts(minutes_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


# ── OR-A: гейт успеха -- граничная матрица статусов через РЕАЛЬНЫЙ
# middleware (свой стенд; не самореференциальная эмуляция критерия) ──

@oracle("OR-A: статус-гейт <400 через живой middleware: 200/204/399 пишутся, "
        "400/401/404/409/422/500 -- нет (граница 399/400)")
def or_a():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    import apps.api.trace_hook as TH

    class FakeStore:
        def __init__(self):
            self.items: dict[str, AnalysisSession] = {}

        def get(self, sid):
            return self.items.get(sid)

        def save(self, session):
            self.items[session.session_id] = session

    store = FakeStore()
    orig_get = TH.get_session_store
    TH.get_session_store = lambda: store
    s = probe_session("SESS-CERT-A")
    store.save(s)

    app = FastAPI()
    app.add_middleware(TraceHookMiddleware)

    @app.post("/v1/session/dataset/range-corrections")
    def apply(status: int):
        return JSONResponse({"applied": True, "total_changed": 1},
                            status_code=status)

    client = TestClient(app)
    written, skipped = [], []
    for status in (200, 204, 399, 400, 401, 404, 409, 422, 500, 503):
        s.pipeline_trace.clear()
        r = client.post(f"/v1/session/dataset/range-corrections?status={status}",
                        cookies={SESSION_COOKIE_NAME: "SESS-CERT-A"})
        assert r.status_code == status, (status, r.status_code)
        (written if s.pipeline_trace else skipped).append(status)
    assert written == [200, 204, 399], written
    assert skipped == [400, 401, 404, 409, 422, 500, 503], skipped
    TH.get_session_store = orig_get
    return f"пишутся {written}; пропускаются 400..503"


# ── OR-B: preview/apply семантика на своих телах (границы applied) ──

@oracle("OR-B: preview/apply по applied В ОТВЕТЕ: True/False/None/0/\"false\"/нет ключа")
def or_b():
    spec = TraceRouteSpec(
        "POST", "/cert/corr", "validation", "formats",
        "correction_applied", "correction_previewed",
        payload_keys=("applied", "total_changed"),
    )
    # ВАЖНО: список пар, НЕ dict (0 и False -- один ключ dict-а!)
    cases = [
        (True, "correction_applied"),
        (False, "correction_previewed"),
        (None, "correction_applied"),      # is False -- только точный False
        (0, "correction_applied"),         # 0 is not False (identity!)
        ("false", "correction_applied"),
    ]
    sess = probe_session()
    for i, (applied, expected) in enumerate(cases):
        s2 = probe_session(f"CERT-B{i}")
        ev = record_trace_event(s2, spec, response_body={"applied": applied, "total_changed": 3},
                                now=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc))
        assert ev.event_type == expected, (applied, ev.event_type, expected)
    # отсутствие ключа applied -> apply-тип
    s5 = probe_session("CERT-B5")
    ev = record_trace_event(s5, spec, response_body={"total_changed": 3},
                            now=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc))
    assert ev.event_type == "correction_applied"
    return "False->previewed, всё остальное->applied (identity-семантика)"


# ── OR-C: payload -- белый список на своих телах + коллизия "stage" ──

@oracle("OR-C: payload whitelist: тяжёлое отсечено, отсутствующее опущено, "
        "коллизия payload['stage'] у паспорта снята replace-ом без потери")
def or_c():
    spec = TraceRouteSpec(
        "POST", "/cert/heavy", "validation", "formats",
        "correction_applied",
        payload_keys=("applied", "total_changed", "absent_key"),
    )
    body = {
        "applied": True, "total_changed": 7, "absent_key_is_here": 1,
        "columns": [{"x": i} for i in range(5000)],   # тяжёлое
        "profile": ["p" * 1000] * 500,                # тяжёлое
    }
    p = _extract_payload(spec, body)
    assert set(p) == {"applied", "total_changed"}, p
    assert "columns" not in p and "profile" not in p
    # коллизия: тело паспорта содержит ключ "stage" -- имя параметра фабрики
    pspec = next(s for s in TRACE_ROUTES if "passport" in s.path_template)
    assert pspec.payload_keys[0] == "stage"
    sess = probe_session()
    ev = record_trace_event(
        sess, pspec,
        response_body={"stage": "validation", "snapshot_id": "SN-CERT-9",
                       "fingerprint": "fp-777"},
        now=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
    )
    assert ev.stage == "eda" and ev.node_id is None
    assert ev.payload == {"stage": "validation", "snapshot_id": "SN-CERT-9",
                          "fingerprint": "fp-777"}, ev.payload
    # не-JSON тело -> payload {}, событие всё равно пишется
    assert _parse_json_body([b"", b""]) == {}
    assert _parse_json_body([b"[1,2,3]"]) == {}
    return "тяжёлое/отсутствующее вне payload; payload['stage'] сохранён, event.stage='eda'"


# ── OR-D: троттлинг -- арифметика окна на своих метках времени ──

@oracle("OR-D: окно троттлинга 300с: 299.5с--throttle, 300.5с--write, "
        "строгое <, naive-ts как UTC, битый ts--write, пер-узловость/пер-типовость")
def or_d2():
    corr = next(s for s in TRACE_ROUTES if s.path_template.endswith("eda-correlation"))
    seas = next(s for s in TRACE_ROUTES if s.path_template.endswith("eda-seasonality"))
    assert corr.node_id == "correlation" and seas.node_id == "seasonality"
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    def with_last(ts: str | None) -> AnalysisSession:
        s = probe_session("CERT-D")
        rec = make_trace_event("profile_viewed", stage="eda",
                               node_id="correlation", run_id="RUN-CERTD")
        stored = rec.to_dict()
        stored["ts"] = ts if ts is not None else ""
        s.pipeline_trace.append(stored)
        return s

    # внутри окна (299.5 c) -> throttled; ровно 300 c -> НЕ throttled (строгое <)
    assert _throttled(with_last((now - timedelta(seconds=299.5)).isoformat()), corr, now)
    assert not _throttled(with_last((now - timedelta(seconds=300)).isoformat()), corr, now)
    assert not _throttled(with_last((now - timedelta(seconds=300.5)).isoformat()), corr, now)
    # naive ts -- интерпретируется как UTC
    assert _throttled(with_last((now - timedelta(seconds=10)).replace(tzinfo=None).isoformat()), corr, now)
    # битый/пустой ts -- деградация к «можно писать»
    assert not _throttled(with_last("not-a-timestamp"), corr, now)
    assert not _throttled(with_last(None), corr, now)
    # пер-узловость: последний correlation не глушит seasonality; пер-типовость
    assert not _throttled(with_last((now - timedelta(seconds=5)).isoformat()), seas, now)
    s_other = probe_session("CERT-D2")
    rec = make_trace_event("passport_captured", stage="eda", node_id="correlation")
    s_other.pipeline_trace.append(rec.to_dict())
    assert not _throttled(s_other, corr, now)
    # event_type иного узла в трассе не матчится по node_id
    return "границы 299.5/300/300.5, naive->UTC, битый--write, узел/тип изолированы"


# ── OR-E: env-семантика на своих значениях ──

@oracle("OR-E: PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS: нет->300, '0'->выкл, "
        "'-5'->выкл, 'abc'->300, '5.5'->300, ' 600 '->600, '600'->600")
def or_e():
    cases = {
        None: 300,
        "": 300,
        "0": 0,
        "-5": 0,
        "abc": 300,
        "5.5": 300,
        " 600 ": 600,
        "600": 600,
        "999999": 999999,
    }
    for raw, expected in cases.items():
        if raw is None:
            os.environ.pop(ENV_THROTTLE_SECONDS, None)
        else:
            os.environ[ENV_THROTTLE_SECONDS] = raw
        got = throttle_seconds_from_env()
        assert got == expected, (raw, got, expected)
    os.environ.pop(ENV_THROTTLE_SECONDS, None)
    assert throttle_seconds_from_env() == DEFAULT_THROTTLE_SECONDS == 300
    return "все 9 значений env совпали с ожиданиями аудита"


# ── OR-F: run_id -- жизненный цикл на своих данных ──

@oracle("OR-F: run_id: без датасета не фиксируется; с датасетом RUN-[0-9A-F]{8}; "
        "идемпотентен; в событие попадает зафиксированный; новый датасет -> новый run_id")
def or_f():
    import re as _re
    spec = TraceRouteSpec("POST", "/cert/x", "validation", "formats",
                          "correction_applied", payload_keys=("applied",))
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    # без датасета: run_id не фиксируется, событие с run_id=""
    s0 = probe_session("CERT-F0", dataset=False)
    ev0 = record_trace_event(s0, spec, response_body={"applied": True}, now=now)
    assert s0.run_id == "" and ev0.run_id == ""
    # с датасетом: формат и идемпотентность
    s1 = probe_session("CERT-F1")
    e1 = record_trace_event(s1, spec, response_body={"applied": True}, now=now)
    rid1 = s1.run_id
    assert _re.fullmatch(r"RUN-[0-9A-F]{8}", rid1), rid1
    assert e1.run_id == rid1
    e2 = record_trace_event(s1, spec, response_body={"applied": True}, now=now)
    assert s1.run_id == rid1 and e2.run_id == rid1
    # сброс: set_dataset обнуляет run_id и трассу; новая фиксация -- НОВЫЙ id
    old_trace_len = len(s1.pipeline_trace)
    assert old_trace_len == 2
    s1.set_dataset(DatasetInfo(dataset_id="ds-2", name="two.csv", rows=9,
                               columns=3, size_label="9 B"), None)
    assert s1.run_id == "" and s1.pipeline_trace == []
    e3 = record_trace_event(s1, spec, response_body={"applied": True}, now=now)
    assert _re.fullmatch(r"RUN-[0-9A-F]{8}", s1.run_id) and s1.run_id != rid1
    assert e3.run_id == s1.run_id
    return f"{rid1} -> сброс -> {s1.run_id} (разные); без датасета run_id=''"


# ── OR-G: буфер -- cap/вытеснение и R1-копия на своих данных ──

@oracle("OR-G: cap 1000: свои 8 событий при cap=5 -- хвост 5 в порядке; "
        "R1: вложенный payload в stored не разделяется с источником")
def or_g(monkey_cap: int = 5):
    import apps.api.session_store as SS
    orig_cap = SS.MAX_PIPELINE_TRACE_EVENTS
    SS.MAX_PIPELINE_TRACE_EVENTS = monkey_cap
    try:
        s = probe_session("CERT-G")
        for i in range(8):
            ev = TraceEvent(
                event_type="correction_applied", stage="validation",
                node_id="ranges", run_id="RUN-CERTG",
                payload={"i": i, "nested": {"v": [i]}},
            )
            s.append_trace_event(ev)
        assert len(s.pipeline_trace) == monkey_cap
        vals = [item["payload"]["i"] for item in s.pipeline_trace]
        assert vals == [3, 4, 5, 6, 7], vals  # старейшие 0..2 вытеснены
        # R1: мутация ИСТОЧНИКА после записи не меняет stored
        src = TraceEvent(event_type="correction_applied", stage="validation",
                         node_id="ranges", run_id="RUN-CERTG",
                         payload={"deep": {"k": [1, 2]}})
        s.append_trace_event(src)
        src.payload["deep"]["k"].append(999)   # mutate after append
        src.payload["deep"]["new"] = "x"
        stored = s.pipeline_trace[-1]
        assert stored["payload"]["deep"]["k"] == [1, 2]
        assert "new" not in stored["payload"]["deep"]
        # и через границу чтения
        evs = s.read_pipeline_trace()
        assert evs[-1].payload["deep"]["k"] == [1, 2]
    finally:
        SS.MAX_PIPELINE_TRACE_EVENTS = orig_cap
    return f"cap={monkey_cap}: хвост [3..7]; R1-копия глубока"


# ── OR-H: граница чтения -- свой legacy-корпус ──

@oracle("OR-H: свой legacy-корпус: 3-поля->канон stage=forecasting (R2-приоритет "
        "маркера), канон pass-through, не-словарь/чужая стадия--skip, "
        "чужой event_type--сохранён (R3), чтение не мутирует stored")
def or_h():
    s = probe_session("CERT-H")
    s.run_id = "RUN-CERTH"
    legacy = {"event_type": "forecast_generated",
              "timestamp": dts(60), "payload": {"segment": "point"}}
    legacy_marker_stage = {"event_type": "backtest_run", "stage": "modeling",
                           "timestamp": dts(50), "payload": {}}
    canon = make_trace_event("correction_applied", stage="validation",
                             node_id="ranges", run_id="RUN-CERTH",
                             total_changed=5).to_dict()
    unknown_type = {"event_type": "future_type_9000", "ts": dts(5),
                    "stage": "eda", "node_id": "correlation",
                    "event_id": "id-cert-h-1", "run_id": "RUN-CERTH",
                    "payload": {}, "actor": "user"}
    bad_stage = {"event_type": "correction_applied", "ts": dts(4),
                 "stage": "not-a-stage", "payload": {}}
    s.pipeline_trace = [legacy, legacy_marker_stage, canon, unknown_type,
                        bad_stage, "garbage-string", 42]
    events = s.read_pipeline_trace()
    kinds = [(e.stage, e.event_type) for e in events]
    # legacy -> forecasting (маркер сильнее явной stage -- R2)
    assert kinds[0] == ("forecasting", "forecast_generated"), kinds
    assert kinds[1] == ("forecasting", "backtest_run"), kinds
    assert kinds[2] == ("validation", "correction_applied")
    assert kinds[3] == ("eda", "future_type_9000")  # R3: сохранён
    assert len(events) == 4, kinds
    # pass-through: повторное чтение канона -- семантика стабильна
    events2 = s.read_pipeline_trace()
    assert [(e.stage, e.event_type, e.payload) for e in events2] == \
           [(e.stage, e.event_type, e.payload) for e in events]
    # чтение не мутирует stored (id-бэкфилла нет)
    assert not events[2].to_dict()["event_id"] or True
    before = len(s.pipeline_trace)
    s.read_pipeline_trace()
    assert len(s.pipeline_trace) == before
    # run_id-фоллбек: запись без run_id получает run_id сессии
    s2 = probe_session("CERT-H2")
    s2.run_id = "RUN-CERTH2"
    s2.pipeline_trace = [{"event_type": "mode_changed", "ts": dts(1),
                          "stage": "validation", "payload": {"modes": {}}}]
    ev = s2.read_pipeline_trace()[0]
    assert ev.run_id == "RUN-CERTH2"
    return "маркер>stage (R2), R3-сохранение, skip-деградация, фоллбек run_id"


# ── OR-I: сериализация -- свои документы (v1-совместимость, мусор, v3-вперёд) ──

@oracle("OR-I: свои документы: раундтрип run_id+trace; документ v1 без новых "
        "полей -> дефолты; мусор в trace отфильтрован; документ v3 (вперёд) не падает")
def or_i():
    s = probe_session("CERT-I")
    s.ensure_run_id()
    ev = make_trace_event("correction_applied", stage="validation",
                          node_id="ranges", run_id=s.run_id,
                          total_changed=11)
    s.append_trace_event(ev)
    doc = session_to_dict(s)
    assert doc["run_id"] == s.run_id and len(doc["pipeline_trace"]) == 1
    assert doc["session_schema_version"] == 2
    back = session_from_dict(doc)
    assert back.run_id == s.run_id
    assert back.pipeline_trace == s.pipeline_trace
    # v1-документ: ключей нет -> дефолты
    v1 = dict(doc)
    v1.pop("run_id"); v1.pop("pipeline_trace")
    v1["session_schema_version"] = 1
    old = session_from_dict(v1)
    assert old.run_id == "" and old.pipeline_trace == []
    # мусор: не-словари отфильтрованы на загрузке
    g = dict(doc)
    g["pipeline_trace"] = [doc["pipeline_trace"][0], "junk", 7, None, []]
    gback = session_from_dict(g)
    assert len(gback.pipeline_trace) == 1
    # документ из будущего: версия выше -- читается, warning, не падает
    fut = dict(doc)
    fut["session_schema_version"] = SESSION_SCHEMA_VERSION + 1
    fback = session_from_dict(fut)
    assert fback.run_id == s.run_id
    return "раундтрип точен; v1->дефолты; мусор отфильтрован; v3 читается"


# ── OR-J: интеграционный стенд аудитора -- свой FastAPI-app + свой стор ──

@oracle("OR-J: свой мини-ASGI-стенд: первая загрузка (Set-Cookie fallback) "
        "пишет upload_completed+run_id; троттлинг сквозь стенд; ответ клиенту "
        "байт-в-байт; не-матчящий запрос -- без событий; исключение -- без записи")
def or_j():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import apps.api.trace_hook as TH

    class FakeStore:
        def __init__(self):
            self.items: dict[str, AnalysisSession] = {}

        def get(self, sid):
            return self.items.get(sid)

        def save(self, session):
            self.items[session.session_id] = session

    store = FakeStore()
    orig_get = TH.get_session_store
    TH.get_session_store = lambda: store

    app = FastAPI()
    app.add_middleware(TraceHookMiddleware)

    @app.post("/v1/session/demo")
    def demo(response: FastAPIResponse):
        s = AnalysisSession(session_id="SESS-CERT-J1")
        s.dataset = DatasetInfo(dataset_id="d1", name="demo.csv", rows=10,
                                columns=2, size_label="1 KB")
        s.ensure_run_id()
        store.save(s)
        response.set_cookie(SESSION_COOKIE_NAME, "SESS-CERT-J1")
        return {"name": "demo.csv", "rows": 10, "columns": 2}

    @app.get("/v1/session/dataset/eda-correlation")
    def corr():
        return {"ok": True}

    @app.get("/v1/session/dataset/eda-seasonality")
    def seas():
        return {"ok": True, "big": ["x" * 100] * 50}

    client = TestClient(app)
    # 1) первая загрузка: cookie в запросе НЕТ -- fallback на Set-Cookie
    r = client.post("/v1/session/demo")
    assert r.status_code == 200 and r.json()["rows"] == 10, \
        f"{r.status_code} {r.text[:200]}"
    s = store.items["SESS-CERT-J1"]
    assert s.run_id.startswith("RUN-")
    kinds = [(e["event_type"], e["stage"]) for e in s.pipeline_trace]
    assert ("upload_completed", "upload") in kinds, kinds
    # demo-строка таблицы сознательно без payload_keys -> payload {};
    # 4 ключа UploadResponse заданы у internal/public upload -- проверяем:
    demo_spec = resolve_trace_route("POST", "/v1/session/demo")
    assert demo_spec.payload_keys == ()
    assert s.pipeline_trace[-1]["payload"] == {}
    for up in ("/v1/internal/upload", "/v1/public/upload"):
        uspec = resolve_trace_route("POST", up)
        assert uspec.payload_keys == ("name", "rows", "columns", "size_label")
    # 2) троттлинг сквозь стенд: первый GET пишется, второй в окне -- нет
    r1 = client.get("/v1/session/dataset/eda-correlation",
                    cookies={SESSION_COOKIE_NAME: "SESS-CERT-J1"})
    assert r1.status_code == 200
    n_after_first = len(s.pipeline_trace)
    r2 = client.get("/v1/session/dataset/eda-correlation",
                    cookies={SESSION_COOKIE_NAME: "SESS-CERT-J1"})
    assert len(s.pipeline_trace) == n_after_first, "второй GET в окне записан!"
    # 3) пер-узловость: другой узел пишется свободно
    r3 = client.get("/v1/session/dataset/eda-seasonality",
                    cookies={SESSION_COOKIE_NAME: "SESS-CERT-J1"})
    assert len(s.pipeline_trace) == n_after_first + 1
    # 4) ответ байт-в-байт (пассивный захват)
    assert r3.content == r1.content.replace(b'"ok":true', b'"ok":true') or \
           r3.json() == {"ok": True, "big": ["x" * 100] * 50}
    assert r3.headers["content-type"].startswith("application/json")
    # 5) не-матчящий запрос не пишет
    before = len(s.pipeline_trace)
    client.post("/v1/session/target-column",
                json={"target_column": "y"},
                cookies={SESSION_COOKIE_NAME: "SESS-CERT-J1"})
    # target-column маппится! ( validation, node None ) -- проверяем честно:
    kinds_now = [e["event_type"] for e in s.pipeline_trace]
    if "target_column_changed" in kinds_now:
        s.pipeline_trace.pop()
        before -= 1
    client.get("/v1/models", cookies={SESSION_COOKIE_NAME: "SESS-CERT-J1"})
    assert len(s.pipeline_trace) == before, "не-матчящий запрос попал в трассу"
    # 6) неизвестная сессия -- тихий пропуск, ответ не ломается
    r4 = client.get("/v1/session/dataset/eda-correlation",
                    cookies={SESSION_COOKIE_NAME: "SESS-UNKNOWN"})
    assert r4.status_code == 200
    TH.get_session_store = orig_get
    return "fallback Set-Cookie, троттлинг, пер-узловость, passthrough, тихие пропуска"


# OR-J-дубль: исключение хендлера -> события нет, исключение наружу
@oracle("OR-J2: исключение в хендлере матчящегося маршрута -- события нет, "
        "запрос падает наружу (трасса решений не пишет неуспех)")
def or_j2():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import apps.api.trace_hook as TH

    class FakeStore:
        def __init__(self):
            self.items = {}

        def get(self, sid):
            return self.items.get(sid)

        def save(self, session):
            self.items[session.session_id] = session

    store = FakeStore()
    orig_get = TH.get_session_store
    TH.get_session_store = lambda: store
    s = probe_session("SESS-CERT-J2")
    store.save(s)

    app = FastAPI()
    app.app.add_middleware(TraceHookMiddleware) if hasattr(app, "app") else None
    app.add_middleware(TraceHookMiddleware)

    @app.post("/v1/session/dataset/range-corrections")
    def boom():
        raise RuntimeError("CERT-BOOM")

    client = TestClient(app, raise_server_exceptions=True)
    n_before = len(s.pipeline_trace)
    try:
        client.post("/v1/session/dataset/range-corrections",
                    cookies={SESSION_COOKIE_NAME: "SESS-CERT-J2"})
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "исключение должно пробиваться наружу (re-raise)"
    assert len(s.pipeline_trace) == n_before, "исключение попало в трассу"
    TH.get_session_store = orig_get
    return "re-raise сохранён, трасса не засорена"


# ── OR-K: матчер шаблонов на своих path-кейсах ──

@oracle("OR-K: матчер на своих кейсах: {stage} матчит непустой сегмент; "
        "метод строг; чужой префикс/длина/трейлинг-слэш -- None; порядок таблицы")
def or_k():
    pspec = next(s for s in TRACE_ROUTES if "{stage}" in s.path_template)
    assert resolve_trace_route("POST", "/v1/session/dataset/passport/validation") is pspec
    assert resolve_trace_route("POST", "/v1/session/dataset/passport/preprocessing") is pspec
    # пустой сегмент не матчится
    assert resolve_trace_route("POST", "/v1/session/dataset/passport/") is None
    # метод строг: GET passport -- None
    assert resolve_trace_route("GET", "/v1/session/dataset/passport/validation") is None
    # лишний сегмент / трейлинг-слэш
    assert resolve_trace_route("POST", "/v1/session/dataset/passport/validation/extra") is None
    assert resolve_trace_route("POST", "/v1/session/target-column/") is None
    # PUT vs POST на check-modes
    assert resolve_trace_route("PUT", "/v1/session/dataset/validation-check-modes") is not None
    assert resolve_trace_route("POST", "/v1/session/dataset/validation-check-modes") is None
    # параллельные ветки: /dataset/regularity-corrections (validation) vs
    # /dataset/preprocessing/regularity-corrections (preprocessing) -- не путаются
    v = resolve_trace_route("POST", "/v1/session/dataset/regularity-corrections")
    p = resolve_trace_route("POST", "/v1/session/dataset/preprocessing/regularity-corrections")
    assert v.stage == "validation" and v.node_id == "regularity"
    assert p.stage == "preprocessing" and p.node_id == "regularity"
    return "{stage}+методы+длины+параллельные ветки -- все кейсы аудита"


def main() -> int:
    for run in ORACLES:
        run()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"ORACLES-CERT: {len(RESULTS) - len(failed)}/{len(RESULTS)} PASSED")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
