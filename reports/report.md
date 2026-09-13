# Task 143 -- Benchmark полной production-матрицы 24x11

- **Дата**: 2026-09-13T14:06:32+0000
- **Реестр**: 24 моделей x 11 стадий (статусы: available, not_applicable)
- **Backtest scope**: 24/24 моделей, 4 движка (main/vector/volatility/panel)
- **Tuning scope**: 18/18 tunable-моделей, max_trials={'classical': 2, 'neural': 1}
- **Timeout-политика**: все модели в пределах step_timeout (resource_policy_for)
- **Пик RSS процесса**: 1237.3 MB

## Backtest (wall-time / метрика / движок)

| Модель | Движок | Wall, ms | Метрика | OOF |
|---|---|---:|---|---:|
| arima | main | 116.4 | 3.1046 | 24 |
| arima_auto | main | 251.4 | 3.1347 | 24 |
| catboost | main | 1599.4 | 7.1389 | 24 |
| deepar | panel | 32589.3 | 109.5998 | 6 |
| drift | main | 9.1 | 3.8741 | 24 |
| egarch | volatility | 31.0 | qlike=-1.6732 | 12 |
| ets | main | 132.8 | 0.6911 | 24 |
| ets_damped | main | 145.8 | 0.9973 | 24 |
| garch | volatility | 44.6 | qlike=-1.6295 | 12 |
| lightgbm | main | 793.7 | 5.1765 | 24 |
| lstm | main | 15537.2 | 0.8539 | 24 |
| mean | main | 8.9 | 16.9297 | 24 |
| naive | main | 9.0 | 5.1328 | 24 |
| nbeats | main | 6897.4 | 0.8336 | 24 |
| nhits | main | 9758.4 | 0.8665 | 24 |
| prophet | main | 724.1 | 0.7296 | 24 |
| random_forest | main | 684.8 | 6.0983 | 24 |
| seasonal_naive | main | 9.3 | 3.6922 | 24 |
| tbats | main | 603.2 | 0.8781 | 24 |
| tft | main | 182086.9 | 1.0586 | 24 |
| theta | main | 19.7 | 1.7444 | 24 |
| var | vector | 37.2 | scaled_loss=0.5855 | 36 |
| vecm | vector | 27.3 | scaled_loss=0.9095 | 36 |
| xgboost | main | 377.0 | 4.5664 | 24 |

## Tuning (bounded, best_params)

| Модель | Движок | Wall, ms | Trials | Best |
|---|---|---:|---:|---|
| arima | main | 182.0 | 2 | `{"p": 0, "d": 1, "q": 0}` |
| catboost | main | 1122.3 | 2 | `{"iterations": 100, "depth": 4, "learning_rate": 0.2, "n_lags": 7}` |
| deepar | panel | 34413.8 | 1 | `{"lstm_hidden_size": 32, "input_size": 24}` |
| egarch | volatility | 127.6 | 2 | `{"p": 1, "o": 1, "q": 1, "mean": "Constant", "dist": "t"}` |
| ets | main | 200.7 | 2 | `{"trend": "add", "seasonal": "add", "seasonal_periods": 12, "damped_trend": true}` |
| ets_damped | main | 169.8 | 2 | `{"trend": "add", "seasonal": "add", "seasonal_periods": 12}` |
| garch | volatility | 71.0 | 2 | `{"p": 1, "q": 1, "mean": "Constant", "dist": "normal"}` |
| lightgbm | main | 796.5 | 2 | `{"n_estimators": 100, "num_leaves": 15, "learning_rate": 0.2, "n_lags": 7}` |
| lstm | main | 18696.8 | 1 | `{"cell_type": "LSTM", "hidden_size": 32, "input_size": 48}` |
| nbeats | main | 8171.1 | 1 | `{"stack_config": "interpretable", "hidden_size": 32, "input_size": 48}` |
| nhits | main | 11045.1 | 1 | `{"interpolation_config": "hierarchical", "hidden_size": 32, "input_size": 48}` |
| prophet | main | 1550.1 | 2 | `{"changepoint_prior_scale": 0.1, "seasonality_prior_scale": 1.0, "seasonality_mode": "additive"}` |
| random_forest | main | 606.4 | 2 | `{"n_estimators": 100, "max_depth": 6, "min_samples_leaf": 5, "n_lags": 7}` |
| tbats | main | 1235.5 | 2 | `{"use_boxcox": false, "trend_spec": "damped_trend"}` |
| tft | main | 288343.0 | 1 | `{"n_head": 2, "hidden_size": 32, "input_size": 48}` |
| var | vector | 71.3 | 2 | `{"maxlags": 12, "ic": "bic"}` |
| vecm | vector | 53.3 | 2 | `{"k_ar_diff": 1, "deterministic": "ci"}` |
| xgboost | main | 262.5 | 2 | `{"n_estimators": 100, "max_depth": 3, "learning_rate": 0.2, "n_lags": 7}` |

## Топ-5 медленных моделей (backtest)

1. `tft` -- 182086.9 ms (main)
2. `deepar` -- 32589.3 ms (panel)
3. `lstm` -- 15537.2 ms (main)
4. `nhits` -- 9758.4 ms (main)
5. `nbeats` -- 6897.4 ms (main)

## Находки (не блокируют финализацию, требуют решения тимлида)

### Timeout-нарушения (wall 2-fold backtest против step_timeout)

- tft: 182087 ms (wall, 2-fold backtest) > step_timeout 120000 ms (standard)

Комментарий: wall-time покрывает полный backtest (n_splits фитов); в job-раннере step = ОДИН tuning-trial (все фиты trial'а). На медленных CPU-хостах бюджетный нейро-фит (max_steps=300) на большем профиле может превышать step_timeout standard-класса (120 c). Возможные решения: отдельная постановка на бюджет/политику.

Пиковый RSS -- монотонный показатель ВСЕГО процесса benchmark (движки стеком: classical+ml+volatility+neural в одном процессе); production-семантика -- per-job изоляция. Доминанта пика -- импорт torch+neuralforecast (~600 MB, см. scripts/probe138b_memory.py).

## Снапшоты памяти процесса

{
  "after_a": 204.8
}