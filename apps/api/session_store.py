# apps/api/session_store.py
"""
Серверное хранилище сессии анализа (AnalysisSession).

Введено по решению тимлида (обсуждение Home page): activeDataset и
прогресс по этапам должны переживать F5, а не жить только в React
Context. Идентификация -- httponly cookie, а не API-ключ, потому что
сессия нужна ОДИНАКОВО embedded- и standalone-фронтенду, включая
неавторизованного посетителя standalone (у него ещё нет API-ключа).

ЗАГЛУШКА ПО ХРАНЕНИЮ: in-memory dict, как и остальные прототипные
хранилища в этом API (_rules_override в public.py/internal.py). Не
переживает рестарт процесса и не работает при нескольких воркерах/
подах -- заменить на Redis+TTL в продакшене (см.
docs/MIGRATION_ARCHITECTURE.md, раздел 8, "Открытые вопросы").

ЗАГЛУШКА ПО COOKIE: SameSite=Lax подходит для localhost (embedded и
standalone на разных портах одного хоста -- same-site). Если в
продакшене embedded/standalone/api окажутся на РАЗНЫХ доменах (не
поддоменах одного site) -- потребуется SameSite=None; Secure=True и
HTTPS везде. Не решать сейчас, пометить при реальном деплое.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import Request, Response

SESSION_COOKIE_NAME = "cisstat_session_id"


def format_size_label(size_bytes: int) -> str:
    """Общий формат для size_label -- KB для маленьких файлов (демо-датасет
    ~3KB показывал бы "0.00 MB" в MB-only формате), MB для остальных."""
    size_mb = size_bytes / (1024 * 1024)
    if size_mb < 0.1:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_mb:.2f} MB"

# Порядок и состав совпадают с ModuleNav (packages/ui/components/ModuleNav.tsx)
# и с "шестью этапами анализа" из docs/MIGRATION_ARCHITECTURE.md §1.1.
# "Задачи" сознательно НЕ включены -- по контракту вкладки «Загрузка»
# (см. комментарий в TsAnalysisUpload.tsx) это отдельная сущность
# (What-if/iDSS), не шаг основного пайплайна.
STAGES = ["upload", "validation", "preprocessing", "eda", "modeling", "forecasting"]

StageStatus = str  # "pending" | "in_progress" | "done"


@dataclass
class DatasetInfo:
    dataset_id: str
    name: str
    rows: int
    columns: int
    size_label: str


@dataclass
class AnalysisSession:
    session_id: str
    dataset: Optional[DatasetInfo] = None
    # Сырой DataFrame НЕ отдаётся клиенту напрямую -- нужен будущим
    # эндпоинтам (quality-teaser в деталях, column-mapping override и
    # т.п.), чтобы читать те же данные, что видел Upload, не запрашивая
    # файл заново у пользователя.
    dataframe: Optional[pd.DataFrame] = None
    stages: dict[str, StageStatus] = field(default_factory=lambda: {s: "pending" for s in STAGES})
    last_active_stage: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def set_dataset(self, dataset: DatasetInfo, dataframe: Optional[pd.DataFrame]) -> None:
        """Новый датасет -- сбрасывает прогресс по этапам (новый анализ)."""
        self.dataset = dataset
        self.dataframe = dataframe
        self.stages = {s: "pending" for s in STAGES}
        self.stages["upload"] = "done"
        self.last_active_stage = "upload"
        self.touch()

    def set_stage(self, stage: str, status: StageStatus) -> None:
        if stage not in self.stages:
            return
        self.stages[stage] = status
        if status in ("in_progress", "done"):
            self.last_active_stage = stage
        self.touch()


class SessionStore:
    """Реестр сессий одного процесса uvicorn. ЗАМЕНИТЬ на Redis при
    переходе на несколько воркеров/подов (см. docstring модуля)."""

    def __init__(self) -> None:
        self._sessions: dict[str, AnalysisSession] = {}

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str) -> AnalysisSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = AnalysisSession(session_id=session_id)
            self._sessions[session_id] = session
        return session


_store = SessionStore()


def get_session_store() -> SessionStore:
    return _store


def get_or_create_session_id(request: Request, response: Response) -> str:
    """
    Читает cookie `cisstat_session_id`; если её нет -- создаёт новую и
    выставляет httponly-cookie в ответ. Используется во ВСЕХ роутерах,
    читающих/пишущих AnalysisSession (session.py, а также upload в
    public.py/internal.py через upload_common.py) -- сессия НЕ
    различается по /v1/public vs /v1/internal, один и тот же
    браузер = одна сессия независимо от того, каким фронтендом
    (embedded/standalone) он сейчас пользуется.

    SameSite/Secure зависят от топологии деплоя: локально фронтенд и
    бэкенд на одном хосте (localhost, разные порты) -- это same-site,
    подходит Lax без Secure (работает по HTTP). В продакшене фронтенд
    (Vercel) и бэкенд (Render/...) -- РАЗНЫЕ домены, это cross-site;
    браузер не отправит Lax-cookie на fetch()-запрос с чужого домена --
    нужны SameSite=None + Secure=True (обязательно вместе, того требует
    спецификация, благо оба сервиса всё равно на HTTPS). Переключатель --
    по наличию ALLOWED_ORIGINS (тот же сигнал "мы в продакшене", что и
    для CORS в main.py, не заводим отдельную переменную).
    """
    is_production = bool(os.environ.get("ALLOWED_ORIGINS"))

    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        session_id = uuid.uuid4().hex
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="none" if is_production else "lax",
            secure=is_production,
            max_age=60 * 60 * 24 * 30,  # 30 дней
        )
    return session_id
