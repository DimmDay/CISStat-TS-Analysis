# app/eda/correlation.py
"""
Модуль для корреляционного анализа числовых данных.
Извлечено из app.py (пункт B.3 EXTRACTION_PLAN.md).
"""
import pandas as pd
from typing import List, Dict


def find_significant_correlations(
    df: pd.DataFrame,
    num_cols: List[str],
    threshold: float = 0.5
) -> List[Dict]:
    """
    Находит значимые корреляции между числовыми колонками.
    
    Args:
        df: DataFrame с данными
        num_cols: Список числовых колонок для анализа
        threshold: Порог значимости корреляции (по умолчанию 0.5)
        
    Returns:
        Список словарей с информацией о значимых связях:
        [
            {
                'pair': 'col1 ↔ col2',
                'val': 0.85,
                'desc': 'Сильная прямая связь (r = 0.85)'
            },
            ...
        ]
        
    Examples:
        >>> import pandas as pd
        >>> import numpy as np
        >>> df = pd.DataFrame({'a': [1, 2, 3], 'b': [2, 4, 6]})
        >>> find_significant_correlations(df, ['a', 'b'], threshold=0.5)
        [{'pair': 'a ↔ b', 'val': 1.0, 'desc': 'Сильная прямая связь (r = 1.00)'}]
    """
    if len(num_cols) < 2:
        return []
    
    # Вычисляем матрицу корреляции
    corr_matrix = df[num_cols].corr()
    
    # Ищем значимые связи
    significant_links = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            val = corr_matrix.iloc[i, j]
            if abs(val) >= threshold:
                col1, col2 = corr_matrix.columns[i], corr_matrix.columns[j]
                strength = "Сильная" if abs(val) >= 0.7 else "Умеренная"
                direction = "прямая (+)" if val > 0 else "обратная (-)"
                significant_links.append({
                    "pair": f"{col1} ↔ {col2}",
                    "val": val,
                    "desc": f"{strength} {direction} связь (`r = {val:.2f}`)"
                })
    
    return significant_links