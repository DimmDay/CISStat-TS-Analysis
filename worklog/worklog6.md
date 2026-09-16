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

---

## Task VALID-1: Паттерн зелёной подсветки пройденных остановок перенесён на степпер «Валидации» (10 DQ-проверок):

Точка изменения: TsAnalysisValidation.tsx — ветка done → bg-green-50 border-green-200 text-green-800, байт-в-байт эталон. Учтена специфика: бейджи «Отключено»/«Настроить»/«Нет эталона» и displayedStatus не влияют на окраску — красится строго status === "done"; активная остановка сохраняет индиго.
TDD: 5 кейсов (подсветка done, индиго-приоритет active+done, гарды warning/skipped/needs_rule), RED — ровно один падёж → GREEN 38/38.
Ценный урок задокументирован в worklog6.md: тесты этого файла требуют связку mockActiveValidation + ожидание через findBy*/findAllBy* (asyncAct-промывка React 18 + RTL 16 + jest 30); минимальный мок и waitFor-колбэки дают недетерминированную промывку.
Верификация: 102 сюиты / 975 passed / 0 failed (970 + 5), typecheck 0 ошибок, build 13/13 + 17/17.

---

## Task UPLOAD-1: Паттерн зелёной подсветки пройденных остановок перенесён на степпер «Загрузки» (5 остановок) — сквозная унификация завершена:

Дата: 2026-09-15. Синхронизация: main@7b4ac02, рабочее дерево чистое до
правки. Постановка тимлида: «Последний степпер пайплайна без паттерна —
"Загрузка". Закрой сквозную унификацию». Полный цикл AGENTS.md: TDD
RED->GREEN, полная frontend-регрессия, typecheck/build обеих оболочек.

### Дизайн (эталон и точка изменения)

- ЭТАЛОН: TsAnalysisModeling.tsx (степпер 11 стадий, строки 969-975);
  паттерн уже применён ко ВСЕМ вкладкам пайплайна: Validation
  (VALID-1, строка 804-810), Preprocessing (PREPR-1, строка 1163),
  EDA (EDA-2, строка 1424). Тернарная цепочка className: (1) active:
  «bg-brand text-white border-brand» -> (2) done: «bg-green-50
  border-green-200 text-green-800» -> (3) иначе: «bg-white
  border-neutral-200 hover:bg-neutral-50 text-neutral-800».
- ТОЧКА ИЗМЕНЕНИЯ: TsAnalysisUpload.tsx, степпер 5 остановок
  (overview/chart/distribution/structure/quality) в ЛЕВОЙ колонке
  (блок STOPS.map, строки 943-957 до правки): у кнопки была
  ДВУХветочная цепочка (active / иначе) -- ветка done ОТСУТСТВОВАЛА,
  пройденные остановки выглядели как непройденные (bg-white).
- Геометрия text-sm совпадает с Validation/Preprocessing/EDA
  (в Modeling text-xs) -- существующее различие, в паттерн (цвет
  фона/рамки/текста) не входит, не тронуто.

### Оценка рисков и решения

1. Порядок веток сохранён КАК В ЭТАЛОНЕ: active-ветка ПЕРВАЯ =>
   активная остановка со статусом done остаётся индиго. Гардируем
   двумя кейсами: active+done по умолчанию («Превью датасета» при
   parse_warnings=[]) и active+done после клика («Распределение»
   в кейсе parse_warnings).
2. СПЕЦИФИКА Upload (отличие от VALID-1): stopStatus физически
   производит ТОЛЬКО три статуса -- pending/warning/done (путей
   skipped/running/error в этом степпере нет; бейджей «Отключено»/
   «Настроить»/«Нет эталона» нет -- кнопка простая: label +
   StatusIcon). Пути warning: (a) Качество (пропуски/выбросы/
   дубликаты), (b) Превью при parse_warnings>0, (c) Структура
   (confidence<70). Пути pending: Качество без quality в ответе
   бэкенда; до загрузки степпер не отрисован. Гардируем: warning
   x2 (Качество активно+неактивно; Превью/parse_warnings) +
   pending (Качество без quality).
3. Детерминированность (урок VALID-1 о промывке asyncAct): статусы
   chart/structure зависят от АСИНХРОННОЙ /dataset/structure-detection,
   поэтому все кейсы строятся на статусах, вычисляемых СИНХРОННО из
   uploadResponse (Распределение -- done при numericCols>0; Превью --
   done/warning по parse_warnings; Качество -- done/warning/pending
   по quality). Готовность рендера -- findByText (asyncAct-промывка
   React 18 + RTL 16 + jest 30).
4. Мок ответа upload без quality безопасен: все использования
   uploadData.quality в компоненте либо optional-chained
   (stopStatus), либо под guard activeStop==="quality" (в кейсах
   остановка «Качество» не активируется).
5. Иконка StatusIcon уже зелёная для done (text-green-600) и
   существует независимо от подсветки -- не тронута.
6. Классы green-50/green-200/green-800 -- стандартная палитра
   Tailwind, уже в бандле (4 вкладки используют) -- риск
   purge-потери исключён.
7. Правая колонка (Панель управления), центральная (Описание+Обзор),
   паспортная панель, кнопка StepperNextModuleButton «Перейти к
   валидации» -- НЕ степпер; вне мандата, не тронуты.

### TDD (RED -> GREEN)

- RED: 5 кейсов в TsAnalysisUpload.test.tsx (новая сюита «зелёная
  подсветка пройденных остановок степпера (паттерн Моделирования)»):
  (1) done+неактивная («Распределение», numericCols>0 -- синхронно из
  uploadResponse) -> bg-green-50/border-green-200/text-green-800,
  соседняя warning («Качество», cols_with_missing=1) -> bg-white без
  green-классов; (2) active+done по умолчанию («Превью датасета»,
  parse_warnings=[]) -> приоритет индиго (bg-brand, БЕЗ green);
  (3) warning («Качество») в обоих состояниях: активная warning ->
  индиго (active-ветка первее warning), неактивная (после клика на
  «Распределение») -> без окраски; (4) pending (ответ upload без
  quality) -> без окраски; (5) второй путь warning (parse_warnings>0
  -> «Превью» warning): клик на «Распределение» -> активная done
  индиго, «Превью» неактивная warning -> без окраски. Результат RED:
  ровно ОДИН падёж -- кейс (1): done-кнопка остаётся «bg-white
  border-neutral-200 text-neutral-800» (паттерн отсутствует); гарды
  (2)-(5) проходят ДО правки.
- GREEN: правка компонента -> 31/31 в файле (26 базлайн + 5 новых).

### Верификация

- Полная frontend-регрессия: **102 сюиты / 980 passed / 0 failed**
  (базлайн после Task VALID-1 -- 102/975; +5 новых -- арифметика
  сходится; регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 embedded,
  17/17 standalone).
- Backend не затронут (0 файлов .py); правка применяется в ОБЕИХ
  оболочках через общий компонент packages/ui (прецедент Task w/n:
  форков нет).

### Границы Task UPLOAD-1 (что осознанно НЕ сделано)

- Иконки статусов, правая колонка, паспортная панель, центральная
  колонка -- не тронуты.
- Статусы chart/structure (асинхронная детекция) в тесты не
  вовлекались сознательно -- детерминированность выше покрытия
  ещё одного пути того же статуса (done/warning уже покрыты
  синхронными путями).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@7b4ac02 + изменения Task UPLOAD-1.

### Итог сквозной унификации (цепочка EDA-2 -> PREPR-1 -> VALID-1 -> UPLOAD-1)

Паттерн «зелёная подсветка пройденных остановок степпера (паттерн
вкладки "Моделирование")» теперь применён ко ВСЕМ четырём вкладкам
пайплайна со степпером: Загрузка (5 остановок), Валидация (10
DQ-проверок), Предобработка (10 преобразований), Разведочный EDA
(10 исследований) + исходный эталон Моделирование (11 стадий).
Единый контракт: active -> индиго; done -> светло-зелёный; прочие
статусы -> без окраски. Сквозная унификация ЗАВЕРШЕНА.

Изменённые/новые файлы (ZIP: download/task_upload1_upload_stepper_green_pattern.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisUpload.tsx
  (добавлена ветка done в className степпер-кнопки: «bg-green-50
  border-green-200 text-green-800» + комментарий паттерна),
  packages/ui/components/TsAnalysisUpload.test.tsx (+5 кейсов:
  подсветка done, индиго-приоритет active+done x2, гарды
  warning x2 [качество, parse_warnings] /pending).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task IA-1 certification (audit) -- независимый аудит хаба «Задачи» /tasks (7b4ac02)

Дата: 2026-09-15.  Синхронизация: main@7b4ac02 (Task IA-1 = 6581c98 --
предок HEAD, ревизия аудита свежая: IA-1 -> 142a -> spec_education ->
PRE-1 -> EDA-1 -> 143 -> w/n-3 -> w/n-4 -> FORECAST-1 -> MODEL-1 ->
FORECAST-1 cert -> 4c0ed25 -> EDA-2 -> PREPR-1 -> FORECAST-1a -> VALID-1 ->
7b4ac02; производственный код Task IA-1 после 6581c98 НИКЕМ не менялся --
проверено `git log --oneline 6581c98..7b4ac02 -- packages/ui/lib/task-stops.ts
packages/ui/components/TaskCard.tsx packages/ui/components/TasksHub.tsx`
= 0 коммитов). Постановка тимлида: разведка кода + честная сертификация
Task IA-1, верификация комментариев тимлида, мутационные и оракул тесты
на своих данных, рекомендации по развитию модуля (UI/UX).

### Разведка кода (что проверено глазами)

- `packages/ui/lib/task-stops.ts` (150 строк): реестр TASK_ROUTES (4 задачи
  v1), слой артефактов ARTIFACT_STAGE/artifactsFromStages, чистая логика
  deriveTaskGateState/taskGateReason. Зависимостей от DOM/сети нет -- вся
  гейтинг-логика чистая и детерминированная, что сделало возможным
  исчерпывающий оракул (ниже).
- `packages/ui/components/TaskCard.tsx` (112 строк): трёхсостояновая
  карточка; available -- `<Link href={task.href}>` c фокус-рингом,
  awaiting/blocked -- `<div role="group">` с aria-label «Задача «X»
  недоступна: причина». Ссылочные классы available-состояния ПОБАЙТОВО
  совпадают с RouteCard.tsx:16 (rounded-xl, border-brand/60,
  bg-brand-light/60, hover-усиление, focus-visible ring) -- сверено diff'ом
  строк классов, не по памяти.
- `packages/ui/components/TasksHub.tsx` (74 строки): шапка + сетка
  `grid-cols-1 sm:2 lg:3 gap-5 px-6` -- геометрия идентична
  HomeHero.tsx:38 и HomeCapabilities.tsx:218 (единая DNA карточных сеток).
  Источник сессии -- useAppShell().stages c защитой `stages ?? {}`.
- STAGE_DEFS/StageStatus НЕ задублированы: task-stops.ts импортирует их из
  ./stages; локальных определений этапов нет (grep). Реестр живёт отдельно
  от home-stops/navigator-stops -- основание честное.
- Потребители task-stops: только TasksHub/TaskCard/index.ts -- наружных
  связей нет, риск регрессии локализован.

### Верификация утверждений тимлида (проверка, не доверие)

1. Три ссылки на ARCHITECTURE.md -- ПОДТВЕРЖДЕНЫ на 7b4ac02:
   ~155 (XAI: SHAP/PDP/IRF/FEVD -> «Задачи»), ~375 (матрица доступа:
   «Задачи | все стадии»), ~1382 (mts_results: IRF/FEVD/Грейнджер --
   движок What-if/Shock Propagation для «Задач»). Обоснование спеки §2
   опирается на реальный текст архитектуры, не постфактум.
2. Гейтинг по контракту входа -- ПОДТВЕРЖДЁН: «Сценарии»/«Причины»
   доступны при modeling=done без forecasting (оракул-инвариант O8 на всех
   729 комбинациях стадий + тест TasksHub «after Modeling»).
3. Переиспользование -- ПОДТВЕРЖДЕНО: см. разведку (STAGE_DEFS без дублей,
   DNA RouteCard побайтово, некликабельные -- настоящий div role=group,
   не задизейбленная ссылка).
4. Тесты/сборка -- ПОДТВЕРЖДЕНЫ: модуль 24/24 (task-stops 17 + TasksHub 6 +
   page 1); полная регрессия 102 сюиты / 975 тестов PASSED (у тимлида 960 --
   счётчик тестов вырос вперёд на +15 из-за более поздних срезов в диапазоне
   до 7b4ac02; число сюит 102 совпадает точно); typecheck:all -- 0 ошибок;
   npm run build -- успешно, маршруты /tasks + 4 плейсхолдера в
   production-манифесте, все статичные. Бонусный кейс сверх §8
   (частичный пайплайн validation-only: awaiting, не blocked) --
   в TasksHub.test.tsx присутствует.
5. §8 критерии приёмки -- все три сценария покрыты тестами дословно и
   воспроизведены оракулом (O9a/O9b/O9c).

### Мутационное тестирование (аудиторские мутанты, свой раннер)

scripts/cert_ia1_mutations.py: 14 текстовых мутантов над
task-stops.ts/TaskCard.tsx, защита -- 24 теста модуля; файлы
восстанавливаются, sha256 сверяется. Итог: **12 KILLED / 2 SURVIVED**.

- УБИТЫ (защита работает): always-available гейт (M1), недостижимость
  awaiting (M2) и blocked (M3), артефакт на in_progress (M4), инверсия
  существования (M5), some->every в pipelineStarted (M6), срыв human-label
  в причине (M8), неверный этап-владелец model_card (M9), ослабление
  контракта decisions (M10), role=group->note (M11), неверный href (M12),
  срыв aria-причины (M14).
- **ВЫЖИЛИ (находки аудита):**
  - M7: удаление pipeline-order сортировки firstMissing в taskGateReason --
    для всех контрактов v1 (длина requires = 1) сортировка МЁРТВЫЙ КОД,
    ни один тест не различает порядок. Риск: v2/мультиартефактные контракты
    (например requires: ["validated","forecast_run"]) впервые исполнят эту
    ветку в проде без единого теста.
  - M13: text-base -> text-lg в заголовке TaskCard -- выжил: спека §8
    требует «заголовок text-base, описание text-sm», но TasksHub.test.tsx
    проверяет из DNA только rounded-xl/border-brand/60; типографика
    нигде не защищена. Прямое следствие отсутствия unit-теста TaskCard
    (находка тимлида #4 подтверждена мутантом).

### Оракул-тесты на своих данных (исчерпывающий перебор)

packages/ui/lib/__ia1_oracle_cert.test.ts (временный файл аудита, после
прогона удалён из дерева; копия -- scripts/cert_ia1_oracle.test.ts.bak):
**11/11 PASS**. Свои данные: полная энумерация 3^6 = 729 комбинаций
статусов шести стадий (не фикстуры исполнителя) + независимая
ре-имплементация слоя артефактов и гейтинга в оракуле. Инварианты:
O1 available <=> requires подмножество артефактов; O2 awaiting/blocked
через pipelineStarted; O3 reason null <=> available; O4 awaiting-причина
называет этап-владельца ПЕРВОГО недостающего артефакта (рекомпьют оракулом,
raw-ключ не протекает); O5 blocked-причина указывает на Загрузку;
O6 монотонность (повышение статуса стадии никогда не деградирует состояние);
O7 детерминизм; O8 семантика v1-реестра; O9 сценарии §8; O10 мина
«validated» (ниже); O11 upload-only сессия. Ноль контрпримеров --
контракт хаба держится на всём пространстве входов.

### Верификация находок тимлида (все пять)

1. **validated-мина -- ПОДТВЕРЖДЕНА кодом и оракулом.** grep по всем
   присвоениям: stages["upload"]=done (session_store.py:273, автоматически
   в set_dataset), set_stage("modeling","done") (modeling_session.py:3258),
   stages["forecasting"] (forecasting_session.py:182/339/862);
   validation/preprocessing/eda НЕ выставляет никто; docstring эндпоинта
   POST /v1/session/stage/{stage} (session.py:4184) это прямо признаёт.
   Оракул O10 формализует: гипотетическая задача requires:["validated"]
   при реальном бэке навсегда awaiting с обещанием «после этапа
   Валидация», которое бэкенд не исполнит. Согласен: для v1 не баг
   (ни одна задача не требует validated), но ПРЕДИСЛОВИЕ ДЛЯ РЕЕСТРА
   обязательно -- зафиксировано в рекомендациях R6.
2. **blocked почти недостижим -- ПОДТВЕРЖДЕНО** (O11: upload=done уже
   делает pipelineStarted=true; blocked виден только до первой загрузки
   файла). Это осознанное следствие автоматизма set_dataset, не дефект;
   продуктовое ожидание зафиксировано в рекомендациях R7.
3. **Нет отдельного аудит-коммита -- ПОДТВЕРЖДЕНО** (у IA-1 один коммит
   6581c98; у 143/FORECAST-1 аудит-проходы отдельными коммитами). Настоящая
   запись закрывает гэп на уровне журнала; решение о коммите -- за тимлидом
   (AGENTS.md запрещает мне пуш).
4. **TaskCard без своего unit-теста -- ПОДТВЕРЖДЕНО** + усилено мутантом
   M13 (типографическая часть DNA не защищена даже косвенно).
5. **Честная вырезка v2 (recommendedWith) -- ПОДТВЕРЖДЕНО**: спека §7
   декларирует openly, тесты и код не содержат скрытых следов; для v1
   приемлемо, но рекомендация R2 переводит её в явный план.

### Собственные находки аудита (сверх списка тимлида)

- **F-IA1-6 (copy/a11y, minor):** aria-label списка карточек -- «Задачи
  на основе прогноза» (TasksHub.tsx:52) -- противоречит центральному
  решению самой спеки §2 («зависимость от прогноза НЕ глобальная»: 2 из
  4 задач от model_card). Скринридер-пользователь получает заголовок
  семантики «всё от прогноза», который спека отвергла. Видимый H1 корректен;
  правка одной строки.
- **F-IA1-7 (latent, minor):** M7 -- недетерминированность порядка при
  мультиартефактном контракте не протестирована (см. выше); плюс сама
  ветка sort()[0]-альтернативы выжила бы только до v2.
- Оба -- minor, блокирующих дефектов НЕ найдено.

### ВЕРДИКТ СЕРТИФИКАЦИИ

**Task IA-1 -- СЕРТИФИЦИРОВАНА (passed with remarks).**
Проектирование: IA-решение обосновано реальными узлами архитектуры
(ARCHITECTURE.md 155/375/1382), контракт входа формализуем и формализован,
рост без перепроектирования (эшелоны §6). Реализация: чистая логика
гейтинга корректна на ВСЕХ 729 входах, визуальная DNA переносится
побайтово, а11y-решения осознанные (role=group вместо ложного аффорданса).
TDD-цикл соблюдён (RED подтверждён в журнале исполнителя, 24/24 GREEN,
+бонусный кейс). Замечания: 2 минорных кодовых (F-IA1-6/F-IA1-7),
1 тестовый гэп (TaskCard unit + мультиартефактный порядок), 1 предусловие
реестра (validated-мина), 1 процессная асимметрия (нет аудит-коммита).
Ни одно не блокирует v1 и не требует немедленного фикса, кроме
задокументированного предусловия для будущих задач реестра.

### Рекомендации по развитию модуля «Задачи» (UI/UX)

- **R1 (quick win, a11y/copy):** заменить aria-label списка на
  «Задачи поверх пайплайна» (или «Задачи платформы») -- убрать
  прогнозоцентричную формулировку из семантики хаба; одна строка + правка
  одного теста.
- **R2 (v2-гигиена):** подсказка «рекомендуемый артефакт» для «Сценариев»
  (recommendedWith из §2/§7): третья плашка-призрак «лучше с прогнозом»
  на карточке в состоянии available, не гейтит клик. Закрывает честно
  вырезанный scope и снимает вопрос тимлида о приемлемости для v1.
- **R3 (unit-защита DNA):** компактный TaskCard.test.tsx: три состояния
  x (роль, href/нет href, класс-маппинг SHELL/ICON/CHIP, text-base/text-sm)
  -- убивает мутантов класса M13/M14 на уровне самого компонента и снимает
  находку #4 тимлида.
- **R4 (тест на мультиартефактный порядок):** кейс taskGateReason
  с requires: ["validated","forecast_run"] при artifacts=["validated"] --
  ожидаемая причина «…после этапа Прогнозирование» -- оживляет сортировку
  (M7) ДО появления первого мультиартефактного контракта.
- **R5 (жизнь хаба):** в awaiting-плашку добавить микро-CTA «Перейти к этапу
  {Label}» (ссылка на STAGE_DEFS.href) -- сейчас причина сообщает этап
  текстом, но не даёт движения; это естественное продолжение паттерна
  цепочки PRE-1/EDA-1/MODEL-1 уже внутри хаба.
- **R6 (предусловие реестра, процессное):** в spec_tasks_ia.md §5 добавить
  явное предусловие: «задача с requires, содержащим validated, НЕ может
  быть добавлена в реестр до подключения выставления stages.validation
  роутером валидации» -- превращает найденную мину в правило входа.
- **R7 (продуктовое ожидание blocked):** зафиксировать, что blocked -- это
  состояние «до первой загрузки файла», и его стоит использовать как
  онбординг-подсказку (иллюстрация артефактной модели), а не как рабочий
  сценарий; текущая нейтральная плашка для этого уже подходит.
- **R8 (порог 9–15 задач):** при движении к эшелону 2 (§6) первыми
  категоризировать не карточки, а href-пространство (/tasks/scenarios/...),
  чтобы секции хаба не ломали URL уже выпущенных задач.

Изменённые/новые файлы (ZIP: download/task_ia1_certification_audit.zip):
- ИЗМЕНЁННЫЕ: worklog/worklog5.md (эта запись).
- ВНЕ ДЕРЕВА (аудиторские скрипты): scripts/cert_ia1_mutations.py,
  scripts/cert_ia1_oracle.test.ts.bak (в репозиторий не входят).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

## Task IA-1/R2-R5 -- Хаб «Задачи»: подсказка рекомендуемого артефакта (R2), unit-защита TaskCard (R3), мультиартефактный порядок (R4), микро-CTA в awaiting (R5)

Дата: 2026-09-15.  Синхронизация: main@bbd04f8 (запись сертификации IA-1
перенесена тимлидом в worklog6.md; производственные файлы IA-1 не менялись
с 6581c98 -- sha256 task-stops.ts/TaskCard.tsx совпали с baseline аудита).
Постановка тимлида: R1 закрыт решением («де-факто заголовок/подзаголовок
хаба корректны, копию не трогаем»); реализовать R2-R5 из рекомендаций
сертификации IA-1. Полный цикл AGENTS.md: TDD (RED подтверждён), GREEN,
регрессия, typecheck, build.

### Что реализовано

- **R2 (recommendedWith, spec_tasks_ia.md §2/§7):** `TaskRoute.recommendedWith?`
  (опционально; только «Сценарии» = ["forecast_run"]) + чистая
  `taskRecommendedHint(recommended, artifacts)` -> «Рекомендуется также
  этап Прогнозирование». Рендер: плашка-призрак на ДОСТУПНОЙ карточке
  (пунктирная brand-рамка, Sparkles, text-xs) — совет, НЕ турникет:
  не гейтит клик и исчезает, когда артефакт создан. Вырезанный в v1
  scope (§7) закрыт без расширения контракта состояний.
- **R3 (unit-защита TaskCard):** НОВЫЙ packages/ui/components/TaskCard.test.tsx
  (12 кейсов): три состояния × (роль link/group, href, класс-маппинг
  SHELL/ICON/CHIP, aria-label, Lock/Sparkles/ArrowRight), типографическая
  DNA (text-base/text-sm, и запрет text-lg) на уровне компонента.
  Убивает мутантов M13/M14 на самом компоненте (находка #4 сертификации).
- **R4 (мультиартефактный порядок):** 5 кейсов в task-stops.test.ts,
  включая контракт, объявленный ЗАДOM НАПЕРЁД (["forecast_run","model_card"]
  при artifacts=["validated"] -> причина «…Моделирование», НЕ
  «…Прогнозирование») — оживляет сортировку «первого недостающего» ДО
  появления первого мультиартефактного контракта в реестре (мутант M7);
  отдельно зафиксировано: present-артефакты закрывают свою часть
  мультиартефактного контракта.
- **R5 (микро-CTA):** чистая `awaitStageInfo(requires, artifacts,
  pipelineStarted)` -> StagePointer {key,label} — ЕДИНЫЙ источник истины
  для текста причины и цели CTA (taskGateReason отрефакторен на неё,
  строки причин сохранены байт-в-байт). Рендер: в awaiting-карточке под
  amber-плашкой ссылка «Перейти к этапу {Label}» (ArrowRight, text-brand,
  focus-ring) на STAGE_DEFS.href. НЕ противоречит защите от ложного
  аффорданса: CTA ведёт на РЕАЛИЗОВАННЫЙ этап пайплайна и помечен явно.
  blocked-карточки CTA не получают (scope: awaiting; симметричное
  расширение на blocked — тривиальный follow-up вне этой задачи).
- Экспорты @cisstat/ui: + awaitStageInfo, taskRecommendedHint (значения),
  + StagePointer (тип).

### Риски и их закрытие

- Изменение DOM-контракта ссылок хаба (awaiting теперь содержит 1 CTA-ссылку):
  критерий §8 «свежая сессия — ни одной ссылки» СОХРАНЁН (blocked без CTA,
  0 ссылок); тесты переведены на фильтр 'a[href^="/tasks/"]' для задачных
  ссылок + явные проверки CTA (после Моделирования: 2 задач + 2 CTA =
  4; частичный пайплайн: 0 задач + 4 CTA; полный: 4 задач, CTA нет).
- Срыв текстов причин при рефакторинге taskGateReason: строки зафиксированы
  существующими тестами — не изменились.
- A11y: ссылка внутри div role=group валидна (group не интерактивен);
  aria-label группы сохранён; CTA имеет собственное имя; иконки aria-hidden.
- Обратная совместимость: новые пропсы TaskCard опциональны;
  recommendedWith опционален; потребители вне хаба отсутствуют.

### TDD

- RED: task-stops.test.ts (срыв компиляции на отсутствующих экспортах),
  TaskCard.test.tsx (suite failed to run — пропсов нет), TasksHub.test.tsx
  (2 падения на CTA/подсказке) — подтверждён ДО реализации.
- GREEN: модуль 48/48 (task-stops 29 + TaskCard 12 + TasksHub 6 + page 1;
  было 24 — рост за счёт R3/R4 и юнитов R2/R5).

### Верификация

- Полная frontend-регрессия: **103 сюиты / 1004 passed / 0 failed**
  (базлайн bbd04f8 замерен точно: 102/980; арифметика: 980 + 24 новых
  теста [task-stops +12, TaskCard +12] = 1004, +1 сюита [TaskCard.test.tsx];
  регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone).
- npm run build (standalone) -- успешно; /tasks + 4 маршрута статичны,
  First Load JS без деградации (481 kB, иконки lucide +2 симв. классов).
- **Контрольный мутационный прогон** (scripts/cert_ia1_mutations.py,
  защита расширена TaskCard.test.tsx): **15/15 KILLED, 0 SURVIVED** --
  включая M7 (срыв компаратора порядка), M13 (text-base DNA), M14 (aria),
  M15 (новый: raw key в подсказке R2). Тестовая защита модуля стала
  ПОЛНОЙ относительно матрицы мутантов сертификации.
- Оракул-инварианты сертификации IA-1 (O1-O11) не затронуты:
  deriveTaskGateState/artifactsFromStages/pipelineStartedFromStages не
  менялись; taskGateReason сохранён поведенчески (рефакторинг на
  awaitStageInfo).

### Границы Task IA-1/R2-R5 (что осознанно НЕ сделано)

- R1 (aria-label списка «Задачи на основе прогноза») — ЗАКРЫТ ТИМЛИДОМ
  решением «копия хаба корректна»; НЕ менялся.
- Микро-CTA для blocked-карточек («Начните с этапа Загрузка» без ссылки)
  — сознательно вне scope; follow-up при необходимости.
- Содержимое задач (What-if/XAI/iDSS/мониторинг) — отдельные вертикальные
  срезы (spec §7).
- ModuleNav, STAGES, бэкенд, embedded — НЕ затронуты (запрет спеки §3).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

Изменённые/новые файлы (ZIP: download/task_ia1_r2_r5_tasks_hub.zip):
- НОВЫЕ: packages/ui/components/TaskCard.test.tsx
- ИЗМЕНЁННЫЕ: packages/ui/lib/task-stops.ts,
  packages/ui/lib/task-stops.test.ts, packages/ui/components/TaskCard.tsx,
  packages/ui/components/TasksHub.tsx, packages/ui/components/TasksHub.test.tsx,
  packages/ui/index.ts, scripts/cert_ia1_mutations.py,
  worklog/worklog6.md (этот журнал).

---

## Task IA-1/CTA-SYM -- Хаб «Задачи»: симметричный микро-CTA для blocked-карточек (follow-up R5)

Дата: 2026-09-15.  Синхронизация: main@bbd04f8 (рабочее дерево содержало
незакоммиченные изменения Task IA-1/R2-R5 — задача выполнялась ПОВЕРХ них,
производственные файлы R2-R5 эволюционировали, см. ниже). Постановка
тимлида: «Дальше: симметричный CTA для blocked-карточек» — та самая
граница scope, зафиксированная в предыдущей записи как follow-up. Полный
цикл AGENTS.md: TDD RED->GREEN, мутационный прогон, полная регрессия,
typecheck/build.

### Дизайн и семантика

- Ключевое семантическое решение: в blocked пайплайн ещё НЕ начат, поэтому
  CTA ведёт на ВХОД в пайплайн — этап «Загрузка» (STAGE_DEFS key "upload",
  href "/upload"), а НЕ на этап-владельца недостающего артефакта (до
  Загрузки ни один последующий этап нереализуем — например, для
  «Принятия решений» указывать на «Прогнозирование» в blocked нельзя).
  Это зеркально согласовано с текстом причины blocked («Начните с этапа
  Загрузка…») — причина сообщает этап, CTA даёт движение.
- Единая точка истины: НОВАЯ чистая функция ctaStageInfo(requires,
  artifacts, pipelineStarted) -> StagePointer | null: awaiting —
  делегирует awaitStageInfo (этап-владелец первого недостающего артефакта
  в порядке пайплайна); blocked — указатель «Загрузки» (ищется по key в
  STAGE_DEFS, не хардкод-литерал); available — null. awaitStageInfo
  сохранён без изменений (awaiting-специфичная семантика + публичный
  экспорт).
- Рендер: TaskCard — проп переименован awaitStage -> ctaStage
  (симметричное имя), условие рендера state !== "available" && ctaStage:
  та же геометрия/цвета для обоих состояний (text-xs font-semibold
  text-brand, ArrowRight, focus-ring). TasksHub переключён на
  ctaStageInfo; экспорт @cisstat/ui: + ctaStageInfo.
- A11y: ссылка внутри div role="group" валидна (group неинтерактивен);
  aria-label группы с причиной сохранён байт-в-байт; CTA имеет собственное
  имя «Перейти к этапу Загрузка»; иконки aria-hidden. Защита от ложного
  аффорданса СОХРАНЕНА: ссылок на НЕдоступную задачу по-прежнему нет —
  CTA ведёт только на реализованный этап пайплайна.
- Контракт §8 (осознанная эволюция, санкционирована заказом тимлида):
  «свежая сессия — ни одной ссылки» сужается до «ни одной ЗАДАЧНОЙ ссылки
  (href^="/tasks/")»; появляются 4 CTA на /upload. Спецификацию НЕ правил
  (прерогатива тимлида) — рекомендуется обновить формулировку §8 стр.1.

### TDD

- RED подтверждён: task-stops.test.ts (срыв компиляции на отсутствующем
  экспорте ctaStageInfo), TaskCard.test.tsx (3 падения: blocked-CTA,
  defensive-no-link, available-no-nesting), TasksHub.test.tsx (fresh-сессия
  ждала 4 CTA на /upload).
- GREEN: модуль 55/55 (task-stops 34 + TaskCard 14 + TasksHub 6 + page 1;
  было 48 — рост +7: 5 тестов ctaStageInfo + 2 нетто в TaskCard).

### Верификация

- Полная frontend-регрессия: **103 сюиты / 1011 passed / 0 failed**
  (базлайн 103/1004 точно; арифметика: 1004 + 7 новых = 1011 — сходится;
  регрессий вне задачи нет).
- npm run typecheck:all — 0 ошибок (embedded + standalone).
- npm run build (standalone) — успешно; /tasks + 4 маршрута статичны,
  First Load JS без деградации (481 kB).
- **Мутационный прогон**: матрица расширена 15 -> 18 мутантов:
  M16 (blocked-указатель возвращается как null — CTA исчезает),
  M17 (blocked ищет "forecasting" вместо "upload" — указатель на владельца
  артефакта вместо входа в пайплайн), M18 (условие рендера CTA сужено до
  awaiting-only). Итог: **18/18 KILLED, 0 SURVIVED** — защита полная,
  новые семантические риски blocked-ветки закрыты тестами.

### Границы задачи (что осознанно НЕ сделано)

- Спецификация docs/spec_tasks_ia.md §8 — НЕ редактировалась (см. выше).
- R1 (aria-label списка) — закрыт тимлидом ранее, не трогался.
- Причина blocked («Начните с этапа Загрузка — задачи работают поверх
  артефактов пайплайна») — НЕ менялась: лёгкая текстовая избыточность с
  CTA зеркальна паттерну awaiting и зафиксирована тестами.
- ModuleNav, STAGES, бэкенд, embedded, содержимое задач — НЕ затронуты.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

Изменённые/новые файлы (ZIP: download/task_ia1_blocked_cta_symmetry.zip):
- ИЗМЕНЁННЫЕ: packages/ui/lib/task-stops.ts (+ctaStageInfo),
  packages/ui/components/TaskCard.tsx (проп ctaStage, симметричный рендер),
  packages/ui/components/TasksHub.tsx (переключён на ctaStageInfo),
  packages/ui/index.ts (+экспорт), packages/ui/lib/task-stops.test.ts
  (+5 кейсов), packages/ui/components/TaskCard.test.tsx (+2 нетто,
  переименование пропа), packages/ui/components/TasksHub.test.tsx
  (fresh-сессия: 0 задачных ссылок + 4 CTA), worklog/worklog6.md (эта
  запись); вне дерева: scripts/cert_ia1_mutations.py (M16-M18).

---

## Task VALID-2: Автозагрузка «Метрики и алгоритм» активной остановки в окно «Описание» (инвариант информативности, весь степпер «Валидации»):

Дата: 2026-09-15. Синхронизация: main@dbf8a32 (IA-1/CTA-SYM; Upload-1
принята как e6ad145), рабочее дерево чистое до правки. Постановка
тимлида: при загрузке страницы степпер стоит на первой активной
остановке «Типы данных», а в «Описании» — placeholder «Нажмите
«Метрики и алгоритм»…»; реализовать принцип «активная остановка
степпера автоматически загружает в «Описание» информацию с кнопки
«Метрики и алгоритм» данной остановки (и делает кнопку активной)»
вне зависимости от статуса остановки; изучить кодовую базу на
блокирующие зависимости; реализовать для всего степпера «Валидации».
Полный цикл AGENTS.md: TDD RED->GREEN, полная frontend-регрессия,
typecheck/build обеих оболочек.

### Анализ блокирующих зависимостей (по постановке) — ОТСУТСТВУЮТ

1. Контент «Метрики и алгоритм» — статические константы
   DATA_TYPES…SUFFICIENCY_METRICS_DESCRIPTION (+ статический fallback
   по CHECK_META); НЕ зависит ни от GET /dataset/validate, ни от
   статуса проверки, ни от наличия датасета.
2. Кнопки «Метрики и алгоритм» рендерятся для ВСЕХ 10 проверок
   безусловно (map по orderedChecks) — существуют при любом статусе
   (pending/done/warning/skipped).
3. Активное состояние кнопки — производное от (check.id ===
   activeCheckId && descriptionSection === "metrics") — включается
   само при инварианте, отдельного кода не требует.

### Дизайн (точки изменения — только слой управления секцией)

Инвариант: секция null более не производится; покоящееся состояние
окна «Описание» — метрики активной остановки.
1. Initial state: useState<…>(null) -> useState<…>("metrics") —
   автозагрузка метрик «Типы данных» при загрузке страницы.
2. Клик степпера: setDescriptionSection(null) ->
   setDescriptionSection("metrics") — автозагрузка при переключении
   остановки. Клик по УЖЕ активной остановке секцию не меняет
   (открытая Справка/Правилами остаются) — прежняя семантика.
3. Закрытие Справки (toggle): null -> "metrics".
4. Закрытие «Управление правилами» (toggle): null -> "metrics".
Явный пользовательский выбор («Исправить этап проверки»/pipeline,
Справка, Правилами) приоритетен, пока пользователь сам не вернётся
к метрикам. Placeholder-ветка и guard-и (!descriptionSection)
сохранены как defense-in-depth — при инварианте недостижимы.

### Оценка рисков и решения

1. Toggle-семантика Справки/Правил сохранена (открыть/закрыть);
   изменено только состояние ПОСЛЕ закрытия — возврат к метрикам
   вместо неинформативного placeholder (прямо следует из цели
   «максимизации информативности»). Гардим двумя кейсами.
2. Существующие тесты, кодирующие старую семантику placeholder
   (2 кейса «clicking the rules button…»), переписаны под инвариант
   — прецедент пересертификации Task 133 («тесты кодировали ту же
   устаревшую семантику — переписаны»).
3. Регресс существующего ranges-теста: regex /Эталон диапазонов
   не задан/i стал дважды-совпадающим (метрики «Диапазонов значений»
   сами документируют этот статус фразой в «» + строка статуса
   карточки). Ассерт уточнён до точного текста (исходное намерение —
   строка статуса карточки). Consistency-тест не тронут: фраза
   статуса в CONSISTENCY_METRICS_DESCRIPTION отсутствует, regex
   однозначен.
4. Тест-гард «explicit pipeline click still wins»: явный клик
   «Исправить этап проверки» переключает на мастер; возврат к
   метрикам — явным кликом по кнопке метрик. Инвариант не ломает
   пользовательский выбор.
5. Expandable description: useEffect [descriptionSection]
   сворачивает expand при смене секции — при автозагрузке поведение
   корректно (смена остановки сворачивает развёрнутое описание).
6. Другие вкладки (Загрузка/Предобработка/EDA/Моделирование) — вне
   мандата постановки, не тронуты.

### TDD (RED -> GREEN)

- RED: новая сюита из 6 кейсов («автозагрузка „Метрики и алгоритм“
  активной остановки (инвариант информативности)»): (1) автозагрузка
  при загрузке страницы (pending, без датасета) + активность кнопки
  [0] и неактивность [1]; (2) автозагрузка при переключении
  степпера («Уникальность», pending) без второго клика; (3) статус-
  независимость: done-остановка после запуска валидации автозагружает
  метрики так же; (4) закрытие Справки -> метрики (не placeholder);
  (5) закрытие Правил -> метрики (не placeholder); (6) гард: явный
  pipeline-клик приоритетен, возврат к метрикам явным кликом.
  Плюс переписаны 2 существующих placeholder-теста. Итог RED: ровно
  7 падений — все кодируют новый инвариант; 37 проходят (включая
  гард (6) после уточнения ассерта getAllByText — множественный
  заголовок мастера, как в существующем тесте L241).
- GREEN: 4 точки изменения компонента -> 44/44 в файле
  (38 базлайн + 6 новых).

### Верификация

- Полная frontend-регрессия: **103 сюиты / 1017 passed / 0 failed**
  (базлайн main@dbf8a32 — 103/1011; +6 новых — арифметика сходится;
  регрессий вне задачи нет).
- npm run typecheck:all — 0 ошибок (embedded + standalone);
  npm run build:all — Compiled successfully x2.
- Backend не затронут (0 файлов .py); правка действует в ОБЕИХ
  оболочках через общий компонент packages/ui.

### Границы Task VALID-2 (что осознанно НЕ сделано)

- Распространение инварианта на другие вкладки (Загрузка/
  Предобработка/EDA/Моделирование) — вне мандата; там свои семантики
  секций описания (по отдельной постановке, если понадобится).
- Placeholder-ветка/подзаголовок «Выберите раздел в боковой панели»
  не удалялись — defense-in-depth при недостижимом null.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@dbf8a32 + изменения Task VALID-2.

Изменённые/новые файлы (ZIP: download/task_valid2_validation_metrics_autoload.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisValidation.tsx
  (4 точки изменения: initial "metrics", степпер-клик "metrics",
  toggle-закрытие Справки/Правил -> "metrics"; комментарии
  инварианта), packages/ui/components/TsAnalysisValidation.test.tsx
  (+6 кейсов новой сюиты; переписаны 2 placeholder-теста; уточнён
  ассерт ranges-теста), worklog/worklog6.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task IA-1/R6 -- Правило входа в реестр задач: вариант A (allowlist-тест + предусловие §5) + вариант C (бэкенд производит validated)

Дата: 2026-09-15.  Синхронизация: main@dbf8a32 (тимлид закоммитил R2-R5
как bd055b4 и CTA-SYM как dbf8a32; рабочее дерево после reset --hard
чистое). Постановка тимлида: «Мой выбор A и С. Синхронизируйся. Реализуй»
-- т.е. обе ветки рекомендации R6 сертификации IA-1. Полный цикл
AGENTS.md: TDD RED->GREEN на ОБЕИХ сторонах (pytest + jest), контрольный
мутационный прогон, полная регрессия.

### Семантические решения (задокументированы в докстрингах)

- **Что значит «валидация пройдена» (C):** «работа выполнена», НЕ «данные
  чисты». Успешное завершение общего запуска 10 проверок в
  GET /v1/session/dataset/validate выставляет stages.validation = "done".
  Зеркало прецедентов платформы: model_card создан -> modeling done
  (modeling_session.py:3258); ForecastRun завершён -> forecasting done
  (forecasting_session.py:182). Чистота данных -- отдельное поле ответа
  is_valid: гейт артефакта на is_valid сделал бы мину ХУЖЕ (датасет с
  warning'ами навсегда оставил бы validated-задачу в awaiting).
- **Якорь вставки:** хвост get_dataset_validate, после построения payload,
  до return: session.set_stage("validation", "done") + touch() + save()
  (контракт SessionStore: мутация -- обязательно save()). 500 на
  неожиданном исключении НЕ маркирует этап (вставка после успешного
  построения ответа); 404 без датасета не трогает этап (тест-гард).
- **Свежесть:** новый датасет -> set_dataset сбрасывает ВСЕ этапы в
  pending (session_store.py:268 "Новый датасет -- сбрасывает прогресс") --
  артефакт validated устаревает вместе с этапом автоматически, отдельной
  инвалидации не требуется.
- **Автозапуск исключён конструкцией:** фронтенд вызывает
  /dataset/validate ТОЛЬКО явным действием (кнопка runValidation:
  TsAnalysisValidation.tsx:771, ре-ранги onRulesApplied/onApplied) --
  валидация не становится done от простого визита на вкладку.
- **last_active_stage:** set_stage("validation","done") обновляет
  last_active_stage -- то же поведение, что у modeling/forecasting
  (существующий паттерн, не отклонение).

### Вариант C (бэкенд): TDD

- RED: 3 новых теста в tests/api/test_dataset_validate.py:
  (1) test_validate_marks_validation_stage_done -- pending после загрузки,
  done после запуска; (2) test_validate_404_without_dataset_leaves_stage_
  pending -- гард; (3) test_new_dataset_resets_validation_stage --
  устаревание артефакта. Подтверждён: ровно (1) и (3) падают, 13
  существующих зелёные.
- GREEN: правка get_dataset_validate (+ докстринг с семантикой) --
  15/15 в файле.
- Правка минимальна: +20 строк в session.py, ни один другой роутер
  не затронут.

### Вариант A (фронтенд + спека): TDD

- spec_tasks_ia.md §5: предусловие входа в реестр (R6) после таблицы v1:
  каждый артефакт requires обязан быть производимым бэкендом, с таблицей
  свидетельств (file:line всех четырёх продюсеров) и указанием на
  страхующий тест.
- task-stops.test.ts: НОВЫЙ describe "registry admission rule (R6)" --
  BACKEND_PRODUCIBLE_ARTIFACTS = ["validated","model_card","forecast_run"]
  (ЖИВЁТ В ТЕСТЕ сознательно: обновление = решение в том же PR) + 3
  инварианта: (1) requires каждой задачи реестра ⊆ allowlist; (2)
  allowlist перечисляет ВЕСЬ слой артефактов (новый член ARTIFACT_STAGE
  без сознательного обновления роняет тест); (3) каждый член allowlist
  отображается на реальный ключ STAGE_DEFS (целостность слоя).
- RED-демонстрация guard'а (два временных мутанта вручную, затем
  восстановление): удаление validated из allowlist -> падает инвариант
  (2); срыв ARTIFACT_STAGE.validated -> "ghost_stage" -> падают 7 тестов,
  включая слойные. Мина не проходит молча.
- GREEN: модуль 58/58 (task-stops 37 + TaskCard 14 + TasksHub 6 + page 1;
  было 55 -- +3 R6-инварианта).

### Верификация

- Backend: tests/api/test_dataset_validate.py 15/15; полный pytest
  tests/: **2326 passed / 10 failed / 24 skipped** -- все 10 падений
  ПРЕДСУЩЕСТВЕННЫЕ environment-only (ModelExecutionContractError
  «отсутствуют зависимости ['neuralforecast']»: тяжёлая neural-группа
  torch/neuralforecast в среде не ставится, CI её тоже не ставит);
  предсущественность доказана git stash правки session.py -> те же
  падения на baseline -> stash pop (sha восстановлен).
- Frontend: полный jest **103 сюиты / 1014 passed / 0 failed**
  (базлайн 103/1011 + 3 R6-инварианта -- арифметика сходится);
  typecheck:all 0 ошибок; build успешен (5 маршрутов /tasks статичны,
  481 kB -- без деградации).
- **Мутационный прогон**: +M19 (ARTIFACT_STAGE.validated ->
  "ghost_stage" -- срыв целостности слоя под R6-инвариантом) -->
  **19/19 KILLED, 0 SURVIVED**.
- Среда исполнения: для прогона pytest установлены requirements.txt +
  apps/api/requirements.txt + requirements-dev.txt (+pandera как
  недостающий ключевой пакет); neural-группа сознательно НЕ ставилась
  (~600 MB RSS по замерам Task 138b).

### Следствия для хаба «Задачи»

- Артефакт validated теперь производим: БУДУЩИЕ задачи с
  requires:["validated"] (кандидаты эшелона 2: «Качество данных»,
  «Профиль датасета») легальны БЕЗ правок бэкенда; правило R6 +
  allowlist страхуют от непроизводимых контрактов.
- Реестр v1 НЕ расширялся (4 задачи); UI хаба не менялся: в fresh-сессии
  по-прежнему 4 blocked-карточки; критерии §8 не затронуты.
- Наблюдение тимлиду (НЕ правлено, вне мандата): предложение §5
  «подсказка о forecast_run -- забота самой задачи в v2, не хаба»
  устарело после реализации R2 -- плашка-призрак теперь забота хаба;
  рекомендуется обновить формулировку при следующем касании спеки
  (вместе с §8 из CTA-SYM).

### Границы задачи (что осознанно НЕ сделано)

- in_progress для validation НЕ вводился (вычисление мгновенно, осмысленного
  момента нет; modeling/forecasting вводят его на длинных операциях).
- Реестр, TaskCard, TasksHub, tasks-страницы, ModuleNav, STAGES -- НЕ
  тронуты (C меняет только выставление этапа бэкендом; A -- только тесты
  и спеку).
- Preprocessing/EDA этапы по-прежнему без продюсера: артефактов на них
  в слое задач НЕТ (TaskArtifact их не декларирует), мина не
  воспроизводится; если эшелон 2 захочет артефакт от этих этапов --
  сначала продюсер, потом запись в реестр (теперь это ЗАФИКСИРОВАННОЕ
  правило).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

Изменённые/новые файлы (ZIP: download/task_ia1_r6_admission_rule.zip):
- ИЗМЕНЁННЫЕ: apps/api/routers/session.py (C: маркировка этапа +
  докстринг), tests/api/test_dataset_validate.py (C: +3 API-теста),
  docs/spec_tasks_ia.md (A: предусловие §5),
  packages/ui/lib/task-stops.test.ts (A: allowlist + 3 инварианта),
  worklog/worklog6.md (этот журнал); вне дерева:
  scripts/cert_ia1_mutations.py (+M19).

---

## Task PREPR-2 -- Автозагрузка «Метрики и алгоритм» активной остановки в окно «Описание» (инвариант информативности, весь степпер «Предобработки»)

Дата: 2026-09-15.  Синхронизация: main@e986614 (тимлид закоммитил
VALID-2 как 2de98d9 и IA-1/R6 как e986614; локальные некоммитнутые
правки VALID-2 идентичны upstream -- reset --hard, дерево чистое).
Постановка тимлида: «автозагрузка содержимого „Метрики и алгоритм"
активной остановки в окно „Описание" вкладки „Предобработка", вне
зависимости от статуса остановки». Полный цикл AGENTS.md: TDD
RED->GREEN, полная регрессия, typecheck/build обеих оболочек.

### Дизайн (зеркально VALID-2, адаптация под 3 секции)

- Тот же принцип, что VALID-2 («Валидация»), но у «Предобработки» три
  секции описания (metrics / pipeline / help) и НЕТ секции rules --
  поэтому 3 точки изменения вместо 4. Автозагружается секция metrics.
- **Проверка блокирующих зависимостей (постановка): НЕТ.** Контент
  метрик -- статические константы компонента (10 констант
  *_METRICS_DESCRIPTION, строки 146-425), не зависят от ответов
  /dataset/*-профилей и наличия датасета; descriptionContent/
  descriptionSubtitle -- чистые функции от (activeCheckId,
  descriptionSection); activeCheck всегда определён (CHECKS[0] --
  первый активный). Статусы остановок (pending/running/warning/done/
  skipped/error) вычисляются из профилей, но на секцию описания не
  влияют -- инвариант статус-независим по построению.
- **Точки изменения:** (1) initial descriptionSection null -> "metrics"
  (автозагрузка при загрузке страницы: «Описание» сразу показывает
  метрики «Пропусков», кнопка «Метрики и алгоритм» активна);
  (2) степпер-клик: прежний сброс Справки в placeholder ->
  `if (check.id !== activeCheckId) setDescriptionSection("metrics")`
  (переключение остановки автозагружает её метрики; клик по УЖЕ
  активной остановке секцию не меняет -- открытая Справка остаётся);
  (3) handleHelpClick: закрытие Справки -> "metrics" вместо null
  (placeholder более не производится). Явный выбор мастера
  (handleDescriptionClick, «Исправить …») не тронут -- приоритетен.

### Риски и решения

1. Клик по уже активной остановке: прежнее поведение закрывало
   Справку ЛЮБЫМ степпер-кликом; новое сохраняет открытую секцию при
   клике по активной остановке (та же семантика, что принята в
   VALID-2) -- закрыт отдельным тестом-гардом (6).
2. Мастер-секции («Исправить …»): явный клик приоритетен, инвариант
   не перетирает выбор пользователя -- гард (5), как в VALID-2.
3. useEffect [descriptionSection] (сворачивание expand): смена
   остановки меняет секцию -> развёрнутое описание корректно
   сворачивается; поведение унаследовано без правок.
4. Placeholder-ветка и подзаголовок «Выберите раздел в боковой
   панели» НЕ удалены -- defense-in-depth при недостижимом null.
5. Существующие тесты «Обзор: …»/мастеров используют явные клики по
   кнопкам метрик/мастеров -- с инвариантом не конфликтуют (проверено
   полным файловым прогоном 57/57).
6. Другие вкладки (Загрузка/Валидация/EDA/Моделирование) -- вне
   мандата постановки, не тронуты.

### TDD (RED -> GREEN)

- RED: новая сюита из 6 кейсов («автозагрузка „Метрики и алгоритм"
  активной остановки (инвариант информативности)»): (1) автозагрузка
  при загрузке страницы (warning-профиль «Пропусков») + активность
  кнопки [0]/неактивность [1] + подзаголовок; (2) автозагрузка при
  переключении степпера («Выбросы», pending-оверрайд) без второго
  клика; (3) статус-независимость: done-остановка («Регулярность
  ряда») автозагружает так же; (4) закрытие Справки -> метрики (не
  placeholder); (5) гард: явный pipeline-клик приоритетен, возврат к
  метрикам явным кликом; (6) гард: клик по УЖЕ активной остановке
  сохраняет открытую Справку, переключение -- автозагружает метрики.
  Плюс переписаны 2 существующих placeholder-теста. Итог RED: ровно
  7 падений -- все кодируют новый инвариант; 50 проходят (включая
  гард (5) -- та же RED-семантика, что у гарда VALID-2).
- GREEN: 3 точки изменения компонента -> 57/57 в файле
  (49 базлайн + 6 новых + 2 переписанных).
  Замечание по инфраструктуре: запуск jest из packages/ui (без
  корневого jest.config.js) даёт ложный SyntaxError на TS-аннотациях
  (babel-jest без TS-плагина); корректный прогон -- из корня репо.

### Верификация

- Полная frontend-регрессия: **103 сюиты / 1026 passed / 0 failed**
  (базлайн main@e986614 -- 103/1020 = 1011 + 6 VALID-2 + 3 R6;
  +6 новых PREPR-2 -- арифметика сходится; регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2.
- Backend не затронут (0 файлов .py); правка действует в ОБЕИХ
  оболочках через общий компонент packages/ui.

### Границы Task PREPR-2 (что осознанно НЕ сделано)

- Распространение инварианта на другие вкладки (Загрузка/EDA/
  Моделирование) -- вне мандата; там свои семантики секций описания
  (по отдельной постановке, если понадобится). Инвариант теперь на
  2 из 5 вкладок (Валидация + Предобработка).
- Placeholder-ветка/подзаголовок «Выберите раздел в боковой панели»
  не удалялись -- defense-in-depth при недостижимом null.
- Секция pipeline («Полный пайплайн»/мастера) в автозагрузку не
  вовлекается -- постановка требует именно «Метрики и алгоритм».
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@e986614 + изменения Task PREPR-2.

Изменённые/новые файлы (ZIP: download/task_prepr2_preprocessing_metrics_autoload.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisPreprocessing.tsx
  (3 точки изменения: initial "metrics", степпер-клик "metrics",
  toggle-закрытие Справки -> "metrics"; комментарии инварианта),
  packages/ui/components/TsAnalysisPreprocessing.test.tsx
  (+6 кейсов новой сюиты; переписаны 2 placeholder-теста),
  worklog/worklog6.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task EDA-2 -- Автозагрузка «Метрики и алгоритм» активной остановки в окно «Описание» (инвариант информативности, весь степпер «Разведочного EDA»)

Дата: 2026-09-16.  Синхронизация: среда сброшена, репозиторий
переклонирован; main@82d41db (тимлид закоммитил PREPR-2 как 82d41db),
дерево чистое; зависимости восстановлены npm ci по lockfile.
Постановка тимлида: «автозагрузка содержимого „Метрики и алгоритм"
активной остановки в окно „Описание" вкладки „Разведочный EDA", вне
зависимости от статуса остановки». Полный цикл AGENTS.md: TDD
RED->GREEN, полная регрессия, typecheck/build обеих оболочек.

### Дизайн (зеркально VALID-2/PREPR-2)

- Тот же принцип, что VALID-2 («Валидация») и PREPR-2
  («Предобработка»); у EDA, как и у Предобработки, три секции описания
  (metrics / pipeline / help), секции rules нет, кнопка мастера
  называется «Полный пайплайн» -- 3 точки изменения, автозагружается
  секция metrics. Инвариант теперь на 3 из 5 вкладок.
- **Проверка блокирующих зависимостей (постановка): НЕТ.** Контент
  метрик -- статические константы компонента (11 констант
  *_METRICS_DESCRIPTION, строки 145-394), не зависят от ответов
  /dataset/eda-* и наличия датасета; descriptionContent/
  descriptionSubtitle -- чистые функции от (activeCheckId,
  descriptionSection); activeCheck всегда определён (CHECKS[0] --
  «Описательные статистики»). Статусы остановок вычисляются из
  профилей (running/pending/done/warning/skipped/error), но на секцию
  описания не влияют -- инвариант статус-независим по построению.
- **Точки изменения:** (1) initial descriptionSection null -> "metrics"
  (автозагрузка при загрузке страницы); (2) степпер-клик: прежний
  сброс Справки в placeholder -> `if (check.id !== activeCheckId)
  setDescriptionSection("metrics")` (клик по УЖЕ активной остановке
  секцию не меняет -- открытая Справка остаётся); (3) handleHelpClick:
  закрытие Справки -> "metrics" вместо null. Явный выбор «Полный
  пайплайн» (handleDescriptionClick) не тронут -- приоритетен.

### Риски и решения

1. Клик по уже активной остановке: прежнее поведение закрывало
   Справку ЛЮБЫМ степпер-кликом; новое сохраняет открытую секцию
   (семантика VALID-2/PREPR-2) -- тест-гард (6).
2. Кнопка «Полный пайплайн» НЕ уникальна на странице (10 карточек по
   одной на остановку) -- в тестах клик по [0] (orderedChecks ставит
   активную первой), в отличие от уникальных «Исправить …» PREPR-2.
3. Специфика статусов EDA: descriptive Busy/running -> done после
   /dataset/stats; остальные остановки pending до активации (их
   профили запрашиваются только при activation) -- кейс 2 использует
   естественно-pending «IH-анализ», кейс 3 -- done «Описательных
   статистик» с ожиданием сигналов готовности (таблица + селектор).
4. useEffect [descriptionSection] (сворачивание expand): смена
   остановки меняет секцию -> развёрнутое описание корректно
   сворачивается; поведение унаследовано без правок.
5. Placeholder-ветка и подзаголовок «Выберите раздел в боковой
   панели» НЕ удалены -- defense-in-depth при недостижимом null.
6. Другие вкладки (Загрузка/Моделирование) -- вне мандата постановки,
   не тронуты.

### TDD (RED -> GREEN)

- RED: новая сюита из 6 кейсов («автозагрузка „Метрики и алгоритм"
  активной остановки (инвариант информативности)»): (1) автозагрузка
  при загрузке страницы (running->done «Описательных статистик») +
  активность кнопки [0]/неактивность [1] + подзаголовок; (2)
  автозагрузка при переключении степпера («IH-анализ», pending) без
  второго клика; (3) статус-независимость: клик по done-остановке
  (переключение на «Матрицу моделей» и обратно) автозагружает так же;
  (4) закрытие Справки -> метрики (не placeholder); (5) гард: явный
  pipeline-клик приоритетен, возврат к метрикам явным кликом; (6)
  гард: клик по УЖЕ активной остановке сохраняет открытую Справку.
  Плюс переписаны 2 существующих placeholder-теста. Итог RED: ровно
  7 падений -- все кодируют новый инвариант; 34 проходят (включая
  гард (5) -- та же RED-семантика, что у гардов VALID-2/PREPR-2).
- GREEN: 3 точки изменения компонента -> 41/41 в файле
  (35 базлайн + 6 новых).

### Верификация

- Полная frontend-регрессия: **103 сюиты / 1032 passed / 0 failed**
  (базлайн main@82d41db -- 103/1026; +6 новых EDA-2 -- арифметика
  сходится; регрессий вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2.
- Backend не затронут (0 файлов .py); правка действует в ОБЕИХ
  оболочках через общий компонент packages/ui.
- Инфраструктурная заметка: среда исполнения сброшена между
  сессиями -- репозиторий переклонирован, зависимости восстановлены
  npm ci (root typescript 6.0.3 по lockfile, ts-jest 29.4.12 --
  совместимы, сюиты парсятся); запуск jest -- ТОЛЬКО из корня репо
  (из packages/ui без корневого jest.config.js jest падает на
  babel-jest без TS-плагина, см. заметку в PREPR-2).

### Границы Task EDA-2 (что осознанно НЕ сделано)

- Распространение инварианта на оставшиеся вкладки (Загрузка/
  Моделирование) -- вне мандата; там свои семантики секций описания
  (по отдельной постановке, если понадобится).
- Placeholder-ветка/подзаголовок «Выберите раздел в боковой панели»
  не удалялись -- defense-in-depth при недостижимом null.
- Секция pipeline («Полный пайплайн») в автозагрузку не вовлекается --
  постановка требует именно «Метрики и алгоритм».
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@82d41db + изменения Task EDA-2.

Изменённые/новые файлы (ZIP: download/task_eda2_eda_metrics_autoload.zip):
- ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisEDA.tsx
  (3 точки изменения: initial "metrics", степпер-клик "metrics",
  toggle-закрытие Справки -> "metrics"; комментарии инварианта),
  packages/ui/components/TsAnalysisEDA.test.tsx
  (+6 кейсов новой сюиты; переписаны 2 placeholder-теста),
  worklog/worklog6.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task NAVBG-1 -- Вкладка «Знакомство с платформой» (/navigator): авторский фон по паттерну главной страницы + футер

Дата: 2026-09-16.  Синхронизация: main@765faee (Task EDA-2, autoload
metrics), дерево чистое до правки.  Постановка тимлида: «Во вложении фон
для данной страницы. Реализуй поставку данного фона на "Знакомство с
платформой" по паттерну главной страницы - отрицательная верхняя
граница, скругленные углы. Внизу поставь футер, также в полном
соответствии с главной страницей. Следуй AGENTS.md».  Полный цикл:
TDD RED->GREEN, программная сверка переноса с источником, полная
регрессия, typecheck/build обеих оболочек.

### Дизайн (эталон и точки изменения)

- ЭТАЛОН: apps/standalone/app/page.tsx (главная): обёртка
  «relative isolate -mt-6 pt-6» (компенсация py-6 из <main>
  layout.tsx: абсолютный фон доходит до ModuleNav, контент не
  сдвигается; -mt-6/pt-6 -- один токен шкалы 1.5rem, компенсация
  точная) + HomeWavesBackground (absolute inset-0 -z-10
  overflow-hidden rounded-2xl, inline SVG) + HomeFooter последним
  элементом потока.
- ИСТОЧНИК ФОНА: авторский файл
  CISStat_TS_Analysis_wave_background_3200x1600.svg (холст
  1600x3200, вертикальная композиция под длинную страницу): rect-
  подложка с диагональным градиентом + 4 полупрозрачные «ленты» +
  нижняя мягкая ширма + 3 тонких белых штриха-акцента = 1 rect +
  9 path, 6 linearGradient.
- ТОЧКИ ИЗМЕНЕНИЯ: (1) НОВЫЙ NavigatorWavesBackground.tsx в
  packages/ui -- дословный перенос SVG в JSX по прецеденту
  HomeWavesBackground; (2) apps/standalone/app/navigator/page.tsx --
  обёртка + фон + HomeFooter; (3) экспорт в packages/ui/index.ts;
  (4) НОВЫЕ тесты компонента и страницы.
- Футер: HomeFooter с дефолтным backgroundColor #CAD7F7 -- тот же,
  что на главной («в полном соответствии с главной страницей»);
  компонент документирует «фон -- свой для каждой страницы», но
  изобретать отдельный тинт для navigator постановка не требует --
  дефолт главной честнее; замена на специфичный цвет = правка одного
  пропа по отдельному решению тимлида.

### Два сознательных презентационных отличия от исходного SVG
(оба -- по прецеденту HomeWavesBackground, задокументированы в
докстринге компонента и прижаты тестами):

1. id градиентов (bg/waveA/waveB/waveC/waveD/lower) префиксованы
   «cisstat-nav-»: SVG id глобальны для DOM; голый "bg" почти
   гарантированно столкнётся с другими инлайн-SVG платформы
   (иконки, Recharts, фон главной -- там свои префиксы
   cisstat-home-*). Цвета/offset'ы/opacity скопированы точно.
2. preserveAspectRatio="none" вместо "xMidYMid slice" источника:
   фон обязан заполнять фактическую коробку страницы (absolute
   inset-0) целиком; slice обрезал бы композицию, а мягкие волны
   допускают растяжение -- тот же паттерн, что у главной.

### Оценка рисков и решения

1. Shared-композиция PlatformIntroduction НЕ тронута -- она
   используется и embedded (apps/embedded/app/navigator/page.tsx);
   фон/футер подключены на уровне standalone-страницы, embedded не
   затронут (прецедент фона/футера главной: standalone-only).
2. Вертикальная композиция источника (1600x3200) рассчитана на
   длинную страницу -- /navigator (hero + этапы + навигатор +
   футер) отвечает этому назначению; при resize растяжение
   равномерное (preserveAspectRatio="none").
3. Классы rounded-2xl/overflow-hidden уже в бандле (главная):
   риск purge-потери исключён.
4. Существующая нижняя черта page-bottom-separator внутри
   PlatformIntroduction сохранена: это элемент shared-композиции
   (embedded), не фоновой коробки; гасить её только в standalone
   -- вне мандата постановки (на главной черту убирал сам
   HomeCapabilities, правка 8).
5. isolate на обёртке удерживает -z-10 фона внутри страницы
   (фон не уходит под ModuleNav/ProductHeader).
6. Footer внутри фоновой коробки -- как на главной (bg-бокс
   обёртки простирается за футер; у футера свой rounded-2xl и
   свой фон #CAD7F7).

### TDD (RED -> GREEN)

- RED: (a) packages/ui/components/NavigatorWavesBackground.test.tsx
  -- сюита не собиралась (модуль отсутствует, TS2307);
  (b) apps/standalone/app/navigator/page.test.tsx -- 5 падений из 6
  (обёртка -mt-6/pt-6 отсутствует, фон/футер не рендерятся), гард
  «композиция PlatformIntroduction сохранена» проходил ДО правки.
- GREEN: 10/10 (компонент) + 6/6 (страница).  Два промежуточных
  падения -- ошибки ОЖИДАНИЙ теста, не реализации: (1) ссылок на
  градиенты 7, а не 6 (rect-подложка тоже ссылается на bg);
  (2) источник содержит stroke-opacity=".80" -- перенос дословный,
  ожидание уточнено на ".80".  Повторный GREEN всех целевых сюит
  (включая соседей HomeWavesBackground/HomeFooter/
  PlatformIntroduction/главная) -- 46/46.
- Гард дословности: тест компонента прижимает ВСЕ 9 точных d-строк
  источника (в порядке документа), точную палитру 16 stop-color,
  3 штриха (stroke-opacity .80/.68/.78, width 3) и полупрозрачные
  заливки (.58/.52).

### Программная сверка переноса с источником (не на глаз)

- scripts/task_navbg_verify_transfer.py: парсит исходный SVG и
  компонент, сверяет поэлементно в порядке документа: 6 градиентов
  (координаты x1/y1/x2/y2, stop offset/color/opacity), rect
  (размер/fill), 9 path (d=, fill, stroke, stroke-opacity,
  stroke-width, opacity).  Разрешённые отличия -- ТОЛЬКО префикс id
  и camelCase имён JSX-атрибутов при байт-равных значениях.
  Итог: TRANSFER VERIFICATION OK (6 + 1 + 9, байт-равенство).
- Вспомогательный scripts/task_navbg_extract_source.py -- извлечение
  точной структуры источника для сборки компонента.

### Верификация

- Полная frontend-регрессия: **105 сюит / 1048 passed / 0 failed**
  (базлайн main@765faee -- 103/1032; +2 сюиты / +16 тестов
  [компонент 10 + страница 6] -- арифметика сходится; регрессий
  вне задачи нет).
- npm run typecheck:all -- 0 ошибок (embedded + standalone);
  npm run build:all -- Compiled successfully x2 (13/13 embedded,
  17/17 standalone static pages).
- Прод-смоук собранного маршрута: apps/standalone/.next/server/app/
  navigator.html содержит все 6 префиксованных градиентов
  cisstat-nav-*, геометрию источниковых path, обёртку -mt-6 pt-6 и
  футер <footer aria-label="Подвал сайта" class="rounded-2xl..."
  style="background-color:#CAD7F7">.
- Backend не затронут (0 файлов .py); правка действует в ОБЕИХ
  оболочках через общий компонент packages/ui, НО подключена
  только в standalone-странице (embedded рендерит
  PlatformIntroduction без фоновой обёртки -- без изменений).

### Границы Task NAVBG-1 (что осознанно НЕ сделано)

- Embedded (/navigator) -- фон/футер НЕ подключались: shared-
  композиция не тронута, постановка ссылается на standalone
  (ts-standalone.vercel.app/navigator); при необходимости
  подключения в embedded -- отдельная постановка (там нет
  ModuleNav/py-6-обёртки главной -- компенсация другая).
- Специфичный тинт футера под палитру фона navigator (компонент
  параметризован пропом) -- не изобретался: дефолт #CAD7F7 =
  «полное соответствие главной»; замена -- правка одного пропа.
- Нижняя черта page-bottom-separator (внутри PlatformIntroduction)
  -- сохранена (shared, embedded); гасить только в standalone --
  вне мандата.
- Остальные вкладки платформы -- не тронуты.
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md); рабочее дерево
  main@765faee + изменения Task NAVBG-1.

Изменённые/новые файлы (ZIP: download/task_navbg1_navigator_background_footer.zip):
- НОВЫЕ: packages/ui/components/NavigatorWavesBackground.tsx,
  packages/ui/components/NavigatorWavesBackground.test.tsx,
  apps/standalone/app/navigator/page.test.tsx,
  scripts/task_navbg_extract_source.py,
  scripts/task_navbg_verify_transfer.py
- ИЗМЕНЁННЫЕ: apps/standalone/app/navigator/page.tsx (обёртка
  relative isolate -mt-6 pt-6 + NavigatorWavesBackground + HomeFooter,
  докстринг паттерна), packages/ui/index.ts (экспорт),
  worklog/worklog6.md (этот журнал).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

---

## Task FC-MON-1 — Синтетический датасет мониторинга «Прогнозирования»: нейро-пятёрка честно отсекается применимостью (F04), мониторинг без torch на Render free tier

Дата: 2026-09-16. Синхронизация: main@7b4ac02. Постановка тимлида: нужен
синтетический датасет, который в «Моделировании» фильтром «Применение» не
пропускается в отбор «Для текущего ряда» для нейросетевых моделей (в
частности LSTM) — из-за ограничения render.com free tier 512 MB (Task 138c:
импорт torch+neuralforecast ~606 MB, нейро-бэктест честно 503). До миграции
на корпоративный сервер — быстрый мониторинг «Прогнозирования» на
не-нейронных моделях. Датасет выложен в download CSV.

### Механизм блокировки (реальные правила, не обходные пути)

- F04 (forbidden -> NOT_APPLICABLE): n_observations < model.min_observations;
  у ВСЕЙ нейро-пятёрки min_observations=200. n=150 выбран из окна [100, 200):
  >=100 сохраняет каталог (arima/arima_auto/prophet/tbats/tree_ml min_obs<=100),
  <200 блокирует пятёрку, запас 50 строк в обе стороны.
- LSTM специфичен: requires_gpu=false -> D06 (DL без GPU) его НЕ ловит,
  D02 (n<300) даёт лишь мягкий NOT_RECOMMENDED. F04 — единственный жёсткий
  честный блок для LSTM; им же накрывается вся пятёрка.
- Попутно (тот же профиль, n_series=1, domain=other): var/vecm -> F01,
  deepar -> F01 (раньше F04: min_series=5), garch/egarch -> F02 (domain
  financial), tbats -> D05 (n<200), tree_ml -> D03 (без feature engineering).

### Ряд (детерминированный, numpy default_rng(20260916))

150 месячных наблюдений 2013-01..2025-06 (freq=MS);
value = 120 + 0.55*t + 18*sin(2*pi*(t+2)/12) + N(0, 3.2); положительный
(min=105.79), без пропусков/выбросов (IQR-ratio=0), колонки date,value,
файл ~2.7 KB (лимит прокси Vercel 4.5 MB — без проблем).

### Верификация (верификация, не доверие — ТОЛЬКО реальный код платформы)

scripts/dataset_forecast_monitor.py: CSV -> detect_and_convert_datetime
(date распознана) -> detect_column_frequency (code=MS) ->
prepare_passport_series -> calculate_ts_passport (is_regular=True,
is_seasonal=True, нестационарность тренда — ожидаемо, правилом не
блокируется) -> honest_system_profile (n_series=1) -> мердж
seasonal_periods В ТОЧНОМ порядке build_modeling_context (матрица EDA
подтверждает [12], паспорт даёт спектральный артефакт тренда [32] ->
merged=[12, 32], бэктест возьмёт [0]=12) -> ModelingSpec
(rules/modeling.yaml): resolve_all_applicability + get_candidate_pool.
Итог: 24/24 ассертов PASS.

### Результат (пул «Для текущего ряда» — ровно 10 моделей)

naive/seasonal_naive/drift/mean/ets/ets_damped/theta/arima/arima_auto/
prophet — все RECOMMENDED, все platform_ready. Сообщение LSTM в каталоге:
«Недостаточно данных: 150 < 200 (требуется LSTM / GRU)». Покрытие
ci_method этапа «Прогнозирование»: empirical_oof_quantile (baselines),
analytic (arima/arima_auto/theta), parametric_simulation (ets/ets_damped),
native_adapter (prophet — условная регистрация: локально пакет prophet не
установлен, в прод-образе Dockerfile ставит prophet==1.4.0, Task 124
сертифицирован). Нейро-путь из пула недостижим — инцидент 138c (OOM)
невозможен по построению.

### Кандидат-находка (не блокирующая, уровень документации, к следующему касанию modeling.yaml/spec loader)

Правила применимости исполняются предопределёнными handlers в
modeling_spec_loader._evaluate_rule; YAML-condition — декларативная
документация. Расхождение: YAML-условие F01
«n_series == 1 AND model.requires_multiple_series» не отражает фактическую
логику handler'а — в нём fallback «model.min_series > 1» (ни одна модель
не задаёт requires_multiple_series явно; без fallback F01 был бы мёртвым
правилом). Поведение корректное и желательное (var/vecm/deepar честно
блокируются при одном ряде); расхождение — только текст условия vs
handler. Первая гипотеза «F01 мёртв» (по одному лишь YAML) ОПРОВЕРГНУТА
контрольным прогоном реального движка.

### Замечание для локального мониторинга

Локальное окружение — statsmodels 0.14.5 (прод — 0.15.x): путь
parametric_simulation ETS по находке F-1/FORECAST-1a вернёт честный 422
(defense-in-depth работает), а не интервалы; на проде Render — штатно.

### Границы Task FC-MON-1

- Production-код платформы НЕ тронут (0 изменённых файлов .py; новый
  скрипт — генератор/верификатор). Тесты pytest/Jest не менялись — задача
  датасет-артефактная, верификация отдельным проб-скриптом (прецедент
  scripts/task_*_probe.py).
- Коммит/пуш НЕ выполнялись (запрет AGENTS.md).

Изменённые/новые файлы (ZIP: download/task_fcmon1_forecast_monitor_dataset.zip):
- НОВЫЕ: scripts/dataset_forecast_monitor.py (генератор + верификация
  реальным движком), forecast_monitor_synthetic_n150.csv (артефакт,
  download/), worklog/worklog6.md (этот журнал).
