"use client";

// packages/ui/components/education/LibraryArticleReader.tsx
//
// Task EDU-1 — панель чтения статьи базы знаний.
//
// Паттерн: правая выдвижная панель EventsLogDrawer.tsx (фиксированная
// ширина, задвигается справа, затемнение фона закрывает по клику вне,
// крестик в шапке). Ширина — w-[40rem] по контракту UI-аддендума v4
// (spec_progress_review_and_v4_addendum.md §4.2: 2×w-80 = 640px), на
// мобильных — вся ширина экрана (sm: перелом).
//
// Токены — только тематические (контракт DKT «классы не меняются —
// меняются значения»): bg-white, text-neutral-*, border-neutral-200.
// dark:-оверрайды не нужны.

import { BookOpen, Clock, X } from "lucide-react";
import type { KnowledgeArticle, KnowledgeBlock } from "../../lib/knowledge/types";
import { DIRECTION_LABELS_RU, STAGE_LABELS_RU } from "../../lib/knowledge/types";

function KnowledgeBlockView({ block }: { block: KnowledgeBlock }) {
  if (block.type === "paragraph") {
    return <p className="text-sm text-neutral-700 leading-relaxed">{block.text}</p>;
  }
  if (block.type === "bullets") {
    return (
      <ul className="list-disc pl-5 space-y-1.5">
        {block.items.map((item, i) => (
          <li key={i} className="text-sm text-neutral-700 leading-relaxed">
            {item}
          </li>
        ))}
      </ul>
    );
  }
  // callout — выделенный блок «важно», по паттерну инлайн-подсказок
  return (
    <div className="rounded-lg border border-brand/30 bg-brand-light/50 px-4 py-3">
      <p className="text-sm text-neutral-800 leading-relaxed">{block.text}</p>
    </div>
  );
}

export function LibraryArticleReader({
  article,
  onClose,
}: {
  article: KnowledgeArticle;
  onClose: () => void;
}) {
  return (
    <>
      {/* Затемнение фона — закрывает панель по клику вне неё (паттерн EventsLogDrawer) */}
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} aria-hidden="true" />

      <aside
        role="complementary"
        aria-label="Чтение статьи"
        className="fixed top-0 right-0 h-full w-full sm:w-[40rem] bg-white shadow-xl z-50 flex flex-col"
      >
        {/* ── Шапка панели ── */}
        <div className="flex items-start justify-between gap-3 px-5 py-3 border-b border-neutral-200 shrink-0">
          <div className="min-w-0">
            <h2 className="font-semibold text-neutral-900 leading-snug">{article.title}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-light px-2 py-0.5 text-[11px] font-medium text-brand">
                <BookOpen size={11} aria-hidden="true" />
                {STAGE_LABELS_RU[article.stage_id]}
              </span>
              {article.directions.map((d) => (
                <span
                  key={d}
                  className="inline-flex items-center rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] text-neutral-600"
                >
                  {DIRECTION_LABELS_RU[d]}
                </span>
              ))}
              <span className="inline-flex items-center gap-1 text-[11px] text-neutral-400">
                <Clock size={11} aria-hidden="true" />
                {article.reading_minutes} мин чтения
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть статью"
            className="shrink-0 text-neutral-500 hover:text-neutral-900"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {/* ── Тело статьи ── */}
        <div className="overflow-y-auto flex-1 px-5 py-4">
          <div className="space-y-4">
            {article.body.map((block, i) => (
              <KnowledgeBlockView key={i} block={block} />
            ))}
          </div>

          {/* ── Источники (§7.1: официальные/авторитетные) ── */}
          <div className="mt-6 border-t border-neutral-200 pt-4">
            <h3 className="text-sm font-semibold text-neutral-900 mb-2">Источники</h3>
            <ul className="space-y-1.5">
              {article.sources.map((c, i) => (
                <li key={i} className="text-xs text-neutral-500 leading-relaxed">
                  {c.url ? (
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand hover:underline"
                    >
                      {c.label}
                    </a>
                  ) : (
                    c.label
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>
    </>
  );
}
