// packages/ui/components/NavigatorFormatsVolumePreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Форматы и объём»
// (id="formats") секции «Этапы модуля» остановки «Загрузка» на странице
// Навигатор (Task NAVDET-4).
//
// Контракт:
//   - Визуализация — статичная информационная блок-схема приёма файла:
//     форматы (.csv/.xls/.xlsx/.json), проверка типа и размера,
//     автоопределение формата по расширению, 3 дорожки парсинга
//     (CSV / Excel / JSON), ошибки, результат (UploadResponse).
//   - Схема основана на РЕАЛЬНОЙ логике:
//       • packages/ui/components/TsAnalysisUpload.tsx (react-dropzone:
//         один файл, accept, maxSize, тексты отказов)
//       • app/data/file_loader.py::read_uploaded_file (расширение →
//         парсер CSV/Excel/JSON, тексты ошибок)
//       • apps/api/upload_common.py::handle_upload (POST /v1/internal/upload,
//         UploadResponse → SessionStore)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии.
//
// Архитектурно — родственник NavigatorStructureConfirmPreview
// (статичная Tailwind/CSS-блок-схема, role="img" + aria-label).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorFormatsVolumePreview } from "./NavigatorFormatsVolumePreview";

describe("NavigatorFormatsVolumePreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт.
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorFormatsVolumePreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Форматы и объём»", () => {
    render(<NavigatorFormatsVolumePreview />);
    expect(
      screen.getByRole("heading", { level: 3, name: /форматы и объём/i })
    ).toBeInTheDocument();
  });

  it("exposes the API endpoint name visible to the user", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Реальный бэкенд-эндпоинт приёма файла.
    expect(screen.getByText(/\/v1\/internal\/upload/i)).toBeInTheDocument();
  });

  it("renders drag-and-drop as the input method (single file)", () => {
    render(<NavigatorFormatsVolumePreview />);
    expect(screen.getByText(/drag-and-drop/i)).toBeInTheDocument();
  });

  it("renders all 4 accepted formats as separate badges (.csv .xls .xlsx .json)", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Каждый формат — отдельный узел (бейдж): точные совпадения,
    // .xls не матчится с .xlsx.
    expect(screen.getByText(".csv")).toBeInTheDocument();
    expect(screen.getByText(".xls")).toBeInTheDocument();
    expect(screen.getByText(".xlsx")).toBeInTheDocument();
    expect(screen.getByText(".json")).toBeInTheDocument();
  });

  it("renders the REAL prod size limit (4MB) with the proxy rationale", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Лимит dropzone на проде — 4MB (Vercel proxy ~4.5MB body);
    // текст встречается в узле лимита И в тексте отказа («макс. 4MB»),
    // поэтому getAllByText. Исторические 50MB — в примечании.
    expect(screen.getAllByText(/4MB/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/50MB/i)).toBeInTheDocument();
  });

  it("renders front-end rejection messages of the dropzone", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Тексты TsAnalysisUpload.tsx (file-too-large / file-invalid-type).
    expect(screen.getByText(/Файл слишком большой/i)).toBeInTheDocument();
    expect(screen.getByText(/Неподдерживаемый формат/i)).toBeInTheDocument();
  });

  it("renders format auto-detection by file extension (no dot → csv)", () => {
    render(<NavigatorFormatsVolumePreview />);
    // read_uploaded_file: расширение = после последней точки (lowercase);
    // файла без точки → дефолт csv.
    expect(screen.getByText(/последн.*точк/i)).toBeInTheDocument();
    expect(screen.getByText(/нет точки → csv/i)).toBeInTheDocument();
  });

  it("renders the CSV lane criteria: utf-8-sig, auto separator, auto header, skip", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Из read_uploaded_file: encoding utf-8-sig; разделители , ; \t |;
    // headerless → col_0…; on_bad_lines='skip'.
    expect(screen.getByText(/utf-8-sig/i)).toBeInTheDocument();
    expect(screen.getByText(/разделитель/i)).toBeInTheDocument();
    expect(screen.getByText(/col_0/i)).toBeInTheDocument();
    expect(screen.getByText(/skip/i)).toBeInTheDocument();
  });

  it("renders the Excel lane criteria: pd.read_excel, numeric col names → col_i", () => {
    render(<NavigatorFormatsVolumePreview />);
    expect(screen.getByText(/read_excel/i)).toBeInTheDocument();
    expect(screen.getByText(/col_i/i)).toBeInTheDocument();
  });

  it("renders the JSON lane criteria: JSON-stat 2.0, json_normalize", () => {
    render(<NavigatorFormatsVolumePreview />);
    expect(screen.getByText(/JSON-stat 2\.0/i)).toBeInTheDocument();
    expect(screen.getByText(/json_normalize/i)).toBeInTheDocument();
  });

  it("renders backend error messages of read_uploaded_file", () => {
    render(<NavigatorFormatsVolumePreview />);
    // Тексты ошибок из file_loader.py / upload_common.py.
    expect(screen.getByText(/Файл пуст или не содержит данных/i)).toBeInTheDocument();
    expect(screen.getByText(/не поддерживается/i)).toBeInTheDocument();
    expect(screen.getByText(/не содержит табличные данные/i)).toBeInTheDocument();
  });

  it("renders the result block: UploadResponse → SessionStore", () => {
    render(<NavigatorFormatsVolumePreview />);
    // handle_upload возвращает UploadResponse (preview, columns_info,
    // quality, parse_warnings) и кладёт датасет в SessionStore.
    expect(screen.getByText(/UploadResponse/i)).toBeInTheDocument();
    expect(screen.getByText(/columns_info/i)).toBeInTheDocument();
    expect(screen.getByText(/parse_warnings/i)).toBeInTheDocument();
    expect(screen.getByText(/SessionStore/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorFormatsVolumePreview />);
    expect(screen.queryByText(/загрузка\.\.\./i)).toBeNull();
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
      throw new Error("NavigatorFormatsVolumePreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorFormatsVolumePreview must not create XHR");
    };

    try {
      render(<NavigatorFormatsVolumePreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorFormatsVolumePreview />);
    const text1 = c1.textContent;
    r1(<NavigatorFormatsVolumePreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("renders arrows/indicators of flow (block-scheme, not flat list)", () => {
    render(<NavigatorFormatsVolumePreview />);
    const arrows = document.querySelectorAll(
      '[aria-label*="chevron" i], [aria-label*="arrow" i]'
    );
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorFormatsVolumePreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /форматы|формат|файл/i
    );
  });
});
