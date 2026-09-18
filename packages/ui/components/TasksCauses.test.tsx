// packages/ui/components/TasksCauses.test.tsx
//
// Тесты вертикального среза задачи «Причины» (v2, XAI) — паттерн C
// (spec_tasks_ia_addendum_v1_1.md §10.1, §11.2): колонка методов →
// колонка факторов → деталь фактора, браузинг уже вычисленного.
//
// Строительные блоки §11.2: бейджи «Когда использовать»/«Что нужно
// для запуска» (по образцу NavigatorHero), «Панель управления» в
// правой колонке, контракт высоты рабочего окна 468px,ExpandableChartPanel
// для нетривиального графика. StatusIcon/степпер отсутствуют сознательно:
// у «Причин» нет реальной стадийности (§11.2).
//
// Честная маркировка (§9.1): методы без session-артефакта —
// not_computed с видимой причиной, без фиктивных данных; без Model Card
// — честное пустое состояние с CTA на этап-владелец (прецедент R5-CTA
// хаба), поход в сеть не выполняется.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { TasksCauses } from "./TasksCauses";
import { STAGE_DEFS, StageStatus } from "../lib/stages";
import type { TasksCausesResponse } from "../lib/tasks";

let mockStages: Record<string, StageStatus> = {};
let mockSessionLoading = false;
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    stages: mockStages,
    sessionLoading: mockSessionLoading,
    activeDataset: null,
    log: [],
  }),
}));

const fetchCauses = jest.fn();
jest.mock("../lib/tasks", () => ({
  fetchCauses: (...args: unknown[]) => fetchCauses(...args),
  // Ссылки на типы не требуют рантайма; модуль мокается целиком.
}));

const stagesOf = (over: Record<string, StageStatus>) =>
  Object.fromEntries(STAGE_DEFS.map((s) => [s.key, over[s.key] ?? "pending"]));

const RESP_AVAILABLE: TasksCausesResponse = {
  card: {
    card_id: "c1",
    model_id: "random_forest",
    model_name: "Random Forest",
    selection_kind: "single",
    created_at: "2026-09-18T10:00:00+00:00",
  },
  methods: [
    {
      method_id: "fold_importance",
      kind: "feature_importance",
      title: "Вклад факторов во время бэктеста",
      status: "available",
      reason: null,
      factors: [
        {
          feature_name: "driver",
          mean_share: 0.62,
          n_folds: 2,
          fold_values: [
            { fold: 1, importance: 31.2, share: 0.6, matrix_hash: "abc123def4567890" },
            { fold: 2, importance: 32.1, share: 0.64, matrix_hash: "def456abc1237890" },
          ],
        },
        {
          feature_name: "driver_lag_1",
          mean_share: 0.38,
          n_folds: 2,
          fold_values: [
            { fold: 1, importance: 20.8, share: 0.4, matrix_hash: "abc123def4567890" },
            { fold: 2, importance: 18.0, share: 0.36, matrix_hash: "def456abc1237890" },
          ],
        },
      ],
      provenance: { backtest_run_id: "run-1", plan_id: "plan-1", n_folds: 2 },
    },
    {
      method_id: "granger",
      kind: "granger",
      title: "Причинность по Грейнджеру",
      status: "not_computed",
      reason:
        "Тест Грейнджера вычисляется в EDA по запросу аналитика и не сохраняется в сессии — данных для показа нет.",
      factors: null,
      provenance: null,
    },
    {
      method_id: "shap",
      kind: "shap",
      title: "Атрибуция предсказаний (SHAP)",
      status: "not_computed",
      reason: "SHAP-атрибуция не вычисляется движком платформы в текущей версии.",
      factors: null,
      provenance: null,
    },
    {
      method_id: "pdp",
      kind: "pdp",
      title: "Зависимость прогноза от фактора (PDP)",
      status: "not_computed",
      reason: "Кривые PDP не вычисляются движком платформы в текущей версии.",
      factors: null,
      provenance: null,
    },
  ],
};

afterEach(() => {
  mockStages = {};
  mockSessionLoading = false;
  fetchCauses.mockReset();
});

const renderAvailable = () => {
  mockStages = stagesOf({ validation: "done", modeling: "done" });
  fetchCauses.mockResolvedValue(RESP_AVAILABLE);
  const utils = render(<TasksCauses />);
  return utils;
};

describe("TasksCauses (v2, паттерн C)", () => {
  it("рендерит заголовок и методологические бейджи «Когда использовать» / «Что нужно для запуска»", async () => {
    renderAvailable();
    expect(screen.getByRole("heading", { level: 1, name: "Причины" })).toBeInTheDocument();
    expect(screen.getByTestId("badge-when-to-use")).toHaveTextContent("Когда использовать");
    expect(screen.getByTestId("badge-what-is-needed")).toHaveTextContent("Что нужно для запуска");
  });

  it("без Моделирования показывает честное пустое состояние с CTA на /modeling и НЕ ходит в сеть", () => {
    mockStages = stagesOf({});
    render(<TasksCauses />);

    expect(fetchCauses).not.toHaveBeenCalled();
    const empty = screen.getByTestId("causes-empty");
    expect(empty).toHaveTextContent("Model Card");
    const cta = within(empty).getByRole("link", { name: /Перейти к Моделированию/i });
    expect(cta).toHaveAttribute("href", "/modeling");
    expect(screen.queryByTestId("causes-methods")).not.toBeInTheDocument();
  });

  it("пока сессия гидратируется — нейтральное состояние загрузки без похода в сеть", () => {
    mockSessionLoading = true;
    render(<TasksCauses />);

    expect(fetchCauses).not.toHaveBeenCalled();
    expect(screen.getByTestId("causes-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("causes-empty")).not.toBeInTheDocument();
  });

  it("паттерн C: три колонки — методы (4 записи), факторы, «Панель управления»; недоступные методы честно неактивны с причиной", async () => {
    const { container } = renderAvailable();
    await screen.findByTestId("causes-methods");

    const methods = screen.getByTestId("causes-methods");
    const buttons = within(methods).getAllByRole("button");
    expect(buttons).toHaveLength(4);
    expect(
      within(methods).getByRole("button", { name: /Вклад факторов во время бэктеста/i }),
    ).toBeEnabled();
    expect(
      within(methods).getByRole("button", { name: /Причинность по Грейнджеру/i }),
    ).toBeDisabled();
    // Причина статуса видна пользователю (честная маркировка §9.1).
    expect(
      within(methods).getByText(/вычисляется в EDA по запросу аналитика/i),
    ).toBeInTheDocument();

    expect(screen.getByTestId("causes-factors")).toBeInTheDocument();
    expect(screen.getByText("Панель управления")).toBeInTheDocument();
    // Контракт высоты рабочего окна 468px + ExpandableChartPanel (§11.2).
    const window468 = container.querySelector(".h-\\[468px\\]");
    expect(window468).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }),
    ).toBeInTheDocument();
  });

  it("факторы выбранного метода: список с долями, первый выбран по умолчанию, клик переключает деталь", async () => {
    const { container } = renderAvailable();
    await screen.findByTestId("causes-factors");

    const factors = screen.getByTestId("causes-factors");
    expect(within(factors).getByText("driver")).toBeInTheDocument();
    expect(within(factors).getByText("driver_lag_1")).toBeInTheDocument();
    // Первый фактор (наибольшая доля) выбран по умолчанию.
    expect(
      within(factors).getByRole("button", { name: "driver 62.0%" }),
    ).toHaveAttribute("aria-pressed", "true");
    // Деталь: имя фактора + per-fold таблица.
    expect(screen.getByTestId("causes-factor-detail")).toHaveTextContent("driver");
    expect(screen.getAllByText("fold 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("fold 2").length).toBeGreaterThan(0);

    fireEvent.click(
      within(factors).getByRole("button", { name: "driver_lag_1 38.0%" }),
    );
    expect(
      within(factors).getByRole("button", { name: "driver_lag_1 38.0%" }),
    ).toHaveAttribute("aria-pressed", "true");
    // Recharts-обёртка присутствует (прецедент NavigatorChartPreview.test:
    // в jsdom со stub-ResizeObserver внутренний SVG не строится, поэтому
    // ассертим .recharts-responsive-container, а не .recharts-bar).
    expect(
      container.querySelector(".recharts-responsive-container"),
    ).toBeTruthy();
  });

  it("провенанс метода виден в колонке факторов (run/план бэктеста — Task 127)", async () => {
    renderAvailable();
    await screen.findByTestId("causes-factors");

    const factors = screen.getByTestId("causes-factors");
    expect(within(factors).getByText(/run-1/)).toBeInTheDocument();
    expect(within(factors).getByText(/plan-1/)).toBeInTheDocument();
  });

  it("недоступные методы не выбираются: клик не меняет колонку факторов, причина видна в списке методов", async () => {
    renderAvailable();
    await screen.findByTestId("causes-methods");

    const methods = screen.getByTestId("causes-methods");
    const granger = within(methods).getByRole("button", {
      name: /Причинность по Грейнджеру/i,
    });
    // Честная маркировка §9.1: неактивная кнопка + причина ВИДНА прямо
    // в списке методов (не фиктивное «пусто» и не dead-end выбор).
    expect(granger).toBeDisabled();
    expect(granger).toHaveAttribute("aria-disabled", "true");
    expect(within(methods).getByText(/не сохраняется в сессии/i)).toBeInTheDocument();

    fireEvent.click(granger);

    // Выбор не изменился: колонка факторов остаётся на доступном методе.
    const factors = screen.getByTestId("causes-factors");
    expect(within(factors).getByText("driver")).toBeInTheDocument();
    expect(screen.getByTestId("causes-factor-detail")).toBeInTheDocument();
  });

  it("409 от бэкенда (карта исчезла между запросами) — честное состояние с причиной, не крэш", async () => {
    mockStages = stagesOf({ validation: "done", modeling: "done" });
    fetchCauses.mockRejectedValue(new Error("Model Card не найдена"));
    render(<TasksCauses />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Model Card не найдена");
    expect(screen.queryByTestId("causes-methods")).not.toBeInTheDocument();
  });
});
