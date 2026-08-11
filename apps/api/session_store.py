# apps/api/session_store.py
"""
Серверное хранилище сессии анализа (AnalysisSession).

Введено по решению тимлида (обсуждение Home page): activeDataset и
прогресс по этапам должны переживать F5, а не жить только в React
Context. Идентификация -- httponly cookie, а не API-ключ, потому что
сессия нужна ОДИНАКОВО embedded- и standalone-фронтенду, включая
неавторизованного посетителя standalone (у него ещё нет API-ключа).

КОНТРАКТ ХРАНИЛИЩА (Phase 0, см. worklog Task ID 10):
  SessionStore ABC с 4 методами:
    - get(session_id) -> Optional[AnalysisSession]
    - get_or_create(session_id) -> AnalysisSession
    - save(session) -> None              # persist after mutation
    - delete(session_id) -> bool

  Две реализации:
    - MemorySessionStore (default в dev/tests): in-memory dict, как было
    - RedisSessionStore (production MVP): Upstash Redis free tier

  ВЫБОР ПО ENV:
    - REDIS_URL задан → RedisSessionStore.from_env()
    - иначе → MemorySessionStore()

КОНТРАКТ ПО AЛИАСИНГУ (КРИТИЧНО):
  Memory хранит ссылки -- мутации (set_dataset, set_stage) ВИДНЫ сразу.
  Redis так не может -- сериализует при save(). Чтобы обе реализации
  вели себя одинаково, контракт требует ЯВНЫЙ save() после мутации.
  Все call sites, мутирующие AnalysisSession, ДОЛЖНЫ вызывать save().

ЗАГЛУШКА ПО COOKIE: SameSite=Lax подходит для localhost. В продакшене
(embedded/standalone/api на РАЗНЫХ доменах) -- SameSite=None; Secure=True.
Переключатель -- ALLOWED_ORIGINS (тот же сигнал "мы в продакшене", что и
для CORS в main.py).

TTL: 30 дней (= max_age cookie). Сессия, протухшая в Redis, при следующем
запросе создаётся заново -- это нормально, пользователь просто потеряет
прогресс (как и при очистке cookies в браузере).

ОГРАНИЧЕНИЕ Upstash FREE TIER: 10MB на команду. JSON-сериализация
DataFrame ~10K строк занимает ~1-2MB (проверено тестом
test_large_dataframe_roundtrip). Для бОльших датасетов -- post-MVP:
parquet/S3 + ссылка в сессии.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from fastapi import Request, Response

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "cisstat_session_id"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 дней -- совпадает с cookie max_age


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
#
# Phase 5/6 добавит 11-стадийный modeling sub-pipeline (candidate_pool →
# backtest → tune → ... → model_card). Тот sub-pipeline будет жить в
# session.stages по тем же ключам ("modeling.candidate_pool" и т.д.) или
# в отдельном поле session.modeling_state -- дизайн зафиксируется в
# Phase 6-P0. На уровне SessionStore достаточно, что stages -- это
# dict[str, str] и любая структура ключей сохранится.
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
    """Состояние одной сессии анализа.

    ВАЖНО: мутации (set_dataset, set_stage) НЕ персистятся автоматически.
    После любой мутации вызывающий код ДОЛЖЕН вызвать store.save(session),
    иначе изменения потеряются при следующем get() в Redis-режиме. В
    Memory-режиме save() -- no-op по сути (алиасинг), но ВЫЗЫВАТЬ ВСЁ
    РАВНО НАДО -- иначе код несовместим с Redis.
    """
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


# ────────────────────────────────────────────────────────────────────
# Serialization helpers (shared by Memory → JSON → Redis path)
# ────────────────────────────────────────────────────────────────────

def _dataset_to_dict(ds: DatasetInfo) -> dict[str, Any]:
    return asdict(ds)


def _dataset_from_dict(d: dict[str, Any]) -> DatasetInfo:
    return DatasetInfo(**d)


def _dataframe_to_json(df: pd.DataFrame) -> str:
    """Сериализация DataFrame в JSON-строку.

    orient='split' -- самый компактный формат, сохраняет dtypes (через
    индексы и имена колонок). date_format='iso' -- datetime колонки
    уходят как ISO-8601 строки, при чтении конвертируются обратно.

    ОГРАНИЧЕНИЯ (не блокируют MVP):
      - tz-aware datetimes: теряют tz при roundtrip (приходят как naive
        UTC). На практике в наших датасетах tz-aware нет (CSV-парсинг
        даёт naive).
      - period dtype: приходит как str. Если встретится -- конвертировать
        на месте при чтении.
      - non-serializable значения (object-dtype с произвольными Python
        объектами): default=str fallback в json.dumps.
    """
    return df.to_json(orient="split", date_format="iso", default_handler=str)


def _dataframe_from_json(s: str) -> pd.DataFrame:
    """Десериализация DataFrame из JSON-строки."""
    df = pd.read_json(io_string(s), orient="split", convert_dates=True)
    return df


def io_string(s: str):
    """Wrapper to avoid top-level `from io import StringIO` (keeps imports tight)."""
    from io import StringIO
    return StringIO(s)


def session_to_dict(session: AnalysisSession) -> dict[str, Any]:
    """Полная сериализация AnalysisSession в dict (JSON-совместимый).

    Используется RedisSessionStore, но также доступен как утилита для
    отладки/логирования. MemorySessionStore не вызывает (хранит ссылку).
    """
    return {
        "session_id": session.session_id,
        "dataset": _dataset_to_dict(session.dataset) if session.dataset else None,
        "dataframe_json": _dataframe_to_json(session.dataframe) if session.dataframe is not None else None,
        "stages": dict(session.stages),
        "last_active_stage": session.last_active_stage,
        "updated_at": session.updated_at,
    }


def session_from_dict(d: dict[str, Any]) -> AnalysisSession:
    """Десериализация AnalysisSession из dict."""
    dataset = _dataset_from_dict(d["dataset"]) if d.get("dataset") else None
    df = _dataframe_from_json(d["dataframe_json"]) if d.get("dataframe_json") is not None else None
    return AnalysisSession(
        session_id=d["session_id"],
        dataset=dataset,
        dataframe=df,
        stages=dict(d.get("stages", {})),
        last_active_stage=d.get("last_active_stage"),
        updated_at=d.get("updated_at", datetime.now(timezone.utc).isoformat()),
    )


# ────────────────────────────────────────────────────────────────────
# SessionStore ABC
# ────────────────────────────────────────────────────────────────────


class SessionStore(ABC):
    """Абстракция хранилища сессий.

    Все 4 метода должны быть реализованы любым бэкендом. Контракт
    гарантирует, что MemorySessionStore и RedisSessionStore ведут себя
    одинаково с точки зрения вызывающего кода.

    Сохранение изменений: после мутации AnalysisSession (set_dataset /
    set_stage) вызывающий код ОБЯЗАН вызвать save(session). Без save()
    изменения НЕ персистятся (в Redis -- точно; в Memory -- видны по
    ссылке, но контракт требует save() везде).
    """

    @abstractmethod
    def get(self, session_id: str) -> Optional[AnalysisSession]:
        """Вернуть сессию по id или None если не найдена."""
        ...

    @abstractmethod
    def get_or_create(self, session_id: str) -> AnalysisSession:
        """Вернуть существующую сессию или создать новую (пустую)."""
        ...

    @abstractmethod
    def save(self, session: AnalysisSession) -> None:
        """Персистировать сессию (overwrite по session_id).

        ДОЛЖЕН вызываться после любой мутации AnalysisSession. Без
        save() изменения потеряются в Redis-режиме.
        """
        ...

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Удалить сессию. Вернуть True если существовала, False иначе."""
        ...


# ────────────────────────────────────────────────────────────────────
# MemorySessionStore
# ────────────────────────────────────────────────────────────────────


class MemorySessionStore(SessionStore):
    """In-memory dict хранилище -- default в dev и тестах.

    Не переживает рестарт процесса, не работает при нескольких воркерах.
    В production -- RedisSessionStore (см. get_session_store()).
    """

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

    def save(self, session: AnalysisSession) -> None:
        # В memory ссылка уже в _sessions (если был get_or_create) --
        # мутации видны сразу. save() -- для контракта, не делает
        # ничего дополнительно. НО: если session создан вне get_or_create
        # (маловероно, но возможно в тестах), регистрируем его.
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


# ────────────────────────────────────────────────────────────────────
# RedisSessionStore
# ────────────────────────────────────────────────────────────────────


class RedisSessionStore(SessionStore):
    """Redis-backed SessionStore для production MVP.

    Используется при REDIS_URL env (см. get_session_store()). Сохраняет
    сессии между рестартами процесса и позволяет масштабировать на
    несколько воркеров/подов.

    КЛЮЧИ:
      cisstat:session:{session_id} → JSON-строка (см. session_to_dict)
      TTL: SESSION_TTL_SECONDS (30 дней) -- обновляется при каждом save()

    ЗАВИСИМОСТИ: redis>=5.0 (sync клиент, так как FastAPI-роутеры sync).
    Для Upstash: REDIS_URL=rediss://default:password@host:port
    (двойная 's' в rediss:// -- TLS, обязательно для Upstash).

    СЕРИАЛИЗАЦИЯ: DataFrame → JSON (orient='split'). См.
    _dataframe_to_json для ограничений (tz-aware, period dtype).
    """

    KEY_PREFIX = "cisstat:session:"

    def __init__(self, client: Any, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        """
        Args:
            client: redis.Redis ИЛИ fakeredis.FakeStrictRedis (для тестов).
            ttl_seconds: TTL на ключ сессии. Обновляется при каждом save().
        """
        self._client = client
        self._ttl = ttl_seconds

    @staticmethod
    def from_env() -> "RedisSessionStore":
        """Создаёт RedisSessionStore из REDIS_URL env.

        REDIS_URL поддерживает оба варианта:
          - redis://[:password@]host:port/db  -- без TLS
          - rediss://[:password@]host:port/db -- с TLS (Upstash)

        Поднимает RuntimeError если REDIS_URL не задан.
        """
        import redis  # late import -- не падает если redis не установлен и не нужен

        url = os.environ.get("REDIS_URL")
        if not url:
            raise RuntimeError(
                "REDIS_URL env var is required for RedisSessionStore. "
                "Set it to your Redis/Upstash connection string."
            )
        client = redis.Redis.from_url(url, decode_responses=True)
        return RedisSessionStore(client=client)

    def _key(self, session_id: str) -> str:
        return f"{self.KEY_PREFIX}{session_id}"

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        raw = self._client.get(self._key(session_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return session_from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to deserialize session %s: %s", session_id, e)
            return None

    def get_or_create(self, session_id: str) -> AnalysisSession:
        session = self.get(session_id)
        if session is None:
            session = AnalysisSession(session_id=session_id)
            # НЕ сохраняем сразу -- пустая сессия пишется только при первом
            # save(), чтобы не плодить пустые ключи (для Upstash free tier
            # экономия на количестве команд важна).
        return session

    def save(self, session: AnalysisSession) -> None:
        session.touch()
        data = session_to_dict(session)
        payload = json.dumps(data, default=str)
        key = self._key(session.session_id)
        # setex = SET + EX (expire) в одной атомарной команде
        self._client.setex(key, self._ttl, payload)

    def delete(self, session_id: str) -> bool:
        key = self._key(session_id)
        # Redis DEL возвращает количество удалённых ключей
        result = self._client.delete(key)
        return bool(result)


# ────────────────────────────────────────────────────────────────────
# Factory + singleton
# ────────────────────────────────────────────────────────────────────

_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Возвращает singleton SessionStore.

    ВЫБОР БЭКЕНДА:
      - Если задан REDIS_URL или CISSTAT_SESSION_BACKEND=redis → RedisSessionStore
      - Иначе → MemorySessionStore (default для dev и тестов)

    Один раз созданный экземпляр переиспользуется во всех последующих
    вызовах (для Redis -- чтобы не открывать пул коннектов на каждый
    запрос). Тесты могут сбросить singleton через reset_session_store_for_testing().
    """
    global _store
    if _store is not None:
        return _store

    backend_explicit = os.environ.get("CISSTAT_SESSION_BACKEND", "").lower()
    redis_url = os.environ.get("REDIS_URL", "")

    if redis_url or backend_explicit == "redis":
        try:
            _store = RedisSessionStore.from_env()
            logger.info("SessionStore: RedisSessionStore initialized (REDIS_URL set)")
        except Exception as e:
            # Fallback на Memory если Redis недоступен на старте --
            # лучше работать в degraded-режиме, чем упасть целиком.
            # Логируем, чтобы было видно в мониторинге.
            logger.error("SessionStore: Redis init failed (%s), falling back to Memory", e)
            _store = MemorySessionStore()
    else:
        _store = MemorySessionStore()

    return _store


def reset_session_store_for_testing() -> None:
    """Сбросить singleton. ТОЛЬКО для тестов.

    Используется в tests/api/test_session_store.py для изоляции тестов
    фабрики от глобального состояния.
    """
    global _store
    _store = None


# ────────────────────────────────────────────────────────────────────
# Cookie helpers (ортогонально к хранилищу)
# ────────────────────────────────────────────────────────────────────


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
            max_age=SESSION_TTL_SECONDS,  # 30 дней -- синхронизировано с TTL Redis
        )
    return session_id
