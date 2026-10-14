// packages/ui/components/eda-column-headers-unified.test.tsx
//
// Задача UI-EDA-HDR-1 (2026-10-14, постановка тимлида): привести к
// единому виду по паттерну задачи UI-PREPR-HDR-1 вкладки «Предобработка»
// (которая, в свою очередь, переносит UI-VALIDATION-HDR-1 «Валидации» →
// UI-UPLOAD-HDR-1 «Загрузки») заголовки вкладки «Разведочный EDA»:
//   (1) заголовки колонок 3-колоночного layout («Разведочный EDA»,
//       «Описание», «Панель управления»);
//   (2) заголовок окна «Обзор: …» центральной колонки (EDA не имеет
//       мастер-режима окна — центральное окно ВСЕГДА «Обзор: {label}»,
//       поэтому иконка окна — Eye, без режимного Wrench).
//
// Контракт паттерна (эталон -- preprocessing-column-headers-unified.test.tsx):
//   (a) типографика: text-lg (18px) + font-semibold + text-neutral-800
//       («Разведочный EDA»/«Панель управления» уже были text-lg; «Описание»
//       и «Обзор» рендерились дефолтным text-base -- рассинхрон 2px);
//   (b) строка-паттерн: flex items-center gap-2;
//   (c) иконка паттерна: lucide svg size 16, text-brand, aria-hidden;
//   (d) состав строки: [иконка, заголовок] у «Описания»/«Обзора»/
//       «Панели управления»; у «Разведочный EDA» -- [иконка, h2, кнопка
//       «Справка»] с shrink-0 у кнопки (паттерн левых колонок «Загрузки»/
//       «Валидации»/«Предобработки»; раньше строка была justify-between
//       без иконки);
//   (e) выравнивание по нижней горизонтали: строка заголовка -- первая
//       ветка своей колонки (спуск по firstElementChild), вертикальные
//       офсеты pt-1 ОБОИХ aside убраны.
//
// jsdom не считает layout -- инвариант «низы на одной горизонтали» пинится
// структурой: строка -- первая ветка колонки + одинаковый line box всех
// заголовков (text-lg 28px > иконки 16px, items-center). Тот же подход,
// что в эталонных тестах «Загрузки»/«Валидации»/«Предобработки».
//
// Оракулы на СВОИХ данных: свой мок /session/current (маркер сессии
// hdr-eda-1, has_active_dataset: false -- все заголовки рендерятся и без
// активного датасета; поведение подтверждено существующими тестами
// TsAnalysisEDA.test.tsx, рендерящими модуль с mockActiveDataset = null).
// Корпус дизъюнктен существующим сюитам.

import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisEDA } from "./TsAnalysisEDA";
import { AppShellProvider } from "../context/AppShellContext";

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что в TsAnalysisEDA.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус (маркер сессии hdr-eda-1, без активного датасета) ─────

function mockHdrEdaFetch() {
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
            target_column: null,
            session_marker: "hdr-eda-1",
            updated_at: null,
          }),
      });
    }
    // Все прочие эндпоинты (самофетчи остановок, профильные/прогрессные
    // запросы) не нужны: заголовки структурные, рендерятся без данных --
    // оседают в error-состояниях соответствующих панелей (R6 оценки
    // рисков).
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

function renderHdrEda() {
  mockHdrEdaFetch();
  return render(
    <AppShellProvider>
      <TsAnalysisEDA />
    </AppShellProvider>
  );
}

// ── Контракт единого вида заголовка (эталон UI-PREPR-HDR-1) ──────────

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

  // (d) Состав строки: [иконка, заголовок]; у «Разведочный EDA» --
  //     [иконка, h2, кнопка «Справка» (shrink-0)] -- паттерн левых
  //     колонок «Загрузки»/«Валидации»/«Предобработки».
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
// КОЛОНОК («Разведочный EDA», «Описание», «Панель управления»); окно
// «Обзор: …» -- второй блок центральной колонки, ему -- своя форма ниже
// (как в эталонах «Загрузки»/«Валидации»/«Предобработки»).
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

// Инвариант для заголовка ОКНА («Обзор: …»): строка заголовка открывает
// своё окно -- она первая ветка блока окна (внутри окна над ней ничего
// не рендерится; подпись и контент -- ниже).
function expectWindowHeaderOpensBlock(header: HTMLElement) {
  const row = header.parentElement!;
  const block = row.parentElement;
  expect(block).toBeTruthy();
  expect(block!.firstElementChild).toBe(row);
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Заголовки EDA -- единый вид (паттерн UI-PREPR-HDR-1 «Предобработки»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("заголовки трёх колонок («Разведочный EDA», «Описание», «Панель управления») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    renderHdrEda();

    const hEda = await screen.findByRole("heading", { name: "Разведочный EDA", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание", level: 3 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });

    expectUnifiedHeaderContract(hEda, { withHelpButton: true });
    expectHeaderRowAtColumnTop(hEda);
    for (const h of [hDesc, hPanel]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // «Разведочный EDA» сохраняет защиту узкой колонки и растяжение под
    // прижатие кнопки «Справка» к правому краю (паттерн «Загрузки»/
    // «Валидации»/«Предобработки»).
    expect(hEda.className).toContain("truncate");
    expect(hEda.className).toContain("flex-1");
  });

  it("заголовок окна «Обзор: …» -- тот же контракт; следует за активной остановкой при переключении степпера", async () => {
    renderHdrEda();

    // Дефолтная остановка «Описательные статистики»: окно графика -- Eye,
    // как у окон «Обзор» «Загрузки»/«Валидации»/«Предобработки».
    const hOverview = await screen.findByRole("heading", {
      name: "Обзор: Описательные статистики",
      level: 3,
    });
    expectUnifiedHeaderContract(hOverview);
    expectWindowHeaderOpensBlock(hOverview);

    // Переключение остановки степпером левой колонки: заголовок окна
    // следует за активной остановкой с тем же контрактом (клик по УЖЕ
    // активной остановке секцию не меняет -- инвариант информативности
    // зеркально VALID-2/PREPR; здесь переключение -- на другую остановку).
    const leftAside = screen
      .getByRole("heading", { name: "Разведочный EDA", level: 2 })
      .closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Корреляция/ }));
    const hOverviewNext = await screen.findByRole("heading", {
      name: "Обзор: Корреляция (ACF/PACF)",
      level: 3,
    });
    expectUnifiedHeaderContract(hOverviewNext);
    expectWindowHeaderOpensBlock(hOverviewNext);
  });

  it("выравнивание по нижней горизонтали: офсеты pt-1 ОБОИХ колонок убраны, подпись «Финал перед моделированием» сохранена", async () => {
    renderHdrEda();

    const hEda = await screen.findByRole("heading", { name: "Разведочный EDA", level: 2 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });
    const leftAside = hEda.closest("aside")!;
    const rightAside = hPanel.closest("aside")!;

    // pt-1 сдвигал обе колонки на 4px вниз -- низы заголовков уходили с
    // общей горизонтали; контракт: вертикальных офсетов у колонок нет.
    expect(leftAside.className).not.toContain("pt-");
    expect(rightAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(within(leftAside).getByText("Финал перед моделированием")).toBeInTheDocument();
  });
});
