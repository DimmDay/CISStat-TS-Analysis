# PGV-00 — Инвентарь научных render-sites (документ поставки)

**Дата:** 27 октября 2026. **База:** `main@754219a` (spec_passport_graphics_visual.md — постановка). **Статус:** реестр + родительская спека; runtime не менялся. **Родительский контракт:** `spec_documentation_logging.md` §7/§9.2/§12/§19 (аддитивные дополнения PGV-00).

---

## 1. Назначение и границы

PGV-00 создаёт полный machine-readable инвентарь всех научных визуализаций платформы — foundation для PNG-экспорта (Путь A) и печатных паспортов/сравнений (Путь B, P01/P02) по `spec_passport_graphics_visual.md`. Реестр фиксирует для каждого render-site: `view_id`, `module_id`, `stop_id`, `render_site`, `renderer_kind`, `source_adapter`, `required_refs`, `view_params`, `applicability`, `caption_schema`, `export_status`, `tests` — состав полей §5 проектной спеки.

**Границы поставки (честно):** реестр — инвентарь и план, не runtime. Эта задача не реализует PNG-рендер, VisualResult/VisualPrintSnapshot, producer-адаптеры и UI-кнопки «Скачать PNG» — это PGV-01…09/13/15. Продуктовый код (компоненты, API, сборки) не менялся: поставка — два новых lib-файла, JSON-твин, два скрипта, документ, правки родительской спеки и журнал. Существующие пути скачивания (legacy PNG прогноза, D01–D12 renditions) сохраняют прежнее поведение.

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `packages/ui/lib/visualExportRegistry.ts` | Источник истины: типы, каталоги остановок, 89 записей, 9 групп исключений, хелперы/сводка |
| `packages/ui/lib/visualExportRegistry.coverage.test.ts` | Coverage-оракул: интегрити + pattern-скан + семейные правила + пины + паритет TS⇄JSON (16 тестов) |
| `config/visual_registry.json` | JSON-твин для бэкенда (PGV-01/02) и doc-проверок; генерируется `scripts/pgv00/export_registry.ts` |
| `scripts/pgv00/check_documents.py` | Doc-contract гвард «документация == реестр» (335 проверок) |
| `docs/pgv00_render_site_inventory.md` | Этот документ |
| `spec_documentation_logging.md` | Родительская спека: дополнения §7/§9.2/§12/§19/§19.1 |
| `worklog/worklog11.md` | Запись Task ID: PGV-00 |

## 3. Состав реестра по модулям (denominator coverage)

| Модуль | Sites | Охват |
|---|---|---|
| navigator | 14 | Реальные научные preview Навигатора: график ряда, scatter/histogram, паспорт, 5+5, тех-инфо, структура, качество, источник, форматы, 4 validation-эталона — статические, на демо-данных (`static_demo`) |
| upload | 12 | Обзор (превью строк + тех-таблица), график ряда, декомпозиция (доли + ряд), scatter/histogram/KDE, схема структуры, teaser качества, паспорт + сравнение |
| validation | 12 | Матрица типов, единый reusable chart (formats), 8 профильных обзоров (ranges/consistency/uniqueness/inclusion/referential/text_quality/regularity/sufficiency), паспорт + сравнение |
| preprocessing | 20 | Missing (обзор + CSS-матрица + корреляции), Outliers (обзор + профиль ряда), Regularity (обзор + карта gaps), Декомпозиция, Variance_stab (5 субвидов), Smoothing, Stationarity, Spectral, Feature_eng, Scaling, паспорт + сравнение |
| eda | 18 | Описательные статистики + scatter/histogram/KDE, ACF/PACF, IH (метрики/условная карта/результаты), сезонность, стационарность, распределение, структурные сдвиги, отбор признаков (оценки + матрица), стратегия валидации, матрица моделей, паспорт + сравнение |
| modeling | 6 | Workflow-таблицы, трассируемость, backtest comparison/OOF, панельные метрики, residual diagnostics (`not_mounted`) |
| forecasting | 6 | Chart прогноза, панельные chart+таблица, legacy PNG (`legacy_client`), accuracy, D12-сверка |
| tasks | 1 | XAI «Причины» (fold-importance) |
| **Итого** | **89** | 8 модулей, 5 renderer_kind, 3 export_status |

Renderer kind'ы: `recharts_svg` (графики Recharts), `html_table` (научные таблицы), `html_heatmap` (CSS color-scale матрицы: пропуски, спектр, отбор признаков), `html_cards` (научные метрики/карточки), `mixed` (комбинации). Export status: `planned` (87, адаптеры PGV-03/04/13), `legacy_client` (1 — ForecastExportMenu, переезд PGV-12), `not_mounted` (1 — ResidualDiagnosticsPanel, честная маркировка несмонтированного компонента).

Связность с UI: `stop_id` трёх обзорных этапов (validation/preprocessing/eda) сверяется оракулом с пунктами `navigator-stops.ts` (источник истины «id совпадает с CHECK_META/CHECKS»), Навигатора — со схемой `<stage>.<item>` по всем пунктам; upload — с ветками `activeStop` модуля; modeling/forecasting/tasks — с каталогом остановок реестра.

## 4. Явные исключения (9 групп, с причинами)

| Класс | Файлы | Причина |
|---|---|---|
| `decorative` | HomeWavesBackground, NavigatorWavesBackground, DocumentationWavesBackground, NavigatorHero, HomeFooter | Декоративные волны/герой/футер — иллюстрации интерфейса без научных данных (spec §1) |
| `ops_admin` | AdminLogsDashboard | Операционные таблицы журналов/аудита администратора (DOCLOG-7) — не научные визуализации |
| `controls` | DocumentationWorkspace | Каталог/контролы «Документов»; научное содержимое — зарегистрированная панель D12; печатная композиция — DOCLOG-конвейер |
| `interactive_editor` | PreprocessingMissingManualEditor, PreprocessingOutliersManualEditor, DatasetViewEditor | Интерактивные редакторы данных — инструмент ввода, не печатная визуализация |
| `operational_list` | ForecastHistoryList | Операционная история forecast-заданий; научное содержимое зарегистрировано отдельно |
| `placeholder_soon` | ModulePlaceholder | Placeholder-маршруты «Скоро» (spec §1) |
| `controls` | `*Pipeline.tsx` (glob, 20 файлов) | Мастера коррекций/описания методик — контролы; графики рендерят зарегистрированные Обзоры |

Появление графика в любом исключённом файле ловится pattern-сканом как **unknown site** и блокирует тест (проверено негативным контролем: временный файл с recharts+table → тест падает с точным указанием файла и паттернов).

## 5. Coverage-оракул: как «unknown site блокирует CERT»

`visualExportRegistry.coverage.test.ts` (16 тестов, GREEN; jest):

1. **Интегрити:** схема записи, уникальность `view_id`, каталоги остановок (со сверкой `navigator-stops.ts`), честность `export_status` (legacy_client/not_mounted — ровно известные записи), существование всех файлов на диске, пин «D01–D12 не переименовываются».
2. **Pattern-скан** (spec §5 «вспомогательный oracle»): 6 паттернов (`from "recharts"`, `<svg`, `<canvas`, `<table`, `linear-gradient(`, вычисляемый `backgroundColor:`) по `packages/ui/components` + страницам обоих apps. Базлайн — **58 файлов**; каждый совпавший обязан быть в реестре или исключениях; пин ≥58 + полная классификация.
3. **Семейные правила:** `Navigator*Preview`, `Eda*Overview`, `Validation*Overview`, `Preprocessing*Overview`, `Preprocessing*Visualizations` — покрыты целиком (закрывает слепую зону паттернов для grid/card-превью без recharts/таблиц).
4. **Пины denominator:** точный состав по модулям (14/12/12/20/18/6/6/1 = 89) — удаление записи или исключения падает.
5. **Паритет TS⇄JSON:** `config/visual_registry.json` — структурно честный твин (паттерн EDU-API-1).

Негативный контроль (выполнен): временный `FakeFutureChart.tsx` с recharts+table → 2 теста падают (`unknown` список содержит файл; baseline 58→59), после удаления — 16/16. RED-история: оракул написан до реестра и падал `TS2307 Cannot find module './visualExportRegistry'` (честный collection RED).

## 6. Приёмочные сценарии — вклад PGV-00

| Сценарий | Вклад этой задачи |
|---|---|
| PGV-AC03 (каждый применимый site имеет PNG action и frozen-data oracle) | Полный denominator закреплён: 89 записей; action/oracle — PGV-03/09/10…12 |
| PGV-AC02 (IH HTML-матрица печатается полностью) | `eda.ih.conditional_map` зарегистрирован как `html_table` с пометкой «SVG-only сериализация не подходит» |
| PGV-AC22 (D01–D12/legacy сохраняются) | Пин «реестр не вводит document-kinds»; legacy PNG — единственная `legacy_client` запись с планом PGV-12 |
| PGV-AC11/AC12 (reused checkpoint, gaps) | Паспортные записи требуют `snapshot_id/schema_version` refs; checkpoint-семантика — PGV-04 |
| PGV-AC14 (panel не смешивается) | Панельные записи (`modeling.panel.metrics`, `forecasting.forecast.panel_*`) помечены `applicability: panel` + `entity_column` refs |
| PGV-AC17 (missing dependency честен) | `not_mounted` запись ResidualDiagnosticsPanel — образец честной маркировки отсутствующей поверхности |

## 7. Метод исследования и ограничения

Инвентарь построен read-only исследованием кода: grep-сканы recharts/svg/canvas/table/heatmap-паттернов, разбор веток рендера (`activeStop`/`activeCheckId`/субвиды ExpandableChartPanel), сверка с реестрами остановок (`navigator-stops.ts`, `CHECK_META`/`CHECKS`) и точками монтажа (`TsAnalysis*` оркестраторы, страницы apps). Каждый классификационный спор решён по правилам spec §1: научные данные → реестр; декор/опс/контролы/редакторы → исключение с причиной. Полный jest-регресс 2421/2421 (222 сюиты, 0 failed), `check_documents.py` GREEN 335/335.

Ограничения: реестр фиксирует файлы/ветки рендера, но не пиксельные композиции печатных форм (PGV-01/07); точность `view_params`/`required_refs` — проектная (уточняется PGV-01); браузерная приёмка и живой рендер — вне PGV-00; `applicability` отражает текущую логику UI (панельные ветки), а не будущую матрицу применимости PGV-10…12.
