# scripts/doclog6cert/test_d6cert_oracle_unit.py
"""DOCLOG-6-CERT: unit-оракулы на СВОИХ данных (u01–u25).

Поверхность: policy fail-closed, retention-порог честного дефолта,
разделение прав lifecycle_rights (§15/D5), вычислимое состояние ревизии
из append-only записей (§11), реестр Memory, записи/контракты,
канонические JSON-хелперы. Прямые вызовы apps.api.document_lifecycle --
HTTP-слой покрывается отдельно (API-оракулы).
"""
from __future__ import annotations

import json

import pytest

from apps.api import document_lifecycle as dl
from apps.api.document_lifecycle import (
    APPROVAL_POLICY_ENV,
    DEFAULT_RETENTION_DRAFT_DAYS,
    RETENTION_DRAFT_DAYS_ENV,
    ApprovalRecord,
    LifecycleRecord,
    MemoryDocumentLifecycleRegistry,
    RetentionRecord,
    approval_policy,
    canonical_json_bytes,
    json_loads,
    lifecycle_rights,
    retention_draft_days,
)


# ══ 1. Policy fail-closed (§11/D6) ═══════════════════════════════════


def test_u01_policy_default_single(monkeypatch):
    monkeypatch.delenv(APPROVAL_POLICY_ENV, raising=False)
    assert approval_policy() == dl.POLICY_SINGLE


def test_u02_policy_two_person(monkeypatch):
    monkeypatch.setenv(APPROVAL_POLICY_ENV, "two_person")
    assert approval_policy() == dl.POLICY_TWO_PERSON


def test_u03_policy_case_normalized_value(monkeypatch):
    # Значение нормализуется (.strip().lower()): "TWO_PERSON" -- легитимная
    # запись двух лиц; ГАРАНТИЯ fail-closed -- только для незнакомых строк.
    monkeypatch.setenv(APPROVAL_POLICY_ENV, "TWO_PERSON")
    assert approval_policy() == dl.POLICY_TWO_PERSON


def test_u04_policy_garbage_fail_closed(monkeypatch):
    monkeypatch.setenv(APPROVAL_POLICY_ENV, "bogus-policy")
    assert approval_policy() == dl.POLICY_SINGLE


# ══ 2. Retention-порог (§16.1/D8) ════════════════════════════════════


def test_u05_retention_default(monkeypatch):
    monkeypatch.delenv(RETENTION_DRAFT_DAYS_ENV, raising=False)
    assert retention_draft_days() == DEFAULT_RETENTION_DRAFT_DAYS == 30


def test_u06_retention_explicit_45(monkeypatch):
    monkeypatch.setenv(RETENTION_DRAFT_DAYS_ENV, "45")
    assert retention_draft_days() == 45


def test_u07_retention_negative_fails_to_default(monkeypatch):
    monkeypatch.setenv(RETENTION_DRAFT_DAYS_ENV, "-5")
    assert retention_draft_days() == DEFAULT_RETENTION_DRAFT_DAYS


def test_u08_retention_garbage_fails_to_default(monkeypatch):
    monkeypatch.setenv(RETENTION_DRAFT_DAYS_ENV, "abc")
    assert retention_draft_days() == DEFAULT_RETENTION_DRAFT_DAYS


def test_u09_retention_zero_is_legit(monkeypatch):
    monkeypatch.setenv(RETENTION_DRAFT_DAYS_ENV, "0")
    assert retention_draft_days() == 0


# ══ 3. Разделение прав lifecycle_rights (§15/D5) ═════════════════════


class _Subj:
    def __init__(self, subject_id="", via="anonymous", role=None, scopes=(), tenant_id=None):
        self.subject_id = subject_id
        self.via = via
        self.role = role
        self.scopes = frozenset(scopes)
        self.tenant_id = tenant_id
        self.is_anonymous = not subject_id


def test_u10_rights_anonymous_none():
    rights = lifecycle_rights(None)
    assert not rights.can_request and not rights.can_approve
    assert not rights.can_publish and not rights.can_retention
    assert rights.basis == "none"
    assert lifecycle_rights(_Subj()).basis == "none"


def test_u11_rights_admin_full_catalog():
    rights = lifecycle_rights(_Subj("a1", via="api_key", role="admin"))
    assert rights.can_request and rights.can_approve
    assert rights.can_publish and rights.can_retention
    assert rights.basis == "admin_full_catalog"


def test_u12_rights_api_key_granular_scopes(monkeypatch):
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    rights = lifecycle_rights(
        _Subj(
            "w1",
            via="api_key",
            role="internal_analyst",
            scopes=("documentation.write",),
        )
    )
    assert rights.can_request and not rights.can_approve
    assert not rights.can_publish and not rights.can_retention
    assert rights.basis == "scope"
    full = lifecycle_rights(
        _Subj(
            "w2",
            via="api_key",
            role="internal_analyst",
            scopes=(
                "documentation.write",
                "documentation.approve",
                "documentation.publish",
                "policy.admin",
            ),
        )
    )
    assert full.can_request and full.can_approve
    assert full.can_publish and full.can_retention


def test_u13_rights_scoped_mode_no_scopes_no_pilot(monkeypatch):
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "scoped")
    rights = lifecycle_rights(
        _Subj("w3", via="api_key", role="internal_analyst", scopes=())
    )
    assert not rights.can_request and not rights.can_approve
    assert rights.basis == "scoped_mode_no_pilot_rights"


def test_u14_rights_session_surrogate_pilot(monkeypatch):
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    rights = lifecycle_rights(
        _Subj("s1", via="session_surrogate", role=None)
    )
    assert rights.can_request and rights.can_approve
    assert rights.can_publish and rights.can_retention
    assert rights.basis == "session_owner_pilot"


def test_u15_rights_session_surrogate_scoped_mode_none(monkeypatch):
    # В режиме scoped права cookie-суррогата НЕ фантазируются (D5).
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "scoped")
    rights = lifecycle_rights(
        _Subj("s2", via="session_surrogate", role=None)
    )
    assert not rights.can_request and not rights.can_publish
    assert rights.basis == "scoped_mode_no_pilot_rights"


# ══ 4. Состояние ревизии -- вычисляется из append-only записей ═══════


def _record(event: str, revision_id="rev-u", created_at="2026-10-23T10:00:00+00:00"):
    return LifecycleRecord(
        record_id=f"rec-{event}-{revision_id}",
        document_id="doc-u",
        revision_id=revision_id,
        run_id="RUN-D6C00001",
        event=event,
        actor_subject="subject-u",
        created_at=created_at,
    )


def test_u16_state_empty_is_draft():
    registry = MemoryDocumentLifecycleRegistry()
    service = dl.DocumentLifecycleService(registry, delivery=None)
    assert service.revision_state("rev-u") == dl.STATE_DRAFT


def test_u17_state_chain_final_wins():
    registry = MemoryDocumentLifecycleRegistry()
    service = dl.DocumentLifecycleService(registry, delivery=None)
    for index, event in enumerate(
        (
            dl.EVENT_REQUEST,
            dl.EVENT_APPROVED,
            dl.EVENT_PUBLISHED,
            dl.EVENT_RETRACTED,
        )
    ):
        registry.append_lifecycle(
            _record(
                event,
                created_at=f"2026-10-23T10:0{index}:00+00:00",
            )
        )
    assert service.revision_state("rev-u") == dl.STATE_RETRACTED


def test_u18_state_superseded_terminal():
    registry = MemoryDocumentLifecycleRegistry()
    service = dl.DocumentLifecycleService(registry, delivery=None)
    for index, event in enumerate(
        (dl.EVENT_REQUEST, dl.EVENT_PUBLISHED, dl.EVENT_SUPERSEDED)
    ):
        registry.append_lifecycle(
            _record(event, created_at=f"2026-10-23T11:0{index}:00+00:00")
        )
    assert service.revision_state("rev-u") == dl.STATE_SUPERSEDED


# ══ 5. Memory-реестр: порядок/фльтры/retention ═══════════════════════


def test_u19_registry_approvals_order_and_latest():
    registry = MemoryDocumentLifecycleRegistry()
    a1 = ApprovalRecord(
        approval_id="ap-2",
        revision_id="rev-u",
        document_id="doc-u",
        run_id="RUN-D6C00001",
        decision="approve",
        created_at="2026-10-23T10:00:00+00:00",
    )
    a2 = ApprovalRecord(
        approval_id="ap-1",
        revision_id="rev-u",
        document_id="doc-u",
        run_id="RUN-D6C00001",
        decision="reject",
        created_at="2026-10-23T09:00:00+00:00",
    )
    registry.append_approval(a1)
    registry.append_approval(a2)
    listed = registry.list_approvals("rev-u")
    assert [item.approval_id for item in listed] == ["ap-1", "ap-2"]
    assert registry.latest_approval("rev-u").approval_id == "ap-2"
    assert registry.list_approvals("rev-other") == []
    # Сервисный фильтр: только approve-решения -- a1, не reject a2.
    service = dl.DocumentLifecycleService(registry, delivery=None)
    assert service._latest_approval_record("rev-u").approval_id == "ap-2"


def test_u20_registry_retention_upsert_get_list():
    registry = MemoryDocumentLifecycleRegistry()
    r1 = RetentionRecord(
        document_id="doc-1", run_id="RUN-D6C00001", hold=True, hold_reason="d6c"
    )
    registry.upsert_retention(r1)
    registry.upsert_retention(
        RetentionRecord(document_id="doc-2", run_id="RUN-D6C00002")
    )
    got = registry.get_retention("doc-1")
    assert got.hold is True and got.hold_reason == "d6c"
    assert registry.get_retention("doc-missing") is None
    assert [item.document_id for item in registry.list_retention("RUN-D6C00001")] == ["doc-1"]
    # Копия, не ссылка: мутация копии не меняет реестр.
    got.hold = False
    assert registry.get_retention("doc-1").hold is True


def test_u21_records_to_dict_contract():
    approval = ApprovalRecord(
        approval_id="ap-x",
        revision_id="rev-x",
        document_id="doc-x",
        run_id="RUN-D6C00001",
        decision="approve",
        actor_subject="s",
        actor_via="api_key",
        tenant_id="tenant-d6cert-b",
        reason="r",
        snapshot_payload_sha256="a" * 64,
        approval_manifest=[{"rendition_id": "r1", "format": "md", "content_sha256": "b" * 64}],
    )
    body = approval.to_dict()
    assert body["policy_version"] == dl.APPROVAL_POLICY_VERSION
    assert body["policy"] == dl.POLICY_SINGLE
    assert body["approval_manifest"][0]["format"] == "md"
    body["approval_manifest"][0]["format"] = "mutated"
    assert approval.approval_manifest[0]["format"] == "md"  # глубокая копия
    lifecycle = LifecycleRecord(
        record_id="rec-x", document_id="doc-x", revision_id="rev-x",
        run_id="RUN-D6C00001", event=dl.EVENT_PUBLISHED,
    )
    assert lifecycle.to_dict()["event"] == "published"
    retention = RetentionRecord(document_id="doc-x", run_id="RUN-D6C00001")
    assert retention.to_dict()["hold"] is False
    assert retention.to_dict()["hold_reason"] == ""


def test_u22_registry_factory_memory_by_default(monkeypatch):
    monkeypatch.delenv("CISSTAT_DOCUMENTS_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    registry = dl.get_document_lifecycle_registry()
    assert isinstance(registry, MemoryDocumentLifecycleRegistry)
    assert registry.readiness_probe() == {"ok": True, "backend": "memory"}


# ══ 6. Канонические JSON-хелперы / replace / flatten ═════════════════


def test_u23_canonical_json_deterministic_roundtrip():
    payload = {"b": 2, "a": {"z": [1, 2], "k": None}, "c": "кириллица"}
    first = canonical_json_bytes(payload)
    second = canonical_json_bytes({"c": "кириллица", "a": {"k": None, "z": [1, 2]}, "b": 2})
    assert first == second  # канонизация не зависит от порядка вставки
    assert json_loads(first) == payload


def test_u24_replace_record_keeps_original():
    original = RetentionRecord(
        document_id="doc-r", run_id="RUN-D6C00001", hold=False
    )
    updated = dl.replace_record(original, hold=True, hold_reason="d6c-hold")
    assert updated.hold is True and updated.hold_reason == "d6c-hold"
    assert original.hold is False  # исходник не тронут
    assert updated.updated_at == original.updated_at


def test_u25_flatten_claims_by_section_and_text():
    snapshot = {
        "sections": [
            {
                "code": "D01",
                "claims": [
                    {"text": "T1", "validity": "current"},
                    {"text": "T2", "validity": "unknown"},
                ],
            },
            {"code": "D02", "claims": [{"text": "T1", "validity": "stale"}]},
        ]
    }
    flat = dl._flatten_claims(snapshot)
    # Ключ -- "код секции:текст" (контракт кода): одинаковые тексты
    # разных секций не смешиваются.
    assert set(flat) == {"D01:T1", "D01:T2", "D02:T1"}
    assert flat["D01:T1"]["validity"] == "current"
    assert flat["D02:T1"]["validity"] == "stale"
    assert flat["D01:T2"]["validity"] == "unknown"
