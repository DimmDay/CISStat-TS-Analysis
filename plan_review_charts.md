# План работ: ревизионный refresh графиков Обзоров (класс OUTL-1) — «графики без явной подписки на refresh»

> **Статус исполнения (2026-09-26):** Волна 1 — ВЫПОЛНЕНА (Task RCH-1, commit 84dc8e4);
> Волна 2 — ВЫПОЛНЕНА (Task RCH-2, эта поставка); гвард подписки — введён в RCH-1
> (ReviewChartsRefreshCoverage.test.ts); Волна 3 — по решению тимлида.

Дата: 2026-09-26. Синхронизация: `main@cfa1213` (PROGR-5.1; working tree чистый). Правила: `AGENTS.md`
(TDD RED→GREEN, запрет commit/push, ZIP новых/изменённых файлов в download, запись в worklog8.md).

Источник постановки: граница задачи **OUTL-1** (worklog8.md, 2026-09-25) — «Тот же класс „графики
Обзора без явной подписки на refresh“ существует на других остановках (Пропуски: матрица/корреляция/
boxplot, …) — ревизионный паттерн применён точечно к „Выбросам“; распространение на все Обзоры —
отдельная постановка (механика идентична, тест-паттерн it.each готов к переносу)».

---

## 1. Постановка

Дефект OUTL-1 (остановка «Выбросы», воспроизведён и сертифицирован): после применения исправления
(кэпирование, apply) профиль/счётчик Обзора перезапросились и показали «выбросов — 0», а смонтированный
график остался на старом ряде — запрос был сделан ДО коммита медленного apply и больше не повторялся.
Корень: **график не был подписан на сигнал обновления** (`refreshKey`), которым Обзор перезапрашивает
профиль; свежесть держалась на случайном побочном эффекте (перемонтирование графиков «loading-flash»-ом
профиля), а не на контракте.

Класс не изолирован остановкой «Выбросы»: в Обзорах других остановок есть графики с собственной
загрузкой данных, URL которых не содержит сигнала обновления. Задача — устранить класс **во всех
Обзорах и их остановках**, перенеся сертифицированный паттерн OUTL-1, и закрыть регресс
статическим гвардом.

### Инвариант согласованности (контракт, выработанный OUTL-1)

> Каждый источник данных графика Обзора подписан на ТЕМ же сигнал обновления, что профиль/счётчик
> этой остановки: `refreshKey = <собственный ключ остановки> + datasetVersion` (сумма монотонно
> растёт от ЛЮБОГО источника инвалидации — применение исправления, смена режима, «Пересчитать»).
> Ревизия включается в query как cache-buster (`revision=<refreshKey>`), чтобы исключить и устаревший
> HTTP-кэш промежуточных слоёв. Формула контракта: **«счётчик обновился ⟹ графики перезапросились»**.

Бэкенд не меняется: неизвестный query-параметр FastAPI игнорирует (прецедент OUTL-1, эпиграф
комментария в PreprocessingOutliersVisualizations.tsx).

### Три механизма доставки данных графика (по живому коду)

| Механизм | Как устроено | Чем обеспечивается подписка |
|---|---|---|
| **A. profile-prop** | График рендерит точки из `profile`, которыйfetch-ит контейнер страницы (deps: `xxxRefreshKey`, `datasetKey`, параметры) | Подписка обеспечена deps контейнера — дефект класса невозможен; достаточно запретить self-fetch гвардом |
| **B. self-fetch графика** | Чарт-компонент сам ходит в API (`useJsonFetch`/`useEffect`) с URL, не зависящим от сигнала | **Паттерн OUTL-1**: проп `refreshKey` → включить `revision=${refreshKey}` в query → URL меняется → эффект перезапускается |
| **C. detail-кэш раскрытия** | `useChartDetailData` (Task 97.3): expanded-payload кэшируется в модуль-глобальном `detailCache`, ключ `(profileKey, fingerprint, params)` | `fingerprint` обязан включать версию мутации датасета; плюс глобальная инвалидация кэша в единственной точке apply |

---

## 2. Верификация по живому коду @ cfa1213 (инвентаризация, первый шаг)

Инвентаризация выполнена по исходникам на `cfa1213`: все Обзоры (расширение `*Overview.tsx`),
их chart-источники (`*Visualizations.tsx`, инлайн-чарты), точки fetch и подписки на refresh.

### 2.1 Модуль «Предобработка» (TsAnalysisPreprocessing.tsx, 10 остановок)

| Остановка | Обзор | Представления/графики | Механизм | Статус подписки |
|---|---|---|---|---|
| Пропуски | PreprocessingMissingOverview | Таблица; **Матрица** (`MissingMatrixChart`), **Корреляция** (`MissingCorrelationChart`), **Boxplot** (`MissingBoxplotChart`) | Обзор: self-fetch `/dataset/missing-profile` deps `[refreshKey]` ✓; графики: self-fetch **B** | **✗ ДЕФЕКТ W1**: `/dataset/missing-matrix` и `/dataset/missing-correlation` — константные URL без параметров вовсе; `/dataset/missing-distribution?value_column&indicator_column` — URL зависит только от ручного выбора колонок; `refreshKey` в графики не прокидывается (файл не менялся с Task 54, 6c7a0e6) |
| Выбросы | PreprocessingOutliersOverview | Линейный / Гистограмма / Плотность / Boxplot | B | ✓ **ЭТАЛОН** (OUTL-1, 4ed649f): `refreshKey` проп + `revision=` во всех 4 URL + bounds |
| Регулярность ряда | PreprocessingRegularityOverview | Интервалы / Таймлайн | B | ✓ (`?_r=${refreshKey}` с Task 72; функционально эквивалентно `revision=`; унификация — W3, опционально) |
| Декомпозиция ряда | PreprocessingDecompositionOverview | Компоненты (+expanded), таблицы | A (compact из `profile`) + **C** (`useChartDetailData` для «Компонентов») | **✗ ДЕФЕКТ W2**: `fingerprint` не передан (комментарий «fingerprint не нужен… инвалидация по смене target-колонки» написан ДО эпохи `datasetVersion`/PREPR-4) — после apply ключ кэша неизменен (column тот же) → stale expanded-payload |
| Стабилизация дисперсии | PreprocessingVarianceOverview | графики из `profile` | A | ✓ |
| Сглаживание ряда | PreprocessingSmoothingOverview | графики из `profile` | A | ✓ |
| Стационарность ряда | PreprocessingStationarityOverview | графики из `profile` | A | ✓ |
| Спектральный анализ | PreprocessingSpectralOverview | Вейвлет (+expanded), FFT | A + **C** | **✗ ДЕФЕКТ W2**: `fingerprint` не передан (params покрывают параметры, но не мутацию датасета) |
| Генерация признаков | PreprocessingFeatureEngineeringOverview | графики из `profile` | A | ✓ |
| Масштабирование | PreprocessingScalingOverview | графики из `profile` | A | ✓ |

Сигналы контейнера: `datasetVersion` бампится `onApplied` всех 10 мастеров (PREPR-4); собственные
`xxxRefreshKey` бампятся по смене режима (строки 666–675); Обзорам «Пропуски/Выбросы/Регулярность»
передаётся сумма `xxxRefreshKey + datasetVersion`.

### 2.2 Модуль «EDA» (TsAnalysisEDA.tsx, 10 остановок)

Профили всех остановокfetch-ит контейнер (deps: `xxxRefreshKey`, `datasetKey`, параметры, target);
Обзоры рендерят графики из `profile` — механизм **A**. Отдельные случаи:

| Остановка | Обзор | Особенность | Статус |
|---|---|---|---|
| Описательные статистики | EdaDescriptiveOverview | Единственный self-fetch в EDA: `/dataset/distribution?column=…` с кэш-гвардом `requestKey = ${refreshKey}:${activeFeature}` | ✓ подписан (эффект перезапускается); **без cache-buster в URL** — hardening W3 |
| Структурные сдвиги | EdaStructuralBreaksOverview | **C**: `useChartDetailData` ×2 (regimes/cusum), `fingerprint = datasetKey` | ⚠️ **W2 (косвенно)**: `datasetKey = datasetId ?? name` НЕ меняется при in-place мутации apply; `detailCache` — модуль-глобальный Map, переживает переходы между модулями → stale expanded после возврата из «Предобработки». Лечится глобальной инвалидацией W2b, без правки этого файла |
| Остальные 8 (Корреляция, IH, Сезонность, Стационарность, Распределение, Отбор признаков, Стратегия валидации, Матрица моделей) | Eda*Overview | графики из `profile` | ✓ (A) |

В EDA apply не производится (мутации датасета — только в «Предобработке»), смонтированный-гонки нет;
риск только через глобальный кэш раскрытия (см. W2b).

### 2.3 Модуль «Валидация» (TsAnalysisValidation.tsx, 10 остановок)

| Остановка | Обзор | Статус |
|---|---|---|
| data_types | ValidationTypeMatrix (из `typeProfile` контейнера) | ✓ (A) |
| ranges / consistency / uniqueness / inclusion / referential / text_quality / regularity / sufficiency | Validation*Overview — self-fetch профиля deps `[refreshKey={validationVersion}]`; «графики» — прогресс-бары и таблицы из профиля | ✓ (A); recharts-графиков нет, `ExpandableChartPanel` не используется — self-fetch чартов нет, классу не подвержены |
| formats | пайплайн-обёртка | ✓ (вне Обзора) |

### 2.4 Модуль «Моделирование» (TsAnalysisModeling.tsx)

| Обзор | Статус |
|---|---|
| ModelingTraceabilityOverview (`context` проп) | ✓ (A) |
| ModelingWorkflowOverview — workflow, данные появляются по явным POST-действиям пользователя (бэктест/диагностика) | ✓ (action-driven, сигналу refresh не подлежит) |

### 2.5 Смежные поверхности (вне Обзоров — зафиксировать, не в объёме)

- `TasksCauses.tsx` (хаб «Задачи»): self-fetch один раз по `modelingDone`; при мутации сессии в смонтированном виде не обновляется — кандидат того же класса, но это не Обзор остановки → отдельная постановка.
- Превью «Навигатора» (`Navigator*Preview.tsx`) — самостоятельные поверхности, обновляются при входе; вне класса.

### 2.6 Вывод инвентаризации

- **W1 (P0)** — подтверждённые дефекты механизма B: 3 графика остановки «Пропуски».
- **W2 (P1)** — тот же класс в слое C (кэш раскрытия): Decomposition, Spectral (fingerprint) + глобальная инвалидация в точке apply (закрывает и EdaStructuralBreaks).
- **W3 (P2, опционально)** — hardening: унификация cache-buster `revision=` (Регулярность `_r=`), cache-buster self-fetch EdaDescriptive.
- Гвард — статический тест-прецедент `ExpandableChartCoverage.test.ts` расширяется списками подписки.

---

## 3. Объём работ и постановки по волнам

### Волна 1 (P0) — «Пропуски»: ревизионный refresh трёх графиков Обзора — ВЫПОЛНЕНА (RCH-1, 84dc8e4)

Паттерн — дословный перенос OUTL-1 (PreprocessingOutliersVisualizations.tsx):

1. `packages/ui/components/PreprocessingMissingVisualizations.tsx`
   - `MissingMatrixChart({ refreshKey = 0 })` — URL → `` `/dataset/missing-matrix?revision=${refreshKey}` ``;
   - `MissingCorrelationChart({ refreshKey = 0 })` — URL → `` `/dataset/missing-correlation?revision=${refreshKey}` ``;
   - `MissingBoxplotChart({ columns, refreshKey = 0 })` — URL дополняется `&revision=${refreshKey}`
     (порядок: существующие `value_column`/`indicator_column` не трогать);
   - в шапку файла — комментарий-эпиграф класса дефекта (по образцу OUTL-1: почему ревизия в query,
     сценарий медленного apply, «неизвестный query-параметр FastAPI игнорирует»).
2. `packages/ui/components/PreprocessingMissingOverview.tsx` — прокинуть `refreshKey` в три графика:
   `<MissingMatrixChart refreshKey={refreshKey} />`, `<MissingCorrelationChart refreshKey={refreshKey} />`,
   `<MissingBoxplotChart columns={profile.columns} refreshKey={refreshKey} />`.
3. Бэкенд НЕ меняется (эндпоинты `/dataset/missing-matrix|missing-correlation|missing-distribution`
   уже существуют; лишний параметр игнорируется).

TDD волны 1 (перенос тест-паттерна it.each, оба файла существуют — расширять):

- `PreprocessingMissingVisualizations.test.tsx` — новый describe «Missing charts refetch on refreshKey
  (revision cache-buster)»: `it.each` по 3 графикам; render c `refreshKey={0}` → fetch #1 содержит путь
  и `revision=0`; `rerender` c `refreshKey={2}` → fetch #2 содержит `revision=2`. Мок-ответы —
  минимальные фикстуры (уже есть в файле — переиспользовать).
- `PreprocessingMissingOverview.test.tsx` — интеграционный инвариант (порт теста OUTL-1): смонтированный
  Обзор на вкладке «Матрица» (`fireEvent.click(role="tab", name="Матрица")`); `rerender` c `refreshKey=1`;
  профиль перезапросился (гАРд существующего поведения) И последний вызов `/dataset/missing-matrix`
  несёт `revision=1`. Контракт о ПОСЛЕДНЕМ состоянии, не о числе попыток (loading-flash даёт
  дополнительные, отбрасываемые active-guard-ом вызовы — прецедент OUTL-1).
- RED-критерии: TS2322 (`refreshKey` отсутствует в пропсах компонентов) / отсутствие `revision=` в URL
  первого вызова — падения по правильной причине. GREEN: оба сюита зелёные полностью.

Критерий приёмки волны: сценарий тимлида на «Пропусках» — до apply «Матрица»/«Корреляция» показывают
пропуски, apply (заполнение) → счётчики Обзора и графики сходятся; в network-инспекторе повторные
запросы графиков с новой ревизией.

### Волна 2 (P1) — слой C: кэш раскрытия, подписанный на мутацию датасета — ВЫПОЛНЕНА (RCH-2, 2026-09-26)

1. `packages/ui/hooks/useChartDetailData.ts` — публичный экспорт
   `invalidateChartDetailCache(): void` (очистка модуль-глобального `detailCache`; существующий
   `__clearChartDetailCacheForTests` становится делегатом). Комментарий: единственная точка истины
   инвалидации — обработчик apply «Предобработки».
2. `packages/ui/components/TsAnalysisPreprocessing.tsx` — 10 инлайн-строк
   `onApplied={() => setDatasetVersion((v) => v + 1)}` заменить единым `handleApplied`, который
   бампит `datasetVersion` И вызывает `invalidateChartDetailCache()` (одна строка сути, ноль
   поведенческих отличий вне кэша раскрытия).
3. `PreprocessingDecompositionOverview.tsx`, `PreprocessingSpectralOverview.tsx` — принять
   `refreshKey?: number` и передать его во `useChartDetailData` как `fingerprint={String(refreshKey)}`
   (fingerprint не попадает в URL — только в ключ кэша, §6.3.5 спеки 97.3); контейнер передаёт
   сумму `decompositionRefreshKey + datasetVersion` / `spectralRefreshKey + datasetVersion`
   (та же формула, что у «Пропусков/Выбросов/Регулярности»). Устаревший комментарий
   «fingerprint не нужен…» заменить канонической формулировкой инварианта.
4. `EdaStructuralBreaksOverview.tsx` — без правки: `fingerprint=datasetKey` сохраняется, глобальная
   инвалидация из п.2 закрывает stale-кэш между визитами; решение зафиксировать комментарием.

TDD волны 2:

- `useChartDetailData.test.tsx` (+2): (a) тот же `params` + другой `fingerprint` → перезапрос
  (сейчас кэш отдал бы старое — RED); (b) после `invalidateChartDetailCache()` следующее раскрытие
  уходит в сеть, а не в кэш.
- `TsAnalysisPreprocessing.test.tsx` (+1): применение исправления любого мастера инвалидирует кэш
  раскрытия — поведенчески: apply → механика `invalidateChartDetailCache` (шпион на экспорте хука).
- RED-критерии: (a) падение «кэш отдал данные до смены fingerprint»; отсутствие экспорта — TS-ошибка.
> **Факт исполнения (RCH-2):** RED-триада подтверждена — TS2305 (нет экспорта
> invalidateChartDetailCache), TS2769 (шпион не может шпионить отсутствующий экспорт),
> TS2322×4 (нет пропа refreshKey в Обзорах). Уточнение: механизм хука уже поддерживал
> fingerprint (существующий тест «смена fingerprint»), поэтому дефект «кэш отдал старое»
> воспроизведён интеграционными тестами ОБЗОРОВ (раскрытие после смены refreshKey без
> fingerprint уходило бы в кэш — RED компиляцией + GREEN поведенчески), а hook-тест (a)
> стал механизмом-локом межсеансной смены fingerprint (между ремоунтами — сценарий
> возврата на остановку, ранее не покрытый).
- GREEN:hook-сюит + контейнерный тест зелёные; смежные `ExpandableChartCoverage.test.ts`,
  `ExpandableChartsProvider.test.tsx` не меняются (раскрытие не тронуто).

### Волна 3 (P2, опционально — hardening, исполнять по решению тимлида) — ОЖИДАЕТ РЕШЕНИЯ ТИМЛИДА

- Унификация cache-buster: `PreprocessingRegularityVisualizations.tsx` `_r=` → `revision=`
  (2 URL + тест), чтобы в кодовой базе был один канонический параметр.
- `EdaDescriptiveOverview.tsx`: в URL self-fetch добавить `&revision=${requestKey}`-слагаемое —
  эффект уже перезапускается (requestKey-гвард), cache-buster закрывает теоретический HTTP-кэш.
- `TasksCauses.tsx` — вынести в отдельную постановку (не Обзор; если решать — той же механикой B).

### Статический гвард (обязательная часть волн, прецедент ExpandableChartCoverage.test.ts)

Новый `packages/ui/components/ReviewChartsRefreshCoverage.test.ts` — статическая проверка исходников
по ЯВНЫМ спискам (без рендера, по образцу Coverage-теста Task 97; списки — единственный источник правды):

- `REVISION_SUBSCRIBED_CHART_SOURCES` — файлы чарт-источников, каждый `export function …Chart`
  обязан принимать `refreshKey` и включать в query ревизию (регэксп `(revision|_r)=\$\{refreshKey\}`):
  `PreprocessingOutliersVisualizations.tsx` (4), `PreprocessingRegularityVisualizations.tsx` (2),
  `PreprocessingMissingVisualizations.tsx` (3) — до волны 1 список не содержит Missing (RED-этап).
- `PROFILE_PROP_OVERVIEWS` — Обзоры механизма A (7 Preprocessing + 8 EDA + Validation/Modeling):
  negative-guard — self-fetch `fetch(sessionApiUrl(` внутри запрещён.
- `SELF_FETCH_GUARDED_OVERVIEWS` — `EdaDescriptiveOverview.tsx`: обязан содержать requestKey-гвард
  с `refreshKey` в ключе.
- Правило переноса: новый Обзор/чарт обязан быть классифицирован ровно в одном списке — при переносе
  правится одна строка гварда (дословно как в прецеденте).

---

## 4. Риски и границы

- **R-1 (Info)**: `MissingBoxplotChart` держит ручной выбор колонок в state при смонтированной вкладке;
  после apply выбор не сбрасывается — поведение выбора, не класса refresh; не трогаем.
- **R-2 (Info)**: активные гварды/loading-flash дают дополнительные отбрасываемые вызовы — тесты
  пишутся на «последнюю ревизию последнего вызова», не на число вызовов (прецедент OUTL-1).
- **R-3 (Low)**: `refreshKey` — сумма ключей, монотонная и уникальная на каждый источник инвалидации;
  не менять тип (объект/строка сломали бы URL-ревизию).
- **R-4 (Info)**: ревизия в query попадает в логи/мониторинг — параметр безобиден, бэкенд игнорирует.
- **R-5 (Info)**: правки только frontend (`.tsx`/hook); бэкенд и контракты схем не меняются —
  Python-регрессия не требуется, достаточно полного jest + typecheck.
- **Границы**: Навигатор-превью, TasksCauses, Forecasting-панели — вне постановки (отдельные задачи);
  cross-stage сценарий «моделирование → возврат в предобработку → apply» (устаревание результатов
  Моделирования) — архитектурная задача консистентности стадий, не класса «Обзоры».

## 5. Порядок исполнения и приёмка

1. Синхронизация `main@cfa1213` (выполнена), рабочая ветка — рабочее дерево (commit/push запрещены).
2. **Гвард вперёд**: ReviewChartsRefreshCoverage.test.ts со списками по состоянию ДО волн — RED
   по Missing (документирует дефект), GREEN по остальным спискам.
3. **Волна 1** (Пропуски): RED (перенос it.each + инвариант) → GREEN (2 product-файла) → прогон.
4. **Волна 2** (detail-кэш): RED (hook-тесты) → GREEN (hook + контейнер + 2 Обзора) → прогон.
5. **Волна 3** — по решению тимлида (каждый пункт самостоятелен).
6. Верификация каждой волны: `npx jest <целевые сюиты>` → полный `npx jest` (базлайн 142 сюита /
   1690+ тестов + новые), `npm run typecheck:all` (embedded+standalone), `npm run build:all`.
7. E2E-контроль (по образцу OUTL-1): демо-датасет → «Пропуски» → Обзор (Матрица/Корреляция) →
   мастер-заполнение → apply → графики перезапрошены с новой ревизией, показания сходятся.
8. Deliverable: ZIP в download (`cisstat-plan-review-charts.zip` — план + worklog; по волнам —
   отдельные ZIP с изменёнными/новыми файлами), запись в worklog8.md. Без commit/push (AGENTS.md).

**Оценка объёма**: волна 1 — 2 product + 2 test файла + гвард; волна 2 — 4 product (hook, контейнер,
2 Обзора) + 2 test файла; суммарно ~10 файлов, бэкенд не затрагивается.
