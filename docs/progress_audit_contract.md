# docs/progress_audit_contract.md — контракт «Прогресса» как документирующего контура

Редакция: **v0.2-AUDIT-S** (v0.1-AUDIT-0 + аддендум §12 задачи AUDIT-S, plan_progress_audit.md §5).
Дата: 2026-10-09. База: v0.1 — `main@6a83924`; v0.2 — `main@deaed93` (AUDIT-0 принят).
Полномочия: `spec_progress_audit.md` §5–9 (исследовательский аудит, PROGR-AUDIT-1), `plan_progress_audit.md`
§4 (карточка AUDIT-0) + разделы «Донастройка плана» (рецензия тимлида). Все последующие задачи
плана (AUDIT-C/6A/5B/1a/4/2A/2B/3/8/7A/7B/6B/6C/CERT) ссылаются на ЭТУ редакцию контракта;
изменение решения — новая редакция с журнальной фиксацией, не тихая правка.

Статус решений: пункты, помеченные **УТВЕРЖДЕНО-AUDIT-0**, зафиксированы настоящим документом и
обязательны для задач реализации. Пункты, помеченные **ОТКРЫТО**, сознательно не решены и требуют
отдельного решения тимлида/задачи. Планирование гарантий не делает их доступными (план §4).

---

## 1. База задачи AUDIT-0 (входные условия зафиксированы)

| Пункт | Факт |
|---|---|
| HEAD / рабочее дерево | `main@6a83924`, tracked-файлы чистые (filemode-шум погашен `core.filemode=false`, прецедент PROGR-24-ORIGIN-C); commit/push НЕ выполнялись (AGENTS.md) |
| Продуктовый код vs база аудита | `git diff c8818de..6a83924 -- apps/ app/ packages/ shared/ rules/` — ПУСТО (только spec/plan/scripts/worklog): все наблюдения аудита действительны на 6a83924 без пересчёта |
| Окружение | Python 3.12.14 (venv), pandas 2.3.3, statsmodels 0.15.0, PyWavelets 1.8.0, pandera 0.34.1, statsforecast 2.1.1, arch 8.0.0, ruptures 1.1.10 («лёгкая группа» по рецепту PROGR-25-A-CERT R6); Node v24.21.0, npm 11.19.0, node_modules восстановлен `npm ci`; fakeredis доступен |
| Контрольный прогон инструмента аудита на 6a83924 | `scripts/progress_audit0_baseline_control.json` — **25 OBSERVED / 0 PROBE_ERROR** (оригинал `scripts/progress_audit_readonly.py` не изменён) |
| Повтор P01–P25 на СВОИХ CSV | `scripts/progress_audit0_repro.py` → `scripts/progress_audit0_repro_results.json` — **25 OBSERVED / 0 PROBE_ERROR**. Данные: `date,temp` / `date,temp,humidity`, 20 строк 2026-02-01..20, значения i·1.8 / i·0.35 (у автора — rain/snow, 2026-01-xx). Стенд — САМ оригинальный инструмент (реальные session/progress routers + handle_upload + TraceHookMiddleware), загружен importlib по пути файла без изменений; ассерты адаптированы эквивалентно (имена колонок). Один дефект первой прогона (P10: хелпер `event` оригинала жёстко кодирует run_id="RUN-AUDIT") исправлен явной конструкцией события — не правкой инструмента |
| Тестовый PostgreSQL | В песочнице НЕ развёрнут (Донастройка_2 п.1: подготовить ДО AUDIT-6A). Все проверки P08–P10/P21 — Memory/fakeredis; live-Postgres приёмки AUDIT-6A/6B остаются открытыми до появления тестовой БД |
| Импортируемость `apps.api.main` | В лёгком окружении НЕ импортируется (readiness-гейт Modeling dispatch, Runtime «Реестр готовности моделей расходится…») — как в PROGR-AUDIT-1. Починка — в периметре AUDIT-6C (Донастройка_2 п.2) |

Ограничения базы (наследуются из аудита §3.2): component-integration на Memory/fakeredis, не production E2E; Render/Vercel/браузер/живой PostgreSQL не проверялись; наблюдение дефекта — успех исследовательской проверки, не признание поведения корректным.

## 2. Статусы открытых гипотез H26–H30 (карточка AUDIT-0, действия 2–3)

| Гипотеза | Метод | Статус | Наблюдение (свои артефакты) |
|---|---|---|---|
| **H26** — при неизменном snapshot один отказ доставки UI остаётся без автоматического повтора | React-мок продюсера EDA (`packages/ui/components/prograudit0_h26_no_auto_retry.test.tsx`); контур-близнец Валидации — та же форма effect (`TsAnalysisValidation.tsx:410-442`) | **OBSERVED** | Seed `/trace` → POST `/eda-checks` → 500 → маркер сброшен, НО effect зависит от снапшота: без изменения snapshot повторов НЕТ (пауза 120 мс — ровно 1 POST); смена снапшота (новый просмотр) возобновляет контур (POST #2). Существующий пин PROGR-16-A-R2 («после неудачного запуска 2 отчёта НЕТ, если снапшот null») согласован: повтор сейчас возможен ТОЛЬКО через изменение снапшота — автоматического повтора неизменного тела нет |
| **H27** — отказ EDA seed может понизить уже просмотренные исследования | React-мок двух фаз (`prograudit0_h27_seed_failure_regresses.test.tsx`) | **OBSERVED** | Фаза 1: seed `/trace`=200 {descriptive, correlation: done} → просмотр seasonality → POST #1 {descriptive/correlation/seasonality: done} (факты приняты). Фаза 2 (перемонтирование): seed `/trace`=**500** → пустой seed-set → POST #2 {descriptive: done, **correlation: pending, seasonality: pending**} — карта несёт pending для ранее done-проверок; бэкенд last-wins записал бы регресс (P25 подтверждает запись на живом контуре). Следствие для AUDIT-3: seed должен браться из полной проекции; разрушительная пустая/деградировавшая карта поверх known history недопустима |
| **H28** — при смене цели/in-place коррекции UI переносит EDA-просмотры прежних данных | React-мок (`prograudit0_h28_viewed_transfer.test.tsx`) | **OBSERVED** | datasetId фиксирован; смена цели Price→Volume (POST `/target-column`) при неизменном datasetKey: повторного seed НЕТ (GET `/trace` = 1 за сценарий), reset-эффект не сработал, следующий отчёт несёт descriptive=done из прежней целевой вселенной + correlation=done новой. Следствие для AUDIT-3/C: сброс keyed ТОЛЬКО по datasetKey (`TsAnalysisEDA.tsx:1000-1005`) — target/revision в ключе не участвуют; old-viewed остаются «действующими» без новой версии результата |
| **H29** — Render фактически не гарантирует durable-хранение корпуса | Требуется read-only доступ к deployment-логам/БД Render | **НЕ ПРОВЕРЕНО** (план §4 действие 3: без доступа не проверять) | Необходимые данные (для AUDIT-6C): (а) deploy-манифест/логи старта render.com-сервиса — фактический `CISSTAT_RUNS_BACKEND` и boot-id; (б) при PostgreSQL — наличие `DATABASE_URL`/драйвера в образе, состояние миграций `0001_research_runs.sql`; (в) устойчивость известного run_id/файла между двумя известными boot-id. Секреты и содержимое датасетов не выводить. Не инициировать restart/artificial failures |
| **H30** — P22 (ответ до записи хука) даёт видимую гонку panel/mentor в эксплуатации | Требуются access/trace логи одного request-id или локальный стенд с блокировкой хука | **НЕ ПРОВЕРЕНО** | P22 (порядок `final_body_sent` → `record`) воспроизводится стабильно локально; живая частота гонки не измерена. Необходимые данные: пары «ответ/чтение trace» по одному request/correlation-id либо контролируемая блокировка hook-записи на стенде. Контрактное решение уже зафиксировано (§4-D6): required-контур получит read-after-watermark; advisory остаётся честно best-effort |

Наблюдательные пины H26–H28 — не acceptance-suite: после исправления дефектов соответствующими задачами (AUDIT-2B/3) они заменяются/обновляются как versioned-обновление контракта (Донастройка_2 п.3), а не переписываются под реализацию.

## 3. Решения схемы (конкретизация таблицы плана §4)

### 3.1. Сброс цели — выделенный тип `target_column_cleared` — **УТВЕРЖДЕНО-AUDIT-0**

Решение (Донастройка плана, Часть 1): сброс цели — первоклассное событие ОТДЕЛЬНЫМ каноническим
типом, НЕ «пустой target в `target_column_changed`».

Контракт типа:

1. **Регистрация**: аддитивная запись `"target_column_cleared"` в `_STAGE_EVENT_TYPES["validation"]`
   (`apps/api/trace_events.py`, блок "validation" рядом с `target_column_changed`). Совпадает с
   носителем `target_column_changed` (stage=validation, node_id=None). Это v1-совместимое
   расширение реестра: legacy-корпус типа не содержит → миграция не нужна; неизвестный тип у
   каждого читателя деградирует честно («событие мимо фактов», не 500).
2. **Оговорка-разблокировка**: «добавление ТИПА события не ждёт AUDIT-S; добавление ПОЛЕЙ
   envelope — ждёт» (Донастройка, Часть 1). Тип и его редьюсер-ветки доступны горячей дорожке
   сразу после AUDIT-0; schema_version и новые поля — только с AUDIT-S.
3. **Payload**: `{target_column: null, reset_reason: str, source: "system"|"auto", before_target: str|null}`.
   - `reset_reason` — машинная причина ("type_conversion", …); перечисление причин фиксируется
     задачей-реализацией (первая — горячая дорожка F02).
   - `source` здесь — ИСТОЧНИК решения о сбросе (system/auto), не происхождение прежнего выбора;
     прежний выбор сохраняется в `before_target`.
   - Мусор в любых полях — деградация («событие мимо фактов»), не 500 (щит Mapping из C-CERT).
   - Whitelisting строго кодом: событие сеется кодом (по образцу `auto_fix_and_seed`), НЕ через
     TRACE_ROUTES; таблица маршрутов и `_CORRECTION_PAYLOAD_KEYS` не трогаются.
4. **Семантика origin после сброса**: после `cleared` происхождение текущей цели =
   **unknown/пусто (None), НЕ «user»**. Дефолт `_target_origin`="user" легитимен ТОЛЬКО для
   отсутствия поля у legacy-ВЫБОРА; после сброса «user» фабриковал бы человеческий выбор,
   которого не было (спека §4.1: различие user_decision / отсутствие решения).
5. **Разделение маршрутов**: `POST /v1/session/target-column` остаётся маршрутом ВЫБОРА с 422 на
   пустой (граница PROGR-25-C); сброс — только серверный producer в реальной точке решения.
   Маршруты не объединять.
6. **Двухслойность (канон R3)**: `cleared` сеется в слой 1 (`append_trace_event`) + зеркало слоя 2
   (`record_run_event`, общий event_id) в точке решения — по образцу `auto_fix_and_seed`
   (PROGR-25-C). Хронология: сброс → исход коррекции (`correction_applied` хука) — согласована с
   каноном «фиксация → upload_completed». Run-метаданные обновляются ТОЙ ЖЕ точкой:
   `target_column=None, target_column_source=None` (сейчас не обновляются вовсе — половина P03).
7. **Единый редьюсер**: choice/reset читаются ОДНИМ effective-target reducer'ом
   (session/run-метаданные, reason узла, Наставник, отчёт — потребители одной проекции). Правила
   Наставника (`_target_confirmed`/`_target_origin`/`_phase_event_text_facts`) становятся
   reset-aware: cleared снимает подтверждение и текущую колонку; после сброса условия честно
   падают в fallback «Подтвердите целевой признак…» (ожидание P03).

### 3.2. Новые поля — версионированный envelope v2 — **УТВЕРЖДЕНО-AUDIT-0**

- Канон `TraceEvent` (8 полей + legacy-алиас `timestamp`) сохраняется; новые поля вводятся
  АДДИТИВНО с `schema_version` (AUDIT-S). Существующие обязательные поля и алиас не переименовываются.
- `SESSION_SCHEMA_VERSION` (сейчас 3) поднимается только структурными изменениями документа
  сессии (прецедент PROGR-24-ORIGIN-A/F1: аддитивные Optional — без подъёма).
- `PipelineNodeState` (7 полей §3) — число полей не меняется скрыто; расширение носителей
  проекции (source_event_id, validity и т.п.) — отдельными versioned-контрактами ответов
  (`NodeStateOut`/`ProgressTraceResponse` — аддитивно, как PROGR-25-A).
- Каждому event_type — проверяемая схема обязательности новых полей (таблица AUDIT-S); «не все
  поля обязательны у каждого типа» (спека §8.1).

### 3.3. Порядок — commit sequence от ledger — **УТВЕРЖДЕНО-AUDIT-0**

- Авторитетный порядок — монотонная позиция, назначаемая ledger-хранилищем внутри run при
  фиксации (AUDIT-6A: `commit_event_batch`, транзакционная сериализация по run). BIGSERIAL сам по
  себе не принимается за committed-order (план §7).
- `ts` — описание времени наблюдения, НЕ порядок редьюсера. Один канонический порядок для всех
  потребителей (панель, Наставник, отчёт); сортировка одного корпуса по append в одном месте и
  по ts в другом — запрещена (контрпример P12/F08).
- Legacy-корпус без sequence: стабильный исходный store-order; неизвестное время не используется
  для переупорядочивания (план §5).

### 3.4. Контекст — fingerprint/revision/context_id — **УТВЕРЖДЕНО-AUDIT-0 (форма), детали AUDIT-C**

- Контекст расчёта = raw dataset fingerprint (sha256 файла) + `dataset_revision` + target/date
  колонки + настройки, влияющие на расчёт; сервер вычисляет/проверяет `context_id` — фронт
  контекст не создаёт догадками (план §1).
- Мутации DataFrame → новая ревизия данных; новая загрузка → новый run; смена цели/временной
  структуры → новый target/temporal scope; no-op не выдаётся за изменённые данные (план §6).
- Параметры диагностики образуют result context (два метода на одном ряде различимы без bump
  версии данных).
- Dependency scopes узлов — ОДИН реестр (`app/core/pipeline_graph.py`), инвалидирование
  зависимых результатов централизованное, исторические события не стираются (план §6).

### 3.5. Применимость — historical vs validity — **УТВЕРЖДЕНО-AUDIT-0**

- Историческое достижение (`done` в прошлом контексте) хранится и показывается отдельно от
  применимости к текущим данным: `validity ∈ {current, stale, unknown}` + ссылка на context.
- Старый факт без известного контекста — historical/unknown, НЕ автоматически current
  (план §8; спека §8.2: «Просмотрено на revision=3; текущая revision=4, результат не пересчитан»).
- Raw restore объявляет mode=raw и создаёт новую ревизию/контекст; не обещает восстановление
  промежуточного DataFrame; повторный авто-выбор как замена восстановлению запрещён (спека §8.2).

### 3.6. Доставка — advisory/required — **УТВЕРЖДЕНО-AUDIT-0**

- **advisory** — режим навигационной телеметрии: best-effort с ЧЕСТНЫМ состоянием (потеря
  совместима с HTTP 200 — P09/F15 остаётся допустимой для этого класса); панель/Наставник —
  advisory-потребители.
- **required** — для утверждений «операция документирована»: durable receipt, idempotency key
  (report_id/operation_id), восстановимое обязательство (outbox/ledger-обязательство в
  устойчивом хранилище), повтор по operation_id, который НЕ повторяет научную операцию.
  Перечень required-путей — явный (AUDIT-6B); пустое слово «durable» не распространяет гарантию
  на весь сервис.
- Идемпотентность: (1) клиент формирует report_id и привязывает run/context — сервер отклоняет
  чужой/устаревший контекст ДО первой записи; (2) повтор того же report_id возвращает прежний
  receipt; (3) новый содержательный расчёт — новый result_id даже при совпавшем status/count;
  (4) проекция — из полного ledger либо checkpoint+tail по watermark; (5) один канонический
  порядок у всех потребителей; (6) Memory реализует тот же контракт дедупа/порядка, что Postgres
  (P20/F07); (7) в заявленном required-режиме тихий fallback в Memory недопустим (P21/F14 →
  AUDIT-6C fail-closed).
- Redis CAS не создаёт транзакцию с ResearchRunStore; ошибку CAS учитывать и восстанавливать,
  не заменять бездумным last-write-wins (спека §8.3).

### 3.7. Legacy — **УТВЕРЖДЕНО-AUDIT-0**

- Старые события читаются всегда: отсутствующий `source` у legacy-ВЫБОРА — «user» (контракт
  PROGR-25-A), отсутствующие revision/result-доказательства — **unknown** (не выдумываются);
  повреждённое происхождение — unknown, не «подтверждённый человек» (спека §8.2).
- Исторический корпус не пересортировывается по invented timestamps; backfill новых метаданных —
  отдельный журналируемый процесс с raw/quality (план §20.2).
- Переход старых UI-writers отчётов — compatibility mode с ограниченным сроком/флагом и
  release-marker'ом (план §20.2 п.4); до его отключения полное закрытие P24/H26 не заявляется.
- Изменение старого exact-output теста — только как явное versioned-обновление контракта с
  доказательством сохранённой legacy-ветки; оракулы дефектов под реализацию не переписываются.

## 4. Уровни доказательности события — **УТВЕРЖДЕНО-AUDIT-0**

Каждому event_type при внедрении v2-схемы присваивается уровень (спека §8.1); default actor не
доказывает осознанный человеческий выбор:

| Уровень | Что удостоверяет | Примеры текущих типов |
|---|---|---|
| `server_result` | Алгоритм выдал результат на определённом входе | `target_column_changed` (auto-ветка), `correction_applied` с фактом |
| `client_observation` | Клиент сообщил наблюдаемую картину | `validation_check_status`, `preprocessing_check_status`, `eda_check_status`, `upload_stop_status`, `outliers_profile_status` |
| `user_decision` | Явное действие человека (trigger удостоверен) | ручной `target_column_changed`, `structure_confirmed` (capture-путь паспорта) |
| `operational` | Служебное событие контура | `run_paused`/`run_resumed`/`checkpoint_saved`, hook-факты просмотров |

UI-карты сохраняются как client observation с версиями контекста и ссылками на результаты;
сервер не принуждается к повторному пересчёту всех профилей (спека §8.1).

## 5. DTO-примеры

### 5.1. v1 (текущий канон, 8 полей + legacy-алиас — НЕ меняется)

```json
{
  "event_id": "3f1c9a2e-...",
  "run_id": "RUN-A1B2C3D4",
  "ts": "2026-10-09T12:00:00.123456+00:00",
  "stage": "validation",
  "node_id": null,
  "event_type": "target_column_changed",
  "payload": {"target_column": "temp", "source": "auto"},
  "actor": "system",
  "timestamp": "2026-10-09T12:00:00.123456+00:00"
}
```

### 5.2. Новое событие сброса (v1-тип, решает F02; тип не ждёт AUDIT-S)

```json
{
  "event_id": "9b7d33aa-...",
  "run_id": "RUN-A1B2C3D4",
  "ts": "2026-10-09T12:34:56.000001+00:00",
  "stage": "validation",
  "node_id": null,
  "event_type": "target_column_cleared",
  "payload": {"target_column": null, "reset_reason": "type_conversion",
               "source": "system", "before_target": "temp"},
  "actor": "system",
  "timestamp": "2026-10-09T12:34:56.000001+00:00"
}
```
Точка посева (горячая дорожка F02): `apps/api/routers/session.py::convert-types` — ветка сброса
(`:3952-3961`): двухслойный посев + `upsert_run` с `target_column=None, target_column_source=None`
(паттерн merge-dict — `restore_run`, `progress.py:1194-1203`).

### 5.3. v2-envelope (вводится AUDIT-S; аддитивно к v1)

```json
{
  "event_id": "…", "run_id": "…", "ts": "…", "stage": "…", "node_id": null,
  "event_type": "…", "payload": {}, "actor": "system", "timestamp": "…",
  "schema_version": 2,
  "evidence_level": "client_observation",
  "sequence": 17,
  "operation_id": "op-7f3e…", "causation_id": "req-b1c2…",
  "context_id": "ctx-5d6e…",
  "result_ref": {"result_id": "res-01h2…", "artifact": "s3://…|db://…", "hash": "sha256:…"},
  "method": {"algorithm": "iqr", "rule_id": "outliers.iqr", "rule_version": "3",
              "code_revision": "6a83924"},
  "time_quality": {"observed_at": "…", "raw_ts": "…", "quality": "ok|degraded|substituted"}
}
```
Обязательность полей per-event_type — таблица AUDIT-S; незаполняемое поле отсутствует или null
(«не подменять отсутствие доказательства значением "всё корректно"», план §1).

## 6. Инварианты контракта (проверяемы тестами последующих задач)

- **I1 (identity)**: один факт — один event_id во всех слоях/чтениях; повторное чтение legacy
  возвращает тот же id (F11/P17/P20 → AUDIT-S/6A).
- **I2 (order)**: проекция зависит только от commit sequence; перемена `ts` не меняет проекцию
  (P12/F08 → AUDIT-6A/5B).
- **I3 (context)**: событие/результат ссылается на контекст момента расчёта; поздний ответ не
  перепривязывается к текущим данным (P24/F04 → AUDIT-C/2A).
- **I4 (validity)**: historical ≠ current; без контекста validity=unknown (P05/F03 → AUDIT-8).
- **I5 (reset-awareness)**: после `target_column_cleared` все current-потребители цели (сессия,
  run, reason, Наставник, отчёт) показывают отсутствие цели; origin=unknown (P03/F02 → горячая
  дорожка → AUDIT-1a).
- **I6 (monotonic per context)**: в пределах одного context/result просмотр/достижение не
  понижается рутинным запросом; смена контекста начинает новую применимость (P25/F17, H27/H28 →
  AUDIT-3).
- **I7 (delivery)**: required-факт имеет receipt; повтор доставки не повторяет операцию;
  advisory честно обозначен (P07–P10/H26 → AUDIT-2A/2B/6B).
- **I8 (parity stores)**: Memory и Postgres реализуют одинаковый контракт дедупа/порядка/батча;
  конфигурация required без backend — отказ запуска, не тихая деградация (P20/P21/F07/F14 →
  AUDIT-6A/6C).
- **I9 (cap-safety)**: лимит отображаемого списка не влияет на выведенные состояния/старт
  (P11/F06 → AUDIT-5B).
- **I10 (evidence)**: каждый status/reason/count проекции ссылается на породивший факт и его
  уровень доказательности; невалидное событие исключается из details как диагностическая
  аномалия (P14–P16/F10 → AUDIT-4/5B).

## 7. Схема перехода v1 → v2 (порядок внедрения)

1. **Читатели раньше писателей** (план §20.2): v2-чтение legacy (отсутствующие поля → честные
   unknown/user-семантики §3.7) → аддитивная DB-миграция (AUDIT-6A, новая нумерация, `0001` не
   переписывается) → producers/receipt → strict context-write в конце.
2. **Типы раньше полей**: `target_column_cleared` — сразу после AUDIT-0 (горячая дорожка);
   `schema_version`/envelope — с AUDIT-S.
3. **Обратная совместимость**: v1-события не переписываются задним числом; исправления —
   correction/invalidation-события со ссылкой на исходный факт (спека §8.1); rebuild проекции —
   повторяемый, сравнение corpus ids сохраняется.
4. **Откат**: каждый шаг оставляет читаемым прежний корпус (аддитивные поля, паритет store-контрактов,
   пины legacy-чтения в тестах — `test_progress_progr17` и пр. остаются зелёными).

## 8. Горячая дорожка F02/F17 (следующая после AUDIT-0) — **УТВЕРЖДЕНО-AUDIT-0**

Рецензия тимлида (Донастройка, Часть 2): оба дефекта достижимы штатными действиями, дают
видимую ложь интерфейса; дорожка идёт СТРОГО после AUDIT-0 (этот документ фиксирует контракт
типа) и жёстко ограничена.

- **PROGR-AUDIT-H1 (F02)** — первый инкремент AUDIT-1a, 4 точки: `trace_events.py` (регистрация
  типа по §3.1) → `session.py::convert-types` (двухслойный посев + run-метаданные) →
  `node_status.py` (ветка редьюсера cleared: тот же эффект, что пустая ветка `:359-361` —
  указатель уточнён по R1 PROGR-AUDIT-0-CERT, было `:358-360`) →
  `mentor_rules.py` (тройка reset-aware). RED до правки: сброс-событие в /trace, run.target_column=None,
  Наставник просит, reason снят. Регресс обязателен адресный: `test_progress_progr25a`,
  `test_progress_progr25c`, интеграционные D1/D2 (путь reset не задевают — остаются зелёными),
  оракулы `progr25ccert` (корпуса без cleared — пины §4-C валидны, поведение аддитивно).
- **F17 (interim)** — монотонность ТОЛЬКО для `profile_viewed`, ТОЛЬКО в редьюсере статусов:
  `running` только из pending/отсутствия; узел, достигший done, `profile_viewed` не понижается.
  Точка — derive-функция рядом со статической картой (карта `EVENT_NODE_STATUS` начинается на
  `node_status.py:64`, элемент `"profile_viewed": "running"` — на `:69`; указатель уточнён по
  R2 PROGR-AUDIT-0-CERT, было «карта `node_status.py:69`»), не сама карта.
  Маркировка в коде и поставке: «interim до AUDIT-3, заменяется на контекст-ключевую
  монотонность». Легитимный путь переоткрытия — карта eda-checks (PAYLOAD_STATUS) сохраняется.
- **ЗАПРЕЩЕНО**: глобальная монотонность на все события (сделает H28 неисправимым молча);
  периметр-запрет дорожки: restore (F03), H26–H28, envelope-поля schema_version, доставка.
- **Инструмент аудита не трогать**: `progress_audit_readonly.py` пинит старое поведение —
  после фикса его P03/P25-ассерты закономерно покраснеют (спека §9 это предвидела); новые
  acceptance-тесты живут в tests/, исходный JSON-протокол не переписывается (план §2).
- После фикса: протоколировать в worklog9 перевод P03/P25 в «исправлено, acceptance-тесты: …».

## 9. Организационные решения (Донастройка_2) — **УТВЕРЖДЕНО-AUDIT-0**

1. **Тестовый PostgreSQL** — подготовить ДО начала AUDIT-6A (живые contract-тесты обязательны;
   mock-SQL не замена). Текущее состояние: в песочнице отсутствует — открыто.
2. **Импортируемость `apps.api.main`** в тестовой среде — включена в периметр AUDIT-6C;
   разблокирует полноценную интеграционную приёмку AUDIT-CERT. До тех пор все стенды —
   component-integration (readiness-гейт не отключать ради «зелёного» результата, план §20.1).
3. **Эволюция сертификационных оракулов** (тексты Наставника, «(авто)», наблюдательные пины
   H26–H28) — только как versioned-обновление контракта с журнальной фиксацией, не правка под
   реализацию.

## 10. Что документом НЕ решено (открыто)

- Выбор носителя durable-обязательства (outbox-таблица в Postgres vs отдельное хранилище) —
  AUDIT-6B после появления тестовой БД.
- Точные перечни required-путей и dependency-матрица узлов — AUDIT-C/AUDIT-6B.
- Семантика сброса через API (появление сброс-события в живом UI-контуре) — унаследована из
  PROGR-25-C граница (3); при появлении — отдельная задача.
- Открытые вопросы PROGR-23 (кэп всей колонки, счётчик «Исправлено», stale-производные) —
  вне периметра аудита, ждут решения тимлида (спека §10).
- H29/H30 — эксплуатационные проверки (§2), закрытие — AUDIT-6C/при доступе.

## 11. Артефакты задачи AUDIT-0

| Файл | Статус | Содержание |
|---|---|---|
| `docs/progress_audit_contract.md` | НОВЫЙ | настоящий контракт (редакция v0.1-AUDIT-0) |
| `scripts/progress_audit0_repro.py` | НОВЫЙ | повтор P01–P25 на своих CSV (стенд оригинала через importlib, инструмент не изменён) |
| `scripts/progress_audit0_repro_results.json` | НОВЫЙ | протокол своего репро: 25 OBSERVED / 0 PROBE_ERROR |
| `scripts/progress_audit0_baseline_control.json` | НОВЫЙ | контрольный прогон оригинального инструмента на 6a83924: 25 OBSERVED / 0 PROBE_ERROR |
| `packages/ui/components/prograudit0_h26_no_auto_retry.test.tsx` | НОВЫЙ | наблюдательный пин H26 |
| `packages/ui/components/prograudit0_h27_seed_failure_regresses.test.tsx` | НОВЫЙ | наблюдательный пин H27 |
| `packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx` | НОВЫЙ | наблюдательный пин H28 |
| `worklog/worklog9.md` | ИЗМЕНЁН | запись PROGR-AUDIT-0 |

## 12. Аддендум v0.2-AUDIT-S — схема событий, идентичность и время — **УТВЕРЖДЕНО-AUDIT-S**

Задача AUDIT-S (plan_progress_audit.md §5) реализована на базе `main@deaed93`; настоящий аддендум
конкретизирует §3.2/§3.3/§4/§5.3 до уровня проверяемых правил. Точки: `apps/api/trace_events.py`
(envelope/реестры/helpers), `apps/api/routers/progress.py` (адаптер прогнозов, merge /trace),
`apps/api/research_runs.py` (граница записи stores), `apps/api/schemas.py`
(ForecastTraceEventSchema), `packages/ui/lib/progress.ts` (TraceEventInfo, якорный селектор).

### 12.1. Идентичность (I1; F11/P17) — УТВЕРЖДЕНО

- Явный `event_id` всегда приоритетен: канонические stored-события несут свой id во всех слоях/чтениях.
- Legacy без id (3-польная популяция ForecastRun.trace) получает **стабильный производный id**:
  `uuid5` фиксированного namespace (`…/progress/trace-identity-v1`) от канонического содержимого
  `{run_id, ts, stage, node_id, event_type, payload(sort_keys)}` — правило закреплено в
  `trace_events.derive_stable_event_id`; повторное чтение возвращает тот же id, новые id при каждом
  чтении не генерируются (раньше — uuid4 на каждое чтение, нарушение I1).
- Два независимых действия, байт-идентичных по содержимому и ts до микросекунды, иной идентичности
  в legacy не имеют и считаются одним фактом; ЯВНО разные id никогда не склеиваются.
- Адаптер прогнозов (`canonicalize_stored_event`) сохраняет имеющиеся event_id/run_id/actor и
  передаёт envelope; run_id НЕ выдумывается (у legacy-артефактов его нет).

### 12.2. Уровни доказательности (§4) — полная таблица — УТВЕРЖДЕНО

`resolve_evidence_level(event_type, payload)`: payload-aware override → реестр типа; неизвестный
тип → None (честное unknown). Default actor НЕ участвует в выводе уровня.

| Уровень | Типы |
|---|---|
| `server_result` | upload_completed, correction_previewed, correction_applied, target_column_changed(source=auto), backtest_run, tuning_trial_completed, model_card_generated, candidates_generated, selection_evaluated, diagnostics_run, tuning_job_started, forecast_generated/compared/sensitivity_computed/exported |
| `client_observation` | upload_stop_status, validation_check_status, preprocessing_check_status, outliers_profile_status, eda_check_status |
| `user_decision` | structure_confirmed, mode_changed, target_column_changed (иначе), model_selected, models_compared, tuning_skipped, tuning_job_cancelled |
| `operational` | passport_captured, profile_viewed (hook-факт просмотра), run_paused, run_resumed, checkpoint_saved |

### 12.3. Обязательность envelope v2 per-уровень (таблица AUDIT-S) — УТВЕРЖДЕНО

Базис для всех уровней: `schema_version` + `evidence_level`. Далее:

| Уровень | Обязательные сверх базиса | Смысл |
|---|---|---|
| `server_result` | operation_id, result_ref, method | воспроизводимость расчёта |
| `client_observation` | operation_id | связность отчёта клиента |
| `user_decision` | operation_id, causation_id | удостоверение trigger'а |
| `operational` | operation_id | связность служебного контура |

`context_id` (AUDIT-C) и `sequence` (AUDIT-6A) — Optional у всех уровней на этой редакции.
Правила формы: «незаполняемое поле отсутствует» (to_dict включает только заполненные);
v1-события сериализуются байт-в-байт как прежде (8 полей + legacy-алиас timestamp);
`validate_envelope` — проверяемая функция обязательности (v1 — не нарушение, переход
«читатели раньше писателей» §7). Мусорные envelope-значения на границе чтения отбрасываются
(деградация, не 500); валидно типизированное неизвестное значение проходит (журнал, не реестр).

### 12.4. Честное время (F16/P23) — УТВЕРЖДЕНО

- Нечитаемый НЕпустой ts не подменяется никогда: envelope
  `time_quality={raw_ts, quality, observed_at}`.
- `quality="degraded"` — значение сохранено как есть (граница чтения normalize; Memory-store,
  хранящий raw); `quality="substituted"` — store заменяет значение строки записанным сейчас
  (Postgres TIMESTAMPTZ), observed_at=время записи; отсутствие поля — время читаемо/отсутствует
  (пустой ts — честное отсутствие, не «испорченное»).
- **Граница реализации**: Postgres-строка слоя 2 остаётся v1 до аддитивной миграции AUDIT-6A —
  маркировка производится на границе записи (объект события), durable-хранение маркировки в строке —
  задача AUDIT-6A (миграция `0002`, `0001` не переписывается). `_ts_to_db` сохраняет контракт строки.
- Исходный корпус не переписывается задним числом (§3.7, §7).

### 12.5. Единое чтение канонического порядка (§3.3) — УТВЕРЖДЕНО

- Единственная точка слияния/упорядочения корпуса для /trace: `trace_events.merge_canonical_events`
  = dedupe строго по ОДНОМУ event_id (первый источник приоритетен — слой 1) + `canonical_event_order`.
- Ветка sequence включается ТОЛЬКО когда sequence есть у ВСЕХ событий корпуса (назначит ledger-store
  в AUDIT-6A); частичный sequence корпус не переупорядочивает; legacy-корпус — стабильная
  хронология ts (нечитаемые/пустые — в конец с сохранением store-порядка; неизвестное время не
  переупорядочивает).
- `sort_events_chronologically` отчёта сохранён до AUDIT-5B (миграция потребителя отчёта — её
  периметр); смешение «append в одном месте, ts в другом» для /trace устранено.

### 12.6. Якоря чекпоинтов (§5.1) — семантика сохранена, механизм защиты обновлён — УТВЕРЖДЕНО

Оракул `test_artifact_events_are_not_checkpoint_anchors` пинил ОТСУТСТВИЕ event_id у артефактных
событий — то есть сам дефект F11. После исправления артефактные forecasting-события НЕсут
стабильную идентичность, но якорями быть не могут: слой 2 forecasting-событий не содержит
(хук-таблица forecasting-маршруты запрещает — `_validate_table`), POST /checkpoints отверг бы
ссылку, фронтовый `lastCheckpointableEvent` отсеивает их по stage (прецедент PROGR-5: слой 1
forecasting-событий не содержит). Оракул обновлён как **versioned-обновление** (Донастройка_2 п.3)
с доказательством сохранённой семантики: test_progress_panel (новый контракт: стабильный id +
повторное чтение) + progress.test.ts (кейс «forecasting с id — не якорь»).

### 12.7. Принятие envelope продюсерами — УТВЕРЖДЕНО

`stamp_envelope(event, **поля)` — единственная точка принятия v2 продюсером: любое непустое поле
переводит запись в v2 (schema_version=2 автоматически, evidence_level — из реестра); незнакомое
поле — ValueError (fail-closed у продюсера, в отличие от терпимой границы чтения). Продюсеры
переходят на v2 задачами AUDIT-C (context), AUDIT-6A (sequence), AUDIT-6B (operation/receipt),
AUDIT-7A (method) — до их поставок новые события остаются v1-формы, что честно и совместимо.

## 13. Аддендум v0.3-H1 — горячая дорожка F02/F17 реализована (PROGR-AUDIT-H1) — **УТВЕРЖДЕНО-H1**

Versioned-обновление (Донастройка_2 п.3): фиксирует реализацию дорожки и уточнения
R1/R2 акта docs/cert_prograudits_2026-10-10.md (PROGR-AUDIT-0-CERT); решения §3.1/§8 не меняются.

### 13.1. Уточнения указателей (R1/R2 — внесены в §8 с маркерами)

R1: пустая ветка редьюсера — `node_status.py:359-361` (заявленное `:358-360` включало return
НЕпустой ветки `:358` и не покрывало `:361`). R2: статическая карта `EVENT_NODE_STATUS` —
`node_status.py:64`, элемент `"profile_viewed": "running"` — `:69` (заявление «карта `:69»`
называло элемент карты, не карту). Семантика обоих решений не менялась — уточнены только
указатели (сверка с живым кодом 27b193d при реализации дорожки).

### 13.2. Реализация F02 (4 точки §8 — выполнены)

1. Регистрация: `"target_column_cleared"` в `_STAGE_EVENT_TYPES["validation"]` рядом с
   `target_column_changed`; `EVIDENCE_LEVEL_BY_EVENT_TYPE["target_column_cleared"] =
   "server_result"` — сброс является решением кода точки конвертации (нечисловая колонка не
   может быть целью; POST-маршрута сброса нет, §3.1 п.5); apply-клик пользователя не делает
   сброс осознанным человеческим решением О СБРОСЕ. Override-механизм payload-aware не
   заводится: текущий продюсер один, расширение реестра — вместе с регистрацией нового
   продюсера (прецедент target_column_changed).
2. Посев: `session.py::convert-types` ветка сброса — захват `before_target` до обнуления;
   `ensure_run_id()` (датасет активен — 404-гейт эндпоинта); фабрика
   `make_trace_event(..., actor="system", target_column=None, reset_reason="type_conversion",
   source="system", before_target=...)`; слой 1 `append_trace_event` + зеркало слоя 2
   `record_run_event` (общий event_id, канон R3); хронология «сброс → исход коррекции» —
   correction_applied хука приходит после ответа. Событие — v1-форма (envelope — AUDIT-C/6A/6B/7A,
   §7 «читатели раньше писателей»).
3. Run-метаданные: ветка `target_column_cleared` в `record_run_event` —
   `run.target_column = None` (тип сам есть факт сброса; поля target_column_source в
   ResearchRun не существует — происхождение сбрасывается на уровне сессии, как и было).
4. Редьюсер: `target_column_cleared` в `STAGE_LEVEL_REASON_EVENT_TYPES` + ветка в
   `_stage_level_reason_updates` — `({}, {target_node})`, тот же эффект, что пустая ветка
   (`:359-361`); мусор-payload деградирует щитом выше (не-Mapping → `{}`).
5. Тройка Наставника reset-aware (last-wins по хронологии, выбор после сброса восстанавливает
   факт): `_target_confirmed` — cleared снимает подтверждение; `_target_origin` — после cleared
   `None` (unknown, НЕ "user"; ЭВОЛЮЦИЯ СЕМАНТИКИ: пустой корпус теперь тоже `None` — выбора не
   было, origin неизвестен; единственный потребитель — auto-правило, требующее
   `_target_confirmed()==True`, поведение прежнее); `_phase_event_text_facts` — cleared снимает
   факт колонки. Fallback-текст «Подтвердите целевой признак…» — ожидание P03.

### 13.3. Реализация F17 (interim — выполнена)

`derive_node_statuses`: правило ТОЛЬКО для `event_type == "profile_viewed"` (не по строке
статуса) — `running` пишется только при отсутствии текущего статуса или `pending`; re-view
running идемпотентен; done/warning/error/skipped просмотром не понижаются. Легитимное
переоткрытие сохранено (eda_check_status — PAYLOAD_STATUS — ставит pending после коррекции,
пин H27 не тронут). Глобальная монотонность не вводилась (H28 остаётся исправимым). Маркировка
«interim до AUDIT-3» в докстринге точки; ~10 строк выброса при замене на контекст-ключевую
монотонность.

### 13.4. Приёмка и границы

Acceptance-тесты: `tests/api/test_progress_audit_h1.py` (26: реестр/фабрика/уровень, F17 юнит +
e2e, редьюсер reason, тройка Наставника, run-метаданные, P03 end-to-end с методом наблюдения
инструмента аудита — phase_text("upload") по слою 2, негативные guards, регресс-пины PROGR-25-A/C).
Мутационные пробы: `scripts/prograudith1_mutations.py` — M0 no-op SURVIVED (харнесс достоверен),
9/9 kill-мутантов убиты, 0 выживших; протокол `scripts/prograudith1_mutation_results.txt`.
Пин реестра `test_trace_events.py::test_registry_per_spec_table` обновлён spec-обусловленно
(прецеденты PROGR-16-A/17/18/20/23). Инструмент аудита НЕ тронут: его P03/P25-ассерты
закономерно покраснели бы при прогоне ПОСЛЕ фикса (спека §9); исходный JSON-протокол не
переписан; перевод P03/P25 в «исправлено» зафиксирован в worklog9. Периметр-запреты §8
соблюдены: restore (F03), H26–H28, envelope-поля, доставка — не тронуты.

## 14. Аддендум v0.4-C — данные, ревизии и контекст расчёта (PROGR-AUDIT-C) — **УТВЕРЖДЕНО-C**

Versioned-обновление (Донастройка_2 п.3): конкретизирует §3.4/§3.5/I3 до уровня проверяемых
правил задачи AUDIT-C (plan_progress_audit.md §6). База: `main@d54b648`. Решения
§3.1/§3.4/§12 не меняются — фиксация реализации и уточнение семантики.

### 14.1. Серверный контекст расчёта — компоненты и context_id — УТВЕРЖДЕНО

Единая точка — `apps/api/data_context.py` (без импортов из apps/api: направление
session_store → data_context, циклы исключены; паттерн target_column_rule/column_origin):

1. **Компоненты контекста** (`context_components`): `data = "{fingerprint}#{data_revision}"`,
   `target = имя цели или ""`, `temporal = имя даты или ""`. Отсутствие выбора честно (""),
   не выдумывается (план §1).
2. **context_id** (`compute_context_id`): `"ctx-" + uuid5(fixed-namespace, material).hex[:16]`,
   материал = `{v:1, run_id, components}` (sort_keys). **Run-scoping** — УТВЕРЖДЕНО: контекст
   привязан к ЗАПУСКУ; повторная загрузка того же файла = новый запуск = НОВЫЙ контекст
   (RED «тот же filename после повторной загрузки различается»; семантика set_dataset
   «новый датасет = новый анализ»). Restored-сессия (тот же run + те же компоненты) получает
   ТОТ ЖЕ id — продолжение исследования (§5.3); детерминизм uuid5 — повторное вычисление
   на том же состоянии возвращает тот же id (устойчивость между чтениями /current).
3. **Никакого клиентского контекста**: API не принимает context_id/data_revision от клиента;
   `/current` отдаёт вычисленные сервером значения (гидратация UI —
   `packages/ui/context/AppShellContext.tsx::contextId/dataRevision`) — «запретить подмену
   версии собственным счётчиком фронтенда» (план §6 GREEN).

### 14.2. Ревизии данных — УТВЕРЖДЕНО

- `AnalysisSession.data_revision` (0 при загрузке) + `data_digest` (контент-дайджест
  `compute_data_digest`: форма+колонки+`hash_pandas_object` с фиксированным ключом —
  детерминирован между процессами).
- **Единая точка замены DataFrame** — `AnalysisSession.set_dataframe(df, reason)`; все 18
  точек применения коррекций/преобразований `routers/session.py` переведены (централизованное
  повышение контекста, план §6 п.6). Ревизия +1 ТОЛЬКО при фактическом изменении контента;
  **no-op apply не выдаётся за изменённые данные** (RED «preview не меняет её» — preview
  в точку не доходит вовсе). Недоступность дайджеста (сбой вычисления → "") трактуется
  БЕЗОПАСНО — как изменение (устаревший результат за current дороже лишней инвалидации,
  спека §8.2). `set_dataframe` возвращает ФАКТ изменения.
- Сериализация: `data_revision`/`data_digest` в session_to_dict/from_dict; старые документы —
  0/"" (честная начальная/неизвестная, план §6 п.5). Аддитивные Optional — SESSION_SCHEMA_VERSION
  не поднимается (прецедент PROGR-24-ORIGIN-A/F1).

### 14.3. Dependency scopes — один реестр — УТВЕРЖДЕНО

`app/core/pipeline_graph.py::NODE_DEPENDENCY_SCOPES` (stage → node → frozenset), канон
`CONTEXT_SCOPES = ("data", "target", "temporal")`; полнота — fail-closed (каждая пара
STAGE_NODES имеет запись, сирот нет; `node_dependency_scopes` на неизвестной паре — ValueError).
Матрица: upload — data (chart +target+temporal, distribution +target, structure +temporal);
validation — data (regularity +temporal, sufficiency +target+temporal); preprocessing — data+
target+temporal (missing/outliers/scaling — data-only, regularity +temporal);
eda/modeling/forecasting — data+target+temporal. Имена scope-ключей совпадают с
`data_context.SCOPE_*` — равенство страхует тест (направленный импорт невозможен, паттерн STAGES).

### 14.4. Применимость (validity) — централизованная функция — УТВЕРЖДЕНО

`pipeline_graph.node_context_validity(stage, node_id, captured, current)` →
`current | stale | unknown`: captured отсутствует/нечитаем/неполон (нет нужного узлу scope) —
**unknown** (старый факт без известного контекста НЕ выдаётся за current, план §8);
все нужные scope совпали — current; иначе — stale. Смена ТОЛЬКО цели оставляет data-only узел
current и делает target-dependent узел stale (риск карточки: «нельзя инвалидировать все узлы
на любую настройку ЛИБО сохранять target-dependent done при смене цели»). Verdict —
применимость, НЕ удаление фактов: исторические события не стираются (план §6 п.6; замена
interim-механизмов — AUDIT-3/5B).

### 14.5. Envelope-штампование context_id продюсерами (§12.7) — УТВЕРЖДЕНО

- `trace_hook.record_trace_event` — ВСЕ route-hook события несут context_id момента сеяния
  (сессия прочитана после применения мутации запроса = контекст расчёта ответа);
- `target_column_rule.auto_fix_and_seed` — auto-выбор;
- `session.py::convert-types` — cleared (контекст момента сброса: target-компонент уже пуст,
  ревизия конвертации применена — честная привязка к состоянию расчёта);
- прочие программные продюсеры (forecasting, run-level progress.py, паспорта) остаются v1
  до своих задач (AUDIT-7A/6B) — «читатели раньше писателей» §7.
- **Форма перехода**: штамп любого поля = v2 (stamp_envelope, schema_version=2 +
  evidence_level); частичный v2 (context без operation_id/causation_id) — ЛЕГАЛЬНАЯ
  промежуточная форма перехода; полная обязательность таблицы §12.3 включается задачей
  AUDIT-6B (strict context-write). Граница: durable-хранение envelope слоя 2 (Postgres-строка)
  и run-метаданных ревизии — аддитивная миграция AUDIT-6A (тот же паттерн, что time_quality
  §12.4); Memory-слой 2 несёт envelope полностью.

### 14.6. Приёмка и границы

Acceptance: `tests/api/test_progress_audit_c.py` (32: ревизии/no-op/preview, идентичность
контекста и no-op выбора, unit data_context, штампование трёх продюсеров + I3-не-перепривязка,
полнота/семантика реестра scopes + fail-closed + validity-матрица, сериализация/legacy-дефолты/
CAS-конфликт без ложного обновления, API-экспозиция). Jest-оракул гидратации:
`packages/ui/context/AppShellContext.test.tsx` (гидратация с сервера; отсутствие полей —
честный null). Мутационные пробы: `scripts/prograuditc_mutations.py` — M0 SURVIVED,
12/12 KILLED, 0 выживших (`scripts/prograuditc_mutation_results.txt`); находка харнесса —
усиление теста сброса ревизии (MC12), не правка под мутанта. Контрольные suites:
test_session_store/test_target_column/test_pipeline_graph — зелёные; полный регресс —
1621 passed / 3 failed (документированный средовой нейро-fail-closed класс 1:1 базлайна H1) /
1 skipped; jest 162/1919 (базлайн 161/1916 + 1/3 — оракул задачи); typecheck:all чисто.

Границы (осознанные, вне задачи): result context (параметры методов/правил) — AUDIT-4/7A;
UI keyed-кэши просмотров по contextId/dataRevision — AUDIT-3/2B; разделение
historical/current в проекциях — AUDIT-5B/8; cross-run применимость restore — AUDIT-8;
durable-хранение контекста слоя 2 — AUDIT-6A; required-доставка/receipt — AUDIT-6B.
Инструмент аудита `progress_audit_readonly.py` не тронут (его наблюдения P-серии —
доказательство базы).
## 15. Аддендум v0.5-6A — атомарный ledger и одинаковые хранилища (PROGR-AUDIT-6A) — **УТВЕРЖДЕНО-6A**

Versioned-обновление (Донастройка_2 п.3): конкретизирует §3.3 (sequence), §3.6 (идемпотентность/receipt), I8 (parity) до уровня проверяемых правил задачи AUDIT-6A (plan_progress_audit.md §7). База: `main@9a3ed2b`. Решения §3.3/§3.6/§12/§14 не меняются — фиксация реализации и уточнение семантики.

### 15.1. commit_event_batch — единая транзакция ledger — УТВЕРЖДЕНО

Единая точка — `apps/api/research_runs.py::commit_event_batch` (контракт `ResearchRunStore`; реализации Memory/Postgres проходят ОДНИ параметризованные тесты `tests/api/test_progress_audit_6a.py`):

1. **Состав транзакции**: CAS-проверка expected context → обновление run-метаданных → запись батча событий → регистрация idempotency key и receipt. Падение на середине батча — полный откат: НОЛЬ событий и ПРЕЖНИЕ метаданные (P08/P10/F05 закрыты; «All-or-nothing» теперь фактическая транзакция, а не валидация входа).
2. **CAS expected context**: ожидаемый контекст = хранимый контекст запуска на момент ЧТЕНИЯ продюсером (оптимистичная проверка). stored NULL — первичная привязка (нечего сравнивать); несовпадение — `CommitConflictError` ДО первой записи (I3, «stale context отклонён до commit»). Легитимный сдвиг контекста (коррекция) проходит: продюсер читал stored-контекст до мутации, батч несёт НОВЫЙ контекст в run-метаданных.
3. **Полная карта узлов — один batch**: migrated producer четырёх карт статусов (`upload-stops`/`validation-checks`/`preprocessing-checks`/`eda-checks` в `apps/api/routers/progress.py`) пишет через `record_run_event_batch` — один батч, не десять независимых commit (план §7 п.2).
4. **Граница**: Redis и изменение DataFrame в транзакцию НЕ входят; P09 и контур доставки (outbox/повторы/health) — AUDIT-6B, здесь не закрыты.

### 15.2. Sequence — транзакционная позиция ledger — УТВЕРЖДЕНО

- `commit_seq` (колонка миграции `0002`, envelope-поле `sequence` события) назначается store'ом ВНУТРИ транзакции с сериализацией по run: Postgres — `INSERT shell + SELECT ... FOR UPDATE` на строку запуска; Memory — тот же замок, что и весь батч. Конкурентные батчи одного run дают непрерывный префикс 1..N без дублей и дыр (RED плана: «два concurrent batch имеют один порядок»).
- BIGSERIAL (столбец `seq` 0001) остаётся физическим порядком дописывания и НЕ принимается за committed-order (план §7 п.3). Чтение канонического порядка `list_events`: legacy-строки (commit_seq NULL) — стабильный исходный store-order, затем новые по commit_seq (legacy-first; переупорядочивания исторического корпуса нет, §3.7).
- Дедуп (run_id, event_id) — контракт ОБОИХ хранилищ (P20/H20/F07 закрыты): Postgres `ON CONFLICT DO NOTHING`, Memory — явная проверка (плюс дедуп внутри батча — первый occurrence, I1). `append_event` (advisory-интерфейс одиночных записей) дедуплицирует и назначает sequence по тем же правилам.

### 15.3. Receipt и идемпотентность — УТВЕРЖДЕНО

- `CommitReceipt`: idempotency key, run/context, принятые event ids, committed watermark, created_at; таблица `run_commit_receipts` (FK ON DELETE CASCADE — receipts живут вместе с запуском). Чтение потерянного receipt — `get_commit_receipt`.
- Повтор того же ключа/тела возвращает ПРЕЖНИЙ receipt без записи (retry после потерянного ответа не дублирует); тот же ключ с другим телом — `IdempotencyConflictError` БЕЗ записи (план §7 п.4). Тело — `batch_body_fingerprint` (sha256 канонического материала событий; контекст/метаданные run в тело дедупликации не входят — они вычисляются свежими при каждом зеркале).
- Ключи migrated producers содержательные: `event:{run_id}:{event_id}` (зеркало одиночных событий) и `map:{run_id}:{отпечаток тела}` (карты). Повтор ОДНОЙ поставки карты не дублирует факты; НОВАЯ поставка (новые event_id) честно даёт новые наблюдения — семантика P07 сохранена до AUDIT-2A (binding/идемпотентность карт — её периметр).

### 15.4. Migrated producers и advisory-остаток — УТВЕРЖДЕНО

- **Migrated** (план §7 п.6): `record_run_event` (зеркало хука/сброса цели/Прогнозирования) и `record_run_event_batch` (четыре карты статусов) — через `commit_event_batch`; run-метаданные и события одной транзакцией.
- **Advisory до своей миграции** (явно): прямые `store.append_event`/`set_run_status` в pause/resume/checkpoint/restore (`routers/progress.py`) — их миграция в периметре AUDIT-6B; контракт не менялся.
- Durable run-метаданные (граница AUDIT-C §14.5 закрыта): `research_runs.context_id/data_revision/data_digest` (колонки 0002; COALESCE-слияние при upsert — батч без новых значений не стирает прежние; паритет `_merge_run_additive` в Memory). Durable envelope v2 слоя 2: `trace_events.schema_version/evidence_level/operation_id/causation_id/context_id/result_ref/method/time_quality` (NULL у legacy — честное отсутствие, §3.7).

### 15.5. Миграция и приёмка

- `apps/api/migrations/0002_audit6a_atomic_ledger.sql` — АДДИТИВНАЯ, `0001` не переписывается (план §7); применима к старому корпусу: legacy-строки читаемы (sequence честно None), новые события получают sequence с 1, уникальность позиции ledger — частичный уникальный индекс сервера. Эквивалентность источников DDL (файлы 0001+0002 vs `MIGRATION_STATEMENTS`) — на живом сервере.
- Приёмка (план §7 GREEN): DB rollback атомарен на живом PG; одинаковые contract-тесты Memory и Postgres (паритет I8); миграция применима к старому корпусу. **Live PostgreSQL выполнен** (Донастройка_2 п.1 закрыта): pgserver (переносимые бинарники PostgreSQL) в песочнице + `scripts/prograudit6a_pg_runner.sh` (тот же контракт `CISSTAT_TEST_PG_DSN`, что у CI); 38/38 parity-оракулов и 115/115 полного контура на живой БД.
- Приёмка REST/сессий: адресный прогресс-контур 951 passed; полный регресс 3314 passed с дельтой к базлайну 1:1 (9 failed + 3 error — документированный средовой класс: нейро-группа отсутствует в песочнице + snapshot-ERROR; воспроизведены на чистой 9a3ed2b через stash-прогон).
- Versioned-обновления тестов (план §20.2 п.6): `test_mirrored_event_matches_layer1_payload` (снятие store-назначенного sequence + пин штамповки), `test_mirror_failure_does_not_break_endpoint` (шов отказа — commit_event_batch), `test_migration_statements_cover_all_tables`/`test_migration_statements_match_ddl_file_result` (каталог 0001+0002, таблица receipts).
- Мутационные пробы: `scripts/prograudit6a_mutations.py` — M0 no-op SURVIVED (харнесс достоверен), 9/9 kill-мутантов убиты (дедуп, CAS, fingerprint-конфликт, sequence, run-метаданные, FOR UPDATE-сериализация — оба хранилища), 0 выживших (`scripts/prograudit6a_mutation_results.txt`).

### 15.6. Границы (осознанные, вне задачи)

Redis и изменение DataFrame — вне транзакции (план §7 «Граница»); P09/контур доставки (outbox, восстановление операций, fail-closed required) — AUDIT-6B; полная обязательность v2-envelope (strict context-write) — AUDIT-6B; полная проекция/watermark-чтение потребителями — AUDIT-5B (здесь — только позиция ledger и receipt); binding/идемпотентность карт на уровне API — AUDIT-2A; live PostgreSQL на Render/Vercel — вне периметра.

## 16. Аддендум v0.6-5B — полная согласованная проекция и watermark (PROGR-AUDIT-5B) — **УТВЕРЖДЕНО-5B**

База: main@a2dcbee. Точки: `app/core/node_status.py`, `apps/api/progress_projection.py` (НОВЫЙ),
`apps/api/routers/progress.py`, `app/core/run_report.py`; UI `packages/ui/lib/progress.ts`,
`packages/ui/components/ProgressDrawer.tsx`. Закрывает F06/F08/F11 (P11/P12/P17), инварианты
I9/I10; фундамент 0→S→C→6A использован: проекция читает последовательный ledger, канонический
порядок §3.3 и run-метаданные контекста (§15).

### 16.1. Единая проекция и единый редьюсер — УТВЕРЖДЕНО

- Источник панели «Прогресс» — ПОЛНЫЙ ledger слоя 2 (+ слой 1: свежие, ещё не зеркалированные
  события P15; + артефакты Прогнозирования; дедуп строго по event_id, приоритет идентичности
  ledger → слой 1 → артефакты). cap=1000 ограничивает ТОЛЬКО отображаемый список
  (`ProgressTraceResponse.events`), не накопленные состояния (I9/P11/F06).
- Один редьюсер — `app/core/node_status.py::NodeStateFold`: батч-функции
  `derive_node_statuses`/`derive_pipeline_node_states` — развёртка того же `apply()` по корпусу;
  вторая реализации семантики не заведена (прецедент свёртки §12 п.10). Наставник и отчёт —
  потребители той же проекции (`build_projection`/`canonical_corpus`); отчёт с
  `canonical_order=True` не пересортировывает канонический корпус ts-сортировкой (P12/F08).
- `started_at` панели — `run.created_at` слоя 2, НЕ ts первого события уцелевшего хвоста (P11).
  У session_tail — None (честное неизвестное); у run-less сессии — прежняя семантика слоя 1.

### 16.2. Snapshot, watermark, read-after-watermark — УТВЕРЖДЕНО

- `ProjectionSnapshot` хранит: run_id, context, started_at, watermark (позиция истории — число
  фактов канонического корпуса), last_sequence, полный корпус (позиция), состояния узлов/стадий,
  счётчик диагностических аномалий, флаг полноты. Сериализуем (`to_dict`/`from_dict`) —
  checkpoint проекции (состояние fold внутри).
- `advance_projection(base, tail)` — checkpoint + tail (план §8): состояние fold восстанавливается
  и достраивается хвостом БЕЗ повторного прогона префикса; инвариант «replay полного ledger ==
  snapshot + tail» доказан оракулами (расщепления корпуса в 5 позициях, restart через from_dict,
  нагрузочный корпус 1500 событий > 2 капов). Подключение персистентного кэша снапшотов к
  эндпоинтам — AUDIT-6B; полное чтение на каждый GET — контрольный эталон (план §8 «Риск»).
- Read-after-watermark (план §8 п.7): `min_watermark` в build/advance — `ProjectionPendingError`,
  если корпус не дошёл до позиции; HTTP-форма — `GET /v1/progress/trace?after_watermark=N` → 409
  `projection_pending` (честный отказ от частичного snapshot). Onboarding: append-only ledger
  монотонен; pending означает смену/сброс хранилища или ошибку consumer'а.

### 16.3. Доказательства полей (I10), validity (PR-4), источники (PR-6) — УТВЕРЖДЕНО

- Узел проекции (аддитивно к 7-польному §3): `source_event_id` (событие статуса),
  `reason_source_event_id` / `count_source_event_id` (события reason/числа — могут быть разными
  решениями), `evidence_level` (envelope статусного факта; None — legacy, честное отсутствие),
  `validity` (применимость фактa: current/stale/unknown; None — статусного факта нет),
  `mode_source="session"` (режим из состояния сессии — помечен отдельно от event-derived).
- `pipeline_graph.event_context_validity(event_ctx, run_ctx)` — централизованная функция
  применимости на уровне context_id (грубее scope-сверки `node_context_validity`: у события есть
  только идентификатор контекста; компоненты — уровень AUDIT-8): нет контекста события/запуска —
  unknown, совпал — current, иначе — stale. Исторические факты не стираются (I4).
- Payload невалидного статусного события (тип из PAYLOAD_STATUS_EVENT_TYPES, payload.status вне
  CHECK_STATUS_VALUES) больше НЕ меняет детали узла (reason/счётчик — часть F10, в объёме
  карточки §8 «Payload невалидного события не меняет детали») и учитывается диагностической
  аномалией проекции (`anomalies` в /trace); last_touched_at остаётся (касание — факт журнала).
  Семантическое изменение против v0.5: у payload-статусных типов невалидный payload более не
  порождает reason без статуса.

### 16.4. Честная деградация (PR-8) и приёмка — УТВЕРЖДЕНО

- Слой 2 недоступен / запуск не найден при известном run_id: панель строит проекцию из хвоста
  сессии и ЧЕСТНО помечает ответ `projection_source="session_tail"`, `projection_complete=false`,
  `started_at=null` (хвост не выдаётся за полную историю; UI — предупреждение «история неполна»
  в шапке, N-3 для старого бэкенда). 503 на /trace не вводится — панель advisory-потребитель
  (§3.6); run-scoped чтения (Наставник/отчёт/деталь) сохраняют свои 503.
- Приёмка (план §8 GREEN): одна и та же committed история даёт одинаковые состояния независимо
  от лимита, clocks и выбранного store — оракул `tests/api/test_progress_audit_5b.py` 20/20 на
  Memory И на живом PostgreSQL (pgserver; изоляция уникальными run_id — урок F-6A2);
  postgres-сюита 6A 17/17 без регресса. Адресный прогресс-контур (25 файлов плана) — 832+1665
  passed; полный `tests/` — 3549 passed / 3 errors (документированный snapshot-класс) / 18
  skipped; jest 163 suites / 1934 tests, tsc — без новых ошибок (TS2882 globals.css — средовой,
  воспроизведён на чистой базе).
- Versioned-обновления тестов (план §20.2 п.6): пин «ровно 7 полей» /trace-узлов
  (test_progress_panel.py) — расширен до 13-полевого контракта 5B с фиксацией аддитивности
  (N-3); legacy-корпус PROGR-13-B3 (test_progress_progr13b.py) — старая популяция моделируется
  в ОБОИХ слоях (обе записи писались старым кодом), нормализация legacy id проверяется на
  новом ledger-пути чтения; legacy-ветка сохранена и доказана.
- RED-протокол: `scripts/prograudit5b_red_repro.py` (+ .txt) — 5/5 RED-CONFIRMED на базе
  (P11-хвост/started_at, невалидный payload меняет детали, отсутствие validity, ts-порядок
  отчёта); pytest-оракул на базе — 20/20 FAILED (11 ImportError контрактных API + 9
  поведенческих).

### 16.5. Границы (осознанные, вне задачи)

Персистентный кэш снапшотов проекции и его инвалидация — AUDIT-6B (вместе с outbox/доставкой);
scope-уровень validity (сверка компонентов, а не context_id) — AUDIT-8 (raw restore/историческая
применимость); seed EDA из проекции с watermark и контекст-ключевая монотонность — AUDIT-3;
контекст/идемпотентность API-карт (strict v2-write, binding) — AUDIT-2A; Наставник не читает
артефакты сессии (run-scoped контракт) — расхождение корпусов панель/Наставник на несмиррованных
P15-событиях остаётся честной границей доставки, watermark в ответах делает её наблюдаемой.

## 17. Аддендум v0.7-1A — сброс и восстановление цели/происхождения (PROGR-AUDIT-1A) — **УТВЕРЖДЕНО-1A**

Versioned-обновление: план `plan_progress_audit.md` §9, задача AUDIT-1a (предшественники
AUDIT-C/5B закрыты; база `main@09e312f`). Решения §3.1/§3.7 не меняются — реализуются.

### 17.1. Единый effective-target reducer — УТВЕРЖДЕНО

`app/core/effective_target.py` (НОВЫЙ, лист app/core) — ЕДИНСТВЕННАЯ реализация правил
choice/reset (план §9 п.2 «один reducer для session/run metadata, reason, Наставника и
документа»). Правила:

- `target_column_changed` с непустым строковым target — ВЫБОР:
  `origin = normalize_target_origin(payload.source)`;
- `target_column_changed` с пустой строкой — СБРОС (legacy-форма, канон PROGR-15-B; паритет
  run-метаданных и reason-ветки node_status; в current-корпусе недостижима — POST отклоняет
  пустой, граница PROGR-25-C);
- нестроковый/мусорный target — НЕ ФАКТ (R3; метаданные потребителей не трогаются; до задачи
  record_run_event фабриковал `"123"` из мусора, Наставник — выбор из truthy);
- `target_column_cleared` — СБРОС (payload не требуется; origin после сброса None, НЕ "user" —
  §3.1 п.4);
- прочие события — пропуск. Last-wins по ДАННОМУ порядку (канонический порядок — ответственность
  вызывающего, §3.3; редьюсер не сортирует сам — P12).

`normalize_target_origin`: "auto"|"user" — канон; отсутствие/пустота — "user" (legacy-контракт
PROGR-25-A у ВЫБОРА); прочее — None (unknown; спека §8.2 «повреждённую историю не выдавать за
подтверждённого человека»; до задачи мусорный source читался как "user" — фабрика).

Доказательство (I10-стиль 5B): `EffectiveTarget{target, origin, source_event_id}` +
`resolved` — различение «фактов нет» (corpus без фактов цели; потребители с хранимым состоянием
его НЕ трогают) и «сброс» (очистить) — на этом держится честный инкрементальный mirror.

Потребители (мигрированы, вторых реализаций семантики нет): тройка Наставника
(`_target_confirmed`/`_target_origin`/`_phase_event_text_facts` — делегирование), reason-марка
узла (node_status: normalize_target_origin), run-метаданные (record_run_event — инкрементальный
mirror по одному событию через `effective_target((event,))`), restore (replay полного ledger),
документ — через run-метаданные (durable проекция тех же правил; шаблоны фактов — AUDIT-7B).

### 17.2. Run-метаданные: согласованная пара target/source — УТВЕРЖДЕНО

`ResearchRun.target_column_source: Optional[str]` (аддитивно, миграция **0003**
`ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS target_column_source TEXT`; файл-дубль
`apps/api/migrations/0003_audit1a_target_source.sql`; каталог MIGRATION_STATEMENTS/MIGRATION_FILES
расширен). Значения "auto"|"user"|None; None — честное отсутствие (сброс/повреждение/legacy-строка),
НЕ фабрикуется. Поле ЦЕЛЕВОЙ ПАРЫ: пишется НАПРЯМУЮ (не COALESCE — parity target_column; None
осознанное значение), в `_merge_run_additive` не входит. Memory/Postgres — один контракт
(round-trip на живом pgserver: 18/18).

### 17.3. Restore: согласованная пара без повторного авто-выбора — УТВЕРЖДЕНО

`restore_run` (F03/P04): цель восстанавливается ПАРОЙ (target, origin) из ЕДИНОГО редьюсера над
ПОЛНЫМ ledger (spec §8.2 «из согласованных метаданных либо choice/reset reducer'а»; ledger
авторитетен — устаревшие метаданные не воскрешают сброшенную цель). Legacy-корпус без фактов
цели в ledger — fallback на метаданные (origin из метаданных либо честное отсутствие). Цель,
неприменимая к raw-данным (отсутствует/нечисловая по ЕДИНОМУ примитиву `numeric_columns`
singleton-правила), не восстанавливается — парная origin тоже. Повторный авто-выбор НЕ
выполняется (спека §8.2; второго события выбора нет; singleton-правило и исключение
зарегистрированных производных сохранены). `RestoreResponse.target_column_source` — аддитивно
(N-3: старый клиент поле игнорирует). Raw-семантика/historical-validity — AUDIT-8.

### 17.4. Приёмка и границы

- RED-протокол: `scripts/prograudit1a_red_protocol.txt` — 32 FAILED / 4 PASSED на базе
  (14 ImportError редьюсера + 5 AttributeError origin + restore-группа KeyError/поведение);
  4 PASSED — регресс-пины уже работающего поведения. Оракул `tests/api/test_progress_audit_1a.py`
  — 36/36 GREEN (редьюсер/Наставник/run-метаданные/сброс-согласованность/restore-пара/полный
  цикл auto→reset→manual/derived).
- Регресс: адресные suite'ы (25a/25c/25d/H1/target_column/research_runs/trace_events/
  node_status/mentor/panel/5b/6a/C/S/trace_hook/session_store/run_report/13a-c/16/17/18/23 +
  integration target-column e2e) — без падений; postgres-сюита 18/18 (pgserver, включая новый
  round-trip пары); tests/api+integration — 1682 passed / 19 failed / 18 skipped, все 19
  воспроизводятся на чистой базе 09e312f stash-прогоном (окружение sandbox: production dispatch
  моделей вне контура «Прогресса») — дельта к базлайну 0. Сборка: импорт `apps.api.main` OK,
  py_compile OK, миграция 0003 идемпотентна на живой БД (26 утверждений, повторный прогон no-op).
- Границы (вне задачи): raw restore-семантика и historical/validity — AUDIT-8; шаблоны фактов
  отчёта (P18/auto-метка) — AUDIT-7B; payload/source ручного маршрута остаётся legacy
  {target_column} (PROGR-25-A, читается как user) — изменение формы корпуса не входило.

## 18. Аддендум v0.8-4A — outcome и детали коррекции (PROGR-AUDIT-4) — **УТВЕРЖДЕНО-4A**

Versioned-обновление: план `plan_progress_audit.md` §10, задача AUDIT-4 (предшественники
AUDIT-C/5B/1A закрыты; база `main@02ac7ff`). Решения §4.1/§12 не меняются — разделяются:
тип события остаётся носителем ОПЕРАЦИИ, качество результата выводится отдельно.

### 18.1. Единый вывод исхода коррекции (outcome) — УТВЕРЖДЕНО

`app/core/node_status.py` — ЕДИНСТВЕННАЯ проекция фактов результата payload в словарь
исходов плана §10: `resolve_correction_outcome(data)` → `violations` / `clean` (preview),
`changed` / `no_change` (apply), `unknown` (фактов нет). Правила:

- preview — по диагностике ДО (`CORRECTION_VIOLATIONS_KEYS`): >0 — violations, ==0 — clean,
  фактов нет — unknown (легаси-корпус не фабрикует «Найдены нарушения», H14);
- apply — по прямым отчётам объёма выполненного (`CORRECTION_CHANGED_KEYS`): любой >0 —
  changed, все сообщённые ==0 — no_change;
- fallback apply (прямых фактов нет) — пара до/после (`total_violations_before/after`,
  regularity sort): remaining != before — changed, == — no_change; половина пары
  (convert-types `total_invalid`) — unknown;
- щит счётчиков — тот же, что `_clean_summary_count` (bool/строка/отрицательное — не факт).

`correction_reason(event_type, outcome, remaining)`: канонические тексты карты сохранены
для доказуемых исходов (violations-preview и changed-apply рендерят прежние строки);
новые честные тексты — «Нарушений не найдено: предпросмотр коррекции», «Коррекция
применена частично: нарушения остались», «Коррекция не изменила данные», «Коррекция не
устранила нарушения» (remaining>0), «Коррекция выполнена: исход не подтверждён» (unknown).

### 18.2. Честная проекция статуса/reason/бейджа — УТВЕРЖДЕНО

NodeStateFold (единственный редьюсер):

- статус коррекций — из ИСХОДА, не из типа операции: violations → warning; changed при
  remaining>0 (частичное устранение) → warning; changed иначе → done; no_change при
  remaining>0 → warning; clean/no_change-прочее/unknown → статус НЕ утверждается (узел
  сохраняет прежнее состояние). Специальный исход выбросов сохранён (§18.3);
- reason и бейдж — из фактов ТОГО ЖЕ события (P16/H16): событие решения без фактов
  счётчика ОЧИЩАЕТ бейдж (цифра прежней диагностики не становится результатом нового
  решения; `_count_src` = None согласованно). Бейдж apply — состояние ПОСЛЕ операции
  (remaining-ключи, карточная шкала выбросов первенствует — пины G345); бейдж preview —
  найденные нарушения (гипотетические after-превью бейджем не становятся); unknown —
  прежний плоский приоритет `NODE_SUMMARY_COUNT_KEYS` (расширен фактами до/после);
- P15/H15: override-событие с ПРИСУТСТВУЮЩИМ, но невалидным `status`-полем —
  schema-нарушение: целиком вне decision details (статус/reason/счётчик не тронуты,
  касание остаётся), диагностическая аномалия fold (anomaly_count). `status: null` /
  отсутствие поля — легаси-ветка (фолбэк на карту, пин PROGR-23 сохранён);
  `resolve_event_status` НЕ менялся (словарная проекция для гейтов фаз Наставника);
- доказательства: `node_states_with_evidence` аддитивно несёт `outcome` узла (I10-стиль;
  7-польный контракт §3 не менялся).

### 18.3. Специальные исходы и параметры результата — УТВЕРЖДЕНО

- карточная шкала выбросов (класс C5 G345): валидный `payload.status` приоритетен выводу
  из outcome — частичная коррекция остаётся warning, унификации в безусловный done нет;
  map-фолбэк (`correction_applied` без поля status) исходом НЕ считается — карта
  «тип → done» и есть разделяемый AUDIT-4 стиль;
- P19/F13: dedupe (`_node_picture_unchanged`) сравнивает картину И параметры результата
  (`DEDUPE_PARAM_KEYS = ("method", "mode")`) против последнего stored-события того же
  (event_type, node_id): смена метода/режима при той же status/count-картине — другой
  выполненный метод, факт создаётся (H19); focus-refetch того же результата — нет;
  легаси-события без параметров сравнения не дают (самозаживление);
- whitelist хука `_CORRECTION_PAYLOAD_KEYS` расширен фактами «нарушения до/после»:
  `total_still_invalid/missing/outliers`, `still_duplicate_rows`, `rows_changed`,
  `duplicate_rows`, `total_violations_before/after`, `rows_added/rows_dropped` —
  отсутствующие ключи опускаются (обратная совместимость корпуса).

### 18.4. Приёмка и границы

- RED-протокол: `scripts/prograudit4_red_protocol.txt` — 39 FAILED / 8 PASSED на базе
  02ac7ff (16 ImportError outcome/reason API; честные статусы P14; свежесть P16;
  аномалии P15; evidence-outcome; whitelist; P19-метод; панель e2e). 8 PASSED — пины уже
  корректного поведения (C5-override, легаси-фолбэк, fail-safe счётчиков, dedupe).
  Оракул `tests/api/test_progress_audit_4.py` — 48/48 GREEN.
- Регресс: адресные suite'ы (node_status_engine/progr23/trace_hook/panel/5b/1a/6a/C/S/H1/
  mentor/admin_progress/admin_analytics/…) — без падений; versioned-обновления пинов
  (план §20.2 п.6): engine ×8, H1 ×1, mentor ×1, admin_progress ×1, admin_analytics ×5 —
  голым синтетическим correction-событиям добавлены факты результата (интент пинов
  сохранён: last-wins, смешанные представления, коллизии стадий, mode-reason,
  case-bank/top-problem корпуса). tests/api+integration — 1730 passed / 19 failed /
  18 skipped, все 19 — документированный средовой класс (production dispatch моделей:
  forecasting_session ×16, modeling_workflow, backtest_neural_capacity, models_candidates;
  плюс мусорный DATABASE_URL=file:… в среде sandbox искажал слой 2 — прогон с очищенным
  окружением) — дельта к базлайну 0. Сборка: импорт `apps.api.main` OK, py_compile OK.
  Хранилища/миграции не тронуты (postgres-сюита вне дельты). Jest/tsc не требовались —
  UI не менялся (новые reason-тексты рендерятся существующим полем status_reason, N-3).
- Границы (вне задачи): отложенная математика PROGR-23 (карточная шкала) не исправлялась;
  шаблоны фактов отчёта (P18) — AUDIT-7B; обязательность v2-envelope и контекстные гейты
  коррекций — AUDIT-2A/6B; результат-идентичность durable-уровня (result_id в ledger) —
  AUDIT-6B/7A.

## 19. Аддендум v0.9-2A — API-карты: контекст и идемпотентность (PROGR-AUDIT-2A) — **УТВЕРЖДЕНО-2A**

Versioned-обновление: план `plan_progress_audit.md` §11, задача AUDIT-2A (предшественники
AUDIT-6A/5B закрыты; база `main@3322e4a`). Проблема: F04/F07 (P06/P07/P24) — карты статусов
не привязаны к контексту расчёта, повтор отчёта не идемпотентен, доставка без receipt.
Решения прежних редакций не меняются — развиваются: ledger/receipt-механика AUDIT-6A (§15)
получает первого строгого HTTP-потребителя; client_observation AUDIT-S (§12) получает
обязательный v2-конверт на картах.

### 19.1. v2-конверт карты — УТВЕРЖДЕНО

Единый механизм — НОВЫЙ модуль `apps/api/progress_maps.py`; четыре эндпоинта
(`upload-stops`, `validation-checks`, `preprocessing-checks`, `eda-checks`) — потребители
ОДНОЙ реализации (`accept_map_report`), параметры — `MapSpec` (stage/event_type/registry/
no_dataset_subject). Формовая валидация карты (реестр/словарь/полнота) остаётся в handler'ах
— тексты и гейты legacy-поведения не менялись.

Тело v2: `schema_version=2` + `run_id` + `context_id` + `report_id` (непустые строки) +
опциональные `result_refs` (словарь узел реестра → непрозрачная ссылка ≤512). Формовые
нарушения — 422 ДО первой записи (все слои не тронуты). Явное чужое `schema_version`
(1/3/…) — 422: отсутствие поля — честный признак легаси-режима, явное неверное значение —
ошибка клиента, а не молчаливая деградация.

`result_refs`: ключи — только узлы реестра карты (фантом — 422); ссылка со встроенным
контекстом (`ctx-<16hex>@`, канон `data_context.CONTEXT_ID_PREFIX`) обязана совпадать с
контекстом отчёта — чужой контекст — 409 (I3; RED «result принадлежит чужому контексту»).
Ссылка без префикса — клиентская метка без серверной проверки владения: серверный реестр
результатов — граница AUDIT-6B/7A (durable result_id), здесь не фабрикуется. Ссылки
записываются в envelope события узла (`result_ref={report_ref: …}`).

### 19.2. Контекстные гейты ДО записи — УТВЕРЖДЕНО

Порядок гейтов v2: 400 (нет датасета) → 422 (форма конверта) → 409 `stale_run`
(`payload.run_id != session.run_id`; неизвестный запуск — 409, run_id клиента из тела НЕ
сеется — привязка не фабрикуется) → 409 `stale_context` (`payload.context_id != run.context_id`
durable-слоя). Источник проверки контекста — `run.context_id` долговременного слоя, ТОТ ЖЕ,
что клиент видит в `GET /v1/progress/trace` (client bind to observed context, I3/P24); смена
цели/данных/ревизии сдвигает компоненты контекста (AUDIT-C §3.4: origin цели в контекст не
входит — ручной выбор той же колонки контекст не сдвигает). Все 409/422 — НОЛЬ изменений в
слоях 1 и 2 (план §11 GREEN); старый снапшот не повышает текущий прогресс.

### 19.3. Идемпотентность по report_id — УТВЕРЖДЕНО

Ключ идемпотентности — `report:{run_id}:{report_id}`; отпечаток — ТЕЛО отчёта клиента
(`report_body_fingerprint`: карта + конверт + ссылки, canonical json, БЕЗ event_id/ts).
Матрица (поверх дедупа store'а AUDIT-6A):

| Сценарий | Ответ | Записи |
|---|---|---|
| новый report_id, новое тело | 200, `deduplicated=false`, receipt | события слоя 2 + слой 1 |
| тот же report_id, то же тело (retry/потерянный ответ) | 200, `deduplicated=true`, ПРЕЖНИЙ receipt | НЕТ (включая слой 1) |
| тот же report_id, другое тело | 409 `report_id_conflict` | НЕТ |
| конкурентный дедуп (тот же ключ, гонка) | 200 `deduplicated=true` (второй) | НЕТ |
| сдвиг контекста между гейтом и commit (гонка) | 409 `stale_context` (CAS `CommitConflictError`) | НЕТ |

НОВЫЙ report_id с тем же телом — новое клиентское наблюдение (явное основание — новый отчёт,
план §11 п.4): события пишутся, дедуп не подавляет. Strict-commit (`commit_map_report` в
`research_runs.py`) — БЕЗ bare-except: конфликты store'а возвращаются эндпоинтом как 409
(в отличие от best-effort `record_run_event_batch` легаси-пути).

### 19.4. Транзакционность v2 и receipt — УТВЕРЖДЕНО

Порядок записи v2: строгий commit слоя 2 (CAS `expected_context_id` = проверенный контекст)
ПЕРЕД слоем 1. Отказы до/на commit — ноль частичных узлов в ОБОИХ слоях. Слой 1 пишется
после durable-фиксации; сбой сохранения слоя 1 — честный 500 при существующем receipt
(повтор той же поставки возвращает receipt дедуплицированно; локальная копия сессии
восстанавливается следующей записью/перечтением ledger — панель для запуска читает ledger
AUDIT-5B). Граница: единая кросс-сторовая транзакция «слой 1 + слой 2» остаётся у AUDIT-6B
(outbox) — здесь выбран порядок, минимизирующий класс частичных состояний, без обещания
атомарности хранилищ.

Ответ v2 (аддитивные поля всех четырёх response-моделей): `mode="v2"`, `report_id`,
`context_id`, `deduplicated`, `receipt` (CommitReceipt.to_dict: idempotency_key/run_id/
context_id/accepted_event_ids/committed_watermark/created_at). `reported` — размер реестра
при приёмке, 0 при дедупе (новых фактов не записано).

События v2 штампуются `stamp_envelope`: `schema_version=2`, `evidence_level=client_observation`
(реестр AUDIT-S согласован), `operation_id=report_id`, `context_id` (+`result_ref` узлам со
ссылками) — обязательность §12.3 для client_observation выполнена; доказательства проекции
(I10) получают context/evidence у карт впервые.

### 19.5. Ограниченный режим старых писателей (compatibility mode) — УТВЕРЖДЕНО

Тело БЕЗ `schema_version` — легаси-режим: прежний контур байт-в-байт (ensure_run_id →
события v1 → слой 1 → best-effort `record_run_event_batch` с map:-отпечатком), ответ помечен
`mode="legacy"` (аддитивное поле). ЧЕСТНЫЕ ГРАНИЦЫ (план §11 п.5, §20.2 п.4): P24 НЕ закрыт
для old-write пути (пин `test_legacy_stale_body_still_accepted_p24_open` фиксирует приём
старого тела новым запуском как ГРАНИЦУ, не одобрение); P07 в легаси сохраняет прежнюю
семантику (повтор добавляет события). Закрытие P24 целиком = перевод всех четырёх UI-
продюсеров (AUDIT-2B) на v2 + ОТДЕЛЬНОЕ решение тимлида об отключении легаси-пути
(release-marker режима); до этого строгие гарантии доставляет только v2-конверт.

### 19.6. Приёмка и границы

- RED-протокол: `scripts/prograudit2a_red_protocol.txt` — 20 FAILED / 2 PASSED на базе
  3322e4a (2 ImportError единого механизма; 9 KeyError mode/deduplicated/receipt — конверт
  не принимался; 5×200-vs-409 — гейты P24/P07 отсутствовали; 4×envelope — события писались
  v1-формой). 2 PASSED — пины уже-корректного поведения (словарь EDA 422, 400 без датасета).
  Оракул `tests/api/test_progress_audit_2a.py` — 22/22 GREEN (P24 e2e «отчёт A после upload B»,
  тот же run/другая цель, retry-дедуп, конфликт тела, новое наблюдение тем же телом, 422-формы,
  result_refs (запись/чужой контекст/фантом), легаси-пины честности, параметризованный
  контракт 4 эндпоинтов, стабильность отпечатка тела).
- Регресс: адресные suite'ы карт/панели/хука/семян — 223 passed / 1 средовой (мусорный
  `DATABASE_URL` песочницы, с очисткой 19/19); audit-оракулы + потребители (6a/5b/1a/4/C/S/
  H1/mentor/admin) — 396 passed / 17 skipped; полный tests/api+integration — 1752 passed /
  19 failed / 18 skipped, все 19 — документированный средовой класс базлайна (production
  dispatch моделей: forecasting_session ×16, modeling_workflow, backtest_neural_capacity,
  models_candidates), контроль на ЧИСТОМ worktree 3322e4a дал те же 19 failed / 89 passed —
  дельта к базлайну 0. Сборка: импорт `apps.api.main` OK, py_compile OK. Jest/tsc не
  требовались — UI не менялся (аддитивные поля ответов; UI-продюсеры v2 — AUDIT-2B).
- Границы (вне задачи): серверный реестр результатов/durable result_id — AUDIT-6B/7A;
  UI-доставка/повторы/409-refresh — AUDIT-2B; монотонность просмотров EDA по контексту —
  AUDIT-3; отключение легаси-пути — решение тимлида после AUDIT-2B; единая кросс-сторовая
  транзакция — AUDIT-6B.
- Честная фиксация инцидента рабочего процесса: stash-контроль базлайна вскрыл старый stash
  предыдущей сессии; конфликт разрешён в пользу HEAD (проверено — строгое надмножество),
  stash сохранён; базлайн повторён через отдельный `git worktree`. Продукты задачи не
  пострадали (детали — RED-протокол).

## 20. Аддендум v1.0-2B — UI-доставка карт: единый механизм и восстановление после отказа (PROGR-AUDIT-2B) — **УТВЕРЖДЕНО-2B**

Задача AUDIT-2B (plan_progress_audit.md §12) реализована на базе `main@9e8edde`
(HEAD = коммит PROGR-AUDIT-4-CERT; приёмка v2-сервера — AUDIT-2A, коммит 5689e8a,
уровень API). Настоящий аддендум фиксирует контракт UI-продюсеров карт и написан
по проектному правилу «спецификация до кода»: хук `useProgressMapDelivery` и
перевод четырёх продюсеров реализованы ПО ССЫЛКАМ на пункты настоящего §20.

### 20.1. Единый механизм доставки (useProgressMapDelivery) — УТВЕРЖДЕНО

Четыре продюсера карт (Upload `/upload-stops`, Validation `/validation-checks`,
Preprocessing `/preprocessing-checks`, EDA `/eda-checks`) переводятся с четырёх
копий связки «ref-маркер + один fetch» (PROGR-13-A5/16-A/17/18) на один хук
`packages/ui/hooks/useProgressMapDelivery.ts`. Хук — единственный владелец
статусной машины доставки: `idle → binding → pending → delivered |
accepted_legacy | undelivered | stale`; состояние возвращается продюсеру
(`delivered`, `reportId`, `attempts`, `lastError`, `runId`, `contextId`,
`redeliver()`), но не блокирует модуль и чтение научного результата — статус
доставки остаётся вспомогательным контуром (§12 п.8 spec_progress): сбой не
ломает модуль, алертов нет. Снапшот карты канонизируется сортировкой ключей —
дедуп устойчив к порядку построения объекта. Гейты отчёта каждого модуля
сохранены (до первого запуска отчёта НЕТ; транзитные running/pending — не
факты; Upload не отчитывает «все pending» до загрузки).

### 20.2. report_id, ограниченный retry с backoff (H26) — УТВЕРЖДЕНО

Каждая поставка получает уникальный `report_id` (`map-<uuid>`, ≤200 символов,
§19.1); retry повторяет ТОТ ЖЕ ключ и payload — серверная идемпотентность
AUDIT-2A (§19.3) возвращает прежний receipt без дублей (P07). Сетевой отказ и
5xx повторяются ограниченно: backoff 500мс/1с/2с (до 4 попыток), исчерпание —
честный `undelivered` без ложного delivered. Тем самым H26 («один отказ
доставки при неизменном снапшоте остаётся без повтора») закрыт ШТАТНЫМ
механизмом, а не сбросом ref-а. Легаси-режим НЕ ретраится (см. §20.5).
Постоянные ошибки (`report_id_conflict`, 400/404/422) — без retry.

### 20.3. Receipt-гейт delivered — УТВЕРЖДЕНО

`delivered=true` ставится ТОЛЬКО после ответа `200 + mode="v2" + receipt`
(§19.4). Оптимистическая маркировка до ответа запрещена. Дедуп поставки —
по ключу `(run_id, context_id, канонический снапшот)`; повторная загрузка
одноимённого файла (новый run) доставляется заново (план §12 п.4). Ключ
вселенной фактов (`universeKey`: Upload — `datasetId`, Validation/
Preprocessing — имя датасета, EDA — `datasetKey`) различает запуски в
легаси-фолбэке, где пара (run, context) недоступна; транзитный null карты
(профиль «running» фокус-рефетча) вселенную не меняет и повторной поставки
не рождает. EDA-якорь seed'а (`anchorSnapshot`) — снапшот, уже известный как
записанный: идентичный якорю снапшот не доставляется (семантика seed-маркера
PROGR-18 сохранена).

### 20.4. Acceptance без receipt (легаси-приёмка) — УТВЕРЖДЕНО

Ответ `200` без `mode="v2"`/`receipt` (легаси-режим сервера, §19.5) отражается
честным статусом `accepted_legacy`, `delivered=false` — «принято» не равно
«записано в долговременный слой». Легаси-acceptance засчитывается в дедуп
поставки: серверный легаси-контур без идемпотентности, повтор задублировал бы
факты — недоставка в легаси предпочтительнее дубля. Честная граница: до
отключения легаси-пути (release-marker, решение тимлида) строгие гарантии
доставки обеспечивает только v2-режим.

### 20.5. Легаси-фолбэк клиента и изоляция stale — УТВЕРЖДЕНО

Биндинг берётся из `GET /v1/progress/trace` — ТОТ ЖЕ источник, что проверяет
сервер (durable `run.context_id`, §19.2, I3); кэшируется на вселенную. Оба
поля (run_id, context_id) непустые — v2-конверт; иначе (старый бэкенд,
сбой сети) — легаси-фолбэк: тело БЕЗ `schema_version` одним POST, без retry
(§20.2). Изоляция stale (план §12 п.3): каждая POST-попытка несёт токен,
in-flight запрос абортируется (AbortController); поздний успех/ошибка
устаревшей поставки (после смены снапшота, смены вселенной или unmount)
состояние новой вселенной не изменяют; замещённая поставка не помечается
записанной. `409 stale_run/stale_context` — refresh биндинга + ОДНА
повторная поставка текущего снапшота с НОВЫМ report_id; повторный 409 —
стоп (не бесконечный повтор старого тела, план §12 п.5). Механизм только
доставляет карту: коррекции данных вместе с POST карты не запускаются.

### 20.6. Offline/unmount: границы in-memory — УТВЕРЖДЕНО

При unmount in-flight абортируется, таймеры снимаются; недоставленность
отражается в состоянии хука (`undelivered`/`stale`) и может быть показана UI.
Очередь доставки — in-memory в браузере: перезагрузка страницы НЕ переживается
(TTL-очередь не обещается, план §12 п.6); после remount текущий снапшот
доставляется как новое клиентское наблюдение (новый report_id). Постоянное
переживание отказа — OUTBOX-контур AUDIT-6B, не UI.

### 20.7. Приёмка, versioned-обновления пинов и границы

- RED-протокол: `scripts/prograudit2b_red_repro.txt` — на базе 9e8edde оракул
  `packages/ui/hooks/useProgressMapDelivery.test.tsx` (18 оракулов §12 RED)
  целиком красен suites-failed-to-run (TS2307: модуль механизма не существовал;
  форма RED для нового файла — прецедент AUDIT-2A). Поведенческие пины старого
  поведения (AUDIT-0 H26) были зелёными на базе как пины дефекта.
- Оракул механизма: `packages/ui/hooks/useProgressMapDelivery.test.tsx` —
  18/18 GREEN (v2-конверт формы хука; H26: 500 → retry с тем же report_id →
  исчерпание без ложного delivered → возобновление сменой снапшота; потерянный
  ответ → тот же report_id/payload; легаси-фолбэк одним POST и без retry;
  поздний ответ A после B; дедуп (run, context, snapshot); same filename/new
  run; 409 stale_context refresh + одна повторная поставка, повторный 409 —
  стоп; report_id_conflict без retry; 422 без retry; unmount-аборт; EDA-якорь;
  уникальность report_id; принудительный redeliver; null-map).
- Продюсеры: четыре компонента переведены на хук (гейты отчёта и семантика
  «панель == модулю» сохранены); Upload сохраняет принудительный ре-пост после
  подтверждения структуры (`redeliver()`, новый report_id).
- Versioned-обновления тестов (план §20.2 п.6): наблюдательные пины AUDIT-0
  обновлены как заявлено в их шапках — `prograudit0_h26_no_auto_retry.test.tsx`
  (H26 ЗАКРЫТ: пин дефекта заменён пином нового контракта — ограниченный retry
  с тем же report_id, исчерпание без ложного delivered, возобновление сменой
  снапшота) и `prograudit0_h28_viewed_transfer.test.tsx` (семантика переноса
  viewed сохранена; счётчик GET /trace +1 — биндинг поставки I3; контекст
  цели/ревизии остаётся у AUDIT-3).
- Регресс: jest UI-контур 162 сюиты / 1944 теста — 0 failed (включая адресные
  TsAnalysis* и пины AUDIT-0/5B/25B/C-CERT); `tsc --noEmit` обоих воркспейсов
  (embedded+standalone) — чисто. Python-адресные сюиты контура «Прогресс»
  (21 файл, карты/панель/хук/семья аудита) — 470 passed / 17 skipped / 0
  failed (с очисткой мусорного `DATABASE_URL` песочницы — документированный
  средовой класс). e2e-смоук живого ASGI-контура
  `scripts/prograudit2b_e2e_smoke.py` (+`_results.txt`): 15/15 — биндинг
  /trace, v2-конверт формы хука → 200+mode=v2+receipt, retry того же тела →
  deduplicated=true и прежний receipt, чужой run → 409 stale_run, легаси-тело
  → mode=legacy.
- Границы (вне задачи): отключение легаси-пути и закрытие P24 целиком —
  решение тимлида (release-marker) после AUDIT-2B; серверный реестр
  результатов/durable result_id — AUDIT-6B/7A; монотонность просмотров EDA
  по контексту, seed-failure и P25 — AUDIT-3; переживание reload/offline
  очередью — AUDIT-6B; сертификация AUDIT-2B — независимым раундом.

---

## 21. Аддендум v1.1-3A — EDA: показ, запрос и свежесть (PROGR-AUDIT-3) — **УТВЕРЖДЕНО-3A**

Задача AUDIT-3 (plan_progress_audit.md §13) реализована на базе `main@4289a83`
(HEAD = коммит PROGR-AUDIT-2B-CERT). Настоящий аддендум фиксирует контракт
разделения «запрос ≠ показ», контекст-ключевой монотонности EDA-фактов и
устойчивого seed'а просмотров. Закрываются F17/P25 и H27/H28; interim-
монотонность H1 (§13 контракта, «заменяется контекст-ключевой при AUDIT-3»)
заменена.

### 21.1. Разделение запроса и показа (Р1) — УТВЕРЖДЕНО

GET-профили EDA означают ЗАПРОС/ВЫЧИСЛЕНИЕ; «ни один GET сам по себе не
удостоверяет просмотр человеком». Носитель запроса — новый тип события
`profile_requested` (стадия `eda`, статус-проекция `running`, evidence_level
`operational`), сеется хуком трассы (9 исследовательских GET-роутов);
троттлинг §4.2 сохранён (дефолт 5 мин/узел; `PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS`).
Событие ПОКАЗА результата приходит ТОЛЬКО от UI — карта просмотров
`eda_check_status` (done/pending по факту «аналитик открыл и просмотрел
результат», решение тимлида v1.1 §2 — без изменений). `profile_viewed`
остаётся легаси-типом ЧТЕНИЯ (реестр/карта статуса сохранены; корпус не
переписывается, §3.7); хук его больше не сеет. Отчёт §5.4 получил шаблон
факта `profile_requested` (честная формулировка запроса).

### 21.2. Контекст-ключевая монотонность редьюсера (Р2/Р4) — УТВЕРЖДЕНО

Interim-монотонность H1 (глобальная по всем контекстам) заменена контекст-
ключевой в едином движке `NodeStateFold`:

  * смена контекста утверждается ТОЛЬКО когда контексты ОБОИХ статусных
    фактов (хранимого и нового) известны и различны; неизвестные контексты
    (легаси-события без envelope) смену НЕ утверждают — защита done
    сохраняется (unknown ≠ смена; честная деградация легаси-корпуса);
  * В СВОЁМ контексте (P25/F17): запрос профиля (`profile_requested`/
    `profile_viewed` → running) не понижает узел, уже достигший состояния
    честнее running (done/warning/error/skipped); повторный запрос
    идемпотентен; касание (last_touched_at) и reason честно обновляются,
    источник статуса (_status_src) остаётся событием done (I10);
  * СМЕНА контекста (оба известны, различны) — новая применимость (H28):
    last-wins честен (running/pending нового контекста переоткрывают узел;
    исторический done остаётся в ledger с validity=stale — I4).

### 21.3. Неретракт рутинного pending карты EDA (Р3, H27) — УТВЕРЖДЕНО

Рутинный `pending` ПОЛНОЙ карты `eda_check_status` в СВОЁМ контексте не
retract-ит просмотренный `done` (срыв seed'а клиента не стирает историю;
«увиденный результат не развидеть»). Понижение running → pending не
защищается (честная семантика «не просмотрено»). ЯВНЫЙ retract — ОТДЕЛЬНЫЙ
контракт, настоящей задачей не реализуется. Периметр неретракта — ТОЛЬКО
`eda_check_status`: карты Валидации/Предобработки сохраняют last-wins
(детерминированные статусы профильных ответов — вне периметра AUDIT-3).

### 21.4. Seed из полной проекции и удержание отчёта (H27) — УТВЕРЖДЕНО

Seed множества просмотренных берётся из `/v1/progress/trace` при монтировании
и при смене вселенной фактов; seed считается состоявшимся ТОЛЬКО при
`response.ok` И `projection_complete !== false` (деградация session_tail —
слой 2 недоступен при существующем запуске — историю не выдаёт; fresh-сессия
`projection_source="session"` — bootstrap работает). Из 13-полевого контракта
узлов (AUDIT-5B) сеются ТОЛЬКО факты со статусом `done` и
`validity === "current"`; stale (устаревшее) и unknown (легаси) не сеются —
карта не воскрешает просмотры прежнего контекста (H28). Старый бэкенд (нет
поля `nodes`) — прежний плоский `node_statuses` без фильтра (N-3).

Если seed НЕ получен (отказ /trace, неполная проекция): отчёт УДЕРЖИВАЕТСЯ —
разрушительная пустая/все-pending карта поверх known history не отправляется;
якорь остаётся null (не подменяется все-pending снапшотом). Ретрай seed'а —
по каждому НОВОМУ просмотру (момент, когда отчёт становится нужен); успех —
отчёт объединённым снапшотом (seed + локальные просмотры), неудача —
продолжение удержания. Просмотры при несостоявшемся seed'е фиксируются
локально (монотонное множество) — факты не теряются.

### 21.5. Вселенная фактов EDA: датасет + цель (H28) — УТВЕРЖДЕНО

Ключ вселенной фактов EDA — пара (datasetKey, target): серверный
`context_id = f(run, data#revision, target, temporal)`
(`data_context.context_components`) — смена цели при том же датасете
сдвигает контекст расчёта. Смена цели: сброс множества просмотров + re-seed
полной проекции + новая вселенная доставки (свежий биндинг I3; дедуп прежней
вселенной не подавляет новую). Ключ доставки (`universeKey`) —
`${datasetKey}\u0000${activeFeature}`; монотонное объединение достижений —
ВНУТРИ контекста. Гейт готовности seed'а отсекает окно «показ результата
старого расчёта» (профили перезапрашиваются по цели; на время перезапроса
статус running — факта просмотра нет). Гонка первого seed'а монтирования
закрыта гейтом `hasDataset`/`targetLoading` (seed — один, после разрешения
цели; `targetError` не удерживает отчёт бессрочно).

### 21.6. Versioned-обновления тестов (план §20.2 п.6) — УТВЕРЖДЕНО

  * `prograudit0_h27_seed_failure_regresses.test.tsx` — пин дефекта H27
    заменён пином контракта: отказ seed удерживает отчёт; ретрай по новому
    просмотру; восстановление — объединённый снапшот без понижений.
  * `prograudit0_h28_viewed_transfer.test.tsx` — пин дефекта H28 заменён
    пином контракта: смена цели — новая вселенная (сброс + re-seed); карта
    нового контекста не переносит просмотры прежней цели.
  * `tests/api/test_progress_audit_h1.py::test_other_event_types_unaffected`
    — ассерт «pending после done» (пин дефекта H27) заменён: рутинный
    pending в своём контексте не retract-ит done; контроль периметра —
    карты Валидации сохраняют last-wins.
  * `tests/api/test_progress_progr18.py::test_eda_checks_last_wins_on_rereport`
    — докстринг ограничен контекстной монотонностью (ассерт апгрейда
    pending → done прежний).
  * `tests/api/test_progress_trace_hook.py` (5 тестов), 
    `tests/api/test_node_status_engine.py` (3), `tests/api/test_trace_events.py`
    (1) — пины старого типа GET-события/состава карт: `profile_requested`.

### 21.7. Приёмка и границы — УТВЕРЖДЕНО

Приёмка (план §13 GREEN): done не регрессирует от GET (юнит P25 + e2e);
seed failure не стирает историю (UI-удержание + бэкенд-неретракт — двойная
защита); новая цель/ревизия имеет новую применимость (юнит H28 + e2e
validity stale→pending); обратный порядок GET/отчёт — done в обоих; показ
результата старого расчёта — закрыт гейтом готовности; троттлинг
`profile_requested` — 5 мин/узел (повторы в окне не плодят события, чужой
узел — своё). Оракулы: `tests/api/test_progress_audit_3.py` (25 тестов:
REG/CM/E2E/RPT/периметр) и `packages/ui/components/prograudit3_eda_seed_freshness.test.tsx`
(5 сценариев S1–S5); RED-протоколы на базе 4289a83 —
`scripts/prograudit3_red_protocol.txt` (backend 14 RED / 11 контролов,
UI 4 RED / 1 контроль).

Границы (вне задачи): явный retract-контракт; валидационные/предобработочные
карты (last-wins прежний); легаси-режим доставки (биндинг недоступен —
контексты нет, смена цели бэкендом не различима, честная деградация); P24
old-write (решение тимлида о release-marker); переживание reload — AUDIT-6B;
шаблоны отчёта Modeling/версии пояснений — AUDIT-7B; raw restore/validity
компонентного уровня — AUDIT-8; сертификация AUDIT-3 — независимым раундом.

---

## 22. Аддендум v1.2-8A — raw restore и checkpoint metadata (PROGR-AUDIT-8) — **УТВЕРЖДЕНО-8A**

Задача AUDIT-8 (plan_progress_audit.md §14) реализована на базе `main@493e5b6`
(HEAD = коммит PROGR-AUDIT-3). Настоящий аддендум фиксирует контракт честного
raw-восстановления и metadata чекпоинтов. Закрываются F03/P05 и H05 в части
raw-семантики и применимости исторического прогресса (происхождение цели —
v0.7-1A §17, здесь не пересматривается); I4 конкретизируется до уровня
проверяемых правил.

### 22.1. Restore: режим raw и новые ревизии — УТВЕРЖДЕНО

Restore загружает ИСХОДНЫЙ файл (§12 п.3), промежуточные состояния DataFrame
НЕ восстанавливаются (§5.3) — ответ ЯВНО называет это честно (аддитивно, N-3):
`mode="raw"` (константа; full snapshot replay — отдельный контракт,
сознательно НЕ реализован), `data_revision` (ревизия восстановленной сессии;
raw — 0), `context_id` (серверный context_id нового контекста расчёта,
детерминизм I3), `context_changed` (True — новый контекст отличается от
прежнего хранимого; False — контекст продолжается либо прежний неизвестен:
легаси-запуск без хранимого контекста сравнивать не с чем — честное
отсутствие). История run продолжается (append-only), cookie меняется (§5.3) —
ответ ничего не обещает о восстановлении состояний данных сверх raw-файла.

### 22.2. Run-метаданные контекста следуют raw-входу (P05/H05) — УТВЕРЖДЕНО

После raw restore run-метаданные (context_id/data_revision/data_digest)
обновляются на контекст ВОССТАНОВЛЕННОЙ сессии. Проекция (validity против
run.context_id, PR-4) не использует СТАРУЮ current-validity для raw входа:
исторические done остаются видимыми (ledger не переписывается, I4), но их
применимость — stale/unknown; новый применимый расчёт появляется только с
новым фактом нового контекста (e2e: карта Валидации от восстановленной
сессии — validity current). Детерминизм I3 сохранён: restore запуска БЕЗ
мутаций и с той же парой цели даёт ТОТ ЖЕ context_id (context_changed=False,
применимость продолжается). Сдвиг контекста — легитимный CAS-переход
(паттерн коррекций §14.5/6A: продюсер читает ХРАНИМЫЙ контекст на момент
чтения — уже новый); модельные/карточные гейты 409 не ломаются.

### 22.3. Чекпоинт: metadata создания снимка — УТВЕРЖДЕНО

Чекпоинт связывает снимок с РЕАЛЬНЫМ current контекстом и watermark'ом ЕГО
СОЗДАНИЯ (аддитивные поля `ResearchCheckpoint`/`CheckpointOut`:
context_id/data_revision/watermark, миграция 0004 — файл-дубль
`apps/api/migrations/0004_audit8_checkpoint_metadata.sql`, паритет Memory/
Postgres I8, NULL — честное отсутствие легаси-строк §3.7). Ссылка на event_id
— именованный якорь (§5.1), она НЕ означает «DataFrame в момент того
события»: снимок — DataFrame вызывающей сессии НА МОМЕНТ создания (RED-
карточка «чекпоинт с ранним event_id после поздней коррекции» — metadata
несут контекст/позицию создания, отличные от якоря). Watermark — позиция
durable-истории запуска (число фактов ledger слоя 2) на момент создания, ДО
факта checkpoint_saved; свежие события слоя 1, ещё не зеркалированные (P15),
в неё не входят — позиция привязана к durable-корпусу, не к волатильному
хвосту и не к cap слоя 1 (после restore с усечённым засевом watermark —
ПОЛНАЯ позиция ledger). Чужая сессия — ссылка без снимка и без контекстных
метаданных (has_snapshot=False, context/data_revision None), watermark
записывается (позиция не зависит от сессии).

### 22.4. DTO/UI снимка: что видно потребителю — УТВЕРЖДЕНО

DTO чтения (GET /runs/{run_id}) и создания (POST /checkpoints) несут
metadata; UI (ProgressCheckpointBar) показывает для каждого снимка: наличие
(«снимок данных»), контекст создания, позицию durable-истории и honest-
пометку «Восстановление запуска (raw) снимки чекпоинтов не применяет;
промежуточные состояния данных не восстанавливаются (§5.3)» (рендер при
наличии снимков: без снимков «не применять» нечего). Поля аддитивны (N-3):
старый бэкенд/легаси-чекпоинты — прежний рендер без контекста/позиции,
поля не выдумываются.

### 22.5. Неразрушительность восстановления — УТВЕРЖДЕНО

Restore не меняет исходный raw файл (контроль SHA-256 до/после) и не удаляет
исторические факты (ledger append-only: после restore корпус — прежний
плюс ровно один run_resumed; событий выбора/сброса restore не сеет —
v0.7-1A §17 сохранён). Отсутствующий raw-файл — честный 409 (§5.3, пин
сохранён).

### 22.6. Приёмка и границы — УТВЕРЖДЕНО

Приёмка (план §14 GREEN): raw восстановление честно обозначено (mode/ревизии
в ответе; e2e P05 — stale→current на новом входе); старый data_types done
historical/stale; checkpoint metadata не обещают недоказанного воспроизведения
(контекст/позиция создания ≠ момент якоря; snapshot replay явно вне задачи).
Оракулы: `tests/api/test_progress_audit_8.py` (15 тестов: RAW/CTX/P05/CHK/CAP
— 9 RED / 6 контролов на базе 493e5b6, протокол `scripts/prograudit8_red_protocol.txt`)
и `packages/ui/components/prograudit8_checkpoint_metadata.test.tsx`
(S1–S4). Versioned-обновление: `tests/api/test_research_runs_postgres.py::
test_checkpoints_roundtrip` (metadata roundtrip + легаси-строка без
metadata) на живом PostgreSQL (pgserver, 19/19).

Границы (вне задачи): full snapshot replay и применение снимков — отдельный
контракт; восстановление date_column и производных состояний сессии —
сознательно не расширялось (компоненты контекста считаются по фактическому
состоянию восстановленной сессии); P24 old-write — решение тимлида о
release-marker; сертификация AUDIT-8 — независимым раундом; документ отчёта
(историческая применимость в MD/HTML) — AUDIT-7B.
