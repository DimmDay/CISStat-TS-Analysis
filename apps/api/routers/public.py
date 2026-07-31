# apps/api/routers/public.py
"""
Публичные эндпоинты -- для внешних покупателей (веб-клиент standalone
и прямая интеграция в сторонние ИТ-системы). Авторизация по API-ключу.
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import pandas as pd
import uuid

from apps.api.auth import require_api_key
from apps.api.schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
    UploadResponse,
)
from apps.api.auth import require_api_key

# ЗАМЕНИТЬ путь импорта на реальный, в зависимости от того, куда положите
# этот сервис относительно репозитория CISStat-TS-Analysis:
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from app.data.file_loader import read_uploaded_file

router = APIRouter(dependencies=[Depends(require_api_key)])


def _series_from_points(points) -> pd.Series:
    idx = pd.to_datetime([p.date for p in points])
    values = [p.value for p in points]
    return pd.Series(values, index=idx, name="value").sort_index()


@router.post("/passport", response_model=PassportResponse)
def get_passport(payload: PassportRequest):
    series = _series_from_points(payload.series)
    error_log: list = []
    result = calculate_ts_passport(series, error_log=error_log)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/regularity", response_model=RegularityResponse)
def get_regularity(payload: RegularityRequest):
    df = pd.DataFrame({
        "date": [p.date for p in payload.series],
        "value": [p.value for p in payload.series],
    })
    result = compute_regularity_violations(
        df, date_col="date", entity_col=payload.entity_col,
        gap_threshold_multiplier=payload.gap_threshold_multiplier,
    )
    # mask -- это pd.Series, не сериализуется напрямую в JSON-схему ответа;
    # в публичном API отдаём только агрегаты (gaps_count, freq_info).
    return {
        "gaps_count": result["gaps_count"],
        "freq_info": result["freq_info"],
        "error": result.get("error"),
    }

# Добавить в конец файла apps/api/routers/public.py
@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Загрузка файла для анализа (публичный режим).
    Требует API-ключ (проверяется через require_api_key).
    """
    try:
        # Читаем файл в память
        df, ext = read_uploaded_file(file.file)

        # Генерируем preview
        head = df.head(5).values.tolist()
        tail = df.tail(5).values.tolist()
        # Добавляем заголовки к head
        head = [df.columns.tolist()] + head

        return UploadResponse(
            dataset_id=str(uuid.uuid4()),
            name=file.filename,
            rows=len(df),
            columns=len(df.columns),
            preview={"head": head, "tail": tail},
            error=None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

# Временная отладка
@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    try:
        # Читаем содержимое файла
        contents = await file.read()
        file.file.seek(0)  # Сбрасываем указатель

        # Создаём BytesIO для передачи в file_loader
        from io import BytesIO
        file_like = BytesIO(contents)
        file_like.name = file.filename

        df, ext = read_uploaded_file(file_like)

        # Генерируем preview (все значения конвертируем в строки)
        head_rows = df.head(5).values.tolist()
        tail_rows = df.tail(5).values.tolist()
        # Конвертируем все значения в строки
        head = [[str(cell) for cell in row] for row in head_rows]
        tail = [[str(cell) for cell in row] for row in tail_rows]
        # Добавляем заголовки
        head = [[str(col) for col in df.columns.tolist()]] + head

        return UploadResponse(
            dataset_id=str(uuid.uuid4()),
            name=file.filename,
            rows=len(df),
            columns=len(df.columns),
            preview={"head": head, "tail": tail},
            error=None
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))