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

Versioned-обновление (Донастройка_2 п.3): фиксировает реализацию дорожки и уточнения
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
