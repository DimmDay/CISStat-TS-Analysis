# apps/api/main.py
"""
FastAPI-бэкенд для CISStat TS Analysis.

ВАЖНО: этот сервис оборачивает уже протестированную бизнес-логику из
основного репозитория CISStat-TS-Analysis (app/core/*, app/validation/*,
app/data/*, app/features/*, app/preprocessing/*). Разместите эту папку
так, чтобы указанные модули были импортируемы -- проще всего положить
apps/api рядом с app.py в том же репозитории, а не в изолированный
монорепозиторий фронтендов.

Два семейства роутов:
- /v1/public/*   -- для внешних покупателей, авторизация по API-ключу
- /v1/internal/* -- для embedded-режима (доверяет сессии портала)
- /v1/models/*   -- ПРИМЕР эндпоинта, защищённого по ВОЗМОЖНОСТИ
                     (require_capability("can_train_models")), см. plans.py

Запуск (для разработки): uvicorn main:app --reload --port 8000
"""
import logging
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import public, internal, models, session

app = FastAPI(
    title="CISStat TS Analysis API",
    version="1.0.0",
    description="API для анализа временных рядов: паспорт свойств, "
                 "валидация, предобработка, признаки.",
)

# CORS origins -- через переменную окружения ALLOWED_ORIGINS (список через
# запятую), задаётся на хостинге бэкенда (Render/Railway/...). Localhost
# для локальной разработки добавлен всегда, чтобы не сломать её при
# отсутствии переменной. allow_origin_regex дополнительно разрешает ЛЮБОЙ
# *.vercel.app -- иначе каждый preview-деплой (PR/ветка) получает новый
# поддомен и ловит CORS-ошибку, пока вручную не пропишешь его в
# ALLOWED_ORIGINS.
_env_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_default_dev_origins = ["http://localhost:3000", "http://localhost:3001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_dev_origins + _env_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router, prefix="/v1/public", tags=["public"])
app.include_router(internal.router, prefix="/v1/internal", tags=["internal"])
app.include_router(models.router, prefix="/v1/models", tags=["models"])
# /v1/session -- НЕ под public/internal: сессия (AnalysisSession) общая
# для embedded и standalone, см. docstring apps/api/routers/session.py.
app.include_router(session.router, prefix="/v1/session", tags=["session"])


@app.get("/health")
def health():
    return {"status": "ok"}
