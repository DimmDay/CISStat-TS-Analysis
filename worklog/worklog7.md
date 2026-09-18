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

---

## Task TSKIA-1..4 (2026-09-18) — Доработка модуля «Задачи»: реализация v1.1 хаба (лента артефактов + буллеты карточек + замыкание цепочки степперов)

Синхронизация: main@3c034c5 (Task DKT-0), дерево чистое. Постановка тимлида:
доработать модуль «Задачи» по docs/spec_tasks_ia.md и
docs/spec_tasks_ia_addendum_v1_1.md; при сложности — декомпозировать и
начать с первой подзадачи; фиксация — worklog7.md; по результатам — ZIP.
Декомпозиция: roadmap §10 дополнения — v1 сделано, v1.1 предлагается =>
поставлен и реализован v1.1 целиком (§9.2 + §9.3 + §9.4, критерии §13);
v2 (первый вертикальный срез «Причины», §10.1) — НЕ затронут, отдельная задача.

### Декомпозиция и статус

- TSKIA-1 (§9.2) Лента артефактов сессии — ГОТОВО;
- TSKIA-2 (§9.3) Содержательные буллеты карточек — ГОТОВО;
- TSKIA-3 (§9.4) Замыкающая кнопка цепочки степперов — ГОТОВО;
- TSKIA-4 Регрессия + worklog + ZIP — ГОТОВО (этот блок).

### TSKIA-1 — лента артефактов (§9.2)

- НОВЫЙ packages/ui/components/TaskArtifactRibbon.tsx: горизонтальная лента
  compact-карточек между шапкой хаба и сеткой задач. Честная маркировка:
  рисуются ТОЛЬКО существующие артефакты (артефакт <=> этап-владелец =
  "done", тот же слой §4, контракт состояний НЕ расширяется); свежая
  сессия — компонент возвращает null (ленты нет вовсе, не «пусто»).
- Порядок чипов = порядок пайплайна: validated -> model_card -> forecast_run.
- Наполнение — из уже посчитанных фактов: Датасет — activeDataset из
  AppShellContext («{name} · {rows} набл.», без гидратации — факт
  «загружен»); Model Card — точечный вызов fetchCardSummaries
  (GET /v1/session/modeling/card): последняя карта по created_at,
  при нескольких — «{name} × N»; отказ/пустой список — деградация к
  факту «создана» (fail-soft, отмена эффектов через alive/cancelled —
  без act-предупреждений); Прогноз — факт «построен» без похода за
  деталями (состав чипа — вместе с v2 «Мониторинга», прямо по §9.2).
- Чипы — переиспользование Metric (по образцу DatasetPassportPanel),
  НЕ новый чип; ссылок внутри ленты нет — счётчики ссылок контракта §4
  в TasksHub.test не изменились ни на единицу.
- Интеграция: TasksHub.tsx — единственная вставка <TaskArtifactRibbon />
  между шапкой и сеткой; публичный экспорт index.ts не расширялся
  (лента — внутренняя композиция хаба, минимальная поверхность API).
- Замечание по бэкенд-контракту: §9.2 ожидает от списка карт «метрику»,
  фактически GET /card сводки метрики точности НЕ отдаёт
  (routers/modeling_session.py::list_model_cards: card_id/model_id/
  model_name/selection_kind/horizon/fingerprint/created_at). Чип честно
  показывает имя/счётчик карт без выдуманной метрики; расширение сводки
  — бэкенд-правка, запрещённая §7 исходного спека — отложено до v2.

### TSKIA-2 — буллеты карточек (§9.3)

- task-stops.ts: TaskRoute.outcomes?: string[] — 2–3 обещанных результата
  на задачу, формулировки по продукту, не по механике («Вклад каждого
  фактора в прогноз», «Сравнение сценариев на одном графике»; не
  «использует SHAP»), все 4 записи реестра заполнены.
- TaskCard.tsx: блок data-testid="task-outcomes" после строки описания,
  в ДОПОЛНЕНИЕ к ней (строка v1 не заменена); компактный text-xs с
  brand-маркерами; виден во ВСЕХ трёх состояниях — обещание задачи, не
  гейтинг (гейтят только артефакты контракта входа).

### TSKIA-3 — замыкание цепочки (§9.4)

- TsAnalysisForecasting.tsx: StepperNextModuleButton label="Перейти к
  задачам" href="/tasks" сразу после блока «Шаги этапа» (конец «степпера»
  workspace), до card-handoff; кнопка «Обновить состояние» (mt-auto)
  остаётся внизу колонки. Компонент StepperNextModuleButton НЕ изменён
  (label/href — единственные входы, черта border-t встроена в обёртку):
  прецедент целевой страницы-не-степпера — Моделирование -> Прогнозирование.

### TDD (AGENTS.md: RED -> GREEN на каждую подзадачу)

- TSKIA-1: НОВЫЙ TaskArtifactRibbon.test.tsx (10 кейсов: честная
  маркировка/fresh-null/порядок/деградации/DNA Metric); RED подтверждён
  (TS2307, только отсутствие модуля). GREEN 10/10. TasksHub.test.tsx:
  ДОБАВЛЕНЫ только (а) инфраструктурные моки новой дочерней зависимости
  (jest.mock ../lib/forecasting + activeDataset в фабрике контекста —
  без правки ни одного существующего кейса §4) и (б) 3 новых кейса
  ленты в конце файла. Требование §13 «не меняет ни один существующий
  тест контракта состояний» соблюдено: все прежние кейсы TasksHub —
  байт-в-байт.
- TSKIA-2: task-stops.test.ts + describe outcomes (объём 2–3,
  уникальность, отличимость от description); TaskCard.test.tsx +
  describe буллетов (в дополнение к описанию, точное количество, все
  состояния, компактность, back-compat отсутствия); RED подтверждён
  (TS2339/TS2353 — поля outcomes нет). GREEN.
- TSKIA-3: TsAnalysisForecasting.test.tsx + describe §9.4 (href=/tasks,
  контракт классов StepperNextModuleButton, позиция после
  forecasting-steps, внутри левой колонки); RED подтверждён (ровно 2
  новых падения, 9 старых зелёные). GREEN 11/11.

### Верификация (§13 — полная)

- npx jest: 1157/1157 passed (полная регрессия монорепо; все сюиты
  контракта §4 зелёные без правок).
- npm run typecheck:all: embedded + standalone — без ошибок.
- npm run build: сборка standalone успешна (маршруты /tasks и
  /tasks/* на месте).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

### Границы

- Контракт трёх состояний, реестр (4 записи, без category/
  recommendedWith-расширений), ModuleNav, STAGES, бэкенд — не тронуты
  (§9.5/§7). v2 (срез «Причины» XAI по §10.1, чип истории запусков,
  состояние configurable) — следующий отдельный вертикальный срез.

Изменённые/новые файлы (ZIP: download/task_tskia_tasks_hub_v11.zip):
- НОВЫЕ: packages/ui/components/TaskArtifactRibbon.tsx,
  packages/ui/components/TaskArtifactRibbon.test.tsx
- ИЗМЕНЕНЫ: packages/ui/components/TasksHub.tsx (+лента),
  packages/ui/components/TasksHub.test.tsx (моки+3 новых кейса),
  packages/ui/lib/task-stops.ts (outcomes в типе и реестре),
  packages/ui/lib/task-stops.test.ts (+describe outcomes),
  packages/ui/components/TaskCard.tsx (буллеты),
  packages/ui/components/TaskCard.test.tsx (+describe буллетов),
  packages/ui/components/TsAnalysisForecasting.tsx (кнопка §9.4),
  packages/ui/components/TsAnalysisForecasting.test.tsx (+describe §9.4),
  worklog/worklog7.md (этот журнал).

---

## Task DKT-1 + DKT-2 (2026-09-18) — Фундамент тёмной темы + тёмный каталог значений: калибровка, контраст-аудит, исключения

Синхронизация: main@3c034c5 (DKT-0: спека + журнал), дерево — локальная
онбординг-запись в worklog6.md (незакоммиченно). Постановка тимлида:
«Дальше по спеке: DKT-2 (контраст-аудит и калибровка каталога)». Факт
объёма: артефактов DKT-1 в дереве 3c034c5 не было (§7: «DKT-1 — фундамент,
без него остальное не исполняется») → фундамент DKT-1 возведён в составе
среза как обязательная предпосылка, затем исполнена собственно DKT-2.
Оба среза — полный цикл AGENTS.md (TDD RED→GREEN, регрессия, typecheck/
build, ZIP). Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

### DKT-1 — фундамент (токенизация, провайдер, переключатель)

- tailwind-preset.ts: darkMode:"class"; все занятые шаги палитры
  (инвентарь rg: neutral 50–950 + white/black, brand/brand-light,
  статусные green 8 / amber 9 / red 7 / blue 8 / emerald 4 / violet 3 /
  sky 5 / cyan-500, footer-токены) → rgb(var(--c-*) / <alpha-value>);
  НОВЫЙ токен brand-bright (светлое = #2E3192 — байт-инвариант).
- globals.css: :root = точные светлые значения (байт-инвариант);
  .dark = тёмная ревизия (вердикт DKT-2 ниже); color-scheme light/dark;
  тёмный скроллбар feed-scroll.
- ThemeContext.tsx (новый, hand-rolled ~60 строк по прецеденту NAVSTG-2):
  контракт §5 — localStorage["cisstat-theme"] → prefers-color-scheme →
  light; класс .dark на <html>; идемпотентный applyTheme (класс +
  color-scheme + meta theme-color #FFFFFF/#0B0C10); кросс-таб
  storage-событие; NO_FOUC_SCRIPT — блокирующий IIFE в <head> layout
  до гидратации; layout.tsx: suppressHydrationWarning на <html>,
  ThemeProvider оборачивает ProductHeader+AppShellProvider.
- ProductHeader.tsx: переключатель Moon/Sun СПРАВА между «РУС / ENG» и
  кабинетом (постановка), lucide size={14}, паттерн соседа
  text-neutral-500 hover:text-neutral-900, aria-label по состоянию +
  aria-pressed.

### DKT-2 — калибровка каталога, контраст-аудит, исключения

- Скрипт-оракул scripts/task_dkt2/contrast_audit.py (независимая
  реализация) + jest-зеркало dark-catalog-contrast.test.ts: 48 роль-пар
  каталога по значениям из globals.css (единственный источник), WCAG AA
  (4.5 текст / 3.0 не-текст); со-локационный скан 3 691 className-строк
  (33 цветовые пары фактического кода). Итог: 48/48 PASS в обеих
  реализациях. Артефакты: docs/task_dkt2_contrast_audit_results.json.
- Находка №1 (ловушка Варианта C): text-white — «текст на заливке»
  (bg-brand ×349), инверсия white дала бы тёмный текст на индиго
  (2.88:1 FAIL). Инвентарь: 103 plain + 7 hover: + 2 group-hover:,
  text-white/NN = 0. Решение: токен --c-white-fg (#FFF в обеих темах) +
  utility-ревизии .dark .text-white / hover / group-hover (механизм
  §6.2, ноль правок компонентов). Пара bg-brand ↔ white-fg: 10.66/6.21.
- Находка №2 (R-3): text-brand 159 инстансов (153 plain + 6 hover, 48
  файлов; спека предполагала 157); компромисс #4A4ED9 как текст —
  2.88–2.40:1 (FAIL для всех мелких текстов). Решение: brand-bright
  (#8F94F5 в тёмной; 6.58:1 карточка / 5.89:1 brand-light) +
  utility-ревизия .dark .text-brand (+ hover). dark:text-brand-bright
  доступен для точечного применения (компиляция dark:-варианта
  страхуется тестом).
- Калибровка рампы: neutral-50→#1C1D23 … neutral-900→#F1F2F5; статусы:
  поверхности-50 → тонированные тёмные (green #12251A, amber #2A2113,
  red #2A1414, blue #131C2B, emerald #0E2318, violet #1D1730, sky
  #12202E); тексты-600/700/800/900 → светлые статусные (green-700
  #4ADE80 9.6:1, red-600 #F87171, red-700 #FCA5A5…); индикаторы-400/500
  без ревизии (≥3:1 в тёмной). Светлые факты ниже AA (green-600 3.15,
  amber-600 3.07, red-600 4.41, placeholder 2.52, индикаторы 1.67–2.43)
  зафиксированы как инварианты светлой; тёмная везде лучше (детали —
  docs/task_dkt2_dark_catalog_calibration.md §5).
- Исключения «класс ≠ роль» (§6.2, инвентаризация): код-блок Model Card
  (bg-neutral-950 не инвертируется; точечный dark:text-neutral-800 =
  15.71:1 + dark:ring-1 — ring без изменения геометрии); шеврон
  TsAnalysisModeling text-black на карточке → точечный dark:text-
  neutral-900; black НЕ инвертируется (роль: текст/оверлеи на
  нетокенизированных поверхностях — HomeFooter #CAD7F7 13.9:1, подложка
  EventsLogDrawer); тени shadow-sm/lg/xl → utility-ревизии .dark с
  rgb(0 0 0 / .6); фокус-ринги в токенах ≥3:1 без ревизии.
- Аудит шапки (scripts/task_dkt2/logo_audit.py →
  docs/task_dkt2_logo_audit.json): логотип 77.6% индиго + 21.8% белого;
  белое содержимое на тёмной шапке 17.9:1 (PASS), индиго-поле 1.68:1
  (граница слабая, читаемость на белом — факты для §10.4 тимлиду);
  навигация 6.4–8.5:1; кабинет-круг 4.9:1.
- Матрица страниц-представителей × обе темы (scripts/dkt_pages_matrix.mjs,
  транзитивные деревья компонентов): home/navigator/upload/validation/
  preprocessing/eda/modeling/forecasting/tasks — все поверхности и
  текст-роли в каталоге, ни одного класса без пары аудита (отчёт §8).
- CSS-бандл-смоук продового CSS standalone
  (scripts/task_dkt2/css_bundle_smoke.mjs): 14/14 PASS — var-тройки,
  .dark-ревизии, слэш-прозрачность rgb(var()/0.NN), dark:-вариант
  :is(.dark *), точечные оверрайды в бандле.
- Мутационная кампания провайдера (scripts/task_dkt2/mutation_theme.sh,
  §8.6): M1 init→всегда system, M2 инверсия toggle, M3 инверсия условия
  .dark, M4 снятие персиста, M5 снятие meta theme-color, M6 снятие
  no-FOUC — все 6 KILLED на независимых оракулах.

### Верификация

- TDD: RED 59 тестов (5 новых сюит) → GREEN; полная регрессия
  112 сюит / 1230 теста зелёные; 107 старых сюит / 1134 теста БЕЗ правок
  (контрольный факт Варианта C, §3.3).
- typecheck:all PASS; build:all обеих оболочек PASS.
- Backend не затронут (0 файлов; нулевой дифф по построению).

### Границы

- Embedded: переменные и компоненты готовы, переключатель не монтируется
  (открытый вопрос §10.2); body-фон #0B0C10, sonner theme prop, meta
  theme-color на embedded — DKT-4; 42 файла фиксированных hex
  (Recharts/волны/флоучарты/PNG-экспорт) — DKT-3 (handoff-список —
  отчёт §10).

Изменённые файлы: packages/ui/tailwind-preset.ts, packages/ui/globals.css,
packages/ui/index.ts, apps/standalone/app/layout.tsx,
apps/standalone/components/ProductHeader.tsx,
packages/ui/components/ModelingWorkflowOverview.tsx (точечный dark:
оверрайд код-блока §6.2), packages/ui/components/TsAnalysisModeling.tsx
(точечный dark: оверрайд шеврона §6.2).

Новые файлы: packages/ui/context/ThemeContext.tsx (провайдер),
packages/ui/context/ThemeContext.test.tsx, packages/ui/tailwind-preset.test.ts
(каталог-тест §8.1), packages/ui/preset-compile.test.ts (компиляция §8.2),
packages/ui/dark-catalog-contrast.test.ts (jest-зеркало оракула),
apps/standalone/components/ProductHeaderThemeToggle.test.tsx,
scripts/task_dkt2/contrast_audit.py, scripts/task_dkt2/css_bundle_smoke.mjs,
scripts/task_dkt2/logo_audit.py, scripts/task_dkt2/mutation_theme.sh,
docs/task_dkt2_dark_catalog_calibration.md (отчёт),
docs/task_dkt2_contrast_audit_results.json (сырые данные),
docs/task_dkt2_logo_audit.json.

---

## Task DKT-2R + DKT-3 + DKT-4 (2026-09-18) — решения §10, «цвет логотипа», hex→var, оболочки

**Синхронизация:** main @ e99cd1f (DKT-1+DKT-2 тимлида). **Решения
тимлида:** §10.2 «v1 — только standalone», §10.3 системная схема,
§10.4 логотип оставить — зафиксированы в spec_dark_theme.md §10.

**DKT-2R (требование тимлида: индиго-заголовки в тёмной теме — цветом
логотипа):** инвентарь произвольных hex-классов — text-[#1e3a8a] ×9/4
файла (hero h1/h2/p home, navigator, tasks, platform-introduction),
вне канона каталога, в тёмной ~1.7:1 FAIL. Literal #2E3192 = 1.68:1
(аудит логотипа) → «цвет логотипа» в тёмной калибровке = brand-bright
#8F94F5 (hue 237° логотипа). Utility-ревизия .dark .text-\[\#1e3a8a\]
(§6.2, ноль правок в компонентах). TDD: heading-indigo-calibration.test.ts
7 тестов (инвентарь-страж новых классов, AA, hue-идентичность ±2°,
светлая инвариантность), RED 3 → GREEN 7/7.
Отчёт: docs/task_dkt2r_heading_calibration.md.

**DKT-3 (hex→var, §6.3/§6.4):** ~280 литералов / 36 файлов → 24
chart/status-переменные + 35 волновых (--wave-home-1..14, -stroke,
--wave-nav-1..20; тёмные = hue-сохранное преобразование S.32/L.13,
белый штрих → #2E3038). Светлые значения — байт-инвариант. Скрипт
scripts/task_dkt3/hex_to_var.py (построчная сверка в worklog). PNG-
экспорт: lib/chartVars.ts (CHART_VARS_LIGHT 59 значений — зеркало :root
+ resolveSvgVarsLight §6.4); артефакт «всегда светлый» (рекомендация
§10.1), canvas #FFFFFF — единственный остаточный литерал (намеренно).
Синхронизированы пины 3 сюит (волны ×23, шеврон ×1) на var-ссылки.
Отчёт: docs/task_dkt3_dkt4_hex_to_vars.md.

**DKT-4 (оболочки):** body-фон на токен --c-page (#FFFFFF/#0B0C10,
паритет блоков + сверка с THEME_META_COLOR); ThemeToaster (sonner theme
prop из контекста, R-7) в standalone; embedded не тронут (§10.2, тест
фиксирует контракт); ModuleNav — аудит: только токены каталога, правок
нет. Отложено: токенизация футера #CAD7F7 (пиксельно одинаков в обеих
темах), тёмная ревизия heatmap-шкалы (JS-интерполяция).

**Верификация (полный цикл AGENTS.md):** TDD RED→GREEN по каждому срезу
(новые сюиты: 2R ×7, DKT-3 ×6, экспорт-резолв ×5, DKT-4 ×5); полная
регрессия 117 сюит / 1276 тестов — зелёные; CSS-бандл-смоук PASS;
typecheck:all чисто; build:all обеих оболочек успешно. ZIP среза —
в download. Следующий шаг: DKT-5 (финальная регрессия + прод-смоук
после деплоя тимлидом).

Изменённые файлы: spec_dark_theme.md, packages/ui/globals.css,
packages/ui/index.ts, apps/standalone/app/layout.tsx,
packages/ui/components/ForecastExportMenu.tsx, 30 графовых компонентов
(карта замен — вывод hex_to_var.py), HomeWavesBackground.test.tsx,
NavigatorWavesBackground.test.tsx, NavigatorHero.test.tsx,
worklog/worklog7.md.

Новые файлы: packages/ui/heading-indigo-calibration.test.ts,
packages/ui/dkt3-chart-vars.test.ts, packages/ui/dkt4-shells.test.tsx,
packages/ui/components/ThemeToaster.tsx,
packages/ui/components/ForecastExportMenu.vars.test.ts,
packages/ui/lib/chartVars.ts, scripts/task_dkt3/hex_to_var.py,
docs/task_dkt2r_heading_calibration.md,
docs/task_dkt3_dkt4_hex_to_vars.md.
