// packages/ui/components/prograudit8cert_checkpoint_metadata.test.tsx
//
// PROGR-AUDIT-8-CERT: СВОИ оракулы UI на СВОИХ данных (принцип
// «оракулы на своих данных» независимой сертификации).
//
// Объект: ProgressCheckpointBar (контракт аддендум v1.2-8A §22.4):
// DTO/UI показывают, ЕСТЬ ЛИ снимок, К КАКОМУ контексту он относится,
// на какой позиции durable-истории создан и с какой ревизией, плюс
// honest-пометку, что raw restore снимки НЕ применяет.
//
// Дизъюнкт от оракула исполнителя
// (prograudit8_checkpoint_metadata.test.tsx, сценарии S1–S4:
// RUN-AUDIT888, cp-audit8-1, ctx-abc123, watermark 17, ревизия 1):
//   * свои данные: RUN-C8CERT-77, cp-cert8-a/b/c, контексты
//     ctx-8cert-a1b2c3d4 / ctx-8cert-9e8f7a6b, watermark 0/214/215,
//     ревизии 0/2;
//   * свои наблюдательные углы:
//       U1  полный снимок с метаданными -- контекст/позиция/ревизия +
//           honest-пометка;
//       U2  легаси-чекпоинт (поля undefined -- старый бэкенд N-3):
//           прежний рендер, поля НЕ фабрикуются;
//       U3  без снимков honest-пометка отсутствует («не применять
//           нечего»);
//       U4  несколько чекпоинтов -- каждый несёт СВОЙ контекст/позицию;
//       U5  снимок с watermark=0 и ревизией 0 -- «позиция 0»/«ревизия 0»
//           рендерятся (0 -- валидная позиция начала истории raw);
//       U6  metadata без снимка (has_snapshot=false -- путь сбоя
//           сохранения снимка при заполненных metadata): контекст/
//           позиция НЕ рендерятся (гейт has_snapshot), компонент жив.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ProgressCheckpointBar } from "./ProgressCheckpointBar";
import type { CheckpointInfo, TraceEventInfo } from "../lib/progress";

const RUN_ID = "RUN-C8CERT-77";

const LAST_EVENT: TraceEventInfo = {
  event_id: "e-cert8-99",
  run_id: RUN_ID,
  ts: "2026-10-13T11:30:00+00:00",
  stage: "validation",
  node_id: null,
  event_type: "mode_changed",
  payload: {},
};

function renderBar(
  props: Partial<Parameters<typeof ProgressCheckpointBar>[0]> = {},
): ReturnType<typeof render> {
  return render(
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
    checkpoint_id: "cp-cert8-a",
    run_id: RUN_ID,
    event_id: "e-cert8-7",
    label: "Перед сменой вселенной",
    has_snapshot: true,
    created_at: "2026-10-13T11:15:00+00:00",
    ...overrides,
  };
}

describe("PROGR-AUDIT-8-CERT: metadata чекпоинта в UI (свои данные)", () => {
  it("U1: снимок с метаданными -- контекст, позиция, ревизия и honest-пометка", () => {
    renderBar({
      checkpoints: [
        checkpoint({
          context_id: "ctx-8cert-a1b2c3d4",
          data_revision: 2,
          watermark: 214,
        }),
      ],
    });
    expect(screen.getByText(/снимок данных/)).toBeInTheDocument();
    expect(screen.getByTestId("checkpoint-context")).toHaveTextContent(
      "ctx-8cert-a1b2c3d4",
    );
    expect(screen.getByTestId("checkpoint-watermark")).toHaveTextContent("214");
    expect(screen.getByTestId("checkpoint-data-revision")).toHaveTextContent("2");
    expect(screen.getByTestId("checkpoint-restore-note")).toHaveTextContent(
      /не применяет/i,
    );
  });

  it("U2: легаси-чекпоинт (поля undefined, N-3) -- прежний рендер без фабрикации", () => {
    const { container } = renderBar({
      checkpoints: [checkpoint({ context_id: undefined, data_revision: undefined, watermark: undefined })],
    });
    // Базовые факты живы.
    expect(screen.getByText(/снимок данных/)).toBeInTheDocument();
    expect(screen.getByText(/Перед сменой вселенной/)).toBeInTheDocument();
    // Поля НЕ выдумываются.
    expect(screen.queryByTestId("checkpoint-context")).not.toBeInTheDocument();
    expect(screen.queryByTestId("checkpoint-watermark")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("checkpoint-data-revision"),
    ).not.toBeInTheDocument();
    // Честная пометка при наличии снимка остаётся.
    expect(screen.getByTestId("checkpoint-restore-note")).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("U3: без снимков honest-пометка отсутствует («не применять нечего»)", () => {
    renderBar({
      checkpoints: [checkpoint({ has_snapshot: false, context_id: undefined, watermark: undefined, data_revision: undefined })],
    });
    expect(screen.queryByText(/снимок данных/)).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("checkpoint-restore-note"),
    ).not.toBeInTheDocument();
  });

  it("U4: несколько чекпоинтов -- каждый несёт СВОЙ контекст/позицию", () => {
    renderBar({
      checkpoints: [
        checkpoint({
          checkpoint_id: "cp-cert8-a",
          context_id: "ctx-8cert-a1b2c3d4",
          data_revision: 0,
          watermark: 12,
        }),
        checkpoint({
          checkpoint_id: "cp-cert8-b",
          event_id: "e-cert8-8",
          label: "После коррекции",
          context_id: "ctx-8cert-9e8f7a6b",
          data_revision: 2,
          watermark: 215,
        }),
      ],
    });
    const contexts = screen.getAllByTestId("checkpoint-context");
    expect(contexts).toHaveLength(2);
    expect(contexts[0]).toHaveTextContent("ctx-8cert-a1b2c3d4");
    expect(contexts[1]).toHaveTextContent("ctx-8cert-9e8f7a6b");
    const positions = screen.getAllByTestId("checkpoint-watermark");
    expect(positions[0]).toHaveTextContent("12");
    expect(positions[1]).toHaveTextContent("215");
    const revisions = screen.getAllByTestId("checkpoint-data-revision");
    expect(revisions[0]).toHaveTextContent("0");
    expect(revisions[1]).toHaveTextContent("2");
  });

  it("U5: watermark=0 и ревизия=0 -- валидные значения raw-начала рендерятся", () => {
    renderBar({
      checkpoints: [
        checkpoint({ context_id: "ctx-8cert-a1b2c3d4", data_revision: 0, watermark: 0 }),
      ],
    });
    expect(screen.getByTestId("checkpoint-watermark")).toHaveTextContent("0");
    expect(screen.getByTestId("checkpoint-data-revision")).toHaveTextContent("0");
  });

  it("U6: metadata без снимка (сбой сохранения) -- поля не рендерятся, компонент жив", () => {
    // Путь продукта: replace(context_id/data_revision) выполняется ДО
    // попытки сохранения снимка; сбой сохранения оставляет metadata при
    // has_snapshot=false. UI-гейт has_snapshot честно скрывает поля
    // (снимка нет -- контекст снимка не показывается).
    renderBar({
      checkpoints: [
        checkpoint({ has_snapshot: false, context_id: "ctx-8cert-a1b2c3d4", data_revision: 1, watermark: 33 }),
      ],
    });
    expect(screen.queryByText(/снимок данных/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("checkpoint-context")).not.toBeInTheDocument();
    expect(screen.queryByTestId("checkpoint-watermark")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("checkpoint-data-revision"),
    ).not.toBeInTheDocument();
    // Компонент жив, honest-пометка по снятому чекпоинту не рендерится
    // (снимков нет).
    expect(
      screen.queryByTestId("checkpoint-restore-note"),
    ).not.toBeInTheDocument();
  });
});
