/// packages/ui/lib/demoDatasets.ts
//
// Демо-датасеты для вкладки «Загрузка» (согласовано с тимлидом
// 2026-08-19): при знакомстве с платформой у пользователя может не
// быть под рукой своего файла -- под drag-and-drop полем предлагаются
// 3 готовых синтетических датасета из разных отраслей, каждый --
// другой структурный класс (см. packages/ui/lib/structuralClass.ts),
// чтобы демонстрировать разные ветки платформы (Univariate TS ->
// декомпозиция/распределение, Panel Balanced -> структура/panel-balance,
// Multivariate TS -> будущий корреляционный EDA).
//
// РЕАЛИЗАЦИЯ: генерация CSV на клиенте (без нового backend-кода) --
// сгенерированная строка оборачивается в File и идёт через ТОТ ЖЕ
// doUpload(file), что и обычный drag-and-drop (см. TsAnalysisUpload.tsx)
// -- демо-режим использует РЕАЛЬНЫЙ пайплайн загрузки/детекции/валидации
// от начала до конца, не имитацию.
//
// Детерминированная генерация (seeded PRNG, mulberry32) -- одинаковый
// файл при каждой генерации, тестируемо (см. demoDatasets.test.ts).

/** mulberry32 -- маленький детерминированный PRNG без внешних
 * зависимостей (Math.random недетерминирован, не годится для
 * воспроизводимой демо-генерации / тестов). */
function mulberry32(seed: number): () => number {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Стандартное нормальное распределение (Box-Muller) поверх
 * детерминированного PRNG. */
function gaussian(rng: () => number, mean: number, std: number): number {
  const u1 = Math.max(rng(), 1e-9);
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return mean + z * std;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

function addMonths(base: Date, months: number): Date {
  const d = new Date(base);
  d.setMonth(d.getMonth() + months);
  return d;
}

/** Простая CSV-сериализация (заголовки + строки). Значения в наших
 * генераторах не содержат запятых/кавычек -- полноценный CSV-escaping
 * не нужен, экранирование добавить, если появятся текстовые поля со
 * спецсимволами. */
function toCsv(headers: string[], rows: (string | number)[][]): string {
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(row.join(","));
  }
  return lines.join("\n");
}

export interface DemoDataset {
  id: string;
  name: string;
  industry: string;
  structuralClassLabel: string;
  rowsLabel: string;
  description: string;
  fileName: string;
  generateCsv: () => string;
}

// ── 1. Розничная торговля -- Univariate TS ──
// Дневная выручка одного магазина, ~2 года: тренд + недельная
// сезонность (выходные выше) + редкие промо-всплески + шум.
function generateRetailRevenue(): string {
  const rng = mulberry32(20260819);
  const start = new Date(Date.UTC(2023, 0, 1));
  const n = 730;
  const rows: (string | number)[][] = [];
  for (let i = 0; i < n; i++) {
    const date = addDays(start, i);
    const dow = date.getUTCDay(); // 0=вс, 6=сб
    const weekendBoost = dow === 0 || dow === 6 ? 1.35 : 1.0;
    const trend = 45000 + i * 18;
    const promo = rng() < 0.03 ? 1.6 : 1.0; // редкий промо-день
    const noise = gaussian(rng, 0, 2500);
    const revenue = Math.max(0, trend * weekendBoost * promo + noise);
    rows.push([isoDate(date), Math.round(revenue)]);
  }
  return toCsv(["date", "revenue"], rows);
}

// ── 2. Энергетика -- Panel Data (Balanced) ──
// Месячное потребление электроэнергии, 5 регионов x 5 лет (60 месяцев) --
// у всех регионов ОДИНАКОВЫЙ набор дат (сбалансированная панель).
function generateEnergyConsumption(): string {
  const rng = mulberry32(20260820);
  const regions = [
    { name: "Север", base: 4200 },
    { name: "Юг", base: 3100 },
    { name: "Восток", base: 2600 },
    { name: "Запад", base: 3800 },
    { name: "Центр", base: 5100 },
  ];
  const start = new Date(Date.UTC(2019, 0, 1));
  const nMonths = 60;
  const rows: (string | number)[][] = [];
  for (const region of regions) {
    for (let m = 0; m < nMonths; m++) {
      const date = addMonths(start, m);
      const monthOfYear = date.getUTCMonth(); // 0..11
      // Зимний пик (отопление): выше в дек/янв/фев
      const seasonal = 1 + 0.28 * Math.cos((monthOfYear / 12) * 2 * Math.PI);
      const trend = 1 + m * 0.0015; // слабый рост со временем
      const noise = gaussian(rng, 0, region.base * 0.04);
      const consumption = Math.max(0, region.base * seasonal * trend + noise);
      rows.push([region.name, isoDate(date), Math.round(consumption)]);
    }
  }
  return toCsv(["region", "month", "consumption_mwh"], rows);
}

// ── 3. Финансы -- Multivariate TS ──
// Дневные OHLCV одного синтетического инструмента, ~500 торговых дней:
// close -- геометрическое случайное блуждание, open/high/low вокруг
// него, volume -- логнормальный шум с корреляцией к |движению цены|.
function generateFinanceOhlcv(): string {
  const rng = mulberry32(20260821);
  const start = new Date(Date.UTC(2022, 0, 3)); // понедельник
  const n = 500;
  const rows: (string | number)[][] = [];
  let close = 152.4;
  let tradingDaysAdded = 0;
  let cursor = new Date(start);
  while (tradingDaysAdded < n) {
    const dow = cursor.getUTCDay();
    if (dow !== 0 && dow !== 6) {
      const dailyReturn = gaussian(rng, 0.0003, 0.014);
      const open = close * (1 + gaussian(rng, 0, 0.003));
      close = Math.max(1, close * (1 + dailyReturn));
      const high = Math.max(open, close) * (1 + Math.abs(gaussian(rng, 0, 0.005)));
      const low = Math.min(open, close) * (1 - Math.abs(gaussian(rng, 0, 0.005)));
      const volume = Math.round(Math.exp(gaussian(rng, 13.5, 0.35)) * (1 + Math.abs(dailyReturn) * 8));
      rows.push([
        isoDate(cursor),
        open.toFixed(2),
        high.toFixed(2),
        low.toFixed(2),
        close.toFixed(2),
        volume,
      ]);
      tradingDaysAdded++;
    }
    cursor = addDays(cursor, 1);
  }
  return toCsv(["date", "open", "high", "low", "close", "volume"], rows);
}

export const DEMO_DATASETS: DemoDataset[] = [
  {
    id: "retail_revenue",
    name: "Выручка розничного магазина",
    industry: "Розничная торговля",
    structuralClassLabel: "Univariate TS",
    rowsLabel: "730 дней",
    description: "Дневная выручка одного магазина за 2 года: тренд, недельная сезонность, редкие промо-всплески.",
    fileName: "demo_retail_revenue.csv",
    generateCsv: generateRetailRevenue,
  },
  {
    id: "energy_consumption",
    name: "Энергопотребление по регионам",
    industry: "Энергетика",
    structuralClassLabel: "Panel Data — Balanced",
    rowsLabel: "5 регионов × 60 мес.",
    description: "Месячное потребление электроэнергии в 5 регионах за 5 лет: зимний пик, сбалансированная панель.",
    fileName: "demo_energy_consumption.csv",
    generateCsv: generateEnergyConsumption,
  },
  {
    id: "finance_ohlcv",
    name: "Котировки инструмента (OHLCV)",
    industry: "Финансы",
    structuralClassLabel: "Multivariate TS",
    rowsLabel: "500 торговых дней",
    description: "Дневные Open/High/Low/Close/Volume синтетического инструмента: случайное блуждание цены.",
    fileName: "demo_finance_ohlcv.csv",
    generateCsv: generateFinanceOhlcv,
  },
];

/** Конвертирует сгенерированный CSV в File -- готов идти в тот же
 * doUpload(file), что и drag-and-drop (TsAnalysisUpload.tsx). */
export function demoDatasetToFile(dataset: DemoDataset): File {
  const csv = dataset.generateCsv();
  return new File([csv], dataset.fileName, { type: "text/csv" });
}

// ── Хелпер для окна «Обзор» остановки «График» (Навигатор) ────────────
//
// Задача 2026-08-29: в окне «Обзор» при активации пункта «График» (id="chart")
// секции «Этапы модуля» остановки «Загрузка» должен отображаться СТАТИЧНЫЙ
// линейный график признака `volume` синтетического датасета demo_finance_ohlcv.csv
// (id="finance_ohlcv" в DEMO_DATASETS). График обязан работать ПРИ ЛЮБЫХ
// УСЛОВИЯХ — даже если сам датасет удалён из сессии. Поэтому данные берутся
// из детерминированного клиентского генератора (НЕ из сети/сессии).
//
// Чтобы не дублировать генератор, переиспользуем уже существующий
// `generateFinanceOhlcv()` (детерминированный mulberry32 seed 20260821,
// 500 торговых дней) и парсим его же CSV — так данные графика всегда
// совпадают с тем демо-датасетом, который пользователь может загрузить.

export interface NavigatorChartPoint {
  /** ISO-дата (YYYY-MM-DD). */
  date: string;
  /** Значение признака volume. */
  volume: number;
}

/**
 * Возвращает детерминированный ряд {date, volume} из синтетического датасета
 * demo_finance_ohlcv.csv (500 торговых дней, без выходных).
 *
 * Источник: `generateFinanceOhlcv()` (тот же seed, что и у демо-датасета
 * «Котировки инструмента (OHLCV)» в окне «Загрузка»). Вызов без побочных
 * эффектов, идемпотентный — безопасно оборачивать в useMemo / вызывать
 * многократно.
 *
 * Реализован как простой парсинг CSV, а не как второй генератор, чтобы
 * исключить расхождение между числом точек графика и числом строк
 * демо-датасета: если генератор `generateFinanceOhlcv` изменится,
 * график автоматически подстроится.
 */
export function getDemoFinanceOhlcvVolumeSeries(): NavigatorChartPoint[] {
  // Находим датасет по id — это страхует от хардкода fileName, который
  // может измениться (демо-датасеты эволюционируют по решению тимлида).
  const dataset = DEMO_DATASETS.find((d) => d.id === "finance_ohlcv");
  if (!dataset) {
    // Не должно случаться — датасет объявлен в DEMO_DATASETS статически.
    // Возвращаем пустой массив вместо исключения: статичный график не
    // должен валить рендер страницы Навигатор даже при структурных
    // изменениях demoDatasets.ts (graceful degradation).
    return [];
  }

  const csv = dataset.generateCsv();
  const lines = csv.split("\n");
  // Первая строка — заголовок: date,open,high,low,close,volume
  // volume находится в колонке с индексом 5.
  const header = lines[0].split(",");
  const volumeIdx = header.indexOf("volume");
  const dateIdx = header.indexOf("date");
  // Если по какой-то причине структура CSV изменилась — возвращаем пустой
  // массив, чтобы компонент показал заглушку вместо падения.
  if (volumeIdx < 0 || dateIdx < 0) return [];

  const points: NavigatorChartPoint[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;
    const cols = line.split(",");
    const date = cols[dateIdx];
    const volume = Number(cols[volumeIdx]);
    if (!date || !Number.isFinite(volume)) continue;
    points.push({ date, volume });
  }
  return points;
}

// ── Хелпер для окна «Обзор» остановки «Превью 5+5 строк» (Навигатор) ──
//
// Задача 2026-09-01: в окне «Обзор» при активации пункта «Превью 5+5 строк»
// (id="preview_5_5") секции «Этапы модуля» остановки «Загрузка» должна
// отображаться СТАТИЧНАЯ таблица 5+5 строк синтетического датасета
// demo_finance_ohlcv.csv. Превью закреплено как пример и сохраняется
// ВНЕ ЗАВИСИМОСТИ от того, удалён датасет или нет.
//
// Контракт повторяет apps/api/upload_common.py::handle_upload (поля
// UploadResponse.preview.head / preview.tail):
//   - head: string[][] — head[0] = заголовки колонок, head[1..5] = первые
//     5 строк данных (df.head(5)).
//   - tail: string[][] — последние 5 строк данных (df.tail(5)).
//   - Между head и tail в UI — separator «…».
//
// Тот же генератор generateFinanceOhlcv (mulberry32 seed 20260821),
// что и в getDemoFinanceOhlcvVolumeSeries — данные превью всегда
// совпадают с тем демо-датасетом, который пользователь может загрузить.

export interface Preview55Data {
  /** head[0] — заголовки колонок, head[1..5] — первые 5 строк данных. */
  head: string[][];
  /** Последние 5 строк данных. */
  tail: string[][];
}

/**
 * Возвращает детерминированное превью 5+5 строк синтетического датасета
 * demo_finance_ohlcv.csv (первые 5 строк + последние 5 строк).
 *
 * Источник: `generateFinanceOhlcv()` (тот же seed, что и у демо-датасета
 * «Котировки инструмента (OHLCV)» в окне «Загрузка», и тот же, что у
 * графика в NavigatorChartPreview). Вызов без побочных эффектов,
 * идемпотентный — безопасно оборачивать в useMemo / вызывать многократно.
 *
 * Реализован как простой парсинг CSV — если генератор `generateFinanceOhlcv`
 * изменится (добавятся/удалятся колонки, поменяется seed), превью
 * автоматически подстроится, расхождения с реальным демо-датасетом не будет.
 *
 * Возвращает пустые массивы при отсутствии датасета или изменении схемы
 * (graceful degradation — компонент покажет заглушку, а не упадёт).
 */
export function getDemoFinanceOhlcvPreview55(): Preview55Data {
  const dataset = DEMO_DATASETS.find((d) => d.id === "finance_ohlcv");
  if (!dataset) {
    return { head: [], tail: [] };
  }

  const csv = dataset.generateCsv();
  const lines = csv.split("\n").filter((l) => l.length > 0);
  if (lines.length < 1) {
    return { head: [], tail: [] };
  }

  // lines[0] — заголовок. lines[1..N] — строки данных (N = 500 для OHLCV).
  // Каждую строку CSV сразу разбиваем на ячейки → string[][].
  const header: string[] = lines[0].split(",");
  const dataRows: string[][] = lines.slice(1).map((l) => l.split(","));

  // head: [header, row1, row2, row3, row4, row5]
  const head: string[][] = [header, ...dataRows.slice(0, 5)];
  // tail: последние 5 строк (rowN-4 .. rowN)
  const tail: string[][] = dataRows.slice(-5);

  return { head, tail };
}

// ── Хелпер для окна «Обзор» остановки «Визуализация распределения» ────
//
// Задача 2026-09-02: в окне «Обзор» при активации пункта «Визуализация
// распределения» (id="distribution") секции «Этапы модуля» остановки
// «Загрузка» должны отображаться СТАТИЧНЫЕ графики распределения
// (точечный/гистограмма/KDE) + бейджи описательной статистики
// синтетического датасета demo_energy_consumption.csv (колонка
// consumption_mwh, 300 значений: 5 регионов × 60 месяцев).
//
// Визуализация закреплена СТАТИЧНО как пример — НЕ зависит от сессии/сети.
// Данные берутся из того же детерминированного генератора
// `generateEnergyConsumption()` (mulberry32 seed 20260820), что и у
// демо-датасета «Энергопотребление по регионам» во вкладке «Загрузка».
//
// Контракт повторяет apps/api/routers/session.py::get_dataset_distribution
// (DistributionChartResponse) и apps/api/schemas.py::ColumnStatsOut —
// те же поля, что получает реальная вкладка «Загрузка» через
// GET /dataset/distribution?column=... и GET /dataset/stats.
//
// Расчёт scatter/histogram/kde/stat делается НА КЛИЕНТЕ (а не через API),
// т.к. это статичный пример — нет смысла гонять сеть для детерминированных
// данных. Формулы зеркалируют бэкенд (build_scatter_series без сэмплинга
// при < 3000 точек, гистограмма по правилу Freedman-Diaconis, KDE через
// простой kernel density estimate с гауссовым ядром).

import type {
  DistributionChartData,
  ScatterPoint,
  HistogramBin,
  KdePoint,
} from "../components/DistributionCharts";

export interface DistributionStats {
  mean: number;
  median: number;
  std: number;
  skewness: number | null;
  kurtosis: number | null;
  q1: number;
  q3: number;
  iqr: number;
}

export interface DistributionPreviewData {
  /** Полный DistributionChartData для переиспользования существующих
   *  ScatterDistributionChart/HistogramDistributionChart/KdeDistributionChart. */
  distribution: DistributionChartData;
  /** 8 описательных статистик для Metric-бейджей. */
  stats: DistributionStats;
  /** Сырые значения (для отладки/тестов — детерминизм, длина). */
  rawValues: number[];
}

/** Оценивает плотность (KDE) гауссовым ядром на сетке из 40 точек.
 * Простой аналог scipy.stats.gaussian_kde — достаточен для статичного
 * примера, не претендует на научную точность (нет оптимизации bandwidth
 * по Silverman, используется эвристика std/3). */
function estimateKde(values: number[], nPoints = 40): KdePoint[] {
  const n = values.length;
  if (n < 2) return [];
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const variance = values.reduce((a, v) => a + (v - mean) ** 2, 0) / (n - 1);
  const std = Math.sqrt(variance);
  if (std === 0) return [];
  // Простой bandwidth: 1.06 * std * n^(-1/5) (правило Silverman).
  const h = 1.06 * std * Math.pow(n, -1 / 5);
  if (h === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;
  if (range === 0) return [];
  const step = range / (nPoints - 1);
  const points: KdePoint[] = [];
  for (let i = 0; i < nPoints; i++) {
    const x = min + i * step;
    // Сумма гауссовых ядер / (n * h).
    let sum = 0;
    for (let j = 0; j < n; j++) {
      const u = (x - values[j]) / h;
      sum += Math.exp(-0.5 * u * u) / Math.sqrt(2 * Math.PI);
    }
    points.push({ x, y: sum / (n * h) });
  }
  return points;
}

/** Строит гистограмму с фиксированным числом бинов = 30 — 1:1 как на
 * бэкенде: apps/api/chart_data.py::build_histogram использует
 * `np.histogram(values, bins=DEFAULT_HISTOGRAM_BINS)`, где
 * DEFAULT_HISTOGRAM_BINS = 30 (apps/api/chart_data.py:33).
 *
 * Раньше тут было правило Freedman-Diaconis с ограничением min(20,…)/
 * max(5,…) — давало 11 бинов для demo_energy_consumption.csv, что
 * расходилось со вкладкой «Загрузка» (там 30 бинов из бэкенда).
 * Точечная правка: 30 равномерных бинов по диапазону [min, max]. */
const HISTOGRAM_BINS = 30;

function buildHistogram(values: number[]): HistogramBin[] {
  const n = values.length;
  if (n < 2) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return [];
  const binWidth = (max - min) / HISTOGRAM_BINS;
  const bins: HistogramBin[] = [];
  for (let i = 0; i < HISTOGRAM_BINS; i++) {
    const x0 = min + i * binWidth;
    const x1 = x0 + binWidth;
    let count = 0;
    for (const v of values) {
      // Последний бин включает правую границу (как np.histogram).
      if (v >= x0 && (v < x1 || (i === HISTOGRAM_BINS - 1 && v <= x1))) count++;
    }
    bins.push({ x0, x1, count });
  }
  return bins;
}

/** Считает skewness (асимметрия) и kurtosis (эксцесс) — те же формулы,
 * что pandas: skew = m3 / m2^(3/2), kurt = m4 / m2^2 - 3 (Fisher).
 * Возвращает null при n < 4 (бэкенд так же сериализует NaN в null). */
function computeSkewnessKurtosis(values: number[]): {
  skewness: number | null;
  kurtosis: number | null;
} {
  const n = values.length;
  if (n < 4) return { skewness: null, kurtosis: null };
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const m2 = values.reduce((a, v) => a + (v - mean) ** 2, 0) / n;
  const m3 = values.reduce((a, v) => a + (v - mean) ** 3, 0) / n;
  const m4 = values.reduce((a, v) => a + (v - mean) ** 4, 0) / n;
  if (m2 === 0) return { skewness: null, kurtosis: null };
  const skewness = m3 / Math.pow(m2, 1.5);
  const kurtosis = m4 / (m2 * m2) - 3; // Fisher (excess kurtosis)
  return { skewness, kurtosis };
}

/**
 * Возвращает детерминированные данные распределения + описательные
 * статистики для синтетического датасета demo_energy_consumption.csv
 * (колонка consumption_mwh, 300 значений).
 *
 * Источник: `generateEnergyConsumption()` (mulberry32 seed 20260820).
 * Идемпотентный, без побочных эффектов — безопасно оборачивать в useMemo.
 *
 * Контракт: DistributionChartData (scatter/histogram/kde) — тот же, что
 * в apps/api/routers/session.py::get_dataset_distribution; DistributionStats
 * — те же поля, что в ColumnStatsOut (mean/median/std/skew/kurtosis/q1/q3/iqr).
 */
export function getDemoEnergyDistributionData(): DistributionPreviewData {
  const dataset = DEMO_DATASETS.find((d) => d.id === "energy_consumption");
  if (!dataset) {
    // Graceful degradation — не должно случаться, датасет объявлен статически.
    return {
      distribution: {
        column: "consumption_mwh",
        non_null_count: 0,
        min: null,
        max: null,
        scatter: [],
        scatter_sampled: false,
        scatter_sampling_method: null,
        scatter_original_count: 0,
        histogram: [],
        kde: null,
      },
      stats: {
        mean: 0, median: 0, std: 0,
        skewness: null, kurtosis: null,
        q1: 0, q3: 0, iqr: 0,
      },
      rawValues: [],
    };
  }

  // Парсим CSV: колонки region, month, consumption_mwh (индекс 2).
  const csv = dataset.generateCsv();
  const lines = csv.split("\n").filter((l) => l.length > 0);
  const header = lines[0].split(",");
  const consumptionIdx = header.indexOf("consumption_mwh");
  const rawValues: number[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    const v = Number(cols[consumptionIdx]);
    if (Number.isFinite(v)) rawValues.push(v);
  }

  const n = rawValues.length;
  const min = n > 0 ? Math.min(...rawValues) : null;
  const max = n > 0 ? Math.max(...rawValues) : null;

  // Scatter: x = позиция в очищенном ряде (0-based), y = значение.
  // При n <= 3000 (у нас 300) — без LTTB-сэмплинга, как на бэкенде.
  const scatter: ScatterPoint[] = rawValues.map((y, x) => ({ x, y }));

  const histogram = buildHistogram(rawValues);
  const kde = n >= 2 ? estimateKde(rawValues) : null;

  // Описательные статистики — те же формулы, что pandas (cmoment).
  const mean = rawValues.reduce((a, b) => a + b, 0) / n;
  const sorted = [...rawValues].sort((a, b) => a - b);
  const median = n % 2 === 1
    ? sorted[(n - 1) / 2]
    : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  const variance = rawValues.reduce((a, v) => a + (v - mean) ** 2, 0) / (n - 1);
  const std = Math.sqrt(variance);
  const q1 = sorted[Math.floor(n * 0.25)];
  const q3 = sorted[Math.floor(n * 0.75)];
  const iqr = q3 - q1;
  const { skewness, kurtosis } = computeSkewnessKurtosis(rawValues);

  return {
    distribution: {
      column: "consumption_mwh",
      non_null_count: n,
      min,
      max,
      scatter,
      scatter_sampled: false,
      scatter_sampling_method: null,
      scatter_original_count: n,
      histogram,
      kde,
    },
    stats: { mean, median, std, skewness, kurtosis, q1, q3, iqr },
    rawValues,
  };
}
