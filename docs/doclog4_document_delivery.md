# DOCLOG-4 — UI и MVP выдачи поверх снимков 2+3 (контрактный документ)

*Task DOCLOG-4, 2026-10-23. Спецификация-источник: `spec_documentation_logging.md`
(§7 «Форматы», §10.3 «Атомарность и доставка», §11 «Жизненный цикл» ось генерации,
§12 «UI для аналитика и читателя», §14.1 «Предмет аудита», §15 «Права», §17 «Проект
API», §18 «Пределы», §19 строка DOCLOG-4 и §19.1, §20 AC05/AC06/AC16/AC17).
База: main@52315ac (DOCLOG-0/1/2/3 + сертификаты 0/1/2/2-FIX/3 включены).
Поставка следует AGENTS.md (TDD RED→GREEN→регресс, без commit/push).*

## 1. Постановка и граница задачи

DOCLOG-4 — пятый срез эпика документирования/логирования (§19): **«Раздел
документов, stage entry points, HTML/MD/JSON/JSONL/существующие таблицы,
job states»**. Зависимость — **DOCLOG-2 + DOCLOG-3** (выполнены в 288fdde/
b530606, сертифицированы). Критерий завершения (§19, та же строка):
**read/preview не меняют science state; keyboard/theme/responsive и
negative states**.

Вне границы (по §19): PDF с кириллицей/XLSX/Parquet/ChartSpec SVG-PNG/
evidence ZIP (DOCLOG-5 — только их возврат 400 unsupported_format здесь),
approvals/publish/retract/D10/D11 (DOCLOG-6), admin logs UI/scope grants/
diagnostic bundle (DOCLOG-7), мониторинг D12 (DOCLOG-8). Первые HTTP-маршруты
эпика: §17 помечает их «предлагаемыми» — реализуются с префиксом
`/v1/documentation`, существующие пути (`/v1/progress/runs/{run_id}/report`,
CSV/JSON/PNG экспорты) не трогаются (§17.1).

Проблема: DOCLOG-2 создал замороженный ReportSnapshot, но у него нет ни
выдачи, ни UI — «наличие маршрута недостаточно» (§1 итог): без MVP выдачи
документы недоступны аналитику, а любые самодельные экспорты обошли бы
авторизацию/аудит/франкосты снимка. DOCLOG-4 закрывает MVP-путь «список →
версия → preview → формат → скачивание» строго поверх frozen snapshot
(R06: формат не источник истины; AC05: чтение не меняет науку).

## 2. Что реализовано (карта изменений)

| Файл | Состав |
|---|---|
| `apps/api/document_renditions.py` (НОВЫЙ) | Рендеры §7 P0 как ЧИСТЫЕ функции от ReportSnapshot (R06/AC05 — никакой науки): `render_snapshot_json` (канонические байты снимка), `render_snapshot_jsonl` (§7 «один event на строку» для claims: envelope schema_version/snapshot_id/section/claim/refs/validity/evidence_level), `render_snapshot_markdown` (человеческий текст с честными unknown/partial/gaps), `render_snapshot_html` (§12.3/AC16-безопасность: html.escape всего, статический inline CSS, БЕЗ script/external refs/on*-атрибутов; шапка/оглавление/секции/«Основание»), `render_snapshot_csv` (плоская таблица claims: quoting, ISO-даты, spreadsheet-safe нейтрализация `=`,`+`,`-`,`@` в ТЕКСТОВЫХ значениях, числа не превращаются в текст — §7); каталог `RENDITION_FORMATS` (format → media_type/extension/label); `filename_for(revision_id, format)` — безопасные Content-Disposition имена (§15.2) |
| `apps/api/document_jobs.py` (НОВЫЙ) | Слой документов поверх снимков (§9.1 адаптеры, §19.1 «новые модули», НИКАКОГО переписывания снимков): `DocumentRecord` (document_id `doc-`+hex32, run_id, kind_code, current_revision_id; UNIQUE(run_id, kind_code)), `DocumentRevisionRecord` (revision_id `drev-`+hex32, document_id, snapshot_id, version_no 1..n, UNIQUE(document_id, version_no), UNIQUE(snapshot_id)), `DocumentRenditionRecord` (rendition_id `drend-`+hex32, snapshot_id, format, redaction_profile, state ready\|failed, media_type, size_bytes, content_sha256, storage_key, job_id; UNIQUE(snapshot_id, format, redaction_profile)), `DocumentJobRecord` (job_id `djob-`+hex32, snapshot_id, rendition_id, format, redaction_profile, state queued\|rendering\|ready\|failed\|cancelled, error_code, attempt, created/updated_at) + `DocumentRegistry` ABC + Memory + Postgres (ленивый psycopg, миграция 0010 — паритет фабрик 0007/0008) + `DocumentDeliveryService`: authorize → ensure_document_revision (find-or-create document, append-only version_no) → ensure_rendition (idempotency §10.3/AC09: тот же snapshot+format+profile → существующая ready rendition, БЕЗ нового job и БЕЗ пересчёта; другое тело/неизвестный формат → 400-семантика) → job queued→rendering→ready (P0-форматы рендерятся инлайн-быстро, но состояние persisted честно); cancel идемпотентен (§17); ошибки рендера → failed + error_code, научный результат не тронут (§10.3 «повторяет только рендеринг») |
| `apps/api/routers/documentation.py` (НОВЫЙ) | §17 маршруты `/v1/documentation` — ПЕРВЫЕ HTTP-поверхности эпика; КАЖДЫЙ маршрут: резолв ресурса (document/revision/job/rendition → run) → `identity.authorize_run_access` (R09, одна объектная авторизация; знание ID НЕ право — T15; отказ uniform 404) → действие. GET /runs/{run_id}/documents (список документов+версий, kind/context-фильтры — §12.1 «отфильтрованный список»), POST /runs/{run_id}/documents {kind, idempotency_key?} (создать draft: build_snapshot kinds=[kind] → document/revision; 201/200-идемпотент; 409 SnapshotConflict/Idempotency; 503 durable-слой недоступен), GET /documents/{document_id}/revisions (история), GET /revisions/{revision_id} (metadata+manifest), GET /revisions/{revision_id}/preview (безопасный HTML inline; audit protected_document_viewed — standard; НЕ создаёт документ/рендеринг/науку §17), POST /revisions/{revision_id}/renditions {format} (202 job_id/status_url либо 200 существующей ready), GET /jobs/{job_id} (состояние §11 ось генерации; НЕ повторяет job), POST /jobs/{job_id}/cancel (идемпотентно, научные результаты остаются), GET /renditions/{rendition_id}/content (stream готового файла: media_type/размер, Content-Disposition inline; X-Content-Type-Options nosniff, Cache-Control private,no-store §15.2; audit-тройка download_requested→response_stream_started→response_stream_finished РАЗЛИЧАЕТСЯ §14.1; human_read_confirmed НЕ существует); N3-ГЕЙТ (акт DOCLOG-2-FIX): dependency refs отдаются ТОЛЬКО внутри авторизованного GET /revisions/{id} через get_snapshot-гейт — прямой dependency_refs без авторизации из маршрутов исключён |
| `apps/api/migrations/0010_doclog4_documents.sql` (НОВЫЙ) | `documents` + `document_revisions` + `document_renditions` + `document_jobs` (FK ON DELETE CASCADE на research_runs/report_snapshots — паритет 0007/0008; UNIQUE-ограничения идемпотентности; индексы run/document/snapshot/job); аддитивная, reader раньше writer |
| `apps/api/research_runs.py` (ОБНОВЛЁН) | `MIGRATION_STATEMENTS_0010` + запись в каталоге `MIGRATION_FILES` (10 файлов; паритет файл↔каталог страхуется тестами — паттерн 0007/0008/0009); `run_migrations` применяет 0010 автоматически |
| `apps/api/storage_diagnostics.py` (ОБНОВЛЁН) | `COMPONENT_DOCUMENTS` в снимке фабрик; `build_documents_health()` — facts-only блок `/health/ops.documents` (backend реестра документов, факты конфигурации — БЕЗ путей/DSN; T6/T10 паритет ops.artifacts/snapshots/telemetry/audit) |
| `apps/api/main.py` (ОБНОВЛЁН) | `include_router(documentation.router, prefix="/v1/documentation")` — телеметрия-middleware уже оборачивает новые маршруты (X-Request-ID/сэмплинг GET — без изменений кода) |
| `packages/ui/lib/documentation.ts` (НОВЫЙ) | Типы контракта (DocumentSummary/RevisionSummary/JobState/RenditionMeta —(states §11/§12.3) + клиенты `documentationApiUrl`, `listDocuments`, `createDraft`, `listRevisions`, `getRevision`, `requestRendition`, `getJob`, `cancelJob`, `renditionContentUrl` — credentials: include, деградация к negative states без исключений UI |
| `packages/ui/components/DocumentationWorkspace.tsx` (НОВЫЙ) | §12.1-§12.2: три области desktop (этапы/виды 220–260px, версии 300–360px, preview — остальное; responsive-диапазоны, НЕ жёсткая сетка), на узком экране последовательные панели с возвратом и сохранённым выбором; шапка (исследование/target/ревизия-контекст/дата снимка/статус — неизвестное явно «—»); левые виды D01–D09 с числом документов/неполных версий; таблица версий (версия/дата/полнота/форматы/размер); переключатели представлений «Кратко/Методическое приложение/Основания» — ОДНА версия, не три документа; действия «Собрать формат» (выбор P0-формата; повторный клик — дедуп на бэкенде, job-поллинг, cancel); fullscreen preview; ВСЕ состояния §12.3 (empty/loading/queued/rendering/ready/partial/stale/unknown/failed/cancelled/forbidden/unavailable dependency; 409 → предложение перечитать; offline НЕ показывается как «нет документов» — отдельный недоступен-блок); role=status/alert, aria-current, семантические таблицы/заголовки, focus-visible, цвет НЕ единственный носитель статуса (текстовые метки), темы — общие токены (bg-neutral*/text-neutral*/brand — паттерн ProgressDrawer) |
| `packages/ui/components/DocumentPreview.tsx` (НОВЫЙ) | Preview-панель: sandboxed iframe (`sandbox=""` — без скриптов; srcDoc HTML §12.3 «HTML/SVG не исполняются»), метаданные (снимок/полнота/воспроизводимость/знание-версия), инспектор основания (раскрытие refs — §12.2 «внутренние ID по раскрытию»), честный список gaps (missing_refs — §12.3 «перечень gaps»), запрет защищённого preview при отказе — безопасная причина |
| `packages/ui/components/ModuleNav.tsx` (ОБНОВЛЁН) | §12.1 «Новый раздел доступен из общей оболочки»: бейдж «Документы» в MODULES → /documentation; открытие не меняет степпер и не создаёт документ фактом открытия |
| `packages/ui/components/ProgressDrawer.tsx` (ОБНОВЛЁН) | §12.1 «Из Прогресса — Открыть отчёт истории»: ссылка на /documentation?run={runId} в полосе запуска (только при trace.runId; onClose сохранён — переход закрывает панель по действующему паттерну ссылок панели) |
| `packages/ui/index.ts` (ОБНОВЛЁН) | Экспорт DocumentationWorkspace/DocumentPreview |
| `apps/standalone/app/documentation/page.tsx` (НОВЫЙ) | Страница раздела (Suspense-обёртка useSearchParams — паттерн /navigator; query run/kind — stage entry points глубокие ссылки) |
| `tests/api/test_doclog4_document_delivery.py` (НОВЫЙ) | Оракулы на СВОИХ данных (корпус дизъюнктен repo и 0/1/2/3: RUN-D4xxxxxx/d4-*): рендеры (JSONL-envelope/MD/HTML-безопасность сентинелами `<script>`/CSV spreadsheet-safe/числа-не-текст/ISO), реестр документов (Memory/PG-паритет, миграция-каталог, find-or-create/version_no), job-контракт (состояния/идемпотентность/cancel/failed), HTTP auth-матрица (владелец/чужой-uniform404/аноним/admin на ВСЕХ маршрутах — AC06), отсутствие пересчётов (AC05: diff durable state до/после list/preview/renditions/content + tripwire audit-факты), негативные форматы (400), 409-семантика, аудит-тройка download, health/documents, main-wiring (маршруты delta), миграция (паритет/DDL/UNIQUE/индексы/каталог 10) |
| `packages/ui/components/doclog4_document_workspace.test.tsx` (НОВЫЙ) | UI-оракулы: три области/ширины-классы, негативные состояния (§17 AC17: empty/loading/queued/rendering/ready/failed/forbidden/cancelled + 409 перечитать), kind-фильтр, preview sandbox-атрибут, role=status, keyboard (aria-current/focus), темы-токены, узкий экран (последовательные панели), fullscreen toggle |
| `packages/ui/components/doclog4_document_entry.test.tsx` (НОВЫЙ) | Точки входа §12.1: ModuleNav «Документы» бейдж+href; ProgressDrawer «Открыть отчёт истории» href=/documentation?run=… только при runId (и отсутствие без запуска) |

## 3. Ключевые проектные решения

1. **Документ/версия — АДАПТЕР над снимками, не новый источник истины**
   (§19 «reader раньше writer», §9.1). Полный Document/DocumentRevision
   реестр (тексты аналитика, манифесты ревизий, approvals) — DOCLOG-6;
   DOCLOG-4 вводит МИНИМУМ для выдачи: document=(run_id, kind_code)
   с find-or-create; revision = непerwрываемая ссылка на существующий
   snapshot (UNIQUE(snapshot_id)) с монотонным version_no. Снимок
   immutable (DOCLOG-2) — ревизии не переписываются, «пересборка =
   новая версия» наследуется от идемпотентности сборщика.

2. **Формат — производная, снимок — канон** (R06/AC03). Рендеры — чистые
   функции от ReportSnapshot: не читают живой run/сессию/артефакты,
   не запускают fit/query, не меняют stop status/target/ledger (AC05,
   страхуется diff-ом durable state и tripwire-оракулами). Байты форматов
   различны, факты совпадают (один источник).

3. **Job-контракт без worker-перевода** (§10.3/§17). Тяжёлые форматы —
   DOCLOG-5; P0-форматы рендерятся инлайн-быстро, но через persisted job
   (queued→rendering→ready/failed/cancelled + attempt/error_code): контракт
   UI стабилен для будущих тяжёлых форматов, отмена/повторы честны,
   «повторный клик не создаёт дубли» — UNIQUE(snapshot_id, format,
   redaction_profile) + возврат существующей ready rendition БЕЗ нового job.

4. **Одна объектная авторизация на каждом маршруте** (R09/T15/N3).
   Роутер резолвит document/revision/job/rendition → run_id и проходит
   решающую таблицу DOCLOG-0; отказ — uniform 404 (существование не
   дисклоужается), причина — в audit-потоке. N3-находка акта DOCLOG-2-FIX
   закрыта архитектурно: dependency manifest выдаётся только внутри
   авторизованного GET /revisions/{id}; прямого ungated доступа к
   dependency_refs в HTTP-контуре нет (постановка задаокументирована,
   оракул страхует отсутствие других утечек refs).

5. **Аудит выдачи — тройка download РАЗЛИЧАЕТСЯ** (§14.1):
   download_requested (запрос) → response_stream_started (начало отдачи) →
   response_stream_finished (завершение); human_read_confirmed НЕ вводится
   (сервер не удостоверяет сохранение на диск). protected_document_viewed
   на preview (private-классификация пилота). Все записи — standard-класс
   (AC11-инвариант: сбой аудита не ломает выдачу; счётчики/degraded видны),
   состав — через build_audit_record (redaction R08 наследуется).

6. **HTML-безопасность по умолчанию** (§12.3/AC16): содержимое снимка —
   недоверенный вход; рендер экранирует всё (html.escape), CSS —
   статический inline, скрипты/внешние ссылки/on*-атрибуты отсутствуют
   по построению; UI дополнительно изолирует preview в sandboxed iframe
   (sandbox="" — без same-origin/scripts). Печатный профиль — фиксированный
   светлый (тема не меняет рендер формата).

7. **Существующие таблицы не переписываются** (§17.1): существующие
   CSV/JSON/PNG экспорты и `/v1/progress/.../report` продолжают работать;
   CSV в новом контуре — плоская таблица claims снимка с spreadsheet-safe
   профилем (§7): строки с префиксом `=`,`+`,`-`,`@` и управляющими
   символами нейтрализуются АПОСТРОФОМ только для текстовых значений,
   отрицательные числа остаются числами; quoting/ISO-даты.

8. **UI поверх общих токенов** (§12.1/§12.3): layout-области — flex с
   ограничениями ширины (responsive-диапазоны), узкий экран —
   последовательные панели; состояния §12.3 покрыты ВСЕ (включая offline —
   отдельный блок «сервис недоступен», не путается с «нет документов»);
   role=status (live region) для смен состояний, role=alert для отказов;
   клавиатура — кнопки/ссылки со focus-visible, aria-current на выбранном;
   цвет — не единственный носитель (текстовые метки статусов).

## 4. Верификация

- RED→GREEN: `tests/api/test_doclog4_document_delivery.py` (~70 оракулов);
  UI: `doclog4_document_workspace.test.tsx` + `doclog4_document_entry.test.tsx`.
- Регресс: адресные сюиты doclog0/1/2/3 + research_runs + session_store +
  run_report + admin/progress (проверка отсутствия побочных эффектов) +
  полный pytest дельта против базы 52315ac; Jest: полный прогон UI-сюиты.
- Сборка: импорт `apps.api.main` (FastAPI маршруты delta +N), каталог
  миграций 10 файлов, `next build`-эквивалент не требуется (страница
  addитивна; typecheck/jest покрывают), tsc через jest-ts-jest (strict).
- AC-карта: AC05 (tripwire diff state), AC06 (auth-матрица 6 маршрутов),
  AC09 (идемпотентность rendition/job), AC16 (HTML/CSV сентинелы),
  AC17 (негативные состояния UI+API). AC01–AC04/AC08 — база DOCLOG-1/2;
  AC10/AC11 — база DOCLOG-3 (повторно не дублируются).

## 5. Честные границы

- Тяжёлые форматы (PDF/XLSX/Parquet/SVG-PNG/ZIP), внешний render worker,
  per-tenant quotas/backpressure — DOCLOG-5 (POST renditions на них
  отвечает 400 unsupported_format честно).
- Approvals/publish/retract — DOCLOG-6 (поле approval схемы снимка
  остаётся null; UI статуса согласования показывает «—»).
- Admin-журналы/гранты/diagnostic bundle — DOCLOG-7 (audit-записи уже
  пишутся durable-слоем DOCLOG-3, чтение — там).
- signed URLs, Range/resume, CDN-кэш — §15.2 остаётся на streaming через
  API (MVP), проверка лимитов proxy — деплой-контур.
- Отображение «история изменений» (diff facts/params/comments §12.2) —
  сводится к перечню версий с их cutoff/полнотой; diff-эндпоинт §17 —
  DOCLOG-5/6 (не заявлен MVP).
- PG-прогон миграции 0010 — при следующем durable-срезе (AUDIT-6A
  прецедент 0007–0009).
