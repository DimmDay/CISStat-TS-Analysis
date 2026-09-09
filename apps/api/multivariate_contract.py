# apps/api/multivariate_contract.py
"""Task 131 -- Multivariate Modeling Contract (каркас VAR/VECM, Tasks 132-133).

Инфраструктурный контракт многомерного моделирования, независимый от
HTTP/session-кода (тот же уровень, что model_execution.py / feature_plan.py).
Постановка docs/modeling_task_list.md::Task 131 и точки реализации:

1. **Явный набор endogenous-рядов вместо одной target** -- ``EndogenousSystem``:
   именованные ряды (K >= 2), одинаковая длина, finite, порядок колонок =
   порядок объявления (существенен для векторных моделей); никаких скрытых
   переименований/сортировок.
2. **Общая регулярная временная сетка без скрытой агрегации** --
   ``validate_regular_grid``: дубликаты дат (панель) и нерегулярные интервалы
   отклоняются fail-closed с сообщением «регуляризуйте ряд» (семантика и
   формулировки EDA-стационарности); переиспользуется платформенный
   ``detect_column_frequency`` (pd.infer_freq).  Ни ресемплинга, ни
   интерполяции, ни агрегации контракт не выполняет.
3. **Fold-local стационарность всех компонент и cointegration evidence** --
   ``component_stationarity`` (ADF + KPSS, консенсус-метки зеркалят EDA:
   stationary / non-stationary / inconclusive) и ``fold_cointegration_evidence``
   (Йохансен: trace и max-eig, последовательный ранг).  Обе функции принимают
   ТОЛЬКО переданную матрицу (train-срез фолда) -- полная история им недоступна
   по построению; advisory-функции: на вырожденных/коротких данных честно
   возвращают available=False с причиной, никогда не выдумывают факт.
4. **Векторные OOF-точки, метрики по каждому ряду и агрегированная scaled
   loss** -- ``vector_oof_points`` (long-format: размерность ``series`` поверх
   сертифицированной схемы движка fold/horizon_step/index/label, residual =
   actual - predicted, round 12) и ``compute_vector_metrics`` (формулы ряда
   ИДЕНТИЧНЫ сертифицированной compute_forecast_metrics движка -- паритет
   связан тестами; MASE каждой серии масштабируется train-only naive-MAE
   СВОЕЙ серии).  Агрегированная scaled loss = среднее пер-серийных MASE
   (масштабо-инвариантна); all-or-none: если хоть одна серия не имеет
   MASE -- агрегат честно None, частичная подмена запрещена.
5. **Многомерный baseline и отдельный comparison cohort** --
   ``vector_naive_baseline`` (persistence каждой серии: VAR(0)-аналог; никаких
   fallback-подмен) и ``multivariate_cohort_contract`` (objective=
   "multivariate" + system-блок: состав endogenous, сетка, версия контракта).
   Разделение cohort'ов гарантируется существующим строгим сравнением
   (modeling_comparison.aligned_oof отвергает несовпадение objective и
   cohort_contract) -- привязано тестом.
6. **Диагностика устойчивости и белого шума системы** --
   ``companion_stability`` (собственные значения companion-матрицы из
   коэффициентных матриц PHI_1..PHI_p; устойчивость = max|lambda| < 1
   строго) и ``system_white_noise_diagnostics`` (объединённый
   Portmanteau-тест Люткеполя 2005 §4.4.3 по residual-матрице системы +
   пер-серийный Ljung-Box).  Формула Portmanteau сверена с официальной
   реализацией statsmodels (VARResults.test_whiteness) -- оракул-тест.

Модуль НЕ импортирует backtesting.py (в Tasks 132-133 движок будет
импортировать контракт -- встречный импорт создал бы цикл); паритет формул
с движком гарантируется parity-тестами.  Fail-closed: NaN/Inf, несовпадение
длин/имён/форм, вырожденные данные поднимают MultivariateContractError --
никаких синтетических метрик.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy.stats import chi2
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller, kpss
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from app.data.detectors import detect_column_frequency, smart_to_datetime


MULTIVARIATE_CONTRACT_VERSION = "multivariate-contract-v1"

#: Минимальное число endogenous-рядов системы (modeling.yaml::var.min_series).
MIN_ENDOGENOUS_SERIES = 2

#: Минимальная длина системы; согласовано с MIN_TRAIN_OBSERVATIONS=20
#: EDA validation strategy -- короче фолды невозможны.
MIN_SYSTEM_OBSERVATIONS = 20

#: Отступ наблюдений для Йохансена: n >= k_ar_diff + MIN_COINTEGRATION_MARGIN
#: -- ниже асимптотические критические значения не интерпретируемы.
MIN_COINTEGRATION_MARGIN = 20

#: Допустимые уровни значимости Йохансена -> колонка cvt/cvm (90/95/99).
_JOHANSEN_ALPHA_COLUMNS: dict[float, int] = {0.10: 0, 0.05: 1, 0.01: 2}

#: Агрегированная scaled loss: среднее пер-серийных MASE (масштабо-инвариантно).
SCALED_LOSS_AGGREGATION = "mean_of_per_series_mase"

#: Схема векторной OOF-точки: сертифицированная схема движка (fold,
#: horizon_step, index, label) + размерность ``series`` (long format).
VECTOR_OOF_POINT_KEYS = (
    "fold", "horizon_step", "index", "label", "series",
    "actual", "predicted", "residual",
)

#: Консенсус-метки стационарности компоненты -- зеркалят app/eda/stationarity.
_STATIONARY = "stationary"
_NON_STATIONARY = "non-stationary"
_INCONCLUSIVE = "inconclusive"

_EPS = float(np.finfo(float).eps)


class MultivariateContractError(ValueError):
    """Вход/результат нарушает многомерный контракт Task 131."""


def _finite_matrix(values: np.ndarray, *, argument: str) -> np.ndarray:
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2:
        raise MultivariateContractError(
            f"{argument} должен быть 2D-матрицей наблюдения x ряды, "
            f"получено ndim={matrix.ndim}"
        )
    if not np.isfinite(matrix).all():
        raise MultivariateContractError(f"{argument} содержит NaN/Inf")
    return matrix


def _validated_names(names: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            raise MultivariateContractError(
                "имена endogenous-рядов не могут быть пустыми"
            )
        if name in normalized:
            raise MultivariateContractError(
                f"имена endogenous-рядов дублируются: '{name}'"
            )
        normalized.append(name)
    return tuple(normalized)


def _validate_column(values: Sequence[float], name: str) -> tuple[float, ...]:
    try:
        vector = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise MultivariateContractError(
            f"ряд '{name}' должен быть числовым"
        ) from exc
    if not vector:
        raise MultivariateContractError(f"ряд '{name}' пуст")
    if not np.isfinite(np.asarray(vector, dtype=float)).all():
        raise MultivariateContractError(f"ряд '{name}' содержит NaN/Inf")
    return vector


# ---------------------------------------------------------------------------
# 1. Endogenous system + 2. Общая регулярная временная сетка
# ---------------------------------------------------------------------------

def validate_regular_grid(timestamps: Sequence[str]) -> dict[str, Any]:
    """Валидация общей регулярной временной сетки (fail-closed).

    Дубликаты дат трактуются как панельные данные (выбор одной сущности,
    автоматическая агрегация не выполняется), нерегулярные интервалы --
    как требующие явной регуляризации.  Функция НИКОГДА не ресемплирует,
    не интерполирует и не сортирует вход; частота определяется платформенным
    ``detect_column_frequency`` (pd.infer_freq на отсортированных уникальных
    датах) -- та же семантика, что в EDA-стационарности.
    """
    converted = smart_to_datetime(pd.Series(list(timestamps)))
    if converted.isna().any():
        raise MultivariateContractError(
            "во временной оси есть нераспознанные даты; сначала исправьте "
            "временную ось"
        )
    if converted.duplicated().any():
        duplicate_count = int(converted.duplicated(keep=False).sum())
        raise MultivariateContractError(
            f"во временной оси повторяются даты ({duplicate_count} точек). "
            "Это похоже на панельные данные: выберите одну сущность; "
            "автоматическая агрегация не выполняется."
        )
    if len(converted) >= 2 and not converted.is_monotonic_increasing:
        raise MultivariateContractError(
            "временная ось не упорядочена по возрастанию; отсортируйте вход "
            "явно -- контракт не выполняет скрытую пересортировку"
        )
    frequency = detect_column_frequency(converted)["code"]
    if frequency is None:
        raise MultivariateContractError(
            "временная сетка нерегулярна. Многомерные модели предполагают "
            "общую равноотстоящую сетку; сначала регуляризуйте ряд."
        )
    return {
        "regular": True,
        "frequency": str(frequency),
        "n_observations": int(len(converted)),
        "start": pd.Timestamp(converted.iloc[0]).isoformat(),
        "end": pd.Timestamp(converted.iloc[-1]).isoformat(),
    }


@dataclass(frozen=True)
class EndogenousSystem:
    """Явный набор endogenous-рядов одной системы на общей сетке.

    Порядок ``names`` = порядок колонок матрицы = порядок объявления;
    скрытые переименования/сортировки запрещены (существенен для
    интерпретации векторных коэффициентов VAR/VECM).
    """

    series: Mapping[str, tuple[float, ...]]
    timestamps: Optional[tuple[str, ...]] = None
    grid: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.series, Mapping) or not self.series:
            raise MultivariateContractError(
                f"система требует не менее {MIN_ENDOGENOUS_SERIES} "
                "endogenous-рядов"
            )
        # 1. Общая регулярная сетка валидируется ПЕРВОЙ (специфичная ошибка
        # многомерного контракта важнее общей минимальной длины); никаких
        # скрытых ресемплинга/сортировки -- только fail-closed.
        grid: Optional[dict[str, Any]] = None
        if self.timestamps:
            first_series = next(iter(self.series.values()))
            if len(self.timestamps) != len(first_series):
                raise MultivariateContractError(
                    "длина временной оси не совпадает с длиной рядов системы"
                )
            grid = validate_regular_grid(self.timestamps)
        # 2. Серия за серией: имена, числовость, finite, равные длины.
        validated: dict[str, tuple[float, ...]] = {}
        reference_length: Optional[int] = None
        for raw_name, values in self.series.items():
            name = str(raw_name).strip()
            if not name:
                raise MultivariateContractError(
                    "имена endogenous-рядов не могут быть пустыми"
                )
            if name in validated:
                raise MultivariateContractError(
                    f"имена endogenous-рядов дублируются: '{name}'"
                )
            vector = _validate_column(values, name)
            if reference_length is None:
                reference_length = len(vector)
            elif len(vector) != reference_length:
                raise MultivariateContractError(
                    f"ряд '{name}': длина {len(vector)} не равна "
                    f"{reference_length}"
                )
            validated[name] = vector
        if len(validated) < MIN_ENDOGENOUS_SERIES:
            raise MultivariateContractError(
                f"система требует не менее {MIN_ENDOGENOUS_SERIES} "
                f"endogenous-рядов, получено {len(validated)}"
            )
        if reference_length is not None and reference_length < MIN_SYSTEM_OBSERVATIONS:
            raise MultivariateContractError(
                f"система требует не менее {MIN_SYSTEM_OBSERVATIONS} "
                f"наблюдений, получено {reference_length}"
            )
        object.__setattr__(self, "series", validated)
        if self.timestamps:
            object.__setattr__(self, "grid", grid)
            object.__setattr__(
                self, "timestamps", tuple(str(value) for value in self.timestamps),
            )
        else:
            object.__setattr__(self, "timestamps", None)
            object.__setattr__(self, "grid", None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.series)

    @property
    def n_series(self) -> int:
        return len(self.series)

    @property
    def n_observations(self) -> int:
        return len(next(iter(self.series.values())))

    def matrix(self) -> np.ndarray:
        """T x K float-матрица; колонки в порядке ``names``."""
        return np.column_stack(
            [np.asarray(self.series[name], dtype=float) for name in self.names],
        )

    def train_slice(self, stop: int) -> np.ndarray:
        """Train-срез матрицы [0, stop) -- fold-local по построению."""
        return self.matrix()[:stop]

    def test_slice(self, start: int, stop: int) -> np.ndarray:
        """Test-срез матрицы [start, stop)."""
        return self.matrix()[start:stop]

    def head(self, stop: int) -> "EndogenousSystem":
        """Подсистема [0, stop) (fold-local построение baseline/evidence)."""
        if not 0 < stop <= self.n_observations:
            raise MultivariateContractError(
                f"head: stop={stop} вне диапазона (0, {self.n_observations}]"
            )
        series = {name: values[:stop] for name, values in self.series.items()}
        timestamps = self.timestamps[:stop] if self.timestamps else None
        return build_endogenous_system(series, timestamps=timestamps)


def build_endogenous_system(
    series: Mapping[str, Sequence[float]],
    *,
    timestamps: Optional[Sequence[str]] = None,
) -> EndogenousSystem:
    """Фабрика системы с полной валидацией (сетка/длины/finite/имена)."""
    stamps = tuple(str(value) for value in timestamps) if timestamps else None
    return EndogenousSystem(series=dict(series), timestamps=stamps)


# ---------------------------------------------------------------------------
# 3a. Fold-local стационарность всех компонент (advisory evidence)
# ---------------------------------------------------------------------------

def component_stationarity(
    values: Sequence[float], *, alpha: float = 0.05,
) -> dict[str, Any]:
    """ADF (уровень) + KPSS (уровень) одной компоненты, консенсус EDA.

    ADF: H0 = единичный корень (reject => стационарность).  KPSS: H0 =
    стационарность (reject => единичный корень).  Консенсус зеркалит
    семантику app/eda/stationarity: stationary / non-stationary /
    inconclusive.  Advisory: вырожденный вход (константный ряд, слишком
    короткая выборка) даёт available=False с причиной -- факт никогда
    не выдумывается.
    """
    vector = np.asarray(
        [float(value) for value in values], dtype=float,
    )
    if vector.size == 0:
        raise MultivariateContractError("компонента пуста")
    if not np.isfinite(vector).all():
        raise MultivariateContractError("компонента содержит NaN/Inf")
    result: dict[str, Any] = {
        "available": False, "reason": None, "consensus": None, "alpha": alpha,
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf_stat, adf_p, *_ = adfuller(vector, regression="c", autolag="AIC")
            kpss_stat, kpss_p, *_ = kpss(vector, regression="c", nlags="auto")
    except Exception as exc:  # noqa: BLE001 -- library-native отказ = evidence
        result["reason"] = f"unit-root тесты недоступны: {exc}"
        return result
    adf_reject = bool(float(adf_p) < alpha)
    kpss_reject = bool(float(kpss_p) < alpha)
    if adf_reject and not kpss_reject:
        consensus = _STATIONARY
    elif not adf_reject and kpss_reject:
        consensus = _NON_STATIONARY
    else:
        consensus = _INCONCLUSIVE
    result.update({
        "available": True,
        "consensus": consensus,
        "adf": {
            "statistic": float(adf_stat), "p_value": float(adf_p),
            "reject_null": adf_reject,
            "null_hypothesis": "Единичный корень",
        },
        "kpss": {
            "statistic": float(kpss_stat), "p_value": float(kpss_p),
            "reject_null": kpss_reject,
            "null_hypothesis": "Стационарность вокруг уровня",
        },
    })
    return result


def fold_stationarity_evidence(
    matrix: np.ndarray, names: Sequence[str], *, alpha: float = 0.05,
) -> dict[str, Any]:
    """Fold-local стационарность КАЖДОЙ компоненты train-среза фолда.

    Функция видит ТОЛЬКО переданную матрицу (train-срез фолда) -- полная
    история недоступна по построению; fold-locality привязана тестом
    (система с разладкой: train-срез stationary, полная история
    non-stationary).
    """
    validated = _finite_matrix(matrix, argument="stationarity matrix")
    system_names = _validated_names(names)
    if validated.shape[1] != len(system_names):
        raise MultivariateContractError(
            f"число имён ({len(system_names)}) не совпадает с числом колонок "
            f"матрицы ({validated.shape[1]})"
        )
    components = {
        name: component_stationarity(validated[:, position], alpha=alpha)
        for position, name in enumerate(system_names)
    }
    unavailable = [
        f"{name}: {components[name]['reason']}"
        for name in system_names if not components[name]["available"]
    ]
    return {
        "available": not unavailable,
        "reason": None if not unavailable else "; ".join(unavailable),
        "components": components,
        "n_observations": int(validated.shape[0]),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# 3b. Cointegration evidence (fold-local Johansen, advisory)
# ---------------------------------------------------------------------------

def fold_cointegration_evidence(
    matrix: np.ndarray,
    *,
    det_order: int = 0,
    k_ar_diff: int = 1,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Йохансен (trace + max-eig) на train-срезе фолда -- evidence, не факт.

    Последовательное правило ранга: rank = число подряд идущих отвержений
    H0: r <= i (lr[i] > cv[i, alpha]) начиная с i=0.  ``cointegration_
    evidence`` = rank >= 1.  Короткие фолды (n < k_ar_diff + margin) и
    вырожденные данные честно возвращают available=False с причиной --
    ранг никогда не выдумывается.
    """
    if det_order not in {-1, 0, 1}:
        raise MultivariateContractError(
            f"det_order должен быть -1/0/1, получено {det_order}"
        )
    k_ar_diff = int(k_ar_diff)
    if not 1 <= k_ar_diff <= 12:
        raise MultivariateContractError(
            f"k_ar_diff должен быть в [1, 12], получено {k_ar_diff}"
        )
    if alpha not in _JOHANSEN_ALPHA_COLUMNS:
        raise MultivariateContractError(
            f"alpha должна быть одной из {sorted(_JOHANSEN_ALPHA_COLUMNS)}, "
            f"получено {alpha}"
        )
    column = _JOHANSEN_ALPHA_COLUMNS[float(alpha)]
    evidence: dict[str, Any] = {
        "available": False, "reason": None, "trace": None, "max_eig": None,
        "cointegration_evidence": False, "k_ar_diff": k_ar_diff,
        "det_order": int(det_order), "alpha": alpha,
    }
    validated = _finite_matrix(matrix, argument="cointegration matrix")
    evidence["n_observations"] = int(validated.shape[0])
    if validated.shape[1] < MIN_ENDOGENOUS_SERIES:
        raise MultivariateContractError(
            f"cointegration evidence требует не менее {MIN_ENDOGENOUS_SERIES} "
            f"рядов, получено {validated.shape[1]}"
        )
    if validated.shape[0] < k_ar_diff + MIN_COINTEGRATION_MARGIN:
        evidence["reason"] = (
            f"выборка {validated.shape[0]} наблюдений слишком коротка для "
            f"Йохансена при k_ar_diff={k_ar_diff} (минимум "
            f"{k_ar_diff + MIN_COINTEGRATION_MARGIN}); асимптотические "
            "критические значения не интерпретируемы"
        )
        return evidence
    try:
        result = coint_johansen(validated, int(det_order), k_ar_diff)
    except Exception as exc:  # noqa: BLE001 -- вырожденная система
        evidence["reason"] = f"Йохансен недоступен: {exc}"
        return evidence

    def _rank(statistics: np.ndarray, critical: np.ndarray) -> int:
        rank = 0
        for position in range(len(statistics)):
            if statistics[position] > critical[position, column]:
                rank = position + 1
            else:
                break
        return rank

    trace_stats = [float(value) for value in result.lr1]
    max_eig_stats = [float(value) for value in result.lr2]
    trace_cv = {
        "90": [float(value) for value in result.cvt[:, 0]],
        "95": [float(value) for value in result.cvt[:, 1]],
        "99": [float(value) for value in result.cvt[:, 2]],
    }
    max_eig_cv = {
        "90": [float(value) for value in result.cvm[:, 0]],
        "95": [float(value) for value in result.cvm[:, 1]],
        "99": [float(value) for value in result.cvm[:, 2]],
    }
    trace_rank = _rank(result.lr1, result.cvt)
    max_eig_rank = _rank(result.lr2, result.cvm)
    evidence.update({
        "available": True,
        "trace": {
            "statistics": trace_stats, "critical_values": trace_cv,
            "rank": trace_rank,
        },
        "max_eig": {
            "statistics": max_eig_stats, "critical_values": max_eig_cv,
            "rank": max_eig_rank,
        },
        "cointegration_evidence": trace_rank >= 1,
    })
    return evidence


# ---------------------------------------------------------------------------
# 4a. Векторные OOF-точки (long format)
# ---------------------------------------------------------------------------

def vector_oof_points(
    fold: int,
    test_indices: Sequence[int],
    actual_matrix: np.ndarray,
    predicted_matrix: np.ndarray,
    names: Sequence[str],
    labels: Optional[Sequence[Optional[str]]] = None,
) -> list[dict[str, Any]]:
    """Long-format OOF-точки: схема движка + размерность ``series``.

    Порядок детерминирован: шаг горизонта, затем порядок объявления серий.
    residual = actual - predicted, round 12 -- конвенция движка
    backtesting.py сохранена.
    """
    fold = int(fold)
    if fold < 1:
        raise MultivariateContractError("fold должен быть положительным")
    system_names = _validated_names(names)
    k = len(system_names)
    actual = _finite_matrix(actual_matrix, argument="actual matrix")
    predicted = _finite_matrix(predicted_matrix, argument="predicted matrix")
    if actual.shape != predicted.shape:
        raise MultivariateContractError(
            f"длина/форма actual {actual.shape} и predicted {predicted.shape} "
            "не совпадают"
        )
    if actual.shape[1] != k:
        raise MultivariateContractError(
            f"число имён ({k}) не совпадает с числом колонок ({actual.shape[1]})"
        )
    horizon = actual.shape[0]
    if horizon < 1:
        raise MultivariateContractError("горизонт пуст")
    if len(test_indices) != horizon:
        raise MultivariateContractError(
            f"test_indices: длина {len(test_indices)} не равна горизонту "
            f"{horizon}"
        )
    if labels is not None and len(labels) != horizon:
        raise MultivariateContractError(
            f"labels: длина {len(labels)} не равна горизонту {horizon}"
        )
    points: list[dict[str, Any]] = []
    for step, index in enumerate(test_indices, 1):
        label = None if labels is None else labels[step - 1]
        for position, name in enumerate(system_names):
            actual_value = float(actual[step - 1, position])
            predicted_value = float(predicted[step - 1, position])
            points.append({
                "fold": fold,
                "horizon_step": step,
                "index": int(index),
                "label": None if label is None else str(label),
                "series": name,
                "actual": actual_value,
                "predicted": predicted_value,
                "residual": round(actual_value - predicted_value, 12),
            })
    return points


# ---------------------------------------------------------------------------
# 4b. Метрики по каждому ряду + агрегированная scaled loss
# ---------------------------------------------------------------------------

def vector_metric_scales(
    train_matrix: np.ndarray,
    names: Sequence[str],
    *,
    seasonal_period: int = 1,
) -> dict[str, dict[str, Optional[float]]]:
    """Train-only MASE/RMSSE-знаменатели КАЖДОЙ серии (naive своей серии).

    Формулы идентичны backtesting.compute_metric_scales (паритет связан
    тестом); вызов ДОЛЖЕН выполняться только на train-срезе фолда --
    leakage-safety обеспечивается передачей train-матрицы.
    """
    validated = _finite_matrix(train_matrix, argument="train matrix")
    system_names = _validated_names(names)
    if validated.shape[1] != len(system_names):
        raise MultivariateContractError(
            f"число имён ({len(system_names)}) не совпадает с числом колонок "
            f"({validated.shape[1]})"
        )
    period = max(1, int(seasonal_period))
    scales: dict[str, dict[str, Optional[float]]] = {}
    for position, name in enumerate(system_names):
        column = validated[:, position]
        if column.size <= period:
            scales[name] = {"mase_scale": None, "rmsse_scale": None}
            continue
        scale_errors = column[period:] - column[:-period]
        mae_scale = float(np.mean(np.abs(scale_errors)))
        rmsse_scale = float(np.sqrt(np.mean(np.square(scale_errors))))
        scales[name] = {
            "mase_scale": mae_scale if mae_scale > _EPS else None,
            "rmsse_scale": rmsse_scale if rmsse_scale > _EPS else None,
        }
    return scales


def compute_vector_metrics(
    actual_matrix: np.ndarray,
    predicted_matrix: np.ndarray,
    names: Sequence[str],
    *,
    mase_scales: Optional[Mapping[str, Optional[float]]] = None,
    rmsse_scales: Optional[Mapping[str, Optional[float]]] = None,
) -> dict[str, Any]:
    """Метрики каждого ряда + агрегированная scaled loss (mean of MASE).

    Формулы ряда идентичны backtesting.compute_forecast_metrics (паритет
    связан тестом).  ``weighted_score`` всегда None: нормализация допустима
    только внутри comparison cohort.  Aggregated scaled loss -- all-or-none:
    если хоть у одной серии MASE не определён (нулевой train-only scale),
    агрегат честно None; частичная подмена запрещена.
    """
    from apps.api.schemas import BacktestMetrics

    actual = _finite_matrix(actual_matrix, argument="actual matrix")
    predicted = _finite_matrix(predicted_matrix, argument="predicted matrix")
    if actual.shape != predicted.shape:
        raise MultivariateContractError(
            f"форма actual {actual.shape} и predicted {predicted.shape} "
            "не совпадают"
        )
    if actual.shape[0] < 1:
        raise MultivariateContractError("метрики на пустом горизонте")
    system_names = _validated_names(names)
    if actual.shape[1] != len(system_names):
        raise MultivariateContractError(
            f"число имён ({len(system_names)}) не совпадает с числом колонок "
            f"({actual.shape[1]})"
        )
    mase_scales = dict(mase_scales) if mase_scales else {}
    rmsse_scales = dict(rmsse_scales) if rmsse_scales else {}
    per_series: dict[str, BacktestMetrics] = {}
    for position, name in enumerate(system_names):
        actual_col = actual[:, position]
        predicted_col = predicted[:, position]
        errors = actual_col - predicted_col
        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(np.square(errors))))
        nonzero = np.abs(actual_col) > _EPS
        mape = (
            float(np.mean(np.abs(errors[nonzero] / actual_col[nonzero])) * 100)
            if nonzero.any() else None
        )
        denominator = np.abs(actual_col) + np.abs(predicted_col)
        valid_smape = denominator > _EPS
        smape = (
            float(np.mean(200 * np.abs(errors[valid_smape]) / denominator[valid_smape]))
            if valid_smape.any() else 0.0
        )
        mase_scale = mase_scales.get(name)
        rmsse_scale = rmsse_scales.get(name)
        mase = mae / mase_scale if mase_scale is not None else None
        rmsse = rmse / rmsse_scale if rmsse_scale is not None else None
        per_series[name] = BacktestMetrics(
            mae=round(mae, 6), rmse=round(rmse, 6),
            mape=round(mape, 6) if mape is not None else None,
            mase=round(mase, 6) if mase is not None else None,
            smape=round(smape, 6),
            rmsse=round(rmsse, 6) if rmsse is not None else None,
            mape_valid_points=int(nonzero.sum()), weighted_score=None,
        )
    mases = [per_series[name].mase for name in system_names]
    scaled_loss: Optional[float] = None
    if all(value is not None for value in mases):
        scaled_loss = round(float(np.mean([float(value) for value in mases])), 6)
    return {
        "per_series": per_series,
        "scaled_loss": scaled_loss,
        "scaled_loss_aggregation": SCALED_LOSS_AGGREGATION,
        "n_series": len(system_names),
        "n_points": int(actual.shape[0]),
    }


# ---------------------------------------------------------------------------
# 5a. Многомерный baseline (persistence каждой серии, VAR(0)-аналог)
# ---------------------------------------------------------------------------

def vector_naive_baseline(
    system: EndogenousSystem, horizon: int,
) -> dict[str, tuple[float, ...]]:
    """Persistence-прогноз каждой серии: последнее значение train-среза.

    Fold-local: передавайте ``system.head(train_end)`` -- baseline строится
    от последнего наблюдения ПЕРЕДАННОЙ системы.  Никаких fallback-подмен:
    вырожденный вход отклоняется валидацией системы.
    """
    horizon = int(horizon)
    if horizon < 1:
        raise MultivariateContractError("horizon должен быть положительным")
    matrix = system.matrix()
    last_row = matrix[-1]
    return {
        name: (float(last_row[position]),) * horizon
        for position, name in enumerate(system.names)
    }


# ---------------------------------------------------------------------------
# 5b. Отдельный comparison cohort
# ---------------------------------------------------------------------------

def multivariate_cohort_contract(
    system: EndogenousSystem,
    *,
    series_fingerprints: Mapping[str, str],
    seasonal_period: int = 1,
) -> dict[str, Any]:
    """Cohort-контракт многомерной системы (расширяет контракт движка).

    Схема ключей верхнего уровня идентична backtesting.build_backtest_plan
    (objective / series_fingerprints / feature_contract / metric_policy);
    добавлен блок ``system`` (состав endogenous, сетка, версия контракта).
    Разделение cohort'ов гарантируется строгим сравнением aligned_oof:
    несовпадение objective и cohort_contract отвергается движком.
    """
    system_names = system.names
    fingerprints = {
        str(name).strip(): str(value)
        for name, value in dict(series_fingerprints).items()
    }
    if set(fingerprints) != set(system_names) or len(fingerprints) != len(system_names):
        raise MultivariateContractError(
            f"series_fingerprints {sorted(fingerprints)} не соответствуют "
            f"endogenous-рядам системы {list(system_names)}"
        )
    empty_values = [name for name, value in fingerprints.items() if not value]
    if empty_values:
        raise MultivariateContractError(
            f"series_fingerprints содержат пустые значения: {empty_values}"
        )
    seasonal_period = int(seasonal_period)
    if seasonal_period < 1:
        raise MultivariateContractError(
            "seasonal_period должен быть положительным"
        )
    return {
        "objective": "multivariate",
        "series_fingerprints": {name: fingerprints[name] for name in system_names},
        "feature_contract": {
            "historic": [], "future_known": [], "static": [], "policy": "none",
        },
        "metric_policy": {
            "metrics": ["mae", "rmse", "mape", "mase", "smape", "rmsse"],
            "primary": "rmse",
            "aggregation": "test_size_weighted_folds",
            "seasonal_period": seasonal_period,
            "vector": {
                "per_series_metrics": [
                    "mae", "rmse", "mape", "smape", "mase", "rmsse",
                ],
                "scaled_loss_aggregation": SCALED_LOSS_AGGREGATION,
                "oof_point_keys": list(VECTOR_OOF_POINT_KEYS),
            },
        },
        "system": {
            "contract_version": MULTIVARIATE_CONTRACT_VERSION,
            "endogenous": list(system_names),
            "n_observations": system.n_observations,
            "grid": dict(system.grid) if system.grid else None,
        },
    }


# ---------------------------------------------------------------------------
# 6a. Диагностика устойчивости системы
# ---------------------------------------------------------------------------

def companion_stability(
    coefficient_matrices: Sequence[np.ndarray],
) -> dict[str, Any]:
    """Устойчивость VAR-системы по companion-матрице PHI_1..PHI_p.

    Companion-матрица p*K x p*K: верхний блок [PHI_1 ... PHI_p], ниже --
    сдвиговые единичные блоки.  Система устойчива <=> все собственные
    значения по модулю < 1 (строгое неравенство: |lambda| = 1 -- граница
    единичного круга, устойчивостью не считается).
    """
    matrices = [
        np.asarray(block, dtype=float)
        for block in coefficient_matrices
    ]
    if not matrices:
        raise MultivariateContractError(
            "список коэффициентных матриц пуст: companion_stability требует "
            "хотя бы одну матрицу PHI"
        )
    k = matrices[0].shape
    order = len(matrices)
    for position, block in enumerate(matrices, 1):
        if block.ndim != 2 or block.shape[0] != block.shape[1]:
            raise MultivariateContractError(
                f"коэффициентная матрица {position} должна быть квадратной, "
                f"получено shape={block.shape}"
            )
        if block.shape != k:
            raise MultivariateContractError(
                f"коэффициентная матрица {position}: размерность "
                f"{block.shape} не совпадает с первой {k}"
            )
        if not np.isfinite(block).all():
            raise MultivariateContractError(
                "коэффициентные матрицы содержат NaN/Inf"
            )
        if block.shape[0] < 1:
            raise MultivariateContractError(
                "коэффициентные матрицы пусты"
            )
    k_dim = k[0]
    companion = np.zeros((order * k_dim, order * k_dim), dtype=float)
    companion[:k_dim, :] = np.hstack(matrices)
    if order > 1:
        companion[k_dim:, :-k_dim] = np.eye(order * k_dim - k_dim)
    eigenvalues = np.linalg.eigvals(companion)
    moduli = [float(abs(value)) for value in eigenvalues]
    max_modulus = max(moduli) if moduli else float("inf")
    return {
        "max_modulus": max_modulus,
        "is_stable": bool(max_modulus < 1.0),
        "eigenvalue_moduli": sorted(moduli),
        "order": order,
        "n_series": k_dim,
    }


# ---------------------------------------------------------------------------
# 6b. Диагностика белого шума системы
# ---------------------------------------------------------------------------

def _portmanteau_statistic(
    residuals: np.ndarray, nlags: int, *, adjusted: bool,
) -> float:
    """Объединённый Portmanteau Люткеполя (2005, §4.4.3).

    C_j = (1/T) sum_{t=j+1..T} u_t u_{t-j}' (u центрированы, как в
    statsmodels._compute_acov).  statistic = T^2 * sum_j tr(C_j' C0^-1 C_j
    C0^-1) / (T - j) при adjusted=True (поправка на малые выборки), иначе
    T * sum_j tr(...).  Формула сверена с официальной реализацией
    statsmodels VARResults.test_whiteness -- оракул-тест связывает паритет.
    """
    nobs, _ = residuals.shape
    centered = residuals - residuals.mean(axis=0)
    covariances: list[np.ndarray] = []
    for lag in range(nlags + 1):
        if lag > 0:
            covariances.append(centered[lag:].T @ centered[:-lag] / nobs)
        else:
            covariances.append(centered.T @ centered / nobs)
    cov0_inverse = np.linalg.inv(covariances[0])
    statistic = 0.0
    for lag in range(1, nlags + 1):
        term = np.trace(
            covariances[lag].T @ cov0_inverse @ covariances[lag] @ cov0_inverse,
        )
        if adjusted:
            term /= nobs - lag
        statistic += term
    statistic *= float(nobs) ** 2 if adjusted else float(nobs)
    return float(statistic)


def system_white_noise_diagnostics(
    residuals: np.ndarray,
    *,
    nlags: int,
    fitted_var_order: int = 0,
    adjusted: bool = True,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Белый шум системы: объединённый Portmanteau + пер-серийный Ljung-Box.

    H0 объединённого теста: остатки системы -- белый шум; reject при
    p < alpha (df = K^2 * (nlags - p)).  ``fitted_var_order`` -- порядок
    оцениванной модели (число лагов, съедающих степени свободы); для VECM
    передавайте ранг+детерминированную спецификацию в терминах свободных
    параметров на уравнение.  Вырожденная ковариация остатков (идеальный
    фит) -- fail-closed ошибка, а не фиктивный «идеальный белый шум».
    """
    matrix = np.asarray(residuals, dtype=float)
    if matrix.ndim != 2:
        raise MultivariateContractError(
            "residuals должен быть 2D-матрицей наблюдения x ряды"
        )
    if not np.isfinite(matrix).all():
        raise MultivariateContractError("residuals содержит NaN/Inf")
    nobs, k = matrix.shape
    nlags = int(nlags)
    fitted_var_order = int(fitted_var_order)
    if nlags < 1:
        raise MultivariateContractError("nlags должен быть положительным")
    if fitted_var_order < 0:
        raise MultivariateContractError(
            "fitted_var_order не может быть отрицательным"
        )
    if nlags <= fitted_var_order:
        raise MultivariateContractError(
            f"nlags ({nlags}) должен быть больше fitted_var_order "
            f"({fitted_var_order})"
        )
    if nobs <= nlags + fitted_var_order:
        raise MultivariateContractError(
            f"длина residuals ({nobs}) недостаточна: требуется больше, чем "
            f"nlags={nlags} + fitted_var_order={fitted_var_order}"
        )
    df = k * k * (nlags - fitted_var_order)
    try:
        statistic = _portmanteau_statistic(matrix, nlags, adjusted=adjusted)
    except np.linalg.LinAlgError as exc:
        raise MultivariateContractError(
            f"ковариация остатков вырождена (идеальный фит?): {exc}"
        ) from exc
    p_value = float(chi2.sf(statistic, df))
    per_series = []
    for position in range(k):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = acorr_ljungbox(
                matrix[:, position], lags=[nlags], model_df=fitted_var_order,
                return_df=True,
            )
        lb_stat = float(table["lb_stat"].iloc[-1])
        lb_pvalue = float(table["lb_pvalue"].iloc[-1])
        per_series.append({
            "index": position,
            "statistic": lb_stat,
            "p_value": lb_pvalue,
            "reject_null": bool(lb_pvalue < alpha),
        })
    return {
        "available": True,
        "joint": {
            "statistic": statistic,
            "df": int(df),
            "p_value": p_value,
            "reject_null": bool(p_value < alpha),
            "adjusted": bool(adjusted),
            "nlags": nlags,
            "fitted_var_order": fitted_var_order,
            "alpha": alpha,
        },
        "per_series": per_series,
        "n_observations": int(nobs),
        "n_series": int(k),
    }
