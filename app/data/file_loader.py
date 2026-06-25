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
        try:
            uploaded_file.seek(0)
            content = uploaded_file.read().decode('utf-8-sig')
            data = json.loads(content)
            
            # Проверка на JSON-stat 2.0
            if isinstance(data, dict) and data.get("version") == "2.0":
                df = parse_jsonstat(data)
            elif isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    df = pd.json_normalize(data)
                elif len(data) > 0:
                    df = pd.DataFrame({uploaded_file.name.rsplit('.', 1)[0]: data})
                else:
                    df = pd.DataFrame()
            elif isinstance(data, dict):
                df = pd.DataFrame([data])
            else:
                df = pd.DataFrame([{"value": str(data)}])
        except json.JSONDecodeError as je:
            raise ValueError(f"❌ Ошибка парсинга JSON: {je}")
        except Exception as e:
            raise ValueError(f"❌ Ошибка обработки JSON: {e}")
    else:
        raise ValueError(f"Формат .{ext} не поддерживается.")

    if df.empty:
        raise ValueError("Файл пуст или не содержит табличных данных.")

    return df, ext


def parse_jsonstat(data: dict) -> pd.DataFrame:
    """
    Парсит JSON-stat 2.0 формат в плоский DataFrame.
    
    Args:
        data: Словарь с JSON-stat 2.0 структурой
    
    Returns:
        DataFrame с распарсенными данными
    
    Raises:
        ValueError: Если данные не валидны или пусты
    """
    if not (isinstance(data, dict) and data.get("version") == "2.0" 
            and "value" in data and "dimension" in data):
        raise ValueError("Не является валидным JSON-stat 2.0")
    
    dimensions = data.get("dimension", {})
    dimension_ids = data.get("id", [])
    sizes = data.get("size", [])
    
    # Вычисление strides для линейной индексации
    strides = [1] * len(sizes)
    for j in range(len(sizes) - 2, -1, -1):
        strides[j] = strides[j + 1] * sizes[j + 1]
    
    # Построение карт категорий
    category_maps = {}
    for dim_id in dimension_ids:
        dim_info = dimensions.get(dim_id, {})
        category_info = dim_info.get("category", {})
        index_map = category_info.get("index", {})
        label_map = category_info.get("label", {})
        reverse_index = {v: k for k, v in index_map.items()}
        category_maps[dim_id] = {
            "reverse_index": reverse_index,
            "label": label_map
        }
    
    # Извлечение данных
    rows = []
    for key_str, value in data["value"].items():
        try:
            linear_idx = int(key_str)
            indices = []
            remaining = linear_idx
            for j, size in enumerate(sizes):
                if j == len(sizes) - 1:
                    indices.append(remaining)
                else:
                    idx = remaining // strides[j]
                    indices.append(idx)
                    remaining = remaining % strides[j]
            
            row = {}
            for j, dim_id in enumerate(dimension_ids):
                cat_info = category_maps.get(dim_id, {})
                reverse_index = cat_info.get("reverse_index", {})
                label_map = cat_info.get("label", {})
                cat_code = reverse_index.get(indices[j])
                row[dim_id] = label_map.get(cat_code, cat_code) if cat_code else None
            row["value"] = value
            rows.append(row)
        except (ValueError, KeyError):
            continue
    
    if not rows:
        raise ValueError("JSON-stat 2.0 не содержит валидных данных")
    
    return pd.DataFrame(rows)