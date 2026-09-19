// packages/ui/components/education/EducationKnowledgeBase.test.tsx
//
// Task EDU-1 — контракты хаба «Обучение и база знаний» (страница
// /education, второй бейдж первого ряда главной, spec_education.md Часть I).
//
// Паттерны платформы, которые страхуют тесты:
//   - секции «Библиотека»/«Словарь терминов» — переключатель пилли
//     (паттерн ModuleNav, aria-pressed);
//   - чтение статьи — правая выдвижная панель (паттерн EventsLogDrawer:
//     крестик + клик вне панели закрывают);
//   - контент рендерится ТОЛЬКО из слоя знаний (lib/knowledge) — хаб не
//     содержит текстов статей/терминов (единый источник истины).

import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { EducationKnowledgeBase } from "./EducationKnowledgeBase";
import { getPublishedArticles, getGlossaryTerms } from "../../lib/knowledge/knowledge";
import { STAGE_LABELS_RU } from "../../lib/knowledge/types";

const published = getPublishedArticles();
const terms = getGlossaryTerms();

describe("EducationKnowledgeBase — шапка и навигация секций", () => {
  it("рендерит заголовок хаба и поддерживающую строку", () => {
    render(<EducationKnowledgeBase />);
    expect(screen.getByRole("heading", { level: 1, name: "Обучение и база знаний" }))
      .toBeInTheDocument();
    expect(
      screen.getByText(/единый источник методологии платформы/i),
    ).toBeInTheDocument();
  });

  it("содержит переключатель двух секций: Библиотека и Словарь терминов", () => {
    render(<EducationKnowledgeBase />);
    const libraryTab = screen.getByRole("button", { name: "Библиотека" });
    const glossaryTab = screen.getByRole("button", { name: "Словарь терминов" });
    expect(libraryTab).toHaveAttribute("aria-pressed", "true"); // библиотека активна по умолчанию
    expect(glossaryTab).toHaveAttribute("aria-pressed", "false");
  });

  it("по умолчанию открыта Библиотека: сетка статей из слоя знаний", () => {
    render(<EducationKnowledgeBase />);
    const grid = screen.getByRole("list", { name: "Библиотека статей" });
    const cards = within(grid).getAllByRole("listitem");
    expect(cards.length).toBe(published.length);
  });

  it("переключение на Словарь: термины рендерятся, библиотека скрыта", () => {
    render(<EducationKnowledgeBase />);
    fireEvent.click(screen.getByRole("button", { name: "Словарь терминов" }));
    expect(screen.getByRole("button", { name: "Словарь терминов" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const dl = screen.getByRole("list", { name: "Словарь терминов базы знаний" });
    expect(within(dl).getAllByRole("listitem").length).toBe(terms.length);
    expect(screen.queryByRole("list", { name: "Библиотека статей" })).toBeNull();
  });
});

describe("EducationKnowledgeBase — Библиотека: фильтр по этапам", () => {
  it("есть фильтр «Все этапы» и по одному пилли на каждый этап пайплайна", () => {
    render(<EducationKnowledgeBase />);
    expect(screen.getByRole("button", { name: "Все этапы" })).toBeInTheDocument();
    for (const stage of Object.keys(STAGE_LABELS_RU)) {
      expect(
        screen.getByRole("button", {
          name: STAGE_LABELS_RU[stage as keyof typeof STAGE_LABELS_RU],
        }),
      ).toBeInTheDocument();
    }
  });

  it("фильтр по этапу сокращает сетку до статей этого этапа", () => {
    render(<EducationKnowledgeBase />);
    fireEvent.click(screen.getByRole("button", { name: STAGE_LABELS_RU.eda }));
    const grid = screen.getByRole("list", { name: "Библиотека статей" });
    const cards = within(grid).getAllByRole("listitem");
    const edaArticles = published.filter((a) => a.stage_id === "eda");
    expect(cards.length).toBe(edaArticles.length);
  });
});

describe("EducationKnowledgeBase — чтение статьи (панель-ридер)", () => {
  it("клик по статье открывает панель чтения с заголовком, телом и источниками", () => {
    render(<EducationKnowledgeBase />);
    const article = published[0];
    fireEvent.click(screen.getByText(article.title));

    const reader = screen.getByRole("complementary", { name: "Чтение статьи" });
    expect(within(reader).getByRole("heading", { level: 2, name: article.title }))
      .toBeInTheDocument();
    // хотя бы один абзац тела статьи присутствует в ридере
    const paragraph = article.body.find((b) => b.type === "paragraph");
    expect(paragraph).toBeDefined();
    expect(within(reader).getByText((paragraph as { text: string }).text)).toBeInTheDocument();
    // источники перечислены
    expect(within(reader).getByText(/Источники/)).toBeInTheDocument();
    expect(within(reader).getByText(article.sources[0].label)).toBeInTheDocument();
  });

  it("панель закрывается крестиком", () => {
    render(<EducationKnowledgeBase />);
    fireEvent.click(screen.getByText(published[0].title));
    expect(screen.getByRole("complementary", { name: "Чтение статьи" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть статью" }));
    expect(screen.queryByRole("complementary", { name: "Чтение статьи" })).toBeNull();
  });

  it("панель закрывается кликом по затемнению вне панели", () => {
    render(<EducationKnowledgeBase />);
    fireEvent.click(screen.getByText(published[0].title));
    const reader = screen.getByRole("complementary", { name: "Чтение статьи" });
    const backdrop = reader.previousElementSibling as HTMLElement | null;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop as HTMLElement);
    expect(screen.queryByRole("complementary", { name: "Чтение статьи" })).toBeNull();
  });

  it("открытие статьи из словаря тоже работает (связь Словарь → Библиотека)", () => {
    render(<EducationKnowledgeBase />);
    fireEvent.click(screen.getByRole("button", { name: "Словарь терминов" }));
    const termWithRef = terms.find((t) => t.related_article_ids.length > 0);
    expect(termWithRef).toBeDefined();
    const linkedArticle = published.find(
      (a) => a.article_id === termWithRef!.related_article_ids[0],
    );
    expect(linkedArticle).toBeDefined();
    const dl = screen.getByRole("list", { name: "Словарь терминов базы знаний" });
    const termItem = within(dl)
      .getAllByRole("listitem")
      .find((li) => within(li).queryAllByText(termWithRef!.term).length > 0);
    expect(termItem).toBeDefined();
    fireEvent.click(within(termItem!).getByText(linkedArticle!.title));
    const reader = screen.getByRole("complementary", { name: "Чтение статьи" });
    expect(
      within(reader).getByRole("heading", { level: 2, name: linkedArticle!.title }),
    ).toBeInTheDocument();
  });
});

describe("EducationKnowledgeBase — поиск по базе знаний", () => {
  it("строка поиска фильтрует статьи библиотеки", () => {
    render(<EducationKnowledgeBase />);
    const input = screen.getByRole("textbox", { name: /поиск по базе знаний/i });
    fireEvent.change(input, { target: { value: "ARIMA" } });
    const grid = screen.getByRole("list", { name: "Библиотека статей" });
    const cards = within(grid).getAllByRole("listitem");
    expect(cards.length).toBeGreaterThan(0);
    expect(cards.length).toBeLessThan(published.length);
  });

  it("поиск без результатов показывает честное пустое состояние", () => {
    render(<EducationKnowledgeBase />);
    const input = screen.getByRole("textbox", { name: /поиск по базе знаний/i });
    fireEvent.change(input, { target: { value: "zzz-нет-совпадений-xyz" } });
    expect(screen.getByText(/ничего не найдено/i)).toBeInTheDocument();
  });
});
