# apps/api/feature_plan.py
"""Task 126 -- Leakage-safe supervised FeaturePlan.

Ядро управляет признаками для supervised-моделей и разделяет их роли по
единственному авторитетному источнику -- флагу ``known_in_advance`` каталога
генерации признаков (остановка «Предобработка → Генерация признаков»):

- ``historic``     -- target-derived каузальные трансформы (лаги, rolling,
  разности) и экзогены, чьё будущее значение неизвестно.  Существуют ТОЛЬКО
  для train-среза fold'а; будущее не материализуется никогда -- рекурсивная
  стратегия подставляет прогнозы модели через ``RecursiveFeatureState``.
- ``future_known`` -- детерминированные функции временной оси (календарь,
  тренд, Fourier), известные на любой горизонт по построению; материализуются
  и для train, и для будущего.
- ``static``       -- построчные константы (сущность, категория объекта).

Инварианты, закрываете ошибки отклонённой сдачи Task 126:

1. Никакой oracle-утечки: derived-признаки пересчитываются каузально ВНУТРИ
   train-среза fold'а; API не содержит пути, который материализует
   historic-признак будущего (ровно та утечка, что была в отклонённой сдаче).
2. Единый рекурсивный контракт: builder хранит хвост train, поэтому первая
   future-строка строится из реального хвоста train, а последующие -- из
   прогнозов модели (``RecursiveFeatureState.next_row``).
3. Fold-local статистика: imputer (медиана train-среза), scaler и one-hot
   encoder фитуются заново на каждом fold'е -- fresh-инстанс builder'а на
   каждый EDA-fold; статистика между fold'ами не разделяется.
4. Fail-closed: отсутствующая/битая (NaN/Inf, длина) платформенная колонка,
   не-константный static, неизвестная семья признаков -- ошибки построения
   плана, а не предупреждения.
5. Импортанс привязан к точной fold-матрице через lineage-record c
   matrix_hash (``bind_feature_importance``); чужие колонки отклоняются.

Историческая память: план иммутабелен, ``plan_id``/``fingerprint``
детерминированы (sha256 канонического JSON) -- они входят в cohort_contract
и cohort_id бэктеста (см. backtesting.py::build_backtest_plan).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Mapping, Optional, Sequence, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover -- только типизация, без runtime-цикла
    from apps.api.backtesting import BacktestFoldPlan


FEATURE_PLAN_CONTRACT_VERSION = "feature-plan-v1"

# Роли признаков: разделение обязанностей, на котором стоит весь leakage-safe
# контракт.  Historic никогда не попадает в regressors-канал адаптеров;
# future_known/static -- единственное, что получают Prophet-подобные модели.
ROLE_HISTORIC = "historic"
ROLE_FUTURE_KNOWN = "future_known"
ROLE_STATIC = "static"
ROLE_VALUES = (ROLE_HISTORIC, ROLE_FUTURE_KNOWN, ROLE_STATIC)

# Семьи признаков каталога генерации (apps/api/preprocessing_feature_engineering).
# exogenous -- платформенная колонка, чья роль определяется known_in_advance.
KIND_LAG = "lag"
KIND_ROLLING = "rolling"
KIND_DIFFERENCE = "difference"
KIND_CALENDAR = "calendar"
KIND_TREND = "trend"
KIND_FOURIER = "fourier"
KIND_EXOGENOUS = "exogenous"
SUPPORTED_KINDS = frozenset({
    KIND_LAG, KIND_ROLLING, KIND_DIFFERENCE,
    KIND_CALENDAR, KIND_TREND, KIND_FOURIER, KIND_EXOGENOUS,
})
TARGET_DERIVED_KINDS = frozenset({KIND_LAG, KIND_ROLLING, KIND_DIFFERENCE})

# Только эти машины могут исполняться без наблюдаемой истории будущих точек.
POLICY_NONE = "none"
POLICY_RECURSIVE = "recursive"
POLICY_DIRECT = "direct"
SUPPORTED_POLICIES = frozenset({POLICY_NONE, POLICY_RECURSIVE, POLICY_DIRECT})

_ROLLING_NAME_PATTERN = re.compile(r"_(mean|std|sum|min|max)_(\d+)$")
_TRAILING_NUMBER_PATTERN = re.compile(r"_(\d+)$")


class FeaturePlanError(ValueError):
    """План/матрица/привязка importance нарушают leakage-safe контракт."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureSpec:
    """Иммутабельное описание одного признака плана."""

    name: str
    kind: str
    role: str
    lookback: int
    params: Mapping[str, Any] = field(default_factory=dict)
    source_column: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True)
class FeaturePlan:
    """Иммутабельный leakage-safe план supervised-признаков.

    Поля задаются построителями (``build_feature_plan_from_metadata`` /
    ``empty_feature_plan``); конструктор открыт для срезов плана в тестах
    (например, план только из historic-признаков).
    """

    plan_id: str
    features: tuple[FeatureSpec, ...]
    policy: str
    fingerprint: str
    source_column: str

    def __post_init__(self) -> None:
        if not self.policy in SUPPORTED_POLICIES:
            raise FeaturePlanError(f"Неподдерживаемая policy FeaturePlan: {self.policy!r}")
        object.__setattr__(self, "features", tuple(self.features))

    # -- роли -------------------------------------------------------------
    def _names_of_role(self, role: str) -> list[str]:
        return [spec.name for spec in self.features if spec.role == role]

    def historic_names(self) -> list[str]:
        """Target-derived/unknown-future признаки (только train-срез)."""
        return self._names_of_role(ROLE_HISTORIC)

    def future_known_names(self) -> list[str]:
        """Признаки, известные заранее на любой горизонт."""
        return self._names_of_role(ROLE_FUTURE_KNOWN)

    def static_names(self) -> list[str]:
        """Построчные константы (entity/category)."""
        return self._names_of_role(ROLE_STATIC)

    def feature_by_name(self) -> dict[str, FeatureSpec]:
        return {spec.name: spec for spec in self.features}

    @property
    def max_lookback(self) -> int:
        """Строгий warm-up: максимум lookback по historic-признакам."""
        return max(
            (int(spec.lookback) for spec in self.features if spec.role == ROLE_HISTORIC),
            default=0,
        )

    # -- идентичность ------------------------------------------------------
    def feature_contract(self) -> dict[str, Any]:
        """Канонический cohort-контракт плана (входит в cohort_id)."""
        return {
            "version": FEATURE_PLAN_CONTRACT_VERSION,
            "policy": self.policy,
            "plan_id": self.plan_id,
            "fingerprint": self.fingerprint,
            "historic": self.historic_names(),
            "future_known": self.future_known_names(),
            "static": self.static_names(),
        }


def _plan_identity(
    features: Sequence[FeatureSpec], *, policy: str, source_column: str,
) -> tuple[str, str]:
    fingerprint = _digest({
        "version": FEATURE_PLAN_CONTRACT_VERSION,
        "source_column": source_column,
        "policy": policy,
        "features": [
            {
                "name": spec.name, "kind": spec.kind, "role": spec.role,
                "lookback": int(spec.lookback),
                "params": dict(spec.params), "source_column": spec.source_column,
            }
            for spec in sorted(features, key=lambda item: item.name)
        ],
    })
    return f"fp_{fingerprint[:12]}", fingerprint


def empty_feature_plan(*, source_column: str = "") -> FeaturePlan:
    """План без признаков: cohort-контракт остаётся legacy-формы."""
    plan_id, fingerprint = _plan_identity((), policy=POLICY_NONE, source_column=source_column)
    return FeaturePlan(
        plan_id=plan_id, features=(), policy=POLICY_NONE,
        fingerprint=fingerprint, source_column=source_column,
    )


def _rolling_params(name: str) -> dict[str, Any]:
    match = _ROLLING_NAME_PATTERN.search(name)
    if match is None:
        raise FeaturePlanError(
            f"Признак '{name}' (family=rolling): окно/статистика не парсятся из имени; "
            "ожидался суффикс '_<statistic>_<window>' (например value_roll_mean_3)"
        )
    return {"statistic": match.group(1), "window": int(match.group(2))}


def build_feature_plan_from_metadata(
    metadata: Mapping[str, Any], *, policy: str = POLICY_RECURSIVE,
) -> FeaturePlan:
    """Построить план из metadata остановки «Генерация признаков».

    Единственный авторитет ролей -- флаг ``known_in_advance`` каждой записи
    ``feature_catalog`` (плюс явный ``static``).  Отсутствие флага, неизвестная
    семья, дубликаты имён, расхождение ``feature_names``/каталога и lookback
    больше заявленного ``max_lookback`` отклоняются fail-closed.
    """
    if policy not in SUPPORTED_POLICIES:
        raise FeaturePlanError(f"Неподдерживаемая policy FeaturePlan: {policy!r}")
    if not isinstance(metadata, Mapping) or str(metadata.get("kind")) != "feature_generation":
        raise FeaturePlanError(
            "FeaturePlan строится только из metadata 'feature_generation'"
        )
    catalog = metadata.get("feature_catalog")
    if not isinstance(catalog, Sequence) or isinstance(catalog, (str, bytes)) or not catalog:
        raise FeaturePlanError(
            "metadata не содержит feature_catalog -- authoritative-источник ролей отсутствует"
        )
    source_column = str(metadata.get("source_column") or "")
    if not source_column:
        raise FeaturePlanError("metadata feature_generation без source_column")
    declared_max_lookback = int(metadata.get("max_lookback") or 0)

    names = [str(item) for item in (metadata.get("feature_names") or [])]
    catalog_names = [str(item.get("name") or "") for item in catalog]
    if len(set(catalog_names)) != len(catalog_names):
        duplicates = sorted({
            name for name in catalog_names
            if catalog_names.count(name) > 1
        })
        raise FeaturePlanError(
            f"Имена признаков должны быть уникальными; дубликаты: {duplicates}"
        )

    specs: list[FeatureSpec] = []
    for item in catalog:
        name = str(item.get("name") or "")
        if not name:
            raise FeaturePlanError("Запись feature_catalog без name")
        kind = str(item.get("family") or "")
        if kind not in SUPPORTED_KINDS:
            raise FeaturePlanError(
                f"Признак '{name}': неподдерживаемая семья '{kind}'; "
                f"разрешены {sorted(SUPPORTED_KINDS)}"
            )
        if "known_in_advance" not in item:
            raise FeaturePlanError(
                f"Признак '{name}': в feature_catalog нет флага known_in_advance -- "
                "роль роли не может быть выведена безопасно"
            )
        known_in_advance = bool(item["known_in_advance"])
        static = bool(item.get("static", False))
        if static and not known_in_advance:
            raise FeaturePlanError(
                f"Признак '{name}': static-роль требует known_in_advance=True"
            )
        if known_in_advance and static:
            role = ROLE_STATIC
        elif known_in_advance:
            role = ROLE_FUTURE_KNOWN
        else:
            role = ROLE_HISTORIC
        lookback = int(item.get("lookback") or 0)
        if lookback < 0:
            raise FeaturePlanError(f"Признак '{name}': отрицательный lookback {lookback}")
        params: dict[str, Any] = {}
        if kind == KIND_ROLLING:
            params = _rolling_params(name)
            lookback = int(params["window"])
        if kind == KIND_DIFFERENCE:
            match = _TRAILING_NUMBER_PATTERN.search(name)
            params = {"difference_lag": int(match.group(1)) if match else 1}
            lookback = max(lookback, int(params["difference_lag"]) + 1)
        if role == ROLE_HISTORIC and declared_max_lookback and lookback > declared_max_lookback:
            raise FeaturePlanError(
                f"Признак '{name}': lookback {lookback} превышает declared max_lookback "
                f"{declared_max_lookback} -- warm-up плана не сходится"
            )
        specs.append(FeatureSpec(
            name=name, kind=kind, role=role, lookback=lookback,
            params=params, source_column=source_column,
        ))

    if not names or names != catalog_names:
        raise FeaturePlanError(
            "feature_names расходится с feature_catalog -- stale-каталог запрещён; "
            "перестройте план по актуальной генерации признаков"
        )

    plan_id, fingerprint = _plan_identity(specs, policy=policy, source_column=source_column)
    return FeaturePlan(
        plan_id=plan_id, features=tuple(specs), policy=policy,
        fingerprint=fingerprint, source_column=source_column,
    )


def _regressor_spec(
    declaration: Mapping[str, Any], taken_names: set[str],
) -> FeatureSpec:
    """Валидировать одно объявление произвольного регрессора (fail-closed).

    Объявление -- это колонка датасета, подключаемая к supervised-моделям как
    fold-local регрессор.  Роль выводится из того же единственного авторитета,
    что и в каталоге генерации: ``known_in_advance`` (+явный ``static``).
    """
    if not isinstance(declaration, Mapping):
        raise FeaturePlanError(
            "Объявление регрессора должно быть объектом вида "
            "{column, known_in_advance, static?}"
        )
    name = str(declaration.get("column") or "")
    if not name:
        raise FeaturePlanError("Объявление регрессора без имени колонки (column)")
    if name in taken_names:
        raise FeaturePlanError(
            f"Регрессор '{name}': колонка уже входит в план признаков -- "
            "дубликаты имён запрещены"
        )
    if "known_in_advance" not in declaration:
        raise FeaturePlanError(
            f"Регрессор '{name}': отсутствует обязательный флаг known_in_advance -- "
            "роль не может быть выведена безопасно"
        )
    known_in_advance = bool(declaration["known_in_advance"])
    static = bool(declaration.get("static", False))
    if static and not known_in_advance:
        raise FeaturePlanError(
            f"Регрессор '{name}': static-роль требует known_in_advance=True"
        )
    if static:
        role = ROLE_STATIC
    elif known_in_advance:
        role = ROLE_FUTURE_KNOWN
    else:
        role = ROLE_HISTORIC
    return FeatureSpec(
        name=name, kind=KIND_EXOGENOUS, role=role, lookback=0,
        params={}, source_column="",
    )


def with_regressor_specs(
    plan: FeaturePlan,
    declarations: Sequence[Mapping[str, Any]],
    *,
    policy: Optional[str] = None,
) -> FeaturePlan:
    """Дополнить иммутабельный план произвольными регрессорами пользователя.

    Task 124 (финальная сертификация): произвольные fold-local regressors
    end-to-end.  Каждое объявление превращается в FeatureSpec
    (kind=exogenous) с ролью из known_in_advance/static; существующие фичи
    плана не изменяются, исходный план НЕ мутируется.  Дубликаты имён против
    каталога и внутри объявлений отклоняются fail-closed.  Возвращается
    НОВЫЙ FeaturePlan с пересчитанным plan_id/fingerprint -- cohort_id
    бэктестов автоматически меняется, reuse-логика инвалидирует старые
    артефакты.  Пустой список объявлений возвращает план без изменений.
    """
    resolved_policy = policy if policy is not None else plan.policy
    if resolved_policy not in SUPPORTED_POLICIES:
        raise FeaturePlanError(f"Неподдерживаемая policy FeaturePlan: {resolved_policy!r}")
    declarations = list(declarations or [])
    if not declarations:
        if resolved_policy == plan.policy:
            return plan
        return FeaturePlan(
            plan_id=plan.plan_id, features=plan.features,
            policy=resolved_policy, fingerprint=plan.fingerprint,
            source_column=plan.source_column,
        )
    taken_names = {spec.name for spec in plan.features}
    specs = list(plan.features)
    for declaration in declarations:
        spec = _regressor_spec(declaration, taken_names)
        specs.append(FeatureSpec(
            name=spec.name, kind=spec.kind, role=spec.role,
            lookback=spec.lookback, params=spec.params,
            source_column=plan.source_column,
        ))
        taken_names.add(spec.name)
    new_plan_id, new_fingerprint = _plan_identity(
        specs, policy=resolved_policy, source_column=plan.source_column,
    )
    return FeaturePlan(
        plan_id=new_plan_id, features=tuple(specs), policy=resolved_policy,
        fingerprint=new_fingerprint, source_column=plan.source_column,
    )


class RecursiveFeatureState:
    """Единый recursive-контракт для будущих supervised/ML-адаптеров.

    Хранит хвост train (и далее -- прогнозы модели) как единственный источник
    history.  ``next_row(prediction)`` строит строку historic-признаков для
    СЛЕДУЮЩЕЙ точки из текущей history, и только затем добавляет прогноз в
    историю: первая future-строка опирается на реальный хвост train, каждая
    последующая -- на прогнозы модели, но никогда на факты теста.  Параметр
    ``prediction`` -- это прогноз модели для следующей точки (становится
    историей для точки после неё), а не наблюдаемый факт.
    """

    def __init__(
        self,
        history: Sequence[float],
        columns: Sequence[str],
        specs: Mapping[str, FeatureSpec],
    ) -> None:
        self._history: list[float] = [float(value) for value in history]
        self._columns = tuple(columns)
        self._specs = dict(specs)

    def history(self) -> list[float]:
        """Копия history: внешняя мутация не влияет на состояние."""
        return list(self._history)

    def columns(self) -> list[str]:
        return list(self._columns)

    def _historic_value(self, spec: FeatureSpec, history: list[float]) -> float:
        lookback = int(spec.lookback)
        if spec.kind == KIND_LAG:
            if len(history) < lookback:
                return math.nan
            return history[-lookback]
        if spec.kind == KIND_ROLLING:
            if len(history) < lookback:
                return math.nan
            window = history[-lookback:]
            statistic = str(spec.params.get("statistic", "mean"))
            if statistic == "mean":
                return float(np.mean(window))
            if statistic == "std":
                return float(np.std(window, ddof=0))
            if statistic == "sum":
                return float(np.sum(window))
            if statistic == "min":
                return float(np.min(window))
            if statistic == "max":
                return float(np.max(window))
            raise FeaturePlanError(
                f"Признак '{spec.name}': неподдерживаемая rolling-статистика '{statistic}'"
            )
        if spec.kind == KIND_DIFFERENCE:
            lag = int(spec.params.get("difference_lag", 1))
            if len(history) < max(lag + 1, lookback):
                return math.nan
            return history[-lag] - history[-(lag + 1)]
        if spec.kind == KIND_EXOGENOUS:
            return math.nan
        raise FeaturePlanError(
            f"Признак '{spec.name}': kind '{spec.kind}' не является historic-трансформом"
        )

    def next_row(self, prediction: float) -> list[float]:
        """Строка historic-признаков следующей точки + push прогноза в history."""
        row: list[float] = []
        for name in self._columns:
            spec = self._specs[name]
            if spec.kind == KIND_EXOGENOUS:
                row.append(math.nan)
                continue
            row.append(self._historic_value(spec, self._history))
        self._history.append(float(prediction))
        return row


def _numeric_vector(
    values: Sequence[Any], *, name: str, expected_length: int,
    allow_nan: bool = False,
) -> list[float]:
    if len(values) != expected_length:
        raise FeaturePlanError(
            f"Платформенная колонка '{name}': длина {len(values)} не равна "
            f"длине ряда {expected_length}"
        )
    vector: list[float] = []
    for value in values:
        if isinstance(value, (str, bytes, bool)) or value is None:
            raise FeaturePlanError(
                f"Платформенная колонка '{name}': нечисловое значение {value!r}"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FeaturePlanError(
                f"Платформенная колонка '{name}': нечисловое значение {value!r}"
            ) from exc
        if not math.isfinite(number) and not allow_nan:
            raise FeaturePlanError(
                f"Платформенная колонка '{name}': NaN/Inf в future-known данных "
                "запрещены -- импутация известного будущего не определена"
            )
        vector.append(number)
    return vector


def _is_categorical(values: Sequence[Any]) -> bool:
    for value in values:
        if value is None or isinstance(value, (str, bool)):
            return True
        if isinstance(value, (int, float, np.integer, np.floating)):
            continue
        return True
    return False


def _rolling_statistic(window: Sequence[float], statistic: str) -> float:
    if statistic == "mean":
        return float(np.mean(window))
    if statistic == "std":
        return float(np.std(window, ddof=0))
    if statistic == "sum":
        return float(np.sum(window))
    if statistic == "min":
        return float(np.min(window))
    if statistic == "max":
        return float(np.max(window))
    raise FeaturePlanError(
        f"Неподдерживаемая rolling-статистика '{statistic}'"
    )


class FoldFeatureMatrixBuilder:
    """Fold-local построитель supervised-матриц по иммутабельному плану.

    Fresh-инстанс на каждый EDA-fold: все статистики (медианная импутация,
    scaler, one-hot категории) фитуются строго на train-срезе ЭТОГО fold'а и
    не разделяются между fold'ами.  Derived-признаки пересчитываются каузально
    внутри train-среза (лаг/окно никогда не включает y[t]); future-канал
    строится ТОЛЬКО из future_known/static платформенных колонок --
    материализовать historic-признак будущего через этот API невозможно.
    """

    def __init__(self, plan: FeaturePlan, *, scale_exogenous: bool = False) -> None:
        self._plan = plan
        self._scale_exogenous = bool(scale_exogenous)
        self._fitted = False
        self._observation_indices: list[int] = []
        self._matrix_columns: list[str] = []
        self._matrix_rows: list[list[float]] = []
        self._target: list[float] = []
        self._future_columns: list[str] = []
        self._future_rows: list[list[float]] = []
        self._known_train: dict[str, list[float]] = {}
        self._train_history: list[float] = []
        self._future_positions: list[int] = []
        self._exogenous_train: dict[str, list[float]] = {}
        self._known_train_rows: list[list[float]] = []
        self._statistics: dict[str, Any] = {"imputer": None, "scaler": None, "encoder": None}

    # -- служебное ---------------------------------------------------------
    @property
    def plan(self) -> FeaturePlan:
        return self._plan

    def statistics(self) -> dict[str, Any]:
        """Fold-local статистика трансформеров (для аудита fold-local fit)."""
        return {
            "imputer": dict(self._statistics["imputer"]) if self._statistics["imputer"] else None,
            "scaler": dict(self._statistics["scaler"]) if self._statistics["scaler"] else None,
            "encoder": dict(self._statistics["encoder"]) if self._statistics["encoder"] else None,
        }

    def _platform_column(
        self, name: str, feature_columns: Mapping[str, Sequence[Any]], n: int,
    ) -> Sequence[Any]:
        if name not in feature_columns:
            raise FeaturePlanError(
                f"Платформенная колонка '{name}' отсутствует в feature_columns: "
                "план требует материализованные колонки датасета"
            )
        return feature_columns[name]

    def fit_fold(
        self,
        values: Sequence[float],
        labels: Sequence[str],
        fold: "BacktestFoldPlan",
        *,
        feature_columns: Optional[Mapping[str, Sequence[Any]]] = None,
    ) -> "FoldFeatureMatrixBuilder":
        if self._fitted:
            raise FeaturePlanError(
                "FoldFeatureMatrixBuilder одноразовый: создайте fresh-инстанс на каждый fold"
            )
        values = [float(value) for value in values]
        n = len(values)
        if len(labels) != n:
            raise FeaturePlanError("labels и ряд должны совпадать по длине")
        if not np.isfinite(np.asarray(values, dtype=float)).all():
            raise FeaturePlanError("Ряд содержит NaN/Inf")
        columns = dict(feature_columns or {})
        train_indices = list(fold.train_indices)
        test_indices = list(fold.test_indices)
        if not train_indices or not test_indices:
            raise FeaturePlanError("Fold без train/test-индексов не исполним")
        future_positions = list(range(train_indices[-1] + 1, test_indices[-1] + 1))
        train_slice = [values[index] for index in train_indices]
        specs = self._plan.feature_by_name()

        derived: dict[str, list[float]] = {}      # historic derived (per observation)
        historic_exog: dict[str, list[float]] = {}  # numeric exogenous historic
        known_train: dict[str, list[float]] = {}  # future_known/static numeric train slice
        known_future: dict[str, list[float]] = {}  # same, future positions
        one_hot_train: dict[str, list[list[float]]] = {}
        one_hot_future: dict[str, list[list[float]]] = {}
        encoder_stats: dict[str, Any] = {}
        imputer_stats: dict[str, float] = {}
        scaler_stats: dict[str, dict[str, float]] = {}

        for spec in self._plan.features:
            if spec.role != ROLE_HISTORIC:
                continue
            if spec.kind in TARGET_DERIVED_KINDS:
                derived[spec.name] = self._derived_column(spec, train_slice)
                continue
            if spec.kind == KIND_EXOGENOUS:
                raw = self._platform_column(spec.name, columns, n)
                if _is_categorical(raw):
                    raise FeaturePlanError(
                        f"Признак '{spec.name}': категориальная historic-экзогена с "
                        "unknown future не поддерживается (известная в будущем -- "
                        "пометьте known_in_advance=True)"
                    )
                column = _numeric_vector(
                    raw, name=spec.name, expected_length=n, allow_nan=True,
                )
                train_values = [column[index] for index in train_indices]
                train_values, medians = self._impute_train(train_values, spec.name)
                imputer_stats.update(medians)
                if self._scale_exogenous:
                    train_values, scale = self._scale_train(train_values, spec.name)
                    scaler_stats[spec.name] = scale
                historic_exog[spec.name] = train_values
                self._exogenous_train[spec.name] = train_values
                continue
            raise FeaturePlanError(
                f"Признак '{spec.name}': kind '{spec.kind}' в historic-роли не поддерживается"
            )

        for spec in self._plan.features:
            if spec.role == ROLE_HISTORIC:
                continue
            if spec.name not in columns:
                if spec.kind in {KIND_CALENDAR, KIND_TREND, KIND_FOURIER} or spec.role == ROLE_STATIC:
                    raise FeaturePlanError(
                        f"Платформенная колонка '{spec.name}' отсутствует в feature_columns: "
                        "детерминированная временная ось и static-роли обязаны быть "
                        "материализованы платформой"
                    )
                # Exogenous без материализованной колонки: признак недоступен
                # в этом fold'е и исключается целиком (не попадает ни в train,
                # ни в future-канал) -- частичный план безопаснее выдуманной колонки.
                continue
            raw = columns[spec.name]
            if spec.role == ROLE_STATIC:
                # Static-константность проверяется ДО any-кодировки: и строковые,
                # и числовые static-колонки обязаны быть постоянны в train-срезе.
                train_raw = [raw[index] for index in train_indices]
                first = train_raw[0]
                for value in train_raw[1:]:
                    if isinstance(first, (int, float, np.integer, np.floating)) \
                            and not isinstance(first, bool):
                        if abs(float(value) - float(first)) > 1e-12:
                            raise FeaturePlanError(
                                f"Static-колонка '{spec.name}' не константа внутри "
                                "train-среза fold: static-роль требует построчного постоянства"
                            )
                    elif value != first:
                        raise FeaturePlanError(
                            f"Static-колонка '{spec.name}' не константа внутри "
                            "train-среза fold: static-роль требует построчного постоянства"
                        )
            if _is_categorical(raw):
                categories = self._train_categories(raw, train_indices, spec.name)
                encoder_stats[spec.name] = list(categories)
                train_rows = self._one_hot(
                    [raw[index] for index in train_indices], categories, spec.name,
                )
                future_rows = self._one_hot(
                    [raw[index] for index in future_positions], categories, spec.name,
                )
                one_hot_train[spec.name] = train_rows
                one_hot_future[spec.name] = future_rows
                continue
            column = _numeric_vector(raw, name=spec.name, expected_length=n)
            known_train[spec.name] = [column[index] for index in train_indices]
            known_future[spec.name] = [column[index] for index in future_positions]

        # -- матрицы ---------------------------------------------------------
        warmup = self._plan.max_lookback
        usable = warmup if warmup < len(train_indices) else len(train_indices)
        self._observation_indices = train_indices[usable:]
        self._target = [values[index] for index in self._observation_indices]
        offset = usable
        matrix_columns: list[str] = []
        rows: list[list[float]] = [[] for _ in self._observation_indices]
        for spec in self._plan.features:
            if spec.role != ROLE_HISTORIC:
                continue
            if spec.name in derived:
                column_values = derived[spec.name]
            else:
                column_values = historic_exog[spec.name]
            matrix_columns.append(spec.name)
            for row, value in zip(rows, column_values[offset:], strict=True):
                row.append(float(value))
        for spec in self._plan.features:
            if spec.role == ROLE_HISTORIC or spec.name not in one_hot_train:
                continue
            matrix_columns.extend(f"{spec.name}={category}" for category in encoder_stats[spec.name])
            for row, encoded in zip(rows, one_hot_train[spec.name][offset:], strict=True):
                row.extend(float(value) for value in encoded)
        self._matrix_columns = matrix_columns
        self._matrix_rows = rows

        future_columns: list[str] = []
        future_rows: list[list[float]] = [[] for _ in future_positions]
        for spec in self._plan.features:
            if spec.role == ROLE_HISTORIC:
                continue
            if spec.name in known_train:
                future_columns.append(spec.name)
                for row, value in zip(future_rows, known_future[spec.name], strict=True):
                    row.append(float(value))
        for spec in self._plan.features:
            if spec.role == ROLE_HISTORIC or spec.name not in one_hot_future:
                continue
            future_columns.extend(f"{spec.name}={category}" for category in encoder_stats[spec.name])
            for row, encoded in zip(future_rows, one_hot_future[spec.name], strict=True):
                row.extend(float(value) for value in encoded)
        self._future_columns = future_columns
        self._future_rows = future_rows if future_columns else []
        self._known_train = known_train
        # Train-срез будущих-known/static колонок в той же кодировке, что и
        # future_matrix (числовые -- как есть, категориальные -- one-hot):
        # регрессоры адаптера обязаны покрывать train и future симметрично.
        self._known_train_rows = [
            [
                *(known_train[spec.name][position] for spec in self._plan.features
                  if spec.role != ROLE_HISTORIC and spec.name in known_train),
                *(value for spec in self._plan.features
                  if spec.name in one_hot_train
                  for value in one_hot_train[spec.name][position]),
            ]
            for position in range(len(train_indices))
        ]
        self._future_positions = future_positions
        self._train_history = train_slice
        self._statistics = {
            "imputer": imputer_stats or None,
            "scaler": scaler_stats or None,
            "encoder": encoder_stats or None,
        }
        self._fitted = True
        return self

    def _derived_column(self, spec: FeatureSpec, train_slice: list[float]) -> list[float]:
        lookback = int(spec.lookback)
        column: list[float] = []
        for position in range(len(train_slice)):
            if spec.kind == KIND_LAG:
                if position < lookback:
                    column.append(math.nan)
                else:
                    column.append(train_slice[position - lookback])
                continue
            if spec.kind == KIND_ROLLING:
                if position < lookback:
                    column.append(math.nan)
                else:
                    statistic = str(spec.params.get("statistic", "mean"))
                    column.append(_rolling_statistic(
                        train_slice[position - lookback : position], statistic,
                    ))
                continue
            if spec.kind == KIND_DIFFERENCE:
                lag = int(spec.params.get("difference_lag", 1))
                if position < max(lag + 1, lookback):
                    column.append(math.nan)
                else:
                    column.append(
                        train_slice[position - lag] - train_slice[position - lag - 1]
                    )
                continue
            raise FeaturePlanError(
                f"Признак '{spec.name}': kind '{spec.kind}' не является historic-трансформом"
            )
        return column

    @staticmethod
    def _impute_train(train_values: list[float], name: str) -> tuple[list[float], dict[str, float]]:
        array = np.asarray(train_values, dtype=float)
        if np.isfinite(array).all():
            return train_values, {}
        median = float(np.nanmedian(array))
        if not math.isfinite(median):
            raise FeaturePlanError(
                f"Колонка '{name}': train-срез не содержит ни одного конечного значения "
                "-- медианная импутация невозможна"
            )
        return [median if not math.isfinite(value) else value for value in train_values], {
            name: median,
        }

    @staticmethod
    def _scale_train(train_values: list[float], name: str) -> tuple[list[float], dict[str, float]]:
        array = np.asarray(train_values, dtype=float)
        mean = float(np.mean(array))
        std = float(np.std(array, ddof=0))
        if std <= np.finfo(float).eps:
            return [0.0 for _ in train_values], {"mean": mean, "std": std}
        return [(value - mean) / std for value in train_values], {"mean": mean, "std": std}

    @staticmethod
    def _train_categories(
        raw: Sequence[Any], train_indices: Sequence[int], name: str,
    ) -> list[str]:
        categories: list[str] = []
        for index in train_indices:
            value = raw[index]
            text = str(value)
            if text not in categories:
                categories.append(text)
        if not categories:
            raise FeaturePlanError(f"Колонка '{name}': пустой train-срез категорий")
        return categories

    @staticmethod
    def _one_hot(
        values: Sequence[Any], categories: Sequence[str], name: str,
    ) -> list[list[float]]:
        rows: list[list[float]] = []
        for value in values:
            text = str(value)
            if text not in categories:
                # Unknown future-категория -- вектор из нулей (fold-2 encoder
                # может знать больше категорий; train-кодировка не подменяется).
                rows.append([0.0] * len(categories))
                continue
            rows.append([1.0 if category == text else 0.0 for category in categories])
        return rows

    # -- публичные срезы ----------------------------------------------------
    def train_matrix(self) -> dict[str, Any]:
        """Supervised-матрица train-среза (без warm-up наблюдений)."""
        self._ensure_fitted()
        return {
            "columns": list(self._matrix_columns),
            "rows": [list(row) for row in self._matrix_rows],
            "observation_indices": list(self._observation_indices),
            "target": list(self._target),
        }

    def future_matrix(self) -> dict[str, Any]:
        """Матрица будущего: ТОЛЬКО future_known/static (historic запрещены)."""
        self._ensure_fitted()
        return {
            "columns": list(self._future_columns),
            "rows": [list(row) for row in self._future_rows],
        }

    def train_known_matrix(self) -> dict[str, Any]:
        """Train-срез будущих-known/static колонок (без warm-up дропа)."""
        self._ensure_fitted()
        return {
            "columns": list(self._future_columns),
            "rows": [list(row) for row in self._known_train_rows],
        }

    def recursive_state(self) -> Optional[RecursiveFeatureState]:
        """Рекурсивный контракт: None для плана без historic-признаков."""
        self._ensure_fitted()
        if self._plan.policy == POLICY_NONE:
            return None
        specs = self._plan.feature_by_name()
        historic = [
            spec.name for spec in self._plan.features if spec.role == ROLE_HISTORIC
        ]
        if not historic:
            return None
        return RecursiveFeatureState(
            self._train_history,
            historic,
            specs,
        )

    def matrix_hash(self) -> Optional[str]:
        """Точный hash train-матрицы fold'а (None для пустого плана)."""
        self._ensure_fitted()
        if not self._matrix_columns and not self._future_columns:
            return None
        return _digest({
            "plan_id": self._plan.plan_id,
            "columns": self._matrix_columns,
            "rows": self._matrix_rows,
            "observation_indices": self._observation_indices,
            "target": self._target,
        })

    def lineage_record(self, *, fold: int) -> dict[str, Any]:
        """Аудиторская привязка план+fold+матрица (в fold-запись бэктеста)."""
        self._ensure_fitted()
        return {
            "fold": int(fold),
            "plan_id": self._plan.plan_id,
            "fingerprint": self._plan.fingerprint,
            "matrix_hash": self.matrix_hash(),
            "columns": list(self._matrix_columns),
            "future_known_columns": list(self._future_columns),
            "fit_policy": "per_train_fold",
            "scale_exogenous": self._scale_exogenous,
        }

    def _ensure_fitted(self) -> None:
        if not self._fitted:
            raise FeaturePlanError("FoldFeatureMatrixBuilder не фитован: вызовите fit_fold")


def bind_feature_importance(
    lineage: Mapping[str, Any], importances: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Привязать importance к ТОЧНОЙ fold-матрице (oracle-защита).

    Каждое имя признака обязано входить в колонки той самой матрицы, hash
    которой записан в lineage; чужие колонки отклоняются -- импортанс,
    посчитанный по другой матрице, не может выдаваться за importance этого fold'а.
    """
    valid = set(lineage.get("columns") or []) | set(lineage.get("future_known_columns") or [])
    records: list[dict[str, Any]] = []
    for item in importances:
        name = str(item.get("feature_name") or "")
        if name not in valid:
            raise FeaturePlanError(
                f"Feature importance '{name}' не входит в колонки fold-матрицы "
                f"(matrix_hash={lineage.get('matrix_hash')}): привязка невозможна"
            )
        records.append({
            "feature_name": name,
            "importance": float(item.get("importance") or 0.0),
        })
    return {
        "version": FEATURE_PLAN_CONTRACT_VERSION,
        "plan_id": lineage.get("plan_id"),
        "fold": lineage.get("fold"),
        "matrix_hash": lineage.get("matrix_hash"),
        "fit_policy": lineage.get("fit_policy"),
        "importances": records,
    }
