# AUTH-11 — применение поставки

База ZIP и текущая VM: bf5763051285f1f1e74d14e2ce3680a47493c0ca. Распаковать архив в корень локального checkout. Только файлы этой задачи перечислены в scripts/auth11/files.txt. Старые manifests AUTH-09/10 уже в базе.

## Локальная машина

```powershell
git status --short
git add --pathspec-from-file=scripts/auth11/files.txt
git diff --cached --stat
python scripts/local_gates.py
```

Если зависимости уже установлены, допускается `--skip-install`. AUTH-00 проверяет INDEX, поэтому git add обязателен после распаковки и после любого дальнейшего редактирования. Скрипт сам не stage/commit/push. При красном AUTH-00 читать `logs/local_gates/auth00.log` в UTF-8. После своего локального commit перед push проверить `python scripts/local_gates.py --auth00-target head --skip-install`.

Native PostgreSQL gate отдельный: `--with-auth11-postgres` и disposable CISSTAT_AUTH_TEST_DSN; production БД для тестов не использовать. Без DSN/skips native не PASS. Все результаты и ограничения текущей среды в scripts/auth11/protocols/README.md.

## VM после собственного push и зелёных гейтов

Выполнить из корня клона на VM:

```bash
set -e
git pull --ff-only
cd deployment/cisstat-stack
unset CISSTAT_AUTH_MFA_KEYS CISSTAT_AUTH_MFA_ACTIVE_KEY
docker compose build api web
docker compose up -d api web
docker compose exec -T api python scripts/auth10/migrate.py --check
docker compose exec -T api python -c 'import json, urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/health/ops")); print(json.dumps(d["identity"], ensure_ascii=False)); assert d["identity"]["scientific_guard"] == "enforce"'
```

Миграции/new mandatory env не добавлены. `--check` проверяет уже установленную authority0024 без DDL. Compose берёт MFA settings из действующего .env; unset убирает только переопределения из shell. Оба образа api/web нужны. Внешний /health/ops закрыт периметром, статус снимается из контейнера. Поле scientific_guard подтверждает режим, не заменяет readiness authority и реальный login smoke.

После старта: named личный вход → upload → baseline naive/drift → ModelCard/forecast/CSV; Demo advanced/tuning получает отказ, research-cookie-only scientific запрос401. Старые ENV keys не заменяют durable programmatic keys. Anonymous Demo отдельно AUTH-15. При откате использовать согласованные прежние код/образы api+web; production guard через off/shadow/legacy_dev не выключать.

В этой сессии VM, commit и push не выполнялись.
