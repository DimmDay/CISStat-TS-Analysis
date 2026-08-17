# Task 20 — PHASE 2: Диагностика остатков

## Status
Backend MVP implementation completed on isolated branch; CI/local execution pending.

## Process
- Синхронизирована отдельная ветка от актуального `main`.
- Перед изменениями просмотрены текущие `apps/api/schemas.py`, `apps/api/routers/models.py`, `apps/api/model_impls/ets.py`, `apps/api/model_impls/arima.py`, `apps/api/main.py`.
- `schemas.py` и `models.py` не изменялись: это снижает риск перезаписи параллельной работы команды.
- Создан отдельный diagnostics router и отдельные Pydantic-контракты Phase 2.

## Реализовано
- `POST /v1/models/diagnostics`.
- Реальные residuals получаютcя после fit реальных `statsmodels` ETS/ARIMA.
- Ljung–Box.
- Jarque–Bera.
- ARCH-LM.
- Durbin–Watson.
- `applicable_if` и честный `applicable=false` для недостаточной длины ряда/нулевой дисперсии.
- Alpha configurable, default 0.05.
- Статусы `pass | warning | fail` для UI.
- Авторизация через существующий `can_train_models`.

## Тесты
Создан `tests/api/test_diagnostics.py`:
- ETS residuals из реального statsmodels fit.
- ARIMA residuals из реального statsmodels fit.
- Ljung–Box not applicable при недостаточном числе наблюдений.
- ARCH-LM not applicable при нулевой дисперсии.
- UI status contract.

## Изменённые файлы
- `apps/api/routers/diagnostics.py` — новый.
- `apps/api/main.py` — только импорт diagnostics и регистрация router.
- `tests/api/test_diagnostics.py` — новый.
- `worklog/Task-20-Phase2.md` — текущая запись.

## Риски и ограничения
- `schemas.py` и `routers/models.py` намеренно не затронуты.
- UI Phase 2 пока не реализован.
- Residuals для Phase 2 fit повторяет параметры реальной модели; следующий этап должен унифицировать fit-result/residual contract перед Phase 3, чтобы исключить drift между tuning и diagnostics.
- Полный pytest/build в текущей среде не запускались; перед merge требуется локальный targeted suite и полный CI.
