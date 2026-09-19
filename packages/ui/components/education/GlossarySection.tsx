"use client";

// packages/ui/components/education/GlossarySection.tsx
//
// Task EDU-1 — секция «Словарь терминов» хаба «Обучение и база знаний».
// Термины — алфавитный порядок (ru) из слоя знаний; у каждого термина —
// определение и связанные статьи Библиотеки (кнопки открывают панель
// чтения: связь Словарь → Библиотека внутри базы знаний).
//
// Контент НЕ хардкодится: секция рендерит пропы из слоя знаний.

import { ArrowRight, BookOpen } from "lucide-react";
import type { GlossaryTerm, KnowledgeArticle } from "../../lib/knowledge/types";

export function GlossarySection({
  terms,
  articleById,
  onOpenArticle,
}: {
  terms: GlossaryTerm[];
  /** Доступ к статьям по id для связанных ссылок (уже включая draft —
   * ссылка словаря может вести на статью в подготовке, она честно
   * помечается в ридере статусом). */
  articleById: (articleId: string) => KnowledgeArticle | undefined;
  onOpenArticle: (articleId: string) => void;
}) {
  if (terms.length === 0) {
    return (
      <p className="text-center py-12 text-sm text-neutral-500">
        Ничего не найдено — попробуйте изменить запрос.
      </p>
    );
  }

  return (
    <div
      className="grid grid-cols-1 md:grid-cols-2 gap-4 px-6"
      role="list"
      aria-label="Словарь терминов базы знаний"
    >
      {terms.map((term) => {
        const related = term.related_article_ids
          .map((id) => articleById(id))
          .filter((a): a is KnowledgeArticle => Boolean(a));
        const letter = term.term.charAt(0).toUpperCase();
        return (
          <div
            role="listitem"
            key={term.term_id}
            className="rounded-xl border border-neutral-200 bg-white p-5"
          >
            <div className="flex items-center gap-2.5 mb-2">
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-brand-light text-[13px] font-semibold text-brand"
                aria-hidden="true"
              >
                {letter}
              </span>
              <h3 className="text-[15px] font-semibold text-neutral-900">{term.term}</h3>
            </div>

            <p className="text-[13px] text-neutral-600 leading-relaxed">{term.definition}</p>

            {related.length > 0 && (
              <div className="mt-3 border-t border-neutral-100 pt-2.5">
                <p className="text-[11px] uppercase tracking-wide text-neutral-400 mb-1.5">
                  Читать подробнее
                </p>
                {/* div, а не ul/li: term-item сам является listitem —
                    вложенная семантика списка ломает подсчёт терминов
                    (listitem внутри listitem). Кнопки без list-семантики. */}
                <div className="space-y-1">
                  {related.map((article) => (
                    <div key={article.article_id}>
                      <button
                        type="button"
                        onClick={() => onOpenArticle(article.article_id)}
                        className="group inline-flex items-center gap-1 text-[13px] text-brand hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 rounded"
                      >
                        <BookOpen size={12} aria-hidden="true" />
                        {article.title}
                        <ArrowRight
                          size={12}
                          className="opacity-40 group-hover:opacity-100 transition-opacity"
                          aria-hidden="true"
                        />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
