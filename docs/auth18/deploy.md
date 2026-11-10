# AUTH-18 — установка поверх 3ca5e4e

ZIP содержит только новые/обновлённые файлы задачи. Репозиторий/VM эта сессия не изменяет. Перед переносом — штатный backup PostgreSQL/.env и volumes. AUTH-18 добавляет0030;0019…0029/checksums не меняются. Нужна пересборка api и web; научные kernels/compute*.py не менялись, перекалибровка CU не требуется.

## Локальная машина

Распаковать в корень checkout на3ca5e4ed0742b5dce6c811f048ed3648817eafa6. Сверить scripts/auth18/files.txt, затем:

```powershell
git add --pathspec-from-file=scripts/auth18/files.txt
python scripts/local_gates.py --skip-install
# При установленном disposable PostgreSQL и CISSTAT_AUTH_TEST_DSN:
python scripts/local_gates.py --only auth18,auth18-postgres --skip-install
npm run build:all
# После собственного commit, до push:
python scripts/local_gates.py --auth00-target head --skip-install
```

## VM — безопасная установка с выключенной оплатой

После собственного push и зелёного CI, из checkout VM:

```bash
set -euo pipefail
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose run --rm --no-deps -T api python scripts/auth18/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth18/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 \
    docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth18/migrate.py --check
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops
docker compose ps
```

По умолчанию `CISSTAT_YOOKASSA_ENABLED=off`, новый worker profile не запускается. Никаких платных запросов/новых credits миграция не создаёт. Existing User/Account/tenant/run/reservations/списания не меняются.

## Изолированный тестовый магазин

Только для специально выделенного sandbox Account и тестового магазина ЮKassa. Нельзя регистрировать основной пользовательский Account как sandbox: test succeeded активирует его seats, поэтому тестовая идентичность/данные должны быть изолированы. До любого payment POST адаптер проверяет `/me`: enabled shop, точный account_id, test=true. Настоящие платежи (`test=false`) адаптер отвергает; live режим кодом закрыт до утверждённых коммерческих и фискальных условий.

В `.env` VM вручную указать shop ID и **тестовый** секрет, не помещая их в shell history/ZIP/Git:

```dotenv
CISSTAT_YOOKASSA_ENABLED=test
CISSTAT_YOOKASSA_SHOP_ID=YOUR_TEST_SHOP_ID
CISSTAT_YOOKASSA_SECRET_KEY=YOUR_TEST_SECRET_KEY
```

Пересоздать api с новыми env, затем в интерактивном терминале зарегистрировать существующий оплаченный/разрешённый sandbox цикл:

```bash
docker compose up -d --no-deps api
# Значения: ваши утверждённые целочисленные копейки/micro-CU, версии terms/прайса;
# ends-at ОБЯЗАН совпадать с plan_expires_at Account, заданным через AUTH-08.
# Никакие примерные цены не являются действующим прайсом.
docker compose exec api python scripts/auth18/provision_cycle.py ACCOUNT_UUID \
  --starts-at YOUR_ISO_START --ends-at YOUR_ISO_END \
  --seat-price-minor APPROVED_MINOR --included-per-seat APPROVED_MICRO_CU \
  --price-version APPROVED_PRICE_VERSION --terms-version APPROVED_TERMS_VERSION \
  --reason 'Approved isolated sandbox cycle'
docker compose --profile billing-test build billing-worker
docker compose --profile billing-test up -d --no-deps billing-worker
```

Для zero-refund reduction только после утверждения соответствующих условий добавить `--allow-reduction`. Без него уменьшение/нулевое изменение запрещено. Регистрация цикла не продлевает plan_expires_at, не меняет seats и не начисляет spendable CU. Renewal/rollover и source-aware spend — AUTH-21; повторная регистрация существующего Account запрещена, историю не удалять.

В кабинете тестового магазина Integration → HTTP notifications указать `https://api.datasetup.ru/v1/billing/webhooks/yookassa`, события payment.succeeded/payment.canceled/payment.waiting_for_capture. Это direct API ingress; first-party browser proxy требует CSRF и для провайдера не используется. Caddy уже проксирует API host. Callback не имеет browser authority: только enqueue, затем authenticated GET, точная проверка shop/test/id/order/digest/amount/currency. Поддельный callback не подтверждает платёж. ЮKassa не использует описанный в абстрактной архитектуре HMAC header; применяется её официальный current-object verification протокол.

OWNER `/account`: заявка мест → «Рассчитать стоимость» → просмотреть quote/terms/expiry → «Подтвердить предложение» → «Обновить статус оплаты» → ссылка ЮKassa. Worker сначала создаёт checkout; ссылка появляется после обновления статуса. После тестовой оплаты обновить статус и Account. Редирект возвращает на главную, сам ничего не активирует. Другой OWNER/MEMBER/API key/demo не может подтвердить чужой quote. Replay не создаёт второй заказ.

## Неизвестный платёж и сверка

POST имеет постоянный UUID Idempotence-Key, повтор только23h с первого claim (у провайдера окно24h). После этого неизвестный результат — review_required. Найти payment ID в кабинете магазина по order metadata и поставить на authenticated GET:

```bash
docker compose exec api python scripts/auth18/reconcile.py ORDER_UUID PROVIDER_PAYMENT_ID \
  --reason 'Recovered unknown outcome in merchant dashboard'
```

CLI требует terminal и точный order UUID. Не вводить секрет/номер карты. Worker не верит оператору на слово, он проверяет платеж через API. Если Account/OWNER/request/version/cycle ещё действительны — единый commit seats+receipt+audit+allocation; иначе paid_review. Paid_review сохраняет оплату, не выпускает места; оператор проводит контролируемый возврат через кабинет/будущий AUTH-23. Не очищать заказ и не создавать повторную оплату. Автоматического refund/chargeback API эта задача не добавляет.

Included entitlement хранится как immutable signed proration ledger; в общий spendable CU бюджет оно пока не смешивается. Расход/reserved остаются прежними. Источники/expiry/carry/rollover и выдача доступных included CU подключаются AUTH-21. Это не top-up checkout AUTH-22.

При остановке контура: `docker compose --profile billing-test stop billing-worker`, выключить env и пересоздать api. Сохранить inbox/order/adjustments0030 и старые receipts, обеспечить сверку уже созданных платежей. Не выполнять down -v и обратную DDL миграцию. Удалять paid history запрещено.
