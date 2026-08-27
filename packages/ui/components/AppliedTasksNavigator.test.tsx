import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { AppliedTasksNavigator } from "./AppliedTasksNavigator";
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
