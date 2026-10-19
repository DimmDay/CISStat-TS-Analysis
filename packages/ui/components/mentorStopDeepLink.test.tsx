// packages/ui/components/mentorStopDeepLink.test.tsx
//
// Интеграционные тесты узловых deep-link Наставника (Task MNS-LINK-3,
// план docs/mentor_next_step_review_2026-10-19.md §6; контракт --
// spec_mentor_next_step.md §5.3, решение Q6) для ТРЁХ warning-способных
// степперов (upload 5 + validation 10 + preprocessing 10 = 25 остановок):
//
// (1) якорь #stop=<node_id> при МОНТИРОВАНИИ выбирает остановку
//     (cross-stage переход, перезагрузка, закладка);
// (2) неизвестный/чужой узел в якоре -- fail-closed: степпер остаётся
//     на дефолтной остановке (паттерн allowlist-перехвата PROGR-3);
// (3) same-route переход -- явное событие GOTO_STOP_EVENT: панель
//     «Прогресс» доступна на всех модульных страницах, клик по
//     рекомендации на уже открытой вкладке обязан переключить остановку;
//     семантика переключения = клик по остановке (закрытие Справки --
//     инвариант UI-UPLOAD-HELP-1/VALID-2).
//
// Активная остановка ассертится по классам кнопки степпера
// (bg-brand text-white) -- тот же признак, что используют тесты
// степперов; fetch -- best-effort мок «без датасета» (паттерн
// TsAnalysisValidation.test.tsx): компоненты рендерятся без данных.

import { fireEvent, render, screen, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { TsAnalysisValidation } from "./TsAnalysisValidation";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { AppShellProvider } from "../context/AppShellContext";
import { GOTO_STOP_EVENT } from "../lib/stopLinks";

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

beforeEach(() => {
  // Паттерн TsAnalysisValidation.test.tsx: провайдер гидрируется «без
  // датасета» -- степперы рендерятся с pending-статусами, данных нет.
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
  jest.clearAllMocks();
});

function expectStopActive(label: RegExp) {
  const button = screen.getByRole("button", { name: label });
  expect(button.className).toContain("bg-brand");
  expect(button.className).toContain("text-white");
}

function expectStopNotActive(label: RegExp) {
  const button = screen.getByRole("button", { name: label });
  expect(button.className).not.toContain("bg-brand");
}

// ── Валидация (10 остановок) ─────────────────────────────────────────

function renderValidation() {
  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>,
  );
}

describe("TsAnalysisValidation: deep-link остановки (MNS-LINK-3)", () => {
  it("якорь #stop=ranges при монтировании активирует «Диапазоны значений»", () => {
    window.location.hash = "stop=ranges";
    renderValidation();
    expectStopActive(/^Диапазоны значений/);
    expectStopNotActive(/^Типы данных/);
  });

  it("неизвестный узел в якоре -- fail-closed: активна дефолтная остановка", () => {
    window.location.hash = "stop=nope";
    renderValidation();
    expectStopActive(/^Типы данных/);
    expectStopNotActive(/^Диапазоны значений/);
  });

  it("узел чужой стадии в якоре -- fail-closed (whitelist по своей стадии)", () => {
    window.location.hash = "stop=missing"; // остановка Предобработки
    renderValidation();
    expectStopActive(/^Типы данных/);
  });

  it("same-route: GOTO_STOP_EVENT переключает остановку (панель на той же вкладке)", () => {
    renderValidation();
    expectStopActive(/^Типы данных/);
    fireEvent(
      window,
      new CustomEvent(GOTO_STOP_EVENT, { detail: { stage: "validation", node_id: "uniqueness" } }),
    );
    expectStopActive(/^Уникальность/);
    expectStopNotActive(/^Типы данных/);
  });

  it("событие ЧУЖОЙ стадии игнорируется (степпер своей стадии слушает своё)", () => {
    renderValidation();
    fireEvent(
      window,
      new CustomEvent(GOTO_STOP_EVENT, { detail: { stage: "preprocessing", node_id: "missing" } }),
    );
    expectStopActive(/^Типы данных/);
  });
});

// ── Предобработка (10 остановок) ─────────────────────────────────────

function renderPreprocessing() {
  return render(
    <AppShellProvider>
      <TsAnalysisPreprocessing />
    </AppShellProvider>,
  );
}

describe("TsAnalysisPreprocessing: deep-link остановки (MNS-LINK-3)", () => {
  it("якорь #stop=outliers при монтировании активирует «Выбросы»", () => {
    window.location.hash = "stop=outliers";
    renderPreprocessing();
    expectStopActive(/^Выбросы/);
    expectStopNotActive(/^Пропуски/);
  });

  it("неизвестный узел в якоре -- fail-closed: активны «Пропуски» (дефолт)", () => {
    window.location.hash = "stop=nope";
    renderPreprocessing();
    expectStopActive(/^Пропуски/);
  });

  it("same-route: GOTO_STOP_EVENT активирует «Стационарность ряда»", () => {
    renderPreprocessing();
    expectStopActive(/^Пропуски/);
    fireEvent(
      window,
      new CustomEvent(GOTO_STOP_EVENT, { detail: { stage: "preprocessing", node_id: "stationarity" } }),
    );
    expectStopActive(/^Стационарность ряда/);
  });
});

// ── Загрузка (5 остановок) ───────────────────────────────────────────
// Степпер «Загрузки» гейтится isUploaded (3-колоночный блок — после
// появления датасета). В тестах датасет появляется через штатную
// ГИДРАТАЦИЮ сессии: /session/current возвращает активный датасет,
// компонент подтягивает GET /dataset (UploadApiResponse) — тот же
// путь «Продолжить» с Home. Deep-link читается при МОНТИРОВАНИИ (до
// гидратации): state переживает появление степпера — ровно сценарий
// перехода по ссылке Наставника во вкладку с уже существующей сессией.

const UPLOAD_RESPONSE = {
  dataset_id: "123",
  name: "test.csv",
  rows: 10,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [["date", "value"], ["2023-01-01", "10"], ["2023-01-02", "20"]],
    tail: [["2023-01-09", "90"], ["2023-01-10", "100"]],
  },
  columns_info: [
    { name: "date", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
    { name: "value", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
  ],
  quality: {
    cols_with_missing: 1,
    cols_with_outliers: 0,
    rows_total: 10,
    duplicates: 0,
    missing_cols: ["value"],
    outlier_cols: [],
  },
};

function mockUploadSessionWithDataset() {
  global.fetch = jest.fn((url: string) => {
    const u = String(url);
    if (u.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "d1", name: "test.csv", rows: 10, columns: 2, size_label: "0.01 MB" },
            stages: {},
            last_active_stage: null,
            target_column: null,
            updated_at: null,
          }),
      });
    }
    // GET /v1/session/dataset -- UploadApiResponse для гидратации;
    // прочие dataset/*-профили -- честный отказ (best-effort).
    if (u.endsWith("/session/dataset")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(UPLOAD_RESPONSE) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

function renderUpload() {
  return render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>,
  );
}

async function waitForUploadStepper() {
  await waitFor(() => expect(screen.getByRole("button", { name: /^Превью датасета/ })).toBeInTheDocument());
}

describe("TsAnalysisUpload: deep-link остановки (MNS-LINK-3)", () => {
  it("якорь #stop=quality при монтировании активирует «Качество» (после гидратации)", async () => {
    window.location.hash = "stop=quality";
    mockUploadSessionWithDataset();
    renderUpload();
    await waitForUploadStepper();
    expectStopActive(/^Качество/);
    expectStopNotActive(/^Превью датасета/);
  });

  it("неизвестный узел в якоре -- fail-closed: активно «Превью датасета»", async () => {
    window.location.hash = "stop=nope";
    mockUploadSessionWithDataset();
    renderUpload();
    await waitForUploadStepper();
    expectStopActive(/^Превью датасета/);
  });

  it("same-route: GOTO_STOP_EVENT активирует «Структура»", async () => {
    mockUploadSessionWithDataset();
    renderUpload();
    await waitForUploadStepper();
    expectStopActive(/^Превью датасета/);
    fireEvent(
      window,
      new CustomEvent(GOTO_STOP_EVENT, { detail: { stage: "upload", node_id: "structure" } }),
    );
    expectStopActive(/^Структура/);
  });
});
