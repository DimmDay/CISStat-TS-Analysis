# Аудит захардкоженных строковых констант базы знаний (по каждому узлу)

**Платформа:** CISStat TS Analysis · **Синхронизация:** `main` @ `63c3f0c` (Task EDU-API-1) · **Дата:** 2026-09-22
**Режим:** аудит, без изменения кода. Метод: чтение репозитория + скриптовый скан строковых литералов (кириллица ≥40 симв. в .ts/.tsx, ≥60 симв. в .py; тесты и сгенерированные артефакты исключены).

---

## 1. Резюме

Проверены оба тезиса постановки тимлида о «захардкоженной ранее базе знаний». Тезис **(а) подтверждён**: весь контент слоя знаний живёт в коде репозитория — источником истины остаётся TS-реестр фронта (`packages/ui/lib/knowledge/`), а backend (`apps/api/knowledge/registry_data.json`, появившийся в `63c3f0c`) — генерируемая копия того же контента, тоже лежащая в git. Управляемого хранилища (СУБД/редакционного контура) в платформе нет вообще — ни для знаний, ни для чего-либо ещё. Тезис **(б) подтверждён с уточнением**: для 77 записей справки окна «Описание» физический вынос текстов из `.tsx` выполнен (старые константы удалены, греп-проверка это подтверждает), но связь с `.tsx` сохранена трижды — поле `superseded_constant` в каждой записи, паритет-фикстура байт-в-байт, снятая с кода до миграции, и компиляция реестра в фронтовый бандл. Одновременно вне окна «Описание» существует второй эшелон захардкоженного узлового контента: мета-описания 49 узлов в массивах `CHECK_META`/`CHECKS`/`STOPS`, порядка 60 узловых компонентов `*Pipeline/*Overview/*Preview`, динамически собираемые тексты справки Моделирования, плюс крупный знаниеподобный контент в lib-файлах вне слоя знаний (`applied-tasks.ts`, `navigator-stops.ts`) и в Python-коде API (~52 тыс. символов интерпретаций и рекомендаций).

Совокупный объём методологического текста, привязанного к коду, — **порядка 305 тыс. символов** в четырёх несводимых друг с другом слоях (TS-реестр, .tsx-остатки, lib-файлы, Python). Для RAGFlow/курса/аналитики контент стал доступнее (открытый API из `63c3f0c`), но источник истины остался во фронтовом бандле, а API не отдаёт справочный корпус списком и не содержит ни версий, ни метаданных ревью, ни телеметрии.

---

## 2. Что изменилось синхронизацией до 63c3f0c

Между предыдущей точкой работы `074c6d8` и `63c3f0c` апстрим получил два коммита:

| Коммит | Суть | Отношение к аудиту |
|--------|------|--------------------|
| `917ae45` NAVDET-DATATYPES | Новый компонент `NavigatorValidationDataTypesPreview.tsx` (495 строк) + правки `TsAnalysisNavigator.tsx` | Добавил новый узел с захардкоженным текстом: 1 490 симв. кириллицы в самом компоненте |
| `63c3f0c` EDU-API-1 | Backend-промоушен слоя знаний: `apps/api/knowledge/` (роутер, реестр, JSON-артефакт, 440 строк тестов) | Создал вторую копию контента (JSON в репо) и открытый API; **источник истины не сменился** |

Локальные незакоммиченные наработки прошлой сессии (своя реализация Шага 4) сохранены в stash `wip-shag4-knowledge-before-sync-63c3f0c` и перекрыты апстримной реализацией; рабочее дерево чистое.

---

## 3. Инвентарь слоя знаний (централизованный реестр)

Источник истины — TS-файлы в `packages/ui/lib/knowledge/`; backend читает их механическую копию. Паритет байт-в-байт застрахован тестом (фикстура `help-parity.fixture.json`: 77 записей, 100 952 симв. — идентична реестру) и генератором `scripts/promote_knowledge_registry.test.ts` (запуск с `PROMOTE_KNOWLEDGE=1`; JSON помечен «НЕ редактировать вручную»).

| Реестр | Носитель (источник истины) | Записей | Объём текста | Копия в backend |
|--------|---------------------------|--------:|-------------:|-----------------|
| Справка узлов (`help.ts`) | TS, компилируется в бандл | 77 | 100 952 симв. | `registry_data.json` (291,5 КБ целиком) |
| Статьи Библиотеки (`articles.ts`) | TS, компилируется в бандл | 13 (12 published + 1 draft) | 16 849 симв. (body_md) | та же копия |
| Словарь (`glossary.ts`) | TS, компилируется в бандл | 28 | 7 121 симв. | та же копия |
| **Итого по реестру** | — | **118** | **124 922 симв.** | дублируется 1:1 |

Разрез справки по стадиям: preprocessing — 21 запись / 39 962 симв.; eda — 21 / 32 224; validation — 21 / 20 561; modeling — 12 / 6 145; forecasting — 2 / 2 060; **upload — 0** (этап не участвует в реестре справки). Разрез по граням: metrics — 30, pipeline — 30, stage_overview — 12, module_help — 5.

---

## 4. Пер-узловая карта: где лежит текст каждого узла

Полный список 77 записей реестра — Приложение А; сводная матрица ниже. Колонки: покрытие реестром и захардкоженные остатки в коде компонентов.

| Стадия | Узлов | Реестр: записей | Реестр: символов | Остаток в .tsx: мета-массивы узлов | Остаток в .tsx: узловые компоненты |
|--------|------:|----------------:|-----------------:|------------------------------------|------------------------------------|
| upload | 5 | **0** | 0 | `STOPS`: 957 симв. | Navigator*Preview (11 файлов): 4 441 симв. |
| validation | 10 | 21 | 20 561 | `CHECK_META`: 1 903 симв. (10×~190) | Validation*Pipeline/Overview (18 файлов): 14 981 симв. |
| preprocessing | 10 | 21 | 39 962 | `CHECKS`: 1 957 симв. | Preprocessing*Pipeline/Overview/Visualizations (23 файла): 16 230 симв. |
| eda | 10 | 21 | 32 224 | `CHECKS`: 2 573 симв. | Eda*Overview (10 файлов): 6 886 симв. |
| modeling | 11 стадий | 12 | 6 145 | динамические шаблоны: 12 литерала / 2 577 симв. | ModelingWorkflowOverview: 980 симв. |
| forecasting | 4 шага | 2 | 2 060 | `STEP_LABELS`: 58 симв. | TsAnalysisForecasting: 459 симв. |

Чтение матрицы по каждому узлу:

- **Окно «Описание»** (секции «Метрики и алгоритм» / «Полный пайплайн» / «Справка» / описание стадии) — единственное место, где узлы validation/preprocessing/eda/modeling/forecasting рендерят текст из реестра, через `describeNode(stage_id, node_id, facet)`. Вызовы `describeNode` с захардкоженными ключами сидят в 5 модулях `TsAnalysis*.tsx`.
- **Тот же узел в остальных поверхностях** — текст захардкожен: мета-массивы (описание остановки в степпере/навигаторе, ~150–260 символов на узел) и узловые компоненты (`ValidationTextQualityPipeline.tsx` — 2 048 симв., `PreprocessingStationarityPipeline.tsx` — 1 951, `PreprocessingSpectralOverview.tsx` — 1 808 и т.д. — пояснения операций, интерпретации, подписи).
- **Узлы upload** — полностью вне реестра: их методологические описания живут в `STOPS` и в компонентах предпросмотра Навигатора, включая свежий `NavigatorValidationDataTypesPreview.tsx` из `917ae45`.
- **Динамические тексты Моделирования** — справка «Метрики и алгоритм: ${model_name}…» собирается в рантайме из шаблонных строк, зашитых в `TsAnalysisModeling.tsx` (12 шаблонов, 2 577 симв. фиксированной методологической обвязки, включая формулировку «24 правила (5 forbidden, 7 discouraged…)»). Архдок (§2.5) классифицирует их как «факты рантайма, не методология», однако фиксированная часть шаблонов — методологична и реестром не управляется.
- **Динамические тексты Forecasting** — аналогично: 4 шаблона/459 симв. (подписи запусков, сравнений).

Суммарно мета-массивы + шаблоны: **49 узлов, 7 448 симв.** плюс **~10 026 симв.** динамических шаблонов двух модулей; узловые компоненты всех групп: **62 файла, ~42 538 симв.**

---

## 5. Знаниеподобный контент вне слоя знаний

| Слой | Файлы | Объём | Природа |
|------|-------|------:|---------|
| Контент прикладных задач хаба | `packages/ui/lib/applied-tasks.ts` | 26 814 симв. (284 литерала) | Методологические описания задач — потенциальный контур курса/RAGFlow, вне реестра |
| Описания остановок Навигатора | `packages/ui/lib/navigator-stops.ts` | 8 555 симв. (84 id) | Узловые тексты платформенного навигатора, дублируют тематику справки |
| Прочие lib | `structuralClass.ts` (1 672), `task-stops.ts` (626), `demoDatasets.ts` (401) | 2 699 симв. | Тексты классификаций и демо-материалов |
| Страница «Путь продукта» | `apps/standalone/components/ProductJourneyGuide.tsx` | 2 759 симв. | Нарратив платформы в компоненте |
| Панели служебных знаний | `RulesManagementPanel.tsx` (1 126), `DatasetPassportPanel.tsx` (996), `ModelingWorkflowOverview.tsx` (980) | 3 102 симв. | Пояснения правил Наставника, паспорта данных |
| **Python-сторона API** | 77 файлов `apps/api/*.py` | **52 035 симв.** (713 литералов ≥60) | Интерпретации находок, рекомендации, формулировки правил — третья копия методологии, вне реестра (топ: `routers/session.py` 4 391, `schemas.py` 4 096, `routers/modeling_session.py` 2 861, `preprocessing_stationarity.py` 2 316, `feature_plan.py` 2 189) |

Отдельно: словари этапов и направлений (`STAGE_LABELS_RU`, `DIRECTION_LABELS_RU`, `DIRECTION_DESCRIPTIONS_RU` в `types.ts`) продублированы в JSON-артефакте (`stage_labels_ru`, `direction_labels_ru`) — словарная гармонизация тоже живёт в коде, синхронизируемая генератором.

Итого по всем слоям, привязанным к коду: **≈ 305 тыс. символов** (реестр 125 К + .tsx-остатки 69 К + lib вне слоя 38 К + Python 52 К + служебные панели ~8 К + словари).

---

## 6. Тезис (а): «в коде, а не в управляемом хранилище» — ПОДТВЕРЖДЁН

1. **Источник истины — файл исходников фронта.** `registry_data.json` прямо декларирует: «TS-реестры — единый источник истины; промоушен без перенабора контента», а `registry.py` — что модуль backend «НЕ содержит методологических текстов» и загружает артефакт. Правка любого текста = правка `.ts` файла, перегенерация через jest и коммит.
2. **БД в платформе нет.** В `apps/api` отсутствуют sqlalchemy/alembic/psycopg/sqlite/CREATE TABLE; состояние сессий — файловое JSON. Целевое состояние спеки (`spec_education.md`, Часть II prerequisites: «KnowledgeArticle, Citation… — та же СУБД, что уже выбрана для research_runs/trace_events») не реализовано; выбор СУБД в апстриме остаётся открытым вопросом.
3. **Две копии в одном репозитории.** Контент существует синхронно в TS (бандл фронта, деплой Vercel) и JSON (Docker backend, деплой Render). Рассинхронизация между копиями исключена механически (тест-генератор в общем прогоне), но публикация одной правки требует прохождения обеих пайплайнов.
4. **Признаки управляемого хранилища отсутствуют.** Нет редакционного контура: `last_reviewed_at` не заполнен ни у одной из 13 статей; у 77 справочных записей нет ни версий, ни авторов, ни дат ревью, ни статусов (все неявно published), ни направлений (пусто по построению промоушена). Draft-механика есть только у библиотечных статей (1 из 13). Черновики, очереди ревью, журналирование правок — отсутствуют как класс.
5. Уточнение к тезису: требование архдока «контент живёт в управляемом реестре, а не в коде компонентов» выполнено **наполовину** — «не в коде компонентов» да (для окна «Описание»), но сам «управляемый реестр» пока является кодом.

## 7. Тезис (б): «содержимое привязано к конкретному .tsx-файлу» — ПОДТВЕРЖДЁН (в трёх смыслах)

1. **Аудит-поля происхождения.** Каждая из 77 записей несёт `superseded_constant` вида `TsAnalysisEDA.tsx::CORRELATION_METRICS_DESCRIPTION` — контент семантически адресуется через исходный `.tsx`.
2. **Паритет-фикстура** (`help-parity.fixture.json`, 189 КБ) — байт-в-байт оракул, снятый с кода до миграции: любое редактирование текста ломает тест, то есть эволюция контента заблокирована исторической формой `.tsx`-констант (вербатим-текст с `\n`, под whitespace-pre-wrap рендер).
3. **Рендер из бандла.** Реестр экспортируется из `@cisstat/ui` (`index.ts`: `KNOWLEDGE_HELP_ENTRIES`, `KNOWLEDGE_ARTICLES`, `GLOSSARY_TERMS` и типы) и компилируется в JS-бандл standalone/embedded. Потребитель вне фронта (курс, RAGFlow, аналитика) не может обратиться к контенту иначе как через новый backend API или парсинг репозитория/бандла.
4. **Второй эшелон — прямая привязка.** Мета-массивы 49 узлов, ~60 узловых компонентов, динамические шаблоны Моделирования, `applied-tasks.ts`/`navigator-stops.ts` и Python-интерпретации — по-прежнему буквально «содержимое внутри кода компонента/модуля вычислений», для них миграция ещё не проводилась (§16 спеки: Этап 1 охватил только константы окна «Описание»).

## 8. Доступность для RAGFlow / курса / аналитики

Что появилось в `63c3f0c` (открытые эндпоинты, без авторизации — образование вне тарифов по §7.2 спеки):

- `GET /v1/knowledge/articles` — Библиотека списком (published, порядок пайплайна) **или** статья по ключу узла `(stage_id, node_id, facet)` с честным `null` «справка готовится»;
- `GET /v1/knowledge/glossary?stage_id=` — словарь;
- `POST /v1/learning/track {"directions":[…]}` — обучающий стек (§2.2, семантика 1:1 с фронтом).

Чего по-прежнему нет для внешних потребителей:

1. **Перечисление справочного корпуса.** Списковый режим отдаёт только библиотечные статьи (facet=library); 77 справочных записей адресуются только точным ключом, а словарь валидных ключей наружу не выдан — для полного обхода корпуса нужно знать `node_id` всех узлов из кода фронта.
2. **Поиск.** Полный текстовый поиск (`searchKnowledge`) существует только на фронте; REST-аналога нет.
3. **Метаданные для курирования и аналитики.** Ни версий/дату ревью у справки, ни направлений у справочных записей (RAGFlow-чанкинг по методологическим осям §2.2 невозможен без тегов), ни счётчиков использования: телеметрия Q/ΔQ (точки `describeNode` и `openArticleFromAnywhere`) спроектирована, но не встроена.
4. **Событие публикации.** По спеке RAGFlow переиндексируется по событию `draft → published`; сейчас статусы живут только в TS-файле, событие возникать неоткуда.
5. **Курс** (§7 спеки) не начат — единственный его источник контента сегодня был бы тем же TS-реестром.

Практический вывод: реалистичный путь индексации RAGFlow сейчас — чтение `registry_data.json` из репозитория (или парсинг бандла), то есть ровно то состояние «в коде», от которого постановка предлагает уйти.

## 9. Оценка риска

| Риск | Серьёзность | Комментарий |
|------|------------|-------------|
| Расхождение копий контента при человеческой правке JSON напрямую | Средняя (сейчас закрыта тестом) | Единственный барьер — jest-тест в общем прогоне; вне CI барьера нет |
| Двойной деплой одной правки текста (Vercel + Render) | Средняя | Удорожает каждое изменение методологии, создаёт окно рассогласования фронт/бэк |
| Расползание второго эшелона (узловые компоненты, Python) | Высокая | ~120 К символов методологии вне реестра продолжают расти (пример: `917ae45` добавил 1 490 симв. в новый компонент) — каждый новый узел воспроизводит антипаттерн |
| Блокировка эволюции текста паритет-фикстурой | Средняя | Любая редактура методологии = переснятие оракула; механика переснятия не формализована как редакторский процесс |
| Тираж знаний в RAGFlow/курс/аналитику | Высокая | Без управляемого хранилища и API перечисления контент недоступен потребителям спеки §4.1/§7 |
| Отсутствие авторства/версий/ревью | Средняя | Методологическая ответственность неотслеживаема; `last_reviewed_at` — пустое поле без владельца |

## 10. Рекомендации (без кода, порядок по приоритету)

1. **Инверсия источника истины (ключевое).** Сделать backend-хранилище (СУБД из открытого вопроса `spec_progress.md` — тот же выбор, что для `research_runs`/`trace_events`) первичным носителем `KnowledgeArticle`/`GlossaryTerm`/справки; TS-реестр — либо кэшем сборки, либо генерируемым типизированным клиентом. Это закрывает тезис (а) и разворачивает направление промоушена: не «фронт → бэк», а «бэк → фронт».
2. **Административный контур поверх хранилища:** версии, автор, `last_reviewed_at`, статусный переход draft → published как событие (для RAGFlow-триггера §5.1), очереди ревью по §6.2 спеки. Пока контент в git, этот контур строить не на чем.
3. **Дорасширение API для внешних потребителей:** перечисление всего корпуса (включая 77 справочных записей) с пагинацией, полнотекстовый поиск (REST-аналог `searchKnowledge`), выдача словаря ключей узлов; затем — батч-экспорт для RAGFlow по событию публикации.
4. **Довыравнивание узлов.** Перенести в реестр мета-описания 49 узлов (`CHECK_META`/`CHECKS`/`STOPS`/`STEP_LABELS`) и фиксированную обвязку динамических шаблонов Моделирования/Прогнозирования — с фасетом уровня «карточка узла» отдельно от окна «Описание»; подключить этап upload к реестру (сейчас 0 записей при 5 узлах и контенте в Навигаторе).
5. **Второй контур промоушена:** `applied-tasks.ts` (26,8 К), `navigator-stops.ts` (8,6 К) и Python-интерпретации (52 К) — сформировать как записи реестра с типом «интерпретация вычисления», чтобы методология перестала дублироваться в трёх слоях кода.
6. **Правило для новых задач:** запрет добавлять методологические тексты в `.tsx`/`.py` вне реестра (греп-инвариант расширить с констант окна «Описание» на длинные кириллические литералы узловых компонентов) — иначе третий эшелон воспроизведётся в каждой новой фиче.
7. **Телеметрия Q/ΔQ** (Этап 5): встроить показы в `describeNode` и `openArticleFromAnywhere` одновременно с переездом контента — на хранилище это ложится естественно (event → статья по id).

---

## Приложения

Приложения А (все 77 записей реестра по узлам), А-2 (матрица «узел → носитель»), Б (топ-30 .tsx файлов по объёму кириллицы), Б-2 (lib-файлы), В (топ-15 Python-файлов) — в файле отчёта `audit_hardcoded_kb_63c3f0c_2026-09-22.md`, выложенном в download-контейнер сессии.
### Приложение А. Реестр справки: все 77 записей по узлам

Каждая запись: ключ (stage_id, node_id, facet), объём текста, файл-происхождение (superseded_constant).

| # | entry_id | stage | node | facet | симв. | происхождение (.tsx-константа) |
|---|----------|-------|------|-------|------:|--------------------------------|
| 1 | `eda.module.module_help` | eda | — (модуль) | module_help | 1991 | `TsAnalysisEDA.tsx::EDA_HELP` |
| 2 | `eda.correlation.metrics` | eda | correlation | metrics | 1284 | `TsAnalysisEDA.tsx::CORRELATION_METRICS_DESCRIPTION` |
| 3 | `eda.correlation.pipeline` | eda | correlation | pipeline | 1356 | `TsAnalysisEDA.tsx::CORRELATION_PIPELINE_DESCRIPTION` |
| 4 | `eda.descriptive.metrics` | eda | descriptive | metrics | 1530 | `TsAnalysisEDA.tsx::DESCRIPTIVE_METRICS_DESCRIPTION` |
| 5 | `eda.descriptive.pipeline` | eda | descriptive | pipeline | 1222 | `TsAnalysisEDA.tsx::DESCRIPTIVE_PIPELINE_DESCRIPTION` |
| 6 | `eda.distribution.metrics` | eda | distribution | metrics | 1766 | `TsAnalysisEDA.tsx::DISTRIBUTION_METRICS_DESCRIPTION` |
| 7 | `eda.distribution.pipeline` | eda | distribution | pipeline | 1395 | `TsAnalysisEDA.tsx::DISTRIBUTION_PIPELINE_DESCRIPTION` |
| 8 | `eda.feature_select.metrics` | eda | feature_select | metrics | 1374 | `TsAnalysisEDA.tsx::FEATURE_SELECTION_METRICS_DESCRIPTION` |
| 9 | `eda.feature_select.pipeline` | eda | feature_select | pipeline | 552 | `TsAnalysisEDA.tsx::FEATURE_SELECTION_PIPELINE_DESCRIPTION` |
| 10 | `eda.ih_analysis.metrics` | eda | ih_analysis | metrics | 1996 | `TsAnalysisEDA.tsx::IH_METRICS_DESCRIPTION` |
| 11 | `eda.ih_analysis.pipeline` | eda | ih_analysis | pipeline | 1630 | `TsAnalysisEDA.tsx::IH_PIPELINE_DESCRIPTION` |
| 12 | `eda.model_matrix.metrics` | eda | model_matrix | metrics | 2014 | `TsAnalysisEDA.tsx::MODEL_MATRIX_METRICS_DESCRIPTION` |
| 13 | `eda.model_matrix.pipeline` | eda | model_matrix | pipeline | 1050 | `TsAnalysisEDA.tsx::MODEL_MATRIX_PIPELINE_DESCRIPTION` |
| 14 | `eda.seasonality.metrics` | eda | seasonality | metrics | 1876 | `TsAnalysisEDA.tsx::SEASONALITY_METRICS_DESCRIPTION` |
| 15 | `eda.seasonality.pipeline` | eda | seasonality | pipeline | 1574 | `TsAnalysisEDA.tsx::SEASONALITY_PIPELINE_DESCRIPTION` |
| 16 | `eda.stationarity.metrics` | eda | stationarity | metrics | 2179 | `TsAnalysisEDA.tsx::STATIONARITY_METRICS_DESCRIPTION` |
| 17 | `eda.stationarity.pipeline` | eda | stationarity | pipeline | 1818 | `TsAnalysisEDA.tsx::STATIONARITY_PIPELINE_DESCRIPTION` |
| 18 | `eda.structural.metrics` | eda | structural | metrics | 1634 | `TsAnalysisEDA.tsx::STRUCTURAL_METRICS_DESCRIPTION` |
| 19 | `eda.structural.pipeline` | eda | structural | pipeline | 1501 | `TsAnalysisEDA.tsx::STRUCTURAL_PIPELINE_DESCRIPTION` |
| 20 | `eda.validation_strategy.metrics` | eda | validation_strategy | metrics | 1437 | `TsAnalysisEDA.tsx::VALIDATION_STRATEGY_METRICS_DESCRIPTION` |
| 21 | `eda.validation_strategy.pipeline` | eda | validation_strategy | pipeline | 1045 | `TsAnalysisEDA.tsx::VALIDATION_STRATEGY_PIPELINE_DESCRIPTION` |
| 22 | `forecasting.module.module_help` | forecasting | — (модуль) | module_help | 1237 | `TsAnalysisForecasting.tsx::FORECASTING_HELP` |
| 23 | `forecasting.module.stage_overview` | forecasting | — (модуль) | stage_overview | 823 | `TsAnalysisForecasting.tsx::FORECASTING_DESCRIPTION` |
| 24 | `modeling.module.module_help` | modeling | — (модуль) | module_help | 1454 | `TsAnalysisModeling.tsx::MODELING_HELP` |
| 25 | `modeling.backtest.stage_overview` | modeling | backtest | stage_overview | 381 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.backtest` |
| 26 | `modeling.baseline_estimation.stage_overview` | modeling | baseline_estimation | stage_overview | 400 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.baseline_estimation` |
| 27 | `modeling.candidate_generation.stage_overview` | modeling | candidate_generation | stage_overview | 472 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.candidate_generation` |
| 28 | `modeling.comparison.stage_overview` | modeling | comparison | stage_overview | 446 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.comparison` |
| 29 | `modeling.constraint_mapping.stage_overview` | modeling | constraint_mapping | stage_overview | 445 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.constraint_mapping` |
| 30 | `modeling.data_structure.stage_overview` | modeling | data_structure | stage_overview | 425 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.data_structure` |
| 31 | `modeling.diagnostics.stage_overview` | modeling | diagnostics | stage_overview | 406 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.diagnostics` |
| 32 | `modeling.model_card.stage_overview` | modeling | model_card | stage_overview | 439 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.model_card` |
| 33 | `modeling.problem_definition.stage_overview` | modeling | problem_definition | stage_overview | 463 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.problem_definition` |
| 34 | `modeling.selection.stage_overview` | modeling | selection | stage_overview | 413 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.selection` |
| 35 | `modeling.tuning.stage_overview` | modeling | tuning | stage_overview | 401 | `TsAnalysisModeling.tsx::MODELING_STAGE_DESCRIPTIONS.tuning` |
| 36 | `preprocessing.module.module_help` | preprocessing | — (модуль) | module_help | 1650 | `TsAnalysisPreprocessing.tsx::PREPROCESSING_HELP` |
| 37 | `preprocessing.decomposition.metrics` | preprocessing | decomposition | metrics | 1854 | `TsAnalysisPreprocessing.tsx::DECOMPOSITION_METRICS_DESCRIPTION` |
| 38 | `preprocessing.decomposition.pipeline` | preprocessing | decomposition | pipeline | 935 | `TsAnalysisPreprocessing.tsx::DECOMPOSITION_PIPELINE_DESCRIPTION` |
| 39 | `preprocessing.feature_eng.metrics` | preprocessing | feature_eng | metrics | 2988 | `TsAnalysisPreprocessing.tsx::FEATURE_ENGINEERING_METRICS_DESCRIPTION` |
| 40 | `preprocessing.feature_eng.pipeline` | preprocessing | feature_eng | pipeline | 1183 | `TsAnalysisPreprocessing.tsx::FEATURE_ENGINEERING_PIPELINE_DESCRIPTION` |
| 41 | `preprocessing.missing.metrics` | preprocessing | missing | metrics | 2212 | `TsAnalysisPreprocessing.tsx::MISSING_METRICS_DESCRIPTION` |
| 42 | `preprocessing.missing.pipeline` | preprocessing | missing | pipeline | 1262 | `TsAnalysisPreprocessing.tsx::MISSING_PIPELINE_DESCRIPTION` |
| 43 | `preprocessing.outliers.metrics` | preprocessing | outliers | metrics | 2863 | `TsAnalysisPreprocessing.tsx::OUTLIERS_METRICS_DESCRIPTION` |
| 44 | `preprocessing.outliers.pipeline` | preprocessing | outliers | pipeline | 1360 | `TsAnalysisPreprocessing.tsx::OUTLIERS_PIPELINE_DESCRIPTION` |
| 45 | `preprocessing.regularity.metrics` | preprocessing | regularity | metrics | 2623 | `TsAnalysisPreprocessing.tsx::REGULARITY_METRICS_DESCRIPTION` |
| 46 | `preprocessing.regularity.pipeline` | preprocessing | regularity | pipeline | 1266 | `TsAnalysisPreprocessing.tsx::REGULARITY_PIPELINE_DESCRIPTION` |
| 47 | `preprocessing.scaling.metrics` | preprocessing | scaling | metrics | 3172 | `TsAnalysisPreprocessing.tsx::SCALING_METRICS_DESCRIPTION` |
| 48 | `preprocessing.scaling.pipeline` | preprocessing | scaling | pipeline | 1232 | `TsAnalysisPreprocessing.tsx::SCALING_PIPELINE_DESCRIPTION` |
| 49 | `preprocessing.smoothing.metrics` | preprocessing | smoothing | metrics | 3073 | `TsAnalysisPreprocessing.tsx::SMOOTHING_METRICS_DESCRIPTION` |
| 50 | `preprocessing.smoothing.pipeline` | preprocessing | smoothing | pipeline | 856 | `TsAnalysisPreprocessing.tsx::SMOOTHING_PIPELINE_DESCRIPTION` |
| 51 | `preprocessing.spectral.metrics` | preprocessing | spectral | metrics | 3139 | `TsAnalysisPreprocessing.tsx::SPECTRAL_METRICS_DESCRIPTION` |
| 52 | `preprocessing.spectral.pipeline` | preprocessing | spectral | pipeline | 1169 | `TsAnalysisPreprocessing.tsx::SPECTRAL_PIPELINE_DESCRIPTION` |
| 53 | `preprocessing.stationarity.metrics` | preprocessing | stationarity | metrics | 3079 | `TsAnalysisPreprocessing.tsx::STATIONARITY_METRICS_DESCRIPTION` |
| 54 | `preprocessing.stationarity.pipeline` | preprocessing | stationarity | pipeline | 1280 | `TsAnalysisPreprocessing.tsx::STATIONARITY_PIPELINE_DESCRIPTION` |
| 55 | `preprocessing.variance_stab.metrics` | preprocessing | variance_stab | metrics | 1844 | `TsAnalysisPreprocessing.tsx::VARIANCE_METRICS_DESCRIPTION` |
| 56 | `preprocessing.variance_stab.pipeline` | preprocessing | variance_stab | pipeline | 922 | `TsAnalysisPreprocessing.tsx::VARIANCE_PIPELINE_DESCRIPTION` |
| 57 | `validation.module.module_help` | validation | — (модуль) | module_help | 1705 | `TsAnalysisValidation.tsx::DQ_STANDARDS_HELP` |
| 58 | `validation.consistency.metrics` | validation | consistency | metrics | 1485 | `TsAnalysisValidation.tsx::CONSISTENCY_METRICS_DESCRIPTION` |
| 59 | `validation.consistency.pipeline` | validation | consistency | pipeline | 755 | `TsAnalysisValidation.tsx::CONSISTENCY_PIPELINE_DESCRIPTION` |
| 60 | `validation.data_types.metrics` | validation | data_types | metrics | 1802 | `TsAnalysisValidation.tsx::DATA_TYPES_METRICS_DESCRIPTION` |
| 61 | `validation.data_types.pipeline` | validation | data_types | pipeline | 457 | `TsAnalysisValidation.tsx::DATA_TYPES_PIPELINE_DESCRIPTION` |
| 62 | `validation.formats.metrics` | validation | formats | metrics | 1032 | `TsAnalysisValidation.tsx::FORMATS_METRICS_DESCRIPTION` |
| 63 | `validation.formats.pipeline` | validation | formats | pipeline | 526 | `TsAnalysisValidation.tsx::FORMATS_PIPELINE_DESCRIPTION` |
| 64 | `validation.inclusion.metrics` | validation | inclusion | metrics | 1061 | `TsAnalysisValidation.tsx::INCLUSION_METRICS_DESCRIPTION` |
| 65 | `validation.inclusion.pipeline` | validation | inclusion | pipeline | 592 | `TsAnalysisValidation.tsx::INCLUSION_PIPELINE_DESCRIPTION` |
| 66 | `validation.ranges.metrics` | validation | ranges | metrics | 1300 | `TsAnalysisValidation.tsx::RANGES_METRICS_DESCRIPTION` |
| 67 | `validation.ranges.pipeline` | validation | ranges | pipeline | 631 | `TsAnalysisValidation.tsx::RANGES_PIPELINE_DESCRIPTION` |
| 68 | `validation.referential.metrics` | validation | referential | metrics | 1256 | `TsAnalysisValidation.tsx::REFERENTIAL_METRICS_DESCRIPTION` |
| 69 | `validation.referential.pipeline` | validation | referential | pipeline | 629 | `TsAnalysisValidation.tsx::REFERENTIAL_PIPELINE_DESCRIPTION` |
| 70 | `validation.regularity.metrics` | validation | regularity | metrics | 1083 | `TsAnalysisValidation.tsx::REGULARITY_METRICS_DESCRIPTION` |
| 71 | `validation.regularity.pipeline` | validation | regularity | pipeline | 673 | `TsAnalysisValidation.tsx::REGULARITY_PIPELINE_DESCRIPTION` |
| 72 | `validation.sufficiency.metrics` | validation | sufficiency | metrics | 1134 | `TsAnalysisValidation.tsx::SUFFICIENCY_METRICS_DESCRIPTION` |
| 73 | `validation.sufficiency.pipeline` | validation | sufficiency | pipeline | 632 | `TsAnalysisValidation.tsx::SUFFICIENCY_PIPELINE_DESCRIPTION` |
| 74 | `validation.text_quality.metrics` | validation | text_quality | metrics | 1175 | `TsAnalysisValidation.tsx::TEXT_QUALITY_METRICS_DESCRIPTION` |
| 75 | `validation.text_quality.pipeline` | validation | text_quality | pipeline | 691 | `TsAnalysisValidation.tsx::TEXT_QUALITY_PIPELINE_DESCRIPTION` |
| 76 | `validation.uniqueness.metrics` | validation | uniqueness | metrics | 1212 | `TsAnalysisValidation.tsx::UNIQUENESS_METRICS_DESCRIPTION` |
| 77 | `validation.uniqueness.pipeline` | validation | uniqueness | pipeline | 730 | `TsAnalysisValidation.tsx::UNIQUENESS_PIPELINE_DESCRIPTION` |

### Приложение А-2. Сводная матрица «узел → где лежит его текст»

| Стадия | Узлов | Записей справки (реестр) | Символов в реестре | Остаток в .tsx: мета-описания узлов | Остаток в .tsx: узловые компоненты |
|--------|------:|--------------------------:|-------------------:|------------------------------------:|-----------------------------------:|
| upload | 5 | 0 | 0 | STOPS: 957 симв. | Navigator*Preview: 4 441 симв. (11 файлов) |
| validation | 10 | 21 | 20 561 | CHECK_META: 1 903 симв. | Validation*Pipeline/Overview: 14 981 симв. (18 файлов) |
| preprocessing | 10 | 21 | 39 962 | CHECKS: 1 957 симв. | Preprocessing*Pipeline/Overview/Visual: 16 230 симв. (23 файла) |
| eda | 10 | 21 | 32 224 | CHECKS: 2 573 симв. | Eda*Overview: 6 886 симв. (10 файлов) |
| modeling | 11 | 12 | 6 145 | динам. шаблоны: 2 577 симв. | ModelingWorkflowOverview: 980 симв. |
| forecasting | 4 | 2 | 2 060 | STEP_LABELS: 58 симв. | TsAnalysisForecasting: 459 симв. |

### Приложение Б. .tsx-файлы: объём кириллических строковых литералов (≥40 симв.), топ-30

| Файл | Стат. литералов | Стат. симв. | Шаблонных | Шабл. симв. | Всего симв. |
|------|----------------:|------------:|----------:|------------:|------------:|
| `TsAnalysisPreprocessing.tsx` | 45 | 4 506 | 6 | 637 | 5 143 |
| `TsAnalysisEDA.tsx` | 25 | 3 231 | 17 | 1 451 | 4 682 |
| `TsAnalysisValidation.tsx` | 35 | 3 783 | 6 | 660 | 4 443 |
| `TsAnalysisModeling.tsx` | 14 | 782 | 12 | 2 577 | 3 359 |
| `ValidationTextQualityPipeline.tsx` | 21 | 1 993 | 1 | 55 | 2 048 |
| `PreprocessingStationarityPipeline.tsx` | 22 | 1 896 | 1 | 55 | 1 951 |
| `ValidationReferentialPipeline.tsx` | 21 | 1 833 | 1 | 55 | 1 888 |
| `ValidationInclusionPipeline.tsx` | 21 | 1 776 | 1 | 55 | 1 831 |
| `PreprocessingSpectralOverview.tsx` | 11 | 1 686 | 2 | 122 | 1 808 |
| `TsAnalysisUpload.tsx` | 9 | 1 294 | 6 | 506 | 1 800 |
| `ValidationRegularityPipeline.tsx` | 22 | 1 554 | 1 | 55 | 1 609 |
| `PreprocessingSpectralPipeline.tsx` | 15 | 1 536 | 1 | 55 | 1 591 |
| `NavigatorValidationDataTypesPreview.tsx` | 25 | 1 490 | 0 | 0 | 1 490 |
| `PreprocessingSmoothingPipeline.tsx` | 17 | 1 310 | 1 | 55 | 1 365 |
| `EdaStructuralBreaksOverview.tsx` | 10 | 1 168 | 2 | 94 | 1 262 |
| `PreprocessingScalingPipeline.tsx` | 13 | 1 196 | 1 | 66 | 1 262 |
| `EdaFeatureSelectionOverview.tsx` | 10 | 1 170 | 2 | 91 | 1 261 |
| `RulesManagementPanel.tsx` | 9 | 658 | 10 | 468 | 1 126 |
| `ValidationSufficiencyPipeline.tsx` | 15 | 1 070 | 1 | 55 | 1 125 |
| `PreprocessingVariancePipeline.tsx` | 13 | 985 | 1 | 55 | 1 040 |
| `DatasetPassportPanel.tsx` | 6 | 373 | 6 | 623 | 996 |
| `ModelingWorkflowOverview.tsx` | 13 | 920 | 1 | 60 | 980 |
| `ValidationUniquenessPipeline.tsx` | 12 | 918 | 1 | 55 | 973 |
| `PreprocessingFeatureEngineeringPipeline.tsx` | 9 | 865 | 1 | 70 | 935 |
| `EdaValidationStrategyOverview.tsx` | 7 | 827 | 2 | 85 | 912 |
| `PreprocessingRegularityPipeline.tsx` | 11 | 833 | 1 | 55 | 888 |
| `PreprocessingOutliersPipeline.tsx` | 11 | 817 | 1 | 55 | 872 |
| `EdaModelMatrixOverview.tsx` | 8 | 859 | 0 | 0 | 859 |
| `ValidationSufficiencyOverview.tsx` | 10 | 653 | 3 | 187 | 840 |
| `EdaStationarityOverview.tsx` | 6 | 508 | 6 | 330 | 838 |

**Суммарно по компонентам** (92 файла с литералами ≥40 симв.): статических 54 264 симв. + шаблонных 14 563 симв. = **68 827 симв.**

### Приложение Б-2. lib-файлы (packages/ui/lib)

| Файл | Символов (кириллица ≥40) | Роль |
|------|-------------------------:|------|
| `packages/ui/lib/knowledge/help.ts` | 101 767 | СЛОЙ ЗНАНИЙ — реестр справки (источник истины) |
| `packages/ui/lib/applied-tasks.ts` | 26 814 | ВНЕ слоя знаний — контент прикладных задач хаба |
| `packages/ui/lib/knowledge/articles.ts` | 20 266 | СЛОЙ ЗНАНИЙ — реестр статей (источник истины) |
| `packages/ui/lib/navigator-stops.ts` | 8 555 | ВНЕ слоя знаний — описания остановок Навигатора (84 id) |
| `packages/ui/lib/knowledge/glossary.ts` | 7 121 | СЛОЙ ЗНАНИЙ — реестр терминов (источник истины) |
| `packages/ui/lib/structuralClass.ts` | 1 672 | ВНЕ слоя знаний — структурные классы ряда (тексты) |
| `packages/ui/lib/capabilities.ts` | 1 009 | UI — описания тарифных capabilities |
| `packages/ui/lib/task-stops.ts` | 812 | ВНЕ слоя знаний — остановки задач |
| `packages/ui/lib/knowledge/types.ts` | 504 | СЛОЙ ЗНАНИЙ — контракты + RU-словари этапов/направлений |
| `packages/ui/lib/demoDatasets.ts` | 401 | ВНЕ слоя знаний — описания демо-датасетов |
| `packages/ui/lib/home-stops.ts` | 309 | — |
| `packages/ui/lib/tasks.ts` | 61 | — |
| `packages/ui/lib/plans.ts` | 60 | — |

### Приложение В. apps/api (Python): кириллические литералы ≥60 симв., топ-15

| Файл | Литералов | Символов | Пример |
|------|----------:|---------:|--------|
| `apps/api/routers/session.py` | 66 | 4 391 | Не позволяет старому решению скрыть изменившийся профиль ряд… |
| `apps/api/schemas.py` | 61 | 4 096 | Профиль dtype с результатом сверки с пользовательским эталон… |
| `apps/api/routers/modeling_session.py` | 40 | 2 861 | Modeling заблокирован критическими проверками; устраните при… |
| `apps/api/preprocessing_stationarity.py` | 25 | 2 316 | Диагностика и preview/apply остановки «Стационарность ряда».… |
| `apps/api/feature_plan.py` | 33 | 2 189 | План/матрица/привязка importance нарушают leakage-safe контр… |
| `apps/api/preprocessing_feature_engineering.py` | 21 | 1 982 | API-адаптер остановки «Предобработка → Генерация признаков».… |
| `apps/api/eda_model_matrix.py` | 24 | 1 909 | Временная колонка уверенно не определена; порядок строк треб… |
| `apps/api/preprocessing_scaling.py` | 20 | 1 849 | Нулевая средняя и единичная дисперсия; чувствителен к выброс… |
| `apps/api/neural_contract.py` | 27 | 1 809 | Нейро-runtime недоступен (пакеты не установлены или GPU отсу… |
| `apps/api/preprocessing_smoothing.py` | 15 | 1 414 | Сглаживание опционально. Выбор по полному ряду диагностическ… |
| `apps/api/eda_validation_strategy.py` | 15 | 1 305 | Временная ось не определена: границы показаны в текущем поря… |
| `apps/api/preprocessing_decomposition.py` | 15 | 1 256 | В колонке времени {invalid_dates} некорректных дат; сначала … |
| `apps/api/multivariate_contract.py` | 20 | 1 248 | во временной оси есть нераспознанные даты; сначала исправьте… |
| `apps/api/preprocessing_spectral.py` | 12 | 1 149 | API-адаптер остановки «Предобработка → Спектральный анализ».… |
| `apps/api/preprocessing_variance.py` | 13 | 1 073 | Параметры в backtest следует оценивать только на train-части… |

**Суммарно**: 77 файла  713 литералов  52 035 симв. — интерпретации находок/рекомендации узлов  зашитые в вычислительный код.
