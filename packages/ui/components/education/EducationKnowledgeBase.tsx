"use client";

// packages/ui/components/education/EducationKnowledgeBase.tsx
//
// Task EDU-1 — хаб страницы «Обучение и база знаний» (/education,
// второй бейдж первого ряда главной, spec_education.md Часть I).
//
// Композиция:
//   - шапка хаба по паттерну HomeHero/TasksHub (text-center + hero-индиго
//     из шкалы заголовков платформы; тёмная ревизия покрывается
//     класс-уровневой utility-ревизией globals.css, DKT);
//   - строка поиска по всей базе знаний (статьи + термины);
//   - переключатель секций пилли (паттерн ModuleNav, aria-pressed);
//   - Библиотека: фильтр по этапам + сетка карточек статей;
//   - Словарь: алфавитный список терминов со связями к статьям;
//   - панель чтения статьи (паттерн EventsLogDrawer, w-[40rem]).
//
// КОНТЕНТ НЕ ХАРДКОДИТСЯ: весь текст приходит из слоя знаний
// (lib/knowledge) — база знаний единый источник истины по методологии
// для всей платформы. Хаб знает только про ids и состояние.

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import {
  getArticleById,
  getGlossaryTerms,
  getPublishedArticles,
  searchKnowledge,
} from "../../lib/knowledge/knowledge";
import { LibrarySection, type StageFilter } from "./LibrarySection";
import { GlossarySection } from "./GlossarySection";
import { LibraryArticleReader } from "./LibraryArticleReader";

type Section = "library" | "glossary";

export function EducationKnowledgeBase() {
  const [section, setSection] = useState<Section>("library");
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");
  const [openArticleId, setOpenArticleId] = useState<string | null>(null);

  // Поиск по всей базе знаний (статьи + термины) — слой знаний.
  const search = useMemo(() => searchKnowledge(query), [query]);

  // Библиотека: результаты поиска, сужённые фильтром этапа.
  // Порядок уже следует пайплайну (контракт getPublishedArticles, §13).
  const libraryArticles = useMemo(
    () =>
      stageFilter === "all"
        ? search.articles
        : search.articles.filter((a) => a.stage_id === stageFilter),
    [search.articles, stageFilter],
  );

  const glossaryTerms = search.terms;
  const openArticle = openArticleId ? getArticleById(openArticleId) : undefined;
  const allTerms = useMemo(() => getGlossaryTerms(), []);
  const allPublished = useMemo(() => getPublishedArticles(), []);

  const openArticleFromAnywhere = (articleId: string) => setOpenArticleId(articleId);
  const closeReader = () => setOpenArticleId(null);

  return (
    <div className="space-y-10">
      {/* ── Шапка хаба (паттерн HomeHero/TasksHub) ── */}
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]">
          Обучение и база знаний
        </h1>
        <p className="mt-3 text-lg text-[#1e3a8a]">
          единый источник методологии платформы • библиотека • словарь терминов
        </p>
      </div>

      {/* ── Поиск по базе знаний ── */}
      <div className="max-w-xl mx-auto px-6">
        <div className="relative">
          <Search
            size={15}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400"
            aria-hidden="true"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск по базе знаний"
            placeholder="Поиск по базе знаний: методы, термины, практики…"
            className="w-full rounded-full border border-neutral-300 bg-white py-2 pl-10 pr-4 text-sm text-neutral-800 placeholder:text-neutral-400 focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/30 transition-colors"
          />
        </div>
      </div>

      {/* ── Переключатель секций (пилли по паттерну ModuleNav) ── */}
      <div className="flex items-center justify-center gap-2 px-6">
        <button
          type="button"
          onClick={() => setSection("library")}
          aria-pressed={section === "library"}
          className={
            section === "library"
              ? "inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm bg-brand font-medium text-white transition-colors"
              : "inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm bg-neutral-100 text-neutral-700 hover:bg-neutral-200 hover:text-neutral-900 transition-colors"
          }
        >
          Библиотека
        </button>
        <button
          type="button"
          onClick={() => setSection("glossary")}
          aria-pressed={section === "glossary"}
          className={
            section === "glossary"
              ? "inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm bg-brand font-medium text-white transition-colors"
              : "inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm bg-neutral-100 text-neutral-700 hover:bg-neutral-200 hover:text-neutral-900 transition-colors"
          }
        >
          Словарь терминов
        </button>
      </div>

      {/* ── Активная секция ── */}
      {section === "library" ? (
        <LibrarySection
          articles={libraryArticles}
          stageFilter={stageFilter}
          onStageFilterChange={setStageFilter}
          onOpenArticle={openArticleFromAnywhere}
        />
      ) : (
        <GlossarySection
          terms={glossaryTerms}
          articleById={getArticleById}
          onOpenArticle={openArticleFromAnywhere}
        />
      )}

      {/* ── Подпись о наполнении (честная маркировка) ── */}
      <p className="text-center text-xs text-neutral-400 px-6">
        База знаний пополняется вместе с платформой: {allPublished.length} статьи Библиотеки
        и {allTerms.length} терминов Словаря — та же методология, что и в рабочих
        инструментах этапов.
      </p>

      {/* ── Панель чтения статьи ── */}
      {openArticle && <LibraryArticleReader article={openArticle} onClose={closeReader} />}
    </div>
  );
}
