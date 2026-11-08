# Локальные гейты перед передачей в GitHub

AUTH-12 применяется поверх ad4fd342eeba39161e69cce736d9d5d25f1cea2f. AUTH-09/10/11 и исправления INDEX уже в базе. Команды из корня checkout. Состав: `python scripts/local_gates.py --list`.

## До коммита: явно подготовить Git index

После распаковки ZIP просмотрите и добавьте только файлы текущей поставки:

```bash
git status --short
git add --pathspec-from-file=scripts/auth12/files.txt
git diff --cached --stat
python scripts/local_gates.py
```

Распаковки недостаточно: до git add INDEX содержит прежние версии. AUTH-00 сначала проверяет INDEX snapshot; при несовпадении останавливает этот gate, показывает staging hint и сохраняет полный UTF-8 вывод в `logs/local_gates/auth00.log` (ignored runtime log, не добавлять в Git). После изменения файла повторите его git add. Runner сам не stage/commit/push. Hint выбирает manifest самой новой поставки AUTH; старые manifests AUTH-09/10 на базе bf57630 повторять не требуется.

При установленных зависимостях добавьте `--skip-install`. Повтор AUTH-00 и чтение лога в Windows:

```powershell
python scripts/local_gates.py --only auth00 --skip-install
Get-Content -Raw -Encoding UTF8 logs/local_gates/auth00.log
```

Если FAIL сохраняется после git add, нужен этот лог: итоговая сводка не содержит причины. `FAILED STEP` и путь лога выводятся после сводки. Лог перезаписывается следующим AUTH-00. Пустой/неполный index — FAIL, LF/CRLF нормализуются collector; защита от пропущенных файлов не ослаблена.

## После локального коммита, до push

```bash
python scripts/local_gates.py --auth00-target head --skip-install
```

Прямой `python scripts/auth00/check_committed.py` сохраняет строгий HEAD default; для precommit задайте `--target index`. Проверяется snapshot без его изменения.

## Состав проверок

Default: auth12, auth11, auth10, auth09, auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Jest включает renderer build и typecheck обеих оболочек. Production builds: `npm run build:all`. Scientific pytest — `--with-pytest`; средовые сбои сравниваются с чистой базой.

AUTH-12 unit использует scripts/auth12/requirements.txt без полного scientific runtime. Native gate требует полный API runtime и настоящий disposable PostgreSQL, никогда production БД:

```bash
# CISSTAT_AUTH_TEST_DSN уже задан в защищённом окружении.
python scripts/local_gates.py --only auth12,auth12-postgres
# либо вместе с default:
python scripts/local_gates.py --with-auth12-postgres --skip-install
```

Без DSN/при skips native не PASS. `.github/workflows/auth12.yml`: Ubuntu/Windows unit; PostgreSQL16/18 native Ubuntu. Linux проверки не заменяют настоящий Windows CI. Все прежние PostgreSQL opt-in сохранены; auth07 также выполняет windows_parity.py с запретом Unix-only resource.

## Маршруты AUTH-12

HTTP methods/paths, DTO/OpenAPI/TS/BFF bindings не изменены:239 API,243 bindings. Новых публичных финансовых writer endpoints нет. AUTH-12 — trusted domain coordinator и transactional job intent/outbox; реальная интеграция очередей/worker adapters AUTH-13, коэффициенты CU AUTH-14. Не объявлять текущие HTTP scientific handlers финансово metered до этих этапов.

AUTH-00 reviewed map добавляет шесть non-HTTP surfaces:reserve,settle,policy operator,schema apply,ledger store,job outbox. Полный inventory574→580, discovery545 прежний. Обновлена карта docs/auth00/inventory.md. Проверка actual ASGI: `python scripts/auth06/check_routes.py`.

Новая explicit authority migration0025 через scripts/auth12/migrate.py --apply/--check; request-time auto-DDL нет. VM требует пересборку api; web байты прежние. Порядок развёртывания/границы и команды в docs/auth12/deploy.md. Локальные тесты используют только disposable DSN и не изменяют VM.
