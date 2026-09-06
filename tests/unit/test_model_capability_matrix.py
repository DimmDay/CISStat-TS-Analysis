from src.catalog.modeling_spec_loader import ModelingSpec

from apps.api.model_readiness import (
    MODELING_CAPABILITY_CONTRACT_VERSION,
    MODELING_STAGE_IDS,
    model_stage_capabilities,
)


def test_capability_contract_covers_every_catalog_model_and_stage() -> None:
    spec = ModelingSpec.from_yaml("rules/modeling.yaml")

    matrix = {
        model.id: model_stage_capabilities(model.id, family.id)
        for family in spec.families
        for model in family.models
    }

    assert MODELING_CAPABILITY_CONTRACT_VERSION == "model-capabilities-v1"
    assert len(matrix) == 24
    assert all(set(stages) == set(MODELING_STAGE_IDS) for stages in matrix.values())
    assert matrix["naive"]["tuning"]["status"] == "not_applicable"
    assert matrix["theta"]["diagnostics"]["status"] == "available"
    assert matrix["ets"]["tuning"]["status"] == "available"
    assert matrix["prophet"]["backtest"]["status"] == "available"
    assert spec.pipeline.version == "1.1"
    assert spec.pipeline.capability_contract["version"] == MODELING_CAPABILITY_CONTRACT_VERSION
    assert spec.pipeline.capability_contract["comparison_scope"] == (
        "all_runnable_minus_acknowledged_exclusions"
    )
