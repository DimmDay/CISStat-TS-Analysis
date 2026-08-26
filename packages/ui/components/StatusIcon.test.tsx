import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { StatusIcon, STATUS_LABEL, type CheckStatus } from "./StatusIcon";

const ALL_STATUSES: CheckStatus[] = ["done", "warning", "pending", "skipped", "running", "error"];

describe("StatusIcon", () => {
  it.each(ALL_STATUSES)("renders an accessible label for status '%s'", (status) => {
    render(<StatusIcon status={status} />);
    expect(screen.getByRole("img", { name: STATUS_LABEL[status] })).toBeInTheDocument();
  });

  it("spins only the running status", () => {
    const { container: running } = render(<StatusIcon status="running" />);
    expect(running.querySelector("svg")).toHaveClass("animate-spin");

    const { container: done } = render(<StatusIcon status="done" />);
    expect(done.querySelector("svg")).not.toHaveClass("animate-spin");
  });

  it("keeps backward-compatible labels for the original three statuses", () => {
    expect(STATUS_LABEL.done).toBe("Пройдено");
    expect(STATUS_LABEL.warning).toBe("Найдены проблемы");
    expect(STATUS_LABEL.pending).toBe("Не запускалось");
  });

  it("labels the neutral skipped status (Task 47: auto/enabled/disabled modes)", () => {
    expect(STATUS_LABEL.skipped).toBe("Не требуется");
  });
});
