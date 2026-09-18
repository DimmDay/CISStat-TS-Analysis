// packages/ui/components/HomeWavesBackground.test.tsx
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { HomeWavesBackground } from "./HomeWavesBackground";

// Контракт обновлён под точную геометрию/палитру авторского файла
// CISStat_TS_Analysis_background_wave_1600x1600.svg (заменяет прежнюю
// реконструкцию по скриншоту-макету: 1 rect-подложка + 4 "ленты" + 2
// белых штриха-акцента = 1 rect + 7 path, вместо прежних 2 path).

describe("HomeWavesBackground", () => {
  it("является чисто декоративным слоем: aria-hidden и не перехватывает клики", () => {
    const { container } = render(<HomeWavesBackground />);
    const root = container.firstElementChild;

    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root?.className).toContain("pointer-events-none");
  });

  it("спозиционирован абсолютно позади контента (absolute inset-0 -z-10), не fixed к вьюпорту", () => {
    const { container } = render(<HomeWavesBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("absolute");
    expect(root?.className).toContain("inset-0");
    expect(root?.className).toContain("-z-10");
    expect(root?.className).not.toMatch(/\bfixed\b/);
  });

  it("использует точную палитру background-wash градиента из авторского SVG", () => {
    const { container } = render(<HomeWavesBackground />);
    const html = container.innerHTML;

    expect(html).toContain("var(--wave-home-1)");
    expect(html).toContain("var(--wave-home-2)");
    expect(html).toContain("var(--wave-home-3)");
  });

  it("использует точную палитру всех 4 лент из авторского SVG", () => {
    const { container } = render(<HomeWavesBackground />);
    const html = container.innerHTML;

    expect(html).toContain("var(--wave-home-4)"); // w1
    expect(html).toContain("var(--wave-home-7)"); // w2
    expect(html).toContain("var(--wave-home-10)"); // w3
    expect(html).toContain("var(--wave-home-13)"); // low
  });

  it("рендерит инлайн SVG (не растровое изображение, не canvas) с полной геометрией источника: 1 rect-подложка + 7 path", () => {
    const { container } = render(<HomeWavesBackground />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg?.querySelectorAll("rect").length).toBe(1);
    expect(svg?.querySelectorAll("path").length).toBe(7);
  });

  it("viewBox соответствует авторскому источнику (1600×1600) и растягивается на весь контейнер", () => {
    const { container } = render(<HomeWavesBackground />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("viewBox", "0 0 1600 1600");
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
  });

  it("использует префиксованные id градиентов, чтобы не конфликтовать с другими инлайн-SVG на странице", () => {
    const { container } = render(<HomeWavesBackground />);
    const ids = Array.from(container.querySelectorAll("linearGradient")).map((el) =>
      el.getAttribute("id")
    );

    expect(ids.length).toBe(5);
    for (const id of ids) {
      expect(id).toMatch(/^cisstat-home-/);
    }
  });
});
