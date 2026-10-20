// packages/ui/lib/structuralClass.test.ts
//
// UPLOAD-RECOMP-2-DECOMP (2026-10-20): RED-тесты дефекта классификации,
// заблокировавшего путь «панель -> панельные микросервисы -> декомпозиция»
// на остановке «График» (сценарий тимлида, воспроизведён в реальном
// браузере на живом API).
//
// Дефект (найден на живом стеке standalone@3001 + api@8000, датасет
// panel_browser.csv: month/region/sales, 2 сущности x 36 месяцев):
//   1) detectHierarchyCandidates строит цепочку иерархии ПО ВСЕМ
//      категориальным колонкам, ВКЛЮЧАЯ временную: дата из CSV -- строки
//      (columns_info.type_icon = "categorical"), кардинальность
//      region(2) -> month(36) проходит порог 1.5x -> цепочка
//      ["region", "month"] -> класс Hierarchical;
//   2) ветка Hierarchical в classifyStructure выполняется РАНЬШЕ ветки
//      Panel Data -> панельный класс украдён -> isPanelClass=false ->
//      блок «Панельные данные: три пути исследования» не рендерится ->
//      «Фильтр сущности»/«Агрегация по времени» недоступны -> панель
//      нельзя свести к одному ряду -> декомпозиция на «Графике» остаётся
//      недоступной (честный отказ бэкенда по панельным дублям дат).
//
// В Jest-моках дефект не воспроизводился: тестовые columns_info
// помечали month как type_icon="datetime", тогда как реальный API
// отдаёт "categorical" для строковых дат CSV (проверено curl'ом
// /v1/session/dataset на живой сессии).
//
// Контракт дерева спеки (spec_upload_recompose_2026-10-20.md §3.2,
// порядок правил): правило 4 «Есть дата И есть группирующая колонка ->
// Panel Data» стоит РАНЬШЕ правила 6 «Обнаружена вложенная иерархия ->
// Hierarchical»; время -- ось наблюдений, а не уровень вложенности
// сущностей, и в иерархическую цепочку (страна -> регион -> ...) не
// входит. Явные факты детекции (дата + группировка + panel-balance)
// сильнее эвристики кардинальности (её собственный routingHint:
// "не проверено группировкой").

import { classifyStructure, type ColumnLike } from "./structuralClass";

function col(name: string, typeIcon: ColumnLike["type_icon"], unique: number): ColumnLike {
  return { name, type_icon: typeIcon, unique };
}

// ── СВОЙ корпус: панель со СТРОЧНЫМИ датами (реальный профиль CSV) ──────
// Точно такой columns_info отдаёт живой API для panel_browser.csv
// (2 сущности x 36 месяцев, месяц -- строки "2022-01-01").

const categoricalDatePanelColumns: ColumnLike[] = [
  col("month", "categorical", 36),
  col("region", "categorical", 2),
  col("sales", "numeric", 60),
];

describe("UPLOAD-RECOMP-2-DECOMP: панель со строчными датами не крадётся иерархией", () => {
  it("R1: панель region(2) x month(36, categorical) -- класс Panel Data, НЕ Hierarchical", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 2,
      isRegularFrequency: true,
      columnsInfo: categoricalDatePanelColumns,
      panelBalance: "balanced",
      dateColumnName: "month",
    });
    // До фикса: "hierarchical" (цепочка region -> month) -- панельные
    // микросервисы недоступны, путь к декомпозиции заблокирован.
    expect(result.id).toBe("panel_balanced");
  });

  it("R2: панель с неизвестным балансом -- panel_unknown, НЕ Hierarchical", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 2,
      isRegularFrequency: true,
      columnsInfo: categoricalDatePanelColumns,
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("panel_unknown");
  });

  it("R3: временная колонка НЕ входит в иерархическую цепочку даже без группировки", () => {
    // city(100) + month(36, categorical) + sales + temperature, entity
    // не выбрана -- это Multivariate TS (месяц -- ось, city --
    // игнорируемая категория), а не «иерархия month -> city».
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("month", "categorical", 36),
        col("city", "categorical", 100),
        col("sales", "numeric", 100),
        col("temperature", "numeric", 90),
      ],
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("multivariate_ts");
  });

  it("R4: панель с категориальным годом (year categorical) -- Panel Data, НЕ Hierarchical (правило 4 раньше правила 6)", () => {
    // Распространённая панель: region x year x month, месяц выбран датой,
    // год остаётся категорией -- ложная цепочка region -> year -> month.
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 2,
      isRegularFrequency: true,
      columnsInfo: [
        col("region", "categorical", 2),
        col("year", "categorical", 3),
        col("month", "categorical", 36),
        col("sales", "numeric", 200),
      ],
      panelBalance: "unbalanced",
      dateColumnName: "month",
    });
    expect(result.id).toBe("panel_unbalanced");
  });
});

describe("UPLOAD-RECOMP-2-DECOMP: легитимная иерархия сущностей сохраняется (гард)", () => {
  it("R5: страна(4) -> регион(50) при datetime-дате -- Hierarchical, как и прежде", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("country", "categorical", 4),
        col("region_name", "categorical", 50),
        col("value", "numeric", 200),
      ],
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("hierarchical");
  });

  it("R6: прежний контракт без dateColumnName (старые вызовы) -- иерархия по категориям не ломается", () => {
    const result = classifyStructure({
      hasDateColumn: false,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: false,
      columnsInfo: [col("country", "categorical", 4), col("region_name", "categorical", 50)],
      panelBalance: "unknown",
    });
    expect(result.id).toBe("hierarchical");
  });

  it("R7: event TS остаётся специфичнее панели (первая ветка дерева не сдвинулась)", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 3,
      isRegularFrequency: false,
      columnsInfo: [col("timestamp", "datetime", 50), col("event_type", "categorical", 3)],
      panelBalance: "unknown",
      dateColumnName: "timestamp",
    });
    expect(result.id).toBe("event_ts");
  });
});
