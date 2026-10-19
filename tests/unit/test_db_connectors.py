"""
Unit-тесты реестра коннекторов БД — UPLOAD-DB-1 (spec_database_plan.md, фаза A).

Реестр app/data/db_connectors.py — ЕДИНСТВЕННАЯ точка знания о СУБД:
6 записей утверждённой матрицы (PostgreSQL + Postgres Pro — одна запись
с alias'ами, ClickHouse, MS SQL Server, MySQL/MariaDB, DuckDB, SQLite).
Каждая запись несёт готовый text()-объект контрольного запроса (фикс D1).
"""
import os
import subprocess
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.sql.elements import TextClause

from app.data.db_connectors import (
    DB_CONNECTORS,
    get_connector,
    list_connectors,
    build_server_url,
)
from app.data.file_loader import init_db_connection

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Утверждённая матрица БД (UPLOAD-DB-PLAN-1): порядок и подписи UI
APPROVED_MATRIX = [
    ("postgresql", "PostgreSQL / Postgres Pro", "server", 5432),
    ("clickhouse", "ClickHouse", "server", 8123),
    ("mssql", "MS SQL Server", "server", 1433),
    ("mysql", "MySQL / MariaDB", "server", 3306),
    ("duckdb", "DuckDB (встроенная)", "embedded", None),
    ("sqlite", "SQLite (встроенная)", "embedded", None),
]


class TestRegistry:
    """Контракт реестра: 6 записей, порядок, режимы, D1."""

    def test_six_entries_approved_matrix(self):
        """Ровно 6 записей в порядке утверждённой матрицы."""
        assert [s.id for s in list_connectors()] == [row[0] for row in APPROVED_MATRIX]

    def test_labels_match_approved(self):
        for spec, (_, label, _, _) in zip(list_connectors(), APPROVED_MATRIX):
            assert spec.label == label

    def test_modes_server_embedded(self):
        modes = {spec.id: spec.mode for spec in list_connectors()}
        assert modes == {
            "postgresql": "server",
            "clickhouse": "server",
            "mssql": "server",
            "mysql": "server",
            "duckdb": "embedded",
            "sqlite": "embedded",
        }

    def test_default_ports(self):
        ports = {spec.id: spec.default_port for spec in list_connectors()}
        assert ports == {
            "postgresql": 5432,
            "clickhouse": 8123,
            "mssql": 1433,
            "mysql": 3306,
            "duckdb": None,
            "sqlite": None,
        }

    def test_test_sql_is_ready_textclause(self):
        """D1: каждая запись несёт ГОТОВЫЙ text()-объект контрольного запроса."""
        for spec in list_connectors():
            assert isinstance(spec.test_sql, TextClause), spec.id
        assert get_connector("postgresql").test_sql.text == "SELECT 1"

    def test_native_client_only_clickhouse(self):
        for spec in list_connectors():
            assert spec.native_client == (spec.id == "clickhouse")

    def test_ssl_support_only_server(self):
        for spec in list_connectors():
            assert spec.ssl_support == (spec.mode == "server")

    def test_pg_dialect_is_psycopg_v3(self):
        """Скоуп-решение S1 (утверждено тимлидом): драйвер PG — psycopg v3."""
        assert get_connector("postgresql").dialect == "postgresql+psycopg"

    def test_version_probe_declared_for_vendor_detection(self):
        """Вендор-детекция PG-семейства: готовый text() SELECT version()."""
        pg = get_connector("postgresql")
        assert isinstance(pg.version_probe, TextClause)
        assert pg.version_probe.text == "SELECT version()"

    def test_mysql_mssql_dialects(self):
        assert get_connector("mysql").dialect == "mysql+pymysql"
        assert get_connector("mssql").dialect == "mssql+pyodbc"
        assert get_connector("clickhouse").dialect is None  # нативный клиент


class TestGetConnector:
    """Резолюция по id/alias, case-insensitive, unsupported → ValueError."""

    @pytest.mark.parametrize("raw,expected", [
        ("PostgreSQL", "postgresql"),   # legacy-значения прототипа app.py
        ("ClickHouse", "clickhouse"),
        ("postgres", "postgresql"),
        ("pg", "postgresql"),
        ("PostgresPro", "postgresql"),  # Postgres Pro — ОДНА запись с alias'ами
        ("postgres-pro", "postgresql"),
        ("mariadb", "mysql"),
        ("MariaDB", "mysql"),
        ("mssql", "mssql"),
        ("MS SQL Server", "mssql"),
        ("sqlserver", "mssql"),
        ("sqlite3", "sqlite"),
        ("duckdb", "duckdb"),
    ])
    def test_resolution(self, raw, expected):
        assert get_connector(raw).id == expected

    def test_unknown_raises_valueerror(self):
        with pytest.raises(ValueError, match="Неподдерживаемый тип БД"):
            get_connector("Oracle")

    def test_unknown_message_lists_supported(self):
        with pytest.raises(ValueError) as ei:
            get_connector("mongodb")
        msg = str(ei.value)
        for cid in ("postgresql", "clickhouse", "mssql", "mysql", "duckdb", "sqlite"):
            assert cid in msg

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            get_connector("   ")


class TestBuildServerUrl:
    """URL-билдер: пароль НЕ в строке соединения (D4), паритет таймаутов."""

    def test_pg_url_no_password(self):
        """DoD: пароль отсутствует в строке URL — даже с hide_password=False."""
        spec = get_connector("postgresql")
        url, connect_args = build_server_url(
            spec, host="db.corp", port=5432, database="dw",
            username="analyst", password="s3cret-pw",
        )
        assert isinstance(url, URL)
        assert url.drivername == "postgresql+psycopg"
        assert url.host == "db.corp" and url.port == 5432
        assert url.database == "dw" and url.username == "analyst"
        rendered = url.render_as_string(hide_password=False)
        assert "s3cret-pw" not in rendered
        # пароль передаётся через connect_args (вне строки соединения)
        assert connect_args["password"] == "s3cret-pw"

    def test_pg_legacy_timeout_parity(self):
        spec = get_connector("postgresql")
        _, connect_args = build_server_url(
            spec, host="h", port=5432, database="d",
            username="u", password="p",
        )
        assert connect_args["connect_timeout"] == 10
        assert "statement_timeout=60000" in connect_args["options"]

    def test_mysql_url_no_password(self):
        spec = get_connector("mysql")
        url, connect_args = build_server_url(
            spec, host="h", port=3306, database="d",
            username="u", password="mysql-pw",
        )
        assert url.drivername == "mysql+pymysql"
        assert "mysql-pw" not in url.render_as_string(hide_password=False)
        assert connect_args["password"] == "mysql-pw"

    def test_mssql_url_driver_and_masked(self):
        spec = get_connector("mssql")
        url, _ = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="mssql-pw",
        )
        assert url.drivername == "mssql+pyodbc"
        assert url.query["driver"] == "ODBC Driver 18 for SQL Server"
        # pyodbc получает пароль через URL-объект, но str() маскирует его (DoD)
        assert "mssql-pw" not in str(url)


class TestInitDbConnectionDelegation:
    """file_loader.init_db_connection делегирует реестру (одна реализация семантики)."""

    @patch('app.data.db_connectors.create_engine')
    def test_pg_success_via_registry(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        result = init_db_connection(
            db_type="PostgreSQL", host="localhost", port=5432,
            user="test_user", password="test_pass", db_name="test_db",
        )

        assert result == mock_engine
        args, kwargs = mock_create_engine.call_args
        url = args[0]
        assert isinstance(url, URL)
        assert "test_pass" not in str(url)  # D4: пароль не в URL
        assert kwargs["connect_args"]["password"] == "test_pass"
        sent = mock_conn.execute.call_args[0][0]
        assert isinstance(sent, TextClause) and sent.text == "SELECT 1"  # D1

    @patch('app.data.db_connectors.clickhouse_connect')
    def test_ch_success_via_registry(self, mock_ch_connect):
        mock_client = Mock()
        mock_ch_connect.get_client.return_value = mock_client

        result = init_db_connection(
            db_type="ClickHouse", host="localhost", port=8123,
            user="test_user", password="test_pass", db_name="test_db",
        )

        assert result == mock_client
        mock_ch_connect.get_client.assert_called_once()
        mock_client.ping.assert_called_once()

    @patch('app.data.db_connectors.create_engine')
    def test_pg_error_wraps_connectionerror(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Connection refused")
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        with pytest.raises(ConnectionError, match="Не удалось подключиться к PostgreSQL"):
            init_db_connection(
                db_type="PostgreSQL", host="localhost", port=5432,
                user="u", password="p", db_name="d",
            )

    def test_invalid_type_propagates_valueerror(self):
        with pytest.raises(ValueError, match="Неподдерживаемый тип БД"):
            init_db_connection(
                db_type="Sybase", host="localhost", port=5000,
                user="u", password="p", db_name="d",
            )


class TestImportSafety:
    """Модуль реестра импортируется БЕЗ sqlalchemy (ограничение образа apps/api)."""

    def test_db_modules_importable_without_sqlalchemy(self):
        code = (
            "import sys\n"
            "sys.modules['sqlalchemy'] = None\n"
            "sys.modules['sqlalchemy.engine'] = None\n"
            "sys.modules['sqlalchemy.exc'] = None\n"
            "sys.modules['sqlalchemy.sql'] = None\n"
            "sys.modules['sqlalchemy.sql.elements'] = None\n"
            "import app.data.db_connectors as dc\n"
            "import app.data.file_loader as fl\n"
            "assert dc.get_connector('postgresql').id == 'postgresql'\n"
            "assert dc.get_connector('clickhouse').native_client is True\n"
            "assert len(dc.list_connectors()) == 6\n"
            "assert callable(fl.init_db_connection)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "OK" in result.stdout


# ═══════════════ UPLOAD-DB-7 (фаза C): MySQL/MariaDB + MS SQL Server ═════════
#
# План (spec_database_plan.md): диалекты mysql+pymysql (порт 3306, ssl) и
# mssql+pyodbc (порт 1433, ODBC Driver 18, Encrypt/TrustServerCertificate),
# PyMySQL[cryptography]+pyodbc пиннен, unit на URL-билдеры.
#
# Пересмотр (указание тимлида из UPLOAD-DB-4, «MSSQL-пароль в URL-объекте
# pyodbc — пересмотреть на UPLOAD-DB-7»): пароль MSSQL ВЫВЕДЕН из URL-объекта
# целиком — D4-паритет с PG/MySQL/ClickHouse. Эксперимент E1 (протокол в
# scripts/upload_db7_experiments.py): render_as_string(hide_password=False)
# и атрибут url.password отдают СЫРОЙ пароль — маскирование str() не является
# защитой объекта. pyodbc 5.x (докстринг connect): «Any keywords except
# autocommit and timeout are simply added to the connection string» + «DB API
# keywords ... will be converted to 'uid', 'pwd'» — пароль передаётся через
# connect_args["PWD"] с ODBC-экранированием в фигурных скобках (SQLDriverConnect).
#
# Fallback pymssql (скоуп-решение S2, риск RP2): если pyodbc недоступен, а
# pymssql установлен — диалект mssql+pymssql; оба отсутствуют — дефолт
# mssql+pyodbc с дружественной ошибкой (D2) с подсказкой обоих драйверов.
# Порядок резолюции драйвера MSSQL: явный параметр mssql_driver →
# env UPLOAD_DB_MSSQL_DRIVER (переключатель деплоя без правки кода:
# если apt-слой ODBC недоступен в контуре — RP2) → авто (pyodbc → pymssql →
# дефолт pyodbc).


@pytest.fixture(autouse=True)
def _deterministic_mssql_driver(monkeypatch):
    """UPLOAD-DB-7: детерминизм авто-резолюции mssql-драйвера для всех
    тестов модуля (pyodbc — основной, S2). Fallback-ветка отдельно
    переключает оба флага через monkeypatch в собственных тестах."""
    import app.data.db_connectors as dc
    monkeypatch.setattr(dc, "pyodbc", object())


class TestUploadDb7Registry:
    """Реестр: полные записи MySQL/MSSQL — version_probe, пины, fallback."""

    def test_mysql_version_probe(self):
        """Вендор/версия MySQL/MariaDB: SELECT VERSION() (работает в обоих)."""
        probe = get_connector("mysql").version_probe
        assert isinstance(probe, TextClause)
        assert probe.text == "SELECT VERSION()"

    def test_mssql_version_probe(self):
        """Версия MS SQL Server: SELECT @@VERSION."""
        probe = get_connector("mssql").version_probe
        assert isinstance(probe, TextClause)
        assert probe.text == "SELECT @@VERSION"

    def test_mysql_pip_hint_includes_cryptography(self):
        """D2-подсказка: MySQL 8 (caching_sha2_password) требует cryptography.
        В метаданных PyMySQL extra 'cryptography' НЕ существует (только
        'rsa'/'ed25519') — пин зависимостей даёт cryptography отдельно,
        подсказка перечисляет оба пакета через пробел (паттерн duckdb)."""
        assert get_connector("mysql").pip_package == "PyMySQL cryptography"

    def test_mssql_fallback_pip_package(self):
        """S2: pyodbc — основной драйвер MSSQL, pymssql — fallback."""
        spec = get_connector("mssql")
        assert spec.pip_package == "pyodbc"
        assert spec.fallback_pip_package == "pymssql"
        # прочим СУБД fallback не объявлен
        for cid in ("postgresql", "clickhouse", "mysql", "duckdb", "sqlite"):
            assert get_connector(cid).fallback_pip_package is None, cid


class TestUploadDb7MysqlUrl:
    """URL-билдер mysql+pymysql: пароль вне строки, порт, ssl, таймаут."""

    def test_default_port_3306(self):
        spec = get_connector("mysql")
        url, _ = build_server_url(
            spec, host="db.corp", port=None, database="dw",
            username="analyst", password="pw",
        )
        assert url.drivername == "mysql+pymysql"
        assert url.port == 3306

    def test_password_nowhere_in_url_object(self):
        """D4-паритет: пароль отсутствует даже в render_as_string(hide_password=False)."""
        spec = get_connector("mysql")
        url, connect_args = build_server_url(
            spec, host="h", port=3306, database="d",
            username="u", password="mysql-pw",
        )
        assert "mysql-pw" not in url.render_as_string(hide_password=False)
        assert connect_args["password"] == "mysql-pw"

    def test_connect_timeout_present(self):
        spec = get_connector("mysql")
        _, connect_args = build_server_url(
            spec, host="h", port=None, database="d",
            username="u", password="pw",
        )
        assert connect_args["connect_timeout"] == 10  # S4


class TestUploadDb7MssqlUrl:
    """URL-билдер mssql+pyodbc: пароль ВНЕ URL-объекта (пересмотр), ODBC-параметры."""

    def test_password_not_in_url_object_at_all(self):
        """Пересмотр D4 (указание тимлида): url.password is None и сырой пароль
        отсутствует даже в render_as_string(hide_password=False)."""
        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="mssql-pw",
        )
        assert url.drivername == "mssql+pyodbc"
        assert url.password is None
        assert "mssql-pw" not in url.render_as_string(hide_password=False)

    def test_password_via_connect_args_odbc_escaped(self):
        """pyodbc.connect добавляет неизвестные kwargs к строке соединения
        (докстринг pyodbc 5.x) — PWD уходит через connect_args с
        ODBC-экранированием в фигурных скобках."""
        spec = get_connector("mssql")
        _, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="mssql-pw",
        )
        assert connect_args["PWD"] == "{mssql-pw}"

    def test_odbc_escaping_special_chars(self):
        """ODBC-экранирование: спецсимволы пароля не ломают строку соединения
        (';' внутри значения, '}' удваивается)."""
        from app.data.db_connectors import _odbc_quote
        assert _odbc_quote("plain") == "{plain}"
        assert _odbc_quote("p;a") == "{p;a}"
        assert _odbc_quote("p@ss;w0rd}x") == "{p@ss;w0rd}}x}"
        assert _odbc_quote("") == "{}"

    def test_login_timeout_in_connect_args(self):
        """S4-паритет: login-таймаут pyodbc (kwarg timeout) в connect_args."""
        spec = get_connector("mssql")
        _, connect_args = build_server_url(
            spec, host="h", port=None, database="d",
            username="u", password="pw",
        )
        assert connect_args["timeout"] == 10
        assert spec.default_port == 1433

    def test_ssl_query_flags_unchanged(self):
        """D3: Encrypt/TrustServerCertificate остаются в query URL (не секрет)."""
        spec = get_connector("mssql")
        url_off, _ = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw", ssl=False,
        )
        url_on, _ = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw", ssl=True,
        )
        assert url_off.query["Encrypt"] == "no"
        assert "TrustServerCertificate" not in url_off.query
        assert url_on.query["Encrypt"] == "yes"
        assert url_on.query["TrustServerCertificate"] == "no"


class TestUploadDb7MssqlFallback:
    """S2/RP2: fallback-диалект mssql+pymssql — явный параметр, env-переключатель
    и авто-резолюция по доступности драйверов."""

    def test_explicit_pymssql_driver(self):
        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw", mssql_driver="pymssql",
        )
        assert url.drivername == "mssql+pymssql"
        # pymssql.connect(password=...) — сырой пароль, без ODBC-экранирования
        assert connect_args["password"] == "pw"
        assert "PWD" not in connect_args
        assert connect_args["login_timeout"] == 10
        assert "driver" not in url.query and "Encrypt" not in url.query

    def test_explicit_pyodbc_driver(self):
        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw", mssql_driver="pyodbc",
        )
        assert url.drivername == "mssql+pyodbc"
        assert connect_args["PWD"] == "{pw}"

    def test_unknown_driver_raises(self):
        spec = get_connector("mssql")
        with pytest.raises(ValueError, match="mssql_driver"):
            build_server_url(
                spec, host="h", port=1433, database="d",
                username="u", password="pw", mssql_driver="adonet",
            )

    def test_env_override_pymssql(self, monkeypatch):
        """RP2: переключатель деплоя UPLOAD_DB_MSSQL_DRIVER=pymssql —
        fallback без правки кода (например, apt-репозиторий MS недоступен
        в закрытом контуре, а ODBC-стек не ставится)."""
        monkeypatch.setenv("UPLOAD_DB_MSSQL_DRIVER", "pymssql")
        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw",
        )
        assert url.drivername == "mssql+pymssql"
        assert connect_args["password"] == "pw"

    def test_env_invalid_value_raises(self, monkeypatch):
        """Некорректное значение env — громкая ошибка конфигурации."""
        monkeypatch.setenv("UPLOAD_DB_MSSQL_DRIVER", "jtds")
        spec = get_connector("mssql")
        with pytest.raises(ValueError, match="UPLOAD_DB_MSSQL_DRIVER"):
            build_server_url(
                spec, host="h", port=1433, database="d",
                username="u", password="pw",
            )

    def test_mssql_driver_param_rejected_for_mysql(self):
        """Защита от тихого misuse: параметр только для mssql."""
        spec = get_connector("mysql")
        with pytest.raises(ValueError, match="только для mssql"):
            build_server_url(
                spec, host="h", port=3306, database="d",
                username="u", password="pw", mssql_driver="pymssql",
            )

    def test_auto_resolution_prefers_pyodbc(self, monkeypatch):
        """Оба драйвера доступны → pyodbc (S2: основной)."""
        import app.data.db_connectors as dc
        monkeypatch.setattr(dc, "pyodbc", object())
        monkeypatch.setattr(dc, "pymssql", object())
        spec = get_connector("mssql")
        url, _ = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw",
        )
        assert url.drivername == "mssql+pyodbc"

    def test_auto_resolution_falls_back_to_pymssql(self, monkeypatch):
        """RP2: pyodbc недоступен, pymssql установлен → mssql+pymssql."""
        import app.data.db_connectors as dc
        monkeypatch.setattr(dc, "pyodbc", None)
        monkeypatch.setattr(dc, "pymssql", object())
        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw",
        )
        assert url.drivername == "mssql+pymssql"
        assert connect_args["password"] == "pw"

    def test_auto_resolution_default_pyodbc_when_both_missing(self, monkeypatch):
        """Оба отсутствуют → детерминированный дефолт mssql+pyodbc
        (дружественная ошибка D2 с подсказкой обоих драйверов)."""
        import app.data.db_connectors as dc
        monkeypatch.setattr(dc, "pyodbc", None)
        monkeypatch.setattr(dc, "pymssql", None)
        spec = get_connector("mssql")
        url, _ = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw",
        )
        assert url.drivername == "mssql+pyodbc"


class TestUploadDb7DriverHandoff:
    """Что реально получает pyodbc.connect (эксперимент E2, протокол
    scripts/upload_db7_experiments.py): SQLAlchemy строит строку соединения
    из URL БЕЗ PWD, пароль приходит kwarg-ом — дублирования нет."""

    def test_pyodbc_connect_receives_pwd_as_kwarg(self):
        import types

        import app.data.db_connectors as dc
        captured = {}

        def _capture(*a, **kw):
            # фиксируем НАСТОЯЩИЕ аргументы вызова pyodbc.connect и
            # останавливаем соединение (диалект далее выполняет
            # _get_server_version_info, мокать его не требуется)
            captured.update(args=a, kwargs=kw)
            raise FakePyodbc.Error("captured — соединение не открываем")

        class FakePyodbc:
            """DBAPI-поверхность pyodbc (исключения + метаданные) —
            полноценная замена MagicMock: SQLAlchemy обращается к
            loaded_dbapi.<ProgrammingError и др.> в путях обработки ошибок."""

        for _exc in (
            "Warning", "Error", "InterfaceError", "DatabaseError", "DataError",
            "OperationalError", "IntegrityError", "InternalError",
            "ProgrammingError", "NotSupportedError",
            # классы объектов и константы DBAPI-модуля, к которым обращается
            # SQLAlchemy-коннектор pyodbc в путях инициализации/ошибок
            "Connection", "Cursor", "Row", "Binary", "Date", "Time", "Timestamp",
            "DATETIME", "STRING", "NUMBER", "BINARY",
        ):
            setattr(FakePyodbc, _exc, type(_exc, (Exception,), {}))
        FakePyodbc.version = "5.2.0"
        FakePyodbc.apilevel = "2.0"
        FakePyodbc.paramstyle = "qmark"
        FakePyodbc.threadsafety = 1
        FakePyodbc.connect = staticmethod(_capture)

        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="mssql-pw",
        )
        with patch.dict(sys.modules, {"pyodbc": types.SimpleNamespace(**vars(FakePyodbc))}):
            engine = dc.open_server_engine(spec, url, connect_args)
            # SQLAlchemy оборачивает DBAPI-ошибку в DBAPIError — важен факт
            # capture (аргументы pyodbc.connect), а не класс исключения
            with pytest.raises(Exception, match="captured"):
                engine.connect()
        conn_str = captured["args"][0]
        # строка соединения БЕЗ пароля; PWD — отдельным kwarg-ом (экранирован)
        assert "PWD" not in conn_str
        assert "mssql-pw" not in conn_str
        assert captured["kwargs"]["PWD"] == "{mssql-pw}"
        assert captured["kwargs"]["timeout"] == 10
        assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_str
        assert "Encrypt=no" in conn_str

    def test_missing_pyodbc_friendly_error_with_fallback_hint(self):
        """D2+S2: pyodbc отсутствует → ImportError с подсказкой pip install
        pyodbc И fallback-подсказкой pymssql (сырой ModuleNotFoundError
        диалекта не должен доходить до пользователя)."""
        import app.data.db_connectors as dc

        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name == "pyodbc":
                    raise ModuleNotFoundError("No module named 'pyodbc'")
                return None

        spec = get_connector("mssql")
        url, connect_args = build_server_url(
            spec, host="h", port=1433, database="d",
            username="u", password="pw",
        )
        monkey_sys_path = patch.dict(sys.modules, {"pyodbc": None})
        with monkey_sys_path, patch("sys.meta_path", [_Blocker(), *sys.meta_path]):
            with pytest.raises(ImportError) as ei:
                dc.open_server_engine(spec, url, connect_args)
        msg = str(ei.value)
        assert "pyodbc" in msg
        assert "pymssql" in msg  # S2: fallback упомянут в подсказке

    def test_missing_pymysql_friendly_error(self):
        """D2 для MySQL: pymysql отсутствует → ImportError с pip-подсказкой."""
        import app.data.db_connectors as dc

        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name == "pymysql":
                    raise ModuleNotFoundError("No module named 'pymysql'")
                return None

        spec = get_connector("mysql")
        url, connect_args = build_server_url(
            spec, host="h", port=3306, database="d",
            username="u", password="pw",
        )
        with patch.dict("sys.modules", {"pymysql": None}), \
                patch("sys.meta_path", [_Blocker(), *sys.meta_path]):
            with pytest.raises(ImportError) as ei:
                dc.open_server_engine(spec, url, connect_args)
        msg = str(ei.value)
        assert "PyMySQL" in msg
        assert "cryptography" in msg

    def test_module_importable_without_pyodbc_pymysql(self):
        """Импорт-безопасность (паттерн TestImportSafety): реестр читается
        в процессе БЕЗ pyodbc/pymysql (guarded-импорты, реестр не падает)."""
        code = (
            "import sys\n"
            "sys.modules['pyodbc'] = None\n"
            "sys.modules['pymysql'] = None\n"
            "sys.modules['pymssql'] = None\n"  # isolate the optional fallback too
            "import app.data.db_connectors as dc\n"
            "assert dc.pyodbc is None and dc.pymssql is None\n"
            "spec = dc.get_connector('mssql')\n"
            "assert spec.fallback_pip_package == 'pymssql'\n"
            "assert dc.get_connector('mysql').pip_package == 'PyMySQL cryptography'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "OK" in result.stdout
