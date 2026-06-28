# app/classification/classifier.py
"""
Модуль для классификации колонок DataFrame по типам данных.
Извлечено из app.py (пункт B.4 EXTRACTION_PLAN.md).
"""
import pandas as pd
from typing import Dict, List


def classify_columns(df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Классифицирует колонки DataFrame по типам данных.
    
    Args:
        df: DataFrame для классификации
        
    Returns:
        Словарь с типами колонок:
        {
            'num': список числовых колонок,
            'cat': список категориальных колонок,
            'date': список временных колонок
        }
        
    Note:
        - Числовые колонки: все числовые типы данных
        - Категориальные колонки: object/string типы с 1 < nunique < 100
        - Временные колонки: datetime64 типы
        
    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'num': [1, 2, 3],
        ...     'cat': ['a', 'b', 'c'],
        ...     'date': pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'])
        ... })
        >>> classify_columns(df)
        {'num': ['num'], 'cat': ['cat'], 'date': ['date']}
    """
    if df.empty:
        return {'num': [], 'cat': [], 'date': []}
    
    # Числовые колонки
    num_cols = df.select_dtypes(include='number').columns.tolist()
    
    # Временные колонки
    date_cols = df.select_dtypes(include=['datetime64[ns]', 'datetime64']).columns.tolist()
    
    # Категориальные колонки: object/string с 1 < nunique < 100
    cat_cols = []
    for col in df.select_dtypes(include=['object', 'string']).columns:
        n_unique = df[col].nunique()
        if 1 < n_unique < 100:
            cat_cols.append(col)
    
    return {
        'num': num_cols,
        'cat': cat_cols,
        'date': date_cols
    }