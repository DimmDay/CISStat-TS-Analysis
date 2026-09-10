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

---

## Task 134 — Volatility Objective Contract (каркас GARCH/EGARCH, Tasks 135–136)

Дата: 2026-09-10. Синхронизация до **05eb467** (принятый Task 133 коллеги
`081b9fc` + worklog_summary; базлайн **1912 passed** / 0 failed, snapshots 3/3).
Постановка docs/modeling_task_list.md::Task 134. Инфраструктурная
задача-контракт (уровень Task 131), НЕ новая модель: адаптеры GARCH/EGARCH
подключаются в Tasks 135–136 поверх контракта. CERTIFIED_IDS/каталог-гейты
не менялись: **17/24 production-моделей — без сдвига**.

### Дизайн-рекогносцировка (эмпирическая, до тестов)

Probe-скрипт (scripts/task134_probe.py) зафиксировал факты, на которых
построен дизайн: (1) ручная реализация ARCH-LM (Engle 1982,
LM = T̃·R² из регрессии z² на лаги 1..q с константой, T̃ = T − q) ПОБИТОВО
совпадает с официальной statsmodels het_arch при nlags 1/3/5/12
(rtol 1e-10) — оракул-сверка; (2) QLIKE в robust-форме Паттона (2011)
mean(log σ̂² + σ²/σ̂²) отличается от классической формы
σ²/σ̂² − log(σ²/σ̂²) − 1 ровно на константу mean(log σ²) + 1 (проверено
численно: 0.00e+00) — ранжирование-эквивалентность, устойчивость к
зашумлённому proxy и допустимость σ² = 0; (3) Ljung-Box на квадратах
(McLeod-Li) работоспособен; (4) на симулированном GARCH(1,1) сырые
остатки дают reject по LB-квадратам/ARCH-LM и НЕ дают по LB-уровням,
на стандартизованных z = ε/√σ² все три теста не отвергают (устойчиво
по seeds 7/11/23/42); (5) **обнаружена дыра**: run_backtest_plan передаёт
objective=plan.objective в реестр, а с injected-predictor вообще минует
реестр — volatility-план был бы исполнен одномерным движком с level-
метриками (MAE/RMSE) на дисперсии.

### Реализация (2 поверхности + декларация)

1. **`apps/api/volatility_contract.py` (NEW, ~730 строк)** — контракт
   волатильности, зеркало multivariate_contract.py (Task 131), независим
   от HTTP/session-кода, НЕ импортирует backtesting.py.  Шесть пунктов
   постановки:
   - *Явное преобразование цены в returns без скрытого выбора*:
     `price_to_returns(prices, *, method)` — method ОБЯЗАТЕЛЬНЫЙ keyword
     {log, simple}: вызов без него невозможен by construction (TypeError),
     неизвестный метод отклоняется; fail-closed на конечность/строгую
     положительность цен.  `VolatilityTarget` (frozen dataclass, зеркало
     EndogenousSystem): анти-тампер — stored returns обязаны
     воспроизводиться из цен заявленным методом бит-в-бит; timestamps
     выровнены с ЦЕНАМИ (returns[i] реализуется между t[i] и t[i+1]);
     MIN_RETURNS_OBSERVATIONS = 20; head/train_slice/test_slice;
     сетка — переиспользование сертифицированного
     validate_regular_grid Task 131 (единый источник истины).
     Преобразование — точечно каузальная функция пары (P_{t-1}, P_t),
     параметры не оценивает: однократный расчёт на полной истории
     leakage-safe (в отличие от Box-Cox lambda) — задокументировано.
   - *Цель — условная дисперсия*: `realized_variance_proxy(returns, *,
     proxy)` — proxy обязательный keyword {squared_returns}; в
     cohort-контракте target_kind="conditional_variance"; схема
     OOF-точки движка (VOLATILITY_OOF_POINT_KEYS) сохраняет
     сертифицированные ключи fold/horizon_step/index/label/actual/
     predicted/residual, где actual = realized proxy тест-окна —
     совместимость с comparison/selection-машинерией по построению.
   - *Primary metric QLIKE + дополнительные ошибки по proxy*:
     `compute_volatility_metrics(realized, predicted, *, proxy)` —
     QLIKE (robust-форма Паттона, primary), RMSE/MAE в шкале дисперсии;
     прогноз σ̂² ≤ 0 — fail-closed отказ БЕЗ clamp-подмен; отрицательный
     realized — нарушение контракта proxy; proxy декларируется в каждой
     точке вычисления (тихая подмена между моделями невозможна).
     `aggregate_volatility_metrics(folds)` — взвешивание по n_test
     (конвенция движка): qlike/mae — пул точек, rmse — корень из
     взвешенного MSE (не среднее RMSE); согласованность proxy между
     folds — all-or-none.
   - *Собственный volatility baseline*: `volatility_naive_baseline(
     returns, horizon, *, decay=0.94)` — EWMA (RiskMetrics), fold-local
     (аргумент — train-префикс), seed = train-дисперсия (ddof=1),
     рекурсия σ²_{t+1} = λσ²_t + (1−λ)r²_t, плоское продление горизонта
     (конвенция RiskMetrics, без скрытой реверсии — она вводила бы
     скрытый гиперпараметр); decay ∈ (0,1) валидируется и фиксируется в
     cohort-контракте; вырожденный train (все returns нулевые) — честный
     отказ.
   - *Диагностика standardized/squared residuals*:
     `standardized_residual_diagnostics(z, *, nlags, alpha=0.05)` —
     Ljung-Box на z + Ljung-Box на z² (McLeod-Li) + ARCH-LM (Engle 1982,
     ручная реализация с оракул-паритетом het_arch); вырожденные
     остатки (нулевая дисперсия) — отказ, а не фиктивный «идеальный
     фит».  `volatility_clustering_evidence(returns, *, nlags, alpha)` —
     ARCH-LM на самих returns: a priori-свидетельство кластеризации
     (источник честного data.has_volatility_clustering при подключении
     GARCH; в Task 134 профиль данных НЕ меняется — граница задачи).
   - *Полностью отдельный cohort*: `volatility_cohort_contract(*,
     target_column, fingerprint, returns_method, n_returns,
     seasonal_period, decay)` — objective="volatility", metric_policy
     primary="qlike", metrics [qlike, rmse, mae], блоки volatility
     (target_kind/returns_method/realized_proxy/oof_point_keys/baseline)
     и target (contract_version/source_column/returns_method);
     returns_method — обязательный keyword, cohort фиксирует явный выбор.
2. **Гейт одномерного движка (`backtesting.py::run_backtest_plan`,
   +17 строк)** — fail-closed отказ volatility-планов ДО любого
   исполнения (включая injected-predictor путь, минующий реестр):
   «target волатильности — условная дисперсия, а не уровень ряда;
   level-метрики (MAE/RMSE/MASE) на ней запрещены».  Закрывает
   обнаруженную дыру; исполнение volatility-планов — volatility-движок
   (Tasks 135–136).  build_backtest_plan objective="volatility" уже
   принимал (проверено probe) — план строим, исполнять движком уровня
   запрещено; разделение подкреплено существующими гейтами: реестр v2
   (request.objective == definition.objective), aligned_oof (смешение
   objective → ComparisonContractError) — привязаны regression-тестами.
3. **`rules/modeling.yaml`** — секция metrics.volatility: qlike
   (use_in_ranking: true, primary volatility-cohort, undefined_when
   σ̂² ≤ 0, robust-форма Паттона с пояснением эквивалентности) +
   realized_rmse/realized_mae (отчётность, не ранжирование) с
   комментариями о разделении cohort.  Загрузчик ModelingSpec
   игнорирует неизвестные ключи metrics (проверено) — backward
   compatible.

### TDD

RED: tests/unit/test_volatility_contract.py (66 кейсов, 10 классов) —
ModuleNotFoundError apps.api.volatility_contract; после реализации
модуля оставался ровно 1 RED (гейт движка: injected-predictor +
volatility-план исполнялся с level-метриками).  Оракул-тесты:
ARCH-LM == het_arch бит-в-бит (rtol 1e-10); QLIKE == классическая форма
+ константа; EWMA == независимая рекурсия теста; LB-squared/ARCH-LM
отвергают на сырых GARCH-остатках и НЕ отвергают на стандартизованных
(смысл стандартизации связан тестом).  GREEN: 66/66.

### Мутационная самопроверка (5 мутаций, применялись и откатывались)

(1) method получает default "log" → тесты «без скрытого выбора» падают;
(2) гейт движка удалён → test_univariate_engine_rejects_volatility_plan
падает; (3) QLIKE подменён на −mean(log σ̂²) → ranking-эквивалентность
падает; (4) ARCH-LM T вместо T̃ = T − q → оракул-паритет падает;
(5) EWMA seed = 0 вместо train-дисперсии → рекурсионный оракул падает.
Урок процесса: git checkout не восстанавливает НЕотслеживаемые файлы —
для них мутации откатывались вручную (восстановлено, GREEN подтверждён).

### Верификация

- Полный pytest: **1978 passed / 0 failed**, snapshots 3/3; арифметика:
  1912 (05eb467) + 66 unit = 1978 (сходится ровно).
- compileall OK; `from apps.api.main import app` OK; pip check PASS.
- E2E-смоук (scripts/task134_e2e_smoke.py): каталог 17 «Подключённых»
  без сдвига; в реестре нет objective="volatility"; volatility-план
  отвергнут движком, level-план исполнен бит-в-бит прежней семантики;
  мини-пайплайн контракта: 121 цена → 120 returns (method=log) →
  EWMA-baseline → QLIKE (baseline 1.374 лучше плохого прогноза 1.768) →
  агрегация folds → диагностика стандартизованных остатков (reject=False
  на корректной стандартизации) → cohort_id vol ≠ cohort_id level.

### Границы Task 134 (задел Tasks 135–136)

- Volatility-движок (fold-loop с QLIKE-метриками, EWMA-baseline на тех
  же folds и OOF-точками realized/predicted) подключается с первым
  исполнителем (GARCH, Task 135) — по прецеденту Task 131→132.
- Профиль данных: has_volatility_clustering/domain захардкожены
  (modeling_workflow.py) — честная проводка volatility_clustering_evidence
  в профиль и P04/D04-гейты — при подключении GARCH.
- Selection v2 принимает primary_metric только mae/rmse — расширение на
  qlike (ранжирование внутри volatility-cohort) — с первым
  volatility-моделями; сейчас fail-closed («Selection v2 поддерживает
  primary_metric mae/rmse»), тихий fallback на RMSE запрещён.
- GARCHX (exogenous-канал GARCH) не декларирован: feature_contract
  policy="none"; потребность — отдельная постановка (прецедент VARX в
  Task 133).

### Изменённые/новые файлы

Новые:
- apps/api/volatility_contract.py (~730 строк)
- tests/unit/test_volatility_contract.py (66 кейсов)

Изменённые:
- apps/api/backtesting.py (+17: fail-closed гейт volatility-планов)
- rules/modeling.yaml (metrics.volatility: qlike/realized_rmse/realized_mae)

---

## Пересертификация Task 133 (VECM + vector tuning + VARX): исправление дефектов аудита

Дата: 2026-09-10. База: main @ 081b9fc, рабочая копия без коммитов/пуша
(запрет AGENTS.md). Все четыре пункта пути пересертификации из аудита
выполнены по TDD-циклу (RED → код → GREEN), мутационная верификация
фиксов — 6/6 проб пойманы, полный набор 1922 passed / 0 failed /
3 snapshots.

### Изменения кода (исправления дефектов)

1. `apps/api/multivariate_contract.py::vecm_stability` — устранена
   инверсия спектрального инварианта: устойчивость VECM теперь требует
   РОВНО `K − coint_rank` единичных корней companion уровневого
   VAR-представления (спектральная теорема Granger-представления;
   Johansen 1995, Lütkepohl 2005 гл. 6), а не `coint_rank`. Размерность
   K вынесена из формы матриц (base["n_series"]), добавлен ключ
   `expected_unit_roots` и fail-closed отказ при `coint_rank > K`.
   При r=K ⇒ 0 единичных корней (стационарные уровни); прежняя
   семантика совпадала с теорией только при K=2r (все fixture-примеры
   коллеги были K=2, r=1).
2. `apps/api/multivariate_contract.py::system_white_noise_diagnostics` —
   новый optional-параметр `rank_adjustment` (int ≥ 0, дефолт 0 =
   бит-в-бит legacy VAR): df = K²·(nlags − p) − rank_adjustment;
   fail-closed при df < 1 и при rank_adjustment < 0. Для VECM движок
   передаёт K·coint_rank — достигнут ТОЧНЫЙ паритет df с официальной
   statsmodels VECMResults.test_whiteness (закреплён оракул-тестом).
3. `apps/api/backtesting.py::run_vector_backtest_plan` — VECM-ветка
   white-noise учитывает фактический порядок модели: окно
   nlags = max(k_ar_diff+2, min(8, k_ar_diff+4)) строго выше уровневого
   порядка k_ar_diff+1 (прежде — всегда 3, меньше порядка при
   k_ar_diff ≥ 3), fitted_var_order = k_ar_diff (прежде 0),
   rank_adjustment = K·coint_rank. VAR-ветка бит-в-бит прежняя.
4. Комментарии семантики исправлены в backtesting.py и
   model_execution.py (реестр vecm: «ровно K − coint_rank единичных
   корней» + df-поправка ранга).

### Изменения тестов (TDD)

- `tests/unit/test_varx_exogenous.py::TestVecmStability` — переписан на
  корректную семантику: два прежде ошибочных теста (eye(2)+rank2
  «stable», diag(0.5,0.3)+rank0 «stable») теперь кодируют честные
  противоречия (unstable); добавлены K=3-кейсы (r=1 ⇒ 2 единичных
  корня — устойчиво; лишний корень — нестабильно), fail-closed rank>K
  и **постоянный оракул** `test_statsmodels_vecm_oracle_k3_rank1`:
  реальный фит statsmodels VECM на коинтегрированной системе K=3,
  r=1 (DGP: y1 — блуждание, y2 = y1 + шум, y3 — независимое блуждание;
  ранг подтверждён select_coint_rank trace 0.05) ⇒ n_unit_roots == 2 ==
  K−r, is_stable, неранговая часть спектра строго внутри круга +
  регрессионный якорь n_unit_roots != coint_rank против возврата
  инвертированной семантики (audit C6 теперь закрыт навсегда).
- `TestVecmEngineWhiteNoise` (2 теста) — движковый VECM white-noise:
  окно/порядок/df привязаны к формуле K²·(nlags−p) − K·r.
- `tests/unit/test_multivariate_contract.py` — df-паритет с
  VECMResults.test_whiteness на реальном фите (+ проверка, что без
  поправки df завышен ровно на K·r), fail-closed df<1, отказ
  отрицательного rank_adjustment.
- `tests/unit/test_var_backtest.py::test_oof_predictions_bind_to_
  adapter_forecast_with_gap` — прямой binding (audit M3): при gap=2
  OOF-прогноз шага h бит-в-бит == forecast[gap+h] адаптера на точном
  train-префиксе.
- `tests/unit/test_vector_tuning.py::test_var_grid_from_bounded_space`
  — сетка сделана различимой [4,8]×[None] вместо вырожденной
  [4,8]×["aic"] (audit M4), + ассерт неравенства RMSE trials.
- Докстринги test_varx_exogenous.py синхронизированы с новой семантикой.

### TDD и мутационная верификация

- RED подтверждён: 13 новых тестов падали против дефектного кода
  (KeyError expected_unit_roots, инвертированный is_stable, TypeError
  rank_adjustment, df=12 вместо 14), 2 hardening-теста (M3/M4)
  проходили и до кода — движок/тюнинг были корректны, дефект был в
  семантике диагностики и в качестве фикстур.
- GREEN: полный pytest **1922 passed / 0 failed, snapshots 3/3**
  (базлайн 1912 + 10 новых тестов; арифметика сходится: TestVecmStability
  4→8, +2 движковых white-noise, +3 контрактных rank_adjustment,
  +1 gap-binding).
- Мутационные пробы фиксов (применялись и откатывались, git-верификация
  отсутствия маркеров): (1) обратная инверсия инварианта — ПОЙМАНА
  (4 отказа); (2) игнор rank_adjustment в df — ПОЙМАНА (3);
  (3) legacy-окно white-noise для VECM — ПОЙМАНА (2); (4) снятие
  fail-closed rank>K — ПОЙМАНА (1); (5) replay M3 (без отбрасывания
  gap) — ПОЙМАНА новым binding-тестом (2), прежде проба выживала;
  (6) replay M4 (argmax) — ПОЙМАНА обострённой фикстурой (1), прежде
  проба выживала.
- Frontend не затронут (0 файлов packages/, apps/standalone,
  apps/embedded) — jest-регрессия невозможна по построению.
- Отладочные заметки: seed 11 K=3-DGP — пограничный для trace-теста
  (5.49 против крит. 3.84 при r≤2) — оракул зафиксирован на seed 13
  (ранг 1 подтверждён); companion порядка k_ar_diff+1 несёт K·(p−1)
  сдвиговых нулей — асsert неранговой части спектра это учитывает.

### Вердикт пересертификации

**Task 133 (VECM + vector tuning + exogenous channel VARX):
сертифицирована, реализация отличная.** Все требования постановки
выполнены; единственный блокирующий дефект аудита (инверсия
спектрального инварианта vecm_stability) устранён вместе с кодировавшей
ошибку парой юнит-тестов, дополнительный white-noise дефект движка
закрыт с точным df-паритетом statsmodels, оба мутационных пробела
покрытия (M3 gap-binding, M4 различимая сетка) закрыты. Поведение
доказано постоянным K=3-оракулом против statsmodels, мутационный
контур чувствителен (6/6), полный набор 1922/0/3 воспроизводим.
Изменения ожидают решения тимлида (commit/push агентом не выполнялись).

---

## Task w/n — Декоративный фон главной страницы (мягкие волны)

### Контекст

По присланному скриншоту-макету («Вариант 1. Волны» — мягкий диагональный
градиент белый→голубой + 2-3 перекрывающихся слоя волн, лёгкая глубина без
отвлечения от контента) реализован фон главной страницы standalone.
Синхронизация на новый коммит не запрашивалась — задача продолжает работу
на `bfe11cf`, поверх уже несданного в git (не закоммиченного) Task 131a.

### Что сделано

`packages/ui/components/HomeWavesBackground.tsx` — новый декоративный
компонент: диагональный CSS-градиент (`from-white ... to-brand-light/70`)
+ инлайн SVG с двумя перекрывающимися path-волнами (`fill-brand-light/45`,
`fill-brand/[0.08]`).

**Canvas сознательно не использован**, хотя был предложен как ориентир на
"минимальный вес": для статичного (не анимированного) рисунка SVG даёt тот
же нулевой сетевой вес (компилируется в тот же JS-чанк, не отдельный файл),
но без JS-исполнения в рантайме и без пересчёта на ресайз, который
потребовался бы canvas — SVG строго не тяжелее и практически всегда легче
по факту рантайм-стоимости. Растровое изображение (PNG/JPG экспорт
скриншота) тоже не использован — отдельный сетевой запрос, тяжелее любого
из двух других вариантов.

Прозрачность слоёв подобрана с учётом уже существующей вёрстки главной
страницы (проверено чтением кода, не предположено): карточки-маршруты
Hero уже полупрозрачны (`bg-brand-light/60`, `RouteCard.tsx`) — волны
заметно светлее, чтобы не спорить с ними; карточки блока «Возможности»
непрозрачны (`bg-white`/`bg-neutral-100`, `HomeCapabilities.tsx`) — просто
«плавают» на фоне в промежутках, без визуального конфликта.

Подключение — `apps/standalone/app/page.tsx`: обёртка `relative isolate`,
фон — первым child'ом абсолютно (`absolute inset-0 -z-10`), контент
(`HomeHero`+`HomeCapabilities`) — во вложенном `relative` div, во весь
рост страницы (не только Hero) — покрывает всю главную, включая длинный
скролл `HomeCapabilities`. Экспортирован из `packages/ui/index.ts`.
**Только standalone** — та же причина, что и у `HomeHero`/`HomeCapabilities`
(в embedded пользователь уже внутри портала, маркетинговый фон не нужен).

### Тесты

`HomeWavesBackground.test.tsx` (новый, 4 теста): чисто декоративный слой
(`aria-hidden`, `pointer-events-none`), абсолютное позиционирование
(`absolute inset-0 -z-10`, явно НЕ `fixed`), использует фирменные токены
(`brand-light`/`brand`, не произвольная палитра), инлайн SVG с двумя
path-слоями (явно НЕ `<img>`/`<canvas>`).

### Проверки

- `HomeWavesBackground.test.tsx` + `HomeHero.test.tsx` + `HomeCapabilities.test.tsx`: 34/34 PASS.
- Полный frontend regression: **92/92 suites, 841/841 tests PASS**.
- `typecheck:all`: embedded PASS (компонент экспортирован из общего пакета,
  но не используется — конфликтов нет), standalone PASS.
- Production build embedded/standalone: PASS, 13/13 страниц. Вес главной
  страницы (`/`) — **538 B, не изменился** относительно билда до этой
  задачи — прямое подтверждение "минимального веса" (SVG внутри уже
  существующего JS-чанка, ни одного нового байта на сеть). Временный шим
  `next/font/google` применён, собран, немедленно отменён — `git diff`
  после отката пуст.

### Изменённые/новые файлы

Новые:
- `packages/ui/components/HomeWavesBackground.tsx`
- `packages/ui/components/HomeWavesBackground.test.tsx`

Изменённые:
- `apps/standalone/app/page.tsx`
- `packages/ui/index.ts`

### Что осталось за рамками этой задачи (осознанно)

- Волны спроектированы как приближение к стилю скриншота (мягкие
  перекрывающиеся S-кривые, диагональный градиент, палитра `brand`), а не
  пиксель-в-пиксель копия — сам скриншот помечен как макет варианта («5
  точек-вариантов» на нём), не финальный асcет для прямого экспорта.
  При необходимости точной подгонки кривых под референс — дело правки
  двух `d="..."` path'ов в `HomeWavesBackground.tsx`, без изменения
  остальной архитектуры.
- Не применено к embedded — по той же логике, что и остальной контент
  главной страницы standalone (маркетинговый/исследовательский контекст,
  не нужен внутри портала).

---

## Task 135 — GARCH (первый исполнитель volatility-контракта Task 134)

Дата: 2026-09-10. Синхронизация до **b3b6534** (принятые Task 134
`56613cc` + пересертификация Task 133 `bd887b2` + фон главной страницы;
базлайн **1988 passed** / 0 failed, snapshots 3/3). Постановка
docs/modeling_task_list.md::Task 135 + задел «Границы Task 134»
(worklog3.md::Task 134): volatility-движок подключается с первым
исполнителем по прецеденту Task 131→132. CERTIFIED_IDS/каталог-гейты
сдвинуты честно: **18/24 production-моделей** (17 + GARCH).

### Дизайн-рекогносцировка (эмпирическая, до тестов)

Probe-скрипт (scripts/task135_probe.py) зафиксировал факты, на которых
построен дизайн: (1) arch 8.0: MLE (SLSQP) детерминирован -- fit+аналити-
ческий forecast бит-идентичны между запусками; (2) оракул-паритет:
fc[0] = omega + alpha*eps^2_T + beta*sigma2_T (фильтрованное состояние
conditional_volatility), fc[h] = omega + (alpha+beta)*fc[h-1] (ожидание
ненаблюдаемого eps^2 замещается условной дисперсией) -- rtol 1e-8;
(3) параметр forecast random_state отвечает только за method="bootstrap";
для method="simulation" RNG -- distribution.simulate (global np.random) =>
детерминизм интервалов -- через ЯВНЫЙ rng-callable с сидированным
numpy-генератором (проверено: одинаковый seed => бит-идентичные пути,
разный => разные при том же точечном прогнозе); (4) rescale=None
(дефолт arch!) выдал DataScaleWarning на returns ~1e-3 => адаптер
фиксирует rescale=False ЯВНО (зеркало «без скрытого выбора» Task 134);
(5) вырожденный вход (все returns нулевые): arch молча возвращает
convergence_flag=4, прогноз sigma2=0 и NaN в std_resid -- три
независимых fail-closed слоя адаптера ловят каждый; (6) i.i.d. УРОВЕНЬ
(не цены!) при дифференцировании даёт MA(1), квадраты которого
автокоррелированы => ARCH-LM честно детектирует «кластеризацию» --
для профиля данных эталон отсутствия кластеризации -- случайное
блуждание, а не белый шум уровня (найдено при отладке теста профиля).

### Реализация (адаптер + движок + 8 поверхностей интеграции)

1. **`apps/api/model_impls/garch.py` (NEW, ~330 строк)** -- нативный
   GARCH(p,q) пакета arch, первый исполнитель контракта Task 134
   (прецедент var.py Task 132): fold-local (адаптер получает ТОЛЬКО
   train-срез returns; полная история недостижима), target -- условная
   дисперсия (аналитический forecast arch); rescale=False (без скрытого
   масштабирования); fail-closed: несошедшийся MLE (convergence_flag != 0),
   sigma2 <= 0 (без clamp-подмен), NaN/Inf вход и не-конечные
   стандартизованные остатки -- честный отказ fold'а.  Интервалы --
   симуляционные квантили путей дисперсии (alpha 0.01/0.05/0.10, 1000
   путей, сидированный rng => детерминизм).  Bounded params: p,q (1..3),
   mean (Constant/Zero), dist (normal/t).  Метаданные для движка:
   params/persistence/is_covariance_stationary/convergence_flag/aic/bic/
   std_residuals/conditional_volatility.  run_garch_backtest -- честный
   отказ однорядного synthetic-эндпоинта (как VAR/VECM/ML).
2. **Volatility-движок (`backtesting.py::run_volatility_backtest_plan`,
   ~250 строк)** -- зеркало run_vector_backtest_plan на контракте
   Task 134: гейт «только objective=volatility» (плюс input_kind=
   univariate реестра); fold-local train-префикс returns через
   VolatilityTarget; OOF-точки -- VOLATILITY_OOF_POINT_KEYS с
   actual = realized proxy (квадрат return тест-окна), predicted =
   прогноз дисперсии, label = timestamps[i+1] (return i реализуется
   между t[i] и t[i+1]); метрики -- compute_volatility_metrics
   (QLIKE primary, fail-closed) + агрегация aggregate_volatility_
   metrics (взвешивание по n_test, rmse = корень из взвешенного MSE);
   baseline -- EWMA RiskMetrics (volatility_naive_baseline) на ТЕХ ЖЕ
   folds, decay читается из cohort-контракта (fail-closed: подмена
   baseline между моделями невозможна); диагностика fold'а --
   standardized_residual_diagnostics (LB/LB^2/ARCH-LM по остаткам
   адаптера, nlags=8) + a priori volatility_clustering_evidence
   train-среза + GARCH-блок MLE.
3. **Реестр v2 (`model_execution.py`)**: `_garch_executor` (плоский
   forecast = дисперсия; lower/upper = симуляционные квантили; полный
   payload в metadata) + запись model_id="garch", family_id="volatility",
   adapter_id="arch-garch", engine="arch", required_packages=("arch",),
   actions=_TUNABLE, objective="volatility", input_kind="univariate",
   dependency_group="volatility", supports_prediction_intervals=True,
   deterministic=True.  GARCHX не декларирован (Task 134:
   feature_contract policy="none"; прецедент VARX -- отдельная
   постановка).
4. **Session-контур (`routers/modeling_session.py`)**: returns_method
   (log/simple) -- ЯВНЫЙ обязательный параметр ModelingBacktestRequest и
   ModelingTuneRequest для volatility-моделей (скрытый выбор запрещён
   контрактом; fail-closed 422 без него); `_volatility_context` --
   prices = сырой source-ряд (преобразования уровня НЕ применяются --
   warning честно декларирует), валидационная стратегия ПЕРЕСОБИРАЕТСЯ
   на пространстве returns (n_prices - 1; та же geometry horizon/gap/
   splits/train_window), cohort = volatility_cohort_contract; dispatch
   backtest -> run_volatility_backtest_plan, tune ->
   execute_volatility_tuning_plan_with_artifacts; tune-metric Literal +
   VALID_SESSION_TUNING_METRICS += qlike (для level-моделей qlike=None =>
   честный отказ trial'а, привязано тестом mape-отказа на дисперсии);
   selection-evaluation Literal += qlike.
5. **Tuning (`modeling_tuning.py`)**: execute_volatility_tuning_trial/
   _plan_with_artifacts -- зеркало векторного (та же prepare_tuning_grid/
   finalize; каждый trial -- полный volatility backtest; best = argmin
   метрики).
6. **Selection v2 (`modeling_selection.py`)**: primary_metric расширен
   {"mae","rmse"} -> {"mae","rmse","qlike"} (задел Task 134 закрыт);
   смешение objective невозможно -- aligned_oof отвергает cohort'ы с
   разными objective раньше selection (сертифицировано Task 131).
7. **Матрица применимости (`eda_model_matrix.py`)**: честный
   task-критерий для production volatility-моделей под task="forecast":
   attention (не блок) с honest note «прогноз условной дисперсии
   доходностей target-ряда; cohort objective='volatility' не смешивается
   с level-моделями в comparison» -- точное зеркало overrides Task 132
   для multivariate; catalog-only EGARCH (Task 136) остаётся blocked.
8. **Честный профиль данных (`modeling_workflow.py`)**:
   has_volatility_clustering больше не захардкожен False --
   volatility_clustering_profile(values) через контракт (log-returns,
   выбор method ОБЪЯВЛЕН в коде/доке; degenerate-ряды -- honest
   available=False).  P04/D04-гейты читают настоящий флаг.
9. **Декларации**: rules/modeling.yaml -- garch param_space
   p/q [1,2] x mean [Constant,Zero] x dist [normal,t] = 16 trials
   (<= 64) с комментарием о fold-local MLE/rescale/QLIKE; apps/api/
   Dockerfile -- release-проба _garch_fit_predict на симулированном
   GARCH-процессе (exec-цикл внутри python -c; verified via sh).
10. **Схемы (`schemas.py`)**: BacktestMetrics.qlike (Optional, primary
    volatility-cohort); BacktestFoldResult.volatility_baseline/
    volatility_diagnostics; BacktestResponse.volatility_baseline --
    артефакты не теряются при Pydantic-сериализации (привязано тестом).

### TDD

RED: tests/unit/test_garch_adapter.py (24), tests/unit/
test_volatility_engine.py (11: гейты/leakage-spy реестра/OOF-контракт/
EWMA-оракул/агрегация/диагностика/честный отказ короткого fold'а),
tests/unit/test_garch_integration_paths.py (21: реестр/dispatch/readiness
18/схемы/матрица/selection/профиль/yaml/Dockerfile), tests/api/
test_garch_session.py (5: returns_method-гейт/полный backtest/tuning
qlike/честный отказ mape/изоляция objective в aligned_oof) -- все RED
по правильным причинам (ModuleNotFoundError/NotRegistered/AttributeError).
GREEN: 62/62.  Оракул-тесты: аналитический forecast == ручная GARCH(1,1)
рекурсия (seed = фильтрованное состояние arch, rtol 1e-8); детерминизм
бит-в-бит (точечный прогноз + интервалы при равном seed); EWMA-baseline ==
независимая рекурсия контракта; паритет params с прямым rescale=False
фитом + отсутствие DataScaleWarning.

### Мутационная самопроверка (5 мутаций, применялись и откатывались)

(1) rescale=False -> None: пережила первый тест (arch репортит params на
исходной шкале!) -- тест УСИЛЕН привязкой отсутствия DataScaleWarning,
мутация убита; (2) гейт «только volatility-планы» удалён из движка ->
test_rejects_non_volatility_plan падает; (3) GARCH_MIN_TRAIN 20 -> 10:
пережила тест (константа самосогласована) -- добавлен явный тест
равенства MIN_RETURNS_OBSERVATIONS == 20, мутация убита; (4) decay
движка захардкожен 0.94 вместо cohort-контракта -> EWMA-оракул (0.90)
падает; (5) OOF-label timestamps[index] вместо [index+1] ->
test_oof_points_contract падает.  Урок: константно-параметризованные
тесты связывают только относительную согласованность -- абсолютные
инварианты контракта требуют явных привязок.

### Верификация

- Полный pytest: **2049 passed / 0 failed**, snapshots 3/3; арифметика:
  1988 (b3b6534) + 62 новых - 0 = 2049 (сходится ровно).
- Обновлены честные count-гейты сертификации 17 -> 18 (7 тестов:
  _BACKTEST_IMPLEMENTATIONS/CERTIFIED_IDS/certified-scope/dispatch-chain/
  candidates-stats/tbats-explain/engine-cohort; в engine-cohort привязан
  отказ level-движка для garch).
- compileall OK; `from apps.api.main import app` OK; pip check PASS.
- E2E-смоук (scripts/task135_e2e_smoke.py): каталог 18 connected;
  гейт level-движка на месте; волатильный пайплайн:
  160 цен -> 159 returns (method=log) -> GARCH(1,1) fold-local MLE ->
  QLIKE GARCH -9.7356 ЛУЧШЕ EWMA-baseline -9.6149 (модель даёт реальную
  прогнозную ценность на симулированном процессе) -> изоляция cohort ->
  диагностика (persistence=0.900, cov_stationary=True).
- Dockerfile-проба исполнена локально через sh: 'GARCH executable OK'.

### Границы Task 135 (задел Task 136)

- EGARCH (leverage/asymmetry) -- тот же volatility-движок переиспользуется
  бит-в-бит: новый адаптер + запись реестра + yaml (прецедент пары
  var/vecm в одном движке).
- Диагностика session-эндпоинта (_diagnose) считает OOF-остатки в шкале
  дисперсии generic-путём; fold-local standardized_residual_diagnostics
  (контрактная, честная) уже в volatility_diagnostics каждого fold'а.
- Comparison внутри volatility-cohort: weighted_score (mae/rmse-базе)
  считается generic-машинерией; каноническое ранжирование cohort'а --
  qlike (selection primary_metric).  QLIKE-центричный comparison --
  отдельная постановка, если потребуется.
- GARCHX (exogenous-канал) -- отдельная постановка (прецедент VARX
  Task 133), yaml supports_exogenous: true декларирован каталогом,
  feature_contract движка -- policy="none".

### Изменённые/новые файлы

Новые:
- apps/api/model_impls/garch.py (~330 строк)
- tests/unit/test_garch_adapter.py (25 кейсов)
- tests/unit/test_volatility_engine.py (11 кейсов)
- tests/unit/test_garch_integration_paths.py (21 кейс)
- tests/api/test_garch_session.py (5 кейсов)
- scripts/task135_probe.py, scripts/task135_e2e_smoke.py

Изменённые:
- apps/api/backtesting.py (+~250: run_volatility_backtest_plan)
- apps/api/model_execution.py (_garch_executor + запись реестра)
- apps/api/routers/models.py (dispatch garch)
- apps/api/model_impls/__init__.py (экспорт run_garch_backtest)
- apps/api/routers/modeling_session.py (returns_method, _volatility_context, dispatch, Literals)
- apps/api/modeling_tuning.py (qlike + execute_volatility_tuning_*)
- apps/api/modeling_selection.py (primary_metric qlike)
- apps/api/eda_model_matrix.py (task-критерий volatility-семейства)
- apps/api/modeling_workflow.py (volatility_clustering_profile)
- apps/api/schemas.py (qlike, volatility_baseline/diagnostics)
- rules/modeling.yaml (param_space garch)
- apps/api/Dockerfile (release-проба GARCH)
- tests/*: 6 count-гейтов 17 -> 18 (test_models_backtest_real,
  test_backtesting_engine, test_model_execution_contract,
  test_model_readiness_candidates, test_modeling_mvp_certification,
  test_var_integration_paths)

---

## Task 136 -- EGARCH (второй исполнитель volatility-контракта; leverage/asymmetry)

Дата: 2026-09-10. Синхронизация до **51ee33d** (принятый Task 135 GARCH;
базлайн **2049 passed** / 0 failed -- задокументирован в записи Task 135
этого же коммита). Постановка docs/modeling_task_list.md::Task 136:
«EGARCH дополнительно проверяет leverage/asymmetry. Прогнозы выполняются
через официальный arch-контур». Задел «Границы Task 135» исполнен
дословно: volatility-движок Task 135 переиспользуется, новый адаптер +
запись реестра + yaml (прецедент пары var/vecm). CERTIFIED_IDS сдвинуты
честно: **19/24 production-моделей** (18 + EGARCH).

### Дизайн-рекогносцировка (эмпирическая, до тестов)

Probe-скрипт (scripts/task136_probe.py) зафиксировал факты дизайна:
(1) arch 8.0 жёстко запрещает analytic-прогноз EGARCH за горизонтом 1
(«Analytic forecasts not available for horizon > 1» -- ValueError из
_check_forecasting_method) => точечный прогноз -- официальный
СИМУЛЯЦИОННЫЙ контур; (2) variance.values симуляционного прогноза ==
среднее путей (probe fact 5) -- arch сам определяет точечный прогноз
EGARCH как MC-оценку E[sigma2_{T+h}|F_T] (оптимальный прогноз под
QLIKE); (3) h=1 путей ВЫРОЖДЕНЫ (не зависят от симулируемых инноваций)
=> симуляционное среднее h=1 бит-точно равно analytic h=1 == ручной
рекурсии EGARCH(1,1,1) из фильтрованного состояния (rtol 1e-8, rel err
3.45e-16); (4) MC-ошибка среднего на h>=2 при 4000 путях < 0.6% для
персистентных процессов (sims 4000 vs 50000, runtime ~0.01-0.02с);
(5) MLE (SLSQP) детерминирован; сидированный rng => бит-идентичные пути
(разный seed => разные пути при тех же MLE-параметрах); (6) arch НЕ
предоставляет fitted.persistence для EGARCH => честный аналог --
сумма beta-коэффициентов (AR(q) по log-дисперсии; стационарность
log-дисперсии <=> sum(beta) < 1); (7) rescale=None может «молча»
масштабировать вход => rescale=False ЯВНО (зеркало Task 135);
(8) leverage восстанавливается: на сериях с gamma_true=-0.15 фит даёт
gamma<0 на всех проверенных seed; (9) **EGARCH-специфика сходимости**:
scipy-бюджет SLSQP по умолчанию (maxiter=100) недостаточен -- срез-207
смоук-серии: flag=9 «Iteration limit reached» при llf=-228.90, с ЯВНЫМ
бюджетом maxiter=1000 -- flag=0 при llf=-222.58 (лучше!), runtime
~0.08с; то же поведение воспроизводится unit-оракулом (премиса:
дефолтный фит не сходится; адаптер сходится к flag=0 с llf не хуже).

### Реализация (адаптер + движок переиспользован + поверхности)

1. **`apps/api/model_impls/egarch.py` (NEW, ~450 строк)** -- нативный
   EGARCH(p,o,q) пакета arch, второй исполнитель контракта Task 134.
   Fold-local (только train-срез returns), target -- условная дисперсия;
   точечный прогноз -- variance.values официального симуляционного
   контура (метод -- simulation, 4000 путей, сидированный rng);
   интервалы -- квантили ТЕХ ЖЕ путей (alpha 0.01/0.05/0.10);
   rescale=False; ЯВНЫЙ бюджет сходимости EGARCH_MAXITER=1000 через
   официальный fit-options arch (тот же MLE, честная EGARCH-специфика,
   привязано оракул-тестом на патологическом срезе); fail-closed:
   несошедшийся MLE (даже при бюджете), sigma2 <= 0, NaN/Inf вход,
   не-конечные стандартизованные остатки, короткая история (>= 20
   returns).  **Ядро Task 136 -- asymmetry-блок**: gamma-коэффициенты /
   std_errors / Wald p-values из официального фита, leverage_direction
   (negative/positive/mixed из знаковой структуры), asymmetry_
   significant (порог 0.05), honest note.  Bounded params: p/o/q (1..3,
   o >= 1 -- модель ОБЯЗАНА параметризовать асимметрию), mean
   (Constant/Zero), dist (normal/t).  run_egarch_backtest -- честный
   отказ однорядного synthetic-эндпоинта (как GARCH/VAR/VECM/ML).
2. **Реестр v2 (`model_execution.py`)**: _egarch_executor (forecast =
   дисперсия; lower/upper = квантили; полный payload + asymmetry в
   metadata) + запись model_id="egarch", family_id="volatility",
   adapter_id="arch-egarch", engine="arch", required_packages=("arch",),
   actions=_TUNABLE, objective="volatility", input_kind="univariate",
   dependency_group="volatility", supports_prediction_intervals=True,
   deterministic=True.  Обоим volatility-executor'ам добавлен adapter_id
   в metadata (самоиндентификация блока диагностики; для garch --
   аддитивно, "arch-garch").
3. **Volatility-движок (`backtesting.py`)**: ЛОГИКА НЕ ТРОНУТА; ключ
   блока диагностики теперь = model_id (для garch ответ бит-идентичен
   Task 135: тот же ключ "garch"), блок дополнен adapter_id/asymmetry
   (для GARCH asymmetry=None -- модель асимметрию не параметризует).
4. **Dispatch (`routers/models.py`)**: _BACKTEST_IMPLEMENTATIONS +=
   "egarch"; consistency-gate реестр<->dispatch сошёлся (19==19).
5. **`model_impls/__init__.py`**: экспорт run_egarch_backtest.
6. **Декларации**: rules/modeling.yaml -- имя "EGARCH(p,o,q)" (o теперь
   явный параметр), param_space p/o/q [1,2] x mean [Constant,Zero] x
   dist [normal,t] = 32 trials (<= 64) с комментарием о fold-local MLE,
   o >= 1, бюджете сходимости, симуляционном контуре; apps/api/Dockerfile
   -- release-проба _egarch_fit_predict на симулированном
   EGARCH-процессе с leverage (проверена локально через sh: 'EGARCH
   executable OK'; ассертит и asymmetry-блок).
7. **Матрица применимости (`eda_model_matrix.py`)**: production-критерий
   выводит готовность из PRODUCTION_BACKTEST_MODEL_IDS -- EGARCH
   разблокировался автоматически (attention, honest note); комментарий
   обновлён (catalog-only блок снят).

### TDD

RED: tests/unit/test_egarch_adapter.py (32: параметры/границы, оракул
h=1 против ручной рекурсии, паритет с официальным variance.values,
бит-детерминизм, seed меняет симуляцию но не MLE, alpha-ширина
интервалов, rescale=False без DataScaleWarning, mean=Zero/dist=t/
о-порядки, asymmetry-блок (структура/знак leverage/обратный полюс/
старшие порядки), fail-closed (вырожденный вход, короткая история,
NaN/Inf, horizon<=0, оракул бюджета сходимости на патологическом
срезе), честный отказ legacy-эндпоинта, минимум истории == 20),
tests/unit/test_egarch_integration_paths.py (14: контракт реестра,
гейты objective/train_features/related_series, executor+asymmetry,
dispatch/readiness 19, пара garch+egarch в одном движке, матрица
(egarch runnable/short-history), yaml-границы, Dockerfile),
tests/api/test_egarch_session.py (4: returns_method-гейт, полный
session backtest с egarch-блоком и asymmetry, tuning qlike, честный
отказ mape) -- RED по правильным причинам (ModuleNotFoundError/
NotRegistered/KeyError).  GREEN: все.
Оракул-тесты: симуляционное среднее h=1 == ручная EGARCH-рекурсия
(rtol 1e-8); точечный прогноз == variance.values официального контура
(бит-паритет с прямым arch-фитом при том же seed); патологический
срез: дефолтный фит flag!=0 => адаптер flag=0 с llf >= премисы
(детерминизм сходимости от seed не зависит).

### Мутационная самопроверка (5 мутаций, применялись и откатывались)

(1) EGARCH_MAXITER 1000 -> 100: оракул патологического среза падает
(адаптер честно отказывает на срезе, который обязан осилить); (2) гейт
o >= 1 ослаблен до o >= 0: test_o_must_be_strictly_positive падает;
(3) persistence = sum(beta+alpha) вместо sum(beta): тест метаданных
падает; (4) ключ блока диагностики захардкожен "garch": egarch session
тест падает (KeyError 'egarch'); (5) leverage_direction "negative" ->
"positive": тест восстановления leverage падает.  Все мутации убиты,
рабочее дерево восстановлено байт-в-байт.

### Верификация

- Полный pytest (чанками, каждый -- отдельный прогон): tests/unit
  **1376 passed** (snapshots 3/3), tests/api **623 passed**, остальные
  (root/integration/legacy) **100 passed**; итого **2099 passed / 0
  failed**.  Арифметика: 2049 (51ee33d) + 50 новых (32 адаптер + 14
  интеграция + 4 session) - 0 изменённых = 2099 -- сходится ровно.
- Обновлены честные count-гейты сертификации 18 -> 19 (7 файлов:
  test_model_execution_contract CERTIFIED_IDS/VOLATILITY_IDS,
  test_modeling_mvp_certification CERTIFIED_MODEL_IDS+tuning-set,
  test_models_backtest_real dispatch-set, test_backtesting_engine
  cohort-exclusions, test_var_integration_paths import-chain probe,
  test_garch_integration_paths count+матрица,
  test_model_readiness_candidates catalog-статистика: catalog-only 6->5,
  blocked 3->4 на macro-профиле / 8->9 на короткой истории).
- compileall OK; `from apps.api.main import app` OK; pip check PASS.
- E2E-смоук (scripts/task136_e2e_smoke.py): каталог 19 connected;
  гейт level-движка на месте; волатильный пайплайн: 220 цен -> 219
  returns (method=log) -> EGARCH(1,1,1) fold-local MLE -> QLIKE
  EGARCH 0.7189; asymmetry: gamma=-0.1288, p=0.00, direction=negative,
  significant=True; beta-persistence=0.986, cov_stationary=True;
  cohort-ранжирование честное: EWMA > GARCH > EGARCH на этой серии
  (EGARCH не объявлен «лучшим» -- ранжирование только по данным);
  изоляция cohort на месте.
- Dockerfile-проба исполнена локально через sh: 'EGARCH executable OK'.

### Границы Task 136 (что осознанно НЕ сделано)

- EGARCHX (exogenous-канал) -- не декларирован (прецедент GARCHX/VARX:
  отдельная постановка); yaml supports_exogenous не объявлен.
- Сравнение GARCH vs EGARCH внутри volatility-cohort -- честное
  QLIKE-ранжирование работает (см. смоук (6)); QLIKE-центричный
  comparison-UI -- отдельная постановка (задел Task 135 сохранён).
- Тюнинг симуляционных путей (INTERVAL_SIMULATIONS) и бюджета
  (EGARCH_MAXITER) -- константы адаптера с фиксированной honest-декла-
  рацией; вынос в param_space не выполнялся (не гиперпараметры модели).
- Нейросетевые volatility-модели -- вне скоупа (Neural -- Task 137+).

### Изменённые/новые файлы

Новые:
- apps/api/model_impls/egarch.py (~450 строк)
- tests/unit/test_egarch_adapter.py (32 кейса)
- tests/unit/test_egarch_integration_paths.py (14 кейсов)
- tests/api/test_egarch_session.py (4 кейса)
- scripts/task136_probe.py, scripts/task136_e2e_smoke.py

Изменённые:
- apps/api/model_execution.py (_egarch_executor + запись реестра +
  adapter_id в metadata volatility-executor'ов)
- apps/api/backtesting.py (ключ блока диагностики = model_id,
  adapter_id/asymmetry в блоке; логика движка не тронута)
- apps/api/routers/models.py (dispatch egarch)
- apps/api/model_impls/__init__.py (экспорт run_egarch_backtest)
- apps/api/eda_model_matrix.py (комментарий; логика -- из реестра)
- rules/modeling.yaml (param_space egarch + имя EGARCH(p,o,q))
- apps/api/Dockerfile (release-проба EGARCH)
- tests/*: 7 count-гейтов 18 -> 19 (test_models_backtest_real,
  test_backtesting_engine, test_model_execution_contract,
  test_model_readiness_candidates, test_modeling_mvp_certification,
  test_var_integration_paths, test_garch_integration_paths)

---

## Task 134 + Task 135 — Независимая сертификация (аудит исполненных задач)

Дата: 2026-09-10. Аудитор: senior-разработчик (исполнитель задач 132/133/
131a и Task w/n-серии). Объект аудита: Task 134 `56613cc` (Volatility
Objective Contract: `apps/api/volatility_contract.py` 730 строк + гейт
движка +17 + yaml-метрики) и Task 135 `51ee33d` (GARCH: адаптер ~330
строк + volatility-движок ~250 + 8 поверхностей интеграции). База аудита:
чистое дерево `main @ 51ee33d`, границы diff `05eb467..56613cc` и
`b3b6534..51ee33d` сверены (обе задачи backend-only, фронтенд не затронут;
все удаления Task 135 -- честные count-гейты 17->18).

### Методология аудита

(1) Построчный аудит кода против постановки docs/modeling_task_list.md и
записей worklog3.md; (2) воспроизведение окружения с нуля (свежий venv:
Python 3.12.14, arch 8.0.0, statsmodels 0.15.0, pandas 2.3.3, numpy
2.5.3 -- ЗАМЕТНО НОВЕЕ окружения исполнителя: оракул-паритеты обязаны
держаться на других версиях, и они держатся); (3) полная backend-
регрессия; (4) независимые оракул-пробы на СВОИХ данных и сидах (скрипт
scripts/cert134135_oracles.py, сиды 20260910/424242/777001/31415/271828/
161803/555000/606060/707070/808080/909090..93 -- ни один не совпадает с
сидами исполнителя); (5) мутационные пробы (скрипт
scripts/cert134135_mutations.py, 16 мутаций, каждая apply -> RED-check ->
revert -> git-diff верификация чистоты).

### Воспроизведение базлайна

Полная backend-регрессия пофайловым прогоном (монолитный прогон в среде
аудитора убивался OOM: 4GB RAM без swap; пофайлово с OMP/BLAS-потоками=1
-- стабильно): **2050 passed / 0 failed / 0 skipped**. Арифметика:
1988 (b3b6534) + 62 новых Task 135 (25 адаптер + 11 движок + 21
integration + 5 session) = **2050**. В записи Task 135 («Верификация»)
указано «2049 passed» и «1988 + 62 - 0 = 2049 (сходится ровно)» --
арифметическая описка (сумма равна 2050); на суть вердикта не влияет
(все тесты зелёные), но отчётную строку стоит поправить при следующей
правке worklog силами исполнителя.

### Независимые оракул-сверки (93/93 PASS, мои данные/сиды)

- Task 134: price_to_returns log/simple == ручным формулам бит-в-бит;
  method -- обязательный keyword (TypeError без него); неположительные/
  NaN/короткие цены отказаны. Анти-тампер VolatilityTarget ловит подмену
  returns на 1e-12; head()/train_slice геометрия точна.
- QLIKE robust-форма Паттона: разность с классической == mean(log rv)+1
  (max отклонение 8.88e-16 на 5 случайных сетках прогнозов);
  ранжирование-эквивалентность подтверждена. Fail-closed: sv<=0,
  realized<0, неизвестный/непереданный proxy -- всё отказано, clamp
  отсутствует.
- Агрегация: qlike/mae -- взвешенные по n_test; rmse == корень
  взвешенного MSE (поймана ловушка: 2.22486 vs mean-RMSE 2.0); подмена
  proxy между folds -- all-or-none отказ.
- EWMA RiskMetrics: seed = var(ddof=1), рекурсия и плоский горизонт ==
  независимой рекурсии на decay 0.94/0.90/0.97; вырожденный train
  отказан; decay вне (0,1) отказан.
- ARCH-LM: ручная реализация == statsmodels het_arch БИТ-В-БИТ на 10
  комбинациях (2 ряда x nlags {1,3,5,8,12}; worst rel 1.27e-13 --
  жёстче заявленного rtol 1e-10) на statsmodels 0.15.0. LB/LB^2 ==
  прямому acorr_ljungbox. Вырожденные остатки отказаны.
- volatility_clustering_evidence: белый шум p=0.23 (не отвергает),
  симулированный GARCH(1,1) p=7.8e-54 (отвергает) -- тест различает
  DGP корректно.
- Cohort-контракт: objective/primary/policy/блоки volatility/target
  полны; returns_method -- обязательный keyword.
- Реестр/гейты: describe("garch") полный (objective=volatility,
  input_kind=univariate, engine=arch, deterministic, intervals);
  PRODUCTION_BACKTEST_MODEL_IDS == 18 с garch; одномерный движок
  отказывает volatility-план ДО исполнения (гейт Task 134).
- GARCH: аналитическая рекурсия fc[0]=omega+alpha*eps^2_T+beta*sigma2_T,
  fc[h]=omega+(alpha+beta)*fc[h-1] == arch analytic == адаптеру
  (rel 1.5e-16); params == прямому фиту rescale=False; persistence ==
  sum(alpha)+sum(beta); детерминизм интервалов бит-в-бит при равном
  seed, точечный прогноз от seed не зависит; DataScaleWarning
  отсутствует на мелкой шкале (подобрана эмпирически: scale=0.5
  триггерит warning при rescale=None и сходится при rescale=False;
  на более мелких шкалах MLE закономерно не сходится и адаптер
  отказывает fail-closed -- поведение контракта, не дефект).
- E2E конвейер (_volatility_context -> run_volatility_backtest_plan,
  мои 500 цен/499 returns, 3 fold'а expanding): train -- непрерывный
  префикс; адаптер видел ровно n_train наблюдений (arch nobs);
  OOF: actual == квадрат return тест-окна, label == timestamps[index+1],
  residual == round(a-p,12); baseline == независимой EWMA-рекурсии на
  train-префиксе с cohort-decay; evaluation_scale == 'log'; level-метрики
  None; диагностика полна.
- Каталог/прод: modeling.yaml garch param_space 2x2x2x2=16 (<=64);
  EGARCH отсутствует в реестре (граница Task 136); прод-каталог
  ts-standalone.vercel.app: 18/24 ready, garch присутствует.

### Статистика GARCH vs EWMA (репорт, не гейт)

Контракт не обещает победы GARCH над EWMA в каждом розыгрыше. Мои панели
(по 4 реализации, QLIKE, GARCH(1,1)-DGP): (a) T=500/30 OOF-точек -- шум
(wins 2/4, mean -0.024); (b) T=900/48 точек -- GARCH выигрывает 4/4
(mean +0.056); (c) persistence 0.98 (EWMA(0.94) заведомо misspecified) --
4/4 (mean +0.032). Вывод: конвейер корректен; на коротких сериях
различие статистически неотличимо (ожидаемо по литературе), baseline-
машерия честная (доказано побитовой рекурсией).

### Мутационные пробы (16, применялись и откатывались; git diff-верификация)

Убиты тестами (12): M1 скрытый default метода доходностей; M2 подмена
QLIKE; M3 ARCH-LM T вместо T-tilde; M4 seed EWMA=0.01; M5 удаление гейта
движка; M6 rmse=sqrt->weighted-MSE; M8 MIN_RETURNS 20->10 (абсолютная
привязка test_min_train_aligns_with_contract_minimum в тесте АДАПТЕРА);
M9 rescale=False->None; M11 GARCH_MIN_TRAIN 20->10; M12 захардкоженный
decay=0.94 мимо cohort-контракта; M13 OOF label timestamps[index] вместо
[index+1]; M14 несидированный rng интервалов.

Выжившие (4) -- разобраны по одному:
- M7 анти-тампер array_equal->allclose: ЕДИНСТВЕННЫЙ реальный пробел
  тестового покрытия: ни один тест проекта не конструирует
  VolatilityTarget с чужими returns (фабрика всегда пересчитывает
  returns сама). Рантайм строг (мой оракул O2b поймал 1e-12), но
  регрессию array_equal->allclose тесты не поймают. Рекомендация
  исполнителю: dedicated тест-привязка (не блокирует сертификацию).
- M10 отключение гейта convergence_flag: слоистая защита -- тест
  degenerate-входа декларирует OR-семантику («обязан отказать на ЛЮБОЙ
  из причин»), sigma2<=0 слой ловит тот же вход. Поведение fail-closed
  сохранено; изоляция слоя сходимости потребовала бы mock (опционально).
- M15 отключение первого 422-гейта returns_method в backtest: двойной
  гейт -- whitelist-проверка `not in {"log","simple"}` тоже отклоняет
  None с 422 (detail содержит returns_method). Контракт сохранён
  избыточностью; безвредно.
- M16 clamp прогноза sigma2: третий слой защиты; недостижим при активном
  первом (flag=4 -> отказ до прогноза). Поведение сохранено; опционально
  mock-изоляция.

Урок мутационной методологии (продолжение линии Task 135 «константные
тесты связывают относительность»): цель мутации обязана включать ВСЕ
файлы с привязками инварианта -- M8 выглядел пробелом, пока прогон не
покрыл тест адаптера, где живёт абсолютная привязка == 20.

### Покрытие постановки

Task 134 -- все 6 пунктов подтверждены кодом и оракулами (явное
price->returns; target == условная дисперсия; QLIKE primary + proxy-
метрики; собственный EWMA-baseline; диагностика LB/LB^2/ARCH-LM;
полностью отдельный cohort) + гейт одномерного движка + yaml-секция
метрик. Task 135 -- все поверхности подтверждены: адаптер (fold-local,
rescale=False, fail-closed x4 слоя, сидированные интервалы), движок
(гейты, OOF-контракт, baseline cohort'а, диагностика), реестр v2,
session (returns_method 422, пересборка стратегии на returns,
preprocessing-предупреждение об уровне), tuning (qlike + честный отказ
mape), selection (qlike), матрица (attention, EGARCH blocked), честный
профиль has_volatility_clustering, схемы (qlike/volatility_baseline/
volatility_diagnostics), yaml (16 trials), Dockerfile-проба, count-гейты
17->18 (6 файлов).

### Замечания (не блокируют сертификацию)

1. (документация) Off-by-one «2049» vs фактических 2050 в записи Task
   135 «Верификация» -- поправить исполнителю при следующей правке.
2. (тесты) Анти-тампер VolatilityTarget без тест-привязки в проекте
   (M7) -- добавить dedicated тест на 1e-12-подмену.
3. (тесты, опционально) изоляция отдельных слоёв fail-closed (M10/M16)
   и первого 422-гейта (M15) -- mock-тесты, приоритет низкий.
4. (наблюдение к Task 136+) короткие train-срезы (порядка 60 returns)
   закономерно дают несходимость MLE GARCH (flag=4) -- fold честно
   отказывается (паритет с level/vector-движками). Не дефект; можно
   заранее отражать в применимости/профиле данных.

### Вердикт

**CERTIFIED.** Task 134 и Task 135 соответствуют постановкам;
методологические обещания (leakage-safety, fail-closed без clamp,
явные keyword-выборы, отдельный cohort, честный baseline, детерминизм)
подтверждены независимо: 93/93 оракул-проб на своих сидах, 12/16 мутаций
убиты, 4 выживших разобраны (1 пробел тест-привязки -- рекомендация,
3 -- слоистая защита/избыточность), 2050/2050 регрессия, прод-каталог
соответствует (18/24, garch). Кодовых дефектов не обнаружено.

Изменённые/новые файлы сертификации:
- worklog3.md (данная секция)
- scripts/cert134135_oracles.py (новый, 93 пробы)
- scripts/cert134135_mutations.py (новый, 16 мутаций)

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
