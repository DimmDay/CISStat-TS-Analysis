// packages/ui/components/TasksHubSessionSync.test.tsx
//
// Task PREPR-4 (аудит PREPR-3-класса на других вкладках). Оракул-тест
// хаба «Задачи»: бэкенд честно гейтит карточки состоянием сессии
// (task-stops.deriveTaskGateState по stages), но AppShellContext живёт
// в layout.tsx и НЕ ремоунтится при клиентской навигации; stages
// гидрируются только при монтировании провайдера (F5) и после upload.
// Сценарий: аналитик прошёл этапы пайплайна в других вкладках, открыл
// /tasks — хаб обязан ПЕРЕСИНХРОНИЗИРОВАТЬ stages с бэкендом при
// монтировании (refreshSession), иначе карточки показывают устаревший
// гейтинг до перезагрузки страницы.
//
// Инфраструктура: РЕАЛЬНЫЙ AppShellProvider (без jest.mock контекста):
// мок /v1/session/current с флагом «бэкенд уже видел done». Провайдер
// гидратируется на «свежей» сессии; затем TasksHub монтируется в то же
// дерево (rerender сохраняет состояние провайдера — клиентская
// навигация без ремоунта layout) — монтирование хаба должно дать
// ВТОРОЙ вызов /session/current уже с done и перегейтить карточки.

import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { AppShellProvider } from "../context/AppShellContext";
import { TasksHub } from "./TasksHub";

function sessionResponse(pipelineDone: boolean) {
  return {
    has_active_dataset: true,
    dataset: {
      dataset_id: "d1",
      name: "sales.csv",
      rows: 120,
      columns: 3,
      size_label: "1 KB",
    },
    stages: pipelineDone
      ? {
          upload: "done",
          validation: "done",
          preprocessing: "done",
          eda: "done",
          modeling: "done",
          forecasting: "done",
        }
      : {},
    last_active_stage: pipelineDone ? "forecasting" : null,
    updated_at: "2026-09-18T00:00:00Z",
  };
}

let backendPipelineDone: boolean;
let currentCalls: number;

beforeEach(() => {
  backendPipelineDone = false;
  currentCalls = 0;
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      currentCalls += 1;
      const done = backendPipelineDone;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(sessionResponse(done)),
      });
    }
    // Точечный поход ленты артефактов за картами (fail-soft: [] — чип
    // остаётся с фактом «создана»).
    if (typeof url === "string" && url.includes("/modeling/card")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
});

describe("TasksHub — пересинхронизация stages с бэкендом при монтировании (PREPR-4)", () => {
  it("re-syncs session stages on mount and re-gates task cards without a page reload", async () => {
    // 1) Провайдер гидратируется со «свежей» сессией (артефактов нет) —
    //    это состояние контекста, оставшееся от предыдущей навигации.
    const view = render(<AppShellProvider>{null}</AppShellProvider>);
    await waitFor(() => expect(currentCalls).toBe(1));

    // 2) Аналитик проходит пайплайн в ДРУГИХ вкладках; бэкенд уже знает
    //    о done. Контекст (layout) об этом пока не знает.
    backendPipelineDone = true;

    // 3) Пользователь открывает вкладку «Задачи» (клиентская навигация:
    //    провайдер НЕ ремоунтится, монтируется только children).
    view.rerender(
      <AppShellProvider>
        <TasksHub />
      </AppShellProvider>
    );

    // 4) Хаб обязан пересинхронизировать stages при монтировании:
    //    второй вызов /session/current вернёт done — карточки
    //    перегейтываются без перезагрузки страницы.
    //    «Сценарии» требуют model_card (этап Моделирования) — после
    //    синхронизации карточка становится ссылкой на задачу.
    expect(await screen.findByRole("link", { name: /Сценарии/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: /Задача «Сценарии» недоступна/ })
    ).not.toBeInTheDocument();

    // Синхронизация ровно одним дополнительным вызовом (нет цикла).
    expect(currentCalls).toBe(2);
  });
});
