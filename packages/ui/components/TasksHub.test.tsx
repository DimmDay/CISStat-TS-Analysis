// packages/ui/components/TasksHub.test.tsx
//
// Тесты хаба «Задачи» (spec_tasks_ia.md §4, §8):
//   - шапка + сетка 4 карточек (TaskCard) с ролью list;
//   - три состояния по сессии: blocked (свежая), awaiting (частичный
//     прогресс), available (контракт выполнен);
//   - некликабельные состояния НЕ ссылки; available — ссылки на /tasks/<id>;
//   - причины недоступности видны пользователю.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { TasksHub } from "./TasksHub";
import { STAGE_DEFS, StageStatus } from "../lib/stages";

// TasksHub читает сессию из AppShellContext (stages, гидратация
// GET /v1/session/current) — мокаем на фиксированный сценарий.
let mockStages: Record<string, StageStatus> = {};
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    stages: mockStages,
    log: [],
  }),
}));

const stagesOf = (over: Record<string, StageStatus>) =>
  Object.fromEntries(STAGE_DEFS.map((s) => [s.key, over[s.key] ?? "pending"]));

const TASK_TITLES = [
  "Сценарии",
  "Причины",
  "Принятие решений",
  "Мониторинг прогноза",
];

afterEach(() => {
  mockStages = {};
});

describe("TasksHub", () => {
  it("renders the hub header and a list of exactly 4 task cards", () => {
    mockStages = stagesOf({});
    render(<TasksHub />);

    expect(screen.getByRole("heading", { level: 1, name: "Задачи" })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /Задачи на основе прогноза/i });
    expect(list.children).toHaveLength(4);
    TASK_TITLES.forEach((title) => {
      expect(screen.getByText(title)).toBeInTheDocument();
    });
  });

  it("fresh session: all 4 cards are blocked and NONE is a link", () => {
    mockStages = stagesOf({});
    const { container } = render(<TasksHub />);

    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(0);
    // Причина заблокированного состояния видна на каждой карточке.
    const reasons = screen.getAllByText(/Начните с этапа Загрузка/);
    expect(reasons).toHaveLength(4);
    // Состояние озвучено для a11y.
    const groups = screen.getAllByRole("group", { name: /недоступна/i });
    expect(groups).toHaveLength(4);
  });

  it("after Modeling: Сценарии and Причины are links, forecast tasks are awaiting with reason", () => {
    mockStages = stagesOf({ validation: "done", modeling: "done" });
    const { container } = render(<TasksHub />);

    const links = Array.from(container.querySelectorAll("a"));
    expect(links.map((l) => l.getAttribute("href"))).toEqual(
      expect.arrayContaining(["/tasks/scenarios", "/tasks/causes"])
    );
    expect(links).toHaveLength(2);

    // Прогнозные задачи ещё не доступны — причина называет этап.
    const awaiting = screen.getAllByText(/Станет доступна после этапа Прогнозирование/);
    expect(awaiting).toHaveLength(2);
  });

  it("partial pipeline (validation done only): all cards still locked, but awaiting (amber), not blocked", () => {
    mockStages = stagesOf({ validation: "done" });
    const { container } = render(<TasksHub />);

    expect(container.querySelectorAll("a")).toHaveLength(0);
    // Модельные задачи ждут Моделирование.
    expect(screen.getAllByText(/Станет доступна после этапа Моделирование/)).toHaveLength(2);
    // Прогнозные ждут Прогнозирование (пайплайн уже начат — не blocked).
    expect(screen.getAllByText(/Станет доступна после этапа Прогнозирование/)).toHaveLength(2);
    expect(screen.queryByText(/Начните с этапа Загрузка/)).toBeNull();
  });

  it("full pipeline: all 4 cards are links to their routes", () => {
    mockStages = stagesOf({
      upload: "done",
      validation: "done",
      preprocessing: "done",
      eda: "done",
      modeling: "done",
      forecasting: "done",
    });
    const { container } = render(<TasksHub />);

    const hrefs = Array.from(container.querySelectorAll("a")).map((a) =>
      a.getAttribute("href")
    );
    expect(hrefs).toEqual([
      "/tasks/scenarios",
      "/tasks/causes",
      "/tasks/decisions",
      "/tasks/monitoring",
    ]);
  });

  it("cards inherit the RouteCard visual DNA (badge-card with brand border)", () => {
    mockStages = stagesOf({ validation: "done", modeling: "done" });
    const { container } = render(<TasksHub />);

    const firstCard = container.querySelector("a");
    expect(firstCard?.className).toContain("rounded-xl");
    expect(firstCard?.className).toContain("border-brand/60");
  });
});
