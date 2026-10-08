# apps/api/routers/progress.py
"""Чтение/управление трассой «Прогресса» (spec_progress.md §5-§5.3).

PROGR-4 дало чтение внутрисессионного слоя (§5 слой 1):
    GET /v1/progress/trace -> {run_id, started_at, events[]}

PROGR-5 даёт долговременный кросс-сессионный слой (§5 слой 2) и
run-scoped контракт (namespace /v1/progress/runs/{run_id}/...):

  GET  /v1/progress/runs/{run_id}            -- запуск: мета + события +
                                                чекпоинты (шапка §6.1:
                                                «Начат N мин назад» =
                                                created_at; «Развернуть
                                                трассу» §6.2 -- полная
                                                история слоя 2)
  POST /v1/progress/runs/{run_id}/pause      -- §5.2: явная фиксация
                                                run.status = "paused"
  POST /v1/progress/runs/{run_id}/resume     -- возврат к работе
  POST /v1/progress/runs/{run_id}/checkpoints -- §5.1: именованная
                                                ссылка на событие
                                                (паттерн PassportCheckpoint)
  GET  /v1/progress/runs/{run_id}/restore    -- §5.3: новая сессия
                                                (новый cookie) из трассы;
                                                run_id переживает cookie

Читающие/управляющие эндпоинты СОЗНАТЕЛЬНО отсутствуют в таблице
TRACE_ROUTES хука (паттерн PROGR-4: ридер трассы сам не трассируется);
run-level события (run_paused/run_resumed/checkpoint_saved -- §4.1
«session (любая стадия)») пишутся эндпоинтами ЯВНО через
make_trace_event (тот же fail-closed гейт реестра) -- и в слой 2, и в
слой 1 вызывающей сессии (когда она принадлежит этому запуску).

N-2 (находка PROGR-4): stage-level события (node_id=None) нигде не
превращаются в узловые факты; N-4: ответы не содержат семантики
закрытия панели (состояние панели -- во фронтенде).

PROGR-6 -- Наставник v1 (spec_progress.md §7, правило-движок без LLM):

  GET  /v1/progress/runs/{run_id}/mentor/next-step
       -- §7.1 «Следующий шаг»: статусы узлов запуска выводятся из
          фактов трассы слоя 2 (зеркало фронтенд-логики PROGR-4),
          прогоняются через отсортированный по (priority, rule_id)
          список on_demand-правил, возвращается ПЕРВОЕ сработавшее
          (одна рекомендация за раз) + текст пояснения текущей фазы
          (шаблон по последнему активному stage) + краткая сводка
          уже полученных выводов узлов той же стадии; здесь же
          on_demand_with_history-правило «мечется» (§7.2: требует
          истории trace_events, вызывается при открытии Наставника,
          предупреждение показывается в панели, не инлайн в Мастере).
  POST /v1/progress/mentor/sanity-check
       -- §7.2: прогон preview-исхода Мастера (клиент строит
          CorrectionOutcomeSummary из уже полученного preview-ответа --
          переупаковка полей, не новые вычисления) через ВСЕ
          on_correction_result-правила; возвращается ВЕСЬ список
          сработавших предупреждений. Чистое вычисление над телом
          запроса: долговременный слой не нужен (в отличие от
          run-scoped эндпоинтов -- без _durable_ops). Неизвестная пара
          (stage, node_id) -- fail-closed 422 (паттерн make_node_state).

PROGR-7 -- отчёт для пользователя (spec_progress.md §5.4):

  GET  /v1/progress/runs/{run_id}/report?format=md|html
       -- линейный отчёт из trace_events слоя 2: по каждому пройденному
          узлу -- что нашли, что исправили, чем кончилось (факты из
          payload §4.1). Терминология НЕ изобретается заново: методология
          остановок -- тексты «Метрики и алгоритм» ВЕРБАТИМ из единого
          промотированного реестра знаний (apps/api/knowledge,
          EDU-API-1); метки стадий -- stage_labels_ru того же реестра.
          Прогнозирование -- по ссылке на
          GET /v1/session/modeling/forecast/{id}/export.json (§5.4:
          сериализация не дублируется). Движок -- app/core/run_report.py
          (чистый модуль без HTTP). Ридер трассы сам не трассируется;
          слой 2 недоступен -- честный 503 (отчёт по неполной истории
          выдавал бы неполные факты за полные, паттерн PROGR-5/PROGR-6).

PROGR-8 -- Admin-панель (§10) + офлайн-потребители (§9), категория D:

  GET /v1/progress/admin/overview?days=&top=
       -- агрегаты §10 по корпусу (запуски по статусам за период, время
          по стадиям, топ warning/error-узлов, частоты правил §7.1,
          частоты sanity §7.2 по правилу/узлу, предпочтения
          Прогнозирования §9). Движок -- app/core/admin_analytics.py
          (чистый, без HTTP). Пустой корпус -- честные нули
          («старт -- по накоплении данных, не гейтится кодом»).
  GET /v1/progress/admin/case-bank/candidates
       -- отбор кандидатов банка кейсов (§9): алгоритмическая эвристика
          (completed + финальный бэктест-скор + малое число warning-узлов
          + малое число sanity-предупреждений); суммаризация трассы в
          кейс -- офлайн-джоба ВНЕ сервиса (§9 дословно).

  Авторизация §10 дословно: API-ключ с ролью ADMIN, НЕ cookie-сессия
  аналитика (require_admin_role -- та же ролевая модель Role,
  фабрика зависимостей -- паттерн require_capability). Админ-эндпоинты
  не в TRACE_ROUTES (ридеры не трассируются).

  Источник частот §10 -- журнал наблюдений Наставника
  (research_runs.MentorObservation, append-only слой 2):
    * sanity-check записывает сработавшие предупреждения (run-контекст
      из cookie-сессии -- фронтенд шлёт credentials: include, тело
      запроса НЕ меняется); best-effort: сбой журнала не ломает ответ
      (предупреждения вспомогательны, §12 п.8);
    * next-step записывает ВЫДАННУЮ рекомендацию (частота выдач --
      «какие рекомендации даются чаще всего», §10 дословно).

PROGR-10 -- Расхождение №1 (progress_ts_analysis.md vs реализация):

  Единый движок статусов -- app/core/node_status.py (чистый модуль:
  карта EVENT_NODE_STATUS + event_to_dict + resolve_node_id +
  derive_node_statuses + derive_stage_states); один и тот же вывод
  статуса из фактов решений у всех трёх потребителей -- панель,
  Наставник, admin-аналитика (N опросов и клиентское вычисление
  убраны). «Живой опрос profile-эндпоинтов» (§3/§4.2 дизайн-документа)
  сознательно НЕ реализуется; цена -- статус с точностью до последнего
  засеянного события (принята тимлидом: для навигационной панели
  приемлемо).

  GET /v1/progress/trace расширен АДДИТИВНО: панель -- потребитель
  ГОТОВОГО состояния. Сервер сам сливает слой 1 с ForecastRun.trace
  (артефакты session.modeling_artifacts["forecasts"] -- тот же
  источник, что /v1/session/modeling/forecast), канонизирует 3-польную
  запись (ts=timestamp, stage="forecasting", node_id=event_type, чужие
  типы fail-safe пропуск), сортирует хронологически и отдаёт вместе с
  node_statuses (единый движок) и stages (свёртки §12 п.10 + счётчики).
  run_id/event_id у канонизируемых событий НЕ выдумываются: события
  артефакта не становятся якорями чекпоинтов (семантика §5.1 прежняя).
  Второй опрос панели (/v1/session/modeling/forecast) и клиентское
  слияние удалены; started_at -- по-прежнему ts первого события слоя 1
  (§6.1 без изменений); 503 долговременного слоя панель не гасит
  (ридер трассы -- сессионный, без durable-зависимости).
"""
from __future__ import annotations

import logging
import os
import re
import functools
from dataclasses import replace
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.data.file_loader import read_uploaded_file
from app.core.admin_analytics import (
    build_admin_overview,
    select_case_bank_candidates,
)
from app.core.mentor_rules import (
    CorrectionOutcomeSummary,
    evaluate_history_warnings,
    evaluate_next_step,
    evaluate_sanity,
    evaluate_session_advice,
    phase_text,
    stage_node_summary,
)
from app.core.node_status import (
    derive_last_active_stage,
    derive_node_statuses,
    derive_pipeline_node_states,
    derive_stage_states,
    event_to_dict,
)
from app.core.pipeline_graph import (
    CHECK_STATUS_VALUES,
    FORECASTING_STAGE_IDS,
    STAGE_NODES,
    is_known_node,
)
from app.core.run_report import (
    build_report_model,
    render_html,
    render_markdown,
    sort_events_chronologically,
)
from apps.api.auth import require_admin_role
from apps.api.research_runs import (
    MentorObservation,
    ResearchCheckpoint,
    ResearchRun,
    get_dataset_file_store,
    get_research_run_store,
    record_run_event,
    stage_for_run_level_event,
)
from apps.api.session_store import (
    MAX_PIPELINE_TRACE_EVENTS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    AnalysisSession,
    DatasetInfo,
    format_size_label,
    get_or_create_session_id,
    get_session_store,
)
from apps.api.trace_events import KNOWN_STAGES, make_trace_event
from apps.api.column_origin import derived_columns_in_frame, scope_frame
from app.preprocessing.outliers import outliers_summary, profile_outliers

logger = logging.getLogger(__name__)

router = APIRouter()


class StageStateOut(BaseModel):
    """Готовая свёртка стадии для карточки блок-схемы §6.2 (PROGR-10):
    fold -- каноническая fold_status_values (§12 п.10) из единого
    движка; счётчики -- чтобы фронтенд собирал подпись из готовых
    чисел, не пересчитывая узлы (текст -- UI-ответственность)."""

    stage: str
    fold: str
    done_count: int
    warning_nodes: int
    total_nodes: int


class NodeStateOut(BaseModel):
    """Полное состояние узла §3 (PROGR-11) -- зеркало PipelineNodeState
    (app/core/pipeline_graph.py): статус канонического движка + поля,
    прежде не доходившие до панели (расхождение постановки: mode/
    summary_count/status_reason объявлены в датаклассе, но /trace
    отдавал только статус из событий).

    status_reason -- шаблон факта последнего события решения узла;
    PROGR-21: плюс reason-источники уровня стадии (mode_changed/
    target_column_changed -- payload-атрибутированные «Режим: …»/
    «Целевой признак: …», статус не меняют); mode -- эффективный режим
    сессии (auto/enabled/disabled, только
    Валидация/Предобработка, тот же контракт, что у степперов);
    last_touched_at -- ts последнего события узла; summary_count --
    число правого бейджа узла из payload последнего корректировочного
    события (тот же whitelist фактов §4.1; опроса profile-эндпоинтов
    нет -- та же принятая цена расхождения №1, что у статуса)."""

    stage: str
    node_id: str
    status: str
    status_reason: Optional[str] = None
    mode: Optional[str] = None
    last_touched_at: Optional[str] = None
    summary_count: Optional[int] = None


class ProgressTraceResponse(BaseModel):
    """Снимок внутрисессионного слоя трассы (§5 слой 1) для шапки и
    «Развернуть трассу» панели «Прогресс» (§6.1-§6.2).

    events -- канонические 8-польные dict (to_dict §4.1, включая
    legacy-алиас timestamp); порядок -- хронологический (серверное
    слияние слоя 1 с ForecastRun.trace, PROGR-10), фильтры --
    ответственность рендера.

    PROGR-10 (Расхождение №1): node_statuses -- статусы узлов из
    ЕДИНОГО движка (app/core/node_status.py); stages -- свёртки §12 п.10
    + счётчики (готовое состояние карточек). Фронтенд рендерит, не
    вычисляет; поля аддитивны -- старые потребители (шапка/трасса)
    совместимы (N-3).

    PROGR-11: nodes -- полные состояния узлов §3 (все узлы графа в
    порядке §2); аддитивно к node_statuses/stages (N-3).
    """

    run_id: Optional[str] = None
    started_at: Optional[str] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    node_statuses: Dict[str, str] = Field(default_factory=dict)
    stages: List[StageStateOut] = Field(default_factory=list)
    nodes: List[NodeStateOut] = Field(default_factory=list)


def _canonical_forecast_trace_events(
    forecasts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Канонизация ForecastRun.trace к виду §4.1 (PROGR-10): тот же
    источник, что /v1/session/modeling/forecast (артефакты сессии), но
    на стороне СЕРВЕРА -- панель не делает второй опрос и не сливает
    трассы сама.

    Stored-запись артефакта -- канонический dict (event.to_dict в
    _append_event forecasting_session) либо legacy 3-поля
    (event_type/timestamp/payload -- историческая популяция): ts = ts |
    timestamp, stage = "forecasting", node_id = event_type (4
    канонических типа == узлы графа §2); чужие типы -- fail-safe
    пропуск (семантика прежнего collectForecastTraceEvents).

    run_id/event_id НЕ выдумываются и НЕ пробрасываются: события
    артефакта -- не якоря чекпоинтов (§5.1 -- ссылка на
    ИДЕНТИФИЦИРОВАННОЕ событие трассы решения), семантика прежняя.
    """
    events: List[Dict[str, Any]] = []
    for run in (forecasts or {}).values():
        trace = (run or {}).get("trace_events") or []
        for raw in trace:
            if not isinstance(raw, dict):
                continue
            event_type = str(raw.get("event_type") or "")
            if event_type not in FORECASTING_STAGE_IDS:
                continue  # чужие типы fail-safe пропуск (панель PROGR-4)
            events.append(
                {
                    "ts": str(raw.get("ts") or raw.get("timestamp") or ""),
                    "stage": "forecasting",
                    "node_id": event_type,
                    "event_type": event_type,
                    "payload": dict(raw.get("payload") or {}),
                }
            )
    return events


@router.get("/trace", response_model=ProgressTraceResponse)
def get_progress_trace(request: Request, response: Response) -> ProgressTraceResponse:
    """Готовое состояние для панели «Прогресс» (§5 слой 1 + PROGR-10):
    run_id, ts первого события СЛОЯ 1 (шапка §6.1 без изменений),
    слитые сервером события (слой 1 + ForecastRun.trace, хронология),
    node_statuses/stages единого движка. Пустая сессия -- run_id/
    started_at null, events=[] и честные «не начато» (§6.1)."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    layer1 = session.read_pipeline_trace()
    merged = [event_to_dict(event) for event in layer1]
    merged += _canonical_forecast_trace_events(
        session.modeling_artifacts.get("forecasts") or {}
    )
    # Хронология §6.2 (старые раньше новых), нечитаемые ts -- в конец,
    # stable (та же семантика, что у отчёта §5.4 и прежнего фронтенда).
    merged = sort_events_chronologically(merged)
    statuses = derive_node_statuses(merged)
    # PROGR-11: полные состояния узлов §3; mode -- эффективные check-
    # modes СЕССИИ (те же словари, что читают степперы) -- прямое
    # чтение полей сессии, не опрос profile-эндпоинтов.
    node_states = derive_pipeline_node_states(
        merged,
        {
            "validation": session.validation_check_modes,
            "preprocessing": session.preprocessing_check_modes,
        },
    )
    return ProgressTraceResponse(
        run_id=session.run_id or None,
        started_at=layer1[0].ts if layer1 else None,
        events=merged,
        node_statuses=statuses,
        stages=[
            StageStateOut(**state) for state in derive_stage_states(statuses)
        ],
        nodes=[NodeStateOut(**state) for state in node_states],
    )


# ── PROGR-13-A4: отчёт фактов остановок «Загрузки» (дефект 1) ─────────


class UploadStopsReportIn(BaseModel):
    """Тело отчёта модуля «Загрузка» (§7.2-прецедент: клиент строит
    сводку из уже полученных данных -- TsAnalysisUpload.tsx::stopStatus
    вычислен из ответов загрузки/детекции, бэкенд НЕ опрашивает
    profile-эндпоинты повторно).

    stops -- ПОЛНАЯ карта остановок реестра (id -> CheckStatus):
    снапшот состояния модуля, не дельта; партиальные отчёты --
    клиентский баг и fail-closed 422 (чёрные дыры в фактах стадии
    недопустимы: панель обязана совпадать с модулем целиком)."""

    stops: Dict[str, str]


class UploadStopsReportResponse(BaseModel):
    """Эхо приёмки: сколько фактов записано + run_id запуска, в который
    они легли (слой 2 -- тот же механизм зеркала, что у хука §5)."""

    run_id: Optional[str] = None
    reported: int


@router.post("/upload-stops", response_model=UploadStopsReportResponse)
def report_upload_stops(
    payload: UploadStopsReportIn, request: Request, response: Response
) -> UploadStopsReportResponse:
    """Отчёт статусов остановок «Загрузки» от её модуля (PROGR-13-A4,
    закрытие дефекта 1 PROGR-13: панель «Прогресс» показывает 1/5
    остановок и зелёную «Структуру» против жёлтого модуля).

    Факты пишутся СОБЫТИЯМИ трассы (upload_stop_status, payload.status
    из CHECK_STATUS_VALUES -- единый движок node_status читает их через
    resolve_event_status), в слой 1 И зеркалом в слой 2 -- тот же
    двухслойный механизм, что у хука трассы (§5). Валидация fail-closed
    (паттерн sanity-check §7.2): неизвестный узел / недопустимый статус
    / неполная карта -- 422 ДО первой записи (all-or-nothing, чёрных
    дыр в фактах стадии нет). Аналитик без датасета -- 400 (факты
    остановок без исследования не существуют)."""
    stops = payload.stops
    if not stops:
        raise HTTPException(
            status_code=422,
            detail="Карта остановок пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["upload"]
    unknown = sorted(set(stops) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные остановки «Загрузки»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in stops.items()
        if status not in CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус остановок: {invalid}; "
                f"допустимые: {list(CHECK_STATUS_VALUES)} (CheckStatus §3)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in stops]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет остановок: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ остановок реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- остановки «Загрузки» без данных не существуют",
        )
    session.ensure_run_id()
    for node_id in known_ids:
        event = make_trace_event(
            "upload_stop_status",
            stage="upload",
            node_id=node_id,
            run_id=session.run_id,
            status=stops[node_id],
        )
        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов остановок в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return UploadStopsReportResponse(run_id=session.run_id, reported=len(known_ids))


# ── PROGR-16-A: отчёт фактов проверок «Валидации» (дефект
#    PROGR-16-REPRO: «Валидация. Не начато» при цветном модуле) ─────────


class ValidationChecksReportIn(BaseModel):
    """Тело отчёта модуля «Валидация» (прецедент §7.2/PROGR-13-A4:
    клиент строит сводку из УЖЕ ПОЛУЧЕННОГО ответа GET
    /v1/session/dataset/validate -- бэкенд не переопрашивает
    profile-эндпоинты; статус выводится только из засеянных фактов --
    решение Расхождения №1 сохраняется).

    checks -- ПОЛНАЯ карта проверок реестра CHECK_IDS (id -> CheckStatus):
    снапшот состояния модуля после запуска, не дельта; партиальные
    отчёты -- клиентский баг и fail-closed 422 (чёрные дыры в фактах
    стадии недопустимы: панель обязана совпадать с модулем целиком)."""

    checks: Dict[str, str]


class ValidationChecksReportResponse(BaseModel):
    """Эхо приёмки: сколько фактов записано + run_id запуска, в который
    они легли (слой 2 -- тот же механизм зеркала, что у хука §5)."""

    run_id: Optional[str] = None
    reported: int


@router.post(
    "/validation-checks",
    response_model=ValidationChecksReportResponse,
)
def report_validation_checks(
    payload: ValidationChecksReportIn, request: Request, response: Response
) -> ValidationChecksReportResponse:
    """Отчёт статусов проверок «Валидации» от её модуля (PROGR-16-A,
    закрытие дефекта PROGR-16-REPRO: запуск валидации вычислял статусы
    всех 10 проверок, но факт-контур стадии validation не имел носителя
    результатов запуска -- GET /dataset/validate не трассировался,
    клиентского отчёта не существовало, типа события не было в реестре
    §4.1; панель показывала «Валидация. Не начато» при цветном модуле).

    Факты пишутся СОБЫТИЯМИ трассы (validation_check_status,
    payload.status из CHECK_STATUS_VALUES -- единый движок node_status
    читает их через resolve_event_status), в слой 1 И зеркалом в слой 2
    -- тот же двухслойный механизм, что у хука §5 и отчёта остановок
    «Загрузки» (PROGR-13-A4). Валидация fail-closed (паттерн
    sanity-check §7.2): неизвестная проверка / недопустимый статус /
    неполная карта -- 422 ДО первой записи (all-or-nothing, чёрных дыр
    в фактах стадии нет). Аналитик без датасета -- 400 (факты проверок
    без исследования не существуют)."""
    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта проверок пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["validation"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные проверки «Валидации»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус проверок: {invalid}; "
                f"допустимые: {list(CHECK_STATUS_VALUES)} (CheckStatus §3)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет проверок: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ проверок реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- проверки «Валидации» без данных не существуют",
        )
    session.ensure_run_id()
    for node_id in known_ids:
        event = make_trace_event(
            "validation_check_status",
            stage="validation",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )
        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов проверок в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return ValidationChecksReportResponse(
        run_id=session.run_id, reported=len(known_ids)
    )


# ── PROGR-17: отчёт фактов этапов «Предобработки» (spec_progress_
#    v1.1.md §2, категория B -- зеркало /validation-checks PROGR-16-A
#    буквально) ─────────────────────────────────────────────────────────


class PreprocessingChecksReportIn(BaseModel):
    """Тело отчёта модуля «Предобработка» (зеркало
    ValidationChecksReportIn, прецедент §7.2/PROGR-13-A4: клиент строит
    сводку из УЖЕ ПОЛУЧЕННЫХ ответов profile-эндпоинтов -- бэкенд не
    переопрашивает их; статус выводится только из засеянных фактов --
    решение Расхождения №1 сохраняется).

    checks -- ПОЛНАЯ карта остановок реестра PREPROCESSING_CHECK_IDS
    (id -> CheckStatus): снапшот состояния степпера после вычислений,
    не дельта; партиальные отчёты -- клиентский баг и fail-closed 422
    (чёрные дыры в фактах стадии недопустимы: панель обязана совпадать
    с модулем целиком)."""

    checks: Dict[str, str]


class PreprocessingChecksReportResponse(BaseModel):
    """Эхо приёмки: сколько фактов записано + run_id запуска, в который
    они легли (слой 2 -- тот же механизм зеркала, что у хука §5)."""

    run_id: Optional[str] = None
    reported: int


@router.post(
    "/preprocessing-checks",
    response_model=PreprocessingChecksReportResponse,
)
def report_preprocessing_checks(
    payload: PreprocessingChecksReportIn, request: Request, response: Response
) -> PreprocessingChecksReportResponse:
    """Отчёт статусов этапов «Предобработки» от её модуля (PROGR-17,
    spec_progress_v1.1.md §2 категория B -- зеркало /validation-checks
    PROGR-16-A буквально: автозаполнение степпера профилями остановок
    не оставляло следа в факт-контуре стадии preprocessing -- панель
    показывала «не начато» при цветном модуле; тот же класс «нет
    носителя факта прохождения», что закрыт для Валидации).

    Факты пишутся СОБЫТИЯМИ трассы (preprocessing_check_status,
    payload.status из CHECK_STATUS_VALUES -- единый движок node_status
    читает их через resolve_event_status), в слой 1 И зеркалом в слой 2
    -- тот же двухслойный механизм, что у хука §5 и отчётов
    /upload-stops (PROGR-13-A4) и /validation-checks (PROGR-16-A).
    Валидация fail-closed (паттерн sanity-check §7.2): неизвестная
    остановка / недопустимый статус / неполная карта -- 422 ДО первой
    записи (all-or-nothing, чёрных дыр в фактах стадии нет). Аналитик
    без датасета -- 400 (факты этапов без исследования не
    существуют)."""
    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта этапов пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["preprocessing"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные остановки «Предобработки»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус этапов: {invalid}; "
                f"допустимые: {list(CHECK_STATUS_VALUES)} (CheckStatus §3)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет этапов: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ остановок реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- этапы «Предобработки» без данных не существуют",
        )
    session.ensure_run_id()
    for node_id in known_ids:
        event = make_trace_event(
            "preprocessing_check_status",
            stage="preprocessing",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )
        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов этапов в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return PreprocessingChecksReportResponse(
        run_id=session.run_id, reported=len(known_ids)
    )


# ── PROGR-18: отчёт фактов просмотров исследований «EDA»
#    (spec_progress_v1.1.md §2, категория B -- зеркало
#    /preprocessing-checks PROGR-17 / /validation-checks PROGR-16-A) ────

# Словарь ИМЕННО отчёта EDA (решение тимлида, spec_progress_v1.1.md
# §2): статус done/pending по факту «аналитик открыл и просмотрел
# результат»; warning НЕ вводить -- EDA не проверка качества, а анализ,
# критерия ошибки у исследования нет (warning был бы ложной тревогой).
# Отчёт -- факт ПРОСМОТРА, не исход анализа: найденные исследованиями
# особенности (нестационарность, сдвиги, блокировки моделей) остаются
# в модуле, панель отражает прохождение аналитиком. Fail-closed:
# эндпоинт enforced словарь -- чужой статус (даже легальный CheckStatus
# «warning») не доходит до трассы.
EDA_CHECK_STATUS_VALUES: tuple[str, ...] = ("done", "pending")


class EdaChecksReportIn(BaseModel):
    """Тело отчёта модуля «EDA» (зеркало PreprocessingChecksReportIn,
    прецедент §7.2/PROGR-13-A4: клиент строит сводку из УЖЕ ПОЛУЧЕННЫХ
    ответов profile-эндпоинтов -- бэкенд не переопрашивает их; статус
    выводится только из засеянных фактов -- решение Расхождения №1
    сохраняется).

    checks -- ПОЛНАЯ карта исследований реестра EDA_STAGE_IDS
    (id -> "done"|"pending"): снапшот множества просмотренных
    исследований, не дельта; партиальные отчёты -- клиентский баг и
    fail-closed 422 (чёрные дыры в фактах стадии недопустимы: панель
    обязана совпадать с модулем целиком)."""

    checks: Dict[str, str]


class EdaChecksReportResponse(BaseModel):
    """Эхо приёмки: сколько фактов записано + run_id запуска, в который
    они легли (слой 2 -- тот же механизм зеркала, что у хука §5)."""

    run_id: Optional[str] = None
    reported: int


@router.post("/eda-checks", response_model=EdaChecksReportResponse)
def report_eda_checks(
    payload: EdaChecksReportIn, request: Request, response: Response
) -> EdaChecksReportResponse:
    """Отчёт фактов просмотров исследований «EDA» от её модуля (PROGR-18,
    spec_progress_v1.1.md §2 категория B -- зеркало /preprocessing-checks
    PROGR-17 / /validation-checks PROGR-16-A: у стадии eda не было
    носителя факта прохождения -- узлы EDA не достигали done от самого
    модуля (profile_viewed -- running), панель показывала «не начато» /
    «в работе» при просмотренных аналитиком исследованиях; последний
    незакрытый класс «нет носителя факта» из v1.1 §2).

    Семантика статуса -- РЕШЕНИЕ ТИМЛИДА (v1.1 §2): done/pending по
    факту «аналитик открыл и просмотрел результат», warning НЕ вводить
    (ложная тревога там, где нет критерия ошибки). Факты пишутся
    СОБЫТИЯМИ трассы (eda_check_status, payload.status из
    EDA_CHECK_STATUS_VALUES -- единый движок node_status читает их через
    resolve_event_status), в слой 1 И зеркалом в слой 2 -- тот же
    двухслойный механизм, что у хука §5 и отчётов /upload-stops (A4),
    /validation-checks (16-A), /preprocessing-checks (17). Валидация
    fail-closed (паттерн sanity-check §7.2): неизвестное исследование /
    статус вне словаря отчёта EDA / неполная карта -- 422 ДО первой
    записи (all-or-nothing, чёрных дыр в фактах стадии нет). Аналитик
    без датасета -- 400 (факты просмотров без исследования не
    существуют)."""
    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта исследований пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["eda"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные исследования «EDA»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in EDA_CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус исследований: {invalid}; "
                f"словарь отчёта EDA: {list(EDA_CHECK_STATUS_VALUES)} -- "
                "статус по факту «аналитик открыл и просмотрел результат», "
                "warning не вводится (решение тимлида, v1.1 §2: EDA -- "
                "анализ, критерия ошибки нет)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет исследований: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ исследований реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- исследования «EDA» без данных не существуют",
        )
    session.ensure_run_id()
    for node_id in known_ids:
        event = make_trace_event(
            "eda_check_status",
            stage="eda",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )
        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов просмотров в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return EdaChecksReportResponse(
        run_id=session.run_id, reported=len(known_ids)
    )


# ── PROGR-5: долговременный слой (§5 слой 2) ─────────────────────────


class ResearchRunOut(BaseModel):
    run_id: str
    session_id: str
    dataset_fingerprint: str
    dataset_name: str
    target_column: Optional[str] = None
    created_at: str
    last_active_at: str
    status: str


class CheckpointOut(BaseModel):
    checkpoint_id: str
    run_id: str
    event_id: str
    label: str
    has_snapshot: bool
    created_at: str


class RunDetailResponse(ResearchRunOut):
    events: List[Dict[str, Any]] = Field(default_factory=list)
    checkpoints: List[CheckpointOut] = Field(default_factory=list)
    events_total: int = 0


class RunEventResponse(BaseModel):
    run_id: str
    status: str
    event: Dict[str, Any]


class CheckpointCreateRequest(BaseModel):
    """§5.1: чекпоинт -- именованная ссылка на конкретное событие
    трассы + опциональный человекочитаемый комментарий."""

    event_id: str
    label: str = ""


class CheckpointCreatedResponse(BaseModel):
    checkpoint: CheckpointOut
    event: Dict[str, Any]


class RestoreResponse(BaseModel):
    """Факты восстановления (§5.3). Сознательно БЕЗ семантики
    управления панелью (N-4): открыть/закрыть/перейти -- решение
    фронтенда, deep-link узла панель не закрывает."""

    run_id: str
    status: str
    dataset: Dict[str, Any]
    target_column: Optional[str] = None
    last_active_stage: Optional[str] = None
    events_restored: int
    events_total: int


def _require_run(run_id: str) -> ResearchRun:
    run = get_research_run_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Запуск {run_id} не найден")
    return run


def _durable_ops(fn: Callable) -> Callable:
    """Декоратор защитного контура рантайма: сбой долговременного слоя
    (Postgres недоступен/драйвера нет) -- честный 503, а не 500 с сырым
    трейсом. HTTPException проходит насквозь (404/409 -- факты, не сбои)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(
                "Progress: долговременный слой недоступен (%s)", exc, exc_info=True
            )
            raise HTTPException(
                status_code=503, detail="Долговременный слой недоступен"
            ) from exc

    return wrapper


def _require_store():
    try:
        return get_research_run_store()
    except Exception as exc:  # pragma: no cover - защитный контур фабрики
        raise HTTPException(status_code=503, detail="Долговременный слой недоступен") from exc


def _mirror_to_layer1(request: Request, response: Response, run_id: str, event) -> None:
    """Дописывает run-level событие в слой 1 ВЫЗЫВАЮЩЕЙ сессии, когда
    эта сессия принадлежит запуску (панель видит «Пауза»/«Сохранить
    точку» без перечитывания слоя 2). Чужая сессия слой 1 не трогает --
    её трасса про ДРУГОЕ исследование. Best-effort."""
    try:
        session_id = get_or_create_session_id(request, response)
        session_store = get_session_store()
        session = session_store.get(session_id)
        if session is None or session.run_id != run_id:
            return
        session.append_trace_event(event)
        session_store.save(session)
    except Exception:  # pragma: no cover - защитный контур рантайма
        logger.warning("Progress: run-level событие не отражено в слое 1", exc_info=True)


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
@_durable_ops
def get_run_detail(
    run_id: str,
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
) -> RunDetailResponse:
    """Запуск слоя 2: мета (§5) + события (хронология дописывания;
    limit -- ПОСЛЕДНИЕ N, панель/отчёт читают свежий хвост) + чекпоинты
    (§5.1). 503 -- долговременный слой недоступен (деградировать на
    слой 1 нельзя: ответ выдавал бы неполную историю за полную)."""
    store = _require_store()
    run = _require_run(run_id)
    events = store.list_events(run_id)
    events_total = len(events)
    if limit is not None:
        events = events[-limit:]
    checkpoints = store.list_checkpoints(run_id)
    return RunDetailResponse(
        **run.to_dict(),
        events=[event.to_dict() for event in events],
        checkpoints=[CheckpointOut(**checkpoint.to_dict()) for checkpoint in checkpoints],
        events_total=events_total,
    )


@router.post("/runs/{run_id}/pause", response_model=RunEventResponse)
@_durable_ops
def pause_run(request: Request, response: Response, run_id: str) -> RunEventResponse:
    """Пауза (§5.2): явная фиксация run.status="paused" -- отличает
    «аналитик отошёл» от брошенного запуска. Идемпотентности нет: двойная
    пауза -- ошибка клиента (409), не тихий повтор."""
    store = _require_store()
    run = _require_run(run_id)
    if run.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Запуск в статусе {run.status!r}: пауза возможна только из active",
        )
    event = make_trace_event(
        "run_paused", stage=stage_for_run_level_event(store, run_id),
        node_id=None, run_id=run_id,
    )
    store.set_run_status(run_id, "paused")
    store.append_event(run_id, event)
    _mirror_to_layer1(request, response, run_id, event)
    return RunEventResponse(
        run_id=run_id, status="paused", event=event.to_dict()
    )


@router.post("/runs/{run_id}/resume", response_model=RunEventResponse)
@_durable_ops
def resume_run(request: Request, response: Response, run_id: str) -> RunEventResponse:
    """Возврат к работе (§5.2): status -> active + run_resumed (§4.1:
    run-level тип, валиден на любой стадии)."""
    store = _require_store()
    run = _require_run(run_id)
    if run.status != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Запуск в статусе {run.status!r}: возобновить можно только paused",
        )
    event = make_trace_event(
        "run_resumed", stage=stage_for_run_level_event(store, run_id),
        node_id=None, run_id=run_id,
    )
    store.set_run_status(run_id, "active")
    store.append_event(run_id, event)
    _mirror_to_layer1(request, response, run_id, event)
    return RunEventResponse(run_id=run_id, status="active", event=event.to_dict())


@router.post("/runs/{run_id}/checkpoints", response_model=CheckpointCreatedResponse, status_code=201)
@_durable_ops
def create_checkpoint(
    request: Request,
    response: Response,
    run_id: str,
    payload: CheckpointCreateRequest,
) -> CheckpointCreatedResponse:
    """Чекпоинт (§5.1): именованная ссылка на событие трассы, не копия
    (паттерн PassportCheckpoint). Событие обязано существовать в ЭТОМ
    запуске -- ссылки на чужие/фантомные события отклоняются (404).
    Данные: снимок DataFrame сессии запуска (§12 п.4, CSV; последние 5
    на запуск -- prune по списку из хранилища, не по mtime)."""
    store = _require_store()
    run = _require_run(run_id)
    if run.status in ("completed", "abandoned"):
        raise HTTPException(
            status_code=409,
            detail=f"Запуск в статусе {run.status!r}: чекпоинт недоступен",
        )
    referenced = store.get_event(run_id, payload.event_id)
    if referenced is None:
        raise HTTPException(
            status_code=404,
            detail=f"Событие {payload.event_id} не найдено в запуске {run_id}",
        )
    checkpoint = ResearchCheckpoint(
        checkpoint_id=str(uuid4()),
        run_id=run_id,
        event_id=payload.event_id,
        label=payload.label,
    )
    # Снимок данных (§12 п.4) -- только из сессии ЭТОГО запуска: чужая
    # сессия честно создаёт ссылку без снимка.
    session_id = get_or_create_session_id(request, response)
    calling_session = get_session_store().get(session_id)
    if (
        calling_session is not None
        and calling_session.run_id == run_id
        and calling_session.dataframe is not None
    ):
        try:
            if get_dataset_file_store().save_checkpoint_snapshot(
                run_id, checkpoint.checkpoint_id, calling_session.dataframe
            ):
                checkpoint = replace(checkpoint, has_snapshot=True)
        except Exception:  # pragma: no cover - защитный контур диска
            logger.warning("Checkpoint: снимок данных не сохранён", exc_info=True)
    store.add_checkpoint(run_id, checkpoint)
    # §12 п.4: последние 5 снимков на запуск.
    try:
        keep = [checkpoint.checkpoint_id for checkpoint in store.list_checkpoints(run_id)][-5:]
        get_dataset_file_store().prune_checkpoints(run_id, keep=keep)
    except Exception:  # pragma: no cover - защитный контур диска
        logger.warning("Checkpoint: prune снимков не удался", exc_info=True)
    event = make_trace_event(
        "checkpoint_saved", stage=stage_for_run_level_event(store, run_id),
        node_id=None, run_id=run_id,
        checkpoint_id=checkpoint.checkpoint_id,
        event_id=payload.event_id,
        label=payload.label,
    )
    store.append_event(run_id, event)
    _mirror_to_layer1(request, response, run_id, event)
    return CheckpointCreatedResponse(
        checkpoint=CheckpointOut(**checkpoint.to_dict()), event=event.to_dict()
    )


@router.get("/runs/{run_id}/restore", response_model=RestoreResponse)
@_durable_ops
def restore_run(request: Request, response: Response, run_id: str) -> RestoreResponse:
    """Восстановление (§5.3): валидный run_id и status != completed ->
    НОВАЯ AnalysisSession (новый cookie), датасет перезагружается из
    файлового слоя (§12 п.3; нет файла -- честный 409: повторная
    загрузка на аналитике), прогресс -- из trace_events (засев слоя 1
    в пределах cap буфера; полная история остаётся в слое 2).
    Промежуточные состояния DataFrame НЕ восстанавливаются (§5.3) --
    снимки чекпоинтов сохранены, их применение -- отдельный контракт.

    run_id переживает cookie (приёмка плана): новая сессия привязывается
    к ТОМУ ЖЕ запуску, следующие события продолжают его трассу.
    """
    store = _require_store()
    run = _require_run(run_id)
    if run.status == "completed":
        raise HTTPException(status_code=409, detail="Запуск завершён: восстановление закрыто (§5.3)")

    # Датасет из файлового слоя (§12 п.3). Отсутствие -- 409 (§5.3:
    # «восстановление возможно только с ПОВТОРНОЙ загрузкой»).
    source: Optional[Any] = None
    if run.dataset_fingerprint:
        try:
            source = get_dataset_file_store().load(run.dataset_fingerprint)
        except Exception:
            logger.warning("Restore: файловый слой недоступен", exc_info=True)
    if source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Исходный файл датасета недоступен для этого запуска; "
                "загрузите файл повторно (§5.3)"
            ),
        )

    file_like = BytesIO(source.data)
    display_name = run.dataset_name or str(source.meta.get("name") or "dataset.csv")
    # read_uploaded_file выводит формат из суффикса имени: у display-имён
    # бывают людские хвосты («demo_sales.csv (демо-датасет)») -- вытягиваем
    # ИЗВЕСТНОЕ расширение явно, а не «всё после последней точки».
    ext_match = re.search(r"\.(csv|xlsx|xls|tsv|json)\b", display_name.lower())
    source_ext = f".{ext_match.group(1)}" if ext_match else ".csv"
    file_like.name = f"restore{source_ext}"
    try:
        df, _ext = read_uploaded_file(file_like)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="Исходный файл не читается; загрузите файл повторно (§5.3)",
        ) from exc

    # Предыдущие активные запуски вызывавшей сессии (если браузер уже
    # вёл другое исследование) -- abandoned, симметрично новой загрузке.
    old_session_id = request.cookies.get(SESSION_COOKIE_NAME) or ""
    if old_session_id:
        store.supersede_active_runs(old_session_id, keep_run_id=run_id)

    # НОВАЯ сессия (новый cookie, §5.3) -- даже если cookie был.
    new_session_id = uuid4().hex
    session = AnalysisSession(session_id=new_session_id)
    size_label = str(source.meta.get("size_label") or format_size_label(len(source.data)))
    session.set_dataset(
        DatasetInfo(
            dataset_id=str(uuid4()),
            name=run.dataset_name or str(source.meta.get("name") or file_like.name),
            rows=len(df),
            columns=len(df.columns),
            size_label=size_label,
            dataset_fingerprint=run.dataset_fingerprint,
        ),
        df,
    )
    session.run_id = run.run_id  # run переживает cookie -- приёмка плана

    # Прогресс -- из trace_events (засев слоя 1 в пределах cap; §5.3:
    # решения восстанавливаются, промежуточные DataFrame -- нет).
    events = store.list_events(run_id)
    events_total = len(events)
    seeded = events[-MAX_PIPELINE_TRACE_EVENTS:]
    session.pipeline_trace = [dict(event.to_dict()) for event in seeded]
    if run.target_column and run.target_column in df.columns:
        session.set_target_column(run.target_column)
    # PROGR-13-B1: фаза восстановленной сессии -- стадия последнего
    # УЗЛОВОГО факта (единый движок derive_last_active_stage), не хвост
    # трассы: иначе target_column_changed (сеется авто-POST хука на
    # вкладке «Загрузка») делал «Валидацию» текущим этапом и после
    # restore (тот же корень дефекта 2, что у Наставника).
    last_stage = derive_last_active_stage(seeded)
    session.last_active_stage = last_stage

    session_store = get_session_store()
    session_store.save(session)

    # Возврат к работе: статус active + run_resumed (в трассе запуска и
    # в слое 1 новой сессии -- она теперь принадлежит запуску).
    resumed = make_trace_event(
        "run_resumed", stage=last_stage, node_id=None, run_id=run_id,
        restored=True,
    )
    store.upsert_run(
        ResearchRun(
            **{
                **run.to_dict(),
                "session_id": new_session_id,
                "status": "active",
                "last_active_at": resumed.ts,
            }
        )
    )
    store.append_event(run_id, resumed)
    session.append_trace_event(resumed)
    session_store.save(session)

    is_production = bool(os.environ.get("ALLOWED_ORIGINS"))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_session_id,
        httponly=True,
        samesite="none" if is_production else "lax",
        secure=is_production,
        max_age=SESSION_TTL_SECONDS,
    )
    return RestoreResponse(
        run_id=run_id,
        status="active",
        dataset={
            "name": session.dataset.name,
            "rows": session.dataset.rows,
            "columns": session.dataset.columns,
            "size_label": session.dataset.size_label,
        },
        target_column=session.target_column,
        last_active_stage=session.last_active_stage,
        events_restored=len(seeded),
        events_total=events_total,
    )


# ── PROGR-6: Наставник v1 (spec_progress.md §7, правило-движок) ───────


class SanityWarningOut(BaseModel):
    """Предупреждение §7.2 (канон SanityWarning движка)."""

    rule_id: str
    severity: str
    message: str
    suggested_action: Optional[str] = None


class MentorRecommendationOut(BaseModel):
    """Одна рекомендация §7.1 (первое сработавшее on_demand-правило)."""

    rule_id: str
    stage: str
    message: str
    recommended_action: Optional[str] = None


class MentorNodeFactOut(BaseModel):
    """Факт узла сводки стадии: id + статус (человекочитаемые метки --
    на фронте, NODE_LABELS §6.2)."""

    node_id: str
    status: str


class MentorPhaseSummaryOut(BaseModel):
    """Краткая сводка уже полученных выводов узлов стадии (§7.1):
    агрегация фактов трассы -- не новая аналитика, а пересказ."""

    stage: str
    total_nodes: int
    done_count: int
    warning_nodes: int
    nodes: List[MentorNodeFactOut] = Field(default_factory=list)


class MentorNextStepResponse(BaseModel):
    """Ответ «Следующий шаг» (§7.1) + история-предупреждения §7.2.

    N-4: в ответе нет семантики закрытия/навигации панели -- открыть
    «Наставник», перейти по deep-link или закрыть панель решает
    фронтенд; recommended_action -- строка «stage.node_id», переход
    по ней -- ответственность рендера."""

    run_id: str
    run_status: str
    last_active_stage: str
    phase_text: str
    summary: MentorPhaseSummaryOut
    recommendation: Optional[MentorRecommendationOut] = None
    history_warnings: List[SanityWarningOut] = Field(default_factory=list)


class CorrectionOutcomeSummaryIn(BaseModel):
    """Тело sanity-check: нормализованная проекция preview-ответа
    Мастера (§7.2 -- «маппинг тривиален, разный набор полей у
    Missing/Outliers/Regularity сводится к общим именам на клиенте
    перед отправкой»)."""

    stage: str
    node_id: str
    strategy: str = ""
    method: Optional[str] = None
    affected_count_before: int = 0
    changed_count: int = 0
    still_affected_count: int = 0
    rows_before: int = 0
    rows_after: int = 0
    stats_before: Optional[Dict[str, Optional[float]]] = None
    stats_after: Optional[Dict[str, Optional[float]]] = None


class SanityCheckResponse(BaseModel):
    """§7.2: ВЕСЬ список сработавших предупреждений (проблемы
    независимы и не взаимоисключающи), порядок -- реестр правил."""

    warnings: List[SanityWarningOut] = Field(default_factory=list)


def _record_next_step_observation(run_id: str, recommendation: Any) -> None:
    """PROGR-8: факт ВЫДАЧИ рекомендации §7.1 -- в журнал наблюдений
    (частота выдач -- «какие рекомендации даются чаще всего», §10).
    Best-effort (паттерн record_run_event/_mirror_to_layer1): сбой
    журнала не ломает ответ -- рекомендация вспомогательна."""
    if recommendation is None:
        return
    try:
        get_research_run_store().append_mentor_observation(
            MentorObservation(
                run_id=run_id,
                obs_kind="next_step",
                rule_id=recommendation.rule_id,
                stage=recommendation.stage,
                node_id=None,
                severity="",
            )
        )
    except Exception:
        logger.warning(
            "Progress: наблюдение next-step не записано в журнал", exc_info=True
        )


def _derived_spikes_facts(run: ResearchRun) -> dict[str, Any] | None:
    """PROGR-24-ORIGIN-C: факты для правила Наставника derived_spikes --
    проекция профиля ПРОИЗВОДНОЙ области датафрейма сессии запуска.

    Носитель -- та же каноническая функция профиля (profile_outliers,
    шкала карточки iqr-1.5), что питает derived_summary задачи A:
    «пересказ уже посчитанного», числа совпадают с плашкой мастера
    (spec_status_original_series.md, задачи A/B/C). Правила Наставника --
    чистые функции: хранилища сюда не импортируются, данные приносит
    роутер (канон модуля mentor_rules). Best-effort (паттерн
    _record_next_step_observation/_mirror_to_layer1): сессия истекла,
    датасет не активен, производных нет, слой 1 недоступен, мусорные
    метаданные -- None (совета нет), НЕ 500: совет вспомогателен
    (§12 п.8), ядро next-step (статусы/рекомендация слоя 2) от сессии
    не зависит."""
    try:
        if not run.session_id:
            return None
        session = get_session_store().get(run.session_id)
        if session is None or session.dataframe is None:
            return None
        derived_names = derived_columns_in_frame(session)
        if not derived_names:
            return None
        profiles = profile_outliers(
            scope_frame(session.dataframe, derived_names), method="iqr", param=None
        )
        summary = outliers_summary(profiles, total_rows=len(session.dataframe))
        return {
            "total_outliers": int(summary["total_outliers"]),
            "total_columns": len(derived_names),
            "total_numeric_columns": int(summary["total_numeric_columns"]),
            "affected_columns": list(summary["affected_columns"]),
        }
    except Exception:
        logger.warning(
            "Progress: факты производных всплесков недоступны, совет "
            "derived_spikes не выдаётся",
            exc_info=True,
        )
        return None


@router.get("/runs/{run_id}/mentor/next-step", response_model=MentorNextStepResponse)
@_durable_ops
def get_mentor_next_step(run_id: str) -> MentorNextStepResponse:
    """«Следующий шаг» (§7.1): одна рекомендация по трассе слоя 2.

    Статусы узлов выводятся из фактов trace_events запуска
    (derive_node_statuses -- единый движок app/core/node_status.py,
    Расхождение №1 PROGR-10; N-2: run-level события не создают
    узловых фактов). 503 -- долговременный
    слой недоступен (рекомендация по неполной истории выдавала бы
    уверенный совет на неполных данных)."""
    store = _require_store()
    run = _require_run(run_id)
    events = store.list_events(run_id)
    statuses = derive_node_statuses(events)
    recommendation = evaluate_next_step(statuses)
    history_warnings = [
        *evaluate_history_warnings(events),
        # PROGR-24-ORIGIN-C: совет derived_spikes (on_demand_with_session,
        # severity=info) -- тот же канал панели «по запросу»; контракт
        # ответа прежний, в трассу/журнал наблюдений совет не попадает
        # (советы -- не факты, §3.2; консистентно с history-предупреждениями).
        *evaluate_session_advice(_derived_spikes_facts(run)),
    ]
    _record_next_step_observation(run_id, recommendation)

    # PROGR-13-B1: фаза -- стадия последнего УЗЛОВОГО факта решения
    # (единый движок derive_last_active_stage), не хвост трассы:
    # stage-level события (target_column_changed мульти-страничен,
    # passport_captured -- фиксация снимка, run_*) фазу не двигают.
    # Дефект 2: «Идёт этап «Валидация»» без захода на Валидацию.
    last_stage = derive_last_active_stage(events)

    return MentorNextStepResponse(
        run_id=run_id,
        run_status=run.status,
        last_active_stage=last_stage,
        # PROGR-19 (v1.1 §3, категория C): текст фазы обусловлен теми же
        # фактами трассы, что и summary ниже, для ВСЕХ 6 стадий --
        # декларативный реестр STAGE_PHASE_TEXT_RULES в mentor_rules
        # (upload -- частный случай, перенос if/elif PROGR-15-B): текст и
        # сводка одного ответа перестают противоречить друг другу на
        # любой стадии. Статусы и события уже вычислены выше -- ноль
        # дополнительного I/O; контракт ответа прежний (phase_text: str).
        phase_text=phase_text(last_stage, statuses=statuses, events=events),
        summary=MentorPhaseSummaryOut(**stage_node_summary(last_stage, statuses)),
        recommendation=(
            MentorRecommendationOut(
                rule_id=recommendation.rule_id,
                stage=recommendation.stage,
                message=recommendation.message,
                recommended_action=recommendation.recommended_action,
            )
            if recommendation is not None
            else None
        ),
        history_warnings=[
            SanityWarningOut(
                rule_id=warning.rule_id,
                severity=warning.severity,
                message=warning.message,
                suggested_action=warning.suggested_action,
            )
            for warning in history_warnings
        ],
    )


# ── PROGR-7: отчёт для пользователя (spec_progress.md §5.4) ──────────

# Форматы plan_progress.md (md|html): pdf -- не контракт этой задачи,
# неизвестный формат -- честный 422 (fail-closed, паттерн sanity-check).
_REPORT_MEDIA_TYPES: dict[str, str] = {
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


@router.get("/runs/{run_id}/report")
@_durable_ops
def get_run_report(
    run_id: str,
    report_format: str = Query(
        default="md", alias="format", pattern="^(md|html)$"
    ),
) -> Response:
    """Линейный отчёт из trace_events слоя 2 (§5.4): по каждому
    пройденному узлу -- что нашли, что исправили, чем кончилось.
    Методология -- тексты «Метрики и алгоритм» вербатим из реестра
    знаний; Прогнозирование -- ссылкой на export.json, без дублирования
    сериализации. 503 -- долговременный слой недоступен (отчёт по
    неполной истории выдавал бы неполные факты за полные); ответ --
    документ (Response), не pydantic-модель: формат и есть контракт."""
    store = _require_store()
    run = _require_run(run_id)
    events = store.list_events(run_id)
    model = build_report_model(
        run.to_dict(), [event.to_dict() for event in events]
    )
    media_type = _REPORT_MEDIA_TYPES[report_format]
    if report_format == "html":
        content = render_html(model)
        filename = f"report-{run_id}.html"
    else:
        content = render_markdown(model)
        filename = f"report-{run_id}.md"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _record_sanity_observations(
    request: Request,
    outcome: CorrectionOutcomeSummaryIn,
    warnings: List[SanityWarningOut],
) -> None:
    """PROGR-8: сработавшие предупреждения §7.2 -- в журнал наблюдений
    (частота по правилу/узлу §10). Run-контекст -- из cookie-сессии:
    фронтенд шлёт sanity-check с credentials: include, ТЕЛО ЗАПРОСА
    не меняется (обратная совместимость контракта §7.2). Нет cookie /
    сессии / run_id -- записей нет (предупреждение вне исследования
    не существует для корпуса). Best-effort: сбой журнала НЕ ломает
    ответ -- предупреждения вспомогательны (§12 п.8)."""
    if not warnings:
        return
    try:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_id:
            return
        session = get_session_store().get(session_id)
        if session is None or not session.run_id:
            return
        store = get_research_run_store()
        for warning in warnings:
            store.append_mentor_observation(
                MentorObservation(
                    run_id=session.run_id,
                    obs_kind="sanity_warning",
                    rule_id=warning.rule_id,
                    stage=outcome.stage,
                    node_id=outcome.node_id,
                    severity=warning.severity,
                )
            )
    except Exception:
        logger.warning(
            "Progress: sanity-наблюдения не записаны в журнал", exc_info=True
        )


@router.post("/mentor/sanity-check", response_model=SanityCheckResponse)
def run_mentor_sanity_check(
    payload: CorrectionOutcomeSummaryIn, request: Request
) -> SanityCheckResponse:
    """Sanity-проверка preview-исхода Мастера (§7.2): ВЕСЬ список
    сработавших предупреждений над нормализованным исходом.

    Проверка встраивается в шаг «Предпросмотр» ДО применения
    (preview=true, §7.2) -- аналитик видит предупреждение прежде, чем
    нажмёт «Применить исправления»; не блокирует действие (§12 п.8).
    Чистое вычисление: без долговременного слоя (POST умышленно, тело
    несёт данные; результат зависит только от тела запроса)."""
    if payload.stage not in KNOWN_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестная стадия: {payload.stage!r}; известные: {list(KNOWN_STAGES)}",
        )
    if not is_known_node(payload.stage, payload.node_id):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестный узел {payload.node_id!r} стадии "
                f"{payload.stage!r} (§2 -- фантомных узлов нет)"
            ),
        )
    outcome = CorrectionOutcomeSummary(
        stage=payload.stage,
        node_id=payload.node_id,
        strategy=payload.strategy,
        method=payload.method,
        affected_count_before=payload.affected_count_before,
        changed_count=payload.changed_count,
        still_affected_count=payload.still_affected_count,
        rows_before=payload.rows_before,
        rows_after=payload.rows_after,
        stats_before=(
            dict(payload.stats_before) if payload.stats_before is not None else None
        ),
        stats_after=(
            dict(payload.stats_after) if payload.stats_after is not None else None
        ),
    )
    warnings = evaluate_sanity(outcome)
    result = SanityCheckResponse(
        warnings=[
            SanityWarningOut(
                rule_id=warning.rule_id,
                severity=warning.severity,
                message=warning.message,
                suggested_action=warning.suggested_action,
            )
            for warning in warnings
        ]
    )
    _record_sanity_observations(request, payload, result.warnings)
    return result


# ── PROGR-8: Admin-панель (§10) + офлайн-потребители (§9) ────────────

# Схемы ответов -- зеркало моделей движка app/core/admin_analytics.py
# (движок чистый, без HTTP; сериализация -- ответственность роутера,
# паттерн run_report.py PROGR-7).


class StageSpanStatOut(BaseModel):
    """Время по стадии (агрегат по запускам, минуты)."""

    stage: str
    runs_with_stage: int
    mean_minutes: float
    median_minutes: float


class NodeProblemOut(BaseModel):
    """Узел с финальным статусом warning/error по запускам."""

    stage: str
    node_id: str
    status: str
    count: int


class RuleFrequencyOut(BaseModel):
    """Частота правила (§7.1 next_step / §7.2 по правилу)."""

    rule_id: str
    stage: str
    count: int


class SanityNodeFrequencyOut(BaseModel):
    """Частота sanity-предупреждений §7.2 по узлу."""

    stage: str
    node_id: str
    count: int


class ValueFrequencyOut(BaseModel):
    """Частота значения (model_id / horizon / alpha, §9)."""

    value: str
    count: int


class AdminOverviewResponse(BaseModel):
    """Агрегаты §10 по корпусу. Пустой корпус -- честные нули
    (старт -- по накоплении данных, не гейтится кодом)."""

    generated_at: str
    period_days: int
    runs_total_all_time: int
    runs_total_in_period: int
    runs_by_status: Dict[str, int] = Field(default_factory=dict)
    stage_time: List[StageSpanStatOut] = Field(default_factory=list)
    top_problem_nodes: List[NodeProblemOut] = Field(default_factory=list)
    next_step_frequency: List[RuleFrequencyOut] = Field(default_factory=list)
    sanity_by_rule: List[RuleFrequencyOut] = Field(default_factory=list)
    sanity_by_node: List[SanityNodeFrequencyOut] = Field(default_factory=list)
    forecasting_model_frequency: List[ValueFrequencyOut] = Field(default_factory=list)
    forecasting_horizon_frequency: List[ValueFrequencyOut] = Field(default_factory=list)
    forecasting_alpha_frequency: List[ValueFrequencyOut] = Field(default_factory=list)


class CaseBankCandidateOut(BaseModel):
    """Кандидат банка кейсов (§9): run_id + доказательства отбора."""

    run_id: str
    status: str
    dataset_name: str
    created_at: str
    backtest_mape: float
    warning_nodes: int
    sanity_warnings: int


class CaseBankResponse(BaseModel):
    """Отбор кандидатов §9 + эхо-порогов (прозрачность для панели) +
    total_completed -- сколько завершённых запусков рассматривалось."""

    candidates: List[CaseBankCandidateOut] = Field(default_factory=list)
    total_completed: int = 0
    criteria: Dict[str, float] = Field(default_factory=dict)


@router.get("/admin/overview", response_model=AdminOverviewResponse)
@_durable_ops
def get_admin_overview(
    principal: Any = Depends(require_admin_role),
    days: int = Query(default=30, ge=1, le=730, alias="days"),
    top: int = Query(default=10, ge=1, le=50, alias="top"),
) -> AdminOverviewResponse:
    """Агрегаты §10 по корпусу (research_runs/trace_events + журнал
    наблюдений Наставника), БЕЗ раскрытия содержимого датасетов
    пользователей. Слой 2 недоступен -- честный 503 (агрегаты по
    неполному корпусу выдавали бы неполную картину за полную,
    паттерн PROGR-5/6/7)."""
    store = _require_store()
    runs = store.list_runs()
    events_by_run = {run.run_id: store.list_events(run.run_id) for run in runs}
    observations = [
        obs.to_dict() for obs in store.list_mentor_observations()
    ]
    model = build_admin_overview(
        [run.to_dict() for run in runs],
        events_by_run,
        observations,
        period_days=days,
        top_limit=top,
    )
    return AdminOverviewResponse(
        generated_at=model.generated_at,
        period_days=model.period_days,
        runs_total_all_time=model.runs_total_all_time,
        runs_total_in_period=model.runs_total_in_period,
        runs_by_status=model.runs_by_status,
        stage_time=[item.to_dict() for item in model.stage_time],
        top_problem_nodes=[item.to_dict() for item in model.top_problem_nodes],
        next_step_frequency=[item.to_dict() for item in model.next_step_frequency],
        sanity_by_rule=[item.to_dict() for item in model.sanity_by_rule],
        sanity_by_node=[item.to_dict() for item in model.sanity_by_node],
        forecasting_model_frequency=[
            item.to_dict() for item in model.forecasting_model_frequency
        ],
        forecasting_horizon_frequency=[
            item.to_dict() for item in model.forecasting_horizon_frequency
        ],
        forecasting_alpha_frequency=[
            item.to_dict() for item in model.forecasting_alpha_frequency
        ],
    )


@router.get("/admin/case-bank/candidates", response_model=CaseBankResponse)
@_durable_ops
def get_case_bank_candidates(
    principal: Any = Depends(require_admin_role),
    max_backtest_mape: float = Query(default=30.0, gt=0),
    max_warning_nodes: int = Query(default=2, ge=0),
    max_sanity_warnings: int = Query(default=2, ge=0),
) -> CaseBankResponse:
    """Отбор кандидатов банка кейсов (§9): алгоритмическая эвристика
    над корпусом; отобранные run_id идут в офлайн-процесс суммаризации
    трассы (LLM-джоба вне сервиса, §9 дословно). MAPE lower-is-better:
    порог -- максимум (честная инверсия «скор выше порога» §9)."""
    store = _require_store()
    runs = store.list_runs()
    events_by_run = {run.run_id: store.list_events(run.run_id) for run in runs}
    observations = [
        obs.to_dict() for obs in store.list_mentor_observations()
    ]
    candidates = select_case_bank_candidates(
        [run.to_dict() for run in runs],
        events_by_run,
        observations,
        max_backtest_mape=max_backtest_mape,
        max_warning_nodes=max_warning_nodes,
        max_sanity_warnings=max_sanity_warnings,
    )
    return CaseBankResponse(
        candidates=[item.to_dict() for item in candidates],
        total_completed=sum(
            1 for run in runs if run.status == "completed"
        ),
        criteria={
            "max_backtest_mape": max_backtest_mape,
            "max_warning_nodes": max_warning_nodes,
            "max_sanity_warnings": max_sanity_warnings,
        },
    )
