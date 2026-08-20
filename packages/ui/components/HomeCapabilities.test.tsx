// packages/ui/components/HomeCapabilities.test.tsx
//
// Тесты для HomeCapabilities — вторая секция главной страницы (/)
// в standalone-режиме. Содержит три блока:
//   - Заголовок H2 + поддерживающий текст + section tag
//   - Block A: 4 stat-счётчика
//   - Block B: сетка 3×2 из 6 capability-карточек
//   - Block C: manifesto-цитата
//
// Структура тестов повторяет HomeHero.test.tsx — та же дисциплина:
//   - рендер заголовка и поддерживающего текста
//   - рендер всех элементов данных из источника (CAPABILITY_STATS,
//     CAPABILITIES, MANIFESTO_*)
//   - семантика a11y (aria-labelledby, dl/dt/dd, blockquote, role=list)

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeCapabilities } from "./HomeCapabilities";
import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITIES_TAG,
  CAPABILITY_STATS,
  CAPABILITIES,
  MANIFESTO_HEADLINE,
  MANIFESTO_BODY,
} from "../lib/capabilities";

describe("HomeCapabilities", () => {
  // ── Заголовок секции ────────────────────────────────────────

  it("renders the H2 title", () => {
    render(<HomeCapabilities />);
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: CAPABILITIES_TITLE,
      }),
    ).toBeInTheDocument();
  });

  it("renders the subtitle text", () => {
    render(<HomeCapabilities />);
    const subtitle = screen.getByText(CAPABILITIES_SUBTITLE);
    expect(subtitle).toBeInTheDocument();
    // Тонкий серый шрифт — та же конвенция, что в HomeHero
    expect(subtitle.className).toContain("text-neutral-500");
  });

  it("renders the section tag (uppercase mono label)", () => {
    render(<HomeCapabilities />);
    const tag = screen.getByText(CAPABILITIES_TAG);
    expect(tag).toBeInTheDocument();
    expect(tag.className).toContain("font-mono");
    expect(tag.className).toContain("text-brand");
  });

  it("wraps everything in a <section> with aria-labelledby", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    expect(section).toHaveAttribute("aria-labelledby", "capabilities-heading");
    // И id заголовка должен совпадать
    const heading = section!.querySelector("#capabilities-heading");
    expect(heading).not.toBeNull();
  });

  // ── Block A: 4 stat-счётчика ───────────────────────────────

  it("renders all 4 stat values", () => {
    render(<HomeCapabilities />);
    for (const stat of CAPABILITY_STATS) {
      expect(screen.getByText(stat.value)).toBeInTheDocument();
    }
  });

  it("renders all 4 stat labels", () => {
    render(<HomeCapabilities />);
    for (const stat of CAPABILITY_STATS) {
      expect(screen.getByText(stat.label)).toBeInTheDocument();
    }
  });

  it("renders stats inside semantic <dl> with 4 <dd>/<dt> pairs", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl).toHaveAttribute("aria-label", "Метрики платформы");
    const dds = dl!.querySelectorAll("dd");
    const dts = dl!.querySelectorAll("dt");
    expect(dds.length).toBe(4);
    expect(dts.length).toBe(4);
  });

  // ── Block B: 6 capability-карточек ──────────────────────────

  it("renders all 6 capability titles", () => {
    render(<HomeCapabilities />);
    for (const cap of CAPABILITIES) {
      // Заголовки уникальны — используем getByRole(heading, level:3)
      expect(
        screen.getByRole("heading", { level: 3, name: cap.title }),
      ).toBeInTheDocument();
    }
  });

  it("renders all 6 capability descriptions", () => {
    render(<HomeCapabilities />);
    for (const cap of CAPABILITIES) {
      expect(screen.getByText(cap.description)).toBeInTheDocument();
    }
  });

  it("renders 6 cards each with an aria-hidden icon in a brand circle", () => {
    render(<HomeCapabilities />);
    // Тот же селектор, что в HomeHero.test.tsx — проверка консистентности
    // визуальной системы двух секций.
    const iconCircles = document.querySelectorAll(
      ".rounded-full.bg-brand-light.text-brand",
    );
    expect(iconCircles.length).toBe(6);
    // Все иконки aria-hidden
    iconCircles.forEach((el) => {
      expect(el).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("renders the features grid as role=list with 6 listitems", () => {
    const { container } = render(<HomeCapabilities />);
    const list = container.querySelector('[role="list"][aria-label="Ключевые возможности платформы"]');
    expect(list).not.toBeNull();
    const items = list!.querySelectorAll('[role="listitem"]');
    expect(items.length).toBe(6);
  });

  it("uses responsive 3×2 grid classes (lg:grid-cols-3)", () => {
    const { container } = render(<HomeCapabilities />);
    const grids = container.querySelectorAll(".grid");
    // Минимум 2 grid'а: stat-счётчики + capability-карточки
    expect(grids.length).toBeGreaterThanOrEqual(2);
    // Находим capability-грид по наличию lg:grid-cols-3
    const capGrid = Array.from(grids).find((g) =>
      g.className.includes("lg:grid-cols-3"),
    );
    expect(capGrid).toBeDefined();
    expect(capGrid!.className).toContain("grid-cols-1");
    expect(capGrid!.className).toContain("sm:grid-cols-2");
  });

  // ── Block C: Manifesto ─────────────────────────────────────

  it("renders manifesto headline and body inside <blockquote>", () => {
    const { container } = render(<HomeCapabilities />);
    const blockquote = container.querySelector("blockquote");
    expect(blockquote).not.toBeNull();
    expect(
      screen.getByText(MANIFESTO_HEADLINE),
    ).toBeInTheDocument();
    expect(
      screen.getByText(MANIFESTO_BODY),
    ).toBeInTheDocument();
  });

  it("renders an sr-only <cite> for the manifesto", () => {
    const { container } = render(<HomeCapabilities />);
    const cite = container.querySelector("cite");
    expect(cite).not.toBeNull();
    expect(cite!.className).toContain("sr-only");
  });
});
