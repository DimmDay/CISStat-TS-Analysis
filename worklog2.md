# CISStat TS Analysis — Worklog

---

## Task ID: 76 — Устранение HTTP 502 в остановке «Структурные сдвиги»

Date: 2026-08-31

### Диагностика
- Локальный API-контракт и сериализация ответа исправны; 502 воспроизведён как превышение вычислительного бюджета прокси на длинном ряду.
- Прежний `jump=max(1, N//1000)` оставлял шаг 1 вплоть до N=1999. PELT запускался для основного результата и повторно для сетки штрафов, поэтому время на N=1000 достигало примерно 20,3 секунды.
- Дополнительно обнаружен численный крайний случай: практически идеально линейный ряд имеет машинные остатки около нуля, из-за чего CUSUM мог выдавать ложную глобальную нестабильность вместо состояния неприменимости.

### Исправление
- Добавлен вычислительный бюджет `MAX_PELT_GRID_POINTS=250`; шаг кандидатов теперь равен `ceil(N/250)`. Все значения ряда участвуют в оценке стоимости сегментов, ограничивается только сетка возможных границ.
- При шаге больше 1 API явно предупреждает о разрешении локализации в наблюдениях, поэтому ускорение не скрывает методологический компромисс.
- Добавлена проверка остаточной дисперсии общей линейной модели относительно машинной точности и масштаба ряда. Практически точная линейная функция честно возвращает `not_applicable`, поскольку CUSUM и Chow не имеют устойчивого знаменателя.

### Результат профилирования
- N=500: около 1,8 с, шаг 2.
- N=1000: около 1,4 с вместо 20,3 с, шаг 4.
- N=3000: около 1,9 с, шаг 12.
- N=5000: около 2,7 с, шаг 20.

### TDD и проверка
- RED: длинный ряд возвращал `jump=1` вместо 4; точно линейный ряд ошибочно считался применимым.
- Core/adapter/API: 10/10 PASS.
- Frontend остановки и общего EDA: 2/2 suites, 29/29 PASS.
- Ранее в текущем цикле: TypeScript embedded/standalone PASS; production build standalone PASS, 13/13 страниц.
- `git diff --check`: PASS.

### Изменённые файлы текущей задачи
- app/eda/structural_breaks.py
- tests/unit/test_structural_breaks_analysis.py

---

## Task ID: 77 — EDA «Отбор признаков»

Дата: 2026-08-31

### Реализация

- Добавлен многокритериальный backend-профиль: Pearson/Spearman относительно Y, корреляционная матрица предикторов, VIF, Granger X → Y по лагам и Benjamini–Hochberg FDR.
- Переиспользована legacy-функция `app.eda.correlation.find_significant_correlations` для высококоррелированных пар.
- Добавлен `GET /v1/session/dataset/eda-feature-selection` и типизированная схема ответа.
- Для Granger контролируются сортировка и регулярность временной оси; при повторных датах/панели и нерегулярности тест блокируется без отключения корреляций и VIF.
- Поддержаны уровни и первые разности. Результат является shortlist `keep/review/low_signal`, а не автоматическим удалением; требуется expanding-window валидация.
- В «Обзоре» реализованы пять представлений: связь с Y, тепловая матрица, VIF, Granger `−log10(q)` и таблица решений.
- В описании приведены официальные ссылки pandas, SciPy и statsmodels.

### Проверки восстановленного пакета

- Python: `6 passed` — аналитика, временной адаптер и API.
- Jest: `1 passed` — переключение пяти представлений обзора.
- `npm run typecheck:all`: успешно для embedded и standalone.
- `git diff --check`: успешно.

### Файлы

- `app/eda/feature_selection.py`
- `apps/api/eda_feature_selection.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/EdaFeatureSelectionOverview.tsx`
- `packages/ui/components/EdaFeatureSelectionOverview.test.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/index.ts`
- `tests/unit/test_feature_selection_analysis.py`
- `tests/unit/test_eda_feature_selection_adapter.py`
- `tests/api/test_dataset_eda_feature_selection.py`

---

## Task ID: 78 — Восстановление исследований EDA после смены датасета

Дата: 2026-08-31

### Диагностика

- Репозиторий синхронизирован с `d5bc8ea34572d5aa510af6d3af6cb158c1ac7e4f`; локальные backend-тесты и живые EDA API подтвердили исправность вычислительных методов.
- Найден общий клиентский дефект: `TsAnalysisEDA` вызывал `useTargetColumn(undefined)`, хотя контракт хука требует ключ активного датасета для повторного получения target после загрузки нового файла.
- В результате EDA сохранял старый признак (например, `Price`) и отправлял его во все target-зависимые исследования нового датасета. Описательные статистики продолжали работать, поскольку target им не нужен.
- Зафиксировано рассогласование развёртываний: живой backend ещё возвращает прежний ответ feature selection без нового поля `applicability_status`. Это не является причиной общей поломки, но Render необходимо развернуть из того же commit, что и Vercel.

### Исправление

- В `ActiveDataset` добавлен `datasetId`, заполняемый как при гидратации сессии, так и после загрузки файла.
- EDA передаёт в `useTargetColumn` стабильный ключ `datasetId` с fallback на имя файла; повторная загрузка одноимённого CSV также вызывает refetch.
- Все запросы исследований и описательной статистики инвалидируются по ключу датасета.
- При смене датасета очищаются профили, ошибки и статусы предыдущего набора данных, чтобы красные/жёлтые индикаторы не переносились в новый анализ.

### TDD и проверка

- RED: при смене `dataset-a → dataset-b` с одинаковым именем файла выполнялся только один GET `/target-column`.
- GREEN: регрессионный тест подтверждает второй GET после смены `datasetId`.
- Jest: `TsAnalysisEDA` — 27/27 PASS; `TsAnalysisUpload` — 25/25 PASS.
- Python EDA API/core/adapter: 26/26 PASS.
- TypeScript: embedded и standalone PASS.
- Production build: standalone и embedded PASS, по 13/13 страниц.

### Изменённые файлы

- `packages/ui/context/AppShellContext.tsx`
- `packages/ui/components/TsAnalysisUpload.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/components/TsAnalysisEDA.test.tsx`

---

## Task ID: 79 — EDA «Стратегия валидации»

Дата: 2026-08-31

### Аудит методологии

- В backend уже существовали `CVStrategy` и `ExpandingWindowCV`, реально используемые в grid-search `/v1/models/tune`. Базовый контракт корректно запрещал shuffle и обеспечивал `train < test`, поэтому он переиспользован.
- Существующей реализации не хватало gap, sliding window, финального holdout, привязки EDA-плана к концу ряда и визуального API-контракта.
- Методология приведена к официальным контрактам [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) и [skforecast Backtesting/TimeSeriesFold](https://skforecast.org/latest/user_guides/backtesting.html): одинаковый горизонт test, возрастающий или фиксированный train, gap перед test и сохранение временного порядка.
- Single split не позиционируется как замена CV: это финальный нетронутый holdout после выбора модели. На нерегулярной оси folds допустимы по порядку наблюдений, но календарная длительность метрик объявляется несопоставимой. Панельные дубли блокируются без скрытой агрегации.

### Реализация

- `ExpandingWindowCV` расширен опциональным `gap=0` без изменения прежнего поведения; добавлен переиспользуемый `SlidingWindowCV`.
- Добавлен read-only endpoint `GET /v1/session/dataset/eda-validation-strategy` со схемами `expanding`, `sliding`, `single`, параметрами horizon/folds/gap/train window и типизированным ответом.
- План всегда привязан к хвосту ряда: последний test заканчивается последним доступным наблюдением. При недостатке истории folds не сокращаются молча — возвращаются точное требуемое N и применимость альтернатив.
- Контролируются временной порядок, повторные даты, нерегулярность и пропуски цели; исходный `session.dataframe` не изменяется.
- В «Обзоре» реализованы четыре представления: карта Train/Gap/Test, график размера train, сравнение стратегий и таблица точных границ. Параметры меняются без второго target-селектора.
- В UI и описании добавлены кликабельные ссылки на официальную документацию scikit-learn и skforecast.

### TDD и проверка

- RED: отсутствовали `SlidingWindowCV`, backend-builder и UI-компонент остановки.
- Backend CV/builder/API: 43/43 PASS.
- Frontend EDA: 9 suites, 54/54 PASS.
- Расширенный backend-набор: 136/139 PASS; три старых ARIMA tuning-теста падают внутри `statsmodels` SARIMAX на коротком train и воспроизводятся без изменений Task 79 на исходной копии.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц.
- `git diff --check`: PASS.

### Изменённые и новые файлы

- `apps/api/cv.py`
- `apps/api/eda_validation_strategy.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/EdaValidationStrategyOverview.tsx`
- `packages/ui/components/EdaValidationStrategyOverview.test.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/components/TsAnalysisEDA.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_cv.py`
- `tests/api/test_dataset_eda_validation_strategy.py`
- `tests/unit/test_validation_strategy_analysis.py`

---

## Task ID: 80 — EDA «Матрица моделей»

Дата: 2026-08-31

### Аудит методологии

- В backend уже существовали единый `rules/modeling.yaml`, `ModelingSpec`, движок применимости и candidates API; во frontend — каталог и пул кандидатов вкладки «Моделирование». Сама остановка EDA оставалась заглушкой без API и визуализации.
- Прежний candidates-движок возвращал только первое сработавшее правило и при отсутствии совпадений назначал `RECOMMENDED`; этого недостаточно для объяснимой матрицы требований. Новая остановка переиспользует тот же каталог 8 семейств / 24 моделей, но показывает все критерии и не трактует совместимость как прогноз точности.
- Исправлена методологическая ошибка F03: наличие экзогенных колонок больше не блокирует ETS/Naive и другие модели, которые могут просто не использовать X. Запрет действует только при явно обязательном использовании X и отсутствии поддержки у модели.
- Статистическая совместимость отделена от готовности платформы: 9 моделей с production backtest помечаются `ready`, остальные — `catalog_only`. Реестр проверяется на точное совпадение с фактическим backend-dispatch.
- TBATS больше не приписывается `statsmodels`; в каталоге указана официальная реализация StatsForecast.
- Методология опирается на официальные источники: [statsmodels TSA](https://www.statsmodels.org/stable/tsa/), [StatsForecast](https://nixtlaverse.nixtla.io/statsforecast/index.html), [scikit-learn lagged features](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html), [arch volatility forecasting](https://arch.readthedocs.io/en/latest/univariate/univariate_volatility_forecasting.html), [Prophet diagnostics](https://facebook.github.io/prophet/docs/diagnostics.html), [NeuralForecast](https://nixtlaverse.nixtla.io/neuralforecast/docs/getting-started/introduction.html).

### Реализация

- Добавлен read-only endpoint `GET /v1/session/dataset/eda-model-matrix` с режимами `forecast`, `multivariate`, `volatility`; он читает текущий target и не обучает модели.
- Параметры expanding/sliding/single, horizon, folds, gap и train-window переиспользуются из «Стратегии валидации». Минимальная история каждой модели проверяется по первому, самому короткому train fold, а не по полному N.
- Для каждой модели формируются десять явных критериев: задача, история, временная ось, сезонность, стационарность/коинтеграция, структура рядов, экзогенные X, lag-features, цель/знак и backend readiness.
- Жёсткое несоответствие даёт `blocked`; действие или неизвестное свойство — `conditional`; только полностью наблюдаемое соответствие — `candidate`. Отдельно возвращаются `shortlist` и `runnable_shortlist`.
- Повторные даты/панель и ошибки временной оси блокируют одномерный запуск без скрытой агрегации. Для VAR не выдаётся проверка одной цели за проверку всей системы; VECM требует отдельной коинтеграции; DeepAR не принимает числовые колонки одного объекта за панель рядов.
- В «Обзоре» реализованы четыре представления: тепловая карта требований, stacked-график семейств, shortlist-карточки и детальная таблица причин. Встроены ссылки на официальную документацию.
- Остановка интегрирована в общий target/dataset lifecycle EDA, очищается при смене датасета, поддерживает ручной пересчёт и показывает шесть сводных метрик.

### TDD и проверка

- RED backend: отсутствовал `apps.api.eda_model_matrix`; RED frontend: отсутствовал `EdaModelMatrixOverview`.
- Расширенный backend EDA + ModelingSpec/candidates: 151/151 PASS.
- Frontend EDA: 11 suites, 61/61 PASS.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц.
- `git diff --check`: PASS.

### Изменённые и новые файлы

- `apps/api/eda_model_matrix.py`
- `apps/api/model_readiness.py`
- `apps/api/routers/models.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/EdaModelMatrixOverview.tsx`
- `packages/ui/components/EdaModelMatrixOverview.test.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/components/TsAnalysisEDA.test.tsx`
- `packages/ui/index.ts`
- `rules/modeling.yaml`
- `src/catalog/modeling_spec_loader.py`
- `tests/api/test_dataset_eda_model_matrix.py`
- `tests/unit/test_eda_model_matrix.py`

---

## Task ID: 81 — Предобработка «Декомпозиция ряда»

Дата: 2026-09-01

### Аудит методологии

- В backend уже существовали `app.preprocessing.decomposition.apply_decomposition` (statsmodels STL / classical additive / multiplicative) и upload-API компонент. Во frontend существовали только виджеты декомпозиции остановки «График» вкладки загрузки; сама остановка «Предобработка → Декомпозиция ряда» оставалась заглушкой.
- Переиспользован официальный [statsmodels STL](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html) с робастными весами. Classical `seasonal_decompose` не выбран основным методом, поскольку сама [документация statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.seasonal_decompose.html) называет его наивной декомпозицией и рекомендует более совершенные методы.
- Исправлена методологическая ошибка нового контура: старые upload-бейджи выделяли «цикличность» как `trend − rolling_mean(trend)` и повторно включали её дисперсию вместе с дисперсией самого trend. STL не возвращает отдельный cycle, а коррелированные дисперсии компонент нельзя честно нормировать до 100%. Остановка использует только `observed = trend + seasonal + resid` и strength-метрики `max(0, 1 − Var(resid) / Var(component + resid))`.
- Остаток проверяется ACF и официальным [statsmodels Ljung–Box](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.acorr_ljungbox.html); Jarque–Bera трактуется только как предупреждение для параметрических интервалов, а не как блокирующее требование к любому прогнозу.
- SEATS/X-13 не заявлены как «встроенные»: statsmodels требует отдельный X-12/X-13 executable (`X13PATH`/`X12PATH`), которого нет в контракте Render. MSTL оставлен следующим расширением для рядов с несколькими сезонностями; текущий детектор платформы возвращает один сезонный период.
- Зафиксировано ограничение утечки: декомпозиция всего исторического ряда пригодна для EDA, но компоненты нельзя напрямую подавать в backtest. В моделировании STL должен переоцениваться только на train-части каждого fold.

### Реализация

- Добавлен `GET /v1/session/dataset/preprocessing/decomposition-profile`: выбранный общий target, автоматический/ручной period, robust STL, компоненты, средний сезонный профиль, ACF остатка, trend/seasonal strength, Ljung–Box и Jarque–Bera.
- Добавлены честные гейты: числовой target, определённая временная колонка, отсутствие пропусков/битых дат, одна точка на дату, регулярная сетка, минимум два полных периода и ненулевая дисперсия. Панель, нерегулярность и недостаточная история дают `applicable=false`, а не синтетический период 12.
- Поддержаны актуальные pandas-aliases `ME/BME/QE` наряду с прежними `M/BM/Q`.
- Добавлен `POST /v1/session/dataset/preprocessing/decomposition-outputs` с контрактом preview → отдельное подтверждение → атомарный apply. Исходный target не перезаписывается; можно добавить `*_trend`, `*_seasonal`, `*_resid`, `*_seasonally_adjusted`, `*_detrended`. Конфликт имён блокируется 422.
- Остановка включена в реальные `auto/enabled/disabled` режимы, статус степпера и общие метрики. `warning` означает оставшуюся структуру/ненормальность остатка, `done` — успешный STL без диагностических предупреждений, `skipped` — отключение или неприменимость.
- В «Обзоре» реализованы четыре представления: компоненты, сезонный профиль, ACF остатка и диагностические карточки. Переключатели оформлены светло-серыми круглыми бейджами по запрошенному паттерну «Матрицы моделей», без активного фиолетового таба.
- Мастер позволяет настроить период/robust и выбрать выходы, показывает preview добавляемых колонок и предупреждает об утечке в backtest.

### TDD и проверка

- RED backend: отсутствовал `apps.api.preprocessing_decomposition`; RED frontend: отсутствовал `PreprocessingDecompositionOverview`.
- Backend core/API и регрессия существующей декомпозиции/регулярности: 71/71 PASS.
- Frontend «Предобработка»: 12 suites, 88/88 PASS.
- Расширенный Python-набор с `test_regularity_correction.py`: 80/81 PASS; старый тест `test_profile_distinguishes_sort_duplicates_and_bad_dates` ожидает `is_sorted=false`, получает `true` и воспроизводится без изменений на чистом Task 80, поэтому не является регрессией Task 81.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц.
- `git diff --check` и `compileall`: PASS.

### Изменённые и новые файлы

- `app/preprocessing/decomposition.py`
- `apps/api/decomposition_data.py`
- `apps/api/preprocessing_decomposition.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/PreprocessingDecompositionOverview.tsx`
- `packages/ui/components/PreprocessingDecompositionOverview.test.tsx`
- `packages/ui/components/PreprocessingDecompositionPipeline.tsx`
- `packages/ui/components/PreprocessingDecompositionPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_decomposition.py`
- `tests/unit/test_preprocessing_decomposition.py`

---

## Task ID: 82 — Предобработка «Стабилизация дисперсии»

Дата: 2026-09-01

### Аудит методологии

- В backend уже существовали `app.preprocessing.transforms.yeo_johnson_manual` и legacy-диагностика `test_heteroskedasticity`; во frontend остановка оставалась статической заглушкой. Legacy Streamlit-контур визуализировал Box–Cox/Yeo–Johnson/log/log1p/sqrt/reciprocal, но не предоставлял session API для standalone/embedded.
- Исправлена критичная ошибка legacy Box–Cox: код добавлял `1e-10`, хотя официальный [`scipy.stats.boxcox`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.boxcox.html) требует строго положительный неконстантный одномерный вход и не выполняет shift. Новый контур не меняет домен скрыто: недопустимый метод блокируется с точной причиной, `shift=0` сохраняется явно.
- Автоматический λ берётся из официальных реализаций: SciPy Box–Cox и [`sklearn.preprocessing.PowerTransformer`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.PowerTransformer.html) для Yeo–Johnson, обе используют maximum likelihood. `standardize=False`, поскольку масштабирование — отдельная остановка платформы. Для обратного Box–Cox используется [`scipy.special.inv_boxcox`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.inv_boxcox.html); Yeo–Johnson обращается по формуле официального `PowerTransformer.inverse_transform`.
- Breusch–Pagan регрессии уровня только на линейное время исключён из основного критерия: он проверяет конкретную зависимость дисперсии регрессионных ошибок от заданных regressors и не является универсальным тестом временной гетероскедастичности. Вместо него используется [`scipy.stats.levene(center="median")`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.levene.html), то есть Brown–Forsythe, по четырём хронологическим блокам, плюс корреляция rolling mean/rolling std.
- [`statsmodels.stats.diagnostic.het_arch`](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.het_arch.html) показан отдельной диагностикой условной волатильности. ARCH-LM не включён в решение «нужна power transform»: при значимом ARCH-эффекте UI честно рекомендует рассмотреть ARCH/GARCH, поскольку монотонная трансформация не обязана устранить кластеризацию волатильности.
- Reciprocal исключён из основной матрицы как агрессивная убывающая трансформация, меняющая направление порядка значений. Поддержаны обратимые монотонно возрастающие Box–Cox, Yeo–Johnson, log, log1p и sqrt со строгими доменными гейтами.
- Зафиксировано ограничение leakage: обзор полного ряда — диагностический. Выбор метода и λ в backtest должны оцениваться только на train и без переоценки применяться к validation/test.

### Реализация

- В core добавлены `apply_variance_transform` и `inverse_variance_transform` с общей валидацией, автоматическим/ручным λ и round-trip для пяти методов. Legacy `yeo_johnson_manual` реально переиспользован для ручного λ.
- Добавлен `GET /v1/session/dataset/preprocessing/variance-profile`: профиль выбранного общего target, временная ось либо честный row-order, diagnostics до/после, пять кандидатов с доступностью и score, точки ряда/rolling σ и две гистограммы.
- Основной статус `warning` означает обнаруженную нестабильность масштаба (`Brown–Forsythe p < 0,05` либо `|corr(mean, std)| ≥ 0,5`), `done` — сильных признаков нет, `skipped` — отключение или честная неприменимость. Пропуски, бесконечности, константный ряд и N < 20 блокируются объяснимо.
- Добавлен `POST /v1/session/dataset/preprocessing/variance-transformations` с паттерном preview → отдельное подтверждение → атомарный apply. Исходный target не перезаписывается; добавляется `*_<method>`, конфликт имени возвращает 422.
- На apply в `AnalysisSession.preprocessing_transformations` сохраняются source/output, method, λ, `standardized=false`, `shift=0`, `fitted_on_n` и поддержка inverse. Поле сериализуется в Redis/Memory, backward-compatible для старых сессий и сбрасывается при новом датасете.
- Остановка подключена к общему target lifecycle, `auto/enabled/disabled`, степперу, статусам, метрикам и ручному пересчёту обеих оболочек.
- В «Обзоре» реализованы пять визуальных представлений: ряд до/после на независимых шкалах, скользящая σ до/после, bar-сравнение методов, распределения до/после и диагностические карточки. Переключатели — светло-серые круглые бейджи по паттерну «Декомпозиции ряда»/«Матрицы моделей».
- Мастер поддерживает выбор метода, auto/manual λ, preview на глубокой копии, подтверждение apply и показывает сохранённые inverse-параметры. В UI встроены ссылки на официальные SciPy/scikit-learn/statsmodels источники.

### TDD и проверка

- RED backend: отсутствовали core-функции и `apps.api.preprocessing_variance`; RED frontend: отсутствовали Overview/Pipeline и API-интеграция остановки.
- Расширенный backend-набор предобработки, декомпозиции, регулярности и session store: 169/169 PASS.
- Frontend «Предобработка»: 14 suites, 95/95 PASS.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц.
- `git diff --check` и `compileall`: PASS.

### Изменённые и новые файлы

- `app/preprocessing/transforms.py`
- `apps/api/preprocessing_variance.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/PreprocessingVarianceOverview.tsx`
- `packages/ui/components/PreprocessingVarianceOverview.test.tsx`
- `packages/ui/components/PreprocessingVariancePipeline.tsx`
- `packages/ui/components/PreprocessingVariancePipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_variance.py`
- `tests/unit/test_variance_stabilization.py`

---

## Task ID: 83 — Предобработка «Сглаживание ряда»

Дата: 2026-09-01

### Аудит методологии

- В legacy backend уже существовал `app.features.rolling`: SMA, EMA, WMA, rolling median и LOWESS; Streamlit-контур дополнительно вызывал HP-filter. В новом standalone/embedded frontend остановка оставалась статической заглушкой без session API.
- Исправлена утечка будущего: legacy SMA/median по умолчанию использовали `center=True`, а WMA заполнял начало через `bfill()` значением будущего полного окна. Новый контур использует trailing SMA/WMA/median, EMA `adjust=False`; WMA считает каждый префикс собственными весами 1…k.
- LOWESS и Savitzky–Golay честно обозначены как двусторонние offline-фильтры. Для preview/apply требуется отдельное подтверждение; metadata содержит `causal=false`, `modeling_safe=false`. Каузальность самого расчёта не отменяет leakage выбора параметров: в backtest method/window/span выбираются только на train.
- Абсолютный legacy roughness заменён на безразмерный `mean((Δ²y)²) / Var(y)`. Legacy-пороги одного `σ(Δy)/σ(y)` не выдаются за тест шума: основной `needs_smoothing` — прозрачная UI-эвристика совместного сигнала normalized roughness ≥ 1 и доли periodogram-мощности при f ≥ 0,25 не меньше 0,35.
- Визуальная гладкость не трактуется как улучшение прогноза. Корреляция, снижение roughness/high-frequency power, сохранённая дисперсия и Ljung–Box остатка описывают компромисс, но итоговое решение требует expanding/sliding-window backtest.
- HP-filter исключён из основной матрицы как trend/cycle decomposition с endpoint bias, дублирующая уже реализованную остановку «Декомпозиция ряда». Заодно исправлено описание legacy-параметров: официальная документация statsmodels приводит 6,25 для annual, 1600 для quarterly и 129600 для monthly, а не прежнюю таблицу платформы.
- Методология опирается на официальные реализации: [pandas rolling](https://pandas.pydata.org/docs/reference/api/pandas.Series.rolling.html), [pandas EWM](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html), [SciPy periodogram](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html), [SciPy Savitzky–Golay](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html), [statsmodels LOWESS](https://www.statsmodels.org/stable/generated/statsmodels.nonparametric.smoothers_lowess.lowess), [statsmodels HP-filter](https://www.statsmodels.org/stable/generated/statsmodels.tsa.filters.hp_filter.hpfilter.html).

### Реализация

- Добавлен чистый core `apply_smoothing_series` для шести методов: `sma`, `ema`, `wma`, `median`, `savgol`, `lowess`, с единым контрактом параметров и признаками causal/modeling-safe/inverse-supported.
- Legacy `app.features.rolling` реально переиспользован и исправлен. WMA больше не подсматривает в будущее; LOWESS использует одну residual-reweighting итерацию после остановки «Выбросы» и официальный `delta` для длинных рядов, сокращая вычислительную нагрузку Render.
- Добавлен `GET /v1/session/dataset/preprocessing/smoothing-profile`: общий target, честная временная сортировка или row-order, проверка пропусков/finite/константы/N≥15, блокировка нескольких значений на одну дату, регулярность/частота, diagnostics до/после, шесть кандидатов, ряд, удалённая компонента, ACF и спектр.
- Добавлен `POST /v1/session/dataset/preprocessing/smoothing-transformations` с preview → подтверждение → атомарный apply. Исходный target не перезаписывается; создаётся `*_<method>`. Конфликт имени возвращает 422.
- Apply сохраняет в `AnalysisSession.preprocessing_transformations` kind/source/output/method/parameters, causal/modeling_safe, `inverse_supported=false` и `fitted_on_n`. Для LOWESS/Savitzky–Golay без `confirm_non_causal=true` возвращается 422 до выполнения дорогого расчёта.
- Остановка подключена к общему target lifecycle, `auto/enabled/disabled`, статусам степпера, прогрессу, четырём сводным метрикам и ручному пересчёту обеих оболочек.
- В «Обзоре» реализованы пять представлений светло-серыми круглыми бейджами: исходный/сглаженный ряд, удалённая компонента + ACF, сравнение методов, спектр до/после и диагностические карточки. Добавлены кликабельные ссылки на официальную документацию.
- Мастер поддерживает параметры window/span/frac/polyorder, отдельно объясняет каузальный и offline-контракты, preview на глубокой копии и подтверждение добавления новой колонки.
- Комментарий ограничения pandas `<3` актуализирован: прежний явный WMA-блокер устранён, но верхняя граница сохраняется до отдельного полного parity-аудита pandas 3.

### TDD и проверка

- RED backend: отсутствовал `app.preprocessing.smoothing`; RED frontend: отсутствовали `PreprocessingSmoothingOverview`/`Pipeline`.
- Добавлены unit/API/Jest-тесты core, профиля, схемы, session persistence, режимов, offline opt-in, пяти представлений Overview и мастера.
- PASS: task Python `py_compile`; `git diff --check`; ручной core smoke каузальности/WMA/Savitzky–Golay; adapter/Pydantic-schema smoke; edge-contract smoke для missing/constant/panel/offline gate.
- Полный pytest/Jest/typecheck/production build в текущей изолированной среде не запускался: свежий clone не содержит pytest/FastAPI/statsmodels/node_modules, а установка из PyPI/npm заблокирована сетевой политикой среды. Тестовые файлы готовы для обязательного прогона в CI/рабочей среде с зависимостями; это ограничение среды, а не отмеченный PASS.
- Общий `compileall` дополнительно упирается в ранее существующий `IndentationError` в `tests/unit/test_file_loader.py:87`; task-файлы компилируются успешно.

### Изменённые и новые файлы

- `app/features/rolling.py`
- `app/preprocessing/smoothing.py`
- `apps/api/preprocessing_smoothing.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/PreprocessingSmoothingOverview.tsx`
- `packages/ui/components/PreprocessingSmoothingOverview.test.tsx`
- `packages/ui/components/PreprocessingSmoothingPipeline.tsx`
- `packages/ui/components/PreprocessingSmoothingPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `requirements.txt`
- `tests/unit/test_rolling.py`
- `tests/unit/test_preprocessing_smoothing.py`
- `tests/api/test_dataset_preprocessing_smoothing.py`

---

## Task ID: 84 — Предобработка «Стационарность ряда»

Дата: 2026-09-01

### Аудит методологии

- В EDA backend уже существовал качественный `analyze_stationarity`: ADF с константой/трендом, KPSS с константой/трендом, Phillips–Perron и Zivot–Andrews. В legacy-предобработке существовали разности и fractional differencing, но standalone/embedded-остановка оставалась заглушкой без session API, визуального обзора и безопасного apply-контракта.
- Исправлена критическая семантическая ошибка legacy-разностей: `Series.diff(d)` вычисляет разность с лагом `d`, а не разность порядка `d`; прежняя «вторая разность» была `y[t] − y[t−2]`, а не `Δ²y[t]`. Новый core использует `np.diff(..., n=2)`, сезонный оператор `y[t] − y[t−s]` и их корректную композицию `(1−B)(1−B^s)`.
- Legacy fractional differencing не перенесён в мастер: знак первого веса для `(1−B)^d` был неверен, а текущая пороговая усечка могла оставлять одно наблюдение. Метод требует отдельного long-memory-контракта, явной схемы truncation и проверенной инверсии; выдавать его сейчас как готовый метод было бы методологически неверно.
- Основной вывод строится на паре тестов с противоположными нулевыми гипотезами: [`statsmodels.adfuller`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html) проверяет H0 единичного корня, [`statsmodels.kpss`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.kpss.html) — H0 стационарности. Интерпретация уровня и тренда следует официальному [примеру statsmodels по ADF/KPSS](https://www.statsmodels.org/stable/examples/notebooks/generated/stationarity_detrending_adf_kpss.html).
- [`arch.unitroot.PhillipsPerron`](https://arch.readthedocs.io/en/stable/unitroot/generated/arch.unitroot.PhillipsPerron.html) и [`statsmodels.zivot_andrews`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.zivot_andrews.html) оставлены подтверждающими диагностиками и не «голосуют» повторно в консенсусе. В быстрой матрице кандидатов они пропускаются, чтобы не умножать дорогие тесты.
- Auto не подбирает преобразование по минимальному p-value, что создавало бы data snooping: stationary → без преобразования, trend-stationary → linear detrend, non-stationary/inconclusive → первая разность для сравнения. Сезонная разность применяется только при подтверждённом периоде; ACF(1) < −0,5 показан лишь как эвристическое предупреждение возможного over-differencing.
- Linear detrend реализован официальным [`scipy.signal.detrend`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.detrend.html). Полноисторический detrend честно помечен `causal=false`, требует отдельного opt-in и в backtest должен переоцениваться только на train. Для разностей сам оператор каузален, но d/D/s также выбираются внутри train-fold. Общая логика минимальных обычных и сезонных разностей сверена с [Forecasting: Principles and Practice](https://otexts.com/fpp3/stationarity.html).

### Реализация

- Добавлен чистый core шести преобразований: `linear_detrend`, первая, вторая, сезонная, комбинированная и log-разность. Для каждого возвращаются d/D/s, causal/modeling-safe, число потерянных строк и достаточные inverse-границы; исходный ряд не перезаписывается.
- Добавлен `GET /v1/session/dataset/preprocessing/stationarity-profile`: полный ADF/KPSS/PP/Zivot–Andrews профиль до/после, матрица шести кандидатов, ACF, rolling mean/std, дисперсии, предупреждения и объяснимое Auto-решение.
- Добавлен `POST /v1/session/dataset/preprocessing/stationarity-transformations` с паттерном preview → отдельное подтверждение → атомарный apply. Датасет стабильно сортируется по определённой временной оси, математически неопределённый префикс удаляется синхронно из всех колонок, а преобразованный target добавляется новой колонкой.
- Строгие гейты блокируют пропуски/inf, константу, N < 30, битые или повторные даты, панель и нерегулярную сетку. Если временная колонка уверенно не определена, используется текущий row-order с явным предупреждением.
- Metadata в `AnalysisSession.preprocessing_transformations` сохраняет source/output, оператор, порядок разностей, period, log-domain, trend slope/intercept, `history_tail`, `fitted_on_n`, порядок строк и поддержку inverse.
- Остановка подключена к общему target/dataset lifecycle, режимам `auto/enabled/disabled`, степперу, статусам, метрикам, ручному пересчёту и обеим оболочкам.
- В «Обзоре» реализованы пять визуальных представлений светло-серыми круглыми бейджами: ряд до/после, нормированные rolling μ/σ, сравнение p-value и противоположных H0, ACF до/после с границами и таблица всех кандидатов. В интерфейс встроены ссылки на официальные источники.
- Мастер показывает потерю строк и имя новой колонки до мутации, объясняет inverse-контракт, отдельно подтверждает offline-detrend и повторно подтверждает применение к активному датасету.

### TDD и проверка

- RED backend: отсутствовали `app.preprocessing.stationarity` и stationarity session API; RED frontend: отсутствовали `PreprocessingStationarityOverview`/`Pipeline`.
- Расширенная Python-регрессия core/EDA/API и соседних остановок: 108/108 PASS, 3 snapshots PASS.
- Frontend всей вкладки «Предобработка»: 18 suites, 109/109 PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; штатные build-проверки типов прошли.
- `git diff --check` и task Python compile: PASS. Optional `tests/api/test_session_store.py` в локальном окружении пропущен целиком из-за отсутствия `fakeredis`; metadata persistence покрыта API apply-тестом.

### Изменённые и новые файлы

- `app/eda/stationarity.py`
- `app/preprocessing/stationarity.py`
- `apps/api/preprocessing_stationarity.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/PreprocessingStationarityOverview.tsx`
- `packages/ui/components/PreprocessingStationarityOverview.test.tsx`
- `packages/ui/components/PreprocessingStationarityPipeline.tsx`
- `packages/ui/components/PreprocessingStationarityPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_stationarity.py`
- `tests/unit/test_preprocessing_stationarity.py`
- `tests/unit/test_preprocessing_stationarity_adapter.py`

---

## Task ID: 85 — Предобработка «Спектральный анализ»

Дата: 2026-09-02

### Аудит методологии

- В backend уже существовал зрелый контур `app.features.spectral.analyze_spectral_seasonality`: linear detrend, периодическое окно Hann, односторонние FFT/periodogram, нормированная spectral entropy, поиск пиков и подтверждение кандидатов через ACF и устойчивость фазового профиля. EDA API также уже проверял временную ось, сортировку, дубликаты, панель и регулярность. Поэтому новый контур предобработки переиспользует этот двигатель без копирования и расхождения формул.
- Legacy-функции `compute_fft_features`, `compute_periodogram_features`, `compute_spectral_entropy` и `compute_low_high_freq_ratio` не выбраны основой: они ограничиваются вычитанием среднего, используют абсолютный порог `mean + k·σ`, а entropy не нормирована и зависит от длины ряда. Они сохранены для обратной совместимости, но UI не выдаёт их эвристики за основной метод.
- Глобальные периоды оцениваются через [`scipy.signal.periodogram`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html) после [`scipy.signal.detrend`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.detrend.html) и периодического окна [`scipy.signal.windows.hann`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.windows.hann.html); FFT использует официальный [`numpy.fft.rfft`](https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html). Нулевая частота исключается, максимальный период ограничивается `N / min_cycles`, чтобы кандидат содержал хотя бы заданное число повторов.
- Добавлен [`scipy.signal.welch`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html) с Hann, 50% overlap и median averaging. Welch снижает дисперсию PSD за счёт сегментации, но теряет частотное разрешение; поэтому он является устойчивой проверкой, а не заменой full-history periodogram.
- Добавлен обзор времени–частоты через [`pywt.cwt`](https://pywavelets.readthedocs.io/en/stable/ref/cwt.html) с комплексным Morlet `cmor1.5-1.0`. CWT используется как визуальная диагностика локальности/дрейфа циклов, а не как формальный significance test; крайние точки, затронутые конечностью ряда, визуально приглушаются. Минимальный период равен двум наблюдениям, вывод ограничен 64 масштабами и 120 временными точками, а диапазон CWT — 512 наблюдениями на период для контролируемого payload.
- Для нерегулярной временной сетки классические FFT/periodogram/Welch не выполняются скрыто. Остановка блокируется до исправления регулярности и ссылается на специализированный [`scipy.signal.lombscargle`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.lombscargle.html), вместо молчаливого предположения равного шага.
- Подтверждение периода по periodogram + ACF + phase strength является прозрачной эвристикой, а не доказательством сезонности. Отсутствие подтверждённых периодов — нормальный аналитический результат, а не ошибка. Выбор по полной истории помечен `analysis_only=true`, `causal=false`, `modeling_safe=false`: в backtest периоды необходимо заново выбирать только на train-fold.

### Реализация

- Добавлен core `app.preprocessing.spectral`: median Welch PSD, автоматический/ручной размер сегмента, доли мощности в low/mid/high полосах и CWT scaleogram/global spectrum со строгой проверкой finite, константы и N ≥ 24.
- Добавлен `GET /v1/session/dataset/preprocessing/spectral-profile`: общий target и временной контракт EDA, FFT, periodogram, Welch, CWT, phase profile, кандидаты, frequency resolution, Nyquist, предупреждения, рекомендации и сохранённый выбор периодов.
- Добавлен `POST /v1/session/dataset/preprocessing/spectral-selections` с паттерном preview → отдельное подтверждение → apply. Остановка не изменяет DataFrame и не создаёт лаги: она сохраняет уникальные целочисленные периоды как явную конфигурацию для следующего этапа feature engineering. Неподтверждённый кандидат требует отдельного opt-in; выбор «периоды не обнаружены» поддержан явно.
- В `AnalysisSession` добавлено backward-compatible поле `preprocessing_spectral_selection`; оно сериализуется в Redis/Memory, сбрасывается при загрузке нового датасета и не смешивается с преобразованиями колонок.
- Остановка подключена к общему target/dataset lifecycle, режимам `auto/enabled/disabled`, степперу, статусам, четырём метрикам и ручному пересчёту embedded/standalone. Для применимого профиля статус `done` сохраняется и при нуле циклов; счётчик показывает только подтверждённые периоды.
- В «Обзоре» реализованы пять представлений светло-серыми круглыми бейджами: FFT + periodogram, Welch PSD + полосы мощности, CWT scaleogram с приглушёнными краями, phase profile и таблица кандидатов. В UI встроены ссылки на официальную документацию NumPy/SciPy/PyWavelets.
- Мастер позволяет настраивать `min_cycles`, число кандидатов, Welch segment и количество wavelet scales, выбирать периоды, отдельно разрешать неподтверждённые кандидаты, выполнять preview и подтверждать сохранение без мутации датасета.
- В API-зависимости явно добавлен `PyWavelets>=1.4.0`.

### TDD и проверка

- RED backend: отсутствовали `app.preprocessing.spectral` и `apps.api.preprocessing_spectral`; RED frontend: отсутствовали `PreprocessingSpectralOverview` и `PreprocessingSpectralPipeline`.
- Расширенная Python-регрессия core/EDA/API и соседних остановок: 125/125 PASS, 3 snapshots PASS.
- Дополнительная session-группа: 54 PASS, 1 optional module SKIPPED из-за отсутствия `fakeredis`; новое поле отдельно покрыто round-trip и backward-compatible unit-тестом.
- Frontend всей вкладки «Предобработка»: 20 suites, 116/116 PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; штатные lint/type checks прошли, First Load JS — 433 kB.
- `git diff --check` и task Python compile: PASS.

### Изменённые и новые файлы

- `app/preprocessing/spectral.py`
- `apps/api/preprocessing_spectral.py`
- `apps/api/requirements.txt`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/PreprocessingSpectralOverview.tsx`
- `packages/ui/components/PreprocessingSpectralOverview.test.tsx`
- `packages/ui/components/PreprocessingSpectralPipeline.tsx`
- `packages/ui/components/PreprocessingSpectralPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_spectral.py`
- `tests/unit/test_preprocessing_spectral.py`
- `tests/unit/test_preprocessing_spectral_adapter.py`

---

## Task ID: 86 — Предобработка «Генерация признаков»

Дата: 2026-09-02

### Аудит методологии

- Во frontend остановка была статической заглушкой. В backend существовали `app.features.temporal.create_temporal_features` и `create_fourier_features`, а также rolling-функции сглаживания, но не было session API, lag generator, preview/apply-контракта или каталога созданных X.
- Legacy `create_fourier_features` определяет период в календарных днях от минимальной даты. Его нельзя напрямую кормить периодом спектральной остановки, измеренным в наблюдениях: для месячного ряда `period=12` означал бы 12 дней, а не 12 месяцев. Новый Fourier-контур использует позицию наблюдения `t` и тем самым согласован с FFT/periodogram предыдущей остановки. Формулы и ограничение гармоник сверены с [`statsmodels.tsa.deterministic.Fourier`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.deterministic.Fourier.html).
- Raw month/day/dayofweek legacy-контура не выбраны основным представлением циклов: конец и начало периода численно далеки. Новый контур использует пары sin/cos по официальному примеру [scikit-learn о циклических временных признаках](https://scikit-learn.org/stable/auto_examples/applications/plot_cyclical_feature_engineering.html). Auto-набор не дублирует month sin/cos при месячном Fourier period=12 и day-of-week sin/cos при дневном Fourier period=7.
- Критическая защита от target leakage: lag строится официальным [`pandas.Series.shift(k)`](https://pandas.pydata.org/docs/reference/api/pandas.Series.shift.html), а каждая [`rolling`](https://pandas.pydata.org/docs/reference/api/pandas.Series.rolling.html)-статистика сначала получает `target.shift(1)`. Поэтому X[t] использует окно не позднее t−1. Лаговая разность определяется как `y[t−1] − y[t−k−1]`, а не включает y[t]. Существующие rolling-функции сглаживания не переиспользованы напрямую, поскольку их задача — оценка уровня текущей точки, а не supervised feature matrix.
- Warm-up не заполняется скрытыми `bfill`, нулями или текущим значением: preview показывает точный max lookback, а apply по умолчанию синхронно удаляет только общий начальный префикс. Можно осознанно оставить NaN с явным предупреждением.
- Holiday-флаг legacy-контура исключён: он жёстко выбирал календарь RU, а при недоступной библиотеке молча создавал нулевую колонку. Корректная реализация требует явных страны/региона и версии календаря; до такого контракта платформа не выдаёт фиктивные нули за признак.
- In-sample лаг-корреляция используется только для визуальной диагностики. Даже при каузальной формуле выбор лагов/окон/гармоник по полной истории является data snooping; отбор повторяется внутри train-fold, используя временную валидацию, например [`sklearn.model_selection.TimeSeriesSplit`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
- Для горизонта больше одного target-derived признаки не объявляются заранее известными: metadata фиксирует необходимость наблюдаемой истории, direct-моделей по горизонтам либо рекурсивной подстановки прогнозов. Календарь, time index и Fourier известны заранее.

### Реализация

- Добавлен чистый core `generate_time_series_features`: положительные уникальные лаги, trailing rolling mean/std/min/max, лаговые разности, `time_idx`, календарные year/quarter/sin-cos/weekend и positional Fourier до пяти идентифицируемых гармоник. Для периода 2 создаётся только информативная Nyquist cosine, без тождественно нулевого sine.
- Введены ограничения: минимум 8 наблюдений на уровне остановки, finite target без пропусков, параметры меньше N, максимум 100 создаваемых признаков, запрет коллизий имён. Общий `smart_to_datetime` переиспользован для корректной обработки числовых колонок годов без схлопывания в наносекунды 1970 года.
- Добавлен `GET /v1/session/dataset/preprocessing/feature-generation-profile`: временной контракт, актуальность спектрального hand-off, рекомендации, max lookback, сохранённый набор и пять payload-визуализаций. Битые/повторные даты, панель и нерегулярность блокируются; row-order разрешает лаги/Fourier, но не календарь.
- Добавлен `POST /v1/session/dataset/preprocessing/feature-generations` с preview → отдельное подтверждение → атомарный apply. Исходные колонки не перезаписываются; DataFrame сортируется по времени, X добавляются новыми колонками, warm-up удаляется только после успешного расчёта всего набора.
- В `AnalysisSession` добавлено backward-compatible поле `preprocessing_feature_generation`; оно сериализует конфигурацию, каталог формул, имена X, target shift, lookback, dropped rows, порядок, causal/row-level safe и forecast contract, сбрасывается при новом датасете.
- Остановка подключена к target lifecycle, `auto/enabled/disabled`, степперу, прогрессу, статусам, четырём метрикам и ручному пересчёту. `warning` означает, что безопасный набор рекомендован, но ещё не применён; `done` — сохранённые колонки существуют в актуальном DataFrame.
- В «Обзоре» реализованы пять представлений светло-серыми круглыми бейджами: preview target/lag/rolling/Fourier, лаг-корреляции, availability/warm-up, календарные и Fourier-циклы, каталог формул. Payload графиков ограничен 240 временными точками.
- Мастер поддерживает лаги, rolling-окна и статистики, lagged differences, календарные признаки, Fourier periods/harmonics, time index и политику warm-up; показывает число колонок/строк до мутации и отдельно подтверждает apply.

### TDD и проверка

- RED backend: отсутствовали `app.preprocessing.feature_engineering` и `apps.api.preprocessing_feature_engineering`; RED frontend: отсутствовали `PreprocessingFeatureEngineeringOverview` и `PreprocessingFeatureEngineeringPipeline`.
- Task-набор core/adapter/API/session: 13/13 PASS.
- Расширенная Python-регрессия текущей и соседних остановок: 140/140 PASS; 1 optional module SKIPPED из-за отсутствия `fakeredis`.
- Полный frontend-набор компонентов: 73 suites, 601/601 PASS; сфокусированная интеграция новой остановки и родителя: 46/46 PASS.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; штатные lint/type checks прошли, First Load JS — 439 kB.
- `git diff --check` и task Python compile: PASS.

### Изменённые и новые файлы

- `app/preprocessing/feature_engineering.py`
- `apps/api/preprocessing_feature_engineering.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/PreprocessingFeatureEngineeringOverview.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringOverview.test.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringPipeline.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_feature_engineering.py`
- `tests/unit/test_preprocessing_feature_engineering.py`
- `tests/unit/test_preprocessing_feature_engineering_adapter.py`

---

## Task ID: 87 — Предобработка «Масштабирование»

Дата: 2026-09-02

### Аудит методологии

- Во frontend остановка оставалась статической заглушкой. В backend существовала только неиспользуемая `calculate_scaling_metrics`: она сравнивала число 3σ-выбросов, skewness, kurtosis и коэффициент вариации до/после affine scaling. Standard/MinMax/Robust/MaxAbs не удаляют выбросы и не меняют форму распределения, а CV после центрирования около нуля неустойчив, поэтому эти показатели нельзя трактовать как качество масштабирования.
- Основной вычислительный контракт приведён к официальному [`sklearn.preprocessing`](https://scikit-learn.org/stable/modules/preprocessing.html): `StandardScaler` использует mean/std, `MinMaxScaler` — обучающие min/max, `RobustScaler` — median/quantile range, `MaxAbsScaler` — max(abs), `QuantileTransformer` — эмпирическое CDF.
- Исправлен главный риск временных рядов: официальный раздел [scikit-learn Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) запрещает включать validation/test в `fit` preprocessing. Поэтому full-history preview используется только для диагностики, apply не материализует `*_scaled` колонки и не сохраняет обученные statistics. Сохраняется рецепт `fit_policy=per_train_fold`: `fit_transform(train)` и `transform(validation/test)` внутри каждого expanding/sliding fold.
- PowerTransformer исключён из этой остановки: Box–Cox/Yeo–Johnson уже реализованы в «Стабилизации дисперсии», где сохраняются λ и inverse-контракт. Повторное предложение здесь смешивало бы изменение формы распределения со scaling и создавало бы две расходящиеся реализации одного метода.
- [`QuantileTransformer`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.QuantileTransformer.html) оставлен advanced-вариантом с отдельным opt-in: официальная документация предупреждает, что ранговое отображение искажает корреляции и расстояния. Оно не выбирается автоматически.
- Нет универсального теста «масштабирование требуется»: решение зависит от модели. Auto предлагает [`StandardScaler`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html) при спокойном профиле и [`RobustScaler`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.RobustScaler.html) при IQR-выбросах >1% или |skew|>2; итог сравнивается с no-scaling во временном backtest. [`MinMaxScaler`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.MinMaxScaler.html) и [`MaxAbsScaler`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.MaxAbsScaler.html) доступны для явных требований диапазона/сохранения нулей.

### Реализация

- Добавлен чистый core `fit_transform_scaling` с официальными sklearn-классами, строгой проверкой списка колонок, numeric/finite/constant, диапазонов, числа квантилей и лимитом 50 колонок. Входной DataFrame не мутируется; QuantileTransformer детерминирован `random_state=0`.
- Добавлен `GET /v1/session/dataset/preprocessing/scaling-profile`: профиль всех числовых колонок, роли target/generated/source, hand-off непрерывных X из «Генерации признаков», исключение temporal/constant/missing, Auto-набор, data-dependent стартовый метод и проверка актуальности сохранённого рецепта по SHA-256 fingerprint значений/dtypes/индекса.
- Добавлен `POST /v1/session/dataset/preprocessing/scaling-recipes` с паттерном preview → отдельное подтверждение → apply. Preview возвращает before/after-метрики на полной истории как `modeling_safe=false`; apply сохраняет только параметры рецепта, не меняет DataFrame и не переносит fitted statistics.
- В `AnalysisSession` добавлено backward-compatible поле `preprocessing_scaling_recipe`; оно сериализуется в Redis/Memory, сбрасывается при новом датасете и содержит target, columns, method, параметры, fingerprint, `fit_policy=per_train_fold`, target inverse-флаг и nonlinear-флаг.
- Остановка подключена к общему target lifecycle, режимам `auto/enabled/disabled`, степперу, статусам, четырём метрикам, ручному пересчёту и ленивой загрузке только при входе в остановку. `warning` означает несохранённый аналитический рецепт, `done` — актуальный рецепт, `skipped` — отключение или отсутствие применимых числовых колонок.
- В «Обзоре» реализованы пять представлений светло-серыми круглыми бейджами: временной preview до/после на независимых шкалах, log10-сравнение σ, распределение focus-признака, контроль парных корреляций и методическая матрица пяти scaler-ов. Payload ограничен 240 строками и 12 колонками.
- Мастер позволяет выбрать несколько колонок, Standard/Robust/MinMax/MaxAbs/Quantile, feature/quantile range, число квантилей и output distribution; Quantile требует отдельного подтверждения. UI явно показывает, что DataFrame не меняется и scaler обучается заново внутри каждого train-fold.

### TDD и проверка

- RED backend: отсутствовали `app.preprocessing.scaling` и `apps.api.preprocessing_scaling`; RED frontend: отсутствовали `PreprocessingScalingOverview`/`Pipeline`, а родитель показывал заглушку.
- Task core/adapter/API/session: 13/13 PASS.
- Расширенная Python-регрессия текущей и соседних остановок: 146/146 PASS, 3 snapshots PASS; 1 optional module SKIPPED из-за отсутствия `fakeredis`.
- Полный frontend-набор компонентов: 75 suites, 607/607 PASS; сфокусированная новая остановка и родитель: 3 suites, 49/49 PASS.
- TypeScript 5.9 embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; lint/type checks прошли, First Load JS — 445 kB.
- `git diff --check` и task Python compile: PASS.

### Изменённые и новые файлы

- `app/preprocessing/scaling.py`
- `apps/api/preprocessing_scaling.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/PreprocessingScalingOverview.tsx`
- `packages/ui/components/PreprocessingScalingOverview.test.tsx`
- `packages/ui/components/PreprocessingScalingPipeline.tsx`
- `packages/ui/components/PreprocessingScalingPipeline.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/index.ts`
- `tests/api/test_dataset_preprocessing_scaling.py`
- `tests/unit/test_preprocessing_scaling.py`
- `tests/unit/test_preprocessing_scaling_adapter.py`

---

## Task ID: 88 — Высота окна «Обзор» / «Мастер»

Дата: 2026-09-02

### Аудит интерфейсного контракта

- Рабочие области вкладок «Валидация», «Предобработка» и «Разведочный анализ» использовали единый внешний размер `h-[420px]`. Контракт был продублирован в итоговых контейнерах и во всех состояниях loading/error/empty/not-applicable; частичное изменение только родительских компонентов оставило бы скачки высоты при загрузке и переключении остановок.
- Зафиксирована целевая высота `468px`: исходные `420px` + требуемые `48px`. Изменены все 165 вхождений рабочего контракта в 48 компонентах.
- Высоты вложенных графиков, таблиц, блока «Описание», правых панелей и самостоятельного legacy-обзора «Навигатора» не менялись: они не задают размер окна «Обзор»/«Мастер». Существующий `overflow-y-auto` и `feed-scroll` сохранены, поэтому дополнительная высота даёт больше полезного пространства без переполнения длинного содержимого.
- Backend/API и аналитическая методология не затронуты: задача является чистым изменением layout.

### Реализация

- Во всех Overview/Pipeline-компонентах Validation, Preprocessing и EDA внешний класс высоты и эквивалентные состояния заменены с `h-[420px]` на `h-[468px]`.
- В родительских заглушках `TsAnalysisValidation`, `TsAnalysisPreprocessing` и `TsAnalysisEDA` применён тот же размер, чтобы ещё не реализованные и неприменимые остановки не меняли высоту окна.
- Добавлен регрессионный source-contract тест `AnalysisWorkspaceHeight.test.ts`: он проверяет каждый из 48 компонентов, отсутствие старой высоты и полный охват 165 состояний.

### TDD и проверка

- RED: новый тест — 49/49 FAIL (`h-[468px]` отсутствовал, найдено 0 из 165 состояний).
- GREEN: 49/49 PASS.
- Полная frontend-регрессия: 78 suites, 673/673 PASS, 0 snapshots.
- TypeScript 5.9 embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; lint/type checks прошли, First Load JS — 445 kB.
- `git diff --check`: PASS; остаточных `h-[420px]` в `packages/ui/components/*.tsx` нет.

### Изменённые и новые файлы

- `packages/ui/components/AnalysisWorkspaceHeight.test.ts` (новый)
- `packages/ui/components/EdaCorrelationOverview.tsx`
- `packages/ui/components/EdaDescriptiveOverview.tsx`
- `packages/ui/components/EdaDistributionOverview.tsx`
- `packages/ui/components/EdaFeatureSelectionOverview.tsx`
- `packages/ui/components/EdaIhOverview.tsx`
- `packages/ui/components/EdaModelMatrixOverview.tsx`
- `packages/ui/components/EdaSeasonalityOverview.tsx`
- `packages/ui/components/EdaStationarityOverview.tsx`
- `packages/ui/components/EdaStructuralBreaksOverview.tsx`
- `packages/ui/components/EdaValidationStrategyOverview.tsx`
- `packages/ui/components/PreprocessingDecompositionOverview.tsx`
- `packages/ui/components/PreprocessingDecompositionPipeline.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringOverview.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringPipeline.tsx`
- `packages/ui/components/PreprocessingMissingOverview.tsx`
- `packages/ui/components/PreprocessingMissingPipeline.tsx`
- `packages/ui/components/PreprocessingOutliersOverview.tsx`
- `packages/ui/components/PreprocessingOutliersPipeline.tsx`
- `packages/ui/components/PreprocessingRegularityOverview.tsx`
- `packages/ui/components/PreprocessingRegularityPipeline.tsx`
- `packages/ui/components/PreprocessingScalingOverview.tsx`
- `packages/ui/components/PreprocessingScalingPipeline.tsx`
- `packages/ui/components/PreprocessingSmoothingOverview.tsx`
- `packages/ui/components/PreprocessingSmoothingPipeline.tsx`
- `packages/ui/components/PreprocessingSpectralOverview.tsx`
- `packages/ui/components/PreprocessingSpectralPipeline.tsx`
- `packages/ui/components/PreprocessingStationarityOverview.tsx`
- `packages/ui/components/PreprocessingStationarityPipeline.tsx`
- `packages/ui/components/PreprocessingVarianceOverview.tsx`
- `packages/ui/components/PreprocessingVariancePipeline.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisValidation.tsx`
- `packages/ui/components/ValidationCheckChart.tsx`
- `packages/ui/components/ValidationConsistencyOverview.tsx`
- `packages/ui/components/ValidationConsistencyPipeline.tsx`
- `packages/ui/components/ValidationFormatPipeline.tsx`
- `packages/ui/components/ValidationInclusionPipeline.tsx`
- `packages/ui/components/ValidationRangeOverview.tsx`
- `packages/ui/components/ValidationRangePipeline.tsx`
- `packages/ui/components/ValidationReferentialPipeline.tsx`
- `packages/ui/components/ValidationRegularityPipeline.tsx`
- `packages/ui/components/ValidationSufficiencyPipeline.tsx`
- `packages/ui/components/ValidationTextQualityPipeline.tsx`
- `packages/ui/components/ValidationTypeMatrix.tsx`
- `packages/ui/components/ValidationTypePipeline.tsx`
- `packages/ui/components/ValidationUniquenessOverview.tsx`
- `packages/ui/components/ValidationUniquenessPipeline.tsx`

### Дополнение — вложенная визуализация непрокручиваемых состояний

- 165 состояний повторно классифицированы по классу фактического рабочего контейнера: 44 состояния используют `overflow-y-auto`/`overflow-auto`, 121 состояние не имеет ползунка прокрутки.
- `ValidationTypeMatrix` не отнесена к изменяемой визуализации: внешний контейнер использует `overflow-hidden`, но таблица прокручивается во вложенном `overflow-auto`. Все 44 scrollable-состояния и эта матрица оставлены без изменений.
- В 120 из 121 непрокручиваемых состояний отображаются только loading/error/empty/not-applicable сообщения, уже занимающие полные `468px`; растягиваемой вложенной визуализации у них нет.
- Единственная вложенная визуализация без прокрутки — bar chart `ValidationCheckChart`. Ранее подпись `ScopeCaption` располагалась над вложенным блоком `h-[468px]`, поэтому суммарная высота превышала контракт окна. Теперь внешний flex-контейнер имеет ровно `h-[468px]`, а подпись и визуализация делят доступную высоту; chart-panel использует `min-h-0 flex-1`, а `ResponsiveContainer` — `height="100%"`.
- Тем же контейнером охвачены состояния pending/skipped/done с подписью: информационная область растягивается через `flex-1`, но не создаёт прокрутку и не превышает 468px.
- Добавлен компонентный RED/GREEN-тест для bar chart и captioned done-state. Source-contract тест расширен проверкой классификации 44/121.
- RED: 2/2 ожидаемых FAIL — отсутствовали общий контейнер 468px и растягиваемая внутренняя область.
- GREEN: сфокусированный набор 2 suites, 52/52 PASS; полная frontend-регрессия — 79 suites, 676/676 PASS.
- TypeScript 5.9 embedded/standalone: PASS; production build embedded/standalone: PASS, по 13/13 страниц, First Load JS — 445 kB; `git diff --check`: PASS.

---

## Task ID: 89 — Адаптивная высота вложенных EDA-графиков

Дата: 2026-09-02

### Диагностика

- После увеличения окна «Обзор» до `468px` графические представления «Корреляция (ACF/PACF)», «Описательные статистики» и «IH-анализ» сохраняли прежние фиксированные высоты `275px`, `200px` и `270px`. Поэтому дополнительная высота доставалась пустой области под графиком, а не самой визуализации.
- Причина пропуска в предыдущем аудите: один внешний контейнер каждого EDA-компонента имеет `overflow-y-auto` и обслуживает одновременно длинные таблицы и непрокручиваемые графические вкладки. Классификация только по CSS-классу внешнего контейнера ошибочно отнесла графические runtime-состояния к прокручиваемым.
- Общий `ChartFrame` в `DistributionCharts` изначально рассчитан на компактные карточки `200px` вкладок «Загрузка» и «Навигатор». Глобально менять его высоту нельзя: это сломало бы соседние интерфейсы.

### Реализация

- В трёх EDA-окнах внешний контейнер переведён в колонку `flex` при сохранении исходных `h-[468px]`, `overflow-y-auto` и `feed-scroll`. Заголовок и вкладки используют `shrink-0`, а графические области — `min-h-0 flex-1`, поэтому Recharts `ResponsiveContainer height="100%"` занимает всё оставшееся пространство.
- ACF/PACF, IH-рейтинг и график синергии больше не ограничены фиксированными `275px`/`270px`.
- В описательных статистиках подпись отделена как `shrink-0`, а гистограмма, KDE, разброс и их loading/error/empty-состояния растягиваются на остаток высоты. Для `DistributionCharts` добавлен необязательный `className`; без него сохранён прежний контракт `h-[200px]` для «Загрузки» и «Навигатора».
- Таблицы, карта метрик и условная карта помечены `shrink-0`: их естественная высота не сжимается, а прежняя вертикальная прокрутка внешнего окна сохраняется.

### TDD и проверка

- RED: 3 новых теста упали на фиксированных `h-[275px]`, `h-[270px]` и отсутствии растягиваемой области описательной визуализации.
- GREEN: сфокусированный набор вместе с контрактом 165 состояний — 4 suites, 64/64 PASS.
- Полная frontend-регрессия: 79 suites, 679/679 PASS, 0 snapshots.
- TypeScript 5.9 embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; lint/type checks прошли, First Load JS — 445 kB.
- `git diff --check`: PASS.

### Изменённые файлы

- `packages/ui/components/DistributionCharts.tsx`
- `packages/ui/components/EdaCorrelationOverview.tsx`
- `packages/ui/components/EdaCorrelationOverview.test.tsx`
- `packages/ui/components/EdaDescriptiveOverview.tsx`
- `packages/ui/components/EdaDescriptiveOverview.test.tsx`
- `packages/ui/components/EdaIhOverview.tsx`
- `packages/ui/components/EdaIhOverview.test.tsx`

### Дополнение — полный runtime-аудит адаптивной высоты

#### Диагностика

- Task 89 охватил только три EDA-компонента и общий `ValidationCheckChart`. Повторный аудит на уровне runtime-представлений, а не только класса внешнего контейнера, выявил ещё 18 Overview-компонентов и 3 вложенных visualization-компонента с фиксированными внутренними высотами `185–340px`.
- Во вкладке «Валидация» неадаптивным оставалось состояние «Дубликаты не найдены» в `ValidationUniquenessOverview`; остальные специализированные графики используют уже исправленный `ValidationCheckChart`. Формы «Мастера» и табличные состояния намеренно сохраняют естественную высоту и прокрутку.
- В EDA исправлены оставшиеся состояния семи обзоров: «Распределение» (гистограмма, KDE, Q–Q, CDF), «Отбор признаков» (связи, матрица, VIF, Granger), «Матрица моделей» (матрица требований, семейства, shortlist и внутренние loading/error/empty-состояния), «Сезонность» (FFT, periodogram, phase), «Стационарность» (ряд, rolling σ, p-value), «Структурные сдвиги» (режимы, CUSUM, чувствительность) и «Стратегия валидации» (folds, размер train, альтернативы и внутренние служебные состояния).
- В «Предобработке» исправлены десять обзоров: «Декомпозиция», «Генерация признаков», «Пропуски», «Выбросы», «Регулярность», «Масштабирование», «Сглаживание», «Спектральный анализ», «Стационарность» и «Стабилизация дисперсии». Вложенные loading/error/empty-состояния графиков также используют остаток рабочей высоты.
- Всего устранено 86 вхождений фиксированной внутренней высоты в 21 production-компоненте. Высота самого окна остаётся `468px`; контракт 165 внешних состояний не изменён.

#### Реализация

- Рабочие Overview-контейнеры переведены в `flex h-[468px] min-h-0 flex-col`. Заголовки, переключатели, подписи и методические примечания отмечены `shrink-0`; активная визуализация получает `min-h-0 flex-1`.
- Recharts `ResponsiveContainer` продолжает использовать `height="100%"`, но теперь 100% вычисляется от реально доступного остатка окна, а не от прежней фиксированной высоты 185–340px.
- Составные представления — парные графики, FFT/periodogram, Welch, CWT, boxplot, матрицы и карточки диагностик — адаптированы как единая область. Подписи остаются внутри контракта 468px и не отнимают высоту скрыто.
- Таблицы и длинные формы «Мастера» не растягиваются по строкам: они сохраняют `overflow-auto`/`overflow-y-auto`, естественную высоту содержимого и существующий scrollbar-контракт.
- Добавлен source-contract тест `AdaptiveWorkspaceVisualizations.test.ts`, который фиксирует полный перечень 21 компонента, запрещает возврат прежних фиксированных высот и требует flex-контракт для Overview и вложенных визуализаций.

#### TDD и проверка

- RED: новый контракт — 21/21 FAIL на оставшихся фиксированных высотах и отсутствии flex-контракта.
- GREEN: новый контракт — 21/21 PASS; сфокусированный набор вместе с контрактом 165 состояний и компонентами Task 89 — 6 suites, 87/87 PASS.
- Полная frontend-регрессия: 80 suites, 700/700 PASS, 0 snapshots.
- TypeScript embedded/standalone: PASS.
- Production build embedded/standalone: PASS, по 13/13 страниц; First Load JS — 445 kB. Для обхода ограничения sandbox Node 24 (`uv_resident_set_memory`) применялся временный runtime-shim, после сборки удалённый и не входящий в изменения.
- `git diff --check`: PASS; в production-компонентах рабочего окна не осталось внутренних фиксированных высот `185–340px`, перечисленных в контракте.

#### Изменённые и новые файлы дополнения

- `packages/ui/components/AdaptiveWorkspaceVisualizations.test.ts` (новый)
- `packages/ui/components/EdaDistributionOverview.tsx`
- `packages/ui/components/EdaFeatureSelectionOverview.tsx`
- `packages/ui/components/EdaModelMatrixOverview.tsx`
- `packages/ui/components/EdaSeasonalityOverview.tsx`
- `packages/ui/components/EdaStationarityOverview.tsx`
- `packages/ui/components/EdaStructuralBreaksOverview.tsx`
- `packages/ui/components/EdaValidationStrategyOverview.tsx`
- `packages/ui/components/PreprocessingDecompositionOverview.tsx`
- `packages/ui/components/PreprocessingFeatureEngineeringOverview.tsx`
- `packages/ui/components/PreprocessingMissingOverview.tsx`
- `packages/ui/components/PreprocessingMissingVisualizations.tsx`
- `packages/ui/components/PreprocessingOutliersOverview.tsx`
- `packages/ui/components/PreprocessingOutliersVisualizations.tsx`
- `packages/ui/components/PreprocessingRegularityOverview.tsx`
- `packages/ui/components/PreprocessingRegularityVisualizations.tsx`
- `packages/ui/components/PreprocessingScalingOverview.tsx`
- `packages/ui/components/PreprocessingSmoothingOverview.tsx`
- `packages/ui/components/PreprocessingSpectralOverview.tsx`
- `packages/ui/components/PreprocessingStationarityOverview.tsx`
- `packages/ui/components/PreprocessingVarianceOverview.tsx`
- `packages/ui/components/ValidationUniquenessOverview.tsx`

---

Task ID: 90 — Паспорта свойств ряда, этапы 1–2 (TDD foundation)

Границы пакета

Реализованы только согласованные этапы 1–2: каноническая подготовка ряда, устойчивый fingerprint, методологическое усиление расчёта и session-state/Redis persistence.

Session API, Pydantic-схемы и frontend-панели намеренно не добавлялись: они относятся к следующему самостоятельному пакету и будут опираться на зафиксированный здесь контракт.

TDD: RED

Добавлены 24 контрактных теста в двух новых файлах.

RED подтверждён ожидаемыми ошибками импорта: отсутствовали prepare_passport_series, series_fingerprint и PassportSnapshot.

Контракты покрывают очистку/сортировку ряда без мутации исходного DataFrame, отбрасывание NaN/Inf до проверки длины, запрет панельных дубликатов дат, коллизию прежнего агрегатного fingerprint, честные applicable=False для нерегулярных данных, частотно-зависимый STL и Redis roundtrip истории.

Реализация этапа 1 — ядро и методология

В app/core/passport.py добавлен единый prepare_passport_series(): числовое и datetime-приведение, удаление только невалидных пар, UTC-нормализация, стабильная сортировка, запрет скрытой агрегации повторяющихся дат и гейт минимум 30 валидных наблюдений.

calculate_ts_passport() теперь использует тот же канонический контракт и не считает NaN/Inf валидными точками.

Слабый checksum спецификации заменён SHA-256 от pandas.util.hash_pandas_object(series, index=True): учитываются все значения и timestamps; перестановка строк после сортировки не создаёт ложную устарелость. Тест воспроизводит два ряда с одинаковыми len/first/last/sum/sumsq, которые прежняя схема считала одинаковыми.

Для нерегулярного ряда лаговые и спектральные методы (Ljung–Box, ACF, Hurst, FFT, periodogram, CWT, STL) возвращают явные applicable=False и reason, а не методологически недостоверные числа.

STL-period выводится из частоты: D=7, B=5, W=52, M/MS/ME=12, Q/QS/QE=4. Для годовых данных сезонность не выдумывается; требуется не менее двух полных циклов.

Формула силы сезонности приведена к 1 - Var(resid) / Var(seasonal + resid) с ограничением [0,1]. FFT, periodogram и CWT ранжируют пики по мощности, а не по величине периода/порядку индекса.

В паспорт добавлены интерпретационные данные: нулевая гипотеза ADF, проверенный lag Ljung–Box и порог надёжности асимптотики Jarque–Bera (n > 2000).

Реализация этапа 2 — состояние сессии

В AnalysisSession добавлены date_column и append-only passport_history со снимками start / validation / exit.

PassportSnapshot фиксирует UUID, этап, defensive copy паспорта, fingerprint, target/date context и UTC ISO timestamp. latest_passport(stage) предоставляет актуальную версию без потери аудиторского следа повторных расчётов.

История сбрасывается при новом датасете, фактической смене target_column или date_column; повторная установка того же значения историю сохраняет.

JSON/Redis сериализация и десериализация расширены с backward-compatible defaults для старых Redis-сессий без новых полей.

Методологическое отклонение от исходного варианта «перезаписывать одну точку» осознанное: append-only хранение исключает потерю промежуточных решений, а внешний контракт будущего API остаётся простым через последний снимок этапа.

GREEN и проверка

Новый пакет: 24/24 PASS.

Паспортная и session-store регрессия: 121/121 PASS (test_passport, test_compare_ts_props, оба новых файла и общий Memory/Redis contract).

py_compile изменённых production-файлов: PASS.

git diff --check: PASS.

Полный pytest запущен, но collection исходного дерева блокируется окружением (httpx2, pandera и другие зависимости полного backend runtime), а также ранее зафиксированным в worklog IndentationError в tests/unit/test_file_loader.py:87. Эти блокеры не относятся к Task 90; затронутый регрессионный набор проходит полностью.

Изменённые и новые файлы
- app/core/passport.py
- apps/api/session_store.py
- tests/unit/test_passport_foundation.py (новый)
- tests/api/test_passport_session_state.py (новый)

Дополнение — вложенная визуализация непрокручиваемых состояний

165 состояний повторно классифицированы по классу фактического рабочего контейнера: 44 состояния используют overflow-y-auto/overflow-auto, 121 состояние не имеет ползунка прокрутки.

ValidationTypeMatrix не отнесена к изменяемой визуализации: внешний контейнер использует overflow-hidden, но таблица прокручивается во вложенном overflow-auto. Все 44 scrollable-состояния и эта матрица оставлены без изменений.

В 120 из 121 непрокручиваемых состояний отображаются только loading/error/empty/not-applicable сообщения, уже занимающие полные 468px; растягиваемой вложенной визуализации у них нет.

Единственная вложенная визуализация без прокрутки — bar chart ValidationCheckChart. Ранее подпись ScopeCaption располагалась над вложенным блоком h-[468px], поэтому суммарная высота превышала контракт окна. Теперь внешний flex-контейнер имеет ровно h-[468px], а подпись и визуализация делят доступную высоту; chart-panel использует min-h-0 flex-1, а ResponsiveContainer — height="100%".

Тем же контейнером охвачены состояния pending/skipped/done с подписью: информационная область растягивается через flex-1, но не создаёт прокрутку и не превышает 468px.

Добавлен компонентный RED/GREEN-тест для bar chart и captioned done-state. Source-contract тест расширен проверкой классификации 44/121.

RED: 2/2 ожидаемых FAIL — отсутствовали общий контейнер 468px и растягиваемая внутренняя область.
GREEN: сфокусированный набор 2 suites, 52/52 PASS; полная frontend-регрессия — 79 suites, 676/676 PASS.

---

Task ID: 91 — Паспорта свойств ряда, этап 3 (session API, TDD)

Границы пакета

Реализован следующий самостоятельный этап плана после foundation/persistence Task 90: единый session API выбора временной колонки, readiness/status, фиксации паспортов `start` / `validation` / `exit` и сравнения снимков.

Frontend-панели паспортов в «Загрузке», «Валидации» и «Предобработке» намеренно не входят в этот пакет: они будут следующим этапом и используют зафиксированный здесь API-контракт.

TDD: RED

Добавлен новый API-набор `tests/api/test_dataset_passport.py`. Первичный RED: 19/19 ожидаемых FAIL с HTTP 404, так как session routes ещё отсутствовали. До GREEN набор расширен до 22 тестов: добавлены числовая колонка года, сброс истории при очистке target через преобразование типа и защита полноты stateless `PassportResponse`.

Контракты покрывают GET/POST временной колонки, detector suggestion, сохранение и сброс истории, readiness/staleness, все три точки фиксации, повторные снимки append-only, порядок точек, неизменившийся ряд, прямой путь `start → exit`, полную траекторию сравнения, ошибки dataset/columns/min-length/duplicate dates и сохранность спектральных секций ответа.

Реализация session API

- `GET /v1/session/date-column` возвращает текущее значение, ранжированные кандидаты общего platform detector и безопасную рекомендацию.
- `POST /v1/session/date-column` проверяет существование и пригодность колонки, запрещает совпадение с target, сохраняет выбор в сессии и явно сообщает о сбросе несовместимой истории.
- `GET /v1/session/dataset/passport/status` является единым источником readiness/staleness для будущих трёх frontend-панелей: возвращает текущий fingerprint и статус/дату/счётчик истории каждой точки.
- `POST /v1/session/dataset/passport/{stage}` переиспользует канонические `prepare_passport_series()`, `series_fingerprint()` и `calculate_ts_passport()`, контролирует порядок точек и возвращает 409 для расчёта без изменений.
- `GET /v1/session/dataset/passport/compare` переиспользует `_compare_ts_props()` для пары `start → validation`, конкретной пары до `exit` или полной траектории `start → validation? → exit`.
- API использует единый `PASSPORT_STAGES` из session store, без второй копии stage-контракта.

Инвалидация состояния

Смена target/date сбрасывает все паспортные снимки через методы `AnalysisSession`; повторная установка того же значения историю сохраняет. Если преобразование типа делает текущий target нечисловым и очищает его, история теперь также сбрасывается. Выбор одной колонки одновременно как date и target запрещён в обоих направлениях.

Методологические уточнения

Для подготовки индекса переиспользован `smart_to_datetime()`: это устраняет ошибочную интерпретацию числового года `2024` как наносекунд после Unix epoch, сохраняя календарную семантику.

История остаётся append-only согласно решению тимлида для будущего «Отчёта об исследовании временного ряда». При проверке доступности повторного `validation`/`exit` API сравнивает ряд с последним снимком того же этапа, а не только с предыдущей точкой траектории; это не позволяет повторно нажимать кнопку без нового изменения и не теряет аудиторский след.

Pydantic `PassportResponse` дополнен уже вычисляемыми каноническим backend секциями `correlations`, `seasonal_periods`, `fft`, `periodogram`, `wavelet`: прежняя схема молча отбрасывала их в stateless API.

Стабилизация существующего frontend-теста

В коммите синхронизации `5a6d1c3` отсутствовала ранее подготовленная коррекция теста `TsAnalysisValidation`. Она включена в пакет: перед сменой режима тест теперь ждёт завершённый React-render первого validation response, а не только увеличение счётчика fetch. Это устраняет гонку, сообщённую в полном Jest-прогоне, без изменения production frontend.

GREEN и проверка

- Новый API-набор: 22/22 PASS.
- Паспортная/session регрессия: 161/161 PASS.
- Проблемный `TsAnalysisValidation` suite: 32/32 PASS.
- Полная frontend-регрессия: 80 suites, 700/700 PASS, 0 snapshots.
- `py_compile` изменённых Python-файлов: PASS.
- FastAPI/OpenAPI smoke: PASS; все 4 новых route paths присутствуют в схеме.
- `git diff --check`: PASS.

Расширенный backend-прогон с обходом уже существующего `IndentationError` в `tests/unit/test_file_loader.py:87`: 1193 PASS, 23 FAIL, 3 ERROR. Отдельный прогон чистого worktree на точном baseline `5a6d1c3` воспроизвёл те же 26 test cases без отличий; новых backend-регрессий Task 91 не добавил. Сбои baseline относятся к коротким/single-column CSV fixtures, устаревшим diagnostics/validation expectations, ARIMA на короткой выборке и отсутствующей snapshot fixture.

Изменённые и новые файлы

- `app/core/passport.py`
- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `packages/ui/components/TsAnalysisValidation.test.tsx`
- `tests/api/test_dataset_passport.py` (новый)

---

Task ID: 92 — Паспорта свойств ряда, frontend-панели трёх вкладок (TDD)

Границы пакета

Реализован общий frontend-контур паспортов для вкладок «Загрузка», «Валидация» и «Предобработка» поверх session API Task 91. Панели являются отдельными блоками под рабочей областью вкладки и не входят в степпер, CheckStatus или pass/fail-прогресс.

TDD: RED

Добавлен контрактный компонентный набор `DatasetPassportPanel.test.tsx` и изменён интеграционный контракт `TsAnalysisPreprocessing.test.tsx`.

RED зафиксирован двумя ожидаемыми причинами: общий `DatasetPassportPanel` отсутствовал (TypeScript module-not-found), а «Паспорт свойств ряда» продолжал отображаться одиннадцатой mock-остановкой степпера. Backend-контракт удаления `passport` из preprocessing modes также добавлен до изменения production-константы; его первый запуск был заблокирован исчезнувшим локальным executable venv, после подключения доступного Python runtime тест прошёл вместе с расширенной регрессией.

Общий компонент

Создан `DatasetPassportPanel`, используемый всеми тремя вкладками с параметром `stage: start | validation | exit`.

- Заголовки используют пользовательские имена «Паспорт свойств ряда: Загрузка / Валидация / Предобработка», а технические id остаются в API.
- Панель загружает единый status и date-column contract, показывает target/date context, дату последнего снимка, staleness и число append-only снимков этапа.
- Кандидаты временной колонки фильтруются по тому же порогу 0,7, который применяет backend. Если date ещё не сохранена, панель использует уверенную рекомендацию Upload/backend и атомарно сохраняет её перед фиксацией паспорта.
- Кнопки всегда видимы и дизейблятся с объяснением: нет датасета/target/date, нет обязательного `start`, ряд не изменился, итоговая точка уже закрыла траекторию либо baseline нельзя переписать после downstream-снимка.
- После расчёта отображаются 12 переиспользуемых Metric-карточек: n, частота, ADF, R², Ljung–Box, Jarque–Bera, тренд, сила сезонности, Hurst, mean/σ, топ-корреляции и FFT-периоды.
- Для `validation` и `exit` доступно сравнение. Таблица строит двух- или трёхточечную траекторию из backend `path/comparisons`, показывает значения каждой точки и соседние Δ/Δ%; под ней выводятся summary, булевы/категориальные изменения и chip-diff добавленных/удалённых периодов.

Интеграция вкладок

- «Загрузка» фиксирует `start`, переиспользует общий target и уверенную date-колонку локальной structural detection.
- «Валидация» фиксирует/пересчитывает `validation` только после `start` и только при изменившемся ряде; после снимка открывает сравнение `start → validation`.
- «Предобработка» фиксирует `exit` при наличии `start`; `validation` опционален. Сравнение показывает `start → validation → exit` либо прямой `start → exit`.
- Mock-пункт `passport` удалён из frontend `CHECKS` и backend `PREPROCESSING_CHECK_IDS`. Степпер предобработки теперь содержит 10 преобразующих остановок; паспорт не влияет на знаменатель прогресса и режимы auto/enabled/disabled.
- Справка предобработки обновлена с версионных `v1.x` на смысловые точки start/validation/exit.

Инвалидация и уведомления

TypeScript-зеркало `TargetColumnResponse` дополнено `passport_history_reset`. Общий `useTargetColumn` теперь сохраняет отдельное уведомление при ручной смене target, если backend сбросил паспортную историю. Все три панели явно показывают, какая смена признака сбросила цепочку.

Смена date также не происходит молча: для поздних стадий панель останавливает расчёт, сообщает о сбросе и направляет сначала зафиксировать новый `start`; на вкладке загрузки сообщение объединяется с подтверждением нового baseline.

Методологическая оценка

Паспорт намеренно не получает «пройдено/ошибка»: ADF, R², Hurst, сезонность и корреляции не имеют универсального направления качества вне контекста модели.

Радарная диаграмма не реализована: перевод разнородных тестов в оси 0…1 потребовал бы незафиксированных весов и порогов и создавал бы ложную интегральную оценку. Основной интерфейс сохраняет исходные статистики и backend-дельты.

Цвет направления применяется только там, где интерпретация однозначна в данном контракте: снижение ADF p-value и рост Jarque–Bera p-value. R² тренда, slope, Hurst, сезонность, mean и σ остаются нейтральными — их увеличение само по себе не означает улучшение ряда.

GREEN и проверка

- Компонент и три интеграции: 4 suites, 113/113 PASS.
- Полная frontend-регрессия: 81 suites, 711/711 PASS, 0 snapshots.
- Паспортная и preprocessing backend-регрессия: 96/96 PASS.
- TypeScript standalone/embedded: PASS. Для обхода baseline side-effect CSS import использован только флаг проверки `--noUncheckedSideEffectImports false`; production-код и tsconfig не менялись.
- Production build standalone/embedded: PASS, по 13/13 страниц; First Load JS — 449 kB. Из-за sandbox Node 24 временно применялись memory telemetry shim и декларации `*.css`; после проверки они удалены и в изменения не входят.
- `py_compile` изменённого Python API и теста: PASS.
- `git diff --check`: PASS.

Изменённые и новые файлы

- `apps/api/routers/session.py`
- `packages/ui/components/DatasetPassportPanel.tsx` (новый)
- `packages/ui/components/DatasetPassportPanel.test.tsx` (новый)
- `packages/ui/components/TsAnalysisUpload.tsx`
- `packages/ui/components/TsAnalysisUpload.test.tsx`
- `packages/ui/components/TsAnalysisValidation.tsx`
- `packages/ui/components/TsAnalysisValidation.test.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.tsx`
- `packages/ui/components/TsAnalysisPreprocessing.test.tsx`
- `packages/ui/hooks/useTargetColumn.ts`
- `packages/ui/lib/modeling.ts`
- `packages/ui/index.ts`
- `tests/api/test_dataset_passport.py`
- `worklog2.md`

---

Task ID: 93 — Финальный паспорт EDA перед моделированием (TDD)

Синхронизация и границы

Работа выполнена в отдельном чистом worktree на точном коммите `bb113059bdfbb9d6b928cc4d0a4b5a8e7a75aadd`; незакоммиченные изменения прежних задач в исходной рабочей папке не затрагивались. Реализована согласованная четвёртая логическая точка паспортного контура на границе EDA → Modeling.

Методологическое решение

EDA в текущем пайплайне является read-only аналитическим этапом. Поэтому `modeling_entry` реализован как обязательный логический checkpoint, но не как безусловная копия третьего паспорта:

- `PassportSnapshot` хранит полный результат канонического `calculate_ts_passport()` только для уникального состояния ряда;
- `PassportCheckpoint` фиксирует подтверждение точного снимка для моделирования;
- при совпадении fingerprint с существующим снимком создаётся только ссылка, без повторного расчёта и хранения паспорта;
- при новом fingerprint создаётся физический snapshot стадии `modeling_entry`, затем checkpoint ссылается на него;
- если ряд вернулся к ранее сохранённому состоянию, старый snapshot переиспользуется, а сравнение показывает содержательный переход к нему;
- выводы EDA не смешиваются с паспортом данных: стационарность, сезонность, структурные сдвиги, стратегия валидации и shortlist моделей остаются отдельным аналитическим контуром.

Спецификация `spec_passports.md` дополнена приоритетным разделом для четырёхточечного жизненного цикла. Внутренний `exit` сохранён для обратной совместимости и теперь явно трактуется как выход из Предобработки; финальная граница входа в моделирование — `modeling_entry`.

TDD: RED

Backend-тесты сначала завершились ожидаемой ошибкой импорта отсутствующего `PassportCheckpoint`. Контракт покрывает ссылочный checkpoint без копирования паспорта, append-only историю подтверждений, Memory/Redis roundtrip, сброс по dataset/target/date, обязательный `start`, создание нового снимка только для нового fingerprint, повторное подтверждение, возврат к старому fingerprint и сравнение без фиктивной нулевой дельты.

Frontend RED после подключения уже установленных зависимостей подтвердил отсутствие `modeling_entry` в `PassportStage`. Компонентные и EDA-интеграционные тесты добавлены до production-правок: отдельная EDA-панель, удаление mock-пункта из степпера, активное первое подтверждение неизменившегося ряда, сообщение о переиспользовании snapshot и checkpoint-callout в сравнении.

Backend и персистентность

- `PASSPORT_STAGES` расширен `modeling_entry`; добавлен отдельный контракт `PASSPORT_CHECKPOINT_STAGES`.
- `AnalysisSession` получил append-only `passport_checkpoints`, методы добавления/поиска checkpoint и разрешения `snapshot_id`.
- JSON/Redis-сериализация использует backward-compatible default `[]` для старых сессий.
- Единый `reset_passports()` теперь атомарно очищает снимки и checkpoint при смене dataset/target/date.
- `GET /dataset/passport/status` возвращает состояние `modeling_entry`, источник снимка, staleness и число подтверждений.
- `POST /dataset/passport/modeling_entry` переиспользует snapshot при совпадении fingerprint либо рассчитывает новый канонический паспорт; повторное подтверждение текущего ряда получает 409.
- `GET /dataset/passport/compare?to=modeling_entry` возвращает уникальную траекторию физических снимков и отдельные метаданные checkpoint. При неизменном EDA финальная дублирующая колонка не создаётся; более поздний возврат в Предобработку не переписывает уже подтверждённую траекторию задним числом.

Frontend EDA

- Общий `DatasetPassportPanel` расширен стадией `modeling_entry` и заголовком «Паспорт свойств ряда: Для моделирования».
- Первое подтверждение доступно даже при неизменном после Предобработки ряде; после подтверждения кнопка дизейблится до изменения fingerprint.
- UI различает новый snapshot, ссылку на последний snapshot и переиспользование более старого состояния.
- Mock «Паспорт свойств ряда» удалён из `CHECKS`: EDA-степпер содержит 10 реальных исследований, а паспорт расположен отдельной панелью под трёхколоночной рабочей областью и не влияет на progress/CheckStatus.
- Справка EDA переведена с условного `v1.0 → v1.3` на смысловой checkpoint-контракт.
- Уведомление общего `useTargetColumn` о сбросе цепочки передаётся и в EDA-панель.

GREEN и проверка

- Целевой backend-контракт: 40/40 PASS.
- Расширенная паспортная/session-регрессия: 150/150 PASS.
- Целевой frontend-контракт: 2 suites, 43/43 PASS.
- Полная frontend-регрессия: 81 suites, 714/714 PASS, 0 snapshots.
- TypeScript standalone/embedded: PASS с тем же проверочным флагом `--noUncheckedSideEffectImports false`, который использовался в Task 92; production tsconfig не менялся.
- Production build embedded/standalone: PASS, по 13/13 страниц; First Load JS — 450 kB. Временные memory/CSS shims для ограничений sandbox Node 24 удалены и в пакет не входят.
- `py_compile` изменённых Python-файлов и `git diff --check`: PASS.
- Полный backend collection по-прежнему блокируется baseline `IndentationError` в `tests/unit/test_file_loader.py:87`. Прогон с исключением только этого файла: 1200 PASS, 23 FAIL, 3 ERROR; количество и классы известных сбоев совпадают с ранее зафиксированным baseline и не относятся к Task 93.

Изменённые файлы

- `apps/api/routers/session.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/DatasetPassportPanel.tsx`
- `packages/ui/components/DatasetPassportPanel.test.tsx`
- `packages/ui/components/TsAnalysisEDA.tsx`
- `packages/ui/components/TsAnalysisEDA.test.tsx`
- `tests/api/test_dataset_passport.py`
- `tests/api/test_passport_session_state.py`
- `spec_passports.md`
- `worklog2.md`

Артефакт передачи

- `download/task93_eda_modeling_passport_bb11305.zip` — только перечисленные изменённые файлы текущей задачи с сохранением структуры каталогов.

---

Task ID: 94 — Сквозная трассируемость и рабочий модуль «Моделирование» (TDD)

Синхронизация и аудит

Работа выполнена в ветке `main` на точном исходном коммите `ae4a27f60f6f5ebd0637b939c98e6742492e70c9`; commit/push не выполнялись. Изучены `AGENTS.md`, `worklog_summary.md`, `worklog2.md`, legacy-план Modeling, `rules/modeling.yaml`, session/passport API, все остановки Validation/Preprocessing/EDA, существующие кандидаты, backtest, tuning, diagnostics и обе frontend-оболочки.

До Task 94 вкладка Modeling содержала 11 визуальных шагов, но рабочими были только ручной профиль, список кандидатов и одиночный backtest. При отсутствии session target UI мог незаметно использовать синтетический ряд; `modeling_pipeline` не сохранялся; diagnostics-компонент не был включён в цепочку; compare/select/Model Card отсутствовали.

Методологическая цепочка

Зафиксирован единый маршрут:

`modeling_entry checkpoint + fingerprint → канонический ряд, отсортированный по date_column → 30 upstream-свидетельств → EDA validation strategy + model matrix → кандидаты → baseline/backtest → tuning → residual diagnostics → сопоставимое ranking → явный выбор → Model Card JSON`.

Каталог трассируемости содержит ровно 30 узлов:

- 10 проверок Validation: типы, форматы, диапазоны, согласованность, уникальность, включение, ссылочная целостность, текст, регулярность, достаточность;
- 10 остановок Preprocessing: пропуски, выбросы, регулярность, декомпозиция, стабилизация дисперсии, сглаживание, стационарность, спектр, признаки, масштабирование;
- 10 исследований EDA: descriptive, correlation, IH, seasonality, stationarity, distribution, structural breaks, feature selection, validation strategy, model matrix.

Каждый узел хранит исходный endpoint, evidence, статус `done/warning/skipped/pending`, флаг блокировки, точные Modeling inputs и downstream stages. Опциональное `skipped` не считается ошибкой. Общая sufficiency-проверка не блокирует ряд, если конкретные horizon/folds помещаются; нерегулярность ограничивает модели через model matrix, а не вводит ложный универсальный запрет.

Backend и SessionStore

- `AnalysisSession` дополнен персистентными `modeling_pipeline` из 11 канонических стадий и `modeling_artifacts`; Memory/Redis JSON round-trip обратно совместим со старыми сессиями.
- Dataset/target/date/passport reset атомарно инвалидирует Modeling.
- Новый `modeling_workflow.py` переиспользует `prepare_passport_series`, `series_fingerprint`, финальный паспорт, `build_eda_validation_strategy`, `build_eda_model_matrix`, validation engine и `modeling.yaml`; второй реализации аналитических алгоритмов нет.
- Новый session router предоставляет `GET context/state`, `POST candidates/backtest/tune/diagnostics/compare/select/card` и `GET card/{id}`.
- Все вычислительные маршруты требуют актуальный `modeling_entry`, совпадающий fingerprint, date/target и отсутствие критических blockers. Синтетический fallback запрещён; catalog-only модели получают 422 без фиктивных метрик.
- Horizon, effective folds и gap выбранной EDA-стратегии сохраняются как контракт запуска. Backtest без ручного override использует этот horizon; tuning использует те же expanding folds и gap. Sliding tuning честно возвращает 422, так как существующий production tuner реализует только expanding-window.
- Сравнение допускает только один cohort разбиения/источника. Weighted score пересчитывается min-max внутри текущего пула; MAPE исключается при нулях в target с перенормировкой весов.
- Модели с MASE > 1.05 не скрываются: они помечаются риском и требуют явного подтверждения аналитика. Это сохраняет аудиторский след.
- Ensemble не создаётся по одной близости агрегированных метрик. Backend отмечает только candidate, если есть минимум две модели с MASE < 1 и близким score; `ensemble_recommended=false`, пока отсутствует корреляция out-of-fold ошибок.
- Model Card сохраняет checkpoint/fingerprint, реальный train interval, версии библиотек, hyperparameters, CV/backtest, baseline comparison, diagnostics, limitations, recommendations и traceability; повторная загрузка доступна по card id. Не реализованное coverage prediction intervals остаётся `null` и явно внесено в limitations.

Frontend

- Профиль загружается из EDA hand-off и становится read-only; ручные поля не участвуют в расчётах.
- Кандидаты и backtest используют только `/v1/session/modeling/*` с cookie. UI дополнительно отвергает ответ, если `data_source != session`.
- После reload восстанавливаются завершённые стадии и backtests из SessionStore.
- Первые три стадии показывают интерактивную карту 30 upstream-связей с evidence и blockers.
- Tuning/diagnostics/compare/selection/Model Card получили рабочие панели в прежнем 468px layout-паттерне.
- Для tuning/diagnostics UI предлагает только реально поддержанные ETS, ETS Damped и ARIMA.
- Ranking показывает score, MASE и baseline status. Для рискованной модели требуется отдельный checkbox «Принимаю риск»; автоматического acknowledge нет.
- Model Card отображается как JSON и скачивается повторно через session endpoint.

Оценка legacy-плана

- PRE-0 остаётся обязательным release gate, но из текущего sandbox live Render/Vercel недоступны: попытки безопасного GET и запуска штатного smoke заблокированы сетевой политикой. Production smoke необходимо повторить из CI/локального окружения после деплоя Task 94.
- Phase 0+0.5 подтверждена по направлению, но ручной `PATCH modeling-stage` отвергнут: стадии выводятся из фактически сохранённых артефактов, иначе клиент может ложно отметить невыполненную стадию.
- Phase 6-P0 уже реализована шире плана: 9 production backtest моделей. Обязательный `pmdarima` отвергнут; существующий bounded statsmodels grid легче для Render и уже покрывает Auto-ARIMA.
- Phase 1 подтверждена частично: production tuning есть только для ETS/ETS Damped/ARIMA и expanding CV. Полная sliding strategy требует отдельной реализации.
- Phase 2 подтверждена: четыре диагностики уже существовали и теперь встроены в session workflow.
- Phase 3 скорректирована: polling/job layer не нужен для ранжирования уже сохранённых backtests; реализован синхронный compare. Async job понадобится при едином endpoint параллельного обучения всех моделей.
- Phase 4 скорректирована: выбор реализован, auto-ensemble без OOF прогнозов и корреляции ошибок отвергнут как методологически недоказанный.
- Phase 5 реализована как честный Model Card. Формальное заполнение prediction interval coverage числом до реализации интервалов отвергнуто; поле остаётся `null` с limitation.

Таким образом, оценка `~49 ч` не подтверждается как актуальная: значительная часть Phase 0/1/2/6-P0 уже присутствовала в baseline, а часть Phase 3/4 была избыточной или методологически неполной.

TDD и проверка

- RED backend: отсутствовали модуль traceability и session workflow routes.
- RED frontend: отсутствовали оба Modeling overview-компонента.
- Целевой backend: 9/9 PASS.
- Расширенный Modeling/SessionStore/spec backend: 135/135 PASS; после добавления horizon-контракта целевой набор отдельно 9/9 PASS.
- Полный frontend: 83 suites, 718/718 PASS, 0 snapshots.
- Целевой frontend после финальных правок: 3 suites, 54/54 PASS.
- TypeScript embedded/standalone: PASS.
- Production build standalone и embedded: PASS, по 13/13 статических страниц, включая `/modeling`; First Load JS 453 kB.
- `py_compile` и `git diff --check`: PASS.

Полный backend collection исходно блокируется `tests/unit/test_file_loader.py:87` (`IndentationError`) и отсутствующим `openpyxl`. Прогон с исключением этих двух файлов: 1189 PASS, 33 FAIL, 3 ERROR. Остаток относится к baseline/окружению: Pandas 3 string dtype против legacy object expectations, отсутствующие `ruptures` и snapshot fixture, устаревший diagnostics YAML contract и ARIMA на технически слишком коротких folds. Целевые Task 94 тесты зелёные.

Изменённые и новые файлы

- `apps/api/main.py`
- `apps/api/modeling_workflow.py` (новый)
- `apps/api/routers/modeling_session.py` (новый)
- `apps/api/routers/models.py`
- `apps/api/schemas.py`
- `apps/api/session_store.py`
- `packages/ui/components/ModelingTraceabilityOverview.tsx` (новый)
- `packages/ui/components/ModelingTraceabilityOverview.test.tsx` (новый)
- `packages/ui/components/ModelingWorkflowOverview.tsx` (новый)
- `packages/ui/components/ModelingWorkflowOverview.test.tsx` (новый)
- `packages/ui/components/TsAnalysisModeling.tsx`
- `packages/ui/components/TsAnalysisModeling.test.tsx`
- `packages/ui/lib/modeling.ts`
- `packages/ui/index.ts`
- `rules/modeling.yaml`
- `tests/api/test_modeling_workflow.py` (новый)
- `tests/unit/test_modeling_traceability.py` (новый)
- `worklog2.md`

Артефакт передачи

- `download/task94_modeling_traceability_ae4a27f.zip` — только перечисленные изменённые/новые файлы Task 94 с сохранением структуры каталогов.

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