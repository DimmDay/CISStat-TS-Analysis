// packages/ui/components/doclog9-profiles-ui.test.tsx
//
// DOCLOG-9 (спека §12.2 «Действия», §12.3 состояния, §15, §19 строка
// DOCLOG-9 «выбранный профиль подтверждён валидатором и organisational
// policy, не названием файла»): панель выпуска по профилю организации
// в DocumentationWorkspace -- переключатели DOCX/PDF-A; панель
// Doclog9ProfileControls: загрузка активных профилей (GET
// org-profiles?format=), селект с лейблом имя·vN·организация, гарантии
// ТЕКСТОМ (валидатор/подпись/якорь/WORM), заказ рендера с
// org_profile_id, честные состояния loading/empty/forbidden/error;
// после ready -- записи валидации (passed/failed честно) и кнопка
// «Проверить подпись» (HMAC, НЕ юридическая ЭП).
//
// Оракулы на СВОИХ данных: клиенты lib/documentation мокаются; корпус
// дизъюнктен серверным репо-сюитам (tests/api).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  DocumentationWorkspace,
} from "./DocumentationWorkspace";
import { Doclog9ProfileControls } from "./Doclog9ProfileControls";
import * as documentation from "../lib/documentation";

jest.mock("../lib/documentation", () => {
  const actual = jest.requireActual("../lib/documentation");
  return {
    ...actual,
    listDocuments: jest.fn(),
    getRevision: jest.fn(),
    getLifecycle: jest.fn(),
    requestApproval: jest.fn(),
    decideApproval: jest.fn(),
    publishRevision: jest.fn(),
    retractRevision: jest.fn(),
    getRevisionDiff: jest.fn(),
    requestRendition: jest.fn(),
    createDraft: jest.fn(),
    cancelJob: jest.fn(),
    getJob: jest.fn(),
    listOrgProfiles: jest.fn(),
    getRenditionValidations: jest.fn(),
    verifyRenditionSignature: jest.fn(),
  };
});

const mockedDocumentation = documentation as jest.Mocked<typeof documentation>;

const RUN_ID = "RUN-D9B00001";
const PROFILE_ID = "prof-d9bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function d9Document(): documentation.DocumentSummary {
  return {
    document_id: "doc-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
    run_id: RUN_ID,
    kind_code: "D01",
    title: "План исследования",
    current_revision_id: "drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    created_by: null,
    created_at: "2026-10-24T10:00:00Z",
    revisions: [
      {
        revision_id: "drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        document_id: "doc-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
        snapshot_id: "rs-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        run_id: RUN_ID,
        version_no: 1,
        created_by: null,
        created_at: "2026-10-24T10:00:00Z",
        lifecycle_state: "draft",
        renditions: [],
      },
    ],
  };
}

function d9Snapshot(): documentation.SnapshotPayload {
  return {
    snapshot_id: "rs-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    research_run_id: RUN_ID,
    context_id: "ctx-d9-1",
    data_revision: 2,
    captured_at: "2026-10-24T10:00:00Z",
    classification: "internal",
    redaction_profile: "default",
    knowledge_version: null,
    template: { id: "default", version: 1 },
    completeness: { status: "complete", missing_refs: [] },
    reproducibility: { status: "replayable", reasons: [] },
    sections: [
      {
        code: "D01",
        title: "План",
        claims: [
          {
            text: "План согласован",
            event_refs: [],
            result_refs: [],
            validity: "valid",
            evidence_level: "server_result",
          },
        ],
      },
    ],
  } as unknown as documentation.SnapshotPayload;
}

function d9Profile(): documentation.OrgProfileSummary {
  return {
    profile_id: PROFILE_ID,
    schema_version: "doclog.org_profile/1",
    name: "гост-профиль",
    version_no: 2,
    format: "pdfa",
    status: "active",
    language: "ru",
    title_prefix: "CISStat",
    footer_text: "проверено",
    organization: "СтатКомитет",
    validate_conformance: true,
    sign_contents: true,
    anchor_registry: false,
    worm_lock: true,
    created_by: null,
    created_at: "2026-10-24T09:00:00Z",
    retired_by: null,
    retired_at: null,
  };
}

function d9Job(state: string): documentation.JobPayload {
  return {
    job_id: "djob-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    run_id: RUN_ID,
    snapshot_id: "rs-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    format: "pdfa",
    redaction_profile: "default",
    revision_id: "drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    rendition_id: state === "ready" ? "rend-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" : null,
    state: state as documentation.JobState,
    error_code: null,
    attempt: 1,
    created_at: "2026-10-24T10:01:00Z",
    updated_at: "2026-10-24T10:02:00Z",
    rendition: null,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("DOCLOG-9: панель выпуска по профилю организации", () => {
  it("загружает активные профили, показывает селект и гарантии текстом", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: true,
      status: 200,
      data: { profiles: [d9Profile()], count: 1 },
    });
    render(<Doclog9ProfileControls format="pdfa" activeRevisionId="drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />);

    await waitFor(() => {
      expect(mockedDocumentation.listOrgProfiles).toHaveBeenCalledWith("pdfa");
    });
    const select = await screen.findByTestId("doclog9-profile-select");
    // Лейбл имени/версии/организации -- в опции селекта.
    expect(screen.getByText(/гост-профиль · v2 · СтатКомитет/)).toBeInTheDocument();
    // Гарантии профиля -- текстом (цвет не единственный носитель).
    expect(
      screen.getByText(/Гарантии: валидатор, подпись \(HMAC, не юридическая ЭП\), WORM-холд\./),
    ).toBeInTheDocument();
    expect(screen.getByTestId("doclog9-order-button")).toBeEnabled();
  });

  it("пустое состояние -- честный текст без селекта", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: true,
      status: 200,
      data: { profiles: [], count: 0 },
    });
    render(<Doclog9ProfileControls format="docx" activeRevisionId={null} />);
    await waitFor(() => {
      expect(screen.getByText(/Активных профилей для DOCX нет/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("doclog9-profile-select")).toBeNull();
  });

  it("404/403 -- различимое честное состояние запрета", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: false,
      status: 404,
    });
    render(<Doclog9ProfileControls format="pdfa" activeRevisionId={null} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/недоступны для этого запроса/);
    });
  });

  it("иная ошибка сервиса -- честное состояние недоступности", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: false,
      status: 500,
    });
    render(<Doclog9ProfileControls format="pdfa" activeRevisionId={null} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Сервис профилей недоступен/);
    });
  });

  it("заказ рендера уходит с выбранным org_profile_id; после ready -- записи валидации честно", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: true,
      status: 200,
      data: { profiles: [d9Profile()], count: 1 },
    });
    mockedDocumentation.requestRendition.mockResolvedValue({
      ok: true,
      status: 202,
      data: { job: d9Job("ready"), status_url: "/v1/documentation/jobs/x" },
    });
    mockedDocumentation.getRenditionValidations.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        validations: [
          {
            validation_id: "val-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            rendition_id: "rend-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            job_id: "djob-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            run_id: RUN_ID,
            profile_id: PROFILE_ID,
            profile_version_no: 2,
            format: "pdfa",
            validator: "pdfa-structural/1",
            result: "passed",
            findings: ["все маркеры PDF/A-1b на месте"],
            signature_manifest: null,
            checked_at: "2026-10-24T10:02:00Z",
          },
        ],
        count: 1,
      },
    });
    render(<Doclog9ProfileControls format="pdfa" activeRevisionId="drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />);
    fireEvent.click(await screen.findByTestId("doclog9-order-button"));

    await waitFor(() => {
      expect(mockedDocumentation.requestRendition).toHaveBeenCalledWith(
        "drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "pdfa",
        { org_profile_id: PROFILE_ID },
      );
    });
    await waitFor(() => {
      expect(mockedDocumentation.getRenditionValidations).toHaveBeenCalledWith(
        "rend-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      );
    });
    expect(screen.getByTestId("doclog9-validations")).toHaveTextContent(
      "pdfa-structural/1 — пройдена: все маркеры PDF/A-1b на месте",
    );
  });

  it("проверка подписи: passed -- с честной оговоркой «не юридическая ЭП»", async () => {
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: true,
      status: 200,
      data: { profiles: [d9Profile()], count: 1 },
    });
    mockedDocumentation.requestRendition.mockResolvedValue({
      ok: true,
      status: 202,
      data: { job: d9Job("ready"), status_url: "/v1/documentation/jobs/x" },
    });
    mockedDocumentation.getRenditionValidations.mockResolvedValue({
      ok: true,
      status: 200,
      data: { validations: [], count: 0 },
    });
    mockedDocumentation.verifyRenditionSignature.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        verification: {
          validator: "signature/1",
          result: "passed",
          findings: ["algorithm=HMAC-SHA256"],
        },
      },
    });
    render(<Doclog9ProfileControls format="pdfa" activeRevisionId="drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />);
    fireEvent.click(await screen.findByTestId("doclog9-order-button"));
    fireEvent.click(await screen.findByText("Проверить подпись"));

    await waitFor(() => {
      expect(mockedDocumentation.verifyRenditionSignature).toHaveBeenCalledWith(
        "rend-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      );
    });
    expect(screen.getByText(/совпадает с байтами \(HMAC\)/)).toBeInTheDocument();
    expect(screen.getByText(/не является юридической электронной подписью/)).toBeInTheDocument();
  });
});

describe("DOCLOG-9: переключатели профилей в DocumentationWorkspace", () => {
  function setupWorkspace() {
    mockedDocumentation.listDocuments.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: RUN_ID, documents: [d9Document()] },
    });
    mockedDocumentation.getRevision.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        revision: d9Document().revisions[0],
        document: d9Document(),
        snapshot: d9Snapshot(),
        renditions: [],
      },
    });
    mockedDocumentation.getLifecycle.mockResolvedValue({
      ok: true,
      status: 200,
      data: { revision_id: "drev-d9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", records: [] },
    });
    mockedDocumentation.listOrgProfiles.mockResolvedValue({
      ok: true,
      status: 200,
      data: { profiles: [d9Profile()], count: 1 },
    });
    render(<DocumentationWorkspace runId={RUN_ID} />);
  }

  it("кнопки DOCX/PDF-A открывают и скрывают панель профиля", async () => {
    setupWorkspace();
    const previewReady = await screen.findByText(/Собрать формат:/);
    expect(previewReady).toBeInTheDocument();
    // Панель скрыта до переключения.
    expect(screen.queryByTestId("doclog9-profile-panel")).toBeNull();

    fireEvent.click(screen.getByTestId("doclog9-profile-toggle-docx"));
    await waitFor(() => {
      expect(screen.getByTestId("doclog9-profile-panel")).toBeInTheDocument();
    });
    expect(mockedDocumentation.listOrgProfiles).toHaveBeenCalledWith("docx");

    // Повторный клик -- панель скрыта (toggle).
    fireEvent.click(screen.getByTestId("doclog9-profile-toggle-docx"));
    await waitFor(() => {
      expect(screen.queryByTestId("doclog9-profile-panel")).toBeNull();
    });
  });

  it("PDF-A переключатель показывает панель с загрузкой pdfa-профилей", async () => {
    setupWorkspace();
    await screen.findByText(/Собрать формат:/);
    fireEvent.click(screen.getByTestId("doclog9-profile-toggle-pdfa"));
    await waitFor(() => {
      expect(screen.getByTestId("doclog9-profile-panel")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(mockedDocumentation.listOrgProfiles).toHaveBeenCalledWith("pdfa");
    });
  });
});
