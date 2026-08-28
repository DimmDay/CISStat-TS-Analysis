// packages/ui/components/TsAnalysisNavigator.test.tsx
//
// Тесты компонента TsAnalysisNavigator.
//
// ⚠️ Компонент использует хук useAppShell() — оборачиваем в <AppShellProvider>.
// Все тексты берём ровно из navigator-stops.ts (label ЗАГЛАВНЫМИ,
// item.title — точные строки).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { TsAnalysisNavigator } from "./TsAnalysisNavigator";
import { NAVIGATOR_STOPS } from "../lib/navigator-stops";
import { AppShellProvider } from "../context/AppShellContext";

// ─────────────────────────────────────────────────────────────────────────
// helpers
// ─────────────────────────────────────────────────────────────────────────

// Рендер компонента, обёрнутого в AppShellProvider — без этого useAppShell()
// выбрасывает "useAppShell должен вызываться внутри <AppShellProvider>".
function renderNavigator() {
  return render(
    <AppShellProvider>
      <TsAnalysisNavigator />
    </AppShellProvider>
  );
}

// Корневой flex-контейнер 3-колоночной компоновки.
// Берём div с классами .flex .mt-8 (gap-класс намеренно не указываем —
// так тест устойчив и к gap-6, и к gap-[49px]).
function getRootFlexContainer(): HTMLElement {
  const candidates = document.querySelectorAll("div.flex.mt-8");
  if (candidates.length === 0) {
    throw new Error("Root flex container (.flex.mt-8) not found");
  }
  return candidates[0] as HTMLElement;
}

function getColumns(): HTMLElement[] {
  const root = getRootFlexContainer();
  return Array.from(root.children) as HTMLElement[];
}

// ─────────────────────────────────────────────────────────────────────────
// tests
// ─────────────────────────────────────────────────────────────────────────

describe("TsAnalysisNavigator", () => {
  // ── Smoke: рендерится без падения ─────────────────────────────────────

  it("renders without crash", () => {
    renderNavigator();
    expect(getRootFlexContainer()).toBeInTheDocument();
  });

  it("renders all 10 stop labels from navigator-stops.ts", () => {
    renderNavigator();
    expect(NAVIGATOR_STOPS).toHaveLength(10);
    NAVIGATOR_STOPS.forEach((stop) => {
      expect(screen.getByText(stop.label)).toBeInTheDocument();
    });
  });

  it("renders all item titles of the active (upload) stop", () => {
    renderNavigator();
    const uploadStop = NAVIGATOR_STOPS.find((s) => s.id === "upload")!;
    uploadStop.items.forEach((item) => {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    });
  });

  it("does not render the tariff section in the first column", () => {
    renderNavigator();
    const firstColumn = getColumns()[0];

    expect(within(firstColumn).queryByRole("heading", { name: "Тарифы" })).toBeNull();
    expect(within(firstColumn).queryAllByRole("radio")).toHaveLength(0);
  });

  // ── Task 23 — порядок колонок ──────────────────────────────────────────

  describe("Task 23: column order", () => {
    it("renders 3 top-level columns under the root flex container", () => {
      renderNavigator();
      const cols = getColumns();
      expect(cols).toHaveLength(3);
    });

    it("column 1 contains the upload stop label (stepper)", () => {
      renderNavigator();
      const cols = getColumns();
      const col1 = cols[0];
      expect(within(col1).getByText("ЗАГРУЗКА")).toBeInTheDocument();
    });

    it("column 2 (middle, after Task 23) contains the active stop's items", () => {
      renderNavigator();
      const cols = getColumns();
      const col2 = cols[1];
      const uploadStop = NAVIGATOR_STOPS.find((s) => s.id === "upload")!;
      expect(
        within(col2).getByText(uploadStop.items[0].title)
      ).toBeInTheDocument();
    });

    it("column 3 (right, after Task 23) does NOT contain stop labels from the stepper", () => {
      renderNavigator();
      const cols = getColumns();
      const col3 = cols[2];
      expect(within(col3).queryByText("ЗАГРУЗКА")).toBeNull();
    });

    it("preserves widths: w-60, w-80, flex-1", () => {
      renderNavigator();
      const cols = getColumns();
      expect(cols[0].className).toContain("w-60");
      expect(cols[1].className).toContain("w-80");
      expect(cols[2].className).toContain("flex-1");
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-08-29 — окно «Обзор» остановки «График» (upload+chart)
  // рендерит статичный линейный график demo_finance_ohlcv.csv по volume.
  // Требование тимлида: график СТАТИЧНЫЙ, отображается ПРИ ЛЮБЫХ УСЛОВИЯХ,
  // даже если сам датасет удалён. Значит — НЕ зависит от activeDataset.
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + chart: static line chart in Overview", () => {
    // По умолчанию активна пара upload+preview (первый item), поэтому
    // переключаемся на chart вручную через клик по item-карточке.
    // ВАЖНО: используем fireEvent.click() вместо нативного .click() —
    // React synthetic events в jsdom не всегда срабатывают через
    // нативный Element.click(), особенно на <article> элементах.
    function activateChartItem() {
      const card = screen.getByText("График");
      const article = card.closest("article")!;
      fireEvent.click(article);
    }

    it("renders a recharts chart frame when upload + chart is active", () => {
      renderNavigator();
      activateChartItem();
      const c3 = getColumns()[2];
      // within() возвращает только By* функции, без querySelector —
      // используем нативный querySelector у HTMLElement.
      expect(c3.querySelector(".recharts-responsive-container")).toBeTruthy();
    });

    it("renders the static dataset label demo_finance_ohlcv.csv in Overview", () => {
      renderNavigator();
      activateChartItem();
      // Имя файла встречается в шапке графика и в подписи — минимум 1.
      const matches = screen.getAllByText(/demo_finance_ohlcv\.csv/i);
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });

    it("renders the feature label volume in Overview", () => {
      renderNavigator();
      activateChartItem();
      expect(screen.getByText(/volume/i)).toBeInTheDocument();
    });

    it("does NOT show the generic placeholder text for chart item", () => {
      renderNavigator();
      activateChartItem();
      // Заглушка «[ область графика/таблицы/блок-схемы для «График» ]»
      // должна быть заменена статичным графиком.
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders the static chart WITHOUT activeDataset (works if dataset is deleted)", () => {
      // AppShellProvider по умолчанию не предоставляет activeDataset —
      // если бы график зависел от сессии, тест бы падал на empty-state.
      renderNavigator();
      activateChartItem();
      expect(screen.getAllByText(/demo_finance_ohlcv\.csv/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText(/нет данных/i)).toBeNull();
    });

    it("still shows generic placeholder for OTHER upload items (no regression)", () => {
      renderNavigator();
      // По умолчанию активен upload + preview (первый item) —
      // для preview рендерится UploadAutoPreviewPipeline, не заглушка.
      // Переключимся на «Подтверждение автоопределения» (3-й item),
      // для которого НЕТ специализированного Overview-компонента.
      const card = screen.getByText("Подтверждение автоопределения");
      fireEvent.click(card.closest("article")!);
      expect(
        screen.getByText(/область графика\/таблицы\/блок-схемы/)
      ).toBeInTheDocument();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Task 23b — gap между колонками увеличен до 49px
  // (+25px к каждому из 2 gap-ов; flex-1-секция сжимается на 50px).
  // ─────────────────────────────────────────────────────────────────────
  describe("Task 23b: column gap = 49px", () => {
    it("root flex container has gap-[49px] class", () => {
      renderNavigator();
      const root = document.querySelector(".flex.gap-\\[49px\\].mt-8");
      expect(root).not.toBeNull();
    });

    it("root flex container does NOT have legacy gap-6 class", () => {
      renderNavigator();
      const root = document.querySelector(".flex.gap-6.mt-8");
      expect(root).toBeNull();
    });

    it("preserves column widths after gap change: w-60, w-80, flex-1", () => {
      renderNavigator();
      const root = document.querySelector(
        ".flex.gap-\\[49px\\].mt-8"
      ) as HTMLElement;
      expect(root).not.toBeNull();

      const children = Array.from(root.children) as HTMLElement[];
      expect(children).toHaveLength(3);

      expect(children[0].className).toContain("w-60");
      expect(children[1].className).toContain("w-80");
      expect(children[2].className).toContain("flex-1");
    });
  });
});
