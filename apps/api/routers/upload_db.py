# apps/api/routers/upload_db.py
"""
UPLOAD-DB-4 (spec_database_plan.md, фаза B): сервисы «Загрузка → База
данных (SQL)» -- API-контракт над ядром Фазы A.

Роутер монтируется В ОБОИХ семействах (конвенция платформы, паритет
файлового /upload):
    /v1/internal/upload/db/*  -- без авторизации (embedded/standalone);
    /v1/public/upload/db/*    -- по API-ключу (внешние покупатели).
Один модуль реализации: обработчики регистрируются на ОБА роутера,
дублирование логики запрещено (та же дисциплина, что upload_common.py
для файловой дорожки). Браузерная сессия -- общая cookie
cisstat_session_id (сессия НЕ различается по семействам).

Единственная реализация семантики (дублирование запрещено планом):
  подключение -- app.data.file_loader.init_db_connection (реестр
  коннекторов + host-whitelist D5 + открытие + контрольный text()-запрос
  D1 + маскирование D4);
  чтение     -- app.data.db_guard.load_db_dataframe (read-only guard D6 +
  row_limit S4 + chunksize-стриминг + маскирование D4);
  регистрация -- apps.api.upload_common.register_uploaded_dataframe
  (SessionStore → существующий 5-остановочный пайплайн «Загрузки» без
  новых типов событий трассы).

Карта ошибок (задокументирована в OpenAPI):
  /test -- probe-семантика (отрицательный результат пробы -- НЕ ошибка):
    200 {ok:false, error маскирован} -- ConnectionError (креды/транспорт),
        FileNotFoundError (embedded-файл), ImportError (драйвер, D2);
    422 -- HostNotAllowed (whitelist D5), ValueError (путь/расширение),
        pydantic (схема).
  /load:
    200 UploadResponse -- успех (контракт файла);
    400 -- операционные сбои (ConnectionError/FileNotFoundError/
        ImportError/DbLoadError), деталь маскирована (D4);
    422 -- HostNotAllowed, ValueError, DbQueryRejected (read-only guard,
        DoD плана), pydantic (схема).
«Тест» сознательно НЕ трассируется (probe, не факт анализа) и НЕ
создаёт сессию: факт анализа -- только загрузка датасета.

Safe-дефолты фазы B (указание тимлида): ssl=False (паритет legacy, D3),
host-whitelist off (S5 -- решение о включении в проде после утверждения
сетевой топологии), row_limit None → env-потолок ядра (S4).

НЕ в скоупе этой задачи: legacy-UI app.py:520 (остаток D1 -- скоуп
UPLOAD-DB-10), MSSQL-пароль в URL-объекте pyodbc (пересмотр на
UPLOAD-DB-7), UI-форма (UPLOAD-DB-5) и навигатор (UPLOAD-DB-6).
"""
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.data import db_connectors
from app.data.db_guard import (
    DbLoadError,
    DbQueryRejected,
    HostNotAllowed,
    load_db_dataframe,
    mask_secrets,
)
from app.data.file_loader import init_db_connection
from apps.api.auth import require_api_key
from apps.api.schemas import (
    DbLoadRequest,
    DbTestRequest,
    DbTestResponse,
    ServerDbCredentials,
    UploadResponse,
)
from apps.api.session_store import format_size_label
from apps.api.upload_common import register_uploaded_dataframe

logger = logging.getLogger(__name__)

# internal-семейство (embedded/standalone): cookie-сессия, без API-ключа.
router = APIRouter()
# public-семейство (внешние покупатели): тот же контракт за API-ключом.
public_router = APIRouter(dependencies=[Depends(require_api_key)])


def _connection_kwargs(connection) -> dict:
    """Разбор union-профиля в kwargs init_db_connection (ядро Фазы A).

    Embedded-ветка: host/port/креды не нужны (контракт ядра -- игнорирует
    их); серверная: host/port/database/user/password/ssl. Пароль
    передаётся только в ядро (D4: в URL не попадает, в исключениях
    маскируется централизованно)."""
    if not isinstance(connection, ServerDbCredentials):
        return dict(
            db_type=connection.db_type,
            host="",
            port=None,
            user="",
            password="",
            db_name="",
            ssl=False,
            path=connection.path,
        )
    return dict(
        db_type=connection.db_type,
        host=connection.host,
        port=connection.port,
        user=connection.user,
        password=connection.password,
        db_name=connection.database,
        ssl=connection.ssl,
        path=None,
    )


def _source_name(connection, spec) -> str:
    """Человекочитаемое имя датасета для UI/трассы:
    серверная СУБД -- «{label реестра}: {database}», embedded -- basename
    файла (host в имя не включаем: идентификация источника -- вендор+база,
    не сетевой адрес)."""
    if isinstance(connection, ServerDbCredentials):
        return f"{spec.label}: {connection.database}"
    return os.path.basename(os.path.expanduser(str(connection.path).strip()))


def _server_version(spec, conn_obj) -> "str | None":
    """Версия/вендор сервера: version_probe реестра (SELECT version() --
    вендор-детекция PG-семейства, UPLOAD-DB-8). Нативный клиент CH --
    query() по сырому SQL TextClause.text; SQLAlchemy-движок -- scalar().
    У СУБД без probe (embedded) -- честное None."""
    clause = spec.version_probe
    if clause is None:
        return None
    if spec.native_client:
        rows = conn_obj.query(clause.text).result_rows
        return str(rows[0][0]) if rows else None
    with conn_obj.connect() as conn:
        value = conn.execute(clause).scalar()
    return str(value) if value is not None else None


def _release_connection(conn_obj, password: str) -> None:
    """Every API call owns its engine/client, including failed reads/probes."""
    closer = getattr(conn_obj, "dispose", None) or getattr(conn_obj, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception as exc:
            logger.warning("DB connection cleanup failed: %s", mask_secrets(exc, password))


def _register(app_router: APIRouter) -> None:
    @app_router.post("/test", response_model=DbTestResponse)
    def test_db_connection(payload: DbTestRequest) -> DbTestResponse:
        """Проба подключения «Тест»: ядро Фазы A (открытие + контрольный
        text()-запрос D1). Transport/креды/драйвер/файл -- 200 {ok:false}
        с маскированной причиной; контрактные нарушения (схема, путь,
        whitelist) -- 422. Сессию НЕ создаёт (probe-чистота)."""
        connection = payload.connection
        db_type = connection.db_type
        password = getattr(connection, "password", "") or ""
        spec = db_connectors.get_connector(db_type)  # ValueError -- 422 маппинг ниже
        started = time.perf_counter()
        try:
            conn_obj = init_db_connection(**_connection_kwargs(connection))
        except (ConnectionError, FileNotFoundError, ImportError) as exc:
            # Отрицательный результат пробы (не серверная ошибка): 200.
            logger.info("DB test failed (%s): %s", db_type, mask_secrets(exc, password))
            return DbTestResponse(
                ok=False, db_type=db_type, error=mask_secrets(str(exc), password)
            )
        except ValueError as exc:  # вкл. HostNotAllowed (подкласс)
            raise HTTPException(status_code=422, detail=mask_secrets(str(exc), password))
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            # Версия -- best-effort факт: сбой probe версии не роняет пробу
            # (соединение уже подтверждено контрольным запросом ядра).
            try:
                version = _server_version(spec, conn_obj)
            except Exception as exc:
                logger.info("DB version probe failed (%s): %s", db_type, mask_secrets(exc, password))
                version = None
            return DbTestResponse(
                ok=True, db_type=db_type, server_version=version, latency_ms=latency_ms
            )
        finally:
            _release_connection(conn_obj, password)

    @app_router.post("/load", response_model=UploadResponse)
    def load_db_dataset(
        payload: DbLoadRequest, request: Request, response: Response
    ) -> UploadResponse:
        """Загрузка БД-датасета: ядро Фазы A (guard → лимит → стриминг),
        затем ЕДИНАЯ регистрация register_uploaded_dataframe -- ответ
        UploadResponse (контракт файла), сессия/cookie, остановка
        upload=done, событие трассы upload_completed (узел overview) --
        БД-датасет проходит существующий 5-остановочный пайплайн без
        новых типов событий."""
        connection = payload.connection
        db_type = connection.db_type
        password = getattr(connection, "password", "") or ""
        spec = db_connectors.get_connector(db_type)
        try:
            conn_obj = init_db_connection(**_connection_kwargs(connection))
        except ValueError as exc:  # вкл. HostNotAllowed (подкласс)
            raise HTTPException(status_code=422, detail=mask_secrets(str(exc), password))
        except (ConnectionError, FileNotFoundError, ImportError) as exc:
            logger.error(
                "DB load failed (%s): %s", db_type, mask_secrets(exc, password)
            )
            raise HTTPException(status_code=400, detail=mask_secrets(str(exc), password))

        try:
            try:
                result = load_db_dataframe(
                    conn_obj,
                    payload.sql,
                    row_limit=payload.row_limit,
                    secrets=(password,),
                )
            except DbQueryRejected as exc:
                # Read-only guard (DoD: guard -> 422). Сообщение -- про
                # правило чтения, секретов не содержит (SQL пользователя).
                raise HTTPException(status_code=422, detail=str(exc))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=mask_secrets(str(exc), password))
            except DbLoadError as exc:
                # Уже маскировано ядром (D4) -- пробрасываем как есть.
                raise HTTPException(status_code=400, detail=str(exc))
            except (ConnectionError, FileNotFoundError, ImportError) as exc:
                raise HTTPException(status_code=400, detail=mask_secrets(str(exc), password))

            df = result.dataframe
            # Честная пометка усечения выборки -- технический флаг
            # parse_warnings (без новых полей схемы и новых событий трассы).
            extra_warnings = []
            if result.truncated:
                extra_warnings.append(
                    f"Выборка ограничена лимитом {result.row_limit} строк "
                    "(источник содержит больше данных)"
                )
            # size_label БД-источника -- объём загруженного фрейма в памяти
            # (размер файла-источника неприменим; честная размерность).
            size_label = format_size_label(int(df.memory_usage(deep=True).sum()))
            return register_uploaded_dataframe(
                df,
                name=_source_name(connection, spec),
                size_label=size_label,
                request=request,
                response=response,
                extra_parse_warnings=extra_warnings,
            )
        finally:
            _release_connection(conn_obj, password)


_register(router)
_register(public_router)
