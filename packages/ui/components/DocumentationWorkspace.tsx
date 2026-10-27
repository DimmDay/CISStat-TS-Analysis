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
  decideApproval,
  getJob,
  getLifecycle,
  getRevision,
  getRevisionDiff,
  listDocuments,
  publishRevision,
  renditionContentUrl,
  requestApproval,
  requestRendition,
  resolveCurrentRun,
  retractRevision,
  revisionPreviewUrl,
  type DiffPayload,
  type DocumentSummary,
  type JobPayload,
  type LifecycleRecordPayload,
  type LifecycleState,
  type RenditionSummary,
  type RevisionSummary,
  type SnapshotPayload,
} from "../lib/documentation";
import { MonitoringComparisonPanel } from "./MonitoringComparisonPanel";
import { Doclog9ProfileControls } from "./Doclog9ProfileControls";

// Виды документов D01-D11 (спека §6/§12.2 «Левый список»; D10/D11 --
// DOCLOG-6 «Согласование и архив»); заголовки -- серверный реестр
// (DOCUMENT_KINDS), клиентский фолбэк -- по коду.
// DOCLOG-8 (§12.2 «Левый список»): D12 «Сверка прогноза с фактом» --
// плановая поставка DOCLOG-8; каталог экспортируется для UI-оракулов.
export const KIND_CODES = [
  "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11",
  "D12",
] as const;

export const KIND_TITLES: Record<string, string> = {
  D01: "План исследования",
  D02: "Паспорт источника",
  D03: "Протокол качества",
  D04: "Рецепт преобразований",
  D05: "Аналитическая записка",
  D06: "Протокол экспериментов",
  D07: "Карточка модели",
  D08: "Выпуск прогноза",
  D09: "Приложение панели",
  D10: "Рекомендации и ограничения",
  D11: "Итоговый отчёт",
  D12: "Сверка прогноза с фактом",
};

// Форматы кнопки «Собрать формат» (§12.2 действия). P0 -- синхронно;
// C09 (DOCLOG-E2E-RECHECK-1-FIX): к списку подключены реально
// поддержанные backend'ом тяжёлые форматы (DOCLOG-5: pdf/xlsx/parquet/zip
// -- рендер выполняет worker §18, POST ставит job в очередь; UI поллит
// состояние §17). SVG/PNG -- каталог DOCLOG-5 тоже поддерживает; общий
// селектор ограничен форматами акта C09 (pdf/xlsx/parquet/zip), чтобы
// панель действий оставалась компактной. DOCX/PDF-A -- НЕ здесь: выпуск
// только по организационному профилю (панель Doclog9ProfileControls).
// Зависимость от worker показана честной подписью рядом (акт C09:
// «показывать зависимость от профиля/валидатора/worker»).
const BUILD_FORMATS: Array<{ format: string; label: string; heavy?: boolean }> = [
  { format: "md", label: "Markdown" },
  { format: "html", label: "HTML" },
  { format: "json", label: "JSON" },
  { format: "jsonl", label: "JSONL" },
  { format: "csv", label: "CSV" },
  { format: "pdf", label: "PDF", heavy: true },
  { format: "xlsx", label: "XLSX", heavy: true },
  { format: "parquet", label: "Parquet", heavy: true },
  { format: "zip", label: "ZIP", heavy: true },
];

// H29/UIH (DOCLOG-H29-UIHONEST-AUDITVIEW, 2026-10-27): «environment-lost»
// -- честное состояние «run_id разрешён ЭТОЙ ЖЕ сессией (свежий trace),
// но список документов ответил 404 «запуск не найден»» -- класс S4/S5
// (run потерян средой при живой сессии после рестарта free-тира).
// Uniform-404 НЕ ослабляется (T1/R09): для deep-link/чужого run_id и
// 403 остаётся безальтернативное «Доступ запрещён»; отличие фразы --
// только по КОНТЕКСТУ получения run_id на клиенте (свой-resolved vs
// deep-link), существование чужих ресурсов не дисклоужается.
type ListPhase =
  | "loading"
  | "ready"
  | "empty"
  | "forbidden"
  | "offline"
  | "no-run"
  | "environment-lost";

type PreviewPhase = "idle" | "loading" | "ready" | "forbidden" | "conflict" | "error";

const JOB_STATE_LABELS: Record<string, string> = {
  queued: "В очереди (queued)",
  rendering: "Рендеринг (rendering)",
  ready: "Готово (ready)",
  failed: "Ошибка (failed)",
  cancelled: "Отменено (cancelled)",
};

// DOCLOG-6 (§11): состояния оси содержания -- текстовые метки (цвет НЕ
// единственный носитель, §12.3).
export const LIFECYCLE_STATE_LABELS: Record<string, string> = {
  draft: "Черновик (draft)",
  ready_for_review: "На согласовании (ready_for_review)",
  approved: "Согласовано (approved)",
  published: "Опубликовано (published)",
  rejected: "Отклонено (rejected)",
  retracted: "Отозвано (retracted)",
  superseded: "Заменено новой версией (superseded)",
};

const LIFECYCLE_EVENT_LABELS: Record<string, string> = {
  approval_requested: "Запрошено согласование",
  approved: "Согласовано",
  rejected: "Отклонено согласующим",
  published: "Опубликовано",
  retracted: "Отозвано",
  superseded: "Заменено новой версией",
};

/** Честный текст отказа создания черновика по HTTP-статусу (C07, §12.3):
 * видно аналитику, повтор не теряет выбранный вид. */
export function createErrorText(status: number | null): string {
  if (status === null)
    return "Сервис документирования недоступен — создание черновика не выполнено";
  if (status === 403) return "Создание черновика недоступно вашему субъекту";
  if (status === 404)
    return "Исследование не найдено или недоступно — черновик не создан";
  if (status === 409)
    return "Состояние исследования изменилось (409) — повторите создание выбранного вида";
  if (status === 422)
    return "Вид документа или запрос отклонены (422) — выберите вид и повторите";
  if (status === 503)
    return "Сервис документирования недоступен (503) — создание черновика не выполнено, повторите попытку позже";
  return `Создание черновика не выполнено (ошибка ${status ?? "сети"}) — повторите попытку позже`;
}

/** Честный текст отказа жизненного цикла по HTTP-статусу/коду (§12.3). */
export function lifecycleErrorText(status: number | null): string {
  if (status === null) return "Сервис документирования недоступен — действие не выполнено";
  if (status === 403)
    return "Недостаточно прав (insufficient_scope) — действие требует отдельного права согласования/публикации";
  if (status === 404) return "Документ не найден или недоступен";
  if (status === 409)
    return "Хэш снимка/утверждённых форм изменился после согласования (approval_not_applicable) — старое согласование не переносится; соберите формат заново и согласуйте повторно";
  if (status === 422) return "Операция недопустима в текущем состоянии ревизии";
  if (status === 503)
    return "Аудит недоступен — защищённое действие не выполнено (fail-closed)";
  return "Действие не выполнено — повторите попытку позже";
}

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

// Контекст получения run_id (H29/UIH):
//   "session" -- run_id разрешён той же cookie-сессией через свежий
//               GET /v1/progress/trace (кнопка «Документы» из активного
//               исследования/пункт меню);
//   "link"    -- run_id пришёл из deep-link ?run= (может указывать на
//               чужой ресурс -- только безальтернативный запрет);
//   null/проп -- контекст неизвестен: прежний контракт (forbidden).
export type RunIdSource = "link" | "session" | null;

interface DocumentationWorkspaceProps {
  runId?: string | null;
  runIdSource?: RunIdSource;
  initialKind?: string | null;
}

export function DocumentationWorkspace({
  runId,
  runIdSource = null,
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
  // C07 (DOCLOG-E2E-RECHECK-1-FIX): отказ явного создания черновика
  // ДОЛЖЕН быть виден аналитику (§12.3/AC17); выбор вида при повторе
  // не теряется.
  const [createError, setCreateError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  // DOCLOG-9 (§19 строка DOCLOG-9): формат выпуска по профилю
  // организации (docx/pdfa); null -- панель скрыта.
  const [profileFormat, setProfileFormat] = useState<"docx" | "pdfa" | null>(null);
  const [viewMode, setViewMode] = useState<"brief" | "methodology" | "basis">("brief");
  // DOCLOG-6: ось содержания (§11) -- история/действия/diff.
  const [lifecycleRecords, setLifecycleRecords] = useState<LifecycleRecordPayload[]>([]);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [lifecyclePending, setLifecyclePending] = useState(false);
  const [retractReason, setRetractReason] = useState("");
  const [diff, setDiff] = useState<DiffPayload | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);
  // H29/UIH: результат кнопки «Открыть текущее исследование» -- явное
  // переопределение run_id (null тоже честное значение -> no-run).
  // reopen !== null означает "источник -- session" (run разрешён свежим
  // trace той же сессии).
  const [reopenedRun, setReopenedRun] = useState<{ runId: string | null } | null>(
    null,
  );

  const effectiveRunId = reopenedRun !== null ? reopenedRun.runId : runId;
  const effectiveRunIdSource: RunIdSource =
    reopenedRun !== null ? "session" : runIdSource;

  // ── Список документов (чтение; НЕ создаёт документы, §12.1) ────────
  const loadDocuments = useCallback(async () => {
    if (!effectiveRunId) {
      // C01 (DOCLOG-E2E-RECHECK-1-FIX): отсутствие run -- отдельное
      setListPhase("no-run");
      return;
    }
    setListPhase("loading");
    const result = await listDocuments(effectiveRunId);
    if (!result.ok) {
      // H29/UIH (2026-10-27): run_id разрешён ЭТОЙ ЖЕ сессией (свежий
      // trace) и список ответил 404 «запуск не найден» -- это потеря
      // среды (класс S4/S5), а не запрет: честная фраза + кнопка
      // повторного открытия. uniform-404 не ослабляется: deep-link
      // ("link"), неизвестный контекст (null) и остальные статусы
      // (вкл. 403) -- прежняя безальтернативная фраза; сеть -- offline.
      if (result.status === 404 && effectiveRunIdSource === "session") {
        setListPhase("environment-lost");
        return;
      }
      // 403/404 -- безопасная причина без защищённого содержимого (§12.3);
      // null -- сеть/оффлайн: отдельное состояние, НЕ «нет документов».
      setListPhase(result.status === null ? "offline" : "forbidden");
      return;
    }
    const next = result.data?.documents ?? [];
    setDocuments(next);
    setListPhase(next.length === 0 ? "empty" : "ready");
    // C02 (DOCLOG-E2E-RECHECK-1-FIX): выбор вида НЕ сбрасывается успешным
    // ПУСТЫМ списком -- иначе deep-link initialKind и ручной выбор
    // терялись и первый документ было невозможно создать (акт §4 C02:
    // «после загрузки пустого списка выбор очищается»). На непустом
    // списке активный kind остаётся, если ещё существует, иначе --
    // первый существующий документ (прежнее поведение).
    setActiveKind((current) => {
      if (current && next.some((document) => document.kind_code === current)) {
        return current;
      }
      if (next.length === 0) {
        return current; // пустой реестр: выбор вида сохраняется
      }
      return next[0].kind_code;
    });
  }, [effectiveRunId, effectiveRunIdSource]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // ── H29/UIH: «Открыть текущее исследование» ────────────────────────
  // Кнопка состояния environment-lost: заново разрешает ТЕКУЩИЙ run той
  // же сессии (единый источник run_id слоя 1 -- GET /v1/progress/trace):
  //   run_id есть   -> список перечитывается для него (environment-lost
  //                    снимается успешным/честным ответом);
  //   run_id null   -> честное no-run (исследования в среде нет вовсе);
  //   сеть недоступна -> offline (не маскируется под запрет/потерю).
  const reopenCurrentRun = useCallback(async () => {
    setListPhase("loading");
    const result = await resolveCurrentRun();
    if (!result.ok) {
      setListPhase("offline");
      return;
    }
    const nextRun = result.data?.run_id ?? null;
    setReopenedRun({ runId: nextRun });
    // Если эффективный run/источник не изменились, identity loadDocuments
    // не изменится и effect не перезапустится -- перечитываем явно.
    if (nextRun !== null && nextRun === effectiveRunId && effectiveRunIdSource === "session") {
      void loadDocuments();
    }
  }, [effectiveRunId, effectiveRunIdSource, loadDocuments]);

  // ── Выбор версии -> metadata/preview (одно чтение, §12.2) ──────────
  const loadRevision = useCallback(async (revisionId: string) => {
    setPreviewPhase("loading");
    setJob(null);
    setDiff(null);
    setDiffError(null);
    setLifecycleError(null);
    setRetractReason("");
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
    // DOCLOG-6: история жизненного цикла выбранной версии (read-only,
    // §12.2 «История»; отказ не ломает предпросмотр -- честная подпись).
    const history = await getLifecycle(revisionId);
    if (history.ok && history.data) {
      setLifecycleRecords(history.data.records);
      setLifecycleError(null);
    } else {
      setLifecycleRecords([]);
      setLifecycleError(lifecycleErrorText(history.status));
    }
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
    setCreateError(null);
    // «Создать черновик» (§12.2): явное решение аналитика -- новая
    // заморозка текущего состояния (refresh=true; авто-ключ сборщика
    // включает cutoff -- на неизменном состоянии вернётся прежний снимок).
    const result = await createDraft(runId, activeKind, { refresh: true });
    setCreating(false);
    if (result.ok) {
      await loadDocuments();
      return;
    }
    // C07 (DOCLOG-E2E-RECHECK-1-FIX): отказ создания показывается
    // аналитику (§12.3/AC17); повтор не теряет выбранный вид.
    setCreateError(createErrorText(result.status));
  }, [runId, activeKind, loadDocuments]);

  // ── DOCLOG-6: действия жизненного цикла (§11/§12.2) ───────────────
  const runLifecycleAction = useCallback(
    async (
      action: () => Promise<
        | { ok: boolean; status: number | null }
        | { ok: true; status: number; data?: unknown }
      >,
    ) => {
      if (!activeRevisionId) return;
      setLifecyclePending(true);
      setLifecycleError(null);
      const result = await action();
      setLifecyclePending(false);
      if (!result.ok) {
        setLifecycleError(lifecycleErrorText(result.status));
        return;
      }
      // Успех: перечитываем версию + историю (сервер -- источник истины).
      await loadRevision(activeRevisionId);
    },
    [activeRevisionId, loadRevision],
  );

  const handleLifecycle = useCallback(
    async (kind: "request" | "approve" | "reject" | "publish") => {
      if (!activeRevisionId) return;
      const actions = {
        request: () => requestApproval(activeRevisionId),
        approve: () => decideApproval(activeRevisionId, "approve"),
        reject: () => decideApproval(activeRevisionId, "reject"),
        publish: () => publishRevision(activeRevisionId),
      } as const;
      await runLifecycleAction(actions[kind]);
    },
    [activeRevisionId, runLifecycleAction],
  );

  const handleRetract = useCallback(async () => {
    if (!activeRevisionId) return;
    await runLifecycleAction(() => retractRevision(activeRevisionId, retractReason));
  }, [activeRevisionId, retractReason, runLifecycleAction]);

  const handleDiff = useCallback(async () => {
    if (!activeRevisionId || !activeDocument) return;
    const previous = [...activeDocument.revisions]
      .filter((item) => item.version_no < (revision?.version_no ?? 0))
      .sort((a, b) => b.version_no - a.version_no)[0];
    if (!previous) return;
    setDiff(null);
    setDiffError(null);
    const result = await getRevisionDiff(activeRevisionId, previous.revision_id);
    if (result.ok && result.data) {
      setDiff(result.data);
    } else {
      setDiffError(lifecycleErrorText(result.status));
    }
  }, [activeDocument, activeRevisionId, revision]);

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
    if (listPhase === "environment-lost")
      return "Исследование недоступно в этой среде — возможно, потеряно после рестарта сервиса";
    if (listPhase === "empty")
      return "Документов пока нет — соберите черновик нужного вида";
    if (listPhase === "no-run")
      return "Исследование не выбрано — откройте раздел из исследования («Прогресс» → «Документы») или передайте ?run=…; это не пустой реестр активного датасета";
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
          (весь текст бейджа белый, специфичность правила (0,3,0) —
          удвоенный маркер; globals.css, гвард doclog4-badge-dark).
          FIX-4 п.3: hover строк темнеет (dark:hover:bg-black/30; прежний
          dark:hover:bg-neutral-800 = #E3E5EA — почти белая поверхность
          под белым текстом). */}
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
                  : "text-neutral-700 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-black/30"
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
            // C02 (DOCLOG-E2E-RECHECK-1-FIX): создание доступно и на
            // пустом реестре (empty = успешный пустой ответ при известном
            // run); запрещено только в загрузке/отказах/no-run.
            disabled={
              creating ||
              (listPhase !== "ready" && listPhase !== "empty")
            }
            title={
              listPhase === "empty"
                ? "Первый документ этого вида в исследовании"
                : undefined
            }
            className="mt-3 w-full rounded-lg border border-brand px-2 py-1.5 text-sm text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
          >
            {creating ? "Сборка черновика…" : "Создать черновик"}
          </button>
        )}
        {createError && (
          <p
            role="alert"
            data-testid="doclog4-create-error"
            className="text-xs text-red-600"
          >
            {createError}
          </p>
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
        className={`doclog4-badge flex min-w-0 flex-col gap-3 rounded-xl border border-brand/60 bg-brand-light/60 px-4 pt-3 pb-6 ${
          fullscreen ? "fixed inset-4 z-50 overflow-auto" : "lg:flex-1"
        }`}
      >
        {/* FIX-4 п.1: строка шапки items-start — заголовок по верху строки,
            как h2 бейджей 1/2 (паттерн: pt-3 + заголовок top-aligned);
            прежний items-center опускал h2 к центру высоких пилюль. */}
        <div className="flex flex-wrap items-start justify-between gap-2">
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
            {/* DOCLOG-DL-FIX-1 (2026-10-27): вариант C на ядре A --
                разведение действий доставки (разбор:
                docs/doclog_download_behavior_2026-10-27.md).
                Просмотр рендера -- САНИТИЗИРОВАННЫЙ preview-маршрут
                (GET /revisions/{id}/preview, inline + AC16) в новой
                вкладке: сценарий аналитика длинный, переход в той же
                вкладке убивал workspace. Это ПРОСМОТР, не скачивание,
                поэтому не content-маршрут: при attachment на нём
                target="_blank" дал бы скачивание в новой вкладке, а не
                просмотр. Скачивание -- ссылки «Скачать X» ниже: файл
                сохраняет Content-Disposition: attachment бэкенда
                (клиентские blob/target-хаки не дублируются). noopener
                noreferrer -- вкладка без reverse-tabnabbing. */}
            {previewPhase === "ready" && revision && (
              <a
                data-testid="doclog4-open-in-new-tab"
                href={revisionPreviewUrl(revision.revision_id)}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-700 dark:text-neutral-300"
              >
                Открыть в новой вкладке
              </a>
            )}
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

        {/* H29/UIH (DOCLOG-H29-UIHONEST-AUDITVIEW, 2026-10-27): честное
            состояние «исследование недоступно в этой среде» -- run_id
            разрешён ЭТОЙ ЖЕ сессией (свежий trace), но список ответил
            404 (класс S4/S5: run потерян после рестарта сервиса).
            Размещено в preview-панели -- единственной области, видимой
            на ВСЕХ экранах (список версий -- hidden lg:block).
            uniform-404 не ослабляется: для deep-link/чужого run
            состояние не возникает (см. маппинг loadDocuments). */}
        {listPhase === "environment-lost" && (
          <div
            role="alert"
            aria-label="Исследование недоступно в этой среде"
            data-testid="doclog4-environment-lost"
            className="rounded-lg border border-amber-300 px-3 py-2 text-sm text-amber-600 dark:border-amber-700/60"
          >
            <p>
              Исследование недоступно в этой среде — возможно, потеряно
              после рестарта сервиса. Это не запрет доступа: run_id был
              разрешён этой же сессией, но список документов ответил
              «запуск не найден».
            </p>
            <button
              type="button"
              data-testid="doclog4-reopen-current-run"
              onClick={() => void reopenCurrentRun()}
              className="mt-2 rounded-lg border border-brand px-3 py-1.5 text-sm text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
            >
              Открыть текущее исследование
            </button>
          </div>
        )}

        {job && job.state === "failed" && (
          <p role="alert" data-testid="doclog4-job-error" className="text-sm text-red-600">
            Ошибка сборки формата {job.format}: {job.error_code ?? "render_failed"}
          </p>
        )}

        {/* DOCLOG-8 (§6 D12): панель сверки прогноза с фактом -- для
            D12 читает frozen сверки run (без пересчёта); состояния
            §12.3 -- внутри панели. */}
        {activeKind === "D12" && previewPhase === "ready" && (
          <MonitoringComparisonPanel runId={effectiveRunId} />
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
                  className="rounded-full bg-neutral-100 px-3 py-1 text-xs text-neutral-700 hover:bg-neutral-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:bg-white/10 dark:text-neutral-200"
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
            {/* C09 (DOCLOG-E2E-RECHECK-1-FIX): честная зависимость тяжёлых
                форматов от worker'а (§18) -- формат не предлагается как
                мгновенный; готовность зависит от очереди и воркера. */}
            <p className="text-xs text-neutral-500">
              PDF, XLSX, Parquet и ZIP собираются worker&apos;ом (очередь
              заданий): готовность зависит от его работы и занятости
              очереди; Markdown/HTML/JSON/JSONL/CSV собираются сразу.
            </p>

            {/* DOCLOG-9 (§19 строка DOCLOG-9): выпуск DOCX/PDF-A -- ТОЛЬКО
                по организационному профилю (подтверждается валидатором и
                policy, не названием файла); панель выбора профиля.
                Повторный клик по активному формату скрывает панель. */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-neutral-500">Профиль организации:</span>
              {(["docx", "pdfa"] as const).map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  data-testid={`doclog9-profile-toggle-${fmt}`}
                  aria-pressed={profileFormat === fmt}
                  onClick={() => setProfileFormat(profileFormat === fmt ? null : fmt)}
                  className={`rounded-full px-3 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    profileFormat === fmt
                      ? "bg-brand/20 font-medium text-brand"
                      : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-white/10 dark:text-neutral-200"
                  }`}
                >
                  {fmt === "docx" ? "DOCX" : "PDF/A"}
                </button>
              ))}
            </div>
            {previewPhase === "ready" && profileFormat && (
              <Doclog9ProfileControls
                format={profileFormat}
                activeRevisionId={activeRevisionId}
              />
            )}

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

            {/* DOCLOG-6: панель жизненного цикла (§11/§12.2 действия:
                «запросить согласование, опубликовать/отозвать по праву»;
                отказ -- честный текст, состояние -- текстовая метка). */}
            <div
              data-testid="doclog6-lifecycle-panel"
              className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-700"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">
                  Жизненный цикл:{" "}
                  <span
                    data-testid="doclog6-lifecycle-state"
                    className="font-normal"
                  >
                    {LIFECYCLE_STATE_LABELS[revision.lifecycle_state ?? "draft"] ??
                      (revision.lifecycle_state ?? "draft")}
                  </span>
                </p>
                {activeDocument && activeDocument.revisions.length > 1 && (
                  <button
                    type="button"
                    data-testid="doclog6-diff-button"
                    onClick={() => void handleDiff()}
                    className="rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600"
                  >
                    Сравнить с предыдущей версией
                  </button>
                )}
              </div>

              {lifecycleError && (
                <p
                  role="alert"
                  data-testid="doclog6-lifecycle-error"
                  className="mt-2 text-xs text-red-600"
                >
                  {lifecycleError}
                </p>
              )}

              {/* Действия по состоянию (§11: draft -> ready_for_review ->
                  approved -> published; терминальные -- без действий) */}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {revision.lifecycle_state === "draft" && (
                  <button
                    type="button"
                    data-testid="doclog6-action-request"
                    disabled={lifecyclePending}
                    onClick={() => void handleLifecycle("request")}
                    className="rounded-full bg-brand/10 px-3 py-1 text-xs font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                  >
                    Запросить согласование
                  </button>
                )}
                {revision.lifecycle_state === "ready_for_review" && (
                  <>
                    <button
                      type="button"
                      data-testid="doclog6-action-approve"
                      disabled={lifecyclePending}
                      onClick={() => void handleLifecycle("approve")}
                      className="rounded-full bg-brand/10 px-3 py-1 text-xs font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                    >
                      Утвердить
                    </button>
                    <button
                      type="button"
                      data-testid="doclog6-action-reject"
                      disabled={lifecyclePending}
                      onClick={() => void handleLifecycle("reject")}
                      className="rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 dark:border-neutral-600"
                    >
                      Отклонить
                    </button>
                  </>
                )}
                {revision.lifecycle_state === "approved" && (
                  <button
                    type="button"
                    data-testid="doclog6-action-publish"
                    disabled={lifecyclePending}
                    onClick={() => void handleLifecycle("publish")}
                    className="rounded-full bg-brand/10 px-3 py-1 text-xs font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                  >
                    Опубликовать
                  </button>
                )}
                {revision.lifecycle_state === "published" && (
                  <>
                    <input
                      type="text"
                      data-testid="doclog6-retract-reason"
                      value={retractReason}
                      onChange={(event) => setRetractReason(event.target.value)}
                      placeholder="Причина отзыва"
                      className="w-48 rounded border border-neutral-300 px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600 dark:bg-transparent"
                    />
                    <button
                      type="button"
                      data-testid="doclog6-action-retract"
                      disabled={lifecyclePending}
                      onClick={() => void handleRetract()}
                      className="rounded-full border border-red-300 px-3 py-1 text-xs text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
                    >
                      Отозвать
                    </button>
                  </>
                )}
                {revision.lifecycle_state === "rejected" && (
                  <span className="text-xs text-neutral-500">
                    Ревизия отклонена — выпустите новую черновую версию
                    («Создать черновик»)
                  </span>
                )}
                {revision.lifecycle_state === "retracted" && (
                  <span className="text-xs text-neutral-500">
                    Ревизия отозвана (история сохранена); актуальная версия —
                    новая публикация
                  </span>
                )}
                {revision.lifecycle_state === "superseded" && (
                  <span className="text-xs text-neutral-500">
                    Ревизия заменена новой опубликованной версией (история
                    сохранена)
                  </span>
                )}
              </div>

              {/* Diff ревизий (§17: по замороженным данным, без пересчётов) */}
              {diff && (
                <div
                  data-testid="doclog6-diff-panel"
                  className="mt-3 rounded border border-neutral-200 p-2 text-xs dark:border-neutral-700"
                >
                  <p className="font-medium text-neutral-700 dark:text-neutral-200">
                    Различия с предыдущей версией (по замороженным снимкам,
                    без пересчётов):
                  </p>
                  <ul className="ml-4 mt-1 list-disc">
                    {Object.entries(diff.metadata).map(([field, change]) => (
                      <li key={field}>
                        <code className="font-mono">{field}</code>: изменено
                      </li>
                    ))}
                    {diff.claims.added.length > 0 && (
                      <li>Добавлено утверждений: {diff.claims.added.length}</li>
                    )}
                    {diff.claims.removed.length > 0 && (
                      <li>Убрано утверждений: {diff.claims.removed.length}</li>
                    )}
                    {diff.claims.validity_changed.length > 0 && (
                      <li>
                        Изменилась применимость: {diff.claims.validity_changed.length}
                      </li>
                    )}
                    {Object.keys(diff.metadata).length === 0 &&
                      diff.claims.added.length === 0 &&
                      diff.claims.removed.length === 0 &&
                      diff.claims.validity_changed.length === 0 && (
                        <li>Различий не обнаружено</li>
                      )}
                  </ul>
                </div>
              )}
              {diffError && (
                <p role="alert" className="mt-2 text-xs text-red-600">
                  {diffError}
                </p>
              )}

              {/* История (append-only, §12.2 «История») */}
              {lifecycleRecords.length > 0 && (
                <ul
                  data-testid="doclog6-lifecycle-history"
                  className="mt-2 space-y-1 text-xs text-neutral-600 dark:text-neutral-300"
                >
                  {lifecycleRecords.map((record) => (
                    <li key={record.record_id}>
                      {formatDate(record.created_at)} —{" "}
                      {LIFECYCLE_EVENT_LABELS[record.event] ?? record.event}
                      {record.reason ? `: ${record.reason}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
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
