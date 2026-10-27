// packages/ui/components/documentation-environment-lost.test.tsx
//
// Task ID: DOCLOG-H29-UIHONEST-AUDITVIEW (2026-10-27) -- рекомендация
// «UI-честность» из AUTH-SCENARIO-ANALYST-DOCS §6 (база a4277b9).
//
// КОНТРАКТ (uniform-404 НЕ ослабляется, T1/R09 -- «знание run_id не
// право»; причина выбора фразы -- КОНТЕКСТ получения run_id на
// клиенте, не существование чужих ресурсов):
//
//   1. run_id разрешён ТОЙ ЖЕ сессией (resolveCurrentRun/свежий trace,
//      runIdSource="session") и список документов ответил 404 ->
//      «Исследование недоступно в этой среде -- возможно, потеряно
//      после рестарта сервиса» + кнопка «Открыть текущее исследование»
//      (класс S4/S5 H29-сценария: run потерян средой при живой
//      сессии; право никто не нарушал, фраза «Доступ запрещён»
//      вводила в заблуждение);
//   2. run_id из deep-link ?run= (runIdSource="link") и 404 ->
//      БЕЗАЛЬТЕРНАТИВНОЕ «Доступ запрещён» (прежний контракт: ссылка
//      может указывать на чужой ресурс);
//   3. проп не передан (встроенные вызовы) -> прежний контракт;
//   4. 403 при session-resolved -> «Доступ запрещён» (только 404 --
//      «запуск не найден» -- трактуется как потеря среды);
//   5. offline (status null) -- прежнее отдельное состояние;
//   6. кнопка: resolveCurrentRun вернул ДРУГОЙ/тот же run -> список
//      перечитывается; run_id null -> честный no-run; сеть недоступна
//      -> offline.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./DocumentationWorkspace";

jest.mock("../lib/documentation", () => ({
  listDocuments: jest.fn(),
  resolveCurrentRun: jest.fn(),
  createDraft: jest.fn(),
  getRevision: jest.fn(),
  requestRendition: jest.fn(),
  getJob: jest.fn(),
  cancelJob: jest.fn(),
  getLifecycle: jest.fn(),
  decideApproval: jest.fn(),
  requestApproval: jest.fn(),
  publishRevision: jest.fn(),
  retractRevision: jest.fn(),
  getRevisionDiff: jest.fn(),
  renditionContentUrl: (id: string) => `/v1/documentation/renditions/${id}/content`,
  revisionPreviewUrl: (id: string) => `/v1/documentation/revisions/${id}/preview`,
}));

import * as documentation from "../lib/documentation";

const mocked = documentation as jest.Mocked<typeof documentation>;

const FORBIDDEN_TEXT =
  "Доступ запрещён — документы этого исследования недоступны вашему субъекту";
const ENV_LOST_TEXT = "Исследование недоступно в этой среде";
const REOPEN_BUTTON = "Открыть текущее исследование";

beforeEach(() => {
  jest.resetAllMocks();
});

describe("DocumentationWorkspace — UI-честность по контексту run_id (H29/UIH)", () => {
  it("session-resolved run + 404 списка: «исследование недоступно в этой среде» вместо «Доступ запрещён», кнопка повторного открытия присутствует", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByRole("alert", { name: /исследование недоступно/i })).toBeInTheDocument();
    });
    // Фраза видна и в строке статуса (desktop-область), и в alert
    // preview-панели -- честное состояние в обеих областях.
    expect(screen.getAllByText(ENV_LOST_TEXT, { exact: false }).length).toBeGreaterThan(0);
    expect(screen.queryByText(FORBIDDEN_TEXT)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: REOPEN_BUTTON }),
    ).toBeInTheDocument();
  });

  it("deep-link run (?run=) + 404: безальтернативное «Доступ запрещён» сохраняется (uniform-404 не ослаблен), кнопки нет", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="link" />);

    await waitFor(() => {
      expect(screen.getByText(FORBIDDEN_TEXT)).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: REOPEN_BUTTON })).not.toBeInTheDocument();
  });

  it("проп runIdSource не передан (встроенные вызовы): прежний контракт «Доступ запрещён»", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    render(<DocumentationWorkspace runId="RUN-A" />);

    await waitFor(() => {
      expect(screen.getByText(FORBIDDEN_TEXT)).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
  });

  it("session-resolved run + 403: «Доступ запрещён» (только 404 трактуется как потеря среды)", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 403 });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByText(FORBIDDEN_TEXT)).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
  });

  it("session-resolved run + сеть недоступна: прежний offline-статус", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: null });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(
        screen.getByText("Сервис документирования недоступен — повторите попытку позже"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
  });

  it("кнопка «Открыть текущее исследование»: trace вернул текущий run -> список перечитан для него", async () => {
    mocked.listDocuments
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { run_id: "RUN-B", documents: [] },
      });
    mocked.resolveCurrentRun.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-B" },
    });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: REOPEN_BUTTON })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: REOPEN_BUTTON }));

    await waitFor(() => {
      expect(
        screen.getByText("Документов пока нет — соберите черновик нужного вида"),
      ).toBeInTheDocument();
    });
    expect(mocked.listDocuments.mock.calls.map((call) => call[0])).toEqual([
      "RUN-A",
      "RUN-B",
    ]);
  });

  it("кнопка: trace вернул ТОТ ЖЕ run -> список явно перечитан (без застревания)", async () => {
    mocked.listDocuments
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { run_id: "RUN-A", documents: [] },
      });
    mocked.resolveCurrentRun.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-A" },
    });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: REOPEN_BUTTON })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: REOPEN_BUTTON }));

    await waitFor(() => {
      expect(
        screen.getByText("Документов пока нет — соберите черновик нужного вида"),
      ).toBeInTheDocument();
    });
    expect(mocked.listDocuments).toHaveBeenCalledTimes(2);
  });

  it("кнопка: trace вернул run_id null -> честное no-run («Исследование не выбрано»)", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    mocked.resolveCurrentRun.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: null },
    });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: REOPEN_BUTTON })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: REOPEN_BUTTON }));

    await waitFor(() => {
      expect(
        screen.getByText(/Исследование не выбрано — откройте раздел из исследования/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
  });

  it("кнопка: trace недоступен (сеть) -> offline-статус", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    mocked.resolveCurrentRun.mockResolvedValue({ ok: false, status: null });
    render(<DocumentationWorkspace runId="RUN-A" runIdSource="session" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: REOPEN_BUTTON })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: REOPEN_BUTTON }));

    await waitFor(() => {
      expect(
        screen.getByText("Сервис документирования недоступен — повторите попытку позже"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(ENV_LOST_TEXT)).not.toBeInTheDocument();
  });

  it("«Создать черновик» заблокирован в состоянии потери среды (не ready/empty)", async () => {
    mocked.listDocuments.mockResolvedValue({ ok: false, status: 404 });
    render(
      <DocumentationWorkspace runId="RUN-A" runIdSource="session" initialKind="D02" />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: REOPEN_BUTTON })).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Создать черновик/ })).toBeDisabled();
  });
});
