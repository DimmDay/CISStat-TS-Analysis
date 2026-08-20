// packages/ui/components/HomeHero.test.tsx

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeHero } from "./HomeHero";
import { HOME_ROUTES } from "../lib/home-stops";

describe("HomeHero", () => {
  it("renders the H1 title", () => {
    render(<HomeHero />);
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /Анализ временных рядов — от файла до прогноза/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the subtitle text in grey", () => {
    render(<HomeHero />);
    const subtitle = screen.getByText(
      "пространство для исследования, обучения и проверки гипотез",
    );
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.className).toContain("text-neutral-500");
  });

  it("renders all 6 route cards", () => {
    render(<HomeHero />);
    for (const route of HOME_ROUTES) {
      expect(screen.getByText(route.title)).toBeInTheDocument();
    }
  });

  it("renders each card description", () => {
    render(<HomeHero />);
    for (const route of HOME_ROUTES) {
      expect(screen.getByText(route.description)).toBeInTheDocument();
    }
  });

  it("renders 6 links with correct hrefs", () => {
    render(<HomeHero />);
    for (const route of HOME_ROUTES) {
      const link = screen.getByText(route.title).closest("a");
      expect(link).not.toBeNull();
      expect(link).toHaveAttribute("href", route.href);
    }
  });

  it("renders 6 route cards with the requested normal and hover states", () => {
    const { container } = render(<HomeHero />);
    const links = container.querySelectorAll('[role="list"] > a');
    expect(links.length).toBe(6);

    links.forEach((link) => {
      expect(link.className).toContain("border-brand/30");
      expect(link.className).toContain("bg-brand-light/30");
      expect(link.className).toContain("hover:border-brand/60");
      expect(link.className).toContain("hover:bg-brand-light/60");
    });
  });

  it("renders icons with aria-hidden for all 6 cards", () => {
    render(<HomeHero />);
    const iconCircles = document.querySelectorAll(
      ".rounded-full.bg-brand-light.text-brand",
    );
    expect(iconCircles.length).toBe(6);
    iconCircles.forEach((icon) => {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("renders the grid container with grid-cols layout", () => {
    const { container } = render(<HomeHero />);
    const grid = container.querySelector(".grid");
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("grid-cols-1");
    expect(grid?.className).toContain("sm:grid-cols-2");
    expect(grid?.className).toContain("lg:grid-cols-3");
  });
});
