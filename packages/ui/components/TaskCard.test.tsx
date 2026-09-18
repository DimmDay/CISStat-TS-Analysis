// packages/ui/components/TaskCard.test.tsx
//
// Юнит-тесты карточки задачи (R3 сертификации IA-1): состояние -> роль,
// href, класс-маппинг SHELL_BY_STATE/ICON_BY_STATE/CHIP_BY_STATE и
// типографическая DNA (text-base заголовок, text-sm описание) защищены
// на уровне самого компонента, а не только косвенно через TasksHub.
// Убивает мутантов M13 (text-base -> text-lg) и M14 (срыв aria-причины).
// Follow-up R5 (симметрия): микро-CTA рендерится в ОБОИХ некликабельных
// состояниях — awaiting (этап-владелец недостающего артефакта) и blocked
// (этап «Загрузка», вход в пайплайн).

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
  outcomes: [
    "Вклад каждого фактора в прогноз",
    "Сравнение сценариев на одном графике",
  ],
};

const CTA_STAGE: StagePointer = {
  key: "modeling",
  label: "Моделирование",
  href: "/modeling",
};

const UPLOAD_STAGE: StagePointer = {
  key: "upload",
  label: "Загрузка",
  href: "/upload",
};

const renderCard = (
  state: "available" | "awaiting" | "blocked",
  reason: string | null,
  extra: { recommendedHint?: string | null; ctaStage?: StagePointer | null } = {}
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

  it("never nests a CTA link even if ctaStage is passed (available IS the link)", () => {
    const { container } = renderCard("available", null, {
      ctaStage: UPLOAD_STAGE,
    });
    // Единственная ссылка — сама карточка; вложенный <a> невалиден в HTML.
    expect(container.querySelectorAll("a")).toHaveLength(1);
    expect(screen.queryByText(/Перейти к этапу/)).toBeNull();
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
      ctaStage: CTA_STAGE,
    });
    const cta = screen.getByRole("link", { name: "Перейти к этапу Моделирование" });
    expect(cta).toHaveAttribute("href", "/modeling");
    expect(cta.className).toContain("text-brand");
  });

  it("renders no micro-CTA when ctaStage is not provided", () => {
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

  it("renders the SYMMETRIC micro-CTA «Перейти к этапу Загрузка» (follow-up R5)", () => {
    const { container } = renderCard(
      "blocked",
      "Начните с этапа Загрузка — задачи работают поверх артефактов пайплайна",
      { ctaStage: UPLOAD_STAGE }
    );
    // CTA — ссылка на вход в пайплайн, та же геометрия/цвет, что в awaiting.
    const cta = screen.getByRole("link", { name: "Перейти к этапу Загрузка" });
    expect(cta).toHaveAttribute("href", "/upload");
    expect(cta.className).toContain("text-brand");
    expect(cta.className).toContain("text-xs");
    expect(cta.className).toContain("focus-visible:ring-brand/50");
    expect(container.querySelector(".lucide-arrow-right")).not.toBeNull();
    // Карточка остаётся group с aria-причиной (CTA вложен в неинтерактивный group).
    expect(
      screen.getByRole("group", { name: /недоступна/ })
    ).toBeInTheDocument();
  });

  it("renders no link when ctaStage is not provided (defensive)", () => {
    renderCard("blocked", "Начните с этапа Загрузка");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/Перейти к этапу/)).toBeNull();
  });
});

// ── Буллеты обещанных результатов (v1.1, §9.3 дополнения) ────────
// Карточка дополняется 2–3 буллетами конкретного обещанного результата
// В ДОПОЛНЕНИЕ к одной строке описания; формулировки — по продукту.
// Буллеты — обещание задачи, видны во ВСЕХ трёх состояниях (это
// методологический контекст, а не гейтинг).

describe("TaskCard outcomes (v1.1 §9.3)", () => {
  it("renders outcome bullets in addition to the description line", () => {
    renderCard("available", null);
    // Описание на месте (строка v1 не заменена, а дополнена).
    expect(screen.getByText("описание фикстуры")).toBeInTheDocument();
    // Оба буллета видны.
    expect(
      screen.getByText("Вклад каждого фактора в прогноз")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Сравнение сценариев на одном графике")
    ).toBeInTheDocument();
  });

  it("renders exactly the declared number of bullets in a dedicated block", () => {
    const { container } = renderCard("available", null);
    const block = container.querySelector("[data-testid='task-outcomes']");
    expect(block).not.toBeNull();
    expect(block!.children).toHaveLength(TASK.outcomes!.length);
  });

  it("shows bullets in non-available states too (promise, not gating)", () => {
    const awaiting = renderCard(
      "awaiting",
      "Станет доступна после этапа Моделирование"
    );
    expect(
      screen.getByText("Вклад каждого фактора в прогноз")
    ).toBeInTheDocument();
    awaiting.unmount();

    renderCard(
      "blocked",
      "Начните с этапа Загрузка — задачи работают поверх артефактов пайплайна"
    );
    expect(
      screen.getByText("Сравнение сценариев на одном графике")
    ).toBeInTheDocument();
  });

  it("bullets are visually compact (text-xs, below the text-sm description)", () => {
    renderCard("available", null);
    const bullet = screen.getByText("Вклад каждого фактора в прогноз");
    expect(bullet.className).toContain("text-xs");
  });

  it("renders no bullet block when outcomes are absent (v1 fixture back-compat)", () => {
    const { container } = render(
      <TaskCard
        task={{ ...TASK, outcomes: undefined }}
        state="available"
        reason={null}
      />
    );
    expect(
      container.querySelector("[data-testid='task-outcomes']")
    ).toBeNull();
  });
});
