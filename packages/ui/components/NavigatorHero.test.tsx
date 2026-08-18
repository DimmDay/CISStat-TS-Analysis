// packages/ui/components/NavigatorHero.test.tsx
//
// Тесты для NavigatorHero — верхняя часть главной страницы "Навигатор".
// После Task 21 полубейджи «Для кого» и «Для чего» стали раскрывающимися
// (по типу селектора): в закрытом состоянии виден только заголовок + чеврон,
// при клике на триггер-кнопку справа — раскрывается текст.
//
// Поведение:
//   - Заголовок H1 — статичный
//   - 6 числовых бейджей — статичные
//   - 2 полубейджа «Для кого» / «Для чего» — раскрывающиеся (collapsed default)
//   - Состояние каждого полубейджа НЕЗАВИСИМО (не accordion)
//   - a11y: button с aria-expanded, aria-controls на контейнер с текстом

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { NavigatorHero } from "./NavigatorHero";
import {
  NAVIGATOR_BADGES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

describe("NavigatorHero", () => {
  it("renders the H1 title", () => {
    render(<NavigatorHero />);
    expect(
      screen.getByRole("heading", { level: 1, name: /Анализ временных рядов — от файла до прогноза/i }),
    ).toBeInTheDocument();
  });

  it("renders all 6 numbered badges with correct numbers", () => {
    render(<NavigatorHero />);
    const list = screen.getByRole("list", { name: /Этапы анализа/i });
    expect(list).toBeInTheDocument();
    const items = list.querySelectorAll("li");
    expect(items).toHaveLength(6);
    NAVIGATOR_BADGES.forEach((badge) => {
      expect(screen.getByText(badge.label)).toBeInTheDocument();
    });
  });

  // ── Обновлённые под новое поведение (Task 21) ────────────────────────

  it("renders 'Для кого:' and 'Для чего:' labels inside the half-width badges (always visible)", () => {
    // Заголовок живёт внутри <button> триггера и ВИДЕН ВСЕГДА —
    // в закрытом и в раскрытом состояниях (это и есть точка входа).
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_LABEL)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_LABEL)).toBeInTheDocument();
  });

  it("renders audience and purpose texts only when their badges are expanded (collapsed by default)", () => {
    // По умолчанию оба полубейджа СВОРНУТЫ — текст не рендерится.
    // Это и есть поведение «по типу селектора»: закрыто, пока не кликнули.
    render(<NavigatorHero />);
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();

    // Раскрываем «Для кого»
    fireEvent.click(screen.getByText(AUDIENCE_LABEL));
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    // «Для чего» всё ещё свёрнут
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();

    // Раскрываем «Для чего»
    fireEvent.click(screen.getByText(PURPOSE_LABEL));
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
    // «Для кого» всё ещё раскрыт — состояния независимы
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
  });

  it("renders exactly 2 collapsible half-width badges with proper trigger buttons", () => {
    render(<NavigatorHero />);
    // Две кнопки-триггера (по одной на каждый полубейдж).
    const triggers = screen.getAllByRole("button");
    const halfBadgeTriggers = triggers.filter(
      (btn) =>
        btn.textContent?.includes(AUDIENCE_LABEL) ||
        btn.textContent?.includes(PURPOSE_LABEL),
    );
    expect(halfBadgeTriggers).toHaveLength(2);

    // Каждый заголовок находится внутри карточки-полубейджа.
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

  // ── Новые тесты Task 21 — раскрывающееся поведение ──────────────────

  it("audience text is hidden by default (collapsed state)", () => {
    render(<NavigatorHero />);
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
  });

  it("purpose text is hidden by default (collapsed state)", () => {
    render(<NavigatorHero />);
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();
  });

  it("toggles audience text visibility on click (and updates aria-expanded)", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    expect(trigger).not.toBeNull();
    // По умолчанию свёрнут
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();

    // Раскрытие
    fireEvent.click(trigger!);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
  });

  it("toggles purpose text visibility on click (and updates aria-expanded)", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(PURPOSE_LABEL).closest("button");
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();

    fireEvent.click(trigger!);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
  });

  it("audience and purpose badges are independent (opening one does not open the other)", () => {
    render(<NavigatorHero />);
    const audienceTrigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    const purposeTrigger = screen.getByText(PURPOSE_LABEL).closest("button");

    fireEvent.click(audienceTrigger!);
    // audience раскрыт, purpose всё ещё свёрнут
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(PURPOSE_TEXT)).toBeNull();
    expect(audienceTrigger).toHaveAttribute("aria-expanded", "true");
    expect(purposeTrigger).toHaveAttribute("aria-expanded", "false");

    // Открываем purpose — audience остаётся открытым
    fireEvent.click(purposeTrigger!);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();
    expect(audienceTrigger).toHaveAttribute("aria-expanded", "true");
    expect(purposeTrigger).toHaveAttribute("aria-expanded", "true");
  });

  it("re-clicking a trigger collapses the text back", () => {
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");

    // Раскрытие
    fireEvent.click(trigger!);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Сворачивание повторным кликом
    fireEvent.click(trigger!);
    expect(screen.queryByText(AUDIENCE_TEXT)).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("trigger has aria-controls pointing to the text content container", () => {
    // a11y-контракт: aria-controls на кнопке должен ссылаться на id
    // контейнера с текстом (скринридеры используют это для анонса).
    render(<NavigatorHero />);
    const trigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    expect(trigger).not.toBeNull();

    // До раскрытия контейнера с текстом нет в DOM — aria-controls всё равно
    // должен быть установлен (значение = будущий id панели).
    const controlsId = trigger!.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(controlsId?.length).toBeGreaterThan(0);

    // После раскрытия — контейнер с этим id существует в DOM.
    fireEvent.click(trigger!);
    const panel = document.getElementById(controlsId!);
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain(AUDIENCE_TEXT);
  });

  it("chevron icon is present in both badges and toggles direction on expand", () => {
    // Иконка чеврона — это аффорданс: вниз (collapsed) → вверх (expanded).
    // Используем role="img" с aria-label для проверки нахождения в DOM.
    render(<NavigatorHero />);

    // В закрытом состоянии — два «chevron-down» (по одному на каждый бейдж).
    const downChevrons = screen.getAllByLabelText(/chevron down/i);
    expect(downChevrons).toHaveLength(2);

    // Раскрываем «Для кого» → в этом бейдже chevron-up, во втором — всё ещё down.
    const audienceTrigger = screen.getByText(AUDIENCE_LABEL).closest("button");
    fireEvent.click(audienceTrigger!);

    const upChevrons = screen.getAllByLabelText(/chevron up/i);
    expect(upChevrons).toHaveLength(1);

    const remainingDownChevrons = screen.getAllByLabelText(/chevron down/i);
    expect(remainingDownChevrons).toHaveLength(1);
  });
});
