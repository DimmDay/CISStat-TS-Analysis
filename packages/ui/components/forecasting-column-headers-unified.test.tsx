// packages/ui/components/forecasting-column-headers-unified.test.tsx
//
// Задача UI-FORECAST-HDR-1 (2026-10-15, постановка тимлида): привести к
// единому виду по паттерну задачи UI-PREPR-HDR-1 вкладки «Предобработка»
// (которая, в свою очередь, переносит UI-VALIDATION-HDR-1 «Валидации» →
// UI-UPLOAD-HDR-1 «Загрузки»; прямые предшественники -- UI-EDA-HDR-1/2 и
// UI-MODELING-HDR-1) заголовки колонок 3-колоночного layout вкладки
// «Прогнозирование»: шрифты, выравнивание, иконки. Плюс отдельный пункт
// постановки: заголовок левой колонки «Прогнозирование» заменён на
// «Forecasting» (прецедент UI-EDA-HDR-2: «Разведочный EDA» → «Exploration»;
// модульное имя «Прогнозирование» на других поверхностях -- навигация
// ModuleNav/stages.ts, справка knowledge/*, TasksHub, TaskCard,
// бэкенд-реестр -- НЕ менялось, вне скоупа постановки).
//
// Отличия лейаута от семейства (УЧТЕНЫ в контракте):
//   -- левая колонка: кнопка справки в строке заголовка (testid
//      forecasting-help-btn, shrink-0); при UI-FORECAST-HDR-1 была
//      круглой «?» (дизайн сохранялся до отдельной постановки), затем
//      UI-FORECAST-HELP-1 заменил её текстовой кнопкой «Справка» по
//      паттерну EDA -- контракт строки [иконка, h2, кнопка shrink-0]
//      не менялся;
//   -- центральная колонка: заголовок «Описание этапа» переключается на
//      «Справка» (режим help) с кнопкой возврата «К описанию этапа» В ТОЙ
//      ЖЕ строке -- контракт [иконка, h3 flex-1, кнопка shrink-0] в обоих
//      режимах;
//   -- правая колонка: заголовок «Панель управления» был h4 text-sm
//      ВНУТРИ первой карточки control-panel -- поднят на уровень колонки
//      (строка-паттерн -- первая ветка aside, mb-4), текст сохранён.
//
// Контракт паттерна (эталон -- eda-column-headers-unified.test.tsx /
// modeling-column-headers-unified.test.tsx):
//   (a) типографика: text-lg (18px) + font-semibold + text-neutral-800
//       («Прогнозирование» был font-bold text-neutral-900, «Описание
//       этапа» -- text-sm, «Панель управления» -- h4 text-sm);
//   (b) строка-паттерн: flex items-center gap-2;
//   (c) иконка паттерна: lucide svg size 16, text-brand, aria-hidden;
//   (d) состав строки: [иконка, заголовок] у «Описания этапа»/«Панели
//       управления»; у левой колонки -- [иконка, h2, кнопка справки] с
//       shrink-0 у кнопки;
//   (e) выравнивание по нижней горизонтали: строка заголовка -- первая
//       ветка своей колонки (спуск по firstElementChild), вертикальные
//       офсеты pt-1 ОБОИХ aside убраны.
//
// jsdom не считает layout -- инвариант «низы на одной горизонтали» пинится
// структурой: строка -- первая ветка колонки + одинаковый line box всех
// заголовков (text-lg 28px > иконки 16px, items-center). Тот же подход,
// что в эталонных тестах серии.
//
// Оракулы на СВОИХ данных: свой стаб AppShellContext (stages
// upload/modeling=done, датасет есть) + fetch ok:false (карты/прогнозы не
// грузятся -- заголовки структурные, рендер от данных не зависит,
// подтверждено существующими тестами модуля). Корпус дизъюнктен
// существующим сюитам (маркер -- префикс имен describe/хелперов
// hdr-forecast-1).

import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisForecasting } from "./TsAnalysisForecasting";

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что в TsAnalysisForecasting.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус (stages готовы, fetch падает -- заголовки структурные) ──

let hdrForecastStages: Record<string, string> = {};
let hdrForecastHasDataset = true;

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: hdrForecastHasDataset
      ? { datasetId: "hdr-f-1", name: "hdr-forecast.csv", rows: 64, sizeLabel: "2 КБ" }
      : null,
    stages: hdrForecastStages,
    lastActiveStage: null,
    targetColumn: null,
    sessionLoading: false,
    refreshSession: jest.fn(),
  }),
}));

function renderHdrForecast() {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: false, json: () => Promise.resolve(null) })
  ) as unknown as typeof fetch;
  return render(<TsAnalysisForecasting />);
}

// ── Контракт единого вида заголовка (эталон UI-PREPR-HDR-1) ──────────

function expectUnifiedHeaderContract(header: HTMLElement, opts: { withTrailingButton?: boolean } = {}) {
  // (a) Единая типографика -- text-lg + font-semibold + neutral-800.
  expect(header.className).toContain("text-lg");
  expect(header.className).toContain("font-semibold");
  expect(header.className).toContain("text-neutral-800");

  // (b) Строка-паттерн AppliedTasksNavigator: flex items-center gap-2.
  const row = header.parentElement;
  expect(row).toBeTruthy();
  expect(row!.className).toContain("flex");
  expect(row!.className).toContain("items-center");
  expect(row!.className).toContain("gap-2");

  // (c) Иконка паттерна: aria-hidden svg с фирменным индиго (text-brand).
  const icon = row!.querySelector("svg");
  expect(icon).toBeTruthy();
  expect(icon).toHaveAttribute("aria-hidden", "true");
  expect(icon!.getAttribute("class")).toContain("text-brand");

  // (d) Состав строки: [иконка, заголовок]; с хвостовым элементом --
  //     [иконка, заголовок, кнопка] со shrink-0 у кнопки (левая колонка:
  //     круглая «?»; центральная: «К описанию этапа» в режиме «Справка»).
  if (opts.withTrailingButton) {
    expect(row!.children).toHaveLength(3);
    const trailing = row!.children[2] as HTMLElement;
    expect(trailing.tagName).toBe("BUTTON");
    expect(trailing.className).toContain("shrink-0");
  } else {
    expect(row!.children).toHaveLength(2);
  }
}

// Инвариант «низ заголовков на одной горизонтали» в структурной форме:
// спуск по firstElementChild от корня колонки приводит ровно в строку
// заголовка (строка -- первая ветка колонки).
function expectHeaderRowAtColumnTop(header: HTMLElement) {
  const container = header.closest("aside, main");
  expect(container).toBeTruthy();
  const row = header.parentElement!;
  let node: Element = container!;
  while (node !== row) {
    const next = node.firstElementChild;
    expect(next).toBeTruthy();
    node = next!;
  }
  expect(node).toBe(row);
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Заголовки «Прогнозирования» -- единый вид (паттерн UI-PREPR-HDR-1 «Предобработки»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    delete (global as { fetch?: unknown }).fetch;
  });

  it("заголовки трёх колонок («Forecasting», «Описание этапа», «Панель управления») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    renderHdrForecast();

    // Левая колонка: «Прогнозирование» заменено на «Forecasting»
    // (пункт постановки, прецедент UI-EDA-HDR-2).
    const hForecast = await screen.findByRole("heading", { name: "Forecasting", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание этапа", level: 3 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });

    // Левая колонка: [иконка, h2, кнопка справки shrink-0]; защита
    // узкой колонки и растяжение -- truncate min-w-0 flex-1 (паттерн
    // левых колонок серии).
    expectUnifiedHeaderContract(hForecast, { withTrailingButton: true });
    expect(hForecast.className).toContain("truncate");
    expect(hForecast.className).toContain("flex-1");
    expect(screen.getByTestId("forecasting-help-btn")).toBeInTheDocument();
    expectHeaderRowAtColumnTop(hForecast);

    for (const h of [hDesc, hPanel]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // Бывший h4 «Панель управления» поднят из карточки control-panel на
    // уровень колонки: карточка без внутреннего дубликата заголовка.
    const rightAside = hPanel.closest("aside")!;
    expect(within(rightAside).getAllByRole("heading", { name: "Панель управления" })).toHaveLength(1);
  });

  it("заголовок центральной колонки следует за режимом справки: «Описание этапа» ↔ «Справка» с кнопкой возврата -- тот же контракт строки", async () => {
    renderHdrForecast();

    const hDesc = await screen.findByRole("heading", { name: "Описание этапа", level: 3 });
    expectUnifiedHeaderContract(hDesc);
    expectHeaderRowAtColumnTop(hDesc);

    // Кнопка справки включает режим «Справка»: заголовок
    // меняется на «Справка», в строке появляется возврат «К описанию
    // этапа» (shrink-0); контракт строки сохраняется в обоих режимах.
    fireEvent.click(screen.getByTestId("forecasting-help-btn"));
    const hHelp = await screen.findByRole("heading", { name: "Справка", level: 3 });
    expectUnifiedHeaderContract(hHelp, { withTrailingButton: true });
    expectHeaderRowAtColumnTop(hHelp);

    // Возврат: заголовок снова «Описание этапа», без хвостовой кнопки.
    fireEvent.click(screen.getByRole("button", { name: "К описанию этапа" }));
    const hDescBack = await screen.findByRole("heading", { name: "Описание этапа", level: 3 });
    expectUnifiedHeaderContract(hDescBack);
    expectHeaderRowAtColumnTop(hDescBack);
  });

  it("выравнивание по нижней горизонтали: офсеты pt-1 ОБОИХ колонок убраны, подпись левой колонки сохранена", async () => {
    renderHdrForecast();

    const hForecast = await screen.findByRole("heading", { name: "Forecasting", level: 2 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });
    const leftAside = hForecast.closest("aside")!;
    const rightAside = hPanel.closest("aside")!;

    // pt-1 сдвигал обе колонки на 4px вниз -- низы заголовков уходили с
    // общей горизонтали; контракт: вертикальных офсетов у колонок нет.
    expect(leftAside.className).not.toContain("pt-");
    expect(rightAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(
      within(leftAside).getByText("Шестой этап: реальный прогноз по зафиксированной Model Card")
    ).toBeInTheDocument();
  });
});
