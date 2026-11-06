#!/usr/bin/env python3
# scripts/windows_parity.py
"""Windows-паритет локально: pytest с блокировкой Unix-only stdlib.

Зачем: CI (authXX.yml) гоняет контракты на ubuntu-24.04 И windows-2025,
а локальный гейт выполняется на Linux-машине разработчика. Класс
инцидента AUTH-07-HOTFIX2 (2026-11-06): top-level ``import resource``
в apps/api/model_jobs.py существует только на Unix; локально все гейты
были зелёными, а на windows-2025 упала ещё collection тестов
(ModuleNotFoundError: No module named 'resource') -- расхождение
«локально зелено / CI красно» стало платформенным, а не коммитным
(класс «скрыт .gitignore» уже закрыт check_committed.py, AUTH-07-HOTFIX1).

Как работает: скрипт запускает pytest В ЭТОМ процессе, предварительно
«спрятав» из sys.modules блокируемые модули -- их ``import`` поднимает
ImportError, ровно как на Windows, где их нет вовсе.

Почему по умолчанию блокируется только ``resource``: блокировка должна
эмулировать Windows БЕЗ ложных срабатываний. Модули с «двухветочным»
fallback (``try: import fcntl / except ImportError: import msvcrt``)
на Linux при блокировке fcntl уходят в Windows-ветку и падают на
отсутствующем msvcrt -- хотя на настоящем Windows-раннере они работают
(пример такого класса: телеметрия ddtrace, в зависимостях репозитория
её нет). У ``resource`` парного Windows-модуля не существует: все
корректные потребители используют ``try: import resource / except
ImportError: фича недоступна``, поэтому его блокировка даёт ровно ту
картину, что на windows-2025. Расширять список -- опцией --block и
только после разбора реального инцидента; источник истины по-прежнему
нативный прогон CI на windows-2025.

Использование:
    python scripts/windows_parity.py tests/api/test_auth07_admin_sessions.py -v
    python scripts/windows_parity.py --block fcntl,termios tests/...   # осознанно

Stdlib only; ничего не коммитит и не пушит (AGENTS.md).
"""
from __future__ import annotations

import argparse
import sys

# Модуль(и) stdlib, ОТСУТСТВУЮЩИЕ на Windows (документация Python,
# раздел «Platform-specific modules»), блокируемые по умолчанию.
# resource: пик-RSS бюджет джоб (apps/api/model_jobs.py) -- инцидент
# AUTH-07-HOTFIX2. Расширение -- только через --block (см. docstring).
DEFAULT_BLOCKED = ("resource",)


def _hide_modules(names: tuple[str, ...]) -> list[str]:
    """Сделать перечисленные модули неимпортируемыми (как на Windows)."""
    hidden: list[str] = []
    for name in names:
        if name in sys.modules:
            del sys.modules[name]
        sys.modules[name] = None  # import name -> ImportError
        hidden.append(name)
    return hidden


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pytest с блокировкой Unix-only stdlib (симуляция "
                    "windows-2025 раннера на Linux/macOS)",
    )
    parser.add_argument(
        "--block", metavar="MODS", default=None,
        help="доп. модули к блокировке через запятую (по умолчанию "
             "только resource; расширять осознанно -- см. docstring)",
    )
    args, pytest_args = parser.parse_known_args()

    blocked = DEFAULT_BLOCKED
    if args.block:
        extra = tuple(m.strip() for m in args.block.split(",") if m.strip())
        blocked = tuple(dict.fromkeys((*DEFAULT_BLOCKED, *extra)))

    import pytest

    hidden = _hide_modules(blocked)
    print(
        "windows-parity: заблокированы модули ("
        + ", ".join(hidden)
        + ") -- import поднимает ImportError, как на windows-2025",
        flush=True,
    )
    return pytest.main(pytest_args)


if __name__ == "__main__":
    sys.exit(main())
