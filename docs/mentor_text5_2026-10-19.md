# MNS-TEXT-5 — аддитивное объяснение «почему жёлтый/красный» в ответе next-step, проект решения

Дата: 2026-10-19. База: `main@76e9be8` (MNS-FALLBACK-4). Задача из плана `docs/mentor_next_step_review_2026-10-19.md` §6; контракт — `spec_mentor_next_step.md` §5.1/§5.2, §8 (DoD), §9 (критерий приёмки 5). Зависимость: MNS-FALLBACK-4 (Слой B в `evaluate_next_step` + `node_facts` в роутере) — завершён.

## 1. Постановка и границы

DoD плана: «Аддитивное поле объяснения в `MentorNextStepResponse` (например, `explanation`): `status_reason` + `summary_count` узла + ссылка/выдержка методологии из реестра знаний (VERBATIM, паттерн `node_methodology`); рендер в `MentorPanel`. Схема ответа аддитивна (существующие потребители не ломаются); советы — не факты (§3.2): в трассу не пишется; контракты `phase_text`/`summary` прежние».

Решение Q7 (спека §1): в ответе — `status_reason` + `summary_count`; методология остановки — **ссылкой** на статью (`help_entries`), вербатим целиком ответ не утяжеляет; VERBATIM-текст остаётся отчёту (`run_report.py::node_methodology`, не меняется).

Вне скоупа: движок правил (`NEXT_STEP_RULES`, Слой B — контракты MNS-FALLBACK-4 не трогаются), EDA warning (Q3), процессные стадии в скане (Q4), §7.2 sanity/thrashing/derived_spikes, `session.stages`, RAGFlow-рендерер (§8), рендер вербатима методологии в панели (ссылкой — Q7), телеметрия `MentorObservation` (PROGR-8, не меняется).

## 2. Проверенное по коду состояние

- Роутер `get_mentor_next_step` (`apps/api/routers/progress.py:1954`): `recommendation = evaluate_next_step(statuses, node_facts=_node_facts_for_mentor(projection))` — факты (`status_reason`/`summary_count`) уже собраны из `projection.node_states` (AUDIT-5B, `node_states_with_evidence`), но в ответ попадает только отрендеренное сообщение; структурные факты отбрасываются.
- `MentorRecommendationOut` — ровно 4 поля (`rule_id/stage/message/recommended_action`); используется ТОЛЬКО в next-step (проверено грепом) — расширение полями не задевает другие эндпоинты.
- `summary_count` в проекции уже вычищен щитом `_clean_summary_count` (`node_status.py:1472`: только неотрицательное int, bool/дробь/строка/отрицательное → None) — в `node_states` попадает `int | None`.
- Реестр объяснимости MNS-REG-2: `MENTOR_STOP_EXPLANATIONS_BY_KEY[(stage, node_id)]` — 25 записей, несёт `help_entry_id`; доступ уже импортирован движком (`mentor_rules` из `mentor_explanations`) — новый import-time стоимости для роутера нет.
- Реестр знаний backend: `apps/api/knowledge/registry.py::load_registry()` — артефакт промоушена `registry_data.json`, lru_cache singleton (одна загрузка на процесс); help_entries промотированы в `KnowledgeArticle` с `article_id == entry_id`, `title == первая строка текста` (механический вывод, без перенабора). Публичного доступа по id НЕТ — только `find_article(stage_id, node_id, facet)` по тройному ключу; `_article_index` приватный. Прецедент направления зависимостей `app/core → apps.api.knowledge.registry` — `run_report.py:58` (VERBATIM-доступ отчёта).
- Заголовки статей (сюит реестра MNS-REG-2 пинит): validation/preprocessing — «Метрики и алгоритм: <label>» (facet metrics), upload — «Цели модуля «Загрузка»» (`upload.module.module_help`).
- Фронт: `MentorRecommendationInfo` (`lib/mentor.ts`) — зеркало 4 полей; `MentorPanel` рендерит сообщение + deep-link (MNS-LINK-3); клиентские типы не валидируют ответ строго — опциональное поле обратно совместимо.
- Телеметрия `_record_next_step_observation`: пишет только факт выдачи (`rule_id/stage`) в журнал наблюдений — отдельный от трассы контур (PROGR-8); объяснение туда не попадает по построению модели `MentorObservation`.

## 3. Проект решения

### 3.1. Схема (аддитивно к `MentorRecommendationOut`)

`MentorExplanationOut`: `status` (факт статуса узла из той же проекции — честный рендер «жёлтая/красная»), `status_reason: Optional[str]` (сырой факт, None — «не отчитана», фронт строку не рисует и не выдумывает), `summary_count: Optional[int]` (то же число, что бейдж; None — «не отчитано»), `help_entry_id: str` (идентичность статьи реестра знаний — join по `article_id == entry_id`), `methodology_title: Optional[str]` (вербатим заголовка статьи — терминология из реестра, ноль новых текстов; промах — None честно). Поле `explanation` на `MentorRecommendationOut` — optional, default None: ответ старых потребителей дополняется одним ключом, ни один существующий не меняется (pydantic response_model фильтрует, новые ключи аддитивны; точных JSON-равенств в тестах нет — проверено).

Обоснование `status`: спека §5.2 фиксирует три слоя, но панель обязана различать «почему жёлтая»/«почему красная» (инвариант v2 покрывает оба статуса — канон-формулировка §0); deriving из `rule_id` (fallback_error/fallback_warning) — неявное знание, ломкое при будущих правилах; статус — факт той же проекции, нулевая цена.

### 3.2. Где собирается — роутер, не движок

`_explanation_for_recommendation(recommendation, statuses, node_facts)` в `apps/api/routers/progress.py`: (1) `recommended_action` → пара `(stage, node_id)` (единый формат `stage.node_id` §7.1 — у Слоя A это цель правила, у Слоя B — `entry.deep_link`); (2) запись реестра объяснимости по составному ключу — промах → None (процессные правила modeling/forecasting и неизвестные узлы честно без объяснения); (3) статус узла из `projection.node_statuses` ∈ {error, warning} — иначе None (объяснение «почему жёлтый» только у проблемного узла; защитный инвариант на будущее); (4) факты из уже собранного `node_facts` (второй сборки нет); (5) заголовок методологии — `load_registry().find_article_by_id(entry.help_entry_id)`.

Почему не движок: канон «правила — чистые функции, данные приносит роутер» — объяснение есть данные (факты + ссылка), не решение; контракт движка (188 тестов MNS-FALLBACK-4/Слой A) не расширяется; доступ к реестру знаний из `apps/api` — тот же пакет, что knowledge-роутер. Ноль нового I/O на запрос: реестр знаний — артефакт, загруженный один раз на процесс (lru_cache), факты — та же проекция AUDIT-5B.

### 3.3. Доступ к статье знаний по id

`KnowledgeRegistry.find_article_by_id(article_id) -> Optional[KnowledgeArticle]` — аддитивный публичный доступ (приватный `_article_index` уже индексирует ВСЕ статьи: библиотека + справка). Join по `help_entry_id` честнее вывода facet-конвенции на месте вызова («upload → module_help, иначе metrics» — знание Terminологии уже страхуется сюитом реестра, дублировать его в роутере не нужно). Промах — None («no fabricated results», паттерн find_article).

### 3.4. Рендер в MentorPanel (аддитивно)

Под сообщением рекомендации (внутри жёлтой карточки, до deep-link) — блок объяснения: заголовок «Почему остановка жёлтая» / «Почему остановка красная» (по `explanation.status`), строки «Причина: …» и «Проблем по бейджу остановки: N» — только при непустых фактах (None — строка не рисуется, сообщение уже несёт честную формулировку), строка «Методология: «<methodology_title>»» — при известном заголовке. Рекомендация без `explanation` (старый контракт, процессные правила) — блок не рендерится. Deep-link MNS-LINK-3 не меняется: аналитик попадает на остановку, где вербатим «Метрики и алгоритм» и так показан окном модуля — ссылка Q7 замыкается переходом.

### 3.5. Советы — не факты (§3.2)

Объяснение живёт только в HTTP-ответе: `MentorObservation` (факт выдачи) не имеет поля объяснения и не получает его; трасса слоя 1/2 не дописывается; `watermark`/`events_total` — прежние. Тест-пин: после GET next-step размер трассы не изменился.

## 4. Точки изменения

1. `apps/api/knowledge/registry.py` — публичный `find_article_by_id` (аддитивный доступ, докстринг).
2. `apps/api/routers/progress.py` — `MentorExplanationOut`; поле `explanation` на `MentorRecommendationOut`; helper `_explanation_for_recommendation`; проводка в эндпоинт (facts уже собраны — повторного `_node_facts_for_mentor` вызова нет); докстринги.
3. `packages/ui/lib/mentor.ts` — `MentorExplanationInfo` + опциональное `explanation` на `MentorRecommendationInfo`.
4. `packages/ui/components/MentorPanel.tsx` — блок объяснения (аддитивный рендер).
5. `tests/api/test_mentor_rules.py` — контур `TestNextStepExplanationMNS5` (REST: Слой B validation/upload/error, Слой A preprocess-правило, процессное правило — None, форма ответа аддитивна ровно одним ключом, советы-не-факты; unit: парсинг action, промахи реестра, щит фактов, честный None заголовка).
6. `packages/ui/components/MentorPanel.test.tsx` — контур объяснения (рендер, error-заголовок, старый контракт без блока, None-факты).
7. `docs/mentor_text5_2026-10-19.md` (этот документ), `worklog/worklog10.md`.

## 5. Риски и меры

- **Поломка существующих потребителей** — поле optional/default None; точных JSON-равенств в тестах нет; фронт-типы опциональны; гвард аддитивности тестом формы ответа (ровно одно новое поле).
- **Дрейф терминологии методологии** — заголовок берётся вербатимом из артефакта промоушена (байт-паритет с TS-реестром страхует promote-тест); новых текстов нет; промах — честный None.
- **Расширение скоупа движка** — движок не тронут (diff только роутер/фронт); пины Слоя A/B MNS-FALLBACK-4 остаются зелёными.
- **I/O на запрос** — load_registry lru_cache (одна загрузка на процесс), факты уже посчитаны; второй проход по node_states не заводится.
- **Советы в трассе** — тест-пин неизменности трассы после вызова next-step.
