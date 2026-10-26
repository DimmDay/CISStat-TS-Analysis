# scripts/doclog1cert/test_doclog1cert_oracle_unit.py
"""DOCLOG-1-CERT: unit-оракулы сертификатора на СВОИХ данных.

Аудируемая поверхность (спека spec_documentation_logging.md §9.3/§10.2
п.6/§16/§8.1/§19.1; AC04/AC08/AC09/AC12-дух/AC13):
  1. Три digest-схемы НЕ взаимозаменяемы; канон без NaN-маскировки;
  2. Staging-протокол: verify fail-closed, объект content-addressed,
     чтение с проверкой целостности (T8/T9);
  3. Реестр: копии записей (R1), идемпотентность (run_id, producer_key),
     конфликт контента без записи; пины идемпотентны, с причиной;
  4. Миграция 0007: каталог-паритет, UNIQUE/FK в DDL;
  5. Health-факты artifacts: peek без провокации, без путей/DSN (T6/T10).

Ожидание на родителе fb26f6f: collection-error (модулей контура нет) --
это факт RED-класса «отсутствующий контур».
"""
from __future__ import annotations

import hashlib
import json as jsonlib
import os
from pathlib import Path

import pytest

from apps.api import artifact_store
from apps.api.artifact_store import (
    ARTIFACT_KINDS,
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactObjectStore,
    DATA_DIGEST_ALGORITHM,
    MemoryArtifactRegistry,
    ResultArtifact,
    StagingVerificationError,
    artifact_content_sha256,
    canonical_json_bytes,
    data_digest,
    is_valid_artifact_id,
    is_valid_source_ref,
    new_artifact_id,
    SerializationError,
)

# ── Свои константы корпуса (дизъюнкт с repo-корпусом) ─────────────────

CERT_RUN = "RUN-D1C00001"
CERT_RUN_B = "RUN-D1C00002"
CERT_FINGERPRINT = "c1f5e8d2" * 8  # 64 hex-символа


def _payload() -> dict:
    """Свой полезный груз (не повторяет repo-фикстуры)."""
    return {
        "units": "thousand tonnes",
        "series": [
            {"period": "2024-01", "value": 101.5},
            {"period": "2024-02", "value": 98.25},
            {"period": "2024-03", "value": 104.125},
        ],
        "meta": {"source": "cert-oracle", "lang": "ru", "примечание": "кириллица"},
    }


def _artifact(payload_sha: str, storage_key: str = "aa/bb", **overrides) -> ResultArtifact:
    base = dict(
        artifact_id=new_artifact_id(),
        run_id=CERT_RUN,
        kind="passport",
        producer_key="passport:cert-snap-1",
        size_bytes=10,
        payload_sha256=payload_sha,
        storage_key=storage_key,
    )
    base.update(overrides)
    return ResultArtifact(**base)


# ══════════════════════════════════════════════════════════════════════
# 1. Digest-схемы (§9.3): три типа, НЕ взаимозаменяемые
# ══════════════════════════════════════════════════════════════════════


class TestCertDigestSchemes:
    def test_canonical_bytes_are_key_sorted_and_compact(self):
        first = canonical_json_bytes({"b": 1, "a": 2})
        second = canonical_json_bytes({"a": 2, "b": 1})
        assert first == second
        assert b'{"a":2,"b":1}' == first  # сортировка + компактные разделители

    def test_canonical_bytes_keep_unicode_unescaped(self):
        raw = canonical_json_bytes({"текст": "значение"})
        assert "значение".encode("utf-8") in raw  # ensure_ascii=False
        assert b"\\u" not in raw

    def test_canonical_bytes_reject_nan_and_infinity(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(SerializationError):
                canonical_json_bytes({"x": bad})
        with pytest.raises(SerializationError):
            canonical_json_bytes({"nested": [{"deep": float("nan")}]})

    def test_content_sha256_is_independently_recomputed(self):
        blob = b"cert-oracle-bytes-\xf0\x9f\x8c\x90"
        assert artifact_content_sha256(blob) == hashlib.sha256(blob).hexdigest()

    def test_data_digest_declares_algorithm_and_version(self):
        blob = b"some-data-frame-bytes"
        digest = data_digest(blob)
        assert digest["algorithm"] == DATA_DIGEST_ALGORITHM == "cisstat-data-v1"
        assert digest["value"] == hashlib.sha256(blob).hexdigest()
        assert set(digest) == {"algorithm", "value"}

    def test_data_digest_structure_is_not_a_bare_hash(self):
        """НЕ взаимозаменяемость: data_digest -- словарь с algorithm,
        а не строка artifact_content_sha256 (§9.3)."""
        blob = b"identical-bytes"
        assert isinstance(data_digest(blob), dict)
        assert artifact_content_sha256(blob) != data_digest(blob)

    def test_source_ref_validation_is_strict_64hex(self):
        assert is_valid_source_ref(CERT_FINGERPRINT)
        assert not is_valid_source_ref(CERT_FINGERPRINT.upper())
        assert not is_valid_source_ref(CERT_FINGERPRINT[:-1])  # 63 символа
        assert not is_valid_source_ref("g1" * 32)  # не hex
        assert not is_valid_source_ref(None)
        assert not is_valid_source_ref(12345)

    def test_artifact_id_shape_is_server_owned(self):
        artifact_id = new_artifact_id()
        assert is_valid_artifact_id(artifact_id)
        assert artifact_id.startswith("art-")
        assert is_valid_artifact_id(artifact_id.replace("art-", "art_")) is False
        assert is_valid_artifact_id("art-xyz") is False
        assert is_valid_artifact_id(None) is False

    def test_known_kinds_catalog(self):
        # DOCLOG-E2E-RECHECK-1-FIX (честное обновление пина эпохи
        # сертификации): каталог расширен producer-интеграцией C03
        # (validation_result -- протокол валидации для D03;
        # correction_recipe -- рецепт коррекции для D04). Пин отражает
        # состояние на момент сертификации DOCLOG-1 + честное расширение.
        assert set(ARTIFACT_KINDS) == {
            "passport",
            "oof_backtest",
            "model_card",
            "forecast",
            "data_frame",
            "validation_result",
            "correction_recipe",
        }


# ══════════════════════════════════════════════════════════════════════
# 2. Staging-протокол (§10.2 п.6 / AC08 / T8 / T9)
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactObjectStore:
    return ArtifactObjectStore(tmp_path / "artifacts-root")


class TestCertStagingProtocol:
    def test_stage_records_exact_sha_and_size(self, store, tmp_path):
        blob = b"payload-for-staging-0123456789"
        staged = store.stage_bytes(blob, "application/json")
        assert staged.sha256 == hashlib.sha256(blob).hexdigest()
        assert staged.size_bytes == len(blob)
        assert staged.path.exists()
        assert staged.path.parent == store.root / "staging"
        # имя staging-файла выдаёт сервер (uuid), а не клиент (T9)
        assert staged.path.name == staged.staging_id
        assert "/" not in staged.staging_id and ".." not in staged.staging_id

    def test_stage_rejects_non_bytes_and_empty_media_type(self, store):
        with pytest.raises(TypeError):
            store.stage_bytes("not-bytes", "application/json")  # type: ignore[arg-type]
        blob = b"ok-bytes"
        with pytest.raises(ValueError):
            store.stage_bytes(blob, "")

    def test_commit_places_content_addressed_object_and_cleans_staging(
        self, store
    ):
        blob = b"content-to-commit-abcdef"
        staged = store.stage_bytes(blob, "application/json")
        key = store.commit_staged(staged)
        assert key == f"{hashlib.sha256(blob).hexdigest()[:2]}/{hashlib.sha256(blob).hexdigest()}"
        object_path = store.root / "objects" / key
        assert object_path.read_bytes() == blob
        assert not staged.path.exists()  # staging убран после коммита

    def test_commit_same_content_twice_is_deduplicated(self, store):
        blob = b"duplicate-content-check"
        key_first = store.commit_staged(store.stage_bytes(blob, "text/csv"))
        key_second = store.commit_staged(store.stage_bytes(blob, "text/csv"))
        assert key_first == key_second
        objects = list((store.root / "objects").rglob("*"))
        files = [path for path in objects if path.is_file()]
        assert len(files) == 1

    def test_commit_detects_corrupted_staging_fail_closed(self, store):
        staged = store.stage_bytes(b"original-staging-payload", "application/json")
        staged.path.write_bytes(b"tampered-payload!!!!!!!!")
        with pytest.raises(StagingVerificationError):
            store.commit_staged(staged)
        assert not staged.path.exists()  # staged удалён (fail-closed)
        assert not (store.root / "objects").exists() or not any(
            (store.root / "objects").rglob("*")
        )

    def test_commit_detects_size_mismatch(self, store, monkeypatch: pytest.MonkeyPatch):
        staged = store.stage_bytes(b"size-check-payload", "application/json")
        # подмена РАЗМЕРА при честных байтах: патчим StagedObject
        from dataclasses import replace as dc_replace

        lying = dc_replace(staged, size_bytes=staged.size_bytes + 5)
        with pytest.raises(StagingVerificationError):
            store.commit_staged(lying)
        assert not staged.path.exists()

    def test_read_verifies_integrity_against_content_key(self, store):
        blob = b"integrity-checked-read"
        key = store.commit_staged(store.stage_bytes(blob, "application/json"))
        assert store.read_bytes(key) == blob
        # подмена байтов объекта: чтение отказывает, не выдаёт битое (T8)
        object_path = store.path_for_key(key)
        object_path.write_bytes(b"silently-replaced-bytes")
        with pytest.raises(ArtifactIntegrityError):
            store.read_bytes(key)

    def test_sweep_removes_only_aged_staging(self, store, tmp_path):
        import time as time_module

        fresh = store.stage_bytes(b"fresh-staging", "application/json")
        stale = store.stage_bytes(b"stale-staging", "application/json")
        aged_stamp = time_module.time() - 7200
        os.utime(stale.path, (aged_stamp, aged_stamp))
        # прогрев objects-канала: объект не трогается sweep'ом
        key = store.commit_staged(store.stage_bytes(b"committed-object", "text/csv"))
        removed = store.sweep_orphan_staging(grace_seconds=3600)
        assert removed == [stale.staging_id]
        assert fresh.path.exists()
        assert store.read_bytes(key) == b"committed-object"

    def test_default_root_follows_data_dir_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "custom"))
        root = ArtifactObjectStore.default_root()
        assert root == tmp_path / "custom" / "artifacts"
        monkeypatch.delenv("CISSTAT_DATA_DIR")
        fallback = ArtifactObjectStore.default_root()
        assert fallback.name == "artifacts" and fallback.parent.name == "data"


# ══════════════════════════════════════════════════════════════════════
# 3. Реестр (AC09 / R1 / пины §16)
# ══════════════════════════════════════════════════════════════════════


class TestCertRegistry:
    def test_register_and_get_round_trip_with_copy_semantics(self):
        registry = MemoryArtifactRegistry()
        artifact = _artifact("a" * 64, storage_key="ab/cd")
        stored, created = registry.register_artifact(artifact)
        assert created is True
        assert stored.artifact_id == artifact.artifact_id
        fetched = registry.get_artifact(artifact.artifact_id)
        assert fetched is not None and fetched.payload_sha256 == "a" * 64
        # R1: мутирование выданной копии не портит реестр
        fetched.dependencies.append("spoisoned-dep")
        fetched.refs["injected"] = True
        again = registry.get_artifact(artifact.artifact_id)
        assert again.dependencies == []
        assert "injected" not in again.refs

    def test_idempotent_re_register_same_producer_content(self):
        registry = MemoryArtifactRegistry()
        first = _artifact("b" * 64)
        stored_first, created_first = registry.register_artifact(first)
        replay = _artifact("b" * 64, artifact_id=new_artifact_id())  # новый id, тот же producer+контент
        stored_second, created_second = registry.register_artifact(replay)
        assert created_first is True and created_second is False
        assert stored_second.artifact_id == stored_first.artifact_id

    def test_conflict_same_producer_other_content_without_write(self):
        registry = MemoryArtifactRegistry()
        registry.register_artifact(_artifact("c" * 64))
        total_before = len(registry.list_artifacts(CERT_RUN))
        with pytest.raises(ArtifactConflictError):
            registry.register_artifact(_artifact("d" * 64))
        assert len(registry.list_artifacts(CERT_RUN)) == total_before

    def test_list_filters_run_and_kind(self):
        registry = MemoryArtifactRegistry()
        registry.register_artifact(_artifact("e" * 64, kind="passport"))
        registry.register_artifact(
            _artifact("f" * 64, kind="forecast", producer_key="forecast:cert-fc")
        )
        registry.register_artifact(
            _artifact(
                "0" * 64,
                run_id=CERT_RUN_B,
                producer_key="passport:other-run",
            )
        )
        assert len(registry.list_artifacts(CERT_RUN)) == 2
        assert len(registry.list_artifacts(CERT_RUN, kind="forecast")) == 1
        assert len(registry.list_artifacts(CERT_RUN_B)) == 1

    def test_register_rejects_bad_id_and_unknown_kind(self):
        registry = MemoryArtifactRegistry()
        with pytest.raises(ValueError):
            registry.register_artifact(_artifact("1" * 64, artifact_id="art-NOTHEX"))
        with pytest.raises(ValueError):
            registry.register_artifact(_artifact("2" * 64, kind="mystery_kind"))


class TestCertPins:
    def test_pin_idempotent_by_triple_and_keeps_reason(self):
        registry = MemoryArtifactRegistry()
        pin_first = registry.pin_ref(
            CERT_RUN, "checkpoint", "cert-cp-1", reason="artifact:art-1", created_by="subj"
        )
        pin_second = registry.pin_ref(
            CERT_RUN, "checkpoint", "cert-cp-1", reason="artifact:art-2"
        )
        assert pin_second.pin_id == pin_first.pin_id
        assert pin_second.reason == "artifact:art-1"  # повтор не переписывает причину
        assert len(registry.list_pins(CERT_RUN)) == 1

    def test_unpin_removes_only_target_triple(self):
        registry = MemoryArtifactRegistry()
        registry.pin_ref(CERT_RUN, "checkpoint", "cert-cp-1")
        registry.pin_ref(CERT_RUN, "checkpoint", "cert-cp-2")
        registry.pin_ref(CERT_RUN_B, "checkpoint", "cert-cp-1")
        assert registry.unpin_ref(CERT_RUN, "checkpoint", "cert-cp-1") is True
        assert registry.unpin_ref(CERT_RUN, "checkpoint", "cert-cp-1") is False
        rest = {(pin.run_id, pin.ref_id) for pin in registry.list_pins(CERT_RUN)}
        rest_b = {(pin.run_id, pin.ref_id) for pin in registry.list_pins(CERT_RUN_B)}
        assert rest == {(CERT_RUN, "cert-cp-2")}
        assert rest_b == {(CERT_RUN_B, "cert-cp-1")}

    def test_pinned_checkpoint_ids_scope_run_and_kind(self):
        registry = MemoryArtifactRegistry()
        registry.pin_ref(CERT_RUN, "checkpoint", "cert-cp-a")
        registry.pin_ref(CERT_RUN, "checkpoint", "cert-cp-b")
        registry.pin_ref(CERT_RUN, "artifact", "art-something")  # не checkpoint
        registry.pin_ref(CERT_RUN_B, "checkpoint", "cert-cp-other-run")
        pinned = registry.pinned_checkpoint_ids(CERT_RUN)
        assert pinned == {"cert-cp-a", "cert-cp-b"}


# ══════════════════════════════════════════════════════════════════════
# 4. Миграция 0007 (§8.1) и health-факты (§19.1/T6/T10)
# ══════════════════════════════════════════════════════════════════════


class TestCertMigration0007:
    def test_catalog_contains_tables_and_unique_constraints(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0007

        joined = "\n".join(MIGRATION_STATEMENTS_0007)
        assert "CREATE TABLE IF NOT EXISTS research_artifacts" in joined
        assert "CREATE TABLE IF NOT EXISTS research_artifact_pins" in joined
        assert "UNIQUE (run_id, producer_key)" in joined
        assert "UNIQUE (run_id, ref_kind, ref_id)" in joined
        assert "REFERENCES research_runs(run_id) ON DELETE CASCADE" in joined

    def test_sql_file_parity_with_catalog(self):
        from apps.api.research_runs import (
            MIGRATION_FILES,
            MIGRATION_STATEMENTS_0007,
        )

        file_map = dict(MIGRATION_FILES)
        assert "0007_doclog1_artifacts.sql" in file_map
        sql_text = (
            Path(__file__).resolve().parents[2]
            / "apps/api/migrations/0007_doclog1_artifacts.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql_text.split())
        for statement in MIGRATION_STATEMENTS_0007:
            assert " ".join(statement.split()) in normalized_sql

    def test_migration_catalog_includes_0007(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS

        joined = "\n".join(MIGRATION_STATEMENTS)
        assert "research_artifact_pins" in joined


class TestCertHealthFacts:
    def test_peek_before_init_is_honest_not_initialized(self, monkeypatch: pytest.MonkeyPatch):
        from apps.api.storage_diagnostics import build_artifacts_health

        monkeypatch.delenv("CISSTAT_DATA_DIR", raising=False)
        block = build_artifacts_health()
        assert block == {
            "registry_backend": "not_initialized",
            "object_store": "local_fs",
            "data_root_configured": False,
        }

    def test_peek_after_init_reports_memory_without_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.storage_diagnostics import build_artifacts_health

        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "leakcheck"))
        get_artifact_registry()
        block = build_artifacts_health()
        assert block["registry_backend"] == "memory"
        assert block["object_store"] == "local_fs"
        assert block["data_root_configured"] is True
        assert str(tmp_path) not in jsonlib.dumps(block)

    def test_factory_memory_backend_explicit(self, monkeypatch: pytest.MonkeyPatch):
        from apps.api.artifact_store import (
            MemoryArtifactRegistry,
            get_artifact_registry,
        )

        monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
        registry = get_artifact_registry()
        assert isinstance(registry, MemoryArtifactRegistry)

    def test_factory_required_mode_fail_closed(self, monkeypatch: pytest.MonkeyPatch):
        """P21/F14-паритет: required-режим с недоступным Postgres --
        fail-closed RuntimeError, тихий Memory-fallback запрещён."""
        from apps.api.artifact_store import get_artifact_registry

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "postgres")
        monkeypatch.setenv("DATABASE_URL", "postgresql://cert:none@127.0.0.1:1/nodb")
        with pytest.raises(RuntimeError) as caught:
            get_artifact_registry()
        assert "fail-closed" in str(caught.value)
