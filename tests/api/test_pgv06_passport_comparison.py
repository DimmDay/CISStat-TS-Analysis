"""TDD-корпус PGV-06 (spec_passport_graphics_visual.md §9/§13,
строка PGV-06): Pure comparison resolver -- общий pure comparison
engine, выделяемый из session orchestration; существующая
``_compare_ts_props`` -- через versioned adapter, без дублирования
формул.

ПОСТАНОВКА (§13): «Pure comparison resolver; точки изменения --
app/core/passport/session adapter; критерий -- Прежняя семантика refs,
cutoff/reuse/incompatible contexts проверены».

Ключевые инварианты поставки:
  §9    -- Frozen PassportComparisonSnapshot/1: ordered refs/path,
           checkpoint metadata, numeric/category/list/qualitative
           changes, method/schema versions, gaps/context;
  AC13  -- numeric/category/list/qualitative, zero denominator reason,
           несовместимость закрыта (target/entity/schema);
  AC14  -- panel entities/universe не смешиваются с single-series;
  прежняя семантика -- refs (путь из immutable refs, не latest),
  cutoff (замороженные stage_refs на момент подтверждения), reuse
  (unchanged modeling_entry БЕЗ нулевой дублирующей колонки; отдельная
  строка подтверждения с confirmed_at и reused ref), incompatible
  contexts (target/entity/schema -> отказ; cross-context -- только
  явный режим с маркировкой);
  §9    -- Missing validation -- gap, не ноль; complete/partial честны;
  AC06-дух -- резолюция read-only, без записи в durable state.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

RUN_ID = "RUN-P06A0001"
SESSION_ID = "p06-seed-session"


# ── Изоляция среды (паттерн PGV-02/03/04/05) ─────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (свои данные; паттерн PGV-05) ────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"date": dates, "value": values})
    return frame.to_csv(index=False)


def _upload(client: TestClient) -> None:
    import io

    response = client.post(
        "/v1/internal/upload",
        files={"file": ("p06.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    resp = client.post("/v1/session/target-column", json={"column": "value"})
    assert resp.status_code == 200, resp.text
    resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert resp.status_code == 200, resp.text


def _capture(client: TestClient, stage: str) -> dict:
    resp = client.post(f"/v1/session/dataset/passport/{stage}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _capture_new(client: TestClient, stage: str, delta: float) -> dict:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get_or_create(session_id)
    column = session.target_column
    session.dataframe.loc[
        session.dataframe.index[0], column
    ] = session.dataframe[column].iloc[0] + delta
    get_session_store().save(session)
    return _capture(client, stage)


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get_or_create(session_id)
    column = session.target_column
    session.dataframe.loc[
        session.dataframe.index[0], column
    ] = session.dataframe[column].iloc[0] + delta
    get_session_store().save(session)


def _first_target_value(client: TestClient) -> float:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get_or_create(session_id)
    return float(session.dataframe[session.target_column].iloc[0])


def _set_first_target_value(client: TestClient, value: float) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get_or_create(session_id)
    column = session.target_column
    session.dataframe.loc[session.dataframe.index[0], column] = value
    get_session_store().save(session)


def _run_id_of(client: TestClient) -> str:
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.run_id
    return session.run_id


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    owner_subject: str | None = None,
    tenant_id: str | None = None,
):
    """Registry-уровень: research run без клиентской сессии."""
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p06" * 8,
        dataset_name="pgv06-comparison-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=owner_subject
        or SubjectRef.from_session(session_id).subject_id,
        tenant_id=tenant_id or DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def _client_session_id(client: TestClient) -> str:
    return client.cookies.get(SESSION_COOKIE_NAME)


def _client_subject(client: TestClient):
    """Субъект cookie-сессии клиента: run пайплайна создаётся
    приложением с владельцем = субъект ЭТОЙ сессии."""
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(_client_session_id(client))


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p06-foreign-session")


def _capture_full_trajectory(client: TestClient) -> dict:
    """start -> validation -> exit -> modeling_entry (новый снимок)."""
    _capture(client, "start")
    _capture_new(client, "validation", 5.0)
    _capture_new(client, "exit", -3.0)
    return _capture_new(client, "modeling_entry", 2.0)


def _durable_checkpoint(run_id: str, session_checkpoint_id: str):
    from apps.api.passport_checkpoints import durable_checkpoint_id
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(
        run_id, durable_checkpoint_id(session_checkpoint_id)
    )


def _durable_checkpoint_id(client_or_run, session_checkpoint_id: str) -> str:
    """Durable-идентификатор чекпоинта (pck-*): контракт резолвера --
    durable-слой (picker PGV-05 отдаёт durable ids), не session-uuid."""
    from apps.api.session_store import get_session_store as _g

    _ = _g
    run_id = (
        client_or_run
        if isinstance(client_or_run, str)
        else _run_id_of(client_or_run)
    )
    return _durable_checkpoint(run_id, session_checkpoint_id).refs["checkpoint_id"]


PANEL_COLUMNS = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "y",
}


def _panel_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for entity in ("entity", "store"):
        for i in range(60):
            rows.append(
                {
                    "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).date().isoformat(),
                    "entity": entity,
                    "y": 10 + 0.1 * i + rng.normal(0, 0.3),
                }
            )
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# 1. Границы модуля и versioned adapter (движок без дублирования)
# ══════════════════════════════════════════════════════════════════════


class TestModuleBoundaries:
    def test_module_imports_exclude_session_store_pandas_redis(self):
        """Pure resolver: SessionStore/pandas/numpy/redis недопустимы --
        сравнение -- чистая функция immutable refs (§9), не
        orchestration (AST-гейт, паттерн PGV-05)."""
        source = Path("apps/api/passport_comparison.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_roots = {"session_store", "pandas", "numpy", "redis"}
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imported_roots.add(node.module.split(".")[0])
        offenders = sorted(imported_roots & forbidden_roots)
        assert offenders == [], f"Запрещённые импорты: {offenders}"

    def test_session_orchestration_no_longer_imports_engine_directly(self):
        """Выделение engine из session orchestration (§9): routers/session
        больше НЕ импортирует приватный движок напрямую -- только
        versioned adapter (mutant: прямая ссылка на _compare_ts_props
        в orchestration умирает)."""
        source = Path("apps/api/routers/session.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.core.passport":
                names = {alias.name for alias in node.names}
                assert "_compare_ts_props" not in names, (
                    "session orchestration импортирует движок напрямую "
                    "вместо versioned adapter"
                )

    def test_adapter_delegates_to_existing_engine_without_duplication(self, client):
        """Adapter возвращает ТОЧНО вывод существующего движка (формулы
        не дублируются и не меняются): равенство на реальных паспортах."""
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison
        from apps.api.passport_history import list_passport_snapshots

        run_id = _run_id_of(client)
        records = list_passport_snapshots(
            run_id, _client_subject(client), session_id=_client_session_id(client)
        )
        assert len(records) >= 2
        for i in range(len(records) - 1):
            old_p = records[i]["passport"]
            new_p = records[i + 1]["passport"]
            assert passport_comparison.compare_passports_via_engine(old_p, new_p) == (
                _compare_ts_props(old_p, new_p)
            )

    def test_adapter_is_pure_no_store_required(self):
        """Adapter -- чистая функция двух dict: вызывается без сторов,
        cookie и реестров; повторный вызов даёт идентичный результат."""
        from apps.api import passport_comparison

        props_old = {
            "basic_stats": {"n": 10, "mean": 1.0, "std": 0.5},
            "stationarity": {"value": 0.01, "is_stationary": True},
        }
        props_new = {
            "basic_stats": {"n": 12, "mean": 2.0, "std": 0.7},
            "stationarity": {"value": 0.04, "is_stationary": False},
        }
        first = passport_comparison.compare_passports_via_engine(props_old, props_new)
        second = passport_comparison.compare_passports_via_engine(props_old, props_new)
        assert first == second
        assert first["metrics"]["Число наблюдений"]["delta"] == 2.0

    def test_engine_version_is_pinned(self):
        """Versioned adapter: метод/движок пинятся в контракте (§9:
        method/schema versions) -- не анонимный вызов."""
        from apps.api import passport_comparison

        assert passport_comparison.COMPARISON_ENGINE["id"] == (
            "app.core.passport._compare_ts_props"
        )
        assert isinstance(passport_comparison.COMPARISON_ENGINE["version"], str)
        assert passport_comparison.COMPARISON_ENGINE["version"]
        assert passport_comparison.PASSPORT_COMPARISON_SCHEMA_VERSION == (
            "pgv.passport_comparison/1"
        )


# ══════════════════════════════════════════════════════════════════════
# 2. Резолюция по чекпоинту: refs/cutoff/reuse (прежняя семантика)
# ══════════════════════════════════════════════════════════════════════


class TestTrajectoryCheckpointMode:
    def test_full_trajectory_ordered_refs_and_pairs(self, client):
        """Refs-семантика: путь -- ordered immutable refs замороженной
        траектории (start -> validation -> exit -> modeling_entry),
        пары -- соседние точки; попарный вывод == прямой вызов движка
        на паспортах тех же записей; IDs доступны."""
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from apps.api import passport_comparison

        run_id = _run_id_of(client)
        snapshot = passport_comparison.resolve_passport_comparison(
            run_id, _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        assert snapshot["schema_version"] == "pgv.passport_comparison/1"
        assert snapshot["mode"] == "trajectory_checkpoint"
        assert snapshot["path"] == ["start", "validation", "exit", "modeling_entry"]
        assert len(snapshot["ordered_refs"]) == 4
        assert len(set(snapshot["ordered_refs"])) == 4
        assert len(snapshot["comparisons"]) == 3
        stages = [
            (pair["from_stage"], pair["to_stage"])
            for pair in snapshot["comparisons"]
        ]
        assert stages == [
            ("start", "validation"),
            ("validation", "exit"),
            ("exit", "modeling_entry"),
        ]
        for pair in snapshot["comparisons"]:
            assert pair["from_snapshot_id"] and pair["to_snapshot_id"]
            assert pair["from_ref"] and pair["to_ref"]
        # Попарный вывод == движок на тех же паспортах (parity)
        from app.core.passport import _compare_ts_props
        from apps.api.passport_history import read_passport_snapshot

        subject = _client_subject(client)
        session_id = _client_session_id(client)
        for pair in snapshot["comparisons"]:
            old_rec = read_passport_snapshot(
                run_id, subject, snapshot_ref=pair["from_ref"], session_id=session_id,
            )
            new_rec = read_passport_snapshot(
                run_id, subject, snapshot_ref=pair["to_ref"], session_id=session_id,
            )
            assert pair["comparison"] == _compare_ts_props(
                old_rec["passport"], new_rec["passport"]
            )

    def test_frozen_refs_cutoff_not_latest_of_each_stage(self, client):
        """Cutoff-семантика: траектория на выбранное подтверждение --
        замороженные stage_refs на момент подтверждения; более поздний
        capture НЕ подмешивается в раннюю траекторию (не latest каждого
        stage; старые snapshots не переписываются)."""
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        checkpoint_id = capture["checkpoint_id"]
        run_id = _run_id_of(client)
        subject = _client_subject(client)
        session_id = _client_session_id(client)

        # Более поздние captures ПОСЛЕ подтверждения чекпоинта...
        _capture_new(client, "exit", 1.5)
        _capture_new(client, "modeling_entry", 0.5)

        from apps.api import passport_comparison
        from apps.api.passport_history import read_passport_snapshot

        early = passport_comparison.resolve_passport_comparison(
            run_id, subject, checkpoint_id=_durable_checkpoint_id(client, checkpoint_id),
            session_id=session_id,
        )
        # ...не меняют раннюю траекторию: путь и пары -- прежние.
        assert early["path"] == ["start", "validation", "exit", "modeling_entry"]
        assert len(early["comparisons"]) == 3
        validation_ref = next(
            p["to_ref"] for p in early["comparisons"] if p["to_stage"] == "validation"
        )
        frozen_validation = read_passport_snapshot(
            run_id, subject, snapshot_ref=validation_ref, session_id=session_id,
        )
        # Validation -- ЗАМОРОЖЕННЫЙ снимок на момент подтверждения.
        assert frozen_validation["captured_at"] <= early["checkpoint"]["confirmed_at"]
        # И ранний modeling_entry -- не более поздний снимок.
        modeling_ref = next(
            p["to_ref"] for p in early["comparisons"]
            if p["to_stage"] == "modeling_entry"
        )
        frozen_modeling = read_passport_snapshot(
            run_id, subject, snapshot_ref=modeling_ref, session_id=session_id,
        )
        assert frozen_modeling["captured_at"] <= early["checkpoint"]["confirmed_at"]

    def test_unchanged_reuse_no_duplicate_zero_delta_column(self, client):
        """Reuse-семантика (§9/AC11): unchanged modeling_entry не
        добавляет нулевую дублирующую колонку -- путь заканчивается
        source-этапом; отдельная строка подтверждения содержит
        confirmed_at и reused ref; сравнения -- без нулевой пары."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 5.0)
        _capture_new(client, "exit", -3.0)
        exit_value = _first_target_value(client)
        # Возврат ряда к состоянию exit-снимка -> unchanged reuse
        _mutate_target(client, 4.0)
        _set_first_target_value(client, exit_value)
        capture = client.post("/v1/session/dataset/passport/modeling_entry")
        assert capture.status_code == 200, capture.text
        body = capture.json()
        assert body["reused_snapshot"] is True

        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, body["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        assert snapshot["path"] == ["start", "validation", "exit"]
        pair_stages = [
            (p["from_stage"], p["to_stage"]) for p in snapshot["comparisons"]
        ]
        assert ("exit", "modeling_entry") not in pair_stages
        assert len(snapshot["comparisons"]) == 2
        # Отдельная строка подтверждения: confirmed_at + reused ref
        confirmation = snapshot["confirmation"]
        assert confirmation["confirmed_at"]
        assert confirmation["reused"] is True
        assert confirmation["unchanged"] is True
        assert confirmation["reused_ref"]
        # Reused ref указывает на ИСХОДНЫЙ снимок (последняя точка пути)
        assert confirmation["reused_ref"] == snapshot["ordered_refs"][-1]

    def test_reused_older_snapshot_is_alias_not_fourth_copy(self, client):
        """Reused-но-изменённый handoff (возврат к старому снимку):
        modeling_entry в пути, но запись -- АЛИАС исходного снимка
        (тот же snapshot_ref; физической четвёртой копии нет, AC11)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 5.0)
        validation_value = _first_target_value(client)
        _capture_new(client, "exit", -3.0)
        # Возврат ряда к состоянию validation-снимка
        _set_first_target_value(client, validation_value)
        capture = client.post("/v1/session/dataset/passport/modeling_entry")
        assert capture.status_code == 200, capture.text
        body = capture.json()
        assert body["reused_snapshot"] is True

        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, body["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        assert snapshot["path"] == ["start", "validation", "exit", "modeling_entry"]
        last_pair = snapshot["comparisons"][-1]
        assert (last_pair["from_stage"], last_pair["to_stage"]) == (
            "exit", "modeling_entry",
        )
        # modeling_entry -- алиас validation-записи: один snapshot_ref,
        # два адреса пути (без четвёртой физической копии)
        modeling_refs = [
            p["to_ref"] for p in snapshot["comparisons"]
            if p["to_stage"] == "modeling_entry"
        ]
        validation_refs = [
            p["to_ref"] for p in snapshot["comparisons"]
            if p["to_stage"] == "validation"
        ]
        assert modeling_refs and modeling_refs[0] == validation_refs[0]
        confirmation = snapshot["confirmation"]
        assert confirmation["reused"] is True
        assert confirmation["unchanged"] is False
        assert confirmation["reused_ref"] == modeling_refs[0]

    def test_checkpoint_metadata_in_snapshot(self, client):
        """§9: checkpoint metadata в frozen snapshot -- confirmed_at,
        флаги, provenance, context."""
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        checkpoint = snapshot["checkpoint"]
        assert checkpoint["checkpoint_ref"]
        assert checkpoint["confirmed_at"]
        assert checkpoint["flags"]["created"] is True
        assert checkpoint["flags"]["reused"] is False
        assert checkpoint["provenance"]
        assert snapshot["context"] is not None

    def test_missing_checkpoint_is_none_not_fabricated(self):
        """Неизвестный чекпоинт -- None (uniform, без фабкации)."""
        from apps.api import passport_comparison

        _seed_run()
        result = passport_comparison.resolve_passport_comparison(
            RUN_ID, _owner_subject(),
            checkpoint_id="pck-absent", session_id=SESSION_ID,
        )
        assert result is None

    def test_dangling_stage_ref_gap_partial_with_remaining_path(self):
        """§9: missing validation -- gap, не ноль; путь строится по
        доказанным точкам (семантика session-пропуска), gap явно
        перечислен, completeness=partial."""
        from apps.api import passport_comparison
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.visual_artifacts import register_passport_checkpoint

        _seed_run()
        subject = _owner_subject()
        payload = {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id("cp-p06-dangling"),
            "stage": "modeling_entry",
            "confirmed_at": "2026-06-01T10:00:00+00:00",
            "confirmed_at_reason": None,
            "snapshot_ref": "rs-" + "a" * 32,
            "previous_snapshot_ref": None,
            "flags": {"created": True, "reused": False, "unchanged": False},
            "stage_refs": {
                "start": "rs-" + "b" * 32,
                "validation": "rs-" + "c" * 32,
                "exit": "rs-" + "d" * 32,
            },
            "context": {
                "run_id": RUN_ID,
                "context_id": "ctx-p06-dangling",
                "data_revision": 3,
                "target_column": "value",
                "entity_id": None,
            },
            "provenance": {"source": "legacy_import"},
        }
        artifact = register_passport_checkpoint(
            RUN_ID, subject, payload=payload, session_id=SESSION_ID,
        )
        assert artifact is not None
        snapshot = passport_comparison.resolve_passport_comparison(
            RUN_ID, subject,
            checkpoint_id=artifact.refs["checkpoint_id"], session_id=SESSION_ID,
        )
        assert snapshot is not None
        assert snapshot["completeness"] == "partial"
        assert snapshot["comparisons"] == []
        gap_refs = {gap["snapshot_ref"] for gap in snapshot["gaps"]}
        assert "rs-" + "c" * 32 in gap_refs  # validation -- явный gap
        assert snapshot["path"] == []  # ни одна точка не доказана

    def test_trajectory_gap_detail_uniform_foreign_vs_absent(self):
        """PGV-06-FIX / F-P6C1 (AC18-дух): в trajectory-режиме гэп по
        ЧУЖОМУ существующему ref (stage_refs crafted чекпоинта)
        неразличим от гэпа по отсутствующему ref -- reason И detail;
        машина-читаемый reason uniform, адрес дыры (at/snapshot_ref)
        сохраняется. До фикса reader-детали различали «не принадлежит
        запуску» vs «отсутствует в реестре» -- дисклоужение существования
        чужой записи."""
        from apps.api import passport_comparison
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.visual_artifacts import register_passport_checkpoint

        with TestClient(app) as owner_client:
            _upload(owner_client)
            _select_series(owner_client)
            _capture_full_trajectory(owner_client)
            run_id = _run_id_of(owner_client)
            subject = _client_subject(owner_client)
            sid = _client_session_id(owner_client)

            with TestClient(app) as other_client:
                _upload(other_client)
                _select_series(other_client)
                _capture_full_trajectory(other_client)
                other_records = list_passport_snapshots(
                    _run_id_of(other_client),
                    _client_subject(other_client),
                    session_id=_client_session_id(other_client),
                )
                assert other_records
                foreign_ref = other_records[0]["snapshot_ref"]

            def crafted(tag: str, start_ref: str) -> dict:
                return {
                    "schema_version": "pgv.passport_checkpoint/1",
                    "checkpoint_id": durable_checkpoint_id(
                        f"cp-p06-uniform-{tag}"
                    ),
                    "stage": "modeling_entry",
                    "confirmed_at": "2026-11-02T09:00:00+00:00",
                    "confirmed_at_reason": None,
                    "snapshot_ref": "rs-" + "a" * 32,
                    "previous_snapshot_ref": None,
                    "flags": {
                        "created": True, "reused": False, "unchanged": False,
                    },
                    "stage_refs": {
                        "start": start_ref,
                        "validation": "rs-" + "2" * 32,
                        "exit": "rs-" + "3" * 32,
                    },
                    "context": {
                        "run_id": run_id,
                        "context_id": "ctx-p06-uniform",
                        "data_revision": 2,
                        "target_column": "value",
                        "entity_id": None,
                    },
                    "provenance": {"source": "legacy_import"},
                }

            art_f = register_passport_checkpoint(
                run_id, subject,
                payload=crafted("foreign", foreign_ref), session_id=sid,
            )
            art_a = register_passport_checkpoint(
                run_id, subject,
                payload=crafted("absent", "rs-" + "0" * 32), session_id=sid,
            )
            assert art_f is not None and art_a is not None
            snap_f = passport_comparison.resolve_passport_comparison(
                run_id, subject,
                checkpoint_id=art_f.refs["checkpoint_id"], session_id=sid,
            )
            snap_a = passport_comparison.resolve_passport_comparison(
                run_id, subject,
                checkpoint_id=art_a.refs["checkpoint_id"], session_id=sid,
            )
            gf = next(
                (g for g in snap_f["gaps"] if g["snapshot_ref"] == foreign_ref),
                None,
            )
            ga = next(
                (g for g in snap_a["gaps"]
                 if g["snapshot_ref"] == "rs-" + "0" * 32),
                None,
            )
            assert gf is not None and ga is not None, (
                "обе записи обязаны дать гэпы (иначе фабкация резолюции)"
            )
            assert gf["reason"] == ga["reason"] == "missing_snapshot_record"
            # Ключевой дифференциальный оракул F-P6C1: uniform detail.
            assert gf["detail"] == ga["detail"], (
                "деталь trajectory-гэпа различает чужой "
                f"({gf['detail']!r}) и отсутствующий ({ga['detail']!r}) "
                "ref -- дисклоужение существования чужой записи "
                "(AC18-дух)"
            )
            # Адрес дыры сохраняется (не огрубляется нормализацией).
            assert gf["at"] == ga["at"] == "stage_refs.start"

    def test_trajectory_gap_detail_uniform_on_confirmed_and_previous_refs(
        self, client,
    ):
        """PGV-06-FIX / F-P6C1: uniform-detail нормализация покрывает ВСЕ
        позиции reader-гэпов траектории -- подтверждённый ref
        (snapshot_ref) и previous_snapshot_ref, не только stage_refs;
        content-гэпы (corrupt-диагностика) при этом НЕ нормализуются
        (свои честные detail из content_gap_reason)."""
        import json

        from apps.api import passport_comparison
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import (
            list_passport_snapshots,
            read_passport_snapshot,
        )
        from apps.api.visual_artifacts import register_passport_checkpoint

        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        subject = _client_subject(client)
        sid = _client_session_id(client)
        records = list_passport_snapshots(run_id, subject, session_id=sid)
        assert len(records) >= 2
        # Порча passport-артефакта ПЕРВОЙ записи -- честный content-гэп.
        corrupt_ref = records[0]["snapshot_ref"]
        dep_artifact = get_artifact_registry().get_artifact(
            records[0]["artifact_id"]
        )
        assert dep_artifact is not None
        object_path = get_artifact_object_store().path_for_key(
            dep_artifact.storage_key
        )
        assert json.loads(object_path.read_bytes().decode("utf-8"))
        object_path.write_bytes(b'{"tampered": true}')
        corrupt_record = read_passport_snapshot(
            run_id, subject, snapshot_ref=corrupt_ref, session_id=sid,
        )
        assert corrupt_record is not None
        assert corrupt_record["content_status"] != "present"
        corrupt_reason = corrupt_record["content_gap_reason"]
        present_ref = records[-1]["snapshot_ref"]

        with TestClient(app) as other_client:
            _upload(other_client)
            _select_series(other_client)
            _capture_full_trajectory(other_client)
            other_records = list_passport_snapshots(
                _run_id_of(other_client),
                _client_subject(other_client),
                session_id=_client_session_id(other_client),
            )
            assert other_records
            foreign_ref = other_records[0]["snapshot_ref"]

        def crafted(tag: str, *, confirmed: str, previous: str) -> dict:
            return {
                "schema_version": "pgv.passport_checkpoint/1",
                "checkpoint_id": durable_checkpoint_id(
                    f"cp-p06-unif2-{tag}"
                ),
                "stage": "modeling_entry",
                "confirmed_at": "2026-11-02T09:30:00+00:00",
                "confirmed_at_reason": None,
                "snapshot_ref": confirmed,
                "previous_snapshot_ref": previous,
                "flags": {
                    "created": True, "reused": False, "unchanged": False,
                },
                "stage_refs": {
                    "start": corrupt_ref,
                    "validation": "rs-" + "4" * 32,
                    "exit": "rs-" + "5" * 32,
                },
                "context": {
                    "run_id": run_id,
                    "context_id": "ctx-p06-unif2",
                    "data_revision": 2,
                    "target_column": "value",
                    "entity_id": None,
                },
                "provenance": {"source": "legacy_import"},
            }

        def resolve(payload: dict) -> dict:
            artifact = register_passport_checkpoint(
                run_id, subject, payload=payload, session_id=sid,
            )
            assert artifact is not None
            snapshot = passport_comparison.resolve_passport_comparison(
                run_id, subject,
                checkpoint_id=artifact.refs["checkpoint_id"],
                session_id=sid,
            )
            assert snapshot is not None
            return snapshot

        # Ось подтверждённого ref: чужой vs отсутствующий.
        snap_cf = resolve(crafted(
            "conf-foreign", confirmed=foreign_ref, previous="rs-" + "6" * 32,
        ))
        snap_ca = resolve(crafted(
            "conf-absent", confirmed="rs-" + "e" * 32,
            previous="rs-" + "6" * 32,
        ))
        g_cf = next(
            (g for g in snap_cf["gaps"] if g["at"] == "snapshot_ref"), None,
        )
        g_ca = next(
            (g for g in snap_ca["gaps"] if g["at"] == "snapshot_ref"), None,
        )
        assert g_cf is not None and g_ca is not None
        assert g_cf["reason"] == g_ca["reason"] == "missing_snapshot_record"
        assert g_cf["detail"] == g_ca["detail"], (
            "деталь гэпа подтверждённого ref различает чужой "
            f"({g_cf['detail']!r}) и отсутствующий ({g_ca['detail']!r}) -- "
            "дисклоужение (AC18-дух)"
        )
        # Ось previous_snapshot_ref: чужой vs отсутствующий.
        snap_pf = resolve(crafted(
            "prev-foreign", confirmed=present_ref, previous=foreign_ref,
        ))
        snap_pa = resolve(crafted(
            "prev-absent", confirmed=present_ref,
            previous="rs-" + "7" * 32,
        ))
        g_pf = next(
            (g for g in snap_pf["gaps"]
             if g["at"] == "previous_snapshot_ref"), None,
        )
        g_pa = next(
            (g for g in snap_pa["gaps"]
             if g["at"] == "previous_snapshot_ref"), None,
        )
        assert g_pf is not None and g_pa is not None
        assert g_pf["reason"] == g_pa["reason"] == "missing_snapshot_record"
        assert g_pf["detail"] == g_pa["detail"], (
            "деталь гэпа previous_snapshot_ref различает чужой "
            f"({g_pf['detail']!r}) и отсутствующий ({g_pa['detail']!r}) -- "
            "дисклоужение (AC18-дух)"
        )
        # Content-гэп порченой записи НЕ нормализуется: своя честная
        # диагностика (AC12), reason отличен от missing_snapshot_record.
        g_content = next(
            (g for g in snap_pf["gaps"] if g["snapshot_ref"] == corrupt_ref),
            None,
        )
        assert g_content is not None
        assert g_content["reason"] == "content_corrupt"
        assert g_content["detail"] == corrupt_reason


# ══════════════════════════════════════════════════════════════════════
# 3. Совместимость контекстов (AC13/AC14): incompatible/cross-context
# ══════════════════════════════════════════════════════════════════════


def _record(**overrides) -> dict:
    """Snapshot-запись §8 (форма PGV-05) для чистых unit-оракулов."""
    base = {
        "schema_version": "pgv.passport_history/1",
        "snapshot_ref": "rs-test-a",
        "session_snapshot_id": "snap-a",
        "artifact_id": "art-a",
        "stage": "start",
        "universe": "single",
        "passport": {
            "basic_stats": {"n": 10, "mean": 1.0, "std": 0.5},
            "stationarity": {"value": 0.01, "is_stationary": True},
        },
        "content_status": "present",
        "content_gap_reason": None,
        "target_column": "value",
        "date_column": "date",
        "context_id": None,
        "data_revision": None,
        "data_ref": None,
        "captured_at": "2026-10-29T10:00:00+00:00",
        "created_at": None,
        "source_hash_algorithm": "sha256(canonical_json)",
        "fingerprint": "fp-a",
        "fingerprint_reason": None,
        "source_hash": "hash-a",
        "source_hash_reason": None,
        "passport_schema_version": None,
        "passport_schema_version_reason": "legacy_unknown",
        "calculation_version": None,
        "calculation_version_reason": "legacy_unknown",
    }
    base.update(overrides)
    return base


class TestIncompatibleContexts:
    def test_target_mismatch_raises_incompatible(self):
        """§9: несовместимые target -> comparison_incompatible."""
        from apps.api import passport_comparison

        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(
                _record(snapshot_ref="rs-1", target_column="value"),
                _record(snapshot_ref="rs-2", target_column="other"),
            )
        assert any("target" in reason for reason in exc.value.reasons)

    def test_universe_mixing_panel_single_raises(self):
        """AC14: panel и single-series не смешиваются -- отказ с
        причиной universe."""
        from apps.api import passport_comparison

        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(
                _record(snapshot_ref="rs-1", stage="exit", universe="single"),
                _record(
                    snapshot_ref="rs-2",
                    stage="panel_entry",
                    universe="panel",
                ),
            )
        assert any("universe" in reason for reason in exc.value.reasons)

    def test_entity_mismatch_raises_when_provable(self):
        """AC14: разные entities панельного контура не смешиваются --
        проверка только ДОКАЗУЕМЫХ entity (XOR-честность: неизвестное
        entity -- не значение, отказ не фабкуется)."""
        from apps.api import passport_comparison

        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(
                _record(
                    snapshot_ref="rs-1", stage="panel_entry",
                    universe="panel", entity_id="region",
                ),
                _record(
                    snapshot_ref="rs-2",
                    stage="panel_entry",
                    universe="panel",
                    entity_id="store",
                ),
            )
        assert any("entity" in reason for reason in exc.value.reasons)
        # Неизвестные entity с обеих сторон -- не отказ (не фабкация)
        pair = passport_comparison.compare_passport_records(
            _record(snapshot_ref="rs-1", universe="panel"),
            _record(snapshot_ref="rs-2", stage="panel_entry", universe="panel"),
        )
        assert pair["comparison"]

    def test_schema_version_mismatch_raises_when_known(self):
        """§9: несовместимая schema паспорта -> comparison_incompatible;
        legacy_unknown (неизвестно) -- НЕ отказ (честность, не догадка)."""
        from apps.api import passport_comparison

        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(
                _record(
                    snapshot_ref="rs-1",
                    passport_schema_version="pgv.passport_schema/1",
                    passport_schema_version_reason=None,
                ),
                _record(
                    snapshot_ref="rs-2",
                    passport_schema_version="pgv.passport_schema/2",
                    passport_schema_version_reason=None,
                ),
            )
        assert any("schema" in reason for reason in exc.value.reasons)
        # legacy_unknown с обеих сторон -- совместимость недоказуема,
        # отказ НЕ фабкуется
        pair = passport_comparison.compare_passport_records(
            _record(snapshot_ref="rs-1"),
            _record(snapshot_ref="rs-2"),
        )
        assert pair["comparison"]

    def test_cross_context_requires_explicit_mode(self):
        """§9: cross-context историческое сравнение -- ТОЛЬКО явный
        режим; без флага -- отказ; с флагом -- сравнение с маркировкой
        cross_context=True."""
        from apps.api import passport_comparison

        old = _record(snapshot_ref="rs-1", context_id="ctx-1")
        new = _record(
            snapshot_ref="rs-2", stage="validation", context_id="ctx-2"
        )
        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(old, new)
        assert any("context" in reason for reason in exc.value.reasons)

        explicit = passport_comparison.compare_passport_records(
            old, new, allow_cross_context=True
        )
        assert explicit["cross_context"] is True
        assert explicit["comparison"]

    def test_same_context_not_marked_cross(self):
        from apps.api import passport_comparison

        pair = passport_comparison.compare_passport_records(
            _record(snapshot_ref="rs-1", context_id="ctx-1"),
            _record(snapshot_ref="rs-2", stage="validation", context_id="ctx-1"),
        )
        assert pair["cross_context"] is False
        # Неизвестные контексты (None) -- не mismatch (XOR-честность)
        pair_unknown = passport_comparison.compare_passport_records(
            _record(snapshot_ref="rs-1"),
            _record(snapshot_ref="rs-2", stage="validation"),
        )
        assert pair_unknown["cross_context"] is False

    def test_incompatible_error_carries_reasons_and_message(self):
        """Отказ структурирован: reasons машиночитаемы, сообщение
        человекочитаемо (дух 409 comparison_incompatible §11)."""
        from apps.api import passport_comparison

        with pytest.raises(
            passport_comparison.PassportComparisonIncompatible
        ) as exc:
            passport_comparison.compare_passport_records(
                _record(snapshot_ref="rs-1", target_column="a"),
                _record(
                    snapshot_ref="rs-2", target_column="b", stage="validation"
                ),
            )
        assert exc.value.reasons
        assert str(exc.value)


# ══════════════════════════════════════════════════════════════════════
# 4. Явные refs (произвольный выбор UI): порядок, gaps, IDs
# ══════════════════════════════════════════════════════════════════════


class TestExplicitRefsMode:
    def test_refs_preserve_given_order_and_expose_ids(self, client):
        """Произвольный выбор (§9): ordered refs КАК ЗАДАНО (в т.ч.
        обратный порядок), пары в этом порядке, IDs доступны UI."""
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        from apps.api import passport_comparison
        from apps.api.passport_history import list_passport_snapshots

        run_id = _run_id_of(client)
        records = list_passport_snapshots(
            run_id, _client_subject(client), session_id=_client_session_id(client)
        )
        refs = [r["snapshot_ref"] for r in records]
        assert len(refs) >= 3
        reversed_refs = list(reversed(refs))
        snapshot = passport_comparison.resolve_passport_comparison(
            run_id, _client_subject(client),
            snapshot_refs=reversed_refs, session_id=_client_session_id(client),
        )
        assert snapshot["mode"] == "explicit_refs"
        assert snapshot["ordered_refs"] == reversed_refs
        assert len(snapshot["comparisons"]) == len(refs) - 1
        pair_refs = [
            (p["from_ref"], p["to_ref"]) for p in snapshot["comparisons"]
        ]
        assert pair_refs[0] == (reversed_refs[0], reversed_refs[1])
        assert snapshot["path"][0] == records[-1]["stage"]

    def test_missing_ref_is_gap_partial_not_zero(self, client):
        """Отсутствующий ref -- честный gap, completeness=partial,
        сравнения не фабкуются (не нули)."""
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            snapshot_refs=["rs-absent"], session_id=_client_session_id(client),
        )
        assert snapshot["completeness"] == "partial"
        assert snapshot["gaps"]
        assert snapshot["gaps"][0]["snapshot_ref"] == "rs-absent"
        assert snapshot["comparisons"] == []

    def test_dangling_middle_ref_splits_no_silent_bridge(self, client):
        """Дыра В СЕРЕДИНЕ refs (явный выбор): сравнения строятся только
        по соседним РАЗРЕШЁННЫМ позициям; молчаливый «мост» через дыру
        запрещён (§9: partial явно перечисляет пропуски)."""
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        from apps.api import passport_comparison
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            _run_id_of(client), _client_subject(client),
            session_id=_client_session_id(client),
        )
        refs = [r["snapshot_ref"] for r in records]
        assert len(refs) >= 3
        broken = [refs[0], "rs-absent-middle", refs[-1]]
        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            snapshot_refs=broken, session_id=_client_session_id(client),
        )
        assert snapshot["completeness"] == "partial"
        assert snapshot["comparisons"] == []
        assert any(
            gap["snapshot_ref"] == "rs-absent-middle" for gap in snapshot["gaps"]
        )

    def test_duplicate_refs_deduplicated_with_marked_alias(self, client):
        """Повторный ref (алиас под другим адресом пути, AC11-дух):
        физическая запись одна; повтор НЕ создаёт нулевую дублирующую
        пару -- адрес отмечен в aliases, сравнения -- соседних
        РАЗЛИЧНЫХ записей."""
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        from apps.api import passport_comparison
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            _run_id_of(client), _client_subject(client),
            session_id=_client_session_id(client),
        )
        refs = [r["snapshot_ref"] for r in records]
        assert len(refs) >= 2
        with_alias = refs + [refs[-1]]
        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            snapshot_refs=with_alias, session_id=_client_session_id(client),
        )
        pair_refs = [
            (p["from_ref"], p["to_ref"]) for p in snapshot["comparisons"]
        ]
        assert (refs[-1], refs[-1]) not in pair_refs
        assert snapshot["ordered_refs"][-1] == refs[-1]
        assert snapshot["aliases"]
        assert snapshot["aliases"][-1]["snapshot_ref"] == refs[-1]
        assert snapshot["aliases"][-1]["path_position"] == len(with_alias) - 1


# ══════════════════════════════════════════════════════════════════════
# 5. Полнота, контент-gaps и определения метрик (AC13)
# ══════════════════════════════════════════════════════════════════════


class TestCompletenessAndDefinitions:
    def test_complete_trajectory_has_no_gaps(self, client):
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        assert snapshot["completeness"] == "complete"
        assert snapshot["gaps"] == []

    def test_corrupt_content_is_gap_not_zero_not_incompatible(self, client):
        """Corrupt-контент записи -- content-gap (честный недобор), не
        нулевые дельты и не incompatible (§9: missing/corrupt -- gap)."""
        import json

        from apps.api import passport_comparison
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        records = list_passport_snapshots(
            run_id, _client_subject(client), session_id=_client_session_id(client)
        )
        refs = [r["snapshot_ref"] for r in records]
        # Порча байтов passport-артефакта ПЕРВОЙ записи
        first_record = records[0]
        assert first_record["artifact_id"]
        dep_artifact = get_artifact_registry().get_artifact(
            first_record["artifact_id"]
        )
        assert dep_artifact is not None
        object_path = get_artifact_object_store().path_for_key(
            dep_artifact.storage_key
        )
        original = object_path.read_bytes()
        assert json.loads(original.decode("utf-8"))  # целы до порчи
        object_path.write_bytes(b'{"tampered": true}')
        _ = get_snapshot_registry  # реестр не менялся (read-only резолюция)

        snapshot = passport_comparison.resolve_passport_comparison(
            run_id, _client_subject(client),
            snapshot_refs=refs, session_id=_client_session_id(client),
        )
        assert snapshot["completeness"] == "partial"
        # Пары, НЕ затронутые дырой, честно строятся (соседние
        # present-позиции); затронутые -- нет.
        touched_refs = {
            (p["from_ref"], p["to_ref"]) for p in snapshot["comparisons"]
        }
        assert len(snapshot["comparisons"]) == 2
        assert all(refs[0] not in pair for pair in touched_refs)
        corrupt_gaps = [
            gap for gap in snapshot["gaps"] if gap["snapshot_ref"] == refs[0]
        ]
        assert corrupt_gaps
        assert corrupt_gaps[0]["reason"] in {"content_missing", "content_corrupt"}

    def test_metric_definitions_and_zero_denominator_reason(self, client):
        """AC13/§9: absolute/relative changes с определением и
        zero-denominator reason; цвет delta -- не значимость.
        Определения соответствуют ФАКТИЧЕСКОМУ поведению движка
        (parity-оракул), не переписывают формулы."""
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        definitions = snapshot["definitions"]
        assert "absolute" in definitions and "relative" in definitions
        assert definitions["zero_denominator_reason"]
        assert "значимост" in definitions["delta_color"]
        # Zero-denominator оракул: |v_old| <= 1e-10 -> относительное
        # изменение не определено; конвенция движка (0.0/100.0)
        # задокументирована определением, а не переписана.
        props_old = {"basic_stats": {"n": 10, "mean": 0.0, "std": 0.0}}
        props_new = {"basic_stats": {"n": 12, "mean": 5.0, "std": 1.0}}
        engine = _compare_ts_props(props_old, props_new)
        metric = engine["metrics"]["Среднее"]
        assert metric["v_old"] == 0.0
        assert metric["delta_pct"] == 100.0
        adapter_out = passport_comparison.compare_passports_via_engine(
            props_old, props_new
        )
        assert adapter_out == engine

    def test_method_and_schema_versions_recorded(self, client):
        """§9: method/schema versions в frozen snapshot -- из записей
        AS-IS; legacy_unknown остаётся честным (не выдуманный 'v1')."""
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from apps.api import passport_comparison

        snapshot = passport_comparison.resolve_passport_comparison(
            _run_id_of(client), _client_subject(client),
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            session_id=_client_session_id(client),
        )
        versions = snapshot["method_versions"]
        assert versions["engine"] == passport_comparison.COMPARISON_ENGINE
        per_record = versions["records"]
        assert len(per_record) == len(snapshot["ordered_refs"])
        for item in per_record:
            assert set(item) >= {
                "snapshot_ref",
                "passport_schema_version",
                "calculation_version",
            }

    def test_ac13_change_kinds_present_on_real_data(self, client):
        """AC13: numeric/category/list/qualitative изменения присутствуют
        в попарном выводе на реальных захваченных паспортах (не пустые
        заглушки); блоки движка переносятся AS-IS."""
        _upload(client)
        _select_series(client)
        # rs-записи создаются при подтверждении чекпоинта (PGV-04):
        # полный пайплайн даёт доказуемые durable-снимки.
        _capture_full_trajectory(client)
        from apps.api import passport_comparison
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            _run_id_of(client), _client_subject(client),
            session_id=_client_session_id(client),
        )
        pair = passport_comparison.compare_passport_records(records[0], records[1])
        comparison = pair["comparison"]
        assert "metrics" in comparison and comparison["metrics"]
        assert "categorical_changes" in comparison
        assert "list_changes" in comparison
        assert "qualitative_changes" in comparison
        assert "boolean_changes" in comparison


# ══════════════════════════════════════════════════════════════════════
# 6. Панельная вселенная, доступ и отсутствие побочных эффектов
# ══════════════════════════════════════════════════════════════════════


class TestPanelAccessAndPurity:
    @pytest.fixture()
    def panel_client(self, client):
        client.get("/v1/session/modeling/state")
        assert client.cookies.get(SESSION_COOKIE_NAME)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get_or_create(session_id)
        session.set_dataframe(_panel_dataframe(), reason="pgv06-panel")
        session.target_column = "y"
        session.date_column = "date"
        from apps.api.session_store import DatasetInfo

        session.dataset = DatasetInfo(
            dataset_id="p06-panel-ds",
            name="pgv06-panel-seed",
            rows=120,
            columns=3,
            size_label="3 KB",
            dataset_fingerprint="p6p" * 8,
        )
        run_id = session.ensure_run_id()
        owner, tenant = session.ensure_owner_binding()
        store.save(session)
        _seed_run(run_id, session_id, owner_subject=owner, tenant_id=tenant)
        return client

    def test_panel_trajectory_resolves_in_panel_universe(self, panel_client):
        """AC14: панельная траектория резолвится в своей вселенной;
        панельные записи не смешиваются с single-series (universe-гейт
        на каждой паре)."""
        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        body = confirm.json()

        from apps.api import passport_comparison

        session = get_session_store().get(
            panel_client.cookies.get(SESSION_COOKIE_NAME)
        )
        snapshot = passport_comparison.resolve_passport_comparison(
            session.run_id, _owner_subject(session.session_id),
            checkpoint_id=_durable_checkpoint_id(
                session.run_id, body["checkpoint_id"]
            ),
            session_id=session.session_id,
        )
        assert snapshot is not None
        assert snapshot["mode"] == "trajectory_checkpoint"
        # Панельная траектория: единственная точка -- panel; пар нет
        # (сравнивать не с чем -- честно, не нули).
        assert snapshot["path"] == ["panel"]
        assert snapshot["comparisons"] == []
        assert snapshot["completeness"] == "complete"
        assert snapshot["context"]["entity_id"] == "entity"
        for pair in snapshot["comparisons"]:
            assert pair["from_stage"] != "panel_entry" or pair["to_stage"] != "exit"

    def test_foreign_subject_uniform_denial(self, client):
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        from apps.api import passport_comparison
        from apps.api.passport_history import PassportHistoryAccessDenied

        with pytest.raises(PassportHistoryAccessDenied):
            passport_comparison.resolve_passport_comparison(
                _run_id_of(client), _foreign_subject(),
                checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]),
            )

    def test_resolution_is_read_only_and_deterministic(self, client):
        """Резолюция -- pure read: реестры не растут от сравнения;
        те же refs -- тот же snapshot (AC06-дух)."""
        from apps.api import passport_comparison
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        subject = _client_subject(client)
        session_id = _client_session_id(client)
        snap_before = len(get_snapshot_registry().list_records(run_id))
        art_before = len(get_artifact_registry().list_artifacts(run_id))
        first = passport_comparison.resolve_passport_comparison(
            run_id, subject,
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]), session_id=session_id,
        )
        second = passport_comparison.resolve_passport_comparison(
            run_id, subject,
            checkpoint_id=_durable_checkpoint_id(client, capture["checkpoint_id"]), session_id=session_id,
        )
        assert first == second
        assert len(get_snapshot_registry().list_records(run_id)) == snap_before
        assert len(get_artifact_registry().list_artifacts(run_id)) == art_before

    def test_session_endpoint_response_uses_shared_engine(self, client):
        """Сессийный orchestration и durable resolver используют ОДИН
        versioned adapter: попарный вывод эндпоинта == вывод адаптера
        на тех же паспортах (прежняя семантика ответа сохранена)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 5.0)
        resp = client.get(
            "/v1/session/dataset/passport/compare", params={"to": "validation"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["comparisons"]) == 1
        endpoint_comparison = body["comparisons"][0]["comparison"]

        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison

        session = get_session_store().get(_client_session_id(client))
        old_stage = body["comparisons"][0]["from_stage"]
        new_stage = body["comparisons"][0]["to_stage"]
        old_snap = next(
            item for item in session.passport_history if item.stage == old_stage
        )
        new_snap = next(
            item for item in session.passport_history if item.stage == new_stage
        )
        assert endpoint_comparison == _compare_ts_props(
            old_snap.passport, new_snap.passport
        )
        assert endpoint_comparison == (
            passport_comparison.compare_passports_via_engine(
                old_snap.passport, new_snap.passport
            )
        )
