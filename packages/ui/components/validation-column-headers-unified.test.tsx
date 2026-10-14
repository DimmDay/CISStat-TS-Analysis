// packages/ui/components/validation-column-headers-unified.test.tsx
//
// Задача UI-VALIDATION-HDR-1 (2026-10-14, постановка тимлида): привести к
// единому виду по паттерну задачи UI-UPLOAD-HDR-1 вкладки «Загрузка»:
//   (1) заголовки колонок 3-колоночного layout вкладки «Валидация»
//       («Data Quality», «Описание», «Панель управления»);
//   (2) заголовки окон «Обзор» и «Мастер исправления…» центральной колонки.
//
// Контракт паттерна (эталон -- upload-column-headers-unified.test.tsx,
// структурный паттерн AppliedTasksNavigator):
//   (a) типографика: text-lg (18px) + font-semibold + text-neutral-800
//       («Data Quality»/«Панель управления» уже были text-lg; «Описание» и
//       «Обзор»/«Мастер…» рендерились дефолтным text-base -- рассинхрон 2px);
//   (b) строка-паттерн: flex items-center gap-2;
//   (c) иконка паттерна: lucide svg size 16, text-brand, aria-hidden;
//   (d) состав строки: [иконка, заголовок] у «Описания»/«Обзора»/«Мастера»/
//       «Панели управления»; у «Data Quality» -- [иконка, h2, кнопка
//       «Справка»] с shrink-0 у кнопки (паттерн левой колонки «Загрузки»,
//       UI-UPLOAD-HELP-1; раньше строка была justify-between без иконки);
//   (e) выравнивание по нижней горизонтали: строка заголовка -- первая
//       ветка своей колонки (спуск по firstElementChild), вертикальные
//       офсеты pt-1 ОБОИХ aside убраны;
//   (f) иконки окон семантичны режиму: «Обзор: …» -- Eye (как в
//       «Загрузке»), «Мастер исправления…» -- Wrench; обе text-brand
//       aria-hidden.
//
// jsdom не считает layout -- инвариант «низы на одной горизонтали» пинится
// структурой: строка -- первая ветка колонки + одинаковый line box всех
// заголовков (text-lg 28px > иконки 16px, items-center). Тот же подход,
// что в эталонном тесте «Загрузки».
//
// Оракулы на СВОИХ данных: свой мок /session/current (маркер сессии
// hdr-val-1, has_active_dataset: false -- все заголовки рендерятся и без
// активного датасета; поведение подтверждено существующими тестами
// TsAnalysisValidation.test.tsx). Корпус дизъюнктен существующим сюитам.

import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisValidation } from "./TsAnalysisValidation";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что в TsAnalysisValidation.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус (маркер сессии hdr-val-1, без активного датасета) ─────

function mockHdrValidationFetch() {
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
            session_marker: "hdr-val-1",
            updated_at: null,
          }),
      });
    }
    // Все прочие эндпоинты не нужны: заголовки структурные, рендерятся
    // без данных (тот же базовый мок, что в существующих тестах модуля).
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

function renderHdrValidation() {
  mockHdrValidationFetch();
  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>
  );
}

// ── Контракт единого вида заголовка (эталон UI-UPLOAD-HDR-1) ──────────

function expectUnifiedHeaderContract(header: HTMLElement, opts: { withHelpButton?: boolean } = {}) {
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

  // (d) Состав строки: [иконка, заголовок]; у «Data Quality» --
  //     [иконка, h2, кнопка «Справка» (shrink-0)] -- паттерн «Загрузки».
  if (opts.withHelpButton) {
    expect(row!.children).toHaveLength(3);
    const helpButton = row!.children[2] as HTMLElement;
    expect(helpButton.tagName).toBe("BUTTON");
    expect(helpButton.textContent).toBe("Справка");
    expect(helpButton.className).toContain("shrink-0");
  } else {
    expect(row!.children).toHaveLength(2);
  }
}

// Инвариант «низ заголовков на одной горизонтали» в структурной форме:
// спуск по firstElementChild от корня колонки приводит ровно в строку
// заголовка (строка -- первая ветка колонки). Применим к ЗАГОЛОВКАМ
// КОЛОНОК («Data Quality», «Описание», «Панель управления»); окно
// «Обзор»/«Мастер…» -- второй блок центральной колонки, ему -- своя
// форма ниже (как в эталоне «Загрузки»: upload-module-help.test.tsx
// пинит окно «Обзор» без инварианта верха колонки).
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

describe("Заголовки «Валидации» -- единый вид (паттерн UI-UPLOAD-HDR-1 «Загрузки»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("заголовки трёх колонок («Data Quality», «Описание», «Панель управления») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    renderHdrValidation();

    const hDq = await screen.findByRole("heading", { name: "Data Quality", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание", level: 3 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });

    expectUnifiedHeaderContract(hDq, { withHelpButton: true });
    expectHeaderRowAtColumnTop(hDq);
    for (const h of [hDesc, hPanel]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // «Data Quality» сохраняет защиту узкой колонки и растяжение под
    // прижатие кнопки «Справка» к правому краю (паттерн «Загрузки»).
    expect(hDq.className).toContain("truncate");
    expect(hDq.className).toContain("flex-1");
  });

  it("заголовки окон «Обзор» и «Мастер исправления…» -- тот же контракт в обоих режимах центральной колонки", async () => {
    renderHdrValidation();

    // Режим «Обзор» (дефолт): окно графика активной проверки -- Eye,
    // как у окна «Обзор» «Загрузки».
    const hOverview = await screen.findByRole("heading", { name: "Обзор: Типы данных", level: 3 });
    expectUnifiedHeaderContract(hOverview);
    expectWindowHeaderOpensBlock(hOverview);

    // Режим «Мастер исправления…»: тот же заголовок окна в pipeline-режиме
    // -- контракт не зависит от режима (иконка Wrench пинится классом
    // text-brand/aria-hidden в (c); сам факт смены иконки -- деталь
    // семантики, геометрию строки не меняет: обе size 16).
    fireEvent.click(await screen.findByRole("button", { name: "Исправить типы данных" }));
    const hMaster = await screen.findByRole("heading", { name: "Мастер исправления типов", level: 3 });
    expectUnifiedHeaderContract(hMaster);
    expectWindowHeaderOpensBlock(hMaster);

    // Возврат в режим «Обзор» через ПЕРЕКЛЮЧЕНИЕ остановки (клик по УЖЕ
    // активной остановке секцию не меняет -- инвариант информативности
    // сохраняет открытый «Мастер»; переключение автозагружает «Метрики и
    // алгоритм» новой остановки). Заголовок окна следует за активной
    // проверкой с тем же контрактом.
    const leftAside = screen.getByRole("heading", { name: "Data Quality", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Форматы и шаблоны/ }));
    const hOverviewNext = await screen.findByRole("heading", { name: "Обзор: Форматы и шаблоны", level: 3 });
    expectUnifiedHeaderContract(hOverviewNext);
    expectWindowHeaderOpensBlock(hOverviewNext);
  });

  it("выравнивание по нижней горизонтали: офсеты pt-1 ОБОИХ колонок убраны, подпись «Контроль качества данных» сохранена", async () => {
    renderHdrValidation();

    const hDq = await screen.findByRole("heading", { name: "Data Quality", level: 2 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });
    const leftAside = hDq.closest("aside")!;
    const rightAside = hPanel.closest("aside")!;

    // pt-1 сдвигал обе колонки на 4px вниз -- низы заголовков уходили с
    // общей горизонтали; контракт: вертикальных офсетов у колонок нет.
    expect(leftAside.className).not.toContain("pt-");
    expect(rightAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(within(leftAside).getByText("Контроль качества данных")).toBeInTheDocument();
  });
});
