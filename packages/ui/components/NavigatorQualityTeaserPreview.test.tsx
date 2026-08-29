// packages/ui/components/NavigatorQualityTeaserPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» остановки «Teaser качества»
// (id="quality_teaser") секции «Этапы модуля» остановки «Загрузка» на
// странице Навигатор.
//
// Контракт (задача 2026-08-30):
//   - Визуализация — статичная информационная блок-схема алгоритма
//     подсчёта 4 счётчиков качества (cols_with_missing / cols_with_outliers
//     / rows_total / duplicates) + 2 списка колонок.
//   - Алгоритм основан на РЕАЛЬНОЙ бэкенд-логике:
//       • apps/api/upload_common.py::_compute_quality_teaser
//       • apps/api/schemas.py::QualityTeaserOut
//       • apps/api/upload_common.py::handle_upload (отдаёт в UploadResponse.quality)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии.
//
// Архитектурно — ближайший родственник NavigatorStructureConfirmPreview
// (Task 65): статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorQualityTeaserPreview } from "./NavigatorQualityTeaserPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorQualityTeaserPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorQualityTeaserPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Teaser качества»", () => {
    render(<NavigatorQualityTeaserPreview />);
    expect(
      screen.getByRole("heading", { level: 3, name: /teaser качества/i })
    ).toBeInTheDocument();
  });

  it("renders all 4 counter cards (missing / outliers / rows / duplicates)", () => {
    render(<NavigatorQualityTeaserPreview />);
    // 4 счётчика из QualityTeaserOut: cols_with_missing, cols_with_outliers,
    // rows_total, duplicates. Лейблы — человекочитаемые (как в TsAnalysisUpload.tsx).
    expect(screen.getByText(/колонок с пропусками/i)).toBeInTheDocument();
    expect(screen.getByText(/колонок с выбросами/i)).toBeInTheDocument();
    expect(screen.getByText(/всего строк/i)).toBeInTheDocument();
    expect(screen.getByText(/дубликатов/i)).toBeInTheDocument();
  });

  it("renders the backend source name visible to the user", () => {
    render(<NavigatorQualityTeaserPreview />);
    // _compute_quality_teaser — реальная функция из upload_common.py.
    expect(screen.getByText(/_compute_quality_teaser/i)).toBeInTheDocument();
  });

  it("renders the IQR method description for outlier detection", () => {
    render(<NavigatorQualityTeaserPreview />);
    // Из _compute_quality_teaser: Q1, Q3, IQR = Q3-Q1, границы
    // Q1-1.5*IQR / Q3+1.5*IQR, требуются >=4 значений. «Q1, Q3, IQR»
    // встречается в исходном коде И в методе — используем getAllByText.
    const iqrMatches = screen.getAllByText(/Q1.*Q3.*IQR/i);
    expect(iqrMatches.length).toBeGreaterThanOrEqual(1);
    // «1.5×IQR» — в source-коде дорожки outliers.
    expect(screen.getAllByText(/1\.5.*IQR/i).length).toBeGreaterThanOrEqual(1);
    // «≥4 значений» — в методе описания (вне source-кода). В компоненте
    // используется символ ≥ (U+2265), а не ASCII «>=» — поддерживаем оба.
    expect(screen.getByText(/[≥>]=?\s*4\s*значений/i)).toBeInTheDocument();
  });

  it("renders the duplicates detection method (df.duplicated)", () => {
    render(<NavigatorQualityTeaserPreview />);
    expect(screen.getByText(/df\.duplicated/i)).toBeInTheDocument();
  });

  it("renders the missing detection method (isna().any())", () => {
    render(<NavigatorQualityTeaserPreview />);
    expect(screen.getByText(/isna\(\)\.any\(\)/i)).toBeInTheDocument();
  });

  it("renders the 'where it lives' note (counters, not full analysis)", () => {
    render(<NavigatorQualityTeaserPreview />);
    // Контракт фронтенда (TsAnalysisUpload.tsx::Stop quality): «Только
    // счётчики — содержательный разбор проблем качества живёт в «Валидации»».
    // «только счётчики» и «валидаци» встречаются в нескольких местах
    // (финальный блок + подпись) — используем getAllByText.
    expect(screen.getAllByText(/только счётчики/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/валидаци/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the response contract name QualityTeaserOut", () => {
    render(<NavigatorQualityTeaserPreview />);
    // Схема ответа из apps/api/schemas.py::QualityTeaserOut.
    expect(screen.getByText(/QualityTeaserOut/i)).toBeInTheDocument();
  });

  it("renders the integration point: UploadResponse.quality", () => {
    render(<NavigatorQualityTeaserPreview />);
    // Счётчики отдаются ВНУТРИ ответа /upload, не отдельным эндпоинтом.
    expect(screen.getByText(/UploadResponse\.quality/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorQualityTeaserPreview />);
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
      throw new Error("NavigatorQualityTeaserPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorQualityTeaserPreview must not create XHR");
    };

    try {
      render(<NavigatorQualityTeaserPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorQualityTeaserPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorQualityTeaserPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("renders at least one arrow/separator (block-diagram, not flat list)", () => {
    render(<NavigatorQualityTeaserPreview />);
    const arrows = document.querySelectorAll(
      '[aria-label*="chevron" i], [aria-label*="arrow" i]'
    );
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorQualityTeaserPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /качеств|teaser|счётчик/i
    );
  });

  it("renders the warning-state logic (warning if any counter > 0)", () => {
    render(<NavigatorQualityTeaserPreview />);
    // Из TsAnalysisUpload.tsx:736-742: статус warning, если
    // cols_with_missing > 0 OR cols_with_outliers > 0 OR duplicates > 0,
    // иначе done. rows_total в статусе не участвует.
    expect(screen.getByText(/warning.*если.*>\s*0/i)).toBeInTheDocument();
  });
});
