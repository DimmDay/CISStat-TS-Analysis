"""
Безопасность ядра БД-загрузки — UPLOAD-DB-2 (spec_database_plan.md, фаза A).

Закрывает находки аудита UPLOAD-DB-AUDIT-1 ДО открытия эндпоинтов БД в общем
контуре (жёсткое ограничение плана: UPLOAD-DB-2 обязателен до UPLOAD-DB-4):

- D6 read-only guard: разрешены только запросы чтения (SELECT / WITH),
  запрещены мультистейтменты, DML/DDL-конструкции, блокировки строк и
  известные опасные функции. Guard лексический (эвристический) — остаточный
  риск (произвольные функции чтения с побочными эффектами) закрывается
  развёртыванием с read-only пользователем БД (риски RP4, UPLOAD-DB-9).
- D6 row_limit + chunksize-стриминг: принудительный потолок строк
  (env UPLOAD_DB_ROW_LIMIT, дефолт 1 000 000 — скоуп-решение S4) поверх
  опционального лимита вызывающего; чтение SQLAlchemy — через чанки.
- D4 маскирование секретов: централизованная функция mask_secrets —
  прямые замены + паттерны password=/pwd= и scheme://user:pass@.
- D5 host-whitelist: env UPLOAD_DB_HOST_WHITELIST (список хостов/CIDR через
  запятую; «*» или пусто — off, скоуп-решение S5: off в песочнице).
- S4 таймауты: env UPLOAD_DB_CONNECT_TIMEOUT (10с) / UPLOAD_DB_QUERY_TIMEOUT
  (60с) — резолюция в db_connectors.get_db_timeouts.

Модуль НЕ импортирует streamlit — stateless (Правило 14); безопасно
импортируется без sqlalchemy (образ apps/api).
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Tuple

import pandas as pd

try:
    from sqlalchemy import text as _sa_text
    from sqlalchemy.engine import Engine as _SaEngine
except ImportError:  # pragma: no cover — средовой класс (образ apps/api)
    _sa_text = None
    _SaEngine = None

logger = logging.getLogger(__name__)

# ───────────────────────────── Константы (S4) ───────────────────────────────

DEFAULT_ROW_LIMIT = 1_000_000      # env UPLOAD_DB_ROW_LIMIT (скоуп-решение S4)
DEFAULT_CHUNKSIZE = 50_000         # env UPLOAD_DB_CHUNKSIZE (размер чанка стриминга)


class DbQueryRejected(ValueError):
    """SQL-запрос отклонён read-only guard'ом (D6)."""


class HostNotAllowed(ValueError):
    """Хост вне белого списка UPLOAD_DB_HOST_WHITELIST (D5/SSRF)."""


class DbLoadError(RuntimeError):
    """Ошибка выполнения запроса загрузки (сообщение маскируется — D4)."""


# ─────────────────────── Read-only guard (D6) ────────────────────────────────

# DML/DDL-конструкции, допустимые ВНУТРИ CTE PostgreSQL (WITH x AS (DELETE…))
# и потому не отсекаемые правилом первого ключевого слова. Отдельные
# операторы (COPY, VACUUM, EXEC, USE, LOAD, INSTALL и т.п.) отсекаются
# правилом первого ключевого слова (только SELECT/WITH).
_FORBIDDEN_KEYWORDS: Tuple[str, ...] = (
    "insert", "update", "delete", "merge", "truncate",
    "drop", "alter", "create", "grant", "revoke", "into",
)

# Блокировки строк делают выборку не-читающей (аренда соединения).
_ROWLOCK_RE = re.compile(
    r"\bfor\s+(?:update|share|key\s+share|no\s+key\s+update)\b"
)

# Известные опасные функции (DoS/админ-действия/доступ к ФС). Остаточный риск
# произвольных функций — на read-only пользователе БД (RP4, UPLOAD-DB-9).
_DANGEROUS_FN_RE = re.compile(
    r"\b(pg_sleep(?:_for|_until)?|pg_terminate_backend|pg_cancel_backend|"
    r"pg_reload_conf|pg_create_restore_point|pg_ls_dir|pg_read_(?:binary_)?file|"
    r"lo_import|lo_export|dblink\w*)\s*\("
)

_DOLLAR_TAG_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def _strip_sql_text(sql: str) -> str:
    """Вычищает литералы и комментарии конечным автоматом (для АНАЛИЗА).

    Однопроходный автомат устойчив к вложенности разделителей: кавычки внутри
    комментариев, комментарии внутри строк, удвоенные эскейпы ('', ""),
    dollar-кавычки PostgreSQL ($$…$$, $tag$…$tag$), [квадратные] и `обратные`
    кавычки-идентификаторы. Исходный SQL при этом НЕ изменяется — исполняется
    всегда оригинал.
    """
    out: list = []
    i, n = 0, len(sql)
    state = "code"
    dollar_tag = ""
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "-" and nxt == "-":
                state = "line_comment"; i += 2; out.append(" "); continue
            if ch == "/" and nxt == "*":
                state = "block_comment"; i += 2; out.append(" "); continue
            if ch == "'":
                state = "sq"; i += 1; out.append(" "); continue
            if ch == '"':
                state = "dq"; i += 1; out.append(" "); continue
            if ch == "`":
                state = "bt"; i += 1; out.append(" "); continue
            if ch == "[":
                state = "bracket"; i += 1; out.append(" "); continue
            if ch == "$":
                match = _DOLLAR_TAG_RE.match(sql, i)
                if match:
                    dollar_tag = match.group(0)
                    state = "dollar"
                    i += len(dollar_tag); out.append(" "); continue
            out.append(ch); i += 1; continue
        if state == "line_comment":
            if ch == "\n":
                state = "code"; out.append("\n")
            i += 1; continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"; i += 2; out.append(" "); continue
            if ch == "\n":
                out.append("\n")
            i += 1; continue
        if state == "sq":
            if ch == "'":
                if nxt == "'":
                    i += 2; continue
                state = "code"
            i += 1; continue
        if state == "dq":
            if ch == '"':
                if nxt == '"':
                    i += 2; continue
                state = "code"
            i += 1; continue
        if state == "bt":
            if ch == "`":
                state = "code"
            i += 1; continue
        if state == "bracket":
            if ch == "]":
                state = "code"
            i += 1; continue
        if state == "dollar":
            if sql.startswith(dollar_tag, i):
                state = "code"; i += len(dollar_tag); out.append(" "); continue
            if ch == "\n":
                out.append("\n")
            i += 1; continue
    return "".join(out)


def validate_readonly_sql(sql: Any) -> str:
    """Read-only guard (D6). Возвращает исходный SQL (trimmed) для исполнения.

    Правила:
      1) непустой единственный стейтмент (хвостовые «;» допустимы);
      2) первое ключевое слово — только SELECT или WITH;
      3) отсутствие DML/DDL-конструкций (в т.ч. внутри CTE);
      4) отсутствие блокировок строк (FOR UPDATE / FOR SHARE);
      5) отсутствие известных опасных функций.

    Raises:
        DbQueryRejected: нарушение любого правила.
    """
    if sql is None or not str(sql).strip():
        raise DbQueryRejected("Пустой SQL-запрос")
    raw = str(sql).strip()
    stripped = _strip_sql_text(raw).strip()
    core = stripped.rstrip(";").rstrip()
    if not core:
        raise DbQueryRejected("Пустой SQL-запрос")
    if ";" in core:
        raise DbQueryRejected(
            "Мультистейтмент запрещён: разрешён ровно один запрос чтения"
        )
    first_kw = re.match(r"[A-Za-z_]+", core)
    if not first_kw or first_kw.group(0).upper() not in ("SELECT", "WITH"):
        raise DbQueryRejected(
            "Разрешены только запросы чтения (SELECT / WITH)"
        )
    lowered = core.lower()
    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", lowered):
            raise DbQueryRejected(
                f"Запрещённая конструкция «{kw.upper()}»: доступ к БД только на чтение"
            )
    if _ROWLOCK_RE.search(lowered):
        raise DbQueryRejected(
            "Запрещена блокировка строк (FOR UPDATE / FOR SHARE)"
        )
    fn_match = _DANGEROUS_FN_RE.search(lowered)
    if fn_match:
        raise DbQueryRejected(
            f"Запрещённая функция «{fn_match.group(1)}»: доступ к БД только на чтение"
        )
    return raw


# ─────────────────────── Пределы чтения (D6, S4) ─────────────────────────────

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_row_limit() -> int:
    """Принудительный потолок строк (env UPLOAD_DB_ROW_LIMIT, дефолт 1 000 000)."""
    return _env_int("UPLOAD_DB_ROW_LIMIT", DEFAULT_ROW_LIMIT)


def get_chunksize() -> int:
    """Размер чанка стриминга (env UPLOAD_DB_CHUNKSIZE, дефолт 50 000)."""
    return _env_int("UPLOAD_DB_CHUNKSIZE", DEFAULT_CHUNKSIZE)


# ─────────────────────── Host-whitelist (D5, S5) ─────────────────────────────

def get_host_whitelist() -> Optional[list]:
    """Разобранный белый список хостов/CIDR; None — guard выключен (S5: off)."""
    raw = os.getenv("UPLOAD_DB_HOST_WHITELIST", "").strip()
    if not raw or raw == "*":
        return None
    return [entry.strip().lower() for entry in raw.split(",") if entry.strip()]


def validate_host_allowed(host: Any) -> None:
    """Проверка хоста по белому списку (D5/SSRF). Пустой host — решение whitelist.

    Raises:
        HostNotAllowed: хост вне списка.
    """
    whitelist = get_host_whitelist()
    if whitelist is None:
        return
    host_str = str(host).strip().lower() if host is not None else ""
    if not host_str:
        return
    for entry in whitelist:
        if entry == host_str:
            return
        if "/" in entry:
            try:
                if ipaddress.ip_address(host_str) in ipaddress.ip_network(entry, strict=False):
                    return
            except ValueError:
                continue
    raise HostNotAllowed(
        f"Хост {host!r} не входит в белый список UPLOAD_DB_HOST_WHITELIST"
    )


# ───────────────────── Маскирование секретов (D4) ────────────────────────────

_SECRET_KV_RE = re.compile(
    r"(?i)\b(password|pwd|pass)\s*([=:])\s*(\"[^\"]*\"|'[^']*'|[^\s;&,]+)"
)
_URL_CREDS_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*(?:\+[a-z0-9]+)?://)([^:/\s@]*):([^@\s/]+)@"
)


def mask_secrets(message: Any, *secrets: Any) -> str:
    """Централизованное маскирование секретов в сообщениях об ошибках (D4).

    Порядок: прямые замены переданных секретов → паттерн password=/pwd= →
    паттерн scheme://user:password@ (пользователь сохраняется, пароль — ****).
    """
    out = str(message)
    for secret in secrets:
        if secret:
            out = out.replace(str(secret), "****")
    out = _SECRET_KV_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}****", out)
    out = _URL_CREDS_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}:****@", out)
    return out


# ─────────────────────── Загрузка с лимитом (D6) ─────────────────────────────

@dataclass
class DbLoadResult:
    """Результат load_db_dataframe: контракты Phase B (UPLOAD-DB-4)."""

    dataframe: pd.DataFrame
    rows_loaded: int
    truncated: bool
    row_limit: int


def _is_sqlalchemy_engine(conn_obj: Any) -> bool:
    if _SaEngine is not None:
        return isinstance(conn_obj, _SaEngine)
    return False


def _load_sqlalchemy(conn_obj: Any, sql: str, limit: int, chunksize: int) -> pd.DataFrame:
    """Чтение через SQLAlchemy: chunksize-стриминг + клиентская обрезка."""
    frames: list = []
    total = 0
    truncated = False
    reader = pd.read_sql(_sa_text(sql), conn_obj, chunksize=chunksize)
    for chunk in reader:
        frames.append(chunk)
        total += len(chunk)
        if total >= limit:
            # Точность флага: чанк мог стать последним ровно на лимите.
            extra = next(reader, None)
            truncated = extra is not None and len(extra) > 0
            break
    if not frames:
        # Пустой результат: повторное чтение без чанков ради колонок.
        df = pd.read_sql(_sa_text(sql), conn_obj).head(0)
    else:
        df = pd.concat(frames, ignore_index=True)
    if total > limit:
        df = df.iloc[:limit]
        truncated = True
    return df, truncated


def _load_clickhouse(conn_obj: Any, sql: str, limit: int) -> pd.DataFrame:
    """Нативный ClickHouse: серверный потолок max_result_rows + break."""
    # One sentinel row distinguishes a natural exact-size result from a
    # server-truncated one. Only the requested limit reaches the dataset.
    settings = {"max_result_rows": limit + 1, "result_overflow_mode": "break"}
    df = conn_obj.query_df(sql, settings=settings)
    truncated = len(df) > limit
    if truncated:
        df = df.iloc[:limit]
    return df, truncated


def load_db_dataframe(
    conn_obj: Any,
    sql: str,
    *,
    row_limit: Optional[int] = None,
    chunksize: Optional[int] = None,
    secrets: Iterable[Any] = (),
) -> DbLoadResult:
    """Безопасная загрузка выборки: guard → потолок → стриминг → маскирование.

    Args:
        conn_obj: SQLAlchemy Engine/Connection или нативный клиент ClickHouse
                  (детект по наличию query_df — как в legacy-прототипе).
        sql: SQL-запрос чтения (проходит validate_readonly_sql).
        row_limit: желаемый лимит строк; ЖЁСТКО ограничен env-потолком
                   UPLOAD_DB_ROW_LIMIT (запрос выше потолка обрезается).
        chunksize: размер чанка стриминга (None → env UPLOAD_DB_CHUNKSIZE).
        secrets: секреты для маскирования в сообщениях об ошибках (D4).

    Returns:
        DbLoadResult(dataframe, rows_loaded, truncated, row_limit)

    Raises:
        DbQueryRejected: read-only guard отклонил запрос.
        DbLoadError: ошибка исполнения (сообщение маскировано — D4).
    """
    clean_sql = validate_readonly_sql(sql)
    limit = get_row_limit()
    if row_limit is not None:
        limit = max(1, min(int(row_limit), limit))
    chunk = int(chunksize) if chunksize else get_chunksize()
    secrets_tuple = tuple(s for s in secrets if s)

    try:
        if hasattr(conn_obj, "query_df") and not _is_sqlalchemy_engine(conn_obj):
            df, truncated = _load_clickhouse(conn_obj, clean_sql, limit)
        else:
            df, truncated = _load_sqlalchemy(conn_obj, clean_sql, limit, chunk)
    except (DbQueryRejected, DbLoadError):
        raise
    except Exception as exc:
        logger.error("DB load failed: %s", mask_secrets(exc, *secrets_tuple))
        raise DbLoadError(
            mask_secrets(f"Ошибка выполнения запроса к БД: {exc}", *secrets_tuple)
        ) from exc

    df = df.reset_index(drop=True)
    return DbLoadResult(
        dataframe=df,
        rows_loaded=int(len(df)),
        truncated=bool(truncated),
        row_limit=limit,
    )
