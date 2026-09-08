# CISStat TS Analysis — Worklog

---

Task ID: 95 — Разделение применимости и production-готовности моделей (TDD)

Проблема

На демо-датасете модели семейств «Структурные», «Деревья и бустинг» и «Нейросетевые» отображались как обычные кандидаты с активной кнопкой «Запустить бэктест». После клика backend корректно возвращал `Production backtest для модели '<id>' не реализован; фиктивные метрики запрещены`.

Причина — два независимых понятия были сведены в один UI-статус:

- `level` из `modeling.yaml` описывал статистическую/методологическую применимость метода к профилю ряда;
- реестр `PRODUCTION_BACKTEST_MODEL_IDS` описывал наличие реального backend-dispatch;
- EDA model matrix уже различала `ready` и `catalog_only`, но `ModelCandidate`/`CandidatesResponse` эти данные не передавали;
- UI разрешал backtest любому элементу candidate pool.

Решение backend

- `model_readiness.py` остаётся единым реестром реальных реализаций и дополнен реестрами tuning/diagnostics и функцией `available_model_actions()`.
- `ModelCandidate` получил обязательные поля `platform_status: ready | catalog_only`, `available_actions` и `blocking_reason`.
- `CandidatesStatistics` отдельно считает `runnable_candidates`, `catalog_only_candidates` и `blocked_candidates`.
- Общий `_compute_candidates()` помечает все девять production backtest моделей как `ready`; остальные модели каталога получают `catalog_only`, пустой список действий и честное объяснение об отсутствии реализации.
- Session candidates дополнительно пересекает production actions с `runnable_shortlist` текущей EDA model matrix. Поэтому реализованная, но противопоказанная текущему ряду модель получает `ready` на уровне платформы, пустые действия для текущего запуска и точную причину из `blocking_reasons/cautions`.
- Серверный 422 для прямого вызова неподдержанной модели сохранён как обязательный второй уровень защиты.

Решение frontend

- Добавлен независимый фильтр исполнения: `Доступные` включён по умолчанию, `Весь каталог` открывает методологический справочник.
- В рабочем списке по умолчанию остаются только девять моделей с реальным backtest: Naive, Seasonal Naive, Drift, Mean, ETS, ETS Damped, Theta, ARIMA и Auto-ARIMA.
- В полном каталоге каждая модель имеет второй бейдж: `Готово`, `В каталоге` или `Ограничено` — отдельно от бейджа статистической применимости.
- Для `catalog_only` и data-blocked кандидатов вместо кнопки отображается недоступное состояние с `blocking_reason`; DOM-элемент запуска не создаётся.
- `runBacktest()` получил дополнительную клиентскую защиту и не выполняет fetch без действия `backtest`.
- Сводные показатели теперь отдельно показывают общее число кандидатов, доступные реализации и позиции только в каталоге.
- Решение автоматически охватывает также multivariate/volatility и любые будущие модели, отсутствующие в production registry.

TDD и проверка

- RED backend: 2/2 ожидаемых FAIL — в `ModelCandidate` и статистике отсутствовали runtime readiness поля.
- RED frontend: новый тест обнаружил, что Prophet видим в рабочем пуле по умолчанию и имеет путь запуска.
- GREEN backend: readiness/candidates/session workflow — 51/51 PASS.
- GREEN Modeling UI: 51/51 PASS.
- Полная frontend-регрессия: 83 suites, 719/719 PASS, 0 snapshots.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; First Load JS 454 kB.
- `py_compile` изменённых Python-файлов и `git diff --check`: PASS.

Изменённые и новые файлы Task 95

- `apps/api/model_readiness.py`
- `apps/api/routers/models.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/lib/modeling.ts`
- `tests/api/test_models_candidates.py`
- `tests/unit/test_model_readiness_candidates.py` (новый)
- `worklog2.md`

Артефакт передачи

- `download/task95_model_runtime_readiness_ae4a27f.zip` — только перечисленные изменённые/новые файлы Task 95 с сохранением структуры каталогов.

---

Task ID: 95 — корректирующий патч полного каталога моделей (TDD)

Проблема

После разделения production-готовности интерфейс показывал `Весь каталог (16)`, хотя `modeling.yaml` содержит 24 модели. Причина — UI строил оба режима из `CandidatesResponse.candidates`, а этот список намеренно является профильным shortlist и формируется с `min_level=CONDITIONALLY_APPLICABLE`. Модели `NOT_RECOMMENDED` и `NOT_APPLICABLE` отбрасывались backend до ответа. Поле статистики `total_models_in_spec=24` не решало проблему: отсутствующие модели нельзя было открыть и изучить.

Архитектурное решение

- Семантика существующего `candidates` сохранена: это профильный пул `RECOMMENDED + CONDITIONALLY_APPLICABLE` с обязательными baseline-моделями.
- `CandidatesResponse` дополнен отдельным `catalog`, который всегда строится через `resolve_all_applicability()` и содержит все 24 модели в порядке `modeling.yaml`.
- Каждая запись полного каталога несёт уровень применимости, правило, сообщение, `platform_status`, разрешённые действия и причину блокировки.
- Production-модель, исключённая порогом применимости, сохраняет `platform_status=ready`, но получает пустой `available_actions` и объяснение ограничения. Catalog-only модель также не получает действия.
- Session workflow применяет EDA model matrix ко всему `catalog`, затем синхронизирует те же объекты с профильным `candidates`. Это исключает появление кнопки запуска у противопоказанной модели в режиме полного каталога.
- Статистика `catalog_only_candidates` и `blocked_candidates` теперь считается по полному каталогу; `runnable_candidates` — по рабочему shortlist текущего ряда.
- Старые ответы backend поддержаны на клиенте через fallback `data.catalog ?? data.candidates`.

Frontend

- Состояния `candidates` и `catalog` разделены.
- Режим `Доступные` использует профильный shortlist и дополнительно требует действие `backtest`.
- Режим `Весь каталог` использует `catalog`; счётчик теперь равен 24, а не длине shortlist.
- Фильтры четырёх уровней применимости работают по полному каталогу, поэтому `NOT_RECOMMENDED` и `NOT_APPLICABLE` доступны для методологического просмотра.
- Карточка активной модели и клиентская защита backtest ищут модель в полном каталоге; недоступная модель не создаёт кнопку запуска.

TDD и проверка

- RED backend: 2 ожидаемых FAIL — `CandidatesResponse` не имел `catalog`, API не возвращал полный список.
- RED frontend: 1 ожидаемый FAIL — кнопка `Весь каталог (24)` отсутствовала.
- GREEN backend: candidates/readiness/internal/session workflow — 53/53 PASS.
- GREEN Modeling UI: 52/52 PASS.
- Полная frontend-регрессия: 83 suites, 720/720 PASS, 0 snapshots.
- TypeScript standalone/embedded: PASS.
- Production build standalone/embedded: PASS, по 13/13 страниц, включая `/modeling`; First Load JS 454 kB.
- `py_compile` изменённых Python-файлов и `git diff --check`: PASS.

Изменённые файлы корректирующего патча Task 95

- `apps/api/routers/internal.py`
- `apps/api/routers/models.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/lib/modeling.ts`
- `tests/api/test_models_candidates.py`
- `tests/unit/test_model_readiness_candidates.py`

---

Task ID: 96 — Leakage-safe rolling-origin backtest как единая основа Modeling (TDD)

Исходная точка и аудит

Работа выполнена после синхронизации `main` с точным коммитом `65d39b8ef4a013ed57e006b388fbaeb8da1c9343`; commit/push не выполнялись. Повторно проверены `AGENTS.md`, Modeling session workflow, EDA validation strategy, девять production model implementations, legacy public/internal backtest, diagnostics, comparison, Model Card и обе frontend-оболочки.

До Task 96 session backtest фактически был одиночным holdout: из EDA-контракта использовался только horizon, а `strategy`, `n_splits`, `gap`, `train_window` и сами folds не исполнялись. Naive строил one-step rolling forecast с фактическими значениями test, Seasonal Naive также мог читать holdout. При ошибке statsmodels legacy-обёртки могли вернуть Naive под именем исходной модели, а для неподдержанных моделей существовала формула `Naive × family_penalty`. В ответе не было fold boundaries, OOF-прогнозов и OOF-остатков; diagnostics заново строила in-sample residuals по полной истории. Абсолютный `weighted_score` вычислялся до появления сопоставимого пула моделей.

Каноническая основа backtest

- Добавлен отдельный `backtesting.py`: `BacktestPlan` валидирует и замораживает точные folds из остановки EDA без shuffle. Проверяются временной порядок, непересекающиеся test-интервалы, строгий gap, горизонт, expanding-семантика, число folds и завершение последнего test на последнем наблюдении.
- `cohort_id` является SHA-256 от fingerprint ряда, target, стратегии, точных train/test индексов, gap, horizon и seasonal period метрик. Поэтому сравнение результатов с разной шкалой MASE или разными разбиениями невозможно.
- Каждый predictor получает только train slice. Прогноз строится fixed-origin сразу на `gap + horizon`; gap-прогнозы не оцениваются, а в OOF попадает только следующий test-интервал. Naive фиксирует последний train, Drift продолжает train-тренд, Seasonal Naive рекурсивно продолжает train-сезонность и не читает test даже при `horizon > period`.
- Один строгий registry подключает все девять реально реализованных моделей: Naive, Seasonal Naive, Drift, Mean, ETS, ETS Damped, Theta, ARIMA и Auto-ARIMA. Registry программно сверяется с `PRODUCTION_BACKTEST_MODEL_IDS`.
- Любая ошибка fit/predict завершает fold и весь запуск честным 422 с сохранением `backtest_failures`; подмена Naive запрещена. Legacy penalty-ветка также удалена: public/internal API больше не могут вернуть фиктивные метрики для LightGBM, структурных, neural, multivariate или volatility моделей.
- Для каждого fold сохраняются индексы и временные labels train/test, gap, duration, метрики и прогнозные точки. Агрегат строится по всем OOF-точкам; сохраняются actual, predicted и residual.
- Метрики: MAE, RMSE, MAPE с числом допустимых точек, sMAPE, seasonal MASE и RMSSE. Знаменатели MASE/RMSSE рассчитываются только по train соответствующего fold. Невычислимые MAPE/MASE возвращаются как `null` с предупреждением. `weighted_score` канонического одиночного backtest равен `null` и появляется только после min-max нормализации внутри общего comparison cohort.
- Производные target, полученные некаузальным сглаживанием/detrending либо Box-Cox/Yeo-Johnson с параметрами по полной истории, блокируются до появления fold-local preprocessing fit. Детерминированный каузальный target допускается с явным предупреждением о шкале метрик.

EDA hand-off и downstream-трассируемость

- Последний рассчитанный план EDA сохраняется в `AnalysisSession.eda_validation_strategy`, проходит Memory/Redis JSON round-trip и сбрасывается вместе с паспортом при смене dataset/target/date.
- `GET /v1/session/modeling/context` без ручных query-параметров восстанавливает последний EDA-план либо текущий Modeling contract; переход между вкладками и reload больше не заменяют sliding/single/gap дефолтным expanding.
- Candidates request теперь передаёт и сохраняет полный контракт: strategy, horizon, n_splits, gap и train_window. Backtest принимает только сохранённые folds; ручной `train_ratio` в каноническом маршруте отвергается.
- Diagnostics использует только сохранённые OOF residuals того же backtest/cohort, а не повторный in-sample fit по полной истории.
- Compare принимает только полностью успешные backtests с одинаковым ненулевым cohort id. MAPE/MASE исключаются из ranking с перенормировкой весов, если метрика не определена хотя бы для одной модели.
- Model Card сохраняет полный fold contract, cohort id, horizon/gap, OOF predictions/residual source, корректное число наблюдений исходного ряда и фактические границы train.

Frontend

- Типы Modeling расширены fold/OOF/cohort-контрактом и nullable-метриками.
- Карточка результата показывает стратегию, число folds, horizon, последний train и общий размер OOF вместо методологически неверного абсолютного score.
- Сравнительный график до стадии server-side comparison показывает OOF MASE, а не старый `weighted_score` с произвольными делителями.
- Добавлен график «факт ↔ fixed-origin прогноз» выбранной модели по OOF-точкам с разделителями folds; при отсутствии OOF UI не рисует фиктивную визуализацию.

TDD и проверка

- RED: отсутствовал модуль backtest engine; UI не показывал fold contract. Дополнительные RED-регрессии подтвердили потерю sliding-параметров, возврат penalty-метрик LightGBM и игнорирование gap при прогнозировании.
- GREEN core/session contract: 23/23 PASS.
- Расширенный backtest/session/store contract: 88/88 PASS.
- Проверены реальные strict-dispatch всех девяти production-моделей на одном OOF cohort.
- Расширенная Modeling/backend-регрессия: 157/159 PASS; два сбоя — ранее известный baseline ARIMA tuning на технически коротких folds в текущей версии statsmodels.
- Полный backend collection без синтаксически повреждённого baseline-файла `tests/unit/test_file_loader.py`: 1219 PASS, 33 FAIL, 3 ERROR. Число и классы остатка совпадают с ранее зафиксированным baseline: Pandas 3 string dtype, отсутствующие `ruptures` и snapshot fixture, legacy diagnostics YAML contract и короткие ARIMA folds.
- Целевой frontend: 3 suites, 59/59 PASS.
- Полный frontend: 84 suites, 723/723 PASS, 0 snapshots.
- TypeScript embedded/standalone: PASS с ранее принятым проверочным флагом `--noUncheckedSideEffectImports false`; production tsconfig не менялся.
- Production build embedded/standalone: PASS, по 13/13 страниц, включая `/modeling`; First Load JS 455 kB. Временный sandbox memory shim удалён и в изменения не входит.
- `py_compile` изменённых Python-файлов и `git diff --check`: PASS.

Изменённые и новые файлы Task 96

- `apps/api/backtesting.py` (новый)
- `apps/api/routers/modeling_session.py`
- `apps/api/routers/models.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/BacktestComparisonChart.tsx`
- `packages/ui/components/BacktestComparisonChart.test.tsx`
- `packages/ui/components/BacktestOofChart.tsx` (новый)
- `packages/ui/components/BacktestOofChart.test.tsx` (новый)
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/lib/modeling.ts`
- `packages/ui/index.ts`
- `tests/api/test_modeling_workflow.py`
- `tests/api/test_models_candidates.py`
- `tests/unit/test_backtesting_engine.py` (новый)

---

## Task 97 — Спецификация: раскрытие/схлопывание вложенных графиков в Обзоре

Спроектирована архитектура фичи expand/collapse для вложенных графиков
«Обзора» на всех вкладках платформы (Validation/Preprocessing/EDA/Modeling).
Артефакт: `spec_max_graph.md`.

Ключевые решения: переиспользуемый примитив ExpandableChartPanel/
ExpandableChartsProvider/ChartExpandToggle в packages/ui; single-expand
инвариант на уровне одного Обзора; раскрытие в границах существующего
468px-контейнера (Task 88) через absolute inset-0; опциональный
detail_level=compact|expanded для сэмплирования на раскрытом графике
с обратной совместимостью. Поэтапный роллаут (фундамент → пилот →
сэмплирование → тиражирование). Открытые вопросы по вторичным потолкам
сэмплирования и приоритету пилотных Обзоров — на решение тимлида.

Статус: архитектурный дизайн передан на ревью, реализация не начата
(коммит/push в main запрещён протоколом AGENTS.md).

---

## Task 98 — Единый BacktestPlan для tuning и fold-local preprocessing (TDD)

### Исходная точка и выявленный разрыв

Работа выполнена на точном исходном коммите
`fe1c636fccb75bb8f9162fa479cbb7ccecc5f6ca`; commit/push не выполнялись.
Повторно изучены `AGENTS.md`, Task 96, session Modeling API, legacy
`/v1/models/tune`, EDA validation strategy, preprocessing metadata и оба
frontend shell.

До Task 98 session backtest уже исполнял `BacktestPlan`, но session tuning
строил второй набор разбиений через `ExpandingWindowCV`. Поэтому он не мог
гарантировать те же фактические границы folds, отдельно интерпретировал
`min_train_size/step`, запрещал sliding и допускал пользовательский `cv`,
разрывающий cohort. Сохранённый рецепт `fit_policy=per_train_fold` не
исполнялся: scaling target игнорировался, а оценочные power-transform target
блокировались целиком.

### Архитектурное решение

- Добавлен `modeling_tuning.py`: grid/max-trials сохранены, но каждый trial
  теперь запускается через тот же строгий `run_backtest_plan()`, что и
  production backtest. Метрики агрегируются по всем OOF-точкам exact EDA
  folds, а не по заново построенному legacy CV.
- Session endpoint `POST /v1/session/modeling/tune` принимает только
  сохранённый EDA `BacktestPlan`. `single`, `expanding` и `sliding`
  поддерживаются одинаково; ручной `cv` возвращает 422. Публичный legacy
  `/v1/models/tune` оставлен для обратной совместимости, но Modeling больше
  его не вызывает.
- Tuning response сохраняет и показывает `strategy`, `cohort_id`, точные
  `train_start/train_end/test_start/test_end/gap` каждого fold,
  preprocessing contract и warnings. `weighted_score` запрещён на этом
  шаге: он определяется только внутри общего comparison cohort.
- Sliding plan дополнительно валидирует постоянный `train_window` и
  монотонное смещение train-окна.

### Fold-local preprocessing

- Добавлен `fold_preprocessing.py`, который восстанавливает цепочку
  `source_column → ... → target_column` по сохранённым metadata. Полностью
  материализованная диагностическая target-колонка не используется как
  источник обучения.
- Для каждого EDA fold отдельно выполняются fit/transform train и transform
  последующего `gap + horizon`. Автоматические Box–Cox и Yeo–Johnson
  переоценивают lambda только на train; явно заданная аналитиком lambda
  хранится как fixed-рецепт; log/log1p/sqrt применяются детерминированно.
- Реализованы fold-local stationarity и inverse для linear detrend,
  first/second/seasonal/combined/log difference. Прогноз возвращается в
  исходную шкалу перед OOF-метриками.
- Causal SMA/EMA/WMA/median допускаются как явно выбранная целевая шкала;
  некаузальные LOWESS/Savitzky–Golay отклоняются в production.
- Если scaling recipe включает target, scaler fit-ится только на train fold,
  а прогноз inverse-transform-ится до расчёта метрик. Рецепт только для X
  не применяется текущими univariate ETS/ARIMA и маркируется предупреждением.
- Preprocessing signature включена в `cohort_id`: разные transform/scaler
  contracts нельзя сравнить как один эксперимент. Tuned params применяются
  backtest только при совпадении cohort.
- Backtest и Model Card сохраняют использованный preprocessing contract,
  evaluation scale и факт inverse transform.

### Frontend

- Обзор стадии «Тюнинг» объясняет использование exact EDA BacktestPlan и
  train-only preprocessing.
- После запуска показывается компактная сводка: стратегия, число folds,
  `fit_policy` и короткий cohort id; полный JSON-аудит сохранён.
- TypeScript-контракты дополнены fold-local preprocessing и session tuning.

### TDD и проверка

- RED backend: новый набор остановился на отсутствующих
  `fold_preprocessing`/`modeling_tuning`; RED frontend подтвердил отсутствие
  tuning cohort summary.
- GREEN core/session: 28/28 PASS. Проверены exact sliding boundaries и общий
  cohort tuning↔backtest, запрет второго CV-контракта, train-only Box–Cox,
  исходная шкала OOF, target scaling inverse и stationarity inverse.
- Modeling UI: 56/56 PASS; отдельный overview: 3/3 PASS.
- Расширенная legacy tuning/preprocessing регрессия: 158/160 PASS. Два
  оставшихся ARIMA-сбоя на коротких legacy folds (`d=1`, statsmodels 0-D
  initialization) совпадают с baseline Task 96 и не относятся к Task 98.
- Расширенный Modeling-набор: 144/151 PASS. Кроме тех же двух ARIMA-сбоев,
  пять падений относятся к ранее зафиксированному расхождению legacy
  diagnostics YAML с runtime Phase 2; изменённые Task 98 тесты в остаток не
  входят.
- TypeScript standalone/embedded: PASS с ранее принятым флагом
  `--noUncheckedSideEffectImports false`.
- Production build standalone/embedded: PASS, по 13/13 страниц, `/modeling`
  включена; First Load JS 455 kB. Для известного ограничения sandbox Node 24
  `uv_resident_set_memory` применялся временный memory shim, после проверки
  удалённый и не входящий в изменения.
- `py_compile`, `git diff --check`: PASS.

### Изменённые и новые файлы Task 98

- `app/preprocessing/transforms.py`
- `apps/api/backtesting.py`
- `apps/api/fold_preprocessing.py` (новый)
- `apps/api/modeling_tuning.py` (новый)
- `apps/api/preprocessing_variance.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/lib/modeling.ts`
- `tests/api/test_modeling_workflow.py`
- `tests/unit/test_backtesting_engine.py`
- `tests/unit/test_modeling_tuning_plan.py` (новый)

---

## Task 99 — Трассируемая диагностика tuned-модели (TDD)

Дата: 2026-09-03

### Исходная точка и выявленный разрыв

Работа выполнена после синхронизации с точным коммитом 7986075459001fc375ff2ed3dc8af490f2b21a45; commit/push не выполнялись. Task 98 уже унифицировал backtest и tuning на одном BacktestPlan, но лучший trial сохранялся только как best_params/best_metrics. Его полный OOF backtest отбрасывался, а session diagnostics читала прежний backtest модели. Поэтому после tuning можно было диагностировать остатки default-конфигурации и назвать их tuned-остатками. При повторном tuning сохранялись старые diagnostics, comparison, selection и Model Card.

Дополнительно формальный Stage 8 в modeling.yaml описывал пять старых проверок, тогда как runtime реально выполнял Ljung–Box, Jarque–Bera, ARCH-LM и Durbin–Watson. UI скрывал baseline-модели из diagnostics, хотя session endpoint методологически работает с OOF любого успешного backtest, и показывал только неструктурированный JSON без provenance.

### Архитектурное решение

Tuning engine теперь сохраняет полный backtest каждого успешного trial и возвращает точный OOF лучшего trial без повторного fit. Совместимый фасад execute_tuning_plan() сохранён для существующих вызовов и тестов.
Для каждого tuning run создаётся tuning_id; exact best_params получают детерминированный SHA-256 parameter_signature.
Лучший trial атомарно повышается до session backtest с run_id, params_source=tuning, tuning_id, parameter_signature и SHA-256 упорядоченных OOF actual/predicted/residual (oof_signature). Метрики tuning и promoted backtest относятся к одному вычислению.
Обычный backtest получает тот же lineage-контракт. Для baseline/default фиксируется params_source=model_default; при совпавшем tuning cohort — params_source=tuning и соответствующий tuning_id.
Diagnostics принимает только сохранённый OOF и проверяет подписи параметров и OOF, run_id, cohort и соответствие текущему tuning run. Изменённый или устаревший артефакт возвращает 409 вместо расчёта по недоказанным остаткам.
Типизированный session response сохраняет exact params, parameter/tuning/ backtest/OOF identity, preprocessing contract и источник tuned_backtest_oof | backtest_oof вместе с четырьмя результатами тестов.
Повторный backtest/tuning удаляет diagnostics этой модели и все зависящие comparison/selection/model cards; pipeline возвращается к корректным незавершённым стадиям.
Compare повторно валидирует parameter и OOF signatures и запрещает stale tuned-backtests. Ranking и Model Card сохраняют execution lineage; Model Card берёт гиперпараметры из фактически выбранного backtest, а не из потенциально несвязанного tuning artifact.
modeling.yaml синхронизирован с runtime: ровно Ljung–Box, Jarque–Bera, ARCH-LM и Durbin–Watson, включая applicable conditions, p-value contract и lag settings. Удалены неисполняемые ADF и prediction-interval coverage.
Frontend
После tuning promoted backtest сразу заменяет прежний результат модели в TsAnalysisModeling, поэтому последующие графики и diagnostics используют тот же OOF run.
Diagnostics доступны для всех моделей с сохранённым production backtest, а не только ETS/ARIMA; tuning по-прежнему ограничен реестром ETS/ETS Damped/ARIMA.
Вместо raw JSON показана таблица четырёх тестов со статусами и отдельный lineage-блок: источник OOF и параметров, exact params, cohort, tuning ID, backtest run ID, Params SHA, Residuals SHA и fold-local preprocessing.
Результат очищается при смене стадии или модели, чтобы отчёт предыдущего run не отображался под новым выбором.
TDD, риски и проверка
RED backend: 9 ожидаемых падений — отсутствовали lineage/promotion, downstream invalidation и актуальный YAML-контракт.
RED frontend: compile-time ошибка по отсутствующему callback promoted backtest; отчёт diagnostics не был реализован.
Добавлен unit-инвариант: лучший trial повышается с исходным OOF и не переобучается. Добавлен API-негативный тест изменения OOF после tuning.
Целевой GREEN: 26/26 backend; ModelingWorkflowOverview 4/4.
Расширенная Modeling/backend-регрессия: 245/245 PASS, включая Memory/Redis SessionStore, public/internal backtest, runtime diagnostics и ModelingSpec.
Расширенная Modeling UI-регрессия: 5 suites, 65/65 PASS.
Полная frontend-регрессия: 84 suites, 725/725 PASS, 0 snapshots.
TypeScript embedded/standalone: PASS с принятым флагом --noUncheckedSideEffectImports false.
Production build embedded/standalone: PASS, по 13/13 страниц, включая /modeling; First Load JS 456 kB. Для известного sandbox-ограничения Node 24 uv_resident_set_memory использован временный shim, удалённый после сборки и не входящий в изменения.
py_compile и git diff --check: PASS.

### Изменённые файлы Task 99

apps/api/modeling_tuning.py
apps/api/routers/modeling_session.py
apps/api/schemas.py
packages/ui/components/ModelingWorkflowOverview.tsx
packages/ui/components/ModelingWorkflowOverview.test.tsx
packages/ui/components/TsAnalysisModeling.tsx
packages/ui/lib/modeling.ts
rules/modeling.yaml
tests/api/test_modeling_workflow.py
tests/unit/test_modeling_tuning_plan.py

---

## Task 100 — Трассируемое сравнение моделей на едином OOF cohort (TDD)

Дата: 2026-09-03

### Исходная точка и выявленный разрыв

Работа выполнена на точном исходном коммите 0d1786f9050e0b313097a25a14ed60acadb8e07d; commit/push не выполнялись. Task 99 замкнул цепочку tuned backtest → OOF diagnostics, однако Stage 9 сравнивал только совпавший cohort_id. Он не доказывал равенство фактических OOF-точек, границ folds, исходных фактов и шкалы оценки, не требовал актуальную диагностику каждой модели и не имел воспроизводимой подписи comparison.

Legacy YAML дополнительно смешивал разные основания решения: давал диагностике произвольный бонус 10% к прогнозному score. UI показывал только ранг и агрегированные метрики, без lineage, устойчивости между folds, корреляции ошибок и состояния diagnostics. Формальный столбец применимости был описан в UI-контракте, но не доходил до runtime comparison.

### Архитектурное и методологическое решение

Добавлен чистый модуль modeling_comparison.py. Comparable pool теперь содержит минимум две успешные модели и обязательно рассчитанный baseline; неизвестные и повторяющиеся model_ids отклоняются явно.
Для всех моделей проверяется точное совпадение ключей fold/horizon_step/index/label, границ train/test/gap, evaluation scale и фактических значений OOF. Совпавшего cohort_id без этих доказательств недостаточно.
Comparison требует текущий diagnostics report для каждого backtest и валидирует связь backtest_run_id + cohort_id + parameter_signature + residuals_signature + diagnostics_signature. Повторная диагностика инвалидирует comparison, selection и Model Card.
Прогнозный рейтинг рассчитывается только по MAE/RMSE/MAPE/MASE после min-max нормализации внутри exact comparable pool. Если MAPE или MASE не определена хотя бы у одной модели, метрика исключается для всего пула, а веса перенормируются до единицы. Diagnostics не изменяет score и остаётся отдельным свидетельством.
Результат содержит raw и normalized metrics, детерминированный tie-break, baseline-флаг MASE ≤ 1.05 и явный override для рискованного выбора.
Для каждого fold рассчитаны RMSE, среднее, стандартное отклонение, коэффициент вариации, ранги, средний ранг, разброс ранга и доля top-1. Равные с учётом численной точности значения получают одинаковый ранг.
Добавлена Pearson-матрица только по точно совмещённым OOF residual vectors. При нулевой дисперсии значение честно возвращается как null с причиной; корреляция не трактуется как автоматическое доказательство ансамбля.
comparison_signature детерминированно связывает fingerprint, cohort, политики, веса, backtest run/params/OOF, агрегированные и fold-метрики, diagnostics signatures и уровни применимости. Порядок model_ids на подпись и итоговый рейтинг не влияет.
Уровень применимости повторно берётся из существующего rule-engine кандидатов на том же профиле. Он отображается и входит в lineage, но не смешивается с прогнозной точностью или диагностикой.
Selection фиксирует comparison_id/signature, backtest run и diagnostics signature. Model Card получает те же ссылки, normalized score, fold stability и фактический уровень применимости выбранной строки рейтинга.
Frontend и спецификация
Stage 9 в modeling.yaml синхронизирован с runtime: exact OOF alignment, current diagnostics, обязательный baseline, раздельные evidence axes, fold stability и OOF error correlation. Удалён неисполняемый diagnostics_bonus.
В comparison показан lineage-блок с Comparison SHA, cohort, числом OOF-точек и политикой score. Таблица содержит применимость, raw score, RMSE/MASE, fold RMSE μ±σ/top-1, diagnostics и baseline status.
Добавлены фильтры по применимости, семейству, diagnostics status и baseline-risk, а также матрица корреляции OOF-ошибок.
Структурированные 409-ответы показывают конкретные missing/stale model IDs. Повторный tuning/diagnostics/comparison очищает устаревшее локальное отображение downstream-артефактов.
TDD, риски и проверка
RED backend: 7 ожидаемых падений — endpoint принимал отсутствующие diagnostics/неполный пул, не имел comparison/diagnostics signatures, пропускал несовмещённые OOF и расходился с YAML. RED frontend подтвердил отсутствие lineage, stability, correlation и структурированной ошибки.
Целевой GREEN backend: 88/88 PASS, включая 21 session workflow test, ModelingSpec, новый YAML-contract и unit-инварианты tie/alignment/signature.
Целевой ModelingWorkflowOverview: 5/5 PASS.
Расширенная Modeling/backend-регрессия: 271/272 PASS. Единственный сбой — ранее зафиксированный legacy /v1/models/tune ARIMA-grid на коротких folds с d=1 (statsmodels 0-D initialization); Task 100 этот контур не меняет, session Modeling использует единый BacktestPlan.
Полная frontend-регрессия: 84 suites, 726/726 PASS, 0 snapshots.
TypeScript embedded/standalone: PASS.
Production build embedded/standalone: PASS, по 13/13 страниц, включая /modeling; First Load JS 458 kB. Для известного sandbox-ограничения Node 24 uv_resident_set_memory использован временный shim, удалённый после сборок и не входящий в изменения.
py_compile и git diff --check: PASS.

### Изменённые и новые файлы Task 100

apps/api/modeling_comparison.py (новый)
apps/api/routers/modeling_session.py
apps/api/schemas.py
packages/ui/components/ModelingWorkflowOverview.tsx
packages/ui/components/ModelingWorkflowOverview.test.tsx
packages/ui/lib/modeling.ts
rules/modeling.yaml
tests/api/test_modeling_workflow.py
tests/api/test_modeling_comparison_spec.py (новый)
tests/unit/test_modeling_comparison.py (новый)

---

## Task 101 — Спецификация: Soft Pillow (балансировка нижних границ колонок)

Спроектирована архитектура декоративного layout-примитива Soft Pillow — выравнивание нижних границ соседних колонок многоколоночных секций на всех вкладках платформы. Артефакт: spec_soft_pillow.md. Синхронизация: main @ 0d1786f (Task 99).

Ключевые решения: SoftPillowSection/SoftPillowColumn/SoftPillow в packages/ui, паттерн провайдера по образцу ExpandableChartsProvider (Task 97); ResizeObserver наблюдает контент отдельно от подушки (защита от цикла обратной связи); активация только выше брейкпоинта многоколоночной раскладки. Переиспользование: существующие дизайн-токены (цвет skeleton/empty-state, радиус карточек), существующая инфраструктура измерения размеров (Task 89) — новых backend-изменений не требуется. Явно разграничено с Task 97 (разные уровни вложенности, не конфликтуют).

Статус: архитектурный дизайн передан на ревью, реализация не начата (коммит/push в main запрещён протоколом AGENTS.md).

---

## Task 102 — Трассируемый выбор модели и верифицируемый ensemble trigger (TDD)

Дата: 2026-09-04

### Исходная точка и устранённый методологический разрыв

Работа выполнена на точном коммите
`a42df0a75a022336daa85862cae041633dd4ac38`; commit/push не выполнялись.
После Task 100 comparison был воспроизводимым, но Stage 10 всё ещё выбирал
top-1 по pool-dependent weighted min-max score. Baseline-risk определялся по
MASE ≤ 1.05, а ensemble лишь помечался эвристикой «две модели с MASE < 1 и
близким score» — комбинированный прогноз не строился и не имел собственных
OOF-метрик, diagnostics и lineage. Корреляция ошибок сохранялась, но не
участвовала в исполняемом и проверяемом trigger.

### Архитектурное и методологическое решение

- Добавлен чистый модуль `modeling_selection.py` с версионированной политикой
  `selection-v1-equal-weight`. Финальный single-кандидат определяется по
  фактической primary OOF loss (`RMSE` по умолчанию), а weighted score остаётся
  только обзорной осью comparison. Практические ничьи фиксируются отдельно.
- Baseline-риск теперь сравнивает выбранную модель с лучшим реально
  рассчитанным OOF baseline по той же primary metric. Привлекательная MASE сама
  по себе больше не считается доказательством выигрыша.
- Eligibility gate выбирает две модели, которые не хуже фактического baseline,
  укладываются в относительный разрыв primary loss, имеют достаточно OOF-точек
  и корреляцию ошибок ниже порога. Корреляция служит только gate и никогда не
  создаёт рекомендацию сама.
- Production v1 строит только детерминированное простое среднее 50/50 на точно
  совмещённых OOF-точках. Ансамбль получает собственные point forecasts,
  fold/aggregate MAE, RMSE, MAPE, MASE, sMAPE, RMSSE, OOF SHA-256, run/parameter
  signatures и четыре residual diagnostics.
- Для воспроизводимого пересчёта MASE/RMSSE backtest сохраняет в каждом fold
  train-only denominators. Масштабы fit-ятся до test и не реконструируются из
  holdout.
- Ensemble имеет три явных состояния: `not_eligible`, `tested_no_gain`,
  `recommended`. Рекомендация требует фактического относительного улучшения к
  лучшему single, минимальной доли выигранных folds и отсутствия проигрыша
  лучшему OOF baseline. Выбор `tested_no_gain` возможен только как явный override.
- Новый `POST /v1/session/modeling/selection/evaluate` сохраняет signed
  `selection_analysis`, а также ensemble backtest/diagnostics при фактической
  проверке. `POST /select` требует точные analysis ID/SHA и отклоняет stale
  lineage.
- Текущая оценка честно маркируется `selection_oof_reused`: tuning и selection
  используют один OOF cohort, независимый final holdout отсутствует. До выбора
  обязательно явное подтверждение этого ограничения; следующий методологический
  уровень — sealed tail holdout или outer temporal CV.
- Любой новый backtest, tuning, diagnostics или comparison инвалидирует
  selection analysis, ensemble artifacts, selection и Model Cards. Model Card
  повторно проверяет selection lineage и для ensemble сохраняет его участников,
  собственный OOF run, diagnostics, primary baseline comparison и ограничение
  по отсутствию независимого holdout.

### Frontend и формальная спецификация

- Stage 10 получил отдельное действие «Верифицировать выбор». До получения
  signed analysis и подтверждения reused-OOF bias кнопки выбора заблокированы.
- UI показывает Selection SHA, primary metric/loss, фактический лучший baseline,
  состояние и состав ensemble, корреляцию ошибок, улучшение, fold win rate и
  причины отказа. Для ensemble без доказанного выигрыша и/или хуже baseline
  предусмотрены отдельные подтверждения override.
- Подтверждения очищаются при каждом новом comparison/selection analysis и не
  переносятся на новый lineage.
- `modeling.yaml` обновлён до `1.1.0-draft`: Stage 10 закрепляет primary OOF
  selection и actual baseline; ensemble v1 — только `simple_average`, correlation
  — eligibility gate, а inverse-MAE/median/stacking явно оставлены planned до
  честного независимого validation.

### TDD, риски и проверка

- RED core: 4 теста падали из-за отсутствующего `modeling_selection`; RED YAML:
  2 теста подтвердили отсутствие primary-loss selection и verified trigger.
- Unit/spec/backtesting: 20/20 PASS, включая actual baseline вместо MASE,
  correlation-only gate, собственный ensemble OOF, стабильность selection SHA,
  fail-closed при подмене diagnostics lineage и сохранение train-only scales.
- Интеграционный session Modeling workflow: 21/21 PASS.
- UI-регрессия Modeling: 58/58 PASS; целевой компонент после финальной правки:
  5/5 PASS.
- TypeScript embedded/standalone: PASS; после production build использован
  принятый для репозитория флаг `--noUncheckedSideEffectImports false` из-за
  известного side-effect импорта `globals.css`.
- Production build standalone: PASS, 13/13 static pages, включая `/modeling`;
  First Load JS 459 kB. Для sandbox-ограничения Node 24
  `uv_resident_set_memory` использован временный shim, удалённый после сборки и
  не входящий в изменения.
- `py_compile`, `compileall` и `git diff --check`: PASS.

### Изменённые и новые файлы Task 102

- `apps/api/backtesting.py`
- `apps/api/modeling_selection.py` (новый)
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/lib/modeling.ts`
- `rules/modeling.yaml`
- `tests/api/test_modeling_workflow.py`
- `tests/api/test_modeling_selection_spec.py` (новый)
- `tests/unit/test_backtesting_engine.py`
- `tests/unit/test_modeling_selection.py` (новый)

---

## Task 103 — Спецификация: Account/Seats (моно/мульти доступ) + Compute Unit метеринг

Спроектирована архитектура биллинговой модели, расширяющей
ROLES_AND_PLANS_SPEC.md: сущность Account (mono/multi, seats, пул CU) +
AccountMembership (owner/member — отдельная ось от Role/Plan). План и
цена перенесены с Principal на Account, require_capability(...) не
переписывается — меняется только источник резолва плана.
Артефакт: spec_billing_accounts.md. Синхронизация: main @ a42df0a.

Ключевые решения: линейное ценообразование price = base_price × seats
для self-service; единица метеринга — Compute Unit (не токены LLM) —
формула по типу операции, коэффициенты калибруются отдельно; пул CU
на уровне Account, масштабируемый от seats, не делится поровну;
резервирование CU до выполнения операции (защита инфраструктурного
бюджета, не только бухгалтерия). Переиспользование: бюджет PELT-сетки
(Task 76) и TuningPlanExecution (Task 99) как источники входных
параметров формулы CU — не переизобретаются заново.

Статус: архитектурный дизайн передан на ревью, реализация не начата
(коммит/push в main запрещён протоколом AGENTS.md). 5 открытых вопросов
к тимлиду (§9 спецификации), в первую очередь — калибровка
ALGORITHM_COEFFICIENTS на реальных бенчмарках.

---

## Task 104 — Устранение HTTP 502 tuning и гарантированный baseline pool

Дата: 2026-09-04. База: `main @ a4395e11b422780bc91999c0e5531356fc6264ec`.
Commit/push и production deploy не выполнялись.

### Диагностика

- First-party API через Vercel rewrite и Render доступен: обычный session route
  отвечает штатно. Ошибка локализована в `POST /v1/session/modeling/tune`:
  вся сетка ETS/ARIMA исполнялась синхронно в одном HTTP-запросе. Даже локальный
  ETS grid на коротком ряду занимает несколько секунд; на shared CPU и реальном
  числе folds суммарное время может превысить proxy/runtime budget и проявиться
  как bodyless HTTP 502.
- Stage 5 был объявлен обязательным, однако UI не запускал baseline автоматически
  и позволял перейти к comparison. Backend корректно fail-closed отклонял пул без
  рассчитанной baseline-модели сообщением `Comparable pool должен содержать
  минимум один рассчитанный baseline`.
- Сокращение tuning grid отклонено: оно маскировало бы инфраструктурную проблему
  и меняло методологию выбора модели.

### Реализация

- Добавлен `POST /v1/session/modeling/baselines`. Он один раз строит точный EDA
  `BacktestPlan`, рассчитывает доступные production baselines в одном session
  transaction, сохраняет только успешные traceable backtests одного cohort и
  требует минимум один успех. При повторном вызове валидный baseline того же
  cohort переиспользуется без новых run IDs и без инвалидации downstream.
- Загрузка candidate pool в UI теперь включает обязательный baseline bootstrap.
  Результаты сразу попадают в общий `backtestResults`, а стадии Baseline/Backtest
  отмечаются завершёнными. Ручной пересчёт модели остаётся доступен.
- Tuning engine разделён на три проверяемые операции: детерминированная подготовка
  grid, выполнение одного trial и каноническая финализация всех trial artifacts.
  Старый response-only и синхронный API сохранены для обратной совместимости.
- Добавлены `POST /v1/session/modeling/tuning/start` и
  `POST /v1/session/modeling/tuning/step`. Start фиксирует grid, metric, seed,
  cohort и SHA-256 job signature в Redis-compatible session state. Каждый step
  исполняет ровно один trial на всех точных EDA folds и сохраняет прогресс.
  Последний step выбирает best trial, без повторного fit продвигает его OOF
  backtest и сохраняет прежний `TuneResponse`/lineage contract.
- Step использует `expected_trial_index` и возвращает 409 при рассинхронизации;
  завершённый job идемпотентно возвращает тот же tuning result. Изменение EDA
  cohort или job policy переводит запуск в stale и требует нового start.
- UI последовательно вызывает короткие step-запросы, показывает `Trial N/M` и
  останавливается при невалидном размере plan или непродвигающемся progress.
  Полная ETS/ARIMA grid и правила выбора лучшего trial не сокращались.

### TDD и проверки

- RED: новые API-тесты получили ожидаемый 404 для отсутствующих baseline/start
  routes; UI-тест подтвердил, что старый единственный `/tune` response не
  удовлетворяет пошаговому контракту.
- `tests/unit/test_modeling_tuning_plan.py` +
  `tests/api/test_modeling_workflow.py`: 28/28 PASS.
- Полный релевантный Modeling-набор: 119 PASS; 2 известных stale-теста базового
  `a4395e1` остались красными (`1.0.0-draft` против уже принятого
  `1.1.0-draft`, а также удалённый Task 102 heuristic `auto_ensemble_trigger`).
  Они не вызваны Task 104 и не исправлялись вне его scope.
- UI Modeling: 58/58 PASS.
- TypeScript embedded/standalone: PASS с принятыми для текущего toolchain
  флагами `--ignoreDeprecations 6.0 --noUncheckedSideEffectImports false`.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 459 kB. Временный Node 24 memory shim после проверки удалён.
- `py_compile` и `git diff --check`: PASS.

### Изменённые файлы Task 104

- `apps/api/modeling_tuning.py`
- `apps/api/routers/modeling_session.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `tests/api/test_modeling_workflow.py`

---

## Task 105 — Миграция legacy Modeling artifacts без execution/OOF lineage

Дата: 2026-09-04. База: `main @ a363837488901ce71f8520f6936cf245d60bd07f`.
Commit/push и production deploy не выполнялись.

### Симптом и причина

- После устранения 502 и автоматизации baseline comparison мог вернуть:
  `Бэктесты не имеют валидной execution/OOF lineage: ['arima_auto', 'ets']`.
- Ошибка воспроизведена для Redis-сессии, пережившей обновление backend. Modeling
  artifacts не имели версии схемы, поэтому `/v1/session/modeling/state` возвращал
  UI старые backtests, созданные до Task 102 — без `run_id`, корректного
  `parameter_signature` и/или `oof_signature`.
- Comparison правильно работал fail-closed. Подписывать старые результаты задним
  числом нельзя: это выдало бы непроверенное legacy-исполнение за трассируемое.

### Исправление

- Введена `MODELING_ARTIFACT_SCHEMA_VERSION = 2`; новые Modeling states получают
  версию при инициализации.
- Для существующих сессий добавлена селективная миграция. Она независимо проверяет:
  tuning ID/cohort/parameter SHA; backtest run/cohort/parameter/OOF SHA и связь с
  tuned result; diagnostics run/residual/parameter/cohort/signature.
- Валидные результаты Task 102–104 сохраняются. Удаляются только unsigned,
  tampered или stale artifacts и их зависимые tuning/diagnostics.
- При инвалидации очищаются comparison, selection analysis, ensemble artifacts,
  selection и Model Cards; статусы pipeline пересчитываются по фактически
  сохранённым artifacts.
- В `artifact_migration` сохраняются версия, причина, время и отсортированные
  списки удалённых backtests/tunings/diagnostics. Ложная lineage не создаётся.
- Воспроизведён сценарий скриншота: валидный baseline оставлен, legacy `ets` и
  `arima_auto` исключены; после нового backtest/diagnostics для ETS comparison
  `naive + ets` успешно выполняется.

### TDD и проверки

- RED: новый migration-тест получил `KeyError: artifact_schema_version`, а
  legacy `ets/arima_auto` продолжали возвращаться через state.
- Modeling backend/core/API: 60/60 PASS.
- Modeling UI: 58/58 PASS.
- TypeScript embedded и standalone: PASS.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 459 kB.
- `py_compile` и `git diff --check`: PASS.

### Изменённые файлы Task 105

- `apps/api/routers/modeling_session.py`
- `tests/api/test_modeling_workflow.py`

---

## Task 106 — Автоматическая diagnostics готовность comparable pool

Дата: 2026-09-04. База: `main @ a363837488901ce71f8520f6936cf245d60bd07f`.
Включает незакоммиченный hotfix Task 105; commit/push и deploy не выполнялись.

### Симптом и причина

- Comparison после расчёта `theta` и автоматического baseline pool возвращал:
  `Для comparison нужны diagnostics каждого backtest: theta, naive, drift, mean`.
- Fail-closed проверка backend методологически корректна: comparison использует
  diagnostics каждого точного OOF run. Ошибка находилась в UI orchestration:
  Stage 8 позволял вручную диагностировать только одну модель, а Stage 9 сразу
  отправлял весь накопленный pool.
- В batch-сценарии обнаружен дополнительный численный дефект: для постоянных
  baseline residuals отдельные statsmodels-тесты могли вернуть `NaN`. Starlette
  запрещает такой JSON и отвечал 500 вместо диагностического отчёта.

### Исправление

- Логика построения session diagnostics выделена в чистую функцию без мутации
  сессии. Одиночный `POST /diagnostics` сохраняет прежний контракт.
- Добавлен `POST /v1/session/modeling/diagnostics/ensure`. Он принимает точный
  comparable pool, проверяет наличие и lineage каждого backtest, переиспользует
  актуальные подписанные reports и рассчитывает только отсутствующие/stale.
- Batch исполняется атомарно: сессия изменяется только после успешного расчёта
  всего запрошенного пула. Downstream invalidation выполняется один раз.
- UI перед каждым comparison сначала вызывает diagnostics ensure, затем строгий
  `/compare`. Backend comparison gate не ослаблен и по-прежнему отклоняет прямые
  запросы без diagnostics.
- Для Ljung–Box, Jarque–Bera, ARCH-LM и Durbin–Watson введена общая проверка
  конечности statistic/p-value. Нулевая дисперсия residuals и иные численно
  неопределённые результаты маркируются `applicable=false`, `warning`, значения
  становятся `null`; ложный статус `pass` и невалидный JSON исключены.
- Schema version Modeling artifacts повышена до 3. Сохранённые diagnostics с
  `NaN/Inf` признаются stale и безопасно пересчитываются.

### TDD и проверки

- RED API: `/diagnostics/ensure` отсутствовал (404).
- RED UI: первый ответ ensure ошибочно интерпретировался как comparison, что
  подтвердило отсутствие двухшаговой orchestration.
- RED numerical: constant residuals возвращали non-finite statistic.
- Modeling backend/core/API: 67/67 PASS.
- Modeling UI: 58/58 PASS.
- TypeScript embedded/standalone: PASS.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 459 kB.
- `py_compile` и `git diff --check`: PASS.

### Изменённые файлы Task 106

- `apps/api/routers/diagnostics.py`
- `apps/api/routers/modeling_session.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `tests/api/test_diagnostics.py`
- `tests/api/test_modeling_workflow.py`

---

## Task 107 — Атомарная подготовка diagnostics в comparison

Дата: 2026-09-04. База: `main @ a363837488901ce71f8520f6936cf245d60bd07f`.
Включает незакоммиченные hotfix Task 105–106; commit/push и production deploy не выполнялись.

### Воспроизведение и первопричина

- После Task 106 UI всё ещё мог получить: `Для comparison нужны diagnostics каждого
  backtest: theta, naive, drift, mean`.
- Живой Render backend проверен через Vercel proxy: `/diagnostics/ensure` существует
  и отвечает предметной валидацией 409, а не 404. Причина не сводилась к отсутствию
  нового endpoint на backend.
- Task 106 разбивал одну пользовательскую операцию на два HTTP-запроса:
  `diagnostics/ensure`, затем `/compare`. Каждый запрос независимо читал и полностью
  перезаписывал JSON-документ сессии в Redis. Запрос, начавшийся со старого снимка,
  мог сохраниться между этими шагами и удалить только что рассчитанные diagnostics.
- Production-shaped тест с `RedisSessionStore`/`fakeredis` детерминированно
  воспроизвёл окно: ensure сохраняет оба отчёта, затем устаревший snapshot
  перезаписывает сессию; прежний прямой compare видел пустой diagnostics map и
  возвращал тот же 409. MemorySessionStore этот класс проблемы маскировал aliasing.

### Исправление

- `/v1/session/modeling/compare` теперь сам обеспечивает полный prerequisite:
  после проверки backtests, execution/OOF lineage, cohort и tuning lineage он
  переиспользует актуальные diagnostics и рассчитывает отсутствующие либо stale.
- Подготовка отчётов выполняется в отдельном snapshot без мутации сессии. Только
  после успешной валидации diagnostics, applicability и построения comparison
  diagnostics и comparison сохраняются вместе одним `store.save()`.
- Fail-closed контракт сохранён: отсутствующий, incomplete, неподписанный,
  несопоставимый или stale относительно tuning backtest по-прежнему отклоняется;
  diagnostics не синтезируются без валидного OOF lineage.
- UI comparison упрощён до одного `/compare` запроса. Это устраняет наблюдаемое
  промежуточное состояние и остаётся совместимым со старым клиентом: даже если он
  вызывает `/compare` напрямую, backend сам выполняет обязательную диагностику.
- Явный `/diagnostics/ensure` сохранён для batch-подготовки и повторного использования.

### TDD и проверки

- RED: прямой `/compare` после двух валидных backtests без ручных diagnostics
  вернул 409 с `missing_diagnostics=[naive, drift]`, полностью повторив симптом.
- Добавлен Redis regression test с принудительной перезаписью stale snapshot между
  ensure и compare; новый compare восстанавливает diagnostics и сохраняет comparison.
- Точечные API/Redis тесты: 3/3 PASS.
- Полный Modeling backend/core/API набор: 153 PASS; 2 известных stale-теста базы
  остались красными (`1.0.0-draft` против `1.1.0-draft` и удалённый Task 102
  heuristic `auto_ensemble_trigger`). Изменения Task 107 их не затрагивают.
- Modeling UI: 62/62 PASS.
- TypeScript embedded/standalone: PASS с принятыми флагами
  `--ignoreDeprecations 6.0 --noUncheckedSideEffectImports false`.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 459 kB. Временный Node memory shim после проверки удалён.
- `py_compile` и `git diff --check`: PASS.

### Изменённые файлы Task 107

- `apps/api/routers/modeling_session.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `tests/api/test_modeling_workflow.py`

---

## Task 108 — Верификация MASE > 1,05 для всего comparable pool

Дата: 2026-09-04. База: рабочее состояние после Task 107 на
`main @ a363837488901ce71f8520f6936cf245d60bd07f`.
Исследование и воспроизведение; production-код не изменялся.

### Наблюдение

- На экране сравнения при 120 OOF-точках все восемь моделей, включая `naive` и
  `drift`, получили MASE от 2,461 до 6,402 и одинаковое предупреждение
  `MASE ... выше 1.05; требуется осознанный override`.
- 120 OOF-точек соответствуют используемой платформой схеме 5 folds × horizon 24.

### Проверка реализации

- Production backtest рассчитывает fold-local denominator только на train:
  `mean(abs(y[t] - y[t-m]))`, где `m` — подтверждённый seasonal period либо 1.
- Fold MASE равен `MAE(test forecast) / train scale`; итоговый MASE — взвешенное
  по числу test-точек среднее fold MASE. Формула, отсутствие leakage и aggregation
  проверены численно до точности округления.
- Это стандартный scale MASE, но denominator не является ошибкой фактически
  рассчитанного OOF baseline на том же многокроковом горизонте.

### Воспроизведение

- На случайном блуждании длиной 240, `m=1`, 5 expanding folds × 24 точки получен
  тот же паттерн: все модели выше 1; значения 3,430–3,852, Naive = 3,430.
- Monte Carlo из 100 случайных блужданий подтвердил horizon effect для Naive:
  H=1 — mean 0,992 и 43% запусков выше 1,05; H=6 — 1,858 и 99%;
  H=12 — 2,466 и 100%; H=24 — 3,409 и 100%.
- Для random walk ожидаемая абсолютная ошибка шага `h` растёт примерно как
  `sqrt(h)`, тогда как denominator MASE остаётся однокроковым train scale.
  Поэтому средний 24-шаговый MASE самого Naive закономерно существенно выше 1.

### Вывод и корректировка методологии

- Систематической ошибки в численном расчёте MASE нет.
- Есть систематическая ошибка семантики UI/comparison: абсолютный порог
  `MASE <= 1.05` трактуется как допуск относительно baseline и требует override
  для каждой модели. На multi-step fixed-origin backtest этот порог не сравнивает
  модель с фактическим OOF baseline и потому почти неизбежно помечает весь pool.
- Task 102 уже использует правильную основу выбора: primary loss модели против
  лучшего фактически рассчитанного baseline на тех же aligned OOF-точках.
- Рекомендуемое исправление: оставить MASE как scale-free метрику и явно показать
  её train-only denominator/period, но убрать `MASE <= 1.05` из eligibility gate.
  Если нужен допуск 5%, применять его к отношению `model OOF primary loss /
  best baseline OOF primary loss` на том же cohort и horizon.

### Изменённые файлы Task 108

- `worklog2.md`

---

## Task 109 — Спецификация: Аутентификация пользователей

Спроектирован слой аутентификации, согласованный с ROLES_AND_PLANS_SPEC.md
и spec_billing_accounts.md через явное трёхслойное разграничение
(Authentication → Account/Billing → Role/Plan/Capability), без правок
в уже принятых контрактах. Артефакт: spec_auth.md. Синхронизация:
main @ a42df0a.

Ключевые решения: раздельные флоу для embedded (точка расширения,
внутренний IdP CISStat — открытый вопрос) / standalone (email+пароль,
OAuth) / demo (passwordless email, переиспользуется как общий механизм
входа, не демо-специфичная ветка); Credential-сущность отделена от
Principal; access-JWT принципиально без закэшированных прав (только
principal_id) — прямое следствие уже данных платформой обещаний
мгновенного пересчёта плана/seats; refresh-токен с ротацией и
reuse-detection; явно разобрана кросс-доменная проблема Vercel↔render.com
(cookie vs BFF-прокси) как блокирующий вопрос Этапа 1; API-ключи —
отдельный от сессии механизм, метеринг CU на ключ.

Статус: архитектурный дизайн передан на ревью, реализация не начата
(коммит/push в main запрещён протоколом AGENTS.md). 5 открытых вопросов
к тимлиду (§11), два блокирующих (внутренний IdP, cookie vs BFF).

---

## Task 110 — Горизонт-согласованный baseline gate и прозрачная MASE

Дата: 2026-09-04. База: `main @ 5f25c62c1f36f080ee3b90c90c77ffcd13041782`.
Commit/push и production deploy не выполнялись.

### Проблема и контракт решения

- Task 108 подтвердил, что высокий MASE при multi-step fixed-origin backtest не
  является арифметической ошибкой: denominator строится по однокроковым
  train-only seasonal differences, тогда как ошибка прогноза растёт с горизонтом.
- Прежний gate `MASE <= 1.05` поэтому систематически создавал ложный риск для
  всего comparable pool, включая сами baseline-модели.
- MASE сохранена как scale-free метрика ранжирования. Eligibility теперь
  определяется только отношением primary OOF loss модели к loss лучшего
  фактически рассчитанного baseline на одних и тех же OOF-точках, folds и
  горизонте: `model_loss / best_baseline_loss <= 1.05`.
- На этапе Comparison зафиксирована RMSE. На этапе Selection тот же контракт
  применяется к выбранной policy-метрике (`RMSE` либо `MAE`).

### Реализация

- В API добавлены типизированные `OofBaselinePolicy`,
  `OofBaselineComparison`, `MaseAuditContext` и fold-local MASE scales.
- Comparison выбирает лучший фактически рассчитанный baseline детерминированно,
  выдаёт для каждой модели loss ratio, relative improvement, tolerance и
  signed eligibility. Policy и MASE context включены в comparison signature.
- Проверяется не только точное совпадение OOF facts/folds/evaluation scale, но и
  совпадение train-only MASE scale каждого fold между моделями.
- MASE audit раскрывает формулу, denominator policy, seasonal period, horizon,
  агрегацию, scale каждого fold и явный флаг
  `is_same_horizon_baseline_comparison=false`.
- Selection policy повышена до `selection-v2-horizon-baseline`; verdict каждого
  кандидата и проверенного ensemble рассчитывается по фактической primary loss.
  Override требуется только при выходе за OOF baseline tolerance, а не при
  абсолютном MASE выше 1,05. Учтён случай baseline loss = 0 без `Infinity` в JSON.
- Endpoint выбора повторно сверяет подписанный verdict с primary metric/loss и
  baseline loss. В selection result и Model Card сохраняются baseline model,
  ratio, improvement, tolerance, eligibility, acknowledgement и полный MASE
  context.
- UI показывает отдельный блок «Контекст MASE» и отдельную колонку OOF baseline
  ratio. Старый фильтр/текст `MASE <= 1.05` удалён.
- Modeling artifact schema повышена с 3 до 4. При миграции валидные backtests и
  diagnostics сохраняются, но старые comparison/selection/Model Cards
  инвалидируются, поскольку они не содержат нового проверяемого verdict.
- `rules/modeling.yaml` и typed loader приведены к единому контракту.

### TDD и проверки

- RED: 4 ожидаемых падения подтвердили отсутствие `seasonal_period`/MASE audit в
  Comparison, baseline tolerance в Selection и нового контракта в spec/loader.
- Добавлены регрессии для сценария со всеми `MASE > 1.05`: сильная ETS проходит
  при OOF RMSE ratio 0,8, слабый Mean не проходит при ratio 2,0.
- Добавлены проверки границы допуска 1,05, mismatch train-only MASE scales,
  API lineage, Model Card и миграции schema v3 → v4.
- Финальный Modeling backend/core/API/spec прогон: 101 PASS; остались два
  известных stale-теста базы, не связанные с Task 110: ожидание версии
  `1.0.0-draft` вместо текущей `1.1.0-draft` и удалённого в Task 102 эвристического
  `auto_ensemble_trigger`.
- Расширенный прогон в ходе реализации: 168 PASS и те же 2 known stale failures.
- Modeling UI: 62/62 PASS; после финального аудита изменённый suite: 5/5 PASS.
- TypeScript embedded/standalone, `py_compile`, `git diff --check`: PASS.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 459 kB; временный memory shim удалён.

### Изменённые файлы Task 110

- `apps/api/modeling_comparison.py`
- `apps/api/modeling_selection.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/lib/modeling.ts`
- `rules/modeling.yaml`
- `src/catalog/modeling_spec_loader.py`
- `tests/api/test_modeling_comparison_spec.py`
- `tests/api/test_modeling_workflow.py`
- `tests/test_modeling_spec.py`
- `tests/unit/test_modeling_comparison.py`
- `tests/unit/test_modeling_selection.py`

---

## Task 111 — Единая capability-матрица моделей и корректная завершённость степпера

Дата: 2026-09-04. База: `main @ 29911403c1b16ee033f4872455cfdab8b6d322be`.
Commit/push и production deploy не выполнялись.

### Воспроизведённая проблема

- Каталог содержит 24 модели, но production backtest реализован для 9, tuning —
  для 3. При этом сведения о доступности были распределены между backend и
  hardcoded-условиями UI, а diagnostics ошибочно рекламировались только для
  трёх моделей, хотя фактически работают по подписанным OOF-остаткам всех 9.
- Степпер отмечал `backtest=done` после bootstrap baseline либо одного успешного
  запуска. Поэтому последующие стадии могли открываться до обработки полного
  runnable-пула.
- Comparison принимал произвольное подмножество сохранённых backtests и не мог
  доказать, что остальные кандидаты рассчитаны либо осознанно исключены.
- В UI tuning-модели были зашиты вручную; справка содержала WaveNet вместо
  фактической N-HiTS.

### Единый capability-контракт

- Введён versioned-контракт `model-capabilities-v1`: для каждой из 24 моделей
  возвращается полная матрица всех 11 стадий со статусом `available`,
  `not_applicable`, `blocked` либо `not_implemented`, флагом `required`,
  допустимым action и человекочитаемой причиной.
- Единственными источниками runtime-возможностей стали
  `PRODUCTION_BACKTEST_MODEL_IDS`, `PRODUCTION_TUNING_MODEL_IDS` и
  model-agnostic diagnostics для всего production backtest-набора.
- Каталог не выдаёт фиктивную готовность: 9 моделей имеют production backtest,
  15 остаются `catalog_only`/`not_implemented`. Профильная неприменимость
  production-модели представлена отдельным статусом `blocked`.
- Контракт опубликован в candidate API, typed Python/TypeScript schemas и
  `rules/modeling.yaml`; pipeline spec повышен до 1.1. UI получает действия из
  API, а не из локального списка моделей.

### Корректная завершённость и трассируемый scope

- В session artifacts добавлен `execution_scope`: обязательные, включённые,
  выполненные и ожидающие backtests/tuning/diagnostics, а также подписанные
  решения об исключении backtest и сохранении default-параметров без tuning.
- `baseline_estimation` завершается только после всех runnable baselines;
  `backtest` — после всех включённых runnable-моделей; `tuning` — после tuning
  либо явного skip каждой рассчитанной tunable-модели; `diagnostics` — после
  текущего signed OOF-report каждой рассчитанной включённой модели.
- Добавлены endpoints осознанного исключения/возврата non-baseline модели и
  явного tuning skip. Оба требуют подтверждения и причины; обязательный baseline
  исключить нельзя.
- Comparison блокирует pending backtests и tuning, запрещает передать неполный
  model subset и использует точный `all runnable − acknowledged exclusions`
  scope. Scope включён в comparison signature, response и Model Card lineage.
- Modeling artifact schema повышена с 4 до 5; старые downstream verdicts
  инвалидируются, валидные execution/OOF runs сохраняются.
- UI показывает прогресс execution scope, capability-статусы выбранной модели
  по 11 стадиям, управляемое исключение с причиной и действие «Оставить
  defaults». После baseline/backtest клиент перечитывает вычисленный backend
  state и больше не помечает стадии завершёнными локально.

### TDD и проверки

- RED: новый контрактный тест сначала остановился на collection с `ImportError`
  из-за отсутствующего `MODELING_CAPABILITY_CONTRACT_VERSION`; требуемые scope
  endpoints и capability-driven UI также отсутствовали в исходной базе.
- Контрактная/API-регрессия: 33/33 PASS, включая матрицу 24×11, отсутствие
  ложного `backtest=done`, обязательность полного scope, explicit exclusions и
  tune-or-skip.
- Расширенный Modeling-прогон: 118 PASS; два известных stale-теста базы не
  относятся к Task 111 — ожидание `1.0.0-draft` вместо текущей
  `1.1.0-draft` и удалённого в Task 102 `auto_ensemble_trigger`.
- Modeling UI: 65/65 PASS. TypeScript embedded/standalone, `py_compile` и
  `git diff --check`: PASS.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 460 kB; временный memory shim удалён.

### Изменённые файлы Task 111

- `apps/api/model_readiness.py`
- `apps/api/modeling_comparison.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/routers/models.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/lib/modeling.ts`
- `rules/modeling.yaml`
- `src/catalog/modeling_spec_loader.py`
- `tests/api/test_modeling_workflow.py`
- `tests/unit/test_model_capability_matrix.py`
- `tests/unit/test_model_readiness_candidates.py`

---

## Task 112 — Защита tuning result от Redis lost update

Дата: 2026-09-04. База: `main @ fc21b5be9c62be674ff468216d6b20c801284332`.
Commit/push и production deploy не выполнялись.

### Воспроизведение и первопричина

- После фактически выполненного ETS tuning Comparison мог сообщить
  `Tuning не выполнен и не пропущен явно: ets`, а действие «Оставить defaults» —
  `Модель уже имеет текущий tuning result`.
- Последовательный API-сценарий работает корректно: после tuning
  `completed_tuning_model_ids=[ets]`, `pending_tuning_model_ids=[]`, Comparison
  отвечает 200, а tuning skip закономерно отклоняется.
- Production-shaped Redis-тест воспроизвёл оба сообщения: старый снимок с
  default-backtest ETS и без tuning целиком перезаписывал более свежий JSON
  сессии; более поздняя запись свежего снимка снова делала tuning видимым.
- `RedisSessionStore.save()` использовал безусловный `SETEX` без revision/CAS.
  Дополнительно read endpoints сохраняли session даже при отсутствии изменений,
  а UI запускал два одинаковых state refresh после одной tuning-операции.
- UI получал `completed_tuning_model_ids`, но не передавал их в tuning-компонент,
  поэтому кнопка «Оставить defaults» оставалась доступной после расчёта.

### Исправление

- В `AnalysisSession` добавлен backward-compatible `storage_revision`: старые
  Redis-документы без поля читаются как revision 0 и обновляются при первом
  успешном сохранении.
- Redis save переведён на optimistic CAS через `WATCH` → проверку revision →
  `MULTI/SET EX/EXEC`. Stale snapshot получает `SessionConflictError` и больше
  не может удалить tuning, diagnostics или другие свежие artifacts. Контракт
  соответствует официальным Redis/redis-py и Upstash WATCH transactions:
  https://redis.io/docs/latest/develop/clients/redis-py/transpipe/ и
  https://upstash.com/docs/redis/commands/transactions/watch.
- MemorySessionStore поддерживает тот же revision-контракт для снимков без
  aliasing. FastAPI преобразует конфликт в предметный HTTP 409 с указанием, что
  актуальные результаты сохранены и операцию следует повторить.
- Modeling `/context` и `/state` сохраняют сессию только при фактическом
  изменении pipeline/artifacts. Стабильный state read больше не увеличивает
  revision и не создаёт лишнего окна конкуренции.
- UI использует `completed_tuning_model_ids`: после успешного tuning показывает
  disabled «Tuning выполнен», не предлагает несовместимый defaults skip и
  оставляет явное действие «Перезапустить тюнинг».
- Удалён второй дублирующий state refresh; один callback после успешной операции
  перечитывает каноническое backend-состояние.

### TDD и проверки

- RED backend: новые тесты остановились на импорте отсутствующего
  `SessionConflictError`. RED UI: TypeScript сообщил об отсутствующем prop
  `tuningCompletedModelIds`.
- Три точные Redis-регрессии PASS: stale tuning snapshot отклонён, завершённый
  ETS не возвращается в pending, старый diagnostics snapshot не затирает
  подготовленные отчёты. Comparison после защищённого ETS tuning отвечает 200.
- SessionStore + Modeling API: 95/95 PASS. Modeling UI: 66/66 PASS.
- Полный API-прогон: 561 PASS; 15 существующих падений базы воспроизводятся
  изолированно и не связаны с Task 112: 12 correction/type-schema fixture
  failures, ожидание старой spec version и два ожидания ARIMA grid.
- TypeScript embedded/standalone, `py_compile`, `git diff --check`: PASS.
- Production build standalone: PASS, 13/13 static pages, `/modeling` включён,
  First Load JS 460 kB; временный memory shim удалён.

### Изменённые файлы Task 112

- `apps/api/main.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/session_store.py`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `tests/api/test_modeling_workflow.py`
- `tests/api/test_session_store.py`

---

## Task 113 — Read-only EDA hand-off и перекомпоновка UI «Моделирование»

Дата: 2026-09-04. База: `main @ a974886b6b18b6b270de0d32a7ae691b696908a6`.
Commit/push и production deploy не выполнялись.

### Проблема и принятый UI-контракт

- Активный селектор целевой колонки в Modeling вызывал
  `POST /v1/session/target-column`. Серверный `set_target_column()` при
  изменении цели сбрасывает passport/checkpoint history, EDA validation
  strategy, Modeling pipeline и artifacts. Так поздний UI-шаг мог
  инвалидировать результаты предыдущих модулей.
- Legacy-форма «Профиль данных» создавала второй ручной источник
  параметров ряда рядом с каноническим session-контекстом EDA.
- Принят один источник истины: `modeling_entry` EDA hand-off. Селектор
  цели сохранён как визуальное свидетельство, но всегда `disabled`.
  Изменение цели остаётся в upstream-этапах до фиксации hand-off.

### Реализация

- Из `TsAnalysisModeling` удалены local `DataProfile`, его ручные inputs/selects,
  автозаполнение из `activeDataset` и target-column POST handler.
- Вместо них в левой колонке размещён компактный read-only блок
  «Контекст моделирования»: target, временная колонка, число
  наблюдений, частота, число рядов/X, сезонность, регулярность,
  validation strategy/folds/horizon/gap и fingerprint checkpoint.
- Без `modeling_entry` показывается EDA gate; при неготовом, но
  существующем hand-off контекст остаётся видимым, а запуск пула
  блокируется до `ready=true`.
- Перезагрузка одноимённого файла теперь определяется по `datasetId`,
  а не только по filename. До ответа session API очищаются цель,
  контекст, пул, backtests, execution scope и прогресс предыдущего
  dataset.
- Legacy-поля `ActiveDataset` оставлены в shell-типе для обратной
  совместимости, но больше не формируют Modeling profile.

### TDD и проверки

- До производственного кода переписаны UI-регрессии: новый
  read-only hand-off context, удаление legacy-формы, всегда disabled
  target selector, отсутствие target POST и refetch по новому `datasetId`.
- RED source-contract: 4/4 проверки ожидаемо падали на исходном UI.
  После реализации тот же контракт: 4/4 PASS.
- `git diff --check`: PASS.
- Jest, TypeScript typecheck и production build в текущем sandbox не запущены:
  checkout не содержит `node_modules`, локальные `jest`, `tsc` и `next`
  отсутствуют, а команда установки зависимостей остановлена
  сетевыми ограничениями среды.

### Изменённые файлы Task 113

- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/context/AppShellContext.tsx`

---

## Task 114 — Атомарное «Оставить defaults» для полного tuning scope

Дата: 2026-09-04. База: `main @ fbb550b066a215d05485a3c8d7974cc2b15da1df`.
Commit/push и production deploy не выполнялись.

### Воспроизведение и первопричина

- Comparison правильно требует решение `tune-or-explicit-defaults`
  для каждой завершённой tunable-модели. В воспроизведённом
  scope это `arima`, `ets`, `ets_damped`.
- UI-кнопка «Оставить defaults» визуально выглядела как решение
  для всего шага, но вызывала `POST /tuning/skip` только для
  одной текущей модели селектора. Pending scope не показывался,
  поэтому переход к Comparison оставался ложно разрешённым.
- Повторная генерация кандидатов, которую UI использует и как
  session refresh, безусловно пересоздавала `execution_scope` с пустыми
  `tuning_skips` и `backtest_exclusions`. После remount/refresh уже
  подтверждённые defaults исчезали, и Comparison снова видел все
  три модели как pending.

### Исправление

- Добавлена атомарная session-операция
  `POST /v1/session/modeling/tuning/skip-pending`. Она фиксирует
  одно осознанное решение для всех `pending_tuning_model_ids`, но
  сохраняет отдельную audit-запись с причиной, acknowledgement и
  timestamp по каждой модели.
- Операция отклоняется до завершения полного backtest scope и
  во время активного tuning job. Повторный запрос идемпотен и
  возвращает `status=unchanged`.
- Candidate refresh больше не обнуляет execution scope:
  `_ensure_execution_scope()` сохраняет и фильтрует только валидные
  decisions относительно нового runnable-контракта.
- UI показывает канонический backend-список «Ожидают решения»,
  а кнопка явно названа «Оставить defaults для всех (N)».
  После операции UI ждёт повторного чтения backend state и только
  затем снимает loading-блокировку.

### TDD и проверки

- RED source-contract: отсутствовали atomic endpoint, UI-вызов и
  отображение pending scope — 3/3 FAIL.
- Добавлена API-регрессия полной цепочки:
  `arima, ets, ets_damped pending` → один defaults request → `pending=[]` →
  candidate regeneration не сбрасывает decisions → diagnostics → Comparison 200.
- UI-регрессии проверяют один batch-запрос без `model_id`,
  канонический pending-список, partial scope и завершённое состояние.
- GREEN source-contract: 6/6 PASS. `py_compile` для изменённых
  Python-файлов и `git diff --check`: PASS.
- Полные pytest/Jest, TypeScript typecheck и production build в текущем
  sandbox не запущены: checkout не содержит `node_modules`,
  `pytest`/`fastapi`, локальные `jest`, `tsc` и `next` отсутствуют,
  а установка зависимостей ограничена сетевой политикой среды.

### Изменённые файлы Task 114

- `apps/api/routers/modeling_session.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `tests/api/test_modeling_workflow.py`

---

## Task 115 — Client crash при переходе Tuning → Diagnostics

Дата: 2026-09-04. База: `main @ fbb550b066a215d05485a3c8d7974cc2b15da1df`
+ working tree Task 114. Commit/push и production deploy не выполнялись.

### Воспроизведение и первопричина

- После подтверждения defaults в общем `result` оставался response
  `{model_ids, status: "skipped", execution_scope}`.
- При клике на «Диагностика» React сначала рендерил новый
  `stageId` со старым `result`, и только потом запускал `useEffect`,
  который должен был очистить response.
- В этом переходном render tuning-response без проверки приводился
  к `DiagnosticsResult`. Вызов `diagnosticsResult.diagnostics.map(...)` для
  отсутствующего поля выбрасывал client-side `TypeError` до работы
  effect, что и давало белый Application error screen.

### Исправление

- Общий response state заменён на provenance-контракт
  `WorkflowResult {stageId, value}`.
- Актуальный `result` выдаётся в render только если его
  `stageId` совпадает с текущей остановкой. Эта проверка синхронна
  и не зависит от порядка запуска `useEffect`.
- Перед рендерингом diagnostics table добавлена runtime-проверка
  `Array.isArray(diagnosticsResult.diagnostics)`, чтобы malformed API response также
  не мог уронить всю клиентскую страницу.

### TDD и проверки

- До production-кода добавлена регрессия: получить tuning/defaults
  response, переключить тот же component instance на Diagnostics и проверить
  отсутствие exception/ложного diagnostics report.
- RED source-contract: 3/3 FAIL — response не хранил producing stage,
  render не сверял stage, diagnostics shape не проверялся.
- GREEN source-contract: 3/3 PASS. `git diff --check` и Python `py_compile`
  кумулятивных Task 114 files: PASS.
- Jest, TypeScript typecheck и production build не запущены: в checkout
  отсутствуют `node_modules`, `jest`, `tsc` и `next`.

### Изменённые файлы Task 115

- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`

---

## Task 116 — Контекстное «Описание» и единая панель управления Modeling

Дата: 2026-09-04. База: `main @ fbb550b066a215d05485a3c8d7974cc2b15da1df`
+ working tree Task 114–115. Commit/push и production deploy не выполнялись.

### Проблема и UI-контракт

- Центральное окно «Описание» по умолчанию оставалось пустым и предлагало
  нажать одну из служебных кнопок. Поэтому активная остановка 11-шагового
  степпера не имела собственного методологического объяснения.
- Контексты «Справка», «Метрики и алгоритм» и «Полный пайплайн» не имели
  единого явного возврата. При смене остановки выбранная операция могла
  остаться в окне и перестать соответствовать активному шагу.
- Правая колонка не имела принятого на вкладках Validation/Preprocessing/EDA
  заголовка «Панель управления».
- Во время первичной загрузки Движка применимости отображался пустой блок
  «Сравнение бэктестов» с преждевременной инструкцией запустить бэктест.

Принят контракт: описание активной остановки является базовым состоянием;
выбор операции в панели временно замещает его; явный возврат, смена остановки
или смена выбранной модели восстанавливают описание текущей остановки.

### Реализация

- Для всех 11 остановок добавлены подробные описания: цель, входы/результат,
  методологические ограничения и критерий завершения. Стартовое состояние
  теперь сразу показывает «Остановка · Пул кандидатов», а не пустой prompt.
- Контексты операций охватывают «Метрики и алгоритм», «Полный пайплайн»,
  запуск/пересчёт бэктеста и управление execution scope. В заголовке окна
  показывается «Операция · …» и доступно действие «К описанию остановки».
- Любой переход по степперу синхронно сбрасывает контекст операции и выводит
  описание новой остановки. Выбор другой модели также исключает stale-текст
  предыдущего кандидата. Раскрытое описание сворачивается при смене контекста.
- Над правой колонкой добавлен заголовок «Панель управления» с тем же
  визуальным паттерном, что используется в «Предобработке».
- Пока выполняется первичная загрузка Движка применимости, пустой chart
  заменён отдельным loading-state с согласованным текстом
  «Загружаю доступные модели, минутку...». После загрузки возвращается
  штатное «Сравнение бэктестов» и фактическая визуализация.

### TDD и проверки

- До production-кода добавлены регрессии: базовое описание активной
  остановки, переход на Диагностику, выбор операции и явный возврат,
  автоматический возврат при смене шага, заголовок правой панели и новый
  loading placeholder. RED source-contract: 4/4 FAIL.
- Дополнительно существующая backtest-регрессия проверяет, что нажатие
  «Пересчитать бэктест» переводит окно в контекст соответствующей операции.
- GREEN source-contract: 9/9 PASS; `git diff --check`: PASS.
- Jest, TypeScript typecheck и production build не запущены: checkout не
  содержит `node_modules`, локальные `jest`, `tsc` и `next` отсутствуют;
  попытка workspace-команд остановлена сетевой политикой среды до запуска.

### Изменённые файлы Task 116

- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`

--

## Task 117 — Loading-state Modeling с первого render

Дата: 2026-09-05. База: `main @ fa3a5190030b01ee67015f1b1bd3e0ecd812af7a`.
Commit/push и production deploy не выполнялись.

### Воспроизведение и первопричина

- При первом открытии Modeling второе центральное окно на один render
  показывало пустое «Сравнение бэктестов», а затем переключалось на
  «Загружаю доступные модели, минутку...». Этот стартовый экран создавал
  ложное впечатление, что модели уже загружены и пользователь должен вручную
  запустить бэктест.
- Условие loading-state использовало только `isLoading && !hasFetched`.
  Но `isLoading` включается внутри `fetchCandidates`, который запускается
  лишь после асинхронного получения `/v1/session/modeling/context`.
  Поэтому самый первый render неизбежно проходил в ветку comparison.

### Исправление

- Добавлен derived-флаг `isApplicabilityBootstrapping`, активный синхронно
  уже на первом render при ещё отсутствующем modeling context.
- Bootstrap остаётся активным после получения готового EDA hand-off и до
  успешного завершения Движка применимости. Между context response и стартом
  candidates-effect больше нет промежуточного comparison-кадра.
- Ошибка загрузки или неготовый EDA hand-off завершают bootstrap и передают
  отображение существующим предметным error/gate-состояниям. Повторная ручная
  загрузка после уже полученного пула не скрывает актуальное сравнение.
- Второе окно теперь с первого кадра открывается состоянием
  «Загружаю доступные модели, минутку...», а «Сравнение бэктестов» появляется
  только после завершения первичной загрузки.

### TDD и проверки

- До production-кода добавлена регрессия, проверяющая первое синхронное
  состояние сразу после `render(<TsAnalysisModeling />)`, до разрешения
  асинхронного context-запроса.
- RED source-contract: 2/2 FAIL — отсутствовали полный bootstrap-state и его
  использование в окне сравнения. GREEN source-contract: 4/4 PASS.
- `git diff --check`: PASS.
- Jest, TypeScript typecheck и production build не запущены: чистый worktree
  не содержит `node_modules`, локальные `jest`, `tsc` и `next` отсутствуют.

### Изменённые файлы Task 117

- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`

---

## Task 118 — Единая строка фильтров пула моделей

Дата: 2026-09-05. База: `main @ fa3a5190030b01ee67015f1b1bd3e0ecd812af7a`
+ working tree Task 117. Commit/push и production deploy не выполнялись.

### UI-контракт

- Под окном «Описание» фильтры «Исполнение» и «Применимость» находились
  на двух строках, хотя управляют одной выдачей пула кандидатов.
- Согласована единая горизонтальная панель: «Исполнение» остаётся слева,
  «Применимость» находится в той же строке и прижата к правому краю.
- Для заголовка «Применимость» выбрана иконка Lucide `BadgeCheck`:
  она семантически обозначает проверенное соответствие модели условиям,
  тогда как `Filter` у «Исполнения» продолжает обозначать фильтрацию по
  технической доступности.

### Реализация

- Две независимые строки заменены общим `model-filter-toolbar` с
  `justify-between`; группа применимости использует `ml-auto justify-end`.
- Toolbar сохраняет одну строку через `min-w-max`. При недостаточной ширине
  родитель включает горизонтальную прокрутку вместо непредсказуемого переноса
  группы применимости под исполнение.
- К «Применимость» добавлена декоративная `BadgeCheck` с `aria-hidden=true`;
  существующие фильтры, счётчики и состояния активных кнопок не изменены.

### TDD и проверки

- До production-кода добавлена регрессия структуры toolbar: обе группы имеют
  общего родителя, группа применимости выровнена справа, семантическая иконка
  присутствует и скрыта от accessibility tree как декоративная.
- RED source-contract: 3/3 FAIL. GREEN source-contract: 5/5 PASS.
- `git diff --check`: PASS.
- Jest, TypeScript typecheck и production build не запущены: checkout не
  содержит `node_modules`, локальные `jest`, `tsc` и `next` отсутствуют.

### Изменённые файлы Task 118

- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`

---

## Task 119 — Логотип в шапке ProductHeader + усиление названия

Дата: 2026-09-05. База: main @ 385f69f6a4c6d94df23587fb631ff94d3f863f97.
Commit/push и production deploy не выполнялись.

### UI-контракт

- Слева от текстового названия "CISStat TS Analysis" в `ProductHeader`
  добавлен логотип `public/logo_TS.png`.
- Начертание названия усилено с `font-semibold` до `font-bold`,
  размер шрифта увеличен (явный `text-[15px]` вместо унаследованного).

### Реализация

- Логотип и название обёрнуты в общий `flex items-center gap-2`,
  порядок в DOM: логотип → название → навигация (без изменений
  структуры навигации).
- Логотип рендерится через `next/image` с `fill` внутри контейнера
  `relative h-7 w-7` — не требует знания реальных пропорций PNG,
  не искажает изображение; высота согласована с остальными круглыми
  элементами шапки (кнопка личного кабинета — тот же `h-7 w-7`).

### TDD и проверки

- До production-кода добавлен `ProductHeader.test.tsx`: логотип
  предшествует названию в DOM-порядке; название имеет `font-bold`
  (не `font-semibold`) и `text-[15px]`.
- Jest, TypeScript typecheck и production build не запущены: checkout
  не содержит `node_modules`, локальные `jest`, `tsc` и `next`
  отсутствуют.

### Изменённые файлы Task 119

- `apps/standalone/components/ProductHeader.tsx`
- `apps/standalone/components/ProductHeader.test.tsx`

---

## Task 120 — Исправление logo asset и production bold в ProductHeader

Дата: 2026-09-05. База: `main @ 7d143cccf33bcf618589a88e96c43e7bf2b35fb7`.
Commit/push и production deploy не выполнялись.

### Воспроизведение и первопричины Task 119

- `ProductHeader` запрашивал `/logo_TS.png`, однако файл находился в
  корневом `public/` монорепозитория. Standalone Next.js собирается из
  `apps/standalone` и обслуживает статические URL только из
  `apps/standalone/public`, поэтому production-запрос логотипа возвращал 404
  и браузер показывал значок сломанного изображения с alt-текстом.
- В компонент был добавлен класс `font-bold`, но standalone Tailwind config
  сканировал только `./app/**/*` и `../../packages/ui/**/*`. Каталог
  `./components/**/*`, где расположен `ProductHeader`, отсутствовал в content
  scan. Уникальные классы `font-bold` и `text-[15px]` не гарантированно
  попадали в production CSS, поэтому название сохраняло обычное начертание.
- Тест Task 119 проверял только наличие className в DOM и существование
  элемента `next/image`, но не наличие физически обслуживаемого файла и не
  production scan Tailwind.

### Исправление

- Точная копия `logo_TS.png` добавлена в канонический public-каталог
  standalone-приложения: `apps/standalone/public/logo_TS.png`. URL компонента
  `/logo_TS.png` теперь соответствует Next.js static-file contract.
- В `apps/standalone/tailwind.config.ts` добавлен glob
  `./components/**/*.{ts,tsx}`, поэтому стили ProductHeader включаются в
  production build.
- Название заменено со `span` на семантический `strong` и сохраняет явные
  классы `font-bold text-[15px]`. Жирное начертание подтверждается и
  семантикой HTML, и сгенерированным Tailwind CSS.

### TDD и проверки

- До production-кода тесты усилены проверками: название рендерится как
  `STRONG`, PNG существует и непуст в `apps/standalone/public`, Tailwind
  content включает standalone components.
- RED source-contract: 3/3 FAIL. GREEN source-contract: 4/4 PASS;
  бинарная копия PNG побайтово совпадает с исходным ассетом.
- `file` подтверждает корректный PNG 1058×1034 RGBA; `git diff --check`: PASS.
- Jest, TypeScript typecheck и production build не запущены: чистый worktree
  не содержит `node_modules`, локальные `jest`, `tsc` и `next` отсутствуют.

### Изменённые/новые файлы Task 120

- `apps/standalone/components/ProductHeader.tsx`
- `apps/standalone/components/ProductHeader.test.tsx`
- `apps/standalone/tailwind.config.ts`
- `apps/standalone/public/logo_TS.png`

---

## Task 121 — Сертификация девятимодельного baseline

Дата: 2026-09-05. База: `main @ 34332f4baa5b1801f270e4997002e8ea16dcaa8a`.
Commit/push и production deploy не выполнялись.

### Сертифицированный scope

- Каталог сохраняет 24 модели, а production baseline строго ограничен девятью
  реально исполняемыми моделями: `naive`, `seasonal_naive`, `drift`, `mean`,
  `ets`, `ets_damped`, `theta`, `arima`, `arima_auto`.
- Все девять имеют реальные backtest и diagnostics actions и единый OOF
  capability-контракт. Реальный tuning сертифицирован для `ets`,
  `ets_damped`, `arima`; у остальных production-моделей tuning корректно
  отмечен как неприменимый, а 15 catalog-only моделей не получают фиктивных
  production actions.
- Добавлен отдельный release-gate
  `tests/unit/test_modeling_mvp_certification.py`, фиксирующий точный состав
  MVP, согласованность registry/capabilities и работу ARIMA grid на минимальном
  двухточечном expanding-window fold.

### Найденные и устранённые блокеры сертификации

- Свежая установка допускала Starlette 1.x, чей TestClient требует другой
  транспортный стек (`httpx2`). Runtime ограничен совместимой веткой
  `starlette>=0.40,<1`, а test dependency — `httpx>=0.27,<1`; проверка выполнена
  также на FastAPI 0.141.1 / Starlette 0.52.1.
- Для statsmodels 0.15 устранён 0-D сбой инициализации ARIMA на минимальном
  CV-fold: при конкретном известном `IndexError` передаются нейтральные
  конечные start parameters, после чего выполняется тот же state-space MLE,
  без synthetic/naive подмены trial.
- CSV loader теперь одинаково работает с FastAPI/Streamlit и простыми
  file-like объектами, сохраняет указатель исходного потока, различает
  обычные заголовки и явно numeric/date headerless input и не принимает буквы
  одноколоночного CSV за разделитель.
- Закрыты обнаруженные compatibility-регрессии Pandas/Pandera: missing-token
  IH не смешивается с реальным значением, проверка сортировки не теряется из-за
  некорректной даты, `required_columns` корректно переводятся в Column contract
  без удалённого аргумента DataFrameSchema.
- Общий Jest setup подключает `@testing-library/jest-dom`; тесты спецификации
  синхронизированы с `modeling.yaml` 1.1.0-draft и отключённой старой
  auto-ensemble MASE-эвристикой.

### TDD и результаты сертификации

- Исходный RED backend: 14 failed, 934 passed, 172 collection errors;
  frontend: 2 failed, 722 passed. Дополнительный Task 121 release-gate:
  1 failed / 1 passed до исправления ARIMA minimum-fold.
- Целевой GREEN после исправлений: 61/61 backend и 4/4 ProductHeader tests.
- Полный backend regression: 1309/1309 PASS, 3/3 snapshots PASS.
- Полный frontend regression: 84/84 suites, 724/724 tests PASS.
- Отдельный modeling smoke: 5/5 PASS — точный capability scope, все девять
  моделей на одном реальном OOF cohort, persisted comparison/selection/
  model-card workflow и подготовка diagnostics для сравнимого пула.
- TypeScript typecheck: embedded PASS, standalone PASS.
- Production build: embedded и standalone PASS, по 13/13 статических страниц,
  `/modeling` включён; First Load JS 464 kB. Для известного ограничения
  sandbox Node 24 `uv_resident_set_memory` применялся временный memory shim
  вне репозитория, после сборок удалённый и не входящий в изменения.
- `pip check`: PASS. `git diff --check`: PASS.
- Live Render/Vercel deploy и удалённый smoke не выполнялись: задача не
  включает публикацию, поэтому сертификация относится к текущему локальному
  коду на указанной базе.

### Изменённые/новые файлы Task 121

- `app/data/file_loader.py`
- `app/eda/ih_analysis.py`
- `apps/api/model_impls/arima.py`
- `apps/api/requirements.txt`
- `jest.setup.js`
- `requirements-dev.txt`
- `tests/api/test_param_space.py`
- `tests/test_modeling_spec.py`
- `tests/unit/test_modeling_mvp_certification.py`
- `validation/engine.py`
- `validation/regularity.py`

---

## Task 122 — Model Execution Contract v2

Дата: 2026-09-05. База: `main @ 02581fc2f83e3f413f9d04a7d05f1968a2b1bcd8`.
Commit/push и production deploy не выполнялись.

### Проектирование и границы задачи

- Перед подключением остальных 15 моделей введена единая typed execution
  boundary `model-execution-v2`; scope Task 122 не расширяет сертифицированный
  production-набор из девяти моделей и не объявляет catalog-only модели
  исполняемыми.
- `ModelExecutionRequest` разделяет train target, train/future covariates,
  train-only связанные ряды и train/future timestamps. В интерфейсе адаптера
  отсутствует holdout target, поэтому случайная передача фактов модели
  исключена конструкцией контракта.
- `ModelExecutionResult` нормализует point forecast, опциональные интервалы,
  metadata и warnings. Request/result fail closed на пустом train, неверных
  горизонтах, несовпадающих размерностях, NaN/Inf, неполных интервалах и
  прогнозе неверной длины.
- Каждая модель описывается immutable definition: family/adapter identity,
  version, input/output kind, fit policy, actions, feature/multivariate flags,
  engine/dependencies и стабильная SHA-256 подпись descriptor. Исполняемый
  callable в публичный descriptor не попадает.

### Реализация и устранённые риски

- Создан `ModelExecutionRegistry` — единственный источник production
  backtest/tune/diagnostics readiness. Старые `PRODUCTION_*_MODEL_IDS` теперь
  вычисляются из registry, поэтому новый адаптер нельзя объявить готовым в
  capability-слое без реальной регистрации исполнения.
- Девять сертифицированных адаптеров перенесены в registry: четыре fixed-origin
  baseline, ETS/ETS Damped/Theta и ARIMA/Auto-ARIMA. Canonical session
  backtest/tuning исполняет их через v2 request/result; legacy predictor map
  сохранён только как compatibility facade для существующих инъекционных
  тестов и клиентов.
- Backtest artifact и TuneResponse сохраняют точный execution descriptor и
  его signature. Candidates API публикует descriptor только для runtime-ready
  моделей, а catalog-only получает `null`; response и session execution scope
  содержат `execution_contract_version=model-execution-v2`.
- TypeScript mirror расширен тем же descriptor union для будущих
  univariate, feature-based, multivariate и volatility adapters.
- Совместимость MVP сохранена: production scope остаётся ровно девять моделей,
  tuning — ровно ETS, ETS Damped и ARIMA; фиктивные forecasts не добавлялись.

### TDD и проверки

- RED до production-кода: collection error
  `ModuleNotFoundError: apps.api.model_execution` в новом contract suite.
- GREEN contract/regression subset: 98/98 PASS; финальный Task 122 contract
  gate: 5/5 PASS.
- Полный backend regression: 1314/1314 PASS, 3/3 snapshots PASS.
- Полный frontend regression: 84/84 suites, 724/724 tests PASS.
- TypeScript: standalone и embedded PASS; production builds выполнили также
  встроенные lint/type checks. Изолированный package-only `tsc` по-прежнему
  показывает существующие ES5/downlevelIteration ошибки в несвязанных
  preprocessing-компонентах, но оба application tsconfig проходят.
- Production build embedded/standalone: PASS, по 13/13 статических страниц,
  включая `/modeling`; First Load JS 464 kB. Временный Node 24 memory shim для
  sandbox `uv_resident_set_memory` после сборок удалён и в задачу не входит.
- `pip check`: PASS. `git diff --check`: PASS.

### Изменённые/новые файлы Task 122

- `apps/api/model_execution.py`
- `apps/api/backtesting.py`
- `apps/api/model_readiness.py`
- `apps/api/modeling_tuning.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/routers/models.py`
- `apps/api/schemas.py`
- `packages/ui/lib/modeling.ts`
- `tests/unit/test_model_execution_contract.py`

---

## Task 122.1 — Завершение Model Execution Contract v2 и устранение bootstrap CAS race

Дата: 2026-09-05. База: `main @ d8b5b77caff87ff076855b3e561214e9b5f2359f`.
Commit/push и production deploy не выполнялись.

### Закрытие аудита Task 122

- В execution definition/request введён обязательный типизированный objective:
  `level_forecast | multivariate | volatility`; input contract приведён к
  плановым значениям `univariate | supervised | multivariate | panel`.
- Descriptor теперь публикует отдельные lifecycle capabilities для
  fit/predict/tuning/diagnostics и resource capabilities для CPU/GPU, класса
  памяти и parallel folds. Runtime-ready набор по-прежнему выводится только из
  registry; состав сертифицированных девяти моделей не изменён.
- Dependency readiness выполняется probe-операцией через import metadata/spec
  без импорта тяжёлой библиотеки. Недоступная зависимость исключает модель из
  runtime actions, а прямое исполнение завершается fail closed.
- В lineage сохраняются версия модели, версия адаптера, Python и точные версии
  требуемых библиотек, dependency status, runtime verdict и полная подпись
  execution descriptor. Model Card получает версии из backtest lineage, а не
  из отдельного текущего окружения.
- `cohort_id` теперь подписывает objective, fingerprints всех входных рядов/X,
  feature contract и metric policy вместе с exact EDA folds. Comparison явно
  отклоняет модели с разными objective или cohort contracts, поэтому ranking
  между разными постановками задачи невозможен.
- Схема session artifacts повышена с 5 до 6. Миграция сохраняет только
  проверяемые v2 artifacts; результаты без нового objective/cohort/library
  lineage безопасно инвалидируются вместе с зависимыми diagnostics/tuning.

### Ошибка параллельного изменения состояния

- Воспроизведена сообщённая production-ошибка `Состояние анализа изменилось в
  параллельном запросе`. После загрузки context компонент сразу публиковал его
  в React state и независимо запускал GET modeling state. Effect по новому
  fingerprint успевал отправить POST candidates до завершения GET.
- GET state при первом открытии после Task 122 мигрировал Redis artifact и сам
  выполнял optimistic save. GET и POST читали одну revision, после чего один
  из них закономерно получал `SessionConflictError`.
- Bootstrap сериализован: готовый context публикуется только после завершения
  state hydration/migration. Одновременные state-запросы coalesce через один
  in-flight Promise; POST candidates больше не стартует параллельно с
  миграционной записью.

### TDD и проверки

- RED contract gate до production-кода: 4/4 FAIL — отсутствовали objective/lifecycle/
  resources, lazy dependency fail-closed и расширенный cohort fingerprint;
  comparison допускал разные objective.
- RED UI race: зафиксирован порядок `state:start → candidates:start` без
  завершения state migration. GREEN подтверждает строгий порядок
  `state:start → state:finish → candidates:start`.
- Новый schema 5 → 6 integration test подтверждает инвалидизацию неполного
  Task 122 lineage и успешный повторный candidates request.
- Полный backend regression: 1319/1319 PASS, 3/3 snapshots PASS.
- Полный frontend regression: 84/84 suites, 725/725 tests PASS; компонент
  Modeling отдельно: 47/47 PASS.
- TypeScript 5.9 application typecheck: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, по 13/13 статических страниц,
  включая `/modeling`; First Load JS 464 kB. Для ограничения sandbox Node 24
  `uv_resident_set_memory` использован временный внешний memory shim; после
  сборок он удалён и в изменения не входит.
- `pip check`: PASS. `git diff --check`: PASS.

### Изменённые/новые файлы Task 122.1

- `apps/api/backtesting.py`
- `apps/api/model_execution.py`
- `apps/api/modeling_comparison.py`
- `apps/api/modeling_tuning.py`
- `apps/api/routers/modeling_session.py`
- `apps/api/schemas.py`
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/lib/modeling.ts`
- `tests/api/test_modeling_workflow.py`
- `tests/unit/test_model_execution_contract.py`
- `tests/unit/test_model_execution_contract_v2_compliance.py`
- `tests/unit/test_modeling_comparison.py`

---

## Task 123 — Универсальное исполнение долгих model jobs

Дата: 2026-09-05. База: `main @ 36439d569ba1d118fbebb9b29b3f482ea8fefac7`.
Commit/push и production deploy не выполнялись.

### Проверка поведения авто-бэктеста

- Поведение после Task 122.1 соответствует контракту Modeling: POST
  `/modeling/baselines` автоматически исполняет только четыре обязательные
  baseline-модели — `naive`, `seasonal_naive`, `drift`, `mean`.
- Остальные runtime-ready модели входят в подписанный execution scope как
  `pending_backtest_model_ids` и должны быть запущены аналитиком либо явно
  исключены с обоснованием. Это не потеря capability.
- Наблюдавшиеся пять готовых результатов означают четыре автоматически
  рассчитанных baseline плюс один переиспользованный совместимый backtest из
  session artifacts. Regression-test фиксирует точный baseline-набор и
  вычисляет pending относительно актуального runnable shortlist.

### Model Job Contract v1

- Добавлен независимый от FastAPI модуль `model-job-v1`: детерминированная
  SHA-256 identity связывает operation, model, cohort, work plan, seed и
  resource policy. Текущий tuning стал первым production-адаптером общего
  job-протокола; новые модели в scope Task 123 не добавлялись.
- Реализованы endpoint’ы `POST /jobs/start`, `GET /jobs/{job_id}`,
  `POST /jobs/{job_id}/step`, `POST /jobs/{job_id}/cancel`. Один step
  исполняет один ограниченный trial; status позволяет продолжить job после
  перезапуска API/клиента по сохранённому Redis state.
- Повторный start того же плана и повтор уже подтверждённого step возвращают
  текущее состояние как idempotent replay. Конкурентные одинаковые Redis
  steps сходятся через optimistic CAS: победившая revision возвращается обоим
  клиентам без повторного продвижения progress.
- Job хранит selected work plan, компактные trial metrics, ошибки, progress и
  только лучший промежуточный OOF artifact. После завершения временные данные
  очищаются, а job сохраняет ссылку на канонический tuning artifact; fitted
  model/estimator в Redis не сериализуется.
- Legacy `/tuning/start` и `/tuning/step` сохранены для обратной совместимости,
  но основной UI переведён на универсальные `/jobs/*` endpoint’ы.

### Ресурсы, зависимости и воспроизводимость

- Registry descriptor расширен `dependency_group`; текущие девять моделей
  относятся к `classical`. Манифест заранее разделяет `classical`, `ml`,
  `volatility`, `neural` без преждевременной установки библиотек будущих
  Tasks 124–143.
- Resource policy выводится из registry capabilities и фиксирует memory class/
  MiB, CPU threads/time, GPU mode, step timeout и общий persisted deadline.
  Memory, CPU time и оба timeout проверяются fail closed; required GPU
  допускается только при явном deploy-сигнале `CISSTAT_GPU_AVAILABLE`, без
  eager-импорта PyTorch/CUDA.
- `random_state` подписан job identity и передаётся в каждый fold-level
  `ModelExecutionRequest`; nondeterministic adapter не допускается к job start.
- Прогресс имеет общий формат trials/folds/epochs. Для текущего tuning один
  work unit завершает один trial и его exact EDA folds; epochs остаются 0/0 до
  подключения neural job adapters.

### UI

- Tuning использует универсальный job API, восстанавливает уже выполняющийся
  идентичный план и показывает progress одновременно по trials, folds и
  epochs.
- Во время job доступна кооперативная отмена. После cancel следующий work unit
  не стартует; ошибка/terminal state выводится доступным `role=alert`.
- Promoted backtest и весь последующий diagnostics/comparison/selection/
  Model Card workflow сохраняют прежний контракт.

### TDD и проверки

- RED backend: новый suite завершался collection error
  `ModuleNotFoundError: apps.api.model_jobs`; RED frontend показывал обращения
  к legacy `/tuning/start|step` вместо `/jobs/*`.
- Job/API gates проверяют start/status/step/cancel, start/step idempotency,
  compact Redis state, persisted deadline, memory budget, deterministic seed,
  dependency groups и реальную гонку двух Redis steps через barrier/CAS.
- Modeling regression subset: 169/169 PASS; Modeling UI: 58/58 PASS.
- Полный backend regression: 1328/1328 PASS, 3/3 snapshots PASS.
- Полный frontend regression: 84/84 suites, 726/726 tests PASS.
- TypeScript 5.9 application typecheck: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, по 13/13 статических страниц,
  включая `/modeling`; First Load JS 464 kB. Для ограничения sandbox Node 24
  `uv_resident_set_memory` использован временный внешний memory shim; после
  сборок он удалён и в изменения не входит.
- `pip check`: PASS. `git diff --check`: PASS.

### Изменённые/новые файлы Task 123

- `apps/api/model_jobs.py`
- `apps/api/model_execution.py`
- `apps/api/backtesting.py`
- `apps/api/modeling_tuning.py`
- `apps/api/routers/modeling_session.py`
- `packages/ui/components/ModelingWorkflowOverview.tsx`
- `packages/ui/components/ModelingWorkflowOverview.test.tsx`
- `packages/ui/lib/modeling.ts`
- `tests/api/test_modeling_workflow.py`
- `tests/unit/test_model_execution_contract.py`
- `tests/unit/test_model_jobs.py`

Номера задач с Task 121 по Task 143 зарезервированы modeling_task_list.md.

---

## Task 124 — Prophet production vertical slice

### Контекст и сертификация Task 123

Перед началом Task 124 самостоятельно пересертифицирован Task 123 (независимо
от прежней записи): backend 1328/1328 PASS (3/3 snapshots), frontend 84 suites/
726 tests PASS, `typecheck:all` PASS для embedded и standalone, оба production
build 13/13 страниц (First Load JS 464 kB, через тот же временный шим
`next/font/google`, немедленно отменённый — `git diff` после отката пуст),
`pip check` PASS, рабочее дерево чистое. Task 123 подтверждена как готовая к
сертификации; после этого начата Task 124.

### Что сделано

Prophet добавлен как десятая production-модель через `MODEL_EXECUTION_REGISTRY`
(Task 122 контракт) — не отдельная параллельная реализация, а тот же
`ModelExecutionRequest`/`ModelExecutionResult`, что и у остальных девяти
моделей, плюс тот же `run_backtest_plan`/exact EDA folds pipeline (Task 76+).
Собственного второго CV-контура (`prophet.diagnostics.cross_validation`) нет:
ровно один `fit`+`predict` на fold, который передаёт платформа.

- **Строгий future-known contract**: адаптер использует `train_timestamps`/
  `future_timestamps` из `ModelExecutionRequest` как есть — не переизобретает
  даты через `infer_freq`/`make_future_dataframe`. Если платформа не передала
  реальные даты на fold (например будущий fold-local preprocessing меняет
  длину target), executor фейлится явно и внятно
  (`ModelExecutionContractError`), а не молча подставляет synthetic index —
  это единственная модель в registry, для которой этот контракт критичен.
- **Fold-local holidays**: `Prophet.add_country_holidays` из bounded набора
  стран (`SUPPORTED_COUNTRY_HOLIDAYS`) — календарь известен заранее на любой
  горизонт, поэтому не создаёт утечки; объект Prophet пересоздаётся на каждый
  fold (fit_policy="per_train_fold"), holidays никогда не переиспользуются
  между train fold'ами.
- **Осознанное сужение scope**: произвольные пользовательские регрессоры
  через `train_features`/`future_features` НЕ подключены в Task 124. Изучение
  стека (`run_backtest_plan` → `ModelExecutionRequest`) показало, что реальный
  pipeline наполнения этих полей данными сессии ещё не существует нигде выше
  `model_execution.py`/`backtesting.py` — сама эта пара полей была
  спроектирована в Task 122 как будущий контракт для Task 126 (Leakage-safe
  supervised FeaturePlan). Подключать Prophet к несуществующему upstream было
  бы фиктивной функциональностью; решение задокументировано здесь явно, а не
  скрыто в коде (по прецеденту Task 60 с явным протоколированием scope-решений).
- **Bounded tuning**: `changepoint_prior_scale` × `seasonality_prior_scale` ×
  `seasonality_mode` = 5×3×2 = 30 trials (≤ MAX_TRIALS=64), добавлено как
  `param_space` в `rules/modeling.yaml` — тот же grid-tuning движок
  (`modeling_tuning.py`), что и у ETS/ARIMA, без отдельного bayesian-optimization
  контура. `country_holidays` в grid не входит (fold-local calendar-опция, не
  часть bounded-тюнинга).
- **Prediction intervals**: Prophet — первая модель в registry с
  `supports_prediction_intervals=True`; адаптер честно возвращает
  `yhat_lower`/`yhat_upper` (Prophet default `interval_width=0.80`), а не
  фиктивные значения.
- **multiplicative seasonality guard**: как и у ETS, `seasonality_mode=
  "multiplicative"` требует строго положительный ряд — явная проверка с
  понятной ошибкой вместо непрозрачного сбоя внутри Prophet/Stan.
- **Legacy synthetic-demo эндпоинт** (`/v1/models/backtest`, `_generate_series`,
  без реальных дат в профиле): `run_prophet_backtest` синтезирует свою
  внутреннюю дату-ось (частота выводится из `seasonal_period`), т.к. это чисто
  демонстрационный путь, не связанный с реальным EDA BacktestPlan; жёсткий
  инвариант-guard `frozenset(_BACKTEST_IMPLEMENTATIONS) ==
  PRODUCTION_BACKTEST_MODEL_IDS` в `routers/models.py` потребовал добавить эту
  реализацию — без неё приложение падало бы при импорте.

### Обнаруженные и обновлённые release-gate инварианты

Регистрация десятой модели закономерно "сломала" несколько сертификационных
тестов Phase 121/122/123, жёстко фиксировавших число 9 — это ожидаемая,
предусмотренная часть работы, не побочный ущерб:

- `tests/unit/test_modeling_mvp_certification.py` — CERTIFIED_MODEL_IDS
  расширен, тест переименован в `..._exactly_ten_real_models...`,
  `PRODUCTION_TUNING_MODEL_IDS` теперь включает `prophet`.
- `tests/unit/test_backtesting_engine.py` — `test_all_nine_production_models_
  ...` переименован в `..._all_ten_...`; лейблы cohort заменены с
  `["0","1",...]` на реальные `pd.date_range(...).isoformat()` — единственный
  способ честно прогнать Prophet в общем "same real OOF cohort" тесте.
- `tests/unit/test_model_readiness_candidates.py` — `prophet` перемещён из
  списка `catalog_only` в список `ready`; `runnable_candidates` 9→10,
  `catalog_only_candidates` 15→14.
- `tests/unit/test_model_execution_contract.py` — `CERTIFIED_IDS` расширен.
- `tests/unit/test_model_capability_matrix.py` — `matrix["prophet"]["backtest"]
  ["status"]` теперь `"available"` вместо `"not_implemented"`.
- `tests/api/test_modeling_workflow.py` —
  `test_workflow_rejects_catalog_only_model_instead_of_fabricating_metrics`
  использовал `model_id="prophet"` как пример catalog-only модели; заменён на
  `"tbats"` (по прежнему catalog-only после Task 124).
- `tests/api/test_models_backtest_real.py` — `test_registry_has_9_
  implementations` → `..._10_implementations`, добавлен `"prophet"` в
  ожидаемое множество.

### Новые тесты

- `tests/unit/test_prophet_adapter.py` (10 тестов, НОВЫЙ файл): форма
  forecast/интервалов, guard на `multiplicative`+неположительный ряд, guard на
  неподдерживаемый `country_holidays`, ошибка при несовпадении длины
  timestamps, registry descriptor (`actions`, `dependency_group`,
  `runtime_available`), `execute()` требует train/future timestamps, интервалы
  честно содержат точечный прогноз, полный прогон через реальный
  `build_backtest_plan`/`run_backtest_plan` с настоящими датами, размер
  bounded tuning grid ≤ MAX_TRIALS.
- `tests/api/test_modeling_workflow.py::
  test_prophet_full_session_backtest_and_diagnostics_use_real_calendar_dates`
  (НОВЫЙ) — единственное место в проекте, где upstream (`prepare_modeling_
  target`) реально поставляет календарные даты сквозь весь session workflow;
  доказывает работу Prophet end-to-end, а не только на уровне адаптера.
- `tests/api/test_models_backtest_real.py::
  test_prophet_impl_callable_with_minimal_series` (НОВЫЙ) + `"prophet"`
  добавлен в параметризацию `test_short_series_does_not_500` (edge case: 8
  точек, `safe_backtest` fallback отработал корректно).

### TDD-цикл

- RED: после регистрации Prophet в `MODEL_EXECUTION_REGISTRY` (до правки
  тестов) целевой прогон дал ровно 5 ожидаемых провалов — все из-за жёстко
  зашитого числа 9 в разных файлах; ни одного неожиданного провала. Это
  подтвердило, что сама интеграция (registry + legacy dispatch + manifest)
  сделана без побочных разрушений.
- GREEN: после обновления/добавления тестов — 0 неожиданных провалов на
  целевом срезе, затем на `test_modeling_workflow.py` целиком (38/38, самый
  рискованный файл с сотнями неявных сквозных проверок), затем на полном
  backend regression.

### Проверки

- Полный backend regression: **1340/1340 PASS** (было 1328 — +9 новых
  `test_prophet_adapter.py` −1 переиспользованный слот +2 новых в
  `test_modeling_workflow.py`/`test_models_backtest_real.py`), 3/3 snapshots
  PASS.
- Полный frontend regression: 84/84 suites, 726/726 tests PASS (без
  изменений — Task 124 backend-only, фронтенд полностью catalog-driven, ни
  одного захардкоженного упоминания числа моделей не найдено).
- `typecheck:all`: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, 13/13 статических страниц,
  First Load JS 464 kB (не изменился — фронтенд не тронут). Временный шим
  `next/font/google` применён, собран, немедленно отменён; `git diff` после
  отката — пуст.
- `pip check`: PASS. Рабочее дерево чистое (`git status --short` показывает
  только осознанные изменения из списка ниже).
- Установлен `prophet==1.4.0`, добавлен в `apps/api/requirements.txt` и в
  манифест `classical` пакетов (`apps/api/model_jobs.py`).

### Изменённые/новые файлы Task 124

Новые:
- `apps/api/model_impls/prophet.py`
- `tests/unit/test_prophet_adapter.py`

Изменённые:
- `apps/api/model_execution.py`
- `apps/api/model_impls/__init__.py`
- `apps/api/model_jobs.py`
- `apps/api/requirements.txt`
- `apps/api/routers/models.py`
- `rules/modeling.yaml`
- `tests/api/test_modeling_workflow.py`
- `tests/api/test_models_backtest_real.py`
- `tests/unit/test_backtesting_engine.py`
- `tests/unit/test_model_capability_matrix.py`
- `tests/unit/test_model_execution_contract.py`
- `tests/unit/test_model_readiness_candidates.py`
- `tests/unit/test_modeling_mvp_certification.py`

### Что осталось за рамками Task 124 (осознанно, для будущих задач)

- Произвольные пользовательские регрессоры Prophet (`train_features`/
  `future_features`) — ждут Task 126 (Leakage-safe supervised FeaturePlan).
- Model Card-специфичный UI-рендеринг для Prophet (ссылка на
  `Prophet diagnostics` уже присутствует в `TsAnalysisEDA.tsx`, к Modeling
  напрямую не относится) — фронтенд не тронут, т.к. он полностью
  catalog/candidates-driven и уже корректно показывает Prophet как `ready`
  без единой правки кода.
- TBATS (Task 125) — следующая модель в прогрессии "11/24".

---

## Task 97.1 — Раскрытие/схлопывание графиков «Обзора»: Этап 1 (фундамент)

### Исходная точка

Работа выполнена на точном коммите `63b1d7d` (`spec_max_graf_fix` — утверждённая
v2-редакция спецификации Task 97, вопросы §10 закрыты по рекомендациям
ревьюера); commit/push не выполнялись. Перед началом пересинхронизирован с
origin/main, повторно верифицированы факты ревью: 30 `*Overview.tsx`, 54 файла
Обзор-семейства (Overview+Pipeline+Visualizations), контракт `h-[468px]`
в 51 файле, `relative` только в 2/54 файлах, `cn()`/`user-event`/`--badge-*`
в проекте отсутствуют, lucide-react `^0.427.0` и recharts `^2.13.3` в deps.
Task 124 (Prophet) не затрагивал `packages/ui` — скоуп Этапа 1 не пересекается.

### Что сделано (spec_max_graf_fix.md, Этап 1 — «фундамент»)

Реализован переиспользуемый примитив раскрытия графиков в `packages/ui`,
без подключения к Обзорам (это Этапы 2–4) и без backend-изменений:

- **`hooks/useExpandableChart.ts`** — state/actions-контексты фичи + хуки
  доступа `useExpandableChartState` / `useExpandableChartActions` с guard'ом
  «провайдер отсутствует» (понятная ошибка вместо молчаливой деградации).
  Разделение контекстов — правка H: actions стабильны по ссылке (useMemo),
  потребители действий не перерендериваются при смене `expandedChartId`.
- **`ExpandableChartsProvider.tsx`** — провайдер на уровень ОДНОГО Обзора,
  инвариант single-expand (expand нового id неявно схлопывает предыдущий;
  z-index-стек не нужен — §5.2 спеки).
- **`ExpandableChartPanel.tsx`** — обёртка одного визуального блока:
  свёрнуто `flex min-h-0 flex-1 flex-col`, раскрыто `absolute inset-0 z-20
  bg-white`; Esc схлопывает (window keydown, снимается при unmount);
  `onExpandChange` — сигнал для будущего `useChartDetailData` (Этап 3, §6.3).
  В коде зафиксированы контракты правок A (`relative` на корне Обзора —
  проверяет coverage-тест) и C (`overflow-y-auto` → `overflow-hidden`
  на время раскрытия, интеграционный паттерн §4.4).
- **`ChartExpandToggle.tsx`** — иконка-бейдж в фактическом стиле бейджей
  проекта (`rounded-full bg-neutral-100`, hover `bg-neutral-200`,
  focus-visible ринг `ring-neutral-400` — правка B, без несуществующих
  `--badge-*`), `aria-label` + `aria-expanded` (правка I), иконки
  lucide-react `Maximize2`/`Minimize2`. Вместо несуществующей `cn()` —
  шаблонные строки (правка E).
- **`packages/ui/index.ts`** — barrel-экспорты нового примитива
  (компоненты, пропсы, хуки, типы, константы label'ов).

### Контрактный тест покрытия — 3 явных списка (правка F)

`ExpandableChartCoverage.test.ts` построен по прецеденту
AnalysisWorkspaceHeight/AdaptiveWorkspaceVisualizations (статическая проверка
исходников, явные списки, `@ts-nocheck`). Инвентарь Обзор-семейства
верифицирован пофайлово, списки замкнуты инвентарным guard'ом (54 файла,
без дублей и пропусков — при появлении нового файла семейства тест падает,
пока файл не отнесён к списку):

- **EXPANDABLE_WINDOW_OVERVIEWS (20)** — Обзоры с окном `h-[468px]`,
  рендерящие графики данных (10 EDA + 10 Preprocessing Overview, включая
  Missing/Outliers/Regularity, чьи графики живут в Visualizations-детях).
  Требования на файл: `relative` в className окна 468px (правка A) +
  условная пара `overflow-hidden`/`overflow-y-auto` (правка C) +
  `ExpandableChartsProvider` + обёртка блоков в `ExpandableChartPanel`.
- **CHART_BLOCK_SOURCES (3)** — Missing/Outliers/Regularity Visualizations:
  модули, ОПРЕДЕЛЯЮЩИЕ chart-блоки; обёртка ставится на уровне использования
  (в Обзоре списка 1). Guard: каждый импортируется хотя бы одним Обзором
  списка 1.
- **OUT_OF_SCOPE_NO_CHARTS (31)** — файлы семейства без визуализаций данных
  (18 Validation — таблицы/статусы, 10 Preprocessing Pipeline-обёрток,
  2 статичные схемы Modeling, UploadAutoPreviewPipeline). Negative-guard:
  случайное появление Provider/Panel здесь — ошибка скоупа; расширение
  скоупа = перенос файла в список 1 (одна строка). Решение «таблицы
  Validation и статичные схемы вне скоупа раскрытия графиков» следует из
  §2 спеки («раскрыть вложенный график») и зафиксировано явно, а не скрыто.

### TDD-цикл

- RED (тесты написаны до кода): 3 компонентных suite — «Cannot find module»
  (ожидаемо, модулей ещё нет); coverage-тест — ровно 20 провалов
  (по одному на файл списка 1, каждый с перечнем недостающих требований:
  relative / overflow-hidden / overflow-y-auto / Provider / Panel) + 34 GREEN
  (guards). Это и есть чек-лист Этапов 2–4, RED — сознательный,
  spec_max_graf_fix.md §7.2/§8.
- В ходе GREEN выявлен и исправлен дефект самого теста (не кода): в
  provider-тесте был пропущен импорт `screen` — TypeScript честно разрешил
  идентификатор к глобальному jsdom `screen` (`lib.dom`); ошибка всплыла на
  этапе type-check, до запуска. Исправлен импорт.
- GREEN: компонентные suite — 3/3, тесты 17/17 (Provider: single-expand,
  implicit collapse, collapse, split-контексты через счётчики рендеров —
  actions-проба не перерендерилась за 3 смены состояния, guard вне
  провайдера; Toggle: aria/иконки/клик/фокус; Panel: классы состояний,
  Esc-expanded/Esc-collapsed, последовательность onExpandChange
  [false, true, false], aria-expanded встроенного toggle).

### Проверки

- Полный frontend regression: **88 suites / 797 tests** (было 84/726: +4
  suite, +71 тест), из них **777 PASS, ровно 20 FAIL** — все 20 из
  сознательно RED чек-листа ExpandableChartCoverage (Этапы 2–4). Все 726
  прежних тестов — PASS, регрессий нет. Snapshots не затронуты.
- `typecheck:all`: embedded PASS, standalone PASS (barrel-экспорты
  компилируются в обоих приложениях).
- Production build: embedded PASS, standalone PASS, 13/13 статических
  страниц, First Load JS 464 kB (не изменился — примитив ещё не подключён
  ни в один маршрут; рост бандла ожидается на Этапе 2 и будет зафиксирован).
- `npx tsc --noEmit -p packages/ui/tsconfig.json`: exit 0; вывод содержит
  только преждесуществующие deprecation-предупреждения tsconfig
  (target=ES5, baseUrl) при установленной версии tsc — к задаче не относятся.
- Рабочее дерево: только файлы текущей задачи (9 новых + `packages/ui/index.ts`
  + `worklog2.md`), `git status` чист от побочных изменений.

### Изменённые/новые файлы Task 97.1

Новые:
- `packages/ui/hooks/useExpandableChart.ts`
- `packages/ui/components/ExpandableChartsProvider.tsx`
- `packages/ui/components/ExpandableChartsProvider.test.tsx`
- `packages/ui/components/ExpandableChartPanel.tsx`
- `packages/ui/components/ExpandableChartPanel.test.tsx`
- `packages/ui/components/ChartExpandToggle.tsx`
- `packages/ui/components/ChartExpandToggle.test.tsx`
- `packages/ui/components/ExpandableChartCoverage.test.ts`

Изменённые:
- `packages/ui/index.ts`
- `worklog2.md` (эта запись)

### Что осталось за рамками Task 97.1 (по плану спеки)

- Этап 2 (пилот): подключение ExpandableChartPanel к пилотным Обзорам
  (CWT-хитмап спектрального, структурные сдвиги, декомпозиция; матрица
  моделей — по решению) с добавлением `relative` + условного overflow в
  каждой PR-итерации; UX-валидация раскрытия на реальных данных.
- Этап 3: `detail_level=compact|expanded` в backend-профилях,
  `useChartDetailData`, тесты §7.4 (структура/объём вместо byte-for-byte).
- Этап 4: тиражирование по чек-листу до полного GREEN coverage-теста.
- Открытое решение Этапа 2: точка монтирования провайдера в triada
  Missing/Outliers/Regularity (Overview держит список 1; если пилот покажет,
  что окно надо отдавать на уровне Pipeline — файл переносится из списка 3
  в список 1 одной строкой, guard-механика уже готова).

  ## Task 97.2 — Раскрытие/схлопывание графиков «Обзора»: Этап 2 (пилот, 4 Обзора)

### Исходная точка

Синхронизация до `6791c02` — это закоммиченный в main Этап 1 (Task 97.1);
дерево чистое, зависимости не менялись. Решения тимлида: базлайн прогона
остаётся красным (чек-лист = backlog), переключение на `it.failing` не
применяется; пилотный список §10 подтверждён. CWT-пункт пилота маппится на
`PreprocessingSpectralOverview` — отдельного CWT-Обзора в кодовой базе нет,
CWT-скалограмма это вкладка wavelet внутри Spectral.

### Что сделано (spec_max_graf_fix.md §4.4/§8, Этап 2)

Пилотная четвёрка адаптирована по паттерну §4.4 (обёртка: Provider снаружи,
Inner внутри; Inner читает `expandedChartId` для переключения overflow):

- **EdaStructuralBreaksOverview** — панели вкладок Режимы / CUSUM /
  Чувствительность (`structural-*`); таблицы Сегменты/Кандидаты — без панелей.
- **EdaModelMatrixOverview** — тепловая карта применимости и график по
  семействам (`model-matrix-*`); Shortlist/Details — без панелей.
- **PreprocessingDecompositionOverview** — Компоненты / Сезонный профиль /
  ACF остатка (`decomposition-*`); Диагностика (метрики) — без панели.
- **PreprocessingSpectralOverview** — FFT+периодограмма, Welch PSD,
  CWT-скалограмма, фазовый профиль (`spectral-*`); таблица кандидатов — без
  панели; панель фазы монтируется только при наличии данных (бейдж раскрытия
  не показывается на пустом status-сообщении).
- В каждом Обзоре: `relative` на корне (правка A) + условная пара
  `overflow-hidden`/`overflow-y-auto` (правка C) в одном className корня;
  сами графики не тронуты — ResponsiveContainer height="100%" подхватывает
  размер (паттерн Task 89).

### Находки пилота — 2 дефекта Этапа 1, исправлены

1. **ExpandableChartPanel: отсутствие `relative` у свёрнутой ветки.** Бейдж
   `ChartExpandToggle` — `absolute right-2 top-2`; без позиционированной
   панели бейджи ВСЕХ свёрнутых блоков Обзора якорились бы к корню и
   складывались в его правом верхнем углу. Добавлен `relative` в свёрнутую
   ветку панели (в раскрытой — снят, чтобы не конфликтовать с
   `absolute inset-0`); два новых теста панели RED→GREEN.
2. **Статические тесты не видели шаблонные className.** Regex прецедента
   `AnalysisWorkspaceHeight` — `className=(?:"..."|`...`)` — не учитывает
   `{` в JSX-форме `className={`...`}`; все условные классы (включая пару
   overflow правки C) были невидимы статике. Regex исправлен (`\{?` после
   `=`) в `ExpandableChartCoverage.test.ts` и `AnalysisWorkspaceHeight.test.ts`.
   После фиксации контракт высоты Task 88 восстановился БЕЗ изменения
   ожиданий (165 состояний / 44 прокручиваемых / 121 непрокручиваемых) —
   условная пара в шаблоне видна и считается как прокручиваемое состояние.

### Интеграционный тест §7.3

`EdaStructuralBreaksOverview.test.tsx`: раскрытие → панель
`absolute inset-0 z-20` + корень переключается на `overflow-hidden`;
Esc → возврат `overflow-y-auto`; повторный клик по бейджу — toggle.
Acceptance-сигнал адаптации каждого Обзора — флип его чек-лист-теста
(RED→GREEN), отдельные RED-итерации не требовались.

### Верификация

- Полный прогон: 88 suites / 801 tests = 785 PASS + ровно 16 FAIL
  (чек-лист: 20 → 16 после пилота; остальные suite'ы зелёные).
- `typecheck:all` exit 0; production builds embedded + standalone — OK
  (13/13 страниц в каждом).
- Изменённые файлы: 4 Обзора, `ExpandableChartPanel.tsx` (+тест), 2
  статических теста (фикс regex), `EdaStructuralBreaksOverview.test.tsx`
  (интеграция §7.3), worklog2.md.

### Что осталось (Этапы 3–4)

- Этап 3: `detail_level` в backend для пилотных профилей + `useChartDetailData`
  (§6, §7.4); сигнал уже подготовлен — `onExpandChange` панели.
- Этап 4: тиражирование на оставшиеся 16 Обзоров списка 1 до полного GREEN.
- UX-выводы по `title` (сейчас — tooltip бейджа) и поведению шапки в раскрытом
  состоянии — по итогам пилота на реальных данных (§10 п.4).

  ---

## Task 97.3 — Overview Graph Expand: Stage 3 (detail_level backend + useChartDetailData)

**Синхронизация:** `6791c02 → b2c6bb5` (заккоммиченный тимлидом Этап 2;
локальное незакоммиченное дерево Этапа 2 совпало с origin/main кроме 1 строки
worklog2.md — сброшено через `reset --hard`). Дерево чистое, npm ci не требовался.
Спецификация: spec_max_graf_fix.md §6 (модель detail_level), §6.3 (клиентский
флоу дозагрузки), §7.4 (backend-тесты, правка J), §8 п.4 (Этап 3).

### Скоуп Этапа 3 и маппинг на профили-пилоты

- **Спектральный (CWT-скалограмма):** потолок оси времени CWT — единственный
  display-потолок профиля; `MAX_WAVELET_TIME_POINTS 120 → MAX_WAVELET_TIME_POINTS_EXPANDED 240`
  (×2, «×1.5–2 по каждой оси» §6.2). Ось периодов — управляется существующим
  query-параметром `wavelet_scales` (8..64), изменения не требует. Сама CWT
  всегда считалась по всему ряду — expanded не меняет стоимость расчёта.
- **Структурные сдвиги:** LTTB-сэмплы `series`/`cusum_path`:
  `TARGET_SAMPLED_POINTS 1500 → EXPANDED_TARGET_SAMPLED_POINTS 3000`.
  PELT-бюджет `MAX_PELT_GRID_POINTS=250` (Task 76) НЕ тронут — это бюджет
  расчёта, а не отображения.
- **Декомпозиция:** STL всегда по полному ряду; точки отрисовки:
  expanded = полный ряд до `EXPANDED_FULL_POINTS_THRESHOLD 6000` («без
  даунсэмплинга, если в разумных пределах» §6.2), выше — LTTB до 3000.
- **Матрица моделей:** dense-рядов в ответе нет (категориальная матрица 24
  моделей, счётчики семейств) — detail-режим не подключён, раскрытие остаётся
  чисто визуальным (§6.3.6); задокументировано в тесте и коде.

### Backend (GREEN: tests/api/test_dataset_profile_detail_level.py 10/10)

- `apps/api/chart_data.py`: константы `EXPANDED_FULL_POINTS_THRESHOLD=6000`,
  `EXPANDED_TARGET_SAMPLED_POINTS=3000` — явные тестируемые вторичные потолки
  (по аналогии с budget PELT Task 76, мера риска §9).
- `app/preprocessing/spectral.py`: `MAX_WAVELET_TIME_POINTS_EXPANDED=240`;
  `analyze_spectral_extensions(..., detail_level="compact")` → `_wavelet_payload(max_time_points)`.
- `apps/api/preprocessing_spectral.py` / `eda_structural_breaks.py` /
  `preprocessing_decomposition.py`: pass-through `detail_level` со срезом
  только сэмплинга отображения.
- `apps/api/routers/session.py`: Optional `detail_level` (Query, default
  `compact`, pattern `^(compact|expanded)$`) на 3 GET-эндпоинтах пилота —
  обратная совместимость: клиенты, не знающие параметр, получают текущее
  поведение (§6.4).
- Тесты §7.4 (правка J): (1) compact-regression — «без параметра» vs
  `detail_level=compact` идентичны по структуре/объёму (сигнатура ключей,
  типов, длин списков, а не байтов); (2) expanded ≥ compact и ≤ явного
  потолка; (3) методология неизменна — анализ-поля (кандидаты/сегменты
  PELT, strength-метрики и seasonal_pattern STL, Welch/global CWT и ось
  периодов) попарно идентичны compact/expanded; (4) неизвестный
  `detail_level` → 422 на всех трёх эндпоинтах. Регресс затронутых
  профилей: 28 passed (structural-breaks, decomposition, spectral,
  timeseries_decomposition).

### Frontend: useChartDetailData (RED→GREEN, 10/10)

- `packages/ui/hooks/useChartDetailData.ts`: условная догрузка §6.3.
  Ключ кэша `(profileKey, fingerprint, params)`; sessionId в ключе не нужен —
  фронтенд не держит его в состоянии (cookie), а смена сессии всегда меняет
  датасет/fingerprint. Попадание в кэш — синхронно, без сети (§6.3.2);
  промах — фоновый запрос `detail_level=expanded`, `data=null` пока летит —
  Обзор продолжает показывать compact (§6.3.3); индикатор — тонкий
  animate-pulse бар сверху панели (рисует Обзор, панель остаётся универсальной).
  AbortController при размонтировании/смене ключа; ошибка сети/HTTP →
  `error` без исключения (§6.3.6); FIFO-кэш на 40 записей
  (`MAX_CHART_DETAIL_CACHE_ENTRIES`).
- Дефект, найденный при интеграции: в jsdom-тестах без мока сети
  `globalThis.fetch` отсутствует — раскрытие панели роняло старые тесты
  §7.3 (`TypeError: fetch.bind`). Хук теперь graceful-деградирует и при
  отсутствии транспорта; старым тестам §7.2/§7.3 добавлен hermetic fetch-мок
  (заодно убрана зависимость от порядка сьют в worker'е).

### Wiring пилота (4 панели из 9 пилотных)

- `EdaStructuralBreaksOverview`: hook для «Режимы» и «CUSUM» (новый опциональный
  проп `datasetKey` — идентичность датасета для инвалидации, передаёт
  `TsAnalysisEDA`); «Чувствительность» — visual-only.
- `PreprocessingSpectralOverview`: hook для CWT-вкладки (новый опциональный
  проп `parameters` — копия compact-параметров контейнера, чтобы expanded
  считал тот же профиль, §6.4; передаёт `TsAnalysisPreprocessing`);
  FFT/Welch/фаза — visual-only.
- `PreprocessingDecompositionOverview`: hook для «Компоненты STL»
  (params=column — тот же уровень инвалидации, что у compact-феча контейнера);
  «Сезонный профиль»/«ACF» — размер периода/лагов, visual-only.
- Wiring-тесты (§6.3): свёрнутый Обзор не ходит в сеть; раскрытие плотной
  панели → запрос с параметрами compact + `detail_level=expanded` +
  `credentials: "include"`; раскрытие visual-only панелей не фетчит.

### Верификация

- Полный jest: 89 suites / 817 tests = 801 PASS + ровно 16 FAIL
  (чек-лист Этапа 4; RED-поле не расширилось, 20 → 16 → 16).
- `typecheck:all` exit 0; production builds embedded + standalone OK (13/13).
- Полный pytest: 1350 passed, 0 failed (в исходном прогоне 3 ERROR
  test_preprocessing snapshot — преждесуществующий дефект окружения:
  отсутствовал плагин syrupy в локальной venv; после установки 6/6,
  на чистом дереве воспроизводится тот же ERROR).

### Что осталось (Этапы 4–5)

- Этап 4: тиражирование на оставшиеся 16 Обзоров чек-листа до полного GREEN.
- Этап 5 (опционально): detail-режим для остальных профилей, где есть
  плотные выборки; калибровка чисел вторичных потолков на реальных
  датасетах (§9 follow-up) — контракт уже зафиксирован константами.

---

## Task 97.3 — Overview Graph Expand: Stage 3 (detail_level backend + useChartDetailData)

**Синхронизация:** `6791c02 → b2c6bb5` (заккоммиченный тимлидом Этап 2;
локальное незакоммиченное дерево Этапа 2 совпало с origin/main кроме 1 строки
worklog2.md — сброшено через `reset --hard`). Дерево чистое, npm ci не требовался.
Спецификация: spec_max_graf_fix.md §6 (модель detail_level), §6.3 (клиентский
флоу дозагрузки), §7.4 (backend-тесты, правка J), §8 п.4 (Этап 3).

### Скоуп Этапа 3 и маппинг на профили-пилоты

- **Спектральный (CWT-скалограмма):** потолок оси времени CWT — единственный
  display-потолок профиля; `MAX_WAVELET_TIME_POINTS 120 → MAX_WAVELET_TIME_POINTS_EXPANDED 240`
  (×2, «×1.5–2 по каждой оси» §6.2). Ось периодов — управляется существующим
  query-параметром `wavelet_scales` (8..64), изменения не требует. Сама CWT
  всегда считалась по всему ряду — expanded не меняет стоимость расчёта.
- **Структурные сдвиги:** LTTB-сэмплы `series`/`cusum_path`:
  `TARGET_SAMPLED_POINTS 1500 → EXPANDED_TARGET_SAMPLED_POINTS 3000`.
  PELT-бюджет `MAX_PELT_GRID_POINTS=250` (Task 76) НЕ тронут — это бюджет
  расчёта, а не отображения.
- **Декомпозиция:** STL всегда по полному ряду; точки отрисовки:
  expanded = полный ряд до `EXPANDED_FULL_POINTS_THRESHOLD 6000` («без
  даунсэмплинга, если в разумных пределах» §6.2), выше — LTTB до 3000.
- **Матрица моделей:** dense-рядов в ответе нет (категориальная матрица 24
  моделей, счётчики семейств) — detail-режим не подключён, раскрытие остаётся
  чисто визуальным (§6.3.6); задокументировано в тесте и коде.

### Backend (GREEN: tests/api/test_dataset_profile_detail_level.py 10/10)

- `apps/api/chart_data.py`: константы `EXPANDED_FULL_POINTS_THRESHOLD=6000`,
  `EXPANDED_TARGET_SAMPLED_POINTS=3000` — явные тестируемые вторичные потолки
  (по аналогии с budget PELT Task 76, мера риска §9).
- `app/preprocessing/spectral.py`: `MAX_WAVELET_TIME_POINTS_EXPANDED=240`;
  `analyze_spectral_extensions(..., detail_level="compact")` → `_wavelet_payload(max_time_points)`.
- `apps/api/preprocessing_spectral.py` / `eda_structural_breaks.py` /
  `preprocessing_decomposition.py`: pass-through `detail_level` со срезом
  только сэмплинга отображения.
- `apps/api/routers/session.py`: Optional `detail_level` (Query, default
  `compact`, pattern `^(compact|expanded)$`) на 3 GET-эндпоинтах пилота —
  обратная совместимость: клиенты, не знающие параметр, получают текущее
  поведение (§6.4).
- Тесты §7.4 (правка J): (1) compact-regression — «без параметра» vs
  `detail_level=compact` идентичны по структуре/объёму (сигнатура ключей,
  типов, длин списков, а не байтов); (2) expanded ≥ compact и ≤ явного
  потолка; (3) методология неизменна — анализ-поля (кандидаты/сегменты
  PELT, strength-метрики и seasonal_pattern STL, Welch/global CWT и ось
  периодов) попарно идентичны compact/expanded; (4) неизвестный
  `detail_level` → 422 на всех трёх эндпоинтах. Регресс затронутых
  профилей: 28 passed (structural-breaks, decomposition, spectral,
  timeseries_decomposition).

### Frontend: useChartDetailData (RED→GREEN, 10/10)

- `packages/ui/hooks/useChartDetailData.ts`: условная догрузка §6.3.
  Ключ кэша `(profileKey, fingerprint, params)`; sessionId в ключе не нужен —
  фронтенд не держит его в состоянии (cookie), а смена сессии всегда меняет
  датасет/fingerprint. Попадание в кэш — синхронно, без сети (§6.3.2);
  промах — фоновый запрос `detail_level=expanded`, `data=null` пока летит —
  Обзор продолжает показывать compact (§6.3.3); индикатор — тонкий
  animate-pulse бар сверху панели (рисует Обзор, панель остаётся универсальной).
  AbortController при размонтировании/смене ключа; ошибка сети/HTTP →
  `error` без исключения (§6.3.6); FIFO-кэш на 40 записей
  (`MAX_CHART_DETAIL_CACHE_ENTRIES`).
- Дефект, найденный при интеграции: в jsdom-тестах без мока сети
  `globalThis.fetch` отсутствует — раскрытие панели роняло старые тесты
  §7.3 (`TypeError: fetch.bind`). Хук теперь graceful-деградирует и при
  отсутствии транспорта; старым тестам §7.2/§7.3 добавлен hermetic fetch-мок
  (заодно убрана зависимость от порядка сьют в worker'е).

### Wiring пилота (4 панели из 9 пилотных)

- `EdaStructuralBreaksOverview`: hook для «Режимы» и «CUSUM» (новый опциональный
  проп `datasetKey` — идентичность датасета для инвалидации, передаёт
  `TsAnalysisEDA`); «Чувствительность» — visual-only.
- `PreprocessingSpectralOverview`: hook для CWT-вкладки (новый опциональный
  проп `parameters` — копия compact-параметров контейнера, чтобы expanded
  считал тот же профиль, §6.4; передаёт `TsAnalysisPreprocessing`);
  FFT/Welch/фаза — visual-only.
- `PreprocessingDecompositionOverview`: hook для «Компоненты STL»
  (params=column — тот же уровень инвалидации, что у compact-феча контейнера);
  «Сезонный профиль»/«ACF» — размер периода/лагов, visual-only.
- Wiring-тесты (§6.3): свёрнутый Обзор не ходит в сеть; раскрытие плотной
  панели → запрос с параметрами compact + `detail_level=expanded` +
  `credentials: "include"`; раскрытие visual-only панелей не фетчит.

### Верификация

- Полный jest: 89 suites / 817 tests = 801 PASS + ровно 16 FAIL
  (чек-лист Этапа 4; RED-поле не расширилось, 20 → 16 → 16).
- `typecheck:all` exit 0; production builds embedded + standalone OK (13/13).
- Полный pytest: 1350 passed, 0 failed (в исходном прогоне 3 ERROR
  test_preprocessing snapshot — преждесуществующий дефект окружения:
  отсутствовал плагин syrupy в локальной venv; после установки 6/6,
  на чистом дереве воспроизводится тот же ERROR).

### Что осталось (Этапы 4–5)

- Этап 4: тиражирование на оставшиеся 16 Обзоров чек-листа до полного GREEN.
- Этап 5 (опционально): detail-режим для остальных профилей, где есть
  плотные выборки; калибровка чисел вторичных потолков на реальных
  датасетах (§9 follow-up) — контракт уже зафиксирован константами.

---

## Task 97.4 — Overview Graph Expand: Stage 4 (Rollout, 16 Overviews → full GREEN)

- Синхронизация до cc2c296 (= закоммиченный тимлидом Этап 3, ровно 18 файлов
  Stage 3 ZIP); reset --hard, дерево чистое. Базлайн воспроизведён:
  полный jest 89 suites / 817 tests = 801 PASS + ровно 16 FAIL (чек-лист).
- TDD: RED уже стоял (ExpandableChartCoverage.test.ts, 16 файлов — скоуп
  Этапа 4 зафиксирован списком с Этапа 1, spec_max_graf_fix.md §7.2/§8.5).
- Адаптация 16 Обзоров по контракту (a)–(d): Provider снаружи / Inner внутри
  (хук до ранних return'ов), корень `relative` + условная пара
  `overflow-hidden`/`overflow-y-auto` по `expandedChartId` (правки A/C),
  визуальные блоки — в `ExpandableChartPanel` на уровне ИСПОЛЬЗОВАНИЯ (§7.2).
  Перечень панелей (chartId / что обёрнуто / что без панели):
  * EdaCorrelation: acf, pacf / таблица значений — нет.
  * EdaDescriptive: контейнер визуализации (histogram/kde/scatter из
    DistributionCharts, + SamplingBadge) / таблица статистик — нет.
  * EdaDistribution: histogram, density, qq, cdf / таблица «Тесты» — нет.
  * EdaFeatureSelection: association, matrix (HTML-теплокарта), vif,
    granger (панель только при granger_available, прецедент фазы Этапа 2) /
    таблица «Решение» — нет.
  * EdaIh: ranking, metrics (HTML-теплокарта), synergy и conditional
    (панели только при наличии данных) / таблица результатов — нет.
  * EdaSeasonality: fft, periodogram, phase (только при наличии данных) /
    таблица кандидатов — нет.
  * EdaStationarity (EDA): series, rolling_std, pvalues / таблица тестов — нет.
  * EdaValidationStrategy: folds (CSS-схема), train (Recharts) /
    «Альтернативы», таблица folds — нет.
  * PreprocessingFeatureEngineering: preview, lags, availability,
    cycles (только при наличии данных) / каталог-таблица — нет.
  * PreprocessingMissing: matrix, correlation, boxplot (чарт-блоки
    PreprocessingMissingVisualizations) / таблица колонок, прогресс-бар — нет.
  * PreprocessingOutliers: line, histogram, density, boxplot (чарт-блоки
    PreprocessingOutliersVisualizations) / таблица колонок — нет.
  * PreprocessingRegularity: intervals, timeline (чарт-блоки
    PreprocessingRegularityVisualizations) / таблица групп — нет.
  * PreprocessingScaling: preview, ranges, distribution (пара кривых
    до/после — один семантический блок) / таблицы «Корреляции», «Методы» — нет.
  * PreprocessingSmoothing: series, residual, methods, spectrum /
    «Диагностика» (метрики) — нет.
  * PreprocessingStationarity (Prep): series, rolling, tests, acf /
    таблица кандидатов — нет.
  * PreprocessingVariance: series, rolling, methods, distribution /
    «Диагностика» (метрики) — нет.
- detail_level/wiring на Этапе 4 не подключался: Этап 5 опционален (§8.6),
  раскрытие чисто визуальное с compact-данными; useChartDetailData остаётся
  только на 3 профилях пилота. Самофетчеры (Missing/Outliers/Regularity/
  Descriptive) сохраняют собственный феч-контур — Provider обёрнут снаружи.
- Изменено 16 файлов packages/ui/components/*Overview.tsx (+367/−61),
  контрактные тесты не правились (переключение файлов — кодом, не списком).
- Верификация: полный jest 89 suites / 817 tests = **817 PASS / 0 FAIL —
  чек-лист Этапов 1–4 закрыт полностью, RED-поле 20 → 16 → 16 → 0**;
  typecheck:all exit 0; production builds embedded + standalone OK (13/13,
  First Load JS без регресса); полный pytest 1350 passed, 0 failed
  (= базлайн Этапа 3; backend Этапом 4 не затронут).
- Коммит/push не выполнялись. Изменённые файлы упакованы в
  download/Task_97.4_ExpandableCharts_Stage4.zip (17 файлов: 16 Обзоров +
  worklog2.md).

### Что осталось (Этап 5, опционально)

- detail-режим для остальных профилей с плотными выборками — по решению
  тимлида; для большинства Обзоров (короткие/агрегированные ряды, гистограммы
  бинов, HTML-теплокарты) выигрыша от expanded нет, раскрытие остаётся
  чисто визуальным (§8.6). Калибровка вторичных потолков на реальных
  датасетах (§9 follow-up) — контракт уже зафиксирован константами.

---

## Task 97.4a — Hotfix: графики Обзоров не рендерятся (обёртка children ExpandableChartPanel)

- Синхронизация до 8506bc3 (= закоммиченный тимлидом Этап 4, rollout 16
  Обзоров, full GREEN); reset, дерево чистое. Симптом из браузера (скриншот
  «Обзор: Корреляция (ACF/PACF)», вкладка PACF): на всех вкладках графиков
  Обзоров область графика пустая, при этом иконка раскрытия в правом верхнем
  углу работает; таблицы (auto-height) рендерятся. Jest при этом 817/817 —
  дефект не ловится, т.к. jsdom не считает layout, а контрактные проверки
  структурные.
- Причина (анализ Этапов 1–4): в ExpandableChartPanel.tsx (фундамент Этапа 1,
  задействован Этапами 2–4) внутренняя обёртка children была block-элементом
  (<div className="min-h-0 flex-1"> без display:flex). Все обёрнутые
  визуальные блоки Обзоров спроектированы прямыми flex-потомками корня окна
  (flex flex-col h-[468px]) и сами сидят на «min-h-0 flex-1 …» — проверено
  по всем 20 адаптированным файлам (CorrelationChart, HistogramView/Density/
  Qq/Cdf, SpectrumChart, SeriesChart, MissingMatrixChart, ChartStatus,
  grid-корни Spectral/Smoothing/Scaling и т.д.). Внутри block-родителя
  flex-1 инертен: высота блока схлопывается до контента, ResponsiveContainer
  height="100%" против auto-родителя разрешается в 0 → пустая область.
  ChartExpandToggle (absolute, вне потока) и таблицы не зависят от flex-1 —
  ровно наблюдаемый симптом.
- TDD: 2 RED-теста в ExpandableChartPanel.test.tsx — «обёртка children в
  свёрнутой панели — flex-колонка min-h-0 flex-1 (не block)» и «…сохраняется
  и в раскрытой панели (absolute inset-0)»; против кода 8506bc3 падают
  ровно они (Received: min-h-0 flex-1), 8 прежних зелёные.
- Фикс центральный, один файл: ExpandableChartPanel.tsx, обёртка children
  теперь «flex min-h-0 flex-1 flex-col» — воспроизводит исходную flex-среду
  блока в обоих состояниях панели; 20 Обзоров и 4 пилота не трогались,
  OUT_OF_SCOPE не затронуты, ExpandableChartCoverage.test.ts не менялся.
- Верификация: полный jest 89 suites / **819 passed / 0 failed**
  (817 базлайн + 2 регресс-теста); typecheck:all exit 0; production builds
  embedded + standalone OK (13/13, First Load JS 87.5 kB без регресса).
  Backend не затронут (изменения только packages/ui) — pytest-базлайн
  1350 passed остаётся в силе.
- Коммит/push не выполнялись. Изменённые файлы упакованы в
  download/Task_97.4a_ExpandableCharts_Hotfix_ChartRenderFix.zip
  (3 файла: ExpandableChartPanel.tsx, ExpandableChartPanel.test.tsx,
  worklog2.md).

---

## Task 125 — TBATS production vertical slice

### Синхронизация

По прямому указанию тимлида выполнен `git reset --hard` до
`6b3ce89f3bdad1ccd092a396350c8ca0e148765c` ("Task 124 — Prophet production
vertical slice"). Подтверждено: тимлид закоммитил ровно тот набор файлов, что
был сдан в предыдущей задаче, без правок. Backend на этом коммите: 1340/1340
PASS. После этого начата Task 125.

### Повторная синхронизация на 08a4482 и проверка на затирание работы команды

После первой сдачи Task 125 (ZIP на базе `6b3ce89`) тимлид указал
синхронизироваться до `08a448214296b408c139b2cecb2b6df1e5b45cec` и явно
предупредил: "твоя реализация Task 125 может затереть работу команды".
Перед сбросом сохранён `git diff` и копии двух новых файлов в `/home/claude`
(вне репозитория) для последующей сверки. `git log 6b3ce89..08a4482` показал
6 коммитов команды — Task 97.1–97.4a (Overview Graph Collapse/Expand,
чисто frontend `packages/ui/*`) + `spec_max_graf_fix` — ни один не назван
Task 125 и не касается Modeling. Однако `git diff --stat 6b3ce89..08a4482`
неожиданно показал `apps/api/model_impls/tbats.py` и
`tests/unit/test_tbats_adapter.py` как уже добавленные — оба оказались
закоммичены внутри `08a4482` ("Hotfix: Overview charts..."), побайтово
идентичны сданному мной ZIP (проверено `diff` с сохранённой копией). Похоже,
тимлид вручную перенёс эти два НОВЫХ файла из ZIP в коммит вместе с
несвязанным frontend-хотфиксом, но не перенёс остальные 15 изменённых файлов
(`model_execution.py` на `08a4482` НЕ содержит регистрацию `tbats` — проверено
`grep`). Все 15 файлов, которые правит Task 125, оказались побайтово
идентичны состоянию на `6b3ce89` (`git diff --stat 6b3ce89 08a4482 -- <file>`
пуст для каждого) — команда их не трогала. Это значит:
- Реального риска "затереть работу команды" в этих 15 файлах не было — команда
  их не касалась, база не разошлась.
- Сохранённый ранее патч (15 файлов, без двух новых) применился к `08a4482`
  чисто (`git apply --check` — 0 ошибок), без единого конфликта.
- Два уже закоммиченных новых файла НЕ пересоздавались повторно — просто
  сверены байт-в-байт с моей версией (идентичны), чтобы не задваивать историю.
- Запись Task 125 в `worklog2.md` (эта секция) добавлена в конец файла ПОСЛЕ
  существующей записи Task 97.4a, а не вместо неё — предыдущая версия патча
  на `worklog2.md` пересобрана вручную, т.к. её контекст (конец файла) успел
  измениться из-за записей команды.

### Что сделано

TBATS добавлен как 11-я production-модель через `MODEL_EXECUTION_REGISTRY`, с
таким же участием в `run_backtest_plan`/exact EDA folds, что и у остальных
десяти. Использована **Nixtla StatsForecast, версия зафиксирована**
(`statsforecast==2.1.1`), класс `statsforecast.models.TBATS` — **сознательно
не `AutoTBATS`**: `AutoTBATS` запускает свой внутренний AIC-перебор структурных
спецификаций (Box-Cox вкл/выкл, trend, damped trend, ARMA errors) с
непредсказуемым по времени исполнением на каждый fit, что напрямую
противоречит требованию "Бюджетированное обучение и tuning без proxy
timeout" (Task 125, п.3). Явный `TBATS` с конкретными флагами даёт один
детерминированный fit на комбинацию параметров — то же свойство, что и у
ETS/ARIMA с явными order/trend (не двойной auto-поиск поверх auto-поиска).
Замерено на реальных данных: явный `TBATS` — 0.03–0.15с/fit в зависимости от
флагов; `AutoTBATS` для сравнения — ~1.4с/fit (внутренний перебор). Решение
подтверждено бенчмарком, не голым предположением; `_CLASSICAL_RESOURCES`
(`standard`, 120с step timeout) выбран с этим запасом, без пересмотра класса.

- **Множественные сезонные периоды из спектрального hand-off (Task 125,
  п.2)** — ключевая архитектурная работа задачи. Обнаружено: во всех ~7 местах
  `apps/api/routers/modeling_session.py` (`/backtest`, старый монолитный
  `/tune`, универсальный job-контракт Task 123 `/jobs/start|step`, legacy
  `/tuning/start|step`) список сезонных периодов из EDA-профиля жёстко
  усекался до одного значения: `.get("seasonal_periods") or [1])[0]` —
  единственное, что нужно было ВСЕМ девяти прежним моделям (все читают
  singular `seasonal_period`), но именно это ограничение блокировало TBATS
  (единственную модель с нативной поддержкой `season_length: List[int]`).
  Добавлен сквозной passthrough: `run_backtest_plan` → `execute_tuning_trial`
  → `execute_tuning_plan_with_artifacts`/`execute_tuning_plan`, новый параметр
  `seasonal_periods: Optional[Sequence[int]]`, применяется ТОЛЬКО если ключ ещё
  не занят явно переданными `params`. Diagnostics/Comparison/Model Card не
  тронуты — они читают уже сохранённый backtest, не пересчитывают модель.
- **Обнаружена и устранена коллизия имён ключей** (найдена не по докам, а по
  реальному падению теста `test_tuning_stage_requires_tune_or_explicit_skip_
  for_tunable_models`): `_ets_executor` уже читал
  `request.params.get("seasonal_periods", request.seasonal_period)` как
  singular-override периода (механизм Task 122, ранее ничем не заполнялся).
  Мой первый вариант плана использовал тот же ключ `"seasonal_periods"` для
  списка периодов TBATS — это привело к `int() argument ... not 'list'`
  внутри ETS, как только session router стал реально прокидывать hand-off
  (что происходит всегда, для любой модели). Ключ переименован в
  `tbats_seasonal_periods` — специфичный, не пересекающийся ни с чем; добавлен
  отдельный регрессионный тест
  `test_seasonal_periods_plumbing_does_not_collide_with_ets_override_key`,
  который явно фиксирует эту границу на будущее.
- **Bounded tuning**: `use_boxcox` × `trend_spec` = 2×3 = 6 trials.
  `trend_spec: {"none","trend","damped_trend"}` — это НЕ прямая пара
  независимых булевых флагов `use_trend`/`use_damped_trend`: смоук-тестом
  подтверждено, что `use_damped_trend=True, use_trend=False` — структурно
  невозможная в TBATS комбинация (`ValueError: Can't use damped trend without
  trend`), поэтому вместо 2×2 grid с двумя заведомо провальными ячейками
  введено одно поле с ровно тремя валидными значениями, транслируемое
  адаптером в пару флагов.
- **Box-Cox только внутри train-fold (Task 125, п.4)**: удовлетворяется по
  конструкции — TBATS создаётся заново на каждый fold
  (fit_policy="per_train_fold", как и у всех моделей registry), Box-Cox lambda
  оценивается statsforecast'ом внутри `.fit(y_train)`, никогда не видя
  test/future данные; отдельного кода не потребовалось.
- **Prediction intervals**: `supports_prediction_intervals=True`, честные
  `lo-80`/`hi-80` от `TBATS.predict(h, level=[80])` (тот же 80%-default, что и
  у Prophet в Task 124, для единообразия Model Card).
- Проверены и подтверждены смоук-тестом граничные случаи: короткая (8 точек) и
  константная серия не роняют fit (только `RuntimeWarning: divide by zero` на
  константной — безвредно, аналогично существующим `SingularMatrixWarning` у
  ARIMA).

### Обновлённые release-gate инварианты (10 → 11 моделей)

Ожидаемо и предусмотрено, как и в Task 124:
- `tests/unit/test_modeling_mvp_certification.py` — CERTIFIED_MODEL_IDS
  расширен, тест переименован в `..._exactly_eleven_real_models...`,
  `PRODUCTION_TUNING_MODEL_IDS` теперь включает `tbats`.
- `tests/unit/test_backtesting_engine.py` — `test_all_ten_...` →
  `test_all_eleven_production_models_execute_the_same_real_oof_cohort`.
- `tests/unit/test_model_readiness_candidates.py` — `tbats` перемещён из
  `catalog_only` в `ready`; `runnable_candidates` 10→11,
  `catalog_only_candidates` 14→13.
- `tests/unit/test_model_execution_contract.py` — `CERTIFIED_IDS` расширен.
- `tests/api/test_models_backtest_real.py` — `test_registry_has_10_
  implementations` → `..._11_implementations`; добавлены
  `test_tbats_impl_callable_with_minimal_series`, `"tbats"` в параметризацию
  `test_short_series_does_not_500`.
- `tests/api/test_modeling_workflow.py` —
  `test_workflow_rejects_catalog_only_model_instead_of_fabricating_metrics`
  использовал `model_id="tbats"` (заменён Task 124) как пример catalog-only;
  заменён на `"xgboost"` (по-прежнему catalog-only после Task 125).
  `tests/unit/test_model_capability_matrix.py` изменений не потребовал (там
  фигурировал только `prophet`).

### Новые тесты

- `tests/unit/test_tbats_adapter.py` (13 тестов, НОВЫЙ файл): форма
  forecast/интервалов, множественные периоды нативно, fallback на singular
  period, guard на неположительные периоды и неизвестный `trend_spec`,
  параметризованная проверка всех 3 валидных `trend_spec` (защита от
  структурно невозможной комбинации), registry descriptor, `execute()` читает
  `tbats_seasonal_periods` из params, честные intervals, полный прогон через
  реальный `build_backtest_plan`/`run_backtest_plan` с multi-period hand-off
  ([6, 12]), регрессионный тест на коллизию ключей с ETS (см. выше), размер
  bounded tuning grid ≤ MAX_TRIALS.
- `tests/api/test_modeling_workflow.py::
  test_tbats_full_session_backtest_and_tuning_use_the_real_spectral_handoff`
  (НОВЫЙ) — полный session-flow (backtest → diagnostics → tune) с реальным
  spectral hand-off. Обнаружена и обойдена нетривиальность: TBATS объявляет
  `min_observations=100` в каталоге, и правило `F04` (`n_observations <
  model.min_observations`) жёстко блокирует модель (`compatibility="blocked"`)
  — стандартная 96-точечная `_prepare()`-фикстура его не проходит, а с
  дефолтной validation-стратегией (5 splits × 12 horizon) даже 120-точечный
  ряд не проходит, т.к. `initial_train` (эффективный train первого fold, а не
  общий n) урезается ниже 100. Тест использует собственный 120-точечный
  датасет и уменьшенную схему валидации (`n_splits=2, horizon=2` через
  `/v1/session/modeling/candidates`) — то же самое ограничение, которое
  случайно задело и НЕСВЯЗАННЫЙ тест `test_tuning_stage_requires_tune_or_
  explicit_skip_for_tunable_models` (см. ниже).

### TDD-цикл

- RED (интеграция в registry, до правки тестов): целевой прогон дал ровно 6
  ожидаемых провалов — все из-за жёстко зашитого числа 10 в разных файлах; ни
  одного неожиданного.
- GREEN после обновления тестов на счёт "11" — но затем полный прогон
  `test_modeling_workflow.py` вскрыл РЕАЛЬНЫЙ баг (не тестовую хрупкость):
  коллизию ключей `params["seasonal_periods"]` между новым TBATS-plumbing'ом и
  существующим `_ets_executor`. Это ровно тот сценарий, ради которого TDD
  прогоняет полный набор, а не только целевой срез: узкий срез (registry+
  readiness) был бы зелёным и без исправления, баг проявился только в
  `test_tuning_stage_requires_tune_or_explicit_skip_for_tunable_models`
  (ETS-бэктест внутри сценария с реальным session-профилем). После
  переименования ключа в `tbats_seasonal_periods` — `test_modeling_workflow.py`
  целиком 39/39, полный backend regression без единого неожиданного провала.

### Проверки

- Полный backend regression (на базе `08a4482`): **1365/1365 PASS** (база на
  `08a4482` уже 1352 за счёт команды + мои 13 из `test_tbats_adapter.py`),
  3/3 snapshots PASS.
- Полный frontend regression: 89/89 suites, 819/819 tests PASS (рост за счёт
  Task 97.x команды — Task 125 backend-only, фронтенд не тронут).
- `typecheck:all`: embedded PASS, standalone PASS.
- Production build embedded/standalone: PASS, 13/13 статических страниц,
  First Load JS 468 kB (было 464 kB на `6b3ce89` — рост от Task 97.x команды,
  не от Task 125). Временный шим `next/font/google`
  применён, собран, немедленно отменён; `git diff` после отката — пуст.
- `pip check`: PASS. Рабочее дерево чистое.
- Установлен `statsforecast==2.1.1`, добавлен в `apps/api/requirements.txt` и
  в манифест `classical` пакетов (`apps/api/model_jobs.py`).

### Изменённые/новые файлы Task 125

Уже присутствуют в `08a4482` (закоммичены тимлидом ранее вместе с
несвязанным Task 97.4a, сверены байт-в-байт — не пересобираются в ZIP):
- `apps/api/model_impls/tbats.py`
- `tests/unit/test_tbats_adapter.py`

Изменённые в этой сдаче (входят в ZIP):
- `apps/api/backtesting.py`
- `apps/api/model_execution.py`
- `apps/api/model_impls/__init__.py`
- `apps/api/model_jobs.py`
- `apps/api/modeling_tuning.py`
- `apps/api/requirements.txt`
- `apps/api/routers/modeling_session.py`
- `apps/api/routers/models.py`
- `rules/modeling.yaml`
- `tests/api/test_modeling_workflow.py`
- `tests/api/test_models_backtest_real.py`
- `tests/unit/test_backtesting_engine.py`
- `tests/unit/test_model_execution_contract.py`
- `tests/unit/test_model_readiness_candidates.py`
- `tests/unit/test_modeling_mvp_certification.py`

### Что осталось за рамками Task 125 (осознанно)

- `use_arma_errors` зафиксирован адаптером (`False`) и не входит в bounded
  tuning grid — не упомянут в бюллетнях задачи, минимизация scope по
  прецеденту Prophet (Task 124: тюнится только явно specified в задаче).
- Прогресс "11/24" production-моделей достигнут (Prophet + TBATS). Следующие
  задачи по plan-файлу — ML/дерево-бустинг группа (Task 126+, начиная с
  Leakage-safe supervised FeaturePlan).

  ---

## Сертификация Tasks 124–125 на aab3584 и разбор видимости TBATS

### База и методика

Сертификация выполнена на точном коммите
`aab3584f8c8f0c534aa36fb7c874c541ac8ab0a1`; локальный `HEAD` и
`origin/main` совпадают. Проверены требования `docs/modeling_task_list.md`,
реализация registry/backtesting/tuning/session workflow, тесты, production
сборки и фактический PRE-контур Vercel → Render.

### Итог по плану

- **Task 124 — условно сертифицирована.** Prophet зарегистрирован как реальная
  production-модель, исполняется на точных платформенных EDA folds без второго
  CV, получает реальные train/future timestamps, создаёт fold-local holidays,
  имеет bounded grid 5×3×2, реальные prediction intervals и проходит общий
  OOF/diagnostics/comparison/selection/Model Card workflow. Однако буквальное
  требование плана о произвольных fold-local regressors не закрыто end-to-end:
  upstream ещё не формирует `train_features`/`future_features`. Этот разрыв уже
  был задокументирован в первоначальной сдаче Task 124 и остаётся зависимостью
  Task 126 (`Leakage-safe supervised FeaturePlan`). Поэтому без выполнения
  Task 126 полный безусловный PASS по каждому слову Task 124 некорректен.
- **Task 125 — сертифицирована после исправлений release gate.** TBATS является
  11-й production-моделью, использует зафиксированный `statsforecast==2.1.1`,
  получает несколько сезонных периодов через `tbats_seasonal_periods`, имеет
  ограниченный grid из 6 валидных trial, оценивает Box–Cox внутри каждого
  train-fold и проходит единый workflow долгих jobs и 11 остановок.

### Почему TBATS не была видна в «Доступных»

Это не отсутствие библиотеки или адаптера. PRE-запрос через Vercel к Render
подтвердил `platform_status="ready"`, `runtime_available=true`,
`statsforecast=2.1.1`; отдельный реальный TBATS backtest завершился успешно.
На широком профиле (`n_observations=500`) API возвращает TBATS с действиями
`backtest`, `tune`, `diagnostics` и всего 11 runnable production-моделей.

На коротком профиле TBATS блокируется правилом F04: первый train-fold должен
содержать не менее `model.min_observations=100`. Раньше UI называл runnable-
фильтр просто «Доступные» и исключал ready-модели без действия `backtest`, а
причина F04 приходила с неотрендеренными placeholders. Это создавало ложное
впечатление, что TBATS не подключена.

Исправлено:

- фильтр переименован в **«Для текущего ряда»**;
- добавлен отдельный фильтр **«Подключённые»**, где TBATS видна даже при F04
  со статусом «Ограничено», точной причиной и без активной кнопки запуска;
- DSL-сообщения applicability безопасно подставляют фактические значения:
  `Недостаточно данных: 60 < 100 (требуется TBATS)`;
- порог не ослаблялся: чтобы TBATS стала runnable, именно первый train-fold
  выбранного BacktestPlan, а не только весь ряд, должен иметь ≥100 наблюдений.

### Исправления сертификационного контура

- GitHub Actions теперь устанавливает `apps/api/requirements.txt`; ранее
  чистый CI мог молча получить урезанный runtime registry и при этом не
  сертифицировать Prophet/TBATS.
- Prophet закреплён как `prophet==1.4.0`, совпадающий с проверенным PRE runtime;
  StatsForecast остаётся `2.1.1`.
- API Dockerfile выполняет настоящий минимальный fit/predict Prophet и TBATS
  во время сборки, а не ограничивается импортом старых statsmodels-моделей.
- Добавлен release-gate тест на зависимости CI/image и регрессии UI/readiness
  для ready-but-blocked TBATS.
- Исправлена устаревшая документация ключа TBATS-параметров:
  `seasonal_periods` → `tbats_seasonal_periods`.

### TDD и проверки

- RED: новые backend-тесты выявили сырые `{n_observations}`/
  `{model.min_observations}` и отсутствие API dependencies в CI; новый UI-тест
  выявил отсутствие различия между runnable и connected production-моделями.
- GREEN: целевой backend-срез — **133/133 PASS**; Modeling UI — **48/48 PASS**.
- Полный backend regression — **1368/1368 PASS**, **3/3 snapshots PASS**.
- Полный frontend regression — **89/89 suites, 820/820 tests PASS**.
- `typecheck:all` — embedded PASS, standalone PASS.
- Production build — embedded и standalone PASS, по **13/13** статических
  страниц. Из-за отсутствия `/proc` и сети в рабочем контейнере только на время
  build использованы memory/font shims; после проверки они удалены, исходные
  layout-файлы восстановлены функционально.
- Исполняемый smoke — Prophet PASS, StatsForecast TBATS PASS.
- `pip check` — PASS; `git diff --check` — PASS.

### Файлы сертификационной доработки

- `.github/workflows/test.yml`
- `apps/api/Dockerfile`
- `apps/api/model_impls/tbats.py`
- `apps/api/requirements.txt`
- `apps/embedded/app/layout.tsx` (только нормализация финального перевода строки
  после временного build-shim, без изменения кода)
- `apps/standalone/app/layout.tsx` (то же)
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `src/catalog/modeling_spec_loader.py`
- `tests/test_modeling_spec.py`
- `tests/unit/test_model_readiness_candidates.py`
- `tests/unit/test_modeling_mvp_certification.py`

---

## Task 97.4b — Hotfix: детализация expanded-графиков роняет рендер (конверт ответа эндпоинта)

- Синхронизация до 4a2bd85 (сертификация Task 124–125; в апстриме также
  08a4482 = применённый тимлидом hotfix 97.4a); npm ci (окружение
  переустанавливалось). Симптом из браузера: Обзор «Декомпозиция ряда»,
  вкладка «Компоненты» — первичный compact-график корректен, скрытие
  корректно, через ~2 с (завершение detail-дозагрузки) рендер исчезает —
  пустое белое поле с живой легендой; схлопывание возвращает график.
  Вкладки «Сезонный профиль»/«ACF остатка» корректны (без дозагрузки).
- Причина: в пилотах Этапа 3 результат useChartDetailData передавался в
  график сырым ответом эндпоинта. Для /dataset/preprocessing/decomposition-profile
  и /dataset/preprocessing/spectral-profile это КОНВЕРТ статуса проверки
  {mode, status, status_reason, profile} (контейнер хранит конверт и
  передаёт в Обзор развёрнутый .profile), а «голый» профиль отдаёт только
  /dataset/eda-structural-breaks (поэтому structural-breaks не затронут).
  Следствие: Decomposition «Компоненты» — LineChart получал конверт,
  profile.points === undefined → пустое поле с легендой; Spectral CWT —
  WaveletView падал на envelope.wavelet.map → белое поле (тот же дефект,
  не вошедший в отчёт). Тесты Этапа 3 прошли из-за мока голым профилем.
- TDD: +4 теста. RED ровно на 2 регресс-тестах «detail-ответ-конверт
  разворачивается…»: Decomposition — через recharts-зонд (jest.mock
  recharts с JSON-пробой: в jsdom DOM recharts пуст, контролируем, какой
  payload дошёл до графика как data; ассерт: в data НЕТ полей конверта,
  ЕСТЬ detail-точка observed:42.25); Spectral — реальный краш
  TypeError: Cannot read properties of undefined (reading 'map') на
  profile.wavelet. Ещё 2 теста — graceful degradation (ошибка дозагрузки
  сохраняет компактный график) — зелёные сразу, фиксируют §6.3.6.
  Моки прежних detail-тестов переведены с голого профиля на конверт;
  в beforeEach добавлена очистка модульного кэша хука
  (__clearChartDetailCacheForTests).
- Фикс: 2 файла, типизация + развёртывание конверта на границе:
  PreprocessingDecompositionOverview.tsx — useChartDetailData<
  PreprocessingDecompositionProfileResponse>, график получает
  componentsDetail.data?.profile ?? profile;
  PreprocessingSpectralOverview.tsx — useChartDetailData<
  PreprocessingSpectralProfileResponse>, WaveletView получает
  waveletDetail.data?.profile ?? profile. Хук и бэкенд не менялись.
- Верификация: полный jest 89 suites / **824 passed / 0 failed**
  (= базлайн 4a2bd85 + 4 новых теста); typecheck:all exit 0; production
  builds embedded + standalone OK (обе «Compiled successfully», 13/13).
  Backend не затронут (4 файла packages/ui) — pytest-базлайн в силе.
- Коммит/push не выполнялись. Изменённые файлы упакованы в
  download/Task_97.4b_ExpandableCharts_Hotfix_DetailEnvelope.zip
  (5 файлов: 2 Обзора + 2 тест-файла + worklog2.md).

---

## Task 97.4c — Hotfix: chart-сетки Обзоров «залипали» на высоте раскрытого графика после схлопывания

- Симптом из браузера: Обзор «Стабилизация дисперсии» (Предобработка),
  вкладка «Распределения» — первичный рендер корректен, раскрытие и
  раскрытое состояние корректны; после схлопывания графики «уезжают вниз»,
  не возвращаясь к исходному размеру: переполняют окно Обзора, налезают на
  методологическое примечание, окно уходит в скролл (скриншот в задаче).
- Причина: корень DistributionCharts — grid
  (`grid min-h-0 flex-1 grid-cols-2`) БЕЗ явного шаблона строк → неявный
  ряд auto размеряется по контенту, а recharts записывает в svg явную
  пиксельную высоту измеренного контейнера. Раскрытие (absolute inset-0,
  вся высота окна) увеличивает svg; после схлопывания auto-ряд не может
  сжаться ниже min-content (высота svg) — ряд «залипает» на раскрытой
  высоте, ResizeObserver ResponsiveContainer не срабатывает, график
  остаётся большим. Соседние вкладки («До/после», «Скользящая σ»,
  «Методы») используют block-корни — height:100% разрешается от definite
  flex-высоты и дефекта нет; потому баг виден только на «Распределениях».
- Латентные аналоги (тот же класс дефекта «grid + 2 ResponsiveContainer
  без шаблона строк») найдены поиском и починены в той же задаче
  (прецедент 97.4b): Stationarity «Ряд» и «Rolling μ/σ», Scaling
  «Распределение», Smoothing «Остаток / ACF», Spectral «FFT / Periodogram»
  и «Welch PSD» — всего 6 grid'ов в 5 файлах.
- Ложная тревога (зафиксирована для истории): при анализе заподозрено
  повреждение arbitrary-класса колонок Welch («grid-cols-inmax…»).
  Побайтовая проверка (hex-коды символов) показала: класс в файле
  корректен — grid-cols-[minmax(0,2fr)_minmax(170px,1fr)]; «повреждение» —
  артефакт отображения вывода shell-инструмента (съедание «[m» в выводе).
  Код Welch не менялся (кроме grid-rows-1); в тест добавлен ассерт,
  фиксирующий корректный arbitrary-класс.
- TDD: +5 регресс-тестов (по одному на Обзор; jsdom layout не считает,
  поэтому структурные ассерты на классы — паттерн 97.4a): grid-обёртки
  chart-вкладок обязаны иметь grid-rows-1 (= repeat(1, minmax(0,1fr)) —
  ряд размеряется от definite-высоты контейнера flex-цепочки панели и
  сжимаем до 0, ResponsiveContainer следует за свёрнутой панелью);
  в Variance и Smoothing дополнительно фиксируется ровно 2 ячейки
  единственного ряда, в Spectral — корректные колонки Welch 2fr/1fr.
  RED подтверждён ровно на 5 новых тестах (5 failed / 18 passed).
- Фикс: 5 файлов packages/ui — класс grid-обёрток дополнен grid-rows-1:
  PreprocessingVarianceOverview (DistributionCharts),
  PreprocessingStationarityOverview (SeriesView, RollingView),
  PreprocessingScalingOverview (DistributionView),
  PreprocessingSmoothingOverview (ResidualView),
  PreprocessingSpectralOverview (GlobalView, WelchView).
  ExpandableChartPanel / провайдер / хуки / бэкенд не менялись.
- Верификация: полный jest 89 suites / 829 passed / 0 failed (= 824
  базлайна 4a2bd85 + 5 новых); typecheck:all exit 0; production builds
  embedded + standalone OK (обе «Compiled successfully», 13/13).
  Backend не затронут — pytest-базлайн в силе.
- Коммит/push не выполнялись. Изменённые файлы упакованы в
  download/Task_97.4c_ExpandableCharts_Hotfix_GridRowLatch.zip (11 файлов:
  5 Обзоров + 5 тест-файлов + worklog2.md). Примечание:
  PreprocessingSpectralOverview.tsx/.test.tsx содержат также изменения
  97.4b (развёртывание конверта detail-ответа) — файл общий для обеих
  незакоммиченных задач.

---

## Аудит Task 126 — сдача Qwen_python_20260907_n3jc21r5f.zip (рецензия senior-разработчика)

Дата: 2026-09-07. База аудита: `main @ 9935252` (ZIP из `docs/`). Файлы распакованы, промапплены в структуру репозитория, тесты исполнены; деревом репозитория изменения не становились (после проверок удалены).

### Состав сдачи (5 файлов, пути в ZIP не сохранены)

1. Ядро `FeaturePlan`/`FoldFeatureEngine`/`validate_feature_plan_for_model` (307 строк) → соответствует `apps/api/feature_plan.py`.
2. Prophet-интеграция (162 строки) → соответствует `apps/api/model_impls/prophet_features.py`.
3. «Schema v7 additions» (56 строк) — отдельные pydantic-модели `FeaturePlanOut`/`ModelExecutionContractV7`/`BacktestResponseV7`, никуда не включены.
4–5. Два тест-файла (268 и 200 строк) → `tests/unit/test_feature_plan.py`, `tests/unit/test_prophet_features.py`.

### Вердикт: НЕ ПРИНЯТЬ. Сдача не соответствует инструкциям тимлида и AGENTS.md.

### Блокер 1 — тесты не запускались коллегой (нарушение TDD)

- Тесты Prophet-интеграции не собираются: `ImportError: cannot import name 'ModelExecutionRequest' from 'apps.api.schemas'` — класс фактически живёт в `apps/api/model_execution.py`; `apps/api/schemas.py` его не экспортирует. Ошибка импорта на этапе collection — файл физически не мог быть запущен.
- Ядро FeaturePlan: **3 из 15 тестов падают** на собственной реализации автора, включая ключевой leakage-тест `test_no_future_leakage_in_lags` (ожидание 13.0, факт 11.0 — медианная импутация вместо хвоста train) и `test_fit_transform_basic` (тест ожидает NaN первой строки, имьютация её заполняет). В `test_imputation_on_train` арифметическая ошибка в ожидании (10.5 против фактической медианы 11.0). Признак того, что RED→GREEN-цикл не был завершён, а тесты писались без прогона.

### Блокер 2 — реальная утечка в ядре (прямая противоположность критерию завершения)

Runtime-эксперименты (train [10..13], будущее [14,15,16]):
- `transform(полный df)` кладёт в historic-лаги для будущих строк **реальные будущие значения** `[13, 14, 15]` — oracle-утечка, ровно то, что задача запрещает. Docstring обещает «для test-данных признаки будут NaN» — код этого не делает; `shift()`/`rolling()` считаются по всему переданному df без границы train/future.
- `transform(только test)` даёт для первой будущей точки импутированную медиану (11.0) вместо последнего значения train (13.0): движок не хранит хвост train, следовательно **единый рекурсивный контракт (лаги будущего только из прогнозов) с этим API недостижим**. Параметр `is_train` — мёртвый.

### Блокер 3 — мёртвые пути ядра

- Любой план с `kind="categorical"` падает `KeyError` в `fit()`: `_build_historic_features` никогда не строит категориальные колонки, а encoder фитайнится по `historic_df[self._categorical_features]`. Train-only one-hot не реализован, OneHotEncoder — недостижимый код.
- `kind="calendar"` и `kind="numeric"` объявлены в типах, но веток построения нет → `KeyError` в `fit()`. Роли разделены только словарями-геттерами; рабочее разделение ролей в матрицах отсутствует.

### Блокер 4 — отсутствие всей интеграционной части

- **Cohort**: FeaturePlan не включён в cohort — нет правок `backtesting.py` (при том, что `build_backtest_plan` уже принимает `feature_contract` в cohort_id/fingerprint), `model_execution.py`, фолд-цикла `run_backtest_plan`, тюнинга и jobs. «Фолд-local» не подключён ни к одному реальному пути исполнения.
- **Prophet**: написан параллельный `_prophet_fit_predict_with_features` вместо расширения существующего адаптера Task 124 (`apps/api/model_impls/prophet.py`, registry-исполнитель); в `MODEL_EXECUTION_REGISTRY` не зарегистрирован, `build_prophet_features_from_plan` никем не вызывается. Static-категориальные регрессоры (строки) уронили бы Prophet — кодирования нет.
- **Schema v7**: реальный механизм — `MODELING_ARTIFACT_SCHEMA_VERSION = 6` и `_migrate_modeling_artifacts()` в `routers/modeling_session.py`; в сдаче только отдельные V7-модели, никем не импортируемые; `BacktestResponseV7` не наследует реальный `BacktestResponse` (несмотря на собственный комментарий «inherited»). Миграции артефактов 6→7, инвалидации cohort, проверки session/tuning/job путей — НЕТ.
- **Recursive/direct**: контракт multi-step стратегий отсутствует полностью; capability `direct` и запрет direct без явной поддержки — не реализованы (при том, что `requires_train_features`/`supports_future_features` в платформе уже есть и гейтируются fail-closed, а валидатор коллеги возвращает мягкие warnings и никем не вызывается).
- **Importance**: `get_feature_importance_matrix` — повторный `transform()` по полному df (с утечкой из Блокера 2); привязки к точной fold-матрице/OOF-артефактам/lineage нет.

### Приёмка формата (AGENTS.md)

- В ZIP пути репозитория не сохранены (5 файлов с генерированными именами) — отступление от установ Practice предшествующих задач.
- Запись в worklog2.md не приложена — прямое нарушение протокола.

### Что принято

- `FeatureSpec`/`FeaturePlan` как иммутабельные датаклассы с детерминированным sha256-fingerprint — разумная заготовка идентичности плана; 12/15 валидационных тестов (роли, kinds, fingerprint) проходят.
- Контракт «Prophet получает только future_known+static, с проверкой длин train/future» на уровне сигнатуры соответствует указанию.
- `scikit-learn` уже в `requirements.txt` — новых зависимостей не требуется.

### Обязательные условия повторной сдачи

1. Устранить утечку: движок хранит хвост train; historic-признаки будущего строятся только из хвоста train + рекурсивных прогнозов; явная граница train/future в API; честные RED-тесты на oracle-утечку.
2. Достроить ядро: рабочие ветки lag/rolling/calendar/numeric/categorical, train-only imputation/scaling/one-hot (fail-closed вместо warnings — платформенный стандарт), fresh-инстанс на каждый fold.
3. Интеграция: FeaturePlan как feature_contract в `build_backtest_plan`/cohort_id, fold-цикл `run_backtest_plan`, расширение существующего Prophet-адаптера, capability-гейты recursive/direct в registry.
4. Миграция `MODELING_ARTIFACT_SCHEMA_VERSION` 6→7 с инвалидацией cohort и прогоном session/tuning/job путей.
5. Исправить импорты, довести все тесты до GREEN на реальном прогоне, приложить worklog2.md и ZIP с сохранением структуры каталогов.

---

## Task 126 — Leakage-safe supervised FeaturePlan (повторная реализация senior-разработчика)

Дата: 2026-09-08. База: `main @ 27a3d32` (Task 97.4c Hotfix). Полная ре-имплементация с нуля по критериям тимлида; ошибки отклонённой сдачи Qwen (см. рецензию выше) устранены по построению. TDD: RED-тесты зафиксированы до реализации, весь новый контур доведён до GREEN на реальном прогоне. Commit/push в main не выполнялся.

### Состав (5 исходных файлов + 6 тест-файлов)

1. `apps/api/feature_plan.py` (NEW, ~860 строк) -- ядро: `FeatureSpec`/`FeaturePlan` (иммутабельные, детерминированный sha256-fingerprint и plan_id=`fp_<hex12>`), `build_feature_plan_from_metadata` (fail-closed-парсер каталога «Генерация признаков»: роли строго по `known_in_advance`+`static`, дубликаты/stale-каталог/unknown-family/lookback>max_lookback отклоняются), `empty_feature_plan`, `FoldFeatureMatrixBuilder` (fresh-инстанс на fold, одноразовый), `RecursiveFeatureState`, `bind_feature_importance`.
2. `apps/api/backtesting.py` -- `BacktestPlan` получил `feature_plan`/`feature_columns`; `build_backtest_plan` принимает план и кладёт `plan.feature_contract()` в `cohort_contract` (cohort_id производен от плана; без плана -- legacy-контракт, старые cohort_id не меняются); `run_backtest_plan` строит fold-матрицы fresh-билдером на каждый fold, гейтит regressor-канал capability-дескриптором (`univariate`/`gated`/`granted`/`none`+`legacy-injected`), пишет `fold["feature_matrix"]` (lineage: plan_id/fingerprint/matrix_hash/columns/future_known_columns/fit_policy="per_train_fold"), warning'и -- в общий пул.
3. `apps/api/model_impls/prophet.py` -- расширение СУЩЕСТВУЮЩЕГО адаптера Task 124 (не параллельная копия): `_validated_regressors` (fail-closed: симметрия train/future, длины, NaN/Inf) + `add_regressor` до fit; без регрессоров поведение Task 124 не изменено.
4. `apps/api/model_execution.py` -- `prophet` определение: `input_kind="supervised"`, `supports_future_features=True` (единственный supervised-адаптер cohort); `_prophet_executor` прокидывает regressor-канал.
5. `apps/api/routers/modeling_session.py` -- `MODELING_ARTIFACT_SCHEMA_VERSION 6→7`; миграция: активный `feature_contract` без `plan_id`+`fingerprint` инвалидируется (v6-артефакты с policy=none остаются валидны); `_session_feature_plan(session, prepared)` -- верифицирует сохранённую metadata генерации (source_column==target, колонки присутствуют/числовые/конечные/по длине ряда) и либо даёт план в cohort, либо явно понижает до legacy с warning'ом; план включён во ВСЕ 6 путей `build_backtest_plan` (baselines, backtest, sync-tuning, job-inputs, job-start, job-step), warning'и -- в preprocessing_warnings.
6. `apps/api/schemas.py` -- `BacktestFoldResult.feature_matrix: Optional[Dict]` (lineage доходит до API/фронтенда).

Тесты: NEW `tests/unit/test_feature_plan.py` (20 -- построение/роли/kinds/fingerprint/политики), `tests/unit/test_feature_plan_folds.py` (32 -- каузальность lag/rolling внутри fold, отсутствие y[t] в строке, warmup-дроп, future-канал только future_known+static, recursive-контракт из хвоста train и иммунитет к фактам теста, NaN-экзогены, fold-local imputer/scaler/one-hot, static-константность, matrix_hash/lineage/importance-привязка, empty-план), `tests/unit/test_feature_plan_backtest.py` (10 -- cohort-привязка, только future_known в request, capability-гейты, univariate-warning, historic-only без future-payload, legacy-эквивалентность, importance↔fold-матрица), `tests/unit/test_prophet_regressors.py` (7 -- regressor-контракт + backcompat). UPDATED `test_prophet_adapter.py`/`test_model_execution_contract.py` (prophet supervised-capability), `tests/api/test_modeling_workflow.py` (3 миграционных теста v6→v7 + NEW E2E: план в session-cohort, naive-гейт с warning, Prophet-регрессор fold-local lineage, stale-колонка понижает cohort с warning, v7-миграция инвалидирует план без plan_id).

### Как закрыты блокеры рецензии Qwen

- Блокер 2 (oracle-утечка): derived-признаки пересчитываются каузально ВНУТРИ train-среза fold'а; путь материализации historic-признака будущего в API отсутствует -- `future_matrix()` строится только из future_known/static; рекурсия -- через `RecursiveFeatureState` (хвост train + прогнозы; `next_row` игнорирует факты теста по построению, покрыто distractor-тестом).
- Блокер 3 (мёртвые ветки): реализованы lag/rolling(mean|std|sum|min|max)/difference + numeric/categorical exogenous + calendar/trend/fourier; one-hot фитуется на train-категориях fold'а (порядок первого появления), unknown future-категория -- нулевой вектор; imputation -- train-медиана fold'а (NaN future-known запрещены); scaler -- train mean/std (ddof=0) по флагу `scale_exogenous`; статусы статистик -- `statistics()` для аудита fold-local fit.
- Блокер 4 (интеграция): FeaturePlan -- в cohort_contract/cohort_id (включая tuning/job-пути через общий `build_backtest_plan`); единый recursive-контракт (`RecursiveFeatureState`) с policy=recursive по умолчанию; direct -- только явной policy; capability-гейт: без `supports_future_features` регрессоры не передаются + warning (плюс registry-гейты `ModelExecutionRegistry.execute`); importance -- `bind_feature_importance` строго к matrix_hash той самой fold-матрицы (чужие колонки отклоняются).
- Блокер 1 (TDD/импорты): все импорты реальные, полный прогон GREEN (1440 passed; базлайн 1365 + 75 новых/обновлённых). Snapshot-плагин среды -- syrupy по requirements-dev.txt.
- Формат сдачи: ZIP с сохранением структуры каталогов + настоящая запись в worklog2.md.

### Верификация

- `python -m pytest tests/` -- **1440 passed** (включая новые 73 тест-функции Task 126 и обновлённые контракты).
- `python -m compileall apps` -- OK; `from apps.api.main import app` -- OK.
- Фронтенд не затронут (0 содержательных diff в embedded/standalone/packages); Jest-прогон не информативен в среде без node_modules и не требовался.
- Примечание по среде: установлены pinned-зависимости из apps/api/requirements.txt (prophet==1.4.0, statsforecast==2.1.1) и requirements-dev.txt (syrupy, fakeredis, PyWavelets, pandera, arch, ruptures, missingno) -- без них часть существующего suite не собирается независимо от Task 126.
- В рабочем дереве присутствуют посторонние mode-изменения (100644→100755) и чужие удаления `apps/*/app/upload/page.tsx` -- к Task 126 не относятся, в сдачу не включены, не откатывались.

---

## Сертификация Task 126 на b8907a8 — Leakage-safe supervised FeaturePlan

### База и методика

Сертификация выполнена на точном коммите `b8907a87d97dae7118a3057c6e53d1e97425be43`
(Task 126 — повторная реализация senior-разработчика); локальный HEAD и
`origin/main` совпадают, рабочее дерево чистое. Проверены требования
`docs/modeling_task_list.md::Task 126`, пять обязательных условий повторной
сдачи из рецензии на отклонённую Qwen-версию, код реализации
(`apps/api/feature_plan.py`, `backtesting.py`, `model_execution.py`,
`model_impls/prophet.py`, `routers/modeling_session.py`, `schemas.py`),
тесты (4 новых файла + 4 обновлённых) и независимый прогон полного
backend-регрессии в чистом окружении.

### Итог по плану: СЕРТИФИЦИРОВАНА. Реализация отличная.

Проверка по пунктам плана Task 126:

1. **Fold-local лаги/rolling/календарные признаки** — закрыто.
   `FoldFeatureMatrixBuilder._derived_column` пересчитывает lag/rolling/difference
   каузально ВНУТРИ train-среза каждого EDA-fold (`train_slice[position-lookback:position]`
   — окно никогда не включает y[t]; сверено с семантикой `past.shift(1).rolling(window)`
   платформенного генератора — точное совпадение). Warm-up-строки дропаются, а не
   импутируются. Календарь/Fourier/trend берутся из платформенных колонок по позициям
   fold'а (gap+horizon покрыт, проверено тестом `test_future_matrix_covers_gap_plus_horizon`).
2. **Разделение historic / future-known / static X** — закрыто. Роли выводятся
   из единственного авторитета — флага `known_in_advance` (+явный `static`) каталога
   генерации; static-константность проверяется внутри train-среза до кодировки;
   категориальная historic-экзогена (неизвестное будущее) отклоняется outright.
3. **Запрет неизвестных будущих регрессоров** — закрыто. По построению API:
   `future_matrix()` материализует ТОЛЬКО future_known/static — пути материализации
   historic-признака будущего в коде не существует (закрытие Блокера 2 отклонённой
   сдачи). NaN/Inf в future-known — fail-closed. Источник ролей verified E2E:
   stale/битая колонка понижает сессию до legacy-cohort с явным warning.
4. **Multi-step: единый recursive-контракт; direct — только явная поддержка** — закрыто.
   `RecursiveFeatureState` хранит хвост train, `next_row(prediction)` строит признаки
   из истории ДО добавления прогноза; distractor-тест доказывает иммунитет к фактам
   теста. POLICY_RECURSIVE — дефолт всей платформенной проводки; POLICY_DIRECT
   достижим только явной конструкцией, исполняющего контура direct сегодня нет
   (честно: появится с ML-адаптерами 127+).
5. **Fold-local imputation/scaling/encoding** — закрыто. Медиана/mean-std(ddof=0)/
   one-hot фитуются заново на train-срезе каждого fold'а; builder одноразовый
   (повторный fit_fold → FeaturePlanError); unknown future-категория → нулевой
   вектор без подмены train-кодировки; статистики доступны для аудита через
   `statistics()`.
6. **Feature fingerprint и importance lineage** — закрыто. Иммутабельный план,
   детерминированный sha256-fingerprint и plan_id входят в cohort_contract/cohort_id;
   каждый fold пишет `feature_matrix`-lineage (plan_id/fingerprint/matrix_hash/
   columns/fit_policy=per_train_fold) — доходит до API-схемы
   (`BacktestFoldResult.feature_matrix`); `bind_feature_importance` привязывает
   importance к ТОЧНОЙ fold-матрице, чужие колонки отклоняются.
7. **MLForecast-ориентир при платформенных folds** — соблюдено: лаг-трансформы
   по семантике MLForecast, но folds — строго платформенный BacktestPlan, второго
   CV-контура нет.

Все пять условий повторной сдачи из рецензии закрыты (утечка/ядро/интеграция/
миграция 6→7/формат). Существенные архитектурные решения приняты корректно:
расширение СУЩЕСТВУЮЩЕГО Prophet-адаптера Task 124 (не параллельная копия);
regressor-канал только при `supports_future_features` с учётом уже существовавших
с Task 122 гейтов registry; инъекция плана во все 6 путей `build_backtest_plan`
(bootstrap, backtest, sync-tuning, job-inputs, job-start, job-step); reuse-логика
по cohort_id автоматически инвалидирует pre-plan артефакты; миграция v6→v7
инвалидирует активный feature_contract без plan_id+fingerprint (policy=none
остаётся валиден).

### Независимая верификация

- Окружение пересобрано с нуля: pinned `apps/api/requirements.txt` +
  `requirements-dev.txt` (prophet==1.4.0, statsforecast==2.1.1, syrupy и др.).
- Целевые срезы: `test_feature_plan*.py` + `test_prophet_regressors.py` —
  **69/69 PASS**; `test_modeling_workflow.py` + `test_prophet_adapter.py` +
  `test_model_execution_contract.py` + `test_modeling_mvp_certification.py` —
  **60/60 PASS** (включая 3 новых E2E: план в session-cohort с гейтом naive и
  Prophet-lineage; stale-колонка понижает cohort; v7-миграция инвалидирует
  план без plan_id).
- Полный backend regression: **1440 passed / 0 failed**, 3/3 snapshots PASS —
  счётчик сошёлся с заявленным коллегой ровно (базлайн 1365 на 9935252 + 75).
- **Mutation-проверка RED-валидности** (независимая, сверх прогона коллеги):
  временная мутация rolling-окна до включения y[t] —
  `test_rolling_excludes_current_observation` закономерно FAILED; после отката
  дерево чистое. Leakage-охрана тестов доказана, а не декларирована.
- `python -m compileall apps` OK; `from apps.api.main import app` OK;
  `pip check` — PASS.
- Фронтенд не затронут (все 14 файлов коммита — backend/тесты/worklog);
  зависимостей UI от `artifact_schema_version` нет — Jest/typecheck/build
  не требуются, базлайн b8907a8 в силе.

### Наблюдения (не блокирующие, в копилку Tasks 127+)

1. Historic-экзогены (family=exogenous, known_in_advance=False) принимаются
   ядром, но `_session_feature_plan` материализует в feature_columns только
   future_known/static — сессия с такой колонкой упала бы по фолдам. Сегодня
   недостижимо (генератор платформы семьи exogenous не эмитит); при вводе
   экзогенных колонок в Tasks 127+ проводку колонок через
   `_session_feature_plan` нужно дополнить.
2. `RecursiveFeatureState` и `bind_feature_importance` — контракты без
   runtime-потребителей (по дизайну): потребуются адаптерам RF/XGBoost/
   LightGBM/CatBoost (Tasks 127–130).
3. Prophet + укорачивающее преобразование target (first_difference и т.п.)
   падает по фолду — pre-existing поведение Task 124 (рассинхрон
   train_timestamps), не регрессия 126; поведение fail-closed, утечки нет.
4. `scale_exogenous` по умолчанию False и роутером не включается — флаг
   ждёт своих потребителей в ML-задачах.

### Вердикт

**Task 126 сертифицирована. Реализация отличная.** Состав сдачи: 14 файлов
(6 backend-модулей, 7 тест-файлов, worklog2.md), +2630/−17 строк. Коммит и
push в main выполнены тимлидом; со стороны агента изменений кода не потребовалось.

---

## Task 124 — финальная сертификация: произвольные fold-local regressors end-to-end (8ee9579)

### База и постановка

Синхронизация до `8ee9579cedb45221feef6ee005f8330daf81a3b8` («Task 126 certification on
b8907a8»). Состояние Task 124 на входе — «условно сертифицирована»: все требования
Prophet выполнены (точные EDA folds, реальные timestamps, fold-local holidays, bounded
grid 5x3x2, интервалы, общий OOF-workflow), кроме буквального пункта плана
«fold-local regressors»: произвольные регрессоры пользователя не были объявляемы
end-to-end — зависимость Task 126. После сертификации Task 126 ядро платформы
(FeaturePlan → FoldFeatureMatrixBuilder → capability-гейт → regressor-канал адаптера)
готово, но остались три разрыва upstream-проводки:

1. генератор каталога признаков не эмитит `family=exogenous` — произвольную колонку
   датасета невозможно было объявить регрессором;
2. `_session_feature_plan` материализовала в `feature_columns` только
   future_known/static — сессия с historic-экзогеной упала бы в fold'е
   (`_platform_column` → FeaturePlanError);
3. контракт `with_regressor_specs`-уровня не имел runtime-потребителя и API-точки.

### Реализация (TDD: RED → GREEN, точки изменения)

- `apps/api/feature_plan.py` (+93): `_regressor_spec` + `with_regressor_specs(plan,
  declarations, *, policy=None)` — слияние объявлений в иммутабельный план:
  FeatureSpec(kind=exogenous), роль из known_in_advance/static (тот же авторитет, что
  и каталог), дубликаты имён против каталога/внутри объявлений отклоняются,
  static без known_in_advance отклоняется, план не мутируется, plan_id/fingerprint
  пересчитываются → cohort_id меняется, reuse-логика инвалидирует старые артефакты;
  пустой список — план без изменений (байтоффа cohort_id нет).
- `apps/api/session_store.py` (+18): поле `AnalysisSession.modeling_feature_regressors`
  (список {column, known_in_advance, static}), сброс в `set_dataset` (новый датасет —
  старые колонки могут отсутствовать), сериализация to_dict/from_dict с
  backcompat-дефолтом `[]` для старых Redis-записей.
- `apps/api/routers/modeling_session.py` (+175/−13):
  - `_session_feature_plan`: слияние объявлений через `with_regressor_specs`
    (fail-closed: FeaturePlanError → план исключён с warning), материализация ВСЕХ
    объявленных ролей — future_known/static строго конечны (NaN/Inf запрещены),
    historic-экзогены допускают NaN (импутация медианой train-среза fold'а), Inf
    запрещены; регрессор, равный target, понижает план (warning); план без каталога
    генерации, но с объявлениями — валидный регрессорный план policy=recursive;
  - новые эндпоинты `GET/PUT /v1/session/modeling/feature-regressors`: полная замена
    списка, fail-closed валидация против активного датасета (существование, числовой
    dtype, не target, дубликаты, static-константность по ряду), нормализация и
    сохранение; все 6 путей build_backtest_plan покрыты автоматически через
    `_session_feature_plan`.
- `apps/api/backtesting.py` (+17): в granted-режиме historic-экзогены никогда не
  проходят в regressor-канал (структурно — train_known_matrix/future_matrix содержат
  только future_known/static), но теперь это сообщается явно: один warning на run
  вместо тихого деградационного пути.

### Тесты (32 новых: 21 unit + 11 API)

- `tests/unit/test_feature_regressors.py` — роли объявлений, иммутабельность и
  identity-сдвиг плана, дубликаты/static/missing-флаг, регрессорный план без каталога,
  материализация historic/future/static в `_session_feature_plan`, fail-closed
  понижения (отсутствие колонки, NaN в future-known, регрессор==target), интеграция с
  run_backtest_plan через _StubRegistry: future-known проходит в request симметрично
  train+future, historic НЕ проходит ни при каком гейте (строгий future-known
  contract), mixed-разделение по ролям, cohort_contract несёт объявления.
- `tests/api/test_feature_regressors_api.py` — PUT/GET roundtrip и замена списка,
  422/404 на неизвестную/целевую/нечисловую/не-константную static колонку и дубликаты,
  E2E: объявление `driver` → cohort_contract.future_known=[driver] → fold-матрицы
  с future_known_columns=[driver] → spy-обёртка доказывает, что РЕАЛЬНЫЙ Prophet
  получил train_features/future_features по `driver` на каждом fold'е (fit+predict
  с add_regressor); смена объявлений меняет cohort_id; персистентность
  to_dict/from_dict; set_dataset сбрасывает объявления.

### Независимая верификация

- RED-прогон: новые тесты падали до реализации (ImportError/behavior).
- Mutation-проверки RED-валидности (сверх прогона):
  1) swap ролей future_known/historic в `_regressor_spec` → 9 тестов FAILED
  (утечка неизвестного будущего в канал ловится); 2) удаление материализации
  historic-объявлений в `_session_feature_plan` → 3 теста FAILED (разрыв
  end-to-end ловится). Обе мутации откатаны, дерево возвращено в GREEN.
- Полный backend regression на финальном дереве: **1472 passed / 0 failed**,
  3/3 snapshots (базлайн 8ee9579: 1440 + 32 новых — счётчик сходится ровно).
- Смежные срезы до полного прогона: feature_plan/prophet/execution (87 PASS),
  modeling workflow API (42 PASS).
- Сборка: `python -m compileall apps` OK; `from apps.api.main import app` OK;
  `pip check` PASS. Окружение: pinned requirements (prophet==1.4.0,
  statsforecast==2.1.1) + requirements-dev.
- Фронтенд не затронут (4 backend-файла + 2 тест-файла); новые ключи сериализации
  сессии аддитивны, UI-зависимостей от них нет — Jest/typecheck/build не требовались.
- UI-форма объявления регрессоров (выбор колонок/флагов) — отдельная UI-задача,
  API-контракт готов к подключению.

### Вердикт

**Task 124 сертифицирована окончательно. Требование «fold-local holidays/regressors
и строгий future-known contract» закрыто end-to-end:** пользователь объявляет
произвольные числовые регрессоры через API, роли выводятся из
known_in_advance/static, признаки строятся fold-локально (fresh builder на каждый
fold, статистики только train-среза), future_known/static доходят до Prophet
(add_regressor до fit, симметричный train/future канал), historic существуют только
в train-матрицах аудита, будущее historic не материализуемо по построению, каждая
битая деталь понижает план fail-closed с warning. Состав сдачи: 6 файлов
(4 backend-модуля, 2 тест-файла), +303/−13 в коде + 32 теста. Коммит/пуш — по
указанию тимлида.

---

## Task/without a number — Обновление worklog_summary.md (Tasks 76–94)

Дата: 2026-09-06. Синхронизация: main @ bb41796 (для контекста);
источник саммари — worklog.md (Tasks 1–75, @52078e2) и worklog2.md
(Tasks 76–94, @ae4a27f — последняя точка, реально отражённая в файле).

worklog_summary.md дополнен разделами по Tasks 76–94 без потери структуры
и содержания разделов 1–7 оригинала: продолжения треков EDA (76–80),
Предобработка (81–87, сводная таблица методологических решений),
UI/UX (88–89, контракт высоты 468px); новый трек «Паспорта свойств
ряда» (90–93); трек «Моделирование» — сквозная трассируемость и Model
Card (94). Раздел сквозных практик расширен пунктами, закрепившимися
в 76–94 (аудит методологии, leakage-контракт, preview→apply,
468px-стандарт, append-only история).

Чисто документационная задача, кода не затрагивает.

---

## Task 127 — Random Forest: production vertical slice (recursive supervised ML)

Дата: 2026-09-08. База: `main @ bb41796` (spec_forecasting2.md v3; включает
принятые коммиты Task 126 `b8907a8` + сертификации `8ee9579`/`4e8cac8`).
TDD: RED (14 failed) зафиксирован до реализации, доведён до GREEN; полный
прогон 1520 passed (базлайн bb41796: 1472 + 48 новых). Commit/push не выполнялся.

### Постановка и дизайн

Task 127 (`docs/modeling_task_list.md`): отдельный vertical slice — Random
Forest: bounded param_space, exact OOF, feature importance, residual
diagnostics, reproducible seed, capability/UI и Model Card; никаких
штрафных/Naive-fallback путей; нативный production API (scikit-learn).

RF — второй supervised-адаптер платформы (после Prophet), первый
`dependency_group="ml"`, первый ПОТРЕБИТЕЛЬ recursive-контракта Task 126
(`RecursiveFeatureState` до сих пор был контрактом без runtime-потребителей).

Ключевые архитектурные решения:

1. **Recursive-стратегия через RecursiveFeatureState (peek/push).** При
   проектировании обнаружено, что последовательный прогнозный цикл через
   сертифицированный `next_row(prediction)` принципиально не построить без
   загрязнения history: call строит строку ДО push, поэтому передаваемый
   прогноз всегда отстаёт на один шаг (доказательство в записи; State-тесты
   Task 126 это не ловили, т.к. использовали next_row как проверку контракта,
   а не как генератор). Добавлены АДДИТИВНЫЕ `peek_row()` (строка без мутации)
   и `push(value)`; `next_row` отрефакторен как `peek_row()+push()` —
   поведение бит-в-бит, все сертифицированные тесты Task 126 зелёные без правок.
   Корректный порядок потребителя: `row = peek_row()` → `model.predict(row)` →
   `push(prediction)`. Train-матрица и рекурсивный прогноз строятся ОДНИМ
   кодом (peek/push) — train/serve skew рекурсивного прогнозирования устранён
   по построению.
2. **Каузальные признаки адаптера**: лаги 1..n_lags, rolling mean/std (окно
   n_lags, ddof=0 — та же семантика, что у FoldFeatureMatrixBuilder), diff_1;
   имена префиксованы `rf_` (нет столкновений с каталогом генерации). Warm-up
   = max lookback, известные колонки обрезаются на тот же warm-up (выравненность).
3. **Regressor-канал granted (Task 126/124)**: future_known/static колонки
   fold-local FeaturePlan проходят в RF симметрично train/future; fail-closed
   валидация (симметрия множеств, длины, NaN/Inf) — тот же стандарт, что у
   Prophet. Historic-экзогены платформа не передаёт никогда.
4. **Feature importance ↔ точная fold-матрица**: sklearn impurity importances;
   адаптер считает matrix_hash СВОЕЙ X-матрицы (canonical JSON + sha256 — та же
   схема, что у builder) и возвращает lineage в metadata; `run_backtest_plan`
   связывает через `bind_feature_importance` в `fold["feature_importance"]`
   (+`fold`, +`plan_id` при активном плане). Oracle-защита сохранена: чужие
   колонки отклоняются → ошибка fold'а; самопроверка binding'а в адаптере
   (fail-closed до записи в артефакт). Без плана importance по-прежнему
   привязан к матрице адаптера (plan_id=None) — важность не существует вне
   привязки к своей матрице.
5. **Prediction intervals**: пер-квантили предсказаний отдельных деревьев
   (p10/p90, fixed 80% — bounded scope, как interval_width у Prophet);
   границы расширяются до point-прогноза (инвариант реестра
   lower ≤ point ≤ upper при любом распределении).
6. **Fail-closed без fallback**: bounded params (n_estimators 10..1000,
   max_depth None|1..64, min_samples_leaf 1..100, n_lags 1..32; неизвестные
   ключи игнорируются — соглашение платформы), минимум 8 usable-строк
   supervised-матрицы, NaN/Inf target/регрессоров — ошибка fold'а. Legacy
   demo-обёртка `run_random_forest_backtest` — сознательно БЕЗ safe_backtest.

### Состав (11 файлов + 2 новых тест-файла)

- `apps/api/model_impls/random_forest.py` (NEW): `rf_feature_specs`,
  `validate_rf_params`, `supervised_matrix`, `_rf_fit_predict` (fit +
  рекурсивный прогноз + интервалы + importance lineage), `run_random_forest_backtest`.
- `apps/api/feature_plan.py`: `RecursiveFeatureState.peek_row()/push()` (аддитивно).
- `apps/api/model_execution.py`: `_random_forest_executor`; реестр —
  `random_forest` (family=tree_ml, supervised, supports_future_features,
  supports_prediction_intervals, deterministic, ml, scikit-learn, memory=standard);
  фикс `_probe_dependency`: alias import-имени `scikit-learn`→`sklearn`
  (иначе find_spec("scikit_learn")=None и адаптер ошибочно считался
  недоступным — distribution name ≠ module name).
- `apps/api/backtesting.py`: binding feature_importance в fold-запись.
- `apps/api/schemas.py`: `BacktestFoldResult.feature_importance: Optional[Dict]`.
- `apps/api/routers/models.py` + `apps/api/model_impls/__init__.py`:
  `random_forest` в legacy dispatch (guard консистентности реестра).
- `rules/modeling.yaml`: bounded param_space random_forest
  (n_estimators [100,300] × max_depth [6,12] × min_samples_leaf [1,5] ×
  n_lags [3,7] = 16 trials ≤ MAX_TRIALS=64).
- `apps/api/Dockerfile`: executable-проба RF в release-образе.
- Тесты: NEW `tests/unit/test_random_forest_adapter.py` (27: каузальность
  матрицы построчно, warm-up, выравненность known-колонок, детерминизм
  peek/push + эквивалентность next_row, период-2 закрытая форма [1,2,1]
  с точностью 1e-12 — детерминированно ловит stale-history/off-by-one
  рекурсии, границы экстраполяции RF, A/B-дивергенция регрессорного канала,
  интервалы lower ≤ point ≤ upper, importance↔матрица + oracle-отрицательный
  контроль, 10 fail-closed параметрических тестов), NEW
  `tests/unit/test_random_forest_backtest.py` (12: дескриптор реестра,
  готовность production actions, отрицательный контроль capability-гейта,
  E2E run_backtest_plan granted без exclusion-warning, importance в каждой
  fold-записи c plan_id, детерминизм OOF, реальные метрики, работа без
  плана, bounded param_space из YAML ≤ 64, execute_tuning_plan на тех же
  folds). UPDATED сертификационные: test_model_execution_contract (12
  CERTIFIED_IDS, SUPERVISED_IDS={prophet, random_forest},
  dependency_group=ml), test_modeling_mvp_certification (twelve-model gate,
  tuning-множество, RF-проба в Dockerfile), test_model_readiness_candidates
  (runnable 12/catalog_only 12, RF blocked на n=60 — explain, не fake),
  test_backtesting_engine (12 моделей общий OOF cohort), test_models_backtest_real
  (12 реализаций dispatch).

### Тесты и верификация

- RED: 14 failed до реализации (ModuleNotFoundError + сертификационные).
- GREEN: `python -m pytest tests/` — **1520 passed / 0 failed**
  (базлайн 1472 + 48 новых; счётчик сходится ровно). Snapshots 3/3.
- `python -m compileall apps` OK; `from apps.api.main import app` OK;
  `pip check` PASS; Dockerfile RF-проба исполнена локально (OK).
- Методологическое примечание: closed-form тесты рекурсии через
  геометрическое затухание намеренно заменены периодом-2: деревья
  piecewise-constant и не экстраполируют за диапазон train-таргетов
  (это свойство зафиксировано отдельным boundary-тестом и описанием
  семейства tree_ml в modeling.yaml — «не экстраполируют тренд»).
- Model Card/capability/UI: карта строится генерически из артефактов
  бэктеста — folds с feature_importance попадают в `training.folds`
  автоматически; каталог (candidates) поднимает random_forest в
  platform_status="ready" из реестра, фронтенд-изменений не требуется
  (family «Деревья и бустинг» уже был в packages/ui/lib/modeling.ts).
  Residual diagnostics — модель-агностная стадия на OOF-остатках,
  подключается автоматически (actions включают diagnostics).
- Окружение: зависимости восстановлены в активный venv (prophet==1.4.0,
  statsforecast==2.1.1, pandera, syrupy, fakeredis, arch, ruptures и др.).
- Фронтенд не затронут; Jest/typecheck не требовались.

### Вердикт

**Task 127 реализована как полный vertical slice**: 12/24 production-моделей
(4 baseline + 8 моделей). Recursive-контракт Task 126 получил первого
runtime-потребителя; regressor-канал future_known/static работает для
второго supervised-адаптера; importance привязан к точной fold-матрице
(oracle-защита воспроизведена и расширена на адаптерную матрицу); tuning —
на тех же EDA folds с bounded grid 16 trials; интервалы — по деревьям без
утечки; воспроизводимость — random_state через ModelExecutionRequest.
Задел для Tasks 128–130 (XGBoost/LightGBM/CatBoost): peek/push-паттерн
потребления RecursiveFeatureState и адаптерный importance-lineage
переиспользуются как есть.

---

## Task 127 — Сертификация Random Forest (аудит на 258f4d9)

Дата: 2026-09-08. Синхронизация: `main @ 258f4d9` (Task 127 коммит `0310e13`).
Аудитор: независимая сертификационная проверка реализации коллеги.

### Методика аудита

1. Изучены требования `docs/modeling_task_list.md` (Task 127 = vertical slice
   серии ML: bounded param_space, exact OOF, feature importance, residual
   diagnostics, reproducible seed, capability/UI, Model Card; запрет
   Naive-fallback/штрафных результатов; нативный production API).
2. Постатрочный ревью кода: `apps/api/model_impls/random_forest.py` (401
   строка), диффы `feature_plan.py` / `model_execution.py` / `backtesting.py`
   / `schemas.py` / `routers/models.py` / `model_impls/__init__.py` /
   `rules/modeling.yaml` / `Dockerfile`.
3. Ревью тестов: `tests/unit/test_random_forest_adapter.py` (38 кейса),
   `tests/unit/test_random_forest_backtest.py` (10 кейсов) + обновления пяти
   сертификационных тест-файлов.
4. Независимое воспроизведение в чистом окружении (восстановлены зависимости:
   prophet, statsforecast, pandera, syrupy, arch, ruptures, hypothesis,
   PyWavelets).

### Результаты проверки требований (все подтверждены кодом и прогоном)

1. **Bounded param_space**: `PARAM_BOUNDS` в коде — fail-closed и ВНЕ тюнинга
   (n_estimators 10..1000, max_depth None|1..64, min_samples_leaf 1..100,
   n_lags 1..32; bool отсекается). YAML param_space 2×2×2×2 = 16 trials
   ≤ MAX_TRIALS=64. Подтверждено 10 параметрическими fail-closed тестами и
   тестом сетки YAML.
2. **Exact OOF**: единый движок `run_backtest_plan`, общий cohort_id с
   остальными 11 моделями (тест двенадцатимодельного cohort'а), реальные
   метрики (positive MAE/RMSE; weighted_score=None — только comparison),
   детерминизм повторного прогона (OOF и метрики идентичны).
3. **Feature importance**: sklearn impurity importances; lineage
   (`matrix_hash` = canonical JSON + sha256 X-матрицы, adapter_id, колонки,
   warmup, n_rows); `bind_feature_importance` в движке → `fold["feature_importance"]`
   (+fold, +plan_id). Oracle-защита: чужие колонки отклоняются (негативный
   контроль в тесте). Без плана — importance с plan_id=None (важность не
   существует вне привязки к своей матрице).
4. **Residual diagnostics**: модель-агностная стадия на OOF-остатках,
   actions={backtest, tune, diagnostics} — подтверждено дескриптором.
5. **Reproducible seed**: random_state через ModelExecutionRequest; n_jobs=1
   (детерминизм float-суммирования); тесты: идентичность forecast/lower/upper/
   matrix_hash при равном seed, расхождение при смене seed.
6. **Capability/UI**: реестр — family=tree_ml, input_kind=supervised,
   dependency_group="ml", deterministic; candidates → platform_status="ready";
   на коротком профиле (n=60) честный блок "60 < 100" из каталога YAML
   (min_observations=100 — explain, не fake); UI-family «Деревья и бустинг»
   подтверждена в packages/ui/lib/modeling.ts:210 — фронтенд правок не требует.
7. **Model Card**: folds с feature_importance попадают в training.folds
   генерически (schema BacktestFoldResult.feature_importance добавлена
   опциональной — обратная совместимость контракта API).
8. **Запрет Naive-fallback**: legacy-обёртка `run_random_forest_backtest`
   сознательно БЕЗ safe_backtest (в отличие от prophet/tbats legacy-путей) —
   ошибки модели поднимаются как есть; нулевые метрики только на вырожденном
   пустом вводе (общая конвенция _common.py, не подмена ошибки модели).
   Production-контур: fail-closed NaN/Inf/длины/симметрия регрессоров,
   MIN_USABLE_ROWS=8 — всё в ошибку fold'а.
9. **Recursive-стратегия (потребление Task 126)**: `peek_row()/push()` —
   аддитивный рефакторинг; `next_row = peek_row()+push()` бит-в-бит
   (проверено постатрочно по диффу); все сертифицированные тесты Task 126
   зелёные БЕЗ правок (доказано полным прогоном). Аргумент о принципиальной
   неприменимости next_row для последовательного генератора прогнозов
   корректен: строка строится ДО push, аргумент всегда отставал бы на шаг.
   Train-матрица и прогноз строятся одним peek/push-кодом — train/serve skew
   устранён по построению. Каузальность supervised-матрицы подтверждена
   построчным тестом (target в позиции p, признаки строго из y<p).
10. **Regressor-канал**: future_known/static из fold-local FeaturePlan
    симметрично train/future, fail-closed (симметрия множеств, длины,
    NaN/Inf); A/B-дивергенция доказывает достижимость канала моделью;
    E2E granted-режим без exclusion-warning; негативный контроль гейта
    (univariate-модели по-прежнему отклоняют features) — контракт Task 126
    не ослаблен.
11. **Дополнительные находки аудита**: фикс `_probe_dependency` (alias
    `scikit-learn`→`sklearn`, distribution name ≠ module name) — реальный
    баг, без него адаптер ошибочно считался недоступным; guard
    консистентности legacy-dispatch с реестром сохранён; Dockerfile-проба RF
    воспроизведена локально (OK); счётчики readiness обновлены честно
    (12 runnable / 12 catalog_only / blocked=2 на коротком профиле).
12. **Числа сходятся**: 48 новых кейса (адаптер 38 + backtest 10), полный
    прогон **1520 passed / 0 failed** (базлайн bb41796 1472 + 48 — арифметика
    сходится ровно; заявленные в записи коллеги «27»/«12» — счёт функций по
    секциям, на арифметику не влияет). compileall OK; `from apps.api.main
    import app` OK; snapshots 3/3.

### Замечания аудита (некритичные, блокировок нет)

- Описательные счётчики в записи коллеги («27:», «12:») не совпадают с
  pytest-счётом кейсов (38/10) — при этом сводная арифметика 1472+48=1520
  точна; рекомендуется в последующих задачах указывать pytest-счёт.
- В `backtesting.py` `fold_feature_importance` инициализируется дважды
  (до try и в supervised-ветке) — избыточно, но семантически корректно.
- `tests/unit/test_model_readiness_candidates.py` содержит избыточную
  двойную инициализацию той же переменной в тесте блокировок (не влияет).

### Вердикт сертификации

**Task 127 СЕРТИФИЦИРОВАНА. Реализация отличная.**

Все восемь требований постановки выполнены end-to-end без упрощений:
Random Forest — полный production vertical slice (12/24), первый
dependency_group="ml" и первый runtime-потребитель recursive-контракта
Task 126 с устранением train/serve skew по построению; bounded tuning,
exact OOF, importance-lineage с oracle-защитой, интервалы по деревьям,
детерминизм, честные capability-гейты. Коммит/пуш не выполнялся (запрет
AGENTS.md соблюдён). База для Tasks 128–130 (XGBoost/LightGBM/CatBoost):
peek/push-паттерн и адаптерный importance-lineage переиспользуются как есть.

---

## Task 128 — XGBoost: production vertical slice (recursive supervised ML, quantile-regression интервалы)

Дата: 2026-09-08. База: `main @ 944426c` (Task 127 `0310e13` + сертификация
`944426c` -- «СЕРТИФИЦИРОВАНА. Реализация отличная», без обязательных
доработок). TDD: RED (17 failed + collection error) зафиксирован до
реализации, доведён до GREEN; полный прогон 1570 passed (базлайн 944426c:
1520 + 50 новых). Commit/push не выполнялся.

### Постановка и дизайн

Task 128 (`docs/modeling_task_list.md`): отдельный vertical slice -- XGBoost:
bounded param_space, exact OOF, feature importance, residual diagnostics,
reproducible seed, capability/UI и Model Card; никаких штрафных/Naive-fallback
путей; нативный production API (xgboost==2.1.3, зафиксирован в requirements).

Ключевые архитектурные решения:

1. **Общее рекурсивное ядро `_supervised_recursion.py` (NEW).** Задел
   Task 127 («peek/push-паттерн и адаптерный importance-lineage
   переиспользуются как есть») реализован ДРY-экстракцией: каузальные спеки
   (`supervised_feature_specs(prefix, n_lags)`), supervised-матрица через
   RecursiveFeatureState peek/push, fail-closed regressor-канал
   (`validated_known_features`), matrix_digest (canonical JSON + sha256) и
   widen_intervals вынесены из random_forest.py в общий модуль.
   random_forest.py отрефакторен на делегирование с ПОЛНЫМ сохранением
   публичного API (rf_feature_specs/supervised_matrix/PARAM_BOUNDS/...)
   и сообщений об ошибках (часть контракта тестов) -- все 39 тестов
   Task 127 зелёные без единой правки. Задел для Tasks 129-130.
2. **Интервалы -- quantile regression**, ровно как декларировано в
   modeling.yaml («через quantile regression»): три бустера на одной
   supervised-матрице -- point (reg:squarederror) и две квантильные
   (reg:quantileerror, alpha=0.1/0.9, fixed 80% -- bounded scope, как
   interval_width у Prophet).  Рекурсию ведёт point-модель (её прогнозы
   питают историю через peek/push), квантильные предсказывают на ТЕХ ЖЕ
   future-строках; границы расширяются до point-прогноза (инвариант
   реестра lower <= point <= upper).
3. **Детерминизм и seed-проводка**: n_jobs=1, tree_method="hist",
   random_state через ModelExecutionRequest.  Наивное ожидание «другой seed
   -- другой прогноз» для бустинга неверно: при полном сэмплировании
   (colsample_bytree=1.0, subsample=1.0) xgboost детерминирован независимо
   от seed -- это зафиксировано ОТДЕЛЬНЫМ тестом отсутствия скрытой
   стохастичности (3 seed'а -- побайтово одинаковый прогноз), а seed-проводка
   до бустера доказана обратным тестом с colsample_bytree=0.6 (разные seed --
   разные прогнозы).
4. **Importance**: gain-нормализация бустинга (importance_type="gain"),
   привязка к ТОЧНОЙ матрице адаптера через bind_feature_importance
   (matrix_hash в lineage, самопроверка в адаптере, oracle-отрицательный
   контроль в тестах).  Нюанс float32: xgboost нормализует importances во
   float32 (сумма 1.0 ± 1e-7) -- допуск тестов 1e-6, документировано
   (sklearn-RF даёт float64-точность 1e-9).

### Состав (13 файлов + 2 новых тест-файла)

- `apps/api/model_impls/_supervised_recursion.py` (NEW): общее рекурсивное
  ядро семейства tree_ml (см. выше; N_LAGS_BOUNDS=(1,32),
  MIN_USABLE_ROWS=8 -- общий контракт).
- `apps/api/model_impls/xgboost.py` (NEW): `validate_xgb_params`
  (bounded: n_estimators 10..1000, max_depth 1..20, learning_rate
  0.001..1.0, min_child_weight 1..100, reg_lambda 0..1000,
  colsample_bytree 0.1..1.0, n_lags 1..32; неизвестные ключи игнорируются),
  `xgb_feature_specs` (префикс xgb_), `_make_booster` (единая детерминированная
  конфигурация), `_xgb_fit_predict` (point+2 квантили, рекурсия peek/push,
  widen, importance-lineage + самопроверка), `run_xgboost_backtest`
  (legacy demo, сознательно БЕЗ safe_backtest/Naive-fallback).
- `apps/api/model_impls/random_forest.py`: рефакторинг на общее ядро
  (делегирование, публичный API и сообщения сохранены).
- `apps/api/model_execution.py`: `_xgboost_executor`; реестр --
  `xgboost` (family=tree_ml, supervised, supports_future_features,
  supports_prediction_intervals, deterministic, ml, engine=xgboost,
  required_packages=("xgboost",), memory=standard).
- `rules/modeling.yaml`: bounded param_space xgboost (n_estimators
  [100,300] × max_depth [3,6] × learning_rate [0.05,0.2] × n_lags [3,7]
  = 16 trials ≤ 64).
- `apps/api/requirements.txt`: `xgboost==2.1.3` (pinned, по образцу
  prophet/statsforecast).
- `apps/api/Dockerfile`: executable-проба XGBoost в release-образе.
- `apps/api/model_impls/__init__.py` + `apps/api/routers/models.py`:
  xgboost в legacy dispatch (guard консистентности реестра).
- Тесты: NEW `tests/unit/test_xgboost_adapter.py` (29: specs/префикс,
  общее ядро (каузальность/warm-up/выравненность/минимум истории),
  bounded params (17 параметрических fail-closed), детерминизм + отсутствие
  скрытой стохастичности + seed-проводка при colsample<1, интервалы
  lower <= point <= upper с нетривиальной шириной, период-2 закрытая форма
  [1,2,1] 1e-9 (learning_rate=1.0 + reg_lambda=0 -- первый бустинг-раунд
  достигает нулевых остатков), границы диапазона train, A/B-дивергенция
  канала, importance-lineage + oracle-отрицательный контроль, NaN-target/
  канал/horizon fail-closed), NEW `tests/unit/test_xgboost_backtest.py`
  (11: дескриптор реестра, production actions, E2E granted без
  exclusion-warning, importance в каждой fold-записи c plan_id,
  детерминизм OOF, реальные метрики, работа без плана (importance
  plan_id=None), bounded param_space из YAML, execute_tuning_plan на тех
  же folds). UPDATED сертификационные гейты: test_model_execution_contract
  (13 CERTIFIED_IDS, SUPERVISED_IDS={prophet, random_forest, xgboost},
  ML_IDS={random_forest, xgboost}, xgboost-дескриптор в candidates),
  test_modeling_mvp_certification (thirteen-model gate, tuning-множество,
  XGB-проба в Dockerfile), test_model_readiness_candidates (runnable
  13/catalog_only 11; blocked n=60 -- tbats+rf+xgboost=3, explain),
  test_backtesting_engine (13 моделей общий OOF cohort + importance
  обоих ML), test_models_backtest_real (13 реализаций dispatch),
  tests/unit/test_eda_model_matrix (catboost как conditional catalog_only
  пример вместо ставшего production xgboost), tests/api/test_modeling_workflow
  (lstm как catalog-only пример в reject-тесте).

### Тесты и верификация

- RED: 17 failed + 1 collection error до реализации.
- GREEN: `python -m pytest tests/` -- **1570 passed / 0 failed**
  (базлайн 1520 + 50 новых; счётчик сходится ровно). Snapshots 3/3.
- `python -m compileall apps` OK; `from apps.api.main import app` OK;
  `pip check` PASS; Dockerfile XGB-проба исполнена локально (OK).
- Три каталог-теста, использовавшие xgboost как catalog-only пример,
  переведены на catboost/lstm с комментариями (дальнейшие сдвиги --
  при Tasks 129/130).
- Model Card/capability/UI: карта генерическая (folds с importance
  попадают в training.folds автоматически); каталог поднимает xgboost в
  ready из реестра (уровень P06 RECOMMENDED при n>=200+экзогены);
  residual diagnostics -- модель-агностная стадия на OOF-остатках.
- Фронтенд не затронут; Jest/typecheck не требовались. commit/push не
  выполнялся.

### Вердикт

**Task 128 реализована как полный vertical slice**: 13/24 production-моделей
(4 baseline + 9 моделей). Общее рекурсивное ядро tree_ml выделено и
сертифицированный паттерн Task 127 переиспользован без копипасты;
quantile-regression интервалы закрывают декларацию modeling.yaml; tuning
на тех же EDA folds с bounded grid 16 trials; seed-проводка доказана
двусторонне. Задел для Tasks 129-130 (LightGBM/CatBoost): ядро
_supervised_recursion переиспользуется как есть, ожидаемые точки изменения
сведены к адаптеру+реестру+yaml+dispatch.
