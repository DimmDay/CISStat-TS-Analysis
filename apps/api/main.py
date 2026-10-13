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
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from apps.api.session_store import SessionConflictError
# PROGR-3: хук трассы «Прогресса» -- единая точка интеграции §4.2
# (таблица маршрутов путь -> (stage, node_id, event_type) внутри модуля).
from apps.api.trace_hook import TraceHookMiddleware

from apps.api.routers import public, internal, models, session, diagnostics, diagnostics_internal, modeling_session
from apps.api.routers import forecasting_session, tasks_session
# PROGR-4: чтение трассы слоя 1 для панели «Прогресс» (§5 слой 1, §6.1-§6.2).
from apps.api.routers import progress
from apps.api.knowledge import router as knowledge_router_module
# AUDIT-6C (план §18): режимы хранения, in-process worker доставки,
# operational-диагностика /health/ops.
from apps.api.storage_diagnostics import get_storage_mode
from apps.api import delivery_worker


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup/shutdown API (AUDIT-6C):

    - required-режим хранения: фабрики вызываются ДО начала обслуживания
      -- неверная конфигурация/драйвер/миграция/недоступная БД роняют
      старт (fail-closed P21/F14; uvicorn завершается, оркестратор видит
      неработающий контейнер вместо тихой Memory-подмены);
    - in-process worker доставки (остаток AUDIT-6B): авто-старт по env
      (CISSTAT_DELIVERY_WORKER_ENABLED/INTERVAL); shutdown останавливает.
    """
    if get_storage_mode() == "required":
        # Фабрика сама fail-closed в required-режиме (startup readiness-
        # probe). Memory-режим (auto) не трогаем: ленивое создание без
        # side-эффектов -- прежний контракт dev/тестов.
        from apps.api.research_runs import get_research_run_store
        from apps.api.session_store import get_session_store as _get_ss

        get_research_run_store()
        _get_ss()
        logger.info("Startup: required-режим хранения -- фабрики проверены")
    delivery_worker.start_delivery_worker()
    try:
        yield
    finally:
        delivery_worker.stop_delivery_worker()


app = FastAPI(
    title="CISStat TS Analysis API",
    version="1.0.0",
    description="API для анализа временных рядов: паспорт свойств, "
                 "валидация, предобработка, признаки.",
    lifespan=_lifespan,
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

# Хук трассы «Прогресса» (spec_progress.md §4.2, Task PROGR-3): события
# пишутся на успешных ответах по таблице маршрутов apps/api/trace_hook.py.
# Регистрация ДО CORS: последний add_middleware становится внешним, CORS
# должен остаться самым внешним слоем (существующий контракт ответов 4xx).
app.add_middleware(TraceHookMiddleware)

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
app.include_router(diagnostics_internal.router, prefix="/v1/internal", tags=["internal"])
# /v1/session -- НЕ под public/internal: сессия (AnalysisSession) общая
# для embedded и standalone, см. docstring apps/api/routers/session.py.
app.include_router(session.router, prefix="/v1/session", tags=["session"])
app.include_router(modeling_session.router, prefix="/v1/session/modeling", tags=["modeling-session"])
# Прогнозирование -- шестой этап пайплайна (spec_forecasting2.md §6): тот же
# префикс /v1/session/modeling (общая сессия/cookie), отдельный модуль роутера.
app.include_router(forecasting_session.router, prefix="/v1/session/modeling", tags=["forecasting"])
# Задачи (v2, spec_tasks_ia_addendum_v1_1.md §10): вертикальные срезы задач
# поверх артефактов пайплайна. Общая сессия/cookie; отдельный модуль роутера.
app.include_router(tasks_session.router, prefix="/v1/session/tasks", tags=["tasks"])
# PROGR-4: namespace /v1/progress/* -- канон spec_progress.md §5;
# читающий ридер трассы сам не трассируется (вне TRACE_ROUTES).
app.include_router(progress.router, prefix="/v1/progress", tags=["progress"])
# Обучение и база знаний (Шаг 4 EDU, spec_education.md §2.1/§2.2/§7.2):
# эндпоинты ОТКРЫТЫ (образование вне тарифной сетки, пользовательских
# данных нет); контент -- артефакт промоушена apps/api/knowledge/
# registry_data.json (паритет с TS-реестрами застрахован тестами).
app.include_router(knowledge_router_module.router, prefix="/v1/knowledge", tags=["knowledge"])
app.include_router(knowledge_router_module.learning_router, prefix="/v1/learning", tags=["learning"])


@app.exception_handler(SessionConflictError)
async def session_conflict_handler(
    _request: Request, _exc: SessionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": (
                "Состояние анализа изменилось в параллельном запросе; "
                "актуальные результаты сохранены. Повторите операцию."
            ),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ops")
def health_ops():
    """Operational diagnostics (AUDIT-6C, план §18 п.3; контракт
    v1.6-6C §26.3): backend (configured/effective), storage readiness,
    delivery backlog/возраст, projection lag, degraded mode, worker
    доставки, состояние Modeling dispatch.

    Границы контракта: НЕ выдаёт URL БД, tokens и сырые exception
    payload'ы (safe_error); liveness -- отдельный /health (Render
    healthCheckPath): его тело и скорость не зависят от состояния БД.
    Диагностика НЕ инициализирует фабрики (peek-семантика: не
    инициализированное хранилище -- честное not_initialized, а не
    скрытая инициализация фактом запроса health)."""
    from apps.api.research_runs import peek_research_run_store
    from apps.api.session_store import peek_session_store
    from apps.api.storage_diagnostics import build_ops_health

    try:
        from apps.api.routers.models import models_dispatch_state

        models_state = models_dispatch_state()
    except Exception:  # pragma: no cover - диагностика не роняет health
        models_state = {"ready": False, "missing": ["<state unavailable>"]}

    snapshot = build_ops_health(
        run_store=peek_research_run_store(),
        session_store=peek_session_store(),
        worker_status=delivery_worker.delivery_worker_status(),
        models_dispatch=models_state,
    )
    return JSONResponse(status_code=200, content=snapshot)
