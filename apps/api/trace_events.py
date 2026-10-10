# apps/api/trace_events.py
"""Канонический TraceEvent -- общий контракт трассировки этапов
(spec_forecasting2.md §10.4 + spec_progress.md §4.1, сведение -- Task PROGR-1).

AUDIT-S (plan_progress_audit.md §5; PROGR-AUDIT-S): над каноном §4.1
введён АДДИТИВНЫЙ версионированный envelope v2 (docs/progress_audit_contract.md
v0.2-AUDIT-S §12, развитие §3.2/§3.3/§4/§5.3):

  * 9 Optional-полей (schema_version/evidence_level/sequence/operation_id/
    causation_id/context_id/result_ref/method/time_quality); to_dict()
    включает ТОЛЬКО заполненные -- v1-события сериализуются байт-в-байт
    как прежде (8 полей + legacy-алиас), «незаполняемое поле отсутствует»;
  * уровни доказательности (контракт §4): server_result /
    client_observation / user_decision / operational -- реестр покрывает
    ВСЕ текущие типы; resolve_evidence_level учитывает payload
    (target_column_changed source=auto -- server_result); дефолтный actor
    НЕ доказывает осознанный человеческий выбор;
  * стабильная идентичность legacy (I1/F11/P17): событие без event_id
    получает ДЕТЕРМИНИРОВАННЫЙ id (uuid5 канонического содержимого) --
    повторное чтение возвращает тот же id, новые id при каждом чтении
    не генерируются;
  * честное время (F16/P23): нечитаемый ts НЕ подменяется -- envelope
    time_quality={raw_ts, quality: degraded|substituted, observed_at};
    валидный/отсутствующий ts поле не получают;
  * единое чтение порядка (контракт §3.3): merge_canonical_events --
    dedupe строго по ОДНОМУ event_id + канонический порядок; ветка
    sequence включается только когда он есть у ВСЕХ событий корпуса;
    назначение sequence -- ledger-store AUDIT-6A (не здесь).

Точки вызова: адаптер прогнозов -- canonicalize_stored_event
(routers/progress.py), граница записи stores -- mark_honest_time
(research_runs.py), продюсеры v2 -- stamp_envelope (постепенно, по схеме
перехода «читатели раньше писателей», контракт §7).

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

import copy
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

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
        # PROGR-AUDIT-H1 (горячая дорожка F02, контракт
        # docs/progress_audit_contract.md §3.1 -- УТВЕРЖДЕНО-AUDIT-0):
        # выделенный канонический тип СБРОСА цели -- первоклассное
        # событие вместо «пустого target в target_column_changed»
        # (сигнал сброса уходил вне канала цели: флаг
        # target_column_reset=true путешествовал в payload
        # correction_applied узла data_types, который подсистема цели
        # не читает -- F02/P03). Носитель выбора -- та же пара
        # (stage=validation, node_id=None). Посев ТОЛЬКО серверным
        # продюсером в точке решения (POST /target-column остаётся
        # маршрутом ВЫБОРА с 422 на пустой -- маршруты не объединены);
        # whitelisting кодом, TRACE_ROUTES не трогаются. Payload:
        # {target_column: null, reset_reason, source: "system"|"auto",
        # before_target}; мусор в полях -- деградация, не 500.
        # Регистрация ТИПА не ждёт AUDIT-S (оговорка-разблокировка
        # Донастройки Части 1).
        "target_column_cleared",
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
        # G345-фикс (PROGR-23): живые GET-пересчёты карточки «Выбросы»
        # (GET /dataset/outlier-profile, строка таблицы TRACE_ROUTES с
        # dedupe) сеют payload-статус outliers_profile_status из тела
        # ответа (whitelist CHECK_STATUS_VALUES, движок --
        # PAYLOAD_STATUS_EVENT_TYPES). Закрытие «окна лжи»
        # PROGR-22-REPRO/Г5 (карточка warning при трейсе done после
        # появления выбросов в данных): факт живой диагностики --
        # тоже факт трассы.
        "outliers_profile_status",
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


# ── AUDIT-S: уровни доказательности (контракт v0.2-AUDIT-S §12.2) ──

# Четыре канонических уровня (спека §8.1, контракт §4): что удостоверяет
# событие. Default actor ("user") НЕ доказывает осознанный человеческий
# выбор -- уровень определяется типом/_payload-семантикой продюсера.
EVIDENCE_LEVELS = (
    "server_result",       # алгоритм выдал результат на определённом входе
    "client_observation",  # клиент сообщил наблюдаемую картину
    "user_decision",       # явное действие человека (trigger удостоверен)
    "operational",         # служебное событие контура
)

# Реестр по ВСЕМ текущим типам (контракт §4 + классификация по продюсеру:
# расчёт сервера -> server_result; отчёт модуля о наблюдаемой картине ->
# client_observation; явное действие аналитика -> user_decision; хуки
# просмотров и run-контур -> operational). Расширение реестра -- вместе с
# регистрацией типа (аддитивное, задача-продюсер обновляет таблицу
# контракта).
EVIDENCE_LEVEL_BY_EVENT_TYPE: dict[str, str] = {
    # upload
    "upload_completed": "server_result",
    "passport_captured": "operational",
    "structure_confirmed": "user_decision",
    "upload_stop_status": "client_observation",
    # validation / preprocessing
    "mode_changed": "user_decision",
    "correction_previewed": "server_result",
    "correction_applied": "server_result",
    "target_column_changed": "user_decision",  # source=auto -- см. override
    # PROGR-AUDIT-H1 (F02): сброс -- серверное решение кода точки
    # конвертации (нечисловая колонка не может быть целью; POST-маршрута
    # сброса нет -- контракт §3.1 п.5), поэтому server_result, а не
    # user_decision: дефолтный actor и apply-клик пользователя не делают
    # сброс осознанным человеческим решением О СБРОСЕ.
    "target_column_cleared": "server_result",
    "validation_check_status": "client_observation",
    "preprocessing_check_status": "client_observation",
    "outliers_profile_status": "client_observation",
    # eda
    "profile_viewed": "operational",
    "eda_check_status": "client_observation",
    # modeling
    "backtest_run": "server_result",
    "tuning_trial_completed": "server_result",
    "model_selected": "user_decision",
    "model_card_generated": "server_result",
    "candidates_generated": "server_result",
    "selection_evaluated": "server_result",
    "models_compared": "user_decision",
    "diagnostics_run": "server_result",
    "tuning_skipped": "user_decision",
    "tuning_job_started": "server_result",
    "tuning_job_cancelled": "user_decision",
    # forecasting
    "forecast_generated": "server_result",
    "forecast_compared": "server_result",
    "forecast_sensitivity_computed": "server_result",
    "forecast_exported": "server_result",
    # run-level (любая стадия)
    "run_paused": "operational",
    "run_resumed": "operational",
    "checkpoint_saved": "operational",
}

# Payload-aware уточнения: семантика конкретного типа зависит от payload.
# target_column_changed с source=auto -- факт серверного решения
# (контракт §4: «target_column_changed (auto-ветка)»); отсутствие source
# у legacy-ВЫБОРА -- user_decision (согласованная семантика PROGR-25-A,
# контракт §3.7).
_EVIDENCE_PAYLOAD_OVERRIDES = {
    "target_column_changed": lambda payload: (
        "server_result" if (payload or {}).get("source") == "auto" else None
    ),
}


def resolve_evidence_level(event_type: str, payload: dict[str, Any] | None) -> str | None:
    """Уровень доказательности события: payload-aware override, затем
    реестр типа; неизвестный тип -- None (честное unknown, деградация,
    не выдумка)."""
    override = _EVIDENCE_PAYLOAD_OVERRIDES.get(event_type)
    if override is not None:
        resolved = override(payload)
        if resolved is not None:
            return resolved
    return EVIDENCE_LEVEL_BY_EVENT_TYPE.get(event_type)


# Обязательность envelope-полей v2 per-уровень (таблица AUDIT-S,
# контракт v0.2-AUDIT-S §12.3): базис -- schema_version + evidence_level;
# user_decision удостоверяет trigger (causation_id), server_result
# воспроизводимость (result_ref + method), клиентские/служебные отчёты
# связываются с запросом (operation_id). context_id (AUDIT-C) и sequence
# (AUDIT-6A) -- Optional у всех уровней на этой редакции контракта.
ENVELOPE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "server_result": (
        "schema_version", "evidence_level", "operation_id",
        "result_ref", "method",
    ),
    "client_observation": (
        "schema_version", "evidence_level", "operation_id",
    ),
    "user_decision": (
        "schema_version", "evidence_level", "operation_id", "causation_id",
    ),
    "operational": (
        "schema_version", "evidence_level", "operation_id",
    ),
}

# Имена envelope-полей (порядок = порядок ключей to_dict у v2-события).
ENVELOPE_FIELDS: tuple[str, ...] = (
    "schema_version", "evidence_level", "sequence", "operation_id",
    "causation_id", "context_id", "result_ref", "method", "time_quality",
)

# Ожидаемые типы значений при чтении (мусор -- деградация: поле
# отбрасывается на границе, не проходит дальше и не роняет чтение;
# щит из C-CERT).
_ENVELOPE_VALUE_TYPES: dict[str, type] = {
    "schema_version": int,
    "evidence_level": str,
    "sequence": int,
    "operation_id": str,
    "causation_id": str,
    "context_id": str,
    "result_ref": dict,
    "method": dict,
    "time_quality": dict,
}


def _typed_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    """Отбор корректно типизированных envelope-полей stored-события.
    Мусорные значения (чужой тип) -- отбрасываются (честное отсутствие);
    валидно типизированное неизвестное ЗНАЧЕНИЕ (напр. evidence_level вне
    реестра) проходит -- читатель решает сам (журнал, не реестр, R3)."""
    envelope: dict[str, Any] = {}
    for key, py_type in _ENVELOPE_VALUE_TYPES.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) and py_type is int:
            continue  # bool -- подкласс int: schema_version=True -- мусор
        if isinstance(value, py_type):
            envelope[key] = copy.deepcopy(value) if isinstance(value, dict) else value
    return envelope


def validate_envelope(data: dict[str, Any]) -> list[str]:
    """Проверяемая схема обязательности v2 (таблица AUDIT-S):
    возвращает список нарушений (пустой -- всё на месте). v1-событие
    (без schema_version) -- не нарушение: переход «читатели раньше
    писателей» (контракт §7), обязательность -- для v2-записей."""
    violations: list[str] = []
    schema_version = data.get("schema_version")
    if schema_version is None:
        return ["schema_version отсутствует (v1-событие -- не нарушение)"]
    if schema_version != 2:
        violations.append(f"schema_version={schema_version!r}: поддерживается 2")
    evidence = data.get("evidence_level")
    if evidence is None:
        violations.append("evidence_level отсутствует")
    elif evidence not in EVIDENCE_LEVELS:
        violations.append(f"evidence_level={evidence!r} вне реестра")
    level = evidence if evidence in EVIDENCE_LEVELS else None
    if level is None:
        return violations
    for field_name in ENVELOPE_REQUIREMENTS.get(level, ()):
        if data.get(field_name) is None:
            violations.append(
                f"{level}: отсутствует обязательное поле {field_name}"
            )
    return violations


# ── AUDIT-S: стабильная идентичность legacy (I1, F11/P17) ─────────

# Фиксированное пространство имён идентичности трассы: uuid5 от него
# детерминирован между процессами/перезапусками (в отличие от uuid4).
_STABLE_ID_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://cisstat.ts-analysis/progress/trace-identity-v1"
)


def derive_stable_event_id(
    *,
    run_id: str,
    ts: str,
    stage: str,
    node_id: str | None,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Детерминированный event_id для legacy-события БЕЗ идентичности
    (3-польная популяция ForecastRun.trace): uuid5 канонического
    содержимого. Правило ЗАКРЕПЛЕНО (план §5: «выбрать и закрепить
    стабильное правило идентичности, не генерировать новые id при
    каждом чтении»): повторное чтение возвращает тот же id.

    Два независимых действия с одинаковым payload и одинаковым ts до
    микросекунды неразличимы по построению (иной идентичности в legacy
    нет) -- считаются одним фактом; ЯВНЫЕ id всегда приоритетны."""
    material = json.dumps(
        {
            "v": 1,
            "run_id": run_id,
            "ts": ts,
            "stage": stage,
            "node_id": node_id,
            "event_type": event_type,
            "payload": payload,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return str(uuid5(_STABLE_ID_NAMESPACE, material))


def _ts_readable(value: str) -> bool:
    """Нечитаемость ts -- по семантике сортировки отчёта (run_report
    ::_parse_event_ts): datetime.fromisoformat; наивное время читаемо."""
    if not value:
        return True  # отсутствие времени -- не «испорченное время»
    try:
        datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return True


def mark_honest_time(event: "TraceEvent", *, substituted: bool) -> "TraceEvent":
    """Честная маркировка времени на границе записи (F16/P23): событие
    с нечитаемым ts и без time_quality получает
    time_quality={raw_ts, quality, observed_at}; сам ts объекта НЕ
    переписывается (строку для TIMESTAMPTZ-строки строит _ts_to_db
    store'а; durable-хранение маркировки -- миграция AUDIT-6A).

    substituted=False -- store сохраняет raw как есть (Memory);
    substituted=True -- store заменит значение строки записанным сейчас
    (Postgres): quality=substituted, observed_at=время записи.
    Идемпотентно: уже маркированное событие не перемаркируется."""
    if event.time_quality is not None or _ts_readable(event.ts):
        return event
    return replace(
        event,
        time_quality={
            "raw_ts": event.ts,
            "quality": "substituted" if substituted else "degraded",
            "observed_at": _now_iso(),
        },
    )


def stamp_envelope(event: "TraceEvent", **fields: Any) -> "TraceEvent":
    """Точка принятия envelope продюсером (контракт §7: «типы раньше
    полей» -- продюсеры переходят на v2 задачами AUDIT-C/6A/6B/7A).
    Любое непустое поле переводит запись в v2: schema_version=2 ставится
    автоматически (если не задан явно), evidence_level -- из реестра
    resolve_evidence_level (если не задан явно). Незнакомое поле --
    ValueError (fail-closed у фабрики, в отличие от терпимой границы
    чтения)."""
    unknown = set(fields) - set(ENVELOPE_FIELDS)
    if unknown:
        raise ValueError(
            f"Неизвестные envelope-поля: {sorted(unknown)}; "
            f"известные: {list(ENVELOPE_FIELDS)}"
        )
    provided = {key: value for key, value in fields.items() if value is not None}
    if not provided:
        return event
    resolved = dict(provided)
    resolved.setdefault("schema_version", 2)
    resolved.setdefault(
        "evidence_level", resolve_evidence_level(event.event_type, event.payload)
    )
    return replace(event, **resolved)


# ── AUDIT-S: единое чтение канонического порядка (контракт §3.3) ──


def _ts_sort_key(event: dict[str, Any]) -> float:
    """Та же семантика, что sort_events_chronologically отчёта
    (run_report.py): читаемый ts -> epoch-секунды; нечитаемый/пустой --
    в конец с сохранением взаимного порядка (stable sort). Локальная
    реализация: приватный хелпер другого модуля не импортируется
    (прецедент верификации владения PROGR-10)."""
    raw = event.get("ts")
    if not raw:
        return float("inf")
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return float("inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _has_sequence(event: dict[str, Any]) -> bool:
    value = event.get("sequence")
    return isinstance(value, int) and not isinstance(value, bool)


def canonical_event_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ЕДИНОЕ чтение канонического порядка корпуса (контракт §3.3):

    * у ВСЕХ событий есть sequence -- порядок по нему (авторитетная
      позиция ledger; назначит store в AUDIT-6A; stable при равных);
    * иначе (legacy/смешанный корпус) -- стабильная хронология ts,
      нечитаемые/пустые -- в конец с сохранением store-порядка;
      неизвестное время НЕ используется для переупорядочивания.

    Частичный sequence корпус не переупорядочивает (план §5) -- смешение
    «один порядок по append, другой по ts» запрещено (контрпример P12/F08)."""
    if events and all(_has_sequence(event) for event in events):
        return sorted(events, key=lambda event: event["sequence"])
    return sorted(events, key=_ts_sort_key)


def merge_canonical_events(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Слияние источников корпуса (слой 1, артефакты ForecastRun.trace)
    с дедупликацией строго по ОДНОМУ event_id (план §5: «merge удаляет
    повтор одного event_id, но не объединяет независимые действия с
    одинаковыми payload»): первый источник приоритетен (слой 1 --
    авторитетная запись), Независимые события с разными id сохраняются
    даже при байт-совпадающих payload. Итог -- в каноническом порядке
    (canonical_event_order). Несловарные записи пропускаются."""
    seen_ids: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for source in sources:
        for event in source:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "")
            if event_id:
                if event_id in seen_ids:
                    continue  # тот же факт из другого источника
                seen_ids.add(event_id)
            ordered.append(event)
    return canonical_event_order(ordered)


@dataclass(frozen=True)
class TraceEvent:
    """Единое событие трассы исследования (spec_progress.md §4.1) --
    потребляется панелью «Прогресс», Наставником и (в будущем) квантом
    обучения Q/ΔQ (spec_education.md §8-§9).

    Порядок полей сохраняет совместимость прежней позиции event_type;
    все новые поля канона имеют дефолты, поэтому прежние вызовы
    make_trace_event(event_type, **payload) и равенство двух событий
    по 8 каноническим полям не требуют миграции вызывающего кода.

    AUDIT-S: после канона следуют 9 Optional-полей envelope v2
    (контракт v0.2-AUDIT-S §12): schema_version/evidence_level/sequence/
    operation_id/causation_id/context_id/result_ref/method/time_quality.
    Все -- с дефолтом None; to_dict() включает только заполненные
    («незаполняемое поле отсутствует»), поэтому v1-события сериализуются
    как прежде, а dataclass-равенство v1-событий не изменилось.
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=_new_event_id)
    run_id: str = ""
    ts: str = field(default_factory=_now_iso)
    stage: str = "forecasting"
    node_id: str | None = None
    actor: str = "user"
    # ── envelope v2 (AUDIT-S, аддитивно; None = поле отсутствует) ──
    schema_version: int | None = None      # 2 -- запись под контрактом v2
    evidence_level: str | None = None      # один из EVIDENCE_LEVELS
    sequence: int | None = None            # commit sequence ledger (AUDIT-6A)
    operation_id: str | None = None        # идемпотентность операции/delivery
    causation_id: str | None = None        # request/trigger, вызвавший событие
    context_id: str | None = None          # контекст расчёта (AUDIT-C)
    result_ref: dict[str, Any] | None = None   # result_id/artifact/hash
    method: dict[str, Any] | None = None       # algorithm/rule/версии методики
    time_quality: dict[str, Any] | None = None  # honest time (F16/P23)

    @property
    def timestamp(self) -> str:
        """Legacy-алиас канонического ts (spec_forecasting2.md §7):
        сохранён для pydantic-схемы ответа и фронтенд-интерфейса."""
        return self.ts

    def to_dict(self) -> dict[str, Any]:
        """Канонический 8-польный словарь + legacy-алиас `timestamp` +
        ТОЛЬКО заполненные envelope-поля v2 (AUDIT-S).

        Лишний (девятый) ключ сознательно оставлен: ForecastTraceEventSchema
        требует `timestamp` как обязательное поле, лишние ключи pydantic
        фильтрует -- контракт HTTP-ответа не меняется (двойная запись).
        """
        result: dict[str, Any] = {
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
        for key in ENVELOPE_FIELDS:
            value = getattr(self, key)
            if value is not None:
                result[key] = dict(value) if isinstance(value, dict) else value
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, run_id: str = "") -> "TraceEvent":
        """Восстановление из словаря stored-формата (любой версии):
        legacy 3-поля, канонические 8 и канонические 8 + envelope v2 --
        через normalize_trace_event_dict (мусорный envelope отбрасывается
        на границе, честное отсутствие)."""
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
            **{key: data[key] for key in ENVELOPE_FIELDS if key in data},
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


def canonicalize_stored_event(
    raw: dict[str, Any], *, run_id: str = "",
) -> dict[str, Any] | None:
    """Канонизация stored-события артефакта к виду §4.1 С СОХРАНЕНИЕМ
    идентичности (AUDIT-S, F11/P17): имеющиеся event_id/run_id/actor
    сохраняются как есть; событие без id получает стабильный
    derive_stable_event_id (детерминированный, повторное чтение даёт
    тот же id -- новые id при каждом чтении не генерируются).

    Отображаемая семантика прежняя (PROGR-10): stage="forecasting",
    node_id=event_type (4 канонических типа == узлы графа §2);
    envelope v2 проходит чтение, если корректно типизирован.
    Несловарь/пустой event_type -- None (fail-safe пропуск).
    """
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("event_type") or "")
    if not event_type:
        return None
    data = normalize_trace_event_dict(raw, run_id=run_id)
    return {
        "event_id": data["event_id"],
        "run_id": data["run_id"],
        "ts": data["ts"],
        "stage": "forecasting",
        "node_id": event_type,
        "event_type": event_type,
        "payload": dict(data["payload"]),
        "actor": data["actor"],
        **{key: data[key] for key in ENVELOPE_FIELDS if key in data},
    }


def normalize_trace_event_dict(
    raw: dict[str, Any], *, run_id: str = "",
) -> dict[str, Any]:
    """Нормализация stored-события к каноническому 8-польному виду §4.1
    (+ корректно типизированные envelope-поля v2, AUDIT-S).

    Принимает: (а) legacy 3-поля spec_forecasting2.md §7
    (event_type/timestamp/payload -- единственная реальная историческая
    популяция, вся она этапа Прогнозирования); (б) канонический словарь
    (idempotent pass-through); (в) частичный канон -- отсутствующие
    поля заполняются дефолтами. Вход НЕ мутируется; payload копируется.

    AUDIT-S: (1) событие без event_id получает СТАБИЛЬНЫЙ
    derive_stable_event_id -- повторное чтение legacy возвращает тот же
    id (I1; раньше -- новый uuid4 на каждое чтение, F11/P17);
    (2) нечитаемый НЕпустой ts не подменяется и маркируется
    time_quality={raw_ts, quality="degraded", observed_at} (F16/P23:
    «не подменять незаметно now»); валидный/пустой ts поле не получают;
    (3) мусорные envelope-значения отбрасываются (деградация, не 500).
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
    ts_value = str(raw.get("ts") or raw.get("timestamp") or "")
    raw_event_id = str(raw.get("event_id") or "")
    envelope = _typed_envelope(raw)
    if (
        "time_quality" not in envelope
        and ts_value
        and not _ts_readable(ts_value)
    ):
        envelope["time_quality"] = {
            "raw_ts": ts_value,
            "quality": "degraded",
            "observed_at": _now_iso(),
        }
    result: dict[str, Any] = {
        "event_id": raw_event_id or derive_stable_event_id(
            run_id=str(raw.get("run_id") or run_id),
            ts=ts_value,
            stage=base_stage,
            node_id=raw.get("node_id"),
            event_type=str(raw["event_type"]),
            payload=dict(raw.get("payload") or {}),
        ),
        "run_id": str(raw.get("run_id") or run_id),
        "ts": ts_value,
        "stage": base_stage,
        "node_id": raw.get("node_id"),
        "event_type": str(raw["event_type"]),
        "payload": dict(raw.get("payload") or {}),
        "actor": str(raw.get("actor") or "user"),
    }
    result.update(envelope)
    return result
