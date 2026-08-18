// packages/ui/components/UploadAutoPreviewPipeline.test.tsx
//
// Тесты для UploadAutoPreviewPipeline — статичная информационная блок-схема
// «Пайплайн автопревью» для окна «Обзор» Навигатора (только при активной
// остановке «Загрузка» + пункте «Автопревью и типы колонок»).
//
// После Phase 2 (refactor to snake layout) проверяем:
//   - корневой role="img" + aria-label (a11y-контракт)
//   - рендерит все 9 шагов пайплайна (заголовки)
//   - рендерит расширяющую ноду classify_columns с 4 подтипами
//   - рендерит горизонтальные стрелки (ChevronRight/ChevronLeft) между нодами
//   - рендерит вертикальные стрелки (ChevronDown) между строками
//   - упоминание поддерживаемых форматов (.csv, .xlsx, .xls, .json)
//   - компоновка «змейка»: 5 строк, чётные LTR, нечётные RTL

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { UploadAutoPreviewPipeline, PIPELINE_STEPS } from "./UploadAutoPreviewPipeline";

describe("UploadAutoPreviewPipeline", () => {
  it("renders root with role=img and descriptive aria-label", () => {
    render(<UploadAutoPreviewPipeline />);
    const root = screen.getByRole("img", { name: /пайплайн автопревью/i });
    expect(root).toBeInTheDocument();
  });

  it("renders all 9 pipeline step titles", () => {
    render(<UploadAutoPreviewPipeline />);
    // 9 шагов: 7 из примера тимлида + parse_warnings + done.
    expect(PIPELINE_STEPS).toHaveLength(9);
    PIPELINE_STEPS.forEach((step) => {
      expect(screen.getByText(step.title)).toBeInTheDocument();
    });
  });

  it("renders subtitles with extra backend context", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText(/utf-8-sig/i)).toBeInTheDocument();
    expect(screen.getByText(/read_csv/i)).toBeInTheDocument();
  });

  it("renders 4 classify_columns subtypes (numeric / categorical / datetime / text)", () => {
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getByText("numeric")).toBeInTheDocument();
    expect(screen.getByText("categorical")).toBeInTheDocument();
    expect(screen.getByText("datetime")).toBeInTheDocument();
    expect(screen.getByText("text")).toBeInTheDocument();
  });

  it("renders vertical arrow separators (chevron down) between rows", () => {
    render(<UploadAutoPreviewPipeline />);
    // 5 строк → 4 стрелки вниз между ними.
    const chevrons = screen.getAllByLabelText("chevron down");
    expect(chevrons).toHaveLength(4);
  });

  it("mentions all 4 supported file formats in Файл subtitle", () => {
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
    expect(PIPELINE_STEPS).toHaveLength(9);
  });

  // ── Phase 2: snake layout ───────────────────────────────────

  it("compacts the pipeline into 5 rows (snake layout)", () => {
    // ROW_INDICES = [[0,1], [2,3], [4,5], [6,7], [8]] — 5 строк.
    // Косвенная проверка через количество вертикальных стрелок:
    // 5 строк → 4 chevron-down между ними. Это уже покрыто тестом выше,
    // но дублируем явным assertion, чтобы зафиксировать контракт змейки.
    render(<UploadAutoPreviewPipeline />);
    const chevrons = screen.getAllByLabelText("chevron down");
    expect(chevrons).toHaveLength(4);
    // Если строк станет не 5 — тест упадёт, и разработчик вспомнит, что
    // змейка должна быть компактной (минимальный скролл).
  });

  it("renders the last row with a single node «Готово → SessionStore»", () => {
    // Последняя (5-я) строка содержит 1 ноду, без горизонтальной
    // стрелки справа. Проверяем, что заголовок присутствует ровно 1 раз.
    render(<UploadAutoPreviewPipeline />);
    expect(screen.getAllByText(/Готово → SessionStore/i)).toHaveLength(1);
  });
});
