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
ModelDependencyGroup = Literal["classical", "ml", "volatility", "neural"]


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


# Distribution name -> importable module name.  У scikit-learn имя
# дистрибутива (pip/metadata) и имя импортируемого модуля расходятся --
# без алиаса find_spec("scikit_learn") возвращает None и адаптер
# ошибочно считался недоступным в рантайме (Task 127).
_IMPORT_NAME_ALIASES: dict[str, str] = {"scikit-learn": "sklearn"}


def _probe_dependency(package_name: str) -> dict[str, Any]:
    """Inspect a package only when runtime readiness/lineage is requested."""
    import_name = _IMPORT_NAME_ALIASES.get(
        package_name, package_name.replace("-", "_"),
    )
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
    dependency_group: ModelDependencyGroup = "classical"
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
        if self.dependency_group not in {"classical", "ml", "volatility", "neural"}:
            raise ModelExecutionContractError(
                f"Неподдерживаемая dependency_group: {self.dependency_group}"
            )
        supported_actions = {"backtest", "tune", "diagnostics"}
        if not self.actions or not self.actions.issubset(supported_actions):
            raise ModelExecutionContractError("actions содержит неподдерживаемое действие")
        if "tune" in self.actions and "backtest" not in self.actions:
            raise ModelExecutionContractError("tune требует backtest action")
        if self.requires_train_features and self.input_kind not in {"supervised", "panel"}:
            raise ModelExecutionContractError(
                "requires_train_features требует input_kind=supervised или panel"
            )
        if self.supports_future_features and self.input_kind not in {
            "supervised", "panel", "multivariate",
        }:
            # Task 133: multivariate-модель с exogenous-каналом (VARX) --
            # честный носитель future-known регрессоров: yaml::var
            # supports_exogenous: true.  Fail-closed гейты исполнения не
            # меняются: train/future_features отвергаются для всех, кто их
            # не объявил, включая univariate.
            raise ModelExecutionContractError(
                "supports_future_features требует input_kind=supervised, "
                "panel или multivariate (VARX)"
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
            "dependency_group": self.dependency_group,
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


def _prophet_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.prophet import _prophet_fit_predict

    if not request.train_timestamps:
        raise ModelExecutionContractError(
            "Модель 'prophet' требует train_timestamps: fold без реальных дат "
            "не может быть исполнен (строгий future-known contract)"
        )
    if not request.future_timestamps:
        raise ModelExecutionContractError(
            "Модель 'prophet' требует future_timestamps на весь horizon"
        )
    forecast, lower, upper = _prophet_fit_predict(
        y_train=list(request.target),
        horizon=request.horizon,
        train_timestamps=request.train_timestamps,
        future_timestamps=request.future_timestamps,
        changepoint_prior_scale=float(request.params.get("changepoint_prior_scale", 0.05)),
        seasonality_prior_scale=float(request.params.get("seasonality_prior_scale", 10.0)),
        seasonality_mode=str(request.params.get("seasonality_mode", "additive")),
        country_holidays=request.params.get("country_holidays"),
        # Task 126: платформа гейтит состав (future_known/static only) и
        # capability; адаптер остаётся role-agnostic и валидирует только
        # симметрию/длины/конечность (fail-closed).
        train_features=request.train_features or None,
        future_features=request.future_features or None,
    )
    return ModelExecutionResult(forecast=forecast, lower_interval=lower, upper_interval=upper)


def _tbats_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.tbats import _tbats_fit_predict

    # NB: НЕ "seasonal_periods" -- этот ключ уже занят _ets_executor как
    # override единственного seasonal_period (см. выше); см. также
    # backtesting.py::run_backtest_plan.
    forecast, lower, upper = _tbats_fit_predict(
        y_train=list(request.target),
        horizon=request.horizon,
        seasonal_period=request.seasonal_period,
        seasonal_periods=request.params.get("tbats_seasonal_periods"),
        use_boxcox=bool(request.params.get("use_boxcox", True)),
        trend_spec=str(request.params.get("trend_spec", "damped_trend")),
    )
    return ModelExecutionResult(forecast=forecast, lower_interval=lower, upper_interval=upper)


def _random_forest_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.random_forest import _rf_fit_predict

    payload = _rf_fit_predict(
        list(request.target),
        request.horizon,
        train_features=request.train_features or None,
        future_features=request.future_features or None,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=payload["forecast"],
        lower_interval=payload["lower"],
        upper_interval=payload["upper"],
        metadata={
            "feature_importances": payload["feature_importances"],
            "feature_importance_lineage": payload["feature_importance_lineage"],
        },
    )


def _var_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 132/133: нативный statsmodels VAR/VARX поверх related_series-канала v2.

    Плоский контракт ``forecast`` = колонка target-ряда (первая колонка
    системы); полный векторный payload (матрицы forecast/lower/upper,
    порядок лага, коэффициенты, in-sample остатки) -- в metadata и
    читается векторным движком (run_vector_backtest_plan).  VARX (Task
    133): request.train_features/future_features -- future-known экзогенные
    регрессоры (registry-гейт: supports_future_features=True).
    """
    from apps.api.model_impls.var import _var_fit_predict

    payload = _var_fit_predict(
        list(request.target),
        request.horizon,
        related_series=dict(request.related_series) or None,
        params=dict(request.params),
        random_state=request.random_state,
        exog=dict(request.train_features) if request.train_features else None,
        exog_future=dict(request.future_features) if request.future_features else None,
    )
    vector_forecast = payload["forecast"]
    return ModelExecutionResult(
        forecast=[float(value) for value in vector_forecast[:, 0]],
        lower_interval=[float(value) for value in payload["lower"][:, 0]],
        upper_interval=[float(value) for value in payload["upper"][:, 0]],
        metadata={
            "vector_forecast": payload["forecast"].tolist(),
            "vector_lower": payload["lower"].tolist(),
            "vector_upper": payload["upper"].tolist(),
            "series_names": list(payload["series_names"]),
            "lag_order": payload["lag_order"],
            "lag_selection": payload["lag_selection"],
            "trend": payload["trend"],
            "alpha": payload["alpha"],
            "nobs": payload["nobs"],
            "coefficient_matrices": [
                block.tolist() for block in payload["coefficient_matrices"]
            ],
            "in_sample_residuals": payload["in_sample_residuals"].tolist(),
            "deterministic": payload["deterministic"],
            "exogenous": payload.get("exogenous"),
        },
    )


def _vecm_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 133: нативный statsmodels VECM поверх related_series-канала v2.

    Плоский контракт ``forecast`` = колонка target-ряда (первая колонка
    системы); полный векторный payload (матрицы forecast/lower/upper,
    fold-local ранг Йохансена, VAR-представление, in-sample остатки) --
    в metadata и читается векторным движком (run_vector_backtest_plan).
    Exogenous-канала нет (yaml: supports_exogenous: false): реестр
    fail-closed отвергает future_features для vecm.
    """
    from apps.api.model_impls.vecm import _vecm_fit_predict

    payload = _vecm_fit_predict(
        list(request.target),
        request.horizon,
        related_series=dict(request.related_series) or None,
        params=dict(request.params),
        random_state=request.random_state,
    )
    vector_forecast = payload["forecast"]
    return ModelExecutionResult(
        forecast=[float(value) for value in vector_forecast[:, 0]],
        lower_interval=[float(value) for value in payload["lower"][:, 0]],
        upper_interval=[float(value) for value in payload["upper"][:, 0]],
        metadata={
            "vector_forecast": payload["forecast"].tolist(),
            "vector_lower": payload["lower"].tolist(),
            "vector_upper": payload["upper"].tolist(),
            "series_names": list(payload["series_names"]),
            "k_ar_diff": payload["k_ar_diff"],
            "coint_rank": payload["coint_rank"],
            "rank_selection": payload["rank_selection"],
            "deterministic_terms": payload["deterministic_terms"],
            "alpha": payload["alpha"],
            "nobs": payload["nobs"],
            "coefficient_matrices": [
                block.tolist() for block in payload["coefficient_matrices"]
            ],
            "in_sample_residuals": payload["in_sample_residuals"].tolist(),
            "deterministic": payload["deterministic"],
        },
    )


def _garch_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 135: нативный GARCH пакета arch -- первый исполнитель
    volatility-контракта Task 134.

    Плоский контракт ``forecast`` = прогноз УСЛОВНОЙ ДИСПЕРСИИ (target
    volatility-cohort, НЕ уровень ряда); симуляционные квантили путей
    дисперсии -- в lower/upper (детерминизм -- сидированный rng).
    Полный payload (параметры MLE, persistence, стандартизованные
    остатки, сходимость) -- в metadata и читается volatility-движком
    (run_volatility_backtest_plan) для диагностики контракта Task 134.
    Exogenous-канала нет (GARCHX не декларирован, см. Task 134:
    feature_contract policy="none"); реестр fail-closed отвергает
    train/future_features для univariate-входа.
    """
    from apps.api.model_impls.garch import _garch_fit_predict

    payload = _garch_fit_predict(
        list(request.target),
        request.horizon,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=[float(value) for value in payload["variance_forecast"]],
        lower_interval=[float(value) for value in payload["lower"]],
        upper_interval=[float(value) for value in payload["upper"]],
        metadata={
            "adapter_id": payload["adapter_id"],
            "params": payload["params"],
            "persistence": payload["persistence"],
            "is_covariance_stationary": payload["is_covariance_stationary"],
            "convergence_flag": payload["convergence_flag"],
            "nobs": payload["nobs"],
            "loglikelihood": payload["loglikelihood"],
            "aic": payload["aic"],
            "bic": payload["bic"],
            "std_residuals": payload["std_residuals"].tolist(),
            "conditional_volatility": payload["conditional_volatility"].tolist(),
            "mean_model": payload["mean_model"],
            "dist": payload["dist"],
            "intervals": payload["intervals"],
            "deterministic": payload["deterministic"],
        },
    )


def _egarch_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 136: нативный EGARCH пакета arch -- второй исполнитель
    volatility-контракта Task 134 (прецедент пары var/vecm: тот же
    volatility-движок, новый адаптер + запись реестра).

    Плоский контракт ``forecast`` = прогноз УСЛОВНОЙ ДИСПЕРСИИ (target
    volatility-cohort, НЕ уровень ряда) -- официальный симуляционный
    контур arch (EGARCH не имеет analytic-прогноза за горизонтом 1;
    variance.values == среднее путей = честная MC-оценка условного
    ожидания E[sigma2] -- оптимальный точечный прогноз под QLIKE);
    квантили тех же путей -- в lower/upper (детерминизм -- сидированный
    rng).  Полный payload (параметры MLE, beta-персистентность,
    стандартизованные остатки, сходимость, asymmetry-блок
    leverage/gamma-статистика -- ядро Task 136) -- в metadata и читается
    volatility-движком (run_volatility_backtest_plan) для диагностики
    контракта Task 134.  Exogenous-канала нет; реестр fail-closed
    отвергает train/future_features для univariate-входа.
    """
    from apps.api.model_impls.egarch import _egarch_fit_predict

    payload = _egarch_fit_predict(
        list(request.target),
        request.horizon,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=[float(value) for value in payload["variance_forecast"]],
        lower_interval=[float(value) for value in payload["lower"]],
        upper_interval=[float(value) for value in payload["upper"]],
        metadata={
            "adapter_id": payload["adapter_id"],
            "params": payload["params"],
            "persistence": payload["persistence"],
            "is_covariance_stationary": payload["is_covariance_stationary"],
            "convergence_flag": payload["convergence_flag"],
            "nobs": payload["nobs"],
            "loglikelihood": payload["loglikelihood"],
            "aic": payload["aic"],
            "bic": payload["bic"],
            "std_residuals": payload["std_residuals"].tolist(),
            "conditional_volatility": payload["conditional_volatility"].tolist(),
            "asymmetry": payload["asymmetry"],
            "mean_model": payload["mean_model"],
            "dist": payload["dist"],
            "intervals": payload["intervals"],
            "deterministic": payload["deterministic"],
        },
    )


def _lstm_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 138: LSTM/GRU -- первый исполнитель neural-runtime контракта
    Task 137 (единый NeuralForecast-runtime, neural_runtime.py).

    Одномерная level-модель (objective="level_forecast",
    input_kind="univariate"): точечный прогноз -- честный нейро-фит на
    train-срезе fold'а; интервалы -- официальный conformal-контур
    контракта (fit prediction_intervals + predict level), уровни из
    interval_levels_for_alpha.  Ячейка cell_type ∈ {LSTM, GRU} --
    bounded-параметр (yaml::lstm param_space, честная альтернатива
    каталожного имени «LSTM / GRU»).  Детерминизм: random_state реестра
    доходит до КОНСТРУКТОРА модели (ресертификация Task 137).  Бюджет
    обучения -- константа LSTM_MAX_STEPS адаптера (тюнинг бюджета -- вне
    param_space, прецедент Task 136).  Feature-каналы отвергаются гейтами
    реестра для univariate-входа (exog-канал нейро-моделей -- отдельная
    постановка, прецедент GARCHX/VARX).
    """
    from apps.api.model_impls.lstm import _lstm_fit_predict

    payload = _lstm_fit_predict(
        list(request.target),
        request.horizon,
        params=dict(request.params),
        random_state=request.random_state,
        timestamps=list(request.train_timestamps) or None,
    )
    return ModelExecutionResult(
        forecast=[float(value) for value in payload["forecast"]],
        lower_interval=[float(value) for value in payload["lower"]],
        upper_interval=[float(value) for value in payload["upper"]],
        metadata={
            "adapter_id": payload["adapter_id"],
            "params": payload["params"],
            "cell_type": payload["cell_type"],
            "nobs": payload["nobs"],
            "max_steps": payload["max_steps"],
            "seed": payload["seed"],
            "freq": payload["freq"],
            "intervals": payload["intervals"],
            "deterministic": payload["deterministic"],
        },
    )


def _nbeats_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 139: N-BEATS -- второй исполнитель neural-runtime контракта
    Task 137 (прецедент пары lstm Task 138: единый NeuralForecast-runtime,
    neural_runtime.py).

    Одномерная level-модель (objective="level_forecast",
    input_kind="univariate"; каталог: supports_exogenous=false): точечный
    прогноз -- честный нейро-фит на train-срезе fold'а; интервалы --
    официальный conformal-контур контракта (fit prediction_intervals +
    predict level), уровни из interval_levels_for_alpha.  Архитектурный
    выбор стека stack_config ∈ {interpretable, generic} -- bounded-параметр
    (yaml::nbeats param_space, честная альтернатива каталожного описания
    «Basis expansion network. Интерпретируемая декомпозиция (тренд +
    сезонность)»): interpretable -- каноническая декомпозиция Oreshkin
    et al. 2019 (trend/seasonality стеки), generic -- basis-expansion
    identity-стеки.  Детерминизм: random_state реестра доходит до
    КОНСТРУКТОРА модели (ресертификация Task 137).  Бюджет обучения --
    константа NBEATS_MAX_STEPS адаптера (тюнинг бюджета -- вне
    param_space, прецедент Task 136).  Feature-каналы отвергаются гейтами
    реестра для univariate-входа.
    """
    from apps.api.model_impls.nbeats import _nbeats_fit_predict

    payload = _nbeats_fit_predict(
        list(request.target),
        request.horizon,
        params=dict(request.params),
        random_state=request.random_state,
        timestamps=list(request.train_timestamps) or None,
    )
    return ModelExecutionResult(
        forecast=[float(value) for value in payload["forecast"]],
        lower_interval=[float(value) for value in payload["lower"]],
        upper_interval=[float(value) for value in payload["upper"]],
        metadata={
            "adapter_id": payload["adapter_id"],
            "params": payload["params"],
            "stack_config": payload["stack_config"],
            "nobs": payload["nobs"],
            "max_steps": payload["max_steps"],
            "seed": payload["seed"],
            "freq": payload["freq"],
            "intervals": payload["intervals"],
            "deterministic": payload["deterministic"],
        },
    )


def _nhits_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    """Task 140: N-HiTS -- третий исполнитель neural-runtime контракта
    Task 137 (прецедент пар lstm Task 138 / nbeats Task 139: единый
    NeuralForecast-runtime, neural_runtime.py).

    Одномерная level-модель (objective="level_forecast",
    input_kind="univariate"; каталог: supports_exogenous=false): точечный
    прогноз -- честный нейро-фит на train-срезе fold'а; интервалы --
    официальный conformal-контур контракта (fit prediction_intervals +
    predict level), уровни из interval_levels_for_alpha.  Архитектурный
    выбор степени иерархической интерполяции interpolation_config ∈
    {hierarchical, light} -- bounded-параметр (yaml::nhits param_space,
    честная альтернатива каталожного описания «Hierarchical interpolation
    N-BEATS. Быстрее и точнее на долгих горизонтах»): hierarchical --
    канонический N-HiTS Challu et al. 2023 (официальные дефолты 3.2.2),
    light -- минимальная иерархия.  Детерминизм: random_state реестра
    доходит до КОНСТРУКТОРА модели (ресертификация Task 137).  Бюджет
    обучения -- константа NHITS_MAX_STEPS адаптера (тюнинг бюджета --
    вне param_space, прецедент Task 136).  Feature-каналы отвергаются
    гейтами реестра для univariate-входа.  Пара nbeats/nhits -- единый
    runtime и один level-cohort: честное ранжирование comparison
    sectioned by objective применимо к паре напрямую.
    """
    from apps.api.model_impls.nhits import _nhits_fit_predict

    payload = _nhits_fit_predict(
        list(request.target),
        request.horizon,
        params=dict(request.params),
        random_state=request.random_state,
        timestamps=list(request.train_timestamps) or None,
    )
    return ModelExecutionResult(
        forecast=[float(value) for value in payload["forecast"]],
        lower_interval=[float(value) for value in payload["lower"]],
        upper_interval=[float(value) for value in payload["upper"]],
        metadata={
            "adapter_id": payload["adapter_id"],
            "params": payload["params"],
            "interpolation_config": payload["interpolation_config"],
            "nobs": payload["nobs"],
            "max_steps": payload["max_steps"],
            "seed": payload["seed"],
            "freq": payload["freq"],
            "intervals": payload["intervals"],
            "deterministic": payload["deterministic"],
        },
    )


def _xgboost_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.xgboost import _xgb_fit_predict

    payload = _xgb_fit_predict(
        list(request.target),
        request.horizon,
        train_features=request.train_features or None,
        future_features=request.future_features or None,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=payload["forecast"],
        lower_interval=payload["lower"],
        upper_interval=payload["upper"],
        metadata={
            "feature_importances": payload["feature_importances"],
            "feature_importance_lineage": payload["feature_importance_lineage"],
        },
    )


def _lightgbm_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.lightgbm import _lgb_fit_predict

    payload = _lgb_fit_predict(
        list(request.target),
        request.horizon,
        train_features=request.train_features or None,
        future_features=request.future_features or None,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=payload["forecast"],
        lower_interval=payload["lower"],
        upper_interval=payload["upper"],
        metadata={
            "feature_importances": payload["feature_importances"],
            "feature_importance_lineage": payload["feature_importance_lineage"],
        },
    )


def _catboost_executor(request: ModelExecutionRequest) -> ModelExecutionResult:
    from apps.api.model_impls.catboost import _cb_fit_predict

    payload = _cb_fit_predict(
        list(request.target),
        request.horizon,
        train_features=request.train_features or None,
        future_features=request.future_features or None,
        params=dict(request.params),
        random_state=request.random_state,
    )
    return ModelExecutionResult(
        forecast=payload["forecast"],
        lower_interval=payload["lower"],
        upper_interval=payload["upper"],
        metadata={
            "feature_importances": payload["feature_importances"],
            "feature_importance_lineage": payload["feature_importance_lineage"],
        },
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
    ModelExecutionDefinition(
        model_id="prophet", family_id="structural",
        adapter_id="prophet-native", executor=_prophet_executor,
        actions=_TUNABLE, engine="prophet", required_packages=("prophet",),
        # Task 126: единственный supervised-адаптер cohort'а -- принимает
        # future_known/static регрессоры fold-local FeaturePlan. Historic
        # (target-derived) колонки не проходят capability-гейт платформы.
        input_kind="supervised",
        supports_future_features=True,
        supports_prediction_intervals=True,
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="tbats", family_id="structural",
        adapter_id="statsforecast-tbats", executor=_tbats_executor,
        actions=_TUNABLE, engine="statsforecast", required_packages=("statsforecast",),
        supports_prediction_intervals=True,
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="random_forest", family_id="tree_ml",
        adapter_id="sklearn-random-forest", executor=_random_forest_executor,
        actions=_TUNABLE, engine="scikit-learn", required_packages=("scikit-learn",),
        # Task 127: второй supervised-адаптер и первый recursive-стратег.
        # Регрессорный канал -- тот же granted-гейт Task 126: только
        # future_known/static колонки fold-local FeaturePlan; historic
        # (target-derived) признаки адаптер строит САМ каузально через
        # RecursiveFeatureState (лаги/rolling/diff), будущее из фактов
        # недостижимо по построению.
        input_kind="supervised",
        supports_future_features=True,
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="ml",
        resource_capabilities=ModelResourceCapabilities(memory_class="standard"),
    ),
    ModelExecutionDefinition(
        model_id="xgboost", family_id="tree_ml",
        adapter_id="xgboost-native", executor=_xgboost_executor,
        actions=_TUNABLE, engine="xgboost", required_packages=("xgboost",),
        # Task 128: третий supervised-адаптер на общем рекурсивном ядре
        # Task 127 (_supervised_recursion); regressor-канал -- тот же
        # granted-гейт Task 126; интервалы -- quantile regression
        # (reg:quantileerror alpha=0.1/0.9, как декларировано в
        # rules/modeling.yaml::xgboost).
        input_kind="supervised",
        supports_future_features=True,
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="ml",
        resource_capabilities=ModelResourceCapabilities(memory_class="standard"),
    ),
    ModelExecutionDefinition(
        model_id="lightgbm", family_id="tree_ml",
        adapter_id="lightgbm-native", executor=_lightgbm_executor,
        actions=_TUNABLE, engine="lightgbm", required_packages=("lightgbm",),
        # Task 129: четвёртый supervised-адаптер на общем рекурсивном ядре
        # Task 127 (_supervised_recursion); regressor-канал -- тот же
        # granted-гейт Task 126; интервалы -- quantile regression
        # (objective="quantile" alpha=0.1/0.9, как декларировано в
        # rules/modeling.yaml::lightgbm); num_threads=1 + deterministic
        # фиксируют построение гистограмм (детерминизм реестра).
        input_kind="supervised",
        supports_future_features=True,
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="ml",
        resource_capabilities=ModelResourceCapabilities(memory_class="standard"),
    ),
    ModelExecutionDefinition(
        model_id="catboost", family_id="tree_ml",
        adapter_id="catboost-native", executor=_catboost_executor,
        actions=_TUNABLE, engine="catboost", required_packages=("catboost",),
        # Task 130: пятый supervised-адаптер и четвёртый dependency_group="ml"
        # на общем рекурсивном ядре Task 127 (_supervised_recursion);
        # regressor-канал -- тот же granted-гейт Task 126; интервалы --
        # quantile regression (loss_function="Quantile:alpha=0.1/0.9", как
        # декларировано в rules/modeling.yaml::catboost); thread_count=1 +
        # random_seed фиксируют детерминизм реестра; деградация константного
        # target fail-closed на уровне библиотеки (CatBoostError).
        input_kind="supervised",
        supports_future_features=True,
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="ml",
        resource_capabilities=ModelResourceCapabilities(memory_class="standard"),
    ),
    ModelExecutionDefinition(
        model_id="var", family_id="multivariate",
        adapter_id="statsmodels-var", executor=_var_executor,
        actions=_TUNABLE, engine="statsmodels",
        required_packages=("statsmodels",),
        # Task 132: первый исполнитель многомерного контракта Task 131.
        # objective="multivariate" + input_kind="multivariate" +
        # requires_related_series -- гейты реестра v2; исполнение ТОЛЬКО
        # через векторный движок run_vector_backtest_plan (EndogenousSystem,
        # векторные OOF-точки/per-series метрики).  Порядок лага --
        # fold-local (select_order/фиксированный p на train-срезе fold'а);
        # интервалы -- нативный VARResults.forecast_interval (НЕ цикл
        # одномерных ARIMA).  Детерминизм: OLS, случайность отсутствует.
        # Task 133: actions=_TUNABLE -- векторный tuning подключён
        # (execute_vector_tuning_plan, bounded param_space yaml::var);
        # supports_future_features=True -- exogenous-канал VARX
        # (future-known регрессоры через request.train/future_features).
        objective="multivariate",
        input_kind="multivariate",
        requires_related_series=True,
        supports_future_features=True,
        supports_prediction_intervals=True,
        deterministic=True,
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="vecm", family_id="multivariate",
        adapter_id="statsmodels-vecm", executor=_vecm_executor,
        actions=_TUNABLE, engine="statsmodels",
        required_packages=("statsmodels",),
        # Task 133: второй исполнитель многомерного контракта Task 131.
        # Ранг Йохансена -- fold-local (coint_rank="auto" => select_coint_rank
        # на train-срезе fold'а; ранг 0 -- честный отказ без VAR-fallback;
        # фиксированный ранг <= K-1).  Прогноз -- нативный VECMResults.predict
        # с интервалами (НЕ цикл одномерных ARIMA).  Диагностика движка --
        # vecm_stability (ровно K - coint_rank единичных корней companion,
        # спектральная теорема Granger-представления) + белый шум системы
        # с df-поправкой ранга K*coint_rank.  supports_future_features=False: exogenous-канал
        # -- только VARX (yaml: vecm supports_exogenous: false); реестр
        # fail-closed отвергает future_features.  Векторный tuning --
        # execute_vector_tuning_plan (bounded param_space yaml::vecm).
        objective="multivariate",
        input_kind="multivariate",
        requires_related_series=True,
        supports_prediction_intervals=True,
        deterministic=True,
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="garch", family_id="volatility",
        adapter_id="arch-garch", executor=_garch_executor,
        actions=_TUNABLE, engine="arch",
        required_packages=("arch",),
        # Task 135: первый исполнитель volatility-контракта Task 134.
        # objective="volatility" + input_kind="univariate" -- гейты реестра
        # v2; исполнение ТОЛЬКО через volatility-движок
        # run_volatility_backtest_plan (VolatilityTarget: явное
        # price->returns, realized proxy, QLIKE-метрики; одномерный движок
        # уровня отказывает volatility-планам -- Task 134).  Порядки (p, q)
        # и спецификация mean/dist -- fold-local MLE на train-срезе returns;
        # rescale=False -- БЕЗ скрытого масштабирования входа.  Интервалы --
        # симуляционные квантили путей дисперсии (сидированный rng).
        # GARCHX (exogenous-канал) не декларирован: feature_contract
        # policy="none" (Task 134; прецедент VARX -- отдельная постановка).
        objective="volatility",
        input_kind="univariate",
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="volatility",
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="egarch", family_id="volatility",
        adapter_id="arch-egarch", executor=_egarch_executor,
        actions=_TUNABLE, engine="arch",
        required_packages=("arch",),
        # Task 136: второй исполнитель volatility-контракта Task 134
        # (прецедент пары var/vecm: volatility-движок Task 135
        # переиспользуется бит-в-бит).  objective="volatility" +
        # input_kind="univariate" -- гейты реестра v2; исполнение ТОЛЬКО
        # через volatility-движок run_volatility_backtest_plan
        # (VolatilityTarget: явное price->returns, realized proxy,
        # QLIKE-метрики).  Порядки (p, o, q) и спецификация mean/dist --
        # fold-local MLE на train-срезе returns; o >= 1 -- модель
        # ОБЯЗАНА параметризовать асимметрию (leverage); rescale=False --
        # БЕЗ скрытого масштабирования входа.  Точечный прогноз --
        # официальный симуляционный контур arch (EGARCH не имеет
        # analytic-прогноза за горизонтом 1); интервалы -- квантили тех
        # же путей (сидированный rng).  Exogenous-канал не декларирован.
        objective="volatility",
        input_kind="univariate",
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="volatility",
        resource_capabilities=_CLASSICAL_RESOURCES,
    ),
    ModelExecutionDefinition(
        model_id="lstm", family_id="neural",
        adapter_id="neuralforecast-lstm-gru", executor=_lstm_executor,
        actions=_TUNABLE, engine="neuralforecast",
        required_packages=("neuralforecast",),
        # Task 138: первый исполнитель neural-runtime контракта Task 137
        # (единый NeuralForecast-runtime neural_runtime.py; ленивый
        # fail-closed импорт torch -- единственная точка платформы).
        # objective="level_forecast" + input_kind="univariate" -- гейты
        # реестра v2; исполнение через одномерный level-движок
        # run_backtest_plan (общий OOF cohort с классикой/ML).  Ячейка
        # cell_type ∈ {LSTM, GRU} -- bounded-параметр (yaml::lstm,
        # честная альтернатива каталожного имени «LSTM / GRU»); интервалы
        # -- официальный conformal-контур контракта (не «MC Dropout»).
        # Детерминизм: random_state -> fold_seed -> random_seed
        # КОНСТРУКТОРА (блокирующая находка сертификации Task 137).
        # Бюджет -- константа LSTM_MAX_STEPS адаптера; tuning -- тот же
        # одномерный движок (execute_tuning_plan, bounded param_space
        # yaml::lstm, 8 trials).  Neural-runtime -- ОПЦИОНАЛЬНАЯ
        # dependency-группа (requirements-neural.txt): runtime_available
        # реестра честно фильтрует readiness там, где группа не
        # установлена; dispatch routers/models.py регистрирует запись
        # условно (_register_neural_dispatch) -- gate реестр<->dispatch
        # остаётся точным в обеих средах.
        input_kind="univariate",
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="neural",
        resource_capabilities=ModelResourceCapabilities(
            memory_class="standard", gpu="optional",
        ),
    ),
    ModelExecutionDefinition(
        model_id="nbeats", family_id="neural",
        adapter_id="neuralforecast-nbeats", executor=_nbeats_executor,
        actions=_TUNABLE, engine="neuralforecast",
        required_packages=("neuralforecast",),
        # Task 139: второй исполнитель neural-runtime контракта Task 137
        # (прецедент пары lstm Task 138: runtime-контракт не меняется --
        # новый адаптер + запись реестра + условный dispatch + yaml).
        # objective="level_forecast" + input_kind="univariate" -- гейты
        # реестра v2; каталог: supports_exogenous=false -- feature-каналы
        # отвергаются fail-closed.  Архитектурный выбор стека
        # stack_config ∈ {interpretable, generic} -- bounded-параметр
        # (yaml::nbeats, честная альтернатива каталожного описания
        # «Basis expansion network. Интерпретируемая декомпозиция (тренд +
        # сезонность)»); интервалы -- официальный conformal-контур
        # контракта (не «MC Dropout»).  Детерминизм: random_state ->
        # fold_seed -> random_seed КОНСТРУКТОРА (ресертификация Task 137;
        # same-seed бит-в-бит подтверждён пробом Task 139).  Бюджет --
        # константа NBEATS_MAX_STEPS адаптера; tuning -- тот же
        # одномерный движок (execute_tuning_plan, bounded param_space
        # yaml::nbeats, 8 trials).  Dispatch routers/models.py
        # регистрирует запись условно (_register_neural_dispatch) --
        # gate реестр<->dispatch остаётся точным в обеих средах.
        input_kind="univariate",
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="neural",
        resource_capabilities=ModelResourceCapabilities(
            memory_class="standard", gpu="optional",
        ),
    ),
    ModelExecutionDefinition(
        model_id="nhits", family_id="neural",
        adapter_id="neuralforecast-nhits", executor=_nhits_executor,
        actions=_TUNABLE, engine="neuralforecast",
        required_packages=("neuralforecast",),
        # Task 140: третий исполнитель neural-runtime контракта Task 137
        # (прецедент пар lstm Task 138 / nbeats Task 139: runtime-контракт
        # не меняется -- новый адаптер + запись реестра + условный
        # dispatch + yaml).  objective="level_forecast" +
        # input_kind="univariate" -- гейты реестра v2; каталог:
        # supports_exogenous=false -- feature-каналы отвергаются
        # fail-closed.  Архитектурный выбор степени иерархической
        # интерполяции interpolation_config ∈ {hierarchical, light} --
        # bounded-параметр (yaml::nhits, честная альтернатива каталожного
        # описания «Hierarchical interpolation N-BEATS. Быстрее и точнее
        # на долгих горизонтах прогнозирования»); интервалы -- официальный
        # conformal-контур контракта (не «MC Dropout»).  Детерминизм:
        # random_state -> fold_seed -> random_seed КОНСТРУКТОРА
        # (ресертификация Task 137; same-seed бит-в-бит подтверждён пробом
        # Task 140).  Бюджет -- константа NHITS_MAX_STEPS адаптера;
        # tuning -- тот же одномерный движок (execute_tuning_plan, bounded
        # param_space yaml::nhits, 8 trials).  Пара nbeats/nhits -- единый
        # runtime (train_and_forecast) и один level-cohort: готовая база
        # сравнения N-BEATS/N-HiTS (постановка Task 140).  Dispatch
        # routers/models.py регистрирует запись условно
        # (_register_neural_dispatch) -- gate реестр<->dispatch остаётся
        # точным в обеих средах.
        input_kind="univariate",
        supports_prediction_intervals=True,
        deterministic=True,
        dependency_group="neural",
        resource_capabilities=ModelResourceCapabilities(
            memory_class="standard", gpu="optional",
        ),
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
