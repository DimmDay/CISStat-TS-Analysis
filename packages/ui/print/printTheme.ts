// packages/ui/print/printTheme.ts
//
// PGV-07 — Shared pure print layout: светлая печатная тема
// (spec_passport_graphics_visual.md §3 инвариант 4 «Всегда light-print:
// непрозрачный белый фон, читаемые текст/цвета/научные признаки
// независимо от экранной темы»; §7 «Цвета/штриховки/линии устойчивы,
// красный/зелёный не единственный носитель смысла»).
//
// Ключевое решение (AC04): печатная тема — ЖЁСТКИЕ hex-константы, а не
// var()/tailwind-классы. Инлайн-стили print-бандла не зависят ни от
// активной темы экрана, ни от контекста документа: рендер в .dark-предке
// байт-идентичен светлому рендеру (динамический оракул printLayout.test).
//
// Значения НЕ придуманы заново: серые/осевые/серийные цвета взяты из
// светлой карты packages/ui/lib/chartVars.ts (CHART_VARS_LIGHT,
// источник — :root globals.css; паритет гвардится тестом ниже и
// ForecastExportMenu.vars.test.ts на экранной стороне). Print-тема —
// надстройка над картой: экранная экспорт-ветка (legacy ForecastExportMenu)
// не меняется (граница PGV-12).
//
// Чистота: модуль без состояния, без fetch, без времени, без случайности
// — pure function (статический оракул printLayout.test.tsx).

import { CHART_VARS_LIGHT } from "../lib/chartVars";

/** Версия контракта печатной темы (versioned, паритет PGV-01 схем). */
export const PRINT_THEME_VERSION = "pgv.print_theme/1";

/**
 * Светлая печатная палитра. Все значения — 6-значный непрозрачный hex
 * (оракул: isHexColor + запрет #000000 в фоне). Статусные цвета взяты
 * затемнением экранных (--status-*) для контраста на белом: текст в
 * печати читаемее при тёмных оттенках.
 */
export const PRINT_PALETTE = {
  /** Непрозрачный белый фон печатной страницы (§3.4). */
  page_background: "#FFFFFF",
  /** Основной текст. */
  ink: "#171717",
  /** Вторичный текст (подписи осей, примечания). */
  ink_muted: "#525252",
  /** Приглушённый текст (сноски, короткие IDs). */
  ink_faint: "#737373",
  /** Рамки/разделители. */
  border: "#E5E5E5",
  /** Сетка графиков (паритет --chart-grid). */
  grid: "#F0F0F0",
  /** Институциональный акцент (паритет --chart-brand, Статкомитет СНГ). */
  accent: "#2E3192",
  /** Основной серийный цвет (паритет --chart-blue). */
  series_blue: "#2563EB",
  /** Мягкий серийный цвет (паритет --chart-blue-soft). */
  series_blue_soft: "#93C5FD",
  /** Подложка шапок таблиц/мета-блоков. */
  band_fill: "#F5F7FB",
  /** Статусы: затемнённые экранные значения для печати на белом. */
  status_success: "#15803D",
  status_error: "#B91C1C",
  status_warning: "#B45309",
  status_neutral: "#525252",
} as const;

export type PrintPaletteKey = keyof typeof PRINT_PALETTE;

/** Семантический статус с дублированием смысла формой и текстом (§7). */
export interface PrintStatusMark {
  key: "positive" | "negative" | "warning" | "neutral";
  /** Жёсткий цвет статуса. */
  color: string;
  /** Текстовый/знаковый маркер: цвет не единственный носитель смысла. */
  mark: string;
  /** Человекочитаемая метка для легенды/сносок. */
  label: string;
}

/**
 * Статусные метки печати: рост/падение/предупреждение/нейтрально.
 * Знаки (+/−/!/·) дублируют цвет — распечатка читается без цвета
 * (ч/б принтер, дальтонизм, OCR-проверка PGV-AC23).
 */
export const PRINT_STATUS_MARKS: readonly PrintStatusMark[] = [
  { key: "positive", color: PRINT_PALETTE.status_success, mark: "+", label: "рост/улучшение" },
  { key: "negative", color: PRINT_PALETTE.status_error, mark: "−", label: "падение/ухудшение" },
  { key: "warning", color: PRINT_PALETTE.status_warning, mark: "!", label: "предупреждение" },
  { key: "neutral", color: PRINT_PALETTE.status_neutral, mark: "·", label: "без изменения" },
];

/** Шрифт печати: pinned-профиль рендерера (PGV-08 фиксирует стек в контейнере). */
export const PRINT_FONT_STACK =
  "'DejaVu Sans', 'Noto Sans SC', 'Liberation Sans', Arial, sans-serif";

/**
 * Типографская шкала в ФИЗИЧЕСКИХ единицах (pt). PGV13-VIS-01: прежние
 * «сырые» px применялись 1:1 на канвас 300 ppi и давали 2.88 pt тела
 * (находка независимого ревью VIS-01; §7 «Нельзя уменьшать до нечитаемого
 * шрифта»). Целевой коридор задачи: основной текст 9–10 pt (body 9.5),
 * служебный ~8 pt (small 8.5, micro 8), заголовки 16/12/11 pt.
 * px-шкала PRINT_TYPE_SCALE — точное производное через ptToPx.
 */
export const PRINT_TYPE_SCALE_PT = {
  title: 16,
  subtitle: 12,
  section: 11,
  body: 9.5,
  small: 8.5,
  micro: 8,
} as const;

/**
 * Печатные отступы в ФИЗИЧЕСКИХ единицах (мм). Поля страницы, зазоры
 * колонтитулов и паддинги ячеек — производные PRINT_SPACING_PX через
 * mmToPx (§7: композиция «верх/центр/низ» на физическом листе).
 */
export const PRINT_SPACING_MM = {
  /** Поля страницы рамки PrintPageFrame (§7). */
  page_margin: 12,
  /** Зазор между верхом/центром/низом каркаса. */
  band_gap: 4,
  /** Паддинг колонтитулов (верх/низ страницы). */
  band_pad: 2.5,
  /** Зазор между секциями/группами документа. */
  block_gap: 2,
  /** Межстрочный зазор label/значение, мелкие интервалы. */
  item_gap: 1,
  /** Горизонтальный паддинг ячеек таблиц. */
  cell_pad: 1.2,
  /** Вертикальный паддинг ячеек таблиц. */
  cell_pad_y: 1,
} as const;

/** ppi печати каталога профилей PGV-01 (паритет гвардится printTheme.test). */
export const PRINT_PROFILE_PPI = 300;

/** pt → px печати: 1 pt = ppi/72 px (при 300 ppi — 4.166667 px). */
export function ptToPx(pt: number, ppi: number = PRINT_PROFILE_PPI): number {
  return (pt * ppi) / 72;
}

/** мм → px печати: 1 мм = ppi/25.4 px (при 300 ppi — 11.811024 px). */
export function mmToPx(mm: number, ppi: number = PRINT_PROFILE_PPI): number {
  return (mm * ppi) / 25.4;
}

/**
 * Типографская шкала (px при ppi каталога, производное PRINT_TYPE_SCALE_PT).
 * Все потребители (printLayout/printSections/printIh/printPassport/
 * printComparison/rendererCore) читают эту шкалу — единственный источник
 * размеров текста печати. Обратный перевод px→pt даёт целевые pt.
 */
export const PRINT_TYPE_SCALE = {
  title: ptToPx(PRINT_TYPE_SCALE_PT.title),
  subtitle: ptToPx(PRINT_TYPE_SCALE_PT.subtitle),
  section: ptToPx(PRINT_TYPE_SCALE_PT.section),
  body: ptToPx(PRINT_TYPE_SCALE_PT.body),
  small: ptToPx(PRINT_TYPE_SCALE_PT.small),
  micro: ptToPx(PRINT_TYPE_SCALE_PT.micro),
} as const;

/** Отступы в px (производное PRINT_SPACING_MM через mmToPx). */
export const PRINT_SPACING_PX = {
  page_margin: mmToPx(PRINT_SPACING_MM.page_margin),
  band_gap: mmToPx(PRINT_SPACING_MM.band_gap),
  band_pad: mmToPx(PRINT_SPACING_MM.band_pad),
  block_gap: mmToPx(PRINT_SPACING_MM.block_gap),
  item_gap: mmToPx(PRINT_SPACING_MM.item_gap),
  cell_pad: mmToPx(PRINT_SPACING_MM.cell_pad),
  cell_pad_y: mmToPx(PRINT_SPACING_MM.cell_pad_y),
} as const;

/** 6-значный непрозрачный hex-цвет (#RRGGBB). */
export function isHexColor(value: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(value);
}

/**
 * Резолв имени переменной экранной темы по СВЕТЛОЙ карте chartVars.
 * Единственный источник светлых значений — CHART_VARS_LIGHT (паритет
 * гвардится оракулом printLayout.test). Неизвестное имя — null.
 */
export function resolveChartVarLight(name: string): string | null {
  const direct = CHART_VARS_LIGHT[name];
  if (direct !== undefined) return direct;
  const prefixed = CHART_VARS_LIGHT[name.replace(/^--/, "")];
  return prefixed !== undefined ? prefixed : null;
}

/**
 * Подстановка светлых hex вместо var(--…) в значении стиля.
 * Вне карты — ссылка остаётся как есть (fail-visible: видна в артефакте
 * и ловится проверкой финального контейнера PGV-AC23), не молча чёрная.
 */
export function resolveVarStringLight(value: string): string {
  return value.replace(/var\((--[a-zA-Z0-9-]+)\)/g, (match, name: string) => {
    const resolved = resolveChartVarLight(name);
    return resolved === null ? match : resolved;
  });
}
