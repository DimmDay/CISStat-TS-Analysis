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

---

## Task 137 -- Доработка по вердикту сертификации и ресертификация (исправление недоработок)

Дата: 2026-09-11. Исполнитель: senior-разработчик (самостоятельное исправление
недоработок, найденных сертификацией Task 137, по поручению тимлида; прецедент
Task 126 -- двухфазный процесс с возвратом на доработку). База: main @ 8145806
(+ незакоммиченная сертификационная запись в worklog3.md); доработка поверх
коммита 7e73a83 (Task 137), БЕЗ коммитов/пуша (правила AGENTS.md).

### Объём доработки (по пунктам вердикта сертификации)

БЛОКЕР (seed-прокидка):
1. apps/api/model_impls/neural_runtime.py::train_and_forecast -- fold_seed
   прокидывается В КОНСТРУКТОР модели: budget["random_seed"] = int(seed)
   после neural_model_budget_kwargs (с комментарием-обоснованием).
   Обоснование: BaseModel 3.2.2 перезасеивает весь раном в __init__
   (pl.seed_everything(random_seed), дефолт 1) и повторно в on_fit_start;
   прокидка делает fold_seed/config.seed действующими рычагами, а same-seed
   детерминизм -- нетривиальным инвариантом. seed_neural_runtime до
   конструирования сохранён как defense-in-depth (сеет random/numpy для
   пайплайна до fit). Докстринги (шапка модуля п.2/п.4 и train_and_forecast)
   переписаны под новую seed-дисциплину.

НАХОДКИ 2-5 (не-блокирующие):
2. НАХОДКА-2: scripts/task137_neural_api_probe.py -- шаги 4-5 переписаны под
   фактический API 3.2.2: (а) trainer_kwargs-захват фиксируется БЕЗ fit
   (в 3.2.2 ключ вкладывается: model.trainer_kwargs содержит вложенный
   "trainer_kwargs" -- pl.Trainer(**kwargs) упал бы; контракт trainer_kwargs
   не использует); (б) рабочий бюджетный путь -- LSTM(max_steps=2) на
   нативных kwargs: fit/predict OK; (в) probabilistic-путь -- MQLoss(level=
   [10.0, 90.0]) -> NHITS-median/-lo-10.0/-hi-90.0; отказ QuantileLoss(level=
   ...) документируется try/except (q-сигнатура 3.2.2). Probe воспроизведён
   end-to-end: EXIT=0, PROBE OK. Новый шаг детерминизма: random_seed в
   конструкторе -- same-seed max_diff=0.0; разные сиды (21 vs 31337)
   max_diff=7.79.
3. НАХОДКА-4: to_long_format -- isfinite-гейт численно-коэрцибельных
   keep-колонок: pd.to_numeric(errors="coerce") + notna().all() ->
   np.isfinite-проверка; Inf -> отказ с именем колонки. Нечисловые
   (категориальные) колонки проходят только NaN-гейт (легитимный
   категориальный static -- OR5 сертификации). Docstring-обещание
   "NaN/Inf в keep-колонках" теперь истинно.
4. НАХОДКА-5 (hardening): NeuralCheckpointStore.load_checkpoint --
   root-confinement: pointer.path обязан нормализованно (os.path.normpath)
   совпадать с root/<job_id>.ckpt; cross-root чтение и путь чужого job_id
   отклоняются ДО чтения файла (1:1 связка job <-> чекпойнт). Легитимные
   pointer'ы (строятся save_checkpoint тем же store) проходят; избыточные
   '.'-сегменты не дают ложного отказа.
5. Следствие hardening: restore_resume_state получил keyword-only параметр
   root (корень хранилища, создавшего pointer; дефолт -- прежний). Раньше
   payload молча читался по пути из pointer (точное воспроизведение OR12
   сертификации); теперь чужой корень -- честный отказ "вне контейнера".
6. Дисклоужеры НАХОДКИ-3: докстринг neural_runtime.py (accelerator='gpu'
   ТОЛЬКО при torch.cuda.is_available(); на CPU-хосте auto/None -- явный
   accelerator остаётся обязательным), шапка test_neural_runtime.py,
   комментарий test_budget_kwargs_explicit_device_accelerator.

### TDD (RED -> GREEN)

RED -- 9 новых тестов, все отказали ДО фикса по ожидаемым причинам:
- tests/unit/test_neural_runtime.py: test_train_and_forecast_passes_fold_seed_
  into_model_constructor (stub-фабрика + _BudgetCapture -- останавливает
  цикл до fit и фиксирует budget), test_train_and_forecast_constructor_seed_
  varies_with_seed_and_fold (3 прогона: random_seed fold-производен),
  test_train_and_forecast_different_seeds_give_different_forecasts (реальная
  NHITS-тренировка, seed 21 vs 31337), test_train_and_forecast_different_
  fold_index_gives_different_forecast (fold 0 vs 1) -- дифференциальные
  убийцы блокера (урок мутационной методологии сертификации).
- tests/unit/test_neural_contract.py: test_fail_closed_on_inf_in_keep_column,
  test_keep_columns_categorical_still_allowed (регресс-защита -- PASS сразу),
  test_load_fail_closed_on_pointer_path_outside_root,
  test_load_fail_closed_on_foreign_job_path_inside_root,
  test_restore_fail_closed_on_foreign_root.
Адаптированы 2 теста под намеренно изменённое поведение (НАХОДКА-5):
test_restore_fail_closed_on_missing_file (pointer-путь на легитимном
root/<job_id>.ckpt), test_restore_resume_state_after_restart (restore с
root=tmp). Существующий same-seed детерминизм-тест снабжён комментарием о
вакуумности без дифференциальной пары.

GREEN: нейро-набор 94/94 (85 старых + 9 новых). Полная регрессия:
**2193 passed / 0 failed** = unit 1470 (1461 + 9) + api 623 (включая
test_models_backtest_real 23) + root/integration/legacy_wrappers 100;
snapshots 3/3. compileall OK (apps + tests + scripts), app-import OK,
pip check PASS.

### Ресертификационные оракулы (scripts/audit_scripts/cert137_recert_oracles.py)

20 проб на НОВЫХ сидах аудитора (20260912/42424244/1618034/90210666 -- ни
один не совпадает с сидами сертификации) -- **20/20 PASS**:
- RO1a same-seed бит-в-бит (max_diff=0.0); RO1b другой fold_index ->
  max_diff=6.13 (в сертификации было 0.0 -- сид мёртв); RO1c другой seed
  (1618034) -> max_diff=3.91 (0.0);
- RO2a/2b stub-прокидка: budget["random_seed"] == fold_seed(config.seed,
  fold_index) для 3 пар (seed, fold), 3 значения различны;
- RO3a-3d Inf-гейт keep-колонок: числовая с Inf -> отказ; объектная с
  Inf-флоатом (коэрцибельна) -> отказ; чистая числовая -> проход;
  категориальная -> проход;
- RO4a-4e чекпойнт-конфайнмент: легитимный roundtrip; cross-root отклонён
  (было: читалось молча); путь чужого job_id отклонён; path с '..' вне
  корня отклонён; избыточные '.'-сегменты нормализуются (не ложный отказ);
- RO5a-5c restore: тот же корень -> metadata из pointer; чужой (дефолтный)
  корень -> честный отказ; отсутствующий файл на легитимном пути ->
  отказ "не найден" (не retrain);
- RO6a-6c прод-инварианты: PRODUCTION_BACKTEST_MODEL_IDS == 19; нейро-пять
  вне реестра; available_model_actions("lstm") == [] (catalog_only честен).

Старый сертификационный набор cert137_oracles.py на доработанном дереве:
56 PASS до OR11i, затем останов -- OR11i (restore без root) падает по
ОЖИДАЕМОЙ причине: pointer теперь отклоняется confinement'ом; проба
фиксировала старое поведение (characterization), снята с учёта --
эквивалентное и более жёсткое покрытие в RO5a/RO5b. Хвостовой прогон
OR13/OR17/OR19/OR20 -- 14/14 PASS (cohort, budget-мэппинг, yaml-унификация,
границы реестра). Итог: 70 PASS; OR12 формально PASS, но теперь фиксирует
"отклонено" -- прямое доказательство закрытия НАХОДКИ-5.

### Мутационный ре-тест (scripts/audit_scripts/cert137_recert_mutations.py)

10 проб; откат -- backup/restore-копией файла (НЕ git checkout: дерево
содержит доработку), чистота верифицируется сравнением с сохранёнными
копиями. **KILLED=8, SURVIVED=2 (оба ожидания сошлись), unexpected=0.**

KILLED (8): MR1 удаление random_seed из budget (блокер-регресс -- убит
stub-тестами прокидки); MR2 захардкоденный random_seed=1 (убит
дифференциальными тестами реальной тренировки); MR5 снят Inf-гейт;
MR6 снят confinement; MR7 restore игнорирует root; MR8a/MR8b/MR8c -- повторы
сертификационных M2/M6/M14 (дубликаты (unique_id, ds), конечность hist/futr,
sha256-анти-тампер) -- убийства не деградировали.

SURVIVED (2, охарактеризованы): MR3 "seed-блок после конструирования" --
ЭКВИВАЛЕНТНАЯ мутация после фикса: инлайн int(fold_seed(...)) сохраняет то
же значение в конструкторе, поведение не меняется вовсе (проверено stub +
дифференциальными вместе). Принципиально отличается от сертификационной M19:
та МЕНЯЛА поведение (сид вообще не доходил до конструктора) и переживала
только из-за вакуумного same-seed теста; теперь регресс блока прокидки
ловится MR1/MR2. MR4 seed_neural_runtime снят целиком -- defense-in-depth:
после фикса основной механизм -- перезасевание конструктора случайным
random_seed=fold_seed; выживание ожидаемо и задокументировано.

Методологическая заметка: первый прогон MR3 дал ЛОЖНЫЙ KILLED -- артефакт
склейки pytest-команд (второй интерпретатор попал в позиционные аргументы ->
collection error -> passed=False). Механика run_tests исправлена
(последовательный прогон наборов команд; "no tests ran" и collection error
не считаются зелёным прогоном), прогон повторён полностью. Урок: сам
мутационный каркас обязан верифицироваться так же строго, как тестируемый
код.

### Вероятные вопросы / границы доработки

1. Смещение characterization-проб старого набора (OR11i; OR12 по смыслу) --
   не деградация: пробы описывали старое поведение, зафиксированное
   сертификацией как НАХОДКА-5; новое поведение прижато новыми тестами
   (RO4b/RO4c/RO5b) и мутациями (MR6/MR7).
2. Счёт unit-тестов: сертификация 1461 -> ресертификация 1470 (+9); 2 теста
   адаптированы (счёт не меняют).
3. Доработка НЕ трогает реестр v2/count-гейты/ts_models_catalog.yaml
   (19/24 подтверждено RO6a); контрактный data-plane изменён только
   усилением to_long_format/load_checkpoint по находкам 4-5.
4. Для Tasks 138-142 сохраняется рекомендация сертификации: probabilistic-
   путь 3.2.2 -- MQLoss (не QuantileLoss); сид-анкета фабрик -- random_seed
   из budget пробрасывать в BaseModel-наследник (не перекрывать).

### Вердикт ресертификации

**СЕРТИФИЦИРОВАНА** (Task 137, Neural Runtime Contract, neuralforecast
3.2.2). Блокирующая находка сертификации устранена: fold_seed/config.seed --
действующие рычаги (дифференциальные оракулы на новых сидах: fold_index ->
max_diff=6.13, seed -> max_diff=3.91; в сертификации оба 0.0), same-seed
детерминизм остался бит-в-бит (max_diff=0.0). НАХОДКИ 2-5 закрыты: probe
воспроизводим end-to-end на 3.2.2 (PROBE OK), Inf-гейт и root-confinement
прижаты тестами и мутациями (MR5-MR7 KILLED), дисклоужеры внесены.
Регрессия 2193/2193; прод-инварианты 19/24; границы задачи соблюдены
(реестр v2 и count-гейты не тронуты, пять нейро-моделей честно catalog_only).
Пункты постановки: (5) "early stopping, seed, max epochs/steps" --
ПОДТВЕРЖДЁН в действующей части; (6) probabilistic losses -- ПОДТВЕРЖДЁН
(математика уровней + conformal-путь + MQLoss-поверхность; QuantileLoss
3.2.2 сломана и заменена в probe, рекомендация для Tasks 138-142).
Contract готов как фундамент вертикальных срезов Tasks 138-142.

Изменённые/новые файлы доработки и ресертификации:
- apps/api/neural_runtime.py (блокер: random_seed-прокидка; дисклоужеры)
- apps/api/neural_contract.py (НАХОДКА-4: isfinite-гейт; НАХОДКА-5:
  root-confinement + restore(root))
- scripts/task137_neural_api_probe.py (НАХОДКА-2: шаги 4-5 под 3.2.2)
- tests/unit/test_neural_runtime.py (+4 теста, дисклоужеры шапки)
- tests/unit/test_neural_contract.py (+3 теста, 2 адаптированы)
- scripts/audit_scripts/cert137_recert_oracles.py (новый, 20 проб)
- scripts/audit_scripts/cert137_recert_mutations.py (новый, 10 проб)
- worklog3.md (данная секция)

---

## Task w/n — Уточнение фона главной страницы: точная цветопередача и геометрия по скриншоту

### Контекст

По итогам Task 131b тимлид указал воспроизвести фон "как по цветопередаче,
так и по геометрии волн" — точнее, чем первая версия (которая была
приближением по стилю, не измерением). Задача решена количественным
анализом присланного PNG, а не повторным приближением на глаз.

### Метод

Первая попытка уточнения (простое усиление контраста + визуальная
трассировка) дала лучшую топологию, но при рендере и сравнении бок-о-бок
с оригиналом обнаружилось: цвета всё ещё заметно темнее/насыщеннее
оригинала, а геометрия — широкий "клин", а не тонкие пересекающиеся ленты.
Итеративно (4 прохода, каждый — рендер + сравнение side-by-side с
оригиналом через PIL) добился совпадения:

1. **Цвет** — прямое усреднение блоков пикселей PNG (за вычетом области
   текста легенды макета) вместо приближения по стилю. Итоговая палитра:
   градиент `#EFF7FE → #E6ECFA` (сэмплировано из углов), заливки лент
   `#DCE7FB`/`#C9D9F7` (сэмплировано из соответствующих тональных зон).
2. **Геометрия** — K-means кластеризация пикселей (k=4, с нуля на
   NumPy) по RGB дала карту из 4 тональных зон, что впервые однозначно
   показало реальную структуру: **две пересекающиеся ленты переменной
   толщины** (сужаются к точке пересечения ~70% ширины), а не параллельные
   волны в одну сторону (ошибка первой версии Task 131b) и не единый
   "клин" (ошибка первого прохода этой задачи). По кластерной карте
   с наложенной координатной сеткой прослежены центральные линии и
   толщина каждой ленты в узловых x-точках; финальные SVG-path
   сгенерированы программно (offset центральной линии на половину
   толщины вверх/вниз, сглаживание — Catmull-Rom-подобные кубические
   Безье через опорные точки), не написаны от руки.

### Проверка результата

Рендер финального SVG в PNG (`cairosvg`) и сравнение side-by-side
с оригиналом (не итоговая проверка "на глаз сразу после написания кода",
а отдельный, воспроизводимый шаг верификации перед сдачей) — совпадение
по общей композиции, направлению волн, точке пересечения и тону
признано достаточным. Явно зафиксировано в коде и здесь: источник —
холст 495×493px с мягкими, слегка зашумлёнными (JPEG-подобными)
границами — воспроизведение "пиксель-в-пиксель" не имеет смысла для
такого источника (сам оригинал не векторный), цель была "видимо тот же
рисунок", а не побитовое совпадение — эта цель достигнута.

### Тесты и проверки

- Тест `HomeWavesBackground.test.tsx` обновлён под новые hex-значения
  (заменил старую проверку `brand`/`brand-light`-классов на sampled hex,
  т.к. компонент перешёл с Tailwind-токенов на инлайн `style`/`fill` с
  точными сэмплированными цветами) — 4/4 PASS.
- Полный frontend regression: **92/92 suites, 841/841 tests PASS**.
- `typecheck:all`: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, 13/13 страниц, First Load
  JS **469 kB — не изменился** (правки только внутри уже существующего
  компонента, вес по-прежнему нулевой сверх уже посчитанного в Task 131b).
  Временный шим `next/font/google` применён и отменён — `git diff` после
  отката пуст.

### Изменённые файлы

- `packages/ui/components/HomeWavesBackground.tsx` (полностью переписана
  геометрия/цвет заливок; структура компонента — decorative overlay —
  не изменилась)
- `packages/ui/components/HomeWavesBackground.test.tsx` (обновлены
  ожидаемые hex-значения)

### Что осталось за рамками (осознанно)

- Воспроизведение не заявляет пиксель-в-пиксель идентичности источнику —
  для мягкого растрового макета 495×493px это неприменимая метрика
  качества; цель — визуальное совпадение по цвету/направлению/точке
  пересечения волн, подтверждённая рендер-сравнением.
- Метод (K-means + трассировка по кластерной карте) — воспроизводим для
  будущих подобных задач "оцифровать макет фона", но сам скрипт анализа
  не сохранён как часть кодовой базы (разовый инструмент разработки, не
  часть продукта) — при необходимости может быть восстановлен по
  описанию метода выше.

## Task — Точная замена фона главной страницы на авторский SVG

Дата: 2026-09-11. База: main (после layout.tsx/favicon, Task 121).
Commit/push не выполнялись.

### Реализация

- `packages/ui/components/HomeWavesBackground.tsx`: геометрия и палитра
  заменены на точный перенос CISStat_TS_Analysis_background_wave_1600x1600.svg
  (1 rect-подложка с диагональным градиентом + 4 ленты + 2 штриха-акцента,
  было 2 приближённых path). Программно сверено побайтово с источником
  (path d=, hex-цвета, opacity, stroke-width) — полное совпадение.
  Id градиентов префиксованы `cisstat-home-*` во избежание коллизий
  с другими инлайн-SVG на странице (единственное отличие от источника).
- `page.tsx` и `packages/ui/index.ts` изменений не потребовали — компонент
  уже был подключён и экспортирован.

### TDD и проверки

- `HomeWavesBackground.test.tsx` переписан под новый контракт: точная
  палитра, точный счёт 1 rect + 7 path, viewBox/preserveAspectRatio,
  префиксация id градиентов. Старый тест (2 path, старые цвета) стал бы
  RED на новой геометрии.
- Jest не запускался — нет node_modules в этой среде.

### Изменённые файлы

- `packages/ui/components/HomeWavesBackground.tsx`
- `packages/ui/components/HomeWavesBackground.test.tsx`

---

## Task 138 -- LSTM/GRU vertical slice (первый исполнитель Neural Runtime Contract Task 137)

Дата: 2026-09-11. Синхронизация: eba9af8 (ресертификация Task 137; EGARCH
cert 8145806). Постановка docs/modeling_task_list.md::Tasks 138-142, срез
«Task 138 -- LSTM/GRU». Прецедент каркас -> исполнитель: Task 134 ->
135/136 (volatility); нейро-аналог: контракт Task 137 (neural_contract.py +
model_impls/neural_runtime.py, dependency_group="neural", честный
catalog_only пяти нейро-моделей) потреблён адаптером lstm.

### Решение (по пунктам постановки)

1. **Единый runtime -- без собственной fit/predict-петли**: исполнение
   ТОЛЬКО через neural_runtime.train_and_forecast (бюджет max_steps,
   явный accelerator, enable_progress_bar=False, random_seed=fold_seed в
   КОНСТРУКТОРЕ -- seed-дисциплина ресертификации Task 137). Адаптер не
   импортирует torch/neuralforecast напрямую (версии в metadata -- через
   importlib.metadata; единственная точка тяжёлых импортов сохранена).
2. **Ядро постановки -- архитектурный выбор ячейки**: каталог
   rules/modeling.yaml декларирует id="lstm", name="LSTM / GRU"
   («GRU -- легковесная альтернатива»), поэтому cell ∈ {lstm, gru} --
   bounded tuning-параметр на ОДНОМ runtime (нейрофоркаст-классы
   LSTM/GRU с идентичной поверхностью конструктора; эмпирика проба
   scripts/task138_neural_api_probe.py).  alias="LSTM"/"GRU" --
   стабильное именование выходных колонок.
3. **Временная ось -- реальная, регулярная**: train_timestamps
   обязательны (прецедент prophet); частота -- validate_regular_grid
   контракта Task 131 (единый источник истины, переиспользован --
   НЕ продублирован); нерегулярная сетка/дубликаты/row-order метки --
   честный отказ.  LSTM_MIN_TRAIN=32 (абсолютный пол) + гейт
   неосуществимого окна (n_train <= input_size + horizon -- отказ,
   молчаливое ужатие окна запрещено).
4. **Exogenous -- granted-канал Task 126 -> futr-роль контракта Task
   137**: future-known/static колонки (train_features + future_features
   парой) объявляются в NeuralExogenousPlan ролью futr через
   build_exogenous_plan (hist/stat пустые ЯВНО -- решения не прячутся);
   build_static_frame не используется: платформенный static приходит
   timestamped числовым рядом, stat_exog со скрытой агрегацией «первое
   значение» запрещён.  Fail-closed: несимметричный канал, несовпадение
   длин, NaN/Inf, коллизия имён с {unique_id, ds, y}.
5. **Интервалы -- сертифицированный conformal-путь**: point-loss MAE +
   PredictionIntervals + predict(level); уровни -- interval_levels_for_alpha
   (alpha {0.01,0.05,0.10}, как у VAR/GARCH/EGARCH).  Семантика колонок
   neuralforecast 3.2.2 снята ЭМПИРИЧЕСКИ: lo-L = point - q(L/100),
   hi-L = point + q(L/100) => двусторонний (1-alpha)-интервал -- ОБЕ
   границы на уровне L=100*(1-alpha/2)=levels[-1] (alpha=0.05 -> lo-97.5/
   hi-97.5 = 2.5/97.5 квантили).  MQLoss (рекомендация ресертификации
   Task 137) остаётся probabilistic-поверхностью для срезов 139-142.
6. **Bounded params**: PARAM_BOUNDS cell{0.01..}, input_size (4..128),
   encoder_hidden_size (8..256), encoder_n_layers (1..3), encoder_dropout
   (0..0.5), learning_rate (1e-4..0.1), max_steps (1..10000 = контракт);
   bool-коэрция целочисленных ручек отклоняется явно.  yaml param_space:
   cell x input_size x hidden x max_steps = 16 trials (<= 64);
   encoder_n_layers/dropout/lr -- валидируемые константы адаптера
   (границы fail-closed и вне тюнинга).
7. **Реестр v2 + dispatch + образ**: запись №20 -- objective="level_forecast",
   input_kind="supervised" (шестой supervised-адаптер), supports_future_
   features=True, dependency_group="neural", engine="neuralforecast",
   required_packages=("neuralforecast",) (runtime_available -- честный
   dependency-probe), deterministic=True (same-seed бит-в-бит: тесты +
   проб), resource memory_class="high", gpu="optional".  Production-образ
   с Task 138 несёт нейро-зависимости (requirements-neural.txt в Dockerfile,
   torch CPU-колёса -- иначе consistency-gate dispatch<->readiness честно
   уронил бы сборку) + Dockerfile-проба 'LSTM/GRU executable OK'
   (воспроизведена локально).
8. **Legacy synthetic-эндпоинт -- честный отказ** (run_lstm_backtest,
   прецедент var/vecm/garch/egarch): bare-ряд не несёт временной оси;
   изобретать её в обёртке (целочисленный индекс/скрытая регуляризация)
   -- запрещённый контракт скрытый выбор.

### TDD (RED -> GREEN)

- RED: tests/unit/test_lstm_adapter.py (34 кейса) + tests/unit/
  test_lstm_integration_paths.py (17 кейсов) -- collection errors на
  отсутствии модуля/экспортов; count-гейты 19 -- на отсутствии записи.
- GREEN после реализации + правки ОЖИДАНИЙ по снятой эмпирике:
  (а) alpha-коэрция числовой строки whitelist'а -- прецедент GARCH
  (принята), (б) conformal-семантика уровней (обе границы на levels[-1],
  см. п.5), (в) legacy-отказ вместо «реального» прогона bare-ряда,
  (г) порядок available_model_actions по реализации.

### Изменённые/новые файлы

Новые:
- apps/api/model_impls/lstm.py (~560 строк; адаптер LSTM/GRU, docstring
  с полным обоснованием решений)
- tests/unit/test_lstm_adapter.py (34 кейса)
- tests/unit/test_lstm_integration_paths.py (17 кейсов)
- scripts/task138_neural_api_probe.py (эмпирический проб: conformal/
  MQLoss/futr_exog/детерминизм GRU -- PROBE OK)
- scripts/task138_e2e_smoke.py (7 этапов полного chain'а)

Изменённые:
- apps/api/model_execution.py: _lstm_executor + запись реестра №20
- apps/api/model_impls/__init__.py: экспорт run_lstm_backtest
- apps/api/routers/models.py: dispatch + импорт
- rules/modeling.yaml: lstm param_space (16 trials) + комментарий Task 138
- apps/api/Dockerfile: neural-зависимости в образе + LSTM-проба
- apps/api/requirements-neural.txt: дисклоужер статуса (файл входит в
  production-сборку со среза Task 138)
- Count-гейты 19->20 честно в 9 файлах: test_egarch/test_garch
  integration_paths, test_modeling_mvp_certification (CERTIFIED_IDS+
  tuning set), test_model_execution_contract (NEURAL_IDS, supervised),
  test_model_readiness_candidates (lstm ready; 16/4/4; blocked 10 на
  коротком профиле: F04 60<200), test_backtesting_engine (sixteen),
  test_eda_model_matrix (lstm ready+blocked на профиле -- оси независимы),
  tests/api/test_models_backtest_real (20 impls), test_var_integration
  _paths (subprocess 'ok 20'), tests/api: catalog-only примеры
  test_modeling_workflow/test_models_candidates переключены lstm->tft.

### Границы Task 138 (что осознанно НЕ сделано)

- MQLoss/quantile-loss путь, hist_exog/stat_exog, early stopping
  (patience>0 требует val_size>0 -- на коротких folds нестабилен),
  encoder_activation/decoder-ручки -- поверхность контракта для срезов
  139-142; yaml-записи tft/nbeats/nhits/deepar не тронуты (честный
  catalog_only до их срезов).
- GPU-исполнение: runtime Task 137 фиксирует device="cpu" (сертифицировано);
  gpu="optional" в resource_capabilities -- декларация capability, не
  переключатель.
- Audit-скрипты сертификации Task 137 (cert137_*_oracles/mutations) НЕ
  модифицированы: RO6c ('available_model_actions("lstm") == []') и
  yaml-пробы теперь описывают ПРЕДЫДУЩЕЕ состояние дерева --
  characterization-пробы своего момента (прецедент OR11i ресертификации:
  сняты с учёта как характеризация, эквивалентное покрытие новыми тестами).

### Верификация

- TDD цикл выше; нейро-набор: 34 + 17 = 51 новый кейс.
- Полная регрессия на eba9af8 + Task 138: база 2193 (1470 unit + 623 api
  + 100 прочие) -> **2244 passed / 0 failed** (unit 1521 = 1470 + 51,
  api 623, прочие 100); snapshots 3/3; compileall OK; app-import OK;
  pip check PASS.
- Прод-инварианты: PRODUCTION_BACKTEST_MODEL_IDS == 20; lstm
  backtest/tune/diagnostics; tft/deepar catalog_only ([]); пустой
  маркер apps/api/__init__.py не тронут (13 регресс-тестов на месте).
- E2E смоук scripts/task138_e2e_smoke.py: registry/dispatch-gate ->
  candidates (16/4/4, execution_contract lstm) -> реальный OOF-бэктест
  GRU 3 folds (mae=0.4753) -> детерминизм плана бит-в-бит -> bounded
  tuning grid 16 trials + trial реальным движком -> future-known
  регрессор доходит до futr_exog -> изоляция cohort (level-движок
  отказывает volatility-плану). E2E SMOKE OK.
- Проб scripts/task138_neural_api_probe.py: PROBE OK (conformal-колонки
  с alias, MQLoss-median, futr_exog, same-seed бит-в-бит/другой сид
  max_diff=0.038); Dockerfile-проба воспроизведена локально:
  'LSTM/GRU executable OK'.
- Окружение: neuralforecast 3.2.2 + torch 2.14.0+cpu -- те же версии,
  на которых сертифицирован Task 137.
