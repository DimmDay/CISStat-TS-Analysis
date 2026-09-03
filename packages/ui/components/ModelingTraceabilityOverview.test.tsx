import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ModelingTraceabilityOverview } from "./ModelingTraceabilityOverview";
import type { ModelingContext } from "../lib/modeling";


const groups = ["validation", "preprocessing", "eda"] as const;
const nodes = groups.flatMap((group) =>
  Array.from({ length: 10 }, (_, index) => ({
    group,
    source_id: `${group}_${index}`,
    label: `${group} ${index + 1}`,
    source_endpoint: `/source/${group}/${index}`,
    modeling_inputs: [`input_${index}`],
    modeling_stages: ["constraint_mapping"],
    status: index === 0 ? "warning" as const : "done" as const,
    evidence: `evidence ${index}`,
    blocking: index === 0,
  }))
);

const context = {
  ready: true,
  data_source: "session",
  fingerprint: "abc",
  checkpoint: { checkpoint_id: "cp-1", snapshot_id: "snap-1", stage: "modeling_entry", source_stage: "exit", confirmed_at: "2026-09-03" },
  profile: { n_observations: 100, frequency: "M" },
  passport: {},
  validation_strategy: { horizon: 12, n_splits: 5 },
  model_matrix: {},
  runnable_shortlist: ["naive"],
  traceability: { nodes, summary: { total: 30, done: 27, warning: 3, skipped: 0, pending: 0, blocking: 3 } },
} as unknown as ModelingContext;


test("renders all three upstream modules and exactly ten nodes per selected module", () => {
  render(<ModelingTraceabilityOverview context={context} />);

  expect(screen.getByText("30 источников")).toBeInTheDocument();
  expect(screen.getAllByTestId("trace-node")).toHaveLength(10);
  fireEvent.click(screen.getByRole("button", { name: "Предобработка" }));
  expect(screen.getAllByTestId("trace-node")).toHaveLength(10);
  expect(screen.getByText("preprocessing 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "EDA" }));
  expect(screen.getAllByTestId("trace-node")).toHaveLength(10);
  expect(screen.getByText("eda 10")).toBeInTheDocument();
});


test("shows evidence and exact downstream modeling inputs", () => {
  render(<ModelingTraceabilityOverview context={context} />);

  expect(screen.getByText("evidence 0")).toBeInTheDocument();
  expect(screen.getByText("input_0")).toBeInTheDocument();
  expect(screen.getByText("Блокирует переход")).toBeInTheDocument();
});
