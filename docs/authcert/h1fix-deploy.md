# AUTH-CERT-H1FIX — деплой на VM (F-CERT-H1 прогрев durable-слоёв)

База: a38c4a4. Изменения ТОЛЬКО api-кода: новых миграций нет, новых env/volumes
нет, роуты не затронуты (281==281, added/missing=[]), UI не менялся —
**пересборка только web НЕ нужна, только api**.

## Порядок (цепочка: ZIP → локальная машина → push → VM pull)

```bash
# на локальной машине тимлида (после распаковки ZIP поверх checkout):
git status --short
git add --pathspec-from-file=scripts/warmup/files.txt
git diff --cached --stat
python scripts/local_gates.py --skip-install        # warmup в default-прогоне
# после коммита:
python scripts/local_gates.py --auth00-target head --skip-install
git push
```

```bash
# на VM:
cd /opt/cisstat   # каталог compose-стека (deployment/cisstat-stack)
git pull --ff-only
docker compose build api
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d --no-deps api
```

## Верификация

```bash
# verify-URL только api-хост (урок AUTH-23-DEPLOYFIX-01: апекс ведёт на web:3000)
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['storage_warmup'], indent=2))"
```

Ожидается: `"state": "primed"`, `layers` — 12 записей, ни одной `error`
(`support_grants`/`monitoring` — честный `skipped`, если их backend остаётся
Memory по фабричному контракту). Стартовый лог api содержит
`Startup: durable-слои прогреты (F-CERT-H1)`.

Наблюдение: первый запрос после рестарта не должен зависать на
audit/telemetry/trace-пути (класс дедлока F-CERT-H1 закрыт прогревом).

## Откат

Предыдущий образ api: код прогрева исчезает вместе с образом, ленивое
поведение прежнее. БД/схема/маршруты/env не менялись; DDL-откат и down -v
не требуются.

## Границы

- advisory/dev-режим сохраняет ленивый контракт (прогрев — честный no-op,
  статус `skipped`); класс дедлока в advisory+DATABASE_URL остаётся
  достижим в dev — остаточный риск задокументирован (docs/authcert/h1fix.md D6).
- Fresh-DB в required по-прежнему fail-closed на недокатанный ops-каталог
  ДО прогрева (доктрина probes AUDIT-6C не менялась): порядок
  «миграции до старта api» обязателен, как и прежде.
- AUTH-CERT приёмка остаётся на поставке v3; production certified не заявляется.
