# tests/api/test_models_candidates.py
"""
Тесты для API-эндпоинтов модуля «Моделирование»:
  POST /v1/models/candidates
  POST /v1/models/backtest
"""
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

import os
os.environ["CISSTAT_API_KEYS"] = (
    "test-key:external_user:demo,"
    "pro-key:external_user:professional,"
    "admin-key:admin:"
)

DEMO_HEADERS = {"X-API-Key": "test-key"}       # can_train_models=False
PRO_HEADERS  = {"X-API-Key": "pro-key"}        # can_train_models=True
ADMIN_HEADERS = {"X-API-Key": "admin-key"}     # can_train_models=True


# ── Макроэкономический профиль для тестов ──
MACRO_PROFILE = {
    "n_observations": 120,
    "n_series": 1,
    "n_exogenous": 0,
    "is_regular": True,
    "frequency": "M",
    "has_seasonality": True,
    "seasonal_periods": [12],
    "is_stationary_or_diffable": True,
    "is_cointegrated": False,
    "has_negative_values": False,
    "has_volatility_clustering": False,
    "domain": "macro",
    "missing_ratio": 0.0,
    "outlier_ratio": 0.0,
}


# ═══════════════════════════════════════════════════════════
# 1. АВТОРИЗАЦИЯ
# ═══════════════════════════════════════════════════════════

class TestCandidatesAuth:
    """Проверка авторизации и доступа."""

    def test_no_api_key_returns_401_or_422(self):
        """Без API-ключа — отказ."""
        resp = client.post("/v1/models/candidates", json={"profile": MACRO_PROFILE})
        # FastAPI: 422 (missing header) or 401 (if header required)
        assert resp.status_code in (401, 422, 403)

    def test_demo_plan_forbidden(self):
        """Demo-план не имеет can_train_models → 403."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=DEMO_HEADERS,
        )
        assert resp.status_code == 403

    def test_professional_plan_allowed(self):
        """Professional-план имеет can_train_models → 200."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200

    def test_admin_allowed(self):
        """Admin имеет can_train_models → 200."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# 2. СТРУКТУРА ОТВЕТА
# ═══════════════════════════════════════════════════════════

class TestCandidatesResponse:
    """Проверка структуры ответа."""

    def test_response_has_candidates(self):
        """Ответ содержит список candidates."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert "candidates" in data
        assert isinstance(data["candidates"], list)
        assert len(data["candidates"]) > 0

    def test_candidate_structure(self):
        """Каждый кандидат имеет обязательные поля."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        candidate = data["candidates"][0]
        for field in ["model_id", "model_name", "family_id", "level", "rank"]:
            assert field in candidate, f"Missing field: {field}"

    def test_response_has_statistics(self):
        """Ответ содержит статистику по уровням."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert "statistics" in data
        stats = data["statistics"]
        assert "total_candidates" in stats
        assert "by_level" in stats

    def test_response_has_spec_version(self):
        """Ответ содержит версию спецификации."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert "spec_version" in data


# ═══════════════════════════════════════════════════════════
# 3. ЛОГИКА ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class TestCandidatesApplicability:
    """Проверка логики движка применимости через API."""

    def test_baselines_always_in_candidates(self):
        """Baseline-модели всегда в пуле кандидатов."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        ids = {c["model_id"] for c in data["candidates"]}
        assert "naive" in ids
        assert "drift" in ids
        assert "mean" in ids

    def test_garch_not_for_macro(self):
        """GARCH не входит в кандидаты для макроэкономических данных."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        ids = {c["model_id"] for c in data["candidates"]}
        assert "garch" not in ids

    def test_all_candidates_not_not_applicable(self):
        """Все кандидаты имеют уровень ≠ NOT_APPLICABLE."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        for c in data["candidates"]:
            assert c["level"] != "NOT_APPLICABLE", (
                f"{c['model_id']} is NOT_APPLICABLE but in candidate pool"
            )

    def test_candidates_sorted_by_rank(self):
        """Кандидаты отсортированы по rank (RECOMMENDED первыми)."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        ranks = [c["rank"] for c in data["candidates"]]
        assert ranks == sorted(ranks)


# ═══════════════════════════════════════════════════════════
# 4. РАЗНЫЕ ПРОФИЛИ
# ═══════════════════════════════════════════════════════════

class TestCandidatesDifferentProfiles:
    """Проверка разных профилей данных."""

    def test_financial_profile_garch_recommended(self):
        """Финансовый профиль → GARCH в кандидатах (RECOMMENDED)."""
        profile = {
            "n_observations": 500,
            "n_series": 1,
            "n_exogenous": 0,
            "is_regular": True,
            "frequency": "D",
            "has_seasonality": False,
            "seasonal_periods": [],
            "is_stationary_or_diffable": False,
            "is_cointegrated": False,
            "has_negative_values": True,
            "has_volatility_clustering": True,
            "domain": "financial",
            "missing_ratio": 0.0,
            "outlier_ratio": 0.02,
        }
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": profile},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        garch = next(
            (c for c in data["candidates"] if c["model_id"] == "garch"),
            None,
        )
        assert garch is not None
        assert garch["level"] == "RECOMMENDED"

    def test_tiny_profile_only_baselines_and_ets(self):
        """Малый профиль (n=10) → только baselines + ETS-подобные."""
        profile = {
            "n_observations": 10,
            "n_series": 1,
            "n_exogenous": 0,
            "is_regular": True,
            "frequency": "M",
            "has_seasonality": False,
            "seasonal_periods": [],
            "is_stationary_or_diffable": True,
            "is_cointegrated": False,
            "has_negative_values": False,
            "has_volatility_clustering": False,
            "domain": "macro",
            "missing_ratio": 0.0,
            "outlier_ratio": 0.0,
        }
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": profile},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        ids = {c["model_id"] for c in data["candidates"]}
        # Baselines всегда есть
        assert "naive" in ids
        # ARIMA (min=50) не должен быть в пуле
        assert "arima" not in ids
        # DL модели тоже не должны быть
        assert "lstm" not in ids


# ═══════════════════════════════════════════════════════════
# 5. ВАЛИДАЦИЯ ЗАПРОСА
# ═══════════════════════════════════════════════════════════

class TestCandidatesValidation:
    """Проверка валидации входных данных."""

    def test_missing_profile_returns_422(self):
        """Запрос без profile → 422."""
        resp = client.post(
            "/v1/models/candidates",
            json={},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_n_observations_returns_422(self):
        """n_observations < 1 → 422."""
        profile = {**MACRO_PROFILE, "n_observations": 0}
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": profile},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_missing_ratio_returns_422(self):
        """missing_ratio > 1.0 → 422."""
        profile = {**MACRO_PROFILE, "missing_ratio": 1.5}
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": profile},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
# 6. ОПЦИОНАЛЬНЫЕ ПАРАМЕТРЫ
# ═══════════════════════════════════════════════════════════

class TestCandidatesOptions:
    """Проверка опциональных параметров запроса."""

    def test_min_level_filter(self):
        """min_level=RECOMMENDED — только RECOMMENDED модели."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "RECOMMENDED"},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        for c in data["candidates"]:
            assert c["level"] == "RECOMMENDED"

    def test_min_level_default_includes_conditional(self):
        """По умолчанию min_level=CONDITIONALLY_APPLICABLE — включает оба уровня."""
        resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        levels = {c["level"] for c in data["candidates"]}
        # Должен быть хотя бы RECOMMENDED
        assert "RECOMMENDED" in levels


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ═══════════════════════════════════════════════════════════
# BACKTEST: POST /v1/models/backtest
# ═══════════════════════════════════════════════════════════

class TestBacktestAuth:
    """Проверка авторизации бэктеста."""

    def test_no_api_key_returns_401_or_422(self):
        resp = client.post("/v1/models/backtest", json={
            "model_id": "naive", "profile": MACRO_PROFILE,
        })
        assert resp.status_code in (401, 422, 403)

    def test_demo_plan_forbidden(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=DEMO_HEADERS,
        )
        assert resp.status_code == 403

    def test_professional_plan_allowed(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200


class TestBacktestNaive:
    """Бэктест для Naive — реальный расчёт."""

    def test_naive_returns_metrics(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_id"] == "naive"
        assert "metrics" in data
        m = data["metrics"]
        for key in ("mae", "rmse", "mape", "mase", "weighted_score"):
            assert key in m, f"Missing metric: {key}"
            assert m[key] >= 0, f"{key} should be non-negative"

    def test_naive_metrics_reasonable_range(self):
        """Naive на синтетике с трендом должен давать MAE > 0 и < 100."""
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        m = resp.json()["metrics"]
        assert 0 < m["mae"] < 100
        assert 0 < m["rmse"] < 100
        assert m["mape"] >= 0  # MAPE может быть 0 если все y_true одинаковые
        assert m["mase"] >= 0
        assert 0 <= m["weighted_score"] <= 1

    def test_naive_response_has_split_info(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert data["n_train"] > 0
        assert data["n_test"] > 0
        assert data["n_train"] + data["n_test"] == MACRO_PROFILE["n_observations"]
        assert data["train_ratio"] == 0.8
        assert data["duration_ms"] >= 0

    def test_naive_model_info(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert data["model_name"] == "Naive"
        assert data["family_id"] == "baselines"


class TestBacktestOtherBaselines:
    """Бэктест для других baseline-моделей (реальный расчёт)."""

    @pytest.mark.parametrize("model_id", ["seasonal_naive", "drift", "mean"])
    def test_baseline_returns_valid_metrics(self, model_id):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": model_id, "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200
        m = resp.json()["metrics"]
        assert m["mae"] > 0
        assert m["rmse"] >= m["mae"]  # RMSE >= MAE всегда


class TestBacktestNonBaseline:
    """Бэктест для нереализованных моделей — заглушка."""

    def test_ets_returns_approx_metrics(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "ets", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_id"] == "ets"
        assert data["model_name"] == "ETS (Auto)"
        assert data["metrics"]["mae"] > 0

    def test_arima_auto_returns_approx_metrics(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "arima_auto", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["mae"] > 0


class TestBacktestValidation:
    """Валидация запроса бэктеста."""

    def test_unknown_model_returns_404(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "nonexistent_model", "profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 404

    def test_missing_model_id_returns_422(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"profile": MACRO_PROFILE},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_train_ratio_returns_422(self):
        """train_ratio > 0.95 → 422."""
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE, "train_ratio": 0.99},
            headers=PRO_HEADERS,
        )
        assert resp.status_code == 422


class TestBacktestCustomTrainRatio:
    """Разные train_ratio."""

    def test_train_ratio_0_5(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE, "train_ratio": 0.5},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert data["n_train"] == 60
        assert data["n_test"] == 60

    def test_train_ratio_0_95(self):
        resp = client.post(
            "/v1/models/backtest",
            json={"model_id": "naive", "profile": MACRO_PROFILE, "train_ratio": 0.95},
            headers=PRO_HEADERS,
        )
        data = resp.json()
        assert data["n_train"] == 114
        assert data["n_test"] == 6
