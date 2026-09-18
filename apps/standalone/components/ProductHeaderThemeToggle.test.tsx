// apps/standalone/components/ProductHeaderThemeToggle.test.tsx
//
// Task DKT-1 — переключатель темы в ProductHeader (spec_dark_theme.md §4.6).
//
// Постановка тимлида: переключатель — сменяющие друг друга иконки
// луна/солнце в ProductHeader справа, рядом с «РУС / ENG».
// Поведение: Moon в светлой теме («включить тёмную»), Sun в тёмной
// («включить светлую»); aria-label по состоянию, aria-pressed;
// клик меняет класс .dark на <html> и ключ localStorage["cisstat-theme"].

import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ProductHeader } from "./ProductHeader";
import { ThemeProvider } from "@cisstat/ui";
import { THEME_STORAGE_KEY } from "@cisstat/ui/context/ThemeContext";

const LAYOUT_PATH = resolve(process.cwd(), "apps/standalone/app/layout.tsx");

function renderHeader(stored?: "light" | "dark") {
  if (stored) window.localStorage.setItem(THEME_STORAGE_KEY, stored);
  else window.localStorage.removeItem(THEME_STORAGE_KEY);
  return render(
    <ThemeProvider>
      <ProductHeader />
    </ThemeProvider>
  );
}

describe("Переключатель темы в ProductHeader (§4.6)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.style.colorScheme = "";
    document
      .querySelectorAll('meta[name="theme-color"]')
      .forEach((m) => m.remove());
  });

  it("расположен между «РУС / ENG» и кнопкой кабинета (DOM-порядок)", () => {
    renderHeader();
    const rusEng = screen.getByText("РУС / ENG");
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    const cabinet = screen.getByLabelText("Личный кабинет");
    expect(
      // eslint-disable-next-line no-bitwise
      rusEng.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      // eslint-disable-next-line no-bitwise
      toggle.compareDocumentPosition(cabinet) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("в светлой теме показывает Moon и aria по состоянию", () => {
    const { container } = renderHeader();
    expect(container.querySelector("svg.lucide-moon")).not.toBeNull();
    expect(container.querySelector("svg.lucide-sun")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("в тёмной теме показывает Sun и зеркальный aria-label", async () => {
    const { container } = renderHeader("dark");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeInTheDocument()
    );
    expect(container.querySelector("svg.lucide-sun")).not.toBeNull();
    expect(container.querySelector("svg.lucide-moon")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Включить светлую тему" })
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("клик в светлой теме включает тёмную: класс .dark + персист ключа", async () => {
    renderHeader();
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    act(() => {
      fireEvent.click(toggle);
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    // иконка сменилась на Sun, aria зеркально
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Включить светлую тему" })
      ).toHaveAttribute("aria-pressed", "true")
    );
  });

  it("повторный клик возвращает светлую тему", async () => {
    renderHeader();
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: "Включить светлую тему" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("повторяет визуальный паттерн соседа «РУС / ENG» (§4.6)", () => {
    renderHeader();
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    expect(toggle).toHaveClass("text-neutral-500");
    expect(toggle.className).toContain("hover:text-neutral-900");
    expect(toggle.getAttribute("type")).toBe("button");
  });

  it("иконки Moon/Sun берутся из lucide-react, размер 14", () => {
    const source = readFileSync(
      resolve(process.cwd(), "apps/standalone/components/ProductHeader.tsx"),
      "utf8"
    );
    expect(source).toContain("from \"lucide-react\"");
    expect(source).toMatch(/Moon[^)]*size=\{14\}|size=\{14\}[^)]*Moon/s);
  });
});

describe("Монтирование темы в RootLayout (§4.4, §4.5)", () => {
  it("layout.tsx содержит no-FOUC-скрипт в <head> до гидратации", () => {
    const source = readFileSync(LAYOUT_PATH, "utf8");
    expect(source).toContain("dangerouslySetInnerHTML");
    expect(source).toContain("NO_FOUC_SCRIPT");
  });

  it("layout.tsx оборачивает содержимое в ThemeProvider из @cisstat/ui", () => {
    const source = readFileSync(LAYOUT_PATH, "utf8");
    expect(source).toContain("ThemeProvider");
    // ProductHeader (переключатель) — ВНУТРИ провайдера
    const providerIdx = source.indexOf("<ThemeProvider>");
    const headerIdx = source.indexOf("<ProductHeader />");
    expect(providerIdx).toBeGreaterThan(-1);
    expect(headerIdx).toBeGreaterThan(providerIdx);
  });

  it("<html> получает suppressHydrationWarning (класс ставится скриптом)", () => {
    const source = readFileSync(LAYOUT_PATH, "utf8");
    expect(source).toMatch(/<html[^>]*suppressHydrationWarning/s);
  });

  it("no-FOUC-скрипт и ThemeProvider экспортируются из @cisstat/ui", () => {
    const indexPath = resolve(process.cwd(), "packages/ui/index.ts");
    expect(existsSync(indexPath)).toBe(true);
    const source = readFileSync(indexPath, "utf8");
    expect(source).toContain("ThemeContext");
    expect(source).toMatch(/ThemeProvider/);
  });
});
