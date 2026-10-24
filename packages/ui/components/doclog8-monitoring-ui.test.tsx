// packages/ui/components/doclog8-monitoring-ui.test.tsx
//
// DOCLOG-8 (спека §6 D12, §12.2 «Левый список», §12.3 состояния,
// AC15/AC17): D12 «Сверка прогноза с фактом» в DocumentationWorkspace --
// вид в левом списке с серверным заголовком; панель мониторинга в
// предпросмотре D12: таблица actual-vs-forecast (Дата/Прогноз/Факт/
// Ошибка/|Ошибка|/APE/Интервал), агрегаты (MAE/bias/покрытие),
// порог-факт, ЧЕСТНАЯ строка незрелых горизонтов (не нулевая ошибка),
// состояния loading/empty/forbidden/error.
//
// Оракулы на СВОИХ данных: клиенты lib/documentation и lib/monitoring
// мокаются; корпус дизъюнктен серверным репо-сюитам (tests/api).

import { render, screen, waitFor } from "@testing-library/react";
import {
  DocumentationWorkspace,
  KIND_CODES,
  KIND_TITLES,
} from "./DocumentationWorkspace";
import { MonitoringComparisonPanel } from "./MonitoringComparisonPanel";
import * as documentation from "../lib/documentation";
import * as monitoring from "../lib/monitoring";

jest.mock("../lib/documentation", () => {
  const actual = jest.requireActual("../lib/documentation");
  return {
    ...actual,
    listDocuments: jest.fn(),
    getRevision: jest.fn(),
    getLifecycle: jest.fn(),
    requestApproval: jest.fn(),
    decideApproval: jest.fn(),
    publishRevision: jest.fn(),
    retractRevision: jest.fn(),
    getRevisionDiff: jest.fn(),
    requestRendition: jest.fn(),
    createDraft: jest.fn(),
    cancelJob: jest.fn(),
    getJob: jest.fn(),
  };
});

jest.mock("../lib/monitoring", () => {
  const actual = jest.requireActual("../lib/monitoring");
  return {
    ...actual,
    listRunComparisons: jest.fn(),
    getComparison: jest.fn(),
  };
});

const mockedDocumentation = documentation as jest.Mocked<typeof documentation>;
const mockedMonitoring = monitoring as jest.Mocked<typeof monitoring>;

const RUN_ID = "RUN-D8B00001";
const COMPARISON_ID = "mon-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

function d12Document(): documentation.DocumentSummary {
  return {
    document_id: "doc-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
    run_id: RUN_ID,
    kind_code: "D12",
    title: "Сверка прогноза с фактом",
    current_revision_id: "drev-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    created_by: null,
    created_at: "2026-10-24T10:00:00Z",
    revisions: [
      {
        revision_id: "drev-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        document_id: "doc-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
        snapshot_id: "rs-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        run_id: RUN_ID,
        version_no: 1,
        created_by: null,
        created_at: "2026-10-24T10:00:00Z",
        lifecycle_state: "draft",
        renditions: [],
      },
    ],
  };
}

const COMPARISON_PAGE: monitoring.ComparisonListResult = {
  ok: true as const,
  status: 200,
  data: {
    items: [
      {
        comparison_id: COMPARISON_ID,
        run_id: RUN_ID,
        forecast_artifact_id: "art-d8forecast0000000000000000000000",
        forecast_sha256: "sha256-d8",
        actual_batch_id: "act-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_name: "gdp_growth",
        entity_id: null,
        units_check: "as_is",
        units_note: "",
        status: "ready",
        matured_count: 2,
        excluded_count: 3,
        out_of_horizon_count: 0,
        created_at: "2026-10-24T10:00:00Z",
      },
    ],
    total: 1,
  },
};

const COMPARISON_DETAIL: monitoring.ComparisonDetailResult = {
  ok: true as const,
  status: 200,
  data: {
    comparison_id: COMPARISON_ID,
    run_id: RUN_ID,
    forecast_artifact_id: "art-d8forecast0000000000000000000000",
    forecast_sha256: "sha256-d8",
    actual_batch_id: "act-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    target_name: "gdp_growth",
    entity_id: null,
    units_check: "as_is",
    units_note: "",
    status: "ready",
    matured_count: 2,
    excluded_count: 3,
    out_of_horizon_count: 0,
    created_at: "2026-10-24T10:00:00Z",
    result: {
      schema_version: "doclog.monitoring_result/1",
      forecast_origin: { horizon: 5, alpha: 0.05, point_count: 5 },
      alignment: {
        key: "period_label_exact",
        matured_count: 2,
        excluded_count: 3,
        excluded_labels: ["2026-11-01", "2026-12-01", "2027-01-01"],
        out_of_horizon_count: 0,
        out_of_horizon_labels: [],
      },
      pairs: [
        {
          step: 1,
          date: "2026-09-01",
          forecast_value: 5.0,
          actual_value: 4.8,
          signed_error: -0.2,
          absolute_error: 0.2,
          ape: 0.041666666666666664,
          ape_undefined_reason: null,
          interval_hit: true,
        },
        {
          step: 2,
          date: "2026-10-01",
          forecast_value: 6.0,
          actual_value: 6.1,
          signed_error: 0.1,
          absolute_error: 0.1,
          ape: 0.016393442622950821,
          ape_undefined_reason: null,
          interval_hit: true,
        },
      ],
      aggregates: {
        mae: 0.15,
        mae_reason: null,
        mean_signed_error: -0.05,
        mean_signed_error_reason: null,
        mape: 0.029030054644808743,
        mape_reason: null,
        mape_zero_periods: [],
        mase: null,
        mase_reason: "mase_scale_required",
        interval_hits: 2,
        interval_coverage: 1.0,
        interval_coverage_reason: null,
      },
      threshold: {
        metric: "mae",
        operator: ">",
        value: 0.5,
        label: "",
        status: "within",
        reason: null,
      },
      decision_action: null,
    },
  },
};

describe("DOCLOG-8: каталог видов DocumentationWorkspace", () => {
  test("D12 в левом списке с серверным заголовком", () => {
    expect(KIND_CODES).toContain("D12");
    expect(KIND_TITLES["D12"]).toBe("Сверка прогноза с фактом");
  });
});

describe("DOCLOG-8: D12 в рабочей области документов", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedDocumentation.listDocuments.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        documents: [d12Document()],
        total: 1,
      },
    } as never);
    mockedDocumentation.getRevision.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        revision: {
          revision_id: "drev-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          document_id: "doc-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
          snapshot_id: "rs-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          run_id: RUN_ID,
          version_no: 1,
          created_by: null,
          created_at: "2026-10-24T10:00:00Z",
          lifecycle_state: "draft",
          renditions: [],
        },
        snapshot: {
          snapshot_id: "rs-d8aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          run_id: RUN_ID,
          context_id: "ctx-d8-1",
          data_revision: 3,
          captured_at: "2026-10-24T10:00:00Z",
          completeness: { status: "partial", missing_refs: [] },
          sections: [
            {
              code: "D12",
              claims: [
                {
                  text: "Сверки прогноза с фактом не зарегистрированы",
                  event_refs: [],
                  result_refs: [],
                  validity: "unknown",
                  evidence_level: null,
                },
              ],
            },
          ],
        },
      },
    } as never);
    mockedDocumentation.getLifecycle.mockResolvedValue({
      ok: false,
      status: 404,
    } as never);
    mockedMonitoring.listRunComparisons.mockResolvedValue(COMPARISON_PAGE);
    mockedMonitoring.getComparison.mockResolvedValue(COMPARISON_DETAIL);
  });

  test("вид D12 присутствует в списке видов с заголовком", async () => {
    render(<DocumentationWorkspace runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByText("Сверка прогноза с фактом")).toBeTruthy();
    });
  });
});

describe("DOCLOG-8: панель мониторинга (таблица actual-vs-forecast)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("таблица пар, агрегаты, порог и честные незрелые горизонты", async () => {
    mockedMonitoring.listRunComparisons.mockResolvedValue(COMPARISON_PAGE);
    mockedMonitoring.getComparison.mockResolvedValue(COMPARISON_DETAIL);
    render(<MonitoringComparisonPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByTestId("d12-comparison-table")).toBeTruthy();
    });
    // Пары: дата/прогноз/факт/ошибка -- числа из frozen result.
    expect(screen.getByText("2026-09-01")).toBeTruthy();
    expect(screen.getByText("2026-10-01")).toBeTruthy();
    // Агрегаты: MAE/bias/покрытие/порог.
    expect(screen.getByTestId("d12-aggregates").textContent).toContain("MAE");
    expect(screen.getByTestId("d12-aggregates").textContent).toContain("0.15");
    expect(screen.getByTestId("d12-aggregates").textContent).toContain("в норме");
    // MASE без scale -- честный null + reason (AC12), не 0.
    expect(screen.getByTestId("d12-aggregates").textContent).toContain(
      "MASE: —"
    );
    // Незрелые горизонты -- ЯВНО (не нулевая ошибка, AC15).
    expect(screen.getByTestId("d12-excluded").textContent).toContain("3");
    expect(screen.getByTestId("d12-excluded").textContent).toContain(
      "2026-11-01"
    );
  });

  test("пустое состояние -- честный текст без таблицы", async () => {
    mockedMonitoring.listRunComparisons.mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [], total: 0 },
    } satisfies monitoring.ComparisonListResult);
    render(<MonitoringComparisonPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByTestId("d12-empty")).toBeTruthy();
    });
    expect(screen.queryByTestId("d12-comparison-table")).toBeNull();
  });

  test("403 -- различимое честное состояние запрета", async () => {
    mockedMonitoring.listRunComparisons.mockResolvedValue({
      ok: false,
      status: 403,
    } satisfies monitoring.ComparisonListResult);
    render(<MonitoringComparisonPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByTestId("d12-forbidden")).toBeTruthy();
    });
  });

  test("иная ошибка сервиса -- честное состояние недоступности", async () => {
    mockedMonitoring.listRunComparisons.mockResolvedValue({
      ok: false,
      status: 503,
    } satisfies monitoring.ComparisonListResult);
    render(<MonitoringComparisonPanel runId={RUN_ID} />);
    await waitFor(() => {
      expect(screen.getByTestId("d12-error")).toBeTruthy();
    });
  });

  test("без runId панель не рендерит таблицу", () => {
    render(<MonitoringComparisonPanel runId={null} />);
    expect(
      screen.getByTestId("d12-no-run", { exact: false })
    ).toBeTruthy();
    expect(mockedMonitoring.listRunComparisons).not.toHaveBeenCalled();
  });
});
