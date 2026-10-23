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
import { fireEvent, render, screen } from "@testing-library/react";
import { ModuleNav } from "./ModuleNav";

// Мокаем usePathname — по умолчанию на /validation, чтобы не было
// ложных срабатываний isActive на корневом пути. Мок-функция изменяемая:
// тест активного состояния «Документов» переключает pathname на
// /documentation (имя с префиксом mock — требование jest.mock-хойстинга).
const mockUsePathname = jest.fn(() => "/validation");
jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

// ModuleNav (PROGR-4): кнопка «Прогресс» рендерит ProgressDrawer, который
// читает activeDataset/targetColumn из shell-контекста; лог удалён (§6.1).
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: null, targetColumn: null }),
}));

const NAV_LABEL = /Навигация по модулям анализа/i;

// Открытие панели «Прогресс» триггит fetch трассы — глушим сеть, чтобы
// тесты кнопки не зависели от бэкенда (панель best-effort, §6.1).
// usePathname возвращаем к дефолту /validation (изолированность тестов).
beforeEach(() => {
  mockUsePathname.mockImplementation(() => "/validation");
  global.fetch = jest.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }) as jest.Mock;
});

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

  it("renders exactly 8 clickable pill badges in the pipeline grid (Документы выведен из пайплайна)", () => {
    const { container } = render(<ModuleNav />);
    // Точечная правка UI (следом за DOCLOG-4): «Документы» логически не
    // продолжает пайплайн исследования — она больше НЕ бейдж сетки
    // этапов (Загрузка → … → Задачи), а отдельная кнопка у «Прогресса».
    const row = container.querySelector("[class*='grid-flow-col']");
    const gridBadges = Array.from(row?.querySelectorAll("a") ?? []).filter((a) =>
      a.className.includes("rounded-full"),
    );
    expect(gridBadges).toHaveLength(8);
    // Каждая бейдж-ссылка ведёт на свой маршрут; /documentation в сетке нет.
    const hrefs = gridBadges.map((b) => b.getAttribute("href"));
    expect(hrefs).toEqual([
      "/", "/upload", "/validation", "/preprocessing",
      "/eda", "/modeling", "/forecasting", "/tasks",
    ]);
    expect(hrefs).not.toContain("/documentation");
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
    // Task EDU-1: «Обучение и база знаний» получает собственную страницу
    // /education (второй бейдж первого ряда главной); «Документация API»
    // остаётся на /docs — маршруты больше не дублируются.
    const menuItems = screen.getAllByRole("menuitem");
    const expectedHrefs = ["/navigator", "/education", "/research", "/pricing", "/docs"];
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

  // ── Кнопка-триггер «Прогресс» (PROGR-4, аддендум §4.1) ──────────

  it("кнопка «Прогресс» на месте слота справа, «Логи событий» удалены", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Логи событий/i })).toBeNull();
  });

  it("pill-форма по паттерну бейджей: rounded-full + h-9 + whitespace-nowrap", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn.className).toContain("rounded-full");
    expect(btn.className).toContain("h-9");
    expect(btn.className).toContain("whitespace-nowrap");
  });

  it("адаптив паддинга/шрифта как у модульных бейджей (px-3/[13px], lg: px-4/sm)", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn.className).toContain("px-3");
    expect(btn.className).toContain("text-[13px]");
    expect(btn.className).toContain("lg:px-4");
    expect(btn.className).toContain("lg:text-sm");
  });

  it("неактивное состояние: bg-white + тонкая border-brand + text-brand (§4.1)", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn.className).toContain("bg-white");
    expect(btn.className).toContain("border-brand");
    expect(btn.className).toContain("text-brand");
    // «Тонкая» = 1px: border-2 запрещён контрактом.
    expect(btn.className).not.toContain("border-2");
    // Сплошной заливки bg-brand (как отдельного токена) нет —
    // hover:bg-brand-light не считается (границы слова).
    expect(btn.className.match(/(?:^|\s)bg-brand(?:\s|$)/)).toBeNull();
    expect(btn.className.match(/(?:^|\s)text-white(?:\s|$)/)).toBeNull();
  });

  it("активное состояние: bg-brand + text-white + font-semibold (§4.1, semibold ≠ font-medium)", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    fireEvent.click(btn);
    // Токены с границами слова: bg-brand ≠ bg-brand-light (hover).
    expect(btn.className.match(/(?:^|\s)bg-brand(?:\s|$)/)).not.toBeNull();
    expect(btn.className.match(/(?:^|\s)text-white(?:\s|$)/)).not.toBeNull();
    expect(btn.className).toContain("font-semibold");
    expect(btn.className).not.toContain("font-medium");
  });

  it("aria-expanded отражает состояние панели и aria-controls указывает на id панели", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(btn).toHaveAttribute("aria-controls", "progress-drawer");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
  });

  it("focus-visible ring — тот же паттерн доступности, что у бейджей", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    expect(btn.className).toContain("focus-visible");
  });

  it("кнопка — отдельная позиция вне ряда pill-бейджей модулей (§4.1)", () => {
    const { container } = render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    const row = container.querySelector("[class*='grid-flow-col']");
    expect(row?.contains(btn)).toBe(false);
  });

  it("повторный клик закрывает панель (toggle)", () => {
    render(<ModuleNav />);
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "false");
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

  // ── Кнопка-ссылка «Документы» рядом с «Прогрессом» ──────────────
  // Точечная правка UI (следом за DOCLOG-4) по постановке тимлида:
  // «Документы» логически не может продолжать пайплайн исследования
  // (О платформе/Загрузка/Валидация/…/Задачи), поэтому она отделяется
  // от вкладки «Задачи», отцентрируется рядом с кнопкой «Прогресс»
  // (смещается правее), а её дизайн следует паттерну кнопки «Прогресс»:
  // неактивная — белый фон + тонкая (1px) фирменная рамка + индиго-текст,
  // активная — заливка индиго + белый полужирный текст.

  it("«Документы» — ссылка вне ряда бейджей пайплайна (отделена от «Задач»)", () => {
    const { container } = render(<ModuleNav />);
    const link = screen.getByText("Документы").closest("a");
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "/documentation");
    // НЕ в сетке равных ширин (row.grid-flow-col) — вне пайплайна.
    const row = container.querySelector("[class*='grid-flow-col']");
    expect(row?.contains(link ?? null)).toBe(false);
  });

  it("«Документы» отцентрирована в правой группе рядом с «Прогрессом» (первая в группе, Прогресс — крайний справа)", () => {
    render(<ModuleNav />);
    const link = screen.getByText("Документы").closest("a");
    const btn = screen.getByRole("button", { name: /Прогресс/i });
    const group = link?.parentElement;
    // Общая группа справа: оба элемента в одном flex-контейнере.
    expect(group?.contains(btn ?? null)).toBe(true);
    expect(group?.className).toContain("flex");
    expect(group?.className).toContain("items-center");
    // «Документы» — ПЕРВАЯ в группе (левее «Прогресса»), «Прогресс»
    // сохраняет крайний правый слот (§4.1).
    expect(group?.firstElementChild).toBe(link);
  });

  it("дизайн по паттерну «Прогресс»: pill h-9 + rounded-full + whitespace-nowrap + focus-visible", () => {
    render(<ModuleNav />);
    const link = screen.getByText("Документы").closest("a");
    expect(link?.className).toContain("h-9");
    expect(link?.className).toContain("rounded-full");
    expect(link?.className).toContain("whitespace-nowrap");
    expect(link?.className).toContain("focus-visible");
    expect(link?.className).not.toContain("border-2");
  });

  it("неактивное состояние: bg-white + тонкая border-brand + text-brand (паттерн «Прогресс»)", () => {
    render(<ModuleNav />); // usePathname = /validation → «Документы» неактивна
    const link = screen.getByText("Документы").closest("a");
    expect(link?.className).toContain("bg-white");
    expect(link?.className).toContain("border-brand");
    expect(link?.className).toContain("text-brand");
    // Сплошной заливки и белого текста нет (токены с границами слов).
    expect(link?.className.match(/(?:^|\s)bg-brand(?:\s|$)/)).toBeNull();
    expect(link?.className.match(/(?:^|\s)text-white(?:\s|$)/)).toBeNull();
  });

  it("активное состояние на /documentation: bg-brand + text-white + font-semibold + aria-current (паттерн «Прогресс»)", () => {
    mockUsePathname.mockReturnValue("/documentation");
    render(<ModuleNav />);
    const link = screen.getByText("Документы").closest("a");
    // Токены с границами слова: bg-brand ≠ bg-brand-light (hover).
    expect(link?.className.match(/(?:^|\s)bg-brand(?:\s|$)/)).not.toBeNull();
    expect(link?.className.match(/(?:^|\s)text-white(?:\s|$)/)).not.toBeNull();
    // semibold «Прогресса», а не font-medium модульных бейджей.
    expect(link?.className).toContain("font-semibold");
    expect(link?.className).not.toContain("font-medium");
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("без иконки — текстовая кнопка (правка не добавляет пиктограмм)", () => {
    render(<ModuleNav />);
    const link = screen.getByText("Документы").closest("a");
    expect(link?.querySelector("svg")).toBeNull();
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
