import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ValidationCheckChart } from "./ValidationCheckChart";

describe("ValidationCheckChart: непрокручиваемое окно 468px", () => {
  it("растягивает bar chart на всю доступную высоту окна с подписью", () => {
    render(
      <ValidationCheckChart
        checkLabel="Пропуски"
        selectedColumn="Price"
        loading={false}
        data={{
          status: "warning",
          count: 3,
          scope: "column",
          items: [{ label: "Price", count: 3 }],
        }}
      />,
    );

    expect(screen.getByTestId("validation-check-workspace")).toHaveClass(
      "h-[468px]",
      "flex",
      "min-h-0",
      "flex-col",
    );
    expect(screen.getByTestId("validation-check-visualization")).toHaveClass(
      "min-h-0",
      "flex-1",
    );
    expect(screen.getByTestId("validation-check-visualization")).not.toHaveClass("h-[468px]");
  });

  it("удерживает caption и служебное состояние внутри тех же 468px", () => {
    render(
      <ValidationCheckChart
        checkLabel="Пропуски"
        selectedColumn="Price"
        loading={false}
        data={{ status: "done", count: 0, scope: "column", items: [] }}
      />,
    );

    expect(screen.getByTestId("validation-check-state")).toHaveClass(
      "h-[468px]",
      "flex",
      "min-h-0",
      "flex-col",
    );
    expect(screen.getByTestId("validation-check-info")).toHaveClass("min-h-0", "flex-1");
    expect(screen.getByTestId("validation-check-info")).not.toHaveClass("h-[468px]");
  });
});
