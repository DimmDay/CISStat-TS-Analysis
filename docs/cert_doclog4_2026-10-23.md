# Акт независимой сертификации задачи DOCLOG-4

**Задача:** DOCLOG-4 (2026-10-23) — UI и MVP выдачи поверх снимков 2+3: раздел документов, stage entry points, HTML/MD/JSON/JSONL/CSV, job states.
**Аудируемая поставка:** коммит `2caf08e` (родитель `1178288` = DOCLOG-3-FIX; `git diff 1178288 2caf08e` = поставка).
**База аудита:** `main@2caf08e` (рабочее дерево чистое, репозиторий DimmDay/CISStat-TS-Analysis).
**Дата акта:** 2026-10-23. **Сертификатор:** независимый контур DOCLOG-4-CERT.
**Режим:** оракулы на СВОИХ данных (корпус `d4cert-*`/`RUN-D4C*` дизъюнктен repo и корпусам 0/1/2/2-FIX/3-CERT), мутанты СВОИ (двухканальная схема repo+oracle, «мутанты на своих мутантах»), манифест sha256 НЕ ведётся (указание тимлида; целостность обеспечивает git), AGENTS.md соблюдён (без commit/push).

---

## 1. Сверка заявлений с кодовой базой

| # | Заявление (контракт-док `docs/doclog4_document_delivery.md`, worklog) | Факт | Статус |
|---|---|---|---|
| 1 | Рендеры P0 — чистые функции от ReportSnapshot (R06/AC05), каталог {csv,html,json,jsonl,md} | `document_renditions.py`: рендеры не читают run/сессию; P0-каталог подтверждён; 57 green-оракулов + мутанты M01–M07 | ПОДТВЕРЖДЕНО |
| 2 | HTML-безопасность двумя слоями (AC16): экранирование всего, нейтрализация схем, статический CSS, sandbox-iframe UI | Сентинелы `<script>`/`onerror`/`javascript:` нейтрализуются; M01/M02 DUAL-KILLED | ПОДТВЕРЖДЕНО |
| 3 | Job-контракт без worker: queued→rendering→ready/failed/cancelled, идемпотентность rendition, cancel терминальные состояния уважает | `document_jobs.py` + оракулы; M08 DUAL-KILLED, M10/M11 ORACLE-ONLY | ПОДТВЕРЖДЕНО |
| 4 | Одна объектная авторизация на каждом маршруте (R09/T15), отказ uniform-404 | Матрица owner/foreign/anonymous/admin на ВСЕХ 8 путях — repo + оракул; M13 DUAL-KILLED | ПОДТВЕРЖДЕНО |
| 5 | N3-гейт (акт DOCLOG-2-FIX): dependency manifest только внутри авторизованного GET /revisions/{id} | Оракул TestOrcN3Gate GREEN; M16 (утечка refs в список) DUAL-KILLED | ПОДТВЕРЖДЕНО |
| 6 | AC05: read/preview/rendition/content не меняют science state | Tripwire-фингерпринт durable state (repo TestNoScienceMutation + оракул TestOrcNoScienceMutation) GREEN | ПОДТВЕРЖДЕНО |
| 7 | Миграция 0010: 4 таблицы + 5 индексов; каталог 10 файлов/62 statement; паритет файл↔каталог | DDL/UNIQUE/индексы сверены; PG-зеркало реестра документов в repo-сюите; 10/62 подтверждено импортом | ПОДТВЕРЖДЕНО |
| 8 | /health/ops.documents facts-only (T6/T10) | Оракул: блок без путей/DSN/data-root | ПОДТВЕРЖДЕНО |
| 9 | «Аудит выдачи — все записи standard-класс (AC11-инвариант: сбой аудита не ломает выдачу)» | **ОПРОВЕРГНУТО.** AC11: «Обязательный security audit при защищённой выдаче fail-closed до раскрытия»; §14.1: «…отказ до выполнения». Каталог сертифицированного DOCLOG-3 (`AUDIT_REQUIREMENTS`) закрепляет protected_document_viewed/download_requested/response_stream_started/finished = **mandatory**. Реализация пишет все 4 через `record_standard` (routers/documentation.py:424,544,570,584) → fail-open (находка F-D4C2, RED ×2) | **ОПРОВЕРГНУТО** |
| 10 | §14.1: запись фиксирует фактическое решение (разрешено/отказано/прервано) | **ОПРОВЕРГНУТО.** `download_requested` пишется с decision=«allowed» ДО `authorize_run_access` (routers/documentation.py:543–556 — авторизация внутри `read_rendition_content` строкой ниже); при отказе чужому в durable audit остаётся ложный факт «allowed» (находка F-D4C3, RED) | **ОПРОВЕРГНУТО** |
| 11 | AC09: «дубликат idempotency key/body не создаёт новые jobs/версии; другое тело →409» | **ЧАСТИЧНО ОПРОВЕРГНУТО.** Builder-путь защищён (UNIQUE(run_id,key), 409 есть); reuse-путь черновика (refresh=false) ключ игнорирует: тот же ключ + другое тело → 201 + новая версия (находка F-D4C5, RED) | **ЧАСТИЧНО** |
| 12 | UI: «TDD … 15/15 workspace + 4/4 entry»; «полный jest 2296/2297» | **ОПРОВЕРГНУТО.** Файлы `doclog4_document_workspace.test.tsx` / `doclog4_document_entry.test.tsx` отсутствуют в коммите и дереве; Jest на поставке **2278 тестов** (= прежний базлайн 205 сюит, не 2297); из UI-тестов только +1 тест бейджа в ModuleNav.test.tsx. UI-приёмка §12.1–12.3/AC17 (keyboard/theme/responsive/negative states) тестами не покрыта (находка F-D4C4) | **ОПРОВЕРГНУТО** |
| 13 | Регресс исполнителя: «tests/api 10F/2486P vs ЧИСТАЯ БАЗА 52315ac — FAILED-ID байт-идентичны» | Методологическая ошибка базы: родитель поставки — **1178288** (DOCLOG-3-FIX), а не 52315ac. Сравнение с до-FIX базой маскирует откат гвардов (находка F-D4C1) | **ОПРОВЕРГНУТО (методика)** |
| 14 | «doclog0+1+2+3+4: 318/318; 2 оракула DOCLOG-3 обновлены ПО ПЛАНУ» | Обновление 2 статических оракулов (+11 строк: /v1/documentation плановая, каталог 10/62) — действительно по плану; НО тем же коммитом молча удалены 15 гвардов DOCLOG-3-FIX (см. F-D4C1) | ЧАСТИЧНО |
| 15 | Сборка: «183 маршрута (8 новых /v1/documentation/*)» | OpenAPI: 179 путей / 188 операций; документационных путей 8 (9 операций: GET+POST на runs/{run_id}/documents); «183» — нем воспроизводимая методика (как в R-N3 акта DOCLOG-3-CERT); инвариант «8 новых путей» подтверждён | ПОДТВЕРЖДЕНО (по OpenAPI) |

**Учётное R-N1:** контракт-док §4 «~70 оракулов» — в repo-сюите фактически 48 (68 заявленных = 48 + 19 несуществующих UI-тестов + 1 ModuleNav).

## 2. Оракулы на СВОИХ данных — 61 (57 green + 4 RED-доказательства)

Корпус дизъюнктен repo (`RUN-D4A*`/`d4-*`) и корпусам прошлых сертификаций: `RUN-D4C00001/2/9/404`, сессии `d4cert-alpha/beta/omega`, админ-ключ `d4c-cert-admin-key-04`, сентинелы свои (`<script>d4c-xss-77</script>`, `javascript:d4c-scheme-77`, `Утверждение корпуса D4C…`), data-root `d4c-data`.

- **unit (26):** каталог P0/медиа-типы/честные тяжёлые форматы; render_json (канонические байты, детерминизм, чистота); render_jsonl (envelope-поля, **порядок и текст строго по frozen-снимку на многосекционных данных**, пустой снимок); render_markdown (честные unknown/partial/gaps, approval=null DOCLOG-6); render_html (сентинелы не исполняются, on*/схемы нейтрализованы, внешних ссылок нет по построению, gaps-блок, детерминизм); render_csv (строка на claim, нейтрализация =,+,-,@ только текста, минус-числа не текст, control-chars, ISO-даты); filename_for (traversal/мусор); статика миграции (10 файлов, 62 statement, паритет, DDL/UNIQUE, без DROP/ALTER научных таблиц).
- **API (31):** auth-матрица на всех маршрутах (owner green / foreign uniform-404 / anonymous / admin / неизвестные ID / невалидная форма ID); N3-гейт; AC05-tripwire (list/preview/rendition/content не меняют фингерпринт, отказы тоже); идемпотентность (та же format → тот же job/rendition, другая format → отдельная; draft reuse/refresh; конфликт ключа на builder-пути); job-контракт (ready с integrity, 400 unsupported_format без job, failed при ошибке рендера без науки, integrity-гвард sha256); аудит (protected_viewed на preview, тройка download различима и упорядочена, human_read_confirmed отсутствует); wiring/health.
- **RED-доказательства (4) — кодируют спеку и обязаны падать на дефекте; на поставке 2caf08e ПАДАЮТ ВСЕ 4** (см. §6): F-D4C2 content/preview fail-closed, F-D4C3 ложный allowed, F-D4C5 409 на reuse-пути.

**GREEN ×2: 57/57** (5.08s / 5.23s). Протокол: `scripts/doclog4cert/protocols/recheck_final_protocol.json`.

## 3. RED на родителе 1178288 (git-worktree)

- **Статические/символьные факты 15/15 RED** (`protocols/red_parent_1178288.json`): document_renditions.py, document_jobs.py, routers/documentation.py, миграция 0010, repo-сюита, documentation.ts, DocumentationWorkspace.tsx, DocumentPreview.tsx, страница /documentation, контракт-док — отсутствуют; MIGRATION_STATEMENTS_0010, 0010_doclog4_documents, COMPONENT_DOCUMENTS, build_documents_health, include_router documentation — отсутствуют.
- **Оракульный корпус 61/61 RED** (11 failed + 50 errors — ImportError отсутствующего контура; repo-сюита: файл не найден).

## 4. Мутационная кампания — 16 боевых + 3 no-op-контроля, два канала

Каналы: REPO = `tests/api/test_doclog4_document_delivery.py` (48); ORACLE = 57 green-оракулов (RED-блок deselected). Восстановление git checkout байт-в-байт, **RESTORE-FAIL 0**.

**Итог (финальная самосогласованная перепроверка `recheck_final.py`): 10 DUAL-KILLED + 6 ORACLE-ONLY + 0 SURVIVED; контроли C01/C02/C03 ALIVE 3/3.**

- DUAL-KILLED (10): M01/M02 (HTML-безопасность AC16), M03 (CSV spreadsheet-safe), M05 (JSONL schema_version), M08 (идемпотентность выдачи), M12 (сервисная авторизация R09), M13 (uniform-404→403), M14 (тройка теряет finished), M15 (preview без protected_viewed), M16 (N3-гейт — утечка manifest).
- ORACLE-ONLY (6): M04 (CSV числа через текстовый профиль), M06 (порядок секций JSONL), M07 (filename точка → traversal), M09 (integrity-гвард sha256), M10 (cancel переписывает ready), M11 (пустой байтовый рендер) — ловятся только оракулом сертификатора; кандидат на перенос в repo-сюиты (класс N1).
- Урок M06: первая волна дала SURVIVED на односекционных данных; усиление оракула (прямое сравнение порядка с frozen-снимком на ≥2 секциях) перевело мутанта в ORACLE-ONLY; repo-канал порядок секций не пинует.

## 5. Регресс и сборка

- **Полный pytest tests/ на 2caf08e (восстановленная среда: statsmodels 0.15.0, pandera/psycopg/prophet/arch/sqlalchemy/duckdb/syrupy): 4611 passed / 40 failed / 66 skipped** (474s).
- **Полный pytest tests/ на родителе 1178288 (тот же worktree/среда): 4578 passed / 40 failed / 66 skipped** (467s).
- **Дельта-0 доказана побайтно:** множества 40 FAILED-ID **ИДЕНТИЧНЫ** (`protocols/regress_failed_ids_target.txt` ≡ `regress_failed_ids_parent.txt`, diff пуст). Прирост passed **+33 = 48 новых (doclog4 repo-сюита) − 15 удалённых гвардов DOCLOG-3-FIX** — арифметика независимо подтверждает находку F-D4C1.
- Классы 40 падений средовые, предсуществующие: 14 × MNS-SPEC-PATH, 7 × progress_audit_5b (psycopg-DSN), 10 × neural/modeling-каталог, 9 × structural_breaks/profile_detail (дрейф пересобранной среды — класс отсутствует в документированной базе 31F эпохи DOCLOG-2/3, НО идентичен на родителе → не является регрессом поставки).
- Jest на поставке: **205 сюит / 2278 тестов: 2277 passed / 1 failed** (TsAnalysisUpload «чистая загрузка» — предсуществующий флак таймингов; в изоляции 46/46 GREEN; подтверждён исполнителем на stash-дереве). **2278 = прежний базлайн → UI-тесты поставки в дереве отсутствуют (F-D4C4).**
- Сборка: `apps.api.main` импортируется; OpenAPI **179 путей** (171 родитель + 8 документационных; 9 операций); каталог миграций **10 файлов / 62 statement**; P0-каталог {csv,html,json,jsonl,md}; AUDIT_ACTIONS=20 (9 mandatory).

## 6. Находки и вердикт

- **F-D4C1 (БЛОКЕР — регресс сертифицированной поставки):** коммит 2caf08e откатывает гварды DOCLOG-3-FIX: из `tests/api/test_doclog3_telemetry_audit.py` удалено **15 тестов** — класс `TestPostgresMirrorTelemetryAudit` целиком (`_MirrorFakeCursor/_MirrorFakeConnection`, pgm01–pgm11) и 3 теста `TestMainAppWiring` (middleware-слоистость CORS-внешний, preflight без X-Request-ID, простой OPTIONS с request-id). `git diff 1178288 2caf08e` = −568/+11; 93→78 тестов; нигде в дереве не восстановлены. Причина — устаревшая база исполнителя (52315ac, до DOCLOG-3-FIX) и регресс против не-родительской базы. Урок F-D2C1 (PG-зеркала обязаны жить в repo-сюитах) временно обнулён.
- **F-D4C2 (БЛОКЕР — AC11/§14.1):** защищённая выдача fail-open: все 4 обязательных audit-действия записываются `record_standard`; при отказе audit-sink байты рендиции и preview защищённого документа отдаются (200). RED ×2 (`test_red_fd4c2_content/preview_fail_closed_on_sink_failure`). Контракт-док декларирует отклонение как «AC11-инвариант» — инверсия требования спеки; сертифицированная машина `record_mandatory`/`MandatoryAuditFailure` в контуре выдачи не используется.
- **F-D4C3 (БЛОКЕР — §14.1):** ложный audit-факт: `download_requested` с decision=«allowed» фиксируется ДО объектной авторизации; при отказе чужому субъекту durable audit сохраняет недостоверный факт доступа. RED (`test_red_fd4c3_no_false_allowed_on_denied_download`).
- **F-D4C4 (БЛОКЕР поставки/честность заявлений):** заявленные UI-оракулы (15/15 workspace + 4/4 entry, jest 2296/2297) отсутствуют в поставке; Jest-базлайн поставки 2278 (= без прироста); приёмка §12.1–12.3 (keyboard/theme/responsive/negative states/AC17) не покрыта тестами. UI-компоненты (DocumentationWorkspace/DocumentPreview/page) поставлены кодом, но их контракт не верифицирован.
- **F-D4C5 (СЕРЬЁЗНОЕ — AC09):** reuse-путь черновика (refresh=false) игнорирует idempotency_key: тот же ключ с другим телом → 201 + новая версия документа вместо 409. RED (`test_red_fd4c5_...`). Builder-путь защищён корректно.
- **N1 (непокрытие repo-канала, кандидат на пин):** 6 ORACLE-ONLY мутантов (M04/M06/M07/M09/M10/M11) убиты только оракулом сертификатора; рекомендация переноса пинов в repo-сюиты (прецедент N1/N6 DOCLOG-3-CERT и F-D2C1).
- **N2 (учётное, среда):** база FAILED в пересобранной среде 40 (в эпохе DOCLOG-2/3 документировано 31); прирост класса structural_breaks/profile_detail — дрейф среды (идентичен на родителе и таргете, дельта-0 сохранён).
- **N3 (учётное, методика):** эволюция вердикта M06 SURVIVED→ORACLE-ONLY показала: мутационный корпус обязан использовать многосекционные данные для порядковых инвариантов; урок кодифицирован в оракуле.
- **R-N1 (учётное):** «~70 оракулов» контракт-дока = 48 repo + 19 несуществующих UI + 1 ModuleNav.
- **Положительное:** backend-поставка сильная и в основном честная — 57/57 green-оракулов ×2, 48/48 repo, 10 DUAL + 6 ORACLE-ONLY + 0 SURVIVED, контроли 3/3, RESTORE-FAIL 0, RED на родителе 15/15 + 61/61, дельта-0 побайтно, N3-гейт и AC05/AC06/AC16 подтверждены, HTML/CSV-безопасность двухслойная.

## 7. ВЕРДИКТ

**НЕ СЕРТИФИЦИРОВАНО.** Критерий завершения DOCLOG-4 (§19: «read/preview не меняют science state; keyboard/theme/responsive и negative states») не выполним на поставке: (а) three blocker-находки контура выдачи — fail-open обязательного аудита (F-D4C2), ложный audit-факт до авторизации (F-D4C3), регресс сертифицированных гвардов DOCLOG-3-FIX (F-D4C1); (б) UI-половина задачи не покрыта тестами вопреки прямым заявлениям поставки (F-D4C4); (в) AC09 нарушен на reuse-пути (F-D4C5). Backend-часть (рендеры/реестр/jobs/роутер за вычетом аудита выдачи и idempotency-409) подтверждена полностью. Продуктовый код аудитом не менялся (RESTORE-FAIL 0; дерево чистое, только неотслеживаемые артефакты сертификации).

**План DOCLOG-4-FIX (кандидат):** (1) вернуть 15 гвардов DOCLOG-3-FIX (git restore тестового файла из 1178288 + сохранить плановые +11 обновлений); (2) перевести 4 audit-действия выдачи на `record_mandatory` fail-closed ДО раскрытия, решение записи — фактическое (F-D4C2/F-D4C3); (3) 409 на reuse-пути при другом теле с тем же ключом (F-D4C5); (4) поставить заявленные UI-оракулы (F-D4C4); (5) перенос 6 ORACLE-ONLY пинов (N1); пересертификация.

Акт: `docs/cert_doclog4_2026-10-23.md`. Артефакты: `scripts/doclog4cert/` (conftest.py, test_doclog4cert_oracle_unit.py, test_doclog4cert_oracle_api.py, mutations.py, mutations_recheck.py, recheck_final.py, m06_adjudication.py, red_parent.py, protocols/). Запись в `worklog/worklog10.md`. Без commit/push (AGENTS.md). Манифест sha256 не ведётся и не используется (указание тимлида).
