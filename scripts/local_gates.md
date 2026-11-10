# Локальные гейты перед передачей в GitHub

AUTH-17 применяется поверх 201a3b1f12eac55525fb07301b5e37f8e962d938. AUTH-01…16 и Dockerfile CRLF hotfix уже в базе. Команды из корня checkout. Состав: `python scripts/local_gates.py --list`.

## До коммита: явно подготовить Git index

После распаковки ZIP просмотрите и добавьте только файлы текущей поставки:

```bash
git status --short
git add --pathspec-from-file=scripts/auth17/files.txt
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

Default: auth17, auth16, auth15, auth14, auth13, auth12, auth11, auth10, auth09, auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Jest включает renderer build и typecheck обеих оболочек. Production builds: `npm run build:all`. Scientific pytest — `--with-pytest`; средовые сбои сравниваются с чистой базой.

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

AUTH-13 добавляет default `auth13` portable process/stop-proof contracts и
опциональный `--with-auth13-postgres` (или `--only auth13-postgres`) с обязательным
disposable `CISSTAT_AUTH_TEST_DSN`. Миграция и service provisioning —
`docs/auth13/runbook.md`; отсутствие DSN/пропуски не считаются native PASS.

## AUTH-14 — CU benchmark и runtime

Default `auth14`: portable fixed-point/coverage/meter/profile/physical-process contracts, минимальные dependencies из `scripts/auth14/requirements.txt`. Native `--with-auth14-postgres` или `--only auth14-postgres` требует disposable `CISSTAT_AUTH_TEST_DSN`, полный API runtime; missing DSN/skips/zero tests — FAIL. CI: Ubuntu/Windows contracts, PostgreSQL16/18 native. Это не утверждение локального запуска Windows/PG18. Все прежние opt-in gates сохранены.

HTTP paths/methods и DTO сохранены; изменено исполнение существующих PELT GET, sync/stateless tuning и async aliases. AUTH-00 карта отражает calibrated pricing/meter/profile/cache/supervisor boundaries, BFF forwarding Idempotency-Key. Actual ASGI gate: `python scripts/auth06/check_routes.py`; route/BFF parity: `python scripts/pgv11/check_routes_auth00.py`.

Raw локальный benchmark/отдельный holdout — `scripts/auth14/reference/`; его profile не является замером VM и не включается автоматически. В calibrated режиме неизвестный домен отказывается, configured corrupt/mismatched profile даёт503 без unpriced fallback. Новых migrations нет. Для VM пересобрать **api и web**, сохранить protected volumes/keys; measurement/install/checksum и переключение — `docs/auth14/runbook.md`. Docker engine отсутствует в сессии; сборка images выполняется на VM. Финансовый wallet/commercial rollout/AUTH-CERT этим gate не объявляются пройденными.

## AUTH-14 HOTFIX-01 — разбор `Inventory drift`

Патч поверх AUTH-14 уточняет **какой snapshot** упал: WORKTREE, INDEX или HEAD. Лог содержит reviewed source paths и expected/actual SHA-256, изменения entry fields/metadata; прежняя общая строка не позволяла установить локальную причину. Защита не ослаблена и inventory не перезаписывается автоматически.

После распаковки hotfix явно stage объединённый `scripts/auth16/files.txt` и повторить `python scripts/local_gates.py --only auth00 --skip-install`. Если WORKTREE не согласован, одного git add недостаточно: просмотрите названные файлы/карту против поставки. Не выполняйте `inventory.py --write` только для устранения FAIL. Полная инструкция: `docs/auth14/hotfix01.md`. Неполный INDEX, незаписанный guard и новые/ignored routes по-прежнему дают FAIL.

## AUTH-15 (база b9af29b)

Добавлены 14 HTTP bindings и страницы /demo и /admin/demo-campaigns в обеих оболочках. Новый default auth15; native — `--with-auth15-postgres` или `--only auth15-postgres`, disposable `CISSTAT_AUTH_TEST_DSN`. Native CI PG16/18; отсутствие DSN/skip не PASS. Локальный WASM proof не заменяет native locking/restart.

После распаковки: `git add --pathspec-from-file=scripts/auth16/files.txt`, затем `python scripts/local_gates.py --skip-install`; до push после вашего commit — `--auth00-target head`. Обновлены AUTH-00 inventory/review, функциональные bindings, generated OpenAPI/TS и proxy allowlist. Production build обеих оболочек — `npm run build:all`. Установка на VM требует api+web build и explicit0027, см. docs/auth15/deploy.md. AUTH-16 admission codes/cleanup и эксплуатационная сертификация остаются отдельной задачей.

## AUTH-13-HOTFIX-1 (база 58a46f9) — bootstrap worker-credential (OPS-DIAG-1)

Новых гейтов нет. Существующие паттерны подхватывают новые файлы автоматически: `auth13` (unittest discover `tests/unit -p "test_auth13*.py"`) включает `test_auth13_worker_bootstrap.py` (22 unit-сценария: формат ключа, состояния disabled/missing/invalid, отображение строки, отсутствие утечки секрета/дайджеста, startup_check, legibility ошибок воркера), `auth13-postgres` (`scripts/auth13/verify_postgres.py`) — `tests/integration/test_auth13_bootstrap.py` (6 native-сценариев: воспроизведение дефекта 503 на пустом ключе и на ключе без строки, включая пользовательский admit; bootstrap+восстановление воркера; идемпотентность; запрет воскрешения revoked; запрет продления expired).

AUTH-00: после правок document_render_worker/main.py выполнена официальная перегенерация `inventory.py --write`; в `policy_review.json` две worker-записи пере-ключены на новые строки (676→715, 698→737) с байт-идентичной классификацией; entries 614→614, counts прежние (api 253, page 38, worker 9); отпечатки 390→391 — единственный новый reviewed source `apps/api/workers/bootstrap.py`; прочие изменения записей — только evidence-строки main.py (+10). Роуты не затронуты, actual-ASGI `scripts/auth06/check_routes.py` PASS (added/missing пусто). Обновлены docs/auth00/inventory.md|json и docs/auth13/runbook.md (раздел bootstrap). VM: пересборка ТОЛЬКО api, web байты прежние; доставка `scripts/auth13-hotfix1/files.txt`.


## AUTH-16 (база 2f48120)

Default `auth16` проверяет конечные policy/admission contracts; live `--only auth16-postgres` или `--with-auth16-postgres` требует disposable CISSTAT_AUTH_TEST_DSN. CI: PostgreSQL16/18, contracts Linux/Windows. Нет DSN/есть skip — не PASS. `check_routes` подтверждает 255 API методов, 259 bindings и 621 inventory entry; добавлены POST admin admissions и GET own limits. Обновлены review/inventory, OpenAPI/TS, proxy allowlist. `npm run build:all` — production обеих оболочек.

VM требует api+web rebuild, explicit0028 и переноса scientific files в science_data; инструкции `docs/auth16/deploy.md`. Если CU profile настроен, изменённые kernel fingerprints требуют повторной калибровки. `cleanup.py --sweep` — SQL, `--collect-files --quiesced` и восстановление crash HTTP calls — только при остановленных publishers. Retention/holds/uncertain не снимаются принудительно. Общая operational сертификация остаётся AUTH-CERT.


## AUTH-16 HOTFIX-01 — Dockerfile LF/CRLF в INDEX

При `INDEX inventory check failed` с единственным `apps/api/Dockerfile` и expected34659093… / actual0da21e1f… причина — CRLF в staged blob, LF в поставке. AUTH-00 теперь нормализует CRLF для текстового basename Dockerfile, как для .py/.sql/.txt. Содержательные изменения Dockerfile и бинарные bytes по-прежнему вызывают FAIL. Runtime/API/routes/образы этим hotfix не меняются.

Применить `cisstat-auth16-hotfix01.zip` поверх уже распакованной AUTH-16 поставки, затем из корня checkout:

```powershell
git add --pathspec-from-file=scripts/auth16/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Manifest AUTH-16 объединён с hotfix; git config/core.autocrlf менять, выполнять reset или генерировать inventory локально не требуется. При другом FAIL нужен полный UTF-8 logs/local_gates/auth00.log. Прежние runtime/native/Jest проверки AUTH-16 относятся к тем же bytes; дополнительная пересборка VM из-за hotfix не нужна.


## AUTH-17 (база201a3b1)

Default `auth17`: portable team command/target/hash/finite-limit tests. `--only auth17-postgres` или `--with-auth17-postgres` — native Invitations/seats/OWNER/concurrency/rollback и реальный HTTP, нужен disposable CISSTAT_AUTH_TEST_DSN; отсутствие DSN/skip не PASS. CI: contracts Linux/Windows, native PG16/18. Новые11 API routes и /account в обеих оболочках; reviewed inventory/registry/OpenAPI/TS/proxy allowlist обновлены. Не ослаблять strict INDEX и нормализацию CRLF Dockerfile.

После распаковки stage scripts/auth17/files.txt и прогнать default gates; production builds: npm run build:all. На VM: api+web rebuild, explicit0029 --apply/--check, настройки/volumes/worker/MFA/CU profile сохранять. Pending seat request не оплачивает/не активирует место; trusted CLI manage_seats.py только после внешней проверки entitlement. Provider/proration/credit saga AUTH-18. Полная инструкция docs/auth17/deploy.md.
