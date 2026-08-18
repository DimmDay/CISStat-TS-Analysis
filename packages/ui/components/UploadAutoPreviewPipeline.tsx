// packages/ui/components/UploadAutoPreviewPipeline.tsx
//
// Статичная информационная блок-схема «Пайплайн автопревью» для окна
// «Обзор» Навигатора (см. TsAnalysisNavigator.tsx). Рендерится ТОЛЬКО при
// активной остановке «Загрузка» + пункте «Автопревью и типы колонок»
// (id="upload" + id="preview") — для остальных пунктов оставлена
// стандартная текстовая заглушка (по решению тимлида, Task 22).
//
// Что показывает: последовательность шагов, которые платформа выполняет
// сразу после загрузки файла. Шаги взяты из реального бэкенда:
//   - apps/api/upload_common.py: handle_upload / _compute_column_info /
//     _compute_quality_teaser / _compute_parse_warnings
//   - app/data/file_loader.py: read_uploaded_file (pd.read_csv с
//     engine='python', encoding='utf-8-sig', sep=None)
//   - app/classification/classifier.py: classify_columns
//   - apps/api/session_store.py: DatasetInfo / session.set_dataset
//
// ── Компоновка «змейка» (Task 22 — Phase 2) ──────────────────────
//
// Первая итерация была вертикальным списком из 9 строк — высота ~720px,
// что ломает философию минимального скролла платформы. Переделано в
// змейку 5 строк × 2 ноды (последняя — 1 нода):
//
//   Строка 1 (LTR):  [Файл] > [Детект кодировки]
//                                                ↓
//   Строка 2 (RTL):  [Детект типов] < [Парсинг]
//   ↓
//   Строка 3 (LTR):  [classify_columns + 4 чипа] > [Подсчёт пропусков]
//                                                                     ↓
//   Строка 4 (RTL):  [Подсчёт уникальных] < [Предупреждения парсинга]
//   ↓
//   Строка 5 (LTR):  [Готово → SessionStore]
//
// Чётные строки (1, 3) идут слева-направо (LTR), нечётные (2, 4) —
// справа-налево (RTL). Зритель читает змейкой: вниз-влево-вниз-вправо-...
// Между нодами в строке — ChevronRight (LTR) или ChevronLeft (RTL).
// Между строками — ChevronDown с той стороны, где закончилась строка.
//
// Архитектурно — ближайший родственник StructuralClassSchema.tsx (статичная
// информационная схема), но с горизонтально-вертикальной змейкой вместо
// дерева решений.
//
// a11y-контракт:
//   - Корень имеет role="img" + aria-label — скринридер читает весь
//     пайплайн как одно изображение с описанием последовательности.
//   - Внутренние иконки/стрелки — aria-hidden="true", т.к. дублируют
//     текстовую информацию (названия шагов).
//   - ChevronDown между строками имеет aria-label="chevron down" (как в
//     NavigatorHero.tsx — единый паттерн для всех chevron-иконок в проекте).

import { Fragment } from "react";
import {
  FileUp,
  Binary,
  Braces,
  Type,
  Boxes,
  CircleDot,
  Hash,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  type LucideIcon,
} from "lucide-react";

// ── Типы ──────────────────────────────────────────────────────

export interface PipelineStep {
  /** Идентификатор шага (стабилен — на нём строятся тесты). */
  id: string;
  /** Короткий заголовок шага (виден в ноде). */
  title: string;
  /** Техническая деталь (что реально делает бэкенд). */
  subtitle?: string;
  /** Иконка из lucide-react. */
  icon: LucideIcon;
}

// ── 9 шагов пайплайна ─────────────────────────────────────────
//
// Порядок повторяет реальную последовательность в handle_upload (бэкенд):
//   1. Файл → 2. Детект кодировки/разделителя → 3. Парсинг →
//   4. Детект типов → 5. classify_columns (с 4 подтипами) →
//   6. Подсчёт пропусков → 7. Подсчёт уникальных →
//   8. Предупреждения парсинга → 9. Готово → SessionStore

export const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: "file",
    title: "Файл",
    subtitle: ".csv / .xlsx / .xls / .json",
    icon: FileUp,
  },
  {
    id: "detect_encoding",
    title: "Детект кодировки/разделителя",
    subtitle: "engine='python', utf-8-sig, sep=None",
    icon: Binary,
  },
  {
    id: "parsing",
    title: "Парсинг",
    subtitle: "read_csv / read_excel / json",
    icon: Braces,
  },
  {
    id: "detect_types",
    title: "Детект типов",
    subtitle: "datetime64 / numeric / object",
    icon: Type,
  },
  {
    id: "classify_columns",
    title: "classify_columns",
    subtitle: "4 типа колонок",
    icon: Boxes,
  },
  {
    id: "count_missing",
    title: "Подсчёт пропусков",
    subtitle: "cols_with_missing, nulls",
    icon: CircleDot,
  },
  {
    id: "count_unique",
    title: "Подсчёт уникальных",
    subtitle: "nunique per column",
    icon: Hash,
  },
  {
    id: "parse_warnings",
    title: "Предупреждения парсинга",
    subtitle: "Unnamed: N, U+FFFD «�»",
    icon: AlertTriangle,
  },
  {
    id: "done",
    title: "Готово → SessionStore",
    subtitle: "DataFrame + DatasetInfo сохранены",
    icon: CheckCircle2,
  },
];

// ── 4 подтипа classify_columns ───────────────────────────────
//
// Зеркало app/classification/classifier.py: numeric = number, date =
// datetime64, cat = object/string с 1 < nunique < 100, text — fallback
// для object/string вне диапазона cat.

interface ClassifySubtype {
  id: string;
  label: string;
}

const CLASSIFY_SUBTYPES: ClassifySubtype[] = [
  { id: "numeric", label: "numeric" },
  { id: "categorical", label: "categorical" },
  { id: "datetime", label: "datetime" },
  { id: "text", label: "text" },
];

// ── Компоновка «змейка»: 5 строк ──────────────────────────────
//
// rows[] — массив строк. Каждая строка — массив из 1 или 2 шагов.
// Чётные индексы (0, 2, 4) — LTR, нечётные (1, 3) — RTL.
// При рендере RTL-строки мы НЕ переставляем шаги местами в данных
// (порядок остаётся [3, 4], [7, 8] по PIPELINE_STEPS), а только
// инвертируем направление потока через flex-row-reverse — визуально
// [4] < [3], что и есть змейка.

const ROW_INDICES: number[][] = [
  [0, 1], // Строка 1 (LTR): Файл, Детект кодировки
  [2, 3], // Строка 2 (RTL): Парсинг, Детект типов (визуально [Детект типов] < [Парсинг])
  [4, 5], // Строка 3 (LTR): classify_columns, Подсчёт пропусков
  [6, 7], // Строка 4 (RTL): Подсчёт уникальных, Предупреждения парсинга
  [8],    // Строка 5 (LTR): Готово
];

// ── Вспомогательный: одна компактная нода ─────────────────────
//
// Минимальная высота — иконка 16px + title 12px + subtitle 10px = ~44px
// с padding. Это позволяет уложить 5 строк + 4 стрелки вниз в ~280-300px.

function PipelineNode({ step }: { step: PipelineStep }) {
  const Icon = step.icon;
  return (
    <div className="flex items-center gap-2 rounded-md border border-brand/30 bg-white px-2.5 py-1.5 min-w-0 flex-1">
      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
        aria-hidden="true"
      >
        <Icon size={14} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold text-neutral-900 leading-tight truncate">
          {step.title}
        </div>
        {step.subtitle && (
          <div className="text-[10px] text-neutral-500 leading-tight truncate font-mono">
            {step.subtitle}
          </div>
        )}
        {/* 4 подтипа внутри classify_columns — компактные чипы в 1 ряд */}
        {step.id === "classify_columns" && (
          <div className="flex flex-wrap gap-1 mt-1">
            {CLASSIFY_SUBTYPES.map((sub) => (
              <span
                key={sub.id}
                className="inline-flex items-center rounded bg-neutral-100 px-1.5 py-0.5 text-[9px] font-semibold text-neutral-600"
              >
                {sub.label}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Основной компонент ───────────────────────────────────────

export function UploadAutoPreviewPipeline() {
  // Описание для скринридера: перечисляем все шаги одной строкой,
  // чтобы пользователь с AT получил полное представление о пайплайне,
  // не переходя по каждой ноде.
  const ariaLabel = `Пайплайн автопревью: ${PIPELINE_STEPS.map((s) => s.title).join(
    " → ",
  )}`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      <div className="flex flex-col gap-1">
        {ROW_INDICES.map((rowIndices, rowIdx) => {
          const isRTL = rowIdx % 2 === 1; // нечётные строки — справа налево
          const isLast = rowIdx === ROW_INDICES.length - 1;
          const stepsInRow = rowIndices.map((i) => PIPELINE_STEPS[i]);

          return (
            <Fragment key={rowIdx}>
              {/* Строка нод: LTR или RTL через flex-row-reverse.
                  В RTL-строке шаги в данных идут [a, b] (по PIPELINE_STEPS),
                  но визуально [b] < [a] — змейка. */}
              <div
                className={`flex items-stretch gap-1.5 ${
                  isRTL ? "flex-row-reverse" : ""
                }`}
              >
                {stepsInRow.map((step, i) => (
                  <Fragment key={step.id}>
                    <PipelineNode step={step} />
                    {/* Стрелка между нодами в строке (не после последней) */}
                    {i < stepsInRow.length - 1 && (
                      <ChevronSeparator
                        direction={isRTL ? "left" : "right"}
                      />
                    )}
                  </Fragment>
                ))}
              </div>
              {/* Стрелка вниз между строками — с той стороны, где
                  закончилась предыдущая строка:
                    - LTR-строка закончилась справа → ↓ справа
                    - RTL-строка закончилась слева → ↓ слева
                  Последняя строка — без ↓. */}
              {!isLast && (
                <div
                  className={`flex ${
                    isRTL ? "justify-start pl-3" : "justify-end pr-3"
                  }`}
                  aria-hidden="true"
                >
                  <ChevronDown
                    size={16}
                    className="text-neutral-400"
                    aria-label="chevron down"
                    role="img"
                  />
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ── Вспомогательный: горизонтальная стрелка между нодами ─────

function ChevronSeparator({ direction }: { direction: "left" | "right" }) {
  const Icon = direction === "left" ? ChevronLeft : ChevronRight;
  return (
    <div
      className="flex shrink-0 items-center justify-center"
      aria-hidden="true"
    >
      <Icon size={14} className="text-neutral-400" />
    </div>
  );
}
