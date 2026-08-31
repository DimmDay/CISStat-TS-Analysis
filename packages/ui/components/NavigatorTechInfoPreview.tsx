"use client";

// packages/ui/components/NavigatorTechInfoPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» остановки
// «Техническая информация» (id="tech_info") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор (Task 2026-08-31).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     построения технической информации по каждой колонке датасета:
//     4 ветки классификации type_icon + 3 метрики non_null/nulls/unique.
//   • Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       - apps/api/upload_common.py::_compute_column_info
//       - apps/api/schemas.py::ColumnInfoOut
//       - apps/api/upload_common.py::handle_upload (отдаёт в UploadResponse.columns_info)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (это и есть требование тимлида).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//   Аналитик видит 4 «дорожки» классификации type_icon (по dtype):
//
//     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
//     │ datetime     │ │ numeric      │ │ categorical  │ │ text         │
//     │ is_datetime64│ │ is_numeric  │ │ nunique ≤ 50 │ │ fallback     │
//     │ _any_dtype   │ │ _dtype      │ │ (object/str) │ │ (остальное)  │
//     └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
//            └────────────┬──┴─────────────┬───┴──────────────┘
//                         ▼                ▼
//                   ┌──────────────────────────────────┐
//                   │ type_icon (один из 4)            │
//                   └──────────────┬───────────────────┘
//                                  ▼
//                   3 метрики: non_null / nulls / unique
//                                  ▼
//                   ┌──────────────────────────────────┐
//                   │ ColumnInfoOut[]                  │
//                   │ ← UploadResponse.columns_info    │
//                   └──────────────────────────────────┘
//                                  ▼
//                   Таблица 5 колонок во вкладке «Загрузка»:
//                   Колонка / Тип / Не пусто / Пропуски / Уникальных
//
//   Так аналитик мгновенно понимает:
//     1) что именно бэкенд определяет по каждой колонке (4 типа);
//     2) по каким критериям (dtype-проверки + порог nunique ≤ 50);
//     3) какие 3 метрики считаются (non_null / nulls / unique);
//     4) где это видно в UI (таблица во вкладке «Загрузка»).
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — NavigatorQualityTeaserPreview (Task
//     «Teaser качества»): статичная Tailwind/CSS-блок-схема,
//     role="img" + aria-label, без состояния, без recharts.
//   • 4 дорожки type_icon расположены в сетке 4 колонки (grid-cols-4)
//     — повторяет layout Metric-карточек в самой вкладке «Загрузка»
//     (TsAnalysisUpload.tsx:1312 — grid-cols-2 md:grid-cols-4).
//   • Порядок дорожек строго соответствует порядку проверки в
//     _compute_column_info: datetime → numeric → categorical → text
//     (if/elif chain, первое совпадение выигрывает).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с описанием всех 4 дорожек —
//     скринридер читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текстовую
//     информацию, единый паттерн с другими Navigator*Preview).

import {
  CalendarClock,
  Hash,
  Tags,
  Type,
  ChevronDown,
  Database,
  Info,
  type LucideIcon,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────

interface TypeIconLane {
  /** Идентификатор type_icon (стабилен — на нём строятся тесты).
   *  Совпадает со значениями ColumnInfoOut.type_icon на бэкенде. */
  id: string;
  /** Человекочитаемый лейбл (как в TsAnalysisUpload.tsx). */
  label: string;
  /** Бэкенд-источник: код вычисления (pd.api.types.*). */
  source: string;
  /** Иконка. */
  icon: LucideIcon;
  /** Краткое описание критерия/метода. */
  method: string;
}

// ── 4 ветки type_icon ────────────────────────────────────────────────
//
// Источник истины — apps/api/upload_common.py::_compute_column_info.
// Порядок: datetime → numeric → categorical → text, как в if/elif
// chain бэкенда (первое совпадение выигрывает, поэтому порядок важен).

const TYPE_ICON_LANES: TypeIconLane[] = [
  {
    id: "datetime",
    label: "datetime",
    source: "is_datetime64_any_dtype",
    icon: CalendarClock,
    method: "Колонка уже распознана pandas как datetime64 (после detect_and_convert_datetime)",
  },
  {
    id: "numeric",
    label: "numeric",
    source: "is_numeric_dtype",
    icon: Hash,
    method: "Все числовые dtype: int*, float*, uint*",
  },
  {
    id: "categorical",
    label: "categorical",
    source: "nunique(dropna=True) ≤ 50",
    icon: Tags,
    method: "object/string/category dtype с малым числом уникальных значений",
  },
  {
    id: "text",
    label: "text",
    source: "fallback",
    icon: Type,
    method: "Остальные object/string колонки (много уникальных — свободный текст)",
  },
];

// ── 3 метрики ColumnInfoOut (кроме name/dtype/type_icon) ─────────────
//
// Совпадает с apps/api/schemas.py::ColumnInfoOut и заголовками таблицы
// в TsAnalysisUpload.tsx:1056-1060.

const METRICS: { id: string; label: string; source: string }[] = [
  { id: "non_null", label: "Не пусто", source: "series.notna().sum()" },
  { id: "nulls", label: "Пропуски", source: "series.isna().sum()" },
  { id: "unique", label: "Уникальных", source: "series.nunique(dropna=True)" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorTechInfoPreview() {
  // Описание для скринридера — перечисляем все 4 ветки type_icon и
  // 3 метрики одной строкой, чтобы пользователь с AT получил полное
  // представление об алгоритме без перехода по каждой ноде.
  const ariaLabel =
    "Блок-схема технической информации по колонкам: " +
    "классификация type_icon по 4 веткам (" +
    TYPE_ICON_LANES.map((l) => `${l.label} (${l.source})`).join(", ") +
    ") → 3 метрики (non_null, nulls, unique) → ColumnInfoOut[] внутри " +
    "UploadResponse.columns_info → таблица 5 колонок во вкладке Загрузка";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + бэкенд-источник */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Техническая информация
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          _compute_column_info
        </code>
      </div>

      {/* 4 параллельные дорожки type_icon (grid-cols-4 — как в вкладке Загрузка) */}
      <div className="grid grid-cols-4 gap-1.5 mb-2">
        {TYPE_ICON_LANES.map((lane) => {
          const Icon = lane.icon;
          return (
            <div
              key={lane.id}
              className="rounded-md border border-brand/30 bg-white px-1.5 py-2 flex flex-col gap-1 min-w-0"
            >
              {/* Иконка + лейбл type_icon */}
              <div className="flex items-center gap-1">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
                  aria-hidden="true"
                >
                  <Icon size={12} />
                </span>
                <span className="text-[10px] font-semibold text-neutral-900 leading-tight font-mono">
                  {lane.label}
                </span>
              </div>
              {/* Бэкенд-источник: dtype-проверка */}
              <code className="text-[8.5px] text-neutral-400 font-mono leading-tight break-all">
                {lane.source}
              </code>
              {/* Метод */}
              <p className="text-[9px] text-neutral-600 leading-snug mt-0.5">
                {lane.method}
              </p>
            </div>
          );
        })}
      </div>

      {/* Стрелка вниз — выбран ОДИН type_icon (первое совпадение if/elif) */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-метрики: 3 метрики ColumnInfoOut */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Database size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            3 метрики по каждой колонке
          </span>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {METRICS.map((m) => (
            <div key={m.id} className="text-[9px] text-neutral-600 leading-snug">
              <span className="font-mono text-neutral-700 font-semibold">{m.id}</span>
              <br />
              <span className="text-neutral-500">→ {m.label}</span>
              <br />
              <code className="text-[8.5px] text-neutral-400">{m.source}</code>
            </div>
          ))}
        </div>
      </div>

      {/* Стрелка вниз → результат */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: ColumnInfoOut[] (внутри UploadResponse.columns_info) */}
      <div className="rounded-md border border-neutral-300 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Info size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            ColumnInfoOut[]
          </span>
          <span className="text-[9px] text-neutral-400 font-mono">
            ← внутри UploadResponse.columns_info
          </span>
        </div>
        <div className="text-[9px] text-neutral-500 font-mono leading-snug">
          name · dtype · type_icon · non_null · nulls · unique
        </div>
        <div className="mt-1 text-[9px] text-neutral-500 leading-snug">
          Считается <span className="font-mono">сразу при загрузке</span> — отдельного
          эндпоинта нет, как и у Teaser качества.
        </div>
      </div>

      {/* Финальный блок: таблица в UI + польза */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-brand/30 bg-brand-light/30 px-2 py-1.5 flex items-center gap-1.5">
          <Database size={12} className="text-brand shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-neutral-700 leading-tight">
            таблица 5 колонок: <span className="font-mono">Колонка / Тип / Не пусто / Пропуски / Уникальных</span>
          </span>
        </div>
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-center gap-1.5">
          <Info size={12} className="text-emerald-600 shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-emerald-800 leading-tight">
            вход для автоопределения структуры (numeric-колонки → date-скоринг)
          </span>
        </div>
      </div>

      {/* Подпись: краткое пояснение алгоритма */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        Для <span className="font-mono">каждой колонки</span> датасета бэкенд определяет{" "}
        <span className="font-mono">type_icon</span> по dtype (if/elif chain:
        datetime → numeric → categorical → text) и считает 3 метрики. Результат
        уходит в ответ <span className="font-mono">/upload</span> и отображается таблицей
        во вкладке «Загрузка».
      </p>
    </div>
  );
}
