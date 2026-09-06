import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import {
  useExpandableChartActions,
  useExpandableChartState,
} from "../hooks/useExpandableChart";

// Пульт управления состоянием провайдера — дёргает actions-контекст.
function Controls() {
  const { expand, collapse, toggle } = useExpandableChartActions();
  return (
    <div>
      <button data-testid="expand-a" onClick={() => expand("a")}>expand-a</button>
      <button data-testid="expand-b" onClick={() => expand("b")}>expand-b</button>
      <button data-testid="toggle-a" onClick={() => toggle("a")}>toggle-a</button>
      <button data-testid="collapse" onClick={() => collapse()}>collapse</button>
    </div>
  );
}

// Проба state-контекста — показывает текущее значение в DOM.
function StateLabel() {
  const { expandedChartId } = useExpandableChartState();
  return <span data-testid="state">{expandedChartId ?? "null"}</span>;
}

// Счётчики рендеров для проверки split state/actions-контекстов (правка H):
// потребители actions не должны перерендериваться при смене expandedChartId.
function ActionsRenderProbe({ counter }: { counter: { n: number } }) {
  useExpandableChartActions();
  counter.n += 1;
  return null;
}

function StateRenderProbe({ counter }: { counter: { n: number } }) {
  useExpandableChartState();
  counter.n += 1;
  return null;
}

function renderProviderTree(counters?: { actions: { n: number }; state: { n: number } }) {
  return render(
    <ExpandableChartsProvider>
      <Controls />
      <StateLabel />
      {counters ? <ActionsRenderProbe counter={counters.actions} /> : null}
      {counters ? <StateRenderProbe counter={counters.state} /> : null}
    </ExpandableChartsProvider>
  );
}

function stateText(): string {
  return screen.getByTestId("state").textContent ?? "";
}

describe("ExpandableChartsProvider (Task 97, Этап 1)", () => {
  it("expand(id) устанавливает expandedChartId", () => {
    renderProviderTree();
    expect(stateText()).toBe("null");
    fireEvent.click(screen.getByTestId("expand-a"));
    expect(stateText()).toBe("a");
  });

  it("повторный toggle того же id схлопывает график (инвариант single-expand)", () => {
    renderProviderTree();
    fireEvent.click(screen.getByTestId("expand-a"));
    expect(stateText()).toBe("a");
    fireEvent.click(screen.getByTestId("toggle-a"));
    expect(stateText()).toBe("null");
  });

  it("expand(id2) при уже раскрытом id1 раскрывает только id2 (implicit collapse)", () => {
    renderProviderTree();
    fireEvent.click(screen.getByTestId("expand-a"));
    expect(stateText()).toBe("a");
    fireEvent.click(screen.getByTestId("expand-b"));
    expect(stateText()).toBe("b");
  });

  it("collapse() сбрасывает раскрытое состояние", () => {
    renderProviderTree();
    fireEvent.click(screen.getByTestId("expand-a"));
    expect(stateText()).toBe("a");
    fireEvent.click(screen.getByTestId("collapse"));
    expect(stateText()).toBe("null");
  });

  it("потребители actions-контекста не перерендериваются при смене состояния (split-контексты, правка H)", () => {
    const counters = { actions: { n: 0 }, state: { n: 0 } };
    renderProviderTree(counters);
    expect(counters.actions.n).toBe(1);
    expect(counters.state.n).toBe(1);

    fireEvent.click(screen.getByTestId("expand-a"));
    // actions стабильны по ссылке — probe не перерендерился;
    // state изменился — probe перерендерился
    expect(counters.actions.n).toBe(1);
    expect(counters.state.n).toBe(2);

    fireEvent.click(screen.getByTestId("expand-b"));
    expect(counters.actions.n).toBe(1);
    expect(counters.state.n).toBe(3);

    fireEvent.click(screen.getByTestId("collapse"));
    expect(counters.actions.n).toBe(1);
    expect(counters.state.n).toBe(4);
  });

  it("хуки вне провайдера бросают понятную ошибку (контракт монтирования)", () => {
    function Orphan() {
      useExpandableChartState();
      useExpandableChartActions();
      return null;
    }
    const silence = jest.spyOn(console, "error").mockImplementation(() => {});
    try {
      expect(() => render(<Orphan />)).toThrow(
        "ExpandableChartsProvider is missing above this component"
      );
    } finally {
      silence.mockRestore();
    }
  });
});
