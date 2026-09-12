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
