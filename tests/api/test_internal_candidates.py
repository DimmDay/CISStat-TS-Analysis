# tests/api/test_internal_candidates.py
"""
Тесты для зеркала POST /v1/internal/models/candidates (Phase 1 follow-up).

Зеркало существует по той же причине, что и /v1/internal/models/backtest
(Phase 0.5): /v1/models/candidates защищён require_capability(
"can_train_models") — браузер посетителя standalone без API-ключа не может
вызвать /v1/models/candidates. Симптом бага (Task 14 fix): на /modeling
странице после upload'а датасета автоматически срабатывал fetch кандидатов,
запрос падал с 422 (missing X-Api-Key), в UI выводилось
"Ошибка: [object Object],[object Object]" (массив Pydantic-ошибок,
приведённый к строке). Из-за этого candidates=[] → activeCandidate=null →
кнопка бэктеста не отрисовывалась → пользователь видел «бэктест не активный».

Контракт зеркала /v1/internal/models/candidates:
  - НЕ требует X-Api-Key
  - Возвращает тот же CandidatesResponse, что и /v1/models/candidates
  - Принимает тот же CandidatesRequest (profile + min_level)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


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
# 1. АВТОРИЗАЦИЯ — зеркало НЕ требует X-Api-Key
# ═══════════════════════════════════════════════════════════

class TestInternalCandidatesAuth:
    """Зеркало /v1/internal/models/candidates НЕ требует X-Api-Key.

    Это критическое отличие от /v1/models/candidates (см. test_models_candidates.py).
    Браузер visitior'а standalone НЕ имеет API-ключа — без зеркала UI падал с
    422 "Field required: x-api-key", что и было зарепорчено как
    "Ошибка: [object Object],[object Object]".
    """

    def test_no_api_key_required(self):
        """Запрос без X-Api-Key возвращает 200 (не 422, не 401).

        Это и есть регрессия Task 14: раньше UI падал здесь с 422.
        """
        resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "CONDITIONALLY_APPLICABLE"},
        )
        # КРИТИЧНО: НЕ 422 (missing header), НЕ 401/403 (auth failure)
        assert resp.status_code != 422, (
            f"Reg: зеркало требует X-Api-Key (баг!): {resp.text}"
        )
        assert resp.status_code in (200, 403, 401), resp.text
        # Главный кейс: 200 OK
        assert resp.status_code == 200, (
            f"Ожидали 200, получили {resp.status_code}: {resp.text}"
        )

    def test_with_api_key_also_works(self):
        """Если ключ передан (например, embedded-режим) — тоже работает."""
        resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE},
            headers={"X-Api-Key": "any-key"},
        )
        assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════
# 2. КОНТРАКТ ОТВЕТА — то же, что и /v1/models/candidates
# ═══════════════════════════════════════════════════════════

class TestInternalCandidatesContract:
    """Форма ответа идентична /v1/models/candidates.

    Это позволяет UI работать с обоими эндпоинтами взаимозаменяемо
    (мы переключились на internal, но типы/поля те же).
    """

    def test_response_shape(self):
        """Response = { candidates: [...], statistics: {...}, spec_version: str }."""
        resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "CONDITIONALLY_APPLICABLE"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "candidates" in data
        assert "statistics" in data
        assert "spec_version" in data

        assert isinstance(data["candidates"], list)
        assert len(data["candidates"]) > 0, "Пул кандидатов не должен быть пустым"

        # Структура каждой записи-кандидата
        c = data["candidates"][0]
        for field in ("model_id", "model_name", "family_id", "level"):
            assert field in c, f"У кандидата нет поля {field}"

        # Статистика
        stats = data["statistics"]
        for field in ("total_candidates", "by_level", "total_models_in_spec"):
            assert field in stats, f"В статистике нет поля {field}"

    def test_min_level_filter(self):
        """RECOMMENDED должен вернуть ПОДМНОЖЕВО более мягкого фильтра."""
        rec_resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "RECOMMENDED"},
        )
        cond_resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "CONDITIONALLY_APPLICABLE"},
        )
        assert rec_resp.status_code == 200
        assert cond_resp.status_code == 200

        rec_total = rec_resp.json()["statistics"]["total_candidates"]
        cond_total = cond_resp.json()["statistics"]["total_candidates"]
        # Более строгий фильтр → не больше кандидатов
        assert rec_total <= cond_total, (
            f"RECOMMENDED ({rec_total}) должен быть ≤ "
            f"CONDITIONALLY_APPLICABLE ({cond_total})"
        )

    def test_returns_same_candidates_as_protected_endpoint(self):
        """Зеркало возвращает ТОТ ЖЕ список, что и /v1/models/candidates с auth.

        Это доказывает, что зеркало переиспользует ту же бизнес-логику,
        а не делает что-то иное. Если зеркальный ответ отличается — UI
        увидит несоответствие между embedded (public) и standalone (internal).
        """
        # Сравним с /v1/models/candidates (с тем же profile, нужен API-ключ)
        import os
        os.environ["CISSTAT_API_KEYS"] = (
            "test-key:external_user:demo,"
            "pro-key:external_user:professional,"
            "admin-key:admin:"
        )
        # auth._parse_key_registry() читает env лениво при каждом вызове,
        # reload не требуется.

        protected_resp = client.post(
            "/v1/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "CONDITIONALLY_APPLICABLE"},
            headers={"X-Api-Key": "admin-key"},
        )
        assert protected_resp.status_code == 200, protected_resp.text

        internal_resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "CONDITIONALLY_APPLICABLE"},
        )
        assert internal_resp.status_code == 200, internal_resp.text

        # Тот же spec_version (один и тот же modeling.yaml)
        assert protected_resp.json()["spec_version"] == internal_resp.json()["spec_version"]
        # То же количество кандидатов
        assert (
            protected_resp.json()["statistics"]["total_candidates"]
            == internal_resp.json()["statistics"]["total_candidates"]
        )
        # Тот же набор model_id
        protected_ids = {c["model_id"] for c in protected_resp.json()["candidates"]}
        internal_ids = {c["model_id"] for c in internal_resp.json()["candidates"]}
        assert protected_ids == internal_ids


# ═══════════════════════════════════════════════════════════
# 3. ВАЛИДАЦИЯ ВХОДА
# ═══════════════════════════════════════════════════════════

class TestInternalCandidatesValidation:
    """Зеркало валидирует вход так же, как защищённый эндпоинт."""

    def test_invalid_min_level_returns_422(self):
        """Несуществующий min_level → 422 (как и в защищённом)."""
        resp = client.post(
            "/v1/internal/models/candidates",
            json={"profile": MACRO_PROFILE, "min_level": "INVALID_LEVEL"},
        )
        # 422 от HTTPException(detail="Некорректный min_level: ...")
        assert resp.status_code == 422
        # detail — СТРОКА (не массив!), т.к. это HTTPException, а не Pydantic
        detail = resp.json()["detail"]
        assert isinstance(detail, str), (
            f"detail должен быть str (HTTPException), а не array. "
            f"Получили: {detail!r}"
        )
        assert "min_level" in detail

    def test_missing_profile_returns_422(self):
        """Без profile в теле → 422 (Pydantic validation)."""
        resp = client.post(
            "/v1/internal/models/candidates",
            json={"min_level": "RECOMMENDED"},
        )
        assert resp.status_code == 422
        # Здесь detail — массив (Pydantic validation error)
        # ЭТОТ случай и был причиной бага "[object Object],[object Object]":
        # errBody.detail — массив, который JS приводит к строке через String().
        # UI должен корректно это обрабатывать (см. TsAnalysisModeling.tsx fix).
        detail = resp.json().get("detail")
        assert detail is not None
        # Допустимы оба формата: массив Pydantic-ошибок ИЛИ строка
        assert isinstance(detail, (list, str))
