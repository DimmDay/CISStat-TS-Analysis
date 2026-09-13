# MIGRATION ARCHITECTURE — схема сессий, артефактов и миграций

CISStat TS Analysis. Документ фиксирует контракты, на которые ссылаются
`apps/api/session_store.py` и `scripts/smoke/README.md`: архитектура
монорепозитория, шесть этапов анализа (§1.1), схема Redis-документа сессии
(§2), версионирование и миграция modeling-артефактов (§3) и контур
lineage-инвалидации (§4).

## 1. Архитектура монорепозитория

| Путь | Роль |
|---|---|
| `apps/api` | FastAPI-бэкенд: EDA, моделирование, реестр v2 из 24 моделей, lineage-контур |
| `apps/standalone` | Next.js-оболочка (прод: Vercel `ts-standalone.vercel.app`), rewrite `/api/v1/*` → Render |
| `apps/embedded` | Next.js-оболочка для встраивания в портал |
| `packages/ui` | Общая UI-библиотека (в т.ч. `ModuleNav`, порядок стадий синхронен `STAGES`) |
| `rules/modeling.yaml` | Формальная спецификация модуля «Моделирование» (версия в `metadata.version`) |
| `scripts/smoke/` | Дымовые тесты продакшн-деплоя (PRE-0/PRE-1/фазовые) |

Бэкенд-деплой: Render (`render.yaml`, Docker, healthcheck `/health`).
Cookie-фикс (2026-08-12): rewrite через серверную переменную `API_URL`
делает сессионную cookie first-party (Chrome 120+ блокирует SameSite=None
third-party cookies).

### 1.1 Шесть этапов анализа

Порядок и состав совпадают с `ModuleNav`
(`packages/ui/components/ModuleNav.tsx`) и с `apps/api/session_store.py::STAGES`:

```
upload → validation → preprocessing → eda → modeling → forecasting
```

«Задачи» (What-if/iDSS) сознательно НЕ входят в пайплайн — по контракту
вкладки «Загрузка» это отдельная сущность, не шаг основного контура.

Внутри этапа `modeling` живёт 11-стадийный под-пайплайн
(`apps/api/model_readiness.py::MODELING_STAGE_IDS`):

```
problem_definition → data_structure → constraint_mapping →
candidate_generation → baseline_estimation → backtest → tuning →
diagnostics → comparison → selection → model_card
```

Стадии зафиксированы синхронно в коде (`MODELING_STAGE_IDS`), в
`rules/modeling.yaml::pipeline.stages` (order 1..11) и во фронтенде
(`packages/ui/lib/modeling.ts::ModelingStageId`). Полная capability-матрица
финализации — 24 модели × 11 стадий (Task 143).

## 2. Схема Redis-документа сессии

- Ключ: `cisstat:session:{session_id}`; TTL 30 дней (`SESSION_TTL_SECONDS`),
  обновляется при каждом `save()`.
- Хранение: JSON-строка (`session_to_dict`), DataFrame через
  `orient='split'` (`dataframe_json`); ограничение Upstash free tier —
  10 MB/команда.
- Оптимистичная конкуренция: `storage_revision` + WATCH/MULTI
  (CAS); расхождение → `SessionConflictError` (409 на уровне API).
- **Якорь версии схемы (Task 143): `session_schema_version`**.
  Константа `SESSION_SCHEMA_VERSION = 1` (`apps/api/session_store.py`).
  Новые `save()` пишут поле; старые документы (поле отсутствует) читаются
  как схема 0 — «дефолт при чтении» сохраняет rolling-deploy совместимость.
  Правила:
  1. Любое ЛОМАЮЩЕЕ изменение схемы сессии обязано поднять
     `SESSION_SCHEMA_VERSION` и обработать предыдущую версию ЯВНО
     (функция миграции + тест), а не расширять эвристику «по отсутствию
     полей».
  2. Документ с версией БОЛЬШЕ поддерживаемой читается без падения
     (rolling back-deploy); факт логируется warning'ом — последующий
     `save()` может урезать незнакомые поля.
- Graceful degradation: нечитаемый документ (битый JSON, бинарный мусор —
  `json.JSONDecodeError`/`UnicodeDecodeError`/`KeyError`/`TypeError`)
  → `get()` возвращает `None` + warning; `get_or_create()` создаёт пустую
  сессию (семантика «протухшего TTL»: пользователь теряет прогресс,
  сервис жив). `save()` поверх нечитаемого документа разрешён — мусор не
  несёт ревизии и не может быть «свежее»; CAS защищает только валидные
  документы.
- Фабрика: `get_session_store()` — Redis при `REDIS_URL`/`CISSTAT_SESSION_BACKEND=redis`,
  иначе MemorySessionStore; недоступный Redis на старте → fallback на
  Memory с `logger.error`.

## 3. Modeling-артефакты: версионирование и миграция

- Схема артефактов: `MODELING_ARTIFACT_SCHEMA_VERSION = 7`
  (`apps/api/routers/modeling_session.py`), поле `artifact_schema_version`
  внутри `session.modeling_artifacts`.
- Миграция: `_migrate_modeling_artifacts` — при несовпадении версии
  артефакты с невербифицируемой lineage-фактурой дропаются (проверки:
  `tuning_id`, `cohort_id`, objective, `parameter_signature`,
  `oof_signature`, `execution_contract.runtime_available` +
  `library_versions`, привязка FeaturePlan `plan_id`+`fingerprint`,
  кросс-линк tuning↔backtest), downstream (comparison/selection/
  model_cards) сбрасывается, журнал пишется в
  `artifacts["artifact_migration"]` (to_version, счётчики инвалидаций,
  reason, migrated_at).
- Исторические миграции: v4→5 (сохранение валидных прогонов),
  v5→6 (инвалидация прогонов без v2-lineage), v6→7 (привязка
  FeaturePlan). Тесты: `tests/api/test_modeling_workflow.py`
  (`test_state_v4_upgrade_*`, `test_state_v5_upgrade_*`, v6→7).
- Ответы API совместимы по полям: новые фактура-поля (например `panel`
  Task 142 в `BacktestResponse`) добавляются как `Optional` с `None`-дефолтом —
  pre-Task-142 клиенты и Redis-документы валидны.

## 4. Lineage-инвалидация моделирования

Примитивы: `series_fingerprint` (паспорт ряда) → `cohort_id`
(sha256: fingerprint + target + folds + cohort_contract = objective +
series_fingerprints + feature_contract + metric_policy) →
`plan_id`/`matrix_hash` (FeaturePlan) → `parameter_signature`/
`oof_signature`/`diagnostics_signature` → `job_signature`.

Каскад (downstream-артефакты сбрасываются при апгрейде upstream):

| Событие | Механизм | Сброс |
|---|---|---|
| Смена датасета/target/date | `reset_passports()` → `reset_modeling()` | весь modeling-контур |
| Расхождение fingerprint артефактов с текущим рядом | `_prepare_state` | `reset_modeling()` + свежий скелет артефактов |
| Новый прогон модели | `_invalidate_after_model_run` | diagnostics[model], comparison, selection, model_cards |
| Новые diagnostics | `_invalidate_after_diagnostics` | comparison, selection, model_cards |
| Дрейф cohort/adapter/policy у job | `step_modeling_job` | job → `stale` + 409 |

Стадии «done» только при закрытии всего required-scope
(`_refresh_execution_readiness`); diagnostics сверяются с backtest по
`backtest_run_id`/`residuals_signature`/`parameter_signature`/`cohort_id`.
Staleness-флаги: `passport/status → is_stale`, `GET /modeling/state → stale`,
job `stale`. Comparison-гейт `aligned_oof` отвергает смешение objective и
cohort_contract («GARCH нельзя ранжировать рядом с ETS/ARIMA»).

## 5. Связанные документы

- `scripts/smoke/README.md` — дымовые тесты продакшн-деплоя.
- `docs/modeling_task_list.md` — постановки задач модуля «Моделирование».
- `rules/modeling.yaml` — формальная спецификация (8 семейств, применимость,
  пайплайн 11 стадий, метрики, правила).
- `worklog_summary.md` / `worklog5.md` — история работ и сертификаций.
