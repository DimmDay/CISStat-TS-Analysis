// packages/ui/components/NavigatorStructureConfirmPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» остановки
// «Подтверждение автоопределения» (id="structure_confirm") секции
// «Этапы модуля» остановки «Загрузка» на странице Навигатор.
//
// Контракт (задача 2026-08-30):
//   - Визуализация — статичная информационная блок-схема алгоритма
//     автоопределения структуры (3 параллельных детектора).
//   - Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       • apps/api/routers/session.py::get_structure_detection
//       • app/data/detectors.py::score_all_columns_as_date
//       • app/data/detectors.py::score_all_columns_as_entity_group
//       • app/data/detectors.py::detect_column_frequency
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии.
//
// Архитектурно — ближайший родственник UploadAutoPreviewPipeline
// (статичная Tailwind/CSS-блок-схема, role="img" + aria-label).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorStructureConfirmPreview } from "./NavigatorStructureConfirmPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorStructureConfirmPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorStructureConfirmPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Подтверждение автоопределения»", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Заголовок H3 над блок-схемой — повторяет имя остановки в Навигаторе.
    expect(
      screen.getByRole("heading", { level: 3, name: /подтверждение автоопределения/i })
    ).toBeInTheDocument();
  });

  it("renders all 3 detector lanes (date / entity / frequency)", () => {
    render(<NavigatorStructureConfirmPreview />);
    // 3 заголовка детекторов — по имени из бэкенд-контракта.
    expect(screen.getByText(/временная колонка/i)).toBeInTheDocument();
    expect(screen.getByText(/группирующая колонка/i)).toBeInTheDocument();
    expect(screen.getByText(/частота ряда/i)).toBeInTheDocument();
  });

  it("exposes the API endpoint name visible to the user", () => {
    render(<NavigatorStructureConfirmPreview />);
    // GET /dataset/structure-detection — реальный бэкенд-эндпоинт.
    expect(screen.getByText(/\/dataset\/structure-detection/i)).toBeInTheDocument();
  });

  it("renders date detector methods: keyword + regex + year range", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Из _score_column_as_date: TIME_KEYWORDS (рус/англ), DATE_PATTERNS,
    // диапазон 1800–2100 для year_only, unix_s/unix_ms для больших чисел.
    expect(screen.getByText(/ключевые слова/i)).toBeInTheDocument();
    expect(screen.getByText(/regex-паттерны/i)).toBeInTheDocument();
    expect(screen.getByText(/год\s*1800.*2100/i)).toBeInTheDocument();
  });

  it("renders entity detector criteria: dtype + nunique range", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Из score_all_columns_as_entity_group: object/string/category dtype
    // и 1 < nunique < 100.
    expect(screen.getByText(/object.*string.*category/i)).toBeInTheDocument();
    expect(screen.getByText(/1\s*<\s*nunique\s*<\s*100/i)).toBeInTheDocument();
  });

  it("renders frequency detector method: pd.infer_freq", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Из detect_column_frequency: pd.infer_freq на уникальных отсорти-
    // рованных датах выбранной date-колонки, минимум 3 уникальных даты.
    expect(screen.getByText(/pd\.infer_freq/i)).toBeInTheDocument();
    expect(screen.getByText(/3\+\s*уникальных\s*дат/i)).toBeInTheDocument();
  });

  it("renders the manual override note (user can correct)", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Контракт фронтенда: «определяются автоматически, можно поправить»
    // — пользователь может переопределить автоопределение вручную.
    expect(screen.getByText(/можно поправить/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorStructureConfirmPreview />);
    expect(screen.queryByText(/загрузка/i)).toBeNull();
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(container.firstChild).not.toBeNull();
  });

  it("does not make any network call (no fetch, no XMLHttpRequest)", () => {
    const originalFetch = global.fetch;
    const originalXHR = global.XMLHttpRequest;
    let fetchCalled = false;
    let xhrCreated = false;
    global.fetch = (() => {
      fetchCalled = true;
      throw new Error("NavigatorStructureConfirmPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorStructureConfirmPreview must not create XHR");
    };

    try {
      render(<NavigatorStructureConfirmPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorStructureConfirmPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorStructureConfirmPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("renders an arrow/separator indicating flow from detectors to result", () => {
    render(<NavigatorStructureConfirmPreview />);
    // Должна быть хотя бы одна стрелка (ChevronDown/ChevronRight/
    // ArrowDown/ArrowRight) — признак блок-схемы, а не плоского списка.
    // Ищем по role="img" с aria-label, содержащим "chevron" или "arrow".
    const arrows = document.querySelectorAll(
      '[aria-label*="chevron" i], [aria-label*="arrow" i]'
    );
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorStructureConfirmPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /автоопределение|структур|детектор/i
    );
  });
});
