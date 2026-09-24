import { render, screen } from "@testing-library/react";
import { existsSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { ProductHeader } from "./ProductHeader";
import tailwindConfig from "../tailwind.config";

// Task 119 — логотип слева от бренда "CISStat TS Analysis" + усиление
// начертания названия (bold) и небольшое увеличение размера шрифта.

describe("ProductHeader", () => {
  it("renders the CISStat TS Analysis logo positioned before the brand name", () => {
    render(<ProductHeader />);

    const logo = screen.getByAltText("CISStat TS Analysis");
    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

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

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    expect(brandName.tagName).toBe("STRONG");
    expect(brandName).toHaveClass("font-semibold");
    expect(brandName).not.toHaveClass("font-bold");
    expect(brandName).toHaveClass("text-[28px]");
    expect(brandName).not.toHaveClass("text-[15px]");
  });

  it("brand font size equals the logo height (text-[28px] == h-7 == 28px)", () => {
    render(<ProductHeader />);

    const logo = screen.getByAltText("CISStat TS Analysis");
    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // Логотип рендерится в квадратном боксе h-7 w-7 (28px при базовых 16px),
    // object-contain заполняет его по высоте — высота логотипа = 28px.
    const logoBox = logo.closest("div.relative");
    expect(logoBox).not.toBeNull();
    expect(logoBox).toHaveClass("h-7");

    // Высота шрифта бренда равна высоте логотипа: text-[28px] == h-7 (28px).
    expect(brandName).toHaveClass("text-[28px]");
  });

  it("brand keeps its font identity and color (proportional scaling only)", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // Увеличение пропорциональное: начертание и цвет не меняются.
    expect(brandName).toHaveClass("font-bold");
    expect(brandName).toHaveClass("text-brand");
  });

  it("brand letter-spacing is slightly reduced (tracking-tight)", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // Чуть уменьшенное межбуквенное расстояние: tracking-tight (-0.025em).
    expect(brandName).toHaveClass("tracking-tight");
  });

  it("brand line box matches the logo height (leading-none)", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // Строковый бокс 28px: шапка по вертикали остаётся обусловленной
    // логотипом/кнопками h-7, текстовый блок равен высоте логотипа.
    expect(brandName).toHaveClass("leading-none");
  });

  it("serves the logo from the standalone Next.js public directory", () => {
    const logoPath = resolve(
      process.cwd(),
      "apps/standalone/public/logo_TS.png"
    );

    expect(existsSync(logoPath)).toBe(true);
    expect(statSync(logoPath).size).toBeGreaterThan(0);
  });

  it("includes standalone components in the Tailwind production scan", () => {
    expect(tailwindConfig.content).toContain("./components/**/*.{ts,tsx}");
  });

  it("header root has NO bottom border line (border-b removed)", () => {
    // Точечная правка по постановке тимлида: горизонтальная линия под
    // шапкой (border-b border-neutral-200 на корневом div) убрана.
    // Фон белый сохраняется, содержимое шапки не затрагивается.
    const { container } = render(<ProductHeader />);
    const root = container.firstElementChild;
    expect(root).not.toBeNull();
    expect(root!.className).not.toContain("border-b");
    expect(root!.className).not.toContain("border-neutral-200");
    // Фон шапки не изменился.
    expect(root!.className).toContain("bg-white");
  });
});
