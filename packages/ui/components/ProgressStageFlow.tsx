"use client";

// packages/ui/components/ProgressStageFlow.tsx
//
// Блок-схема 6 стадий «Прогресса» (Task PROGR-4, spec_progress.md §6.2):
// карточки стадий с лёгким цветным фоном по свёртке §12 п.10
// (bg-green-50 «пройдено» / bg-amber-50 «в работе или есть замечания» /
// нейтральный «не начато» -- то же семантическое сопоставление цветов,
// что у StatusIcon.tsx, применённое к фону карточки), иконка статуса
// (StatusIcon переиспользуется как есть) и краткая подпись
// («3/10, найдены проблемы» / «6/10, в работе» / «не начато»).
//
// Разворачивание стадии -- список узлов с их статусом; клик по узлу --
// deep-link на вкладку стадии (§6.2: «не дублирует UI остановки внутри
// панели»), поэтому узел -- ссылка, а не кнопка. Статусы узлов выводятся
// из фактов трассы (§4.1) -- см. lib/progress.ts; схема сеткой колонок,
// а не в ряд: 40rem-панель («или колонкой, если панель узкая -- деталь
// адаптива», §6.2).

import { useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { STAGE_DEFS } from "../lib/stages";
import {
  PROGRESS_STAGE_NODES,
  deriveNodeStatuses,
  nodeLabel,
  stageSummary,
  type FoldVisualState,
  type TraceEventInfo,
} from "../lib/progress";

// Свёртка карточки -> иконка StatusIcon (§6.2: «иконкой статуса,
// переиспользуется как есть»): жёлтая карточка схлопывает «в работе» и
// «есть замечания» в одно состояние (§3) -- конкретика видна в подписи
// и при разворачивании узлов.
const FOLD_ICON: Record<FoldVisualState, CheckStatus> = {
  passed: "done",
  attention: "warning",
  not_started: "pending",
};

// in_progress (StageStatus процессных стадий) иконкой = running;
// из трассы не возникает (только done), оставлено для полноты типа.
const NODE_ICON: Record<string, CheckStatus> = {
  done: "done",
  warning: "warning",
  error: "error",
  running: "running",
  in_progress: "running",
  skipped: "skipped",
  pending: "pending",
};

const FOLD_BG: Record<FoldVisualState, string> = {
  passed: "bg-green-50",
  attention: "bg-amber-50",
  not_started: "bg-white",
};

export function ProgressStageFlow({ events }: { events: TraceEventInfo[] }) {
  const statuses = useMemo(() => deriveNodeStatuses(events), [events]);
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  return (
    <div className="grid grid-cols-2 gap-2 px-4 py-3">
      {STAGE_DEFS.map(({ key, label, href }) => {
        const summary = stageSummary(key, statuses);
        const expanded = expandedStage === key;
        return (
          <div key={key} className="min-w-0">
            <button
              type="button"
              onClick={() => setExpandedStage(expanded ? null : key)}
              aria-expanded={expanded}
              aria-label={`Стадия ${label}`}
              className={`w-full rounded-lg border border-neutral-200 p-2.5 text-left transition-colors hover:border-neutral-300 ${FOLD_BG[summary.fold]}`}
            >
              <div className="flex items-center gap-1.5">
                <StatusIcon status={FOLD_ICON[summary.fold]} size={16} />
                <span className="truncate text-sm font-medium text-neutral-800">{label}</span>
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={`ml-auto shrink-0 text-neutral-400 transition-transform ${expanded ? "rotate-180" : ""}`}
                />
              </div>
              <p className="mt-1 text-xs text-neutral-600">{summary.text}</p>
            </button>

            {expanded && (
              <ul className="mt-1 divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
                {(PROGRESS_STAGE_NODES[key] ?? []).map((nodeId) => (
                  <li key={nodeId}>
                    <Link
                      href={href}
                      className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-neutral-700 hover:bg-neutral-50"
                    >
                      <StatusIcon
                        status={NODE_ICON[statuses[`${key}/${nodeId}`] ?? "pending"] ?? "pending"}
                        size={14}
                      />
                      <span className="truncate">{nodeLabel(key, nodeId)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
