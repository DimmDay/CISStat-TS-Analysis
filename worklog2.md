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
