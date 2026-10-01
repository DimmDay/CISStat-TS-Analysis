"use client";

// packages/ui/components/ProgressStageFlow.tsx
//
// Блок-схема 6 стадий «Прогресс» (Task PROGR-4, spec_progress.md §6.2):
// карточки стадий с лёгким цветным фоном по свёртке §12 п.10
// (bg-green-50 «пройдено» / bg-amber-50 «в работе или есть замечания» /
// нейтральный «не начато» -- то же семантическое сопоставление цветов,
// что у StatusIcon.tsx, применённое к фону карточки), иконка статуса
// (StatusIcon переиспользуется как есть) и краткая подпись
// («3/10, найдены проблемы» / «6/10, в работе» / «не начато»).
//
// Разворачивание стадии -- список узлов с их статусом; клик по узлу --
// deep-link на вкладку стадии (§6.2: «не дублирует UI остановки внутри
// панели»), поэтому узел -- ссылка, а не кнопка.
//
// PROGR-10 (Расхождение №1): компонент РЕНДЕРИТ готовое состояние
// (props {statuses, stages} -- ответ /trace), не вычисляет: вывод
// статусов и свёртка §12 п.10 -- единый движок бэкенда
// (app/core/node_status.py). Стадия, отсутствующая в ответе (сеть/
// старый бэкенд), честно «не начато» из реестра узлов, без подстановки
// фейковых фактов. Схема сеткой колонок, а не в ряд: 40rem-панель
// («или колонкой, если панель узкая -- деталь адаптива», §6.2).
//
// PROGR-11: полный узел §3 -- props.nodes (зеркала PipelineNodeState)
// доставляют бейдж-число (summary_count), режим проверки (mode --
// авто/вкл/выкл) и причину статуса (status_reason второй строкой);
// поля аддитивны -- старый бэкенд без nodes рендерится как прежде.

import { useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { STAGE_DEFS } from "../lib/stages";
import {
  FOLD_NOT_STARTED,
  PROGRESS_STAGE_NODES,
  nodeLabel,
  nodeModeLabel,
  nodeStateKey,
  nodeStateMap,
  stageStateText,
  type FoldVisualState,
  type NodeStateInfo,
  type StageStateInfo,
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

export interface ProgressStageFlowProps {
  /** Готовая карта статусов узлов "stage/node_id" (node_statuses ответа
   * /trace; единый движок app/core/node_status.py). */
  statuses: Record<string, string>;
  /** Готовые свёртки стадий §12 п.10 + счётчики (stages ответа /trace). */
  stages: StageStateInfo[];
  /** Полные состояния узлов §3 (nodes ответа /trace, PROGR-11):
   * бейдж-число, режим проверки, причина статуса. Аддитивно: старый
   * бэкенд без nodes -- рендер как прежде (N-3). */
  nodes?: NodeStateInfo[];
}

export function ProgressStageFlow({ statuses, stages, nodes }: ProgressStageFlowProps) {
  const [expandedStage, setExpandedStage] = useState<string | null>(null);
  // Полные состояния узлов §3 -- карта для рендера по узлам; ответ без
  // nodes (старый бэкенд) -- пустая карта, рендер как прежде.
  const nodeStates = nodeStateMap(nodes ?? []);

  return (
    <div className="grid grid-cols-2 gap-2 px-4 py-3">
      {STAGE_DEFS.map(({ key, label, href }) => {
        // Стадия, отсутствующая в ответе (сеть/старый бэкенд) -- честное
        // «не начато» из реестра узлов, не выдуманное состояние.
        const state: StageStateInfo =
          stages.find((s) => s.stage === key) ?? {
            stage: key,
            fold: FOLD_NOT_STARTED,
            done_count: 0,
            warning_nodes: 0,
            total_nodes: (PROGRESS_STAGE_NODES[key] ?? []).length,
          };
        const summaryText = stageStateText(state);
        const expanded = expandedStage === key;
        return (
          <div key={key} className="min-w-0">
            <button
              type="button"
              onClick={() => setExpandedStage(expanded ? null : key)}
              aria-expanded={expanded}
              aria-label={`Стадия ${label}`}
              className={`w-full rounded-lg border border-neutral-200 p-2.5 text-left transition-colors hover:border-neutral-300 ${FOLD_BG[state.fold]}`}
            >
              <div className="flex items-center gap-1.5">
                <StatusIcon status={FOLD_ICON[state.fold]} size={16} />
                <span className="truncate text-sm font-medium text-neutral-800">{label}</span>
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={`ml-auto shrink-0 text-neutral-400 transition-transform ${expanded ? "rotate-180" : ""}`}
                />
              </div>
              <p className="mt-1 text-xs text-neutral-600">{summaryText}</p>
            </button>

            {expanded && (
              <ul className="mt-1 divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
                {(PROGRESS_STAGE_NODES[key] ?? []).map((nodeId) => {
                  // Полное состояние узла §3 (PROGR-11); без фактов --
                  // прежний рендер: иконка статуса + метка.
                  const nodeState = nodeStates[nodeStateKey(key, nodeId)];
                  return (
                    <li key={nodeId}>
                      <Link
                        href={href}
                        className="block px-2.5 py-1.5 text-xs text-neutral-700 hover:bg-neutral-50"
                      >
                        <span className="flex items-center gap-2">
                          <StatusIcon
                            status={NODE_ICON[statuses[`${key}/${nodeId}`] ?? "pending"] ?? "pending"}
                            size={14}
                          />
                          <span className="min-w-0 flex-1 truncate">{nodeLabel(key, nodeId)}</span>
                          {nodeState?.mode != null && (
                            <span
                              data-testid={`node-mode-${key}-${nodeId}`}
                              className="shrink-0 rounded-full border border-neutral-200 px-1.5 py-px text-[10px] leading-none text-neutral-500"
                            >
                              {nodeModeLabel(nodeState.mode)}
                            </span>
                          )}
                          {nodeState?.summary_count != null && (
                            <span
                              data-testid={`node-badge-${key}-${nodeId}`}
                              title={nodeState.status_reason ?? undefined}
                              className="shrink-0 rounded bg-neutral-100 px-1.5 py-px text-[10px] leading-none tabular-nums text-neutral-700"
                            >
                              {nodeState.summary_count}
                            </span>
                          )}
                        </span>
                        {nodeState?.status_reason != null && (
                          <span className="mt-0.5 block pl-[22px] text-[11px] leading-tight text-neutral-500">
                            {nodeState.status_reason}
                          </span>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
