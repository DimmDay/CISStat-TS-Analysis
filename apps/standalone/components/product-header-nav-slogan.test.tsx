// apps/standalone/components/product-header-nav-slogan.test.tsx
//
// Task UI-HOME-HEADER-1 (2026-10-15) — верхнее меню ProductHeader главной
// standalone (https://ts-standalone.vercel.app/):
//
//   1. Пункты меню («Обучение», «Документация API», «Тарифы», «Личный
//      кабинет») перемещены ВПРАВО — в правый контейнер, к «РУС / ENG»,
//      с отступом меню от «РУС / ENG» (mr-5 меню + gap-5 контейнера =
//      40px — крупнее внутри-менюного шага 24px и правого шага 20px).
//      Пункт «Продукт» заменён на «Обучение» (href /education — страница
//      «Обучение и база знаний», EDU-1; маршрута /product в standalone
//      не существует).
//   2. Слева, после «CISStat TS Analysis», с небольшим отступом (gap-6
//      левой группы, 24px) — НЕКЛИКАБЕЛЬНЫЙ слоган «Цифровая научно-
//      исследовательская лаборатория»: обычный span (не ссылка, не
//      кнопка, вне ссылки бренда), размер и толщина шрифта как у бренда
//      (text-[20px] leading-none font-normal tracking-tight), цвет —
//      серый токен text-neutral-600 (светлая #525252; тёмная ревизия
//      #B5B8C1 подставляется платформенным контрактом DKT «имена классов
//      не меняются — меняются значения» — dark:-ветвления не вводятся).
//   3. Весь текст меню выровнен по нижней границе «CISStat TS Analysis»:
//      выравниваются БАЗОВЫЕ линии текстов (типографская «нижняя граница»
//      строки). Ряд/группы СОХРАНЯЮТ items-center (позиции логотипа,
//      бренда и иконок — байт-в-байт к живой странице до задачи), а nav и
//      «РУС / ENG» получают документированный метрический сдвиг
//      relative top-[2.4px]: при items-center базовая линия текста кегля
//      s сидит на 14px + 0.364×s от верха 28px ряда (0.364 = (asc−desc)/2
//      метрик Inter, зафиксирован next/font), разница с брендом (20px) =
//      0.364×Δкегля ≈ 2.4px и не устранима выбором line-height. Слоган —
//      тот же кегль, что у бренда: выровнен конструктивно (одинаковый бокс
//      4..24 в 28px ряду), сдвиг не нужен. items-baseline был реализован
//      и отвергнут браузерной верификацией: флекс-линия правого контейнера
//      вырастала до 28px (аватар h-7), self-end притапливал иконки на 6px
//      в нижний паддинг. Браузерный замер dev-сервера: базовые линии
//      бренда/слогана/меню/«РУС / ENG» совпадают с точностью 0.04–0.15px,
//      высота шапки 48px сохранена.
//
// jsdom не считает layout — геометрия пинится СТРУКТУРНО (классы сдвига,
// состав групп, сохранение выравнивания items-center), браузерная
// верификация базовых линий выполнена на dev-сервере (замер Range API,
// светлая и тёмная темы).

import { render, screen } from "@testing-library/react";
import { ProductHeader } from "./ProductHeader";

const SLOGAN = "Цифровая научно-исследовательская лаборатория";

function renderHeader() {
  return render(<ProductHeader />);
}

describe("UI-HOME-HEADER-1: меню вправо, слоган, нижнее выравнивание", () => {
  it("пункт «Продукт» заменён на «Обучение» с href /education", () => {
    renderHeader();

    // Новый пункт.
    const edu = screen.getByRole("link", { name: "Обучение" });
    expect(edu).toHaveAttribute("href", "/education");

    // Старого пункта нет.
    expect(screen.queryByText("Продукт")).toBeNull();

    // Остальные пункты не тронуты.
    expect(screen.getByRole("link", { name: "Документация API" })).toHaveAttribute("href", "/docs");
    expect(screen.getByRole("link", { name: "Тарифы" })).toHaveAttribute("href", "/pricing");
    expect(screen.getByRole("link", { name: "Личный кабинет" })).toHaveAttribute("href", "/dashboard");
  });

  it("меню перемещено вправо: nav в правом контейнере, перед «РУС / ENG», вне левой группы бренда", () => {
    renderHeader();

    const brand = screen.getByText("CISStat TS Analysis", { selector: "strong" });
    const brandLink = brand.closest("a")!;
    const leftGroup = brandLink.parentElement!;
    const nav = screen.getByRole("navigation");
    const rusEng = screen.getByText("РУС / ENG");
    const rightGroup = rusEng.parentElement!;

    // nav больше не в левой группе (рядом с брендом).
    expect(leftGroup.contains(nav)).toBe(false);
    // nav в правом контейнере, рядом с «РУС / ENG».
    expect(rightGroup.contains(nav)).toBe(true);
    // nav ПЕРЕД «РУС / ENG» (DOM-порядок = слева от него).
    // eslint-disable-next-line no-bitwise
    expect(nav.compareDocumentPosition(rusEng) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("отступ меню от «РУС / ENG» = mr-5 меню + gap-5 правого контейнера (40px)", () => {
    renderHeader();

    const nav = screen.getByRole("navigation");
    const rusEng = screen.getByText("РУС / ENG");
    const rightGroup = rusEng.parentElement!;

    expect(nav).toHaveClass("mr-5");
    expect(rightGroup).toHaveClass("gap-5");
    // Правый контейнер не «сливает» меню с РУС/ENG меньшим шагом.
    expect(nav.className).not.toContain("mr-0");
  });

  it("слоган: некликабельный span после бренда, в левой группе, с точным текстом", () => {
    renderHeader();

    const slogan = screen.getByText(SLOGAN);
    const brand = screen.getByText("CISStat TS Analysis", { selector: "strong" });
    const brandLink = brand.closest("a")!;
    const leftGroup = brandLink.parentElement!;

    // Некликабельный: не ссылка, не кнопка, вне ссылки бренда.
    expect(slogan.tagName).toBe("SPAN");
    expect(slogan.closest("a")).toBeNull();
    expect(slogan.closest("button")).toBeNull();

    // После бренда, прямым ребёнком левой группы (тот же ряд).
    // eslint-disable-next-line no-bitwise
    expect(brandLink.compareDocumentPosition(slogan) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(slogan.parentElement).toBe(leftGroup);
  });

  it("слоган: размер, толщина и трекинг как у бренда; однострочный", () => {
    renderHeader();

    const brand = screen.getByText("CISStat TS Analysis", { selector: "strong" });
    const slogan = screen.getByText(SLOGAN);

    for (const cls of ["text-[20px]", "leading-none", "font-normal", "tracking-tight"]) {
      expect(brand).toHaveClass(cls);
      expect(slogan).toHaveClass(cls);
    }
    expect(slogan).toHaveClass("whitespace-nowrap");
  });

  it("слоган: серый токен text-neutral-600 без dark:-ветвлений (платформенный паттерн тёмной темы)", () => {
    renderHeader();

    const slogan = screen.getByText(SLOGAN);

    // Токенизированный серый (светлая #525252, тёмная #B5B8C1 — ревизия
    // подставляется палитрой globals.css, имя класса не меняется).
    expect(slogan).toHaveClass("text-neutral-600");
    expect(slogan.className).not.toContain("dark:");
  });

  it("нижнее выравнивание: nav и «РУС / ENG» несут метрический сдвиг top-[2.4px], ряд сохраняет items-center", () => {
    renderHeader();

    const brand = screen.getByText("CISStat TS Analysis", { selector: "strong" });
    const brandLink = brand.closest("a")!;
    const row = brandLink.parentElement!.parentElement!;
    const nav = screen.getByRole("navigation");
    const rusEng = screen.getByText("РУС / ENG");

    // Конструкция: ряд/группы items-center (логотип, бренд, иконки —
    // без сдвигов), базовая линия мелких текстов дотягивается до базовой
    // линии бренда метрическим сдвигом 0.364×Δкегля ≈ 2.4px.
    expect(row).toHaveClass("items-center");
    expect(nav).toHaveClass("relative");
    expect(nav).toHaveClass("top-[2.4px]");
    expect(rusEng).toHaveClass("relative");
    expect(rusEng).toHaveClass("top-[2.4px]");
  });

  it("слоган выровнен конструктивно (тот же кегль, что у бренда) — без метрического сдвига", () => {
    renderHeader();

    const slogan = screen.getByText(SLOGAN);

    // Одинаковый бокс 20px в 28px ряду даёт совпадение бокса И базовой
    // линии с брендом без сдвига; наличие top-сдвига сломало бы паритет.
    expect(slogan.className).not.toMatch(/top-\[/);
  });

  it("логотип, бренд и иконки не затронуты выравниванием (нет self-*/pt-сдвигов)", () => {
    renderHeader();

    const logo = screen.getByAltText("CISStat TS Analysis");
    const brand = screen.getByText("CISStat TS Analysis", { selector: "strong" });
    const toggle = screen.getByRole("button", { name: "Включить тёмную тему" });
    const cabinet = screen.getByLabelText("Личный кабинет");
    const logoBox = logo.closest("div.relative")!;

    expect(logoBox.className).not.toMatch(/self-/);
    expect(brand.className).not.toMatch(/\bpt-|\bself-|\btop-\[/);
    expect(toggle.className).not.toMatch(/self-|top-\[/);
    expect(cabinet.className).not.toMatch(/self-|top-\[/);
  });
});
