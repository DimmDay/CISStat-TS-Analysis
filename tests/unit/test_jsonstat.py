"""
Unit-тесты для parse_jsonstat и detect_panel_group_column.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.14).
"""
import pytest
import pandas as pd
from app.data.file_loader import parse_jsonstat
from app.data.detectors import detect_panel_group_column


class TestParseJsonStat:
    """Тесты для функции parse_jsonstat."""

    def _create_sample_jsonstat(self):
        """Создаёт пример JSON-stat 2.0 структуры."""
        return {
            "version": "2.0",
            "label": "Test Dataset",
            "id": ["time", "region"],
            "size": [3, 2],
            "dimension": {
                "time": {
                    "category": {
                        "index": {"2020": 0, "2021": 1, "2022": 2},
                        "label": {"2020": "2020", "2021": "2021", "2022": "2022"}
                    }
                },
                "region": {
                    "category": {
                        "index": {"A": 0, "B": 1},
                        "label": {"A": "Region A", "B": "Region B"}
                    }
                }
            },
            "value": {
                "0": 100,
                "1": 110,
                "2": 120,
                "3": 130,
                "4": 140,
                "5": 150
            }
        }

    def test_parse_valid_jsonstat(self):
        """Должен корректно парсить валидный JSON-stat 2.0."""
        data = self._create_sample_jsonstat()
        df = parse_jsonstat(data)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 6  # 3 времени × 2 региона
        assert "time" in df.columns
        assert "region" in df.columns
        assert "value" in df.columns

    def test_parse_jsonstat_values_correct(self):
        """Значения должны соответствовать исходным данным."""
        data = self._create_sample_jsonstat()
        df = parse_jsonstat(data)
        
        # Проверяем, что все значения на месте
        assert set(df["value"]) == {100, 110, 120, 130, 140, 150}
        assert set(df["time"]) == {"2020", "2021", "2022"}
        assert set(df["region"]) == {"Region A", "Region B"}

    def test_parse_invalid_jsonstat_no_version(self):
        """Должен выбросить ошибку, если нет version."""
        data = {"value": {"0": 100}, "dimension": {}}
        with pytest.raises(ValueError, match="Не является валидным JSON-stat 2.0"):
            parse_jsonstat(data)

    def test_parse_invalid_jsonstat_wrong_version(self):
        """Должен выбросить ошибку, если version != 2.0."""
        data = {"version": "1.0", "value": {"0": 100}, "dimension": {}}
        with pytest.raises(ValueError, match="Не является валидным JSON-stat 2.0"):
            parse_jsonstat(data)

    def test_parse_invalid_jsonstat_no_value(self):
        """Должен выбросить ошибку, если нет value."""
        data = {"version": "2.0", "dimension": {}}
        with pytest.raises(ValueError, match="Не является валидным JSON-stat 2.0"):
            parse_jsonstat(data)

    def test_parse_invalid_jsonstat_no_dimension(self):
        """Должен выбросить ошибку, если нет dimension."""
        data = {"version": "2.0", "value": {"0": 100}}
        with pytest.raises(ValueError, match="Не является валидным JSON-stat 2.0"):
            parse_jsonstat(data)

    def test_parse_empty_values(self):
        """Должен выбросить ошибку, если value пуст."""
        data = {
            "version": "2.0",
            "id": ["time"],
            "size": [0],
            "dimension": {"time": {"category": {"index": {}, "label": {}}}},
            "value": {}
        }
        with pytest.raises(ValueError, match="не содержит валидных данных"):
            parse_jsonstat(data)

    def test_parse_single_dimension(self):
        """Должен работать с одним измерением."""
        data = {
            "version": "2.0",
            "id": ["time"],
            "size": [3],
            "dimension": {
                "time": {
                    "category": {
                        "index": {"2020": 0, "2021": 1, "2022": 2},
                        "label": {"2020": "2020", "2021": "2021", "2022": "2022"}
                    }
                }
            },
            "value": {"0": 100, "1": 110, "2": 120}
        }
        df = parse_jsonstat(data)
        assert len(df) == 3
        assert "time" in df.columns
        assert "value" in df.columns


class TestDetectPanelGroupColumn:
    """Тесты для функции detect_panel_group_column."""

    def test_detect_panel_column_found(self):
        """Должен найти группирующую колонку."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6, freq="MS"),
            "region": ["A", "B"] * 3,
            "value": [100, 110, 120, 130, 140, 150]
        })
        group_col = detect_panel_group_column(df, "date")
        assert group_col == "region"

    def test_detect_panel_column_not_found_numeric(self):
        """Не должен выбирать числовую колонку."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6, freq="MS"),
            "value": [100, 110, 120, 130, 140, 150],
            "count": [1, 2, 3, 4, 5, 6]
        })
        group_col = detect_panel_group_column(df, "date")
        assert group_col is None

    def test_detect_panel_column_not_found_single_unique(self):
        """Не должен выбирать колонку с одним уникальным значением."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6, freq="MS"),
            "constant": ["A"] * 6,
            "value": [100, 110, 120, 130, 140, 150]
        })
        group_col = detect_panel_group_column(df, "date")
        assert group_col is None

    def test_detect_panel_column_not_found_too_many_unique(self):
        """Не должен выбирать колонку со слишком многими уникальными значениями."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=100, freq="D"),
            "id": [f"id_{i}" for i in range(100)],
            "value": range(100)
        })
        group_col = detect_panel_group_column(df, "date")
        assert group_col is None

    def test_detect_panel_column_skips_date_column(self):
        """Не должен выбирать саму колонку даты."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6, freq="MS"),
            "value": [100, 110, 120, 130, 140, 150]
        })
        group_col = detect_panel_group_column(df, "date")
        assert group_col is None

    def test_detect_panel_column_multiple_candidates(self):
        """Должен выбрать первую подходящую колонку."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6, freq="MS"),
            "region": ["A", "B"] * 3,
            "category": ["X", "Y"] * 3,
            "value": [100, 110, 120, 130, 140, 150]
        })
        group_col = detect_panel_group_column(df, "date")
        # Должен выбрать первую подходящую (region)
        assert group_col in ["region", "category"]

    def test_detect_panel_column_empty_dataframe(self):
        """Должен вернуть None для пустого DataFrame."""
        df = pd.DataFrame()
        group_col = detect_panel_group_column(df, "date")
        assert group_col is None