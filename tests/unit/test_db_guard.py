"""
Unit-тесты безопасности ядра БД-загрузки — UPLOAD-DB-2 (spec_database_plan.md, фаза A).

Закрывает находки аудита UPLOAD-DB-AUDIT-1:
- D6: read-only guard (только SELECT/WITH, запрет мультистейтментов и
  DML/DDL-ключевых слов), принудительный row_limit (env UPLOAD_DB_ROW_LIMIT,
  дефолт 1 000 000, скоуп-решение S4) + chunksize-стриминг;
- D4: централизованное маскирование секретов в исключениях;
- D5: host-whitelist (env UPLOAD_DB_HOST_WHITELIST; off в песочнице — S5);
- D3: ssl-флаги по СУБД (PG sslmode, MySQL ssl, MSSQL
  Encrypt/TrustServerCertificate, CH secure/verify);
- D2: дружественная детекция отсутствия драйвера на слое DBAPI;
- S4: настраиваемые таймауты 10с/60с (env-переопределяемые).
"""
import os
import re
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import NoSuchModuleError

from app.data import db_connectors, db_guard
from app.data.db_guard import (
    DbLoadError,
    DbQueryRejected,
    HostNotAllowed,
    get_chunksize,
    get_row_limit,
    load_db_dataframe,
    mask_secrets,
    validate_host_allowed,
    validate_readonly_sql,
)
from app.data.file_loader import init_db_connection


def _make_sqlite_engine(tmp_path, rows: int = 25, name: str = "guard_test.db"):
    """Реальный SQLite-движок с таблицей t (id, val) из rows строк."""
    path = tmp_path / name
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, val REAL)"))
        conn.execute(text(
            "INSERT INTO t VALUES " + ",".join(f"({i}, {i * 1.5})" for i in range(rows))
        ))
    return engine


# ─────────────────────────── Read-only guard (D6) ───────────────────────────

class TestValidateReadonlySql:

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM t",
        "select id, val from t where id > 5",
        "  SELECT 1  ",
        "WITH x AS (SELECT id FROM t) SELECT * FROM x",
        "with x as (select 1) select * from x",
        "SELECT id FROM t ORDER BY id LIMIT 10",
        "-- комментарий\nSELECT 1",
        "/* блок */ SELECT 1",
        "SELECT 1;",                          # хвостовая точка с запятой
        "SELECT * FROM t WHERE name = 'delete me'",   # ключевое слово в литерале
        "SELECT created_at, updated_at, deleted_flag FROM t",  # подстроки идентификаторов
        "SELECT * FROM t FOR JSON PATH",      # форматирование результата — чтение
    ])
    def test_readonly_allowed(self, sql):
        assert validate_readonly_sql(sql) == sql.strip()

    @pytest.mark.parametrize("sql", [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET val = 0",
        "DELETE FROM t",
        "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN UPDATE SET val = 0",
        "TRUNCATE TABLE t",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN x INT",
        "CREATE TABLE x (id INT)",
        "GRANT ALL ON t TO PUBLIC",
        "REVOKE ALL ON t FROM PUBLIC",
        "SELECT * INTO new_t FROM t",                        # SELECT INTO — DDL-подобная запись
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",  # DML внутри CTE (PG)
        "WITH x AS (INSERT INTO t VALUES (1)) SELECT * FROM x",
        "WITH x AS (UPDATE t SET val = 0) SELECT * FROM x",
        "SELECT 1; DROP TABLE t",                            # мультистейтмент
        "SELECT 1;; DROP TABLE t",
        "SELECT pg_sleep(100)",                              # опасные функции (DoS)
        "SELECT pg_terminate_backend(123)",
        "SELECT * FROM t FOR UPDATE",                        # блокировка строк
        "SELECT * FROM t FOR SHARE",
        "UPDATE",                                            # не-чтение как первый токен
        "EXEC my_proc",
        "CALL my_proc",
        "COPY t TO '/tmp/x.csv'",
        "/* ' */ ; DROP TABLE t /* ' */",                    # скрытие в комментарии
        "SELECT * FROM t WHERE s = 'a--b' AND 1=1; DROP TABLE x",  # -- внутри литерала
        "",                                                  # пустой запрос
        "   ",
    ])
    def test_rejected(self, sql):
        with pytest.raises(DbQueryRejected):
            validate_readonly_sql(sql)

    def test_none_rejected(self):
        with pytest.raises(DbQueryRejected):
            validate_readonly_sql(None)


# ─────────────────────── row_limit / chunksize (D6, S4) ─────────────────────

class TestEnvLimits:

    def test_row_limit_default_1m(self, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        assert get_row_limit() == 1_000_000

    def test_row_limit_env_override(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "100")
        assert get_row_limit() == 100

    def test_row_limit_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "not-a-number")
        assert get_row_limit() == 1_000_000

    def test_row_limit_negative_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "-5")
        assert get_row_limit() == 1_000_000

    def test_chunksize_default_and_env(self, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_CHUNKSIZE", raising=False)
        assert get_chunksize() == 50_000
        monkeypatch.setenv("UPLOAD_DB_CHUNKSIZE", "7")
        assert get_chunksize() == 7


class TestLoadDbDataFrame:
    """row_limit + chunksize-стриминг на реальном SQLite-движке (без сервисов)."""

    def test_full_load(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        engine = _make_sqlite_engine(tmp_path)
        result = load_db_dataframe(engine, "SELECT * FROM t")
        assert result.rows_loaded == 25
        assert result.truncated is False
        assert result.row_limit == 1_000_000
        assert list(result.dataframe.columns) == ["id", "val"]

    def test_truncated_by_param(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        engine = _make_sqlite_engine(tmp_path)
        result = load_db_dataframe(engine, "SELECT * FROM t", row_limit=10)
        assert result.rows_loaded == 10
        assert result.truncated is True
        assert len(result.dataframe) == 10

    def test_param_limit_capped_by_env(self, tmp_path, monkeypatch):
        """Запрошенный лимит НЕ может превысить env-потолок (принудительный)."""
        monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "15")
        engine = _make_sqlite_engine(tmp_path)
        result = load_db_dataframe(engine, "SELECT * FROM t", row_limit=100)
        assert result.rows_loaded == 15
        assert result.row_limit == 15

    def test_chunked_equals_full(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        engine = _make_sqlite_engine(tmp_path)
        chunked = load_db_dataframe(engine, "SELECT * FROM t", chunksize=7)
        assert chunked.rows_loaded == 25
        assert chunked.truncated is False
        assert list(chunked.dataframe["id"]) == list(range(25))  # порядок сохранён

    def test_empty_result_keeps_columns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        engine = _make_sqlite_engine(tmp_path)
        result = load_db_dataframe(engine, "SELECT * FROM t WHERE id > 1000")
        assert result.rows_loaded == 0
        assert list(result.dataframe.columns) == ["id", "val"]
        assert result.truncated is False

    def test_dml_rejected_before_execution(self, tmp_path):
        engine = _make_sqlite_engine(tmp_path)
        with pytest.raises(DbQueryRejected):
            load_db_dataframe(engine, "DELETE FROM t")

    def test_driver_error_masked(self, tmp_path, monkeypatch):
        """D4: секреты не всплывают в исключениях загрузки."""
        engine = _make_sqlite_engine(tmp_path)

        def _boom(*args, **kwargs):
            raise RuntimeError("connect failed: user=analyst password=s3cret-pw host=db.corp")

        monkeypatch.setattr(db_guard.pd, "read_sql", _boom)
        with pytest.raises(DbLoadError) as ei:
            load_db_dataframe(engine, "SELECT * FROM t", secrets=("s3cret-pw",))
        msg = str(ei.value)
        assert "s3cret-pw" not in msg
        assert "****" in msg

    def test_clickhouse_native_settings(self, monkeypatch):
        """Нативный ClickHouse: серверный потолок max_result_rows + break."""
        monkeypatch.delenv("UPLOAD_DB_ROW_LIMIT", raising=False)
        client = MagicMock(spec=["query_df", "query", "close", "ping"])
        client.query_df.return_value = pd.DataFrame({"a": range(100)})
        result = load_db_dataframe(client, "SELECT * FROM t", row_limit=30)
        client.query_df.assert_called_once()
        _, kwargs = client.query_df.call_args
        # UPLOAD-DB-FIX: one extra row proves truncation at the boundary;
        # the consumer still receives exactly 30 rows.
        assert kwargs["settings"]["max_result_rows"] == 31
        assert kwargs["settings"]["result_overflow_mode"] == "break"
        assert result.rows_loaded == 30
        assert result.truncated is True


# ───────────────────────── Маскирование секретов (D4) ───────────────────────

class TestMaskSecrets:

    def test_direct_replacement(self):
        out = mask_secrets("ошибка у пользователя analyst:s3cret-pw@db", "s3cret-pw")
        assert "s3cret-pw" not in out and "****" in out

    def test_password_kv_pattern(self):
        out = mask_secrets("FATAL: password=leaked-pw at host", )
        assert "leaked-pw" not in out

    def test_url_credentials_pattern(self):
        out = mask_secrets("cannot connect to postgresql://analyst:topsecret@db:5432/dw")
        assert "topsecret" not in out
        assert "analyst" in out  # пользователь НЕ маскируется
        assert "db:5432/dw" in out

    def test_empty_secrets_noop(self):
        assert mask_secrets("text", "", None) == "text"

    def test_password_keycase_insensitive(self):
        out = mask_secrets("PWD=Abc123!@ host")
        assert "Abc123!@" not in out


# ───────────────────────────── Whitelist (D5, S5) ───────────────────────────

class TestHostWhitelist:

    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("UPLOAD_DB_HOST_WHITELIST", raising=False)
        assert db_guard.get_host_whitelist() is None
        validate_host_allowed("any-host.example")  # не raising

    def test_star_disables(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "*")
        validate_host_allowed("any-host.example")  # не raising

    def test_hostname_match(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "db1.corp,db2.corp")
        validate_host_allowed("DB1.CORP")  # case-insensitive, не raising

    def test_cidr_match(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "10.0.0.0/8,192.168.1.1")
        validate_host_allowed("10.42.0.7")      # не raising
        validate_host_allowed("192.168.1.1")    # не raising

    def test_violation_raises(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "db1.corp,10.0.0.0/8")
        with pytest.raises(HostNotAllowed, match="не входит в белый список"):
            validate_host_allowed("evil.corp")
        with pytest.raises(HostNotAllowed):
            validate_host_allowed("11.0.0.1")

    def test_init_db_connection_enforces_whitelist(self, monkeypatch):
        """D5: guard срабатывает ДО попытки открытия соединения (SSRF)."""
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "db1.corp")
        with patch("app.data.db_connectors.create_engine") as mock_ce:
            with pytest.raises(HostNotAllowed):
                init_db_connection("PostgreSQL", "evil.corp", 5432, "u", "p", "d")
            mock_ce.assert_not_called()  # соединение даже не открывалось


# ──────────────────── ssl-флаги и таймауты (D3, S4) ─────────────────────────

class TestSslFlags:

    @pytest.fixture(autouse=True)
    def _deterministic_mssql_driver(self, monkeypatch):
        """UPLOAD-DB-7: авто-резолюция mssql-драйвера детерминированна в тестах
        D3 (pyodbc — основной по S2; fallback-ветка тестируется в
        test_db_connectors.py::TestUploadDb7MssqlFallback)."""
        monkeypatch.setattr(db_connectors, "pyodbc", object())

    def test_pg_sslmode_explicit(self):
        """D3: sslmode задаётся явно: True → require, False → disable."""
        spec = db_connectors.get_connector("postgresql")
        _, ca_off = db_connectors.build_server_url(
            spec, host="h", port=5432, database="d", username="u", password="p", ssl=False)
        _, ca_on = db_connectors.build_server_url(
            spec, host="h", port=5432, database="d", username="u", password="p", ssl=True)
        assert ca_off["sslmode"] == "disable"
        assert ca_on["sslmode"] == "require"

    def test_mysql_ssl(self):
        spec = db_connectors.get_connector("mysql")
        _, ca_off = db_connectors.build_server_url(
            spec, host="h", port=3306, database="d", username="u", password="p", ssl=False)
        _, ca_on = db_connectors.build_server_url(
            spec, host="h", port=3306, database="d", username="u", password="p", ssl=True)
        assert ca_off["ssl_disabled"] is True
        assert ca_on["ssl_verify_cert"] is True
        assert "ssl_disabled" not in ca_on

    def test_mssql_encrypt(self):
        spec = db_connectors.get_connector("mssql")
        url_off, _ = db_connectors.build_server_url(
            spec, host="h", port=1433, database="d", username="u", password="p", ssl=False)
        url_on, _ = db_connectors.build_server_url(
            spec, host="h", port=1433, database="d", username="u", password="p", ssl=True)
        assert url_off.query["Encrypt"] == "no"
        assert url_on.query["Encrypt"] == "yes"
        assert url_on.query["TrustServerCertificate"] == "no"

    def test_clickhouse_secure_verify(self):
        spec = db_connectors.get_connector("clickhouse")
        with patch("app.data.db_connectors.clickhouse_connect") as mock_mod:
            client = Mock()
            mock_mod.get_client.return_value = client
            db_connectors.open_clickhouse(
                spec, host="h", port=8123, username="u", password="p",
                database="d", ssl=True)
            _, kwargs = mock_mod.get_client.call_args
            assert kwargs["secure"] is True
            assert kwargs["verify"] is True


class TestTimeouts:

    def test_env_timeouts_reach_connect_args(self, monkeypatch):
        """S4: таймауты 10с/60с env-переопределяемые."""
        monkeypatch.setenv("UPLOAD_DB_CONNECT_TIMEOUT", "3")
        monkeypatch.setenv("UPLOAD_DB_QUERY_TIMEOUT", "7")
        spec = db_connectors.get_connector("postgresql")
        _, ca = db_connectors.build_server_url(
            spec, host="h", port=5432, database="d", username="u", password="p")
        assert ca["connect_timeout"] == 3
        assert "statement_timeout=7000" in ca["options"]

    def test_env_timeouts_clickhouse(self, monkeypatch):
        monkeypatch.setenv("UPLOAD_DB_CONNECT_TIMEOUT", "4")
        monkeypatch.setenv("UPLOAD_DB_QUERY_TIMEOUT", "9")
        spec = db_connectors.get_connector("clickhouse")
        with patch("app.data.db_connectors.clickhouse_connect") as mock_mod:
            mock_mod.get_client.return_value = Mock()
            db_connectors.open_clickhouse(
                spec, host="h", port=8123, username="u", password="p", database="d")
            _, kwargs = mock_mod.get_client.call_args
            assert kwargs["connect_timeout"] == 4
            assert kwargs["send_receive_timeout"] == 9


class TestDriverDetection:
    """D2: дружественная детекция отсутствия драйвера на слое DBAPI."""

    def test_nosuchmodule_becomes_friendly_importerror(self):
        spec = db_connectors.get_connector("postgresql")
        with patch("app.data.db_connectors.create_engine") as mock_ce:
            mock_ce.side_effect = NoSuchModuleError(
                "Can't load plugin: sqlalchemy.dialects:postgresql.psycopg")
            with pytest.raises(ImportError, match="psycopg"):
                db_connectors.open_server_engine(spec, Mock(), {})


class TestMaskedInitErrors:
    """init_db_connection: обёртка ошибок с централизованным маскированием."""

    def test_connection_error_masks_password(self):
        with patch("app.data.db_connectors.create_engine") as mock_ce:
            engine = MagicMock()
            conn = MagicMock()
            conn.execute.side_effect = RuntimeError("FATAL: password=s3cret-pw denied")
            engine.connect.return_value.__enter__.return_value = conn
            mock_ce.return_value = engine
            with pytest.raises(ConnectionError) as ei:
                init_db_connection(
                    "PostgreSQL", "h", 5432, "u", "s3cret-pw", "d")
            msg = str(ei.value)
            assert "Не удалось подключиться к PostgreSQL" in msg  # паритет legacy
            assert "s3cret-pw" not in msg                        # D4
            assert "****" in msg
