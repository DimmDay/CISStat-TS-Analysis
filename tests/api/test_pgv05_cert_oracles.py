"""PGV-05-CERT — Class A: оракулы на СВОИХ данных (обязаны быть GREEN
на родителе ad597cb). Независимая сертификация поставки PGV-05
PassportHistoryReader (apps/api/passport_history.py).

Метод: «мутанты на своих мутантах, оракулы на своих данных»
(прецеденты PGV-02-CERT/03-CERT/04-CERT). Namespace p5cert-* /
RUN-P5CERT* — дизъюнкт от продукта и от корпуса поставки (RUN-P05A*,
p05-*); дизъюнкт пинится статикой с анти-самотриггером (проверяется
только apps/).

Покрываемые инварианты поставки (§8/§10/§13 + AC):
  AC09 — чтение после утраты session/Redis из durable refs;
  AC10 — траектория на выбранное подтверждение (замороженные refs);
  AC11 — reused handoff -> исходный снимок, два адреса одной записи;
  AC12 — honest gaps/integrity failure, XOR «значение либо причина»;
  AC14 — панельная вселенная изолирована;
  §8   — полный контракт snapshot-записи, два разных хэша с
         определёнными алгоритмами, два разных доказуемых времени.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
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

RUN_ID = "RUN-P5CERT01"
SESSION_ID = "p5cert-seed-session"

PASSPORT_GROUPS_15 = (
    "autocorrelation",
    "basic_stats",
    "correlations",
    "determinism",
    "fft",
    "freq",
    "hurst",
    "normality",
    "periodogram",
    "seasonal_periods",
    "seasonality",
    "stationarity",
    "timestamp",
    "trend",
    "wavelet",
)


# ── Изоляция среды (паритет корпуса поставки) ────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
    ):
        monkeypatch.delenv(var, raising=False)
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


# ── Сид-хелперы (свои данные, namespace p5cert) ──────────────────────


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(4242)
    dates = pd.date_range("2024-03-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 10 + 0.07 * x + 2.5 * np.sin(2 * np.pi * x / 9) + rng.normal(0, 0.3, n)
    return pd.DataFrame({"date": dates, "value": values}).to_csv(index=False)


def _upload(client: TestClient) -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("p5cert.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
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
    store = get_session_store()
    session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


def _capture_new(client: TestClient, stage: str, delta: float) -> dict:
    _mutate_target(client, delta)
    return _capture(client, stage)


def _first_target_value(client: TestClient) -> float:
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.dataframe is not None
    return float(session.dataframe.loc[session.dataframe.index[0], "value"])


def _set_first_target_value(client: TestClient, value: float) -> None:
    store = get_session_store()
    session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] = value
    session.touch()
    store.save(session)


def _client_session_id(client: TestClient) -> str:
    return client.cookies.get(SESSION_COOKIE_NAME)


def _client_subject(client):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(_client_session_id(client))


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p5cert-foreign-session")


def _full_pipeline(client: TestClient):
    """Полный однорядный поток: 3 stage-снимка + created modeling_entry."""
    _upload(client)
    _select_series(client)
    start = _capture(client, "start")
    _capture_new(client, "validation", 3.0)
    _capture_new(client, "exit", 4.0)
    confirmed = _capture_new(client, "modeling_entry", 5.0)
    return start, confirmed


def _durable_checkpoint(run_id: str, session_checkpoint_id: str):
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")


def _checkpoint_payload(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))


def _passport_rs_records(run_id: str) -> list:
    from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
    from apps.api.report_snapshot import get_snapshot_registry

    return [
        record
        for record in get_snapshot_registry().list_records(run_id)
        if "D02" in (record.kinds or [])
        and str(record.idempotency_key or "").startswith(PASSPORT_RECORD_IDEMPOTENCY_PREFIX)
    ]


def _panel_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(77)
    rows = []
    for entity in ("city-alpha", "city-beta"):
        for t in range(36):
            rows.append(
                {
                    "date": (pd.Timestamp("2024-02-01") + pd.Timedelta(days=t)).date().isoformat(),
                    "entity": entity,
                    "y": 5 + t * 0.2 + rng.normal(0, 0.15),
                }
            )
    return pd.DataFrame(rows)


PANEL_COLUMNS = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "y",
}


# ══════════════════════════════════════════════════════════════════════
# U-блок: чистые функции/статика (XOR-машина, паритет вселенных, пины)
# ══════════════════════════════════════════════════════════════════════


class TestUnitAndStatics:
    def test_u1_xor_machine_value_excludes_reason(self):
        """U1: XOR-конвенция «значение либо явная причина» — машина
        _xor_set: значение присутствует -> reason None; отсутствует ->
        None + причина; оба сразу запрещены (AC12)."""
        from apps.api.passport_history import _xor_set

        record: dict = {}
        _xor_set(record, "fingerprint", "fp-value", "legacy_unknown")
        assert record["fingerprint"] == "fp-value"
        assert record["fingerprint_reason"] is None

        record2: dict = {}
        _xor_set(record2, "fingerprint", None, "legacy_unknown")
        assert record2["fingerprint"] is None
        assert record2["fingerprint_reason"] == "legacy_unknown"

    def test_u2_universe_map_parity(self):
        """U2: карта вселенных — паритет passport_checkpoints
        (_STAGE_UNIVERSES) + физические stage однорядного контура;
        панель отдельно (AC14); неизвестный stage -> None (не догадка)."""
        from apps.api.passport_checkpoints import _STAGE_UNIVERSES
        from apps.api.passport_history import _UNIVERSE_BY_STAGE

        assert _UNIVERSE_BY_STAGE["modeling_entry"] == "single"
        assert _UNIVERSE_BY_STAGE["panel_entry"] == "panel"
        assert _UNIVERSE_BY_STAGE["start"] == "single"
        assert _UNIVERSE_BY_STAGE["validation"] == "single"
        assert _UNIVERSE_BY_STAGE["exit"] == "single"
        for stage, universe in _STAGE_UNIVERSES.items():
            assert _UNIVERSE_BY_STAGE.get(stage) == universe, stage
        assert _UNIVERSE_BY_STAGE.get("unknown_stage_xyz") is None

    def test_u3_version_and_algorithm_pins(self):
        """U3: versioned-контракт и алгоритм source_hash пинованы (§8:
        «определение алгоритмов» — явно, не скрытая конвенция)."""
        from apps.api.passport_history import (
            PASSPORT_HISTORY_SCHEMA_VERSION,
            SOURCE_HASH_ALGORITHM,
        )

        assert PASSPORT_HISTORY_SCHEMA_VERSION == "pgv.passport_history/1"
        assert SOURCE_HASH_ALGORITHM == "sha256(canonical_json)"

    def test_s1_module_imports_and_no_write_calls(self):
        """S1: AST-границы reader'а: (а) нет session_store/pandas/redis
        импортов (§8: чтение НЕ из SessionStore); (б) нет вызовов
        write-функций промоушена (reader ТОЛЬКО читает, AC06)."""
        source = Path("apps/api/passport_history.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
            elif isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name:
                    called.add(name)
        forbidden = {
            name
            for name in imported
            if "session_store" in name
            or name.startswith("pandas")
            or name.startswith("redis")
        }
        assert not forbidden, f"запрещённые импорты: {sorted(forbidden)}"
        write_calls = {
            name
            for name in called
            if name
            in {
                "persist_visual_artifact",
                "freeze_passport_checkpoint",
                "register_passport_checkpoint",
                "freeze_visual_result",
                "freeze_visual_print_snapshot",
                "notify_passport_captured",
                "notify_passport_checkpoint_confirmed",
                "register_snapshot",
                "register_artifact",
                "pin_ref",
                "unregister_artifact",
                "ensure_passport_snapshot_record",
                "backfill_passport_checkpoints",
            }
        }
        assert not write_calls, f"reader вызывает write-функции: {sorted(write_calls)}"

    def test_s2_namespace_disjunct_no_self_trigger(self):
        """S2: namespace p5cert отсутствует в ПРОДУКТОВОМ дереве apps/
        (анти-самотриггер: оракулы не срабатывают на собственный
        namespace, прецедент PGV-04-CERT K02)."""
        hits: list[str] = []
        for path in Path("apps").rglob("*.py"):
            if "p5cert" in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(path))
        assert not hits, f"namespace p5cert просочился в продукт: {hits}"

    def test_s3_reader_module_exists_with_public_contract(self):
        """S3: публичный контракт reader'а существует и полон (§8/§10):
        4 публичные функции чтения + единый отказ доступа."""
        import apps.api.passport_history as module

        for name in (
            "read_passport_snapshot",
            "read_passport_trajectory",
            "list_passport_snapshots",
            "list_passport_checkpoints",
            "PassportHistoryAccessDenied",
        ):
            assert hasattr(module, name), name


# ══════════════════════════════════════════════════════════════════════
# A-блок 1: snapshot-контракт §8 (полные поля, два хэша, два времени)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotContractOracles:
    def test_a1_full_contract_fields_and_two_hashes_two_times(self, client):
        """A1/§8: полный контракт snapshot-записи на created-снимке:
        ПОЛНЫЙ паспорт (15 групп AS-IS), два РАЗНЫХ хэша с алгоритмами,
        два РАЗНЫХ доказуемых времени (captured=rs, created=артефакт),
        stamped-контекст, data_ref честен."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
        from apps.api.passport_history import read_passport_snapshot
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        confirmed = _capture_new(client, "modeling_entry", 5.0)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id

        record = get_snapshot_registry().find_idempotent(
            run_id, f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{confirmed['snapshot_id']}"
        )
        assert record is not None
        snapshot = read_passport_snapshot(
            run_id, _client_subject(client),
            snapshot_ref=record.snapshot_id, session_id=_client_session_id(client),
        )
        # -- полный контракт полей --
        assert snapshot["schema_version"] == "pgv.passport_history/1"
        assert snapshot["snapshot_ref"] == record.snapshot_id
        assert snapshot["session_snapshot_id"] == confirmed["snapshot_id"]
        assert snapshot["artifact_id"]
        assert snapshot["stage"] == "modeling_entry"
        assert snapshot["universe"] == "single"
        assert snapshot["content_status"] == "present"
        assert snapshot["content_gap_reason"] is None
        # -- ПОЛНОЕ содержимое AS-IS (§8: не сокращается) --
        passport = snapshot["passport"]
        assert isinstance(passport, dict)
        for group in PASSPORT_GROUPS_15:
            assert group in passport, f"группа {group} потеряна (§8/AC09)"
        assert passport["basic_stats"]["n"] == 84
        # -- target/date --
        assert snapshot["target_column"] == "value"
        assert snapshot["date_column"] == "date"
        # -- два разных доказуемых времени (§8) --
        # captured_at = время capture СНИМКА (session-факт, перенесён в
        # rs-запись); НЕ время чтения и НЕ checkpoint.confirmed_at
        # (capture-ответ modeling_entry несёт confirmed_at -- они
        # расходятся на микросекунды, что и поймал первый черновик
        # оракула: дефект оракула исправлен честно до кампании).
        session_after = get_session_store().get(_client_session_id(client))
        session_snapshot = session_after.passport_snapshot(confirmed["snapshot_id"])
        assert session_snapshot is not None
        assert snapshot["captured_at"] == session_snapshot.captured_at
        assert snapshot["created_at"]
        assert snapshot["created_at"] >= snapshot["captured_at"]
        # -- stamped-контекст created-снимка --
        assert snapshot["context_id"] == record.context_id
        assert snapshot["context_id"]
        assert snapshot["data_revision"] == record.data_revision
        assert snapshot["data_ref"] is None
        # -- два разных хэша с определёнными алгоритмами (§8) --
        artifact = get_artifact_registry().get_artifact(snapshot["artifact_id"])
        assert artifact is not None and artifact.kind == "passport"
        assert snapshot["source_hash"] == artifact.payload_sha256
        assert snapshot["source_hash_algorithm"] == "sha256(canonical_json)"
        assert snapshot["fingerprint"] == confirmed["fingerprint"]
        assert snapshot["fingerprint_reason"] is None
        assert snapshot["source_hash"] != snapshot["fingerprint"]

    def test_a2_foreign_and_nonpassport_refs_uniform_none(self, client):
        """A2/uniform: чужой СУЩЕСТВУЮЩИЙ rs-ref, не-паспортная запись
        своего run и отсутствующий ref — единый None без фабкации и без
        утечки чужого контента (AC18-дух)."""
        from apps.api.passport_history import read_passport_snapshot
        from apps.api.report_snapshot import ReportSnapshot, get_snapshot_registry, new_snapshot_id

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)
        session_id = _client_session_id(client)

        # Чужой существующий rs-ref (второй run, полный поток).
        with TestClient(app) as client2:
            _upload(client2)
            _select_series(client2)
            _capture(client2, "start")
            _capture_new(client2, "validation", 1.0)
            _capture_new(client2, "exit", 2.0)
            _capture_new(client2, "modeling_entry", 3.0)
            session2 = get_session_store().get(_client_session_id(client2))
            run2 = session2.run_id
        foreign_ref = _passport_rs_records(run2)[0].snapshot_id
        assert read_passport_snapshot(
            run_id, subject, snapshot_ref=foreign_ref, session_id=session_id
        ) is None, "чужой rs-ref вернул контент -- утечка (AC18-дух)"

        # Не-паспортная rs-запись СВОЕГО run (D01).
        registry = get_snapshot_registry()
        doc = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=run_id,
            context_id=None,
            data_revision=None,
            data_ref=None,
            data_digest=None,
            source_cutoff={},
            captured_at="2026-10-29T01:00:00+00:00",
            knowledge_version=None,
            classification="private",
            redaction_profile="owner-v1",
            completeness={"status": "partial", "missing_refs": [], "missing_mandatory": []},
            reproducibility={"status": "limited", "reasons": ["p5cert-seed"]},
            sections=[],
            dependencies=[],
            approval=None,
            kinds=["D01"],
            idempotency_key="p5cert-doc:1",
            request_fingerprint="1" * 64,
            created_by=subject.subject_id,
        )
        stored, _ = registry.register_snapshot(doc, [])
        assert read_passport_snapshot(
            run_id, subject, snapshot_ref=stored.snapshot_id, session_id=session_id
        ) is None, "не-паспортная rs-запись не должна читаться reader'ом"

        # Отсутствующий ref.
        assert read_passport_snapshot(
            run_id, subject, snapshot_ref="rs-" + "e" * 32, session_id=session_id
        ) is None

    def test_a3_xor_on_live_contract_present_and_legacy(self, client):
        """A3/AC12: XOR «значение либо причина» на живом контракте:
        present-запись — reason None при значении; legacy-запись (rs без
        артефакта) — None + legacy_unknown для ВСЕХ XOR-полей, captured_at
        честен из rs-метаданных, фабкации ('v1', текущее время) нет."""
        from types import SimpleNamespace

        from apps.api.passport_checkpoints import ensure_passport_snapshot_record
        from apps.api.passport_history import read_passport_snapshot

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        # present: XOR по всем четырём полям.
        snapshot = read_passport_snapshot(
            run_id, subject,
            snapshot_ref=_passport_rs_records(run_id)[0].snapshot_id,
            session_id=_client_session_id(client),
        )
        for field in (
            "fingerprint",
            "source_hash",
            "passport_schema_version",
            "calculation_version",
        ):
            value, reason = snapshot[field], snapshot.get(f"{field}_reason")
            assert not (value is not None and reason is not None), field
            assert not (value is None and not reason), field

        # legacy: rs-запись без паспортного артефакта.
        legacy = SimpleNamespace(
            snapshot_id="snap-p5cert-legacy",
            stage="start",
            passport={"basic_stats": {"n": 7}},
            fingerprint="b" * 64,
            target_column="value",
            date_column="date",
            captured_at="2026-01-15T12:00:00+00:00",
        )
        record, created = ensure_passport_snapshot_record(
            run_id, subject, session_snapshot=legacy, session_id=_client_session_id(client),
        )
        assert created is True
        item = read_passport_snapshot(
            run_id, subject, snapshot_ref=record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert item["content_status"] == "missing_artifact"
        assert item["content_gap_reason"] == "passport_artifact_absent"
        assert item["passport"] is None
        for field in ("fingerprint", "source_hash", "passport_schema_version", "calculation_version"):
            assert item[field] is None, field
            assert item[f"{field}_reason"] == "legacy_unknown", field
        assert item["captured_at"] == "2026-01-15T12:00:00+00:00"
        assert item["created_at"] is None
        assert item["artifact_id"] is None

    def test_a4_forward_compat_schema_versions_surfaced(self, client):
        """A4: payload с passport_schema_version/calculation_version
        (будущие captures) — reader изВЛЕКАЕТ значения, reason None;
        честная граница «без изменения reader'а» подтверждена делом."""
        from apps.api.artifact_promotion import PromotionService
        from apps.api.passport_checkpoints import ensure_passport_snapshot_record
        from apps.api.passport_history import read_passport_snapshot
        from types import SimpleNamespace

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        future_sid = "snap-p5cert-future"
        payload = {
            "kind": "passport",
            "stage": "start",
            "passport": {"basic_stats": {"n": 84}, "custom_group": {"z": 3}},
            "snapshot_id": future_sid,
            "fingerprint": "c" * 64,
            "target_column": "value",
            "date_column": "date",
            "captured_at": "2026-10-29T05:00:00+00:00",
            "passport_schema_version": "passport/9",
            "calculation_version": "calc-77",
        }
        PromotionService.create_default()._persist(
            run_id=run_id,
            subject=subject,
            kind="passport",
            producer_key=f"passport:{future_sid}",
            payload=payload,
            dependencies=[],
            refs={"snapshot_id": future_sid, "stage": "start", "fingerprint": "c" * 64},
            context_id=None,
            data_revision=None,
            source_bytes_sha256=None,
        )
        record, created = ensure_passport_snapshot_record(
            run_id, subject,
            session_snapshot=SimpleNamespace(
                snapshot_id=future_sid,
                stage="start",
                passport=payload["passport"],
                fingerprint="c" * 64,
                target_column="value",
                date_column="date",
                captured_at="2026-10-29T05:00:00+00:00",
            ),
            session_id=_client_session_id(client),
        )
        assert created
        item = read_passport_snapshot(
            run_id, subject, snapshot_ref=record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert item["content_status"] == "present"
        assert item["passport_schema_version"] == "passport/9"
        assert item["passport_schema_version_reason"] is None
        assert item["calculation_version"] == "calc-77"
        assert item["calculation_version_reason"] is None
        assert "custom_group" in item["passport"]

    def test_a5_association_substitution_is_corrupt(self, client):
        """A5/AC12: подмена ассоциации payload<->rs-запись (артефакт под
        producer_key passport:{sid} несёт payload.snapshot_id ДРУГОГО
        снимка) — content_status=corrupt/snapshot_id_mismatch, контент
        НЕ выдаётся под чужой идентичностью."""
        from apps.api.artifact_promotion import PromotionService
        from apps.api.passport_checkpoints import ensure_passport_snapshot_record
        from apps.api.passport_history import read_passport_snapshot
        from types import SimpleNamespace

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        victim_sid = "snap-p5cert-victim"
        PromotionService.create_default()._persist(
            run_id=run_id,
            subject=subject,
            kind="passport",
            producer_key=f"passport:{victim_sid}",
            payload={
                "kind": "passport",
                "stage": "start",
                "passport": {"basic_stats": {"n": 1}},
                "snapshot_id": "snap-OTHER-p5cert",  # НЕ victim
                "fingerprint": "d" * 64,
                "target_column": "value",
                "date_column": "date",
                "captured_at": "2026-10-29T06:00:00+00:00",
            },
            dependencies=[],
            refs={"snapshot_id": victim_sid, "stage": "start", "fingerprint": "d" * 64},
            context_id=None,
            data_revision=None,
            source_bytes_sha256=None,
        )
        record, _ = ensure_passport_snapshot_record(
            run_id, subject,
            session_snapshot=SimpleNamespace(
                snapshot_id=victim_sid,
                stage="start",
                passport={"basic_stats": {"n": 1}},
                fingerprint="d" * 64,
                target_column="value",
                date_column="date",
                captured_at="2026-10-29T06:00:00+00:00",
            ),
            session_id=_client_session_id(client),
        )
        item = read_passport_snapshot(
            run_id, subject, snapshot_ref=record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert item["content_status"] == "corrupt"
        assert item["content_gap_reason"] == "snapshot_id_mismatch"
        assert item["passport"] is None
        assert item["fingerprint"] is None
        assert item["fingerprint_reason"] == "integrity_failure"
        # Recorded-хэш остаётся доказуемым фактом ожидаемого контента.
        assert item["source_hash"] is not None

    def test_a6_registry_hash_mismatch_second_integrity_layer(self, client):
        """A6/AC12: ВТОРОЙ слой целостности — сверка sha256 прочитанных
        байтов с payload_sha256 РЕЕСТРА (байты passes content-key, но
        registry-метаданные обещают другой контент) — corrupt
        payload_sha256_mismatch, контент не выдаётся."""
        from dataclasses import replace

        from apps.api.artifact_store import (
            ResultArtifact,
            get_artifact_object_store,
            get_artifact_registry,
            new_artifact_id,
        )
        from apps.api.passport_checkpoints import ensure_passport_snapshot_record
        from apps.api.passport_history import read_passport_snapshot
        from types import SimpleNamespace

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        # Честные байты под своим content-key...
        good_payload = {
            "kind": "passport",
            "stage": "start",
            "passport": {"basic_stats": {"n": 5}},
            "snapshot_id": "snap-p5cert-hash",
            "fingerprint": "e" * 64,
            "target_column": "value",
            "date_column": "date",
            "captured_at": "2026-10-29T07:00:00+00:00",
        }
        good_bytes = json.dumps(good_payload, ensure_ascii=False).encode("utf-8")
        good_sha = hashlib.sha256(good_bytes).hexdigest()
        store = get_artifact_object_store()
        staged = store.stage_bytes(good_bytes, "application/json")
        key = store.commit_staged(staged)
        # ...но registry обещает ДРУГОЙ payload_sha256 (метаданные
        # расходятся с байтами; ObjectStore доволен, reader обязан
        # поймать расхождение вторым слоем).
        artifact = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=run_id,
            kind="passport",
            producer_key="passport:snap-p5cert-hash",
            media_type="application/json",
            size_bytes=len(good_bytes),
            payload_sha256="f" * 64,  # НЕ хэш good_bytes
            storage_key=key,
            refs={"snapshot_id": "snap-p5cert-hash", "stage": "start"},
        )
        get_artifact_registry().register_artifact(artifact)
        record, _ = ensure_passport_snapshot_record(
            run_id, subject,
            session_snapshot=SimpleNamespace(
                snapshot_id="snap-p5cert-hash",
                stage="start",
                passport={"basic_stats": {"n": 5}},
                fingerprint="e" * 64,
                target_column="value",
                date_column="date",
                captured_at="2026-10-29T07:00:00+00:00",
            ),
            session_id=_client_session_id(client),
        )
        item = read_passport_snapshot(
            run_id, subject, snapshot_ref=record.snapshot_id,
            session_id=_client_session_id(client),
        )
        assert item["content_status"] == "corrupt"
        assert item["content_gap_reason"] == "payload_sha256_mismatch"
        assert item["passport"] is None
        # Recorded-хэш (registry-факт) при этом доказуем.
        assert item["source_hash"] == "f" * 64


# ══════════════════════════════════════════════════════════════════════
# A-блок 2: траектория (AC10/AC11), gaps (AC12), панель (AC14)
# ══════════════════════════════════════════════════════════════════════


class TestTrajectoryOracles:
    def test_a7_frozen_refs_exactness_two_trajectories(self, client):
        """A7/AC10: траектории двух подтверждений независимы; stage_refs
        РОВНО замороженные refs чекпоинта (совпадение по каждому этапу);
        первая НЕ переключилась на поздний exit; старые snapshots не
        переписываются."""
        from apps.api.passport_history import read_passport_trajectory

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        first = _capture_new(client, "modeling_entry", 5.0)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        first_ref = _durable_checkpoint(run_id, first["checkpoint_id"]).refs["checkpoint_id"]
        first_payload = _checkpoint_payload(_durable_checkpoint(run_id, first["checkpoint_id"]))

        _capture_new(client, "exit", 2.0)
        second = _capture(client, "modeling_entry")
        second_ref = _durable_checkpoint(run_id, second["checkpoint_id"]).refs["checkpoint_id"]
        assert second_ref != first_ref

        traj_first = read_passport_trajectory(
            run_id, _client_subject(client), checkpoint_id=first_ref,
            session_id=_client_session_id(client),
        )
        traj_second = read_passport_trajectory(
            run_id, _client_subject(client), checkpoint_id=second_ref,
            session_id=_client_session_id(client),
        )
        # stage_refs РОВНО замороженные (по каждому этапу).
        for stage in ("start", "validation", "exit"):
            assert traj_first["snapshots"][stage]["snapshot_ref"] == first_payload["stage_refs"][stage]
        # Первая траектория не переключилась на поздний exit (AC10).
        assert (
            traj_first["snapshots"]["exit"]["snapshot_ref"]
            != traj_second["snapshots"]["exit"]["snapshot_ref"]
        )
        # Fingerprint'ы подтверждений различны и честны.
        assert traj_first["snapshots"]["modeling_entry"]["fingerprint"] == first["fingerprint"]
        assert traj_second["snapshots"]["modeling_entry"]["fingerprint"] == second["fingerprint"]
        # confirmed_at -- payload-факт чекпоинта (не время чтения).
        assert traj_first["confirmed_at"] == first_payload["confirmed_at"]
        assert traj_second["confirmed_at"] != traj_first["confirmed_at"]

    def test_a8_reused_handoff_two_addresses_one_record(self, client):
        """A8/AC11: reused handoff — подтверждённый снимок доступен под
        ОБОИМИ адресами (физический exit И путь подтверждения
        modeling_entry), это ОДИН объект (алиас, не копия); новых
        артефактов/записей/пинов чтение не создаёт; физических
        паспортов ровно 3 (без четвёртой копии)."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_history import read_passport_trajectory
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        original = _first_target_value(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _set_first_target_value(client, original)  # ряд == start -> reuse
        _capture(client, "exit")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True

        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        artifact = _durable_checkpoint(run_id, capture["checkpoint_id"])
        payload = _checkpoint_payload(artifact)

        arts_before = len(get_artifact_registry().list_artifacts(run_id))
        recs_before = len(get_snapshot_registry().list_records(run_id))
        pins_before = len(get_artifact_registry().list_pins(run_id))

        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        # Адрес 1 -- физический этап exit; адрес 2 -- путь подтверждения
        # modeling_entry; ОДИН И ТОТ ЖЕ объект записи (алиасинг).
        confirmed_by_path = trajectory["snapshots"]["modeling_entry"]
        confirmed_by_stage = trajectory["snapshots"]["exit"]
        assert confirmed_by_path is confirmed_by_stage
        assert confirmed_by_path["snapshot_ref"] == payload["snapshot_ref"]
        assert confirmed_by_path["content_status"] == "present"
        assert confirmed_by_path["passport"]
        # flags reused честны.
        assert trajectory["flags"]["reused"] is True
        assert trajectory["flags"]["created"] is False
        # Ровно три физических паспорта; чтение ничего не добавило.
        assert len(get_artifact_registry().list_artifacts(run_id, kind="passport")) == 3
        assert len(get_artifact_registry().list_artifacts(run_id)) == arts_before
        assert len(get_snapshot_registry().list_records(run_id)) == recs_before
        assert len(get_artifact_registry().list_pins(run_id)) == pins_before

    def test_a9_dangling_refs_honest_gaps_payload_time_kept(self, client):
        """A9/AC12: чекпоинт с висячими refs — явные gaps по ТОЧНЫМ
        адресам (stage_refs.* + snapshot_ref), snapshots пуст, НО
        commit-факты (confirmed_at/flags/context) читаются из payload —
        время подтверждения не теряется и не выдумывается."""
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import read_passport_trajectory
        from apps.api.visual_artifacts import register_passport_checkpoint

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        payload = {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id("p5cert-dangling"),
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
                "run_id": run_id,
                "context_id": "ctx-p5cert-dangling",
                "data_revision": 3,
                "target_column": "value",
                "entity_id": None,
            },
            "provenance": {"source": "legacy_import"},
        }
        artifact = register_passport_checkpoint(
            run_id, subject, payload=payload, session_id=_client_session_id(client),
        )
        assert artifact is not None
        trajectory = read_passport_trajectory(
            run_id, subject,
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        assert trajectory is not None
        assert trajectory["confirmed_at"] == "2026-06-01T10:00:00+00:00"
        assert trajectory["integrity_status"] == "ok"
        gap_stages = {gap["at"] for gap in trajectory["gaps"]}
        assert gap_stages == {
            "stage_refs.start",
            "stage_refs.validation",
            "stage_refs.exit",
            "snapshot_ref",
        }
        for gap in trajectory["gaps"]:
            assert gap["reason"] == "missing_snapshot_record"
            assert gap["detail"]
        assert trajectory["snapshots"] == {}

    def test_a10_panel_universe_isolated_entity_context(self, client):
        """A10/AC14: панельная траектория несёт entity-контекст и
        universe=panel; списки по universe не смешивают вселенные;
        однорядный чекпоинт под panel-фильтр не попадает и наоборот."""
        from apps.api.passport_history import (
            list_passport_checkpoints,
            read_passport_trajectory,
        )
        from apps.api.session_store import DatasetInfo

        # Панельный контур (свой run).
        client.get("/v1/session/modeling/state")
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get_or_create(session_id)
        session.set_dataframe(_panel_dataframe(), reason="p5cert-panel")
        session.target_column = "y"
        session.date_column = "date"
        session.dataset = DatasetInfo(
            dataset_id="p5cert-panel-ds",
            name="p5cert-panel",
            rows=72,
            columns=3,
            size_label="3 KB",
            dataset_fingerprint="p5c" * 8,
        )
        run_id = session.ensure_run_id()
        owner, tenant = session.ensure_owner_binding()
        store.save(session)
        from apps.api.identity import DEFAULT_TENANT_ID
        from apps.api.research_runs import ResearchRun, get_research_run_store
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        get_research_run_store().upsert_run(ResearchRun(
            run_id=run_id, session_id=session_id, dataset_fingerprint="p5c" * 8,
            dataset_name="p5cert-panel", target_column="y", created_at=now,
            last_active_at=now, status="active", owner_subject=owner,
            tenant_id=tenant or DEFAULT_TENANT_ID, ownership="bound",
        ))
        build = client.post("/v1/session/modeling/panel/passport", json=PANEL_COLUMNS)
        assert build.status_code == 200, build.text
        confirm = client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        panel_subject = _client_subject(client)

        artifact = _durable_checkpoint(run_id, confirm.json()["checkpoint_id"])
        assert artifact is not None
        trajectory = read_passport_trajectory(
            run_id, panel_subject,
            checkpoint_id=artifact.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        assert trajectory["stage"] == "panel_entry"
        assert trajectory["universe"] == "panel"
        assert trajectory["context"]["entity_id"] == "entity"
        panel_record = trajectory["snapshots"]["panel"]
        assert panel_record["content_status"] == "present"
        assert panel_record["stage"] == "panel_entry"
        assert panel_record["universe"] == "panel"

        # Однорядный контур (другой run) — фильтры не смешивают.
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        _capture_new(client, "modeling_entry", 5.0)
        single_session = get_session_store().get(_client_session_id(client))
        single_run = single_session.run_id
        single_subject = _client_subject(client)

        panel_all = list_passport_checkpoints(
            run_id, panel_subject, session_id=_client_session_id(client),
        )
        assert [i["stage"] for i in panel_all] == ["panel_entry"]
        assert all(i["universe"] == "panel" for i in panel_all)
        single_all = list_passport_checkpoints(
            single_run, single_subject, session_id=_client_session_id(client),
        )
        assert [i["stage"] for i in single_all] == ["modeling_entry"]
        assert all(i["universe"] == "single" for i in single_all)
        assert list_passport_checkpoints(
            run_id, panel_subject, universe="single", session_id=_client_session_id(client),
        ) == []
        assert list_passport_checkpoints(
            single_run, single_subject, universe="panel", session_id=_client_session_id(client),
        ) == []
        # snapshot-список панельного run: только панельная вселенная.
        panel_snaps = None
        from apps.api.passport_history import list_passport_snapshots

        panel_snaps = list_passport_snapshots(
            run_id, panel_subject, session_id=_client_session_id(client),
        )
        assert all(i["universe"] == "panel" for i in panel_snaps)
        assert list_passport_snapshots(
            run_id, panel_subject, universe="single", session_id=_client_session_id(client),
        ) == []


# ══════════════════════════════════════════════════════════════════════
# A-блок 3: пикировщики (§10), доступ (AC18-дух), read-only
# ══════════════════════════════════════════════════════════════════════


class TestPickerAccessOracles:
    def test_a11_picker_sorted_by_confirmed_at_fields_full(self, client):
        """A11/§10: пикировщик чекпоинтов — сортировка по confirmed_at
        (не по id); полный состав полей; fingerprint пика = fingerprint
        ПОДТВЕРЖДЁННОГО снимка (не другого этапа); created_at —
        актуальность (provenance + время промоушена). Третий чекпоинт
        сеется контролируемо (id лексически первый, confirmed_at
        ПОЗЖЕ всех) — сортировка по id детерминированно убивается."""
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import list_passport_checkpoints
        from apps.api.visual_artifacts import register_passport_checkpoint

        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _capture_new(client, "validation", 3.0)
        _capture_new(client, "exit", 4.0)
        first = _capture_new(client, "modeling_entry", 5.0)
        _capture_new(client, "exit", 2.5)
        second = _capture(client, "modeling_entry")
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)
        session_id = _client_session_id(client)

        # Контролируемый третий чекпоинт: id "0p5cert-late" (лексически
        # ПЕРВЫЙ: '0' < hex-цифр uuid), confirmed_at ПОЗЖЕ обоих
        # пайплайных -- сортировка по id детерминированно расходится с
        # сортировкой по confirmed_at (дефект первого черновика оракула:
        # id "p5cert-aaa" начинался с 'p' > hex и сортировки совпадали;
        # исправлен честно до финала кампании).
        confirmed_rs = None
        from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
        from apps.api.report_snapshot import get_snapshot_registry

        confirmed_rs = get_snapshot_registry().find_idempotent(
            run_id, f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{second['snapshot_id']}"
        )
        assert confirmed_rs is not None
        third_payload = {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id("0p5cert-late"),
            "stage": "modeling_entry",
            "confirmed_at": "2027-01-01T00:00:00+00:00",
            "confirmed_at_reason": None,
            "snapshot_ref": confirmed_rs.snapshot_id,
            "previous_snapshot_ref": None,
            "flags": {"created": False, "reused": True, "unchanged": False},
            "stage_refs": {
                "start": _checkpoint_payload(
                    _durable_checkpoint(run_id, second["checkpoint_id"])
                )["stage_refs"]["start"],
                "validation": _checkpoint_payload(
                    _durable_checkpoint(run_id, second["checkpoint_id"])
                )["stage_refs"]["validation"],
                "exit": _checkpoint_payload(
                    _durable_checkpoint(run_id, second["checkpoint_id"])
                )["stage_refs"]["exit"],
            },
            "context": {
                "run_id": run_id,
                "context_id": "ctx-p5cert-late",
                "data_revision": 5,
                "target_column": "value",
                "entity_id": None,
            },
            "provenance": {"source": "session_replay"},
        }
        third_art = register_passport_checkpoint(
            run_id, subject, payload=third_payload, session_id=session_id,
        )
        assert third_art is not None

        items = list_passport_checkpoints(
            run_id, subject, session_id=session_id,
        )
        assert len(items) == 3
        times = [i["confirmed_at"] for i in items]
        assert times == sorted(times)
        # Детерминированный убийца сортировки по id: лексически первый
        # id обязан быть ПОСЛЕДНИМ по confirmed_at.
        third_id = third_art.refs["checkpoint_id"]
        assert items[-1]["checkpoint_id"] == third_id
        assert items[0]["checkpoint_id"] != third_id
        assert items[-1]["confirmed_at"] == "2027-01-01T00:00:00+00:00"
        for item in items:
            assert item["schema_version"] == "pgv.passport_history/1"
            assert item["checkpoint_id"].startswith("pck-")
            assert item["artifact_id"]
            assert item["stage"] == "modeling_entry"
            assert item["universe"] == "single"
            assert item["context"]["run_id"] == run_id
            assert item["context"]["target_column"] == "value"
            assert item["confirmed_at"]
            assert item["provenance"]["source"] in {"producer_capture", "session_replay"}
            assert item["integrity_status"] == "ok"
            assert item["integrity_reason"] is None
            assert item["created_at"]
            # XOR: fingerprint со значением -- reason None.
            assert item["fingerprint"]
            assert item["fingerprint_reason"] is None
        # fingerprint каждого пика = fingerprint ЕГО подтверждения.
        by_id = {i["checkpoint_id"]: i for i in items}
        pipe_first = _durable_checkpoint(run_id, first["checkpoint_id"]).refs["checkpoint_id"]
        pipe_second = _durable_checkpoint(run_id, second["checkpoint_id"]).refs["checkpoint_id"]
        assert by_id[pipe_first]["fingerprint"] == first["fingerprint"]
        assert by_id[pipe_second]["fingerprint"] == second["fingerprint"]
        assert by_id[third_art.refs["checkpoint_id"]]["fingerprint"] == second["fingerprint"]
        # snapshot_ref/stage_refs перенесены из payload.
        assert all(i["snapshot_ref"] for i in items)
        assert all(i["stage_refs"] for i in items)

    def test_a12_corrupt_checkpoint_payload_honest_degradation(self, client):
        """A12/AC12: битый CHECKPOINT payload — траектория и пикер
        деградируют честно: integrity_status=corrupt, confirmed_at None +
        integrity_failure (не выдуманы), snapshots пуст + gap,
        universe пикера при этом остаётся доказуемым из refs
        (registry-факт)."""
        from apps.api.artifact_store import get_artifact_object_store
        from apps.api.passport_history import (
            list_passport_checkpoints,
            read_passport_trajectory,
        )

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        checkpoint = None
        for artifact in get_artifact_object_store() and []:  # pragma: no cover
            pass
        from apps.api.artifact_store import get_artifact_registry

        for artifact in get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint"):
            checkpoint = artifact
        assert checkpoint is not None
        path = get_artifact_object_store().path_for_key(checkpoint.storage_key)
        path.write_bytes(b'{"broken": 1}')

        trajectory = read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=checkpoint.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        )
        assert trajectory["integrity_status"] == "corrupt"
        assert trajectory["integrity_reason"]
        assert trajectory["confirmed_at"] is None
        assert trajectory["confirmed_at_reason"] == "integrity_failure"
        assert trajectory["snapshots"] == {}
        assert trajectory["gaps"] and trajectory["gaps"][0]["reason"] == "integrity_failure"

        picker = list_passport_checkpoints(
            run_id, _client_subject(client), session_id=_client_session_id(client),
        )
        target = [
            i for i in picker if i["checkpoint_id"] == checkpoint.refs["checkpoint_id"]
        ][0]
        assert target["integrity_status"] == "corrupt"
        assert target["confirmed_at"] is None
        assert target["confirmed_at_reason"] == "integrity_failure"
        assert target["flags"] is None
        # universe -- доказуемый refs-факт, не теряется.
        assert target["universe"] == "single"

    def test_a13_reader_is_read_only_full_cycle(self, client):
        """A13/AC06-дух: полный цикл чтений (snapshot/trajectory/списки)
        не меняет артефакты/записи/пины; идемпотентно по счётчикам."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_history import (
            list_passport_checkpoints,
            list_passport_snapshots,
            read_passport_snapshot,
            read_passport_trajectory,
        )
        from apps.api.report_snapshot import get_snapshot_registry

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)
        session_id = _client_session_id(client)

        checkpoint = _durable_checkpoint(
            run_id, _capture(client, "modeling_entry")["checkpoint_id"]
        ) if False else None
        ck = None
        for artifact in get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint"):
            ck = artifact
        arts = len(get_artifact_registry().list_artifacts(run_id))
        recs = len(get_snapshot_registry().list_records(run_id))
        pins = len(get_artifact_registry().list_pins(run_id))

        for _ in range(2):
            read_passport_trajectory(
                run_id, subject, checkpoint_id=ck.refs["checkpoint_id"], session_id=session_id,
            )
            read_passport_snapshot(
                run_id, subject,
                snapshot_ref=_passport_rs_records(run_id)[0].snapshot_id, session_id=session_id,
            )
            list_passport_checkpoints(run_id, subject, session_id=session_id)
            list_passport_snapshots(run_id, subject, session_id=session_id)

        assert len(get_artifact_registry().list_artifacts(run_id)) == arts
        assert len(get_snapshot_registry().list_records(run_id)) == recs
        assert len(get_artifact_registry().list_pins(run_id)) == pins

    def test_a14_access_uniform_denial(self, client):
        """A14/AC18-дух: чужой субъект, отсутствующий run и anonymous —
        единый PassportHistoryAccessDenied без дисклоужения."""
        from apps.api.identity import SubjectRef
        from apps.api.passport_history import (
            PassportHistoryAccessDenied,
            list_passport_checkpoints,
            list_passport_snapshots,
            read_passport_snapshot,
            read_passport_trajectory,
        )

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        ref = _passport_rs_records(run_id)[0].snapshot_id
        ck = None
        from apps.api.artifact_store import get_artifact_registry

        for artifact in get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint"):
            ck = artifact

        with pytest.raises(PassportHistoryAccessDenied):
            read_passport_snapshot(
                run_id, _foreign_subject(), snapshot_ref=ref, session_id="p5cert-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            read_passport_trajectory(
                run_id, _foreign_subject(),
                checkpoint_id=ck.refs["checkpoint_id"] if ck else "pck-x",
                session_id="p5cert-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            list_passport_checkpoints(
                run_id, _foreign_subject(), session_id="p5cert-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            list_passport_snapshots(
                run_id, _foreign_subject(), session_id="p5cert-foreign-session",
            )
        with pytest.raises(PassportHistoryAccessDenied):
            list_passport_checkpoints(
                "RUN-P5CERTABSENT", _client_subject(client), session_id=_client_session_id(client),
            )
        with pytest.raises(PassportHistoryAccessDenied):
            read_passport_snapshot(
                run_id, SubjectRef.anonymous(), snapshot_ref=ref,
            )

    def test_a15_checkpoint_lookup_scoped_to_run(self, client):
        """A15: чекпоинт ЧУЖОГО run не читается из своего (scoping по
        run; uniform None без фабкации)."""
        from apps.api.passport_history import read_passport_trajectory

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id

        with TestClient(app) as client2:
            _upload(client2)
            _select_series(client2)
            _capture(client2, "start")
            _capture_new(client2, "validation", 1.0)
            _capture_new(client2, "exit", 2.0)
            _capture_new(client2, "modeling_entry", 3.0)
            session2 = get_session_store().get(_client_session_id(client2))
            run2 = session2.run_id
        foreign_ck = _durable_checkpoint(run2, "x")
        foreign_ck = None
        from apps.api.artifact_store import get_artifact_registry

        for artifact in get_artifact_registry().list_artifacts(run2, kind="passport_checkpoint"):
            foreign_ck = artifact
        assert foreign_ck is not None
        assert read_passport_trajectory(
            run_id, _client_subject(client),
            checkpoint_id=foreign_ck.refs["checkpoint_id"],
            session_id=_client_session_id(client),
        ) is None

    def test_a16_snapshot_list_scope_and_order(self, client):
        """A16/§10: список snapshot-записей — ТОЛЬКО паспортные rs
        (D01/документные не утекают), сортировка по captured_at, полный
        поток даёт 4 записи без дублей."""
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.report_snapshot import ReportSnapshot, get_snapshot_registry, new_snapshot_id

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_id = session.run_id
        subject = _client_subject(client)

        # Сеем не-паспортную D01-запись -- в список попасть не должна.
        doc = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=run_id,
            context_id=None,
            data_revision=None,
            data_ref=None,
            data_digest=None,
            source_cutoff={},
            captured_at="2026-10-29T09:00:00+00:00",
            knowledge_version=None,
            classification="private",
            redaction_profile="owner-v1",
            completeness={"status": "partial", "missing_refs": [], "missing_mandatory": []},
            reproducibility={"status": "limited", "reasons": ["p5cert-seed"]},
            sections=[],
            dependencies=[],
            approval=None,
            kinds=["D01"],
            idempotency_key="p5cert-doc:2",
            request_fingerprint="2" * 64,
            created_by=subject.subject_id,
        )
        get_snapshot_registry().register_snapshot(doc, [])

        items = list_passport_snapshots(
            run_id, subject, session_id=_client_session_id(client),
        )
        assert len(items) == 4
        captured = [i["captured_at"] for i in items]
        assert captured == sorted(captured)
        refs = {i["snapshot_ref"] for i in items}
        assert len(refs) == 4
        assert all(i["content_status"] == "present" for i in items)
        stages = sorted(i["stage"] for i in items)
        assert stages == ["exit", "modeling_entry", "start", "validation"]


class TestCrossRunDependencyOracle:
    def test_a17_dependency_resolution_respects_run_scope(self, client):
        """A17: rs-запись с зависимостью artifact:{id} на ЧУЖЕЙ
        (другой run) паспортный артефакт — dependency-ветка обязана
        отвергнуть чужой артефакт и резолвить ПО producer-ключу СВОЕГО
        run (порядок промоушена C03/PGV-04). Контент чужого run не
        выдаётся; свой контент читается честно."""
        from apps.api.artifact_promotion import PromotionService
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_history import read_passport_snapshot
        from apps.api.report_snapshot import (
            ReportSnapshot,
            get_snapshot_registry,
            new_snapshot_id,
        )

        _full_pipeline(client)
        session = get_session_store().get(_client_session_id(client))
        run_a = session.run_id
        subject = _client_subject(client)
        session_id = _client_session_id(client)

        # Свой паспортный артефакт run A под producer_key
        # passport:snap-p5cert-cross (fallback-цель).
        own_payload = {
            "kind": "passport",
            "stage": "start",
            "passport": {"basic_stats": {"n": 11}, "own_marker": "run-a"},
            "snapshot_id": "snap-p5cert-cross",
            "fingerprint": "9" * 64,
            "target_column": "value",
            "date_column": "date",
            "captured_at": "2026-10-29T11:00:00+00:00",
        }
        PromotionService.create_default()._persist(
            run_id=run_a,
            subject=subject,
            kind="passport",
            producer_key="passport:snap-p5cert-cross",
            payload=own_payload,
            dependencies=[],
            refs={"snapshot_id": "snap-p5cert-cross", "stage": "start"},
            context_id=None,
            data_revision=None,
            source_bytes_sha256=None,
        )

        # Чужой run B с паспортным артефактом ТОГО ЖЕ payload.snapshot_id
        # (подмена контента проверяется именно совпадением идентичности).
        with TestClient(app) as client2:
            _upload(client2)
            _select_series(client2)
            _capture(client2, "start")
            _capture_new(client2, "validation", 1.0)
            _capture_new(client2, "exit", 2.0)
            _capture_new(client2, "modeling_entry", 3.0)
            session2 = get_session_store().get(_client_session_id(client2))
            run_b = session2.run_id
        foreign_payload = {
            "kind": "passport",
            "stage": "start",
            "passport": {"basic_stats": {"n": 99}, "foreign_marker": "run-b"},
            "snapshot_id": "snap-p5cert-cross",
            "fingerprint": "8" * 64,
            "target_column": "value",
            "date_column": "date",
            "captured_at": "2026-10-29T12:00:00+00:00",
        }
        foreign_art = PromotionService.create_default()._persist(
            run_id=run_b,
            subject=_foreign_subject(),
            kind="passport",
            producer_key="passport:snap-p5cert-cross",
            payload=foreign_payload,
            dependencies=[],
            refs={"snapshot_id": "snap-p5cert-cross", "stage": "start"},
            context_id=None,
            data_revision=None,
            source_bytes_sha256=None,
        )
        assert foreign_art is not None

        # rs-запись в run A с ЗАВИСИМОСТЬЮ на чужой артефакт (тампред):
        # честная резолюция -- отвергнуть чужой артефакт по run-принадлеж
        # ности и найти СВОЙ по producer-ключу.
        record = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=run_a,
            context_id=None,
            data_revision=None,
            data_ref=None,
            data_digest=None,
            source_cutoff={},
            captured_at="2026-10-29T13:00:00+00:00",
            knowledge_version=None,
            classification="private",
            redaction_profile="owner-v1",
            completeness={"status": "partial", "missing_refs": [], "missing_mandatory": []},
            reproducibility={"status": "limited", "reasons": ["p5cert-seed"]},
            sections=[],
            dependencies=[f"artifact:{foreign_art.artifact_id}"],
            approval=None,
            kinds=["D02"],
            idempotency_key="pgv-passport:snap-p5cert-cross",
            request_fingerprint="3" * 64,
            created_by=subject.subject_id,
        )
        get_snapshot_registry().register_snapshot(record, [])

        item = read_passport_snapshot(
            run_a, subject, snapshot_ref=record.snapshot_id, session_id=session_id,
        )
        assert item is not None
        assert item["content_status"] == "present", (
            f"свой контент не резолвлен: {item['content_status']}/"
            f"{item['content_gap_reason']}"
        )
        # Контент -- ИМЕННО своего run (fallback по producer-ключу), не
        # чужого артефакта из зависимости.
        assert item["artifact_id"] != foreign_art.artifact_id
        assert item["passport"].get("own_marker") == "run-a"
        assert "foreign_marker" not in item["passport"]
        assert item["fingerprint"] == "9" * 64
