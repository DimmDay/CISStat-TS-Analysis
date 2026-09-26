// packages/ui/components/MentorPanel.test.tsx
//
// Тесты панели «Наставник» (Task PROGR-6, §6.2/§6.3/§7.1): одна
// рекомендация, пояснение фазы, сводка стадии, history-предупреждения
// (§7.2 «мечется» -- в панели, не инлайн), deep-link по
// recommended_action, best-effort недоступность, N-4 (компонент не
// закрывает панель «Прогресс» -- onClose у него нет по контракту).

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MentorPanel, recommendedStageHref } from "./MentorPanel";
import { progressApiUrl } from "../lib/apiClient";

const RUN_ID = "RUN-AB12CD34";

const NEXT_STEP = {
  run_id: RUN_ID,
  run_status: "active",
  last_active_stage: "preprocessing",
  phase_text: "Идёт этап «Предобработка».",
  summary: {
    stage: "preprocessing",
    total_nodes: 10,
    done_count: 2,
    warning_nodes: 1,
    nodes: [{ node_id: "missing", status: "warning" }],
  },
  recommendation: {
    rule_id: "regularity_before_decomposition",
    stage: "preprocessing",
    message: "В ряде остались нарушения регулярности временного шага.",
    recommended_action: "preprocessing.regularity",
  },
  history_warnings: [
    {
      rule_id: "thrashing_detected",
      severity: "info",
      message: "Опробовано несколько разных стратегий подряд.",
      suggested_action: null,
    },
  ],
};

function mockFetch(response: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 503,
    json: () => Promise.resolve(response),
  }) as jest.Mock;
}

describe("MentorPanel", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("загружает next-step по run_id: рекомендация, фаза, сводка, история", async () => {
    mockFetch(NEXT_STEP);
    render(<MentorPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(
        screen.getByText("В ряде остались нарушения регулярности временного шага."),
      ).toBeInTheDocument();
    });
    expect(global.fetch).toHaveBeenCalledWith(
      progressApiUrl(`/runs/${RUN_ID}/mentor/next-step`),
      { credentials: "include" },
    );
    expect(screen.getByText(/2\/10 пройдено/)).toBeInTheDocument();
    expect(screen.getByText("Опробовано несколько разных стратегий подряд.")).toBeInTheDocument();
  });

  it("deep-link рекомендации ведёт на вкладку стадии (§6.2), не закрывая панель", async () => {
    mockFetch(NEXT_STEP);
    render(<MentorPanel runId={RUN_ID} />);
    const link = await screen.findByRole("link", { name: /Перейти: Предобработка/ });
    expect(link).toHaveAttribute("href", "/preprocessing");
  });

  it("нет рекомендации -- «идёт по плану» (одно срабатывание или тишина)", async () => {
    mockFetch({ ...NEXT_STEP, recommendation: null, history_warnings: [] });
    render(<MentorPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByText(/Критичных подсказок нет/)).toBeInTheDocument();
    });
  });

  it("503/сеть -- честная недоступность (best-effort, панель Прогресса жива)", async () => {
    mockFetch({}, false);
    render(<MentorPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Наставник недоступен");
    });
  });

  it("«Обновить» перечитывает next-step", async () => {
    mockFetch(NEXT_STEP);
    render(<MentorPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });
  });
});

describe("recommendedStageHref", () => {
  it("«stage.node_id» -> href вкладки стадии (STAGE_DEFS)", () => {
    expect(recommendedStageHref("preprocessing.regularity")).toBe("/preprocessing");
    expect(recommendedStageHref("modeling.backtest")).toBe("/modeling");
    expect(recommendedStageHref("validation.sufficiency")).toBe("/validation");
  });

  it("неизвестная стадия/пустое значение -- null (chip без ссылки)", () => {
    expect(recommendedStageHref("not_a_stage.node")).toBeNull();
    expect(recommendedStageHref(null)).toBeNull();
    expect(recommendedStageHref("")).toBeNull();
  });
});
