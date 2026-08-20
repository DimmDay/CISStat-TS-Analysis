# Task 20 — Phase 2: Residual Diagnostics UI connection

## Scope

Connect `ResidualDiagnosticsPanel` to the current Modeling Stepper without overwriting the team's shared modeling implementation.

## Repository review

Reviewed current `main`:

- `packages/ui/components/TsAnalysisModeling.tsx` is the shared Modeling Stepper used by standalone and embedded applications.
- `apps/standalone/app/modeling/page.tsx` only mounts `TsAnalysisModeling`.
- `apps/api/routers/diagnostics_internal.py` and `apps/api/main.py` are already present and expose the session-backed diagnostics endpoint.
- The current stepper has no persisted `best_params` from Tune yet.

## Risk assessment

The primary risk is overwriting a large shared `TsAnalysisModeling.tsx` while parallel development is active. The connector available for this task can update complete files but cannot apply a line-level patch to an existing large file. To avoid destroying parallel work, `TsAnalysisModeling.tsx` was intentionally **not overwritten**.

A minimal patch was prepared separately:

`TsAnalysisModeling.phase2.patch`

It adds:

1. `ResidualDiagnosticsPanel` import.
2. Diagnostics-stage model selection.
3. Rendering only for ETS / ETS Damped / ARIMA after successful backtest.
4. Automatic diagnostics execution when the Diagnostics stage is selected.
5. Completion callback marking the diagnostics stage done.
6. Explicit UI messages for missing backtest and unsupported models.

## Implemented safely in branch

- `packages/ui/components/ResidualDiagnosticsPanel.tsx`
  - added `onComplete` callback;
  - preserves existing API/session behavior;
  - reports successful diagnostics to the parent stepper.
- `packages/ui/components/ResidualDiagnosticsPanel.test.tsx`
  - verifies automatic execution;
  - verifies completion callback;
  - verifies conditional-test `N/A` rendering.

## Not changed

- `apps/api/routers/models.py`
- `apps/api/routers/diagnostics.py`
- `apps/api/routers/diagnostics_internal.py`
- `apps/api/main.py`
- `packages/ui/lib/modeling.ts`
- `schemas.py`

## Validation

The shared `TsAnalysisModeling.tsx` integration cannot be safely committed through the current GitHub connector without replacing the complete parallel-edited file. Therefore the actual parent-component integration is pending application of the prepared patch on a fresh local clone / team branch.

No test/build PASS is claimed from this environment.

## Exit criterion

Phase 2 becomes end-to-end complete after the patch is applied and the following flow passes:

`Backtest → select Diagnostics → ResidualDiagnosticsPanel → POST /v1/internal/models/diagnostics → four tests → diagnostics stage DONE`.

The future Tune integration must pass `best_params` into the same panel instead of `{}`.
