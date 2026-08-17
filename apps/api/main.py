# apps/api/main.py
"""
FastAPI-бэкенд для CISStat TS Analysis.
"""
import logging
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import public, internal, models, session, diagnostics

app = FastAPI(
    title="CISStat TS Analysis API",
    version="1.0.0",
    description="API для анализа временных рядов: паспорт свойств, валидация, предобработка, признаки.",
)

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
app.include_router(diagnostics.router, prefix="/v1/models", tags=["models"])
app.include_router(session.router, prefix="/v1/session", tags=["session"])


@app.get("/health")
def health():
    return {"status": "ok"}
