// packages/ui/components/ProgressStageFlow.test.tsx
//
// Тесты блок-схемы 6 стадий (Task PROGR-4, spec_progress.md §6.2):
// карточки с лёгким цветным фоном по свёртке §12 п.10 (bg-green-50 /
// bg-amber-50 / нейтральный), иконка статуса StatusIcon как есть,
// краткая подпись ("3/10, найдены проблемы" / "6/10, в работе" /
// "не начато"), разворачивание стадии -- список узлов с их статусом,
// клик по узлу -- deep-link на вкладку стадии (не дублирует UI
// остановки внутри панели).
//
// PROGR-10 (Расхождение №1): компонент потребляет ГОТОВОЕ состояние
// (props {statuses, stages} из /trace) -- вычисление на бэкенде
// (единый движок app/core/node_status.py); здесь -- рендер готовых
// фактов и честный фоллбек стадии, отсутствующей в ответе.

import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProgressStageFlow } from "./ProgressStageFlow";
import type { NodeStateInfo, StageStateInfo } from "../lib/progress";

const state = (overrides: Partial<StageStateInfo>): StageStateInfo => ({
  stage: "validation",
  fold: "not_started",
  done_count: 0,
  warning_nodes: 0,
  total_nodes: 10,
  ...overrides,
});

const node = (overrides: Partial<NodeStateInfo>): NodeStateInfo => ({
  stage: "validation",
  node_id: "formats",
  status: "done",
  status_reason: null,
  mode: null,
  last_touched_at: null,
  summary_count: null,
  ...overrides,
});

describe("ProgressStageFlow (готовое состояние, PROGR-10)", () => {
  it("рендерирует ровно 6 карточек стадий в порядке STAGE_DEFS", () => {
    render(<ProgressStageFlow statuses={{}} stages={[]} />);
    const labels = ["Загрузка", "Валидация", "Предобработка", "Разведочный EDA", "Моделирование", "Прогнозирование"];
    labels.forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: /Стадия/ })).toHaveLength(6);
  });

  it("стадия, отсутствующая в ответе (сеть/старый бэкенд), -- честное «не начато» из реестра узлов", () => {
    render(<ProgressStageFlow statuses={{}} stages={[]} />);
    const card = screen.getByRole("button", { name: /Стадия Валидация/ });
    expect(card.className).toContain("bg-white");
    // Все 6 стадий «не начато»; тотал Валидации -- из живого реестра
    // узлов (10), не 0.
    expect(screen.getAllByText("не начато")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    expect(screen.getByText("Типы данных")).toBeInTheDocument();
  });

  it("пройденная стадия -- зелёный фон bg-green-50 и подпись «1/1, пройдено»", () => {
    render(
      <ProgressStageFlow
        statuses={{ "upload/structure_confirmed": "done" }}
        stages={[state({ stage: "upload", fold: "passed", done_count: 1, total_nodes: 1 })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card.className).toContain("bg-green-50");
    expect(screen.getByText("1/1, пройдено")).toBeInTheDocument();
  });

  it("стадия с warning -- жёлтый фон bg-amber-50 и «найдены проблемы» (§12 п.10)", () => {
    render(
      <ProgressStageFlow
        statuses={{
          "validation/data_types": "done",
          "validation/formats": "warning",
        }}
        stages={[state({ stage: "validation", fold: "attention", done_count: 1, warning_nodes: 1 })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Валидация/ });
    expect(card.className).toContain("bg-amber-50");
    expect(screen.getByText("1/10, найдены проблемы")).toBeInTheDocument();
  });

  it("частично пройденная процессная стадия -- жёлтая «в работе» (running без warning)", () => {
    render(
      <ProgressStageFlow
        statuses={{ "modeling/backtest": "done", "modeling/diagnostics": "running" }}
        stages={[state({ stage: "modeling", fold: "attention", done_count: 1, total_nodes: 11 })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Моделирование/ });
    expect(card.className).toContain("bg-amber-50");
    expect(screen.getByText("1/11, в работе")).toBeInTheDocument();
  });

  it("карточка несёт иконку статуса (StatusIcon, переиспользуется как есть)", () => {
    render(
      <ProgressStageFlow
        statuses={{ "upload/structure_confirmed": "done" }}
        stages={[state({ stage: "upload", fold: "passed", done_count: 1, total_nodes: 1 })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card.querySelector("svg")).not.toBeNull();
  });

  it("клик по карточке разворачивает список узлов со статусами из props", () => {
    render(
      <ProgressStageFlow
        statuses={{ "validation/formats": "done" }}
        stages={[state({ stage: "validation", fold: "attention", done_count: 1, warning_nodes: 0 })]}
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
        statuses={{ "eda/correlation": "running" }}
        stages={[state({ stage: "eda", fold: "attention", total_nodes: 10 })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Разведочный EDA/ }));
    const link = screen.getByRole("link", { name: /Корреляция \(ACF\/PACF\)/ });
    expect(link).toHaveAttribute("href", "/eda");
  });

  it("узлы без фактов показывают статус «Не запускалось» (pending)", () => {
    render(
      <ProgressStageFlow
        statuses={{ "validation/formats": "done" }}
        stages={[state({ stage: "validation", fold: "attention", done_count: 1 })]}
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
        statuses={{ "validation/formats": "done" }}
        stages={[state({ stage: "validation", fold: "attention", done_count: 1 })]}
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
        statuses={{ "upload/structure_confirmed": "done" }}
        stages={[state({ stage: "upload", fold: "passed", done_count: 1, total_nodes: 1 })]}
      />
    );
    const card = screen.getByRole("button", { name: /Стадия Загрузка/ });
    expect(card).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(card);
    expect(card).toHaveAttribute("aria-expanded", "true");
  });
});

describe("ProgressStageFlow (полные состояния узлов §3, PROGR-11)", () => {
  it("узел с summary_count показывает число правого бейджа (§3)", () => {
    render(
      <ProgressStageFlow
        statuses={{ "preprocessing/missing": "done" }}
        stages={[state({ stage: "preprocessing", fold: "passed", done_count: 1, total_nodes: 10 })]}
        nodes={[node({ stage: "preprocessing", node_id: "missing", summary_count: 12 })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Предобработка/ }));
    const badge = screen.getByTestId("node-badge-preprocessing-missing");
    expect(badge.textContent).toBe("12");
  });

  it("узел без summary_count бейджа не имеет (число не выдумывается)", () => {
    render(
      <ProgressStageFlow
        statuses={{ "eda/correlation": "running" }}
        stages={[state({ stage: "eda", fold: "attention", total_nodes: 10 })]}
        nodes={[node({ stage: "eda", node_id: "correlation" })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Разведочный EDA/ }));
    expect(screen.queryByTestId("node-badge-eda-correlation")).toBeNull();
  });

  it("mode узла рендерится человекочитаемой меткой (авто/вкл/выкл)", () => {
    render(
      <ProgressStageFlow
        statuses={{}}
        stages={[state({})]}
        nodes={[
          node({ node_id: "formats", mode: "disabled" }),
          node({ node_id: "ranges", mode: "auto" }),
        ]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    expect(screen.getByTestId("node-mode-validation-formats").textContent).toBe("выкл");
    expect(screen.getByTestId("node-mode-validation-ranges").textContent).toBe("авто");
  });

  it("mode неприменим (null, вне Валидации/Предобработки) -- чипа нет", () => {
    render(
      <ProgressStageFlow
        statuses={{}}
        stages={[state({ stage: "eda" })]}
        nodes={[node({ stage: "eda", node_id: "correlation", mode: null })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Разведочный EDA/ }));
    expect(screen.queryByTestId("node-mode-eda-correlation")).toBeNull();
  });

  it("status_reason рендерится второй строкой узла", () => {
    render(
      <ProgressStageFlow
        statuses={{ "validation/formats": "done" }}
        stages={[state({ fold: "attention", done_count: 1 })]}
        nodes={[node({ status_reason: "Коррекция применена" })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    expect(screen.getByText("Коррекция применена")).toBeInTheDocument();
  });

  it("nodes не пришёл (старый бэкенд/N-3) -- рендер как прежде, без бейджей и причин", () => {
    render(
      <ProgressStageFlow
        statuses={{ "validation/formats": "done" }}
        stages={[state({ fold: "attention", done_count: 1 })]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Стадия Валидация/ }));
    expect(screen.getByText("Форматы и шаблоны")).toBeInTheDocument();
    expect(screen.queryByText("Коррекция применена")).toBeNull();
  });
});
