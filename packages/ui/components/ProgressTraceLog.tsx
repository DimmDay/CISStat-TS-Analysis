"use client";

// packages/ui/components/ProgressTraceLog.tsx
//
// Развёрнутая трасса «Прогресса» (Task PROGR-4, spec_progress.md §6.2):
// плоский хронологический список trace_events -- то, что раньше показывал
// EventsLogDrawer, теперь здесь, с реальной персистентностью (слой 1
// PROGR-3 + ForecastRun.trace, слияние в lib/progress.ts). Фильтры по
// стадии и по узлу (§6.2: «с фильтром по стадии/узлу»); события уровня
// стадии (node_id=null) -- честная строка без узла.
//
// EventLogDrawer удаляется по §6.1: трасса занимает его нишу на бэкенде,
// персистентно, а не в эфемерном useState (§6.1).

import { useMemo, useState } from "react";
import { STAGE_DEFS } from "../lib/stages";
import {
  PROGRESS_STAGE_NODES,
  nodeLabel,
  sortEventsChronologically,
  stageLabel,
  type TraceEventInfo,
} from "../lib/progress";

function formatTime(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts; // битый ts -- как есть
  return date.toLocaleTimeString("ru-RU");
}

function formatPayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload ?? {});
  if (entries.length === 0) return "";
  return entries
    .map(([key, value]) => {
      const rendered =
        typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
      return `${key}: ${rendered}`;
    })
    .join(" · ");
}

export function ProgressTraceLog({ events }: { events: TraceEventInfo[] }) {
  const [stageFilter, setStageFilter] = useState("");
  const [nodeFilter, setNodeFilter] = useState("");

  const chronological = useMemo(() => sortEventsChronologically(events), [events]);

  const filtered = useMemo(
    () =>
      chronological.filter(
        (event) =>
          (!stageFilter || event.stage === stageFilter) &&
          (!nodeFilter || event.node_id === nodeFilter),
      ),
    [chronological, stageFilter, nodeFilter],
  );

  const nodeOptions = stageFilter ? PROGRESS_STAGE_NODES[stageFilter] ?? [] : [];

  return (
    <div className="px-4 pb-4">
      <div className="mb-2 flex items-center gap-2">
        <label className="text-xs text-neutral-500" htmlFor="progress-trace-stage">
          Стадия
        </label>
        <select
          id="progress-trace-stage"
          value={stageFilter}
          onChange={(e) => {
            setStageFilter(e.target.value);
            setNodeFilter(""); // смена стадии сбрасывает узел: узлы другой стадии
          }}
          className="rounded border border-neutral-200 px-2 py-1 text-xs text-neutral-700"
        >
          <option value="">Все стадии</option>
          {STAGE_DEFS.map((stage) => (
            <option key={stage.key} value={stage.key}>
              {stage.label}
            </option>
          ))}
        </select>

        <label className="text-xs text-neutral-500" htmlFor="progress-trace-node">
          Узел
        </label>
        <select
          id="progress-trace-node"
          value={nodeFilter}
          disabled={!stageFilter}
          onChange={(e) => setNodeFilter(e.target.value)}
          className="rounded border border-neutral-200 px-2 py-1 text-xs text-neutral-700 disabled:bg-neutral-50 disabled:text-neutral-400"
        >
          <option value="">Все узлы</option>
          {nodeOptions.map((nodeId) => (
            <option key={nodeId} value={nodeId}>
              {nodeLabel(stageFilter, nodeId)}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="py-2 text-sm text-neutral-500">Событий пока нет.</p>
      ) : (
        <ul role="log" aria-label="Трасса событий" className="divide-y divide-neutral-100">
          {filtered.map((event, index) => (
            <li key={event.event_id ?? `${event.ts}-${index}`} className="py-2 text-sm">
              <div className="flex items-baseline gap-2">
                <span className="shrink-0 text-xs text-neutral-400">{formatTime(event.ts)}</span>
                <span className="text-xs font-medium text-brand">{stageLabel(event.stage)}</span>
                {event.node_id && (
                  <span className="text-xs text-neutral-500">{nodeLabel(event.stage, event.node_id)}</span>
                )}
                <span className="ml-auto font-mono text-xs text-neutral-700">{event.event_type}</span>
              </div>
              {Object.keys(event.payload ?? {}).length > 0 && (
                <p className="mt-0.5 break-words text-xs text-neutral-600">
                  {formatPayload(event.payload)}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
