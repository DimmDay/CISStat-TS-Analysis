# Локальные гейты перед передачей в GitHub

AUTH-17 применяется поверх 201a3b1f12eac55525fb07301b5e37f8e962d938. AUTH-01…16 и Dockerfile CRLF hotfix уже в базе. Команды из корня checkout. Состав: `python scripts/local_gates.py --list`.

## До коммита: явно подготовить Git index

После распаковки ZIP просмотрите и добавьте только файлы текущей поставки:

```bash
git status --short
git add --pathspec-from-file=scripts/auth20/files.txt
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

Default: auth22, auth21, auth20, auth19, auth18, auth17, auth16, auth15, auth14, auth13, auth12, auth11, auth10, auth09, auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Все `*-postgres` гейты — opt-in: без соответствующего `--with-authXX-postgres` они не входят в прогон (в сводке после зелёного прогона честно печатается, какой live PostgreSQL остался непроверен). Jest включает renderer build и typecheck обеих оболочек. Production builds: `npm run build:all`. Scientific pytest — `--with-pytest`; средовые сбои сравниваются с чистой базой.

AUTH-12 unit использует scripts/auth12/requirements.txt без полного scientific runtime. Native gate требует полный API runtime и настоящий disposable PostgreSQL, никогда production БД:

```bash
# CISSTAT_AUTH_TEST_DSN уже задан в защищённом окружении.
python scripts/local_gates.py --only auth12,auth12-postgres
# либо вместе с default:
python scripts/local_gates.py --with-auth12-postgres --skip-install
```

Без DSN/при skips native не PASS. `.github/workflows/auth12.yml`: Ubuntu/Windows unit; PostgreSQL16/18 native Ubuntu. Linux проверки не заменяют настоящий Windows CI. Все прежние PostgreSQL opt-in сохранены; auth07 также выполняет windows_parity.py с запретом Unix-only resource.

## AUTH-20 — audit/operations и миграционный rollout (поверх c08ee9e)

Default-гейт `auth20` (unit: lockdown fail-closed values, marks validation, каталог 42 с обязательным `auth_ops_changed`, bounds sweeper) и opt-in `auth20-postgres` (native: capture-триггеры 0032 на восьми таблицах, marks export, restore-эмуляция + reconcile/idempotency, tombstone grant, unrepairable consumed, quarantine, lockdown на 4 входах, идемпотентная delivery audit outbox, prune retention, health auth_ops). Native требует disposable PostgreSQL и полный API runtime:

```bash
python scripts/local_gates.py --only auth20 --skip-install
python scripts/local_gates.py --only auth20,auth20-postgres --skip-install
# либо вместе с default:
python scripts/local_gates.py --with-auth20-postgres --skip-install
```

`.github/workflows/auth20.yml`: Ubuntu/Windows unit; PostgreSQL 16/18 native Ubuntu. Роуты НЕ затронуты: HTTP methods/paths, DTO/OpenAPI/TS/BFF bindings без изменений (274 API, 278 bindings; добавлен один non-HTTP surface — in-process sweeper-поток `worker:apps/api/authentication/ops_sweeper.py:103`, policy `ops.diagnostics`, inventory 650→651, worker 10→11). Проверка: `python scripts/auth06/check_routes.py`. Каталог audit честно скорректирован: пин DOCLOG-8 37 был устаревшим (фактически 41 после AUTH-13/15/16), AUTH-20 добавляет обязательное `auth_ops_changed` → 42; пин обновлён с объяснением.

Новая explicit migration 0032 через `scripts/auth20/migrate.py --apply/--check` (цепочка гарантированно применяет 0029/0030 перед 0031/0032; request-time auto-DDL нет). VM требует пересборку api; web байты прежние. Отчёт об операциях: `scripts/auth20/reconcile.py --export|--reconcile|--quarantine|--drain-audit|--prune`. Kill-switch rollback — env `CISSTAT_AUTH_LOCKDOWN` (пустое/`0` = выключено). Порядок развёртывания, backup/export/restore, quarantine и откат — docs/auth20/runbook.md.

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

## AUTH-18 — ЮKassa / subscription seats

`auth18` входит в default прогон и проверяет HTTP adapter + integer proration без магазина.
`auth18-postgres` — обязательный отдельный native gate, DSN disposable PostgreSQL16/18:

```powershell
git add --pathspec-from-file=scripts/auth18/files.txt
python scripts/local_gates.py --skip-install
python scripts/local_gates.py --only auth18,auth18-postgres --skip-install
```

Без `CISSTAT_AUTH_TEST_DSN` native runner возвращает2; skip не PASS. CI `.github/workflows/auth18.yml`: Windows/Linux contracts, PG16/18 native. Протоколы `scripts/auth18/protocols/`. Настоящие provider credentials не нужны для gates, все HTTP ответы controlled MockTransport; реальная сеть магазина не вызывается. После commit перед push — `--auth00-target head`. `check_routes` подтверждает четыре добавленных API surfaces. Live checkout запрещён кодом; инструкция тестового магазина — `docs/auth18/deploy.md`.

## AUTH-19 — OIDC / personal trial / email self-service (база 8ec771d)

`auth19` входит в default прогон и проверяет OIDC adapter (PKCE/state/nonce/RS256 JWKS), email-секреты (keyed HMAC, uniform ответы) и POST-only consume контракты без сети.
`auth19-postgres` — обязательный отдельный native gate, DSN disposable PostgreSQL16/18:

```bash
git add --pathspec-from-file=scripts/auth19/files.txt
python scripts/local_gates.py --skip-install
python scripts/local_gates.py --only auth19,auth19-postgres --skip-install
```

Без `CISSTAT_AUTH_TEST_DSN` native runner возвращает 2; skip не PASS. CI `.github/workflows/auth19.yml`: Windows/Linux contracts, PG16/18 native. IdP/SMTP заменяются controlled fakes (httpx.MockTransport/FakeDelivery), RSA-ключи генерируются в тесте; реальная сеть не вызывается. После commit перед push — `--auth00-target head`. `check_routes` подтверждает четыре добавленных POST surfaces (`/v1/auth/oidc/start`, `/v1/auth/oidc/callback`, `/v1/auth/email/start`, `/v1/auth/email/consume`) и расширение каталога audit 36→37 (`auth_identity_changed` mandatory). Оба контура выключены по умолчанию (OIDC: ISSUER+CLIENT_ID; email: EMAIL_KEY+SMTP_HOST) — флаги видны в GET /v1/auth/csrf. Миграция 0031 расширяет AUTH-15 `auth15_session_family` на третий тип сессии (credential NULL + grant NULL); checksums 0019–0030 не меняются. Миграция/готовность — `scripts/auth19/migrate.py --apply/--check`; инструкция `docs/auth19/deploy.md`.

## AUTH-21 — Source-aware Wallet/CreditLot (поверх a0a2af6)

`auth21` входит в default прогон первым и проверяет контракты FEFO/выдачи/классификации хвостов без БД. `auth21-postgres` — обязательный отдельный native gate (disposable PostgreSQL 16/18), паттерн запуска прежний:

```bash
git add --pathspec-from-file=scripts/auth21/files.txt
python scripts/local_gates.py --skip-install
python scripts/local_gates.py --only auth21,auth21-postgres --skip-install
```

Без `CISSTAT_AUTH_TEST_DSN` native runner возвращает 2; skip не PASS. CI `.github/workflows/auth21.yml`: Ubuntu/Windows contracts + PG16/18 native. Роуты НЕ затронуты: ни одного нового/удалённого HTTP-маршрута (actual 274 = inventory 274, bindings 278, added/missing=[]); изменения исполнения — хуки кошелька внутри существующих AUTH-12 handlers (reserve/extend/settle/release), inventory 651, отпечатки 456→464. Каталог audit 42→43: новое обязательное `auth_wallet_changed` (пины test_auth20_ops/test_doclog8 обновлены с обоснованием). До операторского `create-wallet` поведение платформы идентично AUTH-20: строка кошелька — аддитивный выключатель; деньги/платежи — AUTH-22/23, UI — AUTH-24. Инструкция VM — `docs/auth21/deploy.md` (пересборка только api, миграция explicit 0033; web/compose/env не менялись).

## AUTH-22 — Quote/top-up checkout и credit (поверх 7d233ad)

`auth22` входит в default прогон первым и проверяет контракты каталога/снимка/state machine/DTO/webhook-словаря без БД. `auth22-postgres` — обязательный отдельный native gate (disposable PostgreSQL 16/18), паттерн прежний:

```bash
git add --pathspec-from-file=scripts/auth22/files.txt
python scripts/local_gates.py --skip-install
python scripts/local_gates.py --only auth22,auth22-postgres --skip-install
# либо native вместе с default:
python scripts/local_gates.py --with-auth22-postgres --skip-install
```

Без `CISSTAT_AUTH_TEST_DSN` native runner возвращает 2; skip не PASS. CI `.github/workflows/auth22.yml`: Ubuntu/Windows contracts + PG16/18 native. **Роуты затронуты: +3 OWNER-маршрута** (`GET /v1/billing/{account_id}/topups`, `POST /v1/billing/{account_id}/topup-quotes`, `POST /v1/billing/{account_id}/topups`): actual 277 = inventory 277, bindings 281 (+3, операция `billing.topup`), added/missing=[]; научные пути не переименованы. Inventory 651→654, OpenAPI/TS/proxy allowlist перегенерированы (порядок: производные → inventory). Webhook-маршрут не добавлялся — существующий wake-up расширен на topup-заказы (to_regclass-гвард до применения 0034).

Миграция 0034 explicit: `scripts/auth22/migrate.py --apply/--check` (цепочка гарантирует 0019…0033). Контур выключен по умолчанию: без провижиненных пакетов (`manage_topups.py add-package`) и кошелька (AUTH-21 CLI) проверка честно отвечает `topup_not_configured`/`wallet_required`. UI-секция «Пополнение баланса CU» (TopupPanel) в обеих оболочках только для paid MULTI. Инструкция VM — `docs/auth22/deploy.md` (пересборка api И web, миграция 0034; compose/env не менялись — billing-worker прежний образ получает шаг topup-саги автоматически). Refund/dispute — AUTH-23, wallet/ledger READ-эндпоинты — AUTH-24.

## AUTH-22 HOTFIX-01 — auth22-postgres выполнялся без флага (база 7d233ad)

Дефект первой поставки AUTH-22: гейт `auth22-postgres` добавлен в `GATES`, но не в opt-in механику — отсутствовали `--with-auth22-postgres` и `excluded.add("auth22-postgres")`. Поэтому он один из всех native-гейтов запускался в default прогоне, без `CISSTAT_AUTH_TEST_DSN` честно возвращал 2 (`Set CISSTAT_AUTH_TEST_DSN... No tests ran`) и ронял прогон за <1 c. Заодно устранён дрейф того же класса от AUTH-20/21: `missing_live`-подсказка не называла auth21, footnote `--list` и строки `--only`/`parser.error` — флаги/имена auth20–22; эти строки теперь строятся из `GATES` программно. Поведенческие изменения только в выборе гейтов: default-прогон снова зелёный без DSN (native — по флагу), сам native-гейт и его CI не менялись. После распаковки hotfix: `git add --pathspec-from-file=scripts/auth22/files.txt`, затем `python scripts/local_gates.py --skip-install`; smoke: `python scripts/local_gates.py --list` (`auth22-postgres` без `*`) и `python scripts/local_gates.py --only auth22,auth22-postgres --skip-install` с DSN.

## AUTH-23 — Refund/dispute/chargeback workflow (поверх 004dba5)

`auth23` входит в default прогон первым и проверяет state-машины возврата/спора, окно, валидацию provider-refund, DTO и safe-коды без БД. `auth23-postgres` — обязательный отдельный native gate (disposable PostgreSQL 16/18), паттерн прежний:

```bash
git add --pathspec-from-file=scripts/auth23/files.txt
python scripts/local_gates.py --skip-install
python scripts/local_gates.py --only auth23,auth23-postgres --skip-install
# либо native вместе с default:
python scripts/local_gates.py --with-auth23-postgres --skip-install
```

Без `CISSTAT_AUTH_TEST_DSN` native runner возвращает 2; skip не PASS. CI `.github/workflows/auth23.yml`: Ubuntu/Windows contracts + PG16/18 native. **Роуты затронуты: +2 OWNER-маршрута** (`POST /v1/billing/{account_id}/topups/{order_id}/refunds`, `GET /v1/billing/{account_id}/refunds/{refund_id}`): actual 279 = inventory 279, bindings 283 (+2, операция `billing.refund`), added/missing=[]; научные пути не переименованы; webhook-маршрут прежний (refund-статус подтверждает только сага через GET). Inventory 654→656, OpenAPI/TS/proxy allowlist перегенерированы (порядок: производные → inventory); policy_review: политика `billing.refund` + 2 классификации + честное обновление target `billing.topup`.

Миграция 0035 explicit: `scripts/auth23/migrate.py --apply/--check` (цепочка гарантирует 0019…0034). Контур выключен по умолчанию: без credited-заказа (AUTH-22) возврат невозможен; споры открываются только trusted CLI `scripts/auth23/manage_refunds.py` (dispute-open/dispute-resolve/refund-reconcile), клиентского HTTP-маршрута спора нет. Окно возврата — env `CISSTAT_TOPUP_REFUND_DAYS` (default 14, границы 0…90, фиксируется в записи). Инструкция VM — `docs/auth23/deploy.md` (пересборка api, миграция 0035; web не менялся — только авто-генерируемый TS-контракт). Refund-панель UI и wallet/ledger READ-эндпоинты — AUTH-24, payment reconciliation/launch runbook — AUTH-25.
