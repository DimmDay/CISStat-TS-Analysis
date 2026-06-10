"""
Тесты для справочника моделей.
"""
import pytest
from pathlib import Path
from src.catalog.models_catalog import ModelsCatalog


def test_catalog_loads():
    """Тест загрузки справочника"""
    catalog_path = Path("config/models/ts_models_catalog.yaml")
    catalog = ModelsCatalog.from_yaml(str(catalog_path))
    
    assert len(catalog.models) > 0
    assert len(catalog.categories) > 0


def test_model_filtering():
    """Тест фильтрации моделей"""
    catalog = ModelsCatalog.from_yaml("config/models/ts_models_catalog.yaml")
    
    # Профиль: мало данных
    profile = {
        'n_observations': 20,
        'is_stationary': False,
        'has_seasonality': False,
        'has_exogenous': False,
        'is_regular': False,
        'dq_score': 50.0
    }
    
    suitable = catalog.filter_by_requirements(profile)
    # Должны остаться только бенчмарки
    assert all(m.category == "benchmark" for m in suitable)


def test_recommendations():
    """Тест генерации рекомендаций"""
    catalog = ModelsCatalog.from_yaml("config/models/ts_models_catalog.yaml")
    
    profile = {
        'n_observations': 500,
        'is_stationary': True,
        'has_seasonality': True,
        'has_exogenous': True,
        'is_regular': True,
        'dq_score': 85.0
    }
    
    recs = catalog.get_recommendations(profile)
    assert recs['primary'] is not None
    assert len(recs['recommended']) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])