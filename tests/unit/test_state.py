# tests/unit/test_state.py
import pytest
from app.core.state import AppState

def test_appstate_initialization():
    """Проверяет, что AppState инициализируется корректными дефолтными значениями."""
    state = AppState()
    assert state.user_role == "admin"
    assert state.ts_mode_active is True
    assert state.error_log == []

def test_appstate_error_log_isolation():
    """
    КРИТИЧЕСКИЙ ТЕСТ НА ИНВАРИАНТ:
    Проверяет, что error_log не является разделяемым между экземплярами AppState.
    Если использовать обычный list в качестве дефолта (без default_factory), этот тест упадет.
    """
    state1 = AppState()
    state2 = AppState()
    
    state1.error_log.append({"stage": "test", "message": "error"})
    
    assert len(state1.error_log) == 1
    assert len(state2.error_log) == 0  # Должно быть строго пусто!

def test_appstate_role_assignment():
    """Проверяет, что роли можно назначать при инициализации."""
    state = AppState(user_role="partner")
    assert state.user_role == "partner"