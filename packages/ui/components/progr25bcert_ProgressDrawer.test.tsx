// packages/ui/components/progr25bcert_ProgressDrawer.test.tsx
//
// СЕРТИФИКАЦИОННЫЕ ОРАКУЛЫ задачи PROGR-25-B (PROGR-25-B-CERT, независимый
// аудит шапки панели «Прогресс»). Сюит НЕ копирует repo-тесты задачи
// (ProgressDrawer.test.tsx): свои данные, свой мок контекста, свои
// сценарии. Ключевой приём независимости: контекст гидратирован ЗНАЧЕНИЕМ
// "temp", трасса несёт "load" -- шапка обязана показать ТРАССОВОЕ
// значение (источник /trace, спека §4-B), и только на ответе старого
// бэкенда без полей (N-3) честно деградирует к контексту.
//
// Свои данные сертификации: energy_hourly.csv (336 строк), RUN-CERTB*,
// колонки ts/load/price/temp.
//
// Контракты (спека §4-B, план §2):
//   CERT-D1/D2/D3  -- «load (авто)» / «load» (user) / «load» (legacy);
//   CERT-D4        -- «не выбран» + ссылка «выбрать» (закрывает панель);
//   CERT-D5        -- «—» ТОЛЬКО при отсутствии датасета;
//   CERT-D6        -- источник шапки -- /trace, не контекст;
//   CERT-D7        -- смена признака на другой вкладке + переоткрытие --
//                     новое значение без перезагрузки страницы;
//   CERT-D8/D9     -- N-3 деградация: undefined -> контекст; legacy-мир;
//   CERT-D10       -- инвариант: при датасете «—» недостижим;
//   CERT-D11       -- null трассы строже контекста -> «не выбран».

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProgressDrawer } from "./ProgressDrawer";

// Мутабельное состояние своего контекст-мока аудитора (имя с префиксом
// mock -- требование hoisting jest.mock). Значения СВОИ: стейл-контекст
// намеренно указывает на "temp", чтобы отличать источник шапки.
const mockCertShell: {
  activeDataset: { name: string; rows: number; sizeLabel: string } | null;
  targetColumn: string | null;
} = {
  activeDataset: { name: "energy_hourly.csv", rows: 336, sizeLabel: "34 КБ" },
  targetColumn: "temp",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => mockCertShell,
}));

const RUN_A = "RUN-CERTB001";
const RUN_B = "RUN-CERTB002";

function certTrace(overrides: Record<string, unknown>, runId: string = RUN_A) {
  return {
    run_id: runId,
    started_at: "2026-10-08T08:00:00+00:00",
    events: [
      {
        event_id: "cev-1",
        run_id: runId,
        ts: "2026-10-08T08:00:00+00:00",
        stage: "upload",
        node_id: "structure_confirmed",
        event_type: "upload_completed",
        payload: { name: "energy_hourly.csv", rows: 336, columns: 4 },
        actor: "user",
        timestamp: "2026-10-08T08:00:00+00:00",
      },
    ],
    node_statuses: { "upload/structure_confirmed": "done" } as Record<string, string>,
    stages: [
      { stage: "upload", fold: "passed", done_count: 1, warning_nodes: 0, total_nodes: 1 },
      { stage: "validation", fold: "not_started", done_count: 0, warning_nodes: 0, total_nodes: 10 },
    ],
    ...overrides,
  };
}

let certServerTrace: Record<string, unknown>;

function certTraceFetch(): void {
  global.fetch = jest.fn((url: string) => {
    if (String(url).includes("/v1/progress/trace")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(certServerTrace) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

const readBadge = (): string => screen.getByTestId("progress-target-column").textContent ?? "";

beforeEach(() => {
  certTraceFetch();
  mockCertShell.activeDataset = { name: "energy_hourly.csv", rows: 336, sizeLabel: "34 КБ" };
  mockCertShell.targetColumn = "temp";
});

describe("PROGR-25-B-CERT: шапка панели «Прогресс» (свои оракулы аудита)", () => {
  it("CERT-D1: source=auto -> «load (авто)» -- пометка происхождения честная", async () => {
    certServerTrace = certTrace({ target_column: "load", target_column_source: "auto" });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("load (авто)"));
  });

  it("CERT-D2: source=user -> «load» БЕЗ пометки (ручной выбор не выдаётся за авто)", async () => {
    certServerTrace = certTrace({ target_column: "load", target_column_source: "user" });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("load"));
    expect(readBadge()).not.toContain("(авто)");
  });

  it("CERT-D3: поле source отсутствует (legacy-ответ) -> «load» без пометки", async () => {
    certServerTrace = certTrace({ target_column: "load" });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("load"));
    expect(readBadge()).not.toContain("(авто)");
  });

  it("CERT-D4: датасет есть, признака нет -> «не выбран» + ссылка «выбрать», клик закрывает панель", async () => {
    certServerTrace = certTrace({ target_column: null, target_column_source: null });
    const onClose = jest.fn();
    render(<ProgressDrawer open onClose={onClose} />);
    await waitFor(() => expect(readBadge()).toBe("не выбран"));
    const link = screen.getByRole("link", { name: "выбрать" });
    expect(link).toHaveAttribute("href", "/upload");
    fireEvent.click(link);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("CERT-D5: датасета нет -> «—» (прочерк только в этом классе), даже при значении в трассе", async () => {
    certServerTrace = certTrace({ target_column: "load", target_column_source: "auto" });
    mockCertShell.activeDataset = null;
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("—"));
  });

  it("CERT-D6: источник шапки -- /trace: контекст говорит temp, трасса load -> показан load (авто)", async () => {
    certServerTrace = certTrace({ target_column: "load", target_column_source: "auto" });
    // mockCertShell.targetColumn = "temp" (стейл) -- задан в beforeEach.
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("load (авто)"));
    expect(readBadge()).not.toContain("temp");
  });

  it("CERT-D7: смена признака на другой вкладке + переоткрытие -> новое значение без перезагрузки", async () => {
    certServerTrace = certTrace({ target_column: "load", target_column_source: "auto" }, RUN_A);
    const view = render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("load (авто)"));

    // Панель закрыли; на другой вкладке признак сменили; /trace обновился.
    view.rerender(<ProgressDrawer open={false} onClose={jest.fn()} />);
    certServerTrace = certTrace({ target_column: "price", target_column_source: "user" }, RUN_B);
    view.rerender(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("price"));
    expect(readBadge()).not.toContain("(авто)");
  });

  it("CERT-D8: N-3: ответ старого бэкенда без полей -> честная деградация к контексту (temp без пометки)", async () => {
    certServerTrace = certTrace({}); // ни target_column, ни source
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("temp"));
    expect(readBadge()).not.toContain("(авто)");
  });

  it("CERT-D9: N-3: legacy-ответ + контекст пуст + датасет есть -> «—» (прежнее поведение сохранено)", async () => {
    certServerTrace = certTrace({});
    mockCertShell.targetColumn = null;
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("—"));
  });

  it("CERT-D10: инвариант: при датасете прочерк «—» недостижим ни в одном состоянии трассы", async () => {
    const states: Array<Record<string, unknown>> = [
      { target_column: "load", target_column_source: "auto" },
      { target_column: "load", target_column_source: "user" },
      { target_column: "load" },
      { target_column: null, target_column_source: null },
      {},
    ];
    for (const overrides of states) {
      certServerTrace = certTrace(overrides);
      const view = render(<ProgressDrawer open onClose={jest.fn()} />);
      await waitFor(() => expect(screen.getByTestId("progress-target-column")).toBeInTheDocument());
      await waitFor(() => expect(readBadge()).not.toBe("—"));
      view.unmount();
    }
  });

  it("CERT-D11: null трассы строже контекста: контекст temp, трасса null -> «не выбран»", async () => {
    certServerTrace = certTrace({ target_column: null, target_column_source: null });
    // mockCertShell.targetColumn = "temp".
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(readBadge()).toBe("не выбран"));
    expect(readBadge()).not.toContain("temp");
  });
});
