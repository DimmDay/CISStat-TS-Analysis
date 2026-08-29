# app/preprocessing/outliers.py
"""Чистое профилирование выбросов для остановки степпера «Выбросы»
(модуль «Предобработка»). Архитектура и дисциплина -- один в один с
app/preprocessing/missing.py: единый profile_outliers(df) для степпера,
обзора и мастера, вместо нескольких независимых реализаций подсчёта.

Четыре метода обнаружения -- перенос легаси app.py (секция "Настройка
обнаружения выбросов", ~строки 8123-8210: IQR, Z-score, Modified Z-score
(MAD), процентильный) и уже существующего validation/outliers.py
(режим маркировки для «Валидации» -- НЕ переиспользуется напрямую здесь,
т.к. `validation/outliers.py::detect_outliers` жёстко завязан на
YAML-конфиг правил и сразу для ВСЕХ числовых колонок одним методом;
здесь нужен per-call выбор метода/параметра для явно выбранных колонок,
как и в apps/api/missing_correction.py).

── Позиция по вопросу "выбросы можно обрабатывать только по остатку
   после декомпозиции" ──

Мнение обосновано статистически: точка, которая выглядит выбросом в
СЫРЫХ значениях (например, пик декабрьских продаж), может быть законной
сезонностью/трендом, а не аномалией -- и наоборот, точка, близкая к
среднему в сыром виде, может быть аномальной ОТНОСИТЕЛЬНО ожидаемого
сезонного паттерна. STL/классическая декомпозиция + анализ остатка --
общепринятый в литературе (Hyndman & Athanasopoulos; seasonal-hybrid ESD)
способ отделить "необычно для этого месяца" от "необычно в принципе".

Тем не менее ДЕЛАТЬ ЭТО ЕДИНСТВЕННЫМ способом для остановки «Выбросы»
архитектурно неверно в этом пайплайне:

1. Порядок степпера: «Выбросы» идёт ДО «Регулярности» и «Декомпозиции»
   (см. CHECKS в TsAnalysisPreprocessing.tsx). На этом этапе датасет ещё
   не обязательно имеет регулярный DatetimeIndex -- декомпозиция для
   него попросту недоступна (см. _prepare_decomposable_series в
   apps/api/decomposition_data.py: неприменима для нерегулярной частоты
   и панельных данных). Требовать декомпозицию как предусловие означало
   бы циклическую зависимость («нельзя обработать выбросы, пока не
   исправлена регулярность, но регулярность может зависеть от того же
   выброса, что искажает частоту/дубликаты дат»).
2. Панельные/кросс-секционные датасеты: та же _prepare_decomposable_series
   явно отклоняет данные с несколькими строками на одну дату
   («несколько сущностей на одну дату» -- ровно случай тестового
   FAO-датасета: Страна × Год). Для такого датасета декомпозиции ПО
   ОПРЕДЕЛЕНИЮ не существует ни для одной колонки -- сделать её
   обязательной означало бы оставить аналитика без единого способа
   обработать явную ошибку ввода (например, "8590" вместо "85.90").
3. Не все выбросы -- следствие сезонности. Ошибка ввода данных видна
   и в сырых значениях, и (обычно) в остатке -- но требовать
   декомпозицию ради обнаружения того, что и так видно на сырых
   данных, добавляет сложность без выигрыша.
4. Обратная связь: сам выброс может ИСКАЗИТЬ декомпозицию (один большой
   выброс сильно смещает оценку тренда/сезонности даже у устойчивого
   STL) -- поэтому текстбук-порядок часто "грубая чистка сырых данных
   → декомпозиция → уточнение на остатке", а не только "декомпозиция
   → остаток".

Решение: обнаружение НЕ дублируется как отдельный "пятый метод" --
статистические методы (IQR/Z-score/MAD/процентиль) одинаково применимы
к сырым значениям ИЛИ к ряду остатка; различие не в алгоритме, а в ТОМ,
КАКОЙ ряд ему подать. profile_outliers всегда работает на сырых
значениях (безусловная, всегда доступная диагностика -- как и
profile_missing). Обнаружение на остатке -- ОПЦИОНАЛЬНАЯ, явно
запрашиваемая возможность мастера исправления (см.
apps/api/outliers_correction.py::detect_mask_on_residual), доступная
только когда декомпозиция для конкретной пары (колонка, дата-колонка)
действительно применима -- то же честное condition-gating, что и у
самой декомпозиции.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

# Минимальный размер выборки для статистики -- та же граница, что и в
# validation/outliers.py (короткие серии дают неустойчивые квантили/mean/std).
_MIN_SAMPLE_SIZE = 10
_MAX_EXAMPLES = 5

METHODS = {"iqr", "zscore", "mad", "percentile"}


def _recommend_method(series: pd.Series) -> str:
    """Перенос эвристики app.py (~строки 8138-8146): сильная асимметрия
    (|skew| > 2) -> MAD; малая выборка (< 100) -> IQR; иначе -> Z-score."""
    if len(series) < 100:
        return "iqr"
    skew = series.skew()
    if pd.notnull(skew) and abs(skew) > 2:
        return "mad"
    return "zscore"


def detect_outlier_mask(
    series: pd.Series,
    method: str,
    param: Any = None,
) -> pd.Series:
    """Возвращает булеву маску (индекс совпадает с series.index) --
    True там, где значение считается выбросом. Не мутирует series.

    Параметры по методу (значения по умолчанию -- те же, что в app.py):
      iqr: param = множитель IQR (float, default 1.5)
      zscore: param = порог |Z| (float, default 3.0)
      mad: param = порог модифицированного Z (float, default 3.5)
      percentile: param = (low, high) в процентах, default (1.0, 99.0)
    """
    if method not in METHODS:
        raise ValueError(f"Неподдерживаемый метод обнаружения выбросов: {method}")

    valid = series.dropna()
    if len(valid) < _MIN_SAMPLE_SIZE:
        return pd.Series(False, index=series.index)

    if method == "iqr":
        multiplier = float(param) if param is not None else 1.5
        q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - multiplier * iqr, q3 + multiplier * iqr
        return (series < lower) | (series > upper)

    if method == "zscore":
        threshold = float(param) if param is not None else 3.0
        std = valid.std()
        if not std or pd.isnull(std):
            return pd.Series(False, index=series.index)
        z = (series - valid.mean()) / std
        return z.abs() > threshold

    if method == "mad":
        threshold = float(param) if param is not None else 3.5
        median = valid.median()
        mad = float(np.median(np.abs(valid - median)))
        if mad == 0:
            return pd.Series(False, index=series.index)
        modified_z = 0.6745 * (series - median) / mad
        return modified_z.abs() > threshold

    # percentile
    low, high = param if param is not None else (1.0, 99.0)
    lower, upper = valid.quantile(low / 100), valid.quantile(high / 100)
    return (series < lower) | (series > upper)


def method_bounds(series: pd.Series, method: str, param: Any) -> Optional[dict[str, float]]:
    """Границы метода (для UI/обзора) -- только для методов с явными
    порогами в единицах исходной величины (iqr/percentile); zscore/mad
    работают в стандартизованных единицах, единой пары "нижняя/верхняя
    граница" в исходной шкале для них нет без искусственного пересчёта."""
    valid = series.dropna()
    if len(valid) < _MIN_SAMPLE_SIZE:
        return None
    if method == "iqr":
        multiplier = float(param) if param is not None else 1.5
        q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
        iqr = q3 - q1
        return {"lower": round(float(q1 - multiplier * iqr), 4), "upper": round(float(q3 + multiplier * iqr), 4)}
    if method == "percentile":
        low, high = param if param is not None else (1.0, 99.0)
        return {
            "lower": round(float(valid.quantile(low / 100)), 4),
            "upper": round(float(valid.quantile(high / 100)), 4),
        }
    return None


def profile_outliers(
    df: pd.DataFrame,
    method: str = "iqr",
    param: Any = None,
) -> list[dict[str, Any]]:
    """Профиль выбросов по КАЖДОЙ числовой колонке датасета (включая
    колонки с 0 выбросов) -- как profile_missing: степпер и обзор должны
    честно показать «проверка пройдена», а не молчание. Нечисловые
    колонки не включаются вовсе (метод статистически неприменим), а не
    показываются с missing_count=0 -- в отличие от пропусков, где
    применимость безусловна для любого типа."""
    profiles: list[dict[str, Any]] = []
    total_rows = len(df)
    for column in df.select_dtypes(include=[np.number]).columns:
        series = df[column]
        valid_count = int(series.notna().sum())
        recommended = _recommend_method(series.dropna()) if valid_count >= _MIN_SAMPLE_SIZE else "iqr"
        if valid_count < _MIN_SAMPLE_SIZE:
            profiles.append({
                "column": str(column),
                "sample_size": valid_count,
                "outlier_count": 0,
                "outlier_pct": None,
                "recommended_method": recommended,
                "bounds": None,
                "outlier_examples": [],
                "insufficient_sample": True,
            })
            continue
        mask = detect_outlier_mask(series, method, param)
        outlier_count = int(mask.sum())
        profiles.append({
            "column": str(column),
            "sample_size": valid_count,
            "outlier_count": outlier_count,
            "outlier_pct": round(outlier_count / total_rows * 100, 2) if total_rows else None,
            "recommended_method": recommended,
            "bounds": method_bounds(series, method, param),
            "outlier_examples": [int(i) for i in df.index[mask][:_MAX_EXAMPLES].tolist()],
            "insufficient_sample": False,
        })
    return profiles


def outliers_summary(profiles: list[dict[str, Any]], total_rows: int) -> dict[str, Any]:
    """Сводка по датасету в целом -- агрегирует уже посчитанный
    profile_outliers (не пересчитывает), как и вызывающий код обычно
    делает для missing_summary рядом с profile_missing."""
    total_outliers = sum(item["outlier_count"] for item in profiles)
    affected_columns = [item["column"] for item in profiles if item["outlier_count"] > 0]
    return {
        "total_rows": total_rows,
        "total_numeric_columns": len(profiles),
        "total_outliers": total_outliers,
        "outlier_rate_pct": round(total_outliers / (total_rows * len(profiles)) * 100, 2) if total_rows and profiles else None,
        "affected_columns": affected_columns,
    }
