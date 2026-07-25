# apps/api/auth.py
"""
Авторизация по API-ключу для публичных эндпоинтов (внешние покупатели).

ЗАГЛУШКА: ключи сейчас проверяются по статичному множеству из переменной
окружения -- для продакшена нужна таблица ключей в БД (с привязкой к
клиенту, лимитами использования/биллингом), но интерфейс зависимости
(Depends(require_api_key)) не изменится при переходе на неё.
"""
import os

from fastapi import Header, HTTPException, status

_VALID_API_KEYS = set(
    filter(None, os.environ.get("CISSTAT_API_KEYS", "").split(","))
)


def require_api_key(x_api_key: str = Header(...)) -> str:
    if not _VALID_API_KEYS:
        # Явная защита от случайного запуска без настроенных ключей вообще --
        # лучше падать очевидной ошибкой конфигурации, чем молча пропускать всех.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CISSTAT_API_KEYS не настроены на сервере",
        )
    if x_api_key not in _VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный API-ключ",
        )
    return x_api_key
