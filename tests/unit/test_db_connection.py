"""
Unit-тесты для init_db_connection — подключение к базам данных.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.13).

UPLOAD-DB-1 (spec_database_plan.md, фаза A — коннекторное ядро):
- init_db_connection делегирует реестру коннекторов app/data/db_connectors.py;
- фикс D1 (аудит UPLOAD-DB-AUDIT-1): контрольный запрос выполняется строго
  через sqlalchemy.text() — SQLAlchemy 2.0 (пин >=2.0.0) отклоняет сырые
  строки (ArgumentError), из-за чего «Тест» PostgreSQL в legacy-прототипе
  падал на ровном месте;
- контракт «неподдерживаемый тип БД» изменён по DoD плана: None → ValueError.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from app.data.file_loader import init_db_connection

def _assert_test_query_is_textclause(mock_conn) -> None:
    """D1: контрольный запрос к БД должен быть TextClause, а не сырой строкой."""
    assert mock_conn.execute.call_count == 1, (
        "Контрольный запрос должен выполняться ровно один раз"
    )
    sent = mock_conn.execute.call_args[0][0]
    assert isinstance(sent, __import__("sqlalchemy").sql.elements.TextClause), (
        f"D1: контрольный запрос должен быть text(), получен {type(sent).__name__}"
    )
    assert sent.text == "SELECT 1"


class TestInitDbConnection:
    """Тесты для функции init_db_connection (делегирование реестру коннекторов)."""

    @patch('app.data.db_connectors.create_engine')
    def test_postgresql_success(self, mock_create_engine):
        """Успешное подключение к PostgreSQL; контрольный запрос — text() (D1)."""
        # Правильная настройка mock для контекстного менеджера
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        result = init_db_connection(
            db_type="PostgreSQL",
            host="localhost",
            port=5432,
            user="test_user",
            password="test_pass",
            db_name="test_db"
        )

        assert result == mock_engine
        mock_create_engine.assert_called_once()
        _assert_test_query_is_textclause(mock_conn)

    @patch('app.data.db_connectors.clickhouse_connect')
    def test_clickhouse_success(self, mock_ch_connect):
        """Успешное подключение к ClickHouse."""
        mock_client = Mock()
        mock_ch_connect.get_client.return_value = mock_client

        result = init_db_connection(
            db_type="ClickHouse",
            host="localhost",
            port=8123,
            user="test_user",
            password="test_pass",
            db_name="test_db"
        )

        assert result == mock_client
        mock_ch_connect.get_client.assert_called_once()
        mock_client.ping.assert_called_once()

    def test_invalid_db_type(self):
        """Невалидный тип БД → ValueError (DoD UPLOAD-DB-1: unsupported → ValueError)."""
        with pytest.raises(ValueError, match="Неподдерживаемый тип БД"):
            init_db_connection(
                db_type="Oracle",  # вне утверждённой матрицы 6 СУБД
                host="localhost",
                port=1521,
                user="test_user",
                password="test_pass",
                db_name="test_db"
            )

    @patch('app.data.db_connectors.create_engine')
    def test_postgresql_connection_error(self, mock_create_engine):
        """Ошибка подключения к PostgreSQL."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Connection refused")
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        with pytest.raises(ConnectionError, match="Не удалось подключиться к PostgreSQL"):
            init_db_connection(
                db_type="PostgreSQL",
                host="localhost",
                port=5432,
                user="test_user",
                password="test_pass",
                db_name="test_db"
            )

    @patch('app.data.db_connectors.clickhouse_connect')
    def test_clickhouse_connection_error(self, mock_ch_connect):
        """Ошибка подключения к ClickHouse."""
        mock_client = Mock()
        mock_client.ping.side_effect = Exception("Connection refused")
        mock_ch_connect.get_client.return_value = mock_client

        with pytest.raises(ConnectionError, match="Не удалось подключиться к ClickHouse"):
            init_db_connection(
                db_type="ClickHouse",
                host="localhost",
                port=8123,
                user="test_user",
                password="test_pass",
                db_name="test_db"
            )

