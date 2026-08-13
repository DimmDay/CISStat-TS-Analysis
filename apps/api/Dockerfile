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
# Если statsmodels не установится в образ -- сборка упадёт здесь, а не в
# runtime при первом вызове /v1/internal/models/backtest с model_id=ets.
RUN python -c "from src.catalog.modeling_spec_loader import ModelingSpec; \
               spec = ModelingSpec.from_yaml('rules/modeling.yaml'); \
               print('modeling.yaml OK, models:', spec.total_model_count())" \
    && python -c "import statsmodels; from statsmodels.tsa.holtwinters import ExponentialSmoothing; \
                  from statsmodels.tsa.arima.model import ARIMA; \
                  from statsmodels.tsa.forecasting.theta import ThetaModel; \
                  print('statsmodels OK:', statsmodels.__version__)" \
    && python -c "from apps.api.model_impls import run_ets_backtest, run_ets_damped_backtest, \
                  run_theta_backtest, run_arima_backtest, run_auto_arima_backtest; \
                  print('model_impls OK: 5 implementations importable')"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Render/Railway пробрасывают порт через $PORT -- используем его, если
# задан, иначе 8000 (для локального docker run без переменных).
CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
