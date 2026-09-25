# scripts/audit_scripts/progr4cert_oracles.py
# Task PROGR-4-CERT (2026-09-25) -- независимые оракул-тесты аудитора
# на СВОИХ данных: живой FastAPI-стенд (TestClient), свои cookie-сессии,
# свой корпус событий (канонические + legacy 3-польные), свой сид.
# Независимая перекодировка контракта GET /v1/progress/trace
# (spec_progress.md §5 слой 1, §6.1-§6.2) -- не копия test_progress_panel.py.
# Запуск: python3 scripts/audit_scripts/progr4cert_oracles.py
#   -> ORACLES-CERT-PROGR4: N/N PASSED
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event  # noqa: E402

SEED = 20260925
COOKIE = "cisstat_session_id"
RESULTS: list[tuple[str, bool]] = []


def cookie_value(c: TestClient, name: str = COOKIE) -> str | None:
    """Значение cookie из jar httpx (get_dict отсутствует в этой версии)."""
    for ck in c.cookies.jar:
        if ck.name == name:
            return ck.value
    return None


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")


def client() -> TestClient:
    reset_session_store_for_testing()
    return TestClient(app)


CANON_8 = ("event_id", "run_id", "ts", "stage", "node_id",
           "event_type", "payload", "actor")


# OR-A. Контракт пустой сессии: честный null/[] и Set-Cookie присутствует.
def or_a() -> None:
    print("OR-A пустая сессия: контракт пустого ответа")
    c = client()
    r = c.get("/v1/progress/trace")
    check("A1 HTTP 200", r.status_code == 200)
    d = r.json()
    check("A2 run_id null (не '' и не 0)", d["run_id"] is None)
    check("A3 started_at null", d["started_at"] is None)
    check("A4 events == []", d["events"] == [])
    check("A5 cookie сессии выставлен (панель открывается на пустой сессии)",
          cookie_value(c) is not None)


# OR-B. Формат ответа на своих событиях: 8 канонических полей + legacy-
# алиас timestamp; payload проходит без искажения; run_id единый.
def or_b() -> None:
    print("OR-B канон ответа на своём корпусе (свой payload)")
    c = client()
    c.post("/v1/session/demo")
    store = get_session_store()
    sid = cookie_value(c)
    s = store.get(sid)
    my_payload = {"strategy": "interpolation", "total_changed": 7, "seed": SEED}
    s.append_trace_event(make_trace_event(
        "correction_applied", stage="preprocessing", node_id="outliers",
        run_id=s.run_id, **my_payload))  # **payload-соглашение фабрики
    store.save(s)
    d = c.get("/v1/progress/trace").json()
    evs = d["events"]
    check("B1 >= 2 событий (demo upload + своё)", len(evs) >= 2)
    mine = [e for e in evs if e["event_type"] == "correction_applied"]
    check("B2 своё событие найдено", len(mine) == 1)
    e = mine[0]
    check("B3 все 8 канонических ключей", all(k in e for k in CANON_8))
    check("B4 legacy-алиас timestamp == ts", e.get("timestamp") == e["ts"])
    check("B5 payload без искажения (свой словарь)", e["payload"] == my_payload)
    check("B6 actor == 'user' (§4.1 единственный вариант сейчас)", e["actor"] == "user")
    check("B7 run_id события == run_id ответа", e["run_id"] == d["run_id"])
    check("B8 формат RUN-[0-9A-F]{8}", re.fullmatch(r"RUN-[0-9A-F]{8}", d["run_id"] or "") is not None)


# OR-C. started_at -- ts ПЕРВОГО события, не последнего (мутационно-
# чувствительная точка: events[-1] должен быть пойман).
def or_c() -> None:
    print("OR-C started_at = первый ts, хронология дописывания")
    c = client()
    c.post("/v1/session/demo")
    store = get_session_store()
    sid = cookie_value(c)
    s = store.get(sid)
    s.append_trace_event(make_trace_event(
        "profile_viewed", stage="eda", node_id="correlation",
        run_id=s.run_id, payload={}))
    store.save(s)
    d = c.get("/v1/progress/trace").json()
    evs = d["events"]
    ts_list = [e["ts"] for e in evs]
    check("C1 started_at == ts первого события", d["started_at"] == ts_list[0])
    check("C2 started_at != ts последнего (иначе мутант events[-1] жив)",
          d["started_at"] != ts_list[-1] or ts_list[0] == ts_list[-1])
    check("C3 порядок дописывания: upload раньше profile_viewed",
          [e["event_type"] for e in evs].index("upload_completed")
          < [e["event_type"] for e in evs].index("profile_viewed"))


# OR-D. run_id: гейт первой загрузки. Без датасета -- null даже при
# наличии событий; ручная подмена session_id на свою сессию с датасетом
# невозможна без загрузки -- проверяем честность null на своём id.
def or_d() -> None:
    print("OR-D run_id без датасета -- честный null при наличии событий")
    c = client()
    store = get_session_store()
    my_sid = f"cert4-audit-{SEED}"
    s = store.get_or_create(my_sid)
    s.append_trace_event(make_trace_event(
        "passport_captured", stage="eda", node_id=None, run_id=""))
    store.save(s)
    c.cookies.set(COOKIE, my_sid)
    d = c.get("/v1/progress/trace").json()
    check("D1 run_id null", d["run_id"] is None)
    check("D2 событие при этом отдаётся", len(d["events"]) == 1)
    check("D3 started_at есть (первое событие)", d["started_at"] is not None)


# OR-E. Граница чтения: свой legacy-корпус (3 поля) нормализуется,
# stored-трасса НЕ мутируется чтением (idempotent read).
def or_e() -> None:
    print("OR-E legacy-нормализация на чтении + stored не мутируется")
    c = client()
    store = get_session_store()
    my_sid = f"cert4-legacy-{SEED}"
    s = store.get_or_create(my_sid)
    s.pipeline_trace.append({
        "event_type": "forecast_generated",
        "timestamp": "2026-09-25T05:00:00+00:00",
        "payload": {"model_name": "Naive", "seed": SEED},
    })
    store.save(s)
    before = [dict(x) for x in s.pipeline_trace]
    c.cookies.set(COOKIE, my_sid)
    d = c.get("/v1/progress/trace").json()
    e = d["events"][0]
    check("E1 ts поднят из legacy timestamp", e["ts"] == "2026-09-25T05:00:00+00:00")
    check("E2 stage = forecasting (маркер legacy приоритетнее, R2)",
          e["stage"] == "forecasting")
    check("E3 event_type не валидируется на границе (R3)",
          e["event_type"] == "forecast_generated")
    check("E4 node_id null у legacy", e["node_id"] is None)
    check("E5 payload прошёл", e["payload"]["seed"] == SEED)
    check("E6 run_id legacy -- пустая строка -> ответ run_id null",
          d["run_id"] is None)
    after = get_session_store().get(my_sid).pipeline_trace
    check("E7 чтение не мутирует stored (то же 3-польное представление)",
          after == before and "ts" not in after[0])
    # Повторное чтение -- идемпотентно.
    d2 = c.get("/v1/progress/trace").json()
    check("E8 повторное чтение даёт тот же канон", d2["events"][0]["ts"] == e["ts"])


# OR-F. Ридер сам не трассируется и не растит трассу (вне TRACE_ROUTES):
# два GET подряд -- длина трассы не изменилась, resolve -- None.
def or_f() -> None:
    print("OR-F ридер не трассируется (нет самозаписи)")
    from apps.api.trace_hook import resolve_trace_route
    c = client()
    c.post("/v1/session/demo")
    sid = cookie_value(c)
    n1 = len(c.get("/v1/progress/trace").json()["events"])
    c.get("/v1/progress/trace")
    n2 = len(c.get("/v1/progress/trace").json()["events"])
    check("F1 resolve_trace_route(GET /v1/progress/trace) is None",
          resolve_trace_route("GET", "/v1/progress/trace") is None)
    check("F2 трасса не растёт от чтений", n1 == n2)
    check("F3 >0 событий (демо-загрузка дала события)", n1 > 0)


# OR-G. Своё событие ДО запуска хука на другом маршруте -- хук пишет
# upload_completed на узел structure_confirmed (связка PROGR-3 -> PROGR-4).
def or_g() -> None:
    print("OR-G сквозная связка: хук пишет, ридер отдаёт (свой путь)")
    c = client()
    r = c.post("/v1/session/demo")
    check("G1 demo-загрузка 200", r.status_code == 200)
    d = c.get("/v1/progress/trace").json()
    up = [e for e in d["events"] if e["event_type"] == "upload_completed"]
    check("G2 ровно один upload_completed", len(up) == 1)
    check("G3 узел structure_confirmed", up[0]["node_id"] == "structure_confirmed")
    check("G4 стадия upload", up[0]["stage"] == "upload")
    check("G5 run_id совпадает по всей цепочке",
          up[0]["run_id"] == d["run_id"] is not None or up[0]["run_id"] == d["run_id"])


def main() -> int:
    for fn in (or_a, or_b, or_c, or_d, or_e, or_f, or_g):
        fn()
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"ORACLES-CERT-PROGR4: {passed}/{len(RESULTS)} PASSED")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
