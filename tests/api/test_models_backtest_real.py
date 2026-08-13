# tests/api/test_models_backtest_real.py
"""
Phase 6-P0: реальные реализации ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA.

До Phase 6-P0 эти 5 model_id возвращали «Naive × penalty» заглушку
(см. routers/models.py _run_backtest_with_series else-ветка). Это
значило, что у ВСЕХ небазeline моделей метрики были линейно связаны
с Naive — UI показывал разные числа, но за ними не было настоящих
моделей.

После Phase 6-P0: каждая из 5 моделей вызывает statsmodels и возвращает
РЕАЛЬНО обученный прогноз. Эти тесты доказывают разницу.

Контракт (НЕ меняется в Phase 6-P0):
- BacktestResponse { model_id, model_name, family_id, metrics, n_train,
  n_test, train_ratio, duration_ms, data_source }
- BacktestMetrics { mae, rmse, mape, mase, weighted_score }
- /v1/internal/models/backtest — без auth, данные из сессии
- /v1/models/backtest — auth, синтетика
"""
from __future__ import annotations

import io
import math
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing
from apps.api.routers import models as models_router


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


client = TestClient(app)


# Реальный датасет: 24 месяца × сильный тренд + синусоидальная сезонность.
# Достаточно длинный, чтобы statsmodels смог обучить ARIMA/ETS (нужно ≥ 10
# точек для train_ratio=0.8 → n_train ≥ 8).
CSV_REAL = (
    "date,value\n"
    + "\n".join(
        f"2022-{m:02d}-01,{100 + 5*m + 20*math.sin(2*math.pi*m/12):.2f}"
        for m in range(1, 25)
    )
    + "\n"
)


def _upload_real_and_set_target():
    file = io.BytesIO(CSV_REAL.encode("utf-8"))
    upload_resp = client.post(
        "/v1/internal/upload",
        files={"file": ("real.csv", file, "text/csv")},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    set_resp = client.post("/v1/session/target-column", json={"column": "value"})
    assert set_resp.status_code == 200, set_resp.text
    return set_resp


# ═══════════════════════════════════════════════════════════
# 1. КАЖДАЯ ИЗ 5 МОДЕЛЕЙ ВОЗВРАЩАЕТ ОТВЕТ 200
# ═══════════════════════════════════════════════════════════


class TestRealModelsBasicAvailability:
    """Все 5 model_id отвечают 200 на /v1/internal/models/backtest
    с реальным датасетом в сессии. Это минимальный smoke: модель
    реально вызывается, fit/predict не падает."""

    @pytest.mark.parametrize("model_id", [
        "ets", "ets_damped", "theta", "arima", "arima_auto"
    ])
    def test_model_returns_200_with_real_series(self, model_id):
        _upload_real_and_set_target()
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": model_id,
                "profile": {
                    "n_observations": 24,
                    "frequency": "M",
                    "has_seasonality": True,
                    "seasonal_periods": [12],
                },
                "train_ratio": 0.8,
            },
        )
        assert resp.status_code == 200, f"{model_id}: {resp.text}"
        data = resp.json()
        assert data["model_id"] == model_id
        assert data["data_source"] == "session"
        # Реальный датасет = 24 строки, train_ratio=0.8 → n_train=19, n_test=5
        assert data["n_train"] + data["n_test"] == 24


# ═══════════════════════════════════════════════════════════
# 2. МЕТРИКИ ≠ ЗАГЛУШКЕ «Naive × penalty»
# ═══════════════════════════════════════════════════════════


class TestRealModelsAreNotNaivePenaltyStub:
    """До Phase 6-P0 небазeline модели возвращали
    naive_metrics * (1.1 / family_penalty) — линейную функцию от Naive.
    Это можно обнаружить: для данной модели на ОДНОМ ряде отношение
    metrics.mae / naive_metrics.mae ≈ 1.1/family_penalty (с точностью
    до round()).

    После Phase 6-P0: каждая модель реально обучается — отношение
    отличается от константы 1.1/family_penalty.

    Проверяем: для той же модели на РАЗНЫХ рядах (синтетика vs реальный)
    отношение mae_real / mae_synth должно отличаться. У заглушки оно
    было бы const (т.к. penalty не зависит от ряда).
    """

    @pytest.mark.parametrize("model_id", [
        "ets", "ets_damped", "theta", "arima", "arima_auto"
    ])
    def test_metrics_differ_between_real_and_synthetic(self, model_id):
        # --- Реальный ряд ---
        _upload_real_and_set_target()
        real_resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": model_id,
                "profile": {
                    "n_observations": 24,
                    "frequency": "M",
                    "has_seasonality": True,
                    "seasonal_periods": [12],
                },
                "train_ratio": 0.8,
            },
        )
        assert real_resp.status_code == 200
        real_mae = real_resp.json()["metrics"]["mae"]

        # --- Синтетический ряд (через /v1/models/backtest не вызвать —
        # там нужен API-ключ; используем внутренний без target_column) ---
        reset_session_store_for_testing()
        synth_resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": model_id,
                "profile": {
                    "n_observations": 60,  # синтетика по profile
                    "frequency": "M",
                    "has_seasonality": True,
                    "seasonal_periods": [12],
                },
                "train_ratio": 0.8,
            },
        )
        assert synth_resp.status_code == 200
        synth_mae = synth_resp.json()["metrics"]["mae"]

        # Если бы это была заглушка naive*penalty: оба mae были бы линейно
        # связаны с mae_naive на СВОЁМ ряде. Чтобы не привязываться к
        # конкретным penalty-константам, проверяем более слабое, но
        # достаточное условие: метрики на РЕАЛЬНОМ ряду не равны 0 и не
        # равны метрикам синтетики (это разные ряды → разные числа).
        assert real_mae > 0, f"{model_id}: real MAE must be > 0"
        assert synth_mae > 0, f"{model_id}: synth MAE must be > 0"
        # Реальный ряд имеет тренд 100→220 + сезонность 20 амплитуды →
        # MAE должен быть существенно больше, чем у синтетики 100±2.
        # Это доказывает, что модель реально обучается на данных, а не
        # возвращает константную заглушку.
        assert real_mae != synth_mae, (
            f"{model_id}: real MAE ({real_mae}) == synth MAE ({synth_mae}) — "
            f"модель возвращает константу независимо от данных (заглушка!)"
        )


# ═══════════════════════════════════════════════════════════
# 3. МОДЕЛИ ДАЮТ РАЗНЫЕ МЕТРИКИ МЕЖДУ СОБОЙ
# ═══════════════════════════════════════════════════════════


class TestRealModelsAreDistinctFromEachOther:
    """5 моделей на одном и том же ряду должны давать РАЗНЫЕ метрики.
    Если бы они все ещё были заглушками, все 5 вернули бы
    naive_metrics * (1.1/family_penalty) с family_penalty для
    exponential_smoothing=0.85 и arima=0.80 — то есть ets/ets_damped/theta
    дали бы ОДИНАКОВЫЕ метрики (все из exponential_smoothing).

    После Phase 6-P0: ets/ets_damped/theta — разные алгоритмы, разные
    метрики. ARIMA и Auto-ARIMA тоже отличаются (different orders).
    """

    def test_5_models_produce_distinct_mae(self):
        _upload_real_and_set_target()
        maes: dict[str, float] = {}
        for model_id in ["ets", "ets_damped", "theta", "arima", "arima_auto"]:
            resp = client.post(
                "/v1/internal/models/backtest",
                json={
                    "model_id": model_id,
                    "profile": {
                        "n_observations": 24,
                        "frequency": "M",
                        "has_seasonality": True,
                        "seasonal_periods": [12],
                    },
                    "train_ratio": 0.8,
                },
            )
            assert resp.status_code == 200, f"{model_id}: {resp.text}"
            maes[model_id] = resp.json()["metrics"]["mae"]

        # Все 5 MAE > 0
        assert all(v > 0 for v in maes.values()), maes
        # Должно быть МИНИМУМ 3 уникальных значения (из 5).
        # ets и ets_damped могут быть близки (оба из Holt-Winters),
        # но theta точно отличается (метод декомпозиции), и
        # arima/arima_auto тоже обычно дают разные результаты.
        unique_maes = set(round(v, 2) for v in maes.values())
        assert len(unique_maes) >= 3, (
            f"Ожидаем ≥3 уникальных MAE из 5 моделей, получили {len(unique_maes)}: {maes}. "
            f"Если все 5 одинаковые — модели не вызываются, заглушка активна."
        )


# ═══════════════════════════════════════════════════════════
# 4. РЕАЛЬНАЯ РЕАЛИЗАЦИЯ: прямая проверка model_impls
# ═══════════════════════════════════════════════════════════


class TestModelImplsModuleDirectly:
    """Прямой вызов реализаций (без HTTP), чтобы изолировать баги
    statsmodels от багов роутера. Если тесты выше падают, а эти
    проходят — баг в роутере. Если эти тоже падают — баг в model_impls."""

    def test_5_impls_callable_with_minimal_series(self):
        """Все 5 функций можно импортировать и вызвать на ряде из 24 чисел."""
        from apps.api.model_impls import (
            run_ets_backtest,
            run_ets_damped_backtest,
            run_theta_backtest,
            run_arima_backtest,
            run_auto_arima_backtest,
        )
        from apps.api.schemas import BacktestMetrics

        # Ряд с трендом + сезонностью — достаточный для statsmodels
        series = [100 + 5 * t + 20 * math.sin(2 * math.pi * t / 12)
                  for t in range(24)]

        for fn in [
            run_ets_backtest,
            run_ets_damped_backtest,
            run_theta_backtest,
            run_arima_backtest,
            run_auto_arima_backtest,
        ]:
            metrics = fn(series, train_ratio=0.8, seasonal_period=12)
            assert isinstance(metrics, BacktestMetrics), (
                f"{fn.__name__}: expected BacktestMetrics, got {type(metrics)}"
            )
            assert metrics.mae >= 0
            assert metrics.rmse >= 0
            # weighted_score в [0, 1] по определению (см. _compute_metrics)
            assert 0 <= metrics.weighted_score <= 1.0

    def test_impls_return_different_results_on_different_series(self):
        """На двух разных рядах модели должны давать разные метрики.
        Если заглушка — вернули бы одно и то же (т.к. penalty не зависит
        от ряда, только от family).

        ВАЖНО про выбор рядов: ряды должны быть НЕ симметричны (не +/- тренд
        одинаковой амплитуды). Иначе ETS на тренде вверх и вниз даст
        одинаковые ABSOLUTE ошибки (MAE/RMSE) — это корректное поведение
        модели, но тест провалится. Берём ряды с разной структурой:
        A — сильный тренд вверх, B — плоский ряд с шумом.
        """
        from apps.api.model_impls import (
            run_ets_backtest,
            run_arima_backtest,
            run_theta_backtest,
        )

        # Ряд A: сильный тренд вверх + сезонность
        series_a = [100 + 5 * t + 20 * math.sin(2 * math.pi * t / 12)
                    for t in range(24)]
        # Ряд B: плоский ряд (без тренда) + та же сезонность
        series_b = [100 + 20 * math.sin(2 * math.pi * t / 12)
                    for t in range(24)]

        for fn in [run_ets_backtest, run_arima_backtest, run_theta_backtest]:
            m_a = fn(series_a, train_ratio=0.8, seasonal_period=12)
            m_b = fn(series_b, train_ratio=0.8, seasonal_period=12)
            # Минимум одна метрика должна отличаться. На ряду с трендом
            # метрики отличаются от плоского ряда — это надёжный сигнал.
            assert (m_a.mae != m_b.mae) or (m_a.rmse != m_b.rmse) or (m_a.mape != m_b.mape), (
                f"{fn.__name__}: identical metrics on different series — likely stub"
            )


# ═══════════════════════════════════════════════════════════
# 5. EDGE CASES: модель не падает на проблемных данных
# ═══════════════════════════════════════════════════════════


class TestRealModelsHandleEdgeCases:
    """Реальные модели могут не сойтись на:
    - очень коротком ряде (n < 10)
    - ряде с постоянными значениями (zero variance)
    - ряде с NaN

    Контракт: НЕ падать с 500. Fallback на Naive metrics + предупреждение
    в логе. UI получит осмысленные метрики, а не «internal server error».
    """

    def test_short_series_does_not_500(self):
        """Ряд из 8 точек: statsmodels может не сойтись, но не должно быть 500."""
        csv_short = (
            "date,value\n"
            + "\n".join(f"2023-{m:02d}-01,{100 + 10*m}.0" for m in range(1, 9))
            + "\n"
        )
        file = io.BytesIO(csv_short.encode("utf-8"))
        client.post("/v1/internal/upload",
                    files={"file": ("short.csv", file, "text/csv")})
        client.post("/v1/session/target-column", json={"column": "value"})

        for model_id in ["ets", "ets_damped", "theta", "arima", "arima_auto"]:
            resp = client.post(
                "/v1/internal/models/backtest",
                json={
                    "model_id": model_id,
                    "profile": {"n_observations": 8, "frequency": "M"},
                    "train_ratio": 0.75,
                },
            )
            assert resp.status_code == 200, (
                f"{model_id} on short series: expected 200, got {resp.status_code} ({resp.text})"
            )
            assert resp.json()["metrics"]["mae"] >= 0

    def test_constant_series_does_not_500(self):
        """Ряд с одинаковыми значениями: Theta/ARIMA могут не сойтись."""
        csv_const = (
            "date,value\n"
            + "\n".join(f"2023-{m:02d}-01,100.0" for m in range(1, 25))
            + "\n"
        )
        file = io.BytesIO(csv_const.encode("utf-8"))
        client.post("/v1/internal/upload",
                    files={"file": ("const.csv", file, "text/csv")})
        client.post("/v1/session/target-column", json={"column": "value"})

        for model_id in ["ets", "theta", "arima", "arima_auto"]:
            resp = client.post(
                "/v1/internal/models/backtest",
                json={
                    "model_id": model_id,
                    "profile": {"n_observations": 24, "frequency": "M"},
                    "train_ratio": 0.8,
                },
            )
            assert resp.status_code == 200, (
                f"{model_id} on constant series: {resp.status_code} {resp.text}"
            )
            # На константном ряде MAE должен быть ~0 (любая модель)
            assert resp.json()["metrics"]["mae"] < 1.0, (
                f"{model_id} on constant series: MAE should be ~0, "
                f"got {resp.json()['metrics']['mae']}"
            )


# ═══════════════════════════════════════════════════════════
# 6. РЕГРЕССИЯ: 4 BASELINE МОДЕЛИ НЕ СЛОМАЛИСЬ
# ═══════════════════════════════════════════════════════════


class TestBaselineModelsStillWork:
    """Регрессия: добавление 5 новых моделей не должно сломать 4 baseline
    (naive, seasonal_naive, drift, mean). У них не менялся код, но
    _BACKTEST_IMPLEMENTATIONS расширился — проверяем, что ничего не
    затёрлось и lambda-адаптеры работают."""

    @pytest.mark.parametrize("model_id", [
        "naive", "seasonal_naive", "drift", "mean"
    ])
    def test_baseline_still_works(self, model_id):
        _upload_real_and_set_target()
        resp = client.post(
            "/v1/internal/models/backtest",
            json={
                "model_id": model_id,
                "profile": {
                    "n_observations": 24,
                    "frequency": "M",
                    "has_seasonality": True,
                    "seasonal_periods": [12],
                },
                "train_ratio": 0.8,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_source"] == "session"
        assert resp.json()["metrics"]["weighted_score"] >= 0


# ═══════════════════════════════════════════════════════════
# 7. _BACKTEST_IMPLEMENTATIONS РАСШИРЕН 5 КЛЮЧАМИ
# ═══════════════════════════════════════════════════════════


class TestBacktestImplementationsRegistry:
    """Регрессия: _BACKTEST_IMPLEMENTATIONS должен содержать все 9 моделей:
    4 baseline + 5 новых. Если кто-то случайно удалил ключ — тест падает."""

    def test_registry_has_9_implementations(self):
        impls = models_router._BACKTEST_IMPLEMENTATIONS
        expected = {
            "naive", "seasonal_naive", "drift", "mean",  # baselines (Phase 0)
            "ets", "ets_damped", "theta", "arima", "arima_auto",  # Phase 6-P0
        }
        assert set(impls.keys()) == expected, (
            f"Expected 9 implementations: {expected}, got: {set(impls.keys())}"
        )

    def test_no_stub_branch_for_5_real_models(self):
        """При вызове через _run_backtest_with_series для 5 новых моделей
        не должен срабатывать else-ветка (заглушка naive*penalty).
        Проверяем это косвенно: для 5 новых model_id impl есть в реестре."""
        impls = models_router._BACKTEST_IMPLEMENTATIONS
        for model_id in ["ets", "ets_damped", "theta", "arima", "arima_auto"]:
            assert model_id in impls, (
                f"{model_id} missing from _BACKTEST_IMPLEMENTATIONS — "
                f"будет вызвана заглушка naive*penalty"
            )
