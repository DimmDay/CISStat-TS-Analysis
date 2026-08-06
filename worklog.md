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
