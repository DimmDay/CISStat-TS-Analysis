// packages/ui/dkt4-shells.test.ts
//
// Task DKT-4 — оболочки и сторонние поверхности (spec_dark_theme.md §7
// DKT-4): явный фон body на токен страницы, sonner Toaster с theme prop
// из контекста.
//
// Решения, зафиксированные в спеке §10 (2026-09-18):
//  - §10.2 embedded — «v1 только standalone»: точки монтирования темы в
//    apps/embedded НЕ переносятся; embedded остаётся светлой, тест
//    documentирует это как контракт (layout без ThemeProvider);
//  - §10.3 дефолт — системная схема (реализован в DKT-1, здесь не
//    трогается).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { THEME_META_COLOR, ThemeProvider, useTheme } from "./index";

const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");

function hexToChannels(hex: string): string {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

describe("DKT-4: явный фон body на токен страницы", () => {
  it("в globals.css объявлены правила body для обеих тем на --c-page", () => {
    expect(GLOBALS).toMatch(/body\s*\{[^}]*background-color:\s*rgb\(var\(--c-page\)\)/s);
    expect(GLOBALS).toMatch(/\.dark body\s*\{[^}]*background-color:\s*rgb\(var\(--c-page\)\)/s);
  });

  it("токен --c-page согласован с meta theme-color (ThemeContext)", () => {
    const rootBlock = GLOBALS.match(/:root\s*\{([\s\S]*?)\n\}/)![1];
    const darkBlock = GLOBALS.match(/\.dark\s*\{([\s\S]*?)\n\}/)![1];
    const light = rootBlock.match(/--c-page:\s*([0-9 ]+);/)![1];
    const dark = darkBlock.match(/--c-page:\s*([0-9 ]+);/)![1];
    expect(light).toBe(hexToChannels(THEME_META_COLOR.light));
    expect(dark).toBe(hexToChannels(THEME_META_COLOR.dark));
  });

  it("токен --c-page присутствует симметрично в обоих блоках (паритет каталога)", () => {
    const rootVars = GLOBALS.match(/:root\s*\{([\s\S]*?)\n\}/)![1].match(/--c-[a-z0-9-]+/g) ?? [];
    const darkVars = GLOBALS.match(/\.dark\s*\{([\s\S]*?)\n\}/)![1].match(/--c-[a-z0-9-]+/g) ?? [];
    expect(darkVars.sort()).toEqual(rootVars.sort());
  });
});

// ── sonner Toaster: theme prop из контекста ──

jest.mock("sonner", () => ({
  Toaster: (props: { theme?: string }) => (
    <div data-testid="sonner-toaster" data-theme={props.theme ?? "absent"} />
  ),
}));

function ThemeProbe() {
  const { theme } = useTheme();
  return <span data-testid="probe">{theme}</span>;
}

describe("DKT-4: ThemeToaster", () => {
  it("рендерится внутри провайдера и передаёт активную тему в sonner", async () => {
    const { ThemeToaster } = await import("./components/ThemeToaster");
    render(
      <ThemeProvider>
        <ThemeToaster />
        <ThemeProbe />
      </ThemeProvider>,
    );
    const toaster = screen.getByTestId("sonner-toaster");
    // первый кадр — светлая (SSR-согласованность), после эффекта — системная/лёгкая
    expect(toaster.getAttribute("data-theme")).toBe("light");
    expect(toaster.getAttribute("data-theme")).not.toBe("absent");
    expect(screen.getByTestId("probe").textContent).toBe("light");
  });
});

describe("DKT-4: embedded остаётся светлой (решение §10.2)", () => {
  const EMBEDDED_LAYOUT = readFileSync(
    resolve(__dirname, "..", "..", "apps", "embedded", "app", "layout.tsx"),
    "utf8",
  );

  it("layout embedded не монтирует ThemeProvider и no-FOUC-скрипт", () => {
    expect(EMBEDDED_LAYOUT).not.toContain("ThemeProvider");
    expect(EMBEDDED_LAYOUT).not.toContain("NO_FOUC_SCRIPT");
  });
});
