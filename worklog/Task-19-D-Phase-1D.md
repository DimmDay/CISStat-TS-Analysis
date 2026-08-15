# Task ID: 19-D — Phase 1-D: интеграционные тесты тюнинга на реальных ETS / ARIMA

## Цель

Закрыть последний пункт Phase 1-D: baseline skip / ETS grid / CV splits поверх реальных Phase 6-P0 реализаций, а не legacy `_tunable_predict` STUB.

## Состояние на старте

- Phase 1-A: `param_space` в `rules/modeling.yaml` — завершена.
- Phase 1-B: `ExpandingWindowCV` — завершена.
- Phase 1-C: `POST /v1/models/tune`, grid × CV и `max_trials` — завершена.
- Phase 6-P0: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA для backtest — завершена.
- `_tunable_predict` в `apps/api/routers/models.py` остаётся legacy STUB для tuning. Это отдельная production-задача и не должен маскироваться тестовым monkeypatch.

## Что проверено

Добавлен `tests/api/test_tune_real_models.py`.

Покрытие:

1. Baseline skip: `naive`, `seasonal_naive`, `drift`, `mean` → HTTP 422.
2. ETS grid: 12 комбинаций из `rules/modeling.yaml` выполняются через реальный `statsmodels.ExponentialSmoothing`.
3. ARIMA grid: 18 комбинаций выполняются через реальный `statsmodels.ARIMA`.
4. Все trial metrics finite и неотрицательные.
5. Параметры действительно влияют на RMSE: grid не является декоративным.
6. Реальные прогнозы отличаются от legacy STUB.
7. Expanding-window CV: 5 folds, train расширяется, future leakage отсутствует.
8. `TuneResponse.n_folds` соответствует фактической CV-конфигурации.
9. `max_trials=2` сокращает ETS grid 12 → 2 с `truncated=True`.

## Точки изменения

- `tests/api/test_tune_real_models.py` — единственный production-safe тестовый файл для Phase 1-D.
- Production `_tunable_predict` не изменялся в рамках этого Task 19-D, чтобы не смешивать integration-test coverage с отдельным рефакторингом model dispatch.

## Риски

- Тест не должен проходить за счёт STUB → реальные statsmodels helpers вызываются напрямую.
- Baseline не должен случайно попасть в tuning → отдельные 422 assertions.
- CV leakage → проверка `max(train_idx) < min(test_idx)`.
- Потеря grid combinations → проверка размеров 12/18.
- Неконтролируемое выполнение большого grid → проверка `max_trials`.
- Multiplicative ETS на неположительном ряде требует отдельной обработки/валидации; текущий golden test использует строго положительный ряд.

## Верификация

Полный pytest/build из этой runtime-среды не заявляется: прямой `git clone` недоступен из-за DNS/network restriction. Репозиторий и актуальный `main` синхронизированы через GitHub connector.

## Результат

Phase 1-D integration-test coverage подготовлена и уже присутствует в `main` как `tests/api/test_tune_real_models.py`.

Важно: этот Task не объявляет production `_tunable_predict` заменённым. Если требуется перевод самого `POST /v1/models/tune` на production model dispatch, это отдельное изменение `apps/api/routers/models.py` + model implementation API и должно пройти отдельный полный regression run.
