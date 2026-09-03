from apps.api.modeling_workflow import (
    MODELING_STAGE_IDS,
    TRACEABILITY_CATALOG,
    build_traceability_summary,
)


def test_traceability_catalog_covers_every_upstream_stop_exactly_once():
    grouped = {
        group: [item for item in TRACEABILITY_CATALOG if item["group"] == group]
        for group in ("validation", "preprocessing", "eda")
    }

    assert {group: len(items) for group, items in grouped.items()} == {
        "validation": 10,
        "preprocessing": 10,
        "eda": 10,
    }
    assert len({(item["group"], item["source_id"]) for item in TRACEABILITY_CATALOG}) == 30
    assert all(item["modeling_inputs"] for item in TRACEABILITY_CATALOG)


def test_modeling_pipeline_uses_canonical_eleven_stage_spec_ids():
    assert MODELING_STAGE_IDS == (
        "problem_definition",
        "data_structure",
        "constraint_mapping",
        "candidate_generation",
        "baseline_estimation",
        "backtest",
        "tuning",
        "diagnostics",
        "comparison",
        "selection",
        "model_card",
    )


def test_traceability_summary_does_not_treat_skipped_optional_steps_as_failures():
    nodes = [
        {"status": "done"},
        {"status": "warning"},
        {"status": "skipped"},
        {"status": "pending"},
    ]

    assert build_traceability_summary(nodes) == {
        "total": 4,
        "done": 1,
        "warning": 1,
        "skipped": 1,
        "pending": 1,
        "blocking": 0,
    }
