"""PGV-PNG-FIX: initial upload freezes its visible response; zero is a version."""
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from starlette.requests import Request
from starlette.responses import Response

from tests.api.test_pgv10_visual_exports import (
    CONTEXT_ID, RUN_ID, SESSION_ID, _frozen_visual_result,
    _isolated_environment, _now, _seed_run, _seed_session_object,
)


@pytest.mark.parametrize("revision", [0, 7])
def test_zero_and_later_data_versions_survive_snapshot(revision):
    from apps.api.visual_exports import build_visual_print_snapshot
    _seed_run(data_revision=revision)
    _seed_session_object()
    artifact = SimpleNamespace(artifact_id="art-" + "a" * 32, context_id=CONTEXT_ID,
                               data_revision=revision, created_at=_now())
    snapshot = build_visual_print_snapshot(
        RUN_ID, site_view_id="upload.overview.tech_table", result_artifact=artifact,
        result_payload=_frozen_visual_result(), profile_id="figure-landscape",
        render_requested_at=_now(),
    )
    assert snapshot["data_artifact"]["artifact_version"] == str(revision)
    from apps.api.visual_artifacts import validate_visual_artifact_payload
    assert not validate_visual_artifact_payload("visual_print_snapshot", snapshot)


def test_missing_version_is_still_rejected():
    from apps.api.visual_exports import build_visual_print_snapshot
    from apps.api.visual_artifacts import validate_visual_artifact_payload
    _seed_run()
    _seed_session_object()
    artifact = SimpleNamespace(artifact_id="art-" + "b" * 32, context_id=CONTEXT_ID,
                               data_revision=None, created_at=_now())
    snapshot = build_visual_print_snapshot(
        RUN_ID, site_view_id="upload.overview.tech_table", result_artifact=artifact,
        result_payload=_frozen_visual_result(), profile_id="figure-landscape",
        render_requested_at=_now(),
    )
    assert any(v.code == "missing_data_version" for v in
               validate_visual_artifact_payload("visual_print_snapshot", snapshot))


@pytest.mark.parametrize("source", ["file", "database"])
def test_common_upload_freezes_final_visible_response(source):
    from apps.api.upload_common import register_uploaded_dataframe
    from apps.api.promotion_integration import notify_visual_result
    from apps.api.visual_artifacts import list_visual_results
    from apps.api.visual_exports import _artifact_payload
    _seed_run()
    _seed_session_object()
    request = Request({"type": "http", "method": "POST", "path": "/upload",
                       "headers": [(b"cookie", f"cisstat_session_id={SESSION_ID}".encode())]})
    response = Response()
    df = pd.DataFrame({"date": ["2026-01-01", "2026-02-01"], "value": [11.0, 23.0]})
    warnings = ["database selection truncated"] if source == "database" else None
    with patch("apps.api.promotion_integration.notify_visual_result", wraps=notify_visual_result) as notify:
        result = register_uploaded_dataframe(
            df, name=source, size_label="1 KB", request=request, response=response,
            dataset_fingerprint="" if source == "database" else "f" * 64,
            extra_parse_warnings=warnings,
        )
    notify.assert_called_once()
    assert notify.call_args.kwargs["response"] == result.model_dump(mode="json")
    assert response.headers["X-Visual-Result-Ref"]
    from apps.api.session_store import get_session_store
    session = get_session_store().get(SESSION_ID)
    artifacts = list_visual_results(session.run_id)
    assert {a.refs["view_id"] for a in artifacts} == {
        "upload.overview.preview", "upload.overview.tech_table", "upload.quality.teaser",
    }
    assert {a.data_revision for a in artifacts} == {0}
    preview = next(a for a in artifacts if a.refs["view_id"] == "upload.overview.preview")
    assert "11.0" in str(_artifact_payload(preview)["payload"]["data"])
    if warnings:
        assert warnings[0] in result.parse_warnings


def test_freeze_failure_keeps_successful_upload_and_records_receipt():
    from apps.api.upload_common import register_uploaded_dataframe
    from apps.api.visual_artifacts import list_visual_results
    _seed_run()
    _seed_session_object()
    request = Request({"type": "http", "method": "POST", "path": "/upload",
                       "headers": [(b"cookie", f"cisstat_session_id={SESSION_ID}".encode())]})
    with patch("apps.api.visual_producers.freeze_visual_from_response", side_effect=RuntimeError("test-only store outage")), \
         patch("apps.api.promotion_integration._record_failure") as failure:
        result = register_uploaded_dataframe(
            pd.DataFrame({"date": ["2026-01-01"], "value": [11.0]}),
            name="outage", size_label="1 KB", request=request, response=Response(),
        )
    assert result.rows == 1 and result.error is None
    assert failure.call_count == 3
    assert {c.kwargs["operation"] for c in failure.call_args_list} == {
        "freeze_visual:upload.overview.preview", "freeze_visual:upload.overview.tech_table",
        "freeze_visual:upload.quality.teaser",
    }
    from apps.api.session_store import get_session_store
    assert not list_visual_results(get_session_store().get(SESSION_ID).run_id)


@pytest.mark.parametrize("status,code", [(503, "worker_service_unavailable"), (429, "concurrency_exceeded"),
                                         (402, "quota_exceeded"), (401, "authentication_required")])
@pytest.mark.parametrize("kind", ["visuals", "passport-documents"])
def test_export_preserves_only_trusted_authority_failures(status, code, kind):
    from apps.api.authentication.context import AuthHTTPException
    from tests.api.test_pgv10_visual_exports import _client_post_json
    _seed_run()
    module = "visual_exports" if kind == "visuals" else "passport_documents"
    func = "request_visual_export" if kind == "visuals" else "request_passport_document"
    with patch(f"apps.api.{module}.{func}", side_effect=AuthHTTPException(
        status_code=status, headers={"Cache-Control": "no-store"},
        detail={"code": code, "message": "safe domain message"},
    )):
        response = _client_post_json(f"/v1/documentation/runs/{RUN_ID}/{kind}",
                                     {"view_id": "upload.overview.tech_table", "mode": "single"})
    assert response["status"] == status
    assert response["data"]["detail"]["code"] == code


@pytest.mark.parametrize("kind", ["visuals", "passport-documents"])
def test_arbitrary_http_exception_still_has_safe_export_envelope(kind):
    from fastapi import HTTPException
    from tests.api.test_pgv10_visual_exports import _client_post_json
    _seed_run()
    module = "visual_exports" if kind == "visuals" else "passport_documents"
    func = "request_visual_export" if kind == "visuals" else "request_passport_document"
    with patch(f"apps.api.{module}.{func}", side_effect=HTTPException(
        status_code=502, detail="private upstream response must stay private",
    )):
        response = _client_post_json(f"/v1/documentation/runs/{RUN_ID}/{kind}",
                                     {"view_id": "upload.overview.tech_table", "mode": "single"})
    assert response["status"] == 503
    assert "private upstream" not in str(response["data"])
    assert response["data"]["code"] == (
        "visual_export_unavailable" if kind == "visuals" else "passport_document_unavailable"
    )
