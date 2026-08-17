"use client";

// packages/ui/components/WorkbenchSummary.tsx
//
// Общий блок "С возвращением" -- рендерится на Home ОБОИХ приложений,
// когда в сессии есть активный датасет (sessions-aware Home, по решению
// тимлида: "если activeDataset существует -> Рабочий стол: где я
// остановился, какой этап, кнопка Продолжить"). Не копируется между
// embedded/standalone -- один компонент, разное обрамление в каждом
// приложении (см. EmbeddedHome.tsx и apps/standalone/components/StandaloneHome.tsx).

import Link from "next/link";
import { Check, Circle, ArrowRight } from "lucide-react";
import { STAGE_DEFS, StageStatus } from "../lib/stages";
import type { ActiveDataset } from "../context/AppShellContext";

interface WorkbenchSummaryProps {
  dataset: ActiveDataset;
  stages: Record<string, StageStatus>;
  lastActiveStage: string | null;
}

export function WorkbenchSummary({ dataset, stages, lastActiveStage }: WorkbenchSummaryProps) {
  const continueStage = STAGE_DEFS.find((s) => s.key === lastActiveStage) ?? STAGE_DEFS[0];

  return (
    <div className="bg-white rounded-lg border border-neutral-200 p-6">
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-1">С возвращением</p>
      <h2 className="text-lg font-semibold text-neutral-900 mb-4">
        📄 {dataset.name} · {dataset.rows.toLocaleString("ru-RU")} строк · {dataset.sizeLabel}
      </h2>

      <ol className="flex items-center gap-2 mb-5 flex-wrap">
        {STAGE_DEFS.map((stage, i) => {
          const status = stages[stage.key] ?? "pending";
          return (
            <li key={stage.key} className="flex items-center gap-2">
              <Link
                href={stage.href}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs border transition-colors ${
                  status === "done"
                    ? "bg-green-50 border-green-200 text-green-700"
                    : status === "in_progress"
                    ? "bg-brand-light border-brand text-brand font-medium"
                    : "bg-neutral-50 border-neutral-200 text-neutral-500 hover:border-neutral-300"
                }`}
              >
                {status === "done" ? (
                  <Check size={12} aria-hidden="true" />
                ) : (
                  <Circle size={10} aria-hidden="true" />
                )}
                {stage.label}
              </Link>
              {i < STAGE_DEFS.length - 1 && <span className="text-neutral-300">→</span>}
            </li>
          );
        })}
      </ol>

      <Link
        href={continueStage.href}
        className="inline-flex items-center gap-2 bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
      >
        Продолжить с «{continueStage.label}» <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </div>
  );
}
