// packages/ui/components/HomeCapabilities.test.tsx
//
// Тесты для HomeCapabilities — вторая секция главной страницы (/)
// в standalone-режиме. Содержит:
//   - Block A: 4 stat-счётчика НАД заголовком секции (светло-серый фон,
//     уменьшенный шрифт)
//   - Заголовок H2 + поддерживающий текст (без section tag)
//   - Block B: сетка 3×2 из 6 capability-карточек
//
// Правка от 2026-08-20: убраны тесты section tag и manifesto (Block C),
// добавлены тесты порядка (Block A предшествует H2 в DOM) и проверка
// светло-серого фона stat-ячеек (bg-neutral-50).
//
// Структура тестов повторяет HomeHero.test.tsx — та же дисциплина:
//   - рендер заголовка и поддерживающего текста
//   - рендер всех элементов данных из источника (CAPABILITY_STATS,
//     CAPABILITIES)
//   - семантика a11y (aria-labelledby, dl/dt/dd, role=list)
//   - порядок Block A → H2 → Block B

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
  // ── Block A: 4 stat-счётчика НАД заголовком ─────────────────

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

  it("uses darker grey background for stat cells (bg-neutral-100)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    // 4 ячейки <div class="bg-neutral-100 ...">
    const cells = dl!.querySelectorAll(".bg-neutral-100");
    expect(cells.length).toBe(4);
  });

  it("uses smaller font for stat values (text-xl, not text-3xl)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    const dd = dl!.querySelector("dd");
    expect(dd).not.toBeNull();
    expect(dd!.className).toContain("text-xl");
    expect(dd!.className).not.toContain("text-3xl");
  });

  // ── Заголовок секции (без section tag) ──────────────────────

  it("renders the H2 title with the same font weight as HomeHero H1", () => {
    render(<HomeCapabilities />);
    const h2 = screen.getByRole("heading", {
      level: 2,
      name: CAPABILITIES_TITLE,
    });
    expect(h2).toBeInTheDocument();
    // Тот же класс, что в HomeHero.tsx H1:
    // font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]
    expect(h2.className).toContain("text-2xl");
    expect(h2.className).toContain("font-semibold");
    expect(h2.className).toContain("tracking-tight");
    expect(h2.className).toContain("text-[#1e3a8a]");
  });

  it("renders the subtitle text", () => {
    render(<HomeCapabilities />);
    const subtitle = screen.getByText(CAPABILITIES_SUBTITLE);
    expect(subtitle).toBeInTheDocument();
    // Тонкий серый шрифт — та же конвенция, что в HomeHero
    expect(subtitle.className).toContain("text-neutral-500");
  });

  it("does NOT render the section tag (was removed in 2026-08-20 fix)", () => {
    render(<HomeCapabilities />);
    // Раньше был "ВОЗМОЖНОСТИ" моноширинным шрифтом над H2
    expect(screen.queryByText("ВОЗМОЖНОСТИ")).not.toBeInTheDocument();
  });

  it("wraps everything in a <section> with aria-labelledby", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    expect(section).toHaveAttribute("aria-labelledby", "capabilities-heading");
    const heading = section!.querySelector("#capabilities-heading");
    expect(heading).not.toBeNull();
  });

  // ── Порядок в DOM: Block A → H2 → Block B ───────────────────

  it("renders Block A (stats) BEFORE the H2 in DOM order", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // Первый ребёнок — <dl> (Block A)
    expect(children[0].tagName).toBe("DL");
    // Второй ребёнок — <div> с H2 (заголовок секции)
    expect(children[1].tagName).toBe("DIV");
    expect(children[1].querySelector("h2")).not.toBeNull();
    // Третий ребёнок — сам <div role="list"> (Block B)
    expect(children[2].tagName).toBe("DIV");
    expect(children[2]).toHaveAttribute("role", "list");
    expect(children[2].className).toContain("lg:grid-cols-3");
  });

  // ── Block B: 6 capability-карточек ──────────────────────────

  it("renders all 6 capability titles", () => {
    render(<HomeCapabilities />);
    for (const cap of CAPABILITIES) {
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
    iconCircles.forEach((el) => {
      expect(el).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("renders the features grid as role=list with 6 listitems", () => {
    const { container } = render(<HomeCapabilities />);
    const list = container.querySelector(
      '[role="list"][aria-label="Ключевые возможности платформы"]',
    );
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

  // ── Block C удалён ──────────────────────────────────────────

  it("does NOT render the manifesto block (was removed in 2026-08-20 fix)", () => {
    const { container } = render(<HomeCapabilities />);
    // Раньше был <blockquote> с manifesto
    expect(container.querySelector("blockquote")).not.toBeInTheDocument();
    expect(container.querySelector("cite")).not.toBeInTheDocument();
  });

  // ── Декоративная черта под Block B (правка 2 от 2026-08-20) ──

  it("renders a full-width divider <div> after Block B", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // Последний ребёнок <section> — <div class="h-px w-full bg-neutral-200" aria-hidden>
    const lastChild = children[children.length - 1];
    expect(lastChild.tagName).toBe("DIV");
    expect(lastChild.className).toContain("h-px");
    expect(lastChild.className).toContain("w-full");
    expect(lastChild.className).toContain("bg-neutral-200");
    expect(lastChild).toHaveAttribute("aria-hidden", "true");
  });
});
