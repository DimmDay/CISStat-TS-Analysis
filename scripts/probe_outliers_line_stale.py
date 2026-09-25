"""Контрольный замер (проба) дефекта «график выбросов не изменился после кэпирования».

Сценарий тимлида (2026-09-25):
  1. Загружен демо-датасет forecast_monitor_synthetic_n150.csv (4 выброса).
  2. Обзор «Выбросы»: линейный график показывает выбросы, счётчик "выбросов - 4".
  3. Мастер: метод IQR, стратегия cap, apply.
  4. Возврат на линейный график: график НЕ изменился, счётчик "выбросов - 0".

Проба проверяет БЭКЕНД-часть: меняется ли ответ GET /dataset/outlier-line
(источник данных линейного графика) после POST /dataset/outlier-corrections
apply=true. Генератор демо-датасета -- дословный порт demoDatasets.ts
(mulberry32 + Box-Muller, FORECAST_MONITOR_SEED=20260916).
"""
from __future__ import annotations

import io
import math
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import reset_session_store_for_testing  # noqa: E402

M32 = 0xFFFFFFFF


def _imul(x: int, y: int) -> int:
    return (x * y) & M32


def mulberry32(seed: int):
    state = seed & M32

    def rng() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & M32
        t = _imul(state ^ (state >> 15), (1 | state) & M32)
        t = (((t + _imul(t ^ (t >> 7), (61 | t) & M32)) & M32) ^ t) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rng


def gaussian(rng, mean: float, std: float) -> float:
    u1 = max(rng(), 1e-9)
    u2 = rng()
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    return mean + z * std


N = 150
START = datetime(2013, 1, 1, tzinfo=timezone.utc)
SEED = 20260916
OUTLIERS = {25: 110.0, 70: 105.0, 105: 95.0, 130: -135.0}
MISSING = {45, 87, 122}


def generate_csv() -> str:
    rng = mulberry32(SEED)
    lines = ["date,value"]
    for t in range(N):
        # addMonths(2013-01-01, t): JS setMonth на 1-м числе -- без переполнения дня
        date = add_months(START, t)
        value = 120.0 + 0.55 * t + 18.0 * math.sin((2.0 * math.pi * (t + 2.0)) / 12.0) + gaussian(rng, 0, 3.2)
        if t in OUTLIERS:
            value += OUTLIERS[t]
        # JS toFixed(2): округление к ближайшему, toFixed-эмуляция
        value_str = f"{value:.2f}"
        if t in MISSING:
            value_str = ""
        lines.append(f"{date.strftime('%Y-%m-%d')},{value_str}")
    return "\n".join(lines) + "\n"


def add_months(base: datetime, months: int) -> datetime:
    # setMonth(getMonth()+months) на 1-м числе -- переполнения дня нет
    total = (base.year * 12 + base.month - 1) + months
    return datetime(total // 12, total % 12 + 1, 1, tzinfo=timezone.utc)


def main() -> None:
    reset_session_store_for_testing()
    client = TestClient(app)

    csv_text = generate_csv()
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("forecast_monitor_synthetic_n150.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text
    print("1) Загружен демо-датасет:", response.json().get("dataset", {}).get("name", "?"))

    profile = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    print("2) Профиль IQR: total_outliers =", profile["total_outliers"],
          "| affected:", profile["affected_columns"])

    raw = client.get("/v1/session/dataset/outlier-line", params={"column": "value"}).json()
    points_before = [p["y"] for p in raw["points"]]
    print("3) Линейный график ДО: точек =", len(points_before),
          "| min =", min(points_before), "| max =", max(points_before))

    # Пропуска дают NaN -- dropna() на бэкенде; проверяем, что позиций меньше N
    applied = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    print("4) Apply cap: total_outliers =", body["total_outliers"],
          "| total_changed =", body["total_changed"],
          "| rows_removed =", body["rows_removed"])

    profile_after = client.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    print("5) Профиль ПОСЛЕ: total_outliers =", profile_after["total_outliers"])

    raw_after = client.get("/v1/session/dataset/outlier-line", params={"column": "value"}).json()
    points_after = [p["y"] for p in raw_after["points"]]
    print("6) Линейный график ПОСЛЕ: точек =", len(points_after),
          "| min =", min(points_after), "| max =", max(points_after))

    same = points_before == points_after
    print("7) ВЕРДИКТ (бэкенд): ряд линейного графика", "НЕ ИЗМЕНИЛСЯ" if same else "ИЗМЕНИЛСЯ")
    if not same:
        diffs = [(i, a, b) for i, (a, b) in enumerate(zip(points_before, points_after)) if a != b]
        print("   Изменённых точек:", len(diffs), "; первые 6:", diffs[:6])


if __name__ == "__main__":
    main()
