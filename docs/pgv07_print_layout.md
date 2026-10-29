# PGV-07 — Shared pure print layout (документ поставки)

**Дата:** 29 октября 2026. **База:** `main@1254e50` (KNOWLEDGE-INGESTION-SPEC; PGV-00…PGV-06 включены; рабочее дерево синхронизировано клоном, затем реализация). **Статус:** shared pure print layout — общая чистая печатная композиция UI-слоя; renderer-контейнер, jobs и durable-пайплайн не менялись. **Родительский контракт:** `spec_documentation_logging.md` §7/§12/§19. **Проектная спека:** `spec_passport_graphics_visual.md` §3 (инвариант 4), §4.1, §7, §13 (строка PGV-07), §14 (приёмочные сценарии).

---

## 1. Назначение и границы

PGV-07 реализует строку PGV-13 проектной спеки: «**Shared pure print layout**», точки изменения «`packages/ui/print`/chartVars/screen charts», критерий готовности — «**Light фон, labels/legend/HTML IH/полные паспорта, без fetch/animation**». Это общий print bundle §4.1: «Общий print bundle рендерит Recharts/SVG, HTML IH, матрицы, паспорта и сравнения … Fetch/state/animation отделяются от pure presentation, чтобы screen и print переиспользовали научную геометрию без второй реализации на Python».

**Границы поставки (честно):** компоненты и форматтеры — pure presentation, НЕ runtime-рендер. Изолированный контейнер renderer'а — PGV-08; jobs/CAS/lease — PGV-09; подключение экспорта в экранные остановки (продюсерские адаптеры, action bars) — PGV-10…12; builders P01/P02 — PGV-13; оркестрация page-set/ZIP — PGV-14. Экранные компоненты (`DistributionCharts.tsx`, `EdaIhOverview.tsx`, `DatasetPassportPanel.tsx`, …) и legacy-ветка скачивания `ForecastExportMenu` **не менялись**: их научная геометрия переиспользуется композицией (`PrintChartSection` принимает готовый chart-элемент как children), а не мутацией. `packages/ui/index.ts` (продуктовый barrel) не расширялся — print bundle импортируется напрямую из `packages/ui/print` (урок DOCLOG-8-UI-FIX: barrel делает компоненты достижимыми из server-компонент; здесь это безопасно и без barrel — компоненты без хуков).

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `packages/ui/print/printTheme.ts` | Светлая печатная тема: жёсткие hex-константы (AC04), `PRINT_PALETTE`/`PRINT_STATUS_MARKS` (цвет дублируется знаком/меткой — §7)/`PRINT_TYPE_SCALE` (мин. тело 12 px)/`PRINT_FONT_STACK`; `resolveChartVarLight`/`resolveVarStringLight` — надстройка над светлой картой `chartVars.CHART_VARS_LIGHT` без её модификации |
| `packages/ui/print/printLayout.tsx` | Каркас страницы §7: `PrintPageFrame` (верх — заголовок/вид/источник/target/date/entity/context/data_revision/даты; низ — метод+origin/параметры/версия данных/короткие IDs/номер страницы/пояснения), `PrintPageSurface` (фиксированные px профиля), `pageGeometry` (каталог PGV-01), детерминированные форматтеры (`formatNumberRu`/`formatPrintTime`/`formatUnit`/`shortRef`/`describeSampling`), `PrintLegendStrip`/`PrintNotes`/`PrintSectionTitle` |
| `packages/ui/print/printSections.tsx` | Секции по renderer_kind: `PrintChartSection` (оси с единицами XOR-причин, полная легенда, передача научной геометрии), `PrintTableSection` + `chunkTableRows` (целые строки, повтор заголовков, метка продолжения — база AC15), `PrintHeatmapSection` + `heatColor` (шкала domain+units+legend, честный пропуск), `PrintCardsSection` |
| `packages/ui/print/printIh.tsx` | HTML IH (AC02): `PrintIhConditionalMatrix` — все bins строк/колонок, проценты, знаменатель строки или честная причина, правило 100 %, color legend 0–100 %; `PrintIhMetricsMap` |
| `packages/ui/print/printPassport.tsx` | Полный паспорт (§8): `PrintPassportPage` — провенанс (stage/snapshot/captured_at/context/data_revision/fingerprint/source_hash/schema/calculation version), ВСЕ группы `KNOWN_PASSPORT_GROUPS` + неизвестные по ключу (не выбрасываются), XOR-честность (`legacy_unknown`/`integrity_failure`), баннеры `unsupported_schema` (allowlist `KNOWN_PASSPORT_SCHEMA_VERSIONS` passport/1.0–1.2) и content-гэпа без фабкации |
| `packages/ui/print/printComparison.tsx` | Сравнение (§9/AC13): `PrintPassportComparisonPage` — значения по этапам + absolute/relative дельты, категории/списки/булевы/качественные, определения движка (zero-denominator reason, «цвет delta не значимость»), строка подтверждения reused checkpoint (AC11), честные gaps, маркировка cross_context/полности; зеркало frozen-вывода PGV-06 (`pgv.passport_comparison/1`) |
| `packages/ui/print/index.ts` | Баррель print-бандла для PGV-08/13/15 |
| `packages/ui/print/printLayout.test.tsx` | Jest-оракул: 34 теста — тема/AC04 (статический + динамический оракулы), чистота бандла, композиция §7/AC05, форматтеры, профили AC16, секции, чанкование AC15, HTML IH AC02 |
| `packages/ui/print/printPassport.test.tsx` | Jest-оракул: 14 тестов — полный паспорт без сокращений, неизвестные группы, XOR/AC12, unsupported_schema, content-гэп, сравнение AC13/AC11/gaps/cross_context |
| `docs/pgv07_print_layout.md` | Этот документ |
| `scripts/pgv07/check_documents.py` | Doc-contract гвард (постановка/спека/файлы/AC-привязка/worklog) |
| `scripts/pgv07/protocols/red_protocol.txt` | Протокол RED-прогона (честный Import-RED TS2307 ×5) |
| `worklog/worklog11.md` | Запись Task ID: PGV-07 |

## 3. Проектные решения

### 3.1. Light-print поверх chartVars, не новая палитра (AC04)

Значения серых/осевых/серийных цветов не придуманы заново: `printTheme` строится **над** `CHART_VARS_LIGHT` (packages/ui/lib/chartVars.ts — светлая карта DKT-3, источник `:root` globals.css). Отличие печати: инлайн-константы вместо `var()` — печатная страница не зависит ни от активной темы, ни от контекста документа. Оракулы: паритет `resolveChartVarLight` ⇄ карте (все 50 ключей), статический запрет `dark:`/`var(` в инлайнах, динамическая байт-идентичность рендера внутри `.dark`-предка. Статусные цвета затемнены для контраста на белом (экранные `--status-*` светлее); красный/зелёный не единственный носитель смысла — `PRINT_STATUS_MARKS` дублирует статус знаком и текстовой меткой (§7, база AC23-OCR).

### 3.2. Чистота бандла (§4.1: без fetch/animation)

Статический оракул исходников запрещает: `fetch(`/`axios`/`XMLHttpRequest`, hooks (`useState`/`useEffect`/…), `Tooltip`, `ResponsiveContainer`, `Date.now()`/`new Date()`/`Math.random()`, `"use client"`, `dark:`-классы. Детерминизм: время печатается из ISO-строки напрямую (`formatPrintTime`), числа — собственный ru-форматтер (`formatNumberRu` с фиксированными разделителями и срезом хвостовых нулей), анимации/переходы гасятся глобальным kill-switch'ем печатной страницы (`animation/transition: none !important`). Никакого текущего времени: page number, времена и параметры — только из props/frozen снапшота.

### 3.3. Композиция §7 и метаданные (AC05)

`PrintPageFrame` печатает обязательный состав: header (title/subtitle, view_id+scope, источник «module / stop», target/date/entity/entity_id по applicability, режим univariate/panel, context/data_revision, computed/captured с честными причинами, reused-checkpoint строка), sampling-бейдж (режим/потолок/причина — AC08, не теряется при expanded), footer (метод + origin «producer_freeze/producer_first_export» + параметры, версия данных, короткий ID результата `shortRef` ≤10 символов + «…», тема/профиль, «Стр. N из M», пояснения/warnings). Оракул: meta-блок байт-идентичен для compact/expanded (ничего не теряется при раскрытии).

### 3.4. Секции по renderer_kind (§5–§7)

`recharts_svg`: заголовок, оси «имя (единица | без единицы (причина))», ПОЛНАЯ легенда `legend_ordering`, фиксированная поверхность, в children передаётся научная геометрия экранного компонента (переиспользование §4.1 — без второй реализации). Свотчи легенды (`PrintLegendStrip`) — иллюстративные (честная маркировка «цвета свотчей иллюстративные — фактические цвета серий в контракт печати не переданы», PGV-07-FIX/F-P7C2: фактические цвета серий контрактом PGV-01 не передаются, фабкация фактического вида запрещена). `html_table`: `chunkTableRows` режет ТОЛЬКО целыми строками (rowsPerPage<1 → 1), thead повторяется на каждой части, продолжение помечено caption'ом — база пагинации AC15 (оркестрация страниц/ZIP — PGV-14). `html_heatmap`: шкала `heatColor` (белый → series_blue, clamp по domain), color legend «min–max + units», пропуск — «нет данных» на нейтральной подложке, не ноль. `html_cards`: подпись/значение/единица с XOR-причиной.

### 3.5. HTML IH (AC02)

`PrintIhConditionalMatrix` печатает условную карту полностью: все x_bins (строки) и y_bins (колонки), проценты ячеек («60 %», ru-формат), знаменатель строки отдельной колонкой (n по интервалу фактора) ЛИБО честная причина («знаменатель строки не сохранён в frozen результате»), общий N, правило «каждая строка суммируется до 100 %», color legend 0–100 % с единицей «доля строки, % (dimensionless)». Данные — frozen вход producer-адаптера (зеркало EdaIhResponse-полей), НЕ пересчёт.

### 3.6. Полный паспорт и сравнение (§8/§9)

Паспорт: все 12 известных групп (`KNOWN_PASSPORT_GROUPS`) + неизвестные print'у группы по ключу словаря (§8: «все группы существующей схемы … не сокращается»); особые случаи схемы — `trend.direction` словами, `is_stationary` «стационарен/нестационарен», `applicable:false + reason` — «не применимо: …»; XOR-поля печатают причину (`неизвестно (legacy_unknown)`), не выдуманное значение (AC12); content-гэп — баннер «содержимое не фабрикуется» без таблиц; неизвестная схема — баннер `unsupported_schema` (allowlist passport/1.0–1.2 из документации движка сравнения). Сравнение: зеркало frozen-вывода PGV-06 — значения по этапам (v_old→from, v_new→to, паритет экранной ComparisonView), дельты «+50 (+50 %)» со знаком текстом (цвет не применяется), определения движка печатаются целиком (zero-denominator reason, «цвет delta не означает статистическую значимость»), reused checkpoint — отдельная строка подтверждения (confirmed_at + reused ref + «без повторного расчёта», AC11 — path уже без дублирующей колонки, семантика резолвера PGV-06), gaps — явным списком с at/reason/detail (partial — не ноль), cross_context — бейдж явного режима.

### 3.7. Профили и геометрия (AC16)

`pageGeometry(profileId)` читает каталог PGV-01 (figure-landscape 2400×1500, a4-portrait 2480×3508, a4-landscape 3508×2480 @300 ppi); `PrintPageSurface` задаёт фиксированные px (×scale, округление) с непрозрачным белым фоном — не viewport. Пропорция A4 закреплена оракулом (≈210/297, допуск округления ≤1px — пин PGV-01).

## 4. TDD

**RED (jest):** `printLayout.test.tsx` + `printPassport.test.tsx` до реализации — collection RED `TS2307: Cannot find module './printTheme'|'./printLayout'|'./printIh'|'./printPassport'|'./printComparison'` (честный Import-RED ×5, протокол `scripts/pgv07/protocols/red_protocol.txt`, паттерн PGV-00/01).

**GREEN:** реализация 7 модулей → 34/34 + 14/14. В процессе GREEN зафиксированы три дефекта самого оракула (не реализации): массивы в JSX-атрибутах без фигурных скобок (синтаксис теста), RTL bound-queries ищут в baseElement — при двух живых рендерах scoping явно через `container.querySelector` (урок зафиксирован ниже), и ожидание `shortRef` приведено к семантике keep=10. Два дефекта реализации, пойманные оракулами: `formatNumberRu` не срезал хвостовые нули (»,250» вместо »,25») и point_cap в `describeSampling` печатался с группировкой разрядов (»3 000» вместо экранного паритета «3000»).

**Негативные мутанты покрыты оракулами:** тёмная тема (инлайн var()/dark-зависимость → байт-диф), потеря легенды/sampling при expanded, потеря метаданных в compact, разрез строки чанком, дубликат заголовков отсутствует, выдуманный знаменатель IH, выброшенная неизвестная группа паспорта, выдуманный fingerprint при legacy_unknown, пустая картинка при unsupported schema/content-гэпе, нулевая дублирующая колонка reused, подмена gap нулём, потерянные определения/zero-denominator reason.

## 5. Верификация

- **Jest полный корпус:** 226/226 сюит, **2523/2523** (2475 до поставки + ровно 48 новых PGV-07; printSchema 43/43, coverage-оракул PGV-00, chartVars-зеркала ForecastExportMenu.vars — без регрессий).
- **Сборка:** `typecheck:all` ✓ (embedded + standalone); `next build` embedded ✓ (компиляция с print-бандлом в графе модулей).
- **Границы:** docker/браузерная приёмка не применимы (renderer-контейнер — PGV-08); Python-runtime не менялся — pytest-корпус не затронут (паттерн PGV-00/01); продукты и legacy-пути скачивания не менялись.

## 6. Вклад в приёмочные сценарии (§14)

| Сценарий | Вклад PGV-07 |
|---|---|
| PGV-AC02 (IH HTML matrix полностью) | `PrintIhConditionalMatrix`: bins/проценты/знаменатель/color legend — оракул состава и честного пропуска |
| PGV-AC04 (dark/light → одинаковый light-print) | Жёсткие hex, kill-switch анимаций; статический + динамический (байт-идентичность в `.dark`) оракулы; полная контейнерная проверка — PGV-08 |
| PGV-AC05 (labels/units/legend/method/date/context/data_revision) | Композиция §7 с обязательным meta-составом; оракул байт-равенства compact/expanded |
| PGV-AC08 (sampling различим) | `describeSampling`: режим/потолок/причина; бейдж не теряется |
| PGV-AC11 (reused без ложной копии) | Отдельная строка подтверждения сравнения (confirmed_at + reused ref), без дублирующей колонки |
| PGV-AC13 (P02 numeric/category/list/qualitative, zero-denominator) | `PrintPassportComparisonPage` + печатаемые определения движка |
| PGV-AC15 (пагинация без crop) | `chunkTableRows` + повтор заголовков + метка продолжения; оркестрация — PGV-14 |
| PGV-AC16 (A4 px/ppi согласованы) | `pageGeometry`/`PrintPageSurface` из каталога PGV-01, пропорции пином |
| PGV-AC23 (OCR/читаемость) | Минимум шрифта 12/10 px, цвет дублируется знаком/текстом — база контейнерной проверки |

## 7. Doc-contract гвард

`scripts/pgv07/check_documents.py` проверяет: постановку (строка PGV-07, критерий, зависимость PGV-01, AC-ссылки), проектную спеку (строка §13 PGV-07, §4.1/§7/§14), состав поставки (все файлы существуют), связность документа и worklog-записи (Task ID, состав файлов, счётчики тестов).

## 8. Ограничения и переходы

1. Print-бандл — presentation-слой: mount в изолированный renderer-контейнер, fonts/Chromium/health — PGV-08; job/lease/CAS — PGV-09.
2. Экранные компоненты не переключены на печать: экспортные action bars и producer-адаптеры — PGV-10…12; выборки снапшотов из реестра — уже типизированы (`PrintSectionSpec` PGV-01).
3. Пагинация: PGV-07 даёт чанкование целых строк и повтор заголовков; page-set/manifest/ZIP-оркестрация — PGV-14 (лимиты §7 закреплены в PGV-01).
4. `formatNumberRu` — ru-конвенция печати (детерминизм); интернационализация подписей — вне границы (платформа русскоязычная).
5. Сериализация в PNG (pHYs density, 12 MP/50 MiB preflight) — PGV-08/09; PGV-07 гарантирует фиксированную геометрию и отсутствие скрытых зависимостей.
