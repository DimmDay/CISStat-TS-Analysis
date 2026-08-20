# Task 29 — Home route badges visual state

## Scope

Correct the six navigation badges in `HomeHero` (top section of the standalone home page), not the lower `HomeCapabilities` section.

## Target badges

- Знакомство с платформой
- Обучение и база знаний
- Отраслевые исследования
- Доступ и тарифы
- Документация API
- Приступить к анализу данных

## Visual contract

Normal:
- `border-brand/30`
- `bg-brand-light/30`

Hover:
- `hover:border-brand/60`
- `hover:bg-brand-light/60`
- icon uses filled brand background with white icon

## Changed files

- `packages/ui/components/HomeHero.tsx`
- `packages/ui/components/HomeHero.test.tsx`
- this worklog

## Safety

No `HomeCapabilities` files were changed for this task.

## Validation

Focused test assertions were added for all six route cards. Local test/build execution is not available in the current tool runtime; CI/local developer run remains required.
