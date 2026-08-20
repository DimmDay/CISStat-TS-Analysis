// packages/ui/components/HomeCapabilities.test.tsx

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeCapabilities } from "./HomeCapabilities";
import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
} from "../lib/capabilities";

describe("HomeCapabilities", () => {
  it("renders all 4 stat values and labels", () => {
    render(<HomeCapabilities />);
    for (const stat of CAPABILITY_STATS) {
      expect(screen.getByText(stat.value)).toBeInTheDocument();
      expect(screen.getByText(stat.label)).toBeInTheDocument();
    }
  });

  it("renders stats inside semantic <dl> with 4 <dd>/<dt> pairs", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl).toHaveAttribute("aria-label", "Метрики платформы");
    expect(dl!.querySelectorAll("dd").length).toBe(4);
    expect(dl!.querySelectorAll("dt").length).toBe(4);
  });

  it("renders the H2 title and subtitle", () => {
    render(<HomeCapabilities />);
    const h2 = screen.getByRole("heading", { level: 2, name: CAPABILITIES_TITLE });
    expect(h2.className).toContain("text-2xl");
    expect(h2.className).toContain("font-semibold");
    expect(screen.getByText(CAPABILITIES_SUBTITLE)).toBeInTheDocument();
  });

  it("renders all 6 capability titles and descriptions", () => {
    render(<HomeCapabilities />);
    for (const cap of CAPABILITIES) {
      expect(screen.getByRole("heading", { level: 3, name: cap.title })).toBeInTheDocument();
      expect(screen.getByText(cap.description)).toBeInTheDocument();
    }
  });

  it("renders 6 cards with brand icon circles", () => {
    render(<HomeCapabilities />);
    const iconCircles = document.querySelectorAll(".rounded-full.bg-brand-light.text-brand");
    expect(iconCircles.length).toBe(6);
    iconCircles.forEach((el) => expect(el).toHaveAttribute("aria-hidden", "true"));
  });

  it("uses brand-tinted normal state and stronger hover state for capability cards", () => {
    const { container } = render(<HomeCapabilities />);
    const cards = container.querySelectorAll('[role="listitem"] > div');
    expect(cards.length).toBe(6);
    cards.forEach((card) => {
      expect(card.className).toContain("border-brand/30");
      expect(card.className).toContain("bg-brand-light/30");
      expect(card.className).toContain("hover:border-brand/60");
      expect(card.className).toContain("hover:bg-brand-light/60");
    });
  });

  it("uses responsive 3×2 grid classes", () => {
    const { container } = render(<HomeCapabilities />);
    const capGrid = Array.from(container.querySelectorAll(".grid")).find((g) =>
      g.className.includes("lg:grid-cols-3"),
    );
    expect(capGrid).toBeDefined();
    expect(capGrid!.className).toContain("grid-cols-1");
    expect(capGrid!.className).toContain("sm:grid-cols-2");
  });

  it("renders the full-width divider after Block B", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const lastChild = section.children[section.children.length - 1];
    expect(lastChild.className).toContain("h-px");
    expect(lastChild.className).toContain("w-full");
    expect(lastChild.className).toContain("bg-neutral-200");
    expect(lastChild).toHaveAttribute("aria-hidden", "true");
  });
});
