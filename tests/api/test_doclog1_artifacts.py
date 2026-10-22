# tests/api/test_doclog1_artifacts.py
"""Task DOCLOG-1 (spec_documentation_logging.md §9.1, §9.3, §10.2, §16,
§19 строка DOCLOG-1, §20 AC04/AC05/AC06/AC08/AC09/AC13): устойчивые
артефакты -- Metadata/ObjectStore/schema/digests/staging/pins; адаптеры
паспортов, OOF, cards, forecasts.

Критерий завершения (§19): результаты доступны после TTL-сессии, pin
выдерживает checkpoint-pruning, panel types сохраняются.

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу (RUN-D1xxxxxx);
изоляция каждого теста -- паттерн test_doclog0_identity.py (свой
tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик). Авторизация -- та
же решающая таблица DOCLOG-0 (identity.authorize_run_access): знание
artifact_id НЕ является правом (T7). NaN не маскируется (AC12-дух);
staging-протокол fail-closed на расхождение хэша (AC08/T8); pin
защищает снимок чекпоинта от keeper «последних пяти» (AC04/T11).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import (
    DEFAULT_TENANT_ID,
    SubjectRef,
    authorize_run_access,
)
from apps.api.research_runs import ResearchRun
from apps.api.session_store import SESSION_COOKIE_NAME, AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog0_identity.py) ────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store
    from apps.api.session_store import reset_session_store_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_session_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


ADMIN_KEY = "d1-admin-test-key"


def _admin_headers() -> dict[str, str]:
    return {"x-api-key": ADMIN_KEY}


@pytest.fixture()
def admin_client(client, monkeypatch):
    monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:pro")
    return client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ─────────────────

RUN_ID = "RUN-D1A00001"


def _seed_session(session_id: str = "d1-seed-session") -> AnalysisSession:
    """Сессия-источник фактов (без загрузки данных -- адаптеры читают
    только структуры артефактов; /health-пути не трогаются)."""
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def session_store_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_bound_run(run_id: str = RUN_ID, session_id: str = "d1-seed-session") -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d1" * 16,
        dataset_name="durable-artifacts-seed",
        target_column="value",
        created_at=session_store_now(),
        last_active_at=session_store_now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = "d1-seed-session") -> SubjectRef:
    """Субъект-владелец (стабильный суррогат; паритет session_surrogate
    контракта DOCLOG-0)."""
    return SubjectRef.from_session(session_id)


def _foreign_subject() -> SubjectRef:
    return SubjectRef.from_session("d1-foreign-session")


def _seed_passport(session: AnalysisSession, stage: str = "modeling_entry"):
    session.append_passport_snapshot(
        stage,
        {"rows": 120, "columns": 4, "target": "value", "stage": stage},
        "d1" * 16,
    )


def _seed_panel_passport(session: AnalysisSession):
    session.append_panel_passport_snapshot(
        passport={"rows": 240, "entities": 6, "target": "value"},
        fingerprint="e1" * 16,
    )


def _seed_backtest(session: AnalysisSession, model_id: str = "arima") -> dict:
    entry = {
        "run_id": "bt-d1-0001",
        "cohort_id": "cohort-d1",
        "model_id": model_id,
        "input_kind": "univariate",
        "objective": "level_forecast",
        "params": {"order": [1, 0, 1]},
        "parameter_signature": "sig-d1-params",
        "oof_signature": "sig-d1-oof",
        "oof_predictions": [
            {"fold": 0, "date": "2026-01-01", "y_true": 10.0, "y_pred": 9.7},
            {"fold": 1, "date": "2026-01-02", "y_true": 11.0, "y_pred": 10.9},
        ],
        "metrics": {"mae": 0.2, "rmse": 0.3},
        "folds": [{"fold": 0}, {"fold": 1}],
        "warnings": [],
        "execution_contract": {
            "input_kind": "univariate",
            "runtime_available": True,
            "library_versions": {"statsmodels": "0.14"},
            "model_version": "v1",
        },
        "cohort_contract": {"objective": "level_forecast", "input_kind": "univariate"},
    }
    session.modeling_artifacts.setdefault("backtests", {})[model_id] = entry
    return entry


def _seed_panel_backtest(session: AnalysisSession, model_id: str = "panel_fe") -> dict:
    entry = {
        "run_id": "bt-d1-panel",
        "cohort_id": "cohort-d1-panel",
        "model_id": model_id,
        "objective": "level_forecast",
        "params": {"alpha": 0.1},
        "parameter_signature": "sig-d1-panel-params",
        "oof_signature": "sig-d1-panel-oof",
        "oof_predictions": [
            {"fold": 0, "entity": "RU", "date": "2026-01-01", "y_true": 5.0, "y_pred": 4.8},
            {"fold": 0, "entity": "KZ", "date": "2026-01-01", "y_true": 3.0, "y_pred": 3.1},
        ],
        "metrics": {"mae": 0.15},
        "folds": [{"fold": 0}],
        "warnings": [],
        "execution_contract": {
            "input_kind": "panel_entity",
            "runtime_available": True,
            "library_versions": {"linearmodels": "6.1"},
            "model_version": "v1",
        },
        "cohort_contract": {
            "panel_entity": True,
            "input_kind": "panel_entity",
            "n_entities": 6,
            "balance": "unbalanced",
        },
        "panel": {
            "n_entities": 6,
            "balance": "unbalanced",
            "n_dates_common": 24,
            "target_column": "value",
            "entity_columns_order": ["RU", "KZ", "BY", "AM", "AZ", "GE"],
            "entity_metrics": {"RU": {"mae": 0.1}, "KZ": {"mae": 0.2}},
            "pooled_metrics": {"mae": 0.15},
            "pooled_mase_scale": 1.25,
            "pooled_rmsse_scale": 1.4,
            "pooled_mase_scale_method": "median of per-entity train-only scales",
        },
    }
    session.modeling_artifacts.setdefault("backtests", {})[model_id] = entry
    return entry


def _seed_model_card(session: AnalysisSession, card_id: str = "card-d1-1") -> dict:
    result = {
        "card_id": card_id,
        "card": {
            "model_info": {
                "model_id": "arima",
                "family": "classical",
                "applicability_level": "core",
                "selection_kind": "single",
                "ensemble_members": [],
                "version": "v1",
                "library_versions": {"statsmodels": "0.14"},
            },
            "data_summary": {
                "n_observations": 120,
                "target_column": "value",
                "date_column": "date",
                "fingerprint": "d1" * 16,
                "source_checkpoint": "cp-d1-entry",
            },
            "hyperparameters": {"order": [1, 0, 1]},
            "training": {"horizon": 12, "folds": 3},
            "performance": {"oof_predictions": [{"fold": 0, "y_pred": 9.7}]},
            "traceability": {
                "checkpoint_id": "cp-d1-entry",
                "comparison_id": "cmp-d1",
                "independent_holdout": False,
            },
            "notes": "seed card",
            "created_at": session_store_now(),
        },
    }
    session.modeling_artifacts.setdefault("model_cards", {})[card_id] = result
    return result


def _seed_forecast(session: AnalysisSession, forecast_id: str = "fc-d1-1") -> dict:
    run = {
        "forecast_id": forecast_id,
        "model_card_id": "card-d1-1",
        "model_id": "arima",
        "model_name": "ARIMA(1,0,1)",
        "generated_at": session_store_now(),
        "horizon": 6,
        "alpha": 0.05,
        "alpha_effective": 0.05,
        "alpha_source": "request",
        "ci_method": "residual_normal",
        "points": [
            {"date": "2026-02-01", "point": 12.1, "lower": 11.5, "upper": 12.7},
            {"date": "2026-02-02", "point": 12.3, "lower": 11.6, "upper": 13.0},
        ],
        "history": {"labels": ["2026-01-01"], "values": [10.0], "source_column": "value"},
        "expected_accuracy": {"mae": 0.2},
        "prediction_interval_coverage": None,
        "warnings": ["интервалы номинальные"],
        "trace_events": [],
        "lineage": {
            "fingerprint": "d1" * 16,
            "checkpoint_id": "cp-d1-entry",
            "cohort_id": "cohort-d1",
            "preprocessing_signature": "sig-prep",
            "params": {"order": [1, 0, 1]},
            "n_history": 1,
            "interval_provenance": "residual_normal",
        },
        "sensitivity": None,
    }
    session.modeling_artifacts.setdefault("forecasts", {})[forecast_id] = run
    return run


# ══════════════════════════════════════════════════════════════════════
# 1. Digest-схемы (§9.3: три типа не взаимозаменяемы)
# ══════════════════════════════════════════════════════════════════════


class TestDigestSchemas:
    def test_canonical_json_is_deterministic(self):
        from apps.api.artifact_store import canonical_json_bytes

        payload = {"b": 2, "a": [1, {"c": "кириллица"}]}
        first = canonical_json_bytes(payload)
        second = canonical_json_bytes({"a": [1, {"c": "кириллица"}], "b": 2})
        assert first == second
        assert json.loads(first.decode("utf-8")) == payload

    def test_canonical_json_rejects_nan(self):
        from apps.api.artifact_store import canonical_json_bytes, SerializationError

        with pytest.raises(SerializationError):
            canonical_json_bytes({"metric": float("nan")})

    def test_data_digest_carries_algorithm_and_value(self):
        from apps.api.artifact_store import data_digest

        digest = data_digest(b"csv-bytes")
        assert digest["algorithm"] == "cisstat-data-v1"
        assert digest["value"] == hashlib.sha256(b"csv-bytes").hexdigest()

    def test_data_digest_is_stable_and_distinct_from_content_hash(self):
        from apps.api.artifact_store import artifact_content_sha256, data_digest

        assert data_digest(b"x") == data_digest(b"x")
        # §9.3: data_digest и artifact_content_sha256 -- РАЗНЫЕ типы:
        # одно значение, разные поля/смысл; поля не объявляются взаимозаменяемыми.
        d = data_digest(b"x")
        c = artifact_content_sha256(b"x")
        assert d["value"] == c == hashlib.sha256(b"x").hexdigest()
        assert set(d.keys()) == {"algorithm", "value"}

    def test_source_bytes_digest_is_reference_only(self):
        """source_bytes_sha256 НЕ вычисляется адаптером -- переносится
        ссылкой (существующий fingerprint файла); функция только
        валидирует форму (64 hex)."""
        from apps.api.artifact_store import is_valid_source_ref

        assert is_valid_source_ref("d1" * 32)
        assert not is_valid_source_ref("")
        assert not is_valid_source_ref(None)


# ══════════════════════════════════════════════════════════════════════
# 2. ObjectStore: staging → verify → commit → read (§10.2 п.6, AC08)
# ══════════════════════════════════════════════════════════════════════


class TestObjectStoreStaging:
    def _store(self):
        from apps.api.artifact_store import get_artifact_object_store

        return get_artifact_object_store()

    def test_stage_writes_staging_and_returns_digests(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        assert staged.sha256 == hashlib.sha256(b"payload-bytes").hexdigest()
        assert staged.size_bytes == len(b"payload-bytes")
        assert staged.media_type == "application/json"
        assert staged.path.exists()

    def test_commit_verifies_and_places_content_object(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        key = store.commit_staged(staged)
        object_path = store.path_for_key(key)
        assert object_path.exists()
        assert object_path.read_bytes() == b"payload-bytes"
        # content-addressed: ключ производит сервер из хэша (T9) --
        # traversal из имён клиента невозможен по построению.
        assert ".." not in str(key)
        assert hashlib.sha256(b"payload-bytes").hexdigest() in key

    def test_commit_detects_corrupted_staging(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        staged.path.write_bytes(b"TAMPERED-BYTES")
        with pytest.raises(Exception) as excinfo:
            store.commit_staged(staged)
        from apps.api.artifact_store import StagingVerificationError

        assert isinstance(excinfo.value, StagingVerificationError)
        # fail-closed: битый staging удалён, объект не появился.
        assert not staged.path.exists()
        assert not store.path_for_key(
            "aa/" + hashlib.sha256(b"payload-bytes").hexdigest()
        ).exists()

    def test_read_back_verifies_integrity(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        key = store.commit_staged(staged)
        assert store.read_bytes(key) == b"payload-bytes"

    def test_read_detects_tampered_object(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        key = store.commit_staged(staged)
        store.path_for_key(key).write_bytes(b"CORRUPTED")
        from apps.api.artifact_store import ArtifactIntegrityError

        with pytest.raises(ArtifactIntegrityError):
            store.read_bytes(key)

    def test_size_mismatch_fails_commit(self):
        store = self._store()
        staged = store.stage_bytes(b"payload-bytes", "application/json")
        staged.size_bytes = 999  # metadata расходится с файлом
        from apps.api.artifact_store import StagingVerificationError

        with pytest.raises(StagingVerificationError):
            store.commit_staged(staged)

    def test_sweep_removes_only_stale_orphans(self):
        store = self._store()
        orphan = store.stage_bytes(b"orphan", "application/json")
        fresh = store.stage_bytes(b"fresh", "application/json")
        committed = store.commit_staged(store.stage_bytes(b"committed", "application/json"))
        # осиротевший staging «старше» grace (крэш до коммита, прошло 2ч)
        old = time.time() - 7200
        os.utime(orphan.path, (old, old))
        removed = store.sweep_orphan_staging(grace_seconds=3600)
        assert orphan.staging_id in removed
        assert fresh.path.exists()
        assert store.path_for_key(committed).exists()

    def test_sweep_respects_grace_period(self):
        store = self._store()
        orphan = store.stage_bytes(b"orphan", "application/json")
        removed = store.sweep_orphan_staging(grace_seconds=3600)
        assert orphan.staging_id not in removed
        assert orphan.path.exists()

    def test_object_root_under_data_dir(self):
        store = self._store()
        root = Path(store.root)
        assert root.name == "artifacts"
        # root = CISSTAT_DATA_DIR/artifacts (паритет DatasetFileStore)
        assert root.parent.name == "data"


# ══════════════════════════════════════════════════════════════════════
# 3. Реестр метаданных (паритет Memory/Postgres-каталог)
# ══════════════════════════════════════════════════════════════════════


class TestArtifactRegistry:
    def _artifact(self, run_id: str = RUN_ID, producer_key: str = "passport:snap-1"):
        from apps.api.artifact_store import ResultArtifact

        return ResultArtifact(
            artifact_id="art-" + "a" * 32,
            run_id=run_id,
            kind="passport",
            producer_key=producer_key,
            media_type="application/json",
            size_bytes=10,
            payload_sha256=hashlib.sha256(b"x").hexdigest(),
            storage_key="ab/" + "b" * 64,
            context_id="ctx-d1",
            data_revision=7,
            input_kind="univariate",
            panel=None,
            dependencies=["cp-d1-entry"],
            refs={"snapshot_id": "snap-1"},
            created_by="subj-" + "1" * 16,
        )

    def test_register_and_get_round_trip(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        artifact = self._artifact()
        registry.register_artifact(artifact)
        loaded = registry.get_artifact(artifact.artifact_id)
        assert loaded is not None
        assert loaded.run_id == RUN_ID
        assert loaded.kind == "passport"
        assert loaded.context_id == "ctx-d1"
        assert loaded.data_revision == 7
        assert loaded.dependencies == ["cp-d1-entry"]
        # копия, не живой объект (R1 контракта store)
        assert loaded is not artifact

    def test_idempotent_by_producer_key(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        first = self._artifact()
        registry.register_artifact(first)
        duplicate = self._artifact(producer_key="passport:snap-1")
        duplicate.artifact_id = "art-" + "b" * 32
        stored, created = registry.register_artifact(duplicate)
        assert created is False
        assert stored.artifact_id == first.artifact_id
        assert len(registry.list_artifacts(RUN_ID)) == 1

    def test_same_producer_key_other_content_conflicts(self):
        from apps.api.artifact_store import ArtifactConflictError, get_artifact_registry

        registry = get_artifact_registry()
        registry.register_artifact(self._artifact())
        other = self._artifact(producer_key="passport:snap-1")
        other.payload_sha256 = hashlib.sha256(b"OTHER").hexdigest()
        with pytest.raises(ArtifactConflictError):
            registry.register_artifact(other)

    def test_list_filters_by_run_and_kind(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.register_artifact(self._artifact())
        forecast = self._artifact(producer_key="forecast:fc-1")
        forecast.kind = "forecast"
        forecast.artifact_id = "art-" + "c" * 32
        registry.register_artifact(forecast)
        other_run = self._artifact(run_id="RUN-D1A00002", producer_key="passport:snap-2")
        other_run.artifact_id = "art-" + "d" * 32
        registry.register_artifact(other_run)
        assert len(registry.list_artifacts(RUN_ID)) == 2
        assert len(registry.list_artifacts(RUN_ID, kind="forecast")) == 1
        assert registry.list_artifacts("RUN-D1ZZZZZZ") == []

    def test_panel_fields_round_trip(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        artifact = self._artifact(producer_key="backtest:bt-panel")
        artifact.input_kind = "panel_entity"
        artifact.panel = {"n_entities": 6, "balance": "unbalanced"}
        registry.register_artifact(artifact)
        loaded = registry.get_artifact(artifact.artifact_id)
        assert loaded.input_kind == "panel_entity"
        assert loaded.panel == {"n_entities": 6, "balance": "unbalanced"}

    def test_honest_absence_of_context_metadata(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        artifact = self._artifact()
        artifact.context_id = None
        artifact.data_revision = None
        registry.register_artifact(artifact)
        loaded = registry.get_artifact(artifact.artifact_id)
        assert loaded.context_id is None
        assert loaded.data_revision is None

    def test_migration_catalog_contains_0007(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        joined = "\n".join(MIGRATION_STATEMENTS)
        assert "research_artifacts" in joined
        assert "research_artifact_pins" in joined
        assert any(name == "0007_doclog1_artifacts.sql" for name, _ in MIGRATION_FILES)

    def test_migration_file_parity_with_catalog(self):
        """Паритет источников DDL (паттерн DOCLOG-0/AUDIT-6A): файл
        migrations/0007_*.sql -- дубль каталога (нормализация пробелов)."""
        from apps.api.research_runs import MIGRATION_FILES

        def _norm(value: str) -> str:
            return " ".join(value.split())

        for name, statements in MIGRATION_FILES:
            if name != "0007_doclog1_artifacts.sql":
                continue
            text = (
                Path(__file__).resolve().parents[2]
                / "apps/api/migrations"
                / name
            ).read_text(encoding="utf-8")
            normalized = _norm(text)
            for statement in statements:
                assert _norm(statement) in normalized, statement[:60]

    def test_unique_constraints_in_ddl(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0007

        joined = "\n".join(MIGRATION_STATEMENTS_0007)
        assert "UNIQUE (run_id, producer_key)" in joined
        assert "UNIQUE (run_id, ref_kind, ref_id)" in joined


# ══════════════════════════════════════════════════════════════════════
# 4. Pins (§16: pin защищает зависимости; AC04/T11)
# ══════════════════════════════════════════════════════════════════════


class TestPins:
    def test_pin_is_idempotent(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.pin_ref(RUN_ID, "checkpoint", "cp-1", reason="artifact:art-1", created_by="subj-x")
        registry.pin_ref(RUN_ID, "checkpoint", "cp-1", reason="artifact:art-1", created_by="subj-x")
        pins = registry.list_pins(RUN_ID, ref_kind="checkpoint")
        assert len(pins) == 1
        assert pins[0].ref_id == "cp-1"
        assert pins[0].reason == "artifact:art-1"

    def test_pin_round_trip_fields(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.pin_ref(RUN_ID, "artifact", "art-9", reason="card dependency", created_by="subj-y")
        pins = registry.list_pins(RUN_ID)
        assert pins[0].ref_kind == "artifact"
        assert pins[0].created_by == "subj-y"
        assert pins[0].created_at

    def test_unpin_removes_only_target(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.pin_ref(RUN_ID, "checkpoint", "cp-1", reason="r", created_by="s")
        registry.pin_ref(RUN_ID, "checkpoint", "cp-2", reason="r", created_by="s")
        assert registry.unpin_ref(RUN_ID, "checkpoint", "cp-1") is True
        assert registry.unpin_ref(RUN_ID, "checkpoint", "cp-1") is False
        assert [p.ref_id for p in registry.list_pins(RUN_ID)] == ["cp-2"]

    def test_pinned_checkpoint_ids(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.pin_ref(RUN_ID, "checkpoint", "cp-a", reason="r", created_by="s")
        registry.pin_ref(RUN_ID, "artifact", "art-a", reason="r", created_by="s")
        registry.pin_ref("RUN-D1A00009", "checkpoint", "cp-other", reason="r", created_by="s")
        assert registry.pinned_checkpoint_ids(RUN_ID) == {"cp-a"}

    def test_pins_scoped_by_run(self):
        from apps.api.artifact_store import get_artifact_registry

        registry = get_artifact_registry()
        registry.pin_ref(RUN_ID, "checkpoint", "cp-1", reason="r", created_by="s")
        assert registry.list_pins("RUN-D1A00003") == []


class TestPinProtectsCheckpointPruning:
    """AC04/T11: keeper «последних пяти» не удаляет pinned-снимок;
    сбой lookup пинов -- prune пропускается (fail-closed)."""

    def test_prune_keeps_pinned_snapshot(self, tmp_path):
        from apps.api.research_runs import get_dataset_file_store

        file_store = get_dataset_file_store()
        import pandas as pd

        for i in range(6):
            file_store.save_checkpoint_snapshot(
                RUN_ID, f"cp-{i}", pd.DataFrame({"v": [i]})
            )
        from apps.api.artifact_store import get_artifact_registry

        get_artifact_registry().pin_ref(
            RUN_ID, "checkpoint", "cp-0", reason="artifact:art-x", created_by="s"
        )
        # keeper: последние 5 (cp-1..cp-5) + pinned cp-0 -> ничего не удалено
        keep = [f"cp-{i}" for i in range(1, 6)]
        pinned = get_artifact_registry().pinned_checkpoint_ids(RUN_ID)
        keep = list(dict.fromkeys(list(keep) + sorted(pinned)))
        removed = file_store.prune_checkpoints(RUN_ID, keep=keep)
        assert removed == []
        assert (Path(file_store._checkpoints_dir(RUN_ID)) / "cp-0.csv").exists()

    def test_unpinned_sixth_is_removed_baseline(self):
        """Честно-зелёный пин прежнего контракта: без пинов 6-й снимок
        удаляется (поведение обязано остаться)."""
        from apps.api.research_runs import get_dataset_file_store

        file_store = get_dataset_file_store()
        import pandas as pd

        for i in range(6):
            file_store.save_checkpoint_snapshot(
                RUN_ID, f"cp-{i}", pd.DataFrame({"v": [i]})
            )
        removed = file_store.prune_checkpoints(
            RUN_ID, keep=[f"cp-{i}" for i in range(1, 6)]
        )
        assert removed == ["cp-0"]


# ══════════════════════════════════════════════════════════════════════
# 5. Промоушен: авторизация (R09/T7 -- одна объектная авторизация)
# ══════════════════════════════════════════════════════════════════════


class TestPromotionAuthorization:
    def _service(self):
        from apps.api.artifact_promotion import PromotionService

        return PromotionService.create_default()

    def test_owner_promotes_own_bound_run(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", stage="modeling_entry"
        )
        assert artifact.run_id == RUN_ID

    def test_foreign_subject_denied_write(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        from apps.api.artifact_promotion import PromotionDenied

        with pytest.raises(PromotionDenied) as excinfo:
            service.promote_passport(
                RUN_ID, _foreign_subject(), session,
                session_id="d1-foreign-session", stage="modeling_entry",
            )
        assert excinfo.value.decision.allowed is False
        assert excinfo.value.decision.reason == "foreign_session"

    def test_anonymous_denied(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        from apps.api.artifact_promotion import PromotionDenied

        with pytest.raises(PromotionDenied):
            service.promote_passport(
                RUN_ID, SubjectRef.anonymous(), session,
                session_id="d1-seed-session", stage="modeling_entry",
            )

    def test_creator_continuity_on_unresolved_run(self):
        from apps.api.research_runs import get_research_run_store

        legacy = ResearchRun(
            run_id="RUN-D1A00004",
            session_id="d1-seed-session",
            dataset_fingerprint="",
            dataset_name="legacy",
            target_column="value",
            created_at=session_store_now(),
            last_active_at=session_store_now(),
            status="active",
        )
        get_research_run_store().upsert_run(legacy)
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            "RUN-D1A00004", _owner_subject(), session,
            session_id="d1-seed-session", stage="modeling_entry",
        )
        assert artifact.run_id == "RUN-D1A00004"

    def test_read_gate_denies_foreign(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", stage="modeling_entry"
        )
        from apps.api.artifact_promotion import ArtifactAccessDenied

        with pytest.raises(ArtifactAccessDenied):
            service.get_artifact(artifact.artifact_id, _foreign_subject(), session_id="d1-foreign-session")

    def test_admin_reads_foreign_artifact(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", stage="modeling_entry"
        )
        admin = SubjectRef(
            subject_id="subj-admin", tenant_id=DEFAULT_TENANT_ID,
            via="api_key", role="admin",
        )
        loaded = service.get_artifact(artifact.artifact_id, admin, session_id="")
        assert loaded.artifact_id == artifact.artifact_id


# ══════════════════════════════════════════════════════════════════════
# 6. Адаптеры: паспорт / backtest / card / forecast / checkpoint data
# ══════════════════════════════════════════════════════════════════════


class TestPromotionAdapters:
    def _service(self):
        from apps.api.artifact_promotion import PromotionService

        return PromotionService.create_default()

    def _prepared(self):
        _seed_bound_run()
        session = _seed_session()
        return session, self._service()

    def test_passport_promotion_payload_and_digests(self):
        session, service = self._prepared()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        assert artifact.kind == "passport"
        assert artifact.producer_key.startswith("passport:")
        assert artifact.media_type == "application/json"
        payload = service.read_payload(artifact.artifact_id, _owner_subject(), session_id="d1-seed-session")
        assert payload["stage"] == "modeling_entry"
        assert payload["passport"]["rows"] == 120
        assert payload["fingerprint"] == "d1" * 16
        assert artifact.payload_sha256

    def test_passport_stage_start_promotion(self):
        session, service = self._prepared()
        _seed_passport(session, stage="start")
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", stage="start"
        )
        assert artifact.kind == "passport"

    def test_passport_without_snapshot_is_honest(self):
        session, service = self._prepared()
        from apps.api.artifact_promotion import PromotionUnavailable

        with pytest.raises(PromotionUnavailable):
            service.promote_passport(
                RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
                stage="modeling_entry",
            )

    def test_panel_passport_preserves_panel_semantics(self):
        session, service = self._prepared()
        _seed_panel_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", stage="panel_entry"
        )
        assert artifact.input_kind == "panel_entity"
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert payload["stage"] == "panel_entry"
        assert payload["passport"]["entities"] == 6

    def test_panel_passport_not_mixed_with_single_row(self):
        """R4: панельный контур изолирован от однорядного: promoter
        panel_entry читает ТОЛЬКО panel-список."""
        session, service = self._prepared()
        _seed_passport(session)  # однорядный modeling_entry
        from apps.api.artifact_promotion import PromotionUnavailable

        with pytest.raises(PromotionUnavailable):
            service.promote_passport(
                RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
                stage="panel_entry",
            )

    def test_backtest_promotion_preserves_oof(self):
        session, service = self._prepared()
        entry = _seed_backtest(session)
        artifact = service.promote_backtest(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", model_id="arima"
        )
        assert artifact.kind == "oof_backtest"
        assert artifact.producer_key == "backtest:bt-d1-0001"
        assert artifact.input_kind == "univariate"
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert payload["oof_predictions"] == entry["oof_predictions"]
        assert payload["parameter_signature"] == "sig-d1-params"

    def test_panel_backtest_preserves_per_entity_and_pooled_scale(self):
        """AC13-дух: per-entity OOF/метрики и pooled weighting/scale
        переносятся КАК ЕСТЬ, input_kind сохранён."""
        session, service = self._prepared()
        entry = _seed_panel_backtest(session)
        artifact = service.promote_backtest(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", model_id="panel_fe"
        )
        assert artifact.input_kind == "panel_entity"
        assert artifact.panel is not None
        assert artifact.panel["n_entities"] == 6
        assert artifact.panel["pooled_mase_scale_method"] == (
            "median of per-entity train-only scales"
        )
        assert artifact.panel["entity_columns_order"][0] == "RU"
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert payload["oof_predictions"][0]["entity"] == "RU"
        assert payload["cohort_contract"]["panel_entity"] is True

    def test_model_card_promotion(self):
        session, service = self._prepared()
        _seed_model_card(session)
        artifact = service.promote_model_card(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", card_id="card-d1-1"
        )
        assert artifact.kind == "model_card"
        assert artifact.producer_key == "card:card-d1-1"
        assert "cp-d1-entry" in artifact.dependencies
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert payload["card"]["hyperparameters"] == {"order": [1, 0, 1]}

    def test_forecast_promotion_is_frozen_copy(self):
        """§6 D08: прогноз фиксируется после успешного forecast; promotion
        НЕ пересчитывает -- payload байт-в-байт совпадает с записью сессии."""
        session, service = self._prepared()
        entry = _seed_forecast(session)
        artifact = service.promote_forecast(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", forecast_id="fc-d1-1"
        )
        assert artifact.kind == "forecast"
        assert artifact.producer_key == "forecast:fc-d1-1"
        assert "card-d1-1" in artifact.dependencies
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert payload == entry  # frozen: глубокое равенство, без пересчёта
        assert payload["ci_method"] == "residual_normal"
        assert payload["lineage"]["interval_provenance"] == "residual_normal"

    def test_unknown_forecast_id_is_honest(self):
        session, service = self._prepared()
        from apps.api.artifact_promotion import PromotionUnavailable

        with pytest.raises(PromotionUnavailable):
            service.promote_forecast(
                RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
                forecast_id="fc-missing",
            )

    def test_nan_backtest_payload_refused(self):
        """AC12-дух: NaN не маскируется -- честный отказ, ничего не пишется."""
        session, service = self._prepared()
        entry = _seed_backtest(session)
        entry["metrics"]["mae"] = float("nan")
        from apps.api.artifact_promotion import PromotionUnavailable

        with pytest.raises(PromotionUnavailable):
            service.promote_backtest(
                RUN_ID, _owner_subject(), session, session_id="d1-seed-session", model_id="arima"
            )
        assert service.list_artifacts(
            RUN_ID, subject=_owner_subject(), session_id="d1-seed-session"
        ) == []

    def test_re_promotion_returns_same_artifact(self):
        """AC09: повторный promote того же источника -- тот же артефакт,
        без дублей."""
        session, service = self._prepared()
        _seed_passport(session)
        first = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        second = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        assert first.artifact_id == second.artifact_id
        assert len(
            service.list_artifacts(RUN_ID, subject=_owner_subject(), session_id="d1-seed-session")
        ) == 1


class TestCheckpointDataPromotion:
    def _service(self):
        from apps.api.artifact_promotion import PromotionService

        return PromotionService.create_default()

    def test_checkpoint_data_artifact_with_auto_pin(self):
        import pandas as pd

        from apps.api.research_runs import get_dataset_file_store

        _seed_bound_run()
        file_store = get_dataset_file_store()
        file_store.save_checkpoint_snapshot(
            RUN_ID, "cp-d1-entry", pd.DataFrame({"value": [1.0, 2.0], "date": ["2026-01-01", "2026-01-02"]})
        )
        service = self._service()
        artifact = service.promote_checkpoint_data(
            RUN_ID, _owner_subject(), checkpoint_id="cp-d1-entry", created_by=_owner_subject().subject_id
        )
        assert artifact.kind == "data_frame"
        assert artifact.media_type == "text/csv"
        assert artifact.data_digest["algorithm"] == "cisstat-data-v1"
        assert artifact.data_digest["value"] == artifact.payload_sha256
        # авто-pin зависимости (§16: metadata graph хранит причины)
        pins = service.registry.list_pins(RUN_ID, ref_kind="checkpoint")
        assert any(p.ref_id == "cp-d1-entry" and "artifact:" in p.reason for p in pins)

    def test_checkpoint_data_missing_snapshot_is_honest(self):
        _seed_bound_run()
        service = self._service()
        from apps.api.artifact_promotion import PromotionUnavailable

        with pytest.raises(PromotionUnavailable):
            service.promote_checkpoint_data(
                RUN_ID, _owner_subject(), checkpoint_id="cp-missing",
                created_by=_owner_subject().subject_id,
            )

    def test_checkpoint_data_payload_round_trip(self):
        import pandas as pd
        import io

        from apps.api.research_runs import get_dataset_file_store

        _seed_bound_run()
        frame = pd.DataFrame({"value": [1.5, 2.5]})
        get_dataset_file_store().save_checkpoint_snapshot(RUN_ID, "cp-d1-csv", frame)
        service = self._service()
        artifact = service.promote_checkpoint_data(
            RUN_ID, _owner_subject(), checkpoint_id="cp-d1-csv",
            created_by=_owner_subject().subject_id,
        )
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        restored = pd.read_csv(io.StringIO(payload.decode("utf-8")))
        assert list(restored["value"]) == [1.5, 2.5]


# ══════════════════════════════════════════════════════════════════════
# 7. Долговечность: доступность после TTL-сессии (§19 критерий)
# ══════════════════════════════════════════════════════════════════════


class TestDurabilityAfterSessionLoss:
    def _service(self):
        from apps.api.artifact_promotion import PromotionService

        return PromotionService.create_default()

    def test_artifact_available_after_session_expiry(self):
        """Промоушен -> утрата TTL-сессии (сессия удалена из store) ->
        артефакт+байты читаются владельцем-субъектом (стабильный ID,
        паритет API-key контракта)."""
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        # TTL-сессия истекла: сессии больше нет в store
        from apps.api.session_store import get_session_store

        get_session_store().delete("d1-seed-session")
        owner = SubjectRef(
            subject_id=_owner_subject().subject_id,  # стабильный субъект владельца
            tenant_id=DEFAULT_TENANT_ID, via="api_key",
        )
        loaded = service.get_artifact(artifact.artifact_id, owner, session_id="")
        assert loaded.artifact_id == artifact.artifact_id
        payload = service.read_payload(artifact.artifact_id, owner, session_id="")
        assert payload["stage"] == "modeling_entry"
        # артефакт существует НЕЗАВИСИМО от сессионного хранилища
        assert service.registry.get_artifact(artifact.artifact_id) is not None

    def test_fresh_cookie_after_session_loss_is_denied(self):
        """Идентичность продолжает владелец (DOCLOG-0): новый анонимный
        cookie после утраты сессии НЕ получает доступ к durable-артефакту."""
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        from apps.api.session_store import get_session_store

        get_session_store().delete("d1-seed-session")
        stranger = SubjectRef.from_session("d1-brand-new-cookie")
        from apps.api.artifact_promotion import ArtifactAccessDenied

        with pytest.raises(ArtifactAccessDenied):
            service.get_artifact(artifact.artifact_id, stranger, session_id="d1-brand-new-cookie")

    def test_artifact_survives_checkpoint_prune_via_dependency_pin(self):
        """AC04: pruning 6-го чекпоинта не ломает pinned-зависимость:
        артефакт данных чекпоинта авто-pin-ит свой checkpoint, 6 новых
        чекпоинтов после него не удаляют снимок."""
        import pandas as pd

        from apps.api.research_runs import get_dataset_file_store

        _seed_bound_run()
        file_store = get_dataset_file_store()
        file_store.save_checkpoint_snapshot(
            RUN_ID, "cp-d1-entry", pd.DataFrame({"value": [1.0]})
        )
        service = self._service()
        artifact = service.promote_checkpoint_data(
            RUN_ID, _owner_subject(), checkpoint_id="cp-d1-entry",
            created_by=_owner_subject().subject_id,
        )
        # 6 новых чекпоинтов -> keeper оставил бы последние 5
        for i in range(6):
            file_store.save_checkpoint_snapshot(
                RUN_ID, f"cp-late-{i}", pd.DataFrame({"value": [float(i)]})
            )
        all_ids = ["cp-d1-entry"] + [f"cp-late-{i}" for i in range(6)]
        keep = all_ids[-5:]
        pinned = service.registry.pinned_checkpoint_ids(RUN_ID)
        keep = [cid for cid in all_ids if cid in set(keep) | pinned]
        file_store.prune_checkpoints(RUN_ID, keep=keep)
        # зависимость жива: payload артефакта читается, snapshot-файл на месте
        payload = service.read_payload(
            artifact.artifact_id, _owner_subject(), session_id="d1-seed-session"
        )
        assert b"value" in payload
        assert (Path(file_store._checkpoints_dir(RUN_ID)) / "cp-d1-entry.csv").exists()

    def test_artifacts_listing_after_session_loss(self):
        _seed_bound_run()
        service = self._service()
        session = _seed_session()
        _seed_passport(session)
        _seed_forecast(session)
        service.promote_passport(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session",
            stage="modeling_entry",
        )
        service.promote_forecast(
            RUN_ID, _owner_subject(), session, session_id="d1-seed-session", forecast_id="fc-d1-1"
        )
        from apps.api.session_store import get_session_store

        get_session_store().delete("d1-seed-session")
        owner = SubjectRef(
            subject_id=_owner_subject().subject_id, tenant_id=DEFAULT_TENANT_ID, via="api_key"
        )
        items = service.list_artifacts(RUN_ID, subject=owner, session_id="")
        assert {item.kind for item in items} == {"passport", "forecast"}


# ══════════════════════════════════════════════════════════════════════
# 8. /health/ops artifacts-блок (факты без секретов/путей, T6)
# ══════════════════════════════════════════════════════════════════════


class TestHealthOpsArtifacts:
    def test_ops_health_contains_artifacts_block(self, admin_client):
        # паритет test_ops_health_shape: фабрика инициализируется
        # тестом ЯВНО -- health сам фабрики не провоцирует (peek)
        from apps.api.artifact_store import get_artifact_registry

        get_artifact_registry()
        resp = admin_client.get("/health/ops")
        assert resp.status_code == 200
        body = resp.json()
        assert "artifacts" in body
        block = body["artifacts"]
        assert block["registry_backend"] in {"memory", "postgres"}
        assert block["object_store"] == "local_fs"
        assert isinstance(block["data_root_configured"], bool)

    def test_ops_health_artifacts_not_initialized_is_honest(self, admin_client):
        """Без вызова фабрики health показывает честное
        not_initialized (peek не провоцирует создание)."""
        resp = admin_client.get("/health/ops")
        assert resp.status_code == 200
        assert (
            resp.json()["artifacts"]["registry_backend"] == "not_initialized"
        )

    def test_ops_health_does_not_leak_paths_or_dsn(self, admin_client):
        resp = admin_client.get("/health/ops")
        text = resp.text
        assert "artifacts/objects" not in text
        assert str(Path.cwd()) not in text
        assert "postgresql://" not in text


class TestCheckpointRoutePinIntegration:
    """AC04 через реальный POST-маршрут: pin на ранний чекпоинт --
    5 новых чекпоинтов через API не удаляют его снимок."""

    def test_route_prune_respects_pins(self, client):
        import pandas as pd

        from apps.api.artifact_store import get_artifact_registry
        from apps.api.trace_events import make_trace_event

        _seed_session()
        run = _seed_bound_run()
        store = research_runs.get_research_run_store()
        file_store = research_runs.get_dataset_file_store()
        # сессия-источник снимка: dataframe маршрута чекпоинта
        from apps.api.session_store import get_session_store

        session = get_session_store().get("d1-seed-session")
        session.dataframe = pd.DataFrame({"value": [1.0, 2.0]})
        session.data_revision = 3
        get_session_store().save(session)
        # ранний чекпоинт + снимок + pin (ledger + файл)
        seed_event = make_trace_event(
            "checkpoint_saved", stage="modeling", run_id=run.run_id
        )
        store.append_event(run.run_id, seed_event)
        from apps.api.research_runs import ResearchCheckpoint

        early = ResearchCheckpoint(
            checkpoint_id="cp-d1-pinned",
            run_id=run.run_id,
            event_id=seed_event.event_id,
            label="pinned-early",
            has_snapshot=True,
        )
        store.add_checkpoint(run.run_id, early)
        file_store.save_checkpoint_snapshot(
            run.run_id, "cp-d1-pinned", pd.DataFrame({"value": [42.0]})
        )
        get_artifact_registry().pin_ref(
            run.run_id, "checkpoint", "cp-d1-pinned",
            reason="artifact:demo", created_by="subj-x",
        )
        # 5 новых чекпоинтов через маршрут (каждый -- prune до «последних 5»)
        events = [
            make_trace_event("checkpoint_saved", stage="modeling", run_id=run.run_id)
            for _ in range(5)
        ]
        for event in events:
            store.append_event(run.run_id, event)
            resp = client.post(
                f"/v1/progress/runs/{run.run_id}/checkpoints",
                json={"event_id": event.event_id, "label": "late"},
                cookies={SESSION_COOKIE_NAME: "d1-seed-session"},
            )
            assert resp.status_code == 201, resp.text
        # pinned-снимок пережил все prune; ранний unpinned late-0 удалён
        remaining = {
            path.stem for path in file_store.checkpoint_snapshot_files(run.run_id)
        }
        assert "cp-d1-pinned" in remaining
        late_ids = {f"late-{i}" for i in range(5)}  # seed-id известны из ответов
        # последний из пяти всегда в keep; самый первый late удалён keeper'ом
        checkpoint_ids = [
            cp.checkpoint_id for cp in store.list_checkpoints(run.run_id)
        ]
        assert len(checkpoint_ids) == 6  # ранний + 5 новых
        first_late = checkpoint_ids[1]
        assert first_late not in remaining
