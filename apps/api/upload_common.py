# apps/api/upload_common.py
"""
Общая логика обработки загрузки файла -- используется И public.py,
И internal.py. Раньше (до этого изменения) обработчик /upload был
буквально продублирован в обоих роутерах -- ровно та же ошибка, о
которой предупреждает docs/MIGRATION_ARCHITECTURE.md §7.2 ("4 копии
calculate_ts_passport" в старом Streamlit-коде). Вынесено сюда, чтобы
не завести пятую.

Дополнительно к предпросмотру (как было раньше) обработчик теперь:
  1. Реально считает columns_info и quality-teaser из загруженного
     DataFrame (не моки) -- закрывает соответствующие пункты контракта
     вкладки «Загрузка» из TsAnalysisUpload.tsx.
  2. Сохраняет DataFrame и метаданные в AnalysisSession (session_store.py),
     чтобы Home page знала об активном датасете после F5, а будущие
     эндпоинты (детекция структуры, column-mapping) могли переиспользовать
     тот же DataFrame.

НЕ реализовано здесь (сознательно, вне охвата этой задачи): подтверждение
автоопределения (дата/группировка/частота) с confidence и кандидатами --
на фронтенде это пока моковые данные (см. комментарий в
TsAnalysisUpload.tsx). В app/data/detectors.py уже есть протестированная
`detect_and_convert_datetime`, но она не возвращает форму {selected,
confidence, candidates: [{name, score}]}, которую ожидает фронтенд --
это отдельная по объёму задача (адаптер/скоринг), не подмешивать сюда.
"""
from io import BytesIO
import uuid

import pandas as pd
from fastapi import HTTPException, Request, Response, UploadFile

from apps.api.schemas import ColumnInfoOut, QualityTeaserOut, UploadResponse
from apps.api.session_store import DatasetInfo, format_size_label, get_or_create_session_id, get_session_store
from app.data.file_loader import read_uploaded_file


def _compute_column_info(df: pd.DataFrame) -> list[ColumnInfoOut]:
    columns_info: list[ColumnInfoOut] = []
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            type_icon = "datetime"
        elif pd.api.types.is_numeric_dtype(series):
            type_icon = "numeric"
        elif series.nunique(dropna=True) <= 50:
            type_icon = "categorical"
        else:
            type_icon = "text"
        columns_info.append(
            ColumnInfoOut(
                name=str(col),
                dtype=str(series.dtype),
                type_icon=type_icon,
                non_null=int(series.notna().sum()),
                nulls=int(series.isna().sum()),
                unique=int(series.nunique(dropna=True)),
            )
        )
    return columns_info


def _compute_quality_teaser(df: pd.DataFrame) -> QualityTeaserOut:
    """Только счётчики -- см. docstring модуля / контракт вкладки «Загрузка»."""
    missing_cols = [str(c) for c in df.columns if df[c].isna().any()]

    outlier_cols: list[str] = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        if ((series < lower) | (series > upper)).any():
            outlier_cols.append(str(col))

    return QualityTeaserOut(
        cols_with_missing=len(missing_cols),
        cols_with_outliers=len(outlier_cols),
        rows_total=len(df),
        duplicates=int(df.duplicated().sum()),
        missing_cols=missing_cols,
        outlier_cols=outlier_cols,
    )


async def handle_upload(file: UploadFile, request: Request, response: Response) -> UploadResponse:
    try:
        contents = await file.read()
        file.file.seek(0)  # на случай, если вызывающий код тоже читает file

        file_like = BytesIO(contents)
        file_like.name = file.filename

        df, _ext = read_uploaded_file(file_like)

        head_rows = df.head(5).values.tolist()
        tail_rows = df.tail(5).values.tolist()
        head = [[str(cell) for cell in row] for row in head_rows]
        tail = [[str(cell) for cell in row] for row in tail_rows]
        head = [[str(col) for col in df.columns.tolist()]] + head

        size_label = format_size_label(len(contents))
        dataset_id = str(uuid.uuid4())

        session_id = get_or_create_session_id(request, response)
        session = get_session_store().get_or_create(session_id)
        session.set_dataset(
            DatasetInfo(
                dataset_id=dataset_id,
                name=file.filename,
                rows=len(df),
                columns=len(df.columns),
                size_label=size_label,
            ),
            df,
        )

        return UploadResponse(
            dataset_id=dataset_id,
            name=file.filename,
            rows=len(df),
            columns=len(df.columns),
            preview={"head": head, "tail": tail},
            columns_info=_compute_column_info(df),
            quality=_compute_quality_teaser(df),
            size_label=size_label,
            error=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
