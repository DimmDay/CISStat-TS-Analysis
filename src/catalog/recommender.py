"""
Модуль-адаптер для интеграции справочника с платформой CISStat.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
from .models_catalog import ModelsCatalog, TSModel


class CISStatRecommender:
    """Рекомендатель моделей для платформы CISStat"""
    
    def __init__(self, catalog_path: str = None):
        if catalog_path is None:
            catalog_path = Path(__file__).parent.parent.parent / "config" / "models" / "ts_models_catalog.yaml"
        
        self.catalog = ModelsCatalog.from_yaml(str(catalog_path))
    
    def build_profile_from_session_state(self, session_state) -> Dict[str, Any]:
        """
        Построение профиля данных из session_state Streamlit.
        """
        profile = {
            'n_observations': 0,
            'is_stationary': False,
            'has_seasonality': False,
            'has_exogenous': False,
            'is_regular': False,
            'dq_score': 0.0
        }
        
        # Из паспорта v1.0
        props_v10 = session_state.get('ts_props_v10', {})
        if props_v10:
            profile['n_observations'] = props_v10.get('basic_stats', {}).get('n', 0)
            profile['is_stationary'] = props_v10.get('stationarity', {}).get('is_stationary', False)
            profile['has_seasonality'] = props_v10.get('seasonality', {}).get('is_seasonal', False)
            
            freq = props_v10.get('freq', {}).get('value')
            profile['is_regular'] = freq is not None and freq != 'Нерегулярная'
            
            # Наличие экзогенных признаков
            num_cols = session_state.get('col_types', {}).get('num', [])
            profile['has_exogenous'] = len(num_cols) > 1
        
        # DQ Score
        profile['dq_score'] = session_state.get('dq_score', 0.0)
        
        return profile
    
    def check_preprocessing_needed(self, model: TSModel, profile: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Проверяет, какие шаги предобработки нужны для модели.
        
        Returns:
            Список словарей с описанием необходимых шагов
        """
        steps = []
        req = model.requirements
        
        # Проверка стационарности
        if req.stationarity == "optional" and not profile.get('is_stationary', False):
            if model.preprocessing and model.preprocessing.if_not_stationary:
                prep = model.preprocessing.if_not_stationary
                steps.append({
                    'issue': 'Нестационарность ряда',
                    'action': prep.action,
                    'description': prep.description,
                    'code': prep.code,
                    'expected': prep.expected_result
                })
        
        # Проверка регулярности
        if req.regularity == "optional" and not profile.get('is_regular', False):
            if model.preprocessing and model.preprocessing.if_not_regular:
                prep = model.preprocessing.if_not_regular
                steps.append({
                    'issue': 'Нерегулярная частота',
                    'action': prep.action,
                    'description': prep.description,
                    'code': prep.code,
                    'expected': prep.expected_result
                })
        
        return steps
    
    def get_recommendations_for_ui(self, session_state) -> Dict[str, Any]:
        """
        Получение рекомендаций в формате для UI.
        """
        profile = self.build_profile_from_session_state(session_state)
        
        # Фильтрация по требованиям
        suitable = self.catalog.filter_by_requirements(profile)
        unsuitable = [m for m in self.catalog.models if m not in suitable]
        
        # Сортировка по приоритету категории
        category_priority = {c.id: c.priority for c in self.catalog.categories}
        suitable.sort(key=lambda m: category_priority.get(m.category, 99))
        
        # Проверяем, какие недоступные модели можно активировать
        after_preprocessing = []
        for model in unsuitable:
            steps = self.check_preprocessing_needed(model, profile)
            if steps:
                after_preprocessing.append({
                    'model': model,
                    'steps': steps
                })
        
        # Выбор главной рекомендации
        primary = suitable[0] if suitable else None
        
        # Формирование обоснования
        reasoning = self.catalog._generate_reasoning(profile, suitable)
        
        result = {
            'primary': primary.name if primary else "Нет подходящих моделей",
            'available': [m.name for m in suitable[:3]],
            'limited': [m.name for m in suitable[3:]],
            'unavailable': [m.name for m in unsuitable if not any(
                ap['model'].id == m.id for ap in after_preprocessing
            )],
            'after_preprocessing': after_preprocessing,
            'explanation': reasoning,
            'tier': self._determine_tier(profile),
            'dq_score': profile['dq_score']
        }
        
        return result
    
    def _determine_tier(self, profile: Dict[str, Any]) -> str:
        """Определение уровня качества данных"""
        dq = profile['dq_score']
        n = profile['n_observations']
        
        if dq >= 80 and n >= 100:
            return "high"
        elif dq >= 50 and n >= 30:
            return "medium"
        else:
            return "low"