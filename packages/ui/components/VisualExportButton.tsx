"use client";

// packages/ui/components/VisualExportButton.tsx
//
// PGV-10 (spec_passport_graphics_visual.md §10.1/§13, строка PGV-10):
// общее действие «Скачать PNG» научной визуализации остановок
// upload/validation/preprocessing (§10.1 «В action bar — «Скачать PNG»
// с accessible названием вида»).
//
// Честные состояния (§10.1 «Unavailable/loading имеет причину»):
//   idle -> queued  : PNG поставлен в очередь (V01 в «Документах
//                     исследования → Визуализации» — переход между
//                     модулями job не теряет);
//   idle -> error   : человеческая причина отказа (409 context_changed,
//                     source_unavailable, screen_svg_required, ...);
//   disabled+reason : view без frozen результата (export_ready=false).

import { useCallback, useRef, useState } from "react";
import {
  requestVisualExport,
  resolveCurrentRunForExport,
  visualExportErrorText,
} from "../lib/visualExports";
import { serializeChartSvgSafe } from "../lib/serializeChartSvg";

export interface VisualExportButtonProps {
  /** view_id реестра PGV-00 (pgv-03 research view трёх остановок). */
  viewId: string;
  /** Accessible название вида (§10.1). */
  label?: string;
  /**
   * Сериализатор frozen геометрии ЭТОГО view (serializeChartSvgSafe
   * над ref-ом СВОЕГО chart-контейнера). Для таблиц/карточек не
   * передаётся -- контент печатается из frozen data.
   */
  getScreenSvg?: () => string | null;
  /** view без frozen результата (visual-sources export_ready=false). */
  disabled?: boolean;
  /** Честная причина disabled (показывается в title/рядом). */
  disabledReason?: string | null;
  /** Компактный вариант (в шапке Обзора). */
  compact?: boolean;
}

type Phase =
  | { kind: "idle" }
  | { kind: "queued"; jobId: string }
  | { kind: "error"; message: string };

export function VisualExportButton({
  viewId,
  label = "Скачать PNG",
  getScreenSvg,
  disabled = false,
  disabledReason = null,
  compact = false,
}: VisualExportButtonProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  const onClick = useCallback(async () => {
    if (phase.kind === "queued") return;
    setPhase({ kind: "idle" });
    // 1) run_id -- единый источник слоя 1 (паритет resolveCurrentRun).
    const run = await resolveCurrentRunForExport();
    if (!run.ok || !run.data?.run_id) {
      setPhase({
        kind: "error",
        message:
          run.status === null
            ? "Сеть недоступна — экспорт не выполнен."
            : "Исследование не выбрано — экспорт недоступен.",
      });
      return;
    }
    // 2) frozen геометрия СВОЕГО chart-узла (не первый SVG документа).
    const screenSvg = getScreenSvg ? getScreenSvg() : null;
    if (getScreenSvg && !screenSvg) {
      setPhase({
        kind: "error",
        message:
          "Печатная геометрия графика не приложена — разверните график и повторите.",
      });
      return;
    }
    // 3) POST /visuals: freeze -> snapshot -> V01 -> PNG job (202).
    const outcome = await requestVisualExport({
      runId: run.data.run_id,
      viewId,
      screenSvg,
      expectedContextId: run.data.context_id ?? null,
    });
    if (!outcome.ok || !outcome.data) {
      setPhase({
        kind: "error",
        message: visualExportErrorText(outcome.status, outcome.error?.code ?? null),
      });
      return;
    }
    setPhase({ kind: "queued", jobId: outcome.data.job.job_id });
  }, [phase.kind, getScreenSvg, viewId]);

  const isQueued = phase.kind === "queued";
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled || isQueued}
        data-testid={`visual-export-${viewId}`}
        data-export-state={isQueued ? "queued" : phase.kind === "error" ? "error" : "idle"}
        title={
          disabled
            ? (disabledReason ?? "Экспорт недоступен")
            : `Экспорт печатного PNG: ${label}`
        }
        aria-label={`Скачать PNG: ${label}`}
        className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-colors ${
          disabled
            ? "cursor-not-allowed border-neutral-200 bg-neutral-50 text-neutral-400"
            : isQueued
              ? "border-green-300 bg-green-50 text-green-800"
              : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-100"
        } ${compact ? "text-[11px] px-2 py-0.5" : ""}`}
      >
        {isQueued ? "PNG в очереди" : label}
      </button>
      {phase.kind === "error" && (
        <span role="alert" data-testid={`visual-export-error-${viewId}`} className="text-[11px] text-red-700">
          {phase.message}
        </span>
      )}
      {phase.kind === "queued" && (
        <span role="status" data-testid={`visual-export-status-${viewId}`} className="text-[11px] text-neutral-500">
          Задание {phase.jobId}: готовый PNG появится в «Документах исследования → Визуализации».
        </span>
      )}
      {disabled && disabledReason && (
        <span data-testid={`visual-export-disabled-reason-${viewId}`} className="text-[11px] text-neutral-400">
          {disabledReason}
        </span>
      )}
    </span>
  );
}

/**
 * Скоуп chart-ячейки для остановок с инлайн-графиками (TsAnalysisUpload):
 * ref на СВОЙ контейнер + кнопка «Скачать PNG» — сериализуется геометрия
 * ЭТОГО вида, не первый SVG документа (критерий §13).
 */
export function VisualExportChartScope({
  viewId,
  label,
  children,
  className = "",
}: {
  viewId: string;
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div className={`flex min-h-0 flex-col gap-1 ${className}`} data-testid={`export-chart-scope-${viewId}`}>
      <div ref={ref} className="min-h-0">
        {children}
      </div>
      <VisualExportButton
        viewId={viewId}
        label={`Скачать PNG: ${label}`}
        compact
        getScreenSvg={() => serializeChartSvgSafe(() => ref.current)}
      />
    </div>
  );
}
