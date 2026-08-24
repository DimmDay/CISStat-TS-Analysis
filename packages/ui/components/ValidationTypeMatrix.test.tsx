import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";

import { ValidationTypeMatrix, type ValidationTypeProfileItem } from "./ValidationTypeMatrix";

const PROFILE: ValidationTypeProfileItem[] = [
  { name: "Country", dtype: "object", type_icon: "categorical", non_null: 4, nulls: 0, unique: 3 },
  { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 4, nulls: 0, unique: 4 },
  { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 3, nulls: 1, unique: 3 },
  { name: "Comment", dtype: "object", type_icon: "text", non_null: 4, nulls: 0, unique: 4 },
];

describe("ValidationTypeMatrix", () => {
  it("renders a proportional stacked bar and legend for all semantic classes", () => {
    render(
      <ValidationTypeMatrix
        profile={PROFILE}
        mode="profile"
        loading={false}
        hasDataset
      />
    );

    expect(screen.getByRole("img", { name: /распределение типов колонок/i })).toBeInTheDocument();
    expect(screen.getByTestId("type-segment-numeric")).toHaveStyle({ width: "50%" });
    expect(screen.getByTestId("type-segment-categorical")).toHaveStyle({ width: "25%" });
    expect(screen.getByTestId("type-segment-text")).toHaveStyle({ width: "25%" });
    expect(screen.queryByTestId("type-segment-datetime")).not.toBeInTheDocument();

    expect(screen.getByTestId("type-count-numeric")).toHaveTextContent("2");
    expect(screen.getByTestId("type-count-datetime")).toHaveTextContent("0");
    expect(screen.getByTestId("type-count-categorical")).toHaveTextContent("1");
    expect(screen.getByTestId("type-count-text")).toHaveTextContent("1");
  });

  it("renders the requested type matrix with honest profile-mode values", () => {
    render(
      <ValidationTypeMatrix
        profile={PROFILE}
        mode="profile"
        loading={false}
        hasDataset
      />
    );

    const table = screen.getByRole("table", { name: "Матрица типов колонок" });
    for (const heading of ["Колонка", "dtype", "Ожидаемый тип", "Статус", "Нарушения"]) {
      expect(within(table).getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }

    const countryRow = within(table).getByRole("row", { name: /Country/ });
    expect(within(countryRow).getByText("object")).toBeInTheDocument();
    expect(within(countryRow).getByText("Категориальный")).toBeInTheDocument();
    expect(within(countryRow).getByText("Не задан")).toBeInTheDocument();
    expect(within(countryRow).getByText("Профиль")).toBeInTheDocument();
    expect(within(countryRow).getByText("—")).toBeInTheDocument();
  });

  it("explains why violations are unavailable in profile mode", () => {
    render(
      <ValidationTypeMatrix
        profile={PROFILE}
        mode="profile"
        loading={false}
        hasDataset
      />
    );

    expect(screen.getByText(/ожидаемая схема не выбрана/i)).toBeInTheDocument();
    expect(screen.getByText(/нарушения не рассчитываются/i)).toBeInTheDocument();
  });
});
