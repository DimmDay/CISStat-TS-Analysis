# scripts/pgv02cert/test_p2cert_findings_evidence.py
"""Class B -- RED-свидетельства находок сертификации PGV-02.

Эти тесты кодируют ТРЕБОВАНИЯ (ожидаемое честное поведение), которые
нарушаются целью 2f412d6. Они обязаны падать на цели (RED-свидетельство
находки) и стать GREEN БЕЗ правки смысла после адресного фикса
(прецедент PGV-00-FIX §7.4 акта).

Находки (см. docs/cert_pgv02_2026-10-28.md и protocols/probe_findings.txt):
  F-P2C1 -- ensure_print_document_revision: dangling/чужие basis
  F-P2C2 -- CAS fail-open на нечисловой строке ревизии
  F-P2C3 -- manifest_artifact_id вне basis_fingerprint (тихий дроп)
  F-P2C4 -- previous_snapshot_ref == snapshot_ref (самоссылка)
  F-P2C5 -- pin-отказ после создания артефакта (частичное состояние)
  F-P2C6 -- Memory print-реестр маскирует UNIQUE DDL
  N-P2C1 -- context.data_revision='' принимается валидатором
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
    CTX_A,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    checkpoint_payload,
    owner_subject,
    print_snapshot_payload,
    seed_run,
    visual_result_payload,
)


class TestFP2C1BasisExistenceAndOwnership:
    def test_b01_dangling_basis_must_be_refused(self):
        """§10.2 «revision с frozen refs/pins»: ревизия не должна
        создаваться по basis-артефактам, которых нет в реестре.
        Факт цели: ревизия создаётся + пин на несуществующий артефакт."""
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        with pytest.raises(Exception) as excinfo:
            service.ensure_print_document_revision(
                RUN_A, owner_subject(), session_id=SESSION_A,
                print_kind="V01", basis_kind="visual_print_snapshot",
                basis_artifact_ids=[ARTIFACT_MISSING],
            )
        assert "не печатный тип" not in str(excinfo.value)

    def test_b02_foreign_run_basis_must_be_refused(self):
        """§5/§11 object authorization: артефакт чужого run не является
        допустимым basis; пин на чужой артефакт не ставится."""
        from apps.api.artifact_promotion import PromotionService
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_B, SESSION_B)
        foreign_artifact = PromotionService.create_default().persist_visual_artifact(
            RUN_B, owner_subject(SESSION_B), kind="visual_result",
            payload=visual_result_payload(),
            producer_key="pgv.visual_result:p2certb:v1", session_id=SESSION_B,
        )
        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        with pytest.raises(Exception):
            service.ensure_print_document_revision(
                RUN_A, owner_subject(), session_id=SESSION_A,
                print_kind="V01", basis_kind="visual_print_snapshot",
                basis_artifact_ids=[foreign_artifact.artifact_id],
            )


class TestFP2C2CasFailOpen:
    def test_b03_non_numeric_revision_string_must_not_skip_cas(self):
        """PGV-AC07: снапшот декларирует refs.data_revision='42', фактическая
        ревизия запуска 7, expected_context.data_revision='abc' (схема
        PGV-01 допускает любую непустую строку). CAS обязан отказать
        (или явно признать неизвестность), а не молча пропустить сверку."""
        from apps.api.visual_artifacts import (
            PrintContextConflict,
            freeze_visual_print_snapshot,
        )

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        snap = print_snapshot_payload(data_revision=42, expected_revision_raw="abc")
        with pytest.raises(PrintContextConflict):
            freeze_visual_print_snapshot(RUN_A, owner_subject(), payload=snap, session_id=SESSION_A)


class TestFP2C3ManifestIdentity:
    def test_b04_manifest_change_with_same_basis_must_not_be_silent(self):
        """§11 идемпотентность по телу: manifest_artifact_id принимается
        аргументом, но вне basis_fingerprint -- второй вызов с другим
        manifest молча возвращает старую ревизию с чужим manifest."""
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run(RUN_A, SESSION_A)
        service = DocumentDeliveryService.create_default()
        _, rev1, created1 = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="P01", basis_kind="passport",
            basis_artifact_ids=[], manifest_artifact_id="art-" + "11" * 16,
        )
        _, rev2, created2 = service.ensure_print_document_revision(
            RUN_A, owner_subject(), session_id=SESSION_A,
            print_kind="P01", basis_kind="passport",
            basis_artifact_ids=[], manifest_artifact_id="art-" + "22" * 16,
        )
        # Требование: другой manifest -- либо новая ревизия, либо явный
        # конфликт; молчаливый возврат прежнего manifest недопустим.
        assert (
            rev1.manifest_artifact_id == rev2.manifest_artifact_id == "art-" + "22" * 16
            or created2 is True
            or rev1.print_revision_id != rev2.print_revision_id
        )


class TestFP2C4SelfReference:
    def test_b05_previous_snapshot_ref_must_differ_from_snapshot_ref(self):
        """§8: previous_snapshot_ref -- ссылка на ПРЕДЫДУЩИЙ снимок;
        самоссылка (previous == snapshot) не имеет смысла истории."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        from p2cases import SNAPSHOT_REF

        payload = checkpoint_payload(previous_snapshot_ref=SNAPSHOT_REF)
        out = validate_passport_checkpoint(payload)
        assert out, "самоссылка previous==snapshot обязана отвергаться"


class TestFP2C5AtomicPinFailure:
    def test_b06_pin_failure_must_not_leave_artifact_registered(self):
        """AC08-дух: отказ операции не оставляет частичное состояние.
        Факт цели: freeze_visual_print_snapshot при отказе pin_ref после
        persist оставляет зарегистрированный артефакт без пина зависимости."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        seed_run(RUN_A, SESSION_A, context_id=CTX_A, data_revision=7)
        result_artifact = (
            __import__("apps.api.visual_artifacts", fromlist=["freeze_visual_result"])
            .freeze_visual_result(
                RUN_A, owner_subject(),
                payload=visual_result_payload(result_ref="session:p2cert:b6"),
                session_id=SESSION_A,
            )
        )
        count_before = len(get_artifact_registry().list_artifacts(RUN_A))

        class _PinDown(Exception):
            pass

        original = type(get_artifact_registry()).pin_ref

        def boom(*args, **kwargs):
            raise _PinDown("pin storage down")

        type(get_artifact_registry()).pin_ref = boom
        try:
            with pytest.raises(_PinDown):
                freeze_visual_print_snapshot(
                    RUN_A, owner_subject(),
                    payload=print_snapshot_payload(result_digest="aa" * 32),
                    session_id=SESSION_A,
                    result_artifact_id=result_artifact.artifact_id,
                )
            # Требование AC08-дух: артефакт не остаётся в реестре
            assert len(get_artifact_registry().list_artifacts(RUN_A)) == count_before
        finally:
            type(get_artifact_registry()).pin_ref = original


class TestFP2C6MemoryUniqueParity:
    def test_b07_memory_registry_must_enforce_ddl_uniques(self):
        """Класс F-D2C1 («Memory маскирует Postgres»): DDL 0016 несёт
        UNIQUE(document_id, version_no); Memory-реестр обязан давать
        эквивалентный конфликт, а не молча хранить дубликат."""
        from apps.api.document_jobs import (
            DocumentPrintRevisionRecord,
            get_document_registry,
            new_print_revision_id,
        )

        seed_run(RUN_A, SESSION_A)
        registry = get_document_registry()
        first = DocumentPrintRevisionRecord(
            print_revision_id=new_print_revision_id(), document_id="doc-" + "b7" * 16,
            run_id=RUN_A, print_kind="P01", basis_kind="passport", version_no=1,
        )
        duplicate = DocumentPrintRevisionRecord(
            print_revision_id=new_print_revision_id(), document_id=first.document_id,
            run_id=RUN_A, print_kind="P01", basis_kind="passport", version_no=1,
        )
        registry.register_print_revision(first)
        with pytest.raises(Exception):
            registry.register_print_revision(duplicate)
        assert len(registry.list_print_revisions(first.document_id)) == 1


class TestNP2C1EmptyRevisionString:
    def test_b08_empty_data_revision_string_is_not_a_value(self):
        """context.data_revision='' проходит валидатор (проверка только
        `is None`) -- «обязательная ревизия» без значения; аналог класса
        F-D7C2 (bool/пустые значения). Требование: пустая строка --
        missing_required_ref."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        ctx = {
            "run_id": RUN_A, "context_id": CTX_A, "data_revision": "",
            "target_column": "value", "entity_id": None,
        }
        out = validate_passport_checkpoint(checkpoint_payload(context=ctx))
        assert any(v.code == "missing_required_ref" and v.path == "context.data_revision" for v in out)


class TestFP2C7UnupdatedPins:
    def test_b09_all_migration_counter_pins_must_be_updated(self):
        """Требование поставки («пины счётчиков обновлены честно»): ВСЕ
        пины счётчиков миграций -- doclog3/4/5/6/7/8/9 -- обязаны нести
        16 файлов / 96 statements после 0016. Факт цели: doclog3/7/9
        остались на 15/93 (3 новых отказа полного tests/api, см.
        protocols/delta0_summary.json)."""
        import re

        for rel in (
            "tests/api/test_doclog3_telemetry_audit.py",
            "tests/api/test_doclog7_logs_support.py",
            "tests/api/test_doclog9_profiles.py",
        ):
            text = (CERT_DIR.parents[1] / rel).read_text()
            updated = re.search(r"len\(MIGRATION_FILES\) == 16", text) and re.search(
                r"len\(MIGRATION_STATEMENTS\) == 96", text
            )
            assert updated, f"пин счётчиков не обновлён: {rel}"
