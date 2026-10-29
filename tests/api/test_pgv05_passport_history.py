"""TDD-корпус PGV-05 (spec_passport_graphics_visual.md §8/§10/§13,
строка PGV-05): PassportHistoryReader -- чтение durable-истории
паспортов из registry/ObjectStore, НЕ из SessionStore.

ПОСТАНОВКА (§13): «PassportHistoryReader; точки изменения --
passport_documents/ObjectStore/refs; критерий -- Чтение без
Redis/DataFrame, schema gaps/legacy_unknown честны».

Ключевые инварианты поставки:
  AC09 -- полные группы паспорта читаются после утраты session/Redis
          из durable refs (rs-записи + passport-артефакты);
  AC10 -- траектория читается «на выбранное подтверждение EDA»
          (замороженные stage_refs), не latest каждого stage; старые
          snapshots не переписываются;
  AC11 -- reused handoff резолвится в ИСХОДНЫЙ снимок без ложной
          четвёртой физической копии;
  AC12 -- недостающие/битые записи дают честные gaps/integrity
          failure (content_status=corrupt, причины legacy_unknown),
          НЕ выдуманные даты/контент;
  AC14 -- panel_entry изолирован от single-series (universe по stage);
  §8    -- snapshot несёт полные groups/metrics, schema/calculation
          version, target/date/entity, snapshot_id, fingerprint/
          context/data_revision, captured/created time, data_ref;
          source_hash и fingerprint -- разные поля с определёнными
          алгоритмами (sha256(canonical_json payload) артефакта vs
          series_fingerprint данных).
"""
from __future__ import annotations

import ast
import io
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

RUN_ID = "RUN-P05A0001"
SESSION_ID = "p05-seed-session"

PASSPORT_METRIC_GROUPS = (
    "freq",
    "stationarity",
    "determinism",
    "autocorrelation",
    "normality",
    "trend",
    "correlations",
    "seasonality",
    "seasonal_periods",
    "hurst",
    "fft",
    "periodogram",
    "wavelet",
    "basic_stats",
)


# ── Изоляция среды (паттерн PGV-02/03/04) ────────────────────────────


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


# ── Сид-хелперы (свои данные; паттерн PGV-04) ────────────────────────


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"date": dates, "value": values})
    return frame.to_csv(index=False)


def _upload(client: TestClient) -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200


def _capture(client: TestClient, stage: str) -> dict:
    response = client.post(f"/v1/session/dataset/passport/{stage}")
    assert response.status_code == 200, response.text
    return response.json()


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


def _capture_new(client: TestClient, stage: str, delta: float) -> dict:
    """Мутация ряда + capture: baseline-гейт пайплайна запрещает
    фиксацию ИДЕНТИЧНЫХ снимков (последовательность PGV-04:
    start -> мутация -> validation -> мутация -> exit -> мутация ->
    modeling_entry)."""
    _mutate_target(client, delta)
    return _capture(client, stage)


def _first_target_value(client: TestClient) -> float:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None and session.dataframe is not None
    return float(session.dataframe.loc[session.dataframe.index[0], "value"])


def _set_first_target_value(client: TestClient, value: float) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] = value
    session.touch()
    store.save(session)


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    owner_subject: str | None = None,
    tenant_id: str | None = None,
):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p05" * 8,
        dataset_name="pgv05-history-seed",
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
    приложением с владельцем = субъект ЭТОЙ сессии (ensure_owner_binding)."""
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(_client_session_id(client))


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p05-foreign-session")


def _durable_checkpoint(run_id: str, session_checkpoint_id: str):
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")


def _checkpoint_payload(artifact) -> dict:
    import json

    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))


def _panel_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for entity in ("region-a", "region-b", "region-c"):
        for t in range(40):
            rows.append({
                "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=t)).date().isoformat(),
                "entity": entity,
                "y": 10 + t * 0.1 + rng.normal(0, 0.2),
            })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# 1. Границы модуля: чтение без SessionStore/Redis/DataFrame (AC09, §8)
# ══════════════════════════════════════════════════════════════════════


class TestModuleBoundaries:
    def test_module_imports_exclude_session_store_pandas_redis(self):
        """AST-граница: модуль reader'а не импортирует SessionStore,
        pandas или redis -- чтение ТОЛЬКО registry/ObjectStore (§8)."""
        source = Path("apps/api/passport_history.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
        forbidden = {
            name
            for name in imported
            if "session_store" in name
            or name.startswith("pandas")
            or name.startswith("redis")
        }
        assert not forbidden, f"запрещённые импорты в reader'е: {sorted(forbidden)}"

    def test_full_read_after_session_loss(self, client):
        """AC09: полные группы паспорта читаются после утраты
        session/Redis из durable refs (rs-записи + ObjectStore)."""
        from apps.api.passport_history import read_passport_trajectory

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        capture = _capture_new(client, "modeling_entry", 5.0)

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, capture["checkpoint_id"])
        assert artifact is not None

        # Сессия утрачена (TTL/рестарт)...
        reset_session_store_for_testing()
        # ...траектория читается из durable-записей с ПОЛНЫМ содержимым.
        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        assert trajectory["checkpoint_ref"] == artifact.refs["checkpoint_id"]
        for stage in ("start", "validation", "exit"):
            record = trajectory["snapshots"][stage]
            assert record["content_status"] == "present"
            passport = record["passport"]
            assert isinstance(passport, dict) and passport
            for group in PASSPORT_METRIC_GROUPS:
                assert group in passport, f"группа {group} потеряна (AC09)"
        confirmed = trajectory["snapshots"].get("modeling_entry")
        assert confirmed is not None
        assert confirmed["content_status"] == "present"
        assert confirmed["passport"].get("basic_stats", {}).get("n") == 84


# ══════════════════════════════════════════════════════════════════════
# 2. Траектория по выбранному подтверждению (AC10/AC11, §8/§10)
# ══════════════════════════════════════════════════════════════════════


class TestTrajectoryRead:
    def test_full_pipeline_trajectory_fields(self, client):
        """Траектория modeling_entry: stage-снимки + подтверждённый
        snapshot; confirmed_at/flags/provenance/context из чекпоинта."""
        from apps.api.passport_history import read_passport_trajectory

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        capture = _capture_new(client, "modeling_entry", 5.0)

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, capture["checkpoint_id"])
        payload = _checkpoint_payload(artifact)

        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        assert trajectory["schema_version"] == "pgv.passport_history/1"
        assert trajectory["stage"] == "modeling_entry"
        assert trajectory["universe"] == "single"
        assert trajectory["confirmed_at"] == payload["confirmed_at"]
        assert trajectory["flags"] == payload["flags"]
        assert trajectory["provenance"]["source"] == "producer_capture"
        assert trajectory["context"]["run_id"] == run_id
        assert trajectory["context"]["target_column"] == "value"
        assert trajectory["checkpoint_artifact_id"] == artifact.artifact_id
        # Траектория «на момент подтверждения»: три stage-снимка.
        for stage in ("start", "validation", "exit"):
            assert trajectory["snapshots"][stage]["snapshot_ref"] == payload["stage_refs"][stage]
        # gaps нет: все ссылки разрешены.
        assert trajectory["gaps"] == []
        # Порядок совпадает с замороженным чекпоинтом, не с «latest».
        assert set(trajectory["snapshots"]) == {"start", "validation", "exit", "modeling_entry"}

    def test_selected_trajectory_not_latest_of_each_stage(self, client):
        """AC10: траектория ПЕРВОГО подтверждения продолжает ссылаться
        на замороженные снимки после появления более поздних; старые
        snapshots не переписываются (§8)."""
        from apps.api.passport_history import read_passport_trajectory

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        first = _capture_new(client, "modeling_entry", 5.0)
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        first_ref = _durable_checkpoint(run_id, first["checkpoint_id"]).refs["checkpoint_id"]

        # Новая точка данных -> новый exit -> второе подтверждение
        # (reuse: fingerprint совпадает с exit#2).
        _capture_new(client, "exit", 2.0)
        second = _capture(client, "modeling_entry")
        second_ref = _durable_checkpoint(run_id, second["checkpoint_id"]).refs["checkpoint_id"]
        assert second_ref != first_ref

        trajectory_first = read_passport_trajectory(
            run_id, _client_subject(client), checkpoint_id=first_ref,
            session_id=_client_session_id(client),
        )
        trajectory_second = read_passport_trajectory(
            run_id, _client_subject(client), checkpoint_id=second_ref,
            session_id=_client_session_id(client),
        )
        # Первая траектория НЕ переключилась на поздний exit (AC10).
        assert (
            trajectory_first["snapshots"]["exit"]["snapshot_ref"]
            != trajectory_second["snapshots"]["exit"]["snapshot_ref"]
        )
        assert trajectory_first["snapshots"]["modeling_entry"]["fingerprint"] == first["fingerprint"]
        assert (
            trajectory_second["snapshots"]["modeling_entry"]["fingerprint"]
            == second["fingerprint"]
        )

    def test_reused_handoff_resolves_source_snapshot(self, client):
        """AC11: reused handoff -- reader резолвит ИСХОДНЫЙ снимок
        (reused-поиск), новая физическая копия не создавалась; чтение
        НЕ добавляет артефактов/записей/пинов (reader только читает)."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_history import read_passport_trajectory
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        original = _first_target_value(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        # Ряд возвращается РОВНО к состоянию start (точная установка
        # исходного значения -- reuse-поиск найдёт совпадающий fingerprint).
        _set_first_target_value(client, original)
        _capture(client, "exit")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, capture["checkpoint_id"])
        payload = _checkpoint_payload(artifact)

        artifacts_before = len(get_artifact_registry().list_artifacts(run_id))
        records_before = len(get_snapshot_registry().list_records(run_id))

        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        # snapshot_ref -- ИСХОДНЫЙ снимок (stage exit, reuse-поиск).
        confirmed = trajectory["snapshots"]["exit"]
        assert confirmed["snapshot_ref"] == payload["snapshot_ref"]
        assert confirmed["content_status"] == "present"
        assert trajectory["flags"]["reused"] is True
        # Ровно три физических паспорта -- чтение ничего не добавило.
        passports = get_artifact_registry().list_artifacts(run_id, kind="passport")
        assert len(passports) == 3
        assert len(get_artifact_registry().list_artifacts(run_id)) == artifacts_before
        assert len(get_snapshot_registry().list_records(run_id)) == records_before

    def test_missing_checkpoint_ref_returns_none(self, client):
        """Несуществующий checkpoint_id -- None без фабкации (честное
        отсутствие факта)."""
        from apps.api.passport_history import read_passport_trajectory

        _seed_run()
        result = read_passport_trajectory(
            RUN_ID, _owner_subject(), checkpoint_id="pck-absent", session_id=SESSION_ID,
        )
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# 3. Snapshot-запись §8: полные поля, два разных хэша, версии
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotRecord:
    def test_snapshot_record_contract_fields(self, client):
        """§8: snapshot несёт target/date, snapshot_id, fingerprint/
        context/data_revision, captured/created time, data_ref,
        source_hash; source_hash != fingerprint (разные алгоритмы);
        stamped-контекст -- только у доказуемо созданного снимка."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_history import (
            PASSPORT_HISTORY_SCHEMA_VERSION,
            read_passport_snapshot,
        )
        from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        start = _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)  # created: rs-записи всех снимков
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        registry = get_snapshot_registry()

        record = registry.find_idempotent(
            run_id, f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{start['snapshot_id']}"
        )
        assert record is not None, "rs-запись start отсутствует после заморозки"

        snapshot = read_passport_snapshot(
            run_id, _client_subject(client), snapshot_ref=record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert snapshot["schema_version"] == PASSPORT_HISTORY_SCHEMA_VERSION
        assert snapshot["snapshot_ref"] == record.snapshot_id
        assert snapshot["session_snapshot_id"] == start["snapshot_id"]
        assert snapshot["stage"] == "start"
        assert snapshot["universe"] == "single"
        assert snapshot["target_column"] == "value"
        assert snapshot["date_column"] == "date"
        assert snapshot["fingerprint"] == start["fingerprint"]
        assert snapshot["captured_at"] == start["captured_at"]
        assert snapshot["created_at"]  # время промоушена артефакта
        # data_ref честен: у паспортных rs-записей его нет.
        assert snapshot["data_ref"] is None
        # source_hash -- sha256 канонического payload'а артефакта.
        artifact = get_artifact_registry().get_artifact(snapshot["artifact_id"])
        assert artifact is not None and artifact.kind == "passport"
        assert snapshot["source_hash"] == artifact.payload_sha256
        assert snapshot["source_hash_algorithm"]
        # fingerprint (series_fingerprint данных) и source_hash
        # (sha256 контента) -- РАЗНЫЕ значения/алгоритмы (§8).
        assert snapshot["fingerprint"] != snapshot["source_hash"]

        # Created-снимок (данные изменились ПОСЛЕ modeling_entry#1):
        # rs-запись несёт доказуемый контекст подтверждения.
        _mutate_target(client, 6.0)
        created = _capture(client, "modeling_entry")
        assert created["reused_snapshot"] is False
        created_record = registry.find_idempotent(
            run_id, f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{created['snapshot_id']}"
        )
        assert created_record is not None
        assert created_record.context_id, "контекст created-снимка штампуется"
        created_snapshot = read_passport_snapshot(
            run_id, _client_subject(client),
            snapshot_ref=created_record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert created_snapshot["stage"] == "modeling_entry"
        assert created_snapshot["context_id"] == created_record.context_id
        assert created_snapshot["data_revision"] == created_record.data_revision
        assert created_snapshot["fingerprint"] == created["fingerprint"]

    def test_schema_and_calculation_versions_legacy_unknown(self, client):
        """§8/AC12: payload паспорта не самоназван -- schema/calculation
        version честно legacy_unknown, НЕ выдуманный 'v1'."""
        from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
        from apps.api.report_snapshot import get_snapshot_registry
        from apps.api.passport_history import read_passport_snapshot

        _upload(client)
        _select_series(client)
        start = _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)  # заморозка создаёт rs-записи
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        record = get_snapshot_registry().find_idempotent(
            session.run_id,
            f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{start['snapshot_id']}",
        )
        snapshot = read_passport_snapshot(
            session.run_id, _client_subject(client),
            snapshot_ref=record.snapshot_id, session_id=_client_session_id(client),
        )
        assert snapshot["passport_schema_version"] is None
        assert snapshot["passport_schema_version_reason"] == "legacy_unknown"
        assert snapshot["calculation_version"] is None
        assert snapshot["calculation_version_reason"] == "legacy_unknown"

    def test_missing_snapshot_ref_returns_none(self):
        """Чужой/несуществующий rs-ref -- None (uniform, без
        дисклоужения существования)."""
        from apps.api.passport_history import read_passport_snapshot

        _seed_run()
        result = read_passport_snapshot(
            RUN_ID, _owner_subject(), snapshot_ref="rs-" + "0" * 32, session_id=SESSION_ID,
        )
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# 4. Честные gaps/integrity failure (AC12: не догадка)
# ══════════════════════════════════════════════════════════════════════


class TestHonestGaps:
    def test_rs_record_without_artifact_is_honest_gap(self):
        """rs-запись без паспортного артефакта (legacy до C03):
        content_status=missing_artifact, passport=None, fingerprint/
        source_hash -- причины legacy_unknown; captured_at честен из
        rs-записи (не выдуман, не время чтения)."""
        from types import SimpleNamespace

        from apps.api.passport_checkpoints import ensure_passport_snapshot_record
        from apps.api.passport_history import read_passport_snapshot

        _seed_run()
        subject = _owner_subject()
        legacy_snapshot = SimpleNamespace(
            snapshot_id="snap-legacy-0001",
            stage="start",
            passport={"basic_stats": {"n": 10}},
            fingerprint="fp-legacy-" + "0" * 50,
            target_column="value",
            date_column="date",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        record, created = ensure_passport_snapshot_record(
            RUN_ID, subject, session_snapshot=legacy_snapshot, session_id=SESSION_ID,
        )
        assert created is True

        snapshot = read_passport_snapshot(
            RUN_ID, subject, snapshot_ref=record.snapshot_id, session_id=SESSION_ID,
        )
        assert snapshot["content_status"] == "missing_artifact"
        assert snapshot["passport"] is None
        assert snapshot["fingerprint"] is None
        assert snapshot["fingerprint_reason"] == "legacy_unknown"
        assert snapshot["source_hash"] is None
        assert snapshot["source_hash_reason"] == "legacy_unknown"
        assert snapshot["captured_at"] == "2026-01-01T00:00:00+00:00"
        assert snapshot["artifact_id"] is None

    def test_dangling_stage_ref_yields_gap_not_fabrication(self):
        """Чекпоинт со ссылками на несуществующие rs-записи (формат
        валиден, факт отсутствует): траектория даёт явные gaps, снимки
        не фабкуются, даты не выдумываются (AC12)."""
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import read_passport_trajectory
        from apps.api.visual_artifacts import register_passport_checkpoint

        _seed_run()
        subject = _owner_subject()
        payload = {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id("cp-dangling"),
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
                "context_id": "ctx-p05-dangling",
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

        trajectory = read_passport_trajectory(
            RUN_ID, subject,
            checkpoint_id=artifact.refs["checkpoint_id"], session_id=SESSION_ID,
        )
        assert trajectory is not None
        assert trajectory["confirmed_at"] == "2026-06-01T10:00:00+00:00"
        gap_stages = {gap["at"] for gap in trajectory["gaps"]}
        assert gap_stages == {"stage_refs.start", "stage_refs.validation", "stage_refs.exit", "snapshot_ref"}
        for gap in trajectory["gaps"]:
            assert gap["reason"] == "missing_snapshot_record"
            assert gap["detail"]
        assert trajectory["snapshots"] == {}
        # Ни одного fabricate-поля: снимков нет, даты нет.
        assert "snapshots" in trajectory and not trajectory["snapshots"]

    def test_corrupt_artifact_bytes_integrity_failure(self, client):
        """AC12: порча байтов паспортного артефакта в ObjectStore --
        content_status=corrupt, passport=None; captured_at остаётся
        доказуемым из rs-записи (метаданные целы), выдуманного контента
        и выдуманной даты нет."""
        import json

        from apps.api.artifact_store import get_artifact_object_store
        from apps.api.passport_history import read_passport_trajectory

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        capture = _capture_new(client, "modeling_entry", 5.0)
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, capture["checkpoint_id"])
        payload = _checkpoint_payload(artifact)

        # Порча байтов ОДНОГО stage-снимка (validation).
        from apps.api.report_snapshot import get_snapshot_registry

        target_ref = payload["stage_refs"]["validation"]
        record = get_snapshot_registry().get_snapshot_record(target_ref)
        assert record is not None
        dep_artifact_id = record.dependencies[0].split(":", 1)[1]
        from apps.api.artifact_store import get_artifact_registry

        dep_artifact = get_artifact_registry().get_artifact(dep_artifact_id)
        assert dep_artifact is not None
        object_path = get_artifact_object_store().path_for_key(dep_artifact.storage_key)
        original_bytes = object_path.read_bytes()
        assert json.loads(original_bytes.decode("utf-8"))  # целы до порчи
        object_path.write_bytes(b'{"tampered": true}')

        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        broken = trajectory["snapshots"]["validation"]
        assert broken["content_status"] == "corrupt"
        assert broken["passport"] is None
        assert broken["fingerprint"] is None
        assert broken["fingerprint_reason"] == "integrity_failure"
        # Дата честна из rs-метаданных -- не выдумана, не заменена.
        assert broken["captured_at"] == record.captured_at
        # Остальные снимки не затронуты.
        assert trajectory["snapshots"]["start"]["content_status"] == "present"
        assert trajectory["snapshots"]["exit"]["content_status"] == "present"


# ══════════════════════════════════════════════════════════════════════
# 5. Панельная вселенная изолирована (AC14)
# ══════════════════════════════════════════════════════════════════════

PANEL_COLUMNS = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "y",
}


class TestPanelIsolation:
    @pytest.fixture()
    def panel_client(self, client):
        client.get("/v1/session/modeling/state")
        assert client.cookies.get(SESSION_COOKIE_NAME)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get_or_create(session_id)
        session.set_dataframe(_panel_dataframe(), reason="pgv05-panel")
        session.target_column = "y"
        session.date_column = "date"
        from apps.api.session_store import DatasetInfo

        session.dataset = DatasetInfo(
            dataset_id="p05-panel-ds",
            name="pgv05-panel-seed",
            rows=120,
            columns=3,
            size_label="3 KB",
            dataset_fingerprint="p5p" * 8,
        )
        run_id = session.ensure_run_id()
        owner, tenant = session.ensure_owner_binding()
        store.save(session)
        _seed_run(run_id, session_id, owner_subject=owner, tenant_id=tenant)
        return client

    def test_panel_trajectory_carries_entity_and_universe(self, panel_client):
        """AC14: panel_entry траектория несёт entity-контекст и
        universe=panel; stage_refs.panel разрешается."""
        from apps.api.passport_history import read_passport_trajectory

        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        body = confirm.json()

        session = get_session_store().get(panel_client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, body["checkpoint_id"])
        assert artifact is not None

        trajectory = read_passport_trajectory(
            run_id, _owner_subject(session.session_id),
            checkpoint_id=artifact.refs["checkpoint_id"], session_id=session.session_id,
        )
        assert trajectory["stage"] == "panel_entry"
        assert trajectory["universe"] == "panel"
        assert trajectory["context"]["entity_id"] == "entity"
        panel_record = trajectory["snapshots"]["panel"]
        assert panel_record["content_status"] == "present"
        assert panel_record["stage"] == "panel_entry"
        assert trajectory["previous_snapshot"] is None

    def test_universe_lists_do_not_mix(self, panel_client, client):
        """AC14: списки по universe не смешивают panel_entry и
        single-series чекпоинты."""
        from apps.api.passport_history import list_passport_checkpoints

        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        panel_session = get_session_store().get(
            panel_client.cookies.get(SESSION_COOKIE_NAME)
        )
        panel_run_id = panel_session.run_id
        panel_subject = _owner_subject(panel_session.session_id)

        # Однорядный контур -- отдельный run/сессия.
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)
        single_session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        single_run_id = single_session.run_id

        panel_all = list_passport_checkpoints(
            panel_run_id, panel_subject, session_id=panel_session.session_id,
        )
        assert [item["stage"] for item in panel_all] == ["panel_entry"]
        assert all(item["universe"] == "panel" for item in panel_all)
        single_all = list_passport_checkpoints(
            single_run_id, _client_subject(client),
            session_id=_client_session_id(client),
        )
        assert [item["stage"] for item in single_all] == ["modeling_entry"]
        assert all(item["universe"] == "single" for item in single_all)
        # Фильтр по universe на смешанном запросе -- честная фильтрация.
        assert list_passport_checkpoints(
            panel_run_id, panel_subject, universe="single",
            session_id=panel_session.session_id,
        ) == []
        assert list_passport_checkpoints(
            single_run_id, _client_subject(client), universe="panel",
            session_id=_client_session_id(client),
        ) == []


# ══════════════════════════════════════════════════════════════════════
# 6. Списки-пикеры (§10 version picker) и доступ
# ══════════════════════════════════════════════════════════════════════


class TestPickerListsAndAccess:
    def test_list_checkpoints_picker_fields_sorted(self, client):
        """§10 version picker: run/context/target/time, IDs, stage,
        fingerprint/actuality (provenance + created_at); сортировка по
        confirmed_at."""
        from apps.api.passport_history import list_passport_checkpoints

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)
        _capture_new(client, "exit", 2.5)
        _capture(client, "modeling_entry")
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id

        checkpoints = list_passport_checkpoints(
            run_id, _client_subject(client), session_id=_client_session_id(client),
        )
        assert len(checkpoints) == 2
        confirmed_times = [item["confirmed_at"] for item in checkpoints]
        assert confirmed_times == sorted(confirmed_times)
        for item in checkpoints:
            assert item["checkpoint_id"].startswith("pck-")
            assert item["artifact_id"]
            assert item["stage"] == "modeling_entry"
            assert item["universe"] == "single"
            assert item["context"]["run_id"] == run_id
            assert item["context"]["target_column"] == "value"
            assert item["confirmed_at"]
            assert item["provenance"]["source"] == "producer_capture"
            assert item["integrity_status"] == "ok"
            assert item["fingerprint"], "fingerprint пикера резолвится из контента"
            assert item["created_at"]

    def test_list_snapshots_scoped_and_sorted(self, client):
        """Список snapshot-записей run'а: только pgv-passport записи,
        сортировка по captured_at; полный контракт полей."""
        from apps.api.passport_history import list_passport_snapshots

        _upload(client)
        _select_series(client)
        start = _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))

        snapshots = list_passport_snapshots(
            session.run_id, _client_subject(client),
            session_id=_client_session_id(client),
        )
        # Полный поток: start/validation/exit + created modeling_entry
        # -- 4 физических паспорта и 4 rs-записи (created-вариант).
        assert len(snapshots) == 4
        captured = [item["captured_at"] for item in snapshots]
        assert captured == sorted(captured)
        refs = {item["snapshot_ref"] for item in snapshots}
        assert len(refs) == 4
        stages = [item["stage"] for item in snapshots]
        assert stages.count("start") == 1
        assert stages.count("validation") == 1
        assert stages.count("exit") == 1
        assert stages.count("modeling_entry") == 1
        assert any(item["session_snapshot_id"] == start["snapshot_id"] for item in snapshots)

    def test_empty_run_honest_empty_lists(self):
        """Run без durable-паспортной истории -- пустые списки, ничего
        не фабкуется."""
        from apps.api.passport_history import (
            list_passport_checkpoints,
            list_passport_snapshots,
        )

        _seed_run()
        subject = _owner_subject()
        assert list_passport_checkpoints(RUN_ID, subject, session_id=SESSION_ID) == []
        assert list_passport_snapshots(RUN_ID, subject, session_id=SESSION_ID) == []

    def test_foreign_subject_and_missing_run_uniform_denial(self):
        """AC18-дух: чужой субъект и несуществующий run -- единый отказ
        без дисклоужения существования."""
        from apps.api.passport_history import (
            PassportHistoryAccessDenied,
            list_passport_checkpoints,
            read_passport_trajectory,
        )

        _seed_run()
        with pytest.raises(PassportHistoryAccessDenied):
            list_passport_checkpoints(
                RUN_ID, _foreign_subject(), session_id="p05-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            read_passport_trajectory(
                RUN_ID, _foreign_subject(), checkpoint_id="pck-any",
                session_id="p05-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            list_passport_checkpoints(
                "RUN-P05ABSENT", _owner_subject(), session_id=SESSION_ID,
            )

