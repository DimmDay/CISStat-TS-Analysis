// packages/ui/components/NavigatorHero.test.tsx
//
// Тесты для NavigatorHero — чисто презентационный компонент, проверяет
// структуру верхней части страницы "Навигатор":
//   - заголовок H1
//   - 6 числовых бейджей (с цифрами 1-6 и утверждёнными текстами)
//   - 2 полубейджа на 1/2 ширины каждый: «Для кого» и «Для чего»
//     (после правки тимлида #1 верхний дублирующий блок убран —
//     заголовки «Для кого/Для чего» живут прямо в полубейджах)

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorHero } from "./NavigatorHero";
import {
  NAVIGATOR_BADGES,
  AUDIENCE_TEXT,
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

  it("renders 'Для кого:' and 'Для чего:' labels inside the half-width badges", () => {
    render(<NavigatorHero />);
    expect(screen.getByText("Для кого:")).toBeInTheDocument();
    expect(screen.getByText("Для чего:")).toBeInTheDocument();
  });

  it("renders audience and purpose texts exactly once (only in the half-width badges)", () => {
    render(<NavigatorHero />);
    // После правки #1 верхний дублирующий блок убран — тексты живут
    // только в двух полубейджах, по одному вхождению каждого.
    expect(screen.getAllByText(AUDIENCE_TEXT)).toHaveLength(1);
    expect(screen.getAllByText(PURPOSE_TEXT)).toHaveLength(1);
  });

  it("renders exactly 2 half-width badges (Check icon + label + text)", () => {
    render(<NavigatorHero />);
    // 2 полубейджа: каждый содержит AUDIENCE_LABEL или PURPOSE_LABEL
    // и соответствующий текст.
    const audienceLabel = screen.getByText("Для кого:");
    const purposeLabel = screen.getByText("Для чего:");
    expect(audienceLabel).toBeInTheDocument();
    expect(purposeLabel).toBeInTheDocument();
    // Каждый заголовок находится внутри карточки-полубейджа.
    const audienceCard = audienceLabel.closest(".rounded-lg");
    const purposeCard = purposeLabel.closest(".rounded-lg");
    expect(audienceCard).not.toBeNull();
    expect(purposeCard).not.toBeNull();
    expect(audienceCard).not.toBe(purposeCard);
  });
});
