// packages/ui/components/TasksHub.test.tsx
//
// Тесты хаба «Задачи» (spec_tasks_ia.md §4, §8):
//   - шапка + сетка 4 карточек (TaskCard) с ролью list;
//   - три состояния по сессии: blocked (свежая), awaiting (частичный
//     прогресс), available (контракт выполнен);
//   - некликабельные состояния НЕ ссылки на задачу; available — ссылки
//     на /tasks/<id>; awaiting- и blocked-карточки содержат микро-CTA
//     «Перейти к этапу …» (R5 + симметрия follow-up): ссылку на этап-владельца
//     недостающего артефакта (awaiting) или на вход в пайплайн «Загрузка»
//     (blocked, свежая сессия);
//   - доступная «Сценарии» с отсутствующим forecast_run показывает
//     подсказку рекомендуемого (не гейтящего) артефакта (R2);
//   - причины недоступности видны пользователю.
//
// Контракт ссылок: fresh-сессия — 0 задачных ссылок + 4 CTA на /upload;
// после Моделирования — 2 задач + 2 CTA; полный пайплайн — 4 задач, CTA
// и подсказок нет.

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

  it("fresh session: all 4 cards are blocked, no task links, but each has the symmetric CTA to /upload", () => {
    mockStages = stagesOf({});
    const { container } = render(<TasksHub />);

    // Ни одной ССЫЛКИ НА ЗАДАЧУ (защита от ложного аффорданса сохранена).
    expect(container.querySelectorAll('a[href^="/tasks/"]')).toHaveLength(0);
    // Причина заблокированного состояния видна на каждой карточке.
    const reasons = screen.getAllByText(/Начните с этапа Загрузка/);
    expect(reasons).toHaveLength(4);
    // Состояние озвучено для a11y.
    const groups = screen.getAllByRole("group", { name: /недоступна/i });
    expect(groups).toHaveLength(4);
    // Симметричный микро-CTA (follow-up R5): каждая blocked-карточка ведёт
    // на вход в пайплайн — этап «Загрузка».
    const ctas = screen.getAllByRole("link", {
      name: "Перейти к этапу Загрузка",
    });
    expect(ctas).toHaveLength(4);
    ctas.forEach((cta) => expect(cta).toHaveAttribute("href", "/upload"));
    // Всего ссылок: 0 задач + 4 CTA.
    expect(container.querySelectorAll("a")).toHaveLength(4);
  });

  it("after Modeling: Сценарии and Причины are links, forecast tasks are awaiting with reason", () => {
    mockStages = stagesOf({ validation: "done", modeling: "done" });
    const { container } = render(<TasksHub />);

    // Ссылки на ЗАДАЧИ — только с доступным контрактом.
    const taskLinks = Array.from(
      container.querySelectorAll('a[href^="/tasks/"]')
    );
    expect(taskLinks.map((l) => l.getAttribute("href"))).toEqual(
      expect.arrayContaining(["/tasks/scenarios", "/tasks/causes"])
    );
    expect(taskLinks).toHaveLength(2);

    // Прогнозные задачи ещё не доступны — причина называет этап.
    const awaiting = screen.getAllByText(/Станет доступна после этапа Прогнозирование/);
    expect(awaiting).toHaveLength(2);

    // Микро-CTA (R5): каждая awaiting-карточка ведёт на этап-владелец.
    const ctas = screen.getAllByRole("link", {
      name: "Перейти к этапу Прогнозирование",
    });
    expect(ctas).toHaveLength(2);
    ctas.forEach((cta) =>
      expect(cta).toHaveAttribute("href", "/forecasting")
    );

    // Подсказка рекомендуемого артефакта (R2): только у доступных Сценариев
    // (forecast_run отсутствует; у Причин recommendedWith не объявлен).
    expect(
      screen.getByText("Рекомендуется также этап Прогнозирование")
    ).toBeInTheDocument();

    // Всего ссылок: 2 задач + 2 CTA.
    expect(container.querySelectorAll("a")).toHaveLength(4);
  });

  it("partial pipeline (validation done only): all cards still locked, but awaiting (amber), not blocked", () => {
    mockStages = stagesOf({ validation: "done" });
    const { container } = render(<TasksHub />);

    // Ни одной ссылки на задачу; карточки не кликабельны.
    expect(container.querySelectorAll('a[href^="/tasks/"]')).toHaveLength(0);
    // Модельные задачи ждут Моделирование.
    expect(screen.getAllByText(/Станет доступна после этапа Моделирование/)).toHaveLength(2);
    // Прогнозные ждут Прогнозирование (пайплайн уже начат — не blocked).
    expect(screen.getAllByText(/Станет доступна после этапа Прогнозирование/)).toHaveLength(2);
    expect(screen.queryByText(/Начните с этапа Загрузка/)).toBeNull();

    // Микро-CTA (R5): модельные — на /modeling, прогнозные — на /forecasting.
    const toModeling = screen.getAllByRole("link", {
      name: "Перейти к этапу Моделирование",
    });
    const toForecasting = screen.getAllByRole("link", {
      name: "Перейти к этапу Прогнозирование",
    });
    expect(toModeling).toHaveLength(2);
    expect(toForecasting).toHaveLength(2);
    toModeling.forEach((cta) => expect(cta).toHaveAttribute("href", "/modeling"));
    toForecasting.forEach((cta) =>
      expect(cta).toHaveAttribute("href", "/forecasting")
    );
    // Подсказок рекомендуемого артефакта нет: ни одна задача не available.
    expect(screen.queryByText(/Рекомендуется также/)).toBeNull();
  });

  it("full pipeline: all 4 cards are links to their routes, no CTAs, no hints", () => {
    mockStages = stagesOf({
      upload: "done",
      validation: "done",
      preprocessing: "done",
      eda: "done",
      modeling: "done",
      forecasting: "done",
    });
    const { container } = render(<TasksHub />);

    const hrefs = Array.from(
      container.querySelectorAll('a[href^="/tasks/"]')
    ).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      "/tasks/scenarios",
      "/tasks/causes",
      "/tasks/decisions",
      "/tasks/monitoring",
    ]);
    // Полный пайплайн: подсказок и CTA не остаётся (артефакты есть).
    expect(screen.queryByRole("link", { name: /Перейти к этапу/ })).toBeNull();
    expect(screen.queryByText(/Рекомендуется также/)).toBeNull();
    expect(container.querySelectorAll("a")).toHaveLength(4);
  });

  it("cards inherit the RouteCard visual DNA (badge-card with brand border)", () => {
    mockStages = stagesOf({ validation: "done", modeling: "done" });
    const { container } = render(<TasksHub />);

    const firstCard = container.querySelector("a");
    expect(firstCard?.className).toContain("rounded-xl");
    expect(firstCard?.className).toContain("border-brand/60");
  });
});
