"use client";

// packages/ui/components/NavigatorFormatsVolumePreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта
// «Форматы и объём» (id="formats") секции «Этапы модуля» остановки
// «Загрузка» на странице Навигатор (Task NAVDET-4).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема приёма файла:
//     форматы, проверка типа и размера, автоопределение формата,
//     3 дорожки парсинга (CSV / Excel / JSON), ошибки, результат.
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - packages/ui/components/TsAnalysisUpload.tsx (react-dropzone:
//         один файл, drag-and-drop, accept, maxSize, тексты отказов)
//       - app/data/file_loader.py::read_uploaded_file (расширение →
//         парсер CSV/Excel/JSON; тексты ошибок)
//       - apps/api/upload_common.py::handle_upload
//         (POST /v1/internal/upload → UploadResponse → SessionStore)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (паттерн других остановок).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//
//   ┌──────────────────────────────────────────────────────────┐
//   │ Приём файла: drag-and-drop или выбор — один файл          │
//   └───────────────────────────┬──────────────────────────────┘
//          ┌────────────────────┴───────────────────┐
//   ┌──────▼──────────────────┐  ┌──────────────────▼─────────┐
//   │ Тип: .csv .xls .xlsx    │  │ Размер: до 4MB на проде    │
//   │ .json (accept)          │  │ (прокси ~4.5MB body)       │
//   └─────────────────────────┘  └────────────────────────────┘
//            │ отказ: «Неподдерживаемый        │ отказ: «Файл слишком
//            │ формат»                         │ большой (макс. 4MB)»
//            ▼
//   [Формат — по расширению: всё после последней точки; нет точки → csv]
//            ▼
//   ┌─────────────┐  ┌──────────────────┐  ┌────────────────────┐
//   │ CSV         │  │ Excel .xlsx/.xls │  │ JSON               │
//   │ utf-8-sig   │  │ pd.read_excel    │  │ JSON-stat 2.0      │
//   │ , ; \t |    │  │ col_i            │  │ json_normalize     │
//   │ col_0… skip │  │                  │  │                    │
//   └──────┬──────┘  └────────┬─────────┘  └─────────┬──────────┘
//          ▼ ошибки → HTTP 400          ▼ успех
//   ┌──────────────────────────────────────────────────────────┐
//   │ DataFrame → UploadResponse                                │
//   │ preview 5+5 · columns_info · quality · parse_warnings     │
//   │ → SessionStore                                            │
//   └──────────────────────────────────────────────────────────┘
//
//   Так аналитик мгновенно понимает:
//     1) какие форматы принимает платформа и как файл проверяется;
//     2) как по расширению выбирается парсер и что он делает;
//     3) чем заканчивается загрузка (данные в сессии) и что на отказе.
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Родственник — NavigatorStructureConfirmPreview (статичная
//     Tailwind/CSS-блок-схема, role="img" + aria-label, без состояния).
//   • Без recharts и fetch — чистая разметка с lucide-react иконками.
//   • Про «до 50MB» в тексте остановки: исторический лимит standalone-
//     API; реальный прод-лимит dropzone 4MB (Vercel serverless ~4.5MB
//     body, см. комментарий maxSize в TsAnalysisUpload.tsx) — показан
//     РЕАЛЬНЫЙ лимит, расхождение поясняется в подписи.
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст,
//     единый паттерн с NavigatorStructureConfirmPreview).

import {
  Braces,
  ChevronDown,
  Database,
  FileCheck2,
  FileSearch,
  FileSpreadsheet,
  FileText,
  FileUp,
  FileX,
  type LucideIcon,
} from "lucide-react";

// ── Типы ────────────────────────────────────────────────────────────

interface ParseLane {
  /** Идентификатор дорожки (стабилен — на нём строятся тесты). */
  id: string;
  /** Заголовок дорожки (форматы). */
  title: string;
  /** Иконка. */
  icon: LucideIcon;
  /** Критерии — шаги парсера (по read_uploaded_file). */
  criteria: string[];
}

// ── 3 дорожки парсинга (app/data/file_loader.py::read_uploaded_file) ─

const PARSE_LANES: ParseLane[] = [
  {
    id: "csv",
    title: "CSV",
    icon: FileText,
    criteria: [
      "Кодировка: utf-8-sig (BOM)",
      "Разделитель: , ; \\t | — авто по 1-й строке",
      "Заголовок: авто; без него → col_0…",
      "Битые строки — skip (on_bad_lines)",
    ],
  },
  {
    id: "excel",
    title: "Excel",
    icon: FileSpreadsheet,
    criteria: [
      ".xlsx / .xls — pd.read_excel",
      "Числовые имена колонок → col_i",
      "Первый лист книги",
    ],
  },
  {
    id: "json",
    title: "JSON",
    icon: Braces,
    criteria: [
      "JSON-stat 2.0 → плоская таблица",
      "Список объектов → json_normalize",
      "dict / скаляр → простая таблица",
    ],
  },
];

// ── Принимаемые форматы (accept в TsAnalysisUpload.tsx) ─────────────

const ACCEPTED_FORMATS = [".csv", ".xls", ".xlsx", ".json"] as const;

// ── Ошибки (точные тексты фронта и бэка) ────────────────────────────

const ERROR_ITEMS: string[] = [
  "Неподдерживаемый формат", // dropzone: file-invalid-type
  "Файл слишком большой (макс. 4MB)", // dropzone: file-too-large
  "Файл пуст или не содержит данных.", // read_uploaded_file
  "Формат .{ext} не поддерживается.", // read_uploaded_file
  "Файл пуст или не содержит табличные данные.", // read_uploaded_file
  "Ошибка чтения CSV / Excel / JSON", // обёртки try/except парсеров
];

// ── Поля результата (UploadResponse из upload_common.py) ────────────

const RESULT_FIELDS: { code: string; label: string }[] = [
  { code: "preview", label: "5+5 строк head/tail" },
  { code: "columns_info", label: "dtype и типы колонок" },
  { code: "quality", label: "teaser качества" },
  { code: "parse_warnings", label: "флаги парсинга + size" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorFormatsVolumePreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема приёма файла: drag-and-drop, форматы " +
    ACCEPTED_FORMATS.join(" ") +
    ", проверка типа и размера, формат по расширению, парсинг CSV, Excel, JSON" +
    ", ошибки → HTTP 400, результат UploadResponse → SessionStore";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + бэкенд-эндпоинт */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Форматы и объём
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          POST /v1/internal/upload
        </code>
      </div>

      {/* Приём файла */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2 flex items-center gap-2">
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
          aria-hidden="true"
        >
          <FileUp size={12} />
        </span>
        <span className="text-[11px] text-neutral-700 leading-tight">
          Приём файла: <span className="font-semibold text-neutral-900">drag-and-drop</span>{" "}
          или выбор — один файл (react-dropzone)
        </span>
      </div>

      {/* Две проверки-ворота: тип и размер */}
      <div className="grid grid-cols-2 gap-2 mb-1">
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <FileCheck2 size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Тип файла
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {ACCEPTED_FORMATS.map((f) => (
              <code
                key={f}
                className="text-[9.5px] font-mono text-brand bg-brand-light/60 border border-brand/20 rounded px-1 py-0.5"
              >
                {f}
              </code>
            ))}
          </div>
        </div>
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <FileCheck2 size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Размер файла
            </span>
          </div>
          <span className="text-[9.5px] text-neutral-600 leading-snug">
            до <span className="font-semibold text-neutral-900">4MB</span> на
            проде (прокси ~4.5MB body)
          </span>
        </div>
      </div>

      {/* Стрелка вниз — к определению формата */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Формат по расширению */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-1 flex items-center gap-2">
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-white text-brand border border-brand/20"
          aria-hidden="true"
        >
          <FileSearch size={12} />
        </span>
        <span className="text-[11px] text-neutral-700 leading-tight">
          Формат — по расширению: всё после{" "}
          <span className="font-semibold text-neutral-900">последней точки</span>{" "}
          (lowercase); <span className="font-mono text-[10px]">нет точки → csv</span>
        </span>
      </div>

      {/* Стрелка вниз — к дорожкам парсинга */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* 3 дорожки парсинга */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        {PARSE_LANES.map((lane) => {
          const Icon = lane.icon;
          return (
            <div
              key={lane.id}
              className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0"
            >
              <div className="flex items-center gap-1.5">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
                  aria-hidden="true"
                >
                  <Icon size={12} />
                </span>
                <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
                  {lane.title}
                </span>
              </div>
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

      {/* Стрелка вниз — к результату */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: DataFrame → UploadResponse → SessionStore */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Database size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            DataFrame → UploadResponse → SessionStore
          </span>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {RESULT_FIELDS.map((f) => (
            <div key={f.code} className="text-[9.5px] text-neutral-600 leading-snug">
              <span className="font-mono text-neutral-400">{f.code}</span>
              <br />
              <span className="text-neutral-700">{f.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Ошибки: отказы на входе + ошибки чтения (HTTP 400) */}
      <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 mb-2">
        <div className="flex items-center gap-1.5 mb-1">
          <FileX size={12} className="text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-[10px] font-semibold text-amber-800 leading-tight">
            Если загрузка не прошла — сообщение в окне загрузки / HTTP 400
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {ERROR_ITEMS.map((e) => (
            <span key={e} className="text-[9.5px] text-amber-800 leading-snug">
              {e}
            </span>
          ))}
        </div>
      </div>

      {/* Подпись: пояснение + примечание про 50MB/4MB */}
      <p className="text-[10px] text-neutral-500 mt-1 px-1 leading-snug">
        Файл принимается перетаскиванием в зону загрузки, формат
        определяется по расширению, содержимое читается соответствующим
        парсером pandas — результат сразу попадает в сессию (автопревью,
        типы колонок и teaser качества считаются на бэкенде). Примечание:
        в тексте остановки указан исторический лимит до 50MB, реальный
        лимит прод-прокси — 4.5MB body (dropzone 4MB).
      </p>
    </div>
  );
}
