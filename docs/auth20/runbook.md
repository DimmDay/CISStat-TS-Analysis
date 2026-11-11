# AUTH-20 — runbook: аудит, backup/restore reconciliation, quarantine, rollback

Контур: `security_audit` (auth_audit_outbox + ops sweeper), `auth_ops_ledger` (0032 capture-триггеры), ops-CLI `scripts/auth20/reconcile.py`, kill-switch `CISSTAT_AUTH_LOCKDOWN`. Все команды выполняются из checkout на VM, DSN берётся из окружения api (`CISSTAT_AUTH_DATABASE_URL`/`DATABASE_URL`, libpq). Никаких обратных DDL-миграций: откат = env-операции.

## 1. Миграция 0032 (явная, вне request-path)

```bash
cd deployment/cisstat-stack
git pull --ff-only
docker compose build api            # web не менялся; при желании — build web
docker compose run --rm --no-deps -T api python scripts/auth20/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth20/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 \
    docker compose up -d --no-deps api
docker compose exec -T api python scripts/auth20/migrate.py --check
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops | python3 -c "import json,sys; print(json.load(sys.stdin)['auth_ops'])"
```

0032 additive: `auth_ops_ledger` + append-only guard + capture-триггеры на `auth_password_credentials`, `auth_sessions`, `auth_api_keys`, `auth_worker_services`, `auth_demo_grants`, `auth_demo_admissions`, `auth_reservations`, `auth_billing_orders`. Цепочка `migrate.py` гарантирует применение 0029/0030 перед 0031/0032. Checksums 0019–0031 не меняются. Повторный `--apply` идемпотентен.

## 2. Периодический контур обязательного аудита

`ops_sweeper` (in-process, только при `CISSTAT_STORAGE_MODE=required`) каждые `CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL` секунд (по умолчанию 30, `0` — выключить) доставляет bounded-порцию (≤100) записей `auth_audit_outbox` в durable `security_audit_records` и выполняет prune `auth_ops_ledger` по `CISSTAT_AUTH_OPS_LEDGER_RETENTION_DAYS` (по умолчанию 180, минимум 7). Состояние — `/health/ops → auth_ops` (pending, счётчики циклов/сбоев, lockdown, флаги внешних входов, версия схемы). Ручная доставка (например, после инцидента):

```bash
docker compose exec -T api python scripts/auth20/reconcile.py --drain-audit --limit 100
```

Отказ доставки не теряет запись: intent уже в БД (одна транзакция с мутацией), delivery идемпотентен (`audit_id` + `ON CONFLICT DO NOTHING`). БЕЗ env `DATABASE_URL` у CLI — команда завершится кодом 1 с `auth_authority_unavailable`.

## 3. Backup: ОБЯЗАТЕЛЬНЫЙ export marks ДО снапшота

Ledger живёт в той же БД: restore «уносит» и его. Поэтому out-of-band копия ревокаций хранится в файле на volume ВНЕ pgdata (`ops_marks:/var/lib/cisstat-ops-marks`, примонтирован в api):

```bash
docker compose exec -T api python scripts/auth20/reconcile.py --export /var/lib/cisstat-ops-marks/marks-$(date +%F-%H%M).json
docker compose exec -T api ls -l /var/lib/cisstat-ops-marks
```

Порядок: export marks → штатный dump/pgdata-снапшот → (опционально) копия marks-файла в менеджер паролей/внешнее хранилище. Экспорт пишет обязательный audit (`auth_ops_changed`, kind=marks_export) и создаёт файл атомарно (tmp+rename, права 600). Формат: `cisstat-auth20-marks/1`, `complete:true` — если `complete:false`, повторите export с `--export` (bounded 100k; при большом ledger используйте retention prune или повторный запуск).

## 4. Restore + reconciliation

При restore pgdata «назад во времени» БД консистентна на момент снапшота, но теряет ревокации/погашения/сеттлы после него. Процедура:

1. Остановить api (workers остановятся вместе с контейнером): `docker compose stop api`.
2. Восстановить pgdata штатной процедурой (pg_restore/basebackup). НЕ выполнять `docker compose down -v` (это стирает volumes).
3. `docker compose start postgres` и убедиться, что `migrate.py --check` зелёный (версия схемы осталась снапшотной — это ожидаемо; 0032 в снапшоте уже есть, т.к. устанавливалась до backup).
4. Запустить reconcile с ПОСЛЕДНИМ marks-файлом (созданным ДО backup):

```bash
docker compose run --rm --no-deps -T api python scripts/auth20/reconcile.py \
  --reconcile --marks /var/lib/cisstat-ops-marks/marks-<последний>.json \
  --reason "restore-<дата>"
```

5. Re-apply идемпотентен (повторный запуск — no-op). Отчёт: `applied/skipped/unrepairable/budget_recheck_required`. Гарантии:
   - парольные credential/API-ключи/worker-ключи: revoked восстанавливается, subject-epoch поднимается, сессии закрываются;
   - demo grants: revoked восстанавливается (+ закрытие scope и demo-сессий); потерянный grant (создан после снапшота) реинсертируется tombstone'ом из row_image (status=revoked, `issued_grants+1`) при живых FK-родителях;
   - admissions: consumed восстанавливается; если grant потерян — честный finding `consumed_grant_absent` (auth16-гвард не позволяет in-place закрытие) — оператор приостанавливает кампанию и перевыпускает коды;
   - reservations: settled/released закрываются БЕЗ повторных postings/budget-дельт — over-charge невозможен; недо-charge виден в `budget_recheck_required` (оператор решает — спишет вручную через штатный API/CLI AUTH-12);
   - billing orders: applied/canceled закрывает saga (worker не переприменит места).
6. Только после зелёного reconcile: `docker compose start api` и проверка `/health/ops`.

## 5. Quarantine — «при сомнении кампании и сессии закрываются до reconciliation»

```bash
docker compose run --rm --no-deps -T api python scripts/auth20/reconcile.py --quarantine --reason "подозрение на restore/компрометацию"
```

Поднимает `session_epoch` всем субъектам, ревоцирует все активные сессии, ставит активные кампании в `paused`. API/worker-ключи НЕ затрагиваются (решение оператора штатными командами AUTH-10/AUTH-13). Вход снова открыт сразу после команды; участники кампаний получают новые admission по решению оператора. Каждая порция — обязательный audit.

## 6. Safe rollback — kill-switch без DDL

```bash
# включить: закрыть НОВЫЕ входы (password/demo/OIDC/email) с 503 auth_lockdown
echo "CISSTAT_AUTH_LOCKDOWN=1" >> .env && docker compose up -d --no-deps api
# проверить
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops | python3 -c "import json,sys; print(json.load(sys.stdin)['auth_ops']['lockdown'])"
# снять
sed -i '/CISSTAT_AUTH_LOCKDOWN/d' .env && docker compose up -d --no-deps api
```

Свойства: неизвестное значение включается (fail-closed); существующие сессии/ключи продолжают работать (проверка только на входе); /internal и научные пути остаются под AUTH-11 guards (открытый /internal не возвращается); ревокации не отменяются. Остановка вычислений — через quarantine (сессии) или штатные ревокации worker-ключей (AUTH-13). Ключи/URL в env не меняются, образы не пересобираются.

## 7. Отключение контура AUTH-20

`CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL=0` останавливает доставку (pending копятся в outbox и видны в /health/ops); retention prune продолжит работать только с явно заданным `--prune`. Триггеры 0032 capture'ят события независимо от env — ledger остаётся полным. Удаление миграции/DDL-откат запрещены.

## 8. Диагностика

- `/health/ops → auth_ops.state == "degraded"` + `detail` — проверить DSN/схему (`migrate.py --check`), логи api.
- `auth_ops.audit_outbox_pending` растёт — sweeper выключен (`INTERVAL=0`), required-режим не активен или delivery падает (счётчик `failures` в `audit_sweeper`); использовать `--drain-audit` вручную.
- Лимит reconciliation — 5000 событий за запуск (bounds); при большем ledger — retention prune или повторный запуск (идемпотентно).
- Все команды CLI работают по DSN мимо HTTP: lockdown/quarantine не блокируют operator-доступ.
