# apps/api/data_context.py
"""Единая точка контекста расчёта (задача AUDIT-C, plan_progress_audit.md §6;
контракт docs/progress_audit_contract.md §3.4 -- УТВЕРЖДЕНО-AUDIT-0 (форма),
детали -- аддендум v0.4-C).

Контекст расчёта (спека spec_progress_audit.md §8.1 «Контекст»): raw dataset
fingerprint (sha256 файла) + dataset_revision + target/date колонки; сервер
ВЫЧИСЛЯЕТ context_id -- фронт контекст не создаёт догадками (план §1,
«Запретить подмену версии собственным счётчиком фронтенда»).

Состав модуля (три примитива, ни одного импорта из apps/api -- направление
зависимости session_store -> data_context безопасно от циклов, тот же
паттерн выделения доменного правила, что target_column_rule/column_origin):

  * compute_data_digest(df) -- честный дайджест КОНТЕНТА DataFrame: основа
    no-op-детекции («no-op не выдаётся за изменённые данные», план §6 п.2).
    Детерминирован между процессами (hash_pandas_object с фиксированным
    ключом), различает значения/форму/имена колонок; сбой вычисления --
    честное отсутствие («»), вызывающий (set_dataframe) трактует
    недоступность в безопасную сторону (изменение).
  * context_components(...) -- разложение контекста на SCOPE-компоненты
    («data»/«target»/«temporal»): единственный вход реестра зависимостей
    узлов (app/core/pipeline_graph.py::NODE_DEPENDENCY_SCOPES) и функции
    применимости node_context_validity. Имена scope-ключей совпадают с
    каноном pipeline_graph.CONTEXT_SCOPES -- равенство страхует
    import-инвариант теста (паттерн STAGES, направленный импорт невозможен:
    pipeline_graph импортирует routers.session -- цикл).
  * compute_context_id(run_id, components) -- стабильный идентификатор
    контекста расчёта: uuid5 фиксированного namespace (детерминирован между
    процессами -- повторное вычисление на том же состоянии возвращает ТОТ
    ЖЕ id; свойство I3, восстановимая сессия продолжает свой контекст).
    Run-scoping: контекст привязан к ЗАПУСКУ исследования -- повторная
    загрузка того же файла = новый запуск = новый контекст (RED-критерий
    «тот же filename после повторной загрузки различается»; платформенная
    семантика set_dataset: новый датасет = новый анализ, история не
    переносится). Restored-сессия (тот же run_id + те же компоненты)
    получает тот же context_id -- продолжение того же исследования (§5.3).

Границы (осознанные): «настройки, влияющие на расчёт» и параметры методов
образуют RESULT context -- AUDIT-4/7A (план §6 п.3); durable-хранение
context_id слоя 2 и run-метаданных ревизии -- миграция AUDIT-6A; cross-run
применимость restore -- AUDIT-8.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

# Префикс/пространство имён идентичности контекста: uuid5 от него
# детерминирован между процессами/перезапусками (тот же паттерн, что
# trace_events._STABLE_ID_NAMESPACE AUDIT-S).
_CONTEXT_ID_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://cisstat.ts-analysis/progress/data-context-v1"
)
CONTEXT_ID_PREFIX = "ctx-"

# Канонические scope-компоненты контекста. Владелец реестра -- pipeline_graph
# (CONTEXT_SCOPES); равенство страхует тест (test_progress_audit_c.py).
SCOPE_DATA = "data"        # контент данных: fingerprint файла + ревизия
SCOPE_TARGET = "target"    # исследуемый признак (имя колонки, "" -- нет)
SCOPE_TEMPORAL = "temporal"  # временная колонка (имя, "" -- нет)

_DIGEST_PREFIX = "df1-"


def compute_data_digest(df: Optional[pd.DataFrame]) -> str:
    """Честный дайджест контента DataFrame (основа no-op-детекции).

    Материал: форма + имена колонок + построчные хэши hash_pandas_object
    (фиксированный ключ -- детерминирован между процессами; различает
    значения, dtype-переходы значений, форму). None -> "" (честное
    отсутствие данных). Сбой вычисления -> "" -- вызывающий (set_dataframe)
    обязан трактовать недоступность digest в БЕЗОПАСНУЮ сторону (изменение),
    а не в опасную («данные не изменились») -- стоимость ложного bump
    (лишняя инвалидация) несравнимо ниже стоимости устаревшего результата,
    выданного за current (спека §8.2).
    """
    if df is None:
        return ""
    try:
        hashed = pd.util.hash_pandas_object(df, index=True)
        material = (
            f"{df.shape}|{[str(c) for c in df.columns]}|"
            f"{hashed.to_numpy().tobytes()!r}"
        )
        return _DIGEST_PREFIX + hashlib.sha256(
            material.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
    except Exception:  # pragma: no cover - защитный контур рантайма
        return ""


def context_components(
    *,
    dataset_fingerprint: str,
    data_revision: int,
    target_column: Optional[str],
    date_column: Optional[str],
) -> dict[str, str]:
    """Разложение контекста расчёта на scope-компоненты реестра зависимостей.

    «data» -- fingerprint исходного файла + ревизия данных (тот же файл
    после преобразования -- другой вычислительный вход, спека §8.1);
    «target»/«temporal» -- имена колонок ("" -- не выбрано; отсутствие
    выбора честно, не выдумывается -- план §1).
    """
    return {
        SCOPE_DATA: f"{dataset_fingerprint or ''}#{int(data_revision)}",
        SCOPE_TARGET: target_column or "",
        SCOPE_TEMPORAL: date_column or "",
    }


def compute_context_id(
    *, run_id: str, components: Mapping[str, str]
) -> Optional[str]:
    """Стабильный server context_id запуска на его компонентах контекста.

    Run-scoping: без run_id (исследования нет) -- None (честное отсутствие:
    контекст существует только у запуска, §5); тот же run + те же компоненты
    -- тот же id (детерминизм uuid5); другой run -- другой id (повторная
    загрузка того же файла -- новый контекст). Компоненты копируются в
    материал с сортировкой ключей -- устойчивость к порядку словаря.
    """
    if not run_id:
        return None
    material = json.dumps(
        {
            "v": 1,
            "run_id": str(run_id),
            "components": {str(k): str(v) for k, v in dict(components).items()},
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return CONTEXT_ID_PREFIX + uuid5(_CONTEXT_ID_NAMESPACE, material).hex[:16]


def describe_components(components: Mapping[str, Any]) -> str:
    """Короткое человекочитаемое представление компонентов (логи/диагностика
    без сырых рядов, спека §8.4)."""
    try:
        data = dict(components)
        return (
            f"data={data.get(SCOPE_DATA, '?')}; "
            f"target={data.get(SCOPE_TARGET, '?') or 'none'}; "
            f"temporal={data.get(SCOPE_TEMPORAL, '?') or 'none'}"
        )
    except Exception:  # pragma: no cover - защитный контур
        return "components=<unreadable>"
