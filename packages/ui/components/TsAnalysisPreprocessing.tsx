"use client";

// packages/ui/components/TsAnalysisPreprocessing.tsx
//
// ОБЩИЙ компонент фичи "Предобработка" -- используется И embedded-,
// И standalone-приложением. Только внешняя "рамка" (шапка/навигация)
// вокруг него отличается между apps/embedded и apps/standalone;
// сама аналитическая UI-логика -- одна, чтобы не плодить дубли
// (см. историю разговора: 4 копии calculate_ts_passport -- урок учтён).
//
// Компоновка v2 (по макету «Компоновка2 вкладки_Предобработка»):
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Метрики и алгоритм     Проверка: ...
//   3/10 ████░░         [текстовое поле]       [бейдж результата]
//   ┌─Пропуски──⚠─┐    Обзор: Пропуски        описание
//   ├─Выбросы───⚠─┤    [график]               ▼ Метрики
//   └─────────────┘    [Строк][Проп][Выбр]    ▼ Пайплайн
//                                                [Пересчитать]

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { sessionApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";
import { PreprocessingMissingOverview, type MissingProfileResponse } from "./PreprocessingMissingOverview";
import { PreprocessingMissingPipeline } from "./PreprocessingMissingPipeline";
import { PreprocessingOutliersOverview, type OutlierProfileResponse } from "./PreprocessingOutliersOverview";
import { PreprocessingOutliersPipeline } from "./PreprocessingOutliersPipeline";
import { PreprocessingRegularityOverview, type RegularityProfileResponse } from "./PreprocessingRegularityOverview";
import { PreprocessingRegularityPipeline } from "./PreprocessingRegularityPipeline";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── Моковые данные (заменить на API) ─────────────────────────

const CHECKS: Check[] = [
  { id: "missing", label: "Пропуски", status: "pending", count: null,
    description: "Пропуски нарушают DatetimeIndex, делают невозможной STL-декомпозицию, искажают ACF/PACF и ломают ARIMA/SARIMA. Стратегии: удаление строк, медиана/мода, среднее/мода, ноль/Unknown, линейная интерполяция, флаг пропуска." },
  { id: "outliers", label: "Выбросы", status: "pending", count: null,
    description: "Выбросы завышают дисперсию, искажают оценки тренда и ломают тесты стационарности (ADF/KPSS). Методы: IQR, Z-score, Modified Z-score (MAD), процентильный. Обнаружение — на сырых значениях по умолчанию; на остатке после STL-декомпозиции — опционально, когда декомпозиция применима." },
  { id: "regularity", label: "Регулярность ряда", status: "pending", count: null,
    description: "Нерегулярный временной шаг мешает декомпозиции (STL), спектральному анализу (FFT) и моделям ARIMA/SARIMA. Стратегии: сортировка по дате, ресемплирование к целевой частоте с интерполяцией/ffill/bfill/нулём/без заполнения, флаг нарушения." },
  { id: "decomposition", label: "Декомпозиция ряда", status: "pending", count: null,
    description: "Разложение на Trend + Seasonal + Cycle + Residual методами STL, Classical, SEATS или X13. Диагностика остатков на нормальность и автокорреляцию." },
  { id: "variance_stab", label: "Стабилизация дисперсии", status: "pending", count: null,
    description: "Гетероскедастичность ломает доверительные интервалы и тесты. Трансформации: Box-Cox, Yeo-Johnson, log, sqrt. Параметры сохраняются для обратного преобразования." },
  { id: "smoothing", label: "Сглаживание ряда", status: "pending", count: null,
    description: "Удаление высокочастотного шума методами SMA, EMA, Holt-Winters, HP-filter, Savitzky-Golay или фильтром Калмана. Опциональный шаг для зашумлённых рядов." },
  { id: "stationarity", label: "Стационарность ряда", status: "pending", count: null,
    description: "Нестационарность ломает ACF/PACF и идентификацию ARIMA. Дифференцирование порядка d и сезонное D с контролем ADF/KPSS/PP. Порядок сохраняется для обратного преобразования." },
  { id: "spectral", label: "Спектральный анализ", status: "pending", count: null,
    description: "Разведочный анализ частотного состава ряда: FFT, periodogram, вейвлет-преобразование. Определяет доминантные частоты и сезонные периоды для генерации лаговых признаков." },
  { id: "feature_eng", label: "Генерация признаков", status: "pending", count: null,
    description: "Создание временных (hour, day, month), лаговых, скользящих статистик (rolling mean/std) и производных признаков. Структура лагов определяется результатами спектрального анализа." },
  { id: "scaling", label: "Масштабирование", status: "pending", count: null,
    description: "Нормализация признаков методами StandardScaler, MinMaxScaler, RobustScaler, QuantileTransformer или PowerTransformer. Критично для NN, SVM, k-NN." },
  { id: "passport", label: "Паспорт свойств ряда", status: "pending", count: null,
    description: "Сравнительный анализ свойств ряда: v1.0 (загрузка) → v1.1 (после валидации) → v1.2 (после предобработки). Метрики: ADF, Ljung-Box, Jarque-Bera, R². Экспорт в Excel." },
];

// ── Справка по целям модуля «Предобработка» (из app.py) ───────────

const PREPROCESSING_HELP = `Цели модуля "Предобработка"

Большинство классических моделей временных рядов и нейросетей предъявляют строгие требования к данным:
- отсутствие пропусков
- стационарность
- гомоскедастичность
- нормальность распределения и др.

Цель раздела. Применить математические преобразования, чтобы удовлетворить эти требования, сохранив при этом полезный сигнал (тренд, цикличность, сезонность). Предобработка решает задачу превращения данных в формат, пригодный для машинного обучения.

Что мы получим на выходе? Применив обратные преобразования после предобработки, мы имеем трансформированный датасет, готовый к загрузке в блок «Моделирование». Пользователь получает рекомендации по доступным моделям прогнозирования и сравнительные паспорта свойств ряда для анализа их изменения:
- v1.0 до валидации vs v1.3 после предобработки
- v1.2 до предобработки vs v1.3 после предобработки

Пайплайн предобработки (11 шагов):
1. Пропуски — интерполяция, forward-fill, mean, drop
2. Выбросы — IQR, Z-score, MAD, Isolation Forest, LOF
3. Регулярность ряда — интерполяция gaps, ресемплирование
4. Декомпозиция — STL / Classical / SEATS / X13
5. Стабилизация дисперсии — Box-Cox, Yeo-Johnson, log, sqrt
6. Сглаживание — SMA, EMA, Holt-Winters, HP-filter, Kalman
7. Стационарность — дифференцирование d/D, контроль ADF/KPSS/PP
8. Спектральный анализ — FFT, periodogram, вейвлет
9. Генерация признаков — время, лаги, rolling, производные
10. Масштабирование — Standard, MinMax, Robust, Quantile, Power
11. Паспорт свойств ряда — сравнение v1.0 → v1.1 → v1.2`;

// ── Метрики и алгоритм / Мастер: остановка «Пропуски» ─────────────
// Единственная остановка степпера с реальным backend -- см.
// app/preprocessing/missing.py, apps/api/missing_correction.py. Формат
// текста -- по образцу RANGES_METRICS_DESCRIPTION/RANGES_PIPELINE_DESCRIPTION
// из TsAnalysisValidation.tsx (Цель / Метрики / Алгоритм backend /
// опциональный смысловой блок; отдельная константа для мастера).

const MISSING_METRICS_DESCRIPTION = `Метрики и алгоритм: Пропуски

Цель
Проверка находит пропущенные значения в каждой колонке активного датасета. Пропуски разрывают непрерывность DatetimeIndex, делают невозможной STL-декомпозицию, искажают ACF/PACF и не позволяют напрямую обучать ARIMA/SARIMA. В отличие от проверок «Валидации» (диапазоны, форматы, ссылочная целостность...), у «Пропусков» нет отдельного настраиваемого правила: проверка безусловна для любой колонки любого датасета — режим «Отключена» лишь исключает остановку из прогресса, а не меняет саму логику подсчёта.

Метрики
1. N_missing = Σ isnull() по всем ячейкам датасета — суммарное число пропусков.
2. r_missing = N_missing / (rows × columns) × 100 — доля пропущенных ячеек.
3. Rows with missing / Empty rows — число строк с хотя бы одним пропуском и строк, где пропущены абсолютно все значения (кандидаты на безусловное удаление).
4. По каждой колонке: dtype, семантический класс (numeric / datetime / categorical / text), missing_count и missing_pct, до 5 примеров индексов строк с пропуском.

Алгоритм backend
1. GET /v1/session/dataset/missing-profile получает полный DataFrame активной сессии.
2. profile_missing(df) строит профиль по КАЖДОЙ колонке без исключений — включая колонки с 0 пропусков, чтобы степпер честно показывал «Проверка пройдена», а не молчание.
3. Семантический класс и доля пропусков определяют рекомендованную стратегию: >50% пропусков или <5% числовых пропусков → «удалить строки»; категориальная/текстовая колонка → «медиана/мода»; иначе → «медиана/мода».
4. missing_summary(df) агрегирует сводку по датасету; missing_per_row_histogram(df) готовит распределение числа пропусков на строку.
5. status = done, если пропусков нет; warning — если найдены; skipped — если проверка отключена аналитиком либо в датасете нет ни одной колонки.

Механизм пропусков (MCAR / MAR / MNAR)
Стратегии «медиана/мода», «среднее/мода» и линейная интерполяция статистически корректны только при пропусках, полностью случайных (MCAR) или случайных при условии наблюдаемых данных (MAR). Если же пропуск связан с ненаблюдаемым значением самой переменной (MNAR — например, датчик не пишет показание именно в момент экстремума), заполнение центральной тенденцией смещает оценки.`;

const MISSING_PIPELINE_DESCRIPTION = `Мастер исправления пропусков

1. Отметьте колонки с пропусками. Список предзаполнен колонками, где найден хотя бы один пропуск; интерполяция автоматически снимает отметку с нечисловых колонок при выборе этой стратегии.
2. Выберите одну из шести стратегий: удаление строк (объединение пропусков только по отмеченным колонкам), медиана/мода, среднее/мода, ноль/Unknown, линейная интерполяция (только числовые колонки) либо флаг пропуска (сохраняет исходные значения, добавляет индикаторную колонку *_missing_flag).
3. Запустите «Предпросмотр изменений». Расчёт выполняется на копии датасета и не меняет активные данные: вы увидите число исправленных значений, оставшиеся пропуски и — в блоке «Прогноз влияния на статистики» — среднее, медиану и стандартное отклонение каждой числовой колонки до и после применения стратегии.
4. Оцените прогноз: заметный сдвиг среднего или резкое падение стандартного отклонения — сигнал, что выбранная стратегия слишком агрессивно сглаживает эту колонку; в этом случае вернитесь к шагу 2 и попробуйте другую стратегию.
5. Подтвердите применение отдельным чекбоксом и нажмите «Применить исправления». Подготовленная копия сохраняется в сессии атомарно, после чего профиль пропусков и статус остановки пересчитываются автоматически.`;

const OUTLIERS_METRICS_DESCRIPTION = `Метрики и алгоритм: Выбросы

Цель
Проверка находит аномальные значения в каждой числовой колонке активного датасета. Выбросы завышают дисперсию, искажают оценку тренда и линейную регрессию, ломают тесты стационарности (ADF/KPSS) и STL-декомпозицию (один большой выброс сильно смещает оценку сезонности даже у устойчивого STL).

Метрики
1. Четыре метода на выбор: IQR (границы Q1 − k×IQR / Q3 + k×IQR, устойчив по умолчанию), Z-score (|значение − среднее| / std), Modified Z-score / MAD (то же на медиане — устойчив при асимметрии), процентильный (явные нижняя/верхняя границы).
2. По каждой числовой колонке: sample_size, outlier_count и outlier_pct, границы метода (для IQR/процентильного — в исходной шкале величины; для Z-score/MAD границ в исходной шкале нет, они работают в стандартизованных единицах), до 5 примеров индексов строк-выбросов.
3. Колонки с sample_size < 10 помечаются «недостаточно наблюдений» — статистика на таких выборках неустойчива, outlier_count принудительно 0, а не ложный результат.

Алгоритм backend
1. GET /v1/session/dataset/outlier-profile?method=... получает полный DataFrame активной сессии.
2. profile_outliers(df) строит профиль по КАЖДОЙ числовой колонке без исключений (включая 0 выбросов) — как и profile_missing; нечисловые колонки не входят в профиль вовсе (метод статистически не определён для текста/категорий).
3. Рекомендация метода на колонку: выборка < 100 → IQR; |асимметрия| > 2 → Modified Z-score (MAD); иначе → Z-score — перенос эвристики легаси app.py.
4. status = done, если выбросов нет; warning — если найдены; skipped — если проверка отключена аналитиком либо в датасете нет числовых колонок.

Позиция: «выбросы можно обрабатывать только по остатку после декомпозиции»?
Мнение статистически обосновано — точка, необычная в сырых значениях (например, декабрьский пик продаж), может быть законной сезонностью, а не аномалией; общепринятая практика (Hyndman & Athanasopoulos) — искать аномалию в ОСТАТКЕ после STL, а не в сырых данных. Тем не менее делать это ЕДИНСТВЕННЫМ способом здесь архитектурно неверно: (1) «Выбросы» в степпере идёт ДО «Регулярности» и «Декомпозиции» — регулярный DatetimeIndex на этом этапе не гарантирован; (2) для панельных/кросс-секционных датасетов (несколько строк на одну дату — например, тестовый датасет FAO «Страна × Год») декомпозиции не существует ни для одной колонки в принципе — сделать её обязательной оставило бы аналитика без единого способа обработать явную ошибку ввода; (3) сам выброс искажает декомпозицию (обратная связь). Решение: методы одинаково применимы к сырым значениям ИЛИ к остатку — различие не в алгоритме, а в том, какой ряд ему подать. Профиль всегда на сырых значениях (безусловная диагностика); обнаружение на остатке — опциональная явно запрашиваемая возможность мастера, доступная только когда декомпозиция для конкретной пары колонок применима.`;

const OUTLIERS_PIPELINE_DESCRIPTION = `Мастер исправления выбросов

1. Отметьте числовые колонки с выбросами. Список предзаполнен колонками, где найден хотя бы один выброс выбранным методом.
2. Выберите метод обнаружения (IQR / Z-score / Modified Z-score (MAD) / процентильный) и его параметр. По умолчанию — обнаружение на сырых значениях. Если выбрана РОВНО одна колонка и в датасете есть подходящая колонка с датой, доступен переключатель «Обнаруживать на остатке после STL-декомпозиции» — включите его, если считаете, что выброс нужно оценивать относительно ожидаемого сезонного уровня, а не абсолютной величины (см. позицию в «Метрики и алгоритм» выше).
3. Выберите стратегию исправления: удаление строк, кэпирование (winsorize по границам 1.5×IQR — не зависит от выбранного метода обнаружения), замена медианой (не-выбросных значений) либо флаг выброса (сохраняет исходные значения, добавляет индикаторную колонку *_outlier_flag).
4. Запустите «Предпросмотр изменений». Расчёт выполняется на копии датасета и не меняет активные данные: вы увидите число найденных и исправленных выбросов, оставшиеся выбросы и — при выборе обнаружения на остатке — явную отметку об этом в результате.
5. Подтвердите применение отдельным чекбоксом и нажмите «Применить исправления». Подготовленная копия сохраняется в сессии атомарно, после чего профиль выбросов и статус остановки пересчитываются автоматически.`;

const REGULARITY_METRICS_DESCRIPTION = `Метрики и алгоритм: Регулярность ряда

Цель
Проверка находит нарушения равномерности временного шага: разрывы (пропущенные периоды), дубликаты дат, нарушения хронологического порядка и некорректные значения даты. Нерегулярный шаг делает невозможной STL-декомпозицию и спектральный анализ (FFT/периодограмма требуют равномерной сетки) и искажает автокорреляцию (ACF/PACF) моделей ARIMA/SARIMA.

Метрики
1. Колонка даты и колонка сущности (для панельных датасетов — несколько строк на одну дату, например «Страна × Год») определяются автоматически по тем же content-детекторам, что использует остальная платформа.
2. Целевая частота: если задана явно (например, в правилах «Валидации») — учитывается календарная нерегулярность месяцев/кварталов/лет через date_range, а не наивное сравнение Timedelta; если нет — определяется по модальному интервалу между наблюдениями.
3. Разрыв — интервал между соседними уникальными датами больше modal_interval × gap_threshold_multiplier (по умолчанию 1.5 — тот же коэффициент, что и у IQR-метода в «Выбросах»). Мода, а не среднее/медиана — устойчива к календарным различиям длины месяца.
4. По каждой группе (сущности): число наблюдений, обнаруженная частота, разрывы, дубликаты, нарушения сортировки, до 5 примеров разрывов с датами и числом пропущенных периодов.

Алгоритм backend
1. GET /v1/session/dataset/preprocessing/regularity-profile переиспользует profile_regularity (validation/regularity.py) — тот же движок, что уже работает в «Валидации» (там — как отдельная DQ-проверка с настраиваемым правилом), но здесь без per-колоночных правил: применимость и обнаружение безусловны, как у «Пропусков»/«Выбросов».
2. Панельные датасеты обрабатываются группа за группой — разрыв в одной сущности не путается с обычным интервалом между сущностями.
3. status = done, если нарушений нет; warning — если найдены; skipped — если проверка отключена аналитиком либо колонка даты не определена автоматически (например, чисто кросс-секционные данные без временной оси).

Оценка методологии
Модальный интервал (а не среднее или медиана) — методологически корректный выбор для порога разрыва: устойчив к тому, что настоящие календарные частоты (месяц, квартал) физически имеют переменную длину в днях, а мода схватывает «типичный шаг» вне зависимости от единичных выбросов в самих интервалах. Коэффициент 1.5 — тот же IQR-подобный эвристический множитель, что уже принят на платформе для выбросов; отдельного обоснования именно для регулярности в источниках нет, но согласованность с остальной платформой — осознанный выбор, а не недосмотр. Существенная корректировка методологии не потребовалась.`;

const REGULARITY_PIPELINE_DESCRIPTION = `Мастер исправления регулярности

1. Выберите стратегию: «Отсортировать по дате» (только переупорядочивает строки, не создаёт/не удаляет данные); «Ресемплировать + …» (интерполяция / forward fill / backward fill / ноль-Unknown / без заполнения) приводит ряд к регулярной сетке целевой частоты; «Только пометить флагом» не меняет данные, добавляет индикаторную колонку _has_gap.
2. Для стратегий с ресемплированием укажите целевую частоту (pandas-alias: D, W, MS, QS, YS, h, min и т.п.) — по умолчанию подставлена автоматически определённая частота.
3. Запустите «Предпросмотр изменений». Расчёт выполняется на копии датасета и не меняет активные данные: вы увидите изменение числа нарушений и строк (ресемплирование добавляет строки на месте разрывов), число агрегированных дублей.
4. Подтвердите применение отдельным чекбоксом и нажмите «Применить исправления». Подготовленная копия сохраняется в сессии атомарно, после чего профиль регулярности и статус остановки пересчитываются автоматически.
5. Совет: если дальше в пайплайне планируется декомпозиция или спектральный анализ, выбирайте стратегию с ресемплированием (не «Отсортировать» и не «Флаг») — этим шагам нужна физически регулярная сетка дат, а не просто отсутствие явных «разрывов» в отсортированном ряду.`;

type PreprocessingCheckMode = "auto" | "enabled" | "disabled";

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // Общий target_column вместо сломанного mock-списка тикеров. Хук
  // восстанавливает сохранённый выбор из AnalysisSession либо один раз
  // фиксирует backend-рекомендацию (первая числовая, кроме временной оси).
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    loading: targetLoading,
    error: targetError,
    setColumn: setActiveFeature,
  } = useTargetColumn(undefined);

  // ── Режимы остановок (Task 47, применено к «Предобработке») ──
  // «Авто» / «Включена» / «Отключена» -- сохраняются в сессии через
  // GET/PUT /dataset/preprocessing-check-modes, отдельно от режимов
  // «Валидации» (другой степпер, другой словарь на бэкенде). Только
  // «Пропуски» реально реагируют на режим сегодня -- у остальных 10
  // остановок ещё нет backend-проверки, которую можно включить/отключить,
  // поэтому селектор режима показан только для «Пропусков»: показывать
  // его для мока значило бы обещать эффект, которого нет.
  const [checkModes, setCheckModes] = useState<Record<string, PreprocessingCheckMode>>({});
  const [modeSaving, setModeSaving] = useState<string | null>(null);
  const [modeError, setModeError] = useState<{ checkId: string; message: string } | null>(null);

  // ── Остановка «Пропуски»: реальный статус вместо мока ──
  // Лёгкий собственный запрос профиля (тот же /dataset/missing-profile,
  // что использует и PreprocessingMissingOverview) -- нужен здесь отдельно,
  // чтобы степпер слева и статус-бейдж справа отражали состояние даже пока
  // Overview/Pipeline ещё не смонтированы (активна другая проверка).
  // Дублирование запроса такое же, как между /dataset/validate и
  // /dataset/range-profile в TsAnalysisValidation.tsx -- уже принятый
  // в проекте компромисс между простотой компонента и числом запросов.
  const [missingProfile, setMissingProfile] = useState<MissingProfileResponse | null>(null);
  const [missingLoading, setMissingLoading] = useState(true);
  const [missingNoDataset, setMissingNoDataset] = useState(false);
  const [missingError, setMissingError] = useState<string | null>(null);
  const [missingRefreshKey, setMissingRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setMissingLoading(true);
    setMissingError(null);
    setMissingNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/missing-profile"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setMissingNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: MissingProfileResponse = await response.json();
        if (active) {
          setMissingProfile(data);
          setCheckModes((current) => ({ ...current, missing: data.mode }));
        }
      } catch (caught) {
        if (active) setMissingError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль пропусков");
      } finally {
        if (active) setMissingLoading(false);
      }
    })();
    return () => { active = false; };
  }, [missingRefreshKey]);

  // Режим и статус остановки «Пропуски» приходят напрямую с бэкенда
  // (единый источник истины -- та же политика auto/enabled/disabled, что
  // применяется к /dataset/missing-profile). "skipped" покрывает и явное
  // отключение, и нейтральную неприменимость (0 колонок) -- разница
  // передаётся через status_reason, не через отдельные значения иконки.
  const missingStatus: CheckStatus = missingLoading
    ? "running"
    : missingNoDataset
    ? "skipped"
    : missingError
    ? "error"
    : missingProfile
    ? missingProfile.status
    : "pending";

  // ── Остановка «Выбросы»: тот же паттерн, что и «Пропуски» ──
  const [outliersProfile, setOutliersProfile] = useState<OutlierProfileResponse | null>(null);
  const [outliersLoading, setOutliersLoading] = useState(true);
  const [outliersNoDataset, setOutliersNoDataset] = useState(false);
  const [outliersError, setOutliersError] = useState<string | null>(null);
  const [outliersRefreshKey, setOutliersRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setOutliersLoading(true);
    setOutliersError(null);
    setOutliersNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/outlier-profile?method=iqr"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setOutliersNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: OutlierProfileResponse = await response.json();
        if (active) {
          setOutliersProfile(data);
          setCheckModes((current) => ({ ...current, outliers: data.mode }));
        }
      } catch (caught) {
        if (active) setOutliersError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль выбросов");
      } finally {
        if (active) setOutliersLoading(false);
      }
    })();
    return () => { active = false; };
  }, [outliersRefreshKey]);

  const outliersStatus: CheckStatus = outliersLoading
    ? "running"
    : outliersNoDataset
    ? "skipped"
    : outliersError
    ? "error"
    : outliersProfile
    ? outliersProfile.status
    : "pending";

  // ── Остановка «Регулярность»: тот же паттерн ──
  const [regularityProfile, setRegularityProfile] = useState<RegularityProfileResponse | null>(null);
  const [regularityLoading, setRegularityLoading] = useState(true);
  const [regularityNoDataset, setRegularityNoDataset] = useState(false);
  const [regularityError, setRegularityError] = useState<string | null>(null);
  const [regularityRefreshKey, setRegularityRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setRegularityLoading(true);
    setRegularityError(null);
    setRegularityNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/preprocessing/regularity-profile"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setRegularityNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: RegularityProfileResponse = await response.json();
        if (active) {
          setRegularityProfile(data);
          setCheckModes((current) => ({ ...current, regularity: data.mode }));
        }
      } catch (caught) {
        if (active) setRegularityError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль регулярности");
      } finally {
        if (active) setRegularityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [regularityRefreshKey]);

  const regularityStatus: CheckStatus = regularityLoading
    ? "running"
    : regularityNoDataset
    ? "skipped"
    : regularityError
    ? "error"
    : regularityProfile
    ? regularityProfile.status
    : "pending";

  // Итоговый список проверок -- статика для ещё не реализованных
  // остановок, реальные данные для «Пропусков», «Выбросов» и «Регулярности».
  const checks = useMemo<Check[]>(() => CHECKS.map((check) => {
    if (check.id === "missing") return { ...check, status: missingStatus, count: missingProfile?.total_missing ?? null };
    if (check.id === "outliers") return { ...check, status: outliersStatus, count: outliersProfile?.total_outliers ?? null };
    if (check.id === "regularity") return { ...check, status: regularityStatus, count: regularityProfile?.profile?.total_violations ?? null };
    return check;
  }), [missingStatus, missingProfile, outliersStatus, outliersProfile, regularityStatus, regularityProfile]);

  // Сворачиваем при смене секции
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

  // Click-outside: сворачиваем при клике вне description box
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (descRef.current && !descRef.current.contains(e.target as Node)) {
      setDescriptionExpanded(false);
    }
  }, []);
  useEffect(() => {
    if (descriptionExpanded) {
      document.addEventListener("mousedown", handleOutsideClick);
      return () => document.removeEventListener("mousedown", handleOutsideClick);
    }
  }, [descriptionExpanded, handleOutsideClick]);

  // Отключённые и нейтрально неприменимые остановки исключаются из
  // прогресса -- та же политика, что применена к DQ Score «Валидации»
  // в Task 47 (applicableChecks/evaluatedChecks).
  const applicableChecks = checks.filter((c) => c.status !== "skipped");
  const doneCount = applicableChecks.filter((c) => c.status === "done").length;
  const progressPct = applicableChecks.length > 0
    ? Math.round((doneCount / applicableChecks.length) * 100)
    : 100;
  const activeCheck = checks.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...checks].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  const handleCheckModeChange = async (checkId: string, mode: PreprocessingCheckMode) => {
    if (modeSaving) return;
    const previous = checkModes;
    setCheckModes((current) => ({ ...current, [checkId]: mode }));
    setModeSaving(checkId);
    setModeError(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing-check-modes"), {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modes: { [checkId]: mode } }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // Режим сохранён -- запускаем повторную проверку затронутой
      // остановки, чтобы степпер/панель немедленно отразили новый режим
      // (та же идея, что runValidation() после смены режима в Validation).
      if (checkId === "missing") setMissingRefreshKey((k) => k + 1);
      if (checkId === "outliers") setOutliersRefreshKey((k) => k + 1);
      if (checkId === "regularity") setRegularityRefreshKey((k) => k + 1);
    } catch {
      setCheckModes(previous);
      setModeError({ checkId, message: "Не удалось сохранить режим проверки" });
    } finally {
      setModeSaving(null);
    }
  };

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  // Показать/скрыть справку по целям модуля
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? null : "help");
  };

  // ── Overflow detection для expandable description ──
  useEffect(() => {
    const el = descRef.current;
    if (!el) return;
    const checkOverflow = () => {
      setHasOverflow(el.scrollHeight > el.clientHeight + 2);
    };
    checkOverflow();
    const observer = new ResizeObserver(checkOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [descriptionSection]); // ResizeObserver отслеживает контент

  // Текст описания для центрального поля — вычисляется из активной проверки и секции
  const descriptionContent = (() => {
    if (descriptionSection === "help") return PREPROCESSING_HELP;
    if (!descriptionSection) return null;
    if (activeCheckId === "missing") {
      return descriptionSection === "metrics" ? MISSING_METRICS_DESCRIPTION : MISSING_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "outliers") {
      return descriptionSection === "metrics" ? OUTLIERS_METRICS_DESCRIPTION : OUTLIERS_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "regularity") {
      return descriptionSection === "metrics" ? REGULARITY_METRICS_DESCRIPTION : REGULARITY_PIPELINE_DESCRIPTION;
    }
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты прохождения";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (activeCheckId === "missing") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Пропуски" : "Мастер исправления пропусков";
    }
    if (activeCheckId === "outliers") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Выбросы" : "Мастер исправления выбросов";
    }
    if (activeCheckId === "regularity") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Регулярность" : "Мастер исправления регулярности";
    }
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
    <div className="flex gap-6">
      {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0">
              Preprocessing
            </h2>
            <button
              onClick={handleHelpClick}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
            >
              Справка
            </button>
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Математические преобразования
          </p>
        </div>

        {/* Селектор числового признака */}
        <div>
          <label htmlFor="preprocessing-active-feature" className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            id="preprocessing-active-feature"
            value={activeFeature ?? ""}
            onChange={(e) => void setActiveFeature(e.target.value)}
            disabled={targetLoading || numericFeatures.length === 0}
            className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {numericFeatures.length ? (
              numericFeatures.map((feature) => (
                <option key={feature} value={feature}>{feature}</option>
              ))
            ) : (
              <option value="">Нет числовых признаков</option>
            )}
          </select>
          {targetError && (
            <p role="alert" className="mt-1 text-[10px] text-red-600">
              Не удалось синхронизировать признак: {targetError}
            </p>
          )}
        </div>

        {/* Прогресс */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {doneCount}/{applicableChecks.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: прямоугольные карточки с текстом + иконка */}
        <div className="flex flex-col gap-1.5">
          {checks.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                if (descriptionSection === "help") setDescriptionSection(null);
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                <StatusIcon status={check.status} />
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: метрики-текст + график + метрики-карточки ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          {/* ── Expandable Description Box ──
              collapsed: min-h=220px, max-h=220px, scroll (in-flow)
              expanded: position:absolute overlay over graph, max-h=calc(100vh-180px)
              chevron: shown only when hasOverflow
          */}
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionContent || (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Полный пайплайн» или «Справка»
                </span>
              )}
              {/* Collapse chevron — sticky прилипает к низу scroll-области */}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    onClick={() => setDescriptionExpanded(false)}
                    className="flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                    aria-label="Свернуть описание"
                    data-testid="desc-collapse-btn"
                  >
                    <ChevronUp size={14} />
                  </button>
                </div>
              )}
            </div>
            {/* Expand chevron — только при overflow, collapsed */}
            {hasOverflow && !descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(true)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Развернуть описание"
                data-testid="desc-expand-btn"
              >
                <ChevronDown size={14} />
              </button>
            )}
          </div>
        </div>

        {/* График / Обзор / Мастер исправления */}
        <div>
          <h3 className="font-semibold mb-1">
            {activeCheckId === "missing" && descriptionSection === "pipeline"
              ? "Мастер исправления пропусков"
              : activeCheckId === "outliers" && descriptionSection === "pipeline"
              ? "Мастер исправления выбросов"
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Мастер исправления регулярности"
              : `Обзор: ${activeCheck.label}`}
          </h3>
          <p className="text-xs text-neutral-500 mb-3">
            {activeCheckId === "missing" && descriptionSection === "pipeline"
              ? "Выберите колонки и стратегию, оцените последствия на копии и примените исправления."
              : activeCheckId === "missing"
              ? "Полнота данных по колонкам, рекомендованная стратегия исправления."
              : activeCheckId === "outliers" && descriptionSection === "pipeline"
              ? "Выберите колонку, метод и стратегию; обнаружение — на сырых значениях или (опционально) на остатке после STL-декомпозиции."
              : activeCheckId === "outliers"
              ? "Выбросы по числовым колонкам методом IQR, границы и рекомендованный метод на колонку."
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Выберите стратегию и целевую частоту, оцените последствия на копии и примените исправления."
              : activeCheckId === "regularity"
              ? "Разрывы, дубликаты и нарушения сортировки по группам; интервалы и таймлайн — во вкладках."
              : "Меняется автоматически под активную проверку."}
          </p>

          {activeCheckId === "missing" && descriptionSection === "pipeline" ? (
            <PreprocessingMissingPipeline onApplied={() => setMissingRefreshKey((k) => k + 1)} />
          ) : activeCheckId === "missing" ? (
            <PreprocessingMissingOverview refreshKey={missingRefreshKey} />
          ) : activeCheckId === "outliers" && descriptionSection === "pipeline" ? (
            <PreprocessingOutliersPipeline onApplied={() => setOutliersRefreshKey((k) => k + 1)} />
          ) : activeCheckId === "outliers" ? (
            <PreprocessingOutliersOverview refreshKey={outliersRefreshKey} column={activeFeature} />
          ) : activeCheckId === "regularity" && descriptionSection === "pipeline" ? (
            <PreprocessingRegularityPipeline onApplied={() => setRegularityRefreshKey((k) => k + 1)} />
          ) : activeCheckId === "regularity" ? (
            <PreprocessingRegularityOverview refreshKey={regularityRefreshKey} />
          ) : (
            <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
              [ график для «{activeCheck.label}» ]
            </div>
          )}

          {activeCheckId === "missing" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value={missingProfile ? String(missingProfile.total_rows) : "—"} />
              <Metric label="Колонок" value={missingProfile ? String(missingProfile.total_columns) : "—"} />
              <Metric label="Пропусков" value={missingProfile ? String(missingProfile.total_missing) : "—"} />
              <Metric label="Строк с пропуском" value={missingProfile ? String(missingProfile.rows_with_missing) : "—"} />
            </div>
          ) : activeCheckId === "outliers" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value={outliersProfile ? String(outliersProfile.total_rows) : "—"} />
              <Metric label="Числовых колонок" value={outliersProfile ? String(outliersProfile.total_numeric_columns) : "—"} />
              <Metric label="Выбросов" value={outliersProfile ? String(outliersProfile.total_outliers) : "—"} />
              <Metric label="Затронуто колонок" value={outliersProfile ? String(outliersProfile.affected_columns.length) : "—"} />
            </div>
          ) : activeCheckId === "regularity" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Разрывов" value={regularityProfile ? String(regularityProfile.profile.gap_count) : "—"} />
              <Metric label="Дублей" value={regularityProfile ? String(regularityProfile.profile.duplicate_count) : "—"} />
              <Metric label="Нарушений сортировки" value={regularityProfile ? String(regularityProfile.profile.sort_violations) : "—"} />
              <Metric label="Частота" value={regularityProfile?.profile.target_frequency ?? "—"} />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value="200" />
              <Metric label="Пропусков" value="11" />
              <Metric label="Выбросов" value="1145" />
              <Metric label="ADF p" value="0.03" />
              <Metric label="Частота" value="D" />
            </div>
          )}
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список проверок ── */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={check.status} /> Преобразование: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Режим проверки -- только для «Пропусков» и «Выбросов»:
                  у остальных остановок ещё нет backend-проверки, которую
                  можно реально включить/отключить (см. комментарий у
                  useState checkModes выше). */}
              {(check.id === "missing" || check.id === "outliers" || check.id === "regularity") && (
                <label className="mb-2 block text-[11px] font-medium text-neutral-600">
                  Режим проверки
                  <select
                    aria-label={`Режим проверки ${check.label}`}
                    value={checkModes[check.id] ?? "auto"}
                    disabled={modeSaving !== null}
                    onChange={(event) => void handleCheckModeChange(check.id, event.target.value as PreprocessingCheckMode)}
                    className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm font-normal text-neutral-800 focus:outline-none focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <option value="auto">Авто</option>
                    <option value="enabled">Включена</option>
                    <option value="disabled">Отключена</option>
                  </select>
                </label>
              )}
              {modeSaving === check.id && (
                <p role="status" className="mb-2 text-[11px] text-brand">Сохранение режима…</p>
              )}
              {modeError?.checkId === check.id && (
                <p role="alert" className="mb-2 text-[11px] text-red-700">{modeError.message}</p>
              )}

              {/* Бейдж результата -- для «Пропусков»/«Выбросов» все
                  состояния явно различимы; для остальных (ещё не
                  подключённых) остановок -- прежняя упрощённая логика
                  по count/status. */}
              {check.id === "missing" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {missingError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {missingNoDataset
                        ? "Нет активного датасета"
                        : missingProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} пропусков
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, пропусков нет
                    </p>
                  )}
                </>
              ) : check.id === "outliers" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {outliersError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {outliersNoDataset
                        ? "Нет активного датасета"
                        : outliersProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} выбросов
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, выбросов нет
                    </p>
                  )}
                </>
              ) : check.id === "regularity" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {regularityError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {regularityNoDataset
                        ? "Нет активного датасета"
                        : regularityProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} нарушений регулярности
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, нарушений нет
                    </p>
                  )}
                </>
              ) : (
                <>
                  {check.count !== null && check.count > 0 && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      ⚠️ Найдено {check.count} нарушений
                    </p>
                  )}
                  {check.status === "done" && (
                    <p className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, нарушений нет
                    </p>
                  )}
                </>
              )}

              {/* Кнопка «Метрики и алгоритм» -- активирует контент в центральном поле */}
              <button
                onClick={() => handleDescriptionClick(check, "metrics")}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Для реализованных остановок открывается специализированный мастер. */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                {check.id === "missing" ? "Исправить пропуски" : check.id === "outliers" ? "Исправить выбросы" : check.id === "regularity" ? "Исправить регулярность" : "Полный пайплайн"}
              </button>

              <Button>Пересчитать свойства после преобразования ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
