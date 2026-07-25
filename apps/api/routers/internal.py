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
from fastapi import APIRouter, HTTPException
import pandas as pd

from schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
)
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from routers.public import _series_from_points

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
