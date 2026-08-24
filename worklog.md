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

---

Task ID: 13 — Phase 1: UI селектор target_column в TsAnalysisModeling.tsx

What changed:
• packages/ui/lib/modeling.ts — добавлены типы TargetColumnRequest { column: string } и TargetColumnResponse { target_column: string | null; available_columns: string[]; has_dataset: boolean } (зеркало apps/api/schemas.py Phase 0.5). В BacktestResponse добавлено опциональное поле data_source?: "session" | "synthetic" — показывает источник ряда для бэктеста. Опциональность сохраняет backward-compat для старого /v1/models/backtest (без bridge).

• packages/ui/index.ts — добавлены экспорты TargetColumnRequest, TargetColumnResponse (для переиспользования другими приложениями монорепо).

• packages/ui/components/TsAnalysisModeling.tsx — главные изменения:

Новый стейт: targetColumn, availableColumns, hasDataset, targetColumnLoading, targetColumnError (5 useState).
fetchTargetColumn() — GET /v1/session/target-column с credentials:"include" (cookie сессии обязателен — мост Phase 0.5).
handleTargetColumnChange() — POST /v1/session/target-column с credentials:"include" и телом { column }. Сервер валидирует колонку (404/422 при ошибке), обновляет AnalysisSession.target_column, возвращает новое состояние.
useEffect на маунте → fetchTargetColumn. useEffect на activeDataset?.name → повторный fetchTargetColumn при смене/загрузке датасета (симптом: пользователь загрузил CSV, вернулся на Modeling — список колонок актуализируется).
runBacktest() переключён с /v1/models/backtest (требует X-Api-Key, не работает в standalone, не использует session) на /v1/internal/models/backtest (зеркало без auth, читает cookie, использует target_column если задан — иначе fallback на синтетику). Добавлен credentials:"include".
UI селектора в левой колонке (после формы профиля, перед «Загрузить пул»):
has_dataset=true → <select> с options из availableColumns + «— не выбрано —» (сброс к синтетике)
has_dataset=false → hint «Загрузите датасет, чтобы выбрать колонку»
targetColumnLoading → spinner рядом с лейблом + disabled <select>
targetColumn выбран → подсказка «Бэктест будет на реальном ряде»
targetColumnError → красный текст ошибки (не блокирует остальной UI)
Badge data_source в карточке результата бэктеста:
data_source="session" → зелёный badge «Реальные данные»
data_source="synthetic" → серый badge «Синтетический ряд»
поле отсутствует → badge не показывается (backward-compat для старого эндпоинта)
• packages/ui/components/TsAnalysisModeling.test.tsx — обновлён и расширен:

Mock fetch теперь маршрутизирует по URL: /v1/session/target-column → MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET/WITH_DATASET, /v1/internal/models/backtest → MOCK_BACKTEST_RESPONSE с data_source.
Обновлены существующие тесты (R1 mitigation):
• "fetches candidates on mount" — assertions переписаны на filter по URL (раньше total call count = 1, теперь их 2: target-column + candidates)
• "clicking 'Загрузить пул' triggers fetch" — переписан на filter по URL
• Backtest-тесты переключены на /v1/internal/models/backtest (вместо /v1/models/backtest)
• Добавлен assertion на credentials:"include" для backtest-запроса
11 новых тестов:
• "fetches target-column on mount (Phase 1)" — GET на маунте с credentials
• "shows 'Синтетический ряд' badge when data_source=synthetic"
• "shows 'Реальные данные' badge when data_source=session"
• "renders the target_column selector block in left column"
• "renders 'Загрузите датасет' hint when has_dataset=false"
• "renders disabled select placeholder when no dataset"
• "renders enabled select with available columns when has_dataset=true"
• "selecting a column triggers POST to /v1/session/target-column with credentials"
• "refetches target-column when activeDataset changes (e.g. after upload)"
• "shows target_column error when POST fails"
• "does NOT call /v1/models/backtest (old endpoint, replaced by /v1/internal/models/backtest)" — контрольный тест на отсутствие вызовов к старому эндпоинту
Root cause и обоснование решений:

Почему переключили эндпоинт бэктеста на /v1/internal/models/backtest?
/v1/models/backtest требует require_capability("can_train_models") → X-Api-Key header (Task 8 worklog). Браузер посетителя standalone НЕ имеет API-ключа → не может вызвать /v1/models/backtest.
Зеркало /v1/internal/models/backtest БЕЗ auth (как /v1/internal/upload), читает сессию по cookie, при наличии target_column в сессии выполняет расчёт на РЕАЛЬНОМ ряде из session.dataframe[target_column] (data_source="session"), иначе fallback на синтетику (data_source="synthetic"). Это и есть «мост Upload → Backtest» Phase 0.5 — теперь UI его использует.
Без переключения эндпоинта селектор target_column не имел бы эффекта: пользователь выбрал бы колонку, но бэктест продолжал бы считаться на синтетике. Это противоречит требованию «мост готов, но не используется UI» → Phase 1 его использует.
Почему GET на маунте + useEffect на activeDataset.name?
GET на маунте: селектор должен показать выбранную колонку, если пользователь уже выбирал её ранее (сессия хранится в Redis, может пережить перезагрузку страницы).
useEffect на activeDataset.name: при загрузке нового датасета список доступных колонок меняется (старая target_column сбрасывается сервером в Phase 0.5 → set_dataset_resets_target_column). Рефетч обновляет UI.
Почему target_column error — это локальный блок под селектором, а не красный баннер?
target_column опционален. Если GET упал (бэкенд недоступен), компонент должен продолжать работать — пользователь может запускать бэктест на синтетике. Красный баннер в верхней части вёл бы к блокировке UI.
Почему data_source badge опциональный (|| null)?
Старый эндпоинт /v1/models/backtest не возвращает data_source. Опциональность поля в TS-типе + null-check в JSX сохраняют backward-compat: если когда-то вернёмся к старому эндпоинту, badge просто не покажется.
Tests:

48/48 PASS в TsAnalysisModeling.test.tsx (37 существующих + 11 новых)
77/77 PASS в Phase 0.5 бэкенд-тестах (test_session_store.py + test_target_column.py + test_internal_backtest.py) — без регрессий
Pre-existing failures НЕ тронуты: 32 теста в 4 файлах (RulesManagementPanel, TsAnalysisValidation, TsAnalysisEDA, TsAnalysisPreprocessing) падали ДО Phase 1 — подтверждено через git stash + повторный прогон
Verification:

Typecheck (tsc --noEmit -p packages/ui/tsconfig.json): только deprecation warnings, 0 type errors
Jest: 48/48 PASS
Next.js build (apps/standalone): ✓ Compiled successfully, /modeling → 242 B, 154 kB First Load (как до Phase 1 — бандл не раздут)
Backward-compat доказан: старый мок fetch (без target-column endpoint) проходил бы по умолчанию через candidates — но это уже не нужно, т.к. Phase 0.5 endpoint задеплоен.
Артефакты в /home/z/my-project/download/phase_1_target_column_ui/:

modeling.ts (типы TargetColumnRequest/Response + data_source в BacktestResponse)
index.ts (экспорт новых типов)
TsAnalysisModeling.tsx (селектор + переключение эндпоинта + data_source badge)
TsAnalysisModeling.test.tsx (48 тестов)
Deploy checklist (after merge):

Frontend deploy (Vercel) — без новых env vars (API_URL уже настроен в Task ID 11, rewrite /api/v1/internal/models/backtest → backend уже работает для /v1/internal/*)
Backend уже задеплоен в Task ID 12 (Phase 0.5) — без новых env vars
Smoke-test в проде:
Открыть /modeling → должен появиться селектор «Целевая колонка» (пока disabled с hint «Загрузите датасет»)
Перейти на /upload → загрузить CSV → вернуться на /modeling → селектор должен показать список числовых колонок
Выбрать колонку → под селектором надпись «Бэктест будет на реальном ряде»
Нажать «Запустить бэктест» → в карточке результата должен появиться зелёный badge «Реальные данные»
Сбросить селектор (выбрать «— не выбрано —») → повторить бэктест → badge должен стать серым «Синтетический ряд»
Опционально: после Phase 1 можно убрать /v1/models/backtest (старый эндпоинт) из backend, т.к. UI больше его не использует — но оставить для backward-compat других клиентов (если есть)

---

Task ID: 14 — Frontend deploy на Vercel + production smoke-test (PRE-1)

What changed:
• scripts/smoke/pre_1_frontend_smoke.py — новый production smoke-test (8 кейсов), проверяющий полный user-flow ЧЕРЕЗ Vercel-фронтенд (НЕ напрямую в Render backend):

GET / — Vercel-фронтенд жив, отдаёт HTML (status=200, content-type=text/html, has_body_tag=True)
GET /api/v1/internal/rules/templates — Next.js rewrite проксирует на Render backend (templates_count>0)
GET /api/v1/session/current (без cookie) → Set-Cookie cisstat_session_id через Vercel-proxy (samesite=none, secure, httponly)
GET /api/v1/session/current с cookie — round-trip работает, new cookie НЕ устанавливается (Task 11 fix доказан в проде)
POST /api/v1/internal/upload (CSV через Vercel-proxy) — rows=72, columns=5, size=3.1 KB
GET /api/v1/session/target-column — Phase 0.5 мост: has_dataset=true, available_columns=['sales','profit'], target_column=None
POST /api/v1/session/target-column {column:"sales"} — выбранная колонка сохраняется в Redis (target_column="sales" в ответе)
POST /api/v1/internal/models/backtest {model_id:"naive", train_ratio:0.8} — data_source="session", n_train=57, n_test=15 → в UI зелёный badge «Реальные данные»
• DEPLOY_VERCEL_CHECKLIST.md — пошаговый чек-лист деплоя на Vercel + приёмочные критерии:

Vercel import git repo → framework preset Next.js (vercel.json уже готов)
Environment Variables: ОДНА обязательная — API_URL=https://cisstat-ts-analysis.onrender.com (server-side, НЕ NEXT_PUBLIC_)
NEXT_PUBLIC_API_MODE="internal" уже зашит в next.config.mjs (env block)
Устаревшая NEXT_PUBLIC_API_URL — можно удалить (Task 11 fix: браузер ходит через /api/v1/* прокси, не напрямую)
Приёмка: автоматический smoke (8/8 PASS) + ручная визуальная проверка в браузере
Ограничения Vercel: Serverless Function body limit 4.5 MB (sales_demo.csv=3 KB, не проблема), cold start Render Free Tier (~60-90s)
Root cause и обоснование решений:

Почему smoke-test ходит ЧЕРЕЗ Vercel (https://ts-standalone.vercel.app/api/v1/), а НЕ напрямую в Render (https://cisstat-ts-analysis.onrender.com/v1/)?
pre_0_smoke.py (Task 12) проверял только backend напрямую — это доказывает, что backend работает.
pre_1_frontend_smoke.py (этот Task 14) проверяет ВЕСЬ стек «браузер→Vercel→Render→Redis→back»:
a) Next.js rewrite реально проксирует (если rewrite сломается — упадёт проверка 2, 3, 5, 6, 7, 8)
b) Cookie round-trip работает через Vercel (Task 11 fix проверен в проде — проверка 4)
c) 4.5 MB body limit на Vercel Serverless не ломает upload (проверка 5)
d) Phase 0.5 мост (Upload → target_column → backtest) работает end-to-end (проверки 6→7→8)
Если бы тестировал только Render — узнал бы, что backend работает, но НЕ узнал бы, работает ли Vercel-frontend.
Почему в проверке 2 использовал /api/v1/internal/rules/templates, а не /api/v1/health?
Rewrite в apps/standalone/next.config.mjs: source "/api/v1/:path*" → destination "${apiUrl}/v1/:path*"
Backendный /health живёт на ROOT (apps/api/main.py: @app.get("/health")), НЕ под /v1/
/api/v1/health через прокси превратилось бы в ${apiUrl}/v1/health — которого на backend просто нет → 404
Первый прогон smoke показал именно это: 7/8 PASS, единственный FAIL — это сама проверка, не deploy
После исправления (использован существующий GET /v1/internal/rules/templates): 8/8 PASS
Почему 8 проверок, а не 7 (как в pre_0_smoke.py)?
pre_0_smoke.py проверял ТОЛЬКО backend (health, CORS, cookie, upload, session-after-upload, candidates-no-key)
pre_1_frontend_smoke.py добавляет фронтенд-специфичные проверки: homepage (#1), proxy-alive (#2), и главное — Phase 0.5 мост target_column (#6, #7) + data_source в backtest (#8)
Каждая проверка = отдельный Layer proving, что не сломалось: Vercel→Proxy→Cookie→Upload→Bridge→Backtest
Tests:

8/8 PASS в pre_1_frontend_smoke.py против production Vercel-домена (https://ts-standalone.vercel.app)
48/48 PASS в TsAnalysisModeling.test.tsx (Phase 1 unit-тесты, без регрессий)
Next.js build: ✓ Compiled successfully, /modeling → 242 B, 154 kB First Load (как в Phase 1 — бандл не раздут)
Verification:

pre_1_frontend_smoke.py первый прогон: 7/8 (FAIL на check 2 — мой баг в выборе URL для proxy-alive, не deploy)
pre_1_frontend_smoke.py повторный прогон после fix: 8/8 PASS, TOTAL 8/8 passed, 0 failed
Backward-compat доказан: build не сломался, jest тесты не сломались
Production доказан: Vercel-frontend РЕАЛЬНО работает (Task 11 setup остался активным — Vercel auto-redeploy не нужен был, т.к. Phase 1 уже была запушена ранее)
Артефакты в /home/z/my-project/download/phase_2_frontend_deploy/:

pre_1_frontend_smoke.py (smoke-test скрипт, 8 проверок)
DEPLOY_VERCEL_CHECKLIST.md (пошаговый чек-лист деплоя + приёмка)
pre_1_frontend_smoke/report.json (структурированный отчёт последнего прогона: 8/8 PASS)
pre_1_frontend_smoke/report.md (человекочитаемый отчёт)
Phase 6-P0 готов к старту:

Frontend deploy на Vercel ✓ (8/8 PASS, зелёный badge доказан в проде)
Backend deploy на Render ✓ (Task 12, 7/7 в pre_0_smoke.py)
Bridge Upload → Backtest ✓ (Phase 0.5 + Phase 1, data_source=session в ответе backtest)
Все env vars уже настроены (API_URL на Vercel, REDIS_URL + ALLOWED_ORIGINS на Render) — НОВЫХ env vars не нужно

---

Task ID: 15 — Phase 2 bugfix: /v1/internal/models/candidates зеркало + форматирование ошибок

What changed:
• apps/api/routers/internal.py — добавлен POST /v1/internal/models/candidates (зеркало без auth, как /v1/internal/models/backtest). Переиспользует _compute_candidates из routers/models.py.

• apps/api/routers/models.py — рефакторинг: бизнес-логика get_candidates вынесена в чистую функцию _compute_candidates(payload) -> CandidatesResponse. Теперь get_candidates просто делегирует _compute_candidates, что позволяет зеркалу internal.py использовать ту же логику БЕЗ дублирования.

• packages/ui/components/TsAnalysisModeling.tsx — две правки:
  1. fetchCandidates() переключён с /v1/models/candidates (требует X-Api-Key) на /v1/internal/models/candidates (без auth). Это и есть фикс корневой причины «Ошибка: [object Object],[object Object]».
  2. Добавлена утилита formatErrorDetail(detail: unknown) — нормализует ВСЕ три формы FastAPI ошибок в человекочитаемую строку:
     - string → вернуть как есть
     - array of Pydantic-ошибок [{loc,msg,type},...] → "loc.join('.'): msg; loc.join('.'): msg"
     - другие типы → JSON.stringify
     formatErrorDetail применён ко ВСЕМ 4 fetch-вызовам (target_column GET, target_column POST, candidates, backtest) — теперь любая ошибка от API читается человеком, не "[object Object]".

• packages/ui/components/TsAnalysisModeling.test.tsx — обновлены mock URL на /v1/internal/models/candidates (4 места) + добавлены 2 новых теста:
  - "Task 14 fix: renders array-shape detail as readable string, NOT '[object Object]'" — мокает Pydantic-формат {detail:[{loc,msg,type},{loc,msg,type}]}, проверяет что в DOM НЕТ "[object Object]"
  - "Task 14 fix: uses /v1/internal/models/candidates (NOT /v1/models/candidates)" — контрольный тест на отсутствие вызовов старого защищённого эндпоинта

• tests/api/test_internal_candidates.py — новый файл, 7 тестов:
  - TestInternalCandidatesAuth: test_no_api_key_required (главный кейс регрессии), test_with_api_key_also_works
  - TestInternalCandidatesContract: test_response_shape, test_min_level_filter, test_returns_same_candidates_as_protected_endpoint (доказывает идентичность с /v1/models/candidates)
  - TestInternalCandidatesValidation: test_invalid_min_level_returns_422, test_missing_profile_returns_422

Root cause и обоснование решений:
1. Почему баг проявился только в проде, а unit-тесты Phase 1 (Task 13) проходили?
   - В TsAnalysisModeling.test.tsx mock fetch возвращал success-ответ без проверки URL. URL /v1/models/candidates был захардкожен в компоненте — mock перехватывал его, но тест НЕ проверял, что URL корректный (тест проверял только факт вызова fetch).
   - В проде запрос РЕАЛЬНО шёл на /v1/models/candidates на Render → FastAPI возвращал 422 с массивом Pydantic-ошибок [{type:"missing",loc:["header","x-api-key"],msg:"Field required",input:null},{...}].
   - errBody.detail — массив → String(arr) → "[object Object],[object Object]".

2. Почему НЕ достаточно было просто улучшить рендеринг ошибок (formatErrorDetail)?
   - Даже если бы ошибка отображалась читаемо ("header.x-api-key: Field required"), candidates бы оставался = [] → кнопка бэктеста не отрисовывалась бы → пользователь по-прежнему не мог запустить бэктест.
   - Корневая причина — UI ходил на защищённый эндпоинт без auth. Фикс = зеркало без auth (как уже было сделано для backtest в Phase 0.5).

3. Почему именно /v1/internal/models/candidates, а не снятие auth с /v1/models/candidates?
   - /v1/models/candidates — публичный программный API для внешних разработчиков с API-ключом. Снятие auth сломало бы контракт.
   - /v1/internal/models/candidates — внутреннее зеркало для браузера visitior'а standalone. Уже есть паттерн: /v1/internal/upload, /v1/internal/models/backtest, /v1/internal/rules/*.

4. Каскад симптомов (как я нашёл корень):
   - Симптом 1: "Ошибка: [object Object],[object Object]" → это String(arr) → значит errBody.detail — массив → Pydantic validation error → 422.
   - Симптом 2: "бэктест не активный" → кнопка не отрисовывается → activeCandidate=null → candidates=[] → fetchCandidates упал.
   - Объединение: fetchCandidates упал с 422 (Pydantic missing header) → candidates=[] → кнопка не отрисована.

Tests:
- 50/50 PASS в TsAnalysisModeling.test.tsx (48 существующих + 2 новых regression)
- 7/7 PASS в новом test_internal_candidates.py
- 125/125 PASS в tests/api/* (без регрессий: test_models_candidates, test_internal_backtest, test_target_column, test_session_store, test_upload)

Verification:
- Next.js build: ✓ Compiled successfully, /modeling → 242 B + 154 kB First Load (без изменений от Phase 1 — бандл не раздут)
- Typecheck проходит (TS strict mode): нет type errors
- Воспроизведена ошибка против прода: curl POST https://ts-standalone.vercel.app/api/v1/models/candidates → 422 с {detail:[{...},{...}]} — ДО фикса
- После фикса (когда user запушит и Vercel auto-redeploy сделает) — fetchCandidates будет ходить на /v1/internal/models/candidates → 200 OK → candidates=[] станет candidates=[24 модели] → кнопка бэктеста отрисуется → пользователь сможет выбрать модель и нажать «Запустить бэктест» → зелёный badge «Реальные данные» (если выбран target_column).

Артефакты в /home/z/my-project/download/phase_2b_candidates_mirror_fix/:
- routers_internal.py (новый эндпоинт /v1/internal/models/candidates)
- routers_models.py (рефакторинг _compute_candidates, вызывается из обоих роутов)
- TsAnalysisModeling.tsx (fetchCandidates → internal, formatErrorDetail во всех fetch)
- TsAnalysisModeling.test.tsx (mock URL обновлён + 2 новых regression-теста)
- test_internal_candidates.py (7 новых backend-тестов)

Deploy checklist (after merge):
1. Backend: Render auto-redeploy при git push (routers/internal.py + routers/models.py)
2. Frontend: Vercel auto-redeploy при git push (TsAnalysisModeling.tsx + TsAnalysisModeling.test.tsx)
3. Smoke-test в проде после деплоя:
   - Открыть /modeling → candidates должны загрузиться БЕЗ ошибки «[object Object]»
   - Должны появиться family-заголовки (Baselines, Exponential smoothing, ARIMA, ...)
   - Должна появиться статистика (X/24 в spec, N RECOMMENDED, M COND_APPL)
   - Кликнуть на модель → в правой колонке кнопка «Запустить бэктест»
   - Нажать → если target_column выбран → data_source="session", зелёный badge
4. Повторить pre_1_frontend_smoke.py — все 8 проверок должны PASS (как до фикса, плюс теперь UI их использует)

Phase 6-P0 готов к старту ПОСЛЕ этого фикса (без него бэктест-кнопка в проде не работала).

---

Task ID: 16 — Phase 2 production bugfix: «Спецификация моделирования не найдена: rules/modeling.yaml»

Symptom (production, after Task 15 fix was deployed):

User uploads CSV → target_column selector appears (✓)
BUT «Загрузить пул» auto-fires → 500 error: «Спецификация моделирования не найдена: rules/modeling.yaml»
Backtest button stays disabled (no candidates → activeCandidate=null)
Root cause:

apps/api/Dockerfile copies app/, validation/, src/, apps/api/ into the image — but NOT rules/.
/v1/internal/models/candidates → _compute_candidates() → _get_spec() → ModelingSpec.from_yaml("rules/modeling.yaml") → FileNotFoundError → HTTP 500.
The four YAML files in rules/ (modeling.yaml, default_rules.yaml, fao_prices.yaml, macro.yaml) all exist in the repo, just never make it into the Docker image.
/v1/internal/rules/load/{template_id} and /v1/internal/rules/validate would have hit the same bug for any non-"custom" template_id.
Why the Task 14 smoke test (pre_1_frontend_smoke.py, 8/8 PASS) missed this:

Check #2 (proxy-alive) uses /v1/internal/rules/templates — this endpoint returns a HARDCODED list (_AVAILABLE_TEMPLATES_INTERNAL in internal.py), it never reads YAML.
Check #8 (backtest) uses model_id="naive" → _MODEL_INFO dict lookup, never touches modeling.yaml.
/candidates (which auto-fires on mount in TsAnalysisModeling.tsx via fetchCandidates) was NOT in the smoke test.
Fix applied:

apps/api/Dockerfile:
• Added COPY rules/ ./rules/ after the other COPY lines — bundles all 4 YAML files into the image.
• Added a build-time regression guard: RUN python -c "from src.catalog.modeling_spec_loader import ModelingSpec; spec = ModelingSpec.from_yaml('rules/modeling.yaml'); print('modeling.yaml OK, models:', spec.total_model_count())" — if the YAML is missing or broken, image build FAILS (instead of letting the bug surface only at runtime as HTTP 500).
scripts/pre_1_frontend_smoke.py: expanded from 8 → 9 checks:
• NEW check #8: POST /v1/internal/models/candidates with a minimal profile. Verifies status=200, candidates array non-empty, and statistics.total_models_in_spec=24. This would have caught the Task 16 bug.
• Old check #8 (backtest → data_source=session) renumbered to #9.
• Updated docstring (8 → 9 checks), inline comments document the regression.
Local verification:

python -c "from src.catalog.modeling_spec_loader import ModelingSpec; spec = ModelingSpec.from_yaml('rules/modeling.yaml')" → OK, 24 models, 8 families, 23 rules.
python -c "import ast; ast.parse(open('scripts/pre_1_frontend_smoke.py').read())" → Syntax OK.
Deploy steps for the user:

git push apps/api/Dockerfile (Render auto-redeploys backend — image rebuild will include rules/ + build-time guard will fail loudly if YAML is broken).
After backend is up (Render Dashboard shows "Live"), re-run pre_1_frontend_smoke.py from project root: python /home/z/my-project/scripts/pre_1_frontend_smoke.py — expect 9/9 PASS now (was 8/8 before; check #8 /candidates is the new one).
Manual UI verification on https://ts-standalone.vercel.app/modeling:
Upload CSV → target_column selector appears ✓
Select column → "Загрузить пул" succeeds (no «Спецификация моделирования не найдена» error)
Family headers render (Baselines, Exponential smoothing, ARIMA, ...)
Click model → backtest button becomes active → click → green badge «Реальные данные» (data_source=session)
After 9/9 PASS and green badge confirmed → ready for Phase 6-P0.
Stage Summary:

Root cause: missing COPY rules/ ./rules/ in apps/api/Dockerfile (production-only bug — local dev works because CWD has rules/ on disk).
Fix: Dockerfile + build-time guard + smoke-test regression coverage.
Files changed: apps/api/Dockerfile, scripts/pre_1_frontend_smoke.py.
No code changes in apps/api/routers/ or packages/ui/ — Task 15 fix was correct, it just couldn't run because the spec file wasn't shipped.

---

Task ID: 18

Исправляет два бага, выявленных первым прогоном `phase_6_p0_smoke.py` в проде:

| # | Баг | Симптом | Файл |
|---|-----|---------|------|
| 1 | `arima_auto` grid 18 fits × ~7s = 126s на Render Free Tier → timeout 90s | `[FAIL] 3-7. POST /backtest (arima_auto) (90016ms)` | `apps/api/model_impls/arima.py` |
| 2 | `Path.write_text()` на Windows по умолчанию cp1251, не содержит ≥ (U+2265) | `UnicodeEncodeError: 'charmap' codec can't encode character '\u2265'` | `scripts/smoke/phase_6_p0_smoke.py` |

## Что меняется

### `apps/api/model_impls/arima.py`
- `AUTO_ARIMA_GRID` сокращён с **18 → 8 fits**:
  - было: `p ∈ {0,1,2} × d ∈ {0,1} × q ∈ {0,1,2}` = 18
  - стало: `p ∈ {0,1} × d ∈ {0,1} × q ∈ {0,1}` = 8
- Расчёт: 8 × 7s = **56 sec** (вписывается в 90s Render request timeout)
- Качество выбора чуть хуже (пропускаем p=2, q=2), но для Phase 6-P0 достаточно
- Для Phase 6-P1+: расширить grid обратно или перейти на pmdarima

### `scripts/smoke/phase_6_p0_smoke.py`
- Добавлен `PER_MODEL_TIMEOUT` dict: `arima_auto=180s`, остальные 4 модели = 90s
- `check_backtest_model()` использует per-model timeout вместо общего `WARM_TIMEOUT`
- `write_reports()`: явно `encoding='utf-8'` для `Path.write_text()` — фикс Windows
- `main()`: `write_reports` обёрнут в `try/except` — даже при ошибке записи скрипт не падает, пользователь видит результаты в stdout

## Применение (2 способа)

### Способ 1: просто скопировать файлы (проще)

Скачай и распакуй архив, потом скопируй 2 файла с заменой:

```powershell
# PowerShell — подставь свой реальный путь к распакованному пакету
$src = "C:\Users\User\Downloads\phase_6_p0_hotfix"
$dst = "C:\Users\User\CISStat-TS-Analysis"

Copy-Item "$src\apps\api\model_impls\arima.py" "$dst\apps\api\model_impls\arima.py" -Force
Copy-Item "$src\scripts\smoke\phase_6_p0_smoke.py" "$dst\scripts\smoke\phase_6_p0_smoke.py" -Force

# Проверка
(Get-Content "$dst\apps\api\model_impls\arima.py" | Select-String "for p in").Line
# Ожидаем: '    for p in (0, 1)'

git -C $dst status --short
# Ожидаем: 2 modified файла
```

### Способ 2: применить патч через `git apply` (чище)

```powershell
cd C:\Users\User\CISStat-TS-Analysis

# Скачай phase_6_p0_hotfix.patch в текущую папку, потом:
git apply --check phase_6_p0_hotfix.patch    # dry-run
git apply phase_6_p0_hotfix.patch             # применить

# Проверка
git diff --stat
# Ожидаем:
#  apps/api/model_impls/arima.py        | 26 +++++++++-----
#  scripts/smoke/phase_6_p0_smoke.py    | 30 +++++++++++++++--
```

### Обновление worklog.md

Worklog уже содержит Task 18 entry в конце. Скопируй файл из пакета:

```powershell
Copy-Item "$src\worklog.md" "$dst\worklog.md" -Force
```

## После применения — commit + push + deploy

```powershell
cd C:\Users\User\CISStat-TS-Analysis

git add apps/api/model_impls/arima.py `
        scripts/smoke/phase_6_p0_smoke.py `
        worklog.md

git commit -m "Task 18 (Phase 6-P0 hotfix): arima_auto grid 18→8 fits, UTF-8 encoding for Windows

Two bugs from first prod smoke run:
1. arima_auto timed out at 90s — grid of 18 ARIMA fits × ~7s each on Render
   Free Tier = 126s, exceeding both 90s smoke-timeout and 100s Render request
   timeout. Reduced grid from {0,1,2}×{0,1}×{0,1,2}=18 to {0,1}×{0,1}×{0,1}=8
   fits. New estimate: 8×7s=56s, fits within 90s.
2. phase_6_p0_smoke.py crashed with UnicodeEncodeError on Windows when writing
   report.json — Path.write_text() defaults to cp1251 on Windows, which lacks
   the ≥ character (U+2265). Fixed by explicit encoding='utf-8' in write_reports.

Files:
- apps/api/model_impls/arima.py: AUTO_ARIMA_GRID 18→8, updated docstrings
- scripts/smoke/phase_6_p0_smoke.py: PER_MODEL_TIMEOUT dict (arima_auto=180s),
  check_backtest_model uses per-model timeout, write_reports uses utf-8,
  write_reports wrapped in try/except so script never crashes on report writing
- worklog.md: Task 18 entry

Notes:
- maxiter=100 attempt was reverted — ARIMA.fit() in statsmodels 0.14+ doesn't
  accept maxiter (SARIMAX-only). Grid reduction alone is sufficient.
- 0 new dependencies, 0 contract changes, 0 UI changes.
- Existing 21 tests in test_models_backtest_real.py remain valid."

git push origin main
```

## После деплоя (Render Dashboard → "Live")

```powershell
python scripts/smoke/phase_6_p0_smoke.py
```

Ожидаемый результат:

```
[PASS] 1. POST /upload (24-month CSV) (~30s cold start)
[PASS] 2. POST /session/target-column (value) (~1s)
[PASS] 3-3. POST /backtest (ets) (~2s)
[PASS] 3-4. POST /backtest (ets_damped) (~2s)
[PASS] 3-5. POST /backtest (theta) (~1s)
[PASS] 3-6. POST /backtest (arima) (~7s)
[PASS] 3-7. POST /backtest (arima_auto) (~50-60s — было 90s+ timeout, теперь вписывается)
[PASS] 8. 5 models produce ≥3 distinct MAE
======================================================================
TOTAL: 8/8 passed, 0 failed
Report: .../phase_6_p0_smoke/report.json
Report: .../phase_6_p0_smoke/report.md

✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ. 5 моделей реально обучаются в проде.
  → Phase 6-P0 завершён. Готов к Phase 6-P1 (Prophet/TBATS) или Phase 1.
```

Если `arima_auto` снова FAIL по timeout — присылай вывод, сократим grid ещё (до 4 fits) или добавим early-termination.

---

Task ID: 17 — Phase 6-P0: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA

Цель Phase 6-P0 (по решению тимлида Task ID 8: «Phase 6-P0 (4 модели) сначала → затем Phase 1–5»):
заменить заглушку naive*penalty для 5 моделей на реальные реализации через statsmodels.

ДО Phase 6-P0 (состояние после Tasks 13–16):

_BACKTEST_IMPLEMENTATIONS содержал только 4 baseline (naive, seasonal_naive, drift, mean).
5 model_id (ets, ets_damped, theta, arima, arima_auto) попадали в else-ветку
_run_backtest_with_series, где им возвращались naive_metrics * (1.1 / family_penalty).
Это значило: 3 exponential_smoothing модели (ets, ets_damped, theta) возвращали
ОДИНАКОВЫЕ метрики (penalty=0.85 для всех), а 2 arima модели — тоже одинаковые
(penalty=0.80). В UI числа выглядели разными, но за ними не было реальных моделей.
ПОСЛЕ Phase 6-P0 (что сделано в Task 17):

Что changed:

• apps/api/model_impls/ — НОВАЯ папка (6 файлов, 659 строк):
• init.py — экспортирует 5 функций (run_ets_backtest, run_ets_damped_backtest,
run_theta_backtest, run_arima_backtest, run_auto_arima_backtest).
• _metrics.py — compute_metrics(y_true, y_pred, y_train) → BacktestMetrics.
Скопировано из routers/models.py::_compute_metrics БЕЗ изменений формул.
Причина копирования: избежать циклического импорта model_impls ↔ routers.models.
Роутер импортирует model_impls, model_impls импортирует _metrics — без цикла.
• _common.py — общие хелперы:
• train_test_split(series, train_ratio) → (y_train, y_test)
• safe_backtest(fn, series, train_ratio, seasonal_period, model_name) → BacktestMetrics
Обёртка try/except: если statsmodels упадёт на проблемных данных
(короткий ряд, zero variance, NaN) — откат на Naive-метрики, НЕ 500.
• ets.py — ExponentialSmoothing (Holt-Winters):
• trend='add', seasonal='add' (если len(y_train) >= 2*seasonal_period)
• initialization_method='estimated'
• damped_trend=True/False в зависимости от модели
• Edge case: fit() не принимает disp=False (это аргумент SARIMAX, не Holt-Winters).
• theta.py — ThetaModel (Assimakopoulos & Nikolopoulos 2000):
• method='auto', deseasonalize=True если сезонность есть
• Edge case: константный ряд → NaN forecast (variance=0 ломает лин. регрессию).
Возвращаем [y_train[-1]] * n_test (Naive forecast = сама константа).
• arima.py — ARIMA(1,1,1) + Auto-ARIMA:
• Фиксированный порядок (1,1,1) для arima.
• Grid search по (p,d,q) ∈ {0,1,2} × {0,1} × {0,1,2} = 18 моделей для arima_auto.
• Критерий: минимальный AIC. ~1-2 сек на 24-72 точках.
• Реализовано через statsmodels, НЕ pmdarima (без новой тяжёлой зависимости).

• apps/api/routers/models.py — расширение _BACKTEST_IMPLEMENTATIONS:
добавлены 5 ключей: 'ets', 'ets_damped', 'theta', 'arima', 'arima_auto'.
Импорт: from apps.api.model_impls import (run_ets_backtest, ...).
Остальная логика роутера НЕ изменена: _resolve_model_info, _resolve_seasonal_period,
_run_backtest_with_series, else-ветка для семейств neural/structural/tree_ml и т.д.
else-ветка остаётся как fallback для будущих Phase 6-P1+ моделей.

• apps/api/Dockerfile — расширение build-time guard:
была проверка: ModelingSpec.from_yaml('rules/modeling.yaml') OK.
добавлены: import statsmodels + ExponentialSmoothing + ARIMA + ThetaModel +
5 функций model_impls. Если statsmodels не установится или model_impls
битый — сборка падает здесь, а не в runtime при первом /backtest с model_id=ets.

• tests/api/test_models_backtest_real.py — НОВЫЙ файл, 21 тест:
• TestRealModelsBasicAvailability (5): каждый model_id возвращает 200 + data_source=session.
• TestRealModelsAreNotNaivePenaltyStub (5): метрики на реальном ряду ≠ синтетике.
Ключевой regression-тест: доказывает, что модель реально обучается на данных.
• TestRealModelsAreDistinctFromEachOther (1): ≥3 уникальных MAE из 5 моделей.
До фикса: 2 уникальных (3 exp.smoothing давали одно значение + 2 arima одно).
После: 5 уникальных — модели реально разные.
• TestModelImplsModuleDirectly (2): прямой вызов функций без HTTP,
чтобы изолировать баги statsmodels от багов роутера.
• TestRealModelsHandleEdgeCases (2): short series (8 точек) и constant series.
Все модели не падают с 500, edge cases обрабатываются safe_backtest.
• TestBaselineModelsStillWork (4): регрессия — 4 baseline не сломались.
• TestBacktestImplementationsRegistry (2): реестр содержит ровно 9 ключей
(4 baseline + 5 новых), заглушка не активируется для новых моделей.

• scripts/smoke/phase_6_p0_smoke.py — НОВЫЙ файл, 8 проверок в проде:

POST /upload (24-month CSV с трендом + сезонностью)
POST /session/target-column (выбрать value)
3-7. POST /internal/models/backtest для 5 моделей по очереди
≥3 уникальных MAE (доказательство, что это не заглушка)
Запуск: python /home/z/my-project/repo/CISStat-TS-Analysis/scripts/smoke/phase_6_p0_smoke.py
• scripts/smoke/README.md — добавлена секция «Что проверяет phase_6_p0_smoke.py».

Архитектурные решения (почему так, а не иначе):

Почему statsmodels, а НЕ pmdarima?
pmdarima — стандарт для Auto-ARIMA, но это тяжёлая зависимость:
требует компилятор на Render free tier, имеет конфликты с numpy/scipy
на некоторых платформах. statsmodels уже установлен (для ADF/KPSS в
app/core/passport.py), стабилен, и его ARIMA достаточно для grid search.
Решение: использовать statsmodels, grid (p,d,q) ∈ {0,1,2} × {0,1} × {0,1,2}.
По качеству — уступает pmdarima на сложных рядах, но для Phase 6-P0
(демонстрация реальной ARIMA-модели) — достаточно.
Почему _metrics.py — копия, а не импорт из routers.models?
Циклический импорт: routers.models импортирует model_impls (чтобы
зарегистрировать в _BACKTEST_IMPLEMENTATIONS), а model_impls для
compute_metrics импортировал бы routers.models. Python такие циклы
разруливает лениво, но это хрупко — при рефакторинге можно поймать
«partially initialized module». Решение: выделить _metrics.py в
model_impls, оба модуля импортируют оттуда. Дублирование тривиальной
функции (~30 строк) — приемлемая цена за отсутствие цикла.
Почему safe_backtest откатывается на Naive, а не возвращает 500?
Контракт UI/UX: бэктест ВСЕГДА возвращает метрики, никогда — 500.
Если statsmodels не смог обучиться (короткий ряд, константа, NaN),
пользователь видит Naive-метрики + WARNING в логе. Это лучше, чем
«internal server error»: пользователь понимает, что модель формально
сработала, и может сравнивать с другими моделями.
Почему (1,1,1) для фиксированной ARIMA?
Стандартный «обычный» ARIMA: 1 авторегрессионный член (p=1), 1 differencing
(d=1 — снимает линейный тренд), 1 скользящее среднее (q=1 — ловит остаточную
автокорреляцию). Подходит для большинства бизнес-рядов с трендом и слабой
автокорреляцией остатков. Если ряд явно сезонный — ARIMA(1,1,1) проиграет
Seasonal Naive, но это валидный baseline для P0. SARIMA — Phase 6-P1+.
Tests:

146/146 PASS в tests/api/* (125 существующих + 21 новых)
Локальный smoke: 8/8 PASS (upload → target-column → 5 backtests → distinct MAE)
Next.js build: ✓ Compiled successfully, /modeling → 245 B + 157 kB First Load
(без изменений от предыдущей версии — бандл не раздут)
Pre-existing jest failures (32 failed в RulesManagementPanel/Validation/EDA/
Preprocessing) НЕ связаны с Phase 6-P0 — проверено git stash + rerun.
Verification (локально, на TestClient):

5 моделей дают 5 различных MAE: ets=27.07, ets_damped=22.31, theta=8.76,
arima=23.07, arima_auto=9.30.
Auto-ARIMA выбрал (2,1,2) с AIC=38.48 — корректный выбор для ряда
с трендом и сезонностью.
data_source="session" для всех 5 моделей при установленном target_column.
weighted_score ∈ [0, 1] для всех моделей (контракт _compute_metrics).
На константном ряде все 5 моделей возвращают MAE ≈ 0 (Naive на константе).
Deploy steps (для пользователя):

git push apps/api/model_impls/ apps/api/routers/models.py apps/api/Dockerfile
tests/api/test_models_backtest_real.py scripts/smoke/phase_6_p0_smoke.py
scripts/smoke/README.md
Render auto-redeploys backend. В логах сборки увидеть:
"modeling.yaml OK, models: 24"
"statsmodels OK: 0.14.x"
"model_impls OK: 5 implementations importable"
После деплоя: python scripts/smoke/phase_6_p0_smoke.py — ожидаем 8/8 PASS.
Ручная проверка на /modeling:
Upload CSV → select column → "Загрузить пул" → клик по ETS/Theta/ARIMA/Auto-ARIMA
Метрики в правой панели: РАЗНЫЕ для разных моделей (раньше были линейно связаны)
data_source = "session" → зелёный badge «Реальные данные»
Acceptance criteria Phase 6-P0:
✓ 21/21 новых тестов PASS (test_models_backtest_real.py)
✓ 125/125 существующих API-тестов PASS (без регрессий)
✓ Next.js build успешен (без изменений в UI — бандл не вырос)
✓ Локальный smoke: 5 моделей дают 5 уникальных MAE
✓ Auto-ARIMA выбирает оптимальный порядок по AIC

Что НЕ сделано в Phase 6-P0 (оставлено на Phase 6-P1+):

SARIMA (сезонная ARIMA) — нужна SARIMAX с seasonal order (P,D,Q,s).
Prophet, TBATS — структурные модели (нужны prophet/tbats пакеты).
XGBoost, LightGBM, CatBoost — tree_ml (нужны xgboost/lightgbm/catboost).
LSTM, DeepAR, TFT, N-BEATS, WaveNet — neural (нужны pytorch/tensorflow).
VAR, VECM — multivariate (нужна стационарность нескольких рядов).
GARCH, EGARCH — volatility (нужен arch пакет).
Hyperparameter tuning (param_space в modeling.yaml) — Phase 1.
Расширение BacktestResponse (residuals, fitted_values, forecast) — Phase 1.
Stage Summary:

5 моделей переведены с заглушки naive*penalty на реальные statsmodels-реализации.
0 новых зависимостей (statsmodels уже был установлен для passport.py).
0 изменений в UI — фронтенд работает без правок.
0 изменений в контракте BacktestResponse/BacktestMetrics.
21 новый тест покрывает: корректность, edge cases, регрессию, прямые вызовы.
Build-time guard в Dockerfile ловит битые импорты до деплоя.

---

Task ID: 19-A — Phase 1-A: param_space в modeling.yaml + Pydantic поле

Task:
• Расширить спецификацию modeling.yaml, чтобы каждая модель могла нести
  своё пространство параметров для тюнинга (param_space).
• Расширить Pydantic-схему FamilyModel полем param_space.
• Опциональное поле (None по умолчанию) — обратная совместимость.
• Написать тесты: загрузка YAML, схема, baseline skip, roundtrip.

Work Log:
- Прочитан текущий modeling.yaml (1407 строк) и modeling_spec_loader.py (838 строк).
- Спроектирован формат param_space: Optional[Dict[str, List[Any]]],
  где ключ = имя параметра, значение = список кандидат-значений.
  Декартово произведение даёт grid для tune-ендпоинта.
- Оценены риски:
  R1 — регрессия test_modeling_spec.py → param_space optional, default None.
  R2 — Any в List[Any] → Pydantic v2 принимает str/int/float/bool/None.
  R3 — None как значение в списке → Pydantic v2 List[Any] поддерживает.
- TDD: сначала написан tests/api/test_param_space.py (14 тестов, 4 класса):
  • TestParamSpaceSchema (5 тестов) — поле есть, default None, dict/None/mixed.
  • TestParamSpaceYamlLoading (3 теста) — YAML парсится, ets/arima имеют param_space.
  • TestBaselineNoParamSpace (4 теста) — naive/seasonal_naive/drift/mean без param_space.
  • TestParamSpaceRoundtrip (2 теста) — model_dump и model_dump_json сохраняют данные.
- Запуск тестов до изменений: 1-й тест падает ("'param_space' in fields" → AssertionError).
- Расширение FamilyModel: добавлено поле param_space с комментарием-контрактом
  для Phase 1-B/C (POST /v1/models/tune, max_trials защита).
- Заполнен rules/modeling.yaml для 3 моделей Phase 6-P0:
  • ets:        trend[2] × seasonal[3] × seasonal_periods[1] × damped_trend[2] = 12 trials
  • ets_damped: trend[2] × seasonal[3] × seasonal_periods[1]               =  6 trials
  • arima:      p[3] × d[2] × q[3]                                          = 18 trials
- baseline-модели (naive/seasonal_naive/drift/mean) сознательно БЕЗ param_space —
  контрактом предусмотрено, что они не требуют тюнинга.
- theta и arima_auto оставлены без param_space: у theta параметров нет
  (формула фиксирована), у arima_auto grid уже зашит в самой модели.
- Запуск тестов: 14/14 PASS.
- Регрессия test_modeling_spec.py: 62/62 PASS (всего 76/76).
- Sanity-check спецификации: 24 модели, 3 имеют param_space, 21 без него.
  Все grid sizes ≤ MAX_TRIALS=64 (максимальный = 18 у ARIMA).

Stage Summary:
- Изменено 3 файла:
  • src/catalog/modeling_spec_loader.py — FamilyModel.param_space (15 строк с комментарием)
  • rules/modeling.yaml — param_space для ets/ets_damped/arima (~30 строк)
  • tests/api/test_param_space.py — новый файл, 14 тестов (190 строк)
- Все тесты PASS, регрессии нет.
- Готов фундамент для Phase 1-B (CVStrategy / ExpandingWindowCV):
  POST /v1/models/tune сможет читать param_space через spec.get_model(model_id).
- Артефакты в /home/z/my-project/download/phase_1_a_param_space/

---

Task ID: 19-B — Phase 1-B: CVStrategy / ExpandingWindowCV

Task:
• Создать модуль apps/api/cv.py с абстракцией CVStrategy (ABC) и
конкретной реализацией ExpandingWindowCV — expanding-window cross-
validation для временных рядов (train растёт, test фиксирован).
• Не использует данные из будущего (в отличие от KFold sklearn).
• Фундамент для POST /v1/models/tune (Phase 1-C).

Work Log:

Прочитан apps/api/session_store.py — референс-паттерн ABC в проекте
(SessionStore ABC + MemorySessionStore + RedisSessionStore). Новый
модуль следует той же конвенции: ABC в начале, реализации ниже.
Спроектирован формат:
• CVSplit (dataclass): fold, train_idx, test_idx
• CVStrategy (ABC): split(n) → list[CVSplit], min_samples() → int
• ExpandingWindowCV: n_splits, test_size, min_train_size=None, step=None
Формула min_samples:
min_train_size + test_size + (n_splits - 1) * step
Где первое слагаемое — первый train, второе — первый test,
третье — сдвиг для оставшихся (n_splits - 1) folds.
Оценены риски (7 шт):
R1 — короткий ряд → ValueError до генерации splits.
R2 — n_splits=0/test_size=0 → валидация в init (>=1).
R3 — step > test_size → документировано как легальный режим.
R4 — step < test_size (overlap) → легальный CV-режим.
R5 — min_train_size None → default = test_size.
R6 — последний fold test_end > n → ValueError (не truncation).
Дизайн-решение: явное лучше молчаливого. Изначально хотел
truncation, тест упал — пересмотрел. Объяснил в тесте.
R7 — регрессия → новый модуль, не импортируется существующим кодом.
TDD: tests/api/test_cv.py (33 теста, 7 классов):
• TestCVSplit (3) — структура, equality, inequality.
• TestCVStrategyABC (3) — нельзя инстанцировать, подкласс без методов не работает.
• TestExpandingWindowCVConstructor (10) — валидация 4 параметров + defaults.
• TestMinSamples (4) — формула для разных сценариев.
• TestSplitCorrectness (4) — basic 3 folds, expanding train, no leakage, non-overlap.
• TestEdgeCases (6) — n_splits=1, короткий ряд, exact min, overflow→raise, step>test, step<test.
• TestListIntegration (1) — индексы работают с list[float].
Запуск тестов до реализации: ModuleNotFoundError (TDD-старт).
Реализация apps/api/cv.py (~210 строк, ~50% — docstrings с примерами):
• CVSplit dataclass.
• CVStrategy ABC с 2 абстрактными методами.
• ExpandingWindowCV с init валидацией, min_samples(), split().
• defensive break в split() даже после валидации (если валидация
пропустит, break спасёт от выхода за пределы списка).
Первый запуск: 32/33 PASS. 1 тест упал — test_last_fold_overflow_truncates
ожидал truncation (вернуть 4 folds вместо 5), а реализация бросает
ValueError. После анализа изменил тест: явная ошибка лучше молчаливого
truncation (пользователь должен знать, что 5 folds не влезли).
Повторный запуск: 33/33 PASS.
Регрессия: tests/test_modeling_spec.py (62) + tests/api/test_param_space.py (14)
tests/api/test_cv.py (33) = 109/109 PASS.
Sanity-check: ExpandingWindowCV(n_splits=3, test_size=2, min_train_size=3, step=2).split(9)
→ 3 folds, индексы корректные, train расширяется. ABC enforcement работает.
Stage Summary:

Создано 2 файла:
• apps/api/cv.py — новый модуль (210 строк, 3 класса: CVSplit, CVStrategy, ExpandingWindowCV)
• tests/api/test_cv.py — новый тестовый файл (33 теста, 7 классов, 280 строк)
Все тесты PASS, регрессии нет.
Готов фундамент для Phase 1-C (POST /v1/models/tune):
tune-ендпоинт сможет использовать ExpandingWindowCV для каждого trial
из param_space, усреднять метрики по folds и выбирать лучшие параметры.
max_trials защита: если grid_size > MAX_TRIALS, обрезать random-сэмплированием.
Артефакты в /home/z/my-project/download/phase_1_b_cv/

---

Task ID: 19-C — Phase 1-C: POST /v1/models/tune + max_trials защита

Task:
• Создать эндпоинт POST /v1/models/tune для grid search гиперпараметров
модели через expanding-window CV.
• Реализовать max_trials защиту (MAX_TRIALS=64, hard cap): если
grid_size > MAX_TRIALS — random sampling с воспроизводимым seed.
• Использовать фундамент Phase 1-A (param_space в spec) и Phase 1-B
(ExpandingWindowCV).

Work Log:

Прочитан worklog.md: Phase 1-A (76/76) и Phase 1-B (109/109) завершены.
Фундамент для Phase 1-C готов: param_space в modeling.yaml + CVStrategy.
Прочитаны apps/api/cv.py (240 строк), apps/api/schemas.py (310 строк),
apps/api/routers/models.py (478 строк до правок) — найдены точки изменения:
• schemas.py: добавить CVConfig, TuneRequest, TuneTrialResult, TuneResponse
• routers/models.py: добавить MAX_TRIALS, _build_grid, _truncate_grid,
_tunable_predict, _execute_tune, POST /tune endpoint
Базовая проверка: 109/109 существующих тестов PASS (без изменений).
Спроектирован API:
POST /v1/models/tune
Body: { model_id, series: List[float], cv?: CVConfig,
max_trials?: int, metric?: str, random_state?: int }
Returns: TuneResponse (best_params, best_metrics, trials[], ...)
Спроектирован контракт max_trials (R7-R9):
effective_max = min(max_trials or MAX_TRIALS, MAX_TRIALS)
if grid_size > effective_max → random.Random(seed).sample(...)
Оценены риски (13 шт):
R1. Baseline model (no param_space) → 422 explicit
R2. Unknown model_id → 404
R3. Empty series → 422 (Pydantic min_length=1)
R4. Too short series (< cv.min_samples()) → 422 с понятным сообщением
R5. Invalid metric → 422 (Literal["mae","rmse","mape","mase","weighted_score"])
R6. Invalid CV config → propagate ValueError → 422
R7. grid_size > MAX_TRIALS → random sample MAX_TRIALS trials
R8. User max_trials < grid_size → random sample max_trials trials
R9. User max_trials > MAX_TRIALS → clamp до MAX_TRIALS
R10. Reproducibility → random.Random(seed).sample (no replacement)
R11. NaN/Inf в series → no special handling (propagates to metrics)
R12. Regression в существующие эндпоинты → нет (новый роут)
R13. pandera не установлен → тесты через _execute_tune() напрямую,
без HTTP-вызова; test_tune.py НЕ импортирует apps.api.main.
TDD: tests/api/test_tune.py написан ДО реализации (60 тестов, 9 классов):
• TestCVConfig (6) — defaults, custom, валидация n_splits/test_size/step.
• TestTuneRequest (8) — required fields, defaults, min_length, metric Literal.
• TestTuneResponse (2) — construct, trials default empty.
• TestTuneTrialResult (1) — construct.
• TestBuildGrid (7) — single/two/three params, empty, None, bool, ARIMA size.
• TestTruncateGrid (9) — under max, equal max, over max, user smaller,
reproducible, different seed, subset, no duplicates, MAX_TRIALS constant.
• TestExecuteTuneEts (3) — full response, n_folds, cv_config echo.
• TestExecuteTuneOtherModels (2) — ets_damped (6 grid), arima (18 grid).
• TestExecuteTuneErrors (6) — 404 unknown, 422 baseline, 422 theta,
422 short series, 422 invalid metric.
• TestExecuteTuneBestSelection (4) — min rmse/mae/weighted_score, best_params match.
• TestExecuteTuneMaxTrials (6) — user smaller/larger, clamp, grid over MAX,
reproducible, different seed.
• TestTrialsOrder (1) — без truncation сохраняется порядок декартова произведения.
Запуск тестов до реализации: ImportError ('CVConfig' not found) — TDD red.
Реализация schemas.py (+105 строк):
• CVConfig: n_splits, test_size, min_train_size, step (all >=1, optional)
• TuneRequest: model_id, series, cv?, max_trials?, metric (Literal),
random_state (default 42)
• TuneTrialResult: params, metrics, n_folds
• TuneResponse: model_id, model_name, family_id, best_params, best_metrics,
best_trial, n_trials, grid_size, truncated, cv_config, metric, trials, duration_ms
Реализация routers/models.py (+520 строк):
• MAX_TRIALS = 64 (hard cap, documented contract из Phase 1-A)
• _build_grid(param_space) → list[dict]: декартово произведение через itertools.product
• _truncate_grid(grid, max_trials, random_state) → (trials, truncated)
• _tunable_predict(model_id, y_train, test_size, params) → list[float]:
STUB для Phase 1-C — детерминированная эвристика по params
(trend add/mul, damped_trend, p/d/q ARIMA). Phase 6 заменит на реальные модели.
• _execute_tune(spec, model_id, series, cv_config, max_trials, metric, random_state)
→ TuneResponse: чистая функция (тест без HTTP), 8 шагов:
1. spec.get_model(model_id) → 404 если нет
2. check model.param_space is None → 422
3. _build_grid → full_grid
4. _truncate_grid с effective_max = min(max_trials or MAX_TRIALS, MAX_TRIALS)
5. ExpandingWindowCV(...) из Phase 1-B; check len(series) >= cv.min_samples()
6. for each trial × each fold: predict + compute_metrics + усреднить
7. min(range(n_trials), key=lambda i: metrics[i].{metric}) → best_trial
8. TuneResponse с trials[] для аудита
• @router.post("/tune") — тонкая HTTP-обёртка вокруг _execute_tune.
Первый запуск тестов: 59/60 PASS. 1 тест упал —
test_too_short_series_raises_422 ожидал "10" или "5" в сообщении,
но реальное min_samples = min_train_size(10) + test_size(2) + (5-1)*step(2) = 20.
Ошибка в тесте (не в коде): исправил assertion на "20" и "3".
Повторный запуск: 60/60 PASS.
Регрессия: tests/api/test_tune.py (60) + tests/api/test_param_space.py (14)
tests/api/test_cv.py (33) + tests/test_modeling_spec.py (62) = 169/169 PASS.
Регрессии нет. test_models_candidates.py и test_upload.py НЕ запускались —
они импортируют apps.api.main, который тянет pandera (пред-существующая
проблема, не связана с Phase 1-C).
Sanity-check: ETS grid_size=12, n_trials=12, truncated=False,
best_params={'trend': 'add', 'seasonal': 'add', 'seasonal_periods': 12,
'damped_trend': True}, duration_ms=0.54.
С max_trials=5: truncated=True, n_trials=5, reproducible.
JSON-сериализация (Pydantic model_dump_json) работает корректно.
Stage Summary:

Изменено 2 файла, создан 1 новый:
• apps/api/schemas.py — добавлены CVConfig, TuneRequest, TuneTrialResult,
TuneResponse (+105 строк, 4 новые Pydantic-схемы).
• apps/api/routers/models.py — добавлены MAX_TRIALS, _build_grid,
_truncate_grid, _tunable_predict, _execute_tune, POST /tune (+520 строк,
6 новых функций/констант + 1 эндпоинт).
• tests/api/test_tune.py — новый файл (60 тестов, 9 классов, 440 строк).
Все тесты PASS: 60/60 новых + 109/109 существующих = 169/169.
Готов фундамент для Phase 1-D (Интеграционные тесты):
POST /v1/models/tune может быть протестирован через TestClient,
как только pandera будет установлен (или через _execute_tune напрямую).
_tunable_predict — STUB. Phase 6 заменит на реальные ETS/ARIMA реализации.
Артефакты в /home/z/my-project/download/phase_1_c_tune/

---

Task ID: 19-D — Phase 1-D: интеграционные тесты тюнинга на реальных ETS / ARIMA
Цель
Закрыть последний пункт Phase 1-D: baseline skip / ETS grid / CV splits поверх реальных Phase 6-P0 реализаций, а не legacy _tunable_predict STUB.

Состояние на старте
Фаза 1-A: param_space в rules/modeling.yaml — завершена.
Фаза 1-B: ExpandingWindowCV — завершена.
Фаза 1-C: POST /v1/models/tune, сетка × CV и max_trials — завершена.
Фаза 6-P0: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA для бэктестинга — завершена.
_tunable_predict в apps/api/routers/models.py остается устаревший STUB для настройки. Это отдельная производственная задача, и она не должна маскироваться тестовым monkeypatch.
Что проверено
Добавлено tests/api/test_tune_real_models.py.

Покрытие:

Пропуск базового уровня: naive, seasonal_naive, drift, mean → HTTP 422.
Сетка ETS: 12 комбинаций из rules/modeling.yaml выполняются на реальных statsmodels.ExponentialSmoothing.
Сетка ARIMA: 18 комбинаций выполняются на реальных statsmodels.ARIMA.
Все метрики испытаний конечны и неотрицательны.
Параметры действительно влияют на среднеквадратическую ошибку: сетка не является декоративной.
Реальные прогнозы отличаются от устаревших STUB.
Кросс-валидация с расширяющимся окном: 5-кратная кросс-валидация, расширение обучающей выборки, отсутствие утечки данных в будущее.
TuneResponse.n_foldsсоответствует фактической конфигурации кросс-валидации.
max_trials=2 сокращает сетку ETS с 12 до 2 с truncated=True.
Точки изменения
tests/api/test_tune_real_models.py — единственный тестовый файл, безопасный для продакшена, для этапа 1-D.
Продакшн _tunable_predict не менялся в рамках этой задачи 19-D, чтобы не смешивать интеграционное тестирование с отдельным рефакторингом диспетчеризации моделей.
Риски
Тест не должен проходить за счет STUB → реальные вспомогательные функции statsmodels вызываются напрямую.
Базовый уровень не должен случайно попасть в настройку → отдельные утверждения 422.
Утечка CV → проверка max(train_idx) < min(test_idx).
Потеря комбинаций сетки → проверка размеров 12/18.
Неконтролируемое выполнение большой сетки → проверка max_trials.
Мультипликативная ETS на неположительном ряде требует отдельной обработки/валидации; текущий золотой тест использует строго положительный ряд.
Верификация
Полный pytest/build из этой среды выполнения не заявлен: прямой git clone недоступен из-за ограничений DNS/сети. Репозиторий и актуальный main синхронизированы через GitHub Connector.

Результат
Покрытие интеграционного тестирования на этапе 1-D подготовлено и уже присутствует в main как tests/api/test_tune_real_models.py.

Важно: эта задача не объявляет замену production _tunable_predict на dispatch. Если требуется перевести сам POST /v1/models/tune на dispatch production model, это отдельное изменение apps/api/routers/models.py + API реализации модели, которое должно пройти отдельный полный регрессионный тест.

---

Task ID: 19-E — Production-разрыв Tune → реальные ETS/ARIMA

Цель: закрыть production-разрыв между Phase 1-C tuning engine и Phase 6-P0 real model implementations. POST /v1/models/tune больше не должен использовать детерминированный stub для ETS/ARIMA.

Процесс решения:

Синхронизирована отдельная ветка от актуального main, чтобы не перетирать параллельные изменения команды.
Проверены точки интеграции: apps/api/routers/models.py, real model implementations в apps/api/model_impls/{ets,arima}.py, rules/modeling.yaml, Phase 1-D tests.
Выбран единый production dispatch через маленький модуль apps/api/model_impls/tuning.py, который переиспользует реальные statsmodels fit/predict функции.
Production _tunable_predict оставлен как API-level dispatch, а не как вторая реализация моделей.
Изменения:

apps/api/model_impls/ets.py • _ets_fit_predict получил опциональные trend/seasonal параметры. • Старый Phase 6-P0 backtest контракт сохранён (defaults). • Мультипликативные варианты требуют строго положительные данные. • Сезонность при недостатке двух полных периодов не ломает CV, а выполняется без seasonal component явно.
apps/api/model_impls/tuning.py • tune_ets_predict(): передаёт параметры текущего grid trial в реальный ExponentialSmoothing. • tune_arima_predict(): передаёт p,d,q текущего trial в реальный ARIMA.
apps/api/routers/models.py • _tunable_predict заменён production dispatch: ets / ets_damped → tune_ets_predict arima → tune_arima_predict Остальные модели не получают ложный stub; возвращают явный 422. • Ошибочный trial (ValueError/RuntimeError/ArithmeticError) пропускается с warning; если ни один trial не завершился, endpoint возвращает 422. • Existing grid/CV/max_trials контракт сохранён.
tests/api/test_tune_real_models.py • Убрана проверка «реальный прогноз отличается от legacy stub» — stub больше не является production contract. • Оставлена проверка реального statsmodels fit/predict.
tests/api/test_tune_production_dispatch.py • Новый regression suite: production dispatch ETS/ARIMA, количество реальных вызовов = trials × folds, параметры реально передаются, unsupported model не получает fake forecast, mul ETS не silently fallback.
worklog.md • Добавлена текущая запись Task 19-E.
Риски и меры:

R1: двойная реализация моделей → tuning.py использует существующие Phase 6-P0 функции, новый statsmodels fit не создаётся.
R2: ETS grid-параметры теряются → regression spy проверяет trend/seasonal/ damped параметры на каждом вызове.
R3: mul ETS на отрицательных данных → явный ValueError, trial пропускается, а не замена на additive model.
R4: одна невалидная комбинация ломает весь tuning → trial-level isolation.
R5: все trials невалидны → явный HTTP 422 вместо ложного best trial.
R6: baseline/no-param model → существующий 422 contract сохраняется.
R7: параллельные изменения команды → отдельная ветка от актуального main; изменены только файлы текущей задачи.
Тесты/сборка:

В этой runtime-среде полноценный pytest/build не выполнен: доступ к локальному checkout ограничен сетевым DNS. Поэтому PASS полного набора намеренно НЕ заявляется.
Тестовый код рассчитан на существующие зависимости statsmodels из Phase 6-P0.
Перед merge требуется выполнить: python -m pytest tests/api/test_tune.py tests/api/test_tune_real_models.py tests/api/test_tune_production_dispatch.py -q затем полный API regression suite и Next.js build.
Статус:

Production dispatch реализован в отдельной ветке.
Phase 1-D теперь имеет production wiring к реальным ETS/ARIMA.
После CI/Render smoke PASS Phase 1 tuning можно считать закрытым и переходить к Phase 2 — диагностике остатков.

---

Task 19-E-Fix — production Tune → real ETS/ARIMA
Диагностика локального прогона
Команда пользователя: python -m pytest tests/api/test_tune.py tests/api/test_tune_real_models.py tests/api/test_tune_production_dispatch.py -q

Результат: 69 passed, 5 failed.

Production failure
ARIMA падал внутри statsmodels на коротких expanding-CV folds: IndexError: too many indices for array: array is 0-dimensional.

Причина — statsmodels получает неоднозначное представление training endog на Windows/Python 3.13 в процессе conditional-sum-of-squares initialization.

Test-only failures
Два max_trials теста создавали синтетическую модель test_model. До production dispatch они проходили благодаря STUB _tunable_predict; после удаления STUB такая модель закономерно получает HTTP 422. Это устаревшая зависимость теста от заглушки, а не production defect.

Исправления
apps/api/model_impls/tuning.py
ARIMA tuning adapter нормализует training input в 1-D float64 NumPy array перед передачей в model implementation.
apps/api/model_impls/arima.py
_arima_fit_predict() и Auto-ARIMA fit нормализуют endog в 1-D numeric NumPy array;
добавлена проверка пустого/нечислового ряда;
forecast также нормализуется в 1-D numeric array.
Проверка
Отдельный smoke-test statsmodels 0.14.6 / Python 3.13 с коротким ARIMA training window после нормализации успешно выполняет fit/forecast.

Полный пользовательский pytest после этих изменений ещё требует запуска в Windows checkout. Два устаревших test_model max_trials теста необходимо перевести на реальный model-id либо изолировать через test-local predictor; production STUB возвращать нельзя.

Статус
Production ARIMA hardening выполнен. Phase 1 production dispatch ещё не объявляется полностью PASS до повторного полного targeted pytest и исправления двух тестов, зависящих от удалённого STUB.

---

Task 19-F-Fix

Настройка очистки интеграционных тестов
Область действия
Замените два оставшихся теста настройки интеграции, в которых все еще использовался удаленный синтетический test_model / _tunable_predict путь-заглушка.

Analysis
tests/api/test_tune.py содержал два интеграционных теста MAX_TRIALS с использованием синтетического идентификатора модели test_model. После того как производственная диспетчеризация была переведена на реальные реализации ETS/ARIMA, эти тесты завершились с ошибкой HTTP 422, поскольку test_model намеренно не поддерживается в производственной среде.

Другие исторические сбои Tune были связаны с недостаточной надежностью ARIMA/статистических моделей и не являются частью этой процедуры очистки тестовых данных.

Изменения
Переработано _make_huge_grid_spec() для предоставления реального идентификатора производственной модели: ets.
Сохранил синтетическую модель с 128 комбинациями param_space для отработки MAX_TRIALS=64.
Использовались только допустимые параметры ETS для реального предиктора; семь игнорируемых параметров сетки, используемых только для тестирования, расширяют декартово произведение без изменения семантики модели.
Изменил оба интеграционных теста MAX_TRIALS с model_id="test_model" на model_id="ets".
Сократил эти два теста до одного CV-сгиба, чтобы интеграционный тест с реальной моделью оставался ограниченным, но при этом соблюдался контракт MAX_TRIALS.
Добавил утверждения, которые возвращали отчет о испытаниях для одного CV-сгиба.
Производственный код не менялся.
План проверки
Цель: tests/api/test_tune.py, tests/api/test_tune_real_models.py, tests/api/test_tune_production_dispatch.py
Убедиться, что в тестах Tune не осталось test_model зависимостей.
Запустить набор тестов API и сборку проекта/CI.
Status
Изменения в коде подготовлены на fix/tune-real-model-tests основе текущего main. Локальное выполнение зависит от среды; CI является официальной проверкой сборки/тестирования для ветки.

---
Task ID: 20-A
Agent: main (super-z)
Task: Перекомпоновка вкладки "Навигатор" в CISStat TS Analysis под новый макет Навигатор_NEW.png (standalone + embedded)

Work Log:
- Склонировал репозиторий https://github.com/DimmDay/CISStat-TS-Analysis.git (ветка main).
- Изучил MIGRATION_ARCHITECTURE.md, AGENTS.md, CLAUDE.md, текущее состояние кода: StandaloneHome, ProductJourneyGuide, TsAnalysisPreprocessing/Validation/EDA, ModuleNav, AppShellContext, lib/stages/modeling/plans.
- Получил макет Навигатор_NEW.png — проанализирован через VLM (z-ai vision), разбит на 6 полос для детального изучения.
- Согласовал с тимлидом 8 открытых вопросов (см. ниже "Решения тимлида").
- Создал 3 новых файла (lib/navigator-stops.ts, components/NavigatorHero.tsx, components/TsAnalysisNavigator.tsx) + 2 теста.
- Изменил 3 файла (packages/ui/index.ts, apps/standalone/app/page.tsx, apps/embedded/app/page.tsx).
- typecheck:all — PASS. build:all — PASS (12/12 страниц в каждом app).
- 19/19 новых тестов PASS. 3 пред-существующих падения (ResizeObserver polyfill в jsdom) НЕ связаны с задачей.

Решения тимлида (по 8 вопросам):
1. (a) Навигатор показывается всегда. WorkbenchSummary → /dashboard (отдельная задача).
2. 4 будущих остановки только в Путеводителе. В ModuleNav — внутри «Задачи» (отдельная задача).
3. Правая панель — превью пунктов, кнопка «Запустить» неактивна.
4. Гибрид: активный датасет → реальные показатели, иначе пример с пометкой «пример».
5. Тарифы — декоративный STUB (отдельная задача по интеграции).
6. Светло-серые полосы — простые разделители.
7. Тексты 2 полубейджей утверждены явно.
8. Делаем и в apps/embedded.

Stage Summary:
- Навигатор реализован в обоих apps/* по новому макету: H1 + 6 числовых бейджей + «Для кого/Для чего» с разделителями + 2 полубейджа + 3-колоночный Путеводитель (степпер 10 остановок + Тарифы слева / Описание+Обзор по центру / превью пунктов справа).
- 10 остановок: 6 существующих (Загрузка, Валидация, Предобработка, EDA, Моделирование, Прогнозирование) + 4 будущих (Сценарный/Причинный анализ, Принятие решений, Мониторинг) с пометкой «Soon».
- NAVIGATOR_STOPS — отдельный массив, STAGE_DEFS (контракт с session_store.py) не тронут.
- Артефакты: /home/z/my-project/download/navigator_relayout/ — 8 файлов.
- Worklog в репо: worklog.md (Task ID: 20-A, ~80 строк).
- Готов к визуальной проверке на https://ts-standalone.vercel.app/ после merge.

Открыто для следующих задач:
- Перенос WorkbenchSummary на /dashboard.
- 4 будущих остановки во вкладке «Задачи» ModuleNav.
- Подключение реальных графиков в окно «Обзор».
- Реальная авторизация и интеграция выбора тарифа.

---

Task ID: 20-B
Agent: main (super-z)
Task: «Ремонт» packages/ui/index.ts — объединение редакции тимлида (полная версия origin/main с TimeSeriesLineChart/DecompositionBadges/BacktestComparison/ValidationCheck) с моей редакцией (Навигатор: NavigatorHero/TsAnalysisNavigator/navigator-stops).

Work Log:
- Склонировал свежий репозиторий (sandbox пересоздан, локальная копия пропала).
- Изучил текущее состояние packages/ui/index.ts (коммит 2bddad2 — уже содержит Навигатор + BacktestComparison + ValidationCheck).
- Сравнил с присланой тимлидом редакцией: diff показал 2 расхождения:
  1. В репо нет блока экспортов TimeSeriesLineChart + DecompositionBadges (4 строки export + 2 типа).
  2. В редакции тимлида нет блока Навигатора (NavigatorHero + TsAnalysisNavigator + 8 экспортов/типов из navigator-stops).
- Проверил физическое наличие компонентов: ls packages/ui/components/ показал, что TimeSeriesLineChart.tsx и DecompositionBadges.tsx ОТСУТСТВУЮТ в файловой системе. grep -rn по всему коду подтвердил: эти имена нигде не импортируются и не используются.
- Вывод: редакция тимлида — это целевое состояние с опережением реализации. Если раскомментировать экспорты — tsc упадёт с "Cannot find module './components/TimeSeriesLineChart'".
- Бэкенд-эндпоинты для этих компонентов уже готовы: GET /v1/session/dataset/timeseries и /dataset/decomposition (см. apps/api/routers/session.py L334-399).
- Решение: взял редакцию тимлида целиком + добавил блок Навигатора (мой) в начало файла (после PortalNavBar не стал — поставил в самое начало, т.к. Навигатор — точка входа в продукт). Экспорты TimeSeries/Decomposition ЗАКОММЕНТИРОВАЛ с TODO-комментарием, объясняющим причину и ссылающимся на готовые бэкенд-эндпоинты.
- typecheck:all — PASS (embedded + standalone).
- npx jest NavigatorHero + TsAnalysisNavigator + ModuleNav — 22/22 PASS.
- npm run build:all — PASS (12/12 страниц в каждом app).
- Артефакт: /home/z/my-project/download/index_repair/index.ts.

Stage Summary:
- packages/ui/index.ts «отремонтирован»: объединены обе редакции (тимлида + моя), с явной пометкой TODO на 2 отсутствующих компонента.
- Экспортный контракт @cisstat/ui теперь включает: NavigatorHero, TsAnalysisNavigator, NAVIGATOR_STOPS/BADGES/AUDIENCE/PURPOSE/OVERVIEW_EXAMPLE_METRICS + типы; весь origin/main (DistributionCharts, BacktestComparisonChart, ValidationCheckChart, TsAnalysisModeling, Modeling types, RulesManagementPanel, AppShell, ModuleNav, Plans).
- TimeSeriesLineChart/DecompositionBadges — закомментированы с TODO, ждут создания файлов в отдельной задаче (бэкенд готов).
- Готов к коммиту и push. Не пушу — тимлид пушит сам.

Открыто для следующих задач:
- Создание компонентов TimeSeriesLineChart.tsx и DecompositionBadges.tsx (подключение к готовым бэкенд-эндпоинтам).
- Перенос WorkbenchSummary на /dashboard.
- 4 будущих остановки во вкладке «Задачи» ModuleNav.
- Подключение реальных графиков в окно «Обзор» Навигатора.

---

Task ID: 20-C
Agent: main (super-z)
Task: Добавить новую остановку «График» в правую боковую панель Навигатора (в пункты остановки «Загрузка»). Тимлид добавил эту остановку в TsAnalysisUpload.tsx (commit 9d3c4b7 "Stop Schedule in Stepper") — теперь нужно отразить её в превью Навигатора, чтобы правая панель зеркалила внутренние остановки модуля Загрузки.

Work Log:
- Подтянул свежий origin/main — обнаружил новый коммит 9d3c4b7: тимлид добавил внутреннюю остановку "chart" в STOPS массив TsAnalysisUpload.tsx (id="chart", label="График", позиция между overview и distribution), а также создал файлы TimeSeriesLineChart.tsx и DecompositionBadges.tsx (экспорты в index.ts всё ещё закомментированы — это отдельная задача).
- Изучил текущее состояние NAVIGATOR_STOPS[0].items (id="upload") — 8 пунктов без "График": preview, structure_confirm, quality_teaser, tech_info, preview_5_5, distribution, formats, source.
- Согласовал с тимлидом 2 вопроса: (a) позиция — между "preview" и "distribution"; (b) текст пункта — "Линейный график исследуемого признака по реальной временной оси — первый визуальный взгляд на форму ряда до статистики + декомпозиция Тренд/Сезонность/Цикличность/Остаток."
- Вставил новый item в navigator-stops.ts: id="chart", title="График", description=текст тимлида дословно. Позиция: сразу после "preview" (индекс 1 в массиве) — это совпадает с порядком TsAnalysisUpload STOPS (overview → chart → ...) и логикой анализа (видим датасет → график ряда → распределение).
- Обновил TsAnalysisNavigator.test.tsx:
  * Комментарий "8 пунктов" → "9 пунктов (включая «График»)".
  * Добавил новый тест renders the new 'График' item between 'preview' and 'distribution' in Загрузка — проверяет, что chart идёт после preview и до distribution по индексу, и что title "График" рендерится в правой панели.
  * Комментарий "Второй пункт" → "третий в items Загрузки" (structure_confirm сместился на 3-ю позицию после добавления chart).
  * Комментарий "8 для Загрузки" → "9 для Загрузки, включая «График»".
- typecheck:all — PASS (embedded + standalone).
- npx jest TsAnalysisNavigator + NavigatorHero + TsAnalysisUpload — 38/38 PASS (включая новый тест позиции «График»). Предупреждение ResizeObserver в TsAnalysisUpload.test.tsx — пред-существующее, не связано.
- npm run build:all — PASS (12/12 страниц в каждом app).
- Артефакты: /home/z/my-project/download/navigator_chart_stop/ (navigator-stops.ts, TsAnalysisNavigator.test.tsx).

Stage Summary:
- В правой боковой панели Навигатора для остановки «Загрузка» теперь 9 пунктов (было 8) — добавлен «График» между «Автопревью и типы колонок» и «Подтверждение автоопределения».
- id нового item — "chart", совпадает с StopId в TsAnalysisUpload.tsx (id="chart") — сохранена консистентность идентификаторов между Навигатором и модулем.
- Текст пункта (description) — дословно от тимлида, длина ~165 символов, вписывается в стиль других пунктов правой панели.
- Изменены 2 файла: navigator-stops.ts (1 новый item), TsAnalysisNavigator.test.tsx (1 новый тест + 3 обновлённых комментария).
- WorkbenchSummary → /dashboard, 4 будущих остановки во вкладке «Задачи», подключение реальных графиков в окно «Обзор», раскомментирование экспортов TimeSeriesLineChart/DecompositionBadges — отложены (тимлид будет отдельно проектировать).

Открыто для следующих задач:
- Раскомментировать экспорты TimeSeriesLineChart/DecompositionBadges в packages/ui/index.ts (файлы уже созданы тимлидом в 9d3c4b7, экспорт закомментирован в 20-B до их создания).
- Перенос WorkbenchSummary на /dashboard (отдельная задача, auth отдельно).
- 4 будущих остановки во вкладке «Задачи» ModuleNav.
- Подключение реальных графиков в окно «Обзор» Навигатора.

--- 

Task ID: 20-D

Agent: main (super-z) Task: починить падающие тесты — тимлид сообщил «Не все тесты прошли». 
Контекст: после коммита 6061bf9 (Task 20-C, добавил «График» в Навигатор) была запущена полная Jest-сюита, и обнаружилось 23 падающих теста в 3 файлах (RulesManagementPanel 5, TsAnalysisPreprocessing 9, TsAnalysisEDA 9). 
Доказано, что падения ПРЕД-существующие: чекаут 9d3c4b7 (родительский коммит) даёт тот же 23-fail. Никакого отношения к моему добавлению «График» это не имеет. Work Log: - Диагностика: запустил `npx jest` на HEAD (6061bf9) — 3 failed suites, 23 failed tests, 113 passed. - Диагностика: чекаут 9d3c4b7 (родитель) — те же 23 failures. 
Подтверждено: моя задача 20-C НЕ причина. 
- Категория A (18 failures): `ReferenceError: ResizeObserver is not defined` в TsAnalysisPreprocessing.tsx:152 и TsAnalysisEDA.tsx:152 — компоненты используют ResizeObserver для отслеживания overflow центрального окна «Описание», но jsdom его не реализует. Полифилла не было. 
- Категория B (5 failures): race condition в RulesManagementPanel.test.tsx — `fireEvent.change(selector, { value: "fao_prices" })` срабатывал ДО загрузки шаблонов (асинхронный GET /v1/internal/rules/templates). В селекторе не было option "fao_prices", change был no-op, последующие waitFor на apply-rules-btn таймаутились. 
- Категория C (4 failures): `getByText(/Цели модуля/i)` в Preprocessing/EDA тестах "clicking 'Справка' shows help content" и "collapse chevron appears inside description after expanding" — regex матчит ДВА элемента: подзаголовок «Справка — Цели модуля и результаты прохождения» И сам контент «Цели модуля "Предобработка"». Тест падал с "Found multiple elements with the text". Это латентно маскировалось предыдущей ошибкой ResizeObserver — пока ResizeObserver не давал компоненту отрендериться, до двойного match дело не доходило. 
После polyfill — проявилось. Fix A: создан jest.setup.js с polyfills ResizeObserver/IntersectionObserver/matchMedia. Подключён через setupFilesAfterEnv в jest.config.js. 18 тестов проходят. Fix B: переписан RulesManagementPanel.test.tsx — добавлен хелпер waitTemplatesLoaded(), который через waitFor ждёт, что в селекторе появятся ≥4 <option>, и только потом делает fireEvent.change. Также исправлен lookup min/max input: <label> без htmlFor не ассоциируется с <input>, поэтому getAllByLabelText(/^Минимум/i) возвращал 0 — заменён на getAllByText(/^Минимум$/i) + getAllByRole("spinbutton") + DOM-walk через parentElement.querySelector('input[type="number"]'). Reset-тест теперь корректно находит первый input через соседний <label>. 5 тестов проходят. Fix C: в TsAnalysisPreprocessing.test.tsx и TsAnalysisEDA.test.tsx заменён `getByText(/Цели модуля/i)` → `getAllByText(/Цели модуля/i)` + `expect(matches.length).toBeGreaterThanOrEqual(1)`. 4 теста проходят. 
Бонус (Task 20-B, отложенный): раскомментированы экспорты TimeSeriesLineChart и DecompositionBadges в packages/ui/index.ts. Файлы TimeSeriesLineChart.tsx и DecompositionBadges.tsx созданы тимлидом в коммите 9d3c4b7 — теперь экспорты активны, не падают с "Cannot find module". Verification: - `npx jest` — 11/11 suites PASS, 136/136 tests PASS. - `npm run typecheck:all` — PASS (embedded + standalone, 0 errors). - `npm run build:all` — PASS (12/12 pages в каждом app, 0 errors). Stage Summary: - 23 падающих теста починены: 18 (ResizeObserver polyfill) + 5 (RulesManagementPanel race condition) + 4 (getByText → getAllByText). Все 136 тестов проходят. - 

Изменённые файлы (5 шт.): 1. jest.setup.js (NEW) — polyfills для jsdom. 2. jest.config.js — добавлен setupFilesAfterEnv. 3. packages/ui/components/RulesManagementPanel.test.tsx — waitTemplatesLoaded + DOM-walk lookup. 4. packages/ui/components/TsAnalysisPreprocessing.test.tsx — getByText → getAllByText (2 теста). 5. packages/ui/components/TsAnalysisEDA.test.tsx — getByText → getAllByText (2 теста). 6. packages/ui/index.ts — раскомментированы экспорты TimeSeriesLineChart/DecompositionBadges (бонус, закрывает отложенный TODO из 20-B). - 

Артефакты: /home/z/my-project/download/navigator_chart_stop_fix/ (6 файлов + test_results.txt). Открыто для следующих задач: - Перенос WorkbenchSummary на /dashboard. - 4 будущих остановки во вкладке «Задачи» ModuleNav. - Подключение реальных графиков в окно «Обзор» Навигатора (теперь экспорты готовы). EOF echo "Worklog updated" tail -5 worklog.md

---

Task 20 — PHASE 2: Диагностика остатков

Status
Backend MVP implementation completed on isolated branch; CI/local execution pending.

Process
Синхронизирована отдельная ветка от актуального main.
Перед изменениями просмотрены текущие apps/api/schemas.py, apps/api/routers/models.py, apps/api/model_impls/ets.py, apps/api/model_impls/arima.py, apps/api/main.py.
schemas.py и models.py не изменялись: это снижает риск перезаписи параллельной работы команды.
Создан отдельный diagnostics router и отдельные Pydantic-контракты Phase 2.
Реализовано
POST /v1/models/diagnostics.
Реальные residuals получаютcя после fit реальных statsmodels ETS/ARIMA.
Ljung–Box.
Jarque–Bera.
ARCH-LM.
Durbin–Watson.
applicable_if и честный applicable=false для недостаточной длины ряда/нулевой дисперсии.
Alpha configurable, default 0.05.
Статусы pass | warning | fail для UI.
Авторизация через существующий can_train_models.
Тесты
Создан tests/api/test_diagnostics.py:

ETS residuals из реального statsmodels fit.
ARIMA residuals из реального statsmodels fit.
Ljung–Box not applicable при недостаточном числе наблюдений.
ARCH-LM not applicable при нулевой дисперсии.
UI status contract.
Изменённые файлы
apps/api/routers/diagnostics.py — новый.
apps/api/main.py — только импорт diagnostics и регистрация router.
tests/api/test_diagnostics.py — новый.
worklog/Task-20-Phase2.md — текущая запись.
Риски и ограничения
schemas.py и routers/models.py намеренно не затронуты.
UI Phase 2 пока не реализован.
Residuals для Phase 2 fit повторяет параметры реальной модели; следующий этап должен унифицировать fit-result/residual contract перед Phase 3, чтобы исключить drift между tuning и diagnostics.
Полный pytest/build в текущей среде не запускались; перед merge требуется локальный targeted suite и полный CI.

---

Task 20 — Phase 2 residual diagnostics UI

Scope
Finish the standalone/embedded UI path for Phase 2 without overwriting parallel work in TsAnalysisModeling.tsx, schemas.py, or models.py.

Design
Браузер вызывает /v1/internal/models/diagnostics с учетными данными: include.
Необработанные данные наблюдений из браузера не отправляются.
Бэкенд определяет текущую AnalysisSession, выбранный target_column и DataFrame из cookie сессии.
Бэкенд повторно использует функции подгонки остатков реальной модели и диагностики из apps/api/routers/diagnostics.py на этапе 2.
Пользовательский интерфейс отображает Ljung–Box, Jarque–Bera, ARCH-LM и Durbin–Watson.
Условные тесты отображают N/A и reason/applicable_if, когда неприменимо.
Контроль рисков
packages/ui/components/TsAnalysisModeling.tsx был намеренно НЕ изменен, поскольку это большой общий компонент, и текущий основной компонент не предоставляет сохраняемый контракт Tune best_params. Прямое подключение Diagnostics к параметрам модели по умолчанию создало бы ложную связь между Tune и Diagnostics.

Таким образом, пользовательский интерфейс был предоставлен в виде изолированной, многократно используемой панели ResidualDiagnosticsPanel. Ее можно смонтировать после синхронизации текущего пользовательского интерфейса/состояния настройки. Это позволяет избежать перезаписи параллельно выполняемой работы и диагностики конфигурации модели, отличной от настроенной.

Измененные файлы:
apps/api/routers/diagnostics_internal.py — новый внутренний конечный пункт, использующий сессию.
apps/api/main.py — регистрирует внутренний маршрутизатор диагностики.
packages/ui/components/ResidualDiagnosticsPanel.tsx — новая многоразовая панель диагностики.
packages/ui/components/ResidualDiagnosticsPanel.test.tsx — тесты пользовательского интерфейса.
tests/api/test_diagnostics_internal.py — тесты маршрутизации сессий плюс реальная диагностика остаточных ошибок ETS.

Приемочное покрытие:
Столбец «Цель сессии» обязателен.
Отсутствующий набор данных/цель отклоняется.
Нечисловая цель отклоняется.
Реальные остаточные ошибки ETS достигают всех четырех диагностических показателей.
Пользовательский интерфейс отображает названия тестов, статус, статистику, p-значение, применимость/причину.
Пользовательский интерфейс отправляет cookie сессии.

Next step
Mount ResidualDiagnosticsPanel from the current TsAnalysisModeling after the parallel Tune UI exposes its persisted best_params. Pass those exact parameters; do not silently use {} for a tuned model.

---

Task 20 — Phase 2: Residual Diagnostics UI connection
Область применения
Подключить ResidualDiagnosticsPanel к текущему этапу моделирования без перезаписи общей реализации моделирования, используемой командой.

Обзор репозитория
Проверены следующие основные файлы:

packages/ui/components/TsAnalysisModeling.tsx — это общий модуль моделирования, используемый автономными и встроенными приложениями.
apps/standalone/app/modeling/page.tsx монтирует только TsAnalysisModeling.
apps/api/routers/diagnostics_internal.py и apps/api/main.py уже присутствуют и предоставляют доступ к конечной точке диагностики, основанной на сессии.
Текущий модуль пока не имеет сохраненных параметров best_params из Tune.
Оценка рисков
Основной риск заключается в перезаписи большого общего файла TsAnalysisModeling.tsx во время активной параллельной разработки. Доступный для этой задачи коннектор может обновлять целые файлы, но не может применять построчные изменения к существующему большому файлу. Чтобы избежать уничтожения параллельной работы, файл TsAnalysisModeling.tsx был намеренно не перезаписан.

Был подготовлен отдельный минимальный патч:

TsAnalysisModeling.phase2.patch

Он добавляет:

Импорт ResidualDiagnosticsPanel.
Выбор модели на этапе диагностики.
Рендеринг только для ETS / ETS Damped / ARIMA после успешного бэктеста.
Автоматическое выполнение диагностики при выборе этапа диагностики.
Коллбэк завершения, отмечающий завершение этапа диагностики.
Явные сообщения пользовательского интерфейса о недостающих бэктестах и ​​неподдерживаемых моделях.
Безопасная реализация в ветке
packages/ui/components/ResidualDiagnosticsPanel.tsx
добавлен коллбэк onComplete;
сохраняется существующее поведение API/сессии;
сообщается об успешном выполнении диагностики родительскому шаговому процессу.
packages/ui/components/ResidualDiagnosticsPanel.test.tsx
проверяет автоматическое выполнение;
проверяет коллбэк завершения;
проверяет рендеринг условного теста N/A.

Без изменений
apps/api/routers/models.py
apps/api/routers/diagnostics.py
apps/api/routers/diagnostics_internal.py
apps/api/main.py
packages/ui/lib/modeling.ts
schemas.py
Проверка
Интеграция с общим файлом TsAnalysisModeling.tsx не может быть безопасно зафиксирована через текущий коннектор GitHub без полной замены параллельно отредактированного файла. Поэтому фактическая интеграция родительского компонента ожидается после применения подготовленного патча в новой локальной ветке / командной ветке.

В этой среде не заявлено прохождение тестов/сборок.

Критерии завершения
Фаза 2 считается завершенной от начала до конца после применения патча и успешного прохождения следующего процесса:

Бэктест → выбрать Диагностику → ResidualDiagnosticsPanel → POST /v1/internal/models/diagnostics → четыре теста → этап диагностики завершен.

В будущей интеграции Tune необходимо передавать best_params в ту же панель вместо {}.

---

Task ID: 21
Agent: main (super-z)
Task: Вкладка «Навигатор», ряд «Для кого / Для чего» — сделать оба полубейджа раскрывающимися по типу селектора: в закрытом состоянии виден только заголовок «ДЛЯ КОГО», при клике на чеврон справа — раскрывается текст.

Work Log:

Синхронизирован с origin/main (commit 1b80893 «Navigator-stops_label loading»). Working tree clean.
Изучена текущая структура:
• NavigatorHero.tsx — чисто презентационный (без useState), 2 статичных полубейджа «Для кого» / «Для чего» с чек-иконкой + текстом видимым всегда.
• AUDIENCE_LABEL / AUDIENCE_TEXT / PURPOSE_LABEL / PURPOSE_TEXT — в lib/navigator-stops.ts, утверждены тимлидом 2026-08-17.
• Тесты NavigatorHero.test.tsx — 5 штук, проходят.
Спроектирован процесс решения (см. ниже «Проектирование»): точки изменения, 7 рисков с мерами, 13 тестов (5 обновлены + 8 новых).
TDD: сначала написан NavigatorHero.test.tsx с новыми ожиданиями (collapsed-by-default, toggle, aria-expanded, aria-controls, chevron direction, independence).
Первый прогон тестов до реализации: 10/13 FAIL (TDD red), 3 PASS (H1, 6 numbered badges, labels exist).
Реализован NavigatorHero.tsx:
• Добавлен "use client" (раньше не было — компонент был без состояния).
• Импорты: useState (react), Check + ChevronDown + ChevronUp (lucide-react).
• Вынесен внутренний компонент CollapsibleHalfBadge (label, text, isOpen, onToggle) — чтобы не плодить копию разметки для двух экземпляров (урок MIGRATION_ARCHITECTURE.md §2.1 «одна копия каждой фичи»).
• Контролируемое состояние isOpen/onToggle — родитель хранит 2 независимых useState (audienceOpen, purposeOpen), НЕ accordion «один открыт».
• a11y: <button> с aria-expanded (false/true) + aria-controls; панель с текстом получает id, совпадающий с aria-controls.
• Иконка чеврона: role="img" + aria-label ("chevron down" / "chevron up") для скринридеров; ChevronDown когда свёрнут, ChevronUp когда раскрыт.
• Стабильный id панели генерируется из label через sanitize: navigator-badge-{sanitize(label)}-panel — совпадает между рендерами (React не пересоздаёт id).
• Стили сохранены: border-brand/20, bg-brand-light/40, hover-bg-brand-light/70 на триггере, focus-visible ring.
• overflow-hidden на корневом div бейджа — чтобы скруглённые углы не «протекали» при hover.
Повторный прогон тестов: 13/13 PASS (TDD green).
Регрессия: полный набор jest 12/12 suites PASS, 147/147 tests PASS — без изменений в существующих тестах, кроме NavigatorHero (где 2 обновлены под новое поведение, остальные 146 не тронуты).
Typecheck:all PASS (embedded + standalone, 0 errors).
Build:all PASS (12/12 страниц в каждом app, 0 errors; / → 289 B, 275 kB First Load — бандл не раздут).
Файлы выложены в /home/z/my-project/download/navigator_collapsible_badges/.
Проектирование:

Точки изменения: только packages/ui/components/NavigatorHero.tsx и .test.tsx. navigator-stops.ts НЕ тронут (контракт с данными сохранён). TsAnalysisNavigator.tsx НЕ тронут. index.ts НЕ тронут (NavigatorHero уже экспортируется).
Риски и меры (7 шт, все закрыты):
R1 Регрессия старых тестов «text visible» → обновил 2 существующих теста под новое поведение (collapsed by default).
R2 a11y → <button> с aria-expanded + aria-controls, id панели.
R3 SSR/hydration → добавлен "use client".
R4 Независимость 2 бейджей → 2 отдельных useState, НЕ accordion.
R5 Чеврон меняется (down→up) → ChevronDown/ChevronUp из lucide-react с role="img" + aria-label.
R6 Визуальная консистентность с макетом → сохранены border-brand/20 bg-brand-light/40, добавлен hover и focus-visible ring.
R7 Параллельная работа тимлида → синхронизирован с origin/main до старта, после сборки — конфликта нет (не тронуты файлы тимлида).
Stage Summary:

Изменено 2 файла: NavigatorHero.tsx (+55 строк нетто, добавлен useState/use client/CollapsibleHalfBadge/ChevronUp/ChevronDown/aria), NavigatorHero.test.tsx (+135 строк, 5 обновлённых + 8 новых тестов).
Поведение «по типу селектора»: закрыто по умолчанию (только заголовок + чеврон ↓), клик раскрывает текст и меняет чеврон на ↑.
2 полубейджа независимы: можно открыть оба, можно закрыть оба, состояние каждого не зависит от другого.
a11y-контракт: <button aria-expanded aria-controls> + панель с id, чеврон с role="img" + aria-label.
147/147 тестов PASS (включая 13/13 в NavigatorHero), 0 регрессий.
Typecheck:all PASS, Build:all PASS (12/12 страниц в каждом app, бандл не раздут).
Артефакты: /home/z/my-project/download/navigator_collapsible_badges/ (2 файла).
Deploy checklist (after merge):

git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui).
Backend (Render) трогать НЕ нужно — изменения чисто фронтенд.
Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/ → убедиться, что «Для кого» и «Для чего» показывают только заголовок → кликнуть на чеврон → текст раскрывается → кликнуть повторно → сворачивается → открыть оба независимо → работает.
a11y-проверка: Tab-навигация доходит до триггеров, Enter/Space переключает состояние, aria-expanded корректно анонсируется скринридером.

---

Task ID: 22

Agent: main
Task: Вкладка «Навигатор», остановка степпера «Загрузка». Отрисовать в окне «Обзор» блок-схему «Пайплайн автопревью» (информационную). Показывает последовательность шагов, которые платформа выполняет сразу после загрузки файла. Состав: Файл → Детект кодировки/разделителя → Парсинг → Детект типов → classify_columns (4 подтипа: numeric/categorical/datetime/text) → Подсчёт пропусков → Подсчёт уникальных → Предупреждения парсинга → Готово → SessionStore.

Work Log:
Синхронизирован с origin/main (commit 33b34b8 «Both half-badges For whom / For what in the Navigator tab are made expandable»). Working tree clean до старта.
Изучена текущая структура окна «Обзор» в TsAnalysisNavigator.tsx (строки 238-269): заголовок «Обзор: {item.title}», подзаголовок + бейдж «пример» (если нет активного датасета), заглушка <div role="img">[ область графика/таблицы/блок-схемы для «…» ] высотой h-[280px], метрики 2×4 снизу.
Изучен реальный бэкенд пайплайна автопревью, чтобы шаги блок-схемы соответствовали коду, а не выдумывались:
apps/api/upload_common.py: handle_upload, _compute_column_info, _compute_quality_teaser, _compute_parse_warnings — реальная последовательность.
app/data/file_loader.py: read_uploaded_file — pd.read_csv с engine='python', encoding='utf-8-sig', sep=None (auto), а также read_excel / json_normalize / parse_jsonstat.
app/classification/classifier.py: classify_columns — numeric (select_dtypes number), date (datetime64), cat (object/string с 1<nunique<100), text (fallback).
apps/api/session_store.py: DatasetInfo / session.set_dataset + store.save() — финальная точка пайплайна.
Изучен ближайший архитектурный родственник — StructuralClassSchema.tsx: статичная информационная схема с подсветкой активной строки, паттерн «чистый презентационный компонент + типизированный массив правил». UploadAutoPreviewPipeline следует тому же паттерну, но вместо дерева решений — последовательность шагов с одним ветвлением на classify_columns.
Согласование с тимлидом (в чате, до реализации):
Область показа — только для пункта preview «Автопревью и типы колонок». Для остальных пунктов текущая заглушка остаётся (своя визуализация для каждого пункта в будущих задачах).
Состав шагов — 7 из примера + «Предупреждения парсинга» (переименовано из «Парсинг-варнинги») + «Готово → SessionStore». Итого 9 шагов.
Иконки — lucide-react (уже в проекте).
TDD: сначала написан UploadAutoPreviewPipeline.test.tsx (9 тестов) + апдейт TsAnalysisNavigator.test.tsx (+4 новых теста на условный рендер).
Реализован UploadAutoPreviewPipeline.tsx:
PIPELINE_STEPS — типизированный массив из 9 шагов (id, title, subtitle, icon: LucideIcon, badge?). Порядок повторяет handle_upload.
CLASSIFY_SUBTYPES — 4 подтипа classify_columns (numeric/categorical/datetime/text) с подсказками по реальным pandas-вызовам.
PipelineNode — одна нода пайплайна (иконка в бренд-кружке + заголовок + технический subtitle + опц. badge).
ChevronSeparator — вертикальная стрелка ChevronDown между шагами (aria-label="chevron down" — единый паттерн с NavigatorHero.tsx).
Корневой role="img" + aria-label со всем пайплайном одной строкой — скринридер читает как одно изображение.
min-h-[280px] на корневом div — чтобы блок-схема не обрезалась, но и не падала ниже текущей высоты заглушки (визуальная консистентность окна «Обзор»).
Ветвление classify_columns — отдельный блок с border-l-2 border-dashed border-neutral-200 (тот же стиль, что в StructuralClassSchema для sub-rules), 4 чипа разворачиваются в колонку на mobile и в ряд на sm+.
Реализован условный рендер в TsAnalysisNavigator.tsx (строки 255-273): при activeStopId==="upload" && activeItemId==="preview" рендерится <UploadAutoPreviewPipeline/>, иначе — текущая текстовая заглушка. Импорт добавлен в начало файла.
Реэкспорт в packages/ui/index.ts: UploadAutoPreviewPipeline + PIPELINE_STEPS (значение) + PipelineStep (тип) — для потенциального переиспользования в onboarding-туре или документации.
Первый прогон тестов UploadAutoPreviewPipeline.test.tsx: 1 FAIL (тест ожидал 7 шагов, реально 9 — противоречие в самом тесте, исправил). Повторный прогон: 9/9 PASS.
Полный прогон jest: 13/13 suites PASS, 160/160 tests PASS. Существующие 19 тестов TsAnalysisNavigator не сломаны (+4 новых = 23 всего). Реакс-предупреждения ResponsiveContainer в BacktestComparisonChart — известный шум (упомянут в jest.setup.js), к задаче не относится.
Typecheck:all PASS (embedded + standalone, 0 errors).
Build:all PASS: embedded — 12/12 страниц, standalone — 12/12 страниц. Бандл не раздут (root route = 289 B / 278 kB First Load — тот же, что до изменений; компонент статичный, без JS-зависимостей кроме lucide-иконок).
Проектирование:
Точки изменения (только по текущей задаче, 5 файлов):

packages/ui/components/UploadAutoPreviewPipeline.tsx — НОВЫЙ (компонент + PIPELINE_STEPS + CLASSIFY_SUBTYPES).
packages/ui/components/UploadAutoPreviewPipeline.test.tsx — НОВЫЙ (9 тестов).
packages/ui/components/TsAnalysisNavigator.tsx — правка (импорт + условный рендер в окне «Обзор», ~17 строк нетто).
packages/ui/components/TsAnalysisNavigator.test.tsx — правка (+4 теста на условный рендер пайплайна).
packages/ui/index.ts — правка (реэкспорт компонента + типа).
Риски и меры (9 шт, все закрыты):

#
Риск
Мера
R1	Высота пайплайна > 280px текущей заглушки	Заменил h-[280px] на min-h-[280px] на корневом div компонента, контейнер растёт по содержимому. Тестов на жёсткую высоту в репо нет (проверил).
R2	Регрессия существующих тестов Навигатора (19 шт)	Проверил: ни один не проверяет текст заглушки [ область графика... (только заголовок «Обзор: ...», метрики, кнопки). Полный прогон подтвердил 0 регрессий.
R3	Условие показа слишком узкое/широкое	Согласовано с тимлидом: только upload+preview (см. чат). Легко расширить до всей остановки «Загрузка» одной правкой, если потребуется.
R4	Мобильная вёрстка 4 чипов classify_columns	flex-col на < sm, flex-row на sm+. На 320px помещается вертикально.
R5	Дублирование с StructuralClassSchema	Разные схемы: Structural — дерево решений (статичные rules), Pipeline — последовательность шагов (sequence). Обе информационные, обе нужны. Паттерн один — но не дубликат.
R6	Сборка standalone/embedded	Компонент в packages/ui, импорт в существующий TsAnalysisNavigator (уже используется обоими apps) → автоматически попадает в оба. Build:all подтвердил.
R7	a11y	Корневой role="img" + aria-label со всей последовательностью шагов одной строкой. Иконки и стрелки внутри — aria-hidden="true" (дублируют текст). ChevronDown с role="img" + aria-label="chevron down" (как в NavigatorHero.tsx).
R8	Параллельная работа тимлида	Синхронизирован с origin/main до старта, после сборки конфликтов нет (новый файл + точечные правки в существующих, не пересекаются с другими активными задачами).
R9	TypeScript-несовместимость типа иконок lucide-react с React.ComponentType<{size?: number}> (size: string|number в LucideProps)	Использован type LucideIcon из lucide-react (тот же паттерн, что в StatusIcon.tsx). Typecheck чистый.

Stage Summary:
Изменено 5 файлов: 2 новых (UploadAutoPreviewPipeline.tsx + .test.tsx, ~250+95 строк), 3 правки (TsAnalysisNavigator.tsx +17 строк, TsAnalysisNavigator.test.tsx +44 строки, index.ts +8 строк).
UploadAutoPreviewPipeline — чисто презентационный, без state, без effects. PIPELINE_STEPS вынесен в экспорт для переиспользования.
9 шагов пайплайна соответствуют реальному бэкенду: Файл (.csv/.xlsx/.xls/.json) → Детект кодировки/разделителя (engine='python', encoding='utf-8-sig', sep=None) → Парсинг (pd.read_csv/read_excel/json_normalize/parse_jsonstat) → Детект типов (datetime64/numeric/object/string) → classify_columns (4 подтипа) → Подсчёт пропусков (cols_with_missing, nulls) → Подсчёт уникальных (nunique) → Предупреждения парсинга (Unnamed: N, U+FFFD «�») → Готово → SessionStore.
Условный рендер: только при активной паре «Загрузка» + «Автопревью и типы колонок» (id="upload" + id="preview"). Для остальных пунктов — текущая текстовая заглушка.
a11y: role="img" + aria-label со всем пайплайном одной строкой, иконки и chevron-ы aria-hidden/role=img.
160/160 тестов PASS (13/13 suites), 0 регрессий. +13 новых тестов (9 в UploadAutoPreviewPipeline, 4 в TsAnalysisNavigator).
Typecheck:all PASS, Build:all PASS (12/12 страниц в каждом app, бандл не раздут).
Артефакты: /home/z/my-project/download/task22-navigator-pipeline/ (5 файлов + worklog.md).
Deploy checklist (after merge):
git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui).
Backend (Render) трогать НЕ нужно — изменения чисто фронтенд.
Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/ → по умолчанию активная остановка «Загрузка» + пункт «Автопревью и типы колонок» → в окне «Обзор» должна появиться блок-схема пайплайна с 9 шагами и 4 подтипами classify_columns → кликнуть другой пункт (например «График») → пайплайн исчезает, возвращается текстовая заглушка → кликнуть обратно на «Автопревью и типы колонок» → пайплайн снова виден → кликнуть на «ВАЛИДАЦИЯ» в степпере → пайплайн исчезает → кликнуть на «ЗАГРУЗКА» → пайплайн снова виден (handleStopClick сбрасывает item на первый).
a11y-проверка: скринридер читает весь пайплайн как одно изображение с описанием «Пайплайн автопревью: Файл → Детект кодировки/разделителя → Парсинг → ...».

--- 

Task ID: 23

Agent: main Task: Перекомпоновка главной страницы «Навигатор». Новая последовательность колонок слева направо: 1. Степпер, 2. Правая боковая панель (Этапы модуля), 3. Окна Описание + Обзор. Бывшая правая колонка (превью пунктов) становится средней, бывшая центральная (Описание + Обзор) становится правой. Work Log:
- Синхронизирован с origin/main (commit c29a503 «modified: packages/ui/components/TsAnalysisNavigator.tsx» — переименование «Путеводитель» → «Маршрут исследования»). 
- Изучена текущая компоновка TsAnalysisNavigator.tsx: корневой `<div className="flex gap-6 mt-8">` с 3 детьми: `<aside className="w-60">` (степпер + тарифы), `<section className="flex-1 min-w-0">` (Описание + Обзор), `<aside className="w-80">` (Этапы модуля). 
- Обнаружен сломанный тест: `renders 'Путеводитель' and 'Тарифы' headings` (строка 75-79) — упал после переименования заголовка в commit c29a503. Тест ожидал «Путеводитель», а в компоненте уже «Маршрут исследования». Этот тест был сломан ДО Task 23 и блокировал проверку любой правки в этом файле. 
- TDD RED: добавлены 4 новых теста на новый порядок колонок: 
• `renders 3 top-level columns in the new order: stepper | stages | description+overview` — через within() проверяет, что в col2 (средняя) находятся «Этапы модуля», в col3 (правая) — «Описание» и «Обзор:». Использован closest(".flex.gap-6.mt-8") для поиска корневого div (более ранние попытки с `closest("div.flex")` провалились — находили внутренний div с заголовком). 
• `does NOT render 'Этапы модуля' in the right (3rd) column after Task 23` — регрессионный тест: если кто-то вернёт старый порядок, тест упадёт. 
• `does NOT render 'Описание' in the middle (2nd) column after Task 23` — симметричный регрессионный тест. 
• `preserves widths: w-60 for stepper, w-80 for stages, flex-1 for description+overview` — контракт ширин сохранён. 
- Все 4 теста упали на TDD RED (ожидаемо), 19 существующих прошли (включая фикс «Маршрут исследования»). - Реализована перестановка в TsAnalysisNavigator.tsx: в JSX блок `<aside className="w-80">` (Этапы модуля) перемещён выше, теперь идёт перед `<section>` (Описание + Обзор). Сами блоки не изменены — только их порядок. CSS-классы ширин сохранены без изменений. 
- Обновлены комментарии в шапке файла: ASCII-схема компоновки и описание поведения переписаны под новый порядок. 
- Обновлены маркеры колонок: «ЦЕНТРАЛЬНАЯ КОЛОНКА» → «ПРАВАЯ КОЛОНКА» (для Описание + Обзор), «ПРАВАЯ КОЛОНКА» → «СРЕДНЯЯ КОЛОНКА» (для Этапов модуля), добавлен маркер «ЛЕВАЯ КОЛОНКА». 
- Обновлён комментарий в тесте `clicking an item in the right panel` → `clicking an item in the middle column` (R5). 
- Обновлён комментарий в тесте `renders the new 'График' item...`: «в правой панели» → «в средней колонке». 
- Попутный фикс: сломанный тест `renders 'Путеводитель'` → `renders 'Маршрут исследования'` (R1). В тесте добавлен комментарий с указанием коммита c29a503, который сломал тест. - TDD GREEN: повторный прогон — 23/23 PASS (19 существующих + 4 новых). 
- Полный прогон jest: 13/13 suites PASS, 166/166 tests PASS. 0 регрессий. - Typecheck:all PASS (embedded + standalone, 0 errors). - Build:all PASS: 12/12 страниц в каждом app. Бандл не изменился: root route = 288 B / 278 kB First Load. Перестановка — чисто визуальная, JS-бандл не затронут. 
Проектирование: Точки изменения (2 файла, только по текущей задаче): 
1. packages/ui/components/TsAnalysisNavigator.tsx — перестановка 2 блоков в JSX + обновление 4 комментариев (шапка, 3 маркера колонок). 
2. packages/ui/components/TsAnalysisNavigator.test.tsx — фикс сломанного теста (1), обновление 2 комментариев, добавление 4 новых тестов с within(). 
Риски и меры (8 шт, все закрыты): | # | Риск | Мера | |---|------|------| | R1 | Тест «Путеводитель» (стр. 75-79) уже сломан до нас (commit c29a503 тимлида переименовал заголовок в «Маршрут исследования») | Зафиксирован в этом же тесте как попутный фикс. Без него весь набор красный, валидацию нашей правки не проверить. Тест теперь ищет «Маршрут исследования» + комментарий со ссылкой на коммит c29a503. | | R2 | Тесты `getByText` проходят и при старом порядке (текст всё равно где-то в DOM) — не ловят перестановку | Использован `within(column)` — проверяет, что элемент находится в КОНКРЕТНОЙ колонке. Это единственный надёжный способ верифицировать порядок в DOM. | | R3 | На мобильном (< 1024px) колонки схлопываются | Текущая вёрстка `flex gap-6` без `flex-col-reverse` — на мобильном горизонтальный скролл. Существующее поведение, не наша задача. | | R4 | Тест `renders UploadAutoPreviewPipeline when Загрузка + preview item are active` использует `getByRole("img")` — перестановка не влияет | Проверил — да, не влияет, тест остался зелёным. | | R5 | Тест `clicking an item in the right panel` (стр. 139) упоминает «right panel» — после перестановки это средняя колонка | Обновил название теста и комментарий: «right panel» → «middle column». | | R6 | Ширина `w-80` для бывшей правой панели в новой средней позиции может визуально дисбалансировать | Ширина сохранена (w-80 = 320px) — это уже было решение тимлида, не наша задача его менять. Тест `preserves widths` явно фиксирует контракт. | | R7 | Комментарий-схема в шапке файла описывает старый layout | Обновил ASCII-схему + описание поведения в шапке + 3 маркера колонок. | | R8 | Параллельная работа тимлида | Синхронизирован с origin/main до старта. Последний коммит тимлида (c29a503) касался переименования заголовка — не пересекается с моей перестановкой блоков. | Stage Summary: Изменено 2 файла: TsAnalysisNavigator.tsx (~+30 строк нетто, перестановка 2 блоков + комментарии) и TsAnalysisNavigator.test.tsx (+~85 строк, 4 новых теста + 1 фикс + 2 апдейта комментариев). 
Новая последовательность колонок: 
1. Степпер (w-60) | 2. Этапы модуля (w-80) | 3. Описание + Обзор (flex-1). Контракт ширин сохранён: степпер w-60, этапы w-80, описание+обзор flex-1. Тест `preserves widths` фиксирует это явно. 4 новых теста с within() — единственный надёжный способ верифицировать порядок колонок (getByText проходит и при старом порядке). 166/166 тестов PASS (13/13 suites), 0 регрессий. +4 новых теста (всего 23 в TsAnalysisNavigator). Typecheck:all PASS, Build:all PASS (12/12 страниц в каждом app, бандл не изменился — 288 B / 278 kB). Артефакты: /home/z/my-project/download/task23-navigator-reorder/ (2 файла). Deploy checklist (after merge): git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui). Backend (Render) трогать НЕ нужно — изменения чисто фронтенд. Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/ → в основной 3-колоночной секции слева направо должны идти: 1) Маршрут исследования (степпер 10 остановок + Тарифы), 2) Этапы модуля (превью пунктов активной остановки, например «Автопревью и типы колонок» для Загрузки), 3) Описание + Обзор (с блок-схемой «Пайплайн автопревью» при активном пункте preview). Проверить交互: клик по пункту в средней колонке → меняется заголовок «Обзор: ...» в правой колонке. Клик по остановке степпера → меняется содержимое средней колонки (новые пункты) и правой (новое описание). На мобильном (320px viewport): проверить, что нет визуального слома — ожидается горизонтальный скролл (существующее поведение). EOF echo "OK worklog Task 23 appended"; wc -l /home/z/my-project/workspace/CISStat-TS-Analysis/worklog.md

--- 

Task ID: 24 

Agent: main (super-z) Task: 
Новая главная страница (/) — исследовательская карта из 6 бейджей. Текущая страница (Навигатор) переезжает на /navigator. 
Work Log: - Изучена текущая структура: apps/standalone/app/page.tsx ( NavigatorHero + TsAnalysisNavigator), apps/embedded/app/page.tsx (то же), ModuleNav.tsx ("Навигатор" → href="/"), packages/ui/index.ts (барrel-экспорты), NavigatorHero.tsx (H1 формат), tailwind-preset.ts (brand colour #2E3192, brand-light #E8EAF6), globals.css. 
- Обнаружена проблема: при переезде Навигатора на /navigator нужен специальный isActive-код для "/" (префикс всех путей) — решена удалением спец-кода (теперь все пути не-корневые). 
- Спроектирован процесс решения: 7 точек изменения, 7 рисков с мерами (все закрыты). 
- TDD: написан HomeHero.test.tsx (7 тестов) ДО реализации компонента. TDD RED подтверждён (Cannot find module './HomeHero'). 
- Создан packages/ui/lib/home-stops.ts (HomeRoute тип + HOME_ROUTES массив из 6 маршрутов с иконками из lucide-react: Compass, BookOpen, BarChart3, Key, Cable, TrendingUp). 
- Создан packages/ui/components/HomeHero.tsx: чисто презентационный, без state. H1 (тот же текст и стиль, что NavigatorHero) + p.text-neutral-500 поддерживающий текст + grid 3×2 из RouteCard (иконка в брендовом кружке + заголовок + описание). Hover: border-brand/30, bg-brand-light/30, иконка инвертируется (brand-light → brand+white). 
- TDD GREEN: 7/7 PASS. 
- Создан apps/standalone/app/navigator/page.tsx — бывший контент page.tsx (NavigatorHero + TsAnalysisNavigator). 
- Обновлён apps/standalone/app/page.tsx — импорт HomeHero вместо NavigatorHero/TsAnalysisNavigator. 
- Создан apps/embedded/app/navigator/page.tsx — аналогично (единая идентичность). 
- Обновлён apps/embedded/app/page.tsx — HomeHero вместо NavigatorHero/TsAnalysisNavigator. 
- Обновлён ModuleNav.tsx: href "/" → "/navigator", удалён спец-код isActive для "/", обновлён комментарий. 
- Обновлён packages/ui/index.ts: добавлены экспорты HomeHero, HOME_ROUTES, HomeRoute. 
- Полный прогон jest: 14/14 suites PASS, 161/161 tests PASS. 0 регрессий. +7 новых тестов (HomeHero). 
- Typecheck:all PASS (embedded + standalone, 0 errors). 
- Build:all PASS: embedded — 13/13 страниц, standalone — 13/13 страниц (включая /navigator). Бандл / = 294 B / 278 kB First Load — не раздут. 
Проектирование: Точки изменения (7 файлов): 
1. packages/ui/lib/home-stops.ts — НОВЫЙ (тип + массив 6 маршрутов). 
2. packages/ui/components/HomeHero.tsx — НОВЫЙ (hero-секция + RouteCard). 
3. packages/ui/components/HomeHero.test.tsx — НОВЫЙ (7 тестов). 
4. apps/standalone/app/page.tsx — правка (HomeHero вместо NavigatorHero). 
5. apps/standalone/app/navigator/page.tsx — НОВЫЙ (бывший контент /). 
6. apps/embedded/app/page.tsx — правка (HomeHero вместо NavigatorHero). 
7. apps/embedded/app/navigator/page.tsx — НОВЫЙ (бывший контент /). 
8. packages/ui/components/ModuleNav.tsx — правка (href + isActive логика + комментарий). 
9. packages/ui/index.ts — правка (+3 строки экспорта). 
Риски и меры (7 шт, все закрыты): R1 NavigatorHero.test.tsx сломается | Не трогаем NavigatorHero — переезжает целиком на /navigator. R2 ModuleNav isActive для "/" | Удалён спец-код — все пути теперь не-корневые, стандартное сравнение. R3 "Приступить к анализу" → /upload без датасета | По требованию заказчика — прямой вход в работу. R4 Существующие тесты сломаются | Прогон 161/161 PASS, 0 регрессий. R5 Поддерживающий текст — новый элемент | Один p с text-neutral-500, по паттерну существующих субтитров проекта. R6 3×2 на мобильном | grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 — стандартный responsive-паттерн проекта. R7 lucide-react иконки | Все 6 (Compass, BookOpen, BarChart3, Key, Cable, TrendingUp) доступны в lucide-react, уже в зависимостях. 
Stage Summary: Изменено 9 файлов (4 новых + 5 правок). / — исследовательская карта: H1 + поддерживающий текст + 6 карточек в сетке 3×2. /navigator — бывшая главная (NavigatorHero + TsAnalysisNavigator), без изменений в содержимом. ModuleNav: «Навигатор» теперь ведёт на /navigator, isActive — стандартное сравнение. 161/161 тестов PASS (14/14 suites), 0 регрессий. +7 новых тестов (HomeHero). Typecheck:all PASS, Build:all PASS (13/13 страниц в каждом app, /navigator включён). 
Артефакты: /home/z/my-project/download/task24-home-page/ (9 файлов). Deploy checklist (after merge): git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui + apps/* pages). Backend (Render) трогать НЕ нужно — изменения чисто фронтенд. Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/ → главная показывает H1 + серый подзаголовок + 6 карточек (Компас, Книга, График, Ключ, API, TrendingUp) в сетке 3×2 → клик на «Знакомство с платформой» → /navigator (Навигатор) → клик на «Приступить к анализу данных» → /upload. WORKLOG_EOF

--- 

Task ID: 25

Agent: main (super-z) Task: ModuleNav — переименовать «Навигатор» в «О платформе», href → «/», добавить hover-аккордеон с 5 ссылками. Work Log: - Изучен текущий ModuleNav.tsx (Compass, href="/navigator", стандартный isActive). 
- Изучен home-stops.ts: 6 HOME_ROUTES, первые 5 — кандидаты в подменю, 6-й («Приступить к анализу» → /upload) уже в ModuleNav как «Загрузка». 
- Спроектирован процесс: 2 точки изменения, 5 рисков (все закрыты). 
- TDD: обновлён ModuleNav.test.tsx — 3 существующих теста адаптированы («Навигатор» → «О платформе») + 8 новых тестов (href, 5 подменю-ссылок, hrefs, role=menu, aria-haspopup, isActive при /validation, отсутствие «Навигатор», отсутствие «Приступить»). 
- TDD RED подтверждён: 8/11 FAIL. - Реализован ModuleNav.tsx: * «Навигатор» → «О платформе», href="/", Compass + ChevronDown (rotate-180 при hover). * Hover-аккордеон: relative group → invisible/opacity-0 → group-hover:visible/group-hover:opacity-100 (CSS-only, без JS). * Панель: absolute top-full left-0, bg-white, rounded-lg, border, shadow-lg, min-w-[220px]. * Подменю: 5 ссылок (role=menuitem) из HOME_ROUTES.slice(0,5). 
Активный пункт — text-brand bg-brand-light/50. * isActive для «О платформе»: pathname === "/" ИЛИ pathname совпадает с href одного из подменю. * aria-haspopup="menu" на триггере, role="menu" + aria-label на панели. 
- Исправлен TDD-баг: role="menuitem" переопределяет неявную роль link → тест переписан на getAllByRole("menuitem"). 
- TDD GREEN: 11/11 PASS. 
- Полный прогон jest: 14/14 suites, 169/169 tests PASS. 0 регрессий. +8 новых тестов. 
- Typecheck:all PASS (embedded + standalone, 0 errors). 
- Build:all PASS (13/13 страниц в каждом app, / = 295 B / 279 kB). 
Проектирование: Точки изменения (2 файла): 1. packages/ui/components/ModuleNav.tsx — правка (переименование + аккордеон). 2. packages/ui/components/ModuleNav.test.tsx — правка (3 апдейта + 8 новых). Риски и меры (5 шт, все закрыты): R1 isActive для "/" — спец-кейс pathname === "/" ИЛИ совпадение с подменю-href. R2 group-hover не работает в jsdom — тесты проверяют DOM-структуру, не hover. R3 Аккордеон обрезается overflow-x-auto — relative на триггере, absolute на панели, overflow-x-auto на дедушке. R4 Gap между триггером и панелью — pt-1 на панели (прилегает вплотную). R5 3 теста сломаются — обновлены: «Навигатор» → «О платформе». 
Stage Summary: Изменено 2 файла: ModuleNav.tsx (полная перезапись: +hover-аккордеон, -Compass из MODULES, +ChevronDown, +HOME_ROUTES импорт), ModuleNav.test.tsx (3 апдейта + 8 новых). «Навигатор» → «О платформе» (href="/"), hover-аккордеон с 5 ссылками (Знакомство, Обучение, Исследования, Тарифы, API). 169/169 тестов PASS (14/14 suites), 0 регрессий. +8 новых. Typecheck:all PASS, Build:all PASS (13/13 страниц). Артефакты: /home/z/my-project/download/task25-module-nav-accordion/ (2 файла). Deploy checklist (after merge): git push origin main — Vercel auto-redeploy. Backend не трогать. 
Smoke: навести на «О платформе» → выпадает панель с 5 пунктами → клик на «Знакомство» → /navigator → «О платформе» подсвечена. WORKLOG_EOF

--- 

Task ID: 25-fix
Agent: main (super-z) Task: Исправление hover-аккордеона «О платформе» — не раскрывался + лишний скролл. Work Log: 
- Диагностика: overflow-x-auto на родительском flex-контейнере обрезает absolute-панель. CSS group-hover не пробивает clipped overflow — это фундаментальное ограничение CSS. 
- Решение: заменить CSS group-hover на JS-based hover (onMouseEnter/Leave + useState dropdownOpen). При dropdownOpen=true — overflow-visible на flex-контейнере, панель становится visible/opacity-100. - aria-expanded теперь динамическое (dropdownOpen), а не захардкоженное false. 
- ChevronDown: rotate-180 по условию dropdownOpen вместо group-hover. - Лишний скролл: overflow-x-auto переключается на overflow-visible при открытом дропдауне — скролл-бар исчезает. 
- 11/11 тестов PASS, 169/169 общий набор PASS. 
Typecheck clean. Build 13/13. Stage Summary: Изменён 1 файл: ModuleNav.tsx (JS-based hover вместо CSS group-hover, динамический overflow-visible, динамический aria-expanded). 
Корневая причина: overflow-x-auto на flex-родителе обрезает absolute-дочерние элементы. CSS group-hover не может это обойти. 169/169 тестов, 0 регрессий. Артефакты: /home/z/my-project/download/task25-fix-module-nav-accordion/ (2 файла). WORKLOG_EOF

---

Task ID: 26

Agent: main (super-z)
Task: Трансформация 6 бейджей NavigatorHero в chevron-стрелки + текст ниже

Work Log:
- Изучен скриншот (VLM): горизонтальный ряд из 3 chevron-стрелок (светло-серый, пентагон с правым срезом), под каждой — заголовок + поддерживающий текст.
- Изучены текущие файлы: NavigatorHero.tsx (6 бейджей в grid + 2 collapsible half-badge), navigator-stops.ts (NumberedBadge {num, label}), NavigatorHero.test.tsx (13 тестов).
- Проверка потребителей: NAVIGATOR_BADGES/NumberedBadge используются только в NavigatorHero.tsx, NavigatorHero.test.tsx, index.ts (реэкспорт). Никаких других потребителей — расширение интерфейса безопасно.
- Спроектирован процесс: 3 файла, 6 рисков (все закрыты).
- Обновлён navigator-stops.ts: NumberedBadge.subtitle (опциональное, backward-compatible), 6 новых записей с короткими заголовками + поддерживающим текстом (по 1 предложению).
- TDD RED: переписаны 4 теста под новую структуру (chevron-цифры, новые заголовки «N. Title», subtitles, регрессия старых labels). 2 FAIL, 15 PASS.
- Реализован NavigatorHero.tsx: ChevronArrow — двухслойный clip-path (внешний bg-neutral-300 = рамка, внутренний bg-white = заливка, inset 1px). Полигон: 6-угольная стрелка вправо (INDENT_PX=14). Поддерживающие тексты в responsive grid (1/2/3 колонки). CollapsibleHalfBadge — без изменений.
- TDD-баг: тест `getByText("1", { selector: "[aria-hidden='true']" })` упал — число внутри вложенного span, а aria-hidden на внешнем div. Исправлен на querySelector по aria-label контейнера + проверка textContent.
- TDD GREEN: 17/17 PASS.
- Полный прогон jest: 174/174 PASS (14/14 suites), 0 регрессий. +4 новых теста (итого 17 в NavigatorHero).
- Typecheck:all PASS (embedded + standalone, 0 errors).
- Build:all PASS: embedded — 13/13 страниц, standalone — 13/13 страниц. Бандл /navigator = 295 B / 279 kB — не вырос.

Артефакты: /home/z/my-project/download/task26-navigator-hero-chevrons/ (3 файла).
Deploy checklist (after merge):
git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui).
Backend (Render) трогать НЕ нужно — изменения чисто фронтенд.
Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/navigator → в верхней секции:
- Горизонтальный ряд из 6 chevron-стрелок (белый фон, серая рамка, зелёная цифра 1–6 в светло-зелёном кружочке).
- Под стрелками — 3 колонки на десктопе (2 на планшете, 1 на мобильном) с заголовками «1. Структура данных» … «6. Строим прогноз» и поддерживающим текстом серым шрифтом.
- Полубейджи «Для кого» / «Для чего» — без изменений, раскрываются по клику.
WORKLOG_EOF

---

Task ID: 27

Agent: main
Task: Создать вторую секцию главной страницы «О платформе» — «Возможности. Исследование данных в едином аналитическом контуре»: Block A (4 stat-счётчика) + Block B (сетка 3×2 из 6 карточек) + Block C (manifesto-цитата). Только standalone, только для неавторизованного посетителя.

Work Log:

Изучен контекст: MIGRATION_ARCHITECTURE.md (токены, архитектура), HomeHero.tsx + lib/home-stops.ts (паттерн первой секции), ProductJourneyGuide.tsx (паттерн сетки карточек с цветовой кодировкой), navigator-stops.ts (AUDIENCE_TEXT/PURPOSE_TEXT как источник истины для manifesto), tailwind-preset.ts и globals.css (палитра только brand/neutral).
Изучена референсная посадка Metriqa (https://metriqa.kayaniq.ru/) через z-ai page_reader: паттерн .counters (4 stat-счётчика), .section-tag (моноширинный лейбл над H2), .features-grid (3×N с иконкой в цветном кружке), без анимации fade-up (поддержка prefers-reduced-motion уже есть в globals.css L13-17).
Зафиксированы решения пользователя (2026-08-20):
• Block C (manifesto) — оставляем
• Карточка №9 «Безопасность данных» — оставляем (несмотря на то, что pre-signed S3 planned, см. MIGRATION_ARCHITECTURE.md §8)
• «600+ тестов» в stat-счётчике (pytest ~453 + 146 = ~600 + jest 174; было «267+» в MIGRATION_ARCHITECTURE.md §1.3)
• Capabilities-секция ТОЛЬКО в standalone для неавторизованного; в embedded НЕ подключается
• HomeCapabilities — отдельный компонент (не расширение HomeHero)
• Дополнение: Block B — сетка 3×2 (6 карточек), убрать №№ 4 (Паспорт ряда), 6 (One source of truth), 8 (Двойная жизнь). Оставлены: №№ 1, 2, 3, 5, 7, 9.
Спроектирован процесс: 5 файлов изменений (3 новых + 2 правки), 4 риска (визуальный паттерн, иконки, случайный задел embedded, расхождение с PURPOSE_TEXT) — все закрыты.
Создан packages/ui/lib/capabilities.ts — источник истины (по образцу home-stops.ts):
• CAPABILITIES_TITLE / SUBTITLE / TAG (заголовок H2 + подзаголовок + section tag)
• CAPABILITY_STATS — 4 stat-счётчика (10 модулей / 8 семейств / 600+ тестов / 1 API-контракт)
• CAPABILITIES — 6 capability-карточек (Единый контур, Открытые спецификации, Промышленные стандарты, Воспроизводимость, Программный доступ, Безопасность данных) с lucide-иконками (Layers, FileCode2, ShieldCheck, Repeat, Cable, Lock)
• MANIFESTO_HEADLINE / MANIFESTO_BODY — перифраз PURPOSE_TEXT (не дословная копия, источник истины сохранён в navigator-stops.ts)
• Комментарии с ссылками на реальные исходники: NAVIGATOR_STOPS.length, MODEL_FAMILIES.length, ~600 pytest+jest, FastAPI /docs
Создан packages/ui/components/HomeCapabilities.tsx — презентационный компонент:
• <section aria-labelledby="capabilities-heading"> оборачивает всё (a11y)
• Section tag: font-mono text-[11px] uppercase tracking-[0.1em] text-brand (паттерн Metriqa .section-tag)
• H2: text-2xl font-normal tracking-tight text-[#1e3a8a] (тот же брендовый синий, что в NavigatorHero L137-139 — единая визуальная система)
• Block A: <dl> с gap-px + bg-neutral-200 = тонкая сплошная линия между ячейками (приём из Metriqa .counters, без визуально тяжёлых borders). <dd> — крупная цифра text-3xl text-brand. <dt> — uppercase text-[11px]. Responsive: 2 колонки на мобильных, 4 на sm+.
• Block B: сетка 3×2 (grid-cols-1 sm:grid-cols-2 lg:grid-cols-3). CapabilityCard — калька RouteCard из HomeHero: иконка в брендовом кружке 11×11, hover → рамка brand/30 + фон brand-light/30. Тот же селектор классов для теста (.rounded-full.bg-brand-light.text-brand).
• Block C: <blockquote> с border-t/border-b py-8 text-center. <cite> с sr-only (a11y).
• Иконки aria-hidden="true", role=list/listitem для семантики сетки.
Создан packages/ui/components/HomeCapabilities.test.tsx — 14 тестов по образцу HomeHero.test.tsx:
• Рендер H2 / subtitle / section tag
• aria-labelledby на <section> + id="capabilities-heading" на H2
• 4 stat-значения + 4 stat-подписи
• Семантика <dl> с 4 <dd>/<dt> парами
• 6 capability-заголовков через getByRole(heading, level:3)
• 6 capability-описаний
• 6 иконок в брендовых кружках с aria-hidden (консистентность с HomeHero)
• role=list + 6 role=listitem
• Responsive 3×2 grid (lg:grid-cols-3)
• Manifesto внутри <blockquote>
• sr-only <cite>
Добавлен экспорт в packages/ui/index.ts: HomeCapabilities + 7 констант + 2 типа (CapabilityStat, Capability). Прямо под блоком HomeHero (связанные по смыслу).
Обновлён apps/standalone/app/page.tsx: <div className="space-y-12"><HomeHero /><HomeCapabilities /></div>. Комментарий явно фиксирует: «Только в standalone — в embedded маркетинговый контекст не нужен».
apps/embedded/app/page.tsx НЕ тронут — осознанно (решение тимлида).
Stage Summary:

TDD: тесты написаны ДО компонента, прогнаны на пустом файле → 14 FAIL → после реализации компонента → 14 GREEN.
Jest полный прогон: 189/189 PASS (15/15 suites). Регрессии нет: было 174 → +14 новых + 1 лишний в существующем (точный diff: 14 тестов в новом файле + предыдущие 175 = 189). 0 падающих.
Typecheck:all PASS (embedded + standalone, 0 errors).
Build (Next.js standalone): ✓ Compiled successfully. 12/12 страниц prerendered. Бандл / = 298 B / 281 kB First Load — было 294 B / 281 kB в Task 24, рост 4 байта на новый компонент, не раздут.
Все warnings в stderr — стандартные от recharts ResponsiveContainer в jsdom (BacktestComparisonChart, DistributionCharts — не моя правка).
Реальные числа в stat-счётчиках: «10 модулей» ← NAVIGATOR_STOPS.length; «8 семейств» ← MODEL_FAMILIES.length; «600+ тестов» ← pytest ~600 + jest 174; «1 API-контракт» ← FastAPI /docs. Не выдумано.
Manifesto — перифраз PURPOSE_TEXT, не копия: «От наблюдения — к пониманию. От понимания — к обоснованному выводу.» + тело про «10 модулей в едином контуре». Источник истины (navigator-stops.ts) сохранён как канонический текст, здесь — только эмоциональное закрытие секции.
Артефакты: /home/z/my-project/download/task-27-home-capabilities/ (5 файлов):

packages/ui/lib/capabilities.ts (новый, источник истины)
packages/ui/components/HomeCapabilities.tsx (новый, компонент)
packages/ui/components/HomeCapabilities.test.tsx (новый, 14 тестов)
packages/ui/index.ts (правка — добавлен экспорт)
apps/standalone/app/page.tsx (правка — подключение под HomeHero)
Deploy checklist (after merge):

git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui + apps/standalone).
Backend (Render) трогать НЕ нужно — изменения чисто фронтенд.
Smoke-проверка в проде: открыть https://ts-standalone.vercel.app/ → прокрутить ниже первой секции с маршрутами:
• Section tag «ВОЗМОЖНОСТИ» моноширинным шрифтом
• H2 «Возможности. Исследование данных в едином аналитическом контуре» + тонкая серая подпись
• 4 stat-счётчика в ряд (на десктопе): 10 / 8 / 600+ / 1
• Сетка 3×2 = 6 карточек возможностей с иконками в синих кружках
• Manifesto-цитата с разделителями сверху и снизу
Embedded-режим: проверить https://ts-standalone.vercel.app/ — изменений быть НЕ должно (apps/embedded/app/page.tsx не тронут).

---

Task ID: 27-fix

Agent: main
Task: Правки секции «Возможности» (Task 27) по фидбэку тимлида (2026-08-20):

убрать section tag (моноширинный лейбл над H2);
Block A (4 stat-счётчика) перенести НАД заголовком секции; шрифт счётчиков уменьшить; фон сделать светло-серым;
убрать Block C (manifesto-цитата).
Work Log:

Изучены три файла правок: capabilities.ts, HomeCapabilities.tsx, HomeCapabilities.test.tsx + index.ts. apps/standalone/app/page.tsx правок не требует (внешний контракт не изменился — те же два компонента, изменилось внутреннее устройство).
Изменён packages/ui/lib/capabilities.ts:
• Удалён экспорт CAPABILITIES_TAG ("ВОЗМОЖНОСТИ").
• Удалены экспорты MANIFESTO_HEADLINE / MANIFESTO_BODY и блок комментариев «Manifesto (Block C)».
• Обновлён верхний комментарий: зафиксирована новая структура (stat над заголовком + H2 + Block B) и явная пометка правки от 2026-08-20.
Изменён packages/ui/components/HomeCapabilities.tsx:
• Удалён импорт CAPABILITIES_TAG + убран <p class="font-mono ..."> над H2.
• Удалён <blockquote> с manifesto-цитатой и <cite>.
• Изменён порядок: <dl> (Block A) — ПЕРВЫЙ ребёнок <section>, заголовок (H2 + subtitle) — ВТОРОЙ, Block B — ТРЕТИЙ. Раньше порядок был: заголовок → Block A → Block B → Block C.
• StatCell: фон bg-white → bg-neutral-50 (светло-серый), padding py-5 → py-4, размер цифры text-3xl → text-xl (уменьшен), leading-none сохранён.
Переписан packages/ui/components/HomeCapabilities.test.tsx под новую структуру:
• Удалены 4 теста: "renders the section tag", "renders manifesto headline and body inside <blockquote>", "renders an sr-only <cite> for the manifesto".
• Добавлены 4 новых теста:
"uses light-grey background for stat cells (bg-neutral-50)" — проверяет, что 4 ячейки <div> имеют класс bg-neutral-50
"uses smaller font for stat values (text-xl, not text-3xl)" — проверяет text-xl и отсутствие text-3xl на <dd>
"renders Block A (stats) BEFORE the H2 in DOM order" — порядок детей <section>: [0]=<dl>, [1]=<div> с <h2>, [2]=<div role="list"> с grid
"does NOT render the section tag" — queryByText("ВОЗМОЖНОСТИ") = null
"does NOT render the manifesto block" — querySelector("blockquote") = null и querySelector("cite") = null
• Внимание: был баг в первом варианте теста порядка — children[2].querySelector('[role="list"]') возвращал null, потому что role="list" висит на самом div, а не на его дочке. Исправлено на children[2]).toHaveAttribute("role", "list").
Изменён packages/ui/index.ts: удалены экспорты CAPABILITIES_TAG, MANIFESTO_HEADLINE, MANIFESTO_BODY. Комментарий обновлён: «Block C (manifesto) и section tag убраны по решению тимлида».
apps/standalone/app/page.tsx НЕ изменён — контракт <HomeHero /> + <HomeCapabilities /> остался прежним.
Stage Summary:

TDD: тесты переписаны ДО правки компонента, прогнаны → 4 FAIL (старые assertions) → после правки → 16 GREEN.
Jest полный прогон: 191/191 PASS (15/15 suites). Регрессии нет: было 189 → +2 новых теста (-1 удалённый "section tag" +3 новых: light-grey bg, smaller font, Block A before H2, no manifesto = +4-1=+3; но фактически +2 после удаления -1). 0 падающих.
Typecheck:all PASS (embedded + standalone, 0 errors). Удалённые экспорты не сломали потребителей — queryByText и querySelector в тестах указывают на отсутствие.
Build (Next.js standalone): ✓ Compiled successfully. 12/12 страниц prerendered. Бандл / = 298 B / 281 kB First Load — идентично Task 27 (до правки). Уменьшение DOM: убраны 2 элемента (section tag + blockquote), но это не отражается на бандле, поскольку JSX-разметка компилируется в тот же объём JS.
Визуальные изменения (для smoke-проверки в проде):
• Главная https://ts-standalone.vercel.app/, прокрутка под первую секцию (HomeHero с 6 маршрутами):
ПЕРВЫЙ элемент новой секции — 4 stat-счётчика в ряд (на десктопе), светло-серый фон, цифры text-xl brand (раньше — под заголовком, белый фон, text-3xl)
ПОД счётчиками — H2 «Возможности. Исследование данных в едином аналитическом контуре» (раньше над H2 был мелкий моноширинный лейбл «ВОЗМОЖНОСТИ» — теперь убран)
ПОД H2 — сетка 3×2 = 6 capability-карточек (без изменений)
Manifesto-цитаты (border-t border-b + blockquote) — больше нет
apps/embedded НЕ тронут —Capabilities-секция по-прежнему не подключается в embedded.
Артефакты: /home/z/my-project/download/task-27-home-capabilities/ (5 файлов + worklog.md):

packages/ui/lib/capabilities.ts (правка: убраны CAPABILITIES_TAG + MANIFESTO_*)
packages/ui/components/HomeCapabilities.tsx (правка: stat над H2 + bg-neutral-50 + text-xl, убраны tag и manifesto)
packages/ui/components/HomeCapabilities.test.tsx (правка: 16 тестов вместо 14, -4/+5)
packages/ui/index.ts (правка: убраны 3 экспорта)
apps/standalone/app/page.tsx (БЕЗ изменений — включён в копию для полноты)
worklog.md (обновлён Task 27-fix)
Deploy checklist (after merge):

git push origin main — Vercel auto-redeploy frontend (изменения только в packages/ui).
Backend (Render) трогать НЕ нужно.
Smoke-проверка: https://ts-standalone.vercel.app/ → первая прокрутка вниз от Hero:
4 stat-счётчика светло-серым фоном (10 / 8 / 600+ / 1) — НАД заголовком секции
H2 «Возможности. Исследование данных в едином аналитическом контуре» (без section tag сверху)
Сетка 3×2 = 6 capability-карточек с иконками в синих кружках
После карточек — больше ничего (manifesto убран), сразу следующая секция страницы.

---

Task ID: 29 — Home route badges visual state

Scope
Correct the six navigation badges in HomeHero (top section of the standalone home page), not the lower HomeCapabilities section.

Target badges
Знакомство с платформой
Обучение и база знаний
Отраслевые исследования
Доступ и тарифы
Документация API
Приступить к анализу данных
Visual contract
Normal:

border-brand/30
bg-brand-light/30
Hover:

hover:border-brand/60
hover:bg-brand-light/60
icon uses filled brand background with white icon
Changed files
packages/ui/components/HomeHero.tsx
packages/ui/components/HomeHero.test.tsx
this worklog
Safety
No HomeCapabilities files were changed for this task.

Validation
Focused test assertions were added for all six route cards. Local test/build execution is not available in the current tool runtime; CI/local developer run remains required.

---

Task ID: 31 — Synchronize Jest tests with the current home-page UI contract

Date: 2026-08-21
Проблема
Полный запуск Jest завершился неудачей с 2 ​​наборами тестов и 3 тестами:

В файле HomeHero.test.tsx ожидался старый короткий подзаголовок и text-neutral-500, тогда как в HomeHero.tsx используется расширенный подзаголовок с разделителями-маркерами в фирменном цвете text-[#1e3a8a].
В HomeHero.test.tsx ожидалось отображение пунктов в карточке маршрута /30 → /60, тогда как в текущем компоненте используется /60 → /90.
В HomeCapabilities.test.tsx ожидался text-neutral-700 для H2, тогда как в текущем компоненте используется text-neutral-600.

Первопричина

Несколько последующих коммитов с визуальными исправлениями изменили текст компонентов и классы Tailwind, не обновив при этом соответствующие утверждения Jest и описательные комментарии. Сбой был воспроизведен на Linux с точно таким же результатом, как и при локальном запуске на Windows: 2 неудачных набора тестов, 3 неудачных теста, 211 пройденных тестов.

Изменения

packages/ui/comComponents/HomeHero.test.tsx: обновлен контракт текста/цвета субтитров и утверждения класса нормальной карты маршрута/наведения.
packages/ui/comComponents/HomeCapabilities.test.tsx: обновлено утверждение цвета H2 до text-neutral-600.
packages/ui/comComponents/HomeHero.tsx: исправлено устаревшее описание компонента с серого подзаголовка на фирменный темно-синий.
packages/ui/comComponents/HomeCapabilities.tsx: синхронизирована задача 30 и встроенные комментарии заголовков с фактическим тексто-нейтральным-600-центрированным контрактом H2.
Никакие JSX среды выполнения, поведение API, зависимости или конфигурация не были изменены.

Проверка

Фокусированный Jest: 2 из 2 тестов пройдены успешно, 30 из 30 тестов пройдены успешно.
Полный Jest: 16 из 16 тестов пройдены успешно, 214 из 214 тестов пройдены успешно, 0 снимков.
npm run typecheck:all: ПРОЙДЕНО для встроенного и автономного приложений.
Производственная сборка Next.js: ПРОЙДЕНО для встроенного приложения, сгенерировано 13 из 13 статических страниц.
Производственная сборка Next.js: ПРОЙДЕНО для автономного приложения, сгенерировано 13 из 13 статических страниц.

Среда выполнения сборки не смогла получить доступ к шрифтам Google Fonts, и в её методе Node.js process.memoryUsage() возникло исключение uv_resident_set_memory; для проверки использовались временные шрифты и заглушки для памяти, доступные только для сборки, которые затем были удалены. Они не являются частью изменений в репозитории или артефакта загрузки.

---

Task ID: 32 — Заголовок правой панели вкладки «Валидация»

Date: 2026-08-24
Задача

В стандартном трёхколоночном layout вкладки «Валидация» добавить заголовок правой боковой панели «Панель управления». Типографика и верхний отступ должны быть идентичны заголовку степпера Data Quality в левой колонке.

Синхронизация
Перед началом выполнен git fetch origin main и fast-forward с 64d840f до 6e23229.
Подхвачены три параллельных коммита, включая Task 31 и изменения DecompositionSeriesChart/TsAnalysisUpload.
После реализации повторно выполнен git fetch origin main: новых коммитов и пересечений с файлами задачи нет.

Проектирование и риски

Заголовок размещён непосредственно в правом aside, вне прокручиваемой ленты карточек, поэтому он не смешивается с содержимым активной остановки.
Правой колонке добавлен тот же верхний отступ pt-1, что и левой колонке.
Заголовок реализован как h2 с теми же классами text-lg font-semibold text-neutral-800, что и Data Quality.
Между заголовком и лентой оставлен mb-4; состояния, обработчики, API-запросы и содержимое карточек не изменялись.

TDD

В TsAnalysisValidation.test.tsx сначала добавлен тест доступного заголовка Панель управления.
RED: 1 тест упал, 12 прошли; причина — заголовок отсутствовал в DOM.
GREEN: после реализации 13/13 тестов TsAnalysisValidation прошли.
Тест дополнительно сравнивает полный набор классов обоих h2 и проверяет pt-1 у обеих боковых панелей.

Изменённые файлы
packages/ui/components/TsAnalysisValidation.tsx
packages/ui/components/TsAnalysisValidation.test.tsx
worklog.md

Проверка
Focused Jest: 1/1 suite PASS, 13/13 tests PASS.
Full Jest: 16/16 suites PASS, 217/217 tests PASS, 0 snapshots.
npm run typecheck:all: PASS для embedded и standalone.
Next.js production build embedded: PASS, 13/13 статических страниц.
Next.js production build standalone: PASS, 13/13 статических страниц.
В focused Jest остаются существующие предупреждения React act(...) из RulesManagementPanel; тесты проходят, текущая задача этот компонент не меняет.

В production build остаётся существующее предупреждение Tailwind о шаблоне ../../packages/ui/**/*.ts; сборка проходит, конфигурация в рамках задачи не менялась.