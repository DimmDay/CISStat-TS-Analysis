"use client";

// packages/ui/components/TsAnalysisUpload.tsx
//
// ОБЩИЙ компонент фичи "Загрузка" -- используется И embedded-,
// И standalone-приложением (см. архитектурный принцип: одна UI-логика,
// разные обёртки -- урок от 4 копий calculate_ts_passport учтён).
//
// Контракт вкладки "Загрузка" (по решению тимлида):
//   ✅ Превью датасета
//   ✅ Техническая информация (строки/колонки/память/типы)
//   ✅ Визуализация распределения (точечный + гистограмма+KDE + KDE + статистики) -- БЕЗ СОКРАЩЕНИЙ
//   ✅ Подтверждение автоопределения (дата/группировка/частота) с override
//   ✅ Teaser качества (только счётчики → Валидация)
//   ✅ Предупреждения парсинга (явные флаг, если что-то пошло не так)
//   ❌ Корреляция, STL, ACF/PACF, FFT, периодограмма, вейвлет -- уехали в EDA
//   ❌ Полный паспорт 13 свойств -- уехал в Modeling
//
// Состояние: ПРОТОТИП. Данные -- моковые, как и в TsAnalysisPreprocessing.
// Когда бэкенд /v1/internal/ingest, /detect-structure, /upload-summary,
// /quality-teaser будут готовы -- заменить моки на реальные вызовы.

import { useState } from "react";
import Link from "next/link";
import {
  Upload,
  FileText,
  Calendar,
  Tag,
  Clock,
  ChevronDown,
  Database,
  Table as TableIcon,
  Eye,
  BarChart3,
  ScatterChart,
  Activity,
  Filter,
  AlertTriangle,
  ArrowRight,
  Info,
  RefreshCw,
  Check,
} from "lucide-react";
import { Button } from "./Button";
import { useAppShell } from "../context/AppShellContext";

// ──────────────────────────────────────────────────────────────────────
// МОКОВЫЕ ДАННЫЕ (заменить на ответы API о Фазе 1)
// ──────────────────────────────────────────────────────────────────────

interface ColumnInfo {
  name: string;
  dtype: string;
  typeIcon: "numeric" | "datetime" | "categorical" | "text";
  nonNull: number;
  nulls: number;
  unique: number;
}

interface ParseWarning {
  type: "encoding" | "header" | "delimiter";
  message: string;
}

interface DetectionCandidate {
  name: string;
  score: number;
}

interface StructureDetection {
  dateCol: { selected: string; confidence: number; candidates: DetectionCandidate[] };
  entityCol: { selected: string; confidence: number; candidates: DetectionCandidate[] };
  freq: { selected: string; confidence: number; options: string[] };
}

interface DistStats {
  type: string;
  mean: number;
  median: number;
  std: number;
  skew: number;
  kurt: number;
  q1: number;
  q3: number;
  iqr: number;
}

interface QualityTeaser {
  colsWithMissing: number;
  colsWithOutliers: number;
  rowsTotal: number;
  duplicates: number;
  missingCols: string[];
  outlierCols: string[];
}

const MOCK_COLUMNS: ColumnInfo[] = [
  { name: "Order Date", dtype: "datetime64[ns]", typeIcon: "datetime", nonNull: 9800, nulls: 0, unique: 1234 },
  { name: "Ship Date", dtype: "datetime64[ns]", typeIcon: "datetime", nonNull: 9800, nulls: 0, unique: 1320 },
  { name: "Sales", dtype: "float64", typeIcon: "numeric", nonNull: 9789, nulls: 11, unique: 5678 },
  { name: "Profit", dtype: "float64", typeIcon: "numeric", nonNull: 9700, nulls: 100, unique: 3456 },
  { name: "Quantity", dtype: "int64", typeIcon: "numeric", nonNull: 9800, nulls: 0, unique: 14 },
  { name: "Discount", dtype: "float64", typeIcon: "numeric", nonNull: 9750, nulls: 50, unique: 12 },
  { name: "Country", dtype: "object", typeIcon: "categorical", nonNull: 9800, nulls: 0, unique: 14 },
  { name: "Region", dtype: "object", typeIcon: "categorical", nonNull: 9800, nulls: 0, unique: 52 },
  { name: "Category", dtype: "object", typeIcon: "categorical", nonNull: 9800, nulls: 0, unique: 3 },
  { name: "Product Name", dtype: "object", typeIcon: "text", nonNull: 9800, nulls: 0, unique: 1845 },
];

const MOCK_PARSE_WARNINGS: ParseWarning[] = [
  {
    type: "encoding",
    message:
      "Колонка «Order Date» распознана как текст, потребовалась конвертация (encoding=windows-1251 определён автоматически).",
  },
];

const MOCK_DETECTION: StructureDetection = {
  dateCol: {
    selected: "Order Date",
    confidence: 92,
    candidates: [
      { name: "Order Date", score: 0.92 },
      { name: "Ship Date", score: 0.71 },
      { name: "Row ID", score: 0.05 },
    ],
  },
  entityCol: {
    selected: "Country",
    confidence: 88,
    candidates: [
      { name: "Country", score: 0.88 },
      { name: "Region", score: 0.64 },
      { name: "Category", score: 0.41 },
    ],
  },
  freq: {
    selected: "D — ежедневная",
    confidence: 76,
    options: [
      "D — ежедневная",
      "W — недельная",
      "M — месячная",
      "Q — квартальная",
      "(авто, не получилось)",
    ],
  },
};

const MOCK_DIST_STATS: DistStats = {
  type: "🟠 Непрерывное — Логнормальное",
  mean: 229.86,
  median: 54.49,
  std: 623.25,
  skew: 12.973,
  kurt: 305.318,
  q1: 17.28,
  q3: 209.94,
  iqr: 192.66,
};

const MOCK_QUALITY: QualityTeaser = {
  colsWithMissing: 3,
  colsWithOutliers: 1,
  rowsTotal: 9800,
  duplicates: 0,
  missingCols: ["Sales", "Profit", "Discount"],
  outlierCols: ["Profit"],
};

const NUMERIC_COLS = ["Sales", "Profit", "Quantity", "Discount"];
const PREVIEW_ROWS = [
  { OrderDate: "2023-01-04", Country: "Russia", Region: "Central", Sales: 261.96, Profit: 41.91, Category: "Furniture" },
  { OrderDate: "2023-01-04", Country: "Russia", Region: "Central", Sales: 731.94, Profit: 219.58, Category: "Furniture" },
  { OrderDate: "2023-01-05", Country: "Kazakhstan", Region: "North", Sales: 957.58, Profit: -343.93, Category: "Office Supplies" },
  { OrderDate: "2023-01-06", Country: "Belarus", Region: "West", Sales: 124.55, Profit: 14.12, Category: "Technology" },
  { OrderDate: "2023-01-07", Country: "Russia", Region: "East", Sales: 542.10, Profit: 88.45, Category: "Office Supplies" },
];

const TYPE_ICON = {
  numeric: "N",
  datetime: "D",
  categorical: "C",
  text: "T",
} as const;

// ──────────────────────────────────────────────────────────────────────
// ВСПОМОГАТЕЛЬНЫЕ
// ──────────────────────────────────────────────────────────────────────

function confidenceColor(pct: number): string {
  if (pct >= 85) return "bg-green-100 text-green-700";
  if (pct >= 70) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

function formatNum(n: number): string {
  return n.toLocaleString("ru-RU").replace(/,/g, " ");
}

// ──────────────────────────────────────────────────────────────────────
// ГЛАВНЫЙ КОМПОНЕНТ
// ──────────────────────────────────────────────────────────────────────

export function TsAnalysisUpload() {
  const { setActiveDataset } = useAppShell();
  const [selectedDistCol, setSelectedDistCol] = useState(NUMERIC_COLS[0]);
  const [fileName, setFileName] = useState<string | null>("train.csv");
  const [source, setSource] = useState<"file" | "db">("file");
  const [isUploaded, setIsUploaded] = useState(true); // мок: файл уже загружен
  const [detection, setDetection] = useState<StructureDetection>(MOCK_DETECTION);

  const totalRows = 9800;
  const totalCols = MOCK_COLUMNS.length;
  const memoryMb = 2.42;
  const numericCount = MOCK_COLUMNS.filter((c) => c.typeIcon === "numeric").length;
  const textCount = MOCK_COLUMNS.filter((c) => c.typeIcon !== "numeric").length;

  const handleMockUpload = () => {
    const name = fileName ?? "train.csv";
    // Извлекаем код частоты из detection (например, "D — ежедневная" → "D")
    const freqCode = detection.freq.selected.split(" ")[0] || undefined;
    setActiveDataset({
      name,
      rows: totalRows,
      sizeLabel: `${memoryMb} MB`,
      frequency: freqCode,
      domain: "financial", // мок: Superstore → финансовые данные
    });
    setIsUploaded(true);
  };

  const handleApplyOverride = () => {
    // ЗАМЕНИТЬ: PATCH /v1/internal/datasets/{id}/column-mapping
    // Пока -- просто перерисовка с теми же данными.
    setDetection({ ...detection });
  };

  return (
    <div className="space-y-6">
      {/* Заголовок страницы */}
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">Загрузка данных</h1>
          <p className="text-sm text-neutral-600 mt-1 max-w-3xl">
            Проверка, что файл прочитан правильно, и общее представление о структуре данных.
            Содержательный анализ — в последующих модулях.
          </p>
        </div>
        <div className="text-xs text-neutral-500 flex items-center gap-3">
          <span>Шаг 1 из 6</span>
          <span className="text-neutral-300">|</span>
          {isUploaded ? (
            <span className="text-green-600 inline-flex items-center gap-1">
              <Check size={12} aria-hidden="true" /> Файл загружен
            </span>
          ) : (
            <span className="text-neutral-400">Ожидание файла</span>
          )}
        </div>
      </header>

      {/* ════════ Секция 1: Источник данных ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 inline-flex items-center gap-2">
            <Upload size={18} className="text-brand" aria-hidden="true" />
            Источник данных
          </h2>
          {isUploaded && (
            <button
              type="button"
              onClick={() => setIsUploaded(false)}
              className="text-xs text-neutral-500 hover:text-neutral-700 inline-flex items-center gap-1"
            >
              <RefreshCw size={12} aria-hidden="true" /> Сменить файл
            </button>
          )}
        </div>

        {!isUploaded ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  checked={source === "file"}
                  onChange={() => setSource("file")}
                  className="accent-brand"
                />
                Файл .xlsx, .xls, .csv, .json
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  checked={source === "db"}
                  onChange={() => setSource("db")}
                  className="accent-brand"
                />
                База данных (SQL)
              </label>
            </div>

            {source === "file" ? (
              <div className="mt-4 border-2 border-dashed border-neutral-300 rounded-lg p-6 text-center bg-neutral-50">
                <input
                  type="file"
                  id="file-upload-input"
                  className="hidden"
                  onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
                />
                <label
                  htmlFor="file-upload-input"
                  className="cursor-pointer text-sm text-neutral-600 inline-flex flex-col items-center gap-2"
                >
                  <Upload size={24} className="text-neutral-400" aria-hidden="true" />
                  {fileName ? (
                    <span>
                      Выбрао: <strong className="text-neutral-900">{fileName}</strong>
                    </span>
                  ) : (
                    <span>Перетащите файл сюда или нажмите для выбора</span>
                  )}
                </label>
              </div>
            ) : (
              <p className="text-sm text-neutral-500 mb-4 mt-4 bg-neutral-50 rounded p-4">
                (форма подключения к БД — заглушка)
              </p>
            )}

            <Button onClick={handleMockUpload} className="mt-4">
              Загрузить файл
            </Button>
          </>
        ) : (
          <div className="mt-4 border border-neutral-200 rounded-lg p-4 text-sm bg-neutral-50">
            <div className="flex items-center gap-2 text-neutral-700">
              <FileText size={16} className="text-brand" aria-hidden="true" />
              <strong className="text-neutral-900">{fileName}</strong>
              <span className="text-neutral-400">·</span>
              <span>{memoryMb} MB</span>
              <span className="text-neutral-400">·</span>
              <span>загружен успешно</span>
              <span className="text-neutral-400">·</span>
              <span>{formatNum(totalRows)} строк</span>
              <span className="text-neutral-400">·</span>
              <span>{totalCols} колонок</span>
            </div>
          </div>
        )}

        {/* Предупреждения парсинга */}
        {isUploaded && MOCK_PARSE_WARNINGS.length > 0 && (
          <div className="mt-3 space-y-2">
            {MOCK_PARSE_WARNINGS.map((w, i) => (
              <div
                key={i}
                className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 flex items-start gap-2"
              >
                <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  <strong>Предупреждение парсинга:</strong> {w.message}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ════════ Секция 2: Подтверждение автоопределения (новое) ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-neutral-900">Подтверждение автоопределения</h2>
            <p className="text-xs text-neutral-500 mt-0.5 max-w-2xl">
              Эвристики определили структуру датасета. Проверьте и поправьте, если ошиблись —
              это определит весь дальнейший анализ.
            </p>
          </div>
          <span className="text-xs bg-brand-light text-brand px-2 py-1 rounded font-mono hidden md:inline-block">
            PATCH /v1/internal/datasets/{"{id}"}/column-mapping
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Колонка даты */}
          <div className="border border-neutral-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                <Calendar size={12} aria-hidden="true" /> Колонка даты
              </span>
              <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.dateCol.confidence)}`}>
                {detection.dateCol.confidence}%
              </span>
            </div>
            <select
              value={detection.dateCol.selected}
              onChange={(e) =>
                setDetection({
                  ...detection,
                  dateCol: { ...detection.dateCol, selected: e.target.value },
                })
              }
              className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
            >
              {detection.dateCol.candidates.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
              <option value="(не использовать)">(не использовать)</option>
            </select>
            <details className="mt-2 text-xs text-neutral-500">
              <summary className="cursor-pointer inline-flex items-center gap-1">
                <ChevronDown size={10} aria-hidden="true" /> кандидаты ({detection.dateCol.candidates.length})
              </summary>
              <ul className="mt-1 space-y-0.5">
                {detection.dateCol.candidates.map((c) => (
                  <li key={c.name}>
                    • {c.name} — score {c.score.toFixed(2)}
                  </li>
                ))}
              </ul>
            </details>
          </div>

          {/* Группирующая колонка */}
          <div className="border border-neutral-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                <Tag size={12} aria-hidden="true" /> Группирующая колонка
              </span>
              <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.entityCol.confidence)}`}>
                {detection.entityCol.confidence}%
              </span>
            </div>
            <select
              value={detection.entityCol.selected}
              onChange={(e) =>
                setDetection({
                  ...detection,
                  entityCol: { ...detection.entityCol, selected: e.target.value },
                })
              }
              className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
            >
              {detection.entityCol.candidates.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
              <option value="(нет)">(нет)</option>
            </select>
            <details className="mt-2 text-xs text-neutral-500">
              <summary className="cursor-pointer inline-flex items-center gap-1">
                <ChevronDown size={10} aria-hidden="true" /> кандидаты ({detection.entityCol.candidates.length})
              </summary>
              <ul className="mt-1 space-y-0.5">
                {detection.entityCol.candidates.map((c) => (
                  <li key={c.name}>
                    • {c.name} — score {c.score.toFixed(2)}
                  </li>
                ))}
              </ul>
            </details>
          </div>

          {/* Частота */}
          <div className="border border-neutral-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                <Clock size={12} aria-hidden="true" /> Частота ряда
              </span>
              <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.freq.confidence)}`}>
                {detection.freq.confidence}%
              </span>
            </div>
            <select
              value={detection.freq.selected}
              onChange={(e) =>
                setDetection({
                  ...detection,
                  freq: { ...detection.freq, selected: e.target.value },
                })
              }
              className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
            >
              {detection.freq.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
            <p className="mt-2 text-xs text-neutral-500">
              Определено по {formatNum(totalRows)} точкам.{" "}
              <a href="#" className="underline">
                показать первые 5 наблюдений →
              </a>
            </p>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between flex-wrap gap-3">
          <p className="text-xs text-neutral-500 max-w-2xl">
            Override сохраняется серверно (in-memory на этапе прототипа, Redis+TTL в продакшене) —
            переживёт F5 и доступен через API.
          </p>
          <Button onClick={handleApplyOverride}>Применить и пересчитать превью</Button>
        </div>
      </section>

      {/* ════════ Секция 3: Техническая информация ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <details open>
          <summary className="font-semibold text-neutral-900 cursor-pointer flex items-center justify-between">
            <span className="inline-flex items-center gap-2">
              <Database size={18} className="text-brand" aria-hidden="true" />
              Техническая информация о датасете
            </span>
            <span className="text-xs text-neutral-500 font-normal">4 метрики + таблица колонок</span>
          </summary>

          {/* 4 KPI */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
            <div className="border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">Всего строк</div>
              <div className="text-xl font-semibold text-neutral-900">{formatNum(totalRows)}</div>
            </div>
            <div className="border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">Всего колонок</div>
              <div className="text-xl font-semibold text-neutral-900">{totalCols}</div>
            </div>
            <div className="border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">Память</div>
              <div className="text-xl font-semibold text-neutral-900">{memoryMb.toFixed(2)} MB</div>
            </div>
            <div className="border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">Числовых / Текстовых</div>
              <div className="text-xl font-semibold text-neutral-900">
                {numericCount} / {textCount}
              </div>
            </div>
          </div>

          {/* Таблица колонок */}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-xs text-neutral-500 uppercase">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Колонка</th>
                  <th className="text-left px-3 py-2 font-medium">Тип</th>
                  <th className="text-right px-3 py-2 font-medium">Не пусто</th>
                  <th className="text-left px-3 py-2 font-medium">Пропуски</th>
                  <th className="text-right px-3 py-2 font-medium">Уникальных</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {MOCK_COLUMNS.map((col) => (
                  <tr key={col.name}>
                    <td className="px-3 py-2 font-medium">{col.name}</td>
                    <td className="px-3 py-2 text-neutral-600">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${
                            col.typeIcon === "numeric"
                              ? "bg-blue-100 text-blue-700"
                              : col.typeIcon === "datetime"
                              ? "bg-purple-100 text-purple-700"
                              : col.typeIcon === "categorical"
                              ? "bg-green-100 text-green-700"
                              : "bg-neutral-200 text-neutral-600"
                          }`}
                        >
                          {TYPE_ICON[col.typeIcon]}
                        </span>
                        {col.dtype}
                      </span>
                    </td>
                    <td className="text-right px-3 py-2">{formatNum(col.nonNull)}</td>
                    <td className="px-3 py-2">
                      {col.nulls > 0 ? (
                        <div className="flex items-center gap-2">
                          <div className="w-24 bg-neutral-200 rounded-full h-1.5">
                            <div
                              className="bg-amber-500 h-1.5 rounded-full"
                              style={{ width: `${(col.nulls / totalRows) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs text-neutral-600">{formatNum(col.nulls)}</span>
                        </div>
                      ) : (
                        <span className="text-neutral-400">—</span>
                      )}
                    </td>
                    <td className="text-right px-3 py-2">{formatNum(col.unique)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-neutral-500">Датасет загружен: {fileName}</p>
        </details>
      </section>

      {/* ════════ Секция 4: Превью датасета ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <details>
          <summary className="font-semibold text-neutral-900 cursor-pointer flex items-center justify-between">
            <span className="inline-flex items-center gap-2">
              <Eye size={18} className="text-brand" aria-hidden="true" />
              Превью датасета
            </span>
            <span className="text-xs text-neutral-500 font-normal">первые 10 строк</span>
          </summary>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-neutral-50 text-neutral-500 uppercase">
                <tr>
                  <th className="text-left px-2 py-1.5">Order Date</th>
                  <th className="text-left px-2 py-1.5">Country</th>
                  <th className="text-left px-2 py-1.5">Region</th>
                  <th className="text-right px-2 py-1.5">Sales</th>
                  <th className="text-right px-2 py-1.5">Profit</th>
                  <th className="text-left px-2 py-1.5">Category</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {PREVIEW_ROWS.map((row, i) => (
                  <tr key={i}>
                    <td className="px-2 py-1.5">{row.OrderDate}</td>
                    <td className="px-2 py-1.5">{row.Country}</td>
                    <td className="px-2 py-1.5">{row.Region}</td>
                    <td className="text-right px-2 py-1.5">{row.Sales.toFixed(2)}</td>
                    <td className={'text-right px-2 py-1.5 ${row.Profit < 0 ? "text-red-600" : ""}'}>
                      {row.Profit.toFixed(2)}
                    </td>
                    <td className="px-2 py-1.5">{row.Category}</td>
                  </tr>
                ))}
                <tr className="text-neutral-400">
                  <td colSpan={6} className="px-2 py-1.5 text-center">
                    ... ещё 5 строк
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </section>

      {/* ════════ Секция 5: Визуализация распределения (БЕЗ СОКРАЩЕНИЙ) ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <details open>
          <summary className="font-semibold text-neutral-900 cursor-pointer flex items-center justify-between">
            <span className="inline-flex items-center gap-2">
              <BarChart3 size={18} className="text-brand" aria-hidden="true" />
              Визуализация распределения данных
            </span>
            <span className="text-xs text-neutral-500 font-normal hidden md:inline">
              точечный · гистограмма+KDE » KDE-плотность · статистики
            </span>
          </summary>
          <p className="text-sm text-neutral-600 mt-2 max-w-3xl">
            Интерактивный анализ распределения числовых признаков: точечный график, гистограмма, KDE
            и статистические метрики для оценки формы распределения, асимметрии и выбросов.
          </p>

          {/* Селектор колонки */}
          <div className="mt-4 flex items-center gap-3">
            <label className="text-sm text-neutral-700">Выберите числовую колонку:</label>
            <select
              value={selectedDistCol}
              onChange={(e) => setSelectedDistCol(e.target.value)}
              className="border border-neutral-300 rounded px-3 py-1.5 text-sm font-medium"
            >
              {NUMERIC_COLS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {/* 3 колонки графиков */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
            {/* col1: Точечный график */}
            <div>
              <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                <ScatterChart size={14} className="text-neutral-500" aria-hidden="true" />
                Точечный график
              </h4>
              <div className="h-[400px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
                [ Plotly scatter: x=index, y={selectedDistCol}, opacity=0.6, marker_size=6 ]
              </div>
            </div>

            {/* col2: Гистограмма + KDE + vlines */}
            <div>
              <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                <BarChart3 size={14} className="text-neutral-500" aria-hidden="true" />
                Гистограмма
              </h4>
              <div className="h-[400px] border border-neutral-200 rounded flex flex-col items-center justify-center text-xs text-neutral-500 gap-1 bg-neutral-50">
                [ Plotly histogram, nbins=30 ]
                <span className="text-neutral-400">+ KDE (красный) + vlines: Mean / Median / Q1 / Q3</span>
              </div>
            </div>

            {/* col3: KDE-плотность */}
            <div>
              <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                <Activity size={14} className="text-neutral-500" aria-hidden="true" />
                KDE (плотность)
              </h4>
              <div className="h-[400px] border border-neutral-200 rounded flex flex-col items-center justify-center text-xs text-neutral-500 gap-1 bg-neutral-50">
                [ Plotly scatter: KDE curve, fill=tozeroy ]
                <span className="text-neutral-400">+ vlines: Mean / Median</span>
              </div>
            </div>
          </div>

          {/* Статистики распределения */}
          <div className="mt-5 border-t border-neutral-100 pt-4">
            <h4 className="font-semibold text-neutral-900 mb-3">Статистики распределения</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-neutral-600">Тип распределения:</span>
                <span className="font-mono text-xs">{MOCK_DIST_STATS.type}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Mean (среднее):</span>
                <span className="font-mono">{MOCK_DIST_STATS.mean.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Median (медиана):</span>
                <span className="font-mono">{MOCK_DIST_STATS.median.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Std (отклонение):</span>
                <span className="font-mono">{MOCK_DIST_STATS.std.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Skewness (асимметрия):</span>
                <span className="font-mono">{MOCK_DIST_STATS.skew.toFixed(3)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Kurtosis (эксцесс):</span>
                <span className="font-mono">{MOCK_DIST_STATS.kurt.toFixed(3)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Q1 (25-й перцентиль):</span>
                <span className="font-mono">{MOCK_DIST_STATS.q1.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Q3 (75-й перцентиль):</span>
                <span className="font-mono">{MOCK_DIST_STATS.q3.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">IQR (межквартильный):</span>
                <span className="font-mono">{MOCK_DIST_STATS.iqr.toFixed(2)}</span>
              </div>
            </div>
          </div>

          {/* Справка по методу */}
          <details className="mt-4">
            <summary className="text-sm text-brand cursor-pointer inline-flex items-center gap-1">
              <Info size={14} aria-hidden="true" /> Справка по описательным статистикам
            </summary>
            <div className="mt-2 text-xs text-neutral-600 bg-neutral-50 rounded p-3 space-y-2">
              <p>
                <strong>Назначение:</strong> Визуальная и статистическая оценка распределения данных.
              </p>
              <p>
                <strong>Методы:</strong> точечный график » гистограмма · KDE (гауссовская оценка плотности)
              </p>
              <p>
                <strong>Интерпретация:</strong> Skewness → 0 = симметрия. Kurtosis → 3 = нормальность.
                IQR — устойчивая мера разброса.
              </p>
            </div>
          </details>
        </details>
      </section>

      {/* ════════ Секция 6: Контекст активных фильтров ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <details>
          <summary className="font-semibold text-neutral-900 cursor-pointer flex items-center justify-between">
            <span className="inline-flex items-center gap-2">
              <Filter size={18} className="text-brand" aria-hidden="true" />
              Контекст активных фильтров
            </span>
            <span className="text-xs text-neutral-500 font-normal hidden md:inline">
              лёгкая строка, без построителя графиков
            </span>
          </summary>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-neutral-500 uppercase">Категория 1</label>
              <select className="w-full mt-1 border border-neutral-300 rounded px-2 py-1.5 text-sm">
                <option>Country</option>
                <option>(нет)</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-neutral-500 uppercase">Категория 2</label>
              <select className="w-full mt-1 border border-neutral-300 rounded px-2 py-1.5 text-sm">
                <option>Region</option>
                <option>(нет)</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-neutral-500 uppercase">Года</label>
              <select className="w-full mt-1 border border-neutral-300 rounded px-2 py-1.5 text-sm">
                <option>Все</option>
                <option>2023</option>
                <option>2024</option>
              </select>
            </div>
          </div>
          <p className="mt-3 text-sm text-neutral-600 bg-brand-light rounded px-3 py-2">
            Активно: <strong>{formatNum(totalRows)}</strong> записей · 1 значение (кат.1) · 1 значение
            (кат.2) · Все года
          </p>
          <p className="mt-2 text-xs text-neutral-500">
            Построитель 8 типов графиков (Bar/Line/Area/Scatter/Box/Hist/Hist+KDE/Funnel) и
            переключатель режима «Временные ряды vs Общий» перенесены о модуль{" "}
            <Link href="/eda" className="text-brand underline">
              Разведочный EDA
            </Link>{" "}
            — это содержательный анализ, не проверка загрузки.
          </p>
        </details>
      </section>

      {/* ════════ Секция 7: Предварительная оценка качества (teaser) ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-neutral-900">Предварительная оценка качества</h2>
            <p className="text-xs text-neutral-500 mt-0.5">
              Только счётчики. Содержательный анализ проблем — о модуле «Валидация».
            </p>
          </div>
          <span className="text-xs bg-neutral-100 text-neutral-600 px-2 py-1 rounded font-mono hidden md:inline-block">
            POST /v1/internal/quality-teaser » &lt; 1s
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
            <div className="text-xs text-amber-700 uppercase">Колонок с пропусками</div>
            <div className="text-2xl font-semibold text-amber-900 mt-1">{MOCK_QUALITY.colsWithMissing}</div>
            <div className="text-xs text-amber-700 mt-1">{MOCK_QUALITY.missingCols.join(", ")}</div>
          </div>
          <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
            <div className="text-xs text-amber-700 uppercase">Колонок с потенц. выбросами</div>
            <div className="text-28l font-semibold text-amber-900 mt-1">{MOCK_QUALITY.colsWithOutliers}</div>
            <div className="text-xs text-amber-700 mt-1">{MOCK_QUALITY.outlierCols.join(", ")}</div>
          </div>
          <div className="border border-neutral-200 rounded-lg p-4">
            <div className="text-xs text-neutral-500 uppercase">Всего строк</div>
            <div className="text-2xl font-semibold text-neutral-900 mt-1">
              {formatNum(MOCK_QUALITY.rowsTotal)}
            </div>
          </div>
          <div className="border border-neutral-200 rounded-lg p-4">
            <div className="text-xs text-neutral-500 uppercase">Дубликатов</div>
            <div className="text-2xl font-semibold text-green-700 mt-1">{MOCK_QUALITY.duplicates}</div>
          </div>
        </div>

        <Link
          href="/validation"
          className="mt-4 inline-flex items-center gap-2 bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand-dark transition-colors"
        >
          Перейти к Валидации <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </section>

      {/* ════════ Секция 8: Памятка ════════ */}
      <section className="bg-brand-light rounded-lg p-5 border border-brand/20">
        <h2 className="font-semibold text-brand mb-3 inline-flex items-center gap-2">
          <Info size={18} aria-hidden="true" />
          Что считается о следующих модулях
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-neutral-700">
          <div className="bg-white rounded p-3">
            <div className="font-medium inline-flex items-center gap-1.5">
              <TableIcon size={14} className="text-brand" aria-hidden="true" />
              Разведочный EDA
            </div>
            <ul className="text-xs text-neutral-600 mt-1 space-y-0.5 list-disc list-inside">
              <li>Корреляция Пирсона + heatmap</li>
              <li>STL-декомпозиция (после предобработки)</li>
              <li>ACF / PACF</li>
              <li>FFT, Периодограмма, Вейвлет</li>
              <li>Построитель 8 типов графиков</li>
            </ul>
          </div>
          <div className="bg-white rounded p-3">
            <div className="font-medium inline-flex items-center gap-1.5">
              <TableIcon size={14} className="text-brand" aria-hidden="true" />
              Моделирование
            </div>
            <ul className="text-xs text-neutral-600 mt-1 space-y-0.5 list-disc list-inside">
              <li>Полный паспорт (13 свойств: ADF/KPSS/Hurst/сезонность/спектр)</li>
              <li>Предварительные рекомендации по моделям</li>
              <li>KS-тест с фиттингом 3 распределений</li>
              <li>Excel-отчёт</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
