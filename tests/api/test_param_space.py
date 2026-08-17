"""
Phase 1-A: Тесты для param_space в спецификации моделирования.

Покрывают:
  1. Загрузка YAML с param_space (без ошибок, обратная совместимость)
  2. Pydantic-схема: Optional field, default None
  3. Доступ к param_space по model_id (хелпер)
  4. Несколько моделей Phase 6-P0 имеют непустой param_space (ETS, ARIMA)
  5. Baseline-модели НЕ имеют param_space (контракт: не требуют тюнинга)
  6. Round-trip через model_dump() — сериализация сохраняет param_space
  7. Значения внутри param_space могут быть str/int/bool/None
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.catalog.modeling_spec_loader import (
    ModelingSpec,
    FamilyModel,
)

SPEC_PATH = Path("rules/modeling.yaml")


@pytest.fixture(scope="session")
def spec() -> ModelingSpec:
    return ModelingSpec.from_yaml(str(SPEC_PATH))


# ═══════════════════════════════════════════════════════════
# 1. СХЕМА: ОБРАТНАЯ СОВМЕСТИМОСТЬ
# ═══════════════════════════════════════════════════════════

class TestParamSpaceSchema:
    """Параметр param_space — Optional, по умолчанию None."""

    def test_family_model_has_param_space_field(self):
        """FamilyModel имеет поле param_space."""
        fields = FamilyModel.model_fields
        assert "param_space" in fields, "FamilyModel должен иметь поле param_space"

    def test_param_space_default_is_none(self):
        """Если YAML не содержит param_space — поле = None."""
        m = FamilyModel(
            id="test",
            name="Test",
            description="test",
            min_observations=1,
        )
        assert m.param_space is None

    def test_param_space_accepts_dict_of_lists(self):
        """param_space принимает Dict[str, List[Any]]."""
        m = FamilyModel(
            id="test",
            name="Test",
            description="test",
            min_observations=1,
            param_space={
                "trend": ["add", "mul"],
                "damped": [False, True],
            },
        )
        assert m.param_space == {"trend": ["add", "mul"], "damped": [False, True]}

    def test_param_space_accepts_none_in_list(self):
        """Список значений может содержать None (например, сезонность off)."""
        m = FamilyModel(
            id="test",
            name="Test",
            description="test",
            min_observations=1,
            param_space={"seasonal": ["add", "mul", None]},
        )
        assert None in m.param_space["seasonal"]

    def test_param_space_accepts_mixed_types(self):
        """В одном param_space могут быть int, str, bool, None."""
        m = FamilyModel(
            id="test",
            name="Test",
            description="test",
            min_observations=1,
            param_space={
                "p": [0, 1, 2],            # int
                "trend": ["add", "mul"],    # str
                "damped": [False, True],    # bool
                "seasonal": [None, "add"],  # None + str
            },
        )
        # Pydantic v2 List[Any] принимает любые типы
        assert len(m.param_space) == 4


# ═══════════════════════════════════════════════════════════
# 2. ЗАГРУЗКА ИЗ YAML
# ═══════════════════════════════════════════════════════════

class TestParamSpaceYamlLoading:
    """Спецификация загружается с param_space без ошибок."""

    def test_spec_loads_without_errors(self, spec):
        """Базовая проверка — спецификация парсится."""
        assert spec is not None
        assert spec.metadata.version == "1.0.0-draft"

    def test_ets_has_param_space(self, spec):
        """ETS (Auto) имеет непустой param_space для тюнинга."""
        m = spec.get_model("ets")
        assert m is not None, "Модель 'ets' должна быть в спецификации"
        assert m.param_space is not None, "ETS должен иметь param_space"
        assert len(m.param_space) > 0, "param_space не должен быть пустым dict"

    def test_arima_has_param_space(self, spec):
        """ARIMA имеет непустой param_space для тюнинга (p, d, q)."""
        m = spec.get_model("arima")
        assert m is not None
        assert m.param_space is not None
        # Хотя бы один из ключей — p/d/q
        keys = set(m.param_space.keys())
        assert any(k in keys for k in {"p", "d", "q", "order"}), (
            f"ARIMA param_space должен содержать p/d/q/order, got {keys}"
        )


# ═══════════════════════════════════════════════════════════
# 3. КОНТРАКТ: BASELINE-МОДЕЛИ НЕ ИМЕЮТ PARAM_SPACE
# ═══════════════════════════════════════════════════════════

class TestBaselineNoParamSpace:
    """Baseline-модели (naive, drift, mean) не требуют тюнинга →
    param_space должен быть None у каждой из них."""

    @pytest.mark.parametrize(
        "model_id",
        ["naive", "seasonal_naive", "drift", "mean"],
    )
    def test_baseline_no_param_space(self, spec, model_id):
        m = spec.get_model(model_id)
        assert m is not None, f"Модель {model_id} должна быть в спецификации"
        assert m.param_space is None, (
            f"Baseline {model_id} не должен иметь param_space "
            f"(baseline не требует тюнинга)"
        )


# ═══════════════════════════════════════════════════════════
# 4. ROUND-TRIP СЕРИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════

class TestParamSpaceRoundtrip:
    """model_dump() → Model(**data) сохраняет param_space идентично."""

    def test_roundtrip_preserves_param_space(self, spec):
        """Сериализация спецификации и обратная загрузка сохраняют param_space."""
        ets = spec.get_model("ets")
        if ets.param_space is None:
            pytest.skip("ETS не имеет param_space (требуется заполнить YAML)")

        data = spec.model_dump()
        spec2 = ModelingSpec(**data)
        ets2 = spec2.get_model("ets")
        assert ets2.param_space == ets.param_space, (
            "Round-trip через model_dump должен сохранять param_space"
        )

    def test_json_roundtrip(self, spec):
        """JSON-сериализация (для API-ответов) сохраняет param_space."""
        ets = spec.get_model("ets")
        if ets.param_space is None:
            pytest.skip("ETS не имеет param_space")

        # Pydantic v2: model_dump_json() для вложенных моделей
        json_str = ets.model_dump_json()
        assert "param_space" in json_str, (
            "JSON-сериализация должна включать param_space"
        )
        # Обратная загрузка
        ets2 = FamilyModel.model_validate_json(json_str)
        assert ets2.param_space == ets.param_space
