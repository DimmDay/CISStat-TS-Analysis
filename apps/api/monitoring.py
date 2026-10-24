# apps/api/monitoring.py
"""
DOCLOG-8 (spec_documentation_logging.md §6 D12, §6.1 мониторинг, §19
строка DOCLOG-8, B07/F11, AC12/AC15): контур мониторинга -- D12 «Сверка
прогноза с фактом»: frozen forecast vintage, actual vintages,
выравнивание, честные оценки, revisions/threshold decisions.

ПОСТАНОВКА (§19, строка DOCLOG-8): «D12: frozen forecast и actual
vintages, выравнивание, оценки, revisions/threshold decisions».
Критерий завершения: «поздний факт и revise не переписывают старый
выпуск/OOF».

КОНТРАКТ:
- Forecast vintage -- ЗАМОРОЖЕННЫЙ артефакт kind="forecast" (D08):
  сверка читает его payload с проверкой целостности байтов (T8) и НИКОГДА
  не изменяет артефакт (§6 D08: «никогда не заменять старый выпуск
  новым»). Прогноз не пересчитывается (§19.1: без повторного fit).
- Actual vintage -- ИММУТАБЕЛЬНАЯ партия фактических значений
  (doclog.actual_vintage/1): «фиксировать дату поступления/редакцию
  факта и единицы» (B07). Пересмотр факта = НОВАЯ партия; старые партии
  не переписываются и не удаляются (AC15).
- Сверка (doclog.monitoring_comparison/1) -- frozen вычисление НА
  МОМЕНТ сборки: выравнивание по метке периода, ТОЛЬКО зрелые горизонты
  (§6.1: «ещё не наступившие горизонты не получают нулевую ошибку» --
  незрелые исключены ЯВНО со списком меток), единицы (as_is/converted/
  unknown; несовпадение без явной конверсии -- отказ с причиной, AC15),
  честные метрики (AC12: MAPE с нулями факта / MASE без scale / нет
  зрелых горизонтов -- null + reason, НЕ 0), порог -- ФАКТ
  (exceeded/within/not_evaluable).
- Решение -- отдельная append-only запись человека
  (doclog.monitoring_decision/1): «Автопереобучение не следует из
  превышения порога без отдельного решения» (§6.1); decision_action в
  результате сверки всегда null; «retrain_requested» -- ЗАПРОС
  (запись), не автоматическое действие.
- Сверка -- read-only над научным слоем (AC05-дух): реестр артефактов,
  ledger run и OOF не мутируют; аудируются стандартными записями
  (§8: mandatory -- только публикация/approval/выдача защищённых
  данных).

ИДЕМПОТЕНТНОСТЬ (§10.3/AC09): UNIQUE(run_id, idempotency_key) для
партий и сверок; тот же ключ с другим телом -- конфликт, не тихий дубль.

РЕЕСТР: ABC + Memory + Postgres (структурный паритет, урок F-D2C1);
бэкенд CISSTAT_MONITORING_BACKEND (memory по умолчанию; postgres по
DATABASE_URL); миграция 0014 -- аддитивная.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# ── Версии схем (§7: версионированные контракты) ─────────────────────

MONITORING_SCHEMA_VERSION = "doclog.monitoring/1"
ACTUAL_VINTAGE_SCHEMA_VERSION = "doclog.actual_vintage/1"
COMPARISON_SCHEMA_VERSION = "doclog.monitoring_comparison/1"
DECISION_SCHEMA_VERSION = "doclog.monitoring_decision/1"
RESULT_SCHEMA_VERSION = "doclog.monitoring_result/1"

# §6.1: решение -- отдельное действие человека; каталог действий
# фиксирован (fail-closed), «retrain_requested» -- запрос, не действие.
DECISION_ACTIONS: frozenset[str] = frozenset(
    {"none", "accept", "investigate", "retrain_requested"}
)

# Порог -- политика задачи (§6.1: «порог качества -- политика задачи,
# не универсальная константа»): метрика/оператор/значение от вызывающего.
THRESHOLD_METRICS: frozenset[str] = frozenset(
    {"mae", "mape", "bias_abs", "mase"}
)
THRESHOLD_OPERATORS: frozenset[str] = frozenset({">", ">="})

SOURCE_KINDS: frozenset[str] = frozenset({"manual", "artifact"})

MONITORING_BACKEND_ENV = "CISSTAT_MONITORING_BACKEND"

# §18: страницы списков <=100 элементов (пилотный предел).
DEFAULT_LIST_LIMIT = 100


# ── Ошибки контура (HTTP-маппинг -- routers/monitoring.py) ───────────


class MonitoringError(RuntimeError):
    """Базовая ошибка контура мониторинга."""


class MonitoringValidationError(MonitoringError, ValueError):
    """Некорректный запрос/данные (422-семантика §17)."""


class MonitoringUnitsMismatchError(MonitoringError, ValueError):
    """AC15: единицы прогноза и факта не совпали без явной конверсии --
    отказ с причиной; сверка НЕ строится на разных единицах."""


class MonitoringForecastUnavailable(MonitoringError):
    """Прогноз недоступен: не найден / чужой / битые байты (T8) / не тот
    kind -- честный отказ без выдуманных чисел."""


class MonitoringAccessDenied(MonitoringError):
    """Знание идентификатора НЕ является правом (T7/T15): чужой
    артефакт/run -- отказ."""


class MonitoringIdempotencyConflictError(MonitoringError):
    """§10.3/AC09: тот же idempotency_key с другим телом -- конфликт."""


class MonitoringNotFoundError(MonitoringError):
    """Сверка/партия не найдены в границах run (404-семантика)."""


# ── Идентификаторы и вспомогательные ─────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_bytes(payload: Any) -> bytes:
    """Канонический JSON (паритет report_snapshot.canonical_json_bytes):
    sort_keys, компактные разделители, ensure_ascii=False."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def request_fingerprint(body: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _is_finite_number(value: Any) -> bool:
    """Число (не bool), конечное -- NaN/Infinity отвергаются (§7: без
    NaN/Infinity в контрактах)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _parse_as_of(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MonitoringValidationError(
            "as_of: требуется непустая ISO-метка времени поступления факта"
        )
    try:
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MonitoringValidationError(
            f"as_of: некорректная ISO-метка времени: {value!r}"
        ) from exc
    return parsed


# ── Записи ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActualBatchRecord:
    """Actual vintage (B07): иммутабельная партия фактических значений
    с датой поступления и единицами. Пересмотр -- новая запись."""

    batch_id: str
    run_id: str
    tenant_id: Optional[str]
    target_name: str
    entity_id: Optional[str]
    units: str
    as_of: str
    source_kind: str
    source_ref: Optional[str]
    notes: str
    values: tuple[dict[str, Any], ...]
    point_count: int
    schema_version: str = ACTUAL_VINTAGE_SCHEMA_VERSION
    idempotency_key: str = ""
    request_fingerprint: str = ""
    created_by: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "target_name": self.target_name,
            "entity_id": self.entity_id,
            "units": self.units,
            "as_of": self.as_of,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "notes": self.notes,
            "values": list(self.values),
            "point_count": self.point_count,
            "schema_version": self.schema_version,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ComparisonRecord:
    """Сверка (§6 D12): frozen результат над forecast vintage x actual
    vintage. Иммутабельна: revise создаёт НОВУЮ запись (§19)."""

    comparison_id: str
    run_id: str
    tenant_id: Optional[str]
    forecast_artifact_id: str
    forecast_sha256: str
    actual_batch_id: str
    target_name: str
    entity_id: Optional[str]
    units_check: str
    units_note: str
    status: str
    matured_count: int
    excluded_count: int
    out_of_horizon_count: int
    result: dict[str, Any]
    payload_sha256: str
    schema_version: str = COMPARISON_SCHEMA_VERSION
    idempotency_key: str = ""
    request_fingerprint: str = ""
    created_by: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "forecast_artifact_id": self.forecast_artifact_id,
            "forecast_sha256": self.forecast_sha256,
            "actual_batch_id": self.actual_batch_id,
            "target_name": self.target_name,
            "entity_id": self.entity_id,
            "units_check": self.units_check,
            "units_note": self.units_note,
            "status": self.status,
            "matured_count": self.matured_count,
            "excluded_count": self.excluded_count,
            "out_of_horizon_count": self.out_of_horizon_count,
            "result": self.result,
            "payload_sha256": self.payload_sha256,
            "schema_version": self.schema_version,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class MonitoringDecisionRecord:
    """Решение человека по сверке (§6.1): append-only, с основанием."""

    decision_id: str
    run_id: str
    tenant_id: Optional[str]
    comparison_id: str
    action: str
    rationale: str
    schema_version: str = DECISION_SCHEMA_VERSION
    decided_by: Optional[str] = None
    decided_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "comparison_id": self.comparison_id,
            "action": self.action,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
        }


# ── Чистая функция сверки (ядро выравнивания/метрик) ─────────────────


def compute_comparison_result(
    forecast_payload: dict[str, Any],
    actual_values: list[dict[str, Any]],
    *,
    units_factor: float = 1.0,
    threshold: Optional[dict[str, Any]] = None,
    mase_scale: Optional[float] = None,
) -> dict[str, Any]:
    """Выравнивание forecast points x actual values + честные метрики.

    - Совпадение -- точное по метке периода (strip с обеих сторон).
    - Незрелые горизонты (прогноз без факта) -- excluded_labels, НЕ пары
      с нулевой ошибкой (§6.1).
    - ape = |signed_error / actual|; actual == 0 -- null + reason
      «actual_zero» (AC12).
    - mape -- среднее ape ТОЛЬКО если все зрелые ape определены; иначе
      null + reason + список нулевых периодов.
    - mase -- mean(abs_error)/scale при явном scale > 0; без scale --
      null + «mase_scale_required»; scale <= 0 -- null +
      «mase_scale_invalid» (чистая функция; сервис отвергает вход
      ранее).
    - interval_hit -- ci_lower <= actual <= ci_upper при наличии обеих
      границ; иначе null.
    - threshold -- ФАКТ (exceeded/within/not_evaluable), НЕ действие;
      decision_action всегда null (§6.1: без автопереобучения).
    """
    points = forecast_payload.get("points")
    if not isinstance(points, list):
        points = []
    actual_by_period: dict[str, float] = {}
    for entry in actual_values:
        period = str(entry.get("period", "")).strip()
        value = float(entry.get("value"))
        actual_by_period[period] = value

    pairs: list[dict[str, Any]] = []
    excluded_labels: list[str] = []
    matched_periods: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        date = str(point.get("date", "")).strip()
        forecast_value = float(point.get("value"))
        if date in actual_by_period:
            matched_periods.add(date)
            actual_value = actual_by_period[date] * float(units_factor)
            signed_error = actual_value - forecast_value
            absolute_error = abs(signed_error)
            if actual_value == 0:
                ape: Optional[float] = None
                ape_reason: Optional[str] = "actual_zero"
            else:
                ape = absolute_error / abs(actual_value)
                ape_reason = None
            lower = point.get("ci_lower")
            upper = point.get("ci_upper")
            if _is_finite_number(lower) and _is_finite_number(upper):
                interval_hit: Optional[bool] = (
                    float(lower) <= actual_value <= float(upper)
                )
            else:
                interval_hit = None
            pairs.append(
                {
                    "step": point.get("step"),
                    "date": date,
                    "forecast_value": forecast_value,
                    "actual_value": actual_value,
                    "signed_error": signed_error,
                    "absolute_error": absolute_error,
                    "ape": ape,
                    "ape_undefined_reason": ape_reason,
                    "interval_hit": interval_hit,
                }
            )
        else:
            # Незрелый горизонт: НЕ нулевая ошибка -- явное исключение.
            excluded_labels.append(date)

    out_of_horizon_labels = sorted(
        period for period in actual_by_period if period not in matched_periods
    )
    matured_count = len(pairs)

    aggregates: dict[str, Any] = {}
    if matured_count == 0:
        aggregates.update(
            {
                "mae": None,
                "mae_reason": "no_matured_horizons",
                "mean_signed_error": None,
                "mean_signed_error_reason": "no_matured_horizons",
                "mape": None,
                "mape_reason": "no_matured_horizons",
                "mape_zero_periods": [],
                "mase": None,
                "mase_reason": "no_matured_horizons",
                "interval_hits": 0,
                "interval_coverage": None,
                "interval_coverage_reason": "no_matured_horizons",
            }
        )
    else:
        abs_errors = [pair["absolute_error"] for pair in pairs]
        signed_errors = [pair["signed_error"] for pair in pairs]
        mae = sum(abs_errors) / matured_count
        mean_signed = sum(signed_errors) / matured_count
        zero_periods = [
            pair["date"]
            for pair in pairs
            if pair["ape_undefined_reason"] == "actual_zero"
        ]
        apes = [pair["ape"] for pair in pairs if pair["ape"] is not None]
        if len(apes) == matured_count:
            mape: Optional[float] = sum(apes) / matured_count
            mape_reason: Optional[str] = None
        else:
            mape = None
            mape_reason = "mape_undefined_actual_zero"
        if mase_scale is None:
            mase: Optional[float] = None
            mase_reason: Optional[str] = "mase_scale_required"
        elif mase_scale <= 0:
            mase = None
            mase_reason = "mase_scale_invalid"
        else:
            mase = mae / float(mase_scale)
            mase_reason = None
        hits = sum(1 for pair in pairs if pair["interval_hit"] is True)
        defined_hits = sum(
            1 for pair in pairs if pair["interval_hit"] is not None
        )
        if defined_hits == matured_count:
            coverage: Optional[float] = hits / matured_count
            coverage_reason: Optional[str] = None
        else:
            coverage = None
            coverage_reason = "interval_bounds_missing"
        aggregates.update(
            {
                "mae": mae,
                "mae_reason": None,
                "mean_signed_error": mean_signed,
                "mean_signed_error_reason": None,
                "mape": mape,
                "mape_reason": mape_reason,
                "mape_zero_periods": zero_periods,
                "mase": mase,
                "mase_reason": mase_reason,
                "interval_hits": hits,
                "interval_coverage": coverage,
                "interval_coverage_reason": coverage_reason,
            }
        )

    threshold_result: Optional[dict[str, Any]] = None
    if threshold is not None:
        metric = str(threshold.get("metric"))
        operator = str(threshold.get("operator"))
        metric_aggregate: Optional[float]
        if metric == "mae":
            metric_aggregate = aggregates["mae"]
            metric_reason = aggregates["mae_reason"]
        elif metric == "mape":
            metric_aggregate = aggregates["mape"]
            metric_reason = aggregates["mape_reason"]
        elif metric == "bias_abs":
            bias = aggregates["mean_signed_error"]
            metric_aggregate = (
                abs(bias) if bias is not None else None
            )
            metric_reason = aggregates["mean_signed_error_reason"]
        else:  # "mase"
            metric_aggregate = aggregates["mase"]
            metric_reason = aggregates["mase_reason"]
        if metric_aggregate is None:
            threshold_result = {
                "metric": metric,
                "operator": operator,
                "value": float(threshold.get("value")),
                "label": str(threshold.get("label", "")),
                "status": "not_evaluable",
                "reason": metric_reason,
            }
        else:
            exceeded = (
                metric_aggregate > float(threshold.get("value"))
                if operator == ">"
                else metric_aggregate >= float(threshold.get("value"))
            )
            threshold_result = {
                "metric": metric,
                "operator": operator,
                "value": float(threshold.get("value")),
                "label": str(threshold.get("label", "")),
                "status": "exceeded" if exceeded else "within",
                "reason": None,
            }

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "forecast_origin": {
            "horizon": forecast_payload.get("horizon"),
            "alpha": forecast_payload.get("alpha"),
            "point_count": len(points),
        },
        "alignment": {
            "key": "period_label_exact",
            "matured_count": matured_count,
            "excluded_count": len(excluded_labels),
            "excluded_labels": excluded_labels,
            "out_of_horizon_count": len(out_of_horizon_labels),
            "out_of_horizon_labels": out_of_horizon_labels,
        },
        "pairs": pairs,
        "aggregates": aggregates,
        "threshold": threshold_result,
        # §6.1: решение -- отдельная запись человека, не свойство сверки.
        "decision_action": None,
    }


# ── Реестр: ABC + Memory + Postgres (паритет DOCLOG-6/7) ────────────


class MonitoringRegistry(ABC):
    """Дurable-реестр контура мониторинга (§8.1: тот же Postgres)."""

    # Actual batches (vintages)
    @abstractmethod
    def save_actual_batch(self, record: ActualBatchRecord) -> ActualBatchRecord: ...

    @abstractmethod
    def get_actual_batch(self, batch_id: str) -> Optional[ActualBatchRecord]: ...

    @abstractmethod
    def list_actual_batches(self, run_id: str, limit: int = DEFAULT_LIST_LIMIT) -> list[ActualBatchRecord]: ...

    @abstractmethod
    def find_actual_batch_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ActualBatchRecord]: ...

    # Comparisons
    @abstractmethod
    def save_comparison(self, record: ComparisonRecord) -> ComparisonRecord: ...

    @abstractmethod
    def get_comparison(self, comparison_id: str) -> Optional[ComparisonRecord]: ...

    @abstractmethod
    def list_comparisons(self, run_id: str, limit: int = DEFAULT_LIST_LIMIT) -> list[ComparisonRecord]: ...

    @abstractmethod
    def find_comparison_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ComparisonRecord]: ...

    # Decisions (append-only)
    @abstractmethod
    def save_decision(self, record: MonitoringDecisionRecord) -> MonitoringDecisionRecord: ...

    @abstractmethod
    def list_decisions(self, run_id: str, comparison_id: str) -> list[MonitoringDecisionRecord]: ...


class MemoryMonitoringRegistry(MonitoringRegistry):
    """In-memory реестр (тесты/dev; паритет Memory-контуров DOCLOG-4)."""

    def __init__(self) -> None:
        self._batches: dict[str, ActualBatchRecord] = {}
        self._comparisons: dict[str, ComparisonRecord] = {}
        self._decisions: dict[str, MonitoringDecisionRecord] = {}
        self._lock = threading.Lock()

    def save_actual_batch(self, record: ActualBatchRecord) -> ActualBatchRecord:
        with self._lock:
            self._batches[record.batch_id] = record
        return record

    def get_actual_batch(self, batch_id: str) -> Optional[ActualBatchRecord]:
        return self._batches.get(batch_id)

    def list_actual_batches(
        self, run_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ActualBatchRecord]:
        items = [b for b in self._batches.values() if b.run_id == run_id]
        items.sort(key=lambda b: (b.created_at, b.batch_id))
        return items[: max(0, int(limit))]

    def find_actual_batch_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ActualBatchRecord]:
        if not idempotency_key:
            return None
        for record in self._batches.values():
            if (
                record.run_id == run_id
                and record.idempotency_key == idempotency_key
            ):
                return record
        return None

    def save_comparison(self, record: ComparisonRecord) -> ComparisonRecord:
        with self._lock:
            self._comparisons[record.comparison_id] = record
        return record

    def get_comparison(self, comparison_id: str) -> Optional[ComparisonRecord]:
        return self._comparisons.get(comparison_id)

    def list_comparisons(
        self, run_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ComparisonRecord]:
        items = [c for c in self._comparisons.values() if c.run_id == run_id]
        items.sort(key=lambda c: (c.created_at, c.comparison_id))
        return items[: max(0, int(limit))]

    def find_comparison_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ComparisonRecord]:
        if not idempotency_key:
            return None
        for record in self._comparisons.values():
            if (
                record.run_id == run_id
                and record.idempotency_key == idempotency_key
            ):
                return record
        return None

    def save_decision(
        self, record: MonitoringDecisionRecord
    ) -> MonitoringDecisionRecord:
        with self._lock:
            self._decisions[record.decision_id] = record
        return record

    def list_decisions(
        self, run_id: str, comparison_id: str
    ) -> list[MonitoringDecisionRecord]:
        items = [
            d
            for d in self._decisions.values()
            if d.run_id == run_id and d.comparison_id == comparison_id
        ]
        items.sort(key=lambda d: (d.decided_at, d.decision_id))
        return items


class PostgresMonitoringRegistry(MonitoringRegistry):
    """Durable-реестр (миграция 0014 на первом коннекте; ленивый
    psycopg -- паритет durable-контуров DOCLOG-1/2/4/6/7)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresMonitoringRegistry":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for"
                " PostgresMonitoringRegistry."
            )
        return PostgresMonitoringRegistry(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- паритет durable-контуров

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    @staticmethod
    def _row_to_batch(row: Any) -> ActualBatchRecord:
        (
            batch_id, run_id, tenant_id, target_name, entity_id, units,
            as_of, source_kind, source_ref, notes, actual_values,
            point_count, idempotency_key, request_fingerprint, created_by,
            created_at,
        ) = row
        return ActualBatchRecord(
            batch_id=batch_id,
            run_id=run_id,
            tenant_id=tenant_id,
            target_name=target_name,
            entity_id=entity_id,
            units=units,
            as_of=as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
            source_kind=source_kind,
            source_ref=source_ref,
            notes=notes,
            values=tuple(actual_values or ()),
            point_count=int(point_count),
            idempotency_key=idempotency_key or "",
            request_fingerprint=request_fingerprint or "",
            created_by=created_by,
            created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        )

    @staticmethod
    def _row_to_comparison(row: Any) -> ComparisonRecord:
        (
            comparison_id, run_id, tenant_id, forecast_artifact_id,
            forecast_sha256, actual_batch_id, target_name, entity_id,
            units_check, units_note, status, matured_count, excluded_count,
            out_of_horizon_count, result, payload_sha256, idempotency_key,
            request_fingerprint, created_by, created_at,
        ) = row
        return ComparisonRecord(
            comparison_id=comparison_id,
            run_id=run_id,
            tenant_id=tenant_id,
            forecast_artifact_id=forecast_artifact_id,
            forecast_sha256=forecast_sha256,
            actual_batch_id=actual_batch_id,
            target_name=target_name,
            entity_id=entity_id,
            units_check=units_check,
            units_note=units_note,
            status=status,
            matured_count=int(matured_count),
            excluded_count=int(excluded_count),
            out_of_horizon_count=int(out_of_horizon_count),
            result=result or {},
            payload_sha256=payload_sha256,
            idempotency_key=idempotency_key or "",
            request_fingerprint=request_fingerprint or "",
            created_by=created_by,
            created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        )

    @staticmethod
    def _row_to_decision(row: Any) -> MonitoringDecisionRecord:
        (
            decision_id, run_id, tenant_id, comparison_id, action,
            rationale, decided_by, decided_at,
        ) = row
        return MonitoringDecisionRecord(
            decision_id=decision_id,
            run_id=run_id,
            tenant_id=tenant_id,
            comparison_id=comparison_id,
            action=action,
            rationale=rationale,
            decided_by=decided_by,
            decided_at=decided_at.isoformat() if hasattr(decided_at, "isoformat") else str(decided_at),
        )

    def save_actual_batch(self, record: ActualBatchRecord) -> ActualBatchRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO monitoring_actual_batches (batch_id, run_id,"
                " tenant_id, target_name, entity_id, units, as_of,"
                " source_kind, source_ref, notes, actual_values,"
                " point_count, idempotency_key, request_fingerprint,"
                " created_by, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                " %s, %s, %s, %s)"
                " ON CONFLICT (batch_id) DO NOTHING",
                (
                    record.batch_id, record.run_id, record.tenant_id,
                    record.target_name, record.entity_id, record.units,
                    record.as_of, record.source_kind, record.source_ref,
                    record.notes, json.dumps(list(record.values)),
                    record.point_count, record.idempotency_key,
                    record.request_fingerprint, record.created_by,
                    record.created_at,
                ),
            )
            conn.commit()
        return record

    def get_actual_batch(self, batch_id: str) -> Optional[ActualBatchRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT batch_id, run_id, tenant_id, target_name, entity_id,"
                " units, as_of, source_kind, source_ref, notes,"
                " actual_values, point_count, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_actual_batches WHERE batch_id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
        return self._row_to_batch(row) if row is not None else None

    def list_actual_batches(
        self, run_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ActualBatchRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT batch_id, run_id, tenant_id, target_name, entity_id,"
                " units, as_of, source_kind, source_ref, notes,"
                " actual_values, point_count, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_actual_batches WHERE run_id = %s"
                " ORDER BY created_at ASC, batch_id ASC LIMIT %s",
                (run_id, max(0, int(limit))),
            )
            rows = cur.fetchall()
        return [self._row_to_batch(row) for row in rows]

    def find_actual_batch_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ActualBatchRecord]:
        if not idempotency_key:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT batch_id, run_id, tenant_id, target_name, entity_id,"
                " units, as_of, source_kind, source_ref, notes,"
                " actual_values, point_count, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_actual_batches"
                " WHERE run_id = %s AND idempotency_key = %s",
                (run_id, idempotency_key),
            )
            row = cur.fetchone()
        return self._row_to_batch(row) if row is not None else None

    def save_comparison(self, record: ComparisonRecord) -> ComparisonRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO monitoring_comparisons (comparison_id, run_id,"
                " tenant_id, forecast_artifact_id, forecast_sha256,"
                " actual_batch_id, target_name, entity_id, units_check,"
                " units_note, status, matured_count, excluded_count,"
                " out_of_horizon_count, result, payload_sha256,"
                " idempotency_key, request_fingerprint, created_by,"
                " created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                " %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (comparison_id) DO NOTHING",
                (
                    record.comparison_id, record.run_id, record.tenant_id,
                    record.forecast_artifact_id, record.forecast_sha256,
                    record.actual_batch_id, record.target_name,
                    record.entity_id, record.units_check, record.units_note,
                    record.status, record.matured_count, record.excluded_count,
                    record.out_of_horizon_count,
                    json.dumps(record.result), record.payload_sha256,
                    record.idempotency_key, record.request_fingerprint,
                    record.created_by, record.created_at,
                ),
            )
            conn.commit()
        return record

    def get_comparison(self, comparison_id: str) -> Optional[ComparisonRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT comparison_id, run_id, tenant_id,"
                " forecast_artifact_id, forecast_sha256, actual_batch_id,"
                " target_name, entity_id, units_check, units_note, status,"
                " matured_count, excluded_count, out_of_horizon_count,"
                " result, payload_sha256, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_comparisons WHERE comparison_id = %s",
                (comparison_id,),
            )
            row = cur.fetchone()
        return self._row_to_comparison(row) if row is not None else None

    def list_comparisons(
        self, run_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ComparisonRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT comparison_id, run_id, tenant_id,"
                " forecast_artifact_id, forecast_sha256, actual_batch_id,"
                " target_name, entity_id, units_check, units_note, status,"
                " matured_count, excluded_count, out_of_horizon_count,"
                " result, payload_sha256, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_comparisons WHERE run_id = %s"
                " ORDER BY created_at ASC, comparison_id ASC LIMIT %s",
                (run_id, max(0, int(limit))),
            )
            rows = cur.fetchall()
        return [self._row_to_comparison(row) for row in rows]

    def find_comparison_idempotent(
        self, run_id: str, idempotency_key: str
    ) -> Optional[ComparisonRecord]:
        if not idempotency_key:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT comparison_id, run_id, tenant_id,"
                " forecast_artifact_id, forecast_sha256, actual_batch_id,"
                " target_name, entity_id, units_check, units_note, status,"
                " matured_count, excluded_count, out_of_horizon_count,"
                " result, payload_sha256, idempotency_key,"
                " request_fingerprint, created_by, created_at"
                " FROM monitoring_comparisons"
                " WHERE run_id = %s AND idempotency_key = %s",
                (run_id, idempotency_key),
            )
            row = cur.fetchone()
        return self._row_to_comparison(row) if row is not None else None

    def save_decision(
        self, record: MonitoringDecisionRecord
    ) -> MonitoringDecisionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO monitoring_decisions (decision_id, run_id,"
                " tenant_id, comparison_id, action, rationale, decided_by,"
                " decided_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (decision_id) DO NOTHING",
                (
                    record.decision_id, record.run_id, record.tenant_id,
                    record.comparison_id, record.action, record.rationale,
                    record.decided_by, record.decided_at,
                ),
            )
            conn.commit()
        return record

    def list_decisions(
        self, run_id: str, comparison_id: str
    ) -> list[MonitoringDecisionRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT decision_id, run_id, tenant_id, comparison_id,"
                " action, rationale, decided_by, decided_at"
                " FROM monitoring_decisions"
                " WHERE run_id = %s AND comparison_id = %s"
                " ORDER BY decided_at ASC, decision_id ASC",
                (run_id, comparison_id),
            )
            rows = cur.fetchall()
        return [self._row_to_decision(row) for row in rows]


_registry: Optional[MonitoringRegistry] = None
_registry_lock = threading.Lock()


def _choose_monitoring_registry() -> MonitoringRegistry:
    backend = (
        os.environ.get(MONITORING_BACKEND_ENV) or "memory"
    ).strip().lower()
    if backend == "postgres":
        return PostgresMonitoringRegistry.from_env()
    if backend in ("", "memory"):
        return MemoryMonitoringRegistry()
    raise RuntimeError(
        f"Неизвестный {MONITORING_BACKEND_ENV}: {backend!r}"
    )


def get_monitoring_registry() -> MonitoringRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = _choose_monitoring_registry()
    return _registry


def peek_monitoring_registry() -> Optional[MonitoringRegistry]:
    return _registry


def reset_monitoring_registry_for_testing() -> None:
    global _registry
    with _registry_lock:
        _registry = None


# ── Сервис мониторинга ───────────────────────────────────────────────


class MonitoringService:
    """Сверка прогноза с фактом: регистрация actual vintages, построение
    frozen сверок, append-only решения. Научный слой -- read-only."""

    def __init__(
        self,
        registry: Optional[MonitoringRegistry] = None,
    ) -> None:
        self._registry = registry

    @classmethod
    def create_default(cls) -> "MonitoringService":
        return cls(registry=get_monitoring_registry())

    @property
    def registry(self) -> MonitoringRegistry:
        if self._registry is None:
            self._registry = get_monitoring_registry()
        return self._registry

    # -- Авторизация (решающая таблица DOCLOG-0, §15.1) --

    def _authorized_run(self, run_id: str, subject: Any, *, action: str) -> Any:
        from apps.api.identity import authorize_run_access
        from apps.api.research_runs import get_research_run_store

        run = get_research_run_store().get_run(str(run_id))
        if run is None:
            raise MonitoringNotFoundError(f"Run {run_id!r} не найден")
        decision = authorize_run_access(
            run, subject, action=action
        )
        if not decision.allowed:
            raise MonitoringAccessDenied(
                "Доступ к run запрещён решающей таблицей"
            )
        return run

    # -- Actual vintages --

    def register_actual_batch(
        self,
        run_id: str,
        subject: Any,
        *,
        target_name: Any,
        entity_id: Any = None,
        units: Any,
        as_of: Any,
        values: Any,
        source_kind: str = "manual",
        source_ref: Any = None,
        notes: str = "",
        idempotency_key: str = "",
        session_id: str = "",
    ) -> tuple[ActualBatchRecord, bool]:
        """Иммутабельная партия факта (vintage). Пересмотр -- НОВАЯ
        партия; идемпотентность по (run_id, idempotency_key) (AC09)."""
        run = self._authorized_run(run_id, subject, action="write")

        target = str(target_name or "").strip()
        if not target:
            raise MonitoringValidationError(
                "target_name: требуется непустое имя показателя"
            )
        units_text = str(units or "").strip()
        if not units_text:
            raise MonitoringValidationError(
                "units: требуются единицы измерения факта (B07)"
            )
        if entity_id is not None and not str(entity_id).strip():
            raise MonitoringValidationError(
                "entity_id: пустая строка недопустима (None -- однорядный путь)"
            )
        as_of_dt = _parse_as_of(as_of)
        if not isinstance(values, list) or not values:
            raise MonitoringValidationError(
                "values: требуется непустой список значений факта"
            )
        normalized: list[dict[str, Any]] = []
        seen_periods: set[str] = set()
        for entry in values:
            if not isinstance(entry, dict):
                raise MonitoringValidationError(
                    "values: каждый элемент -- {period, value}"
                )
            period = str(entry.get("period", "")).strip()
            if not period:
                raise MonitoringValidationError(
                    "values: period -- непустая метка периода"
                )
            if period in seen_periods:
                raise MonitoringValidationError(
                    f"values: дубликат периода внутри партии: {period!r}"
                )
            seen_periods.add(period)
            raw_value = entry.get("value")
            if not _is_finite_number(raw_value):
                raise MonitoringValidationError(
                    "values: value -- конечное число (без NaN/Infinity/bool)"
                )
            normalized.append(
                {"period": period, "value": float(raw_value)}
            )
        if source_kind not in SOURCE_KINDS:
            raise MonitoringValidationError(
                f"source_kind: допустимо {sorted(SOURCE_KINDS)}"
            )
        source_ref_text = (
            str(source_ref).strip() if source_ref is not None else None
        )
        if source_ref_text == "":
            source_ref_text = None

        fingerprint = request_fingerprint(
            {
                "target_name": target,
                "entity_id": entity_id if entity_id is None else str(entity_id),
                "units": units_text,
                "as_of": as_of.strip(),
                "values": normalized,
                "source_kind": source_kind,
                "source_ref": source_ref_text,
                "notes": str(notes or ""),
            }
        )
        if idempotency_key:
            existing = self.registry.find_actual_batch_idempotent(
                str(run_id), idempotency_key
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise MonitoringIdempotencyConflictError(
                        "Тот же idempotency_key с другим телом запроса -- "
                        "конфликт (AC09)"
                    )
                return existing, False

        record = ActualBatchRecord(
            batch_id=_new_id("act"),
            run_id=str(run_id),
            tenant_id=getattr(run, "tenant_id", None),
            target_name=target,
            entity_id=entity_id if entity_id is None else str(entity_id),
            units=units_text,
            as_of=as_of_dt.isoformat(),
            source_kind=source_kind,
            source_ref=source_ref_text,
            notes=str(notes or ""),
            values=tuple(normalized),
            point_count=len(normalized),
            idempotency_key=str(idempotency_key or ""),
            request_fingerprint=fingerprint,
            created_by=getattr(subject, "subject_id", "") or None,
            created_at=_now_iso(),
        )
        self.registry.save_actual_batch(record)
        self._audit(
            "monitoring_actual_registered",
            run=run,
            subject=subject,
            resource_id=record.batch_id,
            details={
                "target_name": record.target_name,
                "point_count": record.point_count,
                "as_of": record.as_of,
            },
            basis="DOCLOG-8 actual vintage; §6 D12, B07",
        )
        return record, True

    def list_actual_batches(
        self, run_id: str, subject: Any, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ActualBatchRecord]:
        self._authorized_run(run_id, subject, action="read")
        return self.registry.list_actual_batches(str(run_id), limit=limit)

    # -- Сверки --

    def build_comparison(
        self,
        run_id: str,
        subject: Any,
        *,
        forecast_artifact_id: Any,
        actual_batch_id: Any,
        forecast_units: Any = None,
        units_conversion: Any = None,
        threshold: Any = None,
        mase_scale: Any = None,
        idempotency_key: str = "",
        session_id: str = "",
    ) -> tuple[ComparisonRecord, bool]:
        """Frozen сверка (§6 D12): выравнивание + честные метрики над
        forecast vintage x actual vintage. Прогноз НЕ пересчитывается и
        НЕ изменяется; научный слой read-only."""
        run = self._authorized_run(run_id, subject, action="write")

        artifact_id = str(forecast_artifact_id or "").strip()
        if not artifact_id:
            raise MonitoringValidationError(
                "forecast_artifact_id: требуется идентификатор артефакта"
            )
        batch_id = str(actual_batch_id or "").strip()
        if not batch_id:
            raise MonitoringValidationError(
                "actual_batch_id: требуется идентификатор партии факта"
            )

        # Forecast vintage: артефакт чужого run -- отказ (T7/T15);
        # битые байты -- честный отказ (T8), не выдуманные числа.
        from apps.api.artifact_store import (
            artifact_content_sha256,
            get_artifact_object_store,
            get_artifact_registry,
        )

        artifact = get_artifact_registry().get_artifact(artifact_id)
        if artifact is None:
            raise MonitoringForecastUnavailable(
                f"Артефакт прогноза {artifact_id!r} не найден"
            )
        if artifact.run_id != str(run_id):
            raise MonitoringAccessDenied(
                "Артефакт прогноза принадлежит другому run -- знание "
                "идентификатора не является правом (T7)"
            )
        if artifact.kind != "forecast":
            raise MonitoringForecastUnavailable(
                f"Артефакт {artifact_id!r} kind={artifact.kind!r} -- "
                "ожидается kind='forecast'"
            )
        try:
            raw = get_artifact_object_store().read_bytes(artifact.storage_key)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MonitoringForecastUnavailable(
                "Байты артефакта прогноза повреждены или нечитаемы (T8) -- "
                "честный отказ без выдуманных чисел"
            ) from exc
        if artifact_content_sha256(raw) != artifact.payload_sha256:
            raise MonitoringForecastUnavailable(
                "Целостность прогноза нарушена: payload_sha256 расходится "
                "(T8) -- сверка на подменённых байтах запрещена"
            )
        points = payload.get("points")
        if not isinstance(points, list) or not points:
            raise MonitoringForecastUnavailable(
                "Прогноз без точек (points) -- сверить нечего"
            )

        # Actual vintage: только своей run-границы.
        batch = self.registry.get_actual_batch(batch_id)
        if batch is None or batch.run_id != str(run_id):
            raise MonitoringNotFoundError(
                f"Партия факта {batch_id!r} не найдена в границах run"
            )

        # Единицы (AC15): несовпадение без явной конверсии -- отказ с
        # причиной; конверсия -- только явно переданный ненулевой factor.
        units_factor = 1.0
        units_check = "unknown"
        units_note = ""
        forecast_units_text = (
            str(forecast_units).strip() if forecast_units is not None else None
        )
        if forecast_units_text == "":
            forecast_units_text = None
        if forecast_units_text is None:
            units_check = "unknown"
            units_note = "units прогноза не объявлены -- честное unknown"
        elif forecast_units_text == batch.units:
            units_check = "as_is"
        else:
            conversion = units_conversion
            if not isinstance(conversion, dict):
                raise MonitoringUnitsMismatchError(
                    f"Не совпали единицы измерения: прогноз "
                    f"{forecast_units_text!r} vs факт {batch.units!r}; "
                    "передайте явную конверсию "
                    "{factor, note} либо откажитесь от сверки (AC15)"
                )
            factor = conversion.get("factor")
            if not _is_finite_number(factor) or float(factor) == 0.0:
                raise MonitoringValidationError(
                    "units_conversion.factor: конечное ненулевое число"
                )
            units_factor = float(factor)
            units_check = "converted"
            units_note = str(conversion.get("note", ""))

        # Threshold -- политика задачи: метрика/оператор/значение.
        threshold_dict: Optional[dict[str, Any]] = None
        if threshold is not None:
            if not isinstance(threshold, dict):
                raise MonitoringValidationError(
                    "threshold: {metric, operator, value, label?}"
                )
            metric = str(threshold.get("metric", ""))
            operator = str(threshold.get("operator", ""))
            value = threshold.get("value")
            if metric not in THRESHOLD_METRICS:
                raise MonitoringValidationError(
                    f"threshold.metric: допустимо {sorted(THRESHOLD_METRICS)}"
                )
            if operator not in THRESHOLD_OPERATORS:
                raise MonitoringValidationError(
                    f"threshold.operator: допустимо {sorted(THRESHOLD_OPERATORS)}"
                )
            if not _is_finite_number(value):
                raise MonitoringValidationError(
                    "threshold.value: конечное число"
                )
            threshold_dict = {
                "metric": metric,
                "operator": operator,
                "value": float(value),
                "label": str(threshold.get("label", "")),
            }

        # mase_scale: явный training-scale (§4.1); невалидный -- 422.
        scale: Optional[float] = None
        if mase_scale is not None:
            if not _is_finite_number(mase_scale) or float(mase_scale) <= 0:
                raise MonitoringValidationError(
                    "mase_scale: конечное положительное число (training "
                    "scale MASE; §4.1 time-aware)"
                )
            scale = float(mase_scale)

        result = compute_comparison_result(
            payload,
            list(batch.values),
            units_factor=units_factor,
            threshold=threshold_dict,
            mase_scale=scale,
        )

        fingerprint = request_fingerprint(
            {
                "forecast_artifact_id": artifact_id,
                "forecast_payload_sha256": artifact.payload_sha256,
                "actual_batch_id": batch_id,
                "forecast_units": forecast_units_text,
                "units_factor": units_factor,
                "threshold": threshold_dict,
                "mase_scale": scale,
            }
        )
        if idempotency_key:
            existing = self.registry.find_comparison_idempotent(
                str(run_id), idempotency_key
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise MonitoringIdempotencyConflictError(
                        "Тот же idempotency_key с другим телом запроса -- "
                        "конфликт (AC09)"
                    )
                return existing, False

        payload_bytes = canonical_json_bytes(result)
        record = ComparisonRecord(
            comparison_id=_new_id("mon"),
            run_id=str(run_id),
            tenant_id=getattr(run, "tenant_id", None),
            forecast_artifact_id=artifact_id,
            forecast_sha256=artifact.payload_sha256,
            actual_batch_id=batch_id,
            target_name=batch.target_name,
            entity_id=batch.entity_id,
            units_check=units_check,
            units_note=units_note,
            status="ready",
            matured_count=int(result["alignment"]["matured_count"]),
            excluded_count=int(result["alignment"]["excluded_count"]),
            out_of_horizon_count=int(
                result["alignment"]["out_of_horizon_count"]
            ),
            result=result,
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
            idempotency_key=str(idempotency_key or ""),
            request_fingerprint=fingerprint,
            created_by=getattr(subject, "subject_id", "") or None,
            created_at=_now_iso(),
        )
        self.registry.save_comparison(record)
        self._audit(
            "monitoring_comparison_created",
            run=run,
            subject=subject,
            resource_id=record.comparison_id,
            details={
                "forecast_artifact_id": artifact_id,
                "actual_batch_id": batch_id,
                "matured_count": record.matured_count,
                "excluded_count": record.excluded_count,
                "units_check": record.units_check,
            },
            basis="DOCLOG-8 comparison; §6 D12, §19",
        )
        return record, True

    def list_comparisons(
        self, run_id: str, subject: Any, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[ComparisonRecord]:
        self._authorized_run(run_id, subject, action="read")
        return self.registry.list_comparisons(str(run_id), limit=limit)

    def get_comparison(
        self, run_id: str, subject: Any, comparison_id: str
    ) -> ComparisonRecord:
        self._authorized_run(run_id, subject, action="read")
        record = self.registry.get_comparison(str(comparison_id))
        if record is None or record.run_id != str(run_id):
            raise MonitoringNotFoundError(
                f"Сверка {comparison_id!r} не найдена в границах run"
            )
        return record

    # -- Решения (append-only, §6.1) --

    def record_decision(
        self,
        run_id: str,
        subject: Any,
        comparison_id: Any,
        *,
        action: Any,
        rationale: Any,
        session_id: str = "",
    ) -> MonitoringDecisionRecord:
        run = self._authorized_run(run_id, subject, action="write")
        record = self.registry.get_comparison(str(comparison_id or ""))
        if record is None or record.run_id != str(run_id):
            raise MonitoringNotFoundError(
                f"Сверка {comparison_id!r} не найдена в границах run -- "
                "решение не может ссылаться на чужую сверку"
            )
        action_text = str(action or "").strip()
        if action_text not in DECISION_ACTIONS:
            raise MonitoringValidationError(
                f"action: допустимо {sorted(DECISION_ACTIONS)}"
            )
        rationale_text = str(rationale or "").strip()
        if not rationale_text:
            raise MonitoringValidationError(
                "rationale: требуется непустое основание решения"
            )
        decision = MonitoringDecisionRecord(
            decision_id=_new_id("dec"),
            run_id=str(run_id),
            tenant_id=getattr(run, "tenant_id", None),
            comparison_id=record.comparison_id,
            action=action_text,
            rationale=rationale_text,
            decided_by=getattr(subject, "subject_id", "") or None,
            decided_at=_now_iso(),
        )
        self.registry.save_decision(decision)
        self._audit(
            "monitoring_decision_recorded",
            run=run,
            subject=subject,
            resource_id=decision.decision_id,
            details={
                "comparison_id": record.comparison_id,
                "action": action_text,
            },
            basis="DOCLOG-8 decision; §6.1 (без автопереобучения)",
        )
        return decision

    def list_decisions(
        self, run_id: str, subject: Any, comparison_id: Any
    ) -> list[MonitoringDecisionRecord]:
        self.get_comparison(run_id, subject, str(comparison_id or ""))
        return self.registry.list_decisions(str(run_id), str(comparison_id or ""))

    # -- Аудит (standard; §8: mandatory только для защищённой выдачи) --

    def _audit(
        self,
        action: str,
        *,
        run: Any,
        subject: Any,
        resource_id: str,
        details: dict[str, Any],
        basis: str,
    ) -> None:
        from apps.api.security_audit import record_standard

        try:
            record_standard(
                action,
                "allowed",
                actor_subject=getattr(subject, "subject_id", "") or "",
                actor_via=getattr(subject, "via", "") or "anonymous",
                tenant_id=getattr(run, "tenant_id", None),
                resource_kind="monitoring",
                resource_id=resource_id,
                policy_basis=basis,
                run_id=str(run.run_id),
                details=details,
            )
        except Exception:
            # Standard-класс: сбой аудита не ломает научную операцию
            # (§8/AC11: mandatory -- только защищённая выдача).
            pass
