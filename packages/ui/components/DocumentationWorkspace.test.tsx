// packages/ui/components/DocumentationWorkspace.test.tsx
//
// Точечная правка UI (следом за DOCLOG-4) — дизайн бейджей-заголовков
// областей «Виды документов» / «Версии» / «Предпросмотр» на странице
// «Документы исследования» по образцу бейджа «Знакомство с платформой»
// (RouteCard главной страницы): РАМКА и ФОН — border-brand/60 +
// bg-brand-light/60 + скругление rounded-xl, БЕЗ иконок. Шрифт заголовков
// НЕ меняется (уточнение тимлида: «это рамка и фон, а не шрифт») —
// текстовые классы h2 остаются прежними (text-sm font-semibold
// text-neutral-900 dark:text-neutral-100).
//
// Токены theme-adaptive (tailwind-preset → CSS-переменные): в тёмной теме
// border-brand/60 → #4A4ED9/60, bg-brand-light/60 → #1E2034/60 — отдельные
// dark:-ревизии не требуются (контракт «имена классов не меняются»).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./DocumentationWorkspace";

// Клиенты документации глушим: workspace с runId=null не ходит в сеть
// (честное empty-состояние §12.3), сетевой слой вне объёма UI-правки.
jest.mock("../lib/documentation", () => ({
  listDocuments: jest.fn(),
  createDraft: jest.fn(),
  getRevision: jest.fn(),
  requestRendition: jest.fn(),
  getJob: jest.fn(),
  cancelJob: jest.fn(),
  renditionContentUrl: (id: string) => `/v1/documentation/renditions/${id}/content`,
  revisionPreviewUrl: (id: string) => `/v1/documentation/revisions/${id}/preview`,
}));

const CHIP_FRAME = ["rounded-xl", "border-brand/60", "bg-brand-light/60"] as const;

describe("DocumentationWorkspace — бейджи-заголовки областей (рамка и фон по эталону)", () => {
  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("бейдж «%s»: рамка+фон эталона (rounded-xl, border-brand/60, bg-brand-light/60)", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const chip = screen.getByText(label);
    for (const cls of CHIP_FRAME) {
      expect(chip.className).toContain(cls);
    }
  });

  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("бейдж «%s»: шрифт НЕ менялся — text-sm font-semibold остаются на заголовке h2", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const h2 = screen.getByText(label).closest("h2");
    expect(h2).not.toBeNull();
    expect(h2?.className).toContain("text-sm");
    expect(h2?.className).toContain("font-semibold");
    expect(h2?.className).toContain("text-neutral-900");
    expect(h2?.className).toContain("dark:text-neutral-100");
  });

  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("бейдж «%s»: без иконок (правка исключает пиктограммы)", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const chip = screen.getByText(label);
    expect(chip.querySelector("svg")).toBeNull();
    expect(chip.querySelector("img")).toBeNull();
  });

  it("бейдж-рамка компактно обнимает текст (inline-block), а не растягивается на всю панель", () => {
    render(<DocumentationWorkspace runId={null} />);
    const chip = screen.getByText("Виды документов");
    expect(chip.tagName).toBe("SPAN");
    expect(chip.className).toContain("inline-block");
  });

  it("заголовок «Версии» сохраняет динамику (вид документа при выборе) — правка рамки текст не подменяет", () => {
    render(<DocumentationWorkspace runId={null} />);
    // runId=null → активный вид не выбран → фолбэк-текст «Версии» (§12.2).
    expect(screen.getByText("Версии")).toBeInTheDocument();
  });
});
