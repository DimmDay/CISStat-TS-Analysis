# app/preprocessing/panel.py
"""Панельный контракт и паспорт панели (PANEL-MODELS-3a, спека
spec_panel_models_2026-10-20.md §3a).

Панельный контур моделирования НЕ продавливается через однорядный паспорт
(``app.core.passport``): панель -- сущность × время, а не один ряд. Этот
модуль -- честный контракт панели:

- ``build_panel_frame`` -- fail-closed контракт: колонки существуют и
  различны, дубликаты (entity, date) запрещены, каждая сущность строго
  регулярна внутри себя (переиспользование ``validation.regularity``,
  Правила 14/15), NaN-профиль по сущностям; возвращает честную фактуру
  (n_entities, пересечение сеток, balance, t_per_entity, n_valid).
- ``within_transform`` / ``between_transform`` / ``entity_dummies`` /
  ``panel_lag`` -- по-сущностные преобразования (архитектура §1086-1090):
  ЖЁСТКОЕ правило -- все временные операции строго ``groupby(entity)``;
  плоские сдвиги (``df.shift``) для панельных данных запрещены
  (архитектурная норма 1561) -- гвард-тесты в
  ``tests/unit/test_panel_preprocessing.py``.
- ``panel_fingerprint`` -- устойчивый SHA-256 контента панели
  (entity, date, значения) -- основа истечения checkpoint ``panel_entry``.
- ``build_panel_passport`` -- честный паспорт панели для checkpoint
  ``panel_entry``: фактура + по-сущностный профиль достаточности
  (переиспользование ``validation.sufficiency.profile_sufficiency``) +
  вычислимость панельных моделей (гейты §3b) + advisory Pesaran CD.
- ``pesaran_cd`` -- advisory-тест кросс-секционной зависимости (Pesaran,
  2004) на пересечении сеток; результат НЕ блокирует (прецедент
  cointegration-evidence Task 132).

Границы: однорядный контур (паспорт, passport-серия, checkpoint
modeling_entry) не затрагивается; GMM (Arellano-Bond) -- отдельная
постановка PANEL-GMM-4; без новых зависимостей (statsmodels/numpy/scipy).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from validation.regularity import profile_regularity
from validation.sufficiency import profile_sufficiency

CONTRACT_VERSION = "panel-contract-v1"
PANEL_PASSPORT_VERSION = "panel-passport-v1"

# Гейты применимости панельных моделей (спека §3b; подробные описания и
# исполнители FE/RE/Panel VAR -- этап 3b app/modeling/panel_models.py).
MIN_ENTITIES_FE_RE = 5
MIN_T_PER_ENTITY_FE_RE = 10
MIN_ENTITIES_PANEL_VAR = 5
MIN_VARS_PANEL_VAR = 2
# Гейт DeepAR-панели (PANEL-MODELS-3c, entity-pivot): честный перенос
# правила Task 142 («DeepAR активируется только для настоящей панели»)
# на сущностный контур.  MIN_OBS_PER_ENTITY_DEEPAR -- зеркало
# DEEPAR_MIN_TRAIN=30 адаптера (apps/api/model_impls/deepar.py) --
# семейный пол нейро-пятёрки; enforced-гейт per fold -- адаптер
# (fail-closed, max(DEEPAR_MIN_TRAIN, input_size + horizon)).
MIN_ENTITIES_DEEPAR_PANEL = 5
MIN_OBS_PER_ENTITY_DEEPAR = 30
# Эвристика T_common >= 3 * n_vars * (p + 1): VAR(1) -- минимум применимости,
# VAR(2) -- рекомендованный запас (warning при нехватке).
PANEL_VAR_MAX_LAG_BASE = 2  # p + 1 при p = 1
PANEL_VAR_RECOMMENDED_BASE = 3  # p + 1 при p = 2
# Производственные капы (render.com free tier 512MB, прецедент FC-MON-2).
CAPACITY_WARN_ENTITIES = 200
CAPACITY_REFUSE_ENTITIES = 2000
# Минимум общих периодов для парной корреляции в Pesaran CD.
CD_MIN_COMMON_T = 3

BALANCED = "balanced"
UNBALANCED = "unbalanced"


class PanelContractError(ValueError):
    """Fail-closed нарушение панельного контракта (честное сообщение)."""


# ── Честная фактура панели ──────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelFrame:
    """Иммутабельная фактура панели, прошедшая fail-closed контракт.

    ``frame`` -- нормализованная защитная копия (datetime-даты, числовые
    значения, сортировка по (entity, date)); исходный DataFrame потребителя
    не мутируется. Мутировать ``frame`` извне -- нарушение контракта.
    """

    frame: pd.DataFrame
    date_column: str
    entity_column: str
    value_columns: tuple[str, ...]
    target_column: str
    n_entities: int
    n_dates_common: int
    balance: str  # "balanced" | "unbalanced"
    t_per_entity: Dict[str, float]  # {"min", "median", "max"}
    n_valid: int  # строки с валидной парой (date, target)
    dates_common: tuple = ()
    nan_profile: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-совместимое представление фактуры (без самого фрейма)."""
        return {
            "contract_version": CONTRACT_VERSION,
            "date_column": self.date_column,
            "entity_column": self.entity_column,
            "value_columns": list(self.value_columns),
            "target_column": self.target_column,
            "n_entities": int(self.n_entities),
            "n_dates_common": int(self.n_dates_common),
            "balance": self.balance,
            "t_per_entity": {key: float(value) for key, value in self.t_per_entity.items()},
            "n_valid": int(self.n_valid),
            "nan_profile": {
                str(entity): {key: int(value) if isinstance(value, (int, np.integer)) else value
                              for key, value in profile.items()}
                for entity, profile in self.nan_profile.items()
            },
        }


def _require_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise PanelContractError(
            f"Колонки панельного контракта отсутствуют в датасете: {', '.join(missing)}"
        )


def _validate_column_composition(
    date_column: str,
    entity_column: str,
    value_columns: Sequence[str],
    target_column: str,
) -> tuple[str, ...]:
    values = tuple(str(column) for column in value_columns)
    if date_column == entity_column:
        raise PanelContractError(
            "Временная и сущностная колонки должны различаться: "
            f"получена одна колонка '{date_column}'"
        )
    if len(set(values)) != len(values):
        raise PanelContractError("Колонки значений панели должны различаться между собой")
    if date_column in values or entity_column in values:
        raise PanelContractError(
            "Колонки значений панели не могут совпадать с временной или сущностной колонкой"
        )
    if target_column not in values:
        raise PanelContractError(
            f"Целевая колонка '{target_column}' должна входить в value_columns панели"
        )
    return values


def _normalize_dates(series: pd.Series, name: str) -> pd.Series:
    converted = pd.to_datetime(series, errors="coerce")
    if isinstance(converted.dtype, pd.DatetimeTZDtype):
        converted = converted.dt.tz_convert(None)
    if converted.isna().any():
        bad = int(converted.isna().sum())
        raise PanelContractError(
            f"Колонка даты '{name}' содержит невалидные временные метки "
            f"({bad} из {len(converted)} не приводятся к datetime); "
            "панельный контракт требует полную дату у каждой строки"
        )
    return converted.astype("datetime64[ns]")


def _normalize_values(df: pd.DataFrame, value_columns: Sequence[str]) -> pd.DataFrame:
    numeric = pd.DataFrame(index=df.index)
    for column in value_columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        original_non_null = int(df[column].notna().sum())
        if original_non_null > 0 and int(converted.notna().sum()) == 0:
            raise PanelContractError(
                f"Колонка значений '{column}' не числовая: ни одно значение "
                "не приводится к числу"
            )
        numeric[column] = converted.astype("float64")
    return numeric


def _check_entity_uniqueness(working: pd.DataFrame, entity_column: str, date_column: str) -> None:
    duplicated = working.duplicated(subset=[entity_column, date_column], keep=False)
    if duplicated.any():
        sample = working.loc[duplicated, entity_column].astype(str).unique()[:3].tolist()
        raise PanelContractError(
            f"Обнаружены дубликаты (сущность, дата): {int(duplicated.sum())} строк "
            f"(пример сущностей: {sample}); панельный контракт требует "
            "уникальность (entity, date) -- устраните дубли на остановке «Валидация»"
        )


def _check_per_entity_regularity(
    working: pd.DataFrame, entity_column: str, date_column: str
) -> None:
    """Каждая сущность строго регулярна внутри себя -- переиспользование
    канонического профиля регулярности ``validation.regularity.profile_regularity``
    (по-сущностные гэпы/дубли/сортировка, Правила 14/15; тот же профиль,
    что у API «Валидации» -- единый канон регулярности платформы)."""
    profile = profile_regularity(
        working,
        {"regularity": {"date_column": date_column, "entity_column": entity_column}},
    )
    if not profile.get("applicable"):
        raise PanelContractError(
            f"Не удалось проверить регулярность панели: {profile.get('applicability_message')}"
        )
    gaps = int(profile.get("gap_count", 0))
    if gaps > 0:
        raise PanelContractError(
            f"Панель нерегулярна: {gaps} гэпов внутри сущностей; контракт "
            "требует строгую регулярность каждой сущности -- приведите сетку "
            "к регулярной в «Предобработке» (регулярность) или агрегируйте по времени"
        )


def build_panel_frame(
    df: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str,
    value_columns: Sequence[str],
    target_column: str,
) -> PanelFrame:
    """Fail-closed контракт панели -> честная фактура :class:`PanelFrame`.

    Требования: колонки существуют и различны; даты приводятся к datetime
    полностью; значения числовые; НЕТ дубликатов (entity, date); каждая
    сущность строго регулярна внутри себя (гэпы запрещены, сетки разных
    сущностей могут отличаться -- несбалансированность легитимна).
    Исходный df не мутируется.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise PanelContractError("Входные данные пусты: панельный контракт требует непустой DataFrame")
    _require_columns(df, [date_column, entity_column, target_column, *value_columns])
    values = _validate_column_composition(date_column, entity_column, value_columns, target_column)

    if df[entity_column].isna().any():
        bad = int(df[entity_column].isna().sum())
        raise PanelContractError(
            f"Сущностная колонка '{entity_column}' содержит {bad} пустых значений; "
            "каждая строка панели должна принадлежать сущности"
        )

    working = pd.DataFrame({
        entity_column: df[entity_column].astype(object).where(df[entity_column].notna(), None),
        date_column: _normalize_dates(df[date_column], date_column),
        **{column: _normalize_values(df[[column]], [column])[column] for column in values},
    })

    _check_entity_uniqueness(working, entity_column, date_column)
    _check_per_entity_regularity(working, entity_column, date_column)

    working = working.sort_values([entity_column, date_column], kind="mergesort").reset_index(drop=True)

    entity_series = working[entity_column]
    date_sets = working.groupby(entity_series, sort=False)[date_column].apply(
        lambda s: frozenset(s.tolist())
    )
    balance = BALANCED if date_sets.nunique() <= 1 else UNBALANCED

    common: Optional[set] = None
    for date_set in date_sets:
        common = set(date_set) if common is None else (common & set(date_set))
    dates_common = tuple(sorted(common or set()))
    n_dates_common = len(dates_common)

    counts = working.groupby(entity_series, sort=False)[date_column].nunique()
    t_per_entity = {
        "min": int(counts.min()),
        "median": float(counts.median()),
        "max": int(counts.max()),
    }

    target = working[target_column]
    finite_target = np.isfinite(target.to_numpy(dtype=float, na_value=np.nan))
    valid_mask = target.notna().to_numpy() & finite_target
    n_valid = int(valid_mask.sum())

    nan_profile: Dict[str, Dict[str, Any]] = {}
    for entity_value, group in working.groupby(entity_series, sort=False):
        key = str(entity_value)
        profile: Dict[str, Any] = {"rows": int(len(group))}
        target_group = group[target_column]
        profile["target_missing"] = int(
            (target_group.isna() | ~np.isfinite(target_group.to_numpy(dtype=float, na_value=np.nan))).sum()
        )
        for column in values:
            if column == target_column:
                continue
            column_group = group[column]
            profile[f"{column}_missing"] = int(
                (column_group.isna() | ~np.isfinite(column_group.to_numpy(dtype=float, na_value=np.nan))).sum()
            )
        nan_profile[key] = profile

    return PanelFrame(
        frame=working,
        date_column=str(date_column),
        entity_column=str(entity_column),
        value_columns=values,
        target_column=str(target_column),
        n_entities=int(date_sets.size),
        n_dates_common=n_dates_common,
        balance=balance,
        t_per_entity=t_per_entity,
        n_valid=n_valid,
        dates_common=dates_common,
        nan_profile=nan_profile,
    )


# ── Fingerprint панели ──────────────────────────────────────────────────────

def panel_fingerprint(
    df: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str,
    value_columns: Sequence[str],
    target_column: str,
) -> str:
    """Устойчивый SHA-256 контента панели (entity, date, значения).

    Не зависит от порядка строк (каноническая сортировка по entity, date)
    и от имён колонок значений -- состав колонок сверяется ОТДЕЛЬНО
    (checkpoint сверяет паспорт-состав до сравнения fingerprint). Детерминирован
    между процессами (pd.util.hash_pandas_object с фиксированным ключом).
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise PanelContractError("Fingerprint определён только для непустого DataFrame")
    _require_columns(df, [date_column, entity_column, target_column, *value_columns])
    values = _validate_column_composition(date_column, entity_column, value_columns, target_column)

    canonical = pd.DataFrame({
        entity_column: df[entity_column].astype(str),
        date_column: pd.to_datetime(df[date_column], errors="coerce"),
        **{
            column: pd.to_numeric(df[column], errors="coerce").astype("float64")
            for column in values
        },
    })
    if isinstance(canonical[date_column].dtype, pd.DatetimeTZDtype):
        canonical[date_column] = canonical[date_column].dt.tz_convert(None)
    canonical[date_column] = canonical[date_column].astype("datetime64[ns]")
    canonical = canonical.sort_values([entity_column, date_column], kind="mergesort")

    hashed = pd.util.hash_pandas_object(canonical, index=False, categorize=False)
    payload = hashed.to_numpy(dtype="uint64").tobytes()
    return hashlib.sha256(payload).hexdigest()


# ── По-сущностные преобразования (архитектура §1086-1090, норма 1561) ──────

def _require_entity(df: pd.DataFrame, entity_column: str, columns: Sequence[str]) -> None:
    _require_columns(df, [entity_column, *columns])
    if df[entity_column].isna().any():
        raise PanelContractError(
            f"Сущностная колонка '{entity_column}' содержит пустые значения: "
            "по-сущностные преобразования определены только для полных сущностей"
        )


def within_transform(
    df: pd.DataFrame, *, entity_column: str, columns: Sequence[str]
) -> pd.DataFrame:
    """Within-преобразование: отклонение от среднего сущности.

    Строго ``df.groupby(entity)[col].transform(...)`` (архитектура 1087):
    утечки между сущностями исключены по построению. Возвращает копию df.
    """
    _require_entity(df, entity_column, columns)
    result = df.copy()
    grouped = result.groupby(entity_column, sort=False)
    for column in columns:
        result[column] = grouped[column].transform(lambda s: s - s.mean())
    return result


def between_transform(
    df: pd.DataFrame, *, entity_column: str, columns: Sequence[str]
) -> pd.DataFrame:
    """Between-преобразование: средние сущностей (константа внутри сущности)."""
    _require_entity(df, entity_column, columns)
    result = df.copy()
    grouped = result.groupby(entity_column, sort=False)
    for column in columns:
        result[column] = grouped[column].transform("mean")
    return result


def panel_lag(
    df: pd.DataFrame,
    *,
    entity_column: str,
    column: str,
    lags: Sequence[int],
) -> pd.DataFrame:
    """Лаги строго внутри сущностей: ``groupby(entity)[column].shift(n)``.

    ЖЁСТКОЕ правило панельных лагов (архитектура 1087-1088, норма 1561):
    плоский ``df[column].shift(n)`` утекает последнее значение одной
    сущности в первую дату другой -- этот модуль такого не допускает
    (гвард-тест ``TestPanelLag.test_no_cross_entity_leakage_flat_shift_detected``).
    Колонки именуются ``{column}_lag{n}``; первые n дат каждой сущности -- NaN.
    """
    _require_entity(df, entity_column, [column])
    normalized_lags: list[int] = []
    for lag in lags:
        lag_int = int(lag)
        if lag_int < 1:
            raise PanelContractError(f"Лаги должны быть положительными целыми: получен {lag}")
        normalized_lags.append(lag_int)
    result = df.copy()
    grouped = result.groupby(entity_column, sort=False)[column]
    for lag in normalized_lags:
        result[f"{column}_lag{lag}"] = grouped.shift(lag)
    return result


def entity_dummies(
    df: pd.DataFrame, *, entity_column: str, drop_first: bool = True
) -> pd.DataFrame:
    """Фиксированные эффекты: dummy-матрица сущностей, выровненная по индексу.

    ``drop_first=True`` (умолчание) -- для OLS с интерсептом (базовая
    сущность поглощается интерсептом); ``drop_first=False`` -- для
    спецификаций без интерсепта. Колонки названы значениями сущностей.
    """
    _require_entity(df, entity_column, [])
    dummies = pd.get_dummies(
        df[entity_column].astype(str), prefix="", prefix_sep="",
        drop_first=drop_first, dtype=int,
    )
    dummies.index = df.index
    return dummies


# ── Advisory: Pesaran CD ────────────────────────────────────────────────────

def pesaran_cd(
    df: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str,
    column: str,
) -> Dict[str, Any]:
    """Advisory-тест кросс-секционной зависимости (Pesaran, 2004).

    CD = sqrt(2T / (N(N-1))) * Σ_{i<j} ρ_ij -- парные корреляции сущностей
    на ОБЩЕМ пересечении сеток. Результат advisory: недоступность/вырожденные
    случаи возвращают ``available=False`` с честной причиной, никогда не
    блокируют паспорт (прецедент cointegration-evidence Task 132).
    """
    unavailable = {
        "available": False, "method": "pesaran_cd", "statistic": None,
        "p_value": None, "n_entities": 0, "t_common": 0, "n_pairs": 0,
        "n_pairs_skipped": 0, "note": "advisory -- не блокирует паспорт",
    }
    try:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return {**unavailable, "reason": "пустой вход"}
        _require_columns(df, [date_column, entity_column, column])

        working = pd.DataFrame({
            entity_column: df[entity_column],
            date_column: pd.to_datetime(df[date_column], errors="coerce"),
            column: pd.to_numeric(df[column], errors="coerce"),
        })
        if isinstance(working[date_column].dtype, pd.DatetimeTZDtype):
            working[date_column] = working[date_column].dt.tz_convert(None)
        working = working.dropna(subset=[date_column])

        pivot = working.pivot_table(
            index=date_column, columns=entity_column, values=column, aggfunc="mean",
        )
        n_entities = int(pivot.shape[1])
        # Общее пересечение сеток: даты, где нет NaN-структурных пропусков сущностей
        common_dates = pivot.index[~pivot.isna().any(axis=1)]
        grid = pivot.loc[common_dates]
        t_common = int(grid.shape[0])

        if n_entities < 2:
            return {**unavailable, "reason": "нужно минимум 2 сущности"}
        if t_common < CD_MIN_COMMON_T:
            return {
                **unavailable,
                "n_entities": n_entities,
                "t_common": t_common,
                "reason": f"общая сетка слишком коротка: {t_common} < {CD_MIN_COMMON_T} периодов",
            }

        matrix = grid.to_numpy(dtype=float)
        n_pairs = 0
        n_skipped = 0
        rho_sum = 0.0
        for i in range(n_entities - 1):
            for j in range(i + 1, n_entities):
                pair = matrix[:, [i, j]]
                pair = pair[np.isfinite(pair).all(axis=1)]
                if len(pair) < CD_MIN_COMMON_T:
                    n_skipped += 1
                    continue
                variance = pair.std(axis=0, ddof=1)
                if np.any(variance <= 0):
                    n_skipped += 1
                    continue
                rho = float(np.corrcoef(pair[:, 0], pair[:, 1])[0, 1])
                if not np.isfinite(rho):
                    n_skipped += 1
                    continue
                rho_sum += rho
                n_pairs += 1

        if n_pairs == 0:
            return {
                **unavailable, "n_entities": n_entities, "t_common": t_common,
                "n_pairs_skipped": n_skipped,
                "reason": "нет ни одной вычислимой пары корреляций на общей сетке",
            }

        cd_statistic = float(np.sqrt(2.0 * t_common / (n_entities * (n_entities - 1))) * rho_sum)
        from scipy.stats import norm as _norm

        p_value = float(2.0 * _norm.sf(abs(cd_statistic)))
        return {
            "available": True,
            "method": "pesaran_cd",
            "statistic": cd_statistic,
            "p_value": min(max(p_value, 0.0), 1.0),
            "n_entities": n_entities,
            "t_common": t_common,
            "n_pairs": n_pairs,
            "n_pairs_skipped": n_skipped,
            "note": "advisory -- не блокирует паспорт; значимый CD говорит о "
                    "кросс-секционной зависимости (учтите при выборе спецификации)",
        }
    except PanelContractError as error:
        return {**unavailable, "reason": str(error)}
    except Exception as error:  # noqa: BLE001 -- advisory-профиль, никогда не блокирует
        return {**unavailable, "reason": f"вычисление недоступно: {error}"}


# ── Гейты панельных моделей (§3b; исполнители -- этап 3b) ──────────────────

def _capacity_facts(n_entities: int) -> Dict[str, Any]:
    capacity: Dict[str, Any] = {
        "n_entities": int(n_entities),
        "warn_above": CAPACITY_WARN_ENTITIES,
        "refuse_above": CAPACITY_REFUSE_ENTITIES,
        "warning": None,
        "refused": bool(n_entities > CAPACITY_REFUSE_ENTITIES),
    }
    if capacity["refused"]:
        capacity["warning"] = (
            f"Панель превышает производственный кап: {n_entities} сущностей > "
            f"{CAPACITY_REFUSE_ENTITIES} -- исполнение отказано (ограничение памяти среды 512MB)"
        )
    elif n_entities > CAPACITY_WARN_ENTITIES:
        capacity["warning"] = (
            f"Большая панель: {n_entities} сущностей > {CAPACITY_WARN_ENTITIES} -- "
            "оценка FE/RE может быть медленной и память-ёмкой (среда 512MB)"
        )
    return capacity


def _fe_re_computability(frame: PanelFrame, model_name: str, refused: bool) -> Dict[str, Any]:
    reasons: list[str] = []
    n_exog = len(frame.value_columns) - 1
    gates = {
        "n_entities": int(frame.n_entities),
        "t_min": int(frame.t_per_entity["min"]),
        "n_exog": int(n_exog),
    }
    if refused:
        reasons.append(
            f"Производственный кап превышен: {frame.n_entities} сущностей > "
            f"{CAPACITY_REFUSE_ENTITIES} -- честный отказ вместо риска OOM (среда 512MB)"
        )
        return {"applicable": False, "reasons": reasons, "gates": gates}
    if frame.n_entities < MIN_ENTITIES_FE_RE:
        reasons.append(
            f"Недостаточно сущностей: {frame.n_entities} < {MIN_ENTITIES_FE_RE} "
            "(минимум для панельных FE/RE)"
        )
    if frame.t_per_entity["min"] < MIN_T_PER_ENTITY_FE_RE:
        reasons.append(
            f"Недостаточно наблюдений внутри сущностей: минимальная длина "
            f"{int(frame.t_per_entity['min'])} < {MIN_T_PER_ENTITY_FE_RE}"
        )
    if n_exog < 1:
        reasons.append(
            "Нет экзогенных переменных: статическая панель FE/RE прогнозирует "
            "только по сценарным путям экзогенных факторов; без экзогенных -- "
            "динамические панели это контур GMM (в разработке, PANEL-GMM-4)"
        )
    return {"applicable": not reasons, "reasons": reasons, "gates": gates}


def _panel_var_computability(frame: PanelFrame, refused: bool) -> Dict[str, Any]:
    reasons: list[str] = []
    n_vars = len(frame.value_columns)
    need_min = 3 * n_vars * PANEL_VAR_MAX_LAG_BASE
    need_recommended = 3 * n_vars * PANEL_VAR_RECOMMENDED_BASE
    gates = {
        "n_entities": int(frame.n_entities),
        "n_vars": int(n_vars),
        "t_common": int(frame.n_dates_common),
        "need_t_common_var1": int(need_min),
    }
    warning: Optional[str] = None
    if refused:
        reasons.append(
            f"Производственный кап превышен: {frame.n_entities} сущностей > "
            f"{CAPACITY_REFUSE_ENTITIES} -- честный отказ вместо риска OOM (среда 512MB)"
        )
        return {"applicable": False, "reasons": reasons, "gates": gates, "warning": None}
    if frame.balance != BALANCED:
        reasons.append(
            "Panel VAR требует общий сбалансированный пересекающийся сетки дат: "
            f"панель {UNBALANCED}; сведите панель к общей сетке "
            "(фильтр сущности/агрегация по времени в «Загрузке»)"
        )
    if frame.n_entities < MIN_ENTITIES_PANEL_VAR:
        reasons.append(
            f"Недостаточно сущностей: {frame.n_entities} < {MIN_ENTITIES_PANEL_VAR} "
            "(минимум для Panel VAR)"
        )
    if n_vars < MIN_VARS_PANEL_VAR:
        reasons.append(
            f"Panel VAR требует минимум {MIN_VARS_PANEL_VAR} переменные: "
            f"в панели {n_vars}"
        )
    if frame.n_dates_common < need_min:
        reasons.append(
            f"Недостаточная длина общей сетки: T_common={frame.n_dates_common} < "
            f"3·n_vars·(p+1)={need_min} для VAR(1)"
        )
    elif frame.n_dates_common < need_recommended:
        warning = (
            f"Малое T_common={frame.n_dates_common} для VAR(2) "
            f"(рекомендуется ≥ {need_recommended}): надёжна оценка только VAR(1)"
        )
    return {"applicable": not reasons, "reasons": reasons, "gates": gates, "warning": warning}


def _sanitize_json(value: Any) -> Any:
    """Рекурсивная нормализация numpy-скаляров к JSON-совместимым типам."""
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


@dataclass(frozen=True)
class PanelPassport:
    """Честный паспорт панели -- фиксируемый факт checkpoint ``panel_entry``.

    Содержит фактуру :class:`PanelFrame`, по-сущностный профиль достаточности
    (переиспользование ``profile_sufficiency``), вычислимость панельных
    моделей с гейтами §3b и advisory-факты (Pesaran CD, капы памяти).
    Паспорт НЕ подменяет однорядный паспорт (R4) -- это документ панельного
    контура с собственным checkpoint.
    """

    contract_version: str = PANEL_PASSPORT_VERSION
    date_column: str = ""
    entity_column: str = ""
    value_columns: tuple[str, ...] = ()
    target_column: str = ""
    n_entities: int = 0
    n_dates_common: int = 0
    balance: str = UNBALANCED
    t_per_entity: Dict[str, float] = field(default_factory=dict)
    n_valid: int = 0
    nan_profile: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sufficiency: Dict[str, Any] = field(default_factory=dict)
    models: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cross_sectional_dependence: Dict[str, Any] = field(default_factory=dict)
    capacity: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON-совместимое представление (сохраняется в checkpoint panel_entry).

        ``columns`` дублирует состав колонок структурой -- checkpoint сверяет
        его ДО сравнения fingerprint (значения разных колонок могут совпадать).
        """
        return _sanitize_json({
            "contract_version": self.contract_version,
            "date_column": self.date_column,
            "entity_column": self.entity_column,
            "value_columns": list(self.value_columns),
            "target_column": self.target_column,
            "columns": {
                "date_column": self.date_column,
                "entity_column": self.entity_column,
                "value_columns": list(self.value_columns),
                "target_column": self.target_column,
            },
            "n_entities": int(self.n_entities),
            "n_dates_common": int(self.n_dates_common),
            "balance": self.balance,
            "t_per_entity": {key: float(value) for key, value in self.t_per_entity.items()},
            "n_valid": int(self.n_valid),
            "nan_profile": self.nan_profile,
            "sufficiency": self.sufficiency,
            "models": self.models,
            "cross_sectional_dependence": self.cross_sectional_dependence,
            "capacity": self.capacity,
            "created_at": self.created_at,
        })


def _deepar_panel_computability(frame: PanelFrame, refused: bool) -> Dict[str, Any]:
    """Гейт вычислимости DeepAR-панели (PANEL-MODELS-3c, entity-pivot).

    Честный перенос правила Task 142 на сущностный контур: настоящая
    панель >= DEEPAR_PANEL_MIN_ENTITIES (5) сущностей; per-entity длина
    >= MIN_OBS_PER_ENTITY_DEEPAR (зеркало DEEPAR_MIN_TRAIN=30 адаптера --
    семейный пол нейро-пятёрки; оконный гейт input_size+horizon
    пересчитывается адаптером на каждом fold'е fail-closed).
    Зеркало-константы задокументированы: единый источник enforced-гейта
    -- адаптер (fail-closed на фите), паспорт -- честный предпросмотр."""
    reasons: list[str] = []
    gates = {
        "n_entities": int(frame.n_entities),
        "min_entities": int(MIN_ENTITIES_DEEPAR_PANEL),
        "t_min": int(frame.t_per_entity["min"]),
        "min_entity_observations": int(MIN_OBS_PER_ENTITY_DEEPAR),
    }
    if refused:
        reasons.append(
            f"Производственный кап превышен: {frame.n_entities} сущностей > "
            f"{CAPACITY_REFUSE_ENTITIES} -- честный отказ вместо риска OOM (среда 512MB)"
        )
        return {"applicable": False, "reasons": reasons, "gates": gates}
    if frame.n_entities < MIN_ENTITIES_DEEPAR_PANEL:
        reasons.append(
            f"Недостаточно сущностей для глобальной нейромодели: "
            f"{frame.n_entities} < {MIN_ENTITIES_DEEPAR_PANEL} "
            "(честный перенос правила Task 142 на настоящую панель)"
        )
    if frame.t_per_entity["min"] < MIN_OBS_PER_ENTITY_DEEPAR:
        reasons.append(
            f"Недостаточно наблюдений внутри сущностей для нейро-модели: "
            f"минимальная длина {int(frame.t_per_entity['min'])} < "
            f"{MIN_OBS_PER_ENTITY_DEEPAR} (семейный пол нейро-пятёрки)"
        )
    return {
        "applicable": not reasons,
        "reasons": reasons,
        "gates": gates,
    }


def build_panel_passport(
    df: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str,
    value_columns: Sequence[str],
    target_column: str,
    rules: Optional[Dict[str, Any]] = None,
) -> PanelPassport:
    """Построить честный :class:`PanelPassport` (checkpoint ``panel_entry``).

    Шаги: fail-closed ``build_panel_frame`` -> по-сущностный профиль
    достаточности (``profile_sufficiency`` с зафиксированными колонками) ->
    гейты вычислимости FE/RE/Panel VAR + честный отказ GMM -> advisory
    Pesaran CD по target -> капы производительности. Advisory-факты не
    блокируют; fail-closed нарушения останавливают построение честной ошибкой.
    """
    frame = build_panel_frame(
        df,
        date_column=date_column,
        entity_column=entity_column,
        value_columns=value_columns,
        target_column=target_column,
    )

    user_sufficiency = dict((rules or {}).get("sufficiency") or {})
    sufficiency_rules = {
        **(rules or {}),
        "sufficiency": {
            **user_sufficiency,
            "date_column": str(date_column),
            "entity_column": str(entity_column),
            "target_column": str(target_column),
        },
    }
    try:
        sufficiency = profile_sufficiency(df, sufficiency_rules)
    except Exception as error:  # noqa: BLE001 -- профиль достаточности не блокирует паспорт
        sufficiency = {
            "applicable": False,
            "applicability_message": f"профиль достаточности недоступен: {error}",
            "groups": [],
            "groups_total": 0,
        }

    capacity = _capacity_facts(frame.n_entities)
    models: Dict[str, Dict[str, Any]] = {
        "fixed_effects": _fe_re_computability(frame, "fixed_effects", capacity["refused"]),
        "random_effects": _fe_re_computability(frame, "random_effects", capacity["refused"]),
        "panel_var": _panel_var_computability(frame, capacity["refused"]),
        "deepar_panel": _deepar_panel_computability(frame, capacity["refused"]),
        "gmm": {
            "applicable": False,
            "reasons": [
                "Динамические панели (Arellano-Bond GMM) -- вне контура "
                "PANEL-MODELS-3: отдельная постановка PANEL-GMM-4"
            ],
            "gates": {},
        },
    }

    cd = pesaran_cd(
        frame.frame, date_column=frame.date_column,
        entity_column=frame.entity_column, column=frame.target_column,
    )

    return PanelPassport(
        date_column=frame.date_column,
        entity_column=frame.entity_column,
        value_columns=frame.value_columns,
        target_column=frame.target_column,
        n_entities=frame.n_entities,
        n_dates_common=frame.n_dates_common,
        balance=frame.balance,
        t_per_entity=dict(frame.t_per_entity),
        n_valid=frame.n_valid,
        nan_profile=dict(frame.nan_profile),
        sufficiency=_sanitize_json(sufficiency),
        models=models,
        cross_sectional_dependence=cd,
        capacity=capacity,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
