# Эксперименты UPLOAD-DB-7 (проект решения до кода):
# E1 — str(url)/render_as_string маскирование пароля (текущая Фаза A, mssql)
# E2 — что реально получает pyodbc.connect: URL-пароль vs connect_args-kwargs
# E3 — спецсимволы пароля: экранирование SQLAlchemy (URL-путь) и ODBC-braces
# E4 — ImportError при отсутствии pyodbc на create_engine/connect
import sys
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

print("sqlalchemy", __import__("sqlalchemy").__version__)

# ---------- E1: текущая Фаза A — пароль в URL-объекте ----------
url = URL.create(
    "mssql+pyodbc",
    username="u", password="s3cret-pw", host="h", port=1433, database="d",
    query={"driver": "ODBC Driver 18 for SQL Server", "Encrypt": "no"},
)
print("E1 str(url):", str(url))
print("E1 hide_password=False:", url.render_as_string(hide_password=False))
print("E1 url.password:", url.password)
print("E1 repr(url):", repr(url))

# ---------- E2/E3: pyodbc.connect — что приходит (URL-путь vs kwargs) ----------
captured = {}
fake_pyodbc = MagicMock()
fake_pyodbc.version = "5.2.0"
fake_pyodbc.connect.side_effect = (
    lambda *a, **kw: captured.update(args=a, kwargs=kw) or MagicMock()
)
sys.modules["pyodbc"] = fake_pyodbc

special_password = "p@ss;w0rd}x"

# Вариант A (текущая Фаза A): пароль в URL-объекте
url_a = URL.create(
    "mssql+pyodbc",
    username="u", password=special_password, host="h", port=1433, database="d",
    query={"driver": "ODBC Driver 18 for SQL Server", "Encrypt": "no"},
)
eng_a = create_engine(url_a, connect_args={"timeout": 10})
try:
    eng_a.connect()
except Exception as e:
    print("E2 variantA connect err (expected, mock):", type(e).__name__)
print("E2 variantA conn_str:", captured.get("args"))
print("E2 variantA kwargs:", captured.get("kwargs"))

# Вариант B (пересмотр): БЕЗ пароля в URL, PWD через connect_args (braces)
def odbc_quote(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"

captured.clear()
url_b = URL.create(
    "mssql+pyodbc",
    username="u", host="h", port=1433, database="d",
    query={"driver": "ODBC Driver 18 for SQL Server", "Encrypt": "no"},
)
eng_b = create_engine(url_b, connect_args={"PWD": odbc_quote(special_password), "timeout": 10})
try:
    eng_b.connect()
except Exception as e:
    print("E2 variantB connect err (expected, mock):", type(e).__name__)
print("E2 variantB conn_str:", captured.get("args"))
print("E2 variantB kwargs:", captured.get("kwargs"))

# ---------- E4: pyodbc отсутствует ----------
del sys.modules["pyodbc"]

import importlib
import sqlalchemy.dialects.mssql.pyodbc as mspy
importlib.reload(mspy)  # сброс lazyproperty dbapi

class Blocker:
    def find_module(self, name, path=None):
        return self if name == "pyodbc" else None
    def load_module(self, name):
        raise ImportError("blocked")

sys.meta_path.insert(0, Blocker())
try:
    try:
        eng_c = create_engine("mssql+pyodbc://u@h:1433/d?driver=ODBC+Driver+18+for+SQL+Server")
        print("E4 create_engine OK without pyodbc (lazy)")
        eng_c.connect()
        print("E4 connect OK?!")
    except Exception as e:
        print("E4 err type:", type(e).__module__ + "." + type(e).__name__)
        print("E4 msg:", str(e)[:200])
finally:
    sys.meta_path.pop(0)
