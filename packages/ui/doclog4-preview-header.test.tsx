// packages/ui/doclog4-preview-header.test.tsx
//
// DOCLOG-4-UI-FIX-4 п.1 — бейдж «Предпросмотр»: заголовок приподнят и
// выровнен «по высоте» по паттерну заголовков бейджей «Виды документов»
// и «Версии».
//
// Паттерн (бейджи 1 и 2): контейнер pt-3 (12px от верхней рамки бейджа),
// h2 — ПЕРВЫЙ ребёнок области, выровнен по верху, text-sm font-semibold.
// «Предпросмотр» выпадал из паттерна дважды:
//   - контейнер pt-4 (+4px к положению всей шапки);
//   - шапка — flex-строка items-center: h2 центрировался относительно
//     более высоких пилюль-кнопок (26px против строки h2 20px) —
//     ещё ~+3px вниз.
//   Итог: верх текста заголовка ~19px от рамки против 12px у остальных.
// Правка: pt-4→pt-3 у области предпросмотра и items-center→items-start
// у строки шапки — верх текста h2 ровно 12px, байт-равно паттерну
// бейджей 1/2. Правка чисто геометрическая: темы не затрагиваются.

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./components/DocumentationWorkspace";

describe("DOCLOG-4-UI-FIX-4 п.1: заголовок «Предпросмотр» — по паттерну бейджей 1/2", () => {
  it("область предпросмотра: pt-3 — как у бейджей «Виды документов»/«Версии», pt-4 больше нет", () => {
    render(<DocumentationWorkspace runId={null} />);
    for (const id of ["doclog4-kind-list", "doclog4-version-list", "doclog4-preview-pane"]) {
      const panel = screen.getByTestId(id);
      expect(panel.className).toContain("pt-3");
    }
    const pane = screen.getByTestId("doclog4-preview-pane");
    expect(pane.className).not.toContain("pt-4");
  });

  it("строка шапки: items-start (заголовок по верху строки), items-center больше нет; h2 внутри строки", () => {
    render(<DocumentationWorkspace runId={null} />);
    const pane = screen.getByTestId("doclog4-preview-pane");
    const headerRow = pane.firstElementChild as HTMLElement;
    expect(headerRow.className).toContain("items-start");
    expect(headerRow.className).not.toContain("items-center");
    const h2 = headerRow.querySelector("h2");
    expect(h2).toBeInTheDocument();
    expect(h2?.textContent).toContain("Предпросмотр");
    // Паттерн заголовков бейджей 1/2: text-sm font-semibold.
    expect(h2?.className).toContain("text-sm");
    expect(h2?.className).toContain("font-semibold");
  });

  it("геометрия выравнивания: у бейджей 1/2 h2 — первый ребёнок области (верх текста = pt-3), предпросмотр приведён к тому же паттерну", () => {
    render(<DocumentationWorkspace runId={null} />);
    for (const id of ["doclog4-kind-list", "doclog4-version-list"]) {
      const panel = screen.getByTestId(id);
      // Заголовок — первый элемент области: ничего выше h2 нет.
      expect(panel.firstElementChild?.tagName).toBe("H2");
    }
    // У предпросмотра выше h2 тоже ничего нет: строка шапки — первый
    // ребёнок, h2 — первый ребёнок строки.
    const pane = screen.getByTestId("doclog4-preview-pane");
    const headerRow = pane.firstElementChild as HTMLElement;
    expect(headerRow.firstElementChild?.tagName).toBe("H2");
  });
});
