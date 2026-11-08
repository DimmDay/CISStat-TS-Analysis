# AUTH-14 — поставка и измерение VM

База ZIP: `a16b31bd0c3d49586de24d3556a39e43b9cc3321`. Распаковать в корень checkout этой версии. Только файлы текущей задачи перечислены в `scripts/auth14/files.txt`. Commit/push выполняет тимлид; из сессии GitHub/VM не изменялись. Новых SQL migrations нет; обязательны уже установленные AUTH-12/13 authority schema и service key с `modeling`.

## Локальная приёмка

```bash
python -m pip install -r apps/api/requirements.txt -r scripts/auth14/requirements.txt
python -m unittest discover -s tests/unit -p 'test_auth14*.py' -v
# CISSTAT_AUTH_TEST_DSN — disposable PostgreSQL, никогда production.
python scripts/auth14/verify_postgres.py
python scripts/auth06/check_routes.py
# Просмотреть manifest и явно подготовить index после распаковки:
git add --pathspec-from-file=scripts/auth14/files.txt
python scripts/local_gates.py --skip-install --with-auth14-postgres
npm run build:all
```

Без DSN native gate возвращает2; skips/нулевой набор не PASS. CI содержит Ubuntu/Windows contracts и PostgreSQL16/18 native; локальные результаты и ограничения — в `verification.md`. После локального commit перед push: `python scripts/local_gates.py --auth00-target head --skip-install`. Runner не stage/commit/push автоматически.

## Переключение VM на новый код

Дождаться завершения старых jobs в окне обслуживания; остановить новое admission на время переключения. Не смешивать старые и новые worker binaries над одной очередью. Не выдавать refund по одному истёкшему lease. Сохранить действующие MFA keys, worker key, database, `worker_proofs` и остальные volumes.

```bash
# Из существующего checkout на VM после вашего push и зелёного CI:
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose run --rm --no-deps -T api python scripts/auth13/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth13/manage_workers.py inspect --limit 100
```

Нужны **api и web**: web proxy теперь пропускает `Idempotency-Key`. AUTH-14 не требует повторного выпуска service key. При неожиданном schema mismatch сначала разобрать причину; старый AUTH-13 runbook описывает первоначальный bootstrap, повторять его на уже настроенной VM не нужно.

Новые named volumes: `cu_profiles` → `/var/lib/cisstat-cu-profiles`, `compute_cache` → `/var/lib/cisstat-compute-cache`. Не удалять их при recreate. Cache содержит научные результаты; доступ только доверенному пользователю API. Для внешнего supervisor нужны те же protected cache/proof stores. Отсутствующий или повреждённый committed cache даёт503, не запускает fit/charge заново.

Пустые **обе** `CISSTAT_CU_PROFILE` и `CISSTAT_CU_PROFILE_SHA256` сохраняют AUTH-13 unpriced mode с ограниченным runtime. Поставка не пополняет CU budgets, не запускает wallet/платежи и не активирует измеренный тариф автоматически. Локальный `scripts/auth14/reference/candidate.json` **не переносить в active на VM**.

## Benchmark внутри нового API image на VM

Выделить окно без пользовательской вычислительной нагрузки. Замеры проводить с теми же CPU/memory limits, hardware и image, с которыми будет работать API. `docker compose run` наследует service environment/volumes; проверять фактические limits в `report.json`. Изменение software/ядра/ограничений требует повторной calibration.

Ниже воспроизводимый небольшой стартовый домен: PELT + ETS/ETS damped,80–180 строк, folds≤3,trials≤2,horizon≤4,period≤12, concurrency1. Он не покрывает произвольные production данные. Для включения иных моделей/размеров запустить представительную матрицу с нужными `--models`, `--rows`, `--folds`, `--trials`, `--horizon`, `--concurrency`, сохранив минимум три размера и достаточный memory reserve. Один profile охватывает все перечисленные модели; непокрытая операция получает402, без скрытого free fallback. Конструкторы benchmark есть для унивариатных, vector, volatility и panel engines; успешная calibration требует реальных успешных trials для каждой модели. Вечный/упавший workload не даёт активируемый candidate.

```bash
docker compose run --rm --no-deps -T api python scripts/auth14/benchmark.py \
  --output /var/lib/cisstat-cu-profiles/vm-auth14 \
  --models ets,ets_damped --rows 80,120,180 --folds 2,3 --trials 1,2 \
  --horizon 4 --concurrency 1 --timeout 120 --memory-mb 1024 --reserve-memory-mb 1024
# Повторная независимая проверка raw evidence + атомарная установка, mode600:
docker compose run --rm --no-deps -T api python scripts/auth14/profile.py \
  --report /var/lib/cisstat-cu-profiles/vm-auth14/report.json \
  --candidate /var/lib/cisstat-cu-profiles/vm-auth14/candidate.json \
  --install /var/lib/cisstat-cu-profiles/active.json
```

Только после `ok:true` сохранить **выведенный действительный** `profile_sha256` в закрытом `.env` как `CISSTAT_CU_PROFILE_SHA256`, а `CISSTAT_CU_PROFILE=/var/lib/cisstat-cu-profiles/active.json`. Не использовать hash локального reference. Убедиться в конечных разрешённых AUTH-12 CU/concurrency budgets и prerequisites планируемых Accounts; денежный wallet AUTH-21 отдельно. Изменение бюджета — существующий audited operator workflow, не автоматическая часть benchmark.

```bash
chmod 600 .env
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 docker compose up -d --no-deps api
docker compose exec -T api python scripts/auth13/migrate.py --check
```

Проверять actual workload в измеренном домене, reservation/settle и replay на тестовом Account до открытия admission. Profile mismatch/corruption →503, непокрытые параметры→402, global running+uncertain capacity→429. Старые quotes сохраняют исходную версию/ставку; смена profile не переоценивает уже admitted работу. Для очередного profile: drain, замер, проверка/install, явный checksum, recreate. Режим с пустым profile — явное операторское отключение calibrated pricing, не fallback ошибки.

## Повторы, ограничения и сбой

PELT GET автоматически использует current-authority cache для тех же входов/контекста/credential/kernel. POST `/v1/session/modeling/tune` и `/v1/models/tune` принимают `Idempotency-Key`1–128 символов; повтор после commit получает сохранённый ответ без нового fit/charge. Ключ+иные входы→409. Без ключа POST означает новое вычисление. Cache read вновь проверяет текущие Account/Identity/credential/object/scopes; possession of key/job ID прав не даёт. Конкурирующий незавершённый повтор получает409 и не создаёт второй fit.

Считаются **начатые** folds/PELT fits, включая numerical failure/timeout: progress сохраняется до fit; signed positive-stop receipt нужен для settle. Unknown stop/missing progress сохраняет hold. По прежним правилам `inspect/reconcile` AUTH-13 не заменяют доказательство остановки; force-release нет. Cache objects вне ledger content-addressed; ledger содержит только ссылку/hash. Cleanup retention/backup политик — эксплуатационный AUTH-20; не удалять committed objects вручную.

На Linux независимый supervisor каждые≤50мс проверяет aggregate process-group RSS и wall deadline и останавливает группу, даже если parent занят authority I/O. Это sampled physical bound с задержкой scheduling, не гарантия точного byte-by-byte/p99; hard child CPU/data limits дополняют контроль. Время ответа на заблокированный SQL может превышать физический deadline, но child продолжать fit не может. На Windows wall kill/join portable; Linux aggregate RSS/descendant guarantees не подменяются Windows проверкой. Production ceiling/capacity следует активировать только после замера/приёмки на целевой Linux VM. Docker images в этой сессии не собирались (engine отсутствует).
