"""
Модуль для работы со справочником моделей временных рядов.
Реализует Pydantic-схему для валидации YAML-каталога моделей
и логику фильтрации/рекомендаций на основе профиля данных.

Версия: 2.0
Дата: 2026-06-07
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict, Any
from pathlib import Path
import yaml
import pandas as pd


# ═══════════════════════════════════════════════════════════
# КЛАССЫ МОДЕЛИ ДАННЫХ
# ═══════════════════════════════════════════════════════════

class PreprocessingStep(BaseModel):
    """Шаг предобработки для активации модели"""
    action: str  # diff, resample, interpolate, log_transform, boxcox
    description: str
    code: str
    expected_result: str


class ModelPreprocessing(BaseModel):
    """Условия предобработки для модели"""
    if_not_stationary: Optional[PreprocessingStep] = None
    if_not_regular: Optional[PreprocessingStep] = None
    if_not_normal: Optional[PreprocessingStep] = None
    if_has_outliers: Optional[PreprocessingStep] = None
    if_small_sample: Optional[PreprocessingStep] = None


class ModelRequirements(BaseModel):
    """Требования модели к данным"""
    min_observations: int = Field(..., ge=1, description="Минимум наблюдений")
    stationarity: Literal["required", "optional", "not_needed"]
    seasonality: Literal["required", "optional", "supported", "not_needed", "not_supported"]
    # 🔧 ИСПРАВЛЕНО: добавлено "not_needed" для корректной валидации ансамблей
    exogenous: Literal["required", "optional", "supported", "not_needed", "not_supported"]
    regularity: Literal["required", "optional", "not_needed"]


class ModelConditions(BaseModel):
    """Условия применения модели"""
    when_to_use: List[str] = Field(default_factory=list)
    when_not_to_use: List[str] = Field(default_factory=list)


class TSModel(BaseModel):
    """Модель временного ряда"""
    id: str
    name: str
    category: Literal["benchmark", "statistical", "ml", "deep_learning", "ensemble"]
    description: str
    
    requirements: ModelRequirements
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    conditions: ModelConditions
    parameters: Dict[str, str] = Field(default_factory=dict)
    
    # 🔧 НОВОЕ ПОЛЕ: шаги предобработки для активации модели
    preprocessing: Optional[ModelPreprocessing] = None
    
    libraries: List[str] = Field(default_factory=list)
    complexity: Literal["low", "medium", "high"]
    training_time: Literal["instant", "seconds", "minutes", "hours"]
    
    @field_validator('id')
    @classmethod
    def validate_id(cls, v):
        if not v.replace('_', '').isalnum():
            raise ValueError("ID должен содержать только буквы, цифры и _")
        return v.lower()


class Category(BaseModel):
    """Категория моделей"""
    id: str
    name: str
    description: str
    priority: int = Field(..., ge=1)


class RecommendationRules(BaseModel):
    """Правила рекомендаций"""
    by_dq_score: Dict[str, List[str]]
    by_sample_size: Dict[str, Dict[str, Any]]
    by_properties: Dict[str, List[str]]


# ═══════════════════════════════════════════════════════════
# ГЛАВНЫЙ СПРАВОЧНИК МОДЕЛЕЙ
# ═══════════════════════════════════════════════════════════

class ModelsCatalog(BaseModel):
    """Главный справочник моделей временных рядов"""
    metadata: Dict[str, str]
    categories: List[Category]
    models: List[TSModel]
    recommendation_rules: RecommendationRules
    
    # ── МЕТОДЫ ЗАГРУЗКИ ──────────────────────────────────
    
    @classmethod
    def from_yaml(cls, path: str) -> "ModelsCatalog":
        """Загрузка справочника из YAML-файла"""
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"YAML-файл не найден: {path}")
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data:
            raise ValueError(f"YAML-файл пуст: {path}")
        
        return cls(**data)
    
    def to_yaml(self, path: str) -> None:
        """Сохранение справочника в YAML-файл"""
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(
                self.model_dump(),
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False
            )
    
    # ── МЕТОДЫ ПОЛУЧЕНИЯ МОДЕЛЕЙ ─────────────────────────
    
    def get_model(self, model_id: str) -> Optional[TSModel]:
        """Получить модель по ID"""
        for model in self.models:
            if model.id == model_id:
                return model
        return None
    
    def get_models_by_category(self, category: str) -> List[TSModel]:
        """Получить модели по категории"""
        return [m for m in self.models if m.category == category]
    
    def get_all_model_ids(self) -> List[str]:
        """Получить список всех ID моделей"""
        return [m.id for m in self.models]
    
    # ── ФИЛЬТРАЦИЯ ПО ТРЕБОВАНИЯМ ────────────────────────
    
    def filter_by_requirements(self, data_profile: Dict[str, Any]) -> List[TSModel]:
        """
        Фильтрация моделей по профилю данных.
        
        Args:
            data_profile: {
                'n_observations': int,
                'is_stationary': bool,
                'has_seasonality': bool,
                'has_exogenous': bool,
                'is_regular': bool,
                'dq_score': float
            }
        
        Returns:
            Список моделей, подходящих под требования
        """
        suitable = []
        
        for model in self.models:
            req = model.requirements
            
            # Проверка объёма данных
            if data_profile.get('n_observations', 0) < req.min_observations:
                continue
            
            # Проверка стационарности
            if req.stationarity == "required" and not data_profile.get('is_stationary', False):
                continue
            
            # Проверка сезонности
            if req.seasonality == "required" and not data_profile.get('has_seasonality', False):
                continue
            
            # Проверка регулярности
            if req.regularity == "required" and not data_profile.get('is_regular', False):
                continue
            
            suitable.append(model)
        
        return suitable
    
    # ── ПРОВЕРКА ПРЕДОБРАБОТКИ ───────────────────────────
    
    def check_preprocessing_needed(
        self, 
        model: TSModel, 
        profile: Dict[str, Any]
    ) -> List[Dict[str, str]]:
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
        
        # Проверка нормальности
        if not profile.get('is_normal', True):
            if model.preprocessing and model.preprocessing.if_not_normal:
                prep = model.preprocessing.if_not_normal
                steps.append({
                    'issue': 'Отклонение от нормальности',
                    'action': prep.action,
                    'description': prep.description,
                    'code': prep.code,
                    'expected': prep.expected_result
                })
        
        # Проверка выбросов
        if profile.get('has_outliers', False):
            if model.preprocessing and model.preprocessing.if_has_outliers:
                prep = model.preprocessing.if_has_outliers
                steps.append({
                    'issue': 'Наличие выбросов',
                    'action': prep.action,
                    'description': prep.description,
                    'code': prep.code,
                    'expected': prep.expected_result
                })
        
        return steps
    
    # ── ГЕНЕРАЦИЯ РЕКОМЕНДАЦИЙ ───────────────────────────
    
    def get_recommendations(
        self, 
        data_profile: Dict[str, Any],
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        Генерация рекомендаций по моделям.
        
        Returns:
            {
                'recommended': [TSModel, ...],
                'available': [TSModel, ...],
                'unavailable': [TSModel, ...],
                'after_preprocessing': [{'model': TSModel, 'steps': [...]}, ...],
                'primary': TSModel,
                'reasoning': str
            }
        """
        # Фильтрация по требованиям
        suitable = self.filter_by_requirements(data_profile)
        unsuitable = [m for m in self.models if m not in suitable]
        
        # 🔥 Проверка, какие недоступные модели можно активировать предобработкой
        after_preprocessing = []
        for model in unsuitable:
            steps = self.check_preprocessing_needed(model, data_profile)
            if steps:
                after_preprocessing.append({
                    'model': model,
                    'steps': steps
                })
        
        # Сортировка по приоритету категории
        category_priority = {c.id: c.priority for c in self.categories}
        suitable.sort(key=lambda m: category_priority.get(m.category, 99))
        
        # Выбор главной рекомендации
        primary = suitable[0] if suitable else None
        
        # Формирование обоснования
        reasoning = self._generate_reasoning(data_profile, suitable)
        
        return {
            'recommended': suitable[:top_k],
            'available': suitable,
            'unavailable': [m for m in unsuitable if not any(
                ap['model'].id == m.id for ap in after_preprocessing
            )],
            'after_preprocessing': after_preprocessing,
            'primary': primary,
            'reasoning': reasoning
        }
    
    # ── ГЕНЕРАЦИЯ ОБОСНОВАНИЯ ────────────────────────────
    
    def _generate_reasoning(
        self, 
        data_profile: Dict[str, Any], 
        models: List[TSModel]
    ) -> str:
        """Генерация текстового обоснования рекомендаций"""
        n = data_profile.get('n_observations', 0)
        dq = data_profile.get('dq_score', 0)
        
        parts = []
        
        # По объёму данных
        if n < 30:
            parts.append(f"📊 **Мало данных** ({n} наблюдений) — доступны только бенчмарки")
        elif n < 100:
            parts.append(f"📊 **Небольшой объём** ({n} наблюдений) — статистические модели")
        elif n < 1000:
            parts.append(f"📊 **Средний объём** ({n} наблюдений) — ML-модели доступны")
        else:
            parts.append(f"📊 **Большой объём** ({n} наблюдений) — Deep Learning применим")
        
        # По качеству данных
        if dq >= 80:
            parts.append("✅ **Высокое качество данных** (DQ ≥ 80%) — все модели применимы")
        elif dq >= 50:
            parts.append("⚠️ **Среднее качество** (DQ 50-80%) — рекомендована предобработка")
        else:
            parts.append("❌ **Низкое качество** (DQ < 50%) — только базовые модели")
        
        # По свойствам ряда
        if data_profile.get('has_seasonality'):
            parts.append("🔄 Обнаружена **сезонность** — используйте SARIMA/Prophet")
        if not data_profile.get('is_stationary'):
            parts.append("📈 Ряд **нестационарен** — требуется дифференцирование")
        if not data_profile.get('is_regular'):
            parts.append("📅 **Нерегулярная частота** — требуется ресемплинг")
        
        return "\n\n".join(parts)
    
    # ── УТИЛИТЫ ──────────────────────────────────────────
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику по справочнику"""
        categories_count = {}
        for model in self.models:
            categories_count[model.category] = categories_count.get(model.category, 0) + 1
        
        return {
            'total_models': len(self.models),
            'total_categories': len(self.categories),
            'models_by_category': categories_count,
            'version': self.metadata.get('version', 'unknown'),
            'last_updated': self.metadata.get('last_updated', 'unknown')
        }
    
    def validate_integrity(self) -> List[str]:
        """Проверка целостности справочника"""
        issues = []
        
        # Проверка дубликатов ID
        ids = [m.id for m in self.models]
        duplicates = [x for x in ids if ids.count(x) > 1]
        if duplicates:
            issues.append(f"Дубликаты ID: {set(duplicates)}")
        
        # Проверка ссылок в recommendation_rules
        for rule_type, rules in self.recommendation_rules.model_dump().items():
            if isinstance(rules, dict):
                for key, value in rules.items():
                    if isinstance(value, list):
                        for model_id in value:
                            if isinstance(model_id, str) and not self.get_model(model_id):
                                if model_id not in ['arima_with_diff', 'linear_trend_arima', 
                                                     'external_regressors', 'stochastic_volatility',
                                                     'sarima', 'vecm']:
                                    issues.append(f"Неизвестный model_id в правилах: {model_id}")
        
        return issues
    
    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"ModelsCatalog(v{stats['version']}, "
            f"models={stats['total_models']}, "
            f"categories={stats['total_categories']})"
        )