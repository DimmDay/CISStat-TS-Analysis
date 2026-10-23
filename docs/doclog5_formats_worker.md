# DOCLOG-5 — форматы и worker: PDF с кириллицей, XLSX/Parquet/ChartSpec SVG/PNG, evidence ZIP, лимиты и retries

Задача spec_documentation_logging.md §19, строка DOCLOG-5.
База: main@2caf08e (DOCLOG-0/1/2/3 + сертификаты + DOCLOG-3-FIX + DOCLOG-4 включены).
Зависимости 1–4 выполнены. Критерий завершения §19: «все rendition имеют один
snapshot hash, render crash не теряет результат».

## 1. Граница поставки

Реализуются 6 тяжёлых форматов §7 (очередь P1) поверх frozen ReportSnapshot
DOCLOG-2 и асинхронный рендер-контур (§11/§18): PDF с кириллицей и встроенным
шрифтом, XLSX с листами Summary/Metadata/Results/Methods/Warnings, Parquet с
typed-таблицей claims, ChartSpec SVG/PNG (детерминированная проекция снимка,
фиксированная светлая print-тема), evidence ZIP с manifest/checksums. Форматы
P0 (json/jsonl/md/html/csv) и их синхронный путь НЕ меняются (регресс-пин).
Продуктовые файлы вне документа/worker/миграции/роутера/health не изменяются.

## 2. Ключевые решения (по §7/§11/§12.3/§17/§18/§19.1/§20)

| # | Решение | Обоснование (spec) |
|---|---|---|
| D1 | Рендеры тяжёлых форматов — ЧИСТЫЕ функции от снимка (`document_renditions.render_snapshot_{pdf,xlsx,parquet,svg,png,zip}`), диспетчер `_render_snapshot_by_format` расширяется без изменения механики | R06: MD/HTML/PDF/DOCX/XLSX строятся из одного снимка; AC05: рендер не трогает науку |
| D2 | Тяжёлые форматы НЕ рендерятся синхронно в POST: сервис создаёт job `queued` (202, status_url), рендер выполняет in-process worker `document_render_worker.py` | §18: тяжёлый PDF не создаётся синхронно; §11: queued → rendering → ready |
| D3 | Worker: batch-лимит цикла, per-tenant concurrency, soft render-timeout (daemon-поток + join), lease (claimed_at/lease_expires_at) с реклеймом просроченных, bounded retries (MAX_JOB_ATTEMPTS) | §18: per-tenant concurrency/quota, backpressure, timeouts, отмена; AC08/AC09 |
| D4 | Rendition регистрируется ТОЛЬКО после stage+commit байтов в object store; job помечается ready последним шагом. Crash на любом шаге → job остаётся queued/rendering/failed, «broken ready refs» невозможны по построению | AC08: «либо валидный ready файл, либо явное pending/failed» |
| D5 | Просроченный lease (crash воркера) → честный реклейм в queued (attempt не растёт — научная операция не повторяется: рендер из frozen снимка не является научной операцией) | AC08: retry не повторяет научную операцию |
| D6 | Дубликат запроса при активном (queued/rendering) job → возврат ТОГО ЖЕ job (без нового задания); после MAX_JOB_ATTEMPTS неудач → 429 retry_limit_exceeded; превышение tenant-очереди → 429 quota_exceeded | AC09: worker lease expiry и повтор не делают две версии; §18 backpressure |
| D7 | Все rendition несут `snapshot_payload_sha256` из registry-метаданных снимка (единый snapshot hash для всех форматов одной ревизии) + snapshot_id | Критерий завершения §19: «все rendition имеют один snapshot hash» |
| D8 | PDF: ReportLab, встроенный TTF из allowlist-путей (DejaVuSans — кириллица), invariant-метаданные (детерминизм), без внешних URL/изображений/локальных файлов вне allowlist шрифтов | §7 PDF: кириллица/встроенные шрифты, номер версии/статус; §12.3/AC16 |
| D9 | XLSX: openpyxl, 5 листов Summary/Metadata/Results/Methods/Warnings; недоверенный текст — строки (data_type='s', формулоподобные «=…» не становятся формулами), управляющие символы убираются (IllegalCharacterError), честное усечение по пределам Excel (32767 симв./ячейка) | §7 XLSX; §7 абзац: «XLSX пишет недоверенный текст как строки, не формулы» |
| D10 | Parquet: pyarrow, typed-таблица claims (refs — list<string>, event_count/last_sequence — int64 nullable); ленивый импорт → честный render_dependency_unavailable при отсутствии движка | §7 Parquet + schema: typed-таблицы; §7: превышение лимитов не скрывается |
| D11 | ChartSpec: dataclass-проекция снимка (утверждения по секциям, refs), SVG — рукописный детерминированный XML (без script/xlink/external), PNG — PIL с тем же allowlist-шрифтом; фиксированная светлая print-тема | §7 SVG/PNG; §12.3/AC16: SVG script/external URL запрещены |
| D12 | Evidence ZIP: фиксированные имена членов (manifest.json, report.json, document.md, table_claims.csv, chart_claims.svg, table_schema.json), date_time фиксирован (детерминизм), manifest содержит sha256 каждого члена КРОМЕ самого манифеста (циклическое определение запрещено §13.3), data_included=false + reproducibility=limited | §7 ZIP; §7 абзац: ZIP без данных честно маркируется |
| D13 | Миграция 0011 аддитивная: document_renditions.snapshot_payload_sha256 (TEXT DEFAULT ''), document_jobs.tenant_id/claimed_at/lease_expires_at | §19: миграции аддитивные, reader раньше writer |
| D14 | Worker авто-старт в lifespan API (env CISSTAT_DOCUMENT_RENDER_WORKER_*, паритет DeliveryWorker AUDIT-6C), статус в /health/ops (peek-семантика, safe_error) | §18; паритет существующего worker-контракта |

## 3. Точки изменения (§19.1-дух)

| Файл | Изменение |
|---|---|
| `apps/api/document_renditions.py` | +6 форматов в RENDITION_FORMATS, HEAVY_RENDITION_FORMATS, ChartSpec, рендеры, claims_table_schema, RenderDependencyError, allowlist шрифтов |
| `apps/api/document_jobs.py` | поля записей (tenant_id/claimed_at/lease_expires_at/snapshot_payload_sha256), DocumentRetryLimitExceeded/DocumentQuotaExceeded, асинхронная ветка request_rendition, list_open_jobs (ABC/Memory/Postgres), tenant-квота/лимит попыток |
| `apps/api/document_render_worker.py` | НОВЫЙ: lease/лимиты/timeout/retries, singleton, status |
| `apps/api/routers/documentation.py` | маппинг 429 (retry_limit_exceeded/quota_exceeded) |
| `apps/api/research_runs.py` | MIGRATION_STATEMENTS_0011 + каталог (11 файлов) |
| `apps/api/main.py` | авто-старт/останов worker в lifespan + /health/ops |
| `apps/api/requirements.txt` | reportlab, pyarrow (openpyxl уже объявлен) |
| `tests/api/test_doclog4_document_delivery.py` | честная эволюция контракта: каталог P0+P1, unsupported → docx (P2, по-прежнему отсутствует), миграций 11 |

## 4. Критерии приёмки §20, проверяемые этой поставкой

- **AC03** (частично, форматы): один frozen снимок → совпадающие факты в 11 форматах (число claims в jsonl/csv/xlsx/parquet/zip совпадает), байты/hashes различны.
- **AC08**: fault-injection (register/commit crash) → failed без готовых битых refs; lease expiry → реклейм и готовый результат; timeout → failed render_timeout, не повреждённый файл.
- **AC09**: активный job → возврат того же задания; ready-дубль → прежний job/rendition (пин DOCLOG-4 сохраняется); лимит попыток честен.
- **AC16**: XLSX-формулы/переводы строк/кириллица, SVG без script/external, ZIP без path traversal, рендер без сети/произвольной ФС (allowlist шрифтов).
- **§18**: batch/per-tenant лимиты, backpressure (queued остаётся queued), timeout → failed, отмена (cancel готов/не трогает науку — пин DOCLOG-4).

Вне границы: PDF/A-валидатор и DOCX (§7 P2 — DOCLOG-9), реальный нагрузочный корпус AC20 (§18 числа — ориентиры, не измеряются), E2E UI (AC17 — UI-пин DOCLOG-4 остаётся).
