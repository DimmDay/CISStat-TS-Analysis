# tests/unit/test_dataset_classifier.py
"""
Тесты для app/core/dataset_classifier.py -- НАПИСАНЫ ДО РЕАЛИЗАЦИИ
(правило проекта: "сначала тест, потом код").

По одному golden-примеру на каждый структурный класс из иерархии,
утверждённой в архитектурном обсуждении вкладки "Загрузка":

1. Cross-Sectional Data
2. Univariate Time Series
3. Multivariate Time Series
4. Panel Data (Balanced / Unbalanced)
5. Event Time Series
6. Spatio-Temporal Data
7. Hierarchical Time Series

ВАЖНО: на этом этапе (вкладка "Загрузка") определяется ТОЛЬКО структурный
класс (Уровень 1) -- НЕ стационарность/сезонность/тип пайплайна (Уровень 2/3).
"""
import numpy as np
import pandas as pd
import pytest

from app.core.dataset_classifier import classify_dataset_structure, StructuralClass


@pytest.fixture
def cross_sectional_df():
    return pd.DataFrame({
        "Country": ["A", "B", "C", "D", "E"],
        "GDP": [100, 150, 200, 130, 175],
        "Population": [10, 20, 15, 12, 18],
    })


@pytest.fixture
def univariate_ts_df():
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    return pd.DataFrame({"Date": idx, "Price": np.random.default_rng(1).normal(100, 5, 100)})


@pytest.fixture
def multivariate_ts_df():
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    rng = np.random.default_rng(2)
    return pd.DataFrame({
        "Date": idx,
        "Price": rng.normal(100, 5, 100),
        "Rain": rng.normal(50, 10, 100),
        "Temperature": rng.normal(20, 3, 100),
    })


@pytest.fixture
def panel_balanced_df():
    countries = ["A", "B", "C"]
    years = list(range(2010, 2021))
    rng = np.random.default_rng(3)
    return pd.DataFrame({
        "Country": [c for c in countries for _ in years],
        "Year": [y for _ in countries for y in years],
        "GDP": rng.normal(100, 20, len(countries) * len(years)),
    })


@pytest.fixture
def panel_unbalanced_df():
    rng = np.random.default_rng(4)
    rows = []
    rows += [{"Country": "A", "Year": y, "GDP": rng.normal(100, 20)} for y in range(2010, 2021)]
    rows += [{"Country": "B", "Year": y, "GDP": rng.normal(100, 20)} for y in range(2015, 2021)]
    rows += [{"Country": "C", "Year": y, "GDP": rng.normal(100, 20)} for y in range(2010, 2018)]
    return pd.DataFrame(rows)


@pytest.fixture
def event_ts_df():
    rng = np.random.default_rng(5)
    n = 200
    base = pd.Timestamp("2024-01-01")
    offsets_seconds = np.cumsum(rng.exponential(scale=30, size=n))
    timestamps = [base + pd.Timedelta(seconds=s) for s in offsets_seconds]
    actions = rng.choice(["login", "click", "purchase", "logout"], size=n)
    return pd.DataFrame({"Timestamp": timestamps, "Action": actions})


@pytest.fixture
def spatio_temporal_df():
    rng = np.random.default_rng(6)
    n = 150
    return pd.DataFrame({
        "Latitude": rng.uniform(40, 60, n),
        "Longitude": rng.uniform(30, 50, n),
        "Date": pd.date_range("2023-01-01", periods=n, freq="D"),
        "Yield": rng.normal(30, 5, n),
    })


@pytest.fixture
def hierarchical_df():
    rng = np.random.default_rng(7)
    rows = []
    hierarchy = {
        "Kazakhstan": ["Almaty", "Astana"],
        "Belarus": ["Minsk", "Gomel"],
    }
    for country, regions in hierarchy.items():
        for region in regions:
            for year in range(2018, 2023):
                rows.append({
                    "Country": country, "Region": region, "Year": year,
                    "Output": rng.normal(500, 50),
                })
    return pd.DataFrame(rows)


class TestClassifyDatasetStructure:

    def test_cross_sectional(self, cross_sectional_df):
        result = classify_dataset_structure(cross_sectional_df, date_col=None, group_col=None)
        assert result["structural_class"] == StructuralClass.CROSS_SECTIONAL

    def test_univariate_ts(self, univariate_ts_df):
        result = classify_dataset_structure(univariate_ts_df, date_col="Date", group_col=None)
        assert result["structural_class"] == StructuralClass.UNIVARIATE_TS

    def test_multivariate_ts(self, multivariate_ts_df):
        result = classify_dataset_structure(multivariate_ts_df, date_col="Date", group_col=None)
        assert result["structural_class"] == StructuralClass.MULTIVARIATE_TS

    def test_panel_balanced(self, panel_balanced_df):
        result = classify_dataset_structure(panel_balanced_df, date_col="Year", group_col="Country")
        assert result["structural_class"] == StructuralClass.PANEL_BALANCED

    def test_panel_unbalanced(self, panel_unbalanced_df):
        result = classify_dataset_structure(panel_unbalanced_df, date_col="Year", group_col="Country")
        assert result["structural_class"] == StructuralClass.PANEL_UNBALANCED

    def test_event_ts(self, event_ts_df):
        result = classify_dataset_structure(event_ts_df, date_col="Timestamp", group_col=None)
        assert result["structural_class"] == StructuralClass.EVENT_TS

    def test_spatio_temporal(self, spatio_temporal_df):
        result = classify_dataset_structure(spatio_temporal_df, date_col="Date", group_col=None)
        assert result["structural_class"] == StructuralClass.SPATIO_TEMPORAL

    def test_hierarchical(self, hierarchical_df):
        result = classify_dataset_structure(hierarchical_df, date_col="Year", group_col="Country")
        assert result["structural_class"] == StructuralClass.HIERARCHICAL

    def test_returns_confidence_and_signals(self, univariate_ts_df):
        result = classify_dataset_structure(univariate_ts_df, date_col="Date", group_col=None)
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0
        assert "signals" in result
        assert isinstance(result["signals"], dict)

    def test_returns_recommended_pipeline(self, univariate_ts_df):
        result = classify_dataset_structure(univariate_ts_df, date_col="Date", group_col=None)
        assert "recommended_pipeline" in result
        assert isinstance(result["recommended_pipeline"], list)
        assert len(result["recommended_pipeline"]) > 0

    def test_empty_dataframe_does_not_crash(self):
        result = classify_dataset_structure(pd.DataFrame(), date_col=None, group_col=None)
        assert "structural_class" in result
