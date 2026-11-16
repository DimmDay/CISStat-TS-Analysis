# AUTH-KABINET-DEMO CERT — поставка и VM

Overlay к53ebba5525814f6622774e86da319b274ef27946. ZIP → распаковать в корень локального checkout → собственный commit/push → pull VM → Compose. Сессия не выполняет commit/push и не подключается к VM. Список paths scripts/kabinet_demo_cert/files.txt; акт docs/kabinet_demo_cert/report.md, протоколы рядом со скриптами.

## Локально

```powershell
git add --pathspec-from-file=scripts/kabinet_demo_cert/files.txt
python scripts/local_gates.py --skip-install --jest-workers 1
# Если есть disposable PostgreSQL и CISSTAT_AUTH_TEST_DSN:
python scripts/kabinet_demo_cert/verify_postgres.py
# После собственного commit, до push:
python scripts/local_gates.py --only auth00 --auth00-target head --skip-install
```

Зависимости для новых oracles — scripts/kabinet_demo_cert/requirements.txt, прежние AUTH/API зависимости сохраняются. --skip-install предполагает уже установленные зависимости. Native без DSN/skips не PASS. Browser smoke — дополнительная проверка compiled Next и настоящего proxy/HTTPS с controlled authority stub; она не подключается к production и не заменяет SQL-тесты.

## Подготовка public campaign

Существующей админ-процедурой создать/проверить отдельную **публичную demo campaign**: конечное starts_at/ends_at, budget/max_grants/participant limits/retention под подтверждённую мощность, allowed_origins включает https://datasetup.ru. Для one-click публичной кампании require_admission=false. Организаторские кампании с code остаются отдельным вторичным способом. Для отдельно размещённой embedded нужны её реальные exact HTTPS origins одновременно в настройках API и campaign. Числа/реальные credentials в этой поставке не выдумываются.

В существующий deployment/cisstat-stack/.env добавить обе переменные из .env.example. Значения — **только общий логин и пароль этой public demo campaign**, никогда не personal/admin/API/OIDC/MFA credentials. Эти значения намеренно попадут в browser JS. Не помещать их в URL или Git. Пустые значения оставляют публичную кнопку отключённой; форма организатора/resume/leave продолжает работать.

```dotenv
NEXT_PUBLIC_DEMO_LOGIN=
NEXT_PUBLIC_DEMO_PASSWORD=
```

Ввести опубликованную campaign-пару своим редактором/секретным хранилищем оператора, не копировать synthetic cert fixtures как рабочую пару. Если public campaign ещё не подготовлена, оставить пустыми и честно сохранить disabled.

## VM

После push и зелёного CI, из checkout VM:

```bash
set -euo pipefail
git pull --ff-only
cd deployment/cisstat-stack
# shell overrides не должны подменить значения из .env:
env -u NEXT_PUBLIC_DEMO_LOGIN -u NEXT_PUBLIC_DEMO_PASSWORD \
    docker compose build web
env -u NEXT_PUBLIC_DEMO_LOGIN -u NEXT_PUBLIC_DEMO_PASSWORD \
    docker compose up -d --no-deps web
docker compose ps web
curl -fsS https://datasetup.ru/demo >/dev/null
curl -fsS https://datasetup.ru/dashboard >/dev/null
```

Нужен **только web rebuild/recreate**. Backend image/API/migrations/PG volumes не меняются; новых миграций нет. Не выполнять down -v. Проверка curl — доступность страницы, а не доказательство входа; завершить браузерным smoke оператора: /navigator→4-й бейдж→/demo→запуск→/upload→полоса лимитов→resume на том же устройстве→leave; /dashboard anonymous→login, personal authed→account, outage→сообщение без автоперехода. После expiry доступ закрыт независимо от retention.

Rotation: pause/rotate существующей admin-командой, обновить публичную пару в .env, пересобрать и пересоздать web, проверить вход и состояние кампании. Старая пара после серверной rotation не должна входить; старый bundle до пересборки честно получит отказ. Для rollover — новая конечная кампания, не reset spent/reserved/истории прежней. Обновление runtime environment или простой restart web не заменяет build.

При rollback вернуть проверенный web image/версию и соответствующую public campaign-конфигурацию. На время рассогласования остановить выдачу кампании. Серверные отзывы/expiry/budget не откатывать. Для embedded, если она размещается отдельно, значения задаются при её Next build; отдельной embedded Docker/VM инфраструктуры эта задача не создаёт.
