# Акт независимой сертификации DOCLOG-7 (2026-10-24)

**Task ID:** DOCLOG-7-CERT. **Цель сертификации:** поставка DOCLOG-7
«Журналы и поддержка» (upstream **3634052** — коммит DOCLOG-7, HEAD
origin/main; клон по прямому указанию тимлида; в комплекте DOCLOG-6-CERT
c9b87a1 и DOCLOG-6-CERT-FIX 6d50550). **Метод:** «оракулы на своих
данных, мутанты на своих мутантах» (методология DOCLOG-3/4/5/6-CERT).
Манифест sha256 не ведётся и не используется (указание тимлида,
прецедент DOCLOG-2-FIX…6). Продуктовый код аудитом НЕ менялся: md5 всех
семи затронутых файлов до/после кампании байт-идентичен HEAD
(admin_logs.py, routers/logs.py, document_jobs.py, security_audit.py,
telemetry.py, main.py, research_runs.py); `git status` по продуктовой
части пуст; untracked — `scripts/doclog7cert/` (корпус) и этот акт.

## 1. Корпус сертификатора (оракулы на своих данных)

Namespace дизъюнктен repo-корпусам DOCLOG-0..7 (RUN-D7xxxxxx, d7-*,
tenant-d7*, subj-d7*) и корпусам предыдущих сертификаторов (d6cert-* и
др.): **RUN-D7C\*, d7c-\*, d7grant-d7cert-\*, tenant-d7cert-\*,
subj-d7c\***, шесть СВОИХ API-ключей 6-сегментного формата реестра
(admin / без-scope / logs.read+audit.read+logs.export / только
logs.read / только support.grant у НЕ-админа / чужой tenant). Данные —
СВОИ: telemetry/audit-записи прямой посадки (штатные
telemetry.emit/build_audit_record+sink), собственные цепочки
document→revision→rendition→job (D02, готовые и failed), собственные
support grants (tenant-wide и run-scoped), свой AC10-сентинел в env
(CISSTAT_D7C_SECRET_SENTINEL).

**Итог: 73 GREEN (unit 26 + API 35 + static 12) на 3634052**, финальный
прогон ×2 (3.58 s / 3.46 s) — `scripts/doclog7cert/` (conftest.py,
test_d7cert_oracle_unit.py, test_d7cert_oracle_api.py,
test_d7cert_oracle_static.py).

- **Unit (26), u01–u26**: fail-closed валидация грантов (ticket/subject/
  tenant, subj-вне-hex — отказ; **data/publish-права в whitelist грантов
  запрещены** — artifact.data.read/documentation.publish/policy.admin/
  logs.admin; TTL (0,168], 168 легитимен, «24»-строка легитимна);
  НАХОДКА-пины: **F2** (NaN TTL проходит диапазон и взрывается в
  timedelta — API 500), **F1** (purpose не обязателен, грант без цели
  создаётся); _is_expired fail-closed (мусорная дата = истёкший);
  эффективный доступ (§15.1): ADMIN → полный каталог+grants_management,
  без роли/scope — нули, карта scopes→потоки (logs.read→telemetry+
  delivery, audit.read→audit, logs.export→export, support.grant→
  менеджмент), гранты дают ОБЪЕДИНЕНИЕ границ tenant/run с исключением
  истёкших/отозванных/невалидных; cursor roundtrip base64url + отказ на
  «{}»/не-base64/списке; parse_query (дефолт 24ч, from>=to, окно ровно
  31д ок / 31д+1с отказ, лимиты 1..200, «7»-строка ок, N-пин: float
  1.5 тихо int-обрезается); whitelist-каталоги фильтров трёх потоков;
  retention (30/365/delivery=None, note только при заходе за горизонт);
  сужение (§19): scoped-режим отбрасывает чужой/пустой/отсутствующий
  tenant — fail-closed, run-граница, tenant-wide без run-границыы;
  явный фильтр вне границы — LogsAccessDenied (403-семантика), при
  tenant-wide run-фильтр НЕ классифицируется (N-D7C1); Memory-реестр
  (subject-фильтр, hide-revoked, порядок (created_at, grant_id) DESC,
  переполнение → LogsBackendError, копии без алиасинга, update
  неизвестного → GrantNotFoundError); bundle на СВОИХ данных (члены
  manifest+telemetry.jsonl, **date_time всех членов (2020,1,1)** —
  детерминизм двух сборок вне bundle_id/created_at, members_sha256 =
  hashlib, excluded == 5 категорий дословно, limits/retention/
  effective_scope честны); отказ без logs.export/неизвестный поток;
  _safe_ops не роняет пакет; **pg-хелперы без БД**: _pg_narrow строит
  «tenant_id IN (%s…)» с sorted-параметрами (unrestricted — нуль
  clauses), _pg_window «>= from, < to»; каталог GRANT_SCOPES frozen и
  без data-прав, константы контракта (168/31/200/2000/30/365/schema/
  prefix).
- **API (35), a01–a35**: 401 на всех 7 маршрутах без ключа и на
  неизвестном (+authn_denied с псевдонимом); 403 uniform {code:
  logs_access_denied, request_id} на каждом потоке/экспорте/грантах
  не-субъекту + **authz_denied в durable audit на каждый отказ** и
  отсутствие значения ключа в audit; /access честен (флаги по скоупам,
  unrestricted) и НЕ журналируется (решение зафиксировано); чтение
  telemetry: meta-пины (stream/order/effective_scope/limit/
  retention_horizon 30), свои 3 записи в порядке DESC с кириллицей;
  **саможурналирование ровно ОДНОЙ audit_log_accessed на операцию**
  (повторы → 2, чтение audit → 1 на чтение, без рекурсии); **сбой
  standard-audit не ломает чтение** (AC11-инвариант, ломучий sink →
  200); фильтры точных совпадений (severity INFO/ERROR, event_name,
  request_id, outcome, комбинации); честное дефолтное окно (сид −40ч
  невидим, явное окно видит); 422-каталог (окно >31д, from>=to, мусорная
  дата, лимит 201/0/«abc»); постраничный обход 5/2 без потерь и дублей,
  мусорный/«{}»-cursor → 422, курсор за пределами — пустая страница;
  retention-note честен (telemetry 30д, audit 400д-окно → 365, delivery
  без горизонта); скоуп реестра без гранта читает с meta «unrestricted»
  (пин N-D7C2); **грант сужает до tenant** (zeta-запись не выдана,
  meta {tenants, runs}, запись без tenant fail-closed); **явный фильтр
  вне гранта — 403, не пустой список** (tenant и run), внутри границы —
  200; tenant-wide: run-фильтр — сужение (пин N-D7C1); грант-жизненный
  цикл (до гранта 403 → 201 → 200 → отзыв → 403; «знание run_id не
  право» — чужой tenant 403); **истёкший грант — отказ** (прямая
  подмена expires в реестре); audit-поток: фильтры decision/action,
  самовидимость, N-D7C4; delivery: **ровно 15 ключей whitelist-
  проекции**, kind_code/document/revision/rendition join честен,
  НИКАКИХ content_bytes/payload, failed честен (error_code/attempt);
  гранты API: поля контракта (schema doclog.support_grant/1, префикс
  d7grant-, дедуп scopes, expires−created==TTL, created_by=subject
  админа), **grant_created mandatory-audit** (actor=subject, не ключ;
  policy_basis=ticket:…; grantee_subject в details); 422-каталог грантов
  (12 тел, включая artifact.data.read/documentation.publish — данные НЕ
  грантуются) + **пин F2 (NaN → 500)**; **mandatory fail-closed на
  создании** (ломучий sink → 503 audit_unavailable, **реестр ПУСТ**,
  восстановление → 201); **fail-closed на отзыве** (503, revoked_at
  остался None) + **идемпотентный повтор без второй grant_revoked
  записи** + uniform 404 grant_not_found; листинг include_revoked;
  support.grant у НЕ-админа управляет грантами, но потоки ему закрыты;
  пакет: AC10-сентинелы (СВОЙ env-секрет, все три ключа, postgres://,
  DATABASE_URL — НИЧЕГО из этого в байтах ZIP), члены ровно
  manifest+3×jsonl, delivery-члены без content/payload, manifest
  (schema, bundle_id==filename, excluded==5, counts, effective_scope,
  без значений DSN/env); **download-тройка + mandatory-запись** (по
  одной на экспорт, без рекурсии); **пин F3** (при 403 на экспорт
  mandatory «allowed» уже написана — находка); 422 пакет-каталог
  (неизвестный поток, окно >31д), подмножество потоков честно; пакет по
  гранту: весь каталог без audit.read → 403 (не частичный пакет),
  разрешённый поток — суженный пакет (zeta не в байтах, effective_scope
  честен); 503 logs_backend_unavailable uniform (postgres-бекенд без
  DSN); **AC05-tripwire**: чтение трёх потоков + экспорт не меняют
  состояние реестра доставки; экспорт без тела — все потоки/дефолт-окно;
  run-scoped грант сужает runs; **пин F4** (.jsonl-конкатенация) и
  **экспорт mandatory fail-closed** (ломучий sink → 503, ZIP не выдан).
- **Static (12), s01–s12**: миграция 0013 — файл↔каталог построчно,
  13 файлов/78 statement, ТОЛЬКО CREATE … IF NOT EXISTS (без
  DROP/DELETE/UPDATE/ALTER/TRUNCATE); DDL fail-closed-форма (tenant_id
  NOT NULL — глобальных грантов нет, expires_at NOT NULL, PK, без FK —
  намеренно, 3 индекса); **ровно 7 путей /v1/logs** с методами
  (GET access/telemetry/audit/delivery, POST export, GET+POST grants,
  POST revoke); каталог констант (GRANT_SCOPES frozen, 168/31/200/2000/
  30/365, schema/prefix/date_time); BUNDLE_EXCLUDED == 5 категорий
  дословно, иммутабельный tuple; whitelist-каталоги фильтров
  per-stream извлечением из сорца; **SQL-параметризация** (значения
  фильтров только через params, никогда не интерполируются; IN via
  placeholders+sorted); **list_recent audit/telemetry — статическая
  сверка SELECT-колонок с кортежем проекции** (kill-канал мутантов
  SELECT-списка), без «SELECT *», LIMIT %s; **build_diagnostic_bundle
  не читает env** (все os.environ — только в фабриках бекендов);
  uniform-ошибки роутера (код+request_id, nosniff/no-store/attachment,
  401 в _principal_or_401); структурный паритет Memory/Postgres
  (реестр грантов 4 метода без NotImplementedError, delivery-summary
  в обоих бекендах, _DELIVERY_SUMMARY_COLUMNS без content/payload);
  каталог AUDIT_ACTIONS == 21 без расширений, тройка grant_created/
  grant_revoked/audit_log_accessed и download-тройка из каталога.

## 2. RED на родителе

Корпус на родителе DOCLOG-7 **6d50550** через git-worktree:
**collection RED за 0.48 s** — `ImportError: cannot import name
'admin_logs' from 'apps.api'` (3 errors during collection; протокол
protocols/red_parent_summary.txt). Корпус не вакуумный: он тестирует
именно поверхность DOCLOG-7.

## 3. Мутационная кампания («мутанты на своих мутантах»)

Двухканальная схема: **REPO** = test_doclog7 + test_doclog3 +
test_doclog4 + test_doclog6 (231 тест — поверхность DOCLOG-7 +
фундаментальные пины telemetry/audit/delivery/каталогов); **ORACLE** =
корпус сертификатора (73). **38 боевых мутантов + 3 no-op контроля**
над 4 продуктовыми файлами (admin_logs.py, routers/logs.py,
document_jobs.py, security_audit.py).

**Итог: 23 DUAL-KILLED + 15 ORACLE-ONLY + 0 REPO-ONLY + 0 боевых
SURVIVED; контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0**
(protocols/mutations_summary.json, протоколы mut_\*.json с tails обоих
каналов). После кампании md5 всех четырёх файлов == HEAD побайтово.
Мета-валидация: **MV1** — dry-run 41/41 якорей (ровно одно вхождение);
**MV2** — классификатор сверен с синтетикой (self-test pass);
**MV3** — байт-в-байт восстановление после каждого мутанта (md5-сверка);
**MV4** — контроли C1–C3 (docstring/комментарии) ALIVE — каналы не
«косят» всё; **MV5** — скан хвостов всех киллов на посторонние файлы:
упомянуты ТОЛЬКО файлы каналов (repo: test_doclog7; oracle: unit/api/
static) — ложных киллов от средовых флаков нет (урок N2 DOCLOG-6-CERT).

**Классификация боевых мутантов:**

- **DUAL-KILLED (23):** M01 (admin-role bypass), M02 (гранты
  игнорируются), M04 (tenant-гейт 403 off), M06 (narrowing off), M07
  (whitelist грантов расширен data-правом), M08 (TTL верхняя граница
  off), M10 (отозванные гранты активны), M12 (отзыв не персистится),
  M13 (окно 31д off), M14 (лимит off), M17 (горизонты 30/365
  перепутаны), M19 (саможурналирование чтения off), M23 (download triple
  off), M24 (stream-finished off), M25 (окно экспорта всегда 422), M27
  (**пакет с полным доступом вне границ** — a29 по zeta-записи), M29
  (excluded-каталог опустошён), M30 (даты ZIP не фиксированы), M31
  (утечка content_bytes в delivery-проекции), M32 (state-фильтр
  delivery off), M34 (403→404), M35 (401→422), M36 (грант 404→403).
- **ORACLE-ONLY (15):** M03 (скоупы ключа игнорируются — репо не
  выдает scoped-ключи), M05 (run-гейт off — репо не тестирует
  run-scoped 403), M09 (fail-open невалидной даты — репо тестирует
  валидную прошлую дату, не мусорную), M11 (идемпотентность отзыва off
  — репо не отзывает дважды), M15 (whitelist _validate_filters off —
  через HTTP репо недостижимо: роутер собирает только whitelisted
  имена, N-D7C4), M16 (валидация ключей cursor off — репо-случай
  «%%%bad%%%» падает раньше, на base64), M18 (retention-note off), M20
  (standard→mandatory на чтении — репо не читает с ломучим sink), M21
  (authz_denied при отказе off), M22 (mandatory→standard на экспорте —
  репо не экспортирует с ломучим sink), M26 (export-scope check off —
  репо-субъект без всяких прав отсекается раньше стрим-гейтом; оракул
  a27 доходит с logs.read без logs.export), M28 (members_sha256
  пустышки), M33 (kind_code join off), M37 (pg-narrow clauses off —
  PG в песочнице нет), M38 (list_recent теряет actor_subject из SELECT
  — убит УСИЛЕННЫМ статическим оракулом s09: сверка SELECT-колонок с
  кортежем проекции; первичная версия s09 «колонка в сорце» мутанта не
  ловила — колонка остаётся в кортеже; слабость первого оракула
  исправлена в ходе кампании, протокол перепрогнан).

## 4. Регресс и сборка

- **Полный tests/api дельта-0:** цель **3634052+корпус** (продукт =
  3634052): **37F/2729P/42S** vs база 3634052 (git-worktree):
  **37F/2656P/42S** — **множества FAILED-ID байт-идентичны (37/37,
  diff пуст, протокол protocols/regress_delta0.json)**; +73 passed =
  ровно корпус сертификатора (включён в цель). Все 37F —
  предсуществующие средовые классы (psycopg-DSN progress_audit_5b/6c,
  forecasting-session, modeling/candidates, structural-breaks/profile,
  upload-db/duckdb, progress-panel) — идентичны на обеих сторонах.
- **Jest:** `adminLogs-dashboard` **9/9** (включая «ключ не попадает в
  localStorage/sessionStorage» — §15.1-оракул UI) и
  `doclog6-lifecycle-ui` **15/15** (протокол jest_adminlogs.txt).
- **Сборка:** import apps.api.main OK — **209 маршрутов** (ровно **7
  путей /v1/logs**), каталог **13 миграций / 78 statement**,
  AUDIT_ACTIONS=21, GRANT_SCOPES={audit.read, logs.export, logs.read},
  TTL_MAX=168, WINDOW=31, LIMIT=200, EXPORT=2000; **продуктовое дерево
  чистое** (md5 семи файлов == HEAD) — protocols/build_check.json,
  **BUILD: OK**.

## 5. Находки

- **F-D7C1 (низкая, контракт↔код; пин u05):** `purpose` гранта НЕ
  обязателен в коде (пустой/blank принимается), хотя контрактный
  документ docs/doclog7_logs_support.md требует «TTL ≤ 168h,
  ticket/purpose/tenant обязательны», и §14.2: «Поддержка получает
  ticket/purpose и ограничение по run/tenant/времени». Расхождение
  документ↔реализация; данных/прав не затрагивает. Рекомендация:
  либо добавить валидацию purpose в _validate, либо поправить
  контрактный документ (решение тимлида).
- **F-D7C2 (низкая, robustness; пины u04/a20):** `ttl_hours: NaN`
  проходит сравнения диапазона _validate (nan<=0 False, nan>168 False)
  и взрывается в `timedelta` уже после mandatory-audit → необработанный
  ValueError → **HTTP 500 вместо 422** (грант при этом не создаётся —
  fail-safe направление, но код ошибки нечестен; record_mandatory
  «allowed» остаётся). Смежно: JSON `true` тихо принимается как TTL=1ч.
  Рекомендация: `math.isfinite` + isinstance-фильтр в _validate.
- **F-D7C3 (низкая/средняя, точность audit; пин a27):** в POST
  /v1/logs/export обязательная запись `audit_log_accessed
  decision=allowed` пишется ДО build_diagnostic_bundle; если сборка
  затем отклонена (403: нет logs.export), в durable-аудите остаётся
  «allowed» для НЕсостоявшегося раскрытия (плюс standard authz_denied
  от _denied). Over-accounting с искажённым decision-полем; «все
  действия учитываются» не нарушается (учёт есть), но семантика
  allowed/denied врёт. Рекомендация: переносить mandatory-запись после
  успешной сборки ЛИБО писать mandatory «denied» на ветке отказа.
- **F-D7C4 (низкая/средняя, формат AC19; пин a34):** члены пакета
  `<stream>.jsonl` формируются как `"".join(to_jsonl(record)...)`, где
  `to_jsonl` не добавляет `"\n"` — при >1 записи все объекты склеены в
  ОДНУ строку: стандартный JSONL-ридер независимого получателя (AC19
  «открывается вне сессии») получает «Extra data». Данные полны
  (raw_decode читает все записи); sha256/counts честны. Рекомендация:
  `"\n".join(..., )` + завершающий `\n` (урок DOCLOG-5 о
  детерминизме не затрагивается).
- **F-D7C5 (низкая/средняя, паритет Memory/Postgres; пин a07):**
  memory-адаптеры чтения журналов (_memory_query_telemetry/
  _memory_query_audit) НЕ применяют whitelist-фильтры `run_id`/
  `tenant_id` (они применяются только в PG-пути через _pg_field_filters)
  — на дефолтном бекенде фильтр молча не сужает выборку. Нарушен
  структурный паритет Memory/Postgres (прямой урок F-D2C1); утечки НЕТ
  (сужение по гранту — отдельный механизм _narrow, обязательный в обоих
  бекендах; 403-гейты работают), но контракт фильтра не выполняется и
  списки Memory/PG на одинаковых данных разойдутся. Рекомендация:
  добавить _match_filters по run_id (research_run_id) и tenant_id в
  memory-адаптеры + пин в repo-сюиту.
- **N1 (дизайн-решение; пин a13/u18):** tenant-wide грант (run_id=None):
  явный run-фильтр вне границы НЕ классифицируется как 403 (граница run
  открыта) — честное сужение с раскрытием в meta.effective_scope.
  Непрозрачной маскировки нет; рекомендация: задокументировать в
  контракт-доке рядом с решением о /access.
- **N2 (наблюдение; пин a11):** скоуп реестра ключей (logs.read и др.)
  без гранта НЕ несёт tenant-границыы — такой ключ читает журналы
  платформенно-широко (meta честно «unrestricted»). Выдача скоупа =
  платформенное право; рекомендация: при выдаче скоупа ключу связывать
  его с tenant-границей ключа (реестр уже несёт tenant_id).
- **N3 (покрытие/учёт):** GET /v1/logs/grants (листинг грантов —
  metadata прав) НЕ журналируется; недокументированное исключение (для
  /access решение зафиксировано в контракт-доке). Кандидат: либо
  audit_log_accessed, либо явная фиксация решения.
- **N4 (косметика роутера):** get_log_access дважды вызывает
  _principal_or_401; в тройке download третья запись несёт
  policy_basis="details" (вместо "logs export policy"). На поведение
  не влияет.
- **N5 (крайний случай):** POST /v1/logs/grants не ловит
  LogsBackendError (переполнение MemorySupportGrantRegistry, maxsize
  10000) → 500. Fail-safe (грант не создаётся), но код не uniform.
- **N6 (внутренний контур):** PostgresAuditSink/TelemetrySink
  .list_recent не имеют верхней границы limit (HTTP-контур их не
  вызывает; whitelist-колонки; LIMIT %s параметризован). Рекомендация:
  clamp при следующем durable-срезе (AUDIT-6A).
- **N7 (наблюдение; пин a25):** обязательная самозапись экспорта
  (audit_log_accessed, resource_id=diagnostic_bundle) не попадает в
  СОБСТВЕННЫЙ пакет: to-граница окна фиксируется в parse_query до
  записи mandatory-записи. Учёт состоялся в durable-журнале и виден
  всем последующим чтениям/экспортам (a26) — рекурсии нет.
- **N8 (наблюдение; пины a07/a16/a18):** query-параметры вне collect-
  каталога роутера (например severity на audit-потоке) тихо
  игнорируются (200, без фильтрации), а не 422: whitelist применён
  составом collect-списка; _validate_filters остаётся внутренней
  защитой (unit-пин u15). Рекомендация: единое решение — либо 422 на
  неизвестные имена, либо явная фиксация «тихого игнорирования» в
  контракт-доке.

## 6. Вердикт

**СЕРТИФИЦИРОВАНО С НАХОДКАМИ (PASSED WITH FINDINGS).** Поверхность
DOCLOG-7: критерий завершения §19 — «нет данных/секретов вне grant,
все действия учитываются» — подтверждён двухканально:

- **«нет данных вне grant» (§19/§15.1):** доступ = ADMIN ∪ scopes ∪
  активные гранты (M01/M02/M03); данные вне границы tenant/run не
  выдаются ни списком (narrowing fail-closed, M06), ни явным фильтром
  (403-гейт, M04/M05), ни пакетом (M27 — мутант «пакет с полным
  доступом» убит по zeta-записи a29); истёкшие/отозванные гранты
  отключаются немедленно (M09/M10); data/publish-права через
  support-grant недостижимы (M07); delivery-поток — metadata-only
  (M31/M33); сужение раскрыто в meta.effective_scope.
- **«нет секретов» (AC10/AC19):** пакет НЕ содержит ключи/env/DSN
  (a25-сентинелы; s10 — builder не читает env); manifest с ЯВНЫМ
  перечнем исключений (M29); ошибка/отказ не дисклоужат значение
  ключа (a02, псевдоним субъекта).
- **«все действия учитываются» (§14.2/AC11):** ровно одна
  audit_log_accessed на чтение без рекурсии (a05, M19); сбой записи не
  ломает чтение (a06, M20 — инвариант); экспорт и гранты — mandatory
  fail-closed (a21/a22/a35, M22); отказы сами в audit (a02, M21);
  download-тройка (a26, M23/M24); грант-жизненный цикл append-only с
  идемпотентным отзывом (a22, M11/M12).
- **Контракт запроса (§14.2):** whitelist-фильтры (M15), окно ≤31д
  (M13), лимиты (M14), keyset-cursor fail-closed (M16), честный
  retention-horizon (M17/M18), uniform 401/403/404/422/503 (M34–M36,
  a30), детерминированный ZIP (M30) с members_sha256 (M28).

23/38 боевых мутантов DUAL-KILLED, 15 ORACLE-ONLY (репо-канал слабее
на негативных ветках — перенос пинов M05/M11/M21/M22/M26/M28 в repo-сюиту
= кандидат N-плана, прецедент N1 DOCLOG-6-CERT), 0 SURVIVED. Находки
F-D7C1–F-D7C5 — низкий/низкий-средний уровень, блокером не являются;
рекомендации сформулированы. Живой PostgreSQL-прогон 0013/list_recent —
за границей песочницы (честная граница поставки, паттерн AUDIT-6A);
паритет pg-контура закреплён статически (s01–s02/s08–s09, M37/M38).

**План DOCLOG-7-FIX (кандидат, по решению тимлида):** (1) F-D7C4 —
newline-разделители членов пакета; (2) F-D7C5 — run_id/tenant_id
фильтры в memory-адаптерах + repo-пин; (3) F-D7C3 — порядок mandatory-
записи экспорта; (4) F-D7C2 — isfinite-валидация TTL; (5) F-D7C1 —
purpose-валидация либо правка контракт-дока; (6) перенос ORACLE-ONLY
пинов в repo-сюиту. Для (2)/(4)/(5)/(6) пересертификация адресная, для
(1)/(3) — повторный прогон корпуса сертификатора.

Deliverable: ZIP cisstat-doclog7-cert.zip → открытый контейнер сессии
(download): scripts/doclog7cert/ (conftest, оракулы unit/api/static,
mutations.py, regress_delta0.py, build_check.py, protocols/ 47 файлов),
docs/cert_doclog7_2026-10-24.md (этот акт), worklog/worklog11.md
(запись). Без commit/push (AGENTS.md).
