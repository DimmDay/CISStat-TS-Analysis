// packages/ui/components/HomeCapabilities.test.tsx
//
// Тесты для HomeCapabilities — вторая секция главной страницы (/)
// в standalone-режиме.
//
// Задача M-03 (2026-09-12, решение тимлида): marquee-лента из 14
// бейджей (M-02) заменена на СТАТИЧНУЮ сетку из 6 бейджей «Исследование
// данных…»; в hero-секции (HomeHero) появляется симметричная сетка
// из 6 бейджей «Анализ временных рядов…». Требования:
//   - размер бейджей обеих секций одинаков — общий компонент StatBadge
//     и общая константа сетки STAT_GRID_CLASS (2/3/6 колонок);
//   - отступ бейджей от границ страницы — 24px слева и справа
//     (даёт контейнер <main className="px-6"> layout.tsx);
//   - подпись каждого бейджа — фиксированные 2 строки (h-7 + line-clamp-2).
//
// Исторические тесты Task 29/30 (собственная рамка/скругление бейджа,
// отсутствие «слитого монолита», порядок Block A → divider → H2 →
// Block B → divider) сохранены с пересчётом на 6 бейджей.

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
  // ── Block A: статичная сетка из 6 stat-бейджей НАД заголовком ──

  it("renders 6 stat values in the badge grid", () => {
    const { container } = render(<HomeCapabilities />);
    const dds = Array.from(container.querySelectorAll("dl dd")).map((el) =>
      el.textContent,
    );
    expect(dds).toHaveLength(CAPABILITY_STATS.length);
    for (const stat of CAPABILITY_STATS) {
      expect(dds).toContain(stat.value);
    }
  });

  it("renders 6 stat labels in the badge grid", () => {
    const { container } = render(<HomeCapabilities />);
    const dts = Array.from(container.querySelectorAll("dl dt")).map((el) =>
      el.textContent,
    );
    expect(dts).toHaveLength(CAPABILITY_STATS.length);
    for (const stat of CAPABILITY_STATS) {
      expect(dts).toContain(stat.label);
    }
  });

  it("renders stats inside semantic <dl> with 6 <dd>/<dt> pairs", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl).toHaveAttribute("aria-label", "Метрики платформы");
    expect(dl!.querySelectorAll("dd")).toHaveLength(6);
    expect(dl!.querySelectorAll("dt")).toHaveLength(6);
  });

  it("renders the badge grid as responsive 2/3/6 grid with gap-3 (same as hero)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    expect(dl.className).toContain("grid");
    expect(dl.className).toContain("grid-cols-2");
    expect(dl.className).toContain("sm:grid-cols-3");
    expect(dl.className).toContain("lg:grid-cols-6");
    expect(dl.className).toContain("gap-3");
  });

  it("renders compact uniform badges with 2-line labels (StatBadge contract)", () => {
    const { container } = render(<HomeCapabilities />);
    const badges = container.querySelectorAll("dl > div.bg-neutral-100");
    expect(badges.length).toBe(CAPABILITY_STATS.length);
    badges.forEach((badge) => {
      expect(badge.className).toContain("px-3");
      expect(badge.className).toContain("py-3");
      expect(badge.className).toContain("rounded-xl");
      expect(badge.className).toContain("border-neutral-200");
      expect(badge.className).toContain("bg-neutral-100");
      const dt = badge.querySelector("dt")!;
      expect(dt.className).toContain("h-7");
      expect(dt.className).toContain("line-clamp-2");
      const dd = badge.querySelector("dd")!;
      expect(dd.className).toContain("text-xl");
    });
  });

  it("renders the 6 environment/quality theses and drops the reserve ones", () => {
    const { container } = render(<HomeCapabilities />);
    const text = container.querySelector("dl")!.textContent!;
    // Нижняя секция: среда, качество, инженерия
    expect(text).toContain("единая исследовательская среда");
    expect(text).toContain("автотестов покрывают бизнес-логику");
    expect(text).toContain("API-эндпоинтов");
    expect(text).toContain("критериев качества данных по DAMA DMBOK");
    expect(text).toContain("уровня применимости моделей");
    // Пункт из M-01/M-02 сохранён по решению тимлида
    expect(text).toContain("стратегии ансамблевого прогноза");
    // Тезисы, ушедшие в резерв (M-03), не рендерятся
    expect(text).not.toContain("теста диагностики остатков");
    expect(text).not.toContain("метода декомпозиции ряда");
    // Тезисы верхней секции здесь не дублируются
    expect(text).not.toContain("моделей в каталоге");
    expect(text).not.toContain("стадий пайплайна");
  });

  it("does NOT render the marquee anymore (M-02 superseded by M-03)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    // Ни классов бегущей строки, ни вьюпорта, ни клона
    expect(dl.className).not.toContain("animate-marquee");
    expect(dl.className).not.toContain("w-max");
    expect(container.querySelector(".marquee-viewport")).toBeNull();
    expect(
      container.querySelector('[data-testid="marquee-group-real"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="marquee-group-clone"]'),
    ).toBeNull();
  });

  it("uses smaller font for stat values (text-xl, not text-3xl)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    const dd = dl!.querySelector("dd");
    expect(dd).not.toBeNull();
    expect(dd!.className).toContain("text-xl");
    expect(dd!.className).not.toContain("text-3xl");
  });

  it("does NOT use the old merged-monolith layout on <dl> (Task 29)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    // <dl> НЕ должен иметь общую рамку/скругление/обрезку
    expect(dl.className).not.toContain("rounded-xl");
    expect(dl.className).not.toContain("bg-neutral-200");
    expect(dl.className).not.toContain("gap-px");
    // Обычный gap между бейджами
    expect(dl.className).toContain("gap-3");
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

  it("renders Block A (badge grid) BEFORE the H2 in DOM order", () => {
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
    expect(grids.length).toBeGreaterThanOrEqual(1);
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
