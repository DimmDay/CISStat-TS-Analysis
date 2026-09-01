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
      // После задач 2026-08-30..2026-09-02 остановки «Подтверждение
      // автоопределения» (3-й item), «Teaser качества» (4-й item),
      // «Техническая информация» (5-й item), «Превью 5+5 строк» (6-й item)
      // и «Визуализация распределения» (7-й item) тоже имеют
      // специализированный Overview — выбираем пункт БЕЗ специализированной
      // визуализации: «Форматы и объём» (8-й item, id="formats").
      const card = screen.getByText("Форматы и объём");
      fireEvent.click(card.closest("article")!);
      expect(
        screen.getByText(/область графика\/таблицы\/блок-схемы/)
      ).toBeInTheDocument();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-08-30 — окно «Обзор» остановки «Teaser качества»
  // (upload+quality_teaser) рендерит статичную блок-схему алгоритма
  // подсчёта 4 счётчиков качества (missing / outliers / rows / duplicates).
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + quality_teaser: static infographic in Overview", () => {
    function activateQualityTeaserItem() {
      const card = screen.getByText("Teaser качества");
      fireEvent.click(card.closest("article")!);
    }

    it("renders the infographic heading when upload + quality_teaser is active", () => {
      renderNavigator();
      activateQualityTeaserItem();
      // H3 «Обзор: Teaser качества» — заголовок окна Обзор из
      // TsAnalysisNavigator. Сама инфографика тоже содержит H3 «Teaser
      // качества». Поэтому минимум 2 совпадения.
      const headings = screen.getAllByRole("heading", {
        level: 3,
        name: /teaser качества/i,
      });
      expect(headings.length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT show the generic placeholder text for quality_teaser item", () => {
      renderNavigator();
      activateQualityTeaserItem();
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders all 4 counter cards (missing / outliers / rows / duplicates)", () => {
      renderNavigator();
      activateQualityTeaserItem();
      expect(screen.getByText(/колонок с пропусками/i)).toBeInTheDocument();
      expect(screen.getByText(/колонок с выбросами/i)).toBeInTheDocument();
      expect(screen.getByText(/всего строк/i)).toBeInTheDocument();
      expect(screen.getByText(/дубликатов/i)).toBeInTheDocument();
    });

    it("renders the infographic WITHOUT activeDataset (works if dataset is deleted)", () => {
      renderNavigator();
      activateQualityTeaserItem();
      expect(screen.getByText(/_compute_quality_teaser/i)).toBeInTheDocument();
      expect(screen.queryByText(/нет данных/i)).toBeNull();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-08-30 — окно «Обзор» остановки «Подтверждение
  // автоопределения» (upload+structure_confirm) рендерит статичную
  // блок-схему алгоритма автоопределения структуры (3 параллельных
  // детектора: date / entity / frequency).
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + structure_confirm: static infographic in Overview", () => {
    function activateStructureConfirmItem() {
      const card = screen.getByText("Подтверждение автоопределения");
      fireEvent.click(card.closest("article")!);
    }

    it("renders the infographic heading when upload + structure_confirm is active", () => {
      renderNavigator();
      activateStructureConfirmItem();
      // H3 «Обзор: Подтверждение автоопределения» — это заголовок окна
      // Обзор из TsAnalysisNavigator. Сама инфографика тоже содержит H3
      // «Подтверждение автоопределения». Поэтому минимум 2 совпадения.
      const headings = screen.getAllByRole("heading", {
        level: 3,
        name: /подтверждение автоопределения/i,
      });
      expect(headings.length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT show the generic placeholder text for structure_confirm item", () => {
      renderNavigator();
      activateStructureConfirmItem();
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders 3 detector lanes (date / entity / frequency)", () => {
      renderNavigator();
      activateStructureConfirmItem();
      // Каждая из 3 дорожек встречается ровно 1 раз (нет совпадений вне
      // инфографики), используем getByText.
      expect(screen.getByText("Временная колонка")).toBeInTheDocument();
      expect(screen.getByText("Группирующая колонка")).toBeInTheDocument();
      expect(screen.getByText("Частота ряда")).toBeInTheDocument();
    });

    it("renders the infographic WITHOUT activeDataset (works if dataset is deleted)", () => {
      renderNavigator();
      activateStructureConfirmItem();
      expect(screen.getByText(/\/dataset\/structure-detection/i)).toBeInTheDocument();
      expect(screen.queryByText(/нет данных/i)).toBeNull();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-08-31 — окно «Обзор» остановки «Техническая информация»
  // (upload+tech_info) рендерит статичную блок-схему алгоритма построения
  // технической информации по каждой колонке (type_icon + 3 метрики).
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + tech_info: static infographic in Overview", () => {
    function activateTechInfoItem() {
      const card = screen.getByText("Техническая информация");
      fireEvent.click(card.closest("article")!);
    }

    it("renders the infographic heading when upload + tech_info is active", () => {
      renderNavigator();
      activateTechInfoItem();
      // H3 «Обзор: Техническая информация» — заголовок окна Обзор из
      // TsAnalysisNavigator. Сама инфографика тоже содержит H3 «Техническая
      // информация». Поэтому минимум 2 совпадения.
      const headings = screen.getAllByRole("heading", {
        level: 3,
        name: /техническая информация/i,
      });
      expect(headings.length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT show the generic placeholder text for tech_info item", () => {
      renderNavigator();
      activateTechInfoItem();
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders all 4 type_icon lanes (datetime / numeric / categorical / text)", () => {
      renderNavigator();
      activateTechInfoItem();
      // Имена type_icon встречаются несколько раз внутри инфографики
      // (лейбл дорожки + финальная подпись if/elif chain) — getAllByText.
      expect(screen.getAllByText(/datetime/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/numeric/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/categorical/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/\btext\b/i).length).toBeGreaterThanOrEqual(1);
    });

    it("renders the infographic WITHOUT activeDataset (works if dataset is deleted)", () => {
      renderNavigator();
      activateTechInfoItem();
      expect(screen.getByText(/_compute_column_info/i)).toBeInTheDocument();
      expect(screen.queryByText(/нет данных/i)).toBeNull();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-09-01 — окно «Обзор» остановки «Превью 5+5 строк»
  // (upload+preview_5_5) рендерит статичную таблицу 5+5 строк
  // синтетического датасета demo_finance_ohlcv.csv.
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + preview_5_5: static dataset preview in Overview", () => {
    function activatePreview55Item() {
      const card = screen.getByText("Превью 5+5 строк");
      fireEvent.click(card.closest("article")!);
    }

    it("renders the preview heading when upload + preview_5_5 is active", () => {
      renderNavigator();
      activatePreview55Item();
      // H3 «Обзор: Превью 5+5 строк» — заголовок окна Обзор из
      // TsAnalysisNavigator. Сама инфографика тоже содержит H3 «Превью
      // 5+5 строк». Поэтому минимум 2 совпадения.
      const headings = screen.getAllByRole("heading", {
        level: 3,
        name: /превью 5\+5 строк/i,
      });
      expect(headings.length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT show the generic placeholder text for preview_5_5 item", () => {
      renderNavigator();
      activatePreview55Item();
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders the static dataset filename demo_finance_ohlcv.csv in Overview", () => {
      renderNavigator();
      activatePreview55Item();
      expect(
        screen.getAllByText(/demo_finance_ohlcv\.csv/i).length
      ).toBeGreaterThanOrEqual(1);
    });

    it("renders all 6 column headers (date/open/high/low/close/volume)", () => {
      renderNavigator();
      activatePreview55Item();
      // Точные строковые совпадения (каждое встречается 1 раз в header).
      expect(screen.getByText("date")).toBeInTheDocument();
      expect(screen.getByText("open")).toBeInTheDocument();
      expect(screen.getByText("high")).toBeInTheDocument();
      expect(screen.getByText("low")).toBeInTheDocument();
      expect(screen.getByText("close")).toBeInTheDocument();
      expect(screen.getByText("volume")).toBeInTheDocument();
    });

    it("renders the preview WITHOUT activeDataset (works if dataset is deleted)", () => {
      renderNavigator();
      activatePreview55Item();
      // AppShellProvider по умолчанию не предоставляет activeDataset —
      // если бы превью зависело от сессии, тест бы падал на empty-state.
      expect(screen.getByText("2022-01-03")).toBeInTheDocument();
      expect(screen.queryByText(/нет данных/i)).toBeNull();
    });
  });

  // ─────────────────────────────────────────────────────────────────────
  // Задача 2026-09-02 — окно «Обзор» остановки «Визуализация
  // распределения» (upload+distribution) рендерит статичные графики
  // распределения (точечный/гистограмма/KDE) + бейджи описательной
  // статистики синтетического датасета demo_energy_consumption.csv.
  // ─────────────────────────────────────────────────────────────────────
  describe("upload + distribution: static distribution preview in Overview", () => {
    function activateDistributionItem() {
      const card = screen.getByText("Визуализация распределения");
      fireEvent.click(card.closest("article")!);
    }

    it("renders the heading when upload + distribution is active", () => {
      renderNavigator();
      activateDistributionItem();
      // H3 «Обзор: Визуализация распределения» — заголовок окна Обзор из
      // TsAnalysisNavigator. Сама инфографика тоже содержит H3 «Визуализация
      // распределения». Поэтому минимум 2 совпадения.
      const headings = screen.getAllByRole("heading", {
        level: 3,
        name: /визуализация распределения/i,
      });
      expect(headings.length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT show the generic placeholder text for distribution item", () => {
      renderNavigator();
      activateDistributionItem();
      expect(screen.queryByText(/область графика\/таблицы\/блок-схемы/)).toBeNull();
    });

    it("renders the static dataset filename demo_energy_consumption.csv in Overview", () => {
      renderNavigator();
      activateDistributionItem();
      expect(
        screen.getAllByText(/demo_energy_consumption\.csv/i).length
      ).toBeGreaterThanOrEqual(1);
    });

    it("renders 3 recharts chart frames (scatter/histogram/kde)", () => {
      renderNavigator();
      activateDistributionItem();
      const c3 = getColumns()[2];
      const containers = c3.querySelectorAll(".recharts-responsive-container");
      expect(containers.length).toBe(3);
    });

    it("renders 8 descriptive statistics Metric badges", () => {
      renderNavigator();
      activateDistributionItem();
      // 8 метрик: Mean, Median, Std, Skewness, Kurtosis, Q1, Q3, IQR.
      expect(screen.getByText(/mean.*среднее/i)).toBeInTheDocument();
      expect(screen.getByText(/median.*медиана/i)).toBeInTheDocument();
      expect(screen.getByText(/std.*стандартное/i)).toBeInTheDocument();
      expect(screen.getByText(/skewness.*асимметрия/i)).toBeInTheDocument();
      expect(screen.getByText(/kurtosis.*эксцесс/i)).toBeInTheDocument();
      expect(screen.getByText(/q1.*1 квартиль/i)).toBeInTheDocument();
      expect(screen.getByText(/q3.*3 квартиль/i)).toBeInTheDocument();
      expect(screen.getByText(/iqr.*межквартильный/i)).toBeInTheDocument();
    });

    it("renders the distribution preview WITHOUT activeDataset (works if dataset is deleted)", () => {
      renderNavigator();
      activateDistributionItem();
      expect(
        screen.getAllByText(/consumption_mwh/i).length
      ).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText(/нет данных/i)).toBeNull();
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
