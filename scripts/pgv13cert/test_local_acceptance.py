"""Step 3: additional independent durable/SSR oracles on our own stored facts.

No author-test fixtures, DataFrame, xfail, diagnostic envelope or fake renderer.
"""
from dataclasses import replace
from uuid import uuid4

import pytest

from scripts.pgv13cert.test_contracts import facts, request, basis, ssr


def seed(f, *, stage='exit', target='visits', schema='passport/1.2', foreign=False):
    from apps.api.artifact_promotion import PromotionService
    from apps.api import research_runs as R, report_snapshot as S
    run = 'RUN-C13B0002' if foreign else f.run
    owner = replace(f.owner, account_id=str(uuid4()), subject_id=str(uuid4())) if foreign else f.owner
    if foreign:
        R.get_research_run_store().upsert_run(R.ResearchRun(
            run_id=run, session_id='other-private-session', owner_account_id=owner.account_id,
            owner_subject=owner.subject_id, tenant_id=owner.tenant_id,
            ownership='bound', ownership_version=1))
    physical = 'cert-late-'+uuid4().hex
    artifact = PromotionService.create_default()._persist(
        run_id=run, subject=owner, kind='passport', producer_key='passport:'+physical,
        payload={'kind': 'passport', 'snapshot_id': physical, 'stage': stage,
                 'passport': {'basic_stats': {'n': 91, 'mean': 991},
                              'cert_unknown_group': {'sentinel': 'PRIVATE-C13-FOREIGN' if foreign else 'LATE-C13-991'}},
                 'target_column': target, 'date_column': 'month',
                 'passport_schema_version': schema, 'fingerprint': physical,
                 'calculation_version': 'cert-known/1'})
    snapshot = S.ReportSnapshot(snapshot_id=S.new_snapshot_id(), research_run_id=run,
        context_id='ctx-cert-later', data_revision=9, captured_at='2026-11-20T12:00:00Z',
        kinds=['D02'], idempotency_key='pgv-passport:'+physical,
        request_fingerprint=physical, dependencies=['artifact:'+artifact.artifact_id])
    S.get_snapshot_registry().register_snapshot(snapshot, dependencies=[])
    return snapshot.snapshot_id


def render(outcome):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    return ssr(build_print_render_payload_from_basis(basis(outcome), request_id='local-exact-payload'))


@pytest.mark.parametrize('mode', ['single', 'set', 'compare'])
def test_registry_reload_preserves_basis_revision_and_job(facts, mode):
    from apps.api import research_runs as R, artifact_store as A, report_snapshot as S, document_jobs as D
    refs = facts.refs[:1] if mode == 'single' else facts.refs
    one = request(facts, mode=mode, snapshot_refs=refs)
    if isinstance(R.get_research_run_store(), R.PostgresResearchRunStore):
        # Reopen actual PG registries/connections; Memory has no process durability claim.
        for reset in [R.reset_research_run_store_for_testing, A.reset_artifact_registry_for_testing,
                      S.reset_snapshot_registry_for_testing, D.reset_document_registry_for_testing]:
            reset()
    two = request(facts, mode=mode, snapshot_refs=refs)
    assert [two[k] for k in ['snapshot_artifact_id', 'print_revision_id']] == [one[k] for k in ['snapshot_artifact_id', 'print_revision_id']]
    assert two['job']['job_id'] == one['job']['job_id']
    assert render(two) == render(one)


@pytest.mark.parametrize('mode', ['single', 'set', 'compare'])
@pytest.mark.parametrize('damage', ['missing_bytes', 'corrupt_bytes'])
def test_lost_or_corrupt_object_is_gap_without_invented_content(facts, mode, damage):
    from apps.api.passport_documents import PassportDocumentSourceUnavailable
    path = facts.objects.path_for_key(facts.artifacts[1].storage_key)
    if damage == 'missing_bytes':
        path.unlink()
    else:
        path.write_bytes(b'{"passport":{"secret":"CORRUPT-C13-MUST-NOT-PRINT"}}')
    if mode == 'single':
        with pytest.raises(PassportDocumentSourceUnavailable):
            request(facts, mode=mode, snapshot_refs=[facts.refs[1]])
        return
    out = request(facts, mode=mode, snapshot_refs=facts.refs)
    snap = basis(out)['snapshot']
    assert snap['display']['completeness'] == 'partial'
    if mode == 'set':
        damaged = snap['display']['sections'][1]['record']
        assert damaged['snapshot_ref'] == facts.refs[1]
        assert damaged['content_status'] == 'corrupt' and damaged['passport'] is None
        assert damaged['content_gap_reason']
        assert render(out).count('Полная группа 13CERT') == 2
    else:
        comparison = snap['display']['sections'][0]['comparison']
        assert comparison['gaps'] and comparison['comparisons'] == []
    assert 'CORRUPT-C13-MUST-NOT-PRINT' not in render(out)


@pytest.mark.parametrize('mode', ['single', 'set', 'compare'])
def test_foreign_ref_has_same_safe_result_as_missing_ref(facts, mode):
    from apps.api.passport_documents import PassportDocumentSourceUnavailable
    foreign = seed(facts, foreign=True)
    missing = 'rs-'+'e'*32
    results = []
    for ref in [foreign, missing]:
        if mode == 'single':
            with pytest.raises(PassportDocumentSourceUnavailable) as error:
                request(facts, mode=mode, snapshot_refs=[ref])
            results.append(str(error.value))
        else:
            out = request(facts, mode=mode, snapshot_refs=[facts.refs[0], ref])
            snap = basis(out)['snapshot']
            assert snap['display']['completeness'] == 'partial'
            html = render(out)
            assert 'PRIVATE-C13-FOREIGN' not in html and 'RUN-C13B0002' not in html
            if mode == 'set':
                record = snap['display']['sections'][1]['record']
                assert record['passport'] is None
                results.append((record['content_status'], record['content_gap_reason']))
            else:
                comparison = snap['display']['sections'][0]['comparison']
                assert comparison['comparisons'] == []
                results.append([(g['reason'], g.get('detail')) for g in comparison['gaps']])
    assert results[0] == results[1]


@pytest.mark.parametrize('change,reason', [({'target': 'other'}, 'target_mismatch'),
                                         ({'schema': 'passport/9'}, 'schema_mismatch'),
                                         ({'stage': 'panel_entry'}, 'universe_mixing')])
def test_incompatible_passports_refuse_before_print_persistence(facts, change, reason):
    from apps.api.passport_documents import PassportDocumentIncompatible
    from apps.api.artifact_store import get_artifact_registry
    other = seed(facts, **change)
    if reason == 'universe_mixing':
        from apps.api.passport_history import read_passport_snapshot
        assert read_passport_snapshot(facts.run, facts.owner, snapshot_ref=other)['universe'] == 'panel'
    before = get_artifact_registry().list_artifacts(facts.run)
    with pytest.raises(PassportDocumentIncompatible) as error:
        request(facts, mode='compare', snapshot_refs=[facts.refs[0], other])
    assert any(r.startswith(reason+':') for r in error.value.reasons)
    assert get_artifact_registry().list_artifacts(facts.run) == before


def test_later_same_stage_cannot_replace_historical_checkpoint(facts):
    late = seed(facts)
    out = request(facts, mode='set', checkpoint_id=facts.unchanged)
    records = [s['record'] for s in basis(out)['snapshot']['display']['sections']]
    assert [r['snapshot_ref'] for r in records] == facts.refs
    assert late not in [r['snapshot_ref'] for r in records]
    assert 'LATE-C13-991' not in render(out)
    comp = request(facts, mode='compare', checkpoint_id=facts.checkpoints[0])
    payload = basis(comp)['snapshot']['display']['sections'][0]['comparison']
    assert payload['ordered_refs'] == facts.refs+[facts.refs[0]]
    assert payload['comparisons'][0]['comparison']['metrics']['Среднее']['delta'] == 7


@pytest.mark.parametrize('mode', ['single', 'set', 'compare'])
def test_already_frozen_print_survives_loss_of_source_objects(facts, mode):
    refs = facts.refs[:1] if mode == 'single' else facts.refs
    out = request(facts, mode=mode, snapshot_refs=refs)
    original = render(out)
    for artifact in facts.artifacts:
        facts.objects.path_for_key(artifact.storage_key).unlink()
    # Loading the issued immutable basis must not re-read the missing science objects.
    assert render(out) == original
