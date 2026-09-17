"use client";

// packages/ui/components/NavigatorSourceFileDbPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта
// «Источник: файл или БД» (id="source") секции «Этапы модуля» остановки
// «Загрузка» на странице Навигатор (Task NAVDET-5).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема источника
//     данных: переключатель «Файл / База данных (SQL)», файловая
//     дорожка (drag-and-drop → POST /v1/internal/upload →
//     read_uploaded_file → DataFrame), дорожка БД (PostgreSQL /
//     ClickHouse, форма подключения, SQL-запрос, тест подключения,
//     pd.read_sql / query_df), общий результат (датасет в сессии),
//     ошибки обеих дорожек.
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - packages/ui/components/TsAnalysisUpload.tsx (радио-переключатель
//         «Файл .xlsx, .xls, .csv, .json» / «База данных (SQL)», dropzone,
//         4 демо-датасета через тот же doUpload)
//       - app/data/file_loader.py::init_db_connection (PostgreSQL —
//         SQLAlchemy engine + SELECT 1; ClickHouse — clickhouse_connect +
//         ping; таймауты: подключение 10 с, запрос 60 с; ConnectionError
//         «Не удалось подключиться к {db_type}»; ImportError — драйвер)
//       - app.py (форма подключения: Тип БД, Host, Port 5432/8123,
//         Database, User, Password, SQL Query «SELECT * FROM your_table
//         LIMIT 1000»; pd.read_sql / query_df; robust_datetime_detector;
//         drop_service_columns)
//       - apps/api/upload_common.py::handle_upload (UploadResponse →
//         SessionStore)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (паттерн других остановок).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//
//   ┌────────────────────────────────────────────────────────────┐
//   │ Источник данных — переключатель:                           │
//   │ [Файл .xlsx, .xls, .csv, .json]  [База данных (SQL)]       │
//   └────────────────────────────┬───────────────────────────────┘
//        ┌───────────────────────┴───────────────────────┐
//   ┌────▼─────────────────────┐  ┌──────────────────────▼────────┐
//   │ ФАЙЛ                     │  │ БАЗА ДАННЫХ (SQL)             │
//   │ .csv .xls .xlsx .json    │  │ PostgreSQL / ClickHouse       │
//   │ drag-and-drop, 1 файл    │  │ Host·Port·Database·User·Pwd   │
//   │ 4 демо-датасета          │  │ SELECT … LIMIT 1000           │
//   │ → /v1/internal/upload    │  │ Тест: SELECT 1 / ping         │
//   │ → read_uploaded_file     │  │ pd.read_sql / query_df        │
//   └────┬─────────────────────┘  └──────────────┬────────────────┘
//        └───────────────────────┬───────────────┘
//   ┌────────────────────────────▼───────────────────────────────┐
//   │ DataFrame → датасет в сессии                               │
//   │ файл: UploadResponse (preview/columns_info/quality) → Store│
//   │ БД:   robust_datetime_detector → drop_service_columns      │
//   └────────────────────────────────────────────────────────────┘
//   Ошибки: формат/размер/пустой файл; подключение/драйвер/запрос.
//
//   Так аналитик мгновенно понимает:
//     1) какие два источника данных есть у платформы и как выбираются;
//     2) как устроен каждый путь — от входа до DataFrame;
//     3) чем заканчивается загрузка (датасет в сессии) и что на отказе.
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Родственник — NavigatorFormatsVolumePreview (статичная
//     Tailwind/CSS-блок-схема, role="img" + aria-label, без состояния).
//   • Без recharts и fetch — чистая разметка с lucide-react иконками.
//   • Честный статус функционала: файловый путь реализован полностью
//     (включая демо-датасеты); форма подключения к БД на странице
//     «Загрузка» — заглушка, бэкенд-логика (init_db_connection) готова —
//     показано в подписи, как примечание о 50MB/4MB у NavigatorFormats-
//     VolumePreview.
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст,
//     единый паттерн с NavigatorFormatsVolumePreview).

import {
  ChevronDown,
  Database,
  FileCheck2,
  FileUp,
  FileX,
  Table2,
} from "lucide-react";

// ── Принимаемые форматы файловой дорожки (accept в TsAnalysisUpload) ──

const SOURCE_FILE_FORMATS = [".csv", ".xls", ".xlsx", ".json"] as const;

// ── Поля формы подключения к БД (app.py, expander «Настройки подключения») ──

const DB_FORM_FIELDS = ["Host", "Port", "Database", "User", "Password"] as const;

// ── Ошибки файловой дорожки (dropzone + read_uploaded_file) ─────────

const FILE_ERROR_ITEMS: string[] = [
  "Неподдерживаемый формат", // dropzone: file-invalid-type
  "Файл слишком большой (макс. 4MB)", // dropzone: file-too-large
  "Файл пуст или не содержит данных.", // read_uploaded_file
];

// ── Ошибки дорожки БД (init_db_connection + app.py) ─────────────────

const DB_ERROR_ITEMS: string[] = [
  "Не удалось подключиться к {db_type}", // ConnectionError
  "Требуется драйвер: pip install psycopg2-binary / clickhouse-connect", // ImportError
  "Введите SQL-запрос", // пустой query в app.py
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorSourceFileDbPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема источника данных: переключатель Файл или База данных (SQL). " +
    "Файловая дорожка: drag-and-drop, форматы " +
    SOURCE_FILE_FORMATS.join(" ") +
    ", POST /v1/internal/upload, read_uploaded_file, парсер по расширению. " +
    "Дорожка БД: PostgreSQL или ClickHouse, форма Host Port Database User Password, " +
    "SQL-запрос SELECT * FROM your_table LIMIT 1000, тест подключения SELECT 1 или ping, " +
    "pd.read_sql или query_df. Результат: датасет в сессии. " +
    "Ошибки: сообщение в окне загрузки";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + эндпоинт приёма файла */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Источник: файл или БД
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          POST /v1/internal/upload
        </code>
      </div>

      {/* Переключатель источника (верхняя полоса страницы «Загрузка») */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <Table2 size={12} />
          </span>
          <span className="text-[11px] text-neutral-700 leading-tight">
            Источник данных — переключатель на странице «Загрузка»
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <span className="rounded border border-brand/20 bg-brand-light/60 px-2 py-1 text-[10px] text-neutral-700 text-center leading-tight">
            Файл .xlsx, .xls, .csv, .json
          </span>
          <span className="rounded border border-brand/20 bg-brand-light/60 px-2 py-1 text-[10px] text-neutral-700 text-center leading-tight">
            База данных (SQL)
          </span>
        </div>
      </div>

      {/* Две дорожки источника */}
      <div className="grid grid-cols-2 gap-2 mb-1">
        {/* Дорожка 1: Файл */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <FileUp size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Файл
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {SOURCE_FILE_FORMATS.map((f) => (
              <code
                key={f}
                className="text-[9.5px] font-mono text-brand bg-brand-light/60 border border-brand/20 rounded px-1 py-0.5"
              >
                {f}
              </code>
            ))}
          </div>
          <ul className="flex flex-col gap-0.5 mt-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              drag-and-drop или клик — один файл (react-dropzone)
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              4 демо-датасета — тот же файловый пайплайн
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">POST /v1/internal/upload</span>{" "}
              → <span className="font-mono text-neutral-700">read_uploaded_file</span>
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              парсер по расширению → DataFrame
            </li>
          </ul>
        </div>

        {/* Дорожка 2: База данных (SQL) */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <Database size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              База данных
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            <code className="text-[9.5px] font-mono text-brand bg-brand-light/60 border border-brand/20 rounded px-1 py-0.5">
              PostgreSQL
            </code>
            <code className="text-[9.5px] font-mono text-brand bg-brand-light/60 border border-brand/20 rounded px-1 py-0.5">
              ClickHouse
            </code>
          </div>
          <div className="flex flex-wrap gap-1">
            {DB_FORM_FIELDS.map((f) => (
              <code
                key={f}
                className="text-[9px] font-mono text-neutral-600 bg-neutral-50 border border-neutral-200 rounded px-1 py-0.5"
              >
                {f}
              </code>
            ))}
          </div>
          <ul className="flex flex-col gap-0.5 mt-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              Порты по умолчанию: 5432 (PostgreSQL) / 8123 (ClickHouse)
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              SQL-запрос:{" "}
              <span className="font-mono text-neutral-700">
                SELECT * FROM your_table LIMIT 1000
              </span>{" "}
              — рекомендуется LIMIT для тестов
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              Тест подключения: <span className="font-mono">SELECT 1</span> (PG) /{" "}
              <span className="font-mono">ping</span> (CH)
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              Загрузка: <span className="font-mono">pd.read_sql</span> (PG) /{" "}
              <span className="font-mono">query_df</span> (CH)
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              таймауты: подключение 10 с, запрос 60 с
            </li>
          </ul>
        </div>
      </div>

      {/* Стрелка вниз — к общему результату */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: обе дорожки сходятся в датасет сессии */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Database size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            DataFrame → датасет в сессии
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="text-[9.5px] text-neutral-600 leading-snug">
            <span className="font-semibold text-neutral-700">Файл:</span> UploadResponse{" "}
            <span className="font-mono text-neutral-400">
              (preview · columns_info · quality · parse_warnings)
            </span>{" "}
            → <span className="font-mono text-neutral-700">SessionStore</span>
          </div>
          <div className="text-[9.5px] text-neutral-600 leading-snug">
            <span className="font-semibold text-neutral-700">БД:</span>{" "}
            <span className="font-mono text-neutral-700">robust_datetime_detector</span> →{" "}
            <span className="font-mono text-neutral-700">drop_service_columns</span> → сессия
          </div>
        </div>
      </div>

      {/* Ошибки: отказы файловой дорожки + ошибки подключения к БД */}
      <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 mb-2">
        <div className="flex items-center gap-1.5 mb-1">
          <FileX size={12} className="text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-[10px] font-semibold text-amber-800 leading-tight">
            Если источник не подключился — сообщение в окне загрузки
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {FILE_ERROR_ITEMS.map((e) => (
            <span key={e} className="text-[9.5px] text-amber-800 leading-snug">
              {e}
            </span>
          ))}
          {DB_ERROR_ITEMS.map((e) => (
            <span key={e} className="text-[9.5px] text-amber-800 leading-snug">
              {e}
            </span>
          ))}
        </div>
      </div>

      {/* Подпись: пояснение + честный статус формы БД */}
      <p className="text-[10px] text-neutral-500 mt-1 px-1 leading-snug">
        Выбор источника — переключатель в верхней полосе страницы «Загрузка».
        Файловый путь работает полностью, включая готовые демо-наборы данных.
        Форма подключения к SQL-базе на странице «Загрузка» — заглушка: логика
        подключения (init_db_connection) реализована на бэкенде и поддерживает
        две СУБД; соединение проверяется тестовым запросом до загрузки данных.
      </p>
    </div>
  );
}
