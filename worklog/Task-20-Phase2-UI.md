# Task 20 — Phase 2 residual diagnostics UI

## Scope
Finish the standalone/embedded UI path for Phase 2 without overwriting parallel work in `TsAnalysisModeling.tsx`, `schemas.py`, or `models.py`.

## Design
- Browser calls `/v1/internal/models/diagnostics` with `credentials: include`.
- Raw observations are not sent from the browser.
- Backend resolves the current `AnalysisSession`, selected `target_column`, and DataFrame from the session cookie.
- Backend reuses Phase 2 real-model residual fitting and diagnostic functions from `apps/api/routers/diagnostics.py`.
- UI renders Ljung–Box, Jarque–Bera, ARCH-LM, and Durbin–Watson.
- Conditional tests expose `N/A` and `reason/applicable_if` when not applicable.

## Risk control
`packages/ui/components/TsAnalysisModeling.tsx` was deliberately NOT modified because it is a large shared component and the current `main` does not expose a persisted Tune `best_params` contract in the component. Wiring Diagnostics directly to default model parameters would create a false relationship between Tune and Diagnostics.

The UI was therefore delivered as an isolated reusable `ResidualDiagnosticsPanel`. It can be mounted once the current Tune UI/state is synchronized. This avoids overwriting concurrent work and avoids diagnosing a different model configuration than the tuned one.

## Changed files
- `apps/api/routers/diagnostics_internal.py` — new session-backed internal endpoint.
- `apps/api/main.py` — registers the internal diagnostics router.
- `packages/ui/components/ResidualDiagnosticsPanel.tsx` — new reusable diagnostics panel.
- `packages/ui/components/ResidualDiagnosticsPanel.test.tsx` — UI tests.
- `tests/api/test_diagnostics_internal.py` — session routing tests plus real ETS residual diagnostics.

## Acceptance coverage
- Session target column is required.
- Missing dataset/target is rejected.
- Non-numeric target is rejected.
- Real ETS residuals reach all four diagnostics.
- UI displays test names, status, statistic, p-value, applicability/reason.
- UI sends the session cookie.

## Validation
The branch was created from synchronized `main` and contains only Phase 2 changes. Local pytest/build cannot be executed in this environment; GitHub status for the latest branch commit was not populated at logging time.

## Next step
Mount `ResidualDiagnosticsPanel` from the current `TsAnalysisModeling` after the parallel Tune UI exposes its persisted `best_params`. Pass those exact parameters; do not silently use `{}` for a tuned model.
