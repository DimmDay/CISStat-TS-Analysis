// apps/standalone/app/education/page.test.tsx
//
// Task EDU-1 — контракт страницы «Обучение и база знаний» (/education):
// маршрут standalone рендерит общий хаб @cisstat/ui без обёрток,
// по паттерну хаба «Задачи» (apps/standalone/app/tasks/page.tsx).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import Page from "./page";

describe("Standalone /education page", () => {
  it("рендерит хаб «Обучение и база знаний» (@cisstat/ui EducationKnowledgeBase)", () => {
    render(<Page />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Обучение и база знаний" }),
    ).toBeInTheDocument();
  });

  it("хаб содержит обе секции (Библиотека активна по умолчанию)", () => {
    render(<Page />);
    expect(screen.getByRole("button", { name: "Библиотека" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Словарь терминов" })).toBeInTheDocument();
  });
});
