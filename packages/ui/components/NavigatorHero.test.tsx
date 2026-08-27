// packages/ui/components/NavigatorHero.test.tsx
//
// Тесты для NavigatorHero — верхняя часть страницы «Навигатор».
// Task 26: 6 бейджей трансформированы в chevron-стрелки (светло-серый фон,
// зелёная цифра) + текст ниже (заголовок без нумерации + поддерживающий текст).
// CollapsibleHalfBadge «Для кого»/«Для чего» — без изменений.
//
// Поведение:
//   - Заголовок H1 — статичный
//   - 6 chevron-стрелок — статичные, в каждой зелёная цифра в кружочке
//   - 6 текстовых блоков ниже стрелок: заголовок (БЕЗ номера) + subtitle
//   - 2 полубейджа «Для кого» / «Для чего» — раскрывающиеся (expanded default)
//   - Состояние каждого полубейджа НЕЗАВИСИМО (не accordion)
//   - a11y: button с aria-expanded, aria-controls на контейнер с текстом

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { NavigatorHero } from "./NavigatorHero";
import {
  NAVIGATOR_BADGES,
  NAVIGATOR_SECTION_ROUTES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

describe("NavigatorHero", () => {
  // ── Вводная секция и маршруты по странице ─────────────────────────

  it("renders the page H1 title", () => {
    render(<NavigatorHero />);
    expect(
      screen.getByRole("heading", { level: 1, name: /Знакомство с платформой/i }),
    ).toBeInTheDocument();
  });

  it("renders the H1 title centered (Task 31)", () => {
    render(<NavigatorHero />);
    const h1 = screen.getByRole("heading", {
      level: 1,
      name: /Знакомство с платформой/i,
    });
    expect(h1.className).toContain("text-center");
  });

  it("renders three route badges with stable anchor links", () => {
    render(<NavigatorHero />);

    expect(
      screen.getByRole("navigation", { name: "Разделы знакомства с платформой" }),
    ).toBeInTheDocument();
    expect(NAVIGATOR_SECTION_ROUTES).toHaveLength(3);
    NAVIGATOR_SECTION_ROUTES.forEach((route) => {
      const link = screen.getByRole("link", { name: new RegExp(route.title, "i") });
      expect(link).toHaveAttribute("href", route.href);
    });
  });

  it("reuses the visual states of route cards from the home page", () => {
    const { container } = render(<NavigatorHero />);
    const links = container.querySelectorAll('nav[aria-label="Разделы знакомства с платформой"] > a');
    expect(links).toHaveLength(3);
    links.forEach((link) => {
      expect(link.className).toContain("border-brand/60");
      expect(link.className).toContain("bg-brand-light/60");
      expect(link.className).toContain("hover:border-brand/90");
      expect(link.className).toContain("hover:bg-brand-light/90");
    });
  });

  it("renders the applied tasks navigator and the research stages as anchor targets", () => {
    render(<NavigatorHero />);
    expect(document.getElementById("applied-tasks")).toBeInTheDocument();
    expect(document.getElementById("research-stages")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Предметная область" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Основная задача" })).toBeInTheDocument();
    expect(screen.queryByText(/Наполнение блока согласуем в следующей задаче/i)).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: /Ключевые этапы исследования ряда/i }),
    ).toBeInTheDocument();
  });

  it("renders the applied tasks section under the new title between two full-width gray rules", () => {
    render(<NavigatorHero />);

    const heading = screen.getByRole("heading", {
      level: 2,
      name: "Примеры прикладных задач",
    });
    expect(heading).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        level: 2,
        name: "Прикладные задачи, решаемые платформой",
      }),
    ).toBeNull();

    const ruledHeading = heading.parentElement;
    expect(ruledHeading).not.toBeNull();
    expect(ruledHeading?.className).toContain("w-full");
    expect(ruledHeading?.className).toContain("border-y");
    expect(ruledHeading?.className).toContain("border-neutral-200");
  });

  // ── 6 chevron-стрелок с цифрами (Task 26) ─────────────────────────

  it("renders all 6 step numbers inside chevron arrows", () => {
    render(<NavigatorHero />);
    const ariaContainer = document.querySelector('[aria-label="Этапы анализа"]');
    expect(ariaContainer).not.toBeNull();
    // aria-hidden контейнер содержит цифры (не видны скринридеру, но в DOM)
    const hiddenNums = ariaContainer!.querySelectorAll("[aria-hidden='true']");
    expect(hiddenNums.length).toBeGreaterThanOrEqual(6);
    NAVIGATOR_BADGES.forEach((badge) => {
      expect(ariaContainer!.textContent).toContain(String(badge.num));
    });
  });

  // ── Заголовки БЕЗ нумерации (Task 26, обновлено) ─────────────────

  it("renders badge titles below the chevron row WITHOUT numbering", () => {
    render(<NavigatorHero />);
    // Заголовки без «N. » — только текст label
    expect(screen.getByText("Структура данных", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Качество данных", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Подготовка к исследованию", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Свойства ряда", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Семейство моделей", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Строим прогноз", { selector: "p" })).toBeInTheDocument();
  });

  it("renders subtitle text below each badge title", () => {
    render(<NavigatorHero />);
    NAVIGATOR_BADGES.forEach((badge) => {
      if (badge.subtitle) {
        expect(screen.getByText(badge.subtitle)).toBeInTheDocument();
      }
    });
  });

  it("does NOT render old long badge labels", () => {
    // Регрессионный тест: старые формулировки с глаголами больше не показываются
    render(<NavigatorHero />);
    expect(screen.queryByText("Определяем структуру данных")).toBeNull();
    expect(screen.queryByText("Проверяем качество данных")).toBeNull();
    expect(screen.queryByText("Осуществляем подготовку данных к исследованию")).toBeNull();
  });

  it("does NOT render numbered titles (e.g. '1. Структура данных')", () => {
    // Регрессионный тест: нумерация убрана из заголовков
    render(<NavigatorHero />);
    expect(screen.queryByText("1. Структура данных")).toBeNull();
    expect(screen.queryByText("2. Качество данных")).toBeNull();
    expect(screen.queryByText("3. Подготовка к исследованию")).toBeNull();
    expect(screen.queryByText("4. Свойства ряда")).toBeNull();
    expect(screen.queryByText("5. Семейство моделей")).toBeNull();
    expect(screen.queryByText("6. Строим прогноз")).toBeNull();
  });

  // ── CollapsibleHalfBadge «Для кого» / «Для чего» (без изменений) ─

  it("renders 'Для кого:' and 'Для чего:' labels inside the half-width badges (always visible)", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_LABEL)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_LABEL)).toBeInTheDocument();
  });

  it("renders audience and purpose texts by default and lets each badge collapse independently", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();

    fireEvent.click(screen.getByText(AUDIENCE_LABEL));
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();

    fireEvent.click(screen.getByText(PURPOSE_LABEL));
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
  });

  it("renders exactly 2 collapsible half-width badges with proper trigger buttons", () => {
    render(<NavigatorHero />);
    const triggers = screen.getAllByRole("button");
    const halfBadgeTriggers = triggers.filter(
      (btn) =>
        btn.textContent?.includes(AUDIENCE_LABEL) ||
        btn.textContent?.includes(PURPOSE_LABEL),
    );
    expect(halfBadgeTriggers).toHaveLength(2);

    const audienceCard = screen
      .getByText(AUDIENCE_LABEL)
      .closest(".rounded-lg");
    const purposeCard = screen
      .getByText(PURPOSE_LABEL)
      .closest(".rounded-lg");
    expect(audienceCard).not.toBeNull();
    expect(purposeCard).not.toBeNull();
    expect(audienceCard).not.toBe(purposeCard);
  });

  // ── a11y: раскрывающееся поведение (открыты по умолчанию) ──────────

  it("audience text is visible by default (expanded state)", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
  });

  it("purpose text is visible by default (expanded state)", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
  });

  it("toggles audience text visibility on click (and updates aria-expanded)", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();

    fireEvent.click(trigger!);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
  });

  it("toggles purpose text visibility on click (and updates aria-expanded)", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(PURPOSE_LABEL).closest("button");
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();

    fireEvent.click(trigger!);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();
  });

  it("audience and purpose badges are independent (collapsing one does not collapse the other)", () => {
    render(<NavigatorHero />);
    const audienceTrigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    const purposeTrigger = screen.getByText(PURPOSE_LABEL).closest("button");

    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
    expect(audienceTrigger).toHaveAttribute("aria-expanded", "true");
    expect(purposeTrigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(audienceTrigger!);
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
    expect(audienceTrigger).toHaveAttribute("aria-expanded", "false");
    expect(purposeTrigger).toHaveAttribute("aria-expanded", "true");
  });

  it("re-clicking a collapsed trigger expands the text back", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");

    fireEvent.click(trigger!);
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger!);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("trigger has aria-controls pointing to the text content container", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    expect(trigger).not.toBeNull();

    const controlsId = trigger!.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(controlsId?.length).toBeGreaterThan(0);

    const panel = document.getElementById(controlsId!);
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain(AUDIENCE_TEXT);
  });

  it("chevron icon is present in both badges and toggles direction on expand", () => {
    render(<NavigatorHero />);

    const upChevrons = screen.getAllByLabelText(/chevron up/i);
    expect(upChevrons).toHaveLength(2);

    const audienceTrigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    fireEvent.click(audienceTrigger!);

    const remainingUpChevrons = screen.getAllByLabelText(/chevron up/i);
    expect(remainingUpChevrons).toHaveLength(1);

    const downChevrons = screen.getAllByLabelText(/chevron down/i);
    expect(downChevrons).toHaveLength(1);
  });

  // ── Декоративный разделитель ─────────────────────────────────────

  it("renders a decorative separator (aria-hidden divider) after the hero section", () => {
    render(<NavigatorHero />);
    const dividers = document.querySelectorAll("[aria-hidden='true']");
    // По крайней мере один скрытый элемент-разделитель
    expect(dividers.length).toBeGreaterThanOrEqual(1);
  });
});
