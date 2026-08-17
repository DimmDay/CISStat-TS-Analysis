# tests/api/test_internal_backtest.py
"""
Тесты для зеркала POST /v1/internal/models/backtest (Phase 0.5).

Зеркало существует, потому что /v1/models/backtest защищён
require_capability("can_train_models") — браузер посетителя standalone
без API-ключа не может вызвать /v1/models/backtest напрямую. Аналогично
/v1/internal/upload и /v1/internal/rules/*.

КЛЮЧЕВОЙ контракт Phase 0.5: зеркало использует РЕАЛЬНЫЙ ряд из
session.dataframe[target_column] когда они заданы, а не синтетику.
Это и есть «мост Upload → Backtest».
"""
from __future__ import annotations

import io
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


client = TestClient(app)


CSV_WITH_NUMERIC = (
    "date,value,category\n"
    "2023-01-01,10.5,A\n"
    "2023-01-02,20.1,B\n"
    "2023-01-03,30.2,A\n"
    "2023-01-04,40.7,B\n"
    "2023-01-05,50.0,A\n"
    "2023-01-06,60.3,B\n"
    "2023-01-07,70.8,A\n"
    "2023-01-08,80.1,B\n"
    "2023-01-09,90.4,A\n"
    "2023-01-10,100.2,B\n"
)


def _upload_and_set_target(csv: str = CSV_WITH_NUMERIC, target: str = "value"):
    """Загрузить датасет и установить target_column. Вернуть resp set."""
    file = io.BytesIO(csv.encode("utf-8"))
    upload_resp = client.post(
        "/v1/internal/upload",
        files={"file": ("test.csv", file, "text/csv")},
    )
    assert upload_resp.status_code == 200

    set_resp = client.post("/v1/session/target-column", json={"column": target})
    assert set_resp.status_code == 200
    return set_resp


# ────────────────────────────────────────────────────────────────────
# Базовая доступность зеркала
# ────────────────────────────────────────────────────────────────────


class TestInternalBacktestAvailability:
    """Зеркало отвечает, не требует X-Api-Key."""

    def test_no_api_key_required(self):
        """Запрос без X-Api-Key не возвращает 422 (в отличие от /v1/models/backtest)."""
        _upload_and_set_target()
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 8, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        # 200 — ок (нет auth), но не 422 (нет требования X-Api-Key)
        assert resp.status_code != 422
        assert resp.status_code == 200, resp.text

    def test_unknown_model_returns_404(self):
        _upload_and_set_target()
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "nonexistent_model",
                "profile": {"n_observations": 8, "frequency": "D"},
            },
        )
        assert resp.status_code == 404


# ────────────────────────────────────────────────────────────────────
# Мост Upload → Backtest: реальный ряд из сессии
# ────────────────────────────────────────────────────────────────────


class TestInternalBacktestUsesRealSeries:
    """Когда session.dataframe + target_column заданы — backtest использует
    реальный ряд, не синтетику. Это центральный контракт Phase 0.5."""

    def test_data_source_session_when_target_set(self):
        """При установленном target_column → data_source='session'."""
        _upload_and_set_target(target="value")
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 100, "frequency": "D"},  # фейк — должен быть override
                "train_ratio": 0.75,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["data_source"] == "session"
        # n_train + n_test = реальная длина (10 строк в CSV)
        assert data["n_train"] + data["n_test"] == 10
        assert data["n_train"] == 7  # 10 * 0.75 = 7.5 → 7
        assert data["n_test"] == 3

    def test_data_source_synthetic_when_no_target(self):
        """Без target_column → data_source='synthetic' (fallback на старое поведение)."""
        # Загружаем датасет, но НЕ устанавливаем target_column
        file = io.BytesIO(CSV_WITH_NUMERIC.encode("utf-8"))
        client.post(
            "/v1/internal/upload",
            files={"file": ("test.csv", file, "text/csv")},
        )
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 50, "frequency": "D"},
                "train_ratio": 0.8,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["data_source"] == "synthetic"
        # n_observations из profile, не из df
        assert data["n_train"] + data["n_test"] == 50

    def test_data_source_synthetic_when_no_dataset(self):
        """Без датасета вообще → synthetic fallback (как раньше)."""
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 50, "frequency": "D"},
                "train_ratio": 0.8,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["data_source"] == "synthetic"

    def test_real_series_metrics_differ_from_synthetic(self):
        """Реальный ряд (значения 10.5–100.2) даёт ДРУГИЕ метрики,
        чем синтетика (значения ~100–105). Это доказывает, что backtest
        действительно использует session.dataframe, а не игнорирует target_column."""
        _upload_and_set_target(target="value")
        # С реальным рядом
        real_resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 100, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        assert real_resp.status_code == 200
        real_mae = real_resp.json()["metrics"]["mae"]

        # Без target_column → синтетика
        file = io.BytesIO(CSV_WITH_NUMERIC.encode("utf-8"))
        client.post(
            "/v1/internal/upload",
            files={"file": ("test2.csv", file, "text/csv")},
        )
        synth_resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 100, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        assert synth_resp.status_code == 200
        synth_mae = synth_resp.json()["metrics"]["mae"]

        # Реальный ряд имеет сильный тренд (10 → 100), MAE должен быть
        # существенно больше, чем у синтетики (там ~100 с шумом ±2).
        assert real_mae > synth_mae * 2, (
            f"Real MAE ({real_mae}) should be much larger than "
            f"synthetic MAE ({synth_mae}) for trending real data"
        )


# ────────────────────────────────────────────────────────────────────
# Формат ответа совместим с /v1/models/backtest
# ────────────────────────────────────────────────────────────────────


class TestInternalBacktestResponseShape:
    """Зеркало возвращает ту же структуру, что и /v1/models/backtest
    (плюс поле data_source). Это позволяет фронтенду использовать
    тот же TypeScript-тип BacktestResponse."""

    def test_response_has_all_required_fields(self):
        _upload_and_set_target()
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "drift",
                "profile": {"n_observations": 8, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        required = {"model_id", "model_name", "family_id", "metrics",
                    "n_train", "n_test", "train_ratio", "duration_ms"}
        assert required.issubset(set(data.keys()))
        assert "data_source" in data
        # metrics has all required
        metrics = data["metrics"]
        assert {"mae", "rmse", "mape", "mase", "weighted_score"}.issubset(set(metrics.keys()))


# ────────────────────────────────────────────────────────────────────
# Различные baseline-модели (та же логика, что в /v1/models/backtest)
# ────────────────────────────────────────────────────────────────────


class TestInternalBacktestAllBaselines:
    """Все 4 baseline-модели должны работать с реальным рядом."""

    @pytest.mark.parametrize("model_id", ["naive", "seasonal_naive", "drift", "mean"])
    def test_baseline_models_work_with_real_series(self, model_id):
        _upload_and_set_target(target="value")
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": model_id,
                "profile": {"n_observations": 8, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_source"] == "session"
        assert resp.json()["metrics"]["weighted_score"] >= 0


# ────────────────────────────────────────────────────────────────────
# Edge case: target_column установлен, но df содержит NaN в этой колонке
# ────────────────────────────────────────────────────────────────────


class TestInternalBacktestHandlesNaN:
    """Если в target_column есть пропуски — backtest должен их пережить
    (dropna) или вернуть понятную ошибку."""

    def test_nan_in_target_column_handled_gracefully(self):
        csv_with_nan = (
            "date,value\n"
            "2023-01-01,10.0\n"
            "2023-01-02,\n"          # NaN
            "2023-01-03,30.0\n"
            "2023-01-04,40.0\n"
            "2023-01-05,50.0\n"
            "2023-01-06,60.0\n"
            "2023-01-07,70.0\n"
            "2023-01-08,80.0\n"
        )
        file = io.BytesIO(csv_with_nan.encode("utf-8"))
        client.post(
            "/v1/internal/upload",
            files={"file": ("nan.csv", file, "text/csv")},
        )
        # value всё ещё определяется как числовая колонка
        set_resp = client.post("/v1/session/target-column", json={"column": "value"})
        assert set_resp.status_code == 200

        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": "naive",
                "profile": {"n_observations": 8, "frequency": "D"},
                "train_ratio": 0.75,
            },
        )
        # Не должно упасть с 500 — dropna обрабатывает NaN
        assert resp.status_code == 200, resp.text
        # 7 строк после dropna
        data = resp.json()
        assert data["n_train"] + data["n_test"] == 7
