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

RUN touch apps/__init__.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Render/Railway пробрасывают порт через $PORT -- используем его, если
# задан, иначе 8000 (для локального docker run без переменных).
CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
