from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload(df: pd.DataFrame, filename: str = "dataset.csv") -> None:
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": (filename, buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _df_with_outlier():
    return pd.DataFrame({
        "Price": [10.0] * 20 + [1000.0],
        "Region": ["A", "B"] * 10 + ["A"],
    })


def test_profile_reports_every_numeric_column_including_zero_outliers():
    _upload(pd.DataFrame({
        "Price": [10.0] * 20 + [1000.0],
        "Clean": list(range(1, 22)),
        "Region": ["A", "B"] * 10 + ["A"],
    }))

    profile = client.get("/v1/session/dataset/outlier-profile")
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["rule_source"] == "system"
    assert body["method"] == "iqr"
    columns = {item["column"]: item for item in body["columns"]}
    assert "Region" not in columns  # нечисловая -- не входит в профиль
    assert columns["Price"]["outlier_count"] == 1
    assert columns["Clean"]["outlier_count"] == 0


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/outlier-profile").status_code == 404
    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Price"], "strategy": "cap", "method": "iqr", "apply": False},
    )
    assert response.status_code == 404


def test_preview_does_not_mutate_session_dataset():
    _upload(_df_with_outlier())

    preview = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Price"], "strategy": "cap", "method": "iqr", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_changed"] == 1

    unchanged = client.get("/v1/session/dataset/outlier-profile").json()
    assert unchanged["columns"][0]["outlier_count"] == 1


def test_apply_persists_correction_and_profile_reflects_it():
    _upload(_df_with_outlier())

    applied = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Price"], "strategy": "cap", "method": "iqr", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"][0]["outlier_count"] == 0

    profile = client.get("/v1/session/dataset/outlier-profile").json()
    assert profile["columns"][0]["outlier_count"] == 0
    assert profile["total_outliers"] == 0


def test_drop_rows_updates_session_dataset_metadata():
    _upload(_df_with_outlier())

    applied = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Price"], "strategy": "drop_rows", "method": "iqr", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rows_removed"] == 1

    current = client.get("/v1/session/current").json()
    assert current["dataset"]["rows"] == 20


def test_unknown_column_returns_422_without_mutating_session():
    _upload(_df_with_outlier())

    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Nope"], "strategy": "cap", "method": "iqr", "apply": True},
    )
    assert response.status_code == 422

    profile = client.get("/v1/session/dataset/outlier-profile").json()
    assert profile["columns"][0]["outlier_count"] == 1  # сессия не изменилась


def test_non_numeric_column_returns_422():
    _upload(_df_with_outlier())
    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["Region"], "strategy": "cap", "method": "iqr", "apply": False},
    )
    assert response.status_code == 422


# ── Режимы (та же политика, что у «Пропусков») ──


def test_default_mode_is_auto_and_status_reflects_real_data():
    _upload(_df_with_outlier())
    profile = client.get("/v1/session/dataset/outlier-profile").json()
    assert profile["mode"] == "auto"
    assert profile["status"] == "warning"


def test_disabled_mode_is_skipped_and_excluded_from_status():
    _upload(_df_with_outlier())
    put = client.put("/v1/session/dataset/preprocessing-check-modes", json={"modes": {"outliers": "disabled"}})
    assert put.status_code == 200, put.text

    profile = client.get("/v1/session/dataset/outlier-profile").json()
    assert profile["mode"] == "disabled"
    assert profile["status"] == "skipped"
    assert profile["status_reason"] == "disabled"
    assert profile["total_outliers"] == 1  # данные по-прежнему честны


def test_percentile_method_uses_query_params():
    _upload(pd.DataFrame({"Price": [float(v) for v in range(1, 101)]}))
    response = client.get(
        "/v1/session/dataset/outlier-profile",
        params={"method": "percentile", "param_low": 5, "param_high": 95},
    )
    assert response.status_code == 200, response.text
    assert response.json()["columns"][0]["outlier_count"] > 0


# ── Обнаружение на остатке STL-декомпозиции ──


def _seasonal_dataset_with_shock():
    dates = pd.date_range("2020-01-01", periods=48, freq="MS")
    rng = np.random.default_rng(0)
    seasonal = 10 * np.sin(np.arange(48) * 2 * np.pi / 12)
    trend = np.linspace(0, 5, 48)
    values = 100 + trend + seasonal + rng.normal(0, 0.5, 48)
    values[30] += 50
    return pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "value": values})


def test_use_residual_detects_shock_that_raw_iqr_might_miss():
    _upload(_seasonal_dataset_with_shock())

    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={
            "columns": ["value"], "strategy": "flag", "method": "iqr",
            "use_residual": True, "date_column": "date", "apply": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_outliers"] >= 1


def test_use_residual_requires_date_column():
    _upload(_seasonal_dataset_with_shock())
    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "flag", "method": "iqr", "use_residual": True, "apply": False},
    )
    assert response.status_code == 422


def test_use_residual_rejects_multiple_columns():
    _upload(_seasonal_dataset_with_shock())
    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={
            "columns": ["value", "value"], "strategy": "flag", "method": "iqr",
            "use_residual": True, "date_column": "date", "apply": False,
        },
    )
    assert response.status_code == 422


def test_use_residual_returns_422_for_panel_data_not_500():
    _upload(pd.DataFrame({
        "date": ["2020-01-01", "2020-01-01", "2020-02-01", "2020-02-01"] * 5,
        "value": [float(i) for i in range(20)],
    }))
    response = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={
            "columns": ["value"], "strategy": "flag", "method": "iqr",
            "use_residual": True, "date_column": "date", "apply": False,
        },
    )
    assert response.status_code == 422
    assert "Декомпозиция недоступна" in response.json()["detail"]


# ── Визуализации (Линейный / Гистограмма / Плотность / Boxplot) ──


def test_outlier_line_returns_scatter_points():
    _upload(_df_with_outlier())
    response = client.get("/v1/session/dataset/outlier-line", params={"column": "Price"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["original_count"] == 21
    assert len(body["points"]) == 21


def test_outlier_histogram_reports_bins_and_bounds():
    _upload(_df_with_outlier())
    response = client.get("/v1/session/dataset/outlier-histogram", params={"column": "Price", "method": "iqr"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["bins"]) > 0
    assert body["bounds"] is not None
    assert body["bounds"]["upper"] < 1000.0


def test_outlier_density_returns_kde_points():
    _upload(_df_with_outlier())
    response = client.get("/v1/session/dataset/outlier-density", params={"column": "Price"})
    assert response.status_code == 200, response.text
    assert response.json()["points"] is not None


def test_outlier_boxplot_splits_outliers_and_normal():
    _upload(_df_with_outlier())
    response = client.get("/v1/session/dataset/outlier-boxplot", params={"column": "Price", "method": "iqr"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outliers"]["count"] == 1
    assert body["normal"]["count"] == 20


def test_visualization_endpoints_404_without_dataset():
    assert client.get("/v1/session/dataset/outlier-line", params={"column": "Price"}).status_code == 404
    assert client.get("/v1/session/dataset/outlier-histogram", params={"column": "Price"}).status_code == 404
    assert client.get("/v1/session/dataset/outlier-density", params={"column": "Price"}).status_code == 404
    assert client.get("/v1/session/dataset/outlier-boxplot", params={"column": "Price"}).status_code == 404


def test_visualization_endpoints_422_for_unknown_or_non_numeric_column():
    _upload(_df_with_outlier())
    assert client.get("/v1/session/dataset/outlier-line", params={"column": "Nope"}).status_code == 422
    assert client.get("/v1/session/dataset/outlier-histogram", params={"column": "Region"}).status_code == 422
    assert client.get("/v1/session/dataset/outlier-density", params={"column": "Region"}).status_code == 422
    assert client.get("/v1/session/dataset/outlier-boxplot", params={"column": "Region"}).status_code == 422
