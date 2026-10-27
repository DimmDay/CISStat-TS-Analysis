// packages/ui/components/documentation-new-tab-action.test.tsx
//
// Task ID: DOCLOG-DL-FIX-1 (2026-10-27) -- вариант C на ядре A
// (рекомендация из разбора docs/doclog_download_behavior_2026-10-27.md;
// сценарий тимлида: «Собрать формат:» → «Скачать MD/HTML/JSON»).
//
// КОНТРАКТ доставки документа (разведение действий, честность подписей
// -- тот же класс, что C09/F-D8C1):
//
//   1. «Скачать X» (doclog4-rendition-link) -- ссылка на content-маршрут
//      БЕЗ target/download-атрибутов: семантику скачивания несёт бэкенд
//      Content-Disposition: attachment (ядро A; одинаково работает в
//      same-origin прокси и dev-кросс-домене; blob-хаки на фронте не
//      дублируются). Пин защищает от регрессии к client-side хакам.
//   2. «Открыть в новой вкладке» (doclog4-open-in-new-tab) -- ссылка на
//      САНИТИЗИРОВАННЫЙ preview-маршрут (GET /revisions/{id}/preview,
//      inline + AC16) с target="_blank" rel="noopener noreferrer":
//      просмотр рендера без потери workspace (сценарий аналитика
//      длинный; переход в той же вкладке убивал состояние). Это
//      просмотр, НЕ скачивание -- потому и не content-маршрут: при
//      attachment на content-маршруте target="_blank" на него дал бы
//      скачивание в новой вкладке, а не просмотр.
//   3. Действие показывается только когда версия выбрана и прочитана
//      (previewPhase === "ready") -- иначе открывать нечего; на
//      пустом списке документов его нет (честное отсутствие).

import { render, screen } from "@testing-library/react";
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
  renditionContentUrl: (id: string) =>
    `/v1/documentation/renditions/${id}/content`,
  revisionPreviewUrl: (id: string) =>
    `/v1/documentation/revisions/${id}/preview`,
}));

import * as documentation from "../lib/documentation";

const mocked = documentation as jest.Mocked<typeof documentation>;

// Форма данных -- контракт lib/documentation.ts; касты any только в
// тестовых фикстурах (DOM-ассерты -- предмет теста, не типы).
const REVISION = {
  revision_id: "REV-1",
  document_id: "DOC-1",
  snapshot_id: "SNAP-1",
  run_id: "RUN-A",
  version_no: 1,
  created_by: "owner-v1",
  created_at: "2026-10-27T09:00:00Z",
  captured_at: "2026-10-27T09:00:00Z",
  completeness_status: "full",
  lifecycle_state: "draft",
  renditions: [],
};

const DOCUMENT = {
  document_id: "DOC-1",
  run_id: "RUN-A",
  kind_code: "D02",
  title: "Паспорт источника",
  current_revision_id: "REV-1",
  created_by: "owner-v1",
  created_at: "2026-10-27T09:00:00Z",
  revisions: [REVISION],
};

const SNAPSHOT = {
  schema_version: "doclog.snapshot/1",
  snapshot_id: "SNAP-1",
  research_run_id: "RUN-A",
  context_id: null,
  data_revision: null,
  data_ref: null,
  data_digest: null,
  source_cutoff: {},
  captured_at: "2026-10-27T09:00:00Z",
  template: { id: "D02", version: "1" },
  knowledge_version: "k-1",
  classification: "internal",
  redaction_profile: "P0",
  sections: [],
  completeness: { status: "full", missing_refs: [] },
  reproducibility: { status: "reproducible" },
};

const rendition = (id: string, format: string) => ({
  rendition_id: id,
  revision_id: "REV-1",
  snapshot_id: "SNAP-1",
  run_id: "RUN-A",
  format,
  redaction_profile: "P0",
  state: "ready",
  media_type: format === "md" ? "text/markdown" : "text/html",
  size_bytes: 1266,
  content_sha256: "a".repeat(64),
  storage_key: `k-${id}`,
  job_id: null,
});

const ok = (data: unknown) =>
  ({ ok: true, status: 200, data }) as any;

beforeEach(() => {
  jest.resetAllMocks();
  mocked.getLifecycle.mockResolvedValue(ok({ records: [] }) as any);
});

describe("DocumentationWorkspace — доставка документов (DOCLOG-DL-FIX-1, вариант C на ядре A)", () => {
  it("выбранная версия: «Открыть в новой вкладке» ведёт на санитизированный preview (target=_blank, noopener noreferrer), «Скачать X» -- без target/download (семантику скачивания несёт attachment бэкенда)", async () => {
    mocked.listDocuments.mockResolvedValue(
      ok({ run_id: "RUN-A", documents: [DOCUMENT] }),
    );
    mocked.getRevision.mockResolvedValue(
      ok({
        revision: REVISION,
        document: DOCUMENT,
        snapshot: SNAPSHOT,
        renditions: [rendition("R-MD-1", "md"), rendition("R-HTML-1", "html")],
      }),
    );

    render(<DocumentationWorkspace runId="RUN-A" />);

    // Последняя версия выбирается автоматически (автопин последней v*) --
    // ждём действия новой вкладки как признак preview-ready.
    const newTab = await screen.findByTestId("doclog4-open-in-new-tab");
    expect(screen.getByRole("link", { name: /открыть в новой вкладке/i })).toBeInTheDocument();
    expect(newTab).toHaveAttribute("target", "_blank");
    const rel = newTab.getAttribute("rel") ?? "";
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
    // Просмотр -- САНИТИЗИРОВАННЫЙ preview-маршрут (inline оправдан),
    // не content-маршрут.
    expect(newTab).toHaveAttribute(
      "href",
      "/v1/documentation/revisions/REV-1/preview",
    );

    // «Скачать X» -- href на content-маршрут, БЕЗ target/download:
    // файл сохраняется по Content-Disposition: attachment бэкенда
    // (ядро A); клиентские blob/target-хаки не дублируются.
    const downloadLinks = screen.getAllByTestId("doclog4-rendition-link");
    expect(downloadLinks).toHaveLength(2);
    for (const link of downloadLinks) {
      expect(link.getAttribute("href")).toContain("/renditions/");
      expect(link.getAttribute("href")).toContain("/content");
      expect(link).not.toHaveAttribute("target");
      expect(link).not.toHaveAttribute("download");
    }
  });

  it("пустой список документов: действия нет (нечего открывать и скачивать) -- честное отсутствие", async () => {
    mocked.listDocuments.mockResolvedValue(
      ok({ run_id: "RUN-A", documents: [] }),
    );

    render(<DocumentationWorkspace runId="RUN-A" />);

    await screen.findByTestId("doclog4-status");
    expect(screen.queryByTestId("doclog4-open-in-new-tab")).not.toBeInTheDocument();
    expect(screen.queryByTestId("doclog4-rendition-link")).not.toBeInTheDocument();
  });
});
