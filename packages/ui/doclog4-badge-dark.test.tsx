// packages/ui/doclog4-badge-dark.test.tsx
//
// DOCLOG-4-UI-FIX-3 + DOCLOG-4-UI-FIX-4 — полировка страницы «Документы»:
// ВЕСЬ текст всех трёх бейджей (Виды документов / Версии / Предпросмотр)
// в тёмной теме — белый, ВКЛЮЧАЯ заголовки (h2) — п.2 постановки FIX-4.
//
// Контракт (§6.2, прецедент .dark .home-footer / .dark .text-brand):
//  - классы компонентов НЕ меняются на dark:text-* (перечислять утилиты
//    внутри динамического контента — хрупко: список версий, статусы,
//    предпросмотр рендерятся условно) — ревизия выполняется scoped-
//    универсальным правилом по МАРКЕРНОМУ классу .doclog4-badge;
//  - FIX-4, ключевое: специфичность правила потомков ПОДНЯТА до (0,3,0)
//    удвоением маркерного класса (.doclog4-badge.doclog4-badge).
//    Причина — замер реальной сборки standalone (.next/static/css):
//    все Tailwind-утилиты генерируются на @tailwind-директивах
//    app/globals.css и оказываются в чанке ПОСЛЕ правил, инлайненных
//    из @import packages/ui/globals.css; при равной специфичности (0,2,0)
//    каскад решает порядком источника → утилита dark:text-neutral-100
//    (тёмная ревизия «поверхностного» токена = #24252C!) побеждала
//    правило FIX-3, и заголовки бейджей оставались тёмными по тёмному.
//    (0,3,0) > (0,2,0) — правило побеждает ЛЮБУЮ dark:-утилиту классов
//    НЕЗАВИСИМО от порядка источника (и порядка чанков CSS);
//  - значение — токен --c-white-fg (#FFFFFF в ОБЕИХ темах — «текст на
//    цветных заливках», DKT-2R). Токен --c-white НЕ подходит: в тёмной
//    ревизии он инвертируется в поверхность #16171C;
//  - светлая тема — байт-инвариант (правила только под .dark).
//
// Гварды FIX-4 (пп. 2 и 3 постановки):
//  - правило потомков — удвоенный класс (0,3,0), строго выше (0,2,0)
//    dark:-утилит (специфичности вычисляются в тесте);
//  - h2 всех трёх бейджей — потомки маркерных областей, компонентные
//    классы заголовков не тронуты (белыми их делает ПРАВИЛО);
//  - п.3: hover-подсветка строк списка видов документов ТЕМНЕЕТ бейдж:
//    dark:hover:bg-neutral-800 (тёмная ревизия neutral-800 = #E3E5EA —
//    почти белая поверхность под белым текстом!) заменён на
//    dark:hover:bg-black/30; токен --c-black в .dark НЕ инвертируется
//    (0 0 0) — оверлей реально затемняет (роль black §6.2, прецедент
//    bg-black/20 EventsLogDrawer);
//  - следствие «весь текст белый»: внутри бейджа не остаётся СВЕТЛЫХ
//    поверхностей тёмной темы — dark:bg-neutral-800 (#E3E5EA) у кнопок
//    «Собрать формат» заменён на dark:bg-white/10 со scoped-ревизией
//    .dark .doclog4-badge .dark\:bg-white\/10 → rgb(255 255 255 / 0.07)
//    (прецедент .dark .home-footer .bg-white\/40: светлая поверхность
//    в тёмной теме → полупрозрачная белая плёнка).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./components/DocumentationWorkspace";

const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");
const WORKSPACE = readFileSync(
  resolve(__dirname, "components", "DocumentationWorkspace.tsx"),
  "utf8",
);

const PANEL_IDS = [
  "doclog4-kind-list",
  "doclog4-version-list",
  "doclog4-preview-pane",
] as const;

// Мини-вычислитель «классовой» составляющей специфичности CSS-селектора:
// каждый .class (включая экранированные .dark\:text-*) и каждый
// НЕэкранированный псевдокласс (:hover/:focus-visible) дают +1 в столбце b
// тройки (a,b,c). Достаточно для сравнения правил одного формата.
function classSpecificity(selector: string): number {
  const classes = (selector.match(/\./g) ?? []).length;
  const pseudoClasses = (selector.match(/(?<![\\:]):(hover|focus-visible)/g) ?? []).length;
  return classes + pseudoClasses;
}

describe("DOCLOG-4-UI-FIX-3/4: текст бейджей «Документы» в тёмной теме — белый", () => {
  it("utility-ревизия присутствует: .dark .doclog4-badge.doclog4-badge (и потомки) → --c-white-fg", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.doclog4-badge\.doclog4-badge,\s*\.dark \.doclog4-badge\.doclog4-badge \*\s*\{\s*color:\s*rgb\(var\(--c-white-fg\)\);/,
    );
  });

  it("правило стоит ПОСЛЕ @tailwind utilities (каскадный бэкстоп поверх специфичности)", () => {
    const utilitiesAt = GLOBALS.indexOf("@tailwind utilities");
    const ruleAt = GLOBALS.search(/\.dark \.doclog4-badge\.doclog4-badge,/);
    expect(utilitiesAt).toBeGreaterThanOrEqual(0);
    expect(ruleAt).toBeGreaterThan(utilitiesAt);
  });

  it("значение — --c-white-fg (белый в обеих темах), НЕ --c-white (в тёмной инвертируется в поверхность)", () => {
    const rule = GLOBALS.match(
      /\.dark \.doclog4-badge\.doclog4-badge,\s*\.dark \.doclog4-badge\.doclog4-badge \*\s*\{[\s\S]*?\}/,
    )![0];
    expect(rule).toContain("--c-white-fg");
    expect(rule).not.toMatch(/var\(--c-white\)/);
  });

  it("специфичность правила потомков (0,3,0) строго выше (0,2,0) dark:-утилит — побеждает независимо от порядка источника", () => {
    // Причина FIX-4: в собранном чанке standalone утилиты физически идут
    // ПОСЛЕ правил пакета (замер .next/static/css: .dark .doclog4-badge на
    // 44020, dark:text-neutral-100 на 54097) — при равной специфичности
    // побеждали утилиты. Удвоенный класс снимает зависимость от порядка.
    const ruleSpec = classSpecificity(".dark .doclog4-badge.doclog4-badge *");
    const darkTextUtilitySpec = classSpecificity(".dark .dark\\:text-neutral-100");
    expect(ruleSpec).toBe(3); // .dark + .doclog4-badge ×2
    expect(darkTextUtilitySpec).toBe(2); // .dark + .dark\:text-neutral-100
    expect(ruleSpec).toBeGreaterThan(darkTextUtilitySpec);
  });

  it.each(PANEL_IDS)(
    "маркер doclog4-badge стоит на бейдже-области %s (контейнер, не заголовок)",
    (testId) => {
      render(<DocumentationWorkspace runId={null} />);
      const panel = screen.getByTestId(testId);
      expect(panel.className).toContain("doclog4-badge");
      // Маркер на самой области: заголовок h2 — потомок, не носитель маркера.
      const h2 = panel.querySelector("h2");
      expect(h2?.className).not.toContain("doclog4-badge");
    },
  );
});

describe("DOCLOG-4-UI-FIX-4 п.2: заголовки (h2) всех бейджей в тёмной теме — белые", () => {
  it.each(PANEL_IDS)(
    "h2 бейджа %s — потомок маркерной области, накрывается правилом (0,3,0)",
    (testId) => {
      render(<DocumentationWorkspace runId={null} />);
      const panel = screen.getByTestId(testId);
      const h2 = panel.querySelector("h2");
      expect(h2).toBeInTheDocument();
      // Паттерн заголовков не тронут (контракт «ноль правок ради темы»):
      // их dark:text-neutral-100 (0,2,0) теперь ГАРАНТИРОВАННО перебивается
      // правилом (0,3,0) при любом порядке источника.
      expect(h2?.className).toContain("text-sm");
      expect(h2?.className).toContain("font-semibold");
    },
  );

  it("компонентные классы заголовков не правились: dark:text-neutral-100 остаётся на всех трёх h2 (белыми их делает правило)", () => {
    // Считаем только вхождения в className-строках (не в комментариях):
    // по одному на h2 каждого из трёх бейджей.
    const inClassNames = WORKSPACE.match(/className="[^"]*dark:text-neutral-100/g) ?? [];
    expect(inClassNames.length).toBe(3);
  });
});

describe("DOCLOG-4-UI-FIX-4 п.3: hover-подсветка списка видов документов темнеет", () => {
  it("кнопки видов документов: dark:hover:bg-black/30, прежнего dark:hover:bg-neutral-800 нет", () => {
    render(<DocumentationWorkspace runId={null} />);
    const kindButton = screen.getByTestId("doclog4-kind-D01");
    expect(kindButton.className).toContain("dark:hover:bg-black/30");
    expect(kindButton.className).not.toContain("dark:hover:bg-neutral-800");
  });

  it("--c-black в .dark НЕ инвертируется (0 0 0) — оверлей bg-black/30 затемняет бейдж", () => {
    const darkBlock = GLOBALS.match(/\.dark \{[\s\S]*?\n\}/)![0];
    expect(darkBlock).toMatch(/--c-black:\s*0 0 0/);
  });

  it("следствие «весь текст белый»: светлых поверхностей dark:bg-neutral-800 внутри бейджа больше нет", () => {
    // Тёмная ревизия neutral-800 = #E3E5EA (почти белая): белый текст на
    // такой поверхности нечитаем. Кнопки «Собрать формат» переведены на
    // dark:bg-white/10 (плёнка).
    expect(WORKSPACE).not.toContain("dark:bg-neutral-800");
    expect(WORKSPACE).toContain("dark:bg-white/10");
  });

  it("scoped-ревизия плёнки: .dark .doclog4-badge .dark\\:bg-white\\/10 → rgb(255 255 255 / 0.07) (прецедент .home-footer .bg-white\\/40)", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.doclog4-badge \.dark\\:bg-white\\\/10\s*\{\s*background-color:\s*rgb\(255 255 255 \/ 0\.07\);/,
    );
  });
});
