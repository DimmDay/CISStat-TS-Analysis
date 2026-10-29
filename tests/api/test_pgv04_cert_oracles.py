"""Сертификация PGV-04-CERT (2026-10-29) -- Class A: ОРАКУЛЫ НА СВОИХ
ДАННЫХ (GREEN на родителе c4e90b8, задача PGV-04).

Канал ORACLE мутационной кампании «на своих мутантах»: убивает боевых
мутантов passport_checkpoints.py/promotion_integration.py/роутеров,
которых repo-сюита поставки не ловит (wrong ref, tie-break траектории,
corrupt confirmed_at, passport-receipt reused, пин зависимости).

Разделение каналов (прецедент PGV-03-CERT):
  REPO  -- tests/api/test_pgv04_passport_checkpoints.py (24 поставки);
  ORACLE-- этот файл (Class A);
  Class B (RED-свидетельства находок) -- tests/api/test_pgv04_cert_
  findings.py, в кампании НЕ участвует (RED на родителе независимо от
  мутантов; обязаны стать GREEN после PGV-04-FIX).

Namespace данных: p4cert-* / RUN-P4CERT* (дизъюнкт с продуктовыми
пинами пинится статикой S2 с анти-самотриггером).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
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

CERT_TAG = "p4cert"

RUN_ID = "RUN-P4CERTA01"
SESSION_ID = "p4cert-oracle-session"


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


# ── Сид-хелперы (собственные данные) ─────────────────────────────────


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(4201)
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
):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    now = datetime.now(timezone.utc).isoformat()
    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p4c" * 8,
        dataset_name="p4cert-oracle-seed",
        target_column="value",
        created_at=now,
        last_active_at=now,
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _seed_session_object(run_id: str = RUN_ID, session_id: str = SESSION_ID):
    from apps.api.session_store import AnalysisSession, DatasetInfo

    session = AnalysisSession(session_id=session_id)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p4cert-ds",
        name="p4cert-seed",
        rows=12,
        columns=2,
        size_label="1 KB",
        dataset_fingerprint="p4c" * 8,
    )
    session.data_revision = 7
    session.target_column = "value"
    session.date_column = "date"
    return session


def _owner_subject(session_id: str = SESSION_ID):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def _fake_request(session_id: str = SESSION_ID):
    return SimpleNamespace(cookies={SESSION_COOKIE_NAME: session_id}, headers={})


def _durable_checkpoint(run_id: str, session_checkpoint_id: str):
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")


def _checkpoint_payload(artifact) -> dict:
    import json

    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))


def _seed_full_trajectory(session, *, confirmed_at: str | None = None):
    """start/validation/exit снимки + reused checkpoint modeling_entry,
    подтверждённый ПОСЛЕ всех трёх точек (ретроспектива опциональна)."""
    old = "2026-01-01T00:00:00+00:00"
    snapshots = {}
    for stage in ("start", "validation", "exit"):
        snapshot = session.append_passport_snapshot(
            stage,
            {"basic_stats": {"n": 84}, "stage": stage},
            fingerprint=f"fp-{stage}-" + "0" * 50,
        )
        if confirmed_at:
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


# ══════════════════════════════════════════════════════════════════════
# U. Юнит-оракулы чистых функций (свои данные, без HTTP)
# ══════════════════════════════════════════════════════════════════════


class TestUnitPayloadFunctions:
    def test_build_payload_deterministic_and_pure(self):
        """build_passport_checkpoint_payload -- чистая функция session-
        фактов: два вызова на неизменной сессии дают равные payload;
        сессия не мутируется (история/ревизия/чекпоинты)."""
        from apps.api.passport_checkpoints import build_passport_checkpoint_payload

        _seed_run()
        session = _seed_session_object()
        snapshots, checkpoint = _seed_full_trajectory(session)
        before = (
            len(session.passport_history),
            len(session.passport_checkpoints),
            session.data_revision,
        )
        kwargs = dict(
            created_snapshot=False,
            provenance="producer_capture",
            snapshot_ref="rs-" + "a" * 32,
            previous_snapshot_ref=None,
            stage_refs={"start": "rs-b" * 5, "validation": "rs-c" * 5, "exit": "rs-d" * 5},
        )
        first = build_passport_checkpoint_payload(session, checkpoint, **kwargs)
        second = build_passport_checkpoint_payload(session, checkpoint, **kwargs)
        after = (
            len(session.passport_history),
            len(session.passport_checkpoints),
            session.data_revision,
        )
        assert first == second, "payload недетерминирован"
        assert after == before, "построение payload мутирует сессию (AC06-дух)"

    def test_build_payload_honest_fields(self):
        """Честность полей payload: confirmed_at -- session-факт;
        flags по created_snapshot; provenance переносится как есть;
        unchanged не заявляется ни на одном пути."""
        from apps.api.passport_checkpoints import build_passport_checkpoint_payload

        _seed_run()
        session = _seed_session_object()
        old = "2026-01-02T03:04:05+00:00"
        snapshots, checkpoint = _seed_full_trajectory(session, confirmed_at=old)
        payload = build_passport_checkpoint_payload(
            session,
            checkpoint,
            created_snapshot=False,
            provenance="legacy_import",
            snapshot_ref="rs-" + "a" * 32,
            previous_snapshot_ref=None,
            stage_refs={},
        )
        assert payload["confirmed_at"] == old, "confirmed_at не session-факт"
        assert payload["schema_version"] == "pgv.passport_checkpoint/1"
        assert payload["provenance"] == {"source": "legacy_import"}
        assert payload["flags"] == {
            "created": False,
            "reused": True,
            "unchanged": False,
        }
        created_payload = build_passport_checkpoint_payload(
            session,
            checkpoint,
            created_snapshot=True,
            provenance="producer_capture",
            snapshot_ref="rs-" + "a" * 32,
            previous_snapshot_ref=None,
            stage_refs={},
        )
        assert created_payload["flags"] == {
            "created": True,
            "reused": False,
            "unchanged": False,
        }

    def test_build_payload_panel_entity_from_panel_columns(self):
        """AC14: панельный payload несёт entity_id = entity_column из
        panel_columns; при утраченных panel_columns -- None (валидатор
        честно отвергнет, фабкации нет)."""
        from apps.api.passport_checkpoints import build_passport_checkpoint_payload

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        checkpoint = session.append_panel_entry_checkpoint(
            snapshot,
            previous_snapshot_id=snapshot.snapshot_id,
            created_snapshot=False,
        )
        session.modeling_artifacts["panel_columns"] = {
            "date_column": "date",
            "entity_column": "entity",
            "value_columns": ["y"],
            "target_column": "value",
        }
        payload = build_passport_checkpoint_payload(
            session,
            checkpoint,
            created_snapshot=False,
            provenance="producer_capture",
            snapshot_ref="rs-" + "a" * 32,
            previous_snapshot_ref=None,
            stage_refs={"panel": "rs-" + "a" * 32},
        )
        assert payload["stage"] == "panel_entry"
        assert payload["context"]["entity_id"] == "entity"
        # Утраченные panel_columns -> None (не догадка)
        session.modeling_artifacts.pop("panel_columns")
        degraded = build_passport_checkpoint_payload(
            session,
            checkpoint,
            created_snapshot=False,
            provenance="producer_capture",
            snapshot_ref="rs-" + "a" * 32,
            previous_snapshot_ref=None,
            stage_refs={"panel": "rs-" + "a" * 32},
        )
        assert degraded["context"]["entity_id"] is None

    def test_stage_snapshot_at_respects_confirmation_moment_and_tie(self):
        """Траектория «на момент подтверждения»: снимок ПОЗЖЕ confirmed_at
        не выбирается; при равном времени -- последний добавленный в
        append-only истории (tie-break); отсутствие -- None."""
        from apps.api.passport_checkpoints import _stage_snapshot_at

        _seed_run()
        session = _seed_session_object()
        confirmed = datetime(2026, 1, 10, tzinfo=timezone.utc)
        before = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-before" + "0" * 52,
        )
        object.__setattr__(before, "captured_at", "2026-01-01T00:00:00+00:00")
        after = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 90}}, fingerprint="fp-after" + "0" * 52,
        )
        object.__setattr__(after, "captured_at", "2026-01-20T00:00:00+00:00")
        chosen = _stage_snapshot_at(session, "start", confirmed)
        assert chosen is before, "траектория включает снимок ПОЗЖЕ подтверждения"

        # Tie-break: два снимка с одним captured_at -- последний добавленный
        first = session.append_passport_snapshot(
            "validation", {"basic_stats": {"n": 1}}, fingerprint="fp-tie1" + "0" * 53,
        )
        second = session.append_passport_snapshot(
            "validation", {"basic_stats": {"n": 2}}, fingerprint="fp-tie2" + "0" * 53,
        )
        tie = "2026-01-05T00:00:00+00:00"
        object.__setattr__(first, "captured_at", tie)
        object.__setattr__(second, "captured_at", tie)
        chosen_tie = _stage_snapshot_at(session, "validation", confirmed)
        assert chosen_tie is second, "tie-break должен выбирать последний в истории"

        assert _stage_snapshot_at(session, "exit", confirmed) is None

    def test_parse_ts_honest(self):
        """_parse_ts: ISO с офсетом/Z, без tz -> UTC, мусор -> None
        (не догадка)."""
        from apps.api.passport_checkpoints import _parse_ts

        parsed = _parse_ts("2026-01-02T03:04:05+00:00")
        assert parsed is not None and parsed.utcoffset() == timedelta(0)
        naive = _parse_ts("2026-01-02T03:04:05")
        assert naive is not None and naive.utcoffset() == timedelta(0)
        assert _parse_ts("не время") is None
        assert _parse_ts("") is None
        assert _parse_ts(None) is None

    def test_durable_checkpoint_id_deterministic(self):
        """durable_checkpoint_id = pck- + session id; детерминизм
        (идемпотентность §8 между capture/backfill)."""
        from apps.api.passport_checkpoints import durable_checkpoint_id

        assert durable_checkpoint_id("abc-123") == "pck-abc-123"
        assert durable_checkpoint_id("abc-123") == durable_checkpoint_id("abc-123")


# ══════════════════════════════════════════════════════════════════════
# A. API-оракулы (TestClient: реальный capture-поток)
# ══════════════════════════════════════════════════════════════════════


class TestSyncFreezeOracles:
    def test_stage_refs_point_to_own_stage_snapshots(self, client):
        """«Wrong ref»-мутант-убийца: stage_refs[k] -- rs-запись ИМЕННО
        снимка этапа k (сверка captured_at через реестр rs-записей),
        а не confirmed/чужой снимок."""
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        capture = _capture(client, "modeling_entry")

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        artifact = _durable_checkpoint(session.run_id, capture["checkpoint_id"])
        assert artifact is not None
        payload = _checkpoint_payload(artifact)
        registry = get_snapshot_registry()
        history = session.passport_history
        for stage in ("start", "validation", "exit"):
            ref = payload["stage_refs"][stage]
            record = registry.get_snapshot_record(ref)
            assert record is not None, stage
            # Снимок этапа с ТОЧНО тем же captured_at существует в
            # session-истории и ссылается ровно на эту rs-запись.
            stage_captured = {
                item.captured_at
                for item in history
                if item.stage == stage
                and registry.find_idempotent(
                    session.run_id, f"pgv-passport:{item.snapshot_id}"
                )
                and registry.find_idempotent(
                    session.run_id, f"pgv-passport:{item.snapshot_id}"
                ).snapshot_id
                == ref
            }
            assert record.captured_at in stage_captured, (
                f"stage_refs.{stage} указывает на чужой снимок (wrong ref)"
            )
            assert record.captured_at <= payload["confirmed_at"], stage

    def test_confirmed_at_exact_session_fact_via_http(self, client):
        """confirmed_at payload == captured_at capture-ответа (session-
        факт подтверждения), не wall-clock заморозки/чтения."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        capture = _capture(client, "modeling_entry")
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        payload = _checkpoint_payload(
            _durable_checkpoint(session.run_id, capture["checkpoint_id"])
        )
        assert payload["confirmed_at"] == capture["captured_at"]

    def test_reused_capture_writes_no_passport_receipt(self, client, monkeypatch):
        """Попутный фикс поставки (док §2.7): reused handoff -- промоушен
        паспорта по фактическому stage снимка; НИКАКИХ
        artifact_promotion_failed для passport:* (receipt-шум легитимного
        состояния отсутствует)."""
        calls: list[tuple] = []
        from apps.api import security_audit

        real_record_standard = security_audit.record_standard

        def _spy(action, *args, **kwargs):
            calls.append((action, args, kwargs))
            return real_record_standard(action, *args, **kwargs)

        monkeypatch.setattr(security_audit, "record_standard", _spy)

        _upload(client)
        _select_series(client)
        original = _first_target_value(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _set_first_target_value(client, original)
        _capture(client, "exit")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        passport_receipts = [
            c
            for c in calls
            if c[0] == "artifact_promotion_failed"
            and str(c[2].get("resource_id") or "").startswith("passport:")
        ]
        assert passport_receipts == [], (
            "reused handoff не должен порождать passport-receipt"
        )
        # Чекпоинт при этом заморожен (полная траектория есть)
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert _durable_checkpoint(session.run_id, capture["checkpoint_id"]) is not None

    def test_corrupted_confirmed_at_honest_unavailable_no_writes(self, client, monkeypatch):
        """Corrupt legacy checkpoint (AC12): session-запись с битым
        confirmed_at -> PromotionUnavailable; НИЧЕГО не зарегистрировано
        (ни чекпоинта, ни rs-записей), wall-clock не подставляется."""
        from apps.api.artifact_promotion import PromotionUnavailable
        from apps.api.passport_checkpoints import freeze_passport_checkpoint
        from apps.api.report_snapshot import get_snapshot_registry

        _seed_run()
        session = _seed_session_object()
        snapshots, checkpoint = _seed_full_trajectory(session)
        object.__setattr__(checkpoint, "confirmed_at", "мусор-вместо-даты")
        get_session_store().save(session)

        with pytest.raises(PromotionUnavailable):
            freeze_passport_checkpoint(
                RUN_ID,
                _owner_subject(),
                session=session,
                session_id=SESSION_ID,
                checkpoint=checkpoint,
                created_snapshot=False,
                provenance="producer_capture",
            )
        # Ничего не зарегистрировано
        assert _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id) is None
        registry = get_snapshot_registry()
        for snapshot in snapshots.values():
            assert registry.find_idempotent(
                RUN_ID, f"pgv-passport:{snapshot.snapshot_id}"
            ) is None, "rs-запись создана при битом confirmed_at (фабкация)"

    def test_freeze_checkpoint_absent_on_missing_stage_snapshot(self, client):
        """Честный недобор (нет exit-снимка): PromotionUnavailable,
        ЧЕКПОИНТ не зарегистрирован. rs-записи вовлечённых снимков
        (start/validation) при этом создаются идемпотентно -- они честные
        адресуемые факты СУЩЕСТВУЮЩИХ снимков (наблюдение N-P4C1;
        неточность докстринга -- находка F-P4C3)."""
        from apps.api.artifact_promotion import PromotionUnavailable
        from apps.api.passport_checkpoints import freeze_passport_checkpoint
        from apps.api.report_snapshot import get_snapshot_registry

        _seed_run()
        session = _seed_session_object()
        start = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-start-" + "0" * 52,
        )
        validation = session.append_passport_snapshot(
            "validation", {"basic_stats": {"n": 84}}, fingerprint="fp-val-" + "0" * 53,
        )
        checkpoint = session.append_passport_checkpoint(
            "modeling_entry",
            start,
            previous_snapshot_id=validation.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)
        with pytest.raises(PromotionUnavailable):
            freeze_passport_checkpoint(
                RUN_ID,
                _owner_subject(),
                session=session,
                session_id=SESSION_ID,
                checkpoint=checkpoint,
                created_snapshot=False,
                provenance="producer_capture",
            )
        registry = get_snapshot_registry()
        assert _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id) is None, (
            "чекпоинт зарегистрирован при честном недоборе (фабкация)"
        )
        # Честные rs-факты существующих снимков допустимы; их ключи --
        # только pgv-passport:{существующий snapshot_id}.
        for snapshot in (start, validation):
            record = registry.find_idempotent(
                RUN_ID, f"pgv-passport:{snapshot.snapshot_id}"
            )
            assert record is None or record.research_run_id == RUN_ID

    def test_start_only_backfill_counts_and_no_receipt(self, monkeypatch):
        """Штатный поток «start -> modeling_entry» через backfill: счётчик
        skipped_missing_stage_refs честен; durable-receipt отсутствует
        (легитимное состояние -- не сбой промоушена)."""
        from apps.api import security_audit
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        calls: list[tuple] = []
        real_record_standard = security_audit.record_standard

        def _spy(action, *args, **kwargs):
            calls.append((action, args, kwargs))
            return real_record_standard(action, *args, **kwargs)

        monkeypatch.setattr(security_audit, "record_standard", _spy)

        _seed_run()
        session = _seed_session_object()
        start = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-start-" + "0" * 52,
        )
        checkpoint = session.append_passport_checkpoint(
            "modeling_entry",
            start,
            previous_snapshot_id=start.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)
        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts == {"frozen": 0, "skipped_missing_stage_refs": 1}, counts
        # Фильтр по ФАКТИЧЕСКОЙ структуре записи _record_failure:
        # operation -- в details, producer_key -- в resource_id.
        checkpoint_receipts = [
            c
            for c in calls
            if c[0] == "artifact_promotion_failed"
            and (
                "checkpoint"
                in str((c[2].get("details") or {}).get("operation", ""))
                or str(c[2].get("resource_id") or "").startswith("pgv.checkpoint")
            )
        ]
        assert checkpoint_receipts == []

    def test_notify_honest_skip_no_receipt_via_http(self, client, monkeypatch):
        """Notify-путь (эволюция корпуса после первой порции кампании):
        штатный поток «start -> modeling_entry» через HTTP -- честный
        недобор НЕ получает durable-receipt (легитимное состояние конвейера,
        не сбой промоушена); фильтр по фактической структуре записи
        (resource_id/details.operation)."""
        calls: list[tuple] = []
        from apps.api import security_audit

        real_record_standard = security_audit.record_standard

        def _spy(action, *args, **kwargs):
            calls.append((action, args, kwargs))
            return real_record_standard(action, *args, **kwargs)

        monkeypatch.setattr(security_audit, "record_standard", _spy)

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert _durable_checkpoint(session.run_id, capture["checkpoint_id"]) is None
        checkpoint_receipts = [
            c
            for c in calls
            if c[0] == "artifact_promotion_failed"
            and (
                "checkpoint"
                in str((c[2].get("details") or {}).get("operation", ""))
                or str(c[2].get("resource_id") or "").startswith("pgv.checkpoint")
            )
        ]
        assert checkpoint_receipts == [], (
            "честный недобор notify-канала не должен писать receipt"
        )

    def test_snapshot_record_pins_passport_artifact_with_reason(self):
        """§16: metadata graph хранит ПРИЧИНЫ ссылок -- pin паспортного
        артефакта с reason=passport_record:{rs-id} (мутант-убийца «no
        pin»)."""
        from apps.api.artifact_promotion import PromotionService
        from apps.api.passport_checkpoints import ensure_passport_snapshot_record

        _seed_run()
        session = _seed_session_object()
        snapshot = session.append_passport_snapshot(
            "start", {"basic_stats": {"n": 84}}, fingerprint="fp-start-" + "0" * 52,
        )
        service = PromotionService.create_default()
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session,
            session_id=SESSION_ID, stage="start",
        )
        record, _created = ensure_passport_snapshot_record(
            RUN_ID, _owner_subject(), session_snapshot=snapshot,
            session_id=SESSION_ID, created_by=None,
        )
        pins = [
            p
            for p in service.registry.list_pins(RUN_ID, ref_kind="artifact")
            if p.ref_id == artifact.artifact_id
        ]
        assert pins, "зависимость паспортного артефакта не запинена"
        assert any(
            p.reason == f"passport_record:{record.snapshot_id}" for p in pins
        ), f"pin-причина не соответствует контракту: {[p.reason for p in pins]}"

    def test_capture_response_carries_session_checkpoint_fact(self, client):
        """Capture-ответ несёт session-фактуру чекпоинта; заморозка не
        меняет ответ (наука первична; паритет repo-теста, свой сид)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        _mutate_target(client, 4.0)
        _capture(client, "exit")
        _mutate_target(client, 5.0)
        before = get_session_store().get(
            client.cookies.get(SESSION_COOKIE_NAME)
        ).data_revision
        capture = _capture(client, "modeling_entry")
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert capture["captured_at"]  # время подтверждения присутствует
        assert session.data_revision == before, "capture изменил ревизию данных"
        assert len(session.passport_checkpoints) == 1  # один чекпоинт


# ══════════════════════════════════════════════════════════════════════
# S. Статические оракулы (пины контрактов, wiring, дизъюнкт)
# ══════════════════════════════════════════════════════════════════════

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


class TestStaticPins:
    def test_wiring_exactly_two_freeze_call_sites(self):
        """Единая точка заморозки: notify_passport_checkpoint_confirmed
        вызывается РОВНО из двух capture-точек (modeling_entry в
        session.py, panel confirm в modeling_session.py); прямых вызовов
        freeze_passport_checkpoint в роутерах нет."""
        session_router = (REPO_ROOT / "apps/api/routers/session.py").read_text(
            encoding="utf-8"
        )
        modeling_router = (
            REPO_ROOT / "apps/api/routers/modeling_session.py"
        ).read_text(encoding="utf-8")
        integration = (REPO_ROOT / "apps/api/promotion_integration.py").read_text(
            encoding="utf-8"
        )
        checkpoint_module = (
            REPO_ROOT / "apps/api/passport_checkpoints.py"
        ).read_text(encoding="utf-8")

        assert session_router.count("notify_passport_checkpoint_confirmed(") == 1
        assert modeling_router.count("notify_passport_checkpoint_confirmed(") == 1
        assert "freeze_passport_checkpoint(" not in session_router
        assert "freeze_passport_checkpoint(" not in modeling_router
        # Реализация заморозки -- только в passport_checkpoints
        assert integration.count("freeze_passport_checkpoint(") == 1
        # backfill вызывается ровно из одной sweep-точки
        assert integration.count("backfill_passport_checkpoints(") == 1

    def test_namespace_disjoint_from_product(self):
        """Дизъюнкт namespace p4cert: продуктовое дерево не содержит
        строк сертификатора (анти-самотриггер)."""
        for path in (REPO_ROOT / "apps").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "p4cert" not in text, f"пин сертификатора в продукте: {path}"

    def test_r4_universe_isolation_static(self):
        """R4-изоляция вселенных: _stage_snapshot_at для panel_entry
        читает panel_passport_history, для остальных -- passport_history;
        _STAGE_UNIVERSES фиксирует скоупы."""
        module = (REPO_ROOT / "apps/api/passport_checkpoints.py").read_text(
            encoding="utf-8"
        )
        assert '"modeling_entry": "single"' in module
        assert '"panel_entry": "panel"' in module
        assert "session.panel_passport_history" in module
        assert "session.passport_history" in module

    def test_no_science_imports_in_checkpoint_module(self):
        """AC06: заморозка читает session-факты, научные функции не
        импортируются и не вызываются."""
        module = (REPO_ROOT / "apps/api/passport_checkpoints.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "calculate_ts_passport",
            "panel_fingerprint",
            "build_passport(",
            "to_csv",
            "dataframe",
        ):
            assert forbidden not in module, f"научный импорт/вызов: {forbidden}"

    def test_idempotency_prefixes_pinned(self):
        """Идемпотентность §8: префиксы pck- и pgv-passport: пинятся
        константами; producer_key чекпоинта -- pgv.checkpoint:{id}."""
        module = (REPO_ROOT / "apps/api/passport_checkpoints.py").read_text(
            encoding="utf-8"
        )
        artifacts = (REPO_ROOT / "apps/api/visual_artifacts.py").read_text(
            encoding="utf-8"
        )
        assert 'CHECKPOINT_ID_PREFIX = "pck-"' in module
        assert 'PASSPORT_RECORD_IDEMPOTENCY_PREFIX = "pgv-passport:"' in module
        assert 'f"pgv.checkpoint:{_str(payload.get(\'checkpoint_id\'))' in artifacts
        assert "producer_capture" in artifacts and "legacy_import" in artifacts

    def test_cert_document_exists_with_verdict(self):
        """Акт сертификации существует и содержит вердикт и находки."""
        act = REPO_ROOT / "docs/cert_pgv04_2026-10-29.md"
        assert act.is_file(), "акт docs/cert_pgv04_2026-10-29.md отсутствует"
        text = act.read_text(encoding="utf-8")
        for marker in (
            "PGV-04-CERT",
            "F-P4C1",
            "F-P4C2",
            "F-P4C3",
            "мутантов",
            "вердикт",
        ):
            assert marker.lower() in text.lower(), f"маркер акта: {marker}"

    def test_worklog_entry_present(self):
        """Worklog-запись сертификации существует."""
        worklog = (REPO_ROOT / "worklog/worklog11.md").read_text(encoding="utf-8")
        assert "Task ID: PGV-04-CERT" in worklog
        assert "F-P4C1" in worklog
