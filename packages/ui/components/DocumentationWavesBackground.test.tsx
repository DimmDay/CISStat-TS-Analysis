// packages/ui/components/DocumentationWavesBackground.test.tsx
//
// Точечная правка UI (следом за DOCLOG-4) — фон страницы «Документы
// исследования» = фон страницы «О платформе» (HomeWavesBackground),
// УСЕЧЁННЫЙ по высоте вариант: верхняя половина композиции отрезана,
// виден нижний (богатый волнами) срез того же авторского SVG. Шрифт
// контекста: страница «Документы» много короче главной — без усечения
// волны сплющились бы (preserveAspectRatio="none" растягивает весь
// холст 1600×1600 в низкую коробку); кроп сверху сохраняет визуальную
// плотность волн на уровне главной.
//
// Гарды: (1) декоративность/позиционирование как у домашнего фона;
// (2) viewBox — усечённый (сдвиг y=800, высота 800), НЕ полный холст;
// (3) геометрия (d-строки всех path) байт-в-байт равна HomeWavesBackground
// — перенос «без приближений» страхуется диффом против источника истины;
// (4) палитра — те же токены --wave-home-* (фон «О платформе»);
// (5) префикс id cisstat-docs- исключает коллизии с cisstat-home-*.

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { HomeWavesBackground } from "./HomeWavesBackground";
import { DocumentationWavesBackground } from "./DocumentationWavesBackground";

describe("DocumentationWavesBackground", () => {
  it("является чисто декоративным слоем: aria-hidden и не перехватывает клики", () => {
    const { container } = render(<DocumentationWavesBackground />);
    const root = container.firstElementChild;

    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root?.className).toContain("pointer-events-none");
  });

  it("спозиционирован абсолютно позади контента (absolute inset-0 -z-10), скруглён по паттерну фоновой коробки", () => {
    const { container } = render(<DocumentationWavesBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("absolute");
    expect(root?.className).toContain("inset-0");
    expect(root?.className).toContain("-z-10");
    expect(root?.className).toContain("overflow-hidden");
    expect(root?.className).toContain("rounded-2xl");
    expect(root?.className).not.toMatch(/\bfixed\b/);
  });

  it("УСЕЧЁННЫЙ по высоте вариант: viewBox отрезает ВЕРХнюю половину холста (0 800 1600 800), не полный 0 0 1600 1600", () => {
    const { container } = render(<DocumentationWavesBackground />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("viewBox", "0 800 1600 800");
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
    expect(svg).not.toHaveAttribute("viewBox", "0 0 1600 1600");
  });

  it("геометрия перенесена из домашнего фона БЕЗ приближений: d-строки всех path байт-в-байт равны HomeWavesBackground", () => {
    const home = render(<HomeWavesBackground />);
    const docs = render(<DocumentationWavesBackground />);

    const collect = (root: HTMLElement) =>
      Array.from(root.querySelectorAll("path")).map((p) => p.getAttribute("d"));

    const homePaths = collect(home.container);
    const docsPaths = collect(docs.container);

    // Источник истины: 7 path домашнего фона (4 ленты + 3 штриха-акцента).
    expect(homePaths).toHaveLength(7);
    expect(docsPaths).toEqual(homePaths);
  });

  it("подложка и состав композиции идентичны домашнему фону: 1 rect + 7 path, инлайн SVG (не растр, не canvas)", () => {
    const { container } = render(<DocumentationWavesBackground />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg?.querySelectorAll("rect").length).toBe(1);
    expect(svg?.querySelectorAll("path").length).toBe(7);
  });

  it("палитра — та же, что у фона «О платформе»: токены --wave-home-* (градиент подложки + 4 ленты + штрихи)", () => {
    const { container } = render(<DocumentationWavesBackground />);
    const html = container.innerHTML;

    expect(html).toContain("var(--wave-home-1)");
    expect(html).toContain("var(--wave-home-2)");
    expect(html).toContain("var(--wave-home-3)");
    expect(html).toContain("var(--wave-home-4)"); // w1
    expect(html).toContain("var(--wave-home-7)"); // w2
    expect(html).toContain("var(--wave-home-10)"); // w3
    expect(html).toContain("var(--wave-home-13)"); // low
  });

  it("использует префиксованные id градиентов cisstat-docs- (без коллизий с cisstat-home- на других страницах)", () => {
    const { container } = render(<DocumentationWavesBackground />);
    const ids = Array.from(container.querySelectorAll("linearGradient")).map((el) =>
      el.getAttribute("id"),
    );

    expect(ids.length).toBe(5);
    for (const id of ids) {
      expect(id).toMatch(/^cisstat-docs-/);
      expect(id).not.toMatch(/^cisstat-home-/);
    }
  });
});
