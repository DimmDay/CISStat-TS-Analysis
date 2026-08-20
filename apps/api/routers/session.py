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

from apps.api.chart_data import MAX_ZOOM_POINTS, build_histogram, build_kde, build_scatter_series, build_timeseries_points
from apps.api.decomposition_data import build_decomposition
from apps.api.schemas import (
    ColumnDetectionOut,
    ColumnStatsOut,
    ColumnStatsValues,
    DatasetStatsResponse,
    DatasetSummaryOut,
    DatasetValidateResponse,
    DecompositionResponse,
    DetectionCandidateOut,
    DistributionChartResponse,
    HistogramBin,
    KdePoint,
    PanelBalanceResponse,
    ScatterPoint,
    SessionStateResponse,
    StructureDetectionResponse,
    FrequencyDetectionOut,
    TargetColumnRequest,
    TargetColumnResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    UploadResponse,
    ValidationCheckItem,
    ValidationCheckResult,
)
from app.data.detectors import score_all_columns_as_date, score_all_columns_as_entity_group, detect_column_frequency
from validation.engine import auto_generate_rules, validate_dataframe
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


@router.get("/dataset/validate", response_model=DatasetValidateResponse)
def get_dataset_validate(request: Request, response: Response, column: str | None = None):
    """
    Реальная валидация активного датасета сессии по 10 проверкам вкладки
    «Валидация» (см. TsAnalysisValidation.tsx::CHECKS) -- ранее ВСЕ 10
    были статическим моком (захардкоженный массив, ни одного fetch).

    Правила -- auto_generate_rules(df) (validation/engine.py): диапазоны/
    inclusion/consistency/formats выводятся из имён и значений колонок
    без явного шаблона -- тот же принцип "без конфига", что и в Upload.
    Явный выбор шаблона (RulesManagementPanel) -- отдельная задача,
    пока панель не подключена к сессии (rules_source в ответе всегда
    "auto" на этом этапе, чтобы фронт мог честно это показать).

    referential ВСЕГДА "pending" при auto-правилах: auto_generate_rules
    не умеет придумать справочник для сверки -- это не 0 нарушений,
    а "нечего проверять" (см. validation/engine.py::_run_all_checks).

    column (2026-08-14) -- опциональный per-column скоуп, тот же
    target_column, что и в Моделировании (см. GET/POST /target-column) --
    единый "исследуемый признак" для всей платформы. Часть проверок
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

    rules = auto_generate_rules(df)
    result = validate_dataframe(df, rules, target_column=column)

    checks = {
        check_id: ValidationCheckResult(
            status=raw["status"],
            count=raw["count"],
            items=[ValidationCheckItem(**item) for item in raw["items"]],
            scope=raw.get("scope", "dataset"),
            error=raw.get("error"),
        )
        for check_id, raw in result["checks"].items()
    }

    return DatasetValidateResponse(
        is_valid=result["is_valid"],
        rules_source="auto",
        column=column,
        total_rows=result["summary"]["total_rows"],
        total_columns=result["summary"]["total_columns"],
        checks=checks,
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
    