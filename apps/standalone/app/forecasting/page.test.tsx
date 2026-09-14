// apps/standalone/app/forecasting/page.test.tsx
//
// Контракт страницы /forecasting: плейсхолдер ModulePlaceholder заменён
// живым компонентом этапа TsAnalysisForecasting (шестой этап пайплайна).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import Page from "./page";
import { STAGE_DEFS } from "@cisstat/ui/lib/stages";

jest.mock("@cisstat/ui/context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: null,
    stages: Object.fromEntries(STAGE_DEFS.map((s) => [s.key, "pending"])),
    lastActiveStage: null,
    sessionLoading: false,
    refreshSession: jest.fn(),
    log: [],
    addLogEntry: jest.fn(),
    clearLog: jest.fn(),
  }),
}));

// Глобальный fetch не нужен: без датасета вкладка честно встаёт в гейт
// до любых обращений к API.
describe("Standalone /forecasting page", () => {
  it("renders TsAnalysisForecasting (not ModulePlaceholder) with the stage heading", () => {
    render(<Page />);
    expect(screen.getByRole("heading", { name: "Прогнозирование" })).toBeInTheDocument();
    expect(screen.getByTestId("no-dataset-gate")).toHaveTextContent(/Загрузите датасет/);
  });
});
