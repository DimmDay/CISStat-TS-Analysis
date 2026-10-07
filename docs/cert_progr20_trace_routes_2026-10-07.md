# Акт независимой сертификации Task PROGR-20
## Расширение TRACE_ROUTES: P0 (candidates, selection/evaluate) обязательно, P1/P2 — решение тимлида (spec_progress_v1.1.md §1, категория A)

Дата: 2026-10-07. Аудитор: независимый сертификатор (Senior-разработчик платформы).
База аудита: `main@ed26476` (HEAD; PROGR-20 — коммит `18e4871`, поверх него
фикс находок R3_R7 `ed26476`). Рабочее дерево чистое (кроме артефактов самой
сертификации). Постановка аудита: честная сертификация по практике проекта
(прецеденты PROGR-1-CERT, PROGR-13-CERT, PROGR-17-CERT, PROGR-18-CERT):
изучение spec_progress_v1.1.md и живого кода, НЕЗАВИСИМЫЕ мутационные пробы
на СВОИХ мутантах (AM-1..AM-8 — не копия M-1..M-6 реализатора), оракулы на
СВОИХ данных, воспроизведение RED-состояния, сверка фактов worklog8.md с
кодовой базой. AGENTS.md соблюдены: commit/push НЕ выполнялись.

---

## 1. Предмет сертификации

PROGR-20 (spec_progress_v1.1.md §1, категория A; §6 сводный план): плановое
расширение fail-closed allowlist `TRACE_ROUTES` мутирующими эндпоинтами
Моделирования — фактами, которые раньше не оставляли следа в трассе вовсе.
Критерий приёмки v1.1 §7: «TRACE_ROUTES включает как минимум оба P0».
Таблица v1.1 §1: P0 — `candidates`, `selection/evaluate`; P1 — `compare`,
`diagnostics`×2; P2 — `tuning/skip`×2, `jobs`×3; «Не включать» —
`validation-rules`, `type-schema`. Решение тимлида по P1/P2 зафиксировано:
P1/P2 включить, кроме `jobs/{id}/step` (механические единицы работы —
прогресс-лог, не журнал решений) и путей вне таблицы v1.1 (`baselines`,
`backtest/exclude`, `feature-regressors`, `tuning/start`, `tuning/step`).

## 2. Сверка реализации с кодовой базой (все точки на месте)

| Точка | Файл | Верификация |
|---|---|---|
| 7 новых типов реестра | `apps/api/trace_events.py` | `candidates_generated`, `selection_evaluated`, `models_compared`, `diagnostics_run`, `tuning_skipped`, `tuning_job_started`, `tuning_job_cancelled` в `_STAGE_EVENT_TYPES["modeling"]`, комментарий-корень по каждому (в т.ч. обоснование «НЕ дублирует tuning_trial_completed» и «jobs/{id}/step сознательно НЕ трассируется»); `STAGE_EVENT_TYPES` — frozenset-проекция |
| 9 новых строк таблицы | `apps/api/trace_hook.py` | P0: `candidates`→узел `candidate_generation`, `selection/evaluate`→`selection`; P1: `compare`→`comparison`, `diagnostics`+`diagnostics/ensure`→`diagnostics` (один тип, payload различает calculated/reused); P2: `tuning/skip`+`skip-pending`→`tuning`, `jobs/start`→`tuning_job_started`, `jobs/{job_id}/cancel`→`tuning_job_cancelled`; все `preview_type is None`, `throttled is False` |
| Dotted-ключи payload | `apps/api/trace_hook.py` `_extract_payload` | `statistics.runnable_candidates/catalog_only_candidates/blocked_candidates`, `recommended_single.model_id`, `ensemble.status`, `progress.total_steps`, `cancellation.reason` — под ПОСЛЕДНИМ сегментом (паттерн `metrics.mape` PROGR-8); тяжёлые массивы (candidates/catalog/diagnostics/member_ids/baseline_comparisons) отсечены whitelist'ом |
| Fail-closed валидатор таблицы | `apps/api/trace_hook.py` `_validate_table` | дубликаты маршрутов, невалидные пары (stage, event_type), неизвестные узлы графа, throttled≠profile_viewed, forecasting-гейт — `ImportError` на импорте; расширенная таблица (53 строки) проходит |
| Механизм шаблонов | `resolve_trace_route` | `{job_id}` матчит любой непустой сегмент; пустой сегмент и лишние сегменты не матчятся (оракул B3) |
| Фронтенд | — | БЕЗ изменений (git show --stat 18e4871: ни одного .ts/.tsx) — корректно: `ProgressTraceLog` рендерит event_type как есть; новые типы НЕ введены в `EVENT_NODE_STATUS`/`PAYLOAD_STATUS_EVENT_TYPES` — свод панели не меняется (проверено оракулом D4: `last_touched_at` обновляется, `status_reason` остаётся None, статус не красится) |
| Спецификация | `spec_progress.md` §4.1 | modeling-строка +7 типов; абзац PROGR-20: решения P0/P1/P2, исключения, замечание о путях (stateless-зеркало), потребители |
| Тесты | `tests/api/test_progress_trace_hook.py` (секции 9–10, 9 тестов), `tests/api/test_trace_events.py` (миграция `test_registry_per_spec_table` +7) | на месте, зелёные; миграция контракт-теста — точное равенство множества modeling |

Соответствие постановке v1.1 §1 подтверждено: allowlist-архитектура не
заменена («fail-closed, не fail-open»), расширение плановое, решения P1/P2
зафиксированы и в коде, и в тестах, и в спецификации. Замечание о путях
проверено независимо: `POST /v1/models/candidates` (stateless, API-key) в
таблице ОТСУТСТВУЕТ, сессионный носитель факта
`POST /v1/session/modeling/candidates` — присутствует.

## 3. Независимая верификация приёмки (аудитор, своё окружение)

- Среда: pywavelets/pandera/arch/statsforecast/tbats/psycopg2-binary/
  sqlalchemy/ruptures/prophet/psycopg — уже в контейнере (средовое, код не
  касается). База `ed26476` — свежий pull origin/main.
- Целевые файлы: `test_progress_trace_hook.py` + `test_trace_events.py` —
  **73/73 GREEN** (сходится с записью: 49 trace_hook + 24 trace_events).
- **RED воспроизведён 1:1**: реализация 7e800c6 (trace_hook.py +
  trace_events.py) при текущих тестах — РОВНО 8 failed / 1 passed из 9
  новых; зелёный ДО кода — `test_progr20_conscious_exclusions_stay_untraced`
  (контракт-инвариант исключений, паттерн PROGR-19). Восстановление — по
  backup-копии с байт-контролем `cmp`, повторный прогон 73/73.
- Полный `tests/api`: **1363 passed / 1 skipped / 19 failed** — все 19
  совпадают 1:1 со средовым базлайном (forecasting_session ×16,
  modeling_workflow catalog-only гейт, models_backtest_neural_capacity
  память хоста, models_candidates unsupported-гейт); 1363 = 1351 (запись
  PROGR-20) + 12 от последующих тестовых коммитов (0fc5293, ed26476).
  Ноль новых регрессий.
- Jest/typecheck/build аудитором не запускались СОЗНАТЕЛЬНО: коммит PROGR-20
  не содержит ни одного .ts/.tsx (паттерн PROGR-19) — заявление записи
  подтверждено составом коммита.

## 4. Оракулы аудитора на СВОИХ данных — 16/16 GREEN (scripts/progr20cert_oracles.py)

Датасет аудита: **cert20_weekly_demand_n156.csv** — НЕДЕЛЬНЫЙ ряд спроса,
156 точек (3 года, 2022-01-02..2024-12-29), date/sales; тренд 0.8/нед +
треугольная годовая сезонность (амплитуда 30) + детерминированный
псевдошум ((i·37)%11−5)·0.6. Не пересекается ни с fixtures коллеги
(месячный monitor 150), ни с оракулами PROGR-17-CERT (недельные продажи
120), PROGR-18-CERT (суточный трафик 210), ни с месячным MS-96
реализатора PROGR-20.

- **A — отпечатки своих данных** (applicability-движок на своём датасете,
  spec v1.3.1): каталог 24 модели == total_models_in_spec == len(catalog);
  пул 10 RECOMMENDED, catalog_only 5, blocked 4 (сумма 19 < 24 —
  вне тройки остаются не-рекомендованные без production backtest —
  семантика честная); naive/ets/theta в пуле; payload события
  `candidates_generated` == статистике СВОЕГО ответа (не шаблон).
- **B — механика allowlist на своих пробах**: 9 строк → точная тройка
  (stage, node, type) на живых path-пробах с uuid вместо {job_id};
  метод-гейт (GET/PUT/DELETE мимо); шаблон: uuid-матч, пустой сегмент —
  нет, лишний сегмент — нет; 8 негативных проб (исключения + вне таблицы);
  критерий приёмки v1.1 §7 структурно (оба P0) + счётчик 53.
- **C — форма payload на своих телах**: dotted-ключи — под последним
  сегментом, полные dotted-ключи не утекают; тяжёлые массивы
  (recommended_single.oof, ensemble.member_ids, baseline_comparisons)
  отсечены; отсутствующий промежуточный уровень — ключ честно опущен
  (нет мусора/краха); non-dict intermediate → {}; total_steps из СВОЕГО
  запроса (max_trials 3 → 5 в теле → payload 5).
- **D — e2e на своих данных**: полный контур Моделирования в живой трассе
  (D1): candidates ×2 → ровно 2 события (моделирование НЕ троттлится —
  отличие от EDA), backtest naive+ets (cohort-отпечаток своих данных),
  diagnostics прямые ×2 (payload backtest_run_id == своему ответу,
  params_source whitelist), ensure (union calculated|reused == своему
  ответу), compare (comparison_id/cohort_id/objective == своим ответам),
  selection/evaluate (selection_analysis_id, model_id из СВОЕГО пула,
  status whitelist), skip-pending «unchanged» после полного закрытия scope,
  jobs start/cancel (total_steps==3 от своего max_trials=3; причина отмены
  — своя строка). D1b — добавление аудитора (e2e реализатора на
  skip-pending не было): «skipped» со списком СВОИХ pending-tuning моделей
  → повтор «unchanged» — единственная причина второго события — пустой
  pending (честный след идемпотентного выбора). D2 — зеркало слоя 2
  (research_runs): событие candidates_generated дошло до Наставника/
  admin-аналитики. D3 — 422 (невалидная strategy) / 405 (метод) / 409
  (skip без acknowledge) — ни одного нового события. D4 — панель:
  last_touched_at узла обновлён фактом, status_reason None, статус не
  покрашен (новые типы вне EVENT_NODE_STATUS — свод не меняется). D5 —
  регресс-страж «существующие не сужены»: backtest_run с metrics.mape.

Примечание протокола (честно): первые две итерации D1 падали на ОРАКУЛЕ,
не на реализации — compare/evaluate требуют полного закрытия runnable-scope
(pending_backtests И pending_tuning, честные 409-детейлы), а scope в
`/state` — устаревший артефакт. Контур перестроен на управление от этих
409-детейлов (исключения backtests, явные /tuning/skip для pending_tuning)
— что само по себе дало аудиту дополнительное наблюдение R5.

## 5. Мутационный прогон аудитора — 8 СВОИХ мутантов: 7 KILLED / 1 SURVIVED (87.5%)

Протокол: scripts/progr20cert_mutations.py, журнал
scripts/progr20cert_mutation_results.txt. Каналы фиксировались раздельно
(T — репозиторий 73 теста; O — оракулы 16). Каждый мутант — ровно одна
замена (скрипт падает громко при 0/≥2 вхождениях — невалидный мутант
невозможен); откат по backup-копии с байт-контролем `cmp`; финальный
контроль — оба канала зелёные. Все 8 ожиданий сошлись.

| Мутант | Поверхность | T | O | Вердикт |
|---|---|---|---|---|
| AM-1 метод-гейт: POST→GET на P0-строке candidates | таблица (дисциплина метода) | убит (rows_present, e2e candidates) | убит (B1/B2/B5/D1/D2…) | KILLED |
| AM-2 flatten по ПЕРВОМУ сегменту (rsplit→split) | семантика хранения dotted | убит (payload_dotted + e2e ×3) | убит (A2/C1/C2/C3/D1/D2) | KILLED |
| AM-3 подмена на ВАЛИДНЫЙ тип: models_compared→backtest_run (гейт проходит, без ImportError) | различимость типов внутри стадии | убит (rows_present, e2e compare) | убит (B1/D1) | KILLED |
| AM-4 дегенерация шаблона: /jobs/{job_id}/cancel → /jobs/cancel | механизм {param} на живом пути | убит (rows_present, payload, e2e cancel) | убит (B1/B3/C2/D1) | KILLED |
| AM-5 superset-дрейф реестра: +phantom_modeling_type | слабость `>=`-ассерта локального теста | убит ТОЛЬКО контракт-тестом test_registry_per_spec_table | НЕ пойман (у оракулов нет точного равенства реестра) | KILLED (2-я линия обороны) |
| AM-6 ослабление гейта статуса: >=400 → >=500 (4xx стали бы фактами) | единственный gate middleware | убит (unsuccessful_responses_not_traced) | убит (D3) | KILLED |
| AM-7 потеря атрибуции: run_id=session.run_id → '' | §5-привязка факта к исследованию | убит (first_upload, correction, e2e candidates) | убит (D1) | KILLED |
| AM-8 снятие store.save(session) в _record | персистентная граница слоя 1 | ВЫЖИЛ (exit=0) | ВЫЖИЛ (exit=0) | SURVIVED — ожидаемо, класс BM-H/R4 |

AM-8 — ожидаемый выживший: MemorySessionStore.get возвращает объект ПО
ССЫЛКЕ (алиасинг), мутации видимы без save() — граница сериализации
(RedisSessionStore) на hook-пути тестом не застрахована. Это НЕ дефект
PROGR-20: save() вызывается корректно, находка класса BM-H/R4
(PROGR-17-CERT) относится ко ВСЕМ hook-маршрутам с PROGR-3; для отчётных
контуров (validation/preprocessing) закрыто тестом Пр-4 (PROGR-17-CERT-R1R4).

## 6. Находки (не блокируют)

- **R1 (низкая, покрытие)**: персистентность слоя 1 hook-пути через
  настоящую границу сериализации не покрыта (AM-8 SURVIVED в обоих
  каналах). Рекомендация: fakeredis-тест в духе Пр-4 — один прогон
  middleware-записи с перезачиткой store.get после save (общая задача для
  контура PROGR-3..20, не отдельная на PROGR-20).
- **R2 (информационная)**: локальный
  `test_progr20_registry_accepts_new_event_types` комментирует «ровно 7
  новых», но ассерт — superset (`>=`): дрейф реестра ВВЕРХ ловится только
  контракт-тестом `test_registry_per_spec_table` (AM-5 убит именно им;
  канал O не ловит — у оракулов нет точного равенства реестра). Двойная
  оборона сработала; при желании ассерт можно усилить до `==` над
  разницей с прежним множеством.
- **R3 (информационная, закрыта аудитом)**: e2e skip-pending реализатором
  честно не прогонялся («таблица+payload-тесты покрывают контракт»).
  Оракул D1b закрывает пробел на своих данных: «skipped» → «unchanged»,
  payload-различение веток, stage/node.
- **R4 (информационная, наблюдение о представительной e2e)**: в e2e
  реализатора compare/evaluate выполнялись в сессии БЕЗ вызова candidates —
  гейт полного закрытия runnable-scope (pending_backtests + pending_tuning)
  проходил тривиально. На СВОИХ данных (пул 10 моделей) аудитор подтвердил
  работоспособность полного контура через честные 409-детейлы; факты пишутся
  только на успешных ответах — гейт модуля на трассу не влияет.
- **R5 (информационная, документировано реализатором)**: расхождение путей
  v1.1 («POST /v1/models/candidates») с сессионным носителем факта
  (/v1/session/modeling/candidates) разрешено корректно: stateless-зеркало
  не имеет исследовательской сессии — атрибутировать факт некуда;
  проверено независимо (stateless-путь в таблице ОТСУТСТВУЕТ), замечание
  зафиксировано в spec_progress.md §4.1.

## 7. Вердикт

**PASSED WITH REMARKS.** Критерий приёмки v1.1 §7 «TRACE_ROUTES включает
как минимум оба P0» выполнен и подтверждён независимо (структурно B5 и
e2e D1 на своих данных). Все заявления worklog8.md воспроизведены 1:1:
RED (8 failed / 1 инвариант зелёный ДО кода), GREEN 73/73, счётчик 53,
мутационные пробы реализатора 6/6 KILLED (перечень совпадает с
протоколом), полный tests/api — средовой базлайн 1:1 без новых регрессий,
фронтенд сознательно не менялся. Ядро контракта (таблица → middleware →
событие слоя 1 → зеркало слоя 2 → панель/отчёт) убой-консистентно: 7/8
своих мутантов убиты, единственный выживший — известный класс
персистентной границы, общий для всего hook-контура с PROGR-3 и не
затронутый PROGR-20. Находки R1–R5 не блокируют.

## 8. Deliverable

ZIP `cisstat-progr20-certification.zip`: docs/cert_progr20_trace_routes_2026-10-07.md,
scripts/progr20cert_oracles.py, scripts/progr20cert_mutations.py,
scripts/progr20cert_mutation_results.txt, worklog/worklog8.md.
Без commit/push (AGENTS.md).
