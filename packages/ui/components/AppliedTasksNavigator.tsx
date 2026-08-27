"use client";

import { useState } from "react";
import { BriefcaseBusiness, ListChecks, MapPin } from "lucide-react";
import {
  APPLIED_TASK_DOMAINS,
  APPLIED_TASK_KINDS,
  getAppliedTaskExamples,
  type AppliedTaskDomainId,
  type AppliedTaskKindId,
} from "../lib/applied-tasks";

export function AppliedTasksNavigator() {
  const [activeDomainId, setActiveDomainId] = useState<AppliedTaskDomainId>(
    APPLIED_TASK_DOMAINS[0].id,
  );
  const [activeKindId, setActiveKindId] = useState<AppliedTaskKindId>(
    APPLIED_TASK_KINDS[0].id,
  );
  const [activeExampleId, setActiveExampleId] = useState(
    getAppliedTaskExamples(APPLIED_TASK_DOMAINS[0].id, APPLIED_TASK_KINDS[0].id)[0].id,
  );

  const activeDomain =
    APPLIED_TASK_DOMAINS.find((domain) => domain.id === activeDomainId) ??
    APPLIED_TASK_DOMAINS[0];
  const activeKind =
    APPLIED_TASK_KINDS.find((kind) => kind.id === activeKindId) ?? APPLIED_TASK_KINDS[0];
  const activeExamples = getAppliedTaskExamples(activeDomain.id, activeKind.id);
  const activeExample =
    activeExamples.find((task) => task.id === activeExampleId) ?? activeExamples[0];

  const selectDomain = (domainId: AppliedTaskDomainId) => {
    const nextExamples = getAppliedTaskExamples(domainId, activeKind.id);
    setActiveDomainId(domainId);
    setActiveExampleId(nextExamples[0].id);
  };

  const selectKind = (kindId: AppliedTaskKindId) => {
    const nextExamples = getAppliedTaskExamples(activeDomain.id, kindId);
    setActiveKindId(kindId);
    setActiveExampleId(nextExamples[0].id);
  };

  return (
    <div className="flex flex-col xl:flex-row gap-6 xl:gap-[49px] mt-8">
      <aside className="w-full xl:w-60 shrink-0">
        <div className="flex items-center gap-2 mb-4">
          <MapPin size={16} className="text-brand" aria-hidden="true" />
          <h3 className="text-base font-semibold text-neutral-800">Предметная область</h3>
        </div>
        <div className="relative">
          <span
            className="absolute left-[13px] top-4 bottom-4 border-l-2 border-dashed border-neutral-200"
            aria-hidden="true"
          />
          <ol className="flex flex-col gap-1" aria-label="Предметные области">
            {APPLIED_TASK_DOMAINS.map((domain) => {
              const isActive = domain.id === activeDomain.id;
              return (
                <li key={domain.id}>
                  <button
                    type="button"
                    onClick={() => selectDomain(domain.id)}
                    aria-pressed={isActive}
                    className={`relative w-full flex items-start gap-2.5 rounded-lg px-2 py-2.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                      isActive ? "bg-brand-light" : "hover:bg-neutral-50"
                    }`}
                  >
                    <span
                      className={`relative z-10 mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${
                        isActive ? "border-brand bg-brand" : "border-neutral-400 bg-white"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="min-w-0">
                      <span
                        className={`block text-xs font-semibold leading-tight ${
                          isActive ? "text-brand" : "text-neutral-700"
                        }`}
                      >
                        {domain.label}
                      </span>
                      <span className="block mt-1 text-[10px] leading-tight text-neutral-400">
                        {domain.subtitle}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </aside>

      <aside className="w-full xl:w-80 shrink-0">
        <div className="flex items-center gap-2 mb-4">
          <ListChecks size={16} className="text-brand" aria-hidden="true" />
          <h3 className="text-base font-semibold text-neutral-800">Основная задача</h3>
        </div>
        <div className="space-y-2" role="group" aria-label="Основные задачи">
          {APPLIED_TASK_KINDS.map((kind) => {
            const isActive = kind.id === activeKind.id;
            return (
              <button
                key={kind.id}
                type="button"
                onClick={() => selectKind(kind.id)}
                aria-pressed={isActive}
                className={`w-full rounded-lg border p-3 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                  isActive
                    ? "border-brand bg-brand-light"
                    : "border-neutral-200 bg-white hover:bg-neutral-50"
                }`}
              >
                <span className="flex items-start gap-2">
                  <span
                    className={`mt-1 h-3 w-3 shrink-0 rounded-full border-2 ${
                      isActive ? "border-brand bg-brand" : "border-neutral-300"
                    }`}
                    aria-hidden="true"
                  />
                  <span>
                    <span className="block text-sm font-semibold text-neutral-800 leading-snug">
                      {kind.label}
                    </span>
                    <span className="block mt-1 text-xs text-neutral-500 leading-relaxed">
                      {kind.description}
                    </span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <BriefcaseBusiness size={16} className="text-brand" aria-hidden="true" />
          <h3 className="font-semibold text-neutral-900">Описание</h3>
        </div>
        <p className="text-xs text-neutral-500 mb-3">
          {activeDomain.label} · {activeKind.label}. Выберите прикладную задачу.
        </p>

        <div
          className="grid grid-cols-1 sm:grid-cols-2 gap-2"
          role="group"
          aria-label="Прикладные задачи"
        >
          {activeExamples.map((task) => {
            const isActive = task.id === activeExample.id;
            return (
              <button
                key={task.id}
                type="button"
                onClick={() => setActiveExampleId(task.id)}
                aria-pressed={isActive}
                aria-controls="applied-task-overview"
                className={`min-h-16 rounded-lg border px-3 py-2.5 text-left text-xs font-semibold leading-snug transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                  isActive
                    ? "border-brand bg-brand text-white"
                    : "border-brand/25 bg-brand-light/45 text-neutral-700 hover:border-brand/60 hover:bg-brand-light"
                }`}
              >
                {task.title}
              </button>
            );
          })}
        </div>

        <div id="applied-task-overview" className="mt-5" aria-live="polite">
          <h4 className="font-semibold text-neutral-900 mb-2">
            Обзор: {activeExample.title}
          </h4>
          <div className="rounded-lg border border-brand/15 bg-brand-light/45 px-4 py-4 min-h-[220px]">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                Что анализируется
              </p>
              <p className="mt-1 text-sm text-neutral-700 leading-relaxed">
                {activeExample.description}
              </p>
            </div>
            <div className="mt-4 pt-4 border-t border-brand/15">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                Результат для пользователя
              </p>
              <p className="mt-1 text-sm text-neutral-700 leading-relaxed">
                {activeExample.result}
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
