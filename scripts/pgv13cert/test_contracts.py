"""Independent PGV-13 acceptance. Raw failures are findings, never xfail/PASS.

Own durable facts (no imported implementation-test fixtures or live DataFrame).
Set CISSTAT_PGV13_CERT_DSN only to a disposable PG database with CREATE DATABASE.
The supplied SubjectRef is trusted evidence: this suite certifies object gates,
not the entire personal-login transport or AUTH13 managed-worker authority.
"""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def facts(tmp_path, monkeypatch):
    from apps.api import artifact_store as A, document_jobs as D
    from apps.api import report_snapshot as S, research_runs as R
    from apps.api.artifact_promotion import PromotionService
    from apps.api.identity import Scope, SubjectRef
    from apps.api.visual_artifacts import register_passport_checkpoint

    for key in ("DATABASE_URL", "CISSTAT_AUTH_DATABASE_URL", "CISSTAT_API_KEYS",
                "REDIS_URL", "CISSTAT_RUNS_BACKEND", "CISSTAT_ARTIFACTS_BACKEND",
                "CISSTAT_SNAPSHOTS_BACKEND", "CISSTAT_DOCUMENTS_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "objects"))
    resetters = (R.reset_research_run_store_for_testing,
                 A.reset_artifact_registry_for_testing, A.reset_artifact_object_store_for_testing,
                 S.reset_snapshot_registry_for_testing, D.reset_document_registry_for_testing)
    native = os.environ.get("CISSTAT_PGV13_CERT_DSN")
    db = None
    if native:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        db = "pgv13cert_" + uuid4().hex
        with psycopg.connect(native, autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
        monkeypatch.setenv("DATABASE_URL", make_conninfo(native, dbname=db))
    for reset in resetters:
        reset()
    run = "RUN-C13A0001"
    account, subject = str(uuid4()), str(uuid4())
    owner = SubjectRef(subject_id=subject, account_id=account, tenant_id="tenant-cert",
                       via="auth_session", auth_method="auth_session", is_authenticated=True,
                       scopes=frozenset(s.value for s in Scope))
    R.get_research_run_store().upsert_run(R.ResearchRun(
        run_id=run, session_id="lost-research-session", owner_account_id=account,
        owner_subject=subject, tenant_id=owner.tenant_id, ownership="bound", ownership_version=1))
    service = PromotionService.create_default()
    refs, artifacts, contents = [], [], []
    # Nontrivial own facts: zero denominator, categories, lists, missing metric.
    for i, stage in enumerate(("start", "validation", "exit")):
        passport = {"basic_stats": {"n": 19, "mean": [0, 7, 11][i]},
                    "trend": {"direction": ["flat", "up", "down"][i]},
                    "seasonal_periods": {"periods": [[4, 9], [4], [4, 12]][i]},
                    "seasonality": {"is_seasonal": bool(i)},
                    "stationarity": {"applicable": False, "reason": "short-series-cert"},
                    "cert_unknown_group": {"sentinel": "Полная группа 13CERT"}}
        snapid = "cert-physical-" + stage
        art = service._persist(run_id=run, subject=owner, kind="passport",
            producer_key="passport:" + snapid,
            payload={"kind": "passport", "snapshot_id": snapid, "stage": stage,
                     "passport": passport, "fingerprint": "fingerprint-" + stage,
                     "target_column": "visits", "date_column": "month",
                     "passport_schema_version": "passport/1.2", "calculation_version": "cert-known/1"})
        record = S.ReportSnapshot(snapshot_id=S.new_snapshot_id(), research_run_id=run,
            context_id="ctx-cert", data_revision=3, captured_at=f"2026-11-18T09:0{i}:00+00:00",
            kinds=["D02"], idempotency_key="pgv-passport:" + snapid,
            request_fingerprint=stage, dependencies=["artifact:" + art.artifact_id])
        S.get_snapshot_registry().register_snapshot(record, dependencies=[])
        refs.append(record.snapshot_id)
        artifacts.append(art)
        contents.append(passport)
    checkpoints = []
    for i in range(3):
        checkpoint = "pck-cert-confirmation-" + str(i)
        payload = {"schema_version": "pgv.passport_checkpoint/1", "checkpoint_id": checkpoint,
                   "stage": "modeling_entry", "confirmed_at": f"2026-11-18T10:0{i}:00+00:00",
                   "confirmed_at_reason": None, "snapshot_ref": refs[-1] if i == 2 else refs[0],
                   "previous_snapshot_ref": None if i == 2 else refs[-1],
                   "flags": {"created": False, "reused": True, "unchanged": False},
                   "stage_refs": dict(zip(("start", "validation", "exit"), refs)),
                   "context": {"run_id": run, "context_id": "ctx-cert", "data_revision": 3},
                   "provenance": {"source": "producer_capture"}}
        register_passport_checkpoint(run, owner, payload=payload)
        checkpoints.append(checkpoint)
    f = SimpleNamespace(run=run, owner=owner, refs=refs, artifacts=artifacts,
                        contents=contents, checkpoints=checkpoints, unchanged=checkpoints[2], objects=A.get_artifact_object_store())
    try:
        yield f
    finally:
        for reset in resetters:
            reset()
        if db:
            with psycopg.connect(native, autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))


def request(f, **selection):
    from apps.api.passport_documents import request_passport_document
    return request_passport_document(f.run, f.owner, render_requested_at="2026-11-18T12:00:00Z", **selection)


def basis(outcome):
    from apps.api.print_render_payload import load_print_render_input
    return load_print_render_input(outcome["snapshot_artifact_id"])


def ssr(payload):
    code = "const fs=require('node:fs');const r=require('./apps/print-renderer/dist/apps/print-renderer/src/rendererCore.js');const p=JSON.parse(fs.readFileSync(0,'utf8'));const v=r.validateRenderPayload(p);if(v.violations.length)throw new Error(JSON.stringify(v.violations));process.stdout.write(r.buildPrintHtml(p,1,1));"
    return subprocess.check_output(["node", "-e", code], input=json.dumps(payload, ensure_ascii=False), text=True, encoding="utf-8", cwd=ROOT)


def test_all_groups_survive_without_session_or_scientific_calls(facts, monkeypatch):
    import apps.api.session_store as session
    monkeypatch.setattr(session, "get_session_store", lambda: pytest.fail("SessionStore read forbidden"))
    out = request(facts, mode="single", snapshot_refs=[facts.refs[0]])
    record = basis(out)["snapshot"]["display"]["sections"][0]["record"]
    assert record["passport"] == facts.contents[0]
    assert record["source_hash"] == facts.artifacts[0].payload_sha256


def test_exact_request_is_idempotent(facts):
    one = request(facts, mode="single", snapshot_refs=[facts.refs[0]])
    two = request(facts, mode="single", snapshot_refs=[facts.refs[0]])
    assert one["snapshot_artifact_id"] == two["snapshot_artifact_id"]
    assert one["print_revision_id"] == two["print_revision_id"]
    assert one["job"]["job_id"] == two["job"]["job_id"]


@pytest.mark.parametrize("mode", ["single", "set", "compare"])
def test_requested_profile_matches_revision_and_render_payload(facts, mode):
    from apps.api.document_jobs import get_document_registry
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    refs = facts.refs[:1] if mode == "single" else facts.refs[:2]
    request(facts, mode=mode, snapshot_refs=refs, profile_id="figure-landscape")
    out = request(facts, mode=mode, snapshot_refs=refs, profile_id="a4-portrait")
    revision = get_document_registry().get_print_revision(out["print_revision_id"])
    payload = build_print_render_payload_from_basis(basis(out), request_id="cert-profile")
    assert revision.profile_id == "a4-portrait"
    assert payload["snapshot"]["print"]["profile_id"] == revision.profile_id, "F-C13-01: cached figure basis overrides requested A4"


def test_p01_reused_checkpoint_prints_three_records_and_confirmation(facts):
    out = request(facts, mode="set", checkpoint_id=facts.unchanged)
    snap = basis(out)["snapshot"]
    refs = [s["record"]["snapshot_ref"] for s in snap["display"]["sections"] if s.get("renderer_kind") == "passport_record"]
    assert len(refs) == len(set(refs)) == 3, "F-C13-02: reused alias becomes a fourth full printed passport"


def test_p01_confirmation_is_visible_in_compiled_renderer(facts):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    out = request(facts, mode="set", checkpoint_id=facts.unchanged)
    html = ssr(build_print_render_payload_from_basis(basis(out), request_id="cert-confirmation"))
    assert facts.unchanged in html and "2026" in html and "10:02" in html, "F-C13-02: P01 confirmation fact is absent from actual SSR"


def test_different_confirmation_keeps_its_own_frozen_metadata(facts):
    one = request(facts, mode="set", checkpoint_id=facts.checkpoints[0])
    two = request(facts, mode="set", checkpoint_id=facts.checkpoints[1])
    assert one["checkpoint_id"] != two["checkpoint_id"]
    for key in ("snapshot_artifact_id", "print_revision_id"):
        assert one[key] != two[key]
    assert one["job"]["job_id"] != two["job"]["job_id"]
    assert basis(two)["snapshot"]["checkpoint"]["checkpoint_id"] == two["checkpoint_id"], "F-C13-03: second checkpoint silently reuses first confirmation"


def test_historical_refs_do_not_follow_newest_record(facts):
    out = request(facts, mode="compare", checkpoint_id=facts.checkpoints[0])
    comp = basis(out)["snapshot"]["display"]["sections"][0]["comparison"]
    # Return to the start state is a logical alias in P02, not an unchanged
    # exit handoff. Verify its exact historical path, not latest-stage guesses.
    assert comp["ordered_refs"] == facts.refs + [facts.refs[0]]
    assert comp["confirmation"]["reused"] is True
    assert comp["confirmation"]["confirmed_at"] == "2026-11-18T10:00:00+00:00"
    assert comp["comparisons"] and comp["definitions"]
    pair = comp["comparisons"][0]["comparison"]
    assert pair["metrics"]["Среднее"]["delta"] == 7
    assert pair["metrics"]["Среднее"]["delta_pct"] == 100
    assert "не определено" in comp["definitions"]["zero_denominator_reason"]
    assert pair["categorical_changes"]["Направление тренда"]["v_new"] == "up"
    assert pair["list_changes"]["Сезонные периоды (ACF)"]["removed"] == [9]
    assert pair["qualitative_changes"]


def test_actual_foreign_principal_and_missing_run_uniform_denial(facts):
    from dataclasses import replace
    from apps.api.passport_documents import PassportDocumentAccessDenied, request_passport_document
    stranger = replace(facts.owner, account_id=str(uuid4()), subject_id=str(uuid4()))
    for run, actor in ((facts.run, stranger), ("RUN-C13NONE0", facts.owner)):
        with pytest.raises(PassportDocumentAccessDenied):
            request_passport_document(run, actor, mode="single", snapshot_refs=facts.refs[:1], render_requested_at="2026-11-18T12:00:00Z")


def test_missing_reference_is_gap_and_single_is_unavailable(facts):
    from apps.api.passport_documents import PassportDocumentSourceUnavailable
    missing = "rs-" + "d" * 32
    with pytest.raises(PassportDocumentSourceUnavailable):
        request(facts, mode="single", snapshot_refs=[missing])
    out = request(facts, mode="set", snapshot_refs=[facts.refs[0], missing])
    snap = basis(out)["snapshot"]
    assert snap["display"]["completeness"] == "partial"
    assert snap["display"]["sections"][1]["record"]["passport"] is None


def test_corrupt_source_never_exposes_passport(facts, monkeypatch):
    from apps.api.passport_documents import PassportDocumentSourceUnavailable
    original = facts.objects.read_bytes
    def damaged(key, *args, **kwargs):
        return b'{"damaged":true}' if key == facts.artifacts[0].storage_key else original(key, *args, **kwargs)
    monkeypatch.setattr(facts.objects, "read_bytes", damaged)
    with pytest.raises(PassportDocumentSourceUnavailable):
        request(facts, mode="single", snapshot_refs=[facts.refs[0]])


def test_valid_renderer_html_preserves_all_groups(facts):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    out = request(facts, mode="single", snapshot_refs=facts.refs[:1])
    html = ssr(build_print_render_payload_from_basis(basis(out), request_id="cert-content"))
    for text in ("Полная группа 13CERT", "short-series-cert", "Базовые статистики", "visits"):
        assert text in html


@pytest.mark.parametrize("mode", ["single", "set", "compare"])
def test_python_payload_passes_actual_compiled_renderer(facts, mode):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    out = request(facts, mode=mode, snapshot_refs=facts.refs[:1 if mode == "single" else 2])
    payload = build_print_render_payload_from_basis(basis(out), request_id="cert-real-envelope")
    # No hand-written V01 fixture or injected fields: exact Python production input.
    assert ("Сравнение паспортов" if mode == "compare" else "Паспорт") in ssr(payload), "F-C13-00: real Python P01/P02 input is not renderable"


@pytest.mark.parametrize("mode", ["single", "set", "compare"])
def test_new_builder_does_not_reuse_legacy_frozen_basis(facts, mode):
    """A valid immutable old cache entry must survive, but cannot poison v2."""
    from apps.api.artifact_promotion import PromotionService
    import hashlib

    def legacy_digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    from apps.api.passport_history import read_passport_snapshot
    refs = facts.refs[:1 if mode == "single" else 2]
    out = request(facts, mode=mode, snapshot_refs=refs)
    frozen = basis(out)["snapshot"]
    if mode == "compare":
        c = frozen["display"]["sections"][0]["comparison"]
        digest = legacy_digest({"mode": c.get("mode"), "ordered_refs": refs,
            "engine": c["method_versions"]["engine"], "confirmation": c.get("confirmation"),
            "checkpoint_ref": (c.get("checkpoint") or {}).get("checkpoint_ref")})
        prefix, kind = "pgv.passport_comparison_print", "passport_comparison_snapshot"
    else:
        records = [read_passport_snapshot(facts.run, facts.owner, snapshot_ref=r) for r in refs]
        digest = legacy_digest([{key: r.get(key) for key in ("snapshot_ref", "content_status",
            "content_gap_reason", "source_hash", "source_hash_reason", "fingerprint",
            "fingerprint_reason", "stage")} for r in records])
        prefix, kind = "pgv.passport_print", "passport_print_snapshot"
    key = f"{prefix}:{mode}:{','.join(refs)}:{digest[:16]}"
    service = PromotionService.create_default()
    # Seed the historical producer key using the immutable persistence seam.
    legacy = service.find_by_producer(facts.run, key)
    if legacy is None:
        old_payload = json.loads(json.dumps(frozen))
        old_payload["identity"].pop("builder_version", None)
        old_payload["identity"]["digest"] = digest
        for field in ("sampling", "result", "warnings"):
            old_payload.pop(field, None)
        legacy = service._persist(run_id=facts.run, subject=facts.owner, kind=kind,
            producer_key=key, payload=old_payload)
    from apps.api.document_jobs import DocumentDeliveryService
    delivery = DocumentDeliveryService.create_default()
    _, old_revision, _ = delivery.ensure_print_document_revision(
        facts.run, facts.owner, print_kind="P02" if mode == "compare" else "P01",
        basis_kind=kind, basis_artifact_ids=[legacy.artifact_id], profile_id="figure-landscape")
    old_job, _ = delivery.request_print_rendition(old_revision.print_revision_id,
        format="png", subject=facts.owner)
    before = facts.objects.read_bytes(legacy.storage_key)
    again = request(facts, mode=mode, snapshot_refs=refs)
    assert again["snapshot_artifact_id"] != legacy.artifact_id
    assert again["print_revision_id"] != old_revision.print_revision_id
    assert again["job"]["job_id"] != old_job.job_id
    assert again["snapshot_artifact_id"] == out["snapshot_artifact_id"]
    assert facts.objects.read_bytes(legacy.storage_key) == before
    assert len(__import__("apps.api.artifact_store", fromlist=["get_artifact_registry"])
               .get_artifact_registry().list_artifacts(facts.run, kind="passport")) == 3


def test_confirmed_source_is_exact_alias_not_latest(facts):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    out = request(facts, mode="set", checkpoint_id=facts.checkpoints[0])
    snap = basis(out)["snapshot"]
    assert snap["checkpoint"]["source_snapshot_ref"] == facts.refs[0]
    assert snap["checkpoint"]["reused"] is True
    assert snap["times"]["checkpoint_confirmed_at"] == "2026-11-18T10:00:00+00:00"
    html = ssr(build_print_render_payload_from_basis(basis(out), request_id="source-alias"))
    assert facts.checkpoints[0] in html and facts.refs[0] in html
    assert html.count("Полная группа 13CERT") == 3


def test_retry_time_does_not_change_basis_revision_or_job(facts):
    from apps.api.passport_documents import request_passport_document
    one = request(facts, mode="set", checkpoint_id=facts.unchanged)
    two = request_passport_document(facts.run, facts.owner, mode="set", checkpoint_id=facts.unchanged,
                                   render_requested_at="2026-11-19T12:00:00Z")
    for key in ("snapshot_artifact_id", "print_revision_id"):
        assert one[key] == two[key]
    assert one["job"]["job_id"] == two["job"]["job_id"]


def test_envelope_does_not_fabricate_scientific_times(facts):
    snap = basis(request(facts, mode="set", snapshot_refs=facts.refs))["snapshot"]
    assert snap["sampling"]["applicable"] is False
    assert snap["sampling"]["reason"]
    assert snap["warnings"] == []
    for field in ("computed_at", "captured_at"):
        assert snap["times"][field] is None
        assert snap["times"][field + "_reason"]
    from datetime import datetime
    assert [datetime.fromisoformat(s["record"]["captured_at"]) for s in snap["display"]["sections"]] == [
        datetime.fromisoformat(f"2026-11-18T09:0{i}:00+00:00") for i in range(3)]


def test_confirmation_missing_time_and_source_are_visible_reasons(facts):
    from apps.api.passport_documents import build_passport_print_snapshot
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    record = basis(request(facts, mode="single", snapshot_refs=facts.refs[:1]))["snapshot"]["display"]["sections"][0]["record"]
    snap = build_passport_print_snapshot(facts.run, [record], mode="set", profile_id="figure-landscape",
        render_requested_at="2026-11-19T00:00:00Z", checkpoint_meta={
            "checkpoint_id": "pck-legacy-cert", "stage": "modeling_entry",
            "reused": False, "flags": {"created": True, "reused": False},
            "confirmed_at": None, "confirmed_at_reason": "legacy_unknown_time_cert",
            "source_snapshot_ref": None, "source_snapshot_ref_reason": "legacy_unknown_source_cert"})
    html = ssr(build_print_render_payload_from_basis({"snapshot": snap, "basis_kind": "passport_print_snapshot"}, request_id="legacy-confirmation"))
    for text in ("pck-legacy-cert", "legacy_unknown_time_cert", "legacy_unknown_source_cert"):
        assert text in html


def test_confirmed_source_survives_partial_stage_path(facts):
    """A source resolved outside stage_refs keeps its physical stage key.
    Its checkpoint stage need not be a key of trajectory.snapshots.
    """
    from apps.api.visual_artifacts import register_passport_checkpoint
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    checkpoint = "pck-cert-partial-source"
    register_passport_checkpoint(facts.run, facts.owner, payload={
        "schema_version": "pgv.passport_checkpoint/1", "checkpoint_id": checkpoint,
        "stage": "modeling_entry", "confirmed_at": "2026-11-18T11:00:00Z",
        "confirmed_at_reason": None, "snapshot_ref": facts.refs[0],
        "previous_snapshot_ref": facts.refs[-1],
        "flags": {"created": False, "reused": True, "unchanged": False},
        "stage_refs": {"start": "rs-" + "d" * 32, "validation": facts.refs[1], "exit": facts.refs[2]},
        "context": {"run_id": facts.run, "context_id": "ctx-cert", "data_revision": 3},
        "provenance": {"source": "producer_capture"}})
    out = request(facts, mode="set", checkpoint_id=checkpoint)
    snap = basis(out)["snapshot"]
    assert snap["checkpoint"]["source_snapshot_ref"] == facts.refs[0]
    html = ssr(build_print_render_payload_from_basis(basis(out), request_id="partial-source"))
    assert facts.refs[0] in html and checkpoint in html
    assert html.count("Полная группа 13CERT") == 3
