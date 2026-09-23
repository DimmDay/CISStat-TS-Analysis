// packages/ui/components/NavigatorValidationRangesPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Диапазоны значений»
// (id="ranges", третий пункт) секции «Этапы модуля» остановки «Валидация»
// на странице Навигатор (Task NAVDET-RANGES, 2026-09-22).
//
// Контракт:
//   - Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Диапазоны значений» (третий из 10 критериев Data
//     Quality).
//   - Алгоритм основан на РЕАЛЬНОЙ логике:
//       • validation/rule_resolver.py::resolve_validation_rules
//         (приоритет эталона: сессия overrides > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; _deep_merge(_deep_merge(system, template),
//         overrides); CHECK_SECTIONS["ranges"] = "ranges")
//       • validation/engine.py::auto_generate_rules — системный вывод
//         min/max ТОЛЬКО для числовых колонок и ТОЛЬКО по семантике
//         ИМЕНИ: price/цена/стоимость → min 0 (положительная цена),
//         year/год → 1900–2100 (разумный год), percent/%/доля → 0–100;
//         неизвестной числовой семантике диапазон НЕ назначается из
//         фактических min/max — это гарантировало бы ложное прохождение
//       • rules/default_rules.yaml::ranges — шаблонные правила по
//         keywords: price/cost ≥ 0, pct/percent 0–100, rate/доля/share
//         0–1, moisture 0–100, sugar 0–30, age ≥ 0
//       • validation/engine.py::range_invalid_mask
//         (series.notna() & (series < min) — ниже минимума; series.notna()
//         & (series > max) — выше максимума; min и max независимы —
//         правило может задавать только одну границу; пропуски
//         проверяются отдельно и не считаются нарушениями диапазона)
//       • validation/engine.py::profile_ranges (только числовые колонки;
//         правило подбирается по keywords в имени; правило без min и max
//         пропускается; total/valid/invalid_count, invalid_pct,
//         actual_min/actual_max против min_allowed/max_allowed,
//         invalid_examples — до 5 уникальных; ПОЛНЫЙ профиль применимых
//         правил — включая колонки с 0 нарушений)
//       • validation/engine.py::validate_ranges (строка результата
//         ТОЛЬКО для колонок с нарушениями: Правило «min ≤ x ≤ max»
//         с −∞/∞ для отсутствующей границы, Нарушений, % брака,
//         Min факт, Max факт; rule_bounds заполняется для КАЖДОЙ matched
//         колонки — надёжный сигнал применимости)
//       • validation/engine.py::_run_all_checks::_ranges (scope="column"
//         — при выбранном признаке: признак не в bounds → pending
//         (честный сигнал «правила нет»), matched → статус по нарушениям
//         признака; без признака: bounds пуст → pending, items из raw,
//         count = Σ; отличие от «Типов данных», где scope="dataset")
//       • apps/api/routers/session.py::get_dataset_range_profile
//         (GET /v1/session/dataset/range-profile — профиль применимых
//         min/max-правил + rule_source) и correct_dataset_ranges
//         (POST /v1/session/dataset/range-corrections — preview/apply;
//         маска и границы всегда из resolved rules сервера, не из
//         клиента; preview на глубокой копии, apply — атомарная подмена
//         датасета; для колонки без активного правила — ошибка 422)
//       • apps/api/range_correction.py::preview_range_corrections
//         (5 стратегий: clip — кэпирование до границ; median — медиана
//         только корректных значений (если нарушений нет — колонка не
//         меняется; если валидных нет — ошибка); replace_null —
//         нарушения → NA; drop_rows — удаление строк по ОБЪЕДИНЁННОЙ
//         маске всех выбранных колонок; flag — булева колонка
//         <имя>_range_valid без изменения значений)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других Navigator*Preview).
//
// Архитектурно — родственник NavigatorValidationFormatsPreview:
// статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts, без fetch.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorValidationRangesPreview } from "./NavigatorValidationRangesPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationRangesPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    const { container } = render(<NavigatorValidationRangesPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Диапазоны значений: Валидация»", () => {
    render(<NavigatorValidationRangesPreview />);
    // H3 заголовок шапки блок-схемы — модуль: остановка.
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /диапазоны значений/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes the API endpoints visible to the user", () => {
    render(<NavigatorValidationRangesPreview />);
    // Фронт-контракт чека: GET /v1/session/dataset/validate (общий для
    // 10 чеков) + профиль/исправление диапазонов (range-profile /
    // range-corrections) в финальном блоке мастера.
    expect(
      screen.getAllByText(/session\/dataset\/validate/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/range-profile/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/range-corrections/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the rule resolver with the 3-source priority (session > template > system)", () => {
    render(<NavigatorValidationRangesPreview />);
    // validation/rule_resolver.py::resolve_validation_rules:
    // _deep_merge(_deep_merge(system, template), overrides) — верхний
    // слой выигрывает. Термины легитимно повторяются — getAllByText.
    expect(screen.getAllByText(/resolve_validation_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/сессия/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/система/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the deep-merge resolution order and the template file", () => {
    render(<NavigatorValidationRangesPreview />);
    // Механика резолва: глубокое слияние трёх слоёв; шаблон по умолчанию
    // — default_rules.yaml.
    expect(screen.getAllByText(/_deep_merge/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/default_rules\.yaml/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the system inference lanes by column-name semantics (price / year / percent)", () => {
    render(<NavigatorValidationRangesPreview />);
    // validation/engine.py::auto_generate_rules: только числовые колонки;
    // min/max по семантике имени.
    expect(screen.getAllByText(/auto_generate_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/цена|price/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/год|year/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/процент|percent/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the system inference bounds (0 / 1900–2100 / 0–100)", () => {
    render(<NavigatorValidationRangesPreview />);
    // Системные границы: положительная цена (min 0), разумный год
    // (1900–2100), процент (0–100).
    expect(screen.getAllByText(/1900/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/2100/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/0–100|0-100/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the template keyword lanes (rate 0–1, moisture, sugar, age)", () => {
    render(<NavigatorValidationRangesPreview />);
    // rules/default_rules.yaml::ranges: правило = keywords + min/max;
    // representative lanes шаблона.
    expect(screen.getAllByText(/rate|доля|share/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/влажность|moisture/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/sugar|сахар/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/age|возраст/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the numeric-only honesty (no min/max inferred from observed data)", () => {
    render(<NavigatorValidationRangesPreview />);
    // Честность системного слоя: неизвестной числовой семантике диапазон
    // не назначается из фактических min/max — это гарантировало бы
    // ложное прохождение (каждое наблюдаемое значение валидно по
    // построению).
    expect(screen.getAllByText(/из фактических/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/ложное прохождение/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the invalid-mask mechanics (below min / above max / independent bounds / NaN honesty)", () => {
    render(<NavigatorValidationRangesPreview />);
    // validation/engine.py::range_invalid_mask: единая маска нарушений;
    // пропуски проверяются отдельно и не считаются нарушениями диапазона.
    expect(screen.getAllByText(/range_invalid_mask/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/ниже минимума/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/выше максимума/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/независим/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/пропуски проверяются отдельно/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the profile mechanics (profile_ranges, actual min/max, invalid_examples, 0 violations included)", () => {
    render(<NavigatorValidationRangesPreview />);
    // validation/engine.py::profile_ranges: полный профиль применимых
    // правил ВКЛЮЧАЯ 0 нарушений; actual_min/actual_max — факт против
    // min_allowed/max_allowed; invalid_examples — до 5 уникальных.
    expect(screen.getAllByText(/profile_ranges/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/actual_min|Min факт/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/actual_max|Max факт/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/invalid_examples/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/включая 0 нарушений|включая колонки с 0/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the keyword matching for rules (keywords in column name)", () => {
    render(<NavigatorValidationRangesPreview />);
    // _range_rule_for_column + profile_ranges: правило подбирается по
    // keywords в имени колонки.
    expect(screen.getAllByText(/keywords/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the run contract (results only for violating columns, rule string min ≤ x ≤ max)", () => {
    render(<NavigatorValidationRangesPreview />);
    // validate_ranges: строка результата ТОЛЬКО для колонок с
    // нарушениями; правило печатается как «min ≤ x ≤ max» (с −∞/∞ для
    // отсутствующей границы).
    expect(screen.getAllByText(/validate_ranges/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/только для колонок с нарушениями/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/min ≤ x ≤ max/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/∞/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the bounds applicability contract (rule_bounds for EVERY matched column)", () => {
    render(<NavigatorValidationRangesPreview />);
    // _ranges: bounds (не raw) — надёжный сигнал применимости:
    // rule_bounds заполняется для каждой matched колонки, тогда как raw
    // содержит только нарушающие — по одному raw нельзя отличить
    // «0 нарушений» от «правила нет».
    expect(screen.getAllByText(/rule_bounds|bounds/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/каждой matched колонки/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the aggregation contract and the column scope (differs from data_types)", () => {
    render(<NavigatorValidationRangesPreview />);
    // scope="column" — чек скоупится до выбранного признака; отличие от
    // «Типов данных» (scope="dataset").
    expect(screen.getAllByText(/scope/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/column/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/dataset/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/скоупится/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the pending honesty (feature without rule → pending)", () => {
    render(<NavigatorValidationRangesPreview />);
    // _ranges при выбранном признаке: признак не в bounds → pending —
    // честный сигнал «правила нет», а не «нарушений нет».
    expect(screen.getAllByText(/pending/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the three check statuses (done / warning / pending)", () => {
    render(<NavigatorValidationRangesPreview />);
    // _status: count None → pending; 0 → done; >0 → warning.
    expect(screen.getAllByText(/^done$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^warning$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^pending$/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the correction master with 5 strategies", () => {
    render(<NavigatorValidationRangesPreview />);
    // «Мастер исправления диапазонов» (ValidationRangePipeline) →
    // 5 стратегий apps/api/range_correction.py.
    expect(screen.getAllByText(/Мастер исправления диапазонов/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^clip$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^median$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^replace_null$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^drop_rows$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^flag$/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the clip strategy contract (below min → min, above max → max)", () => {
    render(<NavigatorValidationRangesPreview />);
    // clip: значения ниже min заменяются на min, выше max — на max.
    expect(screen.getAllByText(/ниже min/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/выше max/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the median strategy honesty (median of VALID values only)", () => {
    render(<NavigatorValidationRangesPreview />);
    // median: медиана рассчитывается только по значениям, уже
    // находящимся в допустимом диапазоне.
    expect(screen.getAllByText(/медиан/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/только по значениям|корректных|валидных/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the drop_rows strategy contract (union mask over selected columns)", () => {
    render(<NavigatorValidationRangesPreview />);
    // drop_rows: удаляется ОБЪЕДИНЕНИЕ строк, нарушающих любое из
    // отмеченных правил.
    expect(screen.getAllByText(/объедин/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the flag strategy contract (added <column>_range_valid column)", () => {
    render(<NavigatorValidationRangesPreview />);
    // Стратегия flag добавляет булеву колонку <имя>_range_valid без
    // изменения значений.
    expect(screen.getAllByText(/_range_valid/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/без изменения значений/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the server-side rules guarantee (bounds from server, not client) and atomicity", () => {
    render(<NavigatorValidationRangesPreview />);
    // correct_dataset_ranges: маска и границы всегда из resolved rules,
    // а не из клиента; preview на глубокой копии, apply — атомарная
    // подмена датасета.
    expect(screen.getAllByText(/не из клиента/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/атомарн/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the no-rule error honesty (correction requires an active rule)", () => {
    render(<NavigatorValidationRangesPreview />);
    // preview_range_corrections: для колонки без активного правила
    // диапазона исправление невозможно (ошибка 422).
    expect(screen.getAllByText(/нет активного правила/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the criteria position caption (third of 10 Data Quality criteria)", () => {
    render(<NavigatorValidationRangesPreview />);
    // «Диапазоны значений» — третий из 10 критериев Data Quality
    // (DAMA DMBOK) вкладки «Валидация».
    expect(screen.getAllByText(/DAMA DMBOK/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/третий из 10/i).length).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// a11y и целостность блок-схемы
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationRangesPreview — a11y and integrity", () => {
  it("exposes the whole flowchart as a single role=img with a full aria-label", () => {
    render(<NavigatorValidationRangesPreview />);
    // Скринридер читает блок-схему как одно изображение; aria-label
    // описывает всю цепочку — от эталона правил до мастера исправлений.
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("aria-label");
    const label = img.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/Диапазоны значений/);
    expect(label).toMatch(/resolve_validation_rules|эталон/i);
    expect(label).toMatch(/range_invalid_mask|маска нарушений/i);
    expect(label).toMatch(/scope/);
    expect(label).toMatch(/Мастер исправления диапазонов/i);
  });

  it("renders the arrow chain between blocks (visual flow)", () => {
    render(<NavigatorValidationRangesPreview />);
    // Стрелки между блоками — ChevronDown с aria-label "chevron down"
    // (единый паттерн с NavigatorValidationFormatsPreview). Вложенные
    // роли внутри корневого role="img" недоступны в ролевом дереве,
    // поэтому ищем по aria-label через querySelectorAll.
    const arrows = document.querySelectorAll('[aria-label*="chevron" i]');
    expect(arrows.length).toBeGreaterThanOrEqual(4);
  });

  it("does NOT fetch anything (static infographic, network-independent)", () => {
    // Паттерн других Navigator*Preview: без fetch/XHR — схема статична.
    // Заглушки подставляются вручную: global.fetch может отсутствовать
    // в jsdom-окружении, spyOn на undefined падает.
    const originalFetch = global.fetch;
    const originalXHR = global.XMLHttpRequest;
    let fetchCalled = false;
    let xhrCreated = false;
    global.fetch = (() => {
      fetchCalled = true;
      throw new Error("NavigatorValidationRangesPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorValidationRangesPreview must not create XHR");
    };

    try {
      render(<NavigatorValidationRangesPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("does NOT render an empty-state placeholder (no dataset wording)", () => {
    render(<NavigatorValidationRangesPreview />);
    // Схема не зависит от датасета — никаких «нет данных»/empty-state.
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(screen.queryByText(/активный датасет/i)).toBeNull();
  });
});
