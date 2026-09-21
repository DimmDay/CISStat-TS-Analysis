"use client";

// packages/ui/components/education/LearningTrackBuilder.tsx
//
// Task EDU-2 (spec_education.md, §2.2) — конструктор персональных
// обучающих стеков по направлениям. UI над buildLearningStack()
// (lib/knowledge — единый источник истины), без собственного контента.
//
// Контракт §2.2:
//   - чекбоксы направлений дают МНОЖЕСТВО (не одиночный выбор);
//   - порядок статей в построенном стеке ВСЕГДА по пайплайну (§13),
//     независимо от порядка кликов по чекбоксам;
//   - честность: у стека без статей — явное «справка готовится»
//     (no fabricated results), а не пустая рамка или подмена контента.
//
// Паттерны платформы: чекбоксы с счётчиками статей (честная маркировка
// ДО построения), группировка стека по этапам пайплайна (STAGE_ICONS),
// кнопка построения — явное действие пользователя.

import { useState } from "react";
import { Route, BookOpen, Clock, Compass } from "lucide-react";
import type { KnowledgeDirection } from "../../lib/knowledge/types";
import {
  DIRECTION_LABELS_RU,
  KNOWLEDGE_DIRECTIONS,
  KNOWLEDGE_STAGES,
  STAGE_ICONS,
  STAGE_LABELS_RU,
} from "../../lib/knowledge/types";
import {
  buildLearningStack,
  getDirectionArticleCounts,
  type LearningStack,
} from "../../lib/knowledge/knowledge";

export function LearningTrackBuilder({
  onOpenArticle,
}: {
  onOpenArticle: (articleId: string) => void;
}) {
  const [selected, setSelected] = useState<readonly KnowledgeDirection[]>([]);
  const [stack, setStack] = useState<LearningStack | null>(null);

  // Счётчики статей по направлениям — из слоя знаний (честно, включая 0).
  const counts = getDirectionArticleCounts();

  const toggleDirection = (direction: KnowledgeDirection) => {
    setSelected((prev) =>
      prev.includes(direction)
        ? prev.filter((d) => d !== direction)
        : [...prev, direction],
    );
  };

  const buildTrack = () => {
    setStack(buildLearningStack(selected));
  };

  const totalSelectedArticles = stack?.articles.length ?? 0;

  // Стек сгруппирован по этапам пайплайна: buildLearningStack гарантирует
  // сортировку по §13, поэтому группировка непрерывна — этап идёт блоком.
  const stageGroups = stack
    ? KNOWLEDGE_STAGES.map((stage) => ({
        stage,
        articles: stack.articles.filter((a) => a.stage_id === stage),
      })).filter((g) => g.articles.length > 0)
    : [];

  return (
    <div className="space-y-6 px-6">
      {/* ── Выбор направлений: чекбоксы дают МНОЖЕСТВО (§2.2) ── */}
      <div
        className="rounded-xl border border-neutral-200 bg-white p-5"
        role="group"
        aria-label="Направления обучающего стека"
      >
        <div className="mb-4 flex items-center gap-2">
          <Route size={15} className="text-brand" aria-hidden="true" />
          <h2 className="text-[15px] font-semibold text-neutral-900">
            Выберите направления — соберём персональную траекторию
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {KNOWLEDGE_DIRECTIONS.map((direction) => {
            const checked = selected.includes(direction);
            return (
              <label
                key={direction}
                className={
                  checked
                    ? "flex cursor-pointer items-center gap-2.5 rounded-lg border border-brand/50 bg-brand-light/30 px-3 py-2.5 transition-colors"
                    : "flex cursor-pointer items-center gap-2.5 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 transition-colors hover:border-neutral-300"
                }
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleDirection(direction)}
                  aria-label={DIRECTION_LABELS_RU[direction]}
                  className="h-4 w-4 shrink-0 accent-[var(--brand,#4f46e5)]"
                />
                <span className="text-[13px] font-medium text-neutral-800 leading-snug">
                  {DIRECTION_LABELS_RU[direction]}
                </span>
                <span className="ml-auto shrink-0 text-[11px] text-neutral-400">
                  {counts[direction] > 0
                    ? `${counts[direction]} ст.`
                    : "справка готовится"}
                </span>
              </label>
            );
          })}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={buildTrack}
            disabled={selected.length === 0}
            aria-label="Построить персональный стек"
            className="inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm bg-brand font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400 hover:bg-brand-strong"
          >
            Построить траекторию
          </button>
          <span className="text-xs text-neutral-400">
            {selected.length === 0
              ? "Отметьте хотя бы одно направление"
              : `Выбрано направлений: ${selected.length}`}
          </span>
        </div>
      </div>

      {/* ── Результат: персональный стек ── */}
      {stack === null ? (
        <p className="text-center py-6 text-sm text-neutral-500">
          Траектория ещё не построена — отметьте направления и нажмите
          «Построить траекторию».
        </p>
      ) : totalSelectedArticles === 0 ? (
        // Честность §2.2: стек пуст — «справка готовится», не пустая рамка.
        <p
          className="text-center py-12 text-sm text-neutral-500"
          role="status"
        >
          По выбранным направлениям справка готовится — статьи появятся
          по мере наполнения базы знаний.
        </p>
      ) : (
        <div className="space-y-6">
          <p className="text-xs text-neutral-400" role="status">
            Персональный стек: {totalSelectedArticles}{" "}
            {totalSelectedArticles === 1 ? "статья" : "статьи"} в порядке
            пайплайна — от загрузки данных к прогнозированию (§2.2, §13).
          </p>

          {stageGroups.map(({ stage, articles }) => {
            const StageIcon = STAGE_ICONS[stage];
            return (
              <div key={stage} className="space-y-2.5">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full bg-brand-light px-2.5 py-1 text-[11px] font-medium text-brand"
                    aria-label={`Этап пайплайна: ${STAGE_LABELS_RU[stage]}`}
                  >
                    <StageIcon size={11} aria-hidden="true" />
                    {STAGE_LABELS_RU[stage]}
                  </span>
                  <span className="text-[11px] text-neutral-400">
                    {articles.length}{" "}
                    {articles.length === 1 ? "статья" : "статьи"}
                  </span>
                </div>
                <div
                  className="space-y-2"
                  role="list"
                  aria-label={`Стек этапа «${STAGE_LABELS_RU[stage]}»`}
                >
                  {articles.map((article) => (
                    <div role="listitem" key={article.article_id}>
                      <button
                        type="button"
                        onClick={() => onOpenArticle(article.article_id)}
                        className="group flex w-full items-start gap-3 rounded-lg border border-neutral-200 bg-white px-4 py-3 text-left transition-colors hover:border-brand/60 hover:bg-brand-light/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
                      >
                        <BookOpen
                          size={15}
                          className="mt-0.5 shrink-0 text-brand"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[14px] font-semibold text-neutral-900 leading-snug">
                            {article.title}
                          </span>
                          <span className="mt-0.5 block text-[12px] text-neutral-500 leading-relaxed">
                            {article.summary}
                          </span>
                        </span>
                        <span className="ml-2 flex shrink-0 items-center gap-1 text-[11px] text-neutral-400">
                          <Clock size={11} aria-hidden="true" />
                          {article.reading_minutes} мин
                        </span>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

          {/* ── Термины траектории: только связанные со статьями стека ── */}
          {stack.terms.length > 0 && (
            <div className="rounded-xl border border-neutral-200 bg-white p-5">
              <div className="mb-3 flex items-center gap-2">
                <Compass size={15} className="text-brand" aria-hidden="true" />
                <h2 className="text-[15px] font-semibold text-neutral-900">
                  Термины траектории
                </h2>
                <span className="text-[11px] text-neutral-400">
                  связаны со статьями стека
                </span>
              </div>
              <dl
                className="space-y-2.5"
                role="list"
                aria-label="Термины обучающего стека"
              >
                {stack.terms.map((term) => (
                  <div role="listitem" key={term.term_id} className="text-[13px] leading-relaxed">
                    <dt className="inline font-semibold text-neutral-900">
                      {term.term}
                    </dt>
                    <dd className="inline text-neutral-500"> — {term.definition}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
      )}
    </div>
  );
}