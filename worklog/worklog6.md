# CISStat TS Analysis — Worklog

---

## Task EDA-2 -- Вкладка «Разведочный EDA»: зелёная подсветка пройденных остановок степпера (паттерн вкладки «Моделирование»)

Дата: 2026-09-14. Синхронизация: main@d553345; рабочее дерево содержит
незакоммиченные изменения Task w/n-5 (TsAnalysisModeling.tsx/.test.tsx,
этот журнал) -- задача EDA-2 выполнялась ПОВЕРХ них, файлы Modeling не
затронуты. Постановка тимлида: на вкладке «Моделирование» применён
паттерн «Если остановка степпера пройдена и имеет зелёную галочку, то
кнопка остановки окрашивается в светло-зелёный цвет и текст становится
зелёным. При других статусах кнопка остановки не окрашивается и цвет
текста не меняется» -- применить данный паттерн к модулю «Разведочный
EDA». Полный цикл AGENTS.md: TDD RED->GREEN, полная frontend-регрессия,
typecheck/build обеих оболочек.

### Дизайн (эталон и точка изменения)

- ЭТАЛОН: TsAnalysisModeling.tsx (степпер 11 стадий, строки 969-975
  после Task w/n-5): тернарная цепочка className -- (1) active:
  «bg-brand text-white border-brand» -> (2) done: «bg-green-50
  border-green-200 text-green-800» -> (3) иначе: «bg-white
  border-neutral-200 hover:bg-neutral-50 text-neutral-800». Зелёная
  галочка = StatusIcon «done» (CheckCircle, text-green-600).
- ТОЧКА ИЗМЕНЕНИЯ: TsAnalysisEDA.tsx, степпер 10 исследований в ЛЕВОЙ
  колонке (строка 1407 «Степпер: прямоугольные карточки...»): у кнопки
  была ДВУХветочная цепочка (active / иначе) -- ветка done ОТСУТСТВОВАЛА,
  пройденные остановки выглядели как непройденные (bg-white).
- Отличие геометрии (text-sm в EDA против text-xs в Modeling) --
  СУЩЕСТВУЮЩЕЕ, в паттерн (цвет фона/рамки/текста) не входит, не тронуто.

### Оценка рисков и решения

1. Порядок веток сохранён КАК В ЭТАЛОНЕ: active-ветка ПЕРВАЯ => активная
   остановка со статусом done остаётся индиго (green-ветка применяется
   только к НЕактивным пройденным). Гардируем тестом.
2. Чек EDA имеет 6 статусов CheckStatus (done/warning/pending/skipped/
   running/error): подсветка ТОЛЬКО при done -- все прочие не окрашиваются
   (warning/skipped/running/error/pending), как требует постановка.
   Гардируем 3 кейсами (running+pending; warning; skipped).
3. Правая колонка «Панель управления» (orderedChecks, карточки-статьи) --
   НЕ степпер; вне мандата, не тронута.
4. Иконка StatusIcon уже зелёная для done и существует независимо от
   подсветки -- не тронута (в Modeling при active иконка warning, в EDA
   истинный статус; различие существующее, вне мандата).
5. Классы green-50/green-200/green-800 -- стандартная палитра Tailwind,
   уже в бандле (Modeling, бейджи EDA): риск purge-потери исключён.

### TDD (RED -> GREEN)

- RED: 5 новых кейсов в TsAnalysisEDA.test.tsx (новая сюита «зелёная
  подсветка пройденных остановок степпера (паттерн Моделирования)»):
  (1) done+неактивная -> bg-green-50/border-green-200/text-green-800,
  соседняя pending -> bg-white без green-классов; (2) active+done ->
  приоритет индиго (bg-brand, БЕЗ green); (3) running+pending -> без
  окраски (вечнозависающий fetch); (4) warning (stats:null ->
  insufficientColumns>0) -> без окраски; (5) skipped (404 /dataset/stats
  -> descriptiveNoDataset) -> без окраски. Результат RED: ровно ОДИН
  падёж -- кейс (1): done-кнопка остаётся «bg-white border-neutral-200
  text-neutral-800» (паттерн отсутствует); кейсы-гарды (2)-(5) проходят
  ДО правки (фиксируют отсутствие окраски не-done и индиго-приоритет --
  на них паттерн не влияет).
- GREEN: правка компонента -> 35/35 в файле (30 базлайн + 5 новых).

### Верификация

- Полная frontend-регрессия: **102 сюиты / 966 passed / 0 failed**
  (базлайн после Task w/n-5 -- 102/961; +5 новых -- арифметика сходится;
  регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 embedded,
  17/17 standalone; tailwind-warn о content-паттерне -- существующий,
  вне мандата).
- Backend не затронут (0 файлов .py); правка применяется в ОБЕИХ
  оболочках через общий компонент packages/ui (прецедент Task w/n:
  форков нет).

### Границы Task EDA-2 (что осознанно НЕ сделано)

- text-sm/text-xs геометрия, иконки статусов, правая колонка,
  остальные вкладки (Validation/Preprocessing/Upload имеют СВОИ
  степперы и не входят в постановку) -- не тронуты.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@d553345 + изменения Task w/n-5 и Task EDA-2.

Изменённые/новые файлы (ZIP: download/task_eda2_eda_stepper_green_pattern.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisEDA.tsx (добавлена ветка
  done в className степпер-кнопки: «bg-green-50 border-green-200
  text-green-800» + комментарий паттерна), packages/ui/components/
  TsAnalysisEDA.test.tsx (+5 кейсов: подсветка done, индиго-приоритет
  active+done, гарды running/pending/warning/skipped),
  worklog/worklog5.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task FORECAST-1 -- Этап «Прогнозирование»: полный вертикальный срез по spec_forecasting2.md (final fit + 4 метода интервалов + session-контур + вкладка UI)

Дата: 2026-09-14. Синхронизация: main@30d00d4 (Task 143 certification
+ Task 143a fix). Постановка тимлида: «создаем модуль Прогнозирование;
изучи spec_forecasting2.md (основа) и spec_education.md (контекст вклада
в архитектуру обучения); улучшения обоснуй и примени; спроектируй вкладку
и реализуй в коде по паттернам платформы; следуй AGENTS.md».  Спецификация
v3 (2026-09-08) писалась до production-адаптеров tree_ml/neural и до
Model Execution Contract v2 как единственной точки исполнения -- по
прецеденту сертификаций (декларации сверяются с фактическим кодом)
применены УТОЧНЕНИЯ, не меняющие методологии §1-§10.

### Решение (по пунктам постановки)

1. **Исполнение через MODEL_EXECUTION_REGISTRY, не PRODUCTION_PREDICTORS**
   (уточнение к §3): spec предлагала вызов PRODUCTION_PREDICTORS[model_id]
   (backtesting.py), но это compatibility-facade ПОВЕРХ реестра
   (model_execution.py::legacy_predictor_registry «Compatibility facade for
   callers that still inject plain functions»).  Финальный рефит исполняет
   точку ИСКЛЮЧИТЕЛЬНО через MODEL_EXECUTION_REGISTRY.execute
   (ModelExecutionRequest с train/future timestamps -- обязательны для
   prophet) -- та же сертифицированная точка исполнения, что и бэктест.
2. **Хранение артефактов -- modeling_artifacts["forecasts"]** (уточнение
   к §5.9): spec предполагала modeling_pipeline["forecasts"], но
   modeling_pipeline -- dict[str, StageStatus] (статусы стадий).  Прогнозы
   хранятся по фактическому паттерну артефактов сессии (как model_cards);
   Redis-roundtrip покрыт тестом; инвалидация forecasts связана с
   инвалидацией model_cards во ВСЕХ четырёх точках очистки (не могли бы
   стать stale-ссылками на исчезнувшие карты) + сброс stages["forecasting"].
3. **Расширение классификации ci_method с 11 до 19 моделей** (уточнение
   к §4): spec перечисляла baseline+statsmodels+prophet/tbats; дерево
   (Tasks 127-130: квантильные интервалы) и нейро-четвёрка (Tasks 138-141:
   conformal/MQLoss с alpha-ручкой) появились позже и имеют СЕРТИФИЦИРОВАННЫЕ
   нативные интервалы.  Итоговая карта:
   - analytic: arima/auto_arima (get_forecast().summary_frame(alpha)),
     theta (prediction_intervals(steps, theta, alpha) -- другой API, §10.3);
   - parametric_simulation: ets/ets_damped (simulate + rng, §4.1a);
   - native_adapter: prophet/tbats (80%), tree_ml (90%), lstm/nbeats/nhits/tft
     (alpha-ручка);
   - empirical_oof_quantile: baselines (обязателен, §4.2).
   var/vecm/garch/egarch/deepar -- честный 422: comparison/selection валидируют
   objective=level_forecast, их Model Card недостижима (objective-изоляция
   cohort'ов); multi-objective прогнозы -- отдельная постановка.
4. **Alpha-политика (§5.2 + дисклоужер)**: нейро -- запрошенная alpha
   прокидывается в params с сертифицированным whitelist {0.01, 0.05, 0.10}
   (вне -- fail-closed 422); prophet/tbats/tree_ml -- ФИКСИРОВАННАЯ alpha
   адаптера (0.20/0.10), запрошенная НЕ подменяется другим методом -- интервал
   как есть + честный warning-дисклоужер (прецедент provenance Task 141);
   empirical/analytic/simulation -- любая alpha в (0,1), дефолт 0.05.
5. **Финальный рефит (§3)**: apps/api/final_fit.py::build_final_fit --
   forward-цепочка target-препроцессинга ОДИН раз на полной истории
   (переиспользование _resolve_chain/_make_scaler/_inverse_stationarity/
   apply_variance_transform/apply_smoothing_series из fold_preprocessing --
   НИ ОДНОЙ дублирующей формулы); fixed-lambda фиксируется, оценённая --
   переоценивается на полной истории (та же семантика, что у fold-препро-
   цессора на train-фолде); restore() вызывается ПО ОТДЕЛЬНОСТИ для точки
   и каждой границы интервала -- для log_difference интервал в исходной
   шкале асимметричен корректно (тест прижимает).  Необратимая цепочка
   (сглаживание, inverse_supported=False) и некаузальный smoother --
   честный 422.
6. **Паритет-гейт**: для analytic/simulation интервалы требуют объект
   фита -- модуль делает СОПРЯЖЁННЫЙ фит тем же классом модели/данными/
   параметрами (зеркало сертифицированных адаптеров) и прижимает честность
   гейтом: расхождение точки реестра и интервального фита (rtol 1e-6) --
   ForecastingError, а не молчаливая подмена источника прогноза.  Дрейф
   зеркала ловит гейт, а не пользователь.
7. **Эмпирический метод (§4.2)**: интервал = точка + квантиль OOF-остатков
   СВОЕГО horizon_step (остатки уже в исходной шкале -- инверсия не нужна);
   шаги за training.horizon -- квантиль последнего валидированного шага +
   честный warning «консервативная оценка... не валидирован эмпирически»;
   coverage (§4.3) -- in-sample доля OOF-точек в ретроспективных интервалах,
   заполняется ТОЛЬКО для эмпирического метода (интервалы других методов
   нельзя задним числом посчитать без переобучения на каждом train-фолде).
8. **Аномалии (§5.8)**: переиспользование detect_outlier_mask (Task 60, IQR)
   на объединении «история+прогноз»; флаг -- предупреждение, не запрет.
9. **TraceEvent -- общий контракт (рекомендация §10.4 ПРИНЯТА)**: НОВЫЙ
   apps/api/trace_events.py -- канонический датакласс + make_trace_event
   (fail-closed на неизвестном event_type); 4 типа событий этапа
   (forecast_generated/compared/sensitivity_computed/exported) пишутся в
   ForecastRun.trace_events (формат готов к будущему «Прогрессу» без
   миграции).  GET-экспорт фиксирует forecast_exported и переводит
   stages["forecasting"] в done (дефолт §10.5 по прецеденту Моделирования --
   derived-статус, без кнопки «Готово»); клиентский PNG -- POST /trace.
10. **Сравнение прогнозов (§5.6)**: сравниваются УЖЕ ПОСТРОЕННЫЕ артефакты
    (POST /compare {forecast_ids}, 2..4) с событием в каждом участнике --
    без скрытой регенерации и без нового ранжирования (ранжирование закрыто
    этапом Моделирования).  Спека предполагала генерацию по model_card_ids --
    отклонение в сторону честности: сравнение существующих прогнозов не
    дублирует фиты и сохраняет lineage каждого прогноза.
11. **Чувствительность (§5.7)**: веер по УГЛАМ param_space из
    rules/modeling.yaml ( ModelingSpec.get_model; по каждой оси
    первый/последний элемент списка значений -- без сортировки, значения
    категориальные), дедуплицированное произведение с потолком 8; params =
    card_hyperparams + combo; базовая трансформация истории общая (рефит
    только модели).  Пустой param_space -- честный 422; нейро --
    предупреждение о времени.
12. **Экспорт (§5.5)**: CSV (date,actual,forecast,ci_lower,ci_upper:
    история 96 + прогноз 2) и JSON (ForecastRun целиком, самодостаточен) --
    backend; PNG -- клиентская сериализация SVG (XMLSerializer -> canvas ->
    toBlob, scale 2, без новых зависимостей); **PDF сознательно НЕ
    реализован (уточнение к §5.5)**: jsPDF не содержит кириллических
    шрифтов -- текстовый PDF требует встраивания шрифта (~200+ КБ) и
    выбора лицензии; PDF-из-то-же-PNG ценности не добавляет.  Отдельная
    мелкая постановка.
13. **Freshness-гейты (lineage)**: fingerprint ряда обязан совпадать с
    card.data_summary.fingerprint (409 «Model Card устарела»); методы
    цепочки target-препроцессинга сессии обязаны совпадать с
    card.training.preprocessing.transformations (409 «цепочка расходится»);
    ensemble-карты -- честный 422 (прогноз ансамбля -- отдельная постановка).
14. **Frontend**: TsAnalysisForecasting.tsx -- 3-колоночный лейаут по
    принятому паттерну (левый: шапка+справка '?'+шаги этапа со StatusIcon+
    hand-off карты; центр: описание/справка с раскрыванием, честные гейты
    «Загрузите датасет»/«завершите Моделирование»/«сформируйте Model Card»
    со ссылкой, ForecastChart (факт + пунктирный прогноз + лента интервала
    Area + красные аномалии + ReferenceLine начала прогноза, h-468),
    ForecastAccuracyPanel (дисклоужер «по результатам бэктеста -- не
    точность этого прогноза», сетка метрик + честное «недоступно для этого
    метода» для coverage), предупреждения, веер, lineage-note; правый:
    селектор карт, горизонт (дефолт training.horizon), alpha {0.01,0.05,
    0.10}, кнопка прогноза, история с чекбоксами сравнения (до 3), кнопка
    сравнения, веер, ForecastExportMenu (CSV/JSON/PNG)).  lib/forecasting.ts
    -- типы 1:1 с ForecastRunResponse + человекочитаемые подписи ci_method/
    alpha_source.  Подкомпоненты -- самостоятельные файлы по манифесту §8.
15. **GET /card (список карт)** -- аддитивный сводный эндпоинт
    (card_id/model_id/model_name/selection_kind/horizon/fingerprint/
    created_at): существовал только POST /card и GET /card/{id} -- списка
    не было ни для прогнозирования, ни для UI вообще.

### TDD (RED -> GREEN)

- RED: tests/unit/test_forecasting_contract.py (13) +
  tests/unit/test_final_fit.py (14) + tests/unit/test_forecasting.py (17) +
  tests/api/test_forecasting_session.py (21) -- collection errors на
  отсутствии модулей/эндпоинтов (RED-first, прецедент Tasks 138-142).
  Поверхность ожиданий снята пробом ДО реализации:
  scripts/task_forecast1_interval_api_probe.py (ARIMA summary_frame;
  Theta prediction_intervals(steps, theta, alpha) -> DataFrame[lower,upper];
  ETS simulate(shape nsteps x reps, kwarg rng, anchor=end) -- random_state
  int устарел; нелинейная инверсия границ log_difference даёт асимметрию).
  Правки ОЖИДАНИЙ по снятой эмпирике: рецепты тестов -- фактические
  метаданные сессии (kind=smoothing/stationarity; seasonal_period >= 2 --
  гейт apply_stationarity_series); coverage на достаточной выборке
  (экстремальные квантили малой выборки исключают крайние точки).
- GREEN backend: 65/65 (44 unit + 21 api).  Контур: 2535 passed / 0 failed
  (2470 базлайн 30d00d4 + 65 новых -- арифметика сходится), нейро-тесты
  ИСПОЛНЯЛИСЬ (torch 2.14.0+cpu + neuralforecast 3.2.2 -- сертифицированная
  пара Tasks 137-142; окружение восстановлено из requirements.txt +
  apps/api/requirements.txt + requirements-dev.txt + нейро-группы +
  выравнивание сертификационной эпохи scipy==1.14.1/numpy==2.1.3/
  pandas==2.2.3/arch==7.2.0; pip check -- No broken requirements).
- GREEN frontend: 5 новых сюит (ForecastChart 4 / ForecastAccuracyPanel 5 /
  ForecastHistoryList 5 / TsAnalysisForecasting 9 / forecasting page 1) --
  полная регрессия 102 сюиты / 941 тест passed (было 97/914: +5 сюит /
  +27 тестов -- арифметика сходится).  typecheck:all -- 0 ошибок (обе
  оболочки); build:all -- Compiled successfully x2 (13/13 и 17/17 static
  pages), маршрут /forecasting в production-манифесте обеих оболочек.
- E2E-смоук scripts/task_forecast1_e2e_smoke.py: 41/41 проверок (полный
  путь до карты -> прогнозы обоих методов с паритет-гейтом -> предупреждение
  о горизонте -> история -> compare -> sensitivity 200/422 по param_space ->
  CSV/JSON экспорт + /trace PNG -> инвалидация прогнозов тюнингом ->
  отдельный ETS-проход симуляции).

### Верификация

- compileall OK; app-import OK (FastAPI); rules-smoketest exit=0;
  pip check -- No broken requirements.
- Прод-инварианты: точка прогноза -- только MODEL_EXECUTION_REGISTRY;
  ensemble/non-eligible -- 422; fingerprint-гейт -- 409; прогнозы --
  артефакты сессии (Redis-roundtrip тест); инвалидация -- синхронно с
  картами во всех 4 точках; forecast_exported завершает этап.
- Фронтенд: jest 102/941; typecheck:all 0 ошибок; build:all успешно
  (обе оболочки, /forecasting в манифестах).

### Границы Task FORECAST-1 (что осознанно НЕ сделано)

- PDF-экспорт (§5.5) -- осознанно отложен: кириллические шрифты jsPDF
  (встраивание ~200+ КБ, лицензия шрифта) -- отдельная мелкая постановка.
- Прогноз ensemble-карт, multi-objective прогнозы (var/vecm/garch/egarch/
  deepar -- их карты недостижимы из comparison) -- отдельные постановки;
  честный 422 с объяснением.
- Exogenous-канал прогноза (future-known regressors в финальном прогнозе
  supervised/Prophet) -- вне среза: финальный рефит исполняет univariate
  target-путь; регрессорный канал -- отдельная постановка (прецедент
  lstm: supports_future_features декларируется своим срезом).
- Backend-персистентность панели «Прогресс» (research_runs/trace_events)
  -- владелец: команда «Прогресса» (§9.4); ForecastRun.trace_events уже
  совместим по формату (apps/api/trace_events.py -- общий контракт §10.4).
- StepperNextModuleButton «Перейти к Задачам» на вкладке НЕ добавлялся:
  прогнозирование -- workspace, а не степпер; естественное продолжение
  (хаб /tasks потребляет forecast_run) доступно из главного меню.
- Исторические записи журнала НЕ редактировались (append-only).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@30d00d4 + перечисленные изменения.

### Кандидат-нахождки (не блокирующие, к следующему касанию)

- spec_forecasting2.md §7 ForecastRun не содержит history; реализация
  хранит историю (labels/values/source_column) в артефакте -- CSV-экспорт
  и самодостаточность JSON (§5.5) становятся устойчивыми к смене сессии.
  При появлении формального клиента «Прогресса» вынести history в схему.
- Тюнинг-сетки частных моделей (neural @ max_steps 300) делают веер
  чувствительности по нейро-картам долгим на слабых инстансах (warning
  в ответе есть); если станет продуктивной болью -- вынести в job-контур
  (прецедент Task 104/123 start/step).

Изменённые/новые файлы (ZIP: download/task_forecast1_forecasting_module.zip):
- НОВЫЕ backend: apps/api/{trace_events,forecasting_contract,final_fit,
  forecasting}.py, apps/api/routers/forecasting_session.py,
  tests/unit/{test_forecasting_contract,test_final_fit,test_forecasting}.py,
  tests/api/test_forecasting_session.py,
  scripts/task_forecast1_interval_api_probe.py,
  scripts/task_forecast1_e2e_smoke.py
- НОВЫЕ frontend: packages/ui/lib/forecasting.ts,
  packages/ui/components/{ForecastChart,ForecastAccuracyPanel,
  ForecastHistoryList,ForecastExportMenu,TsAnalysisForecasting}.tsx,
  packages/ui/components/{ForecastChart,ForecastAccuracyPanel,
  ForecastHistoryList,TsAnalysisForecasting}.test.tsx,
  apps/standalone/app/forecasting/page.test.tsx
- ИЗМЕНЁННЫЕ: apps/api/main.py (роутер), apps/api/schemas.py
  (ForecastRunResponse и др.), apps/api/routers/modeling_session.py
  (GET /card список, _invalidate_forecasts в 4 точках очистки карт),
  packages/ui/index.ts (экспорты), apps/standalone/app/forecasting/page.tsx
  (ModulePlaceholder -> TsAnalysisForecasting), worklog5.md (этот журнал)

---

## Task PREPR-1 -- Вкладка «Предобработка»: зелёная подсветка пройденных остановок степпера (паттерн вкладки «Моделирования»)

Дата: 2026-09-14. Синхронизация: main@d553345; рабочее дерево содержит
незакоммиченные изменения Task w/n-5 (Modeling), Task EDA-2 (EDA) и
этот журнал -- задача PREPR-1 выполнялась ПОВЕРХ них, файлы
Modeling/EDA не затронуты. Постановка тимлида: применить тот же
паттерн «зелёная подсветка пройденных остановок степпера (паттерн
вкладки «Моделирование»)» к вкладке «Предобработка». Полный цикл
AGENTS.md: TDD RED->GREEN, полная frontend-регрессия, typecheck/build
обеих оболочек.

### Дизайн (эталон и точка изменения)

- ЭТАЛОН: TsAnalysisModeling.tsx (степпер 11 стадий; строки 969-975);
  уже применён к «Разведочному EDA» в Task EDA-2 -- тернарная цепочка
  className: (1) active: «bg-brand text-white border-brand» -> (2) done:
  «bg-green-50 border-green-200 text-green-800» -> (3) иначе: «bg-white
  border-neutral-200 hover:bg-neutral-50 text-neutral-800».
- ТОЧКА ИЗМЕНЕНИЯ: TsAnalysisPreprocessing.tsx, степпер 10
  преобразований в ЛЕВОЙ колонке (комментарий «Степпер: прямоугольные
  карточки с текстом + иконка», строки 1146-1166 до правки): у кнопки
  была ДВУХветочная цепочка (active / иначе) -- ветка done
  ОТСУТСТВОВАЛА, пройденные остановки выглядели как непройденные
  (bg-white).
- Геометрия text-sm совпадает с EDA (в Modeling text-xs) -- существующее
  различие, в паттерн (цвет фона/рамки/текста) не входит, не тронуто.

### Оценка рисков и решения

1. Порядок веток сохранён КАК В ЭТАЛОНЕ: active-ветка ПЕРВАЯ => активная
   остановка со статусом done остаётся индиго. Гардируем тестом
   (active+done: клик по «Регулярности ряда» после загрузки done-профиля;
   повторного запроса при клике НЕТ -- зависимости useEffect не включают
   activeCheckId, статус остаётся done).
2. 10 остановок имеют 6 статусов CheckStatus (done/warning/pending/
   skipped/running/error); статус может приходить ИЗ БЭКЕНДА напрямую
   (variance/smoothing/stationarity/spectral/featureGeneration/scaling --
   profile.status). Подсветка ТОЛЬКО при done -- все прочие статусы не
   окрашиваются, включая бэкенд-«warning»/«skipped». Гардируем 3 кейсами.
3. Правая колонка «Панель управления» (orderedChecks, карточки-статьи) и
   панель «Паспорт свойств ряда» -- НЕ степпер; вне мандата, не тронуты.
4. Иконка StatusIcon уже зелёная для done -- не тронута.
5. Классы green-50/green-200/green-800 -- стандартная палитра Tailwind,
   уже в бандле (Modeling, бейджи): риск purge-потери исключён.

### TDD (RED -> GREEN)

- RED: 5 новых кейсов в TsAnalysisPreprocessing.test.tsx (новая сюита
  «зелёная подсветка пройденных остановок степпера (паттерн
  Моделирования)»): (1) done+неактивная («Регулярность ряда», mount-загрузка
  done по дефолтному моку; сигнал готовности -- accessible name
  /Пройдено/) -> bg-green-50/border-green-200/text-green-800, соседняя
  pending («Генерация признаков») -> bg-white без green; (2) active+done ->
  приоритет индиго (bg-brand, БЕЗ green); (3) running+pending (вечнозависающий
  fetch; «Пропуски» initial loading=true) -> без окраски; (4) warning
  (дефолтный MISSING_PROFILE.status="warning", сигнал /Найдены проблемы/) ->
  без окраски; (5) skipped (оверрайд regularity-профиля status:"skipped",
  сигнал /Не требуется/) -> без окраски. Результат RED: ровно ОДИН падёж --
  кейс (1): done-кнопка остаётся «bg-white border-neutral-200
  text-neutral-800»; гарды (2)-(5) проходят ДО правки.
- GREEN: правка компонента -> 51/51 в файле (46 базлайн + 5 новых).

### Верификация

- Полная frontend-регрессия: **102 сюиты / 971 passed / 0 failed**
  (базлайн после Task EDA-2 -- 102/966; +5 новых -- арифметика сходится;
  регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 embedded,
  17/17 standalone).
- Backend не затронут (0 файлов .py); правка применяется в ОБЕИХ
  оболочках через общий компонент packages/ui (прецедент Task w/n:
  форков нет).

### Границы Task PREPR-1 (что осознанно НЕ сделано)

- Иконки статусов, правая колонка, паспортная панель, остальные вкладки
  (Валидация/Загрузка имеют СВОИ степперы и не входят в постановку) --
  не тронуты.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@d553345 + изменения Task w/n-5, Task EDA-2, Task PREPR-1.

Изменённые/новые файлы (ZIP: download/task_prepr1_preprocessing_stepper_green_pattern.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisPreprocessing.tsx
  (добавлена ветка done в className степпер-кнопки: «bg-green-50
  border-green-200 text-green-800» + комментарий паттерна),
  packages/ui/components/TsAnalysisPreprocessing.test.tsx (+5 кейсов:
  подсветка done, индиго-приоритет active+done, гарды
  running/pending/warning/skipped), worklog/worklog5.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task FORECAST-1a: Проверка находок аудитора (верификация, не доверие):

- F-1 (P1) — подтверждена: на statsmodels 0.14.5 воспроизведён сырой TypeError → 500 вместо 422 + 3 RED теста. Исправлено: пол >=0.15.0 в обоих requirements (вариант по рекомендации аудита) + defense-in-depth — перехват TypeError → честный ForecastingError (проверено на 0.14.5: honest_fail_closed=True → 422)
- F-2 — опровергнута: мутант MUT-15 убивается существующим JSON-тестом (stages=="done"); «ORACLE-ONLY» — артефакт атрибуции раннера аудитора (гнал один приписанный тест вместо файла). Опровержение зафиксировано в worklog
- F-3 — подтверждена: написаны 3 оракула-убийцы (паритет-инъекция ×1.01, симметрия веера на 3000 траекторий с 5-кратным запасом допуска, точный состав 8 углов) — все 4 бывших «ORACLE-ONLY» мутанта теперь убиты слоем тестов репозитория
- F-4 — подтверждена количественно (11.8%@500 → 3.2%@3000), дефолт сохранён, ручка выведена
Верификация: полная регрессия одним проходом 2539/0/0 (нейро-стек исполнялся), арифметика 2535+4 сходится; мутации, compileall, app-import, rules-smoketest — OK. Коммит/пуш не выполнялись.
