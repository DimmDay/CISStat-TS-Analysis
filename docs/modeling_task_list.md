Серия задач по подключению всего каталога моделей (24) к модулю "Моделирование".
## Фундамент

### Task 121 — Сертификация девятимодельного baseline

Полный backend/frontend regression на 34332f4.
TypeScript обеих оболочек, production build standalone/embedded.
Проверка exact registry из 9 моделей, capability 24×11 и migration Redis.
PRE-0 smoke Vercel → Render после деплоя тимлидом.
Исправление только обнаруженных регрессий.
Результат: зафиксированный зелёный baseline перед расширением.

### Task 122 — Model Execution Contract v2

Текущий Predictor(y_train, horizon, period, params) подходит только одномерным моделям. Вводим единый registry адаптеров:

objective: level_forecast | multivariate | volatility;
input_kind: univariate | supervised | multivariate | panel;
fit/predict, tuning, diagnostics и resource capabilities;
lazy dependency probe;
версии библиотеки и модели в lineage;
runtime capabilities выводятся из registry, а не из нескольких hardcoded sets;
полная обратная совместимость существующих девяти моделей.

cohort_id расширяется objective, набором рядов/X, feature contract и metric policy. Результаты разных задач нельзя сравнивать в одном ranking.

### Task 123 — Универсальное исполнение долгих model jobs

Обобщаем пошаговый tuning-контур:

job start/status/step/cancel;
idempotency, CAS и возобновление после перезапуска;
тайм-ауты, лимиты памяти/CPU/GPU, deterministic seed;
Redis хранит состояние и ссылки, а не тяжёлые модели;
отдельные dependency-группы classical, ml, volatility, neural;
прогресс в UI по folds/trials/epochs.

Это необходимо уже для TBATS и обязательно для neural. Синхронное обучение neural внутри HTTP-запроса Render недопустимо.

## Классические модели

### Task 124 — Prophet production vertical slice

Адаптер Prophet в точные EDA folds.
Без собственного второго CV-контура.
Fold-local holidays/regressors и строгий future-known contract.
Bounded tuning: changepoint/seasonality prior, seasonality mode.
OOF-lineage, diagnostics, comparison, selection, Model Card.
Точные custom cutoffs и tuning согласуются с официальным подходом Prophet, но исполняются через платформенный BacktestPlan. Prophet diagnostics

### Task 125 — TBATS production vertical slice

Проверка и фиксация конкретной версии/API StatsForecast.
Поддержка нескольких сезонных периодов из спектрального hand-off.
Бюджетированное обучение и tuning без proxy timeout.
Box–Cox только внутри train-fold.
Полная интеграция в 11 остановок.

После серии: 11/24 production-моделей.

## ML

### Task 126 — Leakage-safe supervised FeaturePlan

Fold-local построение лагов, rolling и календарных признаков.
Разделение historic, future-known, static X.
Запрет использования неизвестных будущих регрессоров.
Стратегии multi-step: сначала единый контракт recursive; direct — только при явной поддержке.
Fold-local imputation/scaling/encoding.
Feature fingerprint и feature importance lineage.

Методологическим ориентиром служит контракт lag transformations и exogenous features MLForecast, но фактические folds остаются платформенными. MLForecast lag transformations

### Tasks 127–130 — четыре отдельные vertical slice

#### Task 127 — Random Forest.
#### Task 128 — XGBoost.
#### Task 129 — LightGBM.
#### Task 130 — CatBoost.

Каждая задача включает bounded param_space, exact OOF, feature importance, residual diagnostics, reproducible seed, capability/UI и Model Card. Никаких общих штрафных или Naive-fallback реализаций. Используем нативные production API библиотек: XGBoost, LightGBM.

После серии: 15/24.

## Многомерные модели

### Task 131 — Multivariate Modeling Contract

Явный набор endogenous-рядов вместо одной target.
Общая регулярная временная сетка без скрытой агрегации.
Fold-local стационарность всех компонент и cointegration evidence.
Векторные OOF-точки, метрики по каждому ряду и агрегированная scaled loss.
Многомерный baseline и отдельный comparison cohort.
Диагностика устойчивости и белого шума системы.

### Task 132 — VAR.

### Task 133 — VECM.

Для VECM ранг Йохансена определяется только на train-fold. Для VAR порядок лага также выбирается fold-local. Statsmodels предоставляет отдельный многомерный прогноз и интервалы — это не следует сводить к циклу одномерных ARIMA. Statsmodels VAR forecast intervals

После серии: 17/24.

## Volatility

### Task 134 — Volatility Objective Contract

Явное преобразование цены в returns без скрытого выбора.
Цель — условная дисперсия, а не уровень исходного ряда.
Primary metric: QLIKE; дополнительные ошибки по realized proxy.
Собственный volatility baseline.
Диагностика standardized residuals и squared residuals.
Полностью отдельный cohort: GARCH нельзя ранжировать рядом с ETS/ARIMA.

### Task 135 — GARCH.

### Task 136 — EGARCH.

EGARCH дополнительно проверяет leverage/asymmetry. Прогнозы выполняются через официальный arch-контур. ARCH volatility forecasting

После серии: 19/24.

## Neural

### Task 137 — Neural Runtime Contract

Рекомендую унифицировать пять моделей на NeuralForecast, вместо смеси Darts/GluonTS/PyTorch Forecasting:

единый long-format unique_id / ds / y;
historic/future/static exogenous contract;
CPU/GPU worker capabilities;
checkpoints вне Redis JSON;
early stopping, seed, max epochs/steps;
probabilistic losses и quantiles;
продолжение job после рестарта.

NeuralForecast уже объединяет LSTM, N-BEATS, N-HiTS, TFT и DeepAR и поддерживает exogenous/quantile contracts. NHITS, TFT, DeepAR

### Tasks 138–142 — отдельные vertical slice

#### Task 138 — LSTM/GRU.
#### Task 139 — N-BEATS.
#### Task 140 — N-HiTS.
#### Task 141 — TFT.
#### Task 142 — DeepAR.

DeepAR активируется только для настоящей панели с несколькими рядами; несколько числовых колонок одного объекта не выдаются за панель.

## Финализация

### Task 143 — Полная production-матрица 24×11

24 модели имеют реальные адаптеры и честные capabilities.
Все применимые модели проходят полный execution scope.
Нет catalog_only, фиктивных метрик и fallback-подмен.
Comparison разделён по objective.
Проверены migration старых Redis-сессий и invalidation lineage.
Полные backend/frontend тесты, обе production-сборки.
Performance/timeout/memory benchmark.
PRE-0 smoke Vercel–Render.
Обновление modeling.yaml, документации, worklog2.md и итоговый task-ZIP.