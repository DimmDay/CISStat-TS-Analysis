# scripts/doclog2cert/test_doclog2cert_oracle_unit.py
# DOCLOG-2-CERT: юнит-оракулы сертификатора на СВОИХ данных.
# Ключевой контур -- Postgres-зеркало (fake psycopg roundtrip): SQL↔row
# отображение реестра снимков проверяется БЕЗ живого сервера (прецедент
# fakeredis-параметризации repo-тестов). Отдельные оракулы статических
# фактов извлекаются СВОИМ парсером из исходников.
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import (
    ADMIN_KEY, CTX_ALPHA, CTX_BETA, FP, REV_ALPHA, RUN_FOREIGN, RUN_ID,
    RUN_ID_B, RUN_ID_LEGACY, RUN_MISSING, SESSION_B, SESSION_FOREIGN,
    SESSION_ID, UNIFORM_DENIAL_TEXT, admin_subject, append_event,
    foreign_subject, make_artifact, owner_subject, seed_bound_run,
    seed_session, section, service,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════════════════
# 1. Контракт §10.1 (сверка с ОРИГИНАЛОМ спеки, не с docs задачи)
# ══════════════════════════════════════════════════════════════════════


class TestOrcContract:
    def test_schema_and_id_format(self, orc_env):
        from apps.api.report_snapshot import (
            REPORT_SNAPSHOT_SCHEMA_VERSION, is_valid_snapshot_id,
            new_snapshot_id,
        )

        assert REPORT_SNAPSHOT_SCHEMA_VERSION == "doclog.report_snapshot/1"
        sid = new_snapshot_id()
        assert re.fullmatch(r"rs-[0-9a-f]{32}", sid), sid
        assert is_valid_snapshot_id(sid)
        assert not is_valid_snapshot_id("rs-" + "g" * 32)          # не hex
        assert not is_valid_snapshot_id("rs-" + "a" * 31)          # короче
        assert not is_valid_snapshot_id("RUN-D2C00001")            # чужой ns
        assert not is_valid_snapshot_id(None)

    def test_kinds_catalog_independently_from_spec(self, orc_env):
        """Каталог D01-D09 сверяется с §6 СПЕКИ, а не с docs задачи."""
        from apps.api.report_snapshot import DOCUMENT_KINDS

        spec = Path(REPO_ROOT, "spec_documentation_logging.md").read_text("utf-8")
        assert len(DOCUMENT_KINDS) == 9
        expected = {
            "D01": "plan", "D02": "source_passport",
            "D03": "quality_protocol", "D04": "transformation_recipe",
            "D05": "eda_note", "D06": "experiment_protocol",
            "D07": "model_card", "D08": "forecast_release",
            "D09": "panel_appendix",
        }
        for code, kind in expected.items():
            assert DOCUMENT_KINDS[code][0] == kind
            # этап методологии упомянут в спеке §6 у каждой строки
            # (формат строки спеки: «Планирование — D01 «План исследования»»)
            assert f"{code} «" in spec, f"{code} отсутствует в спеке §6"
        # D01 -- форма планирования, этапа реестра нет (честное None)
        assert DOCUMENT_KINDS["D01"][2] is None
        assert DOCUMENT_KINDS["D08"][2] == "forecasting"

    def test_resolve_kinds_aliases_order_dedupe_errors(self, orc_env):
        from apps.api.report_snapshot import resolve_kinds

        assert resolve_kinds(["panel_appendix", "D01"]) == ["D09", "D01"]
        assert resolve_kinds(("D02", "source_passport", "D02")) == ["D02"]
        with pytest.raises(ValueError):
            resolve_kinds([])
        with pytest.raises(ValueError):
            resolve_kinds("D01")  # строка -- не список
        with pytest.raises(ValueError) as ei:
            resolve_kinds(["D10"])
        assert "D09" in str(ei.value)  # известные виды названы

    def test_knowledge_version_missing_file_is_none(self, orc_env, monkeypatch):
        from apps.api import report_snapshot as rs

        monkeypatch.setattr(
            rs, "KNOWLEDGE_REGISTRY_PATH", Path("/nonexistent/d2c/registry.json")
        )
        assert rs.knowledge_registry_version() is None  # не фабкуется

    def test_knowledge_version_matches_manual_sha256(self, orc_env):
        from apps.api.report_snapshot import knowledge_registry_version

        path = Path(REPO_ROOT, "apps/api/knowledge/registry_data.json")
        if not path.exists():
            pytest.skip("registry_data.json отсутствует в базе")
        expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert knowledge_registry_version() == expected
        assert len(expected) == len("sha256:") + 64

    def test_to_dict_excludes_registry_fields(self, orc_env):
        from apps.api.report_snapshot import ReportSnapshot

        snap = ReportSnapshot(snapshot_id="rs-" + "b" * 32,
                              research_run_id=RUN_ID)
        payload = snap.to_dict()
        for registry_field in (
            "payload_sha256", "size_bytes", "storage_key", "kinds",
            "idempotency_key", "request_fingerprint", "created_by",
        ):
            assert registry_field not in payload, registry_field
        assert payload["approval"] is None                      # D11 -> DOCLOG-6
        assert payload["schema_version"] == "doclog.report_snapshot/1"
        assert payload["classification"] == "private"           # §22 default
        assert payload["redaction_profile"] == "owner-v1"
        assert payload["locale"] == "ru-RU"
        assert payload["display_timezone"] == "Europe/Moscow"
        assert payload["template"] == {"id": "research-report", "version": "1.0"}

    def test_from_dict_drops_unknown_keys(self, orc_env):
        from apps.api.report_snapshot import ReportSnapshot

        snap = ReportSnapshot(snapshot_id="rs-" + "c" * 32,
                              research_run_id=RUN_ID)
        payload = snap.to_dict()
        payload["unknown_future_field"] = 42                    # v2-устойчивость
        payload["created_at"] = "не поле контракта"
        restored = ReportSnapshot.from_dict(payload)
        assert restored.snapshot_id == snap.snapshot_id
        assert not hasattr(restored, "unknown_future_field") or \
            not getattr(restored, "unknown_future_field", None)

    def test_copy_is_deep_for_mutable_contract_fields(self, orc_env):
        from apps.api.report_snapshot import ReportSnapshot

        snap = ReportSnapshot(
            snapshot_id="rs-" + "d" * 32, research_run_id=RUN_ID,
            sections=[{"code": "D01", "claims": [{"text": "x"}]}],
            dependencies=["event:e1"],
        )
        clone = snap.copy()
        clone.sections[0]["claims"][0]["text"] = "MUTATED"
        clone.dependencies.append("event:e2")
        assert snap.sections[0]["claims"][0]["text"] == "x"     # R1-копия
        assert snap.dependencies == ["event:e1"]

    def test_validity_matrix_full_corners(self, orc_env):
        from apps.api.report_snapshot import artifact_validity

        class A:  # attr-носитель
            def __init__(self, ctx, rev):
                self.context_id, self.data_revision = ctx, rev

        # оба метаданных отсутствуют -> unknown (даже legacy-зеркало)
        assert artifact_validity(A(None, None), CTX_ALPHA, REV_ALPHA) == "unknown"
        assert artifact_validity(A(None, None), None, None) == "unknown"
        # полное совпадение -> current
        assert artifact_validity(A(CTX_ALPHA, REV_ALPHA), CTX_ALPHA, REV_ALPHA) == "current"
        # известные, но другие -> stale
        assert artifact_validity(A(CTX_ALPHA, REV_ALPHA + 1), CTX_ALPHA, REV_ALPHA) == "stale"
        assert artifact_validity(A(CTX_BETA, REV_ALPHA), CTX_ALPHA, REV_ALPHA) == "stale"
        # rev без ctx: target ctx тоже None и rev совпадает -> current,
        # иначе stale (матрица: известные, не совпадающие -> stale)
        assert artifact_validity(A(None, REV_ALPHA), None, REV_ALPHA) == "current"
        assert artifact_validity(A(None, REV_ALPHA), CTX_ALPHA, REV_ALPHA) == "stale"
        # dict-носитель (строки БД)
        assert artifact_validity(
            {"context_id": CTX_ALPHA, "data_revision": REV_ALPHA},
            CTX_ALPHA, REV_ALPHA,
        ) == "current"


# ══════════════════════════════════════════════════════════════════════
# 2. SourceCutoff §10.2 (последний честный seq / manifest legacy)
# ══════════════════════════════════════════════════════════════════════


class TestOrcCutoff:
    def test_canonical_full_sequence(self, orc_env):
        from apps.api.report_snapshot import build_source_cutoff

        events = [
            {"event_id": "e-d2c-1", "sequence": 7},
            {"event_id": "e-d2c-2", "sequence": 3},
        ]
        cutoff = build_source_cutoff(events)
        assert cutoff.last_sequence == 7
        assert cutoff.event_count == 2
        assert cutoff.ordering_quality == "canonical"
        assert cutoff.event_id_manifest is None     # §18-бережливость

    def test_empty_corpus_honest_zero_canonical(self, orc_env):
        from apps.api.report_snapshot import build_source_cutoff

        cutoff = build_source_cutoff([])
        assert cutoff.last_sequence == 0
        assert cutoff.event_count == 0
        assert cutoff.ordering_quality == "canonical"
        assert cutoff.event_id_manifest is None

    def test_partial_sequence_is_legacy_with_full_manifest(self, orc_env):
        """Частичный sequence: корпус НЕ переупорядочивается sequence'ом;
        manifest содержит ВСЕ id по canonical_event_order."""
        from apps.api.report_snapshot import build_source_cutoff

        events = [
            {"event_id": "e-d2c-a", "sequence": 5},
            {"event_id": "e-d2c-b"},                  # без sequence
            {"event_id": "e-d2c-c", "sequence": 2},
        ]
        cutoff = build_source_cutoff(events)
        assert cutoff.ordering_quality == "legacy"
        assert cutoff.last_sequence == 5  # max СРЕДИ известных, без синтетики
        assert cutoff.event_count == 3
        assert set(cutoff.event_id_manifest) == {"e-d2c-a", "e-d2c-b", "e-d2c-c"}

    def test_bool_sequence_is_not_int_sequence(self, orc_env):
        """True -- подкласс int; в sequence-корпус не проходит (ловушка
        isinstance-проверки), корпус честно legacy."""
        from apps.api.report_snapshot import build_source_cutoff

        events = [{"event_id": "e-d2c-x", "sequence": True}]
        cutoff = build_source_cutoff(events)
        assert cutoff.ordering_quality == "legacy"
        assert cutoff.last_sequence == 0
        assert cutoff.event_id_manifest == ["e-d2c-x"]

    def test_cutoff_roundtrip_and_stability_key(self, orc_env):
        from apps.api.report_snapshot import SourceCutoff

        cut = SourceCutoff(last_sequence=9, event_count=4,
                           ordering_quality="legacy",
                           event_id_manifest=["e1", "e2"])
        restored = SourceCutoff.from_dict(cut.to_dict())
        assert restored.stability_key() == cut.stability_key()
        assert SourceCutoff.from_dict(None).last_sequence == 0
        assert SourceCutoff.from_dict("мусор").event_count == 0
        # manifest -- часть stability_key (появление пробела = изменение)
        assert SourceCutoff(1, 1, "canonical", None).stability_key() != \
            SourceCutoff(1, 1, "legacy", ["e1"]).stability_key()


# ══════════════════════════════════════════════════════════════════════
# 3. Memory-реестр (контракт store: копии, идемпотентность)
# ══════════════════════════════════════════════════════════════════════


def _snap_for_registry(key: str, fp: str = "fp-d2c-1",
                       idem_key: str | None = None) -> "object":
    from apps.api.report_snapshot import ReportSnapshot

    return ReportSnapshot(
        snapshot_id="rs-" + key,
        research_run_id=RUN_ID,
        idempotency_key=idem_key or f"client-{key}",
        request_fingerprint=fp,
        sections=[{"code": "D01", "kind": "plan", "title": "t",
                   "methodology_stage": None, "claims": []}],
    )


class TestOrcRegistryMemory:
    def test_roundtrip_returns_copies(self, orc_env):
        from apps.api.report_snapshot import MemorySnapshotRegistry

        reg = MemorySnapshotRegistry()
        snap = _snap_for_registry("a" * 32)
        snap.payload_sha256 = "p" * 64
        stored, created = reg.register_snapshot(snap, [{"ref_kind": "event",
                                                        "ref_id": "e1",
                                                        "reason": "r"}])
        assert created is True
        got = reg.get_snapshot_record(stored.snapshot_id)
        got.sections.clear()
        again = reg.get_snapshot_record(stored.snapshot_id)
        assert again.sections                       # мутация не портит store
        assert again.payload_sha256 == "p" * 64

    def test_idempotency_semantics(self, orc_env):
        from apps.api.report_snapshot import (
            MemorySnapshotRegistry, SnapshotIdempotencyConflictError,
        )

        reg = MemorySnapshotRegistry()
        first = _snap_for_registry("b" * 32, fp="fp-1", idem_key="idem-1")
        stored, created = reg.register_snapshot(first, [])
        assert created is True
        # тот же ключ (другой snapshot_id) + тот же fingerprint -> прежний
        replay, created2 = reg.register_snapshot(
            _snap_for_registry("c" * 32, fp="fp-1", idem_key="idem-1"), [])
        assert created2 is False
        assert replay.snapshot_id == stored.snapshot_id
        # тот же ключ + другой fingerprint -> конфликт БЕЗ записи
        with pytest.raises(SnapshotIdempotencyConflictError):
            reg.register_snapshot(
                _snap_for_registry("d" * 32, fp="fp-2", idem_key="idem-1"), [])
        assert reg.find_idempotent(RUN_ID, "idem-1") is not None
        assert reg.find_idempotent(RUN_ID, "idem-nope") is None

    def test_list_scoped_sorted_and_probe(self, orc_env):
        from apps.api.report_snapshot import MemorySnapshotRegistry

        reg = MemorySnapshotRegistry()
        s1 = _snap_for_registry("e" * 32)
        s1.captured_at = "2026-10-22T10:00:00+00:00"
        s2 = _snap_for_registry("f" * 32)
        s2.captured_at = "2026-10-22T09:00:00+00:00"
        reg.register_snapshot(s1, [])
        reg.register_snapshot(s2, [])
        ids = [r.snapshot_id for r in reg.list_records(RUN_ID)]
        assert ids == [s2.snapshot_id, s1.snapshot_id]          # по captured_at
        assert reg.list_records("RUN-D2C00002") == []           # scope по run
        assert reg.readiness_probe() == {"ok": True, "backend": "memory"}


# ══════════════════════════════════════════════════════════════════════
# 4. Postgres-зеркало: SQL<->row раундтрип БЕЗ живого сервера
#    (fake psycopg по прецеденту fakeredis; ловит расхождение
#     параметров INSERT и индексов _record_from_row)
# ══════════════════════════════════════════════════════════════════════


class _FakeCursor:
    """Минимальный курсор: перехват execute/executemany, fetchone/fetchall
    по предзагруженным строкам. rowcount по insert_rowcount конна
    (ON CONFLICT DO NOTHING -> 0, обычный INSERT -> 1)."""

    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        self.conn.last_sql = sql
        self.conn.last_params = params
        if "INSERT INTO" in sql:
            # INSERT результат-строк не возвращает; очередь SELECT-строк
            # НЕ расходуется (ON CONFLICT DO NOTHING -> rowcount 0/1)
            if params and "INSERT INTO report_snapshots" in sql:
                self.conn.insert_params.append(tuple(params))
                self.rowcount = getattr(self.conn, "insert_rowcount", 1)
            return
        self._rows = list(self.conn.result_queue)
        self.conn.result_queue = []

    def executemany(self, sql, seq):
        self.conn.executemany_sql = sql
        self.conn.executemany_params = list(seq)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, result_queue=None):
        self.result_queue = list(result_queue or [])
        self.insert_params: list[tuple] = []
        self.executemany_params: list[tuple] = []
        self.last_sql = ""
        self.last_params = None
        self.committed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _row_from_insert_params(registry_cls, params: tuple) -> tuple:
    """Строка SELECT-порядка из параметров INSERT (имитация того, что
    вернёт реальный Postgres: JSONB -> распарсенный список, TIMESTAMPTZ
    -> datetime). Порядок колонок INSERT == _SELECT_COLUMNS (сверяется
    отдельным статическим оракулом)."""
    import json as _json

    (snapshot_id, run_id, schema_version, kinds, template_id,
     template_version, locale, display_timezone, classification,
     redaction_profile, knowledge_version, cutoff_last_seq, cutoff_count,
     ordering_quality, context_id, data_revision, data_ref,
     digest_alg, digest_value, payload_sha256, size_bytes, storage_key,
     completeness_status, completeness_missing, reproducibility_status,
     reproducibility_reasons, dependencies, idempotency_key,
     request_fingerprint, created_by, created_at) = params
    return (
        snapshot_id, run_id, schema_version, _json.loads(kinds),
        template_id, template_version, locale, display_timezone,
        classification, redaction_profile, knowledge_version,
        cutoff_last_seq, cutoff_count, ordering_quality, context_id,
        data_revision, data_ref, digest_alg, digest_value, payload_sha256,
        size_bytes, storage_key, completeness_status,
        _json.loads(completeness_missing), reproducibility_status,
        _json.loads(reproducibility_reasons), _json.loads(dependencies),
        idempotency_key, request_fingerprint, created_by,
        datetime.fromisoformat(created_at),
    )


class TestOrcPostgresMirror:
    """Контракт-зеркало Postgres-ветки реестра (живой PG -- граница
    среды; SQL<->row согласованность проверяемофа)."""

    def _snapshot_full(self) -> "object":
        from apps.api.report_snapshot import ReportSnapshot

        return ReportSnapshot(
            snapshot_id="rs-" + "9" * 32,
            research_run_id=RUN_ID,
            context_id=CTX_ALPHA,
            data_revision=REV_ALPHA,
            data_ref="artifact:art-d2c-77",
            data_digest={"algorithm": "cisstat-data-v1", "value": "v" * 64},
            source_cutoff={"last_sequence": 12, "event_count": 12,
                           "ordering_quality": "canonical",
                           "event_id_manifest": None},
            knowledge_version="sha256:" + "k" * 64,
            completeness={"status": "partial", "missing_refs": ["artifact:x"]},
            reproducibility={"status": "limited",
                             "reasons": ["missing_oof_artifact"]},
            sections=[{"code": "D02", "kind": "source_passport",
                       "title": "Паспорт источника",
                       "methodology_stage": "upload",
                       "claims": [{"text": "утверждение",
                                   "event_refs": ["event:e-d2c-1"],
                                   "result_refs": [],
                                   "validity": "current",
                                   "evidence_level": "server_result"}]}],
            dependencies=["event:e-d2c-1", "artifact:art-d2c-77"],
            payload_sha256="a" * 64,
            size_bytes=555,
            storage_key="objects/aa/bb",
            kinds=["D02"],
            idempotency_key="client-mirror-1",
            request_fingerprint="fp-mirror-1",
            created_by="subj-d2c-owner",
        )

    def test_static_column_alignment(self, orc_env):
        """СТАТИЧЕСКИЙ факт: число колонок INSERT == число %s == число
        колонок SELECT == 31; все 31 имя совпадают по порядку."""
        from apps.api.report_snapshot import (
            PostgresSnapshotRegistry, REPORT_SNAPSHOT_SCHEMA_VERSION,
        )

        src = Path(REPO_ROOT, "apps/api/report_snapshot.py").read_text("utf-8")
        insert_cols = re.search(
            r"INSERT INTO report_snapshots\s*\((.*?)\)", src, re.S
        ).group(1)
        insert_names = [c.strip() for c in insert_cols.replace("\n", " ").split(",")]
        select_cols = PostgresSnapshotRegistry._SELECT_COLUMNS.replace("\n", " ")
        select_names = [c.strip() for c in select_cols.split(",")]
        assert len(insert_names) == len(select_names) == 31
        assert insert_names == select_names
        values_placeholders = re.search(
            r"VALUES \((.*?)\)", src, re.S
        ).group(1)
        assert values_placeholders.count("%s") == 31

    def test_migration_catalog_keeps_idempotency_unique(self, orc_env):
        """СТАТИЧЕСКИЙ факт (свой разбор): каталог MIGRATION_STATEMENTS_0008
        содержит UNIQUE(run_id, idempotency_key) -- §10.3/AC09 на уровне DDL;
        файл-дубль миграции паритетен каталогу."""
        from apps.api.research_runs import (
            MIGRATION_STATEMENTS_0008, MIGRATION_FILES,
        )

        joined = " ".join(MIGRATION_STATEMENTS_0008)
        assert "UNIQUE (run_id, idempotency_key)" in joined
        assert any(name == "0008_doclog2_snapshots.sql"
                   for name, _stmts in MIGRATION_FILES)
        sql_file = Path(REPO_ROOT,
                        "apps/api/migrations/0008_doclog2_snapshots.sql")
        assert "UNIQUE (run_id, idempotency_key)" in sql_file.read_text("utf-8")
        # deps-таблица: UNIQUE(snapshot_id, ref_kind, ref_id) в обоих источниках
        assert "UNIQUE (snapshot_id, ref_kind, ref_id)" in joined
        assert "UNIQUE (snapshot_id, ref_kind, ref_id)" in \
            sql_file.read_text("utf-8")

    def test_register_then_get_roundtrip(self, orc_env, monkeypatch):
        """РАУНДТРИП: register_snapshot пишет 31 параметр; чтение по
        snapshot_id возвращает запись, у которой все контрактные поля
        совпадают с сохранённым снимком. На поставке 288fdde --
        TypeError (created_at не поле ReportSnapshot): блокер F-D2C1."""
        from apps.api.report_snapshot import (
            PostgresSnapshotRegistry, SnapshotRegistry,
        )

        reg = PostgresSnapshotRegistry(dsn="postgresql://fake-d2c")
        snap = self._snapshot_full()
        deps = [{"ref_kind": "artifact", "ref_id": "art-d2c-77",
                 "reason": "snapshot:" + snap.snapshot_id}]
        conn = _FakeConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)

        stored, created = reg.register_snapshot(snap, deps)
        assert created is True
        assert conn.committed
        assert len(conn.insert_params) == 1

        # чтение: строка, собранная из параметров INSERT (паритет DB)
        row = _row_from_insert_params(PostgresSnapshotRegistry,
                                      conn.insert_params[0])
        conn2 = _FakeConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        got = reg.get_snapshot_record(snap.snapshot_id)
        assert got is not None, "чтение снимка из Postgres-реестра сломано"
        assert got.snapshot_id == snap.snapshot_id
        assert got.research_run_id == RUN_ID
        assert got.kinds == ["D02"]
        assert got.payload_sha256 == "a" * 64
        assert got.size_bytes == 555
        assert got.idempotency_key == "client-mirror-1"
        assert got.request_fingerprint == "fp-mirror-1"
        assert got.created_by == "subj-d2c-owner"
        assert got.completeness["status"] == "partial"
        assert got.completeness["missing_refs"] == ["artifact:x"]
        assert got.reproducibility["reasons"] == ["missing_oof_artifact"]
        assert got.data_digest == {"algorithm": "cisstat-data-v1",
                                   "value": "v" * 64}
        assert got.source_cutoff["last_sequence"] == 12
        assert got.template == {"id": "research-report", "version": "1.0"}

    def test_find_idempotent_returns_existing_with_same_fingerprint(
        self, orc_env, monkeypatch,
    ):
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        reg = PostgresSnapshotRegistry(dsn="postgresql://fake-d2c")
        snap = self._snapshot_full()
        conn = _FakeConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        reg.register_snapshot(snap, [])

        row = _row_from_insert_params(PostgresSnapshotRegistry,
                                      conn.insert_params[0])
        conn2 = _FakeConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        found = reg.find_idempotent(RUN_ID, "client-mirror-1")
        assert found is not None
        assert found.request_fingerprint == "fp-mirror-1"
        # другой ключ -> None (не исключение)
        conn3 = _FakeConn(result_queue=[])
        monkeypatch.setattr(reg, "_connect", lambda: conn3)
        assert reg.find_idempotent(RUN_ID, "client-mirror-other") is None

    def test_conflict_replay_path_raises_409_semantics(
        self, orc_env, monkeypatch,
    ):
        """Конфликт-путь register_snapshot: ON CONFLICT DO NOTHING ->
        перечитывание -> сравнение fingerprint -> 409-исключение.
        TypeError от _record_from_row маскирует контрактную семантику."""
        from apps.api.report_snapshot import (
            PostgresSnapshotRegistry, SnapshotIdempotencyConflictError,
        )

        reg = PostgresSnapshotRegistry(dsn="postgresql://fake-d2c")
        snap = self._snapshot_full()
        conn = _FakeConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        reg.register_snapshot(snap, [])

        row = _row_from_insert_params(PostgresSnapshotRegistry,
                                      conn.insert_params[0])
        # повтор: INSERT конфликтует (rowcount=0 -> result_queue пуст),
        # SELECT возвращает существующую строку
        conn2 = _FakeConn(result_queue=[row])
        conn2.insert_rowcount = 0
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        with pytest.raises(SnapshotIdempotencyConflictError):
            reg.register_snapshot(
                self._snapshot_full().__class__(
                    **{
                        **{f.name: getattr(snap, f.name)
                           for f in dataclasses.fields(snap)
                           if f.name != "snapshot_id"},
                        "snapshot_id": "rs-" + "8" * 32,
                        "request_fingerprint": "fp-mirror-OTHER",
                    }
                ),
                [],
            )

    def test_list_dependencies_contract(self, orc_env, monkeypatch):
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        reg = PostgresSnapshotRegistry(dsn="postgresql://fake-d2c")
        row = ("artifact", "art-d2c-77", "snapshot:rs-" + "9" * 32)
        conn = _FakeConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        deps = reg.list_dependencies("rs-" + "9" * 32)
        assert deps == [{"ref_kind": "artifact", "ref_id": "art-d2c-77",
                         "reason": "snapshot:rs-" + "9" * 32}]
