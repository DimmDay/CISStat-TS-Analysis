#!/usr/bin/env python3
# scripts/probe_missing_charts_revision.py
#
# Волна 1 plan_review_charts.md (класс OUTL-1, 2026-09-26): бэкенд-контракт
# пробы -- неизвестный query-параметр `revision` (cache-buster фронтенда)
# ИГНОРИРУЕТСЯ тремя эндпоинтами графиков остановки «Пропуски»: ответ с
# ревизией байт-в-байт совпадает с ответом без неё (200), payload идентичен.
# Дополнительно: apply исправления пропусков меняет payload матрицы --
# свежесть данных на сервере подтверждена (stale-данные исключены, как в
# OUTL-1: источником симптома был только фронтенд).
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402


def demo_dataset(client: "TestClient") -> None:
    # Встроенный демо-датасет (sales_demo.csv) пропусков НЕ содержит (проверено),
    # а встроенный forecast_monitor_synthetic_n150.csv -- датасет выбросов
    # (OUTL-1). Для пробы «Пропусков» нужен ряд С ЗАЗОРАМИ: детерминированный
    # mulberry32 (seed 20260916) -- тот же приём генерации, что в
    # scripts/probe_outliers_line_stale.py (дословный порт демо-генератора),
    # с принудительными NaN-зазорами в части строк.
    import io
    import math

    def mulberry32(seed: int):
        def rnd():
            nonlocal seed
            seed |= 0
            seed = (seed + 0x6D2B79F5) | 0
            t = math.floor(seed * (1 / 4294967296)) & 0xFFFFFFFF
            t = (t + 0x6D2B79F5) & 0xFFFFFFFF
            r = (t ^ (t >> 15)) & 0xFFFFFFFF
            r = (r + ((r * (r | 1)) & 0xFFFFFFFF)) & 0xFFFFFFFF
            r = (r ^ (r + ((r ^ (r >> 7)) & 0x61C88647)) & 0xFFFFFFFF) & 0xFFFFFFFF
            return ((r ^ (r >> 14)) & 0xFFFFFFFF) / 4294967296

        return rnd

    rnd = mulberry32(20260916)
    lines = ["date,value,region"]
    for i in range(120):
        u1, u2 = max(rnd(), 1e-12), rnd()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        # NaN-зазоры в ОБЕИХ колонках: числовая (value) -- для графика,
        # категориальная (region) -- для колонки-индикатора missing-distribution.
        value = "" if i % 7 == 3 else f"{100 + z * 15:.2f}"
        region = "" if i % 9 == 5 else f"R{i % 4}"
        lines.append(f"2026-01-{(i % 28) + 1:02d},{value},{region}")
    files = {"file": ("probe_missing.csv", "\n".join(lines).encode())}
    response = client.post("/v1/internal/upload", files=files)
    assert response.status_code == 200, f"upload failed: {response.status_code} {response.text[:200]}"


def main() -> None:
    client = TestClient(app)
    demo_dataset(client)

    endpoints = ["/v1/session/dataset/missing-matrix", "/v1/session/dataset/missing-correlation"]
    for endpoint in endpoints:
        base = client.get(endpoint)
        revised = client.get(endpoint, params={"revision": 5})
        assert base.status_code == 200, f"{endpoint}: HTTP {base.status_code}"
        assert revised.status_code == 200, f"{endpoint}?revision: HTTP {revised.status_code}"
        assert json.dumps(base.json(), sort_keys=True) == json.dumps(revised.json(), sort_keys=True), (
            f"{endpoint}: payload изменился от неизвестного параметра revision"
        )
        print(f"[1] {endpoint}: 200 c ?revision=5, payload идентичен -- параметр игнорируется")

    # missing-distribution: ревизия добавляется В ХВОСТ существующих параметров
    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["total_missing"] > 0, "демо-датасет не содержит пропусков для пробы"
    missing_columns = [c["column"] for c in profile["columns"] if c["missing_count"] > 0]
    numeric = [c["column"] for c in profile["columns"] if c["semantic"] == "numeric"]
    value_column = numeric[0]
    # Индикатор обязан отличаться от value-колонки (otherColumns Обзора её
    # исключает) -- берём первую колонку с пропусками, не равную value.
    indicator_column = next((c for c in missing_columns if c != value_column), None)
    assert indicator_column is not None, (
        "в пробе нет колонки-индикатора с пропусками, отличной от value-колонки"
    )

    base = client.get(
        "/v1/session/dataset/missing-distribution",
        params={"value_column": value_column, "indicator_column": indicator_column},
    )
    revised = client.get(
        "/v1/session/dataset/missing-distribution",
        params={"value_column": value_column, "indicator_column": indicator_column, "revision": 2},
    )
    assert base.status_code == 200 and revised.status_code == 200, (
        f"missing-distribution: HTTP {base.status_code}/{revised.status_code}"
    )
    assert json.dumps(base.json(), sort_keys=True) == json.dumps(revised.json(), sort_keys=True)
    print("[1] /v1/session/dataset/missing-distribution: 200 c &revision=2, payload идентичен -- параметр игнорируется")

    # Свежесть данных на сервере: исправление пропусков меняет payload матрицы
    before = json.dumps(client.get("/v1/session/dataset/missing-matrix").json(), sort_keys=True)
    correction = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"strategy": "drop_rows", "columns": missing_columns, "apply": True},
    )
    assert correction.status_code == 200, f"correction: HTTP {correction.status_code} {correction.text[:200]}"
    after = json.dumps(client.get("/v1/session/dataset/missing-matrix").json(), sort_keys=True)
    assert before != after, "payload матрицы не изменился после apply -- бэкенд не отражает исправление"
    print("[2] после apply (drop_rows) payload матрицы изменился -- бэкенд свежих данных подтверждён")

    print("PROBE OK: 4 контура пройдено")


if __name__ == "__main__":
    main()
