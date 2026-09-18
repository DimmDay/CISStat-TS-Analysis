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

---

## Task ID: PREPR-3 (2026-09-18) — Автообновление профилей остановок «Предобработки» после применения исправлений (единый datasetVersion)

Синхронизация: main@e99cd1f (DKT-1 + DKT-2), рабочее дерево чистое до
работы. Постановка тимлида: при наличии пропусков (и/или выбросов)
блокируются остановки «Декомпозиция ряда», «Стабилизация дисперсии»,
«Сглаживание ряда» и т.д. с плейсхолдером «В ряду N пропусков; сначала
завершите остановку „Пропуски“»; после применения стратегии исправления
в «Пропусках» остальные остановки об этом НЕ узнают — актуальное состояние
модуля достигается только перезагрузкой страницы. Требуется автообновление
после валидации каждой остановки. Воспроизвести, спроектировать,
реализовать.

### Репродукция (по коду, затем тестом)

- Бэкенд честно гейтит применимость по СОСТОЯНИЮ датасета:
  preprocessing_decomposition.py:94 / preprocessing_variance.py:64 /
  preprocessing_smoothing.py:59 / preprocessing_stationarity.py:74 /
  preprocessing_feature_engineering.py:34 возвращают
  applicable=false + reason «В ряду N пропусков…» (декомпозиция при этом
  status="skipped", status_reason="not_required" — routers/session.py:387).
- Фронт: TsAnalysisPreprocessing кэширует профили 10 остановок в state;
  profile-fetch useEffect зависят ТОЛЬКО от [activeFeature, xxxRefreshKey],
  а onApplied мастера «Пропусков» бампил исключительно
  setMissingRefreshKey → перезапрашивался ТОЛЬКО missing-профиль.
  Профили остальных остановок оставались stale до ремонта компонента
  (перезагрузка страницы).
- Дополнительно: эффекты «Генерация признаков»/«Масштабирование» были
  гейтированы activeCheckId (ленивая загрузка) — их статусы устаревали
  даже БЕЗ посещения остановки (после визита до исправления).
- RED-репродукция: 3 новых теста падают ровно на stale-бейджах
  («STL выполнен…» не появляется; «Проверка пройдена, пропусков нет»
  после чужого применения не наступает; статусы feature_eng/scaling на
  монтировании отсутствуют).

### Решение (одна точка изменения — родительский компонент)

- Единый счётчик datasetVersion («версия состояния датасета модуля»):
  контракт «применение исправления в ЛЮБОЙ остановке = мутация датасета =
  инвалидация ВСЕХ профилей». Все 10 onApplied теперь бампят
  setDatasetVersion (собственные xxxRefreshKey в onApplied больше не
  нужны — собственный профиль остановки перезапрашивается тем же бампом).
- datasetVersion добавлен в deps ВСЕХ 10 profile-fetch useEffect — после
  каждого применения степпер/бейджи/метрики/Обзоры перезапрашиваются
  автоматически (React 18 batching: один бамп = один ре-рендер = один
  повторный fetch каждой остановки; гардируется ассертом
  counts.decomposition === 2).
- Снят ленивый гейт activeCheckId у feature_eng/scaling — контракт
  унифицирован: «статусы всех 10 остановок всегда отражают текущий
  датасет» (самый тяжёлый профиль — STL декомпозиции — и ранее считался
  при монтировании; +2 запроса на монтирование в пределах принятого
  компромисса «8 запросов при монтировании», комментарий к missing-эффекту).
- Узкая зона инвалидации СОХРАНЕНА: смена режима остановки
  (PUT preprocessing-check-modes) и кнопка «Пересчитать» бампят только
  собственный xxxRefreshKey — датасет не мутируют, чужие профили не
  инвалидируют (гард-тест: счётчик decomposition не растёт).

### TDD (AGENTS.md: RED -> GREEN)

- RED (подтверждён ДО правки компонента, ровно 3 падения): (1)
  «after applying missing corrections the blocked decomposition stop
  refreshes without a page reload» — полный сценарий постановки: мок
  декомпозиции blocked (skipped + reason) до apply и done после; ассерты
  бейджа «В ряду 2 пропусков…» → «STL выполнен, остаточная диагностика
  пройдена», степпер done («Пройдено»), counts.decomposition === 2;
  (2) симметрия «выбросы → пропуски» (after applying outliers
  corrections the missing stop refreshes); (3) статусы feature_eng/
  scaling загружаются на монтировании без визита остановки. Гард-тест
  (4) «saving a stop's mode does not invalidate other stops' profiles»
  зелёный уже в RED (фиксирует корректное существующее поведение).
- GREEN: правки только TsAnalysisPreprocessing.tsx → 4/4 новых +
  61/61 всего файла.

### Верификация (полная регрессия)

- Frontend: npx jest — 113 сюит / 1257 passed / 0 failed (полная
  монорепо-регрессия; guard-тесты зелёные БЕЗ правок — arithmetics
  baseline e99cd1f 113/1253, +4 новых).
- npm run typecheck:all — 0 ошибок; npm run build:all — Compiled
  successfully x2 (embedded + standalone).
- Backend не затронут (0 файлов .py) — pytest-прогон не требуется
  (прецедент frontend-only задач EDA-2/PREPR-1/VALID-2).
- Мутационная кампания не проводилась (фронтовый diff 55 строк); критические
  точки контракта прижаты тестами: снятие datasetVersion из deps любого
  эффекта ловится тестом (1), гейт-регрессия — тестом (3), расширение
  зоны инвалидации на смену режима — гардом (4).

### Границы

- DatasetPassportPanel (stage="exit") сознательно не инвалидируется
  datasetVersion: паспорт — точка РУЧНОЙ фиксации («Зафиксировать»),
  семантика подтверждённого снимка, а не автоматического профиля.
- Кнопка «Пересчитать свойства после преобразования» для 6 остановок без
  onClick (pre-existing) не тронута — вне мандата постановки.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); работа в ZIP
  download/task_prepr3_profile_auto_refresh.zip.

Изменённые/новые файлы:
- packages/ui/components/TsAnalysisPreprocessing.tsx (datasetVersion +
  deps 10 эффектов + снятие гейта feature_eng/scaling + 10 onApplied)
- packages/ui/components/TsAnalysisPreprocessing.test.tsx (+4 кейса в
  новом describe «автообновление профилей после применения исправлений»)

  ---

## Task TSKV2-1 (2026-09-18) — v2, первый вертикальный срез «Причины» (XAI, паттерн C §11.2): бэкенд-эндпоинт + фронтенд страницы, полный TDD-цикл

Синхронизация: main@e99cd1f (DKT-1 + DKT-2; TSKIA-1..4 уже в истории), дерево
чистое (stash-остатки прошлой сессии подтверждены включёнными в 4157b6f и
сброшены). Постановка тимлида: v2 — первый вертикальный срез «Причины»
(XAI, паттерн C по §11.2), требует бэкенд-эндпоинта и полного TDD-цикла;
ZIP в download; AGENTS.md.

### Декомпозиция (§10 дополнения: v2 = срез «Причины» + чип истории запусков + configurable)

- TSKV2-1 — вертикальный срез «Причины» (§10.1, паттерн C §11.2) — ЭТОТ СРЕЗ;
- чип истории запусков (маленький бэкенд-эндпоинт списка запусков) — НЕ затронут,
  отдельная задача v2 (в постановке тимлида срез ограничен «Причинами»);
- прототип `configurable` на «Принятии решений» — НЕ затронут (v2, отдельный срез).

### Проектирование (§10.1: «просмотр уже вычисленного», простейший контракт входа)

Инвентаризация вычисленных фактов (программно, не по памяти):
- Feature importance: `backtesting.py:650` — каждый fold бэктеста
  tree-моделей (random_forest/xgboost/lightgbm/catboost — 4 адаптера,
  model_impls) persist-ит `feature_importance` с oracle-привязкой
  (`bind_feature_importance`, feature_plan.py:962: plan_id/matrix_hash/
  fit_policy + importances[]). Данные УЖЕ вычислены и лежат в
  `session.modeling_artifacts["backtests"][model_id]["folds"][i]`.
- Model Card: `create_model_card` reserves `feature_importance: None`
  (modeling_session.py:3255) — поле-заготовка, никогда не заполняется.
  Артефакт бэктеста привязан к карте через training.backtest_run_id.
- Granger: EDA считает по запросу аналитика (GET /dataset/eda-feature-selection,
  session.py:808) и НЕ persist-ит в сессию — «уже вычисленного» артефакта нет.
- SHAP/PDP: движком НЕ вычисляются нигде (grep: import shap — 0 файлов).
- Ensemble-карты: fold-importances членов в ensemble_backtests, но честная
  агрегация по членам — отдельное решение (прецедент честного отказа
  ансамбля — test_forecast_rejects_ensemble_card_honestly).

Следствие (честная маркировка §9.1): первый срез отдаёт БЕЗ пересчётов
только fold-importance как доступный метод; Granger/SHAP/PDP — строки
реестра методов со статусом not_computed и честной причиной (не
фиктивные данные). Контракт входа `model_card` (§2 исходной спеки).

### Решение: бэкенд

- НОВЫЙ apps/api/routers/tasks_session.py — GET /causes (prefix
  /v1/session/tasks, mounting в main.py рядом с modeling_session):
  card_id опционален (дефолт — последняя карта по created_at, тот же
  порядок, что TaskArtifactRibbon); нет карт — 409 с причиной (хаб
  гейтит, прямой URL — честный отказ, прецедент 409 моделирования);
  ensemble-карта — методы с not_computed/причиной, не 5xx.
- Агрегация fold-importance: внутри каждого fold доля importance/sum
  (сырые MDI разных fold несопоставимы по масштабу), средняя доля по
  fold, сортировка по убыванию; per-fold сырые значения и matrix_hash —
  в деталь фактора; provenance (run_id/plan_id) — в метод.
- Ответ: {card, methods:[{method_id,title,status,reason?,factors?,...}]}.

### Решение: фронтенд (паттерн C §11.2, строительные блоки таблицы §11.2)

- НОВЫЙ packages/ui/components/TasksCauses.tsx: 3 колонки по образцу
  AppliedTasksNavigator (aside w-60 методы → aside w-80 факторы →
  section деталь); бейджи «Когда использовать»/«Что нужно для запуска»
  (классы StaticHalfBadge NavigatorHero); правая колонка — «Панель
  управления» (обязательный блок §11.2) с деталью фактора: BarChart
  средних долей факторов (выбранный подсвечен, топ-12) в контейнере
  h-[468px] под ExpandableChartPanel + ExpandableChartsProvider
  (обязательные блоки §11.2), таблица per-fold под графиком; цвета
  Recharts — var(--c-*) (урок DKT-3: новых hex-литералов не создавать).
- НОВЫЙ packages/ui/lib/tasks.ts: типы 1:1 ответу бэкенда + fetchCauses
  (sessionApiUrl, credentials include — прецедент forecasting.ts).
- Гейтинг страницы: stages.modeling !== done → честное пустое состояние
  с микро-CTA на /modeling (прецедент R5-CTA хаба) БЕЗ похода в сеть;
  409 бэкенда → состояние с причиной.
- НОВЫЙ apps/standalone/app/tasks/causes/page.tsx (замена плейсхолдера);
  экспорт в packages/ui/index.ts.

### Точки изменения и риски

- main.py (включение роутера — 1 строка); guard-тесты существующих
  эндпоинтов не задействуют /v1/session/tasks (проверено grep).
- Риск 500 на вложенных артефактах: все чтения через .get-цепочки;
  отсутствующий бэктест-артефакт карты → not_computed с причиной, не 500.
- Риск гидратации: fetch только в useEffect с alive-флагом (прецедент
  TaskArtifactRibbon); jsdom-тесты мокают lib/модуль.
- Риск Recharts в jsdom: polyfills jest.setup.js (ResizeObserver/
  IntersectionObserver) — прецеденты EdaCorrelationOverview.test.
- Тест-план (TDD RED→GREEN): tests/api/test_tasks_causes.py (контракт
  409/статусы/агрегация/ensemble/provenance/порядок сортировки);
  TasksCauses.test.tsx (паттерн C: 3 колонки, бейджи, статусы методов,
  деталь фактора, honest-состояния, 468px+ExpandableChartPanel).

### TDD (AGENTS.md: RED -> GREEN, оба контура)

- Бэкенд RED подтверждён ДО реализации: 9/9 падений ровно одного вида
  (404 {"detail":"Not Found"} — маршрута /v1/session/tasks/causes нет).
  НОВЫЙ tests/api/test_tasks_causes.py: контракт входа (409 без карт с
  причиной про Model Card; 404 неизвестный card_id), реестр 4 методов
  с честными статусами (fold_importance available, granger/shap/pdp
  not_computed с непустой причиной и factors=null), агрегация
  (сумма долей внутри КАЖДОГО fold = 1; сумма средних долей = 1;
  сортировка по убыванию; per-factor fold_values отсортированы),
  provenance (backtest_run_id/plan_id/n_folds=2, matrix_hash в деталях),
  дефолт-карта = последняя по created_at + явный card_id,
  классическая модель (ets) — not_computed с причиной «не вычисляет
  важность», ensemble-карта — честный отказ агрегации (сеанс через
  посев model_cards: полный HTTP-путь до ensemble требует tuning),
  отсутствующий артефакт бэктеста — 200/not_computed, не 500.
- GREEN: 9/9. Находка в процессе: повторный compare/evaluate
  инвалидирует прежние model_cards (lineage-дисциплина
  modeling_session.py:2941/2985) — тест «две карты» построен на
  повторном POST /card под тем же selection (как в селекторе
  прогнозирования), а не на новом сравнении.
- Фронтенд RED подтверждён ДО реализации: TS2307 (отсутствие модулей
  TasksCauses/lib/tasks — только и именно это). GREEN 8/8: заголовок +
  бейджи; honest-empty без сети с CTA /modeling; loading до гидратации
  без сети; паттерн C (4 метода, недоступные disabled+aria-disabled,
  причина видна в списке), «Панель управления», окно h-[468px],
  ExpandableChartPanel-кнопка; факторы с долями (aria-pressed,
  переключение, .recharts-responsive-container — jsdom-прецедент
  NavigatorChartPreview: внутренний SVG в jsdom не строится);
  провенанс run/plan; недоступные методы не выбираются (клик без
  эффекта); ошибка бэкенда — role="alert" с причиной сервера.

### Верификация (полная регрессия)

- npx jest: 114 сюит / 1261 теста — все зелёные (было 112/1230 после
  TSKIA: +2 сюиты этого среза; старые без правок).
- typecheck:all (embedded + standalone) — без ошибок.
- npm run build: standalone успешна, маршрут /tasks/causes на месте.
- Backend: полный pytest tests/ — 2346 passed / 9 failed / 3 errors /
  24 skipped. Все 9+3 — ПРЕДСУЩЕСТВЕННЫЕ, точное множество Task 145:
  нейро-группа не установлена (integration-paths deepar/lstm/nbeats/
  nhits/tft fail-closed, v2-дескрипторы, neural capacity,
  catalog_only-метрики) + 3 snapshot-ошибки test_preprocessing
  (версии pandas/numpy venv против пинов). Ни одного падения от
  правок среза (stash-прогон чистого HEAD e99cd1f воспроизвёл те же 17).
- Окружение восстановлено до сертификационной эпохи после сброса
  между сессиями: pandera/PyWavelets/holidays/missingno/openpyxl/
  plotly/ruptures/prophet 1.4.0/arch/tbats/statsforecast 2.1.1;
  statsmodels 0.14.5 -> 0.15.0 (пин requirements.txt) — это сняло
  16 предсущественных падений forecasting-контура (parametric
  simulation требовал API statsmodels>=0.15).

### Границы

- Реестр методов среза: fold_importance (уже вычислено, Task 127)
  доступен; granger/shap/pdp — честные not_computed-строки (Granger
  не persist-ится сессией, SHAP/PDP движок не вычисляет) — пересчётов
  и синтетики нет (§10.1 «просмотр уже вычисленного»).
- Ensemble-карты: честный отказ агрегации по членам — отдельное решение.
- Чип истории запусков (v2) и прототип configurable («Принятие
  решений») — НЕ затронуты, отдельные задачи v2.
- Multi-карточный селектор на странице — v3 (дефолт = последняя карта,
  явный card_id поддержан эндпоинтом и lib).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); работа в ZIP.

Изменённые/новые файлы (ZIP: download/task_tskv2_causes_slice.zip):
- НОВЫЕ: apps/api/routers/tasks_session.py,
  tests/api/test_tasks_causes.py,
  packages/ui/lib/tasks.ts,
  packages/ui/components/TasksCauses.tsx,
  packages/ui/components/TasksCauses.test.tsx
- ИЗМЕНЕНЫ: apps/api/main.py (+include_router /v1/session/tasks),
  packages/ui/index.ts (+экспорт TasksCauses),
  apps/standalone/app/tasks/causes/page.tsx (плейсхолдер -> срез),

---

## Task ID: PREPR-3 (2026-09-18) — Автообновление профилей остановок «Предобработки» после применения исправлений (единый datasetVersion)

Синхронизация: main@e99cd1f (DKT-1 + DKT-2), рабочее дерево чистое до
работы. Постановка тимлида: при наличии пропусков (и/или выбросов)
блокируются остановки «Декомпозиция ряда», «Стабилизация дисперсии»,
«Сглаживание ряда» и т.д. с плейсхолдером «В ряду N пропусков; сначала
завершите остановку „Пропуски“»; после применения стратегии исправления
в «Пропусках» остальные остановки об этом НЕ узнают — актуальное состояние
модуля достигается только перезагрузкой страницы. Требуется автообновление
после валидации каждой остановки. Воспроизвести, спроектировать,
реализовать.

### Репродукция (по коду, затем тестом)

- Бэкенд честно гейтит применимость по СОСТОЯНИЮ датасета:
  preprocessing_decomposition.py:94 / preprocessing_variance.py:64 /
  preprocessing_smoothing.py:59 / preprocessing_stationarity.py:74 /
  preprocessing_feature_engineering.py:34 возвращают
  applicable=false + reason «В ряду N пропусков…» (декомпозиция при этом
  status="skipped", status_reason="not_required" — routers/session.py:387).
- Фронт: TsAnalysisPreprocessing кэширует профили 10 остановок в state;
  profile-fetch useEffect зависят ТОЛЬКО от [activeFeature, xxxRefreshKey],
  а onApplied мастера «Пропусков» бампил исключительно
  setMissingRefreshKey → перезапрашивался ТОЛЬКО missing-профиль.
  Профили остальных остановок оставались stale до ремонта компонента
  (перезагрузка страницы).
- Дополнительно: эффекты «Генерация признаков»/«Масштабирование» были
  гейтированы activeCheckId (ленивая загрузка) — их статусы устаревали
  даже БЕЗ посещения остановки (после визита до исправления).
- RED-репродукция: 3 новых теста падают ровно на stale-бейджах
  («STL выполнен…» не появляется; «Проверка пройдена, пропусков нет»
  после чужого применения не наступает; статусы feature_eng/scaling на
  монтировании отсутствуют).

### Решение (одна точка изменения — родительский компонент)

- Единый счётчик datasetVersion («версия состояния датасета модуля»):
  контракт «применение исправления в ЛЮБОЙ остановке = мутация датасета =
  инвалидация ВСЕХ профилей». Все 10 onApplied теперь бампят
  setDatasetVersion (собственные xxxRefreshKey в onApplied больше не
  нужны — собственный профиль остановки перезапрашивается тем же бампом).
- datasetVersion добавлен в deps ВСЕХ 10 profile-fetch useEffect — после
  каждого применения степпер/бейджи/метрики/Обзоры перезапрашиваются
  автоматически (React 18 batching: один бамп = один ре-рендер = один
  повторный fetch каждой остановки; гардируется ассертом
  counts.decomposition === 2).
- Снят ленивый гейт activeCheckId у feature_eng/scaling — контракт
  унифицирован: «статусы всех 10 остановок всегда отражают текущий
  датасет» (самый тяжёлый профиль — STL декомпозиции — и ранее считался
  при монтировании; +2 запроса на монтирование в пределах принятого
  компромисса «8 запросов при монтировании», комментарий к missing-эффекту).
- Узкая зона инвалидации СОХРАНЕНА: смена режима остановки
  (PUT preprocessing-check-modes) и кнопка «Пересчитать» бампят только
  собственный xxxRefreshKey — датасет не мутируют, чужие профили не
  инвалидируют (гард-тест: счётчик decomposition не растёт).

### TDD (AGENTS.md: RED -> GREEN)

- RED (подтверждён ДО правки компонента, ровно 3 падения): (1)
  «after applying missing corrections the blocked decomposition stop
  refreshes without a page reload» — полный сценарий постановки: мок
  декомпозиции blocked (skipped + reason) до apply и done после; ассерты
  бейджа «В ряду 2 пропусков…» → «STL выполнен, остаточная диагностика
  пройдена», степпер done («Пройдено»), counts.decomposition === 2;
  (2) симметрия «выбросы → пропуски» (after applying outliers
  corrections the missing stop refreshes); (3) статусы feature_eng/
  scaling загружаются на монтировании без визита остановки. Гард-тест
  (4) «saving a stop's mode does not invalidate other stops' profiles»
  зелёный уже в RED (фиксирует корректное существующее поведение).
- GREEN: правки только TsAnalysisPreprocessing.tsx → 4/4 новых +
  61/61 всего файла.

### Верификация (полная регрессия)

- Frontend: npx jest — 113 сюит / 1257 passed / 0 failed (полная
  монорепо-регрессия; guard-тесты зелёные БЕЗ правок — arithmetics
  baseline e99cd1f 113/1253, +4 новых).
- npm run typecheck:all — 0 ошибок; npm run build:all — Compiled
  successfully x2 (embedded + standalone).
- Backend не затронут (0 файлов .py) — pytest-прогон не требуется
  (прецедент frontend-only задач EDA-2/PREPR-1/VALID-2).
- Мутационная кампания не проводилась (фронтовый diff 55 строк); критические
  точки контракта прижаты тестами: снятие datasetVersion из deps любого
  эффекта ловится тестом (1), гейт-регрессия — тестом (3), расширение
  зоны инвалидации на смену режима — гардом (4).

### Границы

- DatasetPassportPanel (stage="exit") сознательно не инвалидируется
  datasetVersion: паспорт — точка РУЧНОЙ фиксации («Зафиксировать»),
  семантика подтверждённого снимка, а не автоматического профиля.
- Кнопка «Пересчитать свойства после преобразования» для 6 остановок без
  onClick (pre-existing) не тронута — вне мандата постановки.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); работа в ZIP
  download/task_prepr3_profile_auto_refresh.zip.

Изменённые/новые файлы:
- packages/ui/components/TsAnalysisPreprocessing.tsx (datasetVersion +
  deps 10 эффектов + снятие гейта feature_eng/scaling + 10 onApplied)
- packages/ui/components/TsAnalysisPreprocessing.test.tsx (+4 кейса в
  новом describe «автообновление профилей после применения исправлений»)## Task TSKV2-1 (2026-09-18) — v2, первый вертикальный срез «Причины» (XAI, паттерн C §11.2): бэкенд-эндпоинт + фронтенд страницы, полный TDD-цикл

Синхронизация: main@e99cd1f (DKT-1 + DKT-2; TSKIA-1..4 уже в истории), дерево
чистое (stash-остатки прошлой сессии подтверждены включёнными в 4157b6f и
сброшены). Постановка тимлида: v2 — первый вертикальный срез «Причины»
(XAI, паттерн C по §11.2), требует бэкенд-эндпоинта и полного TDD-цикла;
ZIP в download; AGENTS.md.

### Декомпозиция (§10 дополнения: v2 = срез «Причины» + чип истории запусков + configurable)

- TSKV2-1 — вертикальный срез «Причины» (§10.1, паттерн C §11.2) — ЭТОТ СРЕЗ;
- чип истории запусков (маленький бэкенд-эндпоинт списка запусков) — НЕ затронут,
  отдельная задача v2 (в постановке тимлида срез ограничен «Причинами»);
- прототип `configurable` на «Принятии решений» — НЕ затронут (v2, отдельный срез).

### Проектирование (§10.1: «просмотр уже вычисленного», простейший контракт входа)

Инвентаризация вычисленных фактов (программно, не по памяти):
- Feature importance: `backtesting.py:650` — каждый fold бэктеста
  tree-моделей (random_forest/xgboost/lightgbm/catboost — 4 адаптера,
  model_impls) persist-ит `feature_importance` с oracle-привязкой
  (`bind_feature_importance`, feature_plan.py:962: plan_id/matrix_hash/
  fit_policy + importances[]). Данные УЖЕ вычислены и лежат в
  `session.modeling_artifacts["backtests"][model_id]["folds"][i]`.
- Model Card: `create_model_card` reserves `feature_importance: None`
  (modeling_session.py:3255) — поле-заготовка, никогда не заполняется.
  Артефакт бэктеста привязан к карте через training.backtest_run_id.
- Granger: EDA считает по запросу аналитика (GET /dataset/eda-feature-selection,
  session.py:808) и НЕ persist-ит в сессию — «уже вычисленного» артефакта нет.
- SHAP/PDP: движком НЕ вычисляются нигде (grep: import shap — 0 файлов).
- Ensemble-карты: fold-importances членов в ensemble_backtests, но честная
  агрегация по членам — отдельное решение (прецедент честного отказа
  ансамбля — test_forecast_rejects_ensemble_card_honestly).

Следствие (честная маркировка §9.1): первый срез отдаёт БЕЗ пересчётов
только fold-importance как доступный метод; Granger/SHAP/PDP — строки
реестра методов со статусом not_computed и честной причиной (не
фиктивные данные). Контракт входа `model_card` (§2 исходной спеки).

### Решение: бэкенд

- НОВЫЙ apps/api/routers/tasks_session.py — GET /causes (prefix
  /v1/session/tasks, mounting в main.py рядом с modeling_session):
  card_id опционален (дефолт — последняя карта по created_at, тот же
  порядок, что TaskArtifactRibbon); нет карт — 409 с причиной (хаб
  гейтит, прямой URL — честный отказ, прецедент 409 моделирования);
  ensemble-карта — методы с not_computed/причиной, не 5xx.
- Агрегация fold-importance: внутри каждого fold доля importance/sum
  (сырые MDI разных fold несопоставимы по масштабу), средняя доля по
  fold, сортировка по убыванию; per-fold сырые значения и matrix_hash —
  в деталь фактора; provenance (run_id/plan_id) — в метод.
- Ответ: {card, methods:[{method_id,title,status,reason?,factors?,...}]}.

### Решение: фронтенд (паттерн C §11.2, строительные блоки таблицы §11.2)

- НОВЫЙ packages/ui/components/TasksCauses.tsx: 3 колонки по образцу
  AppliedTasksNavigator (aside w-60 методы → aside w-80 факторы →
  section деталь); бейджи «Когда использовать»/«Что нужно для запуска»
  (классы StaticHalfBadge NavigatorHero); правая колонка — «Панель
  управления» (обязательный блок §11.2) с деталью фактора: BarChart
  средних долей факторов (выбранный подсвечен, топ-12) в контейнере
  h-[468px] под ExpandableChartPanel + ExpandableChartsProvider
  (обязательные блоки §11.2), таблица per-fold под графиком; цвета
  Recharts — var(--c-*) (урок DKT-3: новых hex-литералов не создавать).
- НОВЫЙ packages/ui/lib/tasks.ts: типы 1:1 ответу бэкенда + fetchCauses
  (sessionApiUrl, credentials include — прецедент forecasting.ts).
- Гейтинг страницы: stages.modeling !== done → честное пустое состояние
  с микро-CTA на /modeling (прецедент R5-CTA хаба) БЕЗ похода в сеть;
  409 бэкенда → состояние с причиной.
- НОВЫЙ apps/standalone/app/tasks/causes/page.tsx (замена плейсхолдера);
  экспорт в packages/ui/index.ts.

### Точки изменения и риски

- main.py (включение роутера — 1 строка); guard-тесты существующих
  эндпоинтов не задействуют /v1/session/tasks (проверено grep).
- Риск 500 на вложенных артефактах: все чтения через .get-цепочки;
  отсутствующий бэктест-артефакт карты → not_computed с причиной, не 500.
- Риск гидратации: fetch только в useEffect с alive-флагом (прецедент
  TaskArtifactRibbon); jsdom-тесты мокают lib/модуль.
- Риск Recharts в jsdom: polyfills jest.setup.js (ResizeObserver/
  IntersectionObserver) — прецеденты EdaCorrelationOverview.test.
- Тест-план (TDD RED→GREEN): tests/api/test_tasks_causes.py (контракт
  409/статусы/агрегация/ensemble/provenance/порядок сортировки);
  TasksCauses.test.tsx (паттерн C: 3 колонки, бейджи, статусы методов,
  деталь фактора, honest-состояния, 468px+ExpandableChartPanel).

### TDD (AGENTS.md: RED -> GREEN, оба контура)

- Бэкенд RED подтверждён ДО реализации: 9/9 падений ровно одного вида
  (404 {"detail":"Not Found"} — маршрута /v1/session/tasks/causes нет).
  НОВЫЙ tests/api/test_tasks_causes.py: контракт входа (409 без карт с
  причиной про Model Card; 404 неизвестный card_id), реестр 4 методов
  с честными статусами (fold_importance available, granger/shap/pdp
  not_computed с непустой причиной и factors=null), агрегация
  (сумма долей внутри КАЖДОГО fold = 1; сумма средних долей = 1;
  сортировка по убыванию; per-factor fold_values отсортированы),
  provenance (backtest_run_id/plan_id/n_folds=2, matrix_hash в деталях),
  дефолт-карта = последняя по created_at + явный card_id,
  классическая модель (ets) — not_computed с причиной «не вычисляет
  важность», ensemble-карта — честный отказ агрегации (сеанс через
  посев model_cards: полный HTTP-путь до ensemble требует tuning),
  отсутствующий артефакт бэктеста — 200/not_computed, не 500.
- GREEN: 9/9. Находка в процессе: повторный compare/evaluate
  инвалидирует прежние model_cards (lineage-дисциплина
  modeling_session.py:2941/2985) — тест «две карты» построен на
  повторном POST /card под тем же selection (как в селекторе
  прогнозирования), а не на новом сравнении.
- Фронтенд RED подтверждён ДО реализации: TS2307 (отсутствие модулей
  TasksCauses/lib/tasks — только и именно это). GREEN 8/8: заголовок +
  бейджи; honest-empty без сети с CTA /modeling; loading до гидратации
  без сети; паттерн C (4 метода, недоступные disabled+aria-disabled,
  причина видна в списке), «Панель управления», окно h-[468px],
  ExpandableChartPanel-кнопка; факторы с долями (aria-pressed,
  переключение, .recharts-responsive-container — jsdom-прецедент
  NavigatorChartPreview: внутренний SVG в jsdom не строится);
  провенанс run/plan; недоступные методы не выбираются (клик без
  эффекта); ошибка бэкенда — role="alert" с причиной сервера.

### Верификация (полная регрессия)

- npx jest: 114 сюит / 1261 теста — все зелёные (было 112/1230 после
  TSKIA: +2 сюиты этого среза; старые без правок).
- typecheck:all (embedded + standalone) — без ошибок.
- npm run build: standalone успешна, маршрут /tasks/causes на месте.
- Backend: полный pytest tests/ — 2346 passed / 9 failed / 3 errors /
  24 skipped. Все 9+3 — ПРЕДСУЩЕСТВЕННЫЕ, точное множество Task 145:
  нейро-группа не установлена (integration-paths deepar/lstm/nbeats/
  nhits/tft fail-closed, v2-дескрипторы, neural capacity,
  catalog_only-метрики) + 3 snapshot-ошибки test_preprocessing
  (версии pandas/numpy venv против пинов). Ни одного падения от
  правок среза (stash-прогон чистого HEAD e99cd1f воспроизвёл те же 17).
- Окружение восстановлено до сертификационной эпохи после сброса
  между сессиями: pandera/PyWavelets/holidays/missingno/openpyxl/
  plotly/ruptures/prophet 1.4.0/arch/tbats/statsforecast 2.1.1;
  statsmodels 0.14.5 -> 0.15.0 (пин requirements.txt) — это сняло
  16 предсущественных падений forecasting-контура (parametric
  simulation требовал API statsmodels>=0.15).

### Границы

- Реестр методов среза: fold_importance (уже вычислено, Task 127)
  доступен; granger/shap/pdp — честные not_computed-строки (Granger
  не persist-ится сессией, SHAP/PDP движок не вычисляет) — пересчётов
  и синтетики нет (§10.1 «просмотр уже вычисленного»).
- Ensemble-карты: честный отказ агрегации по членам — отдельное решение.
- Чип истории запусков (v2) и прототип configurable («Принятие
  решений») — НЕ затронуты, отдельные задачи v2.
- Multi-карточный селектор на странице — v3 (дефолт = последняя карта,
  явный card_id поддержан эндпоинтом и lib).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); работа в ZIP.

Изменённые/новые файлы (ZIP: download/task_tskv2_causes_slice.zip):
- НОВЫЕ: apps/api/routers/tasks_session.py,
  tests/api/test_tasks_causes.py,
  packages/ui/lib/tasks.ts,
  packages/ui/components/TasksCauses.tsx,
  packages/ui/components/TasksCauses.test.tsx
- ИЗМЕНЕНЫ: apps/api/main.py (+include_router /v1/session/tasks),
  packages/ui/index.ts (+экспорт TasksCauses),
  apps/standalone/app/tasks/causes/page.tsx (плейсхолдер -> срез),
  worklog/worklog7.md (этот журнал).

### Ретаргет среза на 172be75 (2026-09-18, итерация 2)

- Повод: на машине тимлида рабочая копия уже на 172be75 (PREPR-3; цепочка
  e99cd1f → 1afb10b DKT-2R/3/4 → 172be75), а ZIP среза был собран от
  e99cd1f и перезаписал packages/ui/index.ts версией без экспорта
  ThemeToaster — typecheck standalone падал: TS2305 «@cisstat/ui has no
  exported member ThemeToaster» (app/layout.tsx:4).
- Действия: срез переналожен на 172be75 (без коммитов: reset → checkout
  172be75 → восстановление файлов среза). index.ts слит: экспорт
  TasksCauses (строка 276) соседствует с ThemeToaster (строка 603,
  из 1afb10b). Бэкенд-файлы (tasks_session.py, main.py) и page.tsx
  на 172be75 не менялись — применены как есть. worklog7.md — файл
  172be75 + секция TSKV2-1 в конце.
- Новая находка TDD-регрессии: heading-indigo-calibration.test.ts
  (DKT-2R) — реестр text-[#1e3a8a] ожидал 9 инстансов в 4 файлах,
  TasksCauses.tsx добавил 2 (hero-паттерн TasksHub: h1 + p). На базе
  e99cd1f этого теста ещё не было — потому первая итерация была зелёной.
  Тёмная ревизия класс-уровневая (тест «каждый класс имеет .dark-ревизию»
  зелёный без правок), поэтому по контракту реестра обновлён инвентарь:
  9→11 инстансов, 4→5 файлов (+TasksCauses.tsx), комментарий и шапка.
- Верификация на 172be75: pytest tests/api/test_tasks_causes.py — 9/9;
  jest TasksCauses — 8/8; jest ПОЛНЫЙ — 118 сюит / 1288 тестов, все
  зелёные; typecheck:all (embedded + standalone) — без ошибок (TS2305
  устранён); npm run build — успех, маршрут /tasks/causes на месте.
- Полный бэкенд-pytest не перегонялся: бэкенд-файлы среза байт-в-байт
  совпадают с верифицированной итерацией 1 (на e99cd1f: 2346 passed /
  17 предсущественных), main.py на 172be75 не менялся.
- ZIP (итерация 2): download/task_tskv2_causes_slice.zip — 10 файлов
  (9 из итерации 1 + packages/ui/heading-indigo-calibration.test.ts).
