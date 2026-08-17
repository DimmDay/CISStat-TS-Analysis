// packages/ui/components/NavigatorHero.test.tsx
//
// Тесты для NavigatorHero — чисто презентационный компонент, проверяет
// структуру верхней части страницы "Навигатор":
//   - заголовок H1
//   - 6 числовых бейджей (с цифрами 1-6 и утверждёнными текстами)
//   - ряд "Для кого" / "Для чего" с утверждёнными текстами
//   - 2 полубейджа на 1/2 ширины каждый

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

  it("renders 'Для кого:' and 'Для чего:' labels", () => {
    render(<NavigatorHero />);
    expect(screen.getByText("Для кого:")).toBeInTheDocument();
    expect(screen.getByText("Для чего:")).toBeInTheDocument();
  });

  it("renders audience and purpose texts at least once", () => {
    render(<NavigatorHero />);
    // Тексты присутствуют в ряду "Для кого/Для чего" и в 2 полубейджах.
    // Проверяем хотя бы одно вхождение через getAllByText.
    expect(screen.getAllByText(AUDIENCE_TEXT).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(PURPOSE_TEXT).length).toBeGreaterThanOrEqual(1);
  });

  it("renders exactly 2 half-width badges (Check icon + text)", () => {
    render(<NavigatorHero />);
    // 2 полубейджа: каждый содержит текст AUDIENCE_TEXT или PURPOSE_TEXT
    // (в дополнение к ряду "Для кого/Для чего", где они тоже есть).
    // Считаем по 2 — по одному на каждый полубейдж, идём getAllByText.
    const audienceMatches = screen.getAllByText(AUDIENCE_TEXT);
    const purposeMatches = screen.getAllByText(PURPOSE_TEXT);
    // В ряду "Для кого/Для чего" + 2 полубейджа = 2 вхождения каждого.
    expect(audienceMatches).toHaveLength(2);
    expect(purposeMatches).toHaveLength(2);
  });
});
