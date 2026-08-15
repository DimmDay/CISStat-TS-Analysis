# CISStat TS Analysis — Worklog

---
Task ID: 1
Agent: main
Task: Полный перенос «Управление правилами» в вкладку «Валидация» + подключение к apps/api реальных функций валидации

Work Log:
- Изучена структура apps/api: main.py, routers/public.py, routers/internal.py, schemas.py, auth.py, plans.py
- Обнаружены СУЩЕСТВУЮЩИЕ API-эндпоинты: GET /rules/templates, GET /rules/load/{id}, POST /rules/validate (и в public, и в internal)
- Обнаружены СУЩЕСТВУЮЩИЕ схемы: RulesTemplate, RulesTemplatesResponse, RangeRule, RulesContent, RulesLoadResponse, ValidateWithRulesRequest/Response
- Обнаружен СУЩЕСТВУЮЩИЙ UI: RulesManagementPanel.tsx с селектором шаблона, редактором диапазонов, кнопками Применить/Сбросить
- Создан rules/macro.yaml — макроэкономические правила (ВВП, инфляция, безработица, госдолг, торговый баланс, ставка, экспорт/импорт, население)
- Удалён дубликат upload_file в public.py (старый синхронный вариант)
- Добавлен PATCH /rules/update в public.py и internal.py с in-memory override (_rules_override)
- Переписаны тесты RulesManagementPanel.test.tsx: 7 тестов
- Создан apps/standalone/.env.local с NEXT_PUBLIC_API_URL
- Typecheck + build проходят

Stage Summary:
- API: CRUD эндпоинты правил работают + validate
- UI: полный цикл «выбрать шаблон → редактировать диапазоны → применить через API → сбросить»
- 4 шаблона правил: custom, default, fao_prices, macro
- In-memory override: обновлённые правила живут до перезапуска сервера

---
Task ID: 2
Agent: main
Task: Формальная спецификация модуля «Моделирование» — rules/modeling.yaml

Stage Summary:
- 8 семейств, 24 модели, 11 стадий пайплайна
- 4 уровня применимости: RECOMMENDED / CONDITIONALLY_APPLICABLE / NOT_RECOMMENDED / NOT_APPLICABLE
- 23 правила применимости
- Baseline-семейство: Naive, Seasonal Naive, Drift, Mean
- R² исключён из ранжирования; веса MAE=0.35, RMSE=0.25, MAPE=0.20, MASE=0.20
- Model Card: 20 обязательных полей
- Ансамбль: 4 стратегии + auto-trigger

---
Task ID: 3
Agent: main
Task: Python-загрузчик modeling_spec_loader.py + движок применимости + тесты

Stage Summary:
- Pydantic v2 модели для ModelingSpec
- resolve_applicability(), resolve_all_applicability(), get_candidate_pool(), validate_integrity()
- 23 handler'а правил
- 62 теста PASS + test_catalog.py

---
Task ID: 4
Agent: main
Task: POST /v1/models/candidates

Stage Summary:
- Полный endpoint с авторизацией и движком применимости
- 19 API-тестов PASS

---
Task ID: 5
Agent: main
Task: UI TsAnalysisModeling.tsx — пул кандидатов

Stage Summary:
- 3-колоночный UI
- 24 модели / 8 семейств / 4 уровня применимости
- 11 стадий пайплайна
- 23 UI-теста PASS, Typecheck PASS, Build PASS

---
Task ID: 5b
Agent: main
Task: Исправление пустой правой колонки при ошибке API + activeDataset

Stage Summary:
- Error fallback в правой колонке
- activeDataset.rows → n_observations
- 4 состояния правой колонки

---
Task ID: 6
Agent: main
Task: Полная интеграция activeDataset → DataProfile

Stage Summary:
- ActiveDataset расширен backward-compatible полями
- Полный маппинг activeDataset → DataProfile

---
Task ID: 7
Agent: main
Task: «Запустить бэктест» — API + UI + pipeline progression

Stage Summary:
- POST /v1/models/backtest
- Реальные baseline-модели
- BacktestMetrics: MAE/RMSE/MAPE/MASE/weighted_score
- UI показывает результат и продвигает pipeline
- API/UI тесты PASS

---
Task ID: 8
Agent: main
Task: Зафиксировать решения Phase 0 → Phase 5 + PRE-0

Stage Summary:
- Phase 6-P0 сначала → затем Phase 1–5
- param_space в modeling.yaml
- expanding-window CV
- SessionStore abstraction + Redis для production MVP
- Model Card JSON в MVP
- PRE-0 production smoke PASS

---
Task ID: 9
Agent: main
Task: Перенос PRE-0 smoke-теста в репозиторий

Stage Summary:
- scripts/smoke/pre_0_smoke.py
- scripts/smoke/README.md
- smoke reports в gitignore
- 7/7 PASS

---
Task ID: 10 — Phase 0: SessionStore abstraction (Memory + Redis)

Stage Summary:
- SessionStore ABC + MemorySessionStore + RedisSessionStore
- store.save() после мутаций AnalysisSession
- redis/fakeredis зависимости
- 83/83 API PASS + 75/75 связанных PASS

---
Task ID: 11 — Phase 0 fix: third-party cookie blocking

Stage Summary:
- Vercel same-origin /api proxy
- Next.js rewrites → Render
- cookie round-trip стабилизирован
- upload limit 4 MB через Vercel proxy

---
Task ID: 12 — Phase 0.5: Upload → Backtest

Stage Summary:
- target_column в AnalysisSession
- GET/POST /v1/session/target-column
- /v1/internal/models/backtest использует реальный ряд из session
- data_source=session|synthetic
- 118 API tests PASS; smoke upload→target→backtest PASS

---
Task ID: 13 — Phase 1: UI target_column selector

Stage Summary:
- target_column selector
- internal backtest endpoint
- data_source badge
- 48/48 UI tests PASS
- Typecheck + Next build PASS

---
Task ID: 14 — PRE-1 frontend production smoke

Stage Summary:
- Vercel → Render → Redis flow проверен
- 8/8 PASS

---
Task ID: 15 — Internal candidates mirror + error formatting

Stage Summary:
- POST /v1/internal/models/candidates
- UI switched to internal endpoint
- FastAPI error details formatted
- 50/50 UI + 7/7 backend regression tests PASS

---
Task ID: 16 — Production Docker fix: modeling.yaml

Stage Summary:
- Dockerfile COPY rules/ ./rules/
- build-time ModelingSpec guard
- pre_1 smoke расширен до 9 checks

---
Task ID: 18 — Phase 6-P0 hotfix

Stage Summary:
- Auto-ARIMA grid 18 → 8 fits для Render Free Tier
- per-model smoke timeout
- UTF-8 report writing on Windows

---
Task ID: 17 — Phase 6-P0: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA

Stage Summary:
- 5 реальных statsmodels implementations
- _BACKTEST_IMPLEMENTATIONS расширен до 9 ключей
- 21 новый тест
- local smoke 8/8 PASS
- 5 моделей дают разные MAE

---
Task ID: 19-A — Phase 1-A: param_space

Stage Summary:
- FamilyModel.param_space
- modeling.yaml: ETS=12, ETS Damped=6, ARIMA=18
- 14 новых тестов, 62 regression tests PASS

---
Task ID: 19-B — Phase 1-B: ExpandingWindowCV

Stage Summary:
- CVStrategy ABC
- ExpandingWindowCV
- 33 теста PASS
- 109/109 связанных тестов PASS

---
Task ID: 19-C — Phase 1-C: POST /v1/models/tune

Stage Summary:
- grid search + expanding-window CV
- MAX_TRIALS=64
- reproducible random sampling
- 60 новых тестов PASS; 169/169 связанных PASS
- На этом этапе _tunable_predict был STUB.

---
Task ID: 19-D — Phase 1-D: интеграционные тесты реальных ETS/ARIMA

Stage Summary:
- tests/api/test_tune_real_models.py
- baseline skip
- ETS grid 12
- ARIMA grid 18
- CV split/leakage checks
- max_trials checks
- На старте задачи production _tunable_predict оставался STUB намеренно.

---
Task ID: 19-E — Production-разрыв Tune → реальные ETS/ARIMA

Цель:
закрыть production-разрыв между Phase 1-C tuning engine и Phase 6-P0 real
model implementations. POST /v1/models/tune больше не должен использовать
детерминированный stub для ETS/ARIMA.

Процесс решения:
1. Синхронизирована отдельная ветка от актуального main, чтобы не перетирать
   параллельные изменения команды.
2. Проверены точки интеграции: apps/api/routers/models.py, real model
   implementations в apps/api/model_impls/{ets,arima}.py, rules/modeling.yaml,
   Phase 1-D tests.
3. Выбран единый production dispatch через маленький модуль
   apps/api/model_impls/tuning.py, который переиспользует реальные
   statsmodels fit/predict функции.
4. Production _tunable_predict оставлен как API-level dispatch, а не как
   вторая реализация моделей.

Изменения:
- apps/api/model_impls/ets.py
  • _ets_fit_predict получил опциональные trend/seasonal параметры.
  • Старый Phase 6-P0 backtest контракт сохранён (defaults).
  • Мультипликативные варианты требуют строго положительные данные.
  • Сезонность при недостатке двух полных периодов не ломает CV, а
    выполняется без seasonal component явно.
- apps/api/model_impls/tuning.py
  • tune_ets_predict(): передаёт параметры текущего grid trial в реальный
    ExponentialSmoothing.
  • tune_arima_predict(): передаёт p,d,q текущего trial в реальный ARIMA.
- apps/api/routers/models.py
  • _tunable_predict заменён production dispatch:
      ets / ets_damped → tune_ets_predict
      arima → tune_arima_predict
    Остальные модели не получают ложный stub; возвращают явный 422.
  • Ошибочный trial (ValueError/RuntimeError/ArithmeticError) пропускается
    с warning; если ни один trial не завершился, endpoint возвращает 422.
  • Existing grid/CV/max_trials контракт сохранён.
- tests/api/test_tune_real_models.py
  • Убрана проверка «реальный прогноз отличается от legacy stub» — stub больше
    не является production contract.
  • Оставлена проверка реального statsmodels fit/predict.
- tests/api/test_tune_production_dispatch.py
  • Новый regression suite: production dispatch ETS/ARIMA, количество
    реальных вызовов = trials × folds, параметры реально передаются,
    unsupported model не получает fake forecast, mul ETS не silently fallback.
- worklog.md
  • Добавлена текущая запись Task 19-E.

Риски и меры:
- R1: двойная реализация моделей → tuning.py использует существующие
  Phase 6-P0 функции, новый statsmodels fit не создаётся.
- R2: ETS grid-параметры теряются → regression spy проверяет trend/seasonal/
  damped параметры на каждом вызове.
- R3: mul ETS на отрицательных данных → явный ValueError, trial пропускается,
  а не замена на additive model.
- R4: одна невалидная комбинация ломает весь tuning → trial-level isolation.
- R5: все trials невалидны → явный HTTP 422 вместо ложного best trial.
- R6: baseline/no-param model → существующий 422 contract сохраняется.
- R7: параллельные изменения команды → отдельная ветка от актуального main;
  изменены только файлы текущей задачи.

Тесты/сборка:
- В этой runtime-среде полноценный pytest/build не выполнен: доступ к
  локальному checkout ограничен сетевым DNS. Поэтому PASS полного набора
  намеренно НЕ заявляется.
- Тестовый код рассчитан на существующие зависимости statsmodels из Phase 6-P0.
- Перед merge требуется выполнить:
  `python -m pytest tests/api/test_tune.py tests/api/test_tune_real_models.py tests/api/test_tune_production_dispatch.py -q`
  затем полный API regression suite и Next.js build.

Статус:
- Production dispatch реализован в отдельной ветке.
- Phase 1-D теперь имеет production wiring к реальным ETS/ARIMA.
- После CI/Render smoke PASS Phase 1 tuning можно считать закрытым и переходить
  к Phase 2 — диагностике остатков.
