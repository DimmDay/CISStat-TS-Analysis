# AUTH-13 — установка и эксплуатация

База пакета: `a4f744466eb727759e95e8276d7eb3643dfe592c`. ZIP накладывается **в корень этой версии репозитория**. В нём только новые/изменённые файлы AUTH-13; список — `scripts/auth13/files.txt`. Commit/push и установка на VM выполняются тимлидом. Старые SQL 0019–0025 не изменены.

## Локальная проверка

```bash
python -m pip install -r apps/api/requirements.txt -r scripts/auth13/requirements.txt
python -m unittest discover -s tests/unit -p 'test_auth13*.py' -v
# CISSTAT_AUTH_TEST_DSN — исключительно disposable PostgreSQL, не production.
python scripts/auth13/verify_postgres.py
python scripts/auth06/check_routes.py
# После явного staging файлов текущей задачи:
python scripts/local_gates.py --skip-install --with-auth13-postgres
npm run build:all
```

`verify_postgres.py` без DSN возвращает 2; skipped/нулевой набор не считаются PASS. Native CI проверяет PostgreSQL 16/18; portable contracts — Ubuntu/Windows. Это конфигурация CI, не утверждение локального исполнения на обеих ОС/версиях.

## VM: новый образ API, миграция, служебный ключ

Перед переключением остановить admission длительных jobs и дождаться старых running render/model workers либо остановить их под надзором. Не запускать старый и новый бинарники над одной очередью: старый бинарник не знает новых fences. Неизвестный исход старой попытки не считать доказанной остановкой.

После применения ZIP, собственных commit/push тимлида и зелёного CI:

```bash
# На VM — из уже настроенного checkout:
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api
# Миграция использует новый image; работающий старый контейнер не нужен.
docker compose run --rm --no-deps api python scripts/auth13/migrate.py --apply
docker compose run --rm --no-deps api python scripts/auth13/migrate.py --check
# Только интерактивный терминал. Ключ показывается один раз.
docker compose run --rm --no-deps api python scripts/auth13/manage_workers.py issue-service --kinds modeling render delivery --reason 'AUTH-13 VM bootstrap'
```

Сохранить выданный `cwk_…` в закрытом `.env` как `CISSTAT_WORKER_KEY` через редактор (не добавлять секрет в Git/логи/аргументы команд). Сохранить действующие MFA-переменные. `CISSTAT_WORKER_ACCOUNT_SLOTS=1` — исходный технический потолок, 1–32; существующая операторская concurrency policy не перезаписывается. Это не измеренная финансовая CU-квота.

```bash
chmod 600 .env
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY docker compose up -d --no-deps api
docker compose exec api python scripts/auth13/migrate.py --check
docker compose exec api python scripts/auth13/manage_workers.py inspect --limit 100
docker compose exec api python scripts/auth13/manage_workers.py reconcile --limit 100
```

Пересборка web для AUTH-13 не требуется. В среде разработки проверены обе production-сборки веб-оболочек; Docker engine в контейнере сессии отсутствует, сам image здесь не собирался. Dockerfile содержит import guard для нового worker/CLI, а deploy-конфигурация проверяется тестами.

Atomic publication требует один PostgreSQL database/schema для Auth, research/session и document registries. `CISSTAT_AUTH_DATABASE_URL` при его наличии должен соответствовать тому же DSN; разнесённые databases не объединяются скрытым fallback и дают503.

Новый named volume `worker_proofs` хранит подписанные stop receipts вне эфемерной файловой системы API. Не удалять его при рестарте и не передавать его содержимое браузеру. Отдельный supervisor должен использовать тот же ключ и доступ к соответствующим proof receipts; необозримые удалённые receipts не дают автоматического release. Директория должна быть доступна только доверенному пользователю API.

## Сверка после сбоя

`inspect` выводит ограниченную проекцию jobs/services без raw credentials, delegation и key hashes. `reconcile` — ограниченный повторяемый проход:

- queued с отозванной делегацией/истёкшим deadline: закрытие с положительным фактом «не стартовал»;
- running с потерянным lease/deadline/правами: новый fence и `uncertain`; slot/CU остаются held;
- подписанный receipt с подтверждённым join: terminal failure без публикации результата и ровно один settle;
- timeout/потеря ответа удалённого PNG renderer: `remote_unknown`, автоматического refund/повторного старта нет.

TTL/отсутствие PID сами по себе не дают права release. Повторный complete старого fence не публикует результат. Receipt с чужой/повреждённой подписью не принимается. После утраты/отзыва старого service secret старые receipts могут потребовать отдельного операторского расследования; новый ключ не подменяет подпись старого. Команды force-release по job ID нет.

```bash
# Аварийный отзыв конкретного service ID из inspect:
docker compose exec api python scripts/auth13/manage_workers.py revoke-service --service-id SERVICE_UUID --reason 'incident reference'
```

Отзыв проверяется перед start, на pulse и в publication transaction. Отозванный ключ запрещает и публикацию/автоматическую сверку этим ключом; holds сохраняются. До восстановления службы poll/read продолжают проверять актуальные права пользователя.

Исторические jobs без AUTH-13 ticket не auto-claim и не получают синтезированную личность владельца; их следует разобрать при drain/rollout и при необходимости создать заново после авторизованного admission. Автоматическая миграция таких заданий не выполняется.

## Границы

В runtime AUTH-13 применяется server quote `unpriced-auth13/1`, micro-CU=0; конечные slots и counters уже проходят atomic AUTH-12. Synthetic integer-CU tests проверяют settle/hold/гонки; они не задают прайс. Финансовый CU launch/benchmark — AUTH-14, Demo lifecycle — AUTH-15/16, operational rollout/backup disaster recovery — AUTH-20, wallet/lots — AUTH-21. AUTH-CERT не объявляется пройденной.

На Linux применяются process group termination, parent-death signal и CPU/data/RSS bounds; Windows получает supervised terminate/kill/join и wall timeout без Unix-only imports. Нативный Windows runtime в этой сессии не исполнялся. Утрата supervisor без положительного stop receipt оставляет неизвестный исход и hold; безопасный reclaim не выводится из одного истёкшего lease.
