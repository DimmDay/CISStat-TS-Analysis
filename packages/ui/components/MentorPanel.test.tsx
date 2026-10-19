// packages/ui/components/MentorPanel.test.tsx
//
// Тесты панели «Наставник» (Task PROGR-6, §6.2/§6.3/§7.1): одна
// рекомендация, пояснение фазы, сводка стадии, history-предупреждения
// (§7.2 «мечется» -- в панели, не инлайн), deep-link по
// recommended_action, best-effort недоступность, N-4 (компонент не
// закрывает панель «Прогресс» -- onClose у него нет по контракту).
//
// MNS-LINK-3 (2026-10-19, VERSIONED-пин deep-link): известный узел
// warning-способной стадии ведёт НА ОСТАНОВКУ степпера (якорь
// #stop=<node_id>, текст -- метка остановки); процессные стадии и
// неизвестный узел -- фолбэк на вкладку стадии (прежний контракт
// recommendedStageHref); неизвестная стадия -- chip без ссылки.
// Контракт: spec_mentor_next_step.md §5.3, решение Q6; план
// docs/mentor_next_step_review_2026-10-19.md §6 (MNS-LINK-3).

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  MentorPanel,
  recommendedStageHref,
  resolveRecommendationLink,
} from "./MentorPanel";
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

  // MNS-LINK-3 (VERSIONED-пин, был «на вкладку стадии»): известный узел
  // warning-способной стадии -- якорь остановки + метка остановки.
  it("deep-link известного узла ведёт на остановку степпера (MNS-LINK-3, якорь)", async () => {
    mockFetch(NEXT_STEP);
    render(<MentorPanel runId={RUN_ID} />);
    const link = await screen.findByRole("link", { name: /Перейти: Регулярность ряда/ });
    expect(link).toHaveAttribute("href", "/preprocessing#stop=regularity");
  });

  it("deep-link клика диспатчит GOTO_STOP_EVENT (same-route переход)", async () => {
    const spy = jest.fn();
    window.addEventListener("cisstat:goto-stop", spy);
    try {
      mockFetch(NEXT_STEP);
      render(<MentorPanel runId={RUN_ID} />);
      const link = await screen.findByRole("link", { name: /Перейти: Регулярность ряда/ });
      fireEvent.click(link);
      expect(spy).toHaveBeenCalledTimes(1);
      const event = spy.mock.calls[0][0] as CustomEvent;
      expect(event.detail).toEqual({ stage: "preprocessing", node_id: "regularity" });
    } finally {
      window.removeEventListener("cisstat:goto-stop", spy);
    }
  });

  it("процессная стадия (forecasting) -- фолбэк на вкладку стадии (MNS-LINK-3, Q4)", async () => {
    mockFetch({
      ...NEXT_STEP,
      recommendation: {
        rule_id: "forecast_not_compared_before_export",
        stage: "forecasting",
        message: "Прогноз построен, но не сравнивался.",
        recommended_action: "forecasting.compare",
      },
    });
    render(<MentorPanel runId={RUN_ID} />);
    const link = await screen.findByRole("link", { name: /Перейти: Прогнозирование/ });
    expect(link).toHaveAttribute("href", "/forecasting");
  });

  it("известная стадия с неизвестным узлом -- фолбэк на вкладку стадии (Q6)", async () => {
    mockFetch({
      ...NEXT_STEP,
      recommendation: {
        rule_id: "fallback_warning",
        stage: "upload",
        message: "Жёлтая остановка.",
        recommended_action: "upload.unknown_stop",
      },
    });
    render(<MentorPanel runId={RUN_ID} />);
    const link = await screen.findByRole("link", { name: /Перейти: Загрузка/ });
    expect(link).toHaveAttribute("href", "/upload");
  });

  it("неизвестная стадия -- прежний chip без ссылки (контракт не менялся)", async () => {
    mockFetch({
      ...NEXT_STEP,
      recommendation: {
        rule_id: "x",
        stage: "not_a_stage",
        message: "Сообщение.",
        recommended_action: "not_a_stage.node",
      },
    });
    render(<MentorPanel runId={RUN_ID} />);
    await screen.findByText("Рекомендация: not_a_stage.node");
    expect(screen.queryByRole("link", { name: /Перейти:/ })).toBeNull();
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

describe("resolveRecommendationLink (MNS-LINK-3)", () => {
  it("известный узел warning-способной стадии -- stop-link (якорь + метка остановки)", () => {
    expect(resolveRecommendationLink("preprocessing.regularity")).toEqual({
      kind: "stop",
      href: "/preprocessing#stop=regularity",
      targetLabel: "Регулярность ряда",
      stage: "preprocessing",
      nodeId: "regularity",
    });
    expect(resolveRecommendationLink("upload.overview")).toEqual({
      kind: "stop",
      href: "/upload#stop=overview",
      targetLabel: "Превью датасета",
      stage: "upload",
      nodeId: "overview",
    });
  });

  it("процессная стадия -- фолбэк на вкладку (kind: stage, nodeId: null)", () => {
    expect(resolveRecommendationLink("modeling.backtest")).toEqual({
      kind: "stage",
      href: "/modeling",
      targetLabel: "Моделирование",
      stage: "modeling",
      nodeId: null,
    });
  });

  it("известная стадия + неизвестный узел -- фолбэк на вкладку (Q6)", () => {
    const link = resolveRecommendationLink("validation.unknown_check");
    expect(link?.kind).toBe("stage");
    expect(link?.href).toBe("/validation");
    expect(link?.nodeId).toBeNull();
  });

  it("неизвестная стадия/пустое значение -- null (chip без ссылки)", () => {
    expect(resolveRecommendationLink("not_a_stage.node")).toBeNull();
    expect(resolveRecommendationLink(null)).toBeNull();
    expect(resolveRecommendationLink("")).toBeNull();
  });
});
