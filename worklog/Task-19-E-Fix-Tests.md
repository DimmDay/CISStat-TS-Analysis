# Task 19-E-Fix — Tune integration test cleanup

## Scope

Replace the two remaining Tune integration tests that still used the removed synthetic `test_model` / `_tunable_predict` STUB path.

## Analysis

`tests/api/test_tune.py` contained two MAX_TRIALS integration tests using a synthetic model id `test_model`. After production dispatch was switched to real ETS/ARIMA implementations, those tests failed with HTTP 422 because `test_model` is intentionally unsupported in production.

The other historical Tune failures were ARIMA/statmodels robustness failures and are not part of this test-fixture cleanup.

## Changes

- Reworked `_make_huge_grid_spec()` to expose a real production model id: `ets`.
- Kept a 128-combination synthetic `param_space` for exercising MAX_TRIALS=64.
- Used only valid ETS parameters for the real predictor; seven ignored test-only grid knobs expand the Cartesian product without changing model semantics.
- Changed both MAX_TRIALS integration tests from `model_id="test_model"` to `model_id="ets"`.
- Reduced these two tests to one CV fold to keep the real-model integration test bounded while preserving the MAX_TRIALS contract.
- Added assertions that returned trials report one CV fold.
- No production code changed.

## Validation plan

- Targeted: `tests/api/test_tune.py`, `tests/api/test_tune_real_models.py`, `tests/api/test_tune_production_dispatch.py`
- Verify no remaining `test_model` dependency in the Tune tests.
- Run API test suite and project build/CI.

## Status

Code changes prepared on `fix/tune-real-model-tests` from current `main`.
Local execution is environment-dependent; CI is the authoritative build/test validation for the branch.
