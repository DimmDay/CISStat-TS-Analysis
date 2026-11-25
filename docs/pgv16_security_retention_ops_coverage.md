# PGV-16 — Security/retention/ops/coverage

**Дата:** 2026-11-25. **База:** fea4063 (origin/main). **Спецификация:** `spec_passport_graphics_visual.md` §11–§13 (строка PGV-16), AC17–AC20. **Правила:** `AGENTS.md` (TDD RED→GREEN, check_routes, без commit/push, без секретов с VM).

## 1. Постановка

Строка PGV-16 (§13): зависимости PGV-10/11/12/15 — реализованы и в релизе e2da22c на VM; **результат** — «Security/retention/ops/coverage»; **точки изменения** — `identity/audit/pins/health/registry`; **критерий** — «Foreign refs/SSRF denied, permission/holds/TTL/dependency failure честны».

Аудит контура (факты на fea4063) выявил пять честных разрывов между спекой и кодом:

| # | Разрыв | Факт |
|---|---|---|
| R1 | Audit выдачи нечестный и fail-open | `GET /renditions/{id}/content` пишет `download_requested` **до** авторизации с безусловным `allowed` (чужой получает «allowed» + 404); тройка `download_requested`/`stream_started`/`stream_finished` объявлена в `AUDIT_REQUIREMENTS` классом **mandatory**, а пишется через `record_standard` (best-effort) — spec §11 «Mandatory audit до защищённой выдачи» не выполняется. `protected_document_viewed` на preview — та же best-effort схема. |
| R2 | SSRF-префлайт API-слоя неполный (AC19) | `validate_screen_svg` ловит `<script>`/`foreignObject`/`on*`, но **не** ловит внешние ресурсы (`href`/`src`/`xlink:href` c `http(s)`/`file`/`blob`/`ftp`/`javascript`); санитайзер контейнера (второй слой) их удаляет с warnings, а Python-негативных оракулов нет вовсе — мутант, ослабивший оба слоя, не убивается ни одним тестом API-уровня. |
| R3 | Retention печатных PNG/ZIP отсутствует | `sweep_retention` итерирует только `DOCUMENT_KINDS` (D01–D12) и `list_renditions(snapshot_id)`; печатные renditions (`snapshot_id=""`, `print_revision_id`) и печатные документы V01/P01/P02 очисткой не покрываются — TTL §12 «Cleanup не ломает pins/holds/retention; источники и PNG могут иметь разные сроки» для PNG-стороны не существует. |
| R4 | `/health/ops` не классифицирует print-PNG | `render_dependencies_status()` матрица pdf/pdfa/png/parquet — Python-рендеры D-документов; состояние контейнера печати (browser/fonts/bundle/smoke, `/readyz`) в ops-snapshot не проецируется — spec §12 «Readiness отдельно проверяет browser/fonts/print bundle; Safe /health/ops классифицирует PNG отдельно от PDF» на API-уровне не выполняется. |
| R5 | Coverage-gate для CERT отсутствует | «Unknown site блокирует CERT» живёт только в jest-оракуле и doc-guard; Python-сторона не валидирует `config/visual_registry.json` (структура сайта/классы причин/существование файлов/непустые модули/паритет print-схемы), у твина нет `registry_version` — дрейф не обнаруживается гейтом. |

Границы: `routers/logs.py` (выдача логов) — отдельная поверхность, PGV-16 не затрагивает (фиксируется в §6); HTTP-роуты не добавляются и не меняются; DDL/миграции не требуются (печатные renditions/документы уже durable, 0016–0018).

## 2. Решение

### SEC-1 — честная mandatory-аудит-тройка выдачи (identity/audit)

`apps/api/routers/documentation.py`, два маршрута:

- **`GET /renditions/{rendition_id}/content`**: порядок становится authorize → decision → bytes:
  1. резолв rendition (несуществующий id — uniform 404, запись не пишется — честная экономия: ресурса нет, run-контекста нет);
  2. `service.read_rendition_content(...)` (повторная объектная авторизация внутри — defense in depth):
     - `DocumentAccessDenied` → `record_mandatory(download_requested, "denied")` → uniform 404;
     - `RenditionPurgedError` → `record_mandatory(download_requested, "denied", details={reason_code: purged_artifact})` → 410;
     - `DocumentIntegrityError` → `record_mandatory(download_requested, "aborted")` → 500 integrity_mismatch;
  3. успех → `record_mandatory(download_requested, "allowed")` → `record_mandatory(response_stream_started)` → `record_mandatory(response_stream_finished)` → Response (вся тройка ДО отдачи байт — AC11/spec §11).
- **`GET /revisions/{revision_id}/preview`**: `protected_document_viewed` — `record_mandatory` после успешной авторизации (решение `allowed` честно — уже внутри try), при отказе — `record_mandatory(..., "denied")` → uniform 404.

Сбой sink теперь роняет выдачу в `503 mandatory_audit_unavailable` (существующий маппинг `MandatoryAuditFailure`), байты не покидают сервис. Решения ограничены `DECISIONS = {allowed, denied, aborted}` (§14.1). Записи в `routers/logs.py` остаются best-effort (см. §6).

### SEC-2 — SSRF/external-resource префлайт (AC19)

`apps/api/visual_exports.py::validate_screen_svg` дополнительно запрещает внешние ссылки ресурсов: атрибуты `href`/`xlink:href`/`src` со схемами, кроме разрешённых — внутренние якоря `#…` и `data:` (паритет request-policy контейнера `buildRequestPolicy`: всё, кроме `data:`/`about:blank`, заблокировано). Нарушение — `InvalidScreenSvg` → 422 `invalid_screen_svg` (существующий маппинг). Легальные frozen-сериализации Recharts (внутренние якоря `clip-path`/`filter` ссылки) проходят — регресс-гвард в тестах.

### RET-1 — retention печатных renditions (pins/holds/TTL)

- **Реестр**: в `DocumentRegistry` (ABC) добавляется `list_print_renditions(print_revision_id)`; реализации — `MemoryDocumentRegistry` (фильтр по `print_revision_id`) и `PostgresDocumentRegistry` (`SELECT … WHERE print_revision_id = %s ORDER BY created_at, rendition_id`; SQL симметричен `_RENDITION_SELECT`, миграции не требуются).
- **`document_lifecycle.py`**: `retention_print_days()` — env `CISSTAT_DOCUMENT_RETENTION_PRINT_DAYS` (дефолт 30, некорректное значение — честный дефолт, паритет `retention_draft_days`). `sweep_retention` после D-цикла проходит печатные документы: для каждого `PRINT_DOCUMENT_KINDS` (V01/P01/P02) — `find_document_by_kind(run_id, kind)` → `list_print_revisions` → `list_print_renditions` → ready-renditions старее cutoff purge'ятся (`_purge_rendition`: unlink байт, tombstone `state="purged"`, хэши/запись сохранены, чтение → 410). Hold на печатном документе (`document_retention` по `document_id`, механизм единый) защищает; **basis-артефакты и пины не трогаются** — «источники и PNG могут иметь разные сроки» (§12): источник остаётся пиннутым, rendition перестаёт существовать честно (410 + пересборка через штатный POST renditions). Отчёт дополняется `scanned_print_documents`/`skipped_hold_print_documents`/`purged_print_renditions`/`print_days`.

### OPS-1 — print_renderer в `/health/ops` (health)

- **`apps/api/print_renderer_ops.py`** (новый, facts-only, peek-семантика): `print_renderer_ops_status()` — `enabled` (`renderer_enabled_from_env`), `transport` (`uds`|`tcp`, без путей/URL), `readiness` — ограниченный по времени (1.5 s) вызов существующего `PngRendererClient.readiness()` (GET `/readyz`: browser/fonts/bundle+smoke контейнера), переведённый в `{ok, status, reason}`; любые отказы (`disabled`/`unavailable`/`timeout`/`bad body`) — честные reason-коды; `probe_ms`. URL/сокет/секреты в payload не попадают. Ошибки секции не роняют `/health/ops` (паттерн peek секций main.py).
- `main.py::health_ops` добавляет `snapshot["print_renderer"]`. Классификация: print-PNG репортится **отдельной** секцией с полем `classification: "png_print (print-renderer container)"`; python-матрица `render_dependencies` (pdf/pdfa/png/parquet D-документов) не меняется — PNG-контуры разведены честно.

### COV-1 — registry coverage gate (registry)

- **`packages/ui/lib/visualExportRegistry.ts`**: `serializeVisualRegistry()` добавляет детерминированный `registry_version` = `pgv16-<12 hex sha256>` канонической сериализации сайтов (без дат — байт-паритет воспроизводим). `config/visual_registry.json` перегенерирован штатным `scripts/pgv00/export_registry.ts`.
- **`scripts/pgv16/coverage_gate.py`** (новый, fail-closed, exit≠0 при любом нарушении): (1) схема `pgv.visual_registry/1` + self-consistency `registry_version` (пересчёт хэша); (2) каждый сайт — обязательные поля, уникальность view_id, известные module_id/renderer_kind/applicability/export_status, файл `render_site` существует; (3) exclusions — известные reason_class, непустая причина, target-файлы существуют; (4) каждый научный модуль непуст; `total_sites == len(sites) == sum(modules)`; (5) паритет print-схемы: `PRINT_RENDER_BASIS_KINDS ⊇ {V01, P01, P02}`, профили figure-landscape/a4-* присутствуют, лимиты §7 (12 MP/20 стр/50 MiB/60 s) согласованы с `print_limits()`. Unknown-site AST-скан остаётся jest-оракулом (denominator coverage) — гейт честно фиксирует разделение труда (Python-гейт — структура/ссылки/паритет; TS-оракул — исходники JSX).
- **`scripts/local_gates.py`**: новый гейт `pgv16` (unittest API-корпуса + coverage_gate) и `scripts/local_gates.md` раздел PGV-16.

## 3. TDD

RED (`tests/api/test_pgv16_security_retention_ops.py`, `tests/unit/test_pgv16_coverage_gate.py`, протоколы `scripts/pgv16/protocols/`) → реализация §2 → GREEN → затронутый регресс (doclog4 audit, pgv09/10/11/12/13/14/15, doclog-pdf-env) + `check_routes`-паритет AUTH-00 (added=[]/missing=[]).

Тест-оракулы: чужой content → 404 + `download_requested=denied` (ни одной «allowed»-записи чужого); сбой sink → 503 mandatory_audit_unavailable без байт; purged → 410 + denied; integrity → aborted; SSRF-мутанты (http/file/javascript/blob href) → 422; внутренние якоря/data: проходят; retention: purge/hold/пины/свежесть/счётчики; ops: секция facts-only, без URL, сбой probe не роняет health; coverage gate: tamper-оракулы (registry_version/reason_class/файл/дубликат/пустой модуль/лимиты).

## 4. Риски и границы

- Перевод тройки в mandatory меняет поведение при сбое sink для ВСЕХ выдач документации (D01–D12 + печатные) — это и есть требование spec §11; тесты doclog4 (порядок/различимость) сохраняются без изменений.
- Probe `/readyz` в ops — сетевое чтение с жёстким таймаутом, peek-семантика сохранена (инициализации фабрик нет; отказ не ломает health).
- Retention печатных renditions при hold-protect не ломает идемпотентность пересборки (готовая rendition пересоздаётся replay-ready POST — PGV-09/14 AC09).
- VM-образы не затрагиваются поставкой (изменён python API-кода и JSON-твин; web-бандл не меняется — регенерация registry JSON входит в API-образ через config). Пересборка api-image — штатный релизный процесс, команда в чате при приёмке.

## 5. Поставка

ZIP: `cisstat-pgv16-security-retention-ops-coverage.zip` (новые/изменённые файлы задачи + files.txt). `worklog/worklog12.md` — запись PGV-16. Commit/push — тимлид.
