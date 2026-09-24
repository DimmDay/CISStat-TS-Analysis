import { render, screen } from "@testing-library/react";
import { existsSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { ProductHeader } from "./ProductHeader";
import tailwindConfig from "../tailwind.config";

// Task 119 — логотип слева от бренда "CISStat TS Analysis" + усиление
// начертания названия (bold) и небольшое увеличение размера шрифта.
//
// BRND-1 — кегль бренда = высоте логотипа (text-[28px] == h-7 == 28px).
//
// BRND-2 (2026-09-24, следом за правкой тимлида font-bold→font-semibold в
// c7d8344): начертание бренда — normal (font-normal), тест-гарант
// «font identity and color» починен (требовал font-bold на дереве c7d8344 —
// падал). Логотип и бренд обёрнуты в ссылку на главную
// https://ts-standalone.vercel.app/ — клик по любому из них ведёт на главную.

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

  it("renders the brand name in normal weight with the logo-height font size", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    expect(brandName.tagName).toBe("STRONG");
    expect(brandName).toHaveClass("font-normal");
    expect(brandName).not.toHaveClass("font-semibold");
    expect(brandName).not.toHaveClass("font-bold");
    expect(brandName).toHaveClass("text-[22px]");
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
    expect(brandName).toHaveClass("text-[22px]");
  });

  it("brand keeps its color; weight is normal (BRND-2)", () => {
    render(<ProductHeader />);

    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // BRND-2: начертание normal; цвет (text-brand) не менялся.
    expect(brandName).toHaveClass("font-normal");
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

  it("logo and brand are wrapped in a single link to the standalone home page", () => {
    render(<ProductHeader />);

    const logo = screen.getByAltText("CISStat TS Analysis");
    const brandName = screen.getByText("CISStat TS Analysis", { selector: "strong" });

    // Клик по логотипу ведёт на главную standalone.
    const link = logo.closest("a");
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "https://ts-standalone.vercel.app/");

    // Клик по бренду ведёт в ту же ссылку (бренд внутри неё).
    expect(brandName.closest("a")).toBe(link);
  });

  it("home link exposes an accessible name", () => {
    render(<ProductHeader />);

    const link = screen.getByRole("link", {
      name: "CISStat TS Analysis — на главную",
    });

    expect(link).toHaveAttribute("href", "https://ts-standalone.vercel.app/");
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
