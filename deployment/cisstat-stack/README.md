# deployment/cisstat-stack/README.md

# CISStat TS Analysis — прод-стек на собственном сервере (AUTH-06-OPS-PHASE1)

Дата: 2026-11-04. База: main@3659d80. Домен: `datasetup.ru` (слот `178.176.32.210`).
Заменяет контур: фронтенд Vercel (`ts-standalone.vercel.app`) + API render.com.

Обновление **V2** (2026-11-05, база main@e1a379f): перенос серверного
hotfix web-runtime (корневые/workspace-манифесты) в репо; `scripts/auth05`
в образе api (docker cp больше не нужен); §3 — фактическая схема
периметра L7; §6а — bootstrap-миграции свежей БД.

Обновление **V2.1** (2026-11-05): инцидент первого входа — production-гвард
firstPartyProxy отклоняла внутренний http-хоп web→api (503 proxy_unavailable,
логи api пусты); явный allowlist `CISSTAT_PROXY_HTTP_UPSTREAMS=api` в compose
(Fix 5); §7 — фактическая процедура verify_postgres (образ не несёт tests/,
прогон одноразовым контейнером); §8 — диагностика входа.

Обновление **V2.2** (2026-11-06): инцидент №2 — enrollment MFA падал с 503
без traceback (`@boundary` глотает исключения): `CISSTAT_AUTH_MFA_KEYS` в
`.env` был не-JSON, compose-проверка `${VAR:?}` контролирует только
непустоту. §4 — точный рецепт генерации keyring + валидация ДО `up`;
§8 — диагностика молчаливых 503 и урок `env -u` (shell перекрывает `.env`).
Корневой `.gitignore` — шаблон `.env*` (ре-включение `!.env.example`):
копии секретов вида `.env.bak-*` больше не остаются untracked в дереве.

## 1. Топология

```
интернет ──> 80/443 (периметр слота .210)
              └─> caddy (docker, единственная точка входа, auto-TLS LE)
                    ├─ datasetup.ru        -> web:3000  (Next.js standalone shell)
                    ├─ www.datasetup.ru    -> 308 https://datasetup.ru
                    └─ api.datasetup.ru    -> api:8000  (FastAPI: health/диагностика)
внутренняя сеть compose (cisstat-internal):
  web --(API_URL=http://api:8000, first-party proxy AUTH-06)--> api --> postgres:16
  postgres: портов наружу НЕТ; volume pgdata; healthcheck pg_isready
```

Браузер видит только `https://datasetup.ru`; вызовы `/api/v1/*` проксируются
server-side из web в api — куки first-party (архитектура AUTH-06 не меняется).

## 2. Предусловия (на момент поставки выполнены)

- VM `cisstat-api`, Docker 29.9.2 + Compose v5.7.0; периметр слота пропускает 80/443.
- DNS: `A @ → 178.176.32.210`, `A www → 178.176.32.210`, `A api → 178.176.32.210`.
- git clone репозитория (ветка main, база ≥ 3659d80) + файлы этой поставки
  распакованы поверх (структура каталогов совпадает).

## 3. Периметр и TLS: фактическая схема (L7) и порты 80/443 на VM

Подтверждено внешними пробами 2026-11-05 — де-факто реализован **вариант B
(L7-форвардинг)**:

```
интернет ──> машина периметра 192.168.8.80: nginx/1.14.2 терминирует TLS
             (серт Let's Encrypt от certbot: CN=datasetup.ru, SAN www/api,
              действителен до 2027-02-01; продление — certbot на периметре)
         ──> L7-форвардинг на VM 192.168.8.82: caddy
             (свои серты Let's Encrypt по HTTP-01 — в логах caddy
              «certificate obtained successfully» по всем трём именам)
         ──> web:3000 / api:8000 (внутренняя сеть compose)
```

Следствия схемы B:

- TLS-ALPN-01 до caddy НЕ доходит (443 снаружи терминирует край) —
  шум TLS-ALPN в логах caddy НОРМАЛЕН, challenge проходит по HTTP-01.
  Не «чинить».
- `Alt-Svc: h3=":443"` в ответах объявляет HTTP/3, но UDP 443 наружу
  периметром может не пробрасываться — браузеры откатываются на TCP, не
  блокер (вопрос №3 сисадмину).
- Точная схема форвардинга периметра (80 → ?, 443 → ? на VM) —
  **УТОЧНЯЕТСЯ У СИСАДМИНА** (вопрос №1 списка); пункт обновится по ответу.

Порты на самой VM: caddy публикует 80/443 (см. `docker ps`). Если на VM
слушает системный nginx (наследие Keycloak-эпохи, на текущей VM уже не
наблюдалось) — остановить его:

```console
ss -ltnp | grep -E ':80 |:443 '        # слушает docker (caddy) — норма
systemctl stop nginx
systemctl disable nginx                # только если nginx присутствует
```

## 4. Окружение (.env)

```console
cd deployment/cisstat-stack
cp .env.example .env
# заполнить: CISSTAT_PG_PASSWORD, CISSTAT_AUTH_CSRF_KEY,
#            CISSTAT_AUTH_MFA_ACTIVE_KEY; keyring — однострочником ниже
# генерация: openssl rand -base64 32   (CSRF и каждый ключ keyring'а)
chmod 600 .env
```

Кольцо ключей MFA — ТОЛЬКО корректный JSON с двойными кавычками
(V2.2; инцидент 2026-11-05: не-JSON значение ломает enrollment с 503 без
traceback — см. §8). Однострочник генерации (kid=k1):

```console
printf 'CISSTAT_AUTH_MFA_KEYS={"k1":"%s"}\nCISSTAT_AUTH_MFA_ACTIVE_KEY=k1\n' \
  "$(openssl rand -base64 32)" >> .env
```

Валидация ДО `up` обязательна: compose-проверка `${VAR:?}` контролирует
только непустоту, не валидность JSON. Печатается только имя ключа, не секрет:

```console
python3 - <<'EOF'
import json, base64
env = dict(l.split("=", 1) for l in open(".env").read().splitlines()
           if "=" in l and not l.startswith("#"))
ks = json.loads(env["CISSTAT_AUTH_MFA_KEYS"])
assert 1 <= len(ks) <= 8
assert all(len(base64.b64decode(v, validate=True)) == 32 for v in ks.values())
assert env["CISSTAT_AUTH_MFA_ACTIVE_KEY"] in ks
print("ENV OK:", list(ks))
EOF
```

Все значения — в менеджер паролей (без `.env` сессии/MFA-факторы
невосстановимы); резервные копии `.env*` держать ВНЕ дерева репозитория
(`.gitignore` V2.2 закрывает `git add -A`, но не заменяет гигиену).
`CISSTAT_STORAGE_MODE=required` зашита в compose (fail-closed, не переопределять).

Правка `.env` при живом стеке: shell-окружение ПЕРЕКРЫВАЕТ `.env` при
интерполяции compose — если переменные экспортированы в сессии, первый
`up -d` молча оставит старое значение в контейнере. Recreate через `env -u`
(инцидент 2026-11-05: контейнер продолжал жить со старым env):

```console
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d
```

## 5. Сборка и запуск

```console
docker compose build          # api ~5-10 мин; web: npm ci + next build ~3-6 мин
docker compose up -d
docker compose ps             # все 4 - healthy/running
docker compose logs caddy | grep -i certificate   # серты всех трёх имён получены
```

## 6. Проверки

DNS уже смотрит на этот хост — снаружи сразу:

```console
curl -sS https://api.datasetup.ru/health          # {"status":"ok",...}
curl -sS https://api.datasetup.ru/health/ops      # durable-бэкенд Postgres
curl -sSI https://www.datasetup.ru/               # 308 -> https://datasetup.ru/
curl -sS https://datasetup.ru/ | head -c 200      # HTML оболочки
```

До распространения DNS (если понадобится) — локально с хоста:

```console
curl --resolve api.datasetup.ru:443:127.0.0.1 https://api.datasetup.ru/health
curl --resolve datasetup.ru:443:127.0.0.1 https://datasetup.ru/
```

Критерий `/health/ops`: backend Postgres, `CISSTAT_STORAGE_MODE=required`,
режим fail-closed (без БД сервис не стартует вовсе).

V2.3 (2026-11-06): session_backend — тоже Postgres. Таблица
`analysis_sessions` (миграция 0022, слой 1 сессий анализа
`cisstat_session_id`) поднимается САМОСТОЯТЕЛЬНО первым коннектом
(`ensure_schema` в required-режиме — ДО startup-пробы): отдельный
bootstrap-шаг для неё не нужен ни на свежей, ни на существующей БД.
Контроль:

```console
docker compose exec api curl -fsS http://127.0.0.1:8000/health/ops | \
  python3 -c 'import json,sys; s=json.load(sys.stdin)["session_backend"]; print(s["configured"], s["effective"], s["degraded"])'
# ожидание: postgres postgres False
```

## 6а. Bootstrap-миграции для свежей БД (первый подъём)

Нужны ТОЛЬКО если volume `pgdata` пуст (первый подъём, потеря volume,
переезд на новую VM): api стартует fail-closed
(`CISSTAT_STORAGE_MODE=required`) и на пустой БД уходит в restart-цикл
UndefinedTable. Для обычных обновлений (`git pull && build && up`) секция
не нужна.

```console
# Шаг 1. Core-схема научного слоя (миграции 0001–0018) — одноразовый
# контейнер: research-run стор применяет свою схему при подключении.
docker compose run --rm api python -c 'from apps.api.research_runs import PostgresResearchRunStore; s=PostgresResearchRunStore.from_env(); c=s._connect(); c.close(); print("CORE SCHEMA OK")'
# ждём строку: CORE SCHEMA OK; затем повторный `up -d` -- api станет healthy

# Шаг 2. Auth-миграции 0019–0021 -- scripts/auth05 теперь В ОБРАЗЕ
# (AUTH-06-OPS-PHASE1-V2), docker cp не нужен:
docker compose exec api python scripts/auth05/migrate.py --check
docker compose exec api python scripts/auth05/migrate.py --apply
docker compose exec api python scripts/auth05/migrate.py --check     # ok:true
docker compose exec api python scripts/auth05/verify_postgres.py
```

Историческая заметка: при первом подъёме 2026-11-04/05 core-схема и
auth-миграции накатывались обходными путями (inline-блок apply_migration,
docker cp scripts — копия потеряна при пересоздании контейнера). С
поставкой V2 оба класса шагов выполняются штатно из образа.

## 7. Операторская процедура AUTH-05 (миграции + первый админ)

Эквивалент SSH-туннеля из `docs/auth06/first-admin.md`: DSN уже в окружении
контейнера api,postgres не публикуется наружу — команды через `exec`.

```console
docker compose exec api python scripts/auth05/migrate.py --check
docker compose exec api python scripts/auth05/migrate.py --apply     # если 0021 не применена
docker compose exec api python scripts/auth05/migrate.py --check     # ok:true
# Гейт verify_postgres: образ api НЕ содержит tests/ (гигиена прод-образа),
# поэтому прогон -- одноразовый контейнер с tests/ из репо и одноразовой БД
# (тесты сами накатывают auth-схему на пустую БД; V2.1, проверено 2026-11-05:
# Ran 24 tests ... OK):
docker compose exec postgres createdb -U cisstat cisstat_auth_verify_tmp
set -a && . ./.env && set +a && docker compose run --rm \
  -v /opt/cisstat/CISStat-TS-Analysis/tests:/app/tests:ro \
  -e CISSTAT_AUTH_TEST_DSN="postgresql://cisstat:${CISSTAT_PG_PASSWORD}@postgres:5432/cisstat_auth_verify_tmp" \
  api sh -c 'pip install --quiet httpx && python scripts/auth05/verify_postgres.py'
docker compose exec postgres dropdb -U cisstat cisstat_auth_verify_tmp
docker compose exec api python scripts/auth05/bootstrap.py prepare   # TTL 15 минут
docker compose exec api python scripts/auth05/bootstrap.py create --login dimm.day
# пароль скрытым вводом, >= 15 символов; сохранить в менеджер паролей
# Нюансы bootstrap (инцидент 2026-11-05): провал create слот НЕ расходует --
# повторите create с тем же секретом в пределах TTL. Повторный prepare после
# истечения/потребления даст отказ (слот singleton постоянный) -- при потере
# секрета требуется отдельная операторская процедура (docs/auth05/design.md).
```

## 8. Первый вход (Phase 4)

`https://datasetup.ru/login?return_to=%2Fupload` → вход `dimm.day` → настройка
TOTP → сохранение recovery codes → тестовая загрузка датасета → run в Postgres.
Подробно: `docs/auth06/first-admin.md` (без изменений).

Диагностика входа (V2.1): надпись «Не удалось завершить вход» при ПУСТЫХ логах
api = запрос отклонён прокси web до api. Проверка снаружи:
`curl -H "X-CSRF-Request: 1" https://datasetup.ru/api/v1/auth/csrf` — ответ 503
`proxy_unavailable` означает, что окружение web без
`CISSTAT_PROXY_HTTP_UPSTREAMS=api` (см. Fix 5; compose поставки V2.1 уже
содержит переменную — пересобрать web). Ошибка «Failed to find Server Action»
в логах web при рабочей странице = вкладка браузера от старой сборки —
жёсткое обновление Ctrl+F5.

Диагностика enrollment (V2.2): «Сервис входа временно недоступен» на шаге
MFA + `POST /v1/auth/mfa/enroll → 503` в логах api БЕЗ traceback —
`@boundary` (apps/api/authentication/sessions.py) конвертирует ЛЮБОЕ
не-Auth исключение в 503 `auth_authority_unavailable`, поэтому traceback в
логах отсутствует. Типовая причина — `CISSTAT_AUTH_MFA_KEYS` не валидный
JSON (см. §4). Проверка в живом контейнере (печатает только имена ключей,
длины и факт наличия активного kid — секреты не выводятся):

```console
docker compose exec api python -c "
import os, json, base64
ks = json.loads(os.environ.get('CISSTAT_AUTH_MFA_KEYS', ''))
print('kids:', list(ks))
print('lens:', {k: len(base64.b64decode(v, validate=True)) for k, v in ks.items()})
print('active_in_keys:', os.environ.get('CISSTAT_AUTH_MFA_ACTIVE_KEY') in ks)
"
```

`JSONDecodeError` в выводе = `.env` битый, лечится §4 (однострочник +
валидация + recreate через `env -u`). Вращение keyring безопасно, пока
не существует зашифрованных TOTP-факторов: `seal()` в `begin_enrollment`
падает ДО первой записи (транзакция откатывается).

Норма схемы (V2.2): `/health/ops` НЕ маршрутизируется периметром наружу
(снаружи проксируется только `/api/v1/*`) — внешний curl даёт 404,
это не дефект. Снимать статус изнутри:

```console
docker compose exec api python -c "
import urllib.request
print(urllib.request.urlopen('http://localhost:8000/health/ops').read().decode())
"
```

## 9. Бэкапы (Phase 5)

Ежедневный pg_dump (cron от root), ретенция 14 дней:

```console
mkdir -p /opt/backups
crontab -e
# 17 3 * * * cd /opt/cisstat/CISStat-TS-Analysis/deployment/cisstat-stack && docker compose exec -T postgres pg_dump -U cisstat cisstat | gzip > /opt/backups/cisstat_$(date +\%F).sql.gz && find /opt/backups -name 'cisstat_*.sql.gz' -mtime +14 -delete
```

Тестовое восстановление после первого бэкапа: `gunzip -t` + развёртывание на
временной БД. Плюс `caddy_data` volume (сертификаты) и `.env` — в офлайн-копии.

## 10. Периметр (ufw — по готовности сисадмина)

Публикованные docker-порты НЕ фильтруются ufw (iptables DOCKER chain):
наружу торчит ровно то, что в `ports:` compose — только 80/443 у caddy.
Postgres/api/web портов не имеют. ufw тем не менее настроить:

```console
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80,443/tcp
ufw enable
```

## 11. Обновления и откат

```console
git pull && docker compose build && docker compose up -d   # простой ~секунды
docker compose logs -f --tail=100 api                       # после обновления
```

Откат: предыдущий образ остаётся локально — `docker compose up -d --no-deps --force-recreate <svc>`
после `git checkout <prev-tag>`; фронтенд-резерв — `ts-standalone.vercel.app`
до удаления Vercel-проекта.

## 12. Вывод из эксплуатации старого контура (после приёмки Phase 4)

1. render.com: остановить сервис (Dashboard → Suspend).
2. Vercel: удалить проект (после 2+ дней стабильной работы datasetup.ru);
   env там больше ничего не влияет.
3. Ключевые CI-контракты (auth04/05/06, check_routes) не зависят от рантайма —
   продолжают работать как прежде.
