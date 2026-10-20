// packages/ui/lib/structuralClass.cert-oracles.test.ts
//
// UPLOAD-RECOMP-2-CERT (2026-10-20): ОРАКУЛЫ НА СВОИХ ДАННЫХ (канал
// oracle) независимой сертификации серии UPLOAD-RECOMP-2 (8db2d81) +
// FIX (8782abd) + DECOMP (39c001d) -- классификация структуры
// (packages/ui/lib/structuralClass.ts).
//
// Корпус СВОЙ, дизъюнктен structuralClass.test.ts (R1–R7, панель
// month/region/sales): профиль «кубанская торговля» -- week(categorical,
// 12 дат) x warehouse(3) x revenue, вторая цепочка type(2) -> warehouse(10)
// легитимной кардинальности ВНУТРИ панели; отдельные профили unbalanced-
// панели, event-профиля, спатио, кросс-секций и близких категорий (4 и 5 --
// порог иерархии 1.5x НЕ проходит).
//
// Функция канала: на мутационной кампании (scripts/cert_recomp2/mutations.py)
// убивает мутантов M01 (снято исключение даты), M02 (панель ниже иерархии),
// M03 (порог 1.5 -> 0.5), M04 (>= 2 -> >= 3), M05 (> 1 -> >= 1) -- то есть
// детектирует до-фиксное поведение (эквивалент RED на родителе серии).

import { classifyStructure, type ColumnLike } from "./structuralClass";

function col(name: string, typeIcon: ColumnLike["type_icon"], unique: number): ColumnLike {
  return { name, type_icon: typeIcon, unique };
}

// ── СВОЙ корпус: «кубанская торговля» ────────────────────────────────────
// Панель со СТРОЧНОЙ датой CSV (week -- categorical) и ЛЕГИТИМНОЙ
// двухуровневой категориальной цепочкой type(2) -> warehouse(10):
// кардинальность 10 >= 2 * 2 * 1.5 -- эвристика иерархии строит цепочку,
// но дата исключена и панель (явные факты) сильнее эвристики.

const kubanPanelColumns: ColumnLike[] = [
  col("week", "categorical", 12),
  col("type", "categorical", 2),
  col("warehouse", "categorical", 10),
  col("revenue", "numeric", 120),
];

describe("UPLOAD-RECOMP-2-CERT: классификация на своих данных (кубанский корпус)", () => {
  it("P1: панель week(categorical) x warehouse с легитимной цепочкой type->warehouse -- Panel Data — Balanced", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 3,
      isRegularFrequency: true,
      columnsInfo: kubanPanelColumns,
      panelBalance: "balanced",
      dateColumnName: "week",
    });
    // До фикса DECOMP: "hierarchical" (цепочка type -> warehouse либо
    // week -> warehouse). Панель обязана выиграть дважды: и исключением
    // даты из цепочки, и приоритетом правила 4 над правилом 6.
    expect(result.id).toBe("panel_balanced");
  });

  it("P2: несбалансированная панель своего профиля -- Panel Data — Unbalanced", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 4,
      isRegularFrequency: true,
      columnsInfo: [
        col("week", "categorical", 12),
        col("warehouse", "categorical", 4),
        col("revenue", "numeric", 200),
      ],
      panelBalance: "unbalanced",
      dateColumnName: "week",
    });
    expect(result.id).toBe("panel_unbalanced");
  });

  it("P3: баланс ещё считается -- Panel Data (unknown), не Hierarchical", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 3,
      isRegularFrequency: true,
      columnsInfo: kubanPanelColumns,
      panelBalance: "unknown",
      dateColumnName: "week",
    });
    expect(result.id).toBe("panel_unknown");
  });

  it("P4: многомерный ряд своего профиля с категорией city -- Multivariate TS, не «иерархия month -> city»", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("month", "categorical", 24),
        col("city", "categorical", 60),
        col("sales", "numeric", 240),
        col("returns", "numeric", 180),
      ],
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("multivariate_ts");
  });

  it("P5: две НЕЗАВИСИМЫЕ категории близкой кардинальности (4 и 5) -- Univariate TS, не Hierarchical", () => {
    // Порог эвристики: рост минимум в 1.5x на уровень -- 5 < 4 * 1.5 = 6.
    // Ослабление порога (1.5 -> 0.5) превращает независимые категории в
    // ложную иерархию -- оракул это ловит.
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("quarter", "categorical", 4),
        col("segment", "categorical", 5),
        col("value", "numeric", 100),
      ],
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("univariate_ts");
  });

  it("P6: одна сущность (entityUniqueCount=1) -- не панель, Univariate TS", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 1,
      isRegularFrequency: true,
      columnsInfo: [
        col("day", "datetime", 90),
        col("warehouse", "categorical", 1),
        col("sales", "numeric", 90),
      ],
      panelBalance: "unknown",
      dateColumnName: "day",
    });
    expect(result.id).toBe("univariate_ts");
  });

  it("P7: легитимная иерархия страна(4) -> регион(50) своего корпуса -- Hierarchical (гард)", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("country", "categorical", 4),
        col("region_name", "categorical", 50),
        col("turnover", "numeric", 200),
      ],
      panelBalance: "unknown",
      dateColumnName: "month",
    });
    expect(result.id).toBe("hierarchical");
  });

  it("P8: прежний контракт без dateColumnName (старые вызовы) -- иерархия не ломается (гард)", () => {
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

  it("P9: event-профиль своего корпуса специфичнее панели", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: true,
      entityUniqueCount: 2,
      isRegularFrequency: false,
      columnsInfo: [col("ts", "datetime", 70), col("action", "categorical", 3)],
      panelBalance: "unknown",
      dateColumnName: "ts",
    });
    expect(result.id).toBe("event_ts");
  });

  it("P10: спатио-профиль своего корпуса (lat/lon + дата)", () => {
    const result = classifyStructure({
      hasDateColumn: true,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: true,
      columnsInfo: [
        col("lat", "numeric", 80),
        col("lon", "numeric", 80),
        col("day", "datetime", 64),
        col("temp", "numeric", 100),
      ],
      panelBalance: "unknown",
      dateColumnName: "day",
    });
    expect(result.id).toBe("spatio_temporal");
  });

  it("P11: без даты и без группировки -- Cross-Sectional", () => {
    const result = classifyStructure({
      hasDateColumn: false,
      hasEntityColumn: false,
      entityUniqueCount: null,
      isRegularFrequency: false,
      columnsInfo: [col("store", "categorical", 12), col("revenue", "numeric", 300)],
      panelBalance: "unknown",
    });
    expect(result.id).toBe("cross_sectional");
  });
});
