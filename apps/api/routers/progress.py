# apps/api/routers/progress.py
"""Чтение трассы «Прогресса» (spec_progress.md §5 слой 1, Task PROGR-4).

PROGR-3 дала ЗАПИСЬ внутрисессионного буфера (TraceHookMiddleware ->
AnalysisSession.pipeline_trace), но у правой панели (§6) нет чтения:

  * шапка §6.1 требует run_id («новое, см. §5») и «Начат N мин назад»
    (в слое 1 аналог research_runs.created_at -- ts первого события);
  * «Развернуть трассу» §6.2 -- плоский хронологический список
    trace_events с реальной персистентностью.

Ровно один читающий эндпоинт, namespace /v1/progress/* -- канон
спецификации (§5: /v1/progress/runs/{run_id}/restore -- PROGR-5):

    GET /v1/progress/trace -> {run_id, started_at, events[]}

Сессия -- по cookie (get_or_create_session_id: панель открывается и на
пустой сессии -- ответ с run_id=null/events=[]), чтение через
AnalysisSession.read_pipeline_trace() -- граница нормализации legacy
3-польных записей к канону §4.1 (решения R2/R3 PROGR-3-CERT).

Эндпоинт СОЗНАТЕЛЬНО отсутствует в таблице TRACE_ROUTES хука: читающий
ридер трассы сам не трассируется (иначе каждый рендер панели рос бы в
собственном логе). run_id без активного датасета -- честный null (§5:
run_id появляется по факту первой загрузки; гейт ensure_run_id PROGR-3).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from apps.api.session_store import get_or_create_session_id, get_session_store

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
