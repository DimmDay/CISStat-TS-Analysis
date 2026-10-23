// apps/standalone/app/documentation/page.test.tsx
//
// Точечные UI-правки DOCLOG-4 на странице «Документы исследования»:
//   1. Заголовок «Документы исследования» — брендовый индиго (text-brand;
//      тёмная ревизия .dark .text-brand → brand-bright — автоматическая,
//      utility-ревизия globals.css §3).
//   2. Фон страницы = фон «О платформе» в усечённом по высоте варианте
//      (DocumentationWavesBackground, viewBox без верхней половины),
//      подключён по паттерну главной: relative isolate -mt-6 pt-6, фон —
//      первый ребёнок, позади контента.
//   3. Отступы бейджей от краёв страницы (слева/справа) — 24px по паттерну
//      сайта: инсет даёт <main class="px-6"> (24px), обёртка страницы
//      НЕ добавляет собственной горизонтальной подложки (иначе отступ
//      задублировался бы до 48px), ширина ограничена max-w-[1600px]
//      с центрированием — тот же каркас, что у остальных вкладок.
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

  it("отступы бейджей 24px от краёв страницы: max-w-[1600px] + mx-auto, БЕЗ собственной гориз. подложки (инсет даёт main px-6)", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;

    expect(root?.className).toContain("max-w-[1600px]");
    expect(root?.className).toContain("mx-auto");
    // Дубль горизонтальной подложки на обёртке задвоил бы 24px до 48px —
    // запрещено контрактом правки (24px обеспечивает <main class="px-6">).
    expect(root?.className).not.toMatch(/\bpx-\d/);
  });

  it("контент остаётся над фоном: relative-обёртка содержимого после фона", () => {
    const { container } = render(<DocumentationPageShell>проверка</DocumentationPageShell>);
    const root = container.firstElementChild;
    const content = root?.children[1];

    expect(content?.className).toContain("relative");
    expect(content?.textContent).toContain("проверка");
  });
});
