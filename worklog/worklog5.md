# CISStat TS Analysis — Worklog

---

## Task 141 -- TFT vertical slice (четвёртый исполнитель Neural Runtime Contract Task 137; ПЕРВЫЙ срез с probabilistic-поверхностью MQLoss/quantiles)

Дата: 2026-09-12. Синхронизация: 412dd36 (Task 140 -- N-HiTS vertical
slice; третий исполнитель контракта Task 137; main@GitHub приведён к
этому же коммиту принудительным пушем тимлида).  Постановка
docs/modeling_task_list.md::Tasks 138-142, срез «Task 141 -- TFT» +
требования Task 137 («probabilistic losses и quantiles»).  Комментарий
тимлида: «TFT -- первый срез с probabilistic-поверхностью
MQLoss/quantiles».  Прецедент каркас -> исполнители: Task 138 (lstm),
Task 139 (nbeats), Task 140 (nhits); runtime-контракт Task 137 НЕ
меняется -- новый адаптер + запись реестра v2 + условный dispatch +
yaml (прецедент пар var/vecm, garch/egarch, lstm/nbeats/nhits).
MQLoss был явно зарезервирован за срезами 141-142 границей Task 138 и
рекомендацией ресертификации Task 137 (QuantileLoss в 3.2.2 сломана --
проб Task 137; рабочий probabilistic-путь -- MQLoss).

### Решение (по пунктам постановки)

1. **Probabilistic-поверхность -- ядро постановки**: точечный прогноз
   TFT -- МЕДИАНА MQLoss ("TFT-median", канонический point-прогноз
   pinball-loss 0.5); интервалы -- NATIVE-квантили функции потерь
   MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2]) -- честный двусторонний
   интервал [alpha/2; 1-alpha/2] процентилей (проб всех трёх alpha:
   0.01 -> [0.5; 99.5], 0.05 -> [2.5; 97.5], 0.10 -> [5; 95]);
   conformal-контур НЕ активируется (train_and_forecast(levels=()),
   PredictionIntervals не нужен -- квантили нативны loss'у).  Контракт
   Task 137 выполнен: resolve_probabilistic_loss("mqloss", levels=...)
   (NEURAL_PROBABILISTIC_LOSSES, уровни обязательны); метод интервалов
   в metadata -- NeuralIntervalPlan.method="neural_quantile_outputs";
   loss-дисклоужер -- "mqloss".  Первая probabilistic-модель
   платформы: происхождение интервалов честно РАЗЛИЧАЕТСЯ с тройкой
   lstm/nbeats/nhits (conformal) и дисклоужено в metadata.intervals.
2. **НАХОДКА (эмпирика level-семантики 3.2.2; НЕ блокирует, вне
   границ среза)**: суффикс квантильных колонок "-lo-<w>"/"-hi-<w>"
   кодирует ШИРИНУ интервала w (границы при 50±w/2 процентилях --
   исходники level_to_outputs/quantiles_to_outputs +
   add_conformal_distribution_intervals: alphas=[100-lv]), а НЕ прямой
   квантиль.  Следствие для сертифицированной тройки
   lstm/nbeats/nhits: извлечение lower=lo-2.5/upper=hi-97.5 из плана
   interval_levels_for_alpha(0.05)=(2.5, 50.0, 97.5) даёт фактически
   (48.75, 98.75) процентили -- нижняя граница схлопывается к медиане
   (контрольный замер LSTM: lo-2.5 ~ медиана, истинная 2.5-процентиль
   живёт в lo-97.5; clamp-инвариант при этом не нарушается, метрики
   точечного прогноза не затронуты).  Корректное исправление --
   уровень-ШИРИНА 100*(1-alpha) (для 0.05 -> 95.0) ИЛИ прямая
   декларация quantiles=; правка сертифицированных срезов -- отдельная
   постановка тимлида (задокументирована здесь; в Task 141 НЕ
   трогалась).  TFT реализует корректную семантику с первого дня:
   quantiles=[alpha/2, 0.5, 1-alpha/2], колонки по суффиксу ширины
   w=100*(1-alpha) ("TFT-lo-95.0"/"TFT-median"/"TFT-hi-95.0" для
   alpha=0.05).
3. **Готовая база сравнения quartet'а на одном runtime** (развитие оси
   Task 140): quartet исполнителей (nbeats/nhits/tft) имеет ИДЕНТИЧНЫЙ
   когортный контракт (objective="level_forecast",
   input_kind="univariate", engine="neuralforecast",
   dependency_group="neural", actions, пакеты, детерминизм) и ЕДИНУЮ
   точку исполнения -- neural_runtime.train_and_forecast (прижато
   test_tft_shares_one_level_cohort_with_the_neural_family: identity
   train_and_forecast и _resolve_time_axis, torch отсутствует в
   module-globals); OOF-метрики тройки ранжируемы с TFT напрямую
   (e2e-смоук [7]: nbeats mae=2.1995 / nhits mae=0.4788 / tft
   mae=3.3413 на бюджете env-рычага 60).
4. **Attention-ось -- архитектурный выбор честной альтернативы
   каталожного описания** («Attention-based architecture (Google).
   Интерпретируемость через attention weights»): bounded-параметр
   n_head ∈ {2, 4} (число голов InterpretableMultiHeadAttention;
   дефолт библиотеки 4).  Constraint архитектуры d_k =
   hidden_size // n_head: на неделимой паре библиотека падает
   AssertionError (проб: hidden_size=10, n_head=4); адаптерный гейт
   hidden_size % n_head == 0 даёт детерминированное сообщение ДО
   конструирования (стиль гейта неосуществимого окна).
5. **Единый runtime -- без собственной fit/predict-петли**: исполнение
   ТОЛЬКО через neural_runtime.train_and_forecast (бюджет max_steps,
   явный accelerator, random_seed=fold_seed в КОНСТРУКТОРЕ --
   seed-дисциплина ресертификации Task 137).  Адаптер не импортирует
   torch напрямую; MQLoss -- через require_neuralforecast().losses.
   pytorch (та же единственная точка тяжёлого импорта); гейт памяти
   Task 138c и thread-pinning наследуются автоматически.
6. **ds-ось -- конвенция neural-семейства ПЕРЕИСПОЛЬЗОВАНА** (lstm.
   _resolve_time_axis -- единый источник истины, НЕ дубликат):
   datetime + pd.infer_freq либо позиционная целочисленная сетка
   freq=1 (проб: TFT int-ds freq=1 OK).
7. **Гейт неосуществимого окна**: n_train < input_size + horizon --
   отказ ДО фита (библиотека с start_padding_enabled=False согласована
   -- проб: «TFT requires at least 48 training timestamp(s)»);
   TFT_MIN_TRAIN=30 (каталоговский мягкий порог 200 -- раньше,
   readiness-гейтом F04).
8. **Clamp-инвариант -- живой гейт квантильного пересечения**: для
   conformal-тройки crossing невозможен конструктивно, для MQLoss --
   возможен (heads независимы): гейт lower <= median <= upper
   зафиксирован fault-injection тестом и срабатывает на реальных
   недообученных прогонах (эмпирика: crossing 4/5 seeds при
   max_steps=3, 3/5 при 5, 0/5 при >= 10 на тестовом ряде) -- честный
   отказ fold'а вместо clamp-подмен.  Скоростной бюджет тестов 20
   подобран по этой эмпирике (production-константа 300 -- отдельным
   тестом БЕЗ monkeypatch).  Отсутствие медианы/квантильной колонки в
   отклике -- fail-closed (медиана обязательна: bare-колонки "TFT"
   при probabilistic-loss нет -- проб).
9. **Bounded params**: n_head {2, 4}, hidden_size [8, 128] (кратно
   n_head), input_size [8, 104], alpha whitelist {0.01, 0.05, 0.10}.
   Bool-коэрция целочисленных ручек отклоняется ЯВНО (урок
   НАХОДКИ-2/M6), тест параметризован по ВСЕМ int-ручкам.  yaml
   param_space: n_head x hidden_size x input_size = 8 trials (<= 64).
10. **Бюджет**: константа TFT_MAX_STEPS=300 (семейная конвенция
    lstm/nbeats/nhits; анти-тампер [100, NEURAL_MAX_STEPS_BOUND];
    тюнинг бюджета -- вне param_space) + env-рычаг
    CISSTAT_NEURAL_MAX_STEPS (дефолт env не задана -- сертифицированная
    константа; мусор/меньше 1 -- fail-closed; покрытие дефолт/
    override/garbage тестом).  Проводка бюджета до конструктора
    прижата двухслойным spy-тестом (урок НАХОДКИ-1/M18) -- модель
    несёт max_steps/random_seed/input_size И MQLoss как loss.
11. **Реестр v2 + dispatch + образ**: запись №23 -- model_id="tft",
    family_id="neural", adapter_id="neuralforecast-tft",
    objective="level_forecast", input_kind="univariate" (exog-канал
    нейро-моделей -- отдельная постановка, прецедент lstm:
    каталожное supports_exogenous не декларируется в реестре до своего
    среза), actions=_TUNABLE, engine="neuralforecast",
    required_packages=("neuralforecast",), deterministic=True (same-
    seed бит-в-бит пробом: max|diff|=0.0; другой seed -- 0.0147),
    dependency_group="neural", memory_class="standard",
    gpu="optional".  Dispatch: _register_neural_dispatch расширен
    (lstm + nbeats + nhits + tft), условная регистрация сохранена --
    gate реестр<->dispatch точен в обеих средах.  Production-образ:
    Dockerfile-проба 'TFT executable OK' (38 точек, n_head=2,
    input_size=8; воспроизведена локально; LSTM/N-BEATS/N-HiTS пробы
    перепроверены).
12. **Legacy synthetic-эндпоинт -- применим** (run_tft_backtest,
    прецедент lstm/nbeats/nhits/random_forest: одномерная level-
    модель), БЕЗ safe_backtest/Naive-fallback; короткий ряд -- честный
    отказ.

### TDD (RED -> GREEN)

- RED: tests/unit/test_tft_adapter.py (34 кейса) + tests/unit/
  test_tft_integration_paths.py (15 кейсов) -- collection errors на
  отсутствии модуля/экспортов; поверхность ожиданий снята пробом ДО
  написания тестов (прецедент Task 139/140).  Правки ОЖИДАНИЙ по
  снятой эмпирике: (а) match "кратным" (реальная формулировка гейта
  делимости); (б) скоростной бюджет 20 вместо 3 (эмпирика квантильного
  пересечения п.8 -- при 3 шагах crossing 4/5 seeds, honest гейт
  честно отказывал fold'а).
- GREEN: нейро-набор: 34 (tft adapter) + 15 (tft integration) + 26+14
  (nbeats/nhits) + 34+17 (lstm) + runtime/contract/capacity кейсы.
  Окружение: свежая установка requirements.txt + requirements-dev.txt +
  neural-группы (torch 2.14.0+cpu, neuralforecast 3.2.2 -- та же пара
  версий, на которой сертифицированы Tasks 137-140) + prophet 1.4.0 /
  statsforecast 2.1.1 -- полный production dispatch (import-гейт
  routers/models.py -- честный gate и в dev-среде).

### Изменённые/новые файлы

Новые:
- apps/api/model_impls/tft.py (~560 строк; адаптер TFT с
  probabilistic-поверхностью MQLoss/quantiles, docstring с полным
  обоснованием решений и находкой level-семантики)
- tests/unit/test_tft_adapter.py (34 кейса)
- tests/unit/test_tft_integration_paths.py (15 кейсов, включая
  fair-comparison оракулы quartet'а и honest provenance-тест
  интервалов)
- scripts/task141_tft_probe.py (эмпирический проб: поверхность
  конструктора/дефолты/quantiles-путь всех alpha/дубликат 50.0/
  делимость n_head/freq=1/детерминизм/неосуществимое окно -- PROBE OK)
- scripts/task141_e2e_smoke.py (7 этапов полного chain'а + этап
  сравнения quartet'а)

Изменённые:
- apps/api/model_execution.py: _tft_executor + запись реестра №23
- apps/api/model_impls/__init__.py: экспорт run_tft_backtest
- apps/api/routers/models.py: dispatch (lstm + nbeats + nhits + tft) +
  импорт
- rules/modeling.yaml: tft param_space (8 trials) + комментарий Task 141
- apps/api/Dockerfile: TFT-проба в production-цепочке
- apps/api/requirements-neural.txt: дисклоужер статуса (четвёртый
  исполнитель; deepar -- Task 142)
- Count-гейты 22->23 честно в 13 файлах: test_lstm/
  test_nbeats/test_nhits integration_paths (dispatch-конвенция
  {lstm,nbeats,nhits,tft}, count 23/19), test_garch/test_egarch
  integration_paths (subprocess-arith 23/19), test_var_integration_paths
  (subprocess 'ok 23'), test_modeling_mvp_certification
  (_EXPECTED_NEURAL={lstm,nbeats,nhits,tft}, PREDICTORS), 
  test_model_execution_contract (CERTIFIED_IDS+NEURAL_IDS+tft-
  descriptor; catalog-only пример -> deepar), test_model_readiness_
  candidates (catalog-only tuple без tft; runnable 19 / catalog-only 1;
  короткий профиль: blocked 13, tft explain «60 < 200 (требуется
  Temporal Fusion Transformer)»; deepar -- по ПОЛНОМУ каталогу),
  test_backtesting_engine (sweep исключает tft), test_eda_model_matrix
  (tft blocked/ready-ось), tests/api: test_models_backtest_real
  (expected+tft), test_models_candidates (DL-пул без tft; catalog-only
  пример -> deepar), test_modeling_workflow (catalog-only пример ->
  deepar).

### Границы Task 141 (что осознанно НЕ сделано)

- Исправление level-семантики сертифицированной тройки lstm/nbeats/
  nhits (НАХОДКА п.2: conformal-границы фактически (50-w/2; 50+w/2)
  процентили вместо декларируемых alpha/2; 1-alpha/2) -- требуется
  отдельная постановка тимлида (правка сертифицированных срезов +
  ресертификация); в Task 141 тройка НЕ трогалась.
- hist_exog/stat_exog (поверхность конструктора есть -- hist_exog_list;
  реестр НЕ декларирует exog), early stopping, dropout/attn_dropout/
  n_rnn_layers/scaler_type-ручки -- поверхность контракта для среза 142
  и exog-постановки.
- yaml requires_gpu: true для tft НЕ менялось (методологическая ось
  D06 NOT_RECOMMENDED на CPU -- независимая от production-готовности
  platform_status; Tasks 138/139/140 так же не меняли lstm/nbeats/
  nhits).
- Реестровая запись deepar не тронута (честный catalog_only до среза
  142); DeepAR остаётся panel-постановкой (min_series=5).
- scripts/task138/139/140_e2e_smoke.py НЕ модифицировались (снимки
  своего момента -- прецедент; актуальный смоук -- task141).
- GPU-исполнение: runtime Task 137 фиксирует device="cpu"; gpu=
  "optional" -- декларация capability, не переключатель.

### Верификация

- TDD цикл выше; нейро-набор: 34 + 15 = 49 новых кейсов tft.
- Полная регрессия: **2379 passed / 0 failed** (unit 1654 = 1605 + 49
  tft; api 625; прочие 100) -- арифметика сходится точно.  compileall
  OK; app-import OK; pip check (No broken requirements); rules-
  smoketest exit=0; фронтенд не затронут (git status -- backend-only,
  0 файлов .ts/.tsx).
- Прод-инварианты: PRODUCTION_BACKTEST_MODEL_IDS == 23; tft
  backtest/tune/diagnostics; deepar catalog_only ([]); consistency-
  gate dispatch<->readiness зелёный.
- E2E смоук scripts/task141_e2e_smoke.py: 23 connected -> dispatch-gate
  -> tft ready (backtest/tune/diagnostics), deepar catalog_only,
  статистика 19/1 -> реальный OOF-бэктест 2 folds (mae=3.3413) ->
  bounded tuning grid 8 trials -> legacy однорядный путь (mae=0.7667)
  -> база сравнения quartet'а (nbeats mae=2.1995 / nhits mae=0.4788 /
  tft mae=3.3413, один cohort, идентичные когортные контракты,
  честное различие provenance интервалов).  E2E SMOKE OK (прогон на
  env-рычаге CISSTAT_NEURAL_MAX_STEPS=60 -- машина слабее
  production-инстанса; дефолтная константа 300 прижата тестом).
- Проб scripts/task141_tft_probe.py: PROBE OK (поверхность
  конструктора: hidden_size=128/n_head=4/dropout=0.1/scaler_type=
  robust; quantiles-путь всех трёх alpha с честными границами
  процентилей; дубликат 50.0 -- подтверждена избыточность явной
  медианы; делимость n_head -- AssertionError библиотеки; freq=1;
  same-seed max|diff|=0.0 / cross-seed 0.0147; неосуществимое окно --
  честный отказ библиотеки); Dockerfile-пробы LSTM/N-BEATS/N-HiTS/TFT
  воспроизведены локально ('LSTM/GRU executable OK',
  'N-BEATS executable OK', 'N-HiTS executable OK', 'TFT executable OK').
- Окружение: neuralforecast 3.2.2 + torch 2.14.0+cpu -- те же версии,
  на которых сертифицированы Tasks 137/138/139/140.

Изменённые/новые файлы (ZIP: download/task141_tft_vertical_slice_worklog4.zip):
- НОВЫЕ: apps/api/model_impls/tft.py, tests/unit/test_tft_adapter.py,
  tests/unit/test_tft_integration_paths.py,
  scripts/task141_tft_probe.py, scripts/task141_e2e_smoke.py
- ИЗМЕНЁННЫЕ: apps/api/model_execution.py, apps/api/model_impls/__init__.py,
  apps/api/routers/models.py, rules/modeling.yaml, apps/api/Dockerfile,
  apps/api/requirements-neural.txt,
  tests/unit/{test_garch_integration_paths, test_egarch_integration_paths,
  test_var_integration_paths, test_lstm_integration_paths,
  test_nbeats_integration_paths, test_nhits_integration_paths,
  test_model_execution_contract, test_modeling_mvp_certification,
  test_model_readiness_candidates, test_backtesting_engine,
  test_eda_model_matrix}.py,
  tests/api/{test_models_backtest_real, test_models_candidates,
  test_modeling_workflow}.py, worklog4.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@412dd36 + перечисленные изменения.

## Task 141a -- Правка width-семантики сертифицированной тройки lstm/nbeats/nhits (отработка НАХОДКИ Task 141 п.2, постановка тимлида)

Синхронизация: main@952653e (Task 141 TFT vertical slice, четвёртый
исполнитель контракта Task 137).  Постановка тимлида: «Давай сразу
отработаем найденную тобой находку.  Если требуется внесение изменений,
реализуй это» -- НАХОДКА Task 141 п.2 (level-семантика neuralforecast
3.2.2) переведена из статуса «задокументирована, вне границ среза» в
исполнение по полному циклу AGENTS.md (TDD RED->GREEN, контрольный
замер, полная регрессия, сборка обеих оболочек).

### Постановка (из находки Task 141 п.2)

Суффиксы квантильных колонок '-lo-<w>'/'-hi-<w>' отклика neuralforecast
3.2.2 кодируют ШИРИНУ интервала w (границы при 50±w/2 процентилях --
исходники level_to_outputs/quantiles_to_outputs round(100-200*q, 2) +
conformal add_conformal_distribution_intervals: alphas=[100-lv]), а НЕ
прямой квантиль.  Следствие для сертифицированной тройки
lstm/nbeats/nhits: извлечение lower=lo-2.5/upper=hi-97.5 из плана
interval_levels_for_alpha(0.05)=(2.5, 50.0, 97.5) даёт фактически
(48.75, 98.75) процентили -- нижняя conformal-граница схлопывается к
медиане.  TFT реализует корректную семантику с первого дня (прямая
декларация quantiles=[alpha/2, 0.5, 1-alpha/2] + суффикс ширины
w=100*(1-alpha)) -- не затрагивается поведенчески.

### Диагностика (контрольный замер на реальном runtime)

scripts/task141_fix_width_semantics_probe.py (НОВЫЙ, три секции):
- СТАРЫЙ запрос predict(level=[2.5, 50.0, 97.5]): колонка LSTM-lo-2.5
  отстоит от точки на 0.27% масштаба (схлопнута к медиане -- 48.75-й
  процентиль), истинная нижняя граница живёт в LSTM-lo-97.5 (6.70%).
- НОВЫЙ запрос predict(level=[95.0]) (ширина w=100*(1-alpha)):
  LSTM-lo-95.0/hi-95.0 симметричны -- по 6.58% масштаба с каждой
  стороны (= 2.5/97.5 процентили).
- АДАПТЕР ПОСЛЕ ПРАВКИ: полный путь _lstm_fit_predict на реальном
  runtime -- metadata.intervals = {'method': 'conformal', 'alpha':
  0.05, 'levels': [2.5, 50.0, 97.5], 'width': 95.0}; границы симметричны
  по 4.91% масштаба; lower < point < upper, схлопывания нет.

### Решение

1. **Единый источник истины ширины -- контракт** (apps/api/
   neural_contract.py): НОВАЯ функция interval_width_for_alpha(alpha)
   -> round(100*(1-alpha), 2) (конвенция суффиксов quantiles_to_outputs
   3.2.2); fail-closed валидация alpha в (0,1) -- стиль
   interval_levels_for_alpha.  Docstring interval_levels_for_alpha
   дополнен ПРЕДУПРЕЖДЕНИЕМ: levels -- ПРОЦЕНТИЛИ плана (семантика
   интервала), НЕ значения параметра level 3.2.2; для запроса отклика
   использовать interval_width_for_alpha.
2. **Тройка lstm/nbeats/nhits -- минимальная честная правка** (identical
   паттерн в трёх адаптерах): (а) в train_and_forecast уходит
   levels=(width,) вместо plan.levels (запрос ШИРИНЫ, один уровень --
   шесть колонок дефектного запроса больше не создаются); (б) извлечение
   _interval_column по суффиксам ширины lo-<w>/hi-<w>; (в) metadata
   intervals дисклоужирует ОБА плана: levels = процентили интервала
   (контракт NeuralIntervalPlan, без изменений) + НОВЫЙ ключ width =
   фактическая ширина запроса (консистентно с дисклоужером TFT);
   (г) docstring-шапки адаптеров переписаны под width-семантику.
3. **neural_runtime.py -- docstring честен**: параметр ``levels`` --
   ШИРИНЫ интервалов для predict(level=[...]) (границы при 50±w/2
   процентилях), прецедент (10.0, 90.0) «из NeuralIntervalPlan» убран.
4. **TFT -- дублирование устранено**: локальный width=round(100*(1-
   alpha), 2) заменён переиспользованием interval_width_for_alpha
   (поведение идентично; _quantile_plan прижат тестом равенства с
   контрактной функцией на 4 alpha).
5. **model_execution.py**: docstring трёх executor'ов (lstm/nbeats/
   nhits) обновлены под width-семантику; metadata passthrough не менялся.

### TDD

- RED: interval_width_for_alpha не существует (ImportError при
  коллекции) + поведенческие оракулы: запрос levels==(95.0,) spy'ем,
  извлечение различимыми значениями (дефектные lo-2.5/hi-97.5 vs
  корректные lo-95.0/hi-95.0 в одном фейковом отклике), metadata
  width-дисклоужер.
- GREEN: контракт + тройка + TFT-рефакторинг.
- Новые тесты: contract -- 4 (values, round-trip 50±w/2 == план,
  анти-регрессия «ширина не равна уровню», fail-closed); тройка --
  3 x test_conformal_request_and_extraction_use_width_semantics;
  tft -- test_quantile_plan_width_is_the_contract_width.
- M10 fault-injection мониторы тройки переведены на суффиксы ширины
  (lo-95.0/hi-95.0) -- ломающий монитор остаётся на фактическом пути
  извлечения.

### Верификация

- Полная регрессия: **2387 passed / 0 failed** (unit + api + snapshot;
  neural-тесты ИСПОЛНЯЛИСЬ -- neuralforecast 3.2.2 + torch 2.14.0+cpu
  установлены в окружении; базлайн до правки 144 passed на тройке +
  контракт).
- Контрольный замер (probe, реальный runtime) -- все три секции OK
  (см. Диагностику); дефект воспроизведён, правка подтверждена.
- Фронтенд не затронут (0 файлов .ts/.tsx); AGENTS.md верификация:
  npm run typecheck:all -- OK (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 static pages
  обеих оболочек).
- NOTE окружение: чистая песочница; зависимости восстановлены из
  requirements.txt + requirements-dev.txt + neuralforecast==3.2.2 +
  torch CPU-колёса; pip check -- No broken requirements.  Промежуточный
  сбой коллекции («Реестр готовности моделей расходится...») --
  артефакт недоустановленного окружения (statsforecast отсутствовал ->
  tbats выпадал из readiness), не правки; после доустановки гейт зелёный.
- Поведение точечного прогноза НЕ менялось (point-путь не тронут --
  метрики сравнения моделей валидны); исправлен ТОЛЬКО origin/смысл
  интервальных границ тройки (ранее lower ~ медиана).

### Границы Task 141a (что осознанно НЕ сделано)

- scripts/audit_scripts/cert140_*.py, scripts/task138/139/140/141_*.py
  НЕ модифицировались -- characterization-артефакты своего момента
  (прецедент OR11i); актуальная семантика прижата новыми тестами.
- Исторические записи журнала ниже НЕ редактировались (журнал
  append-only; найденная дефектная семантика остаётся честной историей
  сертификаций Tasks 138-140).
- Историческая численность: метрики точечного прогноза не затронуты;
  пересчёт ретроспективных OOF-интервалов не требуется (интервалы --
  производный слой, их честная версия начинается с этой правки).
- Frontend/UI -- без изменений (metadata.intervals дополнен ключом
  width; существующие потребители levels не ломаются -- ключ сохранён).

Изменённые/новые файлы (ZIP: download/task141a_width_semantics_fix.zip):
- НОВЫЕ: scripts/task141_fix_width_semantics_probe.py
- ИЗМЕНЁННЫЕ: apps/api/neural_contract.py, apps/api/model_impls/{lstm,
  nbeats, nhits, tft, neural_runtime}.py, apps/api/model_execution.py,
  tests/unit/{test_neural_contract, test_lstm_adapter, test_nbeats_adapter,
  test_nhits_adapter, test_tft_adapter}.py, worklog4.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@952653e + перечисленные изменения.

## Task 139a -- Применение исправлений находок F1/F2 сертификации Task 139 (N-BEATS: гейт окна +2, pair-маппинг mlp_units) по полному циклу TDD

Дата: 2026-09-13. Синхронизация: main@f7596e1 (Task 141a -- width-
семантика тройки; проверки аудитора на дереве f7596e1 показали: обе
находки сертификации Task 139 в коде НЕ исправлены -- F1: гейт
`nobs < input_size + horizon` в nbeats.py, F2: `[[hidden] * mlp_layers
for _ in range(2)]` в _stack_kwargs; артефактов "Task 139a" в истории/
дереве нет).  Постановка тимлида: «Если исправления не применены, внеси
необходимые правки» -- находки F1/F2 (НАХОДКИ сертификации Task 139,
обе латентные не-блокирующие) переведены в исполнение по полному циклу
AGENTS.md (TDD RED->GREEN, мутации, полная регрессия, сборка).

### Постановка (из находок сертификации Task 139)

- **F1 -- honesty-гэп гейта окна на точной границе**: гейт
  `nobs < input_size + horizon` пропускал полосу [input+h, input+h+1],
  где conformal-конфигурация 3.2.2 (PredictionIntervals в fit --
  калибровочные окна) отказывала СЫРЫМ Exception библиотеки («Time
  series is too short for training» на input+h; «No windows available
  for training» на +1) вне таксономии ValueError/NeuralContractError
  адаптера (мэппинг 422/503 не применялся).
- **F2 -- ручка mlp_layers [1,4] неисполнима как заявлена**: библиотека
  читает inner-списки mlp_units как ПАРЫ [in_features, out_features];
  старый маппинг [[hidden]*layers for _ in range(2)] при layers=1
  падал RAW IndexError конструктора NBEATSBlock, значения 3/4
  проходили fit, но МОЛЧА эквивалентны 2 (max|diff| = 0.0 -- лишние
  entries игнорируются): ложная изменчивость bounded-ручки.

### Диагностика (контрольный замер на реальном runtime ДО правки)

scripts/task139a_fix_f1f2_probe.py (НОВЫЙ, три секции; OMP_NUM_THREADS=1,
CISSTAT_NEURAL_MAX_STEPS=6):
- F1: прямые вызовы библиотеки (БЕЗ адаптерного гейта) на 5 конфигах
  (input,h) = (8,2), (16,4), (24,3), (28,2), (48,6): на n=input+h --
  сырой «Time series is too short», на n=input+h+1 -- сырой «No windows
  available», на n=input+h+2 -- фит OK (len == horizon): ФОРМУЛА
  n_min = input+horizon+2 СТАБИЛЬНА.  Конфиг (8,1) непригоден для
  замера: библиотека отвергает h=1 с interpretable-стеком по
  архитектурной причине (см. Кандидат-нахождку ниже).
- F2 (старый маппинг, до правки): layers=1 -- IndexError: list index
  out of range; layers=3/4 vs 2 -- max|diff| = 0.0 (МОЛЧА эквивалентны).
- F2 (новый pair-маппинг, симуляция правки monkeypatch'ем
  _stack_kwargs): layers ∈ {1,2,3,4} -- все фиты OK; попарно различимы
  (max|diff| = 0.86 для пары 1 vs 2 и > 0 по всем парам); дефолт
  layers=2: структуры old/new литерально равны ([[h,h],[h,h]]),
  бит-паритет прогноза max|diff| = 0.0 -- сертифицированный путь
  бит-неизменен.  PROBE OK.

### Решение

1. **F1 -- гейт окна** (apps/api/model_impls/nbeats.py): условие
   `nobs < input_size + horizon + 2` (supervised-окно ПЛЮС 2
   калибровочных окна conformal-конфигурации 3.2.2); сообщение гейта
   называет причину («+ 2 калибровочных окна conformal-конфигурации
   3.2.2») -- честный ValueError ДО фита на всей полосе
   [input+h, input+h+1]; граница n == input+h+2 исполняется честно.
   Docstring-шапка адаптера (пункт 4) переписана под формулу с
   обоснованием и ссылкой на проб.
2. **F2 -- pair-маппинг** (_stack_kwargs): `mlp_units = [[hidden,
   hidden] for _ in range(mlp_layers)]` -- inner-списки как пары
   [in, out]; весь диапазон [1,4] исполним и реально различим; дефолт
   2 литерально совпадает со старым маппингом ([[32,32],[32,32]]) --
   сертифицированный путь бит-неизменен (прижат бит-паритет тестом
   old-vs-new маппинга).  Docstring _stack_kwargs переписан.
3. **Таксономия/поведение вне полосы НЕ менялись**: point-прогноз,
   conformal-контур, clamp-инвариант, MIN_TRAIN-гейт (проверяется
   ПЕРВЫМ -- O4 (a/b) зелёные), bounded-валидация, env-рычаг --
   бит-неизменны; исправлена ТОЛЬКО полоса гейта и маппинг ручки.

### TDD (RED -> GREEN)

- RED: 4 новых кейса в tests/unit/test_nbeats_adapter.py (секция 2b):
  (1) F1-boundary: n=input+h и n=input+h+1 -> ValueError match
  "калибров" ДО фита, n=input+h+2 -> фит OK (RED: сырой Exception
  библиотеки «Time series is too short...»); (2) F2-структура:
  _stack_kwargs(...,1) == [[32,32]], (...,"generic",...,4) == [[8,8]]*4,
  дефолт == [[32,32],[32,32]] (RED: [[32],[32]] != [[32,32]]);
  (3) F2-различимость: все пары (1,2,3,4) max|diff| > 0 (RED:
  IndexError на layers=1); (4) F2-бит-паритет дефолта: подмена старого
  маппинга -> бит-в-бит тот же прогноз (страж, зелёный в обеих фазах).
  3 failed / 1 passed -- RED подтверждён, падения точно дефектные.
- GREEN: правки nbeats.py -> 31/31 в test_nbeats_adapter.py.
- Characterization-оракулы сертификации (scripts/audit_scripts/
  cert139_oracles.py, задокументированное условие «при исправлении
  находок пробы упадут: пересмотреть characterization»):
  test_f1_window_boundary_band_escapes_as_raw_exception ->
  test_f1_fixed_window_band_gets_honest_value_error_before_fit;
  test_f2_mlp_layers_surface_is_infeasible_as_declared ->
  test_f2_fixed_mlp_layers_range_executable_and_distinguishable
  (оракулы ИСПРАВЛЕННОГО состояния).  Попутно восстановлены 4
  оракула, дрейфовавшие после width-правки Task 141a (зелёный
  базлайн сертификации был до неё): O5/O5b/O6 -- синтетические кадры
  переведены на суффиксы ШИРИНЫ lo-95.0/hi-95.0 (ловушки: дефектные
  lo-2.5/hi-97.5 и hi-как-lower активируют clamp-гейт); O7 --
  реестровая актуальность (23 модели, нейро-четверка зарегистрирована,
  catalog_only только deepar); комментарии O4 -- под формулу +2.
  Итог: 17/17 (было 13 passed / 4 failed на f7596e1).

### Мутационное тестирование (fresh-subprocess, SHA-контроль)

scripts/audit_scripts/cert139a_mutations.py (НОВЫЙ; протокол 138/139/
140 с адаптацией: эталон -- байт-копия файла на старте кампании, т.к.
правки Task 139a незакоммичены -- коммит/пуш запрещены AGENTS.md;
kill-подмножество: test_nbeats_adapter.py + cert139_oracles.py):
- M01 гейт +2 -> +1: KILLED (верхняя кромка полосы уходит в сырой
  Exception);
- M02 гейт +2 -> +0 (откат F1): KILLED;
- M03 pair-маппинг -> старый дефектный (откат F2): KILLED;
- M04 pair-маппинг -> мёртвая ручка range(2): KILLED (3/4 сливаются);
- M05 сообщение теряет калибровочную причину: KILLED (честная
  диагностика);
- M06 off-by-one `<=` (граница +2 ошибочно отклоняется): KILLED.
Итог: **6/6 KILLED**; восстановление байт-чистое (SHA-контроль).

### Верификация

- Полная регрессия: **2391 passed / 0 failed** (unit 1666 = 1662
  базлайн f7596e1 + 4 новых; api 625; snapshot 3) -- арифметика
  сходится.  neural-тесты ИСПОЛНЯЛИСЬ (neuralforecast 3.2.2 + torch
  2.14.0+cpu -- та же пара, на которой сертифицированы Tasks 137-141;
  окружение восстановлено из requirements.txt + requirements-dev.txt +
  neural-группы + prophet 1.4.0 / statsforecast 2.1.1; pip check -- No
  broken requirements).
- compileall OK; app-import OK; rules-smoketest exit=0; фронтенд не
  затронут (git diff -- 0 файлов .ts/.tsx).
- E2E-смоук актуального момента scripts/task141_e2e_smoke.py: ВСЕ
  ПРОВЕРКИ ПРОЙДЕНЫ (23 connected -> tft ready; quartet-сравнение:
  nbeats mae=2.1995 / nhits mae=0.4788 / tft mae=3.3413 -- nbeats mae
  бит-в-бит совпадает с базлайном Task 141 на том же env-бюджете 60:
  дефолтный путь unchanged end-to-end).  Dockerfile-проба N-BEATS
  воспроизведена локально: 'N-BEATS executable OK' (n=38, input=8,
  h=2: 38 >= 8+2+2 -- вне полосы, проба образа не затронута).
- Смоуки-снимки своего момента НЕ модифицировались (прецедент):
  task139_e2e_smoke.py ассертит счётчик 21 (свой момент до Tasks
  140/141) -- пре-существующий дрейф снимка, не правки (актуальный
  смоук -- task141).

### Кандидат-нахождка (НОВАЯ, латентная, НЕ-блокирующая; вне мандата Task 139a)

- **F3' (horizon=1 + interpretable/generic-семейство стеков)**:
  адаптер допускает horizon=1 (гейт `horizon < 1`), но библиотека 3.2.2
  отвергает h=1 со стеками trend/seasonality СЫРЫМ Exception
  «Horizon `h=1` incompatible with `seasonality` or `trend` in stacks»
  (проб, секция F1, конфиг (8,1); все n, не только полоса) -- тот же
  honesty-класс, что F1 (сырой Exception вне таксономии адаптера;
  движок бэктеста оборачивает в честный BacktestExecutionError).
  Рекомендация: либо adapter-гейт `stack_config == "interpretable" and
  horizon < 2 -> ValueError`, либо проверка исполнимости пары
  (стек, horizon) по эмпирике проба.  Требует отдельной постановки
  тимлида (поведенческое изменение сертифицированного среза).

### Границы Task 139a (что осознанно НЕ сделано)

- Аналогичные классы F1'/F2' в nhits.py (унаследованный гейт без +2;
  мёртвые ручки hidden_size/mlp_layers -- characterization в
  cert140_oracles.py/cert140_f1f2_probe.py) НЕ трогались: рекомендация
  сертификации Task 140 -- закрыть их фикс-срезом 140a ВМЕСТЕ.
  cert140_oracles.py на f7596e1 имеет пре-существующий дрейф 5
  оракулов (width-правка Task 141a не касалась audit-скриптов --
  проверено stash-прогоном: те же 5 failed ДО правок Task 139a);
  ревизия cert140_* -- мандат среза 140a.
- lstm/tft: гейты окон tft (`nobs < input_size + horizon`) вне мандата
  (tft -- probabilistic MQLoss БЕЗ conformal-калибровки: потребность
  +2 не следует переносить без собственного проба; lstm -- свой гейт
  MIN_TRAIN).
- yaml param_space не трогался (mlp_layers и раньше был вне
  param_space; ручки hidden_size/input_size -- без изменений).
- Исторические записи журнала НЕ редактировались (append-only).

Изменённые/новые файлы (ZIP: download/task139a_f1f2_fixes.zip):
- НОВЫЕ: scripts/task139a_fix_f1f2_probe.py,
  scripts/audit_scripts/cert139a_mutations.py
- ИЗМЕНЁННЫЕ: apps/api/model_impls/nbeats.py (гейт +2 + pair-маппинг +
  docstring-шапки), tests/unit/test_nbeats_adapter.py (docstring + 4
  кейса секции 2b), scripts/audit_scripts/cert139_oracles.py
  (F1/F2 -> оракулы исправленного состояния; ревизия дрейфа O4/O5/O5b/
  O6/O7), worklog4.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@f7596e1 + перечисленные изменения.

## Task w/n -- Главное меню: реформатинг классических вкладок в кликабельные бейджи (образец localnav apple.com/apple-intelligence; равные размеры по максимальному бейджу)

Дата: 2026-09-13.  Синхронизация: main@de70239 (Task 139a -- фиксы F1/F2
N-BEATS).  Постановка тимлида: главное меню платформы
(ts-standalone.vercel.app: «О платформе», «Загрузка», «Валидация», ...)
переформатировать из классических вкладок в кликабельные бейджи; шаблон
-- localnav apple.com/apple-intelligence («Overview»/«iOS»/«macOS»);
ЕДИНСТВЕННОЕ условие в отличие от образца -- размер бейджей одинаковый
по высоте и ширине (по максимальному бейджу).  Полный цикл AGENTS.md:
TDD RED->GREEN, живая эмпирическая верификация на production-сборке,
полная frontend-регрессия, typecheck/build обеих оболочек.

### Диагностика (точки изменения)

- Главное меню -- packages/ui/components/ModuleNav.tsx: ОБЩИЙ компонент
  standalone и embedded (пути одинаковые; правка одного файла --
  консистентная подача в обеих оболочках, прецедент единых
  контрактов 468px/адаптивных графиков).  8 пунктов: «О платформе»
  (hover-аккордеон, 5 ссылок HOME_ROUTES, Task 25) + 7 модулей
  (MODULES).  «Логи событий» -- справа, вне меню, не бейдж.
- Образец замерен на живой apple.com/apple-intelligence (headless
  Chromium, getComputedStyle): localnav-link -- pill border-radius 18px,
  padding 8px 15px, высота 36px, фон rgba(232,232,237,.5), текст
  rgba(0,0,0,.8); активный/продуктовый бейдж -- тёмная сплошная
  заливка.  Скриншот-пруф снят.

### Решение

1. **Бейдж-«таблетка»** (константа BADGE_BASE + badgeClassName(active)):
   rounded-full; h-9 (36px -- как localnav Apple); whitespace-nowrap
   (ширину колонки задаёт самый длинный заголовок, не перенос);
   justify-center (текст центрируется в равной ширине); неактивный --
   bg-neutral-100 text-neutral-700, hover -- bg-neutral-200 (адаптация
   полупрозрачного #e8e8ed Apple под токены платформы); активный --
   bg-brand text-white font-medium (аналог тёмного активного бейджа
   Apple в фирменном индиго платформы; консистентно с кнопкой
   «Загрузить датасет» и прошлым активным цветом text-brand).
   Адаптив: <lg -- px-3/text-[13px], lg+ -- px-4/text-sm.
2. **Равенство размеров по максимальному бейджу -- CSS-механика без
   JS**: контейнер строки inline-grid grid-flow-col auto-cols-fr
   items-stretch gap-2.  При max-content-ширине контейнера fr-колонки
   выравниваются по самой широкой (css-grid §12.7.1: flex fraction =
   max(track base/flex)); эмпирика пробы на реальном Chromium ДО
   реализации: 5 бейджей разного текста -- ровно одинаковые
   155.2x35px.  Высота -- h-9 на каждом бейдже + stretch сетки.
3. **Живая эмпирика production-сборки поймала латентный дефект и
   потребовала фикса**: первый замер на next start -- 7 бейджей ровно
   162.8px, но «О платформе» 150.9px: его Link обёрнут в div
   (wrapper hover-аккордеона), wrapper растягивается до ширины
   fr-колонки, а inline-flex-ссылка внутри -- по контенту.  Фикс по
   TDD (RED-тест на контракт w-full -> GREEN): w-full на триггере
   «О платформе».  Контрольный замер после пересборки: ВСЕ 8 бейджей
   ровно 162.8x36px (equalWidth/equalHeight true).
4. **Аккордеон «О платформе» СОХРАНЁН без изменений** (Task 25): 5
   ссылок HOME_ROUTES, role=menu/menuitem, aria-haspopup/aria-expanded,
   chevron с поворотом на 180.  Обоснование: постановка --
   реформатинг, не удаление функциональности; снятие подменю
   выбросило бы 5 маршрутов из навигации внутренних страниц
   (функциональная регрессия).  Панель absolute -- out of flow, ширину
   fr-колонок не меняет; overflow-visible на строке бейджей сохранён
   (панель не обрезается).
5. **aria-current="page"** на активных бейджах модулей (доступность);
   «Логи событий», max-w-[1600px]/px-6 контейнер, EventsLogDrawer --
   без изменений (guard-тесты).

### TDD (RED -> GREEN)

- RED: обновлён tests-файл packages/ui/components/ModuleNav.test.tsx
  (11 -> 20 кейсов): новые -- 8 pill-бейджей с точными href; контракт
  равных ширин (inline-grid + grid-flow-col + auto-cols-fr); единая
  форма/высота (rounded-full + h-9 + whitespace-nowrap); активная
  заливка (bg-brand + text-white + font-medium) / нейтральная
  неактивная; chevron в бейдже «О платформе»; w-full триггера
  (второй RED-цикл, после живого замера); overflow-visible строки;
  guard «Логи событий».  Первый RED: 8 failed / 11 passed -- падения
  точно на новом контракте; второй RED (w-full): 1 failed.
- GREEN: 20/20.  Мок usePathname -- /validation (активен бейдж
  «Валидация»).

### Верификация

- Полная frontend-регрессия: baseline до правки снят отдельно --
  94 сюиты / 879 passed / 0 failed; после -- **94 сюиты / 888 passed /
  0 failed** (879 + 9 новых/обновлённых кейсов ModuleNav -- арифметика
  сходится; регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 static pages
  обеих оболочек), финальная сборка с фиксами w-full.
- Живая эмпирика (next start production-сборки standalone, headless
  Chromium, 1600px): 8 бейджей -- ровно 162.8x36px каждый
  (equalWidth/equalHeight true); на /validation активен бейдж
  «Валидация» (bg-brand/text-white, ширина колонки неизменна 162.8);
  hover-аккордеон: visible/opacity 1, 5 menuitem, aria-expanded=true,
  chevron rotate-180; скриншоты главной и /validation сняты и
  просмотрены (pill-форма, равные размеры, активная заливка индиго).

### Границы задачи (что осознанно НЕ сделано)

- Правка применяется в ОБЕИХ оболочках (общий компонент) -- по
  архитектуре пакета; отдельный «standalone-only» вариант меню означал
  бы форк компонента.  Если embedded нужна другая подача -- отдельная
  постановка.
- Горизонтальный скролл строки бейджей на узких экранах НЕ добавлялся:
  overflow-x-auto обрезал бы absolute-панель аккордеона (тот же
  класс ограничения, что у прежних вкладок: whitespace-nowrap без
  скролла).  Суммарная ширина строки ~1300px (lg+) / ~1150px (md,
  компактные px/text) -- в контейнере 1552px; ниже ~1100px --
  пре-существующее поведение.  Мобильное меню -- отдельная постановка.
- Продуктовый бейдж Apple «Apple Intelligence» (логотип в тёмной
  заливке с glow) не воспроизводился: у нас роль «тёмного» бейджа
  играет АКТИВНЫЙ маршрут (динамический по pathname), что закрывает
  постановку; статичный бренд-бейдж -- вне мандата.
- Backend не затронут (0 файлов .py); yaml/каталог моделей не тронуты.

Изменённые/новые файлы (ZIP: download/task_wn_module_nav_badges.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/ModuleNav.tsx (бейджи-«таблетки»,
  сетка равных ширин, w-full триггера аккордеона, aria-current,
  docstring-шапка с обоснованием), packages/ui/components/ModuleNav.
  test.tsx (11 -> 20 кейсов: бейдж-контракт + guard'ы нетронутости)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@de70239 + перечисленные изменения.

---

## Task 140a -- Гейт окна +2 и оживление ручек hidden_size/mlp_layers в nhits.py (F1'/F2' сертификации Task 140) + исправление кандидата-нахождки F3' (nbeats interpretable x horizon=1) по полному циклу TDD

Дата: 2026-09-13. Синхронизация: main@de70239 (Task 139a -- применённые
фиксы F1/F2 сертификации Task 139; находка F3' Task 139a в дереве НЕ
исправлена, characterization cert140_oracles.py красный -- дрейф 5
оракулов width-правки Task 141a + реестровой актуальности Task 141).
Постановка тимлида: «вопрос по F3' и срезу 140a (гейт +2 и мёртвые
ручки в nhits.py -- тот же класс, characterization там по-прежнему
красный из-за width-дрейфа).  Разберись в данной проблеме и исправь» --
F3' + F1'/F2' переведены в исполнение по полному циклу AGENTS.md (TDD
RED->GREEN, проб, мутации, полная регрессия, смоук).

### Постановка (из находок сертификации Task 140 + кандидата-нахождки Task 139a)

- **F1' -- honesty-гэп гейта окна nhits.py** (унаследован от Task 139,
  аналог F1): гейт `nobs < input_size + horizon` пропускал полосу
  [input+h, input+h+1], где conformal-конфигурация 3.2.2
  (PredictionIntervals в fit) отказывала СЫРЫМ Exception библиотеки
  («Time series is too short» / «No windows available») вне таксономии
  ValueError/NeuralContractError адаптера.
- **F2' -- мёртвые ручки hidden_size/mlp_layers** (literal-dup класс):
  validate_nhits_params bounded-валидацией подтверждает и params-эхо
  возвращает значения, но в конструктор NHITS ручки НЕ передавались
  НИКАК -- дефолт библиотеки 3x[[512,512]] навсегда, max|diff|=0.0 по
  всему диапазону; yaml::nhits param_space содержит hidden_size --
  ось тюнинга без эффекта.
- **F3' -- кандидата-нахождка Task 139a**: адаптер nbeats допускает
  horizon=1, но библиотека 3.2.2 отвергает h=1 со стеками
  trend/seasonality СЫРЫМ Exception «Horizon `h=1` incompatible with
  `seasonality` or `trend` in stacks» при ЛЮБОЙ длине ряда.
- **Дрейф characterization cert140_oracles.py** (мандат среза 140a):
  5 оракулов красные на de70239 -- width-правка Task 141a не касалась
  audit-скриптов (O17/O18/O19: _synthetic_preds на дефектных суффиксах
  lo-2.5/hi-97.5), реестровая актуальность Task 141 (O01: 22 vs 23;
  O02: dispatch-набор без tft).

### Диагностика (контрольный замер на реальном runtime ДО правки)

scripts/task140a_fix_probe.py (НОВЫЙ, 4 секции; OMP_NUM_THREADS=1,
CISSTAT_NEURAL_MAX_STEPS=6):
- F1': прямые вызовы библиотеки (БЕЗ адаптерного гейта) на 5 конфигах
  (input,h) = (8,2), (16,4), (24,3), (28,2), (48,6): на n=input+h --
  сырой «Time series is too short», на n=input+h+1 -- сырой «No windows
  available», на n=input+h+2 -- фит OK: ФОРМУЛА n_min = input+horizon+2
  СТАБИЛЬНА (та же, что сертифицирована для NBEATS Task 139a).
- F2' (текущий код до правки): hidden_size (8,32,128) -- max|diff|
  попарно = [0.0, 0.0]; mlp_layers (1,2,4) -- [0.0, 0.0]: ручки мертвы.
- F2' (кандидат-маппинг): семантика потребления mlp_units снята по
  весам блоков (исходник NHITSBlock 3.2.2: первый Linear ->
  mlp_units[0][0], пары [in, out] -> скрытые слои КАЖДОГО блока,
  выходной из mlp_units[-1][1]; дефолт 3x[[512,512]]); pair-маппинг
  [[hidden, hidden] for _ in range(mlp_layers)] -- весь диапазон
  hidden [8,128] x layers [1,4] исполним (conformal-конфигурация) и
  попарно различим на репрезентативной сетке (8,1)/(32,2)/(128,4)/(64,3).
- F3': NBEATS interpretable h=1 -- сырой отказ (все n); interpretable
  h=2 -- OK; NBEATS generic h=1 -- OK; NHITS h=1 -- OK: гейт
  ТОЛЬКО для пары (interpretable, horizon=1); NHITS identity-стеки
  исполнимы при h=1 (перенос гейта на nhits НЕ требуется).
- Контрольный замер ПОСЛЕ правки (тот же проб): hidden_size (8,32,128)
  -- max|diff| = [2.037, 3.573]; mlp_layers (1,2,4) -- [3.161, 0.684]:
  ручки живые.

### Решение

1. **F1' -- гейт окна** (apps/api/model_impls/nhits.py): условие
   `nobs < input_size + horizon + 2` (supervised-окно ПЛЮС 2
   калибровочных окна conformal-конфигурации 3.2.2); сообщение гейта
   называет причину («+ 2 калибровочных окна conformal-конфигурации
   3.2.2») -- честный ValueError ДО фита на всей полосе
   [input+h, input+h+1]; граница n == input+h+2 исполняется честно.
   Docstring-шапка (пункт 4) переписана под формулу с ссылкой на проб.
2. **F2' -- pair-маппинг**: НОВАЯ функция _mlp_units_kwargs(hidden,
   mlp_layers) -> {"mlp_units": [[hidden, hidden] for _ in
   range(mlp_layers)]} -- та же конвенция ПАР [in, out], что
   сертифицирована для NBEATS (Task 139a); _factory разворачивает
   **mlp_units_kwargs в КОНСТРУКТОР.  Весь диапазон [8,128]x[1,4]
   исполним и реально различим.  ОТЛИЧИЕ от 139a: у NBEATS старый
   маппинг при дефолте layers=2 литерально совпадал с новым
   (сертифицированный путь бит-неизменен); у NHITS прежний путь строил
   512-ширины (ручки не передавались вовсе), поэтому честная проводка
   ручек ИЗМЕНЯЕТ численный прогноз при дефолтных параметрах
   (hidden=32/layers=2 -> [[32,32],[32,32]] вместо 3x[[512,512]]) --
   поведение значимо по декларации, эхо params/metadata больше не лжёт
   (ресертификация; e2e-смоук: nhits mae=2.3488 против 0.4788 --
   ожидаемое честное следствие, точечный контракт и fail-closed
   инварианты без изменений).
3. **F3' -- гейт пары (стек, horizon)** (apps/api/model_impls/nbeats.py):
   после validate_nbeats_params, РАНЬШЕ гейтов данных (MIN_TRAIN/окно) --
   параметр-инвариант не зависит от данными и неисправим ими:
   `if stack_config == "interpretable" and horizon < 2 -> ValueError`
   («N-BEATS: horizon=1 несовместим со стеком stack_config='interpretable'
   (стеки trend/seasonality библиотека 3.2.2 отвергает при h=1);
   используйте horizon >= 2 или stack_config='generic' (fail-closed)»).
   Generic x h=1 и NHITS x h=1 остаются исполнимыми (проб, секция 4) --
   гейт НЕ расширяется за эмпирику.
4. **Ревизия cert140_oracles.py** (мандат среза): O01 -- реестровая
   актуальность 23 модели (Task 141, прецедент O7 cert139); O02 --
   dispatch-набор нейро-четверки {lstm, nbeats, nhits, tft}; O03 --
   ось hidden_size ЖИВАЯ; O08 -- characterization сырой полосы ->
   оракул исправленного состояния (ValueError «калибров» на n=31/32);
   O10 -- characterization мёртвой ручки -> ЖИВАЯ ручка (8 vs 128
   различимы; контраст nbeats сохранён); O11 -- весь диапазон [1,4]
   исполним и попарно различим; O12 -- конструкторный spy исправленного
   состояния (первый Linear В hidden, последний ИЗ hidden, скрытые пары
   (hidden, hidden) x layers, дефолт 512 не остаётся; pools-фактура
   interpolation сохранена); _synthetic_preds -- суффиксы ШИРИНЫ
   lo-95.0/hi-95.0 (правка width-семантики Task 141a) с ловушками
   lo-2.5/hi-97.5 (прецедент O5 cert139); O23 -- width-дисклоужер
   metadata на всех трёх alpha; docstring модуля переписан.
5. **Ревизия cert139_oracles.py O4(b)**: для horizon=1+interpretable
   ожидается F3'-гейт («несовместим») вместо MIN_TRAIN; MIN_TRAIN-
   граница снизу перенесена на ИСПОЛНИМУЮ пару (generic, h=1) --
   прецедент 139a (characterization-оракулы пересматриваются при
   исправлении находок).
6. **Таксономия/поведение вне находок НЕ менялись**: point-путь,
   conformal-контур, clamp-инвариант, MIN_TRAIN-гейт, bounded-валидация,
   bool-коэрция, env-рычаг, ds-ось, width-семантика -- бит-неизменны.

### TDD (RED -> GREEN)

- RED: 7 новых кейсов -- tests/unit/test_nhits_adapter.py секция 2b
  (5: F1-boundary «калибров» + фит на границе; F2-структура
  _mlp_units_kwargs; F2-проводка spy'ем с весовой фактурой блока;
  F2-различимость hidden 8/128 и layers 1/4; страж nhits x h=1
  исполним) + tests/unit/test_nbeats_adapter.py секция 2c (2: F3-гейт
  interpretable x h=1 -> ValueError «несовместим»; страж generic x h=1
  исполним).  Результат: 5 failed / 61 passed -- падения ТОЧНО
  дефектные (сырой Exception вместо честного ValueError; AttributeError
  _mlp_units_kwargs; 512-ширины вместо ручек; max|diff|=0.0; F3-сырой
  Exception), оба стража зелёные.
- GREEN: правки nhits.py + nbeats.py -> 66/66 в двух адаптерных
  файлах.  Попутная коррекция ОЖИДАНИЙ по снятой эмпирике: крайние
  измерения весовой фактуры блока (pooled-вход, n_theta выхода) --
  геометрия ряда, от ручек НЕ зависят (исходник NHITSBlock) --
  оракулы прижаты к структуре пар, а не к «всем измерениям <= hidden».
- Оракулы: cert140_oracles.py + cert139_oracles.py -- 51/51 после
  ревизии (до: 5 failed на de70239).

### Мутационное тестирование (fresh-subprocess, SHA-контроль)

scripts/audit_scripts/cert140a_mutations.py (НОВЫЙ; протокол
cert139a_mutations.py; эталон -- байт-копия файла на старте кампании,
т.к. правки Task 140a незакоммичены; kill-подмножество: оба адаптерных
тест-файла + cert140/cert139 оракулы):
- M01 nhits гейт +2 -> +1: KILLED (верхняя кромка полосы уходит в сырой
  Exception);
- M02 nhits гейт +2 -> +0 (откат F1'): KILLED;
- M03 nhits pair-маппинг отключён (откат F2'): KILLED (512-ширины);
- M04 pair-маппинг -> мёртвая глубина range(2): KILLED;
- M05 pair-маппинг -> мёртвая ширина 64: KILLED (8/128 сливаются);
- M06 сообщение теряет калибровочную причину: KILLED (честная
  диагностика);
- M07 off-by-one `<=` (граница +2 ошибочно отклоняется): KILLED;
- M08 nbeats F3'-гейт удалён (откат): KILLED (сырой Exception);
- M09 F3'-гейт расширен на generic (за эмпирику): KILLED (страж
  generic x h=1);
- M10 F3'-сообщение теряет «несовместим»: KILLED (честная диагностика).
Итог: **10/10 KILLED**; восстановление байт-чистое (SHA-контроль);
базлайн kill-подмножества после кампании -- 117 passed.

### Верификация

- Полная регрессия: **2398 passed / 0 failed** (unit + api + snapshot 3;
  6.5 мин) -- арифметика: 2391 базлайн de70239 + 7 новых = 2398.
  neural-тесты ИСПОЛНЯЛИСЬ (neuralforecast 3.2.2 + torch 2.14.0+cpu --
  та же пара, на которой сертифицированы Tasks 137-141; окружение
  восстановлено из requirements.txt + requirements-dev.txt +
  requirements-neural.txt + prophet 1.4.0 / statsforecast 2.1.1;
  pip check -- No broken requirements).
- compileall OK; app-import OK (FastAPI); rules-smoketest exit=0;
  фронтенд не затронут (git diff -- 0 файлов .ts/.tsx).
- E2E-смоук актуального момента scripts/task141_e2e_smoke.py (env-рычаг
  60): ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (23 connected -> tft ready -> tuning grid
  8 trials -> quartet-сравнение: nbeats mae=2.1995 БИТ-В-БИТ базлайн
  Task 141 -- дефолтный путь N-BEATS не тронут (F3'-гейт вне его
  конфигурации); nhits mae=2.3488 (был 0.4788) -- ожидаемое честное
  следствие оживления ручек (см. Решение п.2); tft mae=3.3413 без
  изменений).
- Dockerfile-пробы N-BEATS и N-HiTS воспроизведены локально:
  'N-BEATS executable OK' и 'N-HiTS executable OK' (n=38, input=8, h=2:
  38 >= 8+2+2=12 -- вне полосы; hidden_size=16 теперь честно доходит до
  конструктора; ассерты проб не зависят от ширины сети).
- Контрольный замер после правки (проб, секция 2): ручки живые --
  max|diff| = 2.04/3.57 (hidden 8->32->128) и 3.16/0.68 (layers
  1->2->4).

### Кандидат-нахождки (вне мандата Task 140a; требуют отдельной постановки)

- НЕ обнаружено новых: соседние классы проверены пробом -- NHITS x h=1
  исполним (identity-стеки), generic x h=1 исполним; lstm/tft гейты
  окон (tft -- probabilistic MQLoss БЕЗ conformal-калибровки: потребность
  +2 не следует переносить без собственного проба; lstm -- свой гейт
  MIN_TRAIN) -- вне мандата.
- Поведенческое следствие F2' для эксплуатации: дефолтный nhits-прогноз
  изменился (32-ширинный MLP вместо 512-ширинного дефолта библиотеки) --
  исторические OOF-сравнения quartet'а с участием nhits НЕ сопоставимы
  через границу правки (аналог честной истории width-правки Task 141a:
  ретроспективный пересчёт не требуется -- интервалы/метрики
  производные слои своего момента).

### Границы Task 140a (что осознанно НЕ сделано)

- scripts/audit_scripts/cert140_f1f2_probe.py,
  cert140_mutations.py, task138/139/140/141_e2e_smoke.py НЕ
  модифицировались -- characterization-артефакты своего момента
  (прецедент OR11i; актуальные пробы/смоуки -- task140a_fix_probe.py /
  task141_e2e_smoke.py).
- yaml::nhits param_space НЕ менялся (hidden_size [32, 64] -- ось стала
  живой без правки декларации; mlp_layers и раньше был вне param_space
  -- прецедент nbeats Task 139a).
- Исторические записи журнала НЕ редактировались (append-only).
- Frontend/UI -- без изменений.

Изменённые/новые файлы (ZIP: download/task140a_nhits_gate_liveness_f3_fix.zip):
- НОВЫЕ: scripts/task140a_fix_probe.py,
  scripts/audit_scripts/cert140a_mutations.py
- ИЗМЕНЁННЫЕ: apps/api/model_impls/nhits.py (гейт +2 + pair-маппинг
  _mlp_units_kwargs + docstring-шапки), apps/api/model_impls/nbeats.py
  (F3'-гейт + docstring-шапки), tests/unit/test_nhits_adapter.py
  (секция 2b: 5 кейсов + torch-импорт), tests/unit/
  test_nbeats_adapter.py (секция 2c: 2 кейса),
  scripts/audit_scripts/cert140_oracles.py (ревизия O01/O02/O03/O08/
  O10/O11/O12/_synthetic_preds/O23 + docstring),
  scripts/audit_scripts/cert139_oracles.py (O4(b) под F3'-гейт),
  worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@de70239 + перечисленные изменения.

---

## Сертификация Task 141 -- TFT vertical slice (независимый аудит: оракулы на собственных данных + мутационная кампания в fresh subprocess)

Дата: 2026-09-13. Синхронизация: main@43553e0 (origin/main; локально
был f7596e1, fast-forward через 1ccdad3/de70239 Task 139a/e8755b9/
4184f06 Task 140a/43553e0).  Объект аудита: Task 141 -- TFT vertical
slice, четвёртый исполнитель Neural Runtime Contract Task 137 и ПЕРВЫЙ
срез с probabilistic-поверхностью MQLoss/quantiles (коммиты 952653e +
f7596e1; исполнитель -- коллега).  Постановка
docs/modeling_task_list.md::Tasks 138-142 («Task 141 -- TFT») +
требования Task 137 («probabilistic losses и quantiles»).  Методика --
прецедент сертификаций 136-140: оракулы аудитора на СОБСТВЕННЫХ
данных (seed=141, НЕ фикстуры исполнителя) + мутационная кампания в
fresh subprocess с SHA-контролем байт-чистоты дерева.

### Разведка и ревизия кода

- apps/api/model_impls/tft.py (~540 строк) прочитан полностью:
  probabilistic-план MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2]) с
  width-суффиксами interval_width_for_alpha (единый источник истины с
  тройкой после Task 141a); гейт окна `nobs < input_size + horizon`
  БЕЗ '+2' -- ОБОСНОВАННО: у TFT НЕТ conformal-калибровочных окон
  (levels=(), PredictionIntervals не активируется -- квантили нативны
  loss'у), собственный минимум библиотеки = input+h (проб коллеги
  «TFT requires at least 48 training timestamp(s)» при 24+24);
  граница nobs=input+h адмиссибельна -- подтверждено моим оракулом
  c02, полоса [input+h-1] честно отклоняется на 5 конфигах (c01);
  clamp-инвариант lower <= median <= upper -- живой гейт квантильного
  пересечения MQLoss; fail-closed: NaN/Inf, пустой target, MIN_TRAIN=30,
  bool-коэрция, bounded-границы, делимость d_k=hidden_size//n_head,
  alpha whitelist {0.01, 0.05, 0.10}, n_head {2, 4}; env-рычаг
  CISSTAT_NEURAL_MAX_STEPS (дефолт -- константа 300, мусор/<=0 --
  fail-closed); ds-ось переиспользована из lstm (_resolve_time_axis,
  НЕ дубликат); torch/neuralforecast НЕ импортируются на уровне модуля.
- Реестр v2 (model_execution.py): запись tft -- objective=level_forecast,
  input_kind=univariate, engine=neuralforecast, actions=_TUNABLE,
  deterministic=True, dependency_group=neural, gpu=optional; executor
  _tft_executor с честным metadata-мэппингом (adapter_id/params/nobs/
  max_steps/seed/freq/intervals/deterministic).  Dispatch
  routers/models.py -- условная регистрация, import-gate
  dispatch<->readiness на месте.  yaml::tft param_space
  n_head x hidden_size x input_size = 8 trials, requires_gpu: true
  (методологическая ось D06) НЕ тронута.  deepar -- честный
  catalog_only (в реестре исполнения отсутствует).
- Отличие от гейтов тройки проверено как ДИЗАЙН-решение, не дефект:
  '+2' сертификаций 139a/140a существует ради калибровочных окон
  conformal-поверхности 3.2.2; у TFT поверхность нативно-квантильная --
  формула тройки к TFT неприменима, ослабление до input+h честно.

### Оракулы (scripts/audit_scripts/cert141_oracles.py, 72 кейса)

Секции: A -- реестр/dispatch/yaml/константы/импорт-гигиена (a01-a06,
включая subprocess-проверку отсутствия eager-импорта torch/
neuralforecast); B -- fail-closed валидация на моих значениях
(b01-b08: bool-коэрция с пином формулировки, bounded-границы в обе
стороны, whitelist, делимость); C -- гейты данных: полоса окна на
5 конфигах + адмиссибельность границы + MIN_TRAIN + ds-ось integer/
datetime (c01-c04); D -- живая проводка до КОНСТРУКТОРА через
fake-harness без torch (d01-d03: kwargs фабрики, MQLoss-quantiles,
alias, fold_seed в конструкторе, env-рычаг, levels=() -- conformal
НЕ активируется); F -- fault-injection на синтетическом отклике
(f01-f09: медиана/квантиль отсутствуют, NaN, длина, квантильное
пересечение, равенство на границе, capacity passthrough, contract-
wrap, spy resolve_probabilistic_loss); G -- provenance (g01-g02:
план всех alpha, payload-метаданные); H -- executor-мэппинг,
quartet-когорта lstm/nbeats/nhits/tft, deepar catalog_only, легаси-
эндпоинт (h01-h05); E -- РЕАЛЬНЫЕ фиты на моих данных
(120 точек: тренд + сезонность 14 + шум, seed=141; e01-e03 + h05,
env-гейт CISSTAT_CERT141_REAL=1, маркер real_fit): честная ШИРИНА
интервала (lower < median < upper строго, отступ >= 1% масштаба с
каждой стороны -- НЕ схлопнут к медиане, урок width-семантики
НАХОДКИ Task 141 п.2), монотонность W(0.01) > W(0.05) > W(0.10),
same-seed бит-паритет (array_equal), cross-seed различимость,
легаси-эндпоинт с честным отказом на коротком ряде.

Результат на чистом дереве: **68 fast + 4 real = 72/72 GREEN**
(реальные фиты: 6 уникальных, max_steps=50, 100.8 c на 2 vCPU).

### Мутационная кампания (scripts/audit_scripts/cert141_mutations.py)

39 мутаций, kill-подмножество -- fast-часть оракулов (-m "not real_fit")
в fresh subprocess, SHA-контроль до/после, восстановление git checkout
с байт-сверкой: **39/39 KILLED**.

- Гейты: M01 weaken окна, M02 over-strict '+2', M03 MIN_TRAIN,
  M04 NaN, M05 пустой, M06 horizon, M07 делимость, M08 n_head,
  M09 bounds, M10 alpha, M11 bool-коэрция -- все KILLED (c01/c02/c03,
  b01-b08).
- Квантильная поверхность: M12 медиана выпала из плана, M13 width из
  alpha, M14 точка = первая колонка, M15 сторона lo/hi перепутана,
  M16 суффикс сдвинут, M17 clamp удалён, M18 clamp строгий, M19
  isfinite, M20 длина, M21 capacity проглочен, M22 wrap снят, M23
  контрактный гейт удалён, M24/M25 fail-closed выборки -- все KILLED
  (d01, f01-f09, g01).
- Честность metadata: M28 max_steps-литерал, M29 seed-литерал,
  M30/M31 intervals.method -- KILLED (d02, g01/g02, h03).
- Идентичность/проводка: M32 alias, M33 adapter_id, M34 model_id,
  M35 dispatch, M36 registry adapter_id, M37 deterministic=False,
  M38 yaml trials, M39 executor-мэппинг -- KILLED (a01-a04, h03).
- Эволюция одного оракула: M04 (NaN-гейт) ПЕРВОНАЧАЛЬНО SURVIVED --
  эквивалентное действие через defense-in-depth: контрактный
  to_long_format (Task 137) дублирует NaN-гейт ниже по стеку, отказ
  оставался честным, но с формулировкой КОНТРАКТА, а не адаптера.
  Оракул b06 ужесточён до пина адаптерного слоя («импутация запрещена»,
  _validated_target ДО ds-оси) -- пересборка M04: KILLED.  Вывод:
  дублирование гейта -- осознанная защита в глубину, НЕ дефект; адаптер
  обязан отказывать на своём слое, что и подтверждено.

### Кросс-проверка suites исполнителя и прод-инвариантов

- tests/unit/test_tft_adapter.py + test_tft_integration_paths.py:
  **50/50 passed** в моём окружении (фактическая коллекция 35+15;
  в журнале исполнителя указано 34+15=49 -- расхождение +1 кейса
  в сторону учёта, НЕ в сторону потерь, НЕ блокирующее).
- Count-гейты и контракты (test_lstm/test_nbeats/test_nhits_
  integration_paths, test_model_execution_contract,
  test_modeling_mvp_certification, test_model_readiness_candidates):
  **50/50 passed**.
- Прод-инварианты на полном dispatch-окружении (venv: requirements +
  apps/api/requirements + neural-группа; neuralforecast 3.2.2 +
  torch 2.14.0+cpu + prophet 1.4.0 + statsforecast 2.1.1 + arch):
  registry 23 == PRODUCTION_BACKTEST_MODEL_IDS 23, tft --
  backtest/tune/diagnostics, deepar отсутствует в реестре
  (catalog_only), import-gate dispatch<->readiness зелёный.
- Окружение аудита: Python 3.12.14, pandas 2.2.3, numpy 2.1.3 --
  версии пары neuralforecast/torch совпадают с сертификационными
  Tasks 137-141.

### Вердикт

**Task 141 СЕРТИФИЦИРОВАНА.**  72/72 оракула зелёные, 39/39 мутаций
убиты, suites исполнителя 100/100, прод-инварианты точны.  Probabilistic-
поверхность MQLoss/quantiles -- корректная с первого дня (width-
семантика честная, ПРОТИВОПОЛОЖНАЯ дефекту тройки, исправленному в
Task 141a), fail-closed дисциплина и metadata-честность выдерживают
мутационное давление.  НОВЫХ блокирующих находок НЕ обнаружено.

### Границы сертификации (что осознанно НЕ сделано)

- Полная регрессия 2379 тестов НЕ прогонялась (независимая
  сертификация -- оракулы аудитора + целевые suites исполнителя +
  count-гейты; полный прогон -- зона исполнителя, заявлено 2379/0).
- E2E смоук исполнителя scripts/task141_e2e_smoke.py НЕ воспроизводился
  (его эквивалент на моих данных -- секция E: реальные фиты,
  provenance, детерминизм; смоук использует фикстуры исполнителя).
- Тюнинг-грид 8 trials НЕ прогонялась целиком (лёгкий grid-путь
  прикрыт count-гейтами реестра и e2e-смоком исполнителя).
- Наблюдение вне мандата (косметическое, НЕ блокирующее): в worklog4.md
  счётчик кейсов test_tft_adapter.py указан как 34, фактическая
  коллекция 35 -- журнал расходится на +1 в безопасную сторону.

### Изменённые/новые файлы

Новые:
- scripts/audit_scripts/cert141_oracles.py (72 оракула, секции A-H+E)
- scripts/audit_scripts/cert141_mutations.py (39 мутаций, SHA-протокол)

Изменённые:
- worklog5.md (этот журнал, запись о сертификации)

Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
main@43553e0 + перечисленные файлы.  ZIP: download/cert141_tft_audit_worklog5.zip.

---

## Task 142 -- DeepAR vertical slice (ПЯТЫЙ исполнитель Neural Runtime Contract Task 137; PANEL-постановка min_series=5; ВТОРОЙ срез с probabilistic-поверхностью MQLoss/quantiles)

Дата: 2026-09-13. Синхронизация: main@43553e0 (Task w/n-2 minor UI edit;
цепочка нейро-срезов в main: 952653e Task 141 TFT -> f7596e1 Task 141a
width-семантика тройки -> de70239 Task 139a -> 4184f06 Task 140a).
Постановка docs/modeling_task_list.md::Tasks 138-142, срез «Task 142 --
DeepAR» + правило моделирования: «DeepAR активируется только для
настоящей панели с несколькими рядами; несколько числовых колонок
одного объекта не выдаются за панель» (yaml::deepar min_series=5,
правило F05) + требования Task 137 («probabilistic losses и
quantiles»; MQLoss зарезервирован за срезами 141-142).  Прецедент
quartet'а lstm/nbeats/nhits/tft (Tasks 138-141): runtime-контракт
Task 137 НЕ меняется -- новый адаптер + запись реестра v2 + условный
dispatch + yaml.  НОВАЯ ось среза: input_kind="panel" (единственный
такой носитель в нейро-семействе) -- первый panel-исполнитель
платформы потребовал ПАНЕЛЬНОГО движка session-контура (Task
134-прецедент отдельного движка под input_kind: main-движок не
передаёт related_series, vector-движок жёстко требует
objective=multivariate).

### Решение (по пунктам постановки)

1. **ПАНЕЛЬ -- ядро постановки, честность активации**: адаптер
   принимает target + related_series (канал реестра v2, все ряды одной
   длины -- гейт ModelExecutionRequest) и отказывает ДО фита при
   n_series = 1 + len(related) < DEEPAR_MIN_SERIES=5; сообщение честно
   называет правило («одиночный ряд и несколько числовых колонок
   одного объекта не выдаются за панель»).  Гейт продублирован ТРЕМЯ
   слоями: контекст роутера (honest_system_profile -> n_series-гейт),
   нейро-cohort-контракт Task 137 (neural_cohort_contract:
   n_series < min_series -- отказ; panel=true в cohort_id) и
   panel-движок (len(system.names) < 2 -- отказ).  Панель собирается
   из РЯДОВ датасета (target + связанные числовые ряды, тот же
   honest-профиль, что endogenous-система Task 131); feature-каналы
   реестром/движком не потребляются (FeaturePlan -> честный warning).
2. **ГЛОБАЛЬНАЯ модель -- суть DeepAR**: ОДИН фит на ВСЕЙ панели в
   long-format unique_id/ds/y через сертифицированный to_long_format
   контракта (явный series_column; NaN/Inf, дубликаты (unique_id, ds),
   нерегулярная сетка, несогласованные длины -- отказ).  Точечный
   прогноз payload -- медиана MQLoss ЦЕЛЕВОГО ряда (unique_id
   "series_0", извлечение по unique_id, сортировка по ds --
   детерминированный порядок горизонта); missing-строки целевого ряда
   в отклике -- fail-closed (глобальная модель обязана вернуть прогноз
   каждой серии панели).
3. **Probabilistic-поверхность -- конвенция Task 141**: квантили
   декларируются ПРЯМО -- MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2])
   -- честный двусторонний интервал [alpha/2; 1-alpha/2] процентилей;
   план _quantile_plan ПЕРЕИСПОЛЬЗОВАН из tft.py (единый источник
   истины, прижат identity-тестом); метод интервалов в metadata --
   NeuralIntervalPlan.method="neural_quantile_outputs"; clamp-инвариант
   lower <= median <= upper -- живой гейт + fault-injection тест.
4. **ЭМПИРИКА пробы** (scripts/task142_deepar_probe.py, 10 секций,
   PROBE OK):
   (а) конструктор 3.2.2 с loss=MQLoss требует valid_loss=MQLoss С
   ТЕМИ ЖЕ quantiles -- иначе честный отказ («Please set valid_loss to
   MQLoss() or HuberMQLoss()...»), а NeuralForecast.core дополнительно
   валидирует идентичность quantiles loss/valid_loss -- адаптер
   передаёт ОБЕ головки одним кортежем (прижато spy-тестом, float32-
   допуск); (б) дефолтный loss -- DistributionLoss(StudentT)
   (каталожное «parametric distribution head» подтверждено); выбор
   MQLoss -- платформенная конвенция probabilistic-поверхности Task
   141 (детерминированные нативные квантильные выходы вместо
   сэмплирования trajectory_samples=100 путей), дисклоужен в
   metadata.intervals.loss="mqloss"; (в) колонки отклика
   "DeepAR-median"/"DeepAR-lo-<w>"/"DeepAR-hi-<w>" -- width-семантика
   НАХОДКИ Task 141 п.2 (w = 100*(1-alpha)); (г) панель из 5 серий --
   20 строк отклика (n_series x horizon), unique_ids сохранены;
   (д) same-seed бит-паритет max|diff| = 0.0, cross-seed 0.0299;
   (е) граница окна n == input_size + horizon исполнима (гейт БЕЗ +2,
   как TFT -- MQLoss без conformal-калибровки); конструктор хранит
   input_size+1 (внутренний сдвиг авторегрессии -- прижат spy-тестом);
   (ж) int-ds freq=1 OK (конвенция семейства).
5. **Panel-движок session-контура** (backtesting.py::
   run_panel_backtest_plan -- НОВЫЙ, четвёртый движок платформы после
   main/vector/volatility): гейты objective="level_forecast" +
   input_kind="panel" по execution_contract; fold-local leakage-safe
   префиксы системы (непрерывный префикс, тест не пересекает train --
   как vector-движок); related-ряды -- сырые префиксы (семантика VAR);
   target -- fold-local preprocessing (fold_preprocessor) с
   restore_forecast; метрики -- сертифицированная compute_forecast_
   metrics main-движка на target (MASE/RMSSE scale train-only target),
   агрегат -- сертифицированный _aggregate_metrics; OOF-точки -- формат
   main-движка (diagnostics/comparison совместимы); result несёт НОВЫЙ
   блок "panel" (series_names/n_series/target_series; schemа
   BacktestResponse дополнена опциональным полем panel).
6. **Panel tuning** (modeling_tuning.py::execute_panel_tuning_trial +
   execute_panel_tuning_plan_with_artifacts): полная семантика
   run_panel_backtest_plan на каждый trial; сетка/усечение/финализация
   -- те же prepare_tuning_grid/finalize_tuning_plan_with_artifacts
   (единый контракт MAX_TRIALS=64, детерминированный sample, best =
   argmin).
7. **Panel-cohort изоляция**: план строится с
   cohort_contract_override=neural_cohort_contract (objective=
   "level_forecast" совпадает; panel=true/n_series/min_series/
   loss=interval/training/device в контракте) + series_fingerprints
   ВСЕЙ панели -- cohort_id ОТЛИЧЕН от univariate-планов на тех же
   folds; comparison честно не смешивает ("Cohort contracts моделей не
   совпадают") -- DeepAR образует собственный comparison-cohort.
8. **Реестр v2 + dispatch + движок-роутинг**: запись №24 -- model_id=
   "deepar", family_id="neural", adapter_id="neuralforecast-deepar",
   objective="level_forecast", input_kind="panel",
   requires_related_series=True, actions=_TUNABLE,
   engine="neuralforecast", required_packages=("neuralforecast",),
   deterministic=True, dependency_group="neural",
   memory_class="standard", gpu="optional".  Dispatch:
   _register_neural_dispatch расширен (lstm + nbeats + nhits + tft +
   deepar; условная регистрация сохранена); legacy synthetic-запись --
   run_deepar_backtest с ЧЕСТНЫМ отказом (прецедент var/vecm; ValueError
   маппится в 422 в run_backtest -- honest refusal вместо слепого 500);
   session-роутер: panel_run-гейт (input_kind == "panel" и
   runtime_available) в backtest И tuning эндпоинтах + helper
   _panel_neural_context.  Production-образ: Dockerfile-проба
   'DeepAR executable OK' (реальный panel-фит 5 серий, n_series=5,
   intervals method; воспроизведена локально на константе 300).
9. **Bounded params**: lstm_hidden_size [8, 128] (дефолт 32 -- семейная
   конвенция; ширина доходит до hist_encoder.hidden_size конструктора),
   input_size [8, 104], alpha whitelist {0.01, 0.05, 0.10}.  Bool-коэрция
   целочисленных ручек отклоняется ЯВНО (урок НАХОДКИ-2/M6), тест
   параметризован по ВСЕМ int-ручкам.  yaml param_space:
   lstm_hidden_size x input_size = 4 trials (<= 64); alpha вне тюнинга.
10. **Бюджет**: константа DEEPAR_MAX_STEPS=300 (семейная конвенция;
    анти-тампер [100, NEURAL_MAX_STEPS_BOUND]; тюнинг бюджета -- вне
    param_space) + env-рычаг CISSTAT_NEURAL_MAX_STEPS (дефолт не задана
    -- сертифицированная константа; мусор -- fail-closed).  DEEPAR_
    MIN_TRAIN=30 (семейный пол; каталоговский мягкий порог 200 --
    раньше, readiness-гейтом F04; эмпирика: F05 срабатывает раньше F04
    на коротком профиле n_series=1).  Проводка бюджета до конструктора
    прижата двухслойным spy-тестом -- модель несёт max_steps/random_seed
    и MQLoss как loss И valid_loss.
11. **EDA-матрица -- честный shape-критерий**: до среза deepar был
    безусловно fail/blocking («одна выбранная цель» -- честный
    catalog_only); теперь критерий считает числовые ряды-кандидаты
    (n_series >= 5 -> pass, иначе fail/blocking с сообщением «нельзя
    считать панелью») -- та же честная ось, что у общего критерия, с
    panel-спецификой в тексте.
12. **Каталог нейро-семейства полон**: все 24 модели каталога имеют
    production-адаптеры; catalog_only-моделей в платформе больше НЕТ
    (готовность к Task 143 -- полная production-матрица 24x11).

### TDD (RED -> GREEN)

- RED: tests/unit/test_deepar_adapter.py (38 кейса) + tests/unit/
  test_deepar_integration_paths.py (15 кейсов) -- collection errors на
  отсутствии модуля/экспортов; поверхность ожиданий снята пробом ДО
  написания тестов (прецедент Task 139/140/141).  Правки ОЖИДАНИЙ по
  снятой эмпирике: (а) valid_loss=MQLoss обязателен с теми же
  quantiles (отказ конструктора/core-валидации); (б) quantiles
  хранятся float32 (сравнение с допуском); (в) ширина рекуррентного
  энкодера -- hist_encoder.hidden_size/encoder_hidden_size (атрибута
  lstm_hidden_size у модели нет); (г) regex «отсутствуют» вместо
  «колонка».
- GREEN: адаптер + реестр + dispatch + panel-движок + роутер + yaml.
  Нейро-набор: 38 (deepar adapter) + 15 (deepar integration) + 34+15
  (tft) + 26+14 (nbeats/nhits) + 34+17 (lstm) + runtime/contract/
  capacity кейсы.  Окружение: requirements.txt + requirements-dev.txt +
  requirements-neural.txt (torch 2.14.0+cpu, neuralforecast 3.2.2 --
  та же пара, на которой сертифицированы Tasks 137-141) + prophet
  1.4.0 / statsforecast 2.1.1 -- полный production dispatch; pip check
  -- No broken requirements.
- Count-гейты 23->24 честно в 15 файлах: test_lstm/test_nbeats/
  test_nhits/test_tft integration_paths (dispatch-конвенция
  {lstm,nbeats,nhits,tft,deepar}, count 24/19), test_garch/test_egarch
  integration_paths (subprocess-arith 24/19), test_var_integration_
  paths (subprocess 'ok 24'), test_modeling_mvp_certification
  (_EXPECTED_NEURAL={lstm,nbeats,nhits,tft,deepar}, PREDICTORS),
  test_model_execution_contract (CERTIFIED_IDS+NEURAL_IDS+PANEL_IDS;
  deepar descriptor; catalog-only примеров больше нет),
  test_model_readiness_candidates (deepar production+blocked F05 на
  n_series=1; runnable 19 / catalog-only 0 / blocked 5; короткий
  профиль: blocked 14, deepar F05-объяснение «Модель DeepAR требует
  минимум 5 рядов»), test_backtesting_engine (sweep исключает deepar),
  test_eda_model_matrix (deepar shape-критерий), tests/api:
  test_models_backtest_real (expected+deepar), test_models_candidates
  (deepar legacy 422 «панель»), test_modeling_workflow (deepar blocked
  матрицей применимости).

### Верификация

- TDD цикл выше; 54 новых кейса deepar (38 + 15 + 1 матрица).
- Полная регрессия: **2452 passed / 0 failed** (unit + api + snapshot
  3; ~7 мин; арифметика: 2398 базлайн + 54 новых) -- neural-тесты
  ИСПОЛНЯЛИСЬ (neuralforecast 3.2.2 + torch 2.14.0+cpu).  compileall
  OK; app-import OK (FastAPI); pip check (No broken requirements);
  rules-smoketest exit=0; фронтенд не затронут (git diff -- 0 файлов
  .ts/.tsx -- прецедент Task 139a/140a: typecheck/build обеих оболочек
  не запускались).
- E2E-смоук scripts/task142_e2e_smoke.py (env-рычаг 60): ВСЕ ПРОВЕРКИ
  ПРОЙДЕНЫ (24 connected -> dispatch-gate -> deepar production+blocked
  F05 на n_series=1, catalog-only 0 -> panel-движок: реальный
  глобальный OOF cohort 2 folds (mae=116.1194 на слабом бюджете --
  структурные ассерты стабильны) -> panel tuning 4/4 trials
  (best lstm_hidden_size=64, input_size=24) -> cohort-изоляция ->
  панельный гейт 4 рядов -- честный отказ).
- Проб scripts/task142_deepar_probe.py: PROBE OK (10 секций: поверхность
  конструктора; контрактный гейт MQLoss; односерийный sanity; ПАНЕЛЬ
  5 серий -> 20 строк; дефолт DistributionLoss(StudentT) --
  informational; int-ds freq=1; same-seed 0.0 / cross-seed 0.0299;
  проводка бюджета; неосуществимое окно -- честный отказ; граница
  n == input+h исполнима; недообученное пересечение 0/4 точек на
  seed=2).  Dockerfile-проба DeepAR воспроизведена локально:
  'DeepAR executable OK' (реальный panel-фит на константе 300).
- Прод-инварианты: PRODUCTION_BACKTEST_MODEL_IDS == 24; deepar
  backtest/tune/diagnostics (panel-движок); registry size 24; dispatch
  <-> readiness gate точен; legacy deepar -- честный 422.

### Границы Task 142 (что осознанно НЕ сделано)

- Exogenous-канал DeepAR (cat/hist/futr/stat lists в поверхности
  конструктора 3.2.2): реестр НЕ декларирует exog (supports_future_
  features=False); feature-каналы нейро-моделей -- отдельная
  постановка (прецедент lstm/tft; каталожное supports_exogenous=true
  не декларировано в реестре до своего среза).
- hist_exog/stat_exog, early stopping (val_size/patience),
  lstm_n_layers/lstm_dropout/decoder-ручки, scaler_type -- поверхность
  контракта для отдельных постановок; срез несёт bounded-ручки
  lstm_hidden_size/input_size/alpha.
- Тюнинг бюджета (DEEPAR_MAX_STEPS) -- вне param_space (прецедент
  Task 136); env-рычаг слабых инстансов сохранён.
- yaml requires_gpu: true для deepar НЕ менялось (методологическая ось
  D06 NOT_RECOMMENDED на CPU -- независимая от production-готовности
  platform_status; Tasks 138-141 так же не меняли нейро-четвёрку).
- GPU-исполнение: runtime Task 137 фиксирует device="cpu";
  gpu="optional" -- декларация capability, не переключатель.
- UI/фронтенд не тронут (0 файлов .ts/.tsx): production-статус deepar
  подаётся существующими capability-каналами (available_model_actions,
  execution_contract, blocking_reason).
- scripts/task138/139/140/141_e2e_smoke.py НЕ модифицировались
  (снимки своего момента -- прецедент; актуальный смоук -- task142).

Изменённые/новые файлы (ZIP: download/task142_deepar_vertical_slice.zip):
- НОВЫЕ: apps/api/model_impls/deepar.py,
  tests/unit/test_deepar_adapter.py,
  tests/unit/test_deepar_integration_paths.py,
  scripts/task142_deepar_probe.py, scripts/task142_e2e_smoke.py
- ИЗМЕНЁННЫЕ: apps/api/model_execution.py, apps/api/model_impls/__init__.py,
  apps/api/routers/models.py, apps/api/backtesting.py,
  apps/api/modeling_tuning.py, apps/api/routers/modeling_session.py,
  apps/api/schemas.py, rules/modeling.yaml, apps/api/eda_model_matrix.py,
  apps/api/Dockerfile, apps/api/requirements-neural.txt,
  tests/unit/{test_lstm_integration_paths, test_nbeats_integration_paths,
  test_nhits_integration_paths, test_tft_integration_paths,
  test_garch_integration_paths, test_egarch_integration_paths,
  test_var_integration_paths, test_modeling_mvp_certification,
  test_model_execution_contract, test_model_readiness_candidates,
  test_backtesting_engine, test_eda_model_matrix}.py,
  tests/api/{test_models_backtest_real, test_models_candidates,
  test_modeling_workflow}.py, worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@43553e0 + перечисленные изменения.

---

## Task 143 -- Финализация полной production-матрицы 24x11 (performance/timeout/memory benchmark, PRE-0 smoke Vercel-Render, документация)

Дата: 2026-09-13. Синхронизация: main@68a0cb7 (Task 142 -- DeepAR
vertical slice, закоммичен тимлидом; цепочка нейро-срезов в main
завершена: lstm -> nbeats -> nhits -> tft -> deepar).  Постановка
docs/modeling_task_list.md::Task 143 («Полная production-матрица
24x11») + указание тимлида (финализация матрицы, performance/timeout
benchmark, PRE-0 smoke Vercel-Render, обновление документации).
Прецедент финализационных задач: Task 121 (девятимодельный baseline);
теперь -- 24/24, catalog_only моделей в платформе НЕТ (Task 142 п.12).

### Решение (по пунктам постановки)

1. **«24 модели имеют реальные адаптеры и честные capabilities» --
   верифицировано, не декларировано**: реестр v2 = 24 записи
   (MODEL_EXECUTION_REGISTRY), PRODUCTION_BACKTEST_MODEL_IDS = 24,
   consistency-gate dispatch<->readiness точен; полная capability-матрица
   24x11 закрыта программно (model_stage_capabilities по каждой модели,
   tuple == MODELING_STAGE_IDS, статусы из белого списка).  Счётчики
   readiness на macro-профиле: runnable 19 / catalog-only 0 / blocked 5
   (профильные правила F01/F05/domain -- НЕ отсутствие реализаций).
2. **«Все применимые модели проходят полный execution scope» --
   НОВЫЙ scripts/task143_matrix_benchmark.py**: каждая из 24 моделей
   исполняет РЕАЛЬНЫЙ backtest через СВОЙ движок (main -- 19
   univariate; vector -- var/vecm на системе из 3 рядов; volatility --
   garch/egarch на VolatilityTarget; panel -- deepar на панели из 5
   рядов) и, для tunable, bounded tuning через СВОЙ контур
   (execute_{tuning,vector,volatility,panel}_tuning_plan_with_artifacts:
   13 classical @2 trials + 5 neural @1 trial -- песочница убивает
   долгие фоновые процессы, порционные прогоны с merge-логикой отчёта).
   Итог: 24/24 backtest + 18/18 tuning; честность -- 20/20 уникальных
   MAE (не заглушка), QLIKE primary у volatility, panel-фактура у
   deepar, scaled_loss+vector_baseline у vector.
3. **Performance/timeout/memory**: wall-time каждой модели против
   resource_policy_for (memory_class standard -> step_timeout 120 c);
   снапшоты пикового RSS процесса по секциям (206 -> 1237 MB -- пик
   доминирован импортом torch+neuralforecast ~600 MB, см.
   probe138b_memory.py; production-семантика -- per-job изоляция).
   ⚠️ НАХОДКА (не блокирует, требует решения тимлида): tft -- 182 c
   wall 2-fold backtest > 120 c step_timeout standard-класса на
   benchmark-хосте (4 ГБ RAM, shared CPU); в job-раннере step = ОДИН
   tuning-trial (tft-trial @2 folds ~450 c @2 trials).  Отчёт в
   download/task143_benchmark/report.{json,md} -- секция «Находки»;
   правка бюджетов/политик -- отдельная постановка.
4. **«Проверены migration старых Redis-сессий и invalidation
   lineage» -- TDD RED->GREEN (11 новых кейсов)**: (а) якорь версии
   схемы SESSION_SCHEMA_VERSION=1 -- штамп в session_to_dict, legacy
   документы (поле отсутствует) читаются как схема 0, документ из
   БОЛЕЕ нового приложения не роняет чтение (rolling back-deploy,
   warning); (б) graceful degradation коррапта: битый JSON/бинарный
   мусор -> get()=None+warning, get_or_create выдаёт пустую сессию;
   НОВОЕ -- save() поверх нечитаемого документа РАЗРЕШЁН (мусор не
   несёт ревизии и не может быть «свежее»; раньше SessionConflictError
   блокировал сессию навсегда: get()=None, save()=конфликт, выхода
   нет); (в) model_jobs переживают Redis roundtrip (resume после
   рестарта); (г) pre-Task-142 совместимость: BacktestResponse без
   panel валиден (Optional, None-дефолт), panel переживает
   model_dump-roundtrip.  Существующий migration-набор v4/5/6->7
   зелёный (test_modeling_workflow).
5. **PRE-0 smoke Vercel-Render**: ремонт pre_0_smoke.py -- CLI
   (--api-base/--frontend-origin/--demo-csv/--output-dir) + env-рычаги
   (CISSTAT_API_URL/CISSTAT_FRONTEND_ORIGIN) реализуют контракт
   README (раньше были зашиты константами); stale-путь демо-CSV
   (несуществующий /home/z/my-project/repo/...) заменён
   repo-относительным в pre_0_smoke.py и pre_1_frontend_smoke.py.
   Прогон против ПРОДАКШЕНА: PRE-0 -- 7/7 PASS (Render direct:
   health 239ms, CORS preflight, SameSite=None cookie, round-trip,
   upload, has_active_dataset, candidates 401/422 без ключа); PRE-1 --
   9/9 PASS (Vercel rewrite -> Render: полный пользовательский контур
   до зелёного badge «Реальные данные»).  Отчёты в
   download/pre_0_smoke/ и download/pre_1_frontend_smoke/.
6. **Обновление modeling.yaml и документации**: metadata.version
   1.1.0-draft -> 1.2.0 + last_updated 2026-09-13 (пины честно через
   RED->GREEN в двух тестах); rules-smoketest exit=0.  НОВЫЙ
   docs/MIGRATION_ARCHITECTURE.md -- чинит stale-ссылку
   session_store.py::§1.1 и README smoke: архитектура монорепо,
   шесть этапов (§1.1), схема Redis-документа + правила
   session_schema_version (§2), версионирование/миграции артефактов
   v4..7 (§3), контур lineage-инвалидации каскадом (§4).  README
   smoke синхронизирован с фактическим CLI/дефолтами.
7. **Верификация сборки**: полная backend-регрессия -- **2463 passed /
   0 failed** (~6:45; 2452 базлайн Task 142 + 11 новых); neural-тесты
   ИСПОЛНЯЛИСЬ (окружение восстановлено: torch 2.14.0+cpu +
   neuralforecast 3.2.2 -- та же сертифицированная пара; pip check
   clean).  typecheck:all -- 0 ошибок (обе оболочки); production
   build standalone -- Compiled successfully (13/13 pages); production
   build embedded -- Compiled successfully (13/13 pages); compileall
   OK; e2e-смоук task142 (актуальный) -- ВСЕ 7 секций OK (24
   connected -> panel-движок -> panel tuning 4/4 -> cohort-изоляция ->
   честный отказ 4<5).

### Границы Task 143 (что осознанно НЕ сделано)

- Правка step_timeout/бюджета TFT по находке п.3 -- отдельная
  постановка (правка ресурсной политики -- зона тимлида).
- Tuning neural-группы @1 trial (не 2): предел времени песочницы;
  контракт тюнинга (prepare_grid -> trial -> finalize -> best)
  исполняется полностью, сертифицированные 4-trial сетки -- в срезах
  138-142 и регрессии.
- Benchmark-профили (120/100/180/72 точек) -- канонические малые;
  нагрузочное тестирование под продовым трафиком -- отдельный класс.
- Фронтенд не тронут (0 файлов .ts/.tsx в diff, кроме проверок
  сборки): production-матрица подаётся существующими
  capability-каналами.
- scripts/task135..142_e2e_smoke.py НЕ модифицировались (снимки
  своего момента; актуальные -- task142 e2e и task143 benchmark).

Изменённые/новые файлы (ZIP: download/task143_finalization.zip):
- НОВЫЕ: docs/MIGRATION_ARCHITECTURE.md,
  scripts/task143_matrix_benchmark.py
- ИЗМЕНЁННЫЕ: apps/api/session_store.py, rules/modeling.yaml,
  scripts/smoke/pre_0_smoke.py, scripts/smoke/pre_1_frontend_smoke.py,
  scripts/smoke/README.md, tests/api/test_session_store.py,
  tests/test_modeling_spec.py, tests/api/test_param_space.py,
  worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@68a0cb7 + перечисленные изменения.

## Task IA-1 -- Хаб «Задачи» /tasks: карточная сетка + гейтинг по контракту входа (спека docs/spec_tasks_ia.md)

Дата: 2026-09-13.  Синхронизация: main@4ceb081 (RouteCard text-base,
Task w/n-2 запушен тимлидом).  Постановка тимлида: (1) оформить решение
по развитию главного меню и росту задач в spec_tasks_ia.md; (2) начать
реализацию хаба /tasks (карточная сетка + три состояния) по полному
циклу AGENTS.md.

### Решение IA (спека docs/spec_tasks_ia.md, НОВЫЙ файл)

- Центральный ответ тимлиду: решение задач НЕ предопределено наличием
  прогноза глобально. Каждая задача декларирует контракт входа:
  «Причины»/«Сценарии» -- от model_card (XAI/IRF/FEVD считаются
  обученной моделью на истории; ARCHITECTURE.md:155,1382),
  «Принятие решений»/«Мониторинг прогноза» -- от forecast_run.
  Подтверждение в существующей архитектуре: ARCHITECTURE.md:375 --
  «Задачи» потребляют ВСЕ стадии.
- Формула: пайплайн -- конечная горизонталь (заморожена, зеркало
  STAGES), задачи -- открытая вертикаль (растут в хабе /tasks),
  зависимость -- по контракту входа каждой задачи, не «после прогноза».
- Эшелоны роста: <=8 задач -- плоская сетка; 9-15 -- категории;
  15+ -- вкладки/сайдбар внутри /tasks; промоция в верхнюю строку --
  только как новый этап STAGES (версионно, критерии в спеке §6).
- Аккордеон «Задачи» из ранней постановки ЗАКРЫТ: хаб-страница
  масштабируется, аккордеон умирает при 7-9 пунктах.

### Реализация v1

- packages/ui/lib/task-stops.ts (НОВЫЙ): реестр TASK_ROUTES (4 задачи:
  scenarios/causes/decisions/monitoring, иконки lucide, requires),
  слой артефактов (validated/model_card/forecast_run <- этапы
  validation/modeling/forecasting в статусе done, ARTIFACT_STAGE),
  чистая логика гейтинга: deriveTaskGateState (available: requires
  подмножество artifacts; awaiting: не выполнено + пайплайн начат;
  blocked: не выполнено + сессия свежая), taskGateReason (человекочитаемая
  причина с названием этапа-владельца недостающего артефакта),
  artifactsFromStages, pipelineStartedFromStages.
- packages/ui/components/TaskCard.tsx (НОВЫЙ): карточка с визуальной
  DNA RouteCard (rounded-xl, border-brand/60, иконка h-11 w-11,
  заголовок text-base, описание text-sm) в трёх состояниях:
  available -- Link; awaiting -- div role=group + amber-плашка с
  Lock-иконкой и причиной; blocked -- div role=group + нейтральная
  плашка. Некликабельные состояния сознательно НЕ ссылки (ложный
  аффорданс), aria-label содержит название и причину.
- packages/ui/components/TasksHub.tsx (НОВЫЙ, "use client"): шапка
  (H1 «Задачи» + поддерживающая строка, стиль HomeHero/NavigatorHero)
  + сетка grid-cols-1 sm:2 lg:3 gap-5 px-6 role=list aria-label
  «Задачи на основе прогноза» (геометрия Block B HomeCapabilities).
  Сессия -- useAppShell().stages (гидратация GET /v1/session/current):
  хаб ЖИВОЙ, состояния пересчитываются по мере прохождения пайплайна,
  без нового бэкенда.
- packages/ui/index.ts: экспорт TasksHub, TaskCard, task-stops
  (значения + типы).
- apps/standalone/app/tasks/page.tsx: ModulePlaceholder -> TasksHub.
- НОВЫЕ плейсхолдер-маршруты задач (ModulePlaceholder, скелет под
  вертикальные срезы): tasks/{scenarios,causes,decisions,monitoring}/
  page.tsx -- доступность маршрутов уже сейчас, когда контракты задач
  начнут выполняться.

### TDD (RED -> GREEN)

- RED: 3 новых сюиты -- packages/ui/lib/task-stops.test.ts (реестр:
  порядок/уникальность href/валидность requires/кодификация
  зависимостей спеки §2; слой артефактов; таблица истинности трёх
  состояний; тексты причин с этапом-владельцем),
  packages/ui/components/TasksHub.test.tsx (шапка+список 4 карточек;
  свежая сессия: 0 ссылок + 4 blocked-причины + 4 role=group
  «недоступна»; после Моделирования: 2 ссылки + 2 awaiting
  «…после этапа Прогнозирование»; частичный пайплайн: awaiting, не
  blocked; полный пайплайн: 4 ссылки на свои маршруты; визуальная DNA
  RouteCard), apps/standalone/app/tasks/page.test.tsx (страница
  рендерит хаб, не ModulePlaceholder). Прогон до реализации: 3 сюиты
  fail на отсутствии модулей -- RED подтверждён.
- GREEN: 24/24 после реализации. Один фикс теста: LucideIcon --
  ForwardRef-объект, а не function (assert icon truthy).
- Полная регрессия: npx jest -- 97 сюит / 914 тестов PASSED
  (+3 сюиты / +24 теста к предыдущему срезу 94/890).
- Сборка: npm run build (standalone) -- успешно; маршруты
  /tasks/{scenarios,causes,decisions,monitoring} появились в
  production-манифесте, все статичные, First Load JS без деградации
  (553 B против 537 B на остальных -- иконки lucide).

### Границы Task IA-1 (что осознанно НЕ сделано)

- Содержимое задач (What-if/iDSS/XAI/мониторинг) -- отдельные
  вертикальные срезы; v1 поставляет каркас: хаб + 4 плейсхолдера.
- Состояние configurable (расщеплённый гейт: настройка правил/порогов
  без прогноза) -- расширение контракта v2 (спека §7).
- recommendedWith (подсказки «рекомендован прогноз» для Сценариев) --
  v2, забота самой задачи.
- ModuleNav, STAGES, бэкенд, embedded -- НЕ затронуты (запрет спеки §3:
  верхняя строка заморожена).
- Исторические записи журнала НЕ редактировались (append-only).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

Изменённые/новые файлы (ZIP: download/task_ia1_tasks_hub.zip):
- НОВЫЕ: docs/spec_tasks_ia.md, packages/ui/lib/task-stops.ts,
  packages/ui/lib/task-stops.test.ts, packages/ui/components/TaskCard.tsx,
  packages/ui/components/TasksHub.tsx,
  packages/ui/components/TasksHub.test.tsx,
  apps/standalone/app/tasks/page.test.tsx,
  apps/standalone/app/tasks/scenarios/page.tsx,
  apps/standalone/app/tasks/causes/page.tsx,
  apps/standalone/app/tasks/decisions/page.tsx,
  apps/standalone/app/tasks/monitoring/page.tsx
- ИЗМЕНЁННЫЕ: packages/ui/index.ts, apps/standalone/app/tasks/page.tsx,
  worklog5.md (этот журнал)

## Task 142a (применение) -- Оценка состоятельности находок Дарио по коду main@4e5df1b (после Task 143) и применение фикса F1/F3 по полному циклу AGENTS.md

Дата: 2026-09-13.  Синхронизация: main@4e5df1b (Task 143 -- финализация
полной production-матрицы 24x11; deepar-файлы среза НЕ тронуты --
проверено sha256-сравнением всех девяти файлов среза между 68a0cb7 и
4e5df1b: байт-идентичны, правки Task 142a легли без конфликтов).
Постановка тимлида: «Коллега Дарио параллельно работе коллеги Сэм по
Task 143 нашёл находки по Task 142 и оформил в Task 142a пока без пуша.
Задача -- по текущему коду (после реализации Task 143 Сэма) оценить
состоятельность находок Дарио и, при необходимости, внести изменения».
Объект оценки: записи «Сертификация Task 142» и «Пересертификация
Task 142» (выше; вердикт первого аудита -- НЕ СЕРТИФИЦИРОВАНА,
блокирующая F3; исправление аудитора -- DistributionLoss(StudentT) +
robust + trajectory_samples, смоук-число mae 116.12 -> 1.57).

### Оценка состоятельности находок на текущем коде (4e5df1b)

Все три находки первого аудита ПОДТВЕРЖДЕНЫ независимо -- Task 143
обнаруженные дефекты не закрывал (и не мог: они вне его мандата):

- **F1 -- подтверждена (код-инспекция + живой проб)**:
  `_panel_neural_context` использует DEEPAR_MIN_SERIES (строки
  708/711/744) при единственном локальном импорте-блоке хелпера
  (строки 695-700 -- ТОЛЬКО neural_contract) и полном отсутствии имени
  на уровне модуля -- NameError при первом обращении.  Живой проб
  scripts/audit_scripts/task142a_f1_nameerror_probe.py (НОВЫЙ,
  минимальный session-дубль с панелью из 5 рядов):
  `NameError: name 'DEEPAR_MIN_SERIES' is not defined`
  (modeling_session.py:708) воспроизведён на чистом 4e5df1b.  Пробел
  покрытия подтверждён дислокацией вызовов: e2e-смоук task142 и
  benchmark task143 исполняют run_panel_backtest_plan НАПРЯМУЮ,
  session-хелпер не исполняется ни одним тестом.
- **F2 -- подтверждена (код-инспекция)**: docstring deepar.py п.1
  обещает «запрос с train_features -- честный отказ гейта реестра»;
  фактически гейт model_execution.py:391 отвергает train_features
  ТОЛЬКО при input_kind=="univariate" (наследие до-142 гейта) --
  для panel проходят без потребления, honest-warning даёт
  panel-движок.  Исправлена Дарио в 142a переписыванием docstring под
  фактическую семантику (поведение не менялось -- документ-уровень).
- **F3 -- подтверждена ТРЕМЯ независимыми свидетельствами**:
  (а) код-инспекция статус-кво: фабрика loss=valid_loss=MQLoss, без
  scaler_type (дефолт DeepAR "identity"), без trajectory_samples --
  ровно вырожденная конфигурация из диагноза Дарио;
  (б) СОБСТВЕННЫЙ проб валидатора на СЫРОЙ библиотеке и СВОИХ данных
  (seed=20261, НЕ панель Дарио 142 и НЕ данные Сэма;
  scripts/audit_scripts/task142a_f3_validation_probe.py, бюджет 40):
  V1 MQLoss+identity -- ширина 0 бит-в-бит + коллапс масштаба точки;
  К MQLoss+robust -- ширина ВСЁ ЕЩЁ 0 (механизм M1 независим от
  скейлера); V2 DistributionLoss+robust -- ширина 22.2 + масштаб OK:
  PROBE OK, оба механизма M1/M2 и кандидат фикса подтверждены;
  (в) независимое свидетельство в СОБСТВЕННОМ артефакте Task 143:
  reports/report.json -- deepar OOF mae=109.6 против 0.83-0.87
  (lstm/nbeats/nhits на тех же данных) -- тот же класс деградации,
  что и mae=116.1194 смоука исполнителя («слабый бюджет» -- неверная
  интерпретация, подтверждено диагнозом Дарио).

### Применение (по полному циклу AGENTS.md)

- Фикс перенесён из некоммиченного дерева Дарио (ZIP
  cert142a_recert_worklog5.zip, база 68a0cb7) в актуальное дерево
  4e5df1b ФАЙЛ-В-ФАЙЛ после sha256-сверки баз (см. выше) и
  построчного ревью всех диффов: apps/api/model_impls/deepar.py
  (ядро: DEEPAR_LOSS_KEY="distribution", DEEPAR_TRAJECTORY_SAMPLES=
  1000, фабрика DistributionLoss(StudentT, квантили плана)+MAE+
  robust+trajectory_samples, metadata-дисклоужер, docstring 3/4 --
  почему НЕ MQLoss и почему robust), apps/api/neural_contract.py
  (аддитивно "distribution" в NEURAL_ALLOWED_LOSSES и
  NEURAL_PROBABILISTIC_LOSSES), apps/api/routers/modeling_session.py
  (фикс F1 -- локальный импорт DEEPAR_LOSS_KEY, DEEPAR_MIN_SERIES;
  cohort loss=DEEPAR_LOSS_KEY), apps/api/model_execution.py
  (docstring executor'а и записи №24, уточнение F2),
  apps/api/model_impls/__init__.py (комментарий среза).
- Аудиторский контур Дарио перенесён в репозиторий (в нём
  отсутствовали -- некоммичены): scripts/audit_scripts/
  cert142_oracles.py (84 оракула), cert142_mutations.py (60 мутаций,
  снапшот-протокол для некоммиченного дерева), task142_fix_surface_
  probe.py, task142_fix_surface_probe12.py (матрица E1-E4).
- Тесты исполнителя перепривязаны: tests/unit/test_deepar_adapter.py
  (54 кейса: пины DistributionLoss(StudentT)/MAE/robust/
  trajectory_samples + НОВЫЙ test_contract_gate_distribution_loss_
  requires_levels), tests/unit/test_deepar_integration_paths.py
  (cohort-фикстуры loss=DEEPAR_LOSS_KEY).

### TDD (RED -> GREEN, воспроизведено на 4e5df1b)

- RED: (а) suites на статус-кво -- 3 failed
  (test_contract_gate_distribution_loss_requires_levels,
  test_intervals_metadata_declares_native_quantile_surface,
  test_budget_wiring_reaches_the_constructor) + collection ImportError
  DEEPAR_LOSS_KEY в integration_paths; (б) NameError-проб F1 --
  воспроизведён; (в) F3-проб V1 -- вырождение на живом runtime.
- GREEN: suites 54/54; оракулы Дарио **78/78 fast** + **6/6 real_fit**
  (CISSTAT_CERT142_REAL=1: e01 честная ШИРИНА >= 1% масштаба, e02
  монотонность W(0.01)>W(0.05)>W(0.10), e05 масштаб точки
  отслеживает данные, e03 same-seed бит-паритет, e04 min_series-гейт
  ДО фита, h13 РЕАЛЬНЫЙ panel-движок 2 folds) -- 84/84.
- Мутационная кампания ВОСПРОИЗВЕДЕНА на 4e5df1b+фикс (foreground
  батчами по 15, урок Task 139): **60/60 KILLED, выживших нет**
  (M34a/M59/M60/M61 -- мутации самого фикса -- убиты; восстановление
  байт-чистое, снапшот-протокол).

### Верификация

- Полная регрессия: **2464 passed / 0 failed** (unit 1728, включая
  snapshot 3; api 636; прочие 100) -- арифметика сходится: 2463
  базлайн Task 143 + 1 новый тест Дарио.  neural-тесты ИСПОЛНЯЛИСЬ
  (neuralforecast 3.2.2 + torch 2.14.0+cpu -- та же сертификационная
  пара Tasks 137-142).
- NOTE окружение (пре-существующее, НЕ связано с 142a): тест
  test_egarch_adapter.py::test_explicit_optimizer_budget_converges_
  pathological_slice падал на чистом 4e5df1b ДО правок (воспроизведено
  stash-прогоном -- пре-существующее отклонение окружения): свежий
  venv принёс scipy 1.18.1, а премиса characterization-теста
  (сырой фит НЕ сходится на патологическом срезе) чувствительна к
  оптимизаторному стеку; arch-версия исключена (воспроизводилось и на
  arch 7.2.0).  Выравнивание venv на сертификационную эпоху
  (scipy==1.14.1, numpy==2.1.3, pandas==2.2.3, arch 7.2.0) вернуло
  тест зелёным; дальше -- полный прогон выше на выровненном
  окружении; pip check -- No broken requirements.
- compileall OK; app-import OK (FastAPI); rules-smoketest exit=0.
- E2E-смоук scripts/task142_e2e_smoke.py (env-рычаг 60): ВСЕ 7 СЕКЦИЙ
  OK (24 connected -> deepar production+blocked F05 -> panel-движок
  2 folds mae=**3.3732** против 116.1194 на статус-кво -- численное
  подтверждение фикса на полном session-цепочке -> panel tuning 4/4
  -> cohort-изоляция -> честный отказ 4<5).
- Фронтенд не затронут (git diff -- 0 файлов .ts/.tsx -- прецедент
  Task 139a/140a/142: typecheck/build обеих оболочек не запускались).

### Границы Task 142a (что осознанно НЕ сделано)

- Исторические записи журнала НЕ редактировались (append-only;
  записи Дарио сохраняют свою синхронизацию main@68a0cb7 -- параллельная
  работа до коммита Task 143).
- Мутационная кампания Task 137 НЕ перезапускалась: её строковый якорь
  whitelist'а стал stale после аддитивного расширения (отмечено Дарио
  в записи пересертификации; перепривязка -- при следующем касании
  cert137).
- Dockerfile-проба DeepAR структурна (не в production-образе) --
  мандат Дарио сохранён.
- Эксплуатационная находка Task 143 п.3 (tft wall-time 182 c >
  step_timeout 120 c standard-класса на benchmark-хосте) -- вне
  мандата; правка ресурсных политик -- зона тимлида.
- Vercel/render.com контур НЕ трогался (правки backend-only; PRE-0
  смоук Task 143 не воспроизводился -- прод-деплой правки не получал).

Изменённые/новые файлы (ZIP: download/task142a_apply_on_4e5df1b.zip):
- НОВЫЕ: scripts/audit_scripts/{cert142_oracles, cert142_mutations,
  task142_fix_surface_probe, task142_fix_surface_probe12,
  task142a_f3_validation_probe, task142a_f1_nameerror_probe}.py
- ИЗМЕНЁННЫЕ: apps/api/model_impls/deepar.py, apps/api/neural_contract.py,
  apps/api/routers/modeling_session.py, apps/api/model_execution.py,
  apps/api/model_impls/__init__.py, tests/unit/test_deepar_adapter.py,
  tests/unit/test_deepar_integration_paths.py, worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@4e5df1b + перечисленные изменения.

---

## Сертификация Task 143 (аудит) -- финализация полной production-матрицы 24x11 (коммит 4e5df1b, коллега Сэм) + применение фикса Task 143a

Дата: 2026-09-14. Синхронизация: main@6768354 (Task PRE-1 --preprocessing-степпер; backend идентичен 4e5df1b кроме Task 142a:sha256-сверка session_store-контракта до правок). Постановка тимлида:«проведи разведку кода и честно сертифицируй выполненную коллегой задачуTask 143; при аудите используй также мутационные и оракул тесты на своихданных». Протокол сертификаций Task 136-142 (cert136..cert142_*):count-gates на артефакте + независимые оракулы на СОБСТВЕННЫХ данных +мутационная кампания + RED-верификация тестов исполнителя + полнаярегрессия. Аудиторский контур: scripts/audit_scripts/cert143_oracles.py, cert143_mutations.py,task143a_fA_validjson_probe.py (НОВЫЕ).

### Разведка кода (git show 4e5df1b --stat: 13 файлов, +1921/-26)
Ядро Task 143: (а) apps/api/session_store.py -- якорьSESSION_SCHEMA_VERSION=1, штамп в session_to_dict, future-versionwarning в session_from_dict, деградация get() на нечитаемом документе(UnicodeDecodeError в кортеже), save() поверх мусора (revision=0);(б) scripts/task143_matrix_benchmark.py (НОВЫЙ, 761 строка) -- секцииA (реестр/матрица 24x11), B (backtest 24 модели через 4 движка),C (tuning 18), D (timeout-политика/память); (в) reports/report.{json,md}-- зафиксированный артефакт прогона; (г) rules/modeling.yaml 1.2.0;(д) docs/MIGRATION_ARCHITECTURE.md (НОВЫЙ); (е) pre_0/pre_1 smokeCLI/env-контракт. Фронтенд: 0 файлов .ts/.tsx -- сборки не требуются(прецедент 142a).

### Независимая верификация деклараций (оракулы на СВОИХ данных, seed 20261)
- Группа A -- count-gates на артефакте Сэма (11 оракулов):24/24 backtest (19 main + 2 vector + 2 volatility + 1 panel) --рассечение по движкам сверено с input_kind реестра; 18/18 tuning(13 classical @2 + 5 neural @1); 20/20 уникальных MAE (не заглушка);OOF-арифметика (main 24 = 2x12, vector 36 = 3x2x6, volatility 12,panel 6); volatility -- qlike primary, vector -- scaled_loss; находкаtimeout tft 182086.9 ms > 120000 ms зафиксирована честно (не проглочена);report.md согласован с report.json (24 строки backtest, секция«Находки»).
- Группа B -- session_store на своих payload'ах/fakeredis (17): штамп==1 в сериализации и после roundtrip собственного датафрейма; legacy(без поля) читается как схема 0 БЕЗ future-warning; документ версии 99читается с warning'ом, содержащим session id и обе версии; текущаяверсия НЕ дисклоужается как «новее»; коррапт-классы (JSONDecodeError,бинарь, усечённый JSON) -> get()=None+warning; get_or_create выдаётсвежую сессию; save() поверх мусора перезаписывает; CAS НЕ ослаблен(stale-write на валидном документе обязан конфликтовать -- анти-мутационный оракул); инкремент ревизии == +1; model_jobs переживаютroundtrip; BacktestResponse без panel валиден, panel переживаетmodel_dump.
- Группа C -- честность benchmark-скрипта (8): TUNABLE_ALL ==PRODUCTION_TUNING_MODEL_IDS, группы не пересекаются, deepar в neural;dispatch 24 моделей согласован с реестром; _validation_folds --собственные комбинации (50/5/3/1, 96/8/2/0, 37/4/2/2): expanding-границы, leakage-инвариант test_start > train_end, покрытие до концаряда; section_d behavioral на своих fake-результатах (в т.ч. границаwall == step_timeout -- violation, строгое <); merge-приоритет свежегозамера (свой tmp-отчёт); _metric_of/канонический ряд (тренд ~0.3,сезонная амплитуда); пины honesty-гейтов в исходнике.
- Группа D -- smoke CLI (4): parse_args-дефолты, CLI-оверрайды,env-рычаги CISSTAT_API_URL/CISSTAT_FRONTEND_ORIGIN (monkeypatch),repo-относительный demo-csv существует, stale-пути/home/z/my-project/repo отсутствуют в pre_0/pre_1, READMEдокументирует контракт.
- Группа E -- документы (3): modeling.yaml metadata 1.2.0/2026-09-13(и заголовок); MIGRATION_ARCHITECTURE.md: якоря session_schema_ version/SESSION_SCHEMA_VERSION/storage_revision/§1.1 + docstring-якорь session_store.py синхронизирован; пины 1.2.0 в двух тестах.
- Группа F -- реальные фиты на СВОИХ данных (5, маркер real_fit):main -- ets/naive на своём ряде (n=96, сезон 6, seed 20261): etsчестно бьёт naive, cohort_id -- sha256; vector -- var на своейсистеме из 3 рядов (scaled_loss конечен, vector_baseline); volatility-- garch на своих ценах (QLIKE primary); panel -- deepar на своейпанели из 5 рядов (n=60): mae < 15 (класс деградации до-142a ~110не воспроизводится; подтверждение фикса 142a на benchmark-пути);сырая библиотека + свои данные: DistributionLoss(StudentT)+robust --ширина > 0, масштаб точки OK, квантильное пересечение (анти-рецидивF3).

### Мутационная кампания (34 мутации, foreground батчами)
34/34 KILLED, выживших НЕТ. Поверхность = код Task 143: session_store(s01..s16: якорь/штамп/legacy-дефолт/future-warning/деградация get/save-поверх-мусора/CAS/инкремент/docstring-якорь + анти-регрессия фикса143a s15/s16), benchmark (m01..m12: гейт уникальности >= 15, строгаяграница timeout, сбор нарушений, полнота scope, merge-приоритет,fold-арифметика, QLIKE, канонический ряд, группы тюнинга), smoke(k01..k03: CLI-флаг/дефолт/env), документы (y01/y02 -- версия,d01 -- якорь MIGRATION_ARCHITECTURE). Kill-подмножество --cert143_oracles.py -m "not real_fit" (42 оракула) в свежем subprocess;восстановление байт-чистое (SHA-256 против снапшота).УРОК КАМПАНИИ (документирован в комментариях оракулов): корраптb"\xff\xfe..." начинается с UTF-16-BOM -- json.detect_encodingдекодирует его в ТЕКСТ и падение остаётся JSONDecodeError; такойpayload НЕ убивает срез UnicodeDecodeError из except-кортежа (выжившиеs07/s11 первого батча). Усилено мусором БЕЗ BOM (b"\x80\x81...").

### Находки сертификации
F-A -- БЛОКИРУЮЩАЯ (as-committed), ПРИМЕНЁН ФИКС Task 143a:валидный JSON НЕ-объект (null / число / массив / строка) под ключомсессии крэшил И get(), И save() сырым AttributeError (вне обоихexcept-кортежей) -> 500 на API и вечная блокировка сессии -- ровнота ситуация, которую Task 143 устранял («мусор не несёт ревизии и неможет быть "свежее"»; собственный комментарий кода: «коррапт-запись,бинарный мусор, усечённый JSON»). Тесты Сэма покрывали только классыJSONDecodeError/UnicodeDecodeError. Пробtask143a_fA_validjson_probe.py: 4/4 класса CRASH на чистом дереве.ФИКС (TDD RED->GREEN): TypeError-guard в session_from_dict («Sessiondocument must be a JSON object») + AttributeError в except-кортежеsave() (inline json.loads().get() до session_from_dict); RED 6/6(новый класс TestNonObjectDocumentDegradation), GREEN 82/82test_session_store.py.
F-B -- не блокирующая (косметика отчёта, НЕ правилась):_write_reports пишет заголовок «Timeout-политика: все модели впределах step_timeout» БЕЗУСЛОВНО -- в зафиксированном report.md(tft-нарушение есть) заголовок противоречит секции «Находки».Рекомендация: условная формулировка при следующем касании скрипта.
F-C -- не блокирующая (наследие 142a): собственный cohortбенчмарка объявляет deepar loss="mqloss" (семантика ДО 142a);адаптер loss cohort'а не потребляет (исполняет DistributionLossчерез DEEPAR_LOSS_KEY) -- бенчмарк исполняем и честен на текущемдереве (подтверждено моей панелью, группа F), но декларация cohort'аstale. Рекомендация: DEEPAR_LOSS_KEY при следующем касании.
Унаследованная открытая находка Сэма (п.3): tft wall 182 c >step_timeout 120 c standard-класса на benchmark-хосте -- вне мандатасертификации, решение тимлида.
RED-верификация тестов исполнителя
Свап apps/api/session_store.py на 68a0cb7 (пре-143) по снапшот-протоколу: тест-файл Сэма НЕ СОБИРАЕТСЯ (ImportErrorSESSION_SCHEMA_VERSION -- якоря не существовало) -- 11 новых кейсовчестно RED-first; восстановление байт-чистое (SHA-256).

### Верификация (после применения фикса Task 143a)
Оракул-сьюита: 47/47 GREEN (42 fast по ~3.8 c + 5 real_fit ~52 c).
Мутационная кампания: 34/34 KILLED.
Полная backend-регрессия: 2470 passed / 0 failed (~6:53) --арифметика сходится: 2464 (базлайн 142a) + 6 новых кейсов F-A;нейро-тесты ИСПОЛНЯЛИСЬ (torch 2.14.0+cpu + neuralforecast 3.2.2 --сертифицированная пара; pip check clean).
compileall OK; app-import OK (FastAPI); rules-smoketest exit=0(scripts/check_rules_smoketest.py).
E2E-смоук scripts/task142_e2e_smoke.py: ВСЕ 7 СЕКЦИЙ OK(24 connected -> panel-движок -> panel tuning 4/4 -> cohort-изоляция-> честный отказ 4<5) -- фикс F-A не ломает session-цепочку.
Фронтенд не затронут (0 файлов .ts/.tsx) -- typecheck/build обеихоболочек не запускались (прецедент 139a/140a/142/142a).

### ВЕРДИКТ СЕРТИФИКАЦИИ
Как закоммичено (4e5df1b): НЕ СЕРТИФИЦИРОВАНА -- блокирующая F-Aв п.4 постановки (контракт деградации коррапта заявлен ширереализованного: класс «валидный JSON не-объект» валил API сырымAttributeError и блокировал сессию навсегда).
Ядро финализации (п.1 реестр/матрица 24x11, п.2 полный executionscope 24+18, п.3 performance/timeout/memory, п.5 PRE-0/PRE-1 smoke,п.6 документация, п.7 сборка/регрессия) -- ПОДТВЕРЖДЕНО ПОЛНОСТЬЮ(count-gates + оракулы + мутации на собственных данных).
После применения Task 143a (фикс F-A, полный цикл AGENTS.md):СЕРТИФИЦИРОВАНА -- 47/47 оракулов, 34/34 мутаций KILLED,регрессия 2470/0, e2e 7/7.

### Границы (что осознанно НЕ сделано)
F-B/F-C не правились (косметика отчёта и stale-декларация cohort'а --рекомендации к следующему касанию; артефакт reports/ -- снимокмомента Сэма, не фальсифицировался).
Правка step_timeout/бюджета TFT -- зона тимлида (отдельнаяпостановка; открыта с Task 143 п.3).
Полный повторный прогон 24-модельного benchmark НЕ выполнялся(дорого; честность артефакта установлена count-gates + собственнымиреальными фитами всех четырёх движков на своих данных).
Исторические записи журнала НЕ редактировались (append-only).
Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее деревоmain@6768354 + перечисленные изменения.
Изменённые/новые файлы (ZIP: download/task143_certification.zip):

НОВЫЕ: scripts/audit_scripts/{cert143_oracles, cert143_mutations,task143a_fA_validjson_probe}.py
ИЗМЕНЁННЫЕ: apps/api/session_store.py (фикс F-A -- TypeError-guard +AttributeError в кортеже save()),tests/api/test_session_store.py (класс TestNonObjectDocument-Degradation, 6 кейсов), worklog5.md (этот журнал)

---

## Task w/n-3 -- Вкладка «Предобработка»: бейдж-паттерн переключателей представлений «Обзора» остановки «Генерация признаков» распространён на ВСЕ остановки степпера (кроме «Масштабирования» -- паттерн уже применён)

Дата: 2026-09-14. Синхронизация: main@30d00d4 (Task 143 certification +
фикс 143a, закоммичен тимлидом; рабочее дерево чистое).  Постановка
тимлида: нижнее центральное окно «Обзор» переключает графики/таблицы
внутренними вкладками; на остановке «Генерация признаков» -- бейджи
«Превью»/«Лаг корреляции»/«Доступность»/«Циклы»/«Каталог»; паттерн
(серые бейджи с рамкой, увеличение интенсивности фона при наведении)
распространить на ВСЕ остановки степпера «Предобработки», кроме
«Масштабирования» (там применён).  Полный цикл AGENTS.md: TDD
RED->GREEN, полная frontend-регрессия, typecheck/build обеих оболочек.

### Диагностика (точки изменения; эталон -- PreprocessingFeatureEngineeringOverview.tsx:109, паритет PreprocessingScalingOverview.tsx:110)

Эталонный контракт: tablist ВНУТРИ шапки Обзора (блок `shrink-0 border-b
border-neutral-100 p-4`, после рекомендации/легенды), контейнер
`mt-3 flex flex-wrap gap-2`, кнопки `role="tab"` + `aria-selected`,
классы `rounded-full border px-3 py-1 text-xs`; активный
`border-neutral-300 bg-neutral-200 text-neutral-800`, неактивный
`border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100`
(рамка + усиление фона при наведении).  Три legacy-варианта в 8
остановках:

- **Вариант A -- классические вкладки** (Missing, Outliers, Regularity):
  отдельная строка `flex gap-1 border-b px-4 pt-2`, кнопки `rounded-t
  px-3 py-1.5 font-medium`, активный `bg-white text-brand border-b-0`
  (индиго-текст), семантика `aria-pressed` БЕЗ ролей tablist/tab.
- **Вариант B -- pill в отдельной строке** (Decomposition, Variance,
  Smoothing, Stationarity): цвета уже эталонные, НО строка отдельно от
  шапки (`border-b px-4 py-2 gap-1.5`), геометрия `px-3 py-1.5 font-medium
  transition-colors`.
- **Вариант C -- pill без рамки с ring** (Spectral): в шапке, НО кнопки
  `bg-neutral-100` БЕЗ border, активный `ring-2 ring-neutral-400`,
  неактивный `text-neutral-600 hover:bg-neutral-200`.

### Решение

1. **A-вариант (3 файла)**: module-level `type`-union + `const TABS`
   (прецедент эталона); tablist перенесён внутрь шапки последним
   элементом (после легенды статистик), старая отдельная строка УДАЛЕНА;
   кнопки -- эталонные классы + `role="tab"`/`aria-selected` (вместо
   `aria-pressed`).  aria-label: «Представления проверки пропусков» /
   «...выбросов» / «...регулярности».  Примечание: индикаторные
   бейджи-«переключатели представлений» вида `rounded-t` исчезли --
   активная заливка теперь нейтрально-серая (как в эталоне), индиго
   остаётся цветом действий/ссылок, не переключателей.
2. **B-вариант (4 файла)**: tablist перенесён внутрь шапки (после
   recommendation/warnings), отдельная строка удалена; контейнер
   `mt-3 flex flex-wrap gap-2`; классы `px-3 py-1.5 text-xs font-medium
   transition-colors` -> `px-3 py-1 text-xs` (снят лишний вес шрифта и
   мёртвая transition -- hover в Tailwind-палитре нейтралей без
   анимационного контракта, эталон transition не имеет).  Имена
   tablist'ов СОХРАНЕНЫ (прижаты существующими тестами: «Графики
   сглаживания ряда» и др.).
3. **C-вариант (1 файл)**: только классы кнопок -> эталон (border вместо
   ring-2 у активного); tablist уже был в шапке с `mt-3 flex flex-wrap
   gap-2` -- без переноса.
4. **Правка B-файлов Smoothing/Stationarity выполнена якорным
   Python-скриптом** (scripts/task_wn3_fix_bc.py вне репозитория,
   песочница): точечная замена по трём якорям (tablist-класс, класс
   кнопок, хвост `</p>}</div><div role="tablist"`) -- однострочный
   формат этих компонентов не дал использовать Edit-якоря надёжно.
5. **Честные границы переиспользования**: разметка/тексты/иконки
   представлений, ExpandableChartPanel-обёртки, условные рендеры
   (Outliers: строка «Признак: ...» при не-табличных видах; Spectral:
   панель фазы только при наличии данных) -- БИТ-НЕИЗМЕННЫ; правился
   ТОЛЬКО слой переключателей.  Степпер TsAnalysisPreprocessing.tsx,
   маунт-точки компонентов, backend -- не тронуты.

### TDD (RED -> GREEN)

- RED: 8 новых кейсов «переключатели представлений следуют бейдж-паттерну
  «Генерации признаков»» -- по одному в каждом тест-файле; контракт
  прижат ПОЛНОСТЬЮ: tablist с именем, классы контейнера `mt-3 flex
  flex-wrap gap-2`, размещение ВНУТРИ шапки (`parentElement` имеет
  `p-4` и `border-b border-neutral-100`), активный/неактивный бейдж с
  ПОЛНЫМ набором эталонных классов (включая `hover:bg-neutral-100`),
  семантика `aria-selected`.  Попутно 3 существующих запроса
  `getByRole("button", ...)` переведены на `getByRole("tab", ...)`
  (Missing: «Матрица»; Outliers: «Гистограмма»; Regularity:
  «Интервалы») -- явная роль tab перекрывает неявную button.
  Результат RED: 11 failed / 39 passed -- падения ТОЧНО дефектные (8
  контрактов на трёх legacy-вариантах + 3 запроса к ещё не
  переписанным A-компонентам).
- GREEN: правки 8 компонентов -> 8 сюит / 50 тестов PASSED (39 + 11 --
  арифметика сходится).

### Верификация

- Полная frontend-регрессия: **97 сюит / 925 тестов PASSED / 0 failed**
  (75 с).  Арифметика: базлайн 30d00d4 = 917 (= 914 Task IA-1 + 3 кейса
  из коммитов 4f8a9ef/6768354/d9377ef) + 8 новых кейсов = 925.
  Регрессий вне задачи нет.
- Сверка единства паттерна программно по всем 10 файлам
  Preprocessing*Overview.tsx (включая 2 эталона): geometry/active/
  inactive-классы + tablist-in-header -- все True, набор байт-одинаков.
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (embedded 13/13,
  standalone 17/17 static pages).
- aria-pressed в Preprocessing*Overview.tsx -- 0 вхождений (паттерн
  aria-selected вынесен везде).

### Границы Task w/n-3 (что осознанно НЕ сделано)

- EDA- и Validation-Обзоры НЕ трогались (мандат постановки -- только
  «Предобработка»; в EDA свой набор legacy-вариантов -- при
  необходимости отдельная постановка).
- Правка применяется в ОБЕИХ оболочках через общий пакет packages/ui
  (прецедент Task w/n: общий компонент, форков нет).
- Мобильная механика (горизонтальный скролл/перенос бейджей) -- не
  менялась: `flex-wrap` эталона сохранён во всех 10.
- Backend/контракты данных не затронуты (0 файлов .py; git diff --
  16 файлов, все .tsx).
- Исторические записи журнала НЕ редактировались (append-only).

Изменённые/новые файлы (ZIP: download/task_wn3_preprocessing_badge_pattern.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/{PreprocessingMissingOverview,
  PreprocessingOutliersOverview, PreprocessingRegularityOverview,
  PreprocessingDecompositionOverview, PreprocessingVarianceOverview,
  PreprocessingSmoothingOverview, PreprocessingStationarityOverview,
  PreprocessingSpectralOverview}.tsx + их .test.tsx (8+8 = 16 файлов)
- worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@30d00d4 + перечисленные изменения.

---

## Task w/n-4 -- Вкладка «Разведочный EDA»: бейдж-паттерн переключателей представлений «Обзора» вкладки «Предобработка» применён ко ВСЕМ остановкам степпера EDA (10 Обзоров)

Дата: 2026-09-14. Синхронизация: main@f0d2698 (Task w/n-3 закоммичен
тимлидом; рабочее дерево приведено к коммиту, локальный однострочный
рассинхрон worklog5.md отброшен -- содержимое идентично).  Постановка
тимлида: применить бейдж-паттерн переключателей представлений «Обзора»
вкладки «Предобработка» (эталон «Генерация признаков», раскатанный на
все остановки в Task w/n-3) ко всем остановкам степпера вкладки
«Разведочный EDA».  Прямое продолжение w/n-3: там граница задачи
явно фиксила «EDA- и Validation-Обзоры НЕ трогались... отдельная
постановка».  Полный цикл AGENTS.md: TDD RED->GREEN, полная
frontend-регрессия, typecheck/build обеих оболочек.

### Диагностика (точки изменения; эталон -- PreprocessingFeatureEngineeringOverview.tsx:109)

Контракт эталона (зафиксирован тестами в w/n-3): tablist ВНУТРИ шапки
Обзора (блок с p-4/p-3 и border-b border-neutral-100), контейнер
`mt-3 flex flex-wrap gap-2`, геометрия бейджа `rounded-full border
px-3 py-1 text-xs`, активный `border-neutral-300 bg-neutral-200
text-neutral-800`, неактивный `border-neutral-200 bg-neutral-50
text-neutral-500 hover:bg-neutral-100`, семантика aria-selected.

Состояние 10 Обзоров EDA до правки -- 3 legacy-варианта переключателей:
(a) «подчёркивание»: `rounded-t` + active `border border-b-0 bg-white
text-brand` (Descriptive, Correlation, Seasonality, IH -- у IH ещё
overflow-x-auto/whitespace-nowrap/px-2.5); (b) «заливка»: `rounded-t`
+ active `bg-brand text-white` (Distribution, Stationarity,
StructuralBreaks, FeatureSelection, ValidationStrategy, ModelMatrix);
у Descriptive вдобавок aria-pressed рядом с aria-selected.  Общий
дефект: tablist ВНЕ шапки -- отдельным блоком между шапкой и контентом.

### TDD (RED -> GREEN)

- RED: 10 новых кейсов «переключатели представлений следуют
  бейдж-паттерну «Обзора» «Предобработки»» -- по одному в каждом
  тест-файле (EdaDescriptiveOverview, EdaCorrelationOverview,
  EdaIhOverview, EdaSeasonalityOverview, EdaStationarityOverview,
  EdaDistributionOverview, EdaStructuralBreaksOverview,
  EdaFeatureSelectionOverview, EdaValidationStrategyOverview,
  EdaModelMatrixOverview).  Контракт прижат ПОЛНОСТЬЮ: tablist с
  именем, классы контейнера `mt-3 flex flex-wrap gap-2`, размещение
  ВНУТРИ шапки (parentElement имеет p-4; для IH -- p-3, шапка IH
  сохранена как есть -- суть контракта «внутри шапки», не конкретный
  паддинг), активный/неактивный бейдж с ПОЛНЫМ набором эталонных
  классов (включая hover:bg-neutral-100), семантика aria-selected.
  Роль tab уже использовалась всеми 10 компонентами (в отличие от
  w/n-3, миграции getByRole("button") не потребовалось).  Результат
  RED: 10 failed / 39 passed -- падения ТОЧНО дефектные.
- GREEN: правки 10 компонентов -> полная регрессия 97 сюит /
  935 тестов PASSED (39 + 10 -- арифметика сходится).

### Верификация

- Полная frontend-регрессия: **97 сюит / 935 тестов PASSED / 0
  failed** (45 с).  Арифметика: базлайн f0d2698 = 925 + 10 новых
  кейсов = 935.  Регрессий вне задачи нет.
- Сверка единства паттерна программно по всем 10 файлам
  Eda*Overview.tsx: geometry/active/inactive-классы + контейнер
  `mt-3 flex flex-wrap gap-2` -- все True; legacy-артефакты
  (rounded-t / bg-brand text-white / border-b-0 / aria-pressed) --
  0 вхождений в коде (единственное совпадение -- текст
  поясняющего комментария в EdaDescriptiveOverview).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (embedded 13/13,
  standalone 17/17 static pages).

### Особенности реализации (решения по границам)

- 8 Обзоров с ранними return'ами (Descriptive, Correlation, IH,
  Seasonality, Stationarity, Distribution, StructuralBreaks,
  FeatureSelection): tablist перенесён последним элементом шапки;
  видимость не изменилась (шапка и так рендерится только при готовых
  данных).  У IH шапка p-3 сохранена (контракт «tablist внутри шапки»
  соблюдён, паддинг шапки -- ортогональная деталь).
- ValidationStrategy и ModelMatrix: шапка рендерится ВСЕГДА (в том
  числе в loading/error/no-dataset), а переключатели жили в
  условной ветке контента.  Tablist перенесён в шапку с guard
  `!loading && !error && !noDataset && profile && profile.applicable`
  -- видимость переключателей по состояниям сохранена 1:1 (в
  loading/error/пустых состояниях бейджи по-прежнему скрыты).
- FeatureSelection: шапке добавлен `border-neutral-100` (был голый
  border-b) -- гармонизация с эталоном, визуально почти неотличимо.
- aria-pressed удалён из EdaDescriptiveOverview (единственное
  вхождение в EDA; прецедент w/n-3: aria-selected везде).
- Мобильная механика: overflow-x-auto/whitespace-nowrap IH заменены
  на flex-wrap эталона (5 бейджей переносятся строкой, как в
  «Предобработке»); в остальных файлах flex-wrap уже был или добавлен
  эталонным контейнером.
- Backend/контракты данных не затронуты (0 файлов .py); маунт-точки
  TsAnalysisEDA.tsx, степпер, роли/aria-labelы переключателей --
  БИТ-НЕИЗМЕННЫ; правился ТОЛЬКО слой переключателей и их размещение.
- Исторические записи журнала НЕ редактировались (append-only).

Изменённые/новые файлы (ZIP: download/task_wn4_eda_badge_pattern.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/{EdaDescriptiveOverview,
  EdaCorrelationOverview, EdaIhOverview, EdaSeasonalityOverview,
  EdaStationarityOverview, EdaDistributionOverview,
  EdaStructuralBreaksOverview, EdaFeatureSelectionOverview,
  EdaValidationStrategyOverview, EdaModelMatrixOverview}.tsx +
  их .test.tsx (10+10 = 20 файлов)
- worklog5.md (этот журнал)
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@f0d2698 + перечисленные изменения.

---

## Task FORECAST-1 -- Этап «Прогнозирование»: полный вертикальный срез по spec_forecasting2.md (final fit + 4 метода интервалов + session-контур + вкладка UI)

Дата: 2026-09-14. Синхронизация: main@30d00d4 (Task 143 certification
+ Task 143a fix). Постановка тимлида: «создаем модуль Прогнозирование;
изучи spec_forecasting2.md (основа) и spec_education.md (контекст вклада
в архитектуру обучения); улучшения обоснуй и примени; спроектируй вкладку
и реализуй в коде по паттернам платформы; следуй AGENTS.md».  Спецификация
v3 (2026-09-08) писалась до production-адаптеров tree_ml/neural и до
Model Execution Contract v2 как единственной точки исполнения -- по
прецеденту сертификаций (декларации сверяются с фактическим кодом)
применены УТОЧНЕНИЯ, не меняющие методологии §1-§10.

### Решение (по пунктам постановки)

1. **Исполнение через MODEL_EXECUTION_REGISTRY, не PRODUCTION_PREDICTORS**
   (уточнение к §3): spec предлагала вызов PRODUCTION_PREDICTORS[model_id]
   (backtesting.py), но это compatibility-facade ПОВЕРХ реестра
   (model_execution.py::legacy_predictor_registry «Compatibility facade for
   callers that still inject plain functions»).  Финальный рефит исполняет
   точку ИСКЛЮЧИТЕЛЬНО через MODEL_EXECUTION_REGISTRY.execute
   (ModelExecutionRequest с train/future timestamps -- обязательны для
   prophet) -- та же сертифицированная точка исполнения, что и бэктест.
2. **Хранение артефактов -- modeling_artifacts["forecasts"]** (уточнение
   к §5.9): spec предполагала modeling_pipeline["forecasts"], но
   modeling_pipeline -- dict[str, StageStatus] (статусы стадий).  Прогнозы
   хранятся по фактическому паттерну артефактов сессии (как model_cards);
   Redis-roundtrip покрыт тестом; инвалидация forecasts связана с
   инвалидацией model_cards во ВСЕХ четырёх точках очистки (не могли бы
   стать stale-ссылками на исчезнувшие карты) + сброс stages["forecasting"].
3. **Расширение классификации ci_method с 11 до 19 моделей** (уточнение
   к §4): spec перечисляла baseline+statsmodels+prophet/tbats; дерево
   (Tasks 127-130: квантильные интервалы) и нейро-четвёрка (Tasks 138-141:
   conformal/MQLoss с alpha-ручкой) появились позже и имеют СЕРТИФИЦИРОВАННЫЕ
   нативные интервалы.  Итоговая карта:
   - analytic: arima/auto_arima (get_forecast().summary_frame(alpha)),
     theta (prediction_intervals(steps, theta, alpha) -- другой API, §10.3);
   - parametric_simulation: ets/ets_damped (simulate + rng, §4.1a);
   - native_adapter: prophet/tbats (80%), tree_ml (90%), lstm/nbeats/nhits/tft
     (alpha-ручка);
   - empirical_oof_quantile: baselines (обязателен, §4.2).
   var/vecm/garch/egarch/deepar -- честный 422: comparison/selection валидируют
   objective=level_forecast, их Model Card недостижима (objective-изоляция
   cohort'ов); multi-objective прогнозы -- отдельная постановка.
4. **Alpha-политика (§5.2 + дисклоужер)**: нейро -- запрошенная alpha
   прокидывается в params с сертифицированным whitelist {0.01, 0.05, 0.10}
   (вне -- fail-closed 422); prophet/tbats/tree_ml -- ФИКСИРОВАННАЯ alpha
   адаптера (0.20/0.10), запрошенная НЕ подменяется другим методом -- интервал
   как есть + честный warning-дисклоужер (прецедент provenance Task 141);
   empirical/analytic/simulation -- любая alpha в (0,1), дефолт 0.05.
5. **Финальный рефит (§3)**: apps/api/final_fit.py::build_final_fit --
   forward-цепочка target-препроцессинга ОДИН раз на полной истории
   (переиспользование _resolve_chain/_make_scaler/_inverse_stationarity/
   apply_variance_transform/apply_smoothing_series из fold_preprocessing --
   НИ ОДНОЙ дублирующей формулы); fixed-lambda фиксируется, оценённая --
   переоценивается на полной истории (та же семантика, что у fold-препро-
   цессора на train-фолде); restore() вызывается ПО ОТДЕЛЬНОСТИ для точки
   и каждой границы интервала -- для log_difference интервал в исходной
   шкале асимметричен корректно (тест прижимает).  Необратимая цепочка
   (сглаживание, inverse_supported=False) и некаузальный smoother --
   честный 422.
6. **Паритет-гейт**: для analytic/simulation интервалы требуют объект
   фита -- модуль делает СОПРЯЖЁННЫЙ фит тем же классом модели/данными/
   параметрами (зеркало сертифицированных адаптеров) и прижимает честность
   гейтом: расхождение точки реестра и интервального фита (rtol 1e-6) --
   ForecastingError, а не молчаливая подмена источника прогноза.  Дрейф
   зеркала ловит гейт, а не пользователь.
7. **Эмпирический метод (§4.2)**: интервал = точка + квантиль OOF-остатков
   СВОЕГО horizon_step (остатки уже в исходной шкале -- инверсия не нужна);
   шаги за training.horizon -- квантиль последнего валидированного шага +
   честный warning «консервативная оценка... не валидирован эмпирически»;
   coverage (§4.3) -- in-sample доля OOF-точек в ретроспективных интервалах,
   заполняется ТОЛЬКО для эмпирического метода (интервалы других методов
   нельзя задним числом посчитать без переобучения на каждом train-фолде).
8. **Аномалии (§5.8)**: переиспользование detect_outlier_mask (Task 60, IQR)
   на объединении «история+прогноз»; флаг -- предупреждение, не запрет.
9. **TraceEvent -- общий контракт (рекомендация §10.4 ПРИНЯТА)**: НОВЫЙ
   apps/api/trace_events.py -- канонический датакласс + make_trace_event
   (fail-closed на неизвестном event_type); 4 типа событий этапа
   (forecast_generated/compared/sensitivity_computed/exported) пишутся в
   ForecastRun.trace_events (формат готов к будущему «Прогрессу» без
   миграции).  GET-экспорт фиксирует forecast_exported и переводит
   stages["forecasting"] в done (дефолт §10.5 по прецеденту Моделирования --
   derived-статус, без кнопки «Готово»); клиентский PNG -- POST /trace.
10. **Сравнение прогнозов (§5.6)**: сравниваются УЖЕ ПОСТРОЕННЫЕ артефакты
    (POST /compare {forecast_ids}, 2..4) с событием в каждом участнике --
    без скрытой регенерации и без нового ранжирования (ранжирование закрыто
    этапом Моделирования).  Спека предполагала генерацию по model_card_ids --
    отклонение в сторону честности: сравнение существующих прогнозов не
    дублирует фиты и сохраняет lineage каждого прогноза.
11. **Чувствительность (§5.7)**: веер по УГЛАМ param_space из
    rules/modeling.yaml ( ModelingSpec.get_model; по каждой оси
    первый/последний элемент списка значений -- без сортировки, значения
    категориальные), дедуплицированное произведение с потолком 8; params =
    card_hyperparams + combo; базовая трансформация истории общая (рефит
    только модели).  Пустой param_space -- честный 422; нейро --
    предупреждение о времени.
12. **Экспорт (§5.5)**: CSV (date,actual,forecast,ci_lower,ci_upper:
    история 96 + прогноз 2) и JSON (ForecastRun целиком, самодостаточен) --
    backend; PNG -- клиентская сериализация SVG (XMLSerializer -> canvas ->
    toBlob, scale 2, без новых зависимостей); **PDF сознательно НЕ
    реализован (уточнение к §5.5)**: jsPDF не содержит кириллических
    шрифтов -- текстовый PDF требует встраивания шрифта (~200+ КБ) и
    выбора лицензии; PDF-из-то-же-PNG ценности не добавляет.  Отдельная
    мелкая постановка.
13. **Freshness-гейты (lineage)**: fingerprint ряда обязан совпадать с
    card.data_summary.fingerprint (409 «Model Card устарела»); методы
    цепочки target-препроцессинга сессии обязаны совпадать с
    card.training.preprocessing.transformations (409 «цепочка расходится»);
    ensemble-карты -- честный 422 (прогноз ансамбля -- отдельная постановка).
14. **Frontend**: TsAnalysisForecasting.tsx -- 3-колоночный лейаут по
    принятому паттерну (левый: шапка+справка '?'+шаги этапа со StatusIcon+
    hand-off карты; центр: описание/справка с раскрыванием, честные гейты
    «Загрузите датасет»/«завершите Моделирование»/«сформируйте Model Card»
    со ссылкой, ForecastChart (факт + пунктирный прогноз + лента интервала
    Area + красные аномалии + ReferenceLine начала прогноза, h-468),
    ForecastAccuracyPanel (дисклоужер «по результатам бэктеста -- не
    точность этого прогноза», сетка метрик + честное «недоступно для этого
    метода» для coverage), предупреждения, веер, lineage-note; правый:
    селектор карт, горизонт (дефолт training.horizon), alpha {0.01,0.05,
    0.10}, кнопка прогноза, история с чекбоксами сравнения (до 3), кнопка
    сравнения, веер, ForecastExportMenu (CSV/JSON/PNG)).  lib/forecasting.ts
    -- типы 1:1 с ForecastRunResponse + человекочитаемые подписи ci_method/
    alpha_source.  Подкомпоненты -- самостоятельные файлы по манифесту §8.
15. **GET /card (список карт)** -- аддитивный сводный эндпоинт
    (card_id/model_id/model_name/selection_kind/horizon/fingerprint/
    created_at): существовал только POST /card и GET /card/{id} -- списка
    не было ни для прогнозирования, ни для UI вообще.

### TDD (RED -> GREEN)

- RED: tests/unit/test_forecasting_contract.py (13) +
  tests/unit/test_final_fit.py (14) + tests/unit/test_forecasting.py (17) +
  tests/api/test_forecasting_session.py (21) -- collection errors на
  отсутствии модулей/эндпоинтов (RED-first, прецедент Tasks 138-142).
  Поверхность ожиданий снята пробом ДО реализации:
  scripts/task_forecast1_interval_api_probe.py (ARIMA summary_frame;
  Theta prediction_intervals(steps, theta, alpha) -> DataFrame[lower,upper];
  ETS simulate(shape nsteps x reps, kwarg rng, anchor=end) -- random_state
  int устарел; нелинейная инверсия границ log_difference даёт асимметрию).
  Правки ОЖИДАНИЙ по снятой эмпирике: рецепты тестов -- фактические
  метаданные сессии (kind=smoothing/stationarity; seasonal_period >= 2 --
  гейт apply_stationarity_series); coverage на достаточной выборке
  (экстремальные квантили малой выборки исключают крайние точки).
- GREEN backend: 65/65 (44 unit + 21 api).  Контур: 2535 passed / 0 failed
  (2470 базлайн 30d00d4 + 65 новых -- арифметика сходится), нейро-тесты
  ИСПОЛНЯЛИСЬ (torch 2.14.0+cpu + neuralforecast 3.2.2 -- сертифицированная
  пара Tasks 137-142; окружение восстановлено из requirements.txt +
  apps/api/requirements.txt + requirements-dev.txt + нейро-группы +
  выравнивание сертификационной эпохи scipy==1.14.1/numpy==2.1.3/
  pandas==2.2.3/arch==7.2.0; pip check -- No broken requirements).
- GREEN frontend: 5 новых сюит (ForecastChart 4 / ForecastAccuracyPanel 5 /
  ForecastHistoryList 5 / TsAnalysisForecasting 9 / forecasting page 1) --
  полная регрессия 102 сюиты / 941 тест passed (было 97/914: +5 сюит /
  +27 тестов -- арифметика сходится).  typecheck:all -- 0 ошибок (обе
  оболочки); build:all -- Compiled successfully x2 (13/13 и 17/17 static
  pages), маршрут /forecasting в production-манифесте обеих оболочек.
- E2E-смоук scripts/task_forecast1_e2e_smoke.py: 41/41 проверок (полный
  путь до карты -> прогнозы обоих методов с паритет-гейтом -> предупреждение
  о горизонте -> история -> compare -> sensitivity 200/422 по param_space ->
  CSV/JSON экспорт + /trace PNG -> инвалидация прогнозов тюнингом ->
  отдельный ETS-проход симуляции).

### Верификация

- compileall OK; app-import OK (FastAPI); rules-smoketest exit=0;
  pip check -- No broken requirements.
- Прод-инварианты: точка прогноза -- только MODEL_EXECUTION_REGISTRY;
  ensemble/non-eligible -- 422; fingerprint-гейт -- 409; прогнозы --
  артефакты сессии (Redis-roundtrip тест); инвалидация -- синхронно с
  картами во всех 4 точках; forecast_exported завершает этап.
- Фронтенд: jest 102/941; typecheck:all 0 ошибок; build:all успешно
  (обе оболочки, /forecasting в манифестах).

### Границы Task FORECAST-1 (что осознанно НЕ сделано)

- PDF-экспорт (§5.5) -- осознанно отложен: кириллические шрифты jsPDF
  (встраивание ~200+ КБ, лицензия шрифта) -- отдельная мелкая постановка.
- Прогноз ensemble-карт, multi-objective прогнозы (var/vecm/garch/egarch/
  deepar -- их карты недостижимы из comparison) -- отдельные постановки;
  честный 422 с объяснением.
- Exogenous-канал прогноза (future-known regressors в финальном прогнозе
  supervised/Prophet) -- вне среза: финальный рефит исполняет univariate
  target-путь; регрессорный канал -- отдельная постановка (прецедент
  lstm: supports_future_features декларируется своим срезом).
- Backend-персистентность панели «Прогресс» (research_runs/trace_events)
  -- владелец: команда «Прогресса» (§9.4); ForecastRun.trace_events уже
  совместим по формату (apps/api/trace_events.py -- общий контракт §10.4).
- StepperNextModuleButton «Перейти к Задачам» на вкладке НЕ добавлялся:
  прогнозирование -- workspace, а не степпер; естественное продолжение
  (хаб /tasks потребляет forecast_run) доступно из главного меню.
- Исторические записи журнала НЕ редактировались (append-only).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@30d00d4 + перечисленные изменения.

### Кандидат-находки (не блокирующие, к следующему касанию)

- spec_forecasting2.md §7 ForecastRun не содержит history; реализация
  хранит историю (labels/values/source_column) в артефакте -- CSV-экспорт
  и самодостаточность JSON (§5.5) становятся устойчивыми к смене сессии.
  При появлении формального клиента «Прогресса» вынести history в схему.
- Тюнинг-сетки частных моделей (neural @ max_steps 300) делают веер
  чувствительности по нейро-картам долгим на слабых инстансах (warning
  в ответе есть); если станет продуктивной болью -- вынести в job-контур
  (прецедент Task 104/123 start/step).

Изменённые/новые файлы (ZIP: download/task_forecast1_forecasting_module.zip):
- НОВЫЕ backend: apps/api/{trace_events,forecasting_contract,final_fit,
  forecasting}.py, apps/api/routers/forecasting_session.py,
  tests/unit/{test_forecasting_contract,test_final_fit,test_forecasting}.py,
  tests/api/test_forecasting_session.py,
  scripts/task_forecast1_interval_api_probe.py,
  scripts/task_forecast1_e2e_smoke.py
- НОВЫЕ frontend: packages/ui/lib/forecasting.ts,
  packages/ui/components/{ForecastChart,ForecastAccuracyPanel,
  ForecastHistoryList,ForecastExportMenu,TsAnalysisForecasting}.tsx,
  packages/ui/components/{ForecastChart,ForecastAccuracyPanel,
  ForecastHistoryList,TsAnalysisForecasting}.test.tsx,
  apps/standalone/app/forecasting/page.test.tsx
- ИЗМЕНЁННЫЕ: apps/api/main.py (роутер), apps/api/schemas.py
  (ForecastRunResponse и др.), apps/api/routers/modeling_session.py
  (GET /card список, _invalidate_forecasts в 4 точках очистки карт),
  packages/ui/index.ts (экспорты), apps/standalone/app/forecasting/page.tsx
  (ModulePlaceholder -> TsAnalysisForecasting), worklog5.md (этот журнал)

---

## Task MODEL-1 -- Вкладка «Моделирование»: приглашение «Перейти к прогнозированию» внизу степпера (паттерн цепочки)

- Дата: 2026-09-14. Синхронизация: main@0e06e9c (Task FORECAST-1 закоммичентимлидом; клон в fresh-контуре, дерево чистое, локальных правок нет).Постановка тимлида: реализовать кнопку внизу степпера вкладки«Моделирование» «Перейти к прогнозированию» по паттерну вкладки«Разведочный EDA» (Task EDA-1, коммит d9377ef). Полный цикл AGENTS.md:TDD RED->GREEN, полная frontend-регрессия, typecheck/build обеихоболочек.

- Диагностика (точки изменения)
Паттерн: общий компонент StepperNextModuleButton(packages/ui/components/StepperNextModuleButton.tsx) -- «Ведёмисследователя за руку». Цепочка уже покрыта на 4 из 5 степперов:Загрузка -> «Перейти к валидации» (/validation), Валидация ->«Перейти к предобработке» (/preprocessing), Предобработка ->«Перейти к EDA» (/eda), EDA -> «Перейти к моделированию»(/modeling). Порядок пайплайна подтверждён по ModuleNav.tsx:... Моделирование -> Прогнозирование (/forecasting).
Точка изменения: TsAnalysisModeling.tsx, левая колонка, контейнерстеппера «flex flex-col gap-1.5» (11 стадий пайплайна,PIPELINE_STAGES из lib/modeling.ts; последняя остановка -- «ModelCard»). Кнопка-приглашение ставится последним элементом спискастеппера (после dynamicStages.map), как в EDA (TsAnalysisEDA.tsx,Task EDA-1), Загрузке, Валидации и Предобработке.
Риск: доступное имя последней кнопки степпера = текст шага +aria-label svg-иконки статуса (StatusIcon, role="img") -- в тестематч по подстроке /Model Card/ (уникален среди role="button");неоднозначности getByRole нет (проверено RED-прогоном).
FORECAST-1 фиксировал «StepperNextModuleButton на вкладкеПрогнозирование НЕ добавлялся: прогнозирование -- workspace, а нестеппер». Настоящая задача этому не противоречит: кнопкадобавляется на СТЕППЕР Modeling, прогнозирование остаётсяworkspace без степпера.
TDD (RED -> GREEN)
- RED: 1 новый кейс в TsAnalysisModeling.test.tsx -- сюита«TsAnalysisModeling -- приглашение "Перейти к прогнозированию"»,зеркало теста Task EDA-1. Контракт прижат ПОЛНОСТЬЮ:(1) ссылка role="link" с доступным именем «Перейти кпрогнозированию» и href="/forecasting"; (2) позиция -- строго нижепоследней кнопки степпера (compareDocumentPosition +DOCUMENT_POSITION_FOLLOWING) и последний элемент списка степпера(stepperList.lastElementChild === wrapper); (3) светло-серая полосанад кнопкой -- border-t border-neutral-200 на обёртке; (4) стили --та же геометрия, что у кнопок степпера (rounded-md/border/px-3py-2/text-sm), статичная пастельная заливка bg-brand-light/50,hover-классы фирменного индиго и белого текста (hover:bg-brand /hover:border-brand / hover:text-white). Результат RED: падение наfindByRole("link") -- ссылки нет (кнопка /Model Card/ нашласьоднозначно, 48 остальных кейсов файла в скипе).
GREEN: импорт StepperNextModuleButton + JSX последним элементомсписка степпера TsAnalysisModeling.tsx -> файл 49/49 passed(48 базлайн + 1 новый -- арифметика сходится).

---

## Task FORECAST-1 certification (audit) -- независимый аудит модуля «Прогнозирование» (0e06e9c)

Дата: 2026-09-14. Синхронизация: main@30d00d4 -> 0e06e9c (Task FORECAST-1,
коллега; 3 коммита fast-forward: w/n-3, w/n-4, FORECAST-1). Постановка
тимлида: «проведи разведку кода и честно сертифицируй выполненную коллегой
задачу по проектированию и реализации модуля "Прогнозирование"; при аудите
используй мутационные и оракул-тесты на своих данных». Роль: независимый
аудитор-сертификатор (прецедент сертификаций Tasks 126-143): код модуля
НЕ изменялся, единственные новые файлы -- три аудит-скрипта; записи
append-only, коммит/пуш НЕ выполнялись (запрет AGENTS.md).

### Объём проверки

- Спецификация: spec_forecasting2.md v3 целиком (§1-§10), сверка деклараций
  с фактическим кодом: apps/api/{forecasting(529), final_fit(243),
  forecasting_contract(181), trace_events(66)}.py,
  routers/forecasting_session.py(624), schemas.py (ForecastRunResponse
  и др.), main.py (роутер /v1/session/modeling), modeling_session.py
  (GET /card список + _invalidate_forecasts в 4 точках очистки),
  фронтенд (TsAnalysisForecasting, ForecastChart/AccuracyPanel/
  HistoryList/ExportMenu, lib/forecasting.ts) -- статический обзор.
- Журналы: worklog_summary.md, worklog5.md (запись FORECAST-1 полностью).
- Восстановление контекста: записи прошлой сессии (синхронизация main@30d00d4,
  верификация прод-контура) не пережили переезд worklog5.md -> worklog/
  в коммите 0e06e9c -- восстановлены append-ом из локальной копии.

### Воспроизведение baseline коллеги

- tests/unit/{test_forecasting,test_forecasting_contract,test_final_fit}.py +
  tests/api/test_forecasting_session.py: 65/65 GREEN на statsmodels 0.15.0.
- E2E-смоук scripts/task_forecast1_e2e_smoke.py: 41/41 -- воспроизведено.
- Локальный контур (песочница): юнит 1550+ (после установки ruptures/syrupy),
  api 660, integration/top-level 100 -- все не-нейро тесты GREEN; 8 падений
  (5 юнит neural-path, 3 api neural-capacity) -- ТОЛЬКО отсутствие
  torch/neuralforecast в песочнице (fail-closed гейт зависимостей,
  корень подтверждён текстами ошибок; не регрессия FORECAST-1).
  Frontend jest НЕ перезапускался (node_modules в песочнице нет) --
  заявление коллеги 102 сюиты/941 теста + typecheck 0 + build OK
  не воспроизводилось независимо, отмечено как ограничение аудита.

### Оракул-тесты на СВОИХ данных аудитора (scripts/cert_forecast_oracles.py,
### cert_forecast_session_oracles.py -- DGPs не пересекаются с фикстурами коллеги)

- 18/18 core-оракулов PASS: O1-O4 точные точки baseline-моделей (naive/
  mean/drift/seasonal_naive на белом шуме, точной прямой, чистой синусоиде --
  равенства 1e-9); O5 containment для 3 методов; O6 монотонность ширины по
  alpha (3 метода); O6b симметрия симуляции на симметричном шуме
  (3000 траекторий); O7 MC-покрытие ~= 0.95; O8 асимметрия log_difference
  в исходной шкале -- Совпало с точной теорией (e^d-1)/(1-e^-d) до 6 знака
  ВКЛЮЧАЯ кумулятивную семантику restore на шаге k (d*k); O9 детерминизм
  seed; O10 разная строгость warning'ов analytic vs empirical; O11-O13
  аномалии/формула coverage/границы = точка+квантиль своего шага;
  O14 паритет-гейт ловит 1%-дрейф fake-реестра; O15 календарь ME/None;
  O16 углы param_space 2x1x2+потолок 8; O17 var/garch/deepar fail-closed.
- 7/7 session-оракулов PASS на собственном DGP (дневная сетка, колонки
  moment/load): O18 freshness 409; O19 CSV-структура (заголовок, история
  vs прогноз, согласованность с run); O20 JSON самодостаточен; O21
  жизненный цикл стадии in_progress->done; O22 трасса (generated ->
  exported x2, ISO-tz, payload); O23 инвалидация синхронна с картами;
  O24 compare 2..4/дубликаты/404.
- Примечание: 4 первичных FAIL были ошибками КАЛИБРОВКИ ожиданий самого
  аудитора (numpy linear quantile, кумулятивная инверсия, ME-сетка, шум MC
  при 500 траекториях) -- после выверки по теории 18/18; каждый случай
  усилил оценку корректности реализации, ни один не выявил дефект кода.

### Мутационные тесты (scripts/cert_forecast_mutations.py, 15 мутантов)

- Итог: 15/15 KILLED полным аудиторским слоем (тесты коллеги + оракулы).
- Убиты тестами коллеги: 11/15 (MUT-01,02,03,05,07,08,09,10,11,12,13).
- ORACLE-ONLY (тесты коллеги ПРОПУСТИЛИ, убито оракулами аудитора) -- 4:
  - MUT-04: паритет-гейт отключён -> не ловится ни одним тестом коллеги
    (есть только happy-path проверка metadata parity_gate=ok); убит O14.
  - MUT-06: нижний квантиль симуляции alpha/2 -> alpha (сужение интервала)
    -> энвелоп-тесты коллеги проверяют только lower<point<upper; убит O6b.
  - MUT-14: веер чувствительности только по первому углу каждой оси;
    убит O16 (точный состав углов 2x1x2).
  - MUT-15: forecast_exported не переводит stages["forecasting"]=done
    (§10.5) -> API-тест экспорта стадию не проверяет; убит O21.
- Kill-score тестов коллеги: 11/15 (73%); полный слой: 15/15 (100%).

### Находки сертификации

- F-1 (P1, ДЕФЕКТ КОНТРАКТА ЗАВИСИМОСТЕЙ, требует закрытия): путь
  parametric_simulation (ets/ets_damped) использует API statsmodels>=0.15
  (kwarg `rng=` + приём np.random.Generator), а requirements.txt и
  apps/api/requirements.txt декларируют пол `statsmodels>=0.14.0`. На
  0.14.5 (удовлетворяет декларации): 3 юнит + 15 API тестов RED, а в
  рантайме TypeError из simulate() НЕ перехватывается (except ловит
  ForecastingError/ValueError) -> 500 вместо честного 422. Корень: спека v3
  (§10.3) утверждала «0.15.0 закреплена в requirements.txt» -- фактически
  закреплена >=0.14.0; проб-скрипт коллеги версию зафиксировал, а сверку с
  requirements не сделал. Прод-проверка (2026-09-14, из песочницы): Render
  openapi -- 131 путь, 7 forecast-эндпоинтов; РЕАЛЬНЫЙ полный путь до
  ETS-прогноза на проде -- HTTP 200, ci_method=parametric_simulation,
  интервалы содержательные, warning о горизонте честный -> прод жив
  (статистически 0.15.x: rng работает). F-1 -- портабельность/контракт,
  не прод-инцидент. Рекомендация: поднять пол до statsmodels>=0.15.0
  (согласуется с сертификационной эпохой) ИЛИ compat-шим
  (try rng -> except TypeError -> random_state=int); первый вариант
  предпочтителен -- смена семантики ГСЧ между версиями делает
  воспроизводимость random_state кросс-версионно негарантированной.
- F-2 (P2, тест-гэп): отсутствие негативного теста §10.5 (MUT-15) --
  рекомендация коллеге: API-тест export обязан ассертить
  stages["forecasting"]=="done" (покрыто O21 аудитора).
- F-3 (P3, тест-гэпы): паритет-гейт без инъекции отказа (MUT-04);
  симуляционный квантиль без семантического оракула (MUT-06); углы веера
  без проверки полноты (MUT-14). Оракулы O14/O6b/O16 аудитора закрывают.
- F-4 (P3, наблюдение): дефолтные 500 траекторий симуляции дают шум
  квантиля до ~±8-10% на границу (SE выборочного квантиля) -- допустимо
  для MC-интервала; при повышении требований к воспроизводимости ширины --
  параметр уже выведен (simulation_trajectories).
- Не блокирующие кандидаты коллеги (history вне схемы ForecastRun;
  долгий веер по нейро-картам) -- подтверждены, остаются в силе.

### Вердикт сертификации

СЕРТИФИКАЦИЯ ПРОЙДЕНА С ЗАМЕЧАНИЯМИ. Реализация методологически корректна
и соответствует spec_forecasting2.md §1-§10 с задекларированными
уточнениями коллеги: все 25 оракулов на независимых DGPs точны (включая
точную асимметрию инверсии границ §3 -- совпадение с теорией до 6 знака),
15/15 мутантов убиты полным слоем, E2E 41/41 воспроизведён, прод-контур
функционален. Обязательное условие закрытия аудита: F-1 (правка пола
statsmodels в обоих requirements-файлах либо compat-шим + тест на
перехват TypeError -> 422) -- к следующему касанию модуля; F-2/F-3 --
рекомендации к тестовому долгу коллеги.

Изменённые/новые файлы (ZIP: download/task_forecast1_certification.zip):
- НОВЫЕ: scripts/cert_forecast_oracles.py (18 core-оракулов),
  scripts/cert_forecast_session_oracles.py (7 session-оракулов),
  scripts/cert_forecast_mutations.py (15 мутантов с атрибуцией убийства)
- ИЗМЕНЁННЫЕ: worklog/worklog5.md (этот журнал; + восстановленные записи
  прошлой сессии после переезда файла в worklog/)
- Код модуля Прогнозирование НЕ изменялся (роль аудитора)
