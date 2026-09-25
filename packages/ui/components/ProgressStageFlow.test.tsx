// packages/ui/components/ProgressStageFlow.test.tsx
//
// Тесты блок-схемы 6 стадий (Task PROGR-4, spec_progress.md §6.2):
// карточки с лёгким цветным фоном по свёртке §12 п.10 (bg-green-50 /
// bg-amber-50 / нейтральный), иконка статуса StatusIcon как есть,
// краткая подпись ("3/10, найдены проблемы" / "6/10, в работе" /
// "не начато"), разворачивание стадии -- список узлов с их статусом,
// клик по узлу -- deep-link на вкладку стадии (не дублирует UI
// остановки внутри панели).

import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProgressStageFlow } from "./ProgressStageFlow";
import type { TraceEventInfo } from "../lib/progress";

const ev = (overrides: Partial<TraceEventInfo>): TraceEventInfo => ({
  event_id: "e1",
  run_id: "RUN-TEST000",
  ts: "2026-09-25T10:00:00+00:00",
  stage: "validation",
  node_id: "formats",
  event_type: "correction_applied",
  payload: {},
  actor: "user",
  ...overrides,
});

describe("ProgressStageFlow", () => {
  it("рендерирует ровно 6 карточек стадий в порядке STAGE_DEFS", () => {
    render(<ProgressStageFlow events={[]} />);
    const labels = ["Загрузка", "Валидация", "Предобработка", "Разведочный EDA", "Моделирование", "Прогнозирование"];
    labels.forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: /Стадия/ })).toHaveLength(6);
  });

  it("пройденная стадия -- зелёный фон bg-green-50 и подпись «1/1, пройдено»", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "upload", node_id: "structure_confirmed", event_type: "upload_completed" })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card.className).toContain("bg-green-50");
    expect(screen.getByText("1/1, пройдено")).toBeInTheDocument();
  });

  it("стадия с warning -- жёлтый фон bg-amber-50 и «найдены проблемы» (§12 п.10)", () => {
    render(
      <ProgressStageFlow
        events={[
          // Образец §6.2 «3/10, найдены проблемы»: одна проверка пройдена,
          // по другой найдены проблемы (preview есть -- решение не принято).
          ev({ stage: "validation", node_id: "data_types", event_type: "correction_applied" }),
          ev({ stage: "validation", node_id: "formats", event_type: "correction_previewed" }),
        ]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Валидация/ });
    expect(card.className).toContain("bg-amber-50");
    expect(screen.getByText("1/10, найдены проблемы")).toBeInTheDocument();
  });

  it("частично пройденная процессная стадия -- жёлтая «в работе»", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "modeling", node_id: "backtest", event_type: "backtest_run" })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Моделирование/ });
    expect(card.className).toContain("bg-amber-50");
    expect(screen.getByText("1/11, в работе")).toBeInTheDocument();
  });

  it("стадия без событий -- нейтральный фон и «не начато»", () => {
    render(<ProgressStageFlow events={[]} />);
    const card = screen.getByRole("button", { name: /Стадия Прогнозирование/ });
    expect(card.className).toContain("bg-white");
    expect(card.className).not.toContain("bg-green-50");
    expect(card.className).not.toContain("bg-amber-50");
    // Все 6 стадий без событий -- «не начато» на каждой.
    expect(screen.getAllByText("не начато")).toHaveLength(6);
  });

  it("карточка несёт иконку статуса (StatusIcon, переиспользуется как есть)", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "upload", node_id: "structure_confirmed", event_type: "upload_completed" })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card.querySelector("svg")).not.toBeNull();
  });

  it("клик по карточке разворачивает список узлов с их статусами", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "validation", node_id: "formats", event_type: "correction_applied" })]}
      />
    );
    // До клика узлы скрыты.
    expect(screen.queryByText("Форматы и шаблоны")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    // После клика -- список всех 10 узлов стадии с метками.
    expect(screen.getByText("Форматы и шаблоны")).toBeInTheDocument();
    expect(screen.getByText("Типы данных")).toBeInTheDocument();
    expect(screen.getByText("Достаточность наблюдений")).toBeInTheDocument();
  });

  it("развернутые узлы -- deep-link на вкладку стадии (href, §6.2)", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "eda", node_id: "correlation", event_type: "profile_viewed" })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Разведочный EDA/ }));
    const link = screen.getByRole("link", { name: /Корреляция \(ACF\/PACF\)/ });
    expect(link).toHaveAttribute("href", "/eda");
  });

  it("узлы без событий показывают статус «Не запускалось» (pending)", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "validation", node_id: "formats", event_type: "correction_applied" })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    const untouched = screen.getByRole("link", { name: /Диапазоны значений/ });
    expect(untouched.querySelector('svg[aria-label="Не запускалось"]')).not.toBeNull();
    const applied = screen.getByRole("link", { name: /Форматы и шаблоны/ });
    expect(applied.querySelector('svg[aria-label="Пройдено"]')).not.toBeNull();
  });

  it("повторный клик по карточке сворачивает список", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "validation", node_id: "formats", event_type: "correction_applied" })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Валидация/ });
    fireEvent.click(card);
    expect(screen.getByText("Форматы и шаблоны")).toBeInTheDocument();
    fireEvent.click(card);
    expect(screen.queryByText("Форматы и шаблоны")).toBeNull();
  });

  it("развёрнутая карточка имеет aria-expanded='true'", () => {
    render(
      <ProgressStageFlow
        events={[ev({ stage: "upload", node_id: "structure_confirmed", event_type: "upload_completed" })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(card);
    expect(card).toHaveAttribute("aria-expanded", "true");
  });
});
