# apps/api/neural_contract.py
"""Task 137 -- Neural Runtime Contract (каркас нейро-адаптеров, Tasks 138-142).

Инфраструктурный контракт нейро-runtime, независимый от HTTP/session-кода
(тот же уровень, что multivariate_contract.py Task 131 и
volatility_contract.py Task 134).  Постановка
docs/modeling_task_list.md::Task 137 -- унификация ПЯТИ нейро-моделей
(LSTM/GRU, N-BEATS, N-HiTS, TFT, DeepAR) на NeuralForecast вместо смеси
Darts/GluonTS/PyTorch Forecasting -- и точки реализации:

1. **Единый long-format unique_id/ds/y** -- ``to_long_format``: широкая
   платформенная таблица (одна серия или честная панель) приводится к
   формату NeuralForecast; временная ось, значения и заказанные exog-
   колонки валидируются fail-closed (NaN/Inf, дубликаты (unique_id, ds),
   нерегулярная сетка -- отказ; НИКАКИХ ресемплинга/интерполяции/скрытой
   сортировки данных сверх детерминированного порядка (unique_id, ds)).
   ``validate_long_format`` возвращает честную сводку (n_series,
   n_observations, frequency), переиспользуя сертифицированный
   ``validate_regular_grid`` Task 131 для каждой серии панели.
2. **Historic/future/static exogenous contract** --
   ``build_exogenous_plan``: классификация exog-колонок ОБЯЗАТЕЛЬНО
   объявляется вызовом ({futr, hist, stat} keyword-списки) -- никакого
   скрытого угадывания; валидируются существование, конечность, константность
   static per unique_id и непересекаемость ролей.  ``NeuralExogenousPlan``
   хранит immutbable списки + sha256-подпись (попадает в cohort-контракт).
   ``validate_future_exogenous_frame`` -- futr-план требует полного
   покрытия горизонта (n_series * horizon строк, без NaN); hist-колонки
   нужны только на train; ``build_static_frame`` -- одна строка на серию.
3. **CPU/GPU worker capabilities** -- ``neural_worker_capabilities``:
   GPU-сигнал деплоя через model_jobs.gpu_runtime_available (никакого
   eager-импорта torch); ``resolve_neural_device``: requires_gpu без
   GPU-сигнала -- честный отказ NeuralRuntimeUnavailableError, ТИХОЕ
   CPU-понижение запрещено (yaml-правило D06 requires_gpu).
4. **Checkpoints вне Redis JSON** -- ``NeuralCheckpointStore``:
   filesystem-бэкенд (env CISSTAT_NEURAL_CHECKPOINT_DIR или
   data/neural_checkpoints), размерный потолок, sha256-анти-тампер
   (прецедент VolatilityTarget), JSON-safe pointer; в Redis/session-JSON
   попадает ТОЛЬКО маленький pointer, никогда байты чекпойнта.
5. **Early stopping, seed, max epochs/steps** -- ``NeuralTrainingConfig``:
   bounded-конфиг с ЕДИНЫМ бюджетом ``max_steps``.  NeuralForecast 3.x
   fail-closed отвергает max_epochs ("deprecated, use max_steps") --
   унификация и означает один бюджетный рычаг вместо расхождения
   epoch/step-конвенций Darts/GluonTS/PyTorch Forecasting.
   Early stopping: patience>0 требует val_size>0; seed детерминированно
   разводится по фолдам ``fold_seed``.
6. **Probabilistic losses и quantiles** -- ``interval_levels_for_alpha``:
   симметричные уровни из alpha (0.2 -> 10/50/90); ``resolve_probabilistic_loss``:
   whitelist-функций потерь; probabilistic-функции (quantile/mqloss)
   требуют уровней.  Вывод квантилей point-loss моделей neuralforecast --
   conformal-путь (fit prediction_intervals + predict level), см. neural_runtime.
7. **Продолжение job после рестарта** -- ``restore_resume_state``:
   job-запись хранит pointer; после рестарта воркер восстанавливает
   HeavyState с диска по pointer (sha256-проверка) или честно отказывается --
   продолжение возможно ТОЛЬКО с верифицированным состоянием, молчаливый
   retrain с нуля контрактом запрещён (решение о retrain -- за job-протоколом,
   который обязан его записать).

Модуль НЕ импортирует backtesting.py и роутеры; torch/neuralforecast на
уровне модуля НЕ импортируются (ленивая загрузка -- уровень
model_impls/neural_runtime.py, единственная точка их импорта).  Реестр v2
НЕ расширяется: пять вертикальных срезов Tasks 138-142 добавят свои
записи с runtime_available=neuralforecast_runtime_available() из этого
контракта (прецедент: Task 134 не добавляла garch-запись).
Fail-closed: нарушения контракта поднимают NeuralContractError /
NeuralRuntimeUnavailableError -- никаких синтетических подмен.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.model_jobs import dependency_group_manifest, gpu_runtime_available
from apps.api.multivariate_contract import validate_regular_grid


NEURAL_CONTRACT_VERSION = "neural-contract-v1"
NEURAL_RUNTIME = "neuralforecast"

# Long format / панель
LONG_FORMAT_COLUMNS = ("unique_id", "ds", "y")
PANEL_MIN_SERIES = 2

# Бюджет обучения (NeuralForecast 3.x: только max_steps; max_epochs отказ)
NEURAL_MAX_STEPS_BOUND = 10_000
DEFAULT_NEURAL_PATIENCE = 0
NEURAL_MAX_PATIENCE_BOUND = 50
NEURAL_MAX_BATCH_SIZE_BOUND = 4096
SEED_UPPER_BOUND = 2**31 - 1

# Probabilistic losses / quantiles
DEFAULT_NEURAL_QUANTILE_LEVELS: tuple[float, ...] = (10.0, 50.0, 90.0)
NEURAL_ALLOWED_LOSSES: tuple[str, ...] = (
    "quantile", "mqloss", "mae", "mse", "huber",
)
NEURAL_PROBABILISTIC_LOSSES: tuple[str, ...] = ("quantile", "mqloss")

# Checkpoints
CHECKPOINT_MAX_BYTES = 512 * 1024 * 1024
CHECKPOINT_DIR_ENV = "CISSTAT_NEURAL_CHECKPOINT_DIR"
_CHECKPOINT_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class NeuralContractError(ValueError):
    """Вход или декларация нарушает нейро-контракт (fail-closed)."""


class NeuralRuntimeUnavailableError(RuntimeError):
    """Нейро-runtime недоступен (пакеты не установлены или GPU отсутствует)."""


def _assert_json_safe(value: Any, *, path: str = "metadata") -> None:
    """Рекурсивная проверка JSON-безопасности (pointer в Redis/session-JSON)."""
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not np.isfinite(value):
            raise NeuralContractError(
                f"{path}: нечисловое float-значение недопустимо в JSON"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NeuralContractError(f"{path}: ключи JSON обязаны быть str")
            _assert_json_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_json_safe(item, path=f"{path}[{i}]")
        return
    raise NeuralContractError(
        f"{path}: тип {type(value).__name__} недопустим в JSON-артефакте "
        "(байтовые payload живут в filesystem-чекпойнтах, не в Redis JSON)"
    )


# ── 1. Long-format unique_id / ds / y ─────────────────────────────────────

def to_long_format(
    frame: pd.DataFrame,
    *,
    value_column: str,
    time_column: Optional[str] = None,
    series_column: Optional[str] = None,
    keep_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Приводит платформенную таблицу к long-format unique_id/ds/y (+keep).

    Fail-closed: отсутствующие колонки, NaN/Inf в y и keep-колонках,
    дубликаты (unique_id, ds), не-датовая/не-целочисленная временная ось.
    Одна серия без series_column получает unique_id="series_0" (панель
    требует явного series_column -- числовые колонки одного объекта не
    выдаются за панель, честность DeepAR Task 142).
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise NeuralContractError("вход обязателен: непустой pandas DataFrame")
    if value_column not in frame.columns:
        raise NeuralContractError(f"колонка значения '{value_column}' отсутствует")
    if series_column is not None and series_column not in frame.columns:
        raise NeuralContractError(f"колонка серий '{series_column}' отсутствует")

    if time_column is not None:
        if time_column not in frame.columns:
            raise NeuralContractError(f"колонка времени '{time_column}' отсутствует")
        ds = pd.Series(frame[time_column]).reset_index(drop=True)
    else:
        ds = pd.Series(frame.index).reset_index(drop=True)

    if not (pd.api.types.is_datetime64_any_dtype(ds) or
            pd.api.types.is_integer_dtype(ds)):
        converted = pd.to_datetime(ds, errors="coerce")
        if converted.isna().any():
            raise NeuralContractError(
                "временная ось не распознана (datetime или целые); "
                "контракт не выполняет скрытую коэрцию"
            )
        ds = converted

    y = pd.to_numeric(pd.Series(frame[value_column]).reset_index(drop=True),
                      errors="coerce")
    if not np.isfinite(y.to_numpy(dtype=float)).all():
        raise NeuralContractError(
            "значения ряда содержат NaN/Inf; контракт не выполняет "
            "скрытую очистку -- сначала исправьте данные"
        )

    if series_column is None:
        unique_id = pd.Series(["series_0"] * len(frame), dtype=object)
    else:
        unique_id = pd.Series(frame[series_column]).reset_index(drop=True).astype(object)

    long = pd.DataFrame({
        "unique_id": unique_id,
        "ds": ds,
        "y": y.astype(float),
    })

    for column in keep_columns:
        if column not in frame.columns:
            raise NeuralContractError(f"заказанная exog-колонка '{column}' отсутствует")
        values = pd.Series(frame[column]).reset_index(drop=True)
        if values.isna().any():
            raise NeuralContractError(
                f"exog-колонка '{column}' содержит NaN"
            )
        long[column] = values

    duplicated = long.duplicated(["unique_id", "ds"], keep=False)
    if duplicated.any():
        raise NeuralContractError(
            f"повторяются точки (unique_id, ds): {int(duplicated.sum())} строк; "
            "панель требует уникальные серии на общей сетке"
        )
    return long.sort_values(["unique_id", "ds"]).reset_index(drop=True)


def validate_long_format(long_frame: pd.DataFrame) -> dict[str, Any]:
    """Fail-closed сводка long-format: колонки, per-series регулярная сетка."""
    missing = [c for c in LONG_FORMAT_COLUMNS if c not in long_frame.columns]
    if missing:
        raise NeuralContractError(
            f"long-format требует колонки {LONG_FORMAT_COLUMNS}; отсутствуют: {missing}"
        )
    if long_frame.empty:
        raise NeuralContractError("long-format пуст")

    for series_id, group in long_frame.groupby("unique_id", sort=True):
        ds = group["ds"].reset_index(drop=True)
        if ds.isna().any():
            raise NeuralContractError(f"серия '{series_id}': NaT/NaN во временной оси")
        if pd.api.types.is_datetime64_any_dtype(ds):
            try:
                grid = validate_regular_grid(
                    [pd.Timestamp(v).isoformat() for v in ds]
                )
            except Exception as exc:  # MultivariateContractError -- честный re-raise
                raise NeuralContractError(
                    f"серия '{series_id}': {exc}"
                ) from exc
        else:
            numeric = pd.to_numeric(ds, errors="coerce")
            if numeric.isna().any():
                raise NeuralContractError(
                    f"серия '{series_id}': нечисловая временная ось"
                )
            diffs = numeric.diff().dropna()
            if (diffs <= 0).any():
                raise NeuralContractError(
                    f"серия '{series_id}': временная ось не строго монотонна"
                )
            if diffs.nunique() > 1:
                raise NeuralContractError(
                    f"серия '{series_id}': временная сетка нерегулярна; "
                    "нейро-runtime предполагает равноотстоящую сетку"
                )
            grid = {"frequency": f"int_step_{int(diffs.iloc[0])}"}

    return {
        "n_series": int(long_frame["unique_id"].nunique()),
        "n_observations": int(len(long_frame)),
        "frequency": str(grid.get("frequency", "")),
    }


# ── 2. Historic / future / static exogenous contract ─────────────────────

@dataclass(frozen=True)
class NeuralExogenousPlan:
    """Явная классификация exog-колонок (roles объявляет вызов, не угадывание)."""

    futr_exog_list: tuple[str, ...] = ()
    hist_exog_list: tuple[str, ...] = ()
    stat_exog_list: tuple[str, ...] = ()
    signature: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "futr": list(self.futr_exog_list),
            "hist": list(self.hist_exog_list),
            "stat": list(self.stat_exog_list),
            "signature": self.signature,
        }


def _plan_signature(futr: Sequence[str], hist: Sequence[str],
                    stat: Sequence[str]) -> str:
    payload = json.dumps(
        {"futr": list(futr), "hist": list(hist), "stat": list(stat)},
        sort_keys=True, ensure_ascii=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def build_exogenous_plan(
    long_frame: pd.DataFrame,
    *,
    futr: Sequence[str] = (),
    hist: Sequence[str] = (),
    stat: Sequence[str] = (),
) -> NeuralExogenousPlan:
    """Строит и валидирует exogenous-план на train-длинном формате.

    Fail-closed: неизвестные колонки, NaN/Inf в объявленных колонках,
    non-константный static per unique_id, колонка в двух ролях.
    """
    futr_t, hist_t, stat_t = tuple(futr), tuple(hist), tuple(stat)
    all_declared = (*futr_t, *hist_t, *stat_t)
    if len(set(all_declared)) != len(all_declared):
        overlap = sorted({
            c for c in all_declared if all_declared.count(c) > 1
        })
        raise NeuralContractError(
            f"колонки объявлены в нескольких ролях: {overlap}"
        )
    for column in (*futr_t, *hist_t):
        if column not in long_frame.columns:
            raise NeuralContractError(f"exog-колонка '{column}' отсутствует")
        values = pd.to_numeric(
            long_frame[column], errors="coerce",
        ).to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise NeuralContractError(
                f"exog-колонка '{column}' содержит NaN/Inf/нечисловые "
                "значения на train-срезе (hist/futr обязаны быть числовыми)"
            )

    for column in stat_t:
        if column not in long_frame.columns:
            raise NeuralContractError(f"exog-колонка '{column}' отсутствует")
        counts = long_frame.groupby("unique_id")[column].nunique(dropna=False)
        if (counts > 1).any():
            offenders = sorted(counts[counts > 1].index.tolist())
            raise NeuralContractError(
                f"static-колонка '{column}' не константна внутри серий: {offenders}"
            )

    return NeuralExogenousPlan(
        futr_exog_list=futr_t,
        hist_exog_list=hist_t,
        stat_exog_list=stat_t,
        signature=_plan_signature(futr_t, hist_t, stat_t),
    )


def build_static_frame(
    long_frame: pd.DataFrame, plan: NeuralExogenousPlan,
) -> Optional[pd.DataFrame]:
    """Одна строка на unique_id с static-колонками (None, если статик нет)."""
    if not plan.stat_exog_list:
        return None
    columns = ["unique_id", *plan.stat_exog_list]
    static = long_frame[columns].groupby("unique_id", sort=True).first()
    return static.reset_index()


def validate_future_exogenous_frame(
    plan: NeuralExogenousPlan,
    future_frame: Optional[pd.DataFrame],
    *,
    n_series: int,
    horizon: int,
) -> None:
    """futr-план требует полного покрытия горизонта для каждой серии."""
    if not plan.futr_exog_list:
        return
    if future_frame is None:
        raise NeuralContractError(
            "futr-exogenous план объявлен, но future-frame отсутствует: "
            "NeuralForecast требует futr_df на predict при futr_exog_list"
        )
    required_rows = int(n_series) * int(horizon)
    if len(future_frame) != required_rows:
        raise NeuralContractError(
            f"future-frame покрывает {len(future_frame)} строк вместо "
            f"{required_rows} (n_series * horizon); покрытие горизонта неполное"
        )
    for column in plan.futr_exog_list:
        if column not in future_frame.columns:
            raise NeuralContractError(
                f"future-frame не содержит futr-колонку '{column}'"
            )
        values = pd.to_numeric(future_frame[column], errors="coerce")
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise NeuralContractError(
                f"future-frame: futr-колонка '{column}' содержит NaN/Inf"
            )
    if "unique_id" in future_frame.columns:
        per_series = future_frame.groupby("unique_id").size()
        if (per_series != int(horizon)).any():
            raise NeuralContractError(
                "future-frame: не у каждой серии ровно horizon строк"
            )


# ── 5. NeuralTrainingConfig: seed, early stopping, max steps ─────────────

@dataclass(frozen=True)
class NeuralTrainingConfig:
    """Bounded-конфиг унифицированного нейро-обучения (единый бюджет max_steps)."""

    seed: int
    max_steps: Optional[int] = None
    early_stopping_patience: int = DEFAULT_NEURAL_PATIENCE
    val_size: int = 0
    batch_size: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or not 0 <= self.seed <= SEED_UPPER_BOUND:
            raise NeuralContractError(
                f"seed обязан быть целым в [0, {SEED_UPPER_BOUND}], получено {self.seed}"
            )
        if self.max_steps is None:
            raise NeuralContractError(
                "бюджет обучения обязан быть объявлен: max_steps "
                f"(NeuralForecast 3.x: max_epochs deprecated); "
                "унификация = один бюджетный рычаг"
            )
        if not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= NEURAL_MAX_STEPS_BOUND:
            raise NeuralContractError(
                f"max_steps обязан быть целым в [1, {NEURAL_MAX_STEPS_BOUND}] "
                f"(единый бюджет NeuralForecast 3.x; max_epochs deprecated), "
                f"получено {self.max_steps}"
            )
        if not isinstance(self.early_stopping_patience, int) or not (
            0 <= self.early_stopping_patience <= NEURAL_MAX_PATIENCE_BOUND
        ):
            raise NeuralContractError(
                f"early_stopping_patience обязан быть в "
                f"[0, {NEURAL_MAX_PATIENCE_BOUND}] (0 = отключён), "
                f"получено {self.early_stopping_patience}"
            )
        if self.early_stopping_patience > 0 and self.val_size <= 0:
            raise NeuralContractError(
                "early stopping требует val_size > 0: валидационный срез "
                "обязателен для честной остановки"
            )
        if self.val_size < 0:
            raise NeuralContractError("val_size обязан быть >= 0")
        if self.batch_size is not None and not (
            isinstance(self.batch_size, int) and 1 <= self.batch_size <= NEURAL_MAX_BATCH_SIZE_BOUND
        ):
            raise NeuralContractError(
                f"batch_size обязан быть None или в [1, {NEURAL_MAX_BATCH_SIZE_BOUND}]"
            )

    @property
    def early_stopping_enabled(self) -> bool:
        return self.early_stopping_patience > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "max_steps": self.max_steps,
            "early_stopping_patience": self.early_stopping_patience,
            "val_size": self.val_size,
            "batch_size": self.batch_size,
        }


def fold_seed(seed: int, *, fold_index: int, step: int = 0) -> int:
    """Детерминированный per-fold/per-step seed (стабильный, без случайности)."""
    if not isinstance(seed, int) or not 0 <= seed <= SEED_UPPER_BOUND:
        raise NeuralContractError(f"seed вне [0, {SEED_UPPER_BOUND}]")
    if fold_index < 0 or step < 0:
        raise NeuralContractError("fold_index/step обязаны быть >= 0")
    mixed = (seed * 1_000_003 + fold_index * 7_919 + step * 104_729 + 137)
    return int(mixed % (SEED_UPPER_BOUND + 1))


# ── 6. Probabilistic losses и quantiles ──────────────────────────────────

@dataclass(frozen=True)
class NeuralIntervalPlan:
    """Декларация интервальных выходов нейро-прогноза (quantile/conformal)."""

    alpha: float
    levels: tuple[float, ...] = DEFAULT_NEURAL_QUANTILE_LEVELS
    median_level: float = 50.0
    method: str = "neural_quantile_outputs"

    def as_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "levels": list(self.levels),
            "median_level": self.median_level,
            "method": self.method,
        }


def interval_levels_for_alpha(alpha: float) -> NeuralIntervalPlan:
    """Симметричные уровни (в процентах) из двусторонней alpha, включая медиану."""
    if not isinstance(alpha, (int, float)) or not 0.0 < float(alpha) < 1.0:
        raise NeuralContractError(
            f"alpha обязана быть в (0, 1), получено {alpha!r}"
        )
    alpha = float(alpha)
    lo = round(100.0 * alpha / 2.0, 6)
    hi = round(100.0 * (1.0 - alpha / 2.0), 6)
    return NeuralIntervalPlan(alpha=alpha, levels=(lo, 50.0, hi))


def resolve_probabilistic_loss(
    loss: str, *, levels: Optional[Sequence[float]] = None,
) -> str:
    """Whitelist функций потерь; probabilistic-функции требуют уровней."""
    if not isinstance(loss, str) or loss not in NEURAL_ALLOWED_LOSSES:
        raise NeuralContractError(
            f"loss '{loss}' вне whitelist {NEURAL_ALLOWED_LOSSES}"
        )
    if loss in NEURAL_PROBABILISTIC_LOSSES:
        if not levels:
            raise NeuralContractError(
                f"probabilistic loss '{loss}' требует уровней quantile "
                "(levels); объявите interval-план контракта"
            )
        for level in levels:
            if not 0.0 < float(level) < 100.0:
                raise NeuralContractError(
                    f"уровень quantile {level!r} вне (0, 100)"
                )
    return loss


# ── 3. CPU/GPU worker capabilities ───────────────────────────────────────

def neural_worker_capabilities() -> dict[str, Any]:
    """Честные возможности воркера БЕЗ eager-импорта torch (сигнал деплоя)."""
    gpu = gpu_runtime_available()
    manifest = dependency_group_manifest()["neural"]
    return {
        "gpu_available": bool(gpu),
        "device": "cuda" if gpu else "cpu",
        "dependency_group": "neural",
        "install_extra": manifest["install_extra"],
        "packages": list(manifest["packages"]),
        "contract_version": NEURAL_CONTRACT_VERSION,
    }


def resolve_neural_device(*, requires_gpu: bool) -> str:
    """GPU-обязательная модель без GPU-сигнала -- честный отказ (правило D06)."""
    gpu = gpu_runtime_available()
    if requires_gpu and not gpu:
        raise NeuralRuntimeUnavailableError(
            "модель нейро-семейства требует GPU (requires_gpu=true), "
            "но деплой-сигнал CISSTAT_GPU_AVAILABLE не установлен; "
            "тихое CPU-понижение запрещено контрактом"
        )
    return "cuda" if gpu else "cpu"


# ── 4+7. Checkpoints вне Redis JSON + продолжение после рестарта ─────────

@dataclass(frozen=True)
class NeuralResumeState:
    """Восстановленное после рестарта состояние нейро-job."""

    checkpoint_path: str
    contract_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


def checkpoint_policy() -> dict[str, Any]:
    """Декларация политики чекпойнтов (попадает в cohort-контракт/job)."""
    return {
        "backend": "filesystem",
        "stored_in_redis_json": False,
        "max_bytes": CHECKPOINT_MAX_BYTES,
        "root_env": CHECKPOINT_DIR_ENV,
        "contract_version": NEURAL_CONTRACT_VERSION,
    }


def checkpoint_pointer_is_json_safe(pointer: Mapping[str, Any]) -> bool:
    """True, если pointer целиком JSON-сериализуем (требование Redis-записи)."""
    try:
        _assert_json_safe(dict(pointer), path="pointer")
        return True
    except NeuralContractError:
        return False


def _resolve_checkpoint_root(explicit_root: Optional[Path] = None) -> Path:
    if explicit_root is not None:
        return Path(explicit_root)
    env_root = os.getenv(CHECKPOINT_DIR_ENV, "").strip()
    if env_root:
        return Path(env_root)
    return Path.cwd() / "data" / "neural_checkpoints"


class NeuralCheckpointStore:
    """Filesystem-хранилище чекпойнтов нейро-jobs (вне Redis JSON).

    Pointer (маленький JSON-словарь) хранится в job-записи; байты
    чекпойнта -- только на диске.  Целостность -- sha256-анти-тампер.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = _resolve_checkpoint_root(root)

    def checkpoint_path(self, job_id: str) -> Path:
        self._validate_job_id(job_id)
        return self.root / f"{job_id}.ckpt"

    def _validate_job_id(self, job_id: str) -> None:
        if not isinstance(job_id, str) or not _CHECKPOINT_JOB_ID_RE.match(job_id):
            raise NeuralContractError(
                "job_id обязан соответствовать ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ "
                "(защита от path traversal); получено "
                f"{job_id!r:.64}"
            )

    def _manifest_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def has_checkpoint(self, job_id: str) -> bool:
        self._validate_job_id(job_id)
        return self.checkpoint_path(job_id).exists()

    def save_checkpoint(
        self, job_id: str, payload: bytes, *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Пишет байты + манифест, возвращает JSON-safe pointer для job-записи."""
        self._validate_job_id(job_id)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            raise NeuralContractError("payload чекпойнта пуст -- сохранять нечего")
        if len(payload) > CHECKPOINT_MAX_BYTES:
            raise NeuralContractError(
                f"payload {len(payload)} байт превышает потолок "
                f"CHECKPOINT_MAX_BYTES={CHECKPOINT_MAX_BYTES}"
            )
        meta = dict(metadata or {})
        _assert_json_safe(meta, path="metadata")

        self.root.mkdir(parents=True, exist_ok=True)
        path = self.checkpoint_path(job_id)
        digest = sha256(payload).hexdigest()
        path.write_bytes(payload)
        manifest = {
            "contract_version": NEURAL_CONTRACT_VERSION,
            "job_id": job_id,
            "bytes": len(payload),
            "sha256": digest,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": meta,
        }
        self._manifest_path(job_id).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "backend": "filesystem",
            "checkpoint_id": job_id,
            "path": str(path),
            "bytes": len(payload),
            "sha256": digest,
            "contract_version": NEURAL_CONTRACT_VERSION,
            "metadata": meta,
        }

    def load_checkpoint(
        self, job_id: str, pointer: Mapping[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        """Читает чекпойнт по pointer с sha256-верификацией (fail-closed)."""
        self._validate_job_id(job_id)
        if str(pointer.get("contract_version")) != NEURAL_CONTRACT_VERSION:
            raise NeuralContractError(
                f"contract_version pointer "
                f"({pointer.get('contract_version')!r}) не совпадает с "
                f"{NEURAL_CONTRACT_VERSION}: состояние другого контракта"
            )
        path = Path(str(pointer.get("path", "")))
        if not path.exists():
            raise NeuralContractError(
                f"checkpoint-файл отсутствует на диске: {path}; "
                "продолжение после рестарта невозможно, честный отказ"
            )
        payload = path.read_bytes()
        if pointer.get("bytes") is not None and len(payload) != int(pointer["bytes"]):
            raise NeuralContractError(
                f"размер чекпойнта {len(payload)} не совпадает с pointer "
                f"({pointer['bytes']})"
            )
        digest = sha256(payload).hexdigest()
        if digest != pointer.get("sha256"):
            raise NeuralContractError(
                "sha256 чекпойнта не совпадает с pointer: файл повреждён "
                "или подменён (анти-тампер, прецедент VolatilityTarget)"
            )
        manifest_path = self._manifest_path(job_id)
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = {}
        return payload, manifest

    def delete_checkpoint(self, job_id: str) -> None:
        self._validate_job_id(job_id)
        for path in (self.checkpoint_path(job_id), self._manifest_path(job_id)):
            if path.exists():
                path.unlink()


def restore_resume_state(
    job_id: str, pointer: Mapping[str, Any],
) -> NeuralResumeState:
    """Продолжение job после рестарта: верифицированное состояние по pointer."""
    store = NeuralCheckpointStore()
    _, manifest = store.load_checkpoint(job_id, pointer)
    # Источник истины metadata -- pointer (живёт в job-записи); манифест
    # на диске -- дубликат для аудита.
    metadata = pointer.get("metadata") or manifest.get("metadata") or {}
    return NeuralResumeState(
        checkpoint_path=str(pointer["path"]),
        contract_version=NEURAL_CONTRACT_VERSION,
        metadata=dict(metadata),
    )


# ── Cohort contract: декларация нейро-cohort для движка ──────────────────

def neural_cohort_contract(
    *,
    fingerprint: str,
    n_series: int,
    min_series: int = 1,
    exogenous: NeuralExogenousPlan,
    interval: NeuralIntervalPlan,
    loss: str,
    config: NeuralTrainingConfig,
    requires_gpu: bool = False,
    input_kind: Optional[str] = None,
) -> dict[str, Any]:
    """Декларация нейро-cohort (прецедент volatility_cohort_contract Task 134).

    Честность панели: n_series < min_series -- отказ (числовые колонки
    одного объекта НЕ выдаются за панель, DeepAR Task 142); input_kind
    выводится из n_series и опционально перекрёстно сверяется.
    """
    if not isinstance(n_series, int) or n_series < 1:
        raise NeuralContractError(f"n_series обязан быть >= 1, получено {n_series}")
    if not isinstance(min_series, int) or min_series < 1:
        raise NeuralContractError(f"min_series обязан быть >= 1, получено {min_series}")
    if n_series < min_series:
        raise NeuralContractError(
            f"модель требует панель из min_series={min_series} серий, "
            f"доступно n_series={n_series}; числовые колонки одного объекта "
            "не выдаются за панель (честность DeepAR)"
        )

    derived_kind = "panel" if n_series >= PANEL_MIN_SERIES else "univariate"
    if input_kind is not None and input_kind != derived_kind:
        raise NeuralContractError(
            f"объявленный input_kind={input_kind!r} противоречит данным "
            f"(n_series={n_series} -> {derived_kind})"
        )

    resolved_loss = resolve_probabilistic_loss(loss, levels=interval.levels)
    device = resolve_neural_device(requires_gpu=requires_gpu)

    return {
        "contract_version": NEURAL_CONTRACT_VERSION,
        "objective": "level_forecast",
        "dependency_group": "neural",
        "runtime": NEURAL_RUNTIME,
        "fingerprint": fingerprint,
        "input_kind": derived_kind,
        "panel": derived_kind == "panel",
        "n_series": n_series,
        "min_series": min_series,
        "loss": resolved_loss,
        "feature_contract": exogenous.as_dict(),
        "interval": interval.as_dict(),
        "training": config.as_dict(),
        "device": device,
        "checkpoint_policy": checkpoint_policy(),
    }
