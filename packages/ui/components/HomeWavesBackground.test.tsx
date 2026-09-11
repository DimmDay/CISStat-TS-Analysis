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

  it("использует сэмплированную из макета палитру (точные hex, не Tailwind-токены brand)", () => {
    const { container } = render(<HomeWavesBackground />);

    const root = container.firstElementChild as HTMLElement;
    expect(root.style.background).toContain("#EFF7FE");
    expect(root.style.background).toContain("#E6ECFA");
    expect(container.innerHTML).toContain("#DCE7FB");
    expect(container.innerHTML).toContain("#C9D9F7");
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
