# AUTH-CERT-H1FIX — прогрев durable-слоёв до начала обслуживания (F-CERT-H1)

Дата: 13.11.2026. Находка: F-CERT-H1 из AUTH-CERT (12.11.2026, «Честные находки
приёмки»): «lazy-миграция audit-sink/session-store внутри первого запроса
самодедлочится на trace_events (воспроизведено pg_stat_activity: AccessExclusive/
ShareLock цикл). Harness устраняет прогревом синглтонов до обслуживания
(порядок «миграция до старта api», как в проде); кандидат в runbook-чеклист
деплоя и отдельную задачу». Эта задача — та отдельная поставка: устранение
класса дефекта в продовом коде, а не в тестовом harness.

## 1. Корневая причина (два компонента)

**D1 (механизм).** Каждый Postgres-durable слой лениво прогоняет ПОЛНЫЙ
ops-каталог `research_runs.run_migrations` на первом коннекте процесса
(флаг `_schema_ready`/`_migrated` на экземпляре): PostgresAuditSink,
PostgresTelemetrySink, PostgresSessionStore, PostgresResearchRunStore,
PostgresArtifactRegistry, PostgresSnapshotRegistry, PostgresDocumentRegistry,
PostgresDocumentLifecycleRegistry, PostgresSupportGrantRegistry,
PostgresMonitoringRegistry, PostgresOrgProfileRegistry и module-global
`admin_logs._pg_connect`. Каталог содержит `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` (trace_events и др.): даже как no-op оператор берёт
ACCESS EXCLUSIVE на таблицу. На уже промигрированной БД lazy-прогон не
безопасен — он всё равно лочит таблицы каталога.

**D2 (дыра старта).** В required-режиме `_lifespan` прогревает до
обслуживания только: session (фабрика вызывает `ensure_schema()` явно),
documents/lifecycle (побочный эффект probe → `_connect` → lazy-DDL,
недокументированный). Остальные слои ленивы: первый запрос, который
открывает транзакцию на conn A (например, trace-событие в bound-
транзакции AUTH-16 или INSERT в trace_events) и синхронно обращается ко
второму слою на conn B (mandatory audit → `PostgresAuditSink.append`) —
получает цикл: conn B ждёт ACCESS EXCLUSIVE у незакрытой транзакции conn
A, поток запроса ждёт conn B. Дедлок клиентский — PostgreSQL его не
детектирует (вторая сторона ожидания — приложение). Именно это
воспроизвёл harness и CI-прогон AUTH-CERT (ac12 — тот же класс между
параллельными контекстами).

## 2. Решения

**D3. Прогрев в `_lifespan`, а не в фактиках.** Новый модуль
`apps/api/storage_warmup.py` с единственной публичной точкой
`warmup_durable_layers()`; вызов в `_lifespan` ПОСЛЕ
`verify_required_storage_backends()` (фабрики/probes fail-closed раньше —
недоступная БД роняет старт там) и ДО `worker_bootstrap.startup_check()`,
`telemetry_emit("api.startup")` и старта всех in-process worker'ов
(delivery, document render, demo sweeper, ops sweeper) — воркеры тоже
пишут audit/telemetry. Порядок «миграция до начала обслуживания» — паритет
продового деплоя (explicit CLI-миграции до `up -d api`) и harness-прайма.

**D4. Единый контракт `ensure_schema(conn=None)`.** Каждому Postgres-классу,
у которого его нет, добавлен публичный идемпотентный `ensure_schema` —
байт-паритет `PostgresSessionStore.ensure_schema` (сессия — эталон):
double-checked lock, собственное соединение при `conn=None`,
`run_migrations(conn)`, флаг готовности, отказ НЕ кэшируется. Ленивый
путь `_connect` сохранён без изменений (advisory/dev, fresh-DB-старт,
тесты) — прогрев лишь гарантирует, что в required после старта ни один
запрос не выполнит DDL.

**D5. Реестр слоёв** в storage_warmup — декларативный список
(имя → фабрика/аксессор → prime-вызов): audit, telemetry, session, runs,
artifacts, snapshots, documents, lifecycle, support_grants, admin_logs,
monitoring, org_profiles. Прогрев идемпотентен: каждый слой выполняет
DDL-скан один раз на процесс; последующие прогоны каталога — no-op.
Новый слой присоединяется одной строкой реестра.

**D6. Семантика отказов.**
- required: отказ prime любого слоя, КРОМЕ telemetry → RuntimeError
  (safe_error, без DSN/секрета) — fail-closed доктрина AUDIT-6C
  («неверная ... миграция ... роняет старт»); обязательный аудит не имеет
  права стартовать с неготовой схемой.
- telemetry: отказ прогрева проглатывается (контракт AC11 — телеметрия
  никогда не роняет старт), состояние `error` видно в /health/ops.
- advisory/auto: warmup — честный no-op ({"state": "skipped"}), ленивый
  контракт dev/тестов сохранён (пин «конструирование Postgres-бэкенда не
  открывает соединение»). Класс дедлока в advisory+DATABASE_URL остаётся
  теоретически достижимым — честно документировано как остаточный риск
  dev-режима (production — required).

**D7. Наблюдаемость.** `/health/ops` — аддитивный facts-only ключ
`storage_warmup` (peek-семантика, try/except, паритет worker_credential/
auth_ops): {state, mode, layers: {имя: primed|skipped|error}, ts}.
Секретов/DSN нет; диагностика не инициализирует фабрики и не роняет
health. Оператор на VM проверяет прогрев одной командой без shell-доступа.

**D8. Гейты и роуты.** Роуты НЕ затронуты (ни одного нового/изменённого
HTTP method/path; /health/ops — прежний GET, тело аддитивно). Новые
гейты local_gates: default `warmup` (unittest discover tests/unit,
pattern test_warmup*.py) + opt-in `warmup-postgres` (native-раннер
scripts/warmup/verify_postgres.py, без DSN → exit 2) — пара
`--with-warmup-postgres` + `excluded.add` в одном изменении (урок
AUTH-22-HOTFIX-01), человекочитаемые списки имён строятся программно.

## 3. TDD

- RED: suite-level ImportError отсутствующего `apps.api.storage_warmup`
  (паттерн AUTH-19/20/21) + native-воспроизведение класса дедлока на
  «сыром» lazy-пути (conn A: незакрытая транзакция на trace_events →
  `PostgresAuditSink.append` c lock_timeout → LockNotAvailable) —
  доказательство механизма, не гейт регрессии.
- GREEN unit: требуемый-режим-only; реестр 12 слоёв primed; fail-closed
  на отказе слоя; telemetry-исключение; отсутствие DSN/секрета в статусе;
  порядок вызовов в `_lifespan` (фабрики → прогрев → worker bootstrap →
  телеметрия → воркеры) пином с mock-коллабораторами; ensure_schema
  идемпотентен (второй вызов без DDL — mock run_migrations).
- Native (pgserver, disposable DB, 0 skips): механизм-репро; ensure_schema
  на реальном PG; сквозной: fresh DB + цепочка 0019→0035 → required →
  настоящий lifespan TestClient → /health/ops storage_warmup.state=primed
  → coexistence-оракул (незакрытая транзакция conn A на trace_events,
  audit-append успешен — DDL в запросном пути больше нет); повторный
  прогон lifespan идемпотентен.

## 4. Границы

- Роуты/маршруты/методы — без изменений; карта роутов перегенерируется
  официальным `inventory.py --write` (отпечатки изменённых файлов).
- Миграции/DDL-каталог не меняются; `run_migrations` сохранён
  байт-в-байт (семантика каталога — сертифицированный контракт).
- advisory-режим — ленивый контракт сохранён; остаточный риск задокументирован.
- Docker/VM: пересборка ТОЛЬКО api (UI не менялся); миграций/env нет.
- Полный scientific pytest / browser E2E не заявляются.
