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

def yeo_johnson_manual(y: np.ndarray, lmbda: float) -> np.ndarray:
    """
    Ручная реализация трансформации Yeo-Johnson.
    Используется, когда auto_lambda=False и нужен конкретный lambda.
    """
    result = np.zeros_like(y, dtype=float)
    pos = y >= 0
    neg = ~pos
    if lmbda != 0:
        result[pos] = ((y[pos] + 1) ** lmbda - 1) / lmbda
    else:
        result[pos] = np.log1p(y[pos])
    if lmbda != 2:
        result[neg] = -((-y[neg] + 1) ** (2 - lmbda) - 1) / (2 - lmbda)
    else:
        result[neg] = -np.log1p(-y[neg])
    return result


def test_heteroskedasticity(series, window=30):
    """Тест на гетероскедастичность через скользящее std"""
    if len(series) < window * 2:
        return {
            'bp_pvalue': None,
            'is_hetero': None,
            'rolling_std_corr': None,
            'amplitude_ratio': None
        }

    # 1. Тест Бройша-Пагана (если есть statsmodels)
    try:
        from statsmodels.stats.diagnostic import het_breuschpagan
        import statsmodels.api as sm

        # Регрессия на тренд для получения остатков
        X = sm.add_constant(np.arange(len(series)))
        model = sm.OLS(series, X).fit()
        resid = model.resid

        # Тест Бройша-Пагана
        _, bp_pvalue, _, _ = het_breuschpagan(resid, X)
        is_hetero = bp_pvalue < 0.05
    except Exception:
        bp_pvalue = None
        is_hetero = None

    # 2. Корреляция между rolling_std и rolling_mean
    rolling_mean = series.rolling(window=window).mean()
    rolling_std = series.rolling(window=window).std()

    valid_mask = rolling_mean.notna() & rolling_std.notna() & (rolling_std > 0)
    if valid_mask.sum() > 10:
        corr = rolling_mean[valid_mask].corr(rolling_std[valid_mask])
    else:
        corr = None

    # 3. Отношение амплитуд (последняя треть / первая треть)
    n = len(series)
    first_third = series.iloc[:n//3]
    last_third = series.iloc[2*n//3:]
    if len(first_third) > 0 and len(last_third) > 0:
        amplitude_ratio = last_third.std() / (first_third.std() + 1e-10)
    else:
        amplitude_ratio = None

    return {
        'bp_pvalue': bp_pvalue,
        'is_hetero': is_hetero,
        'rolling_std_corr': corr,
        'amplitude_ratio': amplitude_ratio
    }



def calculate_smoothing_metrics(original: pd.Series, smoothed: pd.Series) -> dict:
    """Расчёт метрик качества сглаживания"""
    metrics = {}

    # 1. SNR (Signal-to-Noise Ratio)
    signal_power = smoothed.var()
    noise = original - smoothed
    noise_power = noise.var()
    metrics['snr'] = 10 * np.log10(signal_power / (noise_power + 1e-10)) if noise_power > 0 else np.inf

    # 2. Корреляция с исходным рядом
    metrics['correlation'] = original.corr(smoothed)

    # 3. Сглаженность (smoothness) — сумма квадратов вторых разностей
    # Чем МЕНЬШЕ, тем ГЛАЖЕ ряд
    second_diff_orig = original.diff().diff().dropna()
    second_diff_smooth = smoothed.diff().diff().dropna()
    metrics['roughness_orig'] = np.sum(second_diff_orig**2)
    metrics['roughness_smooth'] = np.sum(second_diff_smooth**2)
    metrics['smoothness_ratio'] = (metrics['roughness_orig'] / 
                                (metrics['roughness_smooth'] + 1e-10))

    # 4. Сохранение тренда (R² линейного тренда)
    from scipy.stats import linregress
    slope_orig, _, r_orig, _, _ = linregress(range(len(original)), original)
    slope_smooth, _, r_smooth, _, _ = linregress(range(len(smoothed)), smoothed)
    metrics['r2_orig'] = r_orig**2
    metrics['r2_smooth'] = r_smooth**2
    metrics['trend_preservation'] = abs(r_smooth**2 - r_orig**2)

    # 5. Потеря информации (разница дисперсий)
    metrics['variance_loss_pct'] = ((original.var() - smoothed.var()) / 
                                (original.var() + 1e-10)) * 100

    # 6. Amplitude reduction (ослабление амплитуды)
    metrics['amplitude_reduction'] = 1 - (smoothed.std() / (original.std() + 1e-10))

    return metrics



def run_stationarity_tests(series: pd.Series, max_lag: int = None) -> dict:
    """
    Запускает 4 теста стационарности и возвращает консенсус.

    Returns:
        dict с ключами:
        - adf: {'stat': float, 'pvalue': float, 'is_stationary': bool}
        - kpss: {'stat': float, 'pvalue': float, 'is_stationary': bool}
        - pp: {'stat': float, 'pvalue': float, 'is_stationary': bool}
        - za: {'stat': float, 'pvalue': float, 'is_stationary': bool, 'breakpoint': int} (если доступен)
        - consensus: 'stationary' | 'non-stationary' | 'trend-stationary' | 'inconclusive'
        - recommendation: str
    """
    results = {}
    n = len(series)

    if n < 30:
        return {'error': 'Недостаточно данных (нужно ≥ 30)'}

    try:
        from statsmodels.tsa.stattools import adfuller, kpss
        from statsmodels.tsa.stattools import PhillipsPerron

        # ── 1. ADF TEST ──────────────────────────
        # H0: ряд имеет единичный корень (нестационарен)
        # H1: ряд стационарен
        if max_lag is None:
            max_lag_adf = min(int(12 * (n / 100) ** 0.25), n // 3)
        else:
            max_lag_adf = max_lag

        adf_result = adfuller(series.dropna(), autolag='AIC', maxlag=max_lag_adf)
        results['adf'] = {
            'stat': adf_result[0],
            'pvalue': adf_result[1],
            'lags': adf_result[2],
            'is_stationary': adf_result[1] < 0.05,
            'critical_values': adf_result[4]
        }

        # ─ 2. KPSS TEST ─────────────────────────
        # H0: ряд стационарен (вокруг уровня или тренда)
        # H1: ряд нестационарен
        # Тестируем два варианта: level (вокруг константы) и trend (вокруг тренда)
        try:
            kpss_level = kpss(series.dropna(), regression='c', nlags='auto')
            kpss_trend = kpss(series.dropna(), regression='ct', nlags='auto')
            results['kpss'] = {
                'stat_level': kpss_level[0],
                'pvalue_level': kpss_level[1],
                'stat_trend': kpss_trend[0],
                'pvalue_trend': kpss_trend[1],
                'is_stationary_level': kpss_level[1] > 0.05,
                'is_stationary_trend': kpss_trend[1] > 0.05
            }
        except Exception as e:
            results['kpss'] = {'error': str(e)}

        # ── 3. PHILLIPS-PERRON TEST ──────────────
        # Альтернатива ADF, устойчива к гетероскедастичности
        try:
            pp_result = PhillipsPerron(series.dropna(), lags=max_lag_adf)
            results['pp'] = {
                'stat': pp_result.stat,
                'pvalue': pp_result.pvalue,
                'is_stationary': pp_result.pvalue < 0.05
            }
        except Exception:
            # Fallback: если PP недоступен, используем ADF как proxy
            results['pp'] = {
                'stat': adf_result[0],
                'pvalue': adf_result[1],
                'is_stationary': adf_result[1] < 0.05,
                'note': 'PP недоступен, используется ADF'
            }

        # ── 4. ZIVOT-ANDREWS TEST (опционально) ──
        # Учитывает структурные разрывы
        try:
            from statsmodels.tsa.stattools import zivot_andrews
            za_result = zivot_andrews(series.dropna(), model='c')
            results['za'] = {
                'stat': za_result[0],
                'pvalue': za_result[1],  # Может быть недоступен в старых версиях
                'breakpoint': za_result[2] if len(za_result) > 2 else None,
                'is_stationary': za_result[0] < -4.8  # Приблизительный критический уровень
            }
        except Exception:
            results['za'] = {'note': 'Тест Zivot-Andrews недоступен (statsmodels < 0.14)'}

        # ── 5. КОНСЕНСУС ─────────────────────────
        adf_stat = results['adf']['is_stationary']
        kpss_level_stat = results['kpss'].get('is_stationary_level', None)
        kpss_trend_stat = results['kpss'].get('is_stationary_trend', None)
        pp_stat = results['pp']['is_stationary']

        if adf_stat and kpss_level_stat:
            consensus = 'stationary'
            recommendation = '✅ Ряд стационарен. Дифференцирование не требуется.'
        elif not adf_stat and kpss_trend_stat:
            consensus = 'trend-stationary'
            recommendation = '⚠️ Ряд стационарен вокруг тренда. Достаточно удалить тренд (детренд).'
        elif not adf_stat and not kpss_level_stat:
            consensus = 'non-stationary'
            if pp_stat:
                recommendation = '⚠️ ADF и KPSS противоречат PP. Попробуйте другое дифференцирование.'
            else:
                recommendation = ' Ряд нестационарен. Требуется дифференцирование.'
        else:
            consensus = 'inconclusive'
            recommendation = '️ Результаты тестов противоречивы. Визуальный анализ + пробное дифференцирование.'

        results['consensus'] = consensus
        results['recommendation'] = recommendation

    except ImportError as e:
        results['error'] = f'Не установлены необходимые библиотеки: {e}'
    except Exception as e:
        results['error'] = str(e)

    return results



def calculate_scaling_metrics(original: pd.Series, scaled: pd.Series) -> dict:
    """Расчёт метрик качества масштабирования"""
    metrics = {}

    # 1. Диапазон
    metrics['range_orig'] = original.max() - original.min()
    metrics['range_scaled'] = scaled.max() - scaled.min()

    # 2. Среднее и стандартное отклонение
    metrics['mean_orig'] = original.mean()
    metrics['mean_scaled'] = scaled.mean()
    metrics['std_orig'] = original.std()
    metrics['std_scaled'] = scaled.std()

    # 3. Выбросы (по правилу 3σ)
    def count_outliers(series):
        mean, std = series.mean(), series.std()
        return ((series < mean - 3*std) | (series > mean + 3*std)).sum()

    metrics['outliers_orig'] = count_outliers(original)
    metrics['outliers_scaled'] = count_outliers(scaled)

    # 4. Асимметрия (skewness)
    metrics['skew_orig'] = original.skew()
    metrics['skew_scaled'] = scaled.skew()

    # 5. Эксцесс (kurtosis)
    metrics['kurt_orig'] = original.kurtosis()
    metrics['kurt_scaled'] = scaled.kurtosis()

    # 6. Коэффициент вариации
    metrics['cv_orig'] = original.std() / (abs(original.mean()) + 1e-10)
    metrics['cv_scaled'] = scaled.std() / (abs(scaled.mean()) + 1e-10)

    return metrics




def compute_row_properties(series: pd.Series, name: str = "") -> dict:
    """
    Вычисляет полный набор свойств временного ряда.

    Returns:
        dict со всеми свойствами
    """
    if series.empty or len(series) < 10:
        return {'error': f'Недостаточно данных ({len(series)} точек)'}

    props = {}

    # 1. СТАЦИОНАРНОСТЬ (ADF Test)
    try:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(series.dropna(), autolag='AIC')
        adf_pvalue = adf_result[1]
        props['stationarity'] = '✅ Стационарен' if adf_pvalue < 0.05 else '❌ Нестационарен'
        props['stationarity_detail'] = f'(p={adf_pvalue:.4f})'
    except Exception as e:
        props['stationarity'] = '⚠️ Не удалось вычислить'
        props['stationarity_detail'] = str(e)

    # 2. ДЕТЕРМИНИРОВАННОСТЬ (R² тренда)
    try:
        from scipy.stats import linregress
        x = np.arange(len(series))
        slope, intercept, r_value, _, _ = linregress(x, series)
        r_squared = r_value ** 2
        if r_squared > 0.7:
            props['determinism'] = '📈 Детерминированный'
        elif r_squared > 0.3:
            props['determinism'] = '⚠️ Смешанный'
        else:
            props['determinism'] = ' Стохастический'
        props['determinism_detail'] = f'(R²={r_squared:.3f})'
    except Exception as e:
        props['determinism'] = '️ Не удалось вычислить'
        props['determinism_detail'] = str(e)

    # 3. ЧАСТОТА РЯДА
    try:
        freq = pd.infer_freq(series.index)
        if freq:
            props['frequency'] = f'✅ Регулярная ({freq})'
        else:
            props['frequency'] = '⚠️ Нерегулярная'
        props['frequency_detail'] = ''
    except Exception:
        props['frequency'] = '⚠️ Не удалось определить'
        props['frequency_detail'] = ''

    # 4. ГЕТЕРОСКЕДАСТИЧНОСТЬ (упрощённый тест)
    try:
        rolling_std = series.rolling(window=min(30, len(series)//3)).std()
        correlation = series.rolling(window=min(30, len(series)//3)).mean().corr(rolling_std)
        if abs(correlation) > 0.5:
            props['heteroskedasticity'] = '❌ Гетероскедастичность'
        else:
            props['heteroskedasticity'] = '✅ Гомоскедастичность'
        props['heteroskedasticity_detail'] = f'(corr={correlation:.3f})'
    except Exception:
        props['heteroskedasticity'] = '⚠️ Не удалось вычислить'
        props['heteroskedasticity_detail'] = ''

    # 5. АВТОКОРРЕЛЯЦИЯ (Ljung-Box)
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb_result = acorr_ljungbox(series.dropna(), lags=[10], return_df=True)
        lb_pvalue = lb_result['lb_pvalue'].values[0]
        if lb_pvalue < 0.05:
            props['autocorrelation'] = '❌ Есть автокорреляция'
        else:
            props['autocorrelation'] = '✅ Белый шум'
        props['autocorrelation_detail'] = f'(p={lb_pvalue:.4f})'
    except Exception:
        props['autocorrelation'] = '⚠️ Не удалось вычислить'
        props['autocorrelation_detail'] = ''

    # 6. НОРМАЛЬНОСТЬ (Jarque-Bera)
    try:
        from scipy.stats import jarque_bera
        jb_stat, jb_pvalue, _, _ = jarque_bera(series.dropna())
        if jb_pvalue < 0.05:
            props['normality'] = '❌ Отклонение от нормальности'
        else:
            props['normality'] = '✅ Нормальное распределение'
        props['normality_detail'] = f'(p={jb_pvalue:.4f})'
    except Exception:
        props['normality'] = '⚠️ Не удалось вычислить'
        props['normality_detail'] = ''

    # 7. НАПРАВЛЕНИЕ ТРЕНДА
    try:
        from scipy.stats import linregress
        slope, _, _, _, _ = linregress(range(len(series)), series)
        if slope > 0.001:
            props['trend'] = f'📈 Восходящий (Slope={slope:.4f})'
        elif slope < -0.001:
            props['trend'] = f'📉 Нисходящий (Slope={slope:.4f})'
        else:
            props['trend'] = f'➡️ Без тренда (Slope={slope:.4f})'
        props['trend_detail'] = ''
    except Exception:
        props['trend'] = '⚠️ Не удалось вычислить'
        props['trend_detail'] = ''

    # 8. СЕЗОННОСТЬ (сила)
    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(series.dropna(), period=min(12, len(series)//4))
        result = stl.fit()
        seasonal_strength = 1 - (result.resid.var() / (result.seasonal + result.resid).var())
        if seasonal_strength > 0.6:
            props['seasonality'] = f'✅ Сильная (S={seasonal_strength:.2f})'
        elif seasonal_strength > 0.3:
            props['seasonality'] = f'️ Умеренная (S={seasonal_strength:.2f})'
        else:
            props['seasonality'] = f'❌ Слабая/Нет (S={seasonal_strength:.2f})'
        props['seasonality_detail'] = ''
    except Exception:
        props['seasonality'] = '⚠️ Не удалось вычислить'
        props['seasonality_detail'] = ''

    # 9. СЕЗОННЫЕ ПЕРИОДЫ (ACF)
    try:
        from statsmodels.tsa.stattools import acf
        max_lag = min(60, len(series) // 4)
        acf_values = acf(series.dropna(), nlags=max_lag)
        conf_int = 1.96 / np.sqrt(len(series))
        significant_lags = np.where(np.abs(acf_values[1:]) > conf_int)[0] + 1

        if len(significant_lags) > 0:
            # Ищем периодические пики
            periods = []
            for lag in significant_lags:
                if lag > 2:
                    periods.append(lag)
            props['seasonal_periods'] = f'✅ Обнаружены: {periods[:3]}'
        else:
            props['seasonal_periods'] = '⚠️ Не обнаружены'
        props['seasonal_periods_detail'] = ''
    except Exception:
        props['seasonal_periods'] = '⚠️ Не удалось вычислить'
        props['seasonal_periods_detail'] = ''

    # 10. ДОЛГАЯ ПАМЯТЬ (Hurst Exponent)
    try:

        H = hurst_exponent(series.dropna())
        if H > 0.6:
            props['long_memory'] = f'🔴 Персистентность (H={H:.2f})'
        elif H < 0.4:
            props['long_memory'] = f'🔵 Антиперсистентность (H={H:.2f})'
        else:
            props['long_memory'] = f'⚪ Случайное блуждание (H={H:.2f})'
        props['long_memory_detail'] = ''
    except Exception:
        props['long_memory'] = '⚠️ Не удалось вычислить'
        props['long_memory_detail'] = ''

    # 11. СТАТИСТИКИ РАСПРЕДЕЛЕНИЯ
    props['mean'] = f'{series.mean():.2f}'
    props['median'] = f'{series.median():.2f}'
    props['std'] = f'{series.std():.2f}'
    props['skewness'] = f'{series.skew():.3f}'
    props['kurtosis'] = f'{series.kurtosis():.3f}'

    # Тип распределения (упрощённо)
    skew = series.skew()
    kurt = series.kurtosis()
    if abs(skew) < 0.5 and abs(kurt - 3) < 1:
        props['distribution_type'] = 'Нормальное'
    elif skew > 1:
        props['distribution_type'] = 'Правосторонняя асимметрия'
    elif skew < -1:
        props['distribution_type'] = 'Левосторонняя асимметрия'
    else:
        props['distribution_type'] = 'Эмпирическое'

    return props


