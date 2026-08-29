"use client";

// packages/ui/components/NavigatorQualityTeaserPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» остановки
// «Teaser качества» (id="quality_teaser") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор (Task 2026-08-30).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     подсчёта 4 счётчиков качества + 2 списков колонок.
//   • Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       - apps/api/upload_common.py::_compute_quality_teaser
//       - apps/api/schemas.py::QualityTeaserOut
//       - apps/api/upload_common.py::handle_upload (отдаёт в UploadResponse.quality)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (это и есть требование тимлида).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//   Аналитик видит 4 «дорожки»-счётчика:
//
//     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
//     │ Пропуски     │ │ Выбросы      │ │ Всего строк  │ │ Дубликаты   │
//     │ df[c].isna() │ │ Q1,Q3,IQR    │ │ len(df)      │ │ df.duplic.  │
//     │  .any()      │ │ 1.5×IQR      │ │              │ │  .sum()     │
//     └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
//            └────────────┬──┴─────────────┬───┴──────────────┘
//                         ▼                ▼
//                   ┌──────────────────────────────────┐
//                   │ QualityTeaserOut                 │
//                   │ (внутри UploadResponse.quality)  │
//                   └──────────────┬───────────────────┘
//                                  ▼
//                   статус: warning если любой из 3 > 0
//                   (rows_total в статусе не участвует)
//                                  ▼
//                   «Только счётчики — разбор в Валидации»
//
//   Так аналитик мгновенно понимает:
//     1) что именно бэкенд считает при загрузке (4 метрики);
//     2) по каким методам (isna/IQR/len/duplicated);
//     3) что это только teaser — полный разбор в модуле «Валидация».
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — NavigatorStructureConfirmPreview (Task 65):
//     статичная Tailwind/CSS-блок-схема, role="img" + aria-label.
//   • Не использует recharts (нет данных для графика) — чистая
//     разметка с lucide-react иконками и border'ами.
//   • 4 счётчика расположены в сетке 4 колонки (grid-cols-4) —
//     повторяет layout Metric-карточек в самой вкладке «Загрузка»
//     (TsAnalysisUpload.tsx:1312 — grid-cols-2 md:grid-cols-4).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с описанием всех 4 счётчиков —
//     скринридер читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текстовую
//     информацию, единый паттерн с NavigatorStructureConfirmPreview).

import {
  AlertCircle,
  TrendingUp,
  Layers,
  Copy,
  ChevronDown,
  AlertTriangle,
  Info,
  type LucideIcon,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────

interface CounterLane {
  /** Идентификатор счётчика (стабилен — на нём строятся тесты). */
  id: string;
  /** Человекочитаемый лейбл (совпадает с Metric label в TsAnalysisUpload.tsx). */
  label: string;
  /** Бэкенд-источник: код вычисления. */
  source: string;
  /** Иконка. */
  icon: LucideIcon;
  /** Краткое описание метода. */
  method: string;
  /** Входит ли счётчик в warning-логику (3 из 4 — rows_total не входит). */
  affectsStatus: boolean;
}

// ── 4 счётчика ──────────────────────────────────────────────────────
//
// Источник истины — apps/api/upload_common.py::_compute_quality_teaser.
// Порядок: missing → outliers → rows_total → duplicates, как в
// TsAnalysisUpload.tsx:1313-1316 (grid Metric-карточек).

const COUNTER_LANES: CounterLane[] = [
  {
    id: "cols_with_missing",
    label: "Колонок с пропусками",
    source: "df[c].isna().any()",
    icon: AlertCircle,
    method: "Любая колонка, где есть хотя бы один NaN",
    affectsStatus: true,
  },
  {
    id: "cols_with_outliers",
    label: "Колонок с выбросами",
    source: "Q1, Q3, IQR · 1.5×IQR",
    icon: TrendingUp,
    method: "Только numeric, ≥4 значений, IQR > 0; вне [Q1−1.5·IQR, Q3+1.5·IQR]",
    affectsStatus: true,
  },
  {
    id: "rows_total",
    label: "Всего строк",
    source: "len(df)",
    icon: Layers,
    method: "Размер датафрейма после загрузки",
    affectsStatus: false,
  },
  {
    id: "duplicates",
    label: "Дубликатов",
    source: "df.duplicated().sum()",
    icon: Copy,
    method: "Полностью совпадающие строки",
    affectsStatus: true,
  },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorQualityTeaserPreview() {
  // Описание для скринридера — перечисляем все 4 счётчика одной строкой,
  // чтобы пользователь с AT получил полное представление об алгоритме
  // без перехода по каждой ноде.
  const ariaLabel =
    "Блок-схема подсчёта счётчиков качества: " +
    COUNTER_LANES.map((c) => `${c.label} (${c.source})`).join(", ") +
    " → QualityTeaserOut внутри UploadResponse.quality → статус warning если любой из 3 счётчиков > 0";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + бэкенд-источник */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Teaser качества
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          _compute_quality_teaser
        </code>
      </div>

      {/* 4 параллельные дорожки счётчиков (grid-cols-4 — как в вкладке Загрузка) */}
      <div className="grid grid-cols-4 gap-1.5 mb-2">
        {COUNTER_LANES.map((lane) => {
          const Icon = lane.icon;
          return (
            <div
              key={lane.id}
              className="rounded-md border border-brand/30 bg-white px-1.5 py-2 flex flex-col gap-1 min-w-0"
            >
              {/* Иконка + лейбл */}
              <div className="flex items-center gap-1">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
                  aria-hidden="true"
                >
                  <Icon size={12} />
                </span>
                <span className="text-[10px] font-semibold text-neutral-900 leading-tight">
                  {lane.label}
                </span>
              </div>
              {/* Бэкенд-источник */}
              <code className="text-[8.5px] text-neutral-400 font-mono leading-tight break-all">
                {lane.source}
              </code>
              {/* Метод */}
              <p className="text-[9px] text-neutral-600 leading-snug mt-0.5">
                {lane.method}
              </p>
              {/* Бейдж участия в warning-логике */}
              {lane.affectsStatus && (
                <span className="inline-flex items-center rounded bg-amber-50 border border-amber-200 px-1 py-0.5 text-[8px] text-amber-700 uppercase tracking-wide w-fit">
                  влияет на статус
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Стрелка вниз — объединение результатов 4 счётчиков */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: QualityTeaserOut (внутри UploadResponse.quality) */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Info size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            QualityTeaserOut
          </span>
          <span className="text-[9px] text-neutral-400 font-mono">
            ← внутри UploadResponse.quality
          </span>
        </div>
        <div className="grid grid-cols-4 gap-1.5">
          {COUNTER_LANES.map((lane) => (
            <div key={lane.id} className="text-[9px] text-neutral-600 leading-snug">
              <span className="font-mono text-neutral-400">{lane.id}</span>
              <br />
              <span className="text-neutral-700">: int</span>
            </div>
          ))}
        </div>
        <div className="mt-1 text-[9px] text-neutral-500 leading-snug">
          + 2 списка колонок: <span className="font-mono">missing_cols[]</span>,{" "}
          <span className="font-mono">outlier_cols[]</span>
        </div>
      </div>

      {/* Стрелка вниз → статус */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Финальный блок: warning-логика + redirect на Валидацию */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 flex items-center gap-1.5">
          <AlertTriangle size={12} className="text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-amber-800 leading-tight">
            warning если любой из 3 &gt; 0 (rows_total не учитывается)
          </span>
        </div>
        <div className="rounded-md border border-neutral-200 bg-neutral-50 px-2 py-1.5 flex items-center gap-1.5">
          <Info size={12} className="text-neutral-500 shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-neutral-700 leading-tight">
            только счётчики → разбор в «Валидации»
          </span>
        </div>
      </div>

      {/* Подпись: краткое пояснение алгоритма */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        4 счётчика считаются <span className="font-mono">сразу при загрузке</span>,
        внутри ответа <span className="font-mono">/upload</span> (отдельного эндпоинта
        нет). Это анонс проблем — содержательный разбор по 10 критериям живёт в
        модуле «Валидация».
      </p>
    </div>
  );
}
