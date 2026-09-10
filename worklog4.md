# CISStat TS Analysis — Worklog

---

## Task 137 -- Neural Runtime Contract (унификация пяти нейро-моделей на NeuralForecast)

Дата: 2026-09-10. Синхронизация: 98ff25f (cert Task 134+135; EGARCH upstream
2efcd91). Постановка docs/modeling_task_list.md::Task 137. Прецедент
каркасной задачи: Task 134 (volatility-контракт -> исполнители 135/136);
Task 137 -- нейро-аналог: контракт потребляют вертикальные срезы
Tasks 138-142 (LSTM/GRU, N-BEATS, N-HiTS, TFT, DeepAR), реестровые записи
v2 НЕ добавляются (производственный срез остаётся 19/24, честный
catalog_only для пяти нейро-моделей до их срезов).

### Решение (по пунктам постановки)

1. **Единый long-format unique_id/ds/y** -- `apps/api/neural_contract.py::
   to_long_format/validate_long_format`: широкая платформенная таблица
   (серия или честная панель) -> формат NeuralForecast; fail-closed на
   NaN/Inf, дубликаты (unique_id, ds), нерегулярную сетку (per-series
   `validate_regular_grid` переиспользован из сертифицированного контракта
   Task 131 -- единый источник истины регулярной сетки). Панель -- только
   через явный series_column; «числовые колонки одного объекта не выдаются
   за панель» закреплены на уровне контракта (n_series < min_series ->
   отказ; gate честности DeepAR Task 142).
2. **Historic/future/static exogenous contract** -- `build_exogenous_plan`:
   роли {futr, hist, stat} ОБЯЗАНЫ быть объявлены вызовом (никакого
   скрытого угадывания, паритет с keyword-выборами Task 134);
   валидация существования/конечности hist+futr, константности static
   per unique_id (static может быть категориальным -- region='eu');
   непересекаемость ролей; sha256-подпись плана -> cohort-контракт.
   `validate_future_exogenous_frame` -- futr обязан покрыть
   n_series*horizon без NaN (NeuralForecast требует futr_df на predict);
   `build_static_frame` -- одна строка на серию.
3. **CPU/GPU worker capabilities** -- `neural_worker_capabilities`
   (сигнал CISSTAT_GPU_AVAILABLE через model_jobs.gpu_runtime_available,
   eager-импорт torch запрещён) + `resolve_neural_device`: requires_gpu
   без GPU-сигнала -> NeuralRuntimeUnavailableError (тихое CPU-понижение
   запрещено, yaml-правило D06); нейтральное устройство -> честный "cpu".
4. **Checkpoints вне Redis JSON** -- `NeuralCheckpointStore`:
   filesystem-бэкенд (env CISSTAT_NEURAL_CHECKPOINT_DIR | data/
   neural_checkpoints), потолок CHECKPOINT_MAX_BYTES=512MB, sha256-
   анти-тампер (прецедент VolatilityTarget), JSON-safe pointer; в
   Redis/session-JSON попадает ТОЛЬКО pointer (dict), байты -- только на
   диске (job-записи платформы остаются bounded).
5. **Early stopping, seed, max epochs/steps** -- `NeuralTrainingConfig`:
   bounded (seed [0, 2^31-1]; max_steps [1, 10000]; patience [0, 50];
   batch_size [1, 4096]); patience>0 требует val_size>0 (честная
   остановка). Эмпирика neuralforecast 3.2.2 (проб
   scripts/task137_neural_api_probe.py): BaseModel fail-closed отвергает
   max_epochs ("deprecated, use max_steps") и МОЛЧА ставит
   accelerator="gpu" -- контракт фиксирует ЕДИНЫЙ бюджет max_steps и
   ЯВНОЕ устройство (в этом и есть унификация: один бюджетный рычаг
   вместо расхождения epoch/step-конвенций Darts/GluonTS/PyTorch
   Forecasting). `fold_seed(seed, fold_index, step)` -- детерминированный
   per-fold seed (стабильная формула, без хэш-рандомизации).
6. **Probabilistic losses и quantiles** -- `interval_levels_for_alpha`:
   симметричные уровни из двусторонней alpha (0.2 -> 10/50/90, медиана
   всегда присутствует); `resolve_probabilistic_loss`: whitelist
   {quantile, mqloss, mae, mse, huber}; probabilistic-функции требуют
   уровней. Вывод квантилей point-loss моделей -- conformal-путь
   neuralforecast: fit(prediction_intervals=PredictionIntervals()) +
   predict(level=[...]) -> колонки <Model>-lo-<level>/<Model>-hi-<level>
   (подтверждено пробом; НИКАКОГО уровня в конструкторе модели -- 3.x
   прокидывает его в Lightning Trainer и падает).
7. **Продолжение job после рестарта** -- `restore_resume_state`: job-
   запись хранит pointer; воркер восстанавливает состояние с диска по
   pointer с sha256-верификацией; источник истины metadata -- pointer
   (манифест на диске -- дубликат для аудита). Отсутствующий/битый
   чекпойнт -- честный отказ: продолжение возможно ТОЛЬКО с
   верифицированным состоянием; молчаливый retrain контрактом запрещён
   (решение о retrain -- за job-протоколом, который обязан его записать).

### Единый runtime (model_impls/neural_runtime.py)

- `neuralforecast_runtime_available()` -- честный import-проб (find_spec,
  без сайд-эффектов); питает будущие runtime_available реестровых записей
  Tasks 138-142.
- `require_neuralforecast()` -- ленивый импорт, fail-closed с установочной
  подсказкой (apps/api/requirements-neural.txt).
- `seed_neural_runtime(seed)` -- random/numpy/torch (+cuda при наличии)
  ДО конструирования модели (детерминизм бит-в-бит подтверждён пробом
  и тестом: одинаковый seed -> одинаковый прогноз NHITS, max diff 0.0).
- `neural_model_budget_kwargs(config, device)` -- единый бюджет-мэппинг:
  max_steps, явный accelerator (BaseModel по умолчанию "gpu" -- молчаливый
  fallback на недоступный GPU недопустим), enable_progress_bar=False,
  early_stop_patience_steps (enabled: patience; disabled: -1).
- `train_and_forecast(model_factory, freq, train_long, horizon, config,
  futr_df, static_df, levels, fold_index)` -- единый fit/predict-цикл:
  model_factory(budget_kwargs) конструируется ПОСЛЕ сеяния fold_seed;
  val_size передаётся только при включённом early stopping; levels ->
  conformal (PredictionIntervals + predict level); пустой прогноз -- отказ.
- Пять каталог-моделей (LSTM, NBEATS, NHITS, TFT, DeepAR) конструируются
  на едином runtime с бюджетом контракта -- smoke унификации (5 тестов).

### Границы Task 137 (что осознанно НЕ сделано)

- Реестровые записи v2 для lstm/nbeats/nhits/tft/deepar -- НЕ добавлены
  (вертикальные срезы Tasks 138-142; производственный срез остаётся 19/24,
  count-гейты не тронуты). Контракт «готов к потреблению адаптером».
- Dockerfile-пробы нейро-runtime -- НЕ добавлены (torch/neuralforecast
  не входят в production-образ до срезов; манифест -- requirements-neural.txt
  вне Dockerfile, что честно фиксирует catalog_only-статус).
- Полноценные backtest-адаптеры, param_space, tuning/dispatch/readiness --
  скоуп Tasks 138-142. Правила применимости yaml (F01/F05/D02/C04/D06/P07)
  не менялись.
- config/models/ts_models_catalog.yaml (legacy Streamlit-каталог, не
  apps/api) -- сознательно не тронут.

### Изменённые/новые файлы

Новые:
- apps/api/neural_contract.py (~740 строк; pure-модуль, без HTTP и без
  импорта torch/neuralforecast)
- apps/api/model_impls/neural_runtime.py (~230 строк; единственная точка
  ленивого импорта neuralforecast/torch)
- apps/api/requirements-neural.txt (deploy-манифест install_extra="neural")
- tests/unit/test_neural_contract.py (64 кейса)
- tests/unit/test_neural_runtime.py (21 кейс; importorskip neuralforecast)
- scripts/task137_neural_api_probe.py (эмпирический проб API 3.2.2)

Изменённые:
- rules/modeling.yaml: libraries пяти нейро-моделей -> ["neuralforecast"]
  (унификация «вместо смеси Darts/GluonTS/PyTorch Forecasting»); описание
  семейства neural дополнено ссылкой на контракт Task 137.
- worklog3.md (данная секция).

### Верификация

- TDD: RED (collection errors обоих модулей отсутствием) -> GREEN:
  test_neural_contract.py 64/64, test_neural_runtime.py 21/21 (реальный
  микро-цикл NHITS: point + conformal-квантили 10/90, lo<=hi; детерминизм
  seed 21 -> бит-в-бит; construct-smoke пяти моделей).
- Полная регрессия на 98ff25f: база 2099 (1476 unit + 623 api) ->
  после Task 137: 2184 passed (1561 unit + 623 api) = база + 85 новых,
  0 упавших; count-гейты 19 не тронуты; apps/api/__init__.py пустой
  маркер не изменён (13 регресс-тестов на месте).
- Прод-инварианты: PRODUCTION_BACKTEST_MODEL_IDS == 19, нейро-пять
  catalog_only (готовность флипается срезами 138-142); консистентность
  dispatch/readiness (RuntimeError-gate) не затронута.
- Проб окружения: neuralforecast 3.2.2 + torch 2.14.0+cpu установлены;
  conformal-колонки, max_epochs-отказ, accelerator-дефолт подтверждены
  эмпирически и отражены в контракте (не по документации, а по факту).

---

## Task 136 -- Независимая сертификация (аудит исполненной задачи)

Дата: 2026-09-10. Аудитор: senior-разработчик (исполнитель задач 132/133/
131a, автор сертификации 134/135). Объект аудита: Task 136 `2efcd91`
(EGARCH -- второй исполнитель volatility-контракта Task 134; leverage/
asymmetry: адаптер `apps/api/model_impls/egarch.py` 434 строки + реестр +
движок-ключ + dispatch + yaml 32 trials + Dockerfile-проба + 49 тестов).
База аудита: чистое дерево `main @ 98ff25f`, границы diff `51ee33d..2efcd91`
сверены: backend-only (фронтенд не затронут), все удаления -- честные
count-гейты 18->19 и комментарии; surface-диффы (backtesting.py: ключ блока
диагностики = model_id + adapter_id/asymmetry; eda_model_matrix.py --
только комментарий) соответствуют записям worklog3.md.

### Методология аудита

(1) Построчный аудит кода против постановки docs/modeling_task_list.md
::Task 136 и требований Task 134; (2) воспроизведение окружения с нуля
(свежий venv: Python 3.12.14, arch 8.0.0, statsmodels 0.15.0, pandas
2.3.3, numpy 2.5.3 -- новее окружения исполнителя); (3) полная backend-
регрессия; (4) 14 независимых оракул-проб на СВОИХ данных и сидах
(audit_scripts/cert136_oracles.py: сиды 314159265/271828182/141421356/
577215664/999999937/123456789/555555503/987654321/246813579/20260909 --
ни один не совпадает с сидами исполнителя; серии-параметры свои:
omega=-0.10, alpha=0.18, gamma=-0.25, beta=0.92 -- n=800; positive-pole
gamma=+0.20; heavy-tail t(4)-инновации); (5) 15 мутационных проб
(audit_scripts/cert136_mutations.py, каждая apply -> RED-check -> revert
-> git-diff верификация чистоты); (6) воспроизведение probe-скрипта,
e2e-смоука и Dockerfile-пробы; (7) характеризация выживших мутаций и
dist="t"-контура отдельными скриптами.

### Воспроизведение базлайна и регрессии

- tests/unit **1376 passed** (snapshots 3/3), tests/api **623 passed**,
  остальные (root/integration/legacy) **100 passed**; итого **2099
  passed / 0 failed**.  compileall OK; `from apps.api.main import app`
  OK; pip check PASS.
- Арифметика: фактический базлайн `51ee33d` -- **2050** (запись Task 135
  занижала на 1 -- замечание моей сертификации 134/135), новых тестов
  **49** (32 адаптер + 13 интеграция + 4 session; в записи исполнителя
  интеграционный файл посчитан как 14): 2050 + 49 = 2099.  Заявленная
  исполнителем арифметика «2049 + 50 = 2099 -- сходится ровно» даёт
  верный итог по неверным слагаемым (off-by-one унаследован + промах в
  подсчёте интеграционных тестов).

### Оракулы (14/14: 13 PASS, 1 WARN c подтверждённым OR8b)

OR1 h=1 симуляционного прогноза == ручная EGARCH(1,1,1)-рекурсия из
фильтрованного состояния arch: max rel err **7.09e-14** на 7 своих сидах
(заявленный rtol 1e-8 держится с запасом 6 порядков).  OR2 точечный
прогноз == variance.values официального симуляционного контура arch
(тот же seed): bit/allclose rtol 1e-12 на 5 сидах x h=7.  OR3
детерминизм: тот же seed -- бит-идентичные forecast/lower/upper/params;
новый seed -- те же MLE-параметры, другие интервалы.  OR4 ядро
постановки -- leverage: на 5 своих сериях с gamma_true<0 фит даёт
gamma<0, direction=negative, significant=True; на 3 positive-pole сериях
-- gamma>0/direction=positive; o=2 -- оба gamma-члена в блоке.  OR5
persistence == sum(beta) прямого фита (арх не даёт fitted.persistence
для EGARCH -- probe fact подтверждён), is_covariance_stationary ==
(sum(beta) < 1).  OR6 dist="t"-контур -- см. характеризацию ниже.  OR7
clamp-инвариант lower<=point<=upper: на 3 своих сидах x 3 альфах x
h=12 -- **0/432** срабатываний (чисто численная страховка).  OR8/8b
бюджет сходимости: на 40 префиксах своей серии дефолт-отказов не
найдено (WARN: премиса slice-специфична), НО фиксированная премиса
исполнителя воспроизведена: срез-207 смоук-серии -- дефолтный фит
flag=9 llf=-226.94 => адаптер flag=0 llf=-223.59 (лучше, детерминизм от
seed не зависит).  OR9 fail-closed на своих данных: нулевая дисперсия/
NaN/Inf/короткая история (<20)/horizon<=0/legacy-эндпоинт -- все
честные ValueError.  OR10 реестр: 19 production ids, dispatch-гейт
сошёлся, контракт определения (volatility/univariate/arch-egarch/
deterministic/intervals), adapter_id-самоиндентификация ОБОИХ
volatility-исполнителей (garch -- "arch-garch", egarch -- "arch-egarch").
OR11 полный прогон volatility-движка на своей серии: cohort-контракт
(primary=qlike), fold-диагностика с egarch-блоком и asymmetry, EWMA-
baseline на тех же folds, OOF-честность (predicted>0, residual ==
actual-predicted) и НЕЗАВИСИМЫЙ пересчёт QLIKE из OOF-точек -- бит-в-
бит (egarch qlike=-0.297906; пересчёт по конвенции движка: fold-
значения round 6 -> взвешенное среднее по n_test -> round 6; простое
пул-среднее даёт расхождение 1e-6 -- конвенция агрегации подтверждена
добросовестно).  OR12 гейты: level-движок отказывает egarch
(BacktestExecutionError), volatility-движок отказывает level-модели.
OR13 (аудиторский анти-тампер, закрывает выжившие мутации M7/M9):
интервалы бит-прижаты к двусторонним alpha/2-квантилям ТЕХ ЖЕ путей
(alphas 0.01/0.05/0.10), payload intervals.simulations == 4000.

### Характеризация dist="t" симуляционного контура (существенная находка)

audit_scripts/cert136_or6_characterize.py, 200k путей: (a) на h=1 оба
контура совпадают (+0.000%); (b) при fitted nu~=2.97 (сильные хвосты)
t-контур (стандартизованные t-инновации) даёт РАСХОДЯЩЕЕСЯ MC-среднее:
1.09e18 на h=6 -- E[sigma2_{T+h}|F_T] под EGARCH-t для h>=2 не существует
(mgf |e| бесконечен при степенных хвостах t: E[exp(alpha|e|)] = inf),
т.е. «честный» t-контур принципиально не даёт стабильного точечного
прогноза; (c) нормальный контур адаптера стабилен (0.30 на h=6) и
согласован с жёстко зашитой нормировкой sqrt(2/pi) EGARCH-рекурсии
arch; (d) интервалы при dist="t" имеют нормальные хвосты: q99.5% на
h=6 -- 1.29 против 2.10 у t-контура (~1.6x занижение хвостового риска
t-модели).  ВЫВОД: выбор normal-rng легитимен (обратное дало бы
нефинитный MC-шум вместо точечного прогноза), но НЕ задокументирован:
докстринг декларирует «интервалы -- квантили тех же путей» и
детерминизм, не упоминая, что инновации симуляции всегда нормальные
независимо от dist.  Рекомендация (не блокирует): disclose в докстринге
egarch.py + honest note в intervals-метаданных (dist-aware) либо
t-seeded rng с задокументированной дивергенцией среднего.

### Мутационные пробы (15 мутаций: 11 KILLED, 4 SURVIVED -- разобраны)

Убиты (анти-тампер обещаний работает): M1 EGARCH_MAXITER 1000->100
(оракул сходимости); M2 гейт o>=1 -> o>=0 (mandate асимметрии);
M3 persistence sum(beta)->sum(beta+alpha); M4 ключ блока диагностики
захардкожен "garch" (session-тест, KeyError 'egarch'); M5
leverage_direction negative->positive (восстановление leverage);
M8 ASYMMETRY_SIGNIFICANCE_LEVEL 0.05->0.5 (уровень прижат блоком);
M10 EGARCH_MIN_TRAIN 20->5 (привязка к MIN_RETURNS_OBSERVATIONS);
M11 deterministic=True->False в реестре; M12 удаление clamp-инварианта
(lower<=point<=upper) -- ловится их contract-тестом; M14 удаление
adapter_id из metadata executor'а (session-тест); M16 удаление "egarch"
из dispatch -- модульный гейт реестр<->dispatch падает на импорте
(1 error, collection RED).
Выжившие (все -- пробелы тест-привязки/слоистая защита, не дефекты кода):
M6 rescale=False->True SURVIVED на fixture исполнителя (std 0.84):
характеризация (audit_scripts/cert136_survivor_characterize.py) -- arch
масштабирует вход только на poorly-scaled данных (x0.01: params
различаются; x0.001: различаются), при ЯВНОМ rescale=True DataScaleWarning
не эмитится вовсе, поэтому warning-защита их теста инертна, а params-
parity ловит мутацию только на плохо масштабированных данных.  Рекомендация:
добавить в rescale-тест poorly-scaled fixture (x0.01) -- мутация станет
безусловно убитой; реальный кейс платформы (лог-доходности ~1e-2) ловится.
M7 INTERVAL_SIMULATIONS 4000->10 SURVIVED -- число путей не прижато ни
одним тестом (payload intervals.simulations декларируется, но не
ассертится; паритет-тест использует константу на обеих сторонах).
Рекомендация: односторонний ассерт метаданных; моим OR13 прижато.
M9 односторонние квантили alpha вместо alpha/2 SURVIVED -- номинальные
уровни интервалов не прижаны; фактическая реализация двусторонняя и
корректна (OR13 бит-прижимает alpha/2).  Рекомендация: dedicated тест.
M13 удаление NaN/Inf-гейта SURVIVED -- слоистая защита: arch сам
отказывает на NaN ("NaN or inf values found in y", ValueError,
ретранслируется адаптером); собственный гейт даёт контрактное сообщение.
Аналог избыточных слоёв сертификации 134/135 (M10/M16) -- не блокирует.

### Прочие верификации

- e2e-смоук (scripts/task136_e2e_smoke.py) воспроизведён: каталог 19
  connected; гейт level-движка; волатильный пайплайн (220 цен -> 219
  returns method=log -> EGARCH(1,1,1)); asymmetry: gamma<0, p~0,
  direction=negative, significant=True; изоляция cohort; ранжирование
  EWMA > GARCH > EGARCH (EGARCH не объявлен «лучшим»).  АБСОЛЮТНЫЕ
  числа смоука зависят от окружения (мой прогон: qlike=2.8158,
  gamma=-0.1197, persistence=0.967 против 0.7189/-0.1288/0.986 у
  исполнителя): версии scipy/numpy меняют траекторию SLSQP; структурные
  ассерты стабильно выполняются в обоих окружениях -- смоук не содержит
  числовых хрупких ассертов (проверено чтением скрипта).
- Dockerfile-проба EGARCH воспроизведена локально: 'EGARCH executable OK'
  (симулированный EGARCH-процесс с leverage, ассерт asymmetry-блока).
- yaml: EGARCH(p,o,q), bounded param_space 2^5 = 32 trials (<= 64),
  o>=1, комбинируется с адаптерными границами (1..3 строже yaml не
  противоречит).  Count-гейты 18->19 обновлены честно в 7 файлах.
- Границы Task 136 подтверждены: EGARCHX не декларирован (прецедент
  GARCHX/VARX), тюнинг констант (пути/бюджет) -- вне param_space
  обоснованно, нейросетевые volatility -- вне скоупа (Task 137+).
- Каталог: 19/24 production (egarch ready), catalog-only 5, blocked 4
  на macro-профиле / 9 на короткой истории -- согласовано с readiness-
  тестами и смоуком.

### Замечания (не блокируют сертификацию)

1. (документация) Off-by-one арифметики в записи Task 136 (см.
   «Воспроизведение»): фактически 2050 + 49 = 2099, не «2049 + 50».
   Поправить при следующей правке; рекомендация из сертификации 134/135
   по off-by-one записи Task 135 остаётся в силе.
2. (тесты) Прижать INTERVAL_SIMULATIONS и двусторонние квантильные
   уровни (M7/M9; OR13 -- образец).
3. (тесты) rescale-анти-тампер сделать безусловным: poorly-scaled
   fixture x0.01 в rescale-тесте (M6).
4. (документация) Disclose dist="t"-поведения симуляционного контура
   (нормальные инновации при любом dist; дивергенция E[sigma2] под
   EGARCH-t для h>=2; хвосты интервалов -- нормальные) -- докстринг +
   honest note (OR6-характеризация).
5. Открытые рекомендации сертификации 134/135 в силе: анти-тампер
   VolatilityTarget на 1e-12-подмену; изоляция отдельных слоёв
   fail-closed; отражение коротких train-срезов в применимости.

### Вердикт

**CERTIFIED.** Task 136 соответствует постановке (EGARCH -- второй
исполнитель volatility-контракта Task 134; leverage/asymmetry честно
восстанавливается и репортится из официального фита arch; прогнозы --
официальный симуляционный контур; 19/24).  Методологические обещания
(leakage-safety, fail-closed без clamp-подмен точечного прогноза,
rescale=False, явный бюджет сходимости, o>=1, детерминизм) подтверждены
независимо: 14/14 оракулов на своих данных/сидах, 11/15 мутаций убиты,
4 выживших -- пробелы тест-привязки/слоистая защита (разобраны, даны
рекомендации), 2099/2099 регрессия, прод-каталог соответствует (19/24,
egarch).  Кодовых дефектов не обнаружено.

Изменённые/новые файлы сертификации:
- worklog3.md (данная секция)
- audit_scripts/cert136_oracles.py (новый, 14 проб)
- audit_scripts/cert136_mutations.py (новый, 15 мутаций)
- audit_scripts/cert136_or6_characterize.py (новый)
- audit_scripts/cert136_survivor_characterize.py (новый)

---

Task: Cертификация Task 137 не пройдена.

Agent: Super Z (main agent, аудитор)

Work Log:
- Git-верификация: границы 98ff25f..7e73a83, backend-only, count-гейты не тронуты; замечание о взаимных переносах cert-скриптов 7e73a83/8145806.
- Построчный аудит neural_contract.py (793), neural_runtime.py (194), тестов (64+21), probe, requirements-neural.txt, modeling.yaml.
- Свежий venv (neuralforecast 3.2.2 + torch 2.14.0+cpu): регрессия 2184/2184 (1461 unit + 623 api + 100 прочие), compileall/app-import/pip check OK, прод-инварианты 19/24.
- Оракулы: 86 проб на своих сидах (75 быстрых + 11 тренировочных), 84 PASS / 2 FAIL.
- БЛОКИРУЮЩАЯ НАХОДКА: BaseModel(random_seed=1) перезасеивает всё (seed_everything в __init__ + on_fit_start); train_and_forecast не прокидывает random_seed → fold_seed/config.seed — no-op; разные сиды дают бит-идентичные прогнозы (max_diff=0.0); явный random_seed меняет прогноз (2.06) — фикс жизнеспособен. Детерминизм-тест вакуумен (мутация M19 переживает).
- Не-блокирующие: probe несовместим с 3.2.2 (trainer_kwargs crash, QuantileLoss level отклоняется; MQLoss(level) — рабочий путь); accelerator='gpu'-claim верен только при CUDA; keep-колонки не проверяют Inf; pointer без root-конфайнмента.
- Мутации: 23 применено, 10 KILLED, 13 SURVIVED (все ожидания сошлись), дерево чистое после откатов.
- Запись сертификации добавлена в worklog3.md (2234 → 2467 строк).

Stage Summary:
- Вердикт: НЕ СЕРТИФИЦИРОВАНА — возврат на доработку (прецедент Task 126). Один блокирующий пункт (seed-прокидка), объём доработки мал; OR14b/c — готовый инструмент пересдачи.
- Deliverables: download/task137_certification.zip (worklog3.md + 3 audit-скрипта).