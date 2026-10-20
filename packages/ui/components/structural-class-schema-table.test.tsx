// packages/ui/components/structural-class-schema-table.test.tsx
//
// UPLOAD-RECOMP-2 (2026-10-20), пункт (б) + дополнение тимлида:
// справочная схема «Определение структуры данных» на остановке
// «Структура» переписывается с блочного списка на КОМПАКТНУЮ ТАБЛИЦУ:
//
//   | Признаки (условие) | Класс | Определение | Решаемые задачи |
//
//   * столбец «Определение» -- русскоязычные определения классов из
//     ЕДИНОГО источника RU_DEFINITION (structuralClass.ts); вторая
//     копия строк запрещена;
//   * столбец «Решаемые задачи» (дополнение постановки) -- список
//     задач, решаемых платформой на данных класса, из единого
//     источника RU_TASKS (structuralClass.ts);
//   * подсветка совпадающей строки (bg-brand-light + Check) и
//     подписи сохраняются; панельные подстроки -- с отступом.
//
// Оракулы структурные (пины контента) на СВОИХ данных -- корпус
// дизъюнктен существующим тестам «Загрузки».

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { StructuralClassSchema } from "./StructuralClassSchema";
import {
  RU_DEFINITION,
  RU_TASKS,
  type StructuralClass,
} from "../lib/structuralClass";

const ALL_CLASSES: StructuralClass[] = [
  "cross_sectional",
  "univariate_ts",
  "multivariate_ts",
  "panel_balanced",
  "panel_unbalanced",
  "panel_unknown",
  "spatio_temporal",
  "hierarchical",
  "event_ts",
];

// Спека §3.2: дословные русские определения (единый источник).
const EXPECTED_RU_DEFINITION: Record<StructuralClass, string> = {
  cross_sectional: "Кросс-секционные данные: измерения без временно́й оси",
  univariate_ts: "Одномерный временной ряд",
  multivariate_ts: "Многомерный временной ряд: несколько рядов на общей сетке",
  panel_balanced: "Сбалансированная панель",
  panel_unbalanced: "Несбалансированная панель",
  panel_unknown: "Панельные данные (баланс уточняется)",
  spatio_temporal: "Пространственно-временные данные",
  hierarchical: "Иерархические данные: вложенные уровни агрегации",
  event_ts: "Событийный ряд: точки-события, не значения",
};

describe("UPLOAD-RECOMP-2b: единый источник русских определений и решаемых задач", () => {
  it("RU_DEFINITION покрывает все 9 классов дословно по спеке §3.2", () => {
    for (const cls of ALL_CLASSES) {
      expect(RU_DEFINITION[cls]).toBe(EXPECTED_RU_DEFINITION[cls]);
    }
  });

  it("RU_TASKS покрывает все 9 классов: у каждого класса непустой честный список решаемых задач", () => {
    for (const cls of ALL_CLASSES) {
      const tasks = RU_TASKS[cls];
      expect(Array.isArray(tasks)).toBe(true);
      expect(tasks.length).toBeGreaterThan(0);
      for (const task of tasks) {
        expect(typeof task).toBe("string");
        expect(task.length).toBeGreaterThan(3);
      }
    }
  });

  it("честность контента: у одномерного ряда заявлен классический контур и прогноз; у панели -- сведение к одному ряду и честная пометка о панельных моделях в разработке", () => {
    expect(RU_TASKS.univariate_ts.join(" ")).toMatch(/ARIMA|классическ/);
    expect(RU_TASKS.univariate_ts.join(" ")).toMatch(/Прогноз/);
    expect(RU_TASKS.panel_balanced.join(" ")).toMatch(/фильтр сущности|агрегация/);
    expect(RU_TASKS.panel_balanced.join(" ")).toMatch(/в разработке/);
    // Кросс-секционные данные: задачи временных рядов не обещаются.
    expect(RU_TASKS.cross_sectional.join(" ")).toMatch(/Валидация|статистик|корреляц/i);
  });
});

describe("UPLOAD-RECOMP-2b: компактная таблица «Определение структуры данных»", () => {
  it("таблица с заголовками: Признаки, Класс, Определение, Решаемые задачи", () => {
    render(<StructuralClassSchema activeClassId={null} />);
    const table = screen.getByTestId("structural-class-table");
    expect(table.tagName).toBe("TABLE");
    const headerText = screen.getByTestId("structural-class-table-header").textContent ?? "";
    expect(headerText).toContain("Признаки");
    expect(headerText).toContain("Класс");
    expect(headerText).toContain("Определение");
    expect(headerText).toContain("Решаемые задачи");
  });

  it("9 строк: 7 правил + 2 панельные подстроки (отступ), определения и задачи -- из единого источника", () => {
    render(<StructuralClassSchema activeClassId={null} />);
    const rows = screen.getAllByTestId("structural-class-row");
    expect(rows).toHaveLength(9);

    // Панельные подстроки -- с отступом (indented, data-sub="true").
    const subRows = screen.getAllByTestId("structural-class-row").filter((r) => r.getAttribute("data-sub") === "true");
    expect(subRows).toHaveLength(2);

    // Дословные условия правил дерева (подписи сохранены).
    expect(screen.getByText("Нет даты И нет группировки")).toBeInTheDocument();
    expect(screen.getByText("Есть дата, ОДНА числовая колонка, нет группировки")).toBeInTheDocument();
    expect(screen.getByText("Есть дата, МНОГО числовых колонок, нет группировки")).toBeInTheDocument();
    expect(screen.getByText("Есть дата И есть группирующая колонка")).toBeInTheDocument();
    expect(screen.getByText("у всех групп одинаковый набор дат")).toBeInTheDocument();
    expect(screen.getByText("иначе")).toBeInTheDocument();
    expect(screen.getByText("Есть колонки координат (lat/long) + дата")).toBeInTheDocument();
    expect(screen.getByText("Обнаружена вложенная иерархия (страна → регион → …)")).toBeInTheDocument();
    expect(screen.getByText(/Timestamp \+ категориальная/)).toBeInTheDocument();

    // Русские определения читаются из RU_DEFINITION (единый источник).
    expect(screen.getByText(EXPECTED_RU_DEFINITION.univariate_ts)).toBeInTheDocument();
    expect(screen.getByText(EXPECTED_RU_DEFINITION.panel_balanced)).toBeInTheDocument();
    expect(screen.getByText(EXPECTED_RU_DEFINITION.event_ts)).toBeInTheDocument();
  });

  it("каждая строка несёт список решаемых задач из RU_TASKS", () => {
    render(<StructuralClassSchema activeClassId={null} />);
    const rows = screen.getAllByTestId("structural-class-row");
    for (const row of rows) {
      const tasksCell = row.querySelector('[data-testid="row-tasks"]');
      expect(tasksCell).not.toBeNull();
      expect((tasksCell as HTMLElement).textContent?.length ?? 0).toBeGreaterThan(3);
    }
  });

  it("подсветка совпадающей строки сохранена: bg-brand-light + галочка Check", () => {
    render(<StructuralClassSchema activeClassId="univariate_ts" />);
    const rows = screen.getAllByTestId("structural-class-row");
    const activeRow = rows.find((r) => r.textContent?.includes(EXPECTED_RU_DEFINITION.univariate_ts))!;
    expect(activeRow).toHaveClass("bg-brand-light");
    expect(activeRow.querySelector("svg")).not.toBeNull();
  });
});
