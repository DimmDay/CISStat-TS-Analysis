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
