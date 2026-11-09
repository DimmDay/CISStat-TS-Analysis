# AUTH-15 — установка поверх b9af29b

Поставка: task-only overlay, исходный HEAD b9af29bf9e359403db16b280fe8c1ab402597e85. ZIP → локальная машина тимлида → его commit/push → pull VM. Из сессии GitHub/VM не изменяются.

## Локальная приёмка

Распаковать ZIP в корень checkout; просмотреть manifest. Установить API/contract dependencies и `npm ci` при необходимости. Нативные тесты — только отдельная disposable БД, никогда production:

```bash
git status --short
git add --pathspec-from-file=scripts/auth15/files.txt
python scripts/local_gates.py --skip-install
# CISSTAT_AUTH_TEST_DSN уже задан для disposable PostgreSQL
python scripts/local_gates.py --only auth15-postgres --skip-install
npm run build:all
# После своего commit, перед push:
python scripts/local_gates.py --auth00-target head --skip-install
```

AUTH-00 сохраняет строгие INDEX/HEAD fences, не выполняет staging автоматически. При FAIL читать logs/local_gates/auth00.log; WORKTREE source drift не лечится одним git add. Сценарии native повторяются на CI PostgreSQL16/18; Windows contract gate отдельно.

## VM

Перед установкой дождаться завершения старых jobs и остановить новое admission на время замены API; не запускать старые и новые binaries над одной очередью. Сохранить PostgreSQL, MFA/worker secrets и все существующие volumes. Новых обязательных env нет; CU profile настройки не меняются и новый benchmark не требуется (science kernels не менялись).

```bash
# После собственного push и зелёного CI, из существующего checkout VM:
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose run --rm --no-deps -T api python scripts/auth15/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth15/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth15/migrate.py --check
```

Explicit additive0027 применяет недостающие0025/0026 штатной цепочкой, прежние SQL/checksums сохранены. Повтор apply возвращает applied:false. Никаких request-time DDL. Откат кода возможен после остановки новых demo входов/работы; не удалять grant/usage/audit строки и не ослаблять protected guards. Старый session loader не поддерживает новую credential family: после отката demo недоступно, личные sessions сохраняют прежний контракт. Работать с финансовым release/refund вручную нельзя.

## Приёмка функционала

1. Личный ADMIN+MFA → `/admin/demo-campaigns` в обеих оболочках. Все лимиты, dates UTC, origins и причина вводятся явно. 1 CU=1 000 000 micro-CU. Own upload изначально выключен. Сервер разрешает только текущий Demo ceiling.
2. Создать черновик, сохранить одноразово показанный пароль для флаера. Активировать после проверки окна/числа участников/бюджета. Activation не запускается автоматически из миграции. `/demo` принимает login/password; до выдачи сохраняется HttpOnly resume-cookie. Пароль/токены в URL не передаются.
3. Два независимых профиля браузера → разные grant/account/run; чужие ID дают404. После logout повтор enter/resume восстанавливает свой grant, прежние expiry/usage сохраняются. Resume proof host-only: второй origin/новый профиль может считаться новым посетителем в мягком режиме, но общий max grants/end остаётся прежним.
4. Pause/revoke закрывают следующий запрос и worker authority; resume не продлевает grants. Rotation отзывает текущие sessions, меняет только shared secret, не создаёт новых grants. MFA старше5 минут: повторить личный login+MFA по ссылке UI (новый grant администратора не требуется).
5. Для общего компьютера кнопка «Завершить демо на этом устройстве» отзывает свой grant и cookies; новая выдача отдельно учитывается в max grants. Научные объекты сохраняются до cleanup AUTH-16.
6. Usage показывает finite ledger ceilings/spent/reserved; обычный журнал использует существующий auth_audit_outbox/security_audit.

## Границы

AUTH-15 реализует campaign admin и private entry с минимально необходимыми current grant/status/time checks. AUTH-16 — одноразовые admission codes, квотирование всех дешёвых HTTP операций, cleanup/retention и отдельная эксплуатационная сертификация отмены. AUTH-15 не объявляет весь научный HTTP финансово metered: существующие AUTH-12/13/14 reservations используют подготовленную sponsor→campaign→account→grant цепочку, но оставшиеся admission adapters относятся к AUTH-16. Полноценный публичный форумный запуск проводить после AUTH-16 и AUTH-CERT. На VM этой сессией ничего не активировано; фактические пределы участников/времени/бюджета задаёт оператор.
