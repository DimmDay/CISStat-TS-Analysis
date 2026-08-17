from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from apps.api.routers import diagnostics_internal


class FakeStore:
    def __init__(self, session):
        self.session = session

    def get_or_create(self, session_id):
        return self.session


def _request_response():
    return SimpleNamespace(), SimpleNamespace()


def test_internal_diagnostics_uses_session_target_and_real_ets(monkeypatch):
    series = np.linspace(100.0, 140.0, 48) + np.sin(np.arange(48))
    session = SimpleNamespace(
        dataframe=pd.DataFrame({"value": series}),
        target_column="value",
    )
    monkeypatch.setattr(diagnostics_internal, "get_or_create_session_id", lambda request, response: "test-session")
    monkeypatch.setattr(diagnostics_internal, "get_session_store", lambda: FakeStore(session))

    request, response = _request_response()
    result = diagnostics_internal.run_internal_diagnostics(
        diagnostics_internal.InternalDiagnosticsRequest(model_id="ets", params={}),
        request,
        response,
    )

    assert result.model_id == "ets"
    assert result.target_column == "value"
    assert result.n_observations == 48
    assert result.residuals_count >= 8
    assert {item.test for item in result.diagnostics} == {
        "ljung_box", "jarque_bera", "arch_lm", "durbin_watson"
    }


def test_internal_diagnostics_rejects_missing_target(monkeypatch):
    session = SimpleNamespace(dataframe=pd.DataFrame({"value": [1.0, 2.0, 3.0]}), target_column=None)
    monkeypatch.setattr(diagnostics_internal, "get_or_create_session_id", lambda request, response: "test-session")
    monkeypatch.setattr(diagnostics_internal, "get_session_store", lambda: FakeStore(session))

    from fastapi import HTTPException

    request, response = _request_response()
    with pytest.raises(HTTPException) as exc_info:
        diagnostics_internal.run_internal_diagnostics(
            diagnostics_internal.InternalDiagnosticsRequest(model_id="ets"),
            request,
            response,
        )
    assert exc_info.value.status_code == 400
    assert "Target column" in str(exc_info.value.detail)


def test_internal_diagnostics_rejects_non_numeric_target(monkeypatch):
    session = SimpleNamespace(dataframe=pd.DataFrame({"value": ["a", "b", "c"]}), target_column="value")
    monkeypatch.setattr(diagnostics_internal, "get_or_create_session_id", lambda request, response: "test-session")
    monkeypatch.setattr(diagnostics_internal, "get_session_store", lambda: FakeStore(session))

    from fastapi import HTTPException

    request, response = _request_response()
    with pytest.raises(HTTPException) as exc_info:
        diagnostics_internal.run_internal_diagnostics(
            diagnostics_internal.InternalDiagnosticsRequest(model_id="ets"),
            request,
            response,
        )
    assert exc_info.value.status_code == 422
    assert "numeric" in str(exc_info.value.detail)
