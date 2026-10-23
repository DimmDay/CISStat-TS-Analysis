# Акт независимой сертификации задачи DOCLOG-3

**Задача:** DOCLOG-3 (2026-10-22) — Telemetry/audit foundation: structured logging, redaction/error correlation, отдельный durable security audit, ops counters.
**Аудируемая поставка:** коммит `b530606` (линейная история: родитель `fa8c949` → `b530606` → `a6175d0`; продуктовый код `fa8c949`≡`288fdde`, а `a6175d0` добавляет только документацию сертификации DOCLOG-2 — атрибуция переносится, `git diff fa8c949 b530606` = поставка).
**База аудита:** `main@a6175d0` (свежий клон DimmDay/CISStat-TS-Analysis; рабочее дерево чистое).
**Дата акта:** 2026-10-23. **Сертификатор:** независимый контур DOCLOG-3-CERT.
**Режим:** оракулы на СВОИХ данных (корпус `d3cert-*` дизъюнктен repo и корпусам 0/1/2-CERT), мутанты СВОИ (двухканальная схема repo+oracle), манифест sha256 НЕ ведётся (указание тимлида; целостность обеспечивает git), AGENTS.md соблюдён (без commit/push).

---

## 1. Сверка заявлений с кодовой базой

Все ключевые заявления worklog-записи DOCLOG-3 (`worklog/worklog10.md`) и дизайн-дока `docs/doclog3_telemetry_audit.md` (120 строк) подтверждены чтением кода:

| # | Заявление | Факт | Статус |
|---|---|---|---|
| 1 | Контракт `doclog.telemetry/1` (§13.1): OTel-числа severity (1/5/9/13/17/21), allowlist-атрибуты, request_id/traceparent, subject surrogate | `telemetry.py`: `SCHEMA_VERSION`, `SEVERITY_NUMBERS` {trace:1…fatal:21}, `ALLOWED_ATTRIBUTE_KEYS` (19), `subject_pseudonym` для subject_material | ПОДТВЕРЖДЕНО |
| 2 | R08 двумя барьерами: allowlist (SQL-literals/env-dump физически не проходят) + `redact_text` (URL/DSN целиком, Bearer/Basic, key=value, URL-encoded через unquote, CR/LF/control, клип 300) | `redact_text` + `_neutralize_controls` + `_redact_structured`; счётчик `telemetry_attr_dropped_total` | ПОДТВЕРЖДЕНО |
| 3 | Сообщения исключений НЕ логируются вовсе (§13.3 строже маскирования): clean_exception хранит тип/кадры module:function:lineno/fingerprint sha256/chain до 6 | `clean_exception` — без str(exc); fingerprint sha256[:32] от error_code+кадров; chain depth<6 | ПОДТВЕРЖДЕНО |
| 4 | P0-подмена при сбое redaction: `telemetry.redaction_failed`, сырой контент нигде | `_emit_impl` except → минимальный fallback + `telemetry_redaction_failures_total` | ПОДТВЕРЖДЕНО |
| 5 | DEBUG-гейтинг env `CISSTAT_TELEMETRY_DEBUG`; сэмплинг только успешных GET (noisy_read), детерминированный sha256, WARN+/essential никогда | `_debug_enabled`/`_sample_rate`; условие `sample_class=="noisy_read" and not essential and severity<warn`; draw из sha256(event|request_id) | ПОДТВЕРЖДЕНО |
| 6 | AC11: collector failure не ломает расчёт — bounded spool 500 + dropped-счётчики; исключение dispatch → +emergency 20; flush_spool | `_TelemetryPipeline.on_sink_failure`/`flush_spool`; семантика «честный False = потеря → dropped» | ПОДТВЕРЖДЕНО |
| 7 | Durable security audit (§14.1): каталог 20 действий, классы 9 mandatory / 11 standard, DECISIONS allowed/denied/aborted, MandatoryAuditFailure fail-closed ДО действия | `security_audit.py`: `AUDIT_ACTIONS` (20), `AUDIT_REQUIREMENTS` (9/11), `record_mandatory` (исключение И отказ sink → MandatoryAuditFailure), `record_standard` никогда не бросает | ПОДТВЕРЖДЕНО |
| 8 | Корреляция: request_id валидный внешний принимается ([A-Za-z0-9_-]{8,64}), иначе свой req-hex12; X-Request-ID на каждый ответ; traceparent W3C проверяется; ContextVar протаскивает correlation | `accept_request_id`/`new_request_id`/`parse_traceparent`; `send_wrapper` добавляет заголовок в каждый `http.response.start`; `_REQUEST_ID_VAR` | ПОДТВЕРЖДЕНО |
| 9 | 401 → authn_denied (HMAC-псевдоним материала, не значение ключа); 403 → authz_denied; решения решающей таблицы → run_access_allowed/denied рядом с logger (сбой записи не меняет решения) | `auth.py::_audit_authn_denied` + `require_admin_role`; `identity.py::_audit_access_decision` после logger-строки | ПОДТВЕРЖДЕНО |
| 10 | Миграция 0009: telemetry_events (29 колонок) + security_audit_records (17) + 6 индексов; FK на research_runs НЕТ НАМЕРЕННО (§16.1: audit 365 дней переживает lifecycle); файл-дубль ≡ каталог | DDL сверен; `MIGRATION_STATEMENTS` 53 statement / 9 файлов; 0009 = 8 statement; паритет файл↔каталог оракулом pgm11 | ПОДТВЕРЖДЕНО |
| 11 | Нет новых HTTP-поверхностей | OpenAPI 171 путей (179 операций) И на родителе fa8c949, И на a6175d0 — паритет 171=171 | ПОДТВЕРЖДЕНО |
| 12 | Middleware ВНУТРИ CORS, СНАРУЖИ TraceHook; api.startup/shutdown essential | Порядок add_middleware: TraceHook → Telemetry → CORS (последний — внешний); lifecycle-emit в `_lifespan` | ПОДТВЕРЖДЕНО |
| 13 | health-блоки facts-only: peek без провокации фабрики, счётчики без содержимого (T6/T10) | `build_telemetry_health`/`build_audit_health` + `COMPONENT_TELEMETRY/AUDIT` в `storage_backend_snapshot` | ПОДТВЕРЖДЕНО |
| 14 | Postgres-приёмники: ленивый psycopg, run_migrations на первом коннекте, readiness_probe (SELECT 1 + to_regclass), INSERT telemetry 29 колонок / audit 16, ON CONFLICT DO NOTHING, commit на write | Код сверен; PG-зеркальные оракулы pgm01–pgm08: DDL↔INSERT↔runtime-параметры сходятся | ПОДТВЕРЖДЕНО |

**Расхождения заявлений (учётные, не поведенческие):**
- **R-N2:** telemetry.py фактически 1087 строк (заявлено 1071) — финальная ревизия файла; поведенческой сути не имеет.
- **R-N3:** «FastAPI 183 маршрута» — методика счёта не воспроизводится в этой среде; стабильная метрика сертификационной эпохи — **OpenAPI 171 путь** (так считала и DOCLOG-1-CERT), 179 HTTP-операций. Инвариантное заявление «новых поверхностей нет» подтверждено паритетом 171=171.

## 2. Оракулы на СВОИХ данных — 107 (35 unit + 37 unit2 + 24 API + 11 PG-зеркал)

Корпус дизъюнктен repo (`RUN-DOCLOG3*`/`d3-*`) и прошлым сертификациям (0: `RUN-DCAC0Axx`/`dca-*`; 1: `RUN-D1C*`/`d1cert-*`; 2: `RUN-D2C*`/`d2cert-*`): запуски `RUN-D3CERT11/22/99`, сессии `d3cert-sess-*`, админ-ключ `d3cert-admin-key-a1b2c3`, соль `d3cert-salt-oct2026-alpha`, сентинелы свои (`truffle-swine-77-d3cert`, `mysql://svc-d3cert:pivot-goose-88@db.d3cert.internal:3307/warehouse`, `AKIA-D3CERT-IO-777-QQ`, …), события `d3cert.*`, request-id `d3certreq-*`.

- **unit (35):** emit-контракт (30 полей, severity-таблица, fail-safe INFO, traceparent валиден/невалиден, request_id-границы, to_jsonl roundtrip, never-raises на мусоре); сентинелы AC10 (10 векторов × каналы message/attribute); surrogate ≠ материал (+ псевдоним даже невалидного ключа, стабильность, необратимость); клип 300.
- **unit2 (37):** pipeline (исключение sink → spool+emergency и never-raises; честный False → dropped, НЕ spool; границы 500/20; flush после восстановления; частичный flush; set_sink(None) сохраняет spool); статус/peek до инициализации; audit-контракт (полная форма записи, каталог 20 + тройка download/stream различна, классы 9/11, ValueError на неизвестных, mandatory fail-closed на исключение И на честный False, standard never-raises, invalid action счётчиком, маппинг AccessDecision, append-only статически, переполнение memory-аудита честно False, list_recent → NotImplementedError, форма INSERT audit); миграция 0009 (8 statement, без REFERENCES, 29/17 колонок, файл-паритет, каталог 53/9, INSERT-only telemetry SQL, нет новых маршрутов).
- **API (24):** identity durable-поток (deny/allow с псевдонимами и reason_code, AC11-инвариант при сломанном audit); 401/403 аудируются (материал ключа не дисклоужается); foreign run → uniform-404 + audit-запись с корреляцией request_id↔запись; middleware (X-Request-ID на ответ, валидный внешний request_id переиспользуется, невалидный → свой, traceparent проверяется, необработанное исключение → ERROR-событие с clean_exception, unmatched → низкокардинальная метка, OPTIONS//health не наблюдаются, POST не сэмплируется); сентинелы отсутствуют в /health/ops и error response; lifecycle.
- **PG-зеркала (11, класс F-D2C1 — перенос рекомендации DOCLOG-2-CERT):** pgm01 INSERT-колонки ≡ DDL 29/29 по порядку; pgm02 NOT NULL-без-DEFAULT покрыты INSERT; pgm03 динамический roundtrip fake-psycopg: каждый параметр ≡ значению СВОЕЙ колонки (attributes→JSON, sampled→bool); pgm04 ON CONFLICT+commit; pgm05 audit INSERT ≡ DDL минус recorded_at (16/16); pgm06 NOT NULL покрыты; pgm07 roundtrip audit-записи по именам колонок; pgm08 list_recent → NotImplementedError (честная граница); pgm09 без REFERENCES; pgm10 шесть индексов; pgm11 файл-паритет.

**GREEN ×2: 107/107** (3.08s / 3.14s — стабильность повторным прогоном). Протокол: `scripts/doclog3cert/protocols_green.txt`.

## 3. RED на родителе fa8c949 (git-worktree)

- **Статические факты 13/13 RED** (`red_static_facts.json`): telemetry.py / security_audit.py / тест поставки / дизайн-док / миграция 0009 отсутствуют; MIGRATION_STATEMENTS_0009, COMPONENT_TELEMETRY, TelemetryContextMiddleware, _audit_authn_denied, _audit_access_decision, build_telemetry_health, build_audit_health, api.startup — отсутствуют.
- **Оракульный корпус 107/107 ERROR** (ImportError отсутствующего контура; `red_oracle_corpus.txt`).
- Паритет OpenAPI родителя: 171 путь (совпадает с деревом — новых поверхностей нет).

## 4. Мутационная кампания — 30 боевых + 3 no-op-контроля, два канала

Цели: telemetry.py 18, security_audit.py 6, auth.py 1, identity.py 1, main.py 1, PG-зона 3. Точечные байтовые замены (контроль ровно 1 вхождения проверен до применения), восстановление из backup-копий с md5-паспортом (НЕ git checkout), RESTORE-FAIL 0, `git diff` пуст после кампании.

**Каналы:** ORACLE = 107 оракулов; REPO = `tests/api/test_doclog3_telemetry_audit.py` (96).

**Итог: 20 DUAL-KILLED + 10 ORACLE-ONLY + 0 SURVIVORS; контроли 3/3 ALIVE; паспорта OK.**

- DUAL-KILLED (20): M02 fail-safe severity, M03 DEBUG-гейт, M04 WARN-сэмплинг, M05 essential-сэмплинг, M07 URL/DSN-барьер, M08 Bearer, M09 key=value, M10 CR/LF, M11 клип, M12 fingerprint, M13 сообщение исключения, M15 allowlist, M16 семантика dropped, M19 mandatory fail-open (исключение), M21 каталог действий, M23 details без redaction, M24 маппинг allowed/denied, M25 401-субъект, M26 durable-поток AccessDecision, M28 middleware в стеке.
- ORACLE-ONLY (10): M01 (alias warning→13), M06 (детерминизм сэмплинга), M14 (кап chain), M17/M18 (границы spool/emergency), M20 (mandatory fail-open при честном False), M22 (класс обязательности authn_denied), **M29/M30/M31 — PG-зона класса F-D2C1** (сдвиг severity_text/number; сдвиг actor_via/tenant_id; write→False): repo-канал Postgres-пути write не пинует — ровно тот класс, ради которого PG-зеркала перенесены в оракульный корпус.

Рекомендация: перенести ORACLE-ONLY пины в repo-сюиты (в первую очередь PG-зеркала pgm01–pgm08 — прямой урок F-D2C1).

## 5. Регресс и сборка

- **Полный pytest tests/, дерево a6175d0:** 4567 passed / **31 failed** / 66 skipped (454.8s).
- **Полный pytest tests/, родитель fa8c949 (worktree):** 4471 passed / **31 failed** / 66 skipped (451.9s).
- **Дельта-0 доказана побайтово:** множества 31 FAILED-ID **ИДЕНТИЧНЫ** (`regress_full_failed_ids.txt`); прирост passed +96 = ровно корпус исполнителя. Классы падений средовые (предсуществующие): 14 × MNS-SPEC-PATH (test_mentor_next_step_spec), 7 × test_progress_audit_5b (psycopg DSN песочницы), 6 × neural-интеграции (deepar/lstm/nbeats/nhits/tft/capacity), 4 × modeling (workflow/candidates/panel/execution_contract). Ноль содержательных падений.
- **Адресные смежные контуры:** doclog0+doclog1+doclog2+doclog3+research_runs+session_store **412/412**; diagnostics+diagnostics_internal+admin_progress+run_report **93/93**.
- **Сборка:** `apps.api.main` импортируется (TestClient во всех API-оракулах); OpenAPI 171 путь / 179 операций (паритет с родителем — новых HTTP-поверхностей нет); каталог миграций **53 statement / 9 файлов**; AUDIT_ACTIONS=20; SCHEMA `doclog.telemetry/1` + `doclog.security_audit/1`.

## 6. Находки и вердикт

- **N1 (repo-гэп, кандидат на пин):** PG-зеркала класса F-D2C1 (pgm01–pgm08) существуют только в оракульном корпусе; мутанты M29/M30/M31 убиты exclusively оракулом. Рекомендация — перенос в repo-сюиты (прецедент fakeredis).
- **N2/R-N2 (учётное):** 1087 строк telemetry.py против заявленных 1071 — расхождение счётное, поведенческой сути не имеет.
- **N3/R-N3 (учётное):** методика счёта маршрутов («183») не воспроизводится; метрика эпохи — OpenAPI 171 (паритет 171=171).
- **N4 (честная граница, поведение корректно):** CORS-preflight OPTIONS отвечает самый внешний CORSMiddleware — на preflight-ответе X-Request-ID нет (middleware телеметрии внутрь не вызывается); на все ответы, проходящие через телеметрию (включая обычные OPTIONS и /health), заголовок ставится. Слоистость честная; семантика наблюдаемости пинется repo-тестом.
- **N5 (положительное):** урок о нереентерабельности `threading.Lock` закреплён в коде комментарием `on_sink_failure` (счётчики только ВНЕ блока); семантика «честный False = потеря → dropped, исключение = spool+emergency» подтверждена оракулами и мутантами M16/M17/M18.
- **N6:** 10 ORACLE-ONLY пинов — перенос в repo-сюиты не блокирует, рекомендован.
- **Честные границы (НЕ покрыто и НЕ заявляется):** живой PostgreSQL-прогон миграции 0009 (паттерн AUDIT-6A — при следующем durable-срезе); чтение durable-журналов и UI (DOCLOG-7/DOCLOG-4); OTLP/OTel SDK-экспорт (to_jsonl — адаптер будущей поставки); retention-очистка telemetry_events/security_audit_records (§16.1 — отдельный контур); вызовы record_mandatory из approval/publish-контуров (появятся в DOCLOG-6 — API готов).

## 7. ВЕРДИКТ

**PASSED.** Критерии задачи DOCLOG-3 (§19: «Structured logging, redaction/error correlation, отдельный durable security audit, ops counters»; критерий завершения «sentinel/negative auth/collector failure проверки») подтверждены: sentinel-батарея AC10 (10 векторов × 2 канала) чиста в sink-записях/JSONL//health/ops/error response; негативные auth-сценарии (401/403/foreign run) аудируются с HMAC-псевдонимами и корреляцией request_id; collector failure не ломает расчёт (AC11: spool/dropped/emergency + fail-closed mandatory audit). Все прочие контуры поставки (контракт §13.1/§13.3, allowlist+redact R08, clean_exception без сообщений, сэмплинг/DEBUG-гейтинг, durable audit §14.1 с классами обязательности, миграция 0009 без FK, health facts-only) PASSED. Продуктовый код аудитом не менялся (md5-паспорта до/после идентичны, git diff пуст).

Акт: `docs/cert_doclog3_2026-10-23.md`. Артефакты: `scripts/doclog3cert/` (conftest.py, test_doclog3cert_oracle_unit.py, test_doclog3cert_oracle_unit2.py, test_doclog3cert_oracle_api.py, test_doclog3cert_oracle_pgmirror.py, red_repro.py + red_static_facts.json + red_oracle_corpus.txt, mutations.py + mutations_protocol.json, protocols_green.txt, regress_full_failed_ids.txt), `worklog/worklog10.md` (запись DOCLOG-3-CERT). Без commit/push (AGENTS.md). Манифест sha256 не ведётся и не используется (указание тимлида).
