# apps/api/chart_data.py
"""
Подготовка данных для графиков распределения (точечный график / гистограмма /
KDE) -- пункт 3 контракта вкладки «Загрузка» (см. TsAnalysisUpload.tsx).

Живёт в apps/api, а не в app/core/*, сознательно: это presentation-логика
конкретно для Recharts на фронтенде (сэмплинг под лимит точек в браузере,
формат {x,y}), а не аналитическая формула вроде calculate_ts_passport --
не нарушает "app/core не переписывается" из docs/MIGRATION_ARCHITECTURE.md.

Согласовано с тимлидом (2026-08-14):
  - scatter: полный набор точек до FULL_POINTS_THRESHOLD, выше --
    LTTB-сэмплинг (Largest-Triangle-Three-Buckets, а не "каждый N-й" --
    последний искажает форму ряда и может полностью потерять пики).
  - обязательно сохраняются глобальные min/max и IQR-выбросы поверх LTTB,
    чтобы сэмплинг не прятал экстремумы (тот же риск, что и с "каждым N-м").
  - zoom: эндпоинт принимает start/end (позиция в очищенном от NaN ряде) --
    более узкий диапазон, поэтому отдаётся с более высоким разрешением.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# ── Константы адаптивного сэмплинга (согласовано с тимлидом) ──
FULL_POINTS_THRESHOLD = 3000  # до этого числа точек -- рисуем все, без сэмплинга
TARGET_SAMPLED_POINTS = 1500  # целевое число точек после LTTB
MAX_ZOOM_POINTS = 5000  # защитный потолок даже при явном zoom-запросе диапазона

DEFAULT_HISTOGRAM_BINS = 30
KDE_CURVE_POINTS = 200
IQR_OUTLIER_MULTIPLIER = 1.5  # тот же множитель, что и в get_dataset_stats/validation/outliers.py


def _lttb_indices(x: np.ndarray, y: np.ndarray, target: int) -> np.ndarray:
    """Largest-Triangle-Three-Buckets: возвращает ИНДЕКСЫ точек, которые
    нужно оставить, downsample'я (x, y) до `target` точек.

    Алгоритм (Sveinn Steinarsson, 2013) сохраняет визуальную форму ряда
    лучше, чем равномерное прореживание "каждый N-й" -- каждая точка
    выбирается так, чтобы максимизировать площадь треугольника с соседними
    уже выбранными точками, то есть предпочитаются точки, дающие наибольшее
    визуальное отклонение (пики, изломы), а не просто равноотстоящие.

    Первая и последняя точка сохраняются всегда.
    """
    n = len(x)
    if target >= n or target <= 2:
        return np.arange(n)

    # Точки разбиваются на `target - 2` бакета (первая/последняя вне бакетов)
    bucket_size = (n - 2) / (target - 2)
    indices = np.empty(target, dtype=np.int64)
    indices[0] = 0
    indices[-1] = n - 1

    a = 0  # индекс точки, выбранной в предыдущем шаге
    for i in range(target - 2):
        bucket_start = int(np.floor(i * bucket_size)) + 1
        bucket_end = int(np.floor((i + 1) * bucket_size)) + 1
        bucket_end = min(bucket_end, n - 1)
        if bucket_start >= bucket_end:
            bucket_end = bucket_start + 1

        # Среднее следующего бакета -- нужно для площади треугольника
        next_start = bucket_end
        next_end = int(np.floor((i + 2) * bucket_size)) + 1
        next_end = min(next_end, n)
        next_start = min(next_start, n - 1)
        if next_start >= next_end:
            avg_x, avg_y = x[n - 1], y[n - 1]
        else:
            avg_x = x[next_start:next_end].mean()
            avg_y = y[next_start:next_end].mean()

        px, py = x[a], y[a]
        bucket_x = x[bucket_start:bucket_end]
        bucket_y = y[bucket_start:bucket_end]
        # Площадь треугольника (px,py) - (bucket точка) - (avg_x,avg_y),
        # векторизовано по всем точкам бакета сразу.
        areas = np.abs(
            (px - avg_x) * (bucket_y - py) - (px - bucket_x) * (avg_y - py)
        ) * 0.5
        best_local = int(np.argmax(areas))
        chosen = bucket_start + best_local
        indices[i + 1] = chosen
        a = chosen

    return np.unique(indices)  # np.unique попутно сортирует


def _iqr_outlier_positions(y: np.ndarray) -> np.ndarray:
    """Позиции (не значения) точек-выбросов по правилу IQR -- тот же
    множитель 1.5, что и в get_dataset_stats (q1/q3) и
    validation/outliers.py::detect_outliers(method="iqr"). Не вызывает
    detect_outliers напрямую: та функция рассчитана на полноценный
    Validation-отчёт (config из YAML, sklearn IsolationForest, индексы
    исходного df) -- для лёгкого "не потерять пик при сэмплинге на
    Загрузке" достаточно самой формулы IQR-границ."""
    if len(y) < 4:
        return np.array([], dtype=np.int64)
    q1, q3 = np.percentile(y, [25, 75])
    iqr = q3 - q1
    if iqr == 0:
        return np.array([], dtype=np.int64)
    lower = q1 - IQR_OUTLIER_MULTIPLIER * iqr
    upper = q3 + IQR_OUTLIER_MULTIPLIER * iqr
    return np.where((y < lower) | (y > upper))[0]


def build_scatter_series(
    series: pd.Series,
    max_points: int = TARGET_SAMPLED_POINTS,
    full_threshold: int = FULL_POINTS_THRESHOLD,
) -> dict:
    """Точки для точечного графика (x = позиция в очищенном от NaN ряде,
    y = значение). Ниже full_threshold отдаёт все точки без сэмплинга.
    Выше -- LTTB до max_points, с гарантированным сохранением глобальных
    min/max и IQR-выбросов (см. докстринг модуля)."""
    values = series.to_numpy(dtype=float)
    n = len(values)
    x = np.arange(n, dtype=np.int64)

    if n <= full_threshold:
        return {
            "points": [{"x": int(xi), "y": float(yi)} for xi, yi in zip(x, values)],
            "sampled": False,
            "sampling_method": None,
            "original_count": n,
        }

    kept = _lttb_indices(x.astype(float), values, max_points)

    # Гарантируем сохранение экстремумов и выбросов, даже если LTTB их
    # "усреднил" внутри бакета -- иначе сэмплинг может визуально спрятать
    # ровно те точки, которые аналитику важнее всего увидеть.
    extra = {int(np.argmin(values)), int(np.argmax(values))}
    extra.update(int(i) for i in _iqr_outlier_positions(values))
    all_indices = np.union1d(kept, np.array(sorted(extra), dtype=np.int64))

    points = [{"x": int(x[i]), "y": float(values[i])} for i in all_indices]
    return {
        "points": points,
        "sampled": True,
        "sampling_method": "lttb",
        "original_count": n,
    }


def build_histogram(series: pd.Series, nbins: int = DEFAULT_HISTOGRAM_BINS) -> list[dict]:
    """Bins гистограммы (np.histogram) -- считается по ПОЛНОМУ столбцу,
    не по сэмплированным для scatter точкам (иначе форма распределения
    искажалась бы сэмплингом, а не отражала реальные данные)."""
    values = series.to_numpy(dtype=float)
    if len(values) == 0:
        return []
    counts, edges = np.histogram(values, bins=nbins)
    return [
        {"x0": float(edges[i]), "x1": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def build_kde(series: pd.Series, n_points: int = KDE_CURVE_POINTS) -> list[dict] | None:
    """Точки KDE-кривой (scipy.stats.gaussian_kde) по ПОЛНОМУ столбцу.
    None, если KDE не определена: <2 значений или нулевая дисперсия
    (константный столбец -- gaussian_kde падает на вырожденной матрице
    ковариации)."""
    values = series.to_numpy(dtype=float)
    if len(values) < 2 or float(np.std(values)) == 0.0:
        return None
    try:
        kde = scipy_stats.gaussian_kde(values)
    except Exception:
        # Защита от редких numerical edge cases scipy (сингулярная
        # матрица и т.п.) -- клиент получит kde=None и просто не
        # отрисует кривую, не 500.
        return None
    lo, hi = float(values.min()), float(values.max())
    xs = np.linspace(lo, hi, n_points)
    ys = kde(xs)
    return [{"x": float(xi), "y": float(yi)} for xi, yi in zip(xs, ys)]
