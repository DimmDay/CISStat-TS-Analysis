"use client";

// packages/ui/components/TsAnalysisEDA.tsx
//
// ОБЩИЙ компонент фичи "Разведочный EDA" -- используется И embedded-,
// И standalone-приложением. Структура повторяет 3-колоночный лейаут
// TsAnalysisPreprocessing/TsAnalysisValidation.
//
// Компоновка:
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   EDA  [Справка]      Описание               Исследование: ...
//   ▼ Признак: price   [текстовое поле]       описание
//   0/11 ░░░░░░         Обзор: ...             [бейдж]
//   ┌─Описательные──○─┐  [график]              [Метрики и алгоритм]
//   ├─ACF/PACF────○─┤   [карточки]            [Полный пайплайн]
//   └────────────────┘                         [Запустить анализ]

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { sessionApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";
import { Button } from "./Button";
import {
  EdaDescriptiveOverview,
  type DescriptiveStatsResponse,
} from "./EdaDescriptiveOverview";
import {
  EdaCorrelationOverview,
  type EdaCorrelationResponse,
} from "./EdaCorrelationOverview";
import {
  EdaIhOverview,
  type EdaIhParameters,
  type EdaIhResponse,
} from "./EdaIhOverview";
import {
  EdaSeasonalityOverview,
  type EdaSeasonalityParameters,
  type EdaSeasonalityResponse,
} from "./EdaSeasonalityOverview";
import {
  EdaStationarityOverview,
  type EdaStationarityParameters,
  type EdaStationarityResponse,
  type StationarityConsensus,
} from "./EdaStationarityOverview";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── 11 исследований EDA ──────────────────────────────────────

const CHECKS: Check[] = [
  { id: "descriptive", label: "Описательные статистики", status: "pending", count: null,
    description: "Mean, median, std, квартильный профиль, skewness и excess kurtosis по каждому числовому признаку текущего преобразованного датасета. Таблица и три переключаемые визуализации помогают оценить масштаб, вариативность, асимметрию и тяжесть хвостов перед дальнейшим EDA." },
  { id: "correlation", label: "Корреляция (ACF/PACF)", status: "pending", count: null,
    description: "Автокорреляционная и частная автокорреляционная функции с доверительными интервалами. Ключевой вход для идентификации ARIMA-порядков (p, q). Сезонные ACF/PACF при наличии сезонности." },
  { id: "ih_analysis", label: "IH-анализ", status: "pending", count: null,
    description: "Information-Entropy анализ факторов X относительно исследуемой цели Y: энтропия Шеннона, взаимная информация и нормированная мера R(Y|X). Работает с нелинейными связями, категориями, пропусками, лагами цели и комбинациями факторов; перестановочная проверка отделяет устойчивый сигнал от смещения дискретизации." },
  { id: "seasonality", label: "Сезонность и периодичность", status: "pending", count: null,
    description: "FFT и периодограмма равномерного преобразованного ряда после линейного detrend и окна Hann. Спектральные пики проверяются через ACF и фазовый профиль; поддерживаются несколько периодов и маркировка гармоник." },
  { id: "stationarity", label: "Верификация стационарности", status: "pending", count: null,
    description: "Финальная проверка ADF/KPSS/PP на полностью преобразованном ряде. Скользящие mean/std. Автоматическая рекомендация: «ряд стационарен — ARIMA применима» или «вернитесь к шагу 7 Предобработки»." },
  { id: "distribution", label: "Распределение", status: "pending", count: null,
    description: "Гистограмма + плотность N(0,σ²), QQ-plot, тесты Jarque-Bera / Shapiro-Wilk / Kolmogorov-Smirnov. Вывод о корректности доверительных интервалов модели." },
  { id: "structural", label: "Структурные сдвиги", status: "pending", count: null,
    description: "Поиск точек regime change: CUSUM, Chow test, PELT. Визуализация с аннотациями. Рекомендация: «обучать на периоде после [date]» или «использовать модель с переключением режимов»." },
  { id: "feature_select", label: "Отбор признаков", status: "pending", count: null,
    description: "Корреляционная матрица сгенерированных признаков, VIF (Variance Inflation Factor), Granger causality для многомерных моделей. Рекомендация: оставить N значимых из M сгенерированных." },
  { id: "validation_strategy", label: "Стратегия валидации", status: "pending", count: null,
    description: "Выбор схемы разбиения: expanding window / sliding window / single split. Визуализация train/test на графике. Задание горизонта прогноза. Проверка достаточности наблюдений в train." },
  { id: "model_matrix", label: "Матрица моделей", status: "pending", count: null,
    description: "Таблица применимости: модель → требование → статус ряда → вывод. ARIMA, SARIMA, Prophet, LSTM, VAR, XGBoost и др. Автоматическая фильтрация по свойствам ряда." },
  { id: "passport", label: "Паспорт свойств ряда", status: "pending", count: null,
    description: "Финальная сводка конвейера: v1.0 (загрузка) → v1.1 (валидация) → v1.2 (предобработка) → v1.3 (EDA). Включает ACF-структуру, энтропийные метрики, стационарность, рекомендованные модели. Экспорт в Excel." },
];

// ── Справка по целям модуля «Разведочный EDA» ────────────────

const EDA_HELP = `Цели модуля "Разведочный EDA"

После валидации и предобработки данные очищены и трансформированы, но прежде чем выбирать и обучать модель, необходимо понять их статистические свойства, структуру зависимостей и пределы применимости различных моделей.

Цель раздела. Провести финальное разведочное исследование преобразованного временного ряда, верифицировать выполнение требований моделей и сформировать рекомендацию по выбору класса моделей прогнозирования.

Что мы получим на выходе? Аналитик получает:
- Подтверждение стационарности и нормальности остатков
- Идентификацию ACF/PACF структуры для ARIMA (p,d,q)
- Оценку предсказуемости ряда через энтропийные метрики
- Обнаружение структурных сдвигов и рекомендацию периода обучения
- Отбор значимых признаков с исключением мультиколлинеарности
- Стратегию временной валидации (train/test split)
- Матрицу применимости моделей с автоматической фильтрацией
- Финальный паспорт свойств ряда v1.0 → v1.3

Пайплайн EDA (11 шагов):
1. Описательные статистики — mean, std, skew, kurtosis
2. Корреляция (ACF/PACF) — линейная структура, идентификация (p,q)
3. IH-анализ — нелинейная структура, предсказуемость (энтропия)
4. Сезонность и периодичность — FFT, доминантные частоты
5. Верификация стационарности — ADF/KPSS/PP, финальная проверка
6. Распределение — нормальность, QQ-plot, JB/SW тесты
7. Структурные сдвиги — CUSUM, Chow, regime changes
8. Отбор признаков — VIF, Granger causality, мультиколлинеарность
9. Стратегия валидации — expanding/sliding window, горизонт
10. Матрица моделей — рекомендация по применимости
11. Паспорт свойств ряда — сводка v1.0 → v1.3`;

const DESCRIPTIVE_METRICS_DESCRIPTION = `Метрики и алгоритм: Описательные статистики

Остановка рассчитывает профиль каждой числовой колонки по ПОЛНОМУ текущему dataset в AnalysisSession. Это состояние уже включает применённые исправления и преобразования. Исторического снимка «до предобработки» сессия сейчас не хранит, поэтому интерфейс не показывает выдуманное сравнение до/после.

Основные метрики
1. N = число непустых наблюдений. При N < 2 статистики не вычисляются, а признак остаётся в таблице с честным пояснением.
2. Mean и Median характеризуют центр. Их заметное расхождение — сигнал асимметрии или влияния экстремальных значений.
3. Std — выборочное стандартное отклонение (pandas, ddof=1), мера абсолютного разброса в единицах признака.
4. Q1 и Q3 — 25-й и 75-й процентили; IQR = Q3 − Q1 — устойчивый к выбросам разброс центральных 50% наблюдений.
5. Skewness — коэффициент асимметрии: около 0 — симметрия; > 0 — длинный правый хвост; < 0 — длинный левый хвост. Доступен при N ≥ 3.
6. Kurtosis — excess kurtosis (у нормального распределения 0): положительное значение указывает на более тяжёлые хвосты, отрицательное — на более плоскую форму. Доступен при N ≥ 4.

Эвристика формы распределения
- |skew| < 0.5 и |kurtosis| < 1 → близко к нормальному;
- skew ≥ 0.5 / ≤ −0.5 → правосторонняя / левосторонняя асимметрия;
- при умеренной асимметрии kurtosis ≥ 1 → тяжёлые хвосты, иначе плосковершинная форма.

Эта эвристика — навигационный сигнал, а не статистический тест нормальности. Формальные тесты и QQ-plot относятся к отдельной остановке «Распределение».`;

const DESCRIPTIVE_PIPELINE_DESCRIPTION = `Полный пайплайн: описательные статистики

1. GET /v1/session/dataset/stats читает полный текущий session.dataframe; превью 5+5 строк не используется.
2. Backend выбирает все числовые колонки и отдельно удаляет NaN только на время расчёта каждой колонки.
3. Для N ≥ 2 pandas вычисляет mean, median, sample std, Q1, Q3 и IQR; skewness доступна при N ≥ 3, excess kurtosis — при N ≥ 4. Недоступные показатели формы возвращаются как null. Признаки с N < 2 не исчезают: возвращаются с stats=null и фактическим N.
4. Backend добавляет объяснимую эвристику формы распределения по skewness/kurtosis.
5. Выбор признака в левой колонке синхронизирует таблицу, нижние метрики и вкладки визуализации.
6. При первом открытии графической вкладки GET /v1/session/dataset/distribution?column=... возвращает scatter, гистограмму и KDE для выбранного признака. Один ответ переиспользуется при переключении вкладок.
7. Scatter сэмплируется LTTB только для больших рядов с сохранением экстремумов; гистограмма и KDE всегда считаются по полному выбранному диапазону.
8. Остановка read-only: она диагностирует текущее состояние и не мутирует датасет. Кнопка «Пересчитать статистики» повторно читает данные после преобразований предыдущих этапов.`;

const CORRELATION_METRICS_DESCRIPTION = `Метрики и алгоритм: Корреляция (ACF/PACF)

Остановка исследует линейную зависимость выбранного ряда от его прошлых значений. Она работает с ПОЛНЫМ текущим рядом из AnalysisSession и не изменяет датасет.

1. ACF(k) = corr(yₜ, yₜ₋ₖ) измеряет суммарную линейную связь с лагом k. Медленное затухание часто указывает на тренд или нестационарность; пики на кратных лагах — кандидат на сезонную структуру.
2. PACF(k) оценивает прямую связь yₜ и yₜ₋ₖ после исключения влияния промежуточных лагов 1…k−1. Резкое обрезание PACF используют как начальный ориентир порядка AR(p), а обрезание ACF — порядка MA(q).
3. Серые пунктирные границы — 95% доверительные интервалы statsmodels (alpha=0,05). Красным отмечены лаги, чей интервал не включает ноль. При просмотре десятков лагов отдельные ложноположительные пики возможны из-за множественных сравнений.
4. Ljung–Box проверяет совместную гипотезу об отсутствии автокорреляции до выбранного контрольного лага: p < 0,05 означает, что ряд не похож на белый шум.
5. Кандидаты p и q — только объяснимая стартовая эвристика по непрерывной последовательности значимых лагов от лага 1. Это не автоматический выбор финальной ARIMA: параметр d определяется после проверки стационарности, а порядки подтверждаются диагностикой остатков и временной валидацией.`;

const CORRELATION_PIPELINE_DESCRIPTION = `Полный пайплайн: корреляция (ACF/PACF)

1. Выбранный во всей платформе «Исследуемый признак» передаётся в GET /v1/session/dataset/eda-correlation?column=...&max_lags=....
2. Backend контентно ищет временную ось существующим детектором. При уверенном обнаружении даты ряд сортируется по возрастанию; числовые годы обрабатываются как годы, а не unix-наносекунды.
3. Повторяющиеся даты блокируют расчёт как вероятные панельные данные: без выбора сущности автоматическая агрегация исказила бы ряд. Нераспознанные даты и пропуски/∞ в значениях также не удаляются молча, потому что это меняет смысл лага.
4. Если ось времени не найдена, расчёт использует текущий порядок строк и явно показывает предупреждение. При нерегулярной частоте один лаг означает один соседний шаг наблюдения, а не фиксированный календарный интервал.
5. ACF рассчитывается statsmodels с FFT; PACF — методом Yule–Walker. Горизонт ограничивается условием PACF nlags < N/2, поэтому интерфейс показывает фактически доступный максимум.
6. Один API-ответ содержит ACF, PACF, их 95% границы, значимые лаги, Ljung–Box и стартовые p/q. Вкладки «ACF», «PACF» и «Таблица» переиспользуют этот ответ без повторных запросов.
7. Остановка read-only. «Пересчитать корреляцию» повторяет расчёт после изменений датасета, а смена признака или горизонта лагов автоматически запрашивает согласованный профиль.`;

const IH_METRICS_DESCRIPTION = `Метрики и алгоритм: IH-анализ

Остановка реализует Information-Entropy подход из статьи об IH-анализе: измеряет, насколько знание фактора X уменьшает неопределённость выбранной цели Y. Это не Sample/Approximate/Permutation entropy временного ряда и не Transfer Entropy — прежнее описание смешивало разные семейства методов и удалено.

Основные метрики
1. H(Y) = −Σp(y)log₂p(y) — полная неопределённость цели в битах. H(Y)=0 означает константную цель, для которой IH-анализ неприменим.
2. H(X) — энтропия фактора после подготовки. Большое значение само по себе не означает полезность: уникальный идентификатор может иметь высокую H(X), но не обобщаться.
3. I(X;Y) = H(Y) − H(Y|X) — взаимная информация: сколько бит неопределённости Y устраняет знание X.
4. R(Y|X) = I(X;Y)/H(Y) ∈ [0;1] — доля объяснённой неопределённости. Мера не требует линейности или монотонности и направлена по нормировке: R(Y|X) и R(X|Y) в общем случае различаются.
5. R adj. = max(0, R − средний R на перестановках Y). Это консервативный разведочный показатель, уменьшающий оптимистическое смещение конечной выборки и высокой кардинальности.
6. p-value получен перестановочным тестом; q-value — Benjamini–Hochberg FDR по показанным факторам. q≤0,05 помечается как статистически значимый сигнал.

Подготовка
- числовые признаки разбиваются на квантильные интервалы; резкость задаёт желаемую детализацию (~2/sharpness), а «мин. на интервал» ограничивает её реальным покрытием;
- категории остаются категориями даже при высокой кардинальности;
- реальные пропуски становятся отдельным информационным уровнем, как в IH-методе;
- дата не используется как обычный фактор: для временной структуры добавляются лаги выбранной цели.

Парные комбинации
«Добавка к лучшему» = R(X₁,X₂;Y) − max(R₁,R₂) показывает практическую дополнительную информацию. Interaction ΔR = R(X₁,X₂;Y) − R₁ − R₂: положительное значение — синергетическое взаимодействие, отрицательное — перекрытие информации. Ни одна из этих метрик не доказывает причинность.`;

const IH_PIPELINE_DESCRIPTION = `Полный пайплайн: IH-анализ

1. Общий «Исследуемый признак» становится целью Y запроса GET /v1/session/dataset/eda-ih. Отдельного локального target-селектора нет.
2. Backend контентно определяет временную колонку, исключает её из факторов и сортирует ряд по времени. Если даты не определены, лаги строятся по текущему порядку строк с предупреждением.
3. При повторяющихся датах вероятна панель: contemporaneous-факторы продолжают анализироваться, но лаги отключаются, поскольку без выбора сущности они смешали бы разные ряды.
4. Факторами X становятся остальные числовые и категориальные колонки плюс Y[t−1]…Y[t−k]. Структурные пустоты, возникающие от shift, исключаются выравниванием пары; реальные пропуски сохраняются отдельным уровнем.
5. Исправлен существующий backend: высококардинальные категории больше не попадают в numeric qcut, min_samples реально ограничивает число интервалов, а комбинированный дискретный фактор не дискретизируется повторно.
6. Сначала рассчитываются H(X), H(Y), I(X;Y), R(Y|X) для всех факторов. Для top-K выполняются воспроизводимые перестановки Y, baseline, p-value и FDR q-value.
7. Для максимум шести лучших обычных факторов рассчитываются парные R-комбинации, добавочная информация и interaction delta. Лаги не смешиваются в парном переборе из-за разной длины выровненных выборок.
8. Один ответ API питает пять вкладок «Обзора»: рейтинг, карту метрик, синергию, условное распределение и точную таблицу. Переключение вкладок не создаёт новых запросов.
9. Остановка read-only. Смена цели или параметров автоматически пересчитывает профиль; ручная кнопка повторяет расчёт после изменений датасета.`;

const SEASONALITY_METRICS_DESCRIPTION = `Метрики и алгоритм: Сезонность и периодичность

Остановка ищет повторяющиеся компоненты выбранного преобразованного ряда. Период всегда измеряется в числе наблюдений; календарная интерпретация добавляется только при уверенно определённой регулярной частоте.

1. Перед спектром удаляется линейный тренд. Это снижает утечку низкочастотной энергии, из-за которой обычный тренд мог ошибочно выглядеть как очень длинный цикл.
2. Окно Hann сглаживает границы конечного отрезка и уменьшает spectral leakage. FFT показывает амплитуду гармоник, периодограмма — распределение мощности; это два представления одного спектрального свидетельства, а не два независимых теста.
3. Spectral entropy нормирована в [0;1]: низкое значение означает концентрацию энергии в небольшом числе частот, высокое — более рассеянный/шумовой спектр. Энтропия не доказывает наличие сезонности.
4. Пики периодограммы ранжируются по мощности и prominence. Допускаются только периоды, для которых в ряду помещается заданное минимальное число полных циклов.
5. SNR — отношение мощности пика к локальному медианному фону. ACF(period) проверяет повторяемость через соответствующий лаг. Seasonal strength = max(0, 1 − Var(residual)/Var(detrended)) оценивает долю вариации, воспроизводимую средним фазовым профилем.
6. Период помечается «подтверждён», только если одновременно достаточно выражены prominence, локальный SNR, положительная ACF и фазовая сила. Это объяснимая разведочная эвристика, не формальный p-value и не доказательство будущей устойчивости.
7. Короткий пик, кратный более длинному кандидату, маркируется как возможная гармоника. Он не удаляется: несинусоидальная сезонная форма закономерно создаёт гармоники.

Сезонность может быть множественной и меняться со временем. Финальный период модели необходимо подтвердить на временных срезах, после учёта структурных сдвигов и через временную валидацию.`;

const SEASONALITY_PIPELINE_DESCRIPTION = `Полный пайплайн: сезонность и периодичность

1. Общий «Исследуемый признак» передаётся в GET /v1/session/dataset/eda-seasonality вместе с минимальным числом циклов и лимитом кандидатов.
2. Backend переиспользует общий детектор временной оси. Даты сортируются по возрастанию; повторные даты блокируют расчёт как вероятная панель, а не агрегируются без выбора сущности.
3. FFT и классическая периодограмма требуют равномерной дискретизации. Нерегулярная сетка честно возвращает «неприменимо» с рекомендацией сначала регуляризовать ряд либо применять Lomb–Scargle; пропуски/∞ также не удаляются молча.
4. Если дата не определена, текущий порядок строк допускается как равномерная индексная шкала с явным предупреждением: период тогда имеет только смысл «наблюдений», без календарной метки.
5. Существующий backend-модуль app/features/spectral.py расширен производственным контуром: linear detrend → Hann window → real FFT + periodogram → локальные пики/prominence → SNR → ACF → фазовая сила → гармоники.
6. Верхняя граница периода N/min_cycles не позволяет делать вывод по одному неполному колебанию. Для каждого кандидата возвращаются период, частота, число циклов, доля мощности, prominence, SNR, ACF, сила и календарная подсказка.
7. Один API-ответ питает четыре вкладки «Обзора»: FFT, периодограмму, фазовый профиль доминирующего кандидата и таблицу периодов. Переключение вкладок не создаёт повторных запросов.
8. Остановка read-only. Смена общего признака или параметров автоматически пересчитывает результат; ручная кнопка повторяет запрос после преобразований датасета.`;

const STATIONARITY_METRICS_DESCRIPTION = `Метрики и алгоритм: Верификация стационарности

Стационарность означает устойчивость вероятностных характеристик ряда во времени. Остановка не делает вывод по одному p-value: тесты имеют разные нулевые гипотезы, чувствительны к спецификации детерминированных компонент и на коротких выборках обладают ограниченной мощностью.

1. ADF и Phillips–Perron проверяют H₀: единичный корень. p < α означает отклонение H₀ в пользу стационарности для выбранной спецификации. ADF моделирует серийную корреляцию лагами и выбирает их по AIC; PP использует Newey–West оценку долгосрочной дисперсии.
2. KPSS проверяет обратную H₀: стационарность. Для KPSS p ≥ α означает, что оснований отвергнуть стационарность нет. Его табличные p-value ограничены диапазоном [0,01; 0,10], поэтому backend сохраняет предупреждение о границе вместо ложной точности.
3. ADF и KPSS рассчитываются дважды: c — стационарность вокруг уровня, ct — вокруг линейного тренда. «Стационарен вокруг тренда» выдаётся только при согласии ADF(ct) и KPSS(ct), а не из одного неотвергнутого теста.
4. Консенсус: stationary — ADF(c) отвергает единичный корень и KPSS(c) не отвергает уровень; trend-stationary — согласованы ADF(ct)/KPSS(ct); non-stationary — обе ADF-спецификации и обе KPSS-спецификации согласованы с единичным корнем; остальные комбинации честно помечаются inconclusive.
5. Phillips–Perron рассчитывается реальным классом arch.unitroot.PhillipsPerron. Если зависимость недоступна, PP помечается недоступным: результат ADF больше не выдаётся за другой тест.
6. Zivot–Andrews проверяет единичный корень при одном эндогенно найденном структурном разрыве. В ответе используется реальный breakpoint index и p-value, а не приблизительный вручную заданный порог.
7. Скользящие mean/std — визуальная диагностика локальной стабильности, не формальный тест. Выбранное окно измеряется в наблюдениях; систематический дрейф этих кривых помогает объяснить статистический вывод.

Даже согласованный вывод не доказывает применимость всей ARIMA-модели: ещё требуются корректная сезонная спецификация, диагностика остатков и временная валидация.`;

const STATIONARITY_PIPELINE_DESCRIPTION = `Полный пайплайн: верификация стационарности

1. Общий «Исследуемый признак» передаётся в GET /v1/session/dataset/eda-stationarity?column=...&alpha=...&rolling_window=.... Остановка читает текущий полностью преобразованный session.dataframe и не мутирует его.
2. Backend переиспользует общий контентный детектор временной оси. Даты сортируются по возрастанию; повторяющиеся даты блокируют расчёт как вероятную панель, поскольку выбор или агрегация сущности без решения пользователя изменили бы ряд.
3. Нераспознанные и нерегулярные даты блокируют unit-root тесты: лаги должны соответствовать равноотстоящим наблюдениям. Если дата не определена, допускается текущий порядок строк с явным предупреждением и окном в наблюдениях.
4. Пропуски и бесконечности не удаляются молча. Удаление сжало бы временную ось; интерфейс направляет пользователя назад в Предобработку. Минимум — 30 конечных наблюдений; константный ряд помечается как вырожденный для unit-root p-value.
5. Улучшенный общий backend-контур app.eda.stationarity используется и legacy-функцией run_stationarity_tests: ADF(c/ct) → KPSS(c/ct) → настоящий PP → Zivot–Andrews → комплементарный консенсус.
6. Один API-ответ содержит шесть строк тестов, critical values, лаги, решение при α, breakpoint, рекомендации и скользящие mean/std. Для большого ряда график LTTB-сэмплируется с сохранением формы; сами тесты всегда считаются по полному ряду.
7. Четыре вкладки «Обзора» — «Ряд и μ», «Скользящее σ», «p-value», «Таблица» — переиспользуют один ответ без повторных запросов.
8. Смена α, окна или общего признака автоматически пересчитывает профиль; кнопка ручного обновления повторяет проверку после преобразований предыдущих этапов.`;

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить описательные статистики (HTTP ${response.status})`;
}

async function correlationResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось рассчитать ACF/PACF (HTTP ${response.status})`;
}

async function ihResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить IH-анализ (HTTP ${response.status})`;
}

async function seasonalityResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить спектральный анализ (HTTP ${response.status})`;
}

async function stationarityResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось проверить стационарность (HTTP ${response.status})`;
}

function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  return normalized.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
}

function stationarityConsensusLabel(consensus: StationarityConsensus | null | undefined): string {
  if (consensus === "stationary") return "Стационарен";
  if (consensus === "trend-stationary") return "Вокруг тренда";
  if (consensus === "non-stationary") return "Нестационарен";
  if (consensus === "inconclusive") return "Неопределённо";
  return "—";
}

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisEDA() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // Единый исследуемый признак всей платформы. Backend исключает
  // date/year-похожие числовые колонки из АВТОМАТИЧЕСКОЙ рекомендации,
  // а явный выбор пользователя сохраняется в AnalysisSession и доступен
  // на остальных вкладках через тот же GET/POST /target-column.
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    hasDataset,
    loading: targetLoading,
    error: targetError,
    setColumn: setActiveFeature,
  } = useTargetColumn(undefined);

  // ── Остановка «Описательные статистики»: реальные данные ──
  // Переиспользуем endpoint вкладки «Загрузка»: он уже считает профиль по
  // полному session.dataframe и честно сохраняет разреженные колонки.
  const [descriptiveProfile, setDescriptiveProfile] = useState<DescriptiveStatsResponse | null>(null);
  const [descriptiveLoading, setDescriptiveLoading] = useState(true);
  const [descriptiveNoDataset, setDescriptiveNoDataset] = useState(false);
  const [descriptiveError, setDescriptiveError] = useState<string | null>(null);
  const [descriptiveRefreshKey, setDescriptiveRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setDescriptiveLoading(true);
    setDescriptiveError(null);
    setDescriptiveNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/stats"), { credentials: "include" });
        if (response.status === 404) {
          if (active) {
            setDescriptiveNoDataset(true);
            setDescriptiveProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: DescriptiveStatsResponse = await response.json();
        if (active) {
          setDescriptiveProfile(data);
        }
      } catch (caught) {
        if (active) {
          setDescriptiveError(
            caught instanceof Error ? caught.message : "Не удалось загрузить описательные статистики",
          );
        }
      } finally {
        if (active) setDescriptiveLoading(false);
      }
    })();
    return () => { active = false; };
  }, [descriptiveRefreshKey]);

  const descriptiveBusy = descriptiveLoading || targetLoading;
  const descriptiveRequestError = descriptiveError ?? targetError;
  const insufficientColumns = descriptiveProfile?.columns.filter((item) => item.stats === null).length ?? 0;
  const descriptiveStatus: CheckStatus = descriptiveBusy
    ? "running"
    : descriptiveRequestError
    ? "error"
    : descriptiveNoDataset || descriptiveProfile?.columns.length === 0
    ? "skipped"
    : insufficientColumns > 0
    ? "warning"
    : descriptiveProfile
    ? "done"
    : "pending";

  // ── Остановка «Корреляция»: ACF/PACF выбранного общего признака ──
  const [correlationProfile, setCorrelationProfile] = useState<EdaCorrelationResponse | null>(null);
  const [correlationLoading, setCorrelationLoading] = useState(false);
  const [correlationNoDataset, setCorrelationNoDataset] = useState(false);
  const [correlationError, setCorrelationError] = useState<string | null>(null);
  const [correlationRefreshKey, setCorrelationRefreshKey] = useState(0);
  const [correlationMaxLags, setCorrelationMaxLags] = useState(40);

  useEffect(() => {
    if (activeCheckId !== "correlation" || targetLoading) return;
    if (!hasDataset) {
      setCorrelationNoDataset(true);
      setCorrelationProfile(null);
      setCorrelationLoading(false);
      return;
    }
    if (!activeFeature) {
      setCorrelationNoDataset(false);
      setCorrelationProfile(null);
      setCorrelationLoading(false);
      return;
    }

    let active = true;
    setCorrelationLoading(true);
    setCorrelationError(null);
    setCorrelationNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(
          sessionApiUrl(
            `/dataset/eda-correlation?column=${encodeURIComponent(activeFeature)}&max_lags=${correlationMaxLags}`,
          ),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setCorrelationNoDataset(true);
            setCorrelationProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await correlationResponseDetail(response));
        const data: EdaCorrelationResponse = await response.json();
        if (active) setCorrelationProfile(data);
      } catch (caught) {
        if (active) {
          setCorrelationError(
            caught instanceof Error ? caught.message : "Не удалось рассчитать ACF/PACF",
          );
        }
      } finally {
        if (active) setCorrelationLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, correlationMaxLags, correlationRefreshKey, hasDataset, targetLoading]);

  const correlationBusy = correlationLoading || (activeCheckId === "correlation" && targetLoading);
  const correlationRequestError = correlationError ?? (activeCheckId === "correlation" ? targetError : null);
  const correlationStatus: CheckStatus = correlationBusy
    ? "running"
    : correlationRequestError
    ? "error"
    : correlationNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : correlationProfile?.applicable === false
    ? "warning"
    : correlationProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «IH-анализ»: факторы X относительно общего target Y ──
  const [ihProfile, setIhProfile] = useState<EdaIhResponse | null>(null);
  const [ihLoading, setIhLoading] = useState(false);
  const [ihNoDataset, setIhNoDataset] = useState(false);
  const [ihError, setIhError] = useState<string | null>(null);
  const [ihRefreshKey, setIhRefreshKey] = useState(0);
  const [ihParameters, setIhParameters] = useState<EdaIhParameters>({
    sharpness: 0.25,
    minSamples: 20,
    topK: 10,
    maxLag: 3,
  });

  useEffect(() => {
    if (activeCheckId !== "ih_analysis" || targetLoading) return;
    if (!hasDataset) {
      setIhNoDataset(true);
      setIhProfile(null);
      setIhLoading(false);
      return;
    }
    if (!activeFeature) {
      setIhNoDataset(false);
      setIhProfile(null);
      setIhLoading(false);
      return;
    }

    let active = true;
    setIhLoading(true);
    setIhError(null);
    setIhNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          sharpness: String(ihParameters.sharpness),
          min_samples: String(ihParameters.minSamples),
          top_k: String(ihParameters.topK),
          max_lag: String(ihParameters.maxLag),
          permutations: "49",
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-ih?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setIhNoDataset(true);
            setIhProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await ihResponseDetail(response));
        const data: EdaIhResponse = await response.json();
        if (active) setIhProfile(data);
      } catch (caught) {
        if (active) {
          setIhError(caught instanceof Error ? caught.message : "Не удалось выполнить IH-анализ");
        }
      } finally {
        if (active) setIhLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, hasDataset, ihParameters, ihRefreshKey, targetLoading]);

  const ihBusy = ihLoading || (activeCheckId === "ih_analysis" && targetLoading);
  const ihRequestError = ihError ?? (activeCheckId === "ih_analysis" ? targetError : null);
  const ihStatus: CheckStatus = ihBusy
    ? "running"
    : ihRequestError
    ? "error"
    : ihNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : ihProfile?.applicable === false
    ? "warning"
    : ihProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «Сезонность и периодичность»: спектр общего target ──
  const [seasonalityProfile, setSeasonalityProfile] = useState<EdaSeasonalityResponse | null>(null);
  const [seasonalityLoading, setSeasonalityLoading] = useState(false);
  const [seasonalityNoDataset, setSeasonalityNoDataset] = useState(false);
  const [seasonalityError, setSeasonalityError] = useState<string | null>(null);
  const [seasonalityRefreshKey, setSeasonalityRefreshKey] = useState(0);
  const [seasonalityParameters, setSeasonalityParameters] = useState<EdaSeasonalityParameters>({
    minCycles: 3,
    maxCandidates: 5,
  });

  useEffect(() => {
    if (activeCheckId !== "seasonality" || targetLoading) return;
    if (!hasDataset) {
      setSeasonalityNoDataset(true);
      setSeasonalityProfile(null);
      setSeasonalityLoading(false);
      return;
    }
    if (!activeFeature) {
      setSeasonalityNoDataset(false);
      setSeasonalityProfile(null);
      setSeasonalityLoading(false);
      return;
    }

    let active = true;
    setSeasonalityLoading(true);
    setSeasonalityError(null);
    setSeasonalityNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          min_cycles: String(seasonalityParameters.minCycles),
          max_candidates: String(seasonalityParameters.maxCandidates),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-seasonality?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setSeasonalityNoDataset(true);
            setSeasonalityProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await seasonalityResponseDetail(response));
        const data: EdaSeasonalityResponse = await response.json();
        if (active) setSeasonalityProfile(data);
      } catch (caught) {
        if (active) {
          setSeasonalityError(
            caught instanceof Error ? caught.message : "Не удалось выполнить спектральный анализ",
          );
        }
      } finally {
        if (active) setSeasonalityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, hasDataset, seasonalityParameters, seasonalityRefreshKey, targetLoading]);

  const seasonalityBusy = seasonalityLoading || (activeCheckId === "seasonality" && targetLoading);
  const seasonalityRequestError = seasonalityError ?? (activeCheckId === "seasonality" ? targetError : null);
  const seasonalityStatus: CheckStatus = seasonalityBusy
    ? "running"
    : seasonalityRequestError
    ? "error"
    : seasonalityNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : seasonalityProfile?.applicable === false
    ? "warning"
    : seasonalityProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «Верификация стационарности»: общий target без мутации ──
  const [stationarityProfile, setStationarityProfile] = useState<EdaStationarityResponse | null>(null);
  const [stationarityLoading, setStationarityLoading] = useState(false);
  const [stationarityNoDataset, setStationarityNoDataset] = useState(false);
  const [stationarityError, setStationarityError] = useState<string | null>(null);
  const [stationarityRefreshKey, setStationarityRefreshKey] = useState(0);
  const [stationarityParameters, setStationarityParameters] = useState<EdaStationarityParameters>({
    alpha: 0.05,
    rollingWindow: 12,
  });

  useEffect(() => {
    if (activeCheckId !== "stationarity" || targetLoading) return;
    if (!hasDataset) {
      setStationarityNoDataset(true);
      setStationarityProfile(null);
      setStationarityLoading(false);
      return;
    }
    if (!activeFeature) {
      setStationarityNoDataset(false);
      setStationarityProfile(null);
      setStationarityLoading(false);
      return;
    }

    let active = true;
    setStationarityLoading(true);
    setStationarityError(null);
    setStationarityNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          alpha: String(stationarityParameters.alpha),
          rolling_window: String(stationarityParameters.rollingWindow),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-stationarity?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setStationarityNoDataset(true);
            setStationarityProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await stationarityResponseDetail(response));
        const data: EdaStationarityResponse = await response.json();
        if (active) setStationarityProfile(data);
      } catch (caught) {
        if (active) {
          setStationarityError(
            caught instanceof Error ? caught.message : "Не удалось проверить стационарность",
          );
        }
      } finally {
        if (active) setStationarityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, hasDataset, stationarityParameters, stationarityRefreshKey, targetLoading]);

  const stationarityBusy = stationarityLoading || (activeCheckId === "stationarity" && targetLoading);
  const stationarityRequestError = stationarityError ?? (activeCheckId === "stationarity" ? targetError : null);
  const stationarityStatus: CheckStatus = stationarityBusy
    ? "running"
    : stationarityRequestError
    ? "error"
    : stationarityNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : stationarityProfile?.applicable === false
    ? "warning"
    : stationarityProfile?.consensus === "stationary" || stationarityProfile?.consensus === "trend-stationary"
    ? "done"
    : stationarityProfile?.applicable
    ? "warning"
    : "pending";

  const checks = useMemo<Check[]>(() => CHECKS.map((check) =>
    check.id === "descriptive"
      ? { ...check, status: descriptiveStatus, count: insufficientColumns }
      : check.id === "correlation"
      ? { ...check, status: correlationStatus, count: null }
      : check.id === "ih_analysis"
      ? { ...check, status: ihStatus, count: null }
      : check.id === "seasonality"
      ? { ...check, status: seasonalityStatus, count: seasonalityProfile?.confirmed_periods ?? null }
      : check.id === "stationarity"
      ? { ...check, status: stationarityStatus, count: null }
      : check,
  ), [correlationStatus, descriptiveStatus, ihStatus, insufficientColumns, seasonalityProfile?.confirmed_periods, seasonalityStatus, stationarityStatus]);

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

  const applicableChecks = checks.filter((check) => check.status !== "skipped");
  const evaluatedCount = applicableChecks.filter(
    (check) => check.status === "done" || check.status === "warning",
  ).length;
  const progressPct = applicableChecks.length > 0
    ? Math.round((evaluatedCount / applicableChecks.length) * 100)
    : 100;
  const activeCheck = checks.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...checks].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  // Показать/скрыть справку
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

  // Текст описания для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return EDA_HELP;
    if (!descriptionSection) return null;
    if (activeCheckId === "descriptive") {
      return descriptionSection === "metrics"
        ? DESCRIPTIVE_METRICS_DESCRIPTION
        : DESCRIPTIVE_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "correlation") {
      return descriptionSection === "metrics"
        ? CORRELATION_METRICS_DESCRIPTION
        : CORRELATION_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "ih_analysis") {
      return descriptionSection === "metrics" ? IH_METRICS_DESCRIPTION : IH_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "seasonality") {
      return descriptionSection === "metrics" ? SEASONALITY_METRICS_DESCRIPTION : SEASONALITY_PIPELINE_DESCRIPTION;
    }
    if (activeCheckId === "stationarity") {
      return descriptionSection === "metrics" ? STATIONARITY_METRICS_DESCRIPTION : STATIONARITY_PIPELINE_DESCRIPTION;
    }
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты EDA";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (activeCheckId === "descriptive") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Описательные статистики"
        : "Полный пайплайн — Описательные статистики";
    }
    if (activeCheckId === "correlation") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Корреляция (ACF/PACF)"
        : "Полный пайплайн — Корреляция (ACF/PACF)";
    }
    if (activeCheckId === "ih_analysis") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — IH-анализ"
        : "Полный пайплайн — IH-анализ";
    }
    if (activeCheckId === "seasonality") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Сезонность и периодичность"
        : "Полный пайплайн — Сезонность и периодичность";
    }
    if (activeCheckId === "stationarity") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Верификация стационарности"
        : "Полный пайплайн — Верификация стационарности";
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
              Разведочный EDA
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
            Финал перед моделированием
          </p>
        </div>

        {/* Селектор числового признака */}
        <div>
          <label htmlFor="eda-active-feature" className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            id="eda-active-feature"
            value={activeFeature ?? ""}
            onChange={(e) => void setActiveFeature(e.target.value)}
            disabled={descriptiveBusy || numericFeatures.length === 0}
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
            {evaluatedCount}/{applicableChecks.length}
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

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + график + метрики ── */}
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

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Визуализация результатов исследования.
          </p>

          {activeCheckId === "descriptive" ? (
            <EdaDescriptiveOverview
              profile={descriptiveProfile}
              activeFeature={activeFeature ?? ""}
              loading={descriptiveBusy}
              error={descriptiveRequestError}
              noDataset={descriptiveNoDataset}
              refreshKey={descriptiveRefreshKey}
            />
          ) : activeCheckId === "correlation" ? (
            <EdaCorrelationOverview
              profile={correlationProfile}
              loading={correlationBusy}
              error={correlationRequestError}
              noDataset={correlationNoDataset}
              maxLags={correlationMaxLags}
              onMaxLagsChange={setCorrelationMaxLags}
            />
          ) : activeCheckId === "ih_analysis" ? (
            <EdaIhOverview
              profile={ihProfile}
              loading={ihBusy}
              error={ihRequestError}
              noDataset={ihNoDataset}
              parameters={ihParameters}
              onParametersChange={(changes) => setIhParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "seasonality" ? (
            <EdaSeasonalityOverview
              profile={seasonalityProfile}
              loading={seasonalityBusy}
              error={seasonalityRequestError}
              noDataset={seasonalityNoDataset}
              parameters={seasonalityParameters}
              onParametersChange={(changes) => setSeasonalityParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "stationarity" ? (
            <EdaStationarityOverview
              profile={stationarityProfile}
              loading={stationarityBusy}
              error={stationarityRequestError}
              noDataset={stationarityNoDataset}
              parameters={stationarityParameters}
              onParametersChange={(changes) => setStationarityParameters((current) => ({ ...current, ...changes }))}
            />
          ) : (
            <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
              [ график для «{activeCheck.label}» ]
            </div>
          )}

          {activeCheckId === "descriptive" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const selected = descriptiveProfile?.columns.find((item) => item.name === activeFeature) ?? null;
                return (
                  <>
                    <Metric label="N" value={selected ? String(selected.non_null_count) : "—"} />
                    <Metric label="Mean" value={formatMetric(selected?.stats?.mean)} />
                    <Metric label="Median" value={formatMetric(selected?.stats?.median)} />
                    <Metric label="Std" value={formatMetric(selected?.stats?.std)} />
                    <Metric label="Skewness" value={formatMetric(selected?.stats?.skewness)} />
                    <Metric label="Kurtosis" value={formatMetric(selected?.stats?.kurtosis)} />
                  </>
                );
              })()}
            </div>
          ) : activeCheckId === "correlation" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={correlationProfile ? String(correlationProfile.n_observations) : "—"} />
              <Metric label="Макс. лаг" value={correlationProfile?.applicable ? String(correlationProfile.max_lag) : "—"} />
              <Metric label="Значимых ACF" value={correlationProfile?.applicable ? String(correlationProfile.significant_acf_lags.length) : "—"} />
              <Metric label="Значимых PACF" value={correlationProfile?.applicable ? String(correlationProfile.significant_pacf_lags.length) : "—"} />
              <Metric label="Ljung–Box p" value={formatMetric(correlationProfile?.ljung_box_pvalue)} />
              <Metric
                label="Кандидаты p / q"
                value={correlationProfile?.applicable
                  ? `${correlationProfile.suggested_p ?? "—"} / ${correlationProfile.suggested_q ?? "—"}`
                  : "—"}
              />
            </div>
          ) : activeCheckId === "ih_analysis" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const top = ihProfile?.results[0] ?? null;
                const bestGain = ihProfile?.synergies.length
                  ? Math.max(...ihProfile.synergies.map((item) => item.incremental_gain))
                  : null;
                return (
                  <>
                    <Metric label="N" value={ihProfile ? String(ihProfile.n_observations) : "—"} />
                    <Metric label="H(Y), бит" value={formatMetric(ihProfile?.target_entropy)} />
                    <Metric label="Топ R" value={formatMetric(top?.r)} />
                    <Metric label="Топ R adj." value={formatMetric(top?.r_adjusted)} />
                    <Metric label="Значимых q≤0,05" value={ihProfile?.applicable ? String(ihProfile.results.filter((item) => item.significant).length) : "—"} />
                    <Metric label="Лучший прирост ΔR" value={formatMetric(bestGain)} />
                  </>
                );
              })()}
            </div>
          ) : activeCheckId === "seasonality" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={seasonalityProfile ? String(seasonalityProfile.n_observations) : "—"} />
              <Metric label="Частота" value={seasonalityProfile?.frequency ?? (seasonalityProfile?.order_source === "row_order" ? "индекс" : "—")} />
              <Metric label="Топ-период" value={formatMetric(seasonalityProfile?.dominant_period)} />
              <Metric label="Сила профиля" value={formatMetric(seasonalityProfile?.dominant_strength)} />
              <Metric label="Спектр. энтропия" value={formatMetric(seasonalityProfile?.spectral_entropy)} />
              <Metric label="Подтверждено" value={seasonalityProfile?.applicable ? String(seasonalityProfile.confirmed_periods) : "—"} />
            </div>
          ) : activeCheckId === "stationarity" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const byId = (id: string) => stationarityProfile?.tests.find((item) => item.id === id) ?? null;
                return (
                  <>
                    <Metric label="N" value={stationarityProfile ? String(stationarityProfile.n_observations) : "—"} />
                    <Metric label="Консенсус" value={stationarityConsensusLabel(stationarityProfile?.consensus)} />
                    <Metric label="ADF p" value={formatMetric(byId("adf_level")?.p_value)} />
                    <Metric label="KPSS p" value={formatMetric(byId("kpss_level")?.p_value)} />
                    <Metric label="PP p" value={formatMetric(byId("pp")?.p_value)} />
                    <Metric label="ZA-разрыв" value={stationarityProfile?.breakpoint_label ?? (stationarityProfile?.breakpoint_index !== null && stationarityProfile?.breakpoint_index !== undefined ? String(stationarityProfile.breakpoint_index) : "—")} />
                  </>
                );
              })()}
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value="200" />
              <Metric label="Признаков" value="8" />
              <Metric label="H(ряд)" value="2.14" />
              <Metric label="ADF p" value="0.03" />
              <Metric label="Частота" value="D" />
            </div>
          )}
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список исследований ── */}
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
                <StatusIcon status={check.status} /> Исследование: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Бейдж результата — после описания */}
              {check.id === "descriptive" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Рассчитываем статистики по полному датасету…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {descriptiveRequestError ?? "Ошибка расчёта статистик"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {descriptiveNoDataset
                        ? "Нет активного датасета"
                        : "В датасете нет числовых признаков"}
                    </p>
                  )}
                  {check.status === "warning" && check.count !== null && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Для {check.count} {check.count === 1 ? "признака" : "признаков"} недостаточно наблюдений
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Рассчитано признаков: {descriptiveProfile?.columns.length ?? 0}
                    </p>
                  )}
                </>
              ) : check.id === "correlation" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Рассчитываем ACF/PACF по полному ряду…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {correlationRequestError ?? "Ошибка расчёта ACF/PACF"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {correlationNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {correlationProfile?.reason ?? "ACF/PACF неприменимы"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {correlationProfile?.is_white_noise
                        ? "Ljung–Box: автокорреляция совместно не обнаружена"
                        : `Значимых лагов: ACF ${correlationProfile?.significant_acf_lags.length ?? 0}, PACF ${correlationProfile?.significant_pacf_lags.length ?? 0}`}
                    </p>
                  )}
                </>
              ) : check.id === "ih_analysis" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Вычисляем IH-профиль и перестановочный baseline…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {ihRequestError ?? "Ошибка IH-анализа"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {ihNoDataset ? "Нет активного датасета" : "Нет исследуемого признака Y"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {ihProfile?.reason ?? "IH-анализ неприменим"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Исследовано факторов: {ihProfile?.features_analyzed ?? 0}; значимых после FDR: {ihProfile?.results.filter((item) => item.significant).length ?? 0}
                    </p>
                  )}
                </>
              ) : check.id === "seasonality" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Строим спектральный и фазовый профиль…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {seasonalityRequestError ?? "Ошибка спектрального анализа"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {seasonalityNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {seasonalityProfile?.reason ?? "Спектральный анализ неприменим"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {seasonalityProfile?.confirmed_periods
                        ? `Подтверждено периодов: ${seasonalityProfile.confirmed_periods}`
                        : "Анализ завершён: устойчивые периоды не подтверждены"}
                    </p>
                  )}
                </>
              ) : check.id === "stationarity" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Выполняем ADF/KPSS/PP и скользящие диагностики…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {stationarityRequestError ?? "Ошибка проверки стационарности"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {stationarityNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {stationarityProfile?.applicable === false
                        ? stationarityProfile.reason
                        : stationarityProfile?.recommendation ?? "Результаты тестов требуют проверки"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {stationarityConsensusLabel(stationarityProfile?.consensus)} при α={stationarityProfile?.alpha ?? stationarityParameters.alpha}
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
                      Исследование завершено
                    </p>
                  )}
                </>
              )}

              {/* Кнопка «Метрики и алгоритм» */}
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

              {/* Кнопка «Полный пайплайн» */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Полный пайплайн
              </button>

              {check.id === "descriptive" ? (
                <Button
                  type="button"
                  onClick={() => setDescriptiveRefreshKey((key) => key + 1)}
                  disabled={descriptiveBusy}
                >
                  {descriptiveBusy ? "Рассчитываем…" : "Пересчитать статистики"}
                </Button>
              ) : check.id === "correlation" ? (
                <Button
                  type="button"
                  onClick={() => setCorrelationRefreshKey((key) => key + 1)}
                  disabled={correlationBusy || !activeFeature}
                >
                  {correlationBusy ? "Рассчитываем…" : "Пересчитать корреляцию"}
                </Button>
              ) : check.id === "ih_analysis" ? (
                <Button
                  type="button"
                  onClick={() => setIhRefreshKey((key) => key + 1)}
                  disabled={ihBusy || !activeFeature}
                >
                  {ihBusy ? "Рассчитываем…" : "Пересчитать IH-анализ"}
                </Button>
              ) : check.id === "seasonality" ? (
                <Button
                  type="button"
                  onClick={() => setSeasonalityRefreshKey((key) => key + 1)}
                  disabled={seasonalityBusy || !activeFeature}
                >
                  {seasonalityBusy ? "Рассчитываем…" : "Пересчитать сезонность"}
                </Button>
              ) : check.id === "stationarity" ? (
                <Button
                  type="button"
                  onClick={() => setStationarityRefreshKey((key) => key + 1)}
                  disabled={stationarityBusy || !activeFeature}
                >
                  {stationarityBusy ? "Рассчитываем…" : "Пересчитать стационарность"}
                </Button>
              ) : (
                <Button>Запустить анализ ({check.label.toLowerCase()})</Button>
              )}
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
