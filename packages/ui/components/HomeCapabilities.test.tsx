// packages/ui/components/HomeCapabilities.test.tsx
//
// Тесты для HomeCapabilities — вторая секция главной страницы (/)
// в standalone-режиме.
//
// Правка 3 (Task 29, 2026-08-21): Block A теперь — 4 отдельных бейджа
// (раньше — «слитый монолит» с 1px-линиями между ячейками). Добавлены
// тесты на собственную рамку и скругление каждого StatCell, проверено
// отсутствие общей рамки на <dl>.

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
  // ── Block A: 4 stat-бейджа НАД заголовком ─────────────────

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

  // ── Task 29 (2026-08-21): 4 отдельных бейджа ───────────────

  it("renders 4 separate stat badges each with own border and rounding (Task 29)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    // Каждый StatCell — отдельный <div> со своей рамкой и скруглением
    const badges = dl!.querySelectorAll("div.bg-neutral-100.rounded-xl.border");
    expect(badges.length).toBe(4);
    badges.forEach((badge) => {
      expect(badge.className).toContain("border-neutral-200");
      expect(badge.className).toContain("rounded-xl");
      expect(badge.className).toContain("bg-neutral-100");
    });
  });

  it("does NOT use the old merged-monolith layout on <dl> (Task 29)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    // <dl> НЕ должен иметь общую рамку/скругление/overflow-hidden
    // (раньше был: "gap-px bg-neutral-200 rounded-xl overflow-hidden border")
    expect(dl!.className).not.toContain("rounded-xl");
    expect(dl!.className).not.toContain("overflow-hidden");
    expect(dl!.className).not.toContain("bg-neutral-200");
    expect(dl!.className).not.toContain("gap-px");
    // Используется обычный gap
    expect(dl!.className).toContain("gap-3");
  });

  it("renders stat badges in responsive 2/4 grid (mobile/desktop)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl!.className).toContain("grid");
    expect(dl!.className).toContain("grid-cols-2");
    expect(dl!.className).toContain("sm:grid-cols-4");
  });

  // ── Заголовок секции (без section tag) ──────────────────────

  it("renders the H2 title with smaller font and grey color (Task 30)", () => {
    render(<HomeCapabilities />);
    const h2 = screen.getByRole("heading", {
      level: 2,
      name: CAPABILITIES_TITLE,
    });
    expect(h2).toBeInTheDocument();
    // Task 30 (2026-08-21): text-2xl → text-xl, font-semibold сохранён,
    // Текущий UI-контракт: серый text-neutral-600.
    expect(h2.className).toContain("text-xl");
    expect(h2.className).not.toContain("text-2xl");
    expect(h2.className).toContain("font-semibold");
    expect(h2.className).toContain("tracking-tight");
    expect(h2.className).toContain("text-neutral-600");
    expect(h2.className).not.toContain("text-[#1e3a8a]");
  });

  it("renders the subtitle text", () => {
    render(<HomeCapabilities />);
    const subtitle = screen.getByText(CAPABILITIES_SUBTITLE);
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.className).toContain("text-neutral-500");
  });

  it("does NOT render the section tag (was removed in 2026-08-20 fix)", () => {
    render(<HomeCapabilities />);
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

  // ── Порядок в DOM: Block A → divider → H2 → Block B → divider ──

  it("renders Block A (stats) BEFORE the H2 in DOM order", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // [0] <dl> Block A
    expect(children[0].tagName).toBe("DL");
    // [1] <div> декоративная черта между Block A и H2 (Task 30)
    expect(children[1].tagName).toBe("DIV");
    expect(children[1].className).toContain("h-px");
    expect(children[1].className).toContain("w-full");
    expect(children[1].className).toContain("bg-neutral-200");
    // [2] <div> с H2
    expect(children[2].tagName).toBe("DIV");
    expect(children[2].querySelector("h2")).not.toBeNull();
    // [3] <div role="list"> Block B
    expect(children[3].tagName).toBe("DIV");
    expect(children[3]).toHaveAttribute("role", "list");
    expect(children[3].className).toContain("lg:grid-cols-3");
    // [4] <div> декоративная черта после Block B
    expect(children[4].tagName).toBe("DIV");
    expect(children[4].className).toContain("h-px");
  });

  it("renders a divider between Block A and H2 (Task 30)", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // Первый divider стоит сразу после <dl> (Block A) и перед <div> с H2
    expect(children[0].tagName).toBe("DL"); // Block A
    expect(children[1].className).toContain("h-px"); // divider
    expect(children[1].className).toContain("bg-neutral-200");
    expect(children[1]).toHaveAttribute("aria-hidden", "true");
    expect(children[2].querySelector("h2")).not.toBeNull(); // H2
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
    const iconCircles = document.querySelectorAll(
      ".rounded-full.bg-brand-light.text-brand",
    );
    expect(iconCircles.length).toBe(6);
    iconCircles.forEach((el) => {
      expect(el).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("does NOT apply hover effects to CapabilityCard in Block B (Task 30)", () => {
    const { container } = render(<HomeCapabilities />);
    // Block B: 6 карточек <div> внутри role=listitem
    const list = container.querySelector('[role="list"]');
    expect(list).not.toBeNull();
    const cards = list!.querySelectorAll("div.rounded-xl.border-neutral-200.bg-white");
    expect(cards.length).toBe(6);
    cards.forEach((card) => {
      // Task 30 (2026-08-21): hover-эффект убран. Не должно быть:
      // - group класса (родитель group-hover)
      // - transition-colors (плавный переход)
      // - hover:border-* / hover:bg-* (hover-стили)
      // - group-hover:* ( hover-стили иконки)
      expect(card.className).not.toContain("group");
      expect(card.className).not.toContain("transition-colors");
      expect(card.className).not.toContain("hover:border-");
      expect(card.className).not.toContain("hover:bg-");
      // Иконка внутри — тоже без transition-colors и group-hover
      const icon = card.querySelector("span.rounded-full");
      expect(icon).not.toBeNull();
      expect(icon!.className).not.toContain("transition-colors");
      expect(icon!.className).not.toContain("group-hover:");
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
    expect(grids.length).toBeGreaterThanOrEqual(2);
    const capGrid = Array.from(grids).find((g) =>
      g.className.includes("lg:grid-cols-3"),
    );
    expect(capGrid).toBeDefined();
    expect(capGrid!.className).toContain("grid-cols-1");
    expect(capGrid!.className).toContain("sm:grid-cols-2");
  });

  // ── Декоративная черта под Block B ─────────────────────────

  it("renders a full-width divider <div> after Block B", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    const lastChild = children[children.length - 1];
    expect(lastChild.tagName).toBe("DIV");
    expect(lastChild.className).toContain("h-px");
    expect(lastChild.className).toContain("w-full");
    expect(lastChild.className).toContain("bg-neutral-200");
    expect(lastChild).toHaveAttribute("aria-hidden", "true");
  });

  it("does NOT render the manifesto block (was removed in 2026-08-20 fix)", () => {
    const { container } = render(<HomeCapabilities />);
    expect(container.querySelector("blockquote")).not.toBeInTheDocument();
    expect(container.querySelector("cite")).not.toBeInTheDocument();
  });
});
