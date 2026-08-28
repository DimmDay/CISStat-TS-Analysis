// packages/ui/lib/demoDatasets.ts
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
