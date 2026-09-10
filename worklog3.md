# CISStat TS Analysis — Worklog

---

## Task 131 — Multivariate Modeling Contract (каркас VAR/VECM, Tasks 132–133)

Дата: 2026-09-09. Синхронизация: `main @ ffc9deb` (Task 130 CatBoost + принятая
сертификация Task 130). Реализация по TDD (RED → код → GREEN); базовый прогон
на базе: 1678 passed / 0 failed, snapshots 3/3. Попутно закрыты оба
косметических замечания сертификации Task 130 (см. «Хаускипинг»).

### Постановка

docs/modeling_task_list.md::Task 131 — Multivariate Modeling Contract:
(1) явный набор endogenous-рядов вместо одной target; (2) общая регулярная
временная сетка без скрытой агрегации; (3) fold-local стационарность всех
компонент и cointegration evidence; (4) векторные OOF-точки, метрики по
каждому ряду и агрегированная scaled loss; (5) многомерный baseline и
отдельный comparison cohort; (6) диагностика устойчивости и белого шума
системы. Это инфраструктурная задача-контракт (уровень Task 126), НЕ новая
модель: адаптеры VAR/VECM подключаются в Tasks 132–133 поверх контракта.
CERTIFIED_IDS/каталог-гейты не менялись (15/24 production-моделей — без
сдвига).

### Дизайн-рекогносцировка (эмпирическая, до тестов)

Probe-скрипт (scripts/task131_probe.py) зафиксировал факты statsmodels
0.14.5, на которых построен дизайн: (1) формула объединённого Portmanteau
(Люткеполь 2005 §4.4.3, с/без small-sample поправкой) воспроизводится через
numpy и ПОБИТОВО совпадает с официальной VARResults.test_whiteness
(статистика 60.7974084994 при adjusted=True и 58.7584967252 при False —
оракул-сверка); (2) Йохансен (coint_johansen) на независимых I(1) рядах
(seed 11/23/42/77/2026) устойчиво даёт trace-ранг 0 на 95%, на
коинтегрированной паре y=2x+eps — ранг >= 1 (trace 62.9 > 15.49); (3)
детерминированная разладка (белый шум + дрейф +200 на хвосте 30 точек)
разворачивает консенсус ADF/KPSS: train-срез (170 точек) — stationary
(adf 0.0004/kpss 0.10), полная история — non-stationary (adf 0.74/kpss
0.01) — основа fold-locality-теста; (4) iid-остатки (seed 3, T=400) —
Portmanteau p=0.96, AR(1) phi=0.9 — p<1e-6.

### Дизайн

- `apps/api/multivariate_contract.py` (NEW, ~770 строк) — контракт
  многомерного моделирования, независимый от HTTP/session-кода; НЕ
  импортирует backtesting.py (в Tasks 132–133 движок будет импортировать
  контракт — встречный импорт создал бы цикл; паритет формул с движком
  связан parity-тестами):
  - **Endogenous system** (`EndogenousSystem`, `build_endogenous_system`):
    явный набор именованных endogenous-рядов (K >= 2 = min_series из
    modeling.yaml::var), одинаковая длина >= MIN_SYSTEM_OBSERVATIONS=20
    (= MIN_TRAIN_OBSERVATIONS EDA-стратегии), finite, имена уникальны
    (нормализация trim), порядок колонок матрицы = порядок объявления
    (существенен для интерпретации векторных коэффициентов; никакой скрытой
    сортировки). Методы: matrix() (T×K), train_slice/test_slice, head(stop)
    (fold-local подсистема).
  - **Общая регулярная сетка** (`validate_regular_grid`): дубликаты дат —
    панель-ошибка, нерегулярные интервалы — «регуляризуйте ряд» (семантика
    и формулировки EDA-стационарности), несортированный вход — fail-closed
    (никакой скрытой пересортировки); частота — платформенный
    detect_column_frequency (pd.infer_freq), календарные месяцы/кварталы
    распознаются корректно. Ни ресемплинга, ни интерполяции, ни агрегации.
    Grid-info (frequency/start/end/n) попадает в cohort-контракт; режим без
    дат — явный row_order (grid=None), как order_source="row_order" в EDA.
  - **Fold-local стационарность** (`component_stationarity`,
    `fold_stationarity_evidence`): ADF(уровень)+KPSS(уровень) КАЖДОЙ
    компоненты, консенсус-метки зеркалят EDA (stationary/non-stationary/
    inconclusive); advisory-контракт: вырожденные/короткие данные дают
    available=False с причиной — evidence никогда не выдумывается; функции
    видят ТОЛЬКО переданную матрицу (train-срез фолда), fold-locality
    привязана тестом разладки.
  - **Cointegration evidence** (`fold_cointegration_evidence`): Йохансен
    trace+max-eig на train-срезе, последовательный ранг (подряд идущие
    отвержения), det_order ∈ {-1,0,1}, k_ar_diff ∈ [1,12], alpha ∈
    {0.10,0.05,0.01}; короткие фолды (n < k_ar_diff + 20) и вырожденные
    данные — available=False с причиной; reference-тест-привязка: статистики
    модуля == прямому coint_johansen на ТОЙ ЖЕ матрице (rel 1e-12).
  - **Векторные OOF-точки** (`vector_oof_points`): long-format —
    сертифицированная схема движка (fold/horizon_step/index/label, residual
    = actual - predicted round 12) + размерность `series`; детерминированный
    порядок (шаг горизонта, потом порядок серий); fail-closed на форму/NaN/
    дубликаты имён/несовпадение test_indices.
  - **Векторные метрики** (`vector_metric_scales`,
    `compute_vector_metrics`): per-series MAE/RMSE/MAPE/sMAPE/MASE/RMSSE —
    формулы ИДЕНТИЧНЫ сертифицированной compute_forecast_metrics движка
    (parity-тест обоими направлениями); MASE каждой серии масштабируется
    train-only naive-MAE СВОЕЙ серии (vector_metric_scales — паритет с
    compute_metric_scales); weighted_score всегда None (нормализация только
    внутри comparison). Агрегированная scaled loss = mean пер-серийных
    MASE (масштабо-инвариантна), all-or-none: хоть одна серия без MASE —
    агрегат честно None (частичная подмена запрещена).
  - **Многомерный baseline** (`vector_naive_baseline`): persistence каждой
    серии от последнего наблюдения переданной системы (VAR(0)-аналог);
    fold-local через system.head(train_end); никаких fallback-подмен.
  - **Отдельный comparison cohort** (`multivariate_cohort_contract`):
    objective="multivariate" + system-блок (contract_version, endogenous,
    n_observations, grid); ключи верхнего уровня совместимы со схемой
    backtesting.build_backtest_plan; fingerprints обязаны соответствовать
    составу системы; разделение cohort'ов привязано к сертифицированному
    aligned_oof (несовпадение objective/cohort_contract отвергается).
  - **Диагностика системы** (`companion_stability`): companion-матрица из
    PHI_1..PHI_p (pK×pK), max|lambda| < 1 СТРОГО (граница круга =
    неустойчивость, задокументировано); `system_white_noise_diagnostics`:
    объединённый Portmanteau (numpy, центрирование по конвенции
    statsmodels._compute_acov, adjusted/unadjusted, df=K²(nlags-p),
    fitted_var_order обязателен < nlags) + пер-серийный Ljung-Box
    (model_df=fitted_var_order); вырожденная ковариация (идеальный фит) —
    fail-closed, а не фиктивный «идеальный белый шум».
- Хаускипинг Task 130 (оба замечания сертификации):
  1. `apps/api/model_impls/catboost.py::_normalize_importances` — статус
     DEFENSIVE-ONLY зафиксирован в докстринге (ветка недостижима через
     публичную поверхность адаптера: zero-сумма важности требует
     константных признаков, что CatBoost отклоняет library-native) +
     dedicated хелпер-тесты `TestNormalizeImportancesHelper` в
     tests/unit/test_catboost_adapter.py: нулевая сумма → детерминированный
     uniform 1/n, проценты → нормализация к сумме 1.0 с сохранением
     порядка. Mutation-4 gap (удаление fallback не ловился) закрыт на
     уровне юнита.
  2. bagging_temperature=0.0 — документированное платформенное отклонение
     от официального 1.0 подтверждено как корректное (докстринг модуля уже
     фиксирует обоснование: байесовский ресемплинг строк избыточно шумит
     на коротких platform-fold'ах); изменений кода не требует.

### TDD

RED: tests/unit/test_multivariate_contract.py (83 кейса) —
ModuleNotFoundError подтверждён. Два честных фикса ТЕСТОВ до реализации
(арифметика моих собственных закрытых форм: MAPE gdp 10%, а не 1000%;
scaled_loss в A/B-примере 0.25 = mean(0.5, 0.0)) и один тест-фикс
неполной fake-точки (residual в aligned_oof-заглушке). GREEN после
реализации: 3 итерационных фикса КОДА — (1) реальный баг: длина временной
оси сравнивалась с числом СЕРИЙ вместо числа наблюдений + переупорядочена
валидация (сетка ПЕРЕД минимальной длиной — специфичная ошибка контракта
важнее общей); (2) формулировки ошибок приведены к контрактам тестов
(«длина/форма», «список … пуст», «длина … недостаточна») — без изменения
поведения; (3) добавлен тест инвариантности Portmanteau к центрированию
остатков после того, как mutation-проверка показала: на VAR-остатках с
перехватом (выборочное среднее == 0) удаление центрирования оракул-тестом
не различается.

### Мутационная самопроверка RED-валидности (5 мутаций, применялись и откатывались)

1. residual = predicted - actual (знак) → FAILED
   test_vector_oof_residual_sign_convention_and_rounding;
2. scaled_loss = max вместо mean → FAILED
   test_scaled_loss_is_mean_of_per_series_mase;
3. is_stable: max_modulus <= 1.0 (нестрогое неравенство) → FAILED
   test_unit_circle_boundary_is_unstable_by_strict_inequality;
4. Portmanteau без центрирования остатков → сначала НЕ поймана (остатки
   VAR с перехватом имеют нулевое среднее), после добавления
   test_portmanteau_is_invariant_to_residual_centering — FAILED;
5. (вырожденная ветка) — ковариация нулевых остатков поднимает
   MultivariateContractError, поведение привязано
   test_white_noise_singular_covariance_fails_closed напрямую.
Рабочая копия после каждой мутации верифицирована (backup + git diff).

### Верификация

- Полный pytest: **1763 passed / 0 failed** (1678 + 83 контракт + 2
  хаускипинга), snapshots 3/3; арифметика счётчиков сходится ровно
  (--collect-only: 131 = 83 multivariate_contract + 48 catboost_adapter
  (46 + 2 новых)).
- compileall apps OK; `from apps.api.main import app` OK; pip check PASS.
- Фронтенд не затронут (0 файлов packages/, apps/standalone,
  apps/embedded); jest-регрессия невозможна по построению. commit/push не
  выполнялись (запрет AGENTS.md соблюдён).

### Задел Tasks 132–133 (VAR/VECM)

Точки подключения: (1) адаптеры в model_impls/ на EndogenousSystem +
векторной метрике; (2) интеграция движка backtesting.py для векторных
моделей (objective="multivariate", input_kind="multivariate",
requires_related_series — все гейты реестра v2 уже готовы, продюсера
related_series появятся в 132); (3) порядки лагов VAR/ранг Йохансена —
fold-local через fold_cointegration_evidence/fold_stationarity_evidence;
(4) диагностика — companion_stability + system_white_noise_diagnostics;
(5) comparison — multivariate_cohort_contract + vector baseline;
(6) modeling_workflow.py::build_modeling_context жёстко кодирует
n_series=1/is_cointegrated=False — при подключении multivariate-трека
потребует честного профиля системы.

---

## Task 131 — Multivariate Modeling Contract (VAR/VECM framework): сертификация

Дата: 2026-09-09. Синхронизация: `main @ 78d94fd` («Task 131 - Multivariate
Modeling Contract (VAR/VECM framework, Tasks 132–133)»). Аудит реализации
коллеги: apps/api/multivariate_contract.py (NEW, 961 строка),
tests/unit/test_multivariate_contract.py (NEW, 83 кейса), хаускипинг
apps/api/model_impls/catboost.py + tests/unit/test_catboost_adapter.py
(+2 кейса). Коммит не изменён; commit/push агентом не выполнялись
(запрет AGENTS.md соблюдён).

### Методология аудита

(1) Постановка docs/modeling_task_list.md::Task 131 разобрана на 6
обязательных пунктов и каждый прослежен до кода И до связывающего теста;
(2) построчная сверка паритета формул с сертифицированным движком
(compute_metric_scales / compute_forecast_metrics / build_backtest_plan /
BacktestMetrics / aligned_oof / BacktestPredictionPoint);
(3) воспроизведение тестового базлайна в чистом окружении;
(4) НЕЗАВИСИМЫЕ oracle-сверки на собственных данных и seed (не из тестов
коллеги): объединённый Portmanteau против statsmodels
VARResults.test_whiteness (K=4, p=3, остатки с ненулевым средним, оба
варианта adjusted — совпадение rel=0.0, df=112==112), Йохансен против
прямого coint_johansen на alpha 0.10/0.01 (3 ряда, y=1.7x+eps);
(5) собственные mutation spot-checks, НЕ пересекающиеся с пятью мутациями
коллеги: (A) перекрёстная утечка MASE-scale первой серии во все остальные —
поймана test_vector_metric_scales_match_engine_formulas (2 отказа);
(B) удаление центрирования остатков в Portmanteau — поймана
test_portmanteau_is_invariant_to_residual_centering (тест, добавленный
коллегой после его мутации-4, работает); обе мутации применялись и
откатывались, рабочая копия верифицирована (83 passed после отката);
(6) проверка неизменности сертификационной поверхности: коммит трогает
ровно 5 файлов, registry/yaml/dispatch/CERTIFIED_IDS не затронуты
(15/24 production-моделей — без сдвига), фронтенд не затронут.

### Покрытие постановки (все 6 пунктов подтверждены)

1. Явный набор endogenous-рядов — EndogenousSystem: K>=2 (=min_series
   modeling.yaml::var/vecm), равные длины >= MIN_SYSTEM_OBSERVATIONS=20
   (=MIN_TRAIN_OBSERVATIONS EDA), finite, уникальные имена с trim-
   нормализацией, порядок колонок = порядок объявления (тест «zebra/alpha»
   ловит скрытую сортировку); matrix()/train_slice/test_slice/head().
2. Общая регулярная сетка без скрытой агрегации — validate_regular_grid:
   дубликаты = панель-ошибка, нерегулярность = «регуляризуйте ряд»
   (семантика EDA), несортированный вход fail-closed, частота —
   платформенный detect_column_frequency (pd.infer_freq; месяцы/кварталы
   распознаются); ни ресемплинга, ни интерполяции; режим row_order
   (grid=None) явный.
3. Fold-local стационарность + коинтеграция — ADF+KPSS консенсус каждой
   компоненты (метки зеркалят app/eda/stationarity), advisory-контракт
   available=False с причиной на вырожденных данных (константная серия —
   не выдуманный «stationary»); Йохансен trace+max-eig, последовательный
   ранг, det_order{-1,0,1}, k_ar_diff[1,12], alpha{0.10,0.05,0.01},
   короткий фолд < k_ar_diff+20 — честно unavailable; fold-locality
   привязана тестом разладки (train 170 точек stationary, полная история
   non-stationary) и reference-сверкой с прямым coint_johansen.
4. Векторные OOF-точки и метрики — vector_oof_points: long-format,
   схема движка fold/horizon_step/index/label + series, residual =
   actual - predicted round 12, детерминированный порядок (шаг, серия
   объявления); vector_metric_scales — train-only naive-масштаб КАЖДОЙ
   серии (паритет с compute_metric_scales связан тестом обоими
   направлениями); compute_vector_metrics — формулы per-series ИДЕНТИЧНЫ
   compute_forecast_metrics (построчная сверка мною подтверждена: nonzero-
   маска MAPE по eps, sMAPE 200*|e|/(|a|+|p|), round 6, mape_valid_points,
   weighted_score=None), scaled_loss = mean пер-серийных MASE, all-or-none
   (одна серия без MASE — агрегат честно None; привязано тестом).
5. Многомерный baseline + отдельный cohort — vector_naive_baseline:
   persistence каждой серии от последнего значения ПЕРЕДАННОЙ системы
   (VAR(0)-аналог; fold-local через head, привязан тестом «baseline от
   среза != baseline от полной истории»); multivariate_cohort_contract:
   objective="multivariate" + system-блок (contract_version, endogenous,
   n_observations, grid), top-level ключи совместимы со схемой
   build_backtest_plan (сверено мною с backtesting.py:218–223), изоляция
   cohort'ов привязана к сертифицированному aligned_oof (тест отказа
   mixed-objective сравнения; в движке modeling_comparison.py:100–103).
6. Диагностика системы — companion_stability: pK x pK companion из
   PHI_1..PHI_p, max|lambda| < 1 СТРОГО (граница круга = неустойчивость,
   привязано тестом PHI=[[1.0]]); system_white_noise_diagnostics:
   объединённый Portmanteau Люткеполя 2005 §4.4.3 (центрирование по
   конвенции _compute_acov; инвариантность к сдвигу уровня привязана
   отдельным тестом), df = K^2*(nlags - fitted_var_order), nlags >
   fitted_var_order обязателен, пер-серийный Ljung-Box с model_df;
   вырожденная ковариация (нулевые остатки) — fail-closed, а не
   фиктивный «идеальный белый шум» (привязано тестом).

Мои независимые oracle-сверки: Portmanteau rel=0.0 (bitwise) против
statsmodels на моих данных; Йохансен статистики rel 1e-12 и корректные
колонки критических значений для 90%/99%; companion max|lambda| ==
max|eig(PHI)| на моём VAR(1); порядок OOF-точек (шаг, серия-объявление)
без сортировки имён; знаки residual; per-series масштаб при перестановке
колонок. Итог 17/17 PASS.

### TDD и мутационная устойчивость

RED зафиксирован коллегой (ModuleNotFoundError, 83 кейса), честные фиксы
ТЕСТОВ до реализации задокументированы (арифметика закрытых форм).
Мутационная самопроверка коллеги: 5 мутаций с привязкой к тестам, включая
честное признание «мутация 4 сначала не ловилась» с последующим усилением
контура (centering-инвариантность) — это усиление я независимо повторил
своей мутацией B: тест ловит. Мои мутации A/B дополняют коллегу и
подтверждают чувствительность контура к перекрёстным утечкам масштаба.

### Верификация (воспроизведена в моём окружении)

- Окружение потребовало установки 7 отсутствующих пакетов (PyWavelets,
  pandera, prophet, statsforecast, ruptures, arch, syrupy>=4.6.0 — пин из
  requirements-dev.txt) — дрейф МОЕГО окружения, не кода; после
  восстановления: **1763 passed / 0 failed, snapshots 3/3** — ровно как
  заявлено. --collect-only: 1763 = база 1632 + 83 multivariate_contract +
  48 catboost_adapter (46 + 2 хаускипинга).
- compileall apps OK; `from apps.api.main import app` OK; pip check PASS.
- Гейт консистентности `_BACKTEST_IMPLEMENTATIONS` vs
  PRODUCTION_BACKTEST_MODEL_IDS в routers/models.py при неполных
  зависимостях честно падает на импорте (RuntimeError) — это
  спроектированный fail-closed гейт платформы, а не дефект Task 131
  (модуль контракта от HTTP-кода не зависит и при нём импортируем).

### Хаускипинг Task 130 (оба замечания закрыты подтверждённо)

1. `_normalize_importances`: статус DEFENSIVE-ONLY зафиксирован в
   докстринге + TestNormalizeImportancesHelper (2 кейса: нулевая сумма →
   детерминированный uniform 1/n с повторной проверкой детерминизма;
   проценты → нормализация к 1.0 с сохранением порядка). Gap мутации-4
   закрыт на уровне юнита.
2. bagging_temperature=0.0: документированное обоснование в докстринге
   модуля подтверждено корректным (байесовский ресемплинг строк избыточен
   на коротких platform-fold'ах); изменений кода не требует — согласен.

### Замечания (косметические, сертификации не препятствуют)

1. scripts/task131_probe.py упомянут в докстринге тестов и worklog, но в
   репозиторий не закоммичен. Доказательной дыры нет (все факты
   рекогносцировки привязаны oracle-тестами: Portmanteau против
   test_whiteness, Йохансен против coint_johansen, разладка, AR(1)),
   однако ссылка на несуществующий в репо файл — мелкий документационный
   долг; стоит либо закоммитить probe, либо убрать ссылки.
2. multivariate_cohort_contract фиксирует feature_contract в legacy-форме
   policy="none" — корректно для систем без регрессоров, но VAR в
   modeling.yaml имеет supports_exogenous: true: в Tasks 132–133
   потребуется явный путь supervised-контракта в многомерный cohort
   (иначе exogenous-варианты VAR не смогут честно попасть в comparison).
   Задел уже зафиксирован коллегой в разделе «Задел Tasks 132–133».

### Вердикт

**Task 131 сертифицирована: реализация отличная.** Инфраструктурный
контракт полностью закрывает все 6 пунктов постановки, следует конвенциям
сертифицированного ядра (peek/push-уровень fold-locality, паритет формул
движка, all-or-none честность агрегатов, fail-closed на вырожденных
данных, advisory-свидетельства без выдуманных фактов), тестовый контур
чувствителен к мутациям (5 коллеги + 2 мои), базлайн воспроизводится
(1763/0/3). Изменения поверхности сертификации нет: 15/24 сохраняется,
адаптеры VAR/VECM — предмет Tasks 132–133.

---

## Task 132 — VAR: production vertical slice (нативный statsmodels, fold-local порядок лага)

Дата: 2026-09-09. Синхронизация: `main @ ef22027` (принятая сертификация
Task 131). Реализация по TDD (RED → код → GREEN); базовый прогон на базе:
база ef22027 1763 passed → финал **1835 passed / 0 failed, snapshots
3/3**. Арифметика: +72 новых = 28 var_adapter + 26 var_backtest (включая
юнит взвешенной агрегации) + 16 var_registry_integration + 2 API-workflow.
commit/push не выполнялись (запрет AGENTS.md соблюдён).

### Постановка

docs/modeling_task_list.md::Task 132 — VAR; общая нота серии: порядок лага
VAR выбирается fold-local; statsmodels даёт отдельный многомерный прогноз и
интервалы — НЕ сводить к циклу одномерных ARIMA. modeling.yaml::var:
min_observations=100, min_series=2, supports_prediction_intervals, statsmodels.
Точки подключения (worklog3.md, «Задел Tasks 132–133»): адаптер на
EndogenousSystem + векторная интеграция движка + честный n_series в
build_modeling_context. После серии: 16/24 production-моделей.

### Дизайн и реализация

1. **`apps/api/model_impls/var.py` (NEW, ~300 строк)** — нативный
   statsmodels-адаптер (VARAdapterID="statsmodels-var"):
   - bounded params fail-closed: maxlags (1..12), ic ∈ {aic,bic,hqic,fpe}
     или None (=фиксированный p=maxlags), trend ∈ {c,ct,n,ctt}, alpha ∈
     {0.01,0.05,0.10} (семантика statsmodels: уровень значимости — меньше =
     шире; нативная семантика сохранена);
   - fold-local порядок лага: select_order/fit ТОЛЬКО на переданном
     train-срезе; детерминированная проверка достаточности истории
     (nobs > (K+1)·p + K для фикс. p; для ic-поиска — по верхней границе);
   - нативные интервалы VARResults.forecast_interval (НЕ цикл ARIMA);
     инвариант lower ≤ point ≤ upper;
   - fail-closed: K ≥ 2, NaN/Inf, длины, короткая история (VAR_MIN_TRAIN=20
     = MIN_SYSTEM_OBSERVATIONS контракта); никаких Naive-fallback;
   - payload: forecast/lower/upper (horizon×K), lag_order, lag_selection
     (таблица select_order), coefficient_matrices, in_sample_residuals —
     вход диагностики контракта Task 131; детерминизм: VAR = OLS,
     случайности нет (random_state принят по контракту, не влияет);
   - run_var_backtest (legacy synthetic-эндпоинт): честный отказ на
     одиночном ряде (синтетические многомерные демо запрещены).
2. **Реестр v2 (`model_execution.py`)** — первый multivariate-исполнитель:
   objective="multivariate", input_kind="multivariate",
   requires_related_series=True, deterministic, intervals; actions =
   backtest+diagnostics (векторный tuning — предмет Task 133; bounded
   param_space в yaml уже задокументирован). `_var_executor`: плоский
   контракт forecast = колонка target-ряда; полный векторный payload в
   metadata (читается векторным движком).
3. **Векторный движок (`backtesting.py`)** — `run_vector_backtest_plan`:
   - вход: валидированная EndogenousSystem (Task 131) + план
     objective="multivariate"; fold-local: train-срез обязан быть
     непрерывным префиксом (fail-closed);
   - fold_preprocessor применяется к target-колонке (model/evaluation
     шкалы), related-ряды — raw; восстановление прогноза target — через
     restore_forecast;
   - OOF — vector_oof_points (long, размерность series, residual =
     actual − predicted round 12); метрики — vector_metric_scales
     (train-only, своя серия) + compute_vector_metrics; fold["metrics"] —
     поточечный пул всех серий (MAE/RMSE/MAPE/sMAPE) + среднее
     пер-серийных MASE/RMSSE (all-or-none);
   - агрегаты: поточечный пул всех OOF-точек; MASE — взвешенное по n_test
     среднее fold-значений; RMSSE — корень из взвешенного среднего
     квадратов (зеркало _aggregate_metrics); per-series агрегаты отдельно;
     scaled_loss прогона — взвешенное среднее fold-значений (all-or-none);
   - baseline — persistence каждой серии (VAR(0)-аналог) от последнего
     train-наблюдения в evaluation-шкале target, ТЕ ЖЕ folds, те же
     знаменатели MASE — честный сравнительный якорь в result["vector_baseline"];
   - fold-local диагностика: fold_stationarity_evidence +
     fold_cointegration_evidence (train-срез, evaluation-шкала),
     companion_stability (коэффициенты адаптера), Portmanteau по
     in-sample остаткам (nlags = max(p+1, min(8, p+3)) — строго > p);
   - FeaturePlan-регрессоры не применяются (VARX — Task 133) с честным
     warning; cohort-контракт — авторитетный multivariate_cohort_contract
     (Task 131) через новый параметр build_backtest_plan
     cohort_contract_override (участвует в cohort_id; default None —
     univariate-пути не изменены).
4. **Схемы (`schemas.py`)** — BacktestPredictionPoint.series
     (Optional[str]; обратная совместимость: null для univariate);
     BacktestFoldResult/BacktestResponse: per_series_metrics, scaled_loss,
     vector_baseline, multivariate_diagnostics — векторные артефакты не
     теряются при Pydantic-сериализации.
5. **Comparison (`modeling_comparison.py`)** — _point_key дополнен
     размерностью series (5-компонентный ключ; univariate-точки без поля
     дают "" — ключи не меняются); _ensemble_backtest переведён на общий
     _point_key (локальная 4-компонентная копия расходилась бы).
6. **Честный n_series (`modeling_workflow.py`)** — honest_system_profile:
     n_series = число числовых колонок кроме объявленной date-колонки
     (даже числовой), related_series = имена в порядке датафрейма,
     is_cointegrated = advisory-Йохансен (95%) на полной числовой системе —
     никогда не выдумывается; build_modeling_context больше не жёстко
     кодирует n_series=1/is_cointegrated=False.
7. **EDA-матрица (`eda_model_matrix.py`)** — shape-критерий multivariate:
     enough = numeric_series ≥ required (заглушка task=="multivariate"
     снята — исполнители появились); task-критерий: production
     multivariate-модель под task="forecast" — attention (прогноз уровня
     всей системы, target — первая колонка), НЕ fail; catalog-only (VECM
     до Task 133) остаются заблокированными. Стационарность target —
     прежний честный блокирующий критерий.
8. **Dispatch (`routers/models.py`, `model_impls/__init__.py`,
     `modeling_session.py`)** — _BACKTEST_IMPLEMENTATIONS["var"]
     (гейт консистентности с реестром соблюдён); run_modeling_backtest
     ветвится по objective исполнения: vector-путь строит систему из
     target + связанных числовых колонок (порядок датафрейма), fingerprints
     каждой серии (target — контекстный, related — series_fingerprint по
     датам), авторитетный cohort-контракт и вызывает векторный движок.
9. **`rules/modeling.yaml`** — var.param_space: maxlags [4,8,12] × ic
     [aic,bic] = 6 trials; Dockerfile — проба исполняемости _var_fit_predict
     (release-гейт 16-й модели).

### TDD

RED: 3 новых файла (69 кейсов) — ModuleNotFoundError
apps.api.model_impls.var подтверждён. Честные фиксы ТЕСТОВ до реализации:
(1) level-shift всей истории ряда b инвариантен в VAR с интерцептом (OLS
поглощает константу) — мутация хвоста динамики вместо сдвига уровня;
(2) инвертированная семантика alpha statsmodels (меньше = шире) — тест
переименован и перевернут; (3) дублирующая колонка — вырожденная система
(library-native отказ) — независимый шум; (4) seed 42 при n=200 даёт
ложный ранг Йохансена — конструкция n=150, верифицированная в Task 131;
(5) точная линейная связь y=2x+c сингулярна — добавлен шум. GREEN: 3
итерационных фикса КОДА: (1) реальный баг: actual-матрица тест-горизонта
не нуждается в gap-срезе (срез по gap портил форму при gap>0);
(2) nlags Portmanteau обязан быть строго > p (ломалось при p=8);
(3) константная endogenous-серия — library-native отказ statsmodels
(trend='c') — тест переведён на честный fail-closed.

### Мутационная самопроверка (3 мутации, применялись и откатывались)

1. адаптер игнорирует alpha (интервалы всегда 0.05) → FAILED
   test_smaller_alpha_gives_wider_intervals;
2. baseline persistence от последней строки ПОЛНОЙ системы (утечка хвоста)
   → FAILED test_vector_baseline_is_fold_local_persistence;
3. агрегат MASE — простое среднее вместо взвешенного по n_test → FAILED
   test_aggregate_mase_is_test_size_weighted_across_folds (тест добавлен:
   неравные n_test 9/3 → взвешенное 1.5 vs простое 2.0).
Рабочая копия после каждой мутации верифицирована (backup + revert + 54
passed).

### Верификация

- Полный pytest: **1835 passed / 0 failed**, snapshots 3/3;
  --collect-only: 1835 = 1763 + 28 var_adapter + 26 var_backtest +
  16 var_registry_integration + 2 API-workflow (сходится ровно).
- compileall apps OK; `from apps.api.main import app` OK; pip check PASS;
  Dockerfile-проба _var_fit_predict проверена локально (shape (2,2)).
- Фронтенд не затронут (0 файлов packages/, apps/standalone,
  apps/embedded); jest-регрессия невозможна по построению.
- API-сквозной прогон: session backtest var на стационарной системе
  (value+driver, n=120, MS-сетка): objective=multivariate, system-блок
  cohort ["value","driver"], OOF с series-размерностью, per-series
  метрики, scaled_loss, persistence-baseline, fold-диагностика (порядок
  лага ≥ 1, белый шум available) — всё в ответе API и session-артефактах.

### Границы Task 132 (задел Task 133 — VECM)

- Векторный tuning (execute_vector_tuning_plan + router-ветки) — Task 133;
  bounded param_space в yaml готов, actions реестра без "tune".
- Exogenous-канал (VARX, supports_exogenous: true в yaml) — Task 133:
  supervised-контракт в multivariate cohort (замечание сертификации 131).
- Ранг Йохансена fold-local для VECM — через fold_cointegration_evidence
  контракта (готово).
- Изменение критериев EDA-матрицы (task/shape) затронуто минимально и
  честно: production var достижим из session-потока, VECM остаётся
  заблокированным до реализации.

---

## Hotfix интеграции Task 132: канонические пути VAR-адаптера (sync e6f6726)

Дата: 2026-09-09. Синхронизация до **e6f6726** («Task 132 — VAR: production
vertical slice»). Симптом тимлида: вкладка «Моделирование», «Исполнение»,
фильтр «Подключённые» — как было 15 моделей, так и осталось; семейство
«Многомерные» с VAR не появилось.

### Диагноз (корневая причина)

В коммите e6f6726 два файла легли не на свои места (подтверждено
`python3 -c "import apps.api"` → ModuleNotFoundError):

1. **`apps/api/var.py`** — VAR-адаптер закоммичен в корне пакета API вместо
   `apps/api/model_impls/var.py`. Файл сам себя документирует первой строкой
   `# apps/api/model_impls/var.py`; по каноническому пути на него ссылаются
   4 точки: `apps/api/__init__.py:41` (случайно перезаписанный), 
   `model_execution.py:597` (`_var_executor`), `Dockerfile:93`
   (release-проба), `tests/unit/test_var_adapter.py:18`.
2. **`apps/api/__init__.py`** — пакетный init API (в ef22027 — пустой маркер
   e69de29) случайно перезаписан копией содержимого
   `apps/api/model_impls/__init__.py` (+var-импорт). В результате:
   - `import apps.api` падал первым же импортом
     (`ModuleNotFoundError: No module named 'apps.api.model_impls.var'`);
   - бэкенд не поднимался → `/candidates` недоступен → UI отображал
     устаревший каталог: 15 «Подключённых», без «Многомерные»;
   - даже при верном пути адаптера реэкспорты в пакетном init API —
     архитектурная ошибка: side-effect импорты адаптеров при инициализации
     пакета `apps.api` роняют весь бэкенд от любой ошибки одного адаптера.

### Фикс (3 файла + regression-тест)

- `git mv apps/api/var.py apps/api/model_impls/var.py` (канонический путь
  всех адаптеров: prophet.py, tbats.py, random_forest.py, catboost.py, ...).
- `apps/api/__init__.py` — восстановлен пустой маркер пакета
  (статус-кво ef22027, blob e69de29).
- `apps/api/model_impls/__init__.py` — добавлены
  `from apps.api.model_impls.var import run_var_backtest` и
  `"run_var_backtest"` в `__all__` (экспорт-поверхность dispatch:
  `routers/models.py:48`, `test_models_backtest_real.py`).

### TDD

RED: `tests/unit/test_var_integration_paths.py` (NEW, 13 кейсов, 4 класса):
- `TestAdapterCanonicalLocation` — адаптер только в model_impls/, дубль
  в корне API отсутствует, docstring-путь согласован;
- `TestApiPackageInitIsPureMarker` — apps/api/__init__.py без реэкспортов
  (атрибуты + исходник) и без side-effect импортов (subprocess-проверка
  sys.modules после `import apps.api`);
- `TestModelImplsExportSurface` — run_var_backtest экспортируется рядом
  с остальными адаптерами, присутствует в `__all__`, канонический модуль
  импортируется (run_var_backtest + _var_fit_predict);
- `TestRegistrySeesVarAtRuntime` — runtime_available('var'), var в
  PRODUCTION_BACKTEST_MODEL_IDS, полная dispatch-цепочка
  (routers.models + readiness) исполняется в subprocess и даёт 16 моделей.
Прогон на e6f6726: **13 failed** (ModuleNotFoundError/ImportError —
воспроизведение симптома пользователя на уровне импортов).

GREEN после фикса: 13/13.

### Верификация

- Полный pytest: **1848 passed / 0 failed**, snapshots 3/3; арифметика:
  1763 (ef22027) + 74 новых − 2 обновлённых гейта «15→16» (коллега) +
  13 regression (фикс) = 1848 (сходится ровно).
- End-to-end сценарий UI (scripts/task132_fix_ui_e2e_check.py,
  _compute_candidates на профиле n_series=3, M-сетка, 200 obs):
  каталог 24 модели, «Подключённые» = **16**, VAR —
  family_id=multivariate, platform_status=ready, actions
  [backtest, diagnostics], уровень RECOMMENDED; семейство
  «Многомерные» = [var, vecm] (VECM — catalog_only до Task 133).
- Dockerfile-проба `from apps.api.model_impls.var import _var_fit_predict`
  воспроизведена локально (VAR executable OK, shape (2,2)).
- compileall apps/api + новый тест OK; pip check PASS.
- Фронтенд не затронут: MODEL_FAMILIES в packages/ui/lib/modeling.ts уже
  содержит { id: "multivariate", name: "Многомерные" }; группировка UI
  строится из catalog по family_id — catalog просто не доходил до UI из-за
  лежащего бэкенда.

### Влияние

- UI «Моделирование» → «Исполнение» → «Подключённые»: 15 → **16**
  (VAR подключён); семейство «Многомерные» отображается с VAR.
- Regression-защита: 13 кейсов фиксируют канонические пути адаптеров и
  «пустоту» пакетного init API — повторение ошибки размещения файлов
  ловится на RED до поднятия бэкенда.

---

## Task 133 — VECM + векторный tuning + exogenous-канал VARX (production vertical slice)

Дата: 2026-09-09. Синхронизация до **74654a0** («Integration Hotfix Task 132»,
базлайн 1848 passed). Постановка docs/modeling_task_list.md::Task 133 и
задел «Границы Task 132» worklog3.md. После серии: **17/24** production-моделей.

### Реализация (5 поверхностей)

1. **`apps/api/model_impls/vecm.py` (NEW, ~430 строк)** — нативный
   statsmodels-VECM. Ранг Йохансена ТОЛЬКО на train-fold: `coint_rank="auto"`
   => `select_coint_rank` (trace, signif=0.05, det_order из детерминированных
   термов: n→-1, ci/co→0, li/lo→1); ранг 0 — честный отказ БЕЗ VAR-fallback;
   фиксированный ранг ≤ K-1. Прогноз — нативный `VECMResults.predict(steps,
   alpha)` (mid/lower/upper, НЕ цикл одномерных ARIMA). Bounded params:
   k_ar_diff 1..12, coint_rank auto|int≥1, deterministic n/ci/co/li/lo,
   alpha 0.01/0.05/0.10; история: nobs > (K+1)(k_ar_diff+1)+K, минимум 20
   (MIN_SYSTEM_OBSERVATIONS). Metadata: k_ar_diff/coint_rank/rank_selection/
   deterministic_terms/nobs/var_rep-блоки/in_sample_residuals.
   `run_vecm_backtest` — честный отказ на одиночном synthetic-ряде.
2. **Векторный tuning (`modeling_tuning.py` + `modeling_session.py`)** —
   `execute_vector_tuning_trial` / `execute_vector_tuning_plan_with_artifacts`:
   каждый trial — ПОЛНЫЙ `run_vector_backtest_plan` на тех же EDA-folds
   (никаких упрощённых срезов); сетка/усечение/finalize — общие
   `prepare_tuning_grid`/`finalize_tuning_plan_with_artifacts` (MAX_TRIALS=64,
   детерминированный sample, failures — честные пропуски, all-fail —
   BacktestExecutionError). Session tuning endpoint: векторная ветка через
   общий helper `_multivariate_vector_context` (извлечён из backtest-ветки,
   behavior bit-for-bit) — система, fingerprints, cohort, план; promoted
   best_backtest — полноценный векторный артефакт (per-series, scaled_loss,
   baseline, diagnostics). Реестр: var/vecm actions=_TUNABLE =>
   PRODUCTION_TUNING_MODEL_IDS 9 → **11**.
3. **Exogenous-канал VARX** — только VAR (yaml: vecm supports_exogenous:
   false). Адаптер (`var.py::_validated_exog` + `_var_fit_predict(exog=,
   exog_future=)`): обе части одновременно, одинаковые ключи, finite
   (импутация известного будущего запрещена), длины nobs/horizon;
   statsmodels `VAR(matrix, exog=...)` + `forecast_interval(...,
   exog_future=...)`; без exog — прежний контракт бит-в-бит. Движок
   (`run_vector_backtest_plan(exogenous=...)`): полная история exog-колонок,
   выровненная с системой; fail-closed (имена/дубли с endogenous/числовость/
   finite/длина); per-fold срезы train_features=[:n_train],
   future_features=[n_train:n_train+gap+n_test] (гейт future⊆train — по
   построению); модели без канала — честный warning, exog не передаётся.
   Реестр: var supports_future_features=True (гейт «supports_future_features
   требует input_kind=...» расширен на multivariate — VARX); vecm=False —
   registry fail-closed отвергает future_features. FeaturePlan-интеграция:
   kind=exogenous, role future_known/static — в varx_columns (VAR) и в
   cohort-контракт.
4. **Контракт (`multivariate_contract.py`, добавления без изменения
   сертифицированных поверхностей)** — `vecm_stability(coefficients,
   coint_rank)`: устойчивость VECM = РОВНО coint_rank единичных корней
   companion уровневого VAR-представления (|λ|=1 ± 1e-8), остальные строго
   < 1; `multivariate_cohort_contract(+exogenous_future_known=(),
   exogenous_static=())`: честная feature_contract (policy="varx_future_known"),
   дефолт — бит-в-бит прежний (policy="none").
5. **Диагностика движка** — модель-специфичный блок multivariate_diagnostics:
   "var" (как в 132) для VAR; "vecm" (k_ar_diff, coint_rank, rank_selection,
   deterministic_terms, alpha, nobs, vecm_stability) для VECM;
   companion_stability-ключ делит семантику; +exogenous-блок (names/n_exog).

### Интеграция

- `model_impls/__init__.py`: экспорт run_vecm_backtest; `routers/models.py`:
  dispatch "vecm" (gate 17 моделей проходит); `rules/modeling.yaml`: vecm
  param_space (k_ar_diff [1,2,3] x deterministic [ci,co] = 6 trials);
  Dockerfile: VECM-проба (release-гейт 17-й модели; неособые sin-данные —
  линейный ряд даёт сингулярную ML-оценку).

### TDD

RED: 3 новых файла — ModuleNotFoundError (apps.api.model_impls.vecm),
ImportError (vecm_stability, execute_vector_tuning_plan_with_artifacts).
GREEN: 63 unit-кейса (test_vecm_adapter 27: bounded params/fold-local ранг/
auto-ранг-0 отказ/fixed-rank/нативная cross-equation связь/alpha-семантика/
детерминизм; test_vector_tuning 15: trials на тех же folds/честный argmin/
полный векторный артефакт/failures/all-fail/усечение/yaml grid 6;
test_varx_exogenous 21: informative-X/fail-closed длин и NaN/движок-срезы/
vecm-отказ exog/registry гейты/cohort-контракт/vecm_stability) + 1 API-кейс
(test_vecm_runs_vector_session_tuning_with_fold_local_rank: tuning →
promoted vector backtest → session-артефакты → повторный backtest с
tuned-параметрами).

### Честные обновления сертификационных тестов (как 15→16 в Task 132)

- `test_modeling_mvp_certification.py`: CERTIFIED_MODEL_IDS + vecm (17),
  тест переименован sixteen→seventeen; PRODUCTION_TUNING + var/vecm (11).
- `test_model_execution_contract.py`: CERTIFIED_IDS + vecm; MULTIVARIATE_IDS
  {var, vecm} + MULTIVARIATE_EXOG_IDS {var} (supports_future_features).
- `test_backtesting_engine.py`: одномерный OOF-cohort исключает var И vecm
  (векторные исполнители; 15 одномерных).
- `test_model_readiness_candidates.py`: n_series=1 — catalog-only 7,
  blocked 2 (vecm блокируется F01 как var); короткий профиль — blocked 7.
- `test_var_integration_paths.py`: dispatch-цепочка 16 → 17.
- `test_models_backtest_real.py`: dispatch-реестр 17 ключей.

### Верификация

- Полный pytest: **1912 passed / 0 failed**, snapshots 3/3; арифметика:
  1848 (74654a0) + 63 unit + 1 API = 1912 (сходится ровно).
- compileall OK; `from apps.api.main import app` OK; pip check PASS.
- Dockerfile-проба VECM воспроизведена локально (VECM executable OK).
- E2E каталога: «Подключённые» = 17; «Многомерные» = var + vecm, оба ready
  с [backtest, tune, diagnostics] (VECM с cointegrated-профилем — RECOMMENDED
  по P05); фронтенд не менялся — MODEL_FAMILIES уже содержит "multivariate".

### Границы Task 133

- Векторный tuning job-контур (resumable model_jobs для векторных моделей)
  наследует общий механизм — при необходимости отдельный честный разбор.
- VECM с exog (VECMX) не подключён: yaml supports_exogenous: false —
  сознательное методологическое решение (коинтеграционная спецификация без
  внешних регрессоров); потребность — отдельная постановка.
- Rank "auto" — trace-тест signif=0.05 на train-срезе fold'а; выбор уровня
  значимости не параметризуется (fail-closed конвенция платформы).

---

## Task w/n — Паттерн "Ведём исследователя за руку": кнопка приглашения к следующему модулю (вкладка «Загрузка»)

### Синхронизация

По прямому указанию тимлида выполнен `git reset --hard` до `bfe11cf`
("Task 129 — LightGBM: production vertical slice"). Backend не тронут этой
задачей — чисто frontend, `packages/ui`.

### Что сделано

Спроектирован переиспользуемый паттерн платформы: приглашение перейти
к следующему модулю пайплайна внизу степпера текущей вкладки, после
прохождения её пайплайна. Реализован как отдельный компонент
`packages/ui/components/StepperNextModuleButton.tsx` (props: `label`,
`href`) — не inline-разметка внутри `TsAnalysisUpload.tsx`, чтобы остальные
степперы платформы (Валидация, Предобработка, EDA, Моделирование,
Прогнозирование) могли переиспользовать его без дублирования стилей —
именно то, о чём просил тимлид ("спроектируй паттерн для всех степперов").

Стилевой контракт — все 5 пунктов ТЗ проверены по факту существующих
классов в `TsAnalysisUpload.tsx`/`tailwind-preset.ts`, не угаданы:
1. Размер — идентичен кнопкам степпера (`rounded-md border px-3 py-2 text-sm`).
2. Отделение от последней кнопки степпера ("Качество") — обёртка с
   `border-t border-neutral-200` (светло-серая черта).
3. Рамка — как у кнопок степпера (`rounded-md border`), но фон — статичный
   пастельный `bg-brand-light/50`, тот же токен, что уже красит окно
   «Описание» (`bg-brand-light` = `#E8EAF6` — подтверждено в
   `packages/ui/tailwind-preset.ts`), а не рамка самого окна «Описание»
   (там `rounded-lg`, что не было бы «такой же рамкой, как у степпера»).
4. Наведение — `hover:bg-brand hover:text-white` (`brand` = `#2E3192`,
   фирменный индиго логотипа, тот же токен).
5. Переход — `next/link` на `href="/validation"`.

Подключён в `TsAnalysisUpload.tsx`: рендерится последним элементом внутри
того же `flex flex-col gap-1.5`-контейнера степпера, сразу после `.map()`
по `STOPS` — виден при любой активной остановке (не только на «Качество»,
в отличие от уже существующей контекстной ссылки «Перейти к Валидации» в
правой колонке "руль и педали", которая осталась как есть — два разных
элемента с разным назначением, не дублируют друг друга: правая — контекстная
подсказка внутри содержимого остановки «Качество», новая — навигационный
переход уровня всего модуля).

### Тесты

- `StepperNextModuleButton.test.tsx` (новый, 5 тестов): текст/`href`,
  статичный пастельный фон по умолчанию (не индиго), hover-классы индиго/
  белого текста присутствуют, но не применены по умолчанию, рамка
  идентична кнопкам степпера, разделитель `border-t` в обёртке.
- `TsAnalysisUpload.test.tsx` (+1 тест): кнопка видна на дефолтной
  остановке «Превью датасета» (не только на «Качество», где уже существует
  контекстная ссылка с похожим, но не идентичным текстом — регистр «В»/«в»
  различает их, проверено явно, чтобы не столкнуться с двумя совпадающими
  ссылками на остановке «Качество»).

### Проверки

- `packages/ui/components/{StepperNextModuleButton,TsAnalysisUpload}.test.tsx`: 31/31 PASS.
- Полный frontend regression: **91/91 suites, 837/837 tests PASS**.
- `typecheck:all`: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, 13/13 страниц, First Load JS
  469 kB (не изменился — компонент маленький, тот же shared chunk).
  Временный шим `next/font/google` применён, собран, немедленно отменён —
  `git diff` после отката пуст.
- Backend не запускался — задача не затрагивает `apps/api`.

### Изменённые/новые файлы

Новые:
- `packages/ui/components/StepperNextModuleButton.tsx`
- `packages/ui/components/StepperNextModuleButton.test.tsx`

Изменённые:
- `packages/ui/components/TsAnalysisUpload.tsx`
- `packages/ui/components/TsAnalysisUpload.test.tsx`

### Что осталось за рамками этой задачи (осознанно)

- Подключение того же `StepperNextModuleButton` к степперам Валидации/
  Предобработки/EDA/Моделирования/Прогнозирования — компонент готов к
  переиспользованию (`label`/`href` — единственные входы), но по прямому
  ТЗ реализовано только для «Загрузки»; остальные вкладки — по отдельной
  команде тимлида.
- Условная видимость кнопки только после прохождения всего пайплайна
  модуля (философия "После прохождения... логично пригласить") — ТЗ (5
  пунктов) не содержало явного требования скрывать кнопку до завершения;
  реализовано как всегда видимая внизу степпера, решение о gate явно не
  запрашивалось — не введено самостоятельно, чтобы не расширять scope без
  подтверждения.

---

## Сертификация Task 132 (VAR) и Task 133 (VECM + vector tuning + VARX): аудит

Дата: 2026-09-10. Синхронизация: `main @ 081b9fc` («Task 133 — VECM + vector
tuning + exogenous channel VARX», включает e6f6726 Task 132 и hotfix 74654a0).
Аудит реализации коллеги; commit/push агентом не выполнялись (запрет
AGENTS.md соблюдён). Рабочая копия после всех мутационных проб верифицирована
(git status чист, 229/229 профильных тестов green).

### Методология аудита

(1) Постановки docs/modeling_task_list.md::Task 132/133 (включая общую ноту
серии: fold-local порядок лага VAR / ранг Йохансена только на train-fold;
нативный многомерный прогноз statsmodels, НЕ цикл одномерных ARIMA) разобраны
на пункты и прослежены до кода И до связывающих тестов; (2) построчная
рекогносцировка surfaces: model_impls/var.py, model_impls/vecm.py,
векторный движок backtesting.py::run_vector_backtest_plan (+3 агрегатора),
modeling_tuning.py (vector tuning), routers/modeling_session.py
(_multivariate_vector_context + обе endpoint-ветки), model_execution.py
(декларации реестра), multivariate_contract.py (vecm_stability,
cohort+exogenous), rules/modeling.yaml; (3) воспроизведение базлайна в чистом
окружении (после восстановления дрейфа МОЕЙ среды: prophet/statsforecast/
xgboost/lightgbm/catboost/PyWavelets/pandera/syrupy/ruptures/fakeredis);
(4) НЕЗАВИСИМЫЕ oracle-сверки на собственных данных/сидах
(audit_scripts/oracle_audit_132_133.py); (5) собственные мутационные пробы,
НЕ пересекающиеся с тремя мутациями коллеги; (6) сверка сертификационной
поверхности и честности гейтов.

### Воспроизведение базлайна

- Полный pytest: **1912 passed / 0 failed, snapshots 3/3** — ровно как
  заявлено; арифметика 1848 (74654a0) + 63 unit + 1 API = 1912 сходится.
- Гейт консистентности dispatch vs registry честно падает без зависимостей
  (RuntimeError на импорте) — спроектированный fail-closed, после установки
  пакетов проходит; production backtest = 17 (var/vecm включены), tuning =
  11, dispatch-ключи == реестр (17==17).
- Фронтенд не затронут ни одним из трёх коммитов (0 файлов packages/,
  apps/standalone, apps/embedded) — jest-регрессия невозможна по построению;
  claims о MODEL_FAMILIES подтверждены чтением packages/ui/lib/modeling.ts.

### Независимые oracle-сверки (18 проверок, мои данные/сиды)

- VAR: прогноз/интервалы/остатки бит-в-бит == VAR.fit().forecast_interval
  (atol 1e-12); is_stable == VARResults.is_stable; порядок лага ==
  select_order на том же срезе.
- VARX: прогноз/интервалы бит-в-бит == VAR(exog=...).fit().
  forecast_interval(..., exog_future=...).
- VECM: auto-ранг == select_coint_rank(trace, 0.05) и согласован с прямым
  coint_johansen; прогноз/интервалы бит-в-бит == VECMResults.predict;
  var_rep-блоки == statsmodels.
- Движок: OOF-прогнозы каждого fold'а == ручному вызову адаптера на ТОЧНОМ
  префиксе [:n_train] с отбрасыванием gap-шагов (бит-в-бит, gap=2) —
  префикс-дисциплина и gap-семантика доказаны независимо.
- Метрики: mase_scale == mean|diff(train)| каждой серии; per-series MAE
  ручная == движок; scaled_loss == mean(per-series MASE).
- Итог: **17/18 PASS**; единственный FAIL — C6, см. дефект ниже.

### Мутационные пробы аудита (6, применялись и откатывались; git diff-верификация)

1. M1 (движок, утечка related-рядов: полная история вместо префикса) —
   ПОЙМАНА: test_leakage_probe_identical_prefix_identical_fold_one +
   test_oof_points_bind_to_exact_system_values (2 отказа).
2. M2 (VECM: тихий fallback coint_rank=1 вместо честного отказа при ранге 0) —
   ПОЙМАНА: test_auto_rank_zero_is_honest_error_without_var_fallback.
3. M3 (движок: OOF-окно без отбрасывания gap, predicted_matrix[:n_test]) —
   **ВЫЖИЛА полный набор (1912 passed с мутацией)**: все привязки прогнозов
   к шагам адаптера в тестах коллеги исполняются при gap=0 (мутация
   вырождается), а binding-тест фиксирует только actual, не predicted.
   Код движка сам корректен (мой oracle D бит-в-бит ловит мутацию в обоих
   folds) — это ПРОБЕЛ ПОКРЫТИЯ, а не дефект поведения.
4. M4 (tuning: argmax вместо argmin лучшего trial) — **ВЫЖИЛА**
   test_vector_tuning + API (56 passed с мутацией): фикстура
   {maxlags:[4,8]×aic} вырождена — AIC выбирает одинаковый порядок, RMSE
   trials бит-в-бит равны (проверено: 0.752499 == 0.752499), argmin==argmax.
   На острой сетке [1,8]×[None] мутация переворачивает best_trial (1 вместо
   0) — путь живой, код корректен (аргмин верифицирован), слаба фикстура.
5. M5 (агрегат RMSSE: взвешенное среднее вместо корня-из-взвешенных-квадратов)
   — ПОЙМАНА: test_aggregate_mase_is_test_size_weighted_across_folds.
6. M6 (vecm_stability: замена на ТЕОРЕТИЧЕСКИ КОРРЕКТНЫЙ инвариант K−r) —
   2 теста коллеги ПАДАЮТ (test_identity_blocks_two_unit_roots,
   test_stationary_companion_rank_zero) — доказано, что юнит-тесты кодируют
   ту же ошибочную семантику, что и реализация (оракул-слепое пятно).

### Критическая находка: vecm_stability инвертирует спектральный инвариант VECM

Реализация (multivariate_contract.py::vecm_stability, Task 133) требует
«РОВНО coint_rank единичных корней» companion уровневого VAR-представления.
Теория (Granger-представление / Lütkepohl 2005 гл. 6): y_t = (I+αβ′)y_{t-1}+…
с rank(α)=rank(β)=r даёт спектр I+αβ′ = {1+μ_i}, где μ_i — собственные
значения αβ′ ранга r: ровно K−r НУЛЕВЫХ μ дают единичные корни (общие
стохастические тренды), r ненулевых обязаны лежать строго внутри круга.
**Число единичных корней = K − r, а не r.** Правило коллеги совпадает с
теорией только при K=2, r=1 — все их fixture-примеры именно K=2.
Эмпирика (audit_scripts/vecm_stability_theory_check.py, 4 сценария): K=3
ранг-1 VECM (учебный случай) — companion даёт 2 единичных корня: движок
помечает корректно специфицированную модель is_stable=False (ложная тревога
в multivariate_diagnostics всех K≥3-прогонов); rank=K (стационарные уровни)
— 0 корней, движок снова is_stable=False; их тест eye(2)+rank2 признаётся
«stable», хотя комбинация внутренне противоречива (rank 2 = стационарные
уровни ⇒ 0 корней, а identity-спектр имеет 2). Оракул C6 на реальном
коинтегрированном K=3-фите зафиксировал тот же провал. Поражённая
поверхность: advisory-блок multivariate_diagnostics.vecm.{is_stable,
n_unit_roots} (session-артефакты/карточка); прогнозы, метрики, cohort,
tuning-выбор НЕ затронуты (доказано оракулами A–E).

### Дополнительные замечания (не блокирующие)

1. Белый шум VECM в движке: lag_order = metadata.get("lag_order") or 0 — у
   VECM ключа нет ⇒ nlags=3 и fitted_var_order=0 при любом k_ar_diff (вплоть
   до 12): df Portmanteau завышен (K²·3 вместо K²·(nlags−p)), окно 3 лага
   может быть меньше порядка модели. Docstring system_white_noise_diagnostics
   прямо рекомендует передачу порядка для VECM — движок следует ему только
   для VAR. Advisory-only (available-блок), на метрики не влияет.
2. Тест-фикстура best_trial (M4) вырождена: сетку стоит сделать
   различимой ([1,8]×[None] либо фиксированные p).
3. Для M3 стоит добавить прямой binding: при gap>0 OOF predicted шага h ==
   адаптеру forecast[gap+h] (мой oracle D — готовый шаблон).

### Покрытие постановки

Task 132 — все пункты подтверждены кодом И тестами: fold-local порядок лага
(адаптер видит только префикс; движок требует непрерывный префикс fail-closed;
оракул A5 + leakage-проба), нативный forecast_interval (не ARIMA-цикл:
cross-equation тест + мои оракулы A1/A2), fail-closed без fallback,
реестр v2 multivariate, векторный движок (vector OOF, per-series метрики
с паритетом формул, scaled loss all-or-none, persistence-baseline на тех же
folds, fold-local диагностика), честный n_series, dispatch/yaml/Dockerfile.
Task 133 — все пункты КРОМЕ диагностики устойчивости подтверждены:
fold-local ранг Йохансена (оракулы C1/C2, M2-запрет fallback, ранг 0 — честный
отказ), нативный VECMResults.predict с интервалами (оракулы C3/C4), векторный
tuning на тех же EDA-folds с общим контрактом (MAX_TRIALS/усечение/failures),
VARX-канал (оракулы B1/B2; fail-closed длины/NaN/ключи; VECM честно
предупреждает и не потребляет; реестр-гейты), cohort+exogenous
(policy varx_future_known, дефолт бит-в-бит), честные обновления
сертификационных гейтов 15→16→17 и tuning 9→11 (сверено).

### Вердикт

**Task 132 (VAR): сертифицирована, реализация отличная.** Все требования
постановки выполнены, поведение доказано независимыми оракулами, мутационный
контур чувствителен (M1, M5 пойманы), базлайн воспроизводится 1912/0/3.
Замечания M3 (gap-binding пробел покрытия) — косметика, сертификации не
препятствуют.

**Task 133 (VECM + vector tuning + VARX): не может быть сертифицирована в
текущем виде**, потому что vecm_stability инвертирует спектральный инвариант
VECM (ровно coint_rank единичных корней вместо K − coint_rank): системно
неверная диагностика устойчивости для стандартного случая K≥3 (и для
rank=K), при этом юнит-тесты кодируют ту же ошибочную семантику (M6) и
работлог фиксирует ошибку как дизайнерское достижение. Остальные поверхности
Task 133 (fold-local ранг, нативный прогноз, tuning, VARX, cohort) —
отличного качества (17/18 оракулов, единственный FAIL и есть этот дефект).
Путь пересертификации мал: (1) инвариант n_unit_roots == K − coint_rank
(при r=K ⇒ 0) с вынесением K из формы матриц; (2) исправить два юнит-теста
TestVecmStability; (3) добавить K=3 оракул-привязку к спектру var_rep
statsmodels; (4) опционально — NLags-учёт порядка VECM в white-noise.
После этого пересертификация формальна.
