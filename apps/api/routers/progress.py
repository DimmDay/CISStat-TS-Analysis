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

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.data.file_loader import read_uploaded_file
from apps.api.research_runs import (
    ResearchCheckpoint,
    ResearchRun,
    get_dataset_file_store,
    get_research_run_store,
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

logger = logging.getLogger(__name__)

router = APIRouter()


class ProgressTraceResponse(BaseModel):
    """Снимок внутрисессионного слоя трассы (§5 слой 1) для шапки и
    «Развернуть трассу» панели «Прогресс» (§6.1-§6.2).

    events -- канонические 8-польные dict (to_dict §4.1, включая
    legacy-алиас timestamp); chronology -- порядок дописывания (старые
    раньше новых), сортировка/фильтры -- ответственность рендера.
    """

    run_id: Optional[str] = None
    started_at: Optional[str] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/trace", response_model=ProgressTraceResponse)
def get_progress_trace(request: Request, response: Response) -> ProgressTraceResponse:
    """Трасса слоя 1 текущей сессии: run_id, ts первого события и список
    событий в порядке дописывания. Пустая сессия -- run_id/started_at
    null и events=[] (панель показывает честные прочерки, §6.1)."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    events = session.read_pipeline_trace()
    return ProgressTraceResponse(
        run_id=session.run_id or None,
        started_at=events[0].ts if events else None,
        events=[event.to_dict() for event in events],
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
    last_stage = seeded[-1].stage if seeded and seeded[-1].stage in KNOWN_STAGES else "upload"
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



