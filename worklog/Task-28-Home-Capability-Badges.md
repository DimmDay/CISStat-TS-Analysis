# Task 28 — Home capability badges

## Scope

Standalone home page, `HomeCapabilities`: six capability badges/cards under the section headed “Анализ временных рядов — от файла до прогноза”.

## Change

Normal state changed from neutral white to the requested brand-tinted state:

- border: `border-brand/30`
- background: `bg-brand-light/30`

Hover state strengthened:

- border: `hover:border-brand/60`
- background: `hover:bg-brand-light/60`
- icon remains promoted to `bg-brand text-white` on hover.

## Safety

- Only `packages/ui/components/HomeCapabilities.tsx` and its test were changed for the implementation.
- No API, modeling, schema, session, or shared backend files touched.
- Work was started from current `main`; parallel changes were not rebased or overwritten.

## Validation

Added/updated component assertions for all six cards to lock the requested normal and hover class contract.

Local test/build execution was not available in the current environment; CI/local developer run remains required before merge.
