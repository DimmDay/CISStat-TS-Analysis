# PANEL-MODELS-3 — Панельный контур моделирования: panel.py, FE/RE, Panel VAR и настоящий entity-pivot глобальных нейромоделей

Дата: 2026-10-20. База: `main@5f12c7f` (UPLOAD-SEM-1); смежная задача `docs/upload_recompose_2026-10-20.md` (UPLOAD-RECOMP-2) — источники панельных данных и бейдж «Ряд не трансформируем». Постановка тимлида (2026-10-20, чат): большая задача — реализация `app/preprocessing/panel.py` / `app/modeling/panel_models.py` (Fixed Effects / Random Effects / Panel VAR) и настоящий entity-pivot для глобальных нейромоделей, по архитектурному плану.

---

## 1. Постановка и границы

**Обещание маршрутизации должно получить исполнителей.** Справочник классов (`app/core/dataset_classifier.py:46–47`) маршрутизирует панель на `["Fixed Effects", "Random Effects", "Panel VAR", "GMM"]`, чек-лист архитектуры (`ARCHITECTURE.md:1660–1661`) требует `app/preprocessing/panel.py` и `app/modeling/panel_models.py`, §«Обработка структуры панели» (1017–1031) и §«Панельные признаки» (1086–1090) фиксируют требования — НИ ОДИН из этих артефактов не существует: каталог моделей (`rules/modeling.yaml`, 8 семейств) не содержит панельного семейства, единственная `input_kind="panel"`-модель (DeepAR, Task 142) интерпретирует панель как «target + прочие числовые КОЛОНКИ одного датафрейма» (`modeling_session.py::_panel_neural_context` → `honest_system_profile`), т.е. колонку-параллельную систему, а не сущность × время. Аналитик с панельным датасетом не имеет ни одной панели-нативной модели, а после UPLOAD-RECOMP-2 получит честный бейдж «Ряд не трансформируем, исследуем панельные данные» — эта задача наполняет бейдж содержанием.

**Решение — отдельный панельный контур моделирования.** Сессионный контур моделирования построен вокруг паспорта ОДНОГО ряда (`modeling_entry` → `prepare_passport_series`, отказ на повторяющихся датах — `app/core/passport.py:144–147`). Панель НЕ продавливается через однорядный паспорт (нарушение честности): вводится собственный checkpoint `panel_entry` (честный паспорт ПАНЕЛИ) и собственные исполнители в реестре — по прецеденту изолированных движков Task 134/135/142 (vector/volatility/panel-колоночный).

**Границы задачи:**
- добавляются: `app/preprocessing/panel.py`, `app/modeling/panel_models.py`, семейство `panel` в `rules/modeling.yaml`, `input_kind="panel_entity"` в реестре исполнения, entity-pivot контур DeepAR, панельные экраны «Моделирования» и «Прогноза»;
- НЕ меняются: однорядный контур (паспорт, passport-серия, существующие движки main/vector/volatility/panel-колоночный Task 142 и его контракты), семейства 1–8 каталога, EDA/Валидация/Предобработка (панельно-осведомлённые проверки уже поставлены), протокол нейро-контрактов (`neural_contract.py` расширяется, не переписывается);
- GMM (Arellano–Bond) для динамических панелей — ВНЕ задачи (отдельная постановка PANEL-GMM-4 после приёмки 3a–3c);
- без commit/push (AGENTS.md). Этапы 3a/3b/3c — отдельные коммиты-поставки с собственными TDD-циклами.

## 2. Проверенное состояние (по коду 5f12c7f)

- **Каталог/реестр:** `rules/modeling.yaml` — 8 семейств, applicability-движок F-гейтов (минимальные наблюдения, soft-гейты), Model Card обязателен; `MODEL_EXECUTION_REGISTRY` (`apps/api/model_execution.py:201+`) — immutable capability-контракты с `input_kind ∈ {univariate, supervised, multivariate, panel}` (строка 26), гейты requires_train_features/related_series (237–266).
- **Колонко-параллельный «panel» Task 142:** `run_panel_backtest_plan` (`apps/api/backtesting.py:1343–1477`) исполняет ТОЛЬКО column-parallel системы (target + related колонки, gate `len(names) < 2`, min_series=5 — `DEEPAR_MIN_SERIES`, `deepar.py:169`); `_panel_frame` (`deepar.py:297–320`) назначает `unique_id="series_{position}"` КОЛОНКАМ; docstring честно фиксирует: «панель = target + связанные числовые ряды датасета».
- **Готовность к entity-pivot:** сертифицированный конвертер `to_long_format` (`apps/api/neural_contract.py:170–182`) УЖЕ принимает `series_column` и fail-closed валидирует дубликаты `(unique_id, ds)` — т.е. per-entity уникальность сетки; `PANEL_MIN_SERIES=2` (neural_contract.py:90), cohort-контракт `neural_cohort_contract` (819–865) вычисляет derived_kind по `n_series`.
- **Панельная фактура данных:** классификация panel_balanced/unbalanced (`dataset_classifier.py:186–195`), balance-факт `GET /dataset/panel-balance` (`session.py:1182–1210`), по-сущностная достаточность (`validation/sufficiency.py:214–252`: пороги trend≥10/ARIMA≥50/ML≥100 наблюдений на сущность), регулярность по группам (`app/validation/regularity.py:41–64`), уникальность по (сущность+дата) (`validation/engine.py:1489–1494`).
- **Гейты однорядного контура, которые панель НЕ проходит:** паспорт (дубликаты дат), checkpoint `modeling_entry` (`modeling_workflow.py:269–275`), серия `prepare_passport_series`.
- **Среда:** `statsmodels>=0.15.0` (requirements.txt:57) — VAR, OLS, кластерные SE доступны; `linearmodels` НЕ установлен (решение §3.2 — без новых зависимостей); ограничение render.com free tier 512MB (прецедент FC-MON-2).

## 3. Проект

### 3a. `app/preprocessing/panel.py` — панельный контракт и паспорт панели (этап 1)

- **`build_panel_frame(df, *, date_column, entity_column, value_columns, target_column) -> PanelFrame`** — fail-closed контракт панели: колонки существуют и различны; каждая сущность строго регулярна внутри себя (переиспользование `validation.regularity`); НЕТ дубликатов (entity, date) (уникальность); NaN-профиль по сущностям; вычисляет и возвращает честную фактуру: `n_entities, n_dates_common (пересечение сеток), balance ∈ {balanced, unbalanced}, t_per_entity: {min, median, max}, n_valid по (entity, date, target)`. Immutable dataclass; исходный df не мутирует.
- **По-сущностные преобразования по §1086–1090 архитектуры:** `within_transform` (отклонение от среднего сущности — df.groupby(entity).transform), `between_transform` (средние сущностей), `entity_dummies`, ЖЁСТКОЕ ПРАВИЛО лагов/скользящих — строго `groupby(entity)`: вспомогательный `panel_lag(df, column, lags)`; дата-утечка между сущностями запрещена (гвард-тест §5a-4; архитектурная норма 1561 «плоские сдвиги блокируются»).
- **`build_panel_passport(df, ...) -> PanelPassport`** — честный паспорт панели для checkpoint `panel_entry`: фактура build_panel_frame + по-сущностный профиль достаточности (переиспользование `profile_sufficiency` из `validation/sufficiency.py`) + вычислимость каждой панельной модели (гейты §3b) + advisory cross-sectional dependence (Pesaran CD по пересечению сеток, statsmodels-совместимая реализация, результат advisory — не блокирует, как cointegration-evidence Task 132).
- **Checkpoint `panel_entry`** — зеркал `modeling_entry`: подтверждается аналитиком на вкладке «Моделирование» (pre-flight панельного контура), фиксирует PanelPassport + fingerprint панели; истекает при изменении данных (сравнение fingerprint). Однорядный `modeling_entry` и его паспорт не затрагиваются.

### 3b. `app/modeling/panel_models.py` — FE / RE / Panel VAR (этап 2)

- **Fixed Effects (within-оценщик):** OLS на within-преобразованных данных с поглощением сущностных интерсептов; эквивалентная реализация — `statsmodels.OLS` с C(entity) dummy-матрицей (обе реализации в тестах совпадают по коэффициентам в допуске — кросс-валидация без внешних библиотек); кластерно-робастные SE по сущностям (statsmodels `cov_type="cluster"`); артефакты: коэффициенты, SE, R² within/between/overall, по-сущностные эффекты.
- **Random Effects (quasi-demeaning GLS):** оценка дисперсионных компонент Swamy–Arora, квази-детрендирование θ·средних, GLS; артефакты те же + оценённые компоненты дисперсии.
- **Тест Хаусмана (FE vs RE):** разность векторов коэффициентов FE/RE со стат-выводом; результат — advisory-факт Model Card («предпочтительная спецификация»), решение за аналитиком (канон «рекомендация ≠ замена решения»).
- **Panel VAR:** pooled VAR(1..2) на СБАЛАНСИРОВАННОМ пересечении сеток (gate; несбалансированная панель — честный отказ с объяснением «Panel VAR требует общей сетки»), с entity-фиксированными эффектами (dummies в матрице регрессоров), по-переменные OOF-метрики; IRF — вне задачи (PANEL-GMM-4/отдельная постановка).
- **Гейты применимости (в modeling.yaml, семейство №9 `panel`):** FE/RE — `n_entities ≥ 5, t_per_entity.min ≥ 10, n_exog ≥ 1` (статическая панель: прогноз ТОЛЬКО сценарный — при будущих путях экзогенных факторов; без экзогенных — honest limitation «динамические панели — GMM-контур, в разработке»); Panel VAR — сбалансированность + `n_entities ≥ 5, T_common ≥ 3·n_vars·(p+1)` эвристика + предупреждение при малых T; производственные капы: предупреждение при `n_entities > 200` (render 512MB), жёсткий отказ при `n_entities > 2000` с честным сообщением.
- **Реестр исполнения:** новые ModelDefinition с `input_kind="panel_entity"` (ЯВНО отличать от колонко-параллельного "panel" Task 142 — обе ветки живут, docstring каждой определяет честную постановку; cohort-изоляция существующим гейтом «Cohort contracts моделей не совпадают»).
- **Движок бэктеста `run_panel_entity_backtest_plan`** (`apps/api/backtesting.py`, зеркало Task 142-движка): folds по строкам панели (FE/RE — OOF по сущностям/датам с кластерной честностью: entity НЕ разрывается между train/test в fold'е — split по датам ВНУТРИ сущностей; Panel VAR — по общей сетке как в Task 142); leakage-safe fold-local префиксы; метрики по-сущностные + pooled (micro-average) через сертифицированную `compute_forecast_metrics`.
- **Прогноз:** FE/RE — сценарный (пути экзогенных факторов от аналитика; горизонт = длина сценария), точечный + SE-интервалы; Panel VAR — рекурсивный h-шаговый прогноз всех переменных сетки.

### 3c. Entity-pivot глобальных нейромоделей — настоящий DeepAR-панель (этап 3)

- **Новый `deepar_panel` в реестре** (`input_kind="panel_entity"`): панель строится как long-format `unique_id/ds/y`, где `unique_id` = ЗНАЧЕНИЕ entity-колонки — через сертифицированный `to_long_format(frame, value_column=target, time_column=date, series_column=entity)` (fail-closed на дубликаты (unique_id, ds) = per-entity регулярность; каждое требование конвертера уже покрыто тестами neural_contract).
- **Гейты:** panel-класс датасета (структурный класс), `n_entities ≥ DEEPAR_MIN_SERIES (5)` (честный перенос правила Task 142 на настоящую панель), per-entity длина ≥ минимума нейро-пятёрки, checkpoint `panel_entry` подтверждён.
- **Фит/прогноз:** ОДИН глобальный фит на всех сущностях (суть DeepAR — кросс-сущностный трансфер); прогноз — ПО-СУЩНОСТНОЙ (извлечение по unique_id, по прецеденту Task 142 «прогноз извлекается по unique_id»); probabilistic-поверхность (quantile-голова) по сущностям.
- **OOF/бэктест:** через `run_panel_entity_backtest_plan`; метрики per-entity + pooled; cohort-контракт: `panel=true, n_series=n_entities, min_series=5`, изоляция от колонко-параллельного cohort'а.
- **UI «Моделирование»/«Прогноз»:** карточки панельного семейства с гейтами; результат — таблица по-сущностных прогнозов (сущность, точка, интервал), сводный график с мульти-сущностным переключателем, экспорт CSV; Model Card с панельной фактурой (n_entities, balance, T, выбранная спецификация FE/RE по Хаусману).

### 3.4 Интеграция с UPLOAD-RECOMP-2 (последовательность поставки)

Бейдж «Ряд не трансформируем, исследуем панельные данные» (UPLOAD-RECOMP-2c) после поставки 3b/3c обновляет пояснение: «панельные модели доступны в Моделировании» — однострочная правка текста бейджа, отдельным мини-коммитом 3d после приёмки 3c; до тех пор текст честно говорит «в разработке».

## 4. Точки изменения

| Файл | Изменение |
|---|---|
| `app/preprocessing/panel.py` (новый) | build_panel_frame, within/between, panel_lag, entity_dummies, build_panel_passport, Pesaran CD (advisory) |
| `app/modeling/panel_models.py` (новый) | FE/RE/Хаусман/Panel VAR, гейты, сценарный и рекурсивный прогноз |
| `app/core/state.py`, `apps/api/session_store.py` | checkpoint `panel_entry` (PanelPassport + fingerprint), хранение решения спецификации |
| `rules/modeling.yaml` | семейство №9 `panel` (fe, re, panel_var, deepar_panel), F-гейты §3b, метрики |
| `apps/api/model_execution.py` | ModelDefinition ×4 `input_kind="panel_entity"`, валидация нового input_kind в requires-гейтах |
| `apps/api/backtesting.py` | `run_panel_entity_backtest_plan` (folds по сущностям/сетке, per-entity + pooled метрики) |
| `apps/api/model_impls/deepar.py` | pivot-режим: build long-format по entity-колонке, по-сущностной прогноз, honest docstring отличия от Task 142 |
| `apps/api/routers/modeling_session.py` | dispatch panel_entity-ветки (контекст панели, panel_entry-гейт), сценарный прогноз FE/RE |
| `apps/api/schemas.py` | контракты: panel passport, панельные кандидаты/результаты, сценарий, по-сущностной прогноз |
| `packages/ui/components/TsAnalysisModeling.tsx`, `TsAnalysisForecasting.tsx` | панельные экраны: checkpoint pre-flight, карточки с гейтами, по-сущностные результаты, экспорт |
| `packages/ui/lib/knowledge/help.ts` | справка панельного контура |
| `tests/unit/test_panel_preprocessing.py`, `tests/unit/test_panel_models.py`, `tests/api/test_panel_contract.py`, `tests/api/test_deepar_panel_pivot.py` (новые) | §5 |
| `docs/panel_models_2026-10-20.md` | этот план-отчёт |
| `worklog/worklog10.md`, `MANIFEST.sha256` | журнал, манифест (на каждый этап) |

## 5. TDD-план (RED до кода, по этапам)

- **5a (3a-этап):** (1) build_panel_frame: fail-closed на дубликаты (entity,date), на не-дату, честная фактура на синтетических сбалансированной/несбалансированной панелях; (2) within-тождество (within+between=общее среднее), panel_lag не течёт между сущностями (гвард: разная лаг-структура по сущностям → разные результаты, плоский df.shift датекторится); (3) PanelPassport: пороги гейтов, advisory CD не блокирует; (4) checkpoint panel_entry: fingerprint-истечение.
- **5b (3b-этап):** (1) DGP-фикстура с известным истинным within-эффектом → FE восстанавливает без смещения (RE — со смещением при корреляции эффектов с регрессорами — демонстрационный тест); (2) FE-внутри ≡ OLS-with-dummies (кросс-реализация, допуск 1e-8); (3) Хаусман: при корректном RE не отвергает, при FE-DGP отвергает; (4) Panel VAR на синтетическом VAR(1) — коэффициенты восстанавливаются, несбалансированная панель — честный отказ; (5) кластерные SE — покрытие; (6) гейты каталога: n_entities<5 → НЕ_RECOMMENDED с reason; (7) движок: entity не разрывается fold'ом, OOF-pooled согласован с по-сущностным средним.
- **5c (3c-этап):** (1) pivot: long-format unique_id = значения сущностей, fail-closed дубликаты; (2) гейт n_entities<5 → BacktestExecutionError с честным текстом; (3) прогноз содержит КАЖДУЮ сущность (не series_i колонок); (4) cohort-изоляция от Task 142-контракта; (5) детерминизм seed; (6) regression-инвариант: колонко-параллельный DeepAR Task 142 не изменён (старые тесты зелёные).
- **Регресс каждого этапа:** полный Jest, адресные pytest (modeling workflow, реестр, нейро-контракты), typecheck:all, сборка.

## 6. Риски и меры

- **R1 — 512MB render free tier:** капы §3b (warn >200 сущностей, отказ >2000), честные ошибки вместо OOM; нейро-контур — существующие нейро-гейты + n_entities-гейт.
- **R2 — путаница двух «панелей»** (колонко-параллельная Task 142 vs сущностная): отдельный `input_kind="panel_entity"`, отдельные ModelDefinition/cohort-контракты, docstring-различие, regression-инвариант 5c-6.
- **R3 — отсутствие linearmodels:** собственные within/GLS реализации с кросс-валидацией против statsmodels-OLS-with-dummies; при расхождении сверх допуска — СТОП и вынос решения о зависимости на тимлида (не тянуть тихо).
- **R4 — подмена однорядного контура:** панельный контур никогда не касается `prepare_passport_series`/`modeling_entry`; отдельный checkpoint; тест-гвард отсутствия вызовов.
- **R5 — утечка между сущностями:** ЖЁСТКОЕ правило groupby(entity) (архитектура 1087–1088), гвард-тест 5a-2, запрет плоских shift'ов.
- **R6 — статическая панель без экзогенных не прогнозирует:** honest limitation в Model Card/справке; динамический путь — PANEL-GMM-4 (зафиксировано, не скрыто).
- **R7 — сбалансированность:** Panel VAR gate только balanced; FE/RE работают на unbalanced (квази-детрендирование по фактическим T сущности) — тест 5b-1 на несбалансированной фикстуре.

## 7. DoD (по этапам, каждый — отдельная поставка)

1. TDD RED→GREEN этапа; регресс полный без падений; typecheck:all; сборка.
2. 3a: панельный контракт + паспорт + checkpoint подтверждены тестами; 3b: FE/RE/Хаусман/Panel VAR в каталоге с гейтами, движок и сценарный прогноз работают; 3c: DeepAR entity-pivot даёт по-сущностной прогноз, колонко-параллельная ветка не тронута.
3. Model Card панельных прогонов несёт честную фактуру (n_entities, balance, T, спецификация, advisory CD/Hausman).
4. Документация: справка UI + семейство в modeling.yaml согласованы; бейдж UPLOAD-RECOMP-2 обновлён (мини-этап 3d).
5. Журнал worklog10.md дополнен по каждому этапу; ZIP только файлов этапа в открытый контейнер; commit/push НЕТ.
