# apps/api/schemas.py
"""
Pydantic-схемы запросов/ответов. Форма ответов передаёт структуру,
которую реально возвращают app/core/passport.py и app/validation/regularity.py
(мы её проверяли построчно за этот разговор) -- не выдумана заново.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SeriesPoint(BaseModel):
    date: str
    value: Optional[float] = None


class PassportRequest(BaseModel):
    series: List[SeriesPoint] = Field(..., min_length=1)
    target_col: Optional[str] = None


class PassportResponse(BaseModel):
    # Соответствует ключам, которые реально возвращает calculate_ts_passport:
    # freq, stationarity, determinism, autocorrelation, normality, trend,
    # correlations, seasonality, seasonal_periods, hurst, fft, periodogram,
    # wavelet, basic_stats, timestamp (+ error_log при передаче).
    freq: Optional[Dict[str, Any]] = None
    stationarity: Optional[Dict[str, Any]] = None
    determinism: Optional[Dict[str, Any]] = None
    autocorrelation: Optional[Dict[str, Any]] = None
    normality: Optional[Dict[str, Any]] = None
    trend: Optional[Dict[str, Any]] = None
    seasonality: Optional[Dict[str, Any]] = None
    hurst: Optional[Dict[str, Any]] = None
    basic_stats: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


class RegularityRequest(BaseModel):
    series: List[SeriesPoint] = Field(..., min_length=1)
    entity_col: Optional[str] = None
    gap_threshold_multiplier: float = 1.5


class RegularityResponse(BaseModel):
    gaps_count: int
    freq_info: Dict[str, Any]
    error: Optional[str] = None
