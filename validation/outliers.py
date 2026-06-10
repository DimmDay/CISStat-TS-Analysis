# validation/outliers.py
"""
Детектор выбросов и аномалий.
Работает в режиме маркировки: возвращает индексы и статистику, НЕ меняет данные.
"""

import pandas as pd
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

def detect_outliers(df: pd.DataFrame, config: dict) -> Dict[str, Any]:
    """
    Обнаруживает выбросы в числовых колонках.
    
    Args:
        df: Исходный DataFrame
        config: dict из YAML (раздел outliers)
        
    Returns:
        dict с отчётом по колонкам и сводной статистикой
    """
    report = {
        "by_column": {},
        "summary": {"total_outliers": 0, "outlier_columns": []}
    }
    
    method = config.get("method", "iqr").lower()
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:  # Недостаточно данных для статистики
            continue
            
        outlier_indices = []
        
        try:
            if method == "iqr":
                q1, q3 = series.quantile([0.25, 0.75])
                iqr = q3 - q1
                multiplier = config.get("iqr_multiplier", 1.5)
                lower, upper = q1 - multiplier * iqr, q3 + multiplier * iqr
                mask = (df[col] < lower) | (df[col] > upper)
                outlier_indices = df.index[mask].tolist()
                
            elif method == "zscore":
                threshold = config.get("zscore_threshold", 3.0)
                z_scores = np.abs(stats.zscore(series))
                mask_z = z_scores > threshold
                outlier_indices = series.index[mask_z].tolist()
                
            elif method == "isolation_forest":
                model = IsolationForest(contamination="auto", random_state=42, n_estimators=100)
                pred = model.fit_predict(series.values.reshape(-1, 1))
                outlier_indices = series.index[pred == -1].tolist()
                
        except Exception as e:
            logger.warning(f"Не удалось определить выбросы в колонке '{col}': {e}")
            continue
            
        if outlier_indices:
            bounds = {}
            if method == "iqr":
                bounds = {"lower": round(float(q1 - multiplier * iqr), 2), 
                          "upper": round(float(q3 + multiplier * iqr), 2)}
                
            report["by_column"][col] = {
                "count": len(outlier_indices),
                "rate_pct": round(len(outlier_indices) / len(df) * 100, 2),
                "method": method,
                "indices": outlier_indices[:50],  # Лимит для UI/экспорта
                "bounds": bounds
            }
            report["summary"]["total_outliers"] += len(outlier_indices)
            report["summary"]["outlier_columns"].append(col)
            
    return report


def get_outliers_df(report: dict, df_original: pd.DataFrame) -> pd.DataFrame:
    """Преобразует отчёт о выбросах в плоский DataFrame для UI"""
    rows = []
    for col, info in report.get("by_column", {}).items():
        for idx in info.get("indices", []):
            rows.append({
                "row_index": int(idx),
                "column": col,
                "value": df_original.loc[idx, col],
                "method": info["method"],
                "bounds": info.get("bounds", {})
            })
    return pd.DataFrame(rows)