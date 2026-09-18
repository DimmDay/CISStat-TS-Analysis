"""Session-backed вертикальный срез задачи «Причины» (XAI) — v2.

spec_tasks_ia_addendum_v1_1.md §10/§10.1: первый реальный вертикальный
срез задачи — «Причины» (простейший контракт входа: только Model Card).
Паттерн C (§11.2): колонка методов -> колонка факторов -> деталь
фактора; фронтенд (TasksCauses) браузит уже вычисленные факты сессии.

Принцип честной маркировки (§9.1 того же дополнения): эндпоинт отдаёт
ТОЛЬКО реально вычисленные сессией данные. Единственный метод с
существующим session-артефактом — fold-важность tree-ML бэктестов
(bind_feature_importance, Task 127); Granger/SHAP/PDP присутствуют в
реестре методов со статусом not_computed и честной причиной (Granger
считается в EDA по запросу и не persist-ится; SHAP/PDP движок не
вычисляет). Никаких пересчётов и синтетики — §10.1: «просмотр уже
вычисленного».
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from apps.api.routers.modeling_session import _get_session


router = APIRouter()


# Реестр методов объяснения задачи «Причины» (паттерн C, §11.2: колонка
# методов). Порядок фиксирован: доступный метод — первым, затем методы
# без session-артефакта. kind — стабильный машинный идентификатор вида
# объяснения; title — продуктовая формулировка (по образцу буллетов
# TaskCard: «по продукту, не по механике»).
_METHOD_REGISTRY: tuple[dict[str, str], ...] = (
    {
        "method_id": "fold_importance",
        "kind": "feature_importance",
        "title": "Вклад факторов во время бэктеста",
    },
    {
        "method_id": "granger",
        "kind": "granger",
        "title": "Причинность по Грейнджеру",
    },
    {
        "method_id": "shap",
        "kind": "shap",
        "title": "Атрибуция предсказаний (SHAP)",
    },
    {
        "method_id": "pdp",
        "kind": "pdp",
        "title": "Зависимость прогноза от фактора (PDP)",
    },
)

# Честные причины статуса not_computed (одна формулировка — один факт;
# тексты видны пользователю, поэтому без жаргона движка).
_NOT_COMPUTED_REASONS: dict[str, str] = {
    "granger": (
        "Тест Грейнджера вычисляется в EDA по запросу аналитика "
        "и не сохраняется в сессии — данных для показа нет."
    ),
    "shap": (
        "SHAP-атрибуция не вычисляется движком платформы в текущей "
        "версии — вычисление станет отдельным бэкенд-срезом."
    ),
    "pdp": (
        "Кривые PDP не вычисляются движком платформы в текущей "
        "версии — вычисление станет отдельным бэкенд-срезом."
    ),
}


def _select_card(session, card_id: Optional[str]) -> tuple[str, dict]:
    """Выбрать карту: явный card_id (404, если нет) или последняя по
    created_at (тот же порядок, что TaskArtifactRibbon/список карт)."""
    cards = session.modeling_artifacts.get("model_cards") or {}
    if not cards:
        raise HTTPException(
            status_code=409,
            detail=(
                "Model Card не найдена: задача «Причины» работает поверх "
                "артефакта Моделирования. Сначала создайте Model Card."
            ),
        )
    if card_id is not None:
        entry = cards.get(card_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Model Card не найдена")
        return card_id, entry
    latest_id = max(
        cards,
        key=lambda cid: (cards[cid] or {}).get("card", {}).get("created_at") or "",
    )
    return latest_id, cards[latest_id]


def _card_block(card_id: str, entry: dict) -> dict:
    card = (entry or {}).get("card") or {}
    model_info = card.get("model_info") or {}
    return {
        "card_id": card_id,
        "model_id": model_info.get("model_id"),
        "model_name": model_info.get("description") or model_info.get("model_id"),
        "selection_kind": model_info.get("selection_kind", "single"),
        "created_at": card.get("created_at"),
    }


def _not_computed_method(method: dict, reason: str) -> dict:
    return {
        "method_id": method["method_id"],
        "kind": method["kind"],
        "title": method["title"],
        "status": "not_computed",
        "reason": reason,
        "factors": None,
        "provenance": None,
    }


def _fold_importance_factors(folds: list[dict]) -> list[dict]:
    """Агрегация fold-важности: средняя ВНУТРИ-fold доля по fold.

    Сырые MDI разных fold несопоставимы по масштабу (разные матрицы и
    объёмы train), поэтому нормировка — внутри каждого fold
    (importance/sum), затем среднее долей по fold. Сортировка — по
    убыванию средней доли, детерминированная (ties -> имя признака).
    """
    per_feature_folds: dict[str, list[dict]] = {}
    n_bound_folds = 0
    plan_ids: set[str] = set()
    run_ids: set[str] = set()
    for fold in folds:
        importance = (fold or {}).get("feature_importance")
        if not importance:
            continue
        records = importance.get("importances") or []
        total = sum(float(r.get("importance") or 0.0) for r in records)
        if total <= 0.0:
            continue
        n_bound_folds += 1
        if importance.get("plan_id"):
            plan_ids.add(str(importance["plan_id"]))
        fold_no = importance.get("fold", fold.get("fold"))
        run_ids.add(str(fold.get("run_id") or ""))
        for record in records:
            name = str(record.get("feature_name") or "")
            raw = float(record.get("importance") or 0.0)
            per_feature_folds.setdefault(name, []).append({
                "fold": fold_no,
                "importance": raw,
                "share": raw / total,
                "matrix_hash": importance.get("matrix_hash"),
            })
    if n_bound_folds == 0:
        return []
    factors = []
    for name, fold_values in per_feature_folds.items():
        fold_values.sort(key=lambda item: item["fold"])
        factors.append({
            "feature_name": name,
            "mean_share": sum(item["share"] for item in fold_values) / n_bound_folds,
            "n_folds": len(fold_values),
            "fold_values": fold_values,
        })
    factors.sort(key=lambda item: (-item["mean_share"], item["feature_name"]))
    return factors


def _fold_importance_method(session, card_block: dict) -> dict:
    method = _METHOD_REGISTRY[0]
    model_id = card_block.get("model_id")
    if card_block.get("selection_kind") == "ensemble":
        return _not_computed_method(
            method,
            "Карта ансамбля объединяет несколько моделей; вклад факторов "
            "требует честной агрегации по членам ансамбля — отдельное "
            "решение, сейчас данных для показа нет.",
        )
    backtest = (session.modeling_artifacts.get("backtests") or {}).get(model_id)
    if not backtest:
        return _not_computed_method(
            method,
            "Артефакт бэктеста для карты не найден — важность факторов "
            "не вычислялась в этой сессии.",
        )
    folds = backtest.get("folds") or []
    factors = _fold_importance_factors(folds)
    if not factors:
        return _not_computed_method(
            method,
            "Модель не вычисляет важность факторов (нет привязанных "
            "fold-записей): важность доступна для ML-моделей "
            "(random_forest, xgboost, lightgbm, catboost).",
        )
    provenance_plan_ids = {
        str((fold or {}).get("feature_importance", {}).get("plan_id"))
        for fold in folds
        if (fold or {}).get("feature_importance")
    }
    return {
        "method_id": method["method_id"],
        "kind": method["kind"],
        "title": method["title"],
        "status": "available",
        "reason": None,
        "factors": factors,
        "provenance": {
            "backtest_run_id": backtest.get("run_id"),
            "plan_id": (
                provenance_plan_ids.pop() if len(provenance_plan_ids) == 1 else None
            ),
            "n_folds": len(factors[0]["fold_values"]),
        },
    }


@router.get("/causes")
def get_tasks_causes(
    request: Request,
    response: Response,
    card_id: Optional[str] = Query(
        None,
        description="Явная Model Card; по умолчанию — последняя по created_at",
    ),
):
    """Реестр методов объяснения задачи «Причины» для выбранной карты.

    Честная маркировка (§9.1): доступен только метод с реально
    существующим session-артефактом (fold-важность Task 127);
    Granger/SHAP/PDP — not_computed с причиной. Без пересчётов.
    """
    _store, session = _get_session(request, response)
    resolved_id, entry = _select_card(session, card_id)
    card_block = _card_block(resolved_id, entry)
    methods: list[dict[str, Any]] = [_fold_importance_method(session, card_block)]
    for method in _METHOD_REGISTRY[1:]:
        methods.append(
            _not_computed_method(method, _NOT_COMPUTED_REASONS[method["method_id"]])
        )
    return {"card": card_block, "methods": methods}
