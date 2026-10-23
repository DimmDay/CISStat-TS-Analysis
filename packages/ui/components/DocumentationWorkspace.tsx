"use client";

// packages/ui/components/DocumentationWorkspace.tsx
//
// DOCLOG-4 (спека §12.1-§12.3, AC17): раздел «Документы исследования».
//
// Layout (§12.1): три области desktop -- этапы/виды документов (220-260px),
// список версий (300-360px), предпросмотр (остальное); responsive-диапазоны,
// НЕ жёсткая сетка. На узком экране -- последовательные панели (hidden/
// lg:block) с сохранённым выбором; preview имеет полноэкранный режим.
//
// Состояния (§12.3, AC17): empty/loading/queued/rendering/ready/partial/
// stale/unknown/failed/cancelled/forbidden/unavailable dependency; для 409
// -- предложение перечитать; offline НЕ показывается как «нет документов».
// Доступность: role=status для смен состояний, role=alert для отказов,
// aria-current на выбранном виде, семантическая таблица версий, видимый
// focus, цвет НЕ единственный носитель статуса (текстовые метки).
// Темы -- общие токены платформы (bg-neutral-*/text-neutral-*/brand).
//
// Открытие раздела НЕ создаёт документ фактом открытия (§12.1) -- список
// только читает; документ создаёт явное действие «Создать черновик».

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DocumentPreview } from "./DocumentPreview";
import {
  cancelJob,
  createDraft,
  getJob,
  getRevision,
  listDocuments,
  renditionContentUrl,
  requestRendition,
  type DocumentSummary,
  type JobPayload,
  type RenditionSummary,
  type RevisionSummary,
  type SnapshotPayload,
} from "../lib/documentation";

// Виды документов D01-D09 (спека §6/§12.2 «Левый список»); заголовки --
// серверный реестр (DOCUMENT_KINDS), клиентский фолбэк -- по коду.
const KIND_CODES = ["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09"] as const;

const KIND_TITLES: Record<string, string> = {
  D01: "План исследования",
  D02: "Паспорт источника",
  D03: "Протокол качества",
  D04: "Рецепт преобразований",
  D05: "Аналитическая записка",
  D06: "Протокол экспериментов",
  D07: "Карточка модели",
  D08: "Выпуск прогноза",
  D09: "Приложение панели",
};

// Форматы P0 (§7) кнопки «Собрать формат» (§12.2 действия); тяжёлые
// форматы (PDF/XLSX/Parquet/ZIP) -- DOCLOG-5 (сервер ответит 400).
const BUILD_FORMATS: Array<{ format: string; label: string }> = [
  { format: "md", label: "Markdown" },
  { format: "html", label: "HTML" },
  { format: "json", label: "JSON" },
  { format: "jsonl", label: "JSONL" },
  { format: "csv", label: "CSV" },
];

type ListPhase = "loading" | "ready" | "empty" | "forbidden" | "offline";

type PreviewPhase = "idle" | "loading" | "ready" | "forbidden" | "conflict" | "error";

const JOB_STATE_LABELS: Record<string, string> = {
  queued: "В очереди (queued)",
  rendering: "Рендеринг (rendering)",
  ready: "Готово (ready)",
  failed: "Ошибка (failed)",
  cancelled: "Отменено (cancelled)",
};

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "—";
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

/** Upsert rendition в локальный список (идемпотентность AC09). */
function upsertRendition(
  previous: RenditionSummary[],
  next: RenditionSummary,
): RenditionSummary[] {
  const rest = previous.filter((item) => item.rendition_id !== next.rendition_id);
  return [...rest, next];
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU");
}

// ── Бейджи-области (§12.1) — полировка страницы «Документы» (следом за
// DOCLOG-4-UI-FIX), контракт пересмотрен постановкой тимлида ──
//
// БЕЙДЖ — это НЕ чип-заголовок, а ВСЯ область целиком: заголовок «Виды
// документов» + поле с границей вокруг него и списка документов (соседние
// области «Версии»/«Предпросмотр» — такие же бейджи). Следствия:
//   1. Заголовки h2 — ОБЫЧНЫЙ текст (чип-обёртка SECTION_BADGE_FRAME
//      устранена); шрифт заголовков НЕ меняется (text-sm font-semibold
//      text-neutral-900 dark:text-neutral-100 остаются на h2).
//   2. РАМКА и ФОН больших бейджей — по эталону бейджа «Знакомство с
//      платформой» (RouteCard главной страницы): border-brand/60 +
//      bg-brand-light/60 + скругление rounded-xl. Прежние нейтральные
//      рамка/фон (border-neutral-200 bg-white + dark:-ревизии) устранены.
//      Токены theme-adaptive (tailwind-preset → CSS-переменные): в тёмной
//      теме рамка → #4A4ED9/60, фон → #1E2034/60 — отдельные dark:
//      ревизии не требуются (контракт «имена классов не меняются —
//      меняются значения»).
//   3. Нижний инсет 24px (pb-6) — у ВСЕХ трёх бейджей, даже при
//      динамическом содержимом: класс стоит на самой области, поэтому
//      полоса фона под контентом сохраняется в любом состоянии (пустой
//      список, загрузка, таблица версий, предпросмотр). Состав полей
//      записан явными непересекающимися утилитами (px-*/pt-*/pb-*),
//      чтобы нижний инсет не зависел от порядка p-/pb- в CSS-выдаче.

interface DocumentationWorkspaceProps {
  runId?: string | null;
  initialKind?: string | null;
}

export function DocumentationWorkspace({
  runId,
  initialKind = null,
}: DocumentationWorkspaceProps) {
  const [listPhase, setListPhase] = useState<ListPhase>("loading");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [activeKind, setActiveKind] = useState<string | null>(initialKind);
  const [activeRevisionId, setActiveRevisionId] = useState<string | null>(null);
  const [previewPhase, setPreviewPhase] = useState<PreviewPhase>("idle");
  const [snapshot, setSnapshot] = useState<SnapshotPayload | null>(null);
  const [revision, setRevision] = useState<RevisionSummary | null>(null);
  const [renditions, setRenditions] = useState<RenditionSummary[]>([]);
  const [job, setJob] = useState<JobPayload | null>(null);
  const [creating, setCreating] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [viewMode, setViewMode] = useState<"brief" | "methodology" | "basis">("brief");
  const pollTimer = useRef<number | null>(null);

  // ── Список документов (чтение; НЕ создаёт документы, §12.1) ────────
  const loadDocuments = useCallback(async () => {
    if (!runId) {
      setListPhase("empty");
      return;
    }
    setListPhase("loading");
    const result = await listDocuments(runId);
    if (!result.ok) {
      // 403/404 -- безопасная причина без защищённого содержимого (§12.3);
      // null -- сеть/оффлайн: отдельное состояние, НЕ «нет документов».
      setListPhase(result.status === null ? "offline" : "forbidden");
      return;
    }
    const next = result.data?.documents ?? [];
    setDocuments(next);
    setListPhase(next.length === 0 ? "empty" : "ready");
    // Сохранённый выбор (§12.1 «последовательные панели ... сохранённым
    // выбором»): активный kind остаётся, если ещё существует.
    setActiveKind((current) => {
      if (current && next.some((document) => document.kind_code === current)) {
        return current;
      }
      return next.length > 0 ? next[0].kind_code : null;
    });
  }, [runId]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // ── Выбор версии -> metadata/preview (одно чтение, §12.2) ──────────
  const loadRevision = useCallback(async (revisionId: string) => {
    setPreviewPhase("loading");
    setJob(null);
    const result = await getRevision(revisionId);
    if (!result.ok) {
      if (result.status === 409) {
        setPreviewPhase("conflict");
      } else if (result.status === null) {
        setPreviewPhase("error");
      } else {
        setPreviewPhase("forbidden");
      }
      return;
    }
    setRevision(result.data?.revision ?? null);
    setSnapshot(result.data?.snapshot ?? null);
    setRenditions(result.data?.renditions ?? result.data?.revision?.renditions ?? []);
    setPreviewPhase("ready");
  }, []);

  useEffect(() => {
    if (!activeRevisionId) return;
    void loadRevision(activeRevisionId);
  }, [activeRevisionId, loadRevision]);

  // Активная версия: последняя (макс. version_no) активного вида.
  const activeDocument = useMemo(
    () => documents.find((document) => document.kind_code === activeKind) ?? null,
    [documents, activeKind],
  );

  useEffect(() => {
    if (!activeDocument || activeDocument.revisions.length === 0) {
      setActiveRevisionId(null);
      return;
    }
    const latest = activeDocument.revisions.reduce((acc, item) =>
      item.version_no > acc.version_no ? item : acc,
    );
    setActiveRevisionId((current) =>
      current && activeDocument.revisions.some((item) => item.revision_id === current)
        ? current
        : latest.revision_id,
    );
  }, [activeDocument]);

  // ── Job-поллинг (§17 status polling; SSE -- необязательное развитие) ─
  useEffect(() => {
    if (!job || (job.state !== "queued" && job.state !== "rendering")) {
      return;
    }
    pollTimer.current = window.setTimeout(async () => {
      const result = await getJob(job.job_id);
      if (result.ok && result.data) {
        setJob(result.data.job);
        if (
          result.data.job.state === "ready" &&
          result.data.job.rendition
        ) {
          // Rendition готова: пополняем список форматов версии из payload
          // (повторный клик дедупицируется бэкендом, AC09).
          setRenditions((previous) =>
            upsertRendition(previous, result.data!.job.rendition!),
          );
        }
      }
    }, 400);
    return () => {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [job, activeRevisionId]);

  const handleBuild = useCallback(
    async (format: string) => {
      if (!activeRevisionId) return;
      setJob(null);
      const result = await requestRendition(activeRevisionId, format);
      if (!result.ok) {
        if (result.status === 400) {
          // 400 unsupported_format -- честная ошибка формата (§17).
          setJob({
            job_id: "",
            run_id: "",
            snapshot_id: "",
            format,
            redaction_profile: "",
            revision_id: null,
            rendition_id: null,
            state: "failed",
            error_code: "unsupported_format",
            attempt: 0,
            created_at: "",
            updated_at: "",
            rendition: null,
          });
        }
        return;
      }
      const nextJob = result.data?.job ?? null;
      setJob(nextJob);
      // Rendition готова сразу (P0-форматы инлайн-быстры): пополняем
      // список форматов версии из payload задания (одно чтение).
      if (nextJob?.state === "ready" && nextJob.rendition) {
        setRenditions((previous) => upsertRendition(previous, nextJob.rendition!));
      }
    },
    [activeRevisionId],
  );

  const handleCancel = useCallback(async () => {
    if (!job || (job.state !== "queued" && job.state !== "rendering")) return;
    await cancelJob(job.job_id);
    const result = await getJob(job.job_id);
    if (result.ok && result.data) setJob(result.data.job);
  }, [job]);

  const handleCreateDraft = useCallback(async () => {
    if (!runId || !activeKind) return;
    setCreating(true);
    // «Создать черновик» (§12.2): явное решение аналитика -- новая
    // заморозка текущего состояния (refresh=true; авто-ключ сборщика
    // включает cutoff -- на неизменном состоянии вернётся прежний снимок).
    const result = await createDraft(runId, activeKind, { refresh: true });
    setCreating(false);
    if (result.ok) {
      await loadDocuments();
    }
  }, [runId, activeKind, loadDocuments]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, { documents: number; versions: number; incomplete: number }>();
    for (const code of KIND_CODES) counts.set(code, { documents: 0, versions: 0, incomplete: 0 });
    for (const document of documents) {
      const entry = counts.get(document.kind_code);
      if (!entry) continue;
      entry.documents += 1;
      entry.versions += document.revisions.length;
      entry.incomplete += document.revisions.filter(
        (item) => item.completeness_status === "partial",
      ).length;
    }
    return counts;
  }, [documents]);

  // ── Негативные состояния списка (§12.3) ─────────────────────────────
  const listStatus = (() => {
    if (listPhase === "loading") return "Загрузка документов…";
    if (listPhase === "offline")
      return "Сервис документирования недоступен — повторите попытку позже";
    if (listPhase === "forbidden")
      return "Доступ запрещён — документы этого исследования недоступны вашему субъекту";
    if (listPhase === "empty")
      return runId
        ? "Документов пока нет — соберите черновик нужного вида"
        : "Документов пока нет — запуски без документируемых операций не образуют документов";
    return null;
  })();

  return (
    <div
      data-testid="doclog4-workspace"
      className="flex flex-col gap-4 lg:flex-row lg:items-stretch"
      aria-label="Документы исследования"
    >
      {/* Область 1: этапы/виды документов (§12.1: 220-260px desktop).
          Бейдж = вся область: рамка/фон эталона RouteCard + pb-6.
          Маркер doclog4-badge — носитель scoped-ревизии тёмной темы
          (весь текст бейджа белый; globals.css, гвард doclog4-badge-dark). */}
      <nav
        data-testid="doclog4-kind-list"
        aria-label="Виды документов"
        className={`doclog4-badge hidden shrink-0 flex-col gap-1 rounded-xl border border-brand/60 bg-brand-light/60 px-3 pt-3 pb-6 lg:block lg:w-[240px]`}
      >
        <h2 className="mb-2 text-sm font-semibold text-neutral-900 dark:text-neutral-100">
          Виды документов
        </h2>
        {KIND_CODES.map((code) => {
          const counts = kindCounts.get(code) ?? { documents: 0, versions: 0, incomplete: 0 };
          const isActive = activeKind === code;
          return (
            <button
              key={code}
              type="button"
              data-testid={`doclog4-kind-${code}`}
              aria-current={isActive ? "true" : undefined}
              onClick={() => setActiveKind(code)}
              className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                isActive
                  ? "bg-brand font-medium text-white"
                  : "text-neutral-700 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
              }`}
            >
              <span>
                {KIND_TITLES[code]} <span className="text-xs opacity-70">({code})</span>
              </span>
              <span className="text-xs tabular-nums opacity-80">
                {counts.documents > 0 ? `${counts.documents}` : "—"}
                {counts.incomplete > 0 ? ` ⚠${counts.incomplete}` : ""}
              </span>
            </button>
          );
        })}
        {activeKind && (
          <button
            type="button"
            onClick={handleCreateDraft}
            disabled={creating || listPhase !== "ready"}
            className="mt-3 w-full rounded-lg border border-brand px-2 py-1.5 text-sm text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
          >
            {creating ? "Сборка черновика…" : "Создать черновик"}
          </button>
        )}
      </nav>

      {/* Область 2: список версий (§12.1: 300-360px desktop).
          Бейдж = вся область: рамка/фон эталона RouteCard + pb-6;
          маркер doclog4-badge — см. область 1. */}
      <section
        data-testid="doclog4-version-list"
        aria-label="Версии документа"
        className={`doclog4-badge hidden shrink-0 flex-col gap-2 rounded-xl border border-brand/60 bg-brand-light/60 px-3 pt-3 pb-6 lg:block lg:w-[320px]`}
      >
        <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
          {activeKind ? KIND_TITLES[activeKind] : "Версии"}
        </h2>
        <p role="status" data-testid="doclog4-status" className="text-xs text-neutral-500">
          {listStatus ?? ""}
        </p>
        {listPhase === "ready" && activeDocument && activeDocument.revisions.length > 0 && (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              Версии документа {activeDocument.title}
            </caption>
            <thead>
              <tr className="text-xs text-neutral-500">
                <th scope="col" className="py-1">Версия</th>
                <th scope="col" className="py-1">Дата</th>
                <th scope="col" className="py-1">Полнота</th>
                <th scope="col" className="py-1">Форматы</th>
              </tr>
            </thead>
            <tbody>
              {activeDocument.revisions.map((item) => (
                <tr key={item.revision_id} data-testid="doclog4-version-row">
                  <td className="py-1">
                    <button
                      type="button"
                      aria-current={activeRevisionId === item.revision_id ? "true" : undefined}
                      onClick={() => setActiveRevisionId(item.revision_id)}
                      className="rounded px-1 text-left font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                    >
                      v{item.version_no}
                    </button>
                  </td>
                  <td className="py-1 text-xs text-neutral-500">{formatDate(item.captured_at ?? item.created_at)}</td>
                  <td className="py-1 text-xs">
                    {item.completeness_status === "partial" ? (
                      <span className="text-amber-600">неполная (partial)</span>
                    ) : (
                      <span className="text-neutral-600">полная</span>
                    )}
                  </td>
                  <td className="py-1 text-xs text-neutral-500">
                    {item.renditions.length > 0
                      ? item.renditions.map((rendition) => rendition.format).join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {listPhase === "ready" && (!activeDocument || activeDocument.revisions.length === 0) && (
          <p className="text-sm text-neutral-500">
            Для этого вида документов ещё нет версий.
          </p>
        )}
      </section>

      {/* Область 3: предпросмотр (оставшееся пространство; fullscreen §12.1).
          Бейдж = вся область: рамка/фон эталона RouteCard + pb-6;
          маркер doclog4-badge — см. область 1. */}
      <section
        data-testid="doclog4-preview-pane"
        aria-label="Предпросмотр документа"
        className={`doclog4-badge flex min-w-0 flex-col gap-3 rounded-xl border border-brand/60 bg-brand-light/60 px-4 pt-4 pb-6 ${
          fullscreen ? "fixed inset-4 z-50 overflow-auto" : "lg:flex-1"
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            Предпросмотр
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            {(["brief", "methodology", "basis"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={viewMode === mode}
                onClick={() => setViewMode(mode)}
                className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-700 dark:text-neutral-300"
              >
                {mode === "brief" ? "Кратко" : mode === "methodology" ? "Методическое приложение" : "Основания"}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={fullscreen}
              onClick={() => setFullscreen((value) => !value)}
              className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-700 dark:text-neutral-300"
            >
              Во весь экран
            </button>
          </div>
        </div>

        {/* Отказы чтения версии (§12.3: безопасная причина; 409 -- перечитать) */}
        {previewPhase === "conflict" && (
          <p role="alert" className="text-sm text-amber-600">
            Состояние изменилось (409) — перечитайте список и выберите версию заново.
          </p>
        )}
        {previewPhase === "forbidden" && (
          <p role="alert" className="text-sm text-neutral-700">
            Доступ запрещён — защищённый предпросмотр недоступен вашему субъекту.
          </p>
        )}
        {previewPhase === "error" && (
          <p role="alert" className="text-sm text-neutral-700">
            Сервис документирования недоступен — повторите попытку позже.
          </p>
        )}

        {job && job.state === "failed" && (
          <p role="alert" data-testid="doclog4-job-error" className="text-sm text-red-600">
            Ошибка сборки формата {job.format}: {job.error_code ?? "render_failed"}
          </p>
        )}

        {previewPhase === "ready" && snapshot && revision && (
          <>
            {/* Шапка (§12.2): неизвестное явно «—»; partial -- текстом */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-neutral-600 md:grid-cols-3">
              <span>Снимок: <code className="font-mono">{snapshot.snapshot_id}</code></span>
              <span>Дата снимка: {formatDate(snapshot.captured_at)}</span>
              <span>Контекст: {snapshot.context_id ?? "—"}</span>
              <span>Ревизия данных: {snapshot.data_revision ?? "—"}</span>
              <span>
                Полнота:{" "}
                {snapshot.completeness.status === "partial" ? (
                  <span className="font-medium text-amber-600">неполная (partial)</span>
                ) : (
                  "полная (complete)"
                )}
              </span>
              <span>Воспроизводимость: {snapshot.reproducibility.status}</span>
            </div>

            {/* Gaps честны (§12.3: перечень gaps) */}
            {snapshot.completeness.missing_refs.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                Отсутствующие зависимости (gaps):
                <ul className="ml-4 list-disc">
                  {snapshot.completeness.missing_refs.map((ref) => (
                    <li key={ref}>
                      <code className="font-mono">{ref}</code>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Действия: собрать формат (§12.2); повторный клик дедупицируется
                бэкендом (AC09) */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-neutral-500">Собрать формат:</span>
              {BUILD_FORMATS.map(({ format, label }) => (
                <button
                  key={format}
                  type="button"
                  onClick={() => void handleBuild(format)}
                  className="rounded-full bg-neutral-100 px-3 py-1 text-xs text-neutral-700 hover:bg-neutral-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:bg-neutral-800 dark:text-neutral-200"
                >
                  {label}
                </button>
              ))}
              {job && (job.state === "queued" || job.state === "rendering") && (
                <button
                  type="button"
                  onClick={() => void handleCancel()}
                  className="rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600"
                >
                  Отменить
                </button>
              )}
            </div>

            {job && (
              <p
                role="status"
                data-testid="doclog4-job-state"
                className="text-xs text-neutral-600"
              >
                Задание {job.job_id ? `${job.job_id.slice(0, 12)}…` : ""}:{" "}
                {JOB_STATE_LABELS[job.state] ?? job.state}
                {job.attempt > 1 ? ` (попытка ${job.attempt})` : ""}
              </p>
            )}

            {/* Готовые форматы (§12.2 таблица «доступные форматы и размер») */}
            {renditions.filter((item) => item.state === "ready").length > 0 && (
              <ul className="flex flex-wrap gap-2 text-xs">
                {renditions
                  .filter((item) => item.state === "ready")
                  .map((item) => (
                    <li key={item.rendition_id}>
                      <a
                        data-testid="doclog4-rendition-link"
                        href={renditionContentUrl(item.rendition_id)}
                        className="rounded-full bg-brand/10 px-3 py-1 font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                      >
                        Скачать {item.format.toUpperCase()} ({formatBytes(item.size_bytes)})
                      </a>
                    </li>
                  ))}
              </ul>
            )}

            <DocumentPreview
              revisionId={revision.revision_id}
              snapshot={snapshot}
              viewMode={viewMode}
            />
          </>
        )}

        {previewPhase === "idle" && (
          <p className="text-sm text-neutral-500">
            Выберите версию документа для предпросмотра.
          </p>
        )}
        {previewPhase === "loading" && (
          <p className="text-sm text-neutral-500">Загрузка предпросмотра…</p>
        )}
      </section>
    </div>
  );
}
