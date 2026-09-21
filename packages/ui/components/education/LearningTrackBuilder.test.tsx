// packages/ui/components/education/LearningTrackBuilder.test.tsx
//
// Task EDU-2 (spec_education.md, §2.2) — контракты конструктора
// персональных обучающих стеков. Билдер — UI над buildLearningStack(),
// поэтому тесты страхуют связку UI ↔ слой знаний:
//   - чекбоксы дают МНОЖЕСТВО направлений (не радио);
//   - счётчики статей у чекбоксов честные (включая 0 → «справка готовится»);
//   - построенный стек: порядок пайплайна §13 независимо от порядка кликов;
//   - пустой результат — явное «справка готовится» (no fabricated results);
//   - клик по статье стека открывает её через onOpenArticle (ридер хаба);
//   - термины стека рендерятся только связанные со статьями стека.

import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { LearningTrackBuilder } from "./LearningTrackBuilder";
import {
  buildLearningStack,
  getDirectionArticleCounts,
  getPublishedArticles,
} from "../../lib/knowledge/knowledge";
import {
  DIRECTION_LABELS_RU,
  KNOWLEDGE_DIRECTIONS,
  KNOWLEDGE_STAGES,
  STAGE_LABELS_RU,
} from "../../lib/knowledge/types";

const published = getPublishedArticles();
const counts = getDirectionArticleCounts();

function renderBuilder() {
  const onOpenArticle = jest.fn();
  render(<LearningTrackBuilder onOpenArticle={onOpenArticle} />);
  return { onOpenArticle };
}

function toggleDirection(label: string) {
  fireEvent.click(screen.getByRole("checkbox", { name: label }));
}

function build() {
  fireEvent.click(screen.getByRole("button", { name: "Построить персональный стек" }));
}

describe("LearningTrackBuilder — выбор направлений (§2.2)", () => {
  it("рендерит ровно 8 чекбоксов направлений с русскими метками", () => {
    renderBuilder();
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      expect(
        screen.getByRole("checkbox", { name: DIRECTION_LABELS_RU[direction] }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByRole("checkbox")).toHaveLength(KNOWLEDGE_DIRECTIONS.length);
  });

  it("это чекбоксы (множество), а не радио: выбор нескольких направлений одновременно", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    toggleDirection(DIRECTION_LABELS_RU.intervals);
    expect(screen.getByRole("checkbox", { name: DIRECTION_LABELS_RU.seasonality }))
      .toBeChecked();
    expect(screen.getByRole("checkbox", { name: DIRECTION_LABELS_RU.intervals }))
      .toBeChecked();
    expect(screen.getByText("Выбрано направлений: 2")).toBeInTheDocument();
  });

  it("повторный клик снимает выбор (переключение)", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    expect(screen.getByRole("checkbox", { name: DIRECTION_LABELS_RU.seasonality }))
      .not.toBeChecked();
  });

  it("счётчики у чекбоксов честные: количество статей направления из слоя знаний", () => {
    renderBuilder();
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      const checkbox = screen.getByRole("checkbox", {
        name: DIRECTION_LABELS_RU[direction],
      });
      const row = checkbox.closest("label") as HTMLElement;
      const expected =
        counts[direction] > 0 ? `${counts[direction]} ст.` : "справка готовится";
      expect(within(row).getByText(expected)).toBeInTheDocument();
    }
    // направления без опубликованных статей честно помечены
    const emptyDirections = KNOWLEDGE_DIRECTIONS.filter((d) => counts[d] === 0);
    expect(emptyDirections.length).toBeGreaterThan(0);
  });

  it("до построения кнопка disabled и показан честный нейтральный текст", () => {
    renderBuilder();
    expect(screen.getByRole("button", { name: "Построить персональный стек" }))
      .toBeDisabled();
    expect(screen.getByText(/Траектория ещё не построена/)).toBeInTheDocument();
  });
});

describe("LearningTrackBuilder — построение стека (§2.2, §13)", () => {
  it("стек по одному направлению содержит статьи этого направления", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    build();
    const expected = buildLearningStack(["seasonality"]).articles;
    expect(expected.length).toBeGreaterThan(0);
    const lists = screen.getAllByRole("list", {
      name: /^Стек этапа «.+»$/,
    });
    const renderedTitles = lists.flatMap((list) =>
      within(list).getAllByRole("listitem").map((li) => li.textContent ?? ""),
    );
    expect(renderedTitles.length).toBe(expected.length);
    for (const article of expected) {
      expect(
        renderedTitles.some((t) => t.includes(article.title)),
      ).toBe(true);
    }
  });

  it("стек сгруппирован по этапам пайплайна: заголовки этапов идут в порядке §13", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.methodology_validation);
    build();
    const badges = screen
      .getAllByLabelText(/^Этап пайплайна: /)
      .map((el) => el.textContent ?? "");
    const stageOrder = KNOWLEDGE_STAGES.map((s) => STAGE_LABELS_RU[s]);
    const positions = badges.map((b) =>
      stageOrder.findIndex((label) => b.includes(label)),
    );
    for (let i = 1; i < positions.length; i++) {
      expect(positions[i - 1]).toBeLessThan(positions[i]);
    }
  });

  it("множество направлений — объединение без дублей, объём совпадает со слоем знаний", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    toggleDirection(DIRECTION_LABELS_RU.intervals);
    toggleDirection(DIRECTION_LABELS_RU.neural);
    build();
    const expected = buildLearningStack(["seasonality", "intervals", "neural"]);
    const totalBadge = screen.getByText(/Персональный стек: \d+/);
    expect(totalBadge.textContent).toContain(
      String(expected.articles.length),
    );
    const titles = expected.articles.map((a) => a.title);
    expect(new Set(titles).size).toBe(titles.length);
    for (const title of titles) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("порядок кликов по чекбоксам не влияет на построенный стек (DOM)", () => {
    const buildAndReadDom = (first: string, second: string) => {
      const utils = render(<LearningTrackBuilder onOpenArticle={jest.fn()} />);
      toggleDirection(first);
      toggleDirection(second);
      build();
      const titles = screen
        .getAllByRole("list", { name: /^Стек этапа «.+»$/ })
        .flatMap((list) =>
          within(list).getAllByRole("listitem").map((li) => li.textContent ?? ""),
        );
      utils.unmount();
      return titles;
    };

    // одинаковые множества направлений — разный порядок кликов
    const orderA = buildAndReadDom(
      DIRECTION_LABELS_RU.neural,
      DIRECTION_LABELS_RU.intervals,
    );
    const orderB = buildAndReadDom(
      DIRECTION_LABELS_RU.intervals,
      DIRECTION_LABELS_RU.neural,
    );
    expect(orderA.length).toBeGreaterThan(0);
    expect(orderA).toEqual(orderB);
  });

  it("только направления без статей → честное «справка готовится», стек не рисуется", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.volatility); // 0 статей
    toggleDirection(DIRECTION_LABELS_RU.multivariate); // 0 статей
    build();
    expect(
      screen.getByText(/По выбранным направлениям справка готовится/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Персональный стек:/)).toBeNull();
  });

  it("термины траектории: только связанные со статьями стека, без «в пустоту»", () => {
    renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    build();
    const expected = buildLearningStack(["seasonality"]);
    const termsList = screen.getByRole("list", {
      name: "Термины обучающего стека",
    });
    expect(within(termsList).getAllByRole("listitem").length).toBe(
      expected.terms.length,
    );
    for (const term of expected.terms) {
      expect(within(termsList).getByText(term.term)).toBeInTheDocument();
    }
  });
});

describe("LearningTrackBuilder — интеграция с ридером хаба", () => {
  it("клик по статье стека вызывает onOpenArticle с article_id", () => {
    const { onOpenArticle } = renderBuilder();
    toggleDirection(DIRECTION_LABELS_RU.seasonality);
    build();
    const article = buildLearningStack(["seasonality"]).articles[0];
    fireEvent.click(screen.getByText(article.title));
    expect(onOpenArticle).toHaveBeenCalledWith(article.article_id);
  });

  it("все статьи реестра доступны хотя бы в одном стеке (связность данных)", () => {
    const allDirections = KNOWLEDGE_DIRECTIONS.filter((d) => counts[d] > 0);
    const stack = buildLearningStack(allDirections);
    expect(stack.articles.length).toBe(published.length);
  });
});