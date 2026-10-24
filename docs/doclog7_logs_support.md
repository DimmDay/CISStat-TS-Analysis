# DOCLOG-7 — Журналы и поддержка (2026-10-24)

Контрактный документ поставки. Спека: `spec_documentation_logging.md`
§14.2 (UI оператора), §15/§15.1 (права, tenancy), §19 (строка
DOCLOG-7), §20 (AC10/AC11/AC17/AC19).

## Постановка и граница

§19 дословно: «Admin logs/audit/delivery UI, scope grants, diagnostic
bundle». Зависимость: 3+4 (выполнены). **Критерий завершения: «нет
данных/секретов вне grant, все действия учитываются».**

Включено: чтение трёх durable-журналов по whitelist-фильтрам
(telemetry 0009, security audit 0009, delivery/documents 0010+0011),
cursor pagination + временной cutoff + лимиты, честный retention
horizon, support grants (ticket/purpose, tenant/run/time, TTL,
отзыв), диагностический пакет (redacted JSONL + manifest, ZIP),
саможурналирование доступа к журналам, UI-панель «Администрирование →
Журналы» рядом с агрегатами «Прогресса».

НЕ включено (честная граница): retention-очистка telemetry/audit
(§16.1 политика — отдельный контур, horizon только РЕПОРТУЕТСЯ);
retention/hold документов (DOCLOG-6); OTLP/OTel SDK-экспорт
(to_jsonl — адаптер будущей поставки); выдача `artifact.data.read`
через support-grant (пакет «без данных»; data-доступ — отдельный
контур §15); подписи/WORM журналов; живой PostgreSQL-прогон 0013
(паттерн AUDIT-6A — при следующем durable-срезе).

## Карта изменений

**Backend (новые):**
- `apps/api/admin_logs.py` — чтение журналов (memory+postgres
  адаптеры), SupportGrantService/Registry (Memory+Postgres,
  структурный паритет, урок F-D2C1), resolve_effective_log_access,
  build_diagnostic_bundle.
- `apps/api/routers/logs.py` — 7 маршрутов `/v1/logs/*`.
- `apps/api/migrations/0013_doclog7_logs_support.sql` — `support_grants`
  (1 таблица + 3 индекса; tenant_id NOT NULL — глобальных грантов нет).
- `packages/ui/lib/adminLogs.ts`, `packages/ui/components/AdminLogsDashboard.tsx`,
  `apps/embedded/app/admin/logs/page.tsx` — UI (рядом с
  `/admin/progress`, §14.2 дословно).

**Backend (обновлённые):** `research_runs.py` (каталог MIGRATION_FILES
13/78), `security_audit.py` (PostgresAuditSink.list_recent — закрыт
отложенный в DOCLOG-3 гэп), `telemetry.py`
(PostgresTelemetrySink.list_recent — паритет), `document_jobs.py`
(DocumentRegistry.list_delivery_summary — 10-й метод ABC, Memory +
Postgres), `main.py` (include router).

## Ключевые решения

1. **Доступ (§15.1 дословно)**: «Новые admin endpoints сохраняют
   текущую ADMIN-проверку и дополнительно применяют scopes/tenant
   grants». Эффективный доступ = ADMIN-роль (полный каталог) ∪ scopes
   ключа ∪ активные grants субъекта. Запрос с явным фильтром вне
   границы grant — 403 (не пустой список: непрозрачное сужение
   маскировало бы ошибку границы); запрос без фильтра — честное
   сужение с раскрытием `meta.effective_scope`.
2. **Whitelist-фильтры** (§14.2: «Без произвольного SQL/регулярных
   выражений от браузера»): точные совпадения по каталогу полей на
   поток; окно ≤ 31 день; limit ≤ 200 (default 50); cursor — keyset
   `(occurred_at, id) DESC`, base64url-JSON.
3. **Retention horizon (§16.1)**: telemetry 30 дней, audit 365 —
   репортируются в `meta.retention_horizon_days`; период старше
   horizon — честная пометка `retention_note`, не ошибка (очистка —
   отдельный контур).
4. **Саможурналирование (§14.2)**: успешное чтение потока — ровно
   ОДНА `audit_log_accessed` (standard, AC11-инвариант: сбой записи
   не ломает чтение); экспорт пакета — mandatory fail-closed
   (раскрытие) + тройка download triple (§14.1); GET /access —
   не журналируется (мета-доступ без чтения данных, решение
   зафиксировано).
5. **Гранты — mandatory fail-closed (§14.1 «создание/изменение прав и
   support grants»)**: `grant_created`/`grant_revoked` (из каталога
   DOCLOG-3) — record_mandatory ДО записи в реестр; сбой sink → 503,
   грант не создан (a-оракул: реестр пуст). Scopes-whitelist гранта:
   {logs.read, audit.read, logs.export} — выдача data/publish-прав
   через support-grant запрещена («Разрешён пакет „без данных"»).
   TTL ≤ 168h, ticket/purpose/tenant обязательны.
6. **Диагностический пакет (AC10/AC19)**: manifest (schema
   `doclog.diagbundle/1`, bundle_id, окно/фильтры, service versions,
   ops status — safe-подмножество CERT DOCLOG-3, counts, sha256
   членов, retention, effective_scope, ЯВНЫЙ список excluded) +
   `<stream>.jsonl` (redacted-записи как записаны). НИКОГДА: env
   values, DSN, API-key, cookies, строки данных (оракулы: sentinel
   env-значение и ключ отсутствуют в байтах пакета). ZIP
   детерминирован (даты членов (2020,1,1) — урок DOCLOG-5).
7. **Delivery-поток — metadata only**: jobs + document chain
   (kind_code, state, format, attempt, error_code), БЕЗ
   content_bytes/payload (§14.2: «Не показывать raw dataset и секреты
   даже в раскрытии»). Новый метод реестра `list_delivery_summary` —
   структурный паритет Memory/Postgres (урок F-D2C1).
8. **UI**: ключ живёт только в стейте (паттерн AdminProgressDashboard,
   §15.1 «API-key не переносится в URL/storage/UI диагностический
   пакет» — оракул: localStorage/sessionStorage пусты); вкладки;
   фильтры — только ограниченные inputs/selects (нет textarea);
   live tail — тик 5с, на паузе счётчик пропусков без скачивания
   истории; гранты — TTL-селект whitelist; AC17-состояния: 401/403/
   422/503/offline/empty/loading различимы.

## Карта AC (§20)

- **AC10** — sentinel-оракулы: ключ/env/DSN отсутствуют в пакете,
  health и ошибках; actor_subject — псевдоним, не ключ.
- **AC11** — mandatory fail-closed: гранты, экспорт; standard: чтение
  потоков (сбой записи не ломает чтение; счётчик/статус).
- **AC17** — UI: empty/loading/401/403/422/503/offline; keyboard/
  labels/aria; dark theme классы.
- **AC19** — пакет содержит manifest с ЯВНЫМ перечнем исключённых
  категорий; получатель — независимый (ZIP открывается вне сессии).
- **AC06-дух** — знание run_id/tenant_id не право: вне границы
  гранта — 403, сужение раскрыто в meta.

## Проверки поставки (эта сессия)

- RED → GREEN: корпус 38 (RED на родителе c9b87a1: ImportError
  admin_logs; GREEN 38/38); UI-корпус 9/9 (jsdom, lib-моки).
- Регресс doclog-контура: doclog0–7 = 465/465.
- Полный tests/api дельта-0 против чистой базы c9b87a1 (git-worktree):
  FAILED-ID байт-идентичны; +38+9 = ровно корпусы DOCLOG-7.
- Сборка: import apps.api.main OK — 208 маршрутов (7 новых /v1/logs),
  миграции 13/78; typecheck:all ✓; next build ✓ (embedded 12 страниц,
  включая /admin/logs; standalone 19).

## Примечания тимлиду

1. `PostgresAuditSink.list_recent`/`PostgresTelemetrySink.list_recent`
   читают durable-таблицы напрямую (админ-контур); записи уже
   redacted при записи (CERT DOCLOG-3) — второй слой redaction на
   чтении не применяется (байты журнала честны).
2. `audit_log_accessed` для пакетов пишет detail `stream: "bundle"`,
   для чтения потоков — `stream: <имя>`; количество чтений журнала
   само растёт в журнале — рекурсии нет (ровно одна запись на операцию).
3. Глобальных грантов нет: `support_grants.tenant_id NOT NULL`;
   грант на всё — только роль ADMIN (решающая таблица §15).
4. Миграция 0013 аддитивная; применять автоматически при первом
   коннекте (run_migrations), файл-дубль каталога страхуется тестом.
