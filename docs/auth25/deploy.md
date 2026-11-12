# AUTH-25 — Инструкция деплоя на VM

База: `main@f6dbec9` (AUTH-24). Миграций НЕТ: reconciliation живёт на схеме 0033/0034/0035, применённой AUTH-21/22/23. env-переменных НЕТ: `CISSTAT_TOPUP_REFUND_DAYS` уже действует с AUTH-23 (default 14), `CISSTAT_YOOKASSA_ENABLED` остаётся в текущем состоянии (sandbox/not_configured). Меняется только код api → **пересобрать только образ api; web не менялся**.

## Шаги

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only

docker compose build api
docker compose up -d --no-deps api

# health на api-хосте (не на апексе):
curl -fsS https://api.datasetup.ru/health | head -c 400; echo
```

## После деплоя: прогон reconciliation и первый launch-check

```bash
# отчёт консистентности (read-only):
docker compose exec -T api python scripts/auth25/reconcile.py --report

# pre-launch gate (факт готовности; ничего не включает):
docker compose exec -T api python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
```

`--allow-empty-catalog` здесь — фиксация осознанно выключенного checkout (каталог пуст до провижининга AUTH-21/22); без флага команда вернёт blocked по пустому каталогу, это тоже корректный результат.

## Регистрация watermark-файла (первичная)

Выбрать каталог ВНЕ pgdata (например, `/var/lib/cisstat-ops/`), убедиться, что он не попадает в backup pgdata, и выполнить первый экспорт:

```bash
docker compose exec -T api sh -c 'mkdir -p /var/lib/cisstat-ops && python scripts/auth25/reconcile.py --export-watermark /var/lib/cisstat-ops/financial-watermark.json'
```

Далее — по регламенту `docs/auth25/runbook.md` (перед каждым backup и после каждого restore).

## Откат

Откат — предыдущий образ api (вывернуть нечего: новых таблиц/колонок/маршрутов нет; watermark-файл остаётся валидным). `down -v` и DDL-откат запрещены (финансовая история retained).
