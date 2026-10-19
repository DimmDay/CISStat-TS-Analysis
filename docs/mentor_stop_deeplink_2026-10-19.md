# MNS-LINK-3 — узловые deep-link Наставника: проект решения

Дата: 2026-10-19. База разработки: `main@74fd1ca`; база поставки (итерация 2): `main@5cbc5b4` — поставка переносена на параллельный коммит MNS-REG-2 без изменений кода (пересечение поставок по коду нулевое; склейка `worklog10.md`, пересборка `manifest.sha256`). Задача из плана `docs/mentor_next_step_review_2026-10-19.md` §6 (строка MNS-LINK-3); контракт — `spec_mentor_next_step.md` §5.3, решение Q6. Зависимости: только `spec_mentor_next_step.md` (MNS-SPEC-1 завершён); от `MNS-REG-2` задача не зависит (параллельная ветка плана).

## 1. Постановка и границы

Постановка плана: «Узловые deep-link: фронтенд-навигация `stage.node_id` → остановка степпера модуля (якорь/параметр), рендер в `MentorPanel` «Перейти: <остановка>»; фолбэк на вкладку стадии как сейчас». DoD: «Jest: маппинг известного узла — URL остановки; неизвестного — прежний chip; регресс `MentorPanel.test.tsx` зелёный».

Риск-строка плана ограничивает UI-объём: «фолбэк смягчает: сначала только три warning-способные стадии» — узловый deep-link реализуется для `upload | validation | preprocessing` (канон `mns_canon_v2`, решения Q3/Q4: EDA/Моделирование/Прогнозирование warning-семантики не имеют). Рекомендации процессных стадий (`modeling.backtest`, `forecasting.compare`) и рекомендации с неизвестным узлом ведут на вкладку стадии — прежнее поведение. Неизвестная стадия — chip без ссылки (как сейчас).

Вне скоупа (канон §7 spec_mentor_next_step.md): sanity/«мечется»/`derived_spikes` §7.2, EDA warning, `session.stages`, RAGFlow-рендерер, Слой B fallback-скана (это `MNS-FALLBACK-4`), объяснение в ответе (`MNS-TEXT-5`). Задача фронтенд-только: бэкенд, схемы API, события трассы не меняются; переход по рекомендации — совет, не факт (§3.2 `spec_progress.md`: в трассу не пишется).

## 2. Проверенное по коду состояние

- `MentorPanel.tsx::recommendedStageHref` (строка 36) маппит `stage.node_id` **только на вкладку стадии** через `STAGE_DEFS` (`lib/stages.ts`: `/upload … /forecasting`); узловая навигация отсутствует. Рендер: «Перейти: {stageLabel(stage)} →»; неизвестная стадия — `Рекомендация: {action}` без ссылки.
- Ответ next-step уже несёт узел: `recommended_action` = `"{stage}.{node_id}"` (8 правил `NEXT_STEP_RULES`; формат подтверждён тест-пином канон-блока `tests/unit/test_mentor_next_step_spec.py`).
- Единый реестр узлов на фронтенде уже существует: `lib/progress.ts::PROGRESS_STAGE_NODES` (50 узлов, 6 стадий; upload-список синхронизирован с бэкенд-графом sync-тестом `test_progress_panel.py`, который читает живой исходник файла), плюс `isKnownNode(stage, nodeId)` и `nodeLabel(stage, nodeId)` — метки совпадают с подписями степперов (проверено сверкой: Validation `CHECK_META`, Preprocessing `CHECKS`, Upload — общий `shared/pipeline_nodes/upload_stops.json`). Новый реестр меток НЕ создаётся — дрейф терминологии исключён по построению.
- Степперы хранят активную остановку в локальном state: Upload `activeStop: StopId`, Validation/Preprocessing `activeCheckId`. URL-параметры/якоря степперы сегодня не читают (`useSearchParams` в платформе не используется; `searchParams` встречается только в сборке API-URL).
- `MentorPanel` живёт в `ProgressDrawer`, доступном на всех модульных страницах → сценарий «клик по рекомендации на уже открытой вкладке той же стадии» реален и должен переключать остановку без перезагрузки.

## 3. Проект решения

### 3.1. Механизм перехода — якорь `#stop=<node_id>`

Контракт Q6 санкционирует «якорь/параметр». Выбран **якорь** `#stop=<node_id>` по совокупности причин: (1) выбранный механизм обязан работать в обоих приложениях (embedded/standalone) без изменений страниц; (2) `useSearchParams()` требует Suspense-границ при пререндере (риск сборки; production build в среде не проверяем — известный системный `ENOENT uv_resident_set_memory`) и потребовал бы моков `next/navigation` во всех существующих тестах степперов (большой радиус); (3) якорь читается клиентом без SSR-гидратационных расхождений (эффект после монтирования). Ключ `stop` в якоре — единственный, конфликтов с текущими якорями нет (платформа якоря не использует).

Три пути доставки цели, покрывающие все сценарии:
- **чтение якоря при монтировании** — cross-stage переход, перезагрузка, закладка/шаринг ссылки;
- **подписка `hashchange`** — back/forward браузера;
- **явное событие `GOTO_STOP_EVENT`** (`window.dispatchEvent(CustomEvent)`) из `onClick` ссылки MentorPanel — детерминированный same-route переход: клиентская навигация Next по якорю не порождает `hashchange` гарантированно (pushState не стреляет событиями), а панель доступна на всех вкладках.

### 3.2. Fail-closed whitelist (паттерн allowlist-перехвата PROGR-3)

Парс якоря принимает узел только если он — известная остановка **именно этой** стадии (`PROGRESS_STAGE_NODES`): чужой/неизвестный/пустой узел → `null`, степпер остаётся на дефолтной остановке. Никакого угадывания, никакого I/O, никаких исключений. Формат парсинга: `URLSearchParams` по телу якоря (`#stop=x` → `x`), кодировка честная (`encodeURIComponent`).

### 3.3. Разрешение ссылки рекомендации — `resolveRecommendationLink`

Единая функция в `MentorPanel.tsx`, аддитивно над прежним контрактом:

1. `recommended_action` отсутствует → `null` (chip без ссылки — как сейчас);
2. стадия (`split(".")[0]`, прежняя семантика) ∈ `DEEP_LINK_STOP_STAGES` И узел известен (`isKnownNode`) → **stop-link**: `href = "{href стадии}{stopAnchor(node)}"`, текст — `nodeLabel(stage, node)`;
3. иначе — фолбэк через `recommendedStageHref` (не переименован, пины прежние): известная стадия → вкладка стадии, текст — `stageLabel`; неизвестная — `null` → chip без ссылки.

Рендер «Перейти: {targetLabel} →» сохраняет форму; меняется только цель/метка для stop-ссылок. `onClick` stop-ссылки диспатчит `GOTO_STOP_EVENT` (same-route). Существующий экспорт `recommendedStageHref` и его тесты остаются без изменений — фолбэк-ветка заново использует ту же функцию, контракт «как сейчас» сохранён по построению.

### 3.4. Семантика переключения остановки в степперах

Deep-link переключает остановку с той же семантикой, что клик по ней (инварианты UI-UPLOAD-HELP-1/VALID-2/MANUAL-MISSING-1/MANUAL-OUTLIERS-1/DATASET-VIEW-EDITOR-1): закрытие Справки («Описание» показывает новую остановку), закрытие ручных режимов мастера и «Редактора датасета» (Validation/Preprocessing). Клик по УЖЕ активной остановке ничего не меняет (открытая Справка сохраняется) — deep-link на активную остановку тоже no-op. Эффект степпера: чтение якоря при монтировании + `hashchange` + `GOTO_STOP_EVENT` (фильтр по своей стадии), подписка с cleanup, зависимость от текущего идентификатора остановки — чистые сеттеры, без ref-зеркал.

## 4. Точки изменения

| Файл | Изменение |
|---|---|
| `packages/ui/lib/stopLinks.ts` (НОВЫЙ) | `DEEP_LINK_STOP_STAGES`, `stopAnchor`, `stopFromHash`, `GOTO_STOP_EVENT`, `GotoStopDetail`, `dispatchGotoStop`; единственный источник whitelist — `PROGRESS_STAGE_NODES` из `progress.ts` (без копий) |
| `packages/ui/components/MentorPanel.tsx` | `resolveRecommendationLink` + рендер stop-ссылки + `onClick`-диспатч; шапочный комментарий N-4 дополнен v2; `recommendedStageHref` не меняется |
| `packages/ui/components/TsAnalysisUpload.tsx` | эффект deep-link (mount read + `hashchange` + событие), семантика клика по остановке |
| `packages/ui/components/TsAnalysisValidation.tsx` | то же (+закрытие «Редактора датасета») |
| `packages/ui/components/TsAnalysisPreprocessing.tsx` | то же (+закрытие ручных режимов и «Редактора датасета») |
| `packages/ui/components/MentorPanel.test.tsx` | VERSIONED-пин deep-link: известный узел → якорь остановки; новые тесты фолбэка (процессная стадия, неизвестный узел, неизвестная стадия, диспатч события) |
| `packages/ui/lib/stopLinks.test.ts` (НОВЫЙ) | состав/порядок `DEEP_LINK_STOP_STAGES`, покрытие ровно 25 остановок, `stopAnchor`, fail-closed `stopFromHash`, константа события |
| `packages/ui/components/mentorStopDeepLink.test.tsx` (НОВЫЙ) | интеграция трёх степперов: якорь при монтировании, неизвестный узел → дефолт, same-route событие |

## 5. Риски и меры

- **Гидратационное расхождение SSR** — якорь читается эффектом после монтирования (не в инициализаторе state): серверный и первый клиентский рендер совпадают, переключение происходит в эффекте.
- **Дрейф whitelist против графа** — копий нет: whitelist = `PROGRESS_STAGE_NODES` (sync-тест с бэкендом уже существует); тест-гвард фиксирует ровно 25 остановок и состав трёх стадий.
- **Дрейф меток ссылок против степперов** — метки из `nodeLabel` (`progress.ts`), сверены со степперами; копий строк не заводится.
- **Слом существующих тестов степперов** — эффект аддитивен: пустой якорь jsdom (`""`) → `stopFromHash` → `null` → no-op; тесты степперов не рендерят MentorPanel, новых моков не требуется.
- **Разрыв контракта deep-link у внешних потребителей** — `recommendedStageHref` сохранён; ответ бэкенда и тип `MentorRecommendationInfo` не менялись.
