# apps/api/decomposition_data.py
"""
Подготовка данных для бейджей декомпозиции (Тренд/Сезонность/Цикличность/
Остаток) И для графика разложенного ряда -- остановка «График» вкладки
«Загрузка» (согласовано с тимлидом: бейджи -- 2026-08-14, график
компонент -- 2026-08-19, "визуализировать декомпозированный ряд на
дополнительном графике").

Обёртка над app/preprocessing/decomposition.py::apply_decomposition /
compute_decomposition_stats (STL, statsmodels) -- САМА формула
декомпозиции НЕ переписывается (проект уже применял этот принцип к
validation/*, models/* -- app/core не дублируется). Этот модуль
добавляет то, чего не было у сырых функций:

  1. ЧЕСТНЫЙ гейт по частоте -- STL технически не падает даже на
     семантически бессмысленном period (см. чат: 30 годовых точек с
     period=12 по умолчанию дают "сезонность" из чистого шума). Здесь
     period выводится из РЕАЛЬНО обнаруженной pd.infer_freq(), и для
     годовых/нерегулярных данных возвращается applicable=False с
     объяснением, а не подделанные цифры.
  2. Защита от панельных данных -- несколько строк на одну дату
     (например, Country+Year+Price: много стран на один год) делает
     "один ряд на одну дату" неопределённым без агрегации, которую
     здесь никто не просил -- applicable=False, а не тихий выбор
     произвольной строки или креш.
  3. Нормализация дисперсий в проценты (сумма≈100%) для бейджей
     (build_decomposition) И реальные ряды компонент для графика
     (build_decomposition_series) -- гейтинг (пункты 1-2) вынесен в
     _prepare_decomposable_series, ОБЩИЙ для обеих функций, не
     задублирован.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.preprocessing.decomposition import apply_decomposition, compute_decomposition_stats
from app.data.detectors import smart_to_datetime
from apps.api.chart_data import FULL_POINTS_THRESHOLD, TARGET_SAMPLED_POINTS, _iqr_outlier_positions, _lttb_indices

# Частота -> (period для STL, человекочитаемое имя, минимум периодов для
# осмысленной декомпозиции -- 2 полных цикла, как и в apply_decomposition,
# но здесь это ЯВНОЕ условие гейта, а не implicit ValueError из statsmodels).
_FREQ_TO_PERIOD: dict[str, tuple[int, str]] = {
    "D": (7, "дневная (недельная сезонность)"),
    "B": (5, "рабочие дни (недельная сезонность)"),
    "W": (52, "недельная (годовая сезонность)"),
    "M": (12, "месячная (годовая сезонность)"),
    "ME": (12, "месячная (годовая сезонность)"),
    "MS": (12, "месячная (годовая сезонность)"),
    "BM": (12, "конец рабочего месяца (годовая сезонность)"),
    "BME": (12, "конец рабочего месяца (годовая сезонность)"),
    "BMS": (12, "начало рабочего месяца (годовая сезонность)"),
    "Q": (4, "квартальная (годовая сезонность)"),
    "QE": (4, "квартальная (годовая сезонность)"),
    "QS": (4, "квартальная (годовая сезонность)"),
}
_MIN_PERIODS_MULTIPLIER = 2  # тот же порог, что и в apply_decomposition
_CYCLICAL_ROLLING_WINDOW = 30  # тот же множитель, что и в compute_decomposition_stats


def _resolve_period(inferred_freq: str | None) -> tuple[int, str] | None:
    """Возвращает (period, human_label) для STL, или None, если частота
    не поддерживает осмысленную декомпозицию (годовая/нерегулярная/
    неопределённая -- нет внутригодового цикла для выделения)."""
    if inferred_freq is None:
        return None
    # pd.infer_freq может вернуть "D", "3D", "MS" и т.п. -- берём базовую
    # букву(ы) без множителя.
    base = "".join(ch for ch in inferred_freq if not ch.isdigit()).split("-")[0]
    return _FREQ_TO_PERIOD.get(base)


class _NotApplicable(Exception):
    """Внутренний сигнал: гейт декомпозиции не пройден. reason/frequency
    -- то же, что уходит в ответ API (см. _not_applicable ниже)."""
    def __init__(self, reason: str, frequency: str | None = None):
        self.reason = reason
        self.frequency = frequency
        super().__init__(reason)


def _prepare_decomposable_series(dates: pd.Series, values: pd.Series) -> tuple[pd.Series, int, str, str]:
    """ОБЩИЙ гейтинг для build_decomposition (бейджи) и
    build_decomposition_series (график компонент) -- пункты 1-2
    докстринга модуля (частота, панельные дубли, недостаточно точек).

    Возвращает (series с DatetimeIndex, period, inferred_freq_code, freq_label)
    при успехе; бросает _NotApplicable при провале любого условия гейта
    -- вызывающий код ловит её и формирует честный applicable=False."""
    df = pd.DataFrame({"date": smart_to_datetime(dates), "value": pd.to_numeric(values, errors="coerce")})
    df = df.dropna(subset=["date", "value"])

    if len(df) == 0:
        raise _NotApplicable("В колонке нет ни одной пары (дата, значение) без пропусков")

    # ── Защита от панельных данных: несколько строк на одну дату ──
    n_unique_dates = df["date"].nunique()
    if n_unique_dates < len(df):
        raise _NotApplicable(
            f"На одну дату приходится несколько значений ({len(df)} строк, "
            f"{n_unique_dates} уникальных дат) -- похоже на панельные данные "
            f"(несколько сущностей на одну дату). Декомпозиция требует одного "
            f"значения на дату; агрегация по сущностям здесь не выполняется."
        )

    df = df.sort_values("date").reset_index(drop=True)

    # ── Определение реальной частоты (НЕ угадывание "12 по умолчанию") ──
    inferred = pd.infer_freq(df["date"])
    resolved = _resolve_period(inferred)
    if resolved is None:
        freq_desc = inferred or "не определена (нерегулярные интервалы)"
        raise _NotApplicable(
            f"Частота данных ({freq_desc}) не поддерживает внутрипериодную "
            f"сезонность -- для годовых/нерегулярных рядов декомпозиция "
            f"тренд/сезонность/цикл неприменима по определению",
            frequency=inferred,
        )
    period, freq_label = resolved

    min_points = _MIN_PERIODS_MULTIPLIER * period
    if len(df) < min_points:
        raise _NotApplicable(
            f"Недостаточно точек для декомпозиции: {len(df)} из минимум {min_points} "
            f"(2 полных периода по {period} точек при частоте «{freq_label}»)",
            frequency=inferred,
        )

    series = pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(df["date"]))
    return series, period, inferred, freq_label


def build_decomposition(dates: pd.Series, values: pd.Series, column: str) -> dict:
    """Считает бейджи декомпозиции для (dates, values) -- пара серий,
    выровненных по позиции (та же пара, что build_timeseries_points
    получает для линейного графика).

    Возвращает dict:
      applicable: bool
      reason: str | None -- объяснение, если applicable=False
      frequency: str | None -- определённая pandas-частота (например "D")
      frequency_label: str | None -- человекочитаемое имя
      period_used: int | None -- period, переданный в STL
      n_points: int -- число точек, реально использованных
      method: str | None -- "STL"
      trend_pct / seasonal_pct / cyclical_pct / resid_pct: float | None,
        сумма ≈ 100 -- доля дисперсии каждой компоненты (bейджи "уровня шума").
        cyclical_pct -- ОЦЕНОЧНАЯ эвристика (тренд минус скользящее среднее
        тренда), не строгий метод -- см. докстринг compute_decomposition_stats.
    """
    try:
        series, period, inferred, freq_label = _prepare_decomposable_series(dates, values)
    except _NotApplicable as ex:
        return _not_applicable(ex.reason, frequency=ex.frequency)

    try:
        stats = compute_decomposition_stats(series, period=period)
    except Exception as ex:  # noqa: BLE001 -- см. _run_all_checks (validation/engine.py): изоляция сбоя, не 500
        return _not_applicable(f"Декомпозиция не выполнена: {ex}", frequency=inferred)

    total_var = stats["trend_var"] + stats["seasonal_var"] + stats["cyclical_var"] + stats["resid_var"]
    # STL -- итеративный алгоритм, на константном ряде даёт дисперсии
    # порядка 1e-30 (floating-point шум), а не ровный 0.0 -- строгое
    # "<= 0" эту деградацию не ловит. Порог 1e-9 отсекает такой шум,
    # оставаясь far below любой содержательной дисперсии реальных данных.
    if total_var < 1e-9:
        return _not_applicable("Ряд константный (нулевая дисперсия) -- раскладывать нечего", frequency=inferred)

    return {
        "applicable": True,
        "reason": None,
        "frequency": inferred,
        "frequency_label": freq_label,
        "period_used": period,
        "n_points": len(series),
        "method": "STL",
        "trend_pct": round(100 * stats["trend_var"] / total_var, 1),
        "seasonal_pct": round(100 * stats["seasonal_var"] / total_var, 1),
        "cyclical_pct": round(100 * stats["cyclical_var"] / total_var, 1),
        "resid_pct": round(100 * stats["resid_var"] / total_var, 1),
    }


def build_decomposition_series(dates: pd.Series, values: pd.Series, column: str) -> dict:
    """График разложенного ряда (2026-08-19, "визуализировать данный
    декомпозированный ряд на дополнительном графике... 4 составляющие --
    тренд, сезонность, цикличность, остаток"). Переиспользует РЕАЛЬНЫЕ
    ряды компонент из app/preprocessing/decomposition.py::apply_decomposition
    (уже существующая функция, до этого использовалась только косвенно
    через compute_decomposition_stats -- сами ряды trend/seasonal/resid
    нигде не отдавались наружу).

    cyclical -- та же формула, что и в compute_decomposition_stats
    (trend минус его скользящее среднее за 30 точек), но здесь
    сохраняется как РЯД, а не сворачивается в единственную дисперсию.

    Гейтинг (частота/панельные дубли/точки) -- ОБЩИЙ с build_decomposition
    (см. _prepare_decomposable_series) -- одинаковое условие "применимо
    ли вообще" что для бейджей, что для графика, иначе они бы могли
    противоречить друг другу (бейджи says "неприменимо", график
    показывает данные, или наоборот).

    Возвращает dict:
      applicable, reason, method -- как в build_decomposition.
      sampled/sampling_method/original_count -- LTTB-сэмплинг (та же
        инфраструктура, что и в chart_data.py::build_scatter_series),
        если точек больше FULL_POINTS_THRESHOLD -- индексы выбираются
        по ОСТАТКУ (самая шумная/информативная компонента), затем
        ПРИМЕНЯЮТСЯ ОДИНАКОВО ко всем 4 компонентам, чтобы они остались
        выровнены по одной и той же оси X (иначе легенда/наложение на
        графике потеряли бы смысл).
      points: [{x: ISO-дата, trend, seasonal, cyclical, resid}] --
        один объект на точку (не 4 параллельных массива) -- удобно для
        Recharts (один <LineChart data={points}>, 4 <Line dataKey=...>).
    """
    try:
        series, period, inferred, freq_label = _prepare_decomposable_series(dates, values)
    except _NotApplicable as ex:
        return _not_applicable_series(ex.reason, frequency=ex.frequency)

    try:
        decomp = apply_decomposition(series, method="STL", period=period)
    except Exception as ex:  # noqa: BLE001 -- см. build_decomposition: изоляция сбоя, не 500
        return _not_applicable_series(f"Декомпозиция не выполнена: {ex}", frequency=inferred)

    trend = decomp["trend"]
    seasonal = decomp["seasonal"]
    resid = decomp["resid"]
    # Цикличность -- ТА ЖЕ формула, что в compute_decomposition_stats
    # (см. докстринг модуля) -- не задублирована как независимая копия,
    # а буквально та же строка кода.
    cyclical = trend - trend.rolling(_CYCLICAL_ROLLING_WINDOW, min_periods=1).mean()

    # Та же проверка на константный ряд, что и в build_decomposition
    # (найдено собственным parity-тестом: без неё график и бейджи
    # расходились -- бейджи честно говорят "неприменимо", график STL
    # выдавал ~1e-30 floating-point шум как "применимо"). total_var
    # считается из УЖЕ полученных рядов, не повторным вызовом STL.
    total_var = float(trend.var() + seasonal.var() + cyclical.var() + resid.var())
    if total_var < 1e-9:
        return _not_applicable_series("Ряд константный (нулевая дисперсия) -- раскладывать нечего", frequency=inferred)

    n = len(series)
    dates_index = series.index

    if n <= FULL_POINTS_THRESHOLD:
        indices = np.arange(n)
        sampled = False
        sampling_method = None
    else:
        # LTTB по остатку (самая "шумная"/информативная компонента) +
        # сохранение глобальных экстремумов остатка -- тот же принцип,
        # что и в build_scatter_series (chart_data.py), просто индексы
        # общие для всех 4 компонент, не только для одной серии.
        resid_arr = resid.to_numpy(dtype=float)
        x_numeric = np.arange(n, dtype=float)
        kept = _lttb_indices(x_numeric, resid_arr, TARGET_SAMPLED_POINTS)
        extra = {int(np.argmin(resid_arr)), int(np.argmax(resid_arr))}
        extra.update(int(i) for i in _iqr_outlier_positions(resid_arr))
        indices = np.union1d(kept, np.array(sorted(extra), dtype=np.int64))
        sampled = True
        sampling_method = "lttb"

    points = [
        {
            "x": dates_index[i].isoformat(),
            "trend": float(trend.iloc[i]),
            "seasonal": float(seasonal.iloc[i]),
            "cyclical": float(cyclical.iloc[i]),
            "resid": float(resid.iloc[i]),
        }
        for i in indices
    ]

    return {
        "applicable": True,
        "reason": None,
        "method": "STL",
        "sampled": sampled,
        "sampling_method": sampling_method,
        "original_count": n,
        "points": points,
    }


def _not_applicable(reason: str, frequency: str | None = None) -> dict:
    return {
        "applicable": False,
        "reason": reason,
        "frequency": frequency,
        "frequency_label": None,
        "period_used": None,
        "n_points": 0,
        "method": None,
        "trend_pct": None,
        "seasonal_pct": None,
        "cyclical_pct": None,
        "resid_pct": None,
    }


def _not_applicable_series(reason: str, frequency: str | None = None) -> dict:
    return {
        "applicable": False,
        "reason": reason,
        "method": None,
        "sampled": False,
        "sampling_method": None,
        "original_count": 0,
        "points": [],
    }
