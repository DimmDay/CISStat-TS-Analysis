// packages/ui/components/NavigatorValidationDataTypesPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Типы данных»
// (id="data_types", первый пункт) секции «Этапы модуля» остановки
// «Валидация» на странице Навигатор (Task NAVDET-DATATYPES, 2026-09-22).
//
// Контракт:
//   - Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Типы данных» (первый из 10 критериев Data Quality).
//   - Алгоритм основан на РЕАЛЬНОЙ логике:
//       • validation/rule_resolver.py::resolve_validation_rules
//         (приоритет эталона: сессия type_schema > шаблон YAML >
//         системный вывод; CHECK_SECTIONS["data_types"]="schema")
//       • validation/engine.py::infer_system_type_schema
//         (безопасный эталон: dtype + приводимость значений +
//         семантика названия; mixed Price=[10,20,"ошибка"] остаётся
//         числовой и ЛОВИТ ошибку)
//       • validation/engine.py::build_pandera_schema
//         (dtype_map → pa.Int64/Float64/String/Bool/DateTime; Check.*;
//         coerce=True; strict=False)
//       • validation/engine.py::validate_dataframe
//         (schema.validate(df, lazy=True) → SchemaErrors →
//         failure_cases.groupby("column") → schema_errors_by_column)
//       • validation/engine.py::_run_all_checks::_data_types
//         (нет schema.columns → pending; count=Σ; items=[{label: колонка}];
//         done(0)/warning(>0); scope="dataset" — не скоупится)
//       • apps/api/routers/session.py::get_dataset_validate
//         (GET /v1/session/dataset/validate — фронт-контракт)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других Navigator*Preview).
//
// Архитектурно — родственник NavigatorTechInfoPreview / NavigatorPassportPreview:
// статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorValidationDataTypesPreview } from "./NavigatorValidationDataTypesPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationDataTypesPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    const { container } = render(<NavigatorValidationDataTypesPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Типы данных: Валидация»", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // H3 заголовок шапки блок-схемы — модуль: остановка.
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /типы данных/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes the API endpoint visible to the user", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Фронт-контракт чека: GET /v1/session/dataset/validate.
    expect(
      screen.getAllByText(/session\/dataset\/validate/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the rule resolver with the 3-source priority (session > template > system)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // validation/rule_resolver.py::resolve_validation_rules.
    // Термины «сессия/шаблон/система» легитимно повторяются (лейбл
    // источника + подписи) — getAllByText.
    expect(screen.getAllByText(/resolve_validation_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/сессия/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/система/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the system type inference lanes (boolean / integer / float / datetime / string)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // validation/engine.py::infer_system_type_schema — if/elif chain
    // по dtype; ожидаемые типы: boolean, integer, float, datetime, string.
    // Каждое имя встречается несколько раз (дорожка + dtype_map pandera) —
    // getAllByText с >= 1.
    expect(screen.getAllByText(/boolean/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/integer/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/float/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/datetime/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/string/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the object-column coerce criteria with numeric thresholds (0.5 / 0.9 / 0.8)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Из infer_system_type_schema: приводимость object-колонок через
    // pd.to_numeric(errors="coerce"); пороги: год ≥0.5, numeric-имя ≥0.5,
    // безымянная числовость ≥0.9, дата ≥0.8. Порог 0.5 встречается
    // дважды (год + имена числовых) — getAllByText.
    expect(screen.getAllByText(/to_numeric/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/≥\s*0\.5/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/≥\s*0\.9/)).toBeInTheDocument();
    expect(screen.getByText(/≥\s*0\.8/)).toBeInTheDocument();
  });

  it("renders the mixed-column honesty note (Price=[10, 20, «ошибка»])", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Смысловой якорь алгоритма: смешанная колонка НЕ объявляется
    // строковой целиком — остаётся числовой и ловит ошибку. «Price» и
    // «ошибка» встречаются и в списке семантических имён (price/цена) —
    // getAllByText.
    expect(screen.getAllByText(/ошибка/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Price/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the pandera schema block: dtype_map + coerce + strict=False", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // validation/engine.py::build_pandera_schema (видимый код в шапке
    // блока). «coerce»/«strict» встречаются в нескольких местах
    // (Column(..., coerce=True) + подпись схемы) — getAllByText.
    expect(screen.getAllByText(/build_pandera_schema/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Int64/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Float64/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/coerce/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/strict/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the pandera checks (notna / in_range / isin / unique / str_matches)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Из build_pandera_schema: nullable→Check.notna, min/max→in_range,
    // allowed_values→isin, unique→Check.unique, pattern→str_matches.
    expect(screen.getAllByText(/notna/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/in_range/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/isin/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/str_matches/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the validation run + failure aggregation (lazy=True, failure_cases, groupby)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // validation/engine.py::validate_dataframe — SchemaErrors →
    // failure_cases → groupby("column") → schema_errors_by_column.
    expect(screen.getAllByText(/lazy/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/failure_cases/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/schema_errors_by_column/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the 3 statuses: done (0 нарушений) / warning (>0) / pending (нет схемы)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Из _run_all_checks::_data_types: _status(count) + pending без
    // schema.columns.
    expect(screen.getByText(/done/i)).toBeInTheDocument();
    expect(screen.getByText(/warning/i)).toBeInTheDocument();
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
  });

  it("renders the dataset-wide scope note (не скоупится до одной колонки)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Из докстринга _run_all_checks: data_types — dataset-wide,
    // scope="dataset".
    expect(screen.getAllByText(/dataset/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the UI fixing path: «Мастер исправления типов» (type_schema override)", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Фронт TsAnalysisValidation.tsx:425 — «Мастер исправления типов»;
    // исправление уходит в type_schema сессии (coerce=True).
    expect(screen.getAllByText(/Мастер исправления типов/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the arrow/separator indicating flow through the schema", () => {
    render(<NavigatorValidationDataTypesPreview />);
    // Должна быть хотя бы одна стрелка (ChevronDown) — признак блок-схемы.
    const arrows = document.querySelectorAll('[aria-label*="chevron" i]');
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorValidationDataTypesPreview />);
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
      throw new Error("NavigatorValidationDataTypesPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorValidationDataTypesPreview must not create XHR");
    };

    try {
      render(<NavigatorValidationDataTypesPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorValidationDataTypesPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorValidationDataTypesPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorValidationDataTypesPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /типы данных|эталон|pandera|схем/i
    );
  });
});
