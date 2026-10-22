# DOCLOG-3 — Telemetry/audit foundation (контрактный документ)

*Task DOCLOG-3, 2026-10-22. Спецификация-источник: `spec_documentation_logging.md`
(§13 «Техническое логирование и корреляция», §14 «Аудит доступа», §15 «Права,
tenancy» п.15.1, §16.1 retention, §19 строка DOCLOG-3 и §19.1, §20
AC10/AC11). База: main@288fdde (DOCLOG-0 + DOCLOG-0-CERT + DOCLOG-1 +
DOCLOG-2 включены). Поставка следует AGENTS.md (TDD RED→GREEN→регресс,
без commit/push).*

## 1. Постановка и граница задачи

DOCLOG-3 — четвёртый срез эпика документирования/логирования (§19):
**«Structured logging, redaction/error correlation, отдельный durable
security audit, ops counters»**. Зависимость — DOCLOG-0 (выполнен);
параллельно 1/2 (выполнены); обязан быть готов **до выдачи защищённых
документов** (§19). Критерий завершения (та же строка): **sentinel /
negative auth / collector failure проверки** (AC10/AC11).

Вне границы (по §19): HTTP-выдача и UI документов (DOCLOG-4),
форматы/renditions/worker (DOCLOG-5), approvals/publish (DOCLOG-6),
admin logs UI/diagnostic bundle/scope grants (DOCLOG-7), мониторинг D12
(DOCLOG-8), OTel SDK/OTLP-exporter (адаптер будущей поставки — здесь
только JSONL-адаптер `to_jsonl`). Новых HTTP-маршрутов поставка НЕ
добавляет (маршруты чтения журналов — DOCLOG-7; проверено оракулом
отсутствия `/v1/documentation|/v1/audit|/v1/logs` поверх).

## 2. Что реализовано (карта изменений)

| Файл | Состав |
|---|---|
| `apps/api/telemetry.py` (НОВЫЙ) | Контракт `doclog.telemetry/1` (§13.1): `emit()` — единая точка тех-событий (schema_version, occurred_at/observed_at, severity_text/number OTel: TRACE=1/DEBUG=5/INFO=9/WARN=13/ERROR=17/FATAL=21, message_template, allowlist-attributes, service/version/environment/instance, request_id, trace_id/span_id, operation_id/execution_id, research_run_id/context_id, outcome, method, error_code/fingerprint, duration_ms, retry_attempt, subject_surrogate, tenant_id, sampled); `parse_traceparent` (W3C [S4], вход проверяется — доверие к внешнему caller не предполагается); `new_request_id`/`accept_request_id` (внешний — только безопасная форма `[A-Za-z0-9_-]{8,64}`); redaction R08 (два барьера: allowlist `ALLOWED_ATTRIBUTE_KEYS` + `redact_text`: URL/DSN целиком, Bearer/Basic, key=value-секреты, URL-encoded (unquote→redact), многострочные, CR/LF/control → экранирование, клип 300); `clean_exception` (БЕЗ locals/args/сообщений — только module/function/lineno + error_code + stack-fingerprint sha256 + chain до глубины 6); DEBUG-гейтинг (env `CISSTAT_TELEMETRY_DEBUG`, off по умолчанию); детерминированный sampling `noisy_read` (env `CISSTAT_TELEMETRY_SAMPLE_RATE`, по умолчанию 1.0; WARN+/essential — никогда); sink'и `MemoryTelemetrySink` (bounded, переполнение → False) и `PostgresTelemetrySink` (ленивый psycopg, миграция 0009); pipeline с bounded spool (500) + emergency fallback (20) + счётчики; `to_jsonl` (адаптер), `telemetry_status`, `flush_spool`; `TelemetryContextMiddleware` — чистый ASGI |
| `apps/api/security_audit.py` (НОВЫЙ) | Контракт `doclog.security_audit/1` (§14.1): `build_audit_record` — кто (псевдоним)/когда/tenant/resource/version/действие/решение allowed\|denied\|aborted/основание/correlation; каталог `AUDIT_ACTIONS` (20 действий: authn/authz-отказы, run_access, grants, protected_document_viewed, download_requested + response_stream_started/finished — тройка РАЗЛИЧАЕТСЯ, human_read_confirmed НЕ существует, approval/publish/revoke, template/retention, audit_log_accessed, cleanup/restore, integrity); классы обязательности `AUDIT_REQUIREMENTS`: **mandatory** (publication/approval/выдача защищённых данных/grants — fail-closed) vs **standard** (durable best-effort); `record_mandatory` → `MandatoryAuditFailure` ДО выполнения защищённого действия (AC11); `record_standard` — никогда не бросает, сбой виден счётчиком `audit_write_failures_total`/`audit_dropped_total` и degraded; `record_run_access_decision` — интеграция решающей таблицы DOCLOG-0; sink'и Memory (bounded, НЕ молчаливый) + Postgres (INSERT-only, миграция 0009); append-only по построению (в исходнике нет операций изменения/удаления — страхуется тестом) |
| `apps/api/migrations/0009_doclog3_telemetry_audit.sql` (НОВЫЙ) | `telemetry_events` (29 колонок, индексы time/name/request) + `security_audit_records` (17 колонок, индексы action/tenant/request). FK на research_runs НЕТ НАМЕРЕННО: журналы переживают удаление run (§16.1: audit 365 дней против lifecycle запуска). INSERT-only, аддитивная (читатели раньше писателей) |
| `apps/api/research_runs.py` (ОБНОВЛЁН) | `MIGRATION_STATEMENTS_0009` (8 statement: 2 таблицы + 6 индексов) + каталог `MIGRATION_FILES` (9 файлов/53 statement; паритет файл↔каталог страхуется тестами — паттерн 0007/0008) |
| `apps/api/identity.py` (ОБНОВЛЁН) | `_finish` решающей таблицы: durable-поток `security_audit.record_run_access_decision` РЯДОМ с logger (закрыто обещание DOCLOG-0 «DOCLOG-3 заменит logger на durable-поток»); сбой записи НЕ меняет уже принятое решение (AC11-инвариант: deny остаётся deny) |
| `apps/api/auth.py` (ОБНОВЛЁН) | 401 (невалидный ключ) → `authn_denied` durable-запись: субъект — HMAC-псевдоним ПРЕДЪЯВЛЕННОГО материала (связь повторов сохранена, значение ключа не восстановимо и не дисклоужается); 403 (`require_admin_role`) → `authz_denied` (псевдоним, НЕ principal_id) |
| `apps/api/storage_diagnostics.py` (ОБНОВЛЁН) | `COMPONENT_TELEMETRY`/`COMPONENT_AUDIT` в снимке фабрик; `build_telemetry_health()`/`build_audit_health()` — facts-only блоки `/health/ops.telemetry`/`.audit`: backend (peek БЕЗ провокации фабрики), счётчики, degraded, конфиг политики; содержимое событий/записей НЕ выдаётся (T6/T10) |
| `apps/api/main.py` (ОБНОВЛЁН) | `TelemetryContextMiddleware` — ВНУТРИ CORS, СНАРУЖИ TraceHook (порядок add_middleware: последний внешний); X-Request-ID на КАЖДЫЙ ответ включая ошибки (§13.1 error correlation); `api.startup`/`api.shutdown` (essential, сбой телеметрии не влияет на старт — AC11) |
| `tests/api/test_doclog3_telemetry_audit.py` (НОВЫЙ) | 96 оракулов на СВОИХ данных (sentinels дизъюнктны repo-корпусу): контракт события/severity/traceparent/request_id; sentinel-батарея AC10 ×2 канала (message/attribute) + SQL-literal (allowlist) + health/error-response + subject-surrogate + клип; clean_exception (chain/без locals/fingerprint стабилен и различает); allowlist; DEBUG/sampling; collector failure (spool/overflow→dropped/flush/redaction-P0/emergency); аудит (поля/тройка download/каталог §14.1/append-only/redaction details/mandatory fail-closed/standard best-effort/классы); фабрики; интеграции identity (deny+allow durable, сбой аудита не меняет решение) и auth (401/403); HTTP negative auth (uniform-404 без run_id + корреляция request_id↔audit); middleware (route template/статус-класс/traceparent/500-redacted/unmatched/OPTIONS+/health-exclude/sampling GET-vs-POST); main-wiring (/health/ops блоки, без sentinel, без новых маршрутов); миграция (паритет/append-only DDL/без FK/индексы/53 statement × 9 файлов) |

## 3. Ключевые проектные решения

1. **Отдельные потоки, общие фильтры (§13 vs §14.1).** Тех-события —
   fail-open (collector недоступен → bounded spool + счётчики, расчёт
   не ломается); security audit — durable (Postgres INSERT-only),
   класс mandatory — fail-closed. Redaction R08 при этом ОДИН:
   `redact_text`/`clean_exception` из telemetry используются
   security_audit'ом (details записей проходят тот же фильтр).
2. **Семантика сбоя доставки.** Sink вернул False (переполнение
   memory-приёмника) = запись ПОТЕРЯНА → `telemetry_dropped_total`
   (§13.2: «переполнение очереди видимо через dropped_records»);
   sink бросил исключение (collector недоступен) = запись в bounded
   spool (SPOOL_MAX=500) + `telemetry_sink_failures_total` + emergency
   заметка (EMERGENCY_MAX=20) + `telemetry_emergency_total`;
   `flush_spool()` — повторная доставка после восстановления.
3. **Сообщения исключений не логируются вовсе** (строже простого
   masking): §13.3 требует «без locals, аргументов и секретных
   messages» — clean_exception сохраняет только тип/кадры/fingerprint;
   связь с инцидентом — fingerprint + request_id.
4. **request_id: валидный внешний принимается** (корреляция поддержки
   между системами), мусор/инъекция → свой `req-<hex12>`; публикуется
   ContextVar'ом — identity/auth коррелируют durable-записи с ответом
   без протаскивания параметров через слои (проверено оракулом
   равенства request_id в ответе 404 и audit-записи).
5. **Subject surrogate даже для НЕвалидных ключей** (§13.3: «новый
   лог обязан использовать независимый subject surrogate/HMAC, не
   principal_id как есть»): HMAC-псевдоним предъявленного материала —
   связь повторов сохранена, материал не восстановим.
6. **Sampling — детерминированный** (sha256(event_name|request_id)),
   только класс `noisy_read` (успешные GET), WARN+/essential — никогда;
   «Без sampling: security audit, approval/revocation, обязательные
   научные факты и critical failures» (§13.2) — аудит отдельным
   потоком без sampling, критические failures — severity ≥ WARN.
7. **X-Request-ID на КАЖДЫЙ ответ, включая /health и OPTIONS** —
   корреляция поддержки не должна зависеть от пути; событие
   `api.request` при этом не пишется для liveness/OPTIONS (шум §13.2).
8. **Фабрики/флаги честности** — паритет DOCLOG-1/2: singleton с
   peek-семантикой (health не провоцирует инициализацию),
   `record_backend_selected/fallback` в снимок фабрик, required-режим
   fail-closed (P21/F14), reset для тестов; env:
   `CISSTAT_TELEMETRY_BACKEND`, `CISSTAT_AUDIT_BACKEND`
   (memory|postgres|auto по DATABASE_URL).
9. **Миграция 0009 без FK на research_runs** — осознанно: retention
   аудита (365 дней, §16.1) переживает lifecycle запуска; каскадное
   исчезновение журнала действий вместе с ресурсом недопустимо.

## 4. Верификация

- **RED**: 96 ошибок на отсутствующем контуре (ImportError
  apps.api.telemetry — все оракулы красные честно).
- **GREEN**: 96/96, повторный прогон 96/96 (стабильность).
- **Адресная регрессия смежных контуров** (441 тест): doclog0+doclog1+
  session_store 188; doclog2+research_runs+admin_progress_api+
  diagnostics 157; run_report+admin_analytics 89; catalog+
  no_false_positives 7 — все зелёные.
- **Сборка**: `apps.api.main` импортируется; FastAPI-приложение
  собирается (183 маршрута — БЕЗ изменений, новых HTTP-поверхностей
  нет); каталог миграций 53 statement / 9 файлов (45+8, аддитивно).
- **Полный регресс tests/**: 4492 passed / 103 failed / 3 errors —
  **дельта-0 доказана stash-методом**: множество 106 FAILED/ERROR-ID
  на рабочем дереве байт-идентично чистому 288fdde (git stash push -u →
  полный прогон → diff множеств → пусто → stash pop; классы
  предсуществующих: prophet/tbats/deepar/duckdb/neural-зависимости и
  MNS-SPEC-PATH — средовые, ноль содержательных падений).

## 5. Честные границы

Не покрыто и НЕ заявляется: чтение durable-журнала (PostgresAuditSink.
list_recent — NotImplementedError до DOCLOG-7); UI журналов
(«Администрирование → Журналы» — DOCLOG-7); diagnostic bundle
(redacted JSONL+manifest — DOCLOG-7); OTLP/OTel SDK-экспорт (to_jsonl
— адаптер будущей поставки); retention-очистка telemetry_events
(30 дней — политика §16.1, отдельный контур); grants/support
(DOCLOG-6/7); wire проводов approval/publish (DOCLOG-6 — record_
mandatory готов к вызову, защищённые действия появятся там). Живой
PostgreSQL-прогон 0009 — при следующем durable-срезе (паттерн
AUDIT-6A). D01–D09 адаптеры секций продолжают писать только durable
факты (DOCLOG-2); telemetry не дублирует научный ledger — факт
результата хранится в артефактах/ledger, telemetry фиксирует
исполнение и outcome (§13.2).
