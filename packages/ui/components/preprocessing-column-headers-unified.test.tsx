// packages/ui/components/preprocessing-column-headers-unified.test.tsx
//
// Задача UI-PREPR-HDR-1 (2026-10-14, постановка тимлида): привести к
// единому виду по паттерну задачи UI-VALIDATION-HDR-1 вкладки «Валидация»
// (которая, в свою очередь, переносит UI-UPLOAD-HDR-1 «Загрузки»):
//   (1) заголовки колонок 3-колоночного layout вкладки «Предобработка»
//       («Preprocessing», «Описание», «Панель управления»);
//   (2) заголовки окон «Обзор» и «Мастер исправления…» центральной колонки
//       (скоуп-решение: задача-паттерн UI-VALIDATION-HDR-1 включает окна,
//       её результат прямо называет «Предобработку» «следующим кандидатом
//       на ту же правку»; см. worklog10.md).
//
// Контракт паттерна (эталон -- validation-column-headers-unified.test.tsx):
//   (a) типографика: text-lg (18px) + font-semibold + text-neutral-800
//       («Preprocessing»/«Панель управления» уже были text-lg; «Описание» и
//       «Обзор»/«Мастер…» рендерились дефолтным text-base -- рассинхрон 2px);
//   (b) строка-паттерн: flex items-center gap-2;
//   (c) иконка паттерна: lucide svg size 16, text-brand, aria-hidden;
//   (d) состав строки: [иконка, заголовок] у «Описания»/«Обзора»/«Мастера»/
//       «Панели управления»; у «Preprocessing» -- [иконка, h2, кнопка
//       «Справка»] с shrink-0 у кнопки (паттерн левых колонок «Загрузки» и
//       «Валидации»; раньше строка была justify-between без иконки);
//   (e) выравнивание по нижней горизонтали: строка заголовка -- первая
//       ветка своей колонки (спуск по firstElementChild), вертикальные
//       офсеты pt-1 ОБОИХ aside убраны;
//   (f) иконки окон семантичны режиму: «Обзор: …» -- Eye (как в
//       «Загрузке»/«Валидации»), «Мастер исправления…» -- Wrench; обе
//       text-brand aria-hidden.
//
// jsdom не считает layout -- инвариант «низы на одной горизонтали» пинится
// структурой: строка -- первая ветка колонки + одинаковый line box всех
// заголовков (text-lg 28px > иконки 16px, items-center). Тот же подход,
// что в эталонных тестах «Загрузки» и «Валидации».
//
// Оракулы на СВОИХ данных: свой мок /session/current (маркер сессии
// hdr-prepr-1, has_active_dataset: false -- все заголовки рендерятся и без
// активного датасета; поведение подтверждено существующими тестами
// TsAnalysisPreprocessing.test.tsx, которые рендерят модуль вовсе без мока
// fetch). Корпус дизъюнктен существующим сюитам.

import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что в TsAnalysisPreprocessing.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус (маркер сессии hdr-prepr-1, без активного датасета) ───

function mockHdrPreprocessingFetch() {
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: false,
            dataset: null,
            stages: {},
            last_active_stage: null,
            session_marker: "hdr-prepr-1",
            updated_at: null,
          }),
      });
    }
    // Все прочие эндпоинты (self-fetch Обзор-панелей, профильные запросы)
    // не нужны: заголовки структурные, рендерятся без данных -- оседают в
    // error-состоянии соответствующих панелей (R6 оценки рисков).
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

function renderHdrPreprocessing() {
  mockHdrPreprocessingFetch();
  return render(
    <AppShellProvider>
      <TsAnalysisPreprocessing />
    </AppShellProvider>
  );
}

// ── Контракт единого вида заголовка (эталон UI-VALIDATION-HDR-1) ──────

function expectUnifiedHeaderContract(header: HTMLElement, opts: { withHelpButton?: boolean; withManualButton?: boolean } = {}) {
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

  // (d) Состав строки: [иконка, заголовок]; у «Preprocessing» --
  //     [иконка, h2, кнопка «Справка» (shrink-0)] -- паттерн «Загрузки»/
  //     «Валидации»; у окна «Мастер исправления пропусков» --
  //     [иконка, h3 (flex-1), кнопка «Исправить вручную» (shrink-0)]
  //     (MANUAL-MISSING-1: VERSIONED-ПРАВКА ПИНА -- раньше строка окна
  //     пинилась как ровно [иконка, заголовок]; кнопка ручного режима
  //     в заголовке мастера -- осознанное расширение контракта по
  //     паттерну левых колонок, обоснование в worklog10.md).
  if (opts.withHelpButton) {
    expect(row!.children).toHaveLength(3);
    const helpButton = row!.children[2] as HTMLElement;
    expect(helpButton.tagName).toBe("BUTTON");
    expect(helpButton.textContent).toBe("Справка");
    expect(helpButton.className).toContain("shrink-0");
  } else if (opts.withManualButton) {
    expect(row!.children).toHaveLength(3);
    const manualButton = row!.children[2] as HTMLElement;
    expect(manualButton.tagName).toBe("BUTTON");
    expect(manualButton.textContent).toBe("Исправить вручную");
    expect(manualButton.className).toContain("shrink-0");
    // правый край: h3 растянут, кнопка не сжимается
    expect(header.className).toContain("flex-1");
  } else {
    expect(row!.children).toHaveLength(2);
  }
}

// Инвариант «низ заголовков на одной горизонтали» в структурной форме:
// спуск по firstElementChild от корня колонки приводит ровно в строку
// заголовка (строка -- первая ветка колонки). Применим к ЗАГОЛОВКАМ
// КОЛОНОК («Preprocessing», «Описание», «Панель управления»); окно
// «Обзор»/«Мастер…» -- второй блок центральной колонки, ему -- своя
// форма ниже (как в эталонах «Загрузки»/«Валидации»).
function expectHeaderRowAtColumnTop(header: HTMLElement) {
  const container = header.closest("aside, section");
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

// Инвариант для заголовка ОКНА («Обзор»/«Мастер…»): строка заголовка
// открывает своё окно -- она первая ветка блока окна (внутри окна над
// ней ничего не рендерится; подпись и контент -- ниже).
function expectWindowHeaderOpensBlock(header: HTMLElement) {
  const row = header.parentElement!;
  const block = row.parentElement;
  expect(block).toBeTruthy();
  expect(block!.firstElementChild).toBe(row);
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Заголовки «Предобработки» -- единый вид (паттерн UI-VALIDATION-HDR-1 «Валидации»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("заголовки трёх колонок («Preprocessing», «Описание», «Панель управления») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    renderHdrPreprocessing();

    const hPrepr = await screen.findByRole("heading", { name: "Preprocessing", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание", level: 3 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });

    expectUnifiedHeaderContract(hPrepr, { withHelpButton: true });
    expectHeaderRowAtColumnTop(hPrepr);
    for (const h of [hDesc, hPanel]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // «Preprocessing» сохраняет защиту узкой колонки и растяжение под
    // прижатие кнопки «Справка» к правому краю (паттерн «Загрузки»/
    // «Валидации»).
    expect(hPrepr.className).toContain("truncate");
    expect(hPrepr.className).toContain("flex-1");
  });

  it("заголовки окон «Обзор» и «Мастер исправления…» -- тот же контракт в обоих режимах центральной колонки", async () => {
    renderHdrPreprocessing();

    // Режим «Обзор» (дефолт): окно графика активной остановки -- Eye,
    // как у окон «Обзор» «Загрузки»/«Валидации».
    const hOverview = await screen.findByRole("heading", { name: "Обзор: Пропуски", level: 3 });
    expectUnifiedHeaderContract(hOverview);
    expectWindowHeaderOpensBlock(hOverview);

    // Режим «Мастер исправления…»: тот же заголовок окна в pipeline-режиме
    // -- контракт не зависит от режима (иконка Wrench пинится классом
    // text-brand/aria-hidden в (c); сам факт смены иконки -- деталь
    // семантики, геометрию строки не меняет: обе size 16).
    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    const hMaster = await screen.findByRole("heading", { name: "Мастер исправления пропусков", level: 3 });
    // MANUAL-MISSING-1: строка заголовка мастера пропусков несёт кнопку
    // «Исправить вручную» (правый край) -- расширение контракта (см. (d))
    expectUnifiedHeaderContract(hMaster, { withManualButton: true });
    expectWindowHeaderOpensBlock(hMaster);

    // Возврат в режим «Обзор» через ПЕРЕКЛЮЧЕНИЕ остановки (клик по УЖЕ
    // активной остановке секцию не меняет -- инвариант информативности
    // сохраняет открытый «Мастер»; переключение автозагружает «Метрики и
    // алгоритм» новой остановки). Заголовок окна следует за активной
    // остановкой с тем же контрактом.
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Выбросы/ }));
    const hOverviewNext = await screen.findByRole("heading", { name: "Обзор: Выбросы", level: 3 });
    expectUnifiedHeaderContract(hOverviewNext);
    expectWindowHeaderOpensBlock(hOverviewNext);
  });

  it("заголовок окна «Мастер исправления выбросов» -- тот же контракт с кнопкой «Исправить вручную» (MANUAL-OUTLIERS-1)", async () => {
    renderHdrPreprocessing();

    // Переход: степпер → «Выбросы» → «Исправить выбросы» (pipeline-режим).
    // Данные Обзора/мастера не нужны: заголовок структурный (оседает в
    // error-состоянии, R6 оценки рисков UI-PREPR-HDR-1).
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Выбросы/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить выбросы" }));
    const hMaster = await screen.findByRole("heading", { name: "Мастер исправления выбросов", level: 3 });
    // MANUAL-OUTLIERS-1: строка заголовка мастера выбросов несёт кнопку
    // «Исправить вручную» (правый край) -- то же расширение контракта,
    // что у мастера пропусков (MANUAL-MISSING-1).
    expectUnifiedHeaderContract(hMaster, { withManualButton: true });
    expectWindowHeaderOpensBlock(hMaster);
  });

  it("выравнивание по нижней горизонтали: офсеты pt-1 ОБОИХ колонок убраны, подпись «Математические преобразования» сохранена", async () => {
    renderHdrPreprocessing();

    const hPrepr = await screen.findByRole("heading", { name: "Preprocessing", level: 2 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });
    const leftAside = hPrepr.closest("aside")!;
    const rightAside = hPanel.closest("aside")!;

    // pt-1 сдвигал обе колонки на 4px вниз -- низы заголовков уходили с
    // общей горизонтали; контракт: вертикальных офсетов у колонок нет.
    expect(leftAside.className).not.toContain("pt-");
    expect(rightAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(within(leftAside).getByText("Математические преобразования")).toBeInTheDocument();
  });
});
