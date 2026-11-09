# AUTH-16 — установка поверх 2f48120

Task-only overlay: база `2f4812032240b35f1524d0bb31c58fcaf4bc3c85`. ZIP → локальная машина → ваш commit/push → pull VM. Сессия не меняет GitHub и VM. Пересобрать **api и web**. Миграция0028 additive; старые SQL/checksums не изменены. Новых обязательных secrets нет. Campaign activation выполняет администратор отдельно.

## Локальная машина

Распаковать в корень checkout на указанной базе, просмотреть manifest/изменения:

```bash
git status --short
git add --pathspec-from-file=scripts/auth16/files.txt
python scripts/local_gates.py --skip-install
# Только отдельная disposable БД, НЕ production:
python scripts/local_gates.py --only auth16-postgres --skip-install
npm run build:all
# После вашего commit, до push:
python scripts/local_gates.py --auth00-target head --skip-install
```

Не обходить красный AUTH-00 генерацией карты: читать `logs/local_gates/auth00.log`, сверять состав ZIP и INDEX. Зависимости: API requirements + scripts/auth16/requirements.txt и npm ci, если ещё не установлены.

## VM: backup и перенос scientific files

Выбрать окно обслуживания, закрыть admission (внешний доступ) и дождаться jobs; сохранить .env, MFA/worker secrets, PostgreSQL и существующие volumes. Остановленные/неопределённые jobs не refund вручную. Не запускать одновременно старую и новую API над одной БД. Новая Compose-конфигурация добавляет `science_data` в `/var/lib/cisstat-data`: ранее uploads/checkpoints/artifacts находились в writable layer API. **Перенести их до пересоздания старого контейнера.** Скрипт ниже запускается из существующего checkout VM; `set -e` прекращает установку при ошибке, при этом сервисы могут остаться остановленными.

```bash
set -euo pipefail
cd deployment/cisstat-stack
backup_dir="$PWD/backups/auth16-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir/science-data"
chmod 700 "$backup_dir"
# Останавливаем публичный вход; worker jobs должны быть завершены заранее.
docker compose stop caddy web
old_science_dir=$(docker compose exec -T api python -c 'from apps.api.research_runs import DatasetFileStore; p=DatasetFileStore.default_root(); p.mkdir(parents=True, exist_ok=True); print(p)')
docker compose stop api
# cp работает с остановленным контейнером. Не продолжать при ошибке копирования.
docker compose cp "api:${old_science_dir}/." "$backup_dir/science-data/"
docker compose exec -T postgres pg_dump -U cisstat -d cisstat -Fc > "$backup_dir/postgres.dump"
test -s "$backup_dir/postgres.dump"
cp .env "$backup_dir/env.backup"
chmod 600 "$backup_dir/env.backup" "$backup_dir/postgres.dump"
# Секреты и backups в Git не добавлять.
git pull --ff-only
docker compose build api web
# Новый science_data должен быть пуст при ПЕРВОЙ установке. На повторной
# установке не импортировать старый backup поверх актуального volume.
tar -C "$backup_dir/science-data" -cf - . | docker compose run --rm --no-deps -T api sh -c 'test -z "$(ls -A /var/lib/cisstat-data)" && tar -C /var/lib/cisstat-data -xf -'
docker compose run --rm --no-deps -T api python scripts/auth16/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth16/migrate.py --check
```

`deployment/cisstat-stack/backups/` исключён из Git и Docker build context правилами этой поставки. Проверить backup отдельно; не выполнять `down -v`. Если uploads ещё не создавались, команда создаёт пустой каталог по фактически настроенному DatasetFileStore root. Ошибку `cp` не заменять молчаливым продолжением.

## CU profile и запуск

Изменились fingerprints backtesting/models из-за supervisor. **Если CISSTAT_CU_PROFILE настроен**, прежний profile будет отклонён до новой калибровки. Выполнить измерения нового image под прежние реальные CPU/RAM limits и полный используемый workload domain по `docs/auth14/runbook.md`. Не отключать profile ради обхода проверки. Пример для ограниченного домена ETS (расширить матрицу до фактически используемых моделей/размеров):

```bash
docker compose run --rm --no-deps -T api python scripts/auth14/benchmark.py \
  --output /var/lib/cisstat-cu-profiles/vm-auth16 \
  --models ets,ets_damped --rows 80,120,180 --folds 2,3 --trials 1,2 \
  --horizon 4 --concurrency 1 --timeout 120 --memory-mb 1024 --reserve-memory-mb 1024
docker compose run --rm --no-deps -T api python scripts/auth14/profile.py \
  --report /var/lib/cisstat-cu-profiles/vm-auth16/report.json \
  --candidate /var/lib/cisstat-cu-profiles/vm-auth16/candidate.json \
  --install /var/lib/cisstat-cu-profiles/active.json
```

После `ok:true` сохранить фактический выведенный `profile_sha256` в закрытом `.env` (`CISSTAT_CU_PROFILE_SHA256`), путь — `/var/lib/cisstat-cu-profiles/active.json`. Если profile изначально не настроен, не включать его фиктивным hash; требования AUTH-14 к metered операциям остаются.

```bash
chmod 600 .env
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth16/migrate.py --check
docker compose ps
# Открыть внешний вход после проверки API/web:
docker compose up -d --no-deps caddy
```

Проверить `/health/ops`, personal ADMIN+MFA, обе оболочки, /demo: отдельные коды двум браузерам, replay одного кода в новом браузере409, resume в своём браузере с прежним сроком, отказ при исчерпании request/analysis и после expiry/pause/revoke. Defaults для прежних policy: 600 запросов/участника, 60000/кампанию, upload≤4MiB, retention24h, admission optional. Администратор явно включает require_admission и проверяет бюджет перед форумом. Политика не повышает Demo capabilities.

## Lifecycle и физическая очистка

Background sweep включён по умолчанию каждые5s в required profile; opt-out `CISSTAT_DEMO_SWEEPER_ENABLED=0` (только SQL housekeeping; guards от env не зависят). Expiry проверяется в каждом запросе/worker, а не ожидает sweep. Retention `[1,720]` часов после immutable grant.expires_at. SQL очистка удаляет workspace/science payload/cache, сохраняет identity/grant/usage/ledger/audit и redemption; holds/published/approved/pins и ownership migration receipts сохраняют весь workspace. Pending/running/uncertain workers задерживают очистку. Очередь файлов может остаться pending после SQL cleanup.

```bash
# Дополнительный bounded SQL batch; можно онлайн:
docker compose exec -T api python scripts/auth16/cleanup.py --sweep --limit 25
```

**Физический GC требует остановки ВСЕХ publishers**, включая API, document/delivery/model workers, другие инстансы/CLI, использующие эти volumes/БД. `--quiesced` — подтверждение оператором уже выполненной остановки, команда сама процессы не останавливает. Shared referenced bytes не удаляются. Audit intent фиксируется до unlink; сбой допускает безопасный повтор.

```bash
docker compose stop caddy web api
# После проверки отсутствия других publishers:
# Снять только crash HTTP-call hold, не worker uncertainty/financial hold:
docker compose run --rm --no-deps -T api python scripts/auth16/cleanup.py --abandon-calls --quiesced
docker compose run --rm --no-deps -T api python scripts/auth16/cleanup.py --sweep --limit 100
docker compose run --rm --no-deps -T api python scripts/auth16/cleanup.py --collect-files --quiesced --limit 100
# Повторять bounded batches при pending obligations; ссылка/hold не ошибка.
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 docker compose up -d --no-deps api web caddy
```

Не запускать native tests на production DSN. Откат: сначала остановить новые demo admission и все процессы нового кода, сохранить БД/volumes;0028 и immutable audit/usage не удалять. Старый AUTH-15 код не обеспечивает AUTH-16 quotas/codes, поэтому при rollback форумные кампании должны оставаться закрытыми. `science_data` сохранять и при откате. Автоматического refund/удаления hold нет. Production capacity, Windows/PG18 и полный AUTH-CERT не заявляются локальной приёмкой.
