# CERT HOTFIX2 — GitHub Windows CP1252 stdout/stderr

Поверх полной cert-поставки + HOTFIX1. User traceback точно локализует падение scripts/local_gates.py:608 при печати русского заголовка, до gate execution. Это отдельная от чтения UTF-8 файлов проблема: Python3.12 Windows Actions stdout использовал CP1252.

TDD: реальный Python subprocess с PYTHONIOENCODING=cp1252/PYTHONUTF8=0 воспроизвёл тот же UnicodeEncodeError заголовка на исходном runner (RED). Исправление:

- main() настраивает stdout И stderr UTF-8 до argparse/первого print; импорт модуля не меняет streams.
- Все дочерние команды, включая обычные gates без auth00 log, получают PYTHONIOENCODING=utf-8 и PYTHONUTF8=1; окружение родителя глобально не переписывается.
- В CI workflow явно указан UTF-8 для job; корректность runner проверяется отдельно при принудительном CP1252, без зависимости от этого workflow env.
- Сохранены UTF-8 logfile и fallback _logged_command. Error/exit7 дочернего шага по-прежнему даёт FAIL/exit1 итогового runner; ни stage, ни commit не выполняются.

Regression: реальный process, русский heading/description/stdout/stderr/summary, success и failure; index sentinel не меняется. Это воспроизведение codec на Linux, не объявляется native Windows CI PASS до нового workflow прогона.

Распаковать ZIP в текущий checkout после HOTFIX1:

```powershell
git add --pathspec-from-file=scripts/kabinet_demo_cert/hotfix2-files.txt
python scripts/local_gates.py --only kabinet-demo-cert,auth00 --skip-install
# После своего commit перед push:
python scripts/local_gates.py --only auth00 --auth00-target head --skip-install
```

Нужен обычный push исправления и повтор GitHub workflow. Отключать Windows job/гейты или менять console codepage вручную не нужно. Новых runtime/Next/API/Docker/env/migration изменений нет; дополнительный VM rebuild из-за этого hotfix не требуется. Изменённый Python tooling проверен py_compile; Next-сборки не повторяются, их исходники неизменны и были PASS в HOTFIX1.
