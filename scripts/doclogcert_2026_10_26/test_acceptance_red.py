"""Acceptance expectations, intentionally RED on the audited product.

Inputs come from reproduce_scenario.py, not fabricated artifact seeds.
Positive controls distinguish an integration failure from a dead renderer.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def observation():
    return json.loads((HERE / "protocols/scenario.json").read_text())


def test_source_passport_is_promoted_by_the_actual_pipeline(observation):
    passports = [a for a in observation["artifacts_after_real_pipeline"] if a["kind"] == "passport"]
    assert passports, "Session passport exists, but no durable passport artifact is produced"


def test_unknown_source_passport_is_not_presented_as_complete(observation):
    doc = next(d for d in observation["manual_documents"] if d["kind"] == "D02")
    assert doc["completeness"]["status"] == "partial", (
        "Source passport and data_ref are missing, yet completeness is complete"
    )


def test_historical_event_claims_are_not_marked_current(observation):
    wrong = [x for x in observation["event_claim_validity"]
             if x["event_context"] != x["snapshot_context"] and x["claim_validity"] == "current"]
    assert not wrong, wrong


def test_preprocessing_document_preserves_actual_strategy(observation):
    doc = next(d for d in observation["manual_documents"] if d["kind"] == "D04")
    texts = "\n".join(c["text"] for section in doc["sections"] for c in section["claims"])
    assert "median_mode" in texts and "iqr" in texts, texts


def test_mandatory_profile_audit_failure_does_not_commit_policy():
    from apps.api.doc_profiles import OrgProfileService, MemoryOrgProfileRegistry
    from apps.api.security_audit import MandatoryAuditFailure, set_audit_sink_for_testing

    class UnavailableAudit:
        def append(self, record):
            raise RuntimeError("owned-audit-unavailable")

    registry = MemoryOrgProfileRegistry()
    service = OrgProfileService(registry)
    subject = SimpleNamespace(is_anonymous=False, role="admin", subject_id="audit-cert-subject",
                              tenant_id="audit-cert-tenant", via="api_key", scopes=frozenset())
    set_audit_sink_for_testing(UnavailableAudit())
    try:
        with pytest.raises(MandatoryAuditFailure):
            service.create_profile(name="audit-cert-policy", version_no=1,
                                   format="docx", subject=subject)
    finally:
        set_audit_sink_for_testing(None)
    assert registry.find_duplicate("audit-cert-policy", 1) is None, "Protected write survives mandatory audit failure"


def test_control_explicit_api_creation_and_rendering_work(observation):
    assert observation["after_manual_document_count"] == 3
    assert all(d["formats"]["pdf"]["state"] == "ready" for d in observation["manual_documents"])


def test_control_document_reading_does_not_mutate_science(observation):
    assert observation["read_render_preserved_science"] is True


def test_control_anonymous_cannot_read_generated_documents(observation):
    assert all(d["foreign_http"] == 404 for d in observation["manual_documents"])
