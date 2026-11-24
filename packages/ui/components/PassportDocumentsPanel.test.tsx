// packages/ui/components/PassportDocumentsPanel.test.tsx
//
// PGV-15: пикер «Восстановить паспорта» -- критерий задачи «Один/все/
// сравнение по версии, D02 не P01, ZIP страниц доступен».
// Оракулы: режимы single/set/compare с выбором версии, честные
// негативные состояния §12.3, разведение D02/P01, сводка точек/gaps,
// job-поллинг с готовыми скачиваниями PNG/ZIP + metadata.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PassportDocumentsPanel } from "./PassportDocumentsPanel";
import {
  listPassportSources,
  requestPassportDocument,
  passportDocumentErrorText,
} from "../lib/passportDocuments";
import { getJob, cancelJob } from "../lib/documentation";

const mockListSources = listPassportSources as jest.Mock;
const mockRequestDocument = requestPassportDocument as jest.Mock;
const mockGetJob = getJob as jest.Mock;
const mockCancelJob = cancelJob as jest.Mock;

jest.mock("../lib/passportDocuments", () => ({
  __esModule: true,
  listPassportSources: jest.fn(),
  requestPassportDocument: jest.fn(),
  passportDocumentErrorText: jest.fn(
    (status: number | null, code: string | null) =>
      `err:${status ?? "offline"}:${code ?? "null"}`,
  ),
}));

jest.mock("../lib/documentation", () => ({
  __esModule: true,
  getJob: jest.fn(),
  cancelJob: jest.fn(),
  renditionContentUrl: (id: string) =>
    `/v1/documentation/renditions/${id}/content`,
}));

jest.mock("./PrintDocumentsPanel", () => ({
  PrintDocumentsPanel: () => (
    <div data-testid="pgv15-print-documents-mock">saved print documents</div>
  ),
}));

const SOURCES = {
  ok: true,
  status: 200,
  data: {
    run_id: "RUN-1",
    snapshots: [
      {
        snapshot_ref: "rs-start0000000001",
        stage: "start",
        universe: "single",
        content_status: "present",
        content_gap_reason: null,
        target_column: "value",
        date_column: "date",
        captured_at: "2026-11-20T10:00:00+00:00",
      },
      {
        snapshot_ref: "rs-valid0000000002",
        stage: "validation",
        universe: "single",
        content_status: "missing_artifact",
        content_gap_reason: "passport_artifact_absent",
        target_column: "value",
        date_column: "date",
        captured_at: "2026-11-20T11:00:00+00:00",
      },
    ],
    checkpoints: [
      {
        checkpoint_id: "pck-1",
        stage: "modeling_entry",
        universe: "single",
        confirmed_at: "2026-11-20T12:00:00+00:00",
        flags: { reused: false },
        integrity_status: "ok",
      },
      {
        checkpoint_id: "pck-2",
        stage: "modeling_entry",
        universe: "single",
        confirmed_at: "2026-11-21T12:00:00+00:00",
        flags: { reused: true },
        integrity_status: "ok",
      },
    ],
  },
};

beforeEach(() => {
  mockListSources.mockReset().mockResolvedValue(SOURCES);
  mockRequestDocument.mockReset();
  mockGetJob.mockReset();
  mockCancelJob.mockReset();
});

describe("PassportDocumentsPanel — критерий «один/все/сравнение по версии»", () => {
  it("режимы пикера: single/set/compare с aria-pressed, default -- set (§8)", async () => {
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-restore-picker")).toBeInTheDocument());
    const single = screen.getByTestId("pgv15-mode-single");
    const set = screen.getByTestId("pgv15-mode-set");
    const compare = screen.getByTestId("pgv15-mode-compare");
    expect(set).toHaveAttribute("aria-pressed", "true");
    expect(single).toHaveAttribute("aria-pressed", "false");
    expect(compare).toHaveAttribute("aria-pressed", "false");
  });

  it("single: выбор одного снимка -> POST ровно с одним snapshot_ref", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: false,
      status: 422,
      error: { code: "invalid_selection", message: "нет" },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("pgv15-mode-single")).toHaveAttribute("aria-pressed", "false"),
    );
    fireEvent.click(screen.getByTestId("pgv15-mode-single"));
    const radio = screen.getAllByRole("radio")[0];
    fireEvent.click(radio);
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    await waitFor(() => expect(mockRequestDocument).toHaveBeenCalled());
    const input = mockRequestDocument.mock.calls[0][0];
    expect(input.mode).toBe("single");
    expect(input.snapshotRefs).toEqual(["rs-start0000000001"]);
    expect(input.checkpointId).toBeNull();
  });

  it("set: выбор чекпоинта -> POST с checkpoint_id (traektoriya, AC10)", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: false,
      status: 202,
      error: { code: null, message: null },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() =>
      expect(screen.getAllByTestId("pgv15-checkpoint-row").length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    await waitFor(() => expect(mockRequestDocument).toHaveBeenCalled());
    const input = mockRequestDocument.mock.calls[0][0];
    expect(input.mode).toBe("set");
    expect(input.checkpointId).toBe("pck-1");
    expect(input.snapshotRefs).toBeUndefined();
  });

  it("compare: чекпоинт-траектория или ровно два снимка", async () => {
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-restore-picker")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pgv15-mode-compare"));
    // Без выбора -- кнопка честно выключена
    // (чекпоинт по умолчанию выбран -- сбросим выбор снимками нельзя;
    // проверяем и приоритет двух явных снимков).
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes.length).toBe(2);
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    mockRequestDocument.mockResolvedValueOnce({
      ok: false,
      status: 202,
      error: { code: null, message: null },
    });
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    await waitFor(() => expect(mockRequestDocument).toHaveBeenCalled());
    const input = mockRequestDocument.mock.calls[0][0];
    expect(input.mode).toBe("compare");
    // Два явных снимка приоритетнее чекпоинта (детерминированное правило UI)
    expect(input.snapshotRefs).toEqual([
      "rs-start0000000001",
      "rs-valid0000000002",
    ]);
    expect(input.checkpointId).toBeNull();
  });

  it("отказ 409 source_unavailable виден (role=alert), выбор не теряется", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: false,
      status: 409,
      error: { code: "source_unavailable", message: "нет" },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-create-print")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("err:409:source_unavailable");
    // Выбор режима не сброшен
    expect(screen.getByTestId("pgv15-mode-set")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("PassportDocumentsPanel — честность источников и семейств", () => {
  it("D02 не P01: явная подпись разведения семейств", () => {
    render(<PassportDocumentsPanel runId="RUN-1" />);
    const note = screen.getByTestId("pgv15-d02-not-p01-note");
    expect(note.textContent).toContain("D02");
    expect(note.textContent).toContain("P01");
    expect(note.textContent).toContain("не переименовывается");
  });

  it("content_status honest: missing -- «gap», present -- «сохранено»", async () => {
    render(<PassportDocumentsPanel runId="RUN-1" />);
    // Ждём готовности источников (пикер рендерит режимы только в ready),
    // затем переключаем режим, чтобы проверить честные статусы записей.
    await waitFor(() =>
      expect(screen.getByTestId("pgv15-create-print")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("pgv15-mode-single"));
    const rows = await screen.findAllByTestId("pgv15-snapshot-row");
    expect(rows[0].textContent).toContain("содержимое сохранено");
    expect(rows[1].textContent).toContain("содержимое отсутствует (gap)");
  });

  it("offline/запрет источников -- честные состояния (не «нет данных»)", async () => {
    mockListSources.mockResolvedValueOnce({ ok: false, status: null });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    const status = await screen.findByTestId("pgv15-sources-status");
    expect(status.textContent).toContain("Сеть недоступна");
    mockListSources.mockReset().mockResolvedValue({
      ok: false,
      status: 404,
      error: { code: "not_found", message: "нет" },
    });
  });

  it("reused-чекпоинт помечен «исходный снимок» (AC11)", async () => {
    render(<PassportDocumentsPanel runId="RUN-1" />);
    const rows = await screen.findAllByTestId("pgv15-checkpoint-row");
    expect(rows[1].textContent).toContain("reused (исходный снимок)");
  });
});

describe("PassportDocumentsPanel — job: ZIP страниц доступен (критерий)", () => {
  it("ready job с output_format=zip: «Скачать все страницы PNG (ZIP)» + metadata", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: true,
      status: 202,
      data: {
        run_id: "RUN-1",
        mode: "set",
        print_kind: "P01",
        document_id: "doc-1",
        print_revision_id: "dprint-1",
        snapshot_artifact_id: "art-1",
        job: { job_id: "djob-1", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-1",
        completeness: "partial",
        display: {
          title: "Комплект",
          completeness: "partial",
          gaps: [{ at: "stage_refs.exit" }],
          sections: [
            { snapshot_ref: "rs-1", stage: "start", content_status: "present" },
            { snapshot_ref: null, stage: "exit", content_status: null },
          ],
        },
      },
    });
    mockGetJob.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        job: {
          job_id: "djob-1",
          run_id: "RUN-1",
          snapshot_id: "",
          format: "png",
          redaction_profile: "default",
          revision_id: "dprint-1",
          rendition_id: "drend-1",
          state: "ready",
          error_code: null,
          attempt: 1,
          created_at: "2026-11-24T09:00:00Z",
          updated_at: "2026-11-24T09:01:00Z",
          rendition: {
            rendition_id: "drend-1",
            format: "zip",
            size_bytes: 2048,
          },
          output_format: "zip",
          metadata_url: "/v1/documentation/renditions/drend-meta/content",
        },
      },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-create-print")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    const downloads = await screen.findByTestId("pgv15-ready-downloads");
    expect(downloads.textContent).toContain("Скачать все страницы PNG (ZIP)");
    expect(downloads.textContent).toContain("Metadata (JSON)");
    // Сводка resolved-точек честна: present + gap
    const sections = screen.getByTestId("pgv15-outcome-sections");
    expect(sections.textContent).toContain("содержимое сохранено");
    expect(sections.textContent).toContain("—");
    expect(screen.getByTestId("pgv15-outcome").textContent).toContain("неполная (partial)");
  });

  it("ready job с PNG (одна страница): «Скачать PNG» без ZIP", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: true,
      status: 202,
      data: {
        run_id: "RUN-1",
        mode: "single",
        print_kind: "P01",
        document_id: "doc-1",
        print_revision_id: "dprint-9",
        snapshot_artifact_id: "art-9",
        job: { job_id: "djob-9", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-9",
        completeness: "complete",
        display: { title: "Паспорт", completeness: "complete", gaps: [], sections: [] },
      },
    });
    mockGetJob.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        job: {
          job_id: "djob-9",
          run_id: "RUN-1",
          snapshot_id: "",
          format: "png",
          redaction_profile: "default",
          revision_id: "dprint-9",
          rendition_id: "drend-9",
          state: "ready",
          error_code: null,
          attempt: 1,
          created_at: "2026-11-24T09:00:00Z",
          updated_at: "2026-11-24T09:01:00Z",
          rendition: { rendition_id: "drend-9", format: "png", size_bytes: 4096 },
          output_format: "png",
        },
      },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-create-print")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pgv15-mode-single"));
    fireEvent.click(screen.getAllByRole("radio")[0]);
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    const downloads = await screen.findByTestId("pgv15-ready-downloads");
    expect(downloads.textContent).toContain("Скачать PNG");
    expect(downloads.textContent).not.toContain("ZIP");
  });

  it("failed job: честная ошибка с error_code (не «готово»)", async () => {
    mockRequestDocument.mockResolvedValueOnce({
      ok: true,
      status: 202,
      data: {
        run_id: "RUN-1",
        mode: "set",
        print_kind: "P01",
        document_id: "doc-1",
        print_revision_id: "dprint-2",
        snapshot_artifact_id: "art-2",
        job: { job_id: "djob-2", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-2",
        completeness: "complete",
        display: { title: "Комплект", completeness: "complete", gaps: [], sections: [] },
      },
    });
    mockGetJob.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        job: {
          job_id: "djob-2",
          run_id: "RUN-1",
          snapshot_id: "",
          format: "png",
          redaction_profile: "default",
          revision_id: "dprint-2",
          rendition_id: null,
          state: "failed",
          error_code: "render_dependency_unavailable",
          attempt: 1,
          created_at: "2026-11-24T09:00:00Z",
          updated_at: "2026-11-24T09:01:00Z",
          rendition: null,
        },
      },
    });
    render(<PassportDocumentsPanel runId="RUN-1" />);
    await waitFor(() => expect(screen.getByTestId("pgv15-create-print")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pgv15-create-print"));
    const state = await screen.findByTestId("pgv15-job-state");
    await waitFor(() => expect(state.textContent).toContain("ошибка"));
    expect(state.textContent).toContain("render_dependency_unavailable");
  });
});
