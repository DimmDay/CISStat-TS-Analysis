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