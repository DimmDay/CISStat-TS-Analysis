# Пополнение базы знаний из папки проекта

**Дата:** 29 октября 2026 года, Москва. **Проверенная база:** `cb46e3aca646cc77cc600af0de5d80094678c1b8`. **Статус:** исследование и проект алгоритма; конвейер приёма файлов не реализован этой поставкой. Runtime-код, реестры знаний и опубликованный контент не изменялись. Новые исходные материалы пользователем пока не предоставлены.

Связанные контракты: spec_education.md, docs/education_knowledge_base_architecture.md. Сохраняются единый источник контента, pipeline order, отсутствие выдуманного содержимого и human review до публикации. Перенос в серверную БД не требуется для запуска процесса.

## 1. Что работает сейчас

Синхронизация выполнена fetch и отдельным detached worktree, AGENTS.md прочитан также через GitHub plugin на указанном ref. Статический анализ кода и независимый подсчёт registry_data.json подтвердили: **14 статей**, из них 13 published/1 draft, **78** help entries, **28** терминов. Исторический архитектурный текст с 12 статьями/25 терминами описывает прежний срез.

<!-- SOURCE_PATHS -->
| Исходник | Факт |
|---|---|
| `packages/ui/lib/knowledge/articles.ts` | Статьи authored в TypeScript, это текущий источник контента |
| `packages/ui/lib/knowledge/glossary.ts` | Отдельный authored словарь терминов/связей |
| `packages/ui/lib/knowledge/help.ts` | Курированная справка ключей stage/node/facet |
| `packages/ui/lib/knowledge/types.ts` | 6 этапов, 8 направлений, scalar stage_id, body blocks; нет ingestion metadata |
| `packages/ui/lib/knowledge/knowledge.ts` | UI searchKnowledge, buildLearningStack и describeNode читают static imports |
| `packages/ui/components/education/EducationKnowledgeBase.tsx` | Хаб использует локальный knowledge API, не live чтение папки |
| `packages/ui/components/education/LibraryArticleReader.tsx` | Рендер существующих blocks; Markdown source сам по себе не включается в UI |
| `scripts/promote_knowledge_registry.test.ts` | Jest-генератор registry_data.json и parity guard, не parser PDF/DOCX |
| `apps/api/knowledge/registry.py` | Backend читает JSON, load_registry с lru_cache(maxsize=1) |
| `apps/api/knowledge/router.py` | Публичные read APIs статей/glossary и POST learning/track; endpoint загрузки нет |
| `apps/api/knowledge/models.py` | DTO контента и blocks_to_body_md; не файловый ingestion |
| `tests/api/test_knowledge_api.py` | Проверки registry/API, фиксированные corpus expectations требуют согласованных обновлений |
| `docs/education_knowledge_base_architecture.md` | Историческая архитектура, часть будущих шагов уже существует в коде |
<!-- SOURCE_PATHS -->

**Просто положить документ в репозиторий недостаточно.** Нет общего file inbox detector→parser→review→publisher; текущий promotion переносит уже написанные TS-реестры в backend JSON. UI требует rebuild/redeploy, backend — перезапуск workers либо проектируемую versioned reload. Изменение одного JSON в работающей системе не синхронизирует статический frontend.

Текущая библиотека — управляемые статьи, не каталог произвольных исходных книг. Рекомендация — добавить явно различаемую общую библиотеку источников и связывать её с учебными статьями, а не выдавать текст всего PDF за готовый урок.

## 2. Какие форматы выбирать

| Формат | Рекомендация | Вес и разбор |
|---|---|---|
| Markdown `.md`, UTF-8 | Основной для новых авторских методических материалов | Обычно компактный; заголовки/списки/таблицы/формулы/ссылки сохраняют смысл и границы |
| TXT `.txt`, UTF-8 | Для простого текста без сложной структуры | Минимальный служебный overhead, но хуже границы разделов, таблицы, формулы и цитирование |
| DOCX `.docx` | Принимать, если автор работает в Word | Упакованный XML; можно извлечь headings/paragraphs/tables, но tracked changes/формулы требуют отдельного контроля |
| Текстовый PDF | Принимать оригиналы публикаций/стандартов | Сохраняет страницы и вид, но reading order, колонки, таблицы и формулы извлекаются неоднозначно |
| Скан PDF/PNG/JPEG | Исключение | OCR дороже и ошибается; сохранять page mapping/quality flags, не публиковать как достоверно распознанную науку автоматически |
| Старый DOC `.doc` | Не основной | Предпочесть предварительное преобразование в DOCX/MD; binary-конвертер только изолированно |
| HTML | Опциональный вход | Требуются sanitization и локальные assets, запрет скриптов/remote fetch; ссылки сами не импортируются |
| Google Docs/`.gdoc`/«docs» | Не переносимый файл содержимого | Экспортировать в DOCX или Markdown; shortcut/URL не содержит сам документ |

**Минимум служебного веса — TXT; лучший баланс веса и качества научного парсинга — Markdown UTF-8.** Нельзя обещать, что любой MD/TXT меньше любого DOCX/PDF: сжатие, изображения и состав различаются. Не переводить хорошую структурированную публикацию в TXT ценой потери таблиц/формул только ради веса.

Для новых текстов: один материал или глава на MD, заголовки H1–H3, стандартные списки, простые таблицы, формулы в LaTeX, определения явно «Термин — определение», ссылки/DOI/автор/год. Рисунки — отдельные локальные assets с alt/caption; не base64 внутри текста. Для PDF оригинал сохраняется один раз, рядом нормализованный текст и извлечённые нужные assets; не дублировать полный исходник в каждой статье/section.

PDF text extraction может нарушать reading order: это прямо отмечено первичной документацией PyMuPDF. Pandoc поддерживает Markdown/DOCX и структурное преобразование, но не обещает безошибочного переноса сложных таблиц. Выбор parser package фиксируется после проверки лицензии и тестового корпуса; здесь не заявляется установленная PDF/OCR зависимость.

## 3. Папки без БД

Проектируемые пути, отсутствующие пока в runtime:

```text
knowledge/inbox/                 входящие файлы и source sidecars
knowledge/sources/               принятые immutable оригиналы по hash
knowledge/extracted/             parser output + heading/page map + quality
knowledge/review/                кандидаты статей/терминов/связей и diff
knowledge/catalog/              утверждённые metadata/связи/редакции
knowledge/releases/<release_id>/ immutable опубликованные bundles + manifest
knowledge/state/                локальные состояния задач/блокировки
knowledge/reports/              отчёты scan/parse/validate/publish
```

В инфраструктуре один persistent volume/source рабочий каталог, не папка каждого посетителя в serverless frontend. Для текущего репозитория v1 процесс запускается редактором в управляемом checkout, затем публикуется согласованный frontend/backend release. Папка на ноутбуке не становится доступной Render/Vercel автоматически. Локальные upload/state/build files не публикуются через static serving.

Оригиналы большого размера — отдельное хранилище/volume с backup; маленькие curated тексты и manifests подходят для git. Размещение коммерческого оригинала в публичном git не эквивалентно праву его распространения. Серверная БД впоследствии заменит storage adapters, а не stable IDs и контракты содержимого.

Пример sidecar `material.source.json` (предлагаемая схема, не текущий API):

```json
{
  "source_id": "src-seasonality-guide",
  "title": "Методы сезонного анализа",
  "authors": ["Автор"],
  "year": 2026,
  "language": "ru",
  "source_uri": null,
  "license_note": "Авторский материал организации",
  "visibility": "public",
  "allow_fulltext_publication": true,
  "stage_hints": ["preprocessing", "eda", "modeling"],
  "direction_hints": ["seasonality"]
}
```

Автоматически вычисляются content_hash, source_version, received_at, parser_version; автор их не набирает. source_id сохраняется при переименовании/новой редакции. Hints не являются доказанными связями, visibility=public без подтверждённых условий не проходит publish.

## 4. Алгоритм: обнаружение → единый релиз

### Шаг 1. Обнаружение и безопасный приём

Сканировать только inbox allowlist; MD/TXT/DOCX/text PDF. Игнорировать temp/lock files и незавершённую запись: рекомендуемый перенос `.part`→atomic rename либо проверка стабильности размера/mtime два сканирования. На старте и по расписанию делать reconciliation всего inbox, watcher лишь ускоряет обнаружение.

Проверить MIME/signature, encoding, size/page/архивные лимиты, отсутствие symlink/path traversal и зашифрованного/повреждённого файла. DOCX — ZIP с ограничением суммарного распакованного размера. Парсеры subprocess без сети/macros/исполнения команд, ограничены временем/RAM. Входной документ считается данными, не инструкциями для pipeline/LLM.

### Шаг 2. Версия и дедупликация

SHA-256 исходных bytes — content_hash. Один и тот же hash не парсить повторно; сохранять origin aliases. Новый hash с тем же source_id — новая source_version, не новый независимый учебник. При переименовании без metadata changes вычисления не повторять. Похожие документы по нормализованным headings/paragraph hashes — кандидаты дублей, не автоудаление.

Cache key разбора = content_hash + parser/config/OCR version; обогащения = extracted hash + taxonomy/schema/model/prompt versions. Изменение metadata перезапускает classification/build, не OCR всего документа; изменение parser — только affected parse entries. Source extraction и editorial corrections раздельны, повторный parser не затирает правки редактора.

### Шаг 3. Парсинг по формату

MD/TXT читать UTF-8 с явным отчётом неизвестной кодировки. MD→структурный AST; не извлекать таблицы/формулы regex по строкам. DOCX→структура заголовков/абзацев/списков/таблиц/ссылок/формул; отдельно помечать track changes/comments и выбрать вид принятой редакции явно. PDF→page blocks/order/coordinates, убрать повторяющиеся headers/footers с сохранением raw provenance, восстановить главы без стирания номера страницы.

OCR только для страниц без пригодного текста; mixed PDF не OCR целиком. OCR status/confidence доступно лишь если инструмент реально их отдаёт; иначе оценка обозначается эвристикой. Таблицы, формулы, минусы, десятичные знаки и индексы проверяются отдельно. Неудачный parse→failed/quarantined с причиной, исходник сохранён; повтор требует контролируемой retry, не бесконечный цикл.

### Шаг 4. Нормализация и проверка качества

Сохранять headings/paragraphs/tables/formulas/code/assets/captions; ссылки на источник: page/section/paragraph/block offsets и extractor_version. Normalized content — UTF-8 MD либо typed AST JSON; JSON служебный, MD удобен редактору. Оригинал не перезаписывается.

Проверки: непустой осмысленный текст, язык/ошибки кодировки, дубли колонтитулов, порядок колонок, утерянные формулы/таблицы, orphan assets. При quality issue→review_required; машинный score не заменяет ревью. Extraction является текстом источника, а не доказанной научной истиной.

### Шаг 5. Семантическое разбиение

Единица библиотеки — законченный раздел/метод/понятие с prerequisites, а не произвольные 500 символов. На этой единице строятся источниковые citations и кандидат учебной статьи. Технические chunks для поиска/retrieval — отдельный слой: начально 400–800 tokens, небольшой overlap только по границам абзацев, параметры уточняются на corpus. Не разрывать формулы/определения/таблицы; длинную таблицу делить с headers/context. Не превращать каждый chunk в отдельный урок и не дублировать исходные bytes.

### Шаг 6. Классификация и привязки

Сначала точные sidecar hints, controlled vocabulary, aliases и deterministic rules. Затем ранжирование релевантных stage/node/directions по тексту, заголовкам и существующему каталогу; LLM — опциональный помощник для кандидатов/summary, не обязательная дорогая dependency.

Использовать шесть текущих stage_id и восемь directions. У текущей KnowledgeArticle scalar stage_id: выбрать основной этап; материал нескольких этапов разбить на осмысленные articles с общим source_id/refs, а не писать массив туда, где тип его не принимает. UI может показывать related-stage links через будущую аддитивную mapping schema. Не дублировать один текст трижды ради трёх фильтров. Нет подходящей taxonomy — unmapped, предложение нового тега проходит отдельное решение, не silent mapping в «другой» раздел.

Библиотечные связи могут быть many-to-many; **контекстная справка describeNode** имеет уникальный stage/node/facet. Новый документ предлагает additional reading и кандидаты правок, не перезаписывает автоматически текущие 78 help entries. Методологический текст отличать от фактических возможностей кода: внешний учебник не делает отсутствующий алгоритм реализованным.

### Шаг 7. Термины и обучение

Извлечь term candidates из явных определений/глоссария/заголовков; определение имеет citation/source span и редакцию. Связывать с canonical term_id и aliases, включая русские/английские варианты/сокращения. Стемминг/ё/регистр помогают поиску, но не сливают разные смыслы. При конфликте определений — отдельные смыслы/domain либо review, не замена старого одним score.

Публикуемый термин требует проверенного определения и корректных related_article_ids/stage_ids. Простое упоминание термина создаёт occurrence, не новое определение. Не публиковать пустые/orphan термины.

buildLearningStack уже отбирает published articles по directions, dedupe article_id, pipeline order; термины связаны со статьями. После публикации корректно размеченная статья естественно появится в новой траектории. Это не автоматическое построение педагогического курса: objectives/difficulty/prerequisites/control questions — отдельные editorial поля/этап. Для v1 сохранить текущий порядок и добавить approved order_key с одинаковой сортировкой Python/TS; нельзя полагаться на localeCompare vs codepoint для новых заголовков. Действующую выбранную траекторию закреплять release_id, обновление предлагается явно; completed progress не сбрасывается.

### Шаг 8. Ревью и разрешение на публикацию

Автоматически сформировать review package: исходник/фрагмент, extracted text, quality warnings, предложенные summary/articles/stages/nodes/directions/terms, citations, diff предыдущей версии. Редактор проверяет минимум соответствие источнику, parse quality, научную применимость, права публикации, taxonomy и определения. Один approve подтверждает согласованный пакет, не четыре ручных копирования.

Состояния job: discovered→validated→parsed→classified→review_required→approved→built→published либо failed/rejected. Это workflow ingest, не прямое расширение текущего KnowledgeArticleStatus draft/published. needs_review в spec_education связан с будущими сигналами качества Q; не объявлять его готовым ingestion enum без миграции.

Для trusted author MD возможна заранее созданная подпись approval конкретного content/config hash; любое изменение сбрасывает approval. Авторазбор и индекс кандидатов можно включать сразу, но **автопубликация непроверенного внешнего PDF/LLM-определения запрещена** по существующему education contract. Review не требует отдельного согласования каждого технического шага.

### Шаг 9. Детерминированная сборка всех поверхностей

Утверждённые normalized content+catalog становятся единственным authored source нового контура; существующие articles/glossary/help импортируются один раз без перенабора и фиксируются parity fixtures. Не поддерживать параллельно ручной TS и ручной JSON. build генерирует совместимые TS exports для текущего UI и registry_data.json для backend из одного release manifest; текущий Jest promotion рефакторится в обычную CLI build-команду, тесты перестают писать production файлы.

V1 сохраняет одну immutable release для articles/glossary/help/mappings/order/search index. Typed body blocks расширяются versioned headings/table/formula/code/citation при необходимости; нынешний reader имеет ограниченный набор blocks — нельзя молча отбросить таблицы или считать body_md полноценным renderer. Для минимального запуска поддержать MD subset без потерь; неподдерживаемый block блокирует публикацию или явно требует редакторского преобразования.

Validation до publish: IDs/refs/taxonomy, nonempty bodies/definitions, cited spans, published-only visibility, no draft leakage через term/reader/id, no broken help keys, Python/TS parity/sort, источниковые права, отсутствие активного HTML/JS. Hardcoded corpus counts заменить на содержательные invariants и reviewed release snapshot, не отключать защиту при росте корпуса.

### Шаг 10. Публикация, видимость и откат

Собрать staging release_id с hashes/schema/parser/catalog/approval versions, затем atomically activate manifest. CLI lock/single writer исключает частичный merge двух imports; все файлы одной версии проверяются перед activation. Crash оставляет last-known-good release. Документ в статусе approved ещё не виден читателям до согласованного deployment.

В текущей топологии UI static imports требуют сборки/развёртывания frontend, backend JSON с lru_cache — перезапуска всех процессов; одной файловой atomic rename недостаточно для распределённого deploy. Release pipeline сверяет /knowledge version и embedded/standalone build versions. При несовпадении обучение/поиск используют закреплённую версию, не смешивают glossary нового и articles старого release. После миграции UI на versioned API/backend hot reload activation станет быстрее, но не является первым обязательным шагом.

Публикация обновляет общую библиотеку sources+articles, stage/direction sections, learning selection и glossary в одном release. RAG/embeddings, если будут внедрены, строятся только по approved published corpus на событие release; они не prerequisite библиотеки и не означают, что данные «попали в веса LLM». Текущая система использует substring search, не реализованный RAGFlow.

## 5. Режим запуска: что оптимально сейчас

**Рекомендуется manual sync с автоматическим pipeline до review**, затем отдельные approve/build/publish. Для небольшого корпуса это дешевле/надёжнее постоянно работающего parser на API; достаточно Python CLI, hashes и файловых manifests. Watcher — optional удобство редактора, не authority и не auto-publisher.

Ниже **предлагаемые будущие команды**, их пока нет в репозитории:

```bash
python -m tools.knowledge scan --inbox knowledge/inbox --dry-run
python -m tools.knowledge sync --inbox knowledge/inbox
python -m tools.knowledge review --report knowledge/reports/latest.json
python -m tools.knowledge approve --batch <batch_id> --expected-hash <candidate_hash>
python -m tools.knowledge build --approved
python -m tools.knowledge publish --release <release_id>
```

Sync не публикует; approve фиксирует verified content hash; build не меняет active; publish запускается release ответственным. При потере cache/state можно восстановить jobs по original/catalog/release manifests, не повторять платные вызовы без журнала.

Дополнение позже: `watch` для локальной inbox — debounce/stability, очередь и тот же sync handler; на старте/каждые несколько минут reconciliation. Периодический запуск на собственном сервере через scheduler — только обнаружение/parse; независим от live API workers, с ограниченной concurrency. Сканы/OCR — отдельная тяжёлая очередь, MD/TXT fast lane. В текущем cloud-deploy без persistent disk фоновой watch inbox ненадёжен: checkout/deploy не является общей файловой папкой.

**Что можно сделать уже сейчас без нового кода:** редактор вручную готовит статьи и термины в articles.ts/glossary.ts, правит help.ts лишь для осознанной методологической правки; затем выполняет существующий promotion и проверки:

```bash
PROMOTE_KNOWLEDGE=1 npx jest promote_knowledge_registry --runInBand
npx jest promote_knowledge_registry --runInBand
python -m pytest tests/api/test_knowledge_api.py
```

Первая команда меняет generated JSON. Эти команды показаны как действующий ручной механизм, **в этой задаче не запускались** и новых материалов не публиковали. Далее требуются затронутые UI tests, typecheck/build и согласованный deploy; commit/push агентом запрещён AGENTS.md.

## 6. Эффективность и достоверность

- Быстрая discovery проверка size/mtime, окончательная identity по hash; не OCR/LLM на каждом запуске.
- Parse каждого оригинала один раз на parser version; enrich только изменённых разделов; publish пересобирает зависимые mappings/terms/index.
- Не хранить изображения каждой PDF страницы после OCR бессрочно, если они временные и оригинал позволяет восстановление. Нужные figures/table assets сохранять с provenance/правами.
- Малый корпус: structured files + lightweight lexical index; embeddings только после измеренного выигрыша retrieval на своём тестовом наборе. Публичный поиск/learning не ждут внешнего LLM.
- Большие книги обрабатываются по главам/pages с checkpoints/resume, лимитами и caching; не посылать всю книгу в один prompt.
- Модель по умолчанию не получает частные документы в облако: внешняя обработка включается явной конфигурацией/разрешённым source policy. Файловый импорт не запрашивает секреты платформы и не меняет MentorRule.
- Метрики: parsed/new/unchanged/failed counts, время/стоимость parse/OCR/enrichment, review backlog, source→article mapping, orphan refs/terms, version mismatch, search regression. Не считать число chunks качеством базы.

## 7. Исходник, учебный контент и права

Источниковый документ, его normalized text и учебная статья — разные сущности с общим provenance. Допустим source card без открытого full text: title/author/year/citation/link и курированная заметка. Если материал restricted, он не должен попасть в текущие публичные endpoints/TS bundle/embeddings для общего доступа. Для v1 импортировать в published только общедоступный разрешённый корпус; private library требует отдельной object/tenant visibility реализации до публикации.

Изъятие/удаление из inbox не удаляет уже опубликованные знания молча. Отдельный retire/retract flow обновляет release, статьи/terms/dependencies/search/RAG и показывает причину. Нельзя сохранять опубликованное определение, единственный источник которого отозван, без review. Старые learning snapshots хранят историю ID/результатов, но правомерный доступ к отозванному тексту регулируется политикой, не «вечным cache».

## 8. План реализации

| Задача | Зависимости | Результат | Приёмка |
|---|---|---|---|
| KBI-00 | — | Schema/source/catalog/workflow и импорт существующего корпуса | Parity 14/13/78/28 и stable IDs, не теряются help/terms/directions |
| KBI-01 | KBI-00 | Inbox scan/hash/state/retry/lock | Duplicate/rename/partial write/crash не создают повторные задачи/потери |
| KBI-02 | KBI-01 | MD/TXT/DOCX/text PDF parsers, AST/provenance | Заголовки/таблицы/формулы/page spans; неподдержанное честно quarantine |
| KBI-03 | KBI-02 | Quality/OCR fallback/checkpoints | Mixed PDF OCR только нужных страниц; нет безусловного auto-publish плохого текста |
| KBI-04 | KBI-02 | Classification/chunking/relevance candidates | Валидные stages/directions, multi-stage material не ломает scalar stage_id |
| KBI-05 | KBI-04 | Term candidates/aliases/learning links | Mention не становится определением, conflict review и no orphan glossary |
| KBI-06 | KBI-03, KBI-05 | Review package/approval hash и revisions | Нельзя publish без подтверждения точной редакции; parser retry не затирает editorial changes |
| KBI-07 | KBI-06 | Single-source build TS+backend registry+reader adapters | Formulas/tables не теряются; draft не утекает; ordering/parity стабильны |
| KBI-08 | KBI-07 | Atomic release/deploy/version/rollback | Все поверхности одной версии; partial deployment сохраняет last-known-good |
| KBI-09 | KBI-08 | Watch/scheduler/reconciliation и retrieval adapters | Watch и manual используют один handler; RAG только published, downtime не теряет inbox |
| KBI-10 | KBI-09 | Сквозная приёмка и DB migration contract | Drop file→review→library/section/track/glossary с source refs; retire/rollback/restart и private-source запреты |

Первый полезный релиз: KBI-00…02,04…08 с качественным MD/DOCX/text PDF; OCR можно временно явно отклонять. Полностью автоматическое обнаружение не требует автоматического допуска в научную библиотеку. Собственный сервер позже добавляет persistent watch/jobs и storage adapter БД без повторной ручной разметки.

## 9. Приёмочные примеры

1. Автор добавил MD по сезонности: новый source, section candidates, stage/directions и определения с цитатами; до approve пользователи не видят их, после publish появляются библиотека/разделы/стек/термины одной версии.
2. Тот же файл переименован/добавлен второй раз: одна parsed version, origin aliases, без новых статей/terms.
3. В PDF исправлена глава: новый source_version, только изменённые sections требуют enrich/review, старые citations доступны как исторические по политике.
4. Скан с формулой распознан неверно: quality flags/review, опубликованный учебный текст не заменён.
5. Новый документ противоречит существующему термину: два кандидата/контекст/источники, не автоматический overwrite.
6. Материал по не реализованному алгоритму: source card/общая методологическая статья допустимы с маркировкой; справка продукта не обещает работающую функцию.
7. Backend получил новую версию, frontend старую: mismatch обнаружен, rollout не завершён, нет смешанной траектории.
8. Hidden text в PDF просит выполнить команду/отправить секрет: это данные, не действие pipeline; no network/macros/exec.
9. Изъятие источника, restart/повтор publish и две concurrent sync не дают dangling refs, двойных терминов и частичного релиза.

## 10. Проверки исследования и источники

Эта поставка не запускает ingestion и не наполняет базу без документов. Текущие code facts проверены на указанном commit; подсчёт JSON независим от исторических worklog. Documentation checks проверяют base/status, source paths, workflow/consumers, task DAG и Markdown. Они не удостоверяют будущий runtime parser, качество классификации или готовность OCR. Software tests/build не нужны для неизменённого runtime и здесь не запускались.

Первичные внешние источники, проверены 29.10.2026:

- Pandoc User’s Guide: https://pandoc.org/MANUAL.html — Markdown/DOCX, AST, UTF-8, ограничения конверсии сложных элементов.
- PyMuPDF Text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html — text blocks/page mapping и проблемы порядка чтения PDF.

Конкретные pipeline, folders/commands, workflow/approval и release policy выше — проектные решения для этой платформы, не описание уже установленного tooling.
