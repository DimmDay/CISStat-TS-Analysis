import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { ChartExpandToggle } from "./ChartExpandToggle";

const LABEL_COLLAPSED = "Развернуть график до размера окна Обзора";
const LABEL_EXPANDED = "Свернуть график";

describe("ChartExpandToggle (Task 97, Этап 1)", () => {
  it("в свёрнутом состоянии показывает иконку разворота, aria-label и aria-expanded=false", () => {
    const { container } = render(<ChartExpandToggle expanded={false} onClick={() => {}} />);
    const button = screen.getByRole("button", { name: LABEL_COLLAPSED });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector("svg.lucide-maximize2")).toBeInTheDocument();
    expect(container.querySelector("svg.lucide-minimize2")).not.toBeInTheDocument();
  });

  it("в раскрытом состоянии показывает иконку схлопывания, aria-label и aria-expanded=true", () => {
    const { container } = render(<ChartExpandToggle expanded onClick={() => {}} />);
    const button = screen.getByRole("button", { name: LABEL_EXPANDED });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector("svg.lucide-minimize2")).toBeInTheDocument();
    expect(container.querySelector("svg.lucide-maximize2")).not.toBeInTheDocument();
  });

  it("клик вызывает onClick ровно один раз на каждый клик", () => {
    const onClick = jest.fn();
    render(<ChartExpandToggle expanded={false} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: LABEL_COLLAPSED }));
    fireEvent.click(screen.getByRole("button", { name: LABEL_COLLAPSED }));
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("стиль бейджа проекта: круглый, bg-neutral-100, focus-visible ринг", () => {
    render(<ChartExpandToggle expanded={false} onClick={() => {}} />);
    const button = screen.getByRole("button", { name: LABEL_COLLAPSED });
    expect(button).toHaveClass("rounded-full");
    expect(button).toHaveClass("bg-neutral-100");
    expect(button).toHaveClass("focus-visible:ring-2");
  });

  it("title из пропса; без пропса — человекочитаемый aria-label", () => {
    const { rerender } = render(
      <ChartExpandToggle expanded={false} onClick={() => {}} title="Периодограмма" />
    );
    expect(screen.getByRole("button", { name: LABEL_COLLAPSED }).getAttribute("title")).toBe(
      "Периодограмма"
    );

    rerender(<ChartExpandToggle expanded={false} onClick={() => {}} />);
    expect(screen.getByRole("button", { name: LABEL_COLLAPSED }).getAttribute("title")).toBe(
      LABEL_COLLAPSED
    );
  });
});
