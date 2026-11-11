# AUTH-23 — деплой на VM (Refund/dispute/chargeback workflow)

База: 004dba5. Поставка: `download/cisstat-auth23-004dba5.zip` — точное множество `scripts/auth23/files.txt` (CRC/байты/SHA256 проверены упаковщиком). Правит только контур AUTH-23: аддитивная миграция 0035, +2 OWNER-маршрута, refund/dispute-сервис, CLI, шаг саги в общем billing-worker.

## Порядок

```bash
cd /opt/cisstat/CISStat-TS-Analysis   # путь чекаута на VM
git pull --ff-only                    # после пуша тимлида
docker compose build api              # web НЕ пересобирать: UI не менялся (только авто-генерируемый TS-контракт в байт-паритете)
docker compose run --rm api python scripts/auth23/migrate.py --apply
docker compose run --rm api python scripts/auth23/migrate.py --check
docker compose up -d --no-deps api

# Контроль готовности (внутри контейнера: та же схема, что видит api):
docker compose exec -T api python scripts/auth23/migrate.py --check
# Живость: /health наружу отдаёт ТОЛЬКО api-хост (Caddyfile:
# api.datasetup.ru -> api:8000). На апексе datasetup.ru тот же путь
# отвечает 404 -- апекс ведёт на web:3000 (Next.js shell, без /health).
curl -fsS https://api.datasetup.ru/health | head -c 400; echo
```

Порядок шагов обязателен: сага refund-заявок читает таблицы 0035 через to_regclass-гвард — без применённой 0035 шаг честно «нет работы», но HTTP-маршруты уже отвечают 503/409, пока схема не готова (check_schema в каждом контуре). Образ billing-worker (scripts/auth18/worker.py) НЕ пересобирается отдельным образом: он получает шаг refund-саги из того же api-образа.

## Конфигурация

- Окно self-service возврата: `CISSTAT_TOPUP_REFUND_DAYS` (default 14; границы 0…90; фиксируется в refund-записи на момент запроса). Env опционален; compose/env-файлы не менялись.
- Провайдер: те же `CISSTAT_YOOKASSA_*` переменные AUTH-22 (только test-магазин; sandbox=True в адаптере неизменен). Refund POST идёт с Idempotence-Key=refund_id и подтверждается независимым GET.
- Отключение контура без отката кода: возврат — через отключение каталога AUTH-22 (manage_topups disable-package — новые credited-заказы невозможны); disputes — операторская дисциплина (trusted CLI).

## Эксплуатация (trusted CLI, каждый вызов с --reason и обязательным аудитом)

```bash
docker compose run --rm api python scripts/auth23/manage_refunds.py refunds --account-id <UUID>
docker compose run --rm api python scripts/auth23/manage_refunds.py refund-reconcile --refund-id <UUID> --reason "..."
docker compose run --rm api python scripts/auth23/manage_refunds.py dispute-open --order-id <UUID> --reason "chargeback received"
docker compose run --rm api python scripts/auth23/manage_refunds.py dispute-resolve --dispute-id <UUID> --outcome lost|won --reason "..."
docker compose run --rm api python scripts/auth23/manage_refunds.py disputes --account-id <UUID>
```

Семантика: dispute-open лочит кошелёк (новые CU-операции → 403 wallet_locked) и держит остаток available лота в refund_pending (спор с расходом — exposure в auth_disputes.spent_units, отрицательный available невозможен); resolve lost гасит удержанные CU (кошелёк остаётся заблокированным); resolve won возвращает удержанное в available и разблокирует кошелёк ровно один раз. Восстановление после lost — явный AUTH-21 `scripts/auth21/manage_wallet.py` (unlock) с reason.

## Откат

Откат — предыдущий образ api (0035 аддитивна: существующие таблицы/маршруты AUTH-22 не меняются; refund-маршруты исчезают вместе с образом, holds сохраняются в лотах и снимаются trusted-командами AUTH-21/23 после отката). DDL-откат и `down -v` запрещены: финансовая история retained. Повторное применение 0035 идемпотентно (--apply после --check возвращает applied=false).

## Границы

Реальный магазин/сеть не вызывались (MockTransport; PG16/18 и Windows — remote CI auth23.yml). Не выполнено этим деплоем: refund-UI (AUTH-24), wallet/ledger READ-эндпоинты (AUTH-24), payment reconciliation/launch runbook (AUTH-25), AUTH-CERT. Кнопка покупки и каталог остаются выключенными до явного провижининга (AUTH-22).
