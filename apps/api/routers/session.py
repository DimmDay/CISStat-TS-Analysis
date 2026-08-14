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

from apps.api.chart_data import MAX_ZOOM_POINTS, build_histogram, build_kde, build_scatter_series
from apps.api.schemas import (
    ColumnStatsOut,
    ColumnStatsValues,
    DatasetStatsResponse,
    DatasetSummaryOut,
    DistributionChartResponse,
    HistogramBin,
    KdePoint,
    PanelBalanceResponse,
    ScatterPoint,
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

    ИСПРАВЛЕНО: раньше колонки с <2 непустых значений молча пропадали
    из ответа без объяснения ("Статистика недоступна для этой колонки" --
    неинформативно на реальных разреженных данных, см. чат). Теперь
    колонка ВСЕГДА присутствует в ответе, с честным non_null_count;
    stats=None только когда значений действительно недостаточно.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    min_for_stats = 2
    columns_out: list[ColumnStatsOut] = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        non_null_count = len(series)
        if non_null_count < min_for_stats:
            columns_out.append(ColumnStatsOut(name=str(col), non_null_count=non_null_count, stats=None))
            continue
        q1, q3 = float(series.quantile(0.25)), float(series.quantile(0.75))
        skew = float(series.skew())
        kurt = float(series.kurt())  # pandas: excess kurtosis (0 = нормальное)
        columns_out.append(
            ColumnStatsOut(
                name=str(col),
                non_null_count=non_null_count,
                stats=ColumnStatsValues(
                    mean=float(series.mean()),
                    median=float(series.median()),
                    std=float(series.std()),
                    skewness=skew,
                    kurtosis=kurt,
                    q1=q1,
                    q3=q3,
                    iqr=q3 - q1,
                    distribution_hint=_distribution_hint(skew, kurt),
                ),
            )
        )
    return DatasetStatsResponse(columns=columns_out, min_non_null_for_stats=min_for_stats)


@router.get("/dataset/panel-balance", response_model=PanelBalanceResponse)
def get_panel_balance(date_col: str, entity_col: str, request: Request, response: Response):
    """
    Balanced/Unbalanced для панельных данных -- пункт 8 контракта
    (структурный класс, визуальная схема на остановке «Структура»).
    Требует ПОЛНЫЙ датасет -- сравнивает множество дат у каждой группы,
    превью (5+5 строк) для этого недостаточно, поэтому отдельный
    эндпоинт поверх session.dataframe, а не клиентская эвристика.

    Read-only -- не мутирует AnalysisSession, save() не требуется.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if date_col not in df.columns or entity_col not in df.columns:
        raise HTTPException(status_code=422, detail="Указанная колонка отсутствует в датасете")

    date_sets = df.groupby(entity_col)[date_col].apply(lambda s: frozenset(s.dropna()))
    n_entities = len(date_sets)
    n_distinct_date_sets = date_sets.nunique() if n_entities > 0 else 0

    return PanelBalanceResponse(
        balanced=n_distinct_date_sets <= 1,
        n_entities=n_entities,
        n_distinct_date_sets=int(n_distinct_date_sets),
    )


@router.get("/dataset/distribution", response_model=DistributionChartResponse)
def get_dataset_distribution(
    column: str,
    request: Request,
    response: Response,
    start: int | None = None,
    end: int | None = None,
):
    """
    Данные для трёх графиков остановки «Распределение» вкладки «Загрузка»
    (точечный/гистограмма/KDE) -- пункт 3 контракта, ранее placeholder
    (см. TsAnalysisUpload.tsx). Реальный расчёт (numpy/scipy) над ПОЛНЫМ
    столбцом сессии -- тот же принцип, что и в get_dataset_stats.

    start/end (опционально) -- позиции в очищенном от NaN столбце (0-based,
    полуоткрытый интервал [start, end)). Нужны для zoom: когда пользователь
    приближает часть точечного графика на фронтенде, запрашивается более
    узкий диапазон с полным разрешением (без LTTB-сэмплинга, либо с более
    мягким порогом), а не тот же общий сэмплированный набор точек.

    Гистограмма и KDE ВСЕГДА считаются по полному столбцу (или по диапазону
    start/end, если он задан) -- сэмплинг применяется только к scatter,
    иначе форма распределения на гистограмме/KDE была бы искажена самим
    фактом прореживания точек для scatter.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise HTTPException(status_code=422, detail=f"Колонка '{column}' не числовая -- график распределения недоступен")

    series = df[column].dropna()
    non_null_count = len(series)

    if start is not None or end is not None:
        range_start = max(0, start or 0)
        range_end = min(non_null_count, end if end is not None else non_null_count)
        if range_start >= range_end:
            raise HTTPException(status_code=422, detail="Некорректный диапазон start/end")
        zoomed = series.iloc[range_start:range_end]
        # Диапазон уже узкий (пользователь приблизил область на фронтенде) --
        # полное разрешение имеет смысл вплоть до MAX_ZOOM_POINTS, не
        # TARGET_SAMPLED_POINTS общего обзора.
        scatter = build_scatter_series(
            zoomed, max_points=MAX_ZOOM_POINTS, full_threshold=MAX_ZOOM_POINTS
        )
        # x в scatter должен остаться в координатах ПОЛНОГО ряда, а не
        # локального среза -- иначе точки "поплывут" при сравнении с
        # предыдущим (не увеличенным) графиком.
        for p in scatter["points"]:
            p["x"] += range_start
        stats_series = zoomed
    else:
        scatter = build_scatter_series(series)
        stats_series = series

    if non_null_count == 0:
        return DistributionChartResponse(
            column=column,
            non_null_count=0,
            scatter=[],
            scatter_sampled=False,
            scatter_sampling_method=None,
            scatter_original_count=0,
            histogram=[],
            kde=None,
        )

    return DistributionChartResponse(
        column=column,
        non_null_count=non_null_count,
        min=float(stats_series.min()),
        max=float(stats_series.max()),
        scatter=[ScatterPoint(**p) for p in scatter["points"]],
        scatter_sampled=scatter["sampled"],
        scatter_sampling_method=scatter["sampling_method"],
        scatter_original_count=scatter["original_count"],
        histogram=[HistogramBin(**b) for b in build_histogram(stats_series)],
        kde=[KdePoint(**p) for p in kde_points] if (kde_points := build_kde(stats_series)) is not None else None,
    )


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
    