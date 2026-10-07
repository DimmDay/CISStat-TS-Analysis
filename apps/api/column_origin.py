"""Реестр происхождения колонок и каноническая область профилей качества
(spec_status_original_series.md, задача A, Task PROGR-24-ORIGIN-A).

Методологическое правило спеки: гейты качества данных (пропуски / выбросы /
регулярность / проверки «Валидации») применяются ОДИН РАЗ к каноническому
исходному ряду -- к загруженным колонкам и прочим исходно загруженным
предикторам. Колонки, порождённые остановками предобработки (разности
стационарности, сглаживание, декомпозиция, генерация признаков, флаги
коррекций), получают собственную downstream-обработку (остановка
«Генерация признаков», fold-safe бэктест) и НЕ возвращаются на более ранние
остановки общего контура качества: остановка ниже по течению не может
менять статус остановки выше, пайплайн остаётся направленным графом.

Дизайн (спека §Реализация):
  1. ЕДИНАЯ ТОЧКА регистрации: `register_derived_columns` сравнивает список
     колонок ДО и ПОСЛЕ apply -- происхождение НЕ угадывается по суффиксу
     имени. Вызывается во всех apply-эндпоинтах, добавляющих колонки.
  2. `canonical_columns(session)` -- область профилей «Пропусков»,
     «Выбросов», «Регулярности» и проверок «Валидации». Профиль по
     производным колонкам считается отдельно (derived_summary, вне статуса).
  3. Совместимость: старые сессии без реестра считают все колонки
     исходными (пустой реестр); set_dataset сбрасывает реестр.
  4. Реестр -- факультативные метаданные, а не истина в последней
     инстанции: устаревшая запись (колонка удалена мимо реестра) безвредна,
     т.к. область всегда пересекается с фактическими колонками датафрейма.

Модуль -- leaf-зависимость роутера сессии: не импортирует FastAPI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from apps.api.session_store import AnalysisSession


def register_derived_columns(
    session: AnalysisSession,
    *,
    before_columns: list[str],
    stage: str,
    source: str,
) -> list[str]:
    """ЕДИНАЯ ТОЧКА регистрации происхождения колонок (спека §Реализация п.1).

    Сравнивает колонки датафрейма сессии (уже заменённого apply-веткой на
    новый) с колонками ДО операции; каждая новая колонка записывается в
    ``session.derived_columns`` с метаданными {stage, source, created_at}.
    Колонки НЕ угадываются по суффиксу имени -- только факт появления в
    результате apply.

    Args:
        session: сессия, у которой apply уже присвоил новый ``dataframe``.
        before_columns: список колонок датафрейма ДО операции (вызывающий
            код обязан захватить его до присвоения ``session.dataframe``).
        stage: остановка-источник (например "stationarity", "outliers",
            "missing", "validation").
        source: человекочитаемое описание происхождения (метод/операция/
            исходные колонки) для аудита и группировки мастера (задача B).

    Returns:
        Список фактически добавленных имён колонок (порядок датафрейма).
    """
    df = session.dataframe
    if df is None:
        return []
    before = {str(name) for name in before_columns}
    added = [str(name) for name in df.columns if str(name) not in before]
    if not added:
        return []
    created_at = datetime.now(timezone.utc).isoformat()
    for name in added:
        session.derived_columns[name] = {
            "stage": stage,
            "source": source,
            "created_at": created_at,
        }
    return added


def scope_columns(df: pd.DataFrame, derived: Iterable[str]) -> list[str]:
    """Колонки ``df`` минус производные (порядок датафрейма сохранён)."""
    derived_set = {str(name) for name in derived}
    return [str(name) for name in df.columns if str(name) not in derived_set]


def canonical_columns(session: AnalysisSession) -> list[str]:
    """Исходные (канонические) колонки сессии -- область гейтов качества.

    Совместимость (спека §Реализация п.3): сессия без реестра (старые
    Redis-документы, только что загруженный датасет) отдаёт ВСЕ колонки
    датафрейма -- поведение идентично до-спечному.
    """
    if session.dataframe is None:
        return []
    registry = session.derived_columns or {}
    return scope_columns(session.dataframe, registry.keys())


def derived_columns_in_frame(session: AnalysisSession) -> list[str]:
    """Производные колонки, физически присутствующие в датафрейме.

    Реестр append-only и может содержать записи о колонках, удалённых
    мимо реестра; область производного профиля определяется фактом
    присутствия в датафрейме, а не записью реестра.
    """
    if session.dataframe is None:
        return []
    registry = session.derived_columns or {}
    return [str(name) for name in session.dataframe.columns if str(name) in registry]


def scope_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """DataFrame, ограниченный до перечисленных колонок.

    Пустой список даёт датафрейм без колонок (но с строками) -- честный
    «нечего проверять» для гейтов, а не молчаливое подмешивание производных.
    """
    return df.loc[:, [str(name) for name in columns]]


def operation_added_columns(
    before_columns: Iterable[str], after_df: pd.DataFrame
) -> list[str]:
    """Колонки, добавленные ОПЕРАЦИЕЙ (preview ещё не мутировал реестр).

    Нужна, чтобы карточная шкала ответа коррекции (preview -- гипотеза,
    apply -- факт) считалась по области ПОСЛЕ операции: флаг-колонки,
    добавляемые самой операцией, уже производные (Р6 спеки -- петля
    «+4 от флаг-колонки» исчезает по построению ещё до записи реестра).
    """
    before = {str(name) for name in before_columns}
    return [str(name) for name in after_df.columns if str(name) not in before]


def split_profiles(
    df: pd.DataFrame,
    derived_names: Iterable[str],
    profile_fn: Any,
    **profile_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Считает профиль раздельно по канонической и производной областям.

    Возвращает (canonical_profiles, derived_profiles) в формате
    ``profile_fn``; каждая область может быть пустой (пустой список --
    честное отсутствие, не ноль).
    """
    registry_set = {str(name) for name in derived_names}
    canonical = scope_columns(df, registry_set)
    derived_present = [str(name) for name in df.columns if str(name) in registry_set]

    canonical_profiles: list[dict[str, Any]] = (
        list(profile_fn(scope_frame(df, canonical), **profile_kwargs)) if canonical else []
    )
    derived_profiles: list[dict[str, Any]] = (
        list(profile_fn(scope_frame(df, derived_present), **profile_kwargs))
        if derived_present
        else []
    )
    return canonical_profiles, derived_profiles
