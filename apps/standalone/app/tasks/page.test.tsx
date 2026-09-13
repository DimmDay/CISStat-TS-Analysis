// apps/standalone/app/tasks/page.test.tsx
//
// Контракт страницы /tasks (spec_tasks_ia.md): плейсхолдер ModulePlaceholder
// заменён живым хабом TasksHub. Хаб читает сессию из AppShellContext —
// в тесте контекст мокается на свежую сессию.

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import Page from "./page";
import { STAGE_DEFS } from "@cisstat/ui/lib/stages";

// Мок по алиасу @cisstat/ui -- moduleNameMapper сводит его к тому же
// файлу packages/ui/context/AppShellContext, который импортирует TasksHub.
jest.mock("@cisstat/ui/context/AppShellContext", () => ({
  useAppShell: () => ({
    stages: Object.fromEntries(STAGE_DEFS.map((s) => [s.key, "pending"])),
    log: [],
  }),
}));

describe("Standalone /tasks page", () => {
  it("renders the TasksHub (not ModulePlaceholder) with the hub heading", () => {
    render(<Page />);
    expect(screen.getByRole("heading", { level: 1, name: "Задачи" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /Задачи на основе прогноза/i })).toBeInTheDocument();
    expect(screen.queryByText("Модуль в разработке.")).toBeNull();
  });
});
