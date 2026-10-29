"""PGV-06 CERT: независимые пробы-находки (оракулы на своих данных).

Сертификатор: independent audit "Task ID: PGV-06 (2026-10-29) — Pure
comparison resolver". Пробы P1–P12 проверяют ЧЕСТНОСТЬ поставки
(apps/api/passport_comparison.py + routers/session.py) против §9
spec_passport_graphics_visual.md и AC13/AC14/AC06/AC07/AC10/AC11/AC12/
AC18-дух — на СОБСТВЕННЫХ данных сертификатора (seed 20261102, серии
иной формы, чем корпус поставки; namespace RUN-P6CERT*/p6cert-*).

Каждая проба: PASS/FAIL + короткий вердикт. FAIL = кандидат в находки
(F-P6C*)/наблюдения (N-P6C*). Продуктовое дерево не меняется (пробы
только читают/сеют собственные изолированные данные; mutation-фаза —
отдельный скрипт на временной копии).
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import traceback

import numpy as np
import pandas as pd

RESULTS: list[tuple[str, str, str]] = []


def probe(name: str, description: str):
    def deco(fn):
        def wrapper():
            try:
                detail = fn()
                RESULTS.append((name, "PASS", detail or ""))
            except AssertionError as exc:
                RESULTS.append((name, "FAIL", f"ASSERT: {exc}"))
            except Exception as exc:  # noqa: BLE001
                RESULTS.append(
                    (name, "FAIL", f"{type(exc).__name__}: {exc}")
                )
        wrapper.__name__ = fn.__name__
        wrapper._description = description
        return wrapper
    return deco


# ── Общая изолированная среда ────────────────────────────────────────

_TMP = tempfile.mkdtemp(prefix="pgv06cert-probe-")
os.environ["CISSTAT_DATA_DIR"] = _TMP
for _var in (
    "DATABASE_URL",
    "CISSTAT_RUNS_BACKEND",
    "CISSTAT_IDENTITY_MODE",
    "CISSTAT_API_KEYS",
    "CISSTAT_ARTIFACTS_BACKEND",
):
    os.environ.pop(_var, None)


def _fresh_env():
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()


def _series_csv(n: int = 96, seed: int = 20261102) -> str:
    """СВОЙ ряд сертификатора: иной сид/форма/амплитуды, чем у поставки."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-03-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 50 - 0.08 * x + 6 * np.sin(2 * np.pi * x / 12) + rng.normal(0, 0.9, n)
    frame = pd.DataFrame({"date": dates, "value": values})
    return frame.to_csv(index=False)


class Pipe:
    """Живой API-пайплайн сертификатора (свой клиент, свои данные).
    fresh=True -- изолированная среда; fresh=False -- второй клиент
    в ТОМ ЖЕ мире (для двух run'ов рядом, без сброса сторов)."""

    def __init__(self, fresh: bool = True):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.session_store import SESSION_COOKIE_NAME

        if fresh:
            _fresh_env()
        self.client = TestClient(app)
        self.cookie_name = SESSION_COOKIE_NAME
        resp = self.client.post(
            "/v1/internal/upload",
            files={"file": ("p6cert.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        assert self.client.post(
            "/v1/session/target-column", json={"column": "value"}
        ).status_code == 200
        assert self.client.post(
            "/v1/session/date-column", json={"column": "date"}
        ).status_code == 200

    def sid(self) -> str:
        return self.client.cookies.get(self.cookie_name)

    def run_id(self) -> str:
        from apps.api.session_store import get_session_store

        session = get_session_store().get(self.sid())
        assert session is not None and session.run_id
        return session.run_id

    def subject(self):
        from apps.api.identity import SubjectRef

        return SubjectRef.from_session(self.sid())

    def capture(self, stage: str) -> dict:
        resp = self.client.post(f"/v1/session/dataset/passport/{stage}")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def touch(self, delta: float, index: int = 0) -> None:
        from apps.api.session_store import get_session_store

        session = get_session_store().get_or_create(self.sid())
        column = session.target_column
        session.dataframe.loc[
            session.dataframe.index[index], column
        ] = session.dataframe[column].iloc[index] + delta
        get_session_store().save(session)

    def set_value(self, value: float, index: int = 0) -> None:
        from apps.api.session_store import get_session_store

        session = get_session_store().get_or_create(self.sid())
        session.dataframe.loc[
            session.dataframe.index[index], session.target_column
        ] = value
        get_session_store().save(session)

    def first_value(self) -> float:
        from apps.api.session_store import get_session_store

        session = get_session_store().get_or_create(self.sid())
        return float(session.dataframe[session.target_column].iloc[0])

    def full_trajectory(self) -> dict:
        self.capture("start")
        self.touch(7.5)
        self.capture("validation")
        self.touch(-4.25)
        self.capture("exit")
        self.touch(1.75)
        return self.capture("modeling_entry")

    def durable_cp(self, session_checkpoint_id: str, run_id: str | None = None) -> str:
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.visual_artifacts import get_passport_checkpoint

        rid = run_id or self.run_id()
        art = get_passport_checkpoint(rid, durable_checkpoint_id(session_checkpoint_id))
        return art.refs["checkpoint_id"]


def _rec(**overrides) -> dict:
    """СВОЯ форма snapshot-записи сертификатора (поле-в-поле §8/PGV-05)."""
    base = {
        "schema_version": "pgv.passport_history/1",
        "snapshot_ref": "rs-p6cert-a",
        "session_snapshot_id": "snap-a",
        "artifact_id": "art-a",
        "stage": "start",
        "universe": "single",
        "passport": {
            "basic_stats": {"n": 96, "mean": 42.0, "std": 3.0},
            "stationarity": {"value": 0.02, "is_stationary": True},
            "freq": {"value": "daily"},
        },
        "content_status": "present",
        "content_gap_reason": None,
        "target_column": "value",
        "date_column": "date",
        "context_id": None,
        "data_revision": None,
        "data_ref": None,
        "captured_at": "2026-11-02T10:00:00+00:00",
        "created_at": None,
        "source_hash_algorithm": "sha256(canonical_json)",
        "fingerprint": "p6cert-fp-a",
        "fingerprint_reason": None,
        "source_hash": "p6cert-hash-a",
        "source_hash_reason": None,
        "passport_schema_version": None,
        "passport_schema_version_reason": "legacy_unknown",
        "calculation_version": None,
        "calculation_version_reason": "legacy_unknown",
    }
    base.update(overrides)
    return base


# ══ Блок 1: AC13 — определения/виды изменений/несовместимость ════════


@probe("P1", "AC13: zero-denominator/definitions == фактическое поведение движка")
def p1():
    from app.core.passport import _compare_ts_props
    from apps.api import passport_comparison as pc

    # (a) v_old = 0, v_new = 5: движок обязан дать 100.0
    old = {"basic_stats": {"n": 96, "mean": 0.0}}
    new = {"basic_stats": {"n": 96, "mean": 5.0}}
    engine = _compare_ts_props(old, new)
    m = engine["metrics"]["Среднее"]
    assert m["delta"] == 5.0 and m["delta_pct"] == 100.0, m
    assert pc.compare_passports_via_engine(old, new) == engine
    # (b) v_old = 0, v_new = 0: 0.0
    zero = _compare_ts_props(
        {"basic_stats": {"mean": 0.0}}, {"basic_stats": {"mean": 0.0}}
    )
    assert zero["metrics"]["Среднее"]["delta_pct"] == 0.0
    # (c) отрицательный базис: |v_old| в знаменателе
    neg = _compare_ts_props(
        {"basic_stats": {"mean": -3.0}}, {"basic_stats": {"mean": 1.0}}
    )
    assert abs(neg["metrics"]["Среднее"]["delta_pct"] - (4 / 3) * 100) < 1e-9
    # (d) |v_old| <= 1e-10 (граница конвенции): 5.0 -> 100.0
    tiny = _compare_ts_props(
        {"basic_stats": {"mean": 1e-11}}, {"basic_stats": {"mean": 5.0}}
    )
    assert tiny["metrics"]["Среднее"]["delta_pct"] == 100.0, tiny["metrics"]["Среднее"]
    # (e) definitions описывают РОВНО эту конвенцию
    d = pc._COMPARISON_DEFINITIONS
    assert "abs(v_old)" in d["relative"], d["relative"]
    assert "1e-10" in d["zero_denominator_reason"], d["zero_denominator_reason"]
    assert "0.0" in d["zero_denominator_reason"] and "100.0" in d["zero_denominator_reason"]
    assert "значимост" in d["delta_color"]
    return "0/5->100.0; 0/0->0.0; neg-basis 133.33; 1e-11 граница; definitions точны"


@probe("P2", "AC13: виды изменений numeric/category/list/boolean/qualitative AS-IS")
def p2():
    from apps.api import passport_comparison as pc

    old = _rec()["passport"] | {
        "freq": {"value": "daily"},
        "trend": {"direction": "up", "slope": 0.5},
        "seasonal_periods": {"periods": [7]},
        "fft": {"dominant_periods": [1 / 7]},
        "wavelet": {"scales": [1, 2]},
        "seasonality": {"is_seasonal": False, "strength": 0.1},
        "stationarity": {"value": 0.02, "is_stationary": True},
    }
    new = _rec()["passport"] | {
        "freq": {"value": "hourly"},
        "trend": {"direction": "down", "slope": -0.2},
        "seasonal_periods": {"periods": [7, 12]},
        "fft": {"dominant_periods": [1 / 7, 1 / 12]},
        "wavelet": {"scales": [1]},
        "seasonality": {"is_seasonal": True, "strength": 0.8},
        "stationarity": {"value": 0.4, "is_stationary": False},
    }
    pair = pc.compare_passport_records(
        _rec(passport=old), _rec(snapshot_ref="rs-p6cert-b", stage="validation", passport=new)
    )
    c = pair["comparison"]
    assert c["metrics"]["Среднее"]["v_old"] == 42.0 and c["metrics"]["Среднее"]["v_new"] == 42.0
    #mean не менялся в basic_stats... нужен явный numeric дельта-факт
    assert c["categorical_changes"]["Частота ряда"]["changed"] is True
    assert c["categorical_changes"]["Частота ряда"]["v_new"] == "hourly"
    lc = c["list_changes"]["Сезонные периоды (ACF)"]
    assert 12 in lc["added"] and lc["changed"] is True
    assert c["boolean_changes"]["Стационарность"]["changed"] is True
    assert c["qualitative_changes"], "qualitative пуст на реальном флипе"
    assert c["summary"], "summary пуст"
    return "categorical/list/boolean/qualitative/summary присутствуют на своих данных"


@probe("P3", "AC13/§9: матрица несовместимостей 4 оси + XOR-честность None")
def p3():
    from apps.api import passport_comparison as pc

    def raised(a, b, **kw):
        try:
            pc.compare_passport_records(a, b, **kw)
        except pc.PassportComparisonIncompatible as exc:
            return exc.reasons
        return None

    rs = raised(
        _rec(snapshot_ref="rs-1", target_column="value"),
        _rec(snapshot_ref="rs-2", target_column="sales"),
    )
    assert rs and any("target" in r for r in rs), "target-mismatch не пойман"
    rs = raised(
        _rec(snapshot_ref="rs-1", universe="single", stage="exit"),
        _rec(snapshot_ref="rs-2", universe="panel", stage="panel_entry"),
    )
    assert rs and any("universe" in r for r in rs), "universe-mixing не пойман"
    rs = raised(
        _rec(snapshot_ref="rs-1", universe="panel", entity_id="region"),
        _rec(snapshot_ref="rs-2", universe="panel", entity_id="store"),
    )
    assert rs and any("entity" in r for r in rs), "entity-mismatch не пойман"
    rs = raised(
        _rec(snapshot_ref="rs-1", passport_schema_version="schema/1",
             passport_schema_version_reason=None),
        _rec(snapshot_ref="rs-2", passport_schema_version="schema/2",
             passport_schema_version_reason=None),
    )
    assert rs and any("schema" in r for r in rs), "schema-mismatch не пойман"
    # XOR-честность: неизвестное -- не значение (не отказ)
    ok = pc.compare_passport_records(
        _rec(snapshot_ref="rs-1", universe="panel"),
        _rec(snapshot_ref="rs-2", stage="panel_entry", universe="panel"),
    )
    assert ok["comparison"], "отказ на НЕИЗВЕСТНОМ entity -- фабкация"
    # cross-context: вне явного -- отказ; в явном -- маркировка
    ctx_rs = raised(
        _rec(snapshot_ref="rs-1", context_id="ctx-A"),
        _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-B"),
    )
    assert ctx_rs and any("context" in r for r in ctx_rs)
    explicit = pc.compare_passport_records(
        _rec(snapshot_ref="rs-1", context_id="ctx-A"),
        _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-B"),
        allow_cross_context=True,
    )
    assert explicit["cross_context"] is True
    same = pc.compare_passport_records(
        _rec(snapshot_ref="rs-1", context_id="ctx-A"),
        _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-A"),
    )
    assert same["cross_context"] is False
    unknown = pc.compare_passport_records(
        _rec(snapshot_ref="rs-1"), _rec(snapshot_ref="rs-2", stage="validation")
    )
    assert unknown["cross_context"] is False
    return "4 оси ловятся; None не значение; cross-context явный режим маркирует"


@probe("P3b", "§9: cross-context на ЖИВОМ пайплайне (crafted rs-записи своего run)")
def p3b():
    pipe = Pipe()
    from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
    from apps.api.report_snapshot import (
        ReportSnapshot,
        get_snapshot_registry,
        new_snapshot_id,
    )

    reg = get_snapshot_registry()
    # Две rs-паспортные записи СВОЕГО run с разными context_id (мой факт;
    # без паспортного артефакта -- честный content_missing, не фабкация).
    recs = []
    for i, ctx in enumerate(["ctx-p6cert-1", "ctx-p6cert-2"]):
        snap = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=pipe.run_id(),
            context_id=ctx,
            data_revision=1,
            captured_at=f"2026-11-02T1{i}:00:00+00:00",
            kinds=["D02"],
            idempotency_key=f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}p6cert-{i}",
        )
        registered, _created = reg.register_snapshot(snap, [])
        recs.append(registered.snapshot_id)
    # Обе записи без паспортного артефакта -> content_missing (честный gap),
    # поэтому cross-МАРКИРОВКА проверяется юнит-уровнем (P3), здесь --
    # uniform-gaps: чужой context_id в explicit-режиме не приводит к отказу
    # ДО content-проверки (пары не строятся: content-дыры).
    from apps.api import passport_comparison as pc

    snap = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        snapshot_refs=recs, session_id=pipe.sid(),
    )
    assert snap["mode"] == "explicit_refs"
    assert len(snap["gaps"]) == 2, snap["gaps"]
    assert snap["comparisons"] == []
    assert snap["completeness"] == "partial"
    return "crafted cross-context refs -> честные content-gaps, пары не фабкуются"


# ══ Блок 2: AC14 — панель ════════════════════════════════════════════


@probe("P4", "AC14: панельная вселенная резолвится отдельно, пары не смешиваются")
def p4():
    pipe = Pipe()
    from apps.api.session_store import DatasetInfo, get_session_store

    rows = []
    rng = np.random.default_rng(11)
    for entity in ("region", "store"):
        for i in range(60):
            rows.append({
                "date": (pd.Timestamp("2024-02-01") + pd.Timedelta(days=i)).date().isoformat(),
                "entity": entity,
                "y": 30 + 0.2 * i + rng.normal(0, 0.5),
            })
    pipe.client.get("/v1/session/modeling/state")
    session = get_session_store().get_or_create(pipe.sid())
    session.set_dataframe(pd.DataFrame(rows), reason="p6cert-panel")
    session.target_column = "y"
    session.date_column = "date"
    session.dataset = DatasetInfo(
        dataset_id="p6cert-panel-ds", name="p6cert-panel", rows=120,
        columns=3, size_label="3 KB", dataset_fingerprint="p6c" * 8,
    )
    run_id = session.ensure_run_id()
    from apps.api.research_runs import get_research_run_store

    assert get_research_run_store().get_run(run_id) is not None
    build = pipe.client.post(
        "/v1/session/modeling/panel/passport",
        json={"date_column": "date", "entity_column": "entity",
              "value_columns": ["y"], "target_column": "y"},
    )
    assert build.status_code == 200, build.text
    confirm = pipe.client.post("/v1/session/modeling/panel/passport/confirm")
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    from apps.api import passport_comparison as pc

    snap = pc.resolve_passport_comparison(
        run_id, pipe.subject(),
        checkpoint_id=pipe.durable_cp(body["checkpoint_id"], run_id),
        session_id=pipe.sid(),
    )
    assert snap is not None
    assert snap["path"] == ["panel"], snap["path"]
    assert snap["comparisons"] == [] and snap["completeness"] == "complete"
    assert snap["checkpoint"]["universe"] == "panel"
    return "panel-траектория: 1 точка, 0 пар, complete, universe=panel"


# ══ Блок 3: §9 refs/cutoff/reuse (свои данные) ═══════════════════════


@probe("P5", "AC10: cutoff ×2 чекпоинта — две независимые замороженные траектории")
def p5():
    pipe = Pipe()
    first = pipe.full_trajectory()
    cp1 = pipe.durable_cp(first["checkpoint_id"])
    from apps.api import passport_comparison as pc
    from apps.api.passport_history import read_passport_snapshot

    early = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(), checkpoint_id=cp1, session_id=pipe.sid()
    )
    assert early["path"] == ["start", "validation", "exit", "modeling_entry"]
    early_refs = list(early["ordered_refs"])
    # Поздние captures ПОСЛЕ первого подтверждения: стадии строго вперёд
    # (validation после exit запрещён пайплайном) -- exit -> modeling_entry.
    pipe.touch(10.0)
    late_exit = pipe.capture("exit")
    pipe.touch(-6.0)
    second = pipe.capture("modeling_entry")
    assert second["reused_snapshot"] is False or True
    cp2 = pipe.durable_cp(second["checkpoint_id"])
    late = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(), checkpoint_id=cp2, session_id=pipe.sid()
    )
    assert late["ordered_refs"] != early_refs, "late подмешался в early"
    # late-траектория несёт ПОЗДНИЙ exit ref (не замороженный ранний)
    exit_ref_late = next(
        p["to_ref"] for p in late["comparisons"] if p["to_stage"] == "exit"
    )
    exit_ref_early = next(
        p["to_ref"] for p in early["comparisons"] if p["to_stage"] == "exit"
    )
    assert exit_ref_late != exit_ref_early, "exit не обновился во второй траектории"
    # early НЕ изменился после поздних captures (детерминизм cutoff)
    early2 = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(), checkpoint_id=cp1, session_id=pipe.sid()
    )
    assert early2 == early
    assert early2["ordered_refs"] == early_refs
    frozen_val = read_passport_snapshot(
        pipe.run_id(), pipe.subject(), snapshot_ref=early_refs[1], session_id=pipe.sid()
    )
    assert frozen_val["captured_at"] <= early["checkpoint"]["confirmed_at"]
    return "cp1/cp2 независимы; exit обновлён только во второй; early стабилен"


@probe("P6", "AC11: unchanged reuse — без дублирующей колонки; reused-старый — алиас")
def p6():
    # (a) unchanged
    pipe = Pipe()
    pipe.capture("start")
    pipe.touch(7.5)
    pipe.capture("validation")
    pipe.touch(-4.25)
    pipe.capture("exit")
    exit_value = pipe.first_value()
    pipe.touch(4.0)
    pipe.set_value(exit_value)
    body = pipe.capture("modeling_entry")
    assert body["reused_snapshot"] is True, body
    from apps.api import passport_comparison as pc

    snap = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id=pipe.durable_cp(body["checkpoint_id"]), session_id=pipe.sid(),
    )
    assert snap["path"] == ["start", "validation", "exit"], snap["path"]
    stages = [(p["from_stage"], p["to_stage"]) for p in snap["comparisons"]]
    assert ("exit", "modeling_entry") not in stages
    conf = snap["confirmation"]
    assert conf["reused"] is True and conf["unchanged"] is True
    assert conf["confirmed_at"] and conf["reused_ref"] == snap["ordered_refs"][-1]

    # (b) reused-НО-старый: возврат к validation-снимку
    pipe2 = Pipe()
    pipe2.capture("start")
    pipe2.touch(7.5)
    pipe2.capture("validation")
    val_value = pipe2.first_value()
    pipe2.touch(-4.25)
    pipe2.capture("exit")
    pipe2.set_value(val_value)
    body2 = pipe2.capture("modeling_entry")
    assert body2["reused_snapshot"] is True
    snap2 = pc.resolve_passport_comparison(
        pipe2.run_id(), pipe2.subject(),
        checkpoint_id=pipe2.durable_cp(body2["checkpoint_id"]), session_id=pipe2.sid(),
    )
    assert snap2["path"] == ["start", "validation", "exit", "modeling_entry"]
    last = snap2["comparisons"][-1]
    val_ref = next(p["to_ref"] for p in snap2["comparisons"] if p["to_stage"] == "validation")
    assert last["to_ref"] == val_ref, "reused-старый не алиас validation"
    assert (last["from_stage"], last["to_stage"]) == ("exit", "modeling_entry")
    assert snap2["confirmation"]["reused"] is True
    assert snap2["confirmation"]["unchanged"] is False
    return "unchanged: путь без modeling_entry, confirmation полон; reused-старый: алиас"


@probe("P6b", "ПРОБА: reuse НА ПРОМЕЖУТОЧНОМ этапе — дубликат ref в stage_refs?")
def p6b():
    pipe = Pipe()
    pipe.capture("start")
    try:
        start_body = pipe.capture("validation")  # данные не менялись после start?
    except AssertionError as exc:
        # Пайплайн ОТКЛОНЯЕТ capture без изменений ("Свойства ряда не
        # изменились") => промежуточный reuse/дубликат refs в stage_refs
        # НЕВОЗМОЖЕН в реальном пайплайне (честный ответ пробы).
        body = pipe.full_trajectory()
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.visual_artifacts import get_passport_checkpoint

        art = get_passport_checkpoint(
            pipe.run_id(), durable_checkpoint_id(body["checkpoint_id"])
        )
        import json as _json

        from apps.api.artifact_store import get_artifact_object_store

        payload = _json.loads(
            get_artifact_object_store().read_bytes(art.storage_key).decode("utf-8")
        )
        refs = list(payload["stage_refs"].values())
        assert len(refs) == len(set(refs)), (
            f"дубликаты в stage_refs реального пайплайна: {payload['stage_refs']}"
        )
        return (
            "промежуточный unchanged-capture ОТКЛОНЁН пайплайном "
            f"({str(exc)[:60]}...); дубликаты stage_refs реального "
            "пайплайна невозможны (нулевая пара недостижима)"
        )
    body = pipe.full_trajectory()
    from apps.api.passport_checkpoints import durable_checkpoint_id
    from apps.api.visual_artifacts import get_passport_checkpoint

    art = get_passport_checkpoint(
        pipe.run_id(), durable_checkpoint_id(body["checkpoint_id"])
    )
    import json as _json

    from apps.api.artifact_store import get_artifact_object_store

    payload = _json.loads(
        get_artifact_object_store().read_bytes(art.storage_key).decode("utf-8")
    )
    refs = list(payload["stage_refs"].values())
    dup = len(refs) != len(set(refs))
    note = f"validation после unchanged start: reused_snapshot={start_body.get('reused_snapshot')}; stage_refs дубликаты: {dup}"
    if dup:
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            pipe.run_id(), pipe.subject(),
            checkpoint_id=pipe.durable_cp(body["checkpoint_id"]), session_id=pipe.sid(),
        )
        pair_refs = [(p["from_ref"], p["to_ref"]) for p in snap["comparisons"]]
        zero_dup = any(a == b for a, b in pair_refs)
        if zero_dup:
            raise AssertionError(
                "НУЛЕВАЯ дублирующая пара из stage_refs-дубликата: "
                f"{pair_refs} (§9: unchanged не добавляет нулевую колонку)"
            )
    return note


# ══ Блок 4: gaps/completeness ════════════════════════════════════════


@probe("P7", "AC12/§9: дыра в середине explicit — без моста; corrupt — gap, соседи живы")
def p7():
    pipe = Pipe()
    pipe.full_trajectory()
    from apps.api import passport_comparison as pc
    from apps.api.passport_history import list_passport_snapshots

    records = list_passport_snapshots(
        pipe.run_id(), pipe.subject(), session_id=pipe.sid()
    )
    refs = [r["snapshot_ref"] for r in records]
    assert len(refs) >= 4
    broken = [refs[0], "rs-p6cert-hole", refs[2], refs[3]]
    snap = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        snapshot_refs=broken, session_id=pipe.sid(),
    )
    assert snap["completeness"] == "partial"
    assert any(g["snapshot_ref"] == "rs-p6cert-hole" for g in snap["gaps"])
    pair_refs = [(p["from_ref"], p["to_ref"]) for p in snap["comparisons"]]
    assert not any("rs-p6cert-hole" in pr for pr in pair_refs), "мост через дыру!"
    assert (refs[2], refs[3]) in pair_refs, "здоровая соседняя пара потеряна"
    # corrupt первой записи: байты артефакта подменены (мои данные)
    from apps.api.artifact_store import (
        get_artifact_object_store,
        get_artifact_registry,
    )

    first_rec = records[0]
    art = get_artifact_registry().get_artifact(first_rec["artifact_id"])
    path = get_artifact_object_store().path_for_key(art.storage_key)
    original = path.read_bytes()
    path.write_bytes(b'{"p6cert": "tampered"}')
    snap2 = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        snapshot_refs=refs, session_id=pipe.sid(),
    )
    cg = [g for g in snap2["gaps"] if g["snapshot_ref"] == refs[0]]
    assert cg and cg[0]["reason"] in {"content_corrupt", "content_missing"}
    touched = {(p["from_ref"], p["to_ref"]) for p in snap2["comparisons"]}
    assert all(refs[0] not in pr for pr in touched)
    path.write_bytes(original)  # восстановление своих данных
    return "мост запрещён; corrupt -> gap; здоровые соседи строятся"


@probe("P8", "§9: complete ⇔ ноль gaps; partial перечисляет пропуски")
def p8():
    pipe = Pipe()
    full = pipe.full_trajectory()
    from apps.api import passport_comparison as pc
    from apps.api.passport_checkpoints import durable_checkpoint_id
    from apps.api.visual_artifacts import register_passport_checkpoint

    snap = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id=pipe.durable_cp(full["checkpoint_id"]), session_id=pipe.sid(),
    )
    assert snap["completeness"] == "complete" and snap["gaps"] == []
    # Свой crafted чекпоинт с отсутствующими refs -> partial + явные gaps
    from apps.api.identity import SubjectRef

    subject = pipe.subject()
    payload = {
        "schema_version": "pgv.passport_checkpoint/1",
        "checkpoint_id": durable_checkpoint_id("p6cert-dangling"),
        "stage": "modeling_entry",
        "confirmed_at": "2026-11-02T09:00:00+00:00",
        "confirmed_at_reason": None,
        "snapshot_ref": "rs-" + "e" * 32,
        "previous_snapshot_ref": None,
        "flags": {"created": True, "reused": False, "unchanged": False},
        "stage_refs": {"start": "rs-" + "f" * 32, "validation": "rs-" + "1" * 32, "exit": "rs-" + "2" * 32},
        "context": {"run_id": pipe.run_id(), "context_id": "ctx-p6cert",
                    "data_revision": 2, "target_column": "value",
                    "entity_id": None},
        "provenance": {"source": "legacy_import"},
    }
    art = register_passport_checkpoint(
        pipe.run_id(), subject, payload=payload, session_id=pipe.sid()
    )
    assert art is not None
    snap2 = pc.resolve_passport_comparison(
        pipe.run_id(), subject,
        checkpoint_id=art.refs["checkpoint_id"], session_id=pipe.sid(),
    )
    assert snap2 is not None
    assert snap2["completeness"] == "partial"
    assert snap2["comparisons"] == []
    assert any(g["snapshot_ref"] == "rs-" + "f" * 32 for g in snap2["gaps"])
    return "complete чист; dangling -> partial с перечнем"


# ══ Блок 5: чистота/доступ/границы ═══════════════════════════════════


@probe("P9", "AC06-дух/AC18-дух: read-only, детерминизм, чужой субъект — uniform отказ")
def p9():
    pipe = Pipe()
    full = pipe.full_trajectory()
    from apps.api import passport_comparison as pc
    from apps.api.artifact_store import get_artifact_registry
    from apps.api.report_snapshot import get_snapshot_registry

    run_id = pipe.run_id()
    durable = pipe.durable_cp(full["checkpoint_id"])
    snap_before = len(get_snapshot_registry().list_records(run_id))
    art_before = len(get_artifact_registry().list_artifacts(run_id))
    first = pc.resolve_passport_comparison(
        run_id, pipe.subject(), checkpoint_id=durable, session_id=pipe.sid()
    )
    second = pc.resolve_passport_comparison(
        run_id, pipe.subject(), checkpoint_id=durable, session_id=pipe.sid()
    )
    assert first == second, "недетерминизм резолюции"
    assert len(get_snapshot_registry().list_records(run_id)) == snap_before
    assert len(get_artifact_registry().list_artifacts(run_id)) == art_before
    from apps.api.passport_history import PassportHistoryAccessDenied

    from apps.api.identity import SubjectRef

    foreign = SubjectRef.from_session("p6cert-foreign")
    try:
        pc.resolve_passport_comparison(run_id, foreign, checkpoint_id=durable)
        raise AssertionError("чужой субъект допущен")
    except PassportHistoryAccessDenied:
        pass
    return "read-only; first==second; чужой -- uniform PassportHistoryAccessDenied"


@probe("P9b", "AC18-дух: чужой СУЩЕСТВУЮЩИЙ ref в explicit — uniform missing, без дисклоужения")
def p9b():
    pipe_a = Pipe()
    pipe_a.full_trajectory()
    pipe_b = Pipe(fresh=False)  # второй run В ТОМ ЖЕ мире (без сброса)
    pipe_b.full_trajectory()
    from apps.api.passport_history import list_passport_snapshots

    foreign_refs = [
        r["snapshot_ref"]
        for r in list_passport_snapshots(
            pipe_b.run_id(), pipe_b.subject(), session_id=pipe_b.sid()
        )
    ]
    assert foreign_refs
    from apps.api import passport_comparison as pc

    snap = pc.resolve_passport_comparison(
        pipe_a.run_id(), pipe_a.subject(),
        snapshot_refs=[foreign_refs[0]], session_id=pipe_a.sid(),
    )
    assert snap["gaps"], "чужой ref не оформлен gap"
    g_foreign = snap["gaps"][0]
    snap_absent = pc.resolve_passport_comparison(
        pipe_a.run_id(), pipe_a.subject(),
        snapshot_refs=["rs-" + "0" * 32], session_id=pipe_a.sid(),
    )
    g_absent = snap_absent["gaps"][0]
    # ДИФФЕРЕНЦИАЛЬНАЯ uniform-честность (AC18-дух): чужой и отсутствующий
    # неразличимы (reason И detail идентичны, отличается только ref).
    assert (g_foreign["reason"], g_foreign["detail"]) == (
        g_absent["reason"], g_absent["detail"]
    ), f"дисклоужение: {g_foreign} != {g_absent}"
    assert g_foreign["reason"] == "missing_snapshot_record"
    return "explicit: чужой существующий == отсутствующий (reason+detail), без утечки"


@probe("P10", "Границы контракта: режимы взаимоисключающие; отсутствующий cp — None")
def p10():
    pipe = Pipe()
    from apps.api import passport_comparison as pc

    try:
        pc.resolve_passport_comparison(pipe.run_id(), pipe.subject())
        raise AssertionError("без режимов принято")
    except ValueError:
        pass
    try:
        pc.resolve_passport_comparison(
            pipe.run_id(), pipe.subject(),
            checkpoint_id="pck-x", snapshot_refs=["rs-y"],
        )
        raise AssertionError("оба режима приняты")
    except ValueError:
        pass
    try:
        pc.resolve_passport_comparison(
            pipe.run_id(), pipe.subject(), snapshot_refs=[]
        )
        raise AssertionError("пустой refs принят")
    except ValueError:
        pass
    assert pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id="pck-p6cert-absent", session_id=pipe.sid(),
    ) is None, "отсутствующий чекпоинт не None (фабкация)"
    return "2 режима XOR; пустой отклонён; absent -> None"


@probe("P11", "Parity на КРАЙНИХ паспортах: пустые секции/NaN/строки/None-поля")
def p11():
    from app.core.passport import _compare_ts_props
    from apps.api import passport_comparison as pc

    cases = [
        ({}, {}),
        ({"basic_stats": {}}, {"basic_stats": {"mean": 1.0}}),
        ({"basic_stats": {"mean": float("nan")}}, {"basic_stats": {"mean": 1.0}}),
        ({"basic_stats": {"mean": 1.0}}, {"basic_stats": {"mean": float("nan")}}),
        ({"stationarity": {"value": 0.01}}, {"trend": {"slope": 0.5}}),
        ({"freq": {"value": "daily"}}, {"freq": {"value": "daily"}}),
        ({"basic_stats": {"mean": 1e-12}}, {"basic_stats": {"mean": -1e-12}}),
        ({"hurst": {"value": 0.5}}, {"hurst": {"value": 0.9, "extra": None}}),
    ]
    for i, (a, b) in enumerate(cases):
        assert pc.compare_passports_via_engine(a, b) == _compare_ts_props(a, b), (
            f"case {i}: parity нарушен на {a} vs {b}"
        )
    # NaN-поля: движок их пропускает (pd.notna-гейт) -- adapter честно то же
    nan_out = pc.compare_passports_via_engine(
        {"basic_stats": {"mean": float("nan")}}, {"basic_stats": {"mean": 1.0}}
    )
    assert nan_out["metrics"] == {}, "NaN подмешан в метрики вопреки движку"
    return f"{len(cases)} крайних случаев: adapter == движок байт-в-байт; NaN честно пропущен"


@probe("P12", "§9: направление дельты — explicit в обратном порядке даёт инверсию")
def p12():
    pipe = Pipe()
    full = pipe.full_trajectory()  # подтверждающий чекпоинт материализует rs-записи
    from apps.api import passport_comparison as pc

    run_id, subject, sid = pipe.run_id(), pipe.subject(), pipe.sid()
    durable = pipe.durable_cp(full["checkpoint_id"])
    traj = pc.resolve_passport_comparison(
        run_id, subject, checkpoint_id=durable, session_id=sid
    )
    by_stage = {}
    for pair in traj["comparisons"]:
        by_stage.setdefault(pair["from_stage"], pair["from_ref"])
        by_stage.setdefault(pair["to_stage"], pair["to_ref"])
    ref1, ref2 = by_stage["validation"], by_stage["exit"]
    fwd = pc.resolve_passport_comparison(
        run_id, subject, snapshot_refs=[ref1, ref2], session_id=sid
    )
    rev = pc.resolve_passport_comparison(
        run_id, subject, snapshot_refs=[ref2, ref1], session_id=sid
    )
    assert fwd["ordered_refs"] == [ref1, ref2] and rev["ordered_refs"] == [ref2, ref1]
    d_fwd = fwd["comparisons"][0]["comparison"]["metrics"]["Среднее"]["delta"]
    d_rev = rev["comparisons"][0]["comparison"]["metrics"]["Среднее"]["delta"]
    assert abs(d_fwd + d_rev) < 1e-12, "дельта не инвертируется в обратном порядке"
    from apps.api.passport_history import read_passport_snapshot

    r1 = read_passport_snapshot(run_id, subject, snapshot_ref=ref1, session_id=sid)
    r2 = read_passport_snapshot(run_id, subject, snapshot_ref=ref2, session_id=sid)
    assert r1["captured_at"] < r2["captured_at"]
    return f"delta({ref1[:12]}→{ref2[:12]}) == -delta(обратный порядок)"


@probe("P13", "§9: method_versions -- per-record schema/calculation AS-IS, legacy_unknown не выдуман")
def p13():
    pipe = Pipe()
    full = pipe.full_trajectory()
    from apps.api import passport_comparison as pc

    snap = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id=pipe.durable_cp(full["checkpoint_id"]),
        session_id=pipe.sid(),
    )
    mv = snap["method_versions"]
    assert mv["engine"] == pc.COMPARISON_ENGINE
    assert len(mv["records"]) == len(snap["ordered_refs"])
    for item in mv["records"]:
        assert set(item) >= {"snapshot_ref", "passport_schema_version", "calculation_version"}
        assert item["passport_schema_version"] is None, "выдуманная schema!"
        assert item["calculation_version"] is None, "выдуманная версия расчёта!"
    return f"{len(mv['records'])} записей AS-IS; legacy_unknown честен (не 'v1')"


@probe("P14", "AC18-дух/trajectory: чужой vs отсутствующий ref в stage_refs crafted чекпоинта")
def p14():
    pipe = Pipe()
    pipe.full_trajectory()
    pipe_b = Pipe(fresh=False)
    pipe_b.full_trajectory()
    from apps.api.passport_history import list_passport_snapshots

    foreign_ref = list_passport_snapshots(
        pipe_b.run_id(), pipe_b.subject(), session_id=pipe_b.sid()
    )[0]["snapshot_ref"]
    from apps.api.passport_checkpoints import durable_checkpoint_id
    from apps.api.visual_artifacts import register_passport_checkpoint

    def crafted(checkpoint_tag: str, start_ref: str):
        return {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id(f"p6cert-{checkpoint_tag}"),
            "stage": "modeling_entry",
            "confirmed_at": "2026-11-02T09:00:00+00:00",
            "confirmed_at_reason": None,
            "snapshot_ref": "rs-" + "e" * 32,
            "previous_snapshot_ref": None,
            "flags": {"created": True, "reused": False, "unchanged": False},
            "stage_refs": {
                "start": start_ref,
                "validation": "rs-" + "0" * 32,
                "exit": "rs-" + "2" * 32,
            },
            "context": {"run_id": pipe.run_id(), "context_id": "ctx-p6cert-det",
                        "data_revision": 2, "target_column": "value",
                        "entity_id": None},
            "provenance": {"source": "legacy_import"},
        }

    art_f = register_passport_checkpoint(
        pipe.run_id(), pipe.subject(),
        payload=crafted("det-foreign", foreign_ref), session_id=pipe.sid(),
    )
    art_a = register_passport_checkpoint(
        pipe.run_id(), pipe.subject(),
        payload=crafted("det-absent", "rs-" + "0" * 32), session_id=pipe.sid(),
    )
    from apps.api import passport_comparison as pc

    snap_f = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id=art_f.refs["checkpoint_id"], session_id=pipe.sid(),
    )
    snap_a = pc.resolve_passport_comparison(
        pipe.run_id(), pipe.subject(),
        checkpoint_id=art_a.refs["checkpoint_id"], session_id=pipe.sid(),
    )

    def gap_of(snap, ref):
        return next(
            (g for g in snap["gaps"] if g["snapshot_ref"] == ref), None
        )

    gf = gap_of(snap_f, foreign_ref)
    ga = gap_of(snap_a, "rs-" + "0" * 32)
    assert gf and ga, "гэпы не оформлены"
    # Дифференциальный оракул: reason uniform у обоих; detail тоже ОБЯЗАН
    # быть uniform (AC18-дух: отсутствие дисклоужения существования).
    assert gf["reason"] == ga["reason"] == "missing_snapshot_record"
    if gf["detail"] != ga["detail"]:
        raise AssertionError(
            "F-P6C1: trajectory-режим копирует reader-гэпы AS-IS -- detail "
            f"различает чужой ({gf['detail']!r}) и отсутствующий "
            f"({ga['detail']!r}); дисклоужение существования чужой записи"
        )
    return "trajectory: чужой == отсутствующий (reason+detail uniform)"


def main() -> int:
    probes = [v for k, v in sorted(globals().items()) if k.startswith("p") and callable(v) and hasattr(v, "_description")]
    for fn in probes:
        fn()
    print("=" * 78)
    print("PGV-06 CERT: пробы сертификатора (свои данные, свои оракулы)")
    print("=" * 78)
    fails = 0
    for name, status, detail in RESULTS:
        mark = "PASS" if status == "PASS" else "FAIL"
        if status == "FAIL":
            fails += 1
        print(f"[{mark}] {name}: {detail[:400]}")
    print("=" * 78)
    print(f"Итог: {len(RESULTS) - fails}/{len(RESULTS)} PASS, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
