# Акт независимой сертификации DOCLOG-5 (2026-10-23)

**Task ID:** DOCLOG-5-CERT. **Цель сертификации:** поставка DOCLOG-5 «Форматы и
worker» (upstream d5e0fc7, байт-идентично ZIP-поставке: git diff поставки против
upstream = 0 строк), аудит на базе **main@ebbfa87** (ebbfa87 = 2caf08e → d5e0fc7
[DOCLOG-5] → 02634cd [DOCLOG-4-UI-FIX, только UI] → ebbfa87 [DOCLOG-4-CERT, только
scripts/docs/worklog]; продуктовая поверхность DOCLOG-5 между d5e0fc7 и ebbfa87
не менялась — проверено diff'ом). **Метод:** «оракулы на своих данных, мутанты
на своих мутантах» (методология DOCLOG-3-CERT/4-CERT). Манифест sha256 не ведётся
и не используется (указание тимлида). Продуктовый код аудитом НЕ менялся.

## 1. Корпус сертификатора (оракулы на своих данных)

Namespace дизъюнктен repo и корпусам 0/1/2/2-FIX/3-CERT/4/4-CERT: **RUN-D5C*,
d5cert-*, d5c-cert-***, tenant `tenant-d5cert-b`. Данные — СВОИ: враждебный
frozen-снимок прямой конструкции (кириллица; формулоподобные «=1+2;
=HYPERLINK(…)»; управляющие символы \x00/\x07/\x0b; текст 40 000 символов;
заголовок-зонд с `<script>`; пустая секция; честные gaps; cutoff 42/1042).

**Итог: 74 GREEN (unit 39 + API 25 + static 10) + 1 RED-зонд находки** —
`scripts/doclog5cert/` (conftest.py, test_d5cert_oracle_unit.py,
test_d5cert_oracle_api.py, test_d5cert_oracle_static.py, probe_findings.py).

- **Unit (39)**, d5o01–d5o39: PDF (магия %PDF, встроенный allowlist-шрифт в
  байтах, /Title//Producer, детерминизм, честный RenderDependencyError без
  шрифтов, экранирование hostile-разметки); XLSX (ровно 5 листов, формулоподобное
  = строка data_type='s', strip управляющих символов, честное усечение ≤32767 с
  маркером + Warnings-truncation, число claims, cutoff остаётся int,
  детерминизм, без макросов); Parquet (typed-схема list<element: string>,
  int64-nullable сохраняется, rowcount, **значения элементов refs** — урок
  адъюдикации M27, детерминизм, честный ImportError→RenderDependencyError);
  SVG (well-formed XML, 0 script/xlink/javascript, единственный http — xmlns,
  экранирование hostile-КОДА секции, детерминизм, честная пустая серия,
  светлая тема 720px); PNG (подпись/IEND, PIL-размер 1440, детерминизм);
  evidence ZIP (ровно 6 членов, sha256 каждого члена в манифесте совпадает с
  фактическими байтами, манифест БЕЗ самохеша §13.3, фиксированная дата
  (1980,1,1), data_included=false + reproducibility=limited, без path
  traversal, report.json == канонические байты снимка); AC03 (facts-match
  через форматы, 11 hash'ей попарно различны, ChartSpec-series по своим
  данным, схема таблицы claims).
- **API (25)**, d5o40–d5o64: тяжёлый формат НЕ рендерится синхронно (сентинел
  dispatcher'а: 0 вызовов в POST, 202+queued+status_url); worker доводит до
  ready; **единый snapshot hash §19** (P0 csv и P1 svg одной ревизии ==
  payload_sha256 registry, ≠ ""); активный дубликат → тот же job (1 job на
  цель); ready-дубликат → прежний job/rendition без повторного рендера
  (сентинел = 0 вызовов); выдача 200 + integrity + чужой uniform 404;
  **AC08 fault-injection**: crash stage_bytes / commit_staged /
  register_rendition → job в ЯВНОМ rendering, rendition отсутствует (broken
  ready refs невозможны), после контролируемого lease-истечения — реклейм и
  дозавершение, **attempt не растёт**; реклейм просрочки → queued +
  error_code=lease_reclaimed + attempt сохранён + lease-поля очищены (шаг 1 с
  подавленным claim) и одно-цикловое восстановление до ready с тем же
  attempt; живой lease не крадётся и считается в per-tenant concurrency;
  timeout → requeue render_timeout attempt+1, **позднее завершение фонового
  потока НЕ создаёт rendition**; детерминированная ошибка → terminal failed
  сразу (attempt=1, requeued=0); пин TRANSIENT_ERROR_CODES; MAX_JOB_ATTEMPTS=5
  с честной границей (5-й POST разрешён, 6-й → DocumentRetryLimitExceeded) и
  HTTP-маппингом 429 code=retry_limit_exceeded; квота 10 открытых jobs/tenant →
  429 code=quota_exceeded, tenant B не затронут; **tamper-детект выдачи**
  (подмена content_sha256 → DocumentIntegrityError — адъюдикация M20); cancel
  queued → worker пропускает; cancel ready → no-op; health/ops worker-блок
  (авто-старт lifespan, конфиг); auth-матрица owner/foreign/anon/unknown;
  docx → 400 unsupported_format.
- **Static/PG-parity (10)**, d5pgm01–d5pgm10 (класс урока F-D2C1): миграция
  0011 только ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS (без
  UPDATE/DELETE/DROP), каталог 11 файлов/67 statement, паритет файл↔каталог;
  **колоночный паритет ридеров и INSERT** document_jobs/document_renditions
  (позиционное чтение psycopg честно; tenant_id/claimed_at/lease_expires_at и
  snapshot_payload_sha256 пишутся и читаются); UPSERT rendition переносит
  snapshot_payload_sha256; list_open_jobs фильтрует queued/rendering в обоих
  бекендах; load_snapshot_system переносит payload_sha256 и проверяет
  SnapshotIntegrityError.

## 2. RED на родителе

Корпус (на момент прогона 73 оракула) на родителе DOCLOG-5 **2caf08e** через
git-worktree: **73 errors / collection RED за 1.3 s** (ImportError
document_render_worker / HEAVY_RENDITION_FORMATS, отсутствие миграции 0011).
Корпус не вакуумный: он тестирует именно поверхность DOCLOG-5
(protocols/red_parent.json).

## 3. Мутационная кампания («мутанты на своих мутантах»)

Двухканальная схема: **REPO** = test_doclog5_formats_worker + test_doclog4_
document_delivery (82 теста); **ORACLE** = корпус сертификатора (74).
**27 боевых мутантов + 3 no-op контроля** над 4 продуктовыми файлами.

**Итог: 17 DUAL-KILLED + 3 REPO-ONLY + 6 ORACLE-ONLY + 1 SURVIVED(боевой);
контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0** (mutations_summary.json,
протоколы mut_*.json с tails обоих каналов).

Мета-валидация: **MV1** — каждый мутант применён ровно один раз по
уникальному якорю (счётчик patch_applies = 27/27 после правки якоря M27:
первая версия якоря встречала JSONL-рендер — честный PATCH-FAIL с последующим
перепроектированием); **MV2** — классификатор сверен с синтетикой (self-test
pass/pass=SURVIVED, fail/fail=DUAL, repo-only, oracle-only); **MV3** —
байт-в-байт восстановление дерева после каждого мутанта (RESTORE-FAIL 0);
**MV4** — контроли C1–C3 (docstring/комментарии) ALIVE — каналы не «косят»
всё.

**Адъюдикации (урок M06 прецедента 4-CERT):**
- **M20** (content-integrity off): SURVIVED в обеих волнах → корпус не
  tamper-тестил выдачу → добавлен оракул d5o64 → ORACLE-ONLY. Асимметрия с
  M11 (integrity loader'а — REPO-ONLY: repo тестирует loader, но не выдачу).
- **M27** (parquet refs строкой): SURVIVED → **pyarrow молча превращает str в
  список отдельных СИМВОЛОВ** (тип list<string> и rowcount сохраняются,
  данные искажаются!) → оракул d5o17 усилен значениями элементов →
  ORACLE-ONLY. Находка инструментария класса «тихая конверсия» — продукты
  DOCLOG-5 поведение не проявляют (рендер всегда list()).
- **M24**: первая редакция (ZipInfo без date_time) — **эквивалент** (дефолт
  ZipInfo = тот же (1980,1,1,0,0,0)); переопределён в M24_zip_fixed_date_
  changed → ORACLE-ONLY (пин фиксированной даты держит только оракул).
- **M19** (failed job не глотит готовую rendition): SURVIVED. Адъюдикация: в
  sequential-семантике не наблюдаем (ready-цель защищена ready-dup; existing
  в fail_render бывает только в состоянии failed). Наблюдаемость — только
  при конкурентной гонке двух jobs одной цели (память-реестр без CAS на
  постановке). Тема конкурентной модели — вне MVP (§18), кандидат в
  DOCLOG-6/worker-race hardening. Не является нарушением AC08 sequential.

**REPO-ONLY (3)**: M04 (batch+1), M06 (лишняя попытка перед terminal), M11
(integrity loader off) — repo-сюита сильнее оракула; оракульный корпус
заморожен после стабилизации (пины живут в repo — честная граница).

**ORACLE-ONLY (6)**: M03 (реклейм не чистит lease-поля), M08 (timeout вне
TRANSIENT), M20 (tamper-детект), M23 (SVG-экранирование кода), M24b (пин даты
ZIP), M27 (элементы refs) — **находка N1: эти 6 пинов существуют только в
корпусе сертификатора**; рекомендация — перенос в repo-сюиту (прецедент N1
3-CERT/N1 4-CERT).

## 4. Регресс и сборка

- **Полный tests/ ×2** в одной среде (восстановленный паритет: psycopg 3.3.6,
  sqlalchemy, duckdb, arch, pandera, PyWavelets — сессия стартовала на
  деградированной среде, прецедент DOCLOG-2-FIX): цель **ebbfa87+корпус**
  (продукт = ebbfa87) **103F/4606P/66S/3E** vs база **2caf08e** **103F/4545P/
  66S/3E** — **множества FAILED-ID байт-идентичны (103/103, diff пуст в обе
  стороны)**; +61 passed = ровно корпус repo-тестов DOCLOG-5. Все 103F+3E —
  средовые классы (unit-бд sqlalchemy/duckdb-DSN, upload_db, forecasting/
  garch/egarch sessions, modeling/neural) — идентичны на обеих сторонах.
- Сборка: import apps.api.main OK; **192 маршрута**; каталог **11 миграций /
  67 statement**; RENDITION_FORMATS=11 / HEAVY=6; MAX_JOB_ATTEMPTS=5,
  MAX_OPEN_JOBS_PER_TENANT=10, lease=120s; /health/ops.document_render_worker
  (enabled, interval=10, batch=4, per_tenant=2, timeout=60); **продуктовое
  дерево чистое** (git status по apps/packages/tests пуст) —
  protocols/build_check.json, **BUILD: OK**.

## 5. Находки

- **F-D5C1 (серьёзная, §17/§18 «отмена»):** cancel в окне, пока worker держит
  claimed-запись, **теряется**: `DocumentDeliveryService.complete_render`
  безусловно переводит job в READY (`replace_dataclass(job, state=JOB_READY)`
  без проверки текущего состояния; в _process используется устаревшая
  claimed-запись, повторного чтения нет). Пользователь, отменивший rendering-
  задание, получает готовый файл и rendition (RED-доказательство
  probe_findings.py::test_d5f01 — «complete_render перезаписал отмену
  (cancelled) в ready; rendition=True»; диагностическая фиксация факта —
  d5o60). Не теряет данные и не трогает науку; нарушает контракт отмены §18
  («workers имеют … отмену») и ожидание §17. Рекомендация DOCLOG-5-FIX:
  complete_render проверяет текущее состояние job (cancelled/failed → не
  перезаписывать; байты, полученные после отмены, либо отбрасывать, либо
  честно документировать «cancel не прерывает уже начатый рендер» решением
  тимлида).
- **N1 (покрытие, 6 ORACLE-ONLY):** пины M03/M08/M20/M23/M24b/M27 живут
  только в оракульном корпусе — перенос в repo-сюиту.
- **N2 (инструментарий):** pyarrow молча конвертирует str→list<char> в
  list<string>-поле (тихое искажение данных без ошибки) — оракулы typed-
  схем обязаны проверять ЗНАЧЕНИЯ элементов; урок зафиксирован в d5o17.
- **N3 (конкурентная модель):** двойная постановка одной цели возможна при
  гонке двух POST (память-реестр без CAS; active-dup последовательный);
  worker-side защита — живой lease (проверено M01 DUAL). Тема для
  DOCLOG-6/9 (нагрузочный корпус AC20), в MVP-границах поставки честно не
  заявлена — отмечена.
- **Базовые условия (наследие, вне скоупа DOCLOG-5-CERT):** F-D4C1 — на
  ebbfa87 отсутствуют 15 гвардов DOCLOG-3-FIX (TestPostgresMirrorTelemetry_
  Audit pgm01–pgm11 + 3 wiring; 93→78 тестов doclog3-файла — подтверждено
  grep) — план DOCLOG-4-FIX не исполнен upstream; F-D4C2/F-D4C3 (audit
  fail-open/download_requested до авторизации) продолжают действовать и
  распространяются на выдачу тяжёлых форматов (тот же маршрут
  GET /renditions/{id}/content). Вердикт DOCLOG-5 не выставляется до их
  исправления в рамках DOCLOG-4-FIX.

## 6. Вердикт

**СЕРТИФИЦИРОВАНО С НАХОДКАМИ (PASSED WITH FINDINGS).** Поверхность DOCLOG-5:
критерий завершения §19 подтверждён (единый snapshot hash у P0+P1 rendition —
d5o42/d5o41; render crash не теряет результат — fault-injection d5o46–d5o48,
broken ready refs отсутствуют по построению и по факту); AC03/AC08/AC09/AC16
и §18-пределы подтверждены двухканально; 17/27 DUAL-KILLED, 0 боевых
нарушений в sequential-семантике (M19 — только race-наблюдаемость). Вердикт
НЕ засчитывает базовые условия F-D4C1/C2/C3 (наследие DOCLOG-4-CERT) и
выдвигает F-D5C1 в план DOCLOG-5-FIX вместе с N1.

**План DOCLOG-5-FIX (кандидат):** (1) complete_render уважает отмену
(проверка текущего state перед ready-перезаписью + решение по байтам);
(2) перенос 6 ORACLE-ONLY пинов в repo-сюиту; (3) опционально — CAS/идемпо-
тентность двойной постановки (N3) по решению тимлида; пересертификация
затронутого контура.

Deliverable: ZIP cisstat-doclog5-cert.zip → открытый контейнер сессии:
scripts/doclog5cert/ (conftest, оракулы unit/api/static, probe_findings,
red_parent.py, mutations.py, regress_delta0.py, build_check.py, protocols/ 37
файлов), worklog/worklog10.md (запись). Без commit/push (AGENTS.md).
