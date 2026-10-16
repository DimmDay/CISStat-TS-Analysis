"""
Реестр коннекторов БД — единственная точка знания о поддерживаемых СУБД.

UPLOAD-DB-1 (spec_database_plan.md, фаза A — коннекторное ядро;
развитие находок аудита UPLOAD-DB-AUDIT-1).

Утверждённая матрица (UPLOAD-DB-PLAN-1): PostgreSQL + Postgres Pro (ОДНА
запись с alias'ами — протокол совместим, вендор различается по
SELECT version()), ClickHouse, MS SQL Server, MySQL/MariaDB,
DuckDB (встроенная), SQLite (встроенная).

Архитектурные решения плана, реализованные здесь:
- каждая запись реестра несёт ГОТОВЫЙ sqlalchemy.text()-объект контрольного
  запроса (фикс D1 — SQLAlchemy 2.0 отклоняет сырые строки);
- пароль НЕ включается в строку соединения (D4) — передаётся через
  connect_args (SQLAlchemy-диалекты) или kwarg нативного клиента (ClickHouse);
- SQLAlchemy 2.0 — универсальный слой (postgresql+psycopg по скоуп-решению
  S1, mysql+pymysql, mssql+pyodbc, sqlite://, duckdb://); clickhouse-connect —
  нативный клиент ClickHouse (как в legacy-прототипе);
- модуль безопасно импортируется БЕЗ sqlalchemy/clickhouse-connect
  (ограничение образа apps/api: драйверы там не установлены) — при отсутствии
  зависимостей реестр остаётся читаемым, а открытие соединения даёт
  дружественный ImportError с подсказкой pip-установки (D2).

Модуль НЕ импортирует streamlit — stateless, с явными аргументами (Правило 14).
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional, Tuple

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    from sqlalchemy.exc import NoSuchModuleError
    from sqlalchemy.sql.elements import TextClause
except ImportError:  # pragma: no cover — средовой класс (образ apps/api без sqlalchemy)
    create_engine = None
    text = None
    URL = None
    NoSuchModuleError = Exception
    TextClause = None

try:
    import clickhouse_connect
except ImportError:  # pragma: no cover — средовой класс (драйвер не установлен)
    clickhouse_connect = None

from app.data.db_guard import mask_secrets, validate_host_allowed

logger = logging.getLogger(__name__)

# Таймауты по умолчанию (скоуп-решение S4): 10 c на соединение, 60 c на
# запрос — env-переопределяемые (UPLOAD_DB_CONNECT_TIMEOUT / UPLOAD_DB_QUERY_TIMEOUT).
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_QUERY_TIMEOUT = 60

_DRIVER_ODBC_MSSQL = "ODBC Driver 18 for SQL Server"


def _test_clause(sql: str) -> Any:
    """Готовый text()-объект; None без sqlalchemy (импорт-безопасность)."""
    return text(sql) if text is not None else None


@dataclass(frozen=True)
class DbConnectorSpec:
    """Спецификация одного коннектора (одна строка знания о СУБД).

    Атрибуты:
        id:                   канонический идентификатор реестра.
        label:                человекочитаемая подпись (UI, формы UPLOAD-DB-5).
        aliases:              алиасы резолюции (Postgres Pro, MariaDB, ...).
        mode:                 "server" (креды host/port/user/password) или
                              "embedded" (path к файлу).
        dialect:              SQLAlchemy-диалект; None — нативный клиент.
        default_port:         порт по умолчанию (UI-подсказка); None — embedded.
        test_sql:             ГОТОВЫЙ text() контрольного запроса (фикс D1).
        ssl_support:          поддерживает ли TLS-флаг подключения.
        native_client:        True только у ClickHouse (clickhouse-connect).
        path_extensions:      embedded: допустимые расширения файла-источника.
        query_file_extensions: embedded: файл читается прямым SELECT
                              (DuckDB по Parquet/CSV без сервера).
        pip_package:          D2: подсказка установки недостающего драйвера.
        version_probe:        ГОТОВЫЙ text() запроса версии/вендора сервера.
    """

    id: str
    label: str
    aliases: Tuple[str, ...] = ()
    mode: str = "server"
    dialect: Optional[str] = None
    default_port: Optional[int] = None
    test_sql: Any = None
    ssl_support: bool = False
    native_client: bool = False
    path_extensions: Tuple[str, ...] = ()
    query_file_extensions: Tuple[str, ...] = ()
    pip_package: Optional[str] = None
    version_probe: Any = None


DB_CONNECTORS = {
    "postgresql": DbConnectorSpec(
        id="postgresql",
        label="PostgreSQL / Postgres Pro",
        aliases=("postgres", "pg", "postgrespro", "postgres-pro", "postgres_pro"),
        mode="server",
        dialect="postgresql+psycopg",  # скоуп-решение S1: драйвер psycopg v3
        default_port=5432,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=True,
        pip_package="psycopg[binary]",
        version_probe=_test_clause("SELECT version()"),
    ),
    "clickhouse": DbConnectorSpec(
        id="clickhouse",
        label="ClickHouse",
        aliases=("ch",),
        mode="server",
        dialect=None,  # нативный клиент clickhouse-connect (как в legacy)
        default_port=8123,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=True,
        native_client=True,
        pip_package="clickhouse-connect",
        version_probe=_test_clause("SELECT version()"),
    ),
    "mssql": DbConnectorSpec(
        id="mssql",
        label="MS SQL Server",
        aliases=("ms sql", "sqlserver", "ms sql server", "microsoft sql server"),
        mode="server",
        dialect="mssql+pyodbc",  # скоуп-решение S2: pyodbc, fallback pymssql
        default_port=1433,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=True,
        pip_package="pyodbc",
    ),
    "mysql": DbConnectorSpec(
        id="mysql",
        label="MySQL / MariaDB",
        aliases=("mariadb", "maria"),
        mode="server",
        dialect="mysql+pymysql",
        default_port=3306,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=True,
        pip_package="PyMySQL",
    ),
    "duckdb": DbConnectorSpec(
        id="duckdb",
        label="DuckDB (встроенная)",
        aliases=(),
        mode="embedded",
        dialect="duckdb",
        default_port=None,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=False,
        path_extensions=(".db", ".duckdb", ".parquet", ".csv"),
        query_file_extensions=(".parquet", ".csv"),  # прямой SELECT по файлу
        pip_package="duckdb duckdb-engine",
    ),
    "sqlite": DbConnectorSpec(
        id="sqlite",
        label="SQLite (встроенная)",
        aliases=("sqlite3",),
        mode="embedded",
        dialect="sqlite",
        default_port=None,
        test_sql=_test_clause("SELECT 1"),
        ssl_support=False,
        path_extensions=(".db", ".sqlite"),
        pip_package=None,  # sqlite3 входит в стандартную библиотеку
    ),
}

SUPPORTED_IDS_TEXT = ", ".join(DB_CONNECTORS)


def _normalize_db_type(value: Any) -> str:
    """Нормализация пользовательского имени СУБД: регистр/пробелы/дефисы."""
    return (
        str(value).strip().lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
    )


_ALIAS_INDEX = {_normalize_db_type(cid): cid for cid in DB_CONNECTORS}
for _spec in DB_CONNECTORS.values():
    for _alias in _spec.aliases:
        _ALIAS_INDEX.setdefault(_normalize_db_type(_alias), _spec.id)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_db_timeouts() -> Tuple[int, int]:
    """Таймауты подключения/запроса (S4): env UPLOAD_DB_CONNECT_TIMEOUT /
    UPLOAD_DB_QUERY_TIMEOUT; дефолты 10с/60с (паритет legacy-прототипа)."""
    connect_timeout = _env_int("UPLOAD_DB_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT)
    query_timeout = _env_int("UPLOAD_DB_QUERY_TIMEOUT", DEFAULT_QUERY_TIMEOUT)
    return connect_timeout, query_timeout


def get_connector(db_type: Any) -> DbConnectorSpec:
    """Резолюция типа БД по каноническому id или alias (case-insensitive).

    Raises:
        ValueError: тип вне утверждённой матрицы 6 СУБД (DoD UPLOAD-DB-1).
    """
    key = _normalize_db_type(db_type)
    if not key:
        raise ValueError(
            "Неподдерживаемый тип БД: пустое значение. "
            f"Поддерживаются: {SUPPORTED_IDS_TEXT}"
        )
    connector_id = _ALIAS_INDEX.get(key)
    if connector_id is None:
        raise ValueError(
            f"Неподдерживаемый тип БД: {db_type!r}. "
            f"Поддерживаются: {SUPPORTED_IDS_TEXT}"
        )
    return DB_CONNECTORS[connector_id]


def list_connectors() -> list:
    """Записи реестра в порядке утверждённой матрицы."""
    return list(DB_CONNECTORS.values())


def build_server_url(
    spec: DbConnectorSpec,
    *,
    host: str,
    port: Any,
    database: str,
    username: str,
    password: str,
    ssl: bool = False,
) -> Tuple[Any, dict]:
    """Собирает (URL, connect_args) для серверного SQLAlchemy-диалекта.

    D4: пароль НЕ включается в URL (кроме pyodbc-особенности MSSQL, где
    строка ODBC собирается диалектом из URL-объекта, а str(url) маскирует
    пароль штатным render_as_string(hide_password=True)).

    D3: ssl-флаг управляет TLS-поведением диалекта —
      PG:    sslmode=require / disable (явно — находка D3);
      MySQL: ssl_verify_cert=True / ssl_disabled=True (PyMySQL);
      MSSQL: Encrypt=yes+TrustServerCertificate=no / Encrypt=no (ODBC 18).

    Returns:
        (sqlalchemy.engine.URL, dict connect_args)
    """
    if spec.dialect is None:
        raise ValueError(f"Для {spec.label} используется нативный клиент, а не SQLAlchemy")
    port_int = int(port) if port not in (None, "") else spec.default_port
    connect_timeout, query_timeout = get_db_timeouts()

    if spec.id == "mssql":
        # pyodbc: параметры ODBC передаются в query-части URL; пароль маскируется
        # в str(url). Скоуп-решение S2: pyodbc + ODBC Driver 18, fallback pymssql.
        query = {
            "driver": _DRIVER_ODBC_MSSQL,
            "Encrypt": "yes" if ssl else "no",
        }
        if ssl:
            query["TrustServerCertificate"] = "no"
        url = URL.create(
            spec.dialect,
            username=username,
            password=password,
            host=host,
            port=port_int,
            database=database,
            query=query,
        )
        connect_args: dict = {}
    else:
        # PG/MySQL: пароль строго ВНЕ строки соединения — через connect_args.
        url = URL.create(
            spec.dialect,
            username=username,
            host=host,
            port=port_int,
            database=database,
        )
        connect_args = {"password": password}
        if spec.dialect == "postgresql+psycopg":
            connect_args["connect_timeout"] = connect_timeout
            connect_args["options"] = f"-c statement_timeout={query_timeout * 1000}"
            connect_args["sslmode"] = "require" if ssl else "disable"  # D3
        elif spec.dialect == "mysql+pymysql":
            connect_args["connect_timeout"] = connect_timeout
            if ssl:  # D3: TLS с проверкой сертификата сервера
                connect_args["ssl_verify_cert"] = True
            else:
                connect_args["ssl_disabled"] = True
    return url, connect_args


def open_server_engine(spec: DbConnectorSpec, url: Any, connect_args: dict) -> Any:
    """Открывает SQLAlchemy Engine серверной СУБД (паритет legacy: пул + ping)."""
    if create_engine is None:
        raise ImportError(
            f"sqlalchemy не установлен — {spec.label} недоступна. "
            'Установите: pip install "sqlalchemy>=2.0"'
        )
    try:
        return create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    except NoSuchModuleError as exc:
        # D2: дружественная детекция отсутствия драйвера на слое DBAPI.
        raise ImportError(
            f"Не установлен драйвер {spec.label}. "
            f'Установите: pip install "{spec.pip_package}"'
        ) from exc


def open_clickhouse(
    spec: DbConnectorSpec,
    *,
    host: str,
    port: Any,
    username: str,
    password: str,
    database: str,
    ssl: bool = False,
) -> Any:
    """Открывает нативный клиент ClickHouse.

    D3: TLS-флаги secure/verify управляются параметром ssl (legacy-прототип
    жёстко задавал secure=False/verify=False — трафик с паролем шёл открытым
    текстом). По умолчанию ssl=False — паритет legacy-поведения.
    """
    if clickhouse_connect is None:
        raise ImportError(
            f"Не установлен драйвер {spec.label}. "
            f'Установите: pip install "{spec.pip_package}"'
        )
    port_int = int(port) if port not in (None, "") else spec.default_port
    connect_timeout, query_timeout = get_db_timeouts()
    return clickhouse_connect.get_client(
        host=host,
        port=port_int,
        username=username,
        password=password,
        database=database,
        secure=bool(ssl),   # D3
        verify=bool(ssl),   # D3: проверка сертификата при TLS
        connect_timeout=connect_timeout,
        send_receive_timeout=query_timeout,
    )


def open_embedded(spec: DbConnectorSpec, *, path: str) -> Any:
    """Открывает встроенную СУБД по пути к файлу (UPLOAD-DB-3).

    Валидация пути (DoD UPLOAD-DB-3): расширение из path_extensions записи,
    файл существует. Обе встроенные СУБД открываются ТОЛЬКО на чтение:
      SQLite — URI mode=ro (CREATE/INSERT на уровне файла невозможны);
      DuckDB — connect read_only=True (платформа — потребитель данных).
    DuckDB по Parquet/CSV (query_file_extensions) открывает in-memory
    движок — файл читается прямым SELECT 'путь' без сервера.
    """
    if create_engine is None:
        raise ImportError(
            f"sqlalchemy не установлен — {spec.label} недоступна. "
            'Установите: pip install "sqlalchemy>=2.0" '
            f"{(spec.pip_package or '').strip()}".strip()
        )
    validated = _validate_embedded_path(spec, path)
    if spec.dialect == "sqlite":
        # read-only URI: sqlite:///file:<квотиованный путь>?mode=ro&uri=true
        quoted = urllib.parse.quote(validated, safe="/")
        return create_engine(f"sqlite:///file:{quoted}?mode=ro&uri=true")
    if spec.dialect == "duckdb":
        ext = os.path.splitext(validated)[1].lower()
        if ext in spec.query_file_extensions:
            # Parquet/CSV: файл читается прямым SELECT, база — in-memory.
            return create_engine("duckdb:///:memory:")
        return create_engine(
            f"duckdb:///{validated}", connect_args={"read_only": True}
        )
    raise ValueError(f"Встроенный режим не реализован для {spec.label}")


def _validate_embedded_path(spec: DbConnectorSpec, path: Any) -> str:
    """Валидация пути embedded-источника (DoD UPLOAD-DB-3)."""
    raw = str(path).strip() if path else ""
    if not raw:
        raise ValueError(
            f"Не указан путь к файлу {spec.label} (ожидается: "
            f"{', '.join(spec.path_extensions)})"
        )
    resolved = os.path.expanduser(raw)
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in spec.path_extensions:
        raise ValueError(
            f"Недопустимое расширение {ext or '(без расширения)'} для {spec.label}. "
            f"Ожидаются: {', '.join(spec.path_extensions)}"
        )
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Файл не найден: {resolved}")
    return resolved


def probe_connection(spec: DbConnectorSpec, conn_obj: Any, *, path: Any = None) -> None:
    """Контрольный запрос «Тест» (фикс D1): text() из реестра / ping для CH.

    Для DuckDB по Parquet/CSV контрольным запросом служит прямое чтение
    первой строки самого файла — «Тест» честно проверяет читаемость
    источника, а не только факт загрузки движка.

    Raises:
        Exception: любая ошибка транспорта/аутентификации пробрасывается
            выше — обёртка init_db_connection превращает её в ConnectionError.
    """
    if spec.native_client:
        conn_obj.ping()
        return
    if TextClause is None or text is None or spec.test_sql is None:
        raise ImportError(
            "sqlalchemy не установлен — контрольный запрос недоступен. "
            'Установите: pip install "sqlalchemy>=2.0"'
        )
    clause = spec.test_sql
    if spec.mode == "embedded" and path is not None:
        ext = os.path.splitext(os.path.expanduser(str(path).strip()))[1].lower()
        if ext in spec.query_file_extensions:
            file_sql = "SELECT * FROM '{}' LIMIT 1".format(
                str(path).strip().replace("'", "''")
            )
            clause = text(file_sql)
    with conn_obj.connect() as conn:
        conn.execute(clause)
