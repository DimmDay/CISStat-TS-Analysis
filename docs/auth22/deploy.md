# AUTH-22 — установка на VM

База: `7d233ad` (AUTH-21 уже на VM, образы собраны, 0033 --apply/--check выполнены). Поставка: task-only ZIP `cisstat-auth22-7d233ad.zip` (точное множество — `scripts/auth22/files.txt`). Цепочка: ZIP → локальная машина → push тимлида → VM pull.

## Изменённые поверхности

- **api-образ**: `apps/api/billing/topups.py`/`topup_contract.py`/`topup_migrations.py`, миграция `0034_auth22_topups.sql`, hook `credit_purchased_order` в `wallet.py`, safe-коды в `context.py`, расширение `routers/billing.py` (+3 маршрута, wake-up), `provider.py` (опциональный description), `scripts/auth18/worker.py` (шаг topup-саги), CLI `scripts/auth22/{migrate,manage_topups}.py`, Dockerfile import-guard.
- **web-образ МЕНЯЛСЯ**: `TopupPanel.tsx`, `AccountScreen.tsx`, `lib/billing.ts`, перегенерированный `access-contract.generated.ts` — пересборка web обязательна.
- compose/env/volumes — без изменений: billing-worker продолжает команду `scripts/auth18/worker.py --loop` и после пересборки образа шагает обе саги. Новых обязательных env нет; провижининг каталога/кошелька — CLI.

## Команды на VM

```bash
cd /path/to/cisstat && git pull --ff-only

# 1) Пересобрать api и web (UI изменился)
docker compose build api web

# 2) Явная миграция 0034 (цепочка гарантирует 0019…0033; повтор apply=false)
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose run --rm --no-deps api python scripts/auth22/migrate.py --apply
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose run --rm --no-deps api python scripts/auth22/migrate.py --check

# 3) Перезапуск api и web
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose up -d --no-deps api web

# 4) Контроль готовности
docker compose exec -T api python scripts/auth22/migrate.py --check
curl -fsS https://api.datasetup.ru/health | head -c 400; echo
```

Окно обновления: до применения 0034 новые маршруты честно отвечают 503 (check_schema), существующие маршруты и webhook работают (to_regclass-гварды); после применения контур остаётся выключенным до провижининга каталога.

## Провижининг (по операторскому решению, только явные команды)

Кошелёк — контур AUTH-21 (`manage_wallet.py create-wallet`). Каталог пакетов — AUTH-22:

```bash
docker compose exec -T api python scripts/auth22/manage_topups.py add-package \
  --title "100 CU" --units 100000000 --price-minor 4900 \
  --price-version price-v1 --terms-version terms-v1 --reason "approved catalog"
docker compose exec -T api python scripts/auth22/manage_topups.py packages
docker compose exec -T api python scripts/auth22/manage_topups.py status --account-id <UUID>
```

Пакеты immutable: изменение прайса = новый пакет + `disable-package` (история сохраняется). До провижининга кнопки покупки показывают «Пополнение CU ещё не настроено».

## Recovery (исключительные ситуации)

```bash
# Неизвестный исход платежа: повторная постановка в очередь (API-proof обязателен)
docker compose exec -T api python scripts/auth22/manage_topups.py reconcile \
  --order-id <UUID> --payment-id <provider-payment-id> --reason "provider confirmed off-band"
# Деньги подтверждены, кредит невозможен автоматически (wallet locked): ручной кредит + CAS-переход
docker compose exec -T api python scripts/auth21/manage_wallet.py issue-purchased \
  --account-id <UUID> --units <micro-CU> --origin-order <order_id> --reason "manual credit"
docker compose exec -T api python scripts/auth22/manage_topups.py credit-paid \
  --order-id <UUID> --reason "operator resolution"
```

## Откат

- Код: предыдущий образ api/web (0034 аддитивна; старый образ работает с ней без изменений — notify/claim защищены `to_regclass`).
- DDL-откат и `down -v` запрещены (финансовая история retained: заказы, inbox, лоты, аудиты).
- Отключение контура без отката кода: `disable-package` всем пакетам (UI честно показывает «не настроено»); webhook/worker остаются безопасными wake-up'ами.

## Границы

Реальный магазин/live-платежи кодом запрещены (`YooKassa(sandbox=True)`); тестовый магазин — только для изолированных sandbox Account (docs/auth18/deploy.md). Коммерческий запуск (реальный прайс, условия, фискализация) — отдельная поставка до включения каталога. Refund/dispute/chargeback — AUTH-23; wallet/ledger READ и финансовая приватность MEMBER — AUTH-24.
