# deployment/cisstat-stack/README.md

# CISStat TS Analysis — прод-стек на собственном сервере (AUTH-06-OPS-PHASE1)

Дата: 2026-11-04. База: main@3659d80. Домен: `datasetup.ru` (слот `178.176.32.210`).
Заменяет контур: фронтенд Vercel (`ts-standalone.vercel.app`) + API render.com.

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

## 3. Остановка локального nginx слота (обязательно ДО первого `up`)

Порты 80/443 хоста обязан занять caddy. Сейчас их слушает локальный nginx
(наследие Keycloak). ВНИМАНИЕ: убедитесь, что nginx не обслуживает ничего
актуального (`ls /etc/nginx/sites-enabled/`, `nginx -T | grep server_name`).

```console
ss -ltnp | grep -E ':80 |:443 '        # убедиться: слушает nginx
systemctl stop nginx
systemctl disable nginx
systemctl list-timers | grep certbot   # если есть certbot-таймер --
systemctl disable --now certbot.timer  # отключить, продлением займётся caddy
ss -ltnp | grep -E ':80 |:443 '        # порты свободны
```

Если nginx обслуживал ещё какие-то сайты — их перенос/выключение согласовать
с сисадмином до этого шага.

## 4. Окружение (.env)

```console
cd deployment/cisstat-stack
cp .env.example .env
# заполнить: CISSTAT_PG_PASSWORD, CISSTAT_AUTH_CSRF_KEY,
#            CISSTAT_AUTH_MFA_KEYS (JSON без пробелов), CISSTAT_AUTH_MFA_ACTIVE_KEY
# генерация: openssl rand -base64 32   (CSRF и каждый ключ keyring'а)
chmod 600 .env
```

Все значения — в менеджер паролей (без `.env` сессии/MFA-факторы невосстановимы).
`CISSTAT_STORAGE_MODE=required` зашита в compose (fail-closed, не переопределять).

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

## 7. Операторская процедура AUTH-05 (миграции + первый админ)

Эквивалент SSH-туннеля из `docs/auth06/first-admin.md`: DSN уже в окружении
контейнера api,postgres не публикуется наружу — команды через `exec`.

```console
docker compose exec api python scripts/auth05/migrate.py --check
docker compose exec api python scripts/auth05/migrate.py --apply     # если 0021 не применена
docker compose exec api python scripts/auth05/migrate.py --check     # ok:true
docker compose exec api python scripts/auth05/verify_postgres.py
docker compose exec api python scripts/auth05/bootstrap.py prepare   # TTL 15 минут
docker compose exec api python scripts/auth05/bootstrap.py create --login dimm.day
# пароль скрытым вводом, >= 15 символов; сохранить в менеджер паролей
```

## 8. Первый вход (Phase 4)

`https://datasetup.ru/login?return_to=%2Fupload` → вход `dimm.day` → настройка
TOTP → сохранение recovery codes → тестовая загрузка датасета → run в Postgres.
Подробно: `docs/auth06/first-admin.md` (без изменений).

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
