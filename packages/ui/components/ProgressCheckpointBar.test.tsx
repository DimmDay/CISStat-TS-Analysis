// packages/ui/components/ProgressCheckpointBar.test.tsx
//
// Тесты полосы действий панели «Прогресс» (Task PROGR-5.1, spec_progress.md
// §5.1-§5.2, §6.2-§6.3): кнопка «Пауза»/«Продолжить» (§5.2 -- явная фиксация
// run.status="paused"), кнопка «Сохранить точку» (§5.1 -- именованная ссылка
// на событие трассы), бейдж статуса запуска, список чекпоинтов.
//
// Бэкенд -- контракт PROGR-5 (apps/api/routers/progress.py):
//   POST /v1/progress/runs/{run_id}/pause       -> {run_id, status, event}
//   POST /v1/progress/runs/{run_id}/resume      -> {run_id, status, event}
//   POST /v1/progress/runs/{run_id}/checkpoints -> 201 {checkpoint, event}
// Ошибки (409 статуса / 503 слоя / 404 события) -- inline-алерт, панель
// не падает (best-effort, паттерн панели PROGR-4). Никакой семантики
// закрытия панели (N-4): об успехе родитель узнаёт через onChanged().

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProgressCheckpointBar } from "./ProgressCheckpointBar";
import type { CheckpointInfo, TraceEventInfo } from "../lib/progress";

const RUN_ID = "RUN-AB12CD34";

const LAST_EVENT: TraceEventInfo = {
  event_id: "e-42",
  run_id: RUN_ID,
  ts: "2026-09-25T09:05:00+00:00",
  stage: "eda",
  node_id: null,
  event_type: "passport_captured",
  payload: {},
};

function pauseResponse(status = "paused") {
  return {
    ok: true,
    status: 200,
    json: () =>
      Promise.resolve({
        run_id: RUN_ID,
        status,
        event: { event_id: "e-100", ts: "2026-09-25T09:06:00+00:00" },
      }),
  };
}

function checkpointResponse() {
  return {
    ok: true,
    status: 201,
    json: () =>
      Promise.resolve({
        checkpoint: {
          checkpoint_id: "cp-1",
          run_id: RUN_ID,
          event_id: "e-42",
          label: "Перед агрессивным сглаживанием",
          has_snapshot: true,
          created_at: "2026-09-25T09:06:30+00:00",
        },
        event: { event_id: "e-101", ts: "2026-09-25T09:06:30+00:00" },
      }),
  };
}

function mockFetch(mapping: Record<string, (url: string) => unknown>) {
  global.fetch = jest.fn((url: string) => {
    for (const [needle, factory] of Object.entries(mapping)) {
      if (String(url).includes(needle)) return factory(String(url));
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

function renderBar(props: Partial<Parameters<typeof ProgressCheckpointBar>[0]> = {}) {
  const onChanged = jest.fn();
  render(
    <ProgressCheckpointBar
      runId={RUN_ID}
      status="active"
      lastEvent={LAST_EVENT}
      checkpoints={[]}
      onChanged={onChanged}
      {...props}
    />,
  );
  return { onChanged };
}

describe("ProgressCheckpointBar", () => {
  beforeEach(() => {
    mockFetch({ "/pause": () => pauseResponse() });
  });

  it("статус active: бейдж «В работе» и активная кнопка «Пауза»", () => {
    renderBar();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    const pause = screen.getByRole("button", { name: "Пауза" });
    expect(pause).toBeEnabled();
  });

  it("клик «Пауза» -> POST /v1/progress/runs/{run_id}/pause с cookie-credentials, onChanged уведомлён (§5.2)", async () => {
    const { onChanged } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Пауза" }));
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => c as unknown[]);
      expect(calls.some((c) => String(c[0]).endsWith(`/v1/progress/runs/${RUN_ID}/pause`))).toBe(
        true,
      );
    });
    const call = (global.fetch as jest.Mock).mock.calls.find((c) =>
      String(c[0]).includes("/pause"),
    ) as unknown[];
    expect((call[1] as RequestInit).method).toBe("POST");
    expect((call[1] as RequestInit).credentials).toBe("include");
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("статус paused: бейдж «На паузе», кнопка «Продолжить» -> POST .../resume (§5.2)", async () => {
    mockFetch({ "/resume": () => pauseResponse("active") });
    const { onChanged } = renderBar({ status: "paused" });
    expect(screen.getByText("На паузе")).toBeInTheDocument();
    const resume = screen.getByRole("button", { name: "Продолжить" });
    expect(resume).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Пауза" })).toBeNull();
    fireEvent.click(resume);
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.endsWith(`/v1/progress/runs/${RUN_ID}/resume`))).toBe(true);
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("статусы completed/abandoned: обе кнопки disabled (гарантированный 409 не кликается)", () => {
    renderBar({ status: "completed" });
    expect(screen.getByText("Завершён")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Пауза" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Сохранить точку/ })).toBeDisabled();
    renderBar({ status: "abandoned" });
    expect(screen.getByText("Брошен")).toBeInTheDocument();
  });

  it("без run_id: кнопки disabled, действиям запуска неоткуда взяться", () => {
    renderBar({ runId: null });
    expect(screen.getByRole("button", { name: "Пауза" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Сохранить точку/ })).toBeDisabled();
  });

  it("«Сохранить точку»: клик открывает inline-форму с комментарием, отправка -> POST /checkpoints {event_id, label} (§5.1)", async () => {
    mockFetch({ "/checkpoints": () => checkpointResponse() });
    const { onChanged } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Сохранить точку/ }));
    const labelInput = screen.getByLabelText(/Комментарий/);
    fireEvent.change(labelInput, { target: { value: "Перед агрессивным сглаживанием" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      const call = (global.fetch as jest.Mock).mock.calls.find((c) =>
        String(c[0]).includes("/checkpoints"),
      ) as unknown[] | undefined;
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
        event_id: "e-42",
        label: "Перед агрессивным сглаживанием",
      });
    });
    // Подтверждение и появление чекпоинта в списке
    expect(await screen.findByText(/Контрольная точка сохранена/)).toBeInTheDocument();
    expect(screen.getByText(/Перед агрессивным сглаживанием/)).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("«Сохранить точку» без label отправляет пустой комментарий (label опционален, §5.1)", async () => {
    mockFetch({ "/checkpoints": () => checkpointResponse() });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Сохранить точку/ }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      const call = (global.fetch as jest.Mock).mock.calls.find((c) =>
        String(c[0]).includes("/checkpoints"),
      ) as unknown[] | undefined;
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ event_id: "e-42", label: "" });
    });
  });

  it("без последнего события с event_id чекпоинт не сохраняется (нечего фиксировать; бэкенд вернул бы 404)", () => {
    renderBar({ lastEvent: null });
    expect(screen.getByRole("button", { name: /Сохранить точку/ })).toBeDisabled();
  });

  it("событиеForecast без event_id (слой ForecastRun.trace) не годится для якоря", () => {
    renderBar({ lastEvent: { ...LAST_EVENT, event_id: undefined } });
    expect(screen.getByRole("button", { name: /Сохранить точку/ })).toBeDisabled();
  });

  it("список сохранённых чекпоинтов: label + время (§5.1: именованные ссылки)", () => {
    const checkpoints: CheckpointInfo[] = [
      {
        checkpoint_id: "cp-9",
        run_id: RUN_ID,
        event_id: "e-7",
        label: "Исходный ряд",
        has_snapshot: false,
        created_at: "2026-09-25T09:02:00+00:00",
      },
    ];
    renderBar({ checkpoints });
    expect(screen.getByText(/Исходный ряд/)).toBeInTheDocument();
    expect(screen.getByText("09:02:00")).toBeInTheDocument();
    expect(screen.queryByText(/снимок данных/)).toBeNull();
  });

  it("отказ 409 (пауза не из active) -- inline-алерт, компонент жив", async () => {
    mockFetch({
      "/pause": () => ({
        ok: false,
        status: 409,
        json: () => Promise.resolve({ detail: "Запуск в статусе 'paused'" }),
      }),
    });
    renderBar({ status: "active" });
    fireEvent.click(screen.getByRole("button", { name: "Пауза" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Запуск в статусе 'paused'/);
    expect(screen.getByRole("button", { name: "Пауза" })).toBeEnabled();
  });

  it("отказ сети -- inline-алерт, панель не падает (best-effort)", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down")) as jest.Mock;
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Пауза" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("group")).toBeInTheDocument();
  });

  it("отказ 503 долговременного слоя -- текст 503 в алерте", async () => {
    mockFetch({
      "/pause": () => ({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: "Долговременный слой недоступен" }),
      }),
    });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Пауза" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Долговременный слой недоступен/);
  });

  it("N-4: никаких семантик закрытия панели в DOM (панель живёт во фронтенде)", () => {
    renderBar();
    const html = screen.getByRole("group").innerHTML;
    expect(html).not.toContain("close_panel");
    expect(html).not.toContain("navigate");
  });

  // ── PROGR-6: кнопка «Наставник →» (§6.2 макет: слот справа) ─────────

  it("PROGR-6: кнопка «Наставник →» рендерится, aria-expanded=false по умолчанию", () => {
    renderBar();
    const mentor = screen.getByRole("button", { name: "Наставник →" });
    expect(mentor).toBeInTheDocument();
    expect(mentor).toHaveAttribute("aria-expanded", "false");
    expect(mentor).toHaveAttribute("aria-controls", "mentor-panel");
  });

  it("PROGR-6: клик «Наставник →» вызывает onToggleMentor, панель не закрывается (N-4)", () => {
    const onToggleMentor = jest.fn();
    renderBar({ onToggleMentor });
    fireEvent.click(screen.getByRole("button", { name: "Наставник →" }));
    expect(onToggleMentor).toHaveBeenCalledTimes(1);
    // N-4: никакой семантики закрытия -- onChanged не дёргается.
    expect(screen.getByRole("group")).toBeInTheDocument();
  });

  it("PROGR-6: aria-expanded=true при открытой секции; клик тогглер вызывает колбэк", () => {
    const onToggleMentor = jest.fn();
    renderBar({ mentorOpen: true, onToggleMentor });
    const mentor = screen.getByRole("button", { name: "Наставник →" });
    expect(mentor).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(mentor);
    expect(onToggleMentor).toHaveBeenCalledTimes(1);
  });
});
