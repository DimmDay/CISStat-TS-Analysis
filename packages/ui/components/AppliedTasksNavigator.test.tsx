import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { AppliedTasksNavigator } from "./AppliedTasksNavigator";
import { NavigatorHero } from "./NavigatorHero";
import {
  APPLIED_TASK_DOMAINS,
  APPLIED_TASK_KINDS,
  getAppliedTaskExamples,
} from "../lib/applied-tasks";

describe("applied tasks data matrix", () => {
  it("contains 6 domains, 5 task kinds and exactly 4 examples in every cell", () => {
    expect(APPLIED_TASK_DOMAINS).toHaveLength(6);
    expect(APPLIED_TASK_KINDS).toHaveLength(5);

    APPLIED_TASK_DOMAINS.forEach((domain) => {
      APPLIED_TASK_KINDS.forEach((kind) => {
        const examples = getAppliedTaskExamples(domain.id, kind.id);
        expect(examples).toHaveLength(4);
        expect(new Set(examples.map((example) => example.id)).size).toBe(4);
        examples.forEach((example) => {
          expect(example.title.length).toBeGreaterThan(8);
          expect(example.description.length).toBeGreaterThan(40);
          expect(example.result.length).toBeGreaterThan(20);
        });
      });
    });
  });

  it("preserves all 30 examples from the attached workbook as the first item", () => {
    const sourceTitles = {
      government: [
        "Планирование бюджета региона",
        "Оценка эффектов налоговой реформы",
        "Влияние мер соцподдержки на бедность",
        "Выбор мер стимулирования экономики",
        "Контроль исполнения бюджета",
      ],
      universities: [
        "Прогноз нагрузки на кафедры",
        "Сценарии загрузки общежитий",
        "Влияние формата обучения на успеваемость",
        "Распределение аудиторного фонда",
        "Мониторинг посещаемости и отсева",
      ],
      institutes: [
        "Прогноз активности публикаций",
        "Сценарии финансирования проектов",
        "Влияние цитирования на грантовое финансирование",
        "Приоритизация исследовательских тем",
        "Мониторинг публикационной динамики",
      ],
      business: [
        "Прогноз выручки магазинов",
        "Оценка прибыли при разных рыночных сценариях",
        "Влияние промо и рекламы на продажи",
        "Управление запасами и цепочками поставок",
        "Контроль точности прогноза продаж",
      ],
      researchers: [
        "Прогноз цитируемости статей",
        "Сценарии валидации гипотез",
        "Влияние методологии на воспроизводимость",
        "Выбор стратегии сбора данных",
        "Мониторинг качества данных в реальном времени",
      ],
      developers: [
        "Прогноз числа багов в релизе",
        "Масштабирование инфраструктуры",
        "Влияние рефакторинга на стабильность сервиса",
        "Выбор стека технологий для MVP",
        "Мониторинг метрик ML-моделей",
      ],
    } as const;

    APPLIED_TASK_DOMAINS.forEach((domain) => {
      APPLIED_TASK_KINDS.forEach((kind, kindIndex) => {
        expect(getAppliedTaskExamples(domain.id, kind.id)[0].title).toBe(
          sourceTitles[domain.id][kindIndex],
        );
      });
    });
  });
});

describe("AppliedTasksNavigator", () => {
  it("renders the three-column navigation structure", () => {
    const { container } = render(<AppliedTasksNavigator />);

    expect(screen.getByRole("heading", { name: "Предметная область" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Основная задача" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Описание" })).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("xl:flex-row");
  });

  it("shows four badges and a detailed overview for the default selection", () => {
    render(<AppliedTasksNavigator />);
    const examples = getAppliedTaskExamples("government", "forecasting");

    examples.forEach((example) => {
      expect(screen.getByRole("button", { name: example.title })).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", { name: `Обзор: ${examples[0].title}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(examples[0].description)).toBeInTheDocument();
    expect(screen.getByText(examples[0].result)).toBeInTheDocument();
  });

  it("updates badges when the domain and main task change", () => {
    render(<AppliedTasksNavigator />);

    fireEvent.click(screen.getByRole("button", { name: /ВУЗы/i }));
    fireEvent.click(screen.getByRole("button", { name: /Сценарный анализ/i }));

    const examples = getAppliedTaskExamples("universities", "scenario");
    examples.forEach((example) => {
      expect(screen.getByRole("button", { name: example.title })).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: examples[0].title })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("updates the overview when an applied-task badge is clicked", () => {
    render(<AppliedTasksNavigator />);
    const examples = getAppliedTaskExamples("government", "forecasting");

    fireEvent.click(screen.getByRole("button", { name: examples[2].title }));

    expect(
      screen.getByRole("heading", { name: `Обзор: ${examples[2].title}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(examples[2].description)).toBeInTheDocument();
    expect(screen.getByText(examples[2].result)).toBeInTheDocument();
  });
});

// ── Task NAVBG-3: секция «Примеры прикладных задач» (/navigator) ──────
//
// Постановка: (1) трёхколоночный layout сидит вплотную к границе
// фоновой коробки страницы (0px) — по паттерну главной (Task w/n:
// px-6 — собственные боковые поля 24px; прецедент NAVBG-2 на
// nav-сетке секции 1) корень flex-контейнера получает px-6, причём
// сжатие — ТОЛЬКО за счёт колонки «Описание»; (2) текст четырёх
// бейджей окна «Описание» чуть увеличен (text-xs -> text-sm, один
// шаг шкалы Tailwind). Дизайн-система не меняется.

describe("AppliedTasksNavigator layout (Task NAVBG-3)", () => {
  it("insets the three-column flex container 24px from the page edges on both sides (px-6)", () => {
    const { container } = render(<AppliedTasksNavigator />);
    expect(container.firstChild).toHaveClass("px-6");
  });

  it("keeps «Предметная область» and «Основная задача» widths fixed — compression lands only on «Описание»", () => {
    const { container } = render(<AppliedTasksNavigator />);
    const root = container.firstChild as HTMLElement;
    // Корень — трёхколоночный flex на xl+.
    expect(root).toHaveClass("xl:flex-row");

    const domains = screen
      .getByRole("heading", { name: "Предметная область" })
      .closest("aside")!;
    const kinds = screen
      .getByRole("heading", { name: "Основная задача" })
      .closest("aside")!;
    const description = screen
      .getByRole("heading", { name: "Описание" })
      .closest("section")!;
    expect(domains).not.toBeNull();
    expect(kinds).not.toBeNull();
    expect(description).not.toBeNull();

    // Колонки 1–2: фиксированная ширина + запрет сжатия — НЕ меняются.
    expect(domains).toHaveClass("xl:w-60", "shrink-0");
    expect(kinds).toHaveClass("xl:w-80", "shrink-0");
    // Колонка 3 «Описание»: flex-1 + min-w-0 — единственный
    // потребитель всей дельты сжатия px-6 (механика flexbox).
    expect(description).toHaveClass("flex-1", "min-w-0");
  });

  it("uses the same 24px side-inset token as the section-1 badge grid (cross-test with NavigatorHero)", () => {
    const atn = render(<AppliedTasksNavigator />);
    const hero = render(<NavigatorHero />);
    const atnRoot = atn.container.firstChild as HTMLElement;
    const heroGrid = hero.container.querySelector(
      'nav[aria-label="Разделы знакомства с платформой"]',
    )!;
    expect(heroGrid).not.toBeNull();
    // Один и тот же токен px-6 у корня секции 2 и эталонной сетки
    // бейджей секции 1 (NAVGB-2) — паттерн зазоров един.
    expect(atnRoot.className).toContain("px-6");
    expect(heroGrid.className).toContain("px-6");
  });

  it("renders the four description-window badges with slightly larger text (text-sm, not text-xs)", () => {
    render(<AppliedTasksNavigator />);
    const examples = getAppliedTaskExamples("government", "forecasting");
    expect(examples).toHaveLength(4);
    examples.forEach((example) => {
      const badge = screen.getByRole("button", { name: example.title });
      expect(badge).toHaveClass("text-sm");
      expect(badge.className).not.toContain("text-xs");
    });
  });
});
