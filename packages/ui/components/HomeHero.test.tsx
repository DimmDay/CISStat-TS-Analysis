// packages/ui/components/HomeHero.test.tsx
//
// Тесты для HomeHero — hero-секция новой главной страницы (/).
// Компонент содержит:
//   - H1 «Анализ временных рядов — от файла до прогноза»
//   - Поддерживающий текст (тонкий серый)
//   - Сетку 3×2 из 6 карточек-маршрутов с иконками

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeHero } from "./HomeHero";
import { HOME_ROUTES } from "../lib/home-stops";

// next/link оборачивается <a> в jsdom через jest.setup.js mock
// (next/link → <a href={...}>{children}</a>).

describe("HomeHero", () => {
  // ── H1 и поддерживающий текст ────────────────────────────────

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
    // Тонкий серый шрифт — проверяем класс
    expect(subtitle.className).toContain("text-neutral-500");
  });

  // ── 6 карточек исследовательской карты ──────────────────────

  it("renders all 6 route cards", () => {
    render(<HomeHero />);
    // Каждая карточка — ссылка, содержащая заголовок маршрута
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

  it("renders icons with aria-hidden for all 6 cards", () => {
    render(<HomeHero />);
    // 6 иконок — все aria-hidden
    const icons = document.querySelectorAll("[aria-hidden=\"true\"]");
    // В DOM могут быть и другие aria-hidden (chevron-ы и т.д.),
    // поэтому проверяем, что как минимум 6 иконок-кружков
    // с брендовым фоном присутствуют.
    const iconCircles = document.querySelectorAll(
      ".rounded-full.bg-brand-light.text-brand",
    );
    expect(iconCircles.length).toBe(6);
  });

  // ── Семантика сетки ──────────────────────────────────────────

  it("renders the grid container with grid-cols layout", () => {
    const { container } = render(<HomeHero />);
    const grid = container.querySelector(".grid");
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("grid-cols-1");
    expect(grid?.className).toContain("sm:grid-cols-2");
    expect(grid?.className).toContain("lg:grid-cols-3");
  });
});
