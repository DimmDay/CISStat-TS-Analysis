// packages/ui/components/PrintDocumentsPanel.test.tsx
//
// PGV-15: листинг сохранённых печатных документов (V01/P01/P02) --
// «ZIP страниц доступен», честные состояния §12.3, предпросмотр
// соответствует скачиваемой версии (PNG -- как есть; ZIP -- состав из
// frozen metadata), replay «Запросить PNG» без дублей (AC09).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PrintDocumentsPanel } from "./PrintDocumentsPanel";
import {
  listPrintDocuments,
  requestPrintRendition,
} from "../lib/passportDocuments";
import { getJob } from "../lib/documentation";
import { apiFetch } from "../lib/browserTransport";

const mockListDocuments = listPrintDocuments as jest.Mock;
const mockRequestRendition = requestPrintRendition as jest.Mock;
const mockGetJob = getJob as jest.Mock;
const mockApiFetch = apiFetch as jest.Mock;

jest.mock("../lib/passportDocuments", () => ({
  __esModule: true,
  listPrintDocuments: jest.fn(),
  requestPrintRendition: jest.fn(),
  passportDocumentErrorText: jest.fn(
    (status: number | null) => `err:${status ?? "offline"}`,
  ),
}));

jest.mock("../lib/documentation", () => ({
  __esModule: true,
  getJob: jest.fn(),
  renditionContentUrl: (id: string) =>
    `/v1/documentation/renditions/${id}/content`,
}));

jest.mock("../lib/browserTransport", () => ({
  apiFetch: jest.fn(),
}));

const blobUrlSpy = jest.fn();
beforeAll(() => {
  // jsdom: URL.createObjectURL отсутствует -- стаб.
  Object.defineProperty(globalThis.URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: (blob: unknown) => `blob:preview-${(blob as { size: number }).size}`,
  });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: () => undefined,
  });
});

function documentPayload(family: "passports" | "visuals", withRenditions: boolean) {
  const kind = family === "passports" ? "P01" : "V01";
  return {
    ok: true,
    status: 200,
    data: {
      run_id: "RUN-1",
      documents: [
        {
          document_id: "doc-1",
          run_id: "RUN-1",
          print_kind: kind,
          family,
          kind_title: kind === "P01" ? "Паспорта свойств ряда" : "Научная визуализация",
          created_by: null,
          created_at: "2026-11-24T08:00:00Z",
          revisions: [
            {
              print_revision_id: "dprint-1",
              version_no: 1,
              profile_id: "figure-landscape",
              basis_kind: kind === "P01" ? "passport_print_snapshot" : "visual_print_snapshot",
              basis_artifact_ids: ["art-1"],
              basis_fingerprint: "fp-1",
              created_by: null,
              created_at: "2026-11-24T08:00:00Z",
              renditions: withRenditions
                ? [
                    {
                      rendition_id: "drend-1",
                      format: "zip",
                      redaction_profile: "default",
                      state: "ready",
                      media_type: "application/zip",
                      size_bytes: 2048,
                      content_sha256: "a".repeat(64),
                      job_id: "djob-1",
                      created_at: "2026-11-24T08:01:00Z",
                    },
                    {
                      rendition_id: "drend-1-meta",
                      format: "json",
                      redaction_profile: "default",
                      state: "ready",
                      media_type: "application/json",
                      size_bytes: 256,
                      content_sha256: "b".repeat(64),
                      job_id: "djob-1",
                      created_at: "2026-11-24T08:01:00Z",
                    },
                  ]
                : [],
            },
          ],
        },
      ],
    },
  };
}

beforeEach(() => {
  mockListDocuments.mockReset().mockResolvedValue(documentPayload("passports", true));
  mockRequestRendition.mockReset();
  mockGetJob.mockReset();
  mockApiFetch.mockReset();
});

describe("PrintDocumentsPanel — листинг и скачивания (PGV-15)", () => {
  it("P01 с готовым ZIP: «Скачать все страницы PNG (ZIP)» + Metadata (JSON)", async () => {
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    const download = await screen.findByTestId("pgv15-download-main");
    expect(download.textContent).toContain("Скачать все страницы PNG (ZIP)");
    expect(download.getAttribute("href")).toContain("/drend-1/content");
    expect(screen.getByTestId("pgv15-download-metadata").getAttribute("href")).toContain(
      "/drend-1-meta/content",
    );
  });

  it("фильтр семейства: паспорта не показывают V01-документы и наоборот", async () => {
    const all = documentPayload("passports", false);
    (all.data!.documents as Array<Record<string, unknown>>).push({
      document_id: "doc-v01",
      run_id: "RUN-1",
      print_kind: "V01",
      family: "visuals",
      kind_title: "Научная визуализация",
      created_by: null,
      created_at: "2026-11-24T08:00:00Z",
      revisions: [],
    });
    // Один и тот же ответ сервера: панель фильтрует семейство на клиенте.
    mockListDocuments.mockResolvedValue(all);
    const { unmount } = render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    expect(await screen.findByTestId("pgv15-print-document-P01")).toBeInTheDocument();
    expect(screen.queryByTestId("pgv15-print-document-V01")).toBeNull();
    unmount();
    render(<PrintDocumentsPanel runId="RUN-1" family="visuals" />);
    expect(await screen.findByTestId("pgv15-print-document-V01")).toBeInTheDocument();
    expect(screen.queryByTestId("pgv15-print-document-P01")).toBeNull();
  });

  it("пустое семейство -- честный пустой список (не ошибка)", async () => {
    mockListDocuments.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-1", documents: [] },
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="visuals" />);
    await waitFor(() =>
      expect(screen.getByTestId("pgv15-print-documents-status").textContent).toBe(""),
    );
    expect(screen.getByText(/Сохранённых печатных визуализаций \(V01\) пока нет/)).toBeInTheDocument();
  });

  it("uniform 404 -- безальтернативный запрет (AC18), не «нет документов»", async () => {
    mockListDocuments.mockResolvedValue({
      ok: false,
      status: 404,
      error: { code: "not_found", message: "нет" },
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    const alert = await screen.findByTestId("pgv15-print-documents-error");
    expect(alert.textContent).toContain("err:404");
    expect(screen.getByTestId("pgv15-print-documents-status").textContent).toContain(
      "Доступ запрещён",
    );
  });

  it("offline -- честная фраза сети (§12.3)", async () => {
    mockListDocuments.mockResolvedValue({ ok: false, status: null });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    await waitFor(() =>
      expect(screen.getByTestId("pgv15-print-documents-status").textContent).toContain(
        "недоступен",
      ),
    );
  });
});

describe("PrintDocumentsPanel — предпросмотр соответствует скачиваемой версии", () => {
  it("ZIP не рисуется: состав страниц из frozen metadata + честная подпись", async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => ({}),
      json: async () => ({
        page_count: 3,
        profile_id: "figure-landscape",
        pages: [
          { index: 1, filename: "page-001.png", role: "P01", size_bytes: 700 },
          { index: 2, filename: "page-002.png", role: "P01", size_bytes: 700 },
          { index: 3, filename: "page-003.png", role: "P01", size_bytes: 648 },
        ],
      }),
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    fireEvent.click(await screen.findByTestId("pgv15-preview-button"));
    const preview = await screen.findByTestId("pgv15-print-preview");
    expect(screen.queryByTestId("pgv15-preview-image")).toBeNull();
    const pages = screen.getByTestId("pgv15-preview-pages");
    expect(pages.textContent).toContain("page-001.png");
    expect(pages.textContent).toContain("page-003.png");
    expect(preview.textContent).toContain("не рисуется");
  });

  it("PNG-предпросмотр рисует скачаемые байты (тот же rendition)", async () => {
    mockListDocuments.mockResolvedValue(documentPayload("passports", false));
    const payload = documentPayload("passports", true);
    (payload.data!.documents[0].revisions[0].renditions as Array<Record<string, unknown>>)[0].format = "png";
    (payload.data!.documents[0].revisions[0].renditions as Array<Record<string, unknown>>)[0].media_type = "image/png";
    mockListDocuments.mockResolvedValue(payload);
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => ({ size: 12345 }),
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    fireEvent.click(await screen.findByTestId("pgv15-preview-button"));
    const image = await screen.findByTestId("pgv15-preview-image");
    expect(image.getAttribute("src")).toBe("blob:preview-12345");
  });
});

describe("PrintDocumentsPanel — «Запросить PNG» (replay, AC09)", () => {
  it("без готовых форматов: POST print-revisions + поллинг готового job", async () => {
    mockListDocuments.mockResolvedValue(documentPayload("passports", false));
    mockRequestRendition.mockResolvedValueOnce({
      ok: true,
      status: 202,
      data: { job: { job_id: "djob-9", state: "queued" }, status_url: "/x" },
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
          revision_id: "dprint-1",
          rendition_id: "drend-9",
          state: "ready",
          error_code: null,
          attempt: 1,
          created_at: "2026-11-24T09:00:00Z",
          updated_at: "2026-11-24T09:01:00Z",
          rendition: { rendition_id: "drend-9", format: "png", size_bytes: 1024 },
          output_format: "png",
        },
      },
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    fireEvent.click(await screen.findByTestId("pgv15-request-png"));
    await waitFor(() =>
      expect(mockRequestRendition).toHaveBeenCalledWith("dprint-1", "png"),
    );
    await waitFor(() => expect(mockGetJob).toHaveBeenCalledWith("djob-9"));
  });

  it("отказ 429 quota_exceeded -- честная фраза (role=alert)", async () => {
    mockListDocuments.mockResolvedValue(documentPayload("passports", false));
    mockRequestRendition.mockResolvedValueOnce({
      ok: false,
      status: 429,
      error: { code: "quota_exceeded", message: "переполнена" },
    });
    render(<PrintDocumentsPanel runId="RUN-1" family="passports" />);
    fireEvent.click(await screen.findByTestId("pgv15-request-png"));
    const alert = await screen.findByTestId("pgv15-job-error");
    expect(alert.textContent).toContain("err:429");
  });
});
