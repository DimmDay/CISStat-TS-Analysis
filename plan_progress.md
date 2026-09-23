# План работ: микросервис «Прогресс» (spec_progress.md v3 + аддендум v4)

Дата: 2026-09-23. Синхронизация: `main@ab0ef57`. Правила: `AGENTS.md` (TDD RED→GREEN,
запрет commit/push, ZIP изменённых/новых файлов в download, записи в worklog7.md).

Источники: `spec_progress.md` (v3) + `spec_progress_review_and_v4_addendum.md` (Часть 5 —
рекомендуемый порядок работ). Все факты, помеченные в аддендуме «требует верификации по
живому файлу», проверены по живому коду на `ab0ef57` — см. §1.

---

## 1. Верификация фактов по живому коду (первый шаг по аддендуму, выполнена)

| Факт | Источник в спецификации | Проверка на `ab0ef57` | Итог |
|---|---|---|---|
| `TraceEvent` реализован с полями `event_type/timestamp/payload` | аддендум п.2.1 | `apps/api/trace_events.py` — frozen-датакласс, 3 поля, `make_trace_event` fail-closed на `FORECAST_EVENT_TYPES` | **поля РАЗОШЛИСЬ с каноном §4.1** — миграция реальна, не гипотетична |
| Единственный импортёр модуля | — | `routers/forecasting_session.py::54` (только `make_trace_event`) | миграция низкорискованная: прямых конструкций `TraceEvent(...)` и читателей `.timestamp` вне модуля нет |
| Pydantic-контракт ответа требует `timestamp` | — | `apps/api/schemas.py::ForecastTraceEventSchema` (поле обязательное; лишние ключи фильтруются) | `to_dict()` обязан продолжать отдавать ключ `timestamp` — двойная запись |
| `CHECK_IDS` Валидации = 10 | §2 | `validation/rule_resolver.py::21` | совпало дословно |
| `PREPROCESSING_CHECK_IDS` = 10, без `passport` | §2 | `apps/api/routers/session.py::313` | совпало дословно |
| `MODELING_STAGE_IDS` = 11 | §2 | `apps/api/model_readiness.py::18` | совпало дословно |
| EDA `CHECKS` = 10 (frontend-only) | §2 | `packages/ui/components/TsAnalysisEDA.tsx::91` | совпало дословно |
| `STAGES` (6 стадий), `StageStatus`, `PassportCheckpoint`, TTL 30 дней | §2, §3.1, §5.1 | `apps/api/session_store.py::106/108/138/66` | совпало дословно |
| `CheckStatus` (6 значений) / `StageStatus` (3 значения) | §3 | `StatusIcon.tsx::22` / `packages/ui/lib/stages.ts::23` | совпало дословно |
| Ширина `EventsLogDrawer` = `w-80` | аддендум §4.2 | `EventsLogDrawer.tsx::28` — `w-80` | подтверждено → панель «Прогресс» = `w-[40rem]` |
| Кнопка «Логи событий» в `ModuleNav.tsx`, слот справа | §6.1, аддендум §4.1 | `ModuleNav.tsx::184–199` (`ScrollText`), `EventsLogDrawer` в ::204 | подтверждено |
| Прогнозирование реализовано (эндпоинты есть) | аддендум п.2.1 | `routers/forecasting_session.py`: `POST /forecast`, `/compare`, `/sensitivity`, `GET /export`, `POST /{id}/trace`; 4 вызова `make_trace_event` | категория C §11 схлопывается; узел «Прогнозирование» строится сразу |
| `AnalysisSession.stages` частично заполнен (upload/modeling) | §3.1 | `set_stage` — только 2 точки вызова | решение §3.1 «Прогресс не читает/пишет `session.stages`» остаётся в силе |

---

## 2. Архитектурное решение (кратко по слоям)

1. **Граф пайплайна** — `app/core/pipeline_graph.py`: единственный реестр узлов 6 стадий;
   Python-реестры импортируются напрямую, EDA-id — копия с маркером синхронизации;
   import-time инвариант `STAGES == session_store.STAGES` (паттерн CERTIFIED_IDS-тестов).
2. **Модель узла** — `PipelineNodeState` (§3): `CheckStatus` для проверочных стадий,
   `StageStatus` для процессных (modeling/forecasting); свёртка в 3 визуальных состояния
   только для рендера карточек; любой `warning/error` в стадии → жёлтая карточка (§12 п.10).
3. **Трасса** — канонический `TraceEvent` §4.1 (8 полей) в `apps/api/trace_events.py`;
   события пишутся хуком на изменяющих эндпоинтах (таблица маршрутов путь→(stage, node,
   event_type)), читающие profile-эндпоинты — троттлинг `profile_viewed` (дефолт 5 мин,
   env-переменная).
4. **Персистентность, два слоя** (§5): слой 1 — `AnalysisSession.pipeline_trace`
   (внутрисессионный буфер, TTL = TTL сессии, без изменений архитектуры); слой 2 —
   `research_runs`/`trace_events` в Postgres (§12 п.1), `run_id` ≠ `session_id`.
   `session.stages` НЕ используется (§3.1, решение подтверждено аддендумом п.2.3 —
   осознанное сосуществование с хабом задач `/tasks` зафиксировать в тексте спеки).
5. **Наставник** (§7) — правило-движок без LLM: §7.1 «Следующий шаг» (on_demand, одно
   срабатывание по priority), §7.2 sanity-правила (on_correction_result, весь список;
   preview-встраивание ДО apply; пороги в `rules/*.yaml` §12 п.7), `thrashing` —
   on_demand_with_history. `MentorTextRenderer` — точка расширения LLM (§8, не реализуется).
6. **UI** (§6 + аддендум Часть 4): `ProgressDrawer.tsx` (`w-[40rem]`, паттерн
   `EventsLogDrawer`), pill-кнопка «Прогресс» на месте «Логи событий» (контракт §4.1
   аддендума: bg-white/border-brand неактивна, bg-brand/text-white font-semibold активна,
   aria-expanded), `ProgressStageFlow`, `ProgressTraceLog`, `ProgressCheckpointBar`,
   `MentorPanel`/`MentorInlineWarning`; `EventsLogDrawer` + `AppShellContext.log` — удаляются.

---

## 3. Декомпозиция на подзадачи

| ID | Задача | Слой | Файлы (ожидаемые) | Приёмка |
|---|---|---|---|---|
| **PROGR-1** | **Сведение `TraceEvent` с каноном §4.1 + миграция legacy** (задача №1 по аддендуму Часть 5) | backend | `apps/api/trace_events.py` (канонические 8 полей: `event_id/run_id/ts/stage/node_id/event_type/payload/actor`; `timestamp` — legacy-алиас; реестр `STAGE_EVENT_TYPES` по стадиям §4.1, run-level типы `run_paused/run_resumed/checkpoint_saved` валидны на любой стадии; `normalize_trace_event_dict` — миграция 3-польных stored-событий; `from_dict`; `to_dict` — 8 канонических ключей + legacy-алиас `timestamp`), `tests/api/test_trace_events.py` (новый) | RED→GREEN: новые тесты канона; ноль правок `forecasting_session.py` (совместимость через дефолты); полный suite `tests/api/` без новых падений |
| PROGR-2 | Граф пайплайна `pipeline_graph.py` + `PipelineNodeState` + свёртка статусов | backend | `app/core/pipeline_graph.py` (новый), `tests/api/test_pipeline_graph.py` (новый); опционально §12 п.2: `shared/pipeline_nodes/eda_checks.json` — вынос EDA CHECKS из .tsx (рекомендация «вынести сейчас») | import-инвариант `STAGES == session_store.STAGES`; все 6 стадий, 46 узлов; свёртка §12 п.10 тестами |
| PROGR-3 | Внутрисессионный слой трассы (§5 слой 1) + хук записи событий | backend | `apps/api/session_store.py` (+`pipeline_trace`), `apps/api/trace_hook.py` (таблица маршрутов), точечные включения в роутеры, `tests/api/test_progress_trace_hook.py` | события `correction_applied/mode_changed/...` пишутся на успешных ответах; `profile_viewed` троттлится; `run_id` фиксируется при первой загрузке |
| PROGR-4 | UI-панель «Прогресс» + кнопка-триггер (аддендум §4.1–4.2) | frontend | `packages/ui/components/ProgressDrawer.tsx`, `ProgressStageFlow.tsx`, `ProgressTraceLog.tsx` (новые), `ModuleNav.tsx`, `AppShellContext.tsx` (изменения), удаление `EventsLogDrawer.tsx`, тесты *.test.tsx | pill-контракт §4.1 (aria-expanded, bg-brand активная); `w-[40rem]`; закрытие кликом вне + крестик; блок-схема 6 стадий; трасса персистентна; jest-сьюты зелёные; typecheck/build чисто |
| PROGR-5 | Долговременный слой: `research_runs`/`trace_events` (Postgres §12 п.1) + чекпоинты/пауза/restore | backend | `apps/api/research_runs.py` (новый), миграции схемы, `GET /v1/progress/runs/{run_id}/restore` | `run_id` переживает cookie; restore строит новую сессию из трассы; чекпоинт = именованная ссылка на событие (паттерн `PassportCheckpoint`) |
| PROGR-6 | Наставник v1: §7.1 «Следующий шаг» + §7.2 sanity-правила | backend+frontend | `app/core/mentor_rules.py` (новый), `rules/mentor.yaml` (пороги §12 п.7), `GET /v1/progress/runs/{run_id}/mentor/next-step`, `POST /v1/progress/mentor/sanity-check`, `MentorPanel.tsx`, `MentorInlineWarning.tsx` | одно срабатывание §7.1 по priority; весь список §7.2; предупреждение в Предпросмотре ДО apply, не блокирует кнопку (§12 п.8); пороги не хардкод |
| PROGR-7 | Отчёт для пользователя (§5.4) | backend | `GET /v1/progress/runs/{run_id}/report?format=md|html` | линейный отчёт из `trace_events`, терминология «Метрики и алгоритм»; forecasting-экспорт — по ссылке на `GET .../forecast/{id}/export.json` |
| PROGR-8 | Admin-панель (§10) + офлайн-потребители (§9) — категория D | backend+frontend | `AdminProgressDashboard.tsx`, `GET /v1/progress/admin/*` (API-ключ, `Role.ADMIN`) | агрегаты по корпусу; частота sanity-предупреждений по правилу/узлу; старт — по накоплении данных (не гейтится кодом) |

**Зависимости:** PROGR-1 → PROGR-2 → PROGR-3 → {PROGR-4, PROGR-5} → PROGR-6 → PROGR-7;
PROGR-8 — независимая ось (время/данные). Категория B (§11) — Mentor-правила по новым
семействам моделей — инкрементально в PROGR-6 без отдельных этапов.

---

## 4. Риски и митигации

| Риск | Митигация |
|---|---|
| Переименование `timestamp`→`ts` ломает `ForecastTraceEventSchema` (поле обязательное) и фронтенд-интерфейс `ForecastTraceEvent` | Двойная запись в `to_dict()`: 8 канонических ключей + legacy-алиас `timestamp`. Pydantic фильтрует лишние ключи — контракт ответа не меняется. Фронтенд в PROGR-1 не трогается |
| Смешение `CheckStatus`/`StageStatus` в единую модель | Явное поле `stage`-зависимого статуса в `PipelineNodeState`; свёртка только на уровне рендера (§3) |
| Дублирование EDA-id фронт/бэк уйдёт в реализацию | PROGR-2 выполняет §12 п.2 (общий JSON) — правка при первом касании, не миграция |
| Циклические импорты (`pipeline_graph` ↔ `session_store`) | Направление зависимостей: `pipeline_graph` → реестры Python-модулей; инвариант — тестом, не взаимным импортом |
| Redis-сессии со старыми 3-польными событиями | `normalize_trace_event_dict` применяется на границе чтения трассы (PROGR-3), fail-closed к дефолтам канона |
| Регрессии 134 frontend-сьютов при замене `EventsLogDrawer` | PROGR-4 заменяет слот кнопки построчно по контракту §4.1; удаление `log/addLogEntry` — атомарно с подключением `ProgressDrawer` |

---

## 5. Текущий статус

- **PROGR-1 — в работе в этой сессии** (TDD RED→GREEN, см. worklog7.md).
- PROGR-2..8 — ожидают постановки/очерёдности тимлида.
