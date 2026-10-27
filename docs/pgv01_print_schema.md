# PGV-01 — Print schema/metadata/profile (документ поставки)

**Дата:** 27 октября 2026. **База:** `main@2ef6947` (PGV-00 — реестр render-sites; рабочее дерево синхронизировано, затем реализация). **Статус:** versioned-схемы + валидация + профили; runtime (store/jobs/renderer) не менялся. **Родительский контракт:** `spec_documentation_logging.md` §7/§9.2/§12/§19 (аддитивные дополнения PGV-00/PGV-01). **Проектная спека:** `spec_passport_graphics_visual.md` §6/§7/§13 (строка PGV-01), §14 (приёмочные сценарии).

---

## 1. Назначение и границы

PGV-01 фиксирует **общие версионированные контракты печатной основы** PNG-экспорта и паспортов (Путь A/B проектной спеки): что обязан нести frozen payload научной визуализации при постановке рендер-задания. Критерий готовности по spec §13 — «**Result/version/date/units/sampling обязательны по applicability, параметры trusted**».

**Границы поставки (честно):** схемы/валидаторы/профили — контрактный слой, НЕ runtime. Durable store (`visual_result`/`passport_checkpoint` kinds) — PGV-02; producer-адаптеры — PGV-03/04; `PassportHistoryReader`/comparison — PGV-05/06; pure print layout — PGV-07; renderer-контейнер и jobs — PGV-08/09. Продуктовый код (компоненты, API-роутеры, сборки) не менялся: существующие пути скачивания (legacy PNG прогноза, D01–D12 renditions) сохраняют прежнее поведение (spec §10.1/§12).

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `packages/ui/print/printSchema.ts` | Источник истины: версии схем (`pgv.visual_result/1`, `pgv.visual_print_snapshot/1`, `pgv.print_manifest/1`, `pgv.print_profiles/1`), каталог профилей, лимиты §7, правила обязательности по scope/renderer_kind, валидаторы, builder минимального валидного снапшота, сериализация твина |
| `packages/ui/print/printSchema.test.ts` | Jest-оракул: 43 теста — профили/пиксели (PGV-AC16), обязательность metadata (PGV-AC05/AC07/AC08/AC12), trusted-параметры, панель/checkpoint (PGV-AC11/AC14), renderer env (PGV-AC17), sensitive-политика (PGV-AC21), манифест, cross-check реестр⇄схема (89 sites), паритет TS⇄JSON |
| `config/print_schema.json` | JSON-твин для бэкенда и doc-проверок; генерируется `scripts/pgv01/export_print_schema.ts` (паттерн EDU-API-1/PGV-00) |
| `apps/api/print_schema.py` | Python-зеркало правил: preflight frozen payload для PGV-02/09 (те же коды нарушений, чтение твина; без FastAPI-зависимостей) |
| `tests/api/test_pgv01_print_schema.py` | Pytest-сюита зеркала: 35 тестов (твин, профили/лимиты, scope/refs, валидация снапшота/результата/манифеста, согласованность с реестром PGV-00) |
| `packages/ui/lib/visualExportRegistry.ts` | Уточнение required_refs (PGV-00 §7 «уточняется PGV-01»): `+data_revision` у `upload.structure.schema` и `forecasting.accuracy.metrics` |
| `config/visual_registry.json` | Регенерация JSON-твина реестра после уточнения (паритет TS⇄JSON сохранён) |
| `scripts/pgv01/export_print_schema.ts` | Генератор твина print-схем (`node --experimental-strip-types`) |
| `scripts/pgv01/check_documents.py` | Doc-contract гвард «документация == print-схема» |
| `docs/pgv01_print_schema.md` | Этот документ |
| `spec_documentation_logging.md` | Родительская спека: строка PGV-01 в §19 + актуализация точки §19.1 |
| `worklog/worklog11.md` | Запись Task ID: PGV-01 |

## 3. Проектные решения

### 3.1. Scope и обязательные refs («version обязателен по applicability»)

Снапшот не знает про «средний» run: scope выводится из реестра PGV-00 — `demo` (статические preview Навигатора, `demo_dataset_id`), `research` (runtime-сайты: `context_id` + `data_revision`), `passport` (`snapshot_id`/`schema_version`), `comparison` (D12-сверка на frozen vintages). Мандат scope объединяется с заявленными `required_refs` сайта: снапшот обязан нести **все** ref'ы, объявленные его view. Cross-check оракула нашёл ровно две записи research-зоны без `data_revision` (`upload.structure.schema`, `forecasting.accuracy.metrics`) — уточнены с комментарием PGV-01 (задокументированное ограничение PGV-00: «точность required_refs — проектная, уточняется PGV-01»).

### 3.2. Честные null-причины вместо выдуманных фактов (§6)

Единицы, даты, digest/hash — пары «значение XOR причина» (`ambiguous_*`/`missing_*` коды): не выдумывать units и timestamps; утраченный исторический факт — `legacy_unknown` (PGV-AC12), демо-данные — `demo_dataset`. Содержательные требования по renderer_kind: `recharts_svg` — оси с именами и units; `html_table` — заголовки строк/колонок (axes_applicability=not_applicable, §6); `html_heatmap` — цветовая шкала с domain и units; `html_cards` — units с честной `dimensionless`. Смешанные сайты (`mixed`) обязаны нести ≥2 секции базовых kinds — секция декларирует свой renderer_kind.

### 3.3. Trusted-параметры и allowlist selection (§6)

`method.origin` — только `producer_freeze`/`producer_first_export`; клиентский `selection` — ключи строго из `view_params` сайта реестра (`selection_not_allowlisted` иначе). Authoritative series/caption от клиента не принимаются — клиент передаёт ref и allowlisted display selection. Нарушения — стабильный контракт кодов (37 кодов, `printSchemaViolationCodes()`/модуль), на который опираются 422 `invalid_selection/profile` в PGV-09.

### 3.4. Профили и лимиты (§7)

Каталог из трёх профилей: `figure-landscape` (2400×1500 @300 ppi = 8×5 in, по умолчанию), `a4-portrait` (2480×3508), `a4-landscape` (3508×2480). Оракул px⇄мм⇄ppi с допуском округления ≤1px (PGV-AC16; A4 — закреплённое округление спеки: 210 мм / 25.4 × 300 = 2480.3). Лимиты §7 закреплены: 12 MP/страница, 20 страниц, 50 MiB/job, timeout 60 s, concurrency tenant=1/global=2 — источник констант для PGV-08/09 (413 `export_too_large`).

### 3.5. Манифест комплекта и sensitive-политика (§7/§11)

`PrintSetManifest/1`: порядок (непрерывный 1..n), уникальные имена страниц, page roles, пиксели, `png_sha256` **отдельным полем** (hash не внутрь PNG bytes — циклическая зависимость исключена по построению), `metadata_filename`, `data_included=false` пином (ZIP — контейнер PNG и метаданных, raw DataFrame не вкладывается, PGV-AC21). Снапшот несёт `sensitive.raw_data_included=false` (пин) и политику чувствительных полей; renderer env — честный `dependency_status` с обязательной причиной при `unavailable` (PGV-AC17).

### 3.6. Freeze-семантика (§6, PGV-AC07)

`expected_context` (context_id + data_revision [+ expected_data_digest]) обязателен для research-снапшотов — база для 409 `context_changed` при несовпадении закреплённой версии с текущими данными (сравнение на PGV-02/09; схема фиксирует поля и обязательность). Reused checkpoint (PGV-AC11): флаг `reused=true` требует `checkpoint_confirmed_at` и `source_snapshot_ref` — подтверждение и ссылка на исходный снимок без ложной «четвёртой копии».

## 4. TDD

**RED-1 (jest):** `packages/ui/print/printSchema.test.ts` до реализации — collection RED `TS2307: Cannot find module './printSchema'` (честный Import-RED, паттерн PGV-00). **GREEN:** реализация `printSchema.ts` → 43/43. В процессе GREEN зафиксированы два дефекта самого оракула (не реализации): неаккуратная массовая замена view_id (`eda.correlation.heatmap` не существует в реестре — заменён на реальные `eda.feature_select.matrix`/`upload.distribution.scatter`/`upload.overview.preview`) и TS-пин литерального типа в мутанте schema_version. Попутно пойман честный негативный сигнал: тест heatmap после массовой замены проверял график вместо тепловой карты — восстановлен на `eda.feature_select.matrix`.

**RED-2 (pytest):** `tests/api/test_pgv01_print_schema.py` до реализации — collection RED `ModuleNotFoundError: No module named 'apps.api.print_schema'`. **GREEN:** `apps/api/print_schema.py` → 35/35 (после честных фиксов: Python-константы списками для паритет-пина, fixture source_hash для research-зоны, view_id оракула).

**Негативные мутанты покрыты оракулами:** удаление `data_revision` из refs → `missing_required_ref`; `computed_at` без причины → `missing_date`; units без value/reason → `missing_units`; downsampled без point_cap → `missing_point_cap`; client origin → `untrusted_parameter_origin`; selection вне view_params → `selection_not_allowlisted`; entity_id на univariate → `panel_mixing`; reused без подтверждения → `missing_checkpoint_confirmation`; unavailable без причины → `missing_renderer_reason`; raw_data_included=true → `raw_data_included_forbidden`; чужая schema_version → `schema_version_mismatch`; дубликаты/разрывы порядка/пустой hash/data_included=true в манифесте → соответствующие коды.

## 5. Верификация

- **Jest (полный корпус):** см. worklog — новый сюит 43/43 + coverage-оракул PGV-00 16/16 (уточнение реестра не повредило пины: denominator 89, паритет TS⇄JSON, честность статусов) + полный регресс без регрессий.
- **Pytest:** `tests/api/test_pgv01_print_schema.py` — 35/35; doc-contract гвард PGV-00 — 353/353 (регенерация JSON-твина реестра согласована с документацией).
- **check_documents.py (PGV-01):** doc-contract гвард — см. раздел 7.
- Границы: docker/браузерная приёмка не применимы (runtime не менялся); живой рендер — PGV-08/09; полный tests/api не гонялся — дифф добавляет standalone-модуль без затрагивания существующего Python-runtime (граница зафиксирована, паттерн PGV-00).

## 6. Вклад в приёмочные сценарии (§14)

| Сценарий | Вклад PGV-01 |
|---|---|
| PGV-AC05 (labels/units/legend/method/date/context/data_revision не теряются) | Валидатор обязателен по applicability; compact/expanded не влияют на мандат (тест) |
| PGV-AC07 (смена данных при freeze → 409) | `expected_context` обязателен для research; поля freeze-сверки закреплены |
| PGV-AC08 (sampling различим, без скрытого upgrade) | Режимы + point_cap для downsampled/windowed/truncated; `full` — декларация отсутствия усечения |
| PGV-AC11 (reused checkpoint без ложной копии) | `checkpoint.reused` требует confirmed_at + source_snapshot_ref |
| PGV-AC12 (legacy gaps честны) | XOR-причины (`legacy_unknown`) для дат/хэшей; без выдуманных значений |
| PGV-AC14 (panel не смешивается) | mode=panel + entity_column для панельных сайтов; `panel_mixing` на univariate |
| PGV-AC16 (A4 px/ppi согласованы) | Каталог профилей + оракул px⇄мм ≤1px, пропорции сохранены |
| PGV-AC17 (missing dependency честен) | renderer_env `unavailable` требует причину |
| PGV-AC21 (ZIP без raw данных/чужих артефактов) | Манифест: hash отдельным полем, `data_included=false`, уникальные имена, непрерывный порядок |
| PGV-AC03 (frozen-data oracle) | Builder минимального валидного снапшота — эталон обязательного состава для всех 89 sites |

## 7. Doc-contract гвард

`scripts/pgv01/check_documents.py` проверяет: постановку (строка PGV-01, критерий, зависимость PGV-00, AC-ссылки), родительскую спеку (строка §19 + точка §19.1 с `printSchema`/`print_schema.json`), целостность `config/print_schema.json` (версии, 3 профиля, точные пиксели A4, лимиты §7, правила), целостность `config/visual_registry.json` после уточнения (89 sites, `data_revision` в уточнённых записях), существование всех файлов поставки, согласованность документа и worklog-записи.

## 8. Ограничения и переходы

1. Схемы — контракт, не store: durable-хранение `visual_result`/`passport_checkpoint` и versioned migrations — PGV-02; producer-фиксация через `promotion_integration` — PGV-03/04.
2. Python-зеркало — preflight-паритет правил; полным оракулом остаётся jest (источник истины — TS); расхождение невозможно без падения паритет-теста твина.
3. Sampling-правила v1 — по renderer_kind; уточнение по view_params (zoom/window/биннинг) — producer-адаптеры PGV-03 (точка расширения `samplingRequiredForSite`).
4. `print-профили` — физическая семантика; фактическая пиксельная композиция и пагинация — PGV-07/14 (layout поверх профиля).
5. Builder `buildMinimalValidSnapshot` — эталон состава для тестов/адаптеров; значения-фикстуры (`fixture:*`) не являются научными данными.
