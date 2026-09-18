# CISStat TS Analysis — Worklog

---

## Task ID: TASK-145 (2026-09-17) — Калибровка soft_min_observations по первым реальным бэктестам (50/40 → 60/60)

Синхронизация: main@1ed4a1d (Task 144), рабочее дерево чистое (незакоммичен
только онбординг-запись worklog6). Постановка тимлида: значения 50/40 —
стартовые (открытый вопрос Task 144), пересмотреть по первым реальным
бэктестам тем же порядком, что IQR-множитель и окна дрейфа; по результатам —
ZIP в download.

### Метод (парный end-anchored sliding на каноническом движке)

- scripts/task145/soft_calibration.py: для каждого n строится план с
  ФИКСИРОВАННЫМИ тестовыми окнами (последние K=4 окна ряда, одни для всех n),
  train = n наблюдений непосредственно перед окном; h=6 (месячные m=12) /
  h=7 (дневные m=7), gap=0, strategy="sliding". Тестовая масса при любом n
  одинакова => разница MASE объясняется ТОЛЬКО размером истории (парный
  дизайн; наивный sweep-вариант дал зашумлённые кривые и был заменён).
- Исполнение — run_backtest_plan + MODEL_EXECUTION_REGISTRY (tbats /
  random_forest / xgboost / lightgbm / catboost, runtime_available=True),
  без injected predictors — те же пути кода, что у бэктеста пользователя.
- Сетка n: от 2m до min(L-4h, 196), шаг 6/14; 93 точки x 5 моделей, кэш
  scripts/task145/soft_calibration_cache*.json (дозапуск продолжает).
- Данные — ТОЛЬКО реальные ряды платформы (10 рядов): golden value +
  2 ковариаты (110 мес., сертифицированный fixture), демо FC-MON-2
  (147 мес.), 5 регионов энергии (60 мес. — короткий кейс), retail (730 дн.),
  finance close (500 дн., случайное блуждание). Демо-CSV извлечены
  НАСТОЯЩИМИ генераторами платформы (node --experimental-strip-types поверх
  packages/ui/lib/demoDatasets.ts; scripts/task145/extract_demo.mjs).
- Критерий: мягкий гейт живёт в [soft, 100), поэтому оценивается СРЕДНЯЯ
  относительная деградация по оставшейся части окна:
  n*(gamma) = min n0: mean_{n' in [n0,96]} D(n') <= gamma И
  max_{s,n'} d_s(n') <= 1.5 (гвард от катастрофы), где D(n) = среднее по
  рядам MASE_s(n)/MASE_s(n_ref). Оконное среднее выбрано после того, как
  критерий «все последующие точки <= gamma» показал нечувствительность к
  сигналу на шумах одиночных fit'ов (±20-30% между соседними n при 4 окнах).
  Головной gamma=1.10, чувствительность {1.05, 1.20}.

### Результат калибровки

- Группы Task 144 (каждая пара (модель, ряд) — независимая кривая внутри
  pooled-критерия): tbats raw=66, tree_ml raw=66 при gamma=1.10; gamma=1.05 —
  нет решения (шум-пол), gamma=1.20 — 66.
- Отгружено 60/60 (округление ВНИЗ до кратного 10): порог-предупреждение —
  лучше предупредить, чем заблокировать; механические 70 молча убили бы
  мотивирующий кейс Task 144 (Month_Value_1.csv, n=64). Средняя деградация
  в отгруженном окне [60,96]: tbats 1.112, tree_ml 1.008.
- По моделям справочно (разброс — шум фитов): rf 54, xgb 66, lgbm 48,
  catboost 30. Кривые: docs/task145_soft_history_calibration_results.json.
- Смещение стартовых значений: tree_ml 40 -> 60 (+50%) — стартовое было
  оптимистично (полоса деградации 1.05-1.15 на [40,96], точечно 1.36 на
  дневных n=28); tbats 50 -> 60 (+20%). Честный отказ catboost при
  n < warm-up (n_lags=7+1) зафиксирован как данные калибровки.

### TDD (AGENTS.md: RED -> GREEN)

- RED (подтверждён ДО правки YAML, ровно 3 падения): tests/test_modeling_spec.py
  ::test_soft_min_matches_task145_calibration_report (НОВЫЙ: YAML ==
  group_recommendation отчёта == 60/60, фиксация вердикта),
  ::test_spec_loads (1.3.0 -> 1.3.1), tests/api/test_param_space.py
  ::test_spec_loads_without_errors (там же).
- Динамизация пинов (проходят при любом значении порога, читают из spec):
  test_soft_history_window_is_not_recommended_not_not_applicable,
  test_soft_history_floor_below_soft_min_stays_not_applicable,
  test_soft_history_boundary_at_soft_min_is_not_recommended (tbats/rf —
  soft из спецификации вместо литералов 50/40);
  tests/unit/test_eda_model_matrix.py::test_soft_history_boundary_at_soft_min_is_attention
  (размер фрейма = soft+4 из spec вместо литерала 44);
  tests/unit/test_model_readiness_candidates.py (soft_specs из spec).
- GREEN: rules/modeling.yaml — 5 x soft_min_observations: 60 (комментарии
  блоков обновлены), metadata.version 1.3.0 -> 1.3.1 (только данные,
  семантика движка прежняя). Затронутый контур 99/99.
- Мутационный раннер scripts/task144_mutations.py: M20/M21 переписаны под
  новые паттерны (soft 60 -> 59 tbats; random_forest 60 -> 99 по уникальному
  контексту), прогон: 21/21 KILLED, 0 SURVIVED, restore sha256 verified.

### Верификация (полная регрессия)

- Backend: полный pytest tests/ — 2337 passed / 9 failed / 3 errors /
  24 skipped. ВСЕ 9+3 падений доказаны предсущественными stash-прогоном на
  чистом HEAD 1ed4a1d: нейро-группа не установлена (integration-paths
  deepar/lstm/nbeats/nhits/tft fail-closed, v2-дескрипторы, neural capacity,
  catalog_only-метрики) + 3 snapshot-ошибки test_preprocessing (версия
  pandas/numpy venv против пина). Ни одного падения от правок Task 145.
- Среда: доустановлены prophet 1.4.0, arch 8.0.0, pandera, PyWavelets,
  holidays, missingno, openpyxl, plotly, ruptures (venv доведён до
  core-профиля Task 144: без нейро-группы, прецедент R6).
- Санити движка: n=59 -> F04 NOT_APPLICABLE; n=60 -> D07 NOT_RECOMMENDED
  (граница включительна); n=64 (Month_Value) -> D07 — кейс СОХРАНЁН;
  n=100 -> D05 (правая граница); lstm n=64 -> F04 — нейро не тронуты.
- Frontend не затронут (UI не содержит литералов 50/40: тип soft-поля и
  счётчик 24 правила — без изменений); jest/build не перегонялись.

### Артефакты

- docs/task145_soft_history_calibration.md — отчёт (метод, данные, кривые,
  gamma-чувствительность, обоснование 60 вместо 70, ограничения, воспроизведение).
- docs/task145_soft_history_calibration_results.json — сырые кривые по всем
  (модель, ряд, n) + рекомендации.
- docs/modeling_task_list.md — открытый вопрос Task 144 закрыт (Task 145).

### Границы

- Гейт частотно-агностичен: худшая деградация на малых n — дневные ряды
  (D до 1.36-1.79 при n<28-42); периодическая частота мягкого порога —
  кандидат в будущие уточнения. Повторная калибровка — по мере накопления
  реальных пользовательских бэктестов (скрипт и кэш сохранены).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); работа в ZIP
  download/task_145_soft_threshold_calibration.zip.

Изменённые/новые файлы:
- rules/modeling.yaml (soft 50/40 -> 60/60 x 5 моделей, версия 1.3.1)
- tests/test_modeling_spec.py (+test_soft_min_matches_task145_calibration_report,
  версия 1.3.1, динамизация 3 soft-тестов)
- tests/api/test_param_space.py (версия 1.3.1)
- tests/unit/test_eda_model_matrix.py (boundary-тест из spec)
- tests/unit/test_model_readiness_candidates.py (soft_specs из spec)
- scripts/task144_mutations.py (M20/M21 под значение 60)
- scripts/task145/soft_calibration.py (НОВЫЙ — харнесс калибровки)
- scripts/task145/extract_demo.mjs (НОВЫЙ — извлечение демо-CSV)
- scripts/task145/calib_data/*.csv (НОВЫЕ — извлечённые демо-ряды, 4 файла)
- docs/task145_soft_history_calibration.md (НОВЫЙ — отчёт)
- docs/task145_soft_history_calibration_results.json (НОВЫЙ — сырые данные)
- docs/modeling_task_list.md (закрытие открытого вопроса)

---

## Task DKT-0 (2026-09-18) — Спецификация тёмной темы платформы: архитектура + декомпозиция (код не пишется по постановке)

Синхронизация: main@e5afb2c, дерево чистое (онбординг-запись этой сессии —
выше). Постановка тимлида: спроектировать и изложить план подключения
тёмной темы на всей платформе; переключатель — сменяющие друг друга
иконки луна/солнце в ProductHeader справа, рядом с РУС/ENG; декомпозиция,
если не один проход; код пока не пишем. Результат — spec_dark_theme.md
(архитектурная спека по конвенции spec_*.md, к ревью тимлида перед
TDD-стадией).

### Инвентаризация (программные замеры, не оценки)

- packages/ui: 205 tsx, 139 с цветовыми классами; нейтральная палитра
  ~2680 инстансов (bg-white 224, text-neutral-500 538, border-neutral-200
  363...), брендовые 657, статусные ~800, слэш-прозрачность ~150
  (bg-brand-light/50 x24, border-brand/30 x19...); 42 файла с
  фиксированными hex (Recharts #F0F0F0/#171717/#FFFFFF/#2E3192,
  волновые фоны, флоучарты /navigator); standalone-оболочка ~16
  инстансов, embedded-страницы 0.
- PNG-экспорт (ForecastExportMenu): SVG-сериализация + canvas #FFFFFF —
  var() в сериализованном SVG не разрешается, нужен резолв перед
  экспортом (найдка спеки §6.4).
- Инверсная поверхность-прецедент: bg-neutral-950 + text-neutral-100
  (Model Card JSON-блок) — класс «код-блок» в тёмной теме инвертировать
  НЕЛЬЗЯ (исключение §6.2).
- Логотип: пиксельная проверка — индиго #2E3192 + белое содержимое, на
  тёмной шапке читаем.
- Guard-тесты (~110 сюит / ~1100+ тестов) пинят ТОЧНЫЕ строки классов.

### Решение спеки (§3)

Вариант C «имена классов не меняются — меняются значения»:
darkMode:"class" + палитра пресета на CSS-переменные в формате
rgb(var(--c-*) / <alpha-value>) (сохраняет ~150 слэш-модификаторов);
:root = точные текущие светлые значения (байт-инвариант светлой темы),
.dark = тёмная ревизия. Следствие: НОЛЬ правок в 139 компонентах по
всей классовой массе, guard-тесты проходят без правок; точечные правки —
только в 42 hex-файлах (DKT-3). Отвергнуты: A (dark:-пары на каждый
класс — удвоение классовых строк, сотни правок guard-тестов, вечная
дисциплина пар) и B (filter:invert — нечестно). Провайдер — hand-rolled
~50 строк (прецедент NAVSTG-2), next-themes — задокументированная
альтернатива; no-FOUC-скрипт + suppressHydrationWarning на <html>;
контракт темы: localStorage["cisstat-theme"], класс .dark на <html>,
init localStorage -> prefers-color-scheme -> light.

### Декомпозиция (§7; каждая под-задача — полный цикл AGENTS.md)

- DKT-1 фундамент: пресет+globals+ThemeContext+no-FOUC+переключатель
  Moon/Sun в ProductHeader (рядом с РУС/ENG, aria по состоянию) —
  светлая тема инвариантна.
- DKT-2 тёмный каталог: финальная ревизия .dark, программный
  контраст-аудит WCAG AA, инвентаризация исключений (код-блок, тени,
  text-brand 157 -> возможно dark:text-brand-bright), аудит шапки/логотипа.
- DKT-3 hex->var: 42 файла (Recharts, волновые фоны, флоучарты),
  резолв var() в PNG-экспорте (решение тимлида §10.1: рекомендация —
  экспорт всегда светлый).
- DKT-4 оболочки/сторонние: ModuleNav, feed-scroll, sonner theme prop,
  meta theme-color, явный body-фон; embedded — по решению §10.2.
- DKT-5 финальная регрессия + прод-смоук; DKT-CERT — независимая
  сертификация серии по практике проекта.
- Тест-стратегия §8: каталог-тест токенов (инвентарь rg как источник),
  компиляция слэш-прозрачности в CSS-бандле, юниты провайдера
  (matchMedia-стаб), мутационная кампания, guard-инвариант «~1100 тестов
  зелёные без правок».

### Открытые вопросы тимлиду (§10)

1) PNG-экспорт: всегда-светлый (рекомендация) или как-на-экране;
2) embedded v1: только standalone (рекомендация) или обе оболочки;
3) дефолт: системная схема (рекомендация) или всегда светлая;
4) логотип на тёмном: оставить (рекомендация) или светлый ассет;
5) провайдер: hand-rolled (рекомендация) или next-themes;
6) transition: без (рекомендация) или точечный transition-colors.

### Границы

- Производственный код НЕ тронут (постановка: код пока не пишем) —
  1 новый файл spec_dark_theme.md + этот журнал. Коммит/пуш НЕ
  выполнялись (запрет AGENTS.md); ZIP в download.

Изменённые/новые файлы (ZIP: download/task_dkt0_dark_theme_spec.zip):
- НОВЫЕ: spec_dark_theme.md (спека: инвентаризация, стратегия §3,
  архитектура §4, контракт §5, каталог значений §6, декомпозиция DKT-1..5
  §7, тест-стратегия §8, риски §9, открытые вопросы §10),
  worklog/worklog6.md (этот журнал).
