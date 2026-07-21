"""
Проверка паритета: app/core/metrics.py::calculate_ts_passport
             vs     app/core/passport.py::calculate_ts_passport
 
Оба модуля сейчас существуют параллельно; app.py импортирует ТОЛЬКО passport.py.
metrics.py нигде не используется в продакшене, но имеет собственный тест-сьют
(tests/unit/test_metrics.py) и отличается сигнатурой (явный параметр error_log)
и обработкой ошибок (logger.warning в passport.py vs список error_log в metrics.py).
 
Скрипт:
1. Прогоняет обе функции на одной и той же golden-серии (два сценария: без
   ковариат и с ковариатами — чтобы затронуть блок корреляций).
2. Сравнивает вывод рекурсивно, игнорируя заведомо ожидаемые различия
   (timestamp — генерируется динамически; error_log — параметр есть только
   у metrics.py, structurally не часть паспорта).
3. Отдельно печатает содержимое error_log из metrics.py — если он не пуст
   на чистых golden-данных, это сигнал о скрытой ошибке внутри функции,
   которую сейчас просто не видно в passport.py (там она ушла бы в logger).
 
Запуск: python tools/metrics_vs_passport_parity_check.py
"""
import sys
 
import numpy as np
import pandas as pd
 
sys.path.insert(0, ".")
 
from app.core.passport import calculate_ts_passport as passport_impl
from app.core.metrics import calculate_ts_passport as metrics_impl
 
 
# Ключи, различие в которых ожидаемо и не является багом.
IGNORED_KEYS = {"timestamp"}
 
 
def make_golden_series(n=200, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="D")
    trend = np.linspace(0, 10, n)
    seasonal = 3 * np.sin(2 * np.pi * np.arange(n) / 7)
    noise = rng.normal(0, 1, n)
    values = trend + seasonal + noise
    return pd.Series(values, index=idx, name="value")
 
 
def make_golden_covariates(series, seed=43):
    """Второй числовой признак, коррелирующий с series, для теста блока 'correlations'."""
    rng = np.random.default_rng(seed)
    correlated = series.values * 0.8 + rng.normal(0, 0.5, len(series))
    df = pd.DataFrame({
        "value": series.values,
        "covariate": correlated,
    }, index=series.index)
    ct_f = {"num": ["value", "covariate"]}
    return df, ct_f
 
 
def compare_dicts(old, new, path=""):
    diffs = []
    keys = (set(old.keys()) | set(new.keys())) - IGNORED_KEYS
    for k in keys:
        p = f"{path}.{k}" if path else k
        if k not in old:
            diffs.append(f"{p}: отсутствует в passport.py")
            continue
        if k not in new:
            diffs.append(f"{p}: отсутствует в metrics.py")
            continue
        ov, nv = old[k], new[k]
        if isinstance(ov, dict) and isinstance(nv, dict):
            diffs.extend(compare_dicts(ov, nv, p))
        elif isinstance(ov, (float, np.floating)) and isinstance(nv, (float, np.floating)):
            if not np.isclose(float(ov), float(nv), rtol=1e-6, atol=1e-9, equal_nan=True):
                diffs.append(f"{p}: passport.py={ov!r} vs metrics.py={nv!r}")
        elif isinstance(ov, list) and isinstance(nv, list):
            if len(ov) != len(nv):
                diffs.append(f"{p}: разная длина списка — passport.py={ov!r} vs metrics.py={nv!r}")
            else:
                for i, (a, b) in enumerate(zip(ov, nv)):
                    if isinstance(a, (float, np.floating)) and isinstance(b, (float, np.floating)):
                        if not np.isclose(float(a), float(b), rtol=1e-6, atol=1e-9, equal_nan=True):
                            diffs.append(f"{p}[{i}]: passport.py={a!r} vs metrics.py={b!r}")
                    elif a != b:
                        diffs.append(f"{p}[{i}]: passport.py={a!r} vs metrics.py={b!r}")
        else:
            if ov != nv:
                diffs.append(f"{p}: passport.py={ov!r} vs metrics.py={nv!r}")
    return diffs
 
 
def compare_error_logs(passport_log, metrics_log):
    """
    Сравнивает error_log обеих реализаций по (error_type, severity) —
    stage теперь будет разным ('passport' vs 'metrics') по дизайну,
    поэтому сравниваем набор ошибок, а не stage дословно.
    """
    diffs = []
    p_types = sorted(e["error_type"] for e in passport_log)
    m_types = sorted(e["error_type"] for e in metrics_log)
    if p_types != m_types:
        diffs.append(f"Разный набор error_type: passport.py={p_types} vs metrics.py={m_types}")
    p_sev = sorted(e["severity"] for e in passport_log)
    m_sev = sorted(e["severity"] for e in metrics_log)
    if p_sev != m_sev:
        diffs.append(f"Разный набор severity: passport.py={p_sev} vs metrics.py={m_sev}")
    return diffs
 
 
def run_scenario(name, series, df_filtered=None, ct_f=None, target_col=None):
    print(f"\n{'=' * 60}\nСЦЕНАРИЙ: {name}\n{'=' * 60}")
 
    passport_error_log = []
    passport_result = passport_impl(
        series, df_filtered, ct_f, target_col, error_log=passport_error_log
    )
 
    metrics_error_log = []
    metrics_result = metrics_impl(
        series, df_filtered, ct_f, target_col, error_log=metrics_error_log
    )
 
    diffs = compare_dicts(passport_result, metrics_result)
 
    if not diffs:
        print("✅ ПАРИТЕТ ПОДТВЕРЖДЁН: passport.py и metrics.py дают идентичный результат"
              " (кроме timestamp).")
    else:
        print(f"❌ НАЙДЕНЫ РАСХОЖДЕНИЯ ({len(diffs)}):")
        for d in diffs:
            print(f"   - {d}")
 
    # error_log теперь заполняется ОБЕИМИ реализациями (после переноса
    # параметра в passport.py) — сравниваем их между собой.
    log_diffs = compare_error_logs(passport_error_log, metrics_error_log)
    if not passport_error_log and not metrics_error_log:
        print("\nℹ️  error_log пуст в обеих реализациях — на этих данных ошибок не было.")
    elif not log_diffs:
        print(f"\n✅ error_log СОВПАДАЕТ по составу ошибок между passport.py и metrics.py "
              f"({len(passport_error_log)} записей).")
    else:
        print(f"\n❌ error_log РАСХОДИТСЯ ({len(log_diffs)} несовпадений):")
        for d in log_diffs:
            print(f"   - {d}")
        print(f"   passport.py error_log: {passport_error_log}")
        print(f"   metrics.py  error_log: {metrics_error_log}")
 
    return diffs, log_diffs
 
 
def main():
    series = make_golden_series()
    df_cov, ct_f = make_golden_covariates(series)
 
    all_diffs = []
 
    d1, _ = run_scenario("без ковариат", series)
    all_diffs.extend(d1)
 
    d2, _ = run_scenario(
        "с ковариатами (блок 'correlations')",
        series, df_filtered=df_cov, ct_f=ct_f, target_col="value",
    )
    all_diffs.extend(d2)
 
    print(f"\n{'=' * 60}")
    if not all_diffs:
        print("✅ ИТОГ: во всех сценариях passport.py и metrics.py эквивалентны по числам.")
        print("   Можно безопасно переносить error_log-параметр из metrics.py в passport.py")
        print("   и удалять metrics.py + tests/unit/test_metrics.py.")
    else:
        print(f"❌ ИТОГ: суммарно {len(all_diffs)} расхождений — НЕ удалять metrics.py,")
        print("   пока расхождения не объяснены.")
    print("=" * 60)
 
 
if __name__ == "__main__":
    main()
 