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