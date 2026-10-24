# Акт независимой сквозной приёмки DOCLOG-CERT
## Сервис документирования и логирования (DOCLOG-0…9), база main@5856764

**Дата:** 24 октября 2026. **Задача:** Task ID: DOCLOG-CERT (2026-10-24) —
сквозная приёмка (спека `spec_documentation_logging.md` §19, последняя строка:
«Независимый негативный/сбойный/права/методический корпус и миграция»;
критерий завершения: «выполнены относящиеся критерии §20, ограничения явно
перечислены»). **База:** `main@5856764` (HEAD origin/main; DOCLOG-9 и
DOCLOG-8-CERT включены). **Правила:** AGENTS.md (TDD RED→GREEN, регресс,
сборка, ZIP, worklog; без commit/push).

Методология «оракулы на своих данных, мутанты на своих мутантах» —
прецедент DOCLOG-3…8-CERT, без послаблений.

---

## 1. Корпус сертификатора (scripts/doclogcert/)

**119 оракулов GREEN ×2 на 5856764** (unit 59: u01–u59; API 40: a01–a40;
static 20: s01–s20; прогон ~4.7 с). Namespace дизъюнктен repo-корпусам
DOCLOG-0…9 (RUN-D6xxxxxx, d6-*, d8-*, d9-*, org-*) и корпусам предыдущих
сертификаторов (d6cert-*, d7c-*, d8cert-*): **RUN-E2C\*, e2cert-session-\*,
ctx-e2c-\*, fc-e2c-\*, subj-e2c-\* (хвосты hex16 по паттерну identity),
tenant-e2c-2, sentinel CISSTAT_E2C_SECRET_SENTINEL**.

СВОИ данные: собственные research runs (bound), артефакты прогноза
(штатный artifact_store stage/commit/register, T8-совместимые), снимки/
документы/согласования/retention через штатные сервисы, actual vintages и
сверки MonitoringService, org-профили (pdfa/docx), support-гранты, свои
API-ключи (admin / logs.read+audit.read+logs.export / без scopes /
**logs.read+audit.read БЕЗ logs.export** — усиление в ходе кампании).
Изоляция каждого теста — свой tmp CISSTAT_DATA_DIR, сброс ВСЕХ singleton-
фабрик контура (19 reset-функций, включая doc_profiles/admin_logs/
monitoring/delivery_worker/storage_diagnostics), memory-бекенды.

### Покрытие §20 (AC-матрица)

| AC | Оракулы (примеры) | Итог |
|---|---|---|
| AC01 | a01 (run→документы D02/D08/D12), u06 (dangling ref → honest unknown), a02 (D12 пустая → unknown, не 0) | PASSED |
| AC02 | u07 (payload заморожен после новых событий), u01/u02 (идемпотентность/conflict 409) | PASSED |
| AC03 | u09/u10 (паритет текстов claims в json/jsonl/md/html/csv), u11 (hash форматов различны), u03 (knowledge_version пинится), s-оракул ZIP-даты | PASSED |
| AC04 | u58/u59 (публикация и байты rendition переживают reset TTL-сессии; restore-континуитет детерминированного псевдонима), a08 (то же через HTTP) | PASSED |
| AC05 | a04 (fingerprint науки до/после GET-выдачи идентичен; audit исключён из отпечатка — доступен прирост), a05 (download-тройка) | PASSED |
| AC06 | a06 (uniform-404 матрица 17 маршрутов × чужой/аноним; тела без дисклоужения), a09 (scoped-режим — права не фантазируются), M22/M23 (мутанты) | PASSED |
| AC07 | u52/u53 (bound-hash approve; publish без approval отказ), u54 (перепроверка hash на publish — пин точной строки), a10–a13 (два лица, self-approval 422, wrong hash 409) | PASSED |
| AC08 | u31/u32 (реклейм lease: attempt не растёт; чужой живой lease не трогается), u34/u35 (crash → terminal failed, без broken ready refs; retry честный), a15/a16 (очередь+worker через HTTP, crash-injection, cancel) | PASSED |
| AC09 | u01/u02/u33 (снимок/job/сверка идемпотентны; конфликт тела → 409), a03, a15 (повтор тяжёлой цели — тот же job) | PASSED |
| AC10 | a37 (плоские тела ошибок без traceback), a38 (/health/ops без sentinel), a35 (пакет поддержки: sentinel/сессия/ключ отсутствуют), s-оракулы (allowlist исключений, key-header-only) | PASSED |
| AC11 | u41–u43 (ломучий/ложный sink: emit не роняет, dropped/spool виден, восстановление), u44–u46 (mandatory audit fail-closed на approve: raising и «молчащий» sink; standard-сбой чтение не ломает), u47 (порог-факт vs отдельное решение), M10/M12/M13 | PASSED |
| AC12 | u48–u50 (ape null+reason при нуле; mape null; mase null+mase_scale_required; invalid scale 422), M15/M16 | PASSED |
| AC13 | u06-класс (секция D09 — только panel-вселенная; однорядный run не попадает в панельное приложение — честное отсутствие) | PASSED (граница: полный панельный прогон — вне среды, см. §5) |
| AC14 | u05-класс (D08-claims сохраняют alpha/горизонт/точки из frozen-артефакта; мониторинг — coverage null без границ, interval_hit null) | PASSED |
| AC15 | u46 (units unknown честно), u47-класс (mismatch 422; нулевой factor 422), u51 (новая партия — новая сверка; старая заморожена), a28–a32 (то же через HTTP) | PASSED |
| AC16 | u12–u15 (CSV formula-injection апострофом; HTML-экранирование; ZIP без traversal + манифест с sha256), s-оракулы (use client-каркас, key не в localStorage) | PASSED |
| AC17 | a15–a17 + a36 (состояния queued/ready/failed/cancelled/403/404/409/410/422/429 воспроизводимы через HTTP), jest-сюиты документационного UI (89 тестов: Workspace/Monitoring/Profiles/AdminLogs/Lifecycle/Preview/Badge/Standalone) | PASSED (API/уровень компонентов; браузерная визуальная приёмка — граница §5) |
| AC18 | a39 (archive → verify ok), a40 (утрата члена пакета — missing НЕ маскируется), u56/u57 (hold приоритетен; purge → честный tombstone 410; published не очищается) | PASSED |
| AC19 | a35 (диагностический пакет открывается независимым zipfile-читателем без сессии; excluded-список явен), u57-класс (подпись: verify ок/tamper; без ключа — честный отказ), u55 (профиль подтверждён валидатором, не именем файла) | PASSED |
| AC20 | — | НЕ ПРОВЕРЕНО (нагрузочный корпус §18 — вне среды; см. §5) |

---

## 2. RED на родителе и мутационная кампания

**RED на родителе** DOCLOG-0 `cc5c14e` (pre-DOCLOG, git-worktree + копия
корпуса): collection RED — ImportError doclog-модулей, 0 passed
(protocols/red_parent.json) — корпус не вакуумный.

Кампания «мутанты на своих мутантах»: REPO-канал = полный doclog-набор
`tests/api/test_doclog0…9` (582 теста, ~13 с), ORACLE-канал = корпус (119).
**27 боевых мутантов + 3 no-op контроли над 13 файлами контура:**
**23 DUAL-KILLED + 4 ORACLE-ONLY + 0 REPO-ONLY + 0 боевых SURVIVED;
контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0**; MV1 30/30 якорей;
MV2 self-test классификатора; MV3 md5-восстановление (байт-в-байт == HEAD);
MV5 скан хвостов — посторонних файлов в киллах нет. Протокол де-флака
(класс N2 DOCLOG-6-CERT: TestXlsxRender::determinism в комбинированном
прогоне) — один автоматический повтор канала при единственном
флак-FAILED-ID; во всех таких случаях повтор давал зелёный канал.

Ключевые DUAL-KILLED: конфликт идемпотентности снимка/цели, knowledge-pin,
CSV-injection, HTML-escape, two_person, bound-hash approve, publish без
approval, mandatory→standard, реклейм живых lease, невидимая потеря
телеметрии, незрелый горизонт с нулевой ошибкой (§6.1), MAPE-фабрикация,
units mismatch молча as_is, whitelist/TTL грантов, валидатор PDF/A «по
имени», безымянный PDF/A, owner-bypass решающей таблицы, uniform-404→403,
T4 (subject==key), саможурналирование, mismatch профиля готовой цели.

**ORACLE-ONLY (4, genuine — пины остаются в корпусе сертификатора):**
- M01 — гейт конфликта реестра снимков (защита в глубину; через API затенён
  service-гейтом; repo-канал пина не имеет).
- M13 — mandatory fail-open при отказе sink (repo-пин покрывает raising-
  sink, «молчащий» false-sink — только оракул u46).
- M19 — export-гвард сборки пакета (пер-стримовые гейты затеняют её для
  ключа без scopes; случай «logs.read есть, logs.export нет» — только
  оракул a35a; ключ NOEXPORT добавлен в корпус в ходе кампании).
- M27 — перепроверка bound-hash на publish (полный путь через T8-loader
  недостижим для подмены hash — граница зафиксирована DOCLOG-6-CERT;
  пин точной строки — оракул u54 через подмену резолва записи).

Эволюция оракулов в ходе кампании (честно): M01/M27 изначально SURVIVED —
добавлены u-gate/u54; M19 изначально SURVIVED — добавлен NOEXPORT-ключ и
a35a; M26 изначально REPO-ONLY — оракул усилен готовой целью → DUAL.
Исторические протоколы порций сохранены в protocols/mut_*.json.

---

## 3. Регресс дельта-0, сборка, jest

**Дельта-0** полного tests/api (regress_delta0.py; кэш pytest отключён):
цель 5856764+корпус **27F/2901P/42S** vs база 5856764 (git-worktree)
**27F/2782P/42S** — **FAILED-ID байт-идентичны 27/27**; +119 passed = ровно
корпус (119 оракулов). Все 27F — предсуществующие средовые классы базы
(forecasting-session, psycopg-DSN progress_audit_5b/6c, modeling-neural/
candidates, structural-breaks/profile, upload-duckdb/panel); doclog-файлы
в failed отсутствуют.

**Сборка** (build_check.json): import apps.api.main OK — **221 маршрут**
(документация+мониторинг+профили /v1/documentation, журналы /v1/logs),
миграции **15/93** (последняя 0015_doclog9_profiles.sql), DOCUMENT_KINDS=12,
AUDIT_ACTIONS=28, GRANT_SCOPES={audit.read,logs.export,logs.read}, TTL=168,
PROFILE_FORMATS={docx,pdfa}, RENDITION_FORMATS=13 (heavy 8),
DECISION_ACTIONS/THRESHOLD_METRICS по контракту; продуктовое дерево чистое
(md5 == HEAD) — **BUILD: OK**. typecheck:all (embedded+standalone) — 0.

**Jest** документационного UI: 9 сюит **89/89** (doclog8-monitoring-ui 7,
doclog9-profiles-ui 8, adminLogs-dashboard 9, doclog6-lifecycle-ui 15,
DocumentationWorkspace, doclog4-preview-header, doclog4-badge-dark,
DocumentationWavesBackground, standalone documentation page).

---

## 4. Верификация «миграция» (§19)

- Цепочка 0006→0015 присутствует и заявлена в каталоге research_runs
  (15 файлов / 93 statement); каждый файл — только CREATE/ALTER ADD
  (s-оракул «additive_no_drop»; DROP TABLE/COLUMN отсутствуют во всех 15).
- Reader раньше writer: adapter-каталоги читают версии до включения
  writer-веток (repo-пины doclog2/7; дельта-0 чистый).
- Исторические events/receipts не переписываются: append-only контуры
  (monitoring decisions, lifecycle, audit) закреплены оракулами u51/u54/
  u44-класса и repo-пинами DOCLOG-6/8.

## 5. Честные границы приёмки

1. **H29/H30 (эксплуатационные)** — не проверены: живого PostgreSQL/Redis
   и доступа к Render в среде нет; durable-прогоны миграций 0006–0015 на
   живом PG остаются открытым пунктом AUDIT-6A/DOCLOG-серий (фиксируется
   в каждом акте серии).
2. **AC20 (нагрузка §18)** — не измерялась: квоты/lease/лимиты проверены
   функционально (u33/a15-класс), статистика §18 не собиралась.
3. **Браузерная визуальная приёмка (AC17-визуал)** — не выполнялась:
   уровень UI-оракулов здесь — jest-компонентные сюиты и HTTP-состояния;
   скриншотная/E2E-браузерная приёмка двух тем — отдельный контур.
4. **Docker-сборка образа, Render/Vercel деплой, veraPDF** — вне среды
   (veraPDF — заявленная граница DOCLOG-9; структурный валидатор пинится
   оракулом u55).
5. **AC13 (панель ≥5 сущностей)** — полная панельная линейка прогоняется
   repo-корпусом PANEL-MODELS/GMM; здесь панельная секция документа
   пинится на уровне адаптера (изоляция panel-вселенной D09).
6. Средовые классы базы (27F) не считаются регрессией: FAILED-ID байт-
   идентичны базе (дельта-0).
7. **DOCLOG-9-CERT** (независимая сертификация DOCLOG-9) в журнале не
   отражена на момент этой приёмки — граница ответственности работ;
   сквозная приёмка не заменяет персональную сертификацию задачи.

## 6. Вердикт

**PASSED WITH BOUNDARIES** — все относящиеся к среде критерии §20 (AC01–
AC19) подтверждены двухканально (оракулы на своих данных + полный repo-
канал doclog-сюит), негативные/сбойные/права/методические классы
закреплены мутационной кампанией (0 боевых выживших), миграционная цепочка
аддитивна; ограничения перечислены в §5 и не включают заявлений о
production-долговечности, нагрузке и визуальной браузерной приёмке.

Доставляемое: `scripts/doclogcert/` (корпус + machinery + protocols/),
`docs/cert_doclogcert_2026-10-24.md` (акт), `worklog/worklog11.md`
(запись). Продуктовый код не менялся (product_tree_md5_eq_head: true).
Без commit/push (AGENTS.md). Манифест sha256 не ведётся (указание
тимлида, прецедент DOCLOG-2-FIX…8).
