# AUTH-21 — установка на VM

База: `a0a2af6` (AUTH-20 уже на VM, образы собраны). Поставка: task-only ZIP `cisstat-auth21-a0a2af6.zip` (точное множество — `scripts/auth21/files.txt`). Цепочка: ZIP → локальная машина → push тимлида → VM pull.

## Изменённые поверхности

- **api-образ**: новый код `apps/api/billing/wallet*.py`, хуки в `coordinator.py`, миграция `0033_auth21_wallet.sql`, CLI `scripts/auth21/{migrate,manage_wallet}.py`, Dockerfile import-guard.
- **web-образ НЕ менялся** (UI/DTO не затронуты, `routers/billing.py` прежний) — пересборка web не требуется.
- Новых обязательных env, volumes и compose-правок **нет**; compose не менялся.

## Команды на VM

```bash
cd /path/to/cisstat && git pull --ff-only

# 1) Пересобрать ТОЛЬКО api (web не менялся)
docker compose build api

# 2) Явная миграция 0033 (цепочка гарантирует 0019…0032; повтор apply=false)
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose run --rm --no-deps api python scripts/auth21/migrate.py --apply
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose run --rm --no-deps api python scripts/auth21/migrate.py --check

# 3) Перезапуск api
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose up -d --no-deps api

# 4) Контроль: /health/ops прежний (AUTH-21 поверхность не добавлял);
#    readiness кошелька — CLI
docker compose exec -T api python scripts/auth21/migrate.py --check
```

## Провижининг кошелька (после деплоя, по операторскому решению)

Кошелёк не создаётся автоматически ни для одного Account. Выдача — только явные команды с reason (обязательный аудит `auth_wallet_changed` в той же транзакции):

```bash
docker compose exec -T api python scripts/auth21/manage_wallet.py create-wallet --account-id <UUID> --reason "AUTH-21 provisioning"
docker compose exec -T api python scripts/auth21/manage_wallet.py issue-included --account-id <UUID> --cycle-id <UUID> --ref base --reason "cycle base issuance"
docker compose exec -T api python scripts/auth21/manage_wallet.py issue-purchased --account-id <UUID> --units <micro-CU> --origin-order <order-ref> --reason "approved top-up basis"
docker compose exec -T api python scripts/auth21/manage_wallet.py status --account-id <UUID>
docker compose exec -T api python scripts/auth21/manage_wallet.py sweep --reason "cycle rollover hygiene"
```

Величина included-лота вычисляется из строки цикла AUTH-18 (формула `cumulative_allocation`), а не передаётся клиентом; purchased в v1 бессрочен и уникален по `origin_order`; promotional — с явным основанием и опциональным сроком.

## Откат

- Код: предыдущий образ api (миграция 0033 аддитивна, старый образ работает с ней без изменений — хуки кошелька защищены `to_regclass` и отсутствием строки кошелька).
- DDL-откат и `down -v` запрещены (финансовая история retained, гварды 0033).
- До провижининга кошельков поведение платформы байт-в-байт совпадает с AUTH-20.
