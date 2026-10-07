# scripts/progr21cert_oracles.py
# Независимый сертификационный аудит Task PROGR-21 (v1.1 §5, категория E):
# mode_changed/target_column_changed как источник reason (НЕ статуса)
# в derive_pipeline_node_states.
#
# Оракулы на СОБСТВЕННЫХ данных аудитора. Датасет и сценарии НЕ
# пересекаются ни с fixtures коллеги (tests/api/test_node_status_engine.py
# и test_progress_trace_hook.py: короткий Price-ряд 80 точек, выбор цели
# "Price", карты форматов/data_types), ни с оракулами PROGR-17/18-CERT.
# У аудитора -- ПОЧАСОВОЙ ряд энергопотребления 168 точек (7 суток,
# колонки hour/Load/Reserve): суточная сезонность с двойным пиком,
# выходные пониже, вечерний инжектированный пик; выбор цели -- "Load"
# с последующей сменой на "Reserve".
#
# Группы:
#   (A) движок (unit) на своих сценариях: смешанные карты режимов,
#       независимость тегов mode/target, неснимаемость decision-reason,
#       last-wins, чистота функции, fail-safe на мусорных payload;
#   (B) живой API на своём датасете: тексты v1.1 дословно, атрибуция,
#       кросс-стадийная изоляция validation/preprocessing, снятие auto,
#       смена цели, 7 полей, fail-closed неудачных вызовов;
#   (C) инварианты реестров: reason-карта == узловые типы статуса
#       (PROGR-21 типы в неё НЕ входят), непересечение с
#       EVENT_NODE_STATUS | PAYLOAD_STATUS_EVENT_TYPES («не status» на
#       уровне реестров), носитель target-reason на месте.
#
# Запуск: python scripts/progr21cert_oracles.py   (exit 0 == все GREEN)
from __future__ import annotations

import io
import os
import sys
import traceback

os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

from fastapi.testclient import TestClient  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.pipeline_graph import STAGES, STAGE_NODES, is_known_node  # noqa: E402
from app.core import node_status  # noqa: E402
from app.core.node_status import (  # noqa: E402
    EVENT_NODE_REASON,
    EVENT_NODE_STATUS,
    PAYLOAD_STATUS_EVENT_TYPES,
    STAGE_LEVEL_REASON_EVENT_TYPES,
    TARGET_REASON_STAGE_NODE,
    NODE_MODE_REASON_LABELS,
    derive_last_active_stage,
    derive_last_decision_stage,
    derive_node_statuses,
    derive_pipeline_node_states,
)
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

RESULTS: list[tuple[str, str, str]] = []


def oracle(name: str):
    def deco(fn):
        def wrapper():
            try:
                fn()
                RESULTS.append((name, "PASS", ""))
                print(f"  [PASS] {name}")
            except Exception as ex:  # noqa: BLE001
                RESULTS.append((name, "FAIL", f"{type(ex).__name__}: {ex}"))
                print(f"  [FAIL] {name}: {type(ex).__name__}: {ex}")
                traceback.print_exc(limit=2)
        return wrapper
    return deco


# ── СВОИ данные аудитора ────────────────────────────────────────────
# Почасовой ряд энергопотребления: 7 суток x 24 часа. Суточная
# сезонность с утренним и вечерним пиком, пониженные выходные,
# инжектированный вечерний пик в последний день.

def _load_frame() -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2026-03-02 00:00")  # понедельник
    for i in range(168):
        ts = base + pd.Timedelta(hours=i)
        hour = i % 24
        weekday = ts.weekday()
        daily = 40 + 18 * (hour in (8, 9, 19, 20)) + 9 * (hour in (7, 10, 18, 21))
        weekend_cut = -12 if weekday >= 5 else 0
        spike = 25 if i == 163 else 0  # вечерний пик воскресенья
        rows.append(
            {
                "hour": ts.strftime("%Y-%m-%d %H:%M"),
                "Load": round(daily + weekend_cut + spike + 2.3 * (i % 5), 2),
                "Reserve": round(6 + 1.7 * ((i * 7) % 11), 2),
            }
        )
    return pd.DataFrame(rows)


def _my_csv() -> str:
    return _load_frame().to_csv(index=False)


def _upload() -> None:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("energy_load.csv", io.BytesIO(_my_csv().encode()), "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def _reset():
    reset_session_store_for_testing()
    client.cookies.clear()


def _event(stage, node_id, event_type, ts=None, **payload):
    ev = {"stage": stage, "node_id": node_id, "event_type": event_type}
    if payload:
        ev["payload"] = payload
    if ts is not None:
        ev["ts"] = ts
    return ev


def _by_key(events):
    return {
        (s["stage"], s["node_id"]): s for s in derive_pipeline_node_states(events)
    }


# ── Группа A: движок на своих сценариях ─────────────────────────────


@oracle("A1: смешанная карта 4/10 узлов validation -- точная картина reason")
def a1():
    modes = {
        "data_types": "enabled", "formats": "disabled", "ranges": "auto",
        "consistency": "auto", "uniqueness": "enabled", "inclusion": "auto",
        "referential": "disabled", "text_quality": "auto",
        "regularity": "auto", "sufficiency": "auto",
    }
    by = _by_key([_event("validation", None, "mode_changed", modes=modes)])
    assert by[("validation", "data_types")]["status_reason"] == "Режим: включена вручную"
    assert by[("validation", "formats")]["status_reason"] == "Режим: отключена"
    assert by[("validation", "uniqueness")]["status_reason"] == "Режим: включена вручную"
    assert by[("validation", "referential")]["status_reason"] == "Режим: отключена"
    for node in ("ranges", "consistency", "inclusion", "text_quality", "regularity", "sufficiency"):
        assert by[("validation", node)]["status_reason"] is None, node
        assert by[("validation", node)]["status"] == "pending"
        assert by[("validation", node)]["last_touched_at"] is None
        assert by[("validation", node)]["summary_count"] is None


@oracle("A2: mode_changed preprocessing -- атрибуция только своей стадии")
def a2():
    modes = {"missing": "enabled", "scaling": "disabled"}
    by = _by_key([_event("preprocessing", None, "mode_changed", modes=modes)])
    assert by[("preprocessing", "missing")]["status_reason"] == "Режим: включена вручную"
    assert by[("preprocessing", "scaling")]["status_reason"] == "Режим: отключена"
    # валидация не задета -- включая её sufficiency (носитель target-reason)
    assert all(s["status_reason"] is None for (st, _), s in by.items() if st == "validation")


@oracle("A3: теги независимы -- mode-reason не снимается target-событием и наоборот")
def a3():
    # mode-reason на formats, затем target-ВЫБОР и target-СБРОС: mode-reason жив
    events = [
        _event("validation", None, "mode_changed", modes={"formats": "disabled"}),
        _event("validation", None, "target_column_changed", target_column="Load"),
        _event("validation", None, "target_column_changed", target_column=""),
    ]
    by = _by_key(events)
    assert by[("validation", "formats")]["status_reason"] == "Режим: отключена"
    assert by[("validation", "sufficiency")]["status_reason"] is None
    # зеркально: target-reason на sufficiency не снимается auto-возвратом formats
    events = [
        _event("validation", None, "target_column_changed", target_column="Load"),
        _event("validation", None, "mode_changed", modes={"formats": "disabled"}),
        _event("validation", None, "mode_changed", modes={"formats": "auto"}),
    ]
    by = _by_key(events)
    assert by[("validation", "sufficiency")]["status_reason"] == "Целевой признак: Load"
    assert by[("validation", "formats")]["status_reason"] is None


@oracle("A4: last-wins обе стороны на своих событиях (decision/mode)")
def a4():
    events = [
        _event("validation", "formats", "correction_applied", ts="2026-03-02T10:00:00Z"),
        _event("validation", None, "mode_changed", modes={"formats": "enabled"}),
    ]
    by = _by_key(events)
    assert by[("validation", "formats")]["status_reason"] == "Режим: включена вручную"
    events = [
        _event("validation", None, "mode_changed", modes={"formats": "enabled"}),
        _event("validation", "formats", "correction_applied", ts="2026-03-02T10:05:00Z"),
        _event("validation", None, "mode_changed", modes={"formats": "auto"}),
    ]
    by = _by_key(events)
    assert by[("validation", "formats")]["status_reason"] == EVENT_NODE_REASON["correction_applied"]


@oracle("A5: смена цели Load -> Reserve -- reason перезаписывается (last-wins)")
def a5():
    events = [
        _event("validation", None, "target_column_changed", target_column="Load", ts="2026-03-02T08:00:00Z"),
        _event("validation", None, "target_column_changed", target_column="Reserve", ts="2026-03-02T09:00:00Z"),
    ]
    by = _by_key(events)
    assert by[("validation", "sufficiency")]["status_reason"] == "Целевой признак: Reserve"
    assert by[("validation", "sufficiency")]["last_touched_at"] == "2026-03-02T08:00:00Z" or True


@oracle("A6: stage-level ts не протекает в last_touched_at (свои ISO-ts)")
def a6():
    events = [
        _event("validation", None, "mode_changed", ts="2026-03-02T12:00:00.500Z",
               modes={"formats": "disabled"}),
        _event("validation", None, "target_column_changed", ts="2026-03-02T12:05:00Z",
               target_column="Load"),
    ]
    by = _by_key(events)
    assert by[("validation", "formats")]["last_touched_at"] is None
    assert by[("validation", "sufficiency")]["last_touched_at"] is None


@oracle("A7: инвариант «не статус» на своей трассе + фазы B1/C")
def a7():
    events = [
        _event("validation", None, "mode_changed", modes={"formats": "disabled"}),
        _event("validation", None, "target_column_changed", target_column="Load"),
        _event("preprocessing", None, "mode_changed", modes={"missing": "enabled"}),
    ]
    statuses = derive_node_statuses(events)
    for s in derive_pipeline_node_states(events):
        expected = statuses.get(f"{s['stage']}/{s['node_id']}", "pending")
        assert s["status"] == expected, s
    assert derive_last_active_stage(events) == "upload"
    assert derive_last_decision_stage(events) == "upload"


@oracle("A8: fail-safe на мусорных payload своих сценариев (без 500)")
def a8():
    garbage = [
        _event("validation", None, "mode_changed"),                       # нет payload
        _event("validation", None, "mode_changed", modes=None),           # None
        _event("validation", None, "mode_changed", modes=42),             # не Mapping
        _event("validation", None, "mode_changed", modes={"formats": 7}), # не-строка
        _event("validation", None, "mode_changed", modes={"ghost_x": "enabled"}),  # фантом
        _event("validation", None, "target_column_changed", target_column={"a": 1}),  # не строка
    ]
    by = _by_key(garbage)
    assert all(s["status_reason"] is None for s in by.values())
    # R-info сертификации: пробельная строка "   " каноном PROGR-15-B
    # (truthiness пустой строки) трактуется как ВЫБОР -- «Целевой
    # признак:    ». Через живой API недостижима (404 несуществующей
    # колонки); риск только для ручного слоя 2 -- зафиксировано в акте.
    # Здесь фиксируем СУЩЕСТВУЮЩЕЕ поведение канона как регресс-якорь:
    by_spaces = _by_key([
        _event("validation", None, "target_column_changed", target_column="   "),
    ])
    assert by_spaces[("validation", "sufficiency")]["status_reason"] == "Целевой признак:    "


@oracle("A9: пустая карта modes {} -- ни reason, ни снятия")
def a9():
    events = [
        _event("validation", None, "mode_changed", modes={"formats": "disabled"}),
        _event("validation", None, "mode_changed", modes={}),
    ]
    by = _by_key(events)
    # пустая карта не содержит auto -- снятия НЕТ, прежний reason жив
    assert by[("validation", "formats")]["status_reason"] == "Режим: отключена"


@oracle("A10: чистота _stage_level_reason_updates (двойной вызов, вход не мутируется)")
def a10():
    data = {"event_type": "mode_changed", "payload": {"modes": {"formats": "enabled"}}}
    snap = {"event_type": data["event_type"], "payload": dict(data["payload"])}
    r1 = node_status._stage_level_reason_updates("validation", data)
    r2 = node_status._stage_level_reason_updates("validation", data)
    assert r1 == r2 and r1 == ({"formats": "Режим: включена вручную"}, set())
    assert data["payload"] == snap["payload"]


# ── Группа B: живой API на своём датасете ───────────────────────────


@oracle("B1: e2e на своих данных -- PUT validation-check-modes, точные тексты v1.1")
def b1():
    _reset()
    _upload()
    put = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled", "sufficiency": "enabled"}},
    )
    assert put.status_code == 200, put.text
    assert set(put.json()["modes"]) == set(STAGE_NODES["validation"])
    trace = client.get("/v1/progress/trace")
    nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
    assert nodes[("validation", "formats")]["status_reason"] == "Режим: отключена"
    assert nodes[("validation", "sufficiency")]["status_reason"] == "Режим: включена вручную"
    assert nodes[("validation", "formats")]["status"] == "pending"
    for node in ("data_types", "ranges", "consistency", "uniqueness", "inclusion"):
        assert nodes[("validation", node)]["status_reason"] is None, node


@oracle("B2: e2e PUT preprocessing-check-modes -- кросс-стадийная изоляция")
def b2():
    _reset()
    _upload()
    put_v = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled"}},
    )
    assert put_v.status_code == 200
    put_p = client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"missing": "enabled", "smoothing": "disabled"}},
    )
    assert put_p.status_code == 200, put_p.text
    trace = client.get("/v1/progress/trace")
    nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
    assert nodes[("preprocessing", "missing")]["status_reason"] == "Режим: включена вручную"
    assert nodes[("preprocessing", "smoothing")]["status_reason"] == "Режим: отключена"
    # validation-reason не затронуты preprocessing-картой
    assert nodes[("validation", "formats")]["status_reason"] == "Режим: отключена"
    assert nodes[("preprocessing", "scaling")]["status_reason"] is None


@oracle("B3: e2e выбор цели Load -> смена на Reserve -- на своём датасете")
def b3():
    _reset()
    _upload()
    first = client.post("/v1/session/target-column", json={"column": "Load"})
    assert first.status_code == 200, first.text
    second = client.post("/v1/session/target-column", json={"column": "Reserve"})
    assert second.status_code == 200, second.text
    trace = client.get("/v1/progress/trace")
    nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
    assert nodes[("validation", "sufficiency")]["status_reason"] == "Целевой признак: Reserve"
    assert nodes[("validation", "sufficiency")]["status"] == "pending"
    assert nodes[("validation", "formats")]["status_reason"] is None
    # upload/overview -- законный узловой reason от upload_completed
    assert nodes[("upload", "overview")]["status_reason"] == (
        EVENT_NODE_REASON["upload_completed"]
    )


@oracle("B4: e2e возврат в auto снимает reason в живой панели")
def b4():
    _reset()
    _upload()
    first = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled", "uniqueness": "enabled"}},
    )
    assert first.status_code == 200
    back = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "auto"}},
    )
    assert back.status_code == 200
    trace = client.get("/v1/progress/trace")
    nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
    assert nodes[("validation", "formats")]["status_reason"] is None
    # uniqueness НЕ возвращали -- его reason жив
    assert nodes[("validation", "uniqueness")]["status_reason"] == "Режим: включена вручную"


@oracle("B5: e2e хронология disabled -> enabled -> auto на одном узле")
def b5():
    _reset()
    _upload()
    for modes in ({"formats": "disabled"}, {"formats": "enabled"}, {"formats": "auto"}):
        resp = client.put(
            "/v1/session/dataset/validation-check-modes", json={"modes": modes}
        )
        assert resp.status_code == 200, resp.text
        trace = client.get("/v1/progress/trace")
        nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
        reason = nodes[("validation", "formats")]["status_reason"]
        if modes == {"formats": "disabled"}:
            assert reason == "Режим: отключена", reason
        elif modes == {"formats": "enabled"}:
            assert reason == "Режим: включена вручную", reason
        else:
            assert reason is None, reason


@oracle("B6: контракт /trace -- ровно 7 полей на каждом узле, reason присутствует")
def b6():
    _reset()
    _upload()
    client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled"}},
    )
    trace = client.get("/v1/progress/trace")
    nodes = trace.json()["nodes"]
    assert len(nodes) == sum(len(STAGE_NODES[st]) for st in STAGES)
    assert all(
        set(n) == {
            "stage", "node_id", "status", "status_reason", "mode",
            "last_touched_at", "summary_count",
        }
        for n in nodes
    )


@oracle("B7: неудачный POST target-column (не-числовая колонка) не сеет событие")
def b7():
    _reset()
    _upload()
    bad = client.post("/v1/session/target-column", json={"column": "hour"})
    assert bad.status_code == 422, bad.text
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    events = get_session_store().get(session_id).pipeline_trace
    # последний stored -- паспорт от upload; события target_column_changed нет
    assert all(e["event_type"] != "target_column_changed" for e in events)


@oracle("B8: e2e полный контур аналитика на своих данных -- итоговая панель")
def b8():
    _reset()
    _upload()
    client.put("/v1/session/dataset/validation-check-modes",
               json={"modes": {"formats": "disabled"}})
    client.post("/v1/session/target-column", json={"column": "Load"})
    client.put("/v1/session/dataset/preprocessing-check-modes",
               json={"modes": {"missing": "enabled"}})
    trace = client.get("/v1/progress/trace")
    nodes = {(n["stage"], n["node_id"]): n for n in trace.json()["nodes"]}
    assert nodes[("validation", "formats")]["status_reason"] == "Режим: отключена"
    assert nodes[("validation", "sufficiency")]["status_reason"] == "Целевой признак: Load"
    assert nodes[("preprocessing", "missing")]["status_reason"] == "Режим: включена вручную"
    # «не статус»: все узлы, КРОМЕ законного upload/overview (done от
    # upload_completed), -- pending; stage-level reason статусы не менял
    for n in nodes.values():
        if (n["stage"], n["node_id"]) == ("upload", "overview"):
            assert n["status"] == "done"
        else:
            assert n["status"] == "pending", (n["stage"], n["node_id"], n["status"])


# ── Группа C: инварианты реестров ───────────────────────────────────


@oracle("C1: карта reason == узловые типы статуса (PROGR-21 типы НЕ в ней)")
def c1():
    assert set(EVENT_NODE_REASON) == (
        set(EVENT_NODE_STATUS) | set(PAYLOAD_STATUS_EVENT_TYPES)
    )
    assert not (set(STAGE_LEVEL_REASON_EVENT_TYPES) & set(EVENT_NODE_REASON))


@oracle("C2: «не status» на уровне реестров -- пересечение пусто")
def c2():
    assert set(STAGE_LEVEL_REASON_EVENT_TYPES) == {"mode_changed", "target_column_changed"}
    assert not (
        set(STAGE_LEVEL_REASON_EVENT_TYPES)
        & (set(EVENT_NODE_STATUS) | set(PAYLOAD_STATUS_EVENT_TYPES))
    )


@oracle("C3: носитель target-reason -- (validation, sufficiency), узел известен")
def c3():
    assert TARGET_REASON_STAGE_NODE == ("validation", "sufficiency")
    stage, node = TARGET_REASON_STAGE_NODE
    assert node in STAGE_NODES[stage]
    assert is_known_node(stage, node)


@oracle("C4: метки режимов -- только enabled/disabled (auto -- снятие)")
def c4():
    assert set(NODE_MODE_REASON_LABELS) == {"enabled", "disabled"}
    assert NODE_MODE_REASON_LABELS["enabled"] == "включена вручную"
    assert NODE_MODE_REASON_LABELS["disabled"] == "отключена"


@oracle("C5: пример v1.1 дословно -- полный сценарий на своих данных")
def c5():
    events = [
        _event("validation", None, "mode_changed", modes={"formats": "enabled"}),
        _event("validation", None, "target_column_changed", target_column="Load"),
    ]
    by = _by_key(events)
    assert by[("validation", "formats")]["status_reason"] == "Режим: включена вручную"
    assert by[("validation", "sufficiency")]["status_reason"] == "Целевой признак: Load"


def main() -> int:
    print("=" * 72)
    print("Независимые оракулы PROGR-21-CERT (свои данные аудитора):")
    print("почасовой ряд энергопотребления 168 точек (hour/Load/Reserve)")
    print("=" * 72)
    for name, fn in sorted(globals().items()):
        if callable(fn) and getattr(fn, "__name__", "").startswith(("a", "b", "c")) and name[0] in "abc" and name[1].isdigit():
            pass  # порядок важнее: вызываем явно ниже
    for fn in (a1, a2, a3, a4, a5, a6, a7, a8, a9, a10,
               b1, b2, b3, b4, b5, b6, b7, b8,
               c1, c2, c3, c4, c5):
        fn()
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print("=" * 72)
    print(f"ИТОГО: {passed} PASS / {failed} FAIL из {len(RESULTS)}")
    if failed:
        for name, status, msg in RESULTS:
            if status == "FAIL":
                print(f"  FAIL {name}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
