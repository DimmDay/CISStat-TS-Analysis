// packages/ui/components/ModuleNav.test.tsx
//
// Тесты для ModuleNav — проверка навигации, выравнивания и
// аккордеона «О платформе» (Task 25).
//
// Task w/n — реформатинг классических вкладок меню в кликабельные
// бейджи-«таблетки» по образцу localnav apple.com/apple-intelligence
// ("Overview"/"iOS"/"macOS"): pill rounded-full, светлая нейтральная
// заливка неактивного, сплошная brand-заливка активного. Отличие от
// образца по постановке тимлида: ВСЕ бейджи одинакового размера по
// высоте и ширине — ширина каждого равна ширине максимального бейджа
// (CSS-контракт inline-grid + grid-flow-col + auto-cols-fr; эмпирика
// проба на реальном браузере: 5 бейджей разного текста → ровно
// одинаковые 155.2×35px).

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ModuleNav } from "./ModuleNav";

// Мокаем usePathname — по умолчанию на /validation, чтобы не было
// ложных срабатываний isActive на корневом пути.
jest.mock("next/navigation", () => ({
  usePathname: () => "/validation",
}));

// ModuleNav показывает "Логи событий" — нужен log.
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ log: [] }),
}));

const NAV_LABEL = /Навигация по модулям анализа/i;

// Бейджи главного меню = ссылки с pill-формой внутри навигации.
const getBadges = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("a")).filter((a) =>
    a.className.includes("rounded-full"),
  );

describe("ModuleNav", () => {
  it("renders all module tabs including 'О платформе'", () => {
    render(<ModuleNav />);
    const tabs = [
      "О платформе", "Загрузка", "Валидация", "Предобработка", "Разведочный EDA",
      "Моделирование", "Прогнозирование", "Задачи",
    ];
    tabs.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  it("has a max-w-[1600px] container for content alignment", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: NAV_LABEL });
    expect(nav).toBeInTheDocument();
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv).toBeInTheDocument();
  });

  it("content container has px-6 matching main content padding", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: NAV_LABEL });
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv?.className).toMatch(/px-6/);
  });

  // ── Бейджи-«таблетки» (Task w/n, образец Apple localnav) ────────

  it("renders exactly 8 clickable pill badges (main menu items)", () => {
    const { container } = render(<ModuleNav />);
    const badges = getBadges(container);
    expect(badges).toHaveLength(8);
    // Каждая бейдж-ссылка ведёт на свой маршрут.
    const hrefs = badges.map((b) => b.getAttribute("href"));
    expect(hrefs).toEqual([
      "/", "/upload", "/validation", "/preprocessing",
      "/eda", "/modeling", "/forecasting", "/tasks",
    ]);
  });

  it("badge row uses the equal-width grid contract (inline-grid + grid-flow-col + auto-cols-fr)", () => {
    // Условие постановки: бейджи одинаковые по высоте и ширине ПО
    // МАКСИМАЛЬНОМУ бейджу. CSS-механика: grid-auto-flow: column +
    // grid-auto-columns: 1fr при max-content-ширине контейнера даёт
    // всем колонкам ширину самой широкой (эмпирика проба).
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: NAV_LABEL });
    const row = nav.querySelector("[class*='grid-flow-col']");
    expect(row).not.toBeNull();
    expect(row?.className).toContain("inline-grid");
    expect(row?.className).toContain("auto-cols-fr");
  });

  it("all badges share the uniform pill shape and height (rounded-full + h-9)", () => {
    const { container } = render(<ModuleNav />);
    const badges = getBadges(container);
    expect(badges.length).toBeGreaterThan(0);
    badges.forEach((badge) => {
      expect(badge.className).toContain("rounded-full");
      expect(badge.className).toContain("h-9");
      // Текст не переносится — ширина колонки определяется самым
      // длинным заголовком («Разведочный EDA»), а не переносом строк.
      expect(badge.className).toContain("whitespace-nowrap");
    });
  });

  it("active badge uses filled brand style (bg-brand + text-white)", () => {
    // usePathname замокан на /validation — бейдж «Валидация» активен:
    // сплошная заливка фирменным индиго и белый текст (аналог тёмного
    // активного бейджа Apple).
    render(<ModuleNav />);
    const badge = screen.getByText("Валидация").closest("a");
    expect(badge?.className).toContain("bg-brand");
    expect(badge?.className).toContain("text-white");
    expect(badge?.className).toContain("font-medium");
  });

  it("inactive badges use neutral fill and never the active brand fill", () => {
    render(<ModuleNav />);
    ["Загрузка", "Предобработка", "Моделирование"].forEach((label) => {
      const badge = screen.getByText(label).closest("a");
      expect(badge?.className).toContain("bg-neutral-100");
      expect(badge?.className).not.toContain("bg-brand");
      expect(badge?.className).not.toContain("text-white");
    });
  });

  it("'О платформе' badge keeps the accordion chevron", () => {
    const { container } = render(<ModuleNav />);
    const badge = screen.getByText("О платформе").closest("a");
    expect(badge?.querySelector("svg")).not.toBeNull();
    // И бейдж «О платформе» — часть общей сетки равных ширин.
    const row = container.querySelector("[class*='grid-flow-col']");
    const wrapper = badge?.parentElement;
    expect(row?.contains(wrapper ?? null)).toBe(true);
  });

  it("'О платформе' badge fills its stretched grid wrapper (w-full) — equal width by max badge", () => {
    // Бейдж «О платформе» — единственный, чья ссылка обёрнута в div
    // (wrapper несёт hover-аккордеон). Wrapper растягивается до ширины
    // fr-колонки, но ссылка внутри — inline-flex по контенту: без
    // w-full она УЖЕ оставалась шире/уже колонки (живой замер: 150.9px
    // против 162.8px остальных). Контракт: w-full на триггере.
    render(<ModuleNav />);
    const badge = screen.getByText("О платформе").closest("a");
    expect(badge?.className).toContain("w-full");
  });

  it("badge row keeps overflow-visible so the accordion panel is not clipped", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: NAV_LABEL });
    const row = nav.querySelector("[class*='grid-flow-col']");
    expect(row?.className).toContain("overflow-visible");
  });

  // ── Аккордеон «О платформе» (Task 25) ──────────────────────────

  it("'О платформе' link points to /", () => {
    render(<ModuleNav />);
    const link = screen.getByText("О платформе").closest("a");
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders 5 sub-links in the 'О платформе' accordion panel", () => {
    render(<ModuleNav />);
    const subLinks = [
      "Знакомство с платформой",
      "Обучение и база знаний",
      "Отраслевые исследования",
      "Доступ и тарифы",
      "Документация API",
    ];
    subLinks.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  it("accordion sub-links have correct hrefs from HOME_ROUTES", () => {
    render(<ModuleNav />);
    // role="menuitem" переопределяет неявную роль link —
    // ищем по menuitem, а не по link.
    const menuItems = screen.getAllByRole("menuitem");
    const expectedHrefs = ["/navigator", "/docs", "/research", "/pricing", "/docs"];
    const actualHrefs = menuItems.map((mi) => mi.getAttribute("href"));
    expect(actualHrefs).toEqual(expectedHrefs);
  });

  it("accordion panel has role='menu' for accessibility", () => {
    render(<ModuleNav />);
    const menu = screen.getByRole("menu", { name: /О платформе/i });
    expect(menu).toBeInTheDocument();
  });

  it("'О платформе' trigger has aria-haspopup='menu'", () => {
    render(<ModuleNav />);
    const trigger = screen.getByText("О платформе").closest("a");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  });

  it("'О платформе' is NOT marked active when pathname is /validation", () => {
    // usePathname мокнут на /validation — бейдж «О платформе» в
    // нейтральной заливке, без активного brand-стиля.
    render(<ModuleNav />);
    const trigger = screen.getByText("О платформе").closest("a");
    expect(trigger?.className).toContain("bg-neutral-100");
    expect(trigger?.className).not.toContain("bg-brand");
    expect(trigger?.className).not.toContain("text-white");
  });

  // ── Guard-тесты нетронутости остального ─────────────────────────

  it("guard: 'Логи событий' button is present and unchanged", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Логи событий/i });
    expect(btn).toBeInTheDocument();
  });

  // ── Точечная правка: линия-подчёркивание под меню убрана ────────

  it("guard: nav has NO bottom border line (border-b removed)", () => {
    // Точечная правка по постановке тимлида: горизонтальная линия под
    // строкой бейджей (border-b border-neutral-200 на <nav>) убрана.
    // Фон белый сохраняется, геометрия бейджей не затрагивается.
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: NAV_LABEL });
    expect(nav.className).not.toContain("border-b");
    expect(nav.className).not.toContain("border-neutral-200");
    // Фон навигации не изменился.
    expect(nav.className).toContain("bg-white");
  });

  it("does NOT render 'Навигатор' tab (renamed to 'О платформе' in Task 25)", () => {
    render(<ModuleNav />);
    expect(screen.queryByText("Навигатор")).toBeNull();
  });

  it("does NOT render 'Приступить к анализу данных' in accordion (already in main nav as 'Загрузка')", () => {
    render(<ModuleNav />);
    expect(screen.queryByText("Приступить к анализу данных")).toBeNull();
  });
});
