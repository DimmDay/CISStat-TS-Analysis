"""
Unit-тесты для init_db_connection — подключение к базам данных.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.13).
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.data.loader import init_db_connection


class TestInitDbConnection:
    """Тесты для функции init_db_connection."""

    @patch('app.data.loader.create_engine')
    def test_postgresql_success(self, mock_create_engine):
        """Успешное подключение к PostgreSQL."""
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
        mock_conn.execute.assert_called_once_with("SELECT 1")

    @patch('app.data.loader.clickhouse_connect')
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
        """Невалидный тип БД должен вернуть None."""
        result = init_db_connection(
            db_type="MySQL",  # не поддерживается
            host="localhost",
            port=3306,
            user="test_user",
            password="test_pass",
            db_name="test_db"
        )
        
        assert result is None

    @patch('app.data.loader.create_engine')
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

    @patch('app.data.loader.clickhouse_connect')
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

    @patch('app.data.loader.create_engine', None)
    def test_postgresql_missing_driver(self):
        """Отсутствие драйвера psycopg2."""
        with pytest.raises(ImportError):
            init_db_connection(
                db_type="PostgreSQL",
                host="localhost",
                port=5432,
                user="test_user",
                password="test_pass",
                db_name="test_db"
            )

    @patch('app.data.loader.clickhouse_connect', None)
    def test_clickhouse_missing_driver(self):
        """Отсутствие драйвера clickhouse_connect."""
        with pytest.raises(ImportError):
            init_db_connection(
                db_type="ClickHouse",
                host="localhost",
                port=8123,
                user="test_user",
                password="test_pass",
                db_name="test_db"
            )