// packages/ui/components/forecasting-help-eda-pattern.test.tsx
//
// Задача UI-FORECAST-HELP-1 (2026-10-15, постановка тимлида): вкладка
// «Прогнозирование» (/forecasting) -- три правки по паттерну вкладки EDA
// (TsAnalysisEDA.tsx, эталон):
//
//   1. Кнопка справки левой колонки: круглая «?» (h-6 w-6 rounded-full,
//      aria-label «Справка по этапу») заменена на ТЕКСТОВУЮ кнопку
//      «Справка» по паттерну EDA (:1414-1423): text-xs px-2 py-1 rounded
//      transition-colors, активное состояние bg-brand text-white /
//      неактивное bg-brand-light text-neutral-700 hover:..., toggle-
//      семантика (второй клик закрывает справку -- зеркально EDA-2,
//      «инвариант информативности»: возврат к описанию этапа «main»).
//      data-testid forecasting-help-btn СОХРАНЁН (пины двух существующих
//      сюитов -- TsAnalysisForecasting.test.tsx:183 и
//      forecasting-column-headers-unified.test.tsx:165/189; testid --
//      тестовый хук, не визуальный дизайн). aria-label снят: доступное
//      имя -- видимый текст «Справка» (паритет с EDA).
//   2. Окно «Описание этапа» (центральная колонка): размер шрифта текста
//      text-xs (12px) → text-sm (14px) по паттерну EDA (:1542 -- «text-sm
//      text-neutral-600»); остальная геометрия бокса (px-4 py-3, 220px,
//      цвета) не тронута.
//   3. Шеврон «сворачивания окна»: прежний ЕДИНЫЙ toggle-шеврон
//      (desc-toggle-btn, absolute bottom-1 внешней обёртки -- при
//      развёрнутом окне визуально «вверху», у нижней грани свёрнутого
//      следа) заменён на паттерн EDA (:1553-1577):
//        -- сворачивание: шеврон ВНУТРИ развёрнутого бокса, sticky
//           bottom-0 (обёртка sticky bottom-0 flex justify-center py-1
//           bg-brand-light rounded-b-lg; кнопка w-8 h-5 rounded-t
//           bg-brand/10 hover:bg-brand/20 text-brand + ChevronUp,
//           testid desc-collapse-btn) -- прилипает к НИЗУ окна;
//        -- разворачивание: шеврон absolute bottom-1 по центру ПОД
//           боксом, только при переполнении (hasOverflow: ref +
//           ResizeObserver, scrollHeight > clientHeight + 2 -- перенос
//           EDA :1311-1322; testid desc-expand-btn, ChevronDown).
//      ВНЕ СКОУПА (зафиксировано в worklog10.md): click-outside и
//      сворачивание при смене секции (EDA :1269-1284) -- не входят в
//      постановку.
//
// jsdom не считает layout: scrollHeight/clientHeight = 0 → hasOverflow
// false → expand-шеврон в jsdom не рендерится (тот же оракул, что у EDA
// «expand chevron is not visible when no content is loaded»); состояние
// переполнения тестируется управляемым моком ResizeObserver + defineProperty
// scrollHeight/clientHeight на боксе. Sticky-позиционирование пинится
// структурно (классы обёртки + принадлежность боксу).
//
// Оракулы на СВОИХ данных: свой стаб AppShellContext (stages
// upload/modeling=done, датасет fh-f-1) + fetch ok:false (окно описания
// рендерится до фазовых гейтов, заголовки/кнопка структурные). Корпус
// дизъюнктен существующим сюитам (маркер -- префикс fh-1).

import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisForecasting } from "./TsAnalysisForecasting";

// Polyfill ResizeObserver с управляемым колбэком: Recharts требует сам
// полифилл, а механика hasOverflow (EDA :1311-1322) -- ручной запуск
// checkOverflow после подмены scrollHeight/clientHeight.
let fhLastResize: (() => void) | null = null;
global.ResizeObserver = class {
  constructor(cb: ResizeObserverCallback) {
    fhLastResize = () => cb([], {} as ResizeObserver);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

// ── СВОЙ корпус (stages готовы, fetch падает -- окно описания структурное) ──

let fhStages: Record<string, string> = { upload: "done", modeling: "done" };

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: { datasetId: "fh-f-1", name: "fh-help.csv", rows: 48, sizeLabel: "2 КБ" },
    stages: fhStages,
    lastActiveStage: null,
    targetColumn: null,
    sessionLoading: false,
    refreshSession: jest.fn(),
  }),
}));

function renderFhForecast() {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: false, json: () => Promise.resolve(null) })
  ) as unknown as typeof fetch;
  return render(<TsAnalysisForecasting />);
}

function fireResize() {
  act(() => {
    fhLastResize?.();
  });
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Кнопка «Справка» «Прогнозирования» -- паттерн EDA (UI-FORECAST-HELP-1)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    delete (global as { fetch?: unknown }).fetch;
  });

  it("круглая «?» заменена текстовой кнопкой «Справка» с классами EDA; toggle: клик открывает справку, второй клик возвращает к описанию этапа", async () => {
    renderFhForecast();

    // Кнопка доступна по видимому тексту «Справка» (паритет с EDA:
    // getByRole button name, БЕЗ aria-label), testid сохранён.
    const helpButton = screen.getByRole("button", { name: "Справка" });
    expect(screen.getByTestId("forecasting-help-btn")).toBe(helpButton);

    // Классы паттерна EDA (+shrink-0 строки заголовка серии UI-*-HDR);
    // круглый дизайн «?» снят.
    expect(helpButton).toHaveClass("shrink-0", "text-xs", "px-2", "py-1", "rounded", "transition-colors");
    expect(helpButton).not.toHaveClass("rounded-full");
    expect(helpButton).not.toHaveClass("h-6");
    expect(helpButton).not.toHaveClass("w-6");
    expect(helpButton.textContent).toBe("Справка");

    // Неактивное состояние (справка закрыта) -- паттерн EDA.
    expect(helpButton).toHaveClass("bg-brand-light", "text-neutral-700");
    expect(helpButton.className).toContain("hover:bg-brand-light/80");

    // Кнопка в строке заголовка левой колонки [иконка, h2, кнопка]
    // (контракт UI-*-HDR сохранён).
    expect(helpButton.parentElement!.className).toContain("flex items-center gap-2");

    // Первый клик -- режим справки: заголовок окна «Справка», контент
    // module_help, кнопка в активном состоянии EDA.
    fireEvent.click(helpButton);
    await screen.findByRole("heading", { name: "Справка", level: 3 });
    expect(screen.getByText(/Справка этапа «Прогнозирование»/)).toBeInTheDocument();
    expect(helpButton).toHaveClass("bg-brand", "text-white");

    // Второй клик -- toggle (зеркально EDA-2): возврат к описанию этапа,
    // неактивное состояние.
    fireEvent.click(helpButton);
    await screen.findByRole("heading", { name: "Описание этапа", level: 3 });
    expect(screen.getByText(/Цель: построить реальный прогноз/)).toBeInTheDocument();
    expect(helpButton).toHaveClass("bg-brand-light", "text-neutral-700");
    expect(helpButton).not.toHaveClass("bg-brand");
  });
});

describe("Окно «Описание этапа» -- шрифт по паттерну EDA (UI-FORECAST-HELP-1)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    delete (global as { fetch?: unknown }).fetch;
  });

  it("текст окна -- text-sm text-neutral-600 (был text-xs), геометрия бокса сохранена", () => {
    renderFhForecast();

    // Бокс -- элемент, содержащий текст stage_overview (рендерится
    // напрямую строкой в div бокса).
    const box = screen.getByText(/Цель: построить реальный прогноз/);
    expect(box.className).toContain("whitespace-pre-wrap"); // тот самый бокс
    expect(box).toHaveClass("text-sm", "text-neutral-600");
    expect(box.className).not.toContain("text-xs");
    // Геометрия/оформление бокса не тронуты правкой шрифта.
    expect(box).toHaveClass("rounded-lg", "px-4", "py-3");
  });
});

describe("Шевроны окна описания -- размещение по паттерну EDA (UI-FORECAST-HELP-1)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    delete (global as { fetch?: unknown }).fetch;
    fhLastResize = null;
  });

  it("свёрнуто: collapse-шеврона нет; без переполнения expand-шеврона нет (jsdom, оракул EDA)", () => {
    renderFhForecast();

    // Свёрнутое окно -- шеврона сворачивания нет нигде.
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();
    // jsdom: scrollHeight=0 → hasOverflow=false → expand-шеврон скрыт
    // (тот же структурный оракул, что у EDA).
    expect(screen.queryByTestId("desc-expand-btn")).toBeNull();
  });

  it("переполнение: expand-шеврон под боксом (absolute bottom); развёрнуто: collapse-шеврон ВНУТРИ бокса, sticky bottom-0 -- у НИЗА окна", () => {
    renderFhForecast();
    const box = screen.getByText(/Цель: построить реальный прогноз/);
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();
    expect(screen.queryByTestId("desc-expand-btn")).toBeNull();

    // Мок переполнения (jsdom не считает layout) + ручной запуск
    // checkOverflow через управляемый ResizeObserver.
    Object.defineProperty(box, "scrollHeight", { configurable: true, get: () => 600 });
    Object.defineProperty(box, "clientHeight", { configurable: true, get: () => 220 });
    fireResize();

    // Появился expand-шеврон: absolute bottom-1 по центру, под боксом
    // (вне бокса), ChevronDown, aria-label «Развернуть описание».
    const expandBtn = screen.getByTestId("desc-expand-btn");
    expect(expandBtn).toHaveAttribute("aria-label", "Развернуть описание");
    expect(expandBtn.className).toContain("absolute");
    expect(expandBtn.className).toContain("bottom-1");
    expect(expandBtn.className).toContain("left-1/2");
    expect(expandBtn.className).toContain("rounded-t");
    expect(expandBtn.querySelector("svg")).toBeTruthy();
    expect(box.contains(expandBtn)).toBe(false);

    // Разворачивание окна.
    fireEvent.click(expandBtn);

    // Collapse-шеврон -- ВНУТРИ развёрнутого бокса (не absolute-кнопка
    // внешней обёртки): обёртка sticky bottom-0 -- прилипание к НИЗУ
    // окна (паттерн EDA), кнопка rounded-t + ChevronUp.
    const collapseBtn = screen.getByTestId("desc-collapse-btn");
    expect(box.contains(collapseBtn)).toBe(true);
    expect(collapseBtn).toHaveAttribute("aria-label", "Свернуть описание");
    expect(collapseBtn.className).toContain("rounded-t");
    expect(collapseBtn.className).toContain("bg-brand/10");
    expect(collapseBtn.querySelector("svg")).toBeTruthy();

    const stickyWrapper = collapseBtn.parentElement as HTMLElement;
    expect(stickyWrapper.className).toContain("sticky");
    expect(stickyWrapper.className).toContain("bottom-0");
    expect(stickyWrapper.className).toContain("justify-center");
    expect(stickyWrapper.className).toContain("bg-brand-light");

    // Развёрнутый бокс -- scroll-контейнер (overflow-y-auto), sticky
    // внутри него работает.
    expect(box.className).toContain("overflow-y-auto");

    // Сворачивание -- возврат в свёрнутое состояние: collapse-шеврона
    // нет, expand-шеврон возвращён (переполнение по-прежнему истинно).
    fireEvent.click(collapseBtn);
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();
    expect(screen.getByTestId("desc-expand-btn")).toHaveAttribute("aria-label", "Развернуть описание");
  });
});
