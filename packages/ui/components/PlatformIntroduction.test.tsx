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
});
