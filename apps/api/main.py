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
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import public, internal, models

app = FastAPI(
    title="CISStat TS Analysis API",
    version="1.0.0",
    description="API для анализа временных рядов: паспорт свойств, "
                 "валидация, предобработка, признаки.",
)

# ЗАМЕНИТЬ: точные origins для продакшена (домены embedded/standalone фронтендов).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router, prefix="/v1/public", tags=["public"])
app.include_router(internal.router, prefix="/v1/internal", tags=["internal"])
app.include_router(models.router, prefix="/v1/models", tags=["models"])


@app.get("/health")
def health():
    return {"status": "ok"}
