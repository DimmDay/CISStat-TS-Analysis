# app/core/passport.py
"""
Модуль паспорта свойств временного ряда.
Содержит эталонную реализацию расчёта 13 метрик ряда, а также функции
сравнения паспортов (v1.0 vs v1.1 vs v1.2) и упрощённого расчёта свойств.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).

Согласно EXTRACTION_PLAN.md:
- calculate_ts_passport: эталонная реализация (A.2)
- _compare_ts_props: сравнение двух паспортов (A.3)
- _calc_ts_props: упрощённый паспорт для сравнения До/После (A.4)
- _hurst_exponent: приватная функция для показателя Хёрста
"""
import hashlib
import logging
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import linregress, jarque_bera
from scipy.signal import periodogram, find_peaks
from scipy.fft import fft, fftfreq
from statsmodels.tsa.stattools import adfuller, acf as acf_func
from statsmodels.tsa.seasonal import STL
from statsmodels.stats.diagnostic import acorr_ljungbox

from app.data.detectors import smart_to_datetime

logger = logging.getLogger(__name__)

_MIN_PASSPORT_POINTS = 30
_NORMALITY_RELIABILITY_THRESHOLD = 2000
_FREQ_TO_SEASONAL_PERIOD = {
    "D": 7,
    "B": 5,
    "W": 52,
    "M": 12,
    "ME": 12,
    "MS": 12,
    "BM": 12,
    "BME": 12,
    "BMS": 12,
    "Q": 4,
    "QE": 4,
    "QS": 4,
}


# ═══════════════════════════════════════════════════════
# ДЕТЕРМИНИРОВАННОЕ ОКРУГЛЕНИЕ FLOAT-ПОЛЕЙ ПАСПОРТА
# ═══════════════════════════════════════════════════════
# Snapshot-тесты падали на дрейфе ~1e-15 между релизами numpy/scipy и железом.
# Округление до 10 знаков делает снимки стабильными без потери семантической
# точности (ADF p-value, Hurst, slope, seasonal_strength -- 1e-10 достаточно).
_PASSPORT_FLOAT_PRECISION = 10


def _round_floats(obj, precision: int = _PASSPORT_FLOAT_PRECISION):
    """Рекурсивно округляет все float-значения в dict/list/tuple/np.floating."""
    if isinstance(obj, dict):
        return {k: _round_floats(v, precision) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, precision) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_round_floats(v, precision) for v in obj)
    if isinstance(obj, (float, np.floating)):
        return round(float(obj), precision)
    return obj


# ═══════════════════════════════════════════════════════
# ПРИВАТНЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════

def _hurst_exponent(series: np.ndarray, max_lag: int = 20) -> float:
    """
    Вычисление показателя Хёрста через R/S-анализ.
    
    H ∈ [0, 1]:
    - H > 0.55 → персистентность (тренд усиливается)
    - H ≈ 0.5  → случайное блуждание
    - H < 0.45 → антиперсистентность (возврат к среднему)
    
    Args:
        series: Числовой массив (numpy array)
        max_lag: Максимальный лаг для анализа (по умолчанию 20)
    
    Returns:
        float: Значение показателя Хёрста
    """
    lags = range(2, max_lag)
    # Защита от деления на ноль через max(..., 1e-8)
    tau = [max(np.std(np.subtract(series[lag:], series[:-lag])), 1e-8) for lag in lags]
    try:
        return float(np.polyfit(np.log(lags), np.log(tau), 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return 0.5


def prepare_passport_series(
    dataframe: pd.DataFrame,
    target_column: str,
    date_column: str,
    *,
    min_points: int = _MIN_PASSPORT_POINTS,
) -> pd.Series:
    """Собирает единственный канонический ряд для расчёта паспорта.

    Невалидные пары ``(дата, значение)`` удаляются, даты приводятся к UTC
    и возвращаются как timezone-naive ``DatetimeIndex``. Панельные данные
    не агрегируются молча: повторяющиеся даты требуют явного решения выше
    по стеку. Исходный DataFrame не изменяется.
    """
    if target_column not in dataframe.columns:
        raise ValueError(f"Колонка значений «{target_column}» не найдена")
    if date_column not in dataframe.columns:
        raise ValueError(f"Колонка даты «{date_column}» не найдена")
    if target_column == date_column:
        raise ValueError("Колонки даты и значений должны различаться")
    if min_points < 1:
        raise ValueError("min_points должен быть положительным")

    # Единый platform detector корректно трактует числовые годы: голый
    # pd.to_datetime(2024) ошибочно означает наносекунды после Unix epoch.
    dates = pd.to_datetime(
        smart_to_datetime(dataframe[date_column]), errors="coerce", utc=True
    )
    values = pd.to_numeric(dataframe[target_column], errors="coerce")
    finite = pd.Series(
        np.isfinite(values.to_numpy(dtype=float, na_value=np.nan)),
        index=dataframe.index,
    )
    valid = dates.notna() & values.notna() & finite
    prepared = pd.DataFrame(
        {
            "date": dates.loc[valid].dt.tz_convert(None),
            "value": values.loc[valid].astype(float),
        }
    ).sort_values("date", kind="mergesort")

    if prepared["date"].duplicated().any():
        raise ValueError(
            "Обнаружены повторяющиеся даты: паспорт требует один ряд на одну дату"
        )
    if len(prepared) < min_points:
        raise ValueError(
            f"Недостаточно данных: нужно минимум {min_points} валидных точек"
        )

    return pd.Series(
        prepared["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(prepared["date"].to_numpy()),
        name=target_column,
    )


def _normalize_passport_series(analysis_series: pd.Series) -> pd.Series:
    """Нормализует прямой вызов ядра тем же контрактом, что и DataFrame."""
    if not isinstance(analysis_series, pd.Series):
        raise ValueError("analysis_series должен быть pandas.Series")
    frame = pd.DataFrame(
        {
            "__passport_date": analysis_series.index,
            "__passport_value": analysis_series.to_numpy(),
        }
    )
    result = prepare_passport_series(
        frame,
        "__passport_value",
        "__passport_date",
        min_points=_MIN_PASSPORT_POINTS,
    )
    result.name = analysis_series.name
    return result


def series_fingerprint(series: pd.Series) -> str:
    """Возвращает устойчивый SHA-256 fingerprint значений вместе с индексом.

    Ряд сортируется по времени, поэтому перестановка строк не создаёт ложную
    устарелость. В отличие от агрегатного checksum учитывается каждая пара
    ``(timestamp, value)``.
    """
    if not isinstance(series, pd.Series):
        raise ValueError("series должен быть pandas.Series")
    canonical = series.sort_index(kind="mergesort")
    if canonical.index.has_duplicates:
        raise ValueError("Fingerprint не определён для повторяющихся дат")
    hashed = pd.util.hash_pandas_object(canonical, index=True, categorize=False)
    payload = hashed.to_numpy(dtype="uint64").tobytes()
    return hashlib.sha256(payload).hexdigest()


def _seasonal_period_for_frequency(inferred_freq: Optional[str]) -> Optional[int]:
    if inferred_freq is None:
        return None
    base = "".join(
        ch for ch in str(inferred_freq).upper() if not ch.isdigit()
    ).split("-")[0]
    return _FREQ_TO_SEASONAL_PERIOD.get(base)


def _not_applicable(reason: str, **values: Any) -> Dict[str, Any]:
    return {**values, "applicable": False, "reason": reason}


# ═══════════════════════════════════════════════════════
# ЭТАЛОННАЯ ФУНКЦИЯ: ПОЛНЫЙ ПАСПОРТ СВОЙСТВ РЯДА
# ═══════════════════════════════════════════════════════

def calculate_ts_passport(
    analysis_series: pd.Series,
    df_filtered: Optional[pd.DataFrame] = None,
    ct_f: Optional[Dict[str, List[str]]] = None,
    target_col: Optional[str] = None,
    error_log: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Рассчитывает полный паспорт свойств временного ряда (13 метрик).
    
    Это ЭТАЛОННАЯ реализация. Все места в app.py, которые считают паспорт,
    должны использовать эту функцию (а не свои локальные копии).
    
    Args:
        analysis_series: Временной ряд с DatetimeIndex (основной объект анализа)
        df_filtered: Опциональный DataFrame для расчёта корреляций признаков
        ct_f: Опциональный dict с классификацией колонок {'num': [...], 'cat': [...], 'date': [...]}
        target_col: Опциональное имя целевой колонки для корреляционного анализа
        error_log: Опциональный список для структурированного накопления ошибок
            (формат: {'stage', 'severity', 'error_type', 'message'}). Если не передан,
            ошибки по-прежнему уходят в logger.warning/logger.error, как и раньше —
            передача error_log ничего не меняет в поведении существующих вызовов.
    
    Returns:
        dict с ключами:
        - freq: частота ряда
        - stationarity: ADF тест
        - determinism: R² тренда
        - autocorrelation: Ljung-Box тест
        - normality: Jarque-Bera тест
        - trend: направление тренда
        - correlations: топ-3 корреляции с другими признаками
        - seasonality: сила сезонности (STL)
        - seasonal_periods: периоды из ACF
        - hurst: показатель Хёрста
        - fft: доминирующие частоты
        - periodogram: значимые периоды
        - wavelet: доминирующие масштабы
        - basic_stats: базовые статистики (n, mean, std, min, max)
        - timestamp: время расчёта
        - error: сообщение об ошибке (если ряд < 30 точек или сбой)
    """
    props: Dict[str, Any] = {}
    _log = error_log if error_log is not None else None

    try:
        analysis_series = _normalize_passport_series(analysis_series)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Недостаточно данных"):
            return {"error": "Недостаточно данных (нужно минимум 30 валидных точек)"}
        return {"error": message}

    try:
        # ── 0. ЧАСТОТА РЯДА ──────────────────────────
        try:
            inferred_freq = pd.infer_freq(analysis_series.index)
        except (ValueError, TypeError):
            inferred_freq = None
        is_regular = inferred_freq is not None
        props['freq'] = {
            'value': inferred_freq if inferred_freq else 'Нерегулярная',
            'is_ok': is_regular,
            'is_regular': is_regular,
        }
        
        # ── 1. СТАЦИОНАРНОСТЬ (ADF) ──────────────────
        adf_res = adfuller(analysis_series.dropna(), autolag='AIC')
        adf_p = adf_res[1]
        is_stationary = adf_p < 0.05
        props['stationarity'] = {
            'value': float(adf_p),
            'is_stationary': bool(is_stationary),
            'is_ok': bool(is_stationary),
            'null_hypothesis': 'Ряд имеет единичный корень (нестационарен)',
        }
        
        # ── 2. ДЕТЕРМИНИРОВАННОСТЬ (R² тренда) ───────
        slope, intercept, r_value, p_value, std_err = linregress(
            range(len(analysis_series)), analysis_series.values
        )
        r_squared = float(r_value ** 2)
        is_deterministic = r_squared >= 0.7
        props['determinism'] = {
            'value': r_squared,
            'slope': float(slope),
            'is_deterministic': bool(is_deterministic)
        }
        
        # ── 3. АВТОКОРРЕЛЯЦИЯ (Ljung-Box) ────────────
        if is_regular:
            tested_lag = min(10, max(1, len(analysis_series) // 5))
            lb_res = acorr_ljungbox(analysis_series, lags=[tested_lag])
            if isinstance(lb_res, pd.DataFrame):
                lb_p = float(lb_res['lb_pvalue'].iloc[0])
            else:
                lb_p = float(lb_res[1][0])
            is_white_noise = lb_p > 0.05
            props['autocorrelation'] = {
                'value': lb_p,
                'is_white_noise': bool(is_white_noise),
                'is_ok': bool(is_white_noise),
                'tested_lag': tested_lag,
                'applicable': True,
            }
        else:
            props['autocorrelation'] = _not_applicable(
                'Ljung-Box по временным лагам требует регулярной частоты',
                value=None,
                is_white_noise=None,
                is_ok=None,
                tested_lag=None,
            )
        
        # ── 4. НОРМАЛЬНОСТЬ (Jarque-Bera) ────────────
        jb_res = jarque_bera(analysis_series.dropna())
        jb_p = float(jb_res.pvalue) if hasattr(jb_res, 'pvalue') else float(jb_res[1])
        is_normal = jb_p > 0.05
        props['normality'] = {
            'value': jb_p,
            'is_normal': bool(is_normal),
            'is_ok': bool(is_normal),
            'asymptotic_reliable': len(analysis_series) > _NORMALITY_RELIABILITY_THRESHOLD,
            'reliability_threshold': _NORMALITY_RELIABILITY_THRESHOLD,
        }
        
        # ── 5. НАПРАВЛЕНИЕ ТРЕНДА ────────────────────
        if slope > 0:
            trend_dir = 'up'
        elif slope < 0:
            trend_dir = 'down'
        else:
            trend_dir = 'flat'
        props['trend'] = {
            'slope': float(slope),
            'direction': trend_dir
        }
        
        # ── 6. КОРРЕЛЯЦИЯ ПРИЗНАКОВ ──────────────────
        props['correlations'] = {}
        if df_filtered is not None and ct_f is not None and target_col:
            try:
                num_cols = ct_f.get("num", [])
                if len(num_cols) >= 2 and target_col in num_cols:
                    corr_df = df_filtered[num_cols].corr()
                    target_corr = corr_df[target_col].drop(target_col).sort_values(
                        key=abs, ascending=False
                    )
                    top_corrs = {
                        col: float(val)
                        for col, val in target_corr.head(3).items()
                    }
                    props['correlations'] = {
                        'top3': top_corrs,
                        'max_abs_corr': float(target_corr.iloc[0]) if len(target_corr) > 0 else 0.0
                    }
            except Exception as e:
                logger.warning(f"Не удалось рассчитать корреляции: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'CorrelationError', 'message': str(e)})
        
        # ── 7. СЕЗОННОСТЬ (STL strength) ─────────────
        period = _seasonal_period_for_frequency(inferred_freq)
        if not is_regular:
            props['seasonality'] = _not_applicable(
                'STL требует регулярной частоты',
                strength=None,
                is_seasonal=None,
                period=None,
            )
        elif period is None:
            props['seasonality'] = _not_applicable(
                'Для этой частоты нет обоснованного внутрипериодного цикла',
                strength=None,
                is_seasonal=None,
                period=None,
            )
        elif len(analysis_series) < 2 * period:
            props['seasonality'] = _not_applicable(
                f'Для STL нужно минимум два полных цикла ({2 * period} точек)',
                strength=None,
                is_seasonal=None,
                period=period,
            )
        else:
            try:
                stl_res = STL(analysis_series, period=period, robust=True).fit()
                seasonal_plus_resid = stl_res.seasonal + stl_res.resid
                denominator = float(np.var(seasonal_plus_resid, ddof=1))
                strength_seasonality = (
                    max(0.0, min(1.0, 1 - float(np.var(stl_res.resid, ddof=1)) / denominator))
                    if denominator > 0 else 0.0
                )
                is_seasonal = strength_seasonality > 0.6
                props['seasonality'] = {
                    'strength': float(strength_seasonality),
                    'is_seasonal': bool(is_seasonal),
                    'period': period,
                    'applicable': True,
                }
            except Exception as e:
                logger.warning(f"STL-декомпозиция не удалась: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'STLError', 'message': str(e)})
                props['seasonality'] = _not_applicable(
                    f'STL не рассчитан: {e}',
                    strength=None,
                    is_seasonal=None,
                    period=period,
                )
        
        # ── 8. СЕЗОННЫЕ ПЕРИОДЫ (ACF) ────────────────
        if not is_regular:
            props['seasonal_periods'] = _not_applicable(
                'ACF по временным лагам требует регулярной частоты',
                periods=[],
                count=0,
            )
        else:
            try:
                max_lag = min(60, len(analysis_series) // 4)
                acf_values = acf_func(analysis_series, nlags=max_lag)
                confidence = 1.96 / np.sqrt(len(analysis_series))
                significant_lags = np.where(np.abs(acf_values) > confidence)[0][1:]
                seasonal_periods_acf = []
                for i, lag in enumerate(significant_lags):
                    if i > 0 and lag - significant_lags[i - 1] < 3:
                        continue
                    if lag > 2:
                        seasonal_periods_acf.append(int(lag))
                props['seasonal_periods'] = {
                    'periods': seasonal_periods_acf[:3],
                    'count': len(seasonal_periods_acf[:3]),
                    'applicable': True,
                }
            except Exception as e:
                logger.warning(f"Не удалось рассчитать сезонные периоды: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'ACFError', 'message': str(e)})
                props['seasonal_periods'] = _not_applicable(
                    f'ACF не рассчитан: {e}', periods=[], count=0
                )
        
        # ── 9. ДОЛГАЯ ПАМЯТЬ (Hurst) ─────────────────
        if not is_regular:
            props['hurst'] = _not_applicable(
                'Показатель Хёрста по лагам требует регулярной частоты',
                value=None,
                type=None,
            )
        else:
            hurst_val = _hurst_exponent(analysis_series.values)
            if hurst_val < 0.45:
                memory_type = 'anti_persistent'
            elif hurst_val > 0.55:
                memory_type = 'persistent'
            else:
                memory_type = 'random_walk'
            props['hurst'] = {
                'value': float(hurst_val),
                'type': memory_type,
                'applicable': True,
            }
        
        # ── 10. ДОМИНИРУЮЩИЕ ЧАСТОТЫ (FFT) ───────────
        if not is_regular:
            props['fft'] = _not_applicable(
                'FFT требует регулярной частоты', dominant_periods=[], count=0
            )
        else:
            try:
                n = len(analysis_series)
                y = analysis_series.values - analysis_series.mean()
                yf = fft(y)
                xf = fftfreq(n, 1)[:n // 2]
                amplitude = 2.0 / n * np.abs(yf[0:n // 2])
                peaks, _ = find_peaks(
                    amplitude, height=np.mean(amplitude) + np.std(amplitude)
                )
                ranked_peaks = sorted(peaks, key=lambda p: amplitude[p], reverse=True)
                fft_dominant = [
                    1 / xf[p] for p in ranked_peaks if 0 < xf[p] < 0.5
                ][:3]
                props['fft'] = {
                    'dominant_periods': fft_dominant,
                    'count': len(fft_dominant),
                    'applicable': True,
                }
            except Exception as e:
                logger.warning(f"FFT-анализ не удался: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'FFTError', 'message': str(e)})
                props['fft'] = _not_applicable(
                    f'FFT не рассчитан: {e}', dominant_periods=[], count=0
                )
        
        # ── 11. ПЕРИОДОГРАММА ────────────────────────
        if not is_regular:
            props['periodogram'] = _not_applicable(
                'Периодограмма требует регулярной частоты', periods=[], count=0
            )
        else:
            try:
                freq_per, pxx_per = periodogram(
                    analysis_series.values, fs=1.0, window='hann'
                )
                peaks_per, _ = find_peaks(pxx_per, height=np.median(pxx_per) * 2)
                ranked_peaks = sorted(peaks_per, key=lambda p: pxx_per[p], reverse=True)
                periodogram_periods = [
                    1 / freq_per[p] for p in ranked_peaks if freq_per[p] > 0
                ][:3]
                props['periodogram'] = {
                    'periods': periodogram_periods,
                    'count': len(periodogram_periods),
                    'applicable': True,
                }
            except Exception as e:
                logger.warning(f"Периодограмма не удалась: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'PeriodogramError', 'message': str(e)})
                props['periodogram'] = _not_applicable(
                    f'Периодограмма не рассчитана: {e}', periods=[], count=0
                )
        
        # ── 12. ВЕЙВЛЕТ-МАСШТАБЫ ─────────────────────
        if not is_regular:
            props['wavelet'] = _not_applicable(
                'CWT требует регулярной частоты', scales=[], count=0
            )
        else:
            try:
                import pywt  # Опциональная зависимость
                widths = np.arange(1, min(128, len(analysis_series) // 4))
                cwtmatr, _ = pywt.cwt(
                    analysis_series.values - analysis_series.mean(),
                    widths, 'morl', sampling_period=1
                )
                mean_power = np.mean(np.abs(cwtmatr), axis=1)
                wavelet_peaks, _ = find_peaks(
                    mean_power, height=np.mean(mean_power)
                )
                ranked_peaks = sorted(
                    wavelet_peaks, key=lambda p: mean_power[p], reverse=True
                )
                wavelet_scales = (
                    widths[ranked_peaks[:3]].tolist() if ranked_peaks else []
                )
                props['wavelet'] = {
                    'scales': wavelet_scales,
                    'count': len(wavelet_scales),
                    'applicable': True,
                }
            except ImportError:
                logger.warning("PyWavelets не установлен, wavelet-анализ пропущен")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'PyWTNotInstalled',
                                 'message': 'PyWavelets not installed'})
                props['wavelet'] = _not_applicable(
                    'PyWavelets не установлен', scales=[], count=0
                )
            except Exception as e:
                logger.warning(f"Wavelet-анализ не удался: {e}")
                if _log is not None:
                    _log.append({'stage': 'passport', 'severity': 'warning',
                                 'error_type': 'WaveletError', 'message': str(e)})
                props['wavelet'] = _not_applicable(
                    f'CWT не рассчитан: {e}', scales=[], count=0
                )
        
        # ── 13. БАЗОВЫЕ СТАТИСТИКИ ───────────────────
        props['basic_stats'] = {
            'n': int(len(analysis_series)),
            'mean': float(analysis_series.mean()),
            'std': float(analysis_series.std()),
            'min': float(analysis_series.min()),
            'max': float(analysis_series.max())
        }
        
        props['timestamp'] = pd.Timestamp.now().isoformat()
    
    except Exception as e:
        logger.error(f"Критическая ошибка при расчёте паспорта: {e}")
        if _log is not None:
            _log.append({'stage': 'passport', 'severity': 'critical',
                         'error_type': 'PassportCalculationError', 'message': str(e)})
        props['error'] = str(e)

    # Детерминированное округление float-полей для стабильности snapshot-тестов.
    return _round_floats(props)


# ═══════════════════════════════════════════════════════
# СРАВНЕНИЕ ДВУХ ПАСПОРТОВ (v1.0 vs v1.1 / v1.1 vs v1.2)
# ═══════════════════════════════════════════════════════

def _compare_ts_props(props_old: Dict[str, Any], props_new: Dict[str, Any]) -> Dict[str, Any]:
    """
    Сравнивает ВСЕ 13 свойств паспорта v1.0 и v1.1.
    Поддерживает: числа, строки, списки, булевы значения, вложенные dict.
    
    Args:
        props_old: Старый паспорт (например, v1.0 — до валидации)
        props_new: Новый паспорт (например, v1.1 — после валидации)
    
    Returns:
        dict с ключами:
        - metrics: числовые метрики с delta и delta_pct
        - qualitative_changes: качественные изменения (человекочитаемые)
        - categorical_changes: категориальные/строковые изменения
        - list_changes: изменения списков (FFT, wavelet, periods)
        - boolean_changes: изменения булевых флагов
        - summary: человекочитаемое резюме
    """
    comparison: Dict[str, Any] = {
        'metrics': {},
        'qualitative_changes': [],
        'categorical_changes': {},
        'list_changes': {},
        'boolean_changes': {},
        'summary': ''
    }
    
    # ── 1. ЧИСЛОВЫЕ МЕТРИКИ (10 свойств) ─────────────
    numeric_comparisons = [
        ('n', 'basic_stats', 'Число наблюдений'),
        ('mean', 'basic_stats', 'Среднее'),
        ('std', 'basic_stats', 'Стандартное отклонение'),
        ('value', 'stationarity', 'ADF p-value (стационарность)'),
        ('value', 'determinism', 'R² тренда (детерминированность)'),
        ('value', 'autocorrelation', 'Ljung-Box p-value (автокорреляция)'),
        ('value', 'normality', 'Jarque-Bera p-value (нормальность)'),
        ('slope', 'trend', 'Наклон тренда'),
        ('strength', 'seasonality', 'Сила сезонности'),
        ('value', 'hurst', 'Показатель Хёрста'),
    ]
    
    for key, section, label in numeric_comparisons:
        try:
            old_val = props_old.get(section, {}).get(key)
            new_val = props_new.get(section, {}).get(key)
            if old_val is not None and new_val is not None:
                if pd.notna(old_val) and pd.notna(new_val):
                    delta = new_val - old_val
                    if abs(old_val) > 1e-10:
                        delta_pct = (delta / abs(old_val)) * 100
                    else:
                        delta_pct = 0.0 if abs(delta) < 1e-10 else 100.0
                    comparison['metrics'][label] = {
                        'v_old': float(old_val),
                        'v_new': float(new_val),
                        'delta': float(delta),
                        'delta_pct': float(delta_pct),
                        'type': 'numeric'
                    }
        except Exception as e:
            logger.debug(f"Не удалось сравнить {label}: {e}")
            continue
    
    # ── 2. КАТЕГОРИАЛЬНЫЕ СВОЙСТВА (3 свойства) ──────
    categorical_comparisons = [
        ('value', 'freq', 'Частота ряда'),
        ('direction', 'trend', 'Направление тренда'),
    ]
    
    for key, section, label in categorical_comparisons:
        try:
            old_val = props_old.get(section, {}).get(key)
            new_val = props_new.get(section, {}).get(key)
            if old_val is not None and new_val is not None:
                old_str = str(old_val)
                new_str = str(new_val)
                if old_str != new_str:
                    comparison['categorical_changes'][label] = {
                        'v_old': old_str,
                        'v_new': new_str,
                        'changed': True,
                        'type': 'categorical'
                    }
                else:
                    comparison['categorical_changes'][label] = {
                        'v_old': old_str,
                        'v_new': new_str,
                        'changed': False,
                        'type': 'categorical'
                    }
        except Exception as e:
            logger.debug(f"Не удалось сравнить {label}: {e}")
            continue
    
    # ── 3. СПИСКИ (3 свойства: сезонные периоды, FFT, wavelet) ──
    list_comparisons = [
        ('periods', 'seasonal_periods', 'Сезонные периоды (ACF)'),
        ('dominant_periods', 'fft', 'Доминирующие частоты (FFT)'),
        ('scales', 'wavelet', 'Доминирующие масштабы (Wavelet)'),
    ]
    
    for key, section, label in list_comparisons:
        try:
            old_list = props_old.get(section, {}).get(key, [])
            new_list = props_new.get(section, {}).get(key, [])
            old_list = list(old_list) if old_list else []
            new_list = list(new_list) if new_list else []
            
            old_set = set(old_list)
            new_set = set(new_list)
            added = new_set - old_set
            removed = old_set - new_set
            
            comparison['list_changes'][label] = {
                'v_old': old_list,
                'v_new': new_list,
                'added': list(added),
                'removed': list(removed),
                'changed': old_list != new_list,
                'type': 'list'
            }
        except Exception as e:
            logger.debug(f"Не удалось сравнить {label}: {e}")
            continue
    
    # ── 4. БУЛЕВЫ ФЛАГИ (5 свойств) ──────────────────
    boolean_comparisons = [
        ('is_stationary', 'stationarity', 'Стационарность'),
        ('is_deterministic', 'determinism', 'Детерминированность'),
        ('is_white_noise', 'autocorrelation', 'Белый шум (нет автокорреляции)'),
        ('is_normal', 'normality', 'Нормальность распределения'),
        ('is_seasonal', 'seasonality', 'Наличие сезонности'),
    ]
    
    for key, section, label in boolean_comparisons:
        try:
            old_val = props_old.get(section, {}).get(key)
            new_val = props_new.get(section, {}).get(key)
            if old_val is not None and new_val is not None:
                comparison['boolean_changes'][label] = {
                    'v_old': bool(old_val),
                    'v_new': bool(new_val),
                    'changed': old_val != new_val,
                    'type': 'boolean'
                }
                if old_val != new_val:
                    status_new = "✅ Да" if new_val else "❌ Нет"
                    comparison['qualitative_changes'].append(
                        f"{label}: стало {status_new} "
                        f"(было {'✅ Да' if old_val else '❌ Нет'})"
                    )
        except Exception as e:
            logger.debug(f"Не удалось сравнить {label}: {e}")
            continue
    
    # ── 5. ИТОГОВОЕ РЕЗЮМЕ ───────────────────────────
    n_numeric_changes = len([
        m for m in comparison['metrics'].values()
        if abs(m.get('delta_pct', 0)) > 5
    ])
    n_categorical_changes = len([
        c for c in comparison['categorical_changes'].values()
        if c.get('changed')
    ])
    n_list_changes = len([
        l for l in comparison['list_changes'].values()
        if l.get('changed')
    ])
    n_boolean_changes = len([
        b for b in comparison['boolean_changes'].values()
        if b.get('changed')
    ])
    
    total_changes = (
        n_numeric_changes + n_categorical_changes +
        n_list_changes + n_boolean_changes
    )
    
    if total_changes > 0:
        parts = []
        if n_numeric_changes > 0:
            parts.append(f"{n_numeric_changes} числовых метрик")
        if n_categorical_changes > 0:
            parts.append(f"{n_categorical_changes} категориальных")
        if n_list_changes > 0:
            parts.append(f"{n_list_changes} списков")
        if n_boolean_changes > 0:
            parts.append(f"{n_boolean_changes} булевых флагов")
        comparison['summary'] = (
            f"⚠️ Валидация повлияла на свойства ряда: "
            f"изменено {total_changes} свойств ({', '.join(parts)}). "
            f"Рекомендуется изучить различия перед выбором модели."
        )
    else:
        comparison['summary'] = (
            "✅ Валидация незначительно повлияла на свойства ряда. "
            "Все 13 свойств стабильны."
        )
    
    return comparison


# ═══════════════════════════════════════════════════════
# УПРОЩЁННЫЙ ПАСПОРТ (для сравнения До/После в UI)
# ═══════════════════════════════════════════════════════

def calculate_ts_props_quick(series: pd.Series) -> Dict[str, Any]:
    """
    Быстрый расчёт ключевых метрик для сравнения До/После в UI.

    В отличие от calculate_ts_passport (полный паспорт с 13 метриками и вложенной структурой),
    возвращает плоский dict с основными метриками. Используется для интерактивных
    сравнений в вкладке "Предобработка" (кнопки "Пересчитать свойства после...").

    Производительность: быстрее calculate_ts_passport, так как считает только
    базовые метрики (n, mean, std, min, max, ADF, trend, seasonality).

    Args:
        series: pd.Series с временным рядом (index=datetime, values=numeric)

    Returns:
        Плоский dict с ключами: n, mean, std, min, max, adf_pvalue, is_stationary,
        has_trend, has_seasonality, trend_strength, seasonal_strength, error
    """
    props: Dict[str, Any] = {
        'n': len(series),
        'mean': series.mean(),
        'std': series.std(),
        'min': series.min(),
        'max': series.max(),
        'adf_pvalue': None,
        'is_stationary': None,
        'has_trend': False,
        'has_seasonality': False,
        'trend_strength': 0.0,
        'seasonal_strength': 0.0
    }
    
    if len(series) < 10:
        return props
    
    # 1. Тест Дики-Фуллера (стационарность)
    try:
        adf_result = adfuller(series.dropna(), autolag='AIC')
        props['adf_pvalue'] = adf_result[1]
        props['is_stationary'] = adf_result[1] < 0.05
    except Exception as e:
        logger.debug(f"ADF test failed: {e}")
    
    # 2. Проверка тренда (линейная регрессия)
    try:
        x = np.arange(len(series))
        slope, intercept, r_value, p_value, std_err = linregress(x, series.values)
        props['has_trend'] = p_value < 0.05
        props['trend_strength'] = r_value ** 2
    except Exception as e:
        logger.debug(f"Trend detection failed: {e}")
    
    # 3. Проверка сезонности (FFT)
    try:
        fft_vals = np.abs(fft(series.values - series.mean()))
        fft_vals = fft_vals[1:len(fft_vals) // 2]  # Убираем постоянную составляющую
        if len(fft_vals) > 0:
            dominant_freq_idx = np.argmax(fft_vals)
            dominant_amplitude = fft_vals[dominant_freq_idx]
            mean_amplitude = np.mean(fft_vals)
            # Если амплитуда доминирующей частоты в 3+ раза выше средней — есть сезонность
            props['has_seasonality'] = dominant_amplitude > 3 * mean_amplitude
            props['seasonal_strength'] = (
                dominant_amplitude / mean_amplitude if mean_amplitude > 0 else 0
            )
    except Exception as e:
        logger.debug(f"FFT seasonality detection failed: {e}")
    
    return props
