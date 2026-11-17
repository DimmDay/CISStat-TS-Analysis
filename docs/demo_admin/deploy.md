# Уведомление администратору о первой выдаче демо

База: 709c52087589110171e35d8f5ed082c5c2956bdb. Цепочка поставки: ZIP → распаковка в checkout → локальные гейты → commit/push тимлидом → зелёный CI → pull/build/migrate/recreate на VM.

## Поведение

После подтверждения email и первой успешной выдачи личного MONO trial администратор получает отдельное обычное текстовое письмо. По умолчанию получатель admin@datasetup.ru, отправитель/SMTP — уже настроенные CISSTAT_AUTH_SMTP_*.

Тема: «Новый пользователь подтвердил email и получил демо-доступ».

Пример текста (синтетический адрес):

```text
Новый пользователь подтвердил email и получил демо-доступ.

Пользователь: new@example.test
Email подтверждён, демо выдано: 17.11.2026 15:30:00 МСК
Демо-доступ до: 01.12.2026 15:30:00 МСК

Выданные лимиты:
• Вычислительный бюджет: 100 CU
• Исследования: 10
• Одновременные вычисления: 1
• Строк в датасете: до 50000

Личное пространство MONO. Уведомление о первой выдаче демо-доступа.
```

В письме фактический snapshot выдачи: email, время/окончание в МСК (UTC+3), CU, исследования, concurrency и rows. Сокращённый прежним сроком аккаунта trial отображает реальное окончание. Нет кода, magic-link, cookie, CSRF, session token, пароля или ссылки входа. Начальная отправка письма пользователю, неподтверждённый email, неуспешная/откатившаяся выдача, повторный вход и прежние funded accounts не создают такое событие. Подтверждение ссылкой и кодом использует один источник события — receipt первой выдачи trial.

**Существующие пользователи не вызывают уведомление повторным входом.** Исторической рассылки/backfill нет. Для проверки без новой регистрации предусмотрена отдельная SMTP-проба ниже.

## Доставка и границы гарантии

Аддитивная0037 создаёт отдельную auth_demo_admin_notifications. Запись очереди и trial/resources/proof/session фиксируются одной транзакцией. При откате запись не остаётся. Схема0037 обязательна до запуска новой версии при включённых уведомлениях; сбой схемы — authority error, не тихая потеря события.

Существующий AUTH20 ops_sweeper в API required mode обрабатывает одну запись за цикл (обычно каждые30с, при очереди ожидание дольше). Отдельный контейнер/поток/cron не нужен. Audit/retention и уведомления независимы по обработке ошибок. SMTP не вызывается в login request и выполняется вне enrollment и claim SQL transactions. Отказ SMTP не мешает уже подтверждённому пользователю войти и пользоваться ресурсами; очередь остаётся pending с безопасным кодом smtp_unavailable. Backoff30/60/120… до3600с, попытки продолжаются. Два процесса используют SKIP LOCKED, lease3мин и claim_id fence; после падения процесса запись доступна повторно по истечении lease. Подтверждение старой lease не перезаписывает результат новой.

Одна receipt = одна запись очереди, обычные повторные входы/два workers не дублируют её. Однако SMTP не имеет атомарного commit с нашей БД: после принятия письма сервером и crash/неопределённого ответа до ack возможен повтор. Message-ID стабилен для события при неизменном домене отправителя; это идентификатор повторов, не гарантия дедупликации получателем. Честная гарантия — at-least-once при восстановлении БД/SMTP и работающем worker, не exactly-once. Получатель фиксируется при первой попытке доставки. Изменять recipient уже начатой очереди обычной сменой .env нельзя; при ошибочном адресе требуется отдельное операторское решение.

Отключение флага приостанавливает отправку и создание новых записей; уже pending сохраняются и продолжатся после включения. Данные очереди минимальны и защищены snapshot guard: поля события неизменяемы, содержат email/лимиты без proof; доступ — только server/operator DB. Записей текущего пилота не более100; автоматического удаления/изменения receipt нет.

## Настройки

В Compose api по умолчанию:

```dotenv
CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED=1
CISSTAT_DEMO_ADMIN_EMAIL=admin@datasetup.ru
```

Эти параметры передаются только api, не web. Новых секретов нет. Существующий .env сохраняется; если указанные параметры в нём отсутствуют, Compose подставит эти defaults. Для другого административного ящика изменить EMAIL; допускается один адрес. Для выключения ENABLED=0. Вне Compose feature по умолчанию выключена.

Автодоставка использует CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL (обычно30с); значение0 выключает существующий worker, включая уведомления. На этой VM должен оставаться CISSTAT_STORAGE_MODE=required. CLI status показывает interval и counts; процесс API можно дополнительно проверять через прежний health/ops/audit_sweeper. Статус CLI не означает, что SMTP уже принял письмо или что письмо находится во входящих.

## Локальная машина

Из корня репозитория, PowerShell:

```powershell
Expand-Archive -LiteralPath .\cisstat-demo-admin-709c520.zip -DestinationPath . -Force
git add --pathspec-from-file=scripts/demo_admin/files.txt
python scripts/local_gates.py --only personal-demo,auth20,auth00 --skip-install
# Полный штатный default прогон перед своим commit/push:
python scripts/local_gates.py --skip-install
```

Новые unit/native файлы автоматически подхватывают существующие personal-demo / personal-demo-postgres гейты и personal_demo.yml. Новый флаг гейта не вводится. Native требуется disposable CISSTAT_AUTH_TEST_DSN, права CREATE DATABASE и API requirements; не production БД. Запуск: `python scripts/local_gates.py --only personal-demo-postgres --with-personal-demo-postgres --skip-install`. Без DSN/skips результат не считается PASS. После своего commit можно повторить AUTH00 с `--auth00-target head`. GitHub изменения делает тимлид, агент commit/push не выполняет.

## VM: build → migration → recreate

После push и зелёного CI, команды из корня checkout. Пересобирается **только api**; web-код и browser assets не менялись.

```bash
set -euo pipefail
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
cd deployment/cisstat-stack
# Существующий .env не заменять .env.example.
dc() {
  env -u CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED -u CISSTAT_DEMO_ADMIN_EMAIL \
      -u CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL \
      -u CISSTAT_AUTH_SMTP_HOST -u CISSTAT_AUTH_SMTP_PORT \
      -u CISSTAT_AUTH_SMTP_USER -u CISSTAT_AUTH_SMTP_PASSWORD \
      -u CISSTAT_AUTH_SMTP_FROM -u CISSTAT_AUTH_SMTP_TLS \
      docker compose "$@"
}
dc build api
dc run --rm --no-deps api python scripts/demo_admin/migrate.py --apply
dc run --rm --no-deps api python scripts/demo_admin/migrate.py --check
dc up -d --no-deps --force-recreate api
dc ps api
dc exec api python scripts/demo_admin/manage.py status
dc exec api python scripts/demo_admin/manage.py smtp-test
```

Проба отправляет письмо с темой «CISStat — проверка уведомлений администратору» **только настроенному административному получателю**, не создаёт пользователя/trial и не содержит login proof. Ответ smtp_accepted:true означает принятие SMTP relay; проверить входящие/спам admin@datasetup.ru (и настроенную пользователем переадресацию в Gmail). Реальная доставка в этой сессии не выполнялась: SMTP/VM секретов здесь нет.

Далее новым email получить первый личный trial. Через обычный цикл (обычно около30с без очереди) должно прийти отдельное уведомление с email/временем/лимитами. Повторный вход тем же email не должен отправлять новое письмо или пополнять trial.

Диагностика:

```bash
dc exec api python scripts/demo_admin/manage.py status
# Вручную обработать одну готовую запись (не обходит backoff/lease):
dc exec api python scripts/demo_admin/manage.py deliver
```

counts.pending — ожидание/повтор; sending — действует lease; sent — SMTP принял и ack записан, не гарантия входящих. retrying>0 — был отказ отправки. Не выводить содержимое очереди, секреты .env или SMTP debug. После исправления SMTP очередь продолжит попытки сама; recreate не стирает её. При отключении функции поставить ENABLED=0 и recreate api; миграцию0037/receipts/кошельки/volumes не удалять.

## Роуты и проверка

Новых HTTP-маршрутов/Next pages/proxy/registry нет. Consume сохраняет контракт/путь; дополнительный эффект — атомарная запись внутренней очереди. AUTH00 review обновляет этот admission и существующий worker (его source line сдвинулась103→104, добавлен SMTP effect), fingerprints и inventory.md. Actual OpenAPI check_routes должен показывать282 API/286 bindings/661 entries без added/missing. Обновление scripts/local_gates.md описывает расширение существующего гейта; scripts/local_gates.py и workflow менять не требуется.

Подробные фактические результаты — scripts/demo_admin/protocols и worklog/worklog12.md. Tests заменяют только транспорт/factory маршрутизацию к disposable schema, используют реальные PostgreSQL tx/constraints/lease. Реальные SMTP acceptance/inbox, VM docker build/recreate и мобильная приёмка остаются шагами оператора.

Финальная приёмка DEMO-ADMIN-NOTIFY:23 real-PG tests без skips (20 SQL/HTTP router cases +2 full personal HTTP scientific pipeline +1 status privacy;10 новых admin tests), unit31/31, local gates personal-demo (11 Python+8 Jest) и auth20 (17 Python) PASS. AUTH00 inventory unit38/38; actual check_routes282 API/286 bindings/661 entries added=[]/missing=[]; HTTP method/path IDs полностью совпадают с709c520. Review обновляет internal enqueue, personal_demo.enroll и existing worker (auth.ops_delivery policy); strict temporary INDEX parity598 PASS, настоящий INDEX/HEAD не изменён. Обе Next production builds PASS, whitespace PASS. Полный default32-gate, native всей платформы, Docker image build/VM recreate, реальные SMTP/inbox/mobile не заявляются. Native runner discovery видит все23 cases автоматически. ZIP проверяется CRC/manifest/every-byte; git commit/push делает тимлид.
