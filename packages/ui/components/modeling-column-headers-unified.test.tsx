// packages/ui/components/modeling-column-headers-unified.test.tsx
//
// Задача UI-MODELING-HDR-1 (2026-10-15, постановка тимлида): привести к
// единому виду по паттерну задачи UI-PREPR-HDR-1 вкладки «Предобработка»
// (которая, в свою очередь, переносит UI-VALIDATION-HDR-1 «Валидации» →
// UI-UPLOAD-HDR-1 «Загрузки»; прямые предшественники -- UI-EDA-HDR-1/2
// вкладки «Разведочный EDA») заголовки колонок 3-колоночного layout
// вкладки «Моделирование»:
//   (1) заголовки колонок 3-колоночного layout (левая колонка --
//       "Modeling", после переименования UI-MODELING-HDR-2; «Описание»;
//       «Панель управления»);
//   (2) шрифты, выравнивание и иконки -- полный контракт серии
//       (typography/row/icon/состав/выравнивание по нижней горизонтали).
//
// Отличие от «Предобработки»/EDA: Modeling НЕ имеет окон «Обзор»/«Мастер»
// в центральной колонке -- описание ЕДИНОЕ текстовое поле, чья подпись
// (descriptionSubtitle) переключается между остановкой («Остановка ·
// {label}»), справкой и операциями правой колонки. Заголовок окна ВСЕГДА
// «Описание» -- отдельного режимного заголовка (Eye/Wrench) в этой
// вкладке нет; контракт центральной колонки пинится на строке «Описание»
// + следовании подписи за активной остановкой степпера.
//
// FIX-MODELING-TITLE-1 (2026-10-15): пин имени заголовка левой колонки
// выправлен с англ. "Modeling" на платформенное имя «Моделирование»
// (легаси-пин TsAnalysisModeling.test.tsx; структура контракта без
// изменений -- name-only правка в 3 запросах findByRole/getByRole).
//
// UI-MODELING-HDR-2 (2026-10-15, постановка тимлида): заголовок левой
// колонки «Моделирование» переименован в "Modeling" ПО ПРЯМОМУ УКАЗАНИЮ
// -- мотив FIX-MODELING-TITLE-1 снят: там текст изменился СЛУЧАЙНО без
// обновления пинов, здесь переименование ОСОЗНАННОЕ, пины обновлены
// синхронно в том же изменении (4 query-точки: 3 здесь + легаси-пин
// «renders the module title»). Модульное имя «Моделирование» на других
// поверхностях (TasksHub, TaskCard, task-stops, реестр знаний,
// навигация, прогресс) НЕ менялось -- вне скоупа постановки. Прецедент
// EN-заголовков левых колонок: «Preprocessing», «Data Quality»,
// «Exploration» (UI-EDA-HDR-2).
//
// Контракт паттерна (эталон -- eda-column-headers-unified.test.tsx /
// preprocessing-column-headers-unified.test.tsx):
//   (a) типографика: text-lg (18px) + font-semibold + text-neutral-800
//       («Моделирование»/«Панель управления» уже были text-lg; «Описание»
//       рендерилось дефолтным text-base -- рассинхрон 2px);
//   (b) строка-паттерн: flex items-center gap-2;
//   (c) иконка паттерна: lucide svg size 16, text-brand, aria-hidden;
//   (d) состав строки: [иконка, заголовок] у «Описания»/«Панели
//       управления»; у левой колонки -- [иконка, h2, кнопка «Справка»]
//       с shrink-0 у кнопки (паттерн левых колонок «Загрузки»/
//       «Валидации»/«Предобработки»/EDA; раньше строка была
//       justify-between без иконки);
//   (e) выравнивание по нижней горизонтали: строка заголовка -- первая
//       ветка своей колонки (спуск по firstElementChild), вертикальные
//       офсеты pt-1 ОБОИХ aside убраны.
//
// jsdom не считает layout -- инвариант «низы на одной горизонтали» пинится
// структурой: строка -- первая ветка колонки + одинаковый line box всех
// заголовков (text-lg 28px > иконки 16px, items-center). Тот же подход,
// что в эталонных тестах «Загрузки»/«Валидации»/«Предобработки»/EDA.
//
// Оракулы на СВОИХ данных: свой мок /session/current (маркер сессии
// hdr-modeling-1, has_active_dataset: false -- все заголовки рендерятся и
// без активного датасета; поведение подтверждено существующими тестами
// TsAnalysisModeling.test.tsx). Корпус дизъюнктен существующим сюитам.

import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisModeling } from "./TsAnalysisModeling";
import { AppShellProvider } from "../context/AppShellContext";

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что в TsAnalysisModeling.test.tsx / TsAnalysisEDA.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус (маркер сессии hdr-modeling-1, без активного датасета) ──

function mockHdrModelingFetch() {
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
            session_marker: "hdr-modeling-1",
            updated_at: null,
          }),
      });
    }
    // Все прочие эндпоинты (пул кандидатов, контекст hand-off, профильные/
    // прогрессные запросы) не нужны: заголовки структурные, рендерятся без
    // данных -- оседают в error-состояниях соответствующих панелей (класс
    // R6 оценок рисков серии).
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

function renderHdrModeling() {
  mockHdrModelingFetch();
  return render(
    <AppShellProvider>
      <TsAnalysisModeling />
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

  // (d) Состав строки: [иконка, заголовок]; у "Modeling" --
  //     [иконка, h2, кнопка «Справка» (shrink-0)] -- паттерн левых
  //     колонок «Загрузки»/«Валидации»/«Предобработки»/EDA.
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
// заголовка (строка -- первая ветка колонки). Применим ко ВСЕМ ТРЁМ
// заголовкам колонок ("Modeling", «Описание», «Панель управления»).
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

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Заголовки «Моделирования» -- единый вид (паттерн UI-PREPR-HDR-1 «Предобработки»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("заголовки трёх колонок («Modeling», «Описание», «Панель управления») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    renderHdrModeling();

    const hModeling = await screen.findByRole("heading", { name: "Modeling", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание", level: 3 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });

    expectUnifiedHeaderContract(hModeling, { withHelpButton: true });
    expectHeaderRowAtColumnTop(hModeling);
    for (const h of [hDesc, hPanel]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // Левая колонка сохраняет защиту узкой колонки и растяжение под
    // прижатие кнопки «Справка» к правому краю (паттерн «Загрузки»/
    // «Валидации»/«Предобработки»/EDA).
    expect(hModeling.className).toContain("truncate");
    expect(hModeling.className).toContain("flex-1");
  });

  it("строка «Описание» открывает блок описания; подпись следует за активной остановкой степпера", async () => {
    renderHdrModeling();

    // Дефолтная остановка «Пул кандидатов»: подпись под строкой «Описание».
    const hDesc = await screen.findByRole("heading", { name: "Описание", level: 3 });
    expectWindowRowFollowedBySubtitle(hDesc, "Остановка · Пул кандидатов");

    // Переключение остановки степпером левой колонки: подпись следует
    // за активной остановкой (клик по УЖЕ активной остановке секцию
    // не меняет -- инвариант информативности зеркально VALID-2/PREPR/EDA;
    // здесь переключение -- на другую остановку). Заголовок «Описание»
    // и его строка-паттерн НЕ меняются (в Modeling окно описания единое,
    // режимных заголовков «Обзор»/«Мастер» нет).
    const leftAside = screen
      .getByRole("heading", { name: "Modeling", level: 2 })
      .closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Определение задачи/ }));
    const subtitleNext = await screen.findByText("Остановка · Определение задачи");
    expect(subtitleNext).toBeInTheDocument();

    const hDescAfter = screen.getByRole("heading", { name: "Описание", level: 3 });
    expectUnifiedHeaderContract(hDescAfter);
    expectWindowRowFollowedBySubtitle(hDescAfter, "Остановка · Определение задачи");
  });

  it("выравнивание по нижней горизонтали: офсеты pt-1 ОБОИХ колонок убраны, подпись «Выбор модели для прогнозирования» сохранена", async () => {
    renderHdrModeling();

    const hModeling = await screen.findByRole("heading", { name: "Modeling", level: 2 });
    const hPanel = screen.getByRole("heading", { name: "Панель управления", level: 2 });
    const leftAside = hModeling.closest("aside")!;
    const rightAside = hPanel.closest("aside")!;

    // pt-1 сдвигал обе колонки на 4px вниз -- низы заголовков уходили с
    // общей горизонтали; контракт: вертикальных офсетов у колонок нет.
    expect(leftAside.className).not.toContain("pt-");
    expect(rightAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(within(leftAside).getByText("Выбор модели для прогнозирования")).toBeInTheDocument();
  });
});

// Подпись окна описания sits под строкой-паттерном -- та же форма «своя
// форма окна», что в эталонах (строка -- первая ветка блока описания,
// подпись -- следующий sibling строки).
function expectWindowRowFollowedBySubtitle(header: HTMLElement, subtitleText: string) {
  const row = header.parentElement!;
  const block = row.parentElement;
  expect(block).toBeTruthy();
  expect(block!.firstElementChild).toBe(row);
  expect(block!.textContent).toContain(subtitleText);
}
