"use client";

// packages/ui/components/NavigatorStructureConfirmPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» остановки
// «Подтверждение автоопределения» (id="structure_confirm") секции
// «Этапы модуля» остановки «Загрузка» на странице Навигатор
// (Task 2026-08-30).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     автоопределения структуры (3 параллельных детектора).
//   • Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       - apps/api/routers/session.py::get_structure_detection
//       - app/data/detectors.py::score_all_columns_as_date
//       - app/data/detectors.py::score_all_columns_as_entity_group
//       - app/data/detectors.py::detect_column_frequency
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (это и есть требование тимлида).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//   Аналитик видит 3 параллельных «дорожки» детекторов:
//
//     ┌─────────────┐   ┌───────────────┐   ┌──────────────────┐
//     │ date_col    │   │ entity_col    │   │ frequency        │
//     │ (временная) │   │ (группирующая)│   │ (частота ряда)   │
//     └──────┬──────┘   └───────┬───────┘   └────────┬─────────┘
//            │ keyword          │ dtype               │ pd.infer_freq
//            │ regex            │ nunique             │ на уникальных
//            │ year-range       │ 1 < n < 100         │ отсортированных
//            ▼                  ▼                     ▼
//     ┌─────────────────────────────────────────────────────────┐
//     │ StructureDetectionResponse                              │
//     │ GET /dataset/structure-detection                       │
//     │ date_col.selected / entity_col.selected / frequency    │
//     └─────────────────────────────────────────────────────────┘
//            │
//            ▼  можно поправить (ручное переопределение)
//     ┌─────────────────────────────────────────────┐
//     │ Подтверждённая структура → SessionStore     │
//     └─────────────────────────────────────────────┘
//
//   Так аналитик мгновенно понимает:
//     1) что именно бэкенд автоопределяет (3 аспекта);
//     2) по каким критериям (ключевые слова / regex / dtype / infer_freq);
//     3) что результат можно поправить вручную.
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — UploadAutoPreviewPipeline (статичная
//     Tailwind/CSS-блок-схема, role="img" + aria-label, без состояния).
//   • Не использует recharts (нет данных для графика) — чистая
//     разметка с lucide-react иконками и border'ами.
//   • Высота h-[280px] — визуально соответствует другим Overview-
//     компонентам (бывшая заглушка, NavigatorChartPreview), чтобы
//     не менять компоновку окна «Обзор» Навигатора.
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с описанием всех 3 детекторов —
//     скринридер читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текстовую
//     информацию, единый паттерн с UploadAutoPreviewPipeline).

import { Fragment } from "react";
import {
  Calendar,
  Users,
  Gauge,
  ChevronDown,
  ArrowRight,
  PencilLine,
  CheckCircle2,
  Database,
  type LucideIcon,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────

interface DetectorLane {
  /** Идентификатор детектора (стабилен — на нём строятся тесты). */
  id: string;
  /** Заголовок дорожки. */
  title: string;
  /** Бэкенд-источник (модуль + функция). */
  source: string;
  /** Иконка. */
  icon: LucideIcon;
  /** Критерии — короткие строки-критерии детекции. */
  criteria: string[];
}

// ── 3 детектора ─────────────────────────────────────────────────────
//
// Источник истины — apps/api/routers/session.py::get_structure_detection
// (вызывает 3 функции из app/data/detectors.py). Порядок: date → entity
// → frequency, т.к. frequency зависит от выбранной date-колонки.

const DETECTOR_LANES: DetectorLane[] = [
  {
    id: "date_col",
    title: "Временная колонка",
    source: "score_all_columns_as_date",
    icon: Calendar,
    criteria: [
      "Ключевые слова: date, год, период… (рус/англ)",
      "Regex-паттерны: ISO, DD.MM.YYYY, unix_s/ms",
      "Год 1800–2100 (year_only)",
      "Приоритет: первая колонка файла",
    ],
  },
  {
    id: "entity_col",
    title: "Группирующая колонка",
    source: "score_all_columns_as_entity_group",
    icon: Users,
    criteria: [
      "Dtype: object / string / category",
      "1 < nunique < 100",
      "Исключается уже выбранная date-колонка",
      "Скоринг бинарный (1.0 / 0.0)",
    ],
  },
  {
    id: "frequency",
    title: "Частота ряда",
    source: "detect_column_frequency",
    icon: Gauge,
    criteria: [
      "pd.infer_freq на уникальных датах",
      "3+ уникальных дат (иначе «не определена»)",
      "Сортировка по возрастанию",
      "Код: D / W / M / Q / Y / H…",
    ],
  },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorStructureConfirmPreview() {
  // Описание для скринридера — перечисляем все 3 детектора одной строкой,
  // чтобы пользователь с AT получил полное представление об алгоритме
  // без перехода по каждой ноде.
  const ariaLabel =
    "Блок-схема автоопределения структуры: " +
    DETECTOR_LANES.map((d) => `${d.title} (${d.source})`).join(", ") +
    " → ответ GET /dataset/structure-detection → можно поправить вручную";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + бэкенд-эндпоинт */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Подтверждение автоопределения
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          GET /dataset/structure-detection
        </code>
      </div>

      {/* 3 параллельные дорожки детекторов */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        {DETECTOR_LANES.map((lane) => {
          const Icon = lane.icon;
          return (
            <div
              key={lane.id}
              className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0"
            >
              {/* Заголовок дорожки */}
              <div className="flex items-center gap-1.5">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
                  aria-hidden="true"
                >
                  <Icon size={12} />
                </span>
                <span className="text-[11px] font-semibold text-neutral-900 leading-tight truncate">
                  {lane.title}
                </span>
              </div>
              {/* Бэкенд-источник */}
              <code className="text-[9px] text-neutral-400 font-mono leading-tight truncate">
                {lane.source}
              </code>
              {/* Критерии — компактный список */}
              <ul className="flex flex-col gap-0.5 mt-0.5">
                {lane.criteria.map((c, i) => (
                  <li
                    key={i}
                    className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100"
                  >
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      {/* Стрелка вниз — объединение результатов 3 детекторов */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: StructureDetectionResponse */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Database size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            StructureDetectionResponse
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="text-[9.5px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-400">date_col</span>
            <br />
            <span className="text-neutral-700">.selected / .confidence</span>
          </div>
          <div className="text-[9.5px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-400">entity_col</span>
            <br />
            <span className="text-neutral-700">.selected / .confidence</span>
          </div>
          <div className="text-[9.5px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-400">frequency</span>
            <br />
            <span className="text-neutral-700">.code / .selected</span>
          </div>
        </div>
      </div>

      {/* Стрелка вниз → ручное переопределение */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Финальный блок: можно поправить → SessionStore */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 flex items-center gap-1.5">
          <PencilLine size={12} className="text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-[10px] text-amber-800 leading-tight">
            можно поправить вручную
          </span>
        </div>
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-center gap-1.5">
          <CheckCircle2 size={12} className="text-emerald-600 shrink-0" aria-hidden="true" />
          <span className="text-[10px] text-emerald-800 leading-tight">
            подтверждено → SessionStore
          </span>
        </div>
      </div>

      {/* Подпись: краткое пояснение алгоритма */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        3 параллельных детектора оценивают ВСЕ колонки датасета по
        контенту (не по позиции в файле). Лучшая дата → частота по ней.
        Результат можно переопределить вручную — структура сохраняется в
        сессии и используется всеми последующими вкладками.
      </p>
    </div>
  );
}
