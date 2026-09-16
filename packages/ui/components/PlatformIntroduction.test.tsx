import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { AppShellProvider } from "../context/AppShellContext";
import { PlatformIntroduction } from "./PlatformIntroduction";

describe("PlatformIntroduction", () => {
  it("renders all three anchor targets in the shared page composition", () => {
    render(
      <AppShellProvider>
        <PlatformIntroduction />
      </AppShellProvider>,
    );

    expect(document.getElementById("applied-tasks")).toBeInTheDocument();
    expect(document.getElementById("research-stages")).toBeInTheDocument();
    expect(document.getElementById("platform-navigation")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Подробная навигация по платформе" }),
    ).toBeInTheDocument();
  });

  // Task NAVIG-1 (коммит ec4ffce): черта над заголовком — фирменный индиго
  // (border-brand, паттерн главной страницы); серая border-neutral-200
  // запрещена guard-ом. Тест-файл синхронизирован с фактической семантикой
  // компонента (предсущественная рассинхронизация baseline 77f138f,
  // выявлена полной регрессией Task NAVBG-2).
  it("renders a full-width indigo rule above the platform navigation title", () => {
    render(
      <AppShellProvider>
        <PlatformIntroduction />
      </AppShellProvider>,
    );

    const heading = screen.getByRole("heading", {
      level: 2,
      name: "Подробная навигация по платформе",
    });
    const ruledHeading = heading.parentElement;

    expect(ruledHeading).not.toBeNull();
    // Guard по токенам: "border-brand" содержит подстроку "border-b",
    // поэтому сравниваем отдельные классы, а не подстроки.
    const classes = (ruledHeading?.className ?? "").split(/\s+/);
    expect(classes).toContain("w-full");
    expect(classes).toContain("border-t");
    expect(classes).toContain("border-brand");
    expect(classes).not.toContain("border-neutral-200");
  });

  it("renders NO bottom gray separator (removed by NAVIG-1 — like the home page)", () => {
    render(
      <AppShellProvider>
        <PlatformIntroduction />
      </AppShellProvider>,
    );

    expect(screen.queryByTestId("page-bottom-separator")).toBeNull();
  });
});
