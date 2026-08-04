# apps/api/routers/internal.py
"""
Внутренние эндпоинты -- для embedded-режима (TS Analysis внутри портала).

ЗАГЛУШКА по авторизации: сейчас БЕЗ проверки API-ключа, в предположении,
что доступ ограничен на уровне сети/шлюза (внутренний сервис, доступный
только из embedded-фронтенда). Если появится общая авторизация с
порталом (например, JWT из сессии портала) -- добавить Depends() с
проверкой этого токена, аналогично require_api_key в auth.py.

Логика идентична public.py -- сознательно не дублируем формулы, только
роутинг разный (без require_api_key, другой префикс).
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
import pandas as pd
import uuid

from apps.api.schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
    UploadResponse,
)
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from apps.api.routers.public import _series_from_points
from app.data.file_loader import read_uploaded_file

router = APIRouter()


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
    return {
        "gaps_count": result["gaps_count"],
        "freq_info": result["freq_info"],
        "error": result.get("error"),
    }

# Добавить в конец файла apps/api/routers/internal.py
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