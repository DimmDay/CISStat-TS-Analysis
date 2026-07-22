# app/eda/distributions.py
"""
Модуль для анализа распределений числовых данных.
Извлечено из app.py (пункт B.2 EXTRACTION_PLAN.md).
"""
import numpy as np
import pandas as pd
from scipy import stats


def detect_distribution_type(series: pd.Series) -> str:
    """
    Определяет тип распределения числового ряда.
    
    Args:
        series: Числовой ряд для анализа
        
    Returns:
        Строка с описанием типа распределения
        
    Examples:
        >>> import pandas as pd
        >>> import numpy as np
        >>> s = pd.Series(np.random.randn(100))
        >>> detect_distribution_type(s)
        'Непрерывное - Нормальное'
    """
    data = series.dropna()
    
    if len(data) < 30:
        return "Недостаточно данных для определения (<30 точек)"
    
    if len(data) > 5000:
        data = data.sample(5000, random_state=42)
    
    is_discrete = (data == data.astype(int)).all()
    unique_count = data.nunique()
    min_val = data.min()
    mean_v = data.mean()
    var_v = data.var()
    skew = stats.skew(data)
    kurt = stats.kurtosis(data)
    
    # Проверка дискретных распределений
    if is_discrete and unique_count < 100:
        if unique_count == 2 and min_val >= 0:
            return "Дискретное - Биномальное"
        elif min_val >= 1 and var_v > mean_v**2:
            return "Дискретное - Геометрическое"
        elif var_v > mean_v * 1.3:
            return "Дискретное - Отрицательное биномальное"
        elif abs(var_v - mean_v) < mean_v * 0.25:
            return "Дискретное - Пуассона"
        elif unique_count < len(data) * 0.4:
            return "Дискретное - Гипергеометрическое (оценка)"
        return "Дискретное - Эмпирическое"
    
    # Проверка непрерывных распределений
    candidates = {
        "Нормальное": stats.norm,
        "Логнормальное": stats.lognorm,
        "Экспоненциальное": stats.expon,
        "Равномерное": stats.uniform,
        "Стьюдента": stats.t,
        "Хи-квадрат": stats.chi2,
        "Гамма": stats.gamma
    }
    
    best_name, best_ks = None, np.inf
    for name, dist in candidates.items():
        try:
            if name in ["Логнормальное", "Экспоненциальное", "Хи-квадрат"] and min_val <= 0:
                continue
            params = dist.fit(data)
            ks_stat, _ = stats.kstest(data, dist.name, args=params)
            if ks_stat < best_ks:
                best_ks, best_name = ks_stat, name
        except:
            continue
    
    prefix = "Непрерывное - "
    if best_name is None:
        if abs(skew) < 0.5:
            return f"{prefix}Нормальное (по асимметрии)"
        if skew > 0.5:
            return f"{prefix}Правосторонняя асимметрия"
        if skew < -0.5:
            return f"{prefix}Левосторонняя асимметрия"
        return f"{prefix}Неопределённое"
    
    if best_ks < 0.06:
        return f"{prefix}{best_name}"
    elif best_ks < 0.14:
        return f"{prefix}{best_name} (близко)"
    else:
        if skew > 0.6:
            return f"{prefix}Правосторонняя асимметрия"
        if skew < -0.6:
            return f"{prefix}Левосторонняя асимметрия"
        return f"{prefix}Эмпирическое (сложная форма)"