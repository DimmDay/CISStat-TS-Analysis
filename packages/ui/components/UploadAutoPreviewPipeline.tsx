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
// Архитектурно — ближайший родственник StructuralClassSchema.tsx (статичная
// информационная схема с подсветкой активного варианта), но вместо дерева
// решений — последовательность шагов с ветвлением на classify_columns.
// Паттерн «чистый презентационный компонент + типизированный массив шагов»
// тот же.
//
// a11y-контракт:
//   - Корень имеет role="img" + aria-label — скринридер читает весь
//     пайплайн как одно изображение с описанием последовательности.
//   - Внутренние иконки/стрелки — aria-hidden="true", т.к. дублируют
//     текстовую информацию (названия шагов).
//   - ChevronDown между шагами имеет aria-label="chevron down" (как в
//     NavigatorHero.tsx — единый паттерн для всех chevron-иконок в проекте).

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
  ArrowRight,
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
  /** Доп. подпись к иконке/ноде — для первой ноды (форматы). */
  badge?: string;
}

// ── 9 шагов пайплайна ─────────────────────────────────────────
//
// Порядок повторяет реальную последовательность в handle_upload (бэкенд):
//   1. Файл → 2. Детект кодировки/разделителя → 3. Парсинг →
//   4. Детект типов → 5. classify_columns (с 4 подтипами) →
//   6. Подсчёт пропусков → 7. Подсчёт уникальных →
//   8. Предупреждения парсинга → 9. Готово → SessionStore
//
// 7 основных (как в примере тимлида) + 2 уточняющих (parse_warnings и
// done), без которых схема была бы неполной относительно бэкенда.

export const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: "file",
    title: "Файл",
    subtitle: ".csv / .xlsx / .xls / .json — drag-and-drop, до 50MB",
    icon: FileUp,
    badge: "UploadFile",
  },
  {
    id: "detect_encoding",
    title: "Детект кодировки/разделителя",
    subtitle: "engine='python', encoding='utf-8-sig', sep=None (auto)",
    icon: Binary,
  },
  {
    id: "parsing",
    title: "Парсинг",
    subtitle: "pd.read_csv / read_excel / json_normalize / parse_jsonstat",
    icon: Braces,
  },
  {
    id: "detect_types",
    title: "Детект типов",
    subtitle: "datetime64 / numeric / object / string",
    icon: Type,
  },
  {
    id: "classify_columns",
    title: "classify_columns",
    subtitle: "классификация колонок по 4 типам",
    icon: Boxes,
  },
  {
    id: "count_missing",
    title: "Подсчёт пропусков",
    subtitle: "cols_with_missing, nulls per column",
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
    subtitle: "Unnamed: N (сдвиг header), U+FFFD «�» (неверная кодировка)",
    icon: AlertTriangle,
  },
  {
    id: "done",
    title: "Готово → SessionStore",
    subtitle: "DataFrame + DatasetInfo сохранены в сессии",
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
  hint: string;
}

const CLASSIFY_SUBTYPES: ClassifySubtype[] = [
  { id: "numeric", label: "numeric", hint: "select_dtypes(include='number')" },
  { id: "categorical", label: "categorical", hint: "object, 1 < nunique < 100" },
  { id: "datetime", label: "datetime", hint: "datetime64[ns]" },
  { id: "text", label: "text", hint: "object/string, fallback" },
];

// ── Вспомогательный: одна нода пайплайна ───────────────────────

function PipelineNode({ step }: { step: PipelineStep }) {
  const Icon = step.icon;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-brand/30 bg-white px-4 py-3 shadow-sm">
      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-brand-light text-brand"
        aria-hidden="true"
      >
        <Icon size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-neutral-900 leading-tight">
          {step.title}
        </div>
        {step.subtitle && (
          <div className="text-[11px] text-neutral-500 mt-0.5 leading-tight break-words">
            {step.subtitle}
          </div>
        )}
      </div>
      {step.badge && (
        <span
          className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-mono text-neutral-500"
          aria-hidden="true"
        >
          {step.badge}
        </span>
      )}
    </div>
  );
}

// ── Вспомогательный: вертикальная стрелка ────────────────────

function ChevronSeparator() {
  return (
    <div className="flex justify-center py-1" aria-hidden="true">
      <ChevronDown
        size={18}
        className="text-neutral-400"
        aria-label="chevron down"
        role="img"
      />
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

  // Первый шаг (Файл) и последний (Готово) — с акцентом: FileUp зелёный,
  // CheckCircle2 тоже зелёный, но с зелёной рамкой. Средние шаги — нейтральные.
  // Делаем это через условные классы на обёртке PipelineNode.
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-4 min-h-[280px]"
    >
      <div className="flex flex-col gap-0">
        {PIPELINE_STEPS.map((step, idx) => {
          const isLast = idx === PIPELINE_STEPS.length - 1;
          const isFirst = idx === 0;
          return (
            <div key={step.id}>
              <PipelineNode step={step} />

              {/* Развёртка 4 подтипов после classify_columns */}
              {step.id === "classify_columns" && (
                <div className="mt-2 ml-6 border-l-2 border-dashed border-neutral-200 pl-3">
                  <div className="text-[11px] text-neutral-500 mb-1.5">
                    4 типа колонок:
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2">
                    {CLASSIFY_SUBTYPES.map((sub) => (
                      <div
                        key={sub.id}
                        className="flex items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 px-2.5 py-1.5"
                      >
                        <ArrowRight
                          size={12}
                          className="shrink-0 text-neutral-400"
                          aria-hidden="true"
                        />
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-neutral-800">
                            {sub.label}
                          </div>
                          <div className="text-[10px] text-neutral-500 font-mono leading-tight">
                            {sub.hint}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Стрелка между шагами (кроме последнего) */}
              {!isLast && <ChevronSeparator />}
              {/* Подсказка под первым шагом — какие форматы поддерживаются */}
              {isFirst && (
                <div className="text-[11px] text-neutral-400 mb-1 ml-1">
                  4 формата на входе
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
