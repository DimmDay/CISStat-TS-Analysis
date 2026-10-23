// packages/ui/components/DocumentationWorkspace.test.tsx
//
// Точечная UI-правка (полировка страницы «Документы», следом за
// DOCLOG-4-UI-FIX) — КОНТРАКТ БЕЙДЖЕЙ ПЕРЕСМОТРЕН постановкой тимлида:
//
//   1. Бейдж — это НЕ чип-заголовок, а ВСЯ область целиком: заголовок
//      «Виды документов» + поле с границей вокруг него и списка
//      документов. Соседние области («Версии», «Предпросмотр») — такие
//      же бейджи. => Заголовки всех трёх областей возвращены к ОБЫЧНОМУ
//      тексту (чип-обёртка SECTION_BADGE_FRAME устранена).
//   2. Рамка и фон БОЛЬШИХ бейджей — по эталону бейджа «Знакомство с
//      платформой» (RouteCard главной страницы): rounded-xl +
//      border-brand/60 + bg-brand-light/60. Прежние нейтральные рамка и
//      фон (border-neutral-200 bg-white + dark:-ревизии) устранены —
//      токены theme-adaptive, отдельные dark:-ревизии не требуются
//      (контракт DKT-1 «имена классов не меняются — меняются значения»).
//   3. Нижний инсет 24px (pb-6) у ВСЕХ трёх бейджей — даже при
//      динамическом содержимом (списки версий/предпросмотр условные):
//      класс стоит на самой области, а не на контенте.
//
// Шрифт заголовков НЕ меняется (уточнение тимлида: «это рамка и фон,
// а не шрифт») — текстовые классы h2 остаются прежними (text-sm
// font-semibold text-neutral-900 dark:text-neutral-100).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./DocumentationWorkspace";

// Клиенты документации глушим: workspace с runId=null не ходит в сеть
// (честное empty-состояние §12.3), сетевой слой вне объёма UI-правки.
jest.mock("../lib/documentation", () => ({
  listDocuments: jest.fn(),
  createDraft: jest.fn(),
  getRevision: jest.fn(),
  requestRendition: jest.fn(),
  getJob: jest.fn(),
  cancelJob: jest.fn(),
  renditionContentUrl: (id: string) => `/v1/documentation/renditions/${id}/content`,
  revisionPreviewUrl: (id: string) => `/v1/documentation/revisions/${id}/preview`,
}));

// Эталон «Знакомство с платформой» (RouteCard): рамка rgba(46,49,146,.6),
// фон rgba(232,234,246,.6), скругление 12px.
const REFERENCE_FRAME = ["rounded-xl", "border-brand/60", "bg-brand-light/60"] as const;

// Прежние нейтральные рамка/фон областей — устранены правкой.
const LEGACY_FRAME = [
  "border-neutral-200",
  "bg-white",
  "dark:border-neutral-800",
  "dark:bg-neutral-900",
] as const;

const PANEL_IDS = [
  ["doclog4-kind-list", "Виды документов"],
  ["doclog4-version-list", "Версии"],
  ["doclog4-preview-pane", "Предпросмотр"],
] as const;

describe("DocumentationWorkspace — большие бейджи-области (рамка/фон по эталону RouteCard)", () => {
  it.each(PANEL_IDS)(
    "бейдж-область «%s»: рамка+фон эталона (rounded-xl, border-brand/60, bg-brand-light/60)",
    (testId) => {
      render(<DocumentationWorkspace runId={null} />);
      const panel = screen.getByTestId(testId);
      for (const cls of REFERENCE_FRAME) {
        expect(panel.className).toContain(cls);
      }
    },
  );

  it.each(PANEL_IDS)(
    "бейдж-область «%s»: прежние нейтральные рамка/фон устранены (border-neutral-200/bg-white + dark:-ревизии)",
    (testId) => {
      render(<DocumentationWorkspace runId={null} />);
      const panel = screen.getByTestId(testId);
      for (const cls of LEGACY_FRAME) {
        expect(panel.className).not.toContain(cls);
      }
    },
  );

  it.each(PANEL_IDS)(
    "бейдж-область «%s»: нижний инсет 24px (pb-6) стоит на самой области — держится и при динамическом контенте",
    (testId) => {
      render(<DocumentationWorkspace runId={null} />);
      const panel = screen.getByTestId(testId);
      expect(panel.className).toContain("pb-6");
    },
  );
});

describe("DocumentationWorkspace — заголовки бейджей возвращены к обычному тексту", () => {
  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("заголовок «%s»: текст лежит прямо в h2, БЕЗ чип-обёртки (span с рамкой)", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const heading = screen.getByText(label);
    // Чип устранён: элемент с текстом — сам h2, а не span внутри него.
    expect(heading.tagName).toBe("H2");
    expect(heading.querySelector("span.badge, span[class*='border-brand']")).toBeNull();
  });

  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("заголовок «%s»: шрифт НЕ менялся — text-sm font-semibold остаются на заголовке h2", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const h2 = screen.getByText(label).closest("h2");
    expect(h2).not.toBeNull();
    expect(h2?.className).toContain("text-sm");
    expect(h2?.className).toContain("font-semibold");
    expect(h2?.className).toContain("text-neutral-900");
    expect(h2?.className).toContain("dark:text-neutral-100");
    // На самом заголовке нет классов рамки/фона (это обычный текст).
    expect(h2?.className).not.toContain("border-brand");
    expect(h2?.className).not.toContain("bg-brand-light");
  });

  it.each([
    ["Виды документов"],
    ["Версии"],
    ["Предпросмотр"],
  ])("заголовок «%s»: без иконок (правка рамки/фона не добавляет пиктограммы)", (label) => {
    render(<DocumentationWorkspace runId={null} />);
    const h2 = screen.getByText(label).closest("h2");
    expect(h2?.querySelector("svg")).toBeNull();
    expect(h2?.querySelector("img")).toBeNull();
  });

  it("заголовок «Версии» сохраняет динамику (вид документа при выборе) — возврат к обычному тексту её не подменяет", () => {
    render(<DocumentationWorkspace runId={null} />);
    // runId=null → активный вид не выбран → фолбэк-текст «Версии» (§12.2).
    expect(screen.getByText("Версии")).toBeInTheDocument();
  });
});
