"""Acceptance oracle: intentionally RED on 389b930 for revision zero.

This diagnostic file is opt-in; it does not change default local gates.
The revision-seven case is the positive control used by PGV-10 fixtures.
"""
from types import SimpleNamespace

import pytest

from tests.api.test_pgv10_visual_exports import (
    CONTEXT_ID, RUN_ID, _frozen_visual_result, _isolated_environment,
    _now, _seed_run, _seed_session_object,
)


@pytest.mark.parametrize("revision", [0, 7])
def test_existing_data_revision_survives_print_snapshot(revision):
    from apps.api.visual_exports import build_visual_print_snapshot
    _seed_run(data_revision=revision)
    _seed_session_object()
    artifact = SimpleNamespace(artifact_id="art-" + "1" * 32, context_id=CONTEXT_ID,
                               data_revision=revision, created_at=_now())
    snapshot = build_visual_print_snapshot(
        RUN_ID, site_view_id="upload.overview.tech_table", result_artifact=artifact,
        result_payload=_frozen_visual_result(), profile_id="figure-landscape",
        render_requested_at=_now(),
    )
    assert snapshot["data_artifact"]["artifact_version"] == str(revision)
