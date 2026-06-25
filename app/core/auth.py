"""
Система авторизации и управления ролями.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).
"""
import hashlib


def check_token(input_token: str, expected_hash: str) -> bool:
    """
    Проверяет корректность токена авторизации.
    
    Args:
        input_token: Токен, введённый пользователем
        expected_hash: Эталонный SHA-256 хэш (из переменной окружения)
    
    Returns:
        True если токен корректен, иначе False
    
    Note:
        Согласно ARCHITECTURE.md, формат токена должен быть {пароль}_{роль}.
        Текущая реализация проверяет только пароль (legacy-поведение).
        Извлечение роли — технический долг, будет реализовано при создании
        полноценной системы ролей (Этап 7).
    """
    if not input_token:
        return False
    
    input_hash = hashlib.sha256(input_token.encode('utf-8')).hexdigest()
    return input_hash == expected_hash