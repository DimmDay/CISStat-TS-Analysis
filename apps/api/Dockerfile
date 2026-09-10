# apps/api/Dockerfile
#
# Деплой FastAPI-бэкенда CISStat TS Analysis (apps/api). НЕ путать с
# Dockerfile в корне репозитория -- тот для старого Streamlit-приложения
# (app.py), это два разных деплоя.
#
# ВАЖНО: контекст сборки должен быть КОРЕНЬ репозитория, НЕ apps/api.
# Причина: apps/api/main.py и его роутеры импортируют top-level пакеты
# `app.core.passport`, `validation.engine`, `src.catalog.
# modeling_spec_loader` -- они лежат РЯДОМ с apps/, не внутри неё (см.
# docstring в apps/api/main.py). Если собирать из apps/api как
# контекста, эти пакеты просто не попадут в образ (COPY не дотянется
# выше контекста).
#
# Настройка на Render/Railway (оба поддерживают раздельно root+путь к Dockerfile):
#   Root Directory:   .                    (корень репозитория)
#   Dockerfile Path:  apps/api/Dockerfile
# См. render.yaml в корне репозитория -- там это уже прописано.

FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для сборки некоторых wheel'ов (scipy/statsmodels
# на редких платформах требуют компилятор, если бинарного wheel нет).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt ./apps/api/requirements.txt
# Флаг --no-cache-dir + явная проверка импорта критичных зависимостей.
# Если pip не установит redis (например, из-за кэша слоя), сборка упадёт
# здесь с явной ошибкой, а не в runtime через fallback на Memory.
RUN pip install --no-cache-dir -r apps/api/requirements.txt \
    && python -c "import redis; print('redis OK:', redis.__version__)" \
    && python -c "import fastapi, pandas, pydantic; print('core deps OK')"

# Копируем ТОЛЬКО то, что реально импортируется бэкендом (проверено
# статическим AST-разбором, см. apps/api/requirements.txt) -- не весь
# репозиторий (там ещё Streamlit-приложение app.py, два Next.js-
# фронтенда и т.д., бэкенду это не нужно, и раздувает образ).
COPY app/ ./app/
COPY validation/ ./validation/
COPY src/ ./src/
COPY apps/api/ ./apps/api/
# rules/ -- каталог YAML-спецификаций: modeling.yaml (для /candidates),
# default_rules.yaml, fao_prices.yaml, macro.yaml (для /rules/load/*).
# БЕЗ этого слоя бэкенд в проде возвращает 500 «Спецификация
# моделирования не найдена: rules/modeling.yaml» при первом вызове
# /v1/internal/models/candidates (после upload'а датасета).
COPY rules/ ./rules/

RUN touch apps/__init__.py

# Защита от регрессии: если на этапе сборки catalog/spec-файлы
# отсутствуют или битые -- образ не должен собраться (раньше баг
# всплывал только в runtime через 500-ю ошибку). Проверяем, что
# ModelingSpec.from_yaml() парсится без исключений.
#
# Phase 6-P0: добавлена проверка импортов model_impls (ETS/Theta/ARIMA).
# Tasks 124/125: Prophet и StatsForecast TBATS также проверяются на этапе
# сборки. Иначе lazy dependency probe молча уменьшит production registry,
# и модель исчезнет из фильтра доступных только после запуска контейнера.
RUN python -c "from src.catalog.modeling_spec_loader import ModelingSpec; \
               spec = ModelingSpec.from_yaml('rules/modeling.yaml'); \
               print('modeling.yaml OK, models:', spec.total_model_count())" \
    && python -c "import statsmodels; from statsmodels.tsa.holtwinters import ExponentialSmoothing; \
                  from statsmodels.tsa.arima.model import ARIMA; \
                  from statsmodels.tsa.forecasting.theta import ThetaModel; \
                  print('statsmodels OK:', statsmodels.__version__)" \
    && python -c "from apps.api.model_impls import run_ets_backtest, run_ets_damped_backtest, \
                  run_theta_backtest, run_arima_backtest, run_auto_arima_backtest; \
                  print('model_impls OK: 5 implementations importable')" \
    && python -c "import pandas as pd; from apps.api.model_impls.prophet import _prophet_fit_predict; \
                  dates = [value.isoformat() for value in pd.date_range('2020-01-01', periods=14, freq='MS')]; \
                  forecast, _, _ = _prophet_fit_predict([float(value) for value in range(1, 13)], 2, dates[:12], dates[12:]); \
                  assert len(forecast) == 2; print('Prophet executable OK')" \
    && python -c "from apps.api.model_impls.tbats import _tbats_fit_predict; \
                  forecast, _, _ = _tbats_fit_predict([float(value) for value in range(1, 13)], 2, 4, use_boxcox=False); \
                  assert len(forecast) == 2; print('StatsForecast TBATS executable OK')" \
    && python -c "from apps.api.model_impls.random_forest import _rf_fit_predict; \
                  payload = _rf_fit_predict([float(value) for value in range(1, 21)], 2, params={'n_estimators': 20, 'n_lags': 2}, random_state=42); \
                  assert len(payload['forecast']) == 2; print('Random Forest executable OK')" \
    && python -c "from apps.api.model_impls.xgboost import _xgb_fit_predict; \
                  payload = _xgb_fit_predict([float(value) for value in range(1, 21)], 2, params={'n_estimators': 15, 'n_lags': 2}, random_state=42); \
                  assert len(payload['forecast']) == 2; print('XGBoost executable OK')" \
    && python -c "from apps.api.model_impls.lightgbm import _lgb_fit_predict; \
                  payload = _lgb_fit_predict([float(value) for value in range(1, 21)], 2, params={'n_estimators': 15, 'n_lags': 2}, random_state=42); \
                  assert len(payload['forecast']) == 2; print('LightGBM executable OK')" \
    && python -c "from apps.api.model_impls.catboost import _cb_fit_predict; \
                  payload = _cb_fit_predict([float(value) for value in range(1, 21)], 2, params={'iterations': 15, 'n_lags': 2}, random_state=42); \
                  assert len(payload['forecast']) == 2; print('CatBoost executable OK')" \
    && python -c "from apps.api.model_impls.var import _var_fit_predict; \
                  payload = _var_fit_predict([float(value) for value in range(1, 31)], 2, related_series={'related': [float(value) ** 2 for value in range(1, 31)]}, params={'maxlags': 2, 'ic': None}); \
                  assert payload['forecast'].shape == (2, 2); print('VAR executable OK')" \
    && python -c "import math; from apps.api.model_impls.vecm import _vecm_fit_predict; \
                  value = [float(value) + math.sin(value) for value in range(1, 41)]; \
                  payload = _vecm_fit_predict(value, 2, related_series={'related': value[:-1] + [value[-1]]}, params={'coint_rank': 1, 'k_ar_diff': 1}); \
                  assert payload['forecast'].shape == (2, 2); print('VECM executable OK')" \
    && python -c "import numpy as np; from apps.api.model_impls.garch import _garch_fit_predict; \
                  rng = np.random.default_rng(7); omega, alpha, beta = 1e-6, 0.1, 0.85; \
                  s2 = omega / (1 - alpha - beta); returns = []; \
                  exec('for _ in range(150):\n    eps = rng.standard_normal() * np.sqrt(s2)\n    returns.append(float(eps))\n    s2 = omega + alpha * eps**2 + beta * s2'); \
                  payload = _garch_fit_predict(returns, 2, random_state=42); \
                  assert payload['variance_forecast'].shape == (2,) and (payload['variance_forecast'] > 0).all(); \
                  print('GARCH executable OK')"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Render/Railway пробрасывают порт через $PORT -- используем его, если
# задан, иначе 8000 (для локального docker run без переменных).
CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
