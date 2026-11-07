"""Lazy export must carry the caller, never synthesize Account ownership."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.api import visual_exports


def test_account_run_cannot_synthesize_legacy_owner():
    run = SimpleNamespace(
        owner_account_id="account", owner_subject="original", session_id="pointer"
    )
    with (
        patch(
            "apps.api.research_runs.get_research_run_store",
            return_value=SimpleNamespace(get_run=lambda _: run),
        ),
        pytest.raises(visual_exports.VisualExportAccessDenied),
    ):
        visual_exports._system_subject_for("RUN-A0900001")


def test_lazy_export_passes_actual_member():
    actor = object()
    artifact = SimpleNamespace(refs={"result_ref": "saved-ref"})
    freeze = Mock()
    with (
        patch("apps.api.visual_producers.freeze_saved_visual", freeze),
        patch.object(visual_exports, "list_visual_results", return_value=[artifact]),
        patch.object(
            visual_exports,
            "_system_subject_for",
            side_effect=AssertionError("impersonation"),
        ),
    ):
        assert visual_exports._freeze_saved_fallback(
            "RUN-A0900001", "view", "saved-ref", subject=actor
        ) == [artifact]
    assert freeze.call_args.args[1] is actor
