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
    targetColumn: null,
    sessionLoading: false,
    refreshSession: jest.fn(),
    // PROGR-4 (§6.1): log/addLogEntry/clearLog удалены из shell-контекста.
  }),
}));

// Глобальный fetch не нужен: без датасета вкладка честно встаёт в гейт
// до любых обращений к API.
describe("Standalone /forecasting page", () => {
  it("renders TsAnalysisForecasting (not ModulePlaceholder) with the stage heading", () => {
    render(<Page />);
    // Заголовок левой колонки «Forecasting» (UI-FORECAST-HDR-1,
    // переименование «Прогнозирование» -- прямой пункт постановки,
    // прецедент UI-EDA-HDR-2 «Exploration»; модульное имя на других
    // поверхностях -- «Прогнозирование»).
    expect(screen.getByRole("heading", { name: "Forecasting" })).toBeInTheDocument();
    expect(screen.getByTestId("no-dataset-gate")).toHaveTextContent(/Загрузите датасет/);
  });
});
