# app/core/state.py
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AppState:
    """
    Типизированный контейнер состояния приложения.
    Единственный источник истины для UI и бизнес-логики.
    
    ⚠️ ИНВАРИАНТ: Все изменения состояния проходят только через этот класс.
    """
    # Базовые флаги и конфигурация
    user_role: str = "admin"  # admin / user / partner
    ts_mode_active: bool = True
    
    # Логирование ошибок (Graceful Degradation - Правило 16)
    # Используем default_factory, чтобы избежать разделяемого состояния между экземплярами
    error_log: list[dict[str, Any]] = field(default_factory=list)
    
    # TODO: По мере рефакторинга сюда будут добавляться:
    # datasets: DatasetManager (Этап 4)
    # best_model: Any (Этап 6)
    # experiment_log: ExperimentDB (Этап 4)
    # model_registry: dict (Этап 3)