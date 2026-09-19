"use client";

// packages/ui/components/education/LibrarySection.tsx
//
// Task EDU-1 — секция «Библиотека» хаба «Обучение и база знаний»:
// фильтр по этапам пайплайна (пилли по паттерну ModuleNav) + сетка
// карточек статей (DNA HomeHero/RouteCard/TasksHub: grid-cols-1 sm:2 lg:3,
// gap-5). Карточка — кнопка: клик открывает панель чтения.
//
// Контент НЕ хардкодится: секция рендерит то, что пришло через пропы
// из слоя знаний (единый источник истины, spec_education.md Часть I).

import { BookOpen, Clock } from "lucide-react";
import type { KnowledgeArticle, KnowledgeStageId } from "../../lib/knowledge/types";
import {
  DIRECTION_LABELS_RU,
  KNOWLEDGE_STAGES,
  STAGE_ICONS,
  STAGE_LABELS_RU,
} from "../../lib/knowledge/types";

export type StageFilter = KnowledgeStageId | "all";

const STAGE_FILTER_PILL =
  "inline-flex h-8 items-center justify-center whitespace-nowrap rounded-full px-3.5 text-[13px] transition-colors";

function stageFilterClass(active: boolean) {
  return active
    ? `${STAGE_FILTER_PILL} bg-brand font-medium text-white`
    : `${STAGE_FILTER_PILL} bg-neutral-100 text-neutral-700 hover:bg-neutral-200 hover:text-neutral-900`;
}

export function LibrarySection({
  articles,
  stageFilter,
  onStageFilterChange,
  onOpenArticle,
}: {
  articles: KnowledgeArticle[];
  stageFilter: StageFilter;
  onStageFilterChange: (filter: StageFilter) => void;
  onOpenArticle: (articleId: string) => void;
}) {
  return (
    <div className="space-y-5">
      {/* ── Фильтр по этапам пайплайна ── */}
      <div
        className="flex flex-wrap items-center gap-2 justify-center"
        role="group"
        aria-label="Фильтр статей по этапам пайплайна"
      >
        <button
          type="button"
          onClick={() => onStageFilterChange("all")}
          aria-pressed={stageFilter === "all"}
          className={stageFilterClass(stageFilter === "all")}
        >
          Все этапы
        </button>
        {KNOWLEDGE_STAGES.map((stage) => {
          const active = stageFilter === stage;
          return (
            <button
              key={stage}
              type="button"
              onClick={() => onStageFilterChange(stage)}
              aria-pressed={active}
              className={stageFilterClass(active)}
            >
              {STAGE_LABELS_RU[stage]}
            </button>
          );
        })}
      </div>

      {/* ── Сетка карточек статей (единая геометрия карточек платформы) ── */}
      {articles.length === 0 ? (
        <p className="text-center py-12 text-sm text-neutral-500">
          Ничего не найдено — попробуйте изменить запрос или сбросить фильтр этапа.
        </p>
      ) : (
        <div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 px-6"
          role="list"
          aria-label="Библиотека статей"
        >
          {articles.map((article) => {
            const StageIcon = STAGE_ICONS[article.stage_id];
            return (
              <div role="listitem" key={article.article_id}>
                <button
                  type="button"
                  onClick={() => onOpenArticle(article.article_id)}
                  className="group flex h-full w-full flex-col items-start gap-3 rounded-xl border border-neutral-200 bg-white p-5 text-left transition-colors hover:border-brand/60 hover:bg-brand-light/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 focus-visible:ring-offset-2"
                >
                  <div className="flex w-full items-center gap-2">
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-brand-light px-2 py-0.5 text-[11px] font-medium text-brand"
                      aria-label={`Этап: ${STAGE_LABELS_RU[article.stage_id]}`}
                    >
                      <StageIcon size={11} aria-hidden="true" />
                      {STAGE_LABELS_RU[article.stage_id]}
                    </span>
                    <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-neutral-400">
                      <Clock size={11} aria-hidden="true" />
                      {article.reading_minutes} мин
                    </span>
                  </div>

                  <span className="flex items-start gap-2.5">
                    <BookOpen
                      size={15}
                      className="mt-0.5 shrink-0 text-brand"
                      aria-hidden="true"
                    />
                    <span className="text-[15px] font-semibold text-neutral-900 leading-snug">
                      {article.title}
                    </span>
                  </span>

                  <span className="text-[13px] text-neutral-500 leading-relaxed">
                    {article.summary}
                  </span>

                  <span className="mt-auto flex flex-wrap gap-1.5 pt-1">
                    {article.directions.map((d) => (
                      <span
                        key={d}
                        className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] text-neutral-500"
                      >
                        {DIRECTION_LABELS_RU[d]}
                      </span>
                    ))}
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
