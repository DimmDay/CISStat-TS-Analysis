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
    """Тест фильтрации моделей по профилю данных"""
    catalog = ModelsCatalog.from_yaml("config/models/ts_models_catalog.yaml")
    
    # Профиль: мало данных, нестационарный, без сезонности, нерегулярный
    profile = {
        'n_observations': 20,
        'is_stationary': False,
        'has_seasonality': False,
        'has_exogenous': False,
        'is_regular': False,
        'dq_score': 50.0
    }
    
    suitable = catalog.filter_by_requirements(profile)
    
    # Должны пройти: naive (benchmark, min_obs=2) и ets (statistical, min_obs=10)
    # ets проходит, потому что у неё stationarity="not_needed", 
    # seasonality="supported", regularity="optional"
    assert len(suitable) == 2
    model_ids = {m.id for m in suitable}
    assert model_ids == {'naive', 'ets'}


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