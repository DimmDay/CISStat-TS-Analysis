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
