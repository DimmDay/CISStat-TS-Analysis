// packages/ui/components/TaskCard.test.tsx
//
// Юнит-тесты карточки задачи (R3 сертификации IA-1): состояние -> роль,
// href, класс-маппинг SHELL_BY_STATE/ICON_BY_STATE/CHIP_BY_STATE и
// типографическая DNA (text-base заголовок, text-sm описание) защищены
// на уровне самого компонента, а не только косвенно через TasksHub.
// Убивает мутантов M13 (text-base -> text-lg) и M14 (срыв aria-причины).

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { Box } from "lucide-react";
import { TaskCard } from "./TaskCard";
import type { StagePointer, TaskRoute } from "../lib/task-stops";

const TASK: TaskRoute = {
  id: "fixture",
  title: "Тестовая задача",
  description: "описание фикстуры",
  icon: Box,
  href: "/tasks/fixture",
  requires: ["model_card"],
};

const AWAIT_STAGE: StagePointer = {
  key: "modeling",
  label: "Моделирование",
  href: "/modeling",
};

const renderCard = (
  state: "available" | "awaiting" | "blocked",
  reason: string | null,
  extra: { recommendedHint?: string | null; awaitStage?: StagePointer | null } = {}
) =>
  render(<TaskCard task={TASK} state={state} reason={reason} {...extra} />);

describe("TaskCard: available", () => {
  it("is a link to task.href with the RouteCard DNA classes", () => {
    const { container } = renderCard("available", null);
    const link = screen.getByRole("link", { name: /Тестовая задача/ });
    expect(link).toHaveAttribute("href", "/tasks/fixture");
    expect(link.className).toContain("rounded-xl");
    expect(link.className).toContain("border-brand/60");
    expect(link.className).toContain("bg-brand-light/60");
    expect(link.className).toContain("hover:border-brand/90");
    expect(link.className).toContain("focus-visible:ring-brand/50");
    // Иконка available: brand-круг с hover-инверсией.
    const iconWrap = container.querySelector("span[aria-hidden='true']");
    expect(iconWrap?.className).toContain("bg-brand-light");
    expect(iconWrap?.className).toContain("group-hover:bg-brand");
  });

  it("keeps the typographic DNA: title text-base, description text-sm", () => {
    renderCard("available", null);
    const title = screen.getByText("Тестовая задача");
    expect(title.className).toContain("text-base");
    expect(title.className).not.toContain("text-lg");
    const description = screen.getByText("описание фикстуры");
    expect(description.className).toContain("text-sm");
  });

  it("renders no reason chip and no Lock icon", () => {
    const { container } = renderCard("available", null);
    expect(container.querySelector(".lucide-lock")).toBeNull();
    expect(screen.queryByText(/Начните с этапа/)).toBeNull();
  });

  it("renders the recommended-artifact ghost hint when provided (R2)", () => {
    const { container } = renderCard("available", null, {
      recommendedHint: "Рекомендуется также этап Прогнозирование",
    });
    const hint = screen.getByText("Рекомендуется также этап Прогнозирование");
    // Плашка-призрак: пунктирная brand-рамка, brand-текст.
    expect(hint.className).toContain("border-dashed");
    expect(hint.className).toContain("border-brand/40");
    expect(hint.className).toContain("text-brand");
    expect(container.querySelector(".lucide-sparkles")).not.toBeNull();
    // Карточка остаётся ссылкой.
    expect(screen.getByRole("link", { name: /Тестовая задача/ })).toBeInTheDocument();
  });

  it("renders no hint when recommendedHint is null/undefined", () => {
    renderCard("available", null, { recommendedHint: null });
    expect(screen.queryByText(/Рекомендуется/)).toBeNull();
  });
});

describe("TaskCard: awaiting", () => {
  it("is a non-link group with aria-label naming task and reason", () => {
    const { container } = renderCard(
      "awaiting",
      "Станет доступна после этапа Моделирование"
    );
    expect(screen.queryByRole("link")).toBeNull();
    const group = screen.getByRole("group", {
      name: /Задача «Тестовая задача» недоступна: Станет доступна после этапа Моделирование/,
    });
    expect(group).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });

  it("applies amber shell/icon/chip classes", () => {
    const { container } = renderCard(
      "awaiting",
      "Станет доступна после этапа Моделирование"
    );
    const group = screen.getByRole("group");
    expect(group.className).toContain("border-amber-300");
    expect(group.className).toContain("bg-amber-50/60");
    const iconWrap = container.querySelector("span[aria-hidden='true']");
    expect(iconWrap?.className).toContain("bg-amber-100");
    const chip = screen.getByText(/Станет доступна после этапа/);
    expect(chip.className).toContain("bg-amber-100/80");
    expect(chip.className).toContain("text-amber-700");
    expect(container.querySelector(".lucide-lock")).not.toBeNull();
  });

  it("keeps the typographic DNA in non-available states too", () => {
    renderCard("awaiting", "причина");
    expect(screen.getByText("Тестовая задача").className).toContain("text-base");
    expect(screen.getByText("описание фикстуры").className).toContain("text-sm");
  });

  it("renders the micro-CTA to the awaiting stage when provided (R5)", () => {
    renderCard("awaiting", "Станет доступна после этапа Моделирование", {
      awaitStage: AWAIT_STAGE,
    });
    const cta = screen.getByRole("link", { name: "Перейти к этапу Моделирование" });
    expect(cta).toHaveAttribute("href", "/modeling");
    expect(cta.className).toContain("text-brand");
  });

  it("renders no micro-CTA when awaitStage is not provided", () => {
    renderCard("awaiting", "причина");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/Перейти к этапу/)).toBeNull();
  });
});

describe("TaskCard: blocked", () => {
  it("is a non-link group with neutral shell and full aria reason (kills M14)", () => {
    const { container } = renderCard(
      "blocked",
      "Начните с этапа Загрузка — задачи работают поверх артефактов пайплайна"
    );
    expect(screen.queryByRole("link")).toBeNull();
    const group = screen.getByRole("group", {
      name: /Задача «Тестовая задача» недоступна: Начните с этапа Загрузка/,
    });
    expect(group.className).toContain("border-neutral-200");
    expect(group.className).toContain("bg-white");
    const iconWrap = container.querySelector("span[aria-hidden='true']");
    expect(iconWrap?.className).toContain("bg-neutral-100");
    const chip = screen.getByText(/Начните с этапа Загрузка/);
    expect(chip.className).toContain("bg-neutral-100");
    expect(chip.className).toContain("text-neutral-500");
    expect(container.querySelector(".lucide-lock")).not.toBeNull();
  });

  it("never renders the micro-CTA even if awaitStage is passed", () => {
    renderCard("blocked", "Начните с этапа Загрузка", {
      awaitStage: AWAIT_STAGE,
    });
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/Перейти к этапу/)).toBeNull();
  });
});
