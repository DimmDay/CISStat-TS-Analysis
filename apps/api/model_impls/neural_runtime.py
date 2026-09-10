# apps/api/model_impls/neural_runtime.py
"""
Единый NeuralForecast-runtime пяти нейро-моделей платформы (Task 137,
family=neural; потребители -- вертикальные срезы Tasks 138-142).

Постановка docs/modeling_task_list.md::Task 137 -- унификация LSTM/GRU,
N-BEATS, N-HiTS, TFT и DeepAR на NeuralForecast вместо смеси
Darts/GluonTS/PyTorch Forecasting.  Этот модуль -- ЕДИНСТВЕННАЯ точка
импорта torch/neuralforecast на платформе (ленивая, fail-closed);
контракт живёт в apps/api/neural_contract.py (data-plane без тяжёлых
импортов), реестровые записи Tasks 138-142 будут использовать
``neuralforecast_runtime_available`` как честный runtime_available.

Ключевые решения по эмпирике neuralforecast 3.2.2 (проб
scripts/task137_neural_api_probe.py):

1. **Единый бюджет max_steps**: BaseModel neuralforecast 3.x fail-closed
   отвергает max_epochs ("max_epochs is deprecated, use max_steps") --
   контракт NeuralTrainingConfig фиксирует один бюджетный рычаг.
2. **Явное устройство**: BaseModel молча ставит accelerator="gpu" по
   умолчанию -- бюджет-мэппинг обязан задать accelerator из
   resolve_neural_device (честные CPU/GPU capabilities, правило D06).
3. **Квантильные выходы point-loss моделей** -- conformal-путь:
   fit(prediction_intervals=PredictionIntervals()) + predict(level=[...])
   -> колонки <Model>-lo-<level>/<Model>-hi-<level>; probabilistic
   потери (QuantileLoss/MQLoss) дают квантили без conformal.
4. **Детерминизм**: seed_neural_runtime(random/numpy/torch) обязан
   выполняться ДО конструирования модели; train_and_forecast принимает
   model_factory (а не готовую модель) и сеет fold_seed контракта перед
   конструированием -- одинаковый seed даёт бит-в-бит одинаковый прогноз
   (связано тестом).

Fail-closed: нейро-runtime недоступен (пакеты не установлены) --
NeuralRuntimeUnavailableError с установочной подсказкой; runtime_available
реестра v2 честно отфильтрует модели вместо фиктивных метрик.
"""
from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.neural_contract import (
    LONG_FORMAT_COLUMNS,
    NeuralContractError,
    NeuralRuntimeUnavailableError,
    NeuralTrainingConfig,
    fold_seed,
)


NEURALFORECAST_VERSION_BOUND = "neuralforecast>=3.0,<4.0"

_INSTALL_HINT = (
    "нейро-runtime не установлен; deploy-манифест: apps/api/requirements-neural.txt "
    f"({NEURALFORECAST_VERSION_BOUND}, dependency_group='neural', "
    "install_extra='neural')"
)


def neuralforecast_runtime_available() -> bool:
    """Честный import-проб без сайд-эффектов (питает runtime_available v2)."""
    try:
        return find_spec("neuralforecast") is not None
    except (ImportError, ValueError):
        return False


def require_neuralforecast() -> Any:
    """Ленивый импорт neuralforecast; недоступен -- fail-closed с подсказкой."""
    try:
        import neuralforecast as _neuralforecast_module
    except ImportError as exc:  # pragma: no cover -- зависит от окружения
        raise NeuralContractError(
            f"neuralforecast недоступен: {exc}; {_INSTALL_HINT}"
        ) from exc
    return _neuralforecast_module


def seed_neural_runtime(seed: int) -> dict[str, Any]:
    """Детерминизм random/numpy/torch (+cuda при наличии) до конструирования."""
    import random as _random

    if not isinstance(seed, int) or seed < 0:
        raise NeuralContractError(f"seed обязан быть целым >= 0, получено {seed!r}")
    _random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    seeded: dict[str, Any] = {"random": True, "numpy": True, "torch": False,
                              "cuda": False}
    try:
        import torch
    except ImportError:
        return seeded
    torch.manual_seed(seed)
    seeded["torch"] = True
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        seeded["cuda"] = True
    return seeded


def neural_model_budget_kwargs(
    config: NeuralTrainingConfig, *, device: str = "cpu",
) -> dict[str, Any]:
    """Маппинг NeuralTrainingConfig -> kwargs конструктора нейро-модели.

    Единая точка бюджетной конвенции пяти моделей: max_steps, явный
    accelerator, отключённый прогресс-бар, early-stop patience.
    """
    if device not in {"cpu", "cuda"}:
        raise NeuralContractError(f"устройство '{device}' вне {{cpu, cuda}}")
    patience = (
        config.early_stopping_patience if config.early_stopping_enabled else -1
    )
    kwargs: dict[str, Any] = {
        "max_steps": int(config.max_steps),
        "accelerator": device,
        "enable_progress_bar": False,
        "early_stop_patience_steps": int(patience),
    }
    if config.batch_size is not None:
        kwargs["batch_size"] = int(config.batch_size)
    return kwargs


def train_and_forecast(
    *,
    model_factory: Callable[[Mapping[str, Any]], Any],
    freq: str,
    train_long: pd.DataFrame,
    horizon: int,
    config: NeuralTrainingConfig,
    futr_df: Optional[pd.DataFrame] = None,
    static_df: Optional[pd.DataFrame] = None,
    levels: Sequence[float] = (),
    fold_index: int = 0,
) -> pd.DataFrame:
    """Единый fit/predict-цикл NeuralForecast для Tasks 138-142.

    ``model_factory(budget_kwargs)`` конструирует модель ПОСЛЕ сеяния
    fold_seed (детерминизм бит-в-бит).  ``levels`` -- проценты интервалов
    (например (10.0, 90.0) из NeuralIntervalPlan контракта): включают
    conformal-режим fit(prediction_intervals=...).  ``futr_df`` обязателен,
    если у модели futr_exog_list (контракт валидирует покрытие заранее);
    ``static_df`` -- одна строка на unique_id.

    Fail-closed: пустой/неколонный train, пустой horizon.
    """
    if not isinstance(train_long, pd.DataFrame) or train_long.empty:
        raise NeuralContractError("train_long обязан быть непустым long-format DataFrame")
    missing = [c for c in LONG_FORMAT_COLUMNS if c not in train_long.columns]
    if missing:
        raise NeuralContractError(
            f"train_long не содержит колонки long-format: {missing}"
        )
    if not isinstance(horizon, int) or horizon < 1:
        raise NeuralContractError(f"horizon обязан быть целым >= 1, получено {horizon!r}")

    nf_module = require_neuralforecast()
    NeuralForecast = nf_module.NeuralForecast

    seed = fold_seed(config.seed, fold_index=fold_index)
    seed_neural_runtime(seed)

    budget = neural_model_budget_kwargs(config, device="cpu")
    model = model_factory(dict(budget))

    nf = NeuralForecast(models=[model], freq=freq)
    fit_kwargs: dict[str, Any] = {"df": train_long}
    if static_df is not None:
        fit_kwargs["static_df"] = static_df
    if config.early_stopping_enabled:
        fit_kwargs["val_size"] = int(config.val_size)
    if levels:
        from neuralforecast.utils import PredictionIntervals
        fit_kwargs["prediction_intervals"] = PredictionIntervals()
    nf.fit(**fit_kwargs)

    predict_kwargs: dict[str, Any] = {}
    if futr_df is not None:
        predict_kwargs["futr_df"] = futr_df
    if levels:
        predict_kwargs["level"] = [float(level) for level in levels]
    preds = nf.predict(**predict_kwargs)

    if not isinstance(preds, pd.DataFrame) or preds.empty:
        raise NeuralContractError(
            "NeuralForecast вернул пустой прогноз -- fold отклоняется "
            "(никаких синтетических подмен)"
        )
    return preds.reset_index(drop=True)
