# tests/api/test_distribution.py
"""
Интеграционные тесты для GET /v1/session/dataset/distribution.

Покрывает:
  1. Малый датасет — scatter без сэмплинга (все точки).
  2. Большой датасет — LTTB-сэмплинг, min/max/выброс сохранены, x монотонны.
  3. Гистограмма и KDE считаются по ПОЛНОМУ столбцу (не зависят от sampled scatter).
  4. Нечисловая колонка — 422.
  5. Несуществующая колонка — 404.
  6. Нет активного датасета в сессии — 404.
  7. Константный столбец — kde=None, без 500.
  8. Колонка с NaN — non_null_count учитывает только непустые значения.
  9. Zoom (start/end) — узкий диапазон, x остаются в координатах полного ряда.
  10. Некорректный диапазон start >= end — 422.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.chart_data import FULL_POINTS_THRESHOLD
from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload_df(df: pd.DataFrame) -> None:
    # file_loader.py некорректно парсит CSV из ровно одной колонки (не
    # связано с этой задачей — отдельный баг, не трогаем здесь). Добавляем
    # техническую вторую колонку, чтобы тестировать именно distribution,
    # а не наткнуться на посторонний парсинг-баг.
    df = df.copy()
    if df.shape[1] == 1:
        df["_aux"] = 0
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def test_small_dataset_no_sampling():
    df = pd.DataFrame({"value": np.arange(50, dtype=float), "label": ["a"] * 50})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scatter_sampled"] is False
    assert body["scatter_sampling_method"] is None
    assert len(body["scatter"]) == 50
    assert body["scatter_original_count"] == 50
    assert body["non_null_count"] == 50
    assert body["min"] == 0.0
    assert body["max"] == 49.0


def test_large_dataset_sampled_preserves_extremes_and_outlier():
    n = FULL_POINTS_THRESHOLD + 5000
    rng = np.random.default_rng(42)
    values = rng.normal(size=n)
    outlier_pos = 1234
    values[outlier_pos] = 999.0
    df = pd.DataFrame({"value": values, "label": ["x"] * n})
    _upload_df(df)

    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["scatter_sampled"] is True
    assert body["scatter_sampling_method"] == "lttb"
    assert body["scatter_original_count"] == n
    assert len(body["scatter"]) < n  # реально сжали
    assert len(body["scatter"]) > 0

    xs = [p["x"] for p in body["scatter"]]
    ys = [p["y"] for p in body["scatter"]]
    # x строго возрастают (LTTB + union с экстремумами не должен ломать порядок)
    assert xs == sorted(xs)
    assert len(set(xs)) == len(xs)  # без дублей

    assert outlier_pos in xs, "выброс должен быть сохранён даже при сэмплинге"
    assert max(ys) == 999.0
    assert 0 in xs and (n - 1) in xs, "первая и последняя точка ряда должны сохраняться"


def test_histogram_and_kde_use_full_column_not_sampled_scatter():
    n = FULL_POINTS_THRESHOLD + 2000
    rng = np.random.default_rng(1)
    values = rng.normal(loc=10, scale=2, size=n)
    df = pd.DataFrame({"value": values, "label": ["x"] * n})
    _upload_df(df)

    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    body = resp.json()

    assert body["scatter_sampled"] is True
    # Гистограмма должна отражать ПОЛНЫЙ столбец: сумма counts == non_null_count,
    # а не число (сэмплированных) scatter-точек.
    total_hist_count = sum(b["count"] for b in body["histogram"])
    assert total_hist_count == n
    assert len(body["histogram"]) == 30  # DEFAULT_HISTOGRAM_BINS

    assert body["kde"] is not None
    assert len(body["kde"]) == 200  # KDE_CURVE_POINTS
    # KDE должна пиковать примерно у loc=10, а не у случайного шума
    peak_x = max(body["kde"], key=lambda p: p["y"])["x"]
    assert 6 < peak_x < 14


def test_non_numeric_column_returns_422():
    df = pd.DataFrame({"value": [1.0, 2.0, 3.0], "label": ["a", "b", "c"]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/distribution", params={"column": "label"})
    assert resp.status_code == 422


def test_missing_column_returns_404():
    df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/distribution", params={"column": "does_not_exist"})
    assert resp.status_code == 404


def test_no_active_dataset_returns_404():
    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    assert resp.status_code == 404


def test_constant_column_kde_none_no_500():
    df = pd.DataFrame({"value": [7.0] * 40, "label": ["x"] * 40})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kde"] is None
    assert body["min"] == 7.0
    assert body["max"] == 7.0
    assert len(body["scatter"]) == 40


def test_nan_values_excluded_from_non_null_count():
    values = [1.0, 2.0, None, 4.0, None, 6.0]
    df = pd.DataFrame({"value": values, "label": ["x"] * 6})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/distribution", params={"column": "value"})
    body = resp.json()
    assert body["non_null_count"] == 4
    assert len(body["scatter"]) == 4
    # x — позиции в ОЧИЩЕННОМ от NaN ряде (0..3), не исходные индексы (0,1,3,5)
    xs = sorted(p["x"] for p in body["scatter"])
    assert xs == [0, 1, 2, 3]


def test_zoom_range_keeps_full_series_coordinates():
    n = 500
    values = np.arange(n, dtype=float)
    df = pd.DataFrame({"value": values, "label": ["x"] * n})
    _upload_df(df)

    resp = client.get(
        "/v1/session/dataset/distribution",
        params={"column": "value", "start": 100, "end": 150},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scatter_sampled"] is False  # диапазон узкий, полное разрешение
    xs = sorted(p["x"] for p in body["scatter"])
    assert xs == list(range(100, 150)), "x должны остаться в координатах полного ряда, не локального среза"
    # min/max/histogram/kde считаются по диапазону, не по всему ряду
    assert body["min"] == 100.0
    assert body["max"] == 149.0


def test_zoom_invalid_range_returns_422():
    df = pd.DataFrame({"value": np.arange(100, dtype=float), "label": ["x"] * 100})
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/distribution",
        params={"column": "value", "start": 50, "end": 50},
    )
    assert resp.status_code == 422
