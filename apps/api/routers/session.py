# apps/api/routers/session.py
"""
Сессия анализа (AnalysisSession) -- ОБЩИЙ роутер, НЕ дублируется под
/v1/public и /v1/internal. Причина: сессия идентифицируется cookie
браузера, а не API-ключом -- нужна одинаково embedded- и
standalone-фронтенду, включая неавторизованного посетителя standalone,
у которого никакого API-ключа ещё нет. Дублировать под двумя
префиксами означало бы наступить на те же грабли "N копий одной
функции", о которых предупреждает docs/MIGRATION_ARCHITECTURE.md §7.2.

Используется Home page (packages/ui/components/EmbeddedHome.tsx,
apps/standalone/components/StandaloneHome.tsx) для sessions-aware
логики "рабочий стол vs онбординг/маркетинг".
"""
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Request, Response

from apps.api.schemas import DatasetSummaryOut, SessionStateResponse, UploadResponse
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    format_size_label,
    get_or_create_session_id,
    get_session_store,
)
from apps.api.upload_common import _compute_column_info, _compute_quality_teaser

router = APIRouter()

DEMO_DATASET_PATH = Path(__file__).resolve().parent.parent / "demo_data" / "sales_demo.csv"


def _to_response(session: AnalysisSession) -> SessionStateResponse:
    dataset = None
    if session.dataset:
        dataset = DatasetSummaryOut(
            dataset_id=session.dataset.dataset_id,
            name=session.dataset.name,
            rows=session.dataset.rows,
            columns=session.dataset.columns,
            size_label=session.dataset.size_label,
        )
    return SessionStateResponse(
        has_active_dataset=session.dataset is not None,
        dataset=dataset,
        stages=session.stages,
        last_active_stage=session.last_active_stage,
        updated_at=session.updated_at,
    )


@router.get("/current", response_model=SessionStateResponse)
def get_current_session(request: Request, response: Response):
    """Вызывается Home page при монтировании -- решает "рабочий стол vs
    онбординг/маркетинг" по has_active_dataset. Создаёт cookie сессии
    при первом визите, если её ещё нет (пустая сессия, всё pending)."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    return _to_response(session)


@router.post("/demo", response_model=SessionStateResponse)
def load_demo_dataset(request: Request, response: Response):
    """«Попробовать на демо-данных» -- кнопка на Home (embedded онбординг,
    по решению тимлида: снимает барьер "нет своего файла под рукой")."""
    if not DEMO_DATASET_PATH.exists():
        raise HTTPException(status_code=500, detail="Демо-датасет не найден на сервере")

    df = pd.read_csv(DEMO_DATASET_PATH)
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)

    session.set_dataset(
        DatasetInfo(
            dataset_id="demo-sales",
            name="demo_sales.csv (демо-датасет)",
            rows=len(df),
            columns=len(df.columns),
            size_label=format_size_label(DEMO_DATASET_PATH.stat().st_size),
        ),
        df,
    )
    return _to_response(session)


@router.get("/dataset", response_model=UploadResponse)
def get_session_dataset(request: Request, response: Response):
    """
    Восстанавливает превью/техинфо/качество для уже загруженного в сессию
    датасета -- нужно, когда пользователь попадает на «Загрузку» не через
    сам аплоад, а по кнопке «Продолжить» с Home при уже активном датасете
    в сессии (см. WorkbenchSummary). Пересчитывает из session.dataframe --
    тот же DataFrame, что видел исходный upload, не запрашивает файл заново.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataset is None or session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    head_rows = df.head(5).values.tolist()
    tail_rows = df.tail(5).values.tolist()
    head = [[str(cell) for cell in row] for row in head_rows]
    tail = [[str(cell) for cell in row] for row in tail_rows]
    head = [[str(col) for col in df.columns.tolist()]] + head

    return UploadResponse(
        dataset_id=session.dataset.dataset_id,
        name=session.dataset.name,
        rows=session.dataset.rows,
        columns=session.dataset.columns,
        preview={"head": head, "tail": tail},
        columns_info=_compute_column_info(df),
        quality=_compute_quality_teaser(df),
        size_label=session.dataset.size_label,
        error=None,
    )


@router.post("/stage/{stage}", response_model=SessionStateResponse)
def set_stage(stage: str, status: str, request: Request, response: Response):
    """
    Отмечает этап пайплайна как in_progress/done.

    ОХВАТ ЭТОЙ ЗАДАЧИ: сейчас этот эндпоинт вызывается только неявно,
    через set_dataset() внутри upload_common.py (upload автоматически
    ставит stages.upload = "done"). Остальные модули (Валидация,
    Предобработка, EDA, Моделирование, Прогнозирование) ЕЩЁ НЕ вызывают
    его явно при переходе пользователя на страницу -- подключить по
    мере того, как каждый из них перестаёт быть ModulePlaceholder
    (см. README.md, таблицу "что доделать"). До этого момента
    lastActiveStage на Home всегда будет "upload", пока пользователь не
    дойдёт до готового модуля дальше по пайплайну.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if status not in ("pending", "in_progress", "done"):
        raise HTTPException(status_code=422, detail="status должен быть pending|in_progress|done")
    session.set_stage(stage, status)
    return _to_response(session)
