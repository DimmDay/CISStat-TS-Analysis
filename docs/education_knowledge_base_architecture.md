# Архитектура микросервиса «Обучение и база знаний»

Статус: **реализован Шаг 1 (страница-хаб базы знаний, фронт-контур); развитие — по этапам ниже.**

Дата: 2026-09-19. Синхронизация — `main` @ `5718a40` (Task DKT-CERT).

Задача: `spec_education.md` (Часть I), `spec_progress.md` + `spec_progress_review_and_v4_addendum.md` (контексты платформы, паттерны UI и трассировки). Постановка тимлида: спроектировать архитектуру микросервиса, затем реализовать Шаг 1 — страницу «Обучение и база знаний» (второй бейдж первого ряда главной, `HOME_ROUTES[1]`), включающую Библиотеку для чтения и Словарь терминов; база знаний — единый источник истины по методологии для всей платформы.

**Автор:** Claude (Senior dev), платформа CISStat TS Analysis

---

## 1. Место микросервиса в платформе

Микросервис «Обучение и база знаний» — вертикаль знаний, ортогональная пайплайну исследования: он не вычисляет артефакты (в отличие от этапов пайплайна), а **объясняет методологию**, на которой работают все вычисления. По `spec_education.md` это Часть I («база знаний встроена в работу»); Часть II (квант обучения `Q`/`ΔQ`) — последующие этапы, контур Шага 1 их не реализует, но готов принять (см. §6).

```
┌──────────────────────────────────────────────────────────────────┐
│  Точка входа: /education (standalone) — второй бейдж первого     │
│  ряда главной (HOME_ROUTES[1]); «О платформе» → подменю          │
├──────────────────────────────────────────────────────────────────┤
│  UI-слой (packages/ui/components/education/)                     │
│    EducationKnowledgeBase — хаб: шапка, поиск, секции, состояние │
│    LibrarySection — фильтр этапов + сетка карточек статей        │
│    GlossarySection — словарь: алфавитный список + связи          │
│    LibraryArticleReader — панель чтения (паттерн drawers)        │
├──────────────────────────────────────────────────────────────────┤
│  СЛОЙ ЗНАНИЙ — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ                            │
│  (packages/ui/lib/knowledge/)                                    │
│    types.ts — контракты: KnowledgeArticle, Citation, Block,      │
│               GlossaryTerm; KNOWLEDGE_STAGES (1:1 со STAGES)     │
│    articles.ts — реестр статей (12 записей: 11 published +       │
│                  1 draft, честная маркировка)                    │
│    glossary.ts — реестр терминов (25 терминов)                   │
│    knowledge.ts — API доступа: фильтры/поиск/порядок пайплайна   │
├──────────────────────────────────────────────────────────────────┤
│  (будущее) apps/api/knowledge/ — REST-контур                     │
│    GET /v1/knowledge/articles?stage_id=&node_id=                 │
│    POST /v1/learning/track                                       │
│    Реестры промотируются без перенабора контента (§5)            │
└──────────────────────────────────────────────────────────────────┘
```

Ключевой принцип (спецификация §0, §1): **контент живёт в управляемом реестре, а не в коде компонентов**. UI-слой знает только `article_id`/`term_id` и состояние; это и есть механическая гарантия того, что база знаний может стать единым источником истины: сегодня её читает хаб страницы, завтра — `ContextHelpButton` на уровне узлов этапов и курс, без перенабора текстов.

## 2. Что уже реализовано (Шаг 1)

### 2.1 Слой знаний

- `KNOWLEDGE_STAGES` — словарь этапов **1:1 со `STAGES` платформы** (`apps/api/session_store.py`, `packages/ui/lib/stages.ts`): контракт §1.1 спеки, застрахован инвариант-тестом.
- `KnowledgeArticle`: `article_id`, `stage_id`, `directions` (§2.2 — второе измерение тегирования, 8 направлений стартового набора спеки), `title`, `summary`, `reading_minutes`, `body`, `sources`, `status` (`published`/`draft`).
- `KnowledgeBlock` — структурированное тело: `paragraph` | `bullets` | `callout`. См. §3 (осознанное улучшение против `body_md`).
- `GlossaryTerm`: `term_id`, `term`, `definition`, `related_article_ids`, `stage_ids` — Словарь связан с Библиотекой (связность базы знаний), ссылки на несуществующие статьи запрещены инвариант-тестом.
- API доступа: `getPublishedArticles` (порядок — по пайплайну, §13 спеки), `getArticlesByStage`, `getArticlesByDirection`, `getGlossaryTerms` (алфавит ru), `searchKnowledge` (регистронезависимый подстрочный поиск по заголовку/summary/телу статей и терминам; честный пустой результат), `STAGE_ORDER_INDEX`.
- Инвариант-тесты слоя: уникальность id, валидность stage/direction, непустые блоки и источники, покрытие каждого этапа опубликованной статьёй, порядок выдачи = порядок пайплайна, draft не публикуется.

### 2.2 Контент — реальный, не выдуманный

Статьи отражают фактическую методологию платформы и её код:

| Статья | Факты из кода/спек платформы |
|---|---|
| upload-structure | контракт загрузки `TsAnalysisUpload.tsx` (автопревью, 5+5, teaser) |
| validation-dama | `CHECK_IDS` валидации (10 критериев, DAMA DMBOK) |
| preprocessing-missing-outliers | Мастера коррекций + sanity-правила Наставника (`no_effect`, `over_aggressive` >5× std, `excessive_data_loss` >30% строк — пороги из `spec_progress.md` §7.2) |
| preprocessing-regularity-stl | STL/регулярность, robust-режим, множественная сезонность (TBATS) |
| eda-* (4 статьи) | ACF/PACF, энтропии, ADF/KPSS/PP, распределение (JB/Shapiro/KS), CUSUM/Chow/PELT (Task 76, `eda_structural_breaks.py`) |
| modeling-catalog | 24 модели / 8 семейств / 4 уровня применимости (`modeling.ts`), baseline-first, 11 стадий графа |
| modeling-backtest | leak-safe, fold-local признаки (Task 126+), walk-forward |
| forecasting-intervals | 4 метода интервалов `forecasting_contract.py` (`analytic`, `parametric_simulation`, `empirical_oof_quantile`, `native_adapter`) + fail-closed |
| forecasting-accuracy-metrics | 6 метрик `backtesting.py` (`mae/rmse/mape/mase/smape/rmsse`, primary `rmse`) |
| forecasting-applied-modules-draft | **draft**: прикладные модули — ModulePlaceholder в продукте; статья не публикуется до готовности модуля (принцип спеки §7.1: «не пишутся заранее для несуществующего функционала») |

Источники — из §7.1 спеки: FPP3 (Hyndman & Athanasopoulos), Box-Jenkins, Tsay, De Livera (TBATS), Killick et al. (PELT), Tashman, Hyndman & Koehler (MASE), M4/M5, DAMA DMBOK, официальная документация statsmodels/pandas.

### 2.3 UI-слой и точка входа

- Хаб `EducationKnowledgeBase` (`/education`, standalone): шапка по паттерну HomeHero/TasksHub (`text-center`, hero-индиго шкалы заголовков — тёмная ревизия покрывается класс-уровневой utility-ревизией globals.css, DKT); поиск по всей базе; переключатель секций пилли (паттерн `ModuleNav`, `aria-pressed`).
- `LibrarySection`: фильтр «Все этапы» + 6 этапов (пилли, `aria-pressed`), сетка карточек **в единой геометрии карточек платформы** (grid-cols-1/sm:2/lg:3, gap-5 — DNA HomeHero/HomeCapabilities/TasksHub), бейдж этапа с иконкой этапа, направления, время чтения. Карточка — кнопка (открывает панель чтения).
- `GlossarySection`: алфавитный список терминов (ru), буквенная метка, определение, блок «Читать подробнее» со связанными статьями.
- `LibraryArticleReader`: правая выдвижная панель по паттерну `EventsLogDrawer.tsx` — ширина `w-[40rem]` (640px = 2×w-80 по контракту UI-аддендума v4 `spec_progress_review_and_v4_addendum.md` §4.2), на мобильных вся ширина; затемнение закрывает кликом вне; крестик (`aria-label="Закрыть статью"`); шапка с мета-информацией; тело блоками (callout — выделенный блок); источники с внешними ссылками (`target="_blank" rel="noopener noreferrer"`).
- `HOME_ROUTES[1].href`: `/docs` → `/education` (второй бейдж первого ряда главной больше не ведёт на 404 и не дублирует «Документацию API», которая остаётся на `/docs`).
- Доступность: роли `list`/`listitem`/`complementary`, `aria-pressed`, `aria-label`, `focus-visible:ring` — по паттернам платформы.
- Тёмная тема: только тематические токены (`bg-white`, `text-neutral-*`, `bg-brand`, `bg-brand-light`), `dark:`-оверрайдов нет — контракт DKT «классы не меняются — меняются значения» соблюдён; инвентарь hero-заголовков DKT-2R дополнен каталогом (13 инстансов в 6 файлах).

### 2.4 Что сознательно НЕ вошло в Шаг 1

- `ContextHelpButton`/`KnowledgeArticleView` на уровне узлов этапов (миграция `{CHECK}_METRICS_DESCRIPTION`-констант — Этап 1 спеки §16): отдельная задача, требует сверки паритета текстов (снапшот-тесты).
- Курс «Прогнозный аналитик», RAGFlow, ИИ-помощник, обучение стеки по направлениям (`LearningTrackBuilder`), база лучших практик — Этапы 2–4 спеки.
- Backend (`apps/api/knowledge/`), персистентность, события `TraceEvent` для сигналов «помогла/не помогла» — Этап 5+.
- Embedded-приложение: маршрут `/education` — standalone-only (по паттерну остальных standalone-страниц: `/navigator`, `/tasks`...). Общий хаб уже вынесен в `@cisstat/ui`, подключение в embedded — одной строкой, когда понадобится.

## 3. Архитектурные решения и улучшения к спеке

1. **Структурированные блоки вместо сырого `body_md`.** Спека описывает `body_md` (markdown). Шаг 1 хранит тело как типизированные блоки (`paragraph`/`bullets`/`callout`): рендер тривиален и типизирован, не требует markdown-зависимости на фронте, а сериализация в `body_md` при промоушене в backend — 1:1 (paragraph → абзац, bullets → "- ", callout → "> "). Формат спеки остаётся целевым для хранения, содержимое не теряется; риск паритета снимается тестом сериализации (написать при миграции).
2. **Словарь этапов — тот же `STAGES`.** Не новый параллельный словарь (§1.1 спеки): `KNOWLEDGE_STAGES` === ключи `stages.ts`/`session_store.py::STAGES`; инвариант-тест страхует рассинхронизацию.
3. **Порядок выдачи — контракт слоя, не UI.** `getPublishedArticles()` сортирует по `STAGE_ORDER_INDEX` (§13: порядок статей следует пайплайну, не порядку ввода) — UI физически не может нарушить правило.
4. **Честная маркировка draft.** Реестр содержит draft-статью о прикладных модулях: она не попадает в Библиотеку/поиск (тест), но доступна по прямой ссылке из будущего админ-контекста — демонстрация механики статусов и принцип «не описывать несуществующий функционал».
5. **Поиск — локальный, контракт совместим с будущим backend.** На Шаге 1 поиск вычисляется на клиенте по реестру; сигнатура `searchKnowledge(query) → {articles, terms}` идентична будущему REST-контракту `GET /v1/knowledge/search`, замена источника — замена импорта, UI не переписывается.
6. **Панель чтения = паттерн «Прогресса»/drawers.** Ширина `w-[40rem]` уже зафиксирована тимлидом для правых панелей (аддендум v4 §4.2) — база знаний использует тот же контракт, а не изобретает свой.

## 4. Риски и меры

| Риск | Мера |
|---|---|
| Рассинхронизация `KNOWLEDGE_STAGES` со `STAGES` платформы | Инвариант-тест 1:1 + один файл-источник комментариев ссылающийся на контракт |
| Утрата/порча методологического текста при промоушене в backend | Тест сериализации блоков в `body_md` (Этап миграции), снапшот на паритет |
| Дублирование маршрутов («Обучение» vs «Документация API» на `/docs`) | Маршруты разнесены: `/education` и `/docs`; тест hrefs подменю `ModuleNav` |
| Каталог DKT-2R (инвентарь hero-классов) ломается новыми хабами | Каталог обновлён (13 инстансов/6 файлов); правило: новый хаб = строка в каталоге |
| Словарь → ссылка на draft-статью | Ридер помечает статус; допустимо (чтение ≠ публикация в Библиотеке) |
| Вложенные списки ломают listitem-семантику сетки | Связанные статьи словаря — div+кнопки, не ul/li (тест контракта количества) |

## 5. Контракты с будущими этапами (Часть I спеки)

- **Этап 1 спеки (миграция контента):** каждая `{CHECK}_METRICS_DESCRIPTION`-константа `TsAnalysis*.tsx` мигрирует в `KnowledgeArticle` с `superseded_constant`-полем аудита; `ContextHelpButton` запрашивает статью по `(stage_id, node_id)` — **тот же реестр**, что читает `/education` (доп. поле `node_id: string | null` — уже предусмотрено в backend-модели спеки, на фронте не требуется).
- **Этап 2 (обучающие стеки + курс):** `getArticlesByDirection()` уже реализует §2.2 (стек по направлениям, порядок пайплайна); `LearningTrackBuilder` станет UI над ним. Курс = упорядоченное подмножество статей + контрольные вопросы — новых источников контента не требуется.
- **Этап 3 (RAGFlow):** индексируются `published`-статьи реестра; контракт рендера Наставника (`MentorTextRenderer`) не затрагивает этот слой.
- **Этап 5 (Q/ΔQ):** для сигнала «статья помогла/не помогла» понадобится `event_id`-пара на отображение статьи (`trace_events`); точка встраивания — единственный метод `openArticleFromAnywhere` хаба (все открытия чтения проходят через него) — телеметрия добавляется в одном месте, без обхода компонентов.

## 6. Этапы дальнейшей реализации (дорожная карта микросервиса)

1. **Шаг 1 (выполнен, эта задача):** страница-хаб `/education` + слой знаний (Библиотека 12 статей, Словарь 25 терминов, поиск, панель чтения, инвариант-тесты).
2. **Шаг 2:** направление-стеки (`LearningTrackBuilder`: чекбоксы направлений → персональная траектория, порядок пайплайна) — данные и API уже готовы.
3. **Шаг 3:** миграция контекстной справки этапов (`ContextHelpButton`/`KnowledgeArticleView`, паритет-снапшоты) — база знаний становится источником справки `'?'`.
4. **Шаг 4:** backend `apps/api/knowledge/` (`GET /v1/knowledge/articles`, `POST /v1/learning/track`), промоушен реестра без перенабора контента.
5. **Шаги 5+ (Часть I/II спеки):** курс, RAGFlow, база практик, `Q`/`ΔQ` — по порядку роллаута `spec_education.md` §16.

## 7. Манифест файлов Шага 1

Новые:
- `packages/ui/lib/knowledge/types.ts` — контракты слоя знаний
- `packages/ui/lib/knowledge/articles.ts` — реестр статей (12: 11 published + 1 draft)
- `packages/ui/lib/knowledge/glossary.ts` — реестр терминов (25)
- `packages/ui/lib/knowledge/knowledge.ts` — API доступа (фильтры/поиск/порядок)
- `packages/ui/lib/knowledge/knowledge.test.ts` — инвариант-тесты слоя (26)
- `packages/ui/components/education/EducationKnowledgeBase.tsx` — хаб
- `packages/ui/components/education/LibrarySection.tsx` — Библиотека
- `packages/ui/components/education/GlossarySection.tsx` — Словарь
- `packages/ui/components/education/LibraryArticleReader.tsx` — панель чтения
- `packages/ui/components/education/EducationKnowledgeBase.test.tsx` — контракты хаба (12)
- `apps/standalone/app/education/page.tsx` — маршрут standalone
- `apps/standalone/app/education/page.test.tsx` — контракт страницы (2)
- `packages/ui/lib/home-stops.test.ts` — контракт бейджа главной (3)
- `docs/education_knowledge_base_architecture.md` — этот документ

Изменённые:
- `packages/ui/lib/home-stops.ts` — `HOME_ROUTES[1].href`: `/docs` → `/education`
- `packages/ui/index.ts` — экспорты слоя знаний и компонентов education
- `packages/ui/components/ModuleNav.test.tsx` — ожидаемые hrefs подменю (контракт `/education`)
- `packages/ui/heading-indigo-calibration.test.ts` — каталог DKT-2R: 13 инстансов в 6 файлах
- `worklog/worklog7.md` — рабочая запись

## 8. Верификация (TDD RED → GREEN → регрессия)

- RED: 4 новых сюиты падали до реализации (отсутствие модулей/маршрута, контракт `/education`).
- GREEN: слой знаний 26/26, хаб 12/12, страница 2/2, home-stops 3/3, ModuleNav 13/13 (полная сюита), DKT-2R каталог 7/7.
- Полная регрессия: **jest 1362/1362 (125 сюит) — зелёный**; typecheck:all — 0 ошибок; build standalone — OK, `/education` в маршрутах (18 статических страниц).
- Прод-смоук локально: главная → клик второго бейджа → `/education` (HTTP 200), чтение статьи (панель), Словарь, поиск (`GARCH`), светлая/тёмная темы.
