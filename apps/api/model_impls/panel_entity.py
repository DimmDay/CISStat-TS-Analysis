# apps/api/model_impls/panel_entity.py
"""PANEL-MODELS-3b: отказной исполнитель panel_entity-моделей для
legacy synthetic-эндпоинта (POST /v1/models/backtest).

Прецедент run_var_backtest (Task 132): сущностная панель (entity x время)
НЕВЫВОДИМА из одиночного синтетического ряда -- исполнение однорядным
эндпоинтом невозможно без подмены. Никаких синтетических панельных демо:
честный отказ; панельные FE/RE/Panel VAR/GMM (PANEL-GMM-4) исполняются
ТОЛЬКО панельным движком run_panel_entity_backtest_plan (session-контур)
после подтверждения паспорта панели (checkpoint panel_entry, этап 3a).
"""
from __future__ import annotations

from typing import Sequence

from apps.api.schemas import BacktestMetrics


def run_panel_entity_backtest_refusal(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Честный отказ panel_entity-моделей (panel_fe/panel_re/panel_var/
    deepar_panel/panel_gmm) на однорядном synthetic-эндпоинте
    (сигнатура _BACKTEST_IMPLEMENTATIONS)."""
    raise ValueError(
        "panel_entity-модель требует сущностную панель (entity x время): "
        "однорядный synthetic-эндпоинт не применим -- подтвердите паспорт "
        "панели (checkpoint panel_entry) и исполняйте через панельный "
        "движок run_panel_entity_backtest_plan (PANEL-MODELS-3b/GMM-4)"
    )
