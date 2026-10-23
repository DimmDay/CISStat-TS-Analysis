// apps/standalone/app/documentation/page.test.tsx
//
// Точечные UI-правки DOCLOG-4 + полировка (следом за DOCLOG-4-UI-FIX)
// на странице «Документы исследования»:
//   1. Заголовок «Документы исследования» — брендовый индиго (text-brand;
//      тёмная ревизия .dark .text-brand → brand-bright — автоматическая,
//      utility-ревизия globals.css §3).
//   2. Фон страницы = фон «О платформе» в усечённом по высоте варианте
//      (DocumentationWavesBackground, viewBox без верхней половины),
//      подключён по паттерну главной: relative isolate -mt-6 pt-6, фон —
//      первый ребёнок, позади контента.
//   3. Отступы ТЕКСТА и БЕЙДЖЕЙ от границ страницы (слева/справа) — по
//      паттерну главной страницы («О платформе»): собственные поля 24px
//      (px-6) у обёртки КОНТЕНТА — как сетки бейджей px-6 на главной
//      (HomeHero/HomeCapabilities/NavigatorHero: «px-6 — собственные
//      поля от границ фоновой коробки»). Фоновая коробка (root) при
//      этом остаётся БЕЗ горизонтальной подложки — её границы совпадают
//      с content-box <main>, а контент ужат внутри на 24px с каждой
//      стороны. Итог от страницы: текст/бейджи — 48px (24px <main px-6>
//      + 24px px-6 контента), фон — 24px; байт-равно главной странице.
//
// Тест целится в DocumentationPageShell — синхронная статическая оболочка
// страницы (каркас правок, documentation-shell.tsx; Next.js разрешает
// page-модулю только default export, поэтому Shell живёт отдельным файлом);
// асинхронная searchParams-водопроводка DOCLOG-4 не менялась и остаётся за
// границей сьюты (Suspense + клиентский контур).

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationPageShell } from "./documentation-shell";

describe("Standalone documentation page — точечные UI-правки DOCLOG-4", () => {
  it("заголовок «Документы исследования» — брендовый индиго (text-brand, без прежнего neutral-900)", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const h1 = container.querySelector("h1");

    expect(h1?.textContent).toContain("Документы исследования");
    expect(h1?.className).toContain("text-brand");
    expect(h1?.className).not.toContain("text-neutral-900");
    expect(h1?.className).not.toContain("dark:text-neutral-100");
  });

  it("фон — усечённый сверху вариант фона «О платформе» (первый ребёнок обёртки, aria-hidden)", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;

    // Паттерн главной страницы: -mt-6 pt-6 (фон доходит до меню), isolate.
    expect(root?.className).toContain("relative");
    expect(root?.className).toContain("isolate");
    expect(root?.className).toContain("-mt-6");
    expect(root?.className).toContain("pt-6");
    // Фон — ПЕРВЫЙ ребёнок обёртки (позади контента).
    expect(root?.firstElementChild).toHaveAttribute("aria-hidden", "true");

    const svg = root?.querySelector("svg");
    expect(svg).toBeInTheDocument();
    // Усечение сверху: viewBox сдвинут на y=800 (верхняя половина отрезана).
    expect(svg).toHaveAttribute("viewBox", "0 800 1600 800");
  });

  it("фоновая коробка (root) без собственной гориз. подложки — её границы совпадают с content-box <main>", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;

    expect(root?.className).toContain("max-w-[1600px]");
    expect(root?.className).toContain("mx-auto");
    // Подложка на фоновой коробке сдвинула бы и фон, и границы бокса —
    // инсеты контента даёт обёртка содержимого (px-6), не root.
    expect(root?.className).not.toMatch(/\bpx-\d/);
  });

  it("инсеты текста и бейджей по паттерну главной: обёртка контента несёт собственные поля 24px (px-6)", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;
    const content = root?.children[1];

    expect(content?.className).toContain("relative");
    // Паттерн главной страницы (сетка RouteCard/NavigatorHero): px-6 —
    // собственные поля 24px контента от границ фоновой коробки.
    expect(content?.className).toContain("px-6");
    expect(content?.textContent).toContain("проверка");
  });

  it("фон +24px ниже нижней границы бейджей: обёртка контента несёт pb-6 (высота фоновой коробки +24px, зазор динамико-устойчив)", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;
    const content = root?.children[1];

    // Постановка DOCLOG-4-UI-FIX-3 п.1: от нижней границы бейджей до
    // границы фона — расстояние 24px; высота фона увеличена на 24px.
    // pb-6 стоит на обёртке контента (root растёт за счёт потока), фон
    // absolute inset-0 заполняет — полоса волн ниже бейджей сохраняется
    // при любом динамическом содержимом.
    expect(content?.className).toContain("pb-6");
    // Фоновая коробка при этом своей подложки снизу не несёт (растёт
    // содержимым, а не паддингом — иначе фон не дошёл бы до низа).
    expect(root?.className).not.toMatch(/\bpb-\d/);
  });

  it("контент остаётся над фоном: relative-обёртка содержимого после фона", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;
    const content = root?.children[1];

    expect(content?.className).toContain("relative");
    expect(content?.textContent).toContain("проверка");
  });
});
