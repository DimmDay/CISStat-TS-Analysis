"use client";

// packages/ui/components/TsAnalysisUpload.tsx
//
// ОБЩИЙ компонент фичи "Загрузка" -- используется И embedded-,
// И standalone-приложением (одна UI-логика, разные обёртки).
//
// Контракт вкладки "Загрузка" (по решению тимлида):
//   ✅ Превью датасета -- РЕАЛЬНЫЙ (POST /v1/{public|internal}/upload)
//   ✅ Техническая информация (строки/колонки/память/типы) -- РЕАЛЬНАЯ
//   ✅ Teaser качества (только счётчики → Валидация) -- РЕАЛЬНЫЙ
//   🟡 Подтверждение автоопределения (дата/группировка/частота) --
//      клиентская эвристика по реальным columns_info (см.
//      buildDetectionFromColumns ниже). НЕ настоящий бэкенд-детектор --
//      app/data/detectors.py уже умеет определять дату, но не отдаёт
//      форму {selected, confidence, candidates: [{name, score}]}, которую
//      ожидает этот UI. Адаптер -- отдельная задача, не в этом охвате.
//   🟡 Визуализация распределения -- placeholder-макет (Plotly не
//      подключён, реальных статистик по колонке нет backend-эндпоинта).
//      Селектор колонки уже реальный (из columns_info).
//   ⚪ Предупреждения парсинга -- пока не приходят от бэкенда (backend
//      кидает HTTP 400 при ошибке чтения вместо warnings-массива).
//   ❌ Корреляция, STL, ACF/PACF, FFT, периодограмма, вейвлет -- уехали в EDA
//   ❌ Полный паспорт 13 свойств -- уехал в Modeling
//
// ЭТО СЛИЯНИЕ ДВУХ ПРЕЖНИХ КОМПОНЕНТОВ: TsAnalysisUpload.tsx (богатый
// UI-контракт, был не подключён никуда) + DataUploadForm.tsx (реальный,
// но минимальный dropzone). DataUploadForm.tsx удалён -- см. git history.

import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
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
  Loader2,
} from "lucide-react";
import { Button } from "./Button";
import { useAppShell } from "../context/AppShellContext";
import { apiUrl, sessionApiUrl } from "../lib/apiClient";

// ──────────────────────────────────────────────────────────────────────
// ТИПЫ (зеркало apps/api/schemas.py: ColumnInfoOut / QualityTeaserOut /
// UploadResponse -- поля намеренно snake_case, как отдаёт API, без
// промежуточного camelCase-слоя)
// ──────────────────────────────────────────────────────────────────────

interface ColumnInfoOut {
  name: string;
  dtype: string;
  type_icon: "numeric" | "datetime" | "categorical" | "text";
  non_null: number;
  nulls: number;
  unique: number;
}

interface QualityTeaserOut {
  cols_with_missing: number;
  cols_with_outliers: number;
  rows_total: number;
  duplicates: number;
  missing_cols: string[];
  outlier_cols: string[];
}

interface UploadApiResponse {
  dataset_id: string;
  name: string;
  rows: number;
  columns: number;
  preview: { head: string[][]; tail: string[][] };
  columns_info: ColumnInfoOut[] | null;
  quality: QualityTeaserOut | null;
  size_label: string | null;
  error?: string | null;
  // Опциональные поля для автозаполнения профиля в «Моделировании» --
  // бэкенд их пока не возвращает (см. TODO про structure-detection
  // адаптер в шапке файла), но тип готов принять их, когда появятся.
  frequency?: string;
  domain?: string;
  n_series?: number;
  has_seasonality?: boolean;
  is_regular?: boolean;
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

const TYPE_ICON: Record<ColumnInfoOut["type_icon"], string> = {
  numeric: "N",
  datetime: "D",
  categorical: "C",
  text: "T",
};

const FREQ_OPTIONS = [
  "D — ежедневная",
  "W — недельная",
  "M — месячная",
  "Q — квартальная",
  "(авто, не получилось)",
];

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

/**
 * Клиентская ЭВРИСТИКА подтверждения структуры -- ЗАМЕНИТЬ на реальный
 * бэкенд-детектор (см. app/data/detectors.py:detect_and_convert_datetime),
 * когда появится адаптер, отдающий confidence/candidates per column.
 * Пока: колонки с type_icon="datetime" -- кандидаты в дату, "categorical"
 * -- кандидаты в группировку. Уверенность условная (не статистическая).
 */
function buildDetectionFromColumns(columnsInfo: ColumnInfoOut[]): StructureDetection {
  const dateCandidates = columnsInfo.filter((c) => c.type_icon === "datetime");
  const categoricalCandidates = columnsInfo.filter((c) => c.type_icon === "categorical");
  const dateFallback = dateCandidates.length > 0 ? dateCandidates : columnsInfo.slice(0, 3);
  const entityFallback = categoricalCandidates.length > 0 ? categoricalCandidates : columnsInfo.slice(0, 3);

  return {
    dateCol: {
      selected: dateFallback[0]?.name ?? "(не использовать)",
      confidence: dateCandidates.length > 0 ? 80 : 25,
      candidates: dateFallback.map((c, i) => ({ name: c.name, score: Math.max(0.9 - i * 0.2, 0.1) })),
    },
    entityCol: {
      selected: entityFallback[0]?.name ?? "(нет)",
      confidence: categoricalCandidates.length > 0 ? 70 : 25,
      candidates: entityFallback.map((c, i) => ({ name: c.name, score: Math.max(0.85 - i * 0.2, 0.1) })),
    },
    freq: {
      selected: dateCandidates.length > 0 ? "D — ежедневная" : "(авто, не получилось)",
      confidence: dateCandidates.length > 0 ? 60 : 15,
      options: FREQ_OPTIONS,
    },
  };
}

// ──────────────────────────────────────────────────────────────────────
// ГЛАВНЫЙ КОМПОНЕНТ
// ──────────────────────────────────────────────────────────────────────

export function TsAnalysisUpload() {
  const { activeDataset, setActiveDataset, refreshSession, addLogEntry } = useAppShell();

  const [source, setSource] = useState<"file" | "db">("file");
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<UploadApiResponse | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [detection, setDetection] = useState<StructureDetection | null>(null);
  const [selectedDistCol, setSelectedDistCol] = useState<string | null>(null);

  const isUploaded = uploadData !== null;
  const columnsInfo = uploadData?.columns_info ?? [];
  const numericCols = columnsInfo.filter((c) => c.type_icon === "numeric").map((c) => c.name);
  const numericCount = columnsInfo.filter((c) => c.type_icon === "numeric").length;
  const textCount = columnsInfo.length - numericCount;

  // Если в сессии уже есть активный датасет (пользователь пришёл сюда по
  // кнопке "Продолжить" с Home, а не через сам аплоад в этом рендере) --
  // подтягиваем превью/техинфо/качество заново с бэкенда, чтобы не
  // заставлять грузить файл повторно.
  useEffect(() => {
    if (!activeDataset || uploadData) return;
    let cancelled = false;
    setHydrating(true);
    fetch(sessionApiUrl("/dataset"), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: UploadApiResponse | null) => {
        if (cancelled || !data) return;
        setUploadData(data);
        if (data.columns_info) {
          setDetection(buildDetectionFromColumns(data.columns_info));
          const firstNumeric = data.columns_info.find((c) => c.type_icon === "numeric");
          setSelectedDistCol(firstNumeric?.name ?? null);
        }
      })
      .catch(() => {
        // Молча остаёмся в состоянии "нет данных для превью" -- у
        // пользователя всё равно есть activeDataset.name/rows на Home.
      })
      .finally(() => {
        if (!cancelled) setHydrating(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataset]);

  const doUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const resp = await fetch(apiUrl("/upload"), {
          method: "POST",
          body: formData,
          credentials: "include", // несёт cookie сессии -- сервер обновит AnalysisSession
        });
        const data: UploadApiResponse & { detail?: string } = await resp.json();
        if (!resp.ok) {
          throw new Error(data.detail || data.error || "Не удалось загрузить файл");
        }
        setUploadData(data);
        let localDetection: StructureDetection | null = null;
        if (data.columns_info) {
          localDetection = buildDetectionFromColumns(data.columns_info);
          setDetection(localDetection);
          const firstNumeric = data.columns_info.find((c) => c.type_icon === "numeric");
          setSelectedDistCol(firstNumeric?.name ?? null);
        }
        // Автозаполнение профиля для модуля «Моделирование» -- перенесено
        // из packages/ui/components/DataUploadForm.test.tsx на origin/main
        // (Task 6, worklog.md), где эта логика оказалась по ошибке — сам
        // функционал реальный и рабочий, просто не в том файле. Поля из
        // ответа API (когда бэкенд их вернёт -- пока не реализовано, см.
        // TODO в handle_upload) имеют приоритет; freqCode -- fallback на
        // клиентскую эвристику детекции, которая у нас уже есть прямо
        // сейчас, в отличие от исходной версии, где поля брались только
        // из мок-ответа.
        const freqCode = localDetection?.freq.selected.split(" ")[0];
        setActiveDataset({
          name: data.name,
          rows: data.rows,
          sizeLabel: data.size_label ?? "—",
          ...(data.frequency && { frequency: data.frequency }),
          ...(!data.frequency && freqCode && { frequency: freqCode }),
          ...(data.domain && { domain: data.domain }),
          ...(data.n_series != null && { nSeries: data.n_series }),
          ...(data.has_seasonality != null && { hasSeasonality: data.has_seasonality }),
          ...(data.is_regular != null && { isRegular: data.is_regular }),
        });
        // Сервер уже обновил сессию внутри /upload (upload_common.py) --
        // синхронизируем клиентский стейт stages/lastActiveStage тоже.
        await refreshSession();
        toast.success("Файл загружен успешно!");
      } catch (e) {
        const message = e instanceof Error ? e.message : "Неизвестная ошибка загрузки";
        setUploadError(message);
        toast.error(`Ошибка: ${message}`);
        addLogEntry("ERROR", `Ошибка загрузки файла: ${message}`);
      } finally {
        setUploading(false);
      }
    },
    [setActiveDataset, refreshSession, addLogEntry]
  );

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (!file) return;
      setFileName(file.name);
      doUpload(file);
    },
    [doUpload]
  );

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    multiple: false,
    maxSize: 50 * 1024 * 1024, // 50MB — как в прежнем DataUploadForm.tsx
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".xls"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/json": [".json"],
    },
  });

  const rejectedFiles = fileRejections.map(({ file, errors }) => ({
    file,
    errors: errors.map((e) => {
      if (e.code === "file-too-large") return "Файл слишком большой (макс. 50MB)";
      if (e.code === "file-invalid-type") return "Неподдерживаемый формат";
      return e.message;
    }),
  }));

  const handleReset = () => {
    setUploadData(null);
    setUploadError(null);
    setDetection(null);
    setFileName(null);
  };

  const handleApplyOverride = () => {
    // ЗАМЕНИТЬ: PATCH /v1/internal/datasets/{id}/column-mapping -- эндпоинт
    // ещё не реализован на бэкенде (см. комментарий в шапке файла).
    // Пока -- локальное подтверждение выбора, без вызова API.
    if (detection) setDetection({ ...detection });
    addLogEntry("INFO", "Подтверждение структуры сохранено (пока только локально — см. TODO в коде)");
  };

  return (
    <div className="space-y-6">
      {/* Заголовок страницы */}
      <header className="flex items-end justify-between flex-wrap gap-2">
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
          ) : hydrating ? (
            <span className="text-neutral-400 inline-flex items-center gap-1">
              <Loader2 size={12} className="animate-spin" aria-hidden="true" /> Восстанавливаем сессию…
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
              onClick={handleReset}
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
              <div
                {...getRootProps()}
                className={`mt-4 border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
                  isDragActive ? "border-brand bg-brand-light" : "border-neutral-300 bg-neutral-50"
                }`}
              >
                <input {...getInputProps()} data-testid="dropzone-input" />
                <div className="text-sm text-neutral-600 inline-flex flex-col items-center gap-2">
                  {uploading ? (
                    <>
                      <Loader2 size={24} className="text-brand animate-spin" aria-hidden="true" />
                      <span>Загружаем и анализируем файл…</span>
                    </>
                  ) : (
                    <>
                      <Upload size={24} className="text-neutral-400" aria-hidden="true" />
                      <span>
                        {isDragActive
                          ? "Отпустите файл здесь…"
                          : "Перетащите файл сюда или нажмите для выбора"}
                      </span>
                      <span className="text-xs text-neutral-500">
                        Поддерживаемые форматы: .csv, .xlsx, .xls, .json (макс. 50MB)
                      </span>
                      {fileName && (
                        <span className="text-green-600">
                          Выбран: <strong>{fileName}</strong>
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-neutral-500 mb-4 mt-4 bg-neutral-50 rounded p-4">
                (форма подключения к БД — заглушка)
              </p>
            )}

            {rejectedFiles.length > 0 && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
                <h3 className="font-medium text-red-700 mb-1 text-sm">Ошибки:</h3>
                <ul className="list-disc list-inside text-sm text-red-600">
                  {rejectedFiles.map(({ file, errors }) => (
                    <li key={file.name}>
                      {file.name}: {errors.join(", ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {uploadError && (
              <div className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
                <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                <span>{uploadError}</span>
              </div>
            )}
          </>
        ) : (
          <div className="mt-4 border border-neutral-200 rounded-lg p-4 text-sm bg-neutral-50">
            <div className="flex items-center gap-2 text-neutral-700 flex-wrap">
              <FileText size={16} className="text-brand" aria-hidden="true" />
              <strong className="text-neutral-900">{uploadData!.name}</strong>
              <span className="text-neutral-400">·</span>
              <span>{uploadData!.size_label ?? "—"}</span>
              <span className="text-neutral-400">·</span>
              <span>загружен успешно</span>
              <span className="text-neutral-400">·</span>
              <span>{formatNum(uploadData!.rows)} строк</span>
              <span className="text-neutral-400">·</span>
              <span>{uploadData!.columns} колонок</span>
            </div>
          </div>
        )}
      </section>

      {isUploaded && detection && (
        <>
          {/* ════════ Секция 2: Подтверждение автоопределения ════════ */}
          <section className="bg-white rounded-lg border border-neutral-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold text-neutral-900">Подтверждение автоопределения</h2>
                <p className="text-xs text-neutral-500 mt-0.5 max-w-2xl">
                  Эвристика определила структуру датасета по типам колонок. Проверьте и поправьте,
                  если ошиблась — это определит весь дальнейший анализ.
                </p>
              </div>
              <span className="text-xs bg-neutral-100 text-neutral-500 px-2 py-1 rounded font-mono hidden md:inline-block">
                клиентская эвристика · бэкенд-детектор — TODO
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
                    setDetection({ ...detection, dateCol: { ...detection.dateCol, selected: e.target.value } })
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
                    setDetection({ ...detection, entityCol: { ...detection.entityCol, selected: e.target.value } })
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
                  onChange={(e) => setDetection({ ...detection, freq: { ...detection.freq, selected: e.target.value } })}
                  className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
                >
                  {detection.freq.options.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-neutral-500">Оценено по {formatNum(uploadData!.rows)} строкам.</p>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between flex-wrap gap-3">
              <p className="text-xs text-neutral-500 max-w-2xl">
                Override сохраняется серверно (in-memory на этапе прототипа, Redis+TTL в продакшене) —
                переживёт F5 и доступен через API. Применение override-эндпоинта — TODO (см. шапку файла).
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

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                <div className="border border-neutral-200 rounded-lg p-3">
                  <div className="text-xs text-neutral-500">Всего строк</div>
                  <div className="text-xl font-semibold text-neutral-900">{formatNum(uploadData!.rows)}</div>
                </div>
                <div className="border border-neutral-200 rounded-lg p-3">
                  <div className="text-xs text-neutral-500">Всего колонок</div>
                  <div className="text-xl font-semibold text-neutral-900">{uploadData!.columns}</div>
                </div>
                <div className="border border-neutral-200 rounded-lg p-3">
                  <div className="text-xs text-neutral-500">Размер файла</div>
                  <div className="text-xl font-semibold text-neutral-900">{uploadData!.size_label ?? "—"}</div>
                </div>
                <div className="border border-neutral-200 rounded-lg p-3">
                  <div className="text-xs text-neutral-500">Числовых / Прочих</div>
                  <div className="text-xl font-semibold text-neutral-900">
                    {numericCount} / {textCount}
                  </div>
                </div>
              </div>

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
                    {columnsInfo.map((col) => (
                      <tr key={col.name}>
                        <td className="px-3 py-2 font-medium">{col.name}</td>
                        <td className="px-3 py-2 text-neutral-600">
                          <span className="inline-flex items-center gap-1.5">
                            <span
                              className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${
                                col.type_icon === "numeric"
                                  ? "bg-blue-100 text-blue-700"
                                  : col.type_icon === "datetime"
                                  ? "bg-purple-100 text-purple-700"
                                  : col.type_icon === "categorical"
                                  ? "bg-green-100 text-green-700"
                                  : "bg-neutral-200 text-neutral-600"
                              }`}
                            >
                              {TYPE_ICON[col.type_icon]}
                            </span>
                            {col.dtype}
                          </span>
                        </td>
                        <td className="text-right px-3 py-2">{formatNum(col.non_null)}</td>
                        <td className="px-3 py-2">
                          {col.nulls > 0 ? (
                            <div className="flex items-center gap-2">
                              <div className="w-24 bg-neutral-200 rounded-full h-1.5">
                                <div
                                  className="bg-amber-500 h-1.5 rounded-full"
                                  style={{ width: `${(col.nulls / uploadData!.rows) * 100}%` }}
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
              <p className="mt-3 text-xs text-neutral-500">Датасет загружен: {uploadData!.name}</p>
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
                <span className="text-xs text-neutral-500 font-normal">первые и последние 5 строк</span>
              </summary>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-neutral-50 text-neutral-500 uppercase">
                    <tr>
                      {uploadData!.preview.head[0]?.map((colName, i) => (
                        <th key={i} className="text-left px-2 py-1.5">
                          {colName}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {uploadData!.preview.head.slice(1).map((row, i) => (
                      <tr key={`head-${i}`}>
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1.5">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr className="text-neutral-400">
                      <td colSpan={uploadData!.preview.head[0]?.length ?? 1} className="px-2 py-1.5 text-center">
                        …
                      </td>
                    </tr>
                    {uploadData!.preview.tail.map((row, i) => (
                      <tr key={`tail-${i}`}>
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1.5">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </section>

          {/* ════════ Секция 5: Визуализация распределения ════════ */}
          {numericCols.length > 0 && (
            <section className="bg-white rounded-lg border border-neutral-200 p-5">
              <details open>
                <summary className="font-semibold text-neutral-900 cursor-pointer flex items-center justify-between">
                  <span className="inline-flex items-center gap-2">
                    <BarChart3 size={18} className="text-brand" aria-hidden="true" />
                    Визуализация распределения данных
                  </span>
                  <span className="text-xs text-neutral-500 font-normal hidden md:inline">
                    макет — реальный чартинг ещё не подключён
                  </span>
                </summary>
                <p className="text-sm text-neutral-600 mt-2 max-w-3xl">
                  Интерактивный анализ распределения числовых признаков: точечный график, гистограмма, KDE
                  и статистические метрики для оценки формы распределения, асимметрии и выбросов.
                </p>

                <div className="mt-4 flex items-center gap-3">
                  <label className="text-sm text-neutral-700">Выберите числовую колонку:</label>
                  <select
                    value={selectedDistCol ?? numericCols[0]}
                    onChange={(e) => setSelectedDistCol(e.target.value)}
                    className="border border-neutral-300 rounded px-3 py-1.5 text-sm font-medium"
                  >
                    {numericCols.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                  <div>
                    <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                      <ScatterChart size={14} className="text-neutral-500" aria-hidden="true" />
                      Точечный график
                    </h4>
                    <div className="h-[300px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
                      [ Plotly scatter: x=index, y={selectedDistCol}, opacity=0.6 ]
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                      <BarChart3 size={14} className="text-neutral-500" aria-hidden="true" />
                      Гистограмма
                    </h4>
                    <div className="h-[300px] border border-neutral-200 rounded flex flex-col items-center justify-center text-xs text-neutral-500 gap-1 bg-neutral-50">
                      [ Plotly histogram, nbins=30 ]
                      <span className="text-neutral-400">+ KDE + vlines: Mean / Median / Q1 / Q3</span>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
                      <Activity size={14} className="text-neutral-500" aria-hidden="true" />
                      KDE (плотность)
                    </h4>
                    <div className="h-[300px] border border-neutral-200 rounded flex flex-col items-center justify-center text-xs text-neutral-500 gap-1 bg-neutral-50">
                      [ Plotly scatter: KDE curve, fill=tozeroy ]
                    </div>
                  </div>
                </div>

                <p className="mt-4 text-xs text-neutral-500 bg-neutral-50 rounded p-3">
                  Реальные статистики распределения (mean/median/skew/kurtosis/IQR) и графики требуют
                  отдельного backend-эндпоинта — сейчас на бэкенде считаются только счётчики качества
                  (missing/outliers/duplicates), не полное описание распределения. TODO.
                </p>
              </details>
            </section>
          )}

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
              <p className="mt-3 text-sm text-neutral-600 bg-brand-light rounded px-3 py-2">
                Активно: <strong>{formatNum(uploadData!.rows)}</strong> записей · без фильтров
              </p>
              <p className="mt-2 text-xs text-neutral-500">
                Построитель 8 типов графиков (Bar/Line/Area/Scatter/Box/Hist/Hist+KDE/Funnel) и
                переключатель режима «Временные ряды vs Общий» перенесены в модуль{" "}
                <Link href="/eda" className="text-brand underline">
                  Разведочный EDA
                </Link>{" "}
                — это содержательный анализ, не проверка загрузки.
              </p>
            </details>
          </section>

          {/* ════════ Секция 7: Предварительная оценка качества (teaser) ════════ */}
          {uploadData!.quality && (
            <section className="bg-white rounded-lg border border-neutral-200 p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="font-semibold text-neutral-900">Предварительная оценка качества</h2>
                  <p className="text-xs text-neutral-500 mt-0.5">
                    Только счётчики. Содержательный анализ проблем — в модуле «Валидация».
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
                  <div className="text-xs text-amber-700 uppercase">Колонок с пропусками</div>
                  <div className="text-2xl font-semibold text-amber-900 mt-1">
                    {uploadData!.quality.cols_with_missing}
                  </div>
                  <div className="text-xs text-amber-700 mt-1">{uploadData!.quality.missing_cols.join(", ")}</div>
                </div>
                <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
                  <div className="text-xs text-amber-700 uppercase">Колонок с потенц. выбросами</div>
                  <div className="text-2xl font-semibold text-amber-900 mt-1">
                    {uploadData!.quality.cols_with_outliers}
                  </div>
                  <div className="text-xs text-amber-700 mt-1">{uploadData!.quality.outlier_cols.join(", ")}</div>
                </div>
                <div className="border border-neutral-200 rounded-lg p-4">
                  <div className="text-xs text-neutral-500 uppercase">Всего строк</div>
                  <div className="text-2xl font-semibold text-neutral-900 mt-1">
                    {formatNum(uploadData!.quality.rows_total)}
                  </div>
                </div>
                <div className="border border-neutral-200 rounded-lg p-4">
                  <div className="text-xs text-neutral-500 uppercase">Дубликатов</div>
                  <div className="text-2xl font-semibold text-green-700 mt-1">{uploadData!.quality.duplicates}</div>
                </div>
              </div>

              <Link
                href="/validation"
                className="mt-4 inline-flex items-center gap-2 bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
              >
                Перейти к Валидации <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </section>
          )}

          {/* ════════ Секция 8: Памятка ════════ */}
          <section className="bg-brand-light rounded-lg p-5 border border-brand/20">
            <h2 className="font-semibold text-brand mb-3 inline-flex items-center gap-2">
              <Info size={18} aria-hidden="true" />
              Что считается в следующих модулях
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
        </>
      )}
    </div>
  );
}
