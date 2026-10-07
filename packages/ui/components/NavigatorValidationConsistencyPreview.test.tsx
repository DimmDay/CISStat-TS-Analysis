// packages/ui/components/NavigatorValidationConsistencyPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Логика и хронология»
// (id="consistency", четвёртый пункт) секции «Этапы модуля» остановки
// «Валидация» на странице Навигатор (Task NAVDET-CONSISTENCY, 2026-10-08).
//
// Контракт:
//   - Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Логика и хронология» (четвёртый из 10 критериев Data
//     Quality).
//   - Алгоритм основан на РЕАЛЬНОЙ логике:
//       • validation/rule_resolver.py::resolve_validation_rules
//         (приоритет эталона: сессия overrides > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; _deep_merge(_deep_merge(system, template),
//         overrides); CHECK_SECTIONS["consistency"] = "consistency")
//       • validation/engine.py::auto_generate_rules — системный слой
//         согласованности: при наличии date/time-колонки (datetime dtype
//         или токены имени year/год/date/дата/time/время/timestamp/
//         period/период) добавляет ОДНО правило «Хронологический порядок»
//         (type="chronology", columns=[первая date-колонка])
//       • rules/default_rules.yaml::consistency — шаблонные правила:
//         condition-правила (date_order: end_date > start_date,
//         total_match) и предметные типовые (temp_precip, profit_revenue,
//         steps_distance, energy_subsystem)
//       • validation/engine.py::_evaluate_consistency_rule — диспетчер
//         по rule_type: chronology → _chronology_evaluation (группы,
//         shift(1), реверс values < previous, маска помечает ОБЕ строки
//         пары, comparable = обе notna); comparison →
//         _comparison_evaluation (ровно 2 колонки, оператор из 6:
//         <, <=, >, >=, ==, !=); condition → _condition_evaluation
//         (безопасный regex-парс «левое оп правое» БЕЗ eval());
//         предметные: negative_price (>= 0), positive_prices (> 0),
//         profit_revenue (прибыль <= выручка), energy_subsystem
//         (подсистема <= общее), steps_distance (шаги=0 при
//         расстоянии > 0), speed_fuel (скорость=0 при расходе > 1),
//         temp_precip (снег при t > 0 / дождь при t < 0)
//       • validation/engine.py::evaluate_consistency_rules — ЕДИНЫЙ
//         источник масок для общей проверки, обзора и исправлений;
//         изоляция ошибок: сбой одного предметного правила →
//         applicable=false («Ошибка правила: …»), проверка не падает;
//         неприменимое правило — applicability_message («Колонка …
//         отсутствует», «Типы колонок нельзя сравнить», «Тип правила …
//         не поддерживается»); вывод: checked/valid/invalid_count,
//         affected_rows (реверс помечает 2 строки), invalid_examples до 5
//       • validation/engine.py::profile_consistency — полный профиль
//         настроенных правил, включая pass и неприменимость (без
//         mask/correction_columns)
//       • validation/engine.py::validate_consistency — legacy-контракт:
//         строки ТОЛЬКО для применимых правил: Правило, Тип, Колонки,
//         Нарушений, Затронуто строк, Статус «⚠️ Нарушено»/«✅ Соблюдено»
//       • validation/engine.py::_run_all_checks::_consistency —
//         items=[{label: Правило, count: Нарушений}], count = Σ;
//         применимых правил нет → count=None → pending; scope="dataset"
//         — ПРИНЦИПИАЛЬНО не скоупится до одной колонки (межколоночные
//         правила и ось времени не принадлежат одному признаку) —
//         отличие от ranges/formats (scope="column")
//       • apps/api/routers/session.py::get_dataset_consistency_profile
//         (GET /v1/session/dataset/consistency-profile — профиль + rule_source,
//         not_applicable без применимых правил) и correct_dataset_consistency
//         (POST /v1/session/dataset/consistency-corrections — preview/apply;
//         правила и маски всегда из resolved rules сервера, не из клиента;
//         preview на глубокой копии, apply — атомарная подмена датасета)
//       • apps/api/consistency_correction.py::preview_consistency_corrections
//         (4 стратегии: sort_chronology — только для chronology-правил,
//         стабильная группо-устойчивая сортировка по времени, NaT — в
//         конец, считает изменившие позицию строки; drop_rows — удаление
//         строк по ОБЪЕДИНЁННОЙ маске выбранных правил; replace_null —
//         корректируемые колонки правила → NA по маске; flag — булева
//         колонка <имя>_consistency_valid, коллизия имени — ошибка;
//         пустой выбор/дубликаты/неприменимое правило отклоняются)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других Navigator*Preview).
//
// Архитектурно — родственник NavigatorValidationRangesPreview:
// статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
// без состояния, без recharts, без fetch.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorValidationConsistencyPreview } from "./NavigatorValidationConsistencyPreview";

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная блок-схема, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationConsistencyPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    const { container } = render(<NavigatorValidationConsistencyPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Логика и хронология: Валидация»", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // H3 заголовок шапки блок-схемы — модуль: остановка.
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /логика и хронология/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes the API endpoints visible to the user", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Фронт-контракт чека: GET /v1/session/dataset/validate (общий для
    // 10 чеков) + профиль/исправление согласованности (consistency-profile
    // / consistency-corrections) в финальном блоке мастера.
    expect(
      screen.getAllByText(/session\/dataset\/validate/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/consistency-profile/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/consistency-corrections/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the rule resolver with the 3-source priority (session > template > system)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // validation/rule_resolver.py::resolve_validation_rules:
    // _deep_merge(_deep_merge(system, template), overrides) — верхний
    // слой выигрывает. Термины легитимно повторяются — getAllByText.
    expect(screen.getAllByText(/resolve_validation_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/сессия/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/система/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the deep-merge resolution order and the template file", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Механика резолва: глубокое слияние трёх слоёв; шаблон по умолчанию
    // — default_rules.yaml.
    expect(screen.getAllByText(/_deep_merge/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/default_rules\.yaml/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the system inference (chronology rule from the first date column)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // validation/engine.py::auto_generate_rules: при наличии date/time-
    // колонки — ОДНО системное правило «Хронологический порядок».
    expect(screen.getAllByText(/auto_generate_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Хронологический порядок/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the rule-type dispatcher (_evaluate_consistency_rule)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Диспетчер по rule_type — реальная функция бэкенда.
    expect(screen.getAllByText(/_evaluate_consistency_rule/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/rule_type/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the chronology mechanics (groups, shift(1), reversal, both rows marked)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // _chronology_evaluation: группы по group_column (из правила или
    // авто-детект), shift(1) — сравнение с предыдущей точкой, реверс
    // values < previous; маска помечает ОБЕ строки пары; пары с
    // пропусками не сравниваются.
    expect(screen.getAllByText(/shift\(1\)/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/values < previous|время идёт назад|реверс/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/обе строки/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/групп/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the comparison mechanics (2 columns, 6 operators, no eval)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // _comparison_evaluation: ровно 2 колонки, оператор из 6;
    // _condition_evaluation — безопасный regex-парс без eval().
    expect(screen.getAllByText(/<=|≥|оператор/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/без eval\(\)|eval\(\)/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/ровно 2 колонки|две колонки/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the domain rule lanes (negative_price / profit_revenue / steps_distance / temp_precip …)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Предметные типовые правила шаблона и движка.
    expect(screen.getAllByText(/negative_price/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/profit_revenue/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/energy_subsystem/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/steps_distance/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/temp_precip/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the unified evaluation contract (single mask source, error isolation, applicability)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // evaluate_consistency_rules: единый источник масок для общей
    // проверки, обзора и исправлений; сбой одного правила изолируется
    // («Ошибка правила: …»); неприменимое правило — applicability_message.
    expect(screen.getAllByText(/evaluate_consistency_rules/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/единый источник масок/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Ошибка правила/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/applicability_message/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the examples and row-accounting honesty (invalid_examples ≤ 5, affected_rows ≥ reversals)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // invalid_examples — до 5; affected_rows может быть больше числа
    // реверсов: реверс помечает обе строки пары.
    expect(screen.getAllByText(/invalid_examples/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/affected_rows/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the profile contract (profile_consistency includes pass and non-applicability)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // profile_consistency: полный профиль настроенных правил, включая
    // pass и неприменимость.
    expect(screen.getAllByText(/profile_consistency/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/включая pass и неприменимость/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the run contract (results only for applicable rules, violated/observed statuses)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // validate_consistency: строки ТОЛЬКО для применимых правил;
    // Статус «⚠️ Нарушено» / «✅ Соблюдено»; Затронуто строк.
    expect(screen.getAllByText(/validate_consistency/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/только для применимых правил/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Нарушено/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Соблюдено/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Затронуто строк/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the aggregation contract and the dataset scope (differs from ranges/formats)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // _consistency: items=[{label: Правило, count}], count = Σ;
    // scope="dataset" — чек ПРИНЦИПИАЛЬНО не скоупится до одной колонки
    // (межколоночные правила и ось времени), отличие от ranges/formats
    // (scope="column"). Значение scope пин точечно: /dataset/i ловился бы
    // эндпоинтами /v1/session/dataset/… (мутант scope→column выжил).
    expect(screen.getAllByText(/scope/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/scope="dataset"/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/не скоупится/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/count = Σ/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the three check statuses (done / warning / pending)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // _status: count None → pending; 0 → done; >0 → warning.
    expect(screen.getAllByText(/^done$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^warning$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^pending$/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the pending honesty (no applicable rules → pending, not done)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Применимых правил нет (нет date-колонки / правила ссылаются на
    // отсутствующие колонки) → count=None → pending.
    expect(screen.getAllByText(/нет применимых правил/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the correction master with 4 strategies", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // «Мастер исправления логики и хронологии» (TsAnalysisValidation.tsx)
    // → 4 стратегии apps/api/consistency_correction.py.
    expect(screen.getAllByText(/Мастер исправления логики и хронологии/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^sort_chronology$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^drop_rows$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^replace_null$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^flag$/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the sort_chronology contract (chronology-only, stable group-aware sort, NaT last)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // sort_chronology применима ТОЛЬКО к правилам хронологии; стабильная
    // сортировка по времени внутри групп; NaT — в конец; счёт —
    // изменившие позицию строки.
    expect(screen.getAllByText(/только для chronology|только к правилам хронологии/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/стабильная сортировк/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/NaT/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the flag strategy contract (added <rule>_consistency_valid column, name collision error)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Стратегия flag добавляет булеву колонку <имя>_consistency_valid
    // без изменения значений; коллизия имени — ошибка.
    expect(screen.getAllByText(/_consistency_valid/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/коллизия/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the drop_rows strategy contract (union mask over selected rules)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // drop_rows: удаляется ОБЪЕДИНЕНИЕ строк, нарушающих любое из
    // отмеченных правил.
    expect(screen.getAllByText(/объедин/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the server-side rules guarantee (rules from server, not client) and atomicity", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // correct_dataset_consistency: правила и маски всегда из resolved
    // rules, а не из клиента; preview на глубокой копии, apply —
    // атомарная подмена датасета.
    expect(screen.getAllByText(/не из клиента/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/атомарн/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/глубокой копии/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the operation guard honesty (applicable rule required, duplicates/empty selection rejected)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // preview_consistency_corrections: правило должно быть применимо;
    // пустой выбор и дубликаты индексов отклоняются (422).
    expect(screen.getAllByText(/применимого правила|должно быть применимо/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/дубликат/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/пустой выбор/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the criteria position caption (fourth of 10 Data Quality criteria)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // «Логика и хронология» — четвёртый из 10 критериев Data Quality
    // (DAMA DMBOK) вкладки «Валидация».
    expect(screen.getAllByText(/DAMA DMBOK/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/четвёртый из 10/i).length).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// a11y и целостность блок-схемы
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorValidationConsistencyPreview — a11y and integrity", () => {
  it("exposes the whole flowchart as a single role=img with a full aria-label", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Скринридер читает блок-схему как одно изображение; aria-label
    // описывает всю цепочку — от эталона правил до мастера исправлений.
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("aria-label");
    const label = img.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/Логика и хронология/);
    expect(label).toMatch(/resolve_validation_rules|эталон/i);
    expect(label).toMatch(/evaluate_consistency_rules|масок/i);
    expect(label).toMatch(/scope/);
    expect(label).toMatch(/Мастер исправления логики и хронологии/i);
  });

  it("renders the arrow chain between blocks (visual flow)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Стрелки между блоками — ChevronDown с aria-label "chevron down"
    // (единый паттерн с NavigatorValidationRangesPreview). Вложенные
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
      throw new Error("NavigatorValidationConsistencyPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorValidationConsistencyPreview must not create XHR");
    };

    try {
      render(<NavigatorValidationConsistencyPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("does NOT render an empty-state placeholder (no dataset wording)", () => {
    render(<NavigatorValidationConsistencyPreview />);
    // Схема не зависит от датасета — никаких «нет данных»/empty-state.
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(screen.queryByText(/активный датасет/i)).toBeNull();
  });
});
