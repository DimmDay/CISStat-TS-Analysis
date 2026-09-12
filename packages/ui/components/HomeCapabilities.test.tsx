// packages/ui/components/HomeCapabilities.test.tsx
//
// Тесты для HomeCapabilities — вторая секция главной страницы (/)
// в standalone-режиме.
//
// Задача M-02 (2026-09-12): Block A переведён с 4 статичных бейджей
// в сетке 2/4 на БЕГУЩУЮ СТРОКУ (marquee) из 14 бейдж-счётчиков:
//   - 4 исходных + 10 новых маркетинговых тезисов (M-01, фактура из
//     кода main @ 23ca75b);
//   - компактная ширина бейджа w-[clamp(180px,18vw,300px)] — на ширине
//     страницы видно ~5 бейджей;
//   - подпись — фиксированные 2 строки (h-7 + line-clamp-2) у ВСЕХ
//     бейджей, единая высота карточки;
//   - анимация: вся лента синхронно движется справа налево с низкой
//     скоростью (animate-marquee, 90s linear infinite); пауза на hover;
//     prefers-reduced-motion отключает анимацию (globals.css);
//   - бесшовный цикл: лента дублируется в aria-hidden-копию, -50%
//     translate = ровно одна группа (правая граница стыка = левая).
//
// Исторические тесты Task 29/30 (собственная рамка/скругление бейджа,
// отсутствие «слитого монолита», порядок Block A → divider → H2 →
// Block B → divider) сохранены с пересчётом на 14×2 бейджа.
//
// Правка 6 (Task w/n, 2026-09-12): контракт бейджа обновлён —
// фон ПРОЗРАЧНЫЙ (bg-transparent, было bg-neutral-100), подпись (dt)
// в фирменном индиго text-brand — единый цвет текста бейджа с цифрой
// (dd). Селекторы исторических тестов пересчитаны на bg-transparent.
//
// Правка 7 (Task w/n, 2026-09-12): рамка бейджа — фирменный индиго
// border-brand (было border-neutral-200); полоса ПОД бегущей строкой
// — bg-brand. Исторические ассерты (Task 29/DOM-порядок) пересчитаны;
// нижняя полоса (после Block B) и карточки Block B — guard-ами
// закреплены нейтральными.
//
// Правка 8 (Task w/n, 2026-09-12, задача футера): нижняя черта
// (h-px bg-neutral-200 после Block B) УБРАНА — между нижней границей
// страницы и футером черта не нужна; секция заканчивается Block B.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { HomeCapabilities } from "./HomeCapabilities";
import { HomeHero } from "./HomeHero";
import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
} from "../lib/capabilities";

// Ширина бейджа — источник истины для «5 бейджей на ширину страницы».
// Дублируется со StatCell (Tailwind arbitrary value) намеренно: тест
// ловит случайную потерю класса при рефакторинге.
const BADGE_WIDTH_CLASS = "w-[clamp(180px,18vw,300px)]";

describe("HomeCapabilities", () => {
  // ── Block A: marquee из 14 stat-бейджей НАД заголовком ─────

  it("renders 14 stat values in the visible (real) marquee group", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    const dds = Array.from(real.querySelectorAll("dd")).map((el) => el.textContent);
    expect(dds).toHaveLength(CAPABILITY_STATS.length);
    for (const stat of CAPABILITY_STATS) {
      expect(dds).toContain(stat.value);
    }
  });

  it("renders 14 stat labels in the visible (real) marquee group", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    const dts = Array.from(real.querySelectorAll("dt")).map((el) => el.textContent);
    expect(dts).toHaveLength(CAPABILITY_STATS.length);
    for (const stat of CAPABILITY_STATS) {
      expect(dts).toContain(stat.label);
    }
  });

  it("duplicates all badges in an aria-hidden clone for the seamless loop", () => {
    const { container } = render(<HomeCapabilities />);
    const clone = container.querySelector('[data-testid="marquee-group-clone"]')!;
    expect(clone).toHaveAttribute("aria-hidden", "true");
    const cloneDds = Array.from(clone.querySelectorAll("dd")).map((el) => el.textContent);
    expect(cloneDds).toHaveLength(CAPABILITY_STATS.length);
    for (const stat of CAPABILITY_STATS) {
      expect(cloneDds).toContain(stat.value);
    }
    // Клон идёт вторым (справа от реальной группы)
    const groups = Array.from(
      container.querySelectorAll('[data-testid^="marquee-group-"]'),
    );
    expect(groups[1]).toHaveAttribute("aria-hidden", "true");
  });

  it("renders stats inside semantic <dl> with 28 <dd>/<dt> pairs (14×2)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl).toHaveAttribute("aria-label", "Метрики платформы");
    expect(dl!.querySelectorAll("dd")).toHaveLength(28);
    expect(dl!.querySelectorAll("dt")).toHaveLength(28);
  });

  it("renders the 10 new achievement theses (M-01) and drops the replaced one", () => {
    const { container } = render(<HomeCapabilities />);
    const text = container.querySelector('[data-testid="marquee-group-real"]')!
      .textContent!;
    // Пункт 1 фактуры: в проде лейбл «24 модели в каталоге…» (числительное
    // 24 требует именительного падежа); прежнее ожидание «моделей» было
    // рассинхронизировано с лейблом (preexisting-падение на чистом HEAD,
    // починено ожиданием под прод-лейбл).
    expect(text).toContain("модели в каталоге");
    expect(text).toContain("API-эндпоинтов");
    expect(text).toContain("стадий пайплайна моделирования");
    expect(text).toContain("уровня применимости моделей");
    expect(text).toContain("критериев качества данных по DAMA DMBOK");
    expect(text).toContain("метрик точности прогноза");
    expect(text).toContain("статистических теста диагностики остатков");
    expect(text).toContain("частот рядов");
    // Пункт 9 заменён по решению тимлида: вместо дата-контрактов —
    // 4 стратегии ансамблевого прогноза.
    expect(text).toContain("стратегии ансамблевого прогноза");
    expect(text).toContain("метода декомпозиции ряда");
    // Старый пункт 9 исключён из контента
    expect(text).not.toContain("дата-контракта");
  });

  it("renders compact badges: ~5 visible across the page width (fixed clamp width)", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    // Селектор по прозрачному фону (правка 6: bg-neutral-100 → bg-transparent)
    const badges = real.querySelectorAll("div.bg-transparent");
    expect(badges.length).toBe(CAPABILITY_STATS.length);
    badges.forEach((badge) => {
      expect(badge.className).toContain(BADGE_WIDTH_CLASS);
      expect(badge.className).toContain("shrink-0");
      // Компактнее прежнего px-4 py-4
      expect(badge.className).toContain("px-3");
      expect(badge.className).toContain("py-3");
      expect(badge.className).not.toContain("px-4");
      expect(badge.className).not.toContain("py-4");
    });
  });

  it("renders every label with a fixed 2-line height (h-7 + line-clamp-2)", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    const dts = real.querySelectorAll("dt");
    expect(dts.length).toBe(CAPABILITY_STATS.length);
    dts.forEach((dt) => {
      expect(dt.className).toContain("h-7");
      expect(dt.className).toContain("line-clamp-2");
      expect(dt.className).toContain("leading-tight");
    });
  });

  // ── Прозрачный фон бейджей marquee (Task w/n, 2026-09-12) ────
  //
  // Фон бейджа убран (bg-neutral-100 → bg-transparent): сквозь бейдж
  // виден фон страницы. Рамка/скругление/паддинг/анимация НЕ тронуты
  // (контракт Task 29 сохраняется, см. тест ниже). Блок B (карточки
  // возможностей) остаётся с белой заливкой — guard ниже.

  it("renders marquee badges with transparent background (no fill)", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    const badges = real.querySelectorAll("div.bg-transparent");
    expect(badges.length).toBe(CAPABILITY_STATS.length);
    badges.forEach((badge) => {
      expect(badge.className).toContain("bg-transparent");
      expect(badge.className).not.toContain("bg-neutral-100");
      expect(badge.className).not.toContain("bg-neutral-50");
      expect(badge.className).not.toContain("bg-white");
    });
    // Клон (aria-hidden) — тот же компонент, тот же прозрачный фон
    const clone = container.querySelector('[data-testid="marquee-group-clone"]')!;
    expect(clone.querySelectorAll("div.bg-transparent").length).toBe(
      CAPABILITY_STATS.length,
    );
  });

  it("renders every badge label in brand indigo — the same color as the value (text-brand)", () => {
    const { container } = render(<HomeCapabilities />);
    const real = container.querySelector('[data-testid="marquee-group-real"]')!;
    // Подпись (dt) — фирменный индиго text-brand (#2E3192), как цифра
    const dts = real.querySelectorAll("dt");
    expect(dts.length).toBe(CAPABILITY_STATS.length);
    dts.forEach((dt) => {
      expect(dt.className).toContain("text-brand");
      expect(dt.className).not.toContain("text-neutral-500");
      expect(dt.className).not.toContain("text-neutral-600");
      expect(dt.className).not.toContain("text-neutral-700");
    });
    // Значение (dd) тоже text-brand — единый цвет текста бейджа
    const dds = real.querySelectorAll("dd");
    expect(dds.length).toBe(CAPABILITY_STATS.length);
    dds.forEach((dd) => {
      expect(dd.className).toContain("text-brand");
    });
  });

  it("does NOT recolor Block B capability cards (scope: marquee only)", () => {
    const { container } = render(<HomeCapabilities />);
    // Карточки Block B — по-прежнему белые с нейтральной рамкой
    const cards = container.querySelectorAll(
      'div.rounded-xl.border-neutral-200.bg-white',
    );
    expect(cards.length).toBe(6);
  });

  // ── Индиго-рамка бейджей и полоса под marquee (Task w/n, 2026-09-12) ──
  //
  // Продолжение точечной правки бейджа marquee: рамка бейджа — тот же
  // фирменный индиго (токен brand #2E3192; в Tailwind для рамки это
  // класс border-brand, тот же токен, что text-brand). Полоса-разделитель
  // ПОД бегущей строкой (между marquee и H2) — тоже фирменный индиго
  // (bg-brand). Нижняя полоса (после Block B) и карточки Block B
  // остаются нейтральными — guard-ы ниже.

  it("renders every marquee badge border in brand indigo (border-brand)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    // 28 ячеек (14×2): рамка каждой — border-brand, серой рамки нет
    const badges = dl.querySelectorAll("div.bg-transparent.rounded-xl.border");
    expect(badges.length).toBe(28);
    badges.forEach((badge) => {
      expect(badge.className).toContain("border-brand");
      expect(badge.className).not.toContain("border-neutral-200");
    });
  });

  it("renders the divider UNDER the marquee in brand indigo (bg-brand)", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // [1] — полоса между marquee и H2: фирменный индиго
    expect(children[1].className).toContain("h-px");
    expect(children[1].className).toContain("w-full");
    expect(children[1].className).toContain("bg-brand");
    expect(children[1].className).not.toContain("bg-neutral-200");
    expect(children[1]).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps the marquee-only scope of earlier tweaks intact while dropping the bottom divider (footer task, 2026-09-12)", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // Полоса под marquee — по-прежнему индиго (правка 7 не откатывается)
    expect(children[1].className).toContain("bg-brand");
    // Нижняя черта УБРАНА (футер идёт вплотную к нижней границе
    // страницы — правка 8): последняя h-px-черта секции отсутствует
    const trailingDivider = children.filter(
      (c) => c.className.includes("h-px") && c !== children[1],
    );
    expect(trailingDivider).toHaveLength(0);
  });

  it("animates the whole track right-to-left slowly and uniformly (marquee)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    // Трек — широкий flex, лента целиком анимируется одним transform
    expect(dl.className).toContain("flex");
    expect(dl.className).toContain("w-max");
    expect(dl.className).toContain("animate-marquee");
    // Низкая скорость + равномерность — в preset: 90s linear infinite
  });

  it("pauses the marquee on hover", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    expect(dl.className).toContain("[animation-play-state:paused]");
  });

  it("clips the marquee inside a viewport wrapper (overflow-hidden + relative)", () => {
    const { container } = render(<HomeCapabilities />);
    const viewport = container.querySelector(".marquee-viewport");
    expect(viewport).not.toBeNull();
    expect(viewport!.className).toContain("overflow-hidden");
    expect(viewport!.className).toContain("relative");
    // dl — прямой ребёнок вьюпорта
    expect(viewport!.querySelector("dl")).not.toBeNull();
  });

  it("renders each badge with own border and rounding (Task 29 contract, 28 cells)", () => {
    const { container } = render(<HomeCapabilities />);
    const dl = container.querySelector("dl")!;
    // Правка 6: фон бейджа прозрачный — контракт рамки/скругления сохранён
    const badges = dl.querySelectorAll("div.bg-transparent.rounded-xl.border");
    expect(badges.length).toBe(28);
    badges.forEach((badge) => {
      // Правка 7: рамка — фирменный индиго border-brand (было border-neutral-200)
      expect(badge.className).toContain("border-brand");
      expect(badge.className).not.toContain("border-neutral-200");
      expect(badge.className).toContain("rounded-xl");
      expect(badge.className).toContain("bg-transparent");
      expect(badge.className).not.toContain("bg-neutral-100");
    });
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
    expect(dl.className).not.toContain("grid");
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

  // ── Порядок в DOM: marquee → divider → H2 → Block B → divider ──

  it("renders Block A (marquee) BEFORE the H2 in DOM order", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // [0] вьюпорт marquee, внутри — <dl> Block A
    expect(children[0].tagName).toBe("DIV");
    expect(children[0].className).toContain("marquee-viewport");
    expect(children[0].querySelector("dl")).not.toBeNull();
    // [1] <div> декоративная черта между Block A и H2 (Task 30;
    // правка 7 — цвет фирменный индиго bg-brand)
    expect(children[1].tagName).toBe("DIV");
    expect(children[1].className).toContain("h-px");
    expect(children[1].className).toContain("w-full");
    expect(children[1].className).toContain("bg-brand");
    expect(children[1].className).not.toContain("bg-neutral-200");
    // [2] <div> с H2
    expect(children[2].tagName).toBe("DIV");
    expect(children[2].querySelector("h2")).not.toBeNull();
    // [3] <div role="list"> Block B — ПОСЛЕДНИЙ ребёнок секции:
    // нижняя черта убрана (правка 8, задача футера 2026-09-12)
    expect(children[3].tagName).toBe("DIV");
    expect(children[3]).toHaveAttribute("role", "list");
    expect(children[3].className).toContain("lg:grid-cols-3");
    expect(children).toHaveLength(4);
  });

  it("renders a divider between Block A and H2 (Task 30)", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    // Первый divider стоит сразу после вьюпорта marquee и перед <div> с H2;
    // правка 7 — цвет фирменный индиго (bg-brand)
    expect(children[0].className).toContain("marquee-viewport"); // Block A
    expect(children[1].className).toContain("h-px"); // divider
    expect(children[1].className).toContain("bg-brand");
    expect(children[1].className).not.toContain("bg-neutral-200");
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

  // ── Отступы бейджей от границ страницы (Task w/n, 2026-09-12) ──
  //
  // Обе сетки 3×2 главной («Анализ временных рядов…» = HomeHero и
  // «Исследование данных…» = Block B здесь) получают собственные боковые
  // поля 24px (px-6): карточки соразмерно ужимаются (504px -> 488px при
  // ширине страницы 1600px), между бейджем и границей фоновой коробки
  // страницы появляется визуальный зазор. Бегущая строка (marquee) НЕ
  // трогается — остаётся full-bleed до границ страницы.

  it("insets the capabilities grid 24px from the page edges on both sides (px-6)", () => {
    const { container } = render(<HomeCapabilities />);
    const grid = container.querySelector(
      '[aria-label="Ключевые возможности платформы"]',
    )!;
    expect(grid).not.toBeNull();
    expect(grid.className).toContain("px-6");
  });

  it("keeps hero routes grid and capabilities grid at IDENTICAL layout classes (equal badge sizes across sections)", () => {
    const hero = render(<HomeHero />);
    const caps = render(<HomeCapabilities />);
    const heroGrid = hero.container.querySelector('[aria-label="Маршруты"]')!;
    const capGrid = caps.container.querySelector(
      '[aria-label="Ключевые возможности платформы"]',
    )!;
    expect(heroGrid).not.toBeNull();
    expect(capGrid).not.toBeNull();
    // Одинаковый набор layout-классов сетки => одинаковая ширина бейджей
    // обеих секций в браузере при любой ширине вьюпорта.
    for (const cls of [
      "grid-cols-1",
      "sm:grid-cols-2",
      "lg:grid-cols-3",
      "gap-5",
      "px-6",
    ]) {
      expect(heroGrid.className).toContain(cls);
      expect(capGrid.className).toContain(cls);
    }
  });

  it("does NOT touch the marquee: viewport and track stay full-bleed (no px-6)", () => {
    const { container } = render(<HomeCapabilities />);
    const viewport = container.querySelector(".marquee-viewport")!;
    const dl = container.querySelector("dl")!;
    expect(viewport.className).not.toContain("px-6");
    expect(dl.className).not.toContain("px-6");
  });

  // ── Нижняя черта УБРАНА (Task w/n, футер, 2026-09-12) ─────
  //
  // Между нижней границей страницы и футером черта не нужна:
  // секция заканчивается сеткой Block B (правка 8).

  it("does NOT render a divider after Block B (removed for the footer)", () => {
    const { container } = render(<HomeCapabilities />);
    const section = container.querySelector("section")!;
    const children = Array.from(section.children);
    const lastChild = children[children.length - 1];
    // Секция заканчивается Block B (role=list), а не чертой
    expect(lastChild).toHaveAttribute("role", "list");
    expect(lastChild.className).not.toContain("h-px");
    // И во всей секции не осталось нейтральных черт (нижней)
    expect(section.querySelectorAll("div.h-px.bg-neutral-200")).toHaveLength(0);
  });

  it("does NOT render the manifesto block (was removed in 2026-08-20 fix)", () => {
    const { container } = render(<HomeCapabilities />);
    expect(container.querySelector("blockquote")).not.toBeInTheDocument();
    expect(container.querySelector("cite")).not.toBeInTheDocument();
  });
});
