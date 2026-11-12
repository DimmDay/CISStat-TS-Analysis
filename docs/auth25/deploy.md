# AUTH-25 — Инструкция деплоя на VM

База: `main@f6dbec9` (AUTH-24) + **AUTH-25-HOTFIX-01/02**: без патча `apps/api/Dockerfile` (COPY `scripts/auth25/reconcile.py`) CLI `reconcile.py` в образ api не попадает — см. `docs/auth25/hotfix01.md`, `docs/auth25/hotfix02.md`. Миграций НЕТ: reconciliation живёт на схеме 0033/0034/0035, применённой AUTH-21/22/23. env-переменных НЕТ: `CISSTAT_TOPUP_REFUND_DAYS` уже действует с AUTH-23 (default 14), `CISSTAT_YOOKASSA_ENABLED` остаётся в текущем состоянии (sandbox/not_configured). Меняется только код api → **пересобрать только образ api; web не менялся**.

## Шаги

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only

# HOTFIX-01/02, однократно и идемпотентно: +1 строка COPY scripts/auth25 в apps/api/Dockerfile
python3 scripts/auth25/patch_dockerfile.py
# итоговая строка в Dockerfile должна быть ровно:
#   COPY scripts/auth25/reconcile.py ./scripts/auth25/
# патчер v2 (HOTFIX-02) проверяет источники по build-context и чинит неверную строку;
# повторный запуск при верной строке ничего не меняет: "OK: … valid"

docker compose build api
docker compose up -d --no-deps api

# health на api-хосте (не на апексе):
curl -fsS https://api.datasetup.ru/health | head -c 400; echo

# проверка состава образа (урок HOTFIX-01):
docker compose exec -T api ls scripts/auth25
```

## После деплоя: прогон reconciliation и первый launch-check

```bash
# отчёт консистентности (read-only):
docker compose exec -T api python scripts/auth25/reconcile.py --report

# pre-launch gate (факт готовности; ничего не включает):
docker compose exec -T api python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
```

`--allow-empty-catalog` здесь — фиксация осознанно выключенного checkout (каталог пуст до провижининга AUTH-21/22); без флага команда вернёт blocked по пустому каталогу, это тоже корректный результат.

## Быстрый путь без пересборки (временная мера)

Если пересборка откладывается, а отчёт нужен сейчас — скопировать CLI в работающий контейнер. **ЭФЕМЕРНО**: пропадёт при recreate контейнера; не отменяет патч + rebuild из `docs/auth25/hotfix01.md`:

```bash
cd /opt/cisstat/CISStat-TS-Analysis/deployment/cisstat-stack
docker compose exec -T api mkdir -p /app/scripts/auth25
docker compose cp ../../scripts/auth25/. api:/app/scripts/auth25/
docker compose exec -T api python scripts/auth25/reconcile.py --report
```

Если после копирования прогон падает с `ModuleNotFoundError: apps` — layout образа отличается от ожидаемого; использовать только штатный вариант B.

## Регистрация watermark-файла (первичная)

Экспорт выполняется в контейнере (там DSN и код сервиса), но файл СРАЗУ копируется на хост: путь внутри контейнера не переживает recreate, а watermark обязан жить вне pgdata и вне контейнера:

```bash
cd /opt/cisstat/CISStat-TS-Analysis/deployment/cisstat-stack
mkdir -p /opt/cisstat/cisstat-ops
docker compose exec -T api sh -c 'mkdir -p /var/lib/cisstat-ops && python scripts/auth25/reconcile.py --export-watermark /var/lib/cisstat-ops/financial-watermark.json'
docker compose cp api:/var/lib/cisstat-ops/financial-watermark.json /opt/cisstat/cisstat-ops/
```

Сравнение после restore (файл подкладывается в контейнер только на время прогона):

```bash
docker compose cp /opt/cisstat/cisstat-ops/financial-watermark.json api:/tmp/financial-watermark.json
docker compose exec -T api python scripts/auth25/reconcile.py --reconcile-watermark --watermark /tmp/financial-watermark.json --reason "restore-YYYY-MM-DD"
```

Далее — по регламенту `docs/auth25/runbook.md` (перед каждым backup и после каждого restore).

## Откат

Откат — предыдущий образ api (вывернуть нечего: новых таблиц/колонок/маршрутов нет; watermark-файл остаётся валидным). Откат самого HOTFIX-01 — восстановить `apps/api/Dockerfile` из `.bak` и пересобрать. `down -v` и DDL-откат запрещены (финансовая история retained).
