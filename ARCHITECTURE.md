# CISStat TS Analysis — Архитектура проекта

## Текущая структура (Legacy)
- app.py (16000+ строк) — монолитное Streamlit-приложение
- validation/ — модули валидации
- src/catalog/ — рекомендатель моделей

## Целевая структура (Refactored)
app/
├── main.py # Точка входа Streamlit
├── core/ # Бизнес-логика, метрики, состояние
│   ├── state.py # Типизированный AppState
│   ├── metrics.py # calculate_ts_passport, _calc_ts_props
│   └── constants.py # Константы, конфиги
├── data/ # Загрузка данных
│   ├── loader.py # read_uploaded_file, init_db_connection
│   └── detectors.py # robust_datetime_detector
├── validation/ # Валидация (перенос из корня)
│   ├── pipeline.py # run_validation_pipeline
│   └── ui/ # UI-компоненты валидации
├── preprocessing/ # Трансформации данных
│   ├── transforms.py # apply_differencing, apply_scaling
│   └── ui/ # UI предобработки
├── eda/ # Разведочный анализ
│   ├── spectral.py # FFT, Wavelet, ACF
│   ├── ih_analysis.py # IH-анализ
│   └── ui/ # UI EDA
├── modeling/ # Моделирование и прогнозирование
│   └── ui/ # UI моделирования
├── ui/ # Переиспользуемые UI-компоненты
│   ├── components.py # make_card, show_comparison_table
│   ├── styles.py # CSS стили
│   ├── auth.py # Авторизация
│   └── tabs/ # Код конкретных вкладок
│       ├── download.py
│       ├── validation.py
│       ├── preprocessing.py
│       ├── exploratory.py
│       ├── modeling.py
│       ├── forecasting.py
│       └── tasks.py
└── utils/ # Утилиты
    ├── logging.py # add_log, error handling
    └── helpers.py # Вспомогательные функции

## Потоки данных
1. **Загрузка** → `AppState.df`, `col_types`, `ts_mode_active`
2. **Валидация** → `AppState.val_results`, `validation_ready`
3. **Предобработка** → трансформации df, сохранение параметров
4. **EDA/Моделирование** → чтение из `AppState`, визуализация

## Ключевые сущности
- `AppState.df` — основной DataFrame
- `AppState.val_results` — dict результатов валидации (20+ ключей)
- `AppState.ts_props_v10/v11/v12` — паспорта свойств ряда
- `AppState.primary_date_col` — временная колонка
- `AppState.col_types` — типы колонок {num, cat, date}

## Ключевые правила рефакторинга
1. Не менять наблюдаемое поведение без явного указания
2. Сначала выносим бизнес-логику в `core/`, потом UI в `ui/tabs/`
3. Все изменения состояния проходят через типизированный `AppState`
4. Сохраняем обратную совместимость через wrapper в `app.py`

## Этапы рефакторинга
### Этап 1: Подготовка и безопасность (1-2 дня)
- [x] Создание структуры пакетов
- [x] Описание архитектуры
- [ ] Написание интеграционных тестов

### Этап 2: Вынесение бизнес-логики (3-5 дней)
- [ ] Создание app/core/state.py (AppState)
- [ ] Перенос calculate_ts_passport() в app/core/metrics.py
- [ ] Создание app/data/loader.py
- [ ] Создание app/validation/pipeline.py

### Этап 3: Разбиение app.py по вкладкам (5-7 дней)
- [ ] Создание app/ui/components.py (переиспользуемые компоненты)
- [ ] Перенос вкладки "Загрузка" в app/ui/tabs/download.py
- [ ] Перенос вкладки "Валидация" в app/ui/tabs/validation.py
- [ ] Перенос вкладки "Предобработка" в app/ui/tabs/preprocessing.py
- [ ] Перенос вкладки "Разведочный EDA" в app/ui/tabs/exploratory.py
- [ ] Перенос вкладки "Моделирование" в app/ui/tabs/modeling.py

### Этап 4: Устранение дублирования (2-3 дня)
- [ ] Удаление дубликатов функций
- [ ] Создание app/core/transforms.py
- [ ] Унификация стратегий обработки

### Этап 5: Улучшение управления состоянием (2 дня)
- [ ] Использование AppState вместо сырого session_state
- [ ] Добавление валидации переходов
- [ ] Механизм очистки устаревших данных

### Этап 6: Добавление типизации и документации (3-4 дня)
- [ ] Добавление type hints
- [ ] Создание dataclasses для результатов
- [ ] Документирование архитектуры

### Этап 7: Оптимизация производительности (2-3 дня)
- [ ] Улучшение кэширования
- [ ] Lazy loading для тяжёлых вычислений
- [ ] Оптимизация пересчёта масок

### Этап 8: Тестирование и CI (2-3 дня)
- [ ] Unit-тесты для бизнес-логики
- [ ] Интеграционные тесты
- [ ] Настройка CI/CD
