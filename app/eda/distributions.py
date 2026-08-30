# app/eda/distributions.py
"""
Модуль для анализа распределений числовых данных.
Извлечено из app.py (пункт B.2 EXTRACTION_PLAN.md).
"""
import numpy as np
import pandas as pd
from scipy import stats
from typing import Any


MIN_DISTRIBUTION_OBSERVATIONS = 8
SHAPIRO_MAX_OBSERVATIONS = 5_000
JARQUE_BERA_ASYMPTOTIC_MIN = 2_000
JARQUE_BERA_MONTE_CARLO_DRAWS = 499
MAX_DIAGNOSTIC_POINTS = 400


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


def _empty_test(
    test_id: str,
    label: str,
    note: str,
) -> dict[str, Any]:
    return {
        "id": test_id,
        "label": label,
        "available": False,
        "statistic": None,
        "p_value": None,
        "adjusted_p_value": None,
        "reject_normality": None,
        "n_used": None,
        "calibration": None,
        "note": note,
    }


def _holm_adjust(tests: list[dict[str, Any]], alpha: float) -> None:
    """Поправка Холма без предположения независимости тестов."""
    available = [
        (index, float(item["p_value"]))
        for index, item in enumerate(tests)
        if item["available"] and item["p_value"] is not None
    ]
    ranked = sorted(available, key=lambda pair: pair[1])
    m = len(ranked)
    running_max = 0.0
    for rank, (index, p_value) in enumerate(ranked):
        adjusted = min(1.0, (m - rank) * p_value)
        running_max = max(running_max, adjusted)
        tests[index]["adjusted_p_value"] = float(running_max)
        tests[index]["reject_normality"] = bool(running_max < alpha)


def _is_low_cardinality_discrete(values: np.ndarray) -> bool:
    if not np.all(np.isclose(values, np.round(values), rtol=0.0, atol=1e-10)):
        return False
    unique_count = int(np.unique(values).size)
    threshold = max(20, int(np.sqrt(len(values))))
    return unique_count <= threshold


def _shape_label(skewness: float, excess_kurtosis: float, discrete: bool) -> str:
    if discrete:
        return "Дискретное распределение"
    if skewness >= 0.5:
        return "Правосторонняя асимметрия"
    if skewness <= -0.5:
        return "Левосторонняя асимметрия"
    if excess_kurtosis >= 1:
        return "Почти симметричное распределение с тяжёлыми хвостами"
    if excess_kurtosis <= -1:
        return "Почти симметричное распределение с короткими хвостами"
    return "Почти симметричное распределение без выраженного отличия хвостов"


def _jarque_bera_monte_carlo(values: np.ndarray) -> tuple[float, float]:
    observed = stats.jarque_bera(values)
    statistic = float(observed.statistic)
    rng = np.random.default_rng(20_260_830)
    simulated = rng.normal(
        size=(JARQUE_BERA_MONTE_CARLO_DRAWS, len(values)),
    )
    simulated_statistics = np.asarray(
        stats.jarque_bera(simulated, axis=1).statistic,
        dtype=float,
    )
    p_value = (
        1.0 + float(np.count_nonzero(simulated_statistics >= statistic))
    ) / (JARQUE_BERA_MONTE_CARLO_DRAWS + 1.0)
    return statistic, p_value


def _normality_tests(
    values: np.ndarray,
    alpha: float,
    discrete: bool,
) -> list[dict[str, Any]]:
    if discrete:
        note = (
            "Тесты непрерывного нормального распределения неприменимы "
            "к низкокардинальному дискретному признаку."
        )
        return [
            _empty_test("shapiro", "Shapiro–Wilk", note),
            _empty_test("jarque_bera", "Jarque–Bera", note),
            _empty_test("lilliefors", "K–S (Лиллиефорс)", note),
        ]

    n = len(values)
    tests: list[dict[str, Any]] = []
    if n <= SHAPIRO_MAX_OBSERVATIONS:
        shapiro = stats.shapiro(values)
        tests.append({
            "id": "shapiro",
            "label": "Shapiro–Wilk",
            "available": True,
            "statistic": float(shapiro.statistic),
            "p_value": float(shapiro.pvalue),
            "adjusted_p_value": None,
            "reject_normality": None,
            "n_used": n,
            "calibration": "standard",
            "note": None,
        })
    else:
        tests.append(_empty_test(
            "shapiro",
            "Shapiro–Wilk",
            "При N > 5000 статистика W остаётся информативной, но точность p-значения не гарантируется; тест не выполнялся.",
        ))

    if n >= JARQUE_BERA_ASYMPTOTIC_MIN:
        jarque_bera = stats.jarque_bera(values)
        tests.append({
            "id": "jarque_bera",
            "label": "Jarque–Bera",
            "available": True,
            "statistic": float(jarque_bera.statistic),
            "p_value": float(jarque_bera.pvalue),
            "adjusted_p_value": None,
            "reject_normality": None,
            "n_used": n,
            "calibration": "asymptotic",
            "note": "Использовано асимптотическое распределение χ²(2).",
        })
    else:
        statistic, p_value = _jarque_bera_monte_carlo(values)
        tests.append({
            "id": "jarque_bera",
            "label": "Jarque–Bera",
            "available": True,
            "statistic": statistic,
            "p_value": p_value,
            "adjusted_p_value": None,
            "reject_normality": None,
            "n_used": n,
            "calibration": "monte_carlo",
            "note": (
                f"Для N < {JARQUE_BERA_ASYMPTOTIC_MIN} p-значение откалибровано "
                f"по {JARQUE_BERA_MONTE_CARLO_DRAWS} нормальным выборкам методом Монте-Карло."
            ),
        })

    try:
        from statsmodels.stats.diagnostic import lilliefors

        statistic, p_value = lilliefors(values, dist="norm", pvalmethod="table")
        tests.append({
            "id": "lilliefors",
            "label": "K–S (Лиллиефорс)",
            "available": True,
            "statistic": float(statistic),
            "p_value": float(p_value),
            "adjusted_p_value": None,
            "reject_normality": None,
            "n_used": n,
            "calibration": "table",
            "note": "Поправка Лиллиефорса учитывает оценивание среднего и дисперсии по этой же выборке.",
        })
    except (ImportError, ModuleNotFoundError, ValueError, FloatingPointError) as exc:
        tests.append(_empty_test(
            "lilliefors",
            "K–S (Лиллиефорс)",
            f"Тест Лиллиефорса недоступен: {exc}",
        ))

    _holm_adjust(tests, alpha)
    return tests


def _diagnostic_points(values: np.ndarray) -> dict[str, Any]:
    (theoretical, observed), (slope, intercept, correlation) = stats.probplot(
        values,
        dist="norm",
        fit=True,
    )
    n = len(values)
    if n > MAX_DIAGNOSTIC_POINTS:
        indices = np.unique(
            np.linspace(0, n - 1, MAX_DIAGNOSTIC_POINTS, dtype=int)
        )
    else:
        indices = np.arange(n, dtype=int)

    qq = [
        {
            "theoretical": float(theoretical[index]),
            "observed": float(observed[index]),
            "reference": float(slope * theoretical[index] + intercept),
        }
        for index in indices
    ]

    sorted_values = np.sort(values)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    cdf = [
        {
            "x": float(sorted_values[index]),
            "empirical": float((index + 1) / n),
            "normal": float(stats.norm.cdf(sorted_values[index], loc=mean, scale=std)),
        }
        for index in indices
    ]
    return {
        "qq": qq,
        "cdf": cdf,
        "qq_slope": float(slope),
        "qq_intercept": float(intercept),
        "qq_r": float(correlation),
    }


def _not_applicable(
    series: pd.Series,
    reason: str,
    alpha: float,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    finite = numeric.dropna()
    return {
        "applicable": False,
        "reason": reason,
        "n_observations": int(len(finite)),
        "missing_count": missing_count,
        "min_observations": MIN_DISTRIBUTION_OBSERVATIONS,
        "alpha": float(alpha),
        "is_discrete": False,
        "unique_count": int(finite.nunique()),
        "mean": None,
        "median": None,
        "std": None,
        "q1": None,
        "q3": None,
        "iqr": None,
        "mad": None,
        "skewness": None,
        "excess_kurtosis": None,
        "shape_label": "Недоступно",
        "normality_applicable": False,
        "normality_status": "not_applicable",
        "qq_r": None,
        "qq_slope": None,
        "qq_intercept": None,
        "tests": [],
        "qq": [],
        "cdf": [],
        "recommendation": reason,
        "recommendations": [],
        "warnings": [],
    }


def analyze_distribution(
    series: pd.Series,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Проверяет форму маргинального распределения выбранного ряда.

    Пропуски и бесконечные значения не удаляются молча: на финальном EDA
    они означают незавершённую предобработку. Формальные тесты дополняются
    поправкой Холма, Q–Q диагностикой и размерами эффектов формы.
    """
    if not 0 < alpha < 1:
        raise ValueError("Уровень значимости alpha должен быть между 0 и 1")

    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    if missing_count:
        return _not_applicable(
            numeric,
            "В ряду есть пропуски или бесконечные значения. Сначала завершите предобработку; анализ только доступных точек мог бы исказить форму распределения.",
            alpha,
        )
    if len(numeric) < MIN_DISTRIBUTION_OBSERVATIONS:
        return _not_applicable(
            numeric,
            f"Недостаточно наблюдений: нужно не менее {MIN_DISTRIBUTION_OBSERVATIONS}, доступно {len(numeric)}.",
            alpha,
        )
    if float(numeric.max() - numeric.min()) == 0.0:
        return _not_applicable(
            numeric,
            "Ряд константный: дисперсия равна нулю, поэтому нормальное распределение и Q–Q диагностика вырождены.",
            alpha,
        )

    values = numeric.to_numpy(dtype=float)
    n = len(values)
    mean = float(np.mean(values))
    median = float(np.median(values))
    std = float(np.std(values, ddof=1))
    q1, q3 = (float(value) for value in np.quantile(values, [0.25, 0.75]))
    iqr = float(q3 - q1)
    mad = float(np.median(np.abs(values - median)))
    skewness = float(stats.skew(values, bias=False))
    excess_kurtosis = float(stats.kurtosis(values, fisher=True, bias=False))
    discrete = _is_low_cardinality_discrete(values)
    tests = _normality_tests(values, alpha, discrete)
    diagnostics = _diagnostic_points(values)

    effect_shape_close = abs(skewness) < 0.5 and abs(excess_kurtosis) < 1.0
    rejected = sum(item["reject_normality"] is True for item in tests)
    available = sum(item["available"] is True for item in tests)
    if discrete:
        normality_status = "not_applicable"
        recommendation = (
            "Признак низкокардинальный и дискретный. Не интерпретируйте тесты непрерывной нормальности; рассматривайте счётные или категориальные модели."
        )
    elif available and rejected == 0 and effect_shape_close:
        normality_status = "compatible"
        recommendation = (
            "Нет оснований отвергнуть нормальную форму при выбранном α, а асимметрия и эксцесс невелики. Это совместимость, а не доказательство нормальности."
        )
    elif rejected >= 2 or (rejected >= 1 and not effect_shape_close):
        normality_status = "departed"
        recommendation = (
            "Распределение заметно отклоняется от нормального. Оцените характер отклонения на Q–Q графике и сравните устойчивые преобразования или модели с ненормальными ошибками."
        )
    else:
        normality_status = "inconclusive"
        recommendation = (
            "Формальные тесты и показатели формы дают смешанный результат. Ориентируйтесь на величину отклонений и Q–Q график, а не на одно p-значение."
        )

    warnings_out = [
        "Тесты нормальности предполагают независимые наблюдения; при автокорреляции временного ряда p-значения имеют диагностический характер.",
        "Для выводов о доверительных интервалах модели нормальность проверяют на остатках после обучения, а не только на исходном ряде.",
    ]
    if discrete:
        warnings_out.insert(0, "Обнаружен низкокардинальный целочисленный признак.")

    return {
        "applicable": True,
        "reason": None,
        "n_observations": n,
        "missing_count": 0,
        "min_observations": MIN_DISTRIBUTION_OBSERVATIONS,
        "alpha": float(alpha),
        "is_discrete": discrete,
        "unique_count": int(np.unique(values).size),
        "mean": mean,
        "median": median,
        "std": std,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "mad": mad,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "shape_label": _shape_label(skewness, excess_kurtosis, discrete),
        "normality_applicable": not discrete,
        "normality_status": normality_status,
        "qq_r": diagnostics["qq_r"],
        "qq_slope": diagnostics["qq_slope"],
        "qq_intercept": diagnostics["qq_intercept"],
        "tests": tests,
        "qq": diagnostics["qq"],
        "cdf": diagnostics["cdf"],
        "recommendation": recommendation,
        "recommendations": [
            recommendation,
            "Сопоставьте тесты с гистограммой, плотностью, Q–Q графиком и величинами асимметрии/эксцесса.",
        ],
        "warnings": warnings_out,
    }
