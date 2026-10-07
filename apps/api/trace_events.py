# apps/api/trace_events.py
"""Канонический TraceEvent -- общий контракт трассировки этапов
(spec_forecasting2.md §10.4 + spec_progress.md §4.1, сведение -- Task PROGR-1).

История контракта: датакласс вынесен в ОБЩЕЕ место до реализации первого
потребителя (spec_forecasting2.md §10.4), затем канонизирован спецификацией
микросервиса «Прогресс» (spec_progress.md §4.1 -- восемь полей). Сведение
выполнено АДДИТИВНО: прежний 3-польный формат (event_type/timestamp/payload)
остаётся совместимым подмножеством --

  * `timestamp` сохранён как legacy-алиас свойства к `ts` (и как ключ
    to_dict()), потому что pydantic-схема ответа ForecastTraceEventSchema
    (apps/api/schemas.py) объявляет его обязательным, а фронтенд-интерфейс
    ForecastTraceEvent (packages/ui/lib/forecasting.ts) читает его;
  * события, сохранённые в Redis-ранах по старому 3-польному формату,
    нормализуются на границе чтения через normalize_trace_event_dict() /
    TraceEvent.from_dict() (потребители -- PROGR-3, PROGR-5);
  * 4 текущих вызова make_trace_event() в forecasting_session.py не
    изменены: stage по умолчанию "forecasting".

Формат ts -- ISO 8601 UTC (datetime.now(timezone.utc).isoformat()) --
совместим с ForecastRun.generated_at и общей таймлинией трассы.

Реестр типов событий (spec_progress.md §4.1, таблица): fail-closed по паре
(stage, event_type) -- опечатка не должна молча исчезнуть из трассы.
Run-level события (run_paused/run_resumed/checkpoint_saved, §5.1-5.2)
валидны на ЛЮБОЙ стадии. Сторонние этапы регистрируются расширением
реестра STAGE_EVENT_TYPES, а не обходом гейта.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# Типы событий этапа Прогнозирование (spec_forecasting2.md §5.9): дробление
# на отдельные event_type, а не один общий -- панель «Прогресс» визуализирует
# прогресс ВНУТРИ этапа через посегментную подсветку контрольных точек.
FORECAST_EVENT_TYPES = {
    "forecast_generated",              # построен прогноз
    "forecast_compared",               # выполнено сравнение прогнозов
    "forecast_sensitivity_computed",   # рассчитан веер чувствительности
    "forecast_exported",               # экспорт (csv/json/png/pdf)
}

# Стадии пайплайна (spec_progress.md §2). Константа локальна и верифицируется
# на равенство apps/api/session_store.py::STAGES import-инвариантом теста
# графа пайплайна (Task PROGR-2; тот же паттерн, что CERTIFIED_IDS-тесты) --
# направленный импорт session_store отсюда создал бы обратную зависимость
# контракта от хранилища.
KNOWN_STAGES = (
    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",
)

# События уровня запуска (spec_progress.md §4.1, строка «session (любая
# стадия)» + §5.1-5.2): чекпоинты, пауза/восстановление -- валидны на
# любой стадии, поэтому добавляются к каждой в реестре ниже.
RUN_LEVEL_EVENT_TYPES = {
    "run_paused",       # явная фиксация run.status="paused"
    "run_resumed",      # возврат к работе после паузы
    "checkpoint_saved", # именованная ссылка на событие трассы (§5.1)
}

_STAGE_EVENT_TYPES: dict[str, set[str]] = {
    "upload": {
        # §6.1: перенос addLogEntry успешной загрузки в TraceEvent.
        "upload_completed",
        # PROGR-13-B2: паспорт start фиксируется на вкладке «Загрузка» --
        # тип паспортной точки валиден на её стадии (см. примечание ниже).
        "passport_captured",
        # PROGR-13-A3: подтверждение структуры аналитиком
        # (POST /date-column, остановка «Структура» модуля) -- факт
        # решения, не сырой ответ (payload -- date_column из тела ответа).
        "structure_confirmed",
        # PROGR-13-A4: отчёт фактов остановок модулем «Загрузка»
        # (POST /v1/progress/upload-stops; прецедент §7.2 -- клиент строит
        # сводку из уже полученных данных). Статус остановки -- В PAYLOAD
        # (ключ "status", whitelist CHECK_STATUS_VALUES); движок
        # node_status читает его оттуда (PAYLOAD_STATUS_EVENT_TYPES).
        "upload_stop_status",
    },
    "validation": {
        # spec_progress.md §4.1 (унаследовано из progress_ts_analysis.md).
        "mode_changed", "correction_previewed",
        "correction_applied", "target_column_changed",
        # PROGR-13-B2: паспортная точка validation (см. примечание ниже).
        "passport_captured",
        # PROGR-16-A: отчёт фактов проверок модулем «Валидация»
        # (POST /v1/progress/validation-checks; прецедент §7.2 -- клиент
        # строит сводку из уже полученных данных, тот же паттерн, что
        # upload_stop_status PROGR-13-A4). Статус проверки -- В PAYLOAD
        # (ключ "status", whitelist CHECK_STATUS_VALUES); движок
        # node_status читает его оттуда (PAYLOAD_STATUS_EVENT_TYPES).
        # Закрытие дефекта PROGR-16-REPRO: запуск валидации был «слепой
        # зоной» факт-контура -- панель показывала «Валидация. Не начато»
        # при цветном модуле.
        "validation_check_status",
    },
    # Предобработка разделяет набор Валидации (те же действия аналитика
    # на своей остановке), таблица §4.1 объединяет обе стадии.
    "preprocessing": {
        "mode_changed", "correction_previewed",
        "correction_applied", "target_column_changed",
        # PROGR-17 (spec_progress_v1.1.md §2, категория B): отчёт фактов
        # этапов модулем «Предобработка» (POST /v1/progress/preprocessing-
        # checks; зеркало /validation-checks PROGR-16-A буквально, тот же
        # паттерн §7.2 -- клиент строит сводку из уже полученных ответов
        # profile-эндпоинтов). Статус этапа -- В PAYLOAD (ключ "status",
        # whitelist CHECK_STATUS_VALUES); движок node_status читает его
        # оттуда (PAYLOAD_STATUS_EVENT_TYPES). Закрытие родственной зоны
        # дефекта PROGR-16-REPRO: у Предобработки, как и у Валидации до
        # PROGR-16-A, автозаполнение степпера не имело носителя в
        # факт-контуре стадии -- панель показывала «не начато» при
        # цветном модуле.
        "preprocessing_check_status",
    },
    "eda": {
        "profile_viewed",    # троттлинг §4.2 (дефолт 5 мин на узел)
        "passport_captured",
        # PROGR-18 (spec_progress_v1.1.md §2, категория B): отчёт фактов
        # просмотров исследований модулем «EDA» (POST /v1/progress/
        # eda-checks; зеркало /preprocessing-checks PROGR-17 / /validation-
        # checks PROGR-16-A, тот же паттерн §7.2 -- клиент строит сводку
        # из уже полученных данных). Статус исследования -- В PAYLOAD
        # (ключ "status"); движок node_status читает его оттуда
        # (PAYLOAD_STATUS_EVENT_TYPES). Решение тимлида по семантике
        # (v1.1 §2): статус done/pending по факту «аналитик открыл и
        # просмотрел результат», warning НЕ вводить (EDA -- анализ, а не
        # проверка качества: ложная тревога там, где нет критерия ошибки);
        # словарь отчёта {"done", "pending"} enforced эндпоинтом. Закрытие
        # последней дыры класса «нет носителя факта прохождения»: узлы EDA
        # не достигали done от самого модуля (profile_viewed -- running).
        "eda_check_status",
    },
    "modeling": {
        # По факту существующих эндпоинтов routers/modeling_session.py.
        "backtest_run", "tuning_trial_completed",
        "model_selected", "model_card_generated",
        # PROGR-13-B2: паспорт modeling_entry -- контроль входа в
        # Моделирование. Паспорт -- сквозной факт (точка задаёт стадию
        # события, TRACE_ROUTES PROGR-13-B2): расширение реестра -- тот
        # же паттерн «сторонние этапы регистрируются расширением
        # реестра, а не обходом гейта»; спецификация §4.1 дополняется
        # задачей PROGR-13-A (документация).
        "passport_captured",
        # PROGR-20 (spec_progress_v1.1.md §1, категория A): плановое
        # расширение allowlist Моделирования -- факты, которые раньше
        # не оставляли следа в трассе вовсе:
        #   candidates_generated -- формирование пула кандидатов
        #     applicability-движком modeling.yaml («факт, который
        #     система формирует автоматически на основе системных
        #     правил» -- прямой пример из контрольной формулировки);
        #   selection_evaluated -- трассируемая оценка выбора
        #     (рекомендация + проверка ансамбля OOF), класс
        #     model_selected;
        #   models_compared -- факт сравнения моделей (решение
        #     аналитика, P1);
        #   diagnostics_run -- запуск/обеспечение диагностики, пара
        #     к backtest_run (P1; один тип на /diagnostics и
        #     /diagnostics/ensure -- один класс факта);
        #   tuning_skipped -- осознанный аудируемый выбор «оставить
        #     defaults» (P2; НЕ дублирует tuning_trial_completed --
        #     тот пишется только реальным тюнингом /tune);
        #   tuning_job_started / tuning_job_cancelled -- старт/отмена
        #     долгого job-контура тюнинга (P2): до расширения job-путь
        #     не оставлял факта в трассе вовсе (tuning_trial_completed
        #     на нём не возникает), отмена -- явное решение аналитика.
        #     jobs/{id}/step сознательно НЕ трассируется (механические
        #     единицы работы -- прогресс-лог, не журнал решений §1).
        "candidates_generated", "selection_evaluated", "models_compared",
        "diagnostics_run", "tuning_skipped",
        "tuning_job_started", "tuning_job_cancelled",
    },
    "forecasting": set(FORECAST_EVENT_TYPES),
}

# Чистый реестр по таблице §4.1: строки стадий -- только свои типы;
# run-level типы (§5.1-5.2) -- отдельная строка «session (любая стадия)»
# и проверяются отдельно (см. make_trace_event), не растворяются в каждой
# стадии -- реестр остаётся дословным отражением таблицы спецификации.
STAGE_EVENT_TYPES: dict[str, frozenset[str]] = {
    stage: frozenset(types) for stage, types in _STAGE_EVENT_TYPES.items()
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class TraceEvent:
    """Единое событие трассы исследования (spec_progress.md §4.1) --
    потребляется панелью «Прогресс», Наставником и (в будущем) квантом
    обучения Q/ΔQ (spec_education.md §8-§9).

    Порядок полей сохраняет совместимость прежней позиции event_type;
    все новые поля канона имеют дефолты, поэтому прежние вызовы
    make_trace_event(event_type, **payload) и равенство двух событий
    по 8 каноническим полям не требуют миграции вызывающего кода.
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=_new_event_id)
    run_id: str = ""
    ts: str = field(default_factory=_now_iso)
    stage: str = "forecasting"
    node_id: str | None = None
    actor: str = "user"

    @property
    def timestamp(self) -> str:
        """Legacy-алиас канонического ts (spec_forecasting2.md §7):
        сохранён для pydantic-схемы ответа и фронтенд-интерфейса."""
        return self.ts

    def to_dict(self) -> dict[str, Any]:
        """Канонический 8-польный словарь + legacy-алиас `timestamp`.

        Лишний (девятый) ключ сознательно оставлен: ForecastTraceEventSchema
        требует `timestamp` как обязательное поле, лишние ключи pydantic
        фильтрует -- контракт HTTP-ответа не меняется (двойная запись).
        """
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "ts": self.ts,
            "stage": self.stage,
            "node_id": self.node_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "actor": self.actor,
            # Legacy-алиас (spec_forecasting2.md §7) -- см. докстринг класса.
            "timestamp": self.ts,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, run_id: str = "") -> "TraceEvent":
        """Восстановление из словаря stored-формата (любой версии):
        legacy 3-поля и канонические 8 -- через normalize_trace_event_dict."""
        data = normalize_trace_event_dict(raw, run_id=run_id)
        return cls(
            event_type=data["event_type"],
            payload=dict(data["payload"]),
            event_id=data["event_id"],
            run_id=data["run_id"],
            ts=data["ts"],
            stage=data["stage"],
            node_id=data["node_id"],
            actor=data["actor"],
        )


def make_trace_event(
    event_type: str,
    *,
    stage: str = "forecasting",
    node_id: str | None = None,
    run_id: str = "",
    actor: str = "user",
    **payload: Any,
) -> TraceEvent:
    """Фабрика события с каноническим UTC-timestamp и fail-closed гейтом
    по паре (stage, event_type) -- таблица §4.1 spec_progress.md.

    Сигнатура обратно совместима с 4 текущими вызовами Прогнозирования
    (routers/forecasting_session.py): event_type позиционно, payload
    kwargs-ом; stage по умолчанию "forecasting".
    """
    if stage not in KNOWN_STAGES:
        raise ValueError(
            f"Неизвестная стадия трассы: {stage!r}; "
            f"известные: {list(KNOWN_STAGES)}"
        )
    if (
        event_type not in STAGE_EVENT_TYPES[stage]
        and event_type not in RUN_LEVEL_EVENT_TYPES
    ):
        raise ValueError(
            f"Неизвестный тип события трассы: {event_type!r} "
            f"для стадии {stage!r}; "
            f"известные: {sorted(STAGE_EVENT_TYPES[stage] | RUN_LEVEL_EVENT_TYPES)}"
        )
    return TraceEvent(
        event_type=event_type,
        payload=dict(payload),
        event_id=_new_event_id(),
        run_id=run_id,
        ts=_now_iso(),
        stage=stage,
        node_id=node_id,
        actor=actor,
    )


def normalize_trace_event_dict(
    raw: dict[str, Any], *, run_id: str = "",
) -> dict[str, Any]:
    """Нормализация stored-события к каноническому 8-польному виду §4.1.

    Принимает: (а) legacy 3-поля spec_forecasting2.md §7
    (event_type/timestamp/payload -- единственная реальная историческая
    популяция, вся она этапа Прогнозирования); (б) канонический словарь
    (idempotent pass-through); (в) частичный канон -- отсутствующие
    поля заполняются дефолтами. Вход НЕ мутируется; payload копируется.
    """
    if "ts" not in raw and "timestamp" in raw:
        # Legacy-формат: stage у всей популяции -- "forecasting".
        base_stage: str = "forecasting"
    else:
        base_stage = str(raw.get("stage") or "forecasting")
    if base_stage not in KNOWN_STAGES:
        raise ValueError(
            f"Неизвестная стадия трассы: {base_stage!r}; "
            f"известные: {list(KNOWN_STAGES)}"
        )
    return {
        "event_id": str(raw.get("event_id") or _new_event_id()),
        "run_id": str(raw.get("run_id") or run_id),
        "ts": str(raw.get("ts") or raw.get("timestamp") or ""),
        "stage": base_stage,
        "node_id": raw.get("node_id"),
        "event_type": str(raw["event_type"]),
        "payload": dict(raw.get("payload") or {}),
        "actor": str(raw.get("actor") or "user"),
    }
