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