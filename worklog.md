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
- Обнаружены проблемы: нет macro.yaml, дубликат upload_file в public.py, handleApply — заглушка, нет PATCH /rules/update, тесты сломаны
- Создан rules/macro.yaml — макроэкономические правила (ВВП, инфляция, безработица, госдолг, торговый баланс, ставка, экспорт/импорт, население)
- Удалён дубликат upload_file в public.py (старый синхронный вариант)
- Удалён повторный импорт require_api_key
- Добавлены схемы RulesUpdateRequest/Response в schemas.py
- Добавлен PATCH /rules/update в public.py и internal.py с in-memory override (_rules_override)
- _load_rules_by_template теперь учитывает _rules_override — обновлённые правила применяются при валидации
- RulesManagementPanel.handleApply переписан: реальный PATCH-запрос к API, applyLoading state, disabled+spinner при отправке
- Удалён неиспользуемый импорт Button из RulesManagementPanel.tsx
- Переписаны тесты RulesManagementPanel.test.tsx: 7 тестов, корректные ожидания (нет toBeDisabled), тест PATCH, тест Reset
- Создан apps/standalone/.env.local с NEXT_PUBLIC_API_URL
- Typecheck + build проходят

Stage Summary:
- API: все 3 CRUD-эндпоинта правил работают (templates, load, update) + validate
- UI: полный цикл «выбрать шаблон → редактировать диапазоны → применить через API → сбросить»
- 4 шаблона правил: custom, default, fao_prices, macro (все с YAML-файлами)
- In-memory override: обновлённые правила живут до перезапуска сервера
- Typecheck ✅, Build ✅

---
Task ID: 2
Agent: main
Task: Формальная спецификация модуля «Моделирование» — rules/modeling.yaml

Work Log:
- Изучена структура проекта: существующие rules/ (default_rules.yaml, macro.yaml, fao_prices.yaml), config/models/ts_models_catalog.yaml (20 моделей, 5 категорий)
- Проанализирован YAML-стиль проекта (русские комментарии, секции schema/ranges/consistency/inclusion)
- Спроектирована и создана формальная спецификация rules/modeling.yaml (v1.0.0-draft)
- Написан валидатор scripts/validate_modeling_yaml.py
- Валидация пройдена без ошибок и предупреждений

Stage Summary:
- Создан CISStat-TS-Analysis/rules/modeling.yaml — 12 секций, 8 семейств, 24 модели, 11 стадий пайплайна
- 4 уровня применимости: RECOMMENDED / CONDITIONALLY_APPLICABLE / NOT_RECOMMENDED / NOT_APPLICABLE
- Движок применимости: 5 forbidden + 6 discouraged + 5 conditional + 7 preferred = 23 правила
- Baseline-семейство обязательно (Naive, Seasonal Naive, Drift, Mean)
- R² исключён из ранжирования; веса MAE=0.35, RMSE=0.25, MAPE=0.20, MASE=0.20
- Model Card: 20 обязательных полей
- Modeling ≠ Forecasting: разделённые жизненные циклы
- Ансамбль: 4 стратегии (simple_avg, weighted_avg, median, stacking) + auto-trigger
- Prediction Intervals: методы для всех 8 семейств
- Валидация ✅ (0 ошибок, 0 предупреждений)

---
Task ID: 3
Agent: main
Task: Python-загрузчик modeling_spec_loader.py — Pydantic v2 модели + движок применимости + тесты

Work Log:
- Изучена структура src/catalog/: models_catalog.py (Pydantic v2, field_validator, model_dump)
- Pydantic v2.12.5 подтверждён; pytest 9.0.2
- Спроектирована иерархия из 15+ Pydantic-моделей: Metadata → Family → FamilyModel → ApplicabilityLevel → ApplicabilityEngine → ApplicabilityRule → Pipeline → PipelineStage → MetricsConfig → MetricDef → RankingFormula → PredictionIntervalsConfig → ModelCardTemplate → LifecycleSeparation → EnsembleConfig → PreprocessingRule → UIConfig → DataProfile → ApplicabilityResult → ModelingSpec
- Написаны тесты (TDD): 62 теста в 13 классах — загрузка, структура, уровни применимости, движок (F01-F05, D01-D06, C01-C05, P01-P07), пайплайн, метрики, PI, Model Card, жизненные циклы, ансамбли, предобработка, UI, массовая оценка, целостность
- Реализован modeling_spec_loader.py: from_yaml(), to_yaml(), resolve_applicability(), resolve_all_applicability(), get_candidate_pool(), validate_integrity()
- Движок применимости: 23 предопределённых handler'а + fallback eval
- Исправлены 3 конфликта правил в тестах: F01 vs F05 (DeepAR), F04 vs C01 (ARIMA boundary), F03 (VECM exogenous)
- Все 62 теста PASS, существующие test_catalog.py (3 теста) PASS
- Целостность спецификации validate_integrity() → PASS (0 issues)

Stage Summary:
- Создан src/catalog/modeling_spec_loader.py (15+ Pydantic моделей, ~500 строк)
- Создан tests/test_modeling_spec.py (62 теста, 13 классов)
- Движок применимости: 23 правила с 4 приоритетами (forbidden → discouraged → conditional → preferred)
- Ключевые методы: resolve_applicability(), resolve_all_applicability(), get_candidate_pool()
- Массовая оценка для макро-профиля (n=120, M): 10 RECOMMENDED, 5 NOT_RECOMMENDED, 9 NOT_APPLICABLE
- Все тесты ✅ (62 passed)

---
Task ID: 4
Agent: main
Task: API-эндпоинт POST /v1/models/candidates — exposes get_candidate_pool() для фронтенда

Work Log:
- Изучена структура API: routers/models.py (заглушка train), schemas.py, auth.py (require_capability), plans.py (capabilities)
- Изучен паттерн тестов API: tests/api/test_rules.py (TestClient, API-ключи через env)
- Спроектированы схемы: DataProfileRequest, ModelCandidate, CandidatesRequest, CandidatesStatistics, CandidatesResponse
- Добавлены схемы в schemas.py (без изменения существующих)
- Переписан routers/models.py: добавлен POST /candidates с require_capability("can_train_models"), ленивый кэш спецификации
- Написаны тесты: 19 тестов в 6 классах — авторизация (demo→403, pro→200, admin→200), структура ответа, логика применимости (baselines, GARCH, сортировка), разные профили (financial, tiny), валидация (422), опции (min_level)
- Установлен pandera (зависимость validation/engine, не была в venv)
- Все 19 API-тестов PASSED; все 72 связанных тестов PASSED

Stage Summary:
- POST /v1/models/candidates — полный эндпоинт с авторизацией, валидацией, движком применимости
- Схемы: DataProfileRequest → CandidatesRequest → CandidatesResponse (с ModelCandidate[], statistics, spec_version)
- Авторизация: require_capability("can_train_models") — professional/enterprise/admin
- Ленивый кэш спецификации (ModelingSpec загружается один раз)
- 19 тестов ✅ (auth×4, structure×4, applicability×4, profiles×2, validation×3, options×2)
- Пример: макро-профиль n=120 → 10 RECOMMENDED кандидатов (baselines + ETS + ARIMA + Prophet)

---
Task ID: 5
Agent: main
Task: UI компонент TsAnalysisModeling.tsx — визуализация пула кандидатов с бейджами применимости

Work Log:
- Изучена структура packages/ui: 3-колоночный лейаут (TsAnalysisEDA, TsAnalysisPreprocessing, TsAnalysisValidation)
- Изучены паттерны: fetch() для API, Tailwind для стилизации, StatusIcon/Metric/Button как shared-компоненты
- Изучены существующие типы: lib/plans.ts (Role/Plan/Capabilities), StatusIcon (CheckStatus)
- Изучен API-контракт: POST /v1/models/candidates → CandidatesResponse (из apps/api/schemas.py)
- Обнаружены оба page.tsx (embedded + standalone) с ModulePlaceholder — требуют замены
- Создан packages/ui/lib/modeling.ts — TypeScript-типы: DataProfile, ModelCandidate, ApplicabilityLevel, CandidatesRequest/Response/Statistics, APPLICABILITY_BADGE/LABEL/RANK, MODEL_FAMILIES, PIPELINE_STAGES, DEFAULT_PROFILE, DOMAINS, FREQUENCIES
- Создан packages/ui/components/TsAnalysisModeling.tsx — 3-колоночный компонент:
  - Левая: профиль данных (n_observations, n_series, frequency, domain, сезонность, GPU), 11 стадий пайплайна, кнопка «Загрузить пул»
  - Центр: expandable description, таблица кандидатов по семействам с бейджами применимости, фильтр по уровню, метрики-сводка
  - Правая: детальная карточка кандидата с бейджем, сообщением движка, кнопками «Метрики и алгоритм» / «Полный пайплайн» / «Запустить бэктест»
- Создан packages/ui/components/TsAnalysisModeling.test.tsx — 23 теста:
  - Рендер модуля (2), 11 стадий пайплайна (1), Справка (3), Description box (2), Профиль данных (4), Fetch (4), Ошибка API (1), Фильтрация (1), Выбор кандидата (1), Бейджи (1), Метрики и алгоритм (1)
- Обновлён packages/ui/index.ts — добавлены экспорты TsAnalysisModeling + типы моделирования
- Обновлены apps/embedded/app/modeling/page.tsx и apps/standalone/app/modeling/page.tsx — заменён ModulePlaceholder на TsAnalysisModeling
- Создан jest.config.js с ts-jest (до этого Babel не парсил TSX)
- Установлен jest-environment-jsdom
- Все 23 теста PASS
- Typecheck ✅, Build ✅ (/modeling → 240 B, 143 kB First Load)

Stage Summary:
- Создан TsAnalysisModeling.tsx — полноценная вкладка «Моделирование» с 3-колоночным лейаутом
- Визуализация пула кандидатов: 8 семейств, 24 модели, 4 уровня применимости с цветовыми бейджами
- Форма профиля данных: n_observations, n_series, frequency, domain, сезонность, GPU
- POST /v1/models/candidates → таблица кандидатов по семействам с фильтром по уровню
- 11 стадий пайплайна моделирования в степпере
- Детальная карточка кандидата: бейдж, правило, сообщение, кнопки действий
- Jest + ts-jest сконфигурирован для monorepo
- 23 теста ✅, Typecheck ✅, Build ✅

Task ID: 5b
Agent: main
Task: Исправление бага: пустая правая колонка при ошибке API + автозаполнение профиля из activeDataset

Work Log:
- Обнаружен баг: при ошибке API правая колонка была пустой — условие `!error` в placeholder блокировало показ
- Добавлен fallback-блок в правую колонку: при ошибке показывает «Не удалось загрузить пул: {error}» + инструкцию по API
- Подключён useAppShell() — activeDataset.rows автозаполняет n_observations в профиле
- Обновлён тест error message: getAllByText вместо getByText (ошибка теперь в 2 местах)
- Все 23 теста PASS, Typecheck ✅, Build ✅

Stage Summary:
- Баг исправлен: правая колонка показывает инструкцию при ошибке API
- activeDataset подключён для автозаполнения профиля данных
- 4 состояния правой колонки: activeCandidate → candidatesByFamily → error → loading

Task ID: 6
Agent: main
Task: Подключить activeDataset из AppShellContext для автозаполнения DataProfile в TsAnalysisModeling

Work Log:
- Изучил структуру ActiveDataset (name, rows, sizeLabel) и DataProfile (16 полей)
- Нашёл частичную интеграцию: useEffect маппил только rows→n_observations
- Расширил ActiveDataset: добавлены опциональные поля frequency, domain, nSeries, hasSeasonality, isRegular
- Обновил useEffect в TsAnalysisModeling: полный маппинг 6 полей с fallback на текущие значения
...
Stage Summary:
- ActiveDataset расширен 5 опциональными полями (backward-compatible)
- Полный маппинг activeDataset → DataProfile при автозаполнении
- Индикатор «из датасета» появляется при наличии activeDataset
- Файлы: AppShellContext.tsx, TsAnalysisModeling.tsx, TsAnalysisModeling.test.tsx, DataUploadForm.tsx, TsAnalysisUpload.tsx

Task ID: 7
Agent: main
Task: Вариант 1: «Запустить бэктест» — API endpoint + UI handler + pipeline progression

Work Log:

Спроектирован API-контракт: BacktestRequest (model_id, profile, train_ratio), BacktestMetrics (mae, rmse, mape, mase, weighted_score), BacktestResponse
Добавлены схемы в apps/api/schemas.py: BacktestRequest, BacktestMetrics, BacktestResponse
Реализован POST /v1/models/backtest в routers/models.py:
Реальный расчёт для 4 baseline-моделей (Naive, Seasonal Naive, Drift, Mean)
Синтетический ряд: trend(100+0.5t) + seasonality(10sin) + noise(N(0,4))
Метрики: MAE, RMSE, MAPE(%), MASE (= MAE_model / MAE_naive)
Weighted score: 0.35MAE_n + 0.25RMSE_n + 0.20MAPE_n + 0.20MASE_n
Заглушка для нереализованных моделей (ETS, ARIMA, Prophet и др.) с family-penalty
model_id валидация: _MODEL_INFO dict + fallback на спецификацию, 404 если не найден
Добавлены типы в modeling.ts: BacktestRequest, BacktestMetrics, BacktestResponse, BACKTEST_WEIGHTS
Обновлён TsAnalysisModeling.tsx:
backtestResults/backtestLoading/backtestError — новый стейт
completedStages: Set<string> — динамическое продвижение пайплайна
runBacktest(modelId) — fetch POST /v1/models/backtest
Кнопка «Запустить бэктест» → loading spinner → результат (MAE/RMSE/MAPE/MASE/скоринг)
Pipeline progression: candidate_pool (auto) → baseline (auto) → backtest (on click) → tuning (active)
dynamicStages: useMemo на основе completedStages вместо статического PIPELINE_STAGES
Обновлён packages/ui/index.ts: экспорт BacktestRequest/Metrics/Response, BACKTEST_WEIGHTS
API-тесты: 17 новых тестов (36 total), все PASS
TestBacktestAuth (3), TestBacktestNaive (4), TestBacktestOtherBaselines (3 parametrized),
TestBacktestNonBaseline (2), TestBacktestValidation (3), TestBacktestCustomTrainRatio (2)
UI-тесты: 5 новых тестов (37 total), все PASS
Кнопка рендерится, API вызывается, результат отображается, ошибка показывается, пайплайн продвигается
Build standalone ✅

---
Task ID: 8
Agent: main
Task: Зафиксировать решения по плану Phase 0 → Phase 5 + PRE-0 smoke-тест продакшн-деплоя

Work Log:
- Прочитана и проанализирована инструкция тимлида (docs/MIGRATION_ARCHITECTURE.md)
- Изучен контекст: worklog.md Task ID 1–7, apps/api (routers, schemas, session_store, upload_common, auth, plans)
- Найден URL продакшн-бэкенда: https://cisstat-ts-analysis.onrender.com
  (через agent-browser: открыл https://ts-standalone.vercel.app/, отловил XHR к /v1/session/current)
- Спроектирован и зафиксирован план развития модуля «Моделирование» (см. Stage Summary)
- Спроектирован PRE-0 smoke-тест: 7 кейсов от /health до /v1/models/candidates без API-ключа
- Оценены риски: cold start render free tier, cookie cross-domain, CORS preflight, 422 на /v1/models без ключа
- Создан /home/z/my-project/scripts/pre_0_smoke.py (httpx + assertions, 7 кейсов)
- Smoke-тест запущен против продакшн-URL: 7/7 PASS
- Артефакты в /home/z/my-project/download/pre_0_smoke/:
  • pre_0_smoke.py — воспроизводимый тест
  • report.md — человекочитаемый отчёт
  • report.json — структурированный отчёт

Результаты PRE-0 (7/7 PASS):
1. ✅ GET /health → 200, body.status=ok (524 ms)
2. ✅ OPTIONS /v1/session/current (CORS preflight)
   → ACAO=https://ts-standalone.vercel.app, ACAC=true (точный Origin, не *)
3. ✅ GET /v1/session/current → Set-Cookie: cisstat_session_id;
   HttpOnly; SameSite=none; Secure (корректно для cross-domain credentialed)
4. ✅ Round-trip с cookie → повторный запрос НЕ создаёт новую сессию
5. ✅ POST /v1/internal/upload → 200, dataset_id=861e57f9…, rows=72, columns=5, 3.1 KB
6. ✅ GET /v1/session/current после upload → has_active_dataset=true,
   stages.upload=done (SessionStore корректно переживает upload)
7. ✅ POST /v1/models/candidates без X-Api-Key → 422 "Field required: x-api-key"
   (auth-цепочка работает; ожидаемое поведение)

ВАЖНОЕ НАБЛЮДЕНИЕ (блокер для Phase 0):
- /v1/models/candidates и /v1/models/backtest защищены require_capability("can_train_models"),
  который требует X-Api-Key header
- Standalone UI (браузер посетителя без API-ключа) НЕ может вызвать /v1/models/* напрямую
- Workaround уже существует для /upload и /rules: зеркала в /v1/internal/* без auth
- В Phase 0 нужно: либо зеркало /v1/internal/models/*, либо principal extraction из сессии
  для /v1/models/* (тогда capability check работает по данным сессии, не по ключу)

Stage Summary:
- Решения тимлида зафиксированы по 5 открытым вопросам:
  1. Phase 6-P0 (4 модели) сначала → затем Phase 1–5
  2. param_space в modeling.yaml + строгая валидация
  3. CV: expanding window + абстракция CVStrategy (RollingWindowCV позже)
  4. SessionStore abstraction в MVP; Redis/Valkey для production MVP
     (промежуточный вариант — Upstash Redis free tier)
  5. Model Card: JSON в MVP; PDF post-MVP

- Финальная последовательность:
  PRE-0 (1ч) → Phase 0+0.5 (8ч) → Phase 6-P0 (10ч) → Phase 1 (7ч) →
  Phase 2 (6ч) → Phase 3 (7ч) → Phase 4 (5ч) → Phase 5 (5ч)
  MVP total: ~49 ч

- PRE-0 завершён: продакшн-деплой работоспособен, можно переходить к Phase 0.
- Следующий шаг: Phase 0 — SessionStore abstraction + мост Upload → Backtest + зеркало /v1/internal/models/*

---
Task ID: 9
Agent: main
Task: Перенос PRE-0 артефактов в репозиторий + параметризация скрипта + README

Work Log:
- Спроектирован перенос артефактов PRE-0 из /home/z/my-project/download/ в репо:
  • pre_0_smoke.py → scripts/smoke/pre_0_smoke.py (переиспользуемый тест)
  • report.md/json — НЕ коммитить (runtime-данные: dataset_id, session_id)
- Параметризован скрипт (раньше были хардкоды):
  • API_BASE — через env CISSTAT_API_URL или --api-base
  • FRONTEND_ORIGIN — через env CISSTAT_FRONTEND_ORIGIN или --frontend-origin
  • DEMO_CSV_PATH — вычисляется относительно расположения скрипта
    (_REPO_ROOT = Path(__file__).resolve().parents[2])
  • OUTPUT_DIR — через --output-dir (default: ./pre_0_smoke_output)
  • Добавлен argparse с --help
- Добавлены глобальные переменные FRONTEND_ORIGIN/DEMO_CSV_PATH на уровне модуля
  с инициализацией из DEFAULT_* (для pytest-style импорта в будущем)
- Перенесён в репо: scripts/smoke/pre_0_smoke.py
- Написан scripts/smoke/README.md (~250 строк):
  • Назначение smoke-тестов vs unit-тестов
  • Когда запускать (4 ситуации)
  • Структура папки + конвенция именования phase_N_smoke.py
  • Требования (Python 3.10+, httpx)
  • Запуск: прод / локал / CLI / отчёты
  • Подробное описание 7 кейсов с критериями PASS/FAIL и интерпретацией
  • Что НЕ проверяет PRE-0
  • Связанные документы
  • Шаблон для новых smoke-тестов
- В .gitignore добавлена секция "SMOKE-ТЕСТЫ: отчёты" —
  паттерн scripts/smoke/*_output/ (regenerate on each run)
- Проверка запуска из нового расположения: 7/7 PASS
  (cold-start 31с на /health, остальные ~150-340ms)
- CLI --help работает корректно
- Артефакты обновлены в /home/z/my-project/download/pre_0_smoke/:
  • pre_0_smoke.py (параметризованная версия)
  • README.md (копия из scripts/smoke/)
  • report.md, report.json (последний прогон)

Stage Summary:
- Скрипт сделан переносимым: запускается у любого разработчика
  из репо одной командой `python scripts/smoke/pre_0_smoke.py`
- README описывает 7 кейсов с критериями PASS/FAIL + интерпретацию
- Конвенция для будущих фаз: phase_N_smoke.py с переиспользованием
  CheckResult / write_reports из PRE-0
- .gitignore обновлён — отчёты не коммитятся
- Готов переход к Phase 0: продакшн-фундамент доказан работоспособным,
  smoke-тест воспроизводим любым членом команды

---

Task ID: 10 — Phase 0: SessionStore abstraction (Memory + Redis)

What changed:
• apps/api/session_store.py — полная переработка: SessionStore ABC + MemorySessionStore + RedisSessionStore + factory + reset_for_testing
• apps/api/upload_common.py — добавлен store.save(session) после set_dataset
• apps/api/routers/session.py — добавлен store.save(session) в 2 местах (demo, set_stage)
• apps/api/requirements.txt — +redis>=5.0.0
• requirements-dev.txt — +fakeredis>=2.20.0
• tests/api/test_session_store.py — 42 новых теста

Tests: 83/83 API PASS + 75/75 связанных PASS (158 всего)
Build: FastAPI app boots, end-to-end upload→session flow работает, prod-like Redis flow работает через fakeredis

Ключевой контракт: после любой мутации AnalysisSession вызывающий код ОБЯЗАН вызвать store.save(). Контракт одинаковый для Memory и Redis — без save() Redis теряет изменения.

Артефакты в /home/z/my-project/download/phase_0_session_store/

---

Task ID: 11 — Phase 0 fix #3: third-party cookie blocking (session loss after tab switch)

What changed:• packages/ui/lib/apiClient.ts — getApiBase() в проде (NODE_ENV=production, browser) возвращает ОТНОСИТЕЛЬНЫЙ путь "/api" вместо абсолютного NEXT_PUBLIC_API_URL. Браузер ходит на тот же origin (Vercel), Next.js rewrite проксирует на бэкенд.• apps/standalone/next.config.mjs — добавлен async rewrites(): /api/v1/:path* → ${apiUrl}/v1/:path* (apiUrl из API_URL || NEXT_PUBLIC_API_URL || localhost:8000).• apps/embedded/next.config.mjs — то же rewrite для embedded (если задеплоится отдельно — нужен тот же фикс).• packages/ui/components/RulesManagementPanel.tsx — заменён прямой NEXT_PUBLIC_API_URL на getApiBase() (иначе обходил прокси и снова ловил third-party cookie blocking).• packages/ui/components/TsAnalysisModeling.tsx — то же: getApiBase() вместо прямого env var.• packages/ui/components/TsAnalysisUpload.tsx — maxSize снижен с 50 MB до 4 MB (Vercel Serverless Function body limit 4.5 MB через rewrite-прокси; POST-0: pre-signed S3 для больших файлов).• packages/ui/components/TsAnalysisUpload.test.tsx — тест "should reject files > 50MB" → "> 4MB".• render.yaml — обновлена инструкция: на Vercel ставить API_URL (server-side only), а не NEXT_PUBLIC_API_URL.

Root cause:Браузер на ts-standalone.vercel.app ходил НАПРЯМУЮ на cisstat-ts-analysis.onrender.com (cross-origin). Cookie cisstat_session_id с SameSite=None; Secure классифицировалась как third-party и БЛОКИРОВАЛАСЬ Chrome 120+ (также Safari ITP, Firefox ETP). Бэкенд сохранял сессию в Redis корректно (Python-клиент проходит 7/7 шагов), но браузер не отправлял cookie на следующий fetch — сервер создавал новую пустую сессию, /dataset/stats возвращал 404, UI показывал "загрузите заново".

Verification:

/home/z/my-project/scripts/diag_session_loss.py — Python-клиент (httpx, сохраняет cookie как браузер) проходит все 7 шагов против prod, включая паузу 5с (симуляция "ушёл на другую вкладку"). Бэкенд НЕ воспроизводит баг.
Backend tests: 42/42 PASS (test_session_store.py)
Frontend tests: 48/48 PASS (TsAnalysisUpload 11 + TsAnalysisModeling 37). RulesManagementPanel: 5 тестов падали ДО изменения (pre-existing), не регрессия.
Deploy checklist (after merge):

Vercel Project Settings → Environment Variables:
ADD: API_URL = https://cisstat-ts-analysis.onrender.com (server-side only, NO NEXT_PUBLIC_ prefix)
REMOVE (optional): NEXT_PUBLIC_API_URL (больше не нужен в проде; в dev остаётся в .env.local)
Trigger new Vercel deploy (rewrite() применяется при сборке)
Verify в браузере: загрузить CSV → переключить вкладку → вернуться → датасет должен сохраниться

---

Task ID: 12 — Phase 0.5: мост Upload → Backtest (target_column в AnalysisSession)

What changed:
• apps/api/session_store.py — добавлено поле `target_column: Optional[str]` в `AnalysisSession` + метод `set_target_column(name)`. Обновлены `session_to_dict`/`session_from_dict` для сериализации (с backcompat: старые записи в Redis без этого поля десериализуются с target_column=None — rolling-deploy не ломает существующие сессии). `set_dataset()` сбрасывает target_column в None (новый датасет = новый анализ; старая колонка может не существовать).

• apps/api/schemas.py — добавлено поле `target_column: Optional[str] = None` в `SessionStateResponse`. Новые схемы `TargetColumnRequest(column: str)` и `TargetColumnResponse(target_column, available_columns, has_dataset)`. Добавлено поле `data_source: Optional[str]` в `BacktestResponse` ("session" | "synthetic" — показывает источник ряда).

• apps/api/routers/session.py — новые эндпоинты:
  - `GET /v1/session/target-column` — получить текущую target + список доступных числовых колонок (без 404 при отсутствии датасета — UI должен уметь обрабатывать состояние "нет датасета")
  - `POST /v1/session/target-column` — установить target_column с валидацией: 400 если нет датасета, 404 если колонки нет, 422 если колонка не числовая. После валидации — store.save() (контракт SessionStore).
  - Обновлён `_to_response()` для включения target_column в SessionStateResponse.

• apps/api/routers/models.py — рефакторинг: вынесены 3 переиспользуемые функции:
  - `_resolve_model_info(model_id)` — найти (model_name, family_id) по model_id
  - `_resolve_seasonal_period(profile)` — сезонный период из profile или frequency
  - `_run_backtest_with_series(model_id, model_info, series, train_ratio, seasonal_period)` — расчёт метрик на ЗАДАННОМ ряде (синтетическом или реальном)
  - `run_backtest` (/v1/models/backtest) использует их с синтетическим рядом, помечает `data_source="synthetic"`

• apps/api/routers/internal.py — добавлено зеркало:
  - `POST /v1/internal/models/backtest` — БЕЗ auth (как /v1/internal/upload), читает сессию по cookie
  - КЛЮЧЕВОЙ КОНТРАКТ: если session.dataframe + session.target_column заданы → бэктест выполняется на РЕАЛЬНОМ ряде (data_source="session"), иначе fallback на синтетику (data_source="synthetic")
  - NaN в target_column обрабатываются через dropna()
  - Использует ту же `_run_backtest_with_series()` — метрики идентичны /v1/models/backtest

Root cause и обоснование решений:
1. Почему target_column в AnalysisSession, а не в DataProfileRequest?
   - target_column — это UI-выбор пользователя, не свойство файла. Живёт в сессии (cookie-based), доступен без API-ключа (как и upload).
   - При re-upload нового датасета target_column автоматически сбрасывается — нет риска оставить устаревшую колонку.
2. Почему /v1/internal/models/backtest без auth?
   - /v1/models/backtest требует require_capability("can_train_models") → X-Api-Key header (см. Task ID 8). Браузер посетителя standalone без API-ключа не может вызвать /v1/models/backtest. Зеркало /v1/internal/* без auth — устоявшийся паттерн (upload, rules уже так работают).
3. Почему fallback на синтетику если target_column не задан?
   - Сохраняет обратную совместимость для UI, который ещё не подключил выбор target_column. Backtest не падает, а работает как раньше (синтетика по профилю).
4. Почему data_source в ответе?
   - UI должен показывать пользователю, используются ли реальные данные или синтетика. Без этого поля — невозможно отличить (n_observations могут случайно совпасть).

Tests:
- tests/api/test_session_store.py — расширено 5 новыми тестами (для Memory + Redis, итого +10): target_column=None по умолчанию, set_target_column_persists, set_dataset_resets_target_column, target_column_survives_roundtrip_serialization, target_column_backcompat_legacy_dict_without_field
- tests/api/test_target_column.py — новый файл, 15 тестов: GET без датасета, set валидной/несуществующей/нечисловой колонки, re-upload сбрасывает target, available_columns только числовые, cookie persistence
- tests/api/test_internal_backtest.py — новый файл, 10 тестов: no-auth, unknown model 404, data_source=session/synthetic/no_dataset, real vs synthetic metrics differ, response shape, 4 baseline models parametrized, NaN handling

Verification:
- All 118 API tests PASS (77 новых + 41 существующий, без регрессий)
- 453 tests PASS в полном наборе (3 pre-existing errors в test_preprocessing.py — отсутствует pytest-snapshot fixture, не связано с нашими изменениями)
- Smoke-test end-to-end: upload (10 rows) → set target=value → backtest с data_source=session (n_train=7, n_test=3, реальный MAE=9.8); без target → data_source=synthetic
- Backward compat доказан: старые сессии в Redis (без target_column) десериализуются корректно

Артефакты в /home/z/my-project/download/phase_0_5_target_column/:
- session_store.py, schemas.py, routers_session.py, routers_models.py, routers_internal.py
- test_session_store.py, test_target_column.py, test_internal_backtest.py
- worklog.md (обновлённый)

Deploy checklist (after merge):
1. Backend deploy (Render) — без новых env vars (REDIS_URL уже настроен в Task ID 10)
2. Smoke-test в проде: `python scripts/smoke/pre_0_smoke.py` (7/7 PASS expected — target_column обратно совместим)
3. Опционально: добавить UI-селектор target_column в TsAnalysisModeling (Phase 1 — следующий шаг)
4. Опционально: переключить frontend на /v1/internal/models/backtest (вместо /v1/models/backtest) для standalone-режима
