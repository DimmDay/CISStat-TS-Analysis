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
import re
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Request, Response

from apps.api.chart_data import MAX_ZOOM_POINTS, build_histogram, build_kde, build_scatter_series, build_timeseries_points
from apps.api.decomposition_data import build_decomposition, build_decomposition_series
from apps.api.schemas import (
    ColumnDetectionOut,
    ColumnStatsOut,
    ColumnStatsValues,
    ConsistencyCorrectionResultOut,
    ConsistencyProfileItemOut,
    DatasetConsistencyCorrectionRequest,
    DatasetConsistencyCorrectionResponse,
    DatasetConsistencyProfileResponse,
    DatasetStatsResponse,
    DatasetSummaryOut,
    DatasetFormatCorrectionRequest,
    DatasetFormatCorrectionResponse,
    DatasetFormatProfileResponse,
    DatasetInclusionCorrectionRequest,
    DatasetInclusionCorrectionResponse,
    DatasetInclusionProfileResponse,
    DatasetRangeCorrectionRequest,
    DatasetRangeCorrectionResponse,
    DatasetRangeProfileResponse,
    DatasetTypeConversionRequest,
    DatasetTypeConversionResponse,
    DatasetTypeSchemaRequest,
    DatasetTypeSchemaResponse,
    DatasetUniquenessCorrectionRequest,
    DatasetUniquenessCorrectionResponse,
    DatasetUniquenessProfileResponse,
    DatasetValidationRulesRequest,
    DatasetValidationRulesResponse,
    DatasetValidationCheckModesRequest,
    DatasetValidationCheckModesResponse,
    DatasetValidateResponse,
    DecompositionResponse,
    DecompositionSeriesPoint,
    DecompositionSeriesResponse,
    DetectionCandidateOut,
    DistributionChartResponse,
    HistogramBin,
    KdePoint,
    PanelBalanceResponse,
    ScatterPoint,
    SessionStateResponse,
    StructureDetectionResponse,
    FrequencyDetectionOut,
    FormatCorrectionResultOut,
    FormatProfileItemOut,
    InclusionCorrectionResultOut,
    InclusionProfileItemOut,
    RangeCorrectionResultOut,
    RangeProfileItemOut,
    TargetColumnRequest,
    TargetColumnResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    TypeConversionResultOut,
    UniquenessProfileOut,
    UploadResponse,
    ValidationCheckItem,
    ValidationCheckResult,
    ValidationTypeProfileOut,
)
from app.data.detectors import score_all_columns_as_date, score_all_columns_as_entity_group, detect_column_frequency
from validation.engine import profile_consistency, profile_formats, profile_inclusion, profile_ranges, profile_uniqueness, validate_dataframe
from validation.rule_resolver import CHECK_IDS, resolve_validation_rules
from apps.api.consistency_correction import preview_consistency_corrections
from apps.api.format_correction import preview_format_corrections
from apps.api.inclusion_correction import preview_inclusion_corrections
from apps.api.range_correction import preview_range_corrections
from apps.api.type_conversion import preview_type_conversions
from apps.api.uniqueness_correction import preview_uniqueness_correction
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


def _effective_validation_check_modes(session: AnalysisSession) -> dict[str, str]:
    """Return all check modes; missing persisted values are backward-compatible auto."""
    allowed_modes = {"auto", "enabled", "disabled"}
    return {
        check_id: (
            session.validation_check_modes.get(check_id, "auto")
            if session.validation_check_modes.get(check_id, "auto") in allowed_modes
            else "auto"
        )
        for check_id in CHECK_IDS
    }


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


@router.get("/dataset/structure-detection", response_model=StructureDetectionResponse)
def get_structure_detection(request: Request, response: Response):
    """
    Реальная (контентная) детекция date-колонки и группирующей колонки --
    остановка «Структура» вкладки «Загрузка».

    До этого изменения (найдено пользователем 2026-08-14 на реальном
    FAO-датасете): фронт (buildDetectionFromColumns в TsAnalysisUpload.tsx)
    использовал ПОЗИЦИОННУЮ заглушку -- если ни одна колонка не была
    датой по pandas dtype (что для "голых" числовых лет вроде Year
    никогда не так), кандидатами в дату становились первые 3 колонки
    файла с искусственно убывающим score (0.9/0.7/0.5), независимо от
    содержимого -- отсюда абсурдные кандидаты вроде Country/Price.

    Использует app/data/detectors.py::score_all_columns_as_date /
    score_all_columns_as_entity_group -- уже существовавшую,
    протестированную логику (regex-паттерны дат, ключевые слова
    рус/англ, диапазон годов 1800-2100), которая была подключена к
    legacy Streamlit app.py, но не к этому API (см. комментарий в
    apps/api/upload_common.py, признающий этот пробел явно).
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    date_scores = score_all_columns_as_date(df)
    best_date = date_scores[0] if date_scores and date_scores[0]["score"] > 0 else None

    entity_scores = score_all_columns_as_entity_group(df, date_col=best_date["name"] if best_date else None)
    best_entity = next((c for c in entity_scores if c["score"] > 0), None)

    # Реальная частота (2026-08-14, найден пользователем: заглушка
    # "D — ежедневная" на фронте показывалась для годового FAO-датасета).
    frequency = None
    if best_date is not None:
        freq_result = detect_column_frequency(df[best_date["name"]])
        frequency = FrequencyDetectionOut(**freq_result)

    return StructureDetectionResponse(
        date_col=ColumnDetectionOut(
            selected=best_date["name"] if best_date else "(не использовать)",
            confidence=round((best_date["score"] if best_date else 0) * 100),
            candidates=[DetectionCandidateOut(**c) for c in date_scores],
        ),
        entity_col=ColumnDetectionOut(
            selected=best_entity["name"] if best_entity else "(нет)",
            confidence=round((best_entity["score"] if best_entity else 0) * 100),
            candidates=[DetectionCandidateOut(**c) for c in entity_scores],
        ),
        frequency=frequency,
    )


@router.get("/dataset/timeseries", response_model=TimeSeriesResponse)
def get_dataset_timeseries(column: str, date_column: str, request: Request, response: Response):
    """
    Линейный график исследуемого признака с РЕАЛЬНЫМИ датами на оси X --
    остановка «График» вкладки «Загрузка» (между «Превью датасета» и
    «Распределение», согласовано с тимлидом 2026-08-14).

    date_column -- ОБЯЗАТЕЛЬНЫЙ параметр (в отличие от /dataset/distribution,
    где x=позиция): фронт передаёт detection.dateCol.selected, уже
    вычисленный на остановке «Структура» (та же эвристика переиспользуется,
    не задваивается). Если фронт не уверен в date-колонке -- пусть покажет
    честное состояние "нет обнаруженной даты", не шлёт запрос вслепую.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{column}' отсутствует в датасете")
    if date_column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{date_column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise HTTPException(status_code=422, detail=f"Колонка '{column}' не числовая -- график недоступен")

    result = build_timeseries_points(df[date_column], df[column])
    return TimeSeriesResponse(
        column=column,
        date_column=date_column,
        points=[TimeSeriesPoint(**p) for p in result["points"]],
        sampled=result["sampled"],
        sampling_method=result["sampling_method"],
        original_count=result["original_count"],
        was_resorted=result["was_resorted"],
    )


@router.get("/dataset/decomposition", response_model=DecompositionResponse)
def get_dataset_decomposition(column: str, date_column: str, request: Request, response: Response):
    """
    Бейджи декомпозиции Тренд/Сезонность/Цикличность/Остаток -- "уровень
    шума в данных" на старте анализа, под графиком остановки «График»
    (согласовано с тимлидом 2026-08-14). Считается ПО КНОПКЕ на фронте
    (не авто при заходе на остановку) -- STL не мгновенная на statsmodels.

    Реального ValueError изнутри statsmodels здесь быть не должно --
    apps/api/decomposition_data.py::build_decomposition сам гейтит частоту/
    число точек/панельные дубли ДО вызова STL и возвращает applicable=False
    с honest reason вместо пробрасывания исключения наружу. Если что-то
    всё же случится -- это баг build_decomposition, а не ожидаемый путь.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{column}' отсутствует в датасете")
    if date_column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{date_column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise HTTPException(status_code=422, detail=f"Колонка '{column}' не числовая -- декомпозиция недоступна")

    result = build_decomposition(df[date_column], df[column], column)
    return DecompositionResponse(**result)


@router.get("/dataset/decomposition-series", response_model=DecompositionSeriesResponse)
def get_dataset_decomposition_series(column: str, date_column: str, request: Request, response: Response):
    """
    Реальные ряды компонент декомпозиции (Тренд/Сезонность/Цикличность/
    Остаток) для графика под бейджами -- согласовано с тимлидом
    2026-08-19: "визуализировать данный декомпозированный ряд на
    дополнительном графике... каждый своим цветом, легенда: цвет —
    составляющая". Исходный линейный график (/dataset/timeseries)
    остаётся без изменений, это ДОПОЛНИТЕЛЬНЫЙ график.

    Переиспользует app/preprocessing/decomposition.py::apply_decomposition
    (существующая функция -- ДО этой задачи вызывалась только косвенно
    через compute_decomposition_stats, сами ряды trend/seasonal/resid
    нигде наружу не отдавались). Тот же гейт применимости, что и в
    /dataset/decomposition (общий _prepare_decomposable_series) --
    бейджи и график согласованно говорят "неприменимо" на одних данных.

    Считается ПО ТОЙ ЖЕ КНОПКЕ «Считать декомпозицию» на фронте, что и
    бейджи (один клик -- оба результата), не отдельный запрос по требованию.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{column}' отсутствует в датасете")
    if date_column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{date_column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise HTTPException(status_code=422, detail=f"Колонка '{column}' не числовая -- декомпозиция недоступна")

    result = build_decomposition_series(df[date_column], df[column], column)
    return DecompositionSeriesResponse(**result)


def _session_validation_rules(session: AnalysisSession) -> tuple[dict, dict]:
    """Разрешает session > template > system для всех 10 проверок."""
    return resolve_validation_rules(
        session.dataframe,
        template_id=session.validation_template_id,
        session_overrides=session.validation_rule_overrides,
        type_schema=session.type_schema,
    )


def _validation_type_profile(
    df: pd.DataFrame,
    type_schema: dict[str, str],
    validation_result: dict,
) -> list[ValidationTypeProfileOut]:
    violations_by_column = {
        str(column): int(count)
        for column, count in validation_result.get("schema_errors_by_column", {}).items()
    }

    profile: list[ValidationTypeProfileOut] = []
    for item in _compute_column_info(df):
        expected_type = type_schema.get(item.name)
        violations = violations_by_column.get(item.name, 0) if expected_type is not None else None
        profile.append(ValidationTypeProfileOut(
            **item.model_dump(),
            expected_type=expected_type,
            validation_status=(
                "profile" if expected_type is None
                else "mismatch" if violations else "matched"
            ),
            violations=violations,
        ))
    return profile


@router.get("/dataset/validate", response_model=DatasetValidateResponse)
def get_dataset_validate(request: Request, response: Response, column: str | None = None):
    """
    Реальная валидация активного датасета сессии по 10 проверкам вкладки
    «Валидация» (см. TsAnalysisValidation.tsx::CHECKS) -- ранее ВСЕ 10
    были статическим моком (захардкоженный массив, ни одного fetch).

    Resolver объединяет правила в фиксированном порядке: session overrides
    > выбранный YAML-шаблон > безопасные системные правила. Системная схема
    типов использует dtype, приводимость значений и семантику имени; она
    позволяет первому общему запуску вернуть явный pass/fail без ручной
    настройки. Профиль переиспользует ту же _compute_column_info, что и
    ответ загрузки.

    Если resolver не может воспроизводимо определить правило, режим auto
    возвращает нейтральный ``skipped``. Режим enabled оставляет ``pending``
    и требует настройки, а disabled исключает остановку из оценки.

    column сохранён для обратной совместимости как опциональный per-column
    скоуп выбранного target_column (см. GET/POST /target-column). Общая
    кнопка UI не передаёт column и всегда проверяет весь датасет. Часть
    проверок при прямом вызове API
    учитывают column (ranges/formats/inclusion/referential/text_quality/
    sufficiency), часть принципиально dataset-wide (data_types/
    consistency/uniqueness/regularity) -- см. ValidationCheckResult.scope
    в ответе и докстринг _run_all_checks. Несуществующая колонка -- 404,
    не молчаливый игнор параметра.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    df = session.dataframe
    if column is not None and column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Колонка '{column}' отсутствует в датасете")

    rules, rule_sources = _session_validation_rules(session)
    result = validate_dataframe(df, rules, target_column=column)

    modes = _effective_validation_check_modes(session)
    checks: dict[str, ValidationCheckResult] = {}
    for check_id, raw in result["checks"].items():
        mode = modes[check_id]
        status = raw["status"]
        count = raw["count"]
        items = raw["items"]
        status_reason = None
        error = raw.get("error")

        if mode == "disabled":
            status = "skipped"
            count = None
            items = []
            error = None
            status_reason = "disabled"
        elif status == "pending" and not error:
            if mode == "auto":
                status = "skipped"
                status_reason = "not_required"
            else:
                status_reason = "needs_rule"

        checks[check_id] = ValidationCheckResult(
            status=status,
            count=count,
            items=[ValidationCheckItem(**item) for item in items],
            scope=raw.get("scope", "dataset"),
            error=error,
            rule_source=(
                "not_applicable"
                if status in {"pending", "skipped"} and not error
                else rule_sources.get(check_id, "not_applicable")
            ),
            mode=mode,
            status_reason=status_reason,
        )

    policy_is_valid = all(
        check.status not in {"warning"}
        and check.error is None
        and not (check.status == "pending" and check.status_reason == "needs_rule")
        for check in checks.values()
    )

    return DatasetValidateResponse(
        is_valid=policy_is_valid,
        rules_source=(
            "session" if session.type_schema or session.validation_rule_overrides
            else "template" if session.validation_template_id != "system"
            else "system"
        ),
        validation_template_id=session.validation_template_id,
        column=column,
        total_rows=result["summary"]["total_rows"],
        total_columns=result["summary"]["total_columns"],
        type_validation_mode=(
            "schema" if rules.get("schema", {}).get("columns") else "profile"
        ),
        type_profile=_validation_type_profile(
            df,
            {
                name: spec.get("type")
                for name, spec in rules.get("schema", {}).get("columns", {}).items()
                if isinstance(spec, dict) and spec.get("type")
            },
            result,
        ),
        checks=checks,
    )


@router.get("/dataset/validation-rules", response_model=DatasetValidationRulesResponse)
def get_dataset_validation_rules(request: Request, response: Response):
    """Возвращает выбранный шаблон и локальные overrides сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    return DatasetValidationRulesResponse(
        template_id=session.validation_template_id,
        overrides=session.validation_rule_overrides,
    )


@router.get(
    "/dataset/validation-check-modes",
    response_model=DatasetValidationCheckModesResponse,
)
def get_dataset_validation_check_modes(request: Request, response: Response):
    """Возвращает эффективный режим каждой остановки текущей сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")
    return DatasetValidationCheckModesResponse(
        modes=_effective_validation_check_modes(session)
    )


@router.put(
    "/dataset/validation-check-modes",
    response_model=DatasetValidationCheckModesResponse,
)
def save_dataset_validation_check_modes(
    payload: DatasetValidationCheckModesRequest,
    request: Request,
    response: Response,
):
    """Сохраняет partial-обновление режимов; auto удаляет явный override."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    unknown = sorted(set(payload.modes) - set(CHECK_IDS))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестные проверки: {', '.join(unknown)}",
        )
    next_modes = dict(session.validation_check_modes)
    for check_id, mode in payload.modes.items():
        if mode == "auto":
            next_modes.pop(check_id, None)
        else:
            next_modes[check_id] = mode
    session.validation_check_modes = next_modes
    session.touch()
    store.save(session)
    return DatasetValidationCheckModesResponse(
        modes=_effective_validation_check_modes(session)
    )


@router.get("/dataset/format-profile", response_model=DatasetFormatProfileResponse)
def get_dataset_format_profile(request: Request, response: Response):
    """Профиль regex-проверок из активных правил текущей сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, rule_sources = _session_validation_rules(session)
    try:
        columns = profile_formats(session.dataframe, rules)
    except (ValueError, TypeError, re.error) as ex:
        raise HTTPException(status_code=422, detail=f"Некорректное правило формата: {ex}") from ex
    return DatasetFormatProfileResponse(
        rule_source=rule_sources.get("formats", "not_applicable") if columns else "not_applicable",
        columns=[FormatProfileItemOut(**item) for item in columns],
    )


@router.post("/dataset/format-corrections", response_model=DatasetFormatCorrectionResponse)
def correct_dataset_formats(
    payload: DatasetFormatCorrectionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply четырёх стратегий исправления из Streamlit.

    Preview не мутирует сессию. Apply сохраняет полностью подготовленную
    копию атомарно; regex всегда берётся из resolved rules, а не из клиента.
    """
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, _rule_sources = _session_validation_rules(session)
    try:
        corrected_df, raw_results = preview_format_corrections(
            session.dataframe, rules, payload.columns, payload.strategy
        )
        next_profile = profile_formats(corrected_df, rules)
    except (ValueError, TypeError, re.error) as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    if payload.apply:
        session.dataframe = corrected_df
        if session.dataset is not None:
            session.dataset.rows = len(corrected_df)
            session.dataset.columns = len(corrected_df.columns)
        session.touch()
        store.save(session)

    return DatasetFormatCorrectionResponse(
        applied=payload.apply,
        strategy=payload.strategy,
        total_violations=sum(item["invalid_count"] for item in raw_results),
        total_changed=sum(item["changed_count"] for item in raw_results),
        total_still_invalid=sum(item["still_invalid"] for item in raw_results),
        added_columns=[item["flag_column"] for item in raw_results if item["flag_column"]],
        columns=[FormatCorrectionResultOut(**item) for item in raw_results],
        profile=[FormatProfileItemOut(**item) for item in next_profile],
    )


@router.get("/dataset/range-profile", response_model=DatasetRangeProfileResponse)
def get_dataset_range_profile(request: Request, response: Response):
    """Полный профиль применимых min/max-правил активной сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, rule_sources = _session_validation_rules(session)
    try:
        columns = profile_ranges(session.dataframe, rules)
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=f"Некорректное правило диапазона: {ex}") from ex
    return DatasetRangeProfileResponse(
        rule_source=rule_sources.get("ranges", "not_applicable") if columns else "not_applicable",
        columns=[RangeProfileItemOut(**item) for item in columns],
    )


@router.post("/dataset/range-corrections", response_model=DatasetRangeCorrectionResponse)
def correct_dataset_ranges(
    payload: DatasetRangeCorrectionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply безопасных стратегий исправления диапазонов."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, _rule_sources = _session_validation_rules(session)
    try:
        corrected_df, raw_results, rows_removed = preview_range_corrections(
            session.dataframe, rules, payload.columns, payload.strategy
        )
        next_profile = profile_ranges(corrected_df, rules)
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    if payload.apply:
        session.dataframe = corrected_df
        if session.dataset is not None:
            session.dataset.rows = len(corrected_df)
            session.dataset.columns = len(corrected_df.columns)
        session.touch()
        store.save(session)

    return DatasetRangeCorrectionResponse(
        applied=payload.apply,
        strategy=payload.strategy,
        total_violations=sum(item["invalid_count"] for item in raw_results),
        total_changed=sum(item["changed_count"] for item in raw_results),
        total_still_invalid=sum(item["still_invalid"] for item in raw_results),
        rows_removed=rows_removed,
        added_columns=[item["flag_column"] for item in raw_results if item["flag_column"]],
        columns=[RangeCorrectionResultOut(**item) for item in raw_results],
        profile=[RangeProfileItemOut(**item) for item in next_profile],
    )


@router.get("/dataset/inclusion-profile", response_model=DatasetInclusionProfileResponse)
def get_dataset_inclusion_profile(request: Request, response: Response):
    """Профиль явных допустимых наборов активной сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, rule_sources = _session_validation_rules(session)
    columns = profile_inclusion(session.dataframe, rules)
    return DatasetInclusionProfileResponse(
        rule_source=rule_sources.get("inclusion", "not_applicable") if columns else "not_applicable",
        columns=[InclusionProfileItemOut(**item) for item in columns],
    )


@router.post(
    "/dataset/inclusion-corrections",
    response_model=DatasetInclusionCorrectionResponse,
)
def correct_dataset_inclusion(
    payload: DatasetInclusionCorrectionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply стратегий исправления значений вне допустимого набора."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, _rule_sources = _session_validation_rules(session)
    try:
        corrected_df, raw_results, rows_removed = preview_inclusion_corrections(
            session.dataframe, rules, payload.columns, payload.strategy
        )
        next_profile = profile_inclusion(corrected_df, rules)
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    if payload.apply:
        session.dataframe = corrected_df
        if session.dataset is not None:
            session.dataset.rows = len(corrected_df)
            session.dataset.columns = len(corrected_df.columns)
        session.touch()
        store.save(session)

    return DatasetInclusionCorrectionResponse(
        applied=payload.apply,
        strategy=payload.strategy,
        total_violations=sum(item["invalid_count"] for item in raw_results),
        total_changed=sum(item["changed_count"] for item in raw_results),
        total_still_invalid=sum(item["still_invalid"] for item in raw_results),
        rows_removed=rows_removed,
        added_columns=[item["flag_column"] for item in raw_results if item["flag_column"]],
        columns=[InclusionCorrectionResultOut(**item) for item in raw_results],
        profile=[InclusionProfileItemOut(**item) for item in next_profile],
    )


@router.get("/dataset/consistency-profile", response_model=DatasetConsistencyProfileResponse)
def get_dataset_consistency_profile(request: Request, response: Response):
    """Профиль хронологических и предметных правил активной сессии."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, rule_sources = _session_validation_rules(session)
    profile = profile_consistency(session.dataframe, rules)
    applicable = [item for item in profile if item["applicable"]]
    return DatasetConsistencyProfileResponse(
        rule_source=(
            rule_sources.get("consistency", "not_applicable")
            if applicable else "not_applicable"
        ),
        rules=[ConsistencyProfileItemOut(**item) for item in profile],
    )


@router.post(
    "/dataset/consistency-corrections",
    response_model=DatasetConsistencyCorrectionResponse,
)
def correct_dataset_consistency(
    payload: DatasetConsistencyCorrectionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply безопасных стратегий логики и хронологии."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, _rule_sources = _session_validation_rules(session)
    try:
        corrected_df, raw_results, rows_removed = preview_consistency_corrections(
            session.dataframe, rules, payload.rule_indices, payload.strategy
        )
        next_profile = profile_consistency(corrected_df, rules)
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    if payload.apply:
        session.dataframe = corrected_df
        if session.dataset is not None:
            session.dataset.rows = len(corrected_df)
            session.dataset.columns = len(corrected_df.columns)
        session.touch()
        store.save(session)

    return DatasetConsistencyCorrectionResponse(
        applied=payload.apply,
        strategy=payload.strategy,
        total_violations=sum(item["invalid_count"] for item in raw_results),
        total_changed=sum(item["changed_count"] for item in raw_results),
        total_still_invalid=sum(item["still_invalid"] for item in raw_results),
        rows_removed=rows_removed,
        added_columns=[item["flag_column"] for item in raw_results if item["flag_column"]],
        rules=[ConsistencyCorrectionResultOut(**item) for item in raw_results],
        profile=[ConsistencyProfileItemOut(**item) for item in next_profile],
    )


@router.get("/dataset/uniqueness-profile", response_model=DatasetUniquenessProfileResponse)
def get_dataset_uniqueness_profile(request: Request, response: Response):
    """Ключ, метрики и группы дубликатов активного датасета."""
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, rule_sources = _session_validation_rules(session)
    profile = profile_uniqueness(session.dataframe, rules)
    return DatasetUniquenessProfileResponse(
        rule_source=(
            rule_sources.get("uniqueness", "not_applicable")
            if profile["applicable"] else "not_applicable"
        ),
        profile=UniquenessProfileOut(**profile),
    )


@router.post(
    "/dataset/uniqueness-corrections",
    response_model=DatasetUniquenessCorrectionResponse,
)
def correct_dataset_uniqueness(
    payload: DatasetUniquenessCorrectionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply стратегий устранения дубликатов из Streamlit."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    rules, _rule_sources = _session_validation_rules(session)
    try:
        corrected_df, summary = preview_uniqueness_correction(
            session.dataframe, rules, payload.strategy
        )
        next_profile = profile_uniqueness(corrected_df, rules)
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    if payload.apply:
        session.dataframe = corrected_df
        if session.dataset is not None:
            session.dataset.rows = len(corrected_df)
            session.dataset.columns = len(corrected_df.columns)
        session.touch()
        store.save(session)

    return DatasetUniquenessCorrectionResponse(
        applied=payload.apply,
        strategy=payload.strategy,
        profile=UniquenessProfileOut(**next_profile),
        **summary,
    )


@router.put("/dataset/validation-rules", response_model=DatasetValidationRulesResponse)
def save_dataset_validation_rules(
    payload: DatasetValidationRulesRequest,
    request: Request,
    response: Response,
):
    """Сохраняет выбор правил только в текущей AnalysisSession."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    allowed_sections = {
        "schema", "formats", "ranges", "consistency", "uniqueness",
        "inclusion", "referential", "text_quality", "regularity", "sufficiency",
    }
    unknown = sorted(set(payload.overrides) - allowed_sections)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Неизвестные разделы правил: {', '.join(unknown)}")

    list_sections = {"ranges", "consistency", "referential"}
    dict_sections = allowed_sections - list_sections
    malformed = [
        section for section, value in payload.overrides.items()
        if (section in list_sections and not isinstance(value, list))
        or (section in dict_sections and not isinstance(value, dict))
        or (section in list_sections and any(not isinstance(item, dict) for item in value))
    ]
    if malformed:
        raise HTTPException(
            status_code=422,
            detail=f"Некорректная структура разделов правил: {', '.join(sorted(malformed))}",
        )

    # Пустой раздел не считается переопределением: иначе, например,
    # ranges=[] маскировал бы шаблон и одновременно ошибочно помечал
    # сводный источник как session.
    normalized_overrides = {
        section: value for section, value in payload.overrides.items() if value
    }

    for index, rule in enumerate(normalized_overrides.get("ranges", []), start=1):
        keywords = rule.get("keywords")
        min_value = rule.get("min")
        max_value = rule.get("max")
        if not isinstance(keywords, list) or not keywords or any(
            not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Для правила диапазона {index} задайте хотя бы одно ключевое слово",
            )
        for label, value in (("минимум", min_value), ("максимум", max_value)):
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"{label.capitalize()} правила диапазона {index} должен быть числом",
                )
        if min_value is None and max_value is None:
            raise HTTPException(
                status_code=422,
                detail=f"Для правила диапазона {index} задайте минимум или максимум",
            )
        if min_value is not None and max_value is not None and min_value > max_value:
            raise HTTPException(
                status_code=422,
                detail=f"В правиле диапазона {index} минимум не может превышать максимум",
            )

    allowed_consistency_types = {"chronology", "comparison"}
    allowed_comparison_operators = {"<", "<=", ">", ">=", "==", "!="}
    for index, rule in enumerate(normalized_overrides.get("consistency", []), start=1):
        name = rule.get("name")
        rule_type = rule.get("type")
        columns = rule.get("columns")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(
                status_code=422,
                detail=f"Для правила логики {index} задайте название",
            )
        if rule_type not in allowed_consistency_types:
            raise HTTPException(
                status_code=422,
                detail=f"Тип правила логики {index} не поддерживается",
            )
        expected_columns = 1 if rule_type == "chronology" else 2
        if not isinstance(columns, list) or len(columns) != expected_columns or any(
            not isinstance(column, str) or not column.strip() for column in columns
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Для правила логики {index} задайте "
                    f"{expected_columns} {'колонку' if expected_columns == 1 else 'колонки'}"
                ),
            )
        missing_columns = [column for column in columns if column not in session.dataframe.columns]
        group_column = rule.get("group_column")
        if group_column is not None:
            if rule_type != "chronology" or not isinstance(group_column, str) or not group_column.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"Некорректная группирующая колонка правила логики {index}",
                )
            if group_column not in session.dataframe.columns:
                missing_columns.append(group_column)
        if missing_columns:
            raise HTTPException(
                status_code=422,
                detail=f"Колонка '{missing_columns[0]}' отсутствует в датасете",
            )
        if rule_type == "comparison" and rule.get("operator") not in allowed_comparison_operators:
            raise HTTPException(
                status_code=422,
                detail=f"Задайте допустимый оператор правила логики {index}",
            )

    uniqueness = normalized_overrides.get("uniqueness")
    if uniqueness is not None:
        key_columns = uniqueness.get("composite_key")
        if not isinstance(key_columns, list) or any(
            not isinstance(column, str) or not column.strip() for column in key_columns
        ):
            raise HTTPException(
                status_code=422,
                detail="Колонки составного ключа должны быть непустыми строками",
            )
        if len(key_columns) != len(set(key_columns)):
            raise HTTPException(
                status_code=422,
                detail="Колонки составного ключа не могут повторяться",
            )
        missing_columns = [column for column in key_columns if column not in session.dataframe.columns]
        if missing_columns:
            raise HTTPException(
                status_code=422,
                detail=f"Колонка '{missing_columns[0]}' отсутствует в датасете",
            )

    for column, config in normalized_overrides.get("inclusion", {}).items():
        if column not in session.dataframe.columns:
            raise HTTPException(
                status_code=422,
                detail=f"Колонка '{column}' отсутствует в датасете",
            )
        allowed_values = config.get("allowed_values") if isinstance(config, dict) else config
        if not isinstance(allowed_values, list) or not allowed_values:
            raise HTTPException(
                status_code=422,
                detail=f"Для колонки '{column}' задайте непустой список допустимых значений",
            )
        if any(value is None or type(value) not in {str, int, float, bool} for value in allowed_values):
            raise HTTPException(
                status_code=422,
                detail=f"Допустимый набор колонки '{column}' содержит неподдерживаемое значение",
            )
        if len({(type(value).__name__, str(value)) for value in allowed_values}) != len(allowed_values):
            raise HTTPException(
                status_code=422,
                detail=f"Допустимый набор колонки '{column}' содержит повторы",
            )
        if isinstance(config, dict) and "default_value" in config and config["default_value"] is not None:
            default_value = config["default_value"]
            if not any(type(default_value) is type(value) and default_value == value for value in allowed_values):
                raise HTTPException(
                    status_code=422,
                    detail=f"Значение по умолчанию колонки '{column}' должно входить в допустимый набор",
                )

    # Regex из редактора правил валидируется до изменения сессии. Клиент
    # может выбирать только реальные колонки активного DataFrame.
    for column, config in normalized_overrides.get("formats", {}).items():
        if column not in session.dataframe.columns:
            raise HTTPException(
                status_code=422,
                detail=f"Колонка '{column}' отсутствует в датасете",
            )
        pattern = config.get("pattern") if isinstance(config, dict) else config
        threshold = config.get("threshold", 95) if isinstance(config, dict) else 95
        if not isinstance(pattern, str) or not pattern.strip():
            raise HTTPException(status_code=422, detail=f"Для колонки '{column}' не задан regex")
        try:
            re.compile(pattern)
        except re.error as ex:
            raise HTTPException(
                status_code=422,
                detail=f"Некорректный regex для колонки '{column}': {ex}",
            ) from ex
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 100:
            raise HTTPException(
                status_code=422,
                detail=f"Порог для колонки '{column}' должен быть от 0 до 100",
            )

    # Вызов resolver одновременно валидирует template_id и структуру,
    # прежде чем состояние сессии будет изменено.
    resolve_validation_rules(
        session.dataframe,
        template_id=payload.template_id,
        session_overrides=normalized_overrides,
        type_schema=session.type_schema,
    )
    session.validation_template_id = payload.template_id
    session.validation_rule_overrides = normalized_overrides
    session.touch()
    store.save(session)
    return DatasetValidationRulesResponse(
        template_id=session.validation_template_id,
        overrides=session.validation_rule_overrides,
    )


@router.put("/dataset/type-schema", response_model=DatasetTypeSchemaResponse)
def save_dataset_type_schema(
    payload: DatasetTypeSchemaRequest,
    request: Request,
    response: Response,
):
    """Сохраняет явно выбранные ожидаемые типы в текущей сессии."""
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    columns = [item.column for item in payload.columns]
    if len(columns) != len(set(columns)):
        raise HTTPException(status_code=422, detail="Одна колонка не может повторяться в схеме")
    missing = [column for column in columns if column not in session.dataframe.columns]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Колонки отсутствуют в датасете: {', '.join(missing)}",
        )

    session.type_schema = {item.column: item.target_type for item in payload.columns}
    session.touch()
    store.save(session)
    return DatasetTypeSchemaResponse(columns=payload.columns)


@router.post("/dataset/convert-types", response_model=DatasetTypeConversionResponse)
def convert_dataset_types(
    payload: DatasetTypeConversionRequest,
    request: Request,
    response: Response,
):
    """Preview/apply преобразований dtype для активного датасета.

    Preview (apply=False) всегда работает на глубокой копии и не сохраняет
    сессию. Apply транзакционен: при invalid_policy="reject" хотя бы одно
    неприводимое значение отменяет ВСЕ операции; coerce заменяет только
    такие значения на NA/NaT. datetime использует smart_to_datetime из
    app.data.detectors, поэтому числовые годы не превращаются в 1970 год.
    """
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataframe is None:
        raise HTTPException(status_code=404, detail="В сессии нет активного датасета")

    try:
        converted_df, raw_results = preview_type_conversions(
            session.dataframe,
            [item.model_dump() for item in payload.conversions],
        )
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    total_invalid = sum(item["invalid_count"] for item in raw_results)
    if payload.apply and payload.invalid_policy == "reject" and total_invalid > 0:
        failed = [item for item in raw_results if item["invalid_count"] > 0]
        summary = "; ".join(
            f"Колонка '{item['column']}': {item['invalid_count']} значений не удалось преобразовать"
            for item in failed
        )
        raise HTTPException(status_code=422, detail=summary)

    target_column_reset = False
    if payload.apply:
        session.dataframe = converted_df
        session.type_schema.update({
            item.column: item.target_type for item in payload.conversions
        })
        if session.target_column is not None and not pd.api.types.is_numeric_dtype(
            converted_df[session.target_column]
        ):
            session.target_column = None
            target_column_reset = True
        session.touch()
        store.save(session)

    return DatasetTypeConversionResponse(
        applied=payload.apply,
        invalid_policy=payload.invalid_policy,
        total_invalid=total_invalid,
        target_column_reset=target_column_reset,
        columns=[TypeConversionResultOut(**item) for item in raw_results],
        type_profile=[
            ValidationTypeProfileOut(**item.model_dump())
            for item in _compute_column_info(converted_df)
        ],
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


_DATE_LIKE_KEYWORDS = ("date", "дата", "year", "год", "period", "период")


def _suggest_target_column(numeric_columns: list[str]) -> str | None:
    """Эвристический дефолт для target_column: первая числовая колонка,
    ИСКЛЮЧАЯ похожие на дату/год по имени -- те же ключевые слова, что
    уже используются для автодетекта date_col в validation/engine.py
    (_run_all_checks::_uniqueness, validate_sufficiency) -- единая
    эвристика, не две разные копипасты.

    Год/дата технически числовые (int64), но семантически это ИНДЕКС
    временной оси, а не аналитическая величина -- плохой дефолт для
    target_column (см. пример: FAO price dataset, колонки Country/Year/
    Price -- наивная 'первая числовая' выбрала бы Year, а не Price).

    Если ВСЕ числовые колонки похожи на дату (редкий случай) -- честно
    возвращаем первую как есть, лучше чем None.
    """
    if not numeric_columns:
        return None
    non_date_like = [
        c for c in numeric_columns
        if not any(kw in c.lower() for kw in _DATE_LIKE_KEYWORDS)
    ]
    return non_date_like[0] if non_date_like else numeric_columns[0]


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
            suggested_column=None,
            available_columns=[],
            has_dataset=False,
        )

    numeric_columns = _get_numeric_columns(session.dataframe)
    return TargetColumnResponse(
        target_column=session.target_column,
        suggested_column=_suggest_target_column(numeric_columns),
        available_columns=numeric_columns,
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

    numeric_columns = _get_numeric_columns(df)
    return TargetColumnResponse(
        target_column=session.target_column,
        suggested_column=_suggest_target_column(numeric_columns),
        available_columns=numeric_columns,
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
