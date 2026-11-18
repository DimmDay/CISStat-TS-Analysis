"use client";

// packages/ui/components/ForecastExportMenu.tsx
//
// Экспорт прогноза (spec_forecasting2.md §5.5; PGV-12 §10.1):
// - CSV/JSON -- прямые ссылки на backend-роуты (СОХРАНЕНЫ -- критерий
//   §13 «CSV/JSON/audit сохранены»; самодостаточный JSON);
// - PNG -- ОБЩИЙ печатный конвейер PGV (requestVisualExport, view
//   forecasting.forecast.chart): сериализация СВОЕГО chart-узла
//   (serializeChartSvgSafe -- не первый SVG документа, критерий §13)
//   -> freeze -> VisualPrintSnapshot/1 -> V01 revision -> PNG job
//   (202, готовый PNG -- в «Документах исследования → Визуализации»).
//   Legacy клиентский canvas-PNG УДАЛЁН (клиентский рендер из
//   первого SVG): до переезда путь не был архивным воспроизводимым
//   экспортом (§10.1); client-export audit (recordClientExport)
//   сохранён;
// - PDF сознательно не реализован (v1): отдельная постановка
//   (см. worklog Task FORECAST-1).

import { useCallback, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { exportUrl, recordClientExport } from "../lib/forecasting";
import {
  requestVisualExport,
  resolveCurrentRunForExport,
  visualExportErrorText,
} from "../lib/visualExports";
import { serializeChartSvgSafe } from "../lib/serializeChartSvg";

export function ForecastExportMenu({
  forecastId,
  chartContainerId,
  onExported,
}: {
  forecastId: string | null;
  chartContainerId: string;
  onExported?: (format: "csv" | "json" | "png") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedJobId, setQueuedJobId] = useState<string | null>(null);

  const savePng = useCallback(async () => {
    if (!forecastId) return;
    setBusy(true);
    setError(null);
    try {
      // 1) run_id -- единый источник слоя 1 (паритет VisualExportButton,
      //    resolveCurrentRun: GET /v1/progress/trace).
      const run = await resolveCurrentRunForExport();
      if (!run.ok || !run.data?.run_id) {
        throw new Error(
          run.status === null
            ? "Сеть недоступна — экспорт не выполнен."
            : "Исследование не выбрано — экспорт недоступен.",
        );
      }
      // 2) frozen геометрия СВОЕГО chart-узла (контейнер этого view --
      //    не первый SVG документа; null -- честный отказ до POST).
      const screenSvg = serializeChartSvgSafe(
        () => document.getElementById(chartContainerId),
      );
      if (!screenSvg) {
        throw new Error(
          "Печатная геометрия графика не приложена — разверните график и повторите.",
        );
      }
      // 3) общий pipeline: freeze -> snapshot -> V01 -> PNG job (202).
      //    Наука не запускается (AC06); CAS expected_context -- 409
      //    context_changed при смене данных (AC07).
      const outcome = await requestVisualExport({
        runId: run.data.run_id,
        viewId: "forecasting.forecast.chart",
        screenSvg,
        expectedContextId: run.data.context_id ?? null,
      });
      if (!outcome.ok || !outcome.data) {
        throw new Error(
          visualExportErrorText(outcome.status, outcome.error?.code ?? null),
        );
      }
      // Client-export audit события сохранён (§10.1/§13: audit не
      // удаляется при переезде на общий pipeline).
      await recordClientExport(forecastId, "png");
      setQueuedJobId(outcome.data.job.job_id);
      onExported?.("png");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка экспорта PNG");
    } finally {
      setBusy(false);
    }
  }, [forecastId, chartContainerId, onExported]);

  return (
    <div className="flex flex-col gap-1.5" data-testid="forecast-export-menu">
      <div className="grid grid-cols-3 gap-1.5">
        <a
          href={forecastId ? exportUrl(forecastId, "csv") : undefined}
          aria-disabled={!forecastId}
          onClick={(event) => {
            if (!forecastId) event.preventDefault();
            else onExported?.("csv");
          }}
          className={`flex items-center justify-center gap-1 rounded border px-2 py-1.5 text-[11px] ${
            forecastId
              ? "border-neutral-200 bg-white text-neutral-700 hover:border-brand hover:text-brand"
              : "pointer-events-none border-neutral-100 bg-neutral-50 text-neutral-300"
          }`}
          data-testid="export-csv"
        >
          <Download size={12} /> CSV
        </a>
        <a
          href={forecastId ? exportUrl(forecastId, "json") : undefined}
          aria-disabled={!forecastId}
          onClick={(event) => {
            if (!forecastId) event.preventDefault();
            else onExported?.("json");
          }}
          className={`flex items-center justify-center gap-1 rounded border px-2 py-1.5 text-[11px] ${
            forecastId
              ? "border-neutral-200 bg-white text-neutral-700 hover:border-brand hover:text-brand"
              : "pointer-events-none border-neutral-100 bg-neutral-50 text-neutral-300"
          }`}
          data-testid="export-json"
        >
          <Download size={12} /> JSON
        </a>
        <button
          type="button"
          onClick={() => void savePng()}
          disabled={!forecastId || busy}
          className={`flex items-center justify-center gap-1 rounded border px-2 py-1.5 text-[11px] ${
            queuedJobId
              ? "border-green-300 bg-green-50 text-green-800"
              : "border-neutral-200 bg-white text-neutral-700 hover:border-brand hover:text-brand"
          } disabled:border-neutral-100 disabled:bg-neutral-50 disabled:text-neutral-300`}
          data-testid="export-png"
          aria-label="Скачать PNG прогноза через печатный конвейер"
        >
          {busy ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Download size={12} />
          )}
          {queuedJobId ? "PNG в очереди" : "PNG"}
        </button>
      </div>
      {queuedJobId && (
        <p
          className="text-[10px] leading-snug text-neutral-500"
          role="status"
          data-testid="export-png-status"
        >
          Задание {queuedJobId}: готовый печатный PNG появится в «Документах
          исследования → Визуализации».
        </p>
      )}
      {error && (
        <p className="text-[10px] text-red-600" role="alert" data-testid="export-error">
          {error}
        </p>
      )}
      <p className="text-[10px] leading-snug text-neutral-400">
        JSON самодостаточен (прогноз + метрики + история) — подходит для отчёта и
        техподдержки. PNG — печатный конвейер платформы: заголовок, оси и
        подписи из frozen данных выпуска.
      </p>
    </div>
  );
}
