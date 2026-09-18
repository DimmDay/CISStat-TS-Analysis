// packages/ui/components/TaskArtifactRibbon.test.tsx
//
// Тесты ленты артефактов сессии на хабе «Задачи» (v1.1,
// spec_tasks_ia_addendum_v1_1.md §9.2):
//   - Лента рисует ТОЛЬКО реально существующие артефакты (честная
//     маркировка, а не фиктивное заполнение места); отсутствующий
//     артефакт НЕ рисуется как «пусто» — его просто нет в ленте.
//   - Свежая сессия (ни один этап не done) — лента НЕ рендерится вовсе.
//   - Наполнение чипов — из уже посчитанных фактов сессии:
//     Датасет — activeDataset из AppShellContext; Model Card — точечный
//     вызов GET /v1/session/modeling/card (fetchCardSummaries);
//     Прогноз — факт наличия (stages.forecasting === "done") без похода
//     за деталями (состав чипа детализируется вместе с v2 «Мониторинга»).
//   - Порядок чипов = порядок пайплайна артефактов (§4):
//     validated -> model_card -> forecast_run.
//   - Переиспользование Metric-карточек (по образцу DatasetPassportPanel),
//     а не изобретение нового чипа.
//   - Отказ похода за картами НЕ ломает ленту: чип деградирует к
//     факту «создана» (fail-soft), лента остаётся честной.

import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { TaskArtifactRibbon } from "./TaskArtifactRibbon";
import { STAGE_DEFS, StageStatus } from "../lib/stages";

// Сессия — из AppShellContext (гидратация GET /v1/session/current):
// мокаем на фиксированный сценарий (тот же паттерн, что в TasksHub.test).
let mockStages: Record<string, StageStatus> = {};
let mockActiveDataset: { name: string; rows: number; sizeLabel: string } | null =
  null;
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    stages: mockStages,
    activeDataset: mockActiveDataset,
    log: [],
  }),
}));

// Точечный поход за списком Model Card (GET /v1/session/modeling/card)
// мокается на уровне модуля lib/forecasting.
const fetchCardSummaries = jest.fn();
jest.mock("../lib/forecasting", () => ({
  fetchCardSummaries: (...args: unknown[]) => fetchCardSummaries(...args),
}));

const stagesOf = (over: Record<string, StageStatus>) =>
  Object.fromEntries(STAGE_DEFS.map((s) => [s.key, over[s.key] ?? "pending"]));

const DATASET = { name: "Month_Value_1.csv", rows: 240, sizeLabel: "12 КБ" };

const CARDS = [
  {
    card_id: "c-1",
    model_id: "ets",
    model_name: "ETS",
    selection_kind: "tuned",
    horizon: 6,
    fingerprint: "a".repeat(64),
    created_at: "2026-09-18T10:00:00+00:00",
  },
  {
    card_id: "c-2",
    model_id: "tbats",
    model_name: "TBATS",
    selection_kind: "single",
    horizon: 6,
    fingerprint: "b".repeat(64),
    created_at: "2026-09-18T11:00:00+00:00",
  },
];

beforeEach(() => {
  mockStages = {};
  mockActiveDataset = null;
  fetchCardSummaries.mockReset();
  fetchCardSummaries.mockResolvedValue([]);
});

describe("TaskArtifactRibbon: честная маркировка (§9.2)", () => {
  it("fresh session: лента не рендерится вовсе (не «пусто», а её нет)", () => {
    mockStages = stagesOf({});
    const { container } = render(<TaskArtifactRibbon />);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("list", { name: /Артефакты сессии/ })).toBeNull();
    // Поход за картами не выполняется — артефакта model_card нет.
    expect(fetchCardSummaries).not.toHaveBeenCalled();
  });

  it("validation done: только чип Датасета с именем и числом наблюдений", async () => {
    mockStages = stagesOf({ validation: "done" });
    mockActiveDataset = DATASET;
    const { container } = render(<TaskArtifactRibbon />);

    const list = screen.getByRole("list", { name: /Артефакты сессии/ });
    expect(list.children).toHaveLength(1);
    expect(screen.getByText("Month_Value_1.csv · 240 набл.")).toBeInTheDocument();
    // Model Card и Прогноз отсутствуют — их просто нет в ленте.
    expect(screen.queryByText("Model Card")).toBeNull();
    expect(screen.queryByText("Прогноз")).toBeNull();
    expect(container.querySelectorAll("[role='listitem']")).toHaveLength(1);
    expect(fetchCardSummaries).not.toHaveBeenCalled();
  });

  it("modeling done (без валидации — синтетика): только чип Model Card, поход за картами выполняется", async () => {
    mockStages = stagesOf({ modeling: "done" });
    fetchCardSummaries.mockResolvedValue([CARDS[0]]);
    const { container } = render(<TaskArtifactRibbon />);

    const list = screen.getByRole("list", { name: /Артефакты сессии/ });
    await waitFor(() => {
      expect(screen.getByText("ETS")).toBeInTheDocument();
    });
    expect(list.children).toHaveLength(1);
    expect(container.querySelectorAll("[role='listitem']")).toHaveLength(1);
    expect(fetchCardSummaries).toHaveBeenCalledTimes(1);
    // Датасета и Прогноза в ленте нет.
    expect(screen.queryByText(/Датасет/)).toBeNull();
    expect(screen.queryByText("построен")).toBeNull();
  });

  it("полный пайплайн: три чипа в порядке пайплайна (Датасет -> Model Card -> Прогноз)", async () => {
    mockStages = stagesOf({
      validation: "done",
      modeling: "done",
      forecasting: "done",
    });
    mockActiveDataset = DATASET;
    fetchCardSummaries.mockResolvedValue(CARDS);
    const { container } = render(<TaskArtifactRibbon />);

    const list = screen.getByRole("list", { name: /Артефакты сессии/ });
    await waitFor(() => {
      expect(screen.getByText("TBATS × 2")).toBeInTheDocument();
    });
    const items = Array.from(container.querySelectorAll("[role='listitem']"));
    expect(items).toHaveLength(3);
    // Порядок = порядок артефактов §4 (validated -> model_card -> forecast_run).
    const labels = items.map(
      (item) => item.querySelector(".text-xs")?.textContent
    );
    expect(labels).toEqual(["Датасет", "Model Card", "Прогноз"]);
  });
});

describe("TaskArtifactRibbon: наполнение чипов факами сессии", () => {
  it("артефакт validated есть, но activeDataset не гидратирован: чип деградирует к факту «загружен»", () => {
    mockStages = stagesOf({ validation: "done" });
    mockActiveDataset = null;
    render(<TaskArtifactRibbon />);

    expect(screen.getByText("загружен")).toBeInTheDocument();
  });

  it("model_card: одна карта — имя модели из списка карт (GET /card)", async () => {
    mockStages = stagesOf({ modeling: "done" });
    fetchCardSummaries.mockResolvedValue([CARDS[0]]);
    render(<TaskArtifactRibbon />);

    await waitFor(() => {
      expect(screen.getByText("ETS")).toBeInTheDocument();
    });
  });

  it("model_card: несколько карт — последняя по created_at + счётчик «× N»", async () => {
    mockStages = stagesOf({ modeling: "done" });
    fetchCardSummaries.mockResolvedValue(CARDS);
    render(<TaskArtifactRibbon />);

    await waitFor(() => {
      expect(screen.getByText("TBATS × 2")).toBeInTheDocument();
    });
  });

  it("model_card: список карт пуст или поход не удался — чип остаётся с фактом «создана» (fail-soft)", async () => {
    mockStages = stagesOf({ modeling: "done" });
    fetchCardSummaries.mockRejectedValue(new Error("backend down"));
    render(<TaskArtifactRibbon />);

    // Чип виден сразу (артефакт существует), имя просто не уточняется.
    expect(screen.getByText("создана")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchCardSummaries).toHaveBeenCalledTimes(1);
    });
    // После отказа чип всё ещё «создана», а не пустой и не ошибка.
    expect(screen.getByText("создана")).toBeInTheDocument();
  });

  it("forecast_run: чип факта наличия «построен» без похода за деталями (v2 уточнит состав)", () => {
    mockStages = stagesOf({ forecasting: "done" });
    render(<TaskArtifactRibbon />);

    expect(screen.getByText("построен")).toBeInTheDocument();
    expect(fetchCardSummaries).not.toHaveBeenCalled();
  });
});

describe("TaskArtifactRibbon: DNA Metric-карточек (переиспользование)", () => {
  it("каждый чип — переиспользованная Metric-карточка (bg-brand-light, rounded-lg)", () => {
    mockStages = stagesOf({ validation: "done" });
    mockActiveDataset = DATASET;
    const { container } = render(<TaskArtifactRibbon />);

    const metric = container.querySelector("[role='listitem'] > div");
    expect(metric?.className).toContain("bg-brand-light");
    expect(metric?.className).toContain("rounded-lg");
  });
});
