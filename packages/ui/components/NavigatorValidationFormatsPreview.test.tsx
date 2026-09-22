// packages/ui/components/NavigatorValidationFormatsPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Форматы и шаблоны»
// (id="formats", второй пункт) секции «Этапы модуля» остановки «Валидация»
// на странице Навигатор (Task NAVDET-FORMATS, 2026-09-22).
//
// Контракт:
//   - Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Форматы и шаблоны» (второй из 10 критериев Data Quality).
//   - Алгоритм основан на РЕАЛЬНОЙ логике:
//       • validation/rule_resolver.py::resolve_validation_rules
//         (приоритет эталона: сессия overrides > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; _deep_merge(system, template) + overrides;
//         CHECK_SECTIONS["formats"] = "formats")
//       • validation/engine.py::_system_format_rules (через
//         auto_generate_rules): только object/string-колонки, шаблон
//         назначается по семантике ИМЕНИ: email/e-mail → email-шаблон
//         (threshold 95), phone/телефон/mobile → телефон РФ (90),
//         date/дата → дата ISO YYYY-MM-DD (98), currency/валюта →
//         код валюты [A-Z]{3} (100); колонке без семантики имени
//         правило НЕ назначается (честность — правило не выводится из
//         фактических значений)
//       • validation/engine.py::DEFAULT_FORMAT_PATTERNS (email,
//         phone_ru, date_iso, currency — дефолтные regex + пороги)
//       • validation/engine.py::format_invalid_mask
//         (re.compile — шаблон валиден; str.fullmatch — совпадает ВСЁ
//         значение, не подстрока; пропуски NaN не считаются нарушениями)
//       • validation/engine.py::profile_formats (threshold по умолчанию
//         95; match_pct = доля прошедших; invalid_examples — до 5
//         уникальных; пустая колонка не делает проверку применимой)
//       • validation/engine.py::validate_formats (строка на КАЖДУЮ
//         matched колонку — даже с 0 нарушений, сигнал применимости;
//         match_pct >= threshold → Норма, ниже → Отклонение)
//       • validation/engine.py::_run_all_checks::_formats
//         (items=[{label: колонка, count: Нарушений}], count=Σ;
//         done(0)/warning(>0)/pending(нет правила); scope="column" —
//         при выбранном признаке скоупится до одной колонки, отличая
//         от «Типов данных» (scope="dataset"))
//       • apps/api/routers/session.py::get_dataset_format_profile
//         (GET /v1/session/dataset/format-profile — профиль + rule_source)
//         и correct_dataset_formats (POST /v1/session/dataset/
//         format-corrections — preview/apply; regex всегда из resolved
//         rules, не из клиента; preview на копии, apply — атомарная
//         подмена датасета)
//       • apps/api/format_correction.py::preview_format_corrections
//         (4 стратегии: replace_null / smart_replace / normalize / flag
//         с добавлением колонки <имя>_format_valid)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других Navigator*Preview).
//
// Архитектурно — родственник NavigatorValidationDataTypesPreview:
// статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts, без fetch.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorValidationFormatsPreview } from "./NavigatorValidationFormatsPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationFormatsPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    const { container } = render(<NavigatorValidationFormatsPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Форматы и шаблоны: Валидация»", () => {
    render(<NavigatorValidationFormatsPreview />);
    // H3 заголовок шапки блок-схемы — модуль: остановка.
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /форматы и шаблоны/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes the API endpoints visible to the user", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Фронт-контракт чека: GET /v1/session/dataset/validate (общий для
    // 10 чеков) + профиль/исправление форматов (format-profile /
    // format-corrections) в финальном блоке мастера.
    expect(
      screen.getAllByText(/session\/dataset\/validate/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/format-profile/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/format-corrections/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the rule resolver with the 3-source priority (session > template > system)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validation/rule_resolver.py::resolve_validation_rules:
    // _deep_merge(_deep_merge(system, template), overrides) — верхний
    // слой выигрывает. Термины легитимно повторяются (лейбл источника +
    // подписи) — getAllByText.
    expect(screen.getAllByText(/resolve_validation_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/сессия/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/система/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the deep-merge resolution order (system → template → session)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Механика резолва: глубокое слияние трёх слоёв.
    expect(screen.getAllByText(/_deep_merge/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/default_rules\.yaml/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the system inference lanes by column-name semantics (email / phone / date / currency)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validation/engine.py::_system_format_rules: только object/string-
    // колонки; шаблон по семантике имени.
    expect(screen.getAllByText(/_system_format_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/email/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/телефон/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/дата/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/валют/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the default pattern thresholds (95 / 90 / 98 / 100)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // DEFAULT_FORMAT_PATTERNS: email 95, phone_ru 90, date_iso 98,
    // currency 100; порог 95 встречается минимум дважды (email + дефолт
    // threshold в profile_formats) — getAllByText. Числа — отдельные
    // элементы-бейджи с точным текстом.
    expect(screen.getAllByText("95").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("90").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("98").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("100").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the ISO date and currency-code patterns", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Дефолтные шаблоны: дата ISO YYYY-MM-DD; код валюты — 3 буквы A-Z
    // (regex-спецсимволы в элементе — матчим regex-ом, не точной строкой).
    expect(screen.getAllByText(/YYYY-MM-DD/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/A-Z\]\{3\}/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the invalid-mask mechanics (re.compile + fullmatch + NaN honesty)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validation/engine.py::format_invalid_mask: шаблон компилируется
    // до прогона; совпадение — ПОЛНОЕ значение (fullmatch), не подстрока;
    // пропуски не считаются нарушениями.
    expect(screen.getAllByText(/format_invalid_mask/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/re\.compile/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/fullmatch/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/пропуски не считаются нарушениями/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the profile mechanics (match_pct, invalid_examples, threshold default 95)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validation/engine.py::profile_formats: match_pct — доля прошедших
    // шаблон; invalid_examples — до 5 уникальных нарушающих значений;
    // пустая колонка (total_count = 0) не делает проверку применимой.
    expect(screen.getAllByText(/profile_formats/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/match_pct/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/invalid_examples/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/пустая колонка не делает проверку применимой/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the threshold marking (Норма vs Отклонение)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validate_formats: match_pct >= threshold → Норма, иначе Отклонение.
    expect(screen.getAllByText(/норма/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/отклонение/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the applicability signal (row emitted even with 0 violations)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // validate_formats эмитит запись для КАЖДОЙ matched колонки — даже
    // с 0 нарушений: по raw отличают «правило есть, 0 нарушений» от
    // «правила нет вообще».
    expect(screen.getAllByText(/даже с 0 нарушений/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the aggregation contract (items + count sum) and the column scope", () => {
    render(<NavigatorValidationFormatsPreview />);
    // _run_all_checks::_formats: items=[{label: колонка, count}]; count=Σ;
    // scope="column" — чек скоупится до выбранного признака, в отличие
    // от «Типов данных» (scope="dataset").
    expect(screen.getAllByText(/scope/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/column/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/dataset/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/не скоупится|скоупится/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the pending honesty (no rule for the column → pending)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // _formats при выбранном признаке: колонка не matched → pending —
    // честный сигнал «правила нет», а не «нарушений нет».
    expect(screen.getAllByText(/pending/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the three check statuses (done / warning / pending)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // _status: count None → pending; 0 → done; >0 → warning.
    expect(screen.getAllByText(/^done$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^warning$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^pending$/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the correction master with 4 strategies", () => {
    render(<NavigatorValidationFormatsPreview />);
    // «Мастер исправления форматов и шаблонов» (TsAnalysisValidation.tsx)
    // → 4 стратегии apps/api/format_correction.py.
    expect(screen.getAllByText(/Мастер исправления форматов/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/replace_null/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/smart_replace/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/normalize/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/flag/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the flag strategy contract (added <column>_format_valid column)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Стратегия flag добавляет булеву колонку <имя>_format_valid.
    expect(screen.getAllByText(/_format_valid/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the smart-replacement values (median / email / phone / NaT / USD)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // _smart_replacement: числовые — медиана валидных; email →
    // unknown@example.com; phone → +79990000000; date → NaT; currency → USD.
    expect(screen.getAllByText(/unknown@example\.com/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/\+79990000000/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/медиана/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the server-side regex guarantee (rules from server, not client)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // correct_dataset_formats: regex всегда берётся из resolved rules,
    // а не из клиента; preview не мутирует сессию, apply сохраняет копию
    // атомарно.
    expect(screen.getAllByText(/не из клиента/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/атомарн/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the honest name-semantics note (no rule without name semantics)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Честность системного слоя: колонке без семантики имени правило
    // не назначается — правило не выводится из фактических значений.
    expect(screen.getAllByText(/без семантики имени/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the criteria position caption (second of 10 Data Quality criteria)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // «Форматы и шаблоны» — второй из 10 критериев Data Quality
    // (DAMA DMBOK) вкладки «Валидация».
    expect(screen.getAllByText(/DAMA DMBOK/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/второй из 10/i).length).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// a11y и целостность блок-схемы
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationFormatsPreview — a11y and integrity", () => {
  it("exposes the whole flowchart as a single role=img with a full aria-label", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Скринридер читает блок-схему как одно изображение; aria-label
    // описывает всю цепочку — от эталона правил до мастера исправлений.
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("aria-label");
    const label = img.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/Форматы и шаблоны/);
    expect(label).toMatch(/resolve_validation_rules|эталон правил/i);
    expect(label).toMatch(/fullmatch/);
    expect(label).toMatch(/scope/);
    expect(label).toMatch(/Мастер исправления форматов/i);
  });

  it("renders the arrow chain between blocks (visual flow)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Стрелки между блоками — ChevronDown с aria-label "chevron down"
    // (единый паттерн с NavigatorValidationDataTypesPreview). Вложенные
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
      throw new Error("NavigatorValidationFormatsPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorValidationFormatsPreview must not create XHR");
    };

    try {
      render(<NavigatorValidationFormatsPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("does NOT render an empty-state placeholder (no dataset wording)", () => {
    render(<NavigatorValidationFormatsPreview />);
    // Схема не зависит от датасета — никаких «нет данных»/empty-state.
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(screen.queryByText(/активный датасет/i)).toBeNull();
  });
});
