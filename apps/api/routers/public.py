# apps/api/routers/public.py
"""
Публичные эндпоинты -- для внешних покупателей (веб-клиент standalone
и прямая интеграция в сторонние ИТ-системы). Авторизация по API-ключу.
"""
from fastapi import APIRouter, Depends, HTTPException
import pandas as pd

from auth import require_api_key
from schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
)

# ЗАМЕНИТЬ путь импорта на реальный, в зависимости от того, куда положите
# этот сервис относительно репозитория CISStat-TS-Analysis:
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations

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
