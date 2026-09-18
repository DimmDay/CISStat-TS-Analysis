// packages/ui/context/ThemeContext.test.tsx
//
// Task DKT-1 — юниты провайдера темы (spec_dark_theme.md §4.3, §5, §8.3).
//
// Контракт темы (§5):
//   - ключ хранения localStorage["cisstat-theme"], значения "light"|"dark";
//   - класс-триггер .dark на <html>; отсутствие класса = светлая;
//   - порядок инициализации: localStorage → prefers-color-scheme → light;
//   - no-FOUC-скрипт повторяет ту же арифметику до гидратации (§4.5).

import { render, screen, act, waitFor, fireEvent } from "@testing-library/react";
import {
  ThemeProvider,
  useTheme,
  resolveInitialTheme,
  NO_FOUC_SCRIPT,
  THEME_STORAGE_KEY,
  applyTheme,
} from "./ThemeContext";

function ThemeProbe() {
  const { theme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="probe">{theme}</span>
      <button data-testid="toggle" onClick={toggleTheme}>
        toggle
      </button>
    </div>
  );
}

/** Управляемый стаб matchMedia (jest.setup даёт дефолт light). */
function stubMatchMedia(dark: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: dark && query === "(prefers-color-scheme: dark)",
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

describe("resolveInitialTheme: порядок localStorage → системная схема → light (§5)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
    stubMatchMedia(false);
  });

  it("сохранённое dark значение приоритетно", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("сохранённое light значение приоритетно даже при системной тёмной", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    stubMatchMedia(true);
    expect(resolveInitialTheme()).toBe("light");
  });

  it("без хранения берётся системная схема dark", () => {
    stubMatchMedia(true);
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("без хранения и системной тёмной — light", () => {
    expect(resolveInitialTheme()).toBe("light");
  });

  it("мусор в localStorage игнорируется (не light/dark)", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "banana");
    expect(resolveInitialTheme()).toBe("light");
  });
});

describe("NO_FOUC_SCRIPT: арифметика первого кадра (§4.5)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.style.colorScheme = "";
    stubMatchMedia(false);
  });

  it("это самодостаточный IIFE без зависимостей, упоминающий контракт", () => {
    expect(NO_FOUC_SCRIPT).toContain(THEME_STORAGE_KEY);
    expect(NO_FOUC_SCRIPT).toContain('"dark"');
    expect(NO_FOUC_SCRIPT).toContain("prefers-color-scheme: dark");
    expect(NO_FOUC_SCRIPT).toContain("classList.toggle");
  });

  it("сохранённый dark ставит класс .dark и color-scheme до гидратации", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(NO_FOUC_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("сохранённый light при системной тёмной НЕ ставит .dark (персист сильнее)", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    stubMatchMedia(true);
    new Function(NO_FOUC_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("без хранения системная тёмная ставит .dark", () => {
    stubMatchMedia(true);
    new Function(NO_FOUC_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("ThemeProvider: инициализация и применение класса (§4.3)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.style.colorScheme = "";
    document
      .querySelectorAll('meta[name="theme-color"]')
      .forEach((m) => m.remove());
    stubMatchMedia(false);
  });

  it("пере-выводит тему из того же источника истины, что и no-FOUC-скрипт", async () => {
    // Скрипт §4.5 и resolveInitialTheme используют ОДНУ арифметику
    // (localStorage → системная схема → light), поэтому провайдер
    // пере-выводит то же состояние, не читая класс с <html>.
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    document.documentElement.classList.add("dark");
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("самоисправляет рассинхрон: класс без причины снимается (провайдер владеет классом после монтирования)", async () => {
    // Искусственный state (класс есть, причин в localStorage/системе нет)
    // в проде невозможен — провайдер возвращает систему к источнику истины.
    document.documentElement.classList.add("dark");
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("инициализация idempotentна: класс и color-scheme соответствуют состоянию", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("toggleTheme меняет класс на <html>, color-scheme и персистит ключ (§5)", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));

    fireEvent.click(screen.getByTestId("toggle"));
    expect(screen.getByTestId("probe")).toHaveTextContent("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    fireEvent.click(screen.getByTestId("toggle"));
    expect(screen.getByTestId("probe")).toHaveTextContent("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("toggleTheme обновляет meta theme-color (§4.2)", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));
    const meta = document.querySelector('meta[name="theme-color"]');
    expect(meta).not.toBeNull();
    expect(meta!.getAttribute("content")).toBe("#FFFFFF");

    fireEvent.click(screen.getByTestId("toggle"));
    expect(meta!.getAttribute("content")).toBe("#0B0C10");
  });

  it("storage-событие синхронизирует кросс-таб (§4.3)", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: THEME_STORAGE_KEY,
          newValue: "dark",
          oldValue: null,
        })
      );
    });
    expect(screen.getByTestId("probe")).toHaveTextContent("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("storage-событие с чужим ключом игнорируется", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("light"));

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "other-key", newValue: "dark" })
      );
    });
    expect(screen.getByTestId("probe")).toHaveTextContent("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

describe("applyTheme: идемпотентное применение (вспомогательный контракта)", () => {
  beforeEach(() => {
    document.documentElement.className = "";
    document.documentElement.style.colorScheme = "";
    document
      .querySelectorAll('meta[name="theme-color"]')
      .forEach((m) => m.remove());
  });

  it("создаёт meta theme-color при отсутствии и обновляет по теме", () => {
    applyTheme("light");
    expect(
      document.querySelector('meta[name="theme-color"]')!.getAttribute("content")
    ).toBe("#FFFFFF");
    applyTheme("dark");
    expect(
      document.querySelector('meta[name="theme-color"]')!.getAttribute("content")
    ).toBe("#0B0C10");
    // meta не дублируется
    expect(
      document.querySelectorAll('meta[name="theme-color"]').length
    ).toBe(1);
  });

  it("переключает класс .dark и color-scheme синхронно", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
