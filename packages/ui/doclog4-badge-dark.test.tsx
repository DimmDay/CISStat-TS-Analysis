// packages/ui/doclog4-badge-dark.test.tsx
//
// DOCLOG-4-UI-FIX-3 — полировка страницы «Документы», пункт 2: ВЕСЬ текст
// всех трёх бейджей (Виды документов / Версии / Предпросмотр) в тёмной
// теме — белый.
//
// Контракт (§6.2, прецедент .dark .home-footer / .dark .text-brand):
//  - классы компонентов НЕ меняются на dark:text-* (перечислять утилиты
//    внутри динамического контента — хрупко: список версий, статусы,
//    предпросмотр рендерятся условно) — ревизия выполняется scoped-
//    универсальным правилом по МАРКЕРНОМУ классу .doclog4-badge на трёх
//    областях: .dark .doclog4-badge, .dark .doclog4-badge *;
//  - значение — токен --c-white-fg (#FFFFFF в ОБЕИХ темах — «текст на
//    цветных заливках», DKT-2R). Токен --c-white НЕ подходит: в тёмной
//    ревизии он инвертируется в поверхность #16171C;
//  - правило размещено ПОСЛЕ @tailwind utilities — перебивает
//    utility-классы при равной специфичности (.dark .doclog4-badge * =
//    0,2,0 против .dark .dark\:text-* 0,2,0 — решает порядок источника);
//  - светлая тема — байт-инвариант (правило только под .dark).
//
// Гварды: (1) правило присутствует в globals.css и ссылается на
// --c-white-fg; (2) правило стоит после @tailwind utilities (каскад);
// (3) все три бейджа несут маркер doclog4-badge; (4) маркер стоит на
// области-контейнере (data-testid), а не на заголовке.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./components/DocumentationWorkspace";

const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");

const PANEL_IDS = [
  "doclog4-kind-list",
  "doclog4-version-list",
  "doclog4-preview-pane",
] as const;

describe("DOCLOG-4-UI-FIX-3: текст бейджей «Документы» в тёмной теме — белый", () => {
  it("utility-ревизия присутствует: .dark .doclog4-badge (и потомки) → --c-white-fg", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.doclog4-badge,\s*\.dark \.doclog4-badge \*\s*\{\s*color:\s*rgb\(var\(--c-white-fg\)\);/,
    );
  });

  it("правило стоит ПОСЛЕ @tailwind utilities (перебивает utility-классы при равной специфичности)", () => {
    const utilitiesAt = GLOBALS.indexOf("@tailwind utilities");
    const ruleAt = GLOBALS.search(/\.dark \.doclog4-badge,/);
    expect(utilitiesAt).toBeGreaterThanOrEqual(0);
    expect(ruleAt).toBeGreaterThan(utilitiesAt);
  });

  it("значение — --c-white-fg (белый в обеих темах), НЕ --c-white (в тёмной инвертируется в поверхность)", () => {
    const rule = GLOBALS.match(
      /\.dark \.doclog4-badge,\s*\.dark \.doclog4-badge \*\s*\{[\s\S]*?\}/,
    )![0];
    expect(rule).toContain("--c-white-fg");
    expect(rule).not.toMatch(/var\(--c-white\)/);
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
