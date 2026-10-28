# scripts/pgv02cert/test_p2cert_oracle_api.py
"""Class A service-оракулы: freeze/persist/печатные ревизии/durable read
на СВОИХ данных (namespace p2cert-*).

GREEN на цели 2f412d6; RED на родителе 0f8b9a0.
"""
from __future__ import annotations

import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest

from p2cases import (
    ARTIFACT_MISSING,
    CHECKPOINT_ID,
    CHECKPOINT_ID_ALT,
    CTX_A,
    FOREIGN_SESSION,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    VIEW_DEMO_KDE,
    VIEW_RESEARCH_CHART,
    VIEW_RESEARCH_HEATMAP,
    checkpoint_payload,
    owner_subject,
    print_snapshot_payload,
    seed_run,
    visual_result_payload,
)


def artifact_kinds(run_id: str) -> list[str]:
    from apps.api.artifact_store import get_artifact_registry

    return [a.kind for a in get_artifact_registry().list_artifacts(run_id)]


def visual_kinds_of(run_id: str, kind: str) -> list:
    from apps.api.artifact_store import get_artifact_registry

    return get_artifact_registry().list_artifacts(run_id, kind=kind)


# ══════════════════════════════════════════════════════════════════════
# freeze_visual_result: единый конвейер + идемпотентность + CAS (AC07)
# ══════════════════════════════════════════════════════════════════════


class TestFreezeVisualResultService:
    def test_a01_freeze_registers_durable_artifact(self):
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        artifact = freeze_visual_result(
            RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A
        )
        assert artifact.kind == "visual_result"
        assert artifact.schema_version == "pgv.visual_result/1"
        assert artifact.refs["view_id"] == VIEW_RESEARCH_CHART
        assert artifact.refs["result_ref"] == "session:p2cert:hist:v1"
        assert artifact.context_id == CTX_A
        assert artifact.data_revision == 7

    def test_a02_idempotent_retransfer_same_payload(self):
        # AC09-дух: тот же результат переносится идемпотентно
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        first = freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        second = freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        assert first.artifact_id == second.artifact_id
        assert len(visual_kinds_of(RUN_A, "visual_result")) == 1

    def test_a03_same_key_different_payload_is_conflict(self):
        # §11: иной payload с прежним key -- 409-семантика (не маскируется)
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        tampered = visual_result_payload(
            parameters={"origin": "producer_freeze", "method": "histogram", "parameters": {"bins": 99}}
        )
        with pytest.raises(ArtifactConflictError):
            freeze_visual_result(RUN_A, owner_subject(), payload=tampered, session_id=SESSION_A)

    def test_a04_recomputed_result_is_new_immutable_artifact(self):
        # §6: пересчёт (другой result_ref) -- НОВЫЙ артефакт, старый цел
        from apps.api.artifact_store import artifact_content_sha256
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        first = freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        second = freeze_visual_result(
            RUN_A,
            owner_subject(),
            payload=visual_result_payload(result_ref="session:p2cert:hist:v2"),
            session_id=SESSION_A,
        )
        assert first.artifact_id != second.artifact_id
        assert first.payload_sha256 != second.payload_sha256
        assert len(visual_kinds_of(RUN_A, "visual_result")) == 2

    def test_a05_invalid_payload_not_registered_at_all(self):
        # AC12-дух: gap, не «готовая» картинка; ничего в реестре
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.visual_artifacts import ArtifactPayloadInvalid, freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        broken = visual_result_payload(units=[{"value": None, "reason": None}])
        with pytest.raises(ArtifactPayloadInvalid):
            freeze_visual_result(RUN_A, owner_subject(), payload=broken, session_id=SESSION_A)
        assert artifact_kinds(RUN_A) == []

    def test_a06_unknown_view_not_frozen(self):
        from apps.api.visual_artifacts import ArtifactPayloadInvalid, freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        with pytest.raises(ArtifactPayloadInvalid) as excinfo:
            freeze_visual_result(
                RUN_A, owner_subject(), payload=visual_result_payload(view_id="future.chart"), session_id=SESSION_A
            )
        assert any(v.code == "unknown_view" for v in excinfo.value.violations)
        assert artifact_kinds(RUN_A) == []

    def test_a07_cas_conflict_registers_nothing(self):
        # PGV-AC07: расхождение контекста -- честный конфликт, пустой след
        from apps.api.visual_artifacts import PrintContextConflict, freeze_visual_result

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        with pytest.raises(PrintContextConflict) as excinfo:
            freeze_visual_result(
                RUN_A,
                owner_subject(),
                payload=visual_result_payload(),
                session_id=SESSION_A,
                expected_context_id="ctx-p2cert-old",
            )
        assert excinfo.value.error_code == "context_changed"
        assert artifact_kinds(RUN_A) == []

    def test_a08_cas_revision_conflict_registers_nothing(self):
        from apps.api.visual_artifacts import PrintContextConflict, freeze_visual_result

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=8)
        with pytest.raises(PrintContextConflict):
            freeze_visual_result(
                RUN_A,
                owner_subject(),
                payload=visual_result_payload(),
                session_id=SESSION_A,
                expected_data_revision=7,
            )
        assert artifact_kinds(RUN_A) == []

    def test_a09_cas_match_registers_with_own_metadata(self):
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        artifact = freeze_visual_result(
            RUN_A,
            owner_subject(),
            payload=visual_result_payload(),
            session_id=SESSION_A,
            expected_context_id=CTX_A,
            expected_data_revision=7,
        )
        assert artifact.kind == "visual_result"

    def test_a10_foreign_subject_denied_uniformly(self):
        # R09/T7: отказ без дисклоужения существования
        from apps.api.artifact_promotion import PromotionDenied
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A)
        with pytest.raises(PromotionDenied):
            freeze_visual_result(
                RUN_A, owner_subject(FOREIGN_SESSION), payload=visual_result_payload(), session_id=FOREIGN_SESSION
            )
        assert artifact_kinds(RUN_A) == []


# ══════════════════════════════════════════════════════════════════════
# freeze_visual_print_snapshot: сайт реестра, пин зависимости, CAS
# ══════════════════════════════════════════════════════════════════════


class TestFreezePrintSnapshotService:
    def _seed_with_result(self):
        from apps.api.visual_artifacts import freeze_visual_result

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        result_artifact = freeze_visual_result(
            RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A
        )
        return result_artifact

    def test_a11_snapshot_freeze_pins_dependency_with_reason(self):
        # §16: metadata graph хранит ПРИЧИНЫ ссылок
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        result_artifact = self._seed_with_result()
        snapshot = freeze_visual_print_snapshot(
            RUN_A,
            owner_subject(),
            payload=print_snapshot_payload(),
            session_id=SESSION_A,
            result_artifact_id=result_artifact.artifact_id,
        )
        assert snapshot.kind == "visual_print_snapshot"
        assert snapshot.schema_version == "pgv.visual_print_snapshot/1"
        pins = get_artifact_registry().list_pins(RUN_A, ref_kind="artifact")
        pinned = {p.ref_id: p.reason for p in pins}
        assert pinned.get(result_artifact.artifact_id) == f"print_snapshot:{snapshot.artifact_id}"

    def test_a12_snapshot_validates_against_registry_site(self):
        from apps.api.visual_artifacts import ArtifactPayloadInvalid, freeze_visual_print_snapshot

        self._seed_with_result()
        # сайт upload.distribution.histogram рендерит recharts_svg -- секция
        # html_table не соответствует составу
        snap = print_snapshot_payload()
        snap["display"]["sections"] = [dict(snap["display"]["sections"][0], renderer_kind="html_table")]
        with pytest.raises(ArtifactPayloadInvalid) as excinfo:
            freeze_visual_print_snapshot(RUN_A, owner_subject(), payload=snap, session_id=SESSION_A)
        assert any(v.code == "section_kind_mismatch" for v in excinfo.value.violations)

    def test_a13_snapshot_cas_numeric_string_revision(self):
        # PGV-AC07: строка-ревизия по контракту PGV-01 сверяется
        from apps.api.visual_artifacts import PrintContextConflict, freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=8)
        snap = print_snapshot_payload()  # expected data_revision "7"
        with pytest.raises(PrintContextConflict):
            freeze_visual_print_snapshot(RUN_A, owner_subject(), payload=snap, session_id=SESSION_A)

    def test_a14_snapshot_cas_match_registers(self):
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        snapshot = freeze_visual_print_snapshot(
            RUN_A, owner_subject(), payload=print_snapshot_payload(), session_id=SESSION_A
        )
        assert snapshot.context_id == CTX_A
        assert snapshot.data_revision == 7

    def test_a15_demo_scope_snapshot_without_cas(self):
        # demo-скоуп без контекста: CAS не проходит (нет чего сверять)
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A)
        snapshot = freeze_visual_print_snapshot(
            RUN_A,
            owner_subject(),
            payload=print_snapshot_payload(view_id=VIEW_DEMO_KDE, data_revision=None),
            session_id=SESSION_A,
        )
        assert snapshot.kind == "visual_print_snapshot"

    def test_a16_heatmap_snapshot_via_own_view(self):
        # второй research-сайт: html_heatmap с собственной шкалой
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        snapshot = freeze_visual_print_snapshot(
            RUN_A,
            owner_subject(),
            payload=print_snapshot_payload(view_id=VIEW_RESEARCH_HEATMAP),
            session_id=SESSION_A,
        )
        assert snapshot.refs["view_id"] == VIEW_RESEARCH_HEATMAP


# ══════════════════════════════════════════════════════════════════════
# register_passport_checkpoint + durable read (субстрат AC09)
# ══════════════════════════════════════════════════════════════════════


class TestPassportCheckpointService:
    def test_a17_checkpoint_registered_and_idempotent_by_id(self):
        # §8: идемпотентность по checkpoint_id
        from apps.api.visual_artifacts import register_passport_checkpoint

        seed_run(RUN_A, SESSION_A)
        first = register_passport_checkpoint(RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A)
        second = register_passport_checkpoint(RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A)
        assert first.artifact_id == second.artifact_id
        assert first.schema_version == "pgv.passport_checkpoint/1"
        assert first.refs["checkpoint_id"] == CHECKPOINT_ID

    def test_a18_same_checkpoint_id_different_payload_conflicts(self):
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.visual_artifacts import register_passport_checkpoint

        seed_run(RUN_A, SESSION_A)
        register_passport_checkpoint(RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A)
        tampered = checkpoint_payload(confirmed_at="2026-10-28T23:59:59Z")
        with pytest.raises(ArtifactConflictError):
            register_passport_checkpoint(RUN_A, owner_subject(), payload=tampered, session_id=SESSION_A)

    def test_a19_invalid_checkpoint_not_registered(self):
        from apps.api.visual_artifacts import ArtifactPayloadInvalid, register_passport_checkpoint

        seed_run(RUN_A, SESSION_A)
        broken = checkpoint_payload(confirmed_at=None, confirmed_at_reason=None)
        with pytest.raises(ArtifactPayloadInvalid):
            register_passport_checkpoint(RUN_A, owner_subject(), payload=broken, session_id=SESSION_A)
        assert artifact_kinds(RUN_A) == []

    def test_a20_durable_read_after_session_loss(self):
        # Субстрат AC09: чтение из registry/ObjectStore БЕЗ session/Redis;
        # утрата session-store не влияет на durable-чтение
        from apps.api.session_store import reset_session_store_for_testing
        from apps.api.visual_artifacts import (
            get_passport_checkpoint,
            list_visual_results,
            register_passport_checkpoint,
        )

        seed_run(RUN_A, SESSION_A)
        register_passport_checkpoint(RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A)
        freeze = __import__("apps.api.visual_artifacts", fromlist=["freeze_visual_result"]).freeze_visual_result
        frozen = freeze(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        reset_session_store_for_testing()  # сессия утрачена (TTL/рестарт)
        results = list_visual_results(RUN_A)
        assert [a.artifact_id for a in results] == [frozen.artifact_id]
        checkpoint = get_passport_checkpoint(RUN_A, CHECKPOINT_ID)
        assert checkpoint is not None
        assert checkpoint.refs["checkpoint_id"] == CHECKPOINT_ID
        assert checkpoint.payload_dict() is not None if hasattr(checkpoint, "payload_dict") else True

    def test_a21_list_filter_by_view_and_unknown_checkpoint_none(self):
        from apps.api.visual_artifacts import (
            freeze_visual_result,
            get_passport_checkpoint,
            list_visual_results,
        )

        seed_run(RUN_A, SESSION_A)
        freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        freeze_visual_result(
            RUN_A,
            owner_subject(),
            payload=visual_result_payload(view_id=VIEW_RESEARCH_HEATMAP, result_ref="session:p2cert:hm:v1"),
            session_id=SESSION_A,
        )
        hist = list_visual_results(RUN_A, view_id=VIEW_RESEARCH_CHART)
        assert len(hist) == 1
        assert hist[0].refs["view_id"] == VIEW_RESEARCH_CHART
        assert len(list_visual_results(RUN_A)) == 2
        # отсутствующий чекпоинт -- None без фабкации (AC12-дух)
        assert get_passport_checkpoint(RUN_A, "pck-p2cert-absent") is None


# ══════════════════════════════════════════════════════════════════════
# persist_visual_artifact: гейт/версии схем/неизвестный kind
# ══════════════════════════════════════════════════════════════════════


class TestPersistGate:
    def test_a22_unknown_kind_value_error(self):
        from apps.api.artifact_promotion import PromotionService

        seed_run(RUN_A, SESSION_A)
        service = PromotionService.create_default()
        with pytest.raises(ValueError):
            service.persist_visual_artifact(
                RUN_A, owner_subject(), kind="chart", payload={}, producer_key="pgv:boom"
            )

    def test_a23_per_kind_schema_versions_pinned(self):
        from apps.api.visual_artifacts import (
            freeze_visual_print_snapshot,
            freeze_visual_result,
            register_passport_checkpoint,
        )

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        result = freeze_visual_result(RUN_A, owner_subject(), payload=visual_result_payload(), session_id=SESSION_A)
        snapshot = freeze_visual_print_snapshot(
            RUN_A, owner_subject(), payload=print_snapshot_payload(), session_id=SESSION_A
        )
        checkpoint = register_passport_checkpoint(
            RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A
        )
        assert result.schema_version == "pgv.visual_result/1"
        assert snapshot.schema_version == "pgv.visual_print_snapshot/1"
        assert checkpoint.schema_version == "pgv.passport_checkpoint/1"


# ══════════════════════════════════════════════════════════════════════
# Печатные документы/ревизии V01/P01/P02 (§10.2) + legacy поток цел
# ══════════════════════════════════════════════════════════════════════


class TestPrintDocumentRevisions:
    def test_a24_ensure_creates_document_and_revision(self):
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        document, revision, created = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot",
            basis_artifact_ids=[],
        )
        assert created is True
        assert document.kind_code == "V01"
        assert document.run_id == RUN_A
        assert revision.print_kind == "V01"
        assert revision.version_no == 1
        assert revision.print_revision_id.startswith("dprint-")
        assert revision.profile_id == "figure-landscape"

    def test_a25_idempotent_by_basis_fingerprint(self):
        # §12.2: повторный клик не создаёт дубли
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        _, first, created1 = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="P01", basis_kind="passport", basis_artifact_ids=[],
        )
        _, second, created2 = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="P01", basis_kind="passport", basis_artifact_ids=[],
        )
        assert created1 is True and created2 is False
        assert first.print_revision_id == second.print_revision_id
        assert first.version_no == second.version_no == 1

    def test_a26_profile_change_creates_new_version(self):
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        _, first, _ = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
        )
        _, second, created = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
            profile_id="a4-portrait",
        )
        assert created is True
        assert first.print_revision_id != second.print_revision_id
        assert second.version_no == first.version_no + 1

    def test_a27_non_print_kind_refused(self):
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        for code in ("D02", "D01", "V99"):
            with pytest.raises(Exception) as excinfo:
                service.ensure_print_document_revision(
                    RUN_A, owner_subject(), session_id=SESSION_A,
                    print_kind=code, basis_kind="passport",
                )
            assert "не печатный тип" in str(excinfo.value) or "Unsupported" in type(excinfo.value).__name__

    def test_a28_basis_artifacts_pinned_with_reason(self):
        # §16: pins basis с причиной print_revision:{id}
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        snapshot = freeze_visual_print_snapshot(
            RUN_A, owner_subject(), payload=print_snapshot_payload(), session_id=SESSION_A
        )
        service = DocumentDeliveryService.create_default()
        _, revision, _ = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot",
            basis_artifact_ids=[snapshot.artifact_id],
        )
        pins = {p.ref_id: p.reason for p in get_artifact_registry().list_pins(RUN_A, ref_kind="artifact")}
        assert pins[snapshot.artifact_id] == f"print_revision:{revision.print_revision_id}"

    def test_a29_list_print_documents_and_foreign_read_denied(self):
        from apps.api.document_jobs import DocumentAccessDenied, DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
        )
        service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="P01", basis_kind="passport", basis_artifact_ids=[],
        )
        listed = service.list_print_documents(RUN_A, owner_subject(), session_id=SESSION_A)
        assert [d.kind_code for d, _ in listed] == ["V01", "P01"]
        assert all(len(revs) == 1 for _, revs in listed)
        filtered = service.list_print_documents(RUN_A, owner_subject(), session_id=SESSION_A, print_kind="P01")
        assert [d.kind_code for d, _ in filtered] == ["P01"]
        with pytest.raises(DocumentAccessDenied):
            service.list_print_documents(RUN_A, owner_subject(FOREIGN_SESSION), session_id=FOREIGN_SESSION)

    def test_a30_legacy_document_flow_untouched(self):
        # Критерий PGV-02: legacy D01–12/readers работают; печатные
        # документы НЕ попадают в legacy list (скан только D-кодам)
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
        )
        # legacy-поток: D01 через снапшот-сборщик и ensure_document_revision
        from apps.api.snapshot_builder import SnapshotService

        snapshot, _created_snapshot = SnapshotService.create_default().build_snapshot(
            RUN_A, owner_subject(), session_id=SESSION_A, kinds=["D01"]
        )
        document, revision, created = service.ensure_document_revision(
            snapshot, subject=owner_subject(), session_id=SESSION_A,
        )
        assert created is True
        assert document.kind_code == "D01"
        assert revision.revision_id.startswith("drev-")
        assert revision.snapshot_id == snapshot.snapshot_id
        listed = service.list_documents(RUN_A, owner_subject(), session_id=SESSION_A)
        assert [d.kind_code for d, _ in listed] == ["D01"]  # V01 не в legacy-ответе
        # повтор с тем же снапшотом -- идемпотентен
        _, again, created_again = service.ensure_document_revision(
            snapshot, subject=owner_subject(), session_id=SESSION_A,
        )
        assert created_again is False
        assert again.revision_id == revision.revision_id

    def test_a31_registry_contract_print_methods_all_classes(self):
        # Структурный паритет ABC/Memory/Postgres (урок F-D2C1)
        from apps.api.document_jobs import (
            DocumentRegistry,
            MemoryDocumentRegistry,
            PostgresDocumentRegistry,
        )

        methods = (
            "register_print_revision",
            "get_print_revision",
            "find_print_revision_by_fingerprint",
            "list_print_revisions",
        )
        for method in methods:
            assert hasattr(DocumentRegistry, method), method
            assert hasattr(MemoryDocumentRegistry, method), method
            assert hasattr(PostgresDocumentRegistry, method), method
            assert method in DocumentRegistry.__abstractmethods__ or callable(
                getattr(DocumentRegistry, method)
            )

    def test_a32_version_no_monotonic_across_bases(self):
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        versions = []
        for basis in ("passport", "comparison", "visual_print_snapshot"):
            _, revision, _ = service.ensure_print_document_revision(
                RUN_A, owner_subject(), session_id=SESSION_A,
                print_kind="P02", basis_kind=basis, basis_artifact_ids=[],
            )
            versions.append(revision.version_no)
        assert versions == [1, 2, 3]


# ══════════════════════════════════════════════════════════════════════
# Усиление корпуса по итогам кампании (честная эволюция оракулов:
# M10/M19 изначально SURVIVED -- гэп покрытия закрывается пинами a33/a34)
# ══════════════════════════════════════════════════════════════════════


class TestOracleStrengthening:
    def test_a33_checkpoint_lookup_is_by_id_not_first_artifact(self):
        """Пин против M10: get_passport_checkpoint по ЧУЖОМУ checkpoint_id
        обязан вернуть None, даже когда в run есть другие чекпоинты
        (фабкация чужого факта недопустима)."""
        from apps.api.visual_artifacts import (
            get_passport_checkpoint,
            register_passport_checkpoint,
        )

        seed_run(RUN_A, SESSION_A)
        register_passport_checkpoint(
            RUN_A, owner_subject(), payload=checkpoint_payload(), session_id=SESSION_A
        )
        assert get_passport_checkpoint(RUN_A, CHECKPOINT_ID) is not None
        # чужой id при живом чекпоинте -- None, а не «первый попавшийся»
        assert get_passport_checkpoint(RUN_A, "pck-p2cert-other") is None

    def test_a34_print_revision_updates_document_pointer(self):
        """Пин против M19: ревизия печатного документа обновляет
        document.current_revision_id (паритет legacy register_revision)."""
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        document, revision, created = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
        )
        refreshed = service.registry.get_document(document.document_id)
        assert refreshed.current_revision_id == revision.print_revision_id
        # вторая ревизия (смена профиля) -- указатель на последнюю
        _, second, _ = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="V01", basis_kind="visual_print_snapshot", basis_artifact_ids=[],
            profile_id="a4-portrait",
        )
        refreshed = service.registry.get_document(document.document_id)
        assert refreshed.current_revision_id == second.print_revision_id
