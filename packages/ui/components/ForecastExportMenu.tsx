"use client";

// packages/ui/components/ForecastExportMenu.tsx
//
// Экспорт прогноза (spec_forecasting2.md §5.5):
// - CSV/JSON -- прямые ссылки на backend-роуты (самодостаточный JSON);
// - PNG -- клиентская сериализация отрисованного <svg> (XMLSerializer ->
//   canvas -> toBlob), без новых зависимостей и без backend-рендеринга;
// - PDF сознательно не реализован (v1): jsPDF не содержит кириллических
//   шрифтов -- PDF без встраивания шрифта (~200+ КБ) нечитаем; отдельная
//   постановка (см. worklog Task FORECAST-1).

import { useCallback, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { exportUrl, recordClientExport } from "../lib/forecasting";
import { resolveSvgVarsLight } from "../lib/chartVars";

const SVG_NS = "http://www.w3.org/2000/svg";

export async function downloadChartPng(container: HTMLElement, fileName: string): Promise<void> {
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("График не отрисован: SVG не найден");
  const clone = svg.cloneNode(true) as SVGSVGElement;
  // Task DKT-3 §6.4: резолв var() в клоне ДО сериализации — сериализованный
  // SVG теряет контекст стилей документа и var() не разрешается. Артефакт
  // «всегда светлый» (решение по §10.1 — рекомендация спеки): светлая карта
  // независимо от темы просмотра.
  const resolved = resolveSvgVarsLight(clone);
  resolved.setAttribute("xmlns", SVG_NS);
  const bbox = svg.getBoundingClientRect();
  const width = Math.max(1, Math.ceil(bbox.width));
  const height = Math.max(1, Math.ceil(bbox.height));
  resolved.setAttribute("width", String(width));
  resolved.setAttribute("height", String(height));
  const serialized = new XMLSerializer().serializeToString(resolved);
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialized)}`;
  const image = new Image();
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("Сериализация SVG в изображение не удалась"));
    image.src = dataUrl;
  });
  const canvas = document.createElement("canvas");
  const scale = 2; // ретина-качество
  canvas.width = width * scale;
  canvas.height = height * scale;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas 2D недоступен");
  context.fillStyle = "#FFFFFF";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("PNG-блоб не создан");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(link.href);
}

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

  const savePng = useCallback(async () => {
    if (!forecastId) return;
    setBusy(true);
    setError(null);
    try {
      const container = document.getElementById(chartContainerId);
      if (!container) throw new Error("Контейнер графика не найден");
      await downloadChartPng(container, `forecast_${forecastId.slice(0, 8)}.png`);
      await recordClientExport(forecastId, "png");
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
          className="flex items-center justify-center gap-1 rounded border border-neutral-200 bg-white px-2 py-1.5 text-[11px] text-neutral-700 hover:border-brand hover:text-brand disabled:border-neutral-100 disabled:bg-neutral-50 disabled:text-neutral-300"
          data-testid="export-png"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} PNG
        </button>
      </div>
      {error && (
        <p className="text-[10px] text-red-600" role="alert" data-testid="export-error">
          {error}
        </p>
      )}
      <p className="text-[10px] leading-snug text-neutral-400">
        JSON самодостаточен (прогноз + метрики + история) — подходит для отчёта и
        техподдержки. PNG рендерится браузером из графика.
      </p>
    </div>
  );
}
