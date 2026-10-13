// packages/ui/components/prograudit8_checkpoint_metadata.test.tsx
//
// PROGR-AUDIT-8 (plan_progress_audit.md §14, контракт аддендум
// v1.2-8A §22): DTO/UI чекпоинта показывают, ЕСТЬ ЛИ снимок, К КАКОМУ
// контексту он относится и на какой позиции durable-истории создан --
// плюс честную пометку, что raw restore снимок НЕ применяет (full
// snapshot replay -- отдельный контракт, сознательно не реализован).
//
// Состав карточки §14 п.5: «Показать в DTO/UI, есть ли snapshot, к
// какому контексту он относится и что raw restore его не применяет».
//
// Сценарии:
//   S1  чекпоинт со снимком и метаданными: «снимок данных» + контекст +
//       позиция + honest-пометка «restore не применяет»;
//   S2  легаси-чекпоинт без метаданных (старый бэкенд, N-3): прежний
//       рендер без контекста, компонент жив;
//   S3  чекпоинт без снимка: пометка «снимок данных» отсутствует;
//       honest-пометка рендерится только при наличии снимков;
//   S4  несколько чекпоинтов: каждый несёт СВОЙ контекст/позицию
//       (metadata создания, не якорного события).

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ProgressCheckpointBar } from "./ProgressCheckpointBar";
import type { CheckpointInfo, TraceEventInfo } from "../lib/progress";

const RUN_ID = "RUN-AUDIT888";

const LAST_EVENT: TraceEventInfo = {
  event_id: "e-42",
  run_id: RUN_ID,
  ts: "2026-10-13T09:05:00+00:00",
  stage: "validation",
  node_id: null,
  event_type: "mode_changed",
  payload: {},
};

function renderBar(props: Partial<Parameters<typeof ProgressCheckpointBar>[0]> = {}) {
  render(
    <ProgressCheckpointBar
      runId={RUN_ID}
      status="active"
      lastEvent={LAST_EVENT}
      checkpoints={[]}
      onChanged={jest.fn()}
      {...props}
    />,
  );
}

function checkpoint(overrides: Partial<CheckpointInfo> = {}): CheckpointInfo {
  return {
    checkpoint_id: "cp-audit8-1",
    run_id: RUN_ID,
    event_id: "e-7",
    label: "Перед экспериментом",
    has_snapshot: true,
    created_at: "2026-10-13T09:02:00+00:00",
    ...overrides,
  };
}

describe("PROGR-AUDIT-8: metadata чекпоинта в UI", () => {
  it("S1: снимок с метаданными -- контекст, позиция durable-истории и honest-пометка «restore не применяет»", () => {
    renderBar({
      checkpoints: [
        checkpoint({ context_id: "ctx-abc123", data_revision: 1, watermark: 17 }),
      ],
    });
    // Снимок есть.
    expect(screen.getByText(/снимок данных/)).toBeInTheDocument();
    // К какому контексту относится снимок (metadata создания).
    expect(screen.getByTestId("checkpoint-context")).toHaveTextContent("ctx-abc123");
    // Позиция durable-истории на момент создания.
    expect(screen.getByTestId("checkpoint-watermark")).toHaveTextContent("17");
    // Честная пометка: raw restore снимок НЕ применяет.
    expect(screen.getByTestId("checkpoint-restore-note")).toHaveTextContent(
      /не применяет/i,
    );
  });

  it("S2: легаси-чекпоинт без метаданных (старый бэкенд) -- прежний рендер, N-3 деградация без контекста", () => {
    renderBar({ checkpoints: [checkpoint()] });
    expect(screen.getByText(/Перед экспериментом/)).toBeInTheDocument();
    expect(screen.getByText(/снимок данных/)).toBeInTheDocument();
    // Метаданных нет -- контекст/позиция не рендерятся (не выдумываются).
    expect(screen.queryByTestId("checkpoint-context")).toBeNull();
    expect(screen.queryByTestId("checkpoint-watermark")).toBeNull();
    // honest-пометка о снимках остаётся (снимок-то есть).
    expect(screen.getByTestId("checkpoint-restore-note")).toBeInTheDocument();
  });

  it("S3: чекпоинт без снимка -- метки снимка нет; honest-пометка не рендерится без снимков", () => {
    renderBar({
      checkpoints: [
        checkpoint({ has_snapshot: false, context_id: undefined, watermark: undefined }),
      ],
    });
    expect(screen.queryByText(/снимок данных/)).toBeNull();
    expect(screen.queryByTestId("checkpoint-restore-note")).toBeNull();
  });

  it("S4: несколько чекпоинтов -- каждый несёт СВОЙ контекст и позицию создания", () => {
    renderBar({
      checkpoints: [
        checkpoint({
          checkpoint_id: "cp-1",
          label: "Ранняя точка",
          context_id: "ctx-early",
          data_revision: 0,
          watermark: 4,
        }),
        checkpoint({
          checkpoint_id: "cp-2",
          label: "Поздняя точка",
          context_id: "ctx-late",
          data_revision: 1,
          watermark: 31,
        }),
      ],
    });
    const contexts = screen.getAllByTestId("checkpoint-context");
    expect(contexts).toHaveLength(2);
    expect(contexts[0]).toHaveTextContent("ctx-early");
    expect(contexts[1]).toHaveTextContent("ctx-late");
    const marks = screen.getAllByTestId("checkpoint-watermark");
    expect(marks[0]).toHaveTextContent("4");
    expect(marks[1]).toHaveTextContent("31");
  });
});
