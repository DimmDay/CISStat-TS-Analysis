import { render, screen } from "@testing-library/react";
import { ProductHeader } from "./ProductHeader";

// Task 119 — логотип слева от бренда "CISStat TS Analysis" + усиление
// начертания названия (bold) и небольшое увеличение размера шрифта.

describe("ProductHeader", () => {
  it("renders the CISStat TS Analysis logo positioned before the brand name", () => {
    render(<ProductHeader />);

    const logo = screen.getByAltText("CISStat TS Analysis");
    const brandName = screen.getByText("CISStat TS Analysis", { selector: "span" });

    expect(logo).toBeInTheDocument();
    expect(brandName).toBeInTheDocument();

    // Логотип должен предшествовать текстовому названию в DOM-порядке
    // (что при flex-row визуально означает "слева от логотипа").
    // eslint-disable-next-line no-bitwise
    expect(
      logo.compareDocumentPosition(brandName) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("renders the brand name bold and with a slightly increased font size", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "span" });

    expect(brandName).toHaveClass("font-bold");
    expect(brandName).not.toHaveClass("font-semibold");
    expect(brandName).toHaveClass("text-[15px]");
  });
});
