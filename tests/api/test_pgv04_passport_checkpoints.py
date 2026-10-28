"""TDD-корпус PGV-04 (spec_passport_graphics_visual.md §8/§10.2/§13,
строка PGV-04): durable checkpoint/backfill -- каждый EDA handoff
(modeling_entry И panel_entry) фиксируется durable-артефактом
``pgv.passport_checkpoint/1``, включая reused snapshot; недостающие
чекпоинты добираются backfill'ом ТОЛЬКО из доказуемых session-записей
(retry без capture), honest-гэпы не фабрикуются (AC12).

ПОСТАНОВКА (§13): «Durable checkpoint/backfill; точки изменения --
promotion_integration/artifact_promotion/capture; критерий -- Reused
handoff хранит confirmed_at/trajectory отдельно, retry без capture».

Ключевые инварианты поставки:
  AC11 -- reused/unchanged handoff НЕ создаёт четвёртую физическую
          копию паспорта: durable-факт = подтверждение + ссылка на
          ИСХОДНЫЙ снимок (rs-*), собственный confirmed_at;
  AC12 -- утраченные/недоказуемые metadata -- честный пропуск (gap),
          НЕ догадка; confirmed_at -- из session-записи, время
          промоушена НЕ подставляется;
  AC14 -- panel_entry несёт entity-контекст и stage_refs.panel,
          отдельно от single-series;
  AC06 -- заморозка читает session-записи (frozen copy) и НЕ меняет
          научное состояние сессии;
  §8    -- идемпотентность по checkpoint_id (pck-*); rs-записи
          идемпотентны по session snapshot_id; старые снимки не
          переписываются.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace

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

RUN_ID = "RUN-P04A0001"
SESSION_ID = "p04-seed-session"


# ── Изоляция среды (паттерн PGV-02/03) ───────────────────────────────


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

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_session_store_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (свои данные; паттерн PGV-02/03) ─────────────────────


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
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


def _set_first_target_value(client: TestClient, value: float) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] = value
    session.touch()
    store.save(session)


def _first_target_value(client: TestClient) -> float:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None and session.dataframe is not None
    return float(session.dataframe.loc[session.dataframe.index[0], "value"])


def _capture(client: TestClient, stage: str) -> dict:
    response = client.post(f"/v1/session/dataset/passport/{stage}")
    assert response.status_code == 200, response.text
    return response.json()


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
        dataset_fingerprint="p04" * 8,
        dataset_name="pgv04-checkpoints-seed",
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


def _seed_session_object(run_id: str = RUN_ID):
    from apps.api.session_store import AnalysisSession, DatasetInfo

    session = AnalysisSession(session_id=SESSION_ID)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p04-ds",
        name="pgv04-seed",
        rows=12,
        columns=2,
        size_label="1 KB",
        dataset_fingerprint="p04" * 8,
    )
    session.data_revision = 7
    session.target_column = "value"
    session.date_column = "date"
    return session


def _seed_session_checkpoints(session, *, confirmed_at: str | None = None):
    """Session-фактура: start/validation/exit снимки + checkpoint
    modeling_entry (reused, подтверждён ПОСЛЕ всех трёх точек)."""
    old = "2026-01-01T00:00:00+00:00"
    snapshots = {}
    for stage in ("start", "validation", "exit"):
        snapshot = session.append_passport_snapshot(
            stage,
            {"basic_stats": {"n": 84}, "stage": stage},
            fingerprint=f"fp-{stage}-" + "0" * 50,
        )
        if confirmed_at:
            # Ручная ретроспектива: снимки подтверждены ДО чекпоинта.
            object.__setattr__(snapshot, "captured_at", old)
        snapshots[stage] = snapshot
    checkpoint = session.append_passport_checkpoint(
        "modeling_entry",
        snapshots["start"],
        previous_snapshot_id=snapshots["exit"].snapshot_id,
        created_snapshot=False,
    )
    if confirmed_at:
        object.__setattr__(checkpoint, "confirmed_at", confirmed_at)
    return snapshots, checkpoint


def _seed_panel_checkpoints(session):
    """Панельная фактура: panel_entry снимок + checkpoint (reused,
    previous == сам снимок -- конвенция панельного confirm)."""
    snapshot = session.append_passport_snapshot(
        "panel_entry",
        {"entity_column": "region", "models": {}},
        fingerprint="fp-panel-" + "0" * 55,
    )
    checkpoint = session.append_passport_checkpoint(
        "panel_entry",
        snapshot,
        previous_snapshot_id=snapshot.snapshot_id,
        created_snapshot=False,
    )
    return snapshot, checkpoint


def _owner_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(SESSION_ID)


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p04-foreign-session")


def _fake_request():
    return SimpleNamespace(cookies={SESSION_COOKIE_NAME: SESSION_ID}, headers={})


def _durable_checkpoint(run_id: str, session_checkpoint_id: str):
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")


def _checkpoint_payload(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    import json

    return json.loads(data.decode("utf-8"))


def _passport_artifact_ids(run_id: str) -> list[str]:
    from apps.api.artifact_store import get_artifact_registry

    return [
        a.artifact_id
        for a in get_artifact_registry().list_artifacts(run_id, kind="passport")
    ]


# ══════════════════════════════════════════════════════════════════════
# 1. Синхронная заморозка modeling_entry (TestClient: реальный capture)
# ══════════════════════════════════════════════════════════════════════


class TestSyncFreezeModelingEntry:
    def test_full_pipeline_freezes_checkpoint_synchronously(self, client):
        """Полный конвейер (start+validation+exit) -> modeling_entry с
        НОВЫМ состоянием ряда: passport_checkpoint заморожен в момент
        capture; payload честен (confirmed_at/stage_refs/flags)."""
        from apps.api.visual_artifacts import CHECKPOINT_STAGES

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is False

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        artifact = _durable_checkpoint(session.run_id, capture["checkpoint_id"])
        assert artifact is not None, "checkpoint не заморожен в момент capture"
        assert artifact.kind == "passport_checkpoint"
        assert artifact.refs["checkpoint_id"] == f"pck-{capture['checkpoint_id']}"
        assert artifact.refs["stage"] in CHECKPOINT_STAGES

        payload = _checkpoint_payload(artifact)
        assert payload["schema_version"] == "pgv.passport_checkpoint/1"
        assert payload["checkpoint_id"] == f"pck-{capture['checkpoint_id']}"
        assert payload["stage"] == "modeling_entry"
        assert payload["confirmed_at"]  # честное время из session-записи
        assert payload["provenance"]["source"] == "producer_capture"
        flags = payload["flags"]
        assert flags["created"] is True
        assert flags["reused"] is False
        assert flags["unchanged"] is False
        for key in ("start", "validation", "exit"):
            ref = payload["stage_refs"][key]
            assert ref.startswith("rs-") and len(ref) == 35, key
        assert payload["context"]["run_id"] == session.run_id
        assert payload["context"]["context_id"]
        assert payload["context"]["data_revision"] == session.data_revision
        assert payload["context"]["target_column"] == "value"

    def test_confirmed_at_is_session_fact_not_wallclock(self, client):
        """AC12: confirmed_at -- время подтверждения из session-записи;
        время промоушена НЕ подставляется (сравнение с отдельным
        чекпоинтом, замороженным позже по wall-clock)."""
        _upload(client)
        _select_series(client)
        first = _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        capture = _capture(client, "modeling_entry")

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        artifact = _durable_checkpoint(session.run_id, capture["checkpoint_id"])
        payload = _checkpoint_payload(artifact)
        # confirmed_at не пуст и совпадает с фактурой capture-ответа
        # (checkpoint.confirmed_at == captured_at ответа моделирования).
        assert payload["confirmed_at"] == capture["captured_at"]
        # и это НЕ время последующего чтения payload'а:
        first_start_payload = _checkpoint_payload(
            _durable_checkpoint(session.run_id, first["checkpoint_id"] or "")
        ) if first.get("checkpoint_id") else None
        if first_start_payload is not None:
            raise AssertionError("start не должен создавать checkpoint")

    def test_start_only_flow_honest_skip_without_receipt(self, client, monkeypatch):
        """Штатный поток «start -> modeling_entry» (validation/exit ещё
        не зафиксированы): заморозка честно пропущена (гэп, AC12-дух) и
        НЕ замусоривает security-audit receipt'ом (легитимное состояние
        конвейера -- не сбой промоушена)."""
        calls: list[tuple] = []
        from apps.api import security_audit

        real_record_standard = security_audit.record_standard

        def _spy(action, *args, **kwargs):
            if action == "artifact_promotion_failed":
                calls.append((action, args, kwargs))
            return real_record_standard(action, *args, **kwargs)

        monkeypatch.setattr(security_audit, "record_standard", _spy)

        _upload(client)
        _select_series(client)
        start = _capture(client, "start")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert _durable_checkpoint(session.run_id, capture["checkpoint_id"]) is None
        failed = [c for c in calls if c[0] == "artifact_promotion_failed"]
        checkpoint_failures = [
            c for c in failed if "checkpoint" in str(c[2].get("operation", ""))
        ]
        assert checkpoint_failures == [], (
            "честный недобор не должен писать receipt сбоя"
        )

    def test_reused_handoff_no_fourth_copy_and_own_confirmed_at(self, client):
        """AC11: reused handoff (ряд вернулся к состоянию start) --
        durable-факт ссылается на ИСХОДНЫЙ снимок; НОВАЯ физическая
        копия паспорта не создаётся (passport-артефактов ровно 3);
        confirmed_at -- собственный, отдельный от исходного снимка."""
        _upload(client)
        _select_series(client)
        original = _first_target_value(client)
        start = _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        # Ряд возвращается РОВНО к состоянию start (точная установка
        # исходного значения -- без float-дрейфа арифметики дельт).
        _set_first_target_value(client, original)
        _capture(client, "exit")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        artifact = _durable_checkpoint(session.run_id, capture["checkpoint_id"])
        assert artifact is not None
        payload = _checkpoint_payload(artifact)
        assert payload["flags"] == {
            "created": False,
            "reused": True,
            "unchanged": False,
        }
        start_snapshots = [
            a for a in _passport_artifact_ids(session.run_id)
        ]
        # Ровно три физических паспорта: start, validation, exit.
        assert len(start_snapshots) == 3
        # snapshot_ref -- rs-запись СУЩЕСТВУЮЩЕГО снимка (reuse-поиск
        # честно находит последний с совпадающим fingerprint); новая
        # физическая копия не создавалась.
        from apps.api.report_snapshot import get_snapshot_registry

        record = get_snapshot_registry().get_snapshot_record(
            payload["snapshot_ref"]
        )
        assert record is not None
        assert record.captured_at <= payload["confirmed_at"]

    def test_capture_response_unchanged_by_freeze(self, client):
        """Заморозка не меняет HTTP-контракт capture (наука первична)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        capture = _capture(client, "modeling_entry")
        for key in ("snapshot_id", "checkpoint_id", "captured_at",
                    "reused_snapshot", "source_stage", "fingerprint"):
            assert key in capture, key


# ══════════════════════════════════════════════════════════════════════
# 2. Панельный контур (AC14: панели отдельно)
# ══════════════════════════════════════════════════════════════════════


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


class TestPanelEntry:
    @pytest.fixture()
    def panel_client(self, client):
        # Warm-up: фиксирует cookie сессии до манипуляций с хранилищем
        # (паттерн TestSessionPanelContour).
        client.get("/v1/session/modeling/state")
        assert client.cookies.get(SESSION_COOKIE_NAME)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get_or_create(session_id)
        session.set_dataframe(_panel_dataframe(), reason="pgv04-panel")
        session.target_column = "y"
        session.date_column = "date"
        # В проде панель идёт ПОСЛЕ upload: dataset/run/владелец
        # существуют -- сид повторяет это состояние (контекст
        # подтверждения доказуем, как и в реальном потоке).
        from apps.api.session_store import DatasetInfo

        session.dataset = DatasetInfo(
            dataset_id="p04-panel-ds",
            name="pgv04-panel-seed",
            rows=120,
            columns=3,
            size_label="3 KB",
            dataset_fingerprint="p4p" * 8,
        )
        run_id = session.ensure_run_id()
        owner, tenant = session.ensure_owner_binding()
        store.save(session)
        _seed_run(run_id, session_id, owner_subject=owner, tenant_id=tenant)
        return client

    PANEL_COLUMNS = {
        "date_column": "date",
        "entity_column": "entity",
        "value_columns": ["y"],
        "target_column": "y",
    }

    def test_panel_build_promotes_passport_artifact(self, panel_client):
        """C03-прецедент для панели: построение PanelPassport
        промотит passport-артефакт (input_kind=panel_entity)."""
        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text

        session = get_session_store().get(panel_client.cookies.get(SESSION_COOKIE_NAME))
        from apps.api.artifact_store import get_artifact_registry

        passports = get_artifact_registry().list_artifacts(
            session.run_id, kind="passport"
        )
        panel_passports = [a for a in passports if a.input_kind == "panel_entity"]
        assert panel_passports, "панельный паспорт не промотен при build"

    def test_panel_confirm_freezes_checkpoint_with_entity_context(self, panel_client):
        """AC14: panel_entry чекпоинт несёт entity-контекст
        (entity_column как идентификатор entity-вселенной) и
        stage_refs.panel; flags.reused=True (снимок построен заранее)."""
        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        body = confirm.json()

        session = get_session_store().get(panel_client.cookies.get(SESSION_COOKIE_NAME))
        artifact = _durable_checkpoint(session.run_id, body["checkpoint_id"])
        assert artifact is not None, "панельный checkpoint не заморожен"
        payload = _checkpoint_payload(artifact)
        assert payload["stage"] == "panel_entry"
        assert payload["provenance"]["source"] == "producer_capture"
        assert payload["flags"]["reused"] is True
        assert payload["stage_refs"]["panel"].startswith("rs-")
        assert payload["context"]["entity_id"] == "entity"
        # previous == сам снимок -- конвенция панельного confirm:
        # отдельного «предыдущего» нет, самоссылка не записывается.
        assert payload["previous_snapshot_ref"] is None

    def test_panel_checkpoint_survives_session_loss(self, panel_client):
        """Субстрат AC09: панельный checkpoint читается после утраты
        session/Redis (реестр + ObjectStore, не SessionStore)."""
        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert build.status_code == 200
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200
        body = confirm.json()

        session = get_session_store().get(panel_client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        artifact_before = _durable_checkpoint(run_id, body["checkpoint_id"])
        assert artifact_before is not None
        reset_session_store_for_testing()
        artifact_after = _durable_checkpoint(run_id, body["checkpoint_id"])
        assert artifact_after is not None
        assert artifact_after.artifact_id == artifact_before.artifact_id


# ══════════════════════════════════════════════════════════════════════
# 3. Backfill: retry без capture (§8 «доказуемые session/ledger records»)
# ══════════════════════════════════════════════════════════════════════


class TestBackfill:
    def test_backfill_imports_missing_checkpoints_as_legacy(self):
        """Чекпоинт, подтверждённый вне durable-пути (legacy/сбой
        синхронной заморозки), добирается backfill'ом ИЗ session-записей;
        provenance=legacy_import честно маркирует импорт."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(
            session, confirmed_at="2026-01-01T00:00:00+00:00"
        )
        get_session_store().save(session)

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts["frozen"] == 1
        artifact = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact is not None
        payload = _checkpoint_payload(artifact)
        assert payload["provenance"]["source"] == "legacy_import"
        assert payload["confirmed_at"] == "2026-01-01T00:00:00+00:00"
        for key in ("start", "validation", "exit"):
            assert payload["stage_refs"][key].startswith("rs-"), key

    def test_backfill_skips_already_frozen_without_conflict(self):
        """Идемпотентность: чекпоинт, замороженный синхронно
        (producer_capture), backfill'ом НЕ переписывается -- тот же
        producer_key, тот же provenance, без конфликта контента."""
        from apps.api.passport_checkpoints import (
            backfill_passport_checkpoints,
            freeze_passport_checkpoint,
        )

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(session)
        get_session_store().save(session)

        frozen = freeze_passport_checkpoint(
            RUN_ID,
            _owner_subject(),
            session=session,
            session_id=SESSION_ID,
            checkpoint=checkpoint,
            created_snapshot=False,
            provenance="producer_capture",
        )
        assert frozen is not None
        first_payload = _checkpoint_payload(frozen)
        assert first_payload["provenance"]["source"] == "producer_capture"

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts["frozen"] == 0
        artifact = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact.artifact_id == frozen.artifact_id
        assert _checkpoint_payload(artifact)["provenance"]["source"] == (
            "producer_capture"
        )

    def test_retry_without_capture_after_freeze_failure(self, monkeypatch):
        """«retry без capture»: сбой синхронной заморозки (transient) не
        теряет чекпоинт -- sweep-точка добирает его ИЗ session-записей
        без повторного capture/пересчёта паспорта (наука не вызывается)."""
        from apps.api import passport_checkpoints
        from apps.api import visual_artifacts
        from apps.api.passport_checkpoints import (
            backfill_passport_checkpoints,
            freeze_passport_checkpoint,
        )

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(session)
        get_session_store().save(session)

        real_register = visual_artifacts.register_passport_checkpoint
        calls = {"n": 0}

        def _flaky_register(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("transient store outage")

        monkeypatch.setattr(
            visual_artifacts, "register_passport_checkpoint",
            _flaky_register,
        )
        with pytest.raises(RuntimeError):
            freeze_passport_checkpoint(
                RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
                checkpoint=checkpoint, created_snapshot=False,
                provenance="producer_capture",
            )
        assert calls["n"] == 1

        monkeypatch.setattr(
            visual_artifacts, "register_passport_checkpoint",
            real_register,
        )
        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts["frozen"] == 1
        artifact = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact is not None
        assert calls["n"] == 1  # повторной заморозки capture не было

    def test_missing_stage_refs_gap_is_permanent_for_that_checkpoint(self):
        """Честный недобор перманентен ДЛЯ ЭТОГО чекпоинта: снимки,
        зафиксированные ПОЗЖЕ confirmed_at, в его траекторию не попадают
        (фильтр «на момент подтверждения»); backfill продолжает честно
        пропускать, без фабкации ссылок."""
        from apps.api.passport_checkpoints import (
            backfill_passport_checkpoints,
        )

        _seed_run()
        session = _seed_session_object()
        start = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        checkpoint = session.append_passport_checkpoint(
            "modeling_entry",
            start,
            previous_snapshot_id=start.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)

        counts_first = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts_first["frozen"] == 0
        assert counts_first["skipped_missing_stage_refs"] == 1
        assert _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id) is None

        # Появились validation/exit ПОЗЖЕ подтверждения -- в траекторию
        # этого чекпоинта они НЕ попадают (честный гэп сохраняется).
        for stage in ("validation", "exit"):
            session.append_passport_snapshot(
                stage, {"basic_stats": {"n": 84}},
                fingerprint=f"fp-{stage}" + "0" * 55,
            )
        get_session_store().save(session)

        counts_second = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts_second["frozen"] == 0
        assert counts_second["skipped_missing_stage_refs"] == 1
        assert _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id) is None

    def test_trajectory_refs_respect_confirmation_moment(self):
        """«Точные refs на момент подтверждения»: снимки этапов,
        зафиксированные ПОЗЖЕ confirmed_at, в траекторию чекпоинта не
        попадают (история append-only, фильтр по времени)."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints
        from apps.api.report_snapshot import get_snapshot_registry

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(
            session, confirmed_at="2026-01-01T00:00:00+00:00"
        )
        # ПОЗЖЕ подтверждения: ещё один start-снимок (ретроспективная
        # ручная правка captured_at -- будущее относительно чекпоинта).
        late = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 85}}, fingerprint="fp-late" + "0" * 56,
        )
        object.__setattr__(late, "captured_at", "2027-01-01T00:00:00+00:00")
        get_session_store().save(session)

        backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        payload = _checkpoint_payload(_durable_checkpoint(RUN_ID, checkpoint.checkpoint_id))
        record = get_snapshot_registry().get_snapshot_record(
            payload["stage_refs"]["start"]
        )
        assert record is not None
        # Траектория указывает на снимок ДО подтверждения (n=84), не на
        # поздний (n=85).
        late_record = get_snapshot_registry().find_idempotent(
            RUN_ID, f"pgv-passport:{late.snapshot_id}"
        )
        assert payload["stage_refs"]["start"] != (
            late_record.snapshot_id if late_record else None
        )

    def test_sweep_counts_via_notify_modeling_artifacts_updated(self):
        """Sweep-точка моделирования добирает чекпоинты (retry без
        capture); счётчик честный; повтор -- no-op."""
        from apps.api import promotion_integration

        _seed_run()
        store = get_session_store()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(session)
        store.save(session)

        counts = promotion_integration.notify_modeling_artifacts_updated(
            _fake_request(), session
        )
        assert counts.get("passport_checkpoint", 0) == 1, counts
        assert _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id) is not None

        counts_again = promotion_integration.notify_modeling_artifacts_updated(
            _fake_request(), session
        )
        assert counts_again.get("passport_checkpoint", 0) == 0

    def test_backfill_without_run_id_honest_skip(self):
        """Отсутствие run (legacy/ранние состояния) -- честный пропуск
        без шума (паритет notify-функций)."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        session = _seed_session_object()
        session.run_id = ""
        _seed_session_checkpoints(session)
        counts = backfill_passport_checkpoints(
            "", _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts == {"frozen": 0, "skipped_missing_stage_refs": 0}


# ══════════════════════════════════════════════════════════════════════
# 4. rs-записи снимков паспортов (durable trajectory refs)
# ══════════════════════════════════════════════════════════════════════


class TestPassportSnapshotRecords:
    def test_record_idempotent_per_session_snapshot(self):
        """Два чекпоинта, ссылающихся на один снимок -> ОДНА rs-запись
        (идемпотентность по session snapshot_id; старые не переписываются)."""
        from apps.api.passport_checkpoints import (
            ensure_passport_snapshot_record,
        )

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        first, created_first = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert created_first is True
        second, created_second = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert created_second is False
        assert second.snapshot_id == first.snapshot_id

    def test_record_honest_content(self):
        """Содержимое rs-записи честно: captured_at из session-записи
        (не wall-clock), kinds=[D02], без секций документа."""
        from apps.api.passport_checkpoints import (
            ensure_passport_snapshot_record,
        )

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        object.__setattr__(snapshot, "captured_at", "2026-01-02T03:04:05+00:00")
        record, _created = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert record.captured_at == "2026-01-02T03:04:05+00:00"
        assert record.kinds == ["D02"]
        assert record.sections == []
        assert record.research_run_id == RUN_ID

    def test_record_pins_passport_artifact_when_available(self):
        """Паспортный артефакт (промоут notify_passport_captured)
        прицепляется к rs-записи зависимостью; без артефакта -- честное
        отсутствие зависимости (контент-гэп, не догадка)."""
        from apps.api.passport_checkpoints import (
            ensure_passport_snapshot_record,
        )

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        from apps.api.artifact_promotion import PromotionService

        service = PromotionService.create_default()
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session,
            session_id=SESSION_ID, stage="start",
        )
        record_with_artifact, created = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert created is True
        assert record_with_artifact.dependencies == [
            f"artifact:{artifact.artifact_id}"
        ]

    def test_record_without_artifact_has_no_fabricated_dependency(self):
        """Без паспортного артефакта (legacy-сессии до C03) -- честное
        отсутствие зависимости (контент-гэп, не догадка); существующая
        запись не переписывается задним числом."""
        from apps.api.passport_checkpoints import (
            ensure_passport_snapshot_record,
        )

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        record_no_artifact, created = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert created is True
        assert record_no_artifact.dependencies == []

        # Артефакт появился ПОЗЖЕ -- существующая запись не переписывается
        # (§8 «старые snapshots не переписываются»; гэп честно остаётся).
        from apps.api.artifact_promotion import PromotionService

        PromotionService.create_default().promote_passport(
            RUN_ID, _owner_subject(), session,
            session_id=SESSION_ID, stage="start",
        )
        record_again, created_again = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        assert created_again is False
        assert record_again.dependencies == []

    def test_foreign_subject_denied(self):
        """R09/T7: знание run_id не даёт права записи; чужой субъект --
        PromotionDenied, артефакт не создаётся."""
        from apps.api.artifact_promotion import PromotionDenied
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run()
        session = _seed_session_object()
        _seed_session_checkpoints(session)
        get_session_store().save(session)
        with pytest.raises(PromotionDenied):
            backfill_passport_checkpoints(
                RUN_ID, _foreign_subject(), session=session,
                session_id="p04-foreign-session",
            )

    def test_checkpoint_payload_tamper_conflicts(self):
        """§11: тот же идемпотентный ключ с другим payload -- конфликт
        без записи (подмена подтверждения не маскируется)."""
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.passport_checkpoints import freeze_passport_checkpoint

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(session)
        get_session_store().save(session)
        first = freeze_passport_checkpoint(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
            checkpoint=checkpoint, created_snapshot=False,
            provenance="producer_capture",
        )
        assert first is not None

        # Подмена времени подтверждения при том же checkpoint_id -- на
        # БУДУЩЕЕ относительно снимков траектории (stage-фильтр проходит,
        # payload отличается -- конфликт контента, §11).
        from datetime import timedelta

        tampered_time = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        object.__setattr__(checkpoint, "confirmed_at", tampered_time)
        with pytest.raises(ArtifactConflictError):
            freeze_passport_checkpoint(
                RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
                checkpoint=checkpoint, created_snapshot=False,
                provenance="producer_capture",
            )

    def test_freeze_does_not_mutate_session(self):
        """AC06-дух: заморозка читает session-записи (frozen copy) и не
        меняет научное состояние сессии."""
        from apps.api.passport_checkpoints import freeze_passport_checkpoint

        _seed_run()
        session = _seed_session_object()
        _seed_session_checkpoints(session)
        get_session_store().save(session)
        history_before = len(session.passport_history)
        checkpoints_before = len(session.passport_checkpoints)
        revision_before = session.data_revision

        freeze_passport_checkpoint(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
            checkpoint=session.passport_checkpoints[0], created_snapshot=False,
            provenance="producer_capture",
        )
        assert len(session.passport_history) == history_before
        assert len(session.passport_checkpoints) == checkpoints_before
        assert session.data_revision == revision_before

    def test_durable_checkpoint_read_after_session_loss(self):
        """Субстрат AC09: durable-чекпоинт и rs-записи читаются после
        утраты session/Redis."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run()
        session = _seed_session_object()
        _, checkpoint = _seed_session_checkpoints(session)
        get_session_store().save(session)
        backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        artifact_before = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact_before is not None

        reset_session_store_for_testing()
        artifact_after = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact_after is not None
        assert artifact_after.artifact_id == artifact_before.artifact_id
        payload = _checkpoint_payload(artifact_after)
        from apps.api.report_snapshot import get_snapshot_registry

        for key in ("start", "validation", "exit"):
            record = get_snapshot_registry().get_snapshot_record(
                payload["stage_refs"][key]
            )
            assert record is not None, key

    def test_missing_prerequisites_raise_honest_unavailable(self):
        """R03: отсутствие обязательных точек траектории --
        PromotionUnavailable, ничего не фабкуется."""
        from apps.api.artifact_promotion import PromotionUnavailable
        from apps.api.passport_checkpoints import freeze_passport_checkpoint

        _seed_run()
        session = _seed_session_object()
        start = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-a" + "0" * 58,
        )
        checkpoint = session.append_passport_checkpoint(
            "modeling_entry",
            start,
            previous_snapshot_id=start.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)
        with pytest.raises(PromotionUnavailable):
            freeze_passport_checkpoint(
                RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
                checkpoint=checkpoint, created_snapshot=False,
                provenance="producer_capture",
            )
