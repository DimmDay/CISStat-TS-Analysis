# Task 19-E-Fix — production Tune → real ETS/ARIMA

## Диагностика локального прогона

Команда пользователя:
`python -m pytest tests/api/test_tune.py tests/api/test_tune_real_models.py tests/api/test_tune_production_dispatch.py -q`

Результат: **69 passed, 5 failed**.

### Production failure
ARIMA падал внутри statsmodels на коротких expanding-CV folds:
`IndexError: too many indices for array: array is 0-dimensional`.

Причина — statsmodels получает неоднозначное представление training endog на
Windows/Python 3.13 в процессе conditional-sum-of-squares initialization.

### Test-only failures
Два `max_trials` теста создавали синтетическую модель `test_model`. До
production dispatch они проходили благодаря STUB `_tunable_predict`; после
удаления STUB такая модель закономерно получает HTTP 422. Это устаревшая
зависимость теста от заглушки, а не production defect.

## Исправления

- `apps/api/model_impls/tuning.py`
  - ARIMA tuning adapter нормализует training input в 1-D `float64` NumPy
    array перед передачей в model implementation.
- `apps/api/model_impls/arima.py`
  - `_arima_fit_predict()` и Auto-ARIMA fit нормализуют endog в 1-D numeric
    NumPy array;
  - добавлена проверка пустого/нечислового ряда;
  - forecast также нормализуется в 1-D numeric array.

## Проверка

Отдельный smoke-test statsmodels 0.14.6 / Python 3.13 с коротким ARIMA
training window после нормализации успешно выполняет fit/forecast.

Полный пользовательский pytest после этих изменений ещё требует запуска в
Windows checkout. Два устаревших `test_model` max_trials теста необходимо
перевести на реальный model-id либо изолировать через test-local predictor;
production STUB возвращать нельзя.

## Статус

Production ARIMA hardening выполнен. Phase 1 production dispatch ещё не
объявляется полностью PASS до повторного полного targeted pytest и исправления
двух тестов, зависящих от удалённого STUB.
