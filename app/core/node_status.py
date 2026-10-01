# app/core/node_status.py
"""Канонический владелец вывода статусов узлов из фактов решений
(spec_progress.md §4.1; Расхождение №1 progress_ts_analysis.md vs
spec_progress.md -- Task PROGR-10).

РЕШЕНИЕ РАСХОЖДЕНИЯ №1. Дизайн-документ (progress_ts_analysis.md §3/§4.2)
предполагал «живой опрос profile-эндпоинтов» -- он СОЗНАТЕЛЬНО НЕ
реализуется: статус выводится ТОЛЬКО из засеянных фактов решений
(trace_events). Цена принята тимлидом: статус -- с точностью до
последнего засеянного события (узел, просмотренный и оставленный без
коррекции, останется running) -- для навигационной панели это приемлемо.
Взамен три потребителя статуса получают ОДИН движок:

  * навигационная панель (§6.2) -- GET /v1/progress/trace отдаёт
    готовое состояние (node_statuses/stages), фронтенд рендерит,
    не вычисляет;
  * Наставник (§7.1) -- next-step выводит статусы этим же движком;
  * admin-аналитика (§10) -- топ проблемных узлов по этому же движку.

До PROGR-10 движков было ДВА (бэкенд-зеркало в mentor_rules.py и
фронтенд-порт в packages/ui/lib/progress.ts) плюс третье зеркало в
run_report.py -- расползание тихое по построению; здесь оно устранено:
дубликаты удалены, владение проверяется тестом
(tests/api/test_node_status_engine.py, контур «владение»).

Паттерн модуля -- pipeline_graph/admin_analytics: ЧИСТЫЕ функции без
HTTP и хранилищ; на входе события канона §4.1 (TraceEvent либо уже
dict -- смешанные представления легальны: слой 1 отдаёт TraceEvent,
слой 2 -- stored-словари), на выходе -- иммутабельные по смыслу
словари. Ввод событий НЕ валидируется (трасса -- журнал: неизвестные
типы/фантомы честно пропускаются, R3 PROGR-1-CERT), вход не мутируется.

ЕДИНСТВЕННЫЙ источник карты «тип события -> статус»: перенос из
mentor_rules.py дословно (зеркальные тесты страховали семантику --
теперь она канонизирована здесь и проверена напрямую).
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core.pipeline_graph import (
    STAGES,
    STAGE_NODES,
    fold_status_values,
    is_known_node,
)

# ── Каноническая карта §4.1: тип события решения -> статус узла ──────

# Терминальное событие решения -> done; correction_previewed -> warning
# (preview показывается только при найденных нарушениях -- решение ещё
# не принято); profile_viewed -> running (узел исследуется). События
# уровня стадии (node_id=null: mode_changed, target_column_changed,
# passport_captured, run_*) -- не про узел, в статусы не попадают (N-2).
EVENT_NODE_STATUS: dict[str, str] = {
    "upload_completed": "done",
    "correction_applied": "done",
    "correction_previewed": "warning",
    "profile_viewed": "running",
    "backtest_run": "done",
    "tuning_trial_completed": "done",
    "model_selected": "done",
    "model_card_generated": "done",
    "forecast_generated": "done",
    "forecast_compared": "done",
    "forecast_sensitivity_computed": "done",
    "forecast_exported": "done",
}


def event_to_dict(event: Any) -> dict[str, Any] | None:
    """Публичная нормализация события канона §4.1: TraceEvent (любой
    объект с to_dict) -> канонический 8-польный dict (+ legacy-алиас
    timestamp); уже dict -- как есть (без копии: события иммутабельны
    по соглашению); мусор (строка/число/None) -- None, потребители
    пропускают (деградация «событие мимо фактов», не 500).
    Бывший приватный _event_dict mentor_rules -- поднят в публичный API:
    потребители движка не должны импортировать приватное из модулей-
    потребителей (нарушение владения, найденное верификацией PROGR-10)."""
    if hasattr(event, "to_dict"):
        return event.to_dict()
    if isinstance(event, dict):
        return event
    return None


def resolve_node_id(data: Mapping[str, Any]) -> str | None:
    """Вывод узла из нормализованного события (контракт PROGR-1):
    явный node_id приоритетен; forecasting-события слоя 2 хранят
    node_id=None -- узел выводится из типа события (4 канонических типа
    §4.1 совпадают с узлами графа §2). Пара вне этих правил -- None:
    событие уровня стадии не создаёт узловых фактов (N-2)."""
    stage = str(data.get("stage") or "")
    node_id = data.get("node_id")
    if not node_id and stage == "forecasting":
        event_type = str(data.get("event_type") or "")
        if event_type in STAGE_NODES["forecasting"]:
            node_id = event_type
    return str(node_id) if node_id else None


def derive_node_statuses(events: list[Any]) -> dict[str, str]:
    """ЕДИНЫЙ движок: статус каждого узла -- по последнему его событию
    (хронология входа сохраняется: позднее событие перезаписывает
    раннее -- previewed -> applied = done). Ключ -- "stage/node_id"
    (id сознательно пересекаются между стадиями: regularity/stationarity).

    События без узла (N-2), без известного маппинга или вне графа
    честно пропускаются: фантомных узлов не возникает (is_known_node
    гейт -- тот же, что у make_node_state §3)."""
    statuses: dict[str, str] = {}
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        status = EVENT_NODE_STATUS.get(str(data.get("event_type") or ""))
        if status is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        if not node_id:
            continue
        if not is_known_node(stage, node_id):
            continue
        statuses[f"{stage}/{node_id}"] = status
    return statuses


def derive_stage_states(statuses: Mapping[str, str]) -> list[dict[str, Any]]:
    """Панельная надстройка движка: свёртка §12 п.10 + счётчики для
    карточек блок-схемы §6.2. ВСЕ 6 стадий ВСЕГДА присутствуют -- в
    каноническом порядке §2; узлы без фактов честно pending («не
    начато»). Пустая трасса -- честные «не начато» с тоталами из графа,
    а не пустой список: панель не должна дорисовывать стадии сама.

    fold -- каноническая fold_status_values (§12 п.10: любой единичный
    warning/error делает карточку жёлтой; skipped агрегатно не мешает
    пройденности), НЕ локальный порт -- второй реализации свёртки быть
    не должно."""
    states: list[dict[str, Any]] = []
    for stage in STAGES:
        node_statuses = [
            statuses.get(f"{stage}/{node_id}", "pending")
            for node_id in STAGE_NODES[stage]
        ]
        states.append(
            {
                "stage": stage,
                "fold": fold_status_values(node_statuses),
                "done_count": sum(s == "done" for s in node_statuses),
                "warning_nodes": sum(
                    s in ("warning", "error") for s in node_statuses
                ),
                "total_nodes": len(node_statuses),
            }
        )
    return states
