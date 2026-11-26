import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AppShellProvider } from "../context/AppShellContext";
import { TsAnalysisUpload } from "./TsAnalysisUpload";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() } }));
// Scientific SVGs are stubs; Upload, Button, ChartScope and HTTP client are real.
jest.mock("./TimeSeriesLineChart", () => ({ TimeSeriesLineChart: () => <svg id="series-own-svg" /> }));
jest.mock("./DistributionCharts", () => ({
  ScatterDistributionChart: () => <svg id="scatter-own-svg" />,
  HistogramDistributionChart: () => <svg id="histogram-own-svg" />,
  KdeDistributionChart: () => <svg id="kde-own-svg" />,
  SamplingBadge: () => null,
}));

const uploaded = {
  dataset_id: "png-date-1", name: "png-date.csv", rows: 4, columns: 2, size_label: "1 KB", parse_warnings: [],
  preview: {head: [["month", "revenue"], ["2026-01-01", "11"]], tail: [["2026-04-01", "14"]]},
  columns_info: [
    {name: "month", dtype: "object", type_icon: "datetime", non_null: 4, nulls: 0, unique: 4},
    {name: "revenue", dtype: "float64", type_icon: "numeric", non_null: 4, nulls: 0, unique: 4},
  ],
  quality: {cols_with_missing: 0, cols_with_outliers: 0, rows_total: 4, duplicates: 0, missing_cols: [], outlier_cols: []},
};
const views = ["upload.chart.series", "upload.distribution.scatter", "upload.distribution.histogram", "upload.distribution.kde"];
function json(status: number, body: unknown) {
  return {ok: status >= 200 && status < 300, status, json: async () => body};
}
async function start(restored: boolean, date: string | null = "month") {
  const exports: Record<string, unknown>[] = [];
  const datePosts: string[] = [];
  global.fetch = jest.fn(async (input, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/session/current")) return json(200, {has_active_dataset: restored, dataset: restored ? uploaded : null, stages: {}});
    if (url.includes("/target-column")) return json(200, {target_column: "revenue", suggested_column: "revenue", available_columns: ["revenue"], has_dataset: true});
    if (url.includes("/dataset/structure-detection")) return json(200, {
      date_col: {selected: date ?? "(не использовать)", confidence: date ? 95 : 0, candidates: date ? [{name: date, score: .95}] : []},
      entity_col: {selected: "(нет)", confidence: 95, candidates: []},
    });
    if (url.includes("/dataset/timeseries")) return json(200, {column: "revenue", date_column: date, points: [], sampled: false, original_count: 4});
    if (url.includes("/dataset/distribution")) return json(200, {column: "revenue", non_null_count: 4, scatter: [], histogram: [], kde: []});
    if (url.includes("/dataset/stats")) return json(200, {columns: [], min_non_null_for_stats: 2});
    if (url.includes("/date-column") && init?.method === "POST") datePosts.push(url);
    if (url.includes("/runs/") && url.endsWith("/visuals")) {
      const body = JSON.parse(String(init?.body)); exports.push(body);
      return body.date_column === date
        ? json(202, {job: {job_id: "djob-date-" + exports.length, state: "queued"}})
        : json(409, {code: "source_unavailable", message: "missing date_column"});
    }
    if (url.includes("/trace")) return json(200, {run_id: "RUN-DATE", context_id: "ctx-date", nodes: []});
    if (url.endsWith("/session/dataset") || url.includes("/upload")) return json(200, uploaded);
    return json(200, {});
  }) as jest.Mock;
  render(<AppShellProvider><TsAnalysisUpload /></AppShellProvider>);
  if (!restored) {
    fireEvent.drop(screen.getByTestId("dropzone-input"), {dataTransfer: {
      files: [new File(["month,revenue\n2026-01-01,11"], "png-date.csv", {type: "text/csv"})], types: ["Files"],
    }});
  }
  await screen.findByText("Превью датасета");
  return {exports, datePosts};
}

test.each([false, true])("Upload raw PNG requests carry displayed date before Structure confirmation, restored=%s", async (restored) => {
  const calls = await start(restored);
  fireEvent.click(screen.getByRole("button", {name: /^График/}));
  await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([url]) => String(url).includes("/dataset/timeseries"))).toBe(true));
  for (const view of views) {
    if (view.endsWith("scatter")) fireEvent.click(screen.getByRole("button", {name: /^Распределение/}));
    fireEvent.click(await screen.findByTestId(`visual-export-${view}`));
    await waitFor(() => expect(screen.getByTestId(`visual-export-${view}`)).toHaveAttribute("data-export-state", "queued"));
  }
  expect(calls.exports.map(x => x.view_id)).toEqual(views);
  expect(calls.exports.every(x => x.date_column === "month" && x.expected_context_id === "ctx-date")).toBe(true);
  expect(calls.exports.every(x => String(x.screen_svg).includes("own-svg"))).toBe(true);
  expect(calls.datePosts).toEqual([]);
});

test("Upload without a date offers a precise reason and sends no export", async () => {
  const calls = await start(false, null);
  fireEvent.click(screen.getByRole("button", {name: /^Распределение/}));
  const button = await screen.findByTestId("visual-export-upload.distribution.histogram");
  await waitFor(() => expect(button).toBeDisabled());
  expect(screen.getByTestId("visual-export-disabled-reason-upload.distribution.histogram")).toHaveTextContent("временную колонку");
  fireEvent.click(button);
  expect(calls.exports).toEqual([]);
  expect(calls.datePosts).toEqual([]);
});
