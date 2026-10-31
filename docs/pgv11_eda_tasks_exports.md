# PGV-11 — Export EDA/IH/tasks

**Дата:** 31 октября 2026. **База:** `main@5e0920e` (AUTH00-LOCALGATE-DIAG2; клон открытого репозитория, без commit/push — AGENTS.md).
**Критерий завершения (spec_passport_graphics_visual.md §13, строка PGV-11):** «Полные читаемые карты/матрицы, стабильная scale, unavailable не фабрикуется».

## 1. Постановка и скоуп

Продолжение серии экспорта научных визуализаций (PGV-10): «Скачать PNG» на всех render sites остановок **EDA** (16 pgv-03 view) и **задач** (`tasks.causes.fold_importance`) — всего **17 view**. Паспорта (`eda.passport.panel` → PGV-04, `eda.passport.comparison` → PGV-13), demo Навигатора и modeling/forecasting (PGV-12) — честный отказ с именем добирающей задачи.

Архитектура — та же, что в PGV-10, **без новых HTTP-роутов**: те же `GET /v1/documentation/runs/{run_id}/visual-sources` и `POST /v1/documentation/runs/{run_id}/visuals` (202 + status_url), тот же конвейер freeze → VisualPrintSnapshot/1 → V01 revision → PNG job (PGV-09). Сквозь объединённый скоуп **55 view** (38 PGV-10 + 17 PGV-11).

## 2. Ключевые решения

1. **Печатные формы — аддитивны (§6 «producer несёт print input»):** адаптеры PGV-03 срезают экранную форму; PGV-11 достраивает в тех же срезах канонические формы моста — `{columns, rows}` для таблиц, `{row_headings, column_headings, cells, cell_texts}` для тепловой карты. Экранные ключи сохраняются (паритет добора PGV-10); экранная UI читает живой ответ, а не срез.
2. **AC01 (отдельные оракулы):** scatter/histogram/kde — три РАЗНЫХ view: собственные оси (`CHART_AXES`), свой sampling frozen результата, свой title; подмена subplot'а невозможна по построению.
3. **AC02 (полная IH-матрица):** `eda.ih.conditional_map` печатается **html_table-секцией ПОЛНОСТЬЮ** (SVG-only сериализация не подходит — spec §2; `ih_conditional` — kind документов-паспортов, в `SECTION_RENDERER_KINDS` визуального снапшота не входит). Заголовки колонок — **динамические bins, замороженные В СНАПШОТЕ** из тех же frozen данных (`table_headings_from_frozen`); проценты ячеек; «Сумма строки, %» — знаменатель долей (арифметика frozen ячеек); caption несёт честные пометки: абсолютный n строки не сохранён (row_totals=None), цветовая шкала экрана 0–100 % передана полными числами. Печатная форма среза: `ih_input` + `{columns, rows}` + caption.
4. **Стабильная scale:** домен тепловой карты `eda.feature_select.matrix` — из ФАКТИЧЕСКИХ ячеек frozen данных (`_heatmap_domain`, детерминированный; две сборки — один домен — оракул); пары `{row, column, pearson}` развёрнуты в матрицу с row-headers (spec §7 «одна color scale»).
5. **Tasks view:** обязательный ref реестра `modeling_artifact_ref` — из frozen card (`card_id`); без него — честный отказ refs (не фабрикуются). `not_computed` методы не замораживаются wiring'ом (существующий контракт `/tasks/causes`) — печатная форма при not_computed честно пуста.
6. **unavailable не фабрикуется:** нет frozen результата — 409 `source_unavailable`; старый frozen артефакт без печатных форм — снапшот собирается, мост честно отказывается (`missing_section_content`, §3.6); chart-секция без screen_svg — preflight `screen_svg_required` до постановки job'а.
7. **Честный F-P10C1-паритет:** идемпотентность/identity снапшота — без изменений PGV-10 (`pgv.print_snapshot:{view}:{result_digest}[:svg16]`).

## 3. Состав поставки (файлы)

**НОВЫЕ:**
- `tests/api/test_pgv11_visual_exports.py` — 33 оракула на СВОИХ данных (RUN-PGV11xxxx, pgv11-*): скоуп/дизъюнкция/55, печатные формы всех 17, PGV-01-валидация снапшота каждого view, AC01/AC02, стабильная scale, mixed-композиции, refs tasks, мост (включая честный отказ старых артефактов), HTTP-контракт (202×17 с доведением до ready штатным worker'ом с fake-renderer'ом, 422/409/404), visual-sources;
- `packages/ui/lib/visualExportRegistry.pgv11coverage.test.ts` — coverage-гвард: 17/17 смонтированы, паспорта EDA — НЕ смонтированы, чужой viewId — ошибка, chart-сайты — scoped-сериализатор;
- `docs/pgv11_eda_tasks_exports.md` — этот документ;
- `scripts/pgv11/check_routes_auth00.py` — сверка роутов PGV-11 с картой AUTH-00 (AST discovery vs закоммиченная карта; классификации; скоуп);
- `scripts/pgv11/wire_ui.py` — повторяемое подключение кнопок (правки уже применены к исходникам);
- `scripts/pgv11/package_delivery.py`, `scripts/pgv11/protocols/` — упаковщик и протоколы.

**ИЗМЕНЕННЫЕ:**
- `apps/api/visual_exports.py` — скоуп PGV-11/объединённый, `resolve_export_view` (EDA/tasks разрешены; навигатор/demo/modeling — честные подсказки), `CHART_AXES` (13 chart-секций), `TABLE_HEADINGS` (+`eda.ih.metrics_table`), `MIXED_SECTIONS` (9 композиций), `PRINT_COMPOSITIONS` + `_ih_conditional_frozen_headings` (AC02), `VIEW_TITLES` (17), сборка снапшота (динамические заголовки из frozen), refs `modeling_artifact_ref`, `list_visual_sources` по 55;
- `apps/api/visual_producers.py` — аддитивные печатные формы 11 адаптеров (`_print_table`, `_ih_metrics_rows`, `_ih_conditional_print`, `_correlation_pairs_matrix`, `_folds_rows`, `_acf_pacf_data`); разворот `eda.feature_select.matrix` в каноническую форму html_heatmap; `tasks.causes.fold_importance` (+`modeling_artifact_ref`);
- `apps/api/print_render_payload.py` — caption переносится и для форм `{columns, rows}`/`{columns, matrix}` (честная пометка шкалы/знаменателя AC02);
- `packages/ui/components/Eda{Descriptive,Correlation,Ih,Seasonality,Stationarity,Distribution,StructuralBreaks,FeatureSelection,ValidationStrategy,ModelMatrix}Overview.tsx`, `packages/ui/components/TasksCauses.tsx` — «Скачать PNG» (ref СВОЕЙ поверхности, кнопка следует активному представлению; ref до ранних возвратов — урок PGV-10);
- `tests/api/test_pgv10_visual_exports.py` — честные пины сужения недобора: `eda.descriptive.stats`/`tasks.causes.fold_importance` вышли из out-of-scope (скоуп пинится корпусом PGV-11), visual-sources 38 → 55;
- `tests/api/test_p10cert_oracles.py` — те же два честных сдвига (out-of-scope кейс → `eda.passport.panel`; 38 → 55);
- `docs/auth00/policy_review.json` — baseline `5e0920eefe…`, reviewed_sources +`visual_producers.py`/`print_render_payload.py`;
- `docs/auth00/inventory.json`, `docs/auth00/inventory.md` — регенерированы (`inventory.py --write`): **534 entries / api 220 — БЕЗ изменений** (новых маршрутов нет), fingerprints дерева поставки;
- `docs/auth00/operation_variants.md` — база обзора, строка PGV-11 (скоуп тех же маршрутов расширен, семантика не менялась);
- `packages/ui/components/EdaFeatureSelectionOverview.tsx` — **дополнительно восстановлены две последовательности `[m`, съеденные коммитом 5e0920e** (`const [method,setMethod]`, `?.[method]??0` — файл в коммите синтаксически сломан; см. §6);
- `worklog/worklog11.md` — запись поставки.

## 4. AUTH-00: сверка роутов и обновление карты

Постановка тимлида: «Проверь выполненную задачу PGV-11 на предмет соответствия карте роутов из AUTH-00. Если необходимо внести изменения в маршруты, обнови карту».

1. **Сверка (`scripts/pgv11/check_routes_auth00.py` → PASS):** PGV-11 НЕ добавляет ни одного маршрута — 21 api:* маршрутов `routers/documentation.py` идентичны закоммиченной карте `5e0920e`; оба экспорт-маршрута несут классификацию `document.object` + `authorize-before-operation`; все 17 view проходят `resolve_export_view`.
2. **Необходимое обновление карты:** изменились ФАЙЛЫ, входящие во frozen-fingerprints гейта (`visual_exports.py`, `visual_producers.py`, `print_render_payload.py`) → без регенерации гейт падает `Inventory drift` (воспроизведено до обновления). Выполнен явный review-шаг: policy_review baseline → дерево поставки, reviewed_sources дополнены фактически сверявшимися файлами, снапшоты регенерированы `inventory.py --write`.
3. **Результат:** `--check` OK (534 entries, api 220 — без изменений), unittest 27/27 OK, `scripts/local_gates.py --only rules` PASS. Число маршрутов приложения — 224 (без изменений PGV-10).

## 5. TDD и верификация

- **RED:** 29 failed / 3 passed на базе 5e0920e (`scripts/pgv11/protocols/red_protocol.txt`).
- **GREEN:** корпус PGV-11 **33/33**; корпус PGV-10 и p10cert — GREEN (после честных пинов скоупа).
- **Полный tests/api:** 3387P / 20F / 42S; **дельта-0 против чистого 5e0920e** — failed-списки байт-идентичны (20 предсуществующих средовых; `diff` пуст), +33 passed = ровно корпус поставки.
- **Полный Jest:** 2781–2782 passed / 0 failed в каждом прогоне; «падения» сьютов — SIGKILL воркеров песочницей (OOM; случайные сьюты от прогона к прогону), изоляция `--runInBand` — GREEN. Coverage-гварды PGV-10/PGV-11, serializeChartSvg, EDA-компоненты, TasksCauses — GREEN.
- **tsc `packages/ui`** — без ошибок кода (только предсуществующие deprecation-варнинги tsconfig от нового tsc); py_compile; import `apps.api.main` — 224 маршрута.

## 6. Честные границы

1. **Предсуществующая порча в коммите 5e0920e:** `EdaFeatureSelectionOverview.tsx` закоммичен с двумя съеденными последовательностями `[m` (`const ethod,setMethod]`, `?.ethod]??0` — синтаксическая ошибка в блобе; воспроизводится `git show 5e0920e:...`). Поставка восстанавливает честный текст; tsc/jest на исправленном файле зелёные. По изменённым файлам аналогичной порчи не обнаружено.
2. Контейнер PGV-08/Chromium/Docker в среде недоступны (унаследовано): полный путь job'а — штатный worker с fake-renderer'ом (паттерн PGV-09/10); контейнерная E2E/пиксельная корректность — PGV-08/CERT.
3. Живой PostgreSQL/Render не проверялись (Memory-сторы; durable-зеркала наследуются от PGV-02/09).
4. Предсуществующий флак `test_o20` (p10cert, порядок обработки job'ов worker'ом) воспроизводится и на чистом 5e0920e — средовый, не тронут.
5. coverage-гвард — статический оракул исходников; живая браузерная приёмка кнопок — вне среды.
6. Печатная секция AC02 — таблица с честной текстовой пометкой о цветовой шкале (штатный печатный рендер html_table не несёт цвета ячеек; ih_conditional-секции — вид документов паспортов PGV-13, не визуальных снапшотов).

## 7. Deliverable

ZIP `cisstat-pgv11-eda-tasks-exports.zip` → открытый контейнер сессии (`download/`) и веб-приложение сессии (:3000, страница поставки с кнопкой скачивания); только файлы текущей задачи. Упаковщик сверяет точное множество файлов и побайтное содержимое. SHA-манифест не ведётся (конвенция серии). Без commit/push (AGENTS.md).
