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

from apps.api.schemas import (
    ColumnStatsOut,
    DatasetStatsResponse,
    DatasetSummaryOut,
    SessionStateResponse,
    TargetColumnRequest,
    TargetColumnResponse,
    UploadResponse,
)
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    format_size_label,
    get_or_create_session_id,
    get_session_store,
)
from apps.api.upload_common import _compute_column_info, _compute_parse_warnings, _compute_quality_teaser

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
        target_column=session.target_column,
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
    store = get_session_store()
    session = store.get_or_create(session_id)

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
    # КОНТРАКТ SessionStore: мутация -- обязательно save().
    store.save(session)
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
        parse_warnings=_compute_parse_warnings(df),
        error=None,
    )


def _distribution_hint(skew: float, kurtosis: float) -> str:
    """Грубая эвристика по форме распределения -- ориентир для аналитика
    на вкладке «Загрузка», НЕ замена KS-теста с фиттингом распределений
    в «Моделировании» (тот делает содержательный статистический вывод)."""
    if abs(skew) < 0.5 and abs(kurtosis) < 1:
        return "Близко к нормальному"
    if skew >= 0.5:
        return "Правосторонняя асимметрия (длинный правый хвост)"
    if skew <= -0.5:
        return "Левосторонняя асимметрия (длинный левый хвост)"
    if kurtosis >= 1:
        return "Островершинное (тяжёлые хвосты)"
    return "Плосковершинное"


@router.get("/dataset/stats", response_model=DatasetStatsResponse)
def get_dataset_stats(request: Request, response: Response):
    """
    Описательная статистика по числовым колонкам -- пункт 4 контракта
    вкладки «Загрузка» (Mean/Median/Std/Skewness/Kurtosis/Q1/Q3/IQR).
    Считается по ПОЛНОМУ столбцу из session.dataframe, не по превью
    (5+5 строк недостаточно для содержательной статистики).
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    columns_out: list[ColumnStatsOut] = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        if len(series) < 2:
            continue
        q1, q3 = float(series.quantile(0.25)), float(series.quantile(0.75))
        skew = float(series.skew())
        kurt = float(series.kurt())  # pandas: excess kurtosis (0 = нормальное)
        columns_out.append(
            ColumnStatsOut(
                name=str(col),
                mean=float(series.mean()),
                median=float(series.median()),
                std=float(series.std()) if len(series) > 1 else 0.0,
                skewness=skew,
                kurtosis=kurt,
                q1=q1,
                q3=q3,
                iqr=q3 - q1,
                distribution_hint=_distribution_hint(skew, kurt),
            )
        )
    return DatasetStatsResponse(columns=columns_out)


# ────────────────────────────────────────────────────────────────────
# Phase 0.5: target column (мост Upload → Backtest)
# ────────────────────────────────────────────────────────────────────


def _get_numeric_columns(df: pd.DataFrame) -> list[str]:
    """Возвращает имена числовых колонок DataFrame.

    Целевая (target) колонка для TS-прогноза обязана быть числовой --
    прогнозировать категориальную величину baseline-модели не умеют.
    Сюда попадают int*, float* и bool (pandas treat bool как numeric).
    """
    return [str(c) for c in df.select_dtypes(include="number").columns]


@router.get("/target-column", response_model=TargetColumnResponse)
def get_target_column(request: Request, response: Response):
    """Получить текущую target_column + список доступных числовых колонок.

    Используется UI для:
      1. Отрисовать селектор с доступными колонками
      2. Подсветить текущий выбор (target_column из сессии)
      3. Решить, показывать ли селектор вообще (has_dataset=False → скрыть)

    Не возвращает 404 при отсутствии датасета -- UI должен уметь
    обрабатывать состояние "датасета нет, выбор невозможен". Возврат
    target_column=None, available_columns=[], has_dataset=False.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)

    if session.dataframe is None:
        return TargetColumnResponse(
            target_column=None,
            available_columns=[],
            has_dataset=False,
        )

    return TargetColumnResponse(
        target_column=session.target_column,
        available_columns=_get_numeric_columns(session.dataframe),
        has_dataset=True,
    )


@router.post("/target-column", response_model=TargetColumnResponse)
def set_target_column(
    payload: TargetColumnRequest,
    request: Request,
    response: Response,
):
    """Установить выбранную пользователем прогнозируемую колонку.

    Это мост Upload → Backtest: после выбора target_column зеркальный
    эндпоинт /v1/internal/models/backtest будет использовать РЕАЛЬНЫЙ ряд
    из session.dataframe[target_column] вместо синтетического.

    ВАЛИДАЦИЯ:
      1. Датасет должен быть загружен -- иначе 400 (нечего выбирать)
      2. Колонка должна существовать в df -- иначе 404
      3. Колонка должна быть числовой -- иначе 422 (TS-target обязан быть numeric)

    После валидации мутирует session.target_column и ОБЯЗАТЕЛЬНО
    вызывает store.save() (контракт SessionStore, см. session_store.py).
    """
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)

    if session.dataframe is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет — целевую колонку нельзя выбрать без активного датасета",
        )

    df = session.dataframe
    column = payload.column

    # 2. Существование колонки
    if column not in [str(c) for c in df.columns]:
        raise HTTPException(
            status_code=404,
            detail=f"Колонка '{column}' не найдена в датасете. "
            f"Доступные колонки: {list(df.columns)}",
        )

    # 3. Числовой тип (TS-target обязан быть numeric)
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise HTTPException(
            status_code=422,
            detail=f"Колонка '{column}' не является числовой (тип: {df[column].dtype}). "
            f"Целевая колонка для прогноза обязана быть числовой. "
            f"Доступные числовые колонки: {_get_numeric_columns(df)}",
        )

    session.set_target_column(column)
    # КОНТРАКТ SessionStore: мутация -- обязательно save().
    store.save(session)

    return TargetColumnResponse(
        target_column=session.target_column,
        available_columns=_get_numeric_columns(df),
        has_dataset=True,
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
    store = get_session_store()
    session = store.get_or_create(session_id)
    if status not in ("pending", "in_progress", "done"):
        raise HTTPException(status_code=422, detail="status должен быть pending|in_progress|done")
    session.set_stage(stage, status)
    # КОНТРАКТ SessionStore: мутация -- обязательно save().
    store.save(session)
    return _to_response(session)
    