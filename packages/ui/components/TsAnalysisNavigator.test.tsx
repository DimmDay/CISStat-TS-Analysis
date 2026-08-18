// packages/ui/components/TsAnalysisNavigator.test.tsx
//
// Тесты компонента TsAnalysisNavigator.
//
// Что проверяем:
//   - заголовок «Маршрут исследования» (бывш. «Путеводитель») и «Тарифы»
//   - 10 остановок степпера (Загрузка, Валидация, EDA, ...)
// с правильными soon-метками
//   - активная остановка по умолчанию: Загрузка
//   - активный пункт по умолчанию: «Автопревью и типы колонок»
//   - кнопка "Начать анализ" ведёт на /upload (для существующих) /
//     "Скоро" с Lock-иконкой (для будущих)
//   - панель "Этапы модуля" показывает превью пунктов активной остановки
//   - клик по пункту меняет заголовок окна "Обзор"
//   - кнопка "Запустить анализ" в панели этапов — disabled
//
// Новая последовательность слева направо (Task 23):
//   1. Степпер + Тарифы (w-60)   ← левая колонка (без изменений)
//   2. Этапы модуля (w-80)      ← бывшая правая, теперь средняя
//   3. Описание + Обзор (flex-1) ← бывший центр, теперь правая
//
// Task 23b: gap между колонками увеличен с gap-6 (24px) до gap-[49px] (49px),
// то есть +25px на каждый из двух gap-ов. Секция «Описание + Обзор» (flex-1)
// автоматически сжимается на 50px.

import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TsAnalysisNavigator } from "./TsAnalysisNavigator";
import { NAVIGATOR_STOPS } from "../lib/navigator-stops";

// ─────────────────────────────────────────────────────────────────────────
// helpers
// ─────────────────────────────────────────────────────────────────────────

function renderNavigator() {
  return render(<TsAnalysisNavigator />);
}

// Возвращает корневой flex-контейнер 3-колоночной компоновки.
// Используется в тестах на порядок колонок (Task 23) и на gap (Task 23b).
function getRootFlexContainer(): HTMLElement {
  // Ищем самый внешний div с классами .flex .mt-8 — это корневой контейнер
  // 3-колоночной компоновки Навигатора.
  const candidates = document.querySelectorAll("div.flex.mt-8");
  if (candidates.length === 0) {
    throw new Error("Root flex container (.flex.mt-8) not found");
  }
  // Берём первый подходящий — он всегда один в компоненте.
  return candidates[0] as HTMLElement;
}

// Возвращает прямых детей корневого flex-контейнера (только 3 колонки).
function getColumns(): HTMLElement[] {
  const root = getRootFlexContainer();
  return Array.from(root.children) as HTMLElement[];
}

// ─────────────────────────────────────────────────────────────────────────
// tests
// ─────────────────────────────────────────────────────────────────────────

describe("TsAnalysisNavigator", () => {
  // ── Базовая структура ──────────────────────────────────────────────────

  it("renders 'Маршрут исследования' and 'Тарифы' headings", () => {
    renderNavigator();
    expect(screen.getByText("Маршрут исследования")).toBeInTheDocument();
    expect(screen.getByText("Тарифы")).toBeInTheDocument();
  });

  it("renders 10 stops in the stepper", () => {
    renderNavigator();
    // 10 остановок определены в NAVIGATOR_STOPS.
    expect(NAVIGATOR_STOPS).toHaveLength(10);
    // Каждая остановка должна присутствовать в степпере.
    NAVIGATOR_STOPS.forEach((stop) => {
      expect(screen.getByText(stop.label)).toBeInTheDocument();
    });
  });

  it("default active stop is 'Загрузка' and default item is 'Автопревью и типы колонок'", () => {
    renderNavigator();
    // Активная остановка по умолчанию — Загрузка (id=upload).
    expect(screen.getByText(/Этапы модуля: Загрузка/)).toBeInTheDocument();
    // Активный пункт по умолчанию — первый в items Загрузки (id=preview).
    expect(
      screen.getByText("Автопревью и типы колонок")
    ).toBeInTheDocument();
  });

  // ── Заголовок «Обзор» зависит от активного пункта ──────────────────────

  it("changes 'Обзор:' title when user clicks another item in the active stop", async () => {
    const user = userEvent.setup();
    renderNavigator();

    // Пункт «Подтверждение автоопределения» (id=structure_confirm) —
    // после добавления «Графика» стал третьим в items Загрузки.
    // После Task 23: панель «Этапы модуля» — средняя колонка (между
    // степпером и окном «Описание + Обзор»).
    const itemTitle = "Подтверждение автоопределения";
    await user.click(screen.getByText(itemTitle));

    // Заголовок «Обзор:» в правой колонке должен показать этот пункт.
    expect(
      screen.getByText(`Обзор: ${itemTitle}`)
    ).toBeInTheDocument();
  });

  // ── Кнопка «Начать анализ» ─────────────────────────────────────────────

  it("renders 'Начать анализ' button for existing modules (not soon)", () => {
    renderNavigator();
    // Для активной остановки «Загрузка» (soon=false) кнопка доступна.
    expect(screen.getByText("Начать анализ")).toBeInTheDocument();
  });

  it("renders 'Скоро' badge instead of 'Начать анализ' for future modules (soon=true)", async () => {
    const user = userEvent.setup();
    renderNavigator();

    // Кликаем на будущую остановку (например, Сценарный анализ, soon=true).
    const futureStop = NAVIGATOR_STOPS.find((s) => s.soon);
    expect(futureStop).toBeDefined();
    await user.click(screen.getByText(futureStop!.label));

    // Кнопки "Начать анализ" быть не должно — её заменяет бейдж «Скоро».
    expect(screen.queryByText("Начать анализ")).toBeNull();
    expect(screen.getByText(/Скоро/i)).toBeInTheDocument();
  });

  // ── Панель «Этапы модуля» ──────────────────────────────────────────────

  it("disables 'Запустить…' button in the items preview", () => {
    renderNavigator();
    const btn = screen.getByRole("button", { name: /Запустить/i });
    expect(btn).toBeDisabled();
  });

  it("shows item preview cards in the 'Этапы модуля' panel for the active stop", () => {
    renderNavigator();
    const uploadStop = NAVIGATOR_STOPS.find((s) => s.id === "upload")!;
    uploadStop.items.forEach((item) => {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    });
  });

  // ── Task 22 — условный рендеринг «Пайплайн автопревью» ─────────────────

  describe("Task 22: UploadAutoPreviewPipeline conditional rendering", () => {
    it("renders the pipeline flowchart when Загрузка + 'Автопревью и типы колонок' is active", () => {
      renderNavigator();
      // По умолчанию активны upload + preview → пайплайн должен быть в DOM.
      expect(
        screen.getByRole("img", { name: /Пайплайн автопревью/i })
      ).toBeInTheDocument();
    });

    it("replaces the pipeline with a placeholder div when user switches to another item of Загрузка", async () => {
      const user = userEvent.setup();
      renderNavigator();

      // Кликаем на другой пункт Загрузки (не preview).
      const otherItem = screen.getByText("Подтверждение автоопределения");
      await user.click(otherItem);

      // Пайплайн должен исчезнуть.
      expect(
        screen.queryByRole("img", { name: /Пайплайн автопревью/i })
      ).toBeNull();
      // Должна появиться текстовая заглушка.
      expect(
        screen.getByText(/\[ область графика/i)
      ).toBeInTheDocument();
    });

    it("disappears when user switches to another stop (not Загрузка)", async () => {
      const user = userEvent.setup();
      renderNavigator();

      // Кликаем на другую остановку (не Загрузка, не soon).
      const otherStop = NAVIGATOR_STOPS.find(
        (s) => s.id !== "upload" && !s.soon
      )!;
      await user.click(screen.getByText(otherStop.label));

      expect(
        screen.queryByRole("img", { name: /Пайплайн автопревью/i })
      ).toBeNull();
    });

    it("reappears when user navigates back to Загрузка + 'Автопревью и типы колонок'", async () => {
      const user = userEvent.setup();
      renderNavigator();

      // Уходим на другую остановку.
      const otherStop = NAVIGATOR_STOPS.find(
        (s) => s.id !== "upload" && !s.soon
      )!;
      await user.click(screen.getByText(otherStop.label));
      // Возвращаемся на Загрузку.
      await user.click(screen.getByText("Загрузка"));

      // Пайплайн снова должен быть в DOM.
      expect(
        screen.getByRole("img", { name: /Пайплайн автопревью/i })
      ).toBeInTheDocument();
    });
  });

  // ── Task 23 — порядок колонок ──────────────────────────────────────────
  //
  // Новая последовательность слева направо:
  //   1. Степпер + Тарифы (левая колонка, без изменений)
  //   2. Этапы модуля (бывшая правая → теперь средняя)
  //   3. Описание + Обзор (бывший центр → теперь правая)
  //
  // Используем within() для проверки, что конкретный контент находится
  // в конкретной колонке (getByText один найдёт текст в любой колонке,
  // и без within() порядок не проверить).

  describe("Task 23: column order", () => {
    it("renders 3 top-level columns in the new order: stepper | stages | description+overview", () => {
      renderNavigator();

      const cols = getColumns();
      expect(cols).toHaveLength(3);

      const [col1, col2, col3] = cols;

      // Колонка 1: Маршрут исследования (степпер + Тарифы)
      expect(
        within(col1).getByText("Маршрут исследования")
      ).toBeInTheDocument();
      expect(within(col1).getByText("Тарифы")).toBeInTheDocument();
      // Степпер рендерит aria-label заглавными буквами.
      expect(within(col1).getByLabelText("ЗАГРУЗКА")).toBeInTheDocument();

      // Колонка 2: Этапы модуля (после Task 23 — средняя)
      expect(within(col2).getByText(/Этапы модуля:/)).toBeInTheDocument();
      // Здесь же — пункты активной остановки (Загрузка по умолчанию).
      expect(
        within(col2).getByText("Автопревью и типы колонок")
      ).toBeInTheDocument();

      // Колонка 3: Описание + Обзор (после Task 23 — правая)
      expect(within(col3).getByText("Описание")).toBeInTheDocument();
      expect(within(col3).getByText(/Обзор:/)).toBeInTheDocument();
    });

    it("does NOT render 'Этапы модуля' in the right (3rd) column after Task 23", () => {
      // Регрессионный тест: до Task 23 «Этапы модуля» были в правой колонке.
      // Если кто-то вернёт старый порядок — этот тест должен упасть.
      renderNavigator();
      const cols = getColumns();
      expect(cols).toHaveLength(3);
      const col3 = cols[2];
      // «Этапы модуля: ЗАГРУЗКА» НЕ должно быть в третьей (правой) колонке.
      expect(within(col3).queryByText(/Этапы модуля:/)).toBeNull();
    });

    it("does NOT render 'Описание' in the middle (2nd) column after Task 23", () => {
      // Симметричный регрессионный: «Описание» НЕ должно быть в средней колонке.
      renderNavigator();
      const cols = getColumns();
      expect(cols).toHaveLength(3);
      const col2 = cols[1];
      expect(within(col2).queryByText("Описание")).toBeNull();
    });

    it("preserves widths: w-60 for stepper, w-80 for stages, flex-1 for description+overview", () => {
      renderNavigator();
      const cols = getColumns();
      expect(cols).toHaveLength(3);

      // Колонка 1: степпер + Тарифы — фиксированная w-60 (240px).
      expect(cols[0].className).toContain("w-60");
      // Колонка 2: Этапы модуля — фиксированная w-80 (320px).
      expect(cols[1].className).toContain("w-80");
      // Колонка 3: Описание + Обзор — flex-1 (занимает остаток).
      expect(cols[2].className).toContain("flex-1");
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Task 23b — увеличение gap между колонками до 49px
  // (+25px к каждому из 2 gap-ов, flex-1-секция сжимается на 50px).
  // ─────────────────────────────────────────────────────────────────────
  describe("Task 23b: column gap = 49px", () => {
    it("root flex container has gap-[49px] class", () => {
      renderNavigator();
      // Ищем корневой div с классом gap-[49px] (arbitrary value Tailwind).
      // В querySelector квадратные скобки экранируются через \\.
      const root = document.querySelector(".flex.gap-\\[49px\\].mt-8");
      expect(root).not.toBeNull();
    });

    it("root flex container does NOT have legacy gap-6 class", () => {
      renderNavigator();
      // Регрессия: gap-6 (24px) был до Task 23b — после правки класса быть не должно.
      const root = document.querySelector(".flex.gap-6.mt-8");
      expect(root).toBeNull();
    });

    it("preserves column widths after gap change: w-60, w-80, flex-1", () => {
      renderNavigator();
      // После изменения gap классы ширин колонок не должны меняться.
      const root = document.querySelector(
        ".flex.gap-\\[49px\\].mt-8"
      ) as HTMLElement;
      expect(root).not.toBeNull();

      const children = Array.from(root.children) as HTMLElement[];
      expect(children).toHaveLength(3);

      // Колонка 1: степпер + Тарифы — w-60.
      expect(children[0].className).toContain("w-60");
      // Колонка 2: Этапы модуля — w-80.
      expect(children[1].className).toContain("w-80");
      // Колонка 3: Описание + Обзор — flex-1.
      expect(children[2].className).toContain("flex-1");
    });
  });
});