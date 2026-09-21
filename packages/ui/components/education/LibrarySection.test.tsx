// packages/ui/components/education/LibrarySection.test.tsx
//
// EDU-BADGE (постановка тимлида 2026-09-21): пилли фильтра этапов
// Библиотеки — «Все этапы», «Загрузка», «Валидация», «Предобработка»,
// «Разведочный EDA», «Моделирование», «Прогнозирование» — пассивный
// фон, ховер и рамка по паттерну бейджа «Обучение и база знаний» на
// главной странице (RouteCard):
//   пассив: bg-brand-light/60 + рамка border-brand/60;
//   ховер:  углубление до /90 (hover:bg-brand-light/90 + hover:border-brand/90).
// Активное состояние НЕ меняем: сплошное индиго bg-brand + text-white.
//
// Секция — контролируемый компонент: активная пилли задаётся пропом
// stageFilter (не внутренним состоянием), поэтому контракт активного/
// пассивного оформления страхуем разными значениями пропа.
// Отдельный файл: stageFilterClass — контракт LibrarySection, а не хаба
// (секция переиспользуема, страховать её паттерн нужно независимо).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { LibrarySection, type StageFilter } from "./LibrarySection";
import { getPublishedArticles } from "../../lib/knowledge/knowledge";
import { STAGE_LABELS_RU } from "../../lib/knowledge/types";

const articles = getPublishedArticles();

function renderSection(stageFilter: StageFilter = "all") {
  return render(
    <LibrarySection
      articles={articles}
      stageFilter={stageFilter}
      onStageFilterChange={() => {}}
      onOpenArticle={() => {}}
    />,
  );
}

describe("LibrarySection — пилли фильтра этапов по паттерну RouteCard (EDU-BADGE)", () => {
  it("пассивные пилли: bg-brand-light/60 + border-brand/60, ховер /90, не нейтральные и не брендовая заливка", () => {
    // активна «Разведочный EDA» — остальные 6 пилли пассивны
    renderSection("eda");
    const labels = ["Все этапы", ...Object.values(STAGE_LABELS_RU)].filter(
      (l) => l !== STAGE_LABELS_RU.eda,
    );
    expect(labels).toHaveLength(6);
    labels.forEach((label) => {
      const pill = screen.getByRole("button", { name: label });
      expect(pill.className).toContain("bg-brand-light/60");
      expect(pill.className).toContain("border-brand/60");
      expect(pill.className).toContain("hover:bg-brand-light/90");
      expect(pill.className).toContain("hover:border-brand/90");
      expect(pill.className).not.toContain("bg-neutral-100");
      expect(pill.className).not.toContain("hover:bg-neutral-200");
      expect(pill.className).not.toContain("bg-brand ");
      expect(pill.className).not.toContain("text-white");
    });
  });

  it("активная пилли хранит индиго-заливку (bg-brand + text-white), остальные остаются по паттерну RouteCard", () => {
    renderSection("eda");
    const active = screen.getByRole("button", { name: STAGE_LABELS_RU.eda });
    expect(active.className).toContain("bg-brand ");
    expect(active.className).toContain("text-white");
    expect(active.className).not.toContain("bg-brand-light");
    // остальные пилли — пассивные по паттерну
    const passive = screen.getByRole("button", { name: "Все этапы" });
    expect(passive.className).toContain("bg-brand-light/60");
    expect(passive.className).toContain("border-brand/60");
    expect(passive.className).not.toContain("bg-brand ");
  });
});
