// packages/ui/components/UploadAutoPreviewPipeline.test.tsx
//
// Тесты для UploadAutoPreviewPipeline — статичная информационная блок-схема
// «Пайплайн автопревью» для окна «Обзор» Навигатора (только при активной
// остановке «Загрузка» + пункте «Автопревью и типы колонок»).
//
// Проверяем:
//   - корневой role="img" + aria-label (a11y-контракт)
//   - рендерит все 7 основных шагов пайплайна (заголовки)
//   - рендерит расширяющую ноду classify_columns с 4 подтипами
//   - рендерит стрелки между шагами (chevron down)
//   - упоминание поддерживаемых форматов (.csv, .xlsx, .xls, .json)

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { UploadAutoPreviewPipeline, PIPELINE_STEPS } from "./UploadAutoPreviewPipeline";

describe("UploadAutoPreviewPipeline", () => {
  it("renders root with role=img and descriptive aria-label", () => {
    render(<UploadAutoPreviewPipeline />);
    const root = screen.getByRole("img", { name: /пайплайн автопревью/i });
    expect(root).toBeInTheDocument();
  });

  it("renders all main pipeline step titles", () => {
    render(<UploadAutoPreviewPipeline />);
    // 9 шагов: 7 из примера тимлида + parse_warnings + done.
    expect(PIPELINE_STEPS).toHaveLength(9);
    PIPELINE_STEPS.forEach((step) => {
      expect(screen.getByText(step.title)).toBeInTheDocument();
    });
  });

  it("renders subtitles with extra backend context", () => {
    render(<UploadAutoPreviewPipeline />);
    // Проверяем ключевые подзаголовки, отражающие реальный бэкенд:
    expect(screen.getByText(/engine='python', encoding='utf-8-sig'/i)).toBeInTheDocument();
    expect(screen.getByText(/pd\.read_csv/i)).toBeInTheDocument();
  });

  it("renders 4 classify_columns subtypes (numeric / categorical / datetime / text)", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText("numeric")).toBeInTheDocument();
    expect(screen.getByText("categorical")).toBeInTheDocument();
    expect(screen.getByText("datetime")).toBeInTheDocument();
    expect(screen.getByText("text")).toBeInTheDocument();
  });

  it("renders arrow separators between steps", () => {
    render(<UploadAutoPreviewPipeline />);
    // ChevronDown иконки как aria-label="chevron down"
    const chevrons = screen.getAllByLabelText("chevron down");
    // Между 7 шагами — минимум 6 стрелок (фактически больше: до classify,
    // внутри classify-блока, после)
    expect(chevrons.length).toBeGreaterThanOrEqual(6);
  });

  it("mentions all 4 supported file formats", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText(/\.csv/i)).toBeInTheDocument();
    expect(screen.getByText(/\.xlsx/i)).toBeInTheDocument();
    expect(screen.getByText(/\.xls\b/i)).toBeInTheDocument();
    expect(screen.getByText(/\.json/i)).toBeInTheDocument();
  });

  it("renders the final «Готово → SessionStore» node", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText(/Готово/i)).toBeInTheDocument();
    expect(screen.getByText(/SessionStore/i)).toBeInTheDocument();
  });

  it("renders the «Предупреждения парсинга» node (renamed from Парсинг-варнинги)", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText("Предупреждения парсинга")).toBeInTheDocument();
  });

  it("exports PIPELINE_STEPS as a stable array with documented ids", () => {
    const ids = PIPELINE_STEPS.map((s) => s.id);
    expect(ids).toEqual([
      "file",
      "detect_encoding",
      "parsing",
      "detect_types",
      "classify_columns",
      "count_missing",
      "count_unique",
      "parse_warnings",
      "done",
    ]);
    // 9 = 7 из примера тимлида + parse_warnings (Предупреждения парсинга)
    // + done (Готово → SessionStore). См. PIPELINE_STEPS в компоненте.
    expect(PIPELINE_STEPS).toHaveLength(9);
  });
});
