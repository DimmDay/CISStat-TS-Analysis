import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { ExpandableChartPanel } from "./ExpandableChartPanel";

function Harness({ onExpandChange }: { onExpandChange?: (expanded: boolean) => void }) {
  return (
    <ExpandableChartsProvider>
      <ExpandableChartPanel chartId="chart-a" title="Тестовый график" onExpandChange={onExpandChange}>
        <div data-testid="chart">chart-content</div>
      </ExpandableChartPanel>
    </ExpandableChartsProvider>
  );
}

function panelRoot(container: HTMLElement): Element {
  const el = container.firstElementChild;
  if (!el) throw new Error("ExpandableChartPanel не отрендерил корневой элемент");
  return el;
}

describe("ExpandableChartPanel (Task 97, Этап 1)", () => {
  it("в свёрнутом состоянии — обычный flex-блок без absolute/z-20", () => {
    const { container } = render(<Harness />);
    const root = panelRoot(container);
    expect(root).toHaveClass("flex", "min-h-0", "flex-1", "flex-col");
    expect(root).not.toHaveClass("absolute");
    expect(root).not.toHaveClass("inset-0");
    expect(root).not.toHaveClass("z-20");
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  // Интеграция Этапа 2 (Task 97.2): ChartExpandToggle свёрнутой панели —
  // absolute right-2 top-2, поэтому панель обязана быть containing block'ом
  // (relative), иначе бейдж якорится к корню Обзора и складывается в кучу
  // с бейджами других блоков.
  it("в свёрнутом состоянии панель — containing block (relative) для собственного бейджа", () => {
    const { container } = render(<Harness />);
    expect(panelRoot(container)).toHaveClass("relative");
  });

  it("в раскрытом состоянии relative снят — не конфликтует с absolute inset-0", () => {
    const { container } = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    expect(panelRoot(container)).toHaveClass("absolute");
    expect(panelRoot(container)).not.toHaveClass("relative");
  });

  it("в раскрытом состоянии применяются absolute inset-0 z-20 (перекрытие Обзора)", () => {
    const { container } = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    const root = panelRoot(container);
    expect(root).toHaveClass("absolute", "inset-0", "z-20");
    expect(root).not.toHaveClass("flex-1");
    // контент графика остаётся смонтированным
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("Esc при раскрытом состоянии схлопывает график", () => {
    const { container } = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    expect(panelRoot(container)).toHaveClass("absolute");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(panelRoot(container)).not.toHaveClass("absolute");
  });

  it("Esc при свёрнутом состоянии — no-op", () => {
    const { container } = render(<Harness />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(panelRoot(container)).not.toHaveClass("absolute");
    expect(panelRoot(container)).toHaveClass("flex-1");
  });

  it("onExpandChange получает false при монтировании, true при раскрытии, false при схлопывании", () => {
    const onExpandChange = jest.fn();
    render(<Harness onExpandChange={onExpandChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onExpandChange.mock.calls.map((call) => call[0])).toEqual([false, true, false]);
  });

  it("встроенный toggle отражает состояние через aria-expanded и меняет иконку/label", () => {
    render(<Harness />);
    const collapsedButton = screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" });
    expect(collapsedButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(collapsedButton);

    const expandedButton = screen.getByRole("button", { name: "Свернуть график" });
    expect(expandedButton).toHaveAttribute("aria-expanded", "true");
  });
});
