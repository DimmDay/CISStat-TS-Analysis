// packages/ui/components/HomeHero.test.tsx
//
// Задача M-03 (2026-09-12): в hero-секцию добавлена сетка из 6
// stat-бейджей «Анализ временных рядов…» (HERO_STATS) — между
// заголовком и исследовательской картой маршрутов. Бейджи используют
// общий компонент StatBadge и общую константу сетки STAT_GRID_CLASS
// с нижней секцией (HomeCapabilities) — размеры бейджей обеих секций
// совпадают по построению.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeHero } from "./HomeHero";
import { HOME_ROUTES } from "../lib/home-stops";
import { HERO_STATS } from "../lib/capabilities";

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

  it("renders the current subtitle text in brand color", () => {
    render(<HomeHero />);
    const subtitle = screen.getByText(
      "пространство для • исследования • обучения • проверки гипотез • аргументированных выводов • принятия решений",
    );
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.className).toContain("text-[#1e3a8a]");
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
      expect(link.className).toContain("border-brand/60");
      expect(link.className).toContain("bg-brand-light/60");
      expect(link.className).toContain("hover:border-brand/90");
      expect(link.className).toContain("hover:bg-brand-light/90");
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

  it("renders the routes grid with grid-cols layout", () => {
    const { container } = render(<HomeHero />);
    // Сетка маршрутов ищется явно по role="list": первой .grid на странице
    // теперь является dl stat-бейджей (M-03).
    const grid = container.querySelector('[role="list"]');
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("grid");
    expect(grid?.className).toContain("grid-cols-1");
    expect(grid?.className).toContain("sm:grid-cols-2");
    expect(grid?.className).toContain("lg:grid-cols-3");
  });

  // ── M-03: 6 stat-бейджей «Анализ временных рядов…» ──────────

  it("renders all 6 hero stat values (HERO_STATS)", () => {
    render(<HomeHero />);
    const dds = Array.from(document.querySelectorAll("dl dd")).map((el) =>
      el.textContent,
    );
    expect(dds).toHaveLength(HERO_STATS.length);
    for (const stat of HERO_STATS) {
      expect(dds).toContain(stat.value);
    }
  });

  it("renders all 6 hero stat labels", () => {
    render(<HomeHero />);
    const dts = Array.from(document.querySelectorAll("dl dt")).map((el) =>
      el.textContent,
    );
    expect(dts).toHaveLength(HERO_STATS.length);
    for (const stat of HERO_STATS) {
      expect(dts).toContain(stat.label);
    }
  });

  it("renders hero stats inside semantic <dl> with aria-label", () => {
    const { container } = render(<HomeHero />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl).toHaveAttribute(
      "aria-label",
      "Метрики анализа временных рядов",
    );
    expect(dl!.querySelectorAll("dd")).toHaveLength(6);
    expect(dl!.querySelectorAll("dt")).toHaveLength(6);
  });

  it("renders hero badge grid as responsive 2/3/6 grid with gap-3", () => {
    const { container } = render(<HomeHero />);
    const dl = container.querySelector("dl")!;
    expect(dl.className).toContain("grid");
    expect(dl.className).toContain("grid-cols-2");
    expect(dl.className).toContain("sm:grid-cols-3");
    expect(dl.className).toContain("lg:grid-cols-6");
    expect(dl.className).toContain("gap-3");
  });

  it("renders compact uniform badges with 2-line labels (StatBadge contract)", () => {
    const { container } = render(<HomeHero />);
    const badges = container.querySelectorAll("dl > div.bg-neutral-100");
    expect(badges.length).toBe(HERO_STATS.length);
    badges.forEach((badge) => {
      // Компактный паддинг + собственные рамка/скругление
      expect(badge.className).toContain("px-3");
      expect(badge.className).toContain("py-3");
      expect(badge.className).toContain("rounded-xl");
      expect(badge.className).toContain("border-neutral-200");
      expect(badge.className).toContain("bg-neutral-100");
      // Единая высота: подпись ровно 2 строки
      const dt = badge.querySelector("dt")!;
      expect(dt.className).toContain("h-7");
      expect(dt.className).toContain("line-clamp-2");
      // Крупное значение
      const dd = badge.querySelector("dd")!;
      expect(dd.className).toContain("text-xl");
    });
  });

  it("renders stat badges BETWEEN the H1 block and the routes grid", () => {
    const { container } = render(<HomeHero />);
    const root = container.children[0];
    const children = Array.from(root.children);
    // [0] H1 + подзаголовок, [1] dl бейджей, [2] сетка маршрутов
    expect(children[0].tagName).toBe("DIV");
    expect(children[0].querySelector("h1")).not.toBeNull();
    expect(children[1].tagName).toBe("DL");
    expect(children[2]).toHaveAttribute("role", "list");
  });
});