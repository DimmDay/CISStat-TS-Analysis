"""Typed execution boundary shared by every production Modeling adapter.

The registry is intentionally independent from HTTP/session code.  A model
receives train-only targets plus explicitly separated known-future context and
returns a validated forecast.  Future classical, multivariate, volatility, ML
and neural adapters can therefore join the same backtest/tuning engine without
creating another dispatch table or gaining accidental access to holdout facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from importlib import metadata, util
import json
import platform
from typing import Any, Callable, Literal, Mapping, Sequence

import numpy as np


MODEL_EXECUTION_CONTRACT_VERSION = "model-execution-v2"

ExecutionAction = Literal["backtest", "tune", "diagnostics"]
ModelObjective = Literal["level_forecast", "multivariate", "volatility"]
ExecutionInputKind = Literal[
    "univariate", "supervised", "multivariate", "panel",
]
ExecutionOutputKind = Literal["point", "distribution", "volatility"]
GpuCapability = Literal["unsupported", "optional", "required"]


class ModelExecutionContractError(ValueError):
    """An adapter request/result violates the leakage-safe v2 contract."""


@dataclass(frozen=True)
class ModelResourceCapabilities:
    """Minimum execution resources declared before a job is scheduled."""

    cpu: Literal["required", "optional"] = "required"
    gpu: GpuCapability = "unsupported"
    memory_class: Literal["low", "standard", "high"] = "low"
    supports_parallel_folds: bool = False


@dataclass(frozen=True)
class ModelLifecycleCapabilities:
    """Operations backed by real code for one registered adapter."""

    fit: bool
    predict: bool
    tuning: bool
    diagnostics: bool


def _probe_dependency(package_name: str) -> dict[str, Any]:
    """Inspect a package only when runtime readiness/lineage is requested."""
    import_name = package_name.replace("-", "_")
    try:
        import_available = util.find_spec(import_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        import_available = False
    installed_version = "not-installed"
    if import_available:
        try:
            installed_version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            installed_version = "unknown"
    return {
        "package": package_name,
        "import_name": import_name,
        "available": import_available,
        "version": installed_version,
    }


def _finite_vector(values: Sequence[float], *, field_name: str) -> tuple[float, ...]:
    try:
        normalized = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ModelExecutionContractError(f"{field_name} должен быть числовым") from exc
    if not np.isfinite(np.asarray(normalized, dtype=float)).all():
        raise ModelExecutionContractError(f"{field_name} содержит NaN/Inf")
    return normalized


def _finite_matrix(
    values: Mapping[str, Sequence[float]], *, field_name: str, expected_length: int,
) -> dict[str, tuple[float, ...]]:
    normalized: dict[str, tuple[float, ...]] = {}
    for name, column in values.items():
        if not str(name):
            raise ModelExecutionContractError(f"{field_name} содержит пустое имя")
        vector = _finite_vector(column, field_name=f"{field_name}.{name}")
        if len(vector) != expected_length:
            raise ModelExecutionContractError(
                f"{field_name}.{name}: длина {len(vector)} не равна {expected_length}"
            )
        normalized[str(name)] = vector
    return normalized


@dataclass(frozen=True)
class ModelExecutionRequest:
    """Train-only model input with future-known data separated by construction."""

    target: Sequence[float]
    horizon: int
    objective: ModelObjective = "level_forecast"
    seasonal_period: int = 1
    params: Mapping[str, Any] = field(default_factory=dict)
    train_features: Mapping[str, Sequence[float]] = field(default_factory=dict)
    future_features: Mapping[str, Sequence[float]] = field(default_factory=dict)
    related_series: Mapping[str, Sequence[float]] = field(default_factory=dict)
    train_timestamps: Sequence[str] = field(default_factory=tuple)
    future_timestamps: Sequence[str] = field(default_factory=tuple)
    random_state: int = 42

    def __post_init__(self) -> None:
        if int(self.horizon) < 1:
            raise ModelExecutionContractError("horizon должен быть положительным")
        if int(self.seasonal_period) < 1:
            raise ModelExecutionContractError("seasonal_period должен быть положительным")
        if self.objective not in {"level_forecast", "multivariate", "volatility"}:
            raise ModelExecutionContractError(f"Неподдерживаемый objective: {self.objective}")
        target = _finite_vector(self.target, field_name="target")
        if not target:
            raise ModelExecutionContractError("target train fold пуст")
        train_features = _finite_matrix(
            self.train_features, field_name="train_features", expected_length=len(target),
        )
        future_features = _finite_matrix(
            self.future_features, field_name="future_features", expected_length=int(self.horizon),
        )
        related_series = _finite_matrix(
            self.related_series, field_name="related_series", expected_length=len(target),
        )
        if self.train_timestamps and len(self.train_timestamps) != len(target):
            raise ModelExecutionContractError(
                "train_timestamps должны совпадать с длиной target"
            )
        if self.future_timestamps and len(self.future_timestamps) != int(self.horizon):
            raise ModelExecutionContractError(
                "future_timestamps должны совпадать с horizon"
            )
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "horizon", int(self.horizon))
        object.__setattr__(self, "seasonal_period", int(self.seasonal_period))
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "train_features", train_features)
        object.__setattr__(self, "future_features", future_features)
        object.__setattr__(self, "related_series", related_series)
        object.__setattr__(self, "train_timestamps", tuple(str(value) for value in self.train_timestamps))
        object.__setattr__(self, "future_timestamps", tuple(str(value) for value in self.future_timestamps))
        object.__setattr__(self, "random_state", int(self.random_state))


@dataclass(frozen=True)
class ModelExecutionResult:
    """Normalized adapter output before fold metrics are calculated."""

    forecast: Sequence[float]
    lower_interval: Sequence[float] | None = None
    upper_interval: Sequence[float] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "forecast", _finite_vector(self.forecast, field_name="forecast"),
        )
        if self.lower_interval is not None:
            object.__setattr__(
                self, "lower_interval",
                _finite_vector(self.lower_interval, field_name="lower_interval"),
            )
        if self.upper_interval is not None:
            object.__setattr__(
                self, "upper_interval",
                _finite_vector(self.upper_interval, field_name="upper_interval"),
            )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "warnings", tuple(str(value) for value in self.warnings))


ModelExecutor = Callable[[ModelExecutionRequest], ModelExecutionResult]


@dataclass(frozen=True)
class ModelExecutionDefinition:
    """Immutable capabilities and adapter identity for one production model."""

    model_id: str
    family_id: str
    adapter_id: str
    executor: ModelExecutor
    objective: ModelObjective = "level_forecast"
    model_version: str = "1.0.0"
    adapter_version: str = "1.0.0"
    input_kind: ExecutionInputKind = "univariate"
    output_kind: ExecutionOutputKind = "point"
    fit_policy: Literal["per_train_fold"] = "per_train_fold"
    actions: frozenset[ExecutionAction] = frozenset({"backtest", "diagnostics"})
    requires_train_features: bool = False
    supports_future_features: bool = False
    requires_related_series: bool = False
    supports_prediction_intervals: bool = False
    deterministic: bool = True
    engine: str = "native"
    required_packages: tuple[str, ...] = ()
    resource_capabilities: ModelResourceCapabilities = field(
        default_factory=ModelResourceCapabilities,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", frozenset(self.actions))
        object.__setattr__(self, "required_packages", tuple(self.required_packages))
        if not self.model_id or not self.family_id or not self.adapter_id:
            raise ModelExecutionContractError(
                "model_id, family_id и adapter_id обязательны"
            )
        if not callable(self.executor):
            raise ModelExecutionContractError("executor должен быть callable")
        if self.objective not in {"level_forecast", "multivariate", "volatility"}:
            raise ModelExecutionContractError(f"Неподдерживаемый objective: {self.objective}")
        if self.input_kind not in {"univariate", "supervised", "multivariate", "panel"}:
            raise ModelExecutionContractError(f"Неподдерживаемый input_kind: {self.input_kind}")
        supported_actions = {"backtest", "tune", "diagnostics"}
        if not self.actions or not self.actions.issubset(supported_actions):
            raise ModelExecutionContractError("actions содержит неподдерживаемое действие")
        if "tune" in self.actions and "backtest" not in self.actions:
            raise ModelExecutionContractError("tune требует backtest action")
        if self.requires_train_features and self.input_kind not in {"supervised", "panel"}:
            raise ModelExecutionContractError(
                "requires_train_features требует input_kind=supervised или panel"
            )
        if self.supports_future_features and self.input_kind not in {"supervised", "panel"}:
            raise ModelExecutionContractError(
                "supports_future_features требует input_kind=supervised или panel"
            )
        if self.requires_related_series and self.input_kind not in {"multivariate", "panel"}:
            raise ModelExecutionContractError(
                "requires_related_series требует input_kind=multivariate или panel"
            )
        if self.objective == "multivariate" and self.input_kind != "multivariate":
            raise ModelExecutionContractError(
                "objective=multivariate требует input_kind=multivariate"
            )

    def dependency_status(self) -> tuple[dict[str, Any], ...]:
        return tuple(_probe_dependency(package) for package in self.required_packages)

    def lifecycle_capabilities(self) -> ModelLifecycleCapabilities:
        return ModelLifecycleCapabilities(
            fit="backtest" in self.actions,
            predict="backtest" in self.actions,
            tuning="tune" in self.actions,
            diagnostics="diagnostics" in self.actions,
        )

    def runtime_available(self) -> bool:
        return all(item["available"] for item in self.dependency_status())

    def descriptor(self) -> dict[str, Any]:
        dependencies = self.dependency_status()
        lifecycle = self.lifecycle_capabilities()
        payload = {
            "version": MODEL_EXECUTION_CONTRACT_VERSION,
            "model_id": self.model_id,
            "family_id": self.family_id,
            "adapter_id": self.adapter_id,
            "objective": self.objective,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "input_kind": self.input_kind,
            "output_kind": self.output_kind,
            "fit_policy": self.fit_policy,
            "actions": sorted(self.actions),
            "requires_train_features": self.requires_train_features,
            "supports_future_features": self.supports_future_features,
            "requires_related_series": self.requires_related_series,
            "supports_prediction_intervals": self.supports_prediction_intervals,
            "deterministic": self.deterministic,
            "engine": self.engine,
            "required_packages": list(self.required_packages),
            "dependency_status": list(dependencies),
            "library_versions": {
                "python": platform.python_version(),
                **{item["package"]: item["version"] for item in dependencies},
            },
            "runtime_available": all(item["available"] for item in dependencies),
            "lifecycle_capabilities": {
                "fit": lifecycle.fit,
                "predict": lifecycle.predict,
                "tuning": lifecycle.tuning,
                "diagnostics": lifecycle.diagnostics,
            },
            "resource_capabilities": {
                "cpu": self.resource_capabilities.cpu,
                "gpu": self.resource_capabilities.gpu,
                "memory_class": self.resource_capabilities.memory_class,
                "supports_parallel_folds": self.resource_capabilities.supports_parallel_folds,
            },
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return {**payload, "signature": sha256(encoded).hexdigest()}


class ModelExecutionRegistry:
    """Validated, immutable-by-interface collection of execution adapters."""

    def __init__(self, definitions: Sequence[ModelExecutionDefinition]):
        indexed: dict[str, ModelExecutionDefinition] = {}
        for definition in definitions:
            if definition.model_id in indexed:
                raise ModelExecutionContractError(
                    f"Дублирующийся model_id: {definition.model_id}"
                )
            indexed[definition.model_id] = definition
        self._definitions = indexed

    @property
    def model_ids(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def model_ids_for(self, action: ExecutionAction) -> frozenset[str]:
        return frozenset(
            model_id for model_id, definition in self._definitions.items()
            if action in definition.actions and definition.runtime_available()
        )

    def get(self, model_id: str) -> ModelExecutionDefinition | None:
        return self._definitions.get(model_id)

    def require(self, model_id: str) -> ModelExecutionDefinition:
        definition = self.get(model_id)
        if definition is None:
            raise ModelExecutionContractError(
                f"Production execution adapter для модели '{model_id}' не зарегистрирован"
            )
        return definition

    def describe(self, model_id: str) -> dict[str, Any]:
        return self.require(model_id).descriptor()

    def execute(
        self, model_id: str, request: ModelExecutionRequest,
    ) -> ModelExecutionResult:
        definition = self.require(model_id)
        dependencies = definition.dependency_status()
        unavailable = [item["package"] for item in dependencies if not item["available"]]
        if unavailable:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' недоступна: отсутствуют зависимости {unavailable}"
            )
        if request.objective != definition.objective:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' имеет objective={definition.objective}, "
                f"получен {request.objective}"
            )
        if definition.requires_train_features and not request.train_features:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' требует train_features"
            )
        if request.train_features and definition.input_kind == "univariate":
            raise ModelExecutionContractError(
                f"Модель '{model_id}' не принимает train_features"
            )
        if request.future_features and not definition.supports_future_features:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' не принимает future_features"
            )
        if request.future_features and not set(request.future_features).issubset(request.train_features):
            raise ModelExecutionContractError(
                "future_features должны иметь соответствующие train_features"
            )
        if definition.requires_related_series and not request.related_series:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' требует related_series"
            )
        if request.related_series and definition.input_kind not in {"multivariate", "panel"}:
            raise ModelExecutionContractError(
                f"Модель '{model_id}' не принимает related_series"
            )

        result = definition.executor(request)
        if not isinstance(result, ModelExecutionResult):
            raise ModelExecutionContractError(
                f"Адаптер '{definition.adapter_id}' вернул неверный тип результата"
            )
        if len(result.forecast) != request.horizon:
            raise ModelExecutionContractError(
                f"forecast: длина {len(result.forecast)} не равна horizon={request.horizon}"
            )
        if (result.lower_interval is None) != (result.upper_interval is None):
            raise ModelExecutionContractError(
                "Prediction interval должен содержать обе границы"
            )
        if result.lower_interval is not None and result.upper_interval is not None:
            if not definition.supports_prediction_intervals:
                raise ModelExecutionContractError(
                    f"Модель '{model_id}' не объявила prediction intervals"
                )
            if len(result.lower_interval) != request.horizon or len(result.upper_interval) != request.horizon:
                raise ModelExecutionContractError(
                    "Prediction interval должен совпадать с horizon"
                )
            if any(
                lower > point or point > upper
                for lower, point, upper in zip(
                    result.lower_interval, result.forecast, result.upper_interval, strict=True,
                )
            ):
                raise ModelExecutionContractError(
                    "Prediction interval не содержит point forecast"
                )
        return result


def fixed_origin_baseline_predict(
    model_id: str, target: Sequence[float], horizon: int, seasonal_period: int,
) -> list[float]:
    """Leakage-safe fixed-origin baseline forecasts."""
    if not target:
        raise ModelExecutionContractError("Train fold пуст")
    history = [float(value) for value in target]
    if model_id == "naive":
        return [history[-1]] * horizon
    if model_id == "mean":
        return [float(np.mean(history))] * horizon
    if model_id == "drift":
        slope = (history[-1] - history[0]) / max(len(history) - 1, 1)
        return [history[-1] + slope * step for step in range(1, horizon + 1)]
    if model_id == "seasonal_naive":
        if seasonal_period < 1 or len(history) < seasonal_period:
            raise ModelExecutionContractError(
                f"Seasonal Naive требует не менее одного полного периода m={seasonal_period} в train"
            )
        forecast: list[float] = []
        for _ in range(horizon):
            value = history[-seasonal_period]
            forecast.append(value)
            history.append(value)
        return forecast
    raise ModelExecutionContractError(f"Неизвестная baseline-модель: {model_id}")


def _baseline_executor(model_id: str) -> ModelExecutor:
    def execute(request: ModelExecutionRequest) -> ModelExecutionResult:
        return ModelExecutionResult(forecast=fixed_origin_baseline_predict(
            model_id, request.target, request.horizon, request.seasonal_period,
        ))
    return execute


def _ets_executor(*, force_damped: bool) -> ModelExecutor:
    def execute(request: ModelExecutionRequest) -> ModelExecutionResult:
        from apps.api.model_impls.ets import _ets_fit_predict

        period = int(request.params.get("seasonal_periods", request.seasonal_period))
        forecast = _ets_fit_predict(
            list(request.target), request.horizon, period,
            damped=True if force_damped else bool(request.params.get("damped_trend", False)),
            trend=request.params.get("trend", "add"),
            seasonal=request.params.get("seasonal", "add"),
        )
        return ModelExecutionResult(forecast=forecast)
    return execute


def _theta_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.theta import _theta_fit_predict

    return ModelExecutionResult(forecast=_theta_fit_predict(
        list(request.target), request.horizon, request.seasonal_period,
    ))


def _arima_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.arima import DEFAULT_ARIMA_ORDER, _arima_fit_predict

    order = tuple(
        int(request.params.get(key, DEFAULT_ARIMA_ORDER[index]))
        for index, key in enumerate(("p", "d", "q"))
    )
    return ModelExecutionResult(forecast=_arima_fit_predict(
        list(request.target), request.horizon, order,
    ))


def _auto_arima_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.arima import _arima_fit_predict, _auto_arima_select_order

    target = list(request.target)
    order = _auto_arima_select_order(target)
    return ModelExecutionResult(
        forecast=_arima_fit_predict(target, request.horizon, order),
        metadata={"selected_order": list(order)},
    )


_BACKTEST_DIAGNOSTICS = frozenset({"backtest", "diagnostics"})
_TUNABLE = frozenset({"backtest", "tune", "diagnostics"})
_CLASSICAL_RESOURCES = ModelResourceCapabilities(memory_class="standard")

MODEL_EXECUTION_REGISTRY = ModelExecutionRegistry([
    ModelExecutionDefinition(
        model_id=model_id, family_id="baselines",
        adapter_id=f"baseline-{model_id}", executor=_baseline_executor(model_id),
        actions=_BACKTEST_DIAGNOSTICS, engine="numpy", required_packages=("numpy",),
    )
    for model_id in ("naive", "seasonal_naive", "drift", "mean")
] + [
    ModelExecutionDefinition(
        model_id="ets", family_id="exponential_smoothing",
        adapter_id="statsmodels-ets", executor=_ets_executor(force_damped=False),
        actions=_TUNABLE, engine="statsmodels", required_packages=("statsmodels",),
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="ets_damped", family_id="exponential_smoothing",
        adapter_id="statsmodels-ets-damped", executor=_ets_executor(force_damped=True),
        actions=_TUNABLE, engine="statsmodels", required_packages=("statsmodels",),
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="theta", family_id="exponential_smoothing",
        adapter_id="statsmodels-theta", executor=_theta_executor,
        actions=_BACKTEST_DIAGNOSTICS, engine="statsmodels",
        required_packages=("statsmodels",),
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="arima", family_id="arima",
        adapter_id="statsmodels-arima", executor=_arima_executor,
        actions=_TUNABLE, engine="statsmodels", required_packages=("statsmodels",),
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="arima_auto", family_id="arima",
        adapter_id="statsmodels-auto-arima", executor=_auto_arima_executor,
        actions=_BACKTEST_DIAGNOSTICS, engine="statsmodels",
        required_packages=("statsmodels",),
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
])


LegacyPredictor = Callable[[list[float], int, int, Mapping[str, Any]], list[float]]


def legacy_predictor_registry(
    registry: ModelExecutionRegistry = MODEL_EXECUTION_REGISTRY,
) -> dict[str, LegacyPredictor]:
    """Compatibility facade for callers that still inject plain functions."""
    predictors: dict[str, LegacyPredictor] = {}
    for registered_model_id in registry.model_ids:
        def predict(
            target: list[float], horizon: int, seasonal_period: int,
            params: Mapping[str, Any], *, _model_id: str = registered_model_id,
        ) -> list[float]:
            result = registry.execute(_model_id, ModelExecutionRequest(
                target=target, horizon=horizon, seasonal_period=seasonal_period,
                params=params,
            ))
            return list(result.forecast)
        predictors[registered_model_id] = predict
    return predictors
