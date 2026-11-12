# AUTH-24 — деплой на VM (Wallet permissions/UI и lifecycle)

База: 32e0f50. Поставка: `download/cisstat-auth24-32e0f50.zip` — точное множество `scripts/auth24/files.txt` (CRC/байты/SHA256 проверены упаковщиком). Правит только READ-поверхность AUTH-24: +2 GET-маршрута `/v1/billing/{account_id}/wallet[/ledger]`, проекции `apps/api/billing/wallet_views.py`, UI WalletPanel/refund-действие в обеих оболочках. **Новой миграции нет** — схема 0033 (AUTH-21) уже применена на VM; env/compose/volumes не менялись.

## Порядок

```bash
cd /opt/cisstat/CISStat-TS-Analysis   # путь чекаута на VM
git pull --ff-only                    # после пуша тимлида
docker compose build api web          # пересборка ОБЕИХ образов: api — python-код, web — UI запечён в Next build
docker compose up -d --no-deps api web

# Живость: /health наружу отдаёт ТОЛЬКО api-хост (Caddyfile:
# api.datasetup.ru -> api:8000). На апексе datasetup.ru тот же путь
# отвечает 404 -- апекс ведёт на web:3000 (Next.js shell, без /health).
curl -fsS https://api.datasetup.ru/health | head -c 400; echo
curl -fsSI https://datasetup.ru/ | head -n 1
```

Миграции `--apply` не требуются: 0019–0035 уже применены (последняя — 0035 AUTH-23). Проверить идемпотентность при желании: `docker compose exec -T api python scripts/auth23/migrate.py --check` → `applied=false`, `ok=true`.

## Поведение после деплоя

- До провижининга кошелька (AUTH-21 CLI `manage_wallet.py create-wallet`) поведение платформы идентично AUTH-23: WalletPanel в «Аккаунте» скрыта (`wallet_required`), топап-панель у OWNER платного MULTI ведёт себя как прежде.
- После провижининга: OWNER видит «Аккаунт → Баланс CU» (доступно по источникам, резерв, дата сгорания, журнал), MEMBER — только суммарный остаток и подсказку «обратитесь к владельцу» (§13.6/13.8; никаких денег и разбивки источников).
- Покупка (`TopupPanel`) рендерится только при `can_manage` (§13.3 «OWNER покупает»); сервер остаётся authority (403 `owner_required` для MEMBER — без изменений).
- Self-service возврат (AUTH-23): OWNER видит «Запросить возврат» на credited-заказах в пределах окна `CISSTAT_TOPUP_REFUND_DAYS` (default 14). Состояние возврата — из ответа сервера; спор/обязательный возврат остаются trusted CLI AUTH-23.

## Откат

Откат — предыдущие образы api/web (`docker compose up -d --no-deps --force-recreate` после `git checkout <prev>`). READ-маршруты исчезают вместе с образом; данных в БД задача не создаёт и существующие таблицы не меняет. DDL-откат и `down -v` запрещены (финансовая история retained).

## Границы

Реальный магазин/сеть не вызывались; VM-сборка образов выполняется тимлидом по этому документу. Не выполнено этим деплоем: payment reconciliation/launch runbook (AUTH-25), AUTH-CERT. Каталог покупок и кошельки остаются выключенными до явного провижининга (AUTH-21/22 CLI).
