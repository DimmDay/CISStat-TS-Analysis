# app/preprocessing/transforms.py
import numpy as np
import pandas as pd
from typing import Optional, Literal

# Типизация для методов дифференцирования
DiffMethod = Literal['first', 'seasonal', 'second', 'log', 'fractional', 'combined']

def apply_differencing(
    series: pd.Series, 
    method: DiffMethod = 'first', 
    d: int = 1, 
    s: Optional[int] = None, 
    frac_d: Optional[float] = None
) -> pd.Series:
    """
    Чистая функция дифференцирования временного ряда (Single Series).
    ⚠️ ВНИМАНИЕ: Сохраняет legacy-поведение (dropna в начале), 
    чтобы гарантировать идентичность результатов для одиночных рядов.
    Для Panel Data используйте apply_differencing_panel().
    """
    s_clean = series.dropna()
    
    if s_clean.empty:
        return pd.Series(dtype=float, index=s_clean.index)

    if method == 'first':
        return s_clean.diff(d).dropna()
    
    elif method == 'seasonal':
        s_period = s if s is not None else 12
        return s_clean.diff(s_period).dropna()
    
    elif method == 'second':
        return s_clean.diff(2).dropna()
    
    elif method == 'log':
        if (s_clean <= 0).any():
            raise ValueError("Логарифмическое различие требует положительных значений")
        return np.log(s_clean).diff().dropna()
    
    elif method == 'fractional':
        if frac_d is None or not (0 < frac_d < 1):
            raise ValueError("Дробный порядок должен быть в диапазоне (0, 1)")
        
        # ИСПРАВЛЕНИЕ LEGACY BUG: Используем рекуррентную формулу вместо scipy.special.comb
        weights = np.zeros(len(s_clean))
        weights[0] = 1.0
        for k in range(1, len(s_clean)):
            weights[k] = weights[k-1] * (frac_d - k + 1) / k
            if abs(weights[k]) < 1e-5:  # Обрезаем малые веса
                weights[k:] = 0
                break
        
        result = pd.Series(0.0, index=s_clean.index)
        for k, w in enumerate(weights):
            if w == 0: break
            result += w * s_clean.shift(k)
            
        return result.dropna()
    
    elif method == 'combined':
        # ИСПРАВЛЕНИЕ LEGACY BUG: Реализуем отсутствовавший метод
        s_period = s if s is not None else 12
        return s_clean.diff(s_period).diff(d).dropna()
    
    else:
        raise ValueError(f"Неизвестный метод дифференцирования: {method}")


def apply_differencing_panel(
    df: pd.DataFrame,
    target_col: str,
    entity_col: str,
    method: DiffMethod = 'first',
    d: int = 1,
    s: Optional[int] = None,
    frac_d: Optional[float] = None
) -> pd.DataFrame:
    """
    🛡️ PANEL-SAFE WRAPPER (Защита от Data Leakage - Правило 15).
    Применяет дифференцирование строго внутри каждой сущности.
    В отличие от legacy-функции, НЕ делает dropna(), чтобы сохранить 
    выравнивание индексов (MultiIndex) для корректной работы groupby().transform().
    """
    def _diff_safe(group: pd.Series) -> pd.Series:
        # Внутренняя логика без dropna() в начале, чтобы не сломать индексы панели
        if method == 'first':
            res = group.diff(d)
        elif method == 'seasonal':
            res = group.diff(s if s is not None else 12)
        elif method == 'second':
            res = group.diff(2)
        elif method == 'log':
            if (group <= 0).any():
                raise ValueError("Логарифмическое различие требует положительных значений")
            res = np.log(group).diff()
        elif method == 'fractional':
            if frac_d is None or not (0 < frac_d < 1):
                raise ValueError("Дробный порядок должен быть в диапазоне (0, 1)")
            weights = [1.0]
            for k in range(1, len(group)):
                w = weights[-1] * (frac_d - k + 1) / k
                if abs(w) < 1e-5: break
                weights.append(w)
            
            res = pd.Series(0.0, index=group.index)
            for k, w in enumerate(weights):
                res += w * group.shift(k)
        elif method == 'combined':
            res = group.diff(s if s is not None else 12).diff(d)
        else:
            raise ValueError(f"Неизвестный метод: {method}")
            
        return res

    # Строгая группировка по entity_col
    df_result = df.copy()
    df_result[target_col] = df.groupby(entity_col, group_keys=False)[target_col].transform(_diff_safe)
    
    return df_result