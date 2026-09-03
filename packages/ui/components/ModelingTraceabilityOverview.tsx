"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, MinusCircle } from "lucide-react";
import { Metric } from "./Metric";
import type { ModelingContext, ModelingTraceNode, TraceabilityStatus } from "../lib/modeling";


const GROUPS = [
  { id: "validation", label: "Валидация" },
  { id: "preprocessing", label: "Предобработка" },
  { id: "eda", label: "EDA" },
] as const;

const STATUS = {
  done: { label: "Зафиксировано", className: "bg-green-50 text-green-700 border-green-200", icon: CheckCircle2 },
  warning: { label: "Требует внимания", className: "bg-amber-50 text-amber-700 border-amber-200", icon: AlertTriangle },
  skipped: { label: "Не требуется", className: "bg-neutral-100 text-neutral-600 border-neutral-200", icon: MinusCircle },
  pending: { label: "Не зафиксировано", className: "bg-blue-50 text-blue-700 border-blue-200", icon: Circle },
} satisfies Record<TraceabilityStatus, { label: string; className: string; icon: typeof Circle }>;


function TraceNode({ node }: { node: ModelingTraceNode }) {
  const config = STATUS[node.status];
  const Icon = config.icon;
  return (
    <article className="rounded-lg border border-neutral-200 bg-white p-3" data-testid="trace-node">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-neutral-800">{node.label}</h4>
          <p className="mt-1 text-[11px] text-neutral-500">{node.evidence}</p>
        </div>
        <span className={`shrink-0 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-medium ${config.className}`}>
          <Icon size={10} /> {config.label}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {node.modeling_inputs.map((item) => (
          <span key={item} className="rounded-full bg-brand-light px-2 py-0.5 text-[9px] text-neutral-700">{item}</span>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-[9px] text-neutral-400">
        <span>{node.source_endpoint}</span>
        {node.blocking && <span className="font-semibold text-red-600">Блокирует переход</span>}
      </div>
    </article>
  );
}


export function ModelingTraceabilityOverview({ context }: { context: ModelingContext }) {
  const [group, setGroup] = useState<ModelingTraceNode["group"]>("validation");
  const nodes = context.traceability.nodes.filter((item) => item.group === group);
  const summary = context.traceability.summary;
  return (
    <section className="flex h-[468px] min-h-0 flex-col" data-testid="modeling-traceability-overview">
      <div className="shrink-0">
        <div className="grid grid-cols-4 gap-2">
          <Metric label="Трасса" value={`${summary.total} источников`} />
          <Metric label="Зафиксировано" value={String(summary.done)} />
          <Metric label="Внимание" value={String(summary.warning)} />
          <Metric label="Блокеры" value={String(summary.blocking)} />
        </div>
        <div className="my-3 flex flex-wrap gap-2">
          {GROUPS.map((item) => (
            <button key={item.id} type="button" onClick={() => setGroup(item.id)}
              className={`rounded-full border px-3 py-1 text-xs ${group === item.id ? "border-brand bg-brand text-white" : "border-neutral-200 bg-neutral-100 text-neutral-700"}`}>
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1 feed-scroll">
        {nodes.map((node) => <TraceNode key={`${node.group}:${node.source_id}`} node={node} />)}
      </div>
    </section>
  );
}
