// packages/ui/lib/knowledge/glossary.ts
//
// Task EDU-1 (spec_education.md, Часть I) — реестр Словаря терминов
// базы знаний. Термины — фактический методологический язык платформы;
// related_article_ids связывают словарь с Библиотекой (связность базы
// знаний: термин → статья контекста), инвариант ссылок застрахован
// тестом (ссылка только на существующую статью).

import type { GlossaryTerm } from "./types";

export const GLOSSARY_TERMS: readonly GlossaryTerm[] = [
  {
    term_id: "acf-pacf",
    term: "ACF / PACF",
    definition:
      "Автокорреляционная и частная автокорреляционная функции: корреляция ряда с его собственными лагами. ACF с доверительными интервалами показывает «память» ряда, PACF — чистый вклад каждого лага. Затухание ACF при резком PACF — аргумент за авторегрессию, наоборот — за скользящее среднее.",
    related_article_ids: ["eda-descriptive-correlation"],
    stage_ids: ["eda", "modeling"],
  },
  {
    term_id: "adf-kpss",
    term: "ADF / KPSS",
    definition:
      "Пары тестов стационарности с противоположными нулевыми гипотезами: ADF предполагает единичный корень (нестационарность), KPSS — стационарность. Согласные выводы обоих тестов надёжны; противоречие требует визуальной и содержательной проверки.",
    related_article_ids: ["eda-stationarity"],
    stage_ids: ["preprocessing", "eda"],
  },
  {
    term_id: "arima",
    term: "ARIMA",
    definition:
      "Авторегрессионная интегрированная модель скользящего среднего: ряд дифференцируется (I) до стационарности, затем моделируется авторегрессией (AR) и скользящим средним (MA). Сезонное расширение — SARIMA — добавляет те же блоки на сезонных лагах.",
    related_article_ids: ["modeling-catalog", "eda-stationarity"],
    stage_ids: ["modeling", "eda"],
  },
  {
    term_id: "backtest",
    term: "Бэктест",
    definition:
      "Проверка прогнозной способности на истории: модель обучается на прошлом, прогнозирует отрезок, который ей не показывали (out-of-sample), и измеряется ошибка. Для рядов разбиение выполняется только по времени; схема walk-forward повторяет это несколько раз со сдвигом окна.",
    related_article_ids: ["modeling-backtest", "forecasting-accuracy-metrics"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "baseline",
    term: "Baseline (наивный прогноз)",
    definition:
      "Простейшая точка отсчёта: последний факт (naive), значение год назад (сезонный naive) или среднее. Любая сложная модель обязана превзойти baseline — иначе сложность не оправдана. Правило платформы «baseline-first» закрепляет этот принцип в порядке каталога.",
    related_article_ids: ["modeling-catalog"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "box-cox",
    term: "Box-Cox (преобразование)",
    definition:
      "Семейство степенных преобразований (частный случай — логарифм) для стабилизации дисперсии: делает амплитуду колебаний более однородной по уровню ряда. Применяется в Предобработке перед декомпозицией и моделированием.",
    related_article_ids: ["preprocessing-missing-outliers", "eda-stationarity"],
    stage_ids: ["preprocessing"],
  },
  {
    term_id: "chow-test",
    term: "Тест Чоу",
    definition:
      "Проверка структурного сдвига: сравниваются параметры модели, оценённой на всём ряде, и моделей, оценённых до/после кандидата-точки сдвига. Требует априорной точки; для поиска произвольных точек используется PELT.",
    related_article_ids: ["eda-structural-breaks"],
    stage_ids: ["eda"],
  },
  {
    term_id: "cusum",
    term: "CUSUM",
    definition:
      "Метод кумулятивных сумм: накапливает отклонения от ожидаемого уровня и сигнализирует, когда их сумма выходит за контрольные границы. Хорош для плавных дрейфов уровня; один из трёх методов поиска структурных сдвигов в EDA платформы.",
    related_article_ids: ["eda-structural-breaks"],
    stage_ids: ["eda"],
  },
  {
    term_id: "data-leakage",
    term: "Утечка данных (data leakage)",
    definition:
      "Ситуация, когда при обучении модель использует информацию, недоступную в момент прогноза (например, будущее). Для временных рядов главный источник — случайное разбиение и признаки, посчитанные по всему ряду. Платформа исключает утечку конструктивно: сплиты только по времени, генерация признаков внутри фолда (fold-local).",
    related_article_ids: ["modeling-backtest"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "dropout-row",
    term: "Выброс (outlier)",
    definition:
      "Наблюдение, статистически резко выделяющееся из общего ряда значений. Отличать ошибку измерения (исправлять) от реального события (моделировать явно): удаление настоящего шока искажает механизм данных. Методы обнаружения — IQR, правило трёх сигм, остатки STL.",
    related_article_ids: ["preprocessing-missing-outliers"],
    stage_ids: ["preprocessing"],
  },
  {
    term_id: "ets",
    term: "ETS (экспоненциальное сглаживание)",
    definition:
      "Семейство моделей «ошибка-тренд-сезонность» (Error/Trend/Seasonality): уровень, тренд и сезонность оцениваются со сглаживающими параметрами, больший вес — свежим наблюдениям. Простые модели с малым числом параметров; Holt-Winters покрывает тренд и сезонность.",
    related_article_ids: ["modeling-catalog"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "fold-local",
    term: "Fold-local генерация признаков",
    definition:
      "Вычисление производных признаков (лаги, скользящие статистики, нормализации) внутри каждого фолда бэктеста независимо, а не по всему ряду. Исключает просачивание статистики будущего в прошлое фолды; в платформе встроено в движок бэктеста как контракт leak-safe.",
    related_article_ids: ["modeling-backtest"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "forecast-horizon",
    term: "Горизонт прогноза",
    definition:
      "Количество шагов вперёд, на которое строится прогноз. Ошибка растёт с горизонтом, а доверительный интервал расширяется; корректный горизонт согласован с частотой ряда и объёмом истории — прогноз на год по 12 месяцам истории статистически пуст.",
    related_article_ids: ["forecasting-intervals"],
    stage_ids: ["forecasting"],
  },
  {
    term_id: "garch",
    term: "GARCH (семейство)",
    definition:
      "Модели условной гетероскедастичности: моделируют не уровень ряда, а его дисперсию, меняющуюся во времени. Применяются к волатильности финансовых рядов (доходности, цены с кластерами волатильности). Расширения — EGARCH, GJR — ловят асимметрию реакции на шоки.",
    related_article_ids: ["modeling-catalog"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "mase",
    term: "MASE",
    definition:
      "Mean Absolute Scaled Error — ошибка прогноза, нормированная на ошибку наивного прогноза той же серии. MASE < 1 — модель лучше наивной, > 1 — хуже. Нормировка делает метрику сравнимой между рядами с разным масштабом; в платформе считается на out-of-sample фолдах.",
    related_article_ids: ["forecasting-accuracy-metrics"],
    stage_ids: ["modeling", "forecasting"],
  },
  {
    term_id: "missing-value",
    term: "Пропуск (missing value)",
    definition:
      "Отсутствующее наблюдение во временном ряде. Стратегия обработки зависит от механизма возникновения: технический пропуск интерполируется, содержательное отсутствие (не было продаж) заполняется нулём, длинные блоки требуют отдельного решения. См. MCAR/MAR/MNAR в литературе по данным.",
    related_article_ids: ["preprocessing-missing-outliers"],
    stage_ids: ["preprocessing"],
  },
  {
    term_id: "model-card",
    term: "Model Card",
    definition:
      "Итоговый артефакт этапа Моделирования: выбранная модель, её параметры, метрики бэктеста, ограничения и условия применимости — документированный «паспорт» модели, с которым работает этап Прогнозирования.",
    related_article_ids: ["modeling-catalog", "modeling-backtest"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "pelt",
    term: "PELT",
    definition:
      "Pruned Exact Linear Time — эффективный алгоритм точного поиска нескольких точек структурного сдвига в последовательности. Используется в EDA платформы (узел «Структурные сдвиги») и переиспользуется платформой для мониторинга собственных сигналов качества.",
    related_article_ids: ["eda-structural-breaks"],
    stage_ids: ["eda"],
  },
  {
    term_id: "regularity",
    term: "Регулярность ряда",
    definition:
      "Равномерность временного шага: расстояние между соседними наблюдениями одинаково. Нарушение регулярности ломает STL-декомпозицию, спектральный анализ и большинство моделей; восстанавливается ресемплированием или заполнением в Предобработке.",
    related_article_ids: ["preprocessing-regularity-stl"],
    stage_ids: ["validation", "preprocessing"],
  },
  {
    term_id: "seasonal-naive",
    term: "Seasonal naive",
    definition:
      "Наивный прогноз значением того же периода назад (для месячных данных — год назад). Естественный baseline для сезонных рядов; его ошибка — знаменатель метрики RMSSE и эталон, который сложные модели обязаны превзойти.",
    related_article_ids: ["modeling-catalog", "forecasting-accuracy-metrics"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "stl",
    term: "STL-декомпозиция",
    definition:
      "Seasonal-Trend decomposition using Loess: разложение ряда на тренд, сезонность и остаток. Требует регулярной сетки; robust-режим устойчив к выбросам. Один сезонный период за проход — для множественной сезонности нужны MSTL/TBATS.",
    related_article_ids: ["preprocessing-regularity-stl", "eda-seasonality"],
    stage_ids: ["preprocessing", "eda"],
  },
  {
    term_id: "stationarity",
    term: "Стационарность",
    definition:
      "Свойство ряда, при котором его статистические характеристики (уровень, дисперсия, автокорреляции) не меняются во времени. Большинство классических моделей работают на стационарном ряде; нестационарность уровня лечится дифференцированием, дисперсии — Box-Cox/логарифмом.",
    related_article_ids: ["eda-stationarity"],
    stage_ids: ["preprocessing", "eda", "modeling"],
  },
  {
    term_id: "tbats",
    term: "TBATS",
    definition:
      "Модель для рядов со сложными (в том числе нецелыми) сезонными периодами: Box-Cox + ARMA-остатки + тренд + несколько сезонных компонент. Ответ на мультисезонность, которую одна STL или Holt-Winters не покрывают.",
    related_article_ids: ["eda-seasonality", "modeling-catalog"],
    stage_ids: ["modeling", "eda"],
  },
  {
    term_id: "train-test-split",
    term: "Train / Test split для ряда",
    definition:
      "Разбиение данных на обучающую и тестовую части строго по времени: тест — последний отрезок, который модель не видела. Случайное перемешивание для временных рядов запрещено — оно создаёт утечку и переоценивает качество.",
    related_article_ids: ["modeling-backtest"],
    stage_ids: ["modeling"],
  },
  {
    term_id: "walk-forward",
    term: "Walk-forward валидация",
    definition:
      "Схема бэктеста: окно обучения сдвигается вперёд по истории, на каждом шаге модель прогнозирует следующий отрезок out-of-sample. Даёт распределение ошибок по фолдам вместо одной точки — устойчивая оценка того, как модель будет вести себя в меняющемся будущем.",
    related_article_ids: ["modeling-backtest", "forecasting-intervals"],
    stage_ids: ["modeling", "forecasting"],
  },
];

export const GLOSSARY_TERMS_COUNT = GLOSSARY_TERMS.length;
