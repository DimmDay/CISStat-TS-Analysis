# MNS-FALLBACK-4 — Слой B: fallback-скан в evaluate_next_step, проект решения

Дата: 2026-10-19. База: `main@88b464c` (MNS-LINK-3 принят командой дословно). Задача из плана `docs/mentor_next_step_review_2026-10-19.md` §6; контракт — `spec_mentor_next_step.md` §2/§3/§5, §8 (DoD), §9 (критерии приёмки 1–7). Зависимость: MNS-REG-2 (реестр `rules/mentor_stop_explanations.json` + загрузчик `app/core/mentor_explanations.py`) — завершён.

## 1. Постановка и границы

DoD плана: «RED: жёлтый узел вне 8 правил — рекомендация None (самопротиворечие §2.2(д)); GREEN: инвариант + ONE-recommendation + порядок error/warning + приоритеты специфичных правил не изменились; 121 существующий тест зелёный». Спека §8: «Слой B в evaluate_next_step: error-проход → warning-проход по канону; сборка рекомендации из реестра MNS-REG-2».

Вне скоупа: аддитивное поле `explanation` ответа (MNS-TEXT-5), рендер в панели (там же), EDA warning (Q3), процессные стадии в скане (Q4), §7.2 sanity/thrashing/derived_spikes, `session.stages`, RAGFlow-рендерер. Существующие 8 правил не переименовываются, приоритеты не меняются (гвард канон-блока).

## 2. Проверенное по коду состояние

- `evaluate_next_step` (mentor_rules.py:611) — прогон 8 правил по `(priority, rule_id)`, первое сработавшее; иначе `None` — точка закрытия самопротиворечия §2.2(д) (панель жёлтая, ответ «тишина»).
- Реестр MNS-REG-2 готов: `MENTOR_STOP_EXPLANATIONS` (25 записей, порядок == канон сканирования §3.1 —validated fail-closed), `stop_explanation(stage, node_id)` (fail-closed ValueError), `render_stop_explanation(entry, status_reason=, summary_count=)` (честные плейсхолдеры «причина не отчитана»/«не отчитано»), `SCAN_STAGES = (upload, validation, preprocessing)`. Докстринг загрузчика прямо называет MNS-FALLBACK-4 потребителем: «fallback-скан не должен стартовать с частичной картиной объяснимости» — import fail-closed реестра из движка правил санкционирован.
- Факты узлов уже посчитаны: `projection.node_states` (AUDIT-5B, `fold.node_states_with_evidence`) несёт `stage/node_id/status/status_reason/summary_count` — тот же снапшот, что у панели и отчёта; `evaluate_next_step` сегодня получает только `statuses` (`projection.node_statuses`).
- Статусы узлов: `CHECK_STATUS_VALUES` (error/warning/pending/skipped/running/done); ни одно из 8 правил не смотрит на `error` (review §2.2(г)); условия правил — точечные `==`, error-статус не запускает ни одно из них (проверено чтением условий).
- Потребители `evaluate_next_step`: только `apps/api/routers/progress.py:1954` (+ тесты); сертификационный оракул `progr6cert_oracles.py` импортирует, но не вызывает — расширение сигнатуры keyword-only безопасно.

## 3. Проект решения

### 3.1. Слой B — чистая функция поверх того же снапшота

`_fallback_recommendation(statuses, node_facts)`: два прохода по `SCAN_STATUS_PRIORITY = ("error", "warning")` (канон-блок §3.1, решение Q2); внутри прохода — канон `SCAN_STAGES × STAGE_NODES` (стадии в порядке STAGES, узлы в порядке реестра — решение Q1/Q5: глобальный канон, «текущая вкладка» скан не знает); первый узел с точным совпадением статуса останавливает скан. ЭДА/Моделирование/Прогнозирование в обходе отсутствуют по построению (Q3/Q4). Детерминизм: никаких множеств/словарей с непорядком, только последовательные реестры; ноль нового I/O.

Сборка рекомендации (спека §5.1): `rule_id` — синтетические константы семейства `FALLBACK_ERROR_RULE_ID="fallback_error"` / `FALLBACK_WARNING_RULE_ID="fallback_warning"` (НЕ новые специфичные правила — в NEXT_STEP_RULES не добавляются, канон-блок спеки не меняется); `stage` — стадия узла; `recommended_action = entry.deep_link` (== "stage.node_id", контракт MNS-LINK-3 — фронт уже ведёт на остановку); `message = render_stop_explanation(entry, status_reason, summary_count)` — подстановка уже посчитанных фактов, недостающий факт честно называется недостающим.

### 3.2. node_facts — аддитивный keyword-only параметр

`evaluate_next_step(statuses, *, node_facts=None, renderer=None)`: `node_facts` — mapping `"stage/node_id" → {status_reason, summary_count}` из `projection.node_states` (роутер приносит факты — канон «данные приносит роутер, хранилища не импортируются»; ноль reshape-логики в движке). `None` (старые вызовы/тесты) — честные плейсхолдеры средствами `render_stop_explanation`. Порядок слоёв: Слой A прежний (сортировка не тронута) → при пустом результате Слой B. Renderer Protocol остаётся точкой Слоя A: текст Слоя B — из реестра, renderer на fallback не вызывается (пин-тест; LLM-точка §8 не решает «есть ли проблема»).

### 3.3. Роутер — ноль нового I/O

`get_mentor_next_step`: helper `_node_facts_for_mentor(projection)` собирает mapping из `projection.node_states` (уже посчитан в `_build_from_fold`; тех же фактов, что бейджи панели). Телеметрия `_record_next_step_observation` работает без изменений (rule_id/stage универсальны); ответ аддитивен (MentorRecommendationOut прежних 4 полей).

### 3.4. Инвариант и тишина

Инвариант §2: узел error/warning на warning-способной стадии ⇒ рекомендация != None (Слой A или Слой B) — проверяется параметризованным тестом по всем 25 остановкам × {error, warning}. Тишина честна: нет проблемных узлов И неактуальны процессные гэпы — прежние тесты тишины остаются зелёными.

## 4. Точки изменения

1. `app/core/mentor_rules.py` — импорт трёх имён из `app.core.mentor_explanations` (направление зависимостей: данные/конфиг, не хранилище — спека §6); константы семейства + fail-closed самопроверка на импорте (покрытие SCAN_STATUS_PRIORITY, дизъюнкция с rule_id Слоя A — паттерн модуля); `_fallback_recommendation`; расширение `evaluate_next_step` (сигнатура обратно совместима); докстринги (v2-гибрид).
2. `apps/api/routers/progress.py` — helper + передача node_facts (2 строки логики); комментарий-докстринг.
3. `tests/api/test_mentor_rules.py` — новый контур TestNextStepFallbackLayerB (инвариант 25×2 параметризацией, порядок error>warning, канонный порядок стадий/узлов, Слой A старше Слоя B, честная тишина, исключённые стадии, детерминизм, подстановка фактов/честные плейсхолдеры, текст из реестра мимо renderer, константы семейства, REST end-to-end с событием validation_check_status).
4. `worklog/worklog10.md`, `docs/mentor_fallback_2026-10-19.md` (этот документ).

## 5. Риски и меры

- **Взрыв if/elif по 25 остановкам** — исключён по построению: скан по реестрам (STAGE_NODES), текст — из реестра объяснимости (урок PROGR-15-B→PROGR-19).
- **Двойной редьюсер статусов** — исключён: Слой B читает только `statuses`/`node_facts` той же проекции AUDIT-5B.
- **Дрейф канона** — скан НЕ копирует канон-блок: `SCAN_STAGES` (реестр REG-2, валидирован против STAGE_NODES) × `STAGE_NODES`; порядок error/warning — константа == канон-блоку, страхуется гвардом спеки (scan_status_priority) и тест-пином констант.
- **Тихий сдвиг семантики Слоя A** — приоритеты/правила не тронуты; гвард канон-блока (test_mentor_next_step_spec.py) + 121 тест остаются зелёными; пин «Слой A старше Слоя B» — явным тестом.
- **Флаки REST-теста** — событие validation_check_status сеется штатной фабрикой make_trace_event; изоляция autouse-фикстурой (_isolated_environment).
