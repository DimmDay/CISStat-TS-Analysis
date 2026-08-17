# app/core/dataset_classifier.py
"""
Классификация СТРУКТУРНОГО КЛАССА датасета (Уровень 1 из утверждённой
иерархии маршрутизации: Структурный класс → Свойства ряда → Пайплайн).

⚠️ ВАЖНО: эта функция определяет ТОЛЬКО структурный класс (форму данных --
какие колонки есть: дата? группировка? координаты? иерархия?). Она
СОЗНАТЕЛЬНО НЕ вычисляет стационарность/сезонность/тип тренда и не выбирает
конкретную модель (ARIMA vs ETS и т.п.) -- это Уровень 2/3, требующий
расчётов на уже очищенных (см. "Предобработка") данных, а не на сырых,
которые могли только что пройти "Загрузку". Смешивать уровни -- то самое
"иллюзия полноты", от которого мы сознательно отказались при проектировании
вкладки "Загрузка".

Правило проекта: не импортирует streamlit, stateless, явные аргументы.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class StructuralClass(str, Enum):
    CROSS_SECTIONAL = "cross_sectional"
    UNIVARIATE_TS = "univariate_ts"
    MULTIVARIATE_TS = "multivariate_ts"
    PANEL_BALANCED = "panel_balanced"
    PANEL_UNBALANCED = "panel_unbalanced"
    EVENT_TS = "event_ts"
    SPATIO_TEMPORAL = "spatio_temporal"
    HIERARCHICAL = "hierarchical"


# ─────────────────────────────────────────────────────────────
# Рекомендуемый пайплайн (список модулей/анализов для активации во вкладках)
# -- на основе схемы, утверждённой в архитектурном обсуждении.
# ─────────────────────────────────────────────────────────────
RECOMMENDED_PIPELINE: Dict[StructuralClass, List[str]] = {
    StructuralClass.CROSS_SECTIONAL: ["EDA", "Regression", "Clustering", "Classification"],
    StructuralClass.UNIVARIATE_TS: ["Trend", "Seasonality", "ACF", "PACF", "ARIMA", "ETS", "Prophet"],
    StructuralClass.MULTIVARIATE_TS: ["Correlation", "VAR", "Cointegration", "Transfer Entropy", "Feature Engineering"],
    StructuralClass.PANEL_BALANCED: ["Fixed Effects", "Random Effects", "Panel VAR", "GMM"],
    StructuralClass.PANEL_UNBALANCED: ["Fixed Effects", "Random Effects", "GMM"],  # Panel VAR обычно требует баланса
    StructuralClass.EVENT_TS: ["Point Process", "Survival Analysis"],
    StructuralClass.SPATIO_TEMPORAL: ["Spatio-Temporal Kriging", "Spatial Panel Models"],
    StructuralClass.HIERARCHICAL: ["Forecast Reconciliation", "Bottom-Up", "Top-Down"],
}

LAT_PATTERN = re.compile(r"^(lat|latitude|широта)$", re.IGNORECASE)
LON_PATTERN = re.compile(r"^(lon|lng|longitude|долгота)$", re.IGNORECASE)

HIERARCHY_KEYWORDS = [
    "country", "страна", "region", "регион", "область", "district", "район",
    "city", "город", "enterprise", "предприятие", "company", "компания",
]

ACTION_KEYWORDS = [
    "action", "event", "действие", "событие", "type", "тип", "status",
    "статус", "log", "лог", "transaction", "транзакция",
]


def _detect_coordinates(df: pd.DataFrame, exclude: set) -> Optional[Dict[str, str]]:
    """Ищет пару колонок широта/долгота среди числовых, с проверкой диапазона значений."""
    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c not in exclude]
    lat_col = next((c for c in numeric_cols if LAT_PATTERN.match(str(c))), None)
    lon_col = next((c for c in numeric_cols if LON_PATTERN.match(str(c))), None)
    if lat_col is None or lon_col is None:
        return None
    lat_vals = df[lat_col].dropna()
    lon_vals = df[lon_col].dropna()
    if lat_vals.empty or lon_vals.empty:
        return None
    if not (lat_vals.between(-90, 90).mean() > 0.95 and lon_vals.between(-180, 180).mean() > 0.95):
        return None
    return {"lat_col": lat_col, "lon_col": lon_col}


def _detect_hierarchy_column(df: pd.DataFrame, group_col: Optional[str]) -> Optional[str]:
    """
    Ищет дополнительную категориальную колонку (кроме group_col), которая
    вложена в group_col -- каждое её значение принадлежит РОВНО ОДНОМУ
    значению group_col (например, Region всегда принадлежит одной Country).
    """
    if group_col is None or group_col not in df.columns:
        return None
    candidates = [
        c for c in df.select_dtypes(include=["object", "string", "category"]).columns
        if c != group_col and any(kw in str(c).lower() for kw in HIERARCHY_KEYWORDS)
    ]
    for candidate in candidates:
        try:
            nesting = df.groupby(candidate)[group_col].nunique()
            if len(nesting) > 0 and nesting.max() == 1:
                return candidate
        except Exception:
            continue
    return None


def _detect_action_column(df: pd.DataFrame, exclude: set) -> Optional[str]:
    cat_cols = [
        c for c in df.select_dtypes(include=["object", "string", "category"]).columns
        if c not in exclude
    ]
    for c in cat_cols:
        if any(kw in str(c).lower() for kw in ACTION_KEYWORDS):
            return c
    return None


def _is_panel_balanced(df: pd.DataFrame, date_col: str, group_col: str) -> bool:
    """Панель сбалансирована, если у всех групп идентичный набор периодов."""
    date_sets = df.groupby(group_col)[date_col].apply(lambda s: frozenset(s.dropna()))
    unique_sets = date_sets.unique()
    return len(unique_sets) <= 1


def classify_dataset_structure(
    df: pd.DataFrame,
    date_col: Optional[str] = None,
    group_col: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Определяет структурный класс датасета (Уровень 1 маршрутизации).

    Args:
        df: исходный DataFrame
        date_col: колонка даты/периода, если обнаружена ранее (detect_and_convert_datetime)
        group_col: группирующая колонка, если обнаружена ранее (detect_panel_group_column)

    Returns:
        dict с ключами:
            structural_class: StructuralClass
            confidence: float (0..1) -- насколько уверенно определён класс
            signals: dict -- какие именно признаки привели к этому выводу (для UI/override)
            recommended_pipeline: List[str] -- модули для активации в последующих вкладках
    """
    exclude = {c for c in (date_col, group_col) if c is not None}

    if df.empty:
        return {
            "structural_class": StructuralClass.CROSS_SECTIONAL,
            "confidence": 0.0,
            "signals": {"empty_dataframe": True},
            "recommended_pipeline": [],
        }

    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c not in exclude]

    # 1. Координаты -> Spatio-Temporal (проверяем первым -- специфичный, редкий сигнал)
    coords = _detect_coordinates(df, exclude)
    if date_col is not None and coords is not None:
        return {
            "structural_class": StructuralClass.SPATIO_TEMPORAL,
            "confidence": 0.9,
            "signals": {"date_col": date_col, **coords},
            "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.SPATIO_TEMPORAL],
        }

    # 2. Вложенная группировка -> Hierarchical (проверяем до Panel -- частный случай Panel)
    hierarchy_col = _detect_hierarchy_column(df, group_col)
    if date_col is not None and group_col is not None and hierarchy_col is not None:
        return {
            "structural_class": StructuralClass.HIERARCHICAL,
            "confidence": 0.85,
            "signals": {"date_col": date_col, "group_col": group_col, "nested_column": hierarchy_col},
            "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.HIERARCHICAL],
        }

    # 3. Дата без группировки, без числовых признаков, с колонкой-действием -> Event TS
    if date_col is not None and group_col is None and len(numeric_cols) == 0:
        action_col = _detect_action_column(df, exclude)
        if action_col is not None:
            return {
                "structural_class": StructuralClass.EVENT_TS,
                "confidence": 0.8,
                "signals": {"date_col": date_col, "action_col": action_col},
                "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.EVENT_TS],
            }

    # 4. Дата + группировка (без вложенной иерархии) -> Panel Data
    if date_col is not None and group_col is not None:
        balanced = _is_panel_balanced(df, date_col, group_col)
        cls = StructuralClass.PANEL_BALANCED if balanced else StructuralClass.PANEL_UNBALANCED
        return {
            "structural_class": cls,
            "confidence": 0.9,
            "signals": {"date_col": date_col, "group_col": group_col, "balanced": balanced},
            "recommended_pipeline": RECOMMENDED_PIPELINE[cls],
        }

    # 5. Дата без группировки -> Univariate / Multivariate TS, по числу числовых признаков
    if date_col is not None and group_col is None:
        if len(numeric_cols) <= 1:
            return {
                "structural_class": StructuralClass.UNIVARIATE_TS,
                "confidence": 0.85 if len(numeric_cols) == 1 else 0.5,
                "signals": {"date_col": date_col, "numeric_cols": numeric_cols},
                "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.UNIVARIATE_TS],
            }
        return {
            "structural_class": StructuralClass.MULTIVARIATE_TS,
            "confidence": 0.85,
            "signals": {"date_col": date_col, "numeric_cols": numeric_cols},
            "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.MULTIVARIATE_TS],
        }

    # 6. Нет даты вообще -> Cross-Sectional (независимо от наличия group_col --
    #    группировка без времени -- это просто категориальный признак, не панель)
    return {
        "structural_class": StructuralClass.CROSS_SECTIONAL,
        "confidence": 0.7,
        "signals": {"date_col": date_col, "group_col": group_col},
        "recommended_pipeline": RECOMMENDED_PIPELINE[StructuralClass.CROSS_SECTIONAL],
    }
