// packages/ui/components/HomeWavesBackground.test.tsx
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { HomeWavesBackground } from "./HomeWavesBackground";

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

  it("использует фирменные токены (brand-light/brand), а не произвольную палитру", () => {
    const { container } = render(<HomeWavesBackground />);

    expect(container.innerHTML).toContain("brand-light");
    expect(container.innerHTML).toMatch(/fill-brand\b|fill-brand\/|fill-brand\[/);
  });

  it("рендерит инлайн SVG с двумя слоями волн (не растровое изображение, не canvas)", () => {
    const { container } = render(<HomeWavesBackground />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg?.querySelectorAll("path").length).toBe(2);
  });
});
