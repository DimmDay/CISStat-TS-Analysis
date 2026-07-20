# tests/legacy_wrappers/legacy_metrics.py
import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────
# 🔧 УНИВЕРСАЛЬНАЯ ФУНКЦИЯ РАСЧЁТА ПАСПОРТА СВОЙСТВ РЯДА (LEGACY)
# ─────────────────────────────────────────────────────────────


# Локальный хелпер округления (legacy-обёртка не должна зависеть от
# app.core.metrics -- иначе сломается сам смысл snapshot-сравнения
# legacy vs new реализаций). См. _round_floats в app/core/metrics.py.
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


def calculate_ts_passport(analysis_series: pd.Series,
                          df_filtered: pd.DataFrame = None,
                          ct_f: dict = None,
                          target_col: str = None) -> dict:
    """
    Рассчитывает полный паспорт свойств временного ряда (13 метрик).
    Структура идентична паспорту во вкладке "Загрузка".
    
    ВНИМАНИЕ: Это legacy-код из app.py. Импорты внутри функции сохранены как есть.
    """
    from scipy.stats import linregress, jarque_bera
    from scipy.signal import periodogram, find_peaks
    from scipy.fft import fft, fftfreq
    from statsmodels.tsa.stattools import adfuller, acf as acf_func
    from statsmodels.tsa.seasonal import STL
    from statsmodels.stats.diagnostic import acorr_ljungbox

    props = {}

    if len(analysis_series) < 30:
        return {"error": "Недостаточно данных (нужно > 30 точек)"}

    try:
        # 0. ЧАСТОТА РЯДА
        try:
            inferred_freq = pd.infer_freq(analysis_series.index.drop_duplicates().sort_values())
        except:
            inferred_freq = None
        props['freq'] = {
            'value': inferred_freq if inferred_freq else 'Нерегулярная',
            'is_ok': inferred_freq is not None
        }

        # 1. СТАЦИОНАРНОСТЬ (ADF)
        adf_res = adfuller(analysis_series.dropna(), autolag='AIC')
        adf_p = adf_res[1]
        is_stationary = adf_p < 0.05
        props['stationarity'] = {
            'value': float(adf_p),
            'is_stationary': bool(is_stationary),
            'is_ok': bool(is_stationary)
        }

        # 2. ДЕТЕРМИНИРОВАННОСТЬ (R² тренда)
        slope, intercept, r_value, p_value, std_err = linregress(
            range(len(analysis_series)), analysis_series.values
        )
        r_squared = float(r_value**2)
        is_deterministic = r_squared >= 0.7
        props['determinism'] = {
            'value': r_squared,
            'slope': float(slope),
            'is_deterministic': bool(is_deterministic)
        }

        # 3. АВТОКОРРЕЛЯЦИЯ (Ljung-Box)
        lb_res = acorr_ljungbox(analysis_series, lags=[10])
        if isinstance(lb_res, pd.DataFrame):
            lb_p = float(lb_res['lb_pvalue'].iloc[0])
        else:
            lb_p = float(lb_res[1][0])
        is_white_noise = lb_p > 0.05
        props['autocorrelation'] = {
            'value': lb_p,
            'is_white_noise': bool(is_white_noise),
            'is_ok': bool(is_white_noise)
        }

        # 4. НОРМАЛЬНОСТЬ (Jarque-Bera)
        jb_res = jarque_bera(analysis_series.dropna())
        jb_p = float(jb_res.pvalue) if hasattr(jb_res, 'pvalue') else float(jb_res[1])
        is_normal = jb_p > 0.05
        props['normality'] = {
            'value': jb_p,
            'is_normal': bool(is_normal),
            'is_ok': bool(is_normal)
        }

        # 5. НАПРАВЛЕНИЕ ТРЕНДА
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

        # 6. КОРРЕЛЯЦИЯ ПРИЗНАКОВ
        props['correlations'] = {}
        if df_filtered is not None and ct_f is not None and target_col:
            try:
                num_cols = ct_f.get("num", [])
                if len(num_cols) >= 2 and target_col in num_cols:
                    corr_df = df_filtered[num_cols].corr()
                    target_corr = corr_df[target_col].drop(target_col).sort_values(key=abs, ascending=False)
                    top_corrs = {col: float(val) for col, val in target_corr.head(3).items()}
                    props['correlations'] = {
                        'top3': top_corrs,
                        'max_abs_corr': float(target_corr.iloc[0]) if len(target_corr) > 0 else 0.0
                    }
            except:
                pass

        # 7. СЕЗОННОСТЬ (STL strength)
        period = 7 if (inferred_freq and 'D' in str(inferred_freq)) else 12
        try:
            stl_res = STL(analysis_series, period=period, robust=True).fit()
            var_total = float(analysis_series.var())
            var_resid = float(stl_res.resid.var())
            var_detrended = var_total - float(stl_res.trend.var())
            strength_seasonality = max(0, 1 - var_resid / var_detrended) if var_detrended > 0 else 0
            is_seasonal = strength_seasonality > 0.6
        except:
            strength_seasonality = 0.0
            is_seasonal = False
        props['seasonality'] = {
            'strength': float(strength_seasonality),
            'is_seasonal': bool(is_seasonal)
        }

        # 8. СЕЗОННЫЕ ПЕРИОДЫ (ACF)
        try:
            max_lag = min(60, len(analysis_series) // 4)
            acf_values = acf_func(analysis_series, nlags=max_lag)
            confidence = 1.96 / np.sqrt(len(analysis_series))
            significant_lags = np.where(np.abs(acf_values) > confidence)[0][1:]

            seasonal_periods_acf = []
            for i, lag in enumerate(significant_lags):
                if i > 0 and lag - significant_lags[i-1] < 3:
                    continue
                if lag > 2:
                    seasonal_periods_acf.append(int(lag))

            props['seasonal_periods'] = {
                'periods': seasonal_periods_acf[:3],
                'count': len(seasonal_periods_acf[:3])
            }
        except:
            props['seasonal_periods'] = {'periods': [], 'count': 0}

        # 9. ДОЛГАЯ ПАМЯТЬ (Hurst)
        def hurst_exponent(series, max_lag=20):
            lags = range(2, max_lag)
            tau = [max(np.std(np.subtract(series[lag:], series[:-lag])), 1e-8) for lag in lags]
            try:
                return float(np.polyfit(np.log(lags), np.log(tau), 1)[0])
            except:
                return 0.5

        hurst_val = hurst_exponent(analysis_series.values)
        if hurst_val < 0.45:
            memory_type = 'anti_persistent'
        elif hurst_val > 0.55:
            memory_type = 'persistent'
        else:
            memory_type = 'random_walk'
        props['hurst'] = {
            'value': float(hurst_val),
            'type': memory_type
        }

        # 10. ДОМИНИРУЮЩИЕ ЧАСТОТЫ (FFT)
        try:
            n = len(analysis_series)
            y = analysis_series.values - analysis_series.mean()
            yf = fft(y)
            xf = fftfreq(n, 1)[:n//2]
            amplitude = 2.0/n * np.abs(yf[0:n//2])

            peaks, _ = find_peaks(amplitude, height=np.mean(amplitude) + np.std(amplitude))
            fft_periods = [1/xf[p] for p in peaks if xf[p] > 0 and xf[p] < 0.5]
            fft_dominant = sorted(fft_periods)[:3] if fft_periods else []
            props['fft'] = {
                'dominant_periods': fft_dominant,
                'count': len(fft_dominant)
            }
        except:
            props['fft'] = {'dominant_periods': [], 'count': 0}

        # 11. ПЕРИОДОГРАММА
        try:
            freq_per, pxx_per = periodogram(analysis_series.values, fs=1.0, window='hann')
            peaks_per, _ = find_peaks(pxx_per, height=np.median(pxx_per)*2)
            periodogram_periods = sorted([1/freq_per[p] for p in peaks_per if freq_per[p] > 0])[:3]
            props['periodogram'] = {
                'periods': periodogram_periods,
                'count': len(periodogram_periods)
            }
        except:
            props['periodogram'] = {'periods': [], 'count': 0}

        # 12. ВЕЙВЛЕТ-МАСШТАБЫ
        try:
            import pywt
            widths = np.arange(1, min(128, len(analysis_series)//4))
            cwtmatr, _ = pywt.cwt(
                analysis_series.values - analysis_series.mean(),
                widths, 'morl', sampling_period=1
            )
            mean_power = np.mean(np.abs(cwtmatr), axis=1)
            wavelet_peaks, _ = find_peaks(mean_power, height=np.mean(mean_power))
            wavelet_scales = widths[wavelet_peaks][:3].tolist() if len(wavelet_peaks) > 0 else []
            props['wavelet'] = {
                'scales': wavelet_scales,
                'count': len(wavelet_scales)
            }
        except:
            props['wavelet'] = {'scales': [], 'count': 0}

        # 13. БАЗОВЫЕ СТАТИСТИКИ
        props['basic_stats'] = {
            'n': int(len(analysis_series)),
            'mean': float(analysis_series.mean()),
            'std': float(analysis_series.std()),
            'min': float(analysis_series.min()),
            'max': float(analysis_series.max())
        }

        props['timestamp'] = pd.Timestamp.now().isoformat()

    except Exception as e:
        props['error'] = str(e)

    # Детерминированное округление float-полей для стабильности snapshot-тестов.
    return _round_floats(props)