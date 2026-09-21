// apps/standalone/app/education/page.test.tsx
//
// Контракт страницы «Обучение и база знаний» /education (standalone).
// Task EDU-1: маршрут standalone рендерит общий хаб @cisstat/ui,
// по паттерну хаба «Задачи» (apps/standalone/app/tasks/page.tsx).
//
// Постановка тимлида (2026-09-21): фон #EFF6FD и футер — по паттерну
// главной страницы (apps/standalone/app/page.tsx; прецедент контракта —
// apps/standalone/app/navigator/page.test.tsx):
//   - обёртка relative isolate -mt-6 pt-6: компенсация padding-top
//     <main> (py-6 в layout.tsx) — фон доходит вплотную к ModuleNav,
//     содержимое не сдвигается ни на пиксель (один токен шкалы);
//   - EducationPageBackground — первый дочерний элемент обёртки:
//     aria-hidden коробка rounded-2xl на токене --wave-home-2
//     (светлый #EFF6FD; тёмная ревизия #17212C — DKT-CERT);
//   - HomeFooter — последний элемент потока контента, тематический
//     фон var(--c-footer-bg) (как на главной и /navigator), rounded-2xl.
// Страница standalone-only: embedded маршрут и хаб не использует,
// shared-композиция EducationKnowledgeBase не менялась.

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AppShellProvider } from "@cisstat/ui";
import Page from "./page";

function renderPage() {
  return render(
    <AppShellProvider>
      <Page />
    </AppShellProvider>,
  );
}

describe("Standalone /education page", () => {
  it("рендерит хаб «Обучение и база знаний» (@cisstat/ui EducationKnowledgeBase)", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { level: 1, name: "Обучение и база знаний" }),
    ).toBeInTheDocument();
  });

  it("хаб содержит секции-переключатели (Библиотека активна по умолчанию)", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Библиотека" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Словарь терминов" })).toBeInTheDocument();
  });

  it("фон по паттерну главной: обёртка компенсирует padding-top <main> (-mt-6 pt-6 на одной обёртке, один токен шкалы)", () => {
    const { container } = renderPage();
    const root = container.firstElementChild;
    const classes = root?.className ?? "";

    expect(classes).toContain("relative");
    expect(classes).toContain("isolate");
    const negMargin = classes.match(/-mt-(\d+)/)?.[1];
    const posPadding = classes.match(/(?<!-)pt-(\d+)/)?.[1];
    expect(negMargin).toBeDefined();
    expect(posPadding).toBeDefined();
    expect(negMargin).toBe(posPadding);
  });

  it("фон #EFF6FD — первый дочерний элемент обёртки: декоративная коробка rounded-2xl на токене --wave-home-2", () => {
    const { container } = renderPage();
    const root = container.firstElementChild;
    const bg = root?.firstElementChild;

    expect(bg).toHaveAttribute("aria-hidden", "true");
    expect(bg?.className).toContain("absolute");
    expect(bg?.className).toContain("inset-0");
    expect(bg?.className).toContain("rounded-2xl");
    // jsdom не резолвит var() — контракт через атрибут style (как в
    // тесте футера navigator: var(--c-footer-bg)).
    expect((bg as HTMLElement)?.getAttribute("style") ?? "").toContain(
      "var(--wave-home-2)",
    );
  });

  it("футер — последний элемент потока контента (HomeFooter: тематический фон, rounded-2xl)", () => {
    const { container } = renderPage();
    const root = container.firstElementChild;
    const content = root?.children[1]; // relative space-y-12 обёртка контента
    const footer = content?.lastElementChild;

    expect(content?.className).toContain("space-y-12");
    expect(footer?.tagName).toBe("FOOTER");
    expect(footer?.className).toContain("rounded-2xl");
    expect((footer as HTMLElement)?.getAttribute("style") ?? "").toContain(
      "var(--c-footer-bg)",
    );
    expect(content?.querySelector(":scope > footer")).toBe(footer);
  });
});
