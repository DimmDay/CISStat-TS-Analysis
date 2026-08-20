# apps/api/decomposition_data.py
"""
Подготовка данных для бейджей декомпозиции (Тренд/Сезонность/Цикличность/
Остаток) -- остановка «График» вкладки «Загрузка» (согласовано с
тимлидом 2026-08-14, "уровень шума в данных" на старте анализа).

Обёртка над app/preprocessing/decomposition.py::compute_decomposition_stats
(STL, statsmodels) -- САМА формула декомпозиции НЕ переписывается (проект
уже применял этот принцип к validation/*, models/* -- app/core не
дублируется). Этот модуль добавляет то, чего не было у сырой функции:

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
  3. Нормализация дисперсий в проценты (сумма≈100%) для бейджей.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.preprocessing.decomposition import compute_decomposition_stats
from app.data.detectors import smart_to_datetime

# Частота -> (period для STL, человекочитаемое имя, минимум периодов для
# осмысленной декомпозиции -- 2 полных цикла, как и в apply_decomposition,
# но здесь это ЯВНОЕ условие гейта, а не implicit ValueError из statsmodels).
_FREQ_TO_PERIOD: dict[str, tuple[int, str]] = {
    "D": (7, "дневная (недельная сезонность)"),
    "B": (5, "рабочие дни (недельная сезонность)"),
    "W": (52, "недельная (годовая сезонность)"),
    "M": (12, "месячная (годовая сезонность)"),
    "MS": (12, "месячная (годовая сезонность)"),
    "Q": (4, "квартальная (годовая сезонность)"),
    "QS": (4, "квартальная (годовая сезонность)"),
}
_MIN_PERIODS_MULTIPLIER = 2  # тот же порог, что и в apply_decomposition


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
    df = pd.DataFrame({"date": smart_to_datetime(dates), "value": pd.to_numeric(values, errors="coerce")})
    df = df.dropna(subset=["date", "value"])

    if len(df) == 0:
        return _not_applicable("В колонке нет ни одной пары (дата, значение) без пропусков")

    # ── Защита от панельных данных: несколько строк на одну дату ──
    n_unique_dates = df["date"].nunique()
    if n_unique_dates < len(df):
        return _not_applicable(
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
        return _not_applicable(
            f"Частота данных ({freq_desc}) не поддерживает внутрипериодную "
            f"сезонность -- для годовых/нерегулярных рядов декомпозиция "
            f"тренд/сезонность/цикл неприменима по определению",
            frequency=inferred,
        )
    period, freq_label = resolved

    min_points = _MIN_PERIODS_MULTIPLIER * period
    if len(df) < min_points:
        return _not_applicable(
            f"Недостаточно точек для декомпозиции: {len(df)} из минимум {min_points} "
            f"(2 полных периода по {period} точек при частоте «{freq_label}»)",
            frequency=inferred,
        )

    series = pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(df["date"]))
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
        "n_points": len(df),
        "method": "STL",
        "trend_pct": round(100 * stats["trend_var"] / total_var, 1),
        "seasonal_pct": round(100 * stats["seasonal_var"] / total_var, 1),
        "cyclical_pct": round(100 * stats["cyclical_var"] / total_var, 1),
        "resid_pct": round(100 * stats["resid_var"] / total_var, 1),
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
