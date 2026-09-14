# apps/api/final_fit.py
"""Финальный рефит модели на всей доступной истории для реального прогноза
вперёд -- НЕ бэктест-фолд (spec_forecasting2.md §3).

После кросс-валидации модель переобучается на всех доступных данных перед
реальным прогнозом (Hyndman & Athanasopoulos, FPP3, гл. 5.9), с уже
подобранными (замороженными в Model Card) гиперпараметрами, без повторного
подбора.

Переиспользует ту же трансформационную логику, что и fold-local препроцессор
(apps/api/fold_preprocessing.py): _resolve_chain, _make_scaler,
_stationarity_forward/_inverse_stationarity, apply_variance_transform,
apply_smoothing_series -- применённую ОДИН раз к полному ряду, а не по фолдам.

Ключевое требование §3: обратная трансформация границ интервала нелинейна
(log_difference, seasonal_difference...) -- КАЖДАЯ граница (нижняя/точка/
верхняя) инвертируется отдельным вызовом restore() с одним и тем же
зафиксированным состоянием; для мультипликативных/логарифмических
трансформаций это даёт корректно асимметричный интервал в исходной шкале.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from app.core.passport import prepare_passport_series
from app.preprocessing.smoothing import CAUSAL_METHODS, apply_smoothing_series
from app.preprocessing.stationarity import apply_stationarity_series
from app.preprocessing.transforms import (
    apply_variance_transform,
    inverse_variance_transform,
)
from apps.api.fold_preprocessing import (
    _inverse_stationarity,
    _make_scaler,
    _resolve_chain,
    _transform_kind,
)
from sklearn.preprocessing import StandardScaler  # noqa: F401  (экспорт типа)


class FinalFitError(ValueError):
    """Честный отказ контура финального рефита (маппится в 422)."""


@dataclass
class FinalFitResult:
    """Результат финального рефита: трансформированная история + обратимый
    рецепт restore() для точечного прогноза и КАЖДОЙ границы интервала."""

    source_column: str
    target_column: str
    source_values: np.ndarray            # исходный ряд (source column), original scale
    history_labels: list[str]            # ISO-метки полной истории (len == source_values)
    model_train: np.ndarray              # ряд после forward-цепочки (+scaler) -- вход модели
    model_train_labels: list[str]        # метки, выровненные с model_train (хвост history_labels)
    transform_states: list[dict[str, Any]]
    scaler: Any                          # sklearn-скейлер или None
    reversible: bool
    signature: str
    summary: dict[str, Any]

    def restore(self, values: Sequence[float]) -> np.ndarray:
        """Обратная трансформация (transformed -> original scale).

        Вызывается ПО ОТДЕЛЬНОСТИ для точки и каждой границы интервала
        (§3); вызовы stateless относительно друг друга.
        """
        if not self.reversible:
            raise FinalFitError(
                "Цепочка target-препроцессинга необратима (inverse_supported=False, "
                "например сглаживание): прогноз в исходной шкале невозможен; "
                "честный отказ вместо прогноза в transformed-шкале"
            )
        restored = np.asarray(values, dtype=float)
        if self.scaler is not None:
            restored = self.scaler.inverse_transform(restored.reshape(-1, 1)).ravel()
        for state in reversed(self.transform_states):
            kind = state["kind"]
            if kind == "variance":
                restored = inverse_variance_transform(
                    restored, state["method"], state.get("lambda_value"),
                )
            elif kind == "stationarity":
                restored = _inverse_stationarity(
                    restored, state["method"], state["input_train"], state,
                )
            else:
                raise FinalFitError(
                    f"Неизвестный вид трансформации в цепочке финального рефита: {kind}"
                )
        if not np.isfinite(restored).all():
            raise FinalFitError("Inverse preprocessing породил NaN/Inf")
        return restored


def build_final_fit(
    dataframe: pd.DataFrame,
    *,
    target_column: str,
    date_column: str,
    transformations: Mapping[str, Mapping[str, Any]],
    scaling_recipe: Mapping[str, Any],
) -> FinalFitResult:
    """Собрать финальный рефит: forward-цепочка на ПОЛНОЙ истории + обратимый рецепт.

    Источник цепочки, порядок и параметры трансформаций -- те же, что
    использовал fold-local препроцессор бэктеста той же карты
    (session.preprocessing_transformations / preprocessing_scaling_recipe).
    """
    source_column, chain = _resolve_chain(transformations, target_column)
    source_series = prepare_passport_series(
        dataframe, source_column, date_column, min_points=2,
    )
    values = source_series.to_numpy(dtype=float)

    current = values.copy()
    states: list[dict[str, Any]] = []
    for metadata in chain:
        kind = _transform_kind(metadata)
        method = str(metadata.get("method") or "")
        input_full = current.copy()
        if kind == "variance":
            # Fixed-lambda фиксируется, оценённая -- переоценивается на полной
            # истории (для финального рефита полная история и есть train-срез;
            # та же семантика, что у fold-препроцессора на train-фолде).
            requested_lambda = (
                metadata.get("lambda_value")
                if metadata.get("lambda_policy") == "fixed"
                else None
            )
            current, fitted_lambda = apply_variance_transform(
                current, method, requested_lambda,
            )
            states.append({
                "kind": kind, "method": method, "lambda_value": fitted_lambda,
                "lambda_policy": metadata.get("lambda_policy"),
                "input_train": input_full,
            })
        elif kind == "stationarity":
            period = int(metadata.get("seasonal_period") or 12)
            current, fitted = apply_stationarity_series(
                current, method, seasonal_period=period,
            )
            states.append({
                "kind": kind, "method": method, **fitted,
                "input_train": input_full,
            })
        elif kind == "smoothing":
            # Та же каузальная дисциплина, что у production backtest
            # (FoldLocalTargetPreprocessor): некаузальные сглаживатели
            # (LOWESS/Savitzky-Golay) не проходят в исполнение вообще.
            if method not in CAUSAL_METHODS or metadata.get("causal") is False:
                raise FinalFitError(
                    f"Некаузальный target smoother '{method}' неприменим в "
                    "финальном рефите"
                )
            parameters = dict(metadata.get("parameters") or {})
            if method == "ema":
                parameters = {"span": int(parameters.get("span", 7))}
            else:
                parameters = {"window": int(parameters.get("window", 7))}
            current, _ = apply_smoothing_series(current, method, **parameters)
            states.append({
                "kind": kind, "method": method, "input_train": input_full,
            })
        else:
            raise FinalFitError(
                f"Неизвестное preprocessing-преобразование target: {method or kind}"
            )

    target_scaled = target_column in set(scaling_recipe.get("columns") or [])
    scaler = None
    if target_scaled:
        if scaling_recipe.get("fit_policy") != "per_train_fold":
            raise FinalFitError(
                "Target scaler должен иметь fit_policy=per_train_fold"
            )
        scaler = _make_scaler(scaling_recipe, len(current))
        current = scaler.fit_transform(current.reshape(-1, 1)).ravel()

    reversible = all(
        bool(item.get("inverse_supported", True)) for item in chain
    )
    methods = [str(item.get("method") or "unknown") for item in chain]
    contract = {
        "fit_policy": "full_history",
        "source_column": source_column,
        "target_column": target_column,
        "transformations": [
            {
                "kind": _transform_kind(item),
                "method": item.get("method"),
                "parameters": item.get("parameters"),
                "seasonal_period": item.get("seasonal_period"),
                "lambda_policy": item.get("lambda_policy"),
                "fixed_lambda": (
                    item.get("lambda_value")
                    if item.get("lambda_policy") == "fixed" else None
                ),
            }
            for item in chain
        ],
        "target_scaling": {
            "method": scaling_recipe.get("method"),
            "parameters": scaling_recipe.get("parameters"),
        } if target_scaled else None,
    }
    signature = sha256(
        json.dumps(
            contract, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    labels = [value.isoformat() for value in source_series.index]
    summary = {
        "fit_policy": "full_history",
        "source_column": source_column,
        "target_column": target_column,
        "transformations": methods,
        "target_scaling": scaling_recipe.get("method") if target_scaled else None,
        "evaluation_scale": source_column if reversible else target_column,
        "inverse_transform_applied": reversible,
        "signature": signature,
    }
    return FinalFitResult(
        source_column=source_column,
        target_column=target_column,
        source_values=values,
        history_labels=labels,
        model_train=np.asarray(current, dtype=float),
        model_train_labels=labels[len(labels) - len(current):],
        transform_states=states,
        scaler=scaler,
        reversible=reversible,
        signature=signature,
        summary=summary,
    )
