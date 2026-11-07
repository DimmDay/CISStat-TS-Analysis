# Локальные гейты перед передачей в GitHub

Поставка AUTH-10 применяется поверх c13a52b (AUTH-09/HOTFIX01 уже в базе). Команды из корня checkout. Состав: `python scripts/local_gates.py --list`.

## До коммита: явно подготовить Git index

После распаковки исходного ZIP и AUTH-10-HOTFIX01 просмотрите изменения и **до запуска гейтов** добавьте только файлы обеих поставок:

```bash
git status --short
git add --pathspec-from-file=scripts/auth10/files.txt
git add --pathspec-from-file=scripts/auth10/hotfix01/files.txt
git diff --cached --stat
python scripts/local_gates.py
```

AUTH-10-HOTFIX01: одного распакованного ZIP недостаточно для проверки INDEX. До git add он содержит старую версию, даже если приложение и остальные тесты зелёные. Runner теперь первым проверяет snapshot; при несовпадении сразу останавливает AUTH-00, печатает конкретную команду/подсказку и сохраняет полный UTF-8 вывод в `logs/local_gates/auth00.log` (ignored runtime log, не добавлять в Git). После commit используется строгий HEAD, как ниже. Автоматического stage/commit нет.

Если нужен повтор только AUTH-00:

```powershell
python scripts/local_gates.py --only auth00 --skip-install
Get-Content -Raw -Encoding UTF8 logs/local_gates/auth00.log
```

Если после двух git add остаётся FAIL, нужен именно этот лог, а не одна итоговая сводка. `FAILED STEP` и путь лога теперь повторяются под сводкой. Лог перезаписывается при следующем AUTH-00.

При установленных зависимостях — `--skip-install`. Default AUTH-00 target=INDEX проверяет подготовленный snapshot, включая полный reviewed report/source fingerprints. Скрипт сам не stage/commit/push. Старый HEAD до commit не должен содержать новые routes; пустой/неполный index — FAIL. LF/CRLF нормализуются collector. После изменения файла повторите его git add. Исходный manifest AUTH-09 и hotfix повторно добавлять на базе c13a52b не требуется.

## После локального коммита, до push

```bash
python scripts/local_gates.py --auth00-target head --skip-install
```

Прямой `python scripts/auth00/check_committed.py` сохраняет строгий HEAD default; для precommit — явно `--target index`. Gate проверяет snapshot без его изменения. См. описание исправленного инцидента AUTH-09 в docs/auth09/hotfix01.md.

## Состав проверок

Default: auth10, auth09, auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Jest gate включает renderer build и typecheck обеих оболочек. Production builds отдельно: `npm run build:all`. Scientific pytest — `--with-pytest`; результаты сверяются с чистой базой при средовых сбоях.

AUTH-10 unit gate stdlib unittest + scripts/auth10/requirements.txt. Native gate использует полный API runtime и настоящий disposable PostgreSQL, не production БД:

```bash
# CISSTAT_AUTH_TEST_DSN уже задан в защищённом окружении.
python scripts/local_gates.py --only auth10,auth10-postgres
# либо вместе с default:
python scripts/local_gates.py --with-auth10-postgres --skip-install
```

Без DSN/при skips native не PASS. `.github/workflows/auth10.yml`: Ubuntu/Windows unit; PostgreSQL16/18 native на Ubuntu. Linux import/CRLF проверки не заменяют настоящий Windows CI. Остальные PostgreSQL opt-in сохранены; auth07 также проходит windows_parity.py с блокировкой Unix-only resource.

## Маршруты AUTH-10

Добавлены GET/POST `/v1/api-keys`, POST `/v1/api-keys/{key_id}/rotate`, POST `/v1/api-keys/{key_id}/revoke`. Существующие HTTP methods/paths не удалены/не переименованы. API inventory 235→239, registry bindings 239→243, full inventory 567→572 (+4 HTTP, +1 trusted operator surface). Добавлены request/response DTO; OpenAPI/TS/BFF generated metadata и policy review обновлены. Независимая проверка actual ASGI routes: `python scripts/auth06/check_routes.py`.

Production required/scoped использует durable authority. Старый ENV registry доступен только в dev compatibility, csk_ всегда проверяется PostgreSQL. Migration 0024 explicit: перед новым API см. docs/auth10/design.md. Никакие локальные гейты не изменяют VM.
