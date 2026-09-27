// packages/ui/components/AdminProgressDashboard.test.tsx
//
// Тесты Admin-панели мониторинга «Прогресса» (Task PROGR-8,
// spec_progress.md §10 + §9, §6.3: «AdminProgressDashboard.tsx
// (только Role.ADMIN)»).
//
// Ключевые контракты:
//  * §10 дословно: админ заходит ДРУГИМ ПУТЁМ -- API-ключ с ролью
//    ADMIN (заголовок X-API-Key), НЕ cookie-сессия аналитика;
//    ключ вводится в панели, живёт только в стейте компонента.
//  * Состав §10: запуски по статусам за период, время по стадиям,
//    топ warning/error-узлов, частоты правил §7.1, частоты
//    sanity-предупреждений §7.2 по правилу/узлу, предпочтения
//    Прогнозирования (§9); отбор кандидатов банка кейсов (§9).
//  * Пустой корпус -- честные нули («не гейтится кодом»), не ошибка.
//  * 401/403 -- различимые сообщения (неверный ключ / не админ).

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AdminProgressDashboard } from "./AdminProgressDashboard";
import { progressApiUrl } from "../lib/apiClient";

const OVERVIEW = {
  generated_at: "2026-09-27T12:00:00+00:00",
  period_days: 30,
  runs_total_all_time: 3,
  runs_total_in_period: 2,
  runs_by_status: { active: 1, paused: 0, completed: 1, abandoned: 0 },
  stage_time: [
    {
      stage: "preprocessing",
      runs_with_stage: 2,
      mean_minutes: 40.5,
      median_minutes: 40.5,
    },
  ],
  top_problem_nodes: [
    { stage: "preprocessing", node_id: "missing", status: "warning", count: 2 },
  ],
  next_step_frequency: [
    {
      rule_id: "preprocessing_missing_attention",
      stage: "preprocessing",
      count: 4,
    },
  ],
  sanity_by_rule: [{ rule_id: "no_effect", stage: "preprocessing", count: 3 }],
  sanity_by_node: [
    { stage: "preprocessing", node_id: "missing", count: 2 },
  ],
  forecasting_model_frequency: [{ value: "ets", count: 2 }],
  forecasting_horizon_frequency: [{ value: "7", count: 3 }],
  forecasting_alpha_frequency: [{ value: "0.1", count: 2 }],
};

const CASE_BANK = {
  candidates: [
    {
      run_id: "RUN-AB12CD34",
      status: "completed",
      dataset_name: "prices.csv",
      created_at: "2026-09-20T10:00:00+00:00",
      backtest_mape: 12.5,
      warning_nodes: 0,
      sanity_warnings: 0,
    },
  ],
  total_completed: 1,
  criteria: {
    max_backtest_mape: 30,
    max_warning_nodes: 2,
    max_sanity_warnings: 2,
  },
};

function mockFetchByUrl(handlers: Record<string, { status: number; body: unknown }>) {
  global.fetch = jest.fn((url: string) => {
    const matched = Object.keys(handlers).find((key) => url.includes(key));
    const handler = matched ? handlers[matched] : { status: 404, body: {} };
    return Promise.resolve({
      ok: handler.status === 200,
      status: handler.status,
      json: () => Promise.resolve(handler.body),
    });
  }) as jest.Mock;
}

function submitKey(key = "admin-key-000") {
  fireEvent.change(screen.getByLabelText("API-ключ администратора"), {
    target: { value: key },
  });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить" }));
}

describe("AdminProgressDashboard", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("запрос не уходит до ввода ключа (ключ -- в стейте компонента)", () => {
    mockFetchByUrl({});
    render(<AdminProgressDashboard />);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.getByText(/Admin-панель мониторинга/i)).toBeInTheDocument();
  });

  it("загружает обзор и банк кейсов с X-API-Key, НЕ cookie (§10: другой путь)", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 200, body: OVERVIEW },
      "/admin/case-bank/candidates": { status: 200, body: CASE_BANK },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        progressApiUrl("/admin/overview?days=30&top=10"),
        expect.objectContaining({
          headers: { "X-API-Key": "admin-key-000" },
        }),
      );
    });
    expect(global.fetch).toHaveBeenCalledWith(
      progressApiUrl("/admin/case-bank/candidates"),
      expect.objectContaining({ headers: { "X-API-Key": "admin-key-000" } }),
    );
  });

  it("рендерит агрегаты §10: статусы, время по стадиям, топ узлов, частоты правил", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 200, body: OVERVIEW },
      "/admin/case-bank/candidates": { status: 200, body: CASE_BANK },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    // Запуски по статусам за период + all-time (метка runStatusLabel).
    await waitFor(() => {
      expect(screen.getByText("Завершён")).toBeInTheDocument();
    });
    expect(screen.getByText(/2.*из.*3/)).toBeInTheDocument();
    // Время по стадиям: «где застревают» -- средние минуты.
    expect(screen.getByText(/~40\.5 мин/)).toBeInTheDocument();
    // Топ проблемных узлов.
    expect(screen.getByText(/missing/)).toBeInTheDocument();
    // Частоты §7.1 и §7.2.
    expect(screen.getByText(/preprocessing_missing_attention/)).toBeInTheDocument();
    expect(screen.getByText(/no_effect/)).toBeInTheDocument();
    // Предпочтения Прогнозирования (§9).
    expect(screen.getByText("ets")).toBeInTheDocument();
    expect(screen.getByText(/alpha 0\.1/)).toBeInTheDocument();
  });

  it("рендерит кандидатов банка кейсов (§9) с доказательствами", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 200, body: OVERVIEW },
      "/admin/case-bank/candidates": { status: 200, body: CASE_BANK },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(screen.getByText(/RUN-AB12CD34/)).toBeInTheDocument();
    });
    expect(screen.getByText(/12\.5/)).toBeInTheDocument();
    expect(screen.getByText(/prices\.csv/)).toBeInTheDocument();
  });

  it("пустой корпус -- честные нули с пояснением, не ошибка (не гейтится кодом)", async () => {
    mockFetchByUrl({
      "/admin/overview": {
        status: 200,
        body: {
          ...OVERVIEW,
          runs_total_all_time: 0,
          runs_total_in_period: 0,
          runs_by_status: { active: 0, paused: 0, completed: 0, abandoned: 0 },
          stage_time: [],
          top_problem_nodes: [],
          next_step_frequency: [],
          sanity_by_rule: [],
          sanity_by_node: [],
          forecasting_model_frequency: [],
          forecasting_horizon_frequency: [],
          forecasting_alpha_frequency: [],
        },
      },
      "/admin/case-bank/candidates": {
        status: 200,
        body: { candidates: [], total_completed: 0, criteria: CASE_BANK.criteria },
      },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(screen.getByText(/Корпус пуст/i)).toBeInTheDocument();
    });
  });

  it("401 -- различимое сообщение о неверном ключе", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 401, body: { detail: "Неверный API-ключ" } },
      "/admin/case-bank/candidates": { status: 401, body: {} },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Неверный API-ключ/i);
    });
  });

  it("403 -- различимое сообщение о роли (не ADMIN)", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 403, body: { detail: "Требуется роль ADMIN" } },
      "/admin/case-bank/candidates": { status: 403, body: {} },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Требуется роль ADMIN/i);
    });
  });

  it("«Обновить» перечитывает обзор и кандидатов", async () => {
    mockFetchByUrl({
      "/admin/overview": { status: 200, body: OVERVIEW },
      "/admin/case-bank/candidates": { status: 200, body: CASE_BANK },
    });
    render(<AdminProgressDashboard />);
    submitKey();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(4); // 2 загрузки × 2 запроса
    });
  });
});
