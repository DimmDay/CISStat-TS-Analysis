"""Этап 3 (Task 97.3) — detail_level=expanded для профилей-пилотов.

Спецификация: spec_max_graf_fix.md §6.2 (модель двух уровней), §7.4
(backend-тесты, правка J), §8 п.4 (роллаут Этапа 3).

Контракт:
- detail_level — Optional query-параметр со значениями compact|expanded,
  default compact = текущее поведение без изменений (обратная
  совместимость, правка J: guard структуры/объёма, не побайтовый).
- expanded — та же методология расчёта, только выше вторичный потолок
  точек/бинов сэмплинга отображения. Потолок — явная константа модуля,
  как бюджет PELT-сетки Task 76 (MAX_PELT_GRID_POINTS).
- Пилотные профили (Этап 2): спектральный (CWT-скалограмма), структурные
  сдвиги (series/cusum_path), декомпозиция (STL points). Матрица моделей
  dense-рядов не содержит и detail-режим не получает (§6.3.6: раскрытие
  остаётся чисто визуальным).
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

# Вторичные потолки expanded — импортируются как константы, чтобы тест
# падал при любом их изменении (тестируемая константа, §9 таблица рисков).
from apps.api.chart_data import (
    EXPANDED_FULL_POINTS_THRESHOLD,
    EXPANDED_TARGET_SAMPLED_POINTS,
    TARGET_SAMPLED_POINTS,
)
from app.preprocessing.spectral import (
    MAX_WAVELET_TIME_POINTS,
    MAX_WAVELET_TIME_POINTS_EXPANDED,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    client.cookies.clear()
    yield
    reset_session_store_for_testing()
    client.cookies.clear()
    reset_session_store_for_testing()


def _upload(frame: pd.DataFrame, name: str = "series.csv") -> None:
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post("/v1/internal/upload", files={"file": (name, buffer, "text/csv")})
    assert response.status_code == 200, response.text


def _signature(value: Any) -> Any:
    """Структурная подпись (правка J): набор ключей, типов и объём списков.

    Сравнивает структуру и количество, а не значения/байты: guard от
    случайного изменения дефолтного поведения compact-ответа.
    """
    if isinstance(value, dict):
        return {key: _signature(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return {
            "__list__": {
                "len": len(value),
                "item": _signature(value[0]) if value else None,
            },
        }
    return type(value).__name__


# ── Структурные сдвиги (series/cusum_path: LTTB) ────────────────────────────


def _breaks_frame(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    values = np.r_[rng.normal(0, 0.3, n // 2), rng.normal(3, 0.3, n - n // 2)]
    return pd.DataFrame({
        "Date": pd.date_range("2015-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Price": values,
    })


def test_structural_breaks_compact_default_matches_current_contract():
    """detail_level=compact и отсутствие параметра — идентичная структура/объём."""
    _upload(_breaks_frame(3500))

    default = client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "alpha": 0.05, "min_segment": 20, "penalty_multiplier": 2.0},
    ).json()
    compact = client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={
            "column": "Price", "alpha": 0.05, "min_segment": 20,
            "penalty_multiplier": 2.0, "detail_level": "compact",
        },
    ).json()

    assert _signature(default) == _signature(compact)
    # компактное поведение не изменилось: LTTB до TARGET_SAMPLED_POINTS
    assert len(compact["series"]) == TARGET_SAMPLED_POINTS
    assert len(compact["cusum_path"]) == TARGET_SAMPLED_POINTS
    assert compact["series_sampled"] is True


def test_structural_breaks_expanded_raises_density_within_ceiling():
    """expanded: больше точек ряда/CUSUM, но не выше вторичного потолка."""
    _upload(_breaks_frame(3500))
    params = {"column": "Price", "alpha": 0.05, "min_segment": 20, "penalty_multiplier": 2.0}
    compact = client.get(
        "/v1/session/dataset/eda-structural-breaks", params=params,
    ).json()
    expanded = client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={**params, "detail_level": "expanded"},
    ).json()

    assert len(expanded["series"]) > len(compact["series"])
    assert len(expanded["cusum_path"]) > len(compact["cusum_path"])
    # вторичный потолок — явная константа (по аналогии с бюджетом Task 76)
    assert len(expanded["series"]) <= EXPANDED_TARGET_SAMPLED_POINTS
    assert len(expanded["cusum_path"]) <= EXPANDED_TARGET_SAMPLED_POINTS
    assert expanded["series_sampled"] is True
    assert expanded["series_original_count"] == 3500

    # методология не изменилась: анализ (кандидаты/сегменты/статусы) идентичен
    assert expanded["break_count"] == compact["break_count"]
    assert expanded["status"] == compact["status"]
    assert [(c["index"], c["supported"]) for c in expanded["candidates"]] == [
        (c["index"], c["supported"]) for c in compact["candidates"]
    ]
    assert [(s["start_index"], s["end_index"], s["mean"]) for s in expanded["segments"]] == [
        (s["start_index"], s["end_index"], s["mean"]) for s in compact["segments"]
    ]


def test_structural_breaks_rejects_unknown_detail_level():
    _upload(_breaks_frame(200))
    response = client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "detail_level": "ultra"},
    )
    assert response.status_code == 422


# ── Декомпозиция (STL points: LTTB/полный ряд) ──────────────────────────────


def _decomposition_frame(n: int) -> pd.DataFrame:
    index = np.arange(n, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2015-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Price": 50 + index / 40 + 8 * np.sin(2 * np.pi * index / 7),
    })


def test_decomposition_compact_default_matches_current_contract():
    """compact без параметра и с ним — идентичные ключи/типы/объёмы."""
    _upload(_decomposition_frame(7000))

    default = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    ).json()
    compact = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price", "detail_level": "compact"},
    ).json()

    assert _signature(default) == _signature(compact)
    points = compact["profile"]["points"]
    assert len(points) == TARGET_SAMPLED_POINTS
    assert compact["profile"]["sampled"] is True


def test_decomposition_expanded_full_series_within_reason():
    """expanded: ряд до EXPANDED_FULL_POINTS_THRESHOLD отдаётся целиком."""
    _upload(_decomposition_frame(5000))
    compact = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    ).json()
    expanded = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price", "detail_level": "expanded"},
    ).json()

    assert 5000 <= EXPANDED_FULL_POINTS_THRESHOLD
    assert len(compact["profile"]["points"]) == TARGET_SAMPLED_POINTS
    # без даунсэмплинга: полный ряд, «sampled» честно сброшен
    assert len(expanded["profile"]["points"]) == 5000
    assert expanded["profile"]["sampled"] is False
    assert expanded["profile"]["n_points"] == 5000


def test_decomposition_expanded_above_full_threshold_uses_expanded_ceiling():
    """expanded выше полного порога: LTTB до расширенного потолка ≥ compact."""
    _upload(_decomposition_frame(7000))
    compact = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    ).json()
    expanded = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price", "detail_level": "expanded"},
    ).json()

    assert len(expanded["profile"]["points"]) > len(compact["profile"]["points"])
    assert len(expanded["profile"]["points"]) <= EXPANDED_TARGET_SAMPLED_POINTS
    assert expanded["profile"]["sampled"] is True

    # методология не изменилась: strength-метрики и сезонный профиль идентичны
    for key in ("trend_strength", "seasonal_strength", "ljung_box_pvalue", "jarque_bera_pvalue"):
        assert expanded["profile"][key] == compact["profile"][key]
    assert expanded["profile"]["seasonal_pattern"] == compact["profile"]["seasonal_pattern"]


def test_decomposition_rejects_unknown_detail_level():
    _upload(_decomposition_frame(100))
    response = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price", "detail_level": "ultra"},
    )
    assert response.status_code == 422


# ── Спектральный профиль (CWT-скалограмма: ось времени) ─────────────────────


def _spectral_frame(n: int) -> pd.DataFrame:
    index = np.arange(n, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Price": 10 + np.sin(2 * np.pi * index / 7) + 0.05 * np.sin(2 * np.pi * index / 31),
    })


def test_spectral_compact_default_matches_current_contract():
    """compact без параметра и с ним — идентичные ключи/типы/объёмы."""
    _upload(_spectral_frame(400))
    params = {"column": "Price", "wavelet_scales": 24}

    default = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile", params=params,
    ).json()
    compact = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile",
        params={**params, "detail_level": "compact"},
    ).json()

    assert _signature(default) == _signature(compact)
    # ось времени скалограммы срезается компактным потолком
    n_time = min(400, MAX_WAVELET_TIME_POINTS)
    assert len(compact["profile"]["wavelet"]) == 24 * n_time
    assert len(compact["profile"]["welch"]) > 0
    assert len(compact["profile"]["wavelet_global"]) == 24


def test_spectral_expanded_doubles_time_axis_within_ceiling():
    """expanded: ось времени CWT удваивается, остальные представления идентичны."""
    _upload(_spectral_frame(400))
    params = {"column": "Price", "wavelet_scales": 24}
    compact = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile", params=params,
    ).json()
    expanded = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile",
        params={**params, "detail_level": "expanded"},
    ).json()

    compact_points = compact["profile"]["wavelet"]
    expanded_points = expanded["profile"]["wavelet"]
    assert len(expanded_points) > len(compact_points)
    # потолок: scales (по запросу) × MAX_WAVELET_TIME_POINTS_EXPANDED
    assert len(expanded_points) <= 24 * MAX_WAVELET_TIME_POINTS_EXPANDED
    # ось периодов у обоих уровней одна (методология не меняется),
    # ось времени -- независимые linspace-сетки: сравниваем объёмы, не вложенность

    # методология не изменилась: Welch, глобальный CWT и ось периодов идентичны
    assert expanded["profile"]["welch"] == compact["profile"]["welch"]
    assert expanded["profile"]["wavelet_global"] == compact["profile"]["wavelet_global"]
    assert expanded["profile"]["wavelet_period_max"] == compact["profile"]["wavelet_period_max"]
    compact_periods = sorted({point["period"] for point in compact_points})
    expanded_periods = sorted({point["period"] for point in expanded_points})
    assert expanded_periods == compact_periods
    assert expanded["profile"]["candidates"] == compact["profile"]["candidates"]


def test_spectral_rejects_unknown_detail_level():
    _upload(_spectral_frame(40))
    response = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile",
        params={"column": "Price", "detail_level": "ultra"},
    )
    assert response.status_code == 422
