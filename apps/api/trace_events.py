# apps/api/trace_events.py
"""Канонический TraceEvent -- общий контракт трассировки этапов (spec_forecasting2.md §10.4).

Рекомендация §10.4 спецификации Прогнозирования принята: датакласс вынесен
в ОБЩЕЕ место ДО реализации первого потребителя (Прогнозирование или панель
«Прогресс исследования TS»), чтобы каждый модуль не спроектировал свой
TraceEvent независимо «по конвенции» и не породил расхождения формата
timestamp/вложенности payload при реальной интеграции.

Формат timestamp -- ISO 8601 UTC (datetime.now(timezone.utc).isoformat()) --
совместим с ForecastRun.generated_at и общей таймлинией трассы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Типы событий этапа Прогнозирование (spec_forecasting2.md §5.9): дробление
# на отдельные event_type, а не один общий -- панель «Прогресс» визуализирует
# прогресс ВНУТРИ этапа через посегментную подсветку контрольных точек.
FORECAST_EVENT_TYPES = {
    "forecast_generated",              # построен прогноз
    "forecast_compared",               # выполнено сравнение прогнозов
    "forecast_sensitivity_computed",   # рассчитан веер чувствительности
    "forecast_exported",               # экспорт (csv/json/png/pdf)
}


@dataclass(frozen=True)
class TraceEvent:
    """Единое событие трассы исследования -- потребляется панелью «Прогресс»,
    Наставником и (в будущем) квантом обучения Q/ΔQ (spec_education.md §8-§9)."""

    event_type: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_trace_event(event_type: str, **payload: Any) -> TraceEvent:
    """Фабрика события с каноническим UTC-timestamp.

    Fail-closed на неизвестном типе события этапа Прогнозирования: опечатка
    в event_type не должна молча исчезнуть из трассы. Сторонние этапы
    (вне FORECAST_EVENT_TYPES) регистрируются расширением множества, а не
    обходом гейта.
    """
    if event_type not in FORECAST_EVENT_TYPES:
        raise ValueError(
            f"Неизвестный тип события трассы: {event_type!r}; "
            f"известные: {sorted(FORECAST_EVENT_TYPES)}"
        )
    return TraceEvent(
        event_type=event_type, timestamp=_now_iso(), payload=dict(payload),
    )
