"""
Модуль загрузки данных из различных источников.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).
"""
import json
import logging
import pandas as pd
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Опциональные зависимости (драйверы БД)
# Импортируются на уровне модуля с защитой от отсутствия
try:
    from sqlalchemy import create_engine
except ImportError:
    create_engine = None
    logger.debug("sqlalchemy not installed — PostgreSQL support disabled")

try:
    import clickhouse_connect
except ImportError:
    clickhouse_connect = None
    logger.debug("clickhouse-connect not installed — ClickHouse support disabled")


def init_db_connection(
    db_type: str,
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str
) -> Optional[Any]:
    """
    Создаёт подключение к базе данных.
    
    Args:
        db_type: Тип БД ("PostgreSQL" или "ClickHouse")
        host: Хост сервера
        port: Порт
        user: Имя пользователя
        password: Пароль
        db_name: Имя базы данных
    
    Returns:
        Объект подключения (SQLAlchemy engine для PostgreSQL, 
        clickhouse_connect client для ClickHouse) или None при ошибке
    
    Raises:
        ImportError: Если драйвер БД не установлен
        ConnectionError: Если не удалось подключиться
    
    Note:
        Декоратор @st.cache_resource остаётся в UI-обёртке (app.py),
        а не в бизнес-функции, согласно правилу "бизнес-логика не импортирует streamlit".
    """
    try:
        if db_type == "PostgreSQL":
            if create_engine is None:
                raise ImportError("psycopg2-binary")
            
            url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"
            engine = create_engine(
                url,
                connect_args={"connect_timeout": 10, "options": "-c statement_timeout=60000"},
                pool_pre_ping=True,
                pool_recycle=300
            )
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            return engine
        
        elif db_type == "ClickHouse":
            if clickhouse_connect is None:
                raise ImportError("clickhouse-connect")
            
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=user,
                password=password,
                database=db_name,
                secure=False,
                verify=False,
                connect_timeout=10,
                send_receive_timeout=60
            )
            client.ping()
            return client
        
        else:
            logger.warning(f"Unsupported database type: {db_type}")
            return None
    
    except ImportError as e:
        logger.error(f"Missing database driver: {e}")
        raise
    except Exception as e:
        logger.error(f"DB Connection failed: {db_type}@{host}:{port}/{db_name} - {e}")
        raise ConnectionError(f"Не удалось подключиться к {db_type}")
    
def read_uploaded_file(uploaded_file) -> tuple[pd.DataFrame, str]:
    """
    Читает загруженный файл с автодетектом формата и заголовков.
    """
    if uploaded_file is None:
        raise ValueError("Файл не загружен")

    file_name = uploaded_file.name or "unknown.file"
    ext = file_name.split('.')[-1].lower()

    if ext == "csv":
        df = pd.read_csv(
            uploaded_file,
            sep=None,
            engine='python',
            encoding='utf-8-sig',
            on_bad_lines='skip',
            header=None
        )
        first_col_sample = df[0].head(10).astype(str)
        is_date_like = first_col_sample.str.contains(r'\d{4}[-/]\d{2}[-/]\d{2}', regex=True).mean() > 0.8
        if is_date_like:
            new_headers = ['date'] + [f'col_{i}' for i in range(1, len(df.columns))]
            df.columns = new_headers
        else:
            df.columns = [f'col_{i}' for i in range(len(df.columns))]
    elif ext in ["xlsx", "xls"]:
        df = pd.read_excel(uploaded_file)
        if isinstance(df.columns[0], (int, float)):
            df.columns = [f'col_{i}' for i in range(len(df.columns))]
    elif ext == "json":
        uploaded_file.seek(0)
        content = uploaded_file.read().decode('utf-8-sig')
        data = json.loads(content)
        df = pd.json_normalize(data) if isinstance(data, list) else pd.DataFrame([data])
    else:
        raise ValueError(f"Формат .{ext} не поддерживается.")

    if df.empty:
        raise ValueError("Файл пуст или не содержит табличных данных.")

    return df, ext