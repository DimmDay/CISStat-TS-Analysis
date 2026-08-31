// packages/ui/components/NavigatorTechInfoPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» остановки
// «Техническая информация» (id="tech_info") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор.
//
// Контракт (задача 2026-08-31):
//   - Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     построения технической информации по каждой колонке датасета.
//   - Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       • apps/api/upload_common.py::_compute_column_info
//       • apps/api/schemas.py::ColumnInfoOut
//       • apps/api/upload_common.py::handle_upload (отдаёт в UploadResponse.columns_info)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (это и есть требование тимлида).
//
// Архитектурно — ближайший родственник NavigatorQualityTeaserPreview:
// статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorTechInfoPreview } from "./NavigatorTechInfoPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorTechInfoPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorTechInfoPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Техническая информация»", () => {
    render(<NavigatorTechInfoPreview />);
    // H3 заголовок над блок-схемой — повторяет имя остановки в Навигаторе.
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /техническая информация/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes the backend source name visible to the user", () => {
    render(<NavigatorTechInfoPreview />);
    // _compute_column_info — реальная бэкенд-функция.
    expect(screen.getByText(/_compute_column_info/i)).toBeInTheDocument();
  });

  it("renders all 4 type_icon lanes (datetime / numeric / categorical / text)", () => {
    render(<NavigatorTechInfoPreview />);
    // Из _compute_column_info: 4 ветки type_icon по dtype.
    // Каждое имя встречается несколько раз (лейбл дорожки + финальная
    // подпись про if/elif chain) — используем getAllByText с >= 1.
    expect(screen.getAllByText(/datetime/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/numeric/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/categorical/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/\btext\b/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders dtype detection criteria: is_datetime64 / is_numeric / nunique", () => {
    render(<NavigatorTechInfoPreview />);
    // Из _compute_column_info: pd.api.types.is_datetime64_any_dtype,
    // pd.api.types.is_numeric_dtype, nunique(dropna=True) <= 50.
    // 'nunique' встречается в нескольких местах (categorical source +
    // unique метрика) — getAllByText.
    expect(screen.getAllByText(/is_datetime64/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/is_numeric/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/nunique/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders 3 per-column metrics: non_null / nulls / unique", () => {
    render(<NavigatorTechInfoPreview />);
    // Из ColumnInfoOut: 3 метрики + name + dtype.
    // Имена встречаются несколько раз (id метрики + финальная подпись).
    expect(screen.getAllByText(/non_null/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/nulls/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/unique/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the categorical threshold: nunique ≤ 50", () => {
    render(<NavigatorTechInfoPreview />);
    // Из _compute_column_info: elif series.nunique(dropna=True) <= 50.
    expect(screen.getByText(/≤\s*50/i)).toBeInTheDocument();
  });

  it("renders the arrow/separator indicating flow from detector to result", () => {
    render(<NavigatorTechInfoPreview />);
    // Должна быть хотя бы одна стрелка (ChevronDown) — признак блок-схемы.
    const arrows = document.querySelectorAll('[aria-label*="chevron" i]');
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("renders the result block: ColumnInfoOut / UploadResponse.columns_info", () => {
    render(<NavigatorTechInfoPreview />);
    // Результат — массив ColumnInfoOut внутри UploadResponse.columns_info.
    expect(screen.getByText(/ColumnInfoOut/i)).toBeInTheDocument();
    expect(screen.getByText(/columns_info/i)).toBeInTheDocument();
  });

  it("renders the UI table preview note: 5 columns in Загрузка table", () => {
    render(<NavigatorTechInfoPreview />);
    // В TsAnalysisUpload.tsx:1052-1076 таблица с 5 колонками:
    // Колонка / Тип / Не пусто / Пропуски / Уникальных.
    // 'Колонка' встречается в финальной подписи ('для каждой колонки') +
    // в подписи таблицы — getAllByText.
    expect(screen.getAllByText(/Колонка/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Не пусто/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Пропуски/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Уникальных/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorTechInfoPreview />);
    // 'нет данных' — empty-state маркер, его быть не должно.
    // 'загрузка' НЕ проверяем: слово встречается в легитимном контексте
    // («вкладке Загрузка» в финальной подписи), это не empty-state.
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
      throw new Error("NavigatorTechInfoPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorTechInfoPreview must not create XHR");
    };

    try {
      render(<NavigatorTechInfoPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorTechInfoPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorTechInfoPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorTechInfoPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /техническая информация|колонк|dtype|тип/i
    );
  });
});
